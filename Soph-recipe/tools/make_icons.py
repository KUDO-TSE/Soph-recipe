"""Regenerate static/icon-192.png and static/icon-512.png.

Run with: python tools/make_icons.py
"""

import os

from PIL import Image, ImageDraw

INK = (22, 38, 30)
MILK = (242, 245, 241)
TOMATO = (226, 62, 46)
YOLK = (255, 194, 51)
PISTACHIO = (168, 200, 154)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def draw(size):
    s = size * 4  # supersample, then downscale for clean edges
    img = Image.new("RGB", (s, s), YOLK)
    d = ImageDraw.Draw(img)
    u = s / 100.0
    line = max(2, int(3.2 * u))

    # steam
    for x in (34, 50, 66):
        d.arc(
            [int((x - 9) * u), int(11 * u), int((x + 9) * u), int(33 * u)],
            start=200, end=340, fill=INK, width=line,
        )

    # pot body
    d.rounded_rectangle(
        [int(19 * u), int(40 * u), int(81 * u), int(80 * u)],
        radius=int(14 * u), fill=TOMATO, outline=INK, width=line,
    )
    # broth line
    d.line([int(24 * u), int(52 * u), int(76 * u), int(52 * u)], fill=INK, width=line)
    d.rectangle([int(23 * u), int(41 * u), int(77 * u), int(51 * u)], fill=PISTACHIO)
    d.rounded_rectangle(
        [int(19 * u), int(40 * u), int(81 * u), int(80 * u)],
        radius=int(14 * u), outline=INK, width=line,
    )
    # lid
    d.rounded_rectangle(
        [int(14 * u), int(31 * u), int(86 * u), int(42 * u)],
        radius=int(5 * u), fill=MILK, outline=INK, width=line,
    )
    d.ellipse(
        [int(45 * u), int(23 * u), int(55 * u), int(33 * u)],
        fill=YOLK, outline=INK, width=line,
    )

    return img.resize((size, size), Image.LANCZOS)


for px in (192, 512):
    draw(px).save(os.path.join(OUT, f"icon-{px}.png"), optimize=True)
    print(f"wrote icon-{px}.png")
