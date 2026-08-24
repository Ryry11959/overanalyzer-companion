"""Upload transient full Game Report frames to the OverAnalyzer API."""
from __future__ import annotations

import time

import requests

UPLOAD_PATH = "/api/uploads/screenshots"
CAPTURE_FORMAT = "full_frames_v1"
MATCH_STATUS_PATH = "/api/matches/{match_id}/status"
MATCH_PATH = "/api/matches/{match_id}"

TERMINAL_STATUSES = frozenset({"complete", "partial", "needs_review", "failed"})


class UploadError(RuntimeError):
    """Network failure or a non-2xx response from the API."""


def upload(
    api_url: str,
    *,
    summary_frame: bytes,
    teams_frame: bytes,
    self_gamertag: str | None = None,
    bearer_token: str | None = None,
    timeout: float = 30.0,
) -> dict:
    """Upload both full source frames and return the parsed response body."""
    if not summary_frame:
        raise UploadError("summary frame is required")
    if not teams_frame:
        raise UploadError("teams frame is required")

    url = api_url.rstrip("/") + UPLOAD_PATH
    files = {
        "summary_frame": ("summary-frame.png", summary_frame, "image/png"),
        "teams_frame": ("teams-frame.png", teams_frame, "image/png"),
    }
    data = {"capture_format": CAPTURE_FORMAT}
    if self_gamertag:
        data["self_gamertag"] = self_gamertag
    headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}

    try:
        response = requests.post(url, files=files, data=data, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise UploadError(f"request to {url} failed: {exc}") from exc

    if response.status_code >= 400:
        raise UploadError(f"upload failed ({response.status_code}): {response.text[:200]}")
    try:
        return response.json()
    except ValueError as exc:
        raise UploadError(f"API returned non-JSON response: {response.text[:200]}") from exc


def delete_match(
    api_url: str,
    match_id: str,
    *,
    bearer_token: str | None = None,
    timeout: float = 10.0,
) -> None:
    """Delete the real match created by the self test."""
    url = api_url.rstrip("/") + MATCH_PATH.format(match_id=match_id)
    headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
    try:
        response = requests.delete(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise UploadError(f"request to {url} failed: {exc}") from exc
    if response.status_code >= 400 and response.status_code != 404:
        raise UploadError(f"delete failed ({response.status_code}): {response.text[:200]}")


def poll_match_status(
    api_url: str,
    match_id: str,
    *,
    bearer_token: str | None = None,
    interval: float = 1.0,
    max_wait: float = 20.0,
    timeout: float = 10.0,
    _sleep=time.sleep,
    _now=time.monotonic,
) -> str:
    """Poll a match until OCR settles, or return its last readable state."""
    url = api_url.rstrip("/") + MATCH_STATUS_PATH.format(match_id=match_id)
    headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
    deadline = _now() + max_wait
    last = "processing"
    while True:
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code < 400:
                last = response.json().get("status", last)
                if last in TERMINAL_STATUSES:
                    return last
            else:
                return "unknown"
        except (requests.RequestException, ValueError):
            return "unknown"
        if _now() >= deadline:
            return last
        _sleep(interval)
