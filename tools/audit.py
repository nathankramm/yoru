import collections, datetime, glob, importlib.util, os, random, shutil
import tempfile, types, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp()
sp = importlib.util.spec_from_file_location("y", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "yoru.py"))
m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
BUILTIN = dict(m.PAL)          # the Tokyo Night fallback, before any theme is applied
O = types.SimpleNamespace(scale=4, corner="br", margin=24, interval=300,
                          roam=180, cooldown=90, idle=300)
F = []; N = 0
def ck(n, ok, d=""):
    global N; N += 1
    print(("  PASS  " if ok else "  FAIL  ") + n + (("  " + str(d)) if d else ""))
    if not ok: F.append(n)

src = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "yoru.py")).read()
ck("1 hide toggle", "SIGUSR1" in src and "--start-hidden" in src)
ck("2 verification", "HYPR_TOPICS" in src and "--verify-report" in src)
ck("3 voice", (len(m.CHATTER), len(m.LATE), len(m.POKES)) == (32, 4, 7))
ck("4 motion", hasattr(m, "GRAZE_SHIFT") and hasattr(m, "BOUND")
   and hasattr(m.Pet, "bounding"))
ck("5 atomic writes", "os.replace" in src)
ck("6 debug flag", "--debug" in src)
ck("7 topics intact", len({t[0] for t in m.KNOWLEDGE}) >= 27,
   len({t[0] for t in m.KNOWLEDGE}))
ck("8 no duplicate ids", not [x for x, c in collections.Counter(
   m.tip_id(t) for t in m.KNOWLEDGE).items() if c > 1])
ck("9 nothing condescending", not [b for b in
   [x for _, _, _, x in m.KNOWLEDGE] + m.CHATTER + m.LATE + m.POKES
   if any(w in b.lower() for w in
   ["stupid", "idiot", "obviously", "noob", "dumb", "you should know"])])
p = m.Pet(O, m.KNOWLEDGE); p.seen = set(); p.known = set()
ck("10 full cycle no repeats",
   len({m.tip_id(p.pick()) for _ in range(len(m.KNOWLEDGE))}) == len(m.KNOWLEDGE))
ok = True
for (cls, full), want in {("foot", "foot nvim a.rb"): "neovim",
        ("foot", "foot lazygit"): "git",
        ("org.omarchy.agent", "org.omarchy.agent claude"): "agents"}.items():
    q = m.Pet(O, m.KNOWLEDGE)
    for _ in range(30):
        q.seen = set(); r = q.pick(cls=cls, context=full)
        if not r or r[0] != want: ok = False
ck("11 context routing", ok)
q = m.Pet(O, m.KNOWLEDGE)
ck("12 unknown app silent",
   all(q.pick(cls="steam", context="steam x") is None for _ in range(20)))
t = q.pick(); q.mark_known(t)
ck("13 retirement persists", m.tip_id(t) in m.load_known())
pp = m.Pet(O, m.KNOWLEDGE); pp.shown = 0
ck("14 chatter starts low", abs(pp.chatter_share() - 0.15) < 1e-9)
pp.shown = 10**6
ck("15 chatter caps", abs(pp.chatter_share() - 0.40) < 1e-9)
p = m.Pet(O, m.KNOWLEDGE); p.seen = set(); now = 0.0; p.step(.033, now, 1920, 1080)
for _ in range(int(3 * 3600 / .033)): now += .033; p.step(.033, now, 1920, 1080)
ck("16 3h idle spends nothing", len(p.seen) == 0)
gz = []; hm = []; tp = []; bd = 0; tg = mg = 0; spd = set()
for seed in range(8):
    random.seed(seed); p = m.Pet(O, m.KNOWLEDGE); p.seen = set()
    now = 0.0; p.step(.033, now, 1920, 1080)
    c = collections.Counter(); md = collections.Counter(); n = 0
    for i in range(int(7200 / .033)):
        now += .033
        if i % int(60 / .033) == 0: p.saw_activity(now)
        b = p.text; p.step(.033, now, 1920, 1080)
        if p.text and not b: n += 1
        c[p.pose] += 1; md[p.mode] += 1
        if p.bounding(): bd += 1
        if p.pose == "graze" and p.text: tg += 1
        if p.pose == "graze" and p.mode != "home": mg += 1
        if p.mode in ("out", "back"): spd.add(round(p.speed))
    tot = sum(c.values()); gz.append(c["graze"] / tot)
    hm.append(md["home"] / tot); tp.append(n)
ck("17 tips per 2h", all(15 <= x <= 40 for x in tp), "%d-%d" % (min(tp), max(tp)))
ck("18 parked 90%+", all(x > 0.90 for x in hm),
   "%.0f-%.0f%%" % (100 * min(hm), 100 * max(hm)))
ck("19 grazes 5-20%", all(0.05 < x < 0.20 for x in gz),
   "%.1f-%.1f%%" % (100 * min(gz), 100 * max(gz)))
