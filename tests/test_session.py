"""The stat-tile counters: daily capture count (persisted) and session record."""
import json

from overanalyzer_agent.session import SessionStats


def test_record_label_is_none_until_a_result_is_known():
    stats = SessionStats()
    assert stats.record_label() is None
    assert stats.record_hint() is None


def test_wins_and_losses_make_a_record():
    stats = SessionStats()
    for result in ("win", "win", "loss", "win"):
        stats.record_result(result)
    assert stats.record_label() == "3-1"
    assert stats.record_hint() == "75% win rate"


def test_draws_show_as_a_third_number_and_stay_out_of_the_win_rate():
    stats = SessionStats()
    for result in ("win", "loss", "draw"):
        stats.record_result(result)
    assert stats.record_label() == "1-1-1"
    assert stats.record_hint() == "50% win rate"


def test_an_unknown_result_is_not_counted_as_anything():
    """A match we couldn't read back must not be guessed into the tally."""
    stats = SessionStats()
    stats.record_result(None)
    assert stats.played == 0
    assert stats.record_label() is None


def test_uploads_count_for_the_day_and_roll_over_at_midnight(tmp_path):
    stats = SessionStats(path=tmp_path / "state.json")
    stats.record_upload("21:40", today="2026-07-30")
    stats.record_upload("21:52", today="2026-07-30")
    assert stats.captured_today == 2
    assert stats.today_hint() == "last 21:52"

    stats.record_upload("00:04", today="2026-07-31")
    assert stats.captured_today == 1


def test_the_daily_count_survives_a_restart(tmp_path):
    from datetime import date

    path = tmp_path / "state.json"
    stats = SessionStats(path=path)
    stats.record_upload("21:40")
    assert SessionStats.load(path).captured_today == 1
    assert SessionStats.load(path).last_upload_at == "21:40"
    assert json.loads(path.read_text())["day"] == date.today().isoformat()


def test_yesterdays_count_does_not_carry_into_today(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"day": "1999-01-01", "captured_today": 12}))
    assert SessionStats.load(path).captured_today == 0


def test_a_corrupt_or_missing_state_file_is_not_fatal(tmp_path):
    missing = tmp_path / "nope.json"
    assert SessionStats.load(missing).captured_today == 0
    corrupt = tmp_path / "bad.json"
    corrupt.write_text("{not json")
    assert SessionStats.load(corrupt).captured_today == 0


def test_saving_to_an_unwritable_path_is_swallowed(tmp_path):
    """A read-only install directory must not break capture."""
    stats = SessionStats(path=tmp_path / "no-such-dir" / "state.json")
    stats.record_upload("21:40")  # must not raise
    assert stats.captured_today == 1


# --- window position --------------------------------------------------------
def test_window_position_survives_a_restart(tmp_path):
    path = tmp_path / "state.json"
    SessionStats(path=path).set_window_position(240, 96)
    reloaded = SessionStats.load(path)
    assert (reloaded.window_x, reloaded.window_y) == (240, 96)


def test_window_position_is_not_reset_by_a_new_day(tmp_path):
    """Unlike captured_today, a dragged position isn't scoped to `day`."""
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"day": "1999-01-01", "window_x": 50, "window_y": 60}))
    reloaded = SessionStats.load(path)
    assert (reloaded.window_x, reloaded.window_y) == (50, 60)
    assert reloaded.captured_today == 0  # the daily count still rolls over


def test_no_saved_position_means_none():
    assert (SessionStats().window_x, SessionStats().window_y) == (None, None)
