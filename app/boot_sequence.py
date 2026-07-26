"""Fullscreen POST / boot splash for shelter terminal startup."""

from __future__ import annotations

import time
from typing import Callable, Sequence

from PIL import Image, ImageDraw, ImageFont

from app.ui_kit import fit_text

# One second between each POST line; hold fully drawn screen before leaving splash.
BOOT_LINE_INTERVAL_S = 1.0
BOOT_HOLD_AFTER_S = 4.0
BOOT_SKIP_AFTER_S = 1.5

# Line texts in order (timing is derived: 0, 1, 2, … seconds).
_BOOT_LINE_TEXTS: tuple[str, ...] = (
    'УБЕЖИЩЕ-ТЕРМИНАЛ v1.0',
    'Copyright (C) Vault-Tec Industries',
    '',
    'POST ................ OK',
    'ПАМЯТЬ ............. 65536 KB OK',
    'ДИСКОВОД A: ........ SEEK',
    'ДИСКОВОД A: ........ READ OK',
    'ДИСКОВОД B: ........ SEEK',
    'ДИСКОВОД B: ........ READ OK',
    'ЗАГРУЗКА ЯДРА ......',
    'СИСТЕМА УБЕЖИЩА .... ГОТОВА',
    'НАЖМИТЕ ДЛЯ ВХОДА ИЛИ ОЖИДАЙТЕ...',
)


def _spaced_lines(
    texts: Sequence[str] = _BOOT_LINE_TEXTS,
    interval_s: float = BOOT_LINE_INTERVAL_S,
) -> tuple[tuple[float, str], ...]:
    return tuple((i * interval_s, text) for i, text in enumerate(texts))


DEFAULT_BOOT_LINES: tuple[tuple[float, str], ...] = _spaced_lines()

# Last line at (n-1)*interval, then hold BOOT_HOLD_AFTER_S before is_done.
BOOT_DURATION_S = (
    max(0, len(_BOOT_LINE_TEXTS) - 1) * BOOT_LINE_INTERVAL_S + BOOT_HOLD_AFTER_S
)


class BootSequence:
    """Timed BIOS-style line reveal for the startup splash."""

    def __init__(
        self,
        *,
        lines: Sequence[tuple[float, str]] | None = None,
        duration_s: float | None = None,
        skip_after_s: float = BOOT_SKIP_AFTER_S,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.__lines = tuple(lines) if lines is not None else DEFAULT_BOOT_LINES
        if duration_s is None:
            if self.__lines:
                last_t = max(t for t, _ in self.__lines)
                duration_s = last_t + BOOT_HOLD_AFTER_S
            else:
                duration_s = BOOT_HOLD_AFTER_S
        self.__duration_s = max(0.1, float(duration_s))
        self.__skip_after_s = max(0.0, float(skip_after_s))
        self.__clock = clock
        self.__t0 = clock()
        self.__skipped = False

    @property
    def duration_s(self) -> float:
        return self.__duration_s

    @property
    def skipped(self) -> bool:
        return self.__skipped

    def elapsed(self) -> float:
        return max(0.0, self.__clock() - self.__t0)

    def can_skip(self) -> bool:
        return self.elapsed() >= self.__skip_after_s

    def skip(self) -> bool:
        """Request early exit after skip_after. Returns True if accepted."""
        if not self.can_skip():
            return False
        self.__skipped = True
        return True

    def is_done(self) -> bool:
        return self.__skipped or self.elapsed() >= self.__duration_s

    def visible_lines(self) -> list[str]:
        t = self.elapsed()
        return [text for appear, text in self.__lines if appear <= t]

    def render(
        self,
        image: Image.Image,
        *,
        accent: tuple[int, int, int],
        font: ImageFont.FreeTypeFont,
        background: tuple[int, int, int] = (0, 0, 0),
    ) -> Image.Image:
        """Draw splash into ``image`` (fullscreen, no chrome)."""
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, image.width, image.height), fill=background)
        lines = self.visible_lines()
        pad_x = 36
        pad_y = 40
        line_h = max(18, (font.getbbox('Ay')[3] - font.getbbox('Ay')[1]) + 6)
        max_w = image.width - 2 * pad_x
        y = pad_y
        for i, text in enumerate(lines):
            if not text:
                y += line_h // 2
                continue
            shown = fit_text(font, text, max_w)
            if i == len(lines) - 1 and not self.is_done():
                # Blinking block cursor on the newest line.
                if int(self.elapsed() * 2) % 2 == 0:
                    shown = shown + '_'
            draw.text((pad_x, y), shown, fill=accent, font=font)
            y += line_h
            if y > image.height - pad_y:
                break
        hint = 'ТАЧ / КЛАВИША — ПРОПУСК' if self.can_skip() else ''
        if hint:
            hw = font.getbbox(hint)[2]
            draw.text(
                ((image.width - hw) // 2, image.height - pad_y - line_h),
                hint,
                fill=accent,
                font=font,
            )
        return image
