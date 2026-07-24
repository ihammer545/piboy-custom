"""PyAudio / PortAudio one-shot UI sound backend (ALSA on Raspberry Pi).

One long-lived output stream worker; never opens a stream per click.
Falls back silently when the device is unavailable (caller should swap to Null).
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

logger = logging.getLogger('piboy.ui_sound')

# Keep queue tiny — service already coalesces; this is a playback cushion.
_PLAY_QUEUE_MAX = 4


class PyAudioUiSoundBackend:
    def __init__(self, sample_rate: int = 22050, channels: int = 1):
        self.__sample_rate = sample_rate
        self.__channels = channels
        self.__queue: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=_PLAY_QUEUE_MAX)
        self.__closed = False
        self.__available = False
        self.__pa = None
        self.__stream = None
        self.__worker: Optional[threading.Thread] = None
        self.__warn_once = False
        self.__open()

    def __open(self) -> None:
        try:
            import pyaudio  # local import — optional at runtime
            self.__pa = pyaudio.PyAudio()
            self.__stream = self.__pa.open(
                format=pyaudio.paInt16,
                channels=self.__channels,
                rate=self.__sample_rate,
                output=True,
                frames_per_buffer=512,
                start=False,
            )
            self.__available = True
            self.__worker = threading.Thread(target=self.__run, name='ui-sound-worker', daemon=True)
            self.__worker.start()
        except Exception as exc:  # noqa: BLE001 — missing lib / no device
            if not self.__warn_once:
                logger.warning('UI sound device unavailable (%s); using silent backend', exc)
                self.__warn_once = True
            self.__available = False
            self.close()

    @property
    def available(self) -> bool:
        return self.__available and not self.__closed

    def play_pcm(self, pcm: bytes, sample_rate: int, channels: int = 1) -> None:
        if not self.available or not pcm:
            return
        if sample_rate != self.__sample_rate or channels != self.__channels:
            # Service only feeds matching preloaded buffers.
            return
        try:
            self.__queue.put_nowait(pcm)
        except queue.Full:
            # Drop oldest click-like cushion entry, keep newest.
            try:
                self.__queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.__queue.put_nowait(pcm)
            except queue.Full:
                pass

    def __run(self) -> None:
        assert self.__stream is not None
        stream = self.__stream
        try:
            stream.start_stream()
        except Exception as exc:  # noqa: BLE001
            if not self.__warn_once:
                logger.warning('UI sound stream failed to start (%s)', exc)
                self.__warn_once = True
            self.__available = False
            return
        while not self.__closed:
            try:
                item = self.__queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                stream.write(item)
            except Exception as exc:  # noqa: BLE001
                if not self.__warn_once:
                    logger.warning('UI sound write failed (%s); silencing', exc)
                    self.__warn_once = True
                self.__available = False
                break

    def close(self) -> None:
        self.__closed = True
        self.__available = False
        try:
            self.__queue.put_nowait(None)
        except queue.Full:
            pass
        if self.__worker and self.__worker.is_alive() and threading.current_thread() is not self.__worker:
            self.__worker.join(timeout=1.0)
        self.__worker = None
        if self.__stream is not None:
            try:
                self.__stream.stop_stream()
            except Exception:  # noqa: BLE001
                pass
            try:
                self.__stream.close()
            except Exception:  # noqa: BLE001
                pass
            self.__stream = None
        if self.__pa is not None:
            try:
                self.__pa.terminate()
            except Exception:  # noqa: BLE001
                pass
            self.__pa = None
