"""Paints a :class:`~overanalyzer_agent.ui.layout.Layout` onto a Tk canvas.

This is the only place that talks to Tk. It resolves the layout's font roles to
real families, rasterises lucide glyphs, keeps the ``PhotoImage`` references Tk
would otherwise garbage-collect, and turns the layout's :class:`Control` regions
into hover, cursor, tooltip and click behaviour.

A state change repaints the whole canvas. At this size that is a few hundred
items and costs well under a frame, and it means there is exactly one place
where state becomes pixels.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

from PIL import Image, ImageTk

from overanalyzer_agent.ui import icons, theme
from overanalyzer_agent.ui.fonts import FontSet
from overanalyzer_agent.ui.layout import (
    Control, Dot, Entry, Font, Glyph, Layout, Photo, Rect, Select, Text, TextBox,
)

PhotoProvider = Callable[[str], "Image.Image | None"]


def round_rect(canvas: tk.Canvas, x: int, y: int, w: int, h: int, r: int,
               fill: str | None, outline: str | None) -> None:
    """Tk has no rounded rectangle; compose one from bands and corner arcs."""
    x2, y2 = x + w, y + h
    if r <= 0 or w < 2 * r or h < 2 * r:
        canvas.create_rectangle(x, y, x2, y2, fill=fill or "", outline=outline or "", width=1)
        return
    corners = (
        (x + r, y + r, 90), (x2 - r, y + r, 0), (x2 - r, y2 - r, 270), (x + r, y2 - r, 180),
    )
    if fill:
        canvas.create_rectangle(x + r, y, x2 - r, y2, fill=fill, outline=fill)
        canvas.create_rectangle(x, y + r, x2, y2 - r, fill=fill, outline=fill)
        for cx, cy, start in corners:
            canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=91,
                              fill=fill, outline=fill, style=tk.PIESLICE)
    if outline:
        for cx, cy, start in corners:
            canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=90,
                              outline=outline, style=tk.ARC, width=1)
        canvas.create_line(x + r, y, x2 - r, y, fill=outline)
        canvas.create_line(x + r, y2, x2 - r, y2, fill=outline)
        canvas.create_line(x, y + r, x, y2 - r, fill=outline)
        canvas.create_line(x2, y + r, x2, y2 - r, fill=outline)


class Surface:
    """A canvas that knows how to draw layouts and route pointer events."""

    def __init__(self, master, fonts: FontSet, *, width: int, photos: PhotoProvider,
                 on_action: Callable[[str], None],
                 on_hover: Callable[[str | None], None],
                 on_change: Callable[[str, str], None] | None = None) -> None:
        self.fonts = fonts
        self.photos = photos
        self.on_action = on_action
        self.on_hover = on_hover
        self.on_change = on_change or (lambda _key, _value: None)
        self.canvas = tk.Canvas(
            master, width=width, height=100, bg=theme.PAGE, highlightthickness=0, bd=0,
        )
        self._fonts: dict[tuple, tkfont.Font] = {}
        self._images: list[ImageTk.PhotoImage] = []  # keep refs alive
        self._entries: dict[str, tk.Entry] = {}
        self._textboxes: dict[str, tuple[tk.Frame, tk.Text]] = {}
        self._selects: dict[str, tuple[tk.OptionMenu, "tk.StringVar"]] = {}
        self._controls: list[Control] = []
        self._hover: str | None = None
        self._tip: tk.Toplevel | None = None
        self._tip_after: str | None = None

        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        self.canvas.bind("<Button-1>", self._on_click)

    # --- fonts ------------------------------------------------------------
    def font(self, spec: Font) -> tkfont.Font:
        key = (spec.role, spec.size, spec.bold)
        if key not in self._fonts:
            family = {
                "sans": self.fonts.sans,
                "medium": self.fonts.sans_medium,
                "mono": self.fonts.mono,
                "brand": self.fonts.brand,
            }[spec.role]
            self._fonts[key] = tkfont.Font(
                family=family,
                size=-spec.size,  # negative = pixels, so the CSS scale carries over
                weight="bold" if spec.bold else "normal",
            )
        return self._fonts[key]

    def measure(self, text: str, spec: Font) -> int:
        return self.font(spec).measure(text)

    # --- entries ----------------------------------------------------------
    def entry(self, key: str, secret: bool = False) -> tk.Entry:
        """The embedded Tk entry for ``key``, created on first use.

        Entries are reused across repaints rather than rebuilt, so typing, the
        caret and the selection survive a state change.
        """
        if key not in self._entries:
            widget = tk.Entry(
                self.canvas,
                bg=theme.INPUT_BG, fg=theme.TEXT, insertbackground=theme.PRIMARY,
                relief="flat", borderwidth=0, highlightthickness=1,
                highlightbackground=theme.BORDER, highlightcolor=theme.RING,
                font=self.font(Font("mono", theme.TEXT_XS)),
                show="•" if secret else "",
            )
            self._entries[key] = widget
        return self._entries[key]

    # --- log / text boxes --------------------------------------------------
    def textbox(self, key: str) -> tuple[tk.Frame, tk.Text]:
        """The embedded (frame, text) pair for ``key``, created on first use.

        A plain ``tk.Text`` can't scroll itself, so it's paired with a
        ``Scrollbar`` inside a frame; the frame is what gets embedded on the
        canvas. Reused across repaints like :meth:`entry`, so the scroll
        position survives a state change that doesn't touch the log.
        """
        if key not in self._textboxes:
            frame = tk.Frame(self.canvas, bg=theme.SIDEBAR, highlightthickness=1,
                             highlightbackground=theme.BORDER)
            text = tk.Text(
                frame, bg=theme.SIDEBAR, fg=theme.TEXT_MUTED, relief="flat",
                borderwidth=0, wrap="word", highlightthickness=0,
                padx=12, pady=8, cursor="arrow", state="disabled",
                font=self.font(Font("mono", theme.TEXT_11)),
            )
            scrollbar = tk.Scrollbar(
                frame, orient="vertical", command=text.yview, width=10,
                troughcolor=theme.SIDEBAR, bg=theme.BORDER, activebackground=theme.TEXT_MUTED,
                highlightthickness=0, bd=0, elementborderwidth=0,
            )
            text.configure(yscrollcommand=scrollbar.set)
            text.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            self._textboxes[key] = (frame, text)
        return self._textboxes[key]

    def _sync_textbox(self, text: tk.Text, lines: tuple[str, ...]) -> None:
        content = "\n".join(lines)
        if text.get("1.0", "end-1c") == content:
            return
        at_bottom = text.yview()[1] >= 0.999
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", content)
        text.configure(state="disabled")
        if at_bottom:
            text.see("end")

    # --- dropdowns ----------------------------------------------------------
    def select(self, key: str, options: tuple[str, ...],
              on_change: Callable[[str, str], None]) -> tuple[tk.OptionMenu, "tk.StringVar"]:
        """The embedded (menu, var) pair for ``key``, created on first use."""
        if key not in self._selects:
            var = tk.StringVar()
            menu = tk.OptionMenu(self.canvas, var, "")
            menu.configure(
                bg=theme.INPUT_BG, fg=theme.TEXT, activebackground=theme.ACCENT,
                activeforeground=theme.TEXT, relief="flat", borderwidth=0,
                highlightthickness=1, highlightbackground=theme.BORDER,
                font=self.font(Font("sans", theme.TEXT_XS)), anchor="w", padx=10,
            )
            menu["menu"].configure(bg=theme.CARD, fg=theme.TEXT, activebackground=theme.ACCENT,
                                   activeforeground=theme.TEXT, borderwidth=0)
            var.trace_add("write", lambda *_a: on_change(key, var.get()))
            self._selects[key] = (menu, var)
        return self._selects[key]

    def _sync_select(self, key: str, options: tuple[str, ...], value: str,
                     on_change: Callable[[str, str], None]) -> tk.OptionMenu:
        menu, var = self.select(key, options, on_change)
        menu_widget = menu["menu"]
        current = [menu_widget.entrycget(i, "label") for i in range(menu_widget.index("end") + 1)] \
            if menu_widget.index("end") is not None else []
        if list(options) != current:
            menu_widget.delete(0, "end")
            for opt in options:
                menu_widget.add_command(label=opt, command=lambda o=opt: var.set(o))
        if var.get() != value:
            var.set(value)
        return menu

    # --- painting ---------------------------------------------------------
    def paint(self, layout: Layout) -> None:
        # delete("all") also unmaps any embedded entry widgets, so a screen
        # change can't leave a stray input floating over the new layout.
        self.canvas.delete("all")
        self.canvas.configure(height=layout.height)
        self._images.clear()
        self._controls = layout.controls

        for op in layout.ops:
            if isinstance(op, Rect):
                round_rect(self.canvas, op.x, op.y, op.w, op.h, op.radius, op.fill, op.outline)
            elif isinstance(op, Dot):
                self.canvas.create_oval(
                    op.x - op.r, op.y - op.r, op.x + op.r, op.y + op.r,
                    fill=op.fill, outline=op.fill,
                )
            elif isinstance(op, Text):
                self.canvas.create_text(
                    op.x, op.y, text=op.text, font=self.font(op.font), fill=op.fill,
                    anchor=_anchor(op.anchor), width=op.wrap or 0,
                )
            elif isinstance(op, Glyph):
                self._draw_image(icons.icon(op.name, op.size, op.fill), op.x, op.y, op.anchor)
            elif isinstance(op, Photo):
                image = self.photos(op.key)
                if image is not None:
                    self._draw_image(image, op.x, op.y, op.anchor)
            elif isinstance(op, Entry):
                widget = self.entry(op.key, op.secret)
                self.canvas.create_window(
                    op.x, op.y, window=widget, anchor="nw", width=op.w, height=op.h,
                )
            elif isinstance(op, TextBox):
                frame, text = self.textbox(op.key)
                self._sync_textbox(text, op.lines)
                self.canvas.create_window(
                    op.x, op.y, window=frame, anchor="nw", width=op.w, height=op.h,
                )
            elif isinstance(op, Select):
                menu = self._sync_select(op.key, op.options, op.value, self.on_change)
                self.canvas.create_window(
                    op.x, op.y, window=menu, anchor="nw", width=op.w, height=op.h,
                )

    def _draw_image(self, image: Image.Image, x: int, y: int, anchor: str) -> None:
        photo = ImageTk.PhotoImage(image)
        self._images.append(photo)
        self.canvas.create_image(x, y, image=photo, anchor=_anchor(anchor))

    # --- pointer ----------------------------------------------------------
    def control_at(self, x: int, y: int) -> Control | None:
        for control in reversed(self._controls):
            if control.x <= x < control.x + control.w and control.y <= y < control.y + control.h:
                return control
        return None

    def _on_motion(self, event) -> None:
        control = self.control_at(event.x, event.y)
        self._set_hover(control.action if control else None, control)

    def _set_hover(self, action: str | None, control: Control | None = None) -> None:
        if action == self._hover:
            return
        self._hover = action
        self.canvas.configure(cursor="hand2" if action else "")
        self._hide_tip()
        if control is not None and control.tooltip:
            self._tip_after = self.canvas.after(600, lambda: self._show_tip(control))
        self.on_hover(action)

    def _on_click(self, event) -> None:
        control = self.control_at(event.x, event.y)
        if control is not None:
            self._hide_tip()
            self.on_action(control.action)

    # --- tooltip ----------------------------------------------------------
    def _show_tip(self, control: Control) -> None:
        if self._hover != control.action or not control.tooltip:
            return
        tip = tk.Toplevel(self.canvas)
        tip.wm_overrideredirect(True)
        tip.configure(bg=theme.BORDER)
        label = tk.Label(
            tip, text=control.tooltip, bg=theme.CARD, fg=theme.TEXT_MUTED,
            font=self.font(Font("sans", theme.TEXT_11)), padx=8, pady=4, bd=0,
        )
        label.pack(padx=1, pady=1)
        x = self.canvas.winfo_rootx() + control.x
        y = self.canvas.winfo_rooty() + control.y + control.h + 6
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide_tip(self) -> None:
        if self._tip_after is not None:
            self.canvas.after_cancel(self._tip_after)
            self._tip_after = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def _anchor(value: str) -> str:
    return {"nw": "nw", "ne": "ne", "w": "w", "e": "e", "center": "center"}[value]
