"""The small running tallies the panel's two stat tiles show, plus its window spot.

"Captured today" survives a restart (it's a count for the day, not for the
process), so it lives in a JSON file beside ``agent.toml``. Frozen one-file
builds use the durable per-user directory chosen by
:mod:`overanalyzer_agent.config`; source runs preserve their existing config
location. The win/loss record
is deliberately per-session and in memory: it only means anything for the run
you're in, and it's only ever filled in when a match could actually be read back
from the API - an unknown result is left out of the tally rather than guessed.

The last dragged window position lives in the same file, but unlike the daily
count it is NOT reset at midnight - once you've moved the panel somewhere, it
should reopen there every time, not snap back to the corner.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from overanalyzer_agent.config import DEFAULT_CONFIG_PATH

STATE_FILENAME = "agent.state.json"


def default_state_path(config_path: str | None = None) -> Path:
    base = Path(config_path).resolve().parent if config_path else DEFAULT_CONFIG_PATH.parent
    return base / STATE_FILENAME


@dataclass
class SessionStats:
    """Counts for the two tiles. Pure apart from :meth:`load` / :meth:`save`."""

    day: str = ""
    captured_today: int = 0
    last_upload_at: str | None = None
    wins: int = 0
    losses: int = 0
    draws: int = 0
    window_x: int | None = None
    window_y: int | None = None
    path: Path | None = field(default=None, repr=False)

    # --- counting ---------------------------------------------------------
    def record_upload(self, at: str, today: str | None = None) -> None:
        """One more capture uploaded. Rolls the counter over at midnight."""
        today = today or date.today().isoformat()
        if self.day != today:
            self.day, self.captured_today = today, 0
        self.captured_today += 1
        self.last_upload_at = at
        self.save()

    def record_result(self, result: str | None) -> None:
        if result == "win":
            self.wins += 1
        elif result == "loss":
            self.losses += 1
        elif result == "draw":
            self.draws += 1

    # --- presentation -----------------------------------------------------
    @property
    def played(self) -> int:
        return self.wins + self.losses + self.draws

    def record_label(self) -> str | None:
        """``"4-3"`` (or ``"4-3-1"`` with draws), or ``None`` before any result."""
        if not self.played:
            return None
        if self.draws:
            return f"{self.wins}-{self.losses}-{self.draws}"
        return f"{self.wins}-{self.losses}"

    def record_hint(self) -> str | None:
        decided = self.wins + self.losses
        if not decided:
            return None
        return f"{round(self.wins / decided * 100)}% win rate"

    def today_hint(self) -> str | None:
        return f"last {self.last_upload_at}" if self.last_upload_at else None

    # --- window position ----------------------------------------------------
    def set_window_position(self, x: int, y: int) -> None:
        """Remember where the panel was dragged to, and persist it immediately."""
        self.window_x, self.window_y = x, y
        self.save()

    # --- persistence ------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "SessionStats":
        target = path or default_state_path()
        stats = cls(path=target)
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return stats
        if data.get("day") == date.today().isoformat():
            stats.day = data["day"]
            stats.captured_today = int(data.get("captured_today", 0))
            stats.last_upload_at = data.get("last_upload_at")
        # Position isn't day-scoped - carry it forward regardless of `day`.
        wx, wy = data.get("window_x"), data.get("window_y")
        if isinstance(wx, int) and isinstance(wy, int):
            stats.window_x, stats.window_y = wx, wy
        return stats

    def save(self) -> None:
        if self.path is None:
            return
        payload = {
            "day": self.day,
            "captured_today": self.captured_today,
            "last_upload_at": self.last_upload_at,
        }
        if self.window_x is not None and self.window_y is not None:
            payload["window_x"] = self.window_x
            payload["window_y"] = self.window_y
        try:
            self.path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:  # a read-only install dir must not break capture
            pass
