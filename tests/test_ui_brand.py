"""The rasterised app icon."""
from PIL import Image

from overanalyzer_agent.ui import brand


def test_renders_at_the_requested_size():
    for size in (16, 32, 64, 256):
        image = brand.render(size)
        assert isinstance(image, Image.Image)
        assert image.size == (size, size)


def test_the_mark_fills_the_frame():
    """Cropped to the artwork, not the SVG's padded viewBox - it should read at 16px."""
    image = brand.render(64)
    left, top, right, bottom = image.getbbox()
    covered = (right - left) * (bottom - top) / (64 * 64)
    assert covered > 0.5


def test_uses_both_brand_colours():
    pixels = {p[:3] for p in brand.render(64).getdata() if p[3] > 200}
    assert (0xFE, 0x7B, 0x2A) in pixels or any(abs(p[0] - 0xFE) < 4 for p in pixels)
    assert any(p[2] > p[0] for p in pixels)  # the dark navy mark is blue-dominant


def test_icon_is_cached():
    assert brand.icon(64) is brand.icon(64)


def test_render_is_not_cached_and_returns_a_fresh_image():
    """Callers that mutate the result (the tray badge) must not corrupt the cache."""
    assert brand.render(64) is not brand.render(64)
