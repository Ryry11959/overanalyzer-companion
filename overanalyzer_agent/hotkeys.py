"""Global-hotkey registration, tolerant of the ``keyboard`` library's quirks.

Binds hotkeys via ``keyboard`` and tracks the returned handles so re-binding
removes only *our* hotkeys. This deliberately avoids ``keyboard.clear_all_hotkeys()``,
which raises ``'_KeyboardListener' object has no attribute 'blocking_hotkeys'`` when
called before the listener has started (observed on Python 3.13) - the bug that
silently disabled the tray app's hotkeys. ``keyboard`` is imported lazily so this
module stays importable (and testable) without it.
"""
from __future__ import annotations

from typing import Callable


class HotkeyManager:
    """Registers/unregisters a set of global hotkeys, tracking handles."""

    def __init__(self) -> None:
        self._handles: list[object] = []
        self.active = False

    def register(self, bindings: dict[str, Callable[[], None]]) -> str | None:
        """Bind ``{hotkey: callback}``. Returns None on success, else an error string.

        Re-binding first removes any previously registered hotkeys, so this is safe
        to call repeatedly (e.g. after the user edits their keys).
        """
        try:
            import keyboard
        except Exception as exc:  # noqa: BLE001 - lib missing / import failure
            return f"keyboard library unavailable: {exc}"

        self.unregister()
        try:
            for combo, callback in bindings.items():
                self._handles.append(keyboard.add_hotkey(combo, callback))
        except Exception as exc:  # noqa: BLE001 - bad combo, permissions, etc.
            self.unregister()
            return f"could not bind hotkeys ({exc})"
        self.active = True
        return None

    def unregister(self) -> None:
        """Remove every hotkey we registered (best-effort)."""
        try:
            import keyboard
        except Exception:  # noqa: BLE001
            self._handles.clear()
            self.active = False
            return
        for handle in self._handles:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:  # noqa: BLE001 - already gone / listener quirk
                pass
        self._handles.clear()
        self.active = False
