"""UI-agnostic capture/upload state machine.

Shared by the CLI driver (``app.py``) and the system-tray app (``tray.py``): it
holds the two-step capture buffer (summary, then scoreboard) and turns each
action into a sequence of :class:`StatusEvent`s the UI renders however it likes -
log lines for the CLI, tray-icon states + toasts for the tray. The screen grab
and upload live in ``capture``/``uploader``; this module only orchestrates and
reports, which keeps it fully testable without a display.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from overanalyzer_agent import capture
from overanalyzer_agent.config import AgentConfig
from overanalyzer_agent.uploader import UploadError, poll_match_status, upload


class Status(str, Enum):
    """Coarse state a UI can map to an icon colour / toast tone."""

    IDLE = "idle"  # ready; nothing in flight
    BUSY = "busy"  # capturing or uploading
    OK = "ok"  # match recorded (complete / partial / still processing)
    NEEDS_REVIEW = "needs_review"  # uploaded, but OCR wants a human
    ERROR = "error"  # capture or upload failed


@dataclass(frozen=True)
class StatusEvent:
    status: Status
    message: str
    match_id: str | None = None


Listener = Callable[[StatusEvent], None]
ShotHook = Callable[[], None]
# Called with (outcome, detail, match_id, images) once an upload settles or
# fails, so a driver can keep the images on disk for diagnosis. Optional: the
# controller works exactly as before without one.
Recorder = Callable[[str, str, "str | None", dict], None]


# How a settled upload status maps to a user-facing (state, message).
_STATUS_EVENT: dict[str, tuple[Status, str]] = {
    "complete": (Status.OK, "Uploaded ✓ - match complete"),
    "partial": (Status.OK, "Uploaded ✓ - partial (a leaderboard was missing)"),
    "processing": (Status.OK, "Uploaded ✓ - still processing"),
    "needs_review": (Status.NEEDS_REVIEW, "Uploaded ⚠ - needs review"),
    "failed": (Status.ERROR, "Upload received but OCR failed ✗"),
    "unknown": (Status.OK, "Uploaded ✓"),
}


@dataclass
class CaptureBuffer:
    summary: bytes | None = None
    team1: bytes | None = None
    team2: bytes | None = None

    def clear(self) -> None:
        self.summary = self.team1 = self.team2 = None


class CaptureController:
    """Capture buffer + upload flow, emitting status events to a listener."""

    def __init__(self, cfg: AgentConfig, listener: Listener | None = None,
                 on_shot: ShotHook | None = None,
                 recorder: Recorder | None = None) -> None:
        self.cfg = cfg
        self.buffer = CaptureBuffer()
        self._listener = listener
        # Fired right after a successful screenshot grab - before upload, before
        # OCR - so a UI can confirm "the picture was taken" independently of the
        # StatusEvent stream (which CLI/tray also consume as user-facing text).
        self._on_shot = on_shot
        self._recorder = recorder

    def _record(self, outcome: str, detail: str, match_id: str | None,
                images: dict[str, bytes]) -> None:
        """Hand the attempt to the driver's recorder. Never breaks a capture."""
        if self._recorder is None:
            return
        try:
            self._recorder(outcome, detail, match_id, images)
        except Exception:  # noqa: BLE001 - diagnostics must not fail the upload
            pass

    def _emit(self, status: Status, message: str, match_id: str | None = None) -> None:
        if self._listener is not None:
            self._listener(StatusEvent(status, message, match_id))

    def _shot(self) -> None:
        if self._on_shot is not None:
            self._on_shot()

    @property
    def has_summary(self) -> bool:
        return self.buffer.summary is not None

    def capture_summary(self) -> bool:
        """Grab the summary region into the buffer. Returns success."""
        self._emit(Status.BUSY, "Capturing summary…")
        try:
            self.buffer.summary = capture.capture_summary(self.cfg)
        except Exception as exc:  # noqa: BLE001 - keep the app alive on a bad grab
            self._emit(Status.ERROR, capture_error_message("Summary", exc))
            return False
        self._shot()
        self._emit(
            Status.IDLE,
            "Captured summary - open the scoreboard (Tab) and capture it.",
        )
        return True

    def capture_scoreboard(self) -> bool:
        """Grab both leaderboards and, if a summary is buffered, upload the match."""
        self._emit(Status.BUSY, "Capturing scoreboard…")
        try:
            t1, t2 = capture.capture_leaderboards(self.cfg)
        except Exception as exc:  # noqa: BLE001
            self._emit(Status.ERROR, capture_error_message("Scoreboard", exc))
            return False
        self._shot()
        self.buffer.team1, self.buffer.team2 = t1, t2
        if self.buffer.summary is None:
            self._emit(
                Status.IDLE,
                "Captured scoreboard, but no summary yet - capture the summary screen first.",
            )
            return False
        return self._upload()

    def reset(self) -> None:
        self.buffer.clear()
        self._emit(Status.IDLE, "Buffer cleared.")

    def _upload(self) -> bool:
        self._emit(Status.BUSY, f"Uploading to {self.cfg.api_url}…")
        # Taken before the buffer is cleared: these are the exact bytes sent, and
        # they are the only thing that can explain a wrong read afterwards.
        sent = {
            name: blob
            for name, blob in (
                ("summary", self.buffer.summary),
                ("team1", self.buffer.team1),
                ("team2", self.buffer.team2),
            )
            if blob
        }
        try:
            body = upload(
                self.cfg.api_url,
                summary=self.buffer.summary,  # type: ignore[arg-type]
                team1=self.buffer.team1,
                team2=self.buffer.team2,
                self_gamertag=self.cfg.self_gamertag or None,
                bearer_token=self.cfg.bearer_token or None,
                timeout=self.cfg.timeout_sec,
            )
        except UploadError as exc:
            message = upload_error_message(self.cfg, exc)
            self._record("error", message, None, sent)
            self._emit(Status.ERROR, message)
            return False

        self.buffer.clear()
        match_id = body.get("match_id")
        if match_id:
            self._emit(Status.BUSY, "Uploaded - waiting for OCR…", match_id=str(match_id))
            settled = poll_match_status(
                self.cfg.api_url,
                str(match_id),
                bearer_token=self.cfg.bearer_token or None,
                timeout=self.cfg.timeout_sec,
            )
        else:
            settled = "unknown"
        state, message = _STATUS_EVENT.get(settled, _STATUS_EVENT["unknown"])
        self._record(settled, message, str(match_id) if match_id else None, sent)
        self._emit(state, message, match_id=str(match_id) if match_id else None)
        return state is not Status.ERROR


