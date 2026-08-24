import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from overanalyzer_agent.uploader import UploadError, poll_match_status, upload


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.server.last_body = self.rfile.read(length)
        self.server.last_path = self.path
        self.server.last_headers = {key.lower(): value for key, value in self.headers.items()}
        payload = json.dumps(self.server.response_body).encode()
        self.send_response(self.server.response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.server.status_polls += 1
        payload = json.dumps({"status": self.server.match_status}).encode()
        self.send_response(self.server.status_get_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


@pytest.fixture
def mock_api():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.response_status = 202
    server.response_body = {"match_id": "abc123", "status": "processing"}
    server.last_path = None
    server.last_headers = {}
    server.last_body = b""
    server.match_status = "complete"
    server.status_get_code = 200
    server.status_polls = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server
    finally:
        server.shutdown()
        server.server_close()


def test_upload_sends_versioned_full_frame_contract(mock_api):
    base, server = mock_api
    body = upload(
        base,
        summary_frame=b"SUMMARY",
        teams_frame=b"TEAMS",
        self_gamertag="RYRY",
    )
    assert body["match_id"] == "abc123"
    assert server.last_path == "/api/uploads/screenshots"
    raw = server.last_body
    assert b'name="capture_format"' in raw and b"full_frames_v1" in raw
    assert b'name="summary_frame"' in raw and b'filename="summary-frame.png"' in raw
    assert b'name="teams_frame"' in raw and b'filename="teams-frame.png"' in raw
    assert b'name="summary"' not in raw and b'name="team1"' not in raw
    assert b'name="self_gamertag"' in raw and b"RYRY" in raw


def test_upload_requires_both_source_frames(mock_api):
    base, _ = mock_api
    with pytest.raises(UploadError, match="summary frame"):
        upload(base, summary_frame=b"", teams_frame=b"T")
    with pytest.raises(UploadError, match="teams frame"):
        upload(base, summary_frame=b"S", teams_frame=b"")


def test_upload_sends_bearer_token(mock_api):
    base, server = mock_api
    upload(base, summary_frame=b"S", teams_frame=b"T", bearer_token="device-key-example")
    assert server.last_headers["authorization"] == "Bearer device-key-example"


def test_upload_raises_on_error_status(mock_api):
    base, server = mock_api
    server.response_status = 415
    server.response_body = {"detail": "invalid frame"}
    with pytest.raises(UploadError):
        upload(base, summary_frame=b"S", teams_frame=b"T")


def test_upload_wraps_connection_errors():
    with pytest.raises(UploadError):
        upload(
            "http://127.0.0.1:9",
            summary_frame=b"S",
            teams_frame=b"T",
            timeout=1.0,
        )


def test_poll_returns_terminal_status(mock_api):
    base, server = mock_api
    server.match_status = "needs_review"
    assert poll_match_status(base, "m1", max_wait=5.0) == "needs_review"
    assert server.status_polls == 1


def test_poll_times_out_to_processing(mock_api):
    base, server = mock_api
    server.match_status = "processing"
    assert poll_match_status(base, "m1", max_wait=0.0) == "processing"


def test_poll_unknown_on_error_status(mock_api):
    base, server = mock_api
    server.status_get_code = 500
    assert poll_match_status(base, "m1", max_wait=5.0) == "unknown"
