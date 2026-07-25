#!/usr/bin/env python3
"""Generate short UI WAVs (mono 16-bit 22050 Hz).

Key/touch use a mechanical-keyboard model (impact noise + housing modes),
not tonal square-wave beeps.
"""
from __future__ import annotations

import math
import random
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


def _clamp(v: float) -> int:
    return max(-32767, min(32767, int(v)))


def _trim_leading(samples: list[int], thresh: int = 120) -> list[int]:
    while samples and abs(samples[0]) < thresh:
        samples.pop(0)
    return samples


def _norm_peak(samples: list[float], peak: float) -> list[int]:
    m = max((abs(x) for x in samples), default=1.0)
    if m < 1e-9:
        return [0] * len(samples)
    scale = peak / m
    return [_clamp(x * scale) for x in samples]


def mech_click(
    *,
    seed: int,
    ms: float = 58,
    peak: float = 16000,
    bright: float = 1.0,
    body: float = 1.0,
    pitch: float = 1.0,
) -> list[int]:
    """Classic mechanical key: plastic impact + short case 'clack', not a sine beep."""
    rng = random.Random(seed)
    n = int(RATE * ms / 1000)
    out = [0.0] * n

    # 1) Stem/housing impact — broadband noise, ~1–3 ms, high-pass-ish.
    impact_n = max(8, int(RATE * (0.0012 + 0.0018 * bright)))
    lp = 0.0
    for i in range(min(impact_n + 40, n)):
        t = i / RATE
        noise = rng.uniform(-1.0, 1.0)
        # crude 1-pole HP via differencing + light LP on residual
        hp = noise - lp
        lp = lp * 0.35 + noise * 0.65
        env = math.exp(-t * (900 + 500 * bright))
        out[i] += hp * env * (0.95 * bright + 0.35)

    # 2) Click-leaf / buckling tick — short mid-high ring (classic Blue/Model-M bite).
    tick_f = (2850 + rng.uniform(-180, 220)) * pitch
    tick_amp = 0.55 * bright
    for i in range(n):
        t = i / RATE
        env = math.exp(-t * (70 + 40 * bright))
        out[i] += math.sin(2 * math.pi * tick_f * t) * env * tick_amp
        out[i] += math.sin(2 * math.pi * tick_f * 1.7 * t) * env * tick_amp * 0.22

    # 3) Case / plate body — lower damped modes (the audible “clack”, not a beep).
    modes = [
        ((420 + rng.uniform(-40, 50)) * pitch, 28.0, 0.55 * body),
        ((780 + rng.uniform(-60, 70)) * pitch, 38.0, 0.42 * body),
        ((1180 + rng.uniform(-80, 90)) * pitch, 48.0, 0.22 * body * bright),
    ]
    for freq, damp, amp in modes:
        phase = rng.uniform(0, math.pi * 2)
        for i in range(n):
            t = i / RATE
            out[i] += math.sin(2 * math.pi * freq * t + phase) * math.exp(-t * damp) * amp

    # 4) Tiny secondary plastic slap ~4–8 ms later (stabilizer / bottom-out feel).
    slap_at = int(RATE * (0.004 + rng.uniform(0, 0.004)))
    slap_len = int(RATE * 0.0025)
    for j in range(slap_len):
        i = slap_at + j
        if i >= n:
            break
        t = j / RATE
        noise = rng.uniform(-1.0, 1.0)
        out[i] += noise * math.exp(-t * 1200) * (0.28 + 0.12 * bright)

    return _trim_leading(_norm_peak(out, peak))


def tone_sweep(f0: float, f1: float, ms: float = 50, amp: int = 10000) -> list[int]:
    n = int(RATE * ms / 1000)
    out: list[int] = []
    for i in range(n):
        t = i / RATE
        frac = t / (ms / 1000)
        f = f0 + (f1 - f0) * frac
        env = math.sin(math.pi * min(1.0, frac * 1.1)) * (1 - frac * 0.3)
        val = env * math.sin(2 * math.pi * f * t) * amp
        out.append(_clamp(val))
    return _trim_leading(out)


