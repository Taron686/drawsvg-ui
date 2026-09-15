# Aufteilungsvorschlag für `items.py`

## Ausgangsanalyse

* **Hilfsfunktionen und Konstanten** – Raster-Snapping, Cursorlogik und gemeinsame Prüfungen stehen am Dateianfang und werden quer durch alle Item-Klassen genutzt.【F:src/items.py†L1-L156】
* **Interaktions-Mixins und Handle-Klassen** – `HandleAwareItemMixin`, `ResizableItem` sowie mehrere spezialisierte Handle-Implementierungen bündeln die gesamte Eingabelogik für Größenänderung, Rotation und Sonderfälle.【F:src/items.py†L159-L652】
* **Form-spezifische Mixins und Standardformen** – `ShapeLabelMixin` versorgt rechteckartige Shapes mit Labeln; darauf folgen `RectItem`, `SplitRoundedRectItem`, `EllipseItem`, `TriangleItem` und `DiamondItem` als klassische Grundformen.【F:src/items.py†L697-L1204】
* **Komplexe Spezialformen** – `BlockArrowItem`, `CurvyBracketItem` und `LineItem` haben eigene Handles, Metriken und Zeichenlogik, die den Dateiinhalt stark verlängern.【F:src/items.py†L1260-L2093】
* **Nicht-geometrische Items** – `FolderTreeItem` bringt eine vollständige Baumdatenstruktur samt UI mit, `TextItem` und `GroupItem` ergänzen die Szeneverwaltung.【F:src/items.py†L1473-L2320】

## Kriterien für eine sinnvolle Aufteilung

1. **Gemeinsame Infrastruktur nur einmal definieren.** Utility-Funktionen und Handle-Mixins sollten in einem Basismodul landen, damit Formen sie ohne zyklische Importe wiederverwenden können.
2. **Konzeptuell verwandte Shapes gruppieren.** Rechteckbasierte Elemente (Rect, SplitRect, FolderTree) benötigen ähnliche Abhängigkeiten, während linienbasierte Formen (LineItem, CurvyBracket, BlockArrow) eigenständige Pakete bilden können.
3. **Externe API beibehalten.** Bestehende Importpfade – z. B. `from items import RectItem` – lassen sich über ein schlankes `__init__.py` mit Re-Exports erhalten.
4. **Test- und Migrationsschritte planen.** Die Aufteilung sollte über mehrere Commits erfolgen: zuerst Modulstruktur anlegen, dann Klassen umziehen, abschließend relative Importe konsolidieren und Regressionstests fahren.

## Konkrete Modulstruktur

```
src/items/
├── __init__.py          # Re-Exports für Rückwärtskompatibilität
├── base.py              # Konstanten, Snap-Utilities, Mixins, Resize-/Rotation-Handles
├── labels.py            # ShapeLabelMixin und _ShapeLabelItem
├── shapes/
│   ├── __init__.py      # Exportiert Standardformen
│   ├── rects.py         # RectItem, SplitRoundedRectItem
│   ├── polygons.py      # TriangleItem, DiamondItem, BlockArrowItem
│   ├── curves.py        # EllipseItem, CurvyBracketItem
│   └── lines.py         # LineItem und LineHandle
├── widgets/
│   ├── __init__.py
│   └── folder_tree.py   # FolderTreeNode, FolderTreeBranchDot, FolderTreeItem
└── text.py              # TextItem, GroupItem
```

*`base.py`* hält zentrale Utilities und die generischen Handles.【F:src/items.py†L1-L652】

*`labels.py`* kapselt alle Label-Funktionen und kann optional von `rects.py` und `polygons.py` importiert werden.【F:src/items.py†L697-L888】

*`shapes.rects`* sammelt rechteckbasierte Formen inklusive Divider-Handle.【F:src/items.py†L890-L1117】

*`shapes.polygons`* beherbergt Dreieck, Raute und Blockpfeil samt spezialisierter Handles.【F:src/items.py†L1145-L1469】

*`shapes.curves`* deckt Ellipse und geschwungene Klammer ab.【F:src/items.py†L1118-L2080】

*`shapes.lines`* enthält `LineItem` und `LineHandle` für alle Pfad-basierten Linienfunktionen.【F:src/items.py†L654-L2093】

*`widgets.folder_tree`* isoliert Baumdatenstruktur und UI-spezifische Logik vom geometrischen Kern.【F:src/items.py†L1473-L1916】

*`text.py`* bündelt `TextItem` und `GroupItem`, die stark mit Textinteraktion bzw. Gruppierung verknüpft sind.【F:src/items.py†L2239-L2320】

## Umsetzungsschritte

1. **Paketstruktur erstellen.** Leere Module nach obigem Schema anlegen und `__all__` in `src/items/__init__.py` pflegen.
2. **Utilities migrieren.** Konstanten, Snap-Funktionen und Basismixins nach `base.py` verschieben, abhängige Klassen mit relativen Importen anpassen.
3. **Handles reorganisieren.** `ResizeHandle`, `RotationHandle`, `SplitDividerHandle`, `BlockArrowHandle`, `LineHandle` innerhalb der jeweiligen Modulgruppe platzieren.
4. **Formklassen verschieben.** Schrittweise pro Kategorie, dabei jeweils Tests oder manuelle Checks durchführen, um Importfehler früh zu erkennen.
5. **Dokumentation & Tests anpassen.** README/Entwicklerdokumentation auf neue Importwege hinweisen, automatisierte Tests bzw. manuelle Szenenläufe starten.

Durch diese Aufteilung schrumpft jede Datei auf handhabbare ~200–300 Zeilen, während die logische Trennung den Wartungsaufwand reduziert und gezielte Erweiterungen (z. B. neue Polygonformen) erleichtert.
