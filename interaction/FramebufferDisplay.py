"""Linux framebuffer display (/dev/fb0) for 800×480 RGB565 panels."""

from __future__ import annotations

import fcntl
import logging
import mmap
import os
import threading
import time
from pathlib import Path

from PIL import Image

from core.decorator import override
from interaction.Display import Display

logger = logging.getLogger('piboy.fb')

# linux/kd.h — stop fbcon from drawing over our frames (blinking underscore)
_KDSETMODE = 0x4B3A
_KD_TEXT = 0
_KD_GRAPHICS = 1

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore
    _HAS_NUMPY = False


def _hide_tty_cursor() -> None:
    """ANSI / DEC hide-cursor on common console devices (best-effort)."""
    payload = b'\033[?25l\033[?1c'  # hide + soft cursor shape
    for tty in ('/dev/tty1', '/dev/tty0', '/dev/console'):
        try:
            fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY)
            try:
                os.write(fd, payload)
            finally:
                os.close(fd)
        except OSError:
            continue


def _unbind_fb_consoles() -> list[Path]:
    """
    Detach Linux fbcon from the framebuffer so it stops painting over us.

    Needs write access to /sys/class/vtconsole/*/bind (usually root).
    Returns paths we unbound so restore can re-bind.
    """
    unbound: list[Path] = []
    root = Path('/sys/class/vtconsole')
    if not root.is_dir():
        return unbound
    for vt in sorted(root.glob('vtcon*')):
        name_path = vt / 'name'
        bind_path = vt / 'bind'
        try:
            name = name_path.read_text().strip().lower()
        except OSError:
            continue
        if 'frame buffer' not in name and 'framebuffer' not in name:
            continue
        try:
            if bind_path.read_text().strip() == '1':
                bind_path.write_text('0')
                unbound.append(bind_path)
                logger.info('Unbound framebuffer console %s (%s)', vt.name, name)
        except OSError as exc:
            logger.warning('Cannot unbind %s (need root?): %s', bind_path, exc)
    return unbound


def suppress_fb_console() -> tuple[int | None, list[Path]]:
    """
    Hide Linux console cursor / stop fbcon painting on the framebuffer.

    Returns (tty_fd_in_graphics_mode_or_None, unbound_vt_bind_paths).
    """
    blink = Path('/sys/class/graphics/fbcon/cursor_blink')
    try:
        blink.write_text('0')
    except OSError as exc:
        logger.debug('cursor_blink: %s', exc)

    _hide_tty_cursor()
    unbound = _unbind_fb_consoles()

    tty_fd: int | None = None
    for tty in ('/dev/tty0', '/dev/tty1', '/dev/console'):
        try:
            fd = os.open(tty, os.O_RDWR)
            fcntl.ioctl(fd, _KDSETMODE, _KD_GRAPHICS)
            logger.info('Framebuffer console suppressed via %s (KD_GRAPHICS)', tty)
            tty_fd = fd
            break
        except OSError:
            continue
    if tty_fd is None and not unbound:
        logger.warning(
            'Could not suppress fbcon (permission?). Run once as root: '
            'echo 0 > /sys/class/graphics/fbcon/cursor_blink; '
            'for d in /sys/class/vtconsole/vtcon*; do '
            'grep -qi "frame buffer" "$d/name" && echo 0 > "$d/bind"; done'
        )
    return tty_fd, unbound


def restore_fb_console(tty_fd: int | None, unbound: list[Path] | None = None) -> None:
    if tty_fd is not None:
        try:
            fcntl.ioctl(tty_fd, _KDSETMODE, _KD_TEXT)
        except OSError:
            pass
        try:
            os.close(tty_fd)
        except OSError:
            pass
    for bind_path in unbound or ():
        try:
            bind_path.write_text('1')
        except OSError:
            pass


