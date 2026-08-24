"""The panel's pure helpers: config merging and host display.

The Tk parts of ``window`` are imported lazily, so everything here runs headless.
"""
from overanalyzer_agent.config import AgentConfig
from overanalyzer_agent.window import (
    DEFAULT_HOTKEYS, build_config, clamp_position, host_of, monitor_options, split_message,
)


def _build(cfg, **overrides):
    kwargs = dict(
        api_url="http://api.example",
        web_url="https://web.example",
        bearer_token="device-key-example",
        hotkey_summary="f11",
        hotkey_scoreboard="f12",
        hotkey_reset="f9",
    )
    kwargs.update(overrides)
    return build_config(cfg, **kwargs)


def test_build_config_applies_values():
    out = _build(AgentConfig(), api_url="  http://x:9000  ", hotkey_summary="f5")
    assert out.api_url == "http://x:9000"
    assert out.web_url == "https://web.example"
    assert out.hotkey_summary == "f5"


def test_web_url_loses_its_trailing_slash():
    assert _build(AgentConfig(), web_url="https://web.example/").web_url == "https://web.example"


def test_blank_hotkeys_fall_back_to_defaults():
    out = _build(AgentConfig(), hotkey_summary="   ", hotkey_scoreboard="", hotkey_reset="")
    assert out.hotkey_summary == DEFAULT_HOTKEYS["summary"]
    assert out.hotkey_scoreboard == DEFAULT_HOTKEYS["scoreboard"]
    assert out.hotkey_reset == DEFAULT_HOTKEYS["reset"]


def test_preserves_settings_the_form_does_not_edit():
    cfg = AgentConfig(monitor_index=2, timeout_sec=45)
    out = _build(cfg)
    assert out.monitor_index == 2
    assert out.timeout_sec == 45


def test_the_panel_never_touches_the_legacy_gamertag():
    """Identity lives on the account now; an existing agent.toml value survives."""
    out = _build(AgentConfig(self_gamertag="RYRY"))
    assert out.self_gamertag == "RYRY"


def test_device_key_round_trips_and_is_trimmed():
    out = _build(AgentConfig(), bearer_token="  device-key-example  ")
    assert out.bearer_token == "device-key-example"


def test_blank_device_key_clears_it():
    out = _build(AgentConfig(bearer_token="device-key-example"), bearer_token="")
    assert out.bearer_token == ""


def test_host_of_strips_the_scheme_and_path():
    assert host_of("https://api-x.example") == "api-x.example"
    assert host_of("http://localhost:8000/") == "localhost:8000"
    assert host_of("localhost:8000") == "localhost:8000"


# --- remembered window position -------------------------------------------
def test_a_position_that_still_fits_is_left_alone():
    assert clamp_position(400, 300, 360, 540, 1920, 1080) == (400, 300)


def test_a_position_off_a_now_smaller_screen_is_pulled_back_on():
    """Unplugging a second monitor must not strand the panel off-screen."""
    assert clamp_position(3000, 1400, 360, 540, 1920, 1080) == (1560, 540)


def test_negative_positions_are_clamped_to_the_origin():
    assert clamp_position(-50, -20, 360, 540, 1920, 1080) == (0, 0)


def test_a_window_bigger_than_the_screen_pins_to_the_origin():
    assert clamp_position(100, 100, 900, 1200, 800, 600) == (0, 0)


# --- monitor dropdown options ------------------------------------------------
def test_a_single_monitor_only_offers_primary():
    assert monitor_options([{"index": 1, "width": 1920, "height": 1080}]) == [
        ("Primary display", None)
    ]


def test_a_second_monitor_gets_its_own_labelled_entry():
    options = monitor_options([
        {"index": 1, "width": 1920, "height": 1080},
        {"index": 2, "width": 1600, "height": 900},
    ])
    assert options == [
        ("Primary display", None),
        ("Display 2 - 1600 × 900", 2),
    ]


def test_no_monitors_detected_still_offers_primary():
    """A headless box or an mss failure must not remove the only usable option."""
    assert monitor_options([]) == [("Primary display", None)]


# --- toast text ------------------------------------------------------------
def test_a_dashed_status_splits_into_title_and_detail():
    assert split_message("Uploaded - match complete") == ("Uploaded", "match complete")


def test_a_long_explanation_does_not_become_one_giant_title():
    """A full sentence used to land in the unwrapped title label, which is what
    made toasts look like they cut words off."""
    title, detail = split_message(
        "Upload rejected. Sign in to a writable account, then try again."
    )
    assert title == "Upload rejected."
    assert detail == "Sign in to a writable account, then try again."


def test_a_short_status_has_no_detail_line():
    assert split_message("Uploaded") == ("Uploaded", "")


def test_the_toast_reserves_room_for_its_icon_and_gutters():
    """Both labels wrap to this, so a long message grows the toast downwards
    rather than being clipped at the window edge."""
    from overanalyzer_agent.ui import toast

    assert 0 < toast.TEXT_WIDTH < toast.WIDTH
    assert toast.WIDTH - toast.TEXT_WIDTH >= 50  # icon, padding, hairline
