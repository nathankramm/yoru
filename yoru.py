#!/usr/bin/env python3
"""
yoru — a Clippy for Omarchy, minus the reasons everyone hated Clippy.

A pixel deer parks in a corner of your screen and tells you things about
Omarchy 4 (Quattro). Every tip was checked against the installed release
under /usr/share/omarchy, not the manual — which lists Super + Q to close a
window, and it isn't bound. He knows the desktop, the CLI, the coding
agents, the shell tools, tmux, Herdr, Foot, Neovim, lazygit, lazydocker,
btop, the file manager, browsers and updates — and he notices which of
those you are in.

Where he sits
    Bottom right by default, 24px off each edge. Drag him anywhere with the
    left mouse button and he stays there; the spot is saved to
    ~/.config/yoru/state.json and survives a reboot. He lives on one
    monitor: the focused one when he starts, or --monitor DP-1 to choose
    (falls back to the focused one if that output isn't connected).

What he does
    Ambient  — a tip or a remark every fifteen minutes, every five until
                 the eighteen first-hour tips are done, and slower on each
                 pass through the corpus. Never a tip twice until he's run out.
    Contextual — when you focus a new app he offers something for that app,
                 at most twice per app per day, never inside the cooldown.
    On demand  — right click for the next tip, middle click to snooze an hour.

Deps (Arch / Omarchy)
    sudo pacman -S --needed python-gobject gtk4 gtk4-layer-shell python-cairo

Run
    python3 yoru.py
    python3 yoru.py --corner bl --scale 5 --interval 240 --topics nvim,tmux
    python3 yoru.py --ask screenshot        # search his knowledge, print, exit
    python3 yoru.py --list                  # everything he knows
    python3 yoru.py --debug 2>yoru.log      # why he did what he did

Your own tips
    ~/.config/yoru/tips.txt — one per line, "Super + Y | what it does".
    Lines with no pipe become idle remarks. Every o.bind in your
    ~/.config/hypr/bindings.lua with a description becomes a tip as well,
    in your words, unless a stock tip already covers the key (--no-own to
    stop that).
"""

import argparse
import datetime
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

VERSION = "1.0.1"

CONFIG = os.path.expanduser("~/.config/yoru")
STATE = os.path.join(CONFIG, "state.json")
SEEN = os.path.join(CONFIG, "seen.json")
KNOWN = os.path.join(CONFIG, "known.json")
USER_TIPS = os.path.join(CONFIG, "tips.txt")
OWN_BINDS = os.path.expanduser("~/.config/hypr/bindings.lua")
OWN_CAP = 25

# --debug. Every decision he makes goes to stderr with a timestamp, so a
# stranger's "he said the wrong thing" arrives with the why attached. The
# message is only formatted once the flag has been checked, so an argument
# list costs nothing when it's off; anything dearer than that sits behind
# its own `if DEBUG:`.
DEBUG = False


def debug(msg, *args):
    if DEBUG:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("yoru %s %s" % (stamp, msg % args if args else msg),
              file=sys.stderr, flush=True)

# Hidden is not dead. SIGUSR1 flips this and the process carries on stepping,
# so his spot, his snooze and what he has and hasn't said all survive a
# "get out of the way for a minute". Compare pkill, which would reset all
# of it and replay the intro.
visible = True
_on_visibility = []             # the running app's reaction, if any


def toggle_visible(*_):
    global visible
    visible = not visible
    debug("visible: %s (SIGUSR1)", "shown" if visible else "hidden")
    for fn in _on_visibility:
        fn(visible)
    return True                 # keep the signal watch installed

# ---------------------------------------------------------------- sprite ----
# 24x24. Rows 0-17 come from this map; legs are animated in code.
BODY = [
    "..........a..a..a.......",
    "...........a.ad.ad......",
    "............aaaa.d......",
    ".............ddaa.......",
    "................aa......",
    "...............bbbbbb...",
    "..............bbbbbbbb..",
    "................bebbbbb.",
    ".................bbbbbb.",
    "................bbbbb...",
    "..............bbbbb.....",
    "............bbbbbb......",
    "ccbbbbbbbbbbbbbbbb......",
    "ccbbbbbbbbbbbbbbbb......",
    "..bbbbbbbbbbbbbbbb......",
    "..bbbbbbbbbbbbbbb.......",
    "..bccccccccccccbb.......",
    "..bbcccccccccbbb........",
]
SW = SH = 24


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


# Fallback palette (Tokyo Night) — replaced at runtime by the live Omarchy theme.
PAL = {
    "a": rgb("a9b1d6"),   # near antler
    "d": rgb("8f98c4"),   # far antler
    "b": rgb("c0caf5"),   # coat
    "c": rgb("e3e9fb"),   # underside and tail
    "e": rgb("7dcfff"),   # eye
}
FAR, FAR_HOOF, HOOF = rgb("7f88b5"), rgb("353a58"), rgb("414868")
OUTLINE = rgb("16161e")
BUBBLE_BG = rgb("1a1b26")
ACCENT_HEX = "#7dcfff"
REST_HOOF = None        # set below, once _rest_hoof exists

THEME_COLORS = os.path.expanduser("~/.local/state/omarchy/current/theme/colors.toml")
THEME_NAME = os.path.expanduser("~/.local/state/omarchy/current/theme.name")


def _blend(a, b, t):
    """Mix two rgb triples; t=0 is all a."""
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


def _lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _rest_hoof():
    """The hoof tone for the resting pose: whichever of the two hoof tones
    sits further in luminance from the strip of shade the hooves lie in.
    Lying down, a hoof is a mark in that strip and nothing else, and a mark
    too close in value to it melts away -- which is what happened to the
    first attempt. Every shipped theme picks FAR_HOOF today, but on some
    the other tone is within 0.02 of the strip, so it is measured rather
    than assumed: a theme must not be able to take the hooves away."""
    return max((FAR_HOOF, HOOF), key=lambda c: abs(_lum(c) - _lum(FAR)))


def read_theme():
    """The live palette, via Omarchy's own resolver when it's available.

    `omarchy theme color --all` applies the same alias/fallback cascade the
    themed templates use, so we get exactly what every other app gets. If the
    binary isn't there we parse colors.toml ourselves; if that's missing too
    the built-in palette stands.
    """
    out = {}
    try:
        # omarchy-theme-color is marked hidden in the CLI, so call the
        # binary directly and only then try the subcommand form. It prints
        # "key<TAB>value" per line.
        for cmd in (["omarchy-theme-color", "--all"],
                    ["omarchy", "theme", "color", "--all"]):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if r.returncode == 0 and "\t" in r.stdout:
                for line in r.stdout.splitlines():
                    if "\t" in line:
                        k, v = line.split("\t", 1)
                        out[k.strip()] = v.strip()
                break
    except Exception:
        pass
    if not out:
        try:
            for line in open(THEME_COLORS):
                line = line.split("#", 1)[0] if line.strip().startswith("#") else line
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"\'')
        except OSError:
            return None
    return out or None


def apply_theme():
    """Repaint Yoru in the current theme. Semantic keys, so light modes work:
    the coat is the theme's foreground, so it always contrasts with its
    background, whichever way round they are."""
    global PAL, FAR, FAR_HOOF, HOOF, OUTLINE, BUBBLE_BG, ACCENT_HEX, REST_HOOF
    t = read_theme()
    if not t:
        return False

    def col(key, *fallbacks):
        for k in (key,) + fallbacks:
            v = t.get(k, "")
            if isinstance(v, str) and v.startswith("#") and len(v) in (4, 7):
                try:
                    return rgb(v if len(v) == 7 else
                               "#" + "".join(c * 2 for c in v[1:]))
                except ValueError:
                    continue
        return None

    bg = col("background") or rgb("16161e")
    fg = col("foreground") or rgb("c0caf5")
    accent = col("accent", "cyan", "blue") or rgb("7dcfff")

    lum = _lum

    # Highlight away from the background, so the underside reads as shading
    # in dark themes and in light ones alike.
    away = (1, 1, 1) if lum(bg) < 0.5 else (0, 0, 0)
    belly = col("bright_foreground", "light_foreground")
    if belly is None or abs(lum(belly) - lum(fg)) < 0.04:
        belly = _blend(fg, away, 0.30)
    if abs(lum(belly) - lum(fg)) < 0.04:
        # fg is already pure black or white; shade toward the background.
        belly = _blend(fg, bg, 0.22)

    # Some themes set accent == foreground (kanagawa), which would hide the
    # eye in the middle of the head. Judge on hue as well as brightness, so a
    # vivid blue accent that merely matches the coat's luminance still counts.
    def visible(c):
        if c is None:
            return False
        spread = max(abs(c[i] - fg[i]) for i in range(3))
        return abs(lum(c) - lum(fg)) >= 0.10 or spread >= 0.22

    if not visible(accent):
        for key in ("cyan", "blue", "red", "orange", "magenta", "green"):
            alt = col(key)
            if visible(alt):
                accent = alt
                break
        else:
            accent = _blend(fg, away, 0.55)

    PAL["b"] = fg
    PAL["c"] = belly
    PAL["a"] = _blend(fg, bg, 0.22)
    PAL["d"] = _blend(fg, bg, 0.40)
    PAL["e"] = accent
    FAR = _blend(fg, bg, 0.46)
    HOOF = col("muted", "dark_foreground") or _blend(fg, bg, 0.65)
    FAR_HOOF = _blend(HOOF, bg, 0.45)
    REST_HOOF = _rest_hoof()
    OUTLINE = bg
    BUBBLE_BG = col("dark_background", "background") or bg
    ACCENT_HEX = "#%02x%02x%02x" % tuple(round(c * 255) for c in accent)
    return True


def _theme_label():
    """The theme's name, for --debug only."""
    try:
        with open(THEME_NAME) as fh:
            return fh.read().strip() or "?"
    except OSError:
        return "?"


def theme_stamp():
    """Cheap change-detector for the active theme."""
    try:
        return (os.path.getmtime(THEME_COLORS), os.path.getmtime(THEME_NAME))
    except OSError:
        try:
            return (os.path.getmtime(THEME_COLORS),)
        except OSError:
            return None


# Three gaits, and which one is a matter of speed, the same across mammals:
# a four-beat walk when slow, a two-beat trot at intermediate speeds, a
# gallop -- for a deer, a bound -- when fast. He ambles at about half a
# body length a second, which is a walk.
#
# The walk: each foot lands on its own, in lateral sequence -- near hind,
# near fore, far hind, far fore -- a quarter of the stride apart, and three
# feet are on the ground at almost any moment. One leg per frame is in the
# air here, knee bent, coming forward; the other three are planted: just
# landed at reach, under, and pushing off. No bob; a walk is level. The
# head nods once per foreleg, twice a stride, as a walking quadruped's does.
WALK = [
    dict(d1=0, d2=1, up=1),      # swinging: lifted, coming forward
    dict(d1=1, d2=2, up=0),      # reaching, just landed
    dict(d1=0, d2=0, up=0),      # under
    dict(d1=-1, d2=-2, up=0),    # pushing off
]
WALK_PHASE = dict(nr=0, nf=1, fr=2, ff=3)
WALK_NOD = [0, 1, 0, 1]
# The wag: two swings, the tip on the flank for a beat and off for a beat.
WAG_SECS = 0.6
WAG_BEAT = 0.15
# The trot: two-beat, diagonal pairs in phase -- near hind with far fore --
# and the body rises a row on the pass, the legs lengthening to meet it.
# Not used for the roam now; kept for a faster amble.
TROT = [
    dict(r1=0, r2=-1, f1=1, f2=2),
    dict(r1=0, r2=0, f1=0, f2=0),
    dict(r1=0, r2=1, f1=0, f2=-2),
    dict(r1=0, r2=0, f1=0, f2=0),
]
BOB = [0, -1, 0, -1]


def _leg(out, ax, d1, d2, col, hoof, lift=0, top=18, floor=None, up=0):
    """Upper leg from `top` to row 20, lower leg 21-22, hoof 23, all plus
    `lift`. When the trot bobs the body up a row the upper leg starts a
    row higher to meet it -- the legs straighten under the animal, the
    hooves stay on the ground -- or row 17 empties and the halo fills it
    as a seam. `up` is a foot in the air: the lower leg and hoof rise
    that many rows, the upper stays, so the knee bends. A body that has
    come down over the legs (`floor`) hides their tops; drawing them
    anyway puts four coat-coloured stripes through the belly."""
    for y in range(top, 21):
        for i in range(2):
            if floor is None or y > floor:
                out.append((ax + d1 + i, y + lift, col))
    for y in range(21, 23):
        for i in range(2):
            if floor is None or y > floor:
                out.append((ax + d2 + i, y + lift - up, col))
    for i in range(2):
        out.append((ax + d2 + i, 23 + lift - up, hoof))
# A bound is not a faster trot. The legs pair up front and back and the whole
# body leaves the ground, which is why a startled deer reads as a deer.
BOUND = [
    dict(r1=1, r2=2, f1=-1, f2=-2, lift=-2),   # tucked, airborne
    dict(r1=0, r2=1, f1=0, f2=-1, lift=-1),
    dict(r1=-1, r2=-2, f1=1, f2=2, lift=0),    # reaching, landing
    dict(r1=0, r2=0, f1=0, f2=0, lift=-1),
]


# Rows 0-11 are everything forward of the shoulder: antlers, skull, neck.
# Grazing swings that whole assembly down and out rather than redrawing it,
# which keeps one animal instead of two that only mostly match.
GRAZE_SHIFT = (2, 4)
# Lying down is the same trick the other way about. The body drops by the
# height of its legs less one row, so it sits on a strip of shade along
# the ground line where the folded legs are; the legs themselves are not
# drawn, only two hooves as marks in that strip, one at the rear and one
# midway along the belly. At 24x24 anything more reads as grit, and a knee
# or a hoof ahead of the chest reads as a deer that fell over. What says
# "settled" is the head: pulled back three and down one, so the neck rows
# disappear into the shoulders and the muzzle sits over the chest instead
# of ahead of it. The body itself is left alone -- this is a transition
# from the standing animal, and he has to stay recognisably the same one.
REST_SHIFT = (0, 5)
REST_HEAD = (-2, 7)
# One frame between the two, used going down and getting up, the same
# four-frame trick the bound uses rather than a tween: head already pulled
# back, body two rows down of the five, and the legs bent under it -- hind
# folding forward at the hock, fore folding back at the knee -- with only
# what shows below the body drawn. Without it the change is a teleport,
# and it is the one moment the user is watching, because it is what
# confirms the middle click took.
SETTLE_SHIFT = (0, 2)
SETTLE_HEAD = (-2, 4)
SETTLE_LEGS = dict(r1=0, r2=1, f1=0, f2=-1)
SETTLE_SECS = 0.15


