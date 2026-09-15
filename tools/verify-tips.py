#!/usr/bin/env python3
"""Three-way check of Yoru's Hyprland-scope tips against this machine.

  A. the tip  — KNOWLEDGE in yoru.py, its key and what it claims
  B. live     — `hyprctl binds`, key and description
  C. stock    — the installed release's defaults, evaluated for real by
                tools/stock-binds.lua from /usr/share/omarchy/default/hypr

Every tip whose key parses lands in one bucket:

  AGREES        bound here, live description is the stock one
  REBOUND       bound here, but your description differs from stock — the tip
                describes the stock meaning of a key you changed
  GONE          not bound here and not in stock either (or only behind an
                "if installed" guard that fails here)
  STALE         in stock, missing here — your config removed it, or the
                install has drifted; the script says which

What no script can do is bucket 3 from the original audit: the key exists and
the label matches, but the *sentence* is wrong (a menu entry that moved, a
flag that changed). For those, read the AGREES list — it prints the live label
next to the tip so a mismatch is visible — and then read the script behind the
label under /usr/share/omarchy/bin. See tools/README.md.

Usage:  python3 tools/verify-tips.py            # buckets + drift summary
        python3 tools/verify-tips.py --all      # also print every AGREES row
        python3 tools/verify-tips.py --others   # the non-Hyprland tips, grouped
                                                # by where to check them
"""
import collections
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import yoru  # noqa: E402

# Where to look for the tips the compositor can't vouch for.
OTHERS = {
    "grammar": "tools/stock-binds.lua stock force, grouped by modifier set; the fractions in the KNOWLEDGE comment",
    "cli": "bin/omarchy-* headers (# omarchy:summary / :args), `omarchy commands --all`",
    "updates": "bin/omarchy-update, bin/omarchy-snapshot, default/libalpm/hooks/",
    "fixes": "bin/, config/hypr/monitors.lua, default/hypr/input.lua",
    "config": "config/ (shipped user files), default/hypr/helpers.lua, bin/omarchy-hook*",
    "shell": "default/bash/aliases, default/bash/fns/*",
    "tmux": "config/tmux/tmux.conf, default/bash/fns/tmux",
    "herdr": "default/bash/fns/herdr",
    "terminal": "default/omarchy/omarchy-menu.jsonc (install.terminal), bin/omarchy-default-terminal",
    "agents": "install/user/mise.sh, bin/omarchy-default-agent, default/agents/skills/, default/themed/",
    "setup": "default/omarchy/omarchy-menu.jsonc (setup.*, install.*)",
    "style": "default/omarchy/omarchy-menu.jsonc (style.*), bin/omarchy-theme-set*",
    "apps": "applications/*.desktop, install/omarchy-base.packages",
    "browser": "default/chromium/extensions/*/manifest.json",
    "emoji": "default/xcompose, install/user/xcompose.sh",
    "ghostty": "config/ghostty/config; the rest is Ghostty's own defaults (not in the tree)",
    "neovim": "omarchy-nvim: /etc/skel/.local/share/nvim/lazy/LazyVim/lua/lazyvim/config/keymaps.lua (Omarchy adds none)",
    "git": "config/lazygit/; lazygit's own defaults (not in the tree)",
    "docker": "lazydocker's own defaults; default/omarchy/omarchy-menu.jsonc (install.development)",
    "files": "Nautilus's own defaults; default/hypr/apps/system.lua for the previewer rule",
}


def norm(keystr):
    """'SUPER + SHIFT + code:10' -> (frozenset({'SUPER','SHIFT'}), '1'), the
    same shape yoru.live_binds() produces for hyprctl's output."""
    parts = [p.strip() for p in keystr.split("+")]
    mods = frozenset(p.upper() for p in parts if p.upper() in yoru.MODBITS)
    rest = [p for p in parts if p.upper() not in yoru.MODBITS]
    key = rest[-1] if rest else ""
    if key.startswith("code:"):
        key = yoru.KEYCODES.get(key[5:], key)
    elif not key.startswith(("XF86", "mouse", "switch")):
        key = key.upper()
    return mods, key


def harness(mode, force=False):
    cmd = ["lua", os.path.join(HERE, "stock-binds.lua"), mode] + (["force"] if force else [])
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    binds = collections.OrderedDict()     # key -> [descriptions], in bind order
    unbound = set()
    for line in out.splitlines():
        ev, keys, desc, _disp, src = line.split("\t")
        k = norm(keys)
        if ev == "UNBIND":
            binds.pop(k, None)
            unbound.add(k)
        else:
            binds.setdefault(k, []).append((desc, src))
    return binds, unbound


def fmt(k):
    mods, key = k
    return " + ".join([m for m in ("SUPER", "CTRL", "SHIFT", "ALT") if m in mods] + [key])


