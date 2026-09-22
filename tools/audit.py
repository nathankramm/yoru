import collections, datetime, glob, importlib.util, os, random, shutil
import statistics, tempfile, types, sys, re, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REAL_HOME = os.environ.get("HOME", "")      # for the one check that reads a real user file
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


def quiet_idles(q):
    """Park every idle action a character has, so a check that is about
    something else never has a graze or a coffee happening through it."""
    q.next_idle = [1e9] * len(q.next_idle)
    return q

src = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "yoru.py")).read()
ck("1 hide toggle", "SIGUSR1" in src and "--start-hidden" in src)
ck("2 verification", "HYPR_TOPICS" in src and "--verify-report" in src)
# Ranges, not exact counts: an exact triple fails every time a line is added,
# which tells you nothing. What matters is that all three sets are populated.
ck("3 voice", len(m.CHATTER) >= 30 and len(m.LATE) >= 4 and len(m.POKES) >= 5,
   "%d chatter, %d late, %d pokes" % (len(m.CHATTER), len(m.LATE), len(m.POKES)))
ck("4 motion", hasattr(m, "GRAZE_SHIFT") and hasattr(m, "REST_SHIFT")
   and hasattr(m, "BOUND") and hasattr(m.Pet, "bounding"))
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
    p.passes = 0            # check 10 cycled the corpus in this HOME: state.json says passes=1
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
bad = []; hoof = []; shut_eye = []
themes = sorted(glob.glob("/usr/share/omarchy/themes/*/colors.toml"))
for f in themes:
    shutil.copy(f, m.THEME_COLORS); m.apply_theme()
    if abs(lum(m.PAL["b"]) - lum(m.OUTLINE)) < 0.25 or \
       abs(lum(m.PAL["c"]) - lum(m.PAL["b"])) < 0.03: bad.append(f.split("/")[-2])
    # The resting hooves are two-pixel marks in the strip of shade under
    # him, and only value separates them from it. The pick between the two
    # hoof tones is made per theme; here is whether it was enough, and what
    # the tone not picked would have given.
    other = m.HOOF if m.REST_HOOF == m.FAR_HOOF else m.FAR_HOOF
    hoof.append((abs(lum(m.REST_HOOF) - lum(m.FAR)), abs(lum(other) - lum(m.FAR)), f.split("/")[-2]))
    # ...and the shut eye, a pixel of the same shade in the coat, off the coat
    if abs(lum(m.FAR) - lum(m.PAL["b"])) < 0.10: shut_eye.append(f.split("/")[-2])
ck("23 every shipped theme legible", not bad and len(themes) > 0,
   "%d themes, bad: %s" % (len(themes), bad))
thin = [(n, round(g, 3)) for g, _, n in hoof if g < 0.12]
ck("48 resting hooves stand off the shade, and the shut eye off the coat, in every theme",
   not thin and not shut_eye and len(hoof) > 0,
   "%d themes, tightest %s at %.3f (other tone would give %.3f); under 0.12: %s; shut eye under 0.10: %s" % (
       (len(hoof),) + (min(hoof)[2], min(hoof)[0], min(hoof)[1], thin or "none", shut_eye or "none")
       if hoof else (0, "-", 0, 0, "no themes", "-")))
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
# Check 25 owns rendering: it measures Pango lines, so a 98-character tip that
# wraps to three lines still passes it. This one counts characters. 93 is not
# a rendering limit; it is the observed corpus maximum (Super + K has been 93
# since the first commit), and a line past it is a line nobody has read yet.
longest = max((len(x), x) for x in [t[3] for t in m.KNOWLEDGE] + m.CHATTER + m.LATE + m.POKES)
long_lines = [(len(x), x[:50]) for x in [t[3] for t in m.KNOWLEDGE] + m.CHATTER + m.LATE + m.POKES
              if len(x) > 93]
ck("28 nothing over 93 characters", not long_lines,
   "longest %d" % longest[0] if not long_lines else long_lines)
GAITS = (None, "walk", "trot", "bound")
oob = [(pose, g, f) for pose in ("stand", "graze", "rest", "settle") for g in GAITS
       for f in range(4) for e in (0, 1) for tl in (0, 1, 2)
       if (lambda q: min(z[0] for z in q) < -3 or max(z[0] for z in q) > 27
           or min(z[1] for z in q) < -4 or max(z[1] for z in q) > 25)(
           m.pixels(f, False, pose, e, tl, g))]
