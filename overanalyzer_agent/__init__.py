"""OverAnalyzer desktop capture agent.

A small companion that captures two full Overwatch Game Report frames only on an
explicit hotkey and uploads them to OverAnalyzer. The service owns crop geometry and
discards each full frame after processing.

Submodules are import-light: the screen/hotkey libraries (``mss``, ``keyboard``)
are imported lazily so capture and upload stay unit-testable without a display.
"""

__version__ = "0.2.0"
