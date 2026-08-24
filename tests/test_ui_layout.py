"""The panel layout: it's pure, so the whole thing is checkable headless.

``measure`` is faked with a fixed advance width - the layout only needs *a*
metric, and a deterministic one keeps these assertions stable.
"""
from overanalyzer_agent.ui import layout as L
from overanalyzer_agent.ui import theme


def measure(text: str, font: L.Font) -> int:
    return round(len(text) * font.size * 0.55)


def build(**kwargs) -> L.Layout:
    state = L.PanelState(**kwargs)
    return L.build(state, measure)


def actions(result: L.Layout) -> set[str]:
    return {c.action for c in result.controls}


def texts(result: L.Layout) -> list[str]:
    return [op.text for op in result.ops if isinstance(op, L.Text)]


def glyphs(result: L.Layout) -> list[str]:
    return [op.name for op in result.ops if isinstance(op, L.Glyph)]


# --- main screen ----------------------------------------------------------
def test_main_screen_exposes_the_core_actions():
    assert actions(build(capturing=True)) >= {
        "toggle", "toggle_hint", "capture_summary", "capture_scoreboard",
        "settings", "quit", "toggle_log",
    }


def test_the_f9_hint_is_a_real_control_not_just_a_caption():
    """The design draws F9 as a hint; a visible key that ignores clicks reads broken."""
    hint = next(c for c in build(capturing=True).controls if c.action == "toggle_hint")
    assert hint.w > 200 and hint.h >= 16


def test_pause_and_the_f9_hint_both_toggle_capture():
    from overanalyzer_agent.config import AgentConfig
    from overanalyzer_agent.window import CapturePanel

    panel = CapturePanel(AgentConfig())
    calls = []
    panel._toggle_capture = lambda *_a: calls.append(1)
    panel.dispatch("toggle")
    panel.dispatch("toggle_hint")
    assert len(calls) == 2


def test_capturing_shows_the_host_and_a_pause_button():
    result = build(capturing=True, api_host="api.example")
    assert "Pause" in texts(result)
    assert "api.example" in texts(result)


def test_the_status_row_does_not_claim_connected_before_anything_answered():
    assert "Capture active" in texts(build(capturing=True, connected=None))
    assert "Connected" in texts(build(capturing=True, connected=True))
    assert "Offline" in texts(build(capturing=True, connected=False))


def test_paused_shows_the_amber_banner_and_a_resume_button():
    result = build(capturing=False)
    assert "Capture paused" in texts(result)
    assert "Resume" in texts(result)
    assert "hotkeys ignored" in texts(result)
    banner = next(op for op in result.ops if isinstance(op, L.Rect) and op.fill == theme.PAUSED_BG)
    assert banner.radius == theme.RADIUS


def test_an_unreachable_api_turns_the_status_dot_red_while_still_capturing():
    result = build(capturing=True, connected=False)
    dots = [op.fill for op in result.ops if isinstance(op, L.Dot)]
    assert theme.LOSS in dots


def test_hotkey_labels_come_from_state_not_from_hardcoded_keys():
    result = build(hotkeys={"summary": "F7", "scoreboard": "F8", "reset": "F6"})
    assert {"F7", "F8", "F6"} <= set(texts(result))


def test_the_pause_glyph_flips_to_play_when_paused():
    assert "pause" in glyphs(build(capturing=True))
    assert "play" in glyphs(build(capturing=False))


# --- last captured --------------------------------------------------------
def test_with_no_capture_yet_the_card_says_so():
    assert "Nothing captured yet this session." in texts(build())


def test_a_status_only_capture_renders_without_inventing_match_details():
    """When the match can't be read back we show what we know, and no more."""
    result = build(last=L.LastCapture(status="complete", at="21:42", match_id="abc"))
    assert "Match recorded" in texts(result)
    assert "complete" in texts(result)
    assert not [op for op in result.ops if isinstance(op, L.Photo) and op.key == "map_thumb"]


def test_a_detailed_capture_renders_the_map_result_and_stats():
    result = build(
        has_web_url=True,
        last=L.LastCapture(
            status="complete", at="21:42", match_id="abc", map_name="King's Row",
            result="win", role="support", duration="11m 24s", kd="3.1 K/D",
        ),
    )
    assert "King's Row" in texts(result)
    assert "11m 24s · 3.1 K/D · 21:42" in texts(result)
    assert "chevron-right" in glyphs(result)  # the win chevron
    keys = {op.key for op in result.ops if isinstance(op, L.Photo)}
    assert {"map_thumb", "role_support"} <= keys


