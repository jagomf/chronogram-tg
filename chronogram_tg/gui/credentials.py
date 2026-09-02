"""First-run setup: ask for the Telegram API key and write the .env file.

Shown when the app starts without credentials, instead of an error. The
window also explains *why* this step exists at all, because doing this and
then logging in reasonably looks redundant: the API key identifies the app
to Telegram, while the login signs in the account whose chats are read.
"""

from __future__ import annotations

import webbrowser

import customtkinter as ctk

from ..config import ConfigError, Credentials, save_credentials
from .placement import centre_on_screen
from .widgets import DimButton

PAD = 16
WRAP = 430
MY_TELEGRAM_URL = "https://my.telegram.org"
LINK_COLOR = ("#1f6aa5", "#4d9fdb")

WHY_TEXT = (
    "Chronogram TG has no server of its own: it talks to Telegram directly, "
    "as an app that belongs to you — and Telegram asks every such app to "
    "carry its own free API key.\n\n"
    "The key identifies the app, not you. The next step, logging in, is "
    "about you: it signs in the account whose chats will be rescued."
)
HOW_TEXT = (
    "Log in there with your phone number, open “API development "
    "tools”, fill in the short form, and copy the two values here:"
)


class CredentialsWindow(ctk.CTk):
    """The setup form. `result` holds the saved Credentials, or None."""

    def __init__(self, initial_error: str | None = None):
        super().__init__()
        self.result: Credentials | None = None

        self.title("Chronogram TG")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())

        ctk.CTkLabel(
            self,
            text="One-time setup: your Telegram API key",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=PAD, pady=(PAD, 4))
        ctk.CTkLabel(self, text=WHY_TEXT, anchor="w", justify="left", wraplength=WRAP).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=PAD
        )

        get_it = ctk.CTkFrame(self, fg_color="transparent")
        get_it.grid(row=2, column=0, columnspan=2, sticky="w", padx=PAD, pady=(10, 0))
        ctk.CTkLabel(get_it, text="Get yours at").grid(row=0, column=0)
        link = ctk.CTkLabel(get_it, text="my.telegram.org", text_color=LINK_COLOR, cursor="hand2")
        link.grid(row=0, column=1, padx=(4, 0))
        link.bind("<Button-1>", lambda _event: webbrowser.open(MY_TELEGRAM_URL))
        ctk.CTkLabel(self, text=HOW_TEXT, anchor="w", justify="left", wraplength=WRAP).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=PAD
        )

        ctk.CTkLabel(self, text="API ID", anchor="w").grid(
            row=4, column=0, sticky="w", padx=(PAD, 6), pady=(12, 0)
        )
        self.id_value = ctk.StringVar()
        self.id_value.trace_add("write", lambda *_args: self._sanitise_id())
        self.id_entry = ctk.CTkEntry(self, textvariable=self.id_value, width=130)
        self.id_entry.grid(row=4, column=1, sticky="w", padx=(0, PAD), pady=(12, 0))

        ctk.CTkLabel(self, text="API hash", anchor="w").grid(
            row=5, column=0, sticky="w", padx=(PAD, 6), pady=(8, 0)
        )
        self.hash_value = ctk.StringVar()
        self.hash_value.trace_add("write", lambda *_args: self._refresh())
        self.hash_entry = ctk.CTkEntry(self, textvariable=self.hash_value, width=310)
        self.hash_entry.grid(row=5, column=1, sticky="w", padx=(0, PAD), pady=(8, 0))

        self.error_label = ctk.CTkLabel(
            self,
            text=initial_error or "",
            text_color=("#b02a37", "#ea868f"),
            anchor="w",
            justify="left",
            wraplength=WRAP,
        )
        self.error_label.grid(row=6, column=0, columnspan=2, sticky="ew", padx=PAD, pady=(6, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=7, column=0, columnspan=2, pady=(4, PAD))
        self.accept_button = DimButton(
            buttons, text="Accept", width=110, state="disabled", command=self._accept
        )
        self.accept_button.grid(row=0, column=0)
        ctk.CTkButton(buttons, text="Cancel", width=110, command=self._cancel).grid(
            row=0, column=1, padx=(8, 0)
        )
        self.bind("<Return>", lambda _event: self._accept())

        centre_on_screen(self)
        self.lift()
        self.after(100, self.id_entry.focus_set)

    def _sanitise_id(self) -> None:
        # Same self-cleaning as the login fields: digits survive, the rest
        # (spaces from a sloppy paste included) never lands.
        value = self.id_value.get()
        cleaned = "".join(c for c in value if c.isdigit())
        if cleaned != value:
            self.id_value.set(cleaned)
        self._refresh()

    def _refresh(self) -> None:
        ready = bool(self.id_value.get()) and bool(self.hash_value.get().strip())
        self.accept_button.configure(state="normal" if ready else "disabled")

    def _accept(self) -> None:
        try:
            self.result = save_credentials(self.id_value.get(), self.hash_value.get())
        except ConfigError as error:
            self.error_label.configure(text=str(error))
            return
        self.destroy()

    def _cancel(self) -> None:
        self.destroy()  # result stays None: the caller exits quietly


def ask_for_credentials(initial_error: str | None = None) -> Credentials | None:
    """Show the setup window; the saved credentials, or None if cancelled."""
    window = CredentialsWindow(initial_error)
    window.mainloop()
    return window.result
