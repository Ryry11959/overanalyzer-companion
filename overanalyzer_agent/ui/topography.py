"""The topographic contour backdrop, ported from the design system's topography.js.

A value-noise height field is contoured with marching squares into a stack of
thin indigo isolines; every third line is a heavier "index contour", as on a real
map. Drawn at 7-16% alpha, so it reads as texture rather than decoration.

**Static by owner decision.** The web version drifts over time and bunches its
contours around the pointer; the companion app deliberately does not. It sits on
top of a game, and a backdrop that repaints is CPU you didn't ask it to spend.
The field is rendered once per window size and then left alone.

Rendered to a Pillow image (Tk canvases stroke thousands of short segments far
too slowly). Pure apart from the drawing: :func:`field` and
:func:`contour_segments` are testable without a display.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw

PRIMARY_RGB = (138, 105, 246)  # hsl(250 84% 67%)
CELL = 16  # px per grid cell
LEVELS = 9  # isolines
NOISE_FREQ = 0.075  # in grid units


def _fract(n: float) -> float:
    return n - math.floor(n)


def _hash(x: float, y: float) -> float:
    return _fract(math.sin(x * 127.1 + y * 311.7) * 43758.5453)


def _smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


def _noise(x: float, y: float) -> float:
    xi, yi = math.floor(x), math.floor(y)
    u, v = _smooth(x - xi), _smooth(y - yi)
    a, b = _hash(xi, yi), _hash(xi + 1, yi)
    c, d = _hash(xi, yi + 1), _hash(xi + 1, yi + 1)
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v


def fbm(x: float, y: float) -> float:
    """Three octaves of value noise - the height field's base shape."""
    return (
        _noise(x, y) * 0.6
        + _noise(x * 2.1 + 5.2, y * 2.1 + 1.3) * 0.28
        + _noise(x * 4.3 + 9.1, y * 4.3 + 7.7) * 0.12
    )


def field(cols: int, rows: int) -> list[float]:
    """The height field as a flat ``rows * cols`` list."""
    return [
        fbm(i * NOISE_FREQ, j * NOISE_FREQ)
        for j in range(rows)
        for i in range(cols)
    ]


def contour_segments(values: list[float], cols: int, rows: int, level: float) -> list[
    tuple[float, float, float, float]
]:
    """Marching squares for one threshold -> a list of (x1, y1, x2, y2)."""
    segments: list[tuple[float, float, float, float]] = []
    for j in range(rows - 1):
        for i in range(cols - 1):
            a = values[j * cols + i]
            b = values[j * cols + i + 1]
            c = values[(j + 1) * cols + i + 1]
            d = values[(j + 1) * cols + i]
            code = (8 if a > level else 0) | (4 if b > level else 0)
            code |= (2 if c > level else 0) | (1 if d > level else 0)
            if code in (0, 15):
                continue
            x, y = i * CELL, j * CELL
            lerp = lambda p, q: (level - p) / ((q - p) or 1e-6)  # noqa: E731
            top = (x + CELL * lerp(a, b), y)
            right = (x + CELL, y + CELL * lerp(b, c))
            bottom = (x + CELL * lerp(d, c), y + CELL)
            left = (x, y + CELL * lerp(a, d))
            pairs: tuple[tuple[tuple[float, float], tuple[float, float]], ...]
            if code in (1, 14):
                pairs = ((left, bottom),)
            elif code in (2, 13):
                pairs = ((bottom, right),)
            elif code in (3, 12):
                pairs = ((left, right),)
            elif code in (4, 11):
                pairs = ((top, right),)
            elif code in (6, 9):
                pairs = ((top, bottom),)
            elif code in (7, 8):
                pairs = ((left, top),)
            elif code == 5:
                pairs = ((left, top), (bottom, right))
            else:  # code == 10
                pairs = ((left, bottom), (top, right))
            for p, q in pairs:
                segments.append((p[0], p[1], q[0], q[1]))
    return segments


@dataclass
class Backdrop:
    """Renders (and caches) the contour field for one window size."""

    width: int
    height: int
    background: str

    def __post_init__(self) -> None:
        self.cols = math.ceil(self.width / CELL) + 1
        self.rows = math.ceil(self.height / CELL) + 1

    def render(self) -> Image.Image:
        values = field(self.cols, self.rows)
        image = Image.new("RGB", (self.width, self.height), self.background)
        draw = ImageDraw.Draw(image, "RGBA")
        for k in range(LEVELS):
            level = 0.24 + (k / LEVELS) * 0.62
            # Every third line is a heavier index contour, as on a real map.
            alpha = round(255 * (0.16 if k % 3 == 0 else 0.075))
            colour = (*PRIMARY_RGB, alpha)
            for x1, y1, x2, y2 in contour_segments(values, self.cols, self.rows, level):
                draw.line((x1, y1, x2, y2), fill=colour, width=1)
        return image
