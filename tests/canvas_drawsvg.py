# Auto-generated from PySide6 Canvas to drawsvg
import drawsvg as draw

def build_drawing():
    d = draw.Drawing(311, 221, origin=(-162, -107), viewBox='-162 -107 311 221')
    d.append(draw.Rectangle(-162, -107, 311, 221, fill='white', stroke='none'))

    _circ = draw.Circle(50.00, 50.00, 50.00, fill='#62ff67', fill_opacity=1.00, stroke='#000000', stroke_width=2.00, data_label_id='circle_label_1', transform='matrix(1.000000 0.000000 0.000000 1.000000 -51.747302 -51.747302)')
    d.append(_circ)
    # Multiline label for circle_label_1
    _circle_label = draw.Text("rtrtdf", 16.00, 42.00, 14.00, fill='#000000', font_family='Arial', text_anchor='middle', dominant_baseline='alphabetic', line_height=1.125000, xml__space='preserve', data_shape_label='true', data_label_id='circle_label_1', data_label_h='center', data_label_v='middle', data_font_px=16.0000, data_label_kind='circle', transform='matrix(1.000000 0.000000 0.000000 1.000000 -43.747302 -10.747302)')
    d.append(_circle_label)

    _text = draw.Text("Text", 32.00, 4.00, 4.00, fill='#000000', font_family='Arial', text_anchor='start', dominant_baseline='text-before-edge', alignment_baseline='text-before-edge', line_height=1.125000, xml__space='preserve', data_doc_margin=4.0000, data_font_px=32.0000, data_scale=1.000000, data_box_w=100.0000, data_box_h=50.0000, data_text_h='left', data_text_v='top', data_text_dir='ltr', transform='matrix(1.000000 0.000000 0.000000 1.000000 -36.850394 58.740157)')
    d.append(_text)

    _text = draw.Text("Text", 32.00, 4.00, 4.00, fill='#000000', font_family='Arial', text_anchor='start', dominant_baseline='text-before-edge', alignment_baseline='text-before-edge', line_height=1.125000, xml__space='preserve', data_doc_margin=4.0000, data_font_px=32.0000, data_scale=1.000000, data_box_w=100.0000, data_box_h=50.0000, data_text_h='left', data_text_v='top', data_text_dir='ltr', transform='matrix(1.000000 0.000000 0.000000 1.000000 -156.850394 -31.259843)')
    d.append(_text)

    _text = draw.Text("Text", 32.00, 4.00, 4.00, fill='#000000', font_family='Arial', text_anchor='start', dominant_baseline='text-before-edge', alignment_baseline='text-before-edge', line_height=1.125000, xml__space='preserve', data_doc_margin=4.0000, data_font_px=32.0000, data_scale=1.000000, data_box_w=100.0000, data_box_h=50.0000, data_text_h='left', data_text_v='top', data_text_dir='ltr', transform='matrix(1.000000 0.000000 0.000000 1.000000 -26.850394 -101.259843)')
    d.append(_text)

    _text = draw.Text("Text", 32.00, 4.00, 4.00, fill='#000000', font_family='Arial', text_anchor='start', dominant_baseline='text-before-edge', alignment_baseline='text-before-edge', line_height=1.125000, xml__space='preserve', data_doc_margin=4.0000, data_font_px=32.0000, data_scale=1.000000, data_box_w=100.0000, data_box_h=50.0000, data_text_h='left', data_text_v='top', data_text_dir='ltr', transform='matrix(1.000000 0.000000 0.000000 1.000000 43.149606 -31.259843)')
    d.append(_text)

    return d

if __name__ == '__main__':
    d = build_drawing()
    # Creates an SVG file next to the script:
    d.save_svg('canvas.svg')