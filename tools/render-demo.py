"""Render a scripted stretch of a character's life to a GIF and an MP4,
through the real draw path.

The deer's demo was a screen capture, and a capture can only show what the
machine happened to do while the recorder was running -- you wait for a
blink and re-record when the walk came out wrong. This drives the shipped
Pet instead: the same step(), the same draw_sprite() and draw_bubble() the
compositor gets, at the character's own scale, on the theme's own
background. The script says when to nudge him -- speak now, coffee now,
away now -- and everything between those nudges is his own timing, so what
the file shows is what the code does.

    python3 tools/render-demo.py --sprite dane --theme tokyo-night \
        docs/dane-motion.gif
    python3 tools/render-demo.py --sprite dane --acts turn --out /tmp/t.gif
    python3 tools/render-demo.py --sprite dane --acts head-down --fps 25

`--acts` renders a named part of the script on its own, which is how a
transition gets judged as motion rather than as a sheet of stills.
`--acts swap` is the transformation into the other character, and which way
round it goes is whichever `--sprite` it starts as. `--mp4`
is written beside the GIF unless `--no-mp4`. Needs ffmpeg.
"""
import importlib.util, os, shutil, subprocess, sys, tempfile

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
sp = importlib.util.spec_from_file_location("y", os.path.join(root, "yoru.py"))
m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)

args = sys.argv[1:]


def opt(flag, default=None, cast=str):
    if flag in args:
        i = args.index(flag)
        v = args[i + 1]; del args[i:i + 2]
        return cast(v)
    return default


def flag(name):
    if name in args:
        args.remove(name); return True
    return False


sprite = opt("--sprite", "dane")
theme = opt("--theme", "tokyo-night")
fps = opt("--fps", 25, int)
scale = opt("--scale", None, int)
want = opt("--acts", "")
no_mp4 = flag("--no-mp4")
out = opt("--out") or (args[0] if args else "demo.gif")

if theme and theme != "none":
    # A shipped theme by name, the way render-poses.py does it: point the
    # parser at its file and keep the resolver off PATH, or apply_theme()
    # reads whatever the machine is wearing.
    m.THEME_COLORS = "/usr/share/omarchy/themes/%s/colors.toml" % theme
    path, os.environ["PATH"] = os.environ["PATH"], ""
    ok = m.apply_theme(); os.environ["PATH"] = path
    if not ok:
        sys.exit("no theme called %r under /usr/share/omarchy/themes" % theme)

m._load_gtk()                      # draw_bubble needs Pango; draw_sprite needs nothing
import cairo

# The deer's demo is 520x272 because it was a screen capture and he needed
# room to walk. This one is tighter: The Dane does not roam, so the frame
# is what is around him and a bubble's width either side of it.
W, H = 460, 200
DT = 1.0 / fps


class Clock:
    """A Pet driven off a script rather than a wall clock, so a render is
    the same every time it is made."""

    def __init__(self, sprite, scale):
        import types
        o = types.SimpleNamespace(scale=scale, corner="br", margin=24, interval=300,
                                  roam=1e9, cooldown=90, idle=300, sprite=sprite,
                                  quiet=False, still=False, no_basics=True)
        self.pet = m.Pet(o, m.KNOWLEDGE)
        self.t = 0.0
        self.pet.place(W, H)
        # Centered, and on the bottom edge, which is where he actually
        # lives: the bottom of the screen is the ground.
        self.pet.home_x = self.pet.x = (W - self.pet.w) // 2
        self.pet.home_y = self.pet.y = H - self.pet.h
        self.pet.present_until = 1e9
        self.pet.next_talk = 1e9
        self.pet.next_roam = 1e9
        self.quiet_idles()

    def quiet_idles(self):
        self.pet.next_idle = [1e9] * len(self.pet.next_idle)

    def run(self, secs, draw):
        for _ in range(int(round(secs / DT))):
            self.t += DT
            self.pet.step(DT, self.t, W, H)
            draw(self.pet)


def frame_painter(outdir):
    n = [0]

    def draw(pet):
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
        cr = cairo.Context(surf)
        cr.set_source_rgb(*m.OUTLINE)              # the theme background
        cr.paint()
        cr.set_antialias(cairo.ANTIALIAS_NONE)
        m.draw_sprite(cr, pet, pet.y)
        if pet.text:
            cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
            m.draw_bubble(cr, pet, pet.y, W)
        surf.write_to_png(os.path.join(outdir, "f%05d.png" % n[0]))
        n[0] += 1
    return draw


def idle_named(pet, name):
    """The index of a character's idle action, by its held pose."""
    for i, act in enumerate(pet.character.idles):
        if act.pose == name:
            return i
    raise SystemExit("%s has no idle called %r" % (pet.character.name, name))


# The script. Each act is (name, function): the function nudges him and
# then hands the clock however many seconds that act is worth. Nothing in
# here draws; the timing of every pose between the nudges is the Pet's.
def acts(c, draw):
    pet = c.pet

    def working():
        c.run(2.6, draw)                       # at it, eyes down; the blink is his

    def coffee():
        pet.next_idle[idle_named(pet, "sip")] = 0.0
        c.run(6.0, draw)
        c.quiet_idles()

    def beard():
        pet.next_idle[idle_named(pet, "beard")] = 0.0
        c.run(4.0, draw)
        c.quiet_idles()

    def speaking():
        pet.say("Super + Space", "The Omarchy menu. Almost everything starts "
                                 "here, which is the point of it.", 6.0, c.t)
        c.run(8.4, draw)                       # lid down, look up, the bubble, and back

    def swap():
        # The transformation, driven by the signal the key sends. Both
        # characters are drawn through the dissolve, so this is the only
        # act whose canvas is not one character's.
        c.run(0.7, draw)
        pet.request_swap()
        c.run(2.1, draw)                       # laptop, dissolve, laptop again
        c.run(0.9, draw)

    def head_down():
        pet.snooze_until = c.t + 5.0
        c.run(5.0, draw)                       # lid closes, head goes down, he stays
        pet.snooze_until = 0.0
        c.run(2.4, draw)                       # and back up to work

    return [("working", working), ("coffee", coffee), ("beard", beard),
            ("speaking", speaking), ("head-down", head_down), ("swap", swap)]


# What the shipped demo is: a minute of his day, in the order it reads
# best. The beard stroke is not in it -- it is the rare one, and a demo
# that shows the rare thing next to the common one tells you the wrong
# thing about how often you will see it. `--acts beard` renders it.
SCRIPT = ("working", "coffee", "speaking", "head-down")


tmp = tempfile.mkdtemp(prefix="yoru-demo-")
try:
    c = Clock(sprite, scale)
    draw = frame_painter(tmp)
    script = acts(c, draw)
    names = want.split(",") if want else SCRIPT
    script = [a for a in script if a[0] in names]
    if not script:
        sys.exit("no act called %r; have %s" % (want, ", ".join(a for a, _ in acts(c, draw))))
    for name, fn in script:
        fn()
    n = len(os.listdir(tmp))
    if not n:
        sys.exit("nothing rendered")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    src = os.path.join(tmp, "f%05d.png")
    pal = os.path.join(tmp, "pal.png")
    run = lambda *a: subprocess.run(a, check=True, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
    # One palette for the whole clip: the scene is flat theme colours, so a
    # per-frame palette only buys dithering noise on the halo.
    run("ffmpeg", "-y", "-framerate", str(fps), "-i", src,
        "-vf", "palettegen=stats_mode=full", pal)
    run("ffmpeg", "-y", "-framerate", str(fps), "-i", src, "-i", pal,
        "-lavfi", "paletteuse=dither=none", "-loop", "0", out)
    print("%s  (%d frames, %.1fs at %dfps, %.0f KiB)"
          % (out, n, n / fps, fps, os.path.getsize(out) / 1024))
    if not no_mp4:
        mp4 = os.path.splitext(out)[0] + ".mp4"
        run("ffmpeg", "-y", "-framerate", str(fps), "-i", src,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryslow",
            "-crf", "20", "-movflags", "+faststart", mp4)
        print("%s  (%.0f KiB)" % (mp4, os.path.getsize(mp4) / 1024))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