ck("26 all pose combos in bounds", not oob, oob[:2])
# A floating pixel is a rendering fault in any pose, and a pixel-diff that
# only looks at what was removed passes an added one happily. Every pixel of
# every combination -- pose, gait, frame, blink, ear, tail, chew, doze,
# parked or moving -- must have an 8-neighbor in the sprite, and the sprite
# must be one piece. Parked he does not bob; walking he is level with one
# foot in the air, knee bent; trotting, the body rises a row on frames 1 and
# 3 and the legs lengthen to meet it; bounding, the legs lift with the body.
# So every frame is one piece. It was five, parked and
# on the trot's pass frames, from the first commit until the bob stopped
# applying to a standing animal.
def neighbors(p, pts):
    return [(p[0] + dx, p[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            if (dx or dy) and (p[0] + dx, p[1] + dy) in pts]
def components(pts):
    seen = set(); n = 0
    for p in pts:
        if p in seen: continue
        n += 1; stack = [p]; seen.add(p)
        while stack:
            for q in neighbors(stack.pop(), pts):
                if q not in seen: seen.add(q); stack.append(q)
    return n
lonely = []; pieces = collections.Counter(); combos = 0
for pose in ("stand", "graze", "rest", "settle"):
    for g in GAITS:
        for f in range(4):
            for e in (0, 1):
                for tl in (0, 1, 2):
                    for chew in (0, 1):
                        for doze in (0, 1):
                            for blink in (False, True):
                                combos += 1
                                pts = {(x, y) for x, y, _ in m.pixels(f, blink, pose, e, tl, g, chew, doze)}
                                lonely += [(pose, g, f, p) for p in pts if not neighbors(p, pts)]
                                pieces[(pose, g or "parked", f, components(pts))] += 1
multi = sorted({(pose, g, f, n) for (pose, g, f, n), _ in pieces.items() if n > 1})
# parked he must not bob at all: the body (rows 0-17) sits where frame 0's
# does on every frame; trotting it rises on frames 1 and 3; walking it is
# level, head included -- the walk's head nod was tried and cut (see WALK
# in yoru.py), so a moving skull here is a regression, not accuracy
body = lambda f, g, top=17: sorted(p for p in m.pixels(f, False, "stand", gait=g) if p[1] <= top)
still = all(body(f, None) == body(0, None) for f in range(4)) and body(1, "trot") != body(0, "trot")
level = all(body(f, "walk") == body(0, None) for f in range(4))
ck("51 every frame one piece, no floating pixel, no bob while parked, walk level head and all", not lonely and not multi and still and level,
   "%d combinations, floating: %s; more than one piece: %s; parked body still and trotting body rises: %s; walking body level, rows 0-17: %s" % (
       combos, lonely[:3] or "none", ", ".join("%s %s frame %d -> %d" % x for x in multi) or "none", still, level))
# The walk is four-beat: in every frame exactly one hoof is off the ground,
# each leg takes its turn, and the order is the lateral sequence -- near
# hind, near fore, far hind, far fore. The trot is two-beat: all four hooves
# on the ground with diagonal pairs in phase. The roam is a walk (the trot
# was tried for it and reverted, see WALK in yoru.py), the bolt a bound;
# the flag flies only in the bound and the wag never does.
def hooves(f, g):
    pts = m.pixels(f, False, "stand", gait=g)
    return sorted((x, y) for x, y, c in pts if c in (m.HOOF, m.FAR_HOOF))
lifted = [[p for p in hooves(f, "walk") if p[1] == 22] for f in range(4)]
one_up = all(len(l) == 2 and len(hooves(f, "walk")) == 8 for f, l in enumerate(lifted))
# which leg: the near hind is drawn at x 3-4 (+d2), near fore 13-14, far hind 6-7, far fore 10-11
def which(l):
    x = l[0][0]
    return "nr" if x <= 5 else "fr" if x <= 8 else "ff" if x <= 12 else "nf"
order = [which(l) for l in lifted if l]
trot_down = all(all(p[1] == 23 for p in hooves(f, "trot")) for f in range(4))
q = m.Pet(O, m.KNOWLEDGE); q.seen = set(); q.present_until = 1e9; q.next_talk = 1e9; quiet_idles(q)
q.step(.033, 0.0, 1920, 1080)
gaits = collections.Counter(); flags = collections.Counter(); wags = collections.Counter(); t = 0.0
random.seed(5)
for i in range(int(3600 / .033)):
    t += .033; q.step(.033, t, 1920, 1080)
    g = q.gait(); gaits[g] += 1
    if q.tail_frame() == 2: flags[g] += 1
    if q.tail_frame() == 1: wags[g] += 1
ck("52 the roam is a four-beat walk; the flag flies in the bound only; the wag never does",
   one_up and order == ["nr", "nf", "fr", "ff"] and trot_down and gaits["walk"] > 0 and gaits["bound"] > 0
   and gaits["trot"] == 0 and set(flags) <= {"bound"} and flags["bound"] > 0 and "bound" not in wags and wags[None] > 0,
   "walk: one hoof up per frame %s, order %s; trot: all down %s; 1h: %d walk frames, %d bound, %d trot; flag in %s; wag in %s" % (
       one_up, order, trot_down, gaits["walk"], gaits["bound"], gaits["trot"], dict(flags), dict(wags)))
# The legs merge, and this is the ratchet that keeps it from getting
# worse. Every leg is a 2px column, and in a clean frame each drawn row
# below the body is runs of at most 2; in the shipped sprite 14 of the 16
# gait and settle frames have a wider run, and the walk's crossings are
# partial covers -- a far leg with one column left showing beside the
# near leg that overdrew it. Both counts may fall, never rise. The rules
# a clean drawing would meet (a far leg fully covered or not at all;
# legs of one tone never touching) and three drawings that met them are
# recorded at WALK in yoru.py; all read worse running at 4px than this.
LEG_AX = dict(nr=3, fr=6, ff=10, nf=13)          # as pixels() draws them
def gait_legs(g, f):
    """Each leg's pixels in one frame of the walk or the trot, by leg."""
    rows = collections.defaultdict(dict)
    for k, ax in LEG_AX.items():
        if g == "walk":
            w = m.WALK[(f - m.WALK_PHASE[k]) % 4]; d1, d2, up, top = w["d1"], w["d2"], w["up"], 18
        else:
            t = m.TROT[f if k[0] == "n" else (f + 2) % 4]
            d1, d2 = (t["r1"], t["r2"]) if k[1] == "r" else (t["f1"], t["f2"]); up = 0; top = 18 + m.BOB[f]
        pts = []; m._leg(pts, ax, d1, d2, k, k, 0, top, None, up)
        for x, y, _ in pts: rows[y].setdefault(k, set()).add(x)
    return rows
partial = [(g, f, y, a, b) for g in ("walk", "trot") for f in range(4) for y, r in gait_legs(g, f).items()
           for a in r for b in r if a < b and r[a] & r[b] and r[a] != r[b]]
def leg_runs(pose, g, f):
    dy = (m.BOB[f] if g == "trot" else m.BOUND[f]["lift"] if g == "bound"
          else m.SETTLE_SHIFT[1] if pose == "settle" else 0)
    rows = collections.defaultdict(list)
    for x, y, _ in m.pixels(f, False, pose, gait=g):
        if y > 17 + dy: rows[y].append(x)
    for y, xs in rows.items():
        xs = sorted(set(xs)); run = 1
        for a, b in zip(xs, xs[1:]):
            run = run + 1 if b == a + 1 else 1
            if run > 2: yield (pose, g, f, y, xs)
wide = sorted({w[:3] for pose, g in (("stand", "walk"), ("stand", "trot"), ("stand", "bound"), ("settle", None))
               for f in range(4) for w in leg_runs(pose, g, f)})
MERGED, PARTIAL = 14, 23
ck("56 leg merges: no more than the known %d frames with a wide leg row and %d partial-cover rows" % (MERGED, PARTIAL),
   len(wide) <= MERGED and len(partial) <= PARTIAL,
   "%d of 16 frames with a leg row wider than 2: %s; %d partial-cover rows (%d walk, %d trot)" % (
       len(wide), ", ".join("%s %s %d" % (p, g or "parked", f) for p, g, f in wide) or "none",
       len(partial), sum(p[0] == "walk" for p in partial), sum(p[0] == "trot" for p in partial)))
# Tips generated from the user's own bindings.lua replace the curated tip for
# a key the user rebound and add the rest. Afterwards no key may be covered
# twice and every id must be unique. Run against the real file when there is
# one, then against an empty one.
own_path = os.path.join(REAL_HOME, ".config/hypr/bindings.lua")
before = list(m.KNOWLEDGE)
own, replaced = m.own_bind_tips(own_path) if os.path.exists(own_path) else ([], {})
active = [t for t in m.KNOWLEDGE if m.tip_id(t) not in replaced] + own
# The curated set deliberately covers a few keys twice for different windows
# (Super + T for btop, Space for nautilus); what must not happen is an own tip
# sharing a key with any curated tip that is still active, or with another
# own tip.
curated_keys = {(p[0], k) for t in active if t[0] != "yours"
                for p in [m.parse_keys(t[2])] if p for k in p[1]}
own_keys = [m._own_key(t[2]) for t in own]
twice = [m._own_label(t[2]) for t in own if m._own_key(t[2]) in curated_keys] + \
        [k for k, c in collections.Counter(own_keys).items() if c > 1]
ids = [m.tip_id(t) for t in active]
empty_dir = tempfile.mkdtemp(); empty_lua = os.path.join(empty_dir, "bindings.lua")
open(empty_lua, "w").write('-- nothing here\nhl.unbind("SUPER + SHIFT + B")\n')
empty, empty_replaced = m.own_bind_tips(empty_lua)
ck("29 own-bind tips replace, never duplicate", not twice and len(ids) == len(set(ids))
   and own == own[:m.OWN_CAP] and not empty and not empty_replaced and m.KNOWLEDGE == before
   and all(r in {m.tip_id(t) for t in m.KNOWLEDGE} for r in replaced),
   "%d own, %d curated replaced (%s); keys covered twice %s; empty file -> %d" % (
       len(own), len(replaced), ", ".join(sorted(replaced)) or "none", twice, len(empty)))
# The fundamentals tier. Fresh state: the first picks are all fundamentals,
# then the pool opens. Context ignores the tier. A user who has seen most of
# the corpus gets exactly the old draw. --no-basics gets it from the start.
def fresh_pet(**kw):
    q = m.Pet(types.SimpleNamespace(**dict(vars(O), **kw)), m.KNOWLEDGE)
    q.seen = set(); q.known = set(); q.shown = 0
    return q
ids_all = {m.tip_id(t) for t in m.KNOWLEDGE}
fund_ok = m.FUNDAMENTAL <= ids_all
q = fresh_pet(); nf = len(m.FUNDAMENTAL)
first = [m.tip_id(q.pick()) for _ in range(nf)]
tier_first = set(first) == set(m.FUNDAMENTAL)             # each exactly once
later = {m.tip_id(q.pick()) for _ in range(60)}
opened = bool(later - m.FUNDAMENTAL)                        # pool opened up
q = fresh_pet(); q.known = {sorted(m.FUNDAMENTAL)[0]}       # retiring one doesn't hold it open
retired_ok = len({m.tip_id(q.pick()) for _ in range(nf - 1)}) == nf - 1 and \
             m.tip_id(q.pick()) not in m.FUNDAMENTAL
q = fresh_pet()
ctx = q.pick(cls="foot", context="foot nvim a.rb")            # context wins over the tier
context_ok = ctx is not None and ctx[0] == "neovim"
q = fresh_pet(); q.shown = 150
q.seen = ids_all - {"agents:omarchy-mise-install", "tmux:tsl [count] [command]"}
veteran = {m.tip_id(q.pick()) for _ in range(2)}
veteran_ok = veteran == {"agents:omarchy-mise-install", "tmux:tsl [count] [command]"}
skip = any(m.tip_id(fresh_pet(no_basics=True).pick()) not in m.FUNDAMENTAL for _ in range(40))
ck("30 fundamentals first, then everything", fund_ok and tier_first and opened
   and retired_ok and context_ok and veteran_ok and skip,
   "%d fundamentals; first %d picks: %s; then %d others seen; context %s; veteran %s; --no-basics %s"
   % (nf, nf, "all fundamentals" if tier_first else first, len(later - m.FUNDAMENTAL),
      "wins" if context_ok else "LOST", "unchanged" if veteran_ok else veteran,
      "skips" if skip else "STILL GATED"))
# A monitor is unplugged mid-run: the compositor moves the surface to a
# smaller output and step() starts receiving the new size. He must end up
# inside it — position, home and the input region alike — and a walk must
# not carry him off the bottom.
q = m.Pet(O, m.KNOWLEDGE); q.place(1920, 1054)
q.home_x = q.home_y = None
q.x, q.y = 1920 - q.w - 4, 1054 - q.h - 4          # dragged to the far corner
q.home_x, q.home_y = q.x, q.y
q.step(.033, 1.0, 1920, 1054)
q.step(.033, 1.033, 1280, 774)                       # the surface shrank
def inside(w, h): return (4 <= q.x <= w - q.w - 4 and 4 <= q.y <= h - q.h
                          and 4 <= q.home_x <= w - q.w - 4 and 4 <= q.home_y <= h - q.h)
migrated = inside(1280, 774)
region = (int(q.x), int(q.y), int(q.w), int(q.h)); landed = (q.x, q.y, q.home_x, q.home_y)
region_ok = region[0] >= 0 and region[1] >= 0 and region[0] + region[2] <= 1280 and region[1] + region[3] <= 774
# The roam gap: a stranded y used to survive a walk. Force a walk at the new
# size from an off-surface y and check he is on it while walking.
q.y = q.home_y = 900; q.next_roam = 0; q.pause = 0; q.mode = "home"
for i in range(12): q.step(.033, 2.0 + i * .033, 1280, 774)   # he is away, so up off the ground first
walk_ok = q.mode == "out" and 4 <= q.y <= 774 - q.h
# And the reverse: a bigger surface changes nothing he can see.
q2 = m.Pet(O, m.KNOWLEDGE); q2.place(1280, 774); q2.step(.033, 1.0, 1280, 774)
was = (q2.x, q2.y); q2.step(.033, 1.033, 1920, 1054)
grow_ok = (q2.x, q2.y) == was
ck("31 migration to a smaller surface keeps him reachable", migrated and region_ok and walk_ok and grow_ok,
   "after 1920x1054 -> 1280x774: at (%d,%d), home (%d,%d), region %s; walk from y=900 -> y=%d; grow %s"
   % (landed + (region, q.y, "unchanged" if grow_ok else "MOVED")))
# The package check. Every mapped id is a real tip and every package name is
# shaped like one; a fake installed set withholds exactly the tips of the
# packages it lacks; an unknowable set (pacman missing or failing) withholds
# nothing. The live query is exercised too, once, so a broken pacman call
# shows up here rather than as a silent no-op on every machine.
ids_all = {m.tip_id(t) for t in m.KNOWLEDGE}
mapped = [tid for tids in m.NEEDS.values() for tid in tids]
map_ok = all(tid in ids_all for tid in mapped) and len(mapped) == len(set(mapped)) \
    and all(re.fullmatch(r"[a-z0-9][a-z0-9.+_-]*", pkg) for pkg in m.NEEDS)
have = set(m.NEEDS) - {"ghostty", "spotify"}
gone = m.missing_package_tips(have)
expect = set(m.NEEDS["ghostty"]) | set(m.NEEDS["spotify"])
fake_ok = set(gone) == expect and all(v.endswith("not installed") for v in gone.values())
open_ok = m.missing_package_tips(None) == {} and m.missing_package_tips(set(m.NEEDS)) == {}
live = m.installed_packages()
live_ok = live is None or (len(live) > 100 and "pacman" in live)
ck("32 missing software withholds only its own tips", map_ok and fake_ok and open_ok and live_ok,
   "%d tips over %d packages; fake set -> %d withheld as expected; pacman unavailable -> 0; live query: %s"
   % (len(mapped), len(m.NEEDS), len(gone),
      "%d packages" % len(live) if live else "unavailable (fails open)"))
# --monitor lives in autostart.lua, and a laptop boots undocked: an unknown
# connector must warn, name what is connected, and fall through to the
# compositor's choice — never exit. Pure resolver, so no display needed.
import io, contextlib
fake = [("eDP-1", "obj-edp"), ("DP-8", "obj-dp8")]
err = io.StringIO()
with contextlib.redirect_stderr(err):
    hit = m.resolve_monitor("DP-8", fake)
    miss = m.resolve_monitor("DP-99", fake)
    none = m.resolve_monitor("DP-99", [])
warned = err.getvalue()
resolver_src = src.split("def resolve_monitor")[1].split("def draw_sprite")[0]
ck("33 unknown --monitor never stops him", hit == "obj-dp8" and miss is None and none is None
   and "DP-99" in warned and "eDP-1" in warned and "DP-8" in warned and "none" in warned
   and "sys.exit" not in resolver_src and ".quit(" not in resolver_src,
   "known -> pinned; unknown -> None with warning naming %s" % ", ".join(c for c, _ in fake))
# --still: parked for a simulated hour with everything else running — no
# walk, no bound, no graze, never off "home"; blinks still happen and a
# tip still lands.
q = m.Pet(types.SimpleNamespace(**dict(vars(O), still=True, interval=120)), m.KNOWLEDGE)
q.seen = set(); q.saw_activity(0); q.present_until = 1e9
q.step(.033, 0.0, 1920, 1080); x0, y0 = q.x, q.y
moved = poses = modes = 0; blinks = spoke = 0; now = 0.0
for i in range(int(3600 / .033)):
    now += .033; was_b = q.blink > 0; q.step(.033, now, 1920, 1080)
    if (q.x, q.y) != (x0, y0): moved += 1
    if q.pose != "stand": poses += 1
    if q.mode != "home": modes += 1
    if q.blink > 0 and not was_b: blinks += 1
    if q.text: spoke += 1
ck("34 --still never moves", moved == 0 and poses == 0 and modes == 0 and blinks > 100 and spoke > 0,
   "1h: moved %d frames, grazed %d, left home %d, blinked %d times, spoke %s"
   % (moved, poses, modes, blinks, "yes" if spoke else "NO"))
# Redraw-on-change: the key is stable across a static stretch and changes
# on every frame of a walk, so skipping equal keys cannot drop motion.
q = m.Pet(O, m.KNOWLEDGE); q.seen = set(); q.next_talk = q.next_roam = 1e9; quiet_idles(q)
q.blink = q.ear = q.tail = 0; q.next_blink = q.next_ear = q.next_tail = 1e9
for i in range(30): q.step(.033, i * .033, 1920, 1080)      # he is away here: let him lie down first
q.chews_left = 0; q.chew = False; q.next_chew = 1e9         # ...and hold his jaw too
k = q.render_key(); static = all(
    (q.step(.033, 1 + i * .033, 1920, 1080) or q.render_key()) == k for i in range(300))
q.next_roam = 0; t = 20.0                            # the walk starts once he is
while q.mode == "home" and t < 22:                   # up off the ground...
    t += .033; q.step(.033, t, 1920, 1080)
q.target = q.home_x - 400; q.speed = 60             # ...with a random target and
keys = []                                            # gait; pin both, or a short
                                                     # draw arrives and pauses
for i in range(60):
    t += .033; q.step(.033, t, 1920, 1080); keys.append(q.render_key())
walking = q.mode in ("out", "back") and len(set(keys)) > 40
ck("35 redraw key: still when still, moving when moving", static and walking,
   "300 static frames -> 1 key; 60 walking frames -> %d keys" % len(set(keys)))
# Hidden does no work: with GTK loaded but no window, the app's scheduler
# can still be driven. stop() must leave no sources and tick must not run.
m._load_gtk()
app = m.build_app(types.SimpleNamespace(**dict(vars(O), no_theme=False, no_context=False, quiet=False,
                                                start_hidden=False, layer="overlay", monitor=None, topics="")),
                  m.KNOWLEDGE)
ticks = {"n": 0}
app.tick = lambda: (ticks.__setitem__("n", ticks["n"] + 1) or True)
app.poll_context = lambda: (ticks.__setitem__("n", ticks["n"] + 1) or False)
app.poll_theme = lambda: (ticks.__setitem__("n", ticks["n"] + 1) or False)
app.start(); started = set(app._sources)
app.stop(); after_stop = dict(app._sources); ticks["n"] = 0     # start() polls context once, by design
ctx = m.GLib.MainContext.default(); end = time.monotonic() + 0.4
while time.monotonic() < end: ctx.iteration(False); time.sleep(0.01)
ck("36 hidden does no work", "tick" in started and after_stop == {} and ticks["n"] == 0,
   "sources while shown %s; after stop %s; callbacks in 0.4s hidden: %d" % (sorted(started), after_stop, ticks["n"]))
# Snooze must show. Through the real middle-click handler on the app above:
# he answers standing, lies down once the line has cleared, and the render
# key moves on the change so the frame is actually drawn; the second click
# stands him up and he stays up while someone is there. Hidden he is never
# stepped, so the pose he is in when hidden is the pose he is shown in.
def run_pet(q, secs, start, dt=.033):
    now = start
    for _ in range(int(secs / dt)):
        now += dt; q.step(dt, now, 1920, 1080)
    return now
mid = types.SimpleNamespace(get_current_button=lambda: 2)
q = app.pet; q.seen = set(); q.present_until = 1e9; q.next_talk = q.next_roam = 1e9; quiet_idles(q)
m.visible = True
base = m.GLib.get_monotonic_time() / 1e6          # on_click reads the real clock, so
t = run_pet(q, 2, base); k0 = q.render_key()      # the simulated one starts there too
app.on_click(mid, 1, 0, 0); snoozed = q.snoozing(t)
q.step(.033, t + .033, 1920, 1080); said_standing = q.pose == "stand" and bool(q.text)
t = run_pet(q, 4, t); lay = q.pose == "rest" and not q.text; k1 = q.render_key()
t = run_pet(q, 60, t); stayed = q.pose == "rest"
app.on_click(mid, 1, 0, 0); woke = not q.snoozing(t)
q.step(.033, t + .033, 1920, 1080); up = q.pose == "settle"; k2 = q.render_key()
t = run_pet(q, 60, t); stayed_up = q.pose == "stand"
ck("43 middle click lies him down; again stands him up", snoozed and said_standing and lay and stayed
   and woke and up and stayed_up and k0 != k1 and k1 != k2 and k0[4] != k1[4],
   "click -> snoozed %s, answers standing %s, lying after the line %s, still lying at 60s %s; "
   "click -> awake %s, rising next frame %s, standing at 60s %s; key moved %s" % (
       snoozed, said_standing, lay, stayed, woke, up, stayed_up, k0 != k1 and k1 != k2))
# Being away shows the same way: parked and quiet, he lies down when presence
# lapses -- not before -- and the first sign of activity stands him up on the
# next frame. --still gets the pose too: it is not movement.
def away_pet(**kw):
    q = fresh_pet(**kw); q.next_talk = q.next_roam = 1e9; quiet_idles(q)
    q.saw_activity(0.0); q.step(.033, 0.0, 1920, 1080); return q
q = away_pet(); t = run_pet(q, 290, 0.0); early = q.pose
t = run_pet(q, 20, t); lapsed = q.pose; k_away = q.render_key()
q.saw_activity(t); q.step(.033, t + .033, 1920, 1080); rising = q.pose; k_back = q.render_key()
t = run_pet(q, 0.3, t); back = q.pose
s = away_pet(still=True); t = run_pet(s, 310, 0.0); still_rests = s.pose
s.saw_activity(t); run_pet(s, 0.3, t); still_up = s.pose
ck("44 away lies him down; activity stands him up", early == "stand" and lapsed == "rest" and rising == "settle"
   and back == "stand" and k_away != k_back and still_rests == "rest" and still_up == "stand",
   "at 290s %s, at 310s %s, one frame after activity %s, 0.3s after %s; --still: %s then %s" % (
       early, lapsed, rising, back, still_rests, still_up))
# Two hours lying down with everything else running, twice: snoozed with
# someone present, and away with nobody there. Both: lying most of the time,
# never while speaking or walking, never a snap between standing and lying,
# and lying he blinks, his ear moves (bedded deer's ears never stop) and he
# chews. Snoozed, no walk at all -- he was told to be quiet for an hour.
# Away, he gets up to walk and lies back down: nobody told him to stop.
# Right-click tips arrive either way, so speech happens in both runs.
def lie_for_2h(seed, **state):
    random.seed(seed); q = fresh_pet(); q.next_talk = 1e9
    for k, v in state.items(): setattr(q, k, v)
    q.step(.033, 0.0, 1920, 1080); now = 0.0
    c = collections.Counter(); bad = collections.Counter()
    n = dict(blinks=0, ears=0, tails=0, walks=0, chews=0, dozing=0, ears_dozing=0)
    was = dict(b=False, e=False, t=False, c=0)
    for i in range(int(7200 / .033)):
        now += .033
        if i % int(600 / .033) == 0:
            head, text = q.next_ambient(why="asked"); q.say(head, text, 9.0, now)
        mode = q.mode; pose = q.pose; q.step(.033, now, 1920, 1080)
        if {pose, q.pose} == {"stand", "rest"} or {pose, q.pose} == {"graze", "rest"}: bad["snapped"] += 1
        c[q.pose] += 1
        if q.pose == "rest" and q.text: bad["speaking"] += 1
        if q.pose == "rest" and q.mode != "home": bad["walking"] += 1
        if q.pose == "graze": bad["grazing"] += 1
        if q.chew and q.pose != "rest": bad["chewing up"] += 1
        if q.doze and q.pose != "rest": bad["eye shut up"] += 1
        if q.doze and q.chew: bad["chewing asleep"] += 1
        if q.doze and q.blink > 0 and not was["b"]: bad["blinking asleep"] += 1
        if q.doze: n["dozing"] += 1
        if q.doze and q.ear > 0 and not was["e"]: n["ears_dozing"] += 1
        if mode == "home" and q.mode == "out":
            n["walks"] += 1
            if q.pose == "rest": bad["walked lying"] += 1
        if q.pose == "rest":
            if q.blink > 0 and not was["b"]: n["blinks"] += 1
            if q.ear > 0 and not was["e"]: n["ears"] += 1
            if q.tail > 0 and not was["t"]: n["tails"] += 1
            if q.chew == 1 and was["c"] != 1: n["chews"] += 1
        was = dict(b=q.blink > 0, e=q.ear > 0, t=q.tail > 0, c=q.chew)
    n["dozing"] = n["dozing"] / max(1, c["rest"])
    return c["rest"] / sum(c.values()), c["settle"], bad, n
share, settles, bad, n = lie_for_2h(3, snooze_until=1e9, present_until=1e9)
ck("45 snoozed 2h: lies 80%+, no walk, never speaking, blinks, ear moves, chews, dozes, never snaps",
   share > 0.80 and not bad and n["walks"] == 0 and n["blinks"] > 100 and n["ears"] > 200
   and n["tails"] > 10 and n["chews"] > 200 and settles > 0 and 0.3 < n["dozing"] < 0.8 and n["ears_dozing"] > 50,
   "lying %.0f%%, %d settle frames; %s; %d walks; lying: %d blinks, %d ear, %d tail, %d chews, eye shut %.0f%% (%d ear moves shut)" % (
       100 * share, settles, dict(bad) or "clean", n["walks"], n["blinks"], n["ears"], n["tails"], n["chews"],
       100 * n["dozing"], n["ears_dozing"]))
share, settles, bad, n = lie_for_2h(4, snooze_until=0.0, present_until=0.0)
ck("46 away 2h: lies 80%+, gets up to walk and lies back down, never snaps",
   share > 0.80 and not bad and n["walks"] > 0 and n["blinks"] > 100 and n["ears"] > 200 and settles > 0,
   "lying %.0f%%, %d settle frames; %s; %d walks; lying: %d blinks, %d ear, %d tail, %d chews" % (
       100 * share, settles, dict(bad) or "clean", n["walks"], n["blinks"], n["ears"], n["tails"], n["chews"]))
# The settle frame: going down and getting up both hold it for about 150ms
# -- four or five frames at 33ms -- and both transitions change the render
# key three times, so all three drawings reach the screen. A word from a
# resting deer and a walk from one both get up through it too.
def hold(q, t, dt=.033):
    """Step until the pose is neither settle nor what it was; return the
    settle frames seen and the poses passed through."""
    seen = []; start = q.pose; keys = {q.render_key()}
    for _ in range(90):
        t += dt; q.step(dt, t, 1920, 1080); seen.append(q.pose); keys.add(q.render_key())
        if q.pose not in (start, "settle"): break
    via = [p for i, p in enumerate(seen) if i == 0 or p != seen[i - 1]]
    hold.keys = len(keys)                     # start, settle, end: three drawings
    return seen.count("settle"), [p for p in via if p != start], t
q = fresh_pet(); q.present_until = 1e9; q.next_talk = q.next_roam = 1e9; quiet_idles(q)
t = run_pet(q, 1, 0.0)
q.snooze_until = 1e9
down, via_down, t = hold(q, t); keys_down = hold.keys
q.snooze_until = 0.0
up, via_up, t = hold(q, t); keys_up = hold.keys
q.snooze_until = 1e9; t = run_pet(q, 1, t); lying = q.pose == "rest"
q.say(None, "a word", 3.0, t); word, via_word, t = hold(q, t)
q.head = q.text = None; q.pause = 0; t = run_pet(q, 1, t); lying2 = q.pose == "rest"
q.snooze_until = 0.0; q.present_until = 0.0        # away, not snoozed: a walk may fire
q.next_roam = 0; walk, via_walk, t = hold(q, t)
t = run_pet(q, 0.1, t); walked = q.mode == "out" and q.pose == "stand"
ck("47 settle frame held ~150ms both ways; a word and a walk get up through it",
   4 <= down <= 6 and via_down == ["settle", "rest"] and 4 <= up <= 6 and via_up == ["settle", "stand"]
   and lying and 4 <= word <= 6 and via_word == ["settle", "stand"] and lying2 and 4 <= walk <= 6
   and via_walk == ["settle", "stand"] and walked and keys_down == 3 and keys_up == 3,
   "down: %d frames via %s, %d keys; up: %d via %s, %d keys; word: %d via %s; walk: %d via %s then %s" % (
       down, via_down, keys_down, up, via_up, keys_up, word, via_word, walk, via_walk,
       "walking" if walked else "NOT walking"))
# Cud. Lying down and awake, the chin moves between two places at about a
# whitetail's rate -- the real 78-93 a minute, jittered chew to chew so it is
# never on a beat -- in short bouts of 8-14 with 10-20s still between them;
# standing, it never moves; and every move changes the render key, or it
# never draws. The regularity is what the check is against: a fixed period
# read as a loading indicator.
q = fresh_pet(); q.present_until = 1e9; q.snooze_until = 1e9; q.next_talk = q.next_roam = 1e9
t = run_pet(q, 2, 0.0); assert q.pose == "rest"
q.next_doze = 1e9                                    # awake throughout: the cud rhythm alone (50 has the doze)
chews = []; changes = 0; k = q.render_key(); was = q.chew; gaps = []; last = None; mid_bout = q.chews_left > 0
for i in range(int(600 / .033)):
    t += .033; q.step(.033, t, 1920, 1080)
    if q.render_key() != k: changes += 1; k = q.render_key()
    if q.chew == 1 and was != 1:
        chews.append(t)
        if last is not None: gaps.append(t - last)
        last = t
    was = q.chew
bouts = [1]                                          # chews split into bouts by the stills between
for g in gaps:
    if g >= 2: bouts.append(1)
    else: bouts[-1] += 1
bouts = bouts[1:-1] if mid_bout else bouts[:-1]      # neither a bout joined partway nor one cut off
inbout = [g for g in gaps if g < 2]; pauses = [g for g in gaps if g >= 2]
rate = 60 / statistics.mean(inbout) if inbout else 0
jitter = statistics.pstdev(inbout) if len(inbout) > 1 else 0
q.snooze_until = 0.0; t = run_pet(q, 1, t); standing_chews = 0
for i in range(int(60 / .033)):
    t += .033; q.step(.033, t, 1920, 1080); standing_chews += q.chew
# The chin must continue the jaw row, not hang off the muzzle: row 16 of the
# resting head is one unbroken run whether the chin is out or in.
def runs(pts, y):
    xs = sorted(x for x, yy in pts if yy == y); return sum(1 for a, b in zip(xs, xs[1:]) if b != a + 1) + 1
jaw = [runs({(x, y) for x, y, _ in m.pixels(1, False, "rest", chew=c)}, 16) for c in (0, 1)]
ck("49 cud: short jittered bouts near the real rate, long stills, only lying down, every move drawn, chin on the jaw",
   jaw == [1, 1] and 60 <= rate <= 100 and jitter >= 0.05 and len(pauses) >= 10 and all(9 <= p <= 22 for p in pauses)
   and bouts and all(8 <= b <= 14 for b in bouts) and changes >= 2 * len(chews) - 2
   and standing_chews == 0 and q.pose == "stand",
   "jaw row runs chin in/out %s; 10 min lying: %d chews at %.0f/min (sd %.2fs), %d bouts of %d-%d chews, %d stills of %.0f-%.0fs, %d key changes; standing 1 min: %d chews" % (
       jaw, len(chews), rate, jitter, len(bouts), min(bouts) if bouts else 0, max(bouts) if bouts else 0, len(pauses),
       min(pauses) if pauses else 0, max(pauses) if pauses else 0, changes, standing_chews))
# The doze cycle, on Adams' numbers: he beds alert, then dozes 30s to a few
# minutes, wakes briefly, dozes again, for as long as he is down. Eye shut
# means no cud and no blink; the ear goes on regardless; and off the bed the
# eye is open on the very frame he starts to rise.
q = fresh_pet(); q.present_until = 1e9; q.snooze_until = 1e9; q.next_talk = q.next_roam = 1e9
t = run_pet(q, 2, 0.0); assert q.pose == "rest"
first_shut = None; bouts = []; alerts = []; start = t; was = q.doze; ear_shut = 0; was_e = False
chews_shut = blinks_shut = 0; was_b = False
for i in range(int(3600 / .033)):
    t += .033; q.step(.033, t, 1920, 1080)
    if q.doze != was:
        (bouts if was else alerts).append(t - start); start = t
        if first_shut is None and q.doze: first_shut = t - 2.0
    if q.doze:
        if q.ear > 0 and not was_e: ear_shut += 1
        if q.chew: chews_shut += 1
        if q.blink > 0 and not was_b: blinks_shut += 1
    was, was_e, was_b = q.doze, q.ear > 0, q.blink > 0
alerts = alerts[1:]                                   # the first "alert" is the bedding-down one
q.snooze_until = 0.0; t = run_pet(q, 0.034, t); rises_open = q.pose == "settle" and not q.doze
shut_share = sum(bouts) / 3600
ck("50 doze cycle: beds alert, dozes 30s-3min, wakes 15-60s, no cud or blink shut, ear moves, eye opens as he rises",
   first_shut is not None and 25 <= first_shut <= 125 and len(bouts) >= 8
   and all(29 <= b <= 181 for b in bouts) and all(14 <= a <= 61 for a in alerts)
   and chews_shut == 0 and blinks_shut == 0 and ear_shut > 20 and rises_open and 0.3 < shut_share < 0.85,
   "first shut after %ss; %d dozes of %.0f-%.0fs, %d alerts of %.0f-%.0fs, eye shut %.0f%% of the hour; "
   "shut: %d chews, %d blinks, %d ear moves; rising: eye %s" % (
       "%.0f" % first_shut if first_shut is not None else "never", len(bouts), min(bouts) if bouts else 0,
       max(bouts) if bouts else 0, len(alerts), min(alerts) if alerts else 0, max(alerts) if alerts else 0,
       100 * shut_share, chews_shut, blinks_shut, ear_shut, "open" if rises_open else "SHUT"))
# Trips go into the open -- away from the nearer edge, the way he does not
# face when parked -- as
# far as that side holds, never shorter than two strides. From the default
# corner (24px from the right edge) every trip goes inward and none is a
# shuffle; from the middle they all go the one way `open` happens to point; parked
# with no room on the open side he skips the roam rather than take two steps.
def trips(home_x, n=60, width=1920):
    q = m.Pet(O, m.KNOWLEDGE); q.seen = set(); q.present_until = 1e9; q.next_talk = 1e9; quiet_idles(q)
    q.place(width, 1080); q.home_x = q.x = home_x; q.step(.033, 0.0, width, 1080)
    out = []; t = 0.0
    for _ in range(n):
        q.next_roam = 0; q.pause = 0; q.mode = "home"; q.pose = "stand"
        q.step(.033, t, width, 1080); t += .033
        if q.mode != "out": out.append(0); continue
        out.append(q.target - q.home_x); q.mode = "home"
    return out
mt = m.Pet(O, m.KNOWLEDGE).min_trip()
corner = trips(1920 - 96 - 24); middle = trips(912); wall = trips(1920 - 96 - 4, width=1920)
corner_ok = all(d <= -mt for d in corner)
middle_ok = all(abs(d) >= mt for d in middle) and len({d > 0 for d in middle}) == 1
# a surface too narrow for a trip either side: nothing but skips
narrow = trips(4 + int(mt) - 1, width=96 + 8 + 2 * (int(mt) - 1))   # 69px each side
ck("53 trips fit the room and are never a shuffle", mt == 70.4 and corner_ok and middle_ok and all(d == 0 for d in narrow),
   "minimum %.0fpx; corner: %d trips, all inward, %.0f-%.0fpx; middle: %d right %d left (one way, into the open), shortest %.0fpx; no room: %d of %d skipped" % (
       mt, len(corner), min(abs(d) for d in corner), max(abs(d) for d in corner),
       sum(d > 0 for d in middle), sum(d < 0 for d in middle), min(abs(d) for d in middle),
       sum(d == 0 for d in narrow), len(narrow)))
# Facing falls out of the nearer left or right edge: from every corner he
# faces it -- into the corner, back to the room, which is what reads as
# turned away -- a drag across the midline turns him, a monitor change that
# puts the other edge nearer turns him, and within a body width of
# equidistant he keeps the way he last faced. Speaking turns him toward the
# middle of the screen. He walks the other way, into the open.
def parked(**kw):
    q = m.Pet(types.SimpleNamespace(**dict(vars(O), **kw)), m.KNOWLEDGE); q.seen = set()
    q.present_until = 1e9; q.next_talk = q.next_roam = 1e9; quiet_idles(q)
    q.place(1920, 1080); q.step(.033, 0.0, 1920, 1080); return q
faces = {c: parked(corner=c).dir for c in ("br", "tr", "bl", "tl")}
corners_ok = faces == dict(br=1, tr=1, bl=-1, tl=-1)
q = parked(corner="br"); q.home_x = q.x = 200; q.face_open(1920); q.step(.033, 1.0, 1920, 1080); dragged = q.dir
q.say(None, "hi", 3.0, 1.0); q.step(.033, 1.033, 1920, 1080); spoke = q.dir
q.head = q.text = None; q.pause = 0; q.step(.033, 1.066, 1920, 1080); quiet = q.dir
c = parked(corner="br"); center = (1920 - c.w) / 2
c.home_x = c.x = center - 200; c.face_open(1920); before = c.dir            # clearly left of center: faces right
c.home_x = c.x = center + 30; c.face_open(1920); c.step(.033, 2.0, 1920, 1080); small = c.dir   # 30px past center: keeps it
c.home_x = c.x = center + 200; c.face_open(1920); c.step(.033, 2.033, 1920, 1080); big = c.dir  # a body past: turns
r = parked(corner="br"); r.home_x = r.x = 700; r.face_open(1920); r.step(.033, 3.0, 1920, 1080); wide = r.dir   # 696 left, 1120 right
r.step(.033, 3.033, 1000, 1080); shrunk = r.dir                                                  # now 696 left, 200 right
walks = parked(corner="br"); walks.next_roam = 0; walks.step(.033, 4.0, 1920, 1080); walks.step(.033, 4.033, 1920, 1080)
walk_dir = walks.dir if walks.mode == "out" else 0
ck("54 he faces the near edge: into the corner from every corner, after a drag, after a refit; no flip on a small drag; speaks inward; walks out",
   corners_ok and dragged == -1 and spoke == 1 and quiet == -1 and before == -1 and small == -1 and big == 1
   and wide == -1 and shrunk == 1 and walk_dir == -1,
   "corners %s; dragged to x=200 -> %d, speaking %d, quiet again %d; center-200 -> %d, +30 past center -> %d, +200 -> %d; "
   "x=700 on 1920 -> %d, surface to 1000 -> %d; from br he walks %s" % (
       faces, dragged, spoke, quiet, before, small, big, wide, shrunk, {-1: "left, into the room", 1: "RIGHT", 0: "NOT AT ALL"}[walk_dir]))
# The bottom of the surface is the ground. From br and bl his last row -- the
# hooves' row -- sits on the surface's bottom edge; --margin is the side gap
# only. The top corners keep the margin below the bar. A saved (dragged) spot
# is the user's and is left where it is, shelf or not; and the clamps let a
# drag reach the ground too.
def placed(corner, margin=24):
    q = m.Pet(types.SimpleNamespace(**dict(vars(O), corner=corner, margin=margin)), m.KNOWLEDGE)
    q.place(1920, 1080); return q
g = {c: (placed(c).home_x, placed(c).home_y) for c in ("br", "bl", "tr", "tl")}
w, h = placed("br").w, placed("br").h
ground_ok = g["br"] == (1920 - w - 24, 1080 - h) and g["bl"] == (24, 1080 - h)
top_ok = g["tr"] == (1920 - w - 24, 24) and g["tl"] == (24, 24)
side_ok = placed("br", 60).home_x == 1920 - w - 60 and placed("br", 60).home_y == 1080 - h
m.save_json(m.STATE, dict(m.read_state(), x=500, y=700)); kept = placed("br"); saved_ok = (kept.home_x, kept.home_y) == (500, 700)
st = m.read_state(); st.pop("x", None); st.pop("y", None); m.save_json(m.STATE, st)
d = placed("br"); d.home_y = d.y = 5000; d.clamp_home(1920, 1080); drag_ok = d.home_y == 1080 - h
ck("55 the bottom of the screen is the ground", ground_ok and top_ok and side_ok and saved_ok and drag_ok,
   "br %s bl %s (bottom row on the edge); tr %s tl %s (margin below the bar); --margin 60 -> x %d, y %d; "
   "saved spot kept %s; a drag clamps to the ground %s" % (
       g["br"], g["bl"], g["tr"], g["tl"], placed("br", 60).home_x, placed("br", 60).home_y, saved_ok, drag_ok))
# Cadence. Two speeds and a decay, all from tools/exhaust.py. A fresh user at
# the default has every fundamental inside roughly a hundred minutes of
# presence (300 s, ~21 utterances at 15% chatter); after that the gap between
# utterances averages --interval; an explicit --interval under 300 wins in
# both phases; --quiet and --no-basics behave; and the base doubles per
# completed pass, capped, so he slows down but never stops.
def sim_utterances(p, hours, until=None):
    """Drive the real step() at 1 s ticks with someone present. Returns the
    utterance times (s) and the presence time at which `until` first held."""
    times = []; hit = None; now = 0.0
    p.saw_activity(0.0); p.step(1.0, now, 1920, 1080)
    for sec in range(int(hours * 3600)):
        now += 1.0
        if sec % 60 == 0: p.saw_activity(now)
        was = p.text; p.step(1.0, now, 1920, 1080)
        if p.text and not was: times.append(now)
        if hit is None and until is not None and until(p): hit = now
    return times, hit
def cad_pet(**kw):
    q = fresh_pet(**kw); q.passes = 0; return q
q = cad_pet(interval=900)
_, t16 = sim_utterances(q, 4, until=lambda p: not p.basics_open())
basics_ok = t16 is not None and 45 * 60 <= t16 <= 150 * 60
q = cad_pet(interval=900); q.seen = set(m.FUNDAMENTAL)     # tier already closed
t, _ = sim_utterances(q, 12)
gaps = [b - a for a, b in zip(t, t[1:])]
rate_ok = gaps and abs(statistics.mean(gaps) - 900) / 900 < 0.15
fast = cad_pet(interval=60)
fast_ok = fast.cadence() == 60 and (fast.seen.update(m.FUNDAMENTAL) or fast.cadence() == 60)
quiet_ok = cad_pet(interval=900, quiet=True).cadence() >= 1e8
nb = cad_pet(interval=900, no_basics=True); nb_ok = nb.cadence() == 900 and not nb.basics_open()
sup_pet = cad_pet(interval=900); sup_pet.seen = set(m.FUNDAMENTAL) - {"cli:omarchy update"}
m.suppressed["cli:omarchy update"] = "test"; sup_ok = not sup_pet.basics_open(); m.suppressed.clear()
dec = cad_pet(interval=900); dec.seen = set(m.FUNDAMENTAL); curve = []
for dec.passes in (0, 1, 2, 3, 10): curve.append(dec.cadence())
decay_ok = curve == [900, 1800, 3600, 3600, 3600]
# a real pass end bumps the counter through mark_seen and lands in state.json
w = cad_pet(interval=900); w.seen = {m.tip_id(t) for t in m.KNOWLEDGE[1:]}
w.mark_seen(m.KNOWLEDGE[0]); passes_ok = w.passes == 1 and m.read_state().get("passes") == 1 and not w.seen
second = cad_pet(interval=900); second.passes = 1; second_ok = not second.basics_open() and second.cadence() == 1800
ck("37 fundamentals clear in ~100 min at the default", basics_ok,
   "all %d after %s min" % (len(m.FUNDAMENTAL), t16 // 60 if t16 else "never"))
ck("38 after the basics, utterances average --interval", rate_ok,
   "%d gaps, mean %.0fs for --interval 900" % (len(gaps), statistics.mean(gaps) if gaps else 0))
ck("39 explicit low --interval wins; --quiet and --no-basics hold; a withheld fundamental can't hold the tier",
   fast_ok and quiet_ok and nb_ok and sup_ok,
   "60 -> %s both phases; quiet %s; no-basics %s; suppressed %s" % (fast_ok, quiet_ok, nb_ok, sup_ok))
ck("40 cadence doubles per pass and caps", decay_ok and passes_ok and second_ok,
   "passes 0,1,2,3,10 -> %s; pass end -> passes=%d in state.json, seen cleared %s; pass 2 is never the tutorial" % (
       curve, w.passes, not w.seen))
# --no-theme, after a full start. A real do_activate() on a NON_UNIQUE
# application (so GTK does not forward it to a deer already running) with
# start_hidden, so the surface it maps draws nothing and takes no input.
# The palette must be the built-in one and the theme must never have been
# read; and the binding re-check, which has nothing to do with themes, must
# still be scheduled, still call refresh_suppressed, and still throttle to
# 30 s when nobody is there.
from gi.repository import Gio
m.PAL.update(BUILTIN); m.visible = False
calls = {"apply": 0, "read": 0, "refresh": 0}
real_apply, real_read, real_refresh = m.apply_theme, m.read_theme, m.refresh_suppressed
m.apply_theme = lambda: (calls.__setitem__("apply", calls["apply"] + 1) or real_apply())
m.read_theme = lambda: (calls.__setitem__("read", calls["read"] + 1) or real_read())
m.refresh_suppressed = lambda tips: (calls.__setitem__("refresh", calls["refresh"] + 1) or real_refresh(tips))
nt = m.build_app(types.SimpleNamespace(**dict(vars(O), no_theme=True, no_context=True, quiet=True,
                                               start_hidden=True, layer="overlay", monitor=None, topics="")),
                 m.KNOWLEDGE)
nt.set_flags(Gio.ApplicationFlags.NON_UNIQUE); nt.register()
sched = []; orig_schedule = nt._schedule
nt._schedule = lambda name, fn, secs: (sched.append((name, secs)), orig_schedule(name, fn, secs))[1]
nt.do_activate(); nt.start()
ctx = m.GLib.MainContext.default(); end = time.monotonic() + 0.3
while time.monotonic() < end: ctx.iteration(False); time.sleep(0.01)
started_nt = sorted(nt._sources)
ck("41 --no-theme never reads the theme, palette stays built in",
   not nt.get_is_remote() and m.PAL == BUILTIN and calls["apply"] == 0 and calls["read"] == 0
   and "theme" not in started_nt,
   "after do_activate+start: PAL %s, apply_theme %d, read_theme %d, sources %s"
   % ("unchanged" if m.PAL == BUILTIN else "CHANGED", calls["apply"], calls["read"], started_nt))
now = m.GLib.get_monotonic_time() / 1e6
nt.pet.saw_activity(now); sched.clear(); nt._sources.pop("binds", None); before = calls["refresh"]
nt.poll_binds(); here = list(sched)
nt.pet.present_until = 0.0; sched.clear(); nt._sources.pop("binds", None)
nt.poll_binds(); away = list(sched)
ck("42 binding re-check runs on its own source under --no-theme, and throttles away",
   "binds" in started_nt and calls["refresh"] - before == 2 and here == [("binds", 4)] and away == [("binds", 30)],
   "scheduled at start %s; poll_binds -> refresh_suppressed +%d; rescheduled %s present, %s away"
   % (started_nt, calls["refresh"] - before, here, away))
nt.stop(); nt.win.destroy()
m.apply_theme, m.read_theme, m.refresh_suppressed = real_apply, real_read, real_refresh
# ---------------------------------------------------------- characters ----
# Two characters, one Pet. Each is data the Pet reads -- canvas, scale,
# views, gaits, walk step, a pixels() with the deer's signature -- and
# every sprite check below runs per character from that data, never from
# a number written into the check.
chars = dict(m.SPRITES)
ck("57 two characters, the deer the default, each with a canvas, a scale, a roam and a mirror of its own",
   set(chars) >= {"yoru", "dane"} and m.DEFAULT_SPRITE == "yoru"
   and all(callable(c.pixels) and c.w > 0 and c.h > 0 and c.scale > 0 for c in chars.values())
   and (chars["yoru"].w, chars["yoru"].h, chars["yoru"].scale, chars["yoru"].roams, chars["yoru"].mirrors)
   == (m.SW, m.SH, 4, True, True)
   and chars["yoru"].gaits == ("walk", "bound") and not chars["yoru"].views
   and not chars["dane"].roams and not chars["dane"].mirrors and chars["dane"].gaits == ()
   and chars["dane"].turn == m.DANE_TURN == ("work", "folding", "closing", "speak")
   and not chars["dane"].tics
   and "flip = pet.dir < 0 and ch.mirrors" in src
   # every character's idle actions are its own data: a held pose, a path
   # into it whose last frame is that pose, a cadence and a duration
   and all(a.path and a.path[-1] == a.pose and a.every[0] < a.every[1]
           and a.secs[0] < a.secs[1] and a.every[0] > a.secs[1]
           for c in chars.values() for a in c.idles)
   and [a.pose for a in chars["yoru"].idles] == ["graze"]
   and [a.pose for a in chars["dane"].idles] == ["sip", "beard"],
   {n: "%dx%d @%dx %s %s %s; idle %s" % (
       c.w, c.h, c.scale, "roams " + "/".join(c.gaits) if c.roams else "stays",
       "mirrors" if c.mirrors else "fixed",
       "states " + "/".join(c.turn) if c.turn else "one view",
       ", ".join("%s every %d-%ds for %.1f-%.1fs over %d frames"
                 % (a.pose, a.every[0], a.every[1], a.secs[0], a.secs[1], len(a.path))
                 for a in c.idles)) for n, c in chars.items()})
# Bounds, from the canvas. The deer overhangs his by design (the graze
# shift, the bound's lift), by the margins check 26 allows; The Dane's
# scene stays inside his, so a wider canvas later is a data change.
c = chars["dane"]
DANE_POSES = ("stand", "morph", "rest", "settle") + m.COFFEE_PATH + m.BEARD_PATH
def dane_frames():
    for view in c.turn:
        for pose in DANE_POSES:
            for blink in (False, True):
                for doze in (0, 1):
                    for tic in (0, 1):
                        yield (view, pose, blink, doze, tic), m.dane_pixels(1, blink, pose, 0, 0, None, 0, doze, view=view, tic=tic)
oob = [k for k, pts in dane_frames() if any(not (0 <= x < c.w and 0 <= y < c.h) for x, y, _ in pts)]
grounded = all(max(y for _, y, _ in pts) == c.h - 1 for _, pts in dane_frames())
ck("58 the dane's scene inside his %dx%d canvas in every view and frame, the desk on its last row" % (c.w, c.h),
   not oob and grounded, "%s out of bounds; on the ground line: %s" % (oob[:3] or "none", grounded))
lonely = []; multi = []
for k, pts in dane_frames():
    pset = {(x, y) for x, y, _ in pts}
    lonely += [(k, p) for p in pset if not neighbors(p, pset)]
    n = components(pset)
    if n > 1: multi.append((k, n))
ck("59 the dane's scene one piece, no floating pixel, in every view and frame",
   not lonely and not multi, "floating %s; pieces %s" % (lonely[:2] or "none", multi[:3] or "none"))
# The desk. It is drawn over him: the tabletop is the desk tone and
# nothing else in the composited frame; beneath it his legs are there in
# every state -- seated, on the chair, not floating -- and the desk's
# legs stand on the ground row. The lid is whatever the view says and
# a slab with his head down, and it folds seven rows to five to three to
# one, in even steps, so no frame of the fold is twice another. The near
# forearm is at the keys only while he is working -- an idle action takes
# it away and the check knows which poses those are from the character's
# own paths -- and the far one never moves at all. And the eyes: down
# while he works, and while he reaches for the coffee, and while his
# hand is at his beard; up, white and iris, only to speak. That is the
# turn-away, and it is the one rule here with research behind it.
pal = m.dane_palette(); P, E, K, FAR_T, B, kk = pal["P"], pal["E"], pal["K"], pal["F"], pal["B"], pal["k"]   # not F: that is the failure list
through = []; lids = {}; hands = {}; gaze = {}
for k, pts in dane_frames():
    comp = {}
    for x, y, col in pts: comp[(x, y)] = col
    y0, y1, x0, x1 = m.DESK_TOP
    if any(comp.get((x, y)) != P for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)):
        through.append((k, "tabletop"))
    if not all(comp.get((x, 47)) == FAR_T for _, _, lx0, lx1 in m.DESK_LEGS for x in (lx0, lx1)):
        through.append((k, "desk legs off the ground"))
    if not any(comp.get((x, 47)) == B for x in range(m.DESK_TOP[2], m.DESK_TOP[3])):
        through.append((k, "no shoe on the ground under the desk"))
    LAP = (B, FAR_T)                      # the lid's back and its rim / the base
    lids[k] = next((state for state, (ly0, ly1, lx0, lx1) in m.LAPTOP_LID.items()
                    if all(comp.get((x, y)) in LAP for y in range(ly0, ly1 + 1) for x in range(lx0, lx1 + 1))
                    and comp.get(((lx0 + lx1) // 2, ly0 - 1)) not in LAP), None)   # above its middle: his shirt or the O, never his sleeve
    # The forearms, checked against the other frames rather than against
    # the table they came from, which would only be reading the data back.
    # Upright, the far arm is the same pixels in every frame; nothing on
    # the keyboard row is ever skin, which is the whole of "the hands stay
    # behind the lid"; and the frame differs from the working frame of the
    # same view exactly when an idle action has the near arm.
    skin = (pal["K"], kk)
    if k[1] in ("rest", "settle"):
        hands[k] = None
    else:
        # left of the lid's own edge, so the comparison is between frames
        # of the arm and not between how much of it each lid uncovers
        far = tuple(sorted((x, y) for (x, y), col in comp.items()
                           if col == kk and 29 <= y <= 33 and x < m.LAPTOP_BASE[2]))
        keys_row = any(comp.get((x, m.LAPTOP_BASE[0])) in skin for x in range(c.w))
        hands[k] = (far, keys_row)
    dx, dy = m.DANE_SEAT
    if k[1] == "settle": dx, dy = dx + m.DANE_SETTLE_HEAD[0], dy + m.DANE_SETTLE_HEAD[1]
    (fw, fi), (nw, ni) = m.EYES["far"], m.EYES["near"]
    up = all(comp.get((w[0] + dx, w[1] + dy)) == pal["W"] and comp.get((i[0] + dx, i[1] + dy)) == E
             for w, i in ((fw, fi), (nw, ni)))
    # working: the head is tilted a row, the lids are the skin shadow or the dropped brow, the
    # iris a row under; and nothing on his face is the accent but the irises (the glow that was
    # drawn there read as a rash on a green-accent theme -- see the comment at EYES)
    t = m.TILT; HAIR = pal["H"]
    down = all(comp.get((w[0] + dx, w[1] + dy + t)) in (kk, HAIR) and comp.get((i[0] + dx, i[1] + dy + t)) in (kk, HAIR)
               and comp.get((i[0] + dx, i[1] + dy + t + 1)) == E for w, i in ((fw, fi), (nw, ni)))
    irises = {(i[0] + dx, i[1] + dy + (t + 1 if down else 0)) for _, i in ((fw, fi), (nw, ni))}
    face = [(x, y) for (x, y), col in comp.items() if col == E and 5 <= y < 25 and 16 <= x < 40 and (x, y) not in irises]
    if face:
        gaze[k] = "accent on the face at %s" % face[:3]; continue
    shut = all(comp.get((i[0] + dx, i[1] + dy)) in (K, kk) for _, i in ((fw, fi), (nw, ni)))
    gaze[k] = "up" if up else "down" if down else "hidden" if k[1] == "rest" else "shut" if shut else "?"
# shut with his head down, and shut while he is changing: see the swap
want_lid = {k: "speak" if k[1] in ("rest", "settle", "morph") else k[0] for k in lids}
far_ref = next(v[0] for k, v in hands.items() if v is not None and k[1] == "stand")
want_open = {k: None if hands[k] is None else (far_ref, False) for k in lids}
# and the near arm: an idle pose draws a different frame from the working
# one it started from, and the working frames of every view draw the same
# arm as each other.
arms = {k: tuple(sorted(pts)) for k, pts in dane_frames()}
moved = {k for k in arms if k[1] not in ("rest", "settle") and k[1] != "stand"
         and arms[k] == arms[(k[0], "stand") + k[2:]]}
# the fold, in rows of lid still standing: even steps, no frame twice another
fold = [m.LAPTOP_LID[v][1] - m.LAPTOP_LID[v][0] + 1 for v in c.turn]
steps = [a - b for a, b in zip(fold, fold[1:])]
# rest hides the eyes; a blink or a doze shuts them; the settle frame looks down
# (a doze is a rest thing: the Pet never dozes elsewhere, and the settle ignores it)
want_gaze = {k: "hidden" if k[1] == "rest" else "shut" if (k[2] or (k[3] and k[1] != "settle"))
             else "up" if k[0] == "speak" and k[1] not in ("settle", "morph")
             else "down" for k in gaze}
ck("60 the desk: tabletop clean, his legs on the chair beneath it; the lid is the view's and a slab to speak or rest, and folds in even steps; the near forearm at the keys only while he works, the far one always, both still; eyes down for everything but speaking",
   not through and lids == want_lid and hands == want_open and gaze == want_gaze
   and not moved and len(fold) >= 4 and len(set(steps)) == 1 and steps[0] > 0,
   "desk wrong in %s; lid wrong in %s; forearms wrong in %s; poses that drew the working frame %s; gaze wrong in %s; fold %s rows (steps %s); far arm %d px, same in all %d upright frames" % (
       through[:2] or "none", [(k, lids[k]) for k in lids if lids[k] != want_lid[k]][:2] or "none",
       [k for k in hands if hands[k] != want_open[k]][:2] or "none",
       sorted({k[1] for k in moved}) or "none",
       [(k, gaze[k]) for k in gaze if gaze[k] != want_gaze[k]][:2] or "none",
       "-".join(str(f) for f in fold), set(steps),
       len(far_ref), sum(1 for v in hands.values() if v is not None)))
# Legibility in every shipped theme, for what is on the silhouette: every
# colour on an edge pixel, in every view, against the background the halo
# is drawn in. 1.4 is a soft edge that still reads on the sheet; the
# deer's own hooves on the light themes are what set it. The natural
# colours are nudged where they would fall under NATURAL_MIN, and which
# themes needed that is reported, not hidden.
def edge_colors(pts):
    pset = {(x, y) for x, y, _ in pts}
    return {col for x, y, col in pts if len(neighbors((x, y), pset)) < 8}
weak = []; nudged = collections.defaultdict(list); tightest = (9, "", "")
m.THEME_COLORS = os.path.join(os.environ["HOME"], ".local/state/omarchy/current/theme/colors.toml")  # check 24 pointed it at nothing
for f in themes:
    shutil.copy(f, m.THEME_COLORS); m.apply_theme(); name = f.split("/")[-2]
    pal = m.dane_palette(); byc = {v: k for k, v in pal.items()}
    for k, v in m.DANE_NATURAL.items():
        if pal[k] != v: nudged[name].append(k)
    for view in c.turn:
        for col in edge_colors(m.dane_pixels(1, False, "stand", view=view)):
            r = m._contrast(col, m.OUTLINE)
            if r < tightest[0]: tightest = (r, name, byc.get(col, "?"))
            if r < 1.4: weak.append((name, view, byc.get(col, "?"), round(r, 2)))
os.remove(m.THEME_COLORS); m.PAL.update(BUILTIN); m.apply_theme()
ck("61 the dane's scene legible in every shipped theme: every edge colour 1.4+ against the halo, every view",
   not weak and len(themes) > 0,
   "%d themes; tightest %s %s at %.2f; under 1.4: %s; natural colours nudged in: %s" % (
       len(themes), tightest[1], tightest[2], tightest[0], weak or "none",
       ", ".join("%s (%s)" % (t, "".join(v)) for t, v in sorted(nudged.items())) or "none"))
# The swap. SIGUSR2 is installed beside SIGUSR1 and calls request_swap,
# which the running app has hooked to its Pet: on a real activated app,
# the character changes with no restart, through the settle frame, at the
# same spot facing the same way, and state.json remembers it -- so the
# next start, with no flag, is the same character. --sprite sets and saves.
ck("62 swap signal wired", "SIGUSR2" in src and "request_swap" in src and "--swap" in src
   and "_on_swap.append" in src)
sw = m.build_app(types.SimpleNamespace(**dict(vars(O), scale=None, no_theme=True, no_context=True, quiet=True,
                                               start_hidden=False, layer="overlay", monitor=None,
                                               topics="", sprite="yoru")), m.KNOWLEDGE)
sw.set_application_id("dev.local.yoru.audit")     # nt above still holds the real id
sw.set_flags(Gio.ApplicationFlags.NON_UNIQUE); sw.register()
m.visible = True; m._on_swap.clear(); sw.do_activate()
sw.pet.place(1920, 1080); sw.pet.present_until = 1e9
sw.pet.seen = {"a-tip", "another"}              # tips he has already spent
was = (sw.pet.character.name, sw.pet.x, sw.pet.y + sw.pet.h, sw.pet.dir, sw.pet.snooze_until, sw.pet.px)
was_home, was_seen = (sw.pet.home_x, sw.pet.home_y + sw.pet.h), set(sw.pet.seen)
m.request_swap()                                # exactly what the signal calls
seen_poses = []; keys = {sw.pet.render_key()[-1]}; morph_keys = []
for _ in range(120):                            # the dissolve, then the laptop opening
    sw.tick(); seen_poses.append(sw.pet.pose); keys.add(sw.pet.render_key()[-1])
    if sw.pet.pose == "morph":
        morph_keys.append(sw.pet.render_key())
    time.sleep(0.02)
    if sw.pet.character.name != was[0] and sw.pet.view == sw.pet.character.turn[0]:
        break
now_ = (sw.pet.character.name, sw.pet.x, sw.pet.y + sw.pet.h, sw.pet.dir, sw.pet.snooze_until, sw.pet.px)
kept = ((sw.pet.home_x, sw.pet.home_y + sw.pet.h) == was_home and set(sw.pet.seen) == was_seen)
saved = m.read_state().get("sprite")
again = m.Pet(types.SimpleNamespace(**dict(vars(O), scale=None, sprite=m.sprite_choice(None))), m.KNOWLEDGE)
flagged = m.sprite_choice("yoru"); flagged_saved = m.read_state().get("sprite")
ck("63 the swap dissolves one character into the other in a running app, same spot, feet on the ground, same facing; the snooze, the home and the tips he has spent come through it; it persists",
   was[0] == "yoru" and now_[0] == "dane" and now_[1:5] == was[1:5] and (was[5], now_[5]) == (4, 2)
   and "morph" in seen_poses and "settle" not in seen_poses and seen_poses[-1] == "stand"
   and keys == {"yoru", "yoru>dane", "dane"} and kept and saved == "dane"
   and len(morph_keys) == len(set(morph_keys))
   and again.character.name == "dane" and flagged == "yoru" and flagged_saved == "yoru",
   "%s @%dx -> %s @%dx over %d frames; poses %s; x and ground line kept %s; snooze, home and seen kept %s; render keys %s, all %d dissolve frames distinct %s; state.json %r; next start %s; --sprite yoru -> %s saved %r" % (
       was[0], was[5], now_[0], now_[5], len(seen_poses),
       "".join("~" if p == "morph" else "." for p in seen_poses),
       now_[1:5] == was[1:5], kept, sorted(keys), len(morph_keys),
       len(morph_keys) == len(set(morph_keys)), saved, again.character.name, flagged, flagged_saved))
# Canvas and scale follow the character. A taller stand-in swapped in
# keeps the feet on the ground line: the bottom edge stays, the top
# rises, and w/h and the input region come from the new canvas at the
# new scale. --scale overrides every character's own.
tall = m.Character("tall", "Tall", m.dane_pixels, (48, 64), 3, ("walk",), 4.4, (0.5, 0.7), views=m.DANE_VIEWS)
m.SPRITES["tall"] = tall
try:
    p = sw.pet; bottom = p.y + p.h; hb = p.home_y + p.h
    p.request_swap("tall"); p.pose = "stand"
    for _ in range(90):                               # the laptop folds, then the dissolve
        sw.tick(); time.sleep(0.02)
        if p.character.name == "tall": break
    grew = (p.character.name == "tall" and p.px == 3 and p.h == 64 * 3 and p.y + p.h == bottom
            and p.home_y + p.h == hb)
    p.request_swap("dane")
    for _ in range(90):
        sw.tick(); time.sleep(0.02)
        if p.character.name == "dane": break
    back = p.character.name == "dane" and p.px == 2 and p.y + p.h == bottom
finally:
    del m.SPRITES["tall"]
    st = m.read_state(); st["sprite"] = "yoru"; m.save_json(m.STATE, st)
forced = m.Pet(types.SimpleNamespace(**dict(vars(O), scale=3, sprite="dane")), m.KNOWLEDGE)
forced_deer = m.Pet(types.SimpleNamespace(**dict(vars(O), scale=3, sprite="yoru")), m.KNOWLEDGE)
ck("64 canvas and scale are the character's: a 48x64 @3x stand-in keeps his feet on the ground line; --scale overrides both",
   grew and back and forced.px == 3 and forced.w == chars["dane"].w * 3 and forced_deer.px == 3 and forced_deer.w == 24 * 3,
   "grew %s, back %s; --scale 3: dane %dpx wide, deer %dpx" % (grew, back, forced.w, forced_deer.w))
# The Dane never roams: a character with roams=False stays home for the
# hour, so the walk, the bound and the trips are the deer's alone; the
# deer's pace still resolves to the 46-72 px/s he always had.
random.seed(3)
q = m.Pet(types.SimpleNamespace(**dict(vars(O), scale=None, sprite="dane")), m.KNOWLEDGE)
q.seen = set(); q.present_until = 1e9; q.next_talk = 1e9; q.step(.033, 0.0, 1920, 1080)
modes = collections.Counter(); t = 0.0; moved = 0
for i in range(int(3600 / .033)):
    t += .033; q.step(.033, t, 1920, 1080); modes[q.mode] += 1
    if q.moving() or q.gait(): moved += 1
deer = m.Pet(types.SimpleNamespace(**dict(vars(O), scale=None, sprite="yoru")), m.KNOWLEDGE)
random.seed(1); deer_speeds = [deer.walk_speed() for _ in range(200)]
ck("65 the dane never roams -- home all hour, no gait, no trip; the deer's pace is his old 46-72",
   modes["home"] == sum(modes.values()) and moved == 0 and q.x == q.home_x
   and 46 - 1e-6 <= min(deer_speeds) and max(deer_speeds) <= 72 + 1e-6,
   "1h: modes %s, moving frames %d; deer %.0f-%.0f px/s" % (dict(modes), moved, min(deer_speeds), max(deer_speeds)))
# The turn, as motion rather than as a list of drawings. Speaking walks
# him along his turn path and back when the bubble clears; the render key
# moves on each change, so every step of the fold is a frame that is
# actually drawn, and each one is held long enough to be seen -- which is
# the thing a sheet of stills cannot tell you and the reason these are
# measured in milliseconds here. The deer has no views and no tic and is
# drawn from the side whatever the Pet says: draw_sprite passes them only
# to a character that declares them.
DT = .033
def run_views(q, secs, t0=0.0):
    """Every view he holds, with how long he holds it, in milliseconds."""
    out = [[q.view, 0]]
    t = t0
    for _ in range(int(secs / DT)):
        t += DT; q.step(DT, t, 1920, 1080)
        if q.view != out[-1][0]: out.append([q.view, 0])
        out[-1][1] += DT * 1000
    return out, t
q = m.Pet(types.SimpleNamespace(**dict(vars(O), scale=None, sprite="dane")), m.KNOWLEDGE)
q.present_until = 1e9; q.next_talk = 1e9; quiet_idles(q); q.step(DT, 0.0, 1920, 1080)
keys = [q.render_key()]; t = 0.0
q.say("x", "hello", 1.0, 0.0)
held = [[q.view, 0.0]]
for _ in range(int(3.0 / DT)):
    t += DT; q.step(DT, t, 1920, 1080)
    if q.view != held[-1][0]:
        held.append([q.view, 0.0]); keys.append(q.render_key())
    held[-1][1] += DT * 1000
seq = [v for v, _ in held]
# the frames he passes through, which are the ones TURN_SECS times. Not
# the two ends, where he simply stays, and not the front one, which is
# held for as long as the bubble is up.
mid = [ms for v, ms in held[1:-1] if v != chars["dane"].turn[-1]]
want_ms = m.TURN_SECS * 1000
# working, for a minute: the render key moves only for the blink
moves = collections.Counter(); last = q.render_key()
for i in range(int(60 / DT)):
    t += DT; q.step(DT, t, 1920, 1080); key = q.render_key()
    if key != last:
        moves[tuple(i for i, (x, y) in enumerate(zip(key, last)) if x != y)] += 1
    last = key
blink_i = 5                                                 # render_key(): ..., pose, blink, ...
ck("66 speaking folds the laptop down a frame at a time and back, every frame of it drawn and held a TURN_SECS; working, nothing moves but the blink",
   seq == ["work", "folding", "closing", "speak", "closing", "folding", "work"]
   and all(a != b for a, b in zip(keys, keys[1:]))
   and all(abs(ms - want_ms) <= 40 for ms in mid)
   and moves and set(moves) == {(blink_i,)} and "tic" not in chars["dane"].tics,
   "states %s; held %s (TURN_SECS is %.0fms); every step a new render key %s; a working minute: key moved %d times, fields %s" % (
       " -> ".join(seq), ", ".join("%.0fms" % ms for ms in mid), want_ms,
       all(a != b for a, b in zip(keys, keys[1:])),
       sum(moves.values()), sorted(set(moves)) or "none"))
# The idle actions, watched rather than listed. Each one is a path of
# held frames in and the same path back out, IDLE_STEP each, with the
# last frame held for as long as the action lasts -- the deer's graze is
# a path of one, which is why it still behaves exactly as it did. Every
# frame of it is a different render key, or a step of it is never drawn.
# And through all of it his eyes stay down: he is working, not talking.
DTI = .033
def play(act, secs=8.0, sprite="dane"):
    """Force one idle action and report the poses he holds, in order,
    with how long each is held in milliseconds."""
    random.seed(5)
    p = m.Pet(types.SimpleNamespace(**dict(vars(O), scale=None, sprite=sprite)), m.KNOWLEDGE)
    p.seen = set(); p.place(1920, 1080); p.present_until = 1e9
    p.next_talk = p.next_roam = 1e9; quiet_idles(p)
    p.step(DTI, 0.0, 1920, 1080)
    p.next_idle[[a.pose for a in p.character.idles].index(act)] = 0.0
    out = [[p.pose, 0.0, p.render_key()]]; t = 0.0
    for _ in range(int(secs / DTI)):
        t += DTI; p.step(DTI, t, 1920, 1080)
        if p.pose != out[-1][0]: out.append([p.pose, 0.0, p.render_key()])
        out[-1][1] += DTI * 1000
    return p, out
bad = []; report = []
for ch_name, act in (("yoru", "graze"), ("dane", "sip"), ("dane", "beard")):
    p, held = play(act, sprite=ch_name)
    a = next(x for x in p.character.idles if x.pose == act)
    poses = [h[0] for h in held]
    want = ["stand"] + list(a.path) + list(reversed(a.path[:-1])) + ["stand"]
    if poses != want:
        bad.append((act, "poses %s, wanted %s" % (poses, want)))
    steps = [ms for pose, ms, _ in held[1:-1] if pose != act]
    if any(abs(ms - m.IDLE_STEP * 1000) > 40 for ms in steps):
        bad.append((act, "path frames held %s, wanted %.0fms" % (steps, m.IDLE_STEP * 1000)))
    on = next(ms for pose, ms, _ in held if pose == act)
    if not (a.secs[0] * 1000 - 60 <= on <= a.secs[1] * 1000 + 60):
        bad.append((act, "held %.0fms, wanted %.1f-%.1fs" % (on, *a.secs)))
    # adjacent, not unique: he passes through "reach" twice, once on the
    # way out and once on the way back, and those two are the same drawing
    keys = [h[2] for h in held]
    if any(a == b for a, b in zip(keys, keys[1:])):
        bad.append((act, "a frame of the path is never drawn"))
    report.append("%s: %s, path frames %s, held %.0fms"
                  % (act, "-".join(poses), ", ".join("%.0fms" % x for x in steps) or "none", on))
# The eyes, and the mug. Through every frame of the coffee he is looking
# down -- check 60 already proves that from the drawing -- and the mug is
# carried, not redrawn: every pixel of it that the laptop and his own
# hand are not covering is the mug's own tone, in every frame of the
# path, with the coffee showing until he tips it to drink.
pal = m.dane_palette()
def hidden(x, y, view, pose):
    for ly0, ly1, lx0, lx1 in (m.LAPTOP_LID[view], m.LAPTOP_BASE):
        if ly0 <= y <= ly1 and lx0 <= x <= lx1: return True
    dy, dx = m.MUG_CARRY[pose]
    return any(y == hy + dy and hx0 + dx <= x <= hx1 + dx for hy, hx0, hx1 in m.MUG_HAND)
carried = []
for pose, (dy, dx) in sorted(m.MUG_CARRY.items()):
    for view in chars["dane"].turn:
        comp = {(x, y): col for x, y, col in m.dane_pixels(1, False, pose, view=view)}
        body = [(x, y) for y in range(m.MUG[0], m.MUG[1] + 1) for x in range(m.MUG[2], m.MUG[3] + 1)]
        body += [(x, y) for y, x0, x1 in m.MUG_HANDLE for x in range(x0, x1 + 1)]
        cof = [(x, m.MUG_COFFEE[0]) for x in range(m.MUG_COFFEE[1], m.MUG_COFFEE[2] + 1)]
        tipped = pose in m.MUG_TIPPED
        for x, y in body:
            X, Y = x + dx, y + dy
            if hidden(X, Y, view, pose): continue
            want = pal["F"] if ((x, y) in cof and not tipped) else pal["s"]
            if comp.get((X, Y)) != want:
                carried.append((pose, view, (X, Y))); break
ck("67 the coffee and the beard stroke go in and come back out a frame at a time, each held frame drawn and timed; the deer's graze is still the one frame it always was; the mug is carried whole, and tipped it stops showing its coffee",
   not bad and not carried,
   "%s; mug wrong at %s" % ("; ".join(report), carried[:3] or "none"))
# How often. Each action has a clock of its own and that is the whole of
# what makes one rarer than another, so this measures them over four
# hours rather than trusting the numbers in the table. What it is really
# checking is the share: he is at a desk working, and stillness at work
# reads as focus. A man who reaches for his coffee every thirty seconds
# reads as a screensaver.
HOURS, DTL = 4, 0.1
random.seed(17)
p = m.Pet(types.SimpleNamespace(**dict(vars(O), scale=None, sprite="dane")), m.KNOWLEDGE)
p.seen = set(); p.place(1920, 1080); p.present_until = 1e9; p.next_talk = 1e9
p.step(DTL, 0.0, 1920, 1080)
runs = [[None, 0.0]]; t = 0.0; busy = 0; overlap = 0
for _ in range(int(HOURS * 3600 / DTL)):
    t += DTL; p.step(DTL, t, 1920, 1080)
    p.present_until = t + 1e6
    act = p.idle.pose if p.idle else None
    if act != runs[-1][0]: runs.append([act, 0.0])
    runs[-1][1] += DTL
    if p.pose != "stand": busy += 1
bouts = collections.Counter(a for a, _ in runs if a)
share = busy * DTL / (HOURS * 3600)
# and nothing starts while he is speaking, snoozed, or the chair is empty
quiet = {}
for name, setup in (("snoozed", lambda q: setattr(q, "snooze_until", 1e9)),
                    ("away", lambda q: setattr(q, "present_until", 0.0)),
                    ("--still", lambda q: setattr(q, "still", True))):
    random.seed(23)
    q = m.Pet(types.SimpleNamespace(**dict(vars(O), scale=None, sprite="dane")), m.KNOWLEDGE)
    q.seen = set(); q.place(1920, 1080); q.next_talk = 1e9; q.present_until = 1e9
    setup(q)
    started = 0; tq = 0.0
    for _ in range(int(3600 / DTL)):
        tq += DTL; q.step(DTL, tq, 1920, 1080)
        if name != "away": q.present_until = tq + 1e6
        if q.idle is not None: started += 1
    quiet[name] = started
# a word mid-sip puts the mug back on the desk a frame at a time
p2, held2 = play("sip", secs=1.2)
p2.say("x", "hello", 2.0, 1.2)
back = [p2.pose]; t2 = 1.2
for _ in range(int(2.0 / DTI)):
    t2 += DTI; p2.step(DTI, t2, 1920, 1080)
    if p2.pose != back[-1]: back.append(p2.pose)
path = list(m.COFFEE_PATH)
want_back = path[path.index(back[0])::-1] + ["stand"] if back[0] in path else None
spoke_up = [b for b in back if b in path[1:]] and back[-1] == "stand"
ck("68 how often: the beard stroke is the rarer of the two, both are minutes apart, and he is working for almost all of it; nothing starts while he speaks, sleeps or the chair is empty; a word mid-sip puts the mug back rather than vanishing it",
   bouts["beard"] * 2 < bouts["sip"] and 20 <= bouts["sip"] <= 110 and 4 <= bouts["beard"] <= 30
   and share < 0.05 and not any(quiet.values()) and back == want_back,
   "%dh: %d coffees, %d beard strokes, idle %.1f%% of the time; held off while %s; interrupted sip goes %s"
   % (HOURS, bouts["sip"], bouts["beard"], share * 100,
      ", ".join("%s (%d)" % (k, v) for k, v in quiet.items()), "-".join(back)))
# Head down, as motion. The laptop is shut before the head moves and the
# head is up before it opens -- it used to go from a lid seven rows tall
# to a slab in the one frame the head dropped -- and his settle frame is
# his own, longer than the deer's, because he has further to go.
random.seed(29)
p = m.Pet(types.SimpleNamespace(**dict(vars(O), scale=None, sprite="dane")), m.KNOWLEDGE)
p.seen = set(); p.place(1920, 1080); p.present_until = 1e9; p.next_talk = 1e9; quiet_idles(p)
p.step(DTI, 0.0, 1920, 1080)
down = [[(p.pose, p.view), 0.0, p.render_key()]]; t = 0.0
for i in range(int(6.0 / DTI)):
    t += DTI
    if i == 2: p.snooze_until = t + 2.5
    if abs(t - 3.2) < DTI / 2: p.snooze_until = 0.0
    p.step(DTI, t, 1920, 1080)
    if (p.pose, p.view) != down[-1][0]:
        down.append([(p.pose, p.view), 0.0, p.render_key()])
    down[-1][1] += DTI * 1000
steps = [(pose, view, ms) for (pose, view), ms, _ in down]
lids = [m.LAPTOP_LID["speak" if pose in ("rest", "settle") else view][0] for pose, view, _ in steps]
fold_first = all(pose == "stand" for pose, _, _ in steps[:steps.index(
    next(s for s in steps if s[0] == "settle"))])
shut = m.LAPTOP_LID[chars["dane"].turn[-2]][0]
settles = [ms for pose, _, ms in steps if pose == "settle"]
keys = [d[2] for d in down]
ck("69 his head goes down behind a laptop that is already shut: the lid folds first, a frame at a time, then the settle, then his head is on his arms -- and the same in reverse coming up, his own settle frame held longer than the deer's",
   fold_first and [pose for pose, _, _ in steps] == ["stand"] * 3 + ["settle", "rest", "settle"] + ["stand"] * 3
   and all(abs(ms - m.DANE_SETTLE_SECS * 1000) <= 40 for ms in settles)
   and m.DANE_SETTLE_SECS > m.SETTLE_SECS
   and all(a != b for a, b in zip(keys, keys[1:]))
   and all(a <= b for a, b in zip(lids, lids[1:len(lids) // 2 + 1])),
   "%s; settle held %s (his own is %.0fms, the deer's %.0fms); lid top row %s"
   % (" -> ".join("%s/%s %.0fms" % s for s in steps), ", ".join("%.0fms" % x for x in settles),
      m.DANE_SETTLE_SECS * 1000, m.SETTLE_SECS * 1000, lids))
# The accent, everywhere, not just on his face. Check 60 watched the face
# because that is where a glow was once drawn and read as a rash; this
# watches the whole canvas, because the thing that actually got through
# was two pixels of the O on his chest walking out from behind the desk
# at the settle frame and sitting under the table. The rule is simple
# enough to state absolutely: the accent is his irises and the letter on
# his shirt, and nothing else in the scene is ever it.
O_MARK = {(x + m.DANE_SEAT[0], y + m.DANE_SEAT[1])
          for y, row in enumerate(m.DANE_FRONT) for x, ch in enumerate(row) if ch == "A"}
loose = []; irises = 0
for k, pts in dane_frames():
    view, pose, blink = k[0], k[1], k[2]
    comp = {(x, y): col for x, y, col in pts}
    acc = {p for p, col in comp.items() if col == E}
    eyes = {p for p in acc if p[1] < m.DESK_TOP[0] - 10 and p not in O_MARK}
    stray = acc - O_MARK - eyes
    if stray:
        loose.append((k, sorted(stray)[:3]))
    # and the eyes are two irises, or none at all when they are shut
    if pose != "rest" and len(eyes) not in (0, 2):
        loose.append((k, "%d irises" % len(eyes)))
    irises += len(eyes)
ck("70 the accent is his irises and the O on his shirt, and nothing else in the scene is ever it, in any view or pose",
   not loose, "%d frames, %d irises among them; loose accent at %s"
   % (sum(1 for _ in dane_frames()), irises, loose[:3] or "none"))
# The dissolve, measured. The swap is the one moment the user is watching
# for -- it is the whole feedback for a keypress -- so this is about what
# it costs and what survives it rather than about what it looks like; the
# looking was done with tools/render-demo.py --acts swap.
DTS = .033
def one_swap(start, snoozed=False, secs=3.0):
    """Drive a Pet through a swap, recording what would actually be drawn
    on every frame of it."""
    random.seed(4)
    q = m.Pet(types.SimpleNamespace(**dict(vars(O), scale=None, sprite=start)), m.KNOWLEDGE)
    q.seen = {"a-tip"}; q.place(1920, 1080); q.present_until = 1e9; q.next_talk = 1e9
    quiet_idles(q)
    t = 0.0
    q.step(DTS, t, 1920, 1080)
    if snoozed:
        q.snooze_until = 1e9
    before = (q.x, q.dir, q.y + q.h, q.home_x, set(q.seen), q.snooze_until)
    q.request_swap()
    rows = []
    for _ in range(int(secs / DTS)):
        t += DTS; q.step(DTS, t, 1920, 1080)
        mix = None
        if q.pose == "morph":
            p = q.morph_progress()
            out_all, in_all = m.sprite_pixels(q, q.character), m.sprite_pixels(q, q.morph)
            out, into = m.morph_keep(out_all, p, True), m.morph_keep(in_all, p, False)
            mix = (len(out) / float(len(out_all)), len(into) / float(len(in_all)),
                   {c for _, _, c in out} | {c for _, _, c in into},
                   {c for _, _, c in out_all} | {c for _, _, c in in_all},
                   q.px_of(q.character), q.px_of(q.morph),
                   q.y + q.h, q.y + q.h)          # both stand on the same line
        rows.append((q.pose, q.view, q.character, q.morph, mix, q.render_key()))
    after = (q.x, q.dir, q.y + q.h, q.home_x, set(q.seen), q.snooze_until)
    return q, before, after, rows

bad = []; report = []
for start, other in (("yoru", "dane"), ("dane", "yoru")):
    q, before, after, rows = one_swap(start)
    mo = [i for i, r in enumerate(rows) if r[0] == "morph"]
    if not mo:
        bad.append((start, "never dissolved")); continue
    held = len(mo) * DTS
    if abs(held - m.MORPH_SECS) > DTS * 1.5:
        bad.append((start, "the dissolve ran %.2fs, not %.2f" % (held, m.MORPH_SECS)))
    if mo != list(range(mo[0], mo[-1] + 1)):
        bad.append((start, "something interrupted the dissolve"))
    # door to door: the ask, the laptop, the dissolve, the laptop again
    done = next((i for i, r in enumerate(rows)
                 if r[2].name == other and (not r[2].turn or r[1] == r[2].turn[0])), None)
    door = (done + 1) * DTS if done is not None else 99.0
    if door > 1.0:
        bad.append((start, "the whole swap took %.2fs" % door))
    # every frame of the dissolve is a frame that gets drawn
    keys = [rows[i][5] for i in mo]
    if any(x == y for x, y in zip(keys, keys[1:])):
        bad.append((start, "a dissolve frame is never drawn"))
    # he changes as himself: the laptop shut, the deer standing
    if rows[mo[0]][2].turn and rows[mo[0]][1] != rows[mo[0]][2].turn[-2]:
        bad.append((start, "his laptop was not shut: %s" % rows[mo[0]][1]))
    if any(rows[i][0] != "morph" for i in range(mo[0], mo[-1] + 1)):
        bad.append((start, "he was not only dissolving"))
    # the mix: him at the start, the other at the end, both in the middle
    first, mid, last = rows[mo[0]][4], rows[mo[len(mo) // 2]][4], rows[mo[-1]][4]
    if not (first[0] > 0.85 and first[1] < 0.15):
        bad.append((start, "it does not start on him: %.2f/%.2f" % first[:2]))
    if not (last[0] < 0.15 and last[1] > 0.85):
        bad.append((start, "it does not finish on the other: %.2f/%.2f" % last[:2]))
    if not (0.2 < mid[0] < 0.8 and 0.2 < mid[1] < 0.8):
        bad.append((start, "the middle is not a mix: %.2f/%.2f" % mid[:2]))
    # nothing is blended -- every colour drawn is one of theirs, unmixed --
    # and each keeps its own pixel size, on the one ground line they share
    if any(not (rows[i][4][2] <= rows[i][4][3]) for i in mo):
        bad.append((start, "a colour appeared that neither of them has"))
    if first[4] == first[5]:
        bad.append((start, "both drew at the same pixel size"))
    if any(rows[i][4][6] != rows[i][4][7] for i in mo):
        bad.append((start, "they did not share the ground line"))
    if before[:4] != after[:4] or before[4] != after[4]:
        bad.append((start, "something was lost: %s -> %s" % (before, after)))
    report.append("%s->%s %d frames/%.2fs, door to door %.2fs, middle %d%%/%d%%, %dpx and %dpx"
                  % (start, other, len(mo), held, door, mid[0] * 100, mid[1] * 100,
                     first[4], first[5]))
# and snoozed he still changes: he stands up for it and lies back down
qs, before_s, after_s, rows_s = one_swap("dane", snoozed=True, secs=4.0)
slept = [r[0] for r in rows_s]
snoozed_ok = (before_s[5] == after_s[5] == 1e9 and "morph" in slept
              and slept[-1] == "rest" and qs.character.name == "yoru")
if not snoozed_ok:
    bad.append(("snoozed", "%s, ended %s as %s" % ("morph" in slept, slept[-1], qs.character.name)))
ck("71 the dissolve: about half a second of it, the whole swap under one, every frame of it drawn, a real mix of the two in the middle at their own pixel sizes on one ground line; nothing blended, nothing lost; snoozed, he stands up to change and lies back down",
   not bad,
   "%s; snoozed: he changed %s and ended %s" % ("; ".join(report) or "nothing ran",
                                                snoozed_ok, slept[-1] if slept else "?")
   + ("; WRONG: %s" % (bad[:3],) if bad else ""))
sw.stop(); sw.win.destroy()
# The three places a user is told what to put in their Hyprland config:
# install.sh, which writes it; yoru.install, which prints it because a
# package must not write it; and the README's by-hand block, for anyone who
# wants to see each step. They are three copies of the same two lines and
# they drift -- the swap key was added to the first and the third and
# stayed out of the second for a release, so everyone who installed through
# pacman was never told Super + Ctrl + Shift + Y existed, which for a
# keybinding is the same as it not existing. This is the check that would
# have caught it, and it will catch the next one.
#
# The path is allowed to differ and has to: ~/.local/bin/yoru from the
# script, /usr/bin/yoru from the package, a spelled-out home in the README.
# The key, the label and the signal are not allowed to.
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def shipped(name):
    """The file with its shell escaping undone, and install.sh's $bin
    expanded to the path it holds -- otherwise the one copy that is written
    by a script rather than printed looks like it names no binary at all."""
    text = open(os.path.join(root, name)).read().replace('\\"', '"').replace("\\$", "$")
    var = re.search(r'^bin="([^"]+)"', text, re.M)
    return text.replace("$bin", var.group(1)) if var else text
BIND = re.compile(r'''o\.bind\("([^"]+)",\s*"([^"]+)",\s*"pkill -(\S+) -f '([^']+)'"\)''')
LAUNCH = re.compile(r'o\.launch_on_start\("([^"]+)"\)')
inst, pkg, doc = shipped("install.sh"), shipped("yoru.install"), shipped("README.md")
# post_install is the one that has to be complete; post_upgrade may mention
# a subset, and does -- it tells people upgrading about the new key only.
pkg_install, _, pkg_upgrade = pkg.partition("post_upgrade()")
# the README's by-hand block is the fenced lua that has binds in it
doc_block = next((b for b in re.findall(r"```lua\n(.*?)```", doc, re.S) if "o.bind(" in b), "")
doc_launch = next((b for b in re.findall(r"```lua\n(.*?)```", doc, re.S) if "launch_on_start" in b), "")
where = {"install.sh": inst, "yoru.install (post_install)": pkg_install,
         "README by-hand block": doc_block}
binds = {k: BIND.findall(v) for k, v in where.items()}
keys = {k: {(b[0], b[1], b[2]) for b in v} for k, v in binds.items()}
agreed = set.intersection(*keys.values()) if all(keys.values()) else set()
drift = {k: sorted(v ^ agreed) for k, v in keys.items() if v != agreed}
# every pattern keeps the boundary that stops pkill reaching an editor with
# the file open, and names a yoru binary
loose = [(k, b[3]) for k, v in binds.items() for b in v
         if not b[3].endswith("( |$)") or "yoru" not in b[3]]
# the launch line is the same story and drifts the same way
launched = {k: bool(LAUNCH.search(v)) for k, v in
            (("install.sh", inst), ("yoru.install", pkg_install),
             ("README", doc_launch))}
# and a signal nobody handles is as useless as a key nobody is told about
handled = set(re.findall(r"signal\.SIG(\w+)", src)) & {"USR1", "USR2", "USR3"}
signalled = {b[2].lstrip("-") for v in binds.values() for b in v}
extra = sorted(signalled - handled) + sorted(handled - signalled)
ck("72 install.sh, yoru.install and the README's by-hand block tell you to bind the same keys to the same signals, every pattern keeps its word boundary, and every signal is one he handles",
   not drift and not loose and all(launched.values()) and not extra and len(agreed) >= 2,
   "%d bindings agreed on (%s); drift %s; patterns without the boundary %s; launch line present %s; signals bound %s, handled %s" % (
       len(agreed), ", ".join("%s->%s" % (k[0], k[2]) for k in sorted(agreed)) or "none",
       drift or "none", loose or "none",
       ", ".join(k for k, v in launched.items() if v) or "nowhere",
       sorted(signalled) or "none", sorted(handled)))
print("\n%d/%d  FAILURES: %s" % (N - len(F), N, F or "none"))
