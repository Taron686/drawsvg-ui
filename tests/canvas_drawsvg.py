# Auto-generated from PySide6 Canvas to drawsvg
import drawsvg as draw

def _drawsvg_gradient(kind, coords, stops, attrs):
    if kind == 'linear':
        gradient = draw.LinearGradient(*coords, **attrs)
    else:
        cx, cy, radius, fx, fy, fr = coords
        gradient = draw.RadialGradient(cx, cy, radius, fx=fx, fy=fy, fr=fr, **attrs)
    for offset, color, alpha in stops:
        gradient.add_stop(offset, color, opacity=alpha)
    return gradient


def _drawsvg_effect(element, rect, shadow):
    dx, dy, radius, color, alpha = shadow
    x, y, width, height = rect
    # Qt uses a different blur kernel. Gaussian sigma=radius/2 is an
    # approximation; allow three sigma on every side to avoid clipping.
    margin = 1.5 * radius
    left = min(x, x + dx) - margin
    top = min(y, y + dy) - margin
    right = max(x + width, x + width + dx) + margin
    bottom = max(y + height, y + height + dy) + margin
    effect = draw.Filter(x=left, y=top, width=max(1, right-left),
                         height=max(1, bottom-top), filterUnits='userSpaceOnUse',
                         primitiveUnits='userSpaceOnUse', color_interpolation_filters='sRGB')
    if radius > 0:
        effect.append(draw.FilterItem('feGaussianBlur', in_='SourceAlpha',
                                     stdDeviation=radius/2, result='shadow-alpha'))
    effect.append(draw.FilterItem('feOffset', in_='shadow-alpha' if radius > 0 else 'SourceAlpha',
                                 dx=dx, dy=dy, result='shadow-offset'))
    effect.append(draw.FilterItem('feFlood', flood_color=color, flood_opacity=alpha,
                                 result='shadow-color'))
    effect.append(draw.FilterItem('feComposite', in_='shadow-color', in2='shadow-offset',
                                 operator='in', result='shadow'))
    merge = draw.FilterItem('feMerge')
    merge.append(draw.FilterItem('feMergeNode', in_='shadow'))
    merge.append(draw.FilterItem('feMergeNode', in_='SourceGraphic'))
    effect.append(merge)
    # Qt shadow offset/radius use device coordinates. Apply the filter outside
    # the item's transform so rotations and scaling do not change those values.
    transform = element.args.pop('transform', None)
    source = draw.Group(transform=transform) if transform else draw.Group()
    source.append(element)
    result = draw.Group(filter=effect)
    result.append(source)
    return result

