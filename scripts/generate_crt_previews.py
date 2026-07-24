#!/usr/bin/env python3
"""Generate CRT preview PNGs under docs/crt/ (headless)."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rendering.crt import CRTRenderer, resolve_crt_settings


OUT = ROOT / 'docs' / 'crt'


def _font(size: int):
    for name in ('DejaVuSans.ttf', 'FreeSans.ttf', 'Arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_calibration() -> Image.Image:
    img = Image.new('RGB', (800, 480), (0, 0, 0))
    d = ImageDraw.Draw(img)
    # Dark green gradients
    for i, g in enumerate((2, 6, 12, 24, 48, 96)):
        d.rectangle((40 + i * 50, 40, 80 + i * 50, 100), fill=(0, g, 0))
    # Grid
    for x in range(0, 800, 40):
        d.line((x, 0, x, 479), fill=(0, 28, 0))
    for y in range(0, 480, 40):
        d.line((0, y, 799, y), fill=(0, 28, 0))
    # Edge frame
    d.rectangle((2, 2, 797, 477), outline=(27, 251, 30), width=2)
    # Center circle
    d.ellipse((340, 180, 460, 300), outline=(27, 251, 30), width=2)
    # Corner markers
    for x0, y0 in ((20, 20), (760, 20), (20, 440), (760, 440)):
        d.rectangle((x0, y0, x0 + 20, y0 + 20), outline=(27, 251, 30), width=2)
    small = _font(14)
    large = _font(28)
    d.text((120, 200), 'SMALL phosphor text', fill=(27, 251, 30), font=small)
    d.text((120, 320), 'LARGE CRT TEXT', fill=(27, 251, 30), font=large)
    d.text((500, 220), 'CAL', fill=(27, 180, 30), font=large)
    return img


def make_ui_sample() -> Image.Image:
    img = Image.new('RGB', (800, 480), (0, 0, 0))
    d = ImageDraw.Draw(img)
    font = _font(16)
    # Fake tabs
    tabs = ['SVZ', 'DOST', 'SRED', 'SIST', 'LOG', 'SERV']
    for i, t in enumerate(tabs):
        x0 = 24 + i * 120
        fill = (0, 40, 0) if i == 0 else (0, 0, 0)
        d.rectangle((x0, 4, x0 + 110, 36), outline=(27, 251, 30), fill=fill)
        d.text((x0 + 12, 10), t, fill=(27, 251, 30), font=font)
    d.rectangle((24, 48, 776, 420), outline=(27, 251, 30))
    d.rectangle((40, 70, 760, 110), fill=(0, 48, 0), outline=(27, 251, 30))
    d.text((56, 80), 'Selected row — phosphor glass check', fill=(27, 251, 30), font=font)
    d.text((56, 140), 'Idle line on black background', fill=(9, 64, 9), font=font)
    d.text((56, 180), 'Another dim line', fill=(9, 64, 9), font=font)
    d.rectangle((0, 444, 799, 479), outline=(9, 64, 9))
    d.text((24, 452), 'footer status 12:00', fill=(27, 251, 30), font=font)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    calib = make_calibration()
    ui = make_ui_sample()
    calib.save(OUT / 'calibration.png')
    for preset in ('off', 'subtle', 'strong'):
        crt = CRTRenderer(resolve_crt_settings(preset=preset, grain_seed=42))
        frame = ui if preset != 'off' else ui
        # Use calibration for off/subtle/strong comparison of geometry too
        src = calib
        out = crt.process(src, now=3.0, ui_changed=True)
        out.save(OUT / f'{preset}.png')
        print(f'wrote {OUT / (preset + ".png")}')
    print(f'wrote {OUT / "calibration.png"}')


if __name__ == '__main__':
    main()
