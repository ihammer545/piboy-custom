"""Tests for POST boot splash timing and AppState compose gating."""
from __future__ import annotations

from pathlib import Path

from injector import Injector
from PIL import Image

from app.boot_sequence import BOOT_DURATION_S, BOOT_SKIP_AFTER_S, BootSequence
from environment import AppConfig
from piboy import AppModule, AppState, register_shelter_apps
from ports.ui_sound import UiSoundEvent
from services.ui_sound import UiSoundService, UiSoundSettings


class _Clock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_boot_lines_reveal_over_time():
    clock = _Clock(0.0)
    boot = BootSequence(clock=clock, skip_after_s=1.5)
    assert boot.visible_lines()[0].startswith('УБЕЖИЩЕ')
    # 1 s between lines: POST is the 4th entry → appears at t=3
    clock.t = 2.5
    assert not any('POST' in line for line in boot.visible_lines())
    clock.t = 3.0
    assert any('POST' in line for line in boot.visible_lines())
    # ДИСКОВОД A READ OK is the 7th entry → t=6
    clock.t = 6.0
    assert any('ДИСКОВОД A' in line and 'OK' in line for line in boot.visible_lines())
    assert not boot.is_done()
    # Last line at t=11, then 4 s hold → done at 15
    clock.t = BOOT_DURATION_S - 0.1
    assert not boot.is_done()
    clock.t = BOOT_DURATION_S
    assert boot.is_done()


def test_boot_holds_four_seconds_after_last_line():
    clock = _Clock(0.0)
    boot = BootSequence(clock=clock)
    last_appear = max(t for t, _ in boot._BootSequence__lines)  # noqa: SLF001
    assert last_appear == 11.0
    clock.t = last_appear
    assert len(boot.visible_lines()) == 12
    assert not boot.is_done()
    clock.t = last_appear + 3.9
    assert not boot.is_done()
    clock.t = last_appear + 4.0
    assert boot.is_done()


def test_boot_skip_only_after_min_time():
    clock = _Clock(0.0)
    boot = BootSequence(clock=clock, skip_after_s=BOOT_SKIP_AFTER_S)
    assert boot.skip() is False
    assert not boot.skipped
    clock.t = BOOT_SKIP_AFTER_S
    assert boot.can_skip()
    assert boot.skip() is True
    assert boot.is_done()


def test_boot_render_fills_frame():
    clock = _Clock(3.0)  # enough for several lines with 1 s spacing
    boot = BootSequence(clock=clock)
    img = Image.new('RGB', (800, 480), (0, 0, 0))
    cfg = AppConfig()
    boot.render(img, accent=cfg.accent, font=cfg.font_standard, background=cfg.background)
    pixels = img.get_flattened_data() if hasattr(img, 'get_flattened_data') else img.getdata()
    assert any(px != (0, 0, 0) for px in pixels)


def test_compose_frame_boot_hides_tabs():
    module = AppModule()
    module.set_force_simulator(True)
    injector = Injector([module])
    state = injector.get(AppState)
    register_shelter_apps(injector, state)
    state.sounds.set_enabled(False)
    state.begin_boot_sequence()
    assert state.boot_active
    frame = state.compose_frame()
    assert frame.size == (800, 480)
    assert state.boot_active
    state._AppState__boot = None  # noqa: SLF001


def test_boot_wav_preloaded_and_playable():
    from tests.test_ui_sound import RecordingPort, _wait

    port = RecordingPort()
    svc = UiSoundService(port, UiSoundSettings(min_interval_ms=0),
                         sounds_dir=Path('resources/sounds'))
    assert UiSoundEvent.BOOT in svc._UiSoundService__samples  # noqa: SLF001
    samples = svc._UiSoundService__samples[UiSoundEvent.BOOT]  # noqa: SLF001
    assert samples
    assert len(samples[0].pcm) > 50_000
    svc.boot()
    _wait(port, 1, timeout=2.0)
    assert len(port.plays) == 1
    svc.stop_current()
    assert port.stops == 1
    svc.close()
