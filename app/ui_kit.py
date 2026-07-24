from __future__ import annotations

from PIL import ImageDraw, ImageFont

from interaction.touch.events import HitTarget, Rect


def fit_text(font: ImageFont.FreeTypeFont, text: str, max_width: int) -> str:
    if font.getbbox(text)[2] <= max_width:
        return text
    ellipsis = '…'
    while text and font.getbbox(text + ellipsis)[2] > max_width:
        text = text[:-1]
    return text + ellipsis if text else ellipsis


def draw_button(draw: ImageDraw.ImageDraw, box: Rect | tuple[int, int, int, int], label: str,
                font: ImageFont.FreeTypeFont, accent: tuple[int, int, int],
                accent_dark: tuple[int, int, int], focused: bool = False,
                background: tuple[int, int, int] = (0, 0, 0),
                pressed: bool = False, disabled: bool = False) -> Rect:
    rect = box if isinstance(box, Rect) else Rect(*box)
    if disabled:
        fill = background
        outline = accent_dark
        text_color = accent_dark
    elif pressed or focused:
        fill = accent_dark
        outline = accent
        text_color = accent
    else:
        fill = background
        outline = accent
        text_color = accent
    draw.rectangle(rect.as_tuple(), fill=fill, outline=outline, width=2)
    label = fit_text(font, label, rect.width - 12)
    _, _, tw, th = font.getbbox(label)
    tx = rect.x0 + (rect.width - tw) // 2
    ty = rect.y0 + (rect.height - th) // 2
    draw.text((tx, ty), label, fill=text_color, font=font)
    return rect


def button_row(width: int, y: int, labels: list[str], min_width: int, height: int,
               gap: int, side_pad: int = 0) -> list[tuple[str, Rect]]:
    count = len(labels)
    if count == 0:
        return []
    available = width - 2 * side_pad - gap * (count - 1)
    btn_w = max(min_width, available // count)
    total = btn_w * count + gap * (count - 1)
    x = side_pad + max(0, (width - 2 * side_pad - total) // 2)
    result = []
    for label in labels:
        rect = Rect(x, y, x + btn_w - 1, y + height - 1)
        result.append((label, rect))
        x += btn_w + gap
    return result


def make_hit(rect: Rect, action: str, enabled: bool = True, meta=None,
             min_w: int = 44, min_h: int = 44) -> HitTarget:
    hit_rect = rect.expand_to_min(min_w, min_h)
    return HitTarget(hit_rect, action, enabled=enabled, meta=meta)
