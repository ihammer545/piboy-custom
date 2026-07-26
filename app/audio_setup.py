"""First-run UI sound device confirmation overlay."""

from __future__ import annotations

from typing import Callable, Sequence

from PIL import Image, ImageDraw, ImageFont

from app.ui_kit import draw_button, fit_text, make_hit
from backend.ui_sound_device import AudioDeviceInfo
from interaction.touch.events import HitTarget, Rect, hit_test


class AudioSetupSession:
    """
    Fullscreen «слышно?» wizard after boot splash.

    Actions: hear (persist), next (cycle device), skip (mark done, keep auto).
    """

    def __init__(
        self,
        devices: Sequence[AudioDeviceInfo],
        *,
        start_index: int | None = None,
    ):
        self.__devices = list(devices)
        self.__cursor = 0
        if start_index is not None and self.__devices:
            for i, d in enumerate(self.__devices):
                if d.index == int(start_index):
                    self.__cursor = i
                    break
        self.__hits: list[HitTarget] = []
        self.__done = False
        self.__result: str | None = None  # hear | skip | None

    @property
    def done(self) -> bool:
        return self.__done

    @property
    def result(self) -> str | None:
        return self.__result

    @property
    def devices(self) -> list[AudioDeviceInfo]:
        return list(self.__devices)

    @property
    def current(self) -> AudioDeviceInfo | None:
        if not self.__devices:
            return None
        return self.__devices[self.__cursor % len(self.__devices)]

    def next_device(self) -> AudioDeviceInfo | None:
        if not self.__devices:
            return None
        self.__cursor = (self.__cursor + 1) % len(self.__devices)
        return self.current

    def mark_hear(self) -> None:
        self.__result = 'hear'
        self.__done = True

    def mark_skip(self) -> None:
        self.__result = 'skip'
        self.__done = True

    def render(
        self,
        image: Image.Image,
        *,
        accent: tuple[int, int, int],
        accent_dark: tuple[int, int, int],
        font: ImageFont.FreeTypeFont,
        header: ImageFont.FreeTypeFont,
        background: tuple[int, int, int] = (0, 0, 0),
    ) -> Image.Image:
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, image.width, image.height), fill=background)
        pad = 36
        draw.text((pad, pad), 'ПРОВЕРКА ЗВУКА', fill=accent, font=header)
        y = pad + 40
        lines = [
            'Слышите короткий сигнал?',
            'Если нет — нажмите СЛЕДУЮЩЕЕ.',
            '',
        ]
        cur = self.current
        if cur is None:
            lines.append('Устройства вывода не найдены.')
        else:
            lines.append(f'Устройство [{self.__cursor + 1}/{len(self.__devices)}]:')
            lines.append(fit_text(font, f'{cur.index}: {cur.name}', image.width - 2 * pad))
            lines.append(fit_text(font, f'host={cur.host_api}', image.width - 2 * pad))
        for line in lines:
            draw.text((pad, y), line, fill=accent, font=font)
            y += 28

        btn_y = image.height - 100
        width = image.width
        gap = 16
        btn_w = (width - 2 * pad - 2 * gap) // 3
        buttons = [
            ('hear', 'СЛЫШУ', pad),
            ('next', 'СЛЕДУЮЩЕЕ', pad + btn_w + gap),
            ('skip', 'ПРОПУСТИТЬ', pad + 2 * (btn_w + gap)),
        ]
        self.__hits = []
        for action, label, x0 in buttons:
            rect = Rect(x0, btn_y, x0 + btn_w - 1, btn_y + 52)
            draw_button(
                draw, rect, label, font, accent, accent_dark,
                background=background,
            )
            self.__hits.append(make_hit(rect, action, min_w=44, min_h=44))
        return image

    def handle_tap(self, x: int, y: int) -> str | None:
        """Return action hear|next|skip or None."""
        hit = hit_test(self.__hits, x, y)
        return hit.action if hit else None

    def handle_key_left(self) -> str:
        return 'next'

    def handle_key_right(self) -> str:
        return 'hear'

    def handle_key_a(self) -> str:
        return 'hear'

    def handle_key_b(self) -> str:
        return 'skip'
