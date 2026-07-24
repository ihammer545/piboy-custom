from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw

from app.App import SelfUpdatingApp
from app.ui_kit import button_row, draw_button, fit_text, make_hit
from core.decorator import override
from environment import AppConfig
from interaction.touch.events import HitTarget, Rect, hit_test
from ports.devices import DevicePresence
from services.terminal import DeviceService


class DevicesApp(SelfUpdatingApp):
    """СИСТЕМЫ — shelter device control."""

    @inject
    def __init__(self, draw_callback: Callable[[bool], None], devices: DeviceService,
                 app_config: AppConfig):
        super().__init__(lambda: draw_callback(True))
        self.__devices = devices
        self.__app_config = app_config
        self.__selected = 0
        self.__confirm_pending = False
        self.__message = ''
        self.__focus_action = 0
        self.__hits: list[HitTarget] = []
        self.__pressed: str | None = None

    @property
    @override
    def title(self) -> str:
        return 'СИСТ'

    @property
    @override
    def refresh_time(self) -> float:
        return 0.5

    def __current_device(self):
        devices = self.__devices.devices()
        if not devices:
            return None
        return devices[self.__selected % len(devices)]

    def __request_toggle(self):
        device = self.__current_device()
        if device is None:
            return
        if device.presence != DevicePresence.ONLINE:
            self.__message = f'«{device.name}» недоступно'
            return
        if device.requires_confirm and not self.__confirm_pending:
            self.__confirm_pending = True
            self.__message = f'Подтвердите действие: {device.name}'
            self.__focus_action = 1
            return
        result = self.__devices.toggle(device.device_id)
        self.__confirm_pending = False
        self.__message = result.message
        self.__focus_action = 0

    def __cancel(self):
        self.__confirm_pending = False
        self.__message = 'Отменено'
        self.__focus_action = 0

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

        draw.text((layout.pad, layout.pad), 'СИСТЕМЫ — устройства убежища', fill=accent, font=header)

        devices = self.__devices.devices()
        y = layout.pad + layout.line_height + layout.gap
        row_h = max(layout.list_row_height, layout.button_min_height)
        for index, device in enumerate(devices):
            selected = index == self.__selected and self.__focus_action == 0
            box = Rect(layout.pad, y, width - layout.pad, y + row_h - 1)
            if selected:
                draw.rectangle(box.as_tuple(), fill=dark)
            presence = 'online' if device.presence == DevicePresence.ONLINE else 'offline'
            power = 'ВКЛ' if device.powered_on else 'ВЫКЛ'
            line = fit_text(font, f'{device.name}  [{presence}]  {power}', width - 2 * layout.pad - 8)
            text_color = accent if device.presence == DevicePresence.ONLINE else dark
            draw.text((layout.pad + 6, y + (row_h - layout.line_height) // 2), line, fill=text_color, font=font)
            self.__hits.append(make_hit(box, f'device:{index}',
                                        min_w=layout.button_min_width, min_h=layout.button_min_height))
            y += row_h + 4

        if self.__message:
            draw.text((layout.pad, y + layout.gap), fit_text(font, self.__message, width - 2 * layout.pad),
                      fill=accent, font=font)

        btn_y = height - layout.button_min_height - layout.pad
        device = self.__current_device()
        online = device is not None and device.presence == DevicePresence.ONLINE
        if self.__confirm_pending:
            labels = [('confirm', 'Подтвердить', True), ('cancel', 'Отмена', True)]
        else:
            labels = [('toggle', 'Переключить', online)]
        buttons = button_row(width, btn_y, [label for _, label, _ in labels], layout.button_min_width,
                             layout.button_min_height, layout.gap, layout.pad)
        for i, ((action_id, label, enabled), (_, box)) in enumerate(zip(labels, buttons)):
            draw_button(draw, box, label, font, accent, dark,
                        focused=self.__focus_action == i + 1, background=bg,
                        pressed=self.__pressed == action_id, disabled=not enabled)
            self.__hits.append(make_hit(box, action_id, enabled=enabled,
                                        min_w=layout.button_min_width, min_h=layout.button_min_height))

        self.__pressed = None
        yield image, 0, 0

    @override
    def on_tap(self, x: int, y: int) -> bool:
        target = hit_test(self.__hits, x, y)
        if target is None:
            return False
        self.__pressed = target.action
        if target.action.startswith('device:'):
            self.__selected = int(target.action.split(':', 1)[1])
            self.__focus_action = 0
            self.__confirm_pending = False
            return True
        if target.action == 'toggle':
            self.__request_toggle()
            return True
        if target.action == 'confirm':
            self.__request_toggle()
            return True
        if target.action == 'cancel':
            self.__cancel()
            return True
        return False

    @override
    def on_key_up(self):
        devices = self.__devices.devices()
        if devices and self.__focus_action == 0:
            self.__selected = (self.__selected - 1) % len(devices)

    @override
    def on_key_down(self):
        devices = self.__devices.devices()
        if devices and self.__focus_action == 0:
            self.__selected = (self.__selected + 1) % len(devices)

    @override
    def on_key_left(self):
        self.__focus_action = max(0, self.__focus_action - 1)

    @override
    def on_key_right(self):
        max_focus = 2 if self.__confirm_pending else 1
        self.__focus_action = min(max_focus, self.__focus_action + 1)

    @override
    def on_key_a(self):
        if self.__confirm_pending:
            if self.__focus_action == 2:
                self.__cancel()
            else:
                self.__request_toggle()
        else:
            self.__request_toggle()

    @override
    def on_key_b(self):
        self.__confirm_pending = False
        self.__message = ''
        self.__focus_action = 0

    @override
    def on_app_leave(self):
        super().on_app_leave()
        self.__confirm_pending = False
        self.__message = ''
        self.__focus_action = 0
