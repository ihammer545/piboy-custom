from __future__ import annotations

from time import time
from typing import Optional

from interaction.touch.events import TapGate, TouchCallback, TouchEvent, TouchPhase
from interaction.touch.source import CallbackTouchSource


class SimulatorTouchInput(CallbackTouchSource):
    """
    Dev/UTM touch source. Left-click on the 800×480 canvas is one finger tap.
    Does not handle simulator panel clicks — those stay outside this class.
    """

    def __init__(self, on_event: Optional[TouchCallback] = None, debounce_ms: int = 120,
                 screen_width: int = 800, screen_height: int = 480):
        super().__init__(on_event)
        self.__gate = TapGate(debounce_ms)
        self.__screen_width = screen_width
        self.__screen_height = screen_height
        self.__started = False

    @property
    def available(self) -> bool:
        return True

    def start(self) -> None:
        self.__started = True
        self.__gate.reset()

    def stop(self) -> None:
        self.__started = False
        self.__gate.reset()

    def inject_canvas_click(self, canvas_x: float, canvas_y: float,
                            canvas_width: float | None = None,
                            canvas_height: float | None = None) -> bool:
        """
        Map a canvas click (possibly scaled) into screen pixels and emit one tap.
        Returns True if a tap was emitted.
        """
        if not self.__started:
            return False
        cw = canvas_width if canvas_width and canvas_width > 0 else float(self.__screen_width)
        ch = canvas_height if canvas_height and canvas_height > 0 else float(self.__screen_height)
        x = int(round(canvas_x * (self.__screen_width - 1) / max(cw - 1, 1)))
        y = int(round(canvas_y * (self.__screen_height - 1) / max(ch - 1, 1)))
        x = max(0, min(self.__screen_width - 1, x))
        y = max(0, min(self.__screen_height - 1, y))
        ts = time()
        if not self.__gate.on_down(ts):
            self.__gate.on_up()
            return False
        self.emit(TouchEvent(x, y, TouchPhase.TAP, ts))
        self.__gate.on_up()
        return True
