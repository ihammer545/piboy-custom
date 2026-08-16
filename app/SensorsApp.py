from __future__ import annotations

import math
from typing import Any, Callable, Generator

from injector import inject
from PIL import Image, ImageDraw, ImageFont

from app.App import SelfUpdatingApp
from app.ui_kit import fit_text, make_hit
from core.data import DeviceStatus
from core.decorator import override
from environment import AppConfig
from interaction.touch.events import HitTarget, Rect, hit_test
from services.terminal import SensorService


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _temp_zone(celsius: float) -> str:
    if celsius < 10:
        return 'ХОЛОД'
    if celsius > 35:
        return 'ЖАРА'
    return 'НОРМА'


def _humidity_zone(ratio: float) -> str:
    if ratio < 0.20:
        return 'СУХО'
    if ratio > 0.80:
        return 'СЫРО'
    return 'НОРМА'


class SensorsApp(SelfUpdatingApp):
    """СРЕДА — Fallout-style analog temp / humidity instruments."""

    TEMP_MIN = 0.0
    TEMP_MAX = 45.0

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
        width, height = cfg.app_size
        font = cfg.font_standard
        header = cfg.font_header
        accent, dark, bg = cfg.accent, cfg.accent_dark, cfg.background
        self.__hits = []

        draw.text((layout.pad, layout.pad), 'СРЕДА — контроль атмосферы', fill=accent, font=header)

        reading = self.__sensors.reading()
        status = 'ONLINE' if reading.status == DeviceStatus.OPERATIONAL else 'OFFLINE'
        stamp = reading.last_update.strftime('%H:%M:%S') if reading.last_update else '—'
        meta = fit_text(font, f'{status}  ·  обн. {stamp}', width - 2 * layout.pad)
        draw.text((layout.pad, layout.pad + layout.line_height), meta, fill=dark, font=font)

        panel_top = layout.pad + layout.line_height * 2 + layout.gap
        panel_bottom = height - layout.pad
        if reading.warning:
            panel_bottom -= layout.button_min_height + layout.gap

        gap = layout.gap
        panel_w = (width - 2 * layout.pad - gap) // 2
        left = Rect(layout.pad, panel_top, layout.pad + panel_w - 1, panel_bottom)
        right = Rect(left.x1 + 1 + gap, panel_top, left.x1 + gap + panel_w, panel_bottom)

        if reading.data is None:
            self.__draw_empty_panel(draw, left, 'ТЕРМОМЕТР', accent, dark, header, font)
            self.__draw_empty_panel(draw, right, 'ГИГРОМЕТР', accent, dark, header, font)
        else:
            temp = reading.data.temperature
            hum = reading.data.humidity
            self.__draw_thermometer(draw, left, temp, accent, dark, bg, header, font,
                                    selected=self.__selected_metric == 'temp')
            self.__draw_hygrometer(draw, right, hum, accent, dark, bg, header, font,
                                   selected=self.__selected_metric == 'humidity')
            self.__hits.append(make_hit(left, 'metric:temp',
                                        min_w=layout.button_min_width, min_h=layout.button_min_height))
            self.__hits.append(make_hit(right, 'metric:humidity',
                                        min_w=layout.button_min_width, min_h=layout.button_min_height))

        if reading.warning:
            wy = height - layout.pad - layout.button_min_height
            draw.rectangle((layout.pad, wy, width - layout.pad, height - layout.pad),
                           outline=accent, width=2)
            draw.text((layout.pad + 8, wy + 10),
                      fit_text(font, reading.warning, width - 2 * layout.pad - 16),
                      fill=accent, font=font)

        yield image, 0, 0

    def __draw_empty_panel(self, draw: ImageDraw.ImageDraw, box: Rect, title: str,
                           accent, dark, header, font) -> None:
        draw.rectangle(box.as_tuple(), outline=accent, width=2)
        draw.text((box.x0 + 10, box.y0 + 8), title, fill=accent, font=header)
        draw.text((box.x0 + 10, box.y0 + box.height // 2), 'НЕТ ДАННЫХ', fill=dark, font=font)

    def __draw_thermometer(self, draw: ImageDraw.ImageDraw, box: Rect, temp_c: float,
                           accent, dark, bg, header: ImageFont.FreeTypeFont,
                           font: ImageFont.FreeTypeFont, *, selected: bool) -> None:
        if selected:
            draw.rectangle(box.as_tuple(), fill=dark, outline=accent, width=2)
        else:
            draw.rectangle(box.as_tuple(), outline=accent, width=2)

        draw.text((box.x0 + 10, box.y0 + 6), 'ТЕРМОМЕТР', fill=accent, font=header)
        draw.text((box.x0 + 10, box.y0 + 6 + 22), 'модуль убежища', fill=dark, font=font)

        # Instrument body: glass tube + bulb on the left half.
        tube_x = box.x0 + 36
        tube_top = box.y0 + 58
        tube_bottom = box.y1 - 52
        tube_w = 18
        bulb_r = 22
        bulb_cy = tube_bottom + 4
        bulb_cx = tube_x + tube_w // 2

        # Scale ticks (°C)
        for t in range(0, 46, 5):
            frac = (t - self.TEMP_MIN) / (self.TEMP_MAX - self.TEMP_MIN)
            ty = int(tube_bottom - frac * (tube_bottom - tube_top))
            tick_len = 10 if t % 10 == 0 else 6
            draw.line((tube_x + tube_w + 4, ty, tube_x + tube_w + 4 + tick_len, ty),
                      fill=accent if t % 10 == 0 else dark, width=1)
            if t % 10 == 0:
                draw.text((tube_x + tube_w + 16, ty - 7), str(t), fill=dark, font=font)

        # Tube outline
        draw.rectangle((tube_x, tube_top, tube_x + tube_w, tube_bottom), outline=accent, width=2)
        # Bulb
        draw.ellipse((bulb_cx - bulb_r, bulb_cy - bulb_r, bulb_cx + bulb_r, bulb_cy + bulb_r),
                     outline=accent, width=2)

        # Mercury / radiation goo fill
        frac = _clamp((temp_c - self.TEMP_MIN) / (self.TEMP_MAX - self.TEMP_MIN), 0.0, 1.0)
        fill_top = int(tube_bottom - frac * (tube_bottom - tube_top))
        if fill_top < tube_bottom:
            draw.rectangle((tube_x + 3, fill_top, tube_x + tube_w - 3, tube_bottom), fill=accent)
        # Fill bulb solid
        draw.ellipse((bulb_cx - bulb_r + 4, bulb_cy - bulb_r + 4,
                      bulb_cx + bulb_r - 4, bulb_cy + bulb_r - 4), fill=accent)
        # Join tube into bulb
        draw.rectangle((tube_x + 3, tube_bottom - 6, tube_x + tube_w - 3, bulb_cy), fill=accent)

        # Digital readout + zone (right side of panel)
        rx = tube_x + tube_w + 70
        ry = box.y0 + 70
        value = f'{temp_c:.1f}°C'
        draw.text((rx, ry), value, fill=accent, font=header)
        zone = _temp_zone(temp_c)
        draw.text((rx, ry + 28), f'зона: {zone}', fill=accent, font=font)

        # Tiny face: happy / sweaty / chilly stick-glyph
        face_cx, face_cy = rx + 40, ry + 90
        self.__draw_mood_face(draw, face_cx, face_cy, zone, accent, dark)

        # Screw corners (Pip-Boy panel flavor)
        self.__draw_screws(draw, box, dark)

    def __draw_hygrometer(self, draw: ImageDraw.ImageDraw, box: Rect, humidity: float,
                          accent, dark, bg, header: ImageFont.FreeTypeFont,
                          font: ImageFont.FreeTypeFont, *, selected: bool) -> None:
        if selected:
            draw.rectangle(box.as_tuple(), fill=dark, outline=accent, width=2)
        else:
            draw.rectangle(box.as_tuple(), outline=accent, width=2)

        draw.text((box.x0 + 10, box.y0 + 6), 'ГИГРОМЕТР', fill=accent, font=header)
        draw.text((box.x0 + 10, box.y0 + 6 + 22), 'запас влаги', fill=dark, font=font)

        # Water tank silhouette
        tank = Rect(box.x0 + 28, box.y0 + 58, box.x0 + 120, box.y1 - 40)
        draw.rectangle(tank.as_tuple(), outline=accent, width=2)
        # Rivets along sides
        for yy in range(tank.y0 + 12, tank.y1 - 8, 28):
            draw.ellipse((tank.x0 - 3, yy - 3, tank.x0 + 3, yy + 3), outline=dark)
            draw.ellipse((tank.x1 - 3, yy - 3, tank.x1 + 3, yy + 3), outline=dark)

        # Water fill
        hum = _clamp(humidity, 0.0, 1.0)
        water_top = int(tank.y1 - hum * (tank.height - 8) - 4)
        water_top = min(max(water_top, tank.y0 + 4), tank.y1 - 4)
        if water_top < tank.y1 - 4:
            # Wavy surface
            for x in range(tank.x0 + 4, tank.x1 - 3):
                wave = int(2 * math.sin((x + water_top) * 0.35))
                draw.line((x, water_top + wave, x, tank.y1 - 4), fill=accent)
            # Hatch pattern inside water (fallout CRT texture)
            for yy in range(water_top + 8, tank.y1 - 4, 8):
                draw.line((tank.x0 + 6, yy, tank.x1 - 6, yy), fill=dark, width=1)

        # Percent marks
        for pct in (0, 25, 50, 75, 100):
            frac = pct / 100.0
            ty = int(tank.y1 - frac * (tank.height - 8) - 4)
            draw.line((tank.x1 + 4, ty, tank.x1 + 12, ty), fill=accent, width=1)
            draw.text((tank.x1 + 16, ty - 7), f'{pct}', fill=dark, font=font)

        # Droplet mascot above tank
        self.__draw_droplet(draw, tank.x0 + tank.width // 2, tank.y0 - 6, accent)

        # Digital readout
        rx = tank.x1 + 55
        ry = box.y0 + 90
        if rx + 80 > box.x1:
            rx = box.x0 + 140
            ry = box.y1 - 70
        value = f'{hum:.0%}'
        draw.text((rx, ry), value, fill=accent, font=header)
        zone = _humidity_zone(hum)
        draw.text((rx, ry + 28), f'зона: {zone}', fill=accent, font=font)

        self.__draw_screws(draw, box, dark)

    @staticmethod
    def __draw_screws(draw: ImageDraw.ImageDraw, box: Rect, color) -> None:
        r = 3
        pts = [
            (box.x0 + 8, box.y0 + 8),
            (box.x1 - 8, box.y0 + 8),
            (box.x0 + 8, box.y1 - 8),
            (box.x1 - 8, box.y1 - 8),
        ]
        for cx, cy in pts:
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color)
            draw.line((cx - 2, cy, cx + 2, cy), fill=color, width=1)

    @staticmethod
    def __draw_droplet(draw: ImageDraw.ImageDraw, cx: int, tip_y: int, color) -> None:
        # Simple teardrop: triangle + circle
        r = 10
        draw.polygon([(cx, tip_y - 16), (cx - r, tip_y), (cx + r, tip_y)], outline=color)
        draw.ellipse((cx - r, tip_y - 6, cx + r, tip_y + r + 2), outline=color)

    @staticmethod
    def __draw_mood_face(draw: ImageDraw.ImageDraw, cx: int, cy: int, zone: str,
                         accent, dark) -> None:
        r = 22
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=accent, width=2)
        # Eyes
        draw.rectangle((cx - 10, cy - 8, cx - 6, cy - 4), fill=accent)
        draw.rectangle((cx + 6, cy - 8, cx + 10, cy - 4), fill=accent)
        if zone == 'ЖАРА':
            # Tongue out / wavy mouth
            draw.arc((cx - 12, cy - 2, cx + 12, cy + 14), 20, 160, fill=accent, width=2)
            draw.rectangle((cx - 3, cy + 6, cx + 3, cy + 14), fill=accent)
            # Sweat drop
            draw.ellipse((cx + r - 2, cy - r, cx + r + 6, cy - r + 10), outline=dark)
        elif zone == 'ХОЛОД':
            # Chattering flat mouth + shiver lines
            draw.line((cx - 10, cy + 8, cx + 10, cy + 8), fill=accent, width=2)
            for dx in (-18, 18):
                draw.line((cx + dx, cy - 6, cx + dx - 3, cy + 6), fill=dark, width=1)
        else:
            # Smile
            draw.arc((cx - 12, cy - 2, cx + 12, cy + 14), 20, 160, fill=accent, width=2)

    @override
    def on_tap(self, x: int, y: int) -> bool:
        target = hit_test(self.__hits, x, y)
        if target is None or not target.action.startswith('metric:'):
            return False
        self.__selected_metric = target.action.split(':', 1)[1]
        return True
