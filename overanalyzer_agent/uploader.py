"""POST captured screenshots to the OverAnalyzer API.

Targets the same endpoint the web app uses:
    POST {api_url}/api/uploads/screenshots   (multipart: summary[, team1, team2], self_gamertag)
which returns 202 + {match_id, status, message}. The summary part is required;
the two leaderboards are optional (a summary-only upload is recorded as partial).
"""
from __future__ import annotations

import time

import requests

UPLOAD_PATH = "/api/uploads/screenshots"
MATCH_STATUS_PATH = "/api/matches/{match_id}/status"
MATCH_PATH = "/api/matches/{match_id}"

# Statuses the OCR pipeline settles into once it stops "processing".
TERMINAL_STATUSES = frozenset({"complete", "partial", "needs_review", "failed"})


class UploadError(RuntimeError):
    """Network failure or a non-2xx response from the API."""


def upload(
    api_url: str,
    *,
    summary: bytes,
    team1: bytes | None = None,
    team2: bytes | None = None,
    self_gamertag: str | None = None,
    bearer_token: str | None = None,
    timeout: float = 30.0,
) -> dict:
    """Upload one match's screenshots. Returns the parsed JSON body on success."""
    if not summary:
        raise UploadError("summary image is required")

    url = api_url.rstrip("/") + UPLOAD_PATH
    files: dict[str, tuple[str, bytes, str]] = {
        "summary": ("summary.png", summary, "image/png"),
    }
    if team1 is not None:
        files["team1"] = ("team1.png", team1, "image/png")
    if team2 is not None:
        files["team2"] = ("team2.png", team2, "image/png")

    data: dict[str, str] = {}
    if self_gamertag:
        data["self_gamertag"] = self_gamertag
    headers: dict[str, str] = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    try:
        resp = requests.post(url, files=files, data=data, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise UploadError(f"request to {url} failed: {exc}") from exc

    if resp.status_code >= 400:
        raise UploadError(f"upload failed ({resp.status_code}): {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise UploadError(f"API returned non-JSON response: {resp.text[:200]}") from exc


def delete_match(
    api_url: str,
    match_id: str,
    *,
    bearer_token: str | None = None,
    timeout: float = 10.0,
) -> None:
    """Delete a match. Used to clean up after the self test's real upload.

    The self test proves the pipeline by sending a genuine capture, which
    creates a genuine match; leaving those behind would quietly pollute the
    user's history with test rows. Raises :class:`UploadError` so the caller can
    tell the user which match to remove by hand instead of pretending it is gone.
    """
    url = api_url.rstrip("/") + MATCH_PATH.format(match_id=match_id)
    headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
    try:
        resp = requests.delete(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise UploadError(f"request to {url} failed: {exc}") from exc
    # 404 means it is already gone, which is the outcome the caller wanted.
    if resp.status_code >= 400 and resp.status_code != 404:
        raise UploadError(f"delete failed ({resp.status_code}): {resp.text[:200]}")


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
    """Poll ``GET /api/matches/{id}/status`` until the OCR pipeline settles.

    Returns the terminal status (``complete`` / ``partial`` / ``needs_review`` /
    ``failed``), or ``processing`` if it's still running after ``max_wait`` - the
    upload is safe regardless, so the caller just reports "still processing".
    Returns ``unknown`` if the status can't be read (e.g. the match 404s).
    """
    url = api_url.rstrip("/") + MATCH_STATUS_PATH.format(match_id=match_id)
    headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
    deadline = _now() + max_wait
    last = "processing"
    while True:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code < 400:
                last = resp.json().get("status", last)
                if last in TERMINAL_STATUSES:
                    return last
            else:
                return "unknown"
        except (requests.RequestException, ValueError):
            return "unknown"
        if _now() >= deadline:
            return last
        _sleep(interval)
