"""End-to-end self test using the same transient two-frame upload contract.

The test needs a Summary frame already held by F11 and captures the visible Teams
screen when it runs. This preserves a real admission and OCR proof without weakening
the full-frame protocol or writing either frame to disk.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from overanalyzer_agent import capture
from overanalyzer_agent.config import AgentConfig
from overanalyzer_agent.uploader import UploadError, delete_match, poll_match_status, upload

SERVICE = "Service and device key"
SCREEN = "Screen capture"
UPLOAD = "Upload"
OCR = "OCR pipeline"
CLEANUP = "Clean up the test match"
REQUIRED = (SERVICE, SCREEN, UPLOAD, OCR)


@dataclass(frozen=True)
class Stage:
    name: str
    ok: bool
    detail: str = ""

    @property
    def result(self) -> str:
        return "pass" if self.ok else "fail"


@dataclass
class SelfTestReport:
    stages: list[Stage] = field(default_factory=list)
    match_id: str | None = None
    frames: dict[str, str] = field(default_factory=dict)
    regions: dict[str, str] = field(default_factory=dict)
    frame_size: str = ""

    @property
    def passed(self) -> bool:
        required = {stage.name: stage.ok for stage in self.stages}
        return all(required.get(name) for name in REQUIRED)

    @property
    def failure(self) -> Stage | None:
        for stage in self.stages:
            if not stage.ok and stage.name in REQUIRED:
                return stage
        return None

    def summary(self) -> str:
        if self.passed:
            return "Self test passed - capture, upload and OCR all work."
        broken = self.failure
        if broken is None:
            return "Self test could not complete."
        return f"Self test failed at: {broken.name.lower()}. {broken.detail}"

    def as_stage_rows(self) -> list[tuple[str, str, str]]:
        return [(stage.name, stage.result, stage.detail) for stage in self.stages]


def run_self_test(
    cfg: AgentConfig,
    *,
    summary_frame: capture.CapturedFrame | None = None,
    probe: Callable[[AgentConfig], object] | None = None,
    capture_module=None,
    upload_fn: Callable[..., dict] = upload,
    poll_fn: Callable[..., str] = poll_match_status,
    delete_fn: Callable[..., None] = delete_match,
    on_stage: Callable[[Stage], None] | None = None,
) -> SelfTestReport:
    """Run each real capture hop once. Never raises or persists frame bytes."""
    report = SelfTestReport()

    def add(stage: Stage) -> Stage:
        report.stages.append(stage)
        if on_stage is not None:
            on_stage(stage)
        return stage

    if not add(_service_stage(cfg, probe)).ok:
        return report

    screen, teams_frame = _screen_stage(
        cfg, report, summary_frame=summary_frame, capture_module=capture_module
    )
    if not add(screen).ok or summary_frame is None or teams_frame is None:
        return report

    uploaded = _upload_stage(cfg, report, summary_frame, teams_frame, upload_fn)
    add(uploaded)
    if not uploaded.ok or report.match_id is None:
        return report

    add(_ocr_stage(cfg, report, poll_fn))
    add(_cleanup_stage(cfg, report, delete_fn))
    return report


def _service_stage(cfg: AgentConfig, probe: Callable[[AgentConfig], object] | None) -> Stage:
    if probe is None:
        from overanalyzer_agent.window import probe_connection

        probe = probe_connection
    try:
        check = probe(cfg)
    except Exception as exc:
        return Stage(SERVICE, False, f"The connection check could not run: {exc}")
    connected = bool(getattr(check, "connected", False))
    message = str(getattr(check, "message", ""))
    if not connected:
        return Stage(SERVICE, False, message)
    if not cfg.bearer_token:
        return Stage(
            SERVICE,
            False,
            "The service is reachable but no device key is saved. Paste a device key first.",
        )
    return Stage(SERVICE, True, message)


def _screen_stage(
    cfg: AgentConfig,
    report: SelfTestReport,
    *,
    summary_frame: capture.CapturedFrame | None,
    capture_module,
) -> tuple[Stage, capture.CapturedFrame | None]:
    if summary_frame is None:
        return (
            Stage(
                SCREEN,
                False,
                "Capture the Summary screen with F11, open the Teams screen, then run "
                "the self test again.",
            ),
            None,
        )
    if capture_module is None:
        capture_module = capture
    try:
        teams_frame = capture_module.capture_full_frame(cfg, require_game_report=True)
    except capture.NotGameReportError:
        return (
            Stage(
                SCREEN,
                False,
                "The selected display does not look like the Game Report Teams screen.",
            ),
            None,
        )
    except Exception as exc:
        return (
            Stage(
                SCREEN,
                False,
                f"The screen could not be read: {exc}. Check the selected display, then try again.",
            ),
            None,
        )

    report.frame_size = f"{teams_frame.width} x {teams_frame.height}"
    report.frames = {
        "summary_frame": summary_frame.detail,
        "teams_frame": teams_frame.detail,
    }
    report.regions["game_report_check"] = "passed"
    return Stage(SCREEN, True, "Both full Game Report frames are ready in memory."), teams_frame


def _upload_stage(
    cfg: AgentConfig,
    report: SelfTestReport,
    summary_frame: capture.CapturedFrame,
    teams_frame: capture.CapturedFrame,
    upload_fn,
) -> Stage:
    try:
        body = upload_fn(
            cfg.api_url,
            summary_frame=summary_frame.png,
            teams_frame=teams_frame.png,
            self_gamertag=cfg.self_gamertag or None,
            bearer_token=cfg.bearer_token or None,
            timeout=cfg.timeout_sec,
        )
    except UploadError as exc:
        from overanalyzer_agent.controller import upload_error_message

        return Stage(UPLOAD, False, upload_error_message(cfg, exc))
    except Exception as exc:
        return Stage(UPLOAD, False, f"The upload could not run: {exc}")

    match_id = body.get("match_id") if isinstance(body, dict) else None
    if not match_id:
        return Stage(
            UPLOAD,
            False,
            "The service accepted the upload but returned no match id, so there is "
            "nothing to follow. Report this with the debug folder.",
        )
    report.match_id = str(match_id)
    return Stage(UPLOAD, True, f"Accepted as match {report.match_id}.")


def _ocr_stage(cfg: AgentConfig, report: SelfTestReport, poll_fn) -> Stage:
    try:
        status = poll_fn(
            cfg.api_url,
            report.match_id,
            bearer_token=cfg.bearer_token or None,
            timeout=cfg.timeout_sec,
        )
    except Exception as exc:
        return Stage(OCR, False, f"The match status could not be read: {exc}")
    if status == "unknown":
        return Stage(
            OCR,
            False,
            "The upload was accepted but its status could not be read back. The match "
            "may still appear in your history.",
        )
    if status == "processing":
        return Stage(OCR, True, "Queued and still processing, which is normal under load.")
    if status == "failed":
        return Stage(OCR, False, "The service received the upload but OCR failed on it.")
    return Stage(OCR, True, f"OCR finished with status: {status}.")


def _cleanup_stage(cfg: AgentConfig, report: SelfTestReport, delete_fn) -> Stage:
    try:
        delete_fn(
            cfg.api_url,
            report.match_id,
            bearer_token=cfg.bearer_token or None,
            timeout=cfg.timeout_sec,
        )
    except Exception as exc:
        return Stage(
            CLEANUP,
            False,
            f"The test match {report.match_id} could not be removed ({exc}). Delete it "
            "from the web app so it does not count as a real game.",
        )
    return Stage(CLEANUP, True, "The test match was removed from your history.")
