"""Capture on a screen that isn't the author's.

Two hardcoded assumptions used to make this a hard failure BEFORE any OCR ran:
absolute pixel geometry tuned to one 1920x1080 desktop, and four exact RGB
triplets for the team bars. A different resolution cropped the wrong rectangle;
Overwatch's colourblind palettes produced a frame where the anchor scan matched nothing
at all and the scoreboard was simply never captured.
"""
import numpy as np
import pytest
from PIL import Image

from overanalyzer_agent import capture
from overanalyzer_agent.config import (
    REFERENCE_FRAME,
    REFERENCE_SUMMARY_REGION,
    AgentConfig,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# --- proportional geometry ----------------------------------------------------
def test_reference_resolution_is_unchanged():
    """1080p must map to exactly the coordinates that were hand-tuned there."""
    assert capture.resolve_summary_region(AgentConfig(), REFERENCE_FRAME) == REFERENCE_SUMMARY_REGION


@pytest.mark.parametrize("size", [(2560, 1440), (3840, 2160), (1280, 720)])
def test_geometry_scales_with_a_16_9_display(size):
    """Same 16:9 shape, different pixel count: the crop scales, nothing shifts."""
    box = capture.resolve_summary_region(AgentConfig(), size)
    scale = size[0] / REFERENCE_FRAME[0]
    assert box == tuple(round(v * scale) for v in REFERENCE_SUMMARY_REGION)
    # And it stays inside the frame, which the old absolute box did not.
    assert 0 <= box[0] < box[2] <= size[0]
    assert 0 <= box[1] < box[3] <= size[1]


def test_ultrawide_gets_the_ui_box_centred():
    """On 21:9 the UI is pillarboxed, so coordinates shift right by the margin."""
    size = (3440, 1440)
    x, y, scale = capture.ui_rect(size)
    assert y == pytest.approx(0)  # height-limited: no vertical letterbox
    assert x > 0  # centred, not flush left
    box = capture.resolve_summary_region(AgentConfig(), size)
    assert box[0] > round(REFERENCE_SUMMARY_REGION[0] * scale)


def test_a_taller_than_16_9_display_letterboxes_instead():
    """16:10 is width-limited, so the offset lands on the vertical axis."""
    x, y, _ = capture.ui_rect((1920, 1200))
    assert x == pytest.approx(0)
    assert y == pytest.approx(60)  # (1200 - 1080) / 2


def test_an_explicit_region_overrides_the_derived_one():
    cfg = AgentConfig(summary_region=(1, 2, 3, 4))
    assert capture.resolve_summary_region(cfg, (2560, 1440)) == (1, 2, 3, 4)


def test_leaderboard_width_scales_and_can_be_overridden():
    assert capture.resolve_leaderboard_width(AgentConfig(), REFERENCE_FRAME) == 850
    assert capture.resolve_leaderboard_width(AgentConfig(), (3840, 2160)) == 1700
    assert capture.resolve_leaderboard_width(AgentConfig(leaderboard_width=900), (3840, 2160)) == 900


def test_summary_capture_on_a_1440p_frame_is_not_clipped():
    """End to end: the old absolute box ran off a 1440p frame and cropped junk."""
    frame = Image.new("RGB", (2560, 1440), (20, 20, 20))
    assert capture.capture_summary(AgentConfig(), frame=frame)[:8] == PNG_MAGIC


# --- colour tolerance ---------------------------------------------------------
def _bars(team1: tuple, team2: tuple, size=(400, 300)) -> Image.Image:
    """A toy scoreboard: two wide colour bars, own team above the enemy."""
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    arr[40:110, 30:330] = team1
    arr[160:230, 30:330] = team2
    return Image.fromarray(arr)


def test_colour_matching_is_exact_by_default():
    """The default must stay exact - see color_tolerance in config.py.

    Widening the match let stray pixels elsewhere on screen stretch the anchor box
    (850x673 instead of ~850x330 on a real capture), which misaligns the row grid
    and garbles every stat. Opt in per-config, never by default.
    """
    assert AgentConfig().color_tolerance == 0
    assert AgentConfig().auto_team_colors is False

    frame = _bars((3, 188, 251), (230, 47, 82))  # a few off the configured triplets
    assert capture.capture_leaderboards(AgentConfig(leaderboard_width=300), frame=frame) == (
        None,
        None,
    )


def test_a_slightly_shifted_colour_anchors_when_tolerance_is_opted_into():
    frame = _bars((3, 188, 251), (230, 47, 82))
    cfg = AgentConfig(leaderboard_width=300, color_tolerance=24)

    t1, t2 = capture.capture_leaderboards(cfg, frame=frame)

    assert t1 is not None and t2 is not None


def test_exact_match_is_still_exact_when_tolerance_is_zero():
    arr = np.zeros((40, 40, 3), dtype=np.uint8)
    arr[10:20, 10:20] = (3, 188, 251)
    img = Image.fromarray(arr)
    assert capture.find_leaderboard_anchor(img, [(1, 186, 249)], 10, tolerance=0) is None
    assert capture.find_leaderboard_anchor(img, [(1, 186, 249)], 10, tolerance=24) is not None


# --- colourblind palettes -----------------------------------------------------
def test_colourblind_palette_is_sampled_off_the_frame():
    """The failure this whole path exists for.

    With Overwatch's colourblind options the bars are neither blue nor red - the
    configured triplets match zero pixels, and the old code returned (None, None):
    a silent, total capture failure. Detection keys on saturation and position, so
    an orange/purple lobby captures like any other.
    """
    frame = _bars((240, 160, 20), (150, 40, 220))  # orange friendly, purple enemy
    cfg = AgentConfig(leaderboard_width=300, auto_team_colors=True)

    t1, t2 = capture.capture_leaderboards(cfg, frame=frame)

    assert t1 is not None and t2 is not None


def test_detected_colours_are_ordered_own_team_first():
    """Teams are told apart by which block sits higher, not by hue."""
    team1, team2 = capture.detect_team_colors(_bars((240, 160, 20), (150, 40, 220)))
    assert team1 == [(240, 160, 20)]
    assert team2 == [(150, 40, 220)]


def test_detection_ignores_greyscale_ui():
    """Backgrounds, text and portraits are unsaturated; only bars should qualify."""
    arr = np.full((300, 400, 3), 90, dtype=np.uint8)  # flat grey, larger than any bar
    arr[40:110, 30:330] = (240, 160, 20)
    arr[160:230, 30:330] = (150, 40, 220)
    team1, team2 = capture.detect_team_colors(Image.fromarray(arr))
    assert team1 == [(240, 160, 20)] and team2 == [(150, 40, 220)]


def test_no_bars_means_no_detection():
    """A non-scoreboard frame must not invent two teams out of noise."""
    assert capture.detect_team_colors(Image.new("RGB", (400, 300), (12, 12, 12))) == ([], [])


def test_auto_detection_is_off_unless_asked_for():
    """Default behaviour: an unrecognised palette captures nothing, loudly."""
    cfg = AgentConfig(leaderboard_width=300)
    frame = _bars((240, 160, 20), (150, 40, 220))
    assert capture.capture_leaderboards(cfg, frame=frame) == (None, None)


def test_two_shades_of_one_bar_are_not_read_as_two_teams():
    """The highlighted row is a near-identical shade of the same bar colour."""
    arr = np.zeros((300, 400, 3), dtype=np.uint8)
    arr[40:110, 30:330] = (1, 184, 246)
    arr[110:130, 30:330] = (1, 186, 249)  # highlighted row, nearly the same colour
    team1, team2 = capture.detect_team_colors(Image.fromarray(arr))
    assert (team1, team2) == ([], [])
