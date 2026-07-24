from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw

from app.App import SelfUpdatingApp
from app.ui_kit import button_row, draw_button, fit_text, make_hit
from core.decorator import override
from environment import AppConfig
from interaction.touch.events import HitTarget, hit_test
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
        self.__hits: list[HitTarget] = []
        self.__pressed: str | None = None
        self.__max_rows = 1

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
        accent, dark, bg = cfg.accent, cfg.accent_dark, cfg.background
        self.__hits = []

        draw.text((layout.pad, layout.pad), 'ЖУРНАЛ — события сессии', fill=accent, font=header)
        subtitle = f'лимит {self.__event_log.max_events} · без секретов и кодов'
        draw.text((layout.pad, layout.pad + layout.line_height), subtitle, fill=accent, font=font)

        btn_y = height - layout.button_min_height - layout.pad
        buttons = button_row(width, btn_y, ['▲ Вверх', '▼ Вниз'], layout.button_min_width,
                             layout.button_min_height, layout.gap, layout.pad)
        for (label, box), action in zip(buttons, ('scroll_up', 'scroll_down')):
            draw_button(draw, box, label, font, accent, dark, background=bg,
                        pressed=self.__pressed == action)
            self.__hits.append(make_hit(box, action,
                                        min_w=layout.button_min_width, min_h=layout.button_min_height))

        events = self.__event_log.list_events()
        y = layout.pad + layout.line_height * 2 + layout.gap
        row_h = layout.list_row_height - 4
        self.__max_rows = max(1, (btn_y - layout.gap - y) // row_h)
        if self.__offset > max(0, len(events) - self.__max_rows):
            self.__offset = max(0, len(events) - self.__max_rows)

        visible = events[self.__offset:self.__offset + self.__max_rows]
        if not visible:
            draw.text((layout.pad, y), 'Событий пока нет', fill=accent, font=font)
        for event in visible:
            stamp = event.timestamp.strftime('%H:%M:%S')
            line = fit_text(font, f'{stamp}  [{event.category}]  {event.message}', width - 2 * layout.pad)
            draw.rectangle((layout.pad, y, width - layout.pad, y + row_h - 2), outline=dark)
            draw.text((layout.pad + 4, y + 6), line, fill=accent, font=font)
            y += row_h

        self.__pressed = None
        yield image, 0, 0

    def __scroll_up(self):
        self.__offset = max(0, self.__offset - 1)

    def __scroll_down(self):
        self.__offset += 1

    @override
    def on_tap(self, x: int, y: int) -> bool:
        target = hit_test(self.__hits, x, y)
        if target is None:
            return False
        self.__pressed = target.action
        if target.action == 'scroll_up':
            self.__scroll_up()
            return True
        if target.action == 'scroll_down':
            self.__scroll_down()
            return True
        return False

    @override
    def on_key_up(self):
        self.__scroll_up()

    @override
    def on_key_down(self):
        self.__scroll_down()

    @override
    def on_key_a(self):
        pass

    @override
    def on_key_b(self):
        self.__offset = 0
