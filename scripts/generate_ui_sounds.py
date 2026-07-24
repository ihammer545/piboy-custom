#!/usr/bin/env python3
"""Generate short mechanical UI click WAVs (mono 16-bit 22050 Hz)."""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'resources' / 'sounds'
RATE = 22050


def write_wav(name: str, samples: list[int]) -> None:
    path = OUT / name
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(struct.pack('<' + 'h' * len(samples), *samples))
    print(path.relative_to(ROOT), f'{len(samples) / RATE * 1000:.1f}ms', path.stat().st_size, 'bytes')


def click(freq: float, ms: float = 35, amp: int = 14000, decay: float = 2.2, phase: float = 0.0) -> list[int]:
    n = int(RATE * ms / 1000)
    out: list[int] = []
    for i in range(n):
        t = i / RATE
        env = (1.0 - t / (ms / 1000)) ** decay
        sq = 1.0 if math.sin(2 * math.pi * freq * t + phase) >= 0 else -1.0
        harm = 0.25 * math.sin(2 * math.pi * freq * 2 * t + phase)
        val = env * (0.75 * sq + harm) * amp
        out.append(max(-32767, min(32767, int(val))))
    while out and abs(out[0]) < 200:
        out.pop(0)
    return out


def tone_sweep(f0: float, f1: float, ms: float = 50, amp: int = 10000) -> list[int]:
    n = int(RATE * ms / 1000)
    out: list[int] = []
    for i in range(n):
        t = i / RATE
        frac = t / (ms / 1000)
        f = f0 + (f1 - f0) * frac
        env = math.sin(math.pi * min(1.0, frac * 1.1)) * (1 - frac * 0.3)
        val = env * math.sin(2 * math.pi * f * t) * amp
        out.append(max(-32767, min(32767, int(val))))
    while out and abs(out[0]) < 150:
        out.pop(0)
    return out


def buzz(freq: float = 220, ms: float = 70, amp: int = 9000) -> list[int]:
    n = int(RATE * ms / 1000)
    out: list[int] = []
    for i in range(n):
        t = i / RATE
        env = 1.0 - t / (ms / 1000)
        val = env * (1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0) * amp
        val *= 0.7 + 0.3 * math.sin(2 * math.pi * 30 * t)
        out.append(max(-32767, min(32767, int(val))))
    while out and abs(out[0]) < 150:
        out.pop(0)
    return out


def lock_clack(ms: float = 55, amp: int = 12000) -> list[int]:
    n = int(RATE * ms / 1000)
    out: list[int] = []
    for i in range(n):
        t = i / RATE
        env = math.exp(-t * 40)
        a = math.sin(2 * math.pi * 480 * t) * env
        b = math.sin(2 * math.pi * 180 * t) * math.exp(-t * 18) * 0.6
        out.append(max(-32767, min(32767, int((a + b) * amp))))
    while out and abs(out[0]) < 150:
        out.pop(0)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_wav('key_a.wav', click(1750, 28, phase=0.1))
    write_wav('key_b.wav', click(1850, 30, phase=0.4))
    write_wav('key_c.wav', click(1650, 26, phase=0.7))
    write_wav('touch_a.wav', click(1350, 32, amp=12000, phase=0.2))
    write_wav('touch_b.wav', click(1450, 34, amp=11500, phase=0.5))
    write_wav('touch_c.wav', click(1250, 30, amp=12500, phase=0.9))
    write_wav('confirm.wav', tone_sweep(700, 1100, 55, 11000))
    write_wav('back.wav', tone_sweep(900, 500, 45, 9000))
    write_wav('denied.wav', buzz(210, 75, 8500))
    write_wav('lock.wav', lock_clack())
    total = sum(p.stat().st_size for p in OUT.glob('*.wav'))
    print('total', total, 'bytes')


if __name__ == '__main__':
    main()
