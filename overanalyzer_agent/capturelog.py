"""A local record of what the app actually sent, for diagnosing a bad capture.

When an upload comes back wrong, the only thing that explains it is the image
that was sent - the crop geometry, whether the leaderboard anchors landed, what
the summary strip actually contained. Until now the app kept none of that: the
bytes went out and were forgotten, so a user reporting "it read my score wrong"
had nothing to attach and the only recourse was to reproduce it locally on the
owner's own hardware.

Each attempt becomes one folder under ``debug_out``:

    2026-08-10_15-42-03_needs_review/
        summary.png
        team1.png
        team2.png
        attempt.txt     <- human readable, the file a user sends in
        attempt.json    <- the same facts, for tooling

**Nothing here may contain a credential.** The device key is the one secret the
app holds, and a debug folder exists to be shared, so the report records the API
host and never the token. The screenshots do contain gamertags, which is
inherent - they are pictures of a scoreboard - so the report says so in plain
words rather than letting someone attach them unaware.

Old attempts are pruned to :data:`KEEP_ATTEMPTS`, because this is a diagnostic
buffer and not an archive: the raw screenshots are already retained server-side
as the source of truth.
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

# Folder-name-safe, sorts chronologically as a string.
STAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"


def debug_dir(config_path: str | None = None) -> Path:
    """Where capture attempts are kept.

    Deliberately derived from the same base as ``agent.state.json`` so a frozen
    build writes under ``%LOCALAPPDATA%\\OverAnalyzer`` and a source checkout
    writes next to ``agent.toml`` - and so ``removal.py`` keeps finding it.
    """
    return default_state_path(config_path).parent / DEBUG_DIR_NAME


@dataclass
class Attempt:
    """One capture/upload attempt, as it will be written to disk."""

    outcome: str  # complete / needs_review / partial / failed / error / ...
    detail: str = ""
    match_id: str | None = None
    api_host: str = ""
    app_version: str = ""
    monitor: str = ""
    frame_size: str = ""
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
            "regions": dict(self.regions),
            "stages": [
                {"stage": name, "result": result, "detail": detail}
                for name, result, detail in self.stages
            ],
        }

    def as_text(self, images: list[str]) -> str:
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
        if self.regions:
            lines.append("Regions   :")
            lines += [f"  {name}: {value}" for name, value in self.regions.items()]
        if self.stages:
            lines.append("")
            lines.append("Stages")
            lines.append("-" * 30)
            for name, result, detail in self.stages:
                lines.append(f"[{result.upper():<7}] {name}" + (f" - {detail}" if detail else ""))
        lines.append("")
        lines.append("Files")
        lines.append("-" * 30)
        lines += [f"  {name}" for name in images] or ["  (no images were captured)"]
        lines += [
            "",
            "This folder holds no password and no device key.",
            "The screenshots are pictures of the Game Report, so they do show the",
            "gamertags that were in your match. Check that before sharing them.",
        ]
        return "\n".join(lines) + "\n"


def record_attempt(
    attempt: Attempt,
    images: dict[str, bytes],
    *,
    directory: Path,
    keep: int = KEEP_ATTEMPTS,
    now: datetime | None = None,
) -> Path | None:
    """Write one attempt folder and prune old ones. Never raises.

    Returns the folder, or ``None`` if it could not be written - a diagnostic
    aid must never be the reason a capture fails.
    """
    try:
        stamp = (now or datetime.now()).strftime(STAMP_FORMAT)
        attempt.at = attempt.at or (now or datetime.now()).isoformat(timespec="seconds")
        target = _unique_dir(directory, f"{stamp}_{_slug(attempt.outcome)}")
        target.mkdir(parents=True, exist_ok=True)

        written: list[str] = []
        for name, blob in images.items():
            if not blob:
                continue
            path = target / f"{_slug(name)}.png"
            path.write_bytes(blob)
            written.append(path.name)

        (target / REPORT_TXT).write_text(attempt.as_text(sorted(written)), encoding="utf-8")
        (target / REPORT_JSON).write_text(
            json.dumps(attempt.as_dict(), indent=2), encoding="utf-8"
        )
        prune(directory, keep=keep)
        return target
    except OSError:
        return None


def _slug(value: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in value.strip().lower())
    return safe or "attempt"


def _unique_dir(directory: Path, name: str) -> Path:
    """Two captures inside one second must not overwrite each other."""
    candidate = directory / name
    suffix = 2
    while candidate.exists():
        candidate = directory / f"{name}-{suffix}"
        suffix += 1
    return candidate


def recent_attempts(directory: Path) -> list[Path]:
    """Attempt folders, newest first. An unreadable directory reads as empty."""
    try:
        entries = [p for p in directory.iterdir() if p.is_dir()]
    except OSError:
        return []
    return sorted(entries, key=lambda p: p.name, reverse=True)


def prune(directory: Path, *, keep: int = KEEP_ATTEMPTS) -> list[Path]:
    """Drop all but the newest ``keep`` attempts. Returns what was removed."""
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
    """Show the folder in the OS file manager, creating it if it is missing.

    Opening an empty folder is a better answer than an error message: it shows
    the user where captures will appear.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(directory))  # noqa: S606 - a user-initiated folder open
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(directory)])
        else:
            subprocess.Popen(["xdg-open", str(directory)])
        return True
    except (OSError, AttributeError):
        return False
