"""Updating the capture app.

This is the one module that downloads a file and arranges to run it, so most of
these tests are about what it refuses: a non-HTTPS location, a host the app was
not built to trust, a payload whose checksum does not match, and a download that
will not stop. The happy path is the smallest part of the surface.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from overanalyzer_agent import updater
from overanalyzer_agent.config import AgentConfig

GOOD_URL = (
    "https://github.com/rphegel/OverAnalyzer/releases/download/agent-v0.2.0/OverAnalyzer.exe"
)
PAYLOAD = b"a new build of the capture app"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


class FakeResponse:
    def __init__(self, body: bytes = b"", *, status: int = 200, json_body=None,
                 headers: dict | None = None) -> None:
        self.status_code = status
        self._body = body
        self._json = json_body
        self.headers = headers or {"Content-Length": str(len(body))}

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]


def _release(**kwargs) -> updater.Release:
    base = dict(version="0.2.0", url=GOOD_URL, sha256=DIGEST, notes="", mandatory=False)
    base.update(kwargs)
    return updater.Release(**base)


def _announcement(**kwargs) -> dict:
    body = {"version": "0.2.0", "url": GOOD_URL, "sha256": DIGEST, "notes": "Fixes"}
    body.update(kwargs)
    return body


# --- version comparison -----------------------------------------------------
def test_versions_compare_numerically_not_as_strings():
    assert updater.is_newer("0.10.0", "0.9.0")
    assert not updater.is_newer("0.9.0", "0.10.0")


def test_the_same_version_is_not_an_update():
    assert not updater.is_newer("0.1.0", "0.1.0")


def test_a_v_prefix_and_odd_parts_do_not_crash_the_check():
    assert updater.parse_version("v1.2.3-beta") == (1, 2, 3)
    assert updater.parse_version("nonsense") == (0,)
    assert not updater.is_newer("nonsense", "0.1.0")


# --- what the service is allowed to say -------------------------------------
def test_an_available_release_is_offered():
    release = updater.check_for_update(
        AgentConfig(), current_version="0.1.0",
        request_get=lambda *_a, **_kw: FakeResponse(json_body=_announcement()),
    )
    assert release is not None
    assert release.version == "0.2.0" and release.notes == "Fixes"


def test_no_announcement_means_no_update():
    assert updater.check_for_update(
        AgentConfig(), current_version="0.1.0",
        request_get=lambda *_a, **_kw: FakeResponse(status=204),
    ) is None


def test_an_older_or_equal_announcement_is_ignored():
    assert updater.check_for_update(
        AgentConfig(), current_version="0.3.0",
        request_get=lambda *_a, **_kw: FakeResponse(json_body=_announcement()),
    ) is None


def test_the_service_cannot_point_the_app_at_another_host():
    """The core trust rule: a compromised API must not be able to name an
    arbitrary binary for a user's machine to download and run."""
    assert updater.check_for_update(
        AgentConfig(), current_version="0.1.0",
        request_get=lambda *_a, **_kw: FakeResponse(
            json_body=_announcement(url="https://evil.example/OverAnalyzer.exe")
        ),
    ) is None


def test_a_plain_http_location_is_refused():
    assert updater.check_for_update(
        AgentConfig(), current_version="0.1.0",
        request_get=lambda *_a, **_kw: FakeResponse(
            json_body=_announcement(url="http://github.com/x/OverAnalyzer.exe")
        ),
    ) is None


def test_an_announcement_without_a_full_digest_is_ignored():
    assert updater.check_for_update(
        AgentConfig(), current_version="0.1.0",
        request_get=lambda *_a, **_kw: FakeResponse(json_body=_announcement(sha256="abc")),
    ) is None


def test_an_offline_check_is_silent_not_an_error():
    def _explode(*_a, **_kw):
        raise OSError("no route to host")

    assert updater.check_for_update(
        AgentConfig(), current_version="0.1.0", request_get=_explode
    ) is None


def test_a_garbage_response_is_ignored():
    assert updater.check_for_update(
        AgentConfig(), current_version="0.1.0",
        request_get=lambda *_a, **_kw: FakeResponse(status=200),
    ) is None


# --- downloading ------------------------------------------------------------
def test_a_verified_download_is_kept(tmp_path: Path):
    target = tmp_path / "OverAnalyzer.exe"
    result = updater.download_release(
        _release(), target, request_get=lambda *_a, **_kw: FakeResponse(PAYLOAD)
    )
    assert result.read_bytes() == PAYLOAD
    assert not target.with_suffix(".exe.part").exists()


