# Export parity and text strategy

T-030 freezes the portable-export contract around the versioned
`tests/export-references.json` scene and the numeric tolerances in
`tests/export-tools.lock`. The reference scene contains all 13 built-in shape IDs.
The lock remains the single source of truth for the 144-dpi RGBA comparison
environment; this ticket does not relax any tolerance.

## Text strategies

`ExportRequest.text_strategy` accepts two explicit modes:

- `TextStrategy.KEEP_TEXT` preserves text nodes and font-family references.
- `TextStrategy.CONVERT_TO_PATHS` renders the scene once through Qt SVG, converts
  the resulting text nodes to glyph outlines, and supplies that same outline
  representation to SVG, PNG, and PDF. This also covers text painted internally by
  composite items rather than only `QGraphicsTextItem` instances.

PNG scaling now maps the scene onto the complete scaled pixel target. A scale of
`2.0` therefore doubles both output dimensions and rendered geometry, as required
for the locked 144-dpi comparisons.

Font substitution is detected before export. Integrators can provide
`ExportRequest.font_fallback_reporter` to surface the requested and resolved font
families in the export dialog. Without a reporter, `FontFallbackWarning` is emitted.

Export continues to restore visibility, selection, signal, and history state via
the existing temporary-state guard, which this ticket leaves unchanged.

## Current verification status

- The deterministic local SVG/PNG comparison generated with `CONVERT_TO_PATHS` for
  all 13 built-ins satisfies the locked mean-channel, different-pixel, and
  connected-component limits. The release reference run must rasterize SVG with
  the exact `resvg` binary pinned by T-005; the local Qt rasterization is not a
  substitute for that independent gate.
- SVG remains valid XML, PNG dimensions and scaling are checked, and PDF remains a
  valid multi-page Qt export. Independent PDF raster checks use the exact
  `pypdfium2` version pinned by T-005 when that isolated test dependency is
  provisioned.
- Generated drawsvg Python remains executable and continues to produce SVG, but its
  visual parity test is a strict, documented XFail and therefore a visible release
  blocker.

The measured drawsvg-Python deviations for `builtins-grid-v1` are:

| Metric | Measured | Locked maximum |
|---|---:|---:|
| Mean channel difference | 4.458377 | 1.5 |
| Different pixels | 2.577746% | 0.100000% |
| Largest 8-connected component | 0.127479% | 0.020000% |

The follow-up must repair the existing per-shape adapters in
`src/export_drawsvg.py` under their own GitNexus impact review. It must not solve the
failure by weakening the T-005 tolerances or silently replacing reference images.
Once all three metrics pass, remove the strict XFail in
`tests/test_export_parity.py` and record the reviewed reference update.
