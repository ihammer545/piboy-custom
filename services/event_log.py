from collections import deque
from dataclasses import dataclass
from datetime import datetime
from threading import Lock


@dataclass(frozen=True)
class LogEvent:
    timestamp: datetime
    category: str
    message: str


class EventLogService:
    """In-memory event log. Never store secrets or raw access codes."""

    def __init__(self, max_events: int = 100):
        self.__max_events = max(1, max_events)
        self.__events: deque[LogEvent] = deque(maxlen=self.__max_events)
        self.__lock = Lock()

    def add(self, category: str, message: str) -> LogEvent:
        event = LogEvent(datetime.now(), category, message)
        with self.__lock:
            self.__events.appendleft(event)
        return event

    def list_events(self) -> list[LogEvent]:
        with self.__lock:
            return list(self.__events)

    def clear(self) -> None:
        with self.__lock:
            self.__events.clear()

    @property
    def max_events(self) -> int:
        return self.__max_events
