"""The OverAnalyzer app icon.

Vendored from ``frontend/public/brand/app-icon.svg`` - three flat-filled paths,
drawn back to front, no holes or masking. That's simple enough to rasterise with
the same machinery :mod:`icons` uses for lucide glyphs (flatten with
:mod:`svgpath`, fill the polygon, supersample) rather than pulling in an SVG
library for one three-shape asset.
"""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw

from overanalyzer_agent.ui.svgpath import flatten_path

VIEWBOX = 1024.0
SUPERSAMPLE = 4

# (fill, path d), in paint order - verbatim from frontend/public/brand/app-icon.svg.
SHAPES: list[tuple[str, str]] = [
    ("#FE7B2A",
     "M492.127 326.711C498.167 325.806 511.78 326.502 518.315 326.505L567.552 326.504"
     "L610.963 326.493C630.927 326.441 648.893 324.3 665.901 337.119C689.7 355.055 "
     "687.558 376.749 687.57 403.946L687.569 449.638L687.554 498.805C687.544 514.561 "
     "687.761 528.038 686.019 543.76C682.363 575.773 669.921 606.151 650.07 631.531"
     "C620.207 669.707 578.376 691.581 530.681 697.342L529.39 697.453C480.183 701.478 "
     "435.102 687.606 397.447 655.563C362.526 625.618 341.03 582.954 337.745 537.07"
     "C335.791 512.296 335.752 482.161 337.835 457.307C339.97 431.836 354.993 402.293 "
     "371.517 382.69C403.714 344.492 443.756 330.147 492.127 326.711Z"),
    ("#16243B",
     "M489.361 387.008L536.565 386.967C541.167 396.129 545.584 407.247 549.634 416.802"
     "L568.902 461.991C590.441 511.807 611.604 561.784 632.39 611.919C613.773 611.942 "
     "591.766 612.484 573.377 611.768L520.487 489.369C518.145 484.163 515.728 478.992 "
     "513.237 473.856C506.606 485.659 499.673 503.438 494.121 516.254L470.341 571.102"
     "C464.482 584.737 458.815 598.521 452.527 611.953L392.968 611.989C403.701 585.372 "
     "416.136 557.73 427.436 531.236C447.653 482.979 468.296 434.901 489.361 387.008Z"),
    ("#16243B",
     "M512.626 505.259C516.615 509.07 556.038 603.127 560.42 613.553C549.795 607.865 "
     "537.608 598.155 527.185 591.592C523.233 589.103 517.393 584.718 513.214 582.936"
     "C498.459 591.269 480.018 604.823 465.379 614.383C471.065 598.022 479.446 581.054 "
     "486.289 565.116C494.911 545.035 503.453 525.101 512.626 505.259Z"),
]


def _shapes() -> list[tuple[str, list[list[tuple[float, float]]]]]:
    return [(fill, flatten_path(d)) for fill, d in SHAPES]


def _bbox(shapes: list[tuple[str, list[list[tuple[float, float]]]]],
         margin: float = 0.08) -> tuple[float, float, float]:
    """A square (x, y, side) crop around the artwork, not the full padded viewBox.

    The source SVG's viewBox has a lot of dead space around the mark (it was
    made for an app-store safe area); a taskbar/tray icon needs the glyph to
    actually fill the frame at 16-32px, so this crops to the shapes' own
    bounding box plus a small margin instead of rendering the whole 1024x1024.
    """
    xs = [x for _, subs in shapes for sub in subs for x, _ in sub]
    ys = [y for _, subs in shapes for sub in subs for _, y in sub]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    side = max(x1 - x0, y1 - y0) * (1 + margin * 2)
    return x0 - (side - (x1 - x0)) / 2, y0 - (side - (y1 - y0)) / 2, side


def render(size: int = 256) -> Image.Image:
    """Rasterise the app icon at ``size`` x ``size``, transparent background."""
    shapes = _shapes()
    ox, oy, side = _bbox(shapes)
    scale = size * SUPERSAMPLE / side
    big = size * SUPERSAMPLE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for fill, subs in shapes:
        for sub in subs:
            draw.polygon([((x - ox) * scale, (y - oy) * scale) for x, y in sub], fill=fill)
    return image.resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=8)
def icon(size: int = 256) -> Image.Image:
    """Cached :func:`render` - the icon is reused across the window and tray."""
    return render(size)
