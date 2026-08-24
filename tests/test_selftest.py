from dataclasses import dataclass

from overanalyzer_agent import capture, selftest
from overanalyzer_agent.config import AgentConfig
from overanalyzer_agent.uploader import UploadError


@dataclass
class FakeCheck:
    connected: bool = True
    message: str = "Device key accepted."


SUMMARY = capture.CapturedFrame(b"summary", 1920, 1080)
TEAMS = capture.CapturedFrame(b"teams", 1920, 1080)


class FakeCapture:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail

    def capture_full_frame(self, _cfg, *, require_game_report=False):
        if self.fail is not None:
            raise self.fail
        assert require_game_report
        return TEAMS


def _cfg(**kwargs) -> AgentConfig:
    return AgentConfig(bearer_token="device-key-example", **kwargs)


def _run(**overrides) -> selftest.SelfTestReport:
    values = dict(
        summary_frame=SUMMARY,
        probe=lambda _cfg: FakeCheck(),
        capture_module=FakeCapture(),
        upload_fn=lambda *_a, **_kw: {"match_id": "m-1"},
        poll_fn=lambda *_a, **_kw: "complete",
        delete_fn=lambda *_a, **_kw: None,
    )
    values.update(overrides)
    return selftest.run_self_test(_cfg(), **values)


def _stage(report, name):
    return next(stage for stage in report.stages if stage.name == name)


def test_healthy_path_passes_every_stage() -> None:
    report = _run()
    assert report.passed
    assert [stage.name for stage in report.stages] == [
        selftest.SERVICE, selftest.SCREEN, selftest.UPLOAD, selftest.OCR, selftest.CLEANUP
    ]


def test_self_test_requires_a_held_summary_frame() -> None:
    report = _run(summary_frame=None)
    assert not report.passed
    assert "Capture the Summary screen with F11" in _stage(report, selftest.SCREEN).detail
    assert [stage.name for stage in report.stages] == [selftest.SERVICE, selftest.SCREEN]


def test_non_report_teams_screen_stops_before_upload() -> None:
    uploaded = []
    report = _run(
        capture_module=FakeCapture(fail=capture.NotGameReportError()),
        upload_fn=lambda *_a, **_kw: uploaded.append(1),
    )
    assert not report.passed and uploaded == []
    assert "Teams screen" in _stage(report, selftest.SCREEN).detail


def test_valid_key_is_not_enough_when_upload_is_refused() -> None:
    report = _run(
        upload_fn=lambda *_a, **_kw: (_ for _ in ()).throw(
            UploadError("upload failed (403): read-only demo account")
        )
    )
    assert not report.passed
    assert report.failure.name == selftest.UPLOAD


def test_unreachable_service_stops_before_capture() -> None:
    report = _run(probe=lambda _cfg: FakeCheck(False, "Cannot reach OverAnalyzer."))
    assert not report.passed and len(report.stages) == 1


def test_ocr_processing_is_a_pass_because_admission_succeeded() -> None:
    report = _run(poll_fn=lambda *_a, **_kw: "processing")
    assert report.passed


def test_ocr_failure_is_a_failure() -> None:
    report = _run(poll_fn=lambda *_a, **_kw: "failed")
    assert not report.passed and report.failure.name == selftest.OCR


def test_test_match_is_deleted() -> None:
    deleted = []
    report = _run(delete_fn=lambda _url, match_id, **_kw: deleted.append(match_id))
    assert report.passed and deleted == ["m-1"]


def test_cleanup_failure_names_the_match_but_does_not_hide_capture_success() -> None:
    report = _run(
        delete_fn=lambda *_a, **_kw: (_ for _ in ()).throw(UploadError("delete failed"))
    )
    assert report.passed
    assert "m-1" in _stage(report, selftest.CLEANUP).detail


def test_report_keeps_metadata_and_not_raw_frame_bytes() -> None:
    report = _run()
    assert report.frames == {
        "summary_frame": "1920 x 1080, 7 bytes",
        "teams_frame": "1920 x 1080, 5 bytes",
    }
    assert not hasattr(report, "images")


def test_upload_receives_both_full_frame_fields() -> None:
    seen = {}

    def _upload(url, **kwargs):
        seen.update(kwargs)
        seen["url"] = url
        return {"match_id": "m-1"}

    _run(upload_fn=_upload)
    assert seen["summary_frame"] == b"summary"
    assert seen["teams_frame"] == b"teams"
    assert seen["bearer_token"] == "device-key-example"
