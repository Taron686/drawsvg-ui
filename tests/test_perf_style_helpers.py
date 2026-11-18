import canvas_view
import shape_registry


def test_label_color_uses_shared_decoder():
    assert canvas_view._color_from_data is shape_registry._color_from_data
    color = canvas_view._color_from_data({"name": "#123456", "alpha": 0.5})
    assert color.name() == "#123456"
    assert abs(color.alphaF() - 0.5) < 0.001
