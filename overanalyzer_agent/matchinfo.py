"""Read a just-uploaded match back from the API, for the "Last captured" card.

The capture flow only learns a ``match_id`` and an OCR status. That is enough to
say *something* truthful, but the panel's last-captured card wants the map, the
result, your role and your K/D - so after an upload settles this fetches
``GET /api/matches/{id}`` once and fills in what it can.

Everything here degrades to ``None``: an older server, no network, a read-only
account or a match that never finished OCR all just leave the card showing the
status it already knew. Nothing in the capture path depends on this succeeding.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MATCH_PATH = "/api/matches/{match_id}"


@dataclass(frozen=True)
class MatchFacts:
    """The handful of fields the panel renders."""

    match_id: str
    status: str
    map_name: str | None = None
    result: str | None = None  # win / loss / draw
    role: str | None = None  # tank / damage / support
    duration: str | None = None  # "11m 24s"
    kd: str | None = None  # "3.1 K/D"

    @property
    def won(self) -> bool:
        return self.result == "win"


def slugify(name: str) -> str:
    """Mirrors the web app's ``lib/game-assets.ts`` slug, so art URLs line up."""
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", name.lower()))


def format_duration(seconds: int | None) -> str | None:
    """``684`` -> ``"11m 24s"`` - the product's own duration format."""
    if not seconds or seconds < 0:
        return None
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m {rest:02d}s"


def parse_match(body: dict) -> MatchFacts | None:
    """Turn a ``MatchDetail`` payload into :class:`MatchFacts`."""
    match_id = body.get("match_id")
    if not match_id:
        return None
    me = next((p for p in body.get("players") or [] if p.get("is_self")), None)
    kd = None
    if me is not None:
        elims, deaths = me.get("elims"), me.get("deaths")
        if elims is not None and deaths is not None:
            kd = f"{elims / max(int(deaths), 1):.1f} K/D"
    return MatchFacts(
        match_id=str(match_id),
        status=str(body.get("status") or "processing"),
        map_name=body.get("map_name"),
        result=body.get("result"),
        role=(me or {}).get("role"),
        duration=format_duration(body.get("duration_sec")),
        kd=kd,
    )


def fetch_match(api_url: str, match_id: str, *, bearer_token: str | None = None,
                timeout: float = 10.0) -> MatchFacts | None:
    """Fetch one match. Returns ``None`` on any failure - this is best-effort."""
    import requests

    url = api_url.rstrip("/") + MATCH_PATH.format(match_id=match_id)
    headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            return None
        return parse_match(resp.json())
    except Exception:  # noqa: BLE001 - a decorative card must never break capture
        return None


def map_thumb_url(web_url: str, map_name: str) -> str | None:
    """Where the web app serves this map's art (``.jpg`` first, then ``.png``)."""
    if not web_url or not map_name:
        return None
    return f"{web_url.rstrip('/')}/game/maps/{slugify(map_name)}.jpg"


def match_url(web_url: str, match_id: str) -> str | None:
    if not web_url or not match_id:
        return None
    return f"{web_url.rstrip('/')}/matches/{match_id}"
