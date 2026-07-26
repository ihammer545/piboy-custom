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


_ABSTRACT_NAME_TOKENS = (
    'default', 'null', 'dbus', 'jack', 'speex', 'pulse', 'surround',
)
_CONCRETE_NAME_TOKENS = (
    'hw:', 'plughw', 'hda', 'analog', 'usb', 'bcm2835', 'headphones',
    'speaker', 'hdmi',
)


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


def is_abstract_output_name(name: str) -> bool:
    """True for PortAudio abstract sinks that often open but stay silent."""
    n = (name or '').lower().strip()
    if not n:
        return True
    # Exact-ish abstract device labels
    if n in ('default', 'null', 'pulse', 'jack', 'dbus'):
        return True
    for tok in _ABSTRACT_NAME_TOKENS:
        if n == tok or n.startswith(tok + ' ') or n.startswith(tok + ':'):
            return True
    # "default" appearing as whole word in short names
    if n == 'sysdefault' or n.startswith('sysdefault'):
        return True
    return False


def is_concrete_output_name(name: str) -> bool:
    n = (name or '').lower()
    return any(tok in n for tok in _CONCRETE_NAME_TOKENS)


def device_rank_key(dev: AudioDeviceInfo) -> tuple:
    """Lower tuple = better candidate for auto selection."""
    abstract = 1 if is_abstract_output_name(dev.name) else 0
    concrete = 0 if is_concrete_output_name(dev.name) else 1
    # Prefer marked default only among concrete devices; abstract defaults last.
    default_pen = 0 if (dev.is_default_output and not abstract) else (2 if abstract else 1)
    return (
        abstract,
        concrete,
        _prefer_host(dev.host_api),
        default_pen,
        int(dev.index),
    )


def rank_output_devices(devices: Sequence[AudioDeviceInfo]) -> list[AudioDeviceInfo]:
    """All output devices, best-first (concrete ALSA/hw before abstract default)."""
    outputs = [d for d in devices if is_output_device(d)]
    return sorted(outputs, key=device_rank_key)


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
      - ``ranked`` / ``default`` / ``first_output`` for auto selection

    Input-only devices are skipped. Abstract defaults lose to concrete hw devices.
    """
    outputs = [d for d in devices if is_output_device(d)]
    if not outputs:
        return None, 'none'

    if configured_index is not None:
        for d in outputs:
            if d.index == int(configured_index):
                return d, 'configured_index'
        # Invalid configured index — fall through to name / ranked auto.

    if configured_name:
        needle = configured_name.lower().strip()
        matches = [d for d in outputs if needle in d.name.lower()]
        if matches:
            matches.sort(key=device_rank_key)
            return matches[0], 'configured_name'

    ranked = rank_output_devices(outputs)
    concrete = [d for d in ranked if not is_abstract_output_name(d.name)]

    # Prefer PortAudio default only when it is concrete (or no concrete exists).
    if default_output_index is not None:
        for d in outputs:
            if d.index == int(default_output_index):
                if not is_abstract_output_name(d.name) or not concrete:
                    return d, 'default'
                break

    marked = [d for d in outputs if d.is_default_output]
    if marked:
        marked_sorted = sorted(marked, key=device_rank_key)
        best_marked = marked_sorted[0]
        if not is_abstract_output_name(best_marked.name) or not concrete:
            return best_marked, 'default'

    if ranked:
        reason = 'ranked' if not is_abstract_output_name(ranked[0].name) else 'first_output'
        return ranked[0], reason
    return None, 'none'


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
