"""Screen capture + leaderboard anchor detection.

A faithful, vectorized port of the geometry in ``calibrated capture geometry``:
  * the summary screen is a fixed crop of the current frame;
  * the scoreboard screen has a blue (own team) and red (enemy) leaderboard whose
    left edge + vertical extent we find by scanning for the team-bar colors.

``grab_screen`` imports ``mss`` lazily so the pure-image helpers below
(``crop_region``, ``find_leaderboard_anchor``, ``to_png_bytes``) stay testable on
a headless machine.
"""
from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image

from overanalyzer_agent.config import (
    REFERENCE_FRAME,
    REFERENCE_LEADERBOARD_WIDTH,
    REFERENCE_SUMMARY_REGION,
    AgentConfig,
    Box,
    Color,
)


# --------------------------------------------------------------------------- #
# Proportional geometry
# --------------------------------------------------------------------------- #
def ui_rect(size: tuple[int, int]) -> tuple[float, float, float]:
    """Where the game's 16:9 UI box sits in a frame. Returns (x, y, scale).

    Overwatch draws its menus into a fixed-aspect box scaled to fit the display and
    centred, so a coordinate measured on one screen maps to another by a single
    scale factor plus a centring offset. Fitting by ``min`` covers both directions:
    an ultrawide display gets side offsets, a 16:10 or 4:3 one gets top/bottom.
    """
    w, h = size
    ref_w, ref_h = REFERENCE_FRAME
    scale = min(w / ref_w, h / ref_h)
    return (w - ref_w * scale) / 2, (h - ref_h * scale) / 2, scale


def scale_box(ref_box: Box, size: tuple[int, int]) -> Box:
    """A reference-frame rectangle mapped onto a real frame."""
    x, y, scale = ui_rect(size)
    left, top, right, bottom = ref_box
    return (
        round(x + left * scale),
        round(y + top * scale),
        round(x + right * scale),
        round(y + bottom * scale),
    )


def scale_length(ref_length: int, size: tuple[int, int]) -> int:
    return max(1, round(ref_length * ui_rect(size)[2]))


def resolve_summary_region(cfg: AgentConfig, size: tuple[int, int]) -> Box:
    """The configured summary crop, or one derived for this frame."""
    return cfg.summary_region or scale_box(REFERENCE_SUMMARY_REGION, size)


def resolve_leaderboard_width(cfg: AgentConfig, size: tuple[int, int]) -> int:
    return cfg.leaderboard_width or scale_length(REFERENCE_LEADERBOARD_WIDTH, size)


def list_monitors() -> list[dict]:
    """The real monitors mss can see, as ``{index, width, height, left, top}``.

    ``index`` is 1-based and matches what :func:`grab_screen` and
    ``AgentConfig.monitor_index`` expect - mss's own index 0 (the synthetic
    bounding box of every display combined) is excluded, since it isn't
    something you'd actually want to crop a scoreboard out of.
    """
    import mss  # lazy: only needed at runtime on a real desktop

    with mss.mss() as sct:
        return [
            {"index": i, "width": m["width"], "height": m["height"],
             "left": m["left"], "top": m["top"]}
            for i, m in enumerate(sct.monitors)
            if i > 0
        ]


def grab_screen(monitor_index: int | None = None) -> Image.Image:
    """Capture one monitor as an RGB image. ``None`` (the default) is the primary."""
    import mss  # lazy: only needed at runtime on a real desktop

    with mss.mss() as sct:
        # [0] is the synthetic all-monitors bbox; [1] is the primary. An index
        # that no longer exists (a monitor got unplugged) falls back to it too.
        index = monitor_index if monitor_index and 0 < monitor_index < len(sct.monitors) else 1
        raw = sct.grab(sct.monitors[index])
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


def crop_region(img: Image.Image, box: Box) -> Image.Image:
    return img.crop(box)


def color_mask(arr: np.ndarray, colors: list[Color], tolerance: int = 0) -> np.ndarray:
    """Pixels within ``tolerance`` on every channel of any listed colour.

    Tolerance 0 is exact equality, the original behaviour.
    """
    mask = np.zeros(arr.shape[:2], dtype=bool)
    if tolerance <= 0:
        for color in colors:
            mask |= np.all(arr == np.array(color, dtype=arr.dtype), axis=-1)
        return mask
    signed = arr.astype(np.int16)
    for color in colors:
        diff = np.abs(signed - np.array(color, dtype=np.int16))
        mask |= np.all(diff <= tolerance, axis=-1)
    return mask


