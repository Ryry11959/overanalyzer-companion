"""Register the bundled webfonts so Tk can use the product's typefaces.

The web app pulls Space Grotesk / JetBrains Mono / Rajdhani through ``next/font``;
Tk can only use fonts the OS knows about, so the same families are vendored as
TTFs under ``assets/fonts`` and registered **process-privately** at startup
(``AddFontResourceExW`` with ``FR_PRIVATE`` - nothing is installed for the user,
and the registration dies with the process).

Registration has to happen before the Tk root is created, because Tk snapshots
the font family list on init. Everything degrades: if the files are missing or
the platform isn't Windows, :func:`load_fonts` returns a :class:`FontSet` backed
by system fallbacks and the app still renders.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"

# Filename -> the family name the OS will expose it under. Space Grotesk Medium
# ships as its own RIBBI family (its subfamily is "Regular"), which is why the
# medium weight is a separate family string rather than a bold flag.
BUNDLED: dict[str, str] = {
    "SpaceGrotesk-Regular.ttf": "Space Grotesk",
    "SpaceGrotesk-Medium.ttf": "Space Grotesk Medium",
    "SpaceGrotesk-Bold.ttf": "Space Grotesk",
    "JetBrainsMono-Regular.ttf": "JetBrains Mono",
    "Rajdhani-Bold.ttf": "Rajdhani",
}

# What we fall back to when the bundled files can't be registered.
FALLBACK_SANS = "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"
FALLBACK_MONO = "Consolas" if sys.platform == "win32" else "TkFixedFont"


@dataclass(frozen=True)
class FontSet:
    """Resolved family names for the app's three type roles."""

    sans: str
    sans_medium: str
    mono: str
    brand: str
    bundled: bool  # False when we fell back to system fonts

    @classmethod
    def fallback(cls) -> "FontSet":
        return cls(
            sans=FALLBACK_SANS,
            sans_medium=FALLBACK_SANS,
            mono=FALLBACK_MONO,
            brand=FALLBACK_SANS,
            bundled=False,
        )


def font_files(directory: Path | None = None) -> list[Path]:
    """The bundled TTFs that actually exist on disk, in registration order."""
    base = directory or FONT_DIR
    return [base / name for name in BUNDLED if (base / name).is_file()]


def _register_windows(paths: list[Path]) -> int:
    """AddFontResourceExW each path privately. Returns how many took."""
    import ctypes

    FR_PRIVATE = 0x10
    gdi32 = ctypes.WinDLL("gdi32")  # type: ignore[attr-defined]
    added = 0
    for path in paths:
        if gdi32.AddFontResourceExW(ctypes.c_wchar_p(str(path)), FR_PRIVATE, 0):
            added += 1
    return added


def load_fonts(directory: Path | None = None) -> FontSet:
    """Register the bundled fonts and report the family names to use.

    Safe to call more than once (re-registering a private font is a no-op that
    bumps a refcount) and safe to call on a machine with none of the files.
    """
    paths = font_files(directory)
    if not paths or sys.platform != "win32":
        return FontSet.fallback()
    try:
        added = _register_windows(paths)
    except (OSError, AttributeError):  # no gdi32, or a locked/corrupt file
        return FontSet.fallback()
    if not added:
        return FontSet.fallback()
    return FontSet(
        sans="Space Grotesk",
        sans_medium="Space Grotesk Medium",
        mono="JetBrains Mono",
        brand="Rajdhani",
        bundled=True,
    )