def buzz(freq: float = 220, ms: float = 70, amp: int = 9000) -> list[int]:
    n = int(RATE * ms / 1000)
    out: list[int] = []
    for i in range(n):
        t = i / RATE
        env = 1.0 - t / (ms / 1000)
        val = env * (1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0) * amp
        val *= 0.7 + 0.3 * math.sin(2 * math.pi * 30 * t)
        out.append(_clamp(val))
    return _trim_leading(out)


def lock_clack(ms: float = 55, amp: int = 12000) -> list[int]:
    # Heavier latch — reuse mechanical body with stronger low end.
    return mech_click(seed=99, ms=ms, peak=amp, bright=0.75, body=1.35, pitch=0.82)


def _silence(ms: float) -> list[float]:
    return [0.0] * max(0, int(RATE * ms / 1000))


def _square_beep(freq: float, ms: float, amp: float = 0.55) -> list[float]:
    """PC-speaker style square beep (POST)."""
    n = int(RATE * ms / 1000)
    out: list[float] = []
    for i in range(n):
        t = i / RATE
        # Soft edges so it does not click harshly at start/end.
        edge = min(1.0, i / (RATE * 0.004), (n - i) / (RATE * 0.006))
        sq = 1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0
        out.append(sq * amp * edge)
    return out


def _mix_at(buf: list[float], offset: int, chunk: list[float], gain: float = 1.0) -> None:
    need = offset + len(chunk)
    if need > len(buf):
        buf.extend([0.0] * (need - len(buf)))
    for i, v in enumerate(chunk):
        buf[offset + i] += v * gain


def _floppy_motor(rng: random.Random, ms: float, amp: float = 0.22) -> list[float]:
    """Low rumble + soft grit while the spindle spins."""
    n = int(RATE * ms / 1000)
    out: list[float] = []
    phase = 0.0
    for i in range(n):
        t = i / RATE
        # Spin-up then steady.
        spin = min(1.0, t / 0.18) * (0.85 + 0.15 * math.sin(2 * math.pi * 2.2 * t))
        # ~90–120 Hz mechanical hum + slow wow.
        f = 95.0 + 12.0 * math.sin(2 * math.pi * 0.7 * t)
        phase += 2 * math.pi * f / RATE
        hum = math.sin(phase) * 0.55 + math.sin(phase * 2.01) * 0.18
        grit = (rng.random() * 2 - 1) * 0.12
        fade = 1.0
        if t < 0.05:
            fade = t / 0.05
        elif t > ms / 1000 - 0.08:
            fade = max(0.0, (ms / 1000 - t) / 0.08)
        out.append((hum + grit) * amp * spin * fade)
    return out


def _floppy_seek(rng: random.Random, steps: int, step_ms: float = 28.0, amp: float = 0.45) -> list[float]:
    """Head stepper: rapid chirps / ticks while seeking tracks."""
    out: list[float] = []
    for s in range(steps):
        step: list[float] = []
        # Slight pitch drift across the seek (closer/farther tracks).
        base = 1450 + s * 35 + rng.uniform(-40, 40)
        n = int(RATE * step_ms / 1000)
        for i in range(n):
            t = i / RATE
            env = math.exp(-t * 95) * (1.0 if i > 2 else i / 2)
            tick = 1.0 if math.sin(2 * math.pi * base * t) >= 0 else -1.0
            body = math.sin(2 * math.pi * (base * 0.45) * t) * math.exp(-t * 55)
            noise = (rng.random() * 2 - 1) * math.exp(-t * 180) * 0.25
            step.append((0.55 * tick + 0.35 * body + noise) * amp * env)
        # Tiny gap between steps.
        step.extend(_silence(rng.uniform(2, 6)))
        out.extend(step)
    return out


def _floppy_read(rng: random.Random, ms: float, amp: float = 0.28) -> list[float]:
    """Busy read whir — filtered noise with periodic flutter."""
    n = int(RATE * ms / 1000)
    out: list[float] = []
    lp = 0.0
    for i in range(n):
        t = i / RATE
        noise = rng.random() * 2 - 1
        lp = lp * 0.82 + noise * 0.18
        flutter = 0.75 + 0.25 * math.sin(2 * math.pi * 18 * t + rng.random())
        pulse = 0.15 * math.sin(2 * math.pi * 7.5 * t) ** 2
        fade = min(1.0, t / 0.04, max(0.0, (ms / 1000 - t) / 0.06))
        out.append((lp * flutter + pulse) * amp * fade)
    return out


