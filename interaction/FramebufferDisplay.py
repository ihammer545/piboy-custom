"""Linux framebuffer display (/dev/fb0) for 800×480 RGB565 panels."""

from __future__ import annotations

import fcntl
import logging
import mmap
import os
import threading
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


def suppress_fb_console() -> int | None:
    """
    Hide Linux console cursor / stop fbcon painting on the framebuffer.

    Returns the tty fd kept open in graphics mode, or None if unavailable.
    Caller should pass it to restore_fb_console() on shutdown.
    """
    blink = Path('/sys/class/graphics/fbcon/cursor_blink')
    try:
        blink.write_text('0')
    except OSError:
        pass

    for tty in ('/dev/tty0', '/dev/tty1', '/dev/console'):
        try:
            fd = os.open(tty, os.O_RDWR)
            fcntl.ioctl(fd, _KDSETMODE, _KD_GRAPHICS)
            logger.info('Framebuffer console suppressed via %s (KD_GRAPHICS)', tty)
            return fd
        except OSError:
            continue
    logger.warning('Could not switch VT to KD_GRAPHICS (cursor may still blink)')
    return None


def restore_fb_console(tty_fd: int | None) -> None:
    if tty_fd is None:
        return
    try:
        fcntl.ioctl(tty_fd, _KDSETMODE, _KD_TEXT)
    except OSError:
        pass
    try:
        os.close(tty_fd)
    except OSError:
        pass


def rgb_image_to_rgb565(image: Image.Image) -> bytes:
    """Convert a PIL RGB image to little-endian RGB565 bytes."""
    if _HAS_NUMPY:
        arr = np.asarray(image.convert('RGB'), dtype=np.uint16)
        r = arr[:, :, 0]
        g = arr[:, :, 1]
        b = arr[:, :, 2]
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        return rgb565.astype('<u2').tobytes()

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
        self.__line_length = self.__width * self.__bpp
        fb_w, fb_h = read_fb_size(device)
        if fb_w and fb_h and (fb_w != self.__width or fb_h != self.__height):
            logger.warning(
                'Framebuffer %s is %sx%s but app is %sx%s — using app size',
                device, fb_w, fb_h, self.__width, self.__height,
            )
        self.__console_tty_fd = suppress_fb_console()
        self.__fd = os.open(device, os.O_RDWR)
        size = self.__line_length * self.__height
        self.__mm = mmap.mmap(self.__fd, size, mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)
        self.__lock = threading.Lock()
        self.__canvas = Image.new('RGB', (self.__width, self.__height), (0, 0, 0))
        logger.info('FramebufferDisplay %s %sx%s rgb565', device, self.__width, self.__height)

    @property
    def size(self) -> tuple[int, int]:
        return self.__width, self.__height

    def __flush(self) -> None:
        data = rgb_image_to_rgb565(self.__canvas)
        self.__mm.seek(0)
        self.__mm.write(data)

    @override
    def show(self, image: Image.Image, x0: int, y0: int):
        with self.__lock:
            if image.size == (self.__width, self.__height) and x0 == 0 and y0 == 0:
                self.__canvas = image.convert('RGB')
            else:
                self.__canvas.paste(image.convert('RGB'), (int(x0), int(y0)))
            self.__flush()

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
            restore_fb_console(self.__console_tty_fd)
            self.__console_tty_fd = None

    def reset(self):
        with self.__lock:
            self.__canvas = Image.new('RGB', (self.__width, self.__height), (0, 0, 0))
            self.__flush()
