import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from overanalyzer_agent.uploader import UploadError, poll_match_status, upload


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server.last_path = self.path
        self.server.last_headers = {k.lower(): v for k, v in self.headers.items()}
        self.server.last_body = body
        payload = json.dumps(self.server.response_body).encode()
        self.send_response(self.server.response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802 - status-poll endpoint
        self.server.status_polls += 1
        code = self.server.status_get_code
        payload = json.dumps({"status": self.server.match_status}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence test server logging
        pass


@pytest.fixture
def mock_api():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.response_status = 202
    server.response_body = {"match_id": "abc123", "status": "processing", "message": "ok"}
    server.last_path = None
    server.last_headers = {}
    server.last_body = b""
    server.match_status = "complete"
    server.status_get_code = 200
    server.status_polls = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _, port = server.server_address
        yield f"http://127.0.0.1:{port}", server
    finally:
        server.shutdown()
        server.server_close()


def test_upload_success_sends_all_parts(mock_api):
    base, server = mock_api
    body = upload(base, summary=b"S", team1=b"T1", team2=b"T2", self_gamertag="RYRY")
    assert body["match_id"] == "abc123"
    assert server.last_path == "/api/uploads/screenshots"
    raw = server.last_body
    assert b'name="summary"' in raw and b'filename="summary.png"' in raw
    assert b'name="team1"' in raw and b'name="team2"' in raw
    assert b'name="self_gamertag"' in raw and b"RYRY" in raw


def test_upload_summary_only_omits_teams(mock_api):
    base, server = mock_api
    upload(base, summary=b"S")
    raw = server.last_body
    assert b'name="summary"' in raw
    assert b'name="team1"' not in raw and b'name="team2"' not in raw


def test_upload_sends_bearer_token(mock_api):
    base, server = mock_api
    upload(base, summary=b"S", bearer_token="device-key-example")
    assert server.last_headers.get("authorization") == "Bearer device-key-example"


def test_upload_no_token_no_auth_header(mock_api):
    base, server = mock_api
    upload(base, summary=b"S")
    assert "authorization" not in server.last_headers


def test_upload_raises_on_error_status(mock_api):
    base, server = mock_api
    server.response_status = 415
    server.response_body = {"detail": "summary must be an image"}
    with pytest.raises(UploadError):
        upload(base, summary=b"S")


def test_upload_raises_on_connection_error():
    # Port 9 (discard) is not accepting connections -> ConnectionError -> UploadError.
    with pytest.raises(UploadError):
        upload("http://127.0.0.1:9", summary=b"S", timeout=1.0)


def test_upload_requires_summary(mock_api):
    base, _ = mock_api
    with pytest.raises(UploadError):
        upload(base, summary=b"")


def test_poll_returns_terminal_status(mock_api):
    base, server = mock_api
    server.match_status = "needs_review"
    assert poll_match_status(base, "m1", max_wait=5.0) == "needs_review"
    assert server.status_polls == 1


def test_poll_times_out_to_processing(mock_api):
    base, server = mock_api
    server.match_status = "processing"  # never settles
    assert poll_match_status(base, "m1", max_wait=0.0) == "processing"


def test_poll_unknown_on_error_status(mock_api):
    base, server = mock_api
    server.status_get_code = 500
    assert poll_match_status(base, "m1", max_wait=5.0) == "unknown"


def test_poll_unknown_on_connection_error():
    assert poll_match_status("http://127.0.0.1:9", "m1", max_wait=5.0, timeout=1.0) == "unknown"
