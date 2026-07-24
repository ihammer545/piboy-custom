from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw

from app.App import SelfUpdatingApp
from app.ui_kit import fit_text, make_hit
from core.data import DeviceStatus
from core.decorator import override
from environment import AppConfig
from interaction.touch.events import HitTarget, Rect, hit_test
from services.terminal import SensorService


class SensorsApp(SelfUpdatingApp):
    """СРЕДА — environmental sensor readout."""

    @inject
    def __init__(self, draw_callback: Callable[[bool], None], sensors: SensorService,
                 app_config: AppConfig):
        super().__init__(lambda: draw_callback(True))
        self.__sensors = sensors
        self.__app_config = app_config
        self.__selected_metric: str | None = None
        self.__hits: list[HitTarget] = []

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
        accent, dark = cfg.accent, cfg.accent_dark
        self.__hits = []

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
            metrics = [
                ('temp', f'Температура: {reading.data.temperature:.1f} °C'),
                ('humidity', f'Влажность:   {reading.data.humidity:.0%}'),
                ('pressure', f'Давление:    {reading.data.pressure:.1f} hPa'),
            ]
            row_h = max(layout.line_height + layout.gap, layout.button_min_height)
            for key, line in metrics:
                box = Rect(layout.pad, y, width - layout.pad, y + row_h - 1)
                if self.__selected_metric == key:
                    draw.rectangle(box.as_tuple(), fill=dark)
                draw.text((layout.pad + 6, y + (row_h - layout.line_height) // 2),
                          fit_text(header, line, width - 2 * layout.pad - 8), fill=accent, font=header)
                self.__hits.append(make_hit(box, f'metric:{key}',
                                            min_w=layout.button_min_width, min_h=layout.button_min_height))
                y += row_h + 4

        if reading.warning:
            y += layout.gap
            draw.rectangle((layout.pad, y, width - layout.pad, y + layout.button_min_height),
                           outline=accent, width=2)
            draw.text((layout.pad + 8, y + 10), fit_text(font, reading.warning, width - 2 * layout.pad - 16),
                      fill=accent, font=font)

        yield image, 0, 0

    @override
    def on_tap(self, x: int, y: int) -> bool:
        target = hit_test(self.__hits, x, y)
        if target is None or not target.action.startswith('metric:'):
            return False
        self.__selected_metric = target.action.split(':', 1)[1]
        return True
