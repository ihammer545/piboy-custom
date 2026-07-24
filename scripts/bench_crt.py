#!/usr/bin/env python3
"""Headless CRT benchmark (no Tk required)."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from statistics import mean

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rendering.crt import CRTRenderer, resolve_crt_settings


def make_frame() -> Image.Image:
    img = Image.new('RGB', (800, 480), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((40, 40, 760, 440), outline=(27, 251, 30), width=2)
    d.text((60, 60), 'СВЯЗЬ / ДОСТУП / СРЕДА', fill=(27, 251, 30))
    d.rectangle((60, 120, 300, 160), outline=(27, 251, 30))
    return img


def bench(label: str, preset: str, n: int = 100, grain: float | None = None) -> dict:
    settings = resolve_crt_settings(preset=preset, grain=grain, flicker=0 if preset == 'off' else None)
    crt = CRTRenderer(settings)
    frame = make_frame()
    # Warmup / build static cache
    crt.process(frame, now=0.0)
    cache_after_static = crt.cache_bytes()
    times = []
    t0 = time.perf_counter()
    for i in range(n):
        t1 = time.perf_counter()
        crt.process(frame, now=i * 0.05, ui_changed=(i % 10 == 0))
        times.append(time.perf_counter() - t1)
    total = time.perf_counter() - t0
    return {
        'label': label,
        'preset': preset,
        'n': n,
        'avg_ms': mean(times) * 1000,
        'total_s': total,
        'cache_bytes': crt.cache_bytes(),
        'cache_after_static': cache_after_static,
    }


def main():
    frame = make_frame()
    # Baseline: copy only
    times = []
    for _ in range(100):
        t1 = time.perf_counter()
        _ = frame.copy()
        times.append(time.perf_counter() - t1)
    print(f"baseline copy avg_ms={mean(times)*1000:.3f} size={frame.size}")

    for label, preset, grain in (
        ('off', 'off', None),
        ('subtle', 'subtle', None),
        ('subtle_static_grain0', 'subtle', 0.0),
        ('strong', 'strong', None),
    ):
        r = bench(label, preset, grain=grain)
        print(
            f"{r['label']}: avg_ms={r['avg_ms']:.3f} total_s={r['total_s']:.3f} "
            f"cache_bytes={r['cache_bytes']} (static~{r['cache_after_static']})"
        )


if __name__ == '__main__':
    main()
