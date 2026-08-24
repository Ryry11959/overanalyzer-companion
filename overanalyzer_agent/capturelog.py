"""A local metadata-only record of capture attempts.

Full frames are transient upload inputs and must never land at rest. Each debug folder
therefore contains only a readable report and JSON metadata such as frame dimensions,
encoded byte counts, service host, and settled status. No credentials or pixels are
written.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from overanalyzer_agent.session import default_state_path

DEBUG_DIR_NAME = "debug_out"
KEEP_ATTEMPTS = 10
REPORT_TXT = "attempt.txt"
REPORT_JSON = "attempt.json"
STAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"


def debug_dir(config_path: str | None = None) -> Path:
    """Return the attempt-report directory beside the app's state file."""
    return default_state_path(config_path).parent / DEBUG_DIR_NAME


@dataclass
class Attempt:
    outcome: str
    detail: str = ""
    match_id: str | None = None
    api_host: str = ""
    app_version: str = ""
    monitor: str = ""
    frame_size: str = ""
    frames: dict[str, str] = field(default_factory=dict)
    regions: dict[str, str] = field(default_factory=dict)
    stages: list[tuple[str, str, str]] = field(default_factory=list)
    at: str = ""

    def as_dict(self) -> dict:
        return {
            "at": self.at,
            "outcome": self.outcome,
            "detail": self.detail,
            "match_id": self.match_id,
            "api_host": self.api_host,
            "app_version": self.app_version,
            "monitor": self.monitor,
            "frame_size": self.frame_size,
            "frames": dict(self.frames),
            "regions": dict(self.regions),
            "stages": [
                {"stage": name, "result": result, "detail": detail}
                for name, result, detail in self.stages
            ],
        }

    def as_text(self) -> str:
        lines = [
            "OverAnalyzer capture attempt",
            "=" * 30,
            f"When      : {self.at}",
            f"Outcome   : {self.outcome}",
        ]
        if self.detail:
            lines.append(f"Detail    : {self.detail}")
        if self.match_id:
            lines.append(f"Match id  : {self.match_id}")
        lines += [
            f"App       : {self.app_version}",
            f"Service   : {self.api_host}",
            f"Display   : {self.monitor}",
            f"Frame     : {self.frame_size}",
        ]
        if self.frames:
            lines.append("Frames    :")
            lines += [f"  {name}: {value}" for name, value in self.frames.items()]
        if self.regions:
            lines.append("Checks    :")
            lines += [f"  {name}: {value}" for name, value in self.regions.items()]
        if self.stages:
            lines += ["", "Stages", "-" * 30]
            for name, result, detail in self.stages:
                lines.append(f"[{result.upper():<7}] {name}" + (f" - {detail}" if detail else ""))
        lines += [
            "",
            "This folder holds no password, device key, screenshots, or frame pixels.",
            "The full game frames were uploaded only for processing and then discarded.",
        ]
        return "\n".join(lines) + "\n"


def record_attempt(
    attempt: Attempt,
    *,
    directory: Path,
    keep: int = KEEP_ATTEMPTS,
    now: datetime | None = None,
) -> Path | None:
    """Write one metadata-only attempt folder and prune old reports. Never raises."""
    try:
        moment = now or datetime.now()
        stamp = moment.strftime(STAMP_FORMAT)
        attempt.at = attempt.at or moment.isoformat(timespec="seconds")
        target = _unique_dir(directory, f"{stamp}_{_slug(attempt.outcome)}")
        target.mkdir(parents=True, exist_ok=True)
        (target / REPORT_TXT).write_text(attempt.as_text(), encoding="utf-8")
        (target / REPORT_JSON).write_text(
            json.dumps(attempt.as_dict(), indent=2), encoding="utf-8"
        )
        prune(directory, keep=keep)
        return target
    except OSError:
        return None


def _slug(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in "-_" else "_"
                   for character in value.strip().lower())
    return safe or "attempt"


def _unique_dir(directory: Path, name: str) -> Path:
    candidate = directory / name
    suffix = 2
    while candidate.exists():
        candidate = directory / f"{name}-{suffix}"
        suffix += 1
    return candidate


def recent_attempts(directory: Path) -> list[Path]:
    try:
        entries = [path for path in directory.iterdir() if path.is_dir()]
    except OSError:
        return []
    return sorted(entries, key=lambda path: path.name, reverse=True)


def prune(directory: Path, *, keep: int = KEEP_ATTEMPTS) -> list[Path]:
    """Drop all but the newest attempt reports and return what was removed."""
    removed: list[Path] = []
    for stale in recent_attempts(directory)[max(0, keep):]:
        try:
            for child in stale.iterdir():
                child.unlink()
            stale.rmdir()
            removed.append(stale)
        except OSError:
            continue
    return removed


def open_folder(directory: Path) -> bool:
    """Open the metadata report folder in the operating system's file manager."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(directory))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(directory)])
        else:
            subprocess.Popen(["xdg-open", str(directory)])
        return True
    except (OSError, AttributeError):
        return False
