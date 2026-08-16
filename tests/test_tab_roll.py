"""Tab-switch vertical V-hold roll."""
from __future__ import annotations

from PIL import Image, ImageDraw

from rendering.tab_roll import apply_tab_roll, compute_tab_roll


def test_compute_tab_roll_settles():
    start = compute_tab_roll(0.0, duration_s=1.4)
    mid = compute_tab_roll(0.5, duration_s=1.4)
    end = compute_tab_roll(1.4, duration_s=1.4)
    assert not start.done and start.ghost > 0 and abs(start.offset_frac) > 0
    assert not mid.done
    assert mid.ghost < start.ghost
    assert end.done and end.offset_frac == 0 and end.ghost == 0


def test_apply_tab_roll_wraps_and_ghosts():
    img = Image.new('RGB', (80, 60), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 79, 9), fill=(0, 255, 0))
    out = apply_tab_roll(img, offset_frac=0.25, ghost=0.0)
    assert out.size == img.size
    # Band at y=0..9 shifted down by 15px
    assert out.getpixel((40, 0)) == (0, 0, 0)
    assert out.getpixel((40, 15)) == (0, 255, 0)