def test_the_result_chevron_carries_the_shape_not_just_the_colour():
    for result_name, glyph in (("win", "chevron-right"), ("loss", "chevron-left"),
                               ("draw", "equal")):
        out = build(last=L.LastCapture(status="complete", map_name="Busan", result=result_name))
        assert glyph in glyphs(out)


def test_open_in_app_only_appears_when_there_is_a_web_url_and_a_match():
    with_url = build(has_web_url=True, last=L.LastCapture(match_id="abc", map_name="Busan"))
    assert "open_match" in actions(with_url)
    without = build(has_web_url=False, last=L.LastCapture(match_id="abc", map_name="Busan"))
    assert "open_match" not in actions(without)


def test_needs_review_badges_amber_and_complete_badges_green():
    review = build(last=L.LastCapture(status="needs_review"))
    assert "review" in texts(review)
    tones = {op.fill for op in review.ops if isinstance(op, L.Text)}
    assert theme.DRAW in tones


# --- stat tiles -----------------------------------------------------------
def test_empty_tiles_say_what_is_missing_rather_than_showing_a_fake_zero():
    result = build()
    assert "nothing yet" in texts(result)
    assert "no results yet" in texts(result)
    assert "-" in texts(result)


def test_tile_text_is_vertically_balanced_in_its_box():
    """The three rows are positioned by their INK, not their line boxes.

    A 24px JetBrains Mono line box is 38px tall against ~18px of digit, so
    spacing by line height leaves a top-heavy tile whose hint overflows the
    bottom edge. Ink offsets below are measured from the bundled TTFs.
    """
    from PIL import ImageFont

    from overanalyzer_agent.ui.fonts import FONT_DIR

    rows = (  # (font file, px size, y offset, worst-case string)
        ("SpaceGrotesk-Medium.ttf", theme.TEXT_2XS, L.TILE_LABEL_Y, "UPLOADS"),
        ("JetBrainsMono-Regular.ttf", theme.TEXT_2XL, L.TILE_VALUE_Y, "4-3"),
        ("SpaceGrotesk-Regular.ttf", theme.TEXT_11, L.TILE_HINT_Y, "no results yet"),
    )
    ink = []
    for filename, size, offset, text in rows:
        path = FONT_DIR / filename
        if not path.is_file():  # fonts aren't vendored on this checkout
            return
        top, bottom = ImageFont.truetype(str(path), size).getbbox(text)[1::2]
        ink.append((offset + top, offset + bottom))

    top_margin = ink[0][0] - 1  # the tile fill starts 1px in
    bottom_margin = (1 + L.TILE_HEIGHT) - ink[-1][1]
    assert abs(top_margin - bottom_margin) <= 1, f"{top_margin} above vs {bottom_margin} below"
    assert bottom_margin > 0, "the hint overflows the bottom of the tile"
    for (_, above), (below, _) in zip(ink, ink[1:]):
        assert below > above, "tile rows overlap"


def test_tiles_show_the_running_counts():
    result = build(captured_today=7, last_upload_at="21:42",
                   session_record="4-3", session_hint="57% win rate")
    assert "7" in texts(result)
    assert "last 21:42" in texts(result)
    assert "4-3" in texts(result)


# --- activity log ---------------------------------------------------------
def test_the_log_is_collapsed_by_default_and_shows_the_latest_status():
    result = build(status_message="Uploaded - match complete")
    assert "Uploaded - match complete" in texts(result)
    assert "chevron-down" in glyphs(result)


def test_opening_the_log_grows_the_panel_and_shows_recent_lines():
    closed = build(log=["one", "two"])
    opened = build(log=["one", "two"], log_open=True)
    assert opened.height > closed.height
    assert "chevron-up" in glyphs(opened)
    box = next(op for op in opened.ops if isinstance(op, L.TextBox))
    assert box.lines == ("one", "two")


def test_the_log_is_a_scrollable_textbox_not_ellipsised_lines():
    """A real Tk widget wraps and scrolls instead of us cutting lines short."""
    lines = tuple(f"line {i}" for i in range(40))
    result = build(log=list(lines), log_open=True)
    box = next(op for op in result.ops if isinstance(op, L.TextBox))
    assert box.lines == lines  # nothing trimmed - the widget scrolls to fit
    assert box.h == L.LOG_BOX_HEIGHT
    assert not [t for t in texts(result) if t.startswith("line ")]  # not drawn as Text ops


def test_an_empty_log_says_so_without_a_textbox():
    result = build(log=[], log_open=True)
    assert "No activity yet." in texts(result)
    assert not [op for op in result.ops if isinstance(op, L.TextBox)]


# --- settings screen ------------------------------------------------------
def test_settings_screen_exposes_its_controls():
    assert actions(build(screen="settings")) >= {
        "back", "self_test", "toggle_adv", "quit_button",
        "record_summary", "record_scoreboard", "record_reset",
    }


def test_settings_has_no_gamertag_field():
    """Identity moved to the account - the app must not ask for it again."""
    result = build(screen="settings", adv_open=True)
    keys = {op.key for op in result.ops if isinstance(op, L.Entry)}
    assert keys == {"bearer_token"}
    assert not any("gamertag" in t.lower() for t in texts(result))


def test_settings_does_not_ask_for_server_addresses():
    """Captures always go to the same place; only self-hosters touch the URLs,
    and they do it in agent.toml."""
    result = build(screen="settings", adv_open=True)
    keys = {op.key for op in result.ops if isinstance(op, L.Entry)}
    assert "api_url" not in keys and "web_url" not in keys
    assert not any(t in ("API URL", "WEB APP") for t in texts(result))


def test_self_test_button_cannot_run_into_the_subtitle_beside_it():
    """The button is right-aligned on the heading row; the subtitle gets trimmed
    to whatever it leaves rather than sliding underneath it."""
    result = build(screen="settings")
    button = next(c for c in result.controls if c.action == "self_test")
    subtitle = next(
        op for op in result.ops
        if isinstance(op, L.Text) and op.text.startswith("Uses a held Summary frame")
    )
    assert subtitle.x + measure(subtitle.text, subtitle.font) <= button.x


def test_device_key_field_is_masked():
    entries = {op.key: op for op in build(screen="settings", adv_open=True).ops
               if isinstance(op, L.Entry)}
    assert entries["bearer_token"].secret is True
    assert set(entries) == {"bearer_token"}


def test_pairing_link_only_appears_with_a_web_url():
    with_url = build(screen="settings", has_web_url=True)
    assert "open_pairing" in actions(with_url)
    without = build(screen="settings", has_web_url=False)
    assert "open_pairing" not in actions(without)


def test_recording_a_hotkey_prompts_in_place():
    result = build(screen="settings", recording="summary")
    assert "press a key…" in texts(result)


def test_advanced_is_collapsed_until_asked_for():
    closed = build(screen="settings")
    opened = build(screen="settings", adv_open=True)
    assert "test_capture" not in actions(closed)
    assert "test_capture" in actions(opened)
    assert opened.height > closed.height


def test_monitor_dropdown_only_appears_with_more_than_one_display():
    single = build(screen="settings", adv_open=True, monitor_options=("Primary display",))
    multi = build(screen="settings", adv_open=True,
                  monitor_options=("Primary display", "Display 2 - 1600 × 900"),
                  monitor_value="Primary display")
    assert not [op for op in single.ops if isinstance(op, L.Select)]
    select = next(op for op in multi.ops if isinstance(op, L.Select))
    assert select.key == "monitor"
    assert select.options == ("Primary display", "Display 2 - 1600 × 900")
    assert select.value == "Primary display"


def test_connection_state_is_described_honestly():
    assert "Not checked yet" in texts(build(screen="settings"))
    assert "Reachable · 42 ms" in texts(build(screen="settings", connected=True, latency_ms=42))
    unreachable = texts(build(screen="settings", connected=False))
    assert any("Unreachable" in t for t in unreachable)


# --- geometry -------------------------------------------------------------
def test_everything_stays_inside_the_panel_width():
    for state in (build(capturing=True), build(screen="settings", adv_open=True),
                  build(log_open=True, log=["x"] * 10)):
        for control in state.controls:
            assert control.x >= 0
            assert control.x + control.w <= L.WIDTH, control
        for op in state.ops:
            if isinstance(op, L.Rect):
                assert op.x + op.w <= L.WIDTH, op


def test_controls_do_not_overlap_each_other():
    result = build(capturing=True)
    boxes = [(c.x, c.y, c.x + c.w, c.y + c.h, c.action) for c in result.controls]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            overlap = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
            assert not overlap, f"{a[4]} overlaps {b[4]}"


