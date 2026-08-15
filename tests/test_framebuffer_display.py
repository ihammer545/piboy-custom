"""Tests for FramebufferDisplay RGB565 packing (no /dev/fb required)."""
from __future__ import annotations

from PIL import Image

from interaction.FramebufferDisplay import rgb_image_to_rgb565


def test_rgb565_pack_known_colors():
    img = Image.new('RGB', (2, 1))
    img.putpixel((0, 0), (255, 0, 0))    # red
    img.putpixel((1, 0), (0, 255, 0))    # green
    data = rgb_image_to_rgb565(img)
    assert len(data) == 4
    # little-endian uint16
    red = int.from_bytes(data[0:2], 'little')
    green = int.from_bytes(data[2:4], 'little')
    assert red == 0xF800
    assert green == 0x07E0


def test_rgb565_size_matches_pixels():
    img = Image.new('RGB', (800, 480), (27, 251, 30))
    data = rgb_image_to_rgb565(img)
    assert len(data) == 800 * 480 * 2
