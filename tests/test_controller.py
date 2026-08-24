"""Drive the two-frame controller through capture, upload, poll, and recording."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from overanalyzer_agent import capture
from overanalyzer_agent.config import AgentConfig
from overanalyzer_agent.controller import CaptureController, Status, capture_error_message, upload_error_message
from overanalyzer_agent.uploader import UploadError


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.server.last_body = self.rfile.read(length)
        self.server.upload_count += 1
        self._json(202, {"match_id": "m1", "status": "processing"})

    def do_GET(self):
        self._json(200, {"status": self.server.match_status})

    def _json(self, code, body):
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


@pytest.fixture
def mock_api():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.upload_count = 0
    server.last_body = b""
    server.match_status = "complete"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server
    finally:
        server.shutdown()
        server.server_close()


def _frame(data: bytes) -> capture.CapturedFrame:
    return capture.CapturedFrame(data, 1920, 1080)


@pytest.fixture
def fake_capture(monkeypatch):
    calls = []

    def _capture(_cfg, *, frame=None, require_game_report=False):
        calls.append(require_game_report)
        return _frame(b"TEAMS" if require_game_report else b"SUMMARY")

    monkeypatch.setattr(capture, "capture_full_frame", _capture)
    return calls


def test_full_flow_uses_the_versioned_two_frame_contract(mock_api, fake_capture):
    base, server = mock_api
    events = []
    controller = CaptureController(AgentConfig(api_url=base), listener=events.append)
    assert controller.capture_summary()
    assert controller.capture_scoreboard()
    assert fake_capture == [False, True]
    assert server.upload_count == 1
    assert b'name="summary_frame"' in server.last_body
    assert b'name="teams_frame"' in server.last_body
    assert not controller.has_summary
    assert events[-1].status is Status.OK


def test_settled_statuses_map_to_ui_states(mock_api, fake_capture):
    base, server = mock_api
    server.match_status = "needs_review"
    events = []
    controller = CaptureController(AgentConfig(api_url=base), listener=events.append)
    controller.capture_summary()
    controller.capture_scoreboard()
    assert events[-1].status is Status.NEEDS_REVIEW


def test_scoreboard_without_summary_does_not_upload_or_buffer_frame(mock_api, fake_capture):
    base, server = mock_api
    events = []
    controller = CaptureController(AgentConfig(api_url=base), listener=events.append)
    assert not controller.capture_scoreboard()
    assert server.upload_count == 0
    assert controller.buffer.teams_frame is None
    assert events[-1].status is Status.IDLE


def test_coarse_guard_refusal_never_uploads_or_fires_shutter(monkeypatch, mock_api):
    base, server = mock_api
    monkeypatch.setattr(
        capture,
        "capture_full_frame",
        lambda *_a, **_kw: (_ for _ in ()).throw(capture.NotGameReportError()),
    )
    events = []
    shots = []
    controller = CaptureController(
        AgentConfig(api_url=base), listener=events.append, on_shot=lambda: shots.append(1)
    )
    assert not controller.capture_scoreboard()
    assert server.upload_count == 0 and shots == []
    assert events[-1].status is Status.ERROR
    assert "Game Report Teams" in events[-1].message


def test_reset_releases_the_held_summary(fake_capture):
    controller = CaptureController(AgentConfig())
    controller.capture_summary()
    assert controller.has_summary
    controller.reset()
    assert not controller.has_summary


def test_summary_capture_failure_emits_error(monkeypatch):
    monkeypatch.setattr(
        capture,
        "capture_full_frame",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("no screen")),
    )
    events = []
    controller = CaptureController(AgentConfig(), listener=events.append)
    assert not controller.capture_summary()
    assert events[-1].status is Status.ERROR


def test_shutter_fires_only_after_a_successful_grab(fake_capture):
    shots = []
    controller = CaptureController(AgentConfig(), on_shot=lambda: shots.append(1))
    controller.capture_summary()
    controller.capture_scoreboard()
    assert shots == [1, 1]


def test_recorder_receives_metadata_and_never_frame_bytes(mock_api, fake_capture):
    base, _ = mock_api
    recorded = []
    controller = CaptureController(
        AgentConfig(api_url=base), recorder=lambda *args: recorded.append(args)
    )
    controller.capture_summary()
    controller.capture_scoreboard()
    outcome, _detail, match_id, frames = recorded[0]
    assert outcome == "complete" and match_id == "m1"
    assert frames == {
        "summary_frame": "1920 x 1080, 7 bytes",
        "teams_frame": "1920 x 1080, 5 bytes",
    }
    assert all(isinstance(value, str) for value in frames.values())


def test_refused_upload_also_records_metadata_only(fake_capture):
    recorded = []
    controller = CaptureController(
        AgentConfig(api_url="http://127.0.0.1:9", timeout_sec=1.0),
        recorder=lambda *args: recorded.append(args),
    )
    controller.capture_summary()
    assert not controller.capture_scoreboard()
    assert recorded[0][0] == "error"
    assert recorded[0][2] is None
    assert recorded[0][3]["summary_frame"].endswith("7 bytes")


def test_recorder_failure_does_not_change_capture_outcome(mock_api, fake_capture):
    base, server = mock_api
    controller = CaptureController(
        AgentConfig(api_url=base),
        recorder=lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )
    controller.capture_summary()
    assert controller.capture_scoreboard()
    assert server.upload_count == 1


def test_capture_failure_message_is_actionable():
    message = capture_error_message("Summary", RuntimeError("no screen"))
    assert "could not start" in message and "selected display" in message


def test_invalid_device_key_message_explains_recovery():
    message = upload_error_message(
        AgentConfig(bearer_token="device-key-example"),
        UploadError("upload failed (401): Invalid or revoked device token"),
    )
    assert "invalid or revoked" in message and "run the self test again" in message


def test_api_403_detail_is_relayed():
    detail = "This device needs a replacement key."
    message = upload_error_message(
        AgentConfig(), UploadError(f'upload failed (403): {{"detail": "{detail}"}}')
    )
    assert detail in message
