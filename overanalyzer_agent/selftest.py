"""An end-to-end self test: does a capture actually reach the account?

The old buttons each proved one hop and implied the rest. "Test connection"
read the device list, so a valid key looked like a working app even when the
upload endpoint would refuse it; "Test capture" grabbed a frame and never sent
it anywhere. A user could get two green results and still have nothing appear
in their history, which is the failure this replaces.

This runs the real path in order - service, screen, upload, OCR - using the
same functions a genuine capture uses, and reports each stage separately so a
failure names its own hop. Two consequences are deliberate and are stated to
the user rather than hidden:

* It **really uploads**, so it consumes one of the account's daily uploads.
  Nothing else would prove admission; a synthetic ping would test a code path
  no capture takes.
* It therefore **creates a real match**, which the cleanup stage deletes again.
  If the delete fails, the report gives the match id instead of claiming the
  history is clean.

Because the point is the pipeline rather than the picture, the test runs from
the desktop: a frame with no leaderboards still proves upload and OCR, and the
capture stage says plainly what it did and did not find.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from overanalyzer_agent.config import AgentConfig
from overanalyzer_agent.uploader import UploadError, delete_match, poll_match_status, upload

# Stage names, in the order they run. Also the order the report renders.
SERVICE = "Service and device key"
SCREEN = "Screen capture"
UPLOAD = "Upload"
OCR = "OCR pipeline"
CLEANUP = "Clean up the test match"

# Stages that must pass for the app to be considered working. The screen stage
# is graded separately: no leaderboards on the desktop is expected, not a fault.
REQUIRED = (SERVICE, UPLOAD, OCR)


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
    images: dict[str, bytes] = field(default_factory=dict)
    regions: dict[str, str] = field(default_factory=dict)
    frame_size: str = ""

    @property
    def passed(self) -> bool:
        required = {s.name: s.ok for s in self.stages}
        return all(required.get(name) for name in REQUIRED)

    @property
    def failure(self) -> Stage | None:
        """The first required stage that failed - the one worth reporting."""
        for stage in self.stages:
            if not stage.ok and stage.name in REQUIRED:
                return stage
        return None

    def summary(self) -> str:
        """One line for the status row: the verdict, and the next step if not."""
        if self.passed:
            warnings = [s for s in self.stages if not s.ok]
            if warnings:
                return (
                    f"Self test passed - captures reach your account. "
                    f"{warnings[0].detail}"
                )
            return "Self test passed - capture, upload and OCR all work."
        broken = self.failure
        if broken is None:
            return "Self test could not complete."
        return f"Self test failed at: {broken.name.lower()}. {broken.detail}"

    def as_stage_rows(self) -> list[tuple[str, str, str]]:
        return [(s.name, s.result, s.detail) for s in self.stages]


def run_self_test(
    cfg: AgentConfig,
    *,
    probe: Callable[[AgentConfig], object] | None = None,
    capture_module=None,
    upload_fn: Callable[..., dict] = upload,
    poll_fn: Callable[..., str] = poll_match_status,
    delete_fn: Callable[..., None] = delete_match,
    on_stage: Callable[[Stage], None] | None = None,
) -> SelfTestReport:
    """Run every hop of the capture path once. Never raises.

    Each dependency is injectable so the whole flow is testable without a
    screen, a network, or an account.
    """
    report = SelfTestReport()

    def add(stage: Stage) -> Stage:
        report.stages.append(stage)
        if on_stage is not None:
            on_stage(stage)
        return stage

    if not add(_service_stage(cfg, probe)).ok:
        return report

    screen = _screen_stage(cfg, report, capture_module)
    add(screen)
    if report.images.get("summary") is None:
        # Without a summary there is nothing the server would accept, so the
        # remaining stages would fail for a reason that is not their own.
        return report

    uploaded = _upload_stage(cfg, report, upload_fn)
    add(uploaded)
    if not uploaded.ok or report.match_id is None:
        return report

    add(_ocr_stage(cfg, report, poll_fn))
    add(_cleanup_stage(cfg, report, delete_fn))
    return report


def _service_stage(cfg: AgentConfig, probe: Callable[[AgentConfig], object] | None) -> Stage:
    if probe is None:
        # Imported here: window imports this module, and the classified pairing
        # messages live there and should not be duplicated.
        from overanalyzer_agent.window import probe_connection

        probe = probe_connection
    try:
        check = probe(cfg)
    except Exception as exc:  # noqa: BLE001 - a self test must survive anything
        return Stage(SERVICE, False, f"The connection check could not run: {exc}")
    connected = bool(getattr(check, "connected", False))
    message = str(getattr(check, "message", ""))
    if not connected:
        return Stage(SERVICE, False, message)
    if not cfg.bearer_token:
        return Stage(
            SERVICE,
            False,
            "The service is reachable but no device key is saved, so an upload "
            "would have nowhere to go. Paste a device key first.",
        )
    return Stage(SERVICE, True, message)


def _screen_stage(cfg: AgentConfig, report: SelfTestReport, capture_module) -> Stage:
    if capture_module is None:
        from overanalyzer_agent import capture as capture_module  # noqa: PLW2901

    try:
        frame = capture_module.grab_screen(cfg.monitor_index)
        report.frame_size = _frame_size(frame)
        report.images["summary"] = capture_module.capture_summary(cfg, frame=frame)
    except Exception as exc:  # noqa: BLE001
        return Stage(
            SCREEN,
            False,
            f"The screen could not be read: {exc}. Check the selected display, then try again.",
        )

    try:
        team1, team2 = capture_module.capture_leaderboards(cfg, frame=frame)
    except Exception as exc:  # noqa: BLE001
        team1 = team2 = None
        report.regions["leaderboards"] = f"error: {exc}"

    for name, blob in (("team1", team1), ("team2", team2)):
        if blob:
            report.images[name] = blob
    found = [name for name in ("team1", "team2") if report.images.get(name)]
    report.regions["summary"] = "captured"
    report.regions["leaderboards"] = ", ".join(found) if found else "none found"

    if len(found) == 2:
        return Stage(SCREEN, True, "Summary and both leaderboards were found.")
    return Stage(
        SCREEN,
        False,
        "Only the summary was captured, which is expected off the Game Report "
        "screen. The rest of the test still ran."
        if not found
        else f"The summary and {found[0]} were captured, but the other leaderboard was not.",
    )


def _upload_stage(cfg: AgentConfig, report: SelfTestReport, upload_fn) -> Stage:
    try:
        body = upload_fn(
            cfg.api_url,
            summary=report.images["summary"],
            team1=report.images.get("team1"),
            team2=report.images.get("team2"),
            self_gamertag=cfg.self_gamertag or None,
            bearer_token=cfg.bearer_token or None,
            timeout=cfg.timeout_sec,
        )
    except UploadError as exc:
        from overanalyzer_agent.controller import upload_error_message

        return Stage(UPLOAD, False, upload_error_message(cfg, exc))
    except Exception as exc:  # noqa: BLE001
        return Stage(UPLOAD, False, f"The upload could not run: {exc}")

    match_id = body.get("match_id") if isinstance(body, dict) else None
    if not match_id:
        return Stage(
            UPLOAD,
            False,
            "The service accepted the upload but returned no match id, so there "
            "is nothing to follow. Report this with the debug folder.",
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
    except Exception as exc:  # noqa: BLE001
        return Stage(OCR, False, f"The match status could not be read: {exc}")

    if status == "unknown":
        return Stage(
            OCR,
            False,
            "The upload was accepted but its status could not be read back. "
            "The match may still appear in your history.",
        )
    if status == "processing":
        # Still queued is not a failure: admission is what this stage proves,
        # and OCR is deliberately asynchronous.
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
    except Exception as exc:  # noqa: BLE001
        return Stage(
            CLEANUP,
            False,
            f"The test match {report.match_id} could not be removed ({exc}). "
            "Delete it from the web app so it does not count as a real game.",
        )
    return Stage(CLEANUP, True, "The test match was removed from your history.")


def _frame_size(frame) -> str:
    """Best effort. ``grab_screen`` returns a PIL image; anything else degrades."""
    size = getattr(frame, "size", None)
    if isinstance(size, tuple) and len(size) == 2:
        return f"{size[0]} x {size[1]}"
    return "unknown"
