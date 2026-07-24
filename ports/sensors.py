from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from core.data import DeviceStatus
from data.EnvironmentDataProvider import EnvironmentData


@dataclass
class SensorReading:
    data: EnvironmentData | None
    status: DeviceStatus
    last_update: datetime | None
    warning: str | None = None


class SensorPort(ABC):

    @abstractmethod
    def get_reading(self) -> SensorReading:
        raise NotImplementedError

    @abstractmethod
    def set_online(self, online: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def nudge_values(self, temperature: float | None = None,
                     humidity: float | None = None,
                     pressure: float | None = None) -> None:
        raise NotImplementedError