def rgb_image_to_rgb565(image: Image.Image) -> bytes:
    """Convert a PIL RGB image to little-endian RGB565 bytes."""
    if not _HAS_NUMPY:
        # Pure-Python pack is ~1s for 800×480 on Pi 3 — keep for tests only.
        rgb = image.convert('RGB').tobytes()
        out = bytearray((len(rgb) // 3) * 2)
        j = 0
        for i in range(0, len(rgb), 3):
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out[j] = v & 0xFF
            out[j + 1] = (v >> 8) & 0xFF
            j += 2
        return bytes(out)

    # Contiguous uint8 RGB → uint16 RGB565 (vectorized).
    arr = np.asarray(image.convert('RGB'), dtype=np.uint8)
    r = arr[:, :, 0].astype(np.uint16)
    g = arr[:, :, 1].astype(np.uint16)
    b = arr[:, :, 2].astype(np.uint16)
    rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return np.ascontiguousarray(rgb565, dtype='<u2').tobytes()


def read_fb_line_length(device: str = '/dev/fb0') -> int:
    try:
        name = Path(device).name
        return int(Path(f'/sys/class/graphics/{name}/stride').read_text().strip())
    except Exception:  # noqa: BLE001
        try:
            name = Path(device).name
            return int(Path(f'/sys/class/graphics/{name}/line_length').read_text().strip())
        except Exception:  # noqa: BLE001
            return 0


def read_fb_size(device: str = '/dev/fb0') -> tuple[int, int]:
    """Return (width, height) from sysfs, or (0, 0) if unavailable."""
    try:
        name = Path(device).name  # fb0
        raw = Path(f'/sys/class/graphics/{name}/virtual_size').read_text().strip()
        w, h = raw.split(',')
        return int(w), int(h)
    except Exception:  # noqa: BLE001
        return 0, 0


class FramebufferDisplay(Display):
    """
    Write RGB frames to a Linux framebuffer device (typical Waveshare 5\" 800×480).

    Expects 16-bit RGB565 (matches ``fbset`` rgba 5/11,6/5,5/0).
    """

    def __init__(
        self,
        device: str = '/dev/fb0',
        *,
        width: int = 800,
        height: int = 480,
    ):
        self.__device = device
        self.__width = int(width)
        self.__height = int(height)
        self.__bpp = 2  # RGB565
        stride = read_fb_line_length(device)
        self.__line_length = stride if stride >= self.__width * self.__bpp else self.__width * self.__bpp
        fb_w, fb_h = read_fb_size(device)
        if fb_w and fb_h and (fb_w != self.__width or fb_h != self.__height):
            logger.warning(
                'Framebuffer %s is %sx%s but app is %sx%s — using app size',
                device, fb_w, fb_h, self.__width, self.__height,
            )
        if not _HAS_NUMPY:
            logger.error(
                'numpy is not installed — RGB565 fallback is VERY slow on Pi '
                '(~1s/frame). Fix: .venv/bin/pip install numpy'
            )
        self.__console_tty_fd, self.__unbound_vt = suppress_fb_console()
        self.__fd = os.open(device, os.O_RDWR)
        size = self.__line_length * self.__height
        self.__mm = mmap.mmap(self.__fd, size, mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)
        self.__lock = threading.Lock()
        self.__canvas = Image.new('RGB', (self.__width, self.__height), (0, 0, 0))
        self.__defer_flush = 0
        self.__dirty: tuple[int, int, int, int] | None = None  # x0,y0,x1,y1 inclusive-exclusive
        self.__profile = os.environ.get('PIBOY_FB_PROFILE', '').strip() in ('1', 'true', 'yes')
        logger.info(
            'FramebufferDisplay %s %sx%s rgb565 stride=%s numpy=%s',
            device, self.__width, self.__height, self.__line_length, _HAS_NUMPY,
        )

    @property
    def size(self) -> tuple[int, int]:
        return self.__width, self.__height

    def begin_update(self) -> None:
        """Batch multiple show() calls into one framebuffer write."""
        with self.__lock:
            self.__defer_flush += 1

    def end_update(self) -> None:
        with self.__lock:
            if self.__defer_flush > 0:
                self.__defer_flush -= 1
            if self.__defer_flush == 0:
                self.__flush_dirty()

    def __mark_dirty(self, x0: int, y0: int, x1: int, y1: int) -> None:
        x0 = max(0, min(self.__width, int(x0)))
        y0 = max(0, min(self.__height, int(y0)))
        x1 = max(0, min(self.__width, int(x1)))
        y1 = max(0, min(self.__height, int(y1)))
        if x1 <= x0 or y1 <= y0:
            return
        if self.__dirty is None:
            self.__dirty = (x0, y0, x1, y1)
            return
        dx0, dy0, dx1, dy1 = self.__dirty
        self.__dirty = (min(dx0, x0), min(dy0, y0), max(dx1, x1), max(dy1, y1))

    def __flush_full(self) -> None:
        t0 = time.perf_counter() if self.__profile else 0.0
        data = rgb_image_to_rgb565(self.__canvas)
        self.__mm.seek(0)
        self.__mm.write(data)
        self.__dirty = None
        if self.__profile:
            logger.info('fb flush full %sms', round((time.perf_counter() - t0) * 1000, 1))

    def __flush_region(self, x0: int, y0: int, x1: int, y1: int) -> None:
        w = x1 - x0
        h = y1 - y0
        if w <= 0 or h <= 0:
            return
        if x0 == 0 and y0 == 0 and x1 == self.__width and y1 == self.__height:
            self.__flush_full()
            return
        t0 = time.perf_counter() if self.__profile else 0.0
        crop = self.__canvas.crop((x0, y0, x1, y1))
        data = rgb_image_to_rgb565(crop)
        row_bytes = w * self.__bpp
        for row in range(h):
            offset = (y0 + row) * self.__line_length + x0 * self.__bpp
            start = row * row_bytes
            self.__mm.seek(offset)
            self.__mm.write(data[start:start + row_bytes])
        if self.__profile:
            logger.info(
                'fb flush region %sx%s @%s,%s %sms',
                w, h, x0, y0, round((time.perf_counter() - t0) * 1000, 1),
            )
    def __flush_dirty(self) -> None:
        if self.__dirty is None:
            return
        x0, y0, x1, y1 = self.__dirty
        self.__flush_region(x0, y0, x1, y1)
        self.__dirty = None

    @override
    def show(self, image: Image.Image, x0: int, y0: int):
        with self.__lock:
            if image.size == (self.__width, self.__height) and x0 == 0 and y0 == 0:
                self.__canvas = image.convert('RGB')
                self.__mark_dirty(0, 0, self.__width, self.__height)
            else:
                rgb = image.convert('RGB')
                self.__canvas.paste(rgb, (int(x0), int(y0)))
                self.__mark_dirty(int(x0), int(y0), int(x0) + rgb.size[0], int(y0) + rgb.size[1])
            if self.__defer_flush == 0:
                self.__flush_dirty()

    @override
    def close(self):
        with self.__lock:
            try:
                self.__mm.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                os.close(self.__fd)
            except Exception:  # noqa: BLE001
                pass
            restore_fb_console(self.__console_tty_fd, self.__unbound_vt)
            self.__console_tty_fd = None
            self.__unbound_vt = []

    def reset(self):
        with self.__lock:
            self.__canvas = Image.new('RGB', (self.__width, self.__height), (0, 0, 0))
            self.__dirty = (0, 0, self.__width, self.__height)
            if self.__defer_flush == 0:
                self.__flush_dirty()
