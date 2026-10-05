# drawsvg Python export contract

The Python export represents the visible drawing with standalone drawsvg 2.4.x code. It must remain executable with drawsvg and the Python standard library, without importing the editor or Qt at runtime.

This change addresses the defects verified on baseline `b1bce2531ec870725da71155a3b707876952ab98`:

- Generated drawings save well-formed SVG XML for every registered shape, diagram and free-path type, including metadata and text containing quotes, ampersands, angle brackets, Unicode and newlines. Python string quoting and XML escaping are separate requirements. Original raw text and existing safe Python-import roundtrips must remain intact.
- Visible bitmap assets, SVG assets and connectors are included with their displayed geometry, scene transforms and stacking order. Image bytes are embedded so output does not depend on files on the exporting machine. Hidden content and transient editor decorations are omitted. Export bounds include supported visible elements and their rendered effects.
- Fill gradients, soft-shadow filters, alpha, absent pens, pen dash/cap/join properties and compound-path fill rules are transferred where the editor supports them.
- Text uses the Qt layout's visual lines and positions, alignment and font styles. Metadata alone is not a substitute for visible SVG styling.
- Export preserves editor scene state and existing source-Python import behavior. Any newly unsupported import case must be disclosed explicitly in the review.

Verification executes generated Python, builds and saves drawings, parses the saved XML, and checks semantic output rather than only compilation or a nonempty SVG string. Regression tests must include mixed scenes, transformed/grouped elements and special characters.

The image tolerances in `tests/export-tools.lock` must not be weakened. The existing strict parity XFail can be removed only after its three metrics actually pass. Pixel-identical rendering across unrelated fonts and renderers is not an automatic consequence of valid XML; remaining visual deviations must be measured and disclosed.

Implementation is split into three branches (XML/text, styles/effects, assets/connectors), then integrated and reviewed as one pull request against `master`. The original checkout's unrelated Qt SVG-export changes are excluded. The pull request remains unmerged pending human review.
