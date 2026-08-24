"""The on-disk report must never contain uploaded frame pixels or credentials."""
from datetime import datetime
import json
from pathlib import Path

from overanalyzer_agent import capturelog


def _attempt(**kwargs) -> capturelog.Attempt:
    values = dict(
        outcome="needs_review",
        detail="Uploaded, needs review",
        match_id="abc123",
        api_host="api.overanalyzer.app",
        app_version="0.2.0",
        monitor="Primary display",
        frame_size="1920 x 1080",
        frames={
            "summary_frame": "1920 x 1080, 2000000 bytes",
            "teams_frame": "1920 x 1080, 3000000 bytes",
        },
    )
    values.update(kwargs)
    return capturelog.Attempt(**values)


def test_attempt_writes_only_text_and_json_reports(tmp_path: Path) -> None:
    folder = capturelog.record_attempt(_attempt(), directory=tmp_path)
    assert folder is not None
    assert {path.name for path in folder.iterdir()} == {"attempt.txt", "attempt.json"}
    assert not list(folder.glob("*.png"))


def test_json_carries_metadata_but_has_no_pixel_field(tmp_path: Path) -> None:
    attempt = _attempt()
    attempt.stages = [("Upload", "pass", "Accepted")]
    folder = capturelog.record_attempt(attempt, directory=tmp_path)
    payload = json.loads((folder / "attempt.json").read_text(encoding="utf-8"))
    assert payload["frames"]["summary_frame"].endswith("bytes")
    assert "images" not in payload and "screenshots" not in payload


def test_report_shape_has_nowhere_for_a_device_key() -> None:
    fields = set(_attempt().as_dict())
    assert not {field for field in fields if "token" in field or "key" in field or "secret" in field}


def test_text_states_that_full_frames_are_not_stored(tmp_path: Path) -> None:
    folder = capturelog.record_attempt(_attempt(), directory=tmp_path)
    text = (folder / "attempt.txt").read_text(encoding="utf-8")
    assert "no password, device key, screenshots, or frame pixels" in text
    assert "uploaded only for processing and then discarded" in text


def test_two_attempts_in_one_second_do_not_collide(tmp_path: Path) -> None:
    stamp = datetime(2026, 8, 10, 15, 42, 3)
    first = capturelog.record_attempt(_attempt(), directory=tmp_path, now=stamp)
    second = capturelog.record_attempt(_attempt(), directory=tmp_path, now=stamp)
    assert first is not None and second is not None and first != second


def test_only_newest_reports_are_kept(tmp_path: Path) -> None:
    for minute in range(8):
        capturelog.record_attempt(
            _attempt(),
            directory=tmp_path,
            keep=3,
            now=datetime(2026, 8, 10, 12, minute, 0),
        )
    kept = capturelog.recent_attempts(tmp_path)
    assert len(kept) == 3
    assert kept[0].name.startswith("2026-08-10_12-07-00")


def test_unwritable_directory_is_survivable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "mkdir", lambda *_a, **_kw: (_ for _ in ()).throw(OSError()))
    assert capturelog.record_attempt(_attempt(), directory=tmp_path) is None


def test_debug_dir_sits_beside_state_file(tmp_path: Path) -> None:
    config = tmp_path / "agent.toml"
    config.write_text("", encoding="utf-8")
    assert capturelog.debug_dir(str(config)) == tmp_path / capturelog.DEBUG_DIR_NAME


def test_removal_names_the_same_debug_directory() -> None:
    from overanalyzer_agent import removal

    assert capturelog.DEBUG_DIR_NAME in removal.confirmation_text()
