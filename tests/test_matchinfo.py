"""Reading a match back after upload - the "try the API, degrade gracefully" path."""
from overanalyzer_agent import matchinfo

DETAIL = {
    "match_id": "abc123",
    "status": "complete",
    "map_name": "King's Row",
    "result": "win",
    "duration_sec": 684,
    "players": [
        {"is_self": False, "role": "tank", "elims": 20, "deaths": 5},
        {"is_self": True, "role": "support", "elims": 19, "deaths": 6},
    ],
}


def test_parse_match_pulls_the_self_row():
    facts = matchinfo.parse_match(DETAIL)
    assert facts.map_name == "King's Row"
    assert facts.result == "win" and facts.won
    assert facts.role == "support"
    assert facts.duration == "11m 24s"
    assert facts.kd == "3.2 K/D"


def test_parse_match_survives_a_match_with_no_players_yet():
    facts = matchinfo.parse_match({"match_id": "x", "status": "processing"})
    assert facts.status == "processing"
    assert facts.role is None and facts.kd is None and facts.map_name is None


def test_parse_match_needs_an_id():
    assert matchinfo.parse_match({"status": "complete"}) is None


def test_zero_deaths_does_not_divide_by_zero():
    body = dict(DETAIL, players=[{"is_self": True, "elims": 12, "deaths": 0}])
    assert matchinfo.parse_match(body).kd == "12.0 K/D"


def test_duration_formatting():
    assert matchinfo.format_duration(684) == "11m 24s"
    assert matchinfo.format_duration(60) == "1m 00s"
    assert matchinfo.format_duration(0) is None
    assert matchinfo.format_duration(None) is None


def test_slugify_matches_the_web_apps_asset_names():
    assert matchinfo.slugify("King's Row") == "king-s-row"
    assert matchinfo.slugify("Busan") == "busan"
    assert matchinfo.slugify("New Queen Street") == "new-queen-street"


def test_urls_are_only_built_when_a_web_url_is_configured():
    assert matchinfo.map_thumb_url("", "Busan") is None
    assert matchinfo.match_url("", "abc") is None
    assert matchinfo.map_thumb_url("https://web.example/", "Busan") == (
        "https://web.example/game/maps/busan.jpg"
    )
    assert matchinfo.match_url("https://web.example", "abc") == "https://web.example/matches/abc"


def test_fetch_match_returns_none_when_the_server_cannot_be_reached(monkeypatch):
    """A decorative card must never take the capture path down with it."""
    import requests

    def boom(*_a, **_k):
        raise requests.RequestException("nope")

    monkeypatch.setattr(requests, "get", boom)
    assert matchinfo.fetch_match("http://localhost:1", "abc") is None


def test_fetch_match_returns_none_on_an_error_status(monkeypatch):
    import requests

    class Resp:
        status_code = 403

        def json(self):  # pragma: no cover - must not be reached
            raise AssertionError("should not parse an error body")

    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp())
    assert matchinfo.fetch_match("http://x", "abc") is None


def test_fetch_match_parses_a_good_response(monkeypatch):
    import requests

    class Resp:
        status_code = 200

        def json(self):
            return DETAIL

    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp())
    facts = matchinfo.fetch_match("http://x", "abc123", bearer_token="device-key-example")
    assert facts is not None and facts.map_name == "King's Row"
