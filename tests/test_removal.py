from __future__ import annotations

import os
from pathlib import Path

from overanalyzer_agent.config import AgentConfig, runtime_config_path
from overanalyzer_agent.removal import (
    cleanup_helper_script,
    confirmation_text,
    failure_report_path,
    remove_app,
    revoke_device_key,
    spawn_cleanup_helper,
)


class Response:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_frozen_config_is_durable_and_source_contract_is_preserved(monkeypatch, tmp_path):
    local_app_data = tmp_path / "LocalAppData"
    home = tmp_path / "Home"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    if os.name == "nt":
        expected_frozen_path = local_app_data / "OverAnalyzer" / "agent.toml"
    else:
        expected_frozen_path = home / ".local" / "state" / "overanalyzer" / "agent.toml"

    assert runtime_config_path(frozen=True) == expected_frozen_path
    assert runtime_config_path(frozen=False).name == "agent.toml"
    assert runtime_config_path(frozen=False).parent.name == "agent"


def test_confirmation_copy_separates_pc_removal_from_account_data():
    copy = confirmation_text()

    assert "this PC" in copy
    assert "agent.toml" in copy and "device key" in copy
    assert "debug_out" in copy and "local cache" in copy
    assert "tray/startup registration" in copy
    assert "account stays" in copy
    lowered = copy.lower()
    assert "matches" in lowered and "screenshots" in lowered and "rank history" in lowered
    assert "Settings → Devices" in copy


def test_self_revoke_lists_opaque_id_then_deletes_it():
    calls: list[tuple[str, str, dict]] = []

    def get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        return Response(200, [{"token_id": "device/opaque-id"}])

    def delete(url, **kwargs):
        calls.append(("DELETE", url, kwargs))
        return Response(204)

    result = revoke_device_key(
        AgentConfig(api_url="https://api.example", bearer_token="device-key-example"),
        request_get=get,
        request_delete=delete,
    )

    assert result.ok
    assert calls[0][0:2] == ("GET", "https://api.example/api/me/devices")
    assert calls[1][0:2] == ("DELETE", "https://api.example/api/me/devices/device%2Fopaque-id")
    assert calls[0][2]["headers"] == {"Authorization": "Bearer device-key-example"}


def test_self_revoke_refuses_to_guess_when_multiple_keys_exist():
    result = revoke_device_key(
        AgentConfig(api_url="https://api.example", bearer_token="device-key-example"),
        request_get=lambda *_a, **_k: Response(200, [{"token_id": "a"}, {"token_id": "b"}]),
        request_delete=lambda *_a, **_k: Response(204),
    )

    assert not result.ok
    assert "Settings → Devices" in result.message


def test_revoke_failure_leaves_all_local_traces_in_place(tmp_path):
    data_dir = tmp_path / "OverAnalyzer"
    config_path = data_dir / "agent.toml"
    config_path.parent.mkdir()
    config_path.write_text("bearer_token = 'device-key-example'", encoding="utf-8")
    (data_dir / "agent.state.json").write_text("{}", encoding="utf-8")

    def fail_get(*_args, **_kwargs):
        raise OSError("offline")

    result = remove_app(
        AgentConfig(api_url="https://api.example", bearer_token="device-key-example"),
        config_path=config_path,
        data_dir=data_dir,
        frozen=False,
        request_get=fail_get,
        request_delete=lambda *_a, **_k: Response(204),
    )

    assert not result.ok
    assert config_path.exists()
    assert (data_dir / "agent.state.json").exists()


def test_remove_app_deletes_known_local_traces_but_not_unknown_siblings(tmp_path):
    data_dir = tmp_path / "OverAnalyzer"
    config_path = data_dir / "agent.toml"
    config_path.parent.mkdir()
    config_path.write_text("", encoding="utf-8")
    (data_dir / "agent.state.json").write_text("{}", encoding="utf-8")
    (data_dir / "debug_out").mkdir()
    (data_dir / "debug_out" / "capture.png").write_bytes(b"capture")
    (data_dir / "cache").mkdir()
    (data_dir / "cache" / "map.png").write_bytes(b"cache")
    unrelated = data_dir / "user-note.txt"
    unrelated.write_text("not an OverAnalyzer trace", encoding="utf-8")

    result = remove_app(
        AgentConfig(api_url="https://api.example", bearer_token="device-key-example"),
        config_path=config_path,
        data_dir=data_dir,
        frozen=False,
        request_get=lambda *_a, **_k: Response(200, [{"token_id": "id"}]),
        request_delete=lambda *_a, **_k: Response(204),
    )

    assert result.ok and result.verified and not result.scheduled
    assert not config_path.exists()
    assert not (data_dir / "agent.state.json").exists()
    assert not (data_dir / "debug_out").exists()
    assert not (data_dir / "cache").exists()
    assert unrelated.exists()


def test_frozen_removal_uses_detached_helper_and_does_not_claim_verification(tmp_path):
    data_dir = tmp_path / "OverAnalyzer"
    config_path = data_dir / "agent.toml"
    config_path.parent.mkdir()
    config_path.write_text("", encoding="utf-8")
    exe = tmp_path / "OverAnalyzer.exe"
    exe.write_bytes(b"frozen executable")
    commands = []

    def runner(command, **_kwargs):
        commands.append(command)

    result = remove_app(
        AgentConfig(api_url="https://api.example", bearer_token="device-key-example"),
        config_path=config_path,
        data_dir=data_dir,
        executable_path=exe,
        frozen=True,
        request_get=lambda *_a, **_k: Response(200, [{"token_id": "id"}]),
        request_delete=lambda *_a, **_k: Response(204),
        helper_runner=runner,
        process_id=12345,
    )

    assert result.ok and result.scheduled and not result.verified
    assert result.failure_report == failure_report_path(12345)
    assert commands and commands[0][0:5] == [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden"
    ]
    script = cleanup_helper_script(
        type("Plan", (), {"local_paths": (config_path,), "startup_paths": (), "executable_path": exe})(),
        12345,
    )
    assert "Get-Process -Id 12345" in script
    assert "Test-Path -LiteralPath" in script
    assert "OverAnalyzer removal was not verified." in script
    assert exe.exists()  # only the detached helper can delete a running EXE


def test_spawn_helper_encodes_a_hidden_command(tmp_path):
    plan = type(
        "Plan",
        (),
        {"local_paths": (tmp_path / "agent.toml",), "startup_paths": (), "executable_path": None},
    )()
    commands = []
    spawn_cleanup_helper(plan, process_id=9, runner=lambda command, **_kwargs: commands.append(command))
    assert commands[0][0] == "powershell.exe"
    assert commands[0][-2] == "-EncodedCommand"
    assert len(commands[0][-1]) > 100