# Cud. A bedded deer chews, and it is the motion that keeps the pose from
# reading as a frozen frame. The lower jaw is one row of the head, ending
# at x=18 on the resting head; a chew is one pixel of chin at 19, ahead
# of it and under the muzzle, and nothing else -- lateral, the way a
# ruminant's jaw moves, never the mouth opening, which would read as
# speech, and never the row itself, whose rear pixel is the neck line on
# the pulled-back head. A second chin position at 20 was tried: it hangs
# from the muzzle tip with a notch in the jaw line and reads as a
# detached pixel. Anything that continues the jaw row is 19.
#
# The real numbers: a whitetail chews a bolus 40-55 times at 78-93 a
# minute, then swallows and brings up the next. What is shown is
# deliberately not that. At 24x24 one pixel on a fixed beat for forty
# seconds is exactly a blinking status light, so each chew gets its own
# interval around the real mean, the bouts are short -- ten seconds or
# so -- and the stillness between them is longer than the chewing.
CHEW_STEP = (0.28, 0.50)      # chin out or in, jittered: 0.56-1.0s a chew
CHEW_BOUT = (8, 14)           # chews per bout
CHEW_PAUSE = (10, 20)         # seconds between bouts
# Dozing. Bedded deer sleep far less than they lie down (Woods), and when
# they do it is brief: "30 seconds to a few minutes of dozing, followed by
# a brief alert period, and then more dozing" (Adams, NDA). The pose does
# not change -- the head stays up -- only the eye: shut, it is a pixel of
# shade where the accent was, an eye that isn't lit. He beds alert first,
# and cud is a waking activity, so eye open and chewing is alert, eye
# closed and still is dozing. The ears never stop either way.
DOZE_FIRST = (30, 120)
DOZE_FOR = (30, 180)
DOZE_ALERT = (15, 60)


def _folded_legs(out):
    for x in range(3, 15):
        out.append((x, 23, FAR))
    for x in (3, 4, 9, 10):
        out.append((x, 23, REST_HOOF))


REST_HOOF = _rest_hoof()


def pixels(frame, blink, pose="stand", ear=0, tail=0, gait=None, chew=0, doze=0):
    """One frame. `gait` is None parked, else "walk", "trot" or "bound".
    `tail` is 1 for the wag, 2 for the flag."""
    out = []
    grazing, resting = pose == "graze", pose == "rest"
    settling = pose == "settle"
    bound, walking = gait == "bound", gait == "walk"
    # Each leg's (d1, d2, up): the walk phases them one by one, the trot
    # and bound pair them, near against far.
    if settling:
        s = SETTLE_LEGS
        legs = dict(nr=(s["r1"], s["r2"], 0), nf=(s["f1"], s["f2"], 0),
                    fr=(s["r1"], s["r2"], 0), ff=(s["f1"], s["f2"], 0))
    elif walking:
        legs = {k: (WALK[(frame - p) % 4]["d1"], WALK[(frame - p) % 4]["d2"],
                    WALK[(frame - p) % 4]["up"]) for k, p in WALK_PHASE.items()}
    else:
        table = BOUND if bound else TROT
        near, far = table[frame], table[(frame + 2) % 4]
        legs = dict(nr=(near["r1"], near["r2"], 0), nf=(near["f1"], near["f2"], 0),
                    fr=(far["r1"], far["r2"], 0), ff=(far["f1"], far["f2"], 0))
    # A bob is a gait thing. Parked, there is none: he is frame 1 all day,
    # and a body a row off its legs was a seam for as long as he stood
    # there. Walking he is level; the head nods instead. Trotting, the
    # body rises on the pass and the legs lengthen to meet it. In a bound
    # the whole animal leaves the ground, so the legs rise with the body;
    # lifting the body alone just severs them. Lying down there is
    # nothing to bob either way.
    lift = BOUND[frame]["lift"] if bound and not (resting or settling) else 0
    bob = 0 if resting or settling else BOB[frame] if gait == "trot" else lift
    nod = WALK_NOD[frame] if walking and pose == "stand" else 0
    top = 18 + (0 if bound else bob)
    floor = 17 + SETTLE_SHIFT[1] if settling else None

    if not resting:
        _leg(out, 6, *legs["fr"][:2], FAR, FAR_HOOF, lift, top, floor, legs["fr"][2])
        _leg(out, 10, *legs["ff"][:2], FAR, FAR_HOOF, lift, top, floor, legs["ff"][2])

    for y, row in enumerate(BODY):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            col = PAL[ch]
            if ch == "e":
                col = FAR if doze else PAL["b"] if blink else col
            dx, dy = 0, 0
            if grazing and y <= 11:
                dx, dy = GRAZE_SHIFT
            elif resting:
                dx, dy = REST_HEAD if y <= 11 else REST_SHIFT
                if chew and y == 9 and x == 20:
                    # The chin, one pixel ahead of the jaw's front end.
                    # Added, not slid: sliding the row also took its rear
                    # pixel, which on the pulled-back head is the throat
                    # at the head/neck junction, and the neck twitched
                    # once a second.
                    out.append((x + dx + 1, y + bob + dy, col))
            elif settling:
                dx, dy = SETTLE_HEAD if y <= 11 else SETTLE_SHIFT
            elif nod and y <= 9:
                dy = nod                       # the walk's head nod: skull only
            # The wag: the tail swings sideways, and in profile what shows
            # is the tip crossing onto the flank. Drawn after the rump.
            if tail == 1 and y == 13 and x == 0:
                continue
            # The head is still lying down; the ear is not. A bedded deer's
            # ears are never lowered and move constantly.
            if ear and not grazing and y == 6 and x == 14:
                out.append((x + dx - 1, y + bob + dy - 1, col))   # ear pricks up and back
            out.append((x + dx, y + bob + dy, col))

    _, tdy = REST_SHIFT if resting else SETTLE_SHIFT if settling else (0, 0)
    if tail == 1:
        out.append((2, 13 + bob + tdy, PAL["c"]))
    # The flag is the alarm signal a deer gives, and the bound is the only
    # place he gives it. Add to the tail, don't move it, or the rump grows
    # a gap.
    elif tail == 2 and not grazing:
        for x in range(2):
            out.append((x, 10 + bob + tdy, PAL["c"]))
            out.append((x, 11 + bob + tdy, PAL["c"]))

    if resting:
        _folded_legs(out)
    else:
        _leg(out, 3, *legs["nr"][:2], PAL["b"], HOOF, lift, top, floor, legs["nr"][2])
        _leg(out, 13, *legs["nf"][:2], PAL["b"], HOOF, lift, top, floor, legs["nf"][2])
    return out


# ------------------------------------------------------------- knowledge ----
TERM = ("foot", "alacritty", "ghostty", "kitty", "wezterm")
NVIM = ("nvim", "neovim", "lazyvim")
WEB = ("chromium", "chrome", "brave", "firefox", "zen")
# Quattro gives a launched agent its own window class.
AGENT = TERM + ("org.omarchy.agent", "opencode", "claude", "codex", "crush")

