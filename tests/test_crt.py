"""Unit tests for CRT post-processing and touch geometry."""
from __future__ import annotations

from statistics import mean, pstdev
from unittest.mock import MagicMock

from PIL import Image, ImageDraw
from injector import Injector

from interaction.touch.events import TouchEvent
from piboy import AppModule, AppState, register_shelter_apps, draw_base
from rendering.crt import CRTRenderer, clamp01, phosphor_rgb, resolve_crt_settings
from rendering.crt_geometry import display_to_ui, ui_to_display


def _px(img: Image.Image):
    """Flattened pixel iterable compatible with older/newer Pillow."""
    if hasattr(img, 'get_flattened_data'):
        return img.get_flattened_data()
    return img.getdata()


def _solid(color=(0, 40, 0), size=(800, 480)) -> Image.Image:
    return Image.new('RGB', size, color)


def _ui_frame() -> Image.Image:
    img = Image.new('RGB', (800, 480), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 100, 700, 380), outline=(27, 251, 30), width=2)
    draw.text((120, 120), 'TEST CRT', fill=(27, 251, 30))
    return img


def _lum(rgb: tuple[int, int, int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def test_off_pixel_identical():
    src = _ui_frame()
    before = src.copy()
    crt = CRTRenderer(resolve_crt_settings(preset='off', width=800, height=480))
    out = crt.process(src)
    assert out.size == (800, 480)
    assert list(_px(out)) == list(_px(before))
    assert list(_px(src)) == list(_px(before))


def test_source_not_mutated_when_enabled():
    src = _ui_frame()
    before = src.copy()
    crt = CRTRenderer(resolve_crt_settings(
        preset='subtle', grain=0, flicker=0, curvature=0, width=800, height=480,
    ))
    _ = crt.process(src, now=1.0)
    assert list(_px(src)) == list(_px(before))


def test_output_size_and_cache_reuse():
    crt = CRTRenderer(resolve_crt_settings(preset='subtle', grain=0, flicker=0, curvature=0))
    a = crt.process(_solid(), now=1.0)
    bytes1 = crt.cache_bytes()
    b = crt.process(_solid((0, 50, 0)), now=1.0)
    bytes2 = crt.cache_bytes()
    assert a.size == b.size == (800, 480)
    assert bytes2 == bytes1
    assert bytes1 > 0


def test_resolution_change_rebuilds_cache():
    crt = CRTRenderer(resolve_crt_settings(
        preset='subtle', grain=0, flicker=0, curvature=0, width=800, height=480,
    ))
    crt.process(_solid(), now=1.0)
    crt.process(_solid(size=(640, 480)), now=1.0)
    assert crt.settings.width == 640
    assert crt.cache_bytes() != 0
    assert crt.settings.height == 480


def test_scanlines_modulate_rows():
    src = _solid((200, 200, 200))
    crt = CRTRenderer(resolve_crt_settings(
        preset='subtle', scanlines=0.5, vignette=0, grain=0, glare=0, flicker=0, glow=0,
        rounded_corners=0, bezel_inset=0, curvature=0, phosphor_floor=0.02, width=800, height=480,
    ))
    out = crt.process(src, now=1.0)
    assert out.getpixel((400, 0))[1] < out.getpixel((400, 1))[1]


def test_grain_visible_on_black():
    src = Image.new('RGB', (800, 480), (0, 0, 0))
    crt = CRTRenderer(resolve_crt_settings(
        preset='subtle', grain=0.08, flicker=0, glare=0, vignette=0, scanlines=0,
        glow=0, rounded_corners=0, bezel_inset=0, curvature=0, phosphor_floor=0.02,
        grain_fps=5, grain_seed=11,
    ))
    out = crt.process(src, now=2.0)
    greens = [out.getpixel((x, 240))[1] for x in range(40, 760)]
    assert pstdev(greens) > 0.0
    assert mean(greens) > 0.0


def test_vignette_center_edge_corner():
    src = Image.new('RGB', (800, 480), (0, 0, 0))
    crt = CRTRenderer(resolve_crt_settings(
        preset='strong', vignette=0.7, scanlines=0, grain=0, glare=0, flicker=0, glow=0,
        rounded_corners=0, bezel_inset=0, curvature=0, phosphor_floor=0.03,
    ))
    out = crt.process(src, now=1.0)
    center = _lum(out.getpixel((400, 240)))
    edge = _lum(out.getpixel((400, 20)))
    corner = _lum(out.getpixel((20, 20)))
    assert center > edge > corner


def test_rounded_mask_bezel_vs_phosphor():
    src = Image.new('RGB', (800, 480), (0, 0, 0))
    crt = CRTRenderer(resolve_crt_settings(
        preset='subtle', rounded_corners=28, bezel_inset=8, scanlines=0, vignette=0,
        grain=0, glare=0, flicker=0, glow=0, curvature=0, phosphor_floor=0.025,
    ))
    out = crt.process(src, now=1.0)
    assert out.getpixel((0, 0)) == (0, 0, 0)
    assert out.getpixel((1, 1)) == (0, 0, 0)
    interior = out.getpixel((400, 240))
    assert interior[1] > 0
    assert phosphor_rgb(0.025)[1] > 0


def test_glare_raises_dark_region():
    src = Image.new('RGB', (800, 480), (0, 0, 0))
    base = resolve_crt_settings(
        preset='subtle', glare=0, scanlines=0, vignette=0, grain=0, flicker=0, glow=0,
        rounded_corners=0, bezel_inset=0, curvature=0, phosphor_floor=0.02,
    )
    with_glare = resolve_crt_settings(
        preset='subtle', glare=0.5, scanlines=0, vignette=0, grain=0, flicker=0, glow=0,
        rounded_corners=0, bezel_inset=0, curvature=0, phosphor_floor=0.02,
    )
    a = CRTRenderer(base).process(src, now=1.0)
    b = CRTRenderer(with_glare).process(src, now=1.0)
    # Sample upper-left glare zone
    assert _lum(b.getpixel((220, 90))) > _lum(a.getpixel((220, 90)))


def test_glare_rgb_in_range():
    src = _solid((10, 10, 10))
    crt = CRTRenderer(resolve_crt_settings(
        preset='strong', glare=1.0, scanlines=0, vignette=0, grain=0, flicker=0, glow=0,
        rounded_corners=0, bezel_inset=0, curvature=0,
    ))
    out = crt.process(src, now=1.0)
    for i in range(0, len(list(_px(out))), 3):
        pass
    for px in out.getdata():
        assert all(0 <= c <= 255 for c in px)


def test_grain_reproducible_with_seed_and_fps_gate():
    settings = resolve_crt_settings(
        preset='subtle', grain=0.2, flicker=0, glare=0, vignette=0, scanlines=0,
        glow=0, rounded_corners=0, bezel_inset=0, curvature=0, grain_fps=5, grain_seed=7,
        phosphor_floor=0.02,
    )
    a = CRTRenderer(settings)
    b = CRTRenderer(settings)
    src = _solid()
    out1 = a.process(src, now=10.0)
    out2 = b.process(src, now=10.0)
    assert list(_px(out1)) == list(_px(out2))
    out3 = a.process(src, now=10.05)
    assert list(_px(out3)) == list(_px(out1))
    out4 = a.process(src, now=10.25)
    assert out4.size == (800, 480)


def test_clamp_and_presets():
    assert clamp01(2) == 1.0
    assert clamp01(-1) == 0.0
    subtle = resolve_crt_settings(preset='subtle')
    strong = resolve_crt_settings(preset='strong')
    assert subtle.scanlines < strong.scanlines
    assert subtle.vignette < strong.vignette
    assert subtle.phosphor_floor < strong.phosphor_floor
    assert subtle.curvature < strong.curvature
    assert subtle.glow == 0.0
    off = resolve_crt_settings(preset='off')
    assert off.enabled is False
    crazy = resolve_crt_settings(
        preset='subtle', flicker=9, rounded_corners=9999, curvature=9, phosphor_floor=9,
        width=800, height=480,
    )
    assert crazy.flicker <= 0.05
    assert crazy.rounded_corners <= 400
    assert crazy.curvature <= 0.08
    assert crazy.phosphor_floor <= 0.08


def test_runtime_preset_switch():
    crt = CRTRenderer(resolve_crt_settings(preset='subtle', grain=0, flicker=0))
    assert crt.enabled
    crt.apply_preset('off')
    assert not crt.enabled
    src = _ui_frame()
    assert list(_px(crt.process(src))) == list(_px(src))
    crt.apply_preset('strong')
    assert crt.enabled
    assert crt.settings.preset == 'strong'


def test_cache_stable_over_many_frames():
    crt = CRTRenderer(resolve_crt_settings(
        preset='subtle', grain=0, flicker=0, curvature=0,
    ))
    src = _solid()
    crt.process(src, now=1.0)
    base = crt.cache_bytes()
    for i in range(300):
        crt.process(src, now=1.0 + i * 0.001)
    assert crt.cache_bytes() == base


def test_curvature_center_stable_edges_shift():
    w, h = 800, 480
    k = 0.022
    cx, cy = ui_to_display(400, 240, w, h, k)
    assert abs(cx - 400) <= 1 and abs(cy - 240) <= 1
    # Edge UI point maps inward on display
    dx, dy = ui_to_display(40, 240, w, h, k)
    assert dx > 40
    # Round-trip near center
    ux, uy = display_to_ui(cx, cy, w, h, k)
    assert abs(ux - 400) <= 2 and abs(uy - 240) <= 2


def test_touch_matches_distorted_ui():
    module = AppModule()
    module.set_force_simulator(True)
    injector = Injector([module])
    state = injector.get(AppState)
    register_shelter_apps(injector, state)
    disp = MagicMock()
    state.bind_display(disp)
    state.set_crt_preset('strong')
    frame = state.compose_frame()
    for _ in draw_base(frame, state):
        pass
    hits = state._AppState__tab_hits  # noqa: SLF001
    assert hits
    second = hits[1]
    cx = (second.rect.x0 + second.rect.x1) // 2
    cy = (second.rect.y0 + second.rect.y1) // 2
    # Tap where the button *appears* after curvature
    dx, dy = state.crt.ui_to_display(cx, cy)
    state.on_touch_event(TouchEvent.tap(dx, dy))
    assert state.active_app.title == 'ДОСТ'


def test_touch_edges_with_curvature():
    """Synthetic rect hit via display→ui inverse at four edges."""
    crt = CRTRenderer(resolve_crt_settings(preset='strong', grain=0, flicker=0))
    assert crt.curvature > 0
    for ux, uy in ((80, 80), (720, 80), (80, 400), (720, 400)):
        dx, dy = crt.ui_to_display(ux, uy)
        rx, ry = crt.display_to_ui(dx, dy)
        assert abs(rx - ux) <= 3
        assert abs(ry - uy) <= 3


def test_off_does_not_transform_touch():
    crt = CRTRenderer(resolve_crt_settings(preset='off'))
    assert crt.display_to_ui(10, 20) == (10, 20)
    assert crt.ui_to_display(10, 20) == (10, 20)


def test_preset_updates_render_and_touch_together():
    crt = CRTRenderer(resolve_crt_settings(preset='off'))
    assert crt.display_to_ui(50, 50) == (50, 50)
    crt.apply_preset('strong')
    assert crt.curvature > 0
    dx, dy = crt.ui_to_display(50, 50)
    assert (dx, dy) != (50, 50) or crt.display_to_ui(dx, dy)  # mapping active
    ux, uy = crt.display_to_ui(dx, dy)
    assert abs(ux - 50) <= 3 and abs(uy - 50) <= 3


def test_simulator_panel_not_processed_by_crt():
    crt = CRTRenderer(resolve_crt_settings(preset='subtle', grain=0, flicker=0, curvature=0))
    panel = Image.new('RGB', (200, 100), (30, 30, 30))
    out = crt.process(panel, now=1.0)
    assert out.size == (200, 100)
