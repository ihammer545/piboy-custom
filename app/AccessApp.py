from enum import Enum
from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw

from app.App import SelfUpdatingApp
from app.ui_kit import button_row, draw_button
from core.decorator import override
from environment import AppConfig
from ports.lock import AccessOutcome, LockState
from services.terminal import AccessService


class AccessUiState(Enum):
    IDLE = 'ожидание'
    CHECKING = 'проверка'
    GRANTED = 'доступ разрешён'
    DENIED = 'отказ'


class AccessApp(SelfUpdatingApp):
    """ДОСТУП — code entry and simulated lock pulse."""

    @inject
    def __init__(self, draw_callback: Callable[[bool], None], access: AccessService,
                 app_config: AppConfig):
        super().__init__(lambda: draw_callback(True))
        self.__access = access
        self.__app_config = app_config
        self.__digits = ''
        self.__mask_char = '●'
        self.__ui_state = AccessUiState.IDLE
        self.__message = 'Введите код'
        self.__scenario = ''
        self.__focus = 0  # keypad index or action
        self.__keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'Сброс', '0', 'OK']

    @property
    @override
    def title(self) -> str:
        return 'ДОСТ'

    @property
    @override
    def refresh_time(self) -> float:
        return 0.25

    @override
    def draw(self, image: Image.Image, partial=False) -> Generator[tuple[Image.Image, int, int], Any, None]:
        draw = ImageDraw.Draw(image)
        cfg = self.__app_config
        layout = cfg.layout
        width, height = cfg.app_size
        font = cfg.font_standard
        header = cfg.font_header
        accent, dark, bg = cfg.accent, cfg.accent_dark, cfg.background

        draw.text((layout.pad, layout.pad), 'ДОСТУП — электронный замок', fill=accent, font=header)

        masked = self.__mask_char * len(self.__digits) if self.__digits else '—'
        draw.text((layout.pad, layout.pad + layout.line_height + layout.gap),
                  f'Код: {masked}', fill=accent, font=header)

        lock_state = self.__access.lock_state()
        lock_label = 'ИМПУЛЬС' if lock_state == LockState.PULSING else 'ЗАКРЫТ'
        pulse_box = (width - 180, layout.pad, width - layout.pad, layout.pad + layout.button_min_height)
        draw_button(draw, pulse_box, lock_label, font, accent, dark,
                    focused=lock_state == LockState.PULSING, background=bg)

        y = layout.pad + layout.line_height * 3
        draw.text((layout.pad, y), f'Статус: {self.__ui_state.value}', fill=accent, font=font)
        y += layout.line_height
        draw.text((layout.pad, y), self.__message, fill=accent, font=font)
        if self.__scenario:
            y += layout.line_height
            draw.text((layout.pad, y), f'Сценарий: {self.__scenario}', fill=accent, font=font)

        # 3x4 keypad with large hit targets
        grid_top = height - 4 * (layout.button_min_height + layout.gap) - layout.pad
        cols = 3
        btn_w = (width - 2 * layout.pad - (cols - 1) * layout.gap) // cols
        btn_h = layout.button_min_height
        for i, key in enumerate(self.__keys):
            row, col = divmod(i, cols)
            x0 = layout.pad + col * (btn_w + layout.gap)
            y0 = grid_top + row * (btn_h + layout.gap)
            box = (x0, y0, x0 + btn_w - 1, y0 + btn_h - 1)
            draw_button(draw, box, key, font, accent, dark, focused=self.__focus == i, background=bg)

        yield image, 0, 0

    def __press(self, key: str):
        if key == 'Сброс':
            self.__digits = ''
            self.__ui_state = AccessUiState.IDLE
            self.__message = 'Введите код'
            self.__scenario = ''
            return
        if key == 'OK':
            self.__submit()
            return
        if len(self.__digits) < 8:
            self.__digits += key
            self.__ui_state = AccessUiState.IDLE
            self.__message = 'Введите код'

    def __submit(self):
        self.__ui_state = AccessUiState.CHECKING
        self.__message = 'Проверка...'
        # Digits never go to the event log — AccessService/port handles that.
        result, _pulse = self.__access.submit_code(self.__digits)
        self.__digits = ''
        if result.outcome == AccessOutcome.DENIED:
            self.__ui_state = AccessUiState.DENIED
            self.__message = result.message
            self.__scenario = result.scenario
        else:
            self.__ui_state = AccessUiState.GRANTED
            self.__message = result.message
            self.__scenario = result.scenario

    @override
    def on_key_left(self):
        self.__focus = (self.__focus - 1) % len(self.__keys)

    @override
    def on_key_right(self):
        self.__focus = (self.__focus + 1) % len(self.__keys)

    @override
    def on_key_up(self):
        self.__focus = (self.__focus - 3) % len(self.__keys)

    @override
    def on_key_down(self):
        self.__focus = (self.__focus + 3) % len(self.__keys)

    @override
    def on_key_a(self):
        self.__press(self.__keys[self.__focus])

    @override
    def on_key_b(self):
        self.__press('Сброс')
