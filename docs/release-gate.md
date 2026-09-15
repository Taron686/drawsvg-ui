# Release gate

T-050 records the final verification boundary for the current `develop` state.
The active ticket scope is complete: DEC-01 through DEC-03 and T-001 through
T-042 are integrated. T-035B, T-035C, and T-043 are deliberately deferred and
are not part of this gate.

## Required checks

Run the following from the project root in the supported Windows Python
environment:

```powershell
python -m pytest -q
python -m ruff check .
python -m compileall -q src
git diff --check
```

The suite covers the native document lifecycle and recovery, project
validation/migration, clipboard ID remapping, connectors, embedded bitmap
assets, export parity across SVG/PNG/PDF, history limits, and package contents.
The GUI smoke is exercised by the `MainWindow` lifecycle tests; the wheel smoke
is covered by `tests/test_packaging.py`.

Before merging a release candidate, run GitNexus `detect_changes` against the
target branch and review every changed production flow. This T-050 documentation
change itself affects no production flow.

## Release decision

**Functional gate:** pass when all commands above are green, allowing the two
documented expected failures.

**Distribution release:** no-go until the strict XFail in
`tests/test_export_parity.py` is resolved. The legacy drawsvg-Python exporter
still exceeds the locked visual-parity thresholds; details and the required
follow-up are recorded in [Export parity and text strategy](export-parity.md).
This gate does not relax those thresholds or reclassify that XFail as a pass.
