from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw

from app.App import SelfUpdatingApp
from app.ui_kit import fit_text
from core.decorator import override
from environment import AppConfig
from services.event_log import EventLogService


class EventLogApp(SelfUpdatingApp):
    """ЖУРНАЛ — in-memory event list for current run."""

    @inject
    def __init__(self, draw_callback: Callable[[bool], None], event_log: EventLogService,
                 app_config: AppConfig):
        super().__init__(lambda: draw_callback(True))
        self.__event_log = event_log
        self.__app_config = app_config
        self.__offset = 0

    @property
    @override
    def title(self) -> str:
        return 'ЛОГ'

    @property
    @override
    def refresh_time(self) -> float:
        return 0.5

    @override
    def draw(self, image: Image.Image, partial=False) -> Generator[tuple[Image.Image, int, int], Any, None]:
        draw = ImageDraw.Draw(image)
        cfg = self.__app_config
        layout = cfg.layout
        width, height = cfg.app_size
        font = cfg.font_standard
        header = cfg.font_header
        accent, dark = cfg.accent, cfg.accent_dark

        draw.text((layout.pad, layout.pad), 'ЖУРНАЛ — события сессии', fill=accent, font=header)
        subtitle = f'лимит {self.__event_log.max_events} · без секретов и кодов'
        draw.text((layout.pad, layout.pad + layout.line_height), subtitle, fill=accent, font=font)

        events = self.__event_log.list_events()
        y = layout.pad + layout.line_height * 2 + layout.gap
        row_h = layout.list_row_height - 4
        max_rows = max(1, (height - y - layout.pad) // row_h)
        if self.__offset > max(0, len(events) - max_rows):
            self.__offset = max(0, len(events) - max_rows)

        visible = events[self.__offset:self.__offset + max_rows]
        if not visible:
            draw.text((layout.pad, y), 'Событий пока нет', fill=accent, font=font)
        for event in visible:
            stamp = event.timestamp.strftime('%H:%M:%S')
            line = fit_text(font, f'{stamp}  [{event.category}]  {event.message}', width - 2 * layout.pad)
            draw.rectangle((layout.pad, y, width - layout.pad, y + row_h - 2), outline=dark)
            draw.text((layout.pad + 4, y + 6), line, fill=accent, font=font)
            y += row_h

        yield image, 0, 0

    @override
    def on_key_up(self):
        self.__offset = max(0, self.__offset - 1)

    @override
    def on_key_down(self):
        self.__offset += 1

    @override
    def on_key_a(self):
        pass

    @override
    def on_key_b(self):
        self.__offset = 0
