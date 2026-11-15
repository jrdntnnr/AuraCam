#!/usr/bin/env python3
"""Draw the AuraCam launcher icon: HUD viewfinder brackets around a heat aura.

    uv run --with pillow python scripts/gen_icon.py cardputer/auracam.png

  +--            --+
  |     .----.     |      brackets   tactical HUD frame marks
        ( (  +  ) )       rings      thermal aura, fading outward
  |     '----'     |      core       probe point
  +--            --+
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
RINGS = ((30, 3, 90), (23, 4, 160), (16, 5, 235))  # radius, width, alpha
CORE_RADIUS = 7
TICK = (32, 37, 4)  # inner radius, outer radius, width


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


def aura(image: Image.Image) -> None:
    cx, cy = CENTER
    for radius, width, alpha in RINGS:
        layer = Image.new("RGBA", image.size)
        ImageDraw.Draw(layer).ellipse(
            [scaled(cx - radius), scaled(cy - radius), scaled(cx + radius), scaled(cy + radius)],
            outline=AMBER + (alpha,),
            width=scaled(width),
        )
        image.alpha_composite(layer)
    draw = ImageDraw.Draw(image)
    draw.ellipse([scaled(cx - CORE_RADIUS), scaled(cy - CORE_RADIUS), scaled(cx + CORE_RADIUS), scaled(cy + CORE_RADIUS)], AMBER + (255,))
    inner, outer, width = TICK
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        draw.line([(scaled(cx + dx * inner), scaled(cy + dy * inner)), (scaled(cx + dx * outer), scaled(cy + dy * outer))], AMBER + (255,), scaled(width))


def main() -> None:
    image = Image.new("RGBA", (scaled(SIZE), scaled(SIZE)))
    brackets(ImageDraw.Draw(image))
    aura(image)
    image.resize((SIZE, SIZE), Image.LANCZOS).save(sys.argv[1])


if __name__ == "__main__":
    main()
