# drawsvg-ui 0.7.0 integration candidate

## Sources and scope

- Public repository: `drawsvg-ui/main`, `2cd3d66` (0.6.0).
- Editor repository: `UI_drawsvg/master`, `b4f988b` (still labelled 0.3.0).
- Integration branch: `codex/integrate-ui-drawsvg-0.7.0`.

The public repository was initialized from the same Python code as
`UI_drawsvg` at `b70157a`, but has an independent Git history. This integration
records both histories as merge parents and explicitly assembles the result:
the committed editor source, tests, benchmarks and documentation are imported;
public package metadata, existing copyright notices, README, screenshot,
license file and publication workflow are retained. Internal agent rules,
generated indexes, build output and uncommitted editor changes are excluded.

## Public functionality retained

- Canvas hover outline and X markers remain view-only and clear on selection,
  leaving the view, dragging and invalidated items. Guides and connector previews
  continue to use the same foreground rendering path.
- Undo flushes a pending timer snapshot at the newest history state. Existing
  transactional capture and redo preservation remain in place.
- Python text export preserves left/center/right anchors using local coordinates
  and the current full scene transform. Import still accepts older files that
  saved alignment metadata with a start anchor.
- Stack ordering uses the newer `SceneCodec.stack_order` implementation rather
  than restoring the older parallel serializer.
- The newer selection and insertion behavior remains covered by the imported
  editor regression tests.

## Version and packaging

Package and bumpversion metadata are set to 0.7.0. All runtime modules, including
the new hover renderer, are explicitly included in the wheel. The About dialog
links to `Taron686/drawsvg-ui`. No tags, releases, pushes or publication workflow
runs are part of this integration.

## Verification

Verified on Windows with Python 3.11.0, PySide6 6.11.2 and pytest 9.1.1:

- Full suite: **340 passed, 2 skipped, 2 xfailed**, one deprecation warning.
- Nine integration cases cover pending Undo/Redo, view-only hover and invalidation,
  aligned transformed export/import, and legacy scaled/rotated text imports.
- Ruff, compileall and staged/unstaged whitespace checks pass.
- Wheel and sdist build successfully. Runtime modules, UI resources and source
  test fixtures are included. Fresh installation reports version 0.7.0 and
  `pip check` finds no dependency conflicts.
- All runtime modules import from the installed wheel. A native Windows GUI
  smoke opens/closes the installed MainWindow and renders its controls correctly.
- Independent Standards review: no confirmed new integration defect; the
  suggested legacy-import coverage was added and passes.
- Independent Spec review: no findings.
- GitNexus staged analysis: 104 files, 1,892 changed symbols and 292 affected
  flows; **critical** aggregate scope due to the full editor integration. The
  incremental integration entry-point impact checks were low risk; Qt event
  dispatch is additionally covered by tests.

The imported suite still emits pre-existing Qt slot lookup messages at process
shutdown and a deprecated QMouseEvent.pos warning. Two raster checks skip because
resvg/pypdfium2 are not provisioned; the two expected failures remain explicit.
Build tooling also warns about the inherited legacy license metadata format.
These are not reclassified as passing release gates.

Original checkout statuses were compared before/after: UI_drawsvg/master and
public drawsvg-ui/main, their local edits and remote branches are unchanged.

## Release limitations

- Existing strict expected failure: drawsvg-Python visual export parity.
- Existing expected failure: local positions in nested-group roundtrips.
- Independent raster-tool checks require provisioned resvg and pypdfium2.
- License metadata and source notices now match the owner-confirmed GPLv2
  license file: GPL-2.0-or-later, retaining the existing "or later" grant.
  The LICENSE text itself is unchanged.
- Uncommitted edits in the original `UI_drawsvg` checkout are not included.

This is a local integration candidate, not a distribution release approval.