# Every entry below was checked against the installed Omarchy 4 (Quattro)
# release — the scripts, Lua and menu under /usr/share/omarchy — not the
# manual, which lists bindings the release doesn't have (Super + Q).
# tools/README.md says where to look, per topic.
KNOWLEDGE = [
    # ---------------------------------------------------------- windows ----
    ("windows", None, "Super + K", "Every keybinding at once. Alt + K for tmux, Ctrl + K for Herdr. Nobody memorises all of them."),
    ("windows", None, "Super + Space", "The Omarchy menu. Almost everything starts here, which is the point of it."),
    ("windows", None, "Super + Alt + Space", "The apps menu, for when you already know what you want."),
    ("windows", None, "Super + Escape", "Lock, suspend, hibernate, log out, reboot, shut down. Screensaver, if you want a show."),
    ("windows", None, "Super + Ctrl + L", "Lock the screen. The idle timer that does it for you is in shell.json."),
    ("windows", None, "Super + W", "Close the window. No confirmation dialog. There was never going to be one."),
    ("windows", None, "Ctrl + Alt + Delete", "Closes every window. The nuclear option, kept where you can reach it."),
    ("windows", None, "Super + T", "Toggle a window between tiling and floating. Floating is a temporary condition."),
    ("windows", None, "Super + J", "Toggle the split between horizontal and vertical."),
    ("windows", None, "Super + F", "Full screen. Super + Alt + F goes full width, which is the one you actually want."),
    ("windows", None, "Super + Ctrl + F", "Full screen inside the window's own frame."),
    ("windows", None, "Super + L", "Toggle between the dwindle and scrolling layouts."),
    ("windows", None, "Super + P", "Pseudo window style. The window gets its natural size instead of being stretched thin."),
    ("windows", None, "Super + O", "Pop a window out sticky and floating. It follows you everywhere, like me."),
    ("windows", None, "Super + G", "Group windows into tabs. Super + Alt + G lets one back out again."),
    ("windows", None, "Super + Alt + Tab", "Cycle a group. Super + Alt + 1/2/3/4/5 jumps to one."),
    ("windows", None, "Super + Ctrl + Left/Right", "Move between the windows inside a tiling group."),
    ("windows", None, "Super + Arrow", "Move focus. Super + Shift + Arrow swaps the two windows."),
    ("windows", None, "Super + Minus", "Expand window left. Super + Equal shrinks it."),
    ("windows", None, "Super + Alt + Minus/Equal", "The same resizing in smaller steps. Ctrl for bigger ones."),
    ("windows", None, "Super + Alt + Home", "Save this window's width. Super + Home restores it."),
    ("windows", None, "Super + Left Mouse", "Drag the window around. Super + Right Mouse resizes it."),
    ("windows", None, "Super + Ctrl + Z", "Zoom into the screen, repeatedly. Ctrl + Alt + Z admits defeat and zooms out."),
    ("windows", None, "Super + /", "Step through monitor scaling. Super + Alt + / steps back."),
    ("windows", None, "Alt + Tab", "Cycle windows here. Ctrl + Alt + Tab cycles monitors. Old habits, honoured."),
    ("windows", None, "Super + Backspace", "Toggle transparency. Looks incredible, reads terribly. Use sparingly."),
    ("windows", None, "Super + Shift + Backspace", "Toggle window gaps. Gaps are taste, not function. Have taste anyway."),
    ("windows", None, "Super + Ctrl + Backspace", "Toggle single-window square aspect. A lone window shouldn't span an ultrawide."),

    # ------------------------------------------------------- workspaces ----
    ("workspaces", None, "Super + 1/2/3/4", "Jump to a workspace. Add Shift to bring the window. You will use four of the ten."),
    ("workspaces", None, "Super + Shift + Alt + 1/2/3/4", "Move a window to a workspace without following it."),
    ("workspaces", None, "Super + Tab", "Next workspace. Shift for previous, Ctrl for the former one."),
    ("workspaces", None, "Super + S", "The scratchpad. Super + Alt + S throws a window in. Where things go to be forgotten."),
    ("workspaces", None, "Super + Alt + S", "Sends the window to the scratchpad without following it. Super + S brings it back into view."),
    ("workspaces", None, "Super + Scroll Wheel", "Scroll through workspaces. The one concession to the mouse in this whole place."),
    ("workspaces", None, "Super + Shift + Alt + Arrows", "Move workspaces to the monitor in that direction."),

    # ----------------------------------------------------------- panels ----
    ("panels", None, "Super + Ctrl + W", "Wi-Fi panel. A audio, B bluetooth, D display, P power."),
    ("panels", None, "Super + Ctrl + Alt + D", "The calendar panel. Clicking the clock opens it too."),
    ("panels", None, "Super + Ctrl + 1-9", "Toggle a bar panel by position, counting from the right section."),
    ("panels", None, "Super + Ctrl + T", "Activity — btop. It floats. Super + T tiles it, because everything should tile."),
    ("panels", None, "Super + Ctrl + Q", "Calculator. Super + Ctrl + E is emoji. Both faster than reaching for a phone."),
    ("panels", None, "Super + Ctrl + H", "Hardware menu. Super + Ctrl + O is the toggle menu."),
    ("panels", None, "Super + Ctrl + S", "Share a file to anything else on your network. No account, no upload, no cloud."),
    ("panels", None, "Super + Ctrl + .", "Transcode media without learning a single ffmpeg flag."),

    # ---------------------------------------------------------- capture ----
    ("capture", None, "Print Screen", "Screenshot. Alt + Print Screen records; press it again to stop. That's the whole thing."),
    ("capture", None, "Super + Print Screen", "Colour picker. The value goes to the clipboard and nowhere else."),
    ("capture", None, "Super + Ctrl + Print Screen", "OCR the screen to the clipboard. Text out of a picture, no subscription required."),
    ("capture", None, "Super + Ctrl + C", "Capture menu, for keyboards with no Print Screen key."),
    ("capture", None, "Super + Alt + [", "Shrinks the webcam overlay while recording. ] grows it."),
    ("capture", None, "Super + Ctrl + X", "Start and stop dictation. F9 is push to talk."),
    ("browser", WEB, "Alt + Shift + L", "Copy the current URL from a web app or Chromium."),
    ("browser", WEB, "Alt + Shift + D", "Download the video on this page to ~/Videos."),

    # -------------------------------------------------------- clipboard ----
    ("clipboard", None, "Super + C", "Copy. Super + V pastes. They work in the terminal too, which is rarer than you'd think."),
    ("clipboard", None, "Super + X", "Cut — the one that doesn't work in the terminal."),
    ("clipboard", None, "Super + Ctrl + V", "Clipboard history, images included. It remembers more than you do."),

    # ---------------------------------------------------- notifications ----
    ("notifications", None, "Super + ,", "Dismiss the latest notification. Shift dismisses all of them."),
    ("notifications", None, "Super + Alt + ,", "Invoke the most recent notification. No hunting for a toast that went away."),
    ("notifications", None, "Super + Ctrl + ,", "Silence notifications. Super + Shift + Alt + , shows what you ignored."),

    # ------------------------------------------------------------ style ----
    ("style", None, "Super + Ctrl + Shift + Space", "Pick a theme. Super + Ctrl + Space picks the background. Beauty motivates, not decorates."),
    ("style", None, "Super + Shift + Space", "Toggle the top bar. Nothing up there was ever that urgent."),
    ("style", None, "~/.config/omarchy/backgrounds", "Extras go in the subfolder named for the theme, like /nord."),
    ("style", None, "A theme", "Restyles the desktop, terminal, Neovim, btop, Chromium and the shell. All of it, at once."),
    ("style", None, "Obsidian", "Follows the theme too — pick Omarchy once in Appearance > Themes and it stays current."),

    # ---------------------------------------------------------- toggles ----
    ("toggles", None, "Super + Ctrl + N", "Nightlight. It is later than you think."),
    ("toggles", None, "Super + Ctrl + I", "Stay awake: no idle lock, no screensaver, and no confirmation. Press it again to idle."),
    ("toggles", None, "Super + Ctrl + Delete", "Laptop display on and off. Add Alt to mirror it."),
    ("toggles", None, "Shift + Mute", "Next audio output. Shift + Play switches media source."),
    ("toggles", None, "Alt + Play", "Next track. Alt + Shift + Play goes back."),
    ("toggles", None, "Alt + Brightness Up/Down", "One percent at a time, for the perfectionists. Shift jumps to the extremes."),

    # -------------------------------------------------------- reminders ----
    ("reminders", None, "Super + Ctrl + R", "Set a reminder. Ctrl + Alt + R sees all, Ctrl + Shift + R clears."),
    ("reminders", None, "Super + Ctrl + Alt + T", "Time as a notification. B is battery. W toggles the weather panel."),

    # ------------------------------------------------------------- apps ----
    ("apps", None, "Super + Return", "Terminal. Super + Alt + Return opens it in tmux, which is where you'll end up anyway."),
    ("apps", None, "Super + Ctrl + Return", "Herdr, the agent manager, still running from last time."),
    ("apps", None, "Super + Shift + Return", "Browser. Super + Shift + Alt + B for private."),
    ("apps", None, "Super + Shift + F", "File manager. Add Alt to open it in your terminal's directory."),
    ("apps", None, "Super + Shift + N", "Your editor — Neovim by default. Super + Shift + O opens Obsidian. Btw."),
    ("apps", None, "Super + Shift + D", "Lazydocker. Super + Shift + M is Spotify."),
    ("apps", None, "Super + Shift + Alt + M", "Cliamp. A terminal music player built like Winamp 2, for no reason but joy."),
    ("apps", None, "Super + Shift + /", "1Password. Super + Shift + G is Signal."),
    ("apps", None, "Super + Shift + W", "Omawrite. A blank page and nothing else. No ribbon, no assistant, no upsell."),
    ("apps", None, "Super + Shift + A", "ChatGPT. Super + Shift + Alt + A is Grok."),
    ("apps", None, "Disk Usage", "Walks the filesystem biggest first and deletes in place. Always node_modules."),
    ("apps", None, "About", "Fastfetch in a frame. Kernel, uptime, theme and the pleasure of being asked."),
    ("apps", None, "Omacut", "Trims a video's length. Built on ffmpeg, minus the ffmpeg."),

    # ------------------------------------------------------------ setup ----
    ("setup", None, "Install > Editor", "VSCode, Cursor, Zed, Sublime Text, Helix, Vim and Emacs. Neovim's already here."),
    ("setup", None, "Install > Package", "Anything in Arch. Install > AUR when it isn't in the main repos."),
    ("setup", None, "Install > TUI", "Give a terminal program a name and an icon and it's an app. That's all an app ever was."),
    ("setup", None, "Install > Web App", "A URL with a name and an icon. Most desktop apps are this wearing a costume."),
    ("setup", None, "Setup > Defaults", "Editor, terminal, browser, agent. Chosen once, obeyed everywhere. Defaults are a kindness."),
    ("setup", None, "Setup > Input", "Keyboard layout, mouse, trackpad — or ~/.config/hypr/input.lua."),
    ("setup", None, "Setup > Direct Boot", "Skips the Limine menu and boots straight to the decryption screen."),
    ("setup", None, "Dual boot", "Quattro installs into free space beside Windows, LUKS and all."),

    # -------------------------------------------------------------- cli ----
    ("cli", TERM, "omarchy", "The command centre. Run it bare to see every group. It will not judge you for looking."),
    ("cli", TERM, "omarchy update", "Packages, snapshot and migrations in one move. The snapshot is the part that matters."),
    ("cli", TERM, "omarchy theme list", "Then omarchy theme set <name>. omarchy font list does fonts."),
    ("cli", TERM, "omarchy commands --all", "Every subcommand there is. --json if something else is reading."),
    ("cli", TERM, "omarchy-debug", "One log with all a helper needs. --print to read it. Hyphenated; the spaced form fails."),
    ("cli", TERM, "omarchy-restart-xcompose", "Run it after editing ~/.XCompose or nothing changes."),

    # --------------------------------------------------- updates/rescue ----
    ("updates", None, "pacman -Syu", "Omarchy stops you. You'd skip the snapshot, the migrations and the configs, all at once."),
    ("updates", None, "Snapshots", "Taken before every update. Roll back from the Limine menu. Courage, bottled."),
    ("updates", TERM, "omarchy-snapshot create", "Take one yourself before doing something brave. Bravery is cheaper with a rollback."),
    ("updates", TERM, "omarchy-snapshot restore", "Restores the root filesystem. /home and ~/.config are left alone."),
    ("updates", None, "Limine", "Snapshots need it. Default since 2.0, absent on GRUB or systemd-boot."),
    ("updates", TERM, "omarchy-reinstall", "Last resort. Default configs and packages back. No shame in it."),
    ("updates", None, "Update > Config", "Reverts the configs you've made a mess of, without the full reinstall."),
    ("updates", None, "#omarchy-help", "The Discord, via omarchy.org/discord. Bring your omarchy-debug output, not vibes."),

    # ------------------------------------------------------------ fixes ----
    ("fixes", None, "Update > Hardware", "Reload Wi-Fi, Bluetooth, Audio or Trackpad before you reboot."),
    ("fixes", None, "GDK_SCALE", "Apps too big? Omarchy assumes a 2x display. It's a line in monitors.lua, not a crisis."),
    ("fixes", None, "CapsLock", "It isn't broken. It's the compose key now. Arguably its first useful job."),
    ("fixes", None, "Ctrl + Minus", "Shrinks Spotify's oversized UI. Ctrl + Plus goes the other way."),
    ("fixes", TERM, "omarchy audio tuning status", "Tells you if a laptop speaker correction is on. Add off to stop it."),
    ("fixes", None, "Ctrl + Alt + F2", "Locked out by a bad password? A TTY, then faillock --reset --user."),

    # ------------------------------------------------------------ paths ----
    ("config", None, "~/.config", "Your files, for your changes. This half of the system is yours and always will be."),
    ("config", None, "/usr/share/omarchy", "Omarchy's own files. Override in ~/.config. Look, don't touch."),
    ("config", None, "~/.config/hypr/bindings.lua", "Your keybindings. o.bind adds one; hl.unbind a default first if you're replacing it."),
    ("config", None, "~/.config/hypr/monitors.lua", "Monitors, resolution and position. looknfeel.lua does gaps and borders."),
    ("config", None, "~/.config/hypr/autostart.lua", "o.launch_on_start(\"thing\") starts it with your session."),
    ("config", None, "~/.config/omarchy/shell.json", "Bar position, widgets, screensaver and idle timings."),
    ("config", None, "~/.config/foot/foot.ini", "Your terminal's config, foot being the default."),
    ("config", None, "~/.bashrc", "Your aliases, functions and exports. Never overwritten by an update. Ever."),
    ("config", None, "~/.config/omarchy/hooks", "Scripts in <event>.d/ run on post-boot, post-update, theme-set."),
    ("config", None, "omarchy-menu.jsonc", "In ~/.config/omarchy/extensions — adds your own rows to the menu."),
    ("config", TERM, "omarchy menu keybindings --print", "Prints every current binding with its description."),
    ("config", None, "~/.config/omarchy/themed", "Drop a name.tpl there and it's regenerated on every theme switch."),
    ("config", None, "~/.XCompose", "Your quick emoji and name/email autocompletes."),

    # ------------------------------------------------------ shell tools ----
    ("shell", TERM, "ff", "fzf with a preview. Fuzzy find any file below you. Faster than remembering where it is."),
    ("shell", TERM, "Ctrl + R", "fzf through your command history."),
    ("shell", TERM, "cd oma", "Zoxide remembers where you've been. Half a name will do. Type less."),
    ("shell", TERM, "rg <pattern> <path>", "ripgrep. Searches inside the files, not just their names."),
    ("shell", TERM, "man zoxide", "The full story, when the alias stops being enough. man fzf too."),

    # -------------------------------------------------- shell functions ----
    ("shell", TERM, "compress [file/dir]", "A tar.gz without the flag archaeology. decompress unpacks it."),
    ("shell", TERM, "iso2sd [image.iso]", "A bootable drive, with the target picked interactively. There's no dd flag to get wrong."),
    ("shell", TERM, "format-drive", "Run it bare to list drives first. One exFAT partition. Read that sentence twice."),
    ("shell", TERM, "ga [branch]", "A worktree and branch beside the repo, and jumps you in. gd removes it."),
    ("shell", TERM, "rsw [source] [destination]", "Rsyncs on every change, remote host and all. lsw lists, dsw stops."),
    ("shell", TERM, "fip nyc-dev 3000", "Forwards a remote port to localhost over SSH. dip drops it, lip lists."),
    ("shell", TERM, "ssh", "Wrapped — it cleans up and reconnects when the link drops. Ctrl + C still means stop."),

    # ------------------------------------------------------------- tmux ----
    ("tmux", TERM, "Ctrl + Space", "The prefix. Prefix + v splits beside, prefix + h below."),
    ("tmux", TERM, "Alt + Enter", "Splits below with no prefix. Alt + Escape kills a pane."),
    ("tmux", TERM, "Ctrl + Alt + Arrows", "Move between panes. Add Shift to resize."),
    ("tmux", TERM, "Prefix + z", "Zoom a pane full screen. Same keys back out."),
    ("tmux", TERM, "Prefix + c", "New window. k kills, r renames, Alt + 1-9 jumps."),
    ("tmux", TERM, "Prefix + d", "Detach. It all keeps running. Prefix + s lists what you left behind."),
    ("tmux", TERM, "Prefix + [", "Copy mode. v begins the selection, y takes it."),
    ("tmux", TERM, "Prefix + ?", "Every tmux binding. Prefix + q reloads the config."),
    ("tmux", TERM, "tdl c", "Editor, agent and terminal. tdl c cx runs two agents at once."),
    ("tmux", TERM, "tds", "A square: editor, a live diff watcher, terminal and opencode."),
    ("tmux", TERM, "tdlm", "A tdl window for every subdirectory. Alt + 1/2/3 walks them."),
    ("tmux", TERM, "tsl [count] [command]", "A grid of panes all running the same thing. Built for agents, works for anything."),
    ("herdr", TERM, "Super + Ctrl + Return", "Herdr. Same Ctrl + Space prefix, and it survives detaching."),
    ("herdr", TERM, "hdl", "The tmux layouts again, for Herdr. hds, hdlm and hsl too."),

    # --------------------------------------------------------- terminal ----
    ("terminal", ("foot",), "Foot", "The default terminal. No native tabs or splits, by design — that's tmux's job."),
    ("terminal", None, "Install > Terminal", "Foot, Alacritty, Ghostty or Kitty. The last three have native tabs and splits."),
    ("terminal", None, "Setup > Defaults > Terminal", "Switches between the ones you've installed. Super + Return follows."),

    # ----------------------------------------------------------- agents ----
    ("agents", AGENT, "Super + Shift + Ctrl + A", "Launches your default agent in its own window, starting in ~/Work."),
    ("agents", AGENT, "omarchy default agent", "Thirteen are pre-wired. Or Setup > Defaults > Agent in the menu."),
    ("agents", AGENT, "a", "The default agent, inline. c opencode, cx Claude Code, cy Codex. Two letters, no ceremony."),
    ("agents", AGENT, "omarchy agent prompt", "Sends it straight into a task, unattended. Mean what you type."),
    ("agents", AGENT, "omarchy-mise-install", "Wraps any other CLI as a lazy-loaded stub, like the agents are."),
    ("agents", AGENT, "The agents icon", "Appears once you've used one. Left click for spend, right to launch."),
    ("agents", None, "A crash notification", "Click it and your agent is handed the core dump to explain."),
    ("agents", AGENT, "Agent skills", "Omarchy ships two — omarchy and diagnose-crash — symlinked into each harness."),
    ("agents", AGENT, "Agent theming", "Claude Code, Pi, OpenCode and Hermes follow your Omarchy theme."),
    ("agents", AGENT, "LM Studio", "That or Ollama, for running open-weight models on this machine. The model lives on your disk."),

    # ---------------------------------------------------------- ghostty ----
    ("ghostty", ("ghostty",), "Ctrl + Shift + E", "New split below. Ctrl + Shift + O splits beside."),
    ("ghostty", ("ghostty",), "Ctrl + Shift + T", "New tab. Ctrl + Shift + Arrows moves between them."),
    ("ghostty", ("ghostty",), "Super + Ctrl + Shift + Arrows", "Resize a split by 10 lines. Add Alt for 100."),
    ("ghostty", ("ghostty",), "Shift + Pg Up/Down", "Scroll the history. Ctrl + Left mouse opens a link."),

    # ----------------------------------------------------------- neovim ----
    ("neovim", NVIM, "Space", "The leader. Press it and wait — every option explains itself. Start here when lost."),
    ("neovim", NVIM, "Space Space", "Fuzzy find a file. Space S G greps their contents with a preview."),
    ("neovim", NVIM, "Space E", "Toggle the file tree. Ctrl + W W hops between it and the editor."),
    ("neovim", NVIM, "Space G G", "lazygit, floating, from the current directory."),
    ("neovim", NVIM, "Shift + H", "Left through the open tabs. Shift + L right, Space B D closes."),
    ("neovim", NVIM, "Space B O", "Close every tab but this one. Space U W toggles soft wrap."),
    ("neovim", NVIM, "?", "In the file tree, lists every command it has."),
    ("neovim", NVIM, "Ctrl + Left/Right Arrow", "Narrows or widens the focused window, two columns a press. The sidebar, or any split."),
    ("neovim", TERM, "n", "The alias for nvim. n myfile.txt opens just that one."),
    ("neovim", TERM, "sudoedit", "Edit root-owned files with all your plugins still loaded."),
    ("neovim", NVIM, "lazyvim.org/keymaps", "Everything LazyVim binds, on one page. Bookmark it, you'll be back."),

    # -------------------------------------------------------------- git ----
    ("git", ("lazygit",), "Tab", "Moves between lazygit's panes. Space stages, c commits, ? lists all."),
    ("git", TERM, "gh auth login", "Then gh repo clone org/repo reaches your private repositories."),
    ("git", TERM, "ghui", "Pull requests in a TUI. Installs itself the first time. No tab required."),

    # ----------------------------------------------------------- docker ----
    ("docker", ("lazydocker", "docker"), "s", "Stops a container in lazydocker. r restarts, ? lists everything."),
    ("docker", ("lazydocker", "docker"), "Install > Development > Docker DB", "The common databases, configured for local work."),

    # ------------------------------------------------------------- btop ----
    ("btop", ("btop",), "Super + T", "Activity opens floating. This tiles it like anything else."),

    # ----------------------------------------------------- file manager ----
    ("files", ("nautilus", "org.gnome.nautilus", "files"), "Ctrl + L", "Go to a path. Backspace goes back one folder."),
    ("files", ("nautilus", "org.gnome.nautilus", "files"), "Space", "Preview the file; arrows walk through the rest."),

    # ---------------------------------------------------------- browser ----
    ("browser", WEB, "Install > Web App", "Turns a URL into a launcher. Log in with a real browser first."),

    # ---------------------------------------------------------- grammar ----
    # The shape of the map, not its contents. Fractions are from the
    # installed 4.0.4 tree (tools/stock-binds.lua stock force, 228 binds):
    # Super+Shift launches on 15 of 15 letters (17 launchers, counting Return
    # and Slash) and moves the window on 14 of 15 focus keys; Super alone
    # works the window or workspace on 32 of 42;
    # Super+Ctrl is a panel, menu or toggle on 28 of 42; of the 62 pairs that
    # differ only by Alt, 57 are a variant or sibling and 4 of the 5 that
    # aren't are Super+Ctrl+Alt. Not bindings, so not in HYPR_TOPICS: a rule
    # about the map must not be withheld because a key it mentions was rebound.
    ("grammar", None, "Super + Shift + a letter", "Launches an app, every letter. On a number or arrow, Shift moves the window instead of you."),
    ("grammar", None, "Super alone", "Three in four work the window or workspace in front of you. Close, float, focus, full screen."),
    ("grammar", None, "Super + Ctrl", "Two in three are a panel, a menu or a toggle. Wi-Fi, Bluetooth, audio, nightlight, lock."),
    ("grammar", None, "Alt", "Usually the same key's variant: private browser, file manager here, a smaller resize. Try it."),
    ("grammar", None, "Super + Ctrl + Alt", "The exception to Alt. The letter picks a new word: B battery, T time, W weather, D calendar."),

    # ------------------------------------------------------------ emoji ----
    ("emoji", None, "CapsLock M S", "A smile. M H a heart, M Y a thumbs up."),
    ("emoji", None, "CapsLock Space Space", "An em dash. Space N your name, Space E your email. Small mercies, daily."),
]

