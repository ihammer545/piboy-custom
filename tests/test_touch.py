"""Unit tests for touch transform, hit testing, debounce, and UI routing."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from injector import Injector

from app.ui_kit import make_hit
from backend.simulator import SimulatorBackend
from environment import Environment, force_simulator
from interaction.touch.events import HitTarget, Rect, TapGate, TouchEvent, hit_test
from interaction.touch.evdev_source import open_touch_source
from interaction.touch.simulator import SimulatorTouchInput
from interaction.touch.source import NullTouchSource
from interaction.touch.transform import TouchTransform, map_raw_to_screen
from piboy import AppModule, AppState, draw_base, register_shelter_apps
from services.event_log import EventLogService
from services.terminal import AccessService, DeviceService, IntercomService


def test_scale_corners():
    # raw 0..100 maps to 800×480
    assert map_raw_to_screen(0, 0, raw_x_max=100, raw_y_max=100) == (0, 0)
    assert map_raw_to_screen(100, 100, raw_x_max=100, raw_y_max=100) == (799, 479)
    assert map_raw_to_screen(50, 50, raw_x_max=100, raw_y_max=100) == (400, 240)


def test_clamp_outside_range():
    x, y = map_raw_to_screen(-50, 9999, raw_x_max=100, raw_y_max=100)
    assert x == 0
    assert y == 479


def test_invert_axes():
    x, y = map_raw_to_screen(0, 0, raw_x_max=100, raw_y_max=100, invert_x=True, invert_y=True)
    assert (x, y) == (799, 479)


def test_swap_axes():
    # raw_x drives Y when swapped
    x, y = map_raw_to_screen(100, 0, raw_x_max=100, raw_y_max=100, swap_axes=True)
    assert x == 0
    assert y == 479


def test_rotations():
    base = dict(raw_x_max=100, raw_y_max=100)
    assert map_raw_to_screen(0, 0, **base, rotation=0) == (0, 0)
    # 90°: (0,0) -> (ny, 1-nx) = (0, 1) -> (0, 479)
    assert map_raw_to_screen(0, 0, **base, rotation=90) == (0, 479)
    assert map_raw_to_screen(0, 0, **base, rotation=180) == (799, 479)
    # 270°: (0,0) -> (1-ny, nx) = (1, 0) -> (799, 0)
    assert map_raw_to_screen(0, 0, **base, rotation=270) == (799, 0)


def test_touch_transform_class():
    t = TouchTransform(raw_x_max=100, raw_y_max=100, invert_x=True)
    assert t.map_point(0, 50) == (799, 240)


def test_debounce_and_hold_single_fire():
    gate = TapGate(debounce_ms=100)
    assert gate.on_down(1.0) is True
    assert gate.on_down(1.01) is False  # still held / second down ignored
    gate.on_up()
    assert gate.on_down(1.05) is False  # within debounce window
    gate.on_up()
    assert gate.on_down(1.20) is True


def test_hit_testing_button_and_disabled():
    enabled = make_hit(Rect(10, 10, 60, 60), 'ok', enabled=True, min_w=44, min_h=44)
    disabled = make_hit(Rect(100, 10, 150, 60), 'no', enabled=False, min_w=44, min_h=44)
    targets = [enabled, disabled]
    assert hit_test(targets, 30, 30) is enabled
    assert hit_test(targets, 120, 30) is None
    assert hit_test(targets, 0, 0) is None


def _build_state() -> tuple[AppState, Injector]:
    module = AppModule()
    module.set_force_simulator(True)
    injector = Injector([module])
    # Override draw callback path without Tk
    state = injector.get(AppState)
    register_shelter_apps(injector, state)
    display = MagicMock()
    state.bind_display(display)
    # Build chrome hitboxes
    image = state.clear_buffer()
    for _ in draw_base(image, state):
        pass
    return state, injector


def test_tab_switch_by_touch():
    state, _ = _build_state()
    assert state.active_app.title == 'СВЗ'
    # Tap second tab hit if present
    assert state._AppState__tab_hits  # noqa: SLF001
    second = state._AppState__tab_hits[1]  # noqa: SLF001
    cx = (second.rect.x0 + second.rect.x1) // 2
    cy = (second.rect.y0 + second.rect.y1) // 2
    state.on_touch_event(TouchEvent.tap(cx, cy))
    assert state.active_app.title == 'ДОСТ'


def test_tab_labels_share_baseline():
    """Cyrillic tab titles must not shift vertically (regression for ДОСТ/СРЕД clipping)."""
    from PIL import Image

    from piboy import draw_header

    state, _ = _build_state()
    image = Image.new('RGB', state.environment.app_config.resolution, state.environment.app_config.background)
    header, x0, y0 = draw_header(image, state)
    accent = state.environment.app_config.accent
    tops: list[int] = []
    for hit in state._AppState__tab_hits:  # noqa: SLF001
        # Hit rects are in full-frame coords; header crop starts at (x0, y0).
        x_start = max(0, hit.rect.x0 - x0)
        x_end = min(header.width, hit.rect.x1 - x0)
        top_ink = None
        for y in range(header.height):
            for x in range(x_start, x_end):
                if header.getpixel((x, y))[:3] == accent[:3]:
                    top_ink = y
                    break
            if top_ink is not None:
                break
        assert top_ink is not None, 'tab label not drawn'
        tops.append(top_ink)
    assert max(tops) - min(tops) <= 2


def test_access_keypad_touch_and_no_code_in_log():
    state, injector = _build_state()
    # Switch to Access
    state.switch_to_app(1)
    app = state.active_app
    image = state.clear_buffer()
    ox, oy = state.app_content_origin()
    list(app.draw(image.crop((ox, oy, ox + state.environment.app_config.app_size[0],
                              oy + state.environment.app_config.app_size[1])), False))
    # Press digits via on_digit (same path as keyboard) then OK via tap if possible
    assert app.on_digit('1')
    assert app.on_digit('2')
    assert app.on_digit('3')
    assert app.on_digit('4')
    access = injector.get(AccessService)
    result, _ = access.submit_code('1234')
    # Clear digits through app leave
    app.on_app_leave()
    log = injector.get(EventLogService)
    blob = ' '.join(e.message for e in log.list_events())
    assert '1234' not in blob
    assert result.outcome.value.startswith('granted')


def test_access_on_screen_keypad_hit():
    state, injector = _build_state()
    state.switch_to_app(1)
    app = state.active_app
    cfg = state.environment.app_config
    image = state.clear_buffer()
    content = image.crop((cfg.app_side_offset, cfg.app_top_offset,
                          cfg.width - cfg.app_side_offset, cfg.height - cfg.app_bottom_offset))
    list(app.draw(content, False))
    # Find hit for digit '1'
    hits = app._AccessApp__hits  # noqa: SLF001
    one = next(h for h in hits if h.action == '1')
    assert app.on_tap((one.rect.x0 + one.rect.x1) // 2, (one.rect.y0 + one.rect.y1) // 2)
    ok = next(h for h in hits if h.action == 'OK')
    # enter remaining digits then OK
    for d in '234':
        app.on_digit(d)
    list(app.draw(content, False))
    hits = app._AccessApp__hits  # noqa: SLF001
    ok = next(h for h in hits if h.action == 'OK')
    app.on_tap((ok.rect.x0 + ok.rect.x1) // 2, (ok.rect.y0 + ok.rect.y1) // 2)
    log = injector.get(EventLogService)
    assert not any('1234' in e.message for e in log.list_events())


def test_devices_vent_toggle_via_touch():
    state, injector = _build_state()
    state.switch_to_app(3)  # СИСТ
    app = state.active_app
    cfg = state.environment.app_config
    content = state.clear_buffer().crop((cfg.app_side_offset, cfg.app_top_offset,
                                         cfg.width - cfg.app_side_offset, cfg.height - cfg.app_bottom_offset))
    list(app.draw(content, False))
    # Select ventilation (first device)
    hits = app._DevicesApp__hits  # noqa: SLF001
    vent_row = next(h for h in hits if h.action == 'device:0')
    app.on_tap((vent_row.rect.x0 + vent_row.rect.x1) // 2, (vent_row.rect.y0 + vent_row.rect.y1) // 2)
    list(app.draw(content, False))
    hits = app._DevicesApp__hits  # noqa: SLF001
    toggle = next(h for h in hits if h.action == 'toggle')
    app.on_tap((toggle.rect.x0 + toggle.rect.x1) // 2, (toggle.rect.y0 + toggle.rect.y1) // 2)
    # requires confirm
    list(app.draw(content, False))
    hits = app._DevicesApp__hits  # noqa: SLF001
    confirm = next(h for h in hits if h.action == 'confirm')
    app.on_tap((confirm.rect.x0 + confirm.rect.x1) // 2, (confirm.rect.y0 + confirm.rect.y1) // 2)
    devices = injector.get(DeviceService)
    vent = next(d for d in devices.devices() if d.device_id == 'vent')
    assert vent.powered_on is True


def test_footer_touch_ignored():
    state, _ = _build_state()
    footer = state._AppState__footer_rect  # noqa: SLF001
    assert footer is not None
    before = state.active_app_index
    state.on_touch_event(TouchEvent.tap((footer.x0 + footer.x1) // 2, (footer.y0 + footer.y1) // 2))
    assert state.active_app_index == before


def test_simulator_touch_scaling_and_gate():
    events = []
    src = SimulatorTouchInput(on_event=events.append, debounce_ms=0, screen_width=800, screen_height=480)
    src.start()
    assert src.inject_canvas_click(0, 0, 800, 480)
    assert events[-1].x == 0 and events[-1].y == 0
    assert src.inject_canvas_click(799, 479, 800, 480)
    assert events[-1].x == 799 and events[-1].y == 479
    # scaled canvas 400×240 → full screen (rounding may be ±1)
    events.clear()
    assert src.inject_canvas_click(200, 120, 400, 240)
    assert abs(events[-1].x - 400) <= 1
    assert abs(events[-1].y - 240) <= 1
    src.stop()


def test_evdev_fallback_without_device():
    from interaction.touch.transform import TouchTransform
    source = open_touch_source('/dev/input/does-not-exist', TouchTransform(), 120, lambda e: None, enabled=True)
    assert isinstance(source, NullTouchSource)
    source.stop()


def test_touch_source_stop_is_safe():
    src = SimulatorTouchInput(debounce_ms=10)
    src.start()
    src.stop()
    src.stop()
    null = NullTouchSource('x')
    null.start()
    null.stop()


def test_offline_device_toggle_disabled():
    state, injector = _build_state()
    devices = injector.get(DeviceService)
    devices.set_online('vent', False)
    state.switch_to_app(3)
    app = state.active_app
    cfg = state.environment.app_config
    content = state.clear_buffer().crop((cfg.app_side_offset, cfg.app_top_offset,
                                         cfg.width - cfg.app_side_offset, cfg.height - cfg.app_bottom_offset))
    list(app.draw(content, False))
    hits = app._DevicesApp__hits  # noqa: SLF001
    toggle = next(h for h in hits if h.action == 'toggle')
    assert toggle.enabled is False
    assert app.on_tap((toggle.rect.x0 + toggle.rect.x1) // 2, (toggle.rect.y0 + toggle.rect.y1) // 2) is False
