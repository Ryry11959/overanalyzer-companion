"""Full-frame screen capture with one coarse Game Report guard.

The companion deliberately knows nothing about crop coordinates, row geometry,
or team colours. It captures the selected display, checks only that the two broad
scoreboard areas contain the vivid blocks expected on a Teams Game Report, and
encodes the full frame for a transient server upload. The server owns every precise
layout decision.

``mss`` remains a lazy import so the image helpers stay testable without a desktop.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from overanalyzer_agent.config import AgentConfig


# The Teams screen places one large vivid board in each of these deliberately broad
# normalized areas. This is only an accidental-capture guard. It does not find a board,
# choose a crop, or decide what the server retains.
_TEAM_AREAS = (
    (0.25, 0.18, 0.75, 0.58),
    (0.25, 0.60, 0.75, 0.98),
)
_VIVID_FRACTION = 0.20


class NotGameReportError(RuntimeError):
    """The selected display does not coarsely resemble a Teams Game Report."""


@dataclass(frozen=True)
class CapturedFrame:
    """One memory-only PNG plus non-sensitive metadata for the debug report."""

    png: bytes
    width: int
    height: int

    @property
    def detail(self) -> str:
        return f"{self.width} x {self.height}, {len(self.png)} bytes"


def list_monitors() -> list[dict]:
    """The real monitors mss can see, excluding its synthetic all-screen box."""
    import mss

    with mss.mss() as sct:
        return [
            {
                "index": i,
                "width": monitor["width"],
                "height": monitor["height"],
                "left": monitor["left"],
                "top": monitor["top"],
            }
            for i, monitor in enumerate(sct.monitors)
            if i > 0
        ]


def grab_screen(monitor_index: int | None = None) -> Image.Image:
    """Capture one monitor as RGB. A missing saved index falls back to primary."""
    import mss

    with mss.mss() as sct:
        index = monitor_index if monitor_index and 0 < monitor_index < len(sct.monitors) else 1
        raw = sct.grab(sct.monitors[index])
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


def looks_like_game_report(frame: Image.Image) -> bool:
    """Coarsely reject a frame that is not the Teams Game Report screen.

    Both team boards occupy large stable areas but their exact bounds and colours are
    intentionally irrelevant here. Each broad area only needs enough bright, saturated
    pixels to look plausible. Five-row proof and crop geometry remain server concerns.
    """
    rgb = frame.convert("RGB")
    width, height = rgb.size
    if width < 320 or height < 180:
        return False

    return all(
        _vivid_fraction(
            rgb.crop(
                (
                    round(left * width),
                    round(top * height),
                    round(right * width),
                    round(bottom * height),
                )
            )
        )
        >= _VIVID_FRACTION
        for left, top, right, bottom in _TEAM_AREAS
    )


def _vivid_fraction(region: Image.Image) -> float:
    """Fraction of a small sample that is both visible and strongly coloured."""
    sample = region.copy()
    sample.thumbnail((320, 180))
    pixels = sample.get_flattened_data()
    total = sample.width * sample.height
    vivid = sum(1 for red, green, blue in pixels if max(red, green, blue) >= 70
                and max(red, green, blue) - min(red, green, blue) >= 45)
    return vivid / total if total else 0.0


def to_png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def capture_full_frame(
    cfg: AgentConfig,
    *,
    frame: Image.Image | None = None,
    require_game_report: bool = False,
) -> CapturedFrame:
    """Grab and encode one full selected-display frame in memory."""
    source = frame if frame is not None else grab_screen(cfg.monitor_index)
    if require_game_report and not looks_like_game_report(source):
        raise NotGameReportError(
            "the selected display does not look like the Teams Game Report screen"
        )
    rgb = source.convert("RGB")
    return CapturedFrame(to_png_bytes(rgb), rgb.width, rgb.height)
