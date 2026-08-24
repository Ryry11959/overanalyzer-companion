"""The overlay panel's layout, as pure data.

The panel is drawn on a single canvas rather than assembled from Tk widgets:
the contour backdrop has to show through the gaps between surfaces, and Tk
widgets are opaque, so nesting frames would paint the texture out. Instead each
screen is described here as a flat list of draw operations plus the interactive
regions that sit on them, and :mod:`surface` paints the result.

Everything in this module is pure - it takes state and a text-measuring
callback, and returns geometry - so the whole layout is unit-testable with no
display and no fonts installed.

Geometry follows the design's 4/8px rhythm at a 360px panel width; radii, fills
and type sizes come from :mod:`theme`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from overanalyzer_agent.ui import theme

Anchor = Literal["nw", "ne", "w", "e", "center"]
Measure = Callable[[str, "Font"], int]

WIDTH = theme.PANEL_WIDTH
PAD = 16
TITLEBAR_H = 40
GAP = 16
TIGHT_GAP = 8  # around the stat-tiles block, which is its own section now
LOG_BOX_HEIGHT = 140  # ~8 lines of mono-11 before it scrolls

# Stat-tile text offsets from the tile block's top. Derived from the fonts' ink
# extents (see _stat_tiles) rather than their line boxes, so the visual margins
# above the label and below the hint match.
TILE_HEIGHT = 66
TILE_LABEL_Y = 9
TILE_VALUE_Y = 17
TILE_HINT_Y = 43


@dataclass(frozen=True)
class Font:
    """A type role from the design system, resolved to a real family later."""

    role: Literal["sans", "medium", "mono", "brand"] = "sans"
    size: int = theme.TEXT_SM
    bold: bool = False


SANS = Font("sans", theme.TEXT_SM)
SANS_SM = Font("sans", theme.TEXT_XS)
MEDIUM = Font("medium", theme.TEXT_SM)
MONO_11 = Font("mono", theme.TEXT_11)
MONO_10 = Font("mono", theme.TEXT_2XS)
MONO_STAT = Font("mono", theme.TEXT_2XL)
MICRO = Font("medium", theme.TEXT_2XS)
META = Font("sans", theme.TEXT_11)
BRAND = Font("brand", 17, bold=True)


# --- draw operations ------------------------------------------------------
@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int
    radius: int = 0
    fill: str | None = None
    outline: str | None = None


@dataclass(frozen=True)
class Dot:
    x: int
    y: int
    r: float
    fill: str


@dataclass(frozen=True)
class Text:
    x: int
    y: int
    text: str
    font: Font = SANS
    fill: str = theme.TEXT
    anchor: Anchor = "nw"
    wrap: int | None = None  # wrap width in px; None = single line


@dataclass(frozen=True)
class Glyph:
    """A lucide icon, by name."""

    x: int
    y: int
    name: str
    size: int = 16
    fill: str = theme.TEXT
    anchor: Anchor = "nw"


@dataclass(frozen=True)
class Photo:
    """A pre-rendered image (the backdrop, a map thumbnail)."""

    x: int
    y: int
    key: str
    anchor: Anchor = "nw"


@dataclass(frozen=True)
class Entry:
    """A real Tk entry widget, embedded at these coordinates."""

    x: int
    y: int
    w: int
    h: int
    key: str
    secret: bool = False


@dataclass(frozen=True)
class TextBox:
    """A read-only, word-wrapping, scrollable log - an embedded Tk Text widget.

    Unlike :class:`Entry` (whose content is user-owned and left alone across
    repaints), a log's content is state-owned: every repaint hands over the
    current lines and the widget re-syncs to them, auto-scrolling to the
    newest line only if the view was already at the bottom.
    """

    x: int
    y: int
    w: int
    h: int
    key: str
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class Select:
    """A native dropdown, embedded at these coordinates."""

    x: int
    y: int
    w: int
    h: int
    key: str
    options: tuple[str, ...]
    value: str


@dataclass(frozen=True)
class Control:
    """A clickable region. ``action`` is dispatched by the window."""

    action: str
    x: int
    y: int
    w: int
    h: int
    tooltip: str | None = None


@dataclass
class Layout:
    height: int
    ops: list[object] = field(default_factory=list)
    controls: list[Control] = field(default_factory=list)


# --- state ----------------------------------------------------------------
@dataclass
class LastCapture:
    """What the app knows about the most recent upload.

    Only ``status`` and ``at`` are ever guaranteed: the richer fields are filled
    in when the match can be read back from the API, and stay ``None`` when it
    can't (offline, older server, read-only account).
    """

    status: str = "processing"
    at: str = ""
    match_id: str | None = None
    map_name: str | None = None
    result: str | None = None  # win / loss / draw
    role: str | None = None
    duration: str | None = None
    kd: str | None = None

    @property
    def detailed(self) -> bool:
        return self.map_name is not None


@dataclass
class PanelState:
    screen: str = "main"  # "main" | "settings"
    capturing: bool = False
    buffered: bool = False  # a summary is held, waiting on the scoreboard
    connected: bool | None = None  # None until the first health check answers
    latency_ms: int | None = None
    api_host: str = ""
    has_web_url: bool = False
    hotkeys: dict[str, str] = field(
        default_factory=lambda: {"summary": "F11", "scoreboard": "F12", "reset": "F9"}
    )
    # Only offered when more than one display is actually detected.
    monitor_options: tuple[str, ...] = ()
    monitor_value: str = ""
    captured_today: int = 0
    last_upload_at: str | None = None
    session_record: str | None = None
    session_hint: str | None = None
    last: LastCapture | None = None
    status_message: str = "Ready."
    status_color: str = theme.TEXT_MUTED
    log: list[str] = field(default_factory=list)
    log_open: bool = False
    adv_open: bool = False
    recording: str | None = None  # which hotkey is listening for a key
    hover: str | None = None
    # The self test runs the whole capture path and reports each hop, so a
    # failure names the hop that broke instead of a single opaque verdict.
    self_test_running: bool = False
    self_test: tuple[tuple[str, str, str], ...] = ()  # (stage, pass/fail, detail)
    # How many capture attempts are kept on disk for diagnosis.
    debug_count: int = 0
    # A newer build the service is announcing. None means nothing to offer.
    update_version: str | None = None
    update_mandatory: bool = False
    update_busy: bool = False
    update_progress: str | None = None


# --- shared pieces --------------------------------------------------------
def _keycap(ops: list, x: int, y: int, label: str, *, on_primary: bool) -> int:
    """A 2px-radius key chip. Returns its width."""
    w = 10 + len(label) * 6
    ops.append(
        Rect(
            x, y, w, 18, theme.RADIUS_SM,
            outline=theme.over("#ffffff", theme.PRIMARY, 0.35) if on_primary else theme.BORDER,
        )
    )
    ops.append(
        Text(
            x + w // 2, y + 9, label, MONO_10,
            theme.TEXT_ON_PRIMARY if on_primary else theme.TEXT_MUTED, "center",
        )
    )
    return w


def _titlebar(ops: list, controls: list, state: PanelState, measure: Measure) -> None:
    ops.append(Rect(0, 0, WIDTH, TITLEBAR_H, fill=theme.SIDEBAR))
    ops.append(Rect(0, TITLEBAR_H - 1, WIDTH, 1, fill=theme.BORDER))

    if state.screen == "settings":
        _icon_button(ops, controls, 6, 6, "chevron-left", "back", state, tooltip="Back")
        ops.append(Text(42, TITLEBAR_H // 2, "Settings", MEDIUM, theme.TEXT, "w"))
    else:
        # Two-tone Rajdhani wordmark, as in the web app's sidebar lockup.
        ops.append(Text(12, TITLEBAR_H // 2, "Over", BRAND, theme.TEXT, "w"))
        ops.append(
            Text(12 + measure("Over", BRAND), TITLEBAR_H // 2, "Analyzer", BRAND,
                 theme.BRAND, "w")
        )
        _icon_button(ops, controls, WIDTH - 6 - 58, 6, "settings", "settings", state,
                     tooltip="Settings")
    _icon_button(ops, controls, WIDTH - 6 - 28, 6, "power", "quit", state,
                 tooltip="Quit - ends the process", danger=True)


def _icon_button(ops: list, controls: list, x: int, y: int, glyph: str, action: str,
                 state: PanelState, *, tooltip: str | None = None,
                 danger: bool = False) -> None:
    hovered = state.hover == action
    if hovered:
        ops.append(
            Rect(x, y, 28, 28, theme.RADIUS_MD,
                 fill=theme.DANGER_HOVER if danger else theme.ACCENT)
        )
    colour = theme.TEXT_MUTED
    if hovered:
        colour = theme.LOSS if danger else theme.TEXT
    ops.append(Glyph(x + 14, y + 14, glyph, 16, colour, "center"))
    controls.append(Control(action, x, y, 28, 28, tooltip))


def _section_heading(ops: list, y: int, title: str, sub: str | None = None) -> int:
    ops.append(Text(PAD, y, title, MEDIUM, theme.TEXT))
    if sub:
        ops.append(Text(PAD, y + 18, sub, SANS_SM, theme.TEXT_MUTED))
        return y + 34
    return y + 18


def _separator(ops: list, y: int) -> int:
    ops.append(Rect(PAD, y, WIDTH - PAD * 2, 1, fill=theme.BORDER))
    return y + 1


# --- main screen ----------------------------------------------------------
def build_main(state: PanelState, measure: Measure) -> Layout:
    ops: list = []
    controls: list[Control] = []

    ops.append(Photo(0, 0, "backdrop"))
    _titlebar(ops, controls, state, measure)

    y = TITLEBAR_H + PAD
    y = _update_banner(ops, controls, state, y, measure)
    y = _status_row(ops, controls, state, y, measure)
    y += GAP
    y = _capture_buttons(ops, controls, state, y, measure)
    y += TIGHT_GAP
    y = _stat_tiles(ops, state, y)
    y += TIGHT_GAP
    y = _last_captured(ops, controls, state, y, measure)
    y += GAP
    y = _activity(ops, controls, state, y, measure)

    return Layout(height=y + PAD, ops=ops, controls=controls)


def _update_banner(ops: list, controls: list, state: PanelState, y: int,
                   measure: Measure) -> int:
    """A new build is available: one line, one button, above everything else.

    It sits at the top of the panel rather than in Settings because an update
    nobody sees is an update nobody installs. It never blocks capture: a user
    mid-session can ignore it, and a mandatory release only changes the wording.
    """
    if state.update_version is None:
        return y

    inner = WIDTH - PAD * 2
    busy = state.update_busy
    if busy:
        label, action = state.update_progress or "Updating…", None
    elif state.update_mandatory:
        label, action = f"Important update {state.update_version}", "install_update"
    else:
        label, action = f"Update {state.update_version} available", "install_update"

    height = 40
    accent = theme.DRAW if state.update_mandatory else theme.PRIMARY
    hovered = state.hover == "install_update"
    ops.append(
        Rect(PAD, y, inner, height, theme.RADIUS,
             fill=theme.CARD_HOVER if hovered and not busy else theme.CARD,
             outline=accent)
    )
    ops.append(Glyph(PAD + 12, y + height // 2, "arrow-up-right", 14, accent, "w"))

    button = "Update now"
    button_w = measure(button, SANS_SM) + 20
    text_w = inner - 24 - 14 - (0 if busy else button_w + 10)
    ops.append(
        Text(PAD + 34, y + height // 2, _ellipsise(label, text_w, SANS_SM, measure),
             SANS_SM, theme.TEXT, "w")
    )
    if not busy and action is not None:
        bx = PAD + inner - 10 - button_w
        ops.append(
            Rect(bx, y + 8, button_w, 24, theme.RADIUS_SM,
                 fill=theme.PRIMARY if hovered else None, outline=accent)
        )
        ops.append(
            Text(bx + button_w // 2, y + height // 2, button, SANS_SM,
                 theme.TEXT_ON_PRIMARY if hovered else theme.TEXT, "center")
        )
        controls.append(
            Control(action, PAD, y, inner, height,
                    "Downloads the new version, checks it, and restarts the app")
        )
    return y + height + TIGHT_GAP


def _status_row(ops: list, controls: list, state: PanelState, y: int, measure: Measure) -> int:
    inner = WIDTH - PAD * 2
    live = state.capturing
    if live:
        fill, outline = theme.CARD, theme.BORDER
        # Don't claim "Connected" before anything has actually answered.
        dot = theme.WIN
        label = {None: "Capture active", True: "Connected", False: "Offline"}[state.connected]
        meta = state.api_host
        button, button_colour = "Pause", theme.TEXT_MUTED
    else:
        fill, outline = theme.PAUSED_BG, theme.PAUSED_BORDER
        dot, label = theme.DRAW, "Capture paused"
        meta = "hotkeys ignored"
        button, button_colour = "Resume", theme.DRAW
    if state.connected is False and live:
        dot = theme.LOSS

    h = 40
    ops.append(Rect(PAD, y, inner, h, theme.RADIUS, fill=fill, outline=outline))
    ops.append(Dot(PAD + 12 + 3, y + h // 2, 3.5, dot))
    label_x = PAD + 12 + 7 + 8
    ops.append(Text(label_x, y + h // 2, label, SANS, theme.TEXT, "w"))

    btn_w = measure(button, Font("medium", theme.TEXT_11)) + 16
    btn_x = PAD + inner - 12 - btn_w
    meta_x = label_x + measure(label, SANS) + 8
    meta = _ellipsise(meta, btn_x - 8 - meta_x, MONO_11, measure)
    if meta:
        ops.append(Text(meta_x, y + h // 2, meta, MONO_11, theme.TEXT_MUTED, "w"))

    hovered = state.hover == "toggle"
    ops.append(
        Rect(btn_x, y + 8, btn_w, 24, theme.RADIUS_MD,
             fill=(theme.ACCENT if live else theme.over(theme.DRAW, theme.PAGE, 0.12))
             if hovered else None,
             outline=theme.BORDER if live else theme.PAUSED_BORDER)
    )
    ops.append(
        Text(btn_x + btn_w // 2, y + 20, button, Font("medium", theme.TEXT_11),
             theme.TEXT if (hovered and live) else button_colour, "center")
    )
    controls.append(Control("toggle", btn_x, y + 8, btn_w, 24,
                            "Pause capture" if live else "Resume capture"))
    return y + h


def _capture_buttons(ops: list, controls: list, state: PanelState, y: int,
                     measure: Measure) -> int:
    inner = WIDTH - PAD * 2
    # F11 is the primary action until a summary is buffered; once it's waiting
    # on the scoreboard, F12 (the button that finishes the upload) takes over -
    # the highlight always points at whichever key you press next.
    for action, glyph, label, key, primary in (
        ("capture_summary", "image-up", "Capture summary", state.hotkeys["summary"],
         not state.buffered),
        ("capture_scoreboard", "upload", "Scoreboard + upload", state.hotkeys["scoreboard"],
         state.buffered),
    ):
        hovered = state.hover == action
        if primary:
            fill = theme.PRIMARY_HOVER if hovered else theme.PRIMARY
            text_colour = theme.TEXT_ON_PRIMARY
        else:
            fill = theme.SECONDARY_HOVER if hovered else theme.SECONDARY
            text_colour = theme.TEXT
        ops.append(Rect(PAD, y, inner, 40, theme.RADIUS, fill=fill))
        ops.append(Glyph(PAD + 12, y + 20, glyph, 16, text_colour, "w"))
        ops.append(Text(PAD + 12 + 16 + 8, y + 20, label, SANS, text_colour, "w"))
        cap_w = 10 + len(key) * 6
        _keycap(ops, PAD + inner - 12 - cap_w, y + 11, key, on_primary=primary)
        controls.append(Control(action, PAD, y, inner, 40))
        y += 40 + 8

    if state.buffered:
        # Half a capture is in hand. Say so, and offer the way out of it - this
        # is where the old F9 "reset buffer" lives now that F9 pauses.
        ops.append(Dot(PAD + 4, y + 9, 3.5, theme.DRAW))
        ops.append(
            Text(PAD + 16, y + 8, "Summary held - capture the scoreboard next", META,
                 theme.DRAW, "w")
        )
        discard = state.hover == "reset"
        ops.append(
            Text(PAD + inner, y + 8, "Discard", Font("medium", theme.TEXT_11),
                 theme.TEXT if discard else theme.TEXT_MUTED, "e")
        )
        controls.append(Control("reset", PAD + inner - 48, y, 48, 18, "Clear the held summary"))
        return y + 18

    # The F9 hint doubles as a pause control - the design shows it as a hint, but
    # a visible key that does nothing when clicked reads as broken. Centered
    # between the two capture buttons above and the stat tiles below.
    hovered = state.hover == "toggle_hint"
    colour = theme.TEXT if hovered else theme.TEXT_MUTED
    glyph_name = "play" if not state.capturing else "pause"
    key_label = state.hotkeys["reset"]
    hint = "resumes capture" if not state.capturing else "pauses capture without closing the app"
    group_w = 12 + 6 + measure(key_label, MONO_11) + 8 + measure(hint, META)
    start = PAD + (inner - group_w) // 2
    ops.append(Glyph(start, y + 8, glyph_name, 12, colour, "w"))
    ops.append(Text(start + 18, y + 8, key_label, MONO_11, colour, "w"))
    ops.append(Text(start + 18 + measure(key_label, MONO_11) + 8, y + 8, hint, META, colour, "w"))
    controls.append(Control("toggle_hint", PAD, y, inner, 18))
    return y + 18


def _stat_tiles(ops: list, state: PanelState, y: int) -> int:
    inner = WIDTH - PAD * 2
    ops.append(Text(PAD, y, "This session", MEDIUM, theme.TEXT))
    y += 22

    h = TILE_HEIGHT
    # A 1px grid gap over a border-coloured background - the StatStrip pattern.
    ops.append(Rect(PAD, y, inner, h + 2, theme.RADIUS, fill=theme.BORDER, outline=theme.BORDER))
    half = (inner - 3) // 2
    tiles = (
        ("UPLOADS", str(state.captured_today),
         f"last {state.last_upload_at}" if state.last_upload_at else "nothing yet"),
        ("RECORD", state.session_record or "-", state.session_hint or "no results yet"),
    )
    for i, (label, value, hint) in enumerate(tiles):
        x = PAD + 1 + i * (half + 1)
        ops.append(Rect(x, y + 1, half, h, fill=theme.CARD))
        # Offsets are tuned to the fonts' INK, not their line boxes. A 24px
        # JetBrains Mono line box is 38px tall against ~18px of actual digit, so
        # spacing the three rows by line height leaves a visibly top-heavy tile
        # (and overflows the bottom edge). These land 10px of clear space above
        # the label and below the hint, with 4px between rows.
        ops.append(Text(x + 12, y + TILE_LABEL_Y, label, MICRO, theme.TEXT_MUTED))
        ops.append(Text(x + 12, y + TILE_VALUE_Y, value, MONO_STAT, theme.TEXT))
        ops.append(Text(x + 12, y + TILE_HINT_Y, hint, META, theme.TEXT_MUTED))
    return y + h + 2


def _last_captured(ops: list, controls: list, state: PanelState, y: int,
                   measure: Measure) -> int:
    inner = WIDTH - PAD * 2
    ops.append(Text(PAD, y, "Last captured", MEDIUM, theme.TEXT))
    if state.last is not None and state.last.match_id and state.has_web_url:
        hovered = state.hover == "open_match"
        link = "Open in app →"
        ops.append(
            Text(WIDTH - PAD, y + 2, link, Font("medium", theme.TEXT_XS),
                 theme.shift(theme.PRIMARY, 7) if hovered else theme.PRIMARY, "ne")
        )
        w = measure(link, Font("medium", theme.TEXT_XS))
        controls.append(Control("open_match", WIDTH - PAD - w, y, w, 16))
    y += 18 + 12

    h = 68
    ops.append(Rect(PAD, y, inner, h, theme.RADIUS, fill=theme.CARD, outline=theme.BORDER))
    last = state.last
    if last is None:
        ops.append(
            Text(PAD + 12, y + h // 2, "Nothing captured yet this session.", SANS,
                 theme.TEXT_MUTED, "w")
        )
        return y + h

    text_x = PAD + 12
    if last.detailed:
        ops.append(Photo(PAD + 12, y + 12, "map_thumb"))
        text_x = PAD + 12 + 72 + 12

    badge_w = _status_badge(ops, state, PAD + inner - 12, y + 12, last.status, measure)
    name_y = y + 24
    if last.result:
        ops.append(Glyph(text_x, name_y, _CHEVRON[last.result], 14,
                         _RESULT_COLOUR[last.result], "w"))
        text_x += 20
    title = last.map_name or _STATUS_TITLE.get(last.status, "Match uploaded")
    title = _ellipsise(title, PAD + inner - 12 - badge_w - 8 - text_x, SANS, measure)
    ops.append(Text(text_x, name_y, title, SANS, theme.TEXT, "w"))

    meta_x = text_x
    if last.role:
        ops.append(Photo(meta_x, y + 39, f"role_{last.role}"))
        meta_x += 12 + 6
    meta = " · ".join(p for p in (last.duration, last.kd, last.at) if p)
    ops.append(Text(meta_x, y + 45, meta, MONO_11, theme.TEXT_MUTED, "w"))
    return y + h


# The ResultChevron: the shape carries the meaning, not just the colour.
_CHEVRON = {"win": "chevron-right", "loss": "chevron-left", "draw": "equal"}
_RESULT_COLOUR = {"win": theme.WIN, "loss": theme.LOSS, "draw": theme.DRAW}
_STATUS_TITLE = {
    "complete": "Match recorded",
    "partial": "Recorded - partial",
    "needs_review": "Needs review",
    "processing": "Still processing",
    "failed": "OCR failed",
}
_BADGE_TONE = {
    "complete": theme.WIN,
    "partial": theme.DRAW,
    "needs_review": theme.DRAW,
    "processing": theme.TEXT_MUTED,
    "failed": theme.LOSS,
}
_BADGE_LABEL = {
    "complete": "complete",
    "partial": "partial",
    "needs_review": "review",
    "processing": "processing",
    "failed": "failed",
}


def _status_badge(ops: list, state: PanelState, right: int, y: int, status: str,
                  measure: Measure) -> int:
    label = _BADGE_LABEL.get(status, status)
    tone = _BADGE_TONE.get(status, theme.TEXT_MUTED)
    w = measure(label, MONO_10) + 14
    ops.append(
        Rect(right - w, y, w, 18, theme.RADIUS_SM,
             fill=theme.over(tone, theme.CARD, 0.12), outline=theme.over(tone, theme.CARD, 0.35))
    )
    ops.append(Text(right - w // 2, y + 9, label, MONO_10, tone, "center"))
    return w


def _activity(ops: list, controls: list, state: PanelState, y: int, measure: Measure) -> int:
    inner = WIDTH - PAD * 2
    ops.append(Rect(PAD, y, inner, 1, fill=theme.BORDER))
    y += 12

    hovered = state.hover == "toggle_log"
    ops.append(Dot(PAD + 4, y + 8, 3.0, state.status_color))
    label_colour = theme.TEXT if hovered else theme.TEXT_MUTED
    ops.append(
        Text(PAD + 16, y + 8,
             _ellipsise(state.status_message, inner - 16 - 22, SANS_SM, measure),
             SANS_SM, label_colour, "w")
    )
    ops.append(
        Glyph(PAD + inner - 8, y + 8, "chevron-up" if state.log_open else "chevron-down",
              16, label_colour, "e")
    )
    controls.append(Control("toggle_log", PAD, y, inner, 18,
                            "Hide activity" if state.log_open else "Show activity"))
    y += 18

    if not state.log_open:
        return y

    y += 8
    if not state.log:
        h = 40
        ops.append(Rect(PAD, y, inner, h, theme.RADIUS, fill=theme.SIDEBAR, outline=theme.BORDER))
        ops.append(Text(PAD + 12, y + h // 2, "No activity yet.", MONO_11, theme.TEXT_MUTED, "w"))
        return y + h

    # A real Tk text widget: it wraps long lines instead of ellipsising them,
    # and scrolls once there's more history than fits - see ui/surface.py.
    ops.append(TextBox(PAD, y, inner, LOG_BOX_HEIGHT, "log", tuple(state.log)))
    return y + LOG_BOX_HEIGHT


# --- settings screen ------------------------------------------------------
def build_settings(state: PanelState, measure: Measure) -> Layout:
    ops: list = []
    controls: list[Control] = []
    inner = WIDTH - PAD * 2

    ops.append(Photo(0, 0, "backdrop"))
    _titlebar(ops, controls, state, measure)

    y = TITLEBAR_H + PAD
    # --- connection: a device key and nothing else. There is deliberately no
    # server-address field - captures go to the configured service for everyone
    # who isn't self-hosting, and a self-hoster edits agent.toml.
    ops.append(Text(PAD, y, "Connection", MEDIUM, theme.TEXT))
    button = "Testing…" if state.self_test_running else "Run self test"
    # Trim the subtitle to whatever the button leaves, so the two can never
    # collide whatever the font resolves to.
    subtitle = _ellipsise(
        "Uses a held Summary frame and visible Teams screen",
        inner - (measure(button, SANS_SM) + 24) - 12, SANS_SM, measure,
    )
    ops.append(Text(PAD, y + 18, subtitle, SANS_SM, theme.TEXT_MUTED))
    _small_button(ops, controls, state, "self_test", button, y - 2, measure)
    y += 34 + 12

    ops.append(Text(PAD, y, "DEVICE KEY", MICRO, theme.TEXT_MUTED))
    if state.has_web_url:
        hovered = state.hover == "open_pairing"
        label = "Pair a device →"
        colour = theme.shift(theme.PRIMARY, 7) if hovered else theme.PRIMARY
        w = measure(label, Font("medium", theme.TEXT_XS))
        ops.append(Text(WIDTH - PAD, y, label, Font("medium", theme.TEXT_XS), colour, "ne"))
        controls.append(
            Control("open_pairing", WIDTH - PAD - w, y - 2, w, 16,
                    "Opens Settings → Devices in the web app")
        )
    y += 16
    ops.append(Entry(PAD, y, inner, 36, "bearer_token", secret=True))
    y += 36 + 8
    ops.append(Dot(PAD + 4, y + 6, 3.5, _connection_dot(state)))
    ops.append(Text(PAD + 16, y + 6, _connection_text(state), SANS_SM, theme.TEXT_MUTED, "w"))
    y += 20 + 6
    ops.append(
        Text(PAD, y, "Get a key from Settings → Devices in the web app, then paste it "
                     "here.", META, theme.TEXT_MUTED, wrap=inner)
    )
    y += 32
    y = _self_test_rows(ops, state, y, inner, measure)
    y += 20
    y = _separator(ops, y) + 20

    # --- hotkeys
    ops.append(Text(PAD, y, "Hotkeys", MEDIUM, theme.TEXT))
    ops.append(
        Text(PAD, y + 18, "Global - they work while the game has focus", SANS_SM,
             theme.TEXT_MUTED)
    )
    y += 34 + 12
    rows = (
        ("summary", "Capture summary"),
        ("scoreboard", "Scoreboard + upload"),
        ("reset", "Pause capture"),
    )
    row_h = 34
    ops.append(
        Rect(PAD, y, inner, row_h * len(rows) + len(rows) + 1, theme.RADIUS,
             fill=theme.BORDER, outline=theme.BORDER)
    )
    for i, (key, label) in enumerate(rows):
        ry = y + 1 + i * (row_h + 1)
        action = f"record_{key}"
        hovered = state.hover == action
        ops.append(Rect(PAD + 1, ry, inner - 2, row_h,
                        fill=theme.CARD_HOVER if hovered else theme.CARD))
        ops.append(Text(PAD + 13, ry + row_h // 2, label, SANS, theme.TEXT, "w"))
        if state.recording == key:
            cap, colour = "press a key…", theme.DRAW
        else:
            cap, colour = state.hotkeys[key], theme.TEXT
        cap_w = measure(cap, MONO_11) + 12
        ops.append(
            Rect(PAD + inner - 13 - cap_w, ry + 8, cap_w, 18, theme.RADIUS_SM,
                 fill=theme.PAGE, outline=theme.PAUSED_BORDER if state.recording == key
                 else theme.BORDER)
        )
        ops.append(
            Text(PAD + inner - 13 - cap_w // 2, ry + row_h // 2, cap, MONO_11, colour, "center")
        )
        controls.append(Control(action, PAD + 1, ry, inner - 2, row_h, "Click, then press a key"))
    y += row_h * len(rows) + len(rows) + 1 + 8
    ops.append(Text(PAD, y, "Click a row, then press the key you want.", META, theme.TEXT_MUTED))
    y += 16 + 10
    disclosure = (
        "Capture runs only when you press a hotkey or button. Each whole game frame "
        "is uploaded for processing, then discarded. Capture is never continuous."
    )
    ops.append(Text(PAD, y, disclosure, META, theme.TEXT_MUTED, wrap=inner))
    y += _wrapped_height(disclosure, inner, META, measure) + 20
    y = _separator(ops, y) + 20

    # --- advanced
    hovered = state.hover == "toggle_adv"
    colour = theme.TEXT if hovered else theme.TEXT
    ops.append(Text(PAD, y + 8, "Advanced", SANS, colour, "w"))
    ops.append(
        Text(PAD + measure("Advanced", SANS) + 8, y + 8, "display, test capture",
             SANS_SM, theme.TEXT_MUTED, "w")
    )
    ops.append(
        Glyph(PAD + inner - 8, y + 8, "chevron-up" if state.adv_open else "chevron-down",
              16, theme.TEXT_MUTED, "e")
    )
    controls.append(Control("toggle_adv", PAD, y, inner, 18))
    y += 18

    if state.adv_open:
        y += 12
        if len(state.monitor_options) > 1:
            ops.append(Text(PAD, y, "MONITOR", MICRO, theme.TEXT_MUTED))
            y += 16
            ops.append(
                Select(PAD, y, inner, 32, "monitor", state.monitor_options, state.monitor_value)
            )
            y += 32 + 6
            ops.append(
                Text(PAD, y, "Which display to capture from.", META, theme.TEXT_MUTED)
            )
            y += 16 + 14

        _small_button(ops, controls, state, "test_capture", "Test capture", y, measure,
                      left=True)
        y += 32 + 20

        # --- capture debug: metadata only, never uploaded frame pixels
        ops.append(Text(PAD, y, "CAPTURE DEBUG", MICRO, theme.TEXT_MUTED))
        y += 16
        ops.append(
            Text(PAD, y, _debug_text(state), META, theme.TEXT_MUTED, wrap=inner)
        )
        y += _wrapped_height(_debug_text(state), inner, META, measure) + 8
        _small_button(ops, controls, state, "open_debug", "Open debug folder", y, measure,
                      left=True)
        y += 32
    y += 20
    y = _separator(ops, y) + 20

    # --- quit
    hovered = state.hover == "quit_button"
    ops.append(
        Rect(PAD, y, inner, 36, theme.RADIUS,
             fill=theme.DANGER_HOVER if hovered else None,
             outline=theme.over(theme.LOSS, theme.PAGE, 0.35))
    )
    label = "Quit OverAnalyzer"
    label_w = measure(label, SANS)
    start = PAD + (inner - label_w - 16 - 8) // 2
    ops.append(Glyph(start, y + 18, "power", 16, theme.LOSS, "w"))
    ops.append(Text(start + 24, y + 18, label, SANS, theme.LOSS, "w"))
    controls.append(Control("quit_button", PAD, y, inner, 36))
    y += 36 + 6
    ops.append(
        Text(PAD, y, "Unregisters the hotkeys and ends the process. Nothing stays "
                     "running in the background.", META, theme.TEXT_MUTED, wrap=inner)
    )
    y += 32

    return Layout(height=y + PAD, ops=ops, controls=controls)


def _debug_text(state: PanelState) -> str:
    """What the debug folder holds right now, in the user's terms."""
    if not state.debug_count:
        return (
            "Empty. Capture attempts save a readable metadata report here. Full "
            "frame pixels are never written to this folder."
        )
    kept = "attempt" if state.debug_count == 1 else "attempts"
    return (
        f"{state.debug_count} recent {kept}, each with a metadata report. No device "
        "key, screenshot, or full frame is stored here."
    )


