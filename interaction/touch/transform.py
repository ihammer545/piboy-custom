from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TouchTransform:
    """Maps raw absolute touch coordinates into screen pixels (e.g. 800×480)."""

    screen_width: int = 800
    screen_height: int = 480
    raw_x_min: int = 0
    raw_x_max: int = 4095
    raw_y_min: int = 0
    raw_y_max: int = 4095
    swap_axes: bool = False
    invert_x: bool = False
    invert_y: bool = False
    rotation: int = 0  # 0, 90, 180, 270

    def __post_init__(self):
        if self.rotation % 90 != 0:
            raise ValueError(f'rotation must be multiple of 90, got {self.rotation}')
        object.__setattr__(self, 'rotation', int(self.rotation) % 360)

    def map_point(self, raw_x: int, raw_y: int) -> tuple[int, int]:
        return map_raw_to_screen(
            raw_x, raw_y,
            screen_width=self.screen_width,
            screen_height=self.screen_height,
            raw_x_min=self.raw_x_min,
            raw_x_max=self.raw_x_max,
            raw_y_min=self.raw_y_min,
            raw_y_max=self.raw_y_max,
            swap_axes=self.swap_axes,
            invert_x=self.invert_x,
            invert_y=self.invert_y,
            rotation=self.rotation,
        )


def map_raw_to_screen(
    raw_x: int,
    raw_y: int,
    *,
    screen_width: int = 800,
    screen_height: int = 480,
    raw_x_min: int = 0,
    raw_x_max: int = 4095,
    raw_y_min: int = 0,
    raw_y_max: int = 4095,
    swap_axes: bool = False,
    invert_x: bool = False,
    invert_y: bool = False,
    rotation: int = 0,
) -> tuple[int, int]:
    """
    Convert raw ABS coordinates to clamped screen pixels.

    Order: swap → normalize 0..1 → invert → rotate → scale → clamp.
    """
    if screen_width < 1 or screen_height < 1:
        raise ValueError('screen size must be positive')

    rx, ry = (raw_y, raw_x) if swap_axes else (raw_x, raw_y)
    xmin, xmax = (raw_y_min, raw_y_max) if swap_axes else (raw_x_min, raw_x_max)
    ymin, ymax = (raw_x_min, raw_x_max) if swap_axes else (raw_y_min, raw_y_max)

    nx = _normalize(rx, xmin, xmax)
    ny = _normalize(ry, ymin, ymax)

    if invert_x:
        nx = 1.0 - nx
    if invert_y:
        ny = 1.0 - ny

    rot = int(rotation) % 360
    if rot == 90:
        nx, ny = ny, 1.0 - nx
    elif rot == 180:
        nx, ny = 1.0 - nx, 1.0 - ny
    elif rot == 270:
        nx, ny = 1.0 - ny, nx
    elif rot != 0:
        raise ValueError(f'unsupported rotation {rotation}')

    x = int(round(nx * (screen_width - 1)))
    y = int(round(ny * (screen_height - 1)))
    x = max(0, min(screen_width - 1, x))
    y = max(0, min(screen_height - 1, y))
    return x, y


def _normalize(value: int, src_min: int, src_max: int) -> float:
    if src_max == src_min:
        return 0.0
    ratio = (value - src_min) / float(src_max - src_min)
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio
