"""The main window.

This is the task-6 skeleton: every control of the final layout is present
and positioned, but only the pieces that need no Telegram traffic are live.
Later tasks wire the chat picker (8), the scope and destination (9), the
download itself (10) and the settings dialog (11).
"""

from __future__ import annotations

import customtkinter as ctk

from ..config import Credentials
from ..metadata import detect_ffmpeg
from .bridge import TelegramBridge

PAD = 12
BANNER_TEXT = "⚠ ffmpeg not found — videos are unavailable. See README."


class ChronogramApp(ctk.CTk):
    def __init__(self, credentials: Credentials, bridge: TelegramBridge):
        super().__init__()
        self.credentials = credentials
        self.bridge = bridge

        self.title("Chronogram TG")
        # A fixed-size form: resizing adds nothing here, and this also greys
        # out the maximize button on macOS. No explicit geometry - the window
        # takes its natural compact size from the content, banner included.
        self.resizable(False, False)
        self.grid_columnconfigure(1, weight=1)

        self.ffmpeg_available = detect_ffmpeg() is not None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ── construction ────────────────────────────────────────────────

    def _build(self) -> None:
        row = 0

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=row, column=0, columnspan=3, sticky="ew", padx=PAD, pady=(PAD, 0))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Chronogram TG", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.settings_button = ctk.CTkButton(header, text="⚙", width=36, state="disabled")
        self.settings_button.grid(row=0, column=1, sticky="e")
        row += 1

        self.banner = None
        if not self.ffmpeg_available:
            self.banner = ctk.CTkLabel(
                self,
                text=BANNER_TEXT,
                fg_color=("#fff3cd", "#4d3f12"),
                text_color=("#664d03", "#ffda6a"),
                corner_radius=6,
                anchor="w",
                padx=10,
            )
            self.banner.grid(row=row, column=0, columnspan=3, sticky="ew", padx=PAD, pady=(PAD, 0))
            row += 1

        def picker_row(label: str, value: str, button_text: str):
            nonlocal row
            ctk.CTkLabel(self, text=label, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(PAD, 6), pady=(PAD, 0)
            )
            value_label = ctk.CTkLabel(self, text=value, anchor="w", text_color="gray")
            value_label.grid(row=row, column=1, sticky="ew", pady=(PAD, 0))
            button = ctk.CTkButton(self, text=button_text, width=130, state="disabled")
            button.grid(row=row, column=2, sticky="e", padx=(6, PAD), pady=(PAD, 0))
            row += 1
            return value_label, button

        self.chat_label, self.chat_button = picker_row("Chat", "No chat selected", "Choose chat…")

        ctk.CTkLabel(self, text="Scope", anchor="w").grid(
            row=row, column=0, sticky="w", padx=(PAD, 6), pady=(PAD, 0)
        )
        self.scope_value = ctk.StringVar(value="all")
        scope = ctk.CTkFrame(self, fg_color="transparent")
        scope.grid(row=row, column=1, sticky="ew", pady=(PAD, 0))
        ctk.CTkRadioButton(
            scope, text="Whole chat", variable=self.scope_value, value="all", state="disabled"
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkRadioButton(
            scope, text="Date range", variable=self.scope_value, value="range", state="disabled"
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.range_button = ctk.CTkButton(self, text="Choose dates…", width=130, state="disabled")
        self.range_button.grid(row=row, column=2, sticky="e", padx=(6, PAD), pady=(PAD, 0))
        row += 1

        self.destination_label, self.destination_button = picker_row(
            "Save to", "No folder selected", "Choose folder…"
        )

        self.videos_checkbox = ctk.CTkCheckBox(self, text="Include videos")
        if self.ffmpeg_available:
            self.videos_checkbox.select()
        else:
            self.videos_checkbox.deselect()
            self.videos_checkbox.configure(state="disabled")
        self.videos_checkbox.grid(
            row=row, column=0, columnspan=3, sticky="w", padx=PAD, pady=(PAD, 0)
        )
        row += 1

        # An elastic spacer pins everything below it to the bottom edge,
        # whether or not the ffmpeg banner row exists above.
        self.grid_rowconfigure(row, weight=1)
        row += 1

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.grid(
            row=row, column=0, columnspan=3, sticky="ew", padx=PAD, pady=(PAD * 2, 0)
        )
        row += 1
        self.progress_label = ctk.CTkLabel(self, text="Ready.", anchor="w", text_color="gray")
        self.progress_label.grid(
            row=row, column=0, columnspan=3, sticky="ew", padx=PAD, pady=(4, 0)
        )
        row += 1

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        # No sticky: the frame centres itself in its row, resize or not.
        buttons.grid(row=row, column=0, columnspan=3, padx=PAD, pady=PAD)
        self.start_button = ctk.CTkButton(buttons, text="Start", state="disabled")
        self.start_button.grid(row=0, column=0)
        self.pause_button = ctk.CTkButton(buttons, text="Pause", state="disabled")
        self.pause_button.grid(row=0, column=1, padx=(8, 0))
        self.cancel_button = ctk.CTkButton(buttons, text="Cancel", state="disabled")
        self.cancel_button.grid(row=0, column=2, padx=(8, 0))

    # ── shutdown ────────────────────────────────────────────────────

    def _close(self) -> None:
        self.destroy()


def launch(credentials: Credentials) -> None:
    """Open the main window; returns when it closes."""
    bridge = TelegramBridge()
    bridge.start()
    try:
        app = ChronogramApp(credentials, bridge)
        app.mainloop()
    finally:
        bridge.stop()
