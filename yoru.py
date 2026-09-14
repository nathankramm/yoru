#!/usr/bin/env python3
"""
yoru — a Clippy for Omarchy, minus the reasons everyone hated Clippy.

A pixel deer parks in a corner of your screen and tells you things from the
Omarchy 4 (Quattro) manual. He knows the desktop, the CLI, the coding agents,
the shell tools, tmux, Herdr, Foot, Neovim, lazygit, lazydocker, btop, the file
manager, browsers and updates — and he notices which of those you are in.

Where he sits
    Bottom right by default, 24px off each edge. Drag him anywhere with the
    left mouse button and he stays there; the spot is saved to
    ~/.config/yoru/state.json and survives a reboot.

What he does
    Ambient  — a tip every few minutes, never twice until he's run out.
    Contextual — when you focus a new app he offers something for that app,
                 at most twice per app per session, never inside the cooldown.
    On demand  — right click for the next tip, middle click to snooze an hour.

Deps (Arch / Omarchy)
    sudo pacman -S --needed python-gobject gtk4 gtk4-layer-shell python-cairo

Run
    python3 yoru.py
    python3 yoru.py --corner bl --scale 5 --interval 240 --topics nvim,tmux
    python3 yoru.py --ask screenshot        # search his knowledge, print, exit
    python3 yoru.py --list                  # everything he knows

Your own tips
    ~/.config/yoru/tips.txt — one per line, "Super + Y | what it does".
    Lines with no pipe become idle remarks.
"""

import argparse
import datetime
import json
import os
import random
import signal
import subprocess
import sys

CONFIG = os.path.expanduser("~/.config/yoru")
STATE = os.path.join(CONFIG, "state.json")
SEEN = os.path.join(CONFIG, "seen.json")
KNOWN = os.path.join(CONFIG, "known.json")
USER_TIPS = os.path.join(CONFIG, "tips.txt")

# Hidden is not dead. SIGUSR1 flips this and the process carries on stepping,
# so his spot, his snooze and what he has and hasn't said all survive a
# "get out of the way for a minute". Compare pkill, which would reset all
# of it and replay the intro.
visible = True


def toggle_visible(*_):
    global visible
    visible = not visible
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

THEME_COLORS = os.path.expanduser("~/.local/state/omarchy/current/theme/colors.toml")
THEME_NAME = os.path.expanduser("~/.local/state/omarchy/current/theme.name")


def _blend(a, b, t):
    """Mix two rgb triples; t=0 is all a."""
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


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
    global PAL, FAR, FAR_HOOF, HOOF, OUTLINE, BUBBLE_BG, ACCENT_HEX
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

    def lum(c):
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

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
    OUTLINE = bg
    BUBBLE_BG = col("dark_background", "background") or bg
    ACCENT_HEX = "#%02x%02x%02x" % tuple(round(c * 255) for c in accent)
    return True


def theme_stamp():
    """Cheap change-detector for the active theme."""
    try:
        return (os.path.getmtime(THEME_COLORS), os.path.getmtime(THEME_NAME))
    except OSError:
        try:
            return (os.path.getmtime(THEME_COLORS),)
        except OSError:
            return None


GAIT = [
    dict(r1=0, r2=-1, f1=1, f2=2),
    dict(r1=0, r2=0, f1=0, f2=0),
    dict(r1=0, r2=1, f1=0, f2=-2),
    dict(r1=0, r2=0, f1=0, f2=0),
]
BOB = [0, -1, 0, -1]


def _leg(out, ax, d1, d2, col, hoof):
    for y in range(18, 21):
        for i in range(2):
            out.append((ax + d1 + i, y, col))
    for y in range(21, 23):
        for i in range(2):
            out.append((ax + d2 + i, y, col))
    for i in range(2):
        out.append((ax + d2 + i, 23, hoof))


def pixels(frame, blink):
    out = []
    near, far = GAIT[frame], GAIT[(frame + 2) % 4]
    _leg(out, 6, far["r1"], far["r2"], FAR, FAR_HOOF)
    _leg(out, 10, far["f1"], far["f2"], FAR, FAR_HOOF)
    bob = BOB[frame]
    for y, row in enumerate(BODY):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            out.append((x, y + bob, PAL["b"] if (ch == "e" and blink) else PAL[ch]))
    _leg(out, 3, near["r1"], near["r2"], PAL["b"], HOOF)
    _leg(out, 13, near["f1"], near["f2"], PAL["b"], HOOF)
    return out


