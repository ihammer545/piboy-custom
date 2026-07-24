from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw

from app.App import SelfUpdatingApp
from app.ui_kit import fit_text
from core.data import DeviceStatus
from core.decorator import override
from environment import AppConfig
from services.terminal import SensorService


class SensorsApp(SelfUpdatingApp):
    """СРЕДА — environmental sensor readout."""

    @inject
    def __init__(self, draw_callback: Callable[[bool], None], sensors: SensorService,
                 app_config: AppConfig):
        super().__init__(lambda: draw_callback(True))
        self.__sensors = sensors
        self.__app_config = app_config

    @property
    @override
    def title(self) -> str:
        return 'СРЕД'

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

        draw.text((layout.pad, layout.pad), 'СРЕДА — датчики окружающей среды', fill=accent, font=header)

        reading = self.__sensors.reading()
        y = layout.pad + layout.line_height + layout.gap * 2
        status = 'online' if reading.status == DeviceStatus.OPERATIONAL else 'offline'
        draw.text((layout.pad, y), f'Источник: {status}', fill=accent, font=font)
        y += layout.line_height + layout.gap

        if reading.last_update:
            stamp = reading.last_update.strftime('%H:%M:%S')
        else:
            stamp = '—'
        draw.text((layout.pad, y), f'Обновлено: {stamp}', fill=accent, font=font)
        y += layout.line_height + layout.gap * 2

        if reading.data is None:
            draw.text((layout.pad, y), 'Нет данных', fill=accent, font=header)
        else:
            lines = [
                f'Температура: {reading.data.temperature:.1f} °C',
                f'Влажность:   {reading.data.humidity:.0%}',
                f'Давление:    {reading.data.pressure:.1f} hPa',
            ]
            for line in lines:
                draw.text((layout.pad, y), fit_text(font, line, width - 2 * layout.pad), fill=accent, font=header)
                y += layout.line_height + layout.gap

        if reading.warning:
            y += layout.gap
            draw.rectangle((layout.pad, y, width - layout.pad, y + layout.button_min_height),
                           outline=accent, width=2)
            draw.text((layout.pad + 8, y + 10), fit_text(font, reading.warning, width - 2 * layout.pad - 16),
                      fill=accent, font=font)

        yield image, 0, 0
