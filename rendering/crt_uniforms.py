"""Map CrtSettings → GLES CRT shader uniforms (no GPU required)."""

from __future__ import annotations

from typing import Any

from rendering.crt import CrtSettings


def crt_settings_to_uniforms(settings: CrtSettings, *, time_s: float = 0.0) -> dict[str, Any]:
    """Return a flat dict of uniform names → Python values for crt.frag."""
    enabled = 1.0 if settings.enabled else 0.0
    return {
        'u_enabled': enabled,
        'u_resolution': (float(settings.width), float(settings.height)),
        'u_time': float(time_s),
        'u_phosphor_floor': float(settings.phosphor_floor) if settings.enabled else 0.0,
        'u_scanlines': float(settings.scanlines) if settings.enabled else 0.0,
        'u_vignette': float(settings.vignette) if settings.enabled else 0.0,
        'u_grain': float(settings.grain) if settings.enabled else 0.0,
        'u_glare': float(settings.glare) if settings.enabled else 0.0,
        'u_flicker': float(settings.flicker) if settings.enabled else 0.0,
        'u_glow': float(settings.glow) if settings.enabled else 0.0,
        'u_curvature': float(settings.curvature) if settings.enabled else 0.0,
        'u_rounded_corners': float(settings.rounded_corners) if settings.enabled else 0.0,
        'u_bezel_inset': float(settings.bezel_inset) if settings.enabled else 0.0,
        'u_grain_seed': float(settings.grain_seed),
    }
