"""System-tray (toolbar) driver for the capture agent.

Wraps the shared :class:`~overanalyzer_agent.controller.CaptureController` in a
``pystray`` tray icon: a menu (capture summary / scoreboard, reset, settings,
reload, quit), the same global hotkeys as the CLI, a colour-coded icon that
reflects the current state, and balloon toasts via ``pystray``'s own ``notify``
(so no extra toast dependency). Capture/upload runs on a worker thread to keep
the menu responsive while OCR is polled.

``pystray`` and ``keyboard`` are imported lazily inside :func:`run_tray` so this
module - and ``make_icon_image`` in particular - import cleanly under CI without
a display.
"""
from __future__ import annotations

import os
import threading
import webbrowser
from typing import Callable

from PIL import Image, ImageDraw

from overanalyzer_agent.config import AgentConfig, DEFAULT_CONFIG_PATH, load_config
from overanalyzer_agent.controller import CaptureController, Status, StatusEvent
from overanalyzer_agent.hotkeys import HotkeyManager
from overanalyzer_agent.ui import brand, theme
from overanalyzer_agent.ui.sound import play_shutter

APP_NAME = "OverAnalyzer"

# State -> accent colour for the tray badge. These are the design system's data
# colours (win / draw / loss / primary), so the badge reads like the web app.
STATE_COLORS: dict[Status, tuple[int, int, int]] = {
    Status.IDLE: theme.rgb(theme.PRIMARY),  # indigo - ready
    Status.BUSY: theme.rgb(theme.DRAW),  # amber - working
    Status.OK: theme.rgb(theme.WIN),  # emerald - uploaded
    Status.NEEDS_REVIEW: theme.rgb(theme.DRAW),
    Status.ERROR: theme.rgb(theme.LOSS),
}
_BG = theme.rgb(theme.SIDEBAR)  # the app's violet-navy chrome


