"""The capture app's main window - a 360px overlay panel.

Direction 1A of the companion-app design: a frameless, always-on-top panel over
a topographic contour backdrop, with the settings screen living inside the same
frame rather than in a second window. It is drawn on one canvas
(:mod:`ui.surface`) from a pure layout (:mod:`ui.layout`), so state changes are
a single repaint and the backdrop shows through every gap.

The capture core is untouched: this drives the same
:class:`~overanalyzer_agent.controller.CaptureController` and
:class:`~overanalyzer_agent.hotkeys.HotkeyManager` the tray and CLI use. Tk is
imported lazily inside :meth:`CapturePanel.build` so the module - and the pure
helpers below - import cleanly under CI.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from overanalyzer_agent import (
    __version__, capturelog, matchinfo, removal, selftest, updater,
)
from overanalyzer_agent.config import AgentConfig, from_dict, save_config, to_dict
from overanalyzer_agent.controller import CaptureController, Status, StatusEvent
from overanalyzer_agent.hotkeys import HotkeyManager
from overanalyzer_agent.session import SessionStats, default_state_path
from overanalyzer_agent.ui import theme
from overanalyzer_agent.ui.sound import play_shutter
from overanalyzer_agent.ui.layout import LastCapture, PanelState

DEFAULT_HOTKEYS = {"summary": "f11", "scoreboard": "f12", "reset": "f9"}

# Status -> (colour for the activity dot, toast tone).
STATUS_COLORS: dict[Status, str] = {
    Status.IDLE: theme.TEXT_MUTED,
    Status.BUSY: theme.DRAW,
    Status.OK: theme.WIN,
    Status.NEEDS_REVIEW: theme.DRAW,
    Status.ERROR: theme.LOSS,
}
TOAST_TONE: dict[Status, str] = {
    Status.BUSY: "busy",
    Status.OK: "ok",
    Status.NEEDS_REVIEW: "review",
    Status.ERROR: "error",
}


def split_message(message: str) -> tuple[str, str]:
    """Split a status line into a toast title and its detail.

    Status messages come in two shapes: ``"Uploaded - match complete"`` from the
    controller's table, and a full explanatory sentence from an error path. The
    second shape used to become one enormous title, which is what made toasts
    read as truncated. Fall back to sentence-splitting so the title is always a
    short line and the rest becomes wrapped detail.
    """
    title, sep, detail = message.partition(" - ")
    if sep:
        return title.strip(), detail.strip()
    head, dot, tail = message.partition(". ")
    if dot:
        return head.strip() + ".", tail.strip()
    return message.strip(), ""


def build_config(
    base: AgentConfig,
    *,
    api_url: str,
    web_url: str,
    hotkey_summary: str,
    hotkey_scoreboard: str,
    hotkey_reset: str,
    bearer_token: str = "",
) -> AgentConfig:
    """Merge form values over ``base``, preserving what the panel doesn't edit.

    Pure + unit-tested. Blank hotkeys fall back to the defaults so capture always
    has bindings. There is deliberately no gamertag field because identity lives
    on the account, and no crop field because cropping is server-owned.
    """
    data = to_dict(base)
    data["api_url"] = api_url.strip()
    data["web_url"] = web_url.strip().rstrip("/")
    data["bearer_token"] = bearer_token.strip()
    data["hotkey_summary"] = hotkey_summary.strip() or DEFAULT_HOTKEYS["summary"]
    data["hotkey_scoreboard"] = hotkey_scoreboard.strip() or DEFAULT_HOTKEYS["scoreboard"]
    data["hotkey_reset"] = hotkey_reset.strip() or DEFAULT_HOTKEYS["reset"]
    return from_dict(data)


def host_of(url: str) -> str:
    """The host part of an API URL, for the status row's dense meta text."""
    parsed = urlparse(url if "//" in url else f"//{url}")
    return parsed.netloc or url


@dataclass(frozen=True)
class ConnectionCheck:
    """The result of testing the service and, when present, the device key."""

    connected: bool
    latency_ms: int | None
    message: str


