"""lucide glyphs, rendered with Pillow.

The web app uses ``lucide-react``; the design system uses the same icons from a
CDN. Neither is reachable from a Tk app, so the shape data for the glyphs this
UI needs is embedded verbatim from lucide's own SVG sources (ISC licensed) and
stroked here through :mod:`svgpath`. Same art, different rasteriser.

Everything is drawn on a 24x24 grid at 2px stroke with round caps and joins -
lucide's own geometry - supersampled 4x and downscaled, which is what keeps a
16px glyph from looking like it was drawn with a brick.
"""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw

from overanalyzer_agent.ui.svgpath import flatten_path

VIEWBOX = 24.0
STROKE = 2.0
SUPERSAMPLE = 4

Shape = tuple  # ("path", d) | ("circle", cx, cy, r) | ("rect", x, y, w, h, rx)

# Verbatim from lucide (github.com/lucide-icons/lucide, ISC). Keep these in sync
# with the icon names the design references rather than inventing new glyphs.
LUCIDE: dict[str, list[Shape]] = {
    "settings": [
        ("path", "M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 "
                 "2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 "
                 "1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 "
                 "2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"),
        ("circle", 12, 12, 3),
    ],
    "power": [
        ("path", "M12 2v10"),
        ("path", "M18.4 6.6a9 9 0 1 1-12.77.04"),
    ],
    "chevron-left": [("path", "m15 18-6-6 6-6")],
    "chevron-right": [("path", "m9 18 6-6-6-6")],
    "equal": [("path", "M5 9h14"), ("path", "M5 15h14")],
    "chevron-down": [("path", "m6 9 6 6 6-6")],
    "chevron-up": [("path", "m18 15-6-6-6 6")],
    "image-up": [
        ("path", "M10.3 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10l-3.1-3.1a2 2 0 0 "
                 "0-2.814.014L6 21"),
        ("path", "m14 19.5 3-3 3 3"),
        ("path", "M17 22v-5.5"),
        ("circle", 9, 9, 2),
    ],
    "upload": [
        ("path", "M12 3v12"),
        ("path", "m17 8-5-5-5 5"),
        ("path", "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"),
    ],
    "pause": [("rect", 14, 3, 5, 18, 1), ("rect", 5, 3, 5, 18, 1)],
    "play": [
        ("path", "M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"),
    ],
    "circle-check-big": [
        ("path", "M21.801 10A10 10 0 1 1 17 3.335"),
        ("path", "m9 11 3 3L22 4"),
    ],
    "triangle-alert": [
        ("path", "m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"),
        ("path", "M12 9v4"),
        ("path", "M12 17h.01"),
    ],
    "wifi-off": [
        ("path", "M12 20h.01"),
        ("path", "M8.5 16.429a5 5 0 0 1 7 0"),
        ("path", "M5 12.859a10 10 0 0 1 5.17-2.69"),
        ("path", "M19 12.859a10 10 0 0 0-2.007-1.523"),
        ("path", "M2 8.82a15 15 0 0 1 4.177-2.643"),
        ("path", "M22 8.82a15 15 0 0 0-11.288-3.764"),
        ("path", "m2 2 20 20"),
    ],
    "loader-circle": [("path", "M21 12a9 9 0 1 1-6.219-8.56")],
    "x": [("path", "M18 6 6 18"), ("path", "m6 6 12 12")],
    "arrow-up-right": [("path", "M7 7h10v10"), ("path", "M7 17 17 7")],
    "refresh-cw": [
        ("path", "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"),
        ("path", "M21 3v5h-5"),
        ("path", "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"),
        ("path", "M8 16H3v5"),
    ],
}


def _rect_path(x: float, y: float, w: float, h: float, r: float) -> str:
    """A rounded rect as path data, so rects flatten through the same code."""
    r = min(r, w / 2, h / 2)
    return (
        f"M{x + r} {y} H{x + w - r} A{r} {r} 0 0 1 {x + w} {y + r} "
        f"V{y + h - r} A{r} {r} 0 0 1 {x + w - r} {y + h} "
        f"H{x + r} A{r} {r} 0 0 1 {x} {y + h - r} "
        f"V{y + r} A{r} {r} 0 0 1 {x + r} {y} Z"
    )


def _circle_path(cx: float, cy: float, r: float) -> str:
    return (
        f"M{cx - r} {cy} A{r} {r} 0 0 1 {cx + r} {cy} A{r} {r} 0 0 1 {cx - r} {cy} Z"
    )


def polylines(name: str) -> list[list[tuple[float, float]]]:
    """The glyph as flattened polylines in the 24x24 viewbox. Pure + testable."""
    shapes = LUCIDE.get(name)
    if shapes is None:
        raise KeyError(f"unknown icon {name!r}; add its lucide source to LUCIDE")
    out: list[list[tuple[float, float]]] = []
    for shape in shapes:
        kind = shape[0]
        if kind == "path":
            out.extend(flatten_path(shape[1]))
        elif kind == "circle":
            out.extend(flatten_path(_circle_path(*shape[1:])))
        elif kind == "rect":
            out.extend(flatten_path(_rect_path(*shape[1:])))
        else:  # pragma: no cover - guarded by the literal table above
            raise ValueError(f"unsupported shape {kind!r}")
    return out


def render(name: str, size: int = 16, color: str = "#ffffff") -> Image.Image:
    """Render a glyph to an RGBA image of ``size`` x ``size`` in ``color``."""
    scale = size * SUPERSAMPLE / VIEWBOX
    big = size * SUPERSAMPLE
    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)
    width = max(1, round(STROKE * scale))
    cap = width / 2

    for line in polylines(name):
        points = [(x * scale, y * scale) for x, y in line]
        if len(points) == 1:
            # lucide draws dots as a zero-length segment ("M12 20h.01").
            points = points * 2
        draw.line(points, fill=255, width=width, joint="curve")
        for x, y in (points[0], points[-1]):  # round caps
            draw.ellipse((x - cap, y - cap, x + cap, y + cap), fill=255)

    mask = mask.resize((size, size), Image.LANCZOS)
    image = Image.new("RGBA", (size, size), color)
    image.putalpha(mask)
    return image


@lru_cache(maxsize=256)
def icon(name: str, size: int = 16, color: str = "#ffffff") -> Image.Image:
    """Cached :func:`render` - the same glyph is reused across many widgets."""
    return render(name, size, color)
