"""Pixel baseline captured before splitting the palette icon renderer."""

import hashlib

from PySide6 import QtCore

from palette import _build_shape_icon
from shape_registry import SHAPE_REGISTRY


ICON_HASHES = {
    "Arrow": "052afd25a789639abdae4b14aedfa6fae64e48da02333bc17900b3f23636cbd6",
    "Bezier Path": "5d9ead48f531e0deb38ba3945e8f13c3050db4aa7a903f6d9c98935038475b31",
    "Block Arrow": "cd390fa958f89f3cf6084806e328ec714663420dc409f6b5ea1bfb44e6c04d84",
    "Callout": "fbc66f51febeee0a9b99dcd14bd076fd2b3900e5727e1279b0a37c7b2192135f",
    "Circle": "e2e38cd319d0c40490dd07caf843ddfb366c4abaac9e1400d7ed89dc2bcd9c6e",
    "Cloud": "e8bca247a3e67c7b49bb0824a2975ba9a1f09befc3a74935057c3641d2ddda74",
    "Curvy Left Bracket": "f1dca32eb8c4b24064d7120f2d395d75cbf46df86d6c77f442f504fc1de1d523",
    "Curvy Right Bracket": "29d4efd00be4cf6d58f8274be6ba67b8ea94c2220fabf73e7c7f429b47f9ef2d",
    "Database": "abe2842e199faa276e1eef8075c934329bd8bd169cdb5fa9a1fcc23e8061354f",
    "Diamond": "b01db1d371e64891f484f2aab2efb18cbff47a622745dc1c05cdb2f3510be2e7",
    "Document": "0f23d4151c7e76709d9ca6859d18d7e54f93d7c84390c7620971b1ada3f9ae85",
    "Ellipse": "a781ee7fd10c4c60d5793cb86eda3b6474075bcd272ee369a06b8846fe469a6a",
    "Folder Tree": "1c6bf1482718246cbfeb0182b85643ab03d64e280587d27d1a42d8d965731068",
    "Free Polygon": "a05221b4ae0d6c2406b8613caf8446ff6915fb76c643283aeb918ecb3b6a740d",
    "Free Polyline": "e07af353aa9a585bddad70d88556aaf4940d048355b2764b7d0f24e1750de804",
    "Hexagon": "d8e230894e12baef988d1716c34b5deadbd3a67166bad4f824b4574c08a74245",
    "Line": "ed7c73f0286679312595b7ed365be6e90c49bcd802be7e3402b9a8839c8cc6e6",
    "Multiple Document": "aac6ad6cfad9192de5a919c49de223070bf2c9dd19fb0af311663199eeac7e45",
    "Parallelogram": "b740a99cb0eb281276586198b3a051a4003de9a3b81785ee7a18ae6c94246fc6",
    "Rectangle": "f8b50fdd2c1ed7481b0aba016ae17adbc95a531f840cde58acb52a54da3cac3e",
    "Rounded Rectangle": "0ba2effb1ab88f3cdbe05472ad26881cb3cb4bdaabadbf13ec7d8a25e9103fce",
    "Split Rounded Rectangle": "f8a5443651232af96ef1d336116773179b1e1845a7f059a320a6491cbfdde815",
    "Swimlane": "858188b71b676eac9b4072c192b1f6b6b86bcd18faa13ab631ec701de9be2bec",
    "Table": "de144f86ad92b27e64e5c5d8e9a212af7c178b7a471881b85382040d4f17791e",
    "Text": "53ce728a1e3115ff42a52eb58d2568cf0b7bd281b1ade3fdc100a8f47825cfd1",
    "Triangle": "88d97de9034198e429dca5b203a0f6e7ab4400514b6ca0c9cba2571ea5c07927",
}


def test_palette_icon_pixels(application):
    names = [definition.type_id for definition in SHAPE_REGISTRY.palette_definitions()]
    assert set(names) == set(ICON_HASHES)
    for name in names:
        image = _build_shape_icon(name, QtCore.QSize(48, 48)).toImage()
        assert hashlib.sha256(bytes(image.bits())).hexdigest() == ICON_HASHES[name], (
            name
        )
