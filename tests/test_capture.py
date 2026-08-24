import sys
import types
from io import BytesIO

from PIL import Image, ImageDraw

from overanalyzer_agent import capture
from overanalyzer_agent.config import AgentConfig

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _teams_frame(
    top=(20, 155, 210), bottom=(180, 30, 70), size=(1000, 600)
) -> Image.Image:
    frame = Image.new("RGB", size, (10, 15, 35))
    draw = ImageDraw.Draw(frame)
    width, height = size
    draw.rectangle((.25 * width, .18 * height, .75 * width, .58 * height), fill=top)
    draw.rectangle((.25 * width, .60 * height, .75 * width, .98 * height), fill=bottom)
    return frame


def test_full_frame_capture_preserves_the_source_dimensions() -> None:
    captured = capture.capture_full_frame(
        AgentConfig(), frame=Image.new("RGB", (123, 77), (9, 8, 7))
    )
    assert captured.png[:8] == PNG_MAGIC
    assert (captured.width, captured.height) == (123, 77)
    assert Image.open(BytesIO(captured.png)).size == (123, 77)


def test_game_report_guard_accepts_two_broad_team_areas() -> None:
    assert capture.looks_like_game_report(_teams_frame())


def test_game_report_guard_does_not_depend_on_exact_team_colours() -> None:
    assert capture.looks_like_game_report(
        _teams_frame(top=(240, 160, 20), bottom=(150, 40, 220))
    )


def test_game_report_guard_rejects_a_plain_desktop() -> None:
    assert not capture.looks_like_game_report(Image.new("RGB", (1920, 1080), (32, 34, 40)))


def test_required_guard_refuses_before_encoding() -> None:
    try:
        capture.capture_full_frame(
            AgentConfig(),
            frame=Image.new("RGB", (1920, 1080), (32, 34, 40)),
            require_game_report=True,
        )
    except capture.NotGameReportError:
        pass
    else:
        raise AssertionError("a non-report frame was accepted")


def test_the_client_has_no_crop_or_anchor_helpers() -> None:
    retired = {
        "crop_region", "find_leaderboard_anchor", "capture_summary",
        "capture_leaderboards", "detect_team_colors", "resolve_summary_region",
    }
    assert not [name for name in retired if hasattr(capture, name)]


class _FakeGrab:
    def __init__(self, width, height):
        self.size = (width, height)
        self.bgra = bytes(width * height * 4)


class _FakeSct:
    def __init__(self, monitors):
        self.monitors = monitors

    def grab(self, monitor):
        return _FakeGrab(monitor["width"], monitor["height"])

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


_TWO_MONITORS = [
    {"left": 0, "top": 0, "width": 3840, "height": 1080},
    {"left": 0, "top": 0, "width": 1920, "height": 1080},
    {"left": 1920, "top": 0, "width": 1600, "height": 900},
]


def _install_fake_mss(monkeypatch, monitors):
    fake = types.ModuleType("mss")
    fake.mss = lambda: _FakeSct(monitors)
    monkeypatch.setitem(sys.modules, "mss", fake)


def test_list_monitors_excludes_the_synthetic_all_bbox(monkeypatch):
    _install_fake_mss(monkeypatch, _TWO_MONITORS)
    monitors = capture.list_monitors()
    assert [monitor["index"] for monitor in monitors] == [1, 2]


def test_grab_screen_defaults_to_primary(monkeypatch):
    _install_fake_mss(monkeypatch, _TWO_MONITORS)
    assert capture.grab_screen().size == (1920, 1080)


def test_grab_screen_selects_the_configured_monitor(monkeypatch):
    _install_fake_mss(monkeypatch, _TWO_MONITORS)
    assert capture.grab_screen(2).size == (1600, 900)


def test_grab_screen_falls_back_after_a_monitor_is_unplugged(monkeypatch):
    _install_fake_mss(monkeypatch, _TWO_MONITORS)
    assert capture.grab_screen(5).size == (1920, 1080)