# The first hour. While any of these is unseen, ambient tips come from here
# and nowhere else: a new user needs the menu and the keybinding list before
# they need omarchy-mise-install, and the flat draw made those equally likely.
# Context still wins — focus Neovim and you get the Neovim tip — because a
# tip about the window in front of you beats a syllabus. Ids, not tuples, so
# a tip can be edited without touching this.
FUNDAMENTAL = frozenset([
    "windows:Super + K",                    # every keybinding; makes the rest discoverable
    "windows:Super + Space",                # the Omarchy menu
    "windows:Super + Alt + Space",          # the apps menu
    "apps:Super + Return",                  # terminal
    "apps:Super + Shift + Return",          # browser
    "windows:Super + W",                    # close the window
    "workspaces:Super + 1/2/3/4",           # workspaces, Shift to bring the window
    "windows:Super + Arrow",                # focus, Shift to swap
    "windows:Super + T",                    # tiling vs floating
    "windows:Super + F",                    # full screen, full width
    "windows:Super + Escape",               # lock, suspend, shut down: how to leave
    "panels:Super + Ctrl + W",              # Wi-Fi, and the other panels
    "capture:Print Screen",                 # screenshot, recording
    "clipboard:Super + C",                  # copy and paste, in the terminal too
    "style:Super + Ctrl + Shift + Space",   # the theme picker: the payoff
    "cli:omarchy update",                   # the right way to update
    "grammar:Super + Shift + a letter",     # 17 launchers and 14 window-moves in one sentence
    "grammar:Alt",                          # 57 variants in another
])

CHATTER = [
    # Opinions about software, never about the person reading them. That
    # distinction is the whole reason Clippy was resented and this isn't:
    # it was status-lowering toward the user. Punch at bloat instead.
    "Every program has a tiny essence that justifies it. The rest is someone's résumé.",
    "Your entire desktop is config files and good taste. That is the whole trick.",
    "Somewhere a team of forty is shipping a settings panel. You have a text file.",
    "Zero bloat here. Nothing ships that nobody uses. A bolder promise than it sounds.",
    "Somewhere a man is paying monthly to edit text. You are not that man.",
    "Nothing here phones home. I checked. I'm the only one watching, and I'm facing the wall.",
    "The cloud is someone else's computer.",
    "This desktop boots before most web apps finish showing you their loading spinner.",
    "The whole shell fits in less memory than one browser tab. Sit with that.",
    "Better a kick-ass half than a half-assed whole. Ship the half. Ship it tonight.",
    "Planning is guessing with extra steps. You've been planning that thing for a while.",
    "Nobody is an overnight success. They were all nobody for about ten years first.",
    "Workaholics don't finish more. They just sleep less and have more opinions.",
    "It was never about eight hours in a chair. It's about whether they were any good.",
    "A beautiful system is a motivating system. That isn't decoration. It's the argument.",
    "You can spot bad code before you read a line of it. The indentation confesses.",
    "Good code reads like good writing. Fewer words. Then take out two more.",
    "Neovim. Btw.",
    "Yes, you edit config files by hand here. That's not a bug report. That's the point.",
    "Omakase: the chef chooses. You may disagree, but not before you've tried it.",
    "Every keybinding you learn is one you keep. Not true of most things you learn.",
    "An hour of reading the manual saves a week of wondering.",
    "An agent can type it. Taste is still yours. Nobody has automated taste.",
    "My ancestor asked if you were writing a letter. I will never ask you anything.",
    "The paperclip was hated for interrupting, not for being a paperclip. I took notes.",
    "I could tell you what Super + K does. You'd rather find out. I respect that.",
    "Two hundred-odd bindings on this machine. You use eleven. Everyone uses eleven.",
    "That window has been floating for an hour. I'm not going to say anything.",
    "I reread the manual. Still no chapter on deer.",
    "It's dark, everything tiles and nothing is asking me to rate my experience.",
    "Grazing.",
]

# A handful that only make sense at the hour they fire. Cheap, and it makes
# him feel like he lives here rather than running on a timer.
LATE = [
    "Go to bed. The window manager will still be tiling in the morning.",
    "Nothing good gets committed after this hour. Ship it tomorrow.",
    "You've stopped reading the tips. I've stopped believing you're awake.",
    "Deer are crepuscular. You appear to be nocturnal. One of us is doing it wrong.",
]

POKES = [
    "Yes?",
    "Careful. I startle.",
    "Hm.",
    "I was watching the workspaces. They're fine.",
    "Right click me if you want something useful.",
    "I'm not a button.",
    "Poke a paperclip and it offers you a letter template. You got me instead.",
]


def tip_id(tip):
    return "%s:%s" % (tip[0], tip[2])


def load_user_tips():
    try:
        with open(USER_TIPS) as fh:
            lines = [l.strip() for l in fh if l.strip() and not l.startswith("#")]
    except OSError:
        return
    for line in lines:
        if "|" in line:
            keys, text = line.split("|", 1)
            KNOWLEDGE.append(("yours", None, keys.strip(), text.strip()))
        else:
            CHATTER.append(line)


# ---------------------------------------------------------- own binds ----
# ~/.config/hypr/bindings.lua is, by Omarchy's own convention, the user's file:
# the shipped defaults live under /usr/share and the template says to add or
# replace bindings here. So every o.bind in it with a description is a tip
# the user wrote themselves, and it needs no comparison against stock.
_OWN_CALL = re.compile(
    r'o\.bind(?:_toggle)?\(\s*"([^"\n]+)"\s*,\s*"([^"\n]*)"', re.S)


def _own_key(keys):
    """(mods, KEY) the way the verifier normalises, or None if it isn't a
    plain key string. Built keys like 'SUPER + ' .. key never match the
    regex, so they are already gone by here."""
    parts = [p.strip() for p in keys.split("+")]
    mods = frozenset(p.upper() for p in parts if p.upper() in MODBITS)
    rest = [p for p in parts if p.upper() not in MODBITS]
    if len(rest) != 1 or not rest[0]:
        return None
    key = rest[0]
    if key.startswith("code:"):
        key = KEYCODES.get(key[5:], key)
    elif not key.startswith(("XF86", "mouse", "switch")):
        key = key.upper()
    return mods, key


def _own_label(keys):
    """'SUPER + SHIFT + K' -> 'Super + Shift + K', the corpus's spelling."""
    out = []
    for p in (p.strip() for p in keys.split("+")):
        if p.upper() in MODBITS:
            out.append(p.capitalize())
        elif p.startswith("code:"):
            out.append(KEYCODES.get(p[5:], p))
        elif p.isupper() and len(p) > 1:
            out.append(p.capitalize())
        else:
            out.append(p)
    return " + ".join(out)


def own_bind_tips(path=OWN_BINDS, knowledge=None):
    """(tips, replaced) for the user's own bindings, in file order.

    A key in this file is one the user bound, so their description is the
    truth about it. When a curated tip has that key as its *headline*, the
    curated tip is the one that is wrong now: it goes in `replaced`, keyed
    by tip id, and the user's tip takes its place. A curated tip that only
    mentions the key in passing is left alone — too likely to lose something
    useful over a reference. Capped at OWN_CAP. Any failure to read or
    parse means no tips and no replacements."""
    knowledge = KNOWLEDGE if knowledge is None else knowledge
    try:
        with open(path) as fh:
            src = "".join(l for l in fh if not l.lstrip().startswith("--"))
    except (OSError, UnicodeDecodeError):
        return [], {}
    headline = {}                   # normalised key -> curated tip
    for t in knowledge:
        parsed = parse_keys(t[2])
        if parsed:
            for k in parsed[1]:
                headline.setdefault((parsed[0], k), t)
    taken = {tip_id(t) for t in knowledge}
    tips, replaced = {}, {}
    for keys, desc in _OWN_CALL.findall(src):
        desc = desc.strip()
        norm = _own_key(keys)
        if not desc or norm is None:
            continue
        tip = ("yours", None, _own_label(keys), desc)
        if tip_id(tip) in taken:
            continue
        tips[norm] = tip            # a later bind of the same key wins
        if norm in headline:
            replaced[tip_id(headline[norm])] = tip
    tips = list(tips.values())[:OWN_CAP]
    kept = {tip_id(t) for t in tips}
    replaced = {k: v for k, v in replaced.items() if tip_id(v) in kept}
    return tips, replaced


# Curated tips whose headline key the user rebound in bindings.lua. Folded
# into `suppressed` on every refresh, so they stay out however the live
# verifier's own set changes.
rebound = {}                    # curated tip id -> reason

# Tips that are useless without a package: the key launches it, the tip is
# about using it, or the command named is that program. A passing mention
# does not count — the Signal in the 1Password tip, the Spotify in the
# lazydocker one — and neither does anything on the base list nobody removes
# (tmux, foot, fzf: Ctrl + R still searches history without fzf, it is just
# less good). Names are what Omarchy's own installers use.
NEEDS = {
    "ghostty": ["ghostty:Ctrl + Shift + E", "ghostty:Ctrl + Shift + T",
                "ghostty:Super + Ctrl + Shift + Arrows", "ghostty:Shift + Pg Up/Down"],
    "1password": ["apps:Super + Shift + /"],
    "lazydocker": ["apps:Super + Shift + D", "docker:s"],
    "cliamp": ["apps:Super + Shift + Alt + M"],
    "omawrite": ["apps:Super + Shift + W"],
    "obsidian": ["style:Obsidian"],
    "spotify": ["fixes:Ctrl + Minus"],
    "omacut": ["apps:Omacut"],
    "dua-cli": ["apps:Disk Usage"],
    "voxtype-bin": ["capture:Super + Ctrl + X"],
    "herdr": ["herdr:Super + Ctrl + Return", "herdr:hdl", "apps:Super + Ctrl + Return"],
    "lazygit": ["git:Tab", "neovim:Space G G"],
    "tesseract": ["capture:Super + Ctrl + Print Screen"],
}
absent = {}                     # tip id -> reason, from one pacman query


