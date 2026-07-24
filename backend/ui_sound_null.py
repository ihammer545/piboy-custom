"""Null UI sound backend — always safe, no device required."""

from __future__ import annotations


class NullUiSoundBackend:
    def play_pcm(self, pcm: bytes, sample_rate: int, channels: int = 1) -> None:
        return

    def close(self) -> None:
        return

    @property
    def available(self) -> bool:
        return False
