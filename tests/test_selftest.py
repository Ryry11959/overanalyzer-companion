"""The end-to-end self test.

The bug this feature exists to kill: a green "Test connection" that proved a
device key could read the device list, while uploads were being refused. So the
central assertions here are that a valid key alone is never a pass, and that a
failure names the hop that broke.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from overanalyzer_agent import selftest
from overanalyzer_agent.config import AgentConfig
from overanalyzer_agent.uploader import UploadError


@dataclass
class FakeCheck:
    connected: bool = True
    message: str = "Device key accepted · 40 ms."
    latency_ms: int | None = 40


class FakeCapture:
    """Stands in for the capture module - no screen, no mss."""

    def __init__(self, *, leaderboards=(b"t1", b"t2"), fail: str | None = None) -> None:
        self.leaderboards = leaderboards
        self.fail = fail

    def grab_screen(self, _index):
        return _Frame()

    def capture_summary(self, _cfg, frame=None):
        if self.fail == "summary":
            raise RuntimeError("no display")
        return b"summary"

    def capture_leaderboards(self, _cfg, frame=None):
        if self.fail == "leaderboards":
            raise RuntimeError("anchors not found")
        return self.leaderboards


class _Frame:
    size = (1920, 1080)


def _cfg(**kwargs) -> AgentConfig:
    return AgentConfig(bearer_token="device-key-example", **kwargs)


def _run(**overrides) -> selftest.SelfTestReport:
    defaults = dict(
        probe=lambda _cfg: FakeCheck(),
        capture_module=FakeCapture(),
        upload_fn=lambda *_a, **_kw: {"match_id": "m-1"},
        poll_fn=lambda *_a, **_kw: "complete",
        delete_fn=lambda *_a, **_kw: None,
    )
    defaults.update(overrides)
    return selftest.run_self_test(_cfg(), **defaults)


def _stage(report: selftest.SelfTestReport, name: str) -> selftest.Stage:
    return next(s for s in report.stages if s.name == name)


def test_a_healthy_path_passes_every_stage() -> None:
    report = _run()
    assert report.passed
    assert [s.name for s in report.stages] == [
        selftest.SERVICE, selftest.SCREEN, selftest.UPLOAD,
        selftest.OCR, selftest.CLEANUP,
    ]
    assert all(s.ok for s in report.stages)


def test_a_valid_key_is_not_enough_when_the_upload_is_refused() -> None:
    """The exact false pass this replaces: the key reads fine, uploads do not."""
    def _refuse(*_a, **_kw):
        raise UploadError("upload failed (403): read-only demo account")

    report = _run(upload_fn=_refuse)
    assert not report.passed
    assert _stage(report, selftest.SERVICE).ok
    assert report.failure is not None and report.failure.name == selftest.UPLOAD
    assert "writable account" in report.summary()


def test_an_unreachable_service_stops_before_uploading() -> None:
    uploaded = []
    report = _run(
        probe=lambda _cfg: FakeCheck(connected=False, message="Can't reach OverAnalyzer."),
        upload_fn=lambda *a, **kw: uploaded.append(1) or {"match_id": "m-1"},
    )
    assert not report.passed
    assert uploaded == [], "nothing should be sent when the service is down"
    assert len(report.stages) == 1


def test_a_saved_key_is_required_even_when_the_service_answers() -> None:
    report = selftest.run_self_test(
        AgentConfig(bearer_token=""),
        probe=lambda _cfg: FakeCheck(message="Service reachable, no device key saved."),
        capture_module=FakeCapture(),
    )
    assert not report.passed
    assert "no device key" in _stage(report, selftest.SERVICE).detail


def test_a_desktop_frame_still_proves_upload_and_ocr() -> None:
    """Run from the desktop there are no leaderboards, and that must not read as
    a broken app - the pipeline is what this test is for."""
    report = _run(capture_module=FakeCapture(leaderboards=(None, None)))
    assert report.passed
    assert not _stage(report, selftest.SCREEN).ok
    assert "expected off the Game Report screen" in _stage(report, selftest.SCREEN).detail
    assert "Self test passed" in report.summary()


def test_one_missing_leaderboard_is_reported_specifically() -> None:
    report = _run(capture_module=FakeCapture(leaderboards=(b"t1", None)))
    assert "other leaderboard was not" in _stage(report, selftest.SCREEN).detail


def test_a_screen_that_cannot_be_read_stops_the_test() -> None:
    report = _run(capture_module=FakeCapture(fail="summary"))
    assert not report.passed
    assert [s.name for s in report.stages] == [selftest.SERVICE, selftest.SCREEN]
    assert "screen could not be read" in _stage(report, selftest.SCREEN).detail


def test_ocr_still_processing_is_a_pass() -> None:
    """OCR is asynchronous by design; admission is what this proves."""
    report = _run(poll_fn=lambda *_a, **_kw: "processing")
    assert report.passed
    assert "still processing" in _stage(report, selftest.OCR).detail


def test_ocr_failure_is_a_failure() -> None:
    report = _run(poll_fn=lambda *_a, **_kw: "failed")
    assert not report.passed
    assert report.failure is not None and report.failure.name == selftest.OCR


def test_an_unreadable_status_is_not_silently_passed() -> None:
    report = _run(poll_fn=lambda *_a, **_kw: "unknown")
    assert not report.passed


def test_the_test_match_is_deleted_again() -> None:
    deleted: list[str] = []
    report = _run(delete_fn=lambda _url, mid, **_kw: deleted.append(mid))
    assert deleted == ["m-1"]
    assert _stage(report, selftest.CLEANUP).ok


def test_a_failed_cleanup_names_the_match_instead_of_claiming_success() -> None:
    def _fail(*_a, **_kw):
        raise UploadError("delete failed (500): server error")

    report = _run(delete_fn=_fail)
    cleanup = _stage(report, selftest.CLEANUP)
    assert not cleanup.ok
    assert "m-1" in cleanup.detail and "Delete it from the web app" in cleanup.detail
    # Cleanup is housekeeping: the capture path itself still works.
    assert report.passed


def test_an_upload_with_no_match_id_does_not_pass() -> None:
    report = _run(upload_fn=lambda *_a, **_kw: {})
    assert not report.passed
    assert report.failure is not None and report.failure.name == selftest.UPLOAD


def test_the_images_that_were_sent_are_kept_for_the_debug_folder() -> None:
    report = _run()
    assert report.images == {"summary": b"summary", "team1": b"t1", "team2": b"t2"}
    assert report.frame_size == "1920 x 1080"


def test_stages_are_reported_as_they_finish() -> None:
    """The panel renders each hop live rather than freezing until the end."""
    seen: list[str] = []
    _run(on_stage=lambda stage: seen.append(stage.name))
    assert seen[0] == selftest.SERVICE and seen[-1] == selftest.CLEANUP


def test_a_probe_that_explodes_is_reported_not_raised() -> None:
    def _explode(_cfg):
        raise RuntimeError("ssl handshake blew up")

    report = _run(probe=_explode)
    assert not report.passed
    assert "ssl handshake blew up" in _stage(report, selftest.SERVICE).detail


def test_the_upload_carries_the_device_key_and_the_captured_images() -> None:
    seen: dict = {}

    def _capture_call(url, **kwargs):
        seen.update(kwargs)
        seen["url"] = url
        return {"match_id": "m-1"}

    _run(upload_fn=_capture_call)
    assert seen["bearer_token"] == "device-key-example"
    assert seen["summary"] == b"summary"
    assert seen["team1"] == b"t1" and seen["team2"] == b"t2"