def probe_connection(
    cfg: AgentConfig,
    *,
    request_get: Callable[..., object] | None = None,
    timeout: float = 8.0,
) -> ConnectionCheck:
    """Check the hosted service and validate a saved device key.

    ``/api/health`` is intentionally public, so it can only answer whether the
    service is reachable.  When a key is present, the existing authenticated
    ``/api/me/devices`` endpoint is the connection test: a 401 therefore means
    exactly what a first-time user needs to know, without adding a pairing API.
    """
    if request_get is None:
        import requests

        request_get = requests.get

    has_key = bool(cfg.bearer_token)
    path = "/api/me/devices" if has_key else "/api/health"
    url = cfg.api_url.rstrip("/") + path
    started = time.perf_counter()
    try:
        if has_key:
            response = request_get(
                url,
                headers={"Authorization": f"Bearer {cfg.bearer_token}"},
                timeout=timeout,
            )
        else:
            response = request_get(url, timeout=timeout)
    except Exception:  # noqa: BLE001 - connection diagnostics must stay actionable
        return ConnectionCheck(
            False,
            None,
            "Can't reach OverAnalyzer. Check your internet connection, then "
            "run the self test again. If it continues, check the service status.",
        )

    latency = round((time.perf_counter() - started) * 1000)
    status_code = int(getattr(response, "status_code", 0))
    if has_key and status_code == 401:
        return ConnectionCheck(
            False,
            None,
            "Device key rejected (invalid or revoked). Return to the web app's "
            "Settings → Devices, revoke the old key if needed, create one "
            "replacement, paste it here, then run the self test again.",
        )
    if has_key and status_code == 403:
        return ConnectionCheck(
            False,
            None,
            "This account cannot pair the capture app. Sign in to a writable "
            "account, create a device key, paste it here, then run the self test again.",
        )
    if status_code >= 400 or status_code == 0:
        return ConnectionCheck(
            False,
            None,
            f"OverAnalyzer returned HTTP {status_code} while checking the "
            "connection. Wait a little, then run the self test again.",
        )
    if has_key:
        return ConnectionCheck(
            True,
            latency,
            f"Device key accepted · {latency} ms. Go back and start capture.",
        )
    return ConnectionCheck(
        True,
        latency,
        f"Service reachable · {latency} ms, but no device key is saved. Sign in "
        "to the web app, create one key, paste it here, then run the self test.",
    )


def clamp_position(x: int, y: int, window_w: int, window_h: int,
                   screen_w: int, screen_h: int) -> tuple[int, int]:
    """Keep a remembered window position on-screen if the display setup changed."""
    max_x, max_y = max(0, screen_w - window_w), max(0, screen_h - window_h)
    return max(0, min(x, max_x)), max(0, min(y, max_y))


def monitor_options(monitors: list[dict]) -> list[tuple[str, int | None]]:
    """``(label, monitor_index)`` pairs for the settings dropdown.

    ``None`` (always first, "Primary display") means "don't pin one - use
    whichever mss calls primary", matching ``AgentConfig.monitor_index``'s
    default. Only monitors other than the primary get their own explicit entry;
    picking one of those is the whole point of the setting (running the game on
    a secondary display).
    """
    options: list[tuple[str, int | None]] = [("Primary display", None)]
    for m in monitors:
        if m["index"] == 1:
            continue
        options.append((f"Display {m['index']} - {m['width']} × {m['height']}", m["index"]))
    return options


