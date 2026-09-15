import drawsvg as draw

d = draw.Drawing(320, 240, origin=(0, 0))
_rect = draw.Rectangle(24, 36, 80, 40, fill="#4477aa", stroke="#112233")
d.append(_rect)
