"""Tray driver: icon-image generation per state (pure PIL) and menu assembly.

``pystray`` is only needed for the menu tests; the icon/colour tests run anywhere.
"""
import pytest
from PIL import Image

from overanalyzer_agent import tray
from overanalyzer_agent.config import AgentConfig
from overanalyzer_agent.controller import Status


def _pystray_or_skip():
    """importorskip only catches ImportError, but on a headless Linux runner
    pystray's Xorg backend raises DisplayNameError at import time - skip then too."""
    try:
        import pystray  # noqa: F401
    except Exception as exc:
        pytest.skip(f"pystray backend unavailable: {exc!r}")


def _menu_texts(menu):
    return [getattr(item, "text", None) for item in menu.items]


def test_make_icon_image_per_state():
    for state in Status:
        img = tray.make_icon_image(state, size=32)
        assert isinstance(img, Image.Image)
        assert img.size == (32, 32)


def test_the_icon_is_the_brand_mark_not_an_abstract_badge():
    """The tray icon should read as the OverAnalyzer logo, per owner ask."""
    img = tray.make_icon_image(Status.IDLE, size=64)
    pixels = {p[:3] for p in img.getdata() if p[3] > 200}
    assert any(abs(r - 0xFE) < 6 and abs(g - 0x7B) < 6 for r, g, b in pixels)


def test_the_status_dot_uses_the_state_colour():
    img = tray.make_icon_image(Status.ERROR, size=64)
    r = max(3, 64 // 6)
    cx = cy = 64 - r - 64 // 14
    assert img.getpixel((cx, cy))[:3] == tray.STATE_COLORS[Status.ERROR]


def test_making_the_icon_never_mutates_the_shared_brand_cache():
    from overanalyzer_agent.ui import brand

    before = brand.icon(64).copy()
    tray.make_icon_image(Status.ERROR, size=64)
    assert list(brand.icon(64).getdata()) == list(before.getdata())


def test_state_colors_cover_all_states():
    for state in Status:
        assert state in tray.STATE_COLORS


def test_build_menu_exposes_core_actions():
    _pystray_or_skip()
    app = tray.TrayApp(AgentConfig())
    texts = _menu_texts(app.build_menu())
    assert "Capture summary\tF11" in texts
    assert "Scoreboard + upload\tF12" in texts
    assert "Show panel" in texts
    assert "Open dashboard" in texts
    assert "Quit" in texts


def test_menu_shows_the_configured_hotkeys_not_the_defaults():
    _pystray_or_skip()
    app = tray.TrayApp(AgentConfig(hotkey_summary="f7", hotkey_scoreboard="f8"))
    texts = _menu_texts(app.build_menu())
    assert "Capture summary\tF7" in texts
    assert "Scoreboard + upload\tF8" in texts


def test_pause_item_and_status_line_follow_the_paused_flag():
    _pystray_or_skip()
    app = tray.TrayApp(AgentConfig())
    assert app.status_label() == "Connected · capture on"
    assert "Pause capture\tF9" in _menu_texts(app.build_menu())

    app._toggle_capture()

    assert app._paused is True
    assert app.status_label() == "Capture paused"
    assert "Resume capture\tF9" in _menu_texts(app.build_menu())


def test_toggle_capture_round_trips():
    app = tray.TrayApp(AgentConfig())
    app._toggle_capture()
    app._toggle_capture()
    assert app._paused is False
