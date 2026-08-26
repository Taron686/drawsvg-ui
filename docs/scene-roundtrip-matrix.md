# Scene roundtrip matrix

This matrix freezes the legacy `CanvasView` snapshot boundary before the
`SceneCodec` migration. `tests/test_scene_roundtrip_matrix.py` creates every
palette shape, assigns non-default geometry or shape parameters where public
setters exist, and compares JSON-safe state before and after restore.

| Shape | Geometry | Pen | Fill | Text/structure | Transform + z | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Rectangle | size, corner radii | yes | yes | custom label | yes | passing |
| Rounded Rectangle | size, corner radii | yes | yes | custom label | yes | passing |
| Split Rounded Rectangle | size, divider ratio | yes | top + bottom | n/a | yes | passing |
| Ellipse | size | yes | yes | label gap isolated | yes | base passing, label xfail |
| Circle | diameter | yes | yes | label gap isolated | yes | base passing, label xfail |
| Triangle | size | yes | yes | n/a | yes | type passing, geometry xfail |
| Diamond | size | yes | yes | custom label | yes | type passing, geometry xfail |
| Line | points | yes | n/a | arrow-head parameters | yes | passing |
| Arrow | points | yes | n/a | endpoints + arrow head | yes | passing |
| Block Arrow | size, head + shaft ratios | yes | yes | n/a | yes | type passing, geometry xfail |
| Curvy Right Bracket | size, hook ratio | yes | n/a | n/a | yes | passing |
| Text | bounding size | n/a | n/a | content, font, color, margin, alignment, direction | yes | passing |
| Folder Tree | derived bounds | n/a | n/a | nested structure | yes | passing |

Additional cases cover nested groups and legacy handle exclusion. Strict
expected failures record migration requirements without weakening the suite:

- Triangle, Diamond, and Block Arrow serialize pen-inflated bounds as their
  logical size, so geometry grows after restore;
- ellipse/circle custom labels are serialized but not restored;
- transformed nested groups change their serialized local positions;
- equal-`zValue` insertion order has no persistent representation;
- `stack_order` is absent from the legacy payload;
- explicit `KEY_TRANSIENT` marking does not exist yet (handles are excluded by
  class-name convention only).

An unexpected pass is treated as a failure so the matrix must be updated when
the corresponding contract is implemented.
