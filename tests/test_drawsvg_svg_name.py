import pytest

from export_drawsvg import svg_name_for_script


def test_svg_name_uses_script_stem() -> None:
    assert svg_name_for_script("C:/out/my_drawing.py") == "my_drawing.svg"
    assert svg_name_for_script("Bob's-v2.py") == "Bob's-v2.svg"


@pytest.mark.parametrize("name", ["  .py", "my drawing.py", "___.py", "-.py"])
def test_svg_name_rejects_invalid(name: str) -> None:
    with pytest.raises(ValueError):
        svg_name_for_script(name)
