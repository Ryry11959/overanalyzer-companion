"""Game art for the panel: bundled role glyphs and fetched map thumbnails.

Role marks are three small PNGs vendored from the web app, so they always
render. Map art is not - there are 30-odd map images and shipping them with a
capture utility isn't worth the megabytes - so a thumbnail is fetched from the
web app on demand and cached, and simply doesn't appear when there's no
``web_url`` configured or the fetch fails.
"""
from __future__ import annotations

import io
import threading
from pathlib import Path

from PIL import Image

ROLE_DIR = Path(__file__).resolve().parents[2] / "assets" / "game" / "roles"
ROLES = ("tank", "damage", "support")


def role_icon(role: str, size: int = 12) -> Image.Image | None:
    """The official role glyph, or ``None`` if we don't have that one."""
    if role not in ROLES:
        return None
    path = ROLE_DIR / f"{role}.png"
    if not path.is_file():
        return None
    return _load_role(path, size)


_role_cache: dict[tuple[str, int], Image.Image] = {}


def _load_role(path: Path, size: int) -> Image.Image:
    key = (str(path), size)
    if key not in _role_cache:
        with Image.open(path) as image:
            _role_cache[key] = image.convert("RGBA").resize((size, size), Image.LANCZOS)
    return _role_cache[key]


def rounded(image: Image.Image, radius: int) -> Image.Image:
    """Round an image's corners - art chips use the 2px radius."""
    from PIL import ImageDraw

    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *[v - 1 for v in image.size]), radius, fill=255)
    out = image.convert("RGBA")
    out.putalpha(mask)
    return out


class MapThumbs:
    """Lazily fetches and caches map art from the web app.

    Fetches happen on a worker thread; :meth:`get` never blocks, it just returns
    ``None`` until the image has arrived and calls ``on_ready`` when it has.
    """

    def __init__(self, size: tuple[int, int] = (72, 44)) -> None:
        self.size = size
        self._cache: dict[str, Image.Image | None] = {}
        self._lock = threading.Lock()

    def get(self, url: str | None) -> Image.Image | None:
        if not url:
            return None
        with self._lock:
            return self._cache.get(url)

    def fetch(self, url: str | None, on_ready) -> None:
        """Fetch ``url`` in the background, then call ``on_ready()``."""
        if not url:
            return
        with self._lock:
            if url in self._cache:
                return
            self._cache[url] = None  # claim it so we only fetch once

        def worker() -> None:
            image = self._download(url)
            with self._lock:
                self._cache[url] = image
            if image is not None:
                on_ready()

        threading.Thread(target=worker, daemon=True).start()

    def _download(self, url: str) -> Image.Image | None:
        import requests

        try:
            resp = requests.get(url, timeout=8)
            if resp.status_code >= 400:
                return None
            with Image.open(io.BytesIO(resp.content)) as image:
                thumb = image.convert("RGB").resize(self.size, Image.LANCZOS)
            return rounded(thumb, 2)
        except Exception:  # noqa: BLE001 - art is decoration, never a failure path
            return None
