"""CRT post-processing for the shelter terminal (Pillow-only, no geometry warp)."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, replace
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


PRESET_OFF = 'off'
PRESET_SUBTLE = 'subtle'
PRESET_STRONG = 'strong'

_PRESET_VALUES: dict[str, dict[str, Any]] = {
    PRESET_OFF: {
        'enabled': False,
        'scanlines': 0.0,
        'vignette': 0.0,
        'grain': 0.0,
        'glare': 0.0,
        'flicker': 0.0,
        'glow': 0.0,
        'rounded_corners': 0,
        'grain_fps': 5.0,
    },
    PRESET_SUBTLE: {
        'enabled': True,
        'scanlines': 0.10,
        'vignette': 0.20,
        'grain': 0.025,
        'glare': 0.08,
        'flicker': 0.006,
        'glow': 0.0,
        'rounded_corners': 24,
        'grain_fps': 5.0,
    },
    PRESET_STRONG: {
        'enabled': True,
        'scanlines': 0.22,
        'vignette': 0.38,
        'grain': 0.06,
        'glare': 0.14,
        'flicker': 0.018,
        'glow': 0.08,
        'rounded_corners': 32,
        'grain_fps': 8.0,
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
    scanlines: float = 0.10
    vignette: float = 0.20
    grain: float = 0.025
    glare: float = 0.08
    flicker: float = 0.006
    glow: float = 0.0
    rounded_corners: int = 24
    grain_fps: float = 5.0
    grain_seed: int = 42
    width: int = 800
    height: int = 480

    def fingerprint(self) -> tuple:
        return (
            self.enabled, self.preset, self.scanlines, self.vignette, self.grain,
            self.glare, self.flicker, self.glow, self.rounded_corners, self.grain_fps,
            self.grain_seed, self.width, self.height,
        )


def resolve_crt_settings(
    *,
    preset: str = PRESET_SUBTLE,
    enabled: bool | None = None,
    scanlines: float | None = None,
    vignette: float | None = None,
    grain: float | None = None,
    glare: float | None = None,
    flicker: float | None = None,
    glow: float | None = None,
    rounded_corners: int | None = None,
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
        'scanlines': scanlines,
        'vignette': vignette,
        'grain': grain,
        'glare': glare,
        'flicker': flicker,
        'glow': glow,
        'rounded_corners': rounded_corners,
        'grain_fps': grain_fps,
    }
    for key, value in overrides.items():
        if value is not None:
            base[key] = value

    settings = CrtSettings(
        enabled=bool(base['enabled']) and name != PRESET_OFF,
        preset=name if name != PRESET_OFF or enabled is not False else PRESET_OFF,
        scanlines=clamp01(base['scanlines']),
        vignette=clamp01(base['vignette']),
        grain=clamp01(base['grain']),
        glare=clamp01(base['glare']),
        flicker=clamp_range(base['flicker'], 0.0, 0.05),
        glow=clamp01(base['glow']),
        rounded_corners=int(clamp_range(base['rounded_corners'], 0, min(width, height) // 2)),
        grain_fps=clamp_range(base['grain_fps'], 0.5, 30.0),
        grain_seed=int(grain_seed),
        width=max(1, int(width)),
        height=max(1, int(height)),
    )
    if name == PRESET_OFF:
        settings.enabled = False
        settings.preset = PRESET_OFF
    return settings


class CRTRenderer:
    """
    Applies procedural CRT overlays to a composed UI frame.

    Does NOT warp geometry — touch hitboxes stay aligned with logical pixels.
    Static layers are cached; grain refreshes at grain_fps; no unbounded history.
    """

    def __init__(self, settings: CrtSettings | None = None):
        self.__settings = settings or resolve_crt_settings()
        self.__cache_key: tuple | None = None
        self.__scanlines: Image.Image | None = None
        self.__vignette: Image.Image | None = None
        self.__glare: Image.Image | None = None
        self.__corner_mask: Image.Image | None = None
        self.__grain_tile: Image.Image | None = None
        self.__grain_full: Image.Image | None = None
        self.__last_grain_ts = 0.0
        self.__rng = random.Random(self.__settings.grain_seed)
        self.__frame_count = 0
        self.__now_fn = time.monotonic

    @property
    def settings(self) -> CrtSettings:
        return self.__settings

    @property
    def enabled(self) -> bool:
        return self.__settings.enabled

    def set_settings(self, settings: CrtSettings) -> None:
        self.__settings = settings
        self.__rng = random.Random(settings.grain_seed)
        self.__invalidate(force=True)

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
        self.__invalidate(force=True)

    def cache_bytes(self) -> int:
        total = 0
        for img in (self.__scanlines, self.__vignette, self.__glare, self.__corner_mask,
                    self.__grain_tile, self.__grain_full):
            if img is not None:
                total += img.width * img.height * len(img.getbands())
        return total

    def process(self, frame: Image.Image, *, now: float | None = None,
                ui_changed: bool = True) -> Image.Image:
        """
        Return a processed RGB copy. Never mutates `frame`.
        When disabled / off: returns a pixel-identical copy.
        """
        self.__frame_count += 1
        width, height = frame.size
        if (width, height) != (self.__settings.width, self.__settings.height):
            self.set_resolution(width, height)

        if not self.__settings.enabled:
            return frame.copy()

        self.__ensure_static_layers()
        out = frame.convert('RGB').copy()
        ts = self.__now_fn() if now is None else now

        if self.__settings.glow > 0 and ui_changed:
            out = self.__apply_glow(out)

        if self.__scanlines is not None and self.__settings.scanlines > 0:
            out = Image.alpha_composite(out.convert('RGBA'), self.__scanlines).convert('RGB')

        if self.__vignette is not None and self.__settings.vignette > 0:
            out = Image.composite(out, Image.new('RGB', out.size, (0, 0, 0)), self.__vignette)

        if self.__glare is not None and self.__settings.glare > 0:
            out = Image.alpha_composite(out.convert('RGBA'), self.__glare).convert('RGB')

        if self.__settings.grain > 0:
            grain = self.__grain_layer(ts)
            out = Image.blend(out, grain, min(1.0, self.__settings.grain * 0.85))

        if self.__settings.flicker > 0:
            phase = math.sin(ts * 2.2) * 0.5 + math.sin(ts * 5.1) * 0.5
            factor = 1.0 + phase * self.__settings.flicker
            factor = clamp_range(factor, 0.92, 1.08)
            out = ImageEnhance.Brightness(out).enhance(factor)

        if self.__corner_mask is not None and self.__settings.rounded_corners > 0:
            black = Image.new('RGB', out.size, (0, 0, 0))
            out = Image.composite(out, black, self.__corner_mask)

        return out

    def __invalidate(self, force: bool = False) -> None:
        self.__scanlines = None
        self.__vignette = None
        self.__glare = None
        self.__corner_mask = None
        self.__grain_tile = None
        self.__grain_full = None
        self.__cache_key = None
        self.__last_grain_ts = 0.0

    def __ensure_static_layers(self) -> None:
        key = self.__settings.fingerprint()
        if key == self.__cache_key and self.__scanlines is not None:
            return
        w, h = self.__settings.width, self.__settings.height
        self.__scanlines = self.__build_scanlines(w, h, self.__settings.scanlines)
        self.__vignette = self.__build_vignette(w, h, self.__settings.vignette)
        self.__glare = self.__build_glare(w, h, self.__settings.glare)
        self.__corner_mask = self.__build_corner_mask(w, h, self.__settings.rounded_corners)
        self.__grain_tile = self.__build_grain_tile(64, 64)
        self.__grain_full = None
        self.__cache_key = key
        self.__last_grain_ts = 0.0

    @staticmethod
    def __build_scanlines(width: int, height: int, strength: float) -> Image.Image:
        layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        alpha = int(round(255 * strength * 0.55))
        for y in range(0, height, 3):
            draw.line((0, y, width, y), fill=(0, 0, 0, alpha))
        return layer

    @staticmethod
    def __build_vignette(width: int, height: int, strength: float) -> Image.Image:
        """L mask: 255 keeps pixel, 0 fully darkened. Corners darker than mid-edges."""
        mask = Image.new('L', (width, height), 255)
        px = mask.load()
        cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
        for y in range(height):
            ny = (y - cy) / cy if cy else 0.0
            for x in range(width):
                nx = (x - cx) / cx if cx else 0.0
                r = math.sqrt(nx * nx * 0.85 + ny * ny)
                edge = max(abs(nx), abs(ny))
                t = max(0.0, (r - 0.35) / 0.75)
                t = t * 0.7 + max(0.0, (edge - 0.55) / 0.45) * 0.3
                t = clamp01(t)
                t = t * t * (3 - 2 * t)
                keep = 1.0 - strength * t
                px[x, y] = int(round(255 * keep))
        return mask

    @staticmethod
    def __build_glare(width: int, height: int, strength: float) -> Image.Image:
        layer = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        max_alpha = int(round(40 * strength))
        for i in range(12, 0, -1):
            frac = i / 12.0
            alpha = int(max_alpha * frac * frac)
            pad_x = int(width * 0.08 * (1 - frac))
            pad_y = int(height * 0.05 * (1 - frac))
            box = (
                int(width * 0.05) + pad_x,
                int(height * 0.02) + pad_y,
                int(width * 0.62) - pad_x,
                int(height * 0.42) - pad_y,
            )
            if box[2] > box[0] and box[3] > box[1]:
                draw.ellipse(box, fill=(180, 255, 190, alpha))
        return layer

    @staticmethod
    def __build_corner_mask(width: int, height: int, radius: int) -> Image.Image:
        if radius <= 0:
            return Image.new('L', (width, height), 255)
        mask = Image.new('L', (width, height), 0)
        draw = ImageDraw.Draw(mask)
        inset = max(2, radius // 8)
        draw.rounded_rectangle(
            (inset, inset, width - 1 - inset, height - 1 - inset),
            radius=radius,
            fill=255,
        )
        return mask

    def __build_grain_tile(self, tw: int, th: int) -> Image.Image:
        tile = Image.new('RGB', (tw, th))
        px = tile.load()
        rng = random.Random(self.__settings.grain_seed)
        for y in range(th):
            for x in range(tw):
                v = rng.randint(0, 255)
                px[x, y] = (v, v, v)
        return tile

    def __grain_layer(self, now: float) -> Image.Image:
        interval = 1.0 / self.__settings.grain_fps
        need_refresh = self.__grain_full is None or (now - self.__last_grain_ts) >= interval
        if need_refresh:
            bucket = int(now * self.__settings.grain_fps)
            rng = random.Random(self.__settings.grain_seed + bucket)
            tw, th = 64, 64
            tile = Image.new('RGB', (tw, th))
            px = tile.load()
            for y in range(th):
                for x in range(tw):
                    v = rng.randint(0, 255)
                    px[x, y] = (v, v, v)
            w, h = self.__settings.width, self.__settings.height
            self.__grain_full = tile.resize((w, h), Image.Resampling.NEAREST)
            self.__last_grain_ts = now
        assert self.__grain_full is not None
        return self.__grain_full

    def __apply_glow(self, image: Image.Image) -> Image.Image:
        strength = self.__settings.glow
        if strength <= 0:
            return image
        glow = image.filter(ImageFilter.BoxBlur(1))
        return Image.blend(image, glow, strength * 0.35)
