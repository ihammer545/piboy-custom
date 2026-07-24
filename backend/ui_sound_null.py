"""Null UI sound backend — always safe, no device required."""

from __future__ import annotations


class NullUiSoundBackend:
    def __init__(self, output_rate: int = 22050, output_channels: int = 1):
        self.__output_rate = output_rate
        self.__output_channels = output_channels

    def play_pcm(self, pcm: bytes, sample_rate: int, channels: int = 1) -> None:
        return

    def close(self) -> None:
        return

    @property
    def available(self) -> bool:
        return False

    @property
    def output_rate(self) -> int:
        return self.__output_rate

    @property
    def output_channels(self) -> int:
        return self.__output_channels

    def describe_output(self) -> str:
        return 'null'
