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

VERSION = "1.1.0"

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
#
# The body is anatomically wrong in two places, on purpose, and both were
# corrected once and reverted (2026-09-16), so read this before doing it
# again from the references.
#
# The belly tapers the wrong way. Rows 14-17 go from x 2-17 to x 2-15:
# shallower toward the front, square at the rump. A deer is the opposite
# -- a deep brisket at the chest and the flank tucking up toward the rear;
# Longstride's proportion check is that the nose lines up with the front
# legs and the chest sticks out from there. It was inverted: rows 15-16
# to x=17, row 17 to x=16, and the rear corner stepped in over rows 16-17
# (x=3, then x=4). At 16x it was the better deer. At the shipped 4px the
# near hind leg, a column at x 3-4 from row 18, no longer had body over
# it: it hung from (4,17) by one diagonal pixel, passed check 51 as one
# piece, and read as a leg floating beside the body. The tuck cannot
# move forward of the hind leg because the leg is a fixed column, and the
# leg cannot move without the respacing described at WALK. So the square
# rump stays: it is what holds the hind leg on.
#
# No jugular groove. John Muir Laws has the brachiocephalicus running
# skull to shoulder and "the lower edge of this muscle often makes a
# prominent groove called the jugular groove"; without it neck and chest
# share a tone with no line between them, and head, neck and shoulder
# read as one mass, which is what makes the resting neck look thick. It
# was drawn: three pixels of FAR one inside the throat edge, (17,10)
# (16,11), continued into the chest at (16,12) so it survived the settle
# and rest poses, where rows 10-11 slide under the shoulder. Legible in
# all 22 themes, dark and light. At 4px it read as a smudge, not a line:
# three pixels of shade is a large share of a neck five wide. A line on
# the edge itself (18,10) (17,11) only thinned the neck; started from the
# jaw at (16,9) it was a spot. Not drawn at this size.
#
# Sources: johnmuirlaws.com/draw-deer-anatomy (jugular groove, leg taper,
# hock divot), longstrideillustration.com/deer-drawing-tutorial (nose to
# front-leg proportion).
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
# body length a second, which is a walk, and the walk below is the roam
# gait. It is the drawing that shipped all day on 2026-09-16, and what
# follows is the whole of that evening's work on it, all of it reverted,
# recorded so nobody re-derives it from the references.
#
# The walk: each foot lands on its own, in lateral sequence -- near hind,
# near fore, far hind, far fore -- a quarter of the stride apart, and three
# feet are on the ground at almost any moment. One leg per frame is in the
# air here, knee bent, coming forward; the other three are planted: just
# landed at reach, under, and pushing off. No bob; a walk is level, head
# included. A walking quadruped's head does nod, once per foreleg, and it
# was drawn -- WALK_NOD dropped the skull one row on frames 1 and 3. At
# this size that is a rigid translation of the whole head-and-antlers
# block while the neck keeps its shape, which reads as jitter, not a nod:
# a real nod is a rotation the neck can't express in one row, and twice a
# stride it was frequent noise on top of legs that already read as
# walking. Removed for that reason; don't add it back for accuracy.
#
# Known and kept: the legs merge. They are 2px columns one column apart
# within a pair (near hind x 3-4, far hind 6-7; far fore 10-11, near fore
# 13-14) with lower offsets of +-2, so every crossing shares a column --
# frame 0 row 21 is one 4-wide block at x 4-7, frame 3 is x 11-14, and
# frames 1 and 2 overlap outright; 14 of the 16 gait and settle frames
# have a leg row wider than two, and audit check 56 ratchets that count.
# Three fixes were built and each was reverted at 4px, the only size
# that told the truth all evening:
#
# An even respacing to x 3, 7, 11, 15 with +-1 offsets and the far legs'
# swing clamped away from their near mate cleared every frame at 16x and
# read as insect legs at 4px -- four posts with a gap between each,
# where a deer shows two clustered pairs. A +-1 stride on the near legs
# read as a shuffle. Both reverted.
#
# Then the overlap was separated from the touching. Manning Krull, on
# sprites 24 pixels high or smaller, has overlapped legs as normal at
# this size, the near leg drawn brighter doing the separating; measured
# at 4px, a bright leg against a dim one reads as two legs in every
# shipped theme (everforest is the closest pair of tones). What does not
# read is a far leg half covered -- the near leg wins the shared column
# and the tone boundary lands inside the pair, one thick leg with a dark
# edge -- or two legs of one tone touching, dim on dim being one wide
# shape. Two rules follow: a far leg may be fully covered, never partly,
# and legs of one tone never touch. The arithmetic: pairs three columns
# apart make a crossing legal when the two offsets toward each other sum
# to 0 or 1 (a gap, a touch) or 3 (an exact cover), never 2; a strict
# no-shared-column rule would cap the total stride at 2. A table on
# straight legs satisfied both rules with a stride of three -- near hind
# +2/-1, near fore +1/-2, far legs +-1, a far leg exactly under its near
# mate in two frames -- and was clean in all four frames at 4px. Running,
# it still read as an insect, and that was the real finding: four 2px
# columns moving one at a time are what an insect looks like at this
# size, whatever is done about spacing, stride or overlap. All of that
# work was on the wrong problem.
#
# So the trot was tried for the roam, since it moves the legs as two
# diagonal pairs and the eye groups the pairs -- Krull says the same for
# small sprites, legs apart and legs together, the brain filling in four
# -- with its far legs given their own table so it met the two rules.
# Running at his speed it read as squid-like: a fast gait played slow.
# Reverted too. Both readings are real, the insect and the squid, and of
# the three the merging walk was judged the least wrong. The biomechanics
# were right throughout; what the drawing can carry at 24x24 is what
# decides.
WALK = [
    dict(d1=0, d2=1, up=1),      # swinging: lifted, coming forward
    dict(d1=1, d2=2, up=0),      # reaching, just landed
    dict(d1=0, d2=0, up=0),      # under
    dict(d1=-1, d2=-2, up=0),    # pushing off
]
WALK_PHASE = dict(nr=0, nf=1, fr=2, ff=3)
# Sprite pixels of travel per frame of each gait; four frames to a stride.
WALK_STEP, BOUND_STEP = 2.2, 3.2
# The shortest trip worth taking, in strides. One is the gait's floor --
# every foot lifts once, from any phase, since `dist` carries over -- but a
# deer that stops after his first stride reads as a hesitation, not a trip.
# Two is where a walk reads as going somewhere: 70px at the default scale.
MIN_TRIP_STRIDES = 2
# The wag: two swings, the tip on the flank for a beat and off for a beat.
WAG_SECS = 0.6
WAG_BEAT = 0.15
# The trot: two-beat, diagonal pairs in phase -- near hind with far fore --
# and the body rises a row on the pass, the legs lengthening to meet it.
# Drawn, not used: it was the roam gait from the first commit, gave way
# to the walk for accuracy on 2026-09-16, came back the same night when
# the walk read as an insect, and went again when a trot at walking
# speed read as a squid (see WALK). The far legs are the near table two
# frames on, which breaks the overlap rules at WALK -- far hind and far
# fore a shared column apart in frame 0, a dim sliver beside each near
# leg in frame 2. What met them, if it is ever wanted again: the far
# legs on their own table, the far fore stepping back one with the near
# hind in frame 0 and forward one under the near fore in frame 2, the
# far hind standing; the near legs unchanged.
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
    anyway puts four coat-colored stripes through the belly."""
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
# from the standing animal, and he has to stay recognizably the same one.
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
    # there. Walking he is level, head and all. Trotting, the
    # body rises on the pass and the legs lengthen to meet it. In a bound
    # the whole animal leaves the ground, so the legs rise with the body;
    # lifting the body alone just severs them. Lying down there is
    # nothing to bob either way.
    lift = BOUND[frame]["lift"] if bound and not (resting or settling) else 0
    bob = 0 if resting or settling else BOB[frame] if gait == "trot" else lift
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


# ------------------------------------------------------------ characters ----
# Two characters, one Pet. Everything that is not the drawing -- tips,
# context, cadence, theme following, the turn-away, idle detection, the
# roam -- is the Pet, and it never asks which character it is wearing
# beyond three facts it reads from the character: the canvas size, the
# gaits it can draw, and how far one frame of its walk travels. The
# drawing is a `pixels` function with the deer's signature. The deer's is
# pixels() above, code all the way down; The Dane's is a map, a palette of
# roles and a pose table, and a third character is the same three things.
#
# The Dane is named in honour of Omarchy's creator. Same tone as the deer:
# ordinary things done with total seriousness. Nothing goofy.
#
# The map. Each letter is a role, not a colour, so one character map can
# be worn by any theme. Skin, hair and beard are natural colours and stay
# put; the clothes, eye and chest mark come from the theme through the
# same derived tones the deer wears, so one apply_theme() recolours both
# animals. 48x48, front view, faces the viewer: the source figure, with
# the chest mark a plain letter O in the theme's accent, a two-pixel
# stroke with the corners off so it reads as a bold O and not a zero --
# generic, not the Omarchy frame. He is drawn seated behind a desk (see
# the scene), so rows 35-47 -- the standing legs and shoes -- are used
# only for the shins and shoes under the desk, and the figure's hanging
# forearms (rows 27-33) are shirt and trousers here: seated, his arms
# are drawn to the desk.
#
# A side profile and a quarter-turn frame were drawn from this map and
# are gone (2026-09-21), with the turn path between them and the
# mirroring: the scene is front-facing and stationary now, and a desk
# seen from the side mirrored to face the corner put his back to the
# room at the cost of the one thing a person at a desk shows, his face.
# What they had settled, for the record: the profile had one short brow
# over the one eye, the nose breaking the outline, the beard a band
# from the chin back and up to under the ear, the hair at collar length
# at the back; the quarter frame had the far eye's corner, the nose
# breaking the outline, the O foreshortened to four columns; the turn
# was side, lid closed, quarter, front, one TURN_SECS a step. All read
# at 2x and 4x.
DANE_FRONT = [
    "................................................",
    "..................HHHHHHhhhH....................",
    "................HHHhhhHHHhhhHH..................",
    "...............HHhhHHHHdHHHHHHH.................",
    "..............HHhHHHHddHHhhhhhH.................",
    "..............HhhHHHKKKKKKKKKKH.................",
    "..............HhHHHHKKKKKKKKKKHH................",
    "..............HHHdHHKKKKKKKKKKHH................",
    "..............HHHdHdkKHHKKHHHKHH................",
    ".............hhHHHHdkKWEKKWEKKHH................",
    ".............hHHdHHdkKKKKKKKKKHH................",
    "..............HHdHHdkKKKKKkKKKH.................",
    "..............hhHHHdkKKKKKKkkKK.................",
    "..............hHHdHdkKKRRRRRRKH.................",
    ".............HHHHdHdRRRKKkkkKRHH................",
    "............hhHHHHHdRRRKKKKKKRHH................",
    "............hHHdHHHdRRHRRRHRRRHH................",
    ".............HHdHHHHHRRRHRRRHRHH................",
    ".............hhHHHHH...kkkkk.HHHh...............",
    "...............HHH.....kKKKK..HH................",
    "................HHSSSSSkKKKKSSHH................",
    "................SSSSSSSSSSSSSSss................",
    "................FFSSSSSSSSSSSSSs................",
    "................FFSSSSAAAASSSSSS................",
    "................FFSSSAAAAAASSSSS................",
    "................FFSSSAASSAASSSSS................",
    "................FFSSSAASSAASSSSS................",
    "................SSSSSAASSAASSSSS................",
    ".................SSSSAAAAAASSSS.................",
    ".................SSSSSAAAASSSSS.................",
    ".................SSSSSSSSSSSSSS.................",
    ".................SSSSSSSSSSSSSS.................",
    ".................SSSSSSSSSSSSSS.................",
    "..................PPPPPPPPPPPP..................",
    "...................PPPPPPPPPP...................",
    "...................FFF.PPPP.....................",
    "...................FFF.PPPP.....................",
    "...................FFF.PPPP.....................",
    "...................FFF.PPPP.....................",
    "...................FFF.PPPP.....................",
    "...................FFF.PPPP.....................",
    "...................FFF.PPPP.....................",
    "...................FFF.PPPP.....................",
    "...................FFF.PPPP.....................",
    "...................FFF.PPPP.....................",
    "...................FFF.PPPP.....................",
    "..................BBBB.BBBBBB...................",
    "..................BBBB.BBBBBB...................",
]

# The fixed roles, sampled from photographs in daylight: skin from the
# forehead, its shadow from the far cheek, hair from the side, the
# beard as hair blended toward skin (stubble, not a grey beard). The two
# interior tones -- the hair's shadow, the eye's white -- never touch the
# silhouette and are never nudged.
DANE_NATURAL = {
    "K": rgb("d79a85"),   # skin
    "k": rgb("b27d6c"),   # skin shadow: neck, far arm, under the nose
    "H": rgb("5e3e2b"),   # hair
    "h": rgb("8e6644"),   # hair highlight
    "R": rgb("8a6249"),   # beard
}
DANE_INTERIOR = {
    "d": rgb("452b1e"),   # hair shadow, inside the mass and along the hairline
    "W": rgb("f2ece6"),   # eye white
}
# How close a fixed colour may sit to the theme background before it is
# nudged. The halo around him is the background, so a colour that matches
# it has no edge: dark hair on a dark theme, pale skin on a light one.
# WCAG contrast ratio, since a luminance difference is meaningless in
# the dark: 1.6 is where the edge went soft on the Tokyo Night sheet,
# 1.8 is where it was clearly there. The nudge is toward white on a dark
# background and toward black on a light one, by the least that meets
# the target, so the colour stays the colour on every theme that lets it.
NATURAL_MIN, NATURAL_TARGET = 1.6, 1.8
_natural_cache = {}


def _contrast(a, b):
    la, lb = _lum(a) + 0.05, _lum(b) + 0.05
    return la / lb if la > lb else lb / la


def natural_palette(fixed, bg):
    """`fixed` nudged away from `bg` where the two would merge."""
    key = (tuple(sorted(fixed.items())), bg)
    hit = _natural_cache.get(key)
    if hit is not None:
        return hit
    away = (1, 1, 1) if _lum(bg) < 0.5 else (0, 0, 0)
    out = {}
    for k, c in fixed.items():
        if _contrast(c, bg) < NATURAL_MIN:
            t = 0.0
            while _contrast(c, bg) < NATURAL_TARGET and t < 1.0:
                t += 0.02
                c = _blend(fixed[k], away, t)
        out[k] = c
    _natural_cache[key] = out
    return out


def dane_palette():
    """Roles to colours for the current theme. The theme roles are the
    deer's own derived tones: on Tokyo Night that is exactly the drawing's
    original palette (shirt a9b1d6, highlight c0caf5, pants 8990af, far
    limb 676c85, shoes 414868), which is why those were chosen."""
    pal = dict(natural_palette(DANE_NATURAL, OUTLINE))
    pal.update(DANE_INTERIOR)
    pal.update(S=PAL["b"], s=PAL["c"], P=PAL["a"], F=FAR, E=PAL["e"], A=PAL["e"])
    # The shoes are the hooves' tone, the theme's `muted`, and on three
    # shipped themes (rose-pine, catppuccin-latte, flexoki-light) that
    # sits close enough to the background to lose its edge. The deer's
    # standing hooves have the same exposure and nothing corrects them;
    # here the shoes get the natural colours' nudge, since a man with no
    # feet reads worse than a deer with faint hooves.
    pal["B"] = natural_palette({"B": HOOF}, OUTLINE)["B"]
    return pal


# The scene. He lives at a desk, facing you. The roam, the walk and the
# ground-sit were drawn and are gone (2026-09-21): wandering out and back
# is grazing behaviour, right for an animal, and a man doing it read as
# pacing, or a sentry on patrol -- and a man at a desk has nowhere to
# walk to. What the walk had settled, for the record: four frames,
# contact / passing / contact / passing, the lead leg straight with the
# heel down and the trailing leg bent with the heel up, the legs taking
# turns so the far leg was in front on every second step, the near arm
# swinging against the near leg, no body dip; and the sit was on the
# ground, knees up at 45 degrees, hips on the ground row, through a
# crouch. Both read at 2x and 4x. Neither is what a person at a desk
# does, so neither is kept.
#
# The turn-away, and why a front view still honours it. Swartz's finding
# is about an agent that appears to watch the user, and gaze is what
# signals watching. The deer has no gaze to speak of, so his body does
# the work: he parks facing the corner and turns to speak. The Dane has
# eyes, and while he works they are down, on the laptop -- he is not
# watching you. So the meaningful change is his eyes, not his body: eyes
# down working, eyes up to speak. The scene does not mirror when he is
# dragged; dragging moves it.
#
# Front view, canvas 56x48. From the back: the chair back, him seated
# with the desk in front of him -- a tabletop on two slim legs in the far
# tone, his legs showing beneath, seated and still: the knees coming
# toward you as two blocks over the lap, the shins and shoes below --
# the laptop open on the desk facing him, so what shows is the back of
# the lid, plain, no logo, and the mug beside it. Props take the theme
# through the same derived tones as his clothes. Speaking, he closes the
# laptop -- the lid folds down toward him over two frames -- looks up at
# you, and speaks; when the bubble clears he opens it again and his eyes
# go back down. Closing the laptop is the point: he stops what he is
# doing to address you.
#
# The states the Pet walks between working and speaking, one TURN_SECS
# each: the Pet calls them views and the deer has none. "work" is the
# lid open and the eyes down; "folding" and "closing" are the lid on its
# way, eyes still down; "speak" is the lid shut and the eyes up.
#
# There was one frame of fold, not two, and the lid went seven rows tall
# to three in a single 150ms step: at 2x that is eight screen pixels of
# laptop disappearing between two frames, and it read as a cut, not as a
# lid coming down. Two frames make the fold 7-5-3-1 and every step of it
# the same size. Watched as motion rather than as a sheet, that is the
# whole difference between a gesture and an edit.
DANE_VIEWS = ("work", "folding", "closing", "speak")
DANE_TURN = DANE_VIEWS
# Held long enough to be a position the eye lands on. At 0.15 the four
# frames of the fold ran past in six tenths of a second and read as one
# blurred move.
TURN_SECS = 0.20
# One held frame of an idle action's path in or out (see Idle). Long
# enough that the frame registers as a position and not as a smear, short
# enough that the hand is not wading: at 0.10 the mug arrived without
# ever having been anywhere, and at 0.25 he looked like he was thinking
# about it.
IDLE_STEP = 0.18
# Where the map lands in the scene: (dx, dy), and the last map row drawn
# for the body -- the desk covers the rest, and the legs are drawn from
# rows 42-47 of the map where they land.
DANE_SEAT, DANE_SEAT_ROWS = (4, 4), 34
# The eyes, and the posture that carries them. Speaking, the map's own:
# white behind, iris forward, at us. Working, the lids come down over
# that row in the skin shadow and the iris shows a row lower, looking
# down at the screen -- and that alone did not read at 2x, the working
# face looked like the speaking face. So the head tilts down a row, the
# hair with it, and the brows drop one more onto the lid row, so the
# eyes are tucked under them. That carries it. (x, y) in map coordinates.
#
# No screen glow on his face. It was drawn -- six pixels of the accent
# on the lower face and beard while the lid was up, shifting by a pixel
# or two every few seconds as screen light does -- and removed
# (2026-09-22): on a theme with a green accent it read as a rash, as
# something going wrong with him, and any coloured light on a face has
# the same problem at this size. Nothing on his face is ever the accent
# but the iris. While he works his only motion is the blink; the
# forearms are still because forearms are, when you type, and the
# fingers are behind the lid.
EYES = dict(far=((22, 9), (23, 9)), near=((26, 9), (27, 9)))       # (white, iris) per eye
HEAD_ROWS, HAIR_ROWS, TILT, BROW_DROP = 19, 22, 1, 1
BROWS = [(x, 8) for x in range(15, 33) if DANE_FRONT[8][x] == "H"]
# Props, in scene pixels. Desk: the tabletop and its two legs. Laptop: a
# lid tall enough to read at 2x, its back to us, on a base one column
# wider each side; the closing frame is the lid foreshortened, folding
# away from us toward him; closed, it is a slab. Mug: five wide, six
# tall, a handle, a row of coffee. Chair back: behind him, what shows of
# it shows around his hair.
DESK_TOP, DESK_LEGS = (34, 35, 6, 49), [(36, 47, 7, 8), (36, 47, 47, 48)]
# The lid stops below his shoulders and is narrower than they are -- a
# laptop is about three quarters of a man across -- and its rim is a
# pixel of the far tone: as wide as his shoulders with no rim it read as
# a dark shirt, not a laptop. The base is the lid's width: a keyboard is
# no wider than its screen.
LAPTOP_BASE = (33, 33, 22, 33)
LAPTOP_LID = dict(work=(26, 32, 22, 33), folding=(28, 32, 22, 33),
                  closing=(30, 32, 22, 33), speak=(32, 32, 22, 33))
MUG, MUG_HANDLE, MUG_COFFEE = (28, 33, 40, 44), [(29, 45, 46), (30, 46, 46), (31, 45, 46)], (28, 41, 43)
CHAIR = (21, 33, 20, 35)
SEATED_KNEES = [((36, 38, 22, 25), "F"), ((36, 38, 28, 32), "P")]
# The arms: from the elbows, outside the lid, the forearms angle down
# and in and go behind it, and the hands with them -- from the front
# nothing of them shows, and nothing moves. Hands were drawn first as
# wrists either side of the base and read as floating dots outside the
# lid; a keyboard is no wider than its screen, so they are behind it.
# (row, x0, x1) in scene pixels, drawn before the lid, which hides the
# rest of each band.
FOREARMS = [([(30, 35, 36), (31, 34, 35), (32, 33, 34)], "K"),
            ([(30, 20, 21), (31, 21, 22), (32, 21, 22)], "k")]
# The idle actions. Everything below moves the near forearm and nothing
# else: the far arm, the head, the eyes, the lid and the mug's own place
# on the desk are where they were. He is still working, so his eyes stay
# down through all of it.
#
# Coffee. His graze: the thing he does when nothing is happening, and the
# only reason the scene has a mug. Three held frames in and the same
# three back out -- the hand out of hiding and onto the mug, the mug up
# off the desk, twice more on the way up, the mug at his mouth -- because
# the mug crosses two thirds of the canvas and a mug that arrives at a
# face in one frame is a teleport, and because putting it back matters as
# much as lifting it: an interrupted sip reverses along the path rather
# than blinking the mug home (see Idle). Three positions were tried
# first and the mug moved eight pixels a frame, which at 2x is sixteen
# on screen: it read as three places the mug had been, not as a mug
# going up. Four makes each hop about five, and it travels.
#
# The mug is not redrawn, it is carried: (dy, dx) from where it stands,
# so its body, its handle and the row of coffee move as one thing and
# cannot drift apart. The hand is drawn after it and the forearm before
# the laptop, which is what puts the hand in front of the mug and the
# elbow behind the lid with no clipping code -- below row 26 and left of
# x 34 the lid simply covers the arm, the same way it covers his hands
# while he types.
#
# At the sip the mug sits over his mouth and the near half of his beard.
# It was drawn off to the side first, at his cheek, to keep the face
# clear: that read as a man holding a mug up beside his head, not
# drinking from it. A mug at the mouth covers the mouth; that is what
# the gesture is. Nothing of it is the accent -- the body is the belly
# tone, the coffee the far tone -- so the rule about his face holds.
COFFEE_PATH = ("reach", "lift", "carry", "sip")
# The beard stroke. The thinking gesture, and rarer than the coffee by
# about four to one: it is punctuation, and a man who strokes his beard
# every couple of minutes is not thinking, he is twitching. Two frames,
# since the hand travels half as far as the mug does and has nothing to
# carry.
BEARD_PATH = ("raise", "beard")
# (dy, dx) the mug is carried in each held frame. At the reach it has not
# left the desk yet; what has moved is the arm.
# The hops are even in height and near enough in width, and each one is
# placed so the mug's edge never lands beside a pixel of its own tone:
# the mug is the belly tone and so is the highlight down his side, and at
# (-3, -4) the two touched and became one pale shape with the laptop in
# it. Same rule as the deer's legs, same reason.
MUG_CARRY = {"reach": (0, 0), "lift": (-3, -3), "carry": (-6, -8), "sip": (-9, -13)}
# Tipped to his mouth, so the surface of the coffee is not what you see.
MUG_TIPPED = ("sip",)
# The hand, in the mug's own coordinates, so it is carried exactly as the
# handle is and grips the same part of the mug in every frame. It is the
# handle it has hold of -- the handle faces his side of the desk, which is
# the side the arm comes from -- and a hand on a handle covers it.
MUG_HAND = [(29, 44, 46), (30, 44, 46), (31, 44, 46)]
# The near forearm, by pose: the part behind the lid is drawn anyway and
# covered, so each band is the whole arm from the elbow out.
# The near forearm, by pose, elbow end first. The part behind the lid is
# drawn anyway and covered -- and so is the part behind the mug, which is
# what puts the forearm at the mug and the hand on the far side of it.
IDLE_ARM = {
    "reach": [(30, 35, 40), (31, 36, 41)],
    "lift":  [(30, 35, 38), (31, 34, 37), (32, 34, 35)],
    "carry": [(28, 34, 36), (29, 34, 36), (30, 34, 35), (31, 34, 35),
              (32, 34, 35)],
    "sip":   [(23, 32, 34), (24, 32, 34), (25, 32, 35), (26, 33, 35),
              (27, 33, 35), (28, 34, 35), (29, 34, 35), (30, 34, 35),
              (31, 34, 35), (32, 34, 35)],
    "raise": [(26, 33, 35), (27, 33, 35), (28, 34, 35), (29, 34, 35),
              (30, 34, 35), (31, 34, 35), (32, 34, 35)],
    "beard": [(23, 32, 34), (24, 31, 34), (25, 32, 35), (26, 33, 35),
              (27, 33, 35), (28, 34, 35), (29, 34, 35), (30, 34, 35),
              (31, 34, 35), (32, 34, 35)],
}
# The hand on the frames that have no mug in it: the beard stroke, where
# it is simply the end of the arm.
#
# It sits at the jaw, not on the front of the chin, and that is the whole
# of what makes the gesture legible. A hand is skin and so is a face:
# drawn across the chin it touched the skin of his lower face along four
# pixels and the two became one shape -- a man with half a beard, not a
# man with a hand on it. At the jaw it is bounded by the beard on one
# side and the hair on the other, both of them browns, and it reads as a
# hand. Dropped to the throat instead it read as a hand at his collar.
IDLE_HAND = {
    "raise": [(24, 32, 34), (25, 32, 34)],
    "beard": [(20, 31, 34), (21, 31, 34), (22, 31, 34)],
}
# Head down on folded arms, for snooze and away: the laptop closed, the
# arms crossed on the desk in front of it, the head on the arms -- the
# top of it to you, a little forehead showing under the fringe. Nothing
# of the eyes, so the deer's doze cycle has nothing to shut: it runs,
# and shows nothing. The settle frame between is the head four rows
# down with the arms coming onto the desk; a translation, not a nod, and
# at one DANE_SETTLE_SECS it reads as going down.
HEAD_DOWN = [(23, 24, 31), (24, 22, 33), (25, 21, 34), (26, 21, 34), (27, 21, 34), (28, 21, 34),
             (29, 22, 33), (30, 23, 32)]                               # (row, x0, x1) of hair
HEAD_DOWN_HIGHLIGHT, HEAD_DOWN_FACE = [(24, 25, 28), (25, 30, 32), (27, 22, 23)], [(31, 24, 31)]
ARMS_FOLDED = [((30, 31, 18, 38), "k"), ((31, 33, 16, 40), "K")]       # far under, near over
HEAD_DOWN_BODY_FROM = 20                                               # map row: shoulders, no head
# Named for him, not SETTLE_*: the deer has a SETTLE_HEAD of his own, a
# few hundred lines up, and a second one here quietly replaced it and
# moved his resting head two pixels. One file, one namespace.
DANE_SETTLE_HEAD, DANE_SETTLE_ARMS = (0, 4), [((30, 32, 15, 41), "K")]
# The settle moves him down four rows, but only the part of him that is
# above the desk: a man leaning onto a desk moves his shoulders, not his
# hips, and the lap and knees under the tabletop stay where they were.
# It used to shift all of him, and four rows was exactly enough to walk
# the bottom of the O on his chest out from behind the desk and leave two
# pixels of the accent sitting under the table between his knees. From
# this map row down he is behind the desk and does not move.
DANE_SETTLE_LAP = 28
# His settle frame is held longer than the deer's 150ms. The deer's
# settle is a small move -- the same animal, five rows down -- and 150ms
# is plenty for it. This one is the front view on its way to being the
# top of a head, and at 150ms the eye did not get to it before it was
# gone: what you saw was the man, then a shape on the desk.
DANE_SETTLE_SECS = 0.26


def _rect(out, y0, y1, x0, x1, col):
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            out.append((x, y, col))


def _dane_man(out, pal, gaze, blink, doze, rows_to=DANE_SEAT_ROWS, shift=(0, 0), rows_from=0):
    dx, dy = DANE_SEAT[0] + shift[0], DANE_SEAT[1] + shift[1]
    down = {}
    if gaze == "down":
        for white, iris in EYES.values():
            down[white] = "k"; down[iris] = "k"
            down[(iris[0], iris[1] + 1)] = "E"
        for p in BROWS:
            down[p] = "K"                  # the brow leaves its row...
        for x, y in BROWS:
            down[(x, y + BROW_DROP)] = "H"  # ...and lands on the lids
    tilt = TILT if gaze == "down" else 0
    for y, row in enumerate(DANE_FRONT[:rows_to + 1]):
        if y < rows_from:
            continue
        for x, ch in enumerate(row):
            ch = down.get((x, y), ch)
            if ch == ".":
                continue
            col = pal[ch]
            if ch in "EW" and (blink or doze):
                col = pal["k"] if doze else pal["K"]
            ty = tilt if y <= HEAD_ROWS or (y <= HAIR_ROWS and ch in "Hhd") else 0
            out.append((x + dx, y + dy + ty, col))


def _dane_legs(out, pal):
    for (y0, y1, x0, x1), role in SEATED_KNEES:
        _rect(out, y0, y1, x0, x1, pal[role])
    dx = DANE_SEAT[0]
    for y in range(39, 48):
        for x, ch in enumerate(DANE_FRONT[y]):
            if ch != ".":
                out.append((x + dx, y, pal[ch]))


def _dane_desk(out, pal, lid, pose="stand"):
    _rect(out, *DESK_TOP, pal["P"])
    for leg in DESK_LEGS:
        _rect(out, *leg, pal["F"])
    # The mug goes on before the laptop does, so the laptop covers it where
    # the two meet -- carried up past the lid it passes behind it, the
    # same way his chest does. Drawn after, four pixels of mug sat on the
    # lid's top corner and the mug was in front of a screen it is behind.
    dy, dx = MUG_CARRY.get(pose, (0, 0))
    my0, my1, mx0, mx1 = MUG
    _rect(out, my0 + dy, my1 + dy, mx0 + dx, mx1 + dx, pal["s"])
    for y, x0, x1 in MUG_HANDLE:
        _rect(out, y + dy, y + dy, x0 + dx, x1 + dx, pal["s"])
    if pose not in MUG_TIPPED:
        _rect(out, MUG_COFFEE[0] + dy, MUG_COFFEE[0] + dy,
              MUG_COFFEE[1] + dx, MUG_COFFEE[2] + dx, pal["F"])
    for y, x0, x1 in (MUG_HAND if pose in MUG_CARRY else ()):
        _rect(out, y + dy, y + dy, x0 + dx, x1 + dx, pal["K"])   # holding it, not behind it
    for y, x0, x1 in IDLE_HAND.get(pose, ()):
        _rect(out, y, y, x0, x1, pal["K"])
    _rect(out, *LAPTOP_BASE, pal["F"])
    y0, y1, x0, x1 = LAPTOP_LID[lid]
    _rect(out, y0, y1, x0, x1, pal["F"])                # the rim...
    if y1 - y0 >= 2:
        _rect(out, y0 + 1, y1, x0 + 1, x1 - 1, pal["B"])   # ...around the lid's back


def _dane_arms(out, pal, pose="stand"):
    """Both forearms. The far one never moves; the near one is at the keys
    unless an idle action has it somewhere else."""
    near = IDLE_ARM.get(pose)
    for band, role in FOREARMS:
        if near is not None and role == "K":
            band = near
        for y, x0, x1 in band:
            _rect(out, y, y, x0, x1, pal[role])


def _dane_head_down(out, pal, blink, settling):
    if settling:
        _dane_man(out, pal, "down", blink, 0, rows_to=DANE_SETTLE_LAP - 1,
                  shift=DANE_SETTLE_HEAD)
        _dane_man(out, pal, "down", blink, 0, rows_from=DANE_SETTLE_LAP)
        for (y0, y1, x0, x1), role in DANE_SETTLE_ARMS:
            _rect(out, y0, y1, x0, x1, pal[role])
        return
    _dane_man(out, pal, "down", blink, 0, rows_from=HEAD_DOWN_BODY_FROM)
    for (y0, y1, x0, x1), role in ARMS_FOLDED:
        _rect(out, y0, y1, x0, x1, pal[role])
    for y, x0, x1 in HEAD_DOWN:
        _rect(out, y, y, x0, x1, pal["H"])
    for y, x0, x1 in HEAD_DOWN_HIGHLIGHT:
        _rect(out, y, y, x0, x1, pal["h"])
    for y, x0, x1 in HEAD_DOWN_FACE:
        _rect(out, y, y, x0, x1, pal["k"])


def dane_pixels(frame, blink, pose="stand", ear=0, tail=0, gait=None, chew=0, doze=0,
                view="work", tic=0):
    """One frame of The Dane. The deer's signature plus `view` (work,
    closing, speak), so draw_sprite and the audit call either without
    knowing which. Ear, tail, chew and tic are the deer's and other
    characters' tics and do nothing here; blink and doze close the eyes.
    Drawn back to front, later pixels over earlier, as draw_sprite paints
    them."""
    pal = dane_palette()
    out = []
    resting = pose in ("rest", "settle")
    # Shut while his head is down, and shut while he is changing: he closes
    # the laptop before he becomes a deer and opens it when he comes back,
    # so he transforms as himself rather than mid-typing. "speak" is the
    # only shut lid the views have and it looks up at you, which is why
    # this is a pose and not a fifth view -- the eyes stay down.
    lid = "speak" if resting or pose == "morph" else view
    y0, y1, x0, x1 = CHAIR
    _rect(out, y0 + 1, y1, x0, x1, pal["B"])
    _rect(out, y0, y0, x0 + 1, x1 - 1, pal["B"])
    if resting:
        _dane_head_down(out, pal, blink, pose == "settle")
    else:
        # Eyes up only to speak, and changing is not speaking: without the
        # pose test a swap asked for mid-sentence would draw him looking
        # at you all the way through it.
        _dane_man(out, pal, "up" if view == "speak" and pose != "morph" else "down",
                  blink, doze)
        _dane_arms(out, pal, pose)
    _dane_legs(out, pal)
    _dane_desk(out, pal, lid, pose)
    return out


# ------------------------------------------------------------- the swap ----
# The deer is The Dane's spirit animal, and the swap should say so: not one
# sprite exchanged for another but one of them becoming the other.
#
# It used to go through the settle frame, the same held frame he uses to lie
# down, and a held frame between two different drawings is a cut with a
# pause in it. This is a dissolve instead. Every sprite pixel of a character
# has a fixed turn in [0, 1), a hash of its own coordinates; over the
# transition a threshold sweeps from 0 to 1, the one leaving keeps the
# pixels whose turn has not come, and the one arriving shows the pixels
# whose turn has passed. Nothing is ever blended: a pixel is drawn or it is
# not, which is the only way this stays pixel art. A soft cross-fade at this
# size looks like a photograph of a sprite.
#
# The two of them have different canvases and different pixel sizes and that
# is deliberately not reconciled. Each dissolves on its own grid, so the
# deer leaves in four-pixel blocks and The Dane arrives in two-pixel ones,
# and what you watch is one density turning into the other. They are
# anchored where swap() leaves them -- the ground line, and the left edge --
# so nothing moves when the dissolve finishes.
#
# The arriving character eases in and the leaving one does not. They are not
# the same weight: The Dane is 1185 pixels and the deer 206, so on a
# straight ramp a quarter of The Dane is already a head and a desk while the
# deer is still all there, and it reads as something appearing behind him
# rather than as him changing. Smoothstep holds the arrival back through the
# first third and still lands it in the last frame, with no clump of pixels
# popping in at the end. Both were drawn and watched; a ramp squared instead
# opened a hole in the middle where neither of them was there.
MORPH_SECS = 0.45
# Two salts, so the two do not take their turns in the same order. With one,
# the same corners empty and fill together and the mix reads as a wipe.
MORPH_SALT = (0x9E3779B9, 0x85EBCA6B)


def morph_grain(x, y, salt):
    """The turn this sprite pixel takes in the dissolve, in [0, 1). A hash
    rather than a table: nothing to store, nothing to seed, and the same
    scatter on every machine and every run."""
    h = (x * 0x1F1F1F1F ^ y * 0x2545F491 ^ salt) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 0x5BD1E995) & 0xFFFFFFFF
    return ((h ^ (h >> 15)) & 0xFFFF) / 65536.0


def morph_keep(pts, p, leaving):
    """The pixels of one character still drawn at progress `p`."""
    if leaving:
        return [q for q in pts if morph_grain(q[0], q[1], MORPH_SALT[0]) > p]
    t = p * p * (3.0 - 2.0 * p)                      # smoothstep; see above
    return [q for q in pts if morph_grain(q[0], q[1], MORPH_SALT[1]) <= t]


class Idle:
    """One idle action: the pose he holds, the path of held frames he goes
    into it and comes back out through -- IDLE_STEP each, the last of them
    the held pose itself -- how often it comes and how long he holds it.

    The deer's graze is one frame: his head is down or it is up, and the
    Pet has always flipped straight to it. The Dane's coffee is three --
    the hand out to the mug, the mug up off the desk, the mug at his
    mouth -- because a mug that arrives at a face in one frame is a
    teleport, and the same going back. A path of one keeps the deer's old
    behaviour exactly.

    Each action carries its own clock, which is the whole of what makes
    one rarer than another: The Dane's beard stroke comes about a
    quarter as often as his coffee, and both are far rarer than the
    deer's graze. He works; stillness at work reads as focus, and an
    office worker who fidgets every twenty seconds reads as a screensaver."""

    def __init__(self, pose, every, secs, path=None):
        self.pose = pose
        self.path = tuple(path or (pose,))
        self.every, self.secs = every, secs


class Character:
    """What the Pet reads from a character: its name for state.json, the
    label the bubble shows, its drawing, its canvas in sprite pixels and
    the screen pixels each of those takes (--scale overrides it for every
    character); whether it roams at all and whether it mirrors to face
    the way the Pet faces, the gaits it can draw, how far
    one frame of its walk travels in sprite pixels and its walking pace
    as a range in body heights a second (the deer's 46-72 px/s at 96px
    tall is 0.48-0.75); the deer's tics it uses ("tic" is a character's
    own idle motion, driven by the Pet at `tic_every`); its views and the
    path the Pet walks between them to speak, one TURN_SECS a step; and
    its idle actions -- the deer's graze, The Dane's coffee and beard
    stroke -- as Idles, each with a cadence and a path of its own; and
    how long its one settle frame is held, which is how far a character
    has to travel between standing and down: the deer drops five rows
    and pulls his head back, The Dane leaves the front view entirely and
    ends up as the top of a head on a pair of arms."""

    def __init__(self, name, label, pixels, size, scale, gaits, walk_step, pace,
                 roams=True, mirrors=True, tics=(), tic_every=(0.25, 0.5), views=(),
                 turn=(), idles=(), settle_secs=SETTLE_SECS):
        self.name, self.label, self.pixels = name, label, pixels
        self.w, self.h, self.scale = size[0], size[1], scale
        self.roams, self.mirrors = roams, mirrors
        self.gaits, self.walk_step, self.pace = gaits, walk_step, pace
        self.tics, self.tic_every, self.views, self.turn = tics, tic_every, views, turn
        self.idles = idles
        self.settle_secs = settle_secs
        self._middle = None

    def own_view(self, want=None):
        """A view this character actually has, given one that may not be
        its own. Mid-swap the Pet is still holding the other character's,
        and the deer's is "side", which is not a state a laptop has: a
        character with a fold falls back to the shut end of it, which is
        where a swap leaves it, and anything else to its first."""
        if not self.views:
            return None
        if want in self.views:
            return want
        return self.turn[-2] if len(self.turn) >= 2 else self.views[0]

    def middle(self):
        """Where the drawing's weight sits across its canvas, in sprite
        pixels from the left edge -- the mean of every pixel it puts down
        standing still.

        A canvas is not a character. The deer fills his: 24 wide, ink from
        0 to 23, weight at 11.6. The Dane's canvas is 56 wide and his desk
        only occupies 6 to 49, so his weight is at 28.0 -- and at 2px
        against the deer's 4px that is 56 screen pixels from the left edge
        against the deer's 46. Line the two canvases up by their left edges
        and the visible mass jumps ten pixels sideways, which is what the
        swap used to do. Line them up by this instead and it does not.

        Measured once, from the standing frame, and kept: an idle action or
        a lowered head moves the weight a little and the anchor must not
        move with it."""
        if self._middle is None:
            view = self.own_view(self.views[0] if self.views else None)
            pts = self.pixels(1, False, "stand", **({"view": view} if view else {}))
            self._middle = sum(x for x, _, _ in pts) / float(len(pts)) + 0.5
        return self._middle


SPRITES = {
    "yoru": Character("yoru", "Yoru", pixels, (SW, SH), 4, ("walk", "bound"),
                      WALK_STEP, (46 / 96, 72 / 96), tics=("ear", "tail", "chew"),
                      idles=(Idle("graze", every=(25, 70), secs=(4, 11)),)),
    # He does not roam and does not mirror: a man at a desk has nowhere
    # to walk to, and the desk faces you (see the scene). No tic: working,
    # his only motion is the blink, and his two idle actions are minutes
    # apart (see COFFEE and BEARD for what each is and why it is as rare
    # as it is).
    "dane": Character("dane", "The Dane", dane_pixels, (56, 48), 2, (),
                      WALK_STEP, (46 / 96, 72 / 96), roams=False, mirrors=False,
                      views=DANE_VIEWS, turn=DANE_TURN,
                      idles=(Idle("sip", every=(150, 400), secs=(1.8, 2.8),
                                  path=COFFEE_PATH),
                             Idle("beard", every=(700, 1600), secs=(1.0, 1.6),
                                  path=BEARD_PATH)),
                      settle_secs=DANE_SETTLE_SECS),
}
DEFAULT_SPRITE = "yoru"

# The swap: SIGUSR2, the way hiding is SIGUSR1. The signal only asks; the
# Pet does the change on its next step, through the settle frame, so it
# can never land in the middle of a frame or skip the one frame the user
# is watching for.
_on_swap = []


def request_swap(*_):
    debug("swap: requested (SIGUSR2)")
    for fn in _on_swap:
        fn()
    return True                 # keep the signal watch installed


def sprite_choice(flag=None):
    """Which character to start as: the flag if given (and it is saved),
    else the saved choice, else the deer."""
    st = read_state()
    if flag:
        if st.get("sprite") != flag:
            st["sprite"] = flag
            save_json(STATE, st)
        return flag
    saved = st.get("sprite")
    return saved if saved in SPRITES else DEFAULT_SPRITE


def cmd_swap():
    """`yoru --swap`: SIGUSR2 to the running instance, found by the exact
    path this binary was run as -- the same pattern the Hyprland bind
    uses -- and never to this process, whose own command line matches."""
    me = os.path.abspath(sys.argv[0])
    pattern = "python3 %s( |$)" % re.escape(me)
    r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    pids = [int(p) for p in r.stdout.split() if int(p) != os.getpid()]
    if not pids:
        print("yoru: not running (looked for %s)" % me, file=sys.stderr)
        return 1
    for pid in pids:
        os.kill(pid, signal.SIGUSR2)
    return 0


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
    ("windows", None, "Super + K", "Every keybinding at once. Alt + K for tmux, Ctrl + K for Herdr. Nobody memorizes all of them."),
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
    ("windows", None, "Alt + Tab", "Cycle windows here. Ctrl + Alt + Tab cycles monitors. Old habits, honored."),
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
    ("capture", None, "Super + Print Screen", "Color picker. The value goes to the clipboard and nowhere else."),
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
    ("cli", TERM, "omarchy", "The command center. Run it bare to see every group. It will not judge you for looking."),
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
    """(mods, KEY) the way the verifier normalizes, or None if it isn't a
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
    headline = {}                   # normalized key -> curated tip
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
        self._scale = getattr(opts, "scale", None)      # --scale, or None
        self.interval = opts.interval
        self.quiet = getattr(opts, "quiet", False)
        self.roam = opts.roam
        self.margin = opts.margin
        self.corner = opts.corner

        # Which character he is. The Pet is the same either way; the
        # drawing, the canvas and the gaits are read from this. A swap
        # asked for by SIGUSR2 waits here until step() takes it through
        # the settle frame.
        self.character = SPRITES[getattr(opts, "sprite", None) or DEFAULT_SPRITE]
        self.swap_to = None
        # Mid-swap: the character he is turning into, and what the dissolve
        # has left. Both of them are drawn while this is set (see the swap).
        self.morph = None
        self.morph_for = 0.0
        # Which way he faces, for a character with views: side by default,
        # front while he speaks, the steps of the character's turn path
        # held TURN_SECS each between. And the character's own idle
        # motion -- The Dane's typing hand -- a bit the Pet flips on its
        # own jittered clock while he is parked and idle.
        self.view = self.character.turn[0] if self.character.turn else "side"
        self.turn_for = 0.0
        self.tic = 0
        self.next_tic = 0.0

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

        # Which way the open ground lies from home: away from the nearer of
        # the left and right edges. He walks into it, and parks facing the
        # other way -- into the corner, his back to the room. One fact, set
        # where home is set -- place, refit, drag -- and read from.
        self.open = -1
        self.dir = -self.open
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
        # The idle actions (see Idle): the one running, how far along its
        # path he is, what that frame has left, what the held pose has
        # left, and one clock per action -- which is what lets The Dane's
        # beard stroke be rarer than his coffee.
        self.idle = None
        self.idle_step = -1
        self.idle_hold = 0.0
        self.idle_for = 0.0
        self.next_idle = self.fresh_idles()
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
        # the all-clear, and it is what an idle deer does; `tail` times it.
        # The flag is the alarm: danger is here, and a fleeing deer keeps
        # it up for the whole flight, so it is simply the bound, for as
        # long as the bound lasts. tail_frame() says which is drawn.
        self.tail = 0.0
        self.next_tail = random.uniform(8, 20)
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
    def px(self):
        return self._scale or self.character.scale

    @property
    def w(self):
        return self.character.w * self.px

    @property
    def h(self):
        return self.character.h * self.px

    def px_of(self, ch):
        """Screen pixels per sprite pixel for a character that is not
        necessarily the one he is: --scale still overrides every one."""
        return self._scale or ch.scale

    def middle_of(self, ch):
        """Where that character's weight sits, in screen pixels from his x."""
        return ch.middle() * self.px_of(ch)

    def morph_shift(self):
        """How far the character arriving is drawn from the one leaving, so
        the two of them share a centre through the dissolve and the arriving
        one is already standing where it will end up."""
        if self.morph is None:
            return 0.0
        return self.middle_of(self.character) - self.middle_of(self.morph)

    def morph_progress(self):
        """0 at the first frame of the dissolve, 1 at the last."""
        if self.morph is None:
            return 0.0
        return min(1.0, max(0.0, 1.0 - self.morph_for / MORPH_SECS))

    def bounds(self):
        """The box the input region follows. Mid-swap it is both of them:
        the two footprints differ, and a character half-drawn outside the
        region is a character you cannot drag."""
        if self.morph is None:
            return int(self.x), int(self.y), int(self.w), int(self.h)
        px, dx = self.px_of(self.morph), self.morph_shift()
        left = min(0.0, dx)
        right = max(self.w, dx + self.morph.w * px)
        h = max(self.h, self.morph.h * px)
        return (int(self.x + left), int(self.y + self.h - h),
                int(right - left), int(h))

    # -- idle actions ------------------------------------------------------
    def fresh_idles(self):
        """A clock per idle action the character has, started at a random
        point in its own range so two actions never come due together on
        the first pass."""
        return [random.uniform(*a.every) for a in self.character.idles]

    def idling(self):
        return self.idle is not None

    def drop_idle(self):
        """Ask whatever idle action is running to come back out. One held
        frame deep -- the deer's graze, always -- it is simply over, which
        is what the graze has always done when he has something to say;
        deeper in, step() walks him back out along the path a frame at a
        time, so the mug goes back on the desk rather than vanishing."""
        if self.idle is None:
            return
        self.idle_for = 0.0
        if self.idle_step <= 0:
            self.idle, self.idle_step, self.idle_hold = None, -1, 0.0
            if self.pose not in ("rest", "settle"):
                self.pose = "stand"

    # -- the swap ---------------------------------------------------------
    def request_swap(self, name=None):
        """Ask for the next character (or `name`). Taken in step(), through
        the settle frame; asked twice before that, the second ask wins."""
        order = list(SPRITES)
        if name is None:
            name = order[(order.index(self.character.name) + 1) % len(order)]
        if name not in SPRITES:
            debug("swap: no character called %r", name)
            return
        self.swap_to = name
        debug("swap: %s -> %s, waiting for the settle", self.character.name, name)

    def swap(self, width, height, into=None):
        """Become the character the dissolve has been drawing, keeping the
        spot, the facing and everything else. A second ask that arrived
        during the dissolve is left standing, so it takes effect on the
        next step.

        "The spot" is where he looks like he is, not where his canvas
        starts. Two characters may differ in height, so the feet stay on
        the ground line and the top moves; they may differ in width and in
        where their weight sits across it, so the weight stays put and the
        canvas edge moves (see Character.middle). Holding the edge instead
        slid the visible mass ten pixels sideways every swap."""
        was, was_h, was_mid = self.character, self.h, self.middle_of(self.character)
        self.character = into or SPRITES[self.swap_to]
        if self.swap_to == self.character.name:
            self.swap_to = None
        # He arrives with the laptop still shut, where the dissolve left it,
        # and opens it through the fold -- one frame at a time, the way he
        # closed it. Landing on turn[0] instead would snap it open.
        turn = self.character.turn
        self.view = turn[max(0, len(turn) - 2)] if turn else "side"
        self.turn_for = TURN_SECS
        # A deer's graze is not a man's coffee: the clocks start again on
        # the character he has become, and nothing is mid-path.
        self.idle, self.idle_step, self.idle_hold, self.idle_for = None, -1, 0.0, 0.0
        self.next_idle = self.fresh_idles()
        dh = was_h - self.h                 # canvas and scale may both differ
        dx = was_mid - self.middle_of(self.character)
        self.x += dx
        self.y += dh
        if self.home_y is not None:
            self.home_x += dx
            self.home_y += dh
            self.clamp_home(width, height)
        # Both, not just the vertical: dragged hard against the right edge
        # the wider character used to run off it, and home_x was clamped
        # while x was not, so he jumped sideways the next time anything
        # read home.
        self.x = max(4, min(self.x, width - self.w - 4))
        self.y = max(4, min(self.y, height - self.h))
        st = read_state()
        st["sprite"] = self.character.name
        save_json(STATE, st)
        debug("swap: now %s at (%d,%d) facing %s, saved", self.character.name,
              self.x, self.y, "right" if self.dir > 0 else "left")

    def place(self, width, height):
        saved = load_home()
        if saved:
            self.home_x, self.home_y = saved
        else:
            # The bottom of the surface is the ground: hooves land on the
            # sprite's last row, so that row sits on the screen edge (or on
            # the bar, if the bar is at the bottom -- the compositor shrinks
            # the surface around it). --margin is the gap from the side. The
            # top corners have no ground under them; there he keeps the
            # margin below the bar, standing on the shelf he always did.
            m = self.margin
            right = self.corner in ("br", "tr")
            bottom = self.corner in ("br", "bl")
            self.home_x = (width - self.w - m) if right else m
            self.home_y = (height - self.h) if bottom else m
        self.clamp_home(width, height)
        self.x, self.y = self.home_x, self.home_y
        self.face_open(width)
        self.size = (width, height)
        self.placed = True

    def room(self, width, side):
        """Pixels between home and the edge on `side` (-1 left, 1 right)."""
        return (self.home_x - 4) if side < 0 else (width - self.w - 4) - self.home_x

    def face_open(self, width):
        """Point `open` away from the nearer edge, and face him the other
        way, into it. Facing the room reads as watching the user work,
        which is the thing the turn-away exists to avoid; facing out of the
        corner reads as turned away. He turns to walk into the open and
        turns back when he parks, which is what an animal does: it moves
        facing the open and settles facing its cover. Within a body width
        of equidistant he keeps the way he last faced: a deer parked at
        the bottom center must not flip on a pixel of drag."""
        left, right = self.room(width, -1), self.room(width, 1)
        if abs(left - right) >= self.w:
            self.open = 1 if left < right else -1
        self.dir = -self.open

    def clamp_home(self, width, height):
        self.home_x = max(4, min(self.home_x, width - self.w - 4))
        self.home_y = max(4, min(self.home_y, height - self.h))

    def refit(self, width, height):
        """The surface changed size under him — a monitor was unplugged and
        the compositor moved him to a smaller one, or a bigger one arrived.
        A spot that was on-screen may not be now, and off-screen means
        invisible *and* undraggable, since the input region follows him.
        Pull home and his current position back inside the new bounds."""
        was = (self.home_x, self.home_y, self.x, self.y)
        self.clamp_home(width, height)
        self.x = max(4, min(self.x, width - self.w - 4))
        self.y = max(4, min(self.y, height - self.h))
        if self.mode in ("out", "back"):
            self.target = max(4, min(self.target, width - self.w - 4))
        self.face_open(width)           # the other side may be the near one now
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
        # Mid-coffee he puts the mug down first, one frame at a time,
        # because step() sees the text and reverses the path.
        self.drop_idle()
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

        if self.text and now > self.text_until:
            self.head = self.text = None

        # Does he want to be lying down? Snoozed or nobody here, parked,
        # nothing to say, nothing rousing him, and not in the middle of an
        # idle action -- mid-coffee he finishes putting the mug down
        # first, because a head that drops while the hand is still at the
        # chin is two motions at once.
        sleepy = ((self.snoozing(now) or not self.present(now))
                  and self.mode == "home" and not self.text
                  and self.pause <= 0 and not self.rouse and self.idle is None)
        # A swap that has been asked for and has nothing in its way. It
        # outranks the snooze -- he stands up to change -- and it outranks
        # the bubble, so the laptop shuts and he turns away from you for
        # the half second it takes, which is what asking to swap means.
        swapping = (self.swap_to is not None and not self.moving()
                    and self.mode != "drag")
        sleepy = sleepy and not swapping

        # The turn. A character with views faces the viewer to speak and
        # turns back when the bubble clears, one step along its turn path
        # per TURN_SECS -- The Dane folds the laptop down over two frames,
        # then front, and the same path back. A character without views is
        # drawn from the side whatever this says. A want that flips
        # mid-turn simply reverses along the path from wherever he is.
        #
        # Going to sleep walks the same path, but stops one short of the
        # end: the last state is the one where he looks up at you, and he
        # is not looking at anybody, he is putting his head down. One
        # short is the lid shut and the eyes still down, which is exactly
        # what the head-down frames want behind them. Before this the lid
        # went from fully open to a slab in the single frame the head
        # dropped -- three things moving at once, in 150ms, and the laptop
        # simply vanished.
        path = self.character.turn
        want_view = "side"
        if path:
            want_view = path[-2] if (swapping or sleepy
                                     or self.pose in ("rest", "settle", "morph")) \
                else path[-1] if self.text else path[0]
        # The clock runs on the frame he arrives at too, not only on the
        # ones he is passing through: the state he stops in is a held
        # frame like the others, and the settle below waits for it. Zeroed
        # on arrival instead, the lid reached "closing" and the head went
        # down in the same frame, so the drawing went from a lid five rows
        # tall to a shut one with nothing in between.
        self.turn_for -= dt
        if path and self.view != want_view and self.turn_for <= 0:
            i, j = path.index(self.view), path.index(want_view)
            self.view = path[i + (1 if j > i else -1)]
            self.turn_for = TURN_SECS

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
        # He waits for the laptop to be shut before he goes down, which is
        # what the `view` test is: a character with no views is never held
        # up by it.
        want = "rest" if (sleepy and (not path or (self.view == want_view
                                                   and self.turn_for <= 0))) else "stand"
        if self.pose == "morph":
            # The dissolve. Both of him are drawn from here; when it runs
            # out he is the other one, standing, with the laptop shut and
            # the fold still to open.
            self.morph_for -= dt
            if self.morph_for <= 0:
                self.pose = "stand"
                self.swap(width, height, into=self.morph)
                self.morph, self.morph_for = None, 0.0
        elif self.pose == "settle":
            self.settle_to = want
            self.settle_for -= dt
            if self.settle_for <= 0:
                self.pose = want
                if want == "stand":
                    # Coming up, the view he lands in gets a full turn of
                    # its own before the lid starts opening: he sits up,
                    # and then he opens the laptop. Only coming up -- give
                    # it to him going down too and the clock the settle is
                    # waiting on restarts the moment he reaches the floor,
                    # and he sits up and lies down for ever.
                    self.turn_for = TURN_SECS
                if self.swap_to:
                    self.swap(width, height)
        elif want == "rest" and self.pose != "rest":
            self.pose, self.settle_to, self.settle_for = "settle", "rest", self.character.settle_secs
            self.drop_idle()
        elif want == "stand" and self.pose == "rest":
            self.pose, self.settle_to, self.settle_for = "settle", "stand", self.character.settle_secs
        # And the dissolve starts once he is standing, done with whatever
        # he was doing, and -- if he has a laptop -- has shut it. Mid-walk,
        # mid-drag or mid-graze it simply waits; nothing about the swap is
        # lost by waiting, since the ask is held in swap_to.
        # swap_to is read again rather than trusting `swapping`: the block
        # above may have just finished a dissolve and cleared it, and on
        # that frame he is standing and would otherwise start another.
        if (swapping and self.swap_to is not None and self.pose == "stand"
                and (not path or (self.view == want_view and self.turn_for <= 0))):
            self.morph, self.morph_for, self.pose = SPRITES[self.swap_to], MORPH_SECS, "morph"
            debug("swap: %s -> %s, dissolving for %.2fs",
                  self.character.name, self.morph.name, MORPH_SECS)
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
        self.next_tail -= dt
        if self.next_tail <= 0:
            self.tail = WAG_SECS
            self.next_tail = random.uniform(9, 25) * (2 if resting else 1)

        # The idle actions. He only starts one settled, parked and quiet --
        # never mid-sentence, never while walking somewhere, never once
        # he's been told to hush or the chair is empty. Each action has
        # its own clock, and only one runs at a time; an action that comes
        # due while another is out simply waits for its next turn rather
        # than queueing, so two of them can never stack up into a routine.
        #
        # Getting in and out is a path of held frames, IDLE_STEP each (see
        # Idle). Anything that wants him back reverses it from wherever he
        # is -- it does not cut -- which is the whole reason the mug ever
        # gets put down. A one-frame path, which is all the deer's graze
        # is, goes in and comes out in the frame it is asked to, exactly
        # as the graze always did.
        if self.pose not in ("rest", "settle", "morph"):
            free = (self.mode == "home" and not self.text and self.pause <= 0
                    and not self.still and not self.snoozing(now)
                    and self.present(now) and not swapping)
            if self.idle is None and free:
                for i, act in enumerate(self.character.idles):
                    self.next_idle[i] -= dt
                    if self.next_idle[i] <= 0:
                        self.next_idle[i] = random.uniform(*act.every)
                        if self.idle is None:
                            self.idle, self.idle_step, self.idle_hold = act, -1, 0.0
                            self.idle_for = random.uniform(*act.secs)
            if self.idle is not None:
                top = len(self.idle.path) - 1
                if self.idle_step == top and free:
                    self.idle_for -= dt
                want_step = top if (free and self.idle_for > 0) else -1
                self.idle_hold -= dt
                if self.idle_step != want_step and self.idle_hold <= 0:
                    self.idle_step += 1 if want_step > self.idle_step else -1
                    # The held frame is timed by the action, the rest of
                    # the path by IDLE_STEP.
                    self.idle_hold = 0.0 if self.idle_step == top else IDLE_STEP
                self.pose = self.idle.path[self.idle_step] if self.idle_step >= 0 else "stand"
                if self.idle_step < 0:
                    self.idle = None

        # A character's own idle motion, while he is parked and at it --
        # neither shipped character declares one; the deer has his ear,
        # tail and cud, The Dane only his blink. Flipped on a jittered
        # clock so it never reads as a metronome; still while he speaks
        # or rests.
        if "tic" in self.character.tics and self.pose == "stand" and (not path or self.view == path[0]):
            self.next_tic -= dt
            if self.next_tic <= 0:
                self.tic = 1 - self.tic
                self.next_tic = random.uniform(*self.character.tic_every)

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
            # Idle, into the corner. Speaking, he turns toward the middle
            # of the screen, where the user's attention is.
            self.dir = self.open if self.text else -self.open

        if self.mode == "drag":
            return
        if self.pause > 0:
            self.pause -= dt
            return

        if self.mode == "home":
            if self.still or not self.character.roams:
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
                    self.drop_idle()
                    return
                # He turns and walks into the open ground, away from the
                # nearer edge, as far as that side holds. Home is
                # usually against an edge, and a draw symmetric about it
                # clamped to the surface made half his walks a 20px shuffle
                # -- a truncated cycle. With no room
                # for a trip on the open side there is less on the other,
                # so he skips this one and tries again later.
                span = min(width * 0.45, 520)
                room = self.room(width, self.open)
                if room < self.min_trip():
                    self.next_roam = random.uniform(self.roam * 0.7, self.roam * 1.6)
                    debug("roam: no room for a trip (%dpx open, need %d); later",
                          room, self.min_trip())
                    return
                self.target = self.home_x + self.open * random.uniform(
                    self.min_trip(), min(span, room))
                # A walk only moves x. If y is off the surface he would walk
                # past unseen, so bring it in before he sets off.
                self.y = max(4, min(self.y, height - self.h))
                # One trip in five he spooks himself and bounds it, tail up
                # -- the deer does; a character with no bound walks them all.
                if "bound" in self.character.gaits and random.random() < 0.2:
                    self.speed = 150.0
                else:
                    self.speed = self.walk_speed()
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
                if "bound" in self.character.gaits and random.random() < 0.2:
                    self.speed = 150.0
                else:
                    self.speed = self.walk_speed()
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
            if self.idle is not None and self.pose == self.idle.pose:
                why = " for %.1fs" % self.idle_for
            elif self.idle is not None:
                why = " (%s %s)" % ("into" if self.idle_for > 0 else "out of",
                                    self.idle.pose)
            elif self.pose == "morph":
                why = " -> %s over %.2fs" % (self.morph.name, MORPH_SECS)
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
        and that is a walk. The trot is drawn but not used: tried for the
        roam and reverted, see WALK."""
        if not self.moving():
            return None
        return "bound" if self.speed > 120 else "walk"

    def tail_frame(self):
        """2 for the flag, which is the whole of a bound; 1 for the wag's
        tip-on-the-flank half, alternating every WAG_BEAT for two swings
        side to side; else 0. A bolting deer never wags."""
        if self.bounding():
            return 2
        if self.tail > 0 and int((WAG_SECS - self.tail) / WAG_BEAT) % 2 == 0:
            return 1
        return 0

    def render_key(self):
        """Everything a frame depends on. Two equal keys draw the same
        pixels, so a frame whose key hasn't moved needn't be drawn at all —
        and between a blink, an ear and a tail, most frames haven't."""
        # Position first and character last: tick() reads both to know
        # when the input region must follow him or change size.
        tics = self.character.tics
        return (int(self.x), int(self.y), self.dir, self.frame(), self.pose,
                self.blink > 0, "ear" in tics and self.ear > 0,
                self.tail_frame() if "tail" in tics else 0, self.gait(),
                self.chew if "chew" in tics else 0, self.doze,
                self.head, self.text,
                self.view if self.character.views else "-",
                self.tic if "tic" in tics else 0,
                # The dissolve moves every frame, so the key does too and
                # none of it is skipped. The name stays last and carries
                # the morph with it: it changes exactly when the pair of
                # footprints does, which is when the input region must.
                int(self.morph_progress() * 255),
                self.character.name if self.morph is None
                else "%s>%s" % (self.character.name, self.morph.name))

    def min_trip(self):
        return MIN_TRIP_STRIDES * 4 * self.character.walk_step * self.px

    def walk_speed(self):
        """Screen pixels a second for a walk: the character's pace, in body
        heights a second, times his height on screen -- so he covers the
        same share of himself a second at any scale. The deer's is the
        46-72 px/s he always had."""
        return random.uniform(*self.character.pace) * self.h

    def frame(self):
        if not self.moving():
            return 1
        step = self.px * (BOUND_STEP if self.bounding() else self.character.walk_step)
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
    p.add_argument("--scale", type=int, default=None,
                   help="screen pixels per sprite pixel, for every character "
                        "(default: each character's own -- the deer 4, The Dane 2)")
    p.add_argument("--corner", default="br", choices=["br", "bl", "tr", "tl"],
                   help="where he parks on first run (default bottom right)")
    p.add_argument("--margin", type=int, default=24,
                   help="gap from the side of the screen; the bottom is the ground, so "
                        "the bottom corners have none (the top corners keep it, below the bar)")
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
                   help="never walk, bound, graze or reach for the coffee; "
                        "he only blinks and talks")
    p.add_argument("--sprite", choices=sorted(SPRITES),
                   help="which character: yoru (the deer, default) or dane; "
                        "remembered, so it survives a restart")
    p.add_argument("--swap", action="store_true",
                   help="swap the running instance's character (SIGUSR2) and exit")
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
    if opts.swap:
        return cmd_swap()
    opts.sprite = sprite_choice(opts.sprite)
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


