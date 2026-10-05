from __future__ import annotations

import runpy
from xml.etree import ElementTree as ET

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from connectors import ConnectorEndpoint, ConnectorItem
from export_drawsvg import export_drawsvg_py
from shape_registry import SHAPE_REGISTRY

NS = {'svg': 'http://www.w3.org/2000/svg'}


@pytest.mark.parametrize('kind', ['connector', 'Arrow', 'Double Arrow'])
@pytest.mark.parametrize('gradient,opacity,shadow', [
    (False, 0.5, False), (True, 0.5, False),
    (True, 1.0, True), (True, 0.5, True),
])
def test_combined_connector_arrow_attributes_execute_and_save(
    application, monkeypatch, tmp_path, kind, gradient, opacity, shadow,
):
    scene = QtWidgets.QGraphicsScene()
    if kind == 'connector':
        item = ConnectorItem(ConnectorEndpoint.free(QtCore.QPointF(0, 0)),
                             ConnectorEndpoint.free(QtCore.QPointF(100, 60)))
        item.set_route_points([QtCore.QPointF(0, 0), QtCore.QPointF(100, 60)])
    else:
        item = SHAPE_REGISTRY.create('Arrow', 0, 0, 100, 60)
        assert item is not None
        if kind == 'Double Arrow':
            item.arrow_start = True
    pen = QtGui.QPen(QtGui.QColor('red'), 3)
    if gradient:
        paint = QtGui.QLinearGradient(0, 0, 100, 60)
        paint.setColorAt(0, QtGui.QColor('red'))
        paint.setColorAt(1, QtGui.QColor('blue'))
        pen.setBrush(QtGui.QBrush(paint))
    item.setPen(pen)
    item.setOpacity(opacity)
    if shadow:
        effect = QtWidgets.QGraphicsDropShadowEffect()
        effect.setOffset(7, 9)
        effect.setBlurRadius(8)
        item.setGraphicsEffect(effect)
    scene.addItem(item)
    output = tmp_path / 'attributes.py'
    monkeypatch.setattr(QtWidgets.QFileDialog, 'getSaveFileName', lambda *a, **kw: (str(output), ''))
    export_drawsvg_py(scene)

    # Compile and execute the artifact; ast.parse alone accepts duplicate keywords.
    generated = runpy.run_path(str(output))
    drawing = generated['build_drawing']()
    drawing.save_svg(str(tmp_path / 'attributes.svg'))
    root = ET.parse(tmp_path / 'attributes.svg').getroot()
    paths = root.findall('.//svg:path', NS)
    assert len(paths) == (1 if kind == 'connector' else 3 if kind == 'Double Arrow' else 2)
    assert all(float(path.get('opacity', '1')) == pytest.approx(opacity) for path in paths)
    assert bool(root.findall('.//svg:linearGradient', NS)) == gradient
    assert bool(root.findall('.//svg:filter', NS)) == shadow
    if kind == 'connector':
        assert paths[0].get('data-connector')
