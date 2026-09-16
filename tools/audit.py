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
oob = [(pose, b, f) for pose in ("stand", "graze", "rest", "settle") for b in (False, True)
       for f in range(4) for e in (0, 1) for tl in (0, 1)
       if (lambda q: min(z[0] for z in q) < -3 or max(z[0] for z in q) > 27
           or min(z[1] for z in q) < -4 or max(z[1] for z in q) > 25)(
           m.pixels(f, False, pose, e, tl, b))]
ck("26 all pose combos in bounds", not oob, oob[:2])
# A floating pixel is a rendering fault in any pose, and a pixel-diff that
# only looks at what was removed passes an added one happily. Every pixel of
# every combination -- pose, gait, frame, blink, ear, tail, chew, doze,
# parked or moving -- must have an 8-neighbour in the sprite, and the sprite
# must be one piece. Parked he does not bob; trotting, the body rises a row
# on frames 1 and 3 and the legs lengthen to meet it; bounding, the legs
# lift with the body. So every frame is one piece. It was five, parked and
# on the trot's pass frames, from the first commit until the bob stopped
# applying to a standing animal.
def neighbours(p, pts):
    return [(p[0] + dx, p[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            if (dx or dy) and (p[0] + dx, p[1] + dy) in pts]
def components(pts):
    seen = set(); n = 0
    for p in pts:
        if p in seen: continue
        n += 1; stack = [p]; seen.add(p)
        while stack:
            for q in neighbours(stack.pop(), pts):
                if q not in seen: seen.add(q); stack.append(q)
    return n
lonely = []; pieces = collections.Counter(); combos = 0
for pose in ("stand", "graze", "rest", "settle"):
    for b in (False, True):
        for f in range(4):
            for e in (0, 1):
                for tl in (0, 1):
                    for chew in (0, 1):
                        for doze in (0, 1):
                            for blink in (False, True):
                                for moving in (False, True):
                                    combos += 1
                                    pts = {(x, y) for x, y, _ in m.pixels(f, blink, pose, e, tl, b, chew, doze, moving)}
                                    lonely += [(pose, f, p) for p in pts if not neighbours(p, pts)]
                                    pieces[(pose, "moving" if moving else "parked", f, components(pts))] += 1
multi = sorted({(pose, mv, f, n) for (pose, mv, f, n), _ in pieces.items() if n > 1})
# parked he must not bob at all: the body (rows 0-17) sits where frame 0's
# does on every frame, and only when moving does it rise on frames 1 and 3
body = lambda f, mv: sorted(p for p in m.pixels(f, False, "stand", moving=mv) if p[1] <= 17)
still = all(body(f, False) == body(0, False) for f in range(4)) and body(1, True) != body(0, True)
ck("51 every frame one piece, no floating pixel, no bob while parked", not lonely and not multi and still,
   "%d combinations, floating: %s; more than one piece: %s; parked body never moves, trotting body does: %s" % (
       combos, lonely[:3] or "none", ", ".join("%s %s frame %d -> %d" % x for x in multi) or "none", still))
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
def inside(w, h): return (4 <= q.x <= w - q.w - 4 and 4 <= q.y <= h - q.h - 4
                          and 4 <= q.home_x <= w - q.w - 4 and 4 <= q.home_y <= h - q.h - 4)
migrated = inside(1280, 774)
region = (int(q.x), int(q.y), int(q.w), int(q.h)); landed = (q.x, q.y, q.home_x, q.home_y)
region_ok = region[0] >= 0 and region[1] >= 0 and region[0] + region[2] <= 1280 and region[1] + region[3] <= 774
# The roam gap: a stranded y used to survive a walk. Force a walk at the new
# size from an off-surface y and check he is on it while walking.
q.y = q.home_y = 900; q.next_roam = 0; q.pause = 0; q.mode = "home"
for i in range(12): q.step(.033, 2.0 + i * .033, 1280, 774)   # he is away, so up off the ground first
walk_ok = q.mode == "out" and 4 <= q.y <= 774 - q.h - 4
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
q = m.Pet(O, m.KNOWLEDGE); q.seen = set(); q.next_talk = 1e9; q.next_roam = 1e9; q.next_graze = 1e9
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
q = app.pet; q.seen = set(); q.present_until = 1e9; q.next_talk = q.next_roam = q.next_graze = 1e9
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
    q = fresh_pet(**kw); q.next_talk = q.next_roam = q.next_graze = 1e9
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
q = fresh_pet(); q.present_until = 1e9; q.next_talk = q.next_roam = q.next_graze = 1e9
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
print("\n%d/%d  FAILURES: %s" % (N - len(F), N, F or "none"))