def old_pc_boot(*, seed: int = 1984, seconds: float = 7.2, peak: float = 14000) -> list[int]:
    """POST beep + floppy seek/read sequence for the splash / boot window (~5–10 s)."""
    rng = random.Random(seed)
    buf: list[float] = []

    # Power-on hush
    _mix_at(buf, 0, _silence(180))

    # Classic single POST beep (~1 kHz PC speaker), then a short pause.
    beep_at = len(buf)
    _mix_at(buf, beep_at, _square_beep(1000, 280, amp=0.62))
    _mix_at(buf, len(buf), _silence(420))

    # Drive A: motor + seek + read
    motor_a = _floppy_motor(rng, 2200, amp=0.20)
    _mix_at(buf, len(buf), motor_a)
    # Overlap seek near the end of spin-up
    seek_a_at = len(buf) - int(RATE * 1.55)
    seek_a = _floppy_seek(rng, steps=14, step_ms=26, amp=0.48)
    _mix_at(buf, max(0, seek_a_at), seek_a, gain=1.0)
    _mix_at(buf, len(buf), _silence(80))
    _mix_at(buf, len(buf), _floppy_read(rng, 900, amp=0.26))
    _mix_at(buf, len(buf), _silence(220))

    # Drive B (or second pass): shorter check
    motor_b_at = len(buf)
    _mix_at(buf, motor_b_at, _floppy_motor(rng, 1600, amp=0.17))
    seek_b = _floppy_seek(rng, steps=9, step_ms=30, amp=0.42)
    _mix_at(buf, motor_b_at + int(RATE * 0.35), seek_b)
    _mix_at(buf, len(buf), _floppy_read(rng, 650, amp=0.22))
    _mix_at(buf, len(buf), _silence(150))

    # Soft settle click (head park)
    park = mech_click(seed=seed + 7, ms=70, peak=9000, bright=0.55, body=1.2, pitch=0.7)
    park_f = [s / 32767.0 for s in park]
    _mix_at(buf, len(buf), park_f, gain=0.55)
    _mix_at(buf, len(buf), _silence(200))

    # Pad / trim to target length for splash timing.
    target = int(RATE * seconds)
    if len(buf) < target:
        buf.extend(_silence((target - len(buf)) * 1000 / RATE))
    elif len(buf) > target + int(RATE * 0.4):
        buf = buf[:target]

    return _norm_peak(buf, peak)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Keyboard: brighter click-leaf + crisp impact (classic mech).
    write_wav('key_a.wav', mech_click(seed=11, ms=56, peak=16800, bright=1.05, body=1.0, pitch=1.00))
    write_wav('key_b.wav', mech_click(seed=23, ms=60, peak=16200, bright=1.00, body=1.05, pitch=0.96))
    write_wav('key_c.wav', mech_click(seed=37, ms=54, peak=17000, bright=1.10, body=0.95, pitch=1.04))
    # Touch: same family, slightly softer / lower (still mechanical, not a beep).
    write_wav('touch_a.wav', mech_click(seed=41, ms=62, peak=14500, bright=0.82, body=1.15, pitch=0.90))
    write_wav('touch_b.wav', mech_click(seed=53, ms=64, peak=14000, bright=0.78, body=1.20, pitch=0.86))
    write_wav('touch_c.wav', mech_click(seed=67, ms=58, peak=14800, bright=0.85, body=1.10, pitch=0.93))
    write_wav('confirm.wav', tone_sweep(700, 1100, 55, 11000))
    write_wav('back.wav', tone_sweep(900, 500, 45, 9000))
    write_wav('denied.wav', buzz(210, 75, 8500))
    write_wav('lock.wav', lock_clack())
    # Splash / initial loading window (UiSoundEvent.BOOT).
    write_wav('boot.wav', old_pc_boot(seconds=7.2))
    total = sum(p.stat().st_size for p in OUT.glob('*.wav'))
    print('total', total, 'bytes')


if __name__ == '__main__':
    main()