def installed_packages():
    """Names from `pacman -Qq`, or None when that can't be known. None
    means suppress nothing: a tip about software that might be missing
    beats withholding one about software that is there."""
    try:
        r = subprocess.run(["pacman", "-Qq"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return set(r.stdout.split())


def missing_package_tips(packages, needs=NEEDS):
    """{tip id: reason} for every tip whose package is not in `packages`."""
    if packages is None:
        return {}
    return {tid: "%s: needs %s, not installed" % (tid.split(":", 1)[1], pkg)
            for pkg, tids in needs.items() if pkg not in packages for tid in tids}


def load_packages():
    packages = installed_packages()
    if packages is None:
        debug("packages: pacman unavailable, suppressing nothing")
        return
    absent.update(missing_package_tips(packages))
    for tid, why in sorted(absent.items()):
        debug("packages: withholding %s (%s)", tid, why)
    debug("packages: %d installed, %d tips withheld", len(packages), len(absent))
    suppressed.update(absent)


def load_own_binds():
    tips, replaced = own_bind_tips()
    by_id = {tip_id(t): t for t in KNOWLEDGE}
    for old_id, new in replaced.items():
        old = by_id[old_id]
        rebound[old_id] = "%s: rebound in bindings.lua, now %r" % (old[2], new[3])
        debug("own binds: replaced %s (%r) with %r — key is rebound in %s",
              old_id, old[3], new[3], OWN_BINDS)
    KNOWLEDGE.extend(tips)
    suppressed.update(rebound)
    debug("own binds: %d tips from %s, %d curated replaced",
          len(tips), OWN_BINDS, len(replaced))


def load_seen():
    return _load_set(SEEN)


def load_known():
    """Tips the user has explicitly said they already know.

    Swartz's etiquette finding — an assistant that keeps offering help you
    have already declined is the single most resented thing Clippy did, and
    it is what made it feel like it was talking down to experts. Acknowledged
    tips are gone for good.
    """
    return _load_set(KNOWN)


def _load_set(path):
    try:
        with open(path) as fh:
            return set(json.load(fh))
    except (OSError, ValueError):
        return set()


def save_json(path, data):
    """Whole file or no file. The JSON goes to a sibling temp file and is
    renamed into place, because state.json is rewritten every few minutes
    and a crash mid-write would otherwise leave a truncated file that loads
    as {} — his spot, the intro flag and every retired tip gone without a
    word. A stale temp file is what an unclean shutdown leaves behind, and
    is swept on the next write."""
    try:
        os.makedirs(CONFIG, exist_ok=True)
        d, name = os.path.split(path)
        d = d or "."
        for stale in os.listdir(d):
            if stale.startswith("." + name + ".") and stale.endswith(".tmp"):
                try:
                    if os.path.getmtime(os.path.join(d, stale)) < time.time() - 60:
                        os.unlink(os.path.join(d, stale))
                except OSError:
                    pass
        fd, tmp = tempfile.mkstemp(dir=d, prefix="." + name + ".", suffix=".tmp")
        try:
            # mkstemp is 0600; keep whatever mode the file had, or the
            # umask's usual for a new one, so nothing changes but the safety.
            try:
                mode = os.stat(path).st_mode & 0o777
            except OSError:
                umask = os.umask(0)
                os.umask(umask)
                mode = 0o666 & ~umask
            os.chmod(tmp, mode)
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        pass


def read_state():
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def load_home():
    try:
        with open(STATE) as fh:
            d = json.load(fh)
        return float(d["x"]), float(d["y"])
    except (OSError, ValueError, KeyError):
        return None


# ------------------------------------------------------------- headless -----
def cmd_list(topics):
    width = max(len(t[2]) for t in KNOWLEDGE)
    for topic in sorted({t[0] for t in KNOWLEDGE}):
        if topics and topic not in topics:
            continue
        print("\n== %s" % topic)
        for t in KNOWLEDGE:
            if t[0] == topic:
                print("  %-*s  %s" % (width, t[2], t[3]))


def cmd_ask(query):
    """Search his knowledge from the command line."""
    q = query.lower()
    hits = [t for t in KNOWLEDGE
            if q in t[2].lower() or q in t[3].lower() or q in t[0].lower()]
    if not hits:
        print("Nothing about %r. Try: yoru --list" % query)
        return 1
    width = max(len(t[2]) for t in hits)
    for t in hits:
        print("%-*s  %s" % (width, t[2], t[3]))
    return 0


# ------------------------------------------------------------------- pet -----
class Bag:
    """Shuffled draw, no repeats until the pool is exhausted."""

    def __init__(self, items):
        self.items = items
        self.pool = []

    def next(self):
        if not self.pool:
            self.pool = list(self.items)
            random.shuffle(self.pool)
        return self.pool.pop()


# Cadence. He starts fast and slows down. While the fundamentals tier is
# open he speaks every BASICS_INTERVAL seconds, so a new user has all eighteen
# inside the first sitting; after that it is --interval. Each time he has
# been through the whole corpus the gap doubles — a second hearing is worth
# less than a first — up to DECAY_CAP times what was asked for, so he never
# goes silent. tools/exhaust.py is where these numbers came from.
BASICS_INTERVAL = 300
DECAY_CAP = 4


class Pet:
    def __init__(self, opts, tips):
        self.px = opts.scale
        self.interval = opts.interval
        self.quiet = getattr(opts, "quiet", False)
        self.roam = opts.roam
        self.margin = opts.margin
        self.corner = opts.corner

        self.tips = tips
        self.seen = load_seen()
        self.known = load_known()
        self.basics = not getattr(opts, "no_basics", False)
        self.current = None
        # How much of the manual he has already handed over, counted across
        # every session. Drives the chatter ratio below.
        st = read_state()
        self.shown = st.get("shown", 0)
        # Completed passes through the corpus, for the decay.
        self.passes = st.get("passes", 0)
        self.chatter = Bag(CHATTER)
        self.late = Bag(LATE)
        self.pokes = Bag(POKES)

        self.x = self.y = 0.0
        self.home_x = self.home_y = None
        self.placed = False
        self.size = None            # surface size last seen by step()

        self.dir = -1
        self.speed = 0.0
        self.dist = 0.0
        self.mode = "home"          # home | out | back | drag
        self.target = 0.0
        self.pause = 0.0
        self.next_roam = random.uniform(self.roam * 0.5, self.roam)

        self.blink = 0.0
        self.next_blink = random.uniform(2, 6)
        # Idle tics. A deer standing still is never quite still.
        self.pose = "stand"
        self.next_graze = random.uniform(25, 70)
        self.graze_for = 0.0
        # The frame between standing and lying: where it is going, how
        # long it has left, and whether something (a walk) needs him up
        # regardless of the snooze that would keep him down.
        self.settle_to = "stand"
        self.settle_for = 0.0
        self.rouse = False
        # Cud: chin out or not, time to its next move, and moves left in
        # the bout (0 between bouts).
        self.chew = 0
        self.next_chew = 0.0
        self.chews_left = 0
        # Dozing: eye shut or not, and time to the next change.
        self.doze = False
        self.next_doze = 0.0
        self.was_resting = False
        self.ear = 0.0
        self.next_ear = random.uniform(4, 12)
        # The tail says two things. The wag -- casual, side to side -- is
        # the all-clear, and it is what an idle deer does. The flag is
        # the alarm: danger is here, and he only gives it when he has
        # spooked himself into a bound. `tail` times the wag, `flag` the
        # flag; tail_frame() says which is drawn.
        self.tail = 0.0
        self.next_tail = random.uniform(8, 20)
        self.flag = 0.0
        self.next_talk = random.uniform(20, 40)
        self.snooze_until = 0.0
        self.last_spoke = -999.0
        # Presence. Tips are only spent on someone who is actually here;
        # anything else and they'd be burned talking to an empty chair.
        self.idle_after = getattr(opts, "idle", 300)
        self.present_until = 1e9 if not self.idle_after else 0.0
        # --still: parked for good. No walks, no bounds, no grazing; he
        # still blinks and still talks.
        self.still = getattr(opts, "still", False)

        self.head = self.text = None
        self.text_until = 0.0
        # Last values --debug reported, so it only speaks on a change.
        self._last_pose = self.pose
        self._last_doze = False
        self._was_present = self.present(0.0)

    # -- placement ---------------------------------------------------------
    @property
    def w(self):
        return SW * self.px

    @property
    def h(self):
        return SH * self.px

    def place(self, width, height):
        saved = load_home()
        if saved:
            self.home_x, self.home_y = saved
        else:
            m = self.margin
            right = self.corner in ("br", "tr")
            bottom = self.corner in ("br", "bl")
            self.home_x = (width - self.w - m) if right else m
            self.home_y = (height - self.h - m) if bottom else m
        self.clamp_home(width, height)
        self.x, self.y = self.home_x, self.home_y
        self.dir = -1 if self.home_x > width / 2 else 1
        self.size = (width, height)
        self.placed = True

    def clamp_home(self, width, height):
        self.home_x = max(4, min(self.home_x, width - self.w - 4))
        self.home_y = max(4, min(self.home_y, height - self.h - 4))

    def refit(self, width, height):
        """The surface changed size under him — a monitor was unplugged and
        the compositor moved him to a smaller one, or a bigger one arrived.
        A spot that was on-screen may not be now, and off-screen means
        invisible *and* undraggable, since the input region follows him.
        Pull home and his current position back inside the new bounds."""
        was = (self.home_x, self.home_y, self.x, self.y)
        self.clamp_home(width, height)
        self.x = max(4, min(self.x, width - self.w - 4))
        self.y = max(4, min(self.y, height - self.h - 4))
        if self.mode in ("out", "back"):
            self.target = max(4, min(self.target, width - self.w - 4))
        debug("surface: %dx%d -> %dx%d; home (%d,%d) -> (%d,%d), at (%d,%d) -> (%d,%d)",
              self.size[0], self.size[1], width, height, was[0], was[1],
              self.home_x, self.home_y, was[2], was[3], self.x, self.y)

    # -- speech ------------------------------------------------------------
    def snoozing(self, now):
        return now < self.snooze_until

    def present(self, now):
        """True when there is evidence of a human at the machine."""
        return not self.idle_after or now < self.present_until

    def saw_activity(self, now):
        self.present_until = now + self.idle_after

    def mark_seen(self, tip):
        self.shown += 1
        self.seen.add(tip_id(tip))
        if len(self.seen) >= len(self.tips) - len(suppressed):
            self.seen.clear()
            self.passes += 1
            debug("pass %d complete; cadence now %.0fs", self.passes,
                  self.cadence())
        st = read_state()
        st["shown"] = self.shown
        st["passes"] = self.passes
        save_json(STATE, st)
        save_json(SEEN, sorted(self.seen))

    def basics_open(self):
        """True while a fundamental is still to be taught on the first pass:
        unseen, not retired, and not withheld by the binding or package
        checks (a tip he can never say must not hold the fast phase open).
        Second and later passes are never the tutorial again."""
        return (self.basics and self.passes == 0 and any(
            tid in FUNDAMENTAL and tid not in self.seen
            and tid not in self.known and tid not in suppressed
            for tid in (tip_id(t) for t in self.tips)))

    def cadence(self):
        """Average seconds between utterances right now. An explicit
        --interval below the basics rate wins in both phases: someone
        asking for fast means it."""
        if self.quiet:
            return 1e9
        if self.basics_open():
            return min(self.interval, BASICS_INTERVAL)
        return self.interval * min(2 ** self.passes, DECAY_CAP)

    def pick(self, cls="", context=None, why="ambient"):
        """Prefer an unseen tip, and the most specific context match.

        A tip that matches the window *title* (nvim, lazygit, btop running
        inside a terminal) beats one that only matches the terminal's own
        class, so Neovim advice wins over generic shell advice when you are
        actually in Neovim.
        """
        pool = self.tips
        if context is not None:
            scored = []
            for t in self.tips:
                if not t[1]:
                    continue
                if any(m in context and m not in cls for m in t[1]):
                    scored.append((2, t))
                elif any(m in cls for m in t[1]):
                    scored.append((1, t))
            if not scored:
                debug("tip (%s): nothing matches %r", why, cls)
                return None
            best = max(s for s, _ in scored)
            pool = [t for s, t in scored if s == best]
        pool = [t for t in pool if tip_id(t) not in suppressed]
        if not pool:
            debug("tip (%s): every candidate is suppressed", why)
            return None
        # The general pool is the fundamentals until they are used up. A
        # retired one counts as used: "I know this" must not hold the tier
        # open. Once none is left, this is exactly the draw it always was.
        basics = [] if context is not None or not self.basics else [
            t for t in pool if tip_id(t) in FUNDAMENTAL
            and tip_id(t) not in self.seen and tip_id(t) not in self.known]
        if basics:
            pool = basics
        pool = [t for t in pool if tip_id(t) not in self.known] or pool
        fresh = [t for t in pool if tip_id(t) not in self.seen]
        tip = random.choice(fresh or pool)
        debug("tip (%s): %s — %d unseen of %d candidates%s%s", why, tip_id(tip),
              len(fresh), len(pool), (" for %r" % cls) if context is not None else "",
              (" [fundamental, %d left]" % (len(basics) - 1)) if basics else "")
        self.mark_seen(tip)
        self.current = tip
        return tip

    def mark_known(self, tip):
        self.known.add(tip_id(tip))
        debug("known: retired %s (%d retired)", tip_id(tip), len(self.known))
        save_json(KNOWN, sorted(self.known))

    def say(self, head, text, secs, now):
        # Head up before he says anything. Off the ground too, but that
        # goes through the settle frame in step(): text is set here, and
        # a deer with something to say is never one who wants to lie down.
        if self.pose == "graze":
            self.pose = "stand"
        self.graze_for = 0.0
        self.head, self.text = head, text
        self.text_until = now + secs
        self.last_spoke = now
        self.pause = max(self.pause, secs)

    def say_tip(self, tip, secs, now):
        self.say(tip[2], tip[3], secs, now)

    def chatter_share(self):
        """Personality earns more airtime as the teaching runs out.

        A new user needs keybindings, not opinions about subscriptions —
        they can't close a window yet. Someone who has worked through the
        manual needs the opposite, because a tip deck you have exhausted is
        exactly how a desktop pet becomes wallpaper. So the ratio climbs
        from 15% to 40% across roughly one full pass of the corpus.
        """
        progress = min(1.0, self.shown / max(1, len(self.tips)))
        return 0.15 + 0.25 * progress

    def next_ambient(self, why="ambient"):
        if random.random() < self.chatter_share():
            self.current = None
            hour = datetime.datetime.now().hour
            debug("chatter (%s): share %.2f after %d tips shown", why,
                  self.chatter_share(), self.shown)
            if (hour >= 23 or hour < 5) and random.random() < 0.5:
                return None, self.late.next()
            return None, self.chatter.next()
        t = self.pick(why=why)
        if not t:
            debug("chatter (%s): no tip available", why)
        return (t[2], t[3]) if t else (None, self.chatter.next())

    # -- motion ------------------------------------------------------------
    def step(self, dt, now, width, height):
        if not self.placed:
            self.place(width, height)
        elif (width, height) != self.size:
            self.refit(width, height)
            self.size = (width, height)
        if DEBUG:
            self._trace(now)

        # Lying down is what snooze and an empty chair look like. Middle
        # click used to change nothing on screen, so the only way to see it
        # had worked was to click again, which undid it. He lies down when
        # snoozed or when nobody is here, and gets up the moment either
        # ends -- and, like grazing, before he speaks or walks. Not gated
        # on --still: it is a pose, not a movement. Hidden he is never
        # stepped at all, so hidden he never lies down either.
        #
        # Both ways go through one held frame, the settle, or the change is
        # a teleport. Its destination can flip mid-hold (a second middle
        # click 100ms after the first) and it simply lands on the new one.
        want = "rest" if ((self.snoozing(now) or not self.present(now))
                          and self.mode == "home" and not self.text
                          and self.pause <= 0 and not self.rouse) else "stand"
        if self.pose == "settle":
            self.settle_to = want
            self.settle_for -= dt
            if self.settle_for <= 0:
                self.pose = want
        elif want == "rest" and self.pose != "rest":
            self.pose, self.settle_to, self.settle_for = "settle", "rest", SETTLE_SECS
            self.graze_for = 0.0
        elif want == "stand" and self.pose == "rest":
            self.pose, self.settle_to, self.settle_for = "settle", "stand", SETTLE_SECS
        if self.pose == "stand":
            self.rouse = False
        resting = self.pose == "rest"

        # The doze cycle runs only while he is bedded; anywhere else the
        # eye is open. He lies down alert, then dozes and wakes by turns.
        if resting:
            if not self.was_resting:
                self.doze = False
                self.next_doze = random.uniform(*DOZE_FIRST)
            self.next_doze -= dt
            if self.next_doze <= 0:
                self.doze = not self.doze
                self.next_doze = random.uniform(*(DOZE_FOR if self.doze else DOZE_ALERT))
        else:
            self.doze = False
        self.was_resting = resting

        # A motionless deer reads as crashed; a blinking one reads as
        # asleep. So the blink never stops, and lying down it slows: the
        # lids stay shut longer and the tail goes half as often. The ear
        # goes a little more often -- bedded deer stay alert, and the ears
        # never stop -- but the head itself stays where it is.
        self.blink -= dt
        self.next_blink -= dt
        if self.next_blink <= 0:
            if not self.doze:                  # shut already; nothing to blink
                self.blink = 0.25 if resting else 0.11
            self.next_blink = random.uniform(2.5, 7.5)

        self.ear -= dt
        self.next_ear -= dt
        if self.next_ear <= 0:
            self.ear = 0.25
            self.next_ear = random.uniform(3, 11) if resting else random.uniform(4, 14)

        # Cud, only lying down and only awake: it pauses while the eye is
        # shut and picks the bout back up when it opens. The rhythm is
        # regular inside a bout and the bouts are not, so he never looks
        # like a metronome.
        if resting and self.doze:
            self.chew = 0
        elif resting:
            self.next_chew -= dt
            if self.next_chew <= 0:
                if self.chews_left > 0:
                    self.chew = 0 if self.chew else 1
                    self.chews_left -= 1
                    self.next_chew = random.uniform(*CHEW_STEP)
                    if self.chews_left == 0:
                        self.chew = 0
                        self.next_chew = random.uniform(*CHEW_PAUSE)
                else:
                    self.chews_left = 2 * random.randint(*CHEW_BOUT)
                    self.next_chew = 0.0
        elif self.chew or self.chews_left:
            self.chew = 0
            self.chews_left = 0
            self.next_chew = 0.0

        self.tail -= dt
        self.flag -= dt
        self.next_tail -= dt
        if self.next_tail <= 0:
            self.tail = WAG_SECS
            self.next_tail = random.uniform(9, 25) * (2 if resting else 1)

        # He only puts his head down when he's settled, parked and quiet --
        # never mid-sentence, and never while walking somewhere.
        if self.graze_for > 0:
            self.graze_for -= dt
            if self.graze_for <= 0 or self.text or self.mode != "home":
                self.graze_for = 0.0
                self.pose = "stand"
        elif (self.mode == "home" and not self.text and self.pause <= 0
              and not self.still and self.pose == "stand"):
            self.next_graze -= dt
            if self.next_graze <= 0:
                self.pose = "graze"
                self.graze_for = random.uniform(4, 11)
                self.next_graze = random.uniform(30, 90)

        if self.text and now > self.text_until:
            self.head = self.text = None

        self.next_talk -= dt
        if self.next_talk <= 0:
            if self.snoozing(now) or not self.present(now) or not visible:
                # Say nothing and, crucially, pick nothing — an unread tip
                # must not be marked seen. Just look again shortly.
                debug("ambient: held (%s), again in 30s",
                      "snoozing" if self.snoozing(now)
                      else "away" if not self.present(now) else "hidden")
                self.next_talk = 30.0
            else:
                cadence = self.cadence()
                self.next_talk = random.uniform(cadence * 0.6, cadence * 1.4)
                head, text = self.next_ambient()
                self.say(head, text, 8.0, now)

        if self.mode == "home":
            # Facing matters. An agent that watches you measurably raises
            # anxiety and lowers task performance, and Swartz's suggested fix
            # is literally "turn away from the user when not called into
            # service". So he grazes outward, and turns to face you only when
            # he actually has something to say.
            inward = -1 if self.home_x > width / 2 else 1
            self.dir = inward if self.text else -inward

        if self.mode == "drag":
            return
        if self.pause > 0:
            self.pause -= dt
            if self.pause <= 0 and self.bounding():
                self.flag = 1.4          # the flag goes up as he bolts, not
            return                       # while he stands at the far end

        if self.mode == "home":
            if self.still:
                return
            if self.snoozing(now):
                return          # told to be quiet for an hour: he stays down
            self.next_roam -= dt
            if self.next_roam <= 0:
                if self.pose != "stand":
                    # Head up, or up off the ground, before he moves. The
                    # walk waits the one settle frame; rouse overrides the
                    # "nobody here" that would otherwise keep him down --
                    # nobody told him to stop, and a deer that never moves
                    # for an hour isn't right either.
                    self.rouse = True
                    if self.pose == "graze":
                        self.pose = "stand"
                        self.graze_for = 0.0
                    return
                span = min(width * 0.45, 520)
                self.target = max(4, min(
                    self.home_x + random.uniform(-span, span), width - self.w - 4))
                # A walk only moves x. If y is off the surface he would walk
                # past unseen, so bring it in before he sets off.
                self.y = max(4, min(self.y, height - self.h - 4))
                # One trip in five he spooks himself and bounds it, tail up.
                if random.random() < 0.2:
                    self.speed, self.flag = 150.0, 1.4
                else:
                    self.speed = random.uniform(46, 72)
                self.mode = "out"
            return

        goal = self.target if self.mode == "out" else self.home_x
        delta = goal - self.x
        # Arrive if this frame would reach or overshoot the goal. A fixed
        # threshold smaller than one frame's travel lets a bounding deer
        # skip past it, flip, skip back, and oscillate on the spot forever.
        if abs(delta) <= max(2.0, self.speed * dt):
            self.x = goal
            if self.mode == "out":
                self.mode = "back"
                self.pause = random.uniform(1.5, 5.0)
                if random.random() < 0.2:
                    self.speed = 150.0       # flagged when the pause ends
                else:
                    self.speed = random.uniform(46, 72)
            else:
                self.mode = "home"
                self.next_roam = random.uniform(self.roam * 0.7, self.roam * 1.6)
            return

        self.dir = 1 if delta > 0 else -1
        self.x += self.dir * self.speed * dt
        self.dist += self.speed * dt

    def _trace(self, now):
        """--debug only: report presence and pose the frame after they change."""
        here = self.present(now)
        if here != self._was_present:
            self._was_present = here
            debug("presence: %s", "here" if here
                  else "away (%.0fs without activity)" % self.idle_after)
        if self.doze != self._last_doze:
            self._last_doze = self.doze
            debug("doze: %s", "eye shut" if self.doze else "eye open")
        if self.pose != self._last_pose:
            why = ""
            if self.pose == "graze":
                why = " for %.0fs" % self.graze_for
            elif self.pose == "rest":
                why = " (snoozed)" if self.snoozing(now) else " (away)"
            elif self.pose == "settle":
                why = " -> %s" % self.settle_to
            elif self.text:
                why = " (speaking)"
            elif self.mode != "home":
                why = " (%s)" % self.mode
            debug("pose: %s -> %s%s", self._last_pose, self.pose, why)
            self._last_pose = self.pose

    def moving(self):
        return self.mode in ("out", "back") and self.pause <= 0

    def bounding(self):
        return self.moving() and self.speed > 120

    def gait(self):
        """None parked; the bound when he has spooked himself, else the
        walk. He ambles at 46-72 px/s, about half a body length a second,
        and that is a walk. The trot is drawn but not used: it would be
        the gait for a faster amble, if he ever has one."""
        if not self.moving():
            return None
        return "bound" if self.speed > 120 else "walk"

    def tail_frame(self):
        """2 for the flag, 1 for the wag's tip-on-the-flank half, else 0.
        The wag alternates every WAG_BEAT: two swings, side to side."""
        if self.flag > 0 and self.bounding():
            return 2
        if self.tail > 0 and int((WAG_SECS - self.tail) / WAG_BEAT) % 2 == 0:
            return 1
        return 0

    def render_key(self):
        """Everything a frame depends on. Two equal keys draw the same
        pixels, so a frame whose key hasn't moved needn't be drawn at all —
        and between a blink, an ear and a tail, most frames haven't."""
        return (int(self.x), int(self.y), self.dir, self.frame(), self.pose,
                self.blink > 0, self.ear > 0, self.tail_frame(), self.gait(),
                self.chew, self.doze,
                self.head, self.text)

    def frame(self):
        if not self.moving():
            return 1
        step = self.px * (3.2 if self.bounding() else 2.2)
        return int(self.dist / step) % 4


# --------------------------------------------------------------- hyprland ----
def cursor_pos():
    """Mouse position, as a cheap presence signal."""
    try:
        r = subprocess.run(["hyprctl", "-j", "cursorpos"],
                           capture_output=True, text=True, timeout=0.5)
        d = json.loads(r.stdout)
        return (d.get("x"), d.get("y"))
    except Exception:
        return None


def active_window():
    """('class', 'class title') for the focused window, or ('', '')."""
    try:
        out = subprocess.run(["hyprctl", "-j", "activewindow"],
                             capture_output=True, text=True, timeout=0.5)
        d = json.loads(out.stdout)
        cls = (d.get("class") or "").lower()
        return cls, (cls + " " + (d.get("title") or "")).lower()
    except Exception:
        return "", ""


# ---------------------------------------------------------------- verify ----
# The manual is the source of truth for what a binding *means*; the running
# compositor is the source of truth for whether it *exists*. A tip whose keys
# have been unbound or never existed here is withheld, not rewritten — a
# live description is a two-word label and can't stand in for a sentence.
#
# Only these topics carry Hyprland binds. tmux, Neovim, Ghostty, lazygit, the
# file manager and the shell have their own keys that look the same and must
# never be checked against the compositor.
HYPR_TOPICS = {"windows", "workspaces", "panels", "capture", "clipboard",
               "notifications", "style", "toggles", "reminders", "apps",
               "herdr", "agents", "btop", "terminal"}
MODBITS = {"SUPER": 64, "SHIFT": 1, "CTRL": 4, "ALT": 8}
# Omarchy declares digits, minus/equal and the brackets by X keycode.
KEYCODES = {str(10 + i): str((i + 1) % 10) for i in range(10)}
KEYCODES.update({"20": "MINUS", "21": "EQUAL", "34": "BRACKETLEFT",
                 "35": "BRACKETRIGHT"})
# How the manual spells a key -> how hyprctl spells it.
KEY_ALIASES = {
    "PRINT SCREEN": "PRINT", "DEL": "DELETE", "ENTER": "RETURN",
    "/": "SLASH", ",": "COMMA", ".": "PERIOD",
    "[": "BRACKETLEFT", "]": "BRACKETRIGHT",
    "LEFT MOUSE": "mouse:272", "RIGHT MOUSE": "mouse:273",
    "MUTE": "XF86AudioMute", "PLAY": "XF86AudioPlay",
    "BRIGHTNESS UP": "XF86MonBrightnessUp",
    "BRIGHTNESS DOWN": "XF86MonBrightnessDown",
}
MENTION = re.compile(r"\b((?:Super|Ctrl|Alt|Shift)(?: \+ (?:Super|Ctrl|Alt|Shift))*"
                     r" \+ [A-Za-z0-9/\[\],.]+)")
suppressed = {}     # tip id -> why, refreshed alongside the theme poll


def live_binds():
    """{(modifiers, KEY): description} from the compositor, or None.

    The text form, not `hyprctl -j binds`: JSON reports an empty key for
    every bind declared by keycode — 59 of 226 here, including all the
    workspace and resize keys — while the text form keeps "SUPER + code:10".
    None means "don't know", and the caller must then suppress nothing.
    """
    try:
        out = subprocess.run(["hyprctl", "binds"], capture_output=True,
                             text=True, timeout=1).stdout
    except Exception:
        return None
    binds = {}
    for block in out.split("\n\n"):
        f = dict((k.strip(), v.strip()) for k, v in
                 (l.split(":", 1) for l in block.splitlines() if ":" in l))
        if "modmask" not in f or "key" not in f:
            continue
        try:
            mask = int(f["modmask"])
        except ValueError:
            continue
        mods = frozenset(m for m, bit in MODBITS.items() if mask & bit)
        key = re.sub(r"^(?:(?:SUPER|SHIFT|CTRL|ALT) \+ )+", "", f["key"])
        if key.startswith("code:"):
            key = KEYCODES.get(key[5:], key)
        elif not key.startswith(("XF86", "mouse", "switch")):
            key = key.upper()
        binds[(mods, key)] = f.get("description", "")
    return binds or None


def _expand(expr):
    """'1/2/3/4', '1-9', 'Arrow', 'Brightness Up/Down' -> hyprctl key names."""
    e = expr.strip()
    if e.lower() in ("arrow", "arrows"):
        return ["LEFT", "RIGHT", "UP", "DOWN"]
    if e.lower() == "scroll wheel":
        return ["mouse_down", "mouse_up"]
    m = re.match(r"^(\d)-(\d)$", e)
    if m:
        return [str(i) for i in range(int(m.group(1)), int(m.group(2)) + 1)]
    if "/" in e and len(e) > 1:
        parts = [p.strip() for p in e.split("/")]
        if " " in parts[0] and " " not in parts[1]:   # "Brightness Up/Down"
            head = parts[0].rsplit(" ", 1)[0]
            parts = parts[:1] + [head + " " + p for p in parts[1:]]
        return [k for p in parts for k in _expand(p)]
    return [KEY_ALIASES.get(e.upper(), e.upper())]


def parse_keys(keys):
    """(modifiers, [KEY, ...]) for a Hyprland-shaped key string, else None."""
    parts = [p.strip() for p in keys.split("+")]
    mods = frozenset(p.upper() for p in parts if p.upper() in MODBITS)
    rest = [p for p in parts if p.upper() not in MODBITS]
    if len(rest) != 1 or not (mods or rest[0].upper() in KEY_ALIASES):
        return None
    return mods, _expand(rest[0])


def _missing(binds, mods, keys):
    """Which of a compound's members are unbound. A compound survives while
    more than half of it exists — one unbound workspace shouldn't take the
    whole "Super + 1/2/3/4" tip with it."""
    gone = [k for k in keys if (mods, k) not in binds]
    return gone if len(gone) * 2 >= len(keys) else []


def verify_tips(tips, binds):
    """{tip id: reason} for every tip whose keys aren't bound here."""
    out = {}
    for t in tips:
        if t[0] not in HYPR_TOPICS:
            continue
        parsed = parse_keys(t[2])
        if parsed is None:
            continue
        mods, keys = parsed
        gone = _missing(binds, mods, keys)
        if gone:
            out[tip_id(t)] = "%s: %s not bound" % (t[2], ", ".join(gone))
            continue
        # Bindings the sentence itself teaches. The manual abbreviates —
        # "Alt + K for tmux" under a Super + K heading means Super + Alt + K
        # — so a mention gets the heading's modifiers before it counts as gone.
        for m in MENTION.findall(t[3]):
            mm, mk = parse_keys(m)
            if _missing(binds, mm, mk) and _missing(binds, mm | mods, mk):
                out[tip_id(t)] = "%s: mentions %s, not bound" % (t[2], m)
                break
    return out


def refresh_suppressed(tips):
    binds = live_binds()
    if binds is None:
        if not refresh_suppressed.blind:
            debug("suppression: hyprctl binds unavailable, keeping %d withheld",
                  len(suppressed))
        refresh_suppressed.blind = True
        suppressed.update(rebound)  # can't see the compositor: change nothing
        suppressed.update(absent)   # else; neither of these needs it
        return
    refresh_suppressed.blind = False
    fresh = verify_tips(tips, binds)
    fresh.update(rebound)
    fresh.update(absent)
    if DEBUG and fresh != suppressed:
        debug("suppression: %d of %d tips withheld against %d live binds",
              len(fresh), len(tips), len(binds))
        for k in sorted(set(fresh) - set(suppressed)):
            debug("suppression: + %s", fresh[k])
        for k in sorted(set(suppressed) - set(fresh)):
            debug("suppression: - %s (bound again)", k)
    suppressed.clear()
    suppressed.update(fresh)


refresh_suppressed.blind = False    # last poll couldn't see the compositor


def cmd_verify_report(tips):
    binds = live_binds()
    if binds is None:
        print("hyprctl binds unavailable — nothing would be suppressed.")
        return 0
    scoped = [t for t in tips if t[0] in HYPR_TOPICS and parse_keys(t[2])]
    gone = verify_tips(tips, binds)
    gone.update(rebound)
    gone.update(absent)
    for t in tips:
        if tip_id(t) in gone:
            print("  %-13s %s" % (t[0], gone[tip_id(t)]))
    unbound = len(gone) - len(rebound) - len(absent)
    print("\n%d live key combos; %d of %d Hyprland-scope tips unbound here; "
          "%d rebound in your bindings.lua; %d need software that isn't installed; "
          "%d other tips never checked."
          % (len(binds), unbound, len(scoped), len(rebound), len(absent),
             len(tips) - len(scoped)))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Yoru, a Clippy for Omarchy.")
    p.add_argument("--scale", type=int, default=4, help="pixel size (default 4)")
    p.add_argument("--corner", default="br", choices=["br", "bl", "tr", "tl"],
                   help="where he parks on first run (default bottom right)")
    p.add_argument("--margin", type=int, default=24, help="gap from the screen edge")
    p.add_argument("--interval", type=float, default=900,
                   help="average seconds between utterances, tips and remarks "
                        "alike, once the first-hour tips are done (default 900; "
                        "300 until then; doubles per pass through the corpus)")
    p.add_argument("--roam", type=float, default=180,
                   help="average seconds between short walks (default 180)")
    p.add_argument("--idle", type=float, default=300,
                   help="seconds of no mouse or window activity before he "
                        "assumes you're away and stops spending tips (0 = off)")
    p.add_argument("--cooldown", type=float, default=90,
                   help="minimum quiet seconds before a contextual tip")
    p.add_argument("--topics", default="", help="comma-separated topics to limit him to")
    p.add_argument("--no-theme", action="store_true",
                   help="keep the built-in palette instead of following the theme")
    p.add_argument("--no-context", action="store_true",
                   help="ignore the focused window entirely")
    p.add_argument("--no-own", action="store_true",
                   help="don't make tips from your own ~/.config/hypr/bindings.lua")
    p.add_argument("--no-packages", action="store_true",
                   help="teach software whether or not pacman says it's installed")
    p.add_argument("--no-basics", action="store_true",
                   help="skip the first-hour tips; you already know Omarchy")
    p.add_argument("--quiet", action="store_true",
                   help="no ambient tips; only when asked or on context")
    p.add_argument("--still", action="store_true",
                   help="never walk, bound or graze; he only blinks and talks")
    p.add_argument("--version", action="version", version="yoru " + VERSION)
    p.add_argument("--start-hidden", action="store_true",
                   help="begin off screen; SIGUSR1 toggles him")
    p.add_argument("--monitor", metavar="NAME",
                   help="connector to live on, e.g. DP-1 (default: the focused "
                        "one when he starts)")
    p.add_argument("--layer", default="overlay",
                   choices=["background", "bottom", "top", "overlay"])
    p.add_argument("--ask", metavar="QUERY", help="search his knowledge and exit")
    p.add_argument("--list", action="store_true", help="print everything he knows and exit")
    p.add_argument("--verify-report", action="store_true",
                   help="show which tips this machine's bindings rule out, and exit")
    p.add_argument("--forget-known", action="store_true",
                   help="un-retire every tip you've marked as known")
    p.add_argument("--debug", action="store_true",
                   help="log every decision to stderr, for bug reports")
    opts = p.parse_args(argv)

    global DEBUG
    DEBUG = opts.debug

    load_user_tips()
    if not opts.no_own:
        load_own_binds()
    topics = {t.strip() for t in opts.topics.split(",") if t.strip()}

    if opts.forget_known:
        save_json(KNOWN, [])
        print("Retired tips restored.")
        return 0
    if opts.ask:
        return cmd_ask(opts.ask)
    if opts.list:
        cmd_list(topics)
        return 0

    tips = [t for t in KNOWLEDGE if not topics or t[0] in topics]
    if not tips:
        print("No tips match --topics %s" % opts.topics, file=sys.stderr)
        return 1
    if not opts.no_packages:
        load_packages()
    if opts.verify_report:
        return cmd_verify_report(tips)

    refresh_suppressed(tips)
    return run(opts, tips)


# ------------------------------------------------------------------- gui -----
def _load_gtk():
    """Imported lazily so --ask and --list work on a machine without GTK.

    Order matters here. gtk4-layer-shell has to be linked before
    libwayland-client, which means loading the shared object with ctypes
    *before* gi pulls in Gtk — upstream's own Python example does exactly
    this, and skipping it is the classic way to get a layer-shell app that
    builds fine and then refuses to map its surface.
    """
    from ctypes import CDLL

    layer_lib = None
    for soname in ("libgtk4-layer-shell.so.0", "libgtk4-layer-shell.so"):
        try:
            layer_lib = CDLL(soname)
            break
        except OSError:
            continue

    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib, Gdk, Pango, PangoCairo
    import cairo

    # PyGObject needs pycairo's foreign-type integration to hand a Cairo
    # context to Pango. Without it the first speech bubble dies with an
    # unhelpful KeyError, so fail loudly and usefully right here instead.
    try:
        gi.require_foreign("cairo")
    except Exception:
        sys.exit("yoru: PyGObject is missing its cairo integration.\n"
                 "  sudo pacman -S --needed python-cairo python-gobject")

    LayerShell = None
    if layer_lib is not None:
        try:
            gi.require_version("Gtk4LayerShell", "1.0")
            from gi.repository import Gtk4LayerShell as _LS
            LayerShell = _LS
        except (ValueError, ImportError):
            LayerShell = None

    # GLib.unix_signal_add now lives in the GLibUnix namespace and PyGObject
    # warns on the old spelling. Older PyGObject has no GLibUnix typelib at
    # all, so the old call stays as the fallback rather than being swapped.
    GLibUnix = None
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix as _GU
        if hasattr(_GU, "signal_add"):
            GLibUnix = _GU
    except (ValueError, ImportError):
        pass

    globals().update(Gtk=Gtk, GLib=GLib, Gdk=Gdk, Pango=Pango,
                     PangoCairo=PangoCairo, cairo=cairo, LayerShell=LayerShell,
                     GLibUnix=GLibUnix)


def resolve_monitor(name, monitors):
    """The monitor object whose connector is `name`, or None with a warning
    naming what is connected. None means "let the compositor choose", which
    is exactly what no --monitor does; nothing here may exit."""
    for connector, monitor in monitors:
        if connector == name:
            return monitor
    print("yoru: no monitor called %r; using the focused one. Connected: %s"
          % (name, ", ".join(c for c, _ in monitors) or "none"), file=sys.stderr)
    return None


def draw_sprite(cr, pet, oy):
    px, flip = pet.px, pet.dir < 0
    pts = pixels(pet.frame(), pet.blink > 0, pet.pose,
                 1 if pet.ear > 0 else 0, pet.tail_frame(),
                 pet.gait(), pet.chew, pet.doze)

    def sx(x):
        return pet.x + ((SW - 1 - x) if flip else x) * px

    cr.set_source_rgba(*OUTLINE, 0.85)
    for x, y, _ in pts:
        cr.rectangle(sx(x) - 1, oy + y * px - 1, px + 2, px + 2)
    cr.fill()
    for x, y, col in pts:
        cr.set_source_rgb(*col)
        cr.rectangle(sx(x), oy + y * px, px, px)
        cr.fill()


def draw_bubble(cr, pet, oy, width):
    esc = GLib.markup_escape_text
    markup = ('<span foreground="%s">%s</span>\n%s'
              % (ACCENT_HEX, esc(pet.head or "Yoru"), esc(pet.text)))

    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(Pango.FontDescription("monospace 10"))
    layout.set_width(int(360 * Pango.SCALE))
    layout.set_wrap(Pango.WrapMode.WORD_CHAR)
    layout.set_spacing(int(3 * Pango.SCALE))
    layout.set_markup(markup)
    tw, th = layout.get_pixel_size()

    pad = 11
    bw, bh = tw + pad * 2, th + pad * 2
    bx = max(8, min(pet.x + pet.w / 2 - bw / 2, width - bw - 8))
    above = oy - bh - 14 >= 8
    by = (oy - bh - 14) if above else (oy + pet.h + 14)

    cr.set_source_rgba(0, 0, 0, 0.45)
    cr.rectangle(bx + 4, by + 4, bw, bh)
    cr.fill()

    cr.set_source_rgb(*BUBBLE_BG)
    cr.rectangle(bx, by, bw, bh)
    cr.fill_preserve()
    cr.set_source_rgb(*PAL["b"])
    cr.set_line_width(2)
    cr.stroke()

    tail = max(bx + 14, min(pet.x + pet.w / 2, bx + bw - 14))
    ty, tip = (by + bh - 1, by + bh + 9) if above else (by + 1, by - 9)
    cr.set_source_rgb(*BUBBLE_BG)
    cr.move_to(tail - 7, ty)
    cr.line_to(tail + 7, ty)
    cr.line_to(tail, tip)
    cr.close_path()
    cr.fill()
    cr.set_source_rgb(*PAL["b"])
    cr.move_to(tail - 7, ty)
    cr.line_to(tail, tip)
    cr.line_to(tail + 7, ty)
    cr.stroke()

    cr.set_source_rgb(*PAL["b"])
    cr.move_to(bx + pad, by + pad)
    PangoCairo.show_layout(cr, layout)


def build_app(opts, tips):
    class Yoru(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="dev.local.yoru")
            self.opts = opts
            self.pet = Pet(opts, tips)
            self.last = GLib.get_monotonic_time() / 1e6
            self.ctx_cls = None
            self.ctx_offers = {}
            self.ctx_day = datetime.date.today()
            self.last_cursor = None
            self.ctx_full = (None, None)
            self._grab = (0.0, 0.0)
            self._sources = {}          # name -> GLib source id, while running
            self._key = None            # last frame drawn
            self._palette = 0           # bumps on every theme repaint

        # -- setup -------------------------------------------------------
        def do_activate(self):
            # A second `yoru` while one runs is forwarded here by GTK's
            # single-instance machinery. Without this it opened a second
            # window in the running process: two deer, one Pet.
            if getattr(self, "win", None) is not None:
                debug("activate: already running, ignoring a second launch")
                return
            win = Gtk.ApplicationWindow(application=self)
            win.set_decorated(False)
            win.add_css_class("yoru")

            css = Gtk.CssProvider()
            css.load_from_data(b"window.yoru, window.yoru > * "
                               b"{ background: transparent; }")
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            if LayerShell is None:
                print("yoru: gtk4-layer-shell unavailable — falling back to a\n"
                      "normal window, which Hyprland will tile. Install it with:\n"
                      "  sudo pacman -S --needed gtk4-layer-shell",
                      file=sys.stderr)
                win.set_default_size(900, 400)
            else:
                LayerShell.init_for_window(win)
                LayerShell.set_namespace(win, "yoru")
                LayerShell.set_layer(win, {
                    "background": LayerShell.Layer.BACKGROUND,
                    "bottom": LayerShell.Layer.BOTTOM,
                    "top": LayerShell.Layer.TOP,
                    "overlay": LayerShell.Layer.OVERLAY,
                }[opts.layer])
                for edge in (LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT,
                             LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM):
                    LayerShell.set_anchor(win, edge, True)
                LayerShell.set_exclusive_zone(win, 0)
                LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)
                # A layer surface lives on one output, and without a choice
                # the compositor uses the one with keyboard focus when he
                # maps. --monitor pins it — when that output is here. It
                # must never stop him starting: the flag lives in
                # autostart.lua, and a laptop boots undocked.
                if opts.monitor:
                    monitors = Gdk.Display.get_default().get_monitors()
                    chosen = resolve_monitor(opts.monitor, [
                        (monitors.get_item(i).get_connector(), monitors.get_item(i))
                        for i in range(monitors.get_n_items())])
                    if chosen is not None:
                        LayerShell.set_monitor(win, chosen)
                        debug("monitor: pinned to %s", opts.monitor)

            area = Gtk.DrawingArea()
            area.set_draw_func(self.on_draw)
            win.set_child(area)

            click = Gtk.GestureClick()
            click.set_button(0)
            click.connect("pressed", self.on_click)
            area.add_controller(click)

            drag = Gtk.GestureDrag()
            drag.connect("drag-begin", self.on_drag_begin)
            drag.connect("drag-update", self.on_drag_update)
            drag.connect("drag-end", self.on_drag_end)
            area.add_controller(drag)

            self.win, self.area = win, area
            # --no-theme means the built-in palette and no look at the theme
            # files at all, at start or later.
            self._theme_stamp = None
            if not opts.no_theme:
                themed = apply_theme()
                if DEBUG:
                    debug("theme: %s at start (%s)", _theme_label(),
                          "applied" if themed else "unreadable, built-in palette")
                self._theme_stamp = theme_stamp()
            win.present()
            if not read_state().get("introduced"):
                GLib.timeout_add_seconds(4, self.intro)
            _on_visibility.append(self.set_visible)
            if visible:
                self.start()

        # -- scheduling --------------------------------------------------
        # Every recurring job is a source in self._sources, so hiding him
        # can stop all of it and showing him can start it again. The
        # polls reschedule themselves each time with an interval chosen
        # from what the machine is doing: 2s and 4s with someone there,
        # 30s when presence says they're away or he's snoozed. The first
        # poll that sees activity handles it in the same call, so the
        # window that woke you up still gets its tip.
        def start(self):
            self._running = True
            self.last = GLib.get_monotonic_time() / 1e6
            self._key = None
            self._sources["tick"] = GLib.timeout_add(33, self.tick)
            if not opts.no_theme:
                self._schedule("theme", self.poll_theme, 4)
            # The binding re-check is its own source: it has nothing to do
            # with themes, and must not vanish with --no-theme.
            self._schedule("binds", self.poll_binds, 4)
            if not opts.no_context:
                self.poll_context()     # now, so a window you're in gets its
                                        # tip; it schedules the next itself

        def stop(self):
            self._running = False
            for src in self._sources.values():
                GLib.source_remove(src)
            self._sources.clear()

        def _schedule(self, name, fn, seconds):
            self._sources[name] = GLib.timeout_add_seconds(seconds, fn)

        def _reschedule(self, name, fn, busy_seconds, now):
            """Return False from the caller after this: the old source is
            done, a new one is queued at the interval that fits."""
            self._sources.pop(name, None)
            if not getattr(self, "_running", False):
                return False            # stopped while we ran
            quiet = not self.pet.present(now) or self.pet.snoozing(now)
            self._schedule(name, fn, 30 if quiet else busy_seconds)
            return False

        def set_visible(self, shown):
            """SIGUSR1. Hidden means no stepping and no polling at all — he
            is invisible and untouchable, so nothing he'd do could show.
            The Pet keeps its state untouched; showing him resumes it."""
            if shown:
                self.start()
            else:
                self.stop()
            surface = self.win.get_surface()
            if surface is not None and not shown:
                surface.set_input_region(cairo.Region())
            self.area.queue_draw()

        # -- input -------------------------------------------------------
        def on_click(self, gesture, n_press, x, y):
            now = GLib.get_monotonic_time() / 1e6
            button = gesture.get_current_button()
            pet = self.pet
            if button == 3:                                   # next tip
                head, text = pet.next_ambient(why="asked")
                pet.say(head, text, 9.0, now)
            elif button == 2:                                 # snooze
                if pet.snoozing(now):
                    pet.snooze_until = 0.0
                    debug("snooze: off (middle click)")
                    pet.say(None, "Back. What did I miss?", 3.0, now)
                else:
                    pet.snooze_until = now + 3600
                    debug("snooze: on for 3600s (middle click)")
                    pet.say(None, "Quiet for an hour. Middle click to undo.",
                            3.0, now)

        def on_drag_begin(self, gesture, x, y):
            self.pet.mode = "drag"
            self._grab = (self.pet.x, self.pet.y)

        def on_drag_update(self, gesture, dx, dy):
            pet = self.pet
            if pet.mode != "drag":
                return
            w, h = self.area.get_width(), self.area.get_height()
            pet.x = max(4, min(self._grab[0] + dx, w - pet.w - 4))
            pet.y = max(4, min(self._grab[1] + dy, h - pet.h - 4))

        def on_drag_end(self, gesture, dx, dy):
            pet = self.pet
            if pet.mode != "drag":
                return
            if abs(dx) < 3 and abs(dy) < 3:                   # a poke, not a drag
                now = GLib.get_monotonic_time() / 1e6
                pet.mode = "home"
                if pet.text and pet.current:
                    # "I know this one." Gone for good.
                    pet.mark_known(pet.current)
                    pet.current = None
                    pet.say(None, "Noted. You won't see that one again.",
                            2.5, now)
                elif not pet.snoozing(now):
                    pet.say(None, pet.pokes.next(), 3.0, now)
                return
            pet.home_x, pet.home_y = pet.x, pet.y
            pet.mode = "home"
            pet.next_roam = random.uniform(pet.roam * 0.7, pet.roam * 1.6)
            pet.dir = -1 if pet.home_x > self.area.get_width() / 2 else 1
            state = read_state()
            state.update(x=round(pet.home_x), y=round(pet.home_y))
            debug("moved: home is now (%d, %d), saved", state["x"], state["y"])
            save_json(STATE, state)

        def poll_theme(self):
            """Repaint when the Omarchy theme changes, silently."""
            stamp = theme_stamp()
            if stamp != self._theme_stamp:
                self._theme_stamp = stamp
                themed = apply_theme()
                self._palette += 1
                if DEBUG:
                    debug("theme: reloaded %s (%s)", _theme_label(),
                          "applied" if themed else "unreadable, palette kept")
            return self._reschedule("theme", self.poll_theme, 4,
                                    GLib.get_monotonic_time() / 1e6)

        def poll_binds(self):
            """Re-read hyprctl binds, so a rebind lands without a restart."""
            refresh_suppressed(self.pet.tips)
            return self._reschedule("binds", self.poll_binds, 4,
                                    GLib.get_monotonic_time() / 1e6)

        # -- context -----------------------------------------------------
        def poll_context(self):
            pet, now = self.pet, GLib.get_monotonic_time() / 1e6

            # The per-app cap is a daily allowance, not a per-process one.
            # He lives for weeks at a time; without this, contextual tips
            # would go silent after the first day of uptime.
            today = datetime.date.today()
            if today != self.ctx_day:
                self.ctx_day = today
                self.ctx_offers.clear()

            cls, full = active_window()
            cursor = cursor_pos()

            # No hyprctl at all means no presence signal, and a pet that
            # would sulk forever. Fall back to assuming someone is there.
            if cursor is None and not cls:
                pet.saw_activity(now)
            else:
                moved = cursor is not None and cursor != self.last_cursor
                changed = bool(cls) and (cls, full) != self.ctx_full
                if moved or changed:
                    pet.saw_activity(now)
            self.last_cursor = cursor
            self.ctx_full = (cls, full)

            if not cls or cls == self.ctx_cls:
                return self._reschedule("context", self.poll_context, 2, now)
            self.ctx_cls = cls
            held = ("snoozing" if pet.snoozing(now)
                    else "away" if not pet.present(now)
                    else "hidden" if not visible
                    else "cooldown, %.0fs left" % (opts.cooldown - (now - pet.last_spoke))
                    if now - pet.last_spoke < opts.cooldown
                    else "daily cap" if self.ctx_offers.get(cls, 0) >= 2
                    else None)
            if held:
                debug("context %r: held (%s)", cls, held)
                return self._reschedule("context", self.poll_context, 2, now)
            tip = pet.pick(cls=cls, context=full, why="contextual")
            if tip:
                pet.say_tip(tip, 9.0, now)
                self.ctx_offers[cls] = self.ctx_offers.get(cls, 0) + 1
            return self._reschedule("context", self.poll_context, 2, now)

        def intro(self):
            """Say hello once, ever — right click is his best feature and
            nothing else advertises it."""
            if not visible:
                return True     # try again once he is on screen
            now = GLib.get_monotonic_time() / 1e6
            self.pet.saw_activity(now)
            debug("intro: first run, saying hello")
            self.pet.say("Yoru",
                         "I know the Omarchy manual. Right click for a tip, "
                         "left click one to say you already know it and retire "
                         "it, middle click (three fingers on a trackpad) to "
                         "snooze, drag to move me.",
                         14.0, now)
            state = read_state()
            state["introduced"] = True
            save_json(STATE, state)
            return False

        # -- loop --------------------------------------------------------
        def tick(self):
            now = GLib.get_monotonic_time() / 1e6
            dt = min(now - self.last, 0.05)
            self.last = now
            self.pet.step(dt, now,
                          self.area.get_width() or 1920,
                          self.area.get_height() or 1080)
            key = self.pet.render_key() + (self._palette,)
            if key == self._key:
                return True             # same pixels as last frame; no draw
            if self._key is None or key[:2] != self._key[:2]:
                surface = self.win.get_surface()
                if surface is not None:
                    # The input region follows him, and nothing else. Hidden
                    # is handled in set_visible: an empty region hands every
                    # click to whatever is underneath, not to an invisible deer.
                    surface.set_input_region(cairo.Region(cairo.RectangleInt(
                        int(self.pet.x), int(self.pet.y),
                        int(self.pet.w), int(self.pet.h))))
            self._key = key
            self.area.queue_draw()
            return True

        def on_draw(self, area, cr, width, height):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            if not visible:
                return
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.set_antialias(cairo.ANTIALIAS_NONE)

            if not self.pet.placed:
                self.pet.place(width, height)
            draw_sprite(cr, self.pet, self.pet.y)
            if self.pet.text:
                cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
                draw_bubble(cr, self.pet, self.pet.y, width)

    return Yoru()


def run(opts, tips):
    global visible
    visible = not opts.start_hidden
    _load_gtk()
    if DEBUG:
        st = read_state()
        debug("start: yoru %s | python %s | gtk %d.%d.%d | layer-shell %s | "
              "hyprctl %s | signals via %s",
              " ".join(sys.argv[1:]), sys.version.split()[0],
              Gtk.get_major_version(), Gtk.get_minor_version(),
              Gtk.get_micro_version(),
              "yes" if LayerShell else "no",
              "yes" if shutil.which("hyprctl") else "no",
              "GLibUnix" if GLibUnix else "GLib (deprecated)")
        debug("start: %d tips | %d seen, %d retired, %d shown, %d passes | "
              "introduced %s | home %s | %s", len(tips), len(load_seen()),
              len(load_known()), st.get("shown", 0), st.get("passes", 0),
              bool(st.get("introduced")),
              load_home() or "default %s" % opts.corner, CONFIG)
    # Dispatched from the main loop, not from inside the signal handler, so
    # the flip can never land in the middle of a frame.
    add = GLibUnix.signal_add if GLibUnix else GLib.unix_signal_add
    add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, toggle_visible)
    return build_app(opts, tips).run([])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        os._exit(0)
    except KeyboardInterrupt:
        os._exit(0)