def _self_test_rows(ops: list, state: PanelState, y: int, inner: int,
                    measure: Measure) -> int:
    """Render the self test's per-stage verdicts.

    Each hop gets its own line, because "it doesn't work" is not actionable and
    a single combined verdict is what let a valid device key stand in for a
    working upload. A failing stage carries its own next step underneath.
    """
    if not state.self_test:
        return y

    y += 12
    for name, result, detail in state.self_test:
        ok = result == "pass"
        ops.append(
            Glyph(PAD + 1, y + 1, "circle-check-big" if ok else "x", 13,
                  theme.WIN if ok else theme.LOSS)
        )
        ops.append(Text(PAD + 20, y, name, SANS_SM, theme.TEXT))
        y += 18
        if detail:
            ops.append(Text(PAD + 20, y, detail, META, theme.TEXT_MUTED, wrap=inner - 20))
            y += _wrapped_height(detail, inner - 20, META, measure)
        y += 6
    return y


def _wrapped_height(text: str, width: int, font: Font, measure: Measure,
                    line_height: int = 15) -> int:
    """How tall a wrapped run of text will be, in whole lines.

    The layout is pure data and the canvas wraps for real, so the height has to
    be predicted here or every element below a long message overlaps it.
    """
    if width <= 0 or not text:
        return 0
    lines, current = 1, ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and measure(candidate, font) > width:
            lines += 1
            current = word
        else:
            current = candidate
    return lines * line_height


