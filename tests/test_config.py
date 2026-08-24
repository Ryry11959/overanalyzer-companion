from overanalyzer_agent.config import AgentConfig, from_dict, load_config, save_config, to_dict


def test_defaults_point_at_the_hosted_service() -> None:
    cfg = AgentConfig()
    assert cfg.api_url == "https://api.overanalyzer.app"
    assert cfg.web_url == "https://overanalyzer.app"
    assert cfg.monitor_index is None


def test_retired_crop_and_colour_keys_are_ignored() -> None:
    cfg = from_dict(
        {
            "summary_region": [1300, 180, 1600, 800],
            "leaderboard_mode": "region",
            "blue_colors": [[1, 2, 3]],
            "color_tolerance": 24,
            "api_url": "http://example:9000",
        }
    )
    assert cfg.api_url == "http://example:9000"
    assert not hasattr(cfg, "summary_region")
    assert not hasattr(cfg, "blue_colors")


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("OA_AGENT_API_URL", "http://envhost:1234")
    monkeypatch.setenv("OA_AGENT_TOKEN", "device-key-example")
    cfg = load_config(None)
    assert cfg.api_url == "http://envhost:1234"
    assert cfg.bearer_token == "device-key-example"


def test_round_trip_keeps_only_active_settings(tmp_path) -> None:
    cfg = AgentConfig(
        api_url="http://h:1",
        self_gamertag="ME",
        monitor_index=2,
        hotkey_summary="f7",
    )
    path = tmp_path / "agent.toml"
    save_config(cfg, path)
    assert load_config(str(path)) == cfg
    assert from_dict(to_dict(cfg)) == cfg


def test_none_monitor_is_not_written() -> None:
    assert "monitor_index" not in to_dict(AgentConfig())


def test_blank_urls_fall_back_to_defaults() -> None:
    cfg = from_dict({"api_url": "", "web_url": "   "})
    assert cfg.api_url == AgentConfig().api_url
    assert cfg.web_url == AgentConfig().web_url


def test_pasted_device_key_is_trimmed() -> None:
    cfg = from_dict({"bearer_token": "\n  device-key-example  \t"})
    assert cfg.bearer_token == "device-key-example"
