# Registry Serialization Design

## Goal

Make `ShapeRegistry` the single module that serializes and restores every
registered shape. Remove duplicate legacy shape branches from `CanvasView`.

## Scope

- Registered built-in and extension shapes use `ShapeRegistry.serialize()` and
  `ShapeRegistry.restore()` exclusively.
- `CanvasView` remains responsible for scene orchestration and applies
  position, transform, rotation, scale, `zValue`, UUID, layer state and page
  ownership around registry payloads.
- Bitmap, connector and group items retain their existing specialized paths.
- Ctrl-drag cloning uses the registry for every registered shape and assigns a
  new UUID immediately.
- Unknown normal shape payloads are rejected before replacing the open scene.

## Non-Goals

- No new codec module or adapter.
- No change to the bitmap asset, connector binding or group restore contracts.
- No change to the serialized project schema.

## Design

`ShapeRegistry` owns geometry, style and type-specific fields. Its interface
remains `serialize(item)` and `restore(data)`.

`SceneCodec` continues to own persistent scene metadata: IDs, layers and
ordering. `CanvasView` coordinates both modules and owns scene-specific
metadata such as transforms and page ownership.

During restore, registered payloads are restored through the registry. Bitmap,
group and connector payloads use their existing dedicated paths. A payload
that identifies a normal shape but has no registry definition raises a clear
validation error before any scene mutation.

## Tests

- The existing 13-shape roundtrip matrix remains green.
- Registry extensions retain specialized geometry and style through
  save/restore and Ctrl-drag clone.
- Legacy payloads without `type_id` restore through their `shape` field.
- Unknown normal shapes fail transactionally without changing the open scene.
- Bitmap, groups and connectors keep their current regression coverage.
