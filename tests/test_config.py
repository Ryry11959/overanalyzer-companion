import pytest

from overanalyzer_agent.config import (
    AgentConfig,
    from_dict,
    load_config,
    save_config,
    to_dict,
)


def test_defaults():
    cfg = AgentConfig()
    # Points at the configured service out of the box - the app's Settings
    # screen doesn't ask for a server address, so the default has to be the
    # real one. Self-hosters override it here or with OA_AGENT_API_URL.
    assert cfg.api_url == "https://api.overanalyzer.app"
    assert cfg.web_url == "https://overanalyzer.app"
    # Geometry defaults to None = derive it for whatever screen this is. The
    # reference coordinates live in capture.resolve_summary_region, not here.
    assert cfg.summary_region is None
    assert cfg.leaderboard_width is None
    assert cfg.leaderboard_mode == "anchor"
    assert cfg.blue_colors == [(1, 186, 249), (1, 184, 247), (1, 184, 246)]
    assert cfg.monitor_index is None  # primary, until a multi-monitor setup pins one


def test_from_dict_merges_and_coerces():
    cfg = from_dict(
        {
            "api_url": "http://example:9000",
            "self_gamertag": "ZED",
            "summary_region": [0, 0, 10, 20],
            "blue_colors": [[1, 2, 3]],
            "unknown_key": "ignored",
        }
    )
    assert cfg.api_url == "http://example:9000"
    assert cfg.self_gamertag == "ZED"
    assert cfg.summary_region == (0, 0, 10, 20)
    assert cfg.blue_colors == [(1, 2, 3)]


def test_region_mode_requires_rectangles():
    with pytest.raises(ValueError):
        from_dict({"leaderboard_mode": "region"})


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        from_dict({"leaderboard_mode": "bogus"})


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("OA_AGENT_API_URL", "http://envhost:1234")
    monkeypatch.setenv("OA_AGENT_GAMERTAG", "ENVTAG")
    monkeypatch.setenv("OA_AGENT_TOKEN", "device-key-example")
    cfg = load_config(None)
    assert cfg.api_url == "http://envhost:1234"
    assert cfg.self_gamertag == "ENVTAG"
    assert cfg.bearer_token == "device-key-example"


def test_load_config_reads_toml(tmp_path):
    p = tmp_path / "agent.toml"
    p.write_text(
        'api_url = "http://filehost:5"\nself_gamertag = "FILE"\n', encoding="utf-8"
    )
    cfg = load_config(str(p))
    assert cfg.api_url == "http://filehost:5"
    assert cfg.self_gamertag == "FILE"


def test_to_dict_roundtrips_through_from_dict():
    cfg = AgentConfig(self_gamertag="ZED", summary_region=(1, 2, 3, 4), leaderboard_width=900)
    assert from_dict(to_dict(cfg)) == cfg


def test_to_dict_omits_none_regions():
    data = to_dict(AgentConfig())
    assert "team1_region" not in data
    assert "team2_region" not in data
    # Auto geometry is absent rather than pinned, so a saved config keeps adapting
    # to the screen instead of freezing today's resolution into the file.
    assert "summary_region" not in data
    assert "leaderboard_width" not in data


def test_to_dict_keeps_an_explicit_region():
    data = to_dict(AgentConfig(summary_region=(1, 2, 3, 4)))
    assert data["summary_region"] == [1, 2, 3, 4]  # tuple -> list


def test_save_config_then_load_roundtrips(tmp_path):
    cfg = AgentConfig(api_url="http://h:1", self_gamertag="ME", leaderboard_width=900)
    path = tmp_path / "agent.toml"
    written = save_config(cfg, path)
    assert written == path
    assert load_config(str(path)) == cfg


def test_monitor_index_roundtrips(tmp_path):
    cfg = AgentConfig(monitor_index=2)
    assert from_dict(to_dict(cfg)) == cfg
    path = tmp_path / "agent.toml"
    save_config(cfg, path)
    assert load_config(str(path)).monitor_index == 2


def test_unset_monitor_index_is_omitted_from_the_saved_file():
    assert "monitor_index" not in to_dict(AgentConfig())


def test_a_blank_url_falls_back_to_the_default():
    """The app has no URL fields, so a blank left by an older config must not
    strand you with no server and no way to fix it."""
    cfg = from_dict({"api_url": "", "web_url": "   "})
    assert cfg.api_url == AgentConfig().api_url
    assert cfg.web_url == AgentConfig().web_url


def test_a_blank_url_is_not_written_back():
    data = to_dict(AgentConfig(api_url="", web_url=""))
    assert "api_url" not in data and "web_url" not in data


def test_a_real_url_still_wins_over_the_default():
    cfg = from_dict({"api_url": "http://localhost:8000", "web_url": "http://localhost:3000"})
    assert cfg.api_url == "http://localhost:8000"
    assert cfg.web_url == "http://localhost:3000"


def test_a_blank_bearer_token_is_still_meaningful():
    """Unlike the URLs, an empty device key genuinely means "no key"."""
    assert from_dict({"bearer_token": ""}).bearer_token == ""


def test_a_pasted_bearer_token_is_trimmed_when_loaded():
    assert from_dict({"bearer_token": "\n  device-key-example  \t"}).bearer_token == "device-key-example"
