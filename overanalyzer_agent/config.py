"""Agent configuration: typed defaults, TOML file loading, and env overrides.

Regions are resolution-specific. The defaults below match the original
``calibrated capture geometry`` capture geometry (summary crop 300x620 at
(1300,180), leaderboard width 850, the Overwatch blue/red leaderboard anchor colors).
Tune ``summary_region`` (and, in ``region`` mode, the leaderboard rectangles) to
your own screen resolution - see ``agent.example.toml`` and the README.
"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

Box = tuple[int, int, int, int]  # (left, top, right, bottom), PIL crop order
Color = tuple[int, int, int]

# Capture geometry is expressed against this reference frame and scaled to whatever
# the player actually runs - see capture.ui_rect. Overwatch lays its menus out in a
# 16:9 box scaled to fit the display and centred, so one reference set covers every
# resolution of that shape, and ultrawide/letterboxed displays get the offset applied.
REFERENCE_FRAME = (1920, 1080)
REFERENCE_SUMMARY_REGION: Box = (1300, 180, 1600, 800)
REFERENCE_LEADERBOARD_WIDTH = 850

APP_DATA_DIR_NAME = "OverAnalyzer"


def user_data_dir() -> Path:
    """Return the durable per-user directory used by a frozen app.

    A PyInstaller one-file executable runs its Python modules from a transient
    ``_MEI*`` extraction directory. User-owned configuration and state must
    therefore live outside the bundle. ``LOCALAPPDATA`` is the Windows
    per-user location; the non-Windows fallback keeps headless development and
    tests deterministic without changing the frozen Windows contract.
    """
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / APP_DATA_DIR_NAME
    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return base / APP_DATA_DIR_NAME.lower()


def runtime_config_path(*, frozen: bool | None = None) -> Path:
    """Resolve the default config path for source and frozen execution.

    Source runs keep the established ``agent.toml`` contract. A frozen
    one-file build uses the durable per-user directory because its package
    directory is the temporary ``_MEI*`` extraction tree.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return user_data_dir() / "agent.toml"
    return Path(__file__).resolve().parent.parent / "agent.toml"


# The tray + settings window read/write here unless told otherwise; the CLI
# still accepts an explicit ``--config`` path.
DEFAULT_CONFIG_PATH = runtime_config_path()


# These are the hosted service endpoints compiled into packaged builds. The
# OA_AGENT_* environment overrides remain the runtime switch for self-hosters.
DEFAULT_API_ORIGIN = "https://api.overanalyzer.app"
DEFAULT_WEB_ORIGIN = "https://overanalyzer.app"


@dataclass
class AgentConfig:
    # Where to send screenshots. Defaults to the configured service, because
    # that is where captures go for everyone who isn't self-hosting - the app's
    # Settings screen deliberately doesn't ask for it. Self-hosters override it
    # in agent.toml or with OA_AGENT_API_URL.
    api_url: str = DEFAULT_API_ORIGIN
    # The web app that goes with ``api_url``. Presentation only: device pairing,
    # the "Open in app" link, and map art on the last-captured card.
    web_url: str = DEFAULT_WEB_ORIGIN
    # Legacy fallback: your in-game name now lives on your ACCOUNT (set during
    # onboarding in the web app), and the server prefers that. Kept so an older
    # agent.toml keeps working; the app no longer asks for it.
    self_gamertag: str = ""
    # Only needed when the server runs with the configured service requires a device key (paste a device
    # key minted in the web app). Leave blank for the default auth-off deployment.
    bearer_token: str = ""
    timeout_sec: float = 30.0

    # Which display to capture from. None (the default) is the primary monitor;
    # an int is an mss monitor index (1-based; see capture.list_monitors()) for
    # a multi-monitor setup where the game runs on a secondary display.
    monitor_index: int | None = None

    # Summary screen: a crop of the current frame. None (the default) derives it
    # proportionally from the frame size, which is what makes the app work on a
    # display other than the author's. Set it explicitly to override.
    summary_region: Box | None = None

    # Leaderboard capture: "anchor" finds the blue/red team bars automatically
    # (resolution-tolerant, ported from ScreenShot.py); "region" uses the fixed
    # team1_region/team2_region rectangles below.
    leaderboard_mode: str = "anchor"
    # None derives the width proportionally, like summary_region.
    leaderboard_width: int | None = None
    # (1,184,246) is the top/highlighted-row shade - without it the first row's
    # bar isn't matched and the blue crop loses its top player.
    blue_colors: list[Color] = field(
        default_factory=lambda: [(1, 186, 249), (1, 184, 247), (1, 184, 246)]
    )
    red_colors: list[Color] = field(default_factory=lambda: [(232, 45, 80)])
    # Per-channel slack when matching the bar colours above. DEFAULT 0 = exact match.
    #
    # Loosening this is NOT safe as a default. The anchor spans the min/max of every
    # matched pixel, so widening the match lets one stray pixel elsewhere on screen
    # stretch the crop box: at tolerance 24 a real capture produced 850x673 and
    # 850x562 boxes instead of ~850x330, which threw the row grid off and garbled the
    # whole scoreboard. Exact matching is narrow on purpose. Raise this only with a
    # box-plausibility check to go with it.
    color_tolerance: int = 0
    # Opt-in: when the configured colours find no leaderboard, sample the actual bar
    # colours off the frame instead - for players using Overwatch's colourblind friendly/
    # enemy palettes, where the bars are not blue and red at all. Off by default for
    # the same reason as above: a wrong-but-confident crop is worse than no capture.
    auto_team_colors: bool = False
    team1_region: Box | None = None  # used only in "region" mode
    team2_region: Box | None = None

    # Global hotkeys (see the `keyboard` library for names).
    hotkey_summary: str = "f11"
    hotkey_scoreboard: str = "f12"
    hotkey_reset: str = "f9"

    def __post_init__(self) -> None:
        if self.leaderboard_mode not in {"anchor", "region"}:
            raise ValueError(
                f"leaderboard_mode must be 'anchor' or 'region', got {self.leaderboard_mode!r}"
            )
        if self.leaderboard_mode == "region" and (
            self.team1_region is None or self.team2_region is None
        ):
            raise ValueError(
                "leaderboard_mode='region' requires both team1_region and team2_region"
            )


