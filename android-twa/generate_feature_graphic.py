"""
Gera o feature graphic da Play Store (1024x500 PNG) com gradiente azul.

Uso:
    python generate_feature_graphic.py

Saida: feature-graphic.png (ao lado deste arquivo)

Obs.: usamos Pillow em vez de converter o SVG porque os renderizadores de
SVG disponiveis nao desenham o gradiente linear (fundo saia preto).
"""

import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1024, 500
OUT = os.path.join(os.path.dirname(__file__), "feature-graphic.png")

# Paleta (mesma do SVG)
STOPS = [
    (0.0, (0x3A, 0x52, 0xA8)),
    (0.5, (0x4D, 0x63, 0xB7)),
    (1.0, (0x6B, 0x7F, 0xC9)),
]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_color(t):
    for i in range(len(STOPS) - 1):
        t0, c0 = STOPS[i]
        t1, c1 = STOPS[i + 1]
        if t0 <= t <= t1:
            local = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return lerp(c0, c1, local)
    return STOPS[-1][1]


def load_font(names, size):
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    img = Image.new("RGB", (W, H))
    px = img.load()

    # Gradiente diagonal (canto superior esquerdo -> inferior direito)
    max_d = (W - 1) + (H - 1)
    for y in range(H):
        for x in range(W):
            t = (x + y) / max_d
            px[x, y] = gradient_color(t)

    draw = ImageDraw.Draw(img, "RGBA")

    # Circulos decorativos
    def circle(cx, cy, r, alpha):
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, alpha))

    circle(920, 80, 320, 13)
    circle(160, 440, 200, 13)
    circle(420, 120, 120, 15)

    # Caixa do logo (branca, arredondada) com "L"
    draw.rounded_rectangle([72, 175, 182, 285], radius=22, fill=(255, 255, 255, 255))
    font_logo = load_font(["arialbd.ttf", "Arialbd.ttf", "arial.ttf"], 76)
    draw.text((127, 230), "L", font=font_logo, fill=(0x4D, 0x63, 0xB7),
              anchor="mm")

    # Nome e tagline (tagline em duas linhas para nao invadir as pills)
    font_name = load_font(["arialbd.ttf", "arial.ttf"], 64)
    font_tag = load_font(["arial.ttf"], 21)
    draw.text((208, 205), "Líndice", font=font_name, fill=(255, 255, 255), anchor="lm")
    draw.text((210, 258), "Calçados, bolsas e", font=font_tag, fill=(235, 240, 250), anchor="lm")
    draw.text((210, 286), "acessórios femininos", font=font_tag, fill=(235, 240, 250), anchor="lm")

    # Pills lado direito
    pills = [
        "Catálogo de calçados",
        "Compra pelo app",
        "Crediário digital",
        "Acompanhe seu pedido",
        "Entrega no seu endereço",
    ]
    font_pill = load_font(["arial.ttf"], 17)
    pill_x = 472
    pill_y = 100
    pill_h = 48
    gap = 14
    for text in pills:
        tw = draw.textlength(text, font=font_pill)
        pill_w = int(tw) + 70
        draw.rounded_rectangle([pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
                               radius=24, fill=(255, 255, 255, 36),
                               outline=(255, 255, 255, 77), width=2)
        bullet_cx = pill_x + 28
        bullet_cy = pill_y + pill_h // 2
        draw.ellipse([bullet_cx - 5, bullet_cy - 5, bullet_cx + 5, bullet_cy + 5],
                     fill=(255, 255, 255, 255))
        draw.text((pill_x + 46, bullet_cy), text, font=font_pill,
                  fill=(255, 255, 255), anchor="lm")
        pill_y += pill_h + gap

    img.save(OUT)
    print("Saved:", OUT, img.size)


if __name__ == "__main__":
    main()
