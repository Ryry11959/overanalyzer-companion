"""Design tokens, ported from the OverAnalyzer design system.

The source of truth is the web app's token set (``frontend/src/app/globals.css``,
mirrored in the design system's ``tokens/*.css``). Values are transcribed here as
resolved hex because Tk has no CSS variables - and no alpha, which is why
:func:`over` exists: every ``hsl(... / 0.06)`` fill in the design gets flattened
against the surface it sits on.

Pure module: no Tk, no I/O. See shared design tokens for the rules these encode.
"""
from __future__ import annotations

import colorsys


def hsl(h: float, s: float, lightness: float) -> str:
    """CSS ``hsl(h s% l%)`` as a Tk ``#rrggbb`` string."""
    r, g, b = colorsys.hls_to_rgb(h / 360.0, lightness / 100.0, s / 100.0)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def rgb(color: str) -> tuple[int, int, int]:
    """``#rrggbb`` -> an (r, g, b) tuple."""
    value = color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def over(fg: str, bg: str, alpha: float) -> str:
    """Flatten ``fg`` at ``alpha`` over an opaque ``bg``.

    Tk widgets are opaque, so a translucent design value (the amber paused
    banner's ``hsl(45 93% 58% / 0.06)``, a hover tint, a border at 30%) has to be
    resolved against whatever is behind it at authoring time.
    """
    fr, fg_, fb = rgb(fg)
    br, bg_, bb = rgb(bg)
    mix = lambda f, b: round(f * alpha + b * (1 - alpha))  # noqa: E731
    return "#{:02x}{:02x}{:02x}".format(mix(fr, br), mix(fg_, bg_), mix(fb, bb))


def shift(color: str, delta: float) -> str:
    """Lighten (``delta`` > 0) or darken a colour by a lightness delta in %.

    Hover states in this design are a *lightness* shift, never a hue change.
    """
    r, g, b = (c / 255 for c in rgb(color))
    h, lightness, s = colorsys.rgb_to_hls(r, g, b)
    return hsl(h * 360, s * 100, max(0.0, min(100.0, lightness * 100 + delta)))


# --- surfaces -------------------------------------------------------------
PAGE = hsl(248, 28, 8)  # --background
CARD = hsl(248, 26, 11)  # --card / --popover
SIDEBAR = hsl(248, 30, 7)  # --sidebar-background, the title bar
MUTED = hsl(248, 20, 16)
ACCENT = hsl(248, 20, 17)  # hover fill for ghost/outline controls
SECONDARY = hsl(248, 20, 17)
INPUT_BG = hsl(248, 20, 19)

# --- text -----------------------------------------------------------------
TEXT = hsl(250, 25, 96)  # --foreground
TEXT_MUTED = hsl(250, 14, 66)  # --muted-foreground
TEXT_ON_PRIMARY = "#ffffff"

# --- lines + interactive --------------------------------------------------
BORDER = hsl(248, 20, 17)
PRIMARY = hsl(250, 84, 67)
PRIMARY_HOVER = shift(PRIMARY, -5)  # primary/90
RING = PRIMARY

# --- data colours (the only sanctioned non-neutrals) ----------------------
WIN = "#34d399"
LOSS = "#fb7185"
DRAW = "#fbbf24"
ROLE = {"tank": "#60a5fa", "damage": "#f87171", "support": "#4ade80"}
TEAM_BLUE = "#01b8f6"
BRAND = "#ff7a29"
UNRELIABLE = hsl(248, 15, 38)

# --- derived fills used by more than one widget ---------------------------
ACCENT_ON_SIDEBAR = over(ACCENT, SIDEBAR, 1.0)
PAUSED_BG = over(DRAW, PAGE, 0.06)  # hsl(45 93% 58% / 0.06)
PAUSED_BORDER = over(DRAW, PAGE, 0.30)
DANGER_HOVER = over(hsl(0, 62.8, 50.6), SIDEBAR, 0.15)
SECONDARY_HOVER = shift(SECONDARY, 4)
CARD_HOVER = over(MUTED, CARD, 0.5)

# --- geometry -------------------------------------------------------------
# Radii are small on purpose: 6px reads "tool", large radii read "AI slop".
RADIUS = 6
RADIUS_MD = 4
RADIUS_SM = 2
PILL = 999

# 4px base, 8px rhythm. Only these steps appear in product code.
SPACE = (4, 8, 12, 16, 24, 32)

# --- type scale (px) ------------------------------------------------------
TEXT_2XS = 10  # uppercase micro-labels
TEXT_11 = 11  # dense meta rows
TEXT_XS = 12  # labels, captions
TEXT_SM = 14  # body + dense data (the default)
TEXT_LG = 18
TEXT_2XL = 24  # KPI numerals

WEIGHT_NORMAL = "normal"
WEIGHT_BOLD = "bold"

# --- window ---------------------------------------------------------------
# 1A: a 360x540 overlay panel, always on top.
PANEL_WIDTH = 360
PANEL_HEIGHT = 540
