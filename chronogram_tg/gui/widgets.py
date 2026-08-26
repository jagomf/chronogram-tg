"""Small widget refinements shared across the interface."""

from __future__ import annotations

import customtkinter as ctk

# A disabled button's body fades to this; CustomTkinter alone only dims the
# text, which leaves dead buttons looking exactly like live ones.
DISABLED_FG = ("gray78", "gray28")


class DimButton(ctk.CTkButton):
    """A CTkButton whose whole body dims while disabled, not just its text."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._enabled_fg = super().cget("fg_color")
        self._apply_dim()

    def configure(self, require_redraw=False, **kwargs):
        if "fg_color" in kwargs:
            self._enabled_fg = kwargs["fg_color"]
        super().configure(require_redraw, **kwargs)
        if "state" in kwargs or "fg_color" in kwargs:
            self._apply_dim()

    def _apply_dim(self) -> None:
        wanted = DISABLED_FG if super().cget("state") == "disabled" else self._enabled_fg
        if super().cget("fg_color") != wanted:
            super().configure(fg_color=wanted)
