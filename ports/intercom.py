from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class PeerPresence(Enum):
    ONLINE = 'online'
    OFFLINE = 'offline'


class CallPhase(Enum):
    IDLE = 'idle'
    CALLING = 'calling'
    RINGING = 'ringing'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    ENDED = 'ended'


@dataclass
class PeerInfo:
    peer_id: str
    name: str
    presence: PeerPresence
    busy: bool = False


@dataclass
class CallSession:
    phase: CallPhase
    remote_peer_id: str | None = None
    direction: str | None = None  # 'out' | 'in'
    message: str = ''


class IntercomPort(ABC):

    @abstractmethod
    def list_peers(self) -> list[PeerInfo]:
        raise NotImplementedError

    @abstractmethod
    def get_session(self) -> CallSession:
        raise NotImplementedError

    @abstractmethod
    def start_call(self, peer_id: str) -> CallSession:
        raise NotImplementedError

    @abstractmethod
    def accept_call(self) -> CallSession:
        raise NotImplementedError

    @abstractmethod
    def reject_call(self) -> CallSession:
        raise NotImplementedError

    @abstractmethod
    def hang_up(self) -> CallSession:
        raise NotImplementedError

    @abstractmethod
    def simulate_incoming(self, peer_id: str) -> CallSession:
        raise NotImplementedError

    @abstractmethod
    def set_peer_online(self, peer_id: str, online: bool) -> None:
        raise NotImplementedError
