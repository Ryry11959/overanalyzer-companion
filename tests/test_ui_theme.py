"""Design tokens: the colour maths, and that the values match the design system."""
from overanalyzer_agent.ui import theme


def test_hsl_matches_the_design_systems_values():
    # tokens/colors.css: --background 248 28% 8%, --primary 250 84% 67%.
    assert theme.PAGE == theme.hsl(248, 28, 8)
    assert theme.PRIMARY == theme.hsl(250, 84, 67)
    assert theme.hsl(0, 0, 100) == "#ffffff"
    assert theme.hsl(0, 0, 0) == "#000000"


def test_rgb_round_trips():
    assert theme.rgb("#34d399") == (0x34, 0xD3, 0x99)
    assert theme.rgb(theme.PAGE) == theme.rgb(theme.PAGE.upper().replace("#", "#"))


def test_over_flattens_alpha_against_the_surface_behind():
    assert theme.over("#ffffff", "#000000", 0.0) == "#000000"
    assert theme.over("#ffffff", "#000000", 1.0) == "#ffffff"
    assert theme.over("#ffffff", "#000000", 0.5) == "#808080"


def test_paused_banner_sits_between_the_page_and_the_draw_colour():
    """A 6% amber wash has to stay much closer to the page than to the amber."""
    assert theme.PAUSED_BG != theme.PAGE
    page, banner, draw = (theme.rgb(c) for c in (theme.PAGE, theme.PAUSED_BG, theme.DRAW))
    to_page = sum(abs(b - p) for b, p in zip(banner, page))
    to_draw = sum(abs(b - d) for b, d in zip(banner, draw))
    assert to_page < to_draw


def test_shift_moves_lightness_without_changing_hue():
    lighter = theme.shift(theme.PRIMARY, 10)
    assert lighter != theme.PRIMARY
    # Hue is preserved: the channel ordering (b > r > g for indigo) survives.
    r, g, b = theme.rgb(lighter)
    assert b > r > g


def test_shift_clamps_at_the_ends():
    assert theme.shift("#ffffff", 50) == "#ffffff"
    assert theme.shift("#000000", -50) == "#000000"


def test_radii_stay_small():
    """shared design tokens: 6px reads "tool", large radii read "AI slop"."""
    assert theme.RADIUS == 6
    assert theme.RADIUS_MD == 4
    assert theme.RADIUS_SM == 2
