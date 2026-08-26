# T-003: Benchmark-Baseline

`benchmarks/benchmark_simple_objects.py` liefert die reproduzierbare
M0-Ausgangsmessung für 100, 1000 und 2000 einfache Objekte. Der Benchmark ist
bewusst von der Produktionslogik isoliert: pro Durchlauf werden native
`QGraphicsRectItem`-Objekte erstellt, Qt-Ereignisse verarbeitet und eine
deterministische JSON-Repräsentation serialisiert.

## Ausführen

```powershell
.\.venv\Scripts\python.exe benchmarks\benchmark_simple_objects.py --output artifacts\benchmark-baseline.json
```

Für vergleichbare Resultate den Rechner möglichst nicht parallel belasten und
die Standardwerte beibehalten: drei Warmups und 20 Messungen je Objektanzahl.
Die vollständigen Einzelwerte werden in `samples_ms` ausgegeben; `median_ms`,
`p95_ms` (inklusive Perzentil-Interpolation) und `max_ms` sind daraus
abgeleitet. `json_payload_bytes` dokumentiert die serialisierte Nutzlast.

Der Report enthält außerdem Python-, PySide6- und Qt-Version sowie CPU-Modell,
Architektur und logische Kernzahl. `QT_QPA_PLATFORM=offscreen` wird nur gesetzt,
falls es nicht bereits in der Umgebung vorgegeben wurde, damit der Benchmark
auch ohne sichtbares Fenster ausgeführt werden kann.

## Gates

Die Grenzen `p95 <= 100 ms` und `max <= 150 ms` stehen im JSON-Report als
Dokumentation, sind für M0 jedoch ausdrücklich deaktiviert. Dieses Skript
meldet daher bei deren Überschreitung keinen Fehler. Erst nach der M0-Baseline
darf ein Folge-Ticket diese Werte als aktives Qualitäts-Gate einschalten.
