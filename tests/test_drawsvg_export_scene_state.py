from __future__ import annotations

import gc
import runpy
from xml.etree import ElementTree as ET

import pytest
import shiboken6
from PySide6 import QtCore, QtWidgets

from export_drawsvg import export_drawsvg_py
from scene_codec import KEY_TRANSIENT
from shape_registry import SHAPE_REGISTRY
from test_export_parity import _builtins_scene


def _unreferenced_scene():
    """Return only the scene, so Qt alone keeps top-level items alive."""
    scene = _builtins_scene()
    for hidden, transient in ((False, False), (True, False), (False, True)):
        outer = QtWidgets.QGraphicsItemGroup()
        scene.addItem(outer)
        inner = QtWidgets.QGraphicsItemGroup(outer)
        item = SHAPE_REGISTRY.create('Rectangle', 40, 40, 50, 30)
        item.setParentItem(inner)
        item.set_label_text('Nested label')
        outer.setVisible(not hidden)
        outer.setData(KEY_TRANSIENT, transient)
        if hidden or transient:
            outer.setPos(10000, 10000)
    return scene


def _scene_state(scene):
    # Store only scalar identities/state, never item wrappers or strong refs.
    return (
        tuple(sorted((shiboken6.getCppPointer(item)[0], shiboken6.ownedByPython(item),
                      item.isVisible(), item.effectiveOpacity()) for item in scene.items())),
        scene.itemsBoundingRect().getRect(),
    )


@pytest.mark.parametrize('save', [True, False], ids=['save', 'cancel'])
def test_export_preserves_scene_owned_items(application, monkeypatch, tmp_path, save):
    scene = _unreferenced_scene()
    before = _scene_state(scene)
    gc.collect()
    assert _scene_state(scene) == before
    output = tmp_path / 'scene.py'
    monkeypatch.setattr(QtWidgets.QFileDialog, 'getSaveFileName',
                        lambda *a, **kw: (str(output) if save else '', ''))

    export_drawsvg_py(scene)
    assert _scene_state(scene) == before
    gc.collect()
    assert _scene_state(scene) == before
    if save:
        drawing = runpy.run_path(str(output))['build_drawing']()
        drawing.save_svg(str(tmp_path / 'scene.svg'))
        root = ET.parse(tmp_path / 'scene.svg').getroot()
        x, y, width, height = map(float, root.get('viewBox').split())
        assert QtCore.QRectF(x, y, width, height).right() < 10000
        gc.collect()
        assert _scene_state(scene) == before
    else:
        assert not output.exists()


def test_transient_label_does_not_export_or_expand_bounds(application, monkeypatch, tmp_path):
    scene = QtWidgets.QGraphicsScene()
    item = SHAPE_REGISTRY.create('Rectangle', 0, 0, 50, 30)
    item.set_label_text('Editor-only label')
    item.label_item().setData(KEY_TRANSIENT, True)
    item.label_item().setPos(10000, 10000)
    scene.addItem(item)
    output = tmp_path / 'label.py'
    monkeypatch.setattr(QtWidgets.QFileDialog, 'getSaveFileName', lambda *a, **kw: (str(output), ''))
    export_drawsvg_py(scene)
    root = ET.fromstring(runpy.run_path(str(output))['build_drawing']().as_svg())
    assert not root.findall('.//{http://www.w3.org/2000/svg}text')
    assert float(root.get('viewBox').split()[2]) < 100
