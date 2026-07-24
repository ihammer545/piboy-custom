"""PCM helpers for UI sounds (16-bit little-endian)."""

from __future__ import annotations

import struct


def mono_to_stereo_s16(pcm: bytes) -> bytes:
    """Duplicate each mono sample to L/R. Keeps pitch and duration."""
    if not pcm:
        return pcm
    samples = struct.unpack('<' + 'h' * (len(pcm) // 2), pcm)
    stereo: list[int] = []
    for s in samples:
        stereo.append(s)
        stereo.append(s)
    return struct.pack('<' + 'h' * len(stereo), *stereo)


def resample_mono_s16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linear resample mono s16. Identity when rates match."""
    if src_rate == dst_rate or not pcm:
        return pcm
    if src_rate <= 0 or dst_rate <= 0:
        return pcm
    src = struct.unpack('<' + 'h' * (len(pcm) // 2), pcm)
    if len(src) < 2:
        return pcm
    duration = (len(src) - 1) / float(src_rate)
    n_dst = max(1, int(round(duration * dst_rate)) + 1)
    out: list[int] = []
    for i in range(n_dst):
        t = i / float(dst_rate)
        src_pos = t * src_rate
        i0 = int(src_pos)
        if i0 >= len(src) - 1:
            out.append(src[-1])
            continue
        frac = src_pos - i0
        s0 = src[i0]
        s1 = src[i0 + 1]
        sample = int(s0 * (1.0 - frac) + s1 * frac)
        out.append(max(-32768, min(32767, sample)))
    return struct.pack('<' + 'h' * len(out), *out)


def prepare_pcm_for_device(
    pcm: bytes,
    *,
    src_rate: int,
    src_channels: int,
    dst_rate: int,
    dst_channels: int,
) -> bytes:
    """Convert preloaded mono/stereo s16 to the open stream format (once at preload)."""
    if src_channels != 1:
        # Expect mono assets; take left if somehow stereo.
        samples = struct.unpack('<' + 'h' * (len(pcm) // 2), pcm)
        mono = samples[0::src_channels]
        pcm = struct.pack('<' + 'h' * len(mono), *mono)
        src_channels = 1
    if src_rate != dst_rate:
        pcm = resample_mono_s16(pcm, src_rate, dst_rate)
    if dst_channels >= 2:
        pcm = mono_to_stereo_s16(pcm)
    elif dst_channels != 1:
        # Unusual channel count — leave mono (open path should avoid this).
        pass
    return pcm
