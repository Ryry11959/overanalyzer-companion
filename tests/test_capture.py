import sys
import types

import numpy as np
from PIL import Image

from overanalyzer_agent import capture
from overanalyzer_agent.config import AgentConfig

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_to_png_bytes_is_png():
    data = capture.to_png_bytes(Image.new("RGB", (8, 8), (255, 0, 0)))
    assert data[:8] == PNG_MAGIC


def test_crop_region_size():
    out = capture.crop_region(Image.new("RGB", (100, 100)), (10, 20, 40, 80))
    assert out.size == (30, 60)


def test_find_anchor_returns_box():
    arr = np.zeros((120, 200, 3), dtype=np.uint8)
    arr[10:90, 30:60] = (1, 186, 249)  # rows 10..89, cols 30..59
    box = capture.find_leaderboard_anchor(Image.fromarray(arr), [(1, 186, 249)], 50)
    assert box == (30, 10, 80, 89)


def test_find_anchor_none_when_absent():
    img = Image.new("RGB", (50, 50), (0, 0, 0))
    assert capture.find_leaderboard_anchor(img, [(1, 186, 249)], 50) is None


def test_capture_summary_uses_frame():
    cfg = AgentConfig(summary_region=(0, 0, 10, 20))
    data = capture.capture_summary(cfg, frame=Image.new("RGB", (50, 50), (9, 9, 9)))
    assert data[:8] == PNG_MAGIC


def test_capture_leaderboards_region_mode():
    cfg = AgentConfig(
        leaderboard_mode="region",
        team1_region=(0, 0, 20, 10),
        team2_region=(0, 10, 20, 20),
    )
    t1, t2 = capture.capture_leaderboards(cfg, frame=Image.new("RGB", (40, 40)))
    assert t1[:8] == PNG_MAGIC and t2[:8] == PNG_MAGIC


def test_capture_leaderboards_anchor_mode_both_sides():
    arr = np.zeros((100, 200, 3), dtype=np.uint8)
    arr[20:60, 10:40] = (1, 186, 249)  # blue (own team)
    arr[20:60, 120:150] = (232, 45, 80)  # red (enemy)
    cfg = AgentConfig(leaderboard_width=30)
    t1, t2 = capture.capture_leaderboards(cfg, frame=Image.fromarray(arr))
    assert t1 is not None and t2 is not None


def test_capture_leaderboards_anchor_missing_side_is_none():
    arr = np.zeros((100, 200, 3), dtype=np.uint8)
    arr[20:60, 10:40] = (1, 186, 249)  # only blue present
    cfg = AgentConfig(leaderboard_width=30)
    t1, t2 = capture.capture_leaderboards(cfg, frame=Image.fromarray(arr))
    assert t1 is not None and t2 is None


# --- multi-monitor ----------------------------------------------------------
class _FakeGrab:
    def __init__(self, w, h):
        self.size = (w, h)
        self.bgra = bytes(w * h * 4)


class _FakeSct:
    def __init__(self, monitors):
        self.monitors = monitors

    def grab(self, monitor):
        return _FakeGrab(monitor["width"], monitor["height"])

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


_TWO_MONITORS = [
    {"left": 0, "top": 0, "width": 3840, "height": 1080},  # 0: synthetic "all" bbox
    {"left": 0, "top": 0, "width": 1920, "height": 1080},  # 1: primary
    {"left": 1920, "top": 0, "width": 1600, "height": 900},  # 2: secondary
]


def _install_fake_mss(monkeypatch, monitors):
    fake = types.ModuleType("mss")
    fake.mss = lambda: _FakeSct(monitors)
    monkeypatch.setitem(sys.modules, "mss", fake)


def test_list_monitors_excludes_the_synthetic_all_bbox(monkeypatch):
    _install_fake_mss(monkeypatch, _TWO_MONITORS)
    monitors = capture.list_monitors()
    assert [m["index"] for m in monitors] == [1, 2]
    assert monitors[1] == {"index": 2, "width": 1600, "height": 900, "left": 1920, "top": 0}


def test_grab_screen_defaults_to_the_primary_monitor(monkeypatch):
    _install_fake_mss(monkeypatch, _TWO_MONITORS)
    assert capture.grab_screen().size == (1920, 1080)
    assert capture.grab_screen(None).size == (1920, 1080)


def test_grab_screen_selects_the_given_monitor(monkeypatch):
    _install_fake_mss(monkeypatch, _TWO_MONITORS)
    assert capture.grab_screen(2).size == (1600, 900)


def test_grab_screen_falls_back_to_primary_for_an_unplugged_monitor(monkeypatch):
    """A saved index for a monitor that's no longer connected must not crash."""
    _install_fake_mss(monkeypatch, _TWO_MONITORS)
    assert capture.grab_screen(5).size == (1920, 1080)
