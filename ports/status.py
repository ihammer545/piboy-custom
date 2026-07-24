from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class LinkStatus(Enum):
    ONLINE = 'online'
    OFFLINE = 'offline'
    SIMULATED = 'simulated'


@dataclass(frozen=True)
class TerminalStatus:
    backend: str
    network: LinkStatus
    audio: LinkStatus
    resolution: tuple[int, int]
    uptime_seconds: float
    version: str


class StatusPort(ABC):

    @abstractmethod
    def get_status(self) -> TerminalStatus:
        raise NotImplementedError

    @abstractmethod
    def set_network_online(self, online: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_audio_online(self, online: bool) -> None:
        raise NotImplementedError
