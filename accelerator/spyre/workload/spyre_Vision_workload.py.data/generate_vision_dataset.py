#!/usr/bin/env python
"""
Generate the sample vision images used by spyre_Vision_workload.py.

The images are small (384x384, the native granite-vision / SigLIP tile size so
each image maps to a single tile), deterministic and contain simple content
whose correct answer is unambiguous: text, shapes, colors, counting, a bar
chart, an invoice, a table, a traffic light and an arrow.

Usage (requires Pillow, only needed to regenerate the images):
    python3 generate_vision_dataset.py [output_dir]

The prompts that reference these images live in ``vision_prompts.json``.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

SIZE = 384
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
]


def font(size):
    """Return a bold TrueType font if available, otherwise Pillow's default."""
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def canvas(bg="white"):
    img = Image.new("RGB", (SIZE, SIZE), bg)
    return img, ImageDraw.Draw(img)


def centered(draw, xy_center, text, fnt, fill="black"):
    draw.text(xy_center, text, font=fnt, fill=fill, anchor="mm")


def text_spyre():
    img, d = canvas()
    centered(d, (SIZE // 2, SIZE // 2 - 30), "SPYRE", font(90), "navy")
    centered(d, (SIZE // 2, SIZE // 2 + 60), "AIU", font(90), "navy")
    return img


def text_hello_world():
    img, d = canvas("lightyellow")
    centered(d, (SIZE // 2, SIZE // 2 - 40), "Hello", font(80))
    centered(d, (SIZE // 2, SIZE // 2 + 50), "World", font(80))
    return img


def shape_red_circle():
    img, d = canvas()
    d.ellipse((72, 72, 312, 312), fill="red")
    return img


def shape_blue_square():
    img, d = canvas()
    d.rectangle((92, 92, 292, 292), fill="blue")
    return img


def count_triangles():
    img, d = canvas()
    for cx in (80, 192, 304):
        d.polygon([(cx, 130), (cx - 50, 250), (cx + 50, 250)], fill="green")
    return img


def count_stars():
    img, d = canvas()
    import math
    for cx, cy in ((100, 110), (284, 110), (100, 280), (284, 280), (192, 195)):
        pts = []
        for i in range(10):
            r = 48 if i % 2 == 0 else 20
            a = math.pi / 2 + i * math.pi / 5
            pts.append((cx + r * math.cos(a), cy - r * math.sin(a)))
        d.polygon(pts, fill="orange")
    return img


def bar_chart():
    img, d = canvas()
    centered(d, (SIZE // 2, 28), "Fruit Sales", font(30))
    bars = [("Apples", 90, "tomato"), ("Oranges", 150, "orange"), ("Bananas", 250, "gold")]
    base = 330
    for i, (label, h, color) in enumerate(bars):
        x0 = 40 + i * 110
        d.rectangle((x0, base - h, x0 + 90, base), fill=color, outline="black", width=2)
        centered(d, (x0 + 45, base + 20), label, font(18))
    d.line((30, base, 360, base), fill="black", width=2)
    return img


def invoice():
    img, d = canvas()
    d.rectangle((10, 10, SIZE - 10, SIZE - 10), outline="black", width=3)
    centered(d, (SIZE // 2, 50), "INVOICE", font(48))
    d.text((30, 110), "Number: 1042", font=font(34), fill="black")
    d.text((30, 170), "Date: 2026-03-15", font=font(30), fill="black")
    d.text((30, 230), "Customer: ACME", font=font(30), fill="black")
    d.line((30, 285, SIZE - 30, 285), fill="black", width=2)
    d.text((30, 305), "Total: $250", font=font(40), fill="darkred")
    return img


def score_table():
    img, d = canvas()
    rows = [("Name", "Score"), ("Alice", "92"), ("Bob", "87"), ("Carol", "75")]
    fnt = font(38)
    for r, (name, score) in enumerate(rows):
        y0 = 40 + r * 75
        d.rectangle((30, y0, 354, y0 + 75), outline="black", width=3,
                    fill="lightgray" if r == 0 else "white")
        d.line((200, y0, 200, y0 + 75), fill="black", width=3)
        centered(d, (115, y0 + 38), name, fnt)
        centered(d, (277, y0 + 38), score, fnt)
    return img


def traffic_light():
    img, d = canvas("white")
    d.rectangle((132, 30, 252, 354), fill="dimgray", outline="black", width=3)
    colors = [("red", "red"), ("gray", "yellow"), ("gray", "green")]
    for i, (fill, _) in enumerate(colors):
        cy = 90 + i * 100
        d.ellipse((152, cy - 40, 232, cy + 40), fill=fill, outline="black", width=2)
    return img


def flag_stripes():
    img, d = canvas()
    for i, color in enumerate(("red", "white", "blue")):
        d.rectangle((0, i * 128, SIZE, (i + 1) * 128), fill=color)
    d.rectangle((0, 0, SIZE - 1, SIZE - 1), outline="black", width=2)
    return img


def arrow_right():
    img, d = canvas()
    d.rectangle((50, 160, 220, 224), fill="black")
    d.polygon([(220, 100), (340, 192), (220, 284)], fill="black")
    return img


def stop_sign():
    import math
    img, d = canvas()
    pts = [(192 + 170 * math.cos(math.radians(22.5 + 45 * i)),
            192 + 170 * math.sin(math.radians(22.5 + 45 * i))) for i in range(8)]
    d.polygon(pts, fill="red", outline="white")
    centered(d, (192, 192), "STOP", font(90), "white")
    return img


IMAGES = {
    "text_spyre.png": text_spyre,
    "text_hello_world.png": text_hello_world,
    "shape_red_circle.png": shape_red_circle,
    "shape_blue_square.png": shape_blue_square,
    "count_triangles.png": count_triangles,
    "count_stars.png": count_stars,
    "bar_chart.png": bar_chart,
    "invoice.png": invoice,
    "score_table.png": score_table,
    "traffic_light.png": traffic_light,
    "flag_stripes.png": flag_stripes,
    "arrow_right.png": arrow_right,
    "stop_sign.png": stop_sign,
}


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "images")
    os.makedirs(out_dir, exist_ok=True)
    for name, fn in IMAGES.items():
        path = os.path.join(out_dir, name)
        fn().save(path, optimize=True)
        print(f"wrote {path} ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    main()
