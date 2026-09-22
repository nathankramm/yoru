"""Render every pose to a PNG, drawn the way draw_sprite draws them.

The audit can prove a pose stays in bounds and that the render key moves
when it should. It cannot tell you whether the pose reads as a deer at
rest or a deer that fell over. This can. Run it, open the PNG, look.

    python3 tools/render-poses.py                # built-in palette -> poses.png
    python3 tools/render-poses.py --theme        # the live Omarchy theme
    python3 tools/render-poses.py --theme catppuccin-latte   # a shipped one, by name
    python3 tools/render-poses.py --zoom 16 out.png
    python3 tools/render-poses.py --sprite dane              # The Dane, at his own scale
    python3 tools/render-poses.py --sprite dane --cells coffee          # only those cells

The background is the theme's own, the colour the halo is drawn in: the
harshest case, and the common one, since he mostly stands over a terminal.
Judge at --zoom 4. A magnified sheet has been wrong about what reads too
many times to be trusted on its own.

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
sprite = "yoru"
if "--sprite" in args:
    i = args.index("--sprite"); sprite = args[i + 1]; del args[i:i + 2]
if "--theme" in args:
    i = args.index("--theme")
    name = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("--") \
        and not args[i + 1].endswith(".png") else None
    del args[i:i + (2 if name else 1)]
    if name:
        # A shipped theme by name: point the parser at its file and keep
        # the resolver off PATH, or apply_theme() would read the live one.
        m.THEME_COLORS = "/usr/share/omarchy/themes/%s/colors.toml" % name
        path, os.environ["PATH"] = os.environ["PATH"], ""
        ok = m.apply_theme(); os.environ["PATH"] = path
        if not ok:
            sys.exit("no theme called %r under /usr/share/omarchy/themes" % name)
    else:
        m.apply_theme()
ch = m.SPRITES[sprite]
zoom = 12 if sprite == "yoru" else ch.scale       # the deer's sheet was always 12
if "--zoom" in args:
    i = args.index("--zoom"); zoom = int(args[i + 1]); del args[i:i + 2]
only = []
if "--cells" in args:
    i = args.index("--cells"); only = args[i + 1].split(","); del args[i:i + 2]
out = args[0] if args else "poses.png"

# (label, pixels() arguments, mirrored)
# The Dane's sheet is his transitions in the order he plays them, so a
# row of cells is the motion laid out flat: the coffee out and back, the
# beard stroke, the lid folding to speak, and the lid folding the other
# way with his head going down behind it.
DANE_CELLS = [
    ("working (eyes down)", dict(frame=1, blink=False, view="work", tic=0), False),
    ("coffee: reach", dict(frame=1, blink=False, pose="reach", view="work"), False),
    ("coffee: lift", dict(frame=1, blink=False, pose="lift", view="work"), False),
    ("coffee: carry", dict(frame=1, blink=False, pose="carry", view="work"), False),
    ("coffee: sip", dict(frame=1, blink=False, pose="sip", view="work"), False),
    ("beard: raise", dict(frame=1, blink=False, pose="raise", view="work"), False),
    ("beard: stroke", dict(frame=1, blink=False, pose="beard", view="work"), False),
    ("lid folding", dict(frame=1, blink=False, view="folding"), False),
    ("lid closing", dict(frame=1, blink=False, view="closing"), False),
    ("speaking (eyes up)", dict(frame=1, blink=False, view="speak"), False),
    ("speaking, blink", dict(frame=1, blink=True, view="speak"), False),
    ("settle (going down)", dict(frame=1, blink=False, pose="settle", view="closing"), False),
    ("head down", dict(frame=1, blink=False, pose="rest", view="closing"), False),
    ("head down, blink", dict(frame=1, blink=True, pose="rest", view="closing"), False),
]
CELLS = [
    ("stand", dict(frame=1, blink=False, pose="stand"), False),
    ("stand, ear + wag", dict(frame=1, blink=False, pose="stand", ear=1, tail=1), False),
    ("graze", dict(frame=1, blink=False, pose="graze"), False),
    ("walk 0", dict(frame=0, blink=False, gait="walk"), False),
    ("walk 1 (nod)", dict(frame=1, blink=False, gait="walk"), False),
    ("walk 2", dict(frame=2, blink=False, gait="walk"), False),
    ("walk 3 (nod)", dict(frame=3, blink=False, gait="walk"), False),
    ("trot 0 (unused)", dict(frame=0, blink=False, gait="trot"), False),
    ("trot 1 (on the pass)", dict(frame=1, blink=False, gait="trot"), False),
    ("bound 0, flag", dict(frame=0, blink=False, gait="bound", tail=2), False),
    ("bound 2, flag", dict(frame=2, blink=False, gait="bound", tail=2), False),
    ("settle (between)", dict(frame=1, blink=False, pose="settle"), False),
    ("rest", dict(frame=1, blink=False, pose="rest"), False),
    ("rest, blink", dict(frame=1, blink=True, pose="rest"), False),
    ("rest, chew", dict(frame=1, blink=False, pose="rest", chew=1), False),
    ("rest, dozing", dict(frame=1, blink=False, pose="rest", doze=1), False),
    ("rest, ear + wag", dict(frame=1, blink=False, pose="rest", ear=1, tail=1), False),
    ("rest, facing left", dict(frame=1, blink=False, pose="rest"), True),
]
if sprite == "dane":
    CELLS = DANE_CELLS
if only:
    # A name that is exactly a label picks that one cell; anything else is
    # a prefix, so "coffee" is the whole action and "head down" on its own
    # is not also "head down, blink". Cells come out in the order asked
    # for, which is how the README sheet is arranged.
    picked = []
    for n in only:
        for c in ([c for c in CELLS if c[0] == n] or [c for c in CELLS if c[0].startswith(n)]):
            if c not in picked:
                picked.append(c)
    CELLS = picked
cw, chh = (ch.w + 4) * zoom, (ch.h + 6) * zoom
# Labels need room the sprite doesn't at 4px: widen the cell to fit them.
cw = max(cw, 150) if zoom < 8 else cw
W, H = len(CELLS) * cw + zoom * 2, chh + max(zoom * 4, 24)
surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H); cr = cairo.Context(surf)
cr.set_source_rgb(*m.OUTLINE); cr.paint()            # the theme background
cr.set_antialias(cairo.ANTIALIAS_NONE)
ink = (1, 1, 1) if m._lum(m.OUTLINE) < 0.5 else (0, 0, 0)
cr.set_source_rgba(*ink, 0.12)                       # the ground line: the last row
cr.rectangle(0, zoom * 2 + ch.h * zoom, W, 1); cr.fill()
for i, (label, kw, flip) in enumerate(CELLS):
    ox, oy = zoom * 2 + i * cw + 2 * zoom, zoom * 2
    pts = ch.pixels(**kw)
    def sx(x):
        return ox + ((ch.w - 1 - x) if flip else x) * zoom
    cr.set_source_rgba(*m.OUTLINE, 0.85)
    for x, y, _ in pts:
        cr.rectangle(sx(x) - 1, oy + y * zoom - 1, zoom + 2, zoom + 2)
    cr.fill()
    for x, y, col in pts:
        cr.set_source_rgb(*col); cr.rectangle(sx(x), oy + y * zoom, zoom, zoom); cr.fill()
    cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
    cr.set_source_rgba(*ink, 0.6); cr.select_font_face("monospace"); cr.set_font_size(11)
    cr.move_to(ox, H - 6); cr.show_text(label)
    cr.set_antialias(cairo.ANTIALIAS_NONE)
surf.write_to_png(out); print(out)
