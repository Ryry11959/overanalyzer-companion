"""Bundled fonts, role art and the contour backdrop."""
import sys

from PIL import Image

from overanalyzer_agent.ui import assets, fonts, theme, topography


# --- fonts ----------------------------------------------------------------
def test_the_font_files_are_actually_vendored():
    names = {path.name for path in fonts.font_files()}
    assert names == set(fonts.BUNDLED), f"missing: {set(fonts.BUNDLED) - names}"


def test_ofl_licenses_ship_with_the_fonts():
    licenses = fonts.FONT_DIR / "licenses"
    assert licenses.is_dir()
    assert len(list(licenses.glob("OFL-*.txt"))) == 3


def test_no_files_means_system_fallbacks_rather_than_a_crash(tmp_path):
    result = fonts.load_fonts(tmp_path)
    assert result.bundled is False
    assert result.sans and result.mono


def test_loading_reports_the_product_families_when_it_works():
    result = fonts.load_fonts()
    if sys.platform != "win32":
        assert result.bundled is False
        return
    assert result.bundled is True
    assert result.sans == "Space Grotesk"
    assert result.mono == "JetBrains Mono"
    assert result.brand == "Rajdhani"


# --- role art -------------------------------------------------------------
def test_every_role_has_a_glyph():
    for role in assets.ROLES:
        image = assets.role_icon(role, 12)
        assert isinstance(image, Image.Image)
        assert image.size == (12, 12)


def test_an_unknown_role_renders_nothing_rather_than_erroring():
    assert assets.role_icon("flex") is None


def test_map_thumbs_return_none_until_something_is_fetched():
    thumbs = assets.MapThumbs()
    assert thumbs.get(None) is None
    assert thumbs.get("https://web.example/game/maps/busan.jpg") is None


def test_a_failed_thumbnail_fetch_never_calls_back(monkeypatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    called = []
    thumbs = assets.MapThumbs()
    thumbs.fetch("https://web.example/game/maps/busan.jpg", lambda: called.append(1))
    for _ in range(200):
        if thumbs._cache.get("https://web.example/game/maps/busan.jpg") is not None:
            break
    assert called == []


# --- backdrop -------------------------------------------------------------
def test_the_field_covers_the_whole_grid():
    values = topography.field(6, 4)
    assert len(values) == 24
    assert all(0.0 <= v <= 1.5 for v in values)


def test_the_field_is_deterministic():
    """The backdrop is static by owner decision - same size, same texture."""
    assert topography.field(12, 9) == topography.field(12, 9)


def test_contours_appear_between_levels_and_not_outside_them():
    values = [0.0] * 4 + [1.0] * 4  # a 4x2 field split down the middle
    assert topography.contour_segments(values, 4, 2, 0.5)
    assert topography.contour_segments(values, 4, 2, 2.0) == []


def test_the_backdrop_renders_at_the_requested_size():
    image = topography.Backdrop(120, 90, theme.PAGE).render()
    assert image.size == (120, 90)


def test_the_backdrop_is_texture_not_decoration():
    """No pixel may get near the accent colour - the lines are a 7-16% wash.

    Crossing isolines stack, so the worst pixel is a few overlaps deep; it still
    has to stay in the bottom third of the distance to full-strength indigo.
    """
    image = topography.Backdrop(240, 180, theme.PAGE).render()
    page = theme.rgb(theme.PAGE)
    full = sum(abs(c - p) for c, p in zip(topography.PRIMARY_RGB, page))
    worst = max(sum(abs(c - p) for c, p in zip(px, page)) for px in image.getdata())
    assert worst < full * 0.35


def test_the_backdrop_does_not_animate():
    """Two renders of one size are identical - nothing repaints over a game."""
    drop = topography.Backdrop(120, 90, theme.PAGE)
    assert list(drop.render().getdata()) == list(drop.render().getdata())


def test_the_backdrop_actually_draws_contours():
    image = topography.Backdrop(240, 180, theme.PAGE).render()
    assert len(set(image.getdata())) > 1, "the field rendered as flat colour"