def make_icon_image(state: Status, size: int = 64) -> Image.Image:
    """The OverAnalyzer mark, with a small state-coloured dot over one corner.

    The tray icon is "the app icon" in the sense a user means it - it should be
    recognisably the product, not an abstract badge. Status still needs an
    at-a-glance signal, so it becomes a notification-style dot instead of being
    the whole icon.
    """
    img = brand.icon(size).copy()
    draw = ImageDraw.Draw(img)
    accent = STATE_COLORS.get(state, STATE_COLORS[Status.IDLE])
    r = max(3, size // 6)
    cx, cy = size - r - size // 14, size - r - size // 14
    ring = max(2, size // 20)
    draw.ellipse((cx - r - ring, cy - r - ring, cx + r + ring, cy + r + ring), fill=_BG)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=accent)
    return img


class TrayApp:
    """Owns the controller, the tray icon, hotkeys, and the worker-thread guard."""

    def __init__(self, cfg: AgentConfig, config_path: str | None = None) -> None:
        self.cfg = cfg
        self.config_path = config_path
        self.controller = CaptureController(cfg, listener=self._on_event, on_shot=play_shutter)
        self._icon = None  # pystray.Icon, created in run()
        self._busy_lock = threading.Lock()
        self._hotkeys = HotkeyManager()
        self._last_message = "Ready."
        self._last_state = Status.IDLE
        self._paused = False

    # --- status plumbing -------------------------------------------------
    def _on_event(self, event: StatusEvent) -> None:
        self._last_message = event.message
        self._last_state = event.status
        if self._icon is not None:
            self._icon.icon = make_icon_image(event.status)
            self._icon.title = f"{APP_NAME} - {event.message}"
            self._icon.update_menu()
            # Toast on settled outcomes (not on transient BUSY churn).
            if event.status is not Status.BUSY:
                self._icon.notify(event.message, APP_NAME)

    def _run_async(self, fn: Callable[[], object]) -> None:
        """Run a capture/upload action off the UI thread; drop re-entrant clicks."""
        if not self._busy_lock.acquire(blocking=False):
            self._on_event(StatusEvent(Status.BUSY, "Still working on the last capture…"))
            return

        def worker() -> None:
            try:
                fn()
            finally:
                self._busy_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    # --- menu actions ----------------------------------------------------
    def _capture_summary(self, *_a) -> None:
        self._run_async(self.controller.capture_summary)

    def _capture_scoreboard(self, *_a) -> None:
        self._run_async(self.controller.capture_scoreboard)

    def _reset(self, *_a) -> None:
        self.controller.reset()

    def _toggle_capture(self, *_a) -> None:
        """Pause/resume the hotkeys without ending the process."""
        if self._paused:
            self._paused = False
            self._register_hotkeys()
            self._on_event(StatusEvent(Status.IDLE, "Capture resumed."))
        else:
            self._paused = True
            self._unhook_hotkeys()
            self._on_event(StatusEvent(Status.IDLE, "Capture paused."))

    def _open_dashboard(self, *_a) -> None:
        url = self.cfg.web_url or self.cfg.api_url
        if url:
            webbrowser.open(url)

    def status_label(self) -> str:
        """The menu's top line - the design's "Connected · capture on"."""
        if self._paused:
            return "Capture paused"
        return "Connected · capture on"

    def _open_config(self, *_a) -> None:
        path = self.config_path or str(DEFAULT_CONFIG_PATH)
        try:
            os.startfile(path)  # type: ignore[attr-defined]  # Windows-only
        except OSError as exc:
            self._on_event(StatusEvent(Status.ERROR, f"Couldn't open {path}: {exc}"))

    def _reload_config(self, *_a) -> None:
        try:
            self.cfg = load_config(self.config_path)
        except (OSError, ValueError) as exc:
            self._on_event(StatusEvent(Status.ERROR, f"Reload failed: {exc}"))
            return
        self.controller.cfg = self.cfg
        self._register_hotkeys()  # rebind in case hotkeys changed
        self._on_event(StatusEvent(Status.IDLE, "Config reloaded."))

    def _open_panel(self, screen: str) -> None:
        """Show the capture panel (Tk needs its own loop, so: its own thread)."""
        from overanalyzer_agent.window import open_window

        def run() -> None:
            open_window(self.cfg, self.config_path, screen=screen)
            self.cfg = load_config(self.config_path)  # the panel saves as it goes
            self.controller.cfg = self.cfg
            self._register_hotkeys()

        threading.Thread(target=run, daemon=True).start()

    def _show_panel(self, *_a) -> None:
        self._open_panel("main")

    def _open_settings(self, *_a) -> None:
        self._open_panel("settings")

    def _quit(self, *_a) -> None:
        self._unhook_hotkeys()
        if self._icon is not None:
            self._icon.stop()

    # --- hotkeys ---------------------------------------------------------
    def _register_hotkeys(self) -> None:
        err = self._hotkeys.register(
            {
                self.cfg.hotkey_summary: self._capture_summary,
                self.cfg.hotkey_scoreboard: self._capture_scoreboard,
                # F9 pauses rather than resets, matching the panel and the design;
                # "Reset buffer" stays available from the menu.
                self.cfg.hotkey_reset: self._toggle_capture,
            }
        )
        if err:
            self._on_event(StatusEvent(Status.IDLE, f"Hotkeys unavailable ({err}); use the menu."))

    def _unhook_hotkeys(self) -> None:
        self._hotkeys.unregister()

    # --- run -------------------------------------------------------------
    def build_menu(self):
        import pystray

        Item = pystray.MenuItem
        keys = self.cfg
        return pystray.Menu(
            Item(lambda _i: self.status_label(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            Item(f"Capture summary\t{keys.hotkey_summary.upper()}", self._capture_summary),
            Item(f"Scoreboard + upload\t{keys.hotkey_scoreboard.upper()}",
                 self._capture_scoreboard),
            Item(
                lambda _i: ("Resume capture" if self._paused else "Pause capture")
                + f"\t{keys.hotkey_reset.upper()}",
                self._toggle_capture,
            ),
            Item("Reset buffer", self._reset),
            pystray.Menu.SEPARATOR,
            Item("Show panel", self._show_panel, default=True),
            Item("Open dashboard", self._open_dashboard),
            Item("Settings", self._open_settings),
            Item("Open config file", self._open_config),
            Item("Reload config", self._reload_config),
            pystray.Menu.SEPARATOR,
            Item("Quit", self._quit),
        )

    def run(self) -> None:
        import pystray

        self._icon = pystray.Icon(
            APP_NAME,
            icon=make_icon_image(Status.IDLE),
            title=f"{APP_NAME} - Ready",
            menu=self.build_menu(),
        )
        self._register_hotkeys()
        self._icon.run()


def run_tray(cfg: AgentConfig, config_path: str | None = None) -> None:
    TrayApp(cfg, config_path).run()
