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
from services.ui_sound import UiSoundService


class AccessUiState(Enum):
    IDLE = 'ожидание'
    CHECKING = 'проверка'
    GRANTED = 'доступ разрешён'
    DENIED = 'отказ'


class AccessApp(SelfUpdatingApp):
    """ДОСТУП — code entry and simulated lock pulse."""

    # Left digit pad (3×4). Right column: OK + Сброс only.
    DIGITS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '⌫', '0', '']
    ACTIONS = ['OK', 'Сброс']

    @inject
    def __init__(self, draw_callback: Callable[[bool], None], access: AccessService,
                 app_config: AppConfig, sounds: UiSoundService):
        super().__init__(lambda: draw_callback(True))
        self.__access = access
        self.__app_config = app_config
        self.__sounds = sounds
        self.__digits = ''
        self.__mask_char = '●'
        self.__ui_state = AccessUiState.IDLE
        self.__message = 'Введите код'
        self.__scenario = ''
        # Focus index into DIGITS+ACTIONS (skip empty pad cells)
        self.__focus_key = '1'
        self.__hits: list[HitTarget] = []
        self.__pressed_key: str | None = None

    @property
    def __keys(self) -> list[str]:
        """Navigable keys in reading order (no empty cells)."""
        return [k for k in self.DIGITS if k] + self.ACTIONS

    @property
    @override
    def title(self) -> str:
        return 'ДОСТ'

    @property
    @override
    def emits_tap_sound(self) -> bool:
        return False

    @property
    @override
    def refresh_time(self) -> float:
        return 0.25

    def __clear_code(self):
        self.__digits = ''
        self.__ui_state = AccessUiState.IDLE
        self.__message = 'Введите код'
        self.__scenario = ''

    def __press(self, key: str, *, from_touch: bool = False):
        if not key:
            return
        if key in ('Сброс', 'clear'):
            self.__sounds.back()
            self.__clear_code()
            return
        if key in ('⌫', 'backspace'):
            self.__sounds.back()
            self.__digits = self.__digits[:-1]
            self.__ui_state = AccessUiState.IDLE
            self.__message = 'Введите код'
            return
        if key == 'OK':
            self.__sounds.confirm()
            self.__submit()
            return
        if key.isdigit() and len(self.__digits) < 8:
            if from_touch:
                self.__sounds.touch()
            else:
                self.__sounds.key()
            self.__digits += key
            self.__ui_state = AccessUiState.IDLE
            self.__message = 'Введите код'

    def __submit(self):
        self.__ui_state = AccessUiState.CHECKING
        self.__message = 'Проверка...'
        result, pulse = self.__access.submit_code(self.__digits)
        self.__digits = ''
        if result.outcome == AccessOutcome.DENIED:
            self.__ui_state = AccessUiState.DENIED
            self.__message = result.message
            self.__scenario = result.scenario
            self.__sounds.denied()
        else:
            self.__ui_state = AccessUiState.GRANTED
            self.__message = result.message
            self.__scenario = result.scenario
            if pulse is not None:
                self.__sounds.lock()

    def __move_focus(self, delta: int):
        keys = self.__keys
        if self.__focus_key not in keys:
            self.__focus_key = keys[0]
            return
        i = keys.index(self.__focus_key)
        self.__focus_key = keys[(i + delta) % len(keys)]

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

        # Keypad: taller / narrower digit cells on the left; OK + Сброс stacked on the right.
        info_bottom = y + layout.line_height + layout.gap
        grid_top = max(info_bottom, height // 3)
        grid_bottom = height - layout.pad
        gap = max(6, layout.gap - 2)
        action_w = max(120, (width * 2) // 5)
        pad_right = width - layout.pad
        pad_left = layout.pad
        digits_right = pad_right - action_w - gap
        digits_width = digits_right - pad_left

        rows, cols = 4, 3
        btn_w = (digits_width - (cols - 1) * gap) // cols
        # Keep digit keys narrow for one-finger taps; leave slack toward the action column.
        btn_w = min(btn_w, 100)
        btn_h = (grid_bottom - grid_top - (rows - 1) * gap) // rows
        btn_h = max(btn_h, layout.button_min_height + 16)

        for i, key in enumerate(self.DIGITS):
            row, col = divmod(i, cols)
            x0 = pad_left + col * (btn_w + gap)
            y0 = grid_top + row * (btn_h + gap)
            box = Rect(x0, y0, x0 + btn_w - 1, y0 + btn_h - 1)
            if not key:
                continue
            draw_button(draw, box, key, header, accent, dark,
                        focused=self.__focus_key == key, background=bg,
                        pressed=self.__pressed_key == key)
            self.__hits.append(make_hit(box, key, min_w=layout.button_min_width // 2,
                                        min_h=layout.button_min_height))

        action_h = (grid_bottom - grid_top - gap) // 2
        action_h = max(action_h, layout.button_min_height + 12)
        ax0 = digits_right + gap
        for j, key in enumerate(self.ACTIONS):
            y0 = grid_top + j * (action_h + gap)
            box = Rect(ax0, y0, pad_right - 1, y0 + action_h - 1)
            draw_button(draw, box, key, header, accent, dark,
                        focused=self.__focus_key == key, background=bg,
                        pressed=self.__pressed_key == key)
            self.__hits.append(make_hit(box, key, min_w=layout.button_min_width,
                                        min_h=layout.button_min_height))

        self.__pressed_key = None
        yield image, 0, 0

    @override
    def on_tap(self, x: int, y: int) -> bool:
        target = hit_test(self.__hits, x, y)
        if target is None:
            return False
        self.__pressed_key = target.action
        self.__focus_key = target.action
        self.__press(target.action, from_touch=True)
        return True

    @override
    def on_digit(self, digit: str) -> bool:
        if digit.isdigit():
            self.__press(digit, from_touch=False)
            return True
        return False

    @override
    def on_backspace(self) -> bool:
        self.__press('⌫', from_touch=False)
        return True

    @override
    def on_key_left(self):
        self.__move_focus(-1)

    @override
    def on_key_right(self):
        self.__move_focus(1)

    @override
    def on_key_up(self):
        # Prefer vertical step of 3 within digit pad; otherwise previous key.
        if self.__focus_key in self.DIGITS:
            i = self.DIGITS.index(self.__focus_key)
            ni = i - 3
            if ni >= 0 and self.DIGITS[ni]:
                self.__focus_key = self.DIGITS[ni]
                return
        self.__move_focus(-1)

    @override
    def on_key_down(self):
        if self.__focus_key in self.DIGITS:
            i = self.DIGITS.index(self.__focus_key)
            ni = i + 3
            if ni < len(self.DIGITS) and self.DIGITS[ni]:
                self.__focus_key = self.DIGITS[ni]
                return
            if self.__focus_key in ('⌫', '0', '7', '8', '9'):
                self.__focus_key = 'OK'
                return
        self.__move_focus(1)

    @override
    def on_key_a(self):
        self.__press(self.__focus_key, from_touch=False)

    @override
    def on_key_b(self):
        self.__press('Сброс', from_touch=False)

    @override
    def on_app_leave(self):
        super().on_app_leave()
        self.__clear_code()
