"""HotkeyManager register/unregister against a fake ``keyboard`` module."""
import sys
import types

import pytest

from overanalyzer_agent.hotkeys import HotkeyManager


class _FakeKeyboard:
    def __init__(self):
        self.added = []
        self.removed = []
        self._n = 0

    def add_hotkey(self, combo, callback):
        if combo == "BAD":
            raise ValueError("bad combo")
        self._n += 1
        handle = (combo, self._n)
        self.added.append(handle)
        return handle

    def remove_hotkey(self, handle):
        self.removed.append(handle)


@pytest.fixture
def fake_keyboard(monkeypatch):
    fake = _FakeKeyboard()
    mod = types.ModuleType("keyboard")
    mod.add_hotkey = fake.add_hotkey
    mod.remove_hotkey = fake.remove_hotkey
    monkeypatch.setitem(sys.modules, "keyboard", mod)
    return fake


def test_register_binds_all_and_reports_active(fake_keyboard):
    mgr = HotkeyManager()
    err = mgr.register({"f11": lambda: None, "f12": lambda: None})
    assert err is None
    assert mgr.active is True
    assert len(fake_keyboard.added) == 2


def test_unregister_removes_only_our_handles(fake_keyboard):
    mgr = HotkeyManager()
    mgr.register({"f11": lambda: None, "f9": lambda: None})
    added = list(fake_keyboard.added)
    mgr.unregister()
    assert mgr.active is False
    assert fake_keyboard.removed == added


def test_reregister_clears_previous_first(fake_keyboard):
    mgr = HotkeyManager()
    mgr.register({"f11": lambda: None})
    first = fake_keyboard.added[0]
    mgr.register({"f5": lambda: None})
    assert first in fake_keyboard.removed  # old binding removed on re-register
    assert mgr.active is True


def test_register_failure_returns_error_and_rolls_back(fake_keyboard):
    mgr = HotkeyManager()
    err = mgr.register({"f11": lambda: None, "BAD": lambda: None})
    assert err is not None and "bind" in err
    assert mgr.active is False
    # the one that succeeded before the failure was rolled back
    assert len(fake_keyboard.removed) == 1


def test_register_without_keyboard_lib_returns_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyboard", None)  # import keyboard -> ImportError
    mgr = HotkeyManager()
    err = mgr.register({"f11": lambda: None})
    assert err is not None and "keyboard library unavailable" in err
    assert mgr.active is False