def build_drawing():
    d = draw.Drawing(963, 583, origin=(-493, -438), viewBox='-493 -438 963 583')
    d.append(draw.Rectangle(-493, -438, 963, 583, fill='white', stroke='none'))

    _rect = draw.Rectangle(0.00, 0.00, 430.00, 450.00, fill='#ffffff', fill_opacity=0, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, rx=37.17, ry=37.17, transform='matrix(1.000000 0.000000 0.000000 1.000000 -226.850394 -311.259843)')
    d.append(_rect)

    _rect = draw.Rectangle(0.00, 0.00, 160.00, 360.00, fill='#ffffff', fill_opacity=0, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, rx=15.00, ry=15.00, transform='matrix(1.000000 0.000000 0.000000 1.000000 -486.850394 -221.259843)')
    d.append(_rect)

    _rect = draw.Rectangle(0.00, 0.00, 160.00, 100.00, fill='#ffffff', fill_opacity=0, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, rx=15.00, ry=15.00, transform='matrix(1.000000 0.000000 0.000000 1.000000 303.149606 -201.259843)')
    d.append(_rect)

    _path = draw.Path('M 0.00 -170.00 L -100.00 -170.00', stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, fill_rule='evenodd', fill='none', data_arrow_start=False, data_arrow_end=True, data_arrow_head_length=10.00, data_arrow_head_width=10.00, transform='matrix(1.000000 0.000000 0.000000 1.000000 303.149606 -11.259843)')
    # Arrowheads: start=false, end=true, length=10.00, width=10.00
    _arrow_head = draw.Path('M -100.00 -170.00 L -90.00 -175.00 L -90.00 -165.00 Z', fill='#000000', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='miter', stroke_miterlimit=4, fill_rule='evenodd', transform='matrix(1.000000 0.000000 0.000000 1.000000 303.149606 -11.259843)')
    d.append(_arrow_head)
    d.append(_path)

    _path = draw.Path('M 0.00 -170.00 L -100.00 -170.00', stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, fill_rule='evenodd', fill='none', data_arrow_start=False, data_arrow_end=True, data_arrow_head_length=10.00, data_arrow_head_width=10.00, transform='matrix(-1.000000 0.000000 -0.000000 -1.000000 203.149606 -311.259843)')
    # Arrowheads: start=false, end=true, length=10.00, width=10.00
    _arrow_head = draw.Path('M -100.00 -170.00 L -90.00 -175.00 L -90.00 -165.00 Z', fill='#000000', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='miter', stroke_miterlimit=4, fill_rule='evenodd', transform='matrix(-1.000000 0.000000 -0.000000 -1.000000 203.149606 -311.259843)')
    d.append(_arrow_head)
    d.append(_path)

    _circ = draw.Circle(20.00, 20.00, 20.00, fill='#000000', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, transform='matrix(1.000000 0.000000 0.000000 1.000000 -46.850394 -431.259843)')
    d.append(_circ)

    _path = draw.Path('M 0.00 0.00 L 400.00 0.00 L 400.00 210.00', stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, fill_rule='evenodd', fill='none', data_arrow_start=False, data_arrow_end=True, data_arrow_head_length=10.00, data_arrow_head_width=10.00, transform='matrix(1.000000 0.000000 0.000000 1.000000 -6.850394 -411.259843)')
    # Arrowheads: start=false, end=true, length=10.00, width=10.00
    _arrow_head = draw.Path('M 400.00 210.00 L 395.00 200.00 L 405.00 200.00 Z', fill='#000000', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='miter', stroke_miterlimit=4, fill_rule='evenodd', transform='matrix(1.000000 0.000000 0.000000 1.000000 -6.850394 -411.259843)')
    d.append(_arrow_head)
    d.append(_path)

    _path = draw.Path('M 190.00 -40.00 L 190.00 40.00', stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, fill_rule='evenodd', fill='none', data_arrow_start=False, data_arrow_end=True, data_arrow_head_length=10.00, data_arrow_head_width=10.00, transform='matrix(1.000000 0.000000 0.000000 1.000000 -216.850394 -351.259843)')
    # Arrowheads: start=false, end=true, length=10.00, width=10.00
    _arrow_head = draw.Path('M 190.00 40.00 L 185.00 30.00 L 195.00 30.00 Z', fill='#000000', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='miter', stroke_miterlimit=4, fill_rule='evenodd', transform='matrix(1.000000 0.000000 0.000000 1.000000 -216.850394 -351.259843)')
    d.append(_arrow_head)
    d.append(_path)

    _path = draw.Path('M 320.00 40.00 L 0.00 40.00 L 0.00 230.00', stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, fill_rule='evenodd', fill='none', data_arrow_start=False, data_arrow_end=True, data_arrow_head_length=10.00, data_arrow_head_width=10.00, transform='matrix(1.000000 0.000000 0.000000 1.000000 -366.850394 -451.259843)')
    # Arrowheads: start=false, end=true, length=10.00, width=10.00
    _arrow_head = draw.Path('M 0.00 230.00 L -5.00 220.00 L 5.00 220.00 Z', fill='#000000', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='miter', stroke_miterlimit=4, fill_rule='evenodd', transform='matrix(1.000000 0.000000 0.000000 1.000000 -366.850394 -451.259843)')
    d.append(_arrow_head)
    d.append(_path)

    _circ = draw.Circle(20.00, 20.00, 20.00, fill='#000000', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, transform='matrix(1.000000 0.000000 0.000000 1.000000 -196.850394 -231.259843)')
    d.append(_circ)

    _path = draw.Path('M 0.00 0.00 L 60.00 0.00', stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, fill_rule='evenodd', fill='none', data_arrow_start=False, data_arrow_end=True, data_arrow_head_length=10.00, data_arrow_head_width=10.00, transform='matrix(1.000000 0.000000 0.000000 1.000000 -156.850394 -211.259843)')
    # Arrowheads: start=false, end=true, length=10.00, width=10.00
    _arrow_head = draw.Path('M 60.00 0.00 L 50.00 5.00 L 50.00 -5.00 Z', fill='#000000', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='miter', stroke_miterlimit=4, fill_rule='evenodd', transform='matrix(1.000000 0.000000 0.000000 1.000000 -156.850394 -211.259843)')
    d.append(_arrow_head)
    d.append(_path)

    _rect = draw.Rectangle(0.00, 0.00, 260.00, 70.00, fill='#ffffff', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, rx=10.50, ry=10.50, transform='matrix(1.000000 0.000000 0.000000 1.000000 -96.850394 -241.259843)')
    d.append(_rect)

    _rect = draw.Rectangle(0.00, 0.00, 260.00, 70.00, fill='#ffffff', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, rx=10.50, ry=10.50, transform='matrix(1.000000 0.000000 0.000000 1.000000 -86.850394 -21.259843)')
    d.append(_rect)

    _path = draw.Path('M -150.00 -360.00 L -150.00 -210.00', stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, fill_rule='evenodd', fill='none', data_arrow_start=False, data_arrow_end=True, data_arrow_head_length=10.00, data_arrow_head_width=10.00, transform='matrix(1.000000 0.000000 0.000000 1.000000 203.149606 188.740157)')
    # Arrowheads: start=false, end=true, length=10.00, width=10.00
    _arrow_head = draw.Path('M -150.00 -210.00 L -155.00 -220.00 L -145.00 -220.00 Z', fill='#000000', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='miter', stroke_miterlimit=4, fill_rule='evenodd', transform='matrix(1.000000 0.000000 0.000000 1.000000 203.149606 188.740157)')
    d.append(_arrow_head)
    d.append(_path)

    _path = draw.Path('M -173.71 -323.44 L -173.71 -473.44', stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='bevel', stroke_miterlimit=4, fill_rule='evenodd', fill='none', data_arrow_start=False, data_arrow_end=True, data_arrow_head_length=10.00, data_arrow_head_width=10.00, transform='matrix(1.000000 0.000000 0.000000 1.000000 276.857715 302.177710)')
    # Arrowheads: start=false, end=true, length=10.00, width=10.00
    _arrow_head = draw.Path('M -173.71 -473.44 L -168.71 -463.44 L -178.71 -463.44 Z', fill='#000000', fill_opacity=1, stroke='#000000', stroke_opacity=1, stroke_width=2.00, data_pen_units='svg', data_qt_pen_style=1, stroke_linecap='square', stroke_linejoin='miter', stroke_miterlimit=4, fill_rule='evenodd', transform='matrix(1.000000 0.000000 0.000000 1.000000 276.857715 302.177710)')
    d.append(_arrow_head)
    d.append(_path)

    _text = draw.Text("Text", 32.00, 4.00, 4.00, fill='#000000', opacity=1.000000, font_family='Arial', font_weight='normal', font_style='normal', text_decoration='none', data_xml_escaped='true', text_anchor='start', dominant_baseline='alphabetic', line_height=1.125000, xml__space='preserve', data_doc_margin=4.0000, data_font_px=32.0000, data_scale=1.000000, data_raw_text='Text', data_box_w=67.0000, data_box_h=44.0000, data_auto_size=True, data_text_h='left', data_text_v='top', data_text_dir='ltr', direction='ltr', unicode_bidi='embed', transform='matrix(1.000000 0.000000 0.000000 1.000000 103.149606 -121.259843)')
    _text.escaped_text = ''
    _text.children.clear()
    _text.append_line('Text', x=4.0000, y=33.0000, direction='ltr', text_anchor='start')
    d.append(_text)

    _text = draw.Text("Text", 32.00, 4.00, 4.00, fill='#000000', opacity=1.000000, font_family='Arial', font_weight='normal', font_style='normal', text_decoration='none', data_xml_escaped='true', text_anchor='start', dominant_baseline='alphabetic', line_height=1.125000, xml__space='preserve', data_doc_margin=4.0000, data_font_px=32.0000, data_scale=1.000000, data_raw_text='Text', data_box_w=67.0000, data_box_h=44.0000, data_auto_size=True, data_text_h='left', data_text_v='top', data_text_dir='ltr', direction='ltr', unicode_bidi='embed', transform='matrix(1.000000 0.000000 0.000000 1.000000 -16.850394 -121.259843)')
    _text.escaped_text = ''
    _text.children.clear()
    _text.append_line('Text', x=4.0000, y=33.0000, direction='ltr', text_anchor='start')
    d.append(_text)

    _text = draw.Text("Text", 32.00, 4.00, 4.00, fill='#000000', opacity=1.000000, font_family='Arial', font_weight='normal', font_style='normal', text_decoration='none', data_xml_escaped='true', text_anchor='start', dominant_baseline='alphabetic', line_height=1.125000, xml__space='preserve', data_doc_margin=4.0000, data_font_px=32.0000, data_scale=1.000000, data_raw_text='Text', data_box_w=67.0000, data_box_h=44.0000, data_auto_size=True, data_text_h='left', data_text_v='top', data_text_dir='ltr', direction='ltr', unicode_bidi='embed', transform='matrix(1.000000 0.000000 0.000000 1.000000 213.149606 -141.259843)')
    _text.escaped_text = ''
    _text.children.clear()
    _text.append_line('Text', x=4.0000, y=33.0000, direction='ltr', text_anchor='start')
    d.append(_text)

    _text = draw.Text("Text", 32.00, 4.00, 4.00, fill='#000000', opacity=1.000000, font_family='Arial', font_weight='normal', font_style='normal', text_decoration='none', data_xml_escaped='true', text_anchor='start', dominant_baseline='alphabetic', line_height=1.125000, xml__space='preserve', data_doc_margin=4.0000, data_font_px=32.0000, data_scale=1.000000, data_raw_text='Text', data_box_w=67.0000, data_box_h=44.0000, data_auto_size=True, data_text_h='left', data_text_v='top', data_text_dir='ltr', direction='ltr', unicode_bidi='embed', transform='matrix(1.000000 0.000000 0.000000 1.000000 223.149606 -221.259843)')
    _text.escaped_text = ''
    _text.children.clear()
    _text.append_line('Text', x=4.0000, y=33.0000, direction='ltr', text_anchor='start')
    d.append(_text)

    return d

if __name__ == '__main__':
    d = build_drawing()
    # Creates an SVG file next to the script:
    d.save_svg('canvas.svg')