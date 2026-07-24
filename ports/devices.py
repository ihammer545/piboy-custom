from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class DevicePresence(Enum):
    ONLINE = 'online'
    OFFLINE = 'offline'


@dataclass
class DeviceInfo:
    device_id: str
    name: str
    kind: str
    presence: DevicePresence
    powered_on: bool
    requires_confirm: bool = False


@dataclass(frozen=True)
class DeviceCommandResult:
    ok: bool
    message: str
    device: DeviceInfo | None = None


class DevicePort(ABC):

    @abstractmethod
    def list_devices(self) -> list[DeviceInfo]:
        raise NotImplementedError

    @abstractmethod
    def toggle(self, device_id: str) -> DeviceCommandResult:
        raise NotImplementedError

    @abstractmethod
    def set_device_online(self, device_id: str, online: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_next_command_fails(self, fails: bool) -> None:
        raise NotImplementedError