# ------------------------------------------------------------- knowledge ----
TERM = ("foot", "alacritty", "ghostty", "kitty", "wezterm")
NVIM = ("nvim", "neovim", "lazyvim")
WEB = ("chromium", "chrome", "brave", "firefox", "zen")
# Quattro gives a launched agent its own window class.
AGENT = TERM + ("org.omarchy.agent", "opencode", "claude", "codex", "crush")

# Every entry below was checked against the Omarchy 4 (Quattro) manual.
KNOWLEDGE = [
    # ---------------------------------------------------------- windows ----
    ("windows", None, "Super + K", "Every keybinding, all at once. Alt + K for tmux, Ctrl + K for Herdr."),
    ("windows", None, "Super + Space", "The Omarchy menu. Almost everything starts here."),
    ("windows", None, "Super + Alt + Space", "The apps menu, for when you already know what you want."),
    ("windows", None, "Super + Escape", "System menu. Suspend, restart, relaunch Hyprland."),
    ("windows", None, "Super + Ctrl + L", "Lock the screen."),
    ("windows", None, "Super + W", "Close the window. Super + Q does the same thing."),
    ("windows", None, "Ctrl + Alt + Del", "Closes every window. Consider this carefully."),
    ("windows", None, "Super + T", "Toggle a window between tiling and floating."),
    ("windows", None, "Super + J", "Toggle the split between horizontal and vertical."),
    ("windows", None, "Super + F", "Go full screen. Super + Alt + F goes full width instead."),
    ("windows", None, "Super + Ctrl + F", "Full screen inside the window's own frame."),
    ("windows", None, "Super + Ctrl + Alt + F", "Full screen desktop — drops the top bar and the gaps."),
    ("windows", None, "Super + L", "Toggle between the dwindle and scrolling layouts."),
    ("windows", None, "Super + P", "Pseudo window style — natural size rather than stretched."),
    ("windows", None, "Super + O", "Pop a window into sticky and floating. It follows you around."),
    ("windows", None, "Super + G", "Toggle window grouping. Super + Alt + G moves one back out."),
    ("windows", None, "Super + Alt + Tab", "Cycle a group. Super + Alt + 1/2/3/4/5 jumps to one."),
    ("windows", None, "Super + Ctrl + Left/Right", "Move between the windows inside a tiling group."),
    ("windows", None, "Super + Arrow", "Move focus. Super + Shift + Arrow swaps the two windows."),
    ("windows", None, "Super + Minus", "Expand window left. Super + Equal shrinks it."),
    ("windows", None, "Super + Alt + Minus/Equal", "The same resizing in smaller steps. Ctrl for bigger ones."),
    ("windows", None, "Super + Alt + Home", "Save this window's width. Super + Home restores it."),
    ("windows", None, "Super + Left Mouse", "Drag the window around. Super + Right Mouse resizes it."),
    ("windows", None, "Super + Ctrl + Z", "Zoom in on the screen, repeatedly. Ctrl + Alt + Z zooms fully out."),
    ("windows", None, "Super + /", "Step through monitor scaling. Super + Alt + / steps back."),
    ("windows", None, "Alt + Tab", "Cycle windows on this workspace. Ctrl + Alt + Tab cycles monitors."),
    ("windows", None, "Super + Backspace", "Toggle transparency on a window."),
    ("windows", None, "Super + Shift + Backspace", "Toggle window gaps."),
    ("windows", None, "Super + Ctrl + Backspace", "Toggle single-window square aspect."),

    # ------------------------------------------------------- workspaces ----
    ("workspaces", None, "Super + 1/2/3/4", "Jump to a workspace. Add Shift to move the window there."),
    ("workspaces", None, "Super + Shift + Alt + 1/2/3/4", "Move a window to a workspace without following it."),
    ("workspaces", None, "Super + Tab", "Next workspace. Shift for previous, Ctrl for the former one."),
    ("workspaces", None, "Super + S", "Toggle the scratchpad. Super + Alt + S moves a window into it."),
    ("workspaces", None, "Super + Scroll Wheel", "Scroll through your workspaces."),
    ("workspaces", None, "Super + Shift + Alt + Arrows", "Move workspaces to the monitor in that direction."),

    # ----------------------------------------------------------- panels ----
    ("panels", None, "Super + Ctrl + W", "Wifi panel. A audio, B bluetooth, D display, P power."),
    ("panels", None, "Super + Ctrl + Alt + D", "The calendar panel."),
    ("panels", None, "Super + Ctrl + 1-9", "Toggle a bar panel by position, counting from the right section."),
    ("panels", None, "Super + Ctrl + T", "Activity — btop. It floats; Super + T tiles it."),
    ("panels", None, "Super + Ctrl + Q", "Calculator. Super + Ctrl + E is the emoji picker."),
    ("panels", None, "Super + Ctrl + H", "Hardware menu. Super + Ctrl + O is the toggle menu."),
    ("panels", None, "Super + Ctrl + S", "Share menu, via LocalSend, to anything else on your network."),
    ("panels", None, "Super + Ctrl + .", "Transcode media without remembering a single ffmpeg flag."),

    # ---------------------------------------------------------- capture ----
    ("capture", None, "Print Screen", "Screenshot. Alt + Print Screen records; hit it again to stop."),
    ("capture", None, "Super + Print Screen", "Colour picker."),
    ("capture", None, "Super + Ctrl + Print Screen", "Text extraction — OCR straight to the clipboard."),
    ("capture", None, "Super + Ctrl + C", "Capture menu, for keyboards with no Print Screen key."),
    ("capture", None, "Super + Alt + [", "Shrinks the webcam overlay while recording. ] grows it."),
    ("capture", None, "Super + Ctrl + X", "Start and stop dictation. F9 is push to talk."),
    ("capture", WEB, "Alt + Shift + L", "Copy the current URL from a web app or Chromium."),
    ("capture", WEB, "Alt + Shift + D", "Download the video on this page to ~/Videos."),

    # -------------------------------------------------------- clipboard ----
    ("clipboard", None, "Super + C", "Copy. Super + V pastes. They work in the terminal too."),
    ("clipboard", None, "Super + X", "Cut — the one that doesn't work in the terminal."),
    ("clipboard", None, "Super + Ctrl + V", "Clipboard manager. It holds images as well as text."),

    # ---------------------------------------------------- notifications ----
    ("notifications", None, "Super + ,", "Dismiss the latest notification. Shift dismisses all of them."),
    ("notifications", None, "Super + Alt + ,", "Invoke the most recent notification."),
    ("notifications", None, "Super + Ctrl + ,", "Toggle silencing. Super + Shift + Alt + , opens the history."),

    # ------------------------------------------------------------ style ----
    ("style", None, "Super + Ctrl + Shift + Space", "Pick a new theme. Super + Ctrl + Space picks the background."),
    ("style", None, "Super + Shift + Space", "Toggle the top bar."),
    ("style", None, "~/.config/omarchy/backgrounds", "Extras go in the subfolder named for the theme, like /nord."),
    ("style", None, "A theme", "Styles the desktop, terminal, neovim, btop, Chromium and the whole shell."),
    ("style", None, "Obsidian", "The exception — pick the Omarchy theme by hand in Appearance > Themes."),

    # ---------------------------------------------------------- toggles ----
    ("toggles", None, "Super + Ctrl + N", "Nightlight. It is later than you think."),
    ("toggles", None, "Super + Ctrl + I", "Toggle locking on idle."),
    ("toggles", None, "Super + Ctrl + Delete", "Laptop display on and off. Add Alt to mirror it."),
    ("toggles", None, "Shift + Mute", "Next audio output. Shift + Play switches media source."),
    ("toggles", None, "Alt + Play", "Next track. Alt + Shift + Play goes back."),
    ("toggles", None, "Alt + Brightness Up/Down", "Precise 1% steps. Shift jumps to maximum or minimum."),

    # -------------------------------------------------------- reminders ----
    ("reminders", None, "Super + Ctrl + R", "Set a reminder. Ctrl + Alt + R sees all, Ctrl + Shift + R clears."),
    ("reminders", None, "Super + Ctrl + Alt + T", "Time as a notification. B battery, W weather."),

    # ------------------------------------------------------------- apps ----
    ("apps", None, "Super + Return", "Terminal. Super + Alt + Return opens it in tmux."),
    ("apps", None, "Super + Ctrl + Return", "Herdr, the agent manager, still running from last time."),
    ("apps", None, "Super + Shift + Return", "Browser. Super + Shift + Alt + B for private."),
    ("apps", None, "Super + Shift + F", "File manager. Add Alt to open it in your terminal's directory."),
    ("apps", None, "Super + Shift + N", "Editor — Neovim by default. Super + Shift + O is Obsidian."),
    ("apps", None, "Super + Shift + D", "Lazydocker. Super + Shift + M is Spotify."),
    ("apps", None, "Super + Shift + Alt + M", "Cliamp — a terminal music player built like Winamp 2."),
    ("apps", None, "Super + Shift + /", "1Password. Super + Shift + G is Signal."),
    ("apps", None, "Super + Shift + W", "Omawrite, for when you just need a blank page."),
    ("apps", None, "Super + Shift + A", "ChatGPT. Super + Shift + Alt + A is Grok."),
    ("apps", None, "Disk Usage", "In the launcher. Walks the filesystem biggest first, deleting in place."),
    ("apps", None, "About", "Fastfetch in a frame. Kernel, uptime, theme, CPU, memory."),
    ("apps", None, "Omacut", "Trims a video's length. Built on ffmpeg, minus the ffmpeg."),

    # ------------------------------------------------------------ setup ----
    ("setup", None, "Install > Editor", "VSCode, Cursor, Zed, Sublime Text, Helix, Vim and Emacs."),
    ("setup", None, "Install > Package", "Anything in Arch. Install > AUR when it isn't in the main repos."),
    ("setup", None, "Install > TUI", "Give a terminal program a name, command and icon and it becomes an app."),
    ("setup", None, "Install > Web App", "Name, URL, icon — and it launches like anything else."),
    ("setup", None, "Setup > Defaults", "Editor, terminal, agent. Set once, and everything follows."),
    ("setup", None, "Setup > Input", "Keyboard layout, mouse, trackpad — or ~/.config/hypr/input.lua."),
    ("setup", None, "Setup > Direct Boot", "Skips the Limine menu and boots straight to the decryption screen."),
    ("setup", None, "Dual boot", "Quattro installs into free space beside Windows, LUKS and all."),

    # -------------------------------------------------------------- cli ----
    ("cli", TERM, "omarchy", "The command centre. Run it bare to see every group."),
    ("cli", TERM, "omarchy update", "Packages, snapshot and migrations together."),
    ("cli", TERM, "omarchy theme list", "Then omarchy theme set <name>. omarchy font list does fonts."),
    ("cli", TERM, "omarchy commands --all", "Every subcommand there is. --json if something else is reading."),
    ("cli", TERM, "omarchy debug", "The output to bring when you go asking for help."),
    ("cli", TERM, "omarchy-restart-xcompose", "Run it after editing ~/.XCompose or nothing changes."),

    # --------------------------------------------------- updates/rescue ----
    ("updates", None, "pacman -Syu", "Omarchy stops you — you'd skip the snapshot, migrations and configs."),
    ("updates", None, "Snapshots", "Taken before every update. Roll back from the Limine boot menu."),
    ("updates", TERM, "omarchy-snapshot create", "Take one yourself before you go doing something brave."),
    ("updates", TERM, "omarchy-snapshot restore", "Restores the root filesystem. /home and ~/.config are left alone."),
    ("updates", None, "Limine", "Snapshots need it. Default since 2.0, absent on GRUB or systemd-boot."),
    ("updates", TERM, "omarchy-reinstall", "Last resort — default configs and packages back."),
    ("updates", None, "Update > Config", "Reverts the configs you've made a mess of, without the full reinstall."),
    ("updates", None, "#omarchy-help", "The Discord channel. Bring your omarchy-debug output."),

    # ------------------------------------------------------------ fixes ----
    ("fixes", None, "Update > Hardware", "Reload Wi-Fi, Bluetooth, Audio or Trackpad before you reboot."),
    ("fixes", None, "GDK_SCALE", "Apps too big? Omarchy assumes a 2x display. Change it in monitors.lua."),
    ("fixes", None, "Caps Lock", "It isn't broken — it's the xcompose key. Remap it in input.lua."),
    ("fixes", None, "Ctrl + Minus", "Shrinks Spotify's oversized UI. Ctrl + Plus goes the other way."),
    ("fixes", TERM, "omarchy audio tuning status", "Tells you if a laptop speaker correction is on. Add off to stop it."),
    ("fixes", None, "Ctrl + Alt + F2", "Locked out by a bad password? A TTY, then faillock --reset --user."),

    # ------------------------------------------------------------ paths ----
    ("config", None, "~/.config", "Your files, for your changes. This half of the system is yours."),
    ("config", None, "/usr/share/omarchy", "Omarchy's own files. Override in ~/.config instead of editing these."),
    ("config", None, "~/.config/hypr/bindings.lua", "Your keybindings. o.bind adds one, o.rebind replaces a default."),
    ("config", None, "~/.config/hypr/monitors.lua", "Monitors, resolution and position. looknfeel.lua does gaps and borders."),
    ("config", None, "~/.config/hypr/autostart.lua", "o.launch_on_start(\"thing\") starts it with your session."),
    ("config", None, "~/.config/omarchy/shell.json", "Bar position, widgets, and the screensaver and idle timings."),
    ("config", None, "~/.config/foot/foot.ini", "Your terminal's config, foot being the default."),
    ("config", None, "~/.bashrc", "Your aliases, functions and exports. Never overwritten by updates."),
    ("config", None, "~/.config/omarchy/hooks", "Scripts in <event>.d/ run on post-boot, post-update, theme-set."),
    ("config", None, "omarchy-menu.jsonc", "In ~/.config/omarchy/extensions — adds your own rows to the menu."),
    ("config", TERM, "omarchy menu keybindings --print", "Prints every current binding with its description."),
    ("config", None, "~/.config/omarchy/themed", "Drop a name.tpl there and it's regenerated on every theme switch."),
    ("config", None, "~/.XCompose", "Your quick emoji and name/email autocompletes."),

    # ------------------------------------------------------ shell tools ----
    ("shell", TERM, "ff", "fzf with a preview. Fuzzy find any file below where you're standing."),
    ("shell", TERM, "Ctrl + R", "fzf through your command history."),
    ("shell", TERM, "cd oma", "Zoxide remembers where you've been. Half the name will do."),
    ("shell", TERM, "rg <pattern> <path>", "ripgrep. Searches inside the files, not just their names."),
    ("shell", TERM, "man zoxide", "The full story, when the alias stops being enough. man fzf too."),

    # -------------------------------------------------- shell functions ----
    ("shell", TERM, "compress [file/dir]", "A tar.gz without the flag archaeology. decompress unpacks it."),
    ("shell", TERM, "iso2sd [image.iso]", "A bootable drive, with the target picked interactively."),
    ("shell", TERM, "format-drive", "Run it bare to list the drives first. One exFAT partition. Careful."),
    ("shell", TERM, "ga [branch]", "A worktree and branch beside the repo, and jumps you in. gd removes it."),
    ("shell", TERM, "rsw [source] [destination]", "Rsyncs on every change, remote host and all. lsw lists, dsw stops."),
    ("shell", TERM, "fip nyc-dev 3000", "Forwards a remote port to localhost over SSH. dip drops it, lip lists."),
    ("shell", TERM, "ssh", "Wrapped — it cleans up and reconnects when a session drops. Ctrl-C stops."),

    # ------------------------------------------------------------- tmux ----
    ("tmux", TERM, "Ctrl + Space", "The prefix. Prefix + v splits beside, prefix + h below."),
    ("tmux", TERM, "Alt + Enter", "Splits below with no prefix. Alt + Escape kills a pane."),
    ("tmux", TERM, "Ctrl + Alt + Arrows", "Move between panes. Add Shift to resize."),
    ("tmux", TERM, "Prefix + z", "Zoom a pane full screen. Same keys back out."),
    ("tmux", TERM, "Prefix + c", "New window. k kills, r renames, Alt + 1-9 jumps."),
    ("tmux", TERM, "Prefix + d", "Detach; it all keeps running. Prefix + s lists your sessions."),
    ("tmux", TERM, "Prefix + [", "Copy mode. v begins the selection, y takes it."),
    ("tmux", TERM, "Prefix + ?", "Every tmux binding. Prefix + q reloads the config."),
    ("tmux", TERM, "tdl c", "Editor, agent and terminal. tdl c cx runs two agents at once."),
    ("tmux", TERM, "tds", "A square: editor, a live diff watcher, terminal and opencode."),
    ("tmux", TERM, "tdlm", "A tdl window for every subdirectory. Alt + 1/2/3 walks them."),
    ("tmux", TERM, "tsl [count] [command]", "A grid of panes all running the same thing. Good for agents."),
    ("herdr", TERM, "Super + Ctrl + Return", "Herdr. Same Ctrl + Space prefix, and it survives detaching."),
    ("herdr", TERM, "hdl", "The tmux layouts again, for Herdr. hds, hdlm and hsl too."),

    # --------------------------------------------------------- terminal ----
    ("terminal", ("foot",), "Foot", "The default terminal. No native tabs or splits — that's tmux's job."),
    ("terminal", None, "Install > Terminal", "Alacritty, Ghostty or Kitty, if you want native tabs and splits."),
    ("terminal", None, "Setup > Defaults > Terminal", "Switches between the ones you've installed. Super + Return follows."),

    # ----------------------------------------------------------- agents ----
    ("agents", AGENT, "Super + Shift + Ctrl + A", "Launches your default agent in its own window, starting in ~/Work."),
    ("agents", AGENT, "omarchy default agent", "Nine are pre-wired. Or Setup > Defaults > Agent in the menu."),
    ("agents", AGENT, "a", "Runs the default agent inline. c opencode, cx Claude Code, cy Codex."),
    ("agents", AGENT, "omarchy agent prompt", "Sends it straight into a task. It runs unattended, so mean it."),
    ("agents", AGENT, "ori claude", "Runs another harness across OpenRouter's catalogue. ori code is its own."),
    ("agents", AGENT, "omarchy-mise-install", "Wraps any other CLI as a lazy-loaded stub, like the agents are."),
    ("agents", AGENT, "The agents icon", "Appears once you've used one. Left click for spend, right to launch."),
    ("agents", None, "A crash notification", "Click it and your agent is handed the core dump to explain."),
    ("agents", AGENT, "Agent skills", "Omarchy ships one for tailoring the system, symlinked into each harness."),
    ("agents", AGENT, "Agent theming", "Claude Code, Pi, OpenCode and Hermes follow your Omarchy theme."),
    ("agents", AGENT, "LM Studio", "That or Ollama, for running open-weight models on this machine."),

    # ---------------------------------------------------------- ghostty ----
    ("ghostty", ("ghostty",), "Ctrl + Shift + E", "New split below. Ctrl + Shift + O splits beside."),
    ("ghostty", ("ghostty",), "Ctrl + Shift + T", "New tab. Ctrl + Shift + Arrows moves between them."),
    ("ghostty", ("ghostty",), "Super + Ctrl + Shift + Arrows", "Resize a split by 10 lines. Add Alt for 100."),
    ("ghostty", ("ghostty",), "Shift + Pg Up/Down", "Scroll the history. Ctrl + Left mouse opens a link."),

    # ----------------------------------------------------------- neovim ----
    ("neovim", NVIM, "Space", "The leader. Press it, wait, and every option explains itself."),
    ("neovim", NVIM, "Space Space", "Fuzzy find a file. Space S G greps their contents with a preview."),
    ("neovim", NVIM, "Space E", "Toggle the file tree. Ctrl + W W hops between it and the editor."),
    ("neovim", NVIM, "Space G G", "LazyGit, floating, from the current directory."),
    ("neovim", NVIM, "Shift + H", "Left through the open tabs. Shift + L right, Space B D closes."),
    ("neovim", NVIM, "Space B O", "Close every tab but this one. Space U W toggles soft wrap."),
    ("neovim", NVIM, "?", "In the file tree, lists every command it has."),
    ("neovim", NVIM, "Ctrl + Left/Right arrow", "Changes the sidebar's width."),
    ("neovim", TERM, "n", "The alias for nvim. n myfile.txt opens just that one."),
    ("neovim", TERM, "sudoedit", "Edit root-owned files with all your plugins still loaded."),
    ("neovim", NVIM, "lazyvim.org/keymaps", "Everything LazyVim binds, on one page."),

    # -------------------------------------------------------------- git ----
    ("git", ("lazygit",), "Tab", "Moves between lazygit's panes. Space stages, c commits, ? lists all."),
    ("git", TERM, "gh auth login", "Then gh repo clone org/repo reaches your private repositories."),
    ("git", TERM, "ghui", "Pull requests in a TUI. Installs itself the first time you run it."),

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

    # ------------------------------------------------------------ emoji ----
    ("emoji", None, "CapsLock M S", "A smile. M H a heart, M Y a thumbs up."),
    ("emoji", None, "CapsLock Space Space", "An em dash. Space N your name, Space E your email."),
]

