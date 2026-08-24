"""Agent configuration: typed defaults, TOML loading, and environment overrides.

Capture geometry is intentionally absent. Older geometry and colour keys are ignored
when loaded so an existing installation upgrades without requiring config cleanup.
"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

APP_DATA_DIR_NAME = "OverAnalyzer"


def user_data_dir() -> Path:
    """Return the durable per-user directory used by a frozen app."""
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / APP_DATA_DIR_NAME
    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return base / APP_DATA_DIR_NAME.lower()


def runtime_config_path(*, frozen: bool | None = None) -> Path:
    """Resolve the default config path for source and frozen execution."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return user_data_dir() / "agent.toml"
    return Path(__file__).resolve().parent.parent / "agent.toml"


DEFAULT_CONFIG_PATH = runtime_config_path()
DEFAULT_API_ORIGIN = "https://api.overanalyzer.app"
DEFAULT_WEB_ORIGIN = "https://overanalyzer.app"


@dataclass
class AgentConfig:
    api_url: str = DEFAULT_API_ORIGIN
    web_url: str = DEFAULT_WEB_ORIGIN
    # Legacy fallback. The server now prefers the gamertag saved on the account.
    self_gamertag: str = ""
    bearer_token: str = ""
    timeout_sec: float = 30.0

    # None selects the primary display. Integers are 1-based mss monitor indexes.
    monitor_index: int | None = None

    hotkey_summary: str = "f11"
    hotkey_scoreboard: str = "f12"
    hotkey_reset: str = "f9"


_DEFAULTED_IF_BLANK = frozenset({"api_url", "web_url"})


def from_dict(data: dict[str, Any]) -> AgentConfig:
    """Merge known config keys over defaults, ignoring retired crop settings."""
    known = {field.name for field in fields(AgentConfig)}
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key not in known:
            continue
        if key in _DEFAULTED_IF_BLANK and not str(value).strip():
            continue
        if key == "bearer_token":
            kwargs[key] = "" if value is None else str(value).strip()
        else:
            kwargs[key] = value
    return AgentConfig(**kwargs)


def _apply_env(cfg: AgentConfig) -> AgentConfig:
    """Environment overrides win over the file."""
    if value := os.environ.get("OA_AGENT_API_URL"):
        cfg.api_url = value
    if value := os.environ.get("OA_AGENT_WEB_URL"):
        cfg.web_url = value
    if value := os.environ.get("OA_AGENT_GAMERTAG"):
        cfg.self_gamertag = value
    if value := os.environ.get("OA_AGENT_TOKEN"):
        cfg.bearer_token = value
    return cfg


def load_config(path: str | None = None) -> AgentConfig:
    """Load an optional TOML file, then apply environment overrides."""
    data: dict[str, Any] = {}
    resolved = path or (str(DEFAULT_CONFIG_PATH) if DEFAULT_CONFIG_PATH.exists() else None)
    if resolved:
        with open(resolved, "rb") as handle:
            data = tomllib.load(handle)
    return _apply_env(from_dict(data))


def to_dict(cfg: AgentConfig) -> dict[str, Any]:
    """Return a TOML-serializable config dictionary."""
    out: dict[str, Any] = {}
    for key, value in asdict(cfg).items():
        if value is None:
            continue
        if key in _DEFAULTED_IF_BLANK and not str(value).strip():
            continue
        out[key] = value
    return out


def save_config(cfg: AgentConfig, path: str | os.PathLike[str] | None = None) -> Path:
    """Write config to TOML and return the path used."""
    import tomli_w

    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as handle:
        tomli_w.dump(to_dict(cfg), handle)
    return target
