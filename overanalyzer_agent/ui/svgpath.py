"""A minimal SVG path flattener - enough of the spec to draw lucide icons.

lucide ships every glyph as a 24x24 SVG of ``<path>``/``<circle>``/``<rect>``/
``<line>`` elements stroked at 2px with round caps and joins. Rather than
redrawing the glyphs by hand (which would be lucide-ish art, not lucide art) or
adding a full SVG renderer as a dependency, this module parses the path grammar
lucide actually uses and flattens it to polylines that Pillow can stroke.

Supported: ``M m L l H h V v C c S s Q q T t A a Z z`` - the whole set that
appears across lucide's icon library. Output is in the SVG user space of the
source (24x24 for lucide); callers scale.
"""
from __future__ import annotations

import math
import re

Point = tuple[float, float]
SubPath = list[Point]

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")

# Segments per curve. 16 is invisibly smooth at the sizes icons render at
# (12-24px) even with the 4x supersample the renderer uses.
CURVE_STEPS = 16


def _tokenize(d: str) -> list[str]:
    return _TOKEN.findall(d)


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, steps: int) -> list[Point]:
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0]
        y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
        out.append((x, y))
    return out


def _arc(p0: Point, rx: float, ry: float, rot: float, large: int, sweep: int, p1: Point,
         steps: int) -> list[Point]:
    """Endpoint-parameterised elliptical arc -> polyline (SVG F.6.5)."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(rot)
    cos_p, sin_p = math.cos(phi), math.sin(phi)

    dx2, dy2 = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2

    # Scale the radii up if they can't span the chord (SVG F.6.6).
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx, ry = rx * scale, ry * scale

    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) * (-1 if large == sweep else 1)
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (p0[0] + p1[0]) / 2
    cy = sin_p * cxp + cos_p * cyp + (p0[1] + p1[1]) / 2

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        det = ux * vy - uy * vx
        return math.atan2(det, dot)

    theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi

    out = []
    for i in range(1, steps + 1):
        t = theta1 + delta * (i / steps)
        x = cx + rx * math.cos(t) * cos_p - ry * math.sin(t) * sin_p
        y = cy + rx * math.cos(t) * sin_p + ry * math.sin(t) * cos_p
        out.append((x, y))
    return out


def flatten_path(d: str, steps: int = CURVE_STEPS) -> list[SubPath]:
    """Flatten an SVG ``d`` attribute into a list of polylines.

    A closed subpath (``Z``) comes back with its first point repeated at the end,
    so a caller stroking the polyline draws the closing segment too.
    """
    tokens = _tokenize(d)
    i = 0
    subpaths: list[SubPath] = []
    current: SubPath = []
    cursor: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    prev_ctrl: Point | None = None
    prev_quad: Point | None = None
    command = ""

    def num() -> float:
        nonlocal i
        value = float(tokens[i])
        i += 1
        return value

    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            if command in "Zz":
                if current:
                    current.append(start)
                    subpaths.append(current)
                    current = []
                cursor = start
                prev_ctrl = prev_quad = None
                continue
        elif command in ("M", "m"):
            command = "L" if command == "M" else "l"  # implicit lineto after moveto

        rel = command.islower()
        cmd = command.upper()

        if cmd == "M":
            x, y = num(), num()
            cursor = (cursor[0] + x, cursor[1] + y) if rel else (x, y)
            if current:
                subpaths.append(current)
            current = [cursor]
            start = cursor
            prev_ctrl = prev_quad = None
        elif cmd in ("L", "H", "V"):
            if cmd == "L":
                x, y = num(), num()
                cursor = (cursor[0] + x, cursor[1] + y) if rel else (x, y)
            elif cmd == "H":
                x = num()
                cursor = (cursor[0] + x, cursor[1]) if rel else (x, cursor[1])
            else:
                y = num()
                cursor = (cursor[0], cursor[1] + y) if rel else (cursor[0], y)
            current.append(cursor)
            prev_ctrl = prev_quad = None
        elif cmd in ("C", "S"):
            if cmd == "C":
                c1 = (num(), num())
                if rel:
                    c1 = (cursor[0] + c1[0], cursor[1] + c1[1])
            else:  # smooth: reflect the previous control point
                c1 = cursor if prev_ctrl is None else (
                    2 * cursor[0] - prev_ctrl[0], 2 * cursor[1] - prev_ctrl[1]
                )
            c2 = (num(), num())
            end = (num(), num())
            if rel:
                c2 = (cursor[0] + c2[0], cursor[1] + c2[1])
                end = (cursor[0] + end[0], cursor[1] + end[1])
            current.extend(_cubic(cursor, c1, c2, end, steps))
            cursor, prev_ctrl, prev_quad = end, c2, None
        elif cmd in ("Q", "T"):
            if cmd == "Q":
                q = (num(), num())
                if rel:
                    q = (cursor[0] + q[0], cursor[1] + q[1])
            else:
                q = cursor if prev_quad is None else (
                    2 * cursor[0] - prev_quad[0], 2 * cursor[1] - prev_quad[1]
                )
            end = (num(), num())
            if rel:
                end = (cursor[0] + end[0], cursor[1] + end[1])
            # A quadratic is a cubic with the control points at 2/3 of the way.
            c1 = (cursor[0] + 2 / 3 * (q[0] - cursor[0]), cursor[1] + 2 / 3 * (q[1] - cursor[1]))
            c2 = (end[0] + 2 / 3 * (q[0] - end[0]), end[1] + 2 / 3 * (q[1] - end[1]))
            current.extend(_cubic(cursor, c1, c2, end, steps))
            cursor, prev_quad, prev_ctrl = end, q, None
        elif cmd == "A":
            rx, ry, rot, large, sweep = num(), num(), num(), int(num()), int(num())
            end = (num(), num())
            if rel:
                end = (cursor[0] + end[0], cursor[1] + end[1])
            current.extend(_arc(cursor, rx, ry, rot, large, sweep, end, steps))
            cursor, prev_ctrl, prev_quad = end, None, None
        else:  # unknown command: bail rather than loop forever
            i += 1

    if current:
        subpaths.append(current)
    return subpaths