def sprite_pixels(pet, ch):
    """One character's pixels for this frame -- the one he is, or the one
    he is turning into. A character is only ever handed a view of its own:
    mid-swap the Pet is still holding the other one's, and the deer's is
    "side", which is not a state a laptop has."""
    extra = {}
    view = ch.own_view(pet.view)
    if view:
        extra["view"] = view
    if "tic" in ch.tics:
        extra["tic"] = pet.tic
    return ch.pixels(pet.frame(), pet.blink > 0, pet.pose,
                     1 if pet.ear > 0 else 0, pet.tail_frame(),
                     pet.gait(), pet.chew, pet.doze, **extra)


def paint_sprite(cr, pet, ch, oy, pts, ox=0.0):
    px = pet.px_of(ch)
    flip = pet.dir < 0 and ch.mirrors        # a character that doesn't mirror ignores the facing

    def sx(x):
        return pet.x + ox + ((ch.w - 1 - x) if flip else x) * px

    cr.set_source_rgba(*OUTLINE, 0.85)
    for x, y, _ in pts:
        cr.rectangle(sx(x) - 1, oy + y * px - 1, px + 2, px + 2)
    cr.fill()
    for x, y, col in pts:
        cr.set_source_rgb(*col)
        cr.rectangle(sx(x), oy + y * px, px, px)
        cr.fill()