class CapturePanel:
    """Owns the controller, hotkeys, panel state and the Tk surface."""

    def __init__(self, cfg: AgentConfig, config_path: str | None = None) -> None:
        self.cfg = cfg
        self.config_path = config_path
        self.debug_dir = capturelog.debug_dir(config_path)
        self.controller = CaptureController(
            cfg, listener=self._on_event, on_shot=play_shutter, recorder=self._record_attempt
        )
        self.hotkeys = HotkeyManager()
        self.stats = SessionStats.load(default_state_path(config_path))
        self._busy = threading.Lock()
        self.root = None
        self.surface = None
        self.toaster = None
        self._backdrop = None
        self._thumbs = None
        self._icon_image = None
        self._drag: tuple[int, int] | None = None
        # index -> label / label -> index for the monitor dropdown; populated in
        # build() once there's a real desktop to enumerate (mss is lazy-imported).
        self._monitor_options: list[tuple[str, int | None]] = [("Primary display", None)]
        # The release the service is announcing, once a check has found one.
        self._release = None
        # Ticket for connection determinations; see _check_connection.
        self._conn_ticket = 0

        self.state = PanelState(
            api_host=host_of(cfg.api_url),
            has_web_url=bool(cfg.web_url),
            hotkeys=self._hotkey_labels(),
            monitor_value=self._label_for(cfg.monitor_index),
            captured_today=self.stats.captured_today,
            last_upload_at=self.stats.last_upload_at,
            debug_count=len(capturelog.recent_attempts(self.debug_dir)),
        )

    # --- monitor selection --------------------------------------------------
    def _label_for(self, index: int | None) -> str:
        return next((label for label, i in self._monitor_options if i == index),
                    self._monitor_options[0][0])

    def _index_for(self, label: str) -> int | None:
        return next((i for l, i in self._monitor_options if l == label), None)

    def _load_monitors(self) -> None:
        """Best-effort: no monitors detected just means the dropdown stays hidden."""
        try:
            from overanalyzer_agent import capture

            self._monitor_options = monitor_options(capture.list_monitors())
        except Exception:  # noqa: BLE001 - headless/mss-less environments
            self._monitor_options = [("Primary display", None)]
        self.state.monitor_options = tuple(label for label, _ in self._monitor_options)
        self.state.monitor_value = self._label_for(self.cfg.monitor_index)

    def _on_change(self, key: str, value: str) -> None:
        if key != "monitor" or not value:
            return
        index = self._index_for(value)
        if index == self.cfg.monitor_index:
            return
        self.cfg.monitor_index = index
        self.controller.cfg = self.cfg
        self.state.monitor_value = value
        self._save()
        self._log(f"Capture monitor set to {value}.")

    def _hotkey_labels(self) -> dict[str, str]:
        return {
            "summary": self.cfg.hotkey_summary.upper(),
            "scoreboard": self.cfg.hotkey_scoreboard.upper(),
            "reset": self.cfg.hotkey_reset.upper(),
        }

    # --- controller plumbing (marshalled onto the Tk thread) ---------------
    def _on_ui(self, fn: Callable[[], None]) -> None:
        """Run ``fn`` on the Tk thread; a no-op once the window has gone.

        Workers outlive the window (a poll in flight when you hit Quit), and
        ``after`` on a destroyed root raises rather than being ignored.
        """
        root = self.root
        if root is None:
            return
        try:
            root.after(0, fn)
        except Exception:  # noqa: BLE001 - RuntimeError / TclError once torn down
            pass

    def _on_event(self, event: StatusEvent) -> None:
        self._on_ui(lambda e=event: self._apply_event(e))

    def _apply_event(self, event: StatusEvent) -> None:
        self.state.status_message = event.message
        self.state.status_color = STATUS_COLORS.get(event.status, theme.TEXT_MUTED)
        self.state.buffered = self.controller.has_summary
        self._mark_reachability(event)
        self._log(event.message)
        if event.status is not Status.BUSY:
            self._toast(event)
        if event.status in (Status.OK, Status.NEEDS_REVIEW) and event.match_id:
            self._record_upload(event)
        self._repaint()

    def _mark_reachability(self, event: StatusEvent) -> None:
        """Keep the connection indicator honest about what just happened.

        It used to be decided once, by a probe at startup, and never revisited.
        So a single unlucky launch left the panel reading Offline for the rest of
        the session while captures uploaded perfectly - the indicator was
        reporting an old fact rather than the current one.

        A completed upload is stronger evidence than any probe: the service was
        reached, it authenticated the device key, and it answered. A failure is
        weaker evidence, because most failures are not connectivity (OCR failed,
        quota, a refused key), so that only triggers a fresh probe and lets the
        probe decide.
        """
        if event.status in (Status.OK, Status.NEEDS_REVIEW):
            self._conn_ticket += 1  # supersede any probe still in flight
            self.state.connected = True
            self.state.latency_ms = None
        elif event.status is Status.ERROR:
            self._check_connection()

    def _toast(self, event: StatusEvent) -> None:
        if self.toaster is None or event.status is Status.IDLE:
            return
        title, detail = split_message(event.message)
        self.toaster.show(TOAST_TONE.get(event.status, "busy"), title, detail)

    def _record_upload(self, event: StatusEvent) -> None:
        """Count the upload, then try to read the match back for the card."""
        at = datetime.now().strftime("%H:%M")
        self.stats.record_upload(at)
        self.state.captured_today = self.stats.captured_today
        self.state.last_upload_at = self.stats.last_upload_at
        status = "needs_review" if event.status is Status.NEEDS_REVIEW else "complete"
        self.state.last = LastCapture(status=status, at=at, match_id=event.match_id)
        threading.Thread(
            target=self._enrich_last, args=(event.match_id, at), daemon=True
        ).start()

    def _enrich_last(self, match_id: str, at: str) -> None:
        """Best-effort: fill the card in with the real match. Never raises."""
        facts = matchinfo.fetch_match(
            self.cfg.api_url, match_id, bearer_token=self.cfg.bearer_token or None
        )
        if facts is None or self.root is None:
            return

        def apply() -> None:
            self.stats.record_result(facts.result)
            self.state.session_record = self.stats.record_label()
            self.state.session_hint = self.stats.record_hint()
            self.state.last = LastCapture(
                status=facts.status, at=at, match_id=facts.match_id,
                map_name=facts.map_name, result=facts.result, role=facts.role,
                duration=facts.duration, kd=facts.kd,
            )
            if facts.map_name and self.cfg.web_url and self._thumbs is not None:
                self._thumbs.fetch(
                    matchinfo.map_thumb_url(self.cfg.web_url, facts.map_name), self._repaint_soon
                )
            self._repaint()

        self._on_ui(apply)

    def _repaint_soon(self) -> None:
        self._on_ui(self._repaint)

    def _run_async(self, fn: Callable[[], object]) -> None:
        """Run capture/upload off the UI thread; drop overlapping triggers."""
        if not self._busy.acquire(blocking=False):
            self._apply_event(StatusEvent(Status.BUSY, "Still working on the last capture…"))
            return

        def worker() -> None:
            try:
                fn()
            finally:
                self._busy.release()

        threading.Thread(target=worker, daemon=True).start()

    # --- capture ----------------------------------------------------------
    def _capture_summary(self, *_a) -> None:
        self._run_async(self.controller.capture_summary)

    def _capture_scoreboard(self, *_a) -> None:
        self._run_async(self.controller.capture_scoreboard)

    # --- hotkeys ----------------------------------------------------------
    def _bindings(self) -> dict[str, Callable[[], None]]:
        return {
            self.cfg.hotkey_summary: self._capture_summary,
            self.cfg.hotkey_scoreboard: self._capture_scoreboard,
            self.cfg.hotkey_reset: self._toggle_capture,
        }

    def start_capture(self) -> bool:
        if self.state.connected is False:
            message = (
                "Capture cannot start until the connection is ready. Open Settings, "
                "fix the service or device key, then run the self test again."
            )
            self.state.status_message = message
            self.state.status_color = theme.LOSS
            self._log(message)
            self._toast(StatusEvent(Status.ERROR, message))
            self._repaint()
            return False
        err = self.hotkeys.register(self._bindings())
        if err:
            message = (
                f"Capture hotkeys could not start: {err}. Keep the app open and "
                "use the capture buttons instead."
            )
            self._log(message)
            self.state.status_message = message
            self.state.status_color = theme.DRAW
        else:
            self._log("Capture active - listening for your hotkeys.")
            self.state.status_message = "Capture active."
            self.state.status_color = theme.WIN
        self.state.capturing = True
        self._repaint()
        return True

    def pause_capture(self) -> None:
        self.hotkeys.unregister()
        self.state.capturing = False
        self.state.status_message = "Capture paused."
        self.state.status_color = theme.DRAW
        self._log("Capture paused.")
        self._repaint()

    def _toggle_capture(self, *_a) -> None:
        # Reachable from the F9 hotkey (a worker thread), so bounce to the UI one.
        if self.root is not None and threading.current_thread() is not threading.main_thread():
            self.root.after(0, self._toggle_capture)
            return
        self.pause_capture() if self.state.capturing else self.start_capture()

    def _record_hotkey(self, key: str) -> None:
        """Listen for the next keypress and bind it to ``key``."""
        self.state.recording = key
        self._repaint()

        def worker() -> None:
            try:
                import keyboard

                combo = keyboard.read_hotkey(suppress=False)
            except Exception as exc:  # noqa: BLE001
                self._on_ui(lambda: self._finish_record(key, None, str(exc)))
                return
            self._on_ui(lambda: self._finish_record(key, combo, None))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_record(self, key: str, combo: str | None, error: str | None) -> None:
        self.state.recording = None
        if error or not combo:
            self._log(f"Couldn't record a key: {error or 'nothing pressed'}")
        else:
            setattr(self.cfg, f"hotkey_{key}", combo)
            self.state.hotkeys = self._hotkey_labels()
            self._save(rebind=True)
        self._repaint()

    # --- settings ---------------------------------------------------------
    def _collect(self) -> AgentConfig:
        # The URLs aren't editable in the panel - captures always go to the same
        # place. They stay configurable in agent.toml for self-hosting, so they
        # are carried through from the loaded config rather than from a widget.
        return build_config(
            self.cfg,
            api_url=self.cfg.api_url,
            web_url=self.cfg.web_url,
            bearer_token=self.surface.entry("bearer_token", secret=True).get(),
            hotkey_summary=self.cfg.hotkey_summary,
            hotkey_scoreboard=self.cfg.hotkey_scoreboard,
            hotkey_reset=self.cfg.hotkey_reset,
        )

    def _save(self, *, rebind: bool = False) -> None:
        """Persist the current form. Settings apply as you go - there's no Save."""
        try:
            cfg = self._collect() if self.surface is not None else self.cfg
            path = save_config(cfg, self.config_path)
        except (ValueError, OSError) as exc:
            self._log(f"Couldn't save settings: {exc}")
            return
        self.cfg = cfg
        self.controller.cfg = cfg
        self.state.api_host = host_of(cfg.api_url)
        self.state.has_web_url = bool(cfg.web_url)
        self.state.hotkeys = self._hotkey_labels()
        self._log(f"Settings saved to {os.path.basename(str(path))}.")
        if rebind and self.hotkeys.active:
            self.hotkeys.register(self._bindings())

    def _check_connection(self, *, announce: bool = False) -> None:
        """Check service reachability and validate the saved device key.

        Each check takes a ticket. A probe applies its answer only if no newer
        determination has happened since it started, because these run on worker
        threads with an 8 second timeout: a slow startup probe could otherwise
        land after a self test or a successful upload and overwrite a fresher,
        better-evidenced answer with a stale one.
        """
        self._conn_ticket += 1
        ticket = self._conn_ticket
        if announce:
            self.state.status_message = "Checking the connection…"
            self.state.status_color = theme.DRAW
            self._repaint()

        def worker() -> None:
            result = probe_connection(self.cfg)

            def apply() -> None:
                if ticket != self._conn_ticket:
                    return
                self.state.connected = result.connected
                self.state.latency_ms = result.latency_ms
                if announce or not result.connected:
                    self.state.status_message = result.message
                    self.state.status_color = theme.WIN if result.connected else theme.LOSS
                    self._log(f"Connection: {result.message}")
                if announce:
                    self._toast(
                        StatusEvent(
                            Status.OK if result.connected else Status.ERROR,
                            result.message,
                        )
                    )
                self._repaint()

            self._on_ui(apply)

        threading.Thread(target=worker, daemon=True).start()

    def _test_capture(self) -> None:
        self.state.status_message = "Grabbing a test frame…"
        self.state.status_color = theme.DRAW
        self._repaint()

        def worker() -> None:
            from overanalyzer_agent import capture

            try:
                cfg = self._collect()
                captured = capture.capture_full_frame(cfg, require_game_report=True)
                message = f"Test capture ready - Teams screen {captured.width} x {captured.height}."
                colour = theme.WIN
            except capture.NotGameReportError:
                message = (
                    "Test capture was refused. Show the Game Report Teams screen on "
                    "the selected display and try again."
                )
                colour = theme.DRAW
            except Exception as exc:  # noqa: BLE001
                message = (
                    f"Test capture could not start: {exc}. Make sure the game is "
                    "visible on the selected display, then try again."
                )
                colour = theme.LOSS

            def apply() -> None:
                self.state.status_message = message
                self.state.status_color = colour
                self._log(message)
                self._repaint()

            self._on_ui(apply)

        threading.Thread(target=worker, daemon=True).start()

    # --- updates ------------------------------------------------------------
    def _check_for_update(self) -> None:
        """Ask the service whether a newer build exists. Quiet when it doesn't.

        Runs once at startup on a worker thread. A failed check is not reported:
        being offline is not an update problem, and the app keeps working.
        """
        def worker() -> None:
            release = updater.check_for_update(self.cfg, current_version=__version__)
            if release is None:
                return
            self._release = release

            def apply() -> None:
                self.state.update_version = release.version
                self.state.update_mandatory = release.mandatory
                note = f" {release.notes}" if release.notes else ""
                self._log(f"Update {release.version} is available.{note}")
                self._repaint()

            self._on_ui(apply)

        threading.Thread(target=worker, daemon=True).start()

    def _install_update(self) -> None:
        """Download, verify and swap, then quit so the helper can replace the EXE."""
        release = self._release
        if release is None or self.state.update_busy:
            return
        self.state.update_busy = True
        self.state.update_progress = "Downloading…"
        self._log(f"Downloading update {release.version}.")
        self._repaint()

        def on_progress(written: int, expected: int) -> None:
            if not expected:
                return
            percent = min(100, round(written * 100 / expected))
            # Only repaint on whole percents: this fires per 64 KiB chunk.
            if percent != getattr(self, "_last_percent", None):
                self._last_percent = percent
                self._on_ui(lambda: self._update_progress(f"Downloading… {percent}%"))

        def worker() -> None:
            try:
                report = updater.install_release(release, on_progress=on_progress)
            except updater.UpdateError as exc:
                def failed() -> None:
                    self.state.update_busy = False
                    self.state.update_progress = None
                    self.state.status_message = str(exc)
                    self.state.status_color = theme.LOSS
                    self._log(str(exc))
                    self._repaint()

                self._on_ui(failed)
                return

            def restart() -> None:
                self._log(
                    "Update verified. Closing to install it; the app will reopen. "
                    f"If it does not, see {report}."
                )
                self.state.update_progress = "Restarting…"
                self._repaint()
                # The helper is waiting on this process to exit before it can
                # replace a running executable.
                self.close()

            self._on_ui(restart)

        threading.Thread(target=worker, daemon=True).start()

    def _update_progress(self, text: str) -> None:
        self.state.update_progress = text
        self._repaint()

    # --- capture debug ------------------------------------------------------
    def _attempt_context(self) -> capturelog.Attempt:
        """The environment facts every attempt report carries. Never the key."""
        return capturelog.Attempt(
            outcome="",
            api_host=host_of(self.cfg.api_url),
            app_version=__version__,
            monitor=self.state.monitor_value or "Primary display",
        )

    def _record_attempt(self, outcome: str, detail: str, match_id: str | None,
                        frames: dict[str, str]) -> None:
        """Controller hook: keep metadata, never the uploaded frame pixels."""
        attempt = self._attempt_context()
        attempt.outcome = outcome
        attempt.detail = detail
        attempt.match_id = match_id
        attempt.frames = frames
        capturelog.record_attempt(attempt, directory=self.debug_dir)
        self._on_ui(self._refresh_debug_count)

    def _refresh_debug_count(self) -> None:
        self.state.debug_count = len(capturelog.recent_attempts(self.debug_dir))

    def _open_debug(self) -> None:
        if capturelog.open_folder(self.debug_dir):
            self._log(f"Opened the debug folder: {self.debug_dir}")
        else:
            self._log(f"Couldn't open the debug folder. It is at: {self.debug_dir}")
        self._refresh_debug_count()
        self._repaint()

    # --- self test ----------------------------------------------------------
    def _self_test(self) -> None:
        """Run the whole capture path once and report each hop.

        Deliberately not gated on the current connection state: the point is to
        find out what is broken, and refusing to run because a previous check
        failed would withhold the diagnosis exactly when it is needed.
        """
        if self.state.self_test_running:
            return
        self._save()  # test what is in the box, not what was last loaded
        self.state.self_test_running = True
        self.state.self_test = ()
        self.state.status_message = "Running the self test…"
        self.state.status_color = theme.DRAW
        self._log("Self test: sending one test capture through the whole path.")
        self._repaint()

        def on_stage(stage) -> None:
            def apply() -> None:
                self.state.self_test = tuple(
                    list(self.state.self_test) + [(stage.name, stage.result, stage.detail)]
                )
                self._log(f"Self test - {stage.name}: {stage.result}. {stage.detail}".strip())
                self._repaint()

            self._on_ui(apply)

        def worker() -> None:
            report = selftest.run_self_test(
                self.cfg,
                summary_frame=self.controller.buffer.summary_frame,
                on_stage=on_stage,
            )
            if report.match_id is not None:
                self.controller.buffer.clear()
            attempt = self._attempt_context()
            attempt.outcome = "selftest_pass" if report.passed else "selftest_fail"
            attempt.detail = report.summary()
            attempt.match_id = report.match_id
            attempt.frame_size = report.frame_size
            attempt.frames = report.frames
            attempt.regions.update(report.regions)
            attempt.stages = report.as_stage_rows()
            capturelog.record_attempt(attempt, directory=self.debug_dir)

            def apply() -> None:
                self.state.self_test_running = False
                self.state.self_test = tuple(report.as_stage_rows())
                self.state.status_message = report.summary()
                self.state.status_color = theme.WIN if report.passed else theme.LOSS
                # The self test is the authoritative connection answer: it did
                # more than the health probe, so it owns the indicator.
                self._conn_ticket += 1
                self.state.connected = report.passed
                self._log(report.summary())
                self._refresh_debug_count()
                self._repaint()

            self._on_ui(apply)

        threading.Thread(target=worker, daemon=True).start()

    # --- actions ----------------------------------------------------------
    def dispatch(self, action: str) -> None:
        """Route a control's action. One place, so the tray can reuse them."""
        if action.startswith("record_"):
            self._record_hotkey(action.removeprefix("record_"))
            return
        handlers: dict[str, Callable[[], None]] = {
            "toggle": self._toggle_capture,
            "toggle_hint": self._toggle_capture,
            "capture_summary": self._capture_summary,
            "capture_scoreboard": self._capture_scoreboard,
            "reset": self.controller.reset,
            "settings": lambda: self._show("settings"),
            "back": lambda: self._show("main"),
            "quit": self.close,
            "quit_button": self.close,
            "open_match": self._open_match,
            "toggle_log": lambda: self._flip("log_open"),
            "toggle_adv": lambda: self._flip("adv_open"),
            "self_test": self._self_test,
            "test_capture": self._test_capture,
            "open_debug": self._open_debug,
            "install_update": self._install_update,
            "open_pairing": self._open_pairing,
            "remove_app": self._remove_app,
        }
        handler = handlers.get(action)
        if handler is not None:
            handler()

    def _show(self, screen: str) -> None:
        if screen == "main" and self.surface is not None:
            self._save()  # settings apply on leaving the screen
        self.state.screen = screen
        self.state.hover = None
        self._repaint()
        if screen == "settings":
            self._fill_entries()

    def _flip(self, attribute: str) -> None:
        setattr(self.state, attribute, not getattr(self.state, attribute))
        self._repaint()

    def _open_match(self) -> None:
        last = self.state.last
        if last is None or not last.match_id:
            return
        url = matchinfo.match_url(self.cfg.web_url, last.match_id)
        if url:
            webbrowser.open(url)

    def _open_pairing(self) -> None:
        if self.cfg.web_url:
            webbrowser.open(f"{self.cfg.web_url.rstrip('/')}/settings")

    def _remove_app(self) -> None:
        """Confirm and start the D14 local-removal flow off the Tk thread."""
        import tkinter.messagebox as messagebox

        if not messagebox.askyesno(
            "Remove OverAnalyzer from this PC?",
            removal.confirmation_text(),
            parent=self.root,
        ):
            return
        cfg = self._collect()
        self._run_async(lambda: self._remove_app_worker(cfg))

    def _remove_app_worker(self, cfg: AgentConfig) -> None:
        result = removal.remove_app(
            cfg,
            config_path=self.config_path,
            executable_path=str(sys.executable) if getattr(sys, "frozen", False) else None,
            frozen=bool(getattr(sys, "frozen", False)),
        )
        self._on_ui(lambda: self._finish_remove_app(result))

    def _finish_remove_app(self, result: removal.RemovalResult) -> None:
        import tkinter.messagebox as messagebox

        if result.ok:
            messagebox.showinfo("OverAnalyzer removal", result.message, parent=self.root)
            self.close()
            return
        self._log(result.message)
        messagebox.showerror("OverAnalyzer was not removed", result.message, parent=self.root)
        self._repaint()

    def _fill_entries(self) -> None:
        for key, value, secret in (("bearer_token", self.cfg.bearer_token, True),):
            entry = self.surface.entry(key, secret=secret)
            entry.delete(0, "end")
            entry.insert(0, value)

    def _log(self, message: str) -> None:
        self.state.log.append(f"{datetime.now():%H:%M:%S}  {message}")
        del self.state.log[:-200]

    # --- painting ---------------------------------------------------------
    def _photo(self, key: str):
        if key == "backdrop":
            return self._backdrop
        if key == "map_thumb" and self.state.last is not None and self.state.last.map_name:
            return self._thumbs.get(
                matchinfo.map_thumb_url(self.cfg.web_url, self.state.last.map_name)
            )
        if key.startswith("role_"):
            from overanalyzer_agent.ui import assets

            return assets.role_icon(key.removeprefix("role_"))
        return None

    def _repaint(self) -> None:
        if self.surface is None or self.root is None:
            return
        from overanalyzer_agent.ui import layout as layout_mod

        layout = layout_mod.build(self.state, self.surface.measure)
        self._append_removal_control(layout_mod, layout)
        if self._backdrop is None or self._backdrop.height < layout.height:
            self._render_backdrop(layout.height)
        self.surface.paint(layout)
        self.root.geometry(f"{layout_mod.WIDTH}x{layout.height}")

    def _append_removal_control(self, layout_mod, layout) -> None:
        """Add the destructive settings control without changing pure layout code."""
        if self.state.screen != "settings":
            return
        pad = layout_mod.PAD
        inner = layout_mod.WIDTH - pad * 2
        y = layout.height + 16
        layout.ops.append(
            layout_mod.Rect(
                pad, y, inner, 1, fill=theme.BORDER, outline=theme.BORDER,
            )
        )
        layout.ops.append(
            layout_mod.Text(pad, y + 20, "Remove from this PC", layout_mod.MEDIUM, theme.LOSS)
        )
        copy = (
            "Removes this app and its local traces only. Your account, matches, "
            "screenshots, and rank history stay online."
        )
        layout.ops.append(
            layout_mod.Text(pad, y + 40, copy, layout_mod.META, theme.TEXT_MUTED, wrap=inner)
        )
        button_y = y + 84
        label = "Remove OverAnalyzer from this PC"
        hovered = self.state.hover == "remove_app"
        layout.ops.append(
            layout_mod.Rect(
                pad, button_y, inner, 36, theme.RADIUS,
                fill=theme.DANGER_HOVER if hovered else None,
                outline=theme.over(theme.LOSS, theme.PAGE, 0.35),
            )
        )
        label_w = self.surface.measure(label, layout_mod.SANS_SM)
        layout.ops.append(
            layout_mod.Text(
                pad + (inner - label_w) // 2, button_y + 18, label,
                layout_mod.SANS_SM, theme.LOSS, "w",
            )
        )
        layout.controls.append(
            layout_mod.Control("remove_app", pad, button_y, inner, 36,
                               "Revokes this device key and removes local app data")
        )
        layout.height = button_y + 36 + 16 + pad

    def _render_backdrop(self, height: int) -> None:
        """Render the contour texture once for this size. It never animates."""
        from overanalyzer_agent.ui import layout as layout_mod
        from overanalyzer_agent.ui.topography import Backdrop

        drop = Backdrop(layout_mod.WIDTH, max(height, 200), theme.PAGE)
        self._backdrop = drop.render()

    def _on_hover(self, action: str | None) -> None:
        self.state.hover = action
        self._repaint()

    # --- window chrome ----------------------------------------------------
    def build(self):
        import tkinter as tk

        from PIL import ImageTk

        from overanalyzer_agent.ui import assets, brand
        from overanalyzer_agent.ui import layout as layout_mod
        from overanalyzer_agent.ui.fonts import load_fonts
        from overanalyzer_agent.ui.surface import Surface
        from overanalyzer_agent.ui.toast import Toaster

        fonts = load_fonts()  # must happen before Tk snapshots the family list
        root = tk.Tk()
        self.root = root
        root.title("OverAnalyzer Capture")
        root.configure(bg=theme.PAGE)
        root.overrideredirect(True)  # the panel draws its own title bar
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        # Kept alive on self - a PhotoImage with no surviving reference is GC'd
        # and the icon silently reverts to Tk's default feather.
        self._icon_image = ImageTk.PhotoImage(brand.icon(64))
        try:
            root.iconphoto(True, self._icon_image)
        except tk.TclError:  # platforms without iconphoto support
            pass
        if not fonts.bundled:
            self._log("Bundled fonts unavailable - falling back to system fonts.")

        self._thumbs = assets.MapThumbs()
        self._load_monitors()
        self.surface = Surface(
            root, fonts, width=layout_mod.WIDTH, photos=self._photo,
            on_action=self.dispatch, on_hover=self._on_hover, on_change=self._on_change,
        )
        self.surface.canvas.pack(fill="both", expand=True)
        self.toaster = Toaster(root, fonts)

        for key, secret in (("bearer_token", True),):
            entry = self.surface.entry(key, secret=secret)
            entry.bind("<FocusOut>", lambda _e: self._save())
            entry.bind("<Return>", lambda _e: self._save())
        self._fill_entries()

        self._bind_chrome(root)
        self._render_backdrop(theme.PANEL_HEIGHT)
        self._repaint()
        self._place(root)
        _round_corners(root)
        self._check_connection()
        self._check_for_update()
        return root

    def _bind_chrome(self, root) -> None:
        """Drag the panel by its title bar."""
        canvas = self.surface.canvas

        def press(event) -> None:
            if event.y < 40 and self.surface.control_at(event.x, event.y) is None:
                self._drag = (event.x_root - root.winfo_x(), event.y_root - root.winfo_y())

        def drag(event) -> None:
            if self._drag is not None:
                root.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

        def release(_e) -> None:
            if self._drag is not None:
                self._drag = None
                self.stats.set_window_position(root.winfo_x(), root.winfo_y())

        canvas.bind("<ButtonPress-1>", press, add="+")
        canvas.bind("<B1-Motion>", drag, add="+")
        canvas.bind("<ButtonRelease-1>", release, add="+")

    def _place(self, root) -> None:
        """Where you left it - bottom-right of the primary screen on first run."""
        root.update_idletasks()
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        win_w, win_h = root.winfo_width(), root.winfo_height()
        if self.stats.window_x is not None and self.stats.window_y is not None:
            x, y = clamp_position(
                self.stats.window_x, self.stats.window_y, win_w, win_h, screen_w, screen_h
            )
        else:
            x, y = screen_w - win_w - 24, max(24, screen_h - win_h - 72)
        root.geometry(f"+{x}+{y}")

    def close(self) -> None:
        self.hotkeys.unregister()
        if self.toaster is not None:
            self.toaster.destroy()
        if self.root is not None:
            self.root.destroy()
            self.root = None


def _round_corners(root) -> None:
    """Ask Windows 11 for rounded window corners; harmless everywhere else."""
    try:
        import ctypes

        DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())  # type: ignore[attr-defined]
        ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(ctypes.c_int(DWMWCP_ROUND)), ctypes.sizeof(ctypes.c_int),
        )
    except Exception:  # noqa: BLE001 - cosmetic only
        pass


def build_window(cfg: AgentConfig, config_path: str | None = None) -> CapturePanel:
    """Build (but don't run) the panel; the Tk root is at ``.root``."""
    panel = CapturePanel(cfg, config_path)
    panel.build()
    return panel


def open_window(cfg: AgentConfig, config_path: str | None = None, *,
                screen: str = "main") -> None:
    """Launch the panel, opening settings without starting capture when asked."""
    panel = build_window(cfg, config_path)
    panel.state.screen = screen
    if screen == "main":
        panel.start_capture()
    panel.root.mainloop()
