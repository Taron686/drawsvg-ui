# Registry Serialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ShapeRegistry` the only serializer/restorer for registered
shapes while preserving scene metadata and the specialized bitmap, connector
and group paths.

**Architecture:** `ShapeRegistry` owns registered shape geometry, style and
type-specific data. `SceneCodec` remains responsible for IDs, layer IDs and
stack order. `CanvasView` orchestrates scene-level transforms, page ownership
and the three specialized item categories.

**Tech Stack:** Python 3.10+, PySide6, pytest, Ruff, GitNexus.

**Spec:** `docs/superpowers/specs/2026-08-31-registry-serialization-design.md`

## Global Constraints

- Run GitNexus impact analysis before editing every production symbol and warn
  before proceeding at HIGH or CRITICAL risk.
- Use TDD: write and run a failing test before each production change.
- Do not add dependencies, a codec module, or a new adapter.
- Preserve the native project schema and all existing bitmap, connector and
  group restore contracts.
- Do not commit unless the user explicitly requests it.
- Verify with targeted tests, `ruff check src tests`, `python -m compileall -q
  src`, `pytest -q`, `git diff --check` and GitNexus `detect_changes`.

---

## Files

- `src/canvas_view.py`: remove registered-shape fallback branches; retain
  scene metadata, transforms, page ownership, bitmap, group and connector
  paths.
- `src/shape_registry.py`: retain the shape-only interface; add no scene
  metadata.
- `tests/test_scene_roundtrip_matrix.py`: cover registry-only restore for all
  legacy shapes and payloads that use only `shape`.
- `tests/test_free_paths.py`: cover registry extension restore and Ctrl-drag
  clone behavior.
- `tests/test_diagram_shapes.py`: cover diagram clone behavior.
- `tests/test_document_lifecycle.py`: prove a rejected unknown shape does not
  mutate the open document.

### Task 1: Lock down registry-only serialization and cloning

**Files:**
- Modify: `tests/test_scene_roundtrip_matrix.py`
- Modify: `tests/test_free_paths.py`
- Modify: `tests/test_diagram_shapes.py`
- Modify: `src/canvas_view.py:998-1138, 2380-2480`

**Interfaces:**
- Consumes: `ShapeRegistry.serialize(item) -> dict[str, Any] | None` and
  `ShapeRegistry.restore(data) -> QGraphicsItem | None`.
- Produces: `_serialize_item(item)` and `_clone_item(item)` that route every
  registered shape through the registry while retaining scene metadata.

- [ ] **Step 1: Run the existing registry and clone regression baseline**

```python
pytest tests/test_scene_roundtrip_matrix.py tests/test_free_paths.py \
  tests/test_diagram_shapes.py tests/test_import_export_roundtrip.py -q
```

The registry-first behavior and the Ctrl-drag regression test already define
the external contract. This task is a deletion-only refactor, so do not add a
source-structure test.

- [ ] **Step 2: Verify the baseline is green before deleting branches**

Run: `python -m pytest tests/test_scene_roundtrip_matrix.py tests/test_free_paths.py tests/test_diagram_shapes.py tests/test_import_export_roundtrip.py -q`

Expected: PASS.

- [ ] **Step 3: Replace registered-shape branches with the registry path**

```python
registry_data = SHAPE_REGISTRY.serialize(item)
if registry_data is not None:
    base.update(registry_data)
else:
    # Keep only BitmapItem and GroupItem specialized serialization here.
```

```python
registered_item = SHAPE_REGISTRY.restore(data)
if registered_item is not None:
    return registered_item
# Keep only Bitmap, Group and Connector-specific restore paths below.
```

Delete legacy branches for rectangles, ellipses, polygons, lines, brackets,
text and folder trees. Keep position, transforms, layer state, UUID and page
ownership outside the registry.

- [ ] **Step 4: Route all Ctrl-drag registry shapes through the same path**

```python
registry_data = SHAPE_REGISTRY.serialize(item)
if registry_data is not None:
    clone = SHAPE_REGISTRY.restore(registry_data)
    if clone is None:
        return None
```

