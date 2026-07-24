from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import time
from typing import Any, Callable, Optional


class TouchPhase(Enum):
    DOWN = 'down'
    UP = 'up'
    TAP = 'tap'


@dataclass(frozen=True)
class Rect:
    x0: int
    y0: int
    x1: int
    y1: int

    def contains(self, x: int, y: int) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.x0, self.y0, self.x1, self.y1

    @property
    def width(self) -> int:
        return max(0, self.x1 - self.x0 + 1)

    @property
    def height(self) -> int:
        return max(0, self.y1 - self.y0 + 1)

    def expand_to_min(self, min_w: int, min_h: int) -> Rect:
        w, h = self.width, self.height
        extra_w = max(0, min_w - w)
        extra_h = max(0, min_h - h)
        return Rect(
            self.x0 - extra_w // 2,
            self.y0 - extra_h // 2,
            self.x1 + (extra_w - extra_w // 2),
            self.y1 + (extra_h - extra_h // 2),
        )

    def translate(self, dx: int, dy: int) -> Rect:
        return Rect(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)

    def clamp_to(self, bounds: Rect) -> Rect:
        return Rect(
            max(bounds.x0, self.x0),
            max(bounds.y0, self.y0),
            min(bounds.x1, self.x1),
            min(bounds.y1, self.y1),
        )


@dataclass(frozen=True)
class TouchEvent:
    x: int
    y: int
    phase: TouchPhase
    timestamp: float

    @classmethod
    def tap(cls, x: int, y: int, timestamp: float | None = None) -> TouchEvent:
        return cls(int(x), int(y), TouchPhase.TAP, time() if timestamp is None else timestamp)


@dataclass
class HitTarget:
    rect: Rect
    action: str
    enabled: bool = True
    meta: Any = None


def hit_test(targets: list[HitTarget], x: int, y: int) -> Optional[HitTarget]:
    """Return the topmost (last) enabled target containing the point."""
    for target in reversed(targets):
        if target.enabled and target.rect.contains(x, y):
            return target
    return None


class TapGate:
    """Ensures one UI action per physical touch; ignores hold repeats and rapid doubles."""

    def __init__(self, debounce_ms: int = 120):
        self.__debounce_s = max(0, debounce_ms) / 1000.0
        self.__pressed = False
        self.__last_tap_ts = 0.0
        self.__emitted_for_press = False

    @property
    def pressed(self) -> bool:
        return self.__pressed

    def on_down(self, timestamp: float | None = None) -> bool:
        """Return True if this down should emit a tap."""
        ts = time() if timestamp is None else timestamp
        if self.__pressed:
            return False
        self.__pressed = True
        if ts - self.__last_tap_ts < self.__debounce_s:
            self.__emitted_for_press = True
            return False
        self.__last_tap_ts = ts
        self.__emitted_for_press = True
        return True

    def on_up(self) -> None:
        self.__pressed = False
        self.__emitted_for_press = False

    def reset(self) -> None:
        self.__pressed = False
        self.__emitted_for_press = False
        self.__last_tap_ts = 0.0


TouchCallback = Callable[[TouchEvent], None]
