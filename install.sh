#!/bin/bash
# Install Yoru for the current user. Nothing here needs root: the binary goes
# to ~/.local/bin and the autostart line to ~/.config/hypr/autostart.lua.
# Running it twice is safe.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ! -f $here/yoru.py || $PWD != "$here" ]]; then
  echo "install.sh: run it from the repo root (cd to the directory holding yoru.py)." >&2
  exit 1
fi

bin="$HOME/.local/bin/yoru"
autostart="$HOME/.config/hypr/autostart.lua"
line="o.launch_on_start(\"$bin\")"
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
echo "Try the knobs first:  yoru --interval 20 --roam 20 --idle 0"
