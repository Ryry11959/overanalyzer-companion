"""Drives the CaptureController through its capture->upload->poll flow against a
threaded mock API, asserting the status-event sequence a UI would render."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from overanalyzer_agent import capture
from overanalyzer_agent.config import AgentConfig
from overanalyzer_agent.controller import (
    CaptureController,
    Status,
    capture_error_message,
    upload_error_message,
)
from overanalyzer_agent.uploader import UploadError


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - upload endpoint
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.server.upload_count += 1
        self._json(202, {"match_id": "m1", "status": "processing", "message": "ok"})

    def do_GET(self):  # noqa: N802 - status-poll endpoint
        self.server.status_polls += 1
        self._json(200, {"status": self.server.match_status})

    def _json(self, code, body):
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def mock_api():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.upload_count = 0
    server.status_polls = 0
    server.match_status = "complete"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, port = server.server_address
        yield f"http://127.0.0.1:{port}", server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def fake_capture(monkeypatch):
    """Stub the screen-grab so the flow runs headless (no display / mss)."""
    monkeypatch.setattr(capture, "capture_summary", lambda cfg, frame=None: b"SUMMARY")
    monkeypatch.setattr(
        capture, "capture_leaderboards", lambda cfg, frame=None: (b"T1", b"T2")
    )


def test_full_flow_uploads_and_reports_complete(mock_api, fake_capture):
    base, server = mock_api
    events = []
    ctrl = CaptureController(AgentConfig(api_url=base), listener=events.append)

    assert ctrl.capture_summary() is True
    assert ctrl.has_summary
    assert ctrl.capture_scoreboard() is True

    assert server.upload_count == 1
    assert not ctrl.has_summary  # buffer cleared after upload
    assert events[-1].status is Status.OK
    assert "complete" in events[-1].message
    assert events[-1].match_id == "m1"


def test_needs_review_maps_to_needs_review_state(mock_api, fake_capture):
    base, server = mock_api
    server.match_status = "needs_review"
    events = []
    ctrl = CaptureController(AgentConfig(api_url=base), listener=events.append)
    ctrl.capture_summary()
    ctrl.capture_scoreboard()
    assert events[-1].status is Status.NEEDS_REVIEW


def test_failed_ocr_maps_to_error(mock_api, fake_capture):
    base, server = mock_api
    server.match_status = "failed"
    events = []
    ctrl = CaptureController(AgentConfig(api_url=base), listener=events.append)
    ctrl.capture_summary()
    assert ctrl.capture_scoreboard() is False
    assert events[-1].status is Status.ERROR


def test_scoreboard_without_summary_does_not_upload(mock_api, fake_capture):
    base, server = mock_api
    events = []
    ctrl = CaptureController(AgentConfig(api_url=base), listener=events.append)
    assert ctrl.capture_scoreboard() is False
    assert server.upload_count == 0
    assert events[-1].status is Status.IDLE


def test_reset_clears_buffer(fake_capture):
    ctrl = CaptureController(AgentConfig())
    ctrl.capture_summary()
    assert ctrl.has_summary
    ctrl.reset()
    assert not ctrl.has_summary


def test_summary_capture_failure_emits_error(monkeypatch):
    def boom(cfg, frame=None):
        raise RuntimeError("no screen")

    monkeypatch.setattr(capture, "capture_summary", boom)
    events = []
    ctrl = CaptureController(AgentConfig(), listener=events.append)
    assert ctrl.capture_summary() is False
    assert events[-1].status is Status.ERROR
    assert not ctrl.has_summary


def test_upload_connection_error_emits_error(fake_capture):
    events = []
    ctrl = CaptureController(
        AgentConfig(api_url="http://127.0.0.1:9", timeout_sec=1.0), listener=events.append
    )
    ctrl.capture_summary()
    assert ctrl.capture_scoreboard() is False
    assert events[-1].status is Status.ERROR


# --- the shutter hook -------------------------------------------------------
def test_on_shot_fires_for_a_successful_summary_grab(fake_capture):
    shots = []
    ctrl = CaptureController(AgentConfig(), on_shot=lambda: shots.append(1))
    ctrl.capture_summary()
    assert shots == [1]


def test_on_shot_fires_for_a_successful_scoreboard_grab_even_without_a_summary(fake_capture):
    """The picture was taken either way - the hook isn't about the upload outcome."""
    shots = []
    ctrl = CaptureController(AgentConfig(), on_shot=lambda: shots.append(1))
    ctrl.capture_scoreboard()
    assert shots == [1]