def find_leaderboard_anchor(
    img: Image.Image, colors: list[Color], width: int, tolerance: int = 0
) -> Box | None:
    """Find a leaderboard crop box from its team-bar color.

    Returns (left, top, left+width, bottom) spanning the matched pixels, or None
    if the color isn't present. Vectorized equivalent of the original's pixel scan.
    """
    arr = np.asarray(img.convert("RGB"))
    ys, xs = np.nonzero(color_mask(arr, colors, tolerance))
    if xs.size == 0:
        return None
    left, top, bottom = int(xs.min()), int(ys.min()), int(ys.max())
    return (left, top, left + width, bottom)


# --------------------------------------------------------------------------- #
# Team-colour discovery
# --------------------------------------------------------------------------- #
# Minimum spread between a pixel's brightest and dimmest channel for it to count as
# a team bar. The scoreboard's background, text and portraits are near-grey or very
# dark; the bars are the only large saturated blocks on the screen. Keying on
# saturation rather than on hue is the whole point - it finds the bars whatever
# colour the player's colourblind palette makes them.
_BAR_SATURATION = 40
_BAR_MIN_BRIGHTNESS = 60


def detect_team_colors(
    img: Image.Image, min_pixels: int = 500
) -> tuple[list[Color], list[Color]]:
    """Sample the two team-bar colours off a scoreboard frame, top team first.

    Returns ``(team1_colors, team2_colors)`` - empty lists when the frame doesn't
    look like a scoreboard. The two blocks are told apart by vertical position
    rather than by hue, because with Overwatch's colourblind options the top block is not
    necessarily blue and the bottom one not necessarily red.
    """
    arr = np.asarray(img.convert("RGB"))
    high = arr.max(axis=-1).astype(np.int16)
    low = arr.min(axis=-1).astype(np.int16)
    saturated = ((high - low) >= _BAR_SATURATION) & (high >= _BAR_MIN_BRIGHTNESS)
    if not saturated.any():
        return [], []

    px = arr[saturated]
    colors, counts = np.unique(px.reshape(-1, 3), axis=0, return_counts=True)
    order = np.argsort(counts)[::-1]

    # Walk candidates most-common first, keeping the two that are far enough apart in
    # colour to be different teams rather than two shades of the same bar (the
    # highlighted row of a leaderboard is its own near-identical shade).
    picked: list[tuple[Color, float]] = []
    for i in order:
        if counts[i] < min_pixels:
            break
        color = tuple(int(c) for c in colors[i])
        if any(max(abs(a - b) for a, b in zip(color, seen)) < 60 for seen, _ in picked):
            continue
        ys = np.nonzero(color_mask(arr, [color], tolerance=0).any(axis=1))[0]
        picked.append((color, float(ys.mean())))
        if len(picked) == 2:
            break
    if len(picked) < 2:
        return [], []

    picked.sort(key=lambda item: item[1])  # your team renders above the enemy team
    return [picked[0][0]], [picked[1][0]]


def to_png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def capture_summary(cfg: AgentConfig, frame: Image.Image | None = None) -> bytes:
    """PNG bytes of the summary region from ``frame`` (or a fresh screen grab)."""
    frame = frame if frame is not None else grab_screen(cfg.monitor_index)
    return to_png_bytes(crop_region(frame, resolve_summary_region(cfg, frame.size)))


def capture_leaderboards(
    cfg: AgentConfig, frame: Image.Image | None = None
) -> tuple[bytes | None, bytes | None]:
    """PNG bytes of (team1, team2) leaderboards from the scoreboard frame.

    In ``anchor`` mode each side is found by its bar color; in ``region`` mode the
    configured rectangles are cropped. A side returns None if its anchor is missing.
    """
    frame = frame if frame is not None else grab_screen(cfg.monitor_index)
    if cfg.leaderboard_mode == "region":
        t1 = to_png_bytes(crop_region(frame, cfg.team1_region))  # type: ignore[arg-type]
        t2 = to_png_bytes(crop_region(frame, cfg.team2_region))  # type: ignore[arg-type]
        return t1, t2

    width = resolve_leaderboard_width(cfg, frame.size)
    tol = cfg.color_tolerance
    blue = find_leaderboard_anchor(frame, cfg.blue_colors, width, tol)
    red = find_leaderboard_anchor(frame, cfg.red_colors, width, tol)

    # The configured colours are the author's palette. When either side comes back
    # empty the frame is using different bar colours - a colourblind palette, or a
    # display pipeline that shifted them past the tolerance - so read the real ones
    # off the frame rather than failing the capture outright.
    if (blue is None or red is None) and cfg.auto_team_colors:
        team1_colors, team2_colors = detect_team_colors(frame)
        if team1_colors and team2_colors:
            blue = blue or find_leaderboard_anchor(frame, team1_colors, width, tol)
            red = red or find_leaderboard_anchor(frame, team2_colors, width, tol)

    t1 = to_png_bytes(crop_region(frame, blue)) if blue else None
    t2 = to_png_bytes(crop_region(frame, red)) if red else None
    return t1, t2
