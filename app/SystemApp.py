from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw

from app.App import SelfUpdatingApp
from app.ui_kit import draw_button, fit_text, make_hit
from core.decorator import override
from environment import AppConfig, Environment, save_ui_sound_local
import environment
from interaction.touch.events import HitTarget, Rect, hit_test
from services.terminal import SystemService
from services.ui_sound import UiSoundService


class SystemApp(SelfUpdatingApp):
    """СЕРВ — status + UI sound device picker."""

    @inject
    def __init__(self, draw_callback: Callable[[bool], None], system: SystemService,
                 app_config: AppConfig, environment: Environment, sounds: UiSoundService):
        super().__init__(lambda: draw_callback(True))
        self.__system = system
        self.__app_config = app_config
        self.__environment = environment
        self.__sounds = sounds
        self.__devices = []
        self.__cursor = 0
        self.__hits: list[HitTarget] = []
        self.__status_msg = ''
        self.__refresh_devices()

    def __refresh_devices(self) -> None:
        try:
            self.__devices = self.__sounds.list_output_devices()
        except Exception:  # noqa: BLE001
            self.__devices = []
        cur = self.__sounds.current_device_index()
        self.__cursor = 0
        if cur is not None:
            for i, d in enumerate(self.__devices):
                if d.index == cur:
                    self.__cursor = i
                    break

    @property
    @override
    def title(self) -> str:
        return 'СЕРВ'

    @property
    @override
    def refresh_time(self) -> float:
        return 1.0

    @override
    def draw(self, image: Image.Image, partial=False) -> Generator[tuple[Image.Image, int, int], Any, None]:
        draw = ImageDraw.Draw(image)
        cfg = self.__app_config
        layout = cfg.layout
        width, height = cfg.app_size
        font = cfg.font_standard
        header = cfg.font_header
        accent = cfg.accent
        accent_dark = cfg.accent_dark
        bg = cfg.background
        pad = layout.pad

        draw.text((pad, pad), 'СЕРВИС — состояние терминала', fill=accent, font=header)

        status = self.__system.status()
        uptime = int(status.uptime_seconds)
        hours, rem = divmod(uptime, 3600)
        minutes, seconds = divmod(rem, 60)
        lines = [
            f'Backend: {status.backend}',
            f'Разрешение: {status.resolution[0]}×{status.resolution[1]}',
            f'Ввод: {self.__environment.input.mode}',
            f'CRT: {self.__environment.crt.preset}',
            f'Время работы: {hours:02d}:{minutes:02d}:{seconds:02d}',
            f'Версия: {status.version}',
        ]
        y = pad + layout.line_height + layout.gap * 2
        for line in lines:
            draw.text((pad, y), fit_text(font, line, width - 2 * pad), fill=accent, font=font)
            y += layout.line_height + 2

        y += layout.gap
        draw.text((pad, y), 'ЗВУК UI', fill=accent, font=header)
        y += layout.line_height + 4
        src = environment.RUNTIME.ui_sound_device_source
        draw.text(
            (pad, y),
            fit_text(font, f'Сейчас: {self.__sounds.describe_output()}', width - 2 * pad),
            fill=accent, font=font,
        )
        y += layout.line_height + 2
        draw.text((pad, y), fit_text(font, f'Источник: {src}', width - 2 * pad), fill=accent, font=font)
        y += layout.line_height + 4

        # Device list (up to 5 visible around cursor)
        if not self.__devices:
            draw.text((pad, y), 'Нет устройств вывода', fill=accent, font=font)
            y += layout.line_height + 8
        else:
            start = max(0, self.__cursor - 2)
            end = min(len(self.__devices), start + 5)
            for i in range(start, end):
                d = self.__devices[i]
                mark = '>' if i == self.__cursor else ' '
                label = f'{mark} {d.index}: {d.name}'
                draw.text((pad, y), fit_text(font, label, width - 2 * pad), fill=accent, font=font)
                y += layout.line_height + 2
            y += 6

        if self.__status_msg:
            draw.text((pad, y), fit_text(font, self.__status_msg, width - 2 * pad), fill=accent, font=font)
            y += layout.line_height + 6

        btn_h = 44
        btn_y = height - btn_h - pad
        gap = 10
        btn_w = (width - 2 * pad - 3 * gap) // 4

        # List area cycles selection (under buttons so buttons win hit-test).
        self.__hits = []
        self.__hits.append(make_hit(
            Rect(pad, pad + 120, width - pad, max(pad + 121, btn_y - 8)),
            'next',
            enabled=True,
        ))

        labels = [
            ('prev', '◀'),
            ('test', 'ТЕСТ'),
            ('select', 'ВЫБРАТЬ'),
            ('auto', 'АВТО'),
        ]
        x = pad
        for action, label in labels:
            rect = Rect(x, btn_y, x + btn_w - 1, btn_y + btn_h - 1)
            draw_button(draw, rect, label, font, accent, accent_dark, background=bg)
            self.__hits.append(make_hit(rect, action))
            x += btn_w + gap

        yield image, 0, 0

    def __apply_current(self, *, auto: bool = False) -> None:
        if auto:
            self.__refresh_devices()
            if not self.__devices:
                self.__status_msg = 'Авто: устройств нет'
                return
            self.__cursor = 0
            d = self.__devices[0]
            self.__sounds.rebind_output(d.index, selection_source='config')
            save_ui_sound_local(index=d.index, name=d.name, setup_done=True, env=self.__environment)
            self.__status_msg = f'Авто → {d.index}'
            self.__sounds.test_confirm()
            return
        if not self.__devices:
            self.__status_msg = 'Нечего выбрать'
            return
        d = self.__devices[self.__cursor % len(self.__devices)]
        self.__sounds.rebind_output(d.index, selection_source='config')
        save_ui_sound_local(index=d.index, name=d.name, setup_done=True, env=self.__environment)
        self.__status_msg = f'Выбрано {d.index}'
        self.__sounds.test_confirm()

    @override
    def on_tap(self, x: int, y: int) -> bool:
        hit = hit_test(self.__hits, x, y)
        if hit is None:
            return False
        action = hit.action
        if action == 'prev':
            if self.__devices:
                self.__cursor = (self.__cursor - 1) % len(self.__devices)
            self.__status_msg = ''
            return True
        if action == 'next':
            if self.__devices:
                self.__cursor = (self.__cursor + 1) % len(self.__devices)
            self.__status_msg = ''
            return True
        if action == 'test':
            if self.__devices:
                d = self.__devices[self.__cursor % len(self.__devices)]
                if self.__sounds.current_device_index() != d.index:
                    self.__sounds.rebind_output(d.index, selection_source='config')
            self.__sounds.test_confirm()
            self.__status_msg = 'Тест…'
            return True
        if action == 'select':
            self.__apply_current(auto=False)
            return True
        if action == 'auto':
            self.__apply_current(auto=True)
            return True
        return False

    @override
    def on_key_left(self):
        if self.__devices:
            self.__cursor = (self.__cursor - 1) % len(self.__devices)

    @override
    def on_key_right(self):
        if self.__devices:
            self.__cursor = (self.__cursor + 1) % len(self.__devices)

    @override
    def on_key_a(self):
        self.__apply_current(auto=False)

    @override
    def on_key_b(self):
        self.__sounds.test_confirm()
        self.__status_msg = 'Тест…'

    @override
    def on_app_enter(self):
        super().on_app_enter()
        self.__refresh_devices()
