from dataclasses import dataclass

from overanalyzer_agent.app import initial_screen
from overanalyzer_agent.config import AgentConfig
from overanalyzer_agent.window import CapturePanel, probe_connection


@dataclass
class _Response:
    status_code: int


def test_first_run_opens_settings_until_a_device_key_exists():
    assert initial_screen(AgentConfig(bearer_token="")) == "settings"
    assert initial_screen(AgentConfig(bearer_token="device-key-example")) == "main"


def test_connection_without_a_key_checks_reachability_and_explains_pairing():
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(200)

    result = probe_connection(
        AgentConfig(api_url="https://api.example"), request_get=get
    )

    assert result.connected is True
    assert calls == [("https://api.example/api/health", {"timeout": 8.0})]
    assert "no device key is saved" in result.message
    assert "Sign in to the web app" in result.message


def test_connection_with_a_key_uses_the_existing_authenticated_devices_endpoint():
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(200)

    result = probe_connection(
        AgentConfig(api_url="https://api.example", bearer_token="device-key-example"),
        request_get=get,
    )

    assert result.connected is True
    assert calls[0][0] == "https://api.example/api/me/devices"
    assert calls[0][1]["headers"] == {"Authorization": "Bearer device-key-example"}
    assert "device key accepted" in result.message.lower()


def test_connection_401_identifies_an_invalid_or_revoked_key():
    result = probe_connection(
        AgentConfig(bearer_token="device-key-example"),
        request_get=lambda *args, **kwargs: _Response(401),
    )

    assert result.connected is False
    assert "invalid or revoked" in result.message
    assert "create one replacement" in result.message


def test_connection_failure_tells_the_user_to_check_the_service_and_retry():
    def get(*args, **kwargs):
        raise OSError("offline")

    result = probe_connection(AgentConfig(), request_get=get)

    assert result.connected is False
    assert "internet connection" in result.message
    assert "run the self test again" in result.message


def test_capture_does_not_start_again_after_a_failed_connection_test():
    panel = CapturePanel(AgentConfig())
    panel.state.connected = False

    assert panel.start_capture() is False
    assert panel.state.capturing is False
    assert "run the self test again" in panel.state.status_message


def test_hotkey_failure_keeps_button_capture_available_with_an_actionable_message(monkeypatch):
    panel = CapturePanel(AgentConfig())
    monkeypatch.setattr(panel.hotkeys, "register", lambda bindings: "keyboard unavailable")

    assert panel.start_capture() is True
    assert panel.state.capturing is True
    assert "use the capture buttons" in panel.state.status_message


# --- the connection indicator tracks reality, not just startup --------------
def _panel(tmp_path, monkeypatch, *, probe=None):
    """A panel with no Tk and no network. Tk is lazy, so this is safe headless."""
    from overanalyzer_agent import window as window_mod

    if probe is not None:
        monkeypatch.setattr(window_mod, "probe_connection", probe)
    # A successful upload event starts a background read of the match for the
    # "last captured" card. Stub it, or these tests reach the real service.
    monkeypatch.setattr(window_mod.matchinfo, "fetch_match", lambda *a, **kw: None)
    config = tmp_path / "agent.toml"
    config.write_text("", encoding="utf-8")
    return CapturePanel(AgentConfig(bearer_token="device-key-example"), config_path=str(config))


def test_a_completed_upload_clears_a_stale_offline_indicator(tmp_path, monkeypatch):
    """The bug this fixes: connectivity was decided once at startup and never
    revisited, so one unlucky launch left the panel reading Offline for the whole
    session while captures were uploading perfectly."""
    from overanalyzer_agent.controller import Status, StatusEvent

    panel = _panel(tmp_path, monkeypatch)
    panel.state.connected = False  # a probe failed at launch

    panel._apply_event(StatusEvent(Status.OK, "Uploaded - match complete", match_id="m1"))
    assert panel.state.connected is True


def test_a_needs_review_upload_also_proves_the_service_was_reached(tmp_path, monkeypatch):
    from overanalyzer_agent.controller import Status, StatusEvent

    panel = _panel(tmp_path, monkeypatch)
    panel.state.connected = False
    panel._apply_event(StatusEvent(Status.NEEDS_REVIEW, "Uploaded - needs review", match_id="m2"))
    assert panel.state.connected is True


def test_a_failure_re_probes_rather_than_declaring_the_service_down(tmp_path, monkeypatch):
    """Most failures are not connectivity - OCR failed, quota, a refused key -
    so a failure asks, it does not assert."""
    from overanalyzer_agent.controller import Status, StatusEvent

    probes = []
    panel = _panel(tmp_path, monkeypatch)
    monkeypatch.setattr(panel, "_check_connection", lambda **kw: probes.append(kw))
    panel.state.connected = True
    panel._apply_event(StatusEvent(Status.ERROR, "Upload received but OCR failed"))
    assert probes, "a failure should trigger a fresh check"
    assert panel.state.connected is True, "it must not assert offline on its own"


def test_a_slow_startup_probe_cannot_overwrite_a_newer_answer(tmp_path, monkeypatch):
    """These run on worker threads with an 8s timeout. A probe that started
    before a successful upload must not land afterwards and undo it."""
    from overanalyzer_agent.controller import Status, StatusEvent
    from overanalyzer_agent.window import ConnectionCheck

    from overanalyzer_agent import window as window_mod

    applied = []
    panel = _panel(
        tmp_path, monkeypatch,
        probe=lambda cfg: ConnectionCheck(False, None, "Can't reach OverAnalyzer."),
    )
    monkeypatch.setattr(panel, "_on_ui", lambda fn: applied.append(fn))

    # Run the probe's worker inline so the ordering under test is the assertion,
    # not the scheduler's timing.
    class _Inline:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None, **_kw):
            self._call = lambda: target(*args, **(kwargs or {}))

        def start(self):
            self._call()

    monkeypatch.setattr(window_mod.threading, "Thread", _Inline)

    panel._check_connection()          # a probe starts...
    panel._apply_event(               # ...and a real upload succeeds first
        StatusEvent(Status.OK, "Uploaded - match complete", match_id="m1")
    )
    assert panel.state.connected is True
    for apply in applied:              # the stale probe finally lands
        apply()
    assert panel.state.connected is True, "the stale probe overwrote a better answer"
