# tools

Checks for the tips in `KNOWLEDGE`. Run them before a release, and again
whenever Omarchy ships a new version.

## What counts as true

A tip is verified against the **installed release** — the files under
`/usr/share/omarchy` on the machine you are sitting at — not against the
manual and not against the `quattro` branch on GitHub.

The manual's hotkeys table says `Super + Q` closes a window. It is not bound
in 4.0.3; nothing in `default/hypr/bindings/` mentions it. The branch had
`ori`, `o.rebind` and nine agents at the time the tips were written; the
4.0.3 packages have neither of the first two and thirteen of the last. The
tree is the only thing that cannot be ahead of, or behind, what the user's
keys do.

"The tree" is two packages: `omarchy` owns `bin/` and `install/`,
`omarchy-settings` owns `default/`, `config/` and `applications/`. LazyVim's
own keymaps ship in `omarchy-nvim`, under
`/etc/skel/.local/share/nvim/lazy/LazyVim/lua/lazyvim/config/keymaps.lua`.
`pacman -Qkk omarchy omarchy-settings omarchy-nvim` should report 0 altered
files before you trust any of it.

Where to look, by topic, is the `OTHERS` table in `verify-tips.py`
(`--others` prints every non-Hyprland tip under its heading). The short
version: `bin/omarchy-*` headers (`# omarchy:summary`, `# omarchy:args`),
`default/hypr/**/*.lua`, `default/bash/{aliases,fns/*}`,
`config/tmux/tmux.conf`, `default/omarchy/omarchy-menu.jsonc`,
`install/user/mise.sh` for which CLIs are stubbed, `default/themed/` for what
follows the theme.

## stock-binds.lua

Evaluates Omarchy's real Hyprland Lua — bootstrap, helpers, every bindings
file, the toggles — with `hl` replaced by a recorder, and prints each
`hl.bind` / `hl.unbind` as a TSV line. Loops, `bind_toggle` and the
`cmd_present` guards run for real, so this is what the compositor would bind,
not what a regex finds.

    lua tools/stock-binds.lua stock          # shipped defaults, this machine's guards
    lua tools/stock-binds.lua full           # plus ~/.config/hypr/bindings.lua
    lua tools/stock-binds.lua stock force    # every optional app pretended present

Needs the `lua` package. `full` reproduced `hyprctl binds` key-for-key on the
machine it was written on; `verify-tips.py` prints any difference first, so
you know whether to trust the rest.

## verify-tips.py

Three-way comparison — tip, live `hyprctl binds`, stock — for every tip in
`HYPR_TOPICS` whose key parses. Buckets:

| bucket | meaning |
|---|---|
| AGREES | bound here, live description is the stock one |
| REBOUND | bound here, your description differs from stock — the tip teaches the stock meaning of a key you changed |
| GONE | not bound here, not in stock (or only behind an "if installed" guard) — `--verify-report` already withholds these |
| STALE | in stock, missing here — the script says whether your `bindings.lua` removed it or the install has drifted |

It also prints whole-config drift (every stock key missing live, every live
key whose description differs from stock) independent of any tip.

    python3 tools/verify-tips.py            # buckets, plus the drift summary
    python3 tools/verify-tips.py --all      # also every AGREES row, live label beside the sentence
    python3 tools/verify-tips.py --others   # the non-Hyprland tips, grouped by where to check them

The one thing it cannot catch is a sentence that is wrong while its key still
exists and the label still matches — `Super + Escape` describing a menu that
lost its "relaunch Hyprland" entry. For those, read `--all`: the live label is
printed next to each sentence, and the script behind the label is under
`/usr/share/omarchy/bin`. That audit found two in 77 last time; it is worth
the twenty minutes.

## Known 4.0.3 quirks

- **`omarchy debug` does not route from a desktop terminal.** The binary is
  shipped — `omarchy-settings` puts `omarchy-debug`, `omarchy-debug-idle` and
  `omarchy-upload-log` in `/usr/bin` — but package-owned
  `default/hypr/envs.lua` prepends `/usr/share/omarchy/bin` to PATH for every
  Hyprland-launched process, and the `omarchy` dispatcher there only scans
  its own directory, where those three don't exist. So `omarchy debug` says
  "Unknown Omarchy command" in foot while `omarchy-debug` works, and both
  work over SSH. The tip names the hyphenated form. Re-check at the next
  release: this may quietly fix itself, and then the spaced form is the one
  the manual and the shipped agent skill already tell people to use.

## At the next release

    omarchy version                          # note it
    python3 tools/verify-tips.py             # anything new in GONE / STALE / REBOUND?
    python3 tools/verify-tips.py --all       # read the AGREES labels
    python3 tools/verify-tips.py --others    # walk the other topics against the tree
    python3 yoru.py --verify-report          # what he will actually withhold here