def main(argv):
    show_all = "--all" in argv
    if "--others" in argv:
        for topic in sorted({t[0] for t in yoru.KNOWLEDGE}):
            rows = [t for t in yoru.KNOWLEDGE
                    if t[0] == topic and not (topic in yoru.HYPR_TOPICS and yoru.parse_keys(t[2]))]
            if not rows:
                continue
            print("\n== %s — check under /usr/share/omarchy: %s" % (topic, OTHERS.get(topic, "?")))
            for t in rows:
                print("   %-32s %s" % (t[2], t[3]))
        return 0

    live = yoru.live_binds()
    if live is None:
        print("hyprctl binds unavailable — run this inside a Hyprland session.")
        return 1
    stock, _ = harness("stock")
    stock_any, _ = harness("stock", force=True)
    full, user_unbound = harness("full")
    user_bound = {k for k, v in full.items() if any("/.config/hypr/" in src for _, src in v)}

    def stock_descs(k):
        return [d for d, _ in stock.get(k, [])]

    # -- is the harness telling the truth about this machine? ---------------
    print("== harness: stock + ~/.config/hypr/bindings.lua vs live hyprctl")
    print("   %d keys from the Lua, %d live" % (len(full), len(live)))
    for k in full:
        if k not in live:
            print("   in Lua, not live: %s" % fmt(k))
    for k in live:
        if k not in full:
            print("   live, not in Lua: %s" % fmt(k))
    # A key bound twice in stock (Alt+Tab is) shows hyprctl's last description.
    for k in full:
        if k in live and live[k] not in [d for d, _ in full[k]]:
            print("   description differs: %s  lua=%r  live=%r" % (fmt(k), full[k][0][0], live[k]))

    # -- whole-config drift, independent of any tip -------------------------
    print("\n== stock vs live, whole config (%d stock keys)" % len(stock))
    for k in stock:
        if k not in live:
            why = "your bindings.lua unbinds it" if k in user_unbound else "NOT EXPLAINED BY YOUR CONFIG"
            print("   missing live: %-28s %-32s %s" % (fmt(k), stock_descs(k)[0], why))
    for k in stock_any:
        if k not in stock:
            print("   stock only when installed: %-20s %s" % (fmt(k), [d for d, _ in stock_any[k]][0]))
    for k in live:
        if k in stock and live[k] not in stock_descs(k):
            print("   rebound: %-33s stock=%r live=%r" % (fmt(k), stock_descs(k)[0], live[k]))
    yours = [fmt(k) for k in live if k not in stock]
    print("   yours, not in stock: %s" % (", ".join(yours) or "none"))

    # -- per tip -------------------------------------------------------------
    buckets = collections.defaultdict(list)
    for t in yoru.KNOWLEDGE:
        if t[0] not in yoru.HYPR_TOPICS:
            continue
        parsed = yoru.parse_keys(t[2])
        if parsed is None:
            continue
        mods, keys = parsed
        members = [(mods, k) for k in keys]
        gone = yoru._missing(live, mods, keys)
        label = " / ".join(sorted({live[m] for m in members if m in live}))
        if gone:
            missing = [(mods, k) for k in gone]
            if any(m in stock for m in missing):
                why = ("your bindings.lua unbinds it" if any(m in user_unbound for m in missing)
                       else "NOT EXPLAINED BY YOUR CONFIG — install drift?")
                buckets["STALE"].append((t, "stock=%r; %s" % (stock_descs(missing[0])[0], why)))
            elif any(m in stock_any for m in missing):
                buckets["GONE"].append((t, "stock only when installed: %r"
                                        % [d for d, _ in stock_any[missing[0]]][0]))
            else:
                buckets["GONE"].append((t, "not in stock either"))
        elif any(m in stock and live[m] not in stock_descs(m) for m in members):
            m = next(m for m in members if m in stock and live[m] not in stock_descs(m))
            buckets["REBOUND"].append((t, "stock=%r live=%r" % (stock_descs(m)[0], live[m])))
        else:
            buckets["AGREES"].append((t, label))

    print("\n== buckets")
    for name in ("AGREES", "REBOUND", "GONE", "STALE"):
        print("   %-8s %d" % (name, len(buckets[name])))
    for name in ("REBOUND", "GONE", "STALE"):
        if buckets[name]:
            print("\n== %s" % name)
            for t, note in buckets[name]:
                print("   %-14s %-28s %s\n      yoru: %s" % (t[0], t[2], note, t[3]))
    if show_all:
        print("\n== AGREES — read the live label against the sentence; this is where a"
              "\n   stale sentence hides behind a key that still exists")
        for t, label in buckets["AGREES"]:
            print("   %-28s [%s]\n      %s" % (t[2], label, t[3]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
