"""Presentation layer for the capture app.

Everything visual lives here so the capture/upload core (``controller.py`` and
friends, one level up) stays UI-agnostic:

- :mod:`theme` - design tokens, ported from the web app's CSS variables.
- :mod:`fonts` - registers the bundled Space Grotesk / JetBrains Mono / Rajdhani
  TTFs with Windows so Tk can use them.
- :mod:`svgpath` - a small SVG path flattener; the shared rasteriser behind both
  glyph modules below.
- :mod:`icons` - lucide glyphs, vendored as shape data and rasterised with Pillow.
- :mod:`brand` - the OverAnalyzer app icon, rasterised the same way.
- :mod:`topography` - the contour backdrop.
- :mod:`assets` - bundled role art + fetched map thumbnails.
- :mod:`layout` - the panel's screens as pure draw-op data (no Tk).
- :mod:`surface` - paints a :mod:`layout` result onto a Tk canvas; the only
  module that imports ``tkinter``.
- :mod:`toast` - the small always-on-top result popups.
- :mod:`sound` - the synthesized capture-confirm chime.

Only :mod:`surface`, :mod:`toast` and :mod:`fonts` touch Tk/Windows APIs, and
they do so lazily inside functions, so the rest of the package - including all
of :mod:`layout` - is importable and unit-testable with no display.
"""
