"""The SVG path flattener and the lucide glyph renderer."""
import math

import pytest
from PIL import Image

from overanalyzer_agent.ui import icons
from overanalyzer_agent.ui.svgpath import flatten_path


def _bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


# --- path flattening ------------------------------------------------------
def test_absolute_and_relative_lines_agree():
    absolute = flatten_path("M2 2 L10 2 L10 8")
    relative = flatten_path("m2 2 l8 0 l0 6")
    assert absolute == relative


def test_horizontal_and_vertical_shorthands():
    assert flatten_path("M5 9h14") == [[(5.0, 9.0), (19.0, 9.0)]]
    assert flatten_path("M12 2v10") == [[(12.0, 2.0), (12.0, 12.0)]]


def test_implicit_lineto_after_a_moveto():
    """"m6 9 6 6 6-6" is a moveto followed by two implicit linetos."""
    assert flatten_path("m6 9 6 6 6-6") == [[(6.0, 9.0), (12.0, 15.0), (18.0, 9.0)]]


def test_closepath_returns_to_the_subpath_start():
    subpaths = flatten_path("M2 2 L10 2 L10 10 Z")
    assert subpaths[0][0] == subpaths[0][-1] == (2.0, 2.0)


def test_multiple_subpaths_stay_separate():
    assert len(flatten_path("M0 0 L1 1 M5 5 L6 6")) == 2


def test_cubic_curve_ends_where_it_should():
    points = flatten_path("M0 0 C0 10 10 10 10 0")[0]
    assert points[-1] == pytest.approx((10.0, 0.0))
    assert max(p[1] for p in points) > 5  # it actually bulges


def test_arc_traces_a_circle_of_the_right_radius():
    # Two half-arcs of r=5 around (5, 0) starting at the origin.
    points = flatten_path("M0 0 A5 5 0 0 1 10 0 A5 5 0 0 1 0 0")[0]
    radii = [math.dist((5.0, 0.0), p) for p in points]
    assert max(radii) == pytest.approx(5.0, abs=0.01)
    assert min(radii) == pytest.approx(5.0, abs=0.01)


def test_degenerate_arc_degrades_to_a_line():
    assert flatten_path("M0 0 A0 0 0 0 1 10 0")[0][-1] == (10.0, 0.0)


# --- glyph rendering ------------------------------------------------------
def test_every_declared_icon_renders():
    for name in icons.LUCIDE:
        image = icons.render(name, 16, "#ffffff")
        assert isinstance(image, Image.Image)
        assert image.size == (16, 16)
        assert image.getbbox() is not None, f"{name} rendered empty"


def test_glyphs_stay_inside_the_box():
    for name in icons.LUCIDE:
        left, top, right, bottom = icons.render(name, 24, "#ffffff").getbbox()
        assert left >= 0 and top >= 0 and right <= 24 and bottom <= 24


def test_shapes_are_flattened_within_the_24px_viewbox():
    for name in icons.LUCIDE:
        for line in icons.polylines(name):
            x0, y0, x1, y1 = _bbox(line)
            assert -1 <= x0 and -1 <= y0 and x1 <= 25 and y1 <= 25, name


def test_render_uses_the_colour_it_is_given():
    image = icons.render("x", 24, "#fb7185")
    opaque = [p for p in image.getdata() if p[3] > 200]
    assert opaque and all(p[:3] == (0xFB, 0x71, 0x85) for p in opaque)


def test_a_dot_path_still_draws_something():
    """lucide writes dots as a zero-length segment ("M12 17h.01")."""
    assert icons.render("triangle-alert", 24).getbbox() is not None


def test_unknown_icon_is_a_clear_error():
    with pytest.raises(KeyError):
        icons.polylines("definitely-not-an-icon")


def test_icons_are_cached():
    assert icons.icon("pause", 16, "#ffffff") is icons.icon("pause", 16, "#ffffff")