def test_ellipsise_trims_to_fit():
    assert L._ellipsise("short", 1000, L.SANS, measure) == "short"
    trimmed = L._ellipsise("a very long api hostname indeed", 40, L.SANS, measure)
    assert trimmed.endswith("…") and len(trimmed) < len("a very long api hostname indeed")
    assert L._ellipsise("anything", 0, L.SANS, measure) == ""


# --- self test + capture debug ---------------------------------------------
STAGES = (
    ("Service and device key", "pass", "Device key accepted."),
    ("Upload", "fail", "Upload rejected. Sign in to a writable account."),
)


def test_self_test_stages_are_not_drawn_until_one_runs():
    result = build(screen="settings")
    assert not any(t.startswith("Service and device key") for t in texts(result))


def test_each_self_test_stage_gets_its_own_line_and_mark():
    result = build(screen="settings", self_test=STAGES)
    rendered = texts(result)
    assert "Service and device key" in rendered
    assert "Upload" in rendered
    assert "Upload rejected. Sign in to a writable account." in rendered
    marks = glyphs(result)
    assert "circle-check-big" in marks and "x" in marks


def test_a_failing_stage_is_marked_in_the_loss_colour():
    result = build(screen="settings", self_test=STAGES)
    failure = next(op for op in result.ops
                   if isinstance(op, L.Glyph) and op.name == "x")
    assert failure.fill == theme.LOSS


def test_stage_details_do_not_overlap_what_follows():
    """The layout is pure data but the canvas wraps for real, so a long detail
    line has to reserve its wrapped height or it paints over the next section."""
    short = build(screen="settings", self_test=(("Upload", "fail", "Nope."),))
    long_detail = "Upload rejected. " + "Sign in to a writable account. " * 6
    long = build(screen="settings", self_test=(("Upload", "fail", long_detail),))
    assert long.height > short.height


def test_the_button_says_it_is_running():
    assert "Run self test" in texts(build(screen="settings"))
    assert "Testing…" in texts(build(screen="settings", self_test_running=True))


def test_the_debug_folder_is_reachable_from_advanced():
    assert "open_debug" in actions(build(screen="settings", adv_open=True))
    assert "open_debug" not in actions(build(screen="settings", adv_open=False))


def test_an_empty_debug_folder_says_what_will_appear_there():
    result = build(screen="settings", adv_open=True, debug_count=0)
    assert any("Empty." in t for t in texts(result))


def test_the_debug_row_counts_attempts_and_promises_no_key():
    one = texts(build(screen="settings", adv_open=True, debug_count=1))
    assert any("1 recent attempt," in t for t in one)
    many = texts(build(screen="settings", adv_open=True, debug_count=4))
    assert any("4 recent attempts," in t for t in many)
    assert any("No device key, screenshot, or full frame" in t for t in many)


def test_settings_disclose_transient_hotkey_only_full_frame_capture():
    copy = " ".join(texts(build(screen="settings")))
    assert "only when you press a hotkey or button" in copy
    assert "whole game frame" in copy
    assert "uploaded for processing, then discarded" in copy
    assert "never continuous" in copy


# --- update banner ----------------------------------------------------------
def test_no_banner_when_there_is_nothing_to_update():
    assert "install_update" not in actions(build())
    assert not any("Update" in t for t in texts(build()))


def test_an_available_update_is_offered_on_the_main_screen():
    """It sits above the status row because an update nobody sees is an update
    nobody installs."""
    result = build(update_version="0.2.0")
    assert "install_update" in actions(result)
    assert any("Update 0.2.0 available" in t for t in texts(result))
    assert "Update now" in texts(result)


def test_a_mandatory_update_is_worded_differently_but_still_a_choice():
    result = build(update_version="0.2.0", update_mandatory=True)
    assert any("Important update" in t for t in texts(result))
    # Still a button the user presses: nothing installs itself.
    assert "install_update" in actions(result)


def test_an_update_in_flight_shows_progress_and_cannot_be_restarted():
    result = build(update_version="0.2.0", update_busy=True,
                   update_progress="Downloading… 42%")
    assert "Downloading… 42%" in texts(result)
    assert "install_update" not in actions(result)


def test_the_banner_does_not_push_capture_off_the_panel():
    """It adds height rather than overlapping what was already there."""
    plain = build(capturing=True)
    with_banner = build(capturing=True, update_version="0.2.0")
    assert with_banner.height > plain.height
    assert actions(with_banner) >= actions(plain)
