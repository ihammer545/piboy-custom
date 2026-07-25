"""Fullscreen POST / boot splash for shelter terminal startup."""

from __future__ import annotations

import time
from typing import Callable, Sequence

from PIL import Image, ImageDraw, ImageFont

from app.ui_kit import fit_text

# Matches resources/sounds/boot.wav (~7.2 s).
BOOT_DURATION_S = 7.2
BOOT_SKIP_AFTER_S = 1.5

# (appear_at_seconds, line text) — timed to POST beep → floppy seek/read.
DEFAULT_BOOT_LINES: tuple[tuple[float, str], ...] = (
    (0.00, 'УБЕЖИЩЕ-ТЕРМИНАЛ v1.0'),
    (0.15, 'Copyright (C) Vault-Tec Industries'),
    (0.35, ''),
    (0.40, 'POST ................ OK'),
    (1.00, 'ПАМЯТЬ ............. 65536 KB OK'),
    (1.55, 'ДИСКОВОД A: ........ SEEK'),
    (2.40, 'ДИСКОВОД A: ........ READ OK'),
    (3.60, 'ДИСКОВОД B: ........ SEEK'),
    (4.50, 'ДИСКОВОД B: ........ READ OK'),
    (5.80, 'ЗАГРУЗКА ЯДРА ......'),
    (6.50, 'СИСТЕМА УБЕЖИЩА .... ГОТОВА'),
    (7.00, 'НАЖМИТЕ ДЛЯ ВХОДА ИЛИ ОЖИДАЙТЕ...'),
)


class BootSequence:
    """Timed BIOS-style line reveal for the startup splash."""

    def __init__(
        self,
        *,
        lines: Sequence[tuple[float, str]] | None = None,
        duration_s: float = BOOT_DURATION_S,
        skip_after_s: float = BOOT_SKIP_AFTER_S,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.__lines = tuple(lines) if lines is not None else DEFAULT_BOOT_LINES
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
