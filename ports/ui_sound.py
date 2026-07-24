"""UI sound port — semantic events only (no PyAudio in apps)."""

from __future__ import annotations

from enum import Enum
from typing import Protocol


class UiSoundEvent(Enum):
    KEY = 'key'
    TOUCH = 'touch'
    CONFIRM = 'confirm'
    BACK = 'back'
    DENIED = 'denied'
    LOCK = 'lock'


class UiSoundPort(Protocol):
    """Low-level one-shot playback of preloaded PCM buffers."""

    def play_pcm(self, pcm: bytes, sample_rate: int, channels: int = 1) -> None:
        ...

    def close(self) -> None:
        ...

    @property
    def available(self) -> bool:
        ...
