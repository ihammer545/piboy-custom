from __future__ import annotations

import math
from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw, ImageFont

from app.App import SelfUpdatingApp
from app.ui_kit import button_row, draw_button, fit_text, make_hit
from core.decorator import override
from environment import AppConfig
from interaction.touch.events import HitTarget, Rect, hit_test
from ports.devices import DeviceInfo, DevicePresence
from services.terminal import DeviceService


class DevicesApp(SelfUpdatingApp):
    """СИСТЕМЫ — tile controls for ventilation / lights / pump."""

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
            self.__message = f'Подтвердите: {device.name}'
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

        draw.text((layout.pad, layout.pad), 'СИСТЕМЫ — силовые модули', fill=accent, font=header)

        devices = self.__devices.devices()
        btn_h = layout.button_min_height
        msg_h = layout.line_height if self.__message else 0
        tiles_top = layout.pad + layout.line_height + layout.gap
        tiles_bottom = height - layout.pad - btn_h - layout.gap
        if msg_h:
            tiles_bottom -= msg_h + layout.gap

        gap = layout.gap
        n = max(1, len(devices))
        tile_w = (width - 2 * layout.pad - gap * (n - 1)) // n

        for index, device in enumerate(devices):
            x0 = layout.pad + index * (tile_w + gap)
            box = Rect(x0, tiles_top, x0 + tile_w - 1, tiles_bottom)
            selected = index == self.__selected and self.__focus_action == 0
            self.__draw_device_tile(draw, box, device, accent, dark, bg, header, font,
                                    selected=selected)
            self.__hits.append(make_hit(box, f'device:{index}',
                                        min_w=layout.button_min_width, min_h=layout.button_min_height))

        if self.__message:
            my = tiles_bottom + layout.gap
            draw.text((layout.pad, my), fit_text(font, self.__message, width - 2 * layout.pad),
                      fill=accent, font=font)

        btn_y = height - btn_h - layout.pad
        device = self.__current_device()
        online = device is not None and device.presence == DevicePresence.ONLINE
        if self.__confirm_pending:
            labels = [('confirm', 'Подтвердить', True), ('cancel', 'Отмена', True)]
        else:
            labels = [('toggle', 'Переключить', online)]
        buttons = button_row(width, btn_y, [label for _, label, _ in labels], layout.button_min_width,
                             btn_h, layout.gap, layout.pad)
        for i, ((action_id, _label, enabled), (_, box)) in enumerate(zip(labels, buttons)):
            draw_button(draw, box, _label, font, accent, dark,
                        focused=self.__focus_action == i + 1, background=bg,
                        pressed=self.__pressed == action_id, disabled=not enabled)
            self.__hits.append(make_hit(box, action_id, enabled=enabled,
                                        min_w=layout.button_min_width, min_h=layout.button_min_height))

        self.__pressed = None
        yield image, 0, 0

    def __draw_device_tile(self, draw: ImageDraw.ImageDraw, box: Rect, device: DeviceInfo,
                           accent, dark, bg, header: ImageFont.FreeTypeFont,
                           font: ImageFont.FreeTypeFont, *, selected: bool) -> None:
        online = device.presence == DevicePresence.ONLINE
        on = device.powered_on and online
        color = accent if online else dark

        if selected:
            draw.rectangle(box.as_tuple(), outline=accent, width=3)
            inset = Rect(box.x0 + 3, box.y0 + 3, box.x1 - 3, box.y1 - 3)
            draw.rectangle(inset.as_tuple(), outline=accent, width=1)
        else:
            draw.rectangle(box.as_tuple(), outline=color, width=2)

        self.__draw_screws(draw, box, dark if online else dark)

        # Title
        title = fit_text(header, device.name.upper(), box.width - 20)
        draw.text((box.x0 + 10, box.y0 + 8), title, fill=color, font=header)
        kind = {
            'vent': 'воздух',
            'lights': 'свет',
            'pump': 'вода',
        }.get(device.device_id, device.kind)
        draw.text((box.x0 + 10, box.y0 + 30), kind, fill=dark, font=font)

        # Pictogram area (centered upper half)
        icon_cx = box.x0 + box.width // 2
        icon_cy = box.y0 + 95
        icon_r = min(48, box.width // 3, (box.height - 140) // 2)
        if device.device_id == 'vent':
            self.__draw_fan(draw, icon_cx, icon_cy, icon_r, color, on=on)
        elif device.device_id == 'lights':
            self.__draw_bulb(draw, icon_cx, icon_cy, icon_r, color, on=on)
        elif device.device_id == 'pump':
            self.__draw_pump(draw, icon_cx, icon_cy, icon_r, color, on=on)
        else:
            draw.ellipse((icon_cx - icon_r, icon_cy - icon_r, icon_cx + icon_r, icon_cy + icon_r),
                         outline=color, width=2)

        # Status badge at bottom of tile
        if not online:
            power = 'OFFLINE'
            badge_fill = False
        elif on:
            power = 'ВКЛ'
            badge_fill = True
        else:
            power = 'ВЫКЛ'
            badge_fill = False

        badge_h = 36
        badge = Rect(box.x0 + 12, box.y1 - badge_h - 12, box.x1 - 12, box.y1 - 12)
        if badge_fill:
            draw.rectangle(badge.as_tuple(), fill=accent, outline=accent, width=2)
            text_color = bg
        else:
            draw.rectangle(badge.as_tuple(), outline=color, width=2)
            text_color = color
        _, _, tw, th = header.getbbox(power)
        draw.text((badge.x0 + (badge.width - tw) // 2, badge.y0 + (badge.height - th) // 2),
                  power, fill=text_color, font=header)

        if device.requires_confirm and online:
            draw.text((box.x0 + 10, badge.y0 - 20), 'нужно подтв.', fill=dark, font=font)

    @staticmethod
    def __draw_screws(draw: ImageDraw.ImageDraw, box: Rect, color) -> None:
        r = 3
        for cx, cy in (
            (box.x0 + 8, box.y0 + 8),
            (box.x1 - 8, box.y0 + 8),
            (box.x0 + 8, box.y1 - 8),
            (box.x1 - 8, box.y1 - 8),
        ):
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color)
            draw.line((cx - 2, cy, cx + 2, cy), fill=color, width=1)

    @staticmethod
    def __draw_fan(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color, *, on: bool) -> None:
        """Circular fan / blower grille."""
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=2)
        blades = 3 if not on else 4
        # Spin offset when on for a "running" look
        offset = 0.35 if on else 0.0
        for i in range(blades):
            a0 = offset + i * (2 * math.pi / blades)
            a1 = a0 + 0.9
            points = [(cx, cy)]
            for t in (a0, (a0 + a1) / 2, a1):
                points.append((int(cx + math.cos(t) * (r - 6)),
                               int(cy + math.sin(t) * (r - 6))))
            if on:
                draw.polygon(points, fill=color)
            else:
                draw.polygon(points, outline=color)
        hub = max(4, r // 6)
        draw.ellipse((cx - hub, cy - hub, cx + hub, cy + hub),
                     fill=color if on else None, outline=color, width=2)
        # Speed marks when running
        if on:
            for dx in (-r - 8, r + 4):
                draw.line((cx + dx, cy - 6, cx + dx + (4 if dx < 0 else -4), cy), fill=color, width=1)
                draw.line((cx + dx, cy + 6, cx + dx + (4 if dx < 0 else -4), cy), fill=color, width=1)

    @staticmethod
    def __draw_bulb(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color, *, on: bool) -> None:
        """Incandescent bulb with optional rays."""
        bulb_r = int(r * 0.72)
        by = cy - 6
        draw.ellipse((cx - bulb_r, by - bulb_r, cx + bulb_r, by + bulb_r),
                     fill=color if on else None, outline=color, width=2)
        # Neck / base
        neck_w = bulb_r // 2
        draw.rectangle((cx - neck_w, by + bulb_r - 4, cx + neck_w, by + bulb_r + 10),
                       outline=color, width=2)
        # Screw base ridges
        base_top = by + bulb_r + 10
        for i in range(3):
            y = base_top + i * 5
            draw.line((cx - neck_w + 2, y, cx + neck_w - 2, y), fill=color, width=1)
        draw.rectangle((cx - neck_w + 2, base_top + 14, cx + neck_w - 2, base_top + 20),
                       fill=color if on else None, outline=color, width=1)
        # Rays when on
        if on:
            for ang in range(0, 360, 45):
                rad = math.radians(ang)
                x0 = int(cx + math.cos(rad) * (bulb_r + 6))
                y0 = int(by + math.sin(rad) * (bulb_r + 6))
                x1 = int(cx + math.cos(rad) * (bulb_r + 16))
                y1 = int(by + math.sin(rad) * (bulb_r + 16))
                draw.line((x0, y0, x1, y1), fill=color, width=2)

    @staticmethod
    def __draw_pump(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color, *, on: bool) -> None:
        """Pump body + pipes + droplet when running."""
        body_w = int(r * 1.2)
        body_h = int(r * 0.9)
        body = Rect(cx - body_w // 2, cy - body_h // 2, cx + body_w // 2, cy + body_h // 2)
        draw.rectangle(body.as_tuple(), fill=color if on else None, outline=color, width=2)
        # Motor circle
        mr = body_h // 3
        draw.ellipse((cx - mr, cy - mr, cx + mr, cy + mr), outline=color if on else color, width=2)
        if on:
            draw.ellipse((cx - mr // 2, cy - mr // 2, cx + mr // 2, cy + mr // 2), fill=color)
        # Inlet / outlet pipes
        pipe_y = cy
        draw.rectangle((body.x0 - 22, pipe_y - 5, body.x0, pipe_y + 5), outline=color, width=2)
        draw.rectangle((body.x1, pipe_y - 5, body.x1 + 22, pipe_y + 5), outline=color, width=2)
        # Flanges
        draw.rectangle((body.x0 - 26, pipe_y - 9, body.x0 - 20, pipe_y + 9), outline=color, width=1)
        draw.rectangle((body.x1 + 20, pipe_y - 9, body.x1 + 26, pipe_y + 9), outline=color, width=1)
        # Droplets when on
        if on:
            for i, (dx, dy) in enumerate(((-30, 18), (28, 22), (0, 28))):
                px, py = cx + dx, cy + dy
                draw.ellipse((px - 4, py - 2, px + 4, py + 6), outline=color)
                draw.polygon([(px, py - 8), (px - 4, py), (px + 4, py)], outline=color)

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
        if self.__focus_action == 0:
            devices = self.__devices.devices()
            if devices:
                self.__selected = (self.__selected - 1) % len(devices)
            return
        self.__focus_action = max(0, self.__focus_action - 1)

    @override
    def on_key_right(self):
        if self.__focus_action == 0:
            devices = self.__devices.devices()
            if devices:
                self.__selected = (self.__selected + 1) % len(devices)
            return
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
