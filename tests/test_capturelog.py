"""The on-disk record of what was actually sent.

Two properties matter more than the rest: it must never contain a credential
(the folder exists to be shared with someone debugging it), and it must never
be able to break a capture.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pytest

from overanalyzer_agent import capturelog


def _attempt(**kwargs) -> capturelog.Attempt:
    base = dict(
        outcome="needs_review",
        detail="Uploaded, needs review",
        match_id="abc123",
        api_host="api.overanalyzer.app",
        app_version="0.1.0",
        monitor="Primary display",
        frame_size="1920 x 1080",
        regions={"summary_region": "auto"},
    )
    base.update(kwargs)
    return capturelog.Attempt(**base)


def _images() -> dict[str, bytes]:
    return {"summary": b"summary-bytes", "team1": b"team1-bytes", "team2": b""}


def test_an_attempt_writes_images_and_both_reports(tmp_path: Path) -> None:
    folder = capturelog.record_attempt(_attempt(), _images(), directory=tmp_path)
    assert folder is not None
    names = {p.name for p in folder.iterdir()}
    assert names == {"summary.png", "team1.png", "attempt.txt", "attempt.json"}
    assert (folder / "summary.png").read_bytes() == b"summary-bytes"


def test_an_empty_image_is_not_written(tmp_path: Path) -> None:
    folder = capturelog.record_attempt(_attempt(), {"summary": b"x", "team2": b""},
                                       directory=tmp_path)
    assert folder is not None and not (folder / "team2.png").exists()


def test_the_json_report_carries_the_facts(tmp_path: Path) -> None:
    attempt = _attempt()
    attempt.stages = [("Upload", "pass", "Accepted"), ("OCR pipeline", "fail", "OCR failed")]
    folder = capturelog.record_attempt(attempt, _images(), directory=tmp_path)
    assert folder is not None
    payload = json.loads((folder / "attempt.json").read_text(encoding="utf-8"))
    assert payload["outcome"] == "needs_review"
    assert payload["match_id"] == "abc123"
    assert payload["frame_size"] == "1920 x 1080"
    assert payload["stages"][1] == {
        "stage": "OCR pipeline", "result": "fail", "detail": "OCR failed"
    }


def test_the_report_has_nowhere_to_put_a_device_key() -> None:
    """The report is written to be sent to someone else, so the shape itself has
    to exclude the one secret the app holds. This guards the field list, not a
    particular string: adding a `token` field is the mistake worth catching."""
    fields = set(_attempt().as_dict())
    assert not {f for f in fields if "token" in f or "key" in f or "secret" in f}
    assert "api_host" in fields, "the host is the useful, non-secret half"


def test_a_key_leaked_into_a_message_is_still_written_verbatim(tmp_path: Path) -> None:
    """Honest limitation, pinned so nobody assumes redaction that isn't there.

    Nothing scrubs the free-text detail line. Today no caller puts a key in one
    (the API's own errors never echo it back), but if that changes, this test is
    the reminder that the report is a faithful copy, not a filter."""
    attempt = _attempt(detail="rejected: device-key-example")
    folder = capturelog.record_attempt(attempt, _images(), directory=tmp_path)
    assert folder is not None
    assert "device-key-example" in (folder / "attempt.txt").read_text(encoding="utf-8")


def test_the_text_report_warns_that_screenshots_show_gamertags(tmp_path: Path) -> None:
    folder = capturelog.record_attempt(_attempt(), _images(), directory=tmp_path)
    assert folder is not None
    text = (folder / "attempt.txt").read_text(encoding="utf-8")
    assert "gamertags" in text
    assert "no device key" in text.lower()


def test_two_attempts_in_the_same_second_do_not_collide(tmp_path: Path) -> None:
    stamp = datetime(2026, 8, 10, 15, 42, 3)
    first = capturelog.record_attempt(_attempt(), _images(), directory=tmp_path, now=stamp)
    second = capturelog.record_attempt(_attempt(), _images(), directory=tmp_path, now=stamp)
    assert first is not None and second is not None and first != second
    assert (second / "summary.png").exists()


def test_only_the_newest_attempts_are_kept(tmp_path: Path) -> None:
    for minute in range(8):
        capturelog.record_attempt(
            _attempt(), _images(), directory=tmp_path, keep=3,
            now=datetime(2026, 8, 10, 12, minute, 0),
        )
    kept = capturelog.recent_attempts(tmp_path)
    assert len(kept) == 3
    # Newest first, and the newest survived.
    assert kept[0].name.startswith("2026-08-10_12-07-00")


def test_recent_attempts_on_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert capturelog.recent_attempts(tmp_path / "nope") == []


def test_an_unwritable_directory_is_survivable(tmp_path: Path, monkeypatch) -> None:
    """A diagnostic aid must never be the reason a capture reports failure."""
    def _explode(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "mkdir", _explode)
    assert capturelog.record_attempt(_attempt(), _images(), directory=tmp_path) is None


def test_an_outcome_with_odd_characters_still_makes_a_folder(tmp_path: Path) -> None:
    folder = capturelog.record_attempt(
        _attempt(outcome="upload failed (403): forbidden/denied"), _images(), directory=tmp_path
    )
    assert folder is not None and folder.is_dir()


def test_the_debug_dir_sits_beside_the_state_file(tmp_path: Path) -> None:
    config = tmp_path / "agent.toml"
    config.write_text("", encoding="utf-8")
    assert capturelog.debug_dir(str(config)) == tmp_path / capturelog.DEBUG_DIR_NAME


def test_the_debug_dir_is_what_removal_deletes() -> None:
    """removal.py hunts for a folder of this exact name; keep them in step."""
    from overanalyzer_agent import removal

    assert capturelog.DEBUG_DIR_NAME in removal.confirmation_text()
