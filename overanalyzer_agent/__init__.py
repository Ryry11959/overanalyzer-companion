"""OverAnalyzer desktop capture agent.

A small CLI that captures the three Overwatch Game Report regions on a global
hotkey and uploads them to a running OverAnalyzer API. Reuses the proven capture
logic from ``calibrated capture geometry`` (fixed summary crop + blue/red leaderboard
anchor detection).

Submodules are import-light: the screen/hotkey libraries (``mss``, ``keyboard``)
are imported lazily so the upload/capture-geometry logic stays unit-testable on a
machine without a display.
"""

__version__ = "0.1.0"
