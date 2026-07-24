"""Output device selection for UI sounds (no open() probes)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class AudioDeviceInfo:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float
    host_api: str = ''
    is_default_output: bool = False


def is_output_device(dev: AudioDeviceInfo) -> bool:
    return int(dev.max_output_channels) > 0


def _prefer_host(host_api: str) -> int:
    """Lower score = better. Prefer ALSA / Core Audio; deprioritize JACK."""
    h = (host_api or '').lower()
    if 'jack' in h:
        return 50
    if 'alsa' in h:
        return 0
    if 'core audio' in h or 'coreaudio' in h:
        return 0
    if 'pulse' in h:
        return 1
    return 10


def select_output_device(
    devices: Sequence[AudioDeviceInfo],
    *,
    configured_index: int | None = None,
    configured_name: str | None = None,
    default_output_index: int | None = None,
) -> tuple[Optional[AudioDeviceInfo], str]:
    """
    Pick an output device without opening streams.

    Returns (device, reason) where reason is:
      - ``configured_index`` / ``configured_name`` when user config/env applied
      - ``default`` / ``first_output`` for auto selection

    Input-only devices are skipped. JACK-only hosts are deprioritized.
    """
    outputs = [d for d in devices if is_output_device(d)]
    if not outputs:
        return None, 'none'

    if configured_index is not None:
        for d in outputs:
            if d.index == int(configured_index):
                return d, 'configured_index'
        # Invalid configured index — fall through to name / default / first.

    if configured_name:
        needle = configured_name.lower().strip()
        matches = [d for d in outputs if needle in d.name.lower()]
        if matches:
            matches.sort(key=lambda d: (_prefer_host(d.host_api), d.index))
            return matches[0], 'configured_name'

    if default_output_index is not None:
        for d in outputs:
            if d.index == int(default_output_index):
                return d, 'default'

    marked = [d for d in outputs if d.is_default_output]
    if marked:
        marked.sort(key=lambda d: (_prefer_host(d.host_api), d.index))
        return marked[0], 'default'

    outputs_sorted = sorted(outputs, key=lambda d: (_prefer_host(d.host_api), d.index))
    return outputs_sorted[0], 'first_output'


def choose_stream_channels(device: AudioDeviceInfo, prefer: int = 1) -> int:
    """Use stereo when the device cannot do mono or has ≥2 outputs."""
    max_out = int(device.max_output_channels)
    if max_out <= 0:
        return prefer
    if prefer == 1 and max_out >= 1:
        # Many ALSA devices advertise 2; mono often fails — prefer 2 when available.
        return 2 if max_out >= 2 else 1
    return min(prefer, max_out)


def choose_stream_rate(device: AudioDeviceInfo, source_rate: int = 22050) -> int:
    """Prefer device default if 44100/48000; else source rate."""
    raw = float(device.default_sample_rate or source_rate)
    rate = int(round(raw))
    if rate in (44100, 48000, 22050, 16000, 32000):
        return rate
    # Fall back to common rates
    if abs(raw - 48000) < abs(raw - 44100):
        return 48000
    return 44100
