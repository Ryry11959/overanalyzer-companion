"""CLI capture loop (and launcher for the tray app / settings window).

Workflow:
  * On the Summary screen, press its hotkey to hold the full frame in memory.
  * On the Teams screen, press its hotkey to check and upload both full frames.
    The service crops them and discards the full frames after processing.
  * The reset hotkey clears a half-captured buffer.

The capture/upload logic lives in :mod:`overanalyzer_agent.controller`; this
module is just the CLI driver. ``keyboard`` is imported lazily inside ``run`` so
the module imports cleanly on a machine without it. Pass ``--tray`` to launch the
system-tray app instead, or ``--settings`` to open the settings window.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from overanalyzer_agent import __version__
from overanalyzer_agent.config import AgentConfig, load_config
from overanalyzer_agent.controller import CaptureController, StatusEvent


def _log(msg: str) -> None:
    print(msg, flush=True)


def _print_listener(event: StatusEvent) -> None:
    """Render controller status events as CLI log lines."""
    _log(event.message)


def version_message() -> str:
    """The version string used by both source and frozen command-line checks."""
    return f"overanalyzer-agent {__version__}"


def initial_screen(cfg: AgentConfig) -> str:
    """First-run users land in pairing; already-paired users go to capture."""
    return "main" if cfg.bearer_token else "settings"


def missing_bundled_assets() -> list[Path]:
    """Return required fonts and role marks missing from this installation.

    This deliberately uses the same locations as the UI modules.  The packaging
    smoke check can therefore prove the one-file executable extracted the asset
    tree where the live application will look for it, without opening Tk.
    """
    from overanalyzer_agent.ui.assets import ROLE_DIR, ROLES
    from overanalyzer_agent.ui.fonts import BUNDLED, FONT_DIR

    required = [*(FONT_DIR / name for name in BUNDLED)]
    required.extend(ROLE_DIR / f"{role}.png" for role in ROLES)
    return [path for path in required if not path.is_file()]


def verify_bundled_assets() -> int:
    """Check that the frozen app can resolve its explicitly bundled assets."""
    missing = missing_bundled_assets()
    if missing:
        _log("Missing bundled assets:")
        for path in missing:
            _log(f"  {path}")
        return 1
    _log("Bundled assets verified.")
    return 0


def run(cfg: AgentConfig) -> None:
    import keyboard  # lazy: global-hotkey lib, only needed at runtime

    controller = CaptureController(cfg, listener=_print_listener)
    keyboard.add_hotkey(cfg.hotkey_summary, controller.capture_summary)
    keyboard.add_hotkey(cfg.hotkey_scoreboard, controller.capture_scoreboard)
    keyboard.add_hotkey(cfg.hotkey_reset, controller.reset)

    _log("OverAnalyzer capture agent running. Capture is hotkey-only, never continuous.")
    _log("Full game frames are uploaded for processing, cropped by the service, then discarded.")
    if not cfg.bearer_token:
        _log(
            "No device key is saved. Open the desktop app Settings, sign in to the "
            "web app, paste one key, and run the self test before capturing."
        )
    # No gamertag here on purpose: your in-game name lives on your account now.
    _log(f"  API: {cfg.api_url}")
    _log(
        f"  {cfg.hotkey_summary}: capture summary   "
        f"{cfg.hotkey_scoreboard}: capture scoreboard + upload   "
        f"{cfg.hotkey_reset}: reset   (Ctrl+C to quit)"
    )
    try:
        keyboard.wait()
    except KeyboardInterrupt:
        _log("Shutting down.")


def main(argv: list[str] | None = None) -> int:
    # PyInstaller's windowed executable intentionally has no console. Handle
    # the release smoke checks before argparse writes its normal help text so
    # they remain safe in that GUI subsystem as well as in a terminal.
    args_in = sys.argv[1:] if argv is None else argv
    if args_in == ["--version"]:
        _log(version_message())
        return 0
    if args_in == ["--verify-assets"]:
        return verify_bundled_assets()

    parser = argparse.ArgumentParser(prog="overanalyzer-agent", description=__doc__)
    parser.add_argument(
        "-c", "--config", help="Path to an agent TOML config (see agent.example.toml)."
    )
    parser.add_argument(
        "--cli", action="store_true",
        help="Run the headless hotkey loop (no window) instead of the app.",
    )
    parser.add_argument(
        "--tray", action="store_true", help="Launch the system-tray app instead of the window."
    )
    parser.add_argument(
        "--settings", action="store_true",
        help="Open the app on its settings screen instead of the main panel.",
    )
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except (OSError, ValueError) as exc:
        _log(f"Config error: {exc}")
        return 2

    if args.settings:
        from overanalyzer_agent.window import open_window

        open_window(cfg, args.config, screen="settings")
        return 0
    if args.tray:
        from overanalyzer_agent.tray import run_tray

        run_tray(cfg, args.config)
        return 0
    if args.cli:
        run(cfg)
        return 0

    # Default: the standalone capture app window.
    from overanalyzer_agent.window import open_window

    open_window(cfg, args.config, screen=initial_screen(cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
