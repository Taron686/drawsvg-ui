# Logging-Vertrag

**Ticket:** T-004
**Status:** Spezifikation für T-013, T-014 und T-020
**Geltungsbereich:** DrawSVG-Desktopanwendung

Dieses Dokument definiert die beobachtbare Logging-Schnittstelle. Es ist eine
Implementierungsgrundlage; T-004 ändert keine Produktionsfehlerpfade und führt
keinen Logger ein. Spätere Implementierungen dürfen die hier beschriebenen
Felder und Datenschutzgrenzen erweitern, aber nicht stillschweigend umdeuten.

## Ziele und Nichtziele

Logs sollen Fehler reproduzierbar machen, ohne Nutzerdokumente oder persönliche
Daten zu sammeln. Sie sind für Diagnose und technische Telemetrie bestimmt,
nicht für Auditierung, Verhaltensanalyse oder die Speicherung von Zeichnungen.

Nicht Bestandteil dieses Vertrags sind ein Remote-Sammeldienst, ein UI für
Loganzeige und die konkrete Wahl der Python-Logging-Handler. Diese Entscheidungen
gehören in T-013/T-014/T-020, solange sie die folgenden Grenzen einhalten.

## Fehlerkatalog

Jedes Ereignis erhält einen stabilen `event`-Code. Freitext in `message` ist
ergänzend und darf nicht die maschinenlesbare Auswertung ersetzen.

| Code | Bedeutung | Standard-Level | Erwartete Aktion |
| --- | --- | --- | --- |
| `import.failed` | Datei konnte nicht gelesen, geparst oder validiert werden | `WARNING` | Import abbrechen, Ursache im UI anzeigen |
| `export.failed` | Export konnte nicht geschrieben oder erzeugt werden | `ERROR` | Export abbrechen, Ziel nicht als erfolgreich markieren |
| `document.invalid` | Eingabedokument verletzt das unterstützte Schema | `WARNING` | Sicher abbrechen; keine Teilpersistenz |
| `document.unsaved` | Änderungen konnten beim Beenden/Wechseln nicht gespeichert werden | `ERROR` | Nutzerentscheidung einholen |
| `resource.missing` | Referenzierte Ressource ist nicht verfügbar | `WARNING` | Vorgang mit Fallback oder Abbruch fortsetzen |
| `ui.action.failed` | Benutzeraktion konnte nicht abgeschlossen werden | `ERROR` | UI konsistent lassen; keine Exception nach außen |
| `config.invalid` | Konfiguration ist ungültig oder unlesbar | `WARNING` | Sicheren Default verwenden |
| `internal.invariant` | Interne Annahme ist verletzt | `ERROR` | Zustand nicht weiter beschädigen; Diagnose sichern |
| `app.exception` | Nicht behandelte Exception am Anwendungsrand | `CRITICAL` | Crash-Diagnose schreiben, UI kontrolliert beenden |
| `app.startup` / `app.shutdown` | Lebenszyklusereignis | `INFO` | Kontext für Log-Sitzung herstellen |

`DEBUG` ist ausschließlich für zeitlich begrenzte Entwicklungsdiagnose
zulässig und standardmäßig deaktiviert. Ein Stacktrace wird nur für
`ERROR`/`CRITICAL` und explizit angeforderte Diagnose protokolliert.

## Logeintrag und Pflichtfelder

Die kanonische Darstellung ist ein strukturierter Datensatz (bevorzugt JSON
Lines, ein Objekt pro Zeile). Pflichtfelder:

| Feld | Typ | Regel |
| --- | --- | --- |
| `timestamp` | ISO-8601 UTC | Erzeugung des Ereignisses, z. B. `2026-08-26T12:34:56.123Z` |
| `level` | Enum | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `event` | String | Einer der Katalogcodes oder versionierter Erweiterungscode |
| `message` | String | Kurze technische Beschreibung, keine geheimen Werte |
| `session_id` | String | Zufällig pro Prozessstart; nicht aus Nutzer-/Dateidaten abgeleitet |
| `component` | String | Betroffene Schicht, z. B. `import`, `export`, `ui`, `startup` |
| `app_version` | String | Laufende Versionsangabe |

Optionale, kontrollierte Felder sind `operation_id` (zufällig pro Vorgang),
`duration_ms` (nicht-negativ), `exception_type`, `traceback` und technische
Fehlerdetails wie `error_code`. Dateikontext darf nur als `path_hash` oder als
vom Nutzer freigegebener, gekürzter Dateiname erscheinen. Rohpfade sind nicht
Teil des Standardvertrags.

`traceback` enthält höchstens 32 KiB und wird bei wiederholten identischen
Fehlern nicht unbeschränkt vervielfältigt. Einträge müssen auch bei fehlenden
optionalen Feldern valide und parsebar bleiben. Ungültige Zusatzfelder dürfen
den eigentlichen Anwendungsvorgang nicht zum Absturz bringen.

## Datenschutz und Geheimnisse

Nicht protokolliert werden:

- vollständige Zeichnungsinhalte, SVG/XML, Textobjekte und Clipboard-Inhalte,
- Dateiinhalte, Zugangsdaten, Tokens, Umgebungsvariablen und Betriebssystem-
  Geheimnisse,
- vollständige lokale Pfade, Benutzername, E-Mail-Adresse und andere direkte
  Identifikatoren,
- beliebige Exception-Messages, wenn sie unkontrolliert Eingabedaten spiegeln.

