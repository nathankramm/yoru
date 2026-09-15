"""How fast does he run out of things to say?

    python3 tools/exhaust.py yoru.py

This is where the cadence defaults came from: BASICS_INTERVAL, the 900
default for --interval, and the per-pass doubling. Rerun it before moving
any of them.

Drives the real Pet.step() at one-second ticks with a fresh HOME, so
seen.json, known.json and state["shown"] start empty like a new user's.
The two-speed cadence and the decay are the Pet's own; nothing is emulated.
Presence is real (saw_activity every 60 s while "at the machine", nothing
while away, --idle 300). Contextual tips use the App's own rules copied
verbatim — cooldown, at most two per window class per day, pick() with
cls/context — driven by a synthetic focus schedule: the user changes window
every 10 minutes through foot, foot+nvim, chromium, the agent window and
foot+lazygit. That is a developer's day; the cap is per class, so it yields
at most 2 (foot) + 2 (chromium) + 2 (agent) = 6 contextual tips a day.
"""
import importlib.util, os, random, sys, tempfile, types, statistics

os.environ["HOME"] = tempfile.mkdtemp()
sp = importlib.util.spec_from_file_location("y", sys.argv[1])
m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
m.visible = True
N = len(m.KNOWLEDGE)
FUND = set(m.FUNDAMENTAL)

FOCUS = [("foot", "foot ~"), ("foot", "foot nvim main.py"), ("chromium", "chromium docs"),
         ("org.omarchy.agent", "org.omarchy.agent claude"), ("foot", "foot lazygit")]


def fresh(interval, **kw):
    for f in (m.SEEN, m.KNOWN, m.STATE):
        try: os.remove(f)
        except OSError: pass
    o = types.SimpleNamespace(scale=4, corner="br", margin=24, interval=interval,
                              roam=180, cooldown=90, idle=300, **kw)
    p = m.Pet(o, list(m.KNOWLEDGE))
    return p


def run(interval, hours_per_day, context, seed, **kw):
    """Simulate presence H hours a day until all N tips have been shown once.
    Returns (hours_of_presence_to_exhaust, days, tips_per_hour, hours_to_all_fundamentals,
             ctx_tips, chatter_lines, tips_per_hour_after_basics)."""
    random.seed(seed)
    p = fresh(interval, **kw)
    now = 0.0; present_h = 0.0; day = 0
    seen_ids = set(); ctx_tips = 0; chatter = 0; fund_done = None
    exhausted = None
    last_cls = None; offers = {}; fi = 0; next_switch = 600
    # --no-basics has no fast phase: the whole run is "after basics".
    after_tips, after_start = (0, 0.0) if kw.get("no_basics") else (None, None)
    while exhausted is None:
        day += 1; offers = {}
        for sec in range(int(hours_per_day * 3600)):
            now += 1.0
            if sec % 60 == 0:
                p.saw_activity(now)
            before = p.shown; was_text = p.text
            p.step(1.0, now, 1920, 1080)
            if p.shown > before:                       # an ambient tip landed
                seen_ids.add(m.tip_id(p.current))
            elif p.text and not was_text:              # ambient, but chatter
                chatter += 1
            # -- contextual channel, the App's rules ------------------------
            if context:
                next_switch -= 1
                if next_switch <= 0:
                    next_switch = 600; fi = (fi + 1) % len(FOCUS)
                cls, full = FOCUS[fi]
                if cls != last_cls:
                    last_cls = cls
                    held = (p.snoozing(now) or not p.present(now)
                            or now - p.last_spoke < 90 or offers.get(cls, 0) >= 2)
                    if not held:
                        t = p.pick(cls=cls, context=full, why="contextual")
                        if t:
                            p.say_tip(t, 9.0, now); offers[cls] = offers.get(cls, 0) + 1
                            ctx_tips += 1; seen_ids.add(m.tip_id(t))
            if fund_done is None and FUND <= seen_ids:
                fund_done = present_h + (sec + 1) / 3600
                if after_start is None:
                    after_start, after_tips = fund_done, len(seen_ids)
            if len(seen_ids) >= N:
                exhausted = present_h + (sec + 1) / 3600
                break
        present_h += hours_per_day
        # away: nothing is spent. Skip the clock forward without stepping.
        now += (24 - hours_per_day) * 3600
    tips = len(seen_ids)
    after_rate = ((tips - after_tips) / (exhausted - after_start)
                  if after_start is not None and exhausted > after_start else 0)
    return exhausted, day, tips / exhausted, fund_done, ctx_tips, chatter, after_rate


def cell(vals, fmt="%.1f"):
    return fmt % statistics.mean(vals)


SEEDS = range(12)
rows = [(300, {}), (600, {}), (900, {}), (1800, {}), (900, {"no_basics": True})]
for context in (False, True):
    print("Ambient only (no window switching), 6 h/day:" if not context else
          "With a developer's window switching (contextual tips on, capped 2/class/day), 6 h/day:")
    print("| --interval | tips/h | after basics | %s | all %d fundamentals | hours to %d | days @4h | days @6h | days @8h |"
          % ("chatter/h" if not context else "contextual/day", len(FUND), N))
    print("|---|---|---|---|---|---|---|---|---|")
    for iv, kw in rows:
        label = "%d%s" % (iv, " --no-basics" if kw else "")
        r6 = [run(iv, 6, context, s, **kw) for s in SEEDS]
        d4 = [run(iv, 4, context, s, **kw)[1] for s in SEEDS]
        d8 = [run(iv, 8, context, s, **kw)[1] for s in SEEDS]
        print("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            label, cell([r[2] for r in r6]), cell([r[6] for r in r6]),
            cell([r[5] / r[0] for r in r6]) if not context else cell([r[4] / r[1] for r in r6]),
            (cell([r[3] for r in r6]) + " h") if not kw else "no tier",
            cell([r[0] for r in r6], "%.0f"),
            cell(d4, "%.0f"), cell([r[1] for r in r6], "%.0f"), cell(d8, "%.0f")))
    print()
