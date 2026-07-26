"""UiSoundService — semantic UI feedback with preload, debounce, and bounded queue."""

from __future__ import annotations

import logging
import os
import struct
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Optional

from ports.intercom import CallPhase
from ports.ui_sound import UiSoundEvent, UiSoundPort
from backend.ui_sound_pcm import prepare_pcm_for_device

logger = logging.getLogger('piboy.ui_sound')

DEFAULT_SOUNDS_DIR = Path('resources') / 'sounds'

# Click-like events subject to interval debounce and preferential drop.
_CLICK_EVENTS = frozenset({UiSoundEvent.KEY, UiSoundEvent.TOUCH})
_PRIORITY = {
    UiSoundEvent.BOOT: 6,
    UiSoundEvent.LOCK: 5,
    UiSoundEvent.DENIED: 4,
    UiSoundEvent.CONFIRM: 3,
    UiSoundEvent.BACK: 2,
    UiSoundEvent.KEY: 1,
    UiSoundEvent.TOUCH: 1,
}


@dataclass(frozen=True)
class _Sample:
    pcm: bytes
    rate: int
    channels: int


@dataclass
class UiSoundSettings:
    enabled: bool = True
    volume: float = 0.35
    clicks_during_call: bool = False
    min_interval_ms: int = 30
    queue_max: int = 4
    output_device_index: int | None = None
    output_device_name: str | None = None