Dateinamen und externe Ressourcen werden vor dem Logging klassifiziert und
redigiert. Für Korrelation ist ein lokaler, nicht zurückrechenbarer Hash mit
prozess-/installationsgebundenem Salt zulässig; derselbe Eingabewert darf nicht
über Installationen hinweg korrelierbar sein. Redaction muss vor dem
`LogRecord` erfolgen, nicht erst bei der Dateiausgabe. Logs bleiben lokal,
sofern der Nutzer keinen ausdrücklichen Export auslöst. Ein Diagnoseexport muss
vor dem Schreiben eine sichtbare Zusammenfassung und eine Bestätigung anbieten.

## Speicherung und Rotation

Der Standard ist eine begrenzte lokale Logdatei mit UTF-8 und Zeilenformat.
Konkrete Werte dürfen konfigurierbar sein, müssen aber mindestens diese Grenzen
einhalten:

- maximal **5** rotierte Dateien (`app.log`, `app.log.1` bis `.5`),
- maximal **5 MiB** pro Datei vor Rotation,
- Rotation atomar bzw. mit temporärer Datei und sicherem Rename,
- alte Dateien werden nach erfolgreicher Rotation gelöscht; bei fehlenden
  Schreibrechten läuft die Anwendung ohne Logging weiter und meldet dies nur
  einmal als best-effort-Diagnose,
- keine Kompression oder externe Übertragung ohne explizite Produktentscheidung.

Beim Start wird eine neue `session_id` vergeben. Rotation darf die laufende
Anwendung nicht blockieren und darf niemals einen Nutzer-Import/-Export
fehlschlagen lassen. Ein Session-Abschluss ist best effort; unvollständige
letzte Zeilen müssen von Auswertern toleriert werden.

## Excepthook-Verantwortung

T-014 besitzt die Verantwortung für unbehandelte Exceptions an den
Anwendungsgrenzen (`sys.excepthook` und, falls verwendet, Qt-Thread-/Worker-
Grenzen). Der Hook muss:

1. `app.exception` genau einmal pro unbehandeltem Fehler erfassen,
2. Typ und begrenzten Stacktrace nach den Redaction-Regeln schreiben,
3. vorhandene Original-Hooks/Qt-Standardbehandlung nicht dauerhaft ersetzen,
4. Rekursion erkennen (Fehler im Logger darf keinen zweiten Hook-Sturm auslösen),
5. anschließend die bestehende Beendigungsstrategie der Anwendung respektieren.

Bibliotheks- und UI-Code darf Exceptions nicht global verschlucken. Lokale
Fehlerbehandlung loggt den passenden Katalogcode und gibt eine kontrollierte
Rückgabe bzw. Nutzerreaktion zurück. Der Excepthook ist kein Ersatz für diese
fachliche Fehlerbehandlung.

## API-Grenzen für Folgetickets

Die Implementierung soll genau eine kleine, stabile Fassade anbieten:

```python
log_event(level, event, *, component, message, operation_id=None, **fields)
log_exception(event, exc, *, component, operation_id=None, **fields)
start_session() -> str
shutdown_logging() -> None
```

Die Fassade nimmt keine rohen `LogRecord`-Objekte aus Anwendungscode entgegen,
exportiert keine Handler und kennt keine Qt-Widgets. `log_exception` redigiert
und begrenzt Exception-Daten zentral. Anwendungscode darf nur Katalogcodes und
whitelistete Zusatzfelder verwenden; unbekannte Felder werden verworfen oder
als Diagnosefehler behandelt, nicht ungefiltert serialisiert. Logging ist
best-effort: Exceptions aus Logger, Formatter, Rotation oder Hook dürfen den
fachlichen Vorgang nicht ersetzen.

## Testszenarien / Abnahmekriterien

Die folgenden Szenarien bilden den nicht ausführbaren Testplan für T-013/T-014/
T-020:

1. Ein erfolgreicher Start erzeugt `app.startup` mit UTC-Zeitstempel,
   `session_id`, Version und ohne Nutzerpfad.
2. Ein fehlerhafter Import erzeugt genau ein `import.failed`; der Datensatz
   enthält weder Dokumentinhalt noch vollständigen Pfad.
3. Ein Exportfehler erzeugt `export.failed` mit `ERROR`; die Logger-Exception
   selbst darf den UI-Fehlerdialog nicht ersetzen.
4. Eine unbehandelte Exception erzeugt genau ein `app.exception` inklusive
   begrenztem Stacktrace und führt danach die etablierte Beendigung aus.
5. Eine Exception mit geheimnis-/pfadähnlicher Nachricht wird vollständig
   redigiert, bevor sie in Datei oder Diagnoseexport gelangt.
6. Eine Logdatei über 5 MiB rotiert innerhalb der Dateigrenzen; höchstens fünf
   Backups bleiben erhalten.
7. Fehlende Schreibrechte oder ein voller Datenträger lassen den eigentlichen
   Import/Export nicht abstürzen.
8. Loggerfehler und Fehler im Excepthook erzeugen keine Rekursion und keinen
   zweiten `app.exception`-Eintrag.
9. Parallele Worker-/Qt-Fehler behalten `session_id` und `operation_id`, sofern
   vorhanden, und schreiben parsebare einzelne Datensätze.
10. Ein Diagnoseexport enthält nur freigegebene Felder und zeigt vor dem
    Export die enthaltenen Kategorien an.

## Zuordnung

- **T-013:** Fassade, strukturierte Ausgabe, Rotation und Lebenszyklus gemäß
  diesem Vertrag.
- **T-014:** Excepthook, Worker-/Qt-Grenzen und kontrollierte Exception-
  Behandlung gemäß Verantwortungsabschnitt.
- **T-020:** Tests und Diagnose-/Exportprüfung anhand der Szenarien oben.

Abweichungen vom Vertrag müssen als eigene Designentscheidung dokumentiert
werden, insbesondere bei neuen Pflichtfeldern, externen Logzielen oder einer
Änderung der Datenschutzregeln.
