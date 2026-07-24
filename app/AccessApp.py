from enum import Enum
from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw

from app.App import SelfUpdatingApp
from app.ui_kit import draw_button, make_hit
from core.decorator import override
from environment import AppConfig
from interaction.touch.events import HitTarget, Rect, hit_test
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
        self.__focus = 0
        # Digit pad + backspace + OK; clear via Сброс / Esc
        self.__keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '⌫', '0', 'OK']
        self.__hits: list[HitTarget] = []
        self.__pressed_key: str | None = None

    @property
    @override
    def title(self) -> str:
        return 'ДОСТ'

    @property
    @override
    def refresh_time(self) -> float:
        return 0.25

    def __clear_code(self):
        self.__digits = ''
        self.__ui_state = AccessUiState.IDLE
        self.__message = 'Введите код'
        self.__scenario = ''

    def __press(self, key: str):
        if key in ('Сброс', 'clear'):
            self.__clear_code()
            return
        if key in ('⌫', 'backspace'):
            self.__digits = self.__digits[:-1]
            self.__ui_state = AccessUiState.IDLE
            self.__message = 'Введите код'
            return
        if key == 'OK':
            self.__submit()
            return
        if key.isdigit() and len(self.__digits) < 8:
            self.__digits += key
            self.__ui_state = AccessUiState.IDLE
            self.__message = 'Введите код'

    def __submit(self):
        self.__ui_state = AccessUiState.CHECKING
        self.__message = 'Проверка...'
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
    def draw(self, image: Image.Image, partial=False) -> Generator[tuple[Image.Image, int, int], Any, None]:
        draw = ImageDraw.Draw(image)
        cfg = self.__app_config
        layout = cfg.layout
        width, height = cfg.app_size
        font = cfg.font_standard
        header = cfg.font_header
        accent, dark, bg = cfg.accent, cfg.accent_dark, cfg.background
        self.__hits = []

        draw.text((layout.pad, layout.pad), 'ДОСТУП — электронный замок', fill=accent, font=header)

        masked = self.__mask_char * len(self.__digits) if self.__digits else '—'
        draw.text((layout.pad, layout.pad + layout.line_height + layout.gap),
                  f'Код: {masked}', fill=accent, font=header)

        lock_state = self.__access.lock_state()
        lock_label = 'ИМПУЛЬС' if lock_state == LockState.PULSING else 'ЗАКРЫТ'
        pulse_box = Rect(width - 180, layout.pad, width - layout.pad, layout.pad + layout.button_min_height)
        draw_button(draw, pulse_box, lock_label, font, accent, dark,
                    focused=lock_state == LockState.PULSING, background=bg, disabled=True)

        y = layout.pad + layout.line_height * 3
        draw.text((layout.pad, y), f'Статус: {self.__ui_state.value}', fill=accent, font=font)
        y += layout.line_height
        draw.text((layout.pad, y), self.__message, fill=accent, font=font)
        if self.__scenario:
            y += layout.line_height
            draw.text((layout.pad, y), f'Сценарий: {self.__scenario}', fill=accent, font=font)

        clear_h = layout.button_min_height
        clear_y = height - 5 * (layout.button_min_height + layout.gap) - layout.pad
        clear_rect = Rect(layout.pad, clear_y, width - layout.pad, clear_y + clear_h - 1)
        draw_button(draw, clear_rect, 'Сброс', font, accent, dark,
                    focused=False, background=bg, pressed=self.__pressed_key == 'Сброс')
        self.__hits.append(make_hit(clear_rect, 'Сброс',
                                    min_w=layout.button_min_width, min_h=layout.button_min_height))

        grid_top = clear_y + clear_h + layout.gap
        cols = 3
        btn_w = (width - 2 * layout.pad - (cols - 1) * layout.gap) // cols
        btn_h = layout.button_min_height
        for i, key in enumerate(self.__keys):
            row, col = divmod(i, cols)
            x0 = layout.pad + col * (btn_w + layout.gap)
            y0 = grid_top + row * (btn_h + layout.gap)
            box = Rect(x0, y0, x0 + btn_w - 1, y0 + btn_h - 1)
            draw_button(draw, box, key, font, accent, dark, focused=self.__focus == i, background=bg,
                        pressed=self.__pressed_key == key)
            self.__hits.append(make_hit(box, key, min_w=layout.button_min_width, min_h=layout.button_min_height))

        self.__pressed_key = None
        yield image, 0, 0

    @override
    def on_tap(self, x: int, y: int) -> bool:
        target = hit_test(self.__hits, x, y)
        if target is None:
            return False
        self.__pressed_key = target.action
        if target.action in self.__keys:
            self.__focus = self.__keys.index(target.action)
        self.__press(target.action)
        return True

    @override
    def on_digit(self, digit: str) -> bool:
        if digit.isdigit():
            self.__press(digit)
            return True
        return False

    @override
    def on_backspace(self) -> bool:
        self.__press('⌫')
        return True

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

    @override
    def on_app_leave(self):
        super().on_app_leave()
        self.__clear_code()
