"""CRT post-processing for the shelter terminal (Pillow-only).

Pipeline (logical):
  UI frame
  → phosphor black level
  → optional glow
  → barrel distortion
  → scanlines
  → signed grain
  → vignette
  → glass glare (screen)
  → rounded glass mask / bezel
  → output

Effects are designed to remain visible on near-black phosphor, not only on
bright green UI chrome. Geometry warp is optional (``curvature``); touch must
use ``display_to_ui`` so hitboxes match the warped image.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, replace
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from rendering.crt_geometry import (
    apply_barrel,
    build_barrel_mesh,
    display_to_ui as geom_display_to_ui,
    ui_to_display as geom_ui_to_display,
)

PRESET_OFF = 'off'
PRESET_SUBTLE = 'subtle'
PRESET_STRONG = 'strong'

_PRESET_VALUES: dict[str, dict[str, Any]] = {
    PRESET_OFF: {
        'enabled': False,
        'phosphor_floor': 0.0,
        'scanlines': 0.0,
        'vignette': 0.0,
        'grain': 0.0,
        'glare': 0.0,
        'flicker': 0.0,
        'glow': 0.0,
        'rounded_corners': 0,
        'bezel_inset': 0,
        'curvature': 0.0,
        'grain_fps': 5.0,
    },
    PRESET_SUBTLE: {
        'enabled': True,
        'phosphor_floor': 0.018,
        'scanlines': 0.16,
        'vignette': 0.42,
        'grain': 0.045,
        'glare': 0.14,
        # Temporarily 0 — diagnose black-frame flashes vs intentional CRT flicker.
        'flicker': 0.0,
        'glow': 0.0,
        'rounded_corners': 24,
        'bezel_inset': 8,
        'curvature': 0.009,
        'grain_fps': 5.0,
    },
    PRESET_STRONG: {
        'enabled': True,
        'phosphor_floor': 0.028,
        'scanlines': 0.30,
        'vignette': 0.62,
        'grain': 0.08,
        'glare': 0.26,
        # Temporarily 0 — diagnose black-frame flashes vs intentional CRT flicker.
        'flicker': 0.0,
        'glow': 0.06,
        'rounded_corners': 38,
        'bezel_inset': 10,
        'curvature': 0.022,
        'grain_fps': 6.0,
    },
}


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def clamp_range(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


@dataclass
class CrtSettings:
    """Resolved CRT parameters after preset + overrides + clamping."""

    enabled: bool = True
    preset: str = PRESET_SUBTLE
    phosphor_floor: float = 0.018
    scanlines: float = 0.16
    vignette: float = 0.42
    grain: float = 0.045
    glare: float = 0.14
    flicker: float = 0.004
    glow: float = 0.0
    rounded_corners: int = 24
    bezel_inset: int = 8
    curvature: float = 0.009
    grain_fps: float = 5.0
    grain_seed: int = 42
    width: int = 800
    height: int = 480

    def fingerprint(self) -> tuple:
        return (
            self.enabled, self.preset, self.phosphor_floor, self.scanlines, self.vignette,
            self.grain, self.glare, self.flicker, self.glow, self.rounded_corners,
            self.bezel_inset, self.curvature, self.grain_fps, self.grain_seed,
            self.width, self.height,
        )


def resolve_crt_settings(
    *,
    preset: str = PRESET_SUBTLE,
    enabled: bool | None = None,
    phosphor_floor: float | None = None,
    scanlines: float | None = None,
    vignette: float | None = None,
    grain: float | None = None,
    glare: float | None = None,
    flicker: float | None = None,
    glow: float | None = None,
    rounded_corners: int | None = None,
    bezel_inset: int | None = None,
    curvature: float | None = None,
    grain_fps: float | None = None,
    grain_seed: int = 42,
    width: int = 800,
    height: int = 480,
) -> CrtSettings:
    name = (preset or PRESET_SUBTLE).lower().strip()
    if name not in _PRESET_VALUES:
        name = PRESET_SUBTLE
    base = dict(_PRESET_VALUES[name])
    overrides = {
        'enabled': enabled,
        'phosphor_floor': phosphor_floor,
        'scanlines': scanlines,
        'vignette': vignette,
        'grain': grain,
        'glare': glare,
        'flicker': flicker,
        'glow': glow,
        'rounded_corners': rounded_corners,
        'bezel_inset': bezel_inset,
        'curvature': curvature,
        'grain_fps': grain_fps,
    }
    for key, value in overrides.items():
        if value is not None:
            base[key] = value

    max_r = max(0, min(width, height) // 2)
    settings = CrtSettings(
        enabled=bool(base['enabled']) and name != PRESET_OFF,
        preset=name if name != PRESET_OFF or enabled is not False else PRESET_OFF,
        phosphor_floor=clamp_range(base['phosphor_floor'], 0.0, 0.08),
        scanlines=clamp01(base['scanlines']),
        vignette=clamp01(base['vignette']),
        grain=clamp01(base['grain']),
        glare=clamp01(base['glare']),
        flicker=clamp_range(base['flicker'], 0.0, 0.05),
        glow=clamp01(base['glow']),
        rounded_corners=int(clamp_range(base['rounded_corners'], 0, max_r)),
        bezel_inset=int(clamp_range(base['bezel_inset'], 0, 24)),
        curvature=clamp_range(base['curvature'], 0.0, 0.08),
        grain_fps=clamp_range(base['grain_fps'], 0.5, 30.0),
        grain_seed=int(grain_seed),
        width=max(1, int(width)),
        height=max(1, int(height)),
    )
    if name == PRESET_OFF:
        settings.enabled = False
        settings.preset = PRESET_OFF
    return settings


def phosphor_rgb(floor: float) -> tuple[int, int, int]:
    """Very dark green-black phosphor lift. floor≈0.015 → ~(0,4,1)."""
    floor = clamp_range(floor, 0.0, 0.08)
    r = int(round(255 * floor * 0.20))
    g = int(round(255 * floor * 0.95))
    b = int(round(255 * floor * 0.35))
    return r, g, b


class CRTRenderer:
    """
    Applies procedural CRT overlays to a composed UI frame.

    Static layers + barrel mesh are cached; grain refreshes at grain_fps.
    """

    def __init__(self, settings: CrtSettings | None = None):
        self.__settings = settings or resolve_crt_settings()
        self.__cache_key: tuple | None = None
        self.__scanlines: Image.Image | None = None
        self.__vignette: Image.Image | None = None
        self.__glare: Image.Image | None = None
        self.__glass_mask: Image.Image | None = None
        self.__rim: Image.Image | None = None
        self.__phosphor: Image.Image | None = None
        self.__grain_full: Image.Image | None = None
        self.__barrel_mesh: list | None = None
        self.__last_grain_ts = 0.0
        self.__frame_count = 0
        self.__now_fn = time.monotonic

    @property
    def settings(self) -> CrtSettings:
        return self.__settings

    @property
    def enabled(self) -> bool:
        return self.__settings.enabled

    @property
    def curvature(self) -> float:
        return self.__settings.curvature if self.__settings.enabled else 0.0

    def set_settings(self, settings: CrtSettings) -> None:
        self.__settings = settings
        self.__invalidate()

    def apply_preset(self, preset: str, **overrides) -> CrtSettings:
        settings = resolve_crt_settings(
            preset=preset,
            width=self.__settings.width,
            height=self.__settings.height,
            grain_seed=self.__settings.grain_seed,
            **overrides,
        )
        self.set_settings(settings)
        return settings

    def set_resolution(self, width: int, height: int) -> None:
        if width == self.__settings.width and height == self.__settings.height:
            return
        self.__settings = replace(self.__settings, width=width, height=height)
        self.__invalidate()

    def display_to_ui(self, x: int, y: int) -> tuple[int, int]:
        """Map display-space touch to logical UI coordinates."""
        s = self.__settings
        if not s.enabled or s.curvature <= 0:
            return x, y
        return geom_display_to_ui(x, y, s.width, s.height, s.curvature)

    def ui_to_display(self, x: int, y: int) -> tuple[int, int]:
        s = self.__settings
        if not s.enabled or s.curvature <= 0:
            return x, y
        return geom_ui_to_display(x, y, s.width, s.height, s.curvature)

    def cache_bytes(self) -> int:
        total = 0
        for img in (self.__scanlines, self.__vignette, self.__glare, self.__glass_mask,
                    self.__rim, self.__phosphor, self.__grain_full):
            if img is not None:
                total += img.width * img.height * len(img.getbands())
        if self.__barrel_mesh:
            # box(4 int) + quad(8 float) ≈ 4*4 + 8*8 = 80 bytes/cell
            total += len(self.__barrel_mesh) * 80
        return total

    def process(self, frame: Image.Image, *, now: float | None = None,
                ui_changed: bool = True) -> Image.Image:
        """Return a processed RGB copy. Never mutates ``frame``."""
        self.__frame_count += 1
        width, height = frame.size
        if (width, height) != (self.__settings.width, self.__settings.height):
            self.set_resolution(width, height)

        if not self.__settings.enabled:
            return frame.copy()

        self.__ensure_static_layers()
        out = frame.convert('RGB').copy()
        ts = self.__now_fn() if now is None else now
        s = self.__settings

        # 1) Phosphor floor — raise pure black so overlays are visible
        if self.__phosphor is not None and s.phosphor_floor > 0:
            out = ImageChops.lighter(out, self.__phosphor)

        # 2) Optional glow (cheap BoxBlur), only when UI changed
        if s.glow > 0 and ui_changed:
            out = self.__apply_glow(out)

        # 3) Barrel distortion (cached mesh)
        if s.curvature > 0 and self.__barrel_mesh is not None:
            out = apply_barrel(out, s.curvature, mesh=self.__barrel_mesh, fill=(0, 0, 0))

        # 4) Scanlines — modulate brightness on phosphor (visible on dark)
        if self.__scanlines is not None and s.scanlines > 0:
            out = ImageChops.multiply(out, self.__scanlines)

        # 5) Signed grain across full glass
        if s.grain > 0:
            out = self.__apply_grain(out, ts)

        # 6) Vignette
        if self.__vignette is not None and s.vignette > 0:
            out = Image.composite(out, Image.new('RGB', out.size, (0, 0, 0)), self.__vignette)

        # 7) Glass glare — screen blend (visible on dark phosphor)
        if self.__glare is not None and s.glare > 0:
            out = ImageChops.screen(out, self.__glare)

        if s.flicker > 0:
            phase = math.sin(ts * 2.2) * 0.5 + math.sin(ts * 5.1) * 0.5
            factor = clamp_range(1.0 + phase * s.flicker, 0.94, 1.06)
            out = ImageEnhance.Brightness(out).enhance(factor)

        # 8) Rounded glass + outer bezel (absolute black outside)
        if self.__glass_mask is not None:
            black = Image.new('RGB', out.size, (0, 0, 0))
            out = Image.composite(out, black, self.__glass_mask)
            if self.__rim is not None:
                out = ImageChops.screen(out, self.__rim)

        return out

    def __invalidate(self) -> None:
        self.__scanlines = None
        self.__vignette = None
        self.__glare = None
        self.__glass_mask = None
        self.__rim = None
        self.__phosphor = None
        self.__grain_full = None
        self.__barrel_mesh = None
        self.__cache_key = None
        self.__last_grain_ts = 0.0

    def __ensure_static_layers(self) -> None:
        key = self.__settings.fingerprint()
        if key == self.__cache_key and self.__phosphor is not None:
            return
        s = self.__settings
        w, h = s.width, s.height
        self.__phosphor = Image.new('RGB', (w, h), phosphor_rgb(s.phosphor_floor))
        self.__scanlines = self.__build_scanlines(w, h, s.scanlines)
        self.__vignette = self.__build_vignette(w, h, s.vignette, s.preset)
        self.__glare = self.__build_glare(w, h, s.glare)
        self.__glass_mask, self.__rim = self.__build_glass(w, h, s.rounded_corners, s.bezel_inset, s.glare)
        self.__barrel_mesh = (
            build_barrel_mesh(w, h, s.curvature) if s.curvature > 0 else None
        )
        self.__grain_full = None
        self.__cache_key = key
        self.__last_grain_ts = 0.0

    @staticmethod
    def __build_scanlines(width: int, height: int, strength: float) -> Image.Image:
        """RGB multiply layer: even rows slightly darker, odd slightly brighter."""
        layer = Image.new('RGB', (width, height))
        px = layer.load()
        # Keep mid near 1.0 so multiply doesn't crush phosphor; delta ∝ strength
        dark = int(round(255 * (1.0 - strength * 0.45)))
        bright = int(round(255 * min(1.0, 1.0 + strength * 0.08)))
        dark = max(1, min(255, dark))
        bright = max(1, min(255, bright))
        for y in range(height):
            v = dark if (y % 2 == 0) else bright
            # slight green bias so lines read as phosphor modulation
            row = (max(1, v - 1), v, max(1, v - 1))
            for x in range(width):
                px[x, y] = row
        return layer

    @staticmethod
    def __build_vignette(width: int, height: int, strength: float, preset: str) -> Image.Image:
        """L mask: 255 keeps pixel. Falloff starts near the outer rim."""
        mask = Image.new('L', (width, height), 255)
        px = mask.load()
        cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
        # subtle: last ~10%; strong: last ~18%
        start = 0.88 if preset == PRESET_STRONG else 0.90
        if strength >= 0.55:
            start = 0.80
        elif strength >= 0.35:
            start = 0.88
        else:
            start = 0.90
        for y in range(height):
            ny = (y - cy) / cy if cy else 0.0
            for x in range(width):
                nx = (x - cx) / cx if cx else 0.0
                # elliptical radius + stronger corners
                r = math.sqrt(nx * nx * 0.92 + ny * ny)
                edge = max(abs(nx), abs(ny))
                t = max(0.0, (r - start) / max(1e-6, 1.0 - start))
                t2 = max(0.0, (edge - (start - 0.02)) / max(1e-6, 1.0 - (start - 0.02)))
                t = clamp01(max(t, t2 * 0.85))
                t = t * t * (3 - 2 * t)
                keep = 1.0 - strength * t
                px[x, y] = int(round(255 * keep))
        return mask

    @staticmethod
    def __build_glare(width: int, height: int, strength: float) -> Image.Image:
        """Soft green-gray highlight for ImageChops.screen on dark phosphor."""
        layer = Image.new('RGB', (width, height), (0, 0, 0))
        if strength <= 0:
            return layer
        px = layer.load()
        # Diagonal soft blob centered in upper-left quadrant
        cx, cy = width * 0.28, height * 0.18
        rx, ry = width * 0.55, height * 0.42
        peak = 40.0 + 90.0 * strength
        for y in range(height):
            ny = (y - cy) / ry
            for x in range(int(width * 0.85)):
                nx = (x - cx) / rx
                # Diagonal stretch
                d = math.sqrt((nx * 0.85 + ny * 0.25) ** 2 + (nx * -0.2 + ny) ** 2)
                if d >= 1.0:
                    continue
                t = 1.0 - d
                t = t * t * (3 - 2 * t)
                v = peak * t * t
                r = int(min(255, v * 0.50))
                g = int(min(255, v * 0.78))
                b = int(min(255, v * 0.55))
                px[x, y] = (r, g, b)
        return layer

    @staticmethod
    def __build_glass(
        width: int,
        height: int,
        radius: int,
        inset: int,
        glare: float,
    ) -> tuple[Image.Image, Image.Image | None]:
        """Glass mask (L) and optional soft inner rim (RGB for screen)."""
        inset = max(0, int(inset))
        radius = max(0, int(radius))
        mask = Image.new('L', (width, height), 0)
        draw = ImageDraw.Draw(mask)
        if inset >= min(width, height) // 2:
            return mask, None
        box = (inset, inset, width - 1 - inset, height - 1 - inset)
        if radius <= 0:
            draw.rectangle(box, fill=255)
        else:
            draw.rounded_rectangle(box, radius=radius, fill=255)

        rim: Image.Image | None = None
        if inset > 0 or radius > 0:
            rim = Image.new('RGB', (width, height), (0, 0, 0))
            rd = ImageDraw.Draw(rim)
            edge = max(1, inset // 3)
            inner = (
                inset + edge,
                inset + edge,
                width - 1 - inset - edge,
                height - 1 - inset - edge,
            )
            glow = int(18 + 22 * glare)
            if inner[2] > inner[0] and inner[3] > inner[1]:
                rr = max(0, radius - edge)
                if rr > 0:
                    rd.rounded_rectangle(inner, radius=rr, outline=(glow // 2, glow, glow // 2), width=1)
                else:
                    rd.rectangle(inner, outline=(glow // 2, glow, glow // 2), width=1)
        return mask, rim

    def __apply_grain(self, image: Image.Image, now: float) -> Image.Image:
        noise = self.__grain_layer(now)
        # Signed add: noise centered at 128, amplitude ∝ grain
        amp = max(1, int(round(self.__settings.grain * 28)))
        # Scale deviation from mid-gray
        # ImageChops.add(a, b, scale, offset) => (a+b)/scale + offset
        # Want: a + (b-128)*(amp/128) ≈ add with scaled noise
        # Approximate with low-opacity blend against greenish noise around phosphor
        # Use add with offset trick:
        scaled = noise.point(lambda p: 128 + int((p - 128) * amp / 128))
        return ImageChops.add(image, scaled, scale=1.0, offset=-128)

    def __grain_layer(self, now: float) -> Image.Image:
        interval = 1.0 / self.__settings.grain_fps
        need_refresh = self.__grain_full is None or (now - self.__last_grain_ts) >= interval
        if need_refresh:
            bucket = int(now * self.__settings.grain_fps)
            rng = random.Random(self.__settings.grain_seed + bucket)
            # Non-divisor tile size + bicubic upscale → no obvious square tiling
            tw, th = 97, 61
            tile = Image.new('L', (tw, th))
            px = tile.load()
            for y in range(th):
                for x in range(tw):
                    px[x, y] = rng.randint(0, 255)
            w, h = self.__settings.width, self.__settings.height
            full_l = tile.resize((w, h), Image.Resampling.BICUBIC)
            # Mild green bias so grain reads as phosphor noise
            self.__grain_full = Image.merge('RGB', (
                full_l.point(lambda p: int(p * 0.85 + 19)),
                full_l,
                full_l.point(lambda p: int(p * 0.90 + 12)),
            ))
            self.__last_grain_ts = now
        assert self.__grain_full is not None
        return self.__grain_full

    def __apply_glow(self, image: Image.Image) -> Image.Image:
        strength = self.__settings.glow
        if strength <= 0:
            return image
        glow = image.filter(ImageFilter.BoxBlur(1))
        return Image.blend(image, glow, strength * 0.35)
