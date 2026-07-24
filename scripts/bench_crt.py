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
    d.text((60, 60), 'SVZ / DOST / SRED', fill=(27, 251, 30))
    d.rectangle((60, 120, 300, 160), outline=(27, 251, 30))
    return img


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def bench(label: str, **settings_kw) -> dict:
    settings = resolve_crt_settings(**settings_kw)
    crt = CRTRenderer(settings)
    frame = make_frame()
    crt.process(frame, now=0.0, ui_changed=True)
    cache_after_static = crt.cache_bytes()
    times = []
    n = 100
    for i in range(n):
        t1 = time.perf_counter()
        # Alternate grain updates vs static; every 10th marks ui_changed
        crt.process(frame, now=i * 0.05, ui_changed=(i % 10 == 0))
        times.append(time.perf_counter() - t1)
    times_sorted = sorted(times)
    return {
        'label': label,
        'avg_ms': mean(times) * 1000,
        'p95_ms': percentile(times_sorted, 95) * 1000,
        'cache_bytes': crt.cache_bytes(),
        'cache_after_static': cache_after_static,
        'curvature': settings.curvature,
        'grain': settings.grain,
    }


def main():
    frame = make_frame()
    times = []
    for _ in range(100):
        t1 = time.perf_counter()
        _ = frame.copy()
        times.append(time.perf_counter() - t1)
    print(f"baseline copy avg_ms={mean(times)*1000:.3f} size={frame.size}")

    cases = [
        ('off', dict(preset='off')),
        ('subtle', dict(preset='subtle')),
        ('strong', dict(preset='strong')),
        ('subtle_no_curvature', dict(preset='subtle', curvature=0.0)),
        ('strong_no_grain', dict(preset='strong', grain=0.0)),
        ('subtle_static_grain0', dict(preset='subtle', grain=0.0, flicker=0.0)),
    ]
    for label, kw in cases:
        r = bench(label, **kw)
        print(
            f"{r['label']}: avg_ms={r['avg_ms']:.3f} p95_ms={r['p95_ms']:.3f} "
            f"cache_bytes={r['cache_bytes']} curv={r['curvature']} grain={r['grain']}"
        )


if __name__ == '__main__':
    main()
