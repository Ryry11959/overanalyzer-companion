from __future__ import annotations

import importlib.util
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_origins.py"
SPEC = importlib.util.spec_from_file_location("verify_origins", SCRIPT)
assert SPEC and SPEC.loader
verify_origins = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_origins
SPEC.loader.exec_module(verify_origins)


WEB_ORIGIN = "https://overanalyzer.app"
API_ORIGIN = "https://api.overanalyzer.app"
HOST_SUFFIX = "rail" + "way" + ".app"
OLD_API_ORIGIN = "https://" + "api" + "-production-" + "51b4" + ".up." + HOST_SUFFIX


def _write_agent_source(root: Path, *, api_url: str = API_ORIGIN) -> None:
    config_path = root / "agent" / "overanalyzer_agent" / "config.py"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        f'DEFAULT_API_ORIGIN = "{api_url}"\n'
        f'DEFAULT_WEB_ORIGIN = "{WEB_ORIGIN}"\n',
        encoding="utf-8",
    )


def _check(root: Path, capsys: pytest.CaptureFixture[str], *, companion: str | None = None) -> tuple[int, str]:
    result = verify_origins._check(
        Namespace(
            root=str(root),
            web_origin=WEB_ORIGIN,
            api_origin=API_ORIGIN,
            companion_releases_url=companion,
        )
    )
    return result, capsys.readouterr().out


def test_real_origins_pass_and_deployment_history_is_reported(capsys, tmp_path: Path):
    _write_agent_source(tmp_path)
    (tmp_path / "HANDOFF.md").write_text(
        f"Historical deployment: {OLD_API_ORIGIN}\n",
        encoding="utf-8",
    )

    result, output = _check(tmp_path, capsys)

    assert result == 0
    assert "ALLOWED deployment history HANDOFF.md:1" in output
    assert "RESULT=PASS conflicts=0" in output


def test_railway_hostname_in_operational_source_fails(capsys, tmp_path: Path):
    _write_agent_source(tmp_path, api_url=OLD_API_ORIGIN)

    result, output = _check(tmp_path, capsys)

    assert result == 1
    assert "CONFLICT overanalyzer_agent/config.py" in output
    assert "reason=outside deployment history" in output
    assert "RESULT=FAIL conflicts=" in output


def test_unanswered_companion_url_is_reported_without_inventing_one(capsys, tmp_path: Path):
    _write_agent_source(tmp_path)
    downloads_path = tmp_path / "frontend" / "src" / "lib" / "downloads.ts"
    downloads_path.parent.mkdir(parents=True)
    downloads_path.write_text(
        'const url = "https://github.com/owner/not-yet-selected/releases/latest";\n',
        encoding="utf-8",
    )

    result, output = _check(tmp_path, capsys)

    assert result == 0
    assert "INTENDED_COMPANION_RELEASES_URL=UNSET" in output
    assert "UNVERIFIED frontend/src/lib/downloads.ts:1" in output
    assert "RESULT=PASS conflicts=0" in output


def test_git_ignored_local_config_is_not_scanned(capsys, tmp_path: Path):
    """A gitignored local `agent.toml` is the owner's own self-hosting state.

    It legitimately holds a device key and whatever origin that machine points
    at, so reading it would report a conflict no source change can clear.
    """
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    _write_agent_source(tmp_path)
    (tmp_path / ".gitignore").write_text("agent.toml\n", encoding="utf-8")
    (tmp_path / "agent" / "agent.toml").write_text(
        f'api_url = "{OLD_API_ORIGIN}"\n', encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)

    result, output = _check(tmp_path, capsys)

    assert result == 0
    assert "agent.toml" not in output
    assert "RESULT=PASS conflicts=0" in output
