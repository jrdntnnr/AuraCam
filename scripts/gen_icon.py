#!/usr/bin/env python3
"""Draw the AuraCam launcher icon: HUD frame brackets around a diamond.

    uv run --with pillow python scripts/gen_icon.py cardputer/auracam.png

  +--          --+
  |              |
         /\               brackets   tactical HUD frame marks
         \/               diamond    centred outline, the HUD's H marker
  |              |
  +--          --+
"""

from __future__ import annotations

import sys

from PIL import Image, ImageDraw

SIZE = 100
SUPERSAMPLE = 4
AMBER = (255, 194, 0)  # HUD amber palette, 0xFFC200
CLEAR = (0, 0, 0, 0)

# Geometry in final pixels; the launcher's icons keep ~12 px of margin.
FRAME = (12, 14, 88, 86)
BRACKET_ARM = 18
BRACKET_WIDTH = 6
CENTER = (50, 50)
DIAMOND_RADIUS = 19
DIAMOND_WIDTH = 6


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


def rhombus(radius: float) -> list[tuple[int, int]]:
    cx, cy = CENTER
    return [
        (scaled(cx), scaled(cy - radius)),
        (scaled(cx + radius), scaled(cy)),
        (scaled(cx), scaled(cy + radius)),
        (scaled(cx - radius), scaled(cy)),
    ]


def diamond(draw: ImageDraw.ImageDraw) -> None:
    """Outlined diamond: a filled rhombus with a smaller one cleared out.

    The inset is the stroke measured across the 45 degree edges, so the
    outline is DIAMOND_WIDTH thick like the brackets."""
    draw.polygon(rhombus(DIAMOND_RADIUS), AMBER + (255,))
    draw.polygon(rhombus(DIAMOND_RADIUS - DIAMOND_WIDTH * 2**0.5), CLEAR)


def main() -> None:
    image = Image.new("RGBA", (scaled(SIZE), scaled(SIZE)))
    draw = ImageDraw.Draw(image)
    brackets(draw)
    diamond(draw)
    image.resize((SIZE, SIZE), Image.LANCZOS).save(sys.argv[1])


if __name__ == "__main__":
    main()
