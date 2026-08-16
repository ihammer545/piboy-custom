"""Tests for GPU CRT uniforms and curvature identity (no GLES required)."""

from __future__ import annotations

from rendering.crt import resolve_crt_settings
from rendering.crt_geometry import display_to_ui, ui_to_display
from rendering.crt_uniforms import crt_settings_to_uniforms


def test_uniforms_off_disables_effects():
    s = resolve_crt_settings(preset='off', width=800, height=480)
    u = crt_settings_to_uniforms(s, time_s=1.5)
    assert u['u_enabled'] == 0.0
    assert u['u_curvature'] == 0.0
    assert u['u_scanlines'] == 0.0
    assert u['u_time'] == 1.5
    assert u['u_resolution'] == (800.0, 480.0)


def test_uniforms_subtle_exports_curvature():
    s = resolve_crt_settings(preset='subtle', width=800, height=480)
    u = crt_settings_to_uniforms(s)
    assert u['u_enabled'] == 1.0
    assert u['u_curvature'] == s.curvature
    assert u['u_scanlines'] == s.scanlines
    assert u['u_grain_seed'] == float(s.grain_seed)


def _shader_forward_sample(dx: float, dy: float, w: int, h: int, k: float) -> tuple[float, float]:
    """Mirror crt.frag barrel sample (display pixel → UI continuous coords)."""
    xn = (dx / max(1, w - 1)) * 2.0 - 1.0
    yn = (dy / max(1, h - 1)) * 2.0 - 1.0
    r2 = xn * xn + yn * yn
    f = 1.0 + k * r2
    sx, sy = xn * f, yn * f
    sx = max(-1.0, min(1.0, sx))
    sy = max(-1.0, min(1.0, sy))
    ux = (sx + 1.0) * 0.5 * (w - 1)
    uy = (sy + 1.0) * 0.5 * (h - 1)
    return ux, uy


def test_shader_forward_matches_display_to_ui():
    w, h, k = 800, 480, 0.009
    for dx, dy in ((0, 0), (400, 240), (799, 479), (50, 400), (750, 40)):
        ux, uy = display_to_ui(dx, dy, w, h, k)
        sx, sy = _shader_forward_sample(float(dx), float(dy), w, h, k)
        assert abs(sx - ux) <= 1.0
        assert abs(sy - uy) <= 1.0


def test_ui_to_display_roundtrip_center():
    w, h, k = 800, 480, 0.009
    for ux, uy in ((400, 240), (200, 120), (600, 360)):
        dx, dy = ui_to_display(ux, uy, w, h, k)
        back = display_to_ui(dx, dy, w, h, k)
        assert abs(back[0] - ux) <= 2
        assert abs(back[1] - uy) <= 2
