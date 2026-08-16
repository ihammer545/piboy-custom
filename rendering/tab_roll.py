"""Tab-switch CRT V-hold / vertical desync (old TV roll), ~1–2 seconds."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageChops


@dataclass(frozen=True)
class TabRollParams:
    offset_frac: float
    ghost: float
    done: bool


def compute_tab_roll(elapsed_s: float, *, duration_s: float = 1.4,
                     max_offset_frac: float = 0.28) -> TabRollParams:
    """
    Map elapsed time → vertical wrap offset (fraction of height) + ghost blend.

    Starts with a strong rolling/overlapping image and settles to stable.
    """
    duration_s = max(0.2, float(duration_s))
    t = max(0.0, min(1.0, elapsed_s / duration_s))
    if t >= 1.0:
        return TabRollParams(0.0, 0.0, True)

    # Amplitude decays (ease-out); wobble mimics adjusting V-hold.
    amp = (1.0 - t) ** 1.65
    phase = elapsed_s * (2.6 + 9.0 * amp) * math.pi
    offset_frac = amp * max_offset_frac * (0.55 + 0.45 * math.sin(phase))
    ghost = 0.52 * amp
    return TabRollParams(offset_frac, ghost, False)


def apply_tab_roll(image: Image.Image, *, offset_frac: float, ghost: float = 0.0) -> Image.Image:
    """
    Vertical wrap (ImageChops.offset) + optional semi-transparent second copy.

    Mimics old CRT vertical hold slip: picture slides and overlays itself.
    """
    if image.mode != 'RGB':
        image = image.convert('RGB')
    h = image.height
    if h <= 1:
        return image
    offset = int(round(offset_frac * h)) % h
    if offset == 0 and ghost <= 0.001:
        return image

    primary = ImageChops.offset(image, 0, offset)
    if ghost <= 0.001:
        return primary

    # Half-offset ghost → double image / tear look (Pip-Boy reference).
    ghost_off = (offset // 2) if offset else max(1, h // 24)
    secondary = ImageChops.offset(image, 0, ghost_off)
    blend = max(0.0, min(0.55, float(ghost)))
    return Image.blend(primary, secondary, blend)