ck("20 no graze talking/walking", tg == 0 and mg == 0)
ck("21 both gaits", bd > 0 and any(x > 120 for x in spd)
   and any(x <= 120 for x in spd))
real = m.datetime.datetime
class D(datetime.datetime):
    @classmethod
    def now(cls): return cls(2026, 9, 14, 14, 0)
m.datetime.datetime = D; pd = m.Pet(O, m.KNOWLEDGE); pd.shown = 0
day = {x for h, x in (pd.next_ambient() for _ in range(4000)) if h is None}
class Nt(datetime.datetime):
    @classmethod
    def now(cls): return cls(2026, 9, 14, 2, 0)
m.datetime.datetime = Nt
night = {x for h, x in (pd.next_ambient() for _ in range(4000)) if h is None}
m.datetime.datetime = real
ck("22 late lines only at night",
   not (day & set(m.LATE)) and bool(night & set(m.LATE)))
m._load_gtk(); import cairo
d = os.path.join(os.environ["HOME"], ".local/state/omarchy/current/theme")
os.makedirs(d, exist_ok=True); m.THEME_COLORS = os.path.join(d, "colors.toml")
def lum(x): return 0.2126 * x[0] + 0.7152 * x[1] + 0.0722 * x[2]
bad = []
themes = sorted(glob.glob("/usr/share/omarchy/themes/*/colors.toml"))
for f in themes:
    shutil.copy(f, m.THEME_COLORS); m.apply_theme()
    if abs(lum(m.PAL["b"]) - lum(m.OUTLINE)) < 0.25 or \
       abs(lum(m.PAL["c"]) - lum(m.PAL["b"])) < 0.03: bad.append(f.split("/")[-2])
ck("23 every shipped theme legible", not bad and len(themes) > 0,
   "%d themes, bad: %s" % (len(themes), bad))
os.remove(m.THEME_COLORS)
# No source at all: no resolver on PATH, no colors.toml. The built-in palette
# must stand untouched. PAL is mutated in place, so restore it first.
m.PAL.update(BUILTIN); m.THEME_COLORS = os.path.join(d, "does-not-exist.toml")
real_path = os.environ["PATH"]; os.environ["PATH"] = tempfile.mkdtemp()
r24 = m.apply_theme()
os.environ["PATH"] = real_path
ck("24 missing theme safe", r24 is False and m.PAL == BUILTIN,
   "returned %r, PAL %s" % (r24, "unchanged" if m.PAL == BUILTIN else "CHANGED"))
# Resolver only: omarchy-theme-color is back on PATH, colors.toml still absent,
# so a True here can only have come through the subprocess path. Caveat: the
# "PAL differs" clause would fail spuriously on a theme whose resolved palette
# reproduced the built-in five exactly; no shipped theme does (Tokyo Night
# itself resolves a different accent), so it is left as the second signal.
m.PAL.update(BUILTIN)
r27 = m.apply_theme() if shutil.which("omarchy-theme-color") else None
ck("27 resolver path exercised", r27 is True and m.PAL != BUILTIN,
   "returned %r, PAL %s" % (r27, "differs from built-in" if m.PAL != BUILTIN
                             else "IDENTICAL to built-in") if r27 is not None
   else "omarchy-theme-color not on PATH; nothing to exercise")
surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 600); cr = cairo.Context(surf)
over = []
for topic, mt, k, x in m.KNOWLEDGE:
    l = m.PangoCairo.create_layout(cr)
    l.set_font_description(m.Pango.FontDescription("monospace 10"))
    l.set_width(int(360 * m.Pango.SCALE)); l.set_wrap(m.Pango.WrapMode.WORD_CHAR)
    l.set_markup("<span>%s</span>\n%s" % (m.GLib.markup_escape_text(k),
                                          m.GLib.markup_escape_text(x)))
    if l.get_line_count() > 4: over.append((l.get_line_count(), k))
for line in m.CHATTER + m.LATE + m.POKES:
    l = m.PangoCairo.create_layout(cr)
    l.set_font_description(m.Pango.FontDescription("monospace 10"))
    l.set_width(int(360 * m.Pango.SCALE)); l.set_wrap(m.Pango.WrapMode.WORD_CHAR)
    l.set_text(line)
    if l.get_line_count() > 3: over.append((l.get_line_count(), line[:40]))
ck("25 everything fits the bubble", not over, over)
oob = [(pose, b, f) for pose in ("stand", "graze") for b in (False, True)
       for f in range(4) for e in (0, 1) for tl in (0, 1)
       if (lambda q: min(z[0] for z in q) < -3 or max(z[0] for z in q) > 27
           or min(z[1] for z in q) < -4 or max(z[1] for z in q) > 25)(
           m.pixels(f, False, pose, e, tl, b))]
ck("26 all pose combos in bounds", not oob, oob[:2])
print("\n%d/%d  FAILURES: %s" % (N - len(F), N, F or "none"))
