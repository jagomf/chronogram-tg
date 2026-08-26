"""The main window.

Every control of the final layout is present and positioned; they come to
life one task at a time. Wired so far: session startup and login (task 7)
and the chat picker (task 8). Still placeholders: scope and destination
(task 9), the download itself (task 10) and the settings dialog (task 11).
"""

from __future__ import annotations

from pathlib import Path
from tkinter import PhotoImage, messagebox

import customtkinter as ctk

from ..config import Credentials
from ..metadata import detect_ffmpeg
from ..tg import Chat, TelegramSession
from .bridge import TelegramBridge, poll_future
from .chat_picker import FALLBACK_EMOJI, KIND_EMOJI, ChatPicker, ellipsise
from .login import LoginWindow
from .placement import centre_on_screen

PAD = 12
BANNER_TEXT = "⚠ ffmpeg not found — videos are unavailable. See README."
ICON_FILE = Path(__file__).resolve().parent.parent / "assets" / "icon.png"

# Field styling: a placeholder reads dimmer than a chosen value, and a
# barely-there underline ties the left label to its right-hand button.
VALUE_COLOR = ("gray10", "gray90")
PLACEHOLDER_COLOR = ("gray60", "gray45")
UNDERLINE_COLOR = ("gray75", "gray30")


class ChronogramApp(ctk.CTk):
    def __init__(
        self,
        credentials: Credentials,
        bridge: TelegramBridge | None,
        session: TelegramSession | None = None,
    ):
        super().__init__()
        self.credentials = credentials
        self.bridge = bridge
        self.session = session
        self.selected_chat: Chat | None = None
        self.selected_destination = None  # a Path once task 9 wires it

        self.title("Chronogram TG")
        self._set_icon()
        # A fixed-size form: resizing adds nothing here, and this also greys
        # out the maximize button on macOS. No explicit geometry - the window
        # takes its natural compact size from the content, banner included.
        self.resizable(False, False)
        self.grid_columnconfigure(1, weight=1)

        self.ffmpeg_available = detect_ffmpeg() is not None
        self._build()
        centre_on_screen(self)
        self.protocol("WM_DELETE_WINDOW", self._close)

        if self.bridge is not None and self.session is not None:
            # Stay hidden until we know whether a login is needed; the login
            # window, when required, appears on its own (task 7).
            self.withdraw()
            self.after(0, self._connect_session)

    # ── construction ────────────────────────────────────────────────

    def _set_icon(self) -> None:
        """Show the app icon in the Dock/taskbar.

        `iconphoto(True, ...)` applies to this window and every later
        toplevel (the login included); on macOS it is also what the Dock
        shows. The reference is kept on self because Tk drops images that
        get garbage-collected. A missing or corrupt icon is cosmetic - it
        must never stop the app.
        """
        try:
            self._icon = PhotoImage(file=ICON_FILE)
            self.iconphoto(True, self._icon)
        except Exception:
            self._icon = None

    def _build(self) -> None:
        row = 0

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=row, column=0, columnspan=3, sticky="ew", padx=PAD, pady=(PAD, 0))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Chronogram TG", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.settings_button = ctk.CTkButton(
            header, text="⚙️", width=40, font=ctk.CTkFont(size=20), state="disabled"
        )
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

        def picker_row(label: str, placeholder: str, button_text: str):
            nonlocal row
            # Tk has no label-for-control concept, so the HTML behaviour is
            # wired by hand: clicking the label focuses its button.
            label_widget = ctk.CTkLabel(self, text=label, anchor="w", cursor="hand2")
            label_widget.grid(row=row, column=0, sticky="w", padx=(PAD, 6), pady=(PAD, 0))
            field = ctk.CTkFrame(self, fg_color="transparent")
            field.grid(row=row, column=1, sticky="ew", pady=(PAD, 0))
            field.grid_columnconfigure(0, weight=1)
            value_label = ctk.CTkLabel(
                field, text=placeholder, anchor="w", text_color=PLACEHOLDER_COLOR
            )
            value_label.grid(row=0, column=0, sticky="ew")
            ctk.CTkFrame(field, height=1, corner_radius=0, fg_color=UNDERLINE_COLOR).grid(
                row=1, column=0, sticky="ew"
            )
            button = ctk.CTkButton(self, text=button_text, width=130, state="disabled")
            button.grid(row=row, column=2, sticky="e", padx=(6, PAD), pady=(PAD, 0))
            label_widget.bind("<Button-1>", lambda _event, target=button: target.focus_set())
            row += 1
            return value_label, button

        self.chat_label, self.chat_button = picker_row(
            "💬 Chat", "No chat selected", "Choose chat…"
        )

        scope_label = ctk.CTkLabel(self, text="📅 Scope", anchor="w", cursor="hand2")
        scope_label.grid(row=row, column=0, sticky="w", padx=(PAD, 6), pady=(PAD, 0))
        self.scope_value = ctk.StringVar(value="all")
        scope = ctk.CTkFrame(self, fg_color="transparent")
        scope.grid(row=row, column=1, sticky="ew", pady=(PAD, 0))
        whole_chat_radio = ctk.CTkRadioButton(
            scope, text="Whole chat", variable=self.scope_value, value="all", state="disabled"
        )
        whole_chat_radio.grid(row=0, column=0, sticky="w")
        scope_label.bind("<Button-1>", lambda _event: whole_chat_radio.focus_set())
        ctk.CTkRadioButton(
            scope, text="Date range", variable=self.scope_value, value="range", state="disabled"
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.range_button = ctk.CTkButton(self, text="Choose dates…", width=130, state="disabled")
        self.range_button.grid(row=row, column=2, sticky="e", padx=(6, PAD), pady=(PAD, 0))
        row += 1

        self.destination_label, self.destination_button = picker_row(
            "📁 Save to", "No folder selected", "Choose folder…"
        )

        self.videos_checkbox = ctk.CTkCheckBox(self, text="Include videos 🎬")
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

        # The bar lives inside a fixed-height holder so that showing and
        # hiding it never changes the window's natural size. It stays hidden
        # while no transfer is running (visible during pause, hidden again
        # on cancel or completion) - task 10 drives that.
        bar_holder = ctk.CTkFrame(self, fg_color="transparent", height=10)
        bar_holder.grid(row=row, column=0, columnspan=3, sticky="ew", padx=PAD, pady=(PAD * 2, 0))
        bar_holder.grid_propagate(False)
        self.progress_bar = ctk.CTkProgressBar(bar_holder, height=10)
        self.progress_bar.set(0)
        row += 1
        self.progress_label = ctk.CTkLabel(self, text="Ready.", anchor="w", text_color="gray")
        self.progress_label.grid(
            row=row, column=0, columnspan=3, sticky="ew", padx=PAD, pady=(4, 0)
        )
        row += 1

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        # No sticky: the frame centres itself in its row, resize or not.
        buttons.grid(row=row, column=0, columnspan=3, padx=PAD, pady=PAD)
        self.start_button = ctk.CTkButton(buttons, text="▶️ Start", state="disabled")
        self.start_button.grid(row=0, column=0)
        self.pause_button = ctk.CTkButton(buttons, text="⏸️ Pause", state="disabled")
        self.pause_button.grid(row=0, column=1, padx=(8, 0))
        self.cancel_button = ctk.CTkButton(buttons, text="⏹️ Cancel", state="disabled")
        self.cancel_button.grid(row=0, column=2, padx=(8, 0))

    # ── session startup (task 7) ────────────────────────────────────

    def _connect_session(self) -> None:
        poll_future(
            self,
            self.bridge.submit(self.session.connect()),
            lambda _: self._check_authorization(),
            self._fatal,
        )

    def _check_authorization(self) -> None:
        poll_future(
            self,
            self.bridge.submit(self.session.is_authorized()),
            self._authorization_known,
            self._fatal,
        )

    def _authorization_known(self, authorized: bool) -> None:
        if authorized:
            self._show_main()
        else:
            LoginWindow(self, self.bridge, self.session, on_success=self._show_main)

    def _show_main(self) -> None:
        self.deiconify()
        self.lift()
        # Only what has working machinery behind it gets enabled.
        self.chat_button.configure(state="normal", command=self._pick_chat)

    # ── chat selection (task 8) ─────────────────────────────────────

    def _pick_chat(self) -> None:
        ChatPicker(self, self.bridge, self.session, on_choose=self._chat_chosen)

    def _chat_chosen(self, chat: Chat) -> None:
        self.selected_chat = chat
        self.chat_label.configure(
            text=f"{ellipsise(chat.title)}  {KIND_EMOJI.get(chat.kind, FALLBACK_EMOJI)}",
            text_color=VALUE_COLOR,
        )
        self._refresh_start()

    def _refresh_start(self) -> None:
        """Start only makes sense with both a chat and a destination."""
        ready = self.selected_chat is not None and self.selected_destination is not None
        self.start_button.configure(state="normal" if ready else "disabled")

    # ── progress bar visibility ─────────────────────────────────────

    def show_progress_bar(self) -> None:
        self.progress_bar.pack(fill="x")

    def hide_progress_bar(self) -> None:
        self.progress_bar.pack_forget()

    def _fatal(self, error: Exception) -> None:
        # Startup trouble (no internet, rejected credentials): nothing to
        # recover in-window yet, so say it plainly and leave.
        messagebox.showerror("Chronogram TG", str(error))
        self.destroy()

    # ── shutdown ────────────────────────────────────────────────────

    def _close(self) -> None:
        self.destroy()


def launch(credentials: Credentials) -> None:
    """Open the main window; returns when it closes."""
    bridge = TelegramBridge()
    bridge.start()
    session = TelegramSession(credentials)
    try:
        app = ChronogramApp(credentials, bridge, session)
        app.mainloop()
    finally:
        try:
            bridge.submit(session.disconnect()).result(timeout=5)
        except Exception:
            pass  # closing anyway; a hung disconnect must not block exit
        bridge.stop()