def _small_button(ops: list, controls: list, state: PanelState, action: str, label: str,
                  y: int, measure: Measure, *, left: bool = False) -> None:
    w = measure(label, SANS_SM) + 24
    x = PAD if left else WIDTH - PAD - w
    hovered = state.hover == action
    ops.append(
        Rect(x, y, w, 32, theme.RADIUS, fill=theme.ACCENT if hovered else None,
             outline=theme.BORDER)
    )
    ops.append(Text(x + w // 2, y + 16, label, SANS_SM, theme.TEXT, "center"))
    controls.append(Control(action, x, y, w, 32))


def _connection_dot(state: PanelState) -> str:
    if state.connected is None:
        return theme.TEXT_MUTED
    return theme.WIN if state.connected else theme.LOSS


def _connection_text(state: PanelState) -> str:
    if state.connected is None:
        return "Not checked yet"
    if not state.connected:
        return "Unreachable - captures will fail to upload"
    if state.latency_ms is not None:
        return f"Reachable · {state.latency_ms} ms"
    return "Reachable"


def _ellipsise(text: str, max_w: int, font: Font, measure: Measure) -> str:
    """Trim ``text`` to fit ``max_w``, with an ellipsis when it doesn't."""
    if max_w <= 0 or not text:
        return ""
    if measure(text, font) <= max_w:
        return text
    trimmed = text
    while trimmed and measure(trimmed + "…", font) > max_w:
        trimmed = trimmed[:-1]
    return (trimmed + "…") if trimmed else ""


def build(state: PanelState, measure: Measure) -> Layout:
    """Lay out whichever screen is showing."""
    if state.screen == "settings":
        return build_settings(state, measure)
    return build_main(state, measure)
