#!/bin/bash
# Reverse install.sh: the binary and the autostart line go; ~/.config/yoru
# (his position, what he has said, what you retired) is asked about first.
set -euo pipefail

bin="$HOME/.local/bin/yoru"
autostart="$HOME/.config/hypr/autostart.lua"
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
