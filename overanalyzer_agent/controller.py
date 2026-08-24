"""UI-agnostic two-frame capture and upload state machine."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from overanalyzer_agent import capture
from overanalyzer_agent.config import AgentConfig
from overanalyzer_agent.uploader import UploadError, poll_match_status, upload


class Status(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    OK = "ok"
    NEEDS_REVIEW = "needs_review"
    ERROR = "error"


@dataclass(frozen=True)
class StatusEvent:
    status: Status
    message: str
    match_id: str | None = None


Listener = Callable[[StatusEvent], None]
ShotHook = Callable[[], None]
# Raw frame bytes are deliberately absent from this callback. A UI may persist the
# non-sensitive dimensions and byte counts, but never the uploaded pixels.
Recorder = Callable[[str, str, "str | None", dict[str, str]], None]


_STATUS_EVENT: dict[str, tuple[Status, str]] = {
    "complete": (Status.OK, "Uploaded - match complete"),
    "partial": (Status.OK, "Uploaded - partial (one team side was absent)"),
    "processing": (Status.OK, "Uploaded - still processing"),
    "needs_review": (Status.NEEDS_REVIEW, "Uploaded - needs review"),
    "failed": (Status.ERROR, "Upload received but OCR failed"),
    "unknown": (Status.OK, "Uploaded"),
}


@dataclass
class CaptureBuffer:
    summary_frame: capture.CapturedFrame | None = None
    teams_frame: capture.CapturedFrame | None = None

    def clear(self) -> None:
        self.summary_frame = None
        self.teams_frame = None


class CaptureController:
    """Hold a Summary frame until a Teams frame completes the explicit capture."""

    def __init__(
        self,
        cfg: AgentConfig,
        listener: Listener | None = None,
        on_shot: ShotHook | None = None,
        recorder: Recorder | None = None,
    ) -> None:
        self.cfg = cfg
        self.buffer = CaptureBuffer()
        self._listener = listener
        self._on_shot = on_shot
        self._recorder = recorder

    def _record(
        self,
        outcome: str,
        detail: str,
        match_id: str | None,
        frames: dict[str, str],
    ) -> None:
        if self._recorder is None:
            return
        try:
            self._recorder(outcome, detail, match_id, frames)
        except Exception:
            # Diagnostics must never change the capture outcome.
            pass

    def _emit(self, status: Status, message: str, match_id: str | None = None) -> None:
        if self._listener is not None:
            self._listener(StatusEvent(status, message, match_id))

    def _shot(self) -> None:
        if self._on_shot is not None:
            self._on_shot()

    @property
    def has_summary(self) -> bool:
        return self.buffer.summary_frame is not None

    def capture_summary(self) -> bool:
        """Grab the full Summary screen into the memory-only buffer."""
        self._emit(Status.BUSY, "Capturing summary...")
        try:
            self.buffer.summary_frame = capture.capture_full_frame(self.cfg)
        except Exception as exc:
            self._emit(Status.ERROR, capture_error_message("Summary", exc))
            return False
        self._shot()
        self._emit(
            Status.IDLE,
            "Captured summary - open the Teams screen and capture it.",
        )
        return True

    def capture_scoreboard(self) -> bool:
        """Grab the full Teams screen, check it coarsely, then upload both frames."""
        self._emit(Status.BUSY, "Capturing scoreboard...")
        try:
            teams_frame = capture.capture_full_frame(self.cfg, require_game_report=True)
        except capture.NotGameReportError:
            self._emit(
                Status.ERROR,
                "Capture refused - open the Game Report Teams screen on the selected "
                "display, then try again.",
            )
            return False
        except Exception as exc:
            self._emit(Status.ERROR, capture_error_message("Scoreboard", exc))
            return False

        self._shot()
        if self.buffer.summary_frame is None:
            self._emit(
                Status.IDLE,
                "Captured scoreboard, but no summary yet - capture the Summary screen first.",
            )
            return False
        self.buffer.teams_frame = teams_frame
        return self._upload()

    def reset(self) -> None:
        self.buffer.clear()
        self._emit(Status.IDLE, "Buffer cleared.")

    def _upload(self) -> bool:
        self._emit(Status.BUSY, f"Uploading to {self.cfg.api_url}...")
        summary_frame = self.buffer.summary_frame
        teams_frame = self.buffer.teams_frame
        if summary_frame is None or teams_frame is None:
            self._emit(Status.ERROR, "Both Game Report screens are required before upload.")
            return False

        metadata = {
            "summary_frame": summary_frame.detail,
            "teams_frame": teams_frame.detail,
        }
        try:
            body = upload(
                self.cfg.api_url,
                summary_frame=summary_frame.png,
                teams_frame=teams_frame.png,
                self_gamertag=self.cfg.self_gamertag or None,
                bearer_token=self.cfg.bearer_token or None,
                timeout=self.cfg.timeout_sec,
            )
        except UploadError as exc:
            message = upload_error_message(self.cfg, exc)
            self._record("error", message, None, metadata)
            self._emit(Status.ERROR, message)
            return False

        # Release both frames as soon as admission succeeds, before status polling.
        self.buffer.clear()
        match_id = body.get("match_id")
        if match_id:
            self._emit(Status.BUSY, "Uploaded - waiting for OCR...", match_id=str(match_id))
            settled = poll_match_status(
                self.cfg.api_url,
                str(match_id),
                bearer_token=self.cfg.bearer_token or None,
                timeout=self.cfg.timeout_sec,
            )
        else:
            settled = "unknown"
        state, message = _STATUS_EVENT.get(settled, _STATUS_EVENT["unknown"])
        self._record(settled, message, str(match_id) if match_id else None, metadata)
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
    """Extract the API's detail sentence from a formatted upload error."""
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
    """Classify transport failures into useful recovery instructions."""
    detail = str(exc).strip()
    lowered = detail.lower()

    if "401" in lowered or "invalid or revoked device token" in lowered:
        if cfg.bearer_token:
            return (
                "Device key rejected (invalid or revoked). Open Settings > Devices "
                "in the web app, revoke the old key if needed, create one replacement, "
                "paste it in the app, then run the self test again."
            )
        return (
            "No device key was accepted. Open the app Settings, paste the key from "
            "the signed-in web app, then run the self test again."
        )
    if "403" in lowered:
        served = server_detail(detail)
        if served:
            return f"Upload rejected. {served}"
        return (
            "Upload rejected. Sign in to a writable account, create a device key in "
            "Settings > Devices, paste it in the app, then run the self test again."
        )
    if "429" in lowered:
        return "Upload paused by the service limit. Wait a little, then try again."
    if "request to " in lowered and " failed:" in lowered:
        return (
            "Upload could not reach OverAnalyzer. Check your internet connection, "
            "then run the self test and try the capture again."
        )
    if any(code in lowered for code in ("500", "502", "503", "504")):
        return (
            "OverAnalyzer is temporarily unavailable. Wait a little, run the self "
            "test, and try again."
        )
    return f"Upload failed: {detail}"