def test_on_shot_does_not_fire_on_a_failed_grab(monkeypatch):
    monkeypatch.setattr(capture, "capture_summary", lambda cfg, frame=None: (_ for _ in ()).throw(
        RuntimeError("no screen")
    ))
    shots = []
    ctrl = CaptureController(AgentConfig(), on_shot=lambda: shots.append(1))
    ctrl.capture_summary()
    assert shots == []


def test_on_shot_is_optional(fake_capture):
    CaptureController(AgentConfig()).capture_summary()  # must not raise with no hook


def test_capture_failure_explains_how_to_make_the_screen_readable():
    message = capture_error_message("Summary", RuntimeError("no screen"))
    assert "could not start" in message
    assert "selected display" in message


def test_invalid_device_key_upload_failure_explains_the_recovery(monkeypatch):
    import overanalyzer_agent.controller as controller_module

    monkeypatch.setattr(
        controller_module,
        "upload",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            UploadError("upload failed (401): Invalid or revoked device token")
        ),
    )
    events = []
    ctrl = CaptureController(
        AgentConfig(bearer_token="device-key-example"), listener=events.append
    )
    ctrl.buffer.summary = b"summary"

    assert ctrl._upload() is False
    assert events[-1].status is Status.ERROR
    assert "invalid or revoked" in events[-1].message
    assert "run the self test again" in events[-1].message


def test_unreachable_upload_failure_does_not_leave_a_new_user_with_transport_jargon():
    message = upload_error_message(
        AgentConfig(),
        UploadError("request to https://api.example failed: connection refused"),
    )
    assert "could not reach OverAnalyzer" in message
    assert "internet connection" in message


# --- capture debug recording ------------------------------------------------
def test_a_successful_upload_records_what_it_sent(mock_api, fake_capture):
    """The images are the only thing that can explain a wrong read later."""
    base, _ = mock_api
    recorded = []
    ctrl = CaptureController(
        AgentConfig(api_url=base),
        recorder=lambda *args: recorded.append(args),
    )
    ctrl.capture_summary()
    ctrl.capture_scoreboard()

    assert len(recorded) == 1
    outcome, _detail, match_id, images = recorded[0]
    assert outcome == "complete"
    assert match_id == "m1"
    assert images == {"summary": b"SUMMARY", "team1": b"T1", "team2": b"T2"}


def test_a_refused_upload_still_records_the_images(fake_capture):
    """The failing case is the one worth keeping - there is no server-side copy."""
    recorded = []
    ctrl = CaptureController(
        AgentConfig(api_url="http://127.0.0.1:9"),  # nothing listens here
        recorder=lambda *args: recorded.append(args),
    )
    ctrl.capture_summary()
    assert ctrl.capture_scoreboard() is False

    assert len(recorded) == 1
    outcome, detail, match_id, images = recorded[0]
    assert outcome == "error" and match_id is None
    assert images["summary"] == b"SUMMARY"
    assert "internet connection" in detail


def test_a_recorder_that_raises_does_not_break_the_capture(mock_api, fake_capture):
    base, server = mock_api

    def _explode(*_args):
        raise OSError("disk full")

    ctrl = CaptureController(AgentConfig(api_url=base), recorder=_explode)
    ctrl.capture_summary()
    assert ctrl.capture_scoreboard() is True
    assert server.upload_count == 1


# --- the service's own refusal wording --------------------------------------
def test_a_403_relays_the_services_explanation():
    """Guessing one cause is what told a correctly paired user to sign in to a
    writable account when the real problem was their account's first upload."""
    detail = (
        "This device was paired before its account confirmed a verified email. "
        "Open Settings in the web app, create a new device key, and paste it "
        "into the capture app."
    )
    exc = UploadError('upload failed (403): {"detail": "%s"}' % detail)
    message = upload_error_message(AgentConfig(), exc)
    assert detail in message
    assert "writable account" not in message


def test_a_403_without_a_readable_body_still_says_something_useful():
    exc = UploadError("upload failed (403): <html>Forbidden</html>")
    assert "writable account" in upload_error_message(AgentConfig(), exc)


def test_the_demo_refusal_is_relayed_verbatim_too():
    exc = UploadError(
        'upload failed (403): {"detail": "This is the public demo account - '
        'sign in to upload or edit your own matches."}'
    )
    assert "public demo account" in upload_error_message(AgentConfig(), exc)
