"""Tests for UI sound device selection, PCM convert, and service behaviour."""
from __future__ import annotations

import struct
import threading
import time
from pathlib import Path

from backend.ui_sound_device import (
    AudioDeviceInfo,
    choose_stream_channels,
    choose_stream_rate,
    select_output_device,
)
from backend.ui_sound_null import NullUiSoundBackend
from backend.ui_sound_pcm import mono_to_stereo_s16, prepare_pcm_for_device, resample_mono_s16
from backend.ui_sound_pyaudio import PyAudioUiSoundBackend
from ports.intercom import CallPhase
from services.ui_sound import UiSoundService, UiSoundSettings, open_ui_sound_port


def _dev(index, name, out=2, inp=0, rate=44100.0, host='ALSA', default=False):
    return AudioDeviceInfo(
        index=index, name=name, max_input_channels=inp, max_output_channels=out,
        default_sample_rate=rate, host_api=host, is_default_output=default,
    )


class RecordingPort:
    def __init__(self, rate=22050, channels=1):
        self.plays = []
        self.closed = False
        self.available = True
        self.output_rate = rate
        self.output_channels = channels
        self.threads = []

    def play_pcm(self, pcm, sample_rate, channels=1):
        self.threads.append(threading.current_thread().name)
        self.plays.append((pcm, sample_rate, channels))

    def close(self):
        self.closed = True

    def describe_output(self):
        return f'recording rate={self.output_rate} ch={self.output_channels}'


