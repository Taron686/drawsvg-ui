# Entwicklungsbaseline

Stand: 2026-08-26
Branch: `codex/t001-baseline`
Commit: `a3983e042f1e2abe3027269f0cac618b5de662cf`

Diese Baseline wurde in der lokalen Worktree-venv `.venv` ermittelt. Die
venv-Dateien sind durch `.gitignore` ausgeschlossen und werden nicht
versioniert.

## Umgebung

- Python: 3.14.2
- pip: 25.3
- PySide6: 6.11.2
- Qt: 6.11.2
- shiboken6: 6.11.2
- drawsvg: 2.4.2
- Git-Status vor der Dokumentationsänderung: sauber
- GitNexus: Index am 2026-08-26 aktualisiert (`analyze --pdg`), anschließend
  Status `up-to-date` für Commit `c8298ee` auf dem Haupt-Worktree

## Qualitätsbefehle

Die folgenden Befehle wurden aus dem Projektverzeichnis mit
`.venv\Scripts\python.exe` ausgeführt:

| Befehl | Ergebnis |
| --- | --- |
| `python -m pip install -e .[dev]` | Erfolgreich; Projektabhängigkeiten, editable Paket sowie Ruff und Pytest installiert. |
| `python -m ruff check .` | Fehlgeschlagen (Exit 1): 81 bestehende Lint-Fehler (53 automatisch fixierbar). |
| `python -m compileall -q src` | Erfolgreich (Exit 0) |
| `python -m pytest` | Exit 5: keine Tests gesammelt (`collected 0 items`, `no tests ran`). |
| `git diff --check` | Erfolgreich (Exit 0) |

## T-001-Befund

Das `dev`-Extra stellt die beiden Prüfwerkzeuge Ruff und Pytest reproduzierbar
bereit, ohne Laufzeitabhängigkeiten zu verändern. Die Installation ist
erfolgreich; die bestehenden Ruff-Befunde und das Fehlen von Tests bleiben als
separate Projektbefunde sichtbar und werden durch T-001 nicht verdeckt.