def test_a_checksum_mismatch_is_discarded(tmp_path: Path):
    """The published checksum is the whole integrity story for an unsigned
    binary, so a mismatch must leave nothing behind to run."""
    target = tmp_path / "OverAnalyzer.exe"
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download_release(
            _release(sha256="00" * 32), target,
            request_get=lambda *_a, **_kw: FakeResponse(PAYLOAD),
        )
    assert not target.exists()
    assert not target.with_suffix(".exe.part").exists()


def test_an_oversized_download_is_stopped(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(updater, "MAX_DOWNLOAD_BYTES", 8)
    target = tmp_path / "OverAnalyzer.exe"
    with pytest.raises(updater.UpdateError, match="larger than expected"):
        updater.download_release(
            _release(), target, request_get=lambda *_a, **_kw: FakeResponse(PAYLOAD)
        )
    assert not target.exists()


def test_a_failed_download_reports_http_status(tmp_path: Path):
    with pytest.raises(updater.UpdateError, match="404"):
        updater.download_release(
            _release(), tmp_path / "OverAnalyzer.exe",
            request_get=lambda *_a, **_kw: FakeResponse(b"", status=404),
        )


def test_download_refuses_a_disallowed_host_before_requesting(tmp_path: Path):
    called = []

    with pytest.raises(updater.UpdateError):
        updater.download_release(
            _release(url="https://evil.example/x.exe"), tmp_path / "x.exe",
            request_get=lambda *a, **kw: called.append(a) or FakeResponse(PAYLOAD),
        )
    assert called == [], "nothing should be requested from a refused host"


def test_progress_is_reported_while_downloading(tmp_path: Path):
    seen: list[tuple[int, int]] = []
    updater.download_release(
        _release(), tmp_path / "OverAnalyzer.exe",
        request_get=lambda *_a, **_kw: FakeResponse(PAYLOAD),
        on_progress=lambda written, expected: seen.append((written, expected)),
    )
    assert seen and seen[-1][0] == len(PAYLOAD)


# --- installing -------------------------------------------------------------
def test_installing_downloads_then_schedules_the_swap(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(updater, "staging_path", lambda version: tmp_path / f"{version}.exe")
    commands: list[list[str]] = []
    exe = tmp_path / "OverAnalyzer.exe"
    exe.write_bytes(b"the old build")

    report = updater.install_release(
        _release(), executable=exe,
        request_get=lambda *_a, **_kw: FakeResponse(PAYLOAD),
        helper_runner=commands.append,
        process_id=4321,
    )
    assert commands, "the detached helper must be started"
    assert "powershell.exe" in commands[0][0]
    assert report == updater.failure_report_path(4321)
    # The running executable is untouched until the helper runs.
    assert exe.read_bytes() == b"the old build"


def test_a_source_checkout_is_told_to_use_git(tmp_path: Path):
    with pytest.raises(updater.UpdateError, match="from source"):
        updater.install_release(_release(), executable=None)


def test_a_failed_download_never_starts_the_helper(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(updater, "staging_path", lambda version: tmp_path / f"{version}.exe")
    commands: list = []
    with pytest.raises(updater.UpdateError):
        updater.install_release(
            _release(sha256="11" * 32), executable=tmp_path / "OverAnalyzer.exe",
            request_get=lambda *_a, **_kw: FakeResponse(PAYLOAD),
            helper_runner=commands.append,
        )
    assert commands == []


# --- the swap helper --------------------------------------------------------
def test_the_helper_waits_for_this_process_before_swapping():
    script = updater.swap_helper_script(Path("C:/app/OverAnalyzer.exe"), Path("C:/tmp/new.exe"), 99)
    assert "Get-Process -Id 99" in script
    assert "Move-Item" in script


def test_the_helper_restores_the_old_build_if_the_swap_fails():
    """A failed update must leave a working app, not no app."""
    script = updater.swap_helper_script(Path("C:/app/OverAnalyzer.exe"), Path("C:/tmp/new.exe"), 7)
    assert "catch" in script
    assert "$backup" in script and "Move-Item -LiteralPath $backup" in script
    assert "WriteAllLines" in script, "a silent failure would be invisible"


def test_the_helper_restarts_the_app():
    script = updater.swap_helper_script(Path("C:/app/OverAnalyzer.exe"), Path("C:/tmp/new.exe"), 7)
    assert "Start-Process" in script


def test_paths_with_quotes_cannot_break_out_of_the_script():
    script = updater.swap_helper_script(
        Path("C:/app/O'Brien's App.exe"), Path("C:/tmp/new.exe"), 7
    )
    assert "'C:\\app\\O''Brien''s App.exe'" in script or "O''Brien''s" in script
