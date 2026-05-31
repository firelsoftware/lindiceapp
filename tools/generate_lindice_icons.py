from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "accounts" / "static" / "accounts"


def lerp(a, b, t):
    return int(a + (b - a) * t)


def gradient_rect(size, top, bottom):
    width, height = size
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)

    for y in range(height):
        t = y / max(height - 1, 1)
        color = tuple(lerp(top[i], bottom[i], t) for i in range(4))
        draw.line([(0, y), (width, y)], fill=color)

    return image


def rounded_gradient(size, radius, top, bottom):
    gradient = gradient_rect(size, top, bottom)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    gradient.putalpha(mask)

    return gradient


def paste_shadow(base, layer, xy, blur, offset, alpha):
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", layer.size, (17, 24, 39, alpha))
    shadow_layer.putalpha(layer.getchannel("A"))
    shadow.alpha_composite(shadow_layer, (xy[0] + offset[0], xy[1] + offset[1]))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(shadow)


def render_icon(size):
    scale = size / 512
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))

    shell_box = tuple(round(v * scale) for v in (38, 38, 474, 474))
    shell_radius = round(100 * scale)
    border_width = max(3, round(14 * scale))

    shell_shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shell_shadow).rounded_rectangle(shell_box, radius=shell_radius, fill=(29, 41, 57, 34))
    shell_shadow = shell_shadow.filter(ImageFilter.GaussianBlur(round(20 * scale)))
    canvas.alpha_composite(shell_shadow, (0, round(18 * scale)))

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(shell_box, radius=shell_radius, fill=(255, 255, 255, 255), outline=(187, 200, 212, 255), width=border_width)

    inner = tuple(round(v * scale) for v in (54, 54, 458, 458))
    draw.rounded_rectangle(inner, radius=round(86 * scale), fill=(250, 252, 255, 255))

    l_path = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    l_draw = ImageDraw.Draw(l_path)
    l_draw.rounded_rectangle(tuple(round(v * scale) for v in (151, 88, 242, 420)), radius=round(28 * scale), fill=(255, 255, 255, 255))
    l_draw.rounded_rectangle(tuple(round(v * scale) for v in (151, 336, 388, 420)), radius=round(28 * scale), fill=(255, 255, 255, 255))
    cut = tuple(round(v * scale) for v in (242, 88, 388, 336))
    l_draw.rectangle(cut, fill=(0, 0, 0, 0))

    blue = gradient_rect((size, size), (93, 118, 218, 255), (31, 59, 136, 255))
    blue.putalpha(l_path.getchannel("A"))
    paste_shadow(canvas, l_path, (0, 0), round(10 * scale), (0, round(12 * scale)), 88)
    canvas.alpha_composite(blue)

    purple_layer = rounded_gradient(
        (round(173 * scale), round(79 * scale)),
        round(28 * scale),
        (155, 63, 194, 255),
        (78, 29, 104, 255),
    )
    paste_shadow(canvas, purple_layer, (round(246 * scale), round(238 * scale)), round(10 * scale), (0, round(12 * scale)), 76)
    canvas.alpha_composite(purple_layer, (round(246 * scale), round(238 * scale)))

    mist_layer = rounded_gradient(
        (round(70 * scale), round(70 * scale)),
        round(22 * scale),
        (213, 229, 243, 255),
        (80, 105, 134, 255),
    )
    paste_shadow(canvas, mist_layer, (round(342 * scale), round(164 * scale)), round(8 * scale), (0, round(10 * scale)), 72)
    canvas.alpha_composite(mist_layer, (round(342 * scale), round(164 * scale)))

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(tuple(round(v * scale) for v in (166, 105, 227, 126)), radius=round(10 * scale), fill=(142, 162, 255, 120))
    draw.rounded_rectangle(tuple(round(v * scale) for v in (261, 252, 404, 269)), radius=round(8 * scale), fill=(215, 120, 238, 92))
    draw.rounded_rectangle(tuple(round(v * scale) for v in (347, 176, 408, 190)), radius=round(7 * scale), fill=(255, 255, 255, 90))

    return canvas


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        render_icon(size).save(OUT_DIR / f"lindice-icon-{size}.png")


if __name__ == "__main__":
    main()
