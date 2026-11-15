#!/usr/bin/env python3
"""Draw the AuraCam launcher icon: HUD frame brackets around a chevron.

    uv run --with pillow python scripts/gen_icon.py cardputer/auracam.png

  +--          --+
  |              |
         /\               brackets   tactical HUD frame marks
        /  \              chevron    centred, pointing up
  |              |
  +--          --+
"""

from __future__ import annotations

import sys

from PIL import Image, ImageDraw

SIZE = 100
SUPERSAMPLE = 4
AMBER = (255, 194, 0)  # HUD amber palette, 0xFFC200

# Geometry in final pixels; the launcher's icons keep ~12 px of margin.
FRAME = (12, 14, 88, 86)
BRACKET_ARM = 18
BRACKET_WIDTH = 6
CENTER = (50, 50)
CHEVRON_HALF_WIDTH = 17
CHEVRON_HEIGHT = 17
CHEVRON_WIDTH = 7


def scaled(value: float) -> int:
    return round(value * SUPERSAMPLE)


def brackets(draw: ImageDraw.ImageDraw) -> None:
    """Four L-shaped corner marks, each two filled bars sharing the corner."""
    left, top, right, bottom = FRAME
    arm, width = BRACKET_ARM, BRACKET_WIDTH
    for x, y, dx, dy in ((left, top, 1, 1), (right, top, -1, 1), (left, bottom, 1, -1), (right, bottom, -1, -1)):
        for bar_w, bar_h in ((arm, width), (width, arm)):
            x1, y1 = x + dx * bar_w, y + dy * bar_h
            box = [scaled(min(x, x1)), scaled(min(y, y1)), scaled(max(x, x1)), scaled(max(y, y1))]
            draw.rectangle(box, AMBER + (255,))


def chevron(draw: ImageDraw.ImageDraw) -> None:
    """Upward chevron centred in the frame, drawn as one mitred stroke."""
    cx, cy = CENTER
    top = cy - CHEVRON_HEIGHT / 2
    bottom = cy + CHEVRON_HEIGHT / 2
    points = [
        (scaled(cx - CHEVRON_HALF_WIDTH), scaled(bottom)),
        (scaled(cx), scaled(top)),
        (scaled(cx + CHEVRON_HALF_WIDTH), scaled(bottom)),
    ]
    draw.line(points, AMBER + (255,), scaled(CHEVRON_WIDTH), joint="curve")


def main() -> None:
    image = Image.new("RGBA", (scaled(SIZE), scaled(SIZE)))
    draw = ImageDraw.Draw(image)
    brackets(draw)
    chevron(draw)
    image.resize((SIZE, SIZE), Image.LANCZOS).save(sys.argv[1])


if __name__ == "__main__":
    main()
