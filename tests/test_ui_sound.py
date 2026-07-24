"""Tests for UiSoundService (Null backend — no audio device required)."""
from __future__ import annotations

import time
from pathlib import Path

from backend.ui_sound_null import NullUiSoundBackend
from ports.intercom import CallPhase
from ports.ui_sound import UiSoundEvent
from services.ui_sound import UiSoundService, UiSoundSettings, open_ui_sound_port


class RecordingPort:
    def __init__(self):
        self.plays: list[tuple[bytes, int, int]] = []
        self.closed = False
        self.available = True

    def play_pcm(self, pcm: bytes, sample_rate: int, channels: int = 1) -> None:
        self.plays.append((pcm, sample_rate, channels))

    def close(self) -> None:
        self.closed = True


def _wait_plays(port: RecordingPort, n: int, timeout: float = 1.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(port.plays) >= n:
            return
        time.sleep(0.01)
    raise AssertionError(f'expected {n} plays, got {len(port.plays)}')


def test_preload_once(tmp_path: Path):
    port = RecordingPort()
    svc = UiSoundService(port, UiSoundSettings(enabled=True), sounds_dir=tmp_path)
    assert svc.preloaded
    svc.preload()
    assert svc.preloaded
    svc.close()


def test_one_action_one_sound():
    port = RecordingPort()
    clock = {'t': 0.0}
    svc = UiSoundService(
        port,
        UiSoundSettings(enabled=True, min_interval_ms=0),
        sounds_dir=Path('resources/sounds'),
        clock=lambda: clock['t'],
    )
    svc.confirm()
    _wait_plays(port, 1)
    assert len(port.plays) == 1
    svc.close()


def test_click_debounce():
    port = RecordingPort()
    clock = {'t': 1.0}
    svc = UiSoundService(
        port,
        UiSoundSettings(enabled=True, min_interval_ms=30),
        sounds_dir=Path('resources/sounds'),
        clock=lambda: clock['t'],
    )
    svc.key()
    svc.key()  # within interval — dropped
    _wait_plays(port, 1)
    clock['t'] = 1.05
    svc.key()
    _wait_plays(port, 2)
    svc.close()


def test_queue_limit_drops_old_clicks():
    port = RecordingPort()
    # Block worker by using a port that records but service queue fills before drain
    clock = {'t': 0.0}
    settings = UiSoundSettings(enabled=True, min_interval_ms=0, queue_max=4)
    svc = UiSoundService(port, settings, sounds_dir=Path('resources/sounds'), clock=lambda: clock['t'])
    # Flood clicks faster than worker; queue stays ≤ 4
    for i in range(20):
        clock['t'] = float(i)
        svc.touch()
    time.sleep(0.2)
    assert svc.queue_len <= 4
    svc.close()


def test_mute_and_volume_clamp():
    port = RecordingPort()
    svc = UiSoundService(port, UiSoundSettings(enabled=True, volume=0.5),
                         sounds_dir=Path('resources/sounds'))
    svc.set_enabled(False)
    svc.confirm()
    time.sleep(0.05)
    assert port.plays == []
    svc.set_enabled(True)
    svc.set_volume(2.0)
    assert svc.volume == 1.0
    svc.set_volume(-1.0)
    assert svc.volume == 0.0
    svc.close()


def test_missing_device_uses_null():
    port = open_ui_sound_port(prefer_pyaudio=False)
    assert isinstance(port, NullUiSoundBackend)
    assert port.available is False
    port.play_pcm(b'\x00\x00', 22050)
    port.close()


def test_disabled_target_is_silent_by_policy():
    """Documented policy: disabled hits stay silent (hit_test filters them)."""
    from app.ui_kit import make_hit
    from interaction.touch.events import Rect, hit_test
    hits = [make_hit(Rect(0, 0, 40, 40), 'x', enabled=False)]
    assert hit_test(hits, 10, 10) is None


def test_shutdown_closes_port():
    port = RecordingPort()
    svc = UiSoundService(port, sounds_dir=Path('resources/sounds'))
    svc.close()
    assert port.closed
    svc.confirm()
    time.sleep(0.05)
    assert port.plays == []


def test_clicks_suppressed_during_call():
    port = RecordingPort()
    phase = {'p': CallPhase.CONNECTED}
    svc = UiSoundService(
        port,
        UiSoundSettings(enabled=True, clicks_during_call=False, min_interval_ms=0),
        sounds_dir=Path('resources/sounds'),
        call_phase_fn=lambda: phase['p'],
    )
    svc.touch()
    time.sleep(0.05)
    assert port.plays == []
    svc.confirm()  # non-click still allowed
    _wait_plays(port, 1)
    phase['p'] = CallPhase.IDLE
    svc.touch()
    _wait_plays(port, 2)
    svc.close()


def test_access_code_not_in_sound_payload():
    port = RecordingPort()
    svc = UiSoundService(port, sounds_dir=Path('resources/sounds'))
    svc.denied()
    _wait_plays(port, 1)
    pcm, _, _ = port.plays[0]
    # PCM must not contain ASCII digits of demo codes as text
    assert b'1234' not in pcm
    assert b'0000' not in pcm
    assert b'9999' not in pcm
    svc.close()


def test_play_event_variants_cycle():
    port = RecordingPort()
    clock = {'t': 0.0}
    svc = UiSoundService(
        port,
        UiSoundSettings(min_interval_ms=0),
        sounds_dir=Path('resources/sounds'),
        clock=lambda: clock['t'],
    )
    for i in range(3):
        clock['t'] = float(i)
        svc.key()
    _wait_plays(port, 3)
    # Different click variants should not all be identical byte-for-byte
    assert len({p[0] for p in port.plays}) >= 2
    svc.close()
