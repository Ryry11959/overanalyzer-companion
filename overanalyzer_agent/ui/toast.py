"""In-app toasts, styled like the design's popover cards.

The panel usually sits behind a fullscreen game, so the result of a capture has
to be able to reach you without it. These are small always-on-top windows in the
bottom-right corner: a 2px accent edge in the status colour, a lucide glyph, a
title and one line of detail - the same three tones the design shows (uploaded /
needs review / error).

**A toast must never take focus.** Showing a top-level window is an activation
event on Windows, and activating anything while Overwatch is running borderless
tabs the player out of their game - which is exactly when a toast fires. Two
independent defences, because losing the game window is worse than losing the
toast:

1. The window is built **once, at startup**, and reused. Nothing is created
   while a game is running, so the create-and-map activation cannot happen mid
   match.
2. It carries ``WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW``, so Windows will not make
   it the foreground window when it is shown or clicked, and it stays out of
   Alt-Tab.

Neither defence exists off Windows, where the platform does not steal focus for
an override-redirect window in the first place.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont

from PIL import ImageTk

from overanalyzer_agent.ui import icons, theme
from overanalyzer_agent.ui.fonts import FontSet

WIDTH = 340
MARGIN = 24
DURATION_MS = 5000
# What a text label actually gets: the window minus its hairline, the icon and
# its padding, and the trailing gutter. Both labels wrap to this, so nothing is
# ever cut off - the toast grows downwards instead.
TEXT_WIDTH = WIDTH - 2 - 38 - 12


# Win32 constants, spelled out so the intent survives without a winuser.h to hand.
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SW_SHOWNOACTIVATE = 4

# tone -> (accent colour, lucide glyph)
TONES = {
    "ok": (theme.WIN, "circle-check-big"),
    "review": (theme.DRAW, "triangle-alert"),
    "error": (theme.LOSS, "wifi-off"),
    "busy": (theme.TEXT_MUTED, "loader-circle"),
}


def noactivate_exstyle(current: int) -> int:
    """The extended style a toast needs, given whatever the window already has.

    Split out from the Tk call so the bit maths is testable without a display.
    """
    return current | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW


def _apply_noactivate(window: tk.Misc) -> None:
    """Mark a realized Tk window as never-activate. A no-op off Windows.

    Failure here is deliberately silent: a toast that cannot be made passive is
    still better than an app that dies on an unexpected windowing environment.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # Tk wraps a toplevel in a container window, and the extended styles
        # belong to the wrapper. Fall back to the widget's own handle when there
        # is no parent (override-redirect windows on some Tk builds).
        child = window.winfo_id()
        hwnd = user32.GetParent(child) or child
        get_style, set_style = user32.GetWindowLongW, user32.SetWindowLongW
        if hasattr(user32, "GetWindowLongPtrW"):  # 64-bit safe where available
            get_style, set_style = user32.GetWindowLongPtrW, user32.SetWindowLongPtrW
        set_style(hwnd, GWL_EXSTYLE, noactivate_exstyle(get_style(hwnd, GWL_EXSTYLE)))
    except Exception:  # noqa: BLE001 - a passive toast is a nicety, not a feature
        pass


def _show_without_activating(window: tk.Misc) -> None:
    """Belt and braces over ``deiconify``: show, explicitly without activation."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        child = window.winfo_id()
        user32.ShowWindow(user32.GetParent(child) or child, SW_SHOWNOACTIVATE)
    except Exception:  # noqa: BLE001
        pass


class Toaster:
    """Shows one toast at a time, replacing whatever is on screen.

    The window is created eagerly and merely re-dressed on each ``show``, so a
    capture never constructs a window while the game has focus.
    """

    def __init__(self, master: tk.Misc, fonts: FontSet) -> None:
        self.master = master
        self.fonts = fonts
        self._window: tk.Toplevel | None = None
        self._after: str | None = None
        self._image: ImageTk.PhotoImage | None = None
        self._edge: tk.Frame | None = None
        self._icon: tk.Label | None = None
        self._title: tk.Label | None = None
        self._detail: tk.Label | None = None
        self._build()

    def _build(self) -> None:
        """Create the one reusable toast window, hidden, at startup."""
        try:
            window = tk.Toplevel(self.master)
            window.wm_overrideredirect(True)
            window.attributes("-topmost", True)
            window.configure(bg=theme.BORDER)
            window.withdraw()

            # 1px hairline via the outer bg, plus the 2px accent edge on the left.
            self._edge = tk.Frame(window, bg=theme.TEXT_MUTED, width=2)
            self._edge.pack(side="left", fill="y", padx=(1, 0), pady=1)
            body = tk.Frame(window, bg=theme.CARD)
            body.pack(side="left", fill="both", expand=True, padx=(0, 1), pady=1)

            self._icon = tk.Label(body, bg=theme.CARD)
            self._icon.pack(side="left", padx=(12, 10), pady=10)
            text = tk.Frame(body, bg=theme.CARD)
            text.pack(side="left", fill="x", expand=True, pady=10, padx=(0, 12))
            self._title = tk.Label(
                text, bg=theme.CARD, fg=theme.TEXT, anchor="w", justify="left",
                # Wrapped, not clipped. The title is often a whole sentence from
                # the status stream, and an unwrapped label in a fixed-width
                # window simply cuts the end of it off.
                wraplength=TEXT_WIDTH,
                font=tkfont.Font(family=self.fonts.sans, size=-13),
            )
            self._title.pack(fill="x")
            self._detail = tk.Label(
                text, bg=theme.CARD, fg=theme.TEXT_MUTED, anchor="w",
                justify="left", wraplength=TEXT_WIDTH,
                font=tkfont.Font(family=self.fonts.sans, size=-11),
            )
            window.bind("<Button-1>", lambda _e: self.hide())

            # The handle only exists once Tk has realized the window, and the
            # style has to be set before it is ever shown.
            window.update_idletasks()
            _apply_noactivate(window)
            self._window = window
        except tk.TclError:  # noqa: PERF203 - no display: the app runs without toasts
            self._window = None

    def show(self, tone: str, title: str, detail: str = "") -> None:
        window = self._window
        if window is None:
            return
        self._cancel()
        accent, glyph = TONES.get(tone, TONES["busy"])

        self._image = ImageTk.PhotoImage(icons.icon(glyph, 16, accent))
        if self._edge is not None:
            self._edge.configure(bg=accent)
        if self._icon is not None:
            self._icon.configure(image=self._image)
        if self._title is not None:
            self._title.configure(text=title)
        if self._detail is not None:
            self._detail.configure(text=detail)
            if detail:
                self._detail.pack(fill="x")
            else:
                self._detail.pack_forget()

        window.update_idletasks()
        height = window.winfo_reqheight()
        x = window.winfo_screenwidth() - WIDTH - MARGIN
        y = window.winfo_screenheight() - height - MARGIN - 48
        window.wm_geometry(f"{WIDTH}x{height}+{x}+{y}")
        window.deiconify()
        _show_without_activating(window)
        window.attributes("-topmost", True)

        self._after = self.master.after(DURATION_MS, self.hide)

    def _cancel(self) -> None:
        if self._after is not None:
            try:
                self.master.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def hide(self) -> None:
        """Hide the toast. The window itself is kept for the next one."""
        self._cancel()
        if self._window is not None:
            try:
                self._window.withdraw()
            except tk.TclError:
                self._window = None

    def destroy(self) -> None:
        """Tear the reusable window down - only on the way out of the app."""
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None
