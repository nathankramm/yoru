#!/bin/bash
# Install Yoru for the current user. Nothing here needs root: the binary goes
# to ~/.local/bin, the autostart line to ~/.config/hypr/autostart.lua and the
# hide/show binding to ~/.config/hypr/bindings.lua. Running it twice is safe.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ! -f $here/yoru.py || $PWD != "$here" ]]; then
  echo "install.sh: run it from the repo root (cd to the directory holding yoru.py)." >&2
  exit 1
fi

bin="$HOME/.local/bin/yoru"
autostart="$HOME/.config/hypr/autostart.lua"
line="o.launch_on_start(\"$bin\")"
bindings="$HOME/.config/hypr/bindings.lua"
# Super + Ctrl + Y hides and shows him. A signal, not a key inside the app:
# his layer surface takes no keyboard input. SIGUSR1 kills any process that
# has no handler for it, so the pattern is the exact installed path with a
# boundary after it — that is the command line the launcher produces and
# nothing else's: not an editor with the file open, not another user's copy,
# and not the sh -c Hyprland runs this bind through, whose own command line
# contains the pattern text followed by a parenthesis.
toggle="o.bind(\"SUPER + CTRL + Y\", \"Toggle Yoru\", \"pkill -USR1 -f 'python3 $bin( |\$)'\")"
did=()

# -- dependencies ------------------------------------------------------------
missing=()
for pkg in python-gobject gtk4 gtk4-layer-shell python-cairo; do
  pacman -Q "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if ((${#missing[@]})); then
  echo "Missing: ${missing[*]}" >&2
  echo "Install them first, then run this again:" >&2
  echo "  sudo pacman -S --needed ${missing[*]}" >&2
  exit 1
fi

# -- binary --------------------------------------------------------------------
if [[ -L $bin && $(readlink -f -- "$bin") == "$here/yoru.py" ]]; then
  did+=("left $bin alone: it is already a symlink to this checkout")
elif [[ -f $bin ]] && cmp -s "$here/yoru.py" "$bin"; then
  did+=("$bin is already this version")
else
  install -Dm755 "$here/yoru.py" "$bin"
  did+=("installed $bin")
fi

# -- autostart -----------------------------------------------------------------
# Any uncommented launch line that runs ~/.local/bin/yoru counts as present,
# flags and all, so a line you tuned by hand is never duplicated or replaced.
if [[ -f $autostart ]] && grep -Eq '^[^-]*launch_on_start\(.*\.local/bin/yoru' "$autostart"; then
  did+=("autostart line already in $autostart")
else
  mkdir -p "$(dirname -- "$autostart")"
  if [[ -f $autostart ]]; then
    backup="$autostart.bak-$(date +%Y%m%d-%H%M%S)"
    cp -- "$autostart" "$backup"
    did+=("backed up $autostart to $backup")
  fi
  printf '\n-- Yoru, the Omarchy assistant (added by install.sh)\n%s\n' "$line" >>"$autostart"
  did+=("added to $autostart: $line")
fi

# -- hide/show binding ----------------------------------------------------------
# Any uncommented bind that sends USR1 to a yoru binary counts as present,
# whatever key it is on, so a toggle you set up by hand is never duplicated.
if [[ -f $bindings ]] && grep -Eq '^[^-]*bind\(.*USR1.*bin/yoru' "$bindings"; then
  did+=("toggle binding already in $bindings")
else
  mkdir -p "$(dirname -- "$bindings")"
  if [[ -f $bindings ]]; then
    backup="$bindings.bak-$(date +%Y%m%d-%H%M%S)"
    cp -- "$bindings" "$backup"
    did+=("backed up $bindings to $backup")
  fi
  printf '\n-- Yoru, the Omarchy assistant: hide and show him (added by install.sh)\n%s\n' "$toggle" >>"$bindings"
  did+=("added to $bindings: $toggle")
fi

# -- report --------------------------------------------------------------------
printf '%s\n' "${did[@]}"
echo "$(python3 "$here/yoru.py" --version 2>/dev/null || echo yoru)"
echo
if pgrep -f -- "$bin" >/dev/null; then
  echo "He is already running. To pick up this version: pkill -f \"$bin\"; yoru &"
else
  echo "Start him now with:   yoru &"
fi
echo "Autostart takes effect at your next login; a config reload does not rerun it."
echo "Super + Ctrl + Y hides and shows him once Hyprland reloads: hyprctl reload"
echo "Try the knobs first:  yoru --interval 20 --roam 20 --idle 0"
