from PIL import ImageDraw, ImageFont


def fit_text(font: ImageFont.FreeTypeFont, text: str, max_width: int) -> str:
    if font.getbbox(text)[2] <= max_width:
        return text
    ellipsis = '…'
    while text and font.getbbox(text + ellipsis)[2] > max_width:
        text = text[:-1]
    return text + ellipsis if text else ellipsis


def draw_button(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], label: str,
                font: ImageFont.FreeTypeFont, accent: tuple[int, int, int],
                accent_dark: tuple[int, int, int], focused: bool = False,
                background: tuple[int, int, int] = (0, 0, 0)) -> None:
    x0, y0, x1, y1 = box
    fill = accent_dark if focused else background
    outline = accent
    draw.rectangle((x0, y0, x1, y1), fill=fill, outline=outline, width=2)
    label = fit_text(font, label, x1 - x0 - 12)
    _, _, tw, th = font.getbbox(label)
    tx = x0 + (x1 - x0 - tw) // 2
    ty = y0 + (y1 - y0 - th) // 2
    draw.text((tx, ty), label, fill=accent, font=font)


def button_row(width: int, y: int, labels: list[str], min_width: int, height: int,
               gap: int, side_pad: int = 0) -> list[tuple[str, tuple[int, int, int, int]]]:
    count = len(labels)
    if count == 0:
        return []
    available = width - 2 * side_pad - gap * (count - 1)
    btn_w = max(min_width, available // count)
    total = btn_w * count + gap * (count - 1)
    x = side_pad + max(0, (width - 2 * side_pad - total) // 2)
    result = []
    for label in labels:
        box = (x, y, x + btn_w - 1, y + height - 1)
        result.append((label, box))
        x += btn_w + gap
    return result