class UiSoundService:
    """
    Apps call semantic methods (key/touch/confirm/…).
    WAV files are preloaded once; playback goes through UiSoundPort.
    """

    def __init__(
        self,
        port: UiSoundPort,
        settings: UiSoundSettings | None = None,
        sounds_dir: Path | str | None = None,
        call_phase_fn: Optional[Callable[[], CallPhase]] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.__port = port
        self.__settings = settings or UiSoundSettings()
        self.__settings.volume = self._clamp_volume(self.__settings.volume)
        self.__sounds_dir = Path(sounds_dir) if sounds_dir else DEFAULT_SOUNDS_DIR
        self.__call_phase_fn = call_phase_fn
        self.__clock = clock
        self.__samples: dict[UiSoundEvent, list[_Sample]] = {}
        self.__variant_idx = 0
        self.__lock = threading.Lock()
        self.__queue: Deque[UiSoundEvent] = deque()
        self.__last_click_ts = 0.0
        self.__preloaded = False
        self.__closed = False
        self.__worker: Optional[threading.Thread] = None
        self.__wake = threading.Event()
        self.preload()
        self.__start_worker()

    @staticmethod
    def _clamp_volume(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @property
    def enabled(self) -> bool:
        return self.__settings.enabled and not self.__closed

    @property
    def volume(self) -> float:
        return self.__settings.volume

    @property
    def settings(self) -> UiSoundSettings:
        return self.__settings

    @property
    def preloaded(self) -> bool:
        return self.__preloaded

    @property
    def queue_len(self) -> int:
        with self.__lock:
            return len(self.__queue)

    def set_enabled(self, enabled: bool) -> None:
        self.__settings.enabled = bool(enabled)

    def set_volume(self, volume: float) -> None:
        self.__settings.volume = self._clamp_volume(volume)

    def adjust_volume(self, delta: float) -> float:
        self.set_volume(self.__settings.volume + delta)
        return self.__settings.volume

    def preload(self) -> None:
        """Load all UI WAVs into memory once; convert to port output format once."""
        if self.__preloaded:
            return
        self.__reload_samples()
        self.__preloaded = True

    def __reload_samples(self) -> None:
        mapping = {
            UiSoundEvent.KEY: ['key_a.wav', 'key_b.wav', 'key_c.wav'],
            UiSoundEvent.TOUCH: ['touch_a.wav', 'touch_b.wav', 'touch_c.wav'],
            UiSoundEvent.CONFIRM: ['confirm.wav'],
            UiSoundEvent.BACK: ['back.wav'],
            UiSoundEvent.DENIED: ['denied.wav'],
            UiSoundEvent.LOCK: ['lock.wav'],
            UiSoundEvent.BOOT: ['boot.wav'],
        }
        dst_rate = int(getattr(self.__port, 'output_rate', 22050) or 22050)
        dst_ch = int(getattr(self.__port, 'output_channels', 1) or 1)
        samples: dict[UiSoundEvent, list[_Sample]] = {}
        for event, names in mapping.items():
            loaded: list[_Sample] = []
            for name in names:
                path = self.__sounds_dir / name
                if not path.is_file():
                    logger.warning('UI sound missing: %s', path)
                    continue
                raw = self._load_wav(path)
                pcm = prepare_pcm_for_device(
                    raw.pcm,
                    src_rate=raw.rate,
                    src_channels=raw.channels,
                    dst_rate=dst_rate,
                    dst_channels=dst_ch,
                )
                loaded.append(_Sample(pcm=pcm, rate=dst_rate, channels=dst_ch))
            if not loaded:
                raw = self._synth_click(event)
                pcm = prepare_pcm_for_device(
                    raw.pcm,
                    src_rate=raw.rate,
                    src_channels=raw.channels,
                    dst_rate=dst_rate,
                    dst_channels=dst_ch,
                )
                loaded.append(_Sample(pcm=pcm, rate=dst_rate, channels=dst_ch))
            samples[event] = loaded
        self.__samples = samples

    def describe_output(self) -> str:
        fn = getattr(self.__port, 'describe_output', None)
        if callable(fn):
            return str(fn())
        return 'unknown'

    def test_confirm(self) -> str:
        """Log selected device and play confirm via the real play() path (dev panel)."""
        info = self.describe_output()
        if not self.__settings.enabled:
            logger.warning('UI sound test: enabled=false — enabling for this test play')
            self.__settings.enabled = True
        logger.info(
            'UI sound test → calling play(CONFIRM) device=%s volume=%.2f',
            info, self.__settings.volume,
        )
        self.play(UiSoundEvent.CONFIRM)
        return info

    def key(self) -> None:
        self.play(UiSoundEvent.KEY)

    def touch(self) -> None:
        self.play(UiSoundEvent.TOUCH)

    def confirm(self) -> None:
        self.play(UiSoundEvent.CONFIRM)

    def back(self) -> None:
        self.play(UiSoundEvent.BACK)

    def denied(self) -> None:
        self.play(UiSoundEvent.DENIED)

    def lock(self) -> None:
        self.play(UiSoundEvent.LOCK)

    def boot(self) -> None:
        self.play(UiSoundEvent.BOOT)

    def stop_current(self) -> None:
        """Drop queued events and interrupt in-flight PCM (boot skip)."""
        with self.__lock:
            self.__queue.clear()
        stopper = getattr(self.__port, 'stop_current', None)
        if callable(stopper):
            try:
                stopper()
            except Exception as exc:  # noqa: BLE001
                logger.debug('UI sound stop_current failed (%s)', exc)

    def list_output_devices(self):
        """Ranked output devices (best first). Apps must not import PyAudio."""
        from backend.ui_sound_device import rank_output_devices
        lister = getattr(self.__port, 'list_devices', None)
        if callable(lister):
            try:
                devices = lister()
                if devices:
                    return rank_output_devices(devices)
            except Exception as exc:  # noqa: BLE001
                logger.debug('port.list_devices failed (%s)', exc)
        return list_host_output_devices()

    def current_device_index(self) -> int | None:
        sel = getattr(self.__port, 'selected_device', None)
        if sel is not None:
            return int(sel.index)
        return self.__settings.output_device_index

    def rebind_output(
        self,
        index: int | None = None,
        name: str | None = None,
        *,
        selection_source: str = 'config',
    ) -> str:
        """Close current backend and open another device; reload PCM formats."""
        if self.__closed:
            return 'closed'
        self.stop_current()
        old = self.__port
        try:
            old.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug('UI sound old port close (%s)', exc)
        self.__settings.output_device_index = index
        self.__settings.output_device_name = name
        self.__port = open_ui_sound_port(
            prefer_pyaudio=True,
            device_index=index,
            device_name=name,
            selection_source=selection_source,
        )
        self.__reload_samples()
        self.__preloaded = True
        info = self.describe_output()
        logger.info('UI sound rebound → %s', info)
        return info

    def play(self, event: UiSoundEvent) -> None:
        if self.__closed or not self.__settings.enabled:
            return
        if event in _CLICK_EVENTS and not self.__settings.clicks_during_call:
            phase = self.__call_phase_fn() if self.__call_phase_fn else CallPhase.IDLE
            if phase not in (CallPhase.IDLE, CallPhase.ENDED):
                return
        now = self.__clock()
        with self.__lock:
            if event in _CLICK_EVENTS:
                min_gap = max(0.0, self.__settings.min_interval_ms / 1000.0)
                if now - self.__last_click_ts < min_gap:
                    return
                self.__last_click_ts = now
            self.__enqueue_locked(event)
            self.__wake.set()

    def __enqueue_locked(self, event: UiSoundEvent) -> None:
        max_q = max(1, int(self.__settings.queue_max))
        if len(self.__queue) >= max_q:
            # Drop oldest low-priority click; keep important events.
            dropped = False
            for i, existing in enumerate(self.__queue):
                if existing in _CLICK_EVENTS and _PRIORITY.get(existing, 0) <= _PRIORITY.get(event, 0):
                    del self.__queue[i]
                    dropped = True
                    break
            if not dropped and event in _CLICK_EVENTS:
                return  # discard new click if queue is full of important sounds
            if not dropped and len(self.__queue) >= max_q:
                self.__queue.popleft()
        self.__queue.append(event)

    def __start_worker(self) -> None:
        self.__worker = threading.Thread(target=self.__worker_loop, name='ui-sound-dispatch', daemon=True)
        self.__worker.start()

    def __worker_loop(self) -> None:
        while not self.__closed:
            self.__wake.wait(timeout=0.25)
            self.__wake.clear()
            while True:
                with self.__lock:
                    if not self.__queue:
                        break
                    event = self.__queue.popleft()
                self.__emit(event)

    def __emit(self, event: UiSoundEvent) -> None:
        variants = self.__samples.get(event) or []
        if not variants:
            return
        sample = variants[self.__variant_idx % len(variants)]
        self.__variant_idx += 1
        pcm = self._apply_volume(sample.pcm, self.__settings.volume)
        try:
            self.__port.play_pcm(pcm, sample.rate, sample.channels)
        except Exception as exc:  # noqa: BLE001
            logger.warning('UI sound playback error (%s)', exc)

    def close(self) -> None:
        self.__closed = True
        self.__wake.set()
        if self.__worker and self.__worker.is_alive() and threading.current_thread() is not self.__worker:
            self.__worker.join(timeout=1.0)
        self.__worker = None
        with self.__lock:
            self.__queue.clear()
        try:
            self.__port.close()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _load_wav(path: Path) -> _Sample:
        with wave.open(str(path), 'rb') as wf:
            channels = wf.getnchannels()
            rate = wf.getframerate()
            width = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
        if width != 2:
            raise ValueError(f'{path} must be 16-bit PCM')
        if channels != 1:
            # Downmix stereo → mono
            samples = struct.unpack('<' + 'h' * (len(frames) // 2), frames)
            mono = []
            for i in range(0, len(samples), channels):
                mono.append(int(sum(samples[i:i + channels]) / channels))
            frames = struct.pack('<' + 'h' * len(mono), *mono)
            channels = 1
        return _Sample(pcm=frames, rate=rate, channels=channels)

    @staticmethod
    def _apply_volume(pcm: bytes, volume: float) -> bytes:
        if volume >= 0.999:
            return pcm
        if volume <= 0.001:
            return b'\x00' * len(pcm)
        count = len(pcm) // 2
        samples = struct.unpack('<' + 'h' * count, pcm)
        scaled = [max(-32768, min(32767, int(s * volume))) for s in samples]
        return struct.pack('<' + 'h' * count, *scaled)

    @staticmethod
    def _synth_click(event: UiSoundEvent) -> _Sample:
        """Procedural mono 16-bit @ 22050 Hz fallback (~40 ms)."""
        rate = 22050
        duration = 0.04
        n = int(rate * duration)
        freq = {
            UiSoundEvent.KEY: 1800,
            UiSoundEvent.TOUCH: 1400,
            UiSoundEvent.CONFIRM: 900,
            UiSoundEvent.BACK: 700,
            UiSoundEvent.DENIED: 220,
            UiSoundEvent.LOCK: 480,
            UiSoundEvent.BOOT: 1000,
        }.get(event, 1200)
        samples = []
        for i in range(n):
            t = i / rate
            # Decaying square-ish click
            amp = (1.0 - t / duration) ** 2
            val = 1.0 if int(t * freq * 2) % 2 == 0 else -1.0
            samples.append(int(amp * val * 12000))
        return _Sample(pcm=struct.pack('<' + 'h' * n, *samples), rate=rate, channels=1)


def open_ui_sound_port(
    prefer_pyaudio: bool = True,
    *,
    device_index: int | None = None,
    device_name: str | None = None,
    selection_source: str = 'auto',
) -> UiSoundPort:
    """Create PyAudio backend when possible; otherwise Null (one warning)."""
    from backend.ui_sound_null import NullUiSoundBackend
    if not prefer_pyaudio:
        return NullUiSoundBackend()
    try:
        from backend.ui_sound_pyaudio import PyAudioUiSoundBackend
        backend = PyAudioUiSoundBackend(
            device_index=device_index,
            device_name=device_name,
            source_rate=22050,
            source_channels=1,
            selection_source=selection_source,
        )
        if backend.available:
            return backend
        backend.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning('UI sound backend init failed (%s); using Null', exc)
    return NullUiSoundBackend()


def list_host_output_devices():
    """Enumerate PortAudio outputs without keeping a backend open."""
    from backend.ui_sound_device import rank_output_devices
    try:
        import pyaudio
        from backend.ui_sound_pyaudio import _suppress_alsa_enumeration_noise, enumerate_devices
        with _suppress_alsa_enumeration_noise():
            pa = pyaudio.PyAudio()
            try:
                devices, _ = enumerate_devices(pa)
            finally:
                pa.terminate()
        return rank_output_devices(devices)
    except Exception as exc:  # noqa: BLE001
        logger.debug('list_host_output_devices failed (%s)', exc)
        return []
