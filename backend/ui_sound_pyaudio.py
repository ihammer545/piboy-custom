"""PyAudio / PortAudio UI sound backend (ALSA-friendly, no JACK required).

Long-lived blocking output stream + one worker. Stream stays open between
clicks; ``stop_stream`` is only used on shutdown / reopen (never right after
a short write — that clipped ALSA playback).
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from contextlib import contextmanager
from typing import Optional

from backend.ui_sound_device import (
    AudioDeviceInfo,
    choose_stream_channels,
    choose_stream_rate,
    select_output_device,
)
from backend.ui_sound_pcm import prepare_pcm_for_device

logger = logging.getLogger('piboy.ui_sound')

_PLAY_QUEUE_MAX = 4
_SOURCE_RATE = 22050
_SOURCE_CHANNELS = 1


@contextmanager
def _suppress_alsa_enumeration_noise():
    """
    Locally mute ALSA 'Unknown PCM' / JACK probe chatter during PortAudio init
    and device enumeration only. Real playback errors still go to our logger.
    """
    try:
        devnull = open(os.devnull, 'w')
    except OSError:
        yield
        return
    stderr_fd = sys.stderr.fileno()
    saved = os.dup(stderr_fd)
    try:
        os.dup2(devnull.fileno(), stderr_fd)
        yield
    finally:
        os.dup2(saved, stderr_fd)
        os.close(saved)
        devnull.close()


def enumerate_devices(pa) -> tuple[list[AudioDeviceInfo], int | None]:
    """List devices via get_device_info only (no open probes)."""
    devices: list[AudioDeviceInfo] = []
    default_out: int | None = None
    try:
        default_out = int(pa.get_default_output_device_info()['index'])
    except Exception:  # noqa: BLE001
        default_out = None

    host_names: dict[int, str] = {}
    try:
        for hi in range(pa.get_host_api_count()):
            info = pa.get_host_api_info_by_index(hi)
            host_names[hi] = str(info.get('name', ''))
    except Exception:  # noqa: BLE001
        pass

    count = int(pa.get_device_count())
    for i in range(count):
        try:
            info = pa.get_device_info_by_index(i)
        except Exception:  # noqa: BLE001
            continue
        host_api = host_names.get(int(info.get('hostApi', -1)), '')
        devices.append(AudioDeviceInfo(
            index=i,
            name=str(info.get('name', f'device-{i}')),
            max_input_channels=int(info.get('maxInputChannels', 0) or 0),
            max_output_channels=int(info.get('maxOutputChannels', 0) or 0),
            default_sample_rate=float(info.get('defaultSampleRate', 44100) or 44100),
            host_api=host_api,
            is_default_output=(default_out is not None and i == default_out),
        ))
    return devices, default_out


class PyAudioUiSoundBackend:
    def __init__(
        self,
        *,
        device_index: int | None = None,
        device_name: str | None = None,
        source_rate: int = _SOURCE_RATE,
        source_channels: int = _SOURCE_CHANNELS,
        selection_source: str = 'auto',
    ):
        self.__source_rate = source_rate
        self.__source_channels = source_channels
        self.__configured_index = device_index
        self.__configured_name = device_name
        self.__selection_source = selection_source
        self.__pick_reason = 'auto'
        self.__queue: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=_PLAY_QUEUE_MAX)
        self.__closed = False
        self.__available = False
        self.__pa = None
        self.__stream = None
        self.__worker: Optional[threading.Thread] = None
        self.__warn_once = False
        self.__reopen_used = False
        self.__device: Optional[AudioDeviceInfo] = None
        self.__output_rate = source_rate
        self.__output_channels = 1
        self.__lock = threading.Lock()
        self.__writes = 0
        self.__open()

    @property
    def available(self) -> bool:
        return self.__available and not self.__closed

    @property
    def output_rate(self) -> int:
        return self.__output_rate

    @property
    def output_channels(self) -> int:
        return self.__output_channels

    @property
    def selected_device(self) -> Optional[AudioDeviceInfo]:
        return self.__device

    @property
    def selection_source(self) -> str:
        return self.__selection_source

    @property
    def pick_reason(self) -> str:
        return self.__pick_reason

    @property
    def write_count(self) -> int:
        return self.__writes

    def describe_output(self) -> str:
        d = self.__device
        if d is None:
            return 'none'
        return (
            f'index={d.index} name={d.name!r} host={d.host_api!r} '
            f'out_ch={self.__output_channels} rate={self.__output_rate} '
            f'device_max_out={d.max_output_channels} '
            f'source={self.__selection_source} pick={self.__pick_reason}'
        )

    def __open(self) -> None:
        try:
            import pyaudio
            with _suppress_alsa_enumeration_noise():
                self.__pa = pyaudio.PyAudio()
                devices, default_out = enumerate_devices(self.__pa)
            device, pick_reason = select_output_device(
                devices,
                configured_index=self.__configured_index,
                configured_name=self.__configured_name,
                default_output_index=default_out,
            )
            self.__pick_reason = pick_reason
            if device is None:
                raise RuntimeError('no output audio device found')
            self.__device = device
            self.__output_channels = choose_stream_channels(device, prefer=1)
            self.__output_rate = choose_stream_rate(device, source_rate=self.__source_rate)
            self.__stream = self.__open_stream(pyaudio)
            self.__available = True
            logger.info(
                'UI sound device selected: %s (requested_index=%s requested_name=%s)',
                self.describe_output(),
                self.__configured_index,
                self.__configured_name,
            )
            self.__worker = threading.Thread(target=self.__run, name='ui-sound-worker', daemon=True)
            self.__worker.start()
        except Exception as exc:  # noqa: BLE001
            if not self.__warn_once:
                logger.warning('UI sound device unavailable (%s); using silent backend', exc)
                self.__warn_once = True
            self.__available = False
            self._cleanup_pa()

    def __open_stream(self, pyaudio_mod):
        assert self.__pa is not None and self.__device is not None
        # start=True: stream ready for blocking writes; keep it running between clicks.
        stream = self.__pa.open(
            format=pyaudio_mod.paInt16,
            channels=self.__output_channels,
            rate=self.__output_rate,
            output=True,
            output_device_index=self.__device.index,
            frames_per_buffer=1024,
            start=True,
        )
        logger.debug(
            'UI sound stream opened active=%s ch=%s rate=%s device=%s',
            stream.is_active(), self.__output_channels, self.__output_rate, self.__device.index,
        )
        return stream

    def play_pcm(self, pcm: bytes, sample_rate: int, channels: int = 1) -> None:
        """Enqueue PCM already matching output_rate / output_channels."""
        if not self.available or not pcm:
            logger.debug('UI sound play_pcm skipped available=%s bytes=%s', self.available, len(pcm) if pcm else 0)
            return
        if sample_rate != self.__output_rate or channels != self.__output_channels:
            pcm = prepare_pcm_for_device(
                pcm,
                src_rate=sample_rate,
                src_channels=channels,
                dst_rate=self.__output_rate,
                dst_channels=self.__output_channels,
            )
        try:
            self.__queue.put_nowait(pcm)
            logger.debug('UI sound queued bytes=%s qsize≈%s', len(pcm), self.__queue.qsize())
        except queue.Full:
            try:
                self.__queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.__queue.put_nowait(pcm)
            except queue.Full:
                logger.debug('UI sound queue full; drop')

    def __run(self) -> None:
        logger.debug('UI sound worker started')
        while not self.__closed:
            try:
                item = self.__queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                break
            ok = self.__write_blocking(item)
            if not ok:
                logger.debug('UI sound worker stopping after failed write')
                break
        logger.debug('UI sound worker exit closed=%s', self.__closed)

    def __ensure_active(self, stream) -> None:
        """Start stream if PortAudio stopped it after idle underrun."""
        try:
            active = stream.is_active()
        except Exception:  # noqa: BLE001
            active = False
        if not active:
            logger.debug('UI sound stream inactive → start_stream()')
            stream.start_stream()

    def __write_blocking(self, pcm: bytes) -> bool:
        with self.__lock:
            stream = self.__stream
            if stream is None or self.__closed:
                return False
            frame_bytes = 2 * max(1, self.__output_channels)
            n_frames = len(pcm) // frame_bytes
            duration_ms = (n_frames / float(self.__output_rate)) * 1000.0 if self.__output_rate else 0.0
            t0 = time.perf_counter()
            try:
                self.__ensure_active(stream)
                logger.debug(
                    'UI sound write begin bytes=%s frames=%s ch=%s rate=%s dur_ms=%.1f active=%s',
                    len(pcm), n_frames, self.__output_channels, self.__output_rate,
                    duration_ms, stream.is_active(),
                )
                # Keyword-only underflow flag — do NOT pass False as num_frames.
                stream.write(pcm, exception_on_underflow=False)
                self.__writes += 1
                logger.debug(
                    'UI sound write end elapsed_ms=%.1f writes=%s active=%s',
                    (time.perf_counter() - t0) * 1000.0, self.__writes, stream.is_active(),
                )
                # Do NOT stop_stream here — that clipped short WAVs before ALSA drained.
                return True
            except Exception as exc:  # noqa: BLE001
                # Idle underrun between clicks must not kill the backend.
                msg = str(exc).lower()
                if 'underflow' in msg or 'underrun' in msg:
                    logger.debug('UI sound underflow ignored (%s); keep stream', exc)
                    try:
                        self.__ensure_active(stream)
                        stream.write(pcm, exception_on_underflow=False)
                        self.__writes += 1
                        return True
                    except Exception as exc_u:  # noqa: BLE001
                        logger.debug('UI sound rewrite after underflow failed (%s)', exc_u)
                logger.warning('UI sound write failed (%s)', exc)
                if not self.__reopen_used:
                    self.__reopen_used = True
                    if self.__reopen_stream():
                        try:
                            stream = self.__stream
                            assert stream is not None
                            self.__ensure_active(stream)
                            stream.write(pcm, exception_on_underflow=False)
                            self.__writes += 1
                            return True
                        except Exception as exc2:  # noqa: BLE001
                            logger.warning('UI sound rewrite failed (%s); silencing', exc2)
                self.__available = False
                return False

    def __reopen_stream(self) -> bool:
        try:
            import pyaudio
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
            self.__stream = self.__open_stream(pyaudio)
            logger.info('UI sound stream reopened: %s', self.describe_output())
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning('UI sound stream reopen failed (%s)', exc)
            self.__stream = None
            return False

    def _cleanup_pa(self) -> None:
        if self.__stream is not None:
            try:
                if self.__stream.is_active():
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

    def close(self) -> None:
        self.__closed = True
        self.__available = False
        try:
            self.__queue.put_nowait(None)
        except queue.Full:
            pass
        if self.__worker and self.__worker.is_alive() and threading.current_thread() is not self.__worker:
            self.__worker.join(timeout=1.5)
        self.__worker = None
        with self.__lock:
            self._cleanup_pa()
        logger.debug('UI sound backend closed')