def draw_sprite(cr, pet, oy):
    """One character, or -- for the half second of a swap -- both of them,
    each dissolving on its own grid (see the swap). The halo rings go down
    for both before either one's pixels do, so a ring can never land on top
    of a pixel of the other."""
    ch = pet.character
    if pet.morph is None:
        paint_sprite(cr, pet, ch, oy, sprite_pixels(pet, ch))
        return
    p = pet.morph_progress()
    into = pet.morph
    # The two are anchored on the ground line and on their shared weight,
    # so the one arriving is already standing where it will be left and
    # neither of them moves at any point in the dissolve.
    into_oy = oy + pet.h - into.h * pet.px_of(into)
    into_ox = pet.morph_shift()
    for c, o, dx, pts in ((ch, oy, 0.0, morph_keep(sprite_pixels(pet, ch), p, True)),
                          (into, into_oy, into_ox,
                           morph_keep(sprite_pixels(pet, into), p, False))):
        paint_sprite(cr, pet, c, o, pts, dx)


def draw_bubble(cr, pet, oy, width):
    esc = GLib.markup_escape_text
    markup = ('<span foreground="%s">%s</span>\n%s'
              % (ACCENT_HEX, esc(pet.head or pet.character.label), esc(pet.text)))

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
            _on_swap.append(self.pet.request_swap)
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
            pet.y = max(4, min(self._grab[1] + dy, h - pet.h))

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
            pet.face_open(self.area.get_width())
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
            self.pet.say(self.pet.character.label,
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
            if (self._key is None or key[:2] != self._key[:2]
                    or key[-1] != self._key[-1]):     # moved, or a new canvas
                surface = self.win.get_surface()
                if surface is not None:
                    # The input region follows him, and nothing else. Hidden
                    # is handled in set_visible: an empty region hands every
                    # click to whatever is underneath, not to an invisible deer.
                    surface.set_input_region(cairo.Region(
                        cairo.RectangleInt(*self.pet.bounds())))
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
              "introduced %s | home %s | %s | as %s", len(tips), len(load_seen()),
              len(load_known()), st.get("shown", 0), st.get("passes", 0),
              bool(st.get("introduced")),
              load_home() or "default %s" % opts.corner, CONFIG, opts.sprite)
    # Dispatched from the main loop, not from inside the signal handler, so
    # the flip can never land in the middle of a frame.
    add = GLibUnix.signal_add if GLibUnix else GLib.unix_signal_add
    add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, toggle_visible)
    add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, request_swap)
    return build_app(opts, tips).run([])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        os._exit(0)
    except KeyboardInterrupt:
        os._exit(0)
