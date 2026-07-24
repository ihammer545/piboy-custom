from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw

from app.App import SelfUpdatingApp
from app.ui_kit import fit_text
from core.decorator import override
from environment import AppConfig
from services.terminal import SystemService


class SystemApp(SelfUpdatingApp):
    """СЕРВИС — safe status screen (no destructive git/power actions)."""

    @inject
    def __init__(self, draw_callback: Callable[[bool], None], system: SystemService,
                 app_config: AppConfig):
        super().__init__(lambda: draw_callback(True))
        self.__system = system
        self.__app_config = app_config

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
        width, _height = cfg.app_size
        font = cfg.font_standard
        header = cfg.font_header
        accent = cfg.accent

        draw.text((layout.pad, layout.pad), 'СЕРВИС — состояние терминала', fill=accent, font=header)

        status = self.__system.status()
        uptime = int(status.uptime_seconds)
        hours, rem = divmod(uptime, 3600)
        minutes, seconds = divmod(rem, 60)
        lines = [
            f'Backend: {status.backend}',
            f'Разрешение: {status.resolution[0]}×{status.resolution[1]}',
            f'Интерфейс: активен',
            f'Сеть (симулятор): {status.network.value}',
            f'Аудио (симулятор): {status.audio.value}',
            f'Время работы: {hours:02d}:{minutes:02d}:{seconds:02d}',
            f'Версия / commit: {status.version}',
            '',
            'Опасные операции обновления и питания',
            'на этом экране отключены.',
        ]
        y = layout.pad + layout.line_height + layout.gap * 2
        for line in lines:
            draw.text((layout.pad, y), fit_text(font, line, width - 2 * layout.pad), fill=accent, font=font)
            y += layout.line_height + 4

        yield image, 0, 0
