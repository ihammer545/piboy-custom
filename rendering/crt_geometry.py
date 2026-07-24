"""CRT barrel / pincushion geometry (Pillow-friendly, cached mesh).

Positive ``curvature`` pulls UI edges slightly inward on the display
(convex-glass illusion). Touch uses the same mapping in reverse:

  display tap → display_to_ui → hit-test in logical 800×480
"""

from __future__ import annotations

from array import array
from functools import lru_cache

from PIL import Image


def _norm(x: float, y: float, width: int, height: int) -> tuple[float, float]:
    xn = (x / max(1, width - 1)) * 2.0 - 1.0
    yn = (y / max(1, height - 1)) * 2.0 - 1.0
    return xn, yn


def _denorm(xn: float, yn: float, width: int, height: int) -> tuple[float, float]:
    x = (xn + 1.0) * 0.5 * (width - 1)
    y = (yn + 1.0) * 0.5 * (height - 1)
    return x, y


def display_to_ui(x: float, y: float, width: int, height: int, curvature: float) -> tuple[int, int]:
    """Map a displayed pixel to logical UI coordinates (inverse sample)."""
    if abs(curvature) < 1e-9:
        return int(round(x)), int(round(y))
    xn, yn = _norm(x, y, width, height)
    r2 = xn * xn + yn * yn
    f = 1.0 + curvature * r2
    sx, sy = xn * f, yn * f
    # Outside the warped glass → clamp (bezel / void)
    sx = max(-1.0, min(1.0, sx))
    sy = max(-1.0, min(1.0, sy))
    ux, uy = _denorm(sx, sy, width, height)
    return int(round(ux)), int(round(uy))


def ui_to_display(x: float, y: float, width: int, height: int, curvature: float) -> tuple[int, int]:
    """Map logical UI coordinates to where they appear on the display."""
    if abs(curvature) < 1e-9:
        return int(round(x)), int(round(y))
    xn, yn = _norm(x, y, width, height)
    xd, yd = xn, yn
    for _ in range(8):
        r2 = xd * xd + yd * yd
        f = 1.0 + curvature * r2
        if f == 0:
            break
        xd = xn / f
        yd = yn / f
    dx, dy = _denorm(xd, yd, width, height)
    dx = max(0, min(width - 1, dx))
    dy = max(0, min(height - 1, dy))
    return int(round(dx)), int(round(dy))


def build_barrel_mesh(
    width: int,
    height: int,
    curvature: float,
    cell: int = 20,
) -> list[tuple[tuple[int, int, int, int], tuple[float, ...]]]:
    """Pillow MESH data: dest box ← source quad (UL, LL, LR, UR)."""
    if abs(curvature) < 1e-9:
        return []
    mesh: list[tuple[tuple[int, int, int, int], tuple[float, ...]]] = []
    for y0 in range(0, height, cell):
        y1 = min(y0 + cell, height)
        for x0 in range(0, width, cell):
            x1 = min(x0 + cell, width)
            # Dest rectangle corners → sample source via display_to_ui
            ul = display_to_ui(x0, y0, width, height, curvature)
            ur = display_to_ui(x1, y0, width, height, curvature)
            lr = display_to_ui(x1, y1, width, height, curvature)
            ll = display_to_ui(x0, y1, width, height, curvature)
            quad = (
                float(ul[0]), float(ul[1]),
                float(ll[0]), float(ll[1]),
                float(lr[0]), float(lr[1]),
                float(ur[0]), float(ur[1]),
            )
            mesh.append(((x0, y0, x1, y1), quad))
    return mesh


def apply_barrel(
    image: Image.Image,
    curvature: float,
    mesh: list | None = None,
    fill=(0, 0, 0),
) -> Image.Image:
    """Warp ``image`` with cached mesh. Empty areas become ``fill``."""
    if abs(curvature) < 1e-9:
        return image
    w, h = image.size
    data = mesh if mesh is not None else build_barrel_mesh(w, h, curvature)
    if not data:
        return image
    # Start from fill so out-of-range samples read as bezel black via clamp,
    # but uncovered dest (if any) stays black.
    base = Image.new('RGB', (w, h), fill)
    base.paste(image)
    return base.transform(
        (w, h),
        Image.Transform.MESH,
        data,
        resample=Image.Resampling.BILINEAR,
    )


@lru_cache(maxsize=8)
def cached_mesh_bytes(width: int, height: int, curvature_key: int, cell: int = 16) -> bytes:
    """Serialize mesh for size accounting (curvature quantized ×1e6)."""
    k = curvature_key / 1_000_000.0
    mesh = build_barrel_mesh(width, height, k, cell=cell)
    # Rough: 4 ints box + 8 floats quad per cell
    buf = array('d')
    for box, quad in mesh:
        buf.extend(box)
        buf.extend(quad)
    return buf.tobytes()
