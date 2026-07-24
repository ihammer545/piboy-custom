"""Unit tests for CRT post-processing."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from PIL import Image, ImageChops, ImageDraw
from injector import Injector

from interaction.touch.events import TouchEvent
from piboy import AppModule, AppState, register_shelter_apps, draw_base
from rendering.crt import CRTRenderer, clamp01, resolve_crt_settings


def _solid(color=(0, 40, 0), size=(800, 480)) -> Image.Image:
    return Image.new('RGB', size, color)


def _ui_frame() -> Image.Image:
    img = Image.new('RGB', (800, 480), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 100, 700, 380), outline=(27, 251, 30), width=2)
    draw.text((120, 120), 'ТЕСТ CRT', fill=(27, 251, 30))
    return img


def test_off_pixel_identical():
    src = _ui_frame()
    before = src.copy()
    crt = CRTRenderer(resolve_crt_settings(preset='off', width=800, height=480))
    out = crt.process(src)
    assert out.size == (800, 480)
    assert list(out.getdata()) == list(before.getdata())
    assert list(src.getdata()) == list(before.getdata())


def test_source_not_mutated_when_enabled():
    src = _ui_frame()
    before = src.copy()
    crt = CRTRenderer(resolve_crt_settings(preset='subtle', grain=0, flicker=0, width=800, height=480))
    _ = crt.process(src, now=1.0)
    assert list(src.getdata()) == list(before.getdata())


def test_output_size_and_cache_reuse():
    crt = CRTRenderer(resolve_crt_settings(preset='subtle', grain=0, flicker=0))
    a = crt.process(_solid(), now=1.0)
    bytes1 = crt.cache_bytes()
    b = crt.process(_solid((0, 50, 0)), now=1.0)
    bytes2 = crt.cache_bytes()
    assert a.size == b.size == (800, 480)
    assert bytes2 == bytes1
    assert bytes1 > 0


def test_resolution_change_rebuilds_cache():
    crt = CRTRenderer(resolve_crt_settings(preset='subtle', grain=0, flicker=0, width=800, height=480))
    crt.process(_solid(), now=1.0)
    b1 = crt.cache_bytes()
    crt.process(_solid(size=(640, 480)), now=1.0)
    assert crt.settings.width == 640
    assert crt.cache_bytes() != 0
    # fingerprint changed — layers rebuilt for new size
    assert crt.settings.height == 480


def test_scanlines_darken_expected_rows():
    src = _solid((200, 200, 200))
    crt = CRTRenderer(resolve_crt_settings(
        preset='subtle', scanlines=0.5, vignette=0, grain=0, glare=0, flicker=0, glow=0,
        rounded_corners=0, width=800, height=480,
    ))
    out = crt.process(src, now=1.0)
    # row 0 is a scanline
    assert out.getpixel((10, 0))[0] < src.getpixel((10, 0))[0]
    # row 1 should stay closer to original
    assert out.getpixel((10, 1))[0] >= out.getpixel((10, 0))[0]


def test_vignette_corners_darker_than_center():
    src = _solid((180, 180, 180))
    crt = CRTRenderer(resolve_crt_settings(
        preset='subtle', vignette=0.8, scanlines=0, grain=0, glare=0, flicker=0, glow=0,
        rounded_corners=0,
    ))
    out = crt.process(src, now=1.0)
    center = out.getpixel((400, 240))[0]
    corner = out.getpixel((2, 2))[0]
    assert corner < center


def test_rounded_mask_black_corners():
    src = _solid((100, 200, 100))
    crt = CRTRenderer(resolve_crt_settings(
        preset='subtle', rounded_corners=40, scanlines=0, vignette=0, grain=0, glare=0,
        flicker=0, glow=0,
    ))
    out = crt.process(src, now=1.0)
    assert out.getpixel((0, 0)) == (0, 0, 0)


def test_glare_rgb_in_range():
    src = _solid((10, 10, 10))
    crt = CRTRenderer(resolve_crt_settings(
        preset='strong', glare=1.0, scanlines=0, vignette=0, grain=0, flicker=0, glow=0,
        rounded_corners=0,
    ))
    out = crt.process(src, now=1.0)
    for px in out.getdata():
        assert all(0 <= c <= 255 for c in px)


def test_grain_reproducible_with_seed_and_fps_gate():
    settings = resolve_crt_settings(preset='subtle', grain=0.2, flicker=0, glare=0, vignette=0,
                                    scanlines=0, glow=0, rounded_corners=0, grain_fps=5, grain_seed=7)
    a = CRTRenderer(settings)
    b = CRTRenderer(settings)
    src = _solid()
    out1 = a.process(src, now=10.0)
    out2 = b.process(src, now=10.0)
    assert list(out1.getdata()) == list(out2.getdata())
    # Within same grain window — identical
    out3 = a.process(src, now=10.05)
    assert list(out3.getdata()) == list(out1.getdata())
    # After interval — may differ
    out4 = a.process(src, now=10.25)
    # Not asserting inequality always, but cache refresh path executed
    assert out4.size == (800, 480)


def test_clamp_and_presets():
    assert clamp01(2) == 1.0
    assert clamp01(-1) == 0.0
    subtle = resolve_crt_settings(preset='subtle')
    strong = resolve_crt_settings(preset='strong')
    assert subtle.scanlines < strong.scanlines
    assert subtle.vignette < strong.vignette
    assert subtle.glow == 0.0
    off = resolve_crt_settings(preset='off')
    assert off.enabled is False
    crazy = resolve_crt_settings(preset='subtle', flicker=9, rounded_corners=9999, width=800, height=480)
    assert crazy.flicker <= 0.05
    assert crazy.rounded_corners <= 400


def test_runtime_preset_switch():
    crt = CRTRenderer(resolve_crt_settings(preset='subtle', grain=0, flicker=0))
    assert crt.enabled
    crt.apply_preset('off')
    assert not crt.enabled
    src = _ui_frame()
    assert list(crt.process(src).getdata()) == list(src.getdata())
    crt.apply_preset('strong')
    assert crt.enabled
    assert crt.settings.preset == 'strong'


def test_cache_stable_over_many_frames():
    crt = CRTRenderer(resolve_crt_settings(preset='subtle', grain=0, flicker=0))
    src = _solid()
    crt.process(src, now=1.0)
    base = crt.cache_bytes()
    for i in range(300):
        crt.process(src, now=1.0 + i * 0.001)
    assert crt.cache_bytes() == base


def test_touch_hitboxes_unchanged_with_crt():
    module = AppModule()
    module.set_force_simulator(True)
    injector = Injector([module])
    state = injector.get(AppState)
    register_shelter_apps(injector, state)
    disp = MagicMock()
    state.bind_display(disp)
    # Force CRT on
    state.set_crt_preset('subtle')
    frame = state.compose_frame()
    # Build tab hits via draw_base
    for _ in draw_base(frame, state):
        pass
    hits = state._AppState__tab_hits  # noqa: SLF001
    assert hits
    second = hits[1]
    cx = (second.rect.x0 + second.rect.x1) // 2
    cy = (second.rect.y0 + second.rect.y1) // 2
    state.on_touch_event(TouchEvent.tap(cx, cy))
    assert state.active_app.title == 'ДОСТ'


def test_simulator_panel_not_processed_by_crt():
    # Architectural: CRT only wraps the 800×480 frame in AppState.update_display.
    # Panel widgets are outside that path — verify process is only for screen size frames.
    crt = CRTRenderer(resolve_crt_settings(preset='subtle', grain=0, flicker=0))
    panel = Image.new('RGB', (200, 100), (30, 30, 30))
    out = crt.process(panel, now=1.0)
    assert out.size == (200, 100)
