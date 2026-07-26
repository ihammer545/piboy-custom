"""Tests for audio setup persist, ranking helpers, and first-run session."""
from __future__ import annotations

from pathlib import Path

import environment
from app.audio_setup import AudioSetupSession
from backend.ui_sound_device import AudioDeviceInfo
from environment import Environment, UiSoundsConfig, save_ui_sound_local
from services.ui_sound import UiSoundService, UiSoundSettings


def _dev(index, name, out=2, host='ALSA', default=False):
    return AudioDeviceInfo(
        index=index, name=name, max_input_channels=0, max_output_channels=out,
        default_sample_rate=44100.0, host_api=host, is_default_output=default,
    )


class _Port:
    def __init__(self):
        self.plays = []
        self.closed = False
        self.available = True
        self.output_rate = 22050
        self.output_channels = 1
        self._devices = [
            _dev(0, 'HDA Intel: Generic Analog (hw:0,0)'),
            _dev(14, 'default', default=True),
        ]
        self._selected = self._devices[0]
        self.stops = 0

    def play_pcm(self, pcm, sample_rate, channels=1):
        self.plays.append((pcm, sample_rate, channels))

    def stop_current(self):
        self.stops += 1

    def close(self):
        self.closed = True

    def list_devices(self):
        return list(self._devices)

    @property
    def selected_device(self):
        return self._selected

    def describe_output(self):
        return f'index={self._selected.index}'


def test_save_ui_sound_local_roundtrip(tmp_path: Path, monkeypatch):
    local = tmp_path / 'config.local.yaml'
    env = Environment()
    environment.configure()
    save_ui_sound_local(
        index=0, name='HDA Intel', setup_done=True,
        local_path=str(local), env=env,
    )
    assert local.is_file()
    assert env.audio.ui_sounds.output_device_index == 0
    assert env.audio.ui_sounds.audio_setup_done is True
    text = local.read_text(encoding='utf-8')
    assert 'output_device_index: 0' in text
    assert 'audio_setup_done: true' in text

    env2 = Environment()
    environment._apply_local_yaml(env2, str(local))
    assert env2.audio.ui_sounds.output_device_index == 0
    assert env2.audio.ui_sounds.audio_setup_done is True


def test_audio_setup_session_cycle_and_skip():
    devices = [_dev(0, 'HDA'), _dev(1, 'USB Speakers')]
    session = AudioSetupSession(devices, start_index=0)
    assert session.current is not None and session.current.index == 0
    nxt = session.next_device()
    assert nxt is not None and nxt.index == 1
    session.mark_skip()
    assert session.done and session.result == 'skip'


def test_audio_setup_session_hear():
    session = AudioSetupSession([_dev(3, 'bcm2835 Headphones')])
    session.mark_hear()
    assert session.done and session.result == 'hear'


def test_rebind_output_swaps_port(monkeypatch):
    ports = []

    def fake_open(**kwargs):
        p = _Port()
        if kwargs.get('device_index') is not None:
            for d in p._devices:
                if d.index == kwargs['device_index']:
                    p._selected = d
                    break
        ports.append(p)
        return p

    monkeypatch.setattr('services.ui_sound.open_ui_sound_port', fake_open)
    first = _Port()
    svc = UiSoundService(first, UiSoundSettings(min_interval_ms=0),
                         sounds_dir=Path('resources/sounds'))
    info = svc.rebind_output(14, selection_source='config')
    assert '14' in info or first.closed
    assert first.closed
    assert len(ports) >= 1
    listed = svc.list_output_devices()
    assert listed and listed[0].index == 0  # ranked HDA first
    svc.close()


def test_default_audio_setup_done_false():
    assert UiSoundsConfig().audio_setup_done is False
