"""The toast must never take focus away from the game.

A toast fires at exactly the moment the player is in a match, so anything that
activates a window here tabs them out of Overwatch. These tests pin the two
defences: the window is built once and reused, and it is marked never-activate.
Tk is faked so this runs with no display.
"""
from __future__ import annotations

import sys
import types

import pytest

from overanalyzer_agent.ui import toast
from overanalyzer_agent.ui.fonts import FontSet


class FakeTclError(Exception):
    pass


class FakeWidget:
    """Records the calls the toast makes, and nothing else."""

    def __init__(self, *args, **kwargs) -> None:
        self.kwargs = dict(kwargs)
        self.packed = False
        self.calls: list[str] = []

    def pack(self, **_kw) -> None:
        self.packed = True

    def pack_forget(self) -> None:
        self.packed = False

    def configure(self, **kwargs) -> None:
        self.kwargs.update(kwargs)

    def bind(self, *_a, **_kw) -> None:
        pass


class FakeToplevel(FakeWidget):
    created = 0

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        FakeToplevel.created += 1
        self.shown = False
        self.geometry = ""

    def wm_overrideredirect(self, _flag) -> None:
        self.calls.append("overrideredirect")

    def attributes(self, *_a) -> None:
        self.calls.append("attributes")

    def withdraw(self) -> None:
        self.shown = False
        self.calls.append("withdraw")

    def deiconify(self) -> None:
        self.shown = True
        self.calls.append("deiconify")

    def destroy(self) -> None:
        self.calls.append("destroy")

    def update_idletasks(self) -> None:
        pass

    def winfo_reqheight(self) -> int:
        return 72

    def winfo_screenwidth(self) -> int:
        return 1920

    def winfo_screenheight(self) -> int:
        return 1080

    def winfo_id(self) -> int:
        return 1234

    def wm_geometry(self, value: str) -> None:
        self.geometry = value


class FakeMaster:
    def __init__(self) -> None:
        self.scheduled: list[int] = []

    def after(self, delay, _fn) -> str:
        self.scheduled.append(delay)
        return "after#1"

    def after_cancel(self, _handle) -> None:
        pass


@pytest.fixture
def toaster(monkeypatch: pytest.MonkeyPatch) -> toast.Toaster:
    FakeToplevel.created = 0
    fake_tk = types.SimpleNamespace(
        Toplevel=FakeToplevel, Frame=FakeWidget, Label=FakeWidget, TclError=FakeTclError
    )
    monkeypatch.setattr(toast, "tk", fake_tk)
    monkeypatch.setattr(toast, "tkfont", types.SimpleNamespace(Font=lambda **_kw: "font"))
    monkeypatch.setattr(toast, "ImageTk", types.SimpleNamespace(PhotoImage=lambda image: image))
    monkeypatch.setattr(toast.icons, "icon", lambda *_a, **_kw: "image")
    # The platform hooks are ctypes calls; they are exercised separately.
    monkeypatch.setattr(toast, "_apply_noactivate", lambda _w: None)
    monkeypatch.setattr(toast, "_show_without_activating", lambda _w: None)
    return toast.Toaster(FakeMaster(), FontSet.fallback())


def test_the_window_is_built_once_at_startup(toaster: toast.Toaster) -> None:
    assert FakeToplevel.created == 1
    assert toaster._window is not None
    assert not toaster._window.shown, "the toast must start hidden"


def test_showing_twice_reuses_the_same_window(toaster: toast.Toaster) -> None:
    toaster.show("ok", "Uploaded", "match complete")
    toaster.show("error", "Upload failed", "check your connection")
    # The regression this guards: constructing a Toplevel mid-match is itself the
    # activation that pulls the player out of the game.
    assert FakeToplevel.created == 1


def test_hide_keeps_the_window_for_next_time(toaster: toast.Toaster) -> None:
    toaster.show("ok", "Uploaded")
    toaster.hide()
    assert toaster._window is not None
    assert not toaster._window.shown
    toaster.show("ok", "Uploaded again")
    assert FakeToplevel.created == 1


def test_destroy_tears_the_window_down(toaster: toast.Toaster) -> None:
    window = toaster._window
    toaster.destroy()
    assert toaster._window is None
    assert window is not None and "destroy" in window.calls


def test_the_tone_sets_the_accent_and_the_detail_line(toaster: toast.Toaster) -> None:
    toaster.show("review", "Uploaded", "needs review")
    assert toaster._edge is not None
    assert toaster._edge.kwargs["bg"] == toast.TONES["review"][0]
    assert toaster._detail is not None and toaster._detail.packed

    toaster.show("ok", "Uploaded")
    assert not toaster._detail.packed, "an empty detail line must not reserve space"


def test_a_missing_display_leaves_a_silent_toaster(monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(*_a, **_kw):
        raise FakeTclError("no display name and no $DISPLAY environment variable")

    monkeypatch.setattr(
        toast, "tk", types.SimpleNamespace(Toplevel=_explode, TclError=FakeTclError)
    )
    quiet = toast.Toaster(FakeMaster(), FontSet.fallback())
    assert quiet._window is None
    quiet.show("ok", "Uploaded")  # must not raise
    quiet.hide()


def test_noactivate_sets_both_bits() -> None:
    assert toast.noactivate_exstyle(0) == toast.WS_EX_NOACTIVATE | toast.WS_EX_TOOLWINDOW


def test_noactivate_preserves_existing_style_bits() -> None:
    existing = 0x00000008  # WS_EX_TOPMOST, which the toast also sets via Tk
    result = toast.noactivate_exstyle(existing)
    assert result & existing == existing
    assert result & toast.WS_EX_NOACTIVATE
    assert result & toast.WS_EX_TOOLWINDOW


def test_noactivate_is_idempotent() -> None:
    once = toast.noactivate_exstyle(0)
    assert toast.noactivate_exstyle(once) == once


@pytest.mark.skipif(sys.platform != "win32", reason="the focus fix is Windows-only")
def test_the_style_helpers_never_raise_on_a_bad_handle() -> None:
    class Unrealized:
        def winfo_id(self) -> int:
            return 0

    toast._apply_noactivate(Unrealized())
    toast._show_without_activating(Unrealized())