def _as_box(value: Any) -> Box | None:
    if value is None:
        return None
    seq = tuple(int(v) for v in value)
    if len(seq) != 4:
        raise ValueError(f"region must have 4 numbers (left, top, right, bottom), got {value!r}")
    return seq  # type: ignore[return-value]


def _as_colors(value: Any) -> list[Color]:
    return [tuple(int(c) for c in item) for item in value]  # type: ignore[misc]


# TOML has no null, so "unset" round-trips as an empty string. For the two URLs
# that means the built-in default, not "no server" - they aren't editable in the
# app, so a blank left in an old config would strand you with no way to fix it.
_DEFAULTED_IF_BLANK = frozenset({"api_url", "web_url"})


def from_dict(data: dict[str, Any]) -> AgentConfig:
    """Build a config from a dict, merging over the defaults (unknown keys ignored)."""
    known = {f.name for f in fields(AgentConfig)}
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key not in known:
            continue
        if key in _DEFAULTED_IF_BLANK and not str(value).strip():
            continue
        if key in {"summary_region", "team1_region", "team2_region"}:
            kwargs[key] = _as_box(value)
        elif key in {"blue_colors", "red_colors"}:
            kwargs[key] = _as_colors(value)
        elif key == "bearer_token":
            # Device keys are commonly pasted from the web app.  Keep the
            # persisted value usable even when a TOML editor leaves a newline
            # or surrounding spaces around it.
            kwargs[key] = "" if value is None else str(value).strip()
        else:
            kwargs[key] = value
    return AgentConfig(**kwargs)


def _apply_env(cfg: AgentConfig) -> AgentConfig:
    """Env overrides win over the file (handy for secrets / CI)."""
    if (v := os.environ.get("OA_AGENT_API_URL")):
        cfg.api_url = v
    if (v := os.environ.get("OA_AGENT_WEB_URL")):
        cfg.web_url = v
    if (v := os.environ.get("OA_AGENT_GAMERTAG")):
        cfg.self_gamertag = v
    if (v := os.environ.get("OA_AGENT_TOKEN")):
        cfg.bearer_token = v
    return cfg


def load_config(path: str | None = None) -> AgentConfig:
    """Load from a TOML file (if given) then apply env overrides.

    With no explicit ``path``, the user's ``agent.toml`` next to the package is
    loaded automatically when it exists (so the tray app works with no args);
    otherwise the typed defaults are used.
    """
    data: dict[str, Any] = {}
    resolved = path or (str(DEFAULT_CONFIG_PATH) if DEFAULT_CONFIG_PATH.exists() else None)
    if resolved:
        with open(resolved, "rb") as fh:
            data = tomllib.load(fh)
    return _apply_env(from_dict(data))


def to_dict(cfg: AgentConfig) -> dict[str, Any]:
    """A TOML-serializable dict of the config.

    Tuples become lists (TOML arrays) and ``None`` regions are dropped, since
    TOML has no null. The result round-trips back through :func:`from_dict`.
    """
    out: dict[str, Any] = {}
    for key, value in asdict(cfg).items():
        if value is None:
            continue
        if key in _DEFAULTED_IF_BLANK and not str(value).strip():
            continue  # don't pin a blank URL that from_dict would ignore anyway
        if isinstance(value, tuple):
            out[key] = list(value)
        elif isinstance(value, list):
            out[key] = [list(v) if isinstance(v, tuple) else v for v in value]
        else:
            out[key] = value
    return out


def save_config(cfg: AgentConfig, path: str | os.PathLike[str] | None = None) -> Path:
    """Write ``cfg`` to a TOML file (defaults to the user's ``agent.toml``).

    Returns the path written. Used by the settings window so users tune the app
    from a UI instead of hand-editing TOML.
    """
    import tomli_w  # lazy: only the settings/save path needs a TOML writer

    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as fh:
        tomli_w.dump(to_dict(cfg), fh)
    return target
