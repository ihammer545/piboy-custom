#!/bin/bash
# Stop Linux fbcon from painting a blinking cursor over /dev/fb0.
# Must run as root. Safe to call before every piboy start (e.g. systemd ExecStartPre=+).
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "run as root: sudo $0" >&2
  exit 1
fi

echo 0 > /sys/class/graphics/fbcon/cursor_blink 2>/dev/null || true

for d in /sys/class/vtconsole/vtcon*; do
  if [[ -f "$d/name" ]] && grep -qi 'frame buffer' "$d/name"; then
    echo 0 > "$d/bind"
    echo "unbound $(basename "$d"): $(tr -d '\n' < "$d/name") bind=$(cat "$d/bind")"
  fi
done

# Hide cursor + graphics mode on tty1 (stops console redraw)
printf '\033[?25l\033[2J\033[H' > /dev/tty1 2>/dev/null || true
python3 - <<'PY' 2>/dev/null || true
import fcntl, os
KDSETMODE, KD_GRAPHICS = 0x4B3A, 1
for tty in ("/dev/tty1", "/dev/tty0"):
    try:
        fd = os.open(tty, os.O_RDWR)
        fcntl.ioctl(fd, KDSETMODE, KD_GRAPHICS)
        os.close(fd)
        print("KD_GRAPHICS", tty)
        break
    except OSError as e:
        print(tty, e)
PY

# Stop login prompt from fighting us on the panel
systemctl stop getty@tty1.service 2>/dev/null || true

echo "verify: cat /sys/class/vtconsole/vtcon1/bind  → must be 0"
