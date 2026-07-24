from __future__ import annotations

import logging
import threading
from time import time
from typing import Optional

from interaction.touch.events import TapGate, TouchCallback, TouchEvent, TouchPhase
from interaction.touch.source import CallbackTouchSource, NullTouchSource, TouchSource
from interaction.touch.transform import TouchTransform

logger = logging.getLogger('shelter.touch')

# Linux input constants (avoid importing evdev at module import time when unused).
EV_KEY = 0x01
EV_ABS = 0x03
EV_SYN = 0x00
BTN_TOUCH = 0x14a
ABS_X = 0x00
ABS_Y = 0x01
SYN_REPORT = 0


class EvdevTouchInput(CallbackTouchSource):
    """
    Reads ABS_X / ABS_Y / BTN_TOUCH / SYN_REPORT from a Linux input event device.
    Emits at most one TAP per contact. Safe to stop() from another thread.
    """

    def __init__(self, device_path: str, transform: TouchTransform,
                 on_event: Optional[TouchCallback] = None, debounce_ms: int = 120):
        super().__init__(on_event)
        self.__device_path = device_path
        self.__transform = transform
        self.__gate = TapGate(debounce_ms)
        self.__thread: threading.Thread | None = None
        self.__stop = threading.Event()
        self.__available = False
        self.__error: str | None = None
        self.__device = None
        self.__cur_x = 0
        self.__cur_y = 0
        self.__touching = False
        self.__pending = False

    @property
    def available(self) -> bool:
        return self.__available

    @property
    def error(self) -> str | None:
        return self.__error

    @property
    def device_path(self) -> str:
        return self.__device_path

    def start(self) -> None:
        self.__stop.clear()
        self.__gate.reset()
        try:
            import evdev  # type: ignore
            self.__device = evdev.InputDevice(self.__device_path)
            self.__apply_abs_info(self.__device)
            self.__available = True
            self.__error = None
        except Exception as exc:  # noqa: BLE001
            self.__available = False
            self.__error = f'touch device unavailable ({self.__device_path}): {exc}'
            logger.warning(self.__error)
            return
        self.__thread = threading.Thread(target=self.__loop, name='evdev-touch', daemon=True)
        self.__thread.start()

    def stop(self) -> None:
        self.__stop.set()
        device = self.__device
        if device is not None:
            try:
                device.close()
            except Exception:  # noqa: BLE001
                pass
        thread = self.__thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        self.__thread = None
        self.__device = None
        self.__gate.reset()

    def __apply_abs_info(self, device) -> None:
        try:
            caps = device.capabilities().get(EV_ABS, [])
        except Exception:  # noqa: BLE001
            return
        absinfo = {}
        for item in caps:
            # evdev may return (code, AbsInfo) tuples
            if isinstance(item, tuple) and len(item) == 2:
                code, info = item
                absinfo[code] = info
        x_info = absinfo.get(ABS_X)
        y_info = absinfo.get(ABS_Y)
        raw_x_min = self.__transform.raw_x_min
        raw_x_max = self.__transform.raw_x_max
        raw_y_min = self.__transform.raw_y_min
        raw_y_max = self.__transform.raw_y_max
        # Only override when caller left defaults and device reports range
        if x_info is not None and self.__transform.raw_x_min == 0 and self.__transform.raw_x_max == 4095:
            raw_x_min, raw_x_max = int(x_info.min), int(x_info.max)
        if y_info is not None and self.__transform.raw_y_min == 0 and self.__transform.raw_y_max == 4095:
            raw_y_min, raw_y_max = int(y_info.min), int(y_info.max)
        self.__transform = TouchTransform(
            screen_width=self.__transform.screen_width,
            screen_height=self.__transform.screen_height,
            raw_x_min=raw_x_min,
            raw_x_max=raw_x_max,
            raw_y_min=raw_y_min,
            raw_y_max=raw_y_max,
            swap_axes=self.__transform.swap_axes,
            invert_x=self.__transform.invert_x,
            invert_y=self.__transform.invert_y,
            rotation=self.__transform.rotation,
        )

    def __loop(self) -> None:
        device = self.__device
        if device is None:
            return
        try:
            while not self.__stop.is_set():
                try:
                    for event in device.read_loop():
                        if self.__stop.is_set():
                            break
                        self.__handle_event(event)
                except BlockingIOError:
                    continue
                except OSError as exc:
                    if not self.__stop.is_set():
                        self.__error = f'touch read failed: {exc}'
                        logger.warning(self.__error)
                    break
        finally:
            self.__available = False

    def __handle_event(self, event) -> None:
        if event.type == EV_ABS:
            if event.code == ABS_X:
                self.__cur_x = event.value
                self.__pending = True
            elif event.code == ABS_Y:
                self.__cur_y = event.value
                self.__pending = True
        elif event.type == EV_KEY and event.code == BTN_TOUCH:
            if event.value == 1:
                self.__touching = True
                self.__pending = True
            elif event.value == 0:
                self.__touching = False
                self.__gate.on_up()
        elif event.type == EV_SYN and event.code == SYN_REPORT:
            if self.__touching and self.__pending:
                self.__pending = False
                if self.__gate.on_down(time()):
                    x, y = self.__transform.map_point(self.__cur_x, self.__cur_y)
                    self.emit(TouchEvent(x, y, TouchPhase.TAP, time()))


def open_touch_source(device_path: str | None, transform: TouchTransform, debounce_ms: int,
                      on_event: TouchCallback, enabled: bool = True) -> TouchSource:
    """Factory with keyboard-friendly fallback when device is missing."""
    if not enabled or not device_path:
        return NullTouchSource('touch disabled in config')
    source = EvdevTouchInput(device_path, transform, on_event=on_event, debounce_ms=debounce_ms)
    source.start()
    if not source.available:
        source.stop()
        return NullTouchSource(source.error or 'touch device unavailable')
    return source
