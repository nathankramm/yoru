#!/bin/bash
# Reverse install.sh: the binary, the autostart line and the hide/show and
# swap bindings go; ~/.config/yoru (his position, what he has said, what you
# retired, which character he is) is asked about first.
set -euo pipefail

bin="$HOME/.local/bin/yoru"
autostart="$HOME/.config/hypr/autostart.lua"
bindings="$HOME/.config/hypr/bindings.lua"
state="$HOME/.config/yoru"
did=()

if pgrep -f -- "$bin" >/dev/null; then
  pkill -f -- "$bin" && did+=("stopped the running instance")
fi

if [[ -e $bin || -L $bin ]]; then
  rm -f -- "$bin"
  did+=("removed $bin")
else
  did+=("$bin was not there")
fi

if [[ -f $autostart ]] && grep -Eq '\.local/bin/yoru' "$autostart"; then
  backup="$autostart.bak-$(date +%Y%m%d-%H%M%S)"
  cp -- "$autostart" "$backup"
  # Drop the launch line and the comment install.sh put above it, nothing else.
  grep -Ev '^[^-]*launch_on_start\(.*\.local/bin/yoru|^-- Yoru, the Omarchy assistant \(added by install\.sh\)$' \
    "$autostart" >"$autostart.tmp"
  mv -- "$autostart.tmp" "$autostart"
  did+=("removed the yoru line from $autostart (backup: $backup)")
else
  did+=("no yoru line in $autostart")
fi

if [[ -f $bindings ]] && grep -Eq '^[^-]*bind\(.*USR[12].*bin/yoru' "$bindings"; then
  backup="$bindings.bak-$(date +%Y%m%d-%H%M%S)"
  cp -- "$bindings" "$backup"
  # Drop the toggle and swap binds and the comments install.sh put above
  # them, nothing else.
  grep -Ev '^[^-]*bind\(.*USR[12].*bin/yoru|^-- Yoru, the Omarchy assistant: (hide and show him|swap the character) \(added by install\.sh\)$' \
    "$bindings" >"$bindings.tmp"
  mv -- "$bindings.tmp" "$bindings"
  did+=("removed the toggle and swap bindings from $bindings (backup: $backup)")
else
  did+=("no toggle or swap binding in $bindings")
fi

printf '%s\n' "${did[@]}"

if [[ -d $state ]]; then
  echo
  echo "$state holds his position, the tips he has shown and the ones you retired."
  read -r -p "Delete it too? [y/N] " answer
  if [[ ${answer,,} == y* ]]; then
    rm -rf -- "$state"
    echo "removed $state"
  else
    echo "kept $state"
  fi
fi
