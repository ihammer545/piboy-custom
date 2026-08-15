#!/bin/bash
# Stop Linux fbcon from painting a blinking cursor over /dev/fb0.
# Run once (needs root), then start/restart piboy as usual.
set -euo pipefail

echo 0 > /sys/class/graphics/fbcon/cursor_blink 2>/dev/null || true

for d in /sys/class/vtconsole/vtcon*; do
  if [[ -f "$d/name" ]] && grep -qi 'frame buffer' "$d/name"; then
    echo 0 > "$d/bind"
    echo "unbound $(basename "$d"): $(cat "$d/name")"
  fi
done

# Hide cursor on the active console (best-effort)
printf '\033[?25l' > /dev/tty1 2>/dev/null || true

echo "done — restart piboy if it was already running"