def capture_error_message(kind: str, exc: Exception) -> str:
    """Turn a screen-grab exception into a next step a new user can follow."""
    detail = str(exc).strip() or "the screen could not be read"
    return (
        f"{kind} capture could not start: {detail}. "
        "Make sure the game is visible on the selected display, then try again."
    )


def server_detail(message: str) -> str:
    """Pull the API's ``detail`` sentence out of an error string, if there is one.

    ``uploader`` formats failures as ``upload failed (403): {body}``, and the
    body is normally a JSON object with a ``detail`` string. Relaying that
    sentence beats inventing a cause, and a body that isn't JSON yields nothing.
    """
    start = message.find("{")
    if start < 0:
        return ""
    try:
        payload = json.loads(message[start:])
    except ValueError:
        return ""
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return detail.strip() if isinstance(detail, str) else ""


def upload_error_message(cfg: AgentConfig, exc: UploadError) -> str:
    """Avoid making a first upload failure look like an unexplained crash.

    ``uploader`` deliberately keeps its small transport contract, so the
    controller classifies its existing status-text errors here.  In particular,
    the API already tells us when a device key is invalid or revoked.
    """
    detail = str(exc).strip()
    lowered = detail.lower()

    if "401" in lowered or "invalid or revoked device token" in lowered:
        if cfg.bearer_token:
            return (
                "Device key rejected (invalid or revoked). Open Settings → Devices "
                "in the web app, revoke the old key if needed, create one replacement, "
                "paste it in the app, then run the self test again."
            )
        return (
            "No device key was accepted. Open the app Settings, paste the key from "
            "the signed-in web app, then run the self test again."
        )
    if "403" in lowered:
        # The service distinguishes several refusals here (read-only demo, an
        # unverified account, a device paired before verification was recorded)
        # and its own wording is the actionable one. Guessing a single cause is
        # what once told a correctly paired user to "sign in to a writable
        # account" when the real problem was the account's first upload.
        served = server_detail(detail)
        if served:
            return f"Upload rejected. {served}"
        return (
            "Upload rejected. Sign in to a writable account, create a device key in "
            "Settings → Devices, paste it in the app, then run the self test again."
        )
    if "429" in lowered:
        return "Upload paused by the service limit. Wait a little, then try again."
    if "request to " in lowered and " failed:" in lowered:
        return (
            "Upload could not reach OverAnalyzer. Check your internet connection, "
            "then run the self test and try the capture again."
        )
    if any(code in lowered for code in ("500", "502", "503", "504")):
        return "OverAnalyzer is temporarily unavailable. Wait a little, run the self test, and try again."
    return f"Upload failed: {detail}"