Preserve position, transform, rotation, scale, `zValue` and layer ID after
restoring. Call `SceneCodec._item_id(clone)` before returning it. Do not alter
the bitmap path or add group/connector cloning.

- [ ] **Step 5: Run targeted registry and clone tests**

Run: `python -m pytest tests/test_scene_roundtrip_matrix.py tests/test_free_paths.py tests/test_diagram_shapes.py tests/test_import_export_roundtrip.py -q`

Expected: PASS.

### Task 2: Reject unknown shape payloads transactionally

**Files:**
- Modify: `src/canvas_view.py:1479-1531`
- Modify: `tests/test_document_lifecycle.py`

**Interfaces:**
- Consumes: `ShapeRegistry.type_id_from_payload(data) -> str | None` and
  `CanvasView._restore_scene_state(state)`.
- Produces: a preflight validation phase that raises `ValueError` with the
  unknown `shape` or `type_id` before `clear_canvas()` runs.

- [ ] **Step 1: Write the failing transactional-load test**

```python
def test_restore_rejects_unknown_shape_without_replacing_open_scene(
    canvas_view: CanvasView,
) -> None:
    original = canvas_view.add_shape("Rectangle", QtCore.QPointF(10, 20), snap_to_grid=False)
    assert original is not None
    invalid_state = {"schema_version": 1, "items": [{"shape": "Unknown Shape"}]}

    with pytest.raises(ValueError, match="Unknown Shape"):
        canvas_view._restore_scene_state(invalid_state)

    assert original in canvas_view.scene().items()
```

- [ ] **Step 2: Run the test and verify the current destructive restore fails it**

Run: `python -m pytest tests/test_document_lifecycle.py -k unknown_shape -q`

Expected: FAIL because the current restore clears the scene before discovering
the uninstantiable payload.

- [ ] **Step 3: Add a recursive preflight before `clear_canvas()`**

```python
def _validate_restore_items(self, items: list[object]) -> None:
    for data in items:
        if not isinstance(data, Mapping) or is_connector_data(data):
            continue
        if data.get("shape") == "Group":
            self._validate_restore_items(data.get("children", []))
            continue
        if data.get("type_id") == "Bitmap" or data.get("shape") == "Bitmap":
            continue
        if SHAPE_REGISTRY.type_id_from_payload(data) is None:
            raise ValueError(f"Unsupported shape: {data.get('type_id') or data.get('shape')}")
```

Call it on normalized `state["items"]` before `clear_canvas()`. Leave
connector handling unchanged; connectors are valid only after normal items are
constructed and indexed.

- [ ] **Step 4: Run the transactional-load test**

Run: `python -m pytest tests/test_document_lifecycle.py -k unknown_shape -q`

Expected: PASS.

### Task 3: Verify compatibility and changed scope

**Files:**
- Modify only files needed by Tasks 1 and 2.

**Interfaces:**
- Consumes: the finished registry-only serialization and preflight restore.
- Produces: verification evidence and GitNexus change mapping.

- [ ] **Step 1: Run quality checks in the project virtual environment**

```powershell
& ".venv\Scripts\ruff.exe" check src tests
& ".venv\Scripts\python.exe" -m compileall -q src
& ".venv\Scripts\python.exe" -m pytest -q
git diff --check
```

- [ ] **Step 2: Inspect the final GitNexus scope**

Run: `node .gitnexus/run.cjs detect_changes --repo UI_drawsvg`

Expected: changed symbols are confined to registry serialization, scene
restore, clone behavior and their tests. Report unrelated existing worktree
changes separately; do not revert them.

- [ ] **Step 3: Review the final diff**

Run: `git diff -- src/canvas_view.py src/shape_registry.py tests/test_scene_roundtrip_matrix.py tests/test_free_paths.py tests/test_diagram_shapes.py tests/test_document_lifecycle.py`

Expected: no legacy registered-shape branches remain in `CanvasView`; bitmap,
connector and group paths remain explicit.
