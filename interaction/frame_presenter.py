"""Single-slot frame presentation queue for Tk (main-thread only).

Ensures the currently displayed frame stays visible until the next *complete*
frame is ready. Never publishes an empty/black intermediate buffer.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from PIL import Image

logger = logging.getLogger('piboy.present')


class FramePresenter:
    """
    Drop-to-latest presentation queue (capacity 1).

    ``submit`` may be called from any thread. Tk/`PhotoImage` work runs only via
    ``schedule`` (typically ``root.after``) on the UI thread.
    """

    def __init__(
        self,
        schedule: Callable[[Callable[[], None]], None],
        present: Callable[[Image.Image], None],
        *,
        name: str = 'canvas',
    ):
        self.__schedule = schedule
        self.__present = present
        self.__name = name
        self.__lock = threading.Lock()
        self.__pending: Optional[Image.Image] = None
        self.__flush_scheduled = False
        self.__closed = False
        self.__presented_count = 0
        self.__dropped_count = 0

    @property
    def pending_count(self) -> int:
        with self.__lock:
            return 0 if self.__pending is None else 1

    @property
    def dropped_count(self) -> int:
        return self.__dropped_count

    @property
    def presented_count(self) -> int:
        return self.__presented_count

    def submit(self, frame: Image.Image) -> None:
        """Queue a complete RGB frame; replaces any not-yet-presented pending frame."""
        if frame is None:
            return
        # Detach from caller buffers so producers can keep composing.
        ready = frame.copy()
        with self.__lock:
            if self.__closed:
                return
            replaced = self.__pending is not None
            self.__pending = ready
            if replaced:
                self.__dropped_count += 1
                logger.info(
                    'dropped/replaced pending frame name=%s thread=%s dropped_total=%s',
                    self.__name, threading.get_ident(), self.__dropped_count,
                )
            if not self.__flush_scheduled:
                self.__flush_scheduled = True
                self.__schedule(self._flush)

    def _flush(self) -> None:
        """UI-thread: present at most one frame; reschedule if another arrived."""
        with self.__lock:
            if self.__closed:
                self.__pending = None
                self.__flush_scheduled = False
                return
            frame = self.__pending
            self.__pending = None
            # Keep flush_scheduled True until we know whether to continue,
            # so concurrent submit() does not double-schedule.
        if frame is None:
            with self.__lock:
                self.__flush_scheduled = False
            return

        logger.debug(
            'frame presented name=%s size=%s thread=%s',
            self.__name, frame.size, threading.get_ident(),
        )
        self.__present(frame)
        self.__presented_count += 1

        with self.__lock:
            if self.__closed:
                self.__flush_scheduled = False
                self.__pending = None
                return
            if self.__pending is not None:
                # Another frame arrived during present — schedule again.
                self.__schedule(self._flush)
            else:
                self.__flush_scheduled = False

    def shutdown(self) -> None:
        """Stop accepting frames and clear pending (safe from any thread)."""
        with self.__lock:
            self.__closed = True
            self.__pending = None
            self.__flush_scheduled = False
        logger.info('presenter shutdown name=%s thread=%s', self.__name, threading.get_ident())


class RenderGate:
    """
    Serializes compose/CRT so only one render runs; extra requests coalesce
    into a single follow-up pass (no parallel CRT of two frames).
    """

    def __init__(self):
        self.__lock = threading.Lock()
        self.__busy = False
        self.__rerun = False
        self.__closed = False

    @property
    def busy(self) -> bool:
        with self.__lock:
            return self.__busy

    def request(self, render_fn: Callable[[], Any]) -> bool:
        """
        Run ``render_fn`` now if idle; otherwise mark rerun and return False.
        If a render is already in progress on this or another thread, the caller
        does not start a second one.
        """
        with self.__lock:
            if self.__closed:
                return False
            if self.__busy:
                self.__rerun = True
                logger.info(
                    'frame request coalesced (render busy) thread=%s',
                    threading.get_ident(),
                )
                return False
            self.__busy = True
            self.__rerun = False

        logger.debug('frame requested thread=%s', threading.get_ident())
        try:
            while True:
                logger.debug('render started thread=%s', threading.get_ident())
                render_fn()
                logger.debug('render finished thread=%s', threading.get_ident())
                with self.__lock:
                    if self.__closed:
                        self.__busy = False
                        self.__rerun = False
                        return True
                    if self.__rerun:
                        self.__rerun = False
                        logger.info(
                            'dropped/replaced pending frame (rerun) thread=%s',
                            threading.get_ident(),
                        )
                        continue
                    self.__busy = False
                    return True
        except Exception:
            with self.__lock:
                self.__busy = False
                self.__rerun = False
            raise

    def shutdown(self) -> None:
        with self.__lock:
            self.__closed = True
            self.__rerun = False
            self.__busy = False
