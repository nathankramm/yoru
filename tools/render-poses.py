"""Render every pose to a PNG, drawn the way draw_sprite draws them.

The audit can prove a pose stays in bounds and that the render key moves
when it should. It cannot tell you whether the pose reads as a deer at
rest or a deer that fell over. This can. Run it, open the PNG, look.

    python3 tools/render-poses.py                # built-in palette -> poses.png
    python3 tools/render-poses.py --theme        # the live Omarchy theme
    python3 tools/render-poses.py --zoom 16 out.png

To compare candidate drawings, replace the function under test on the
module before rendering (m._folded_legs = candidate) and add a cell per
candidate; that is how the resting pose was chosen.
"""
import importlib.util, os, sys
import cairo

here = os.path.dirname(os.path.abspath(__file__))
sp = importlib.util.spec_from_file_location("y", os.path.join(here, "..", "yoru.py"))
m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)

args = sys.argv[1:]
if "--theme" in args:
    args.remove("--theme"); m.apply_theme()
zoom = 12
if "--zoom" in args:
    i = args.index("--zoom"); zoom = int(args[i + 1]); del args[i:i + 2]
out = args[0] if args else "poses.png"

# (label, pixels() arguments, mirrored)
CELLS = [
    ("stand", dict(frame=1, blink=False, pose="stand"), False),
    ("trot 1 (on the pass)", dict(frame=1, blink=False, moving=True), False),
    ("stand, ear + tail", dict(frame=1, blink=False, pose="stand", ear=1, tail=1), False),
    ("graze", dict(frame=1, blink=False, pose="graze"), False),
    ("trot 0", dict(frame=0, blink=False, moving=True), False),
    ("trot 2", dict(frame=2, blink=False, moving=True), False),
    ("bound 0", dict(frame=0, blink=False, bound=True, moving=True), False),
    ("bound 2", dict(frame=2, blink=False, bound=True, moving=True), False),
    ("settle (between)", dict(frame=1, blink=False, pose="settle"), False),
    ("rest", dict(frame=1, blink=False, pose="rest"), False),
    ("rest, blink", dict(frame=1, blink=True, pose="rest"), False),
    ("rest, chew", dict(frame=1, blink=False, pose="rest", chew=1), False),
    ("rest, dozing", dict(frame=1, blink=False, pose="rest", doze=1), False),
    ("rest, ear + tail", dict(frame=1, blink=False, pose="rest", ear=1, tail=1), False),
    ("rest, facing left", dict(frame=1, blink=False, pose="rest"), True),
]
cw, ch = 28 * zoom, 30 * zoom
W, H = len(CELLS) * cw + zoom * 2, ch + zoom * 4
surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H); cr = cairo.Context(surf)
cr.set_source_rgb(*m.BUBBLE_BG); cr.paint()
cr.set_antialias(cairo.ANTIALIAS_NONE)
cr.set_source_rgba(1, 1, 1, 0.12)                   # the ground line: row 23
cr.rectangle(0, zoom * 2 + 24 * zoom, W, 1); cr.fill()
for i, (label, kw, flip) in enumerate(CELLS):
    ox, oy = zoom * 2 + i * cw + 2 * zoom, zoom * 2
    pts = m.pixels(**kw)
    def sx(x):
        return ox + ((m.SW - 1 - x) if flip else x) * zoom
    cr.set_source_rgba(*m.OUTLINE, 0.85)
    for x, y, _ in pts:
        cr.rectangle(sx(x) - 1, oy + y * zoom - 1, zoom + 2, zoom + 2)
    cr.fill()
    for x, y, col in pts:
        cr.set_source_rgb(*col); cr.rectangle(sx(x), oy + y * zoom, zoom, zoom); cr.fill()
    cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
    cr.set_source_rgba(1, 1, 1, 0.6); cr.select_font_face("monospace"); cr.set_font_size(11)
    cr.move_to(ox, H - zoom); cr.show_text(label)
    cr.set_antialias(cairo.ANTIALIAS_NONE)
surf.write_to_png(out); print(out)
