from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from interaction.touch.events import TouchCallback, TouchEvent


class TouchSource(ABC):
    """Produces normalized screen-space touch events (800×480 by default)."""

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError


class NullTouchSource(TouchSource):
    """No-op source used when touch is disabled or device is missing."""

    def __init__(self, reason: str = 'touch disabled'):
        self.reason = reason

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    @property
    def available(self) -> bool:
        return False


class CallbackTouchSource(TouchSource):
    """Base helper that stores a tap callback."""

    def __init__(self, on_event: Optional[TouchCallback] = None):
        self._on_event = on_event

    def set_callback(self, on_event: TouchCallback) -> None:
        self._on_event = on_event

    def emit(self, event: TouchEvent) -> None:
        if self._on_event is not None:
            self._on_event(event)