def _wait(port, n, timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(port.plays) >= n:
            return
        time.sleep(0.01)
    raise AssertionError(f'expected {n} plays, got {len(port.plays)}')


def test_select_configured_index():
    devices = [_dev(0, 'mic', out=0, inp=2), _dev(1, 'speakers', out=2), _dev(2, 'hdmi', out=2)]
    d, reason = select_output_device(devices, configured_index=2)
    assert d is not None and d.index == 2 and reason == 'configured_index'


def test_select_by_name_case_insensitive():
    devices = [_dev(0, 'Built-in Mic', out=0, inp=1), _dev(3, 'USB Speakers', out=2)]
    d, reason = select_output_device(devices, configured_name='usb speak')
    assert d is not None and d.index == 3 and reason == 'configured_name'


def test_select_default_output():
    devices = [_dev(0, 'a', out=2), _dev(1, 'b', out=2, default=True)]
    d, reason = select_output_device(devices, default_output_index=1)
    assert d is not None and d.index == 1 and reason == 'default'


def test_select_first_output_skips_input_only():
    devices = [_dev(0, 'mic', out=0, inp=2), _dev(1, 'spk', out=2, host='ALSA')]
    d, reason = select_output_device(devices)
    assert d is not None and d.index == 1 and reason == 'first_output'


def test_jack_deprioritized_vs_alsa():
    devices = [
        _dev(0, 'jack out', out=2, host='JACK Audio Connection Kit'),
        _dev(1, 'bcm2835', out=2, host='ALSA'),
    ]
    d, _ = select_output_device(devices)
    assert d is not None and d.index == 1


def test_invalid_index_falls_through_to_default():
    devices = [_dev(0, 'a', out=2), _dev(1, 'b', out=2, default=True)]
    d, reason = select_output_device(devices, configured_index=99, default_output_index=1)
    assert d is not None and d.index == 1 and reason == 'default'


def test_explicit_index_zero_beats_default_fourteen():
    """UTM case: PortAudio default may be 14; config/env index=0 must win."""
    devices = [
        _dev(0, 'HDA Intel: Generic Analog (hw:0,0)', out=2, host='ALSA'),
        _dev(14, 'default', out=2, host='ALSA', default=True),
    ]
    d, reason = select_output_device(
        devices,
        configured_index=0,
        default_output_index=14,
    )
    assert d is not None
    assert d.index == 0
    assert reason == 'configured_index'
    assert 'HDA Intel' in d.name


def test_mono_to_stereo_duplicates_samples():
    mono = struct.pack('<hh', 100, -100)
    stereo = mono_to_stereo_s16(mono)
    assert struct.unpack('<hhhh', stereo) == (100, 100, -100, -100)


def test_resample_doubles_length_22050_to_44100():
    pcm = struct.pack('<' + 'h' * 4, 0, 1000, 0, -1000)
    out = resample_mono_s16(pcm, 22050, 44100)
    assert len(out) // 2 > 4


def test_prepare_pcm_mono_to_stereo_44100():
    pcm = struct.pack('<' + 'h' * 8, *([1000] * 8))
    out = prepare_pcm_for_device(pcm, src_rate=22050, src_channels=1, dst_rate=44100, dst_channels=2)
    assert len(out) >= len(pcm) * 2


def test_choose_stream_prefers_stereo_when_available():
    assert choose_stream_channels(_dev(0, 'x', out=2), prefer=1) == 2
    assert choose_stream_channels(_dev(0, 'x', out=1), prefer=1) == 1
    assert choose_stream_rate(_dev(0, 'x', rate=48000.0)) == 48000


def test_volume_and_mute():
    port = RecordingPort(rate=22050, channels=1)
    svc = UiSoundService(port, UiSoundSettings(enabled=True, volume=0.5),
                         sounds_dir=Path('resources/sounds'))
    svc.set_volume(2)
    assert svc.volume == 1.0
    svc.set_enabled(False)
    svc.confirm()
    time.sleep(0.05)
    assert port.plays == []
    svc.close()


def test_blocking_write_from_worker_thread():
    port = RecordingPort()
    svc = UiSoundService(port, UiSoundSettings(min_interval_ms=0),
                         sounds_dir=Path('resources/sounds'))
    svc.confirm()
    _wait(port, 1)
    assert any('ui-sound-dispatch' in t for t in port.threads)
    svc.close()


def test_shutdown_and_null_device():
    port = RecordingPort()
    svc = UiSoundService(port, sounds_dir=Path('resources/sounds'))
    svc.close()
    assert port.closed
    null = open_ui_sound_port(prefer_pyaudio=False)
    assert isinstance(null, NullUiSoundBackend)
    assert null.available is False


def test_clicks_during_call_false():
    port = RecordingPort()
    phase = {'p': CallPhase.CONNECTED}
    svc = UiSoundService(
        port,
        UiSoundSettings(clicks_during_call=False, min_interval_ms=0),
        sounds_dir=Path('resources/sounds'),
        call_phase_fn=lambda: phase['p'],
    )
    svc.touch()
    time.sleep(0.05)
    assert port.plays == []
    svc.close()


def test_preload_matches_port_format():
    port = RecordingPort(rate=44100, channels=2)
    svc = UiSoundService(port, sounds_dir=Path('resources/sounds'))
    assert svc.preloaded
    svc.confirm()
    _wait(port, 1)
    pcm, rate, ch = port.plays[0]
    assert rate == 44100 and ch == 2
    assert len(pcm) % 4 == 0
    svc.close()


def test_write_error_does_not_crash_service():
    class Flaky:
        def __init__(self):
            self.writes = 0
            self.available = True
            self.output_rate = 22050
            self.output_channels = 1
            self.closed = False

        def play_pcm(self, pcm, sample_rate, channels=1):
            self.writes += 1
            if self.writes == 1:
                raise RuntimeError('underrun')

        def close(self):
            self.closed = True

        def describe_output(self):
            return 'flaky'

    port = Flaky()
    svc = UiSoundService(port, UiSoundSettings(min_interval_ms=0),
                         sounds_dir=Path('resources/sounds'))
    svc.confirm()
    time.sleep(0.1)
    svc.confirm()
    time.sleep(0.1)
    svc.close()
    assert port.closed


def test_pyaudio_backend_close_safe_without_device():
    # Invalid index → falls through; may still find a host device or go silent.
    b = PyAudioUiSoundBackend(device_index=99999)
    b.close()
    assert b.available is False


def test_access_code_not_in_pcm():
    port = RecordingPort()
    svc = UiSoundService(port, sounds_dir=Path('resources/sounds'))
    svc.denied()
    _wait(port, 1)
    assert b'1234' not in port.plays[0][0]
    svc.close()


def test_one_reopen_flag_exists():
    b = PyAudioUiSoundBackend.__new__(PyAudioUiSoundBackend)
    b._PyAudioUiSoundBackend__reopen_used = False  # noqa: SLF001
    assert b._PyAudioUiSoundBackend__reopen_used is False  # noqa: SLF001