CHATTER = [
    "Nothing to report. Carry on.",
    "I like it here. It is dark and everything tiles.",
    "You have not pressed Super in a while. I noticed.",
    "I reread the manual while you were out.",
    "Somewhere on this machine a window is floating that should be tiled.",
    "Grazing.",
    "I know most of the manual by heart. Right click and take a piece of it.",
]

POKES = [
    "Yes?",
    "Careful. I startle.",
    "I was watching the workspaces.",
    "Hm.",
    "Right click me if you want something useful.",
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
    try:
        os.makedirs(CONFIG, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh)
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


class Pet:
    def __init__(self, opts, tips):
        self.px = opts.scale
        self.interval = opts.interval
        self.roam = opts.roam
        self.margin = opts.margin
        self.corner = opts.corner

        self.tips = tips
        self.seen = load_seen()
        self.known = load_known()
        self.current = None
        self.chatter = Bag(CHATTER)
        self.pokes = Bag(POKES)

        self.x = self.y = 0.0
        self.home_x = self.home_y = None
        self.placed = False

        self.dir = -1
        self.speed = 0.0
        self.dist = 0.0
        self.mode = "home"          # home | out | back | drag
        self.target = 0.0
        self.pause = 0.0
        self.next_roam = random.uniform(self.roam * 0.5, self.roam)

        self.blink = 0.0
        self.next_blink = random.uniform(2, 6)
        self.next_talk = random.uniform(20, 40)
        self.snooze_until = 0.0
        self.last_spoke = -999.0
        # Presence. Tips are only spent on someone who is actually here;
        # anything else and they'd be burned talking to an empty chair.
        self.idle_after = getattr(opts, "idle", 300)
        self.present_until = 1e9 if not self.idle_after else 0.0

        self.head = self.text = None
        self.text_until = 0.0

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
        self.placed = True

    def clamp_home(self, width, height):
        self.home_x = max(4, min(self.home_x, width - self.w - 4))
        self.home_y = max(4, min(self.home_y, height - self.h - 4))

    # -- speech ------------------------------------------------------------
    def snoozing(self, now):
        return now < self.snooze_until

    def present(self, now):
        """True when there is evidence of a human at the machine."""
        return not self.idle_after or now < self.present_until

    def saw_activity(self, now):
        self.present_until = now + self.idle_after

    def mark_seen(self, tip):
        self.seen.add(tip_id(tip))
        if len(self.seen) >= len(self.tips):
            self.seen.clear()
        save_json(SEEN, sorted(self.seen))

    def pick(self, cls="", context=None):
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
                return None
            best = max(s for s, _ in scored)
            pool = [t for s, t in scored if s == best]
        pool = [t for t in pool if tip_id(t) not in self.known] or pool
        fresh = [t for t in pool if tip_id(t) not in self.seen]
        tip = random.choice(fresh or pool)
        self.mark_seen(tip)
        self.current = tip
        return tip

    def mark_known(self, tip):
        self.known.add(tip_id(tip))
        save_json(KNOWN, sorted(self.known))

    def say(self, head, text, secs, now):
        self.head, self.text = head, text
        self.text_until = now + secs
        self.last_spoke = now
        self.pause = max(self.pause, secs)

    def say_tip(self, tip, secs, now):
        self.say(tip[2], tip[3], secs, now)

    def next_ambient(self):
        if random.random() < 0.15:
            self.current = None
            return None, self.chatter.next()
        t = self.pick()
        return (t[2], t[3]) if t else (None, self.chatter.next())

    # -- motion ------------------------------------------------------------
    def step(self, dt, now, width, height):
        if not self.placed:
            self.place(width, height)

        self.blink -= dt
        self.next_blink -= dt
        if self.next_blink <= 0:
            self.blink = 0.11
            self.next_blink = random.uniform(2.5, 7.5)

        if self.text and now > self.text_until:
            self.head = self.text = None

        self.next_talk -= dt
        if self.next_talk <= 0:
            if self.snoozing(now) or not self.present(now) or not visible:
                # Say nothing and, crucially, pick nothing — an unread tip
                # must not be marked seen. Just look again shortly.
                self.next_talk = 30.0
            else:
                self.next_talk = random.uniform(self.interval * 0.6,
                                                self.interval * 1.4)
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
            return

        if self.mode == "home":
            self.next_roam -= dt
            if self.next_roam <= 0:
                span = min(width * 0.45, 520)
                self.target = max(4, min(
                    self.home_x + random.uniform(-span, span), width - self.w - 4))
                self.speed = random.uniform(46, 72)
                self.mode = "out"
            return

        goal = self.target if self.mode == "out" else self.home_x
        delta = goal - self.x
        if abs(delta) < 2:
            self.x = goal
            if self.mode == "out":
                self.mode = "back"
                self.pause = random.uniform(1.5, 5.0)
                self.speed = random.uniform(46, 72)
            else:
                self.mode = "home"
                self.next_roam = random.uniform(self.roam * 0.7, self.roam * 1.6)
            return

        self.dir = 1 if delta > 0 else -1
        self.x += self.dir * self.speed * dt
        self.dist += self.speed * dt

    def frame(self):
        if self.mode not in ("out", "back") or self.pause > 0:
            return 1
        return int(self.dist / (self.px * 2.2)) % 4


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


def main(argv=None):
    p = argparse.ArgumentParser(description="Yoru, a Clippy for Omarchy.")
    p.add_argument("--scale", type=int, default=4, help="pixel size (default 4)")
    p.add_argument("--corner", default="br", choices=["br", "bl", "tr", "tl"],
                   help="where he parks on first run (default bottom right)")
    p.add_argument("--margin", type=int, default=24, help="gap from the screen edge")
    p.add_argument("--interval", type=float, default=300,
                   help="average seconds between ambient tips (default 300)")
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
    p.add_argument("--quiet", action="store_true",
                   help="no ambient tips; only when asked or on context")
    p.add_argument("--start-hidden", action="store_true",
                   help="begin off screen; SIGUSR1 toggles him")
    p.add_argument("--layer", default="overlay",
                   choices=["background", "bottom", "top", "overlay"])
    p.add_argument("--ask", metavar="QUERY", help="search his knowledge and exit")
    p.add_argument("--list", action="store_true", help="print everything he knows and exit")
    p.add_argument("--forget-known", action="store_true",
                   help="un-retire every tip you've marked as known")
    opts = p.parse_args(argv)

    load_user_tips()
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
    if opts.quiet:
        opts.interval = 1e9

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

    globals().update(Gtk=Gtk, GLib=GLib, Gdk=Gdk, Pango=Pango,
                     PangoCairo=PangoCairo, cairo=cairo, LayerShell=LayerShell)


def draw_sprite(cr, pet, oy):
    px, flip = pet.px, pet.dir < 0
    pts = pixels(pet.frame(), pet.blink > 0)

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

        # -- setup -------------------------------------------------------
        def do_activate(self):
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
            apply_theme()
            self._theme_stamp = theme_stamp()
            win.present()
            GLib.timeout_add(33, self.tick)
            if not read_state().get("introduced"):
                GLib.timeout_add_seconds(4, self.intro)
            if not opts.no_theme:
                GLib.timeout_add_seconds(4, self.poll_theme)
            if not opts.no_context:
                GLib.timeout_add_seconds(2, self.poll_context)

        # -- input -------------------------------------------------------
        def on_click(self, gesture, n_press, x, y):
            now = GLib.get_monotonic_time() / 1e6
            button = gesture.get_current_button()
            pet = self.pet
            if button == 3:                                   # next tip
                head, text = pet.next_ambient()
                pet.say(head, text, 9.0, now)
            elif button == 2:                                 # snooze
                if pet.snoozing(now):
                    pet.snooze_until = 0.0
                    pet.say(None, "Back. What did I miss?", 3.0, now)
                else:
                    pet.snooze_until = now + 3600
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
            save_json(STATE, state)

        def poll_theme(self):
            """Repaint when the Omarchy theme changes, silently."""
            stamp = theme_stamp()
            if stamp != self._theme_stamp:
                self._theme_stamp = stamp
                apply_theme()
            return True

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
                return True
            self.ctx_cls = cls
            if (pet.snoozing(now)
                    or not pet.present(now)
                    or not visible
                    or now - pet.last_spoke < opts.cooldown
                    or self.ctx_offers.get(cls, 0) >= 2):
                return True
            tip = pet.pick(cls=cls, context=full)
            if tip:
                pet.say_tip(tip, 9.0, now)
                self.ctx_offers[cls] = self.ctx_offers.get(cls, 0) + 1
            return True

        def intro(self):
            """Say hello once, ever — right click is his best feature and
            nothing else advertises it."""
            if not visible:
                return True     # try again once he is on screen
            now = GLib.get_monotonic_time() / 1e6
            self.pet.saw_activity(now)
            self.pet.say("Yoru",
                         "I know the Omarchy manual. Right click for a tip, "
                         "left click one to say you already know it and retire "
                         "it, middle click to snooze, drag to move me.",
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
            surface = self.win.get_surface()
            if surface is not None:
                # Hidden means untouchable too: an empty region hands every
                # click to whatever is underneath, not to an invisible deer.
                region = cairo.Region(cairo.RectangleInt(
                    int(self.pet.x), int(self.pet.y),
                    int(self.pet.w), int(self.pet.h))) if visible else cairo.Region()
                surface.set_input_region(region)
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
    # Dispatched from the main loop, not from inside the signal handler, so
    # the flip can never land in the middle of a frame.
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, toggle_visible)
    return build_app(opts, tips).run([])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        os._exit(0)
    except KeyboardInterrupt:
        os._exit(0)
