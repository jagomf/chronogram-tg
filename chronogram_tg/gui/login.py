"""The login window: phone → code → optional two-step password.

It drives the step methods TelegramSession exposes (send_code,
sign_in_with_code, sign_in_with_password) and never touches Telethon
directly. Wrong codes and passwords show inline in red and the step is
retried; closing the window quits the app, since nothing works unlogged.
"""

from __future__ import annotations

import customtkinter as ctk

from ..tg import LoginError, TelegramError
from .bridge import TelegramBridge, poll_future
from .placement import centre_on_screen

PAD = 16

PHONE_STEP = "phone"
CODE_STEP = "code"
PASSWORD_STEP = "password"

PROMPTS = {
    PHONE_STEP: "Phone number, with country code (for example +34600112233):",
    CODE_STEP: "Telegram sent you a login code. Enter it here:",
    PASSWORD_STEP: "Your account uses two-step verification.\nEnter that password:",
}
BUTTONS = {PHONE_STEP: "Send code", CODE_STEP: "Sign in", PASSWORD_STEP: "Sign in"}

# Each entry is sized for what actually goes in it: a phone number with its
# country code, a login code (always 5 digits nowadays), or a password.
ENTRY_WIDTHS = {PHONE_STEP: 210, CODE_STEP: 110, PASSWORD_STEP: 240}
ENTRY_JUSTIFY = {PHONE_STEP: "left", CODE_STEP: "center", PASSWORD_STEP: "left"}


class LoginWindow(ctk.CTkToplevel):
    def __init__(self, parent, bridge: TelegramBridge, session, on_success):
        super().__init__(parent)
        self._parent = parent
        self._bridge = bridge
        self._session = session
        self._on_success = on_success
        self.step = PHONE_STEP

        self.title("Log in to Telegram")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._abandon)

        ctk.CTkLabel(self, text="Chronogram TG", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=PAD, pady=(PAD, 0)
        )
        ctk.CTkLabel(
            self,
            text="This is asked once; the session is remembered afterwards.",
            text_color="gray",
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=PAD)

        self.prompt = ctk.CTkLabel(self, text=PROMPTS[self.step], anchor="w", justify="left")
        self.prompt.grid(row=2, column=0, sticky="w", padx=PAD, pady=(PAD, 4))

        self.entry = ctk.CTkEntry(
            self,
            width=ENTRY_WIDTHS[self.step],
            height=38,
            font=ctk.CTkFont(size=17),
        )
        # No sticky: the entry centres itself in the window, like the button.
        self.entry.grid(row=3, column=0, padx=PAD)
        self.entry.bind("<Return>", lambda _event: self._submit())

        self.error_label = ctk.CTkLabel(
            self,
            text="",
            text_color=("#b02a37", "#ea868f"),
            anchor="w",
            justify="left",
            wraplength=320,
        )
        self.error_label.grid(row=4, column=0, sticky="ew", padx=PAD, pady=(4, 0))

        self.action_button = ctk.CTkButton(self, text=BUTTONS[self.step], command=self._submit)
        self.action_button.grid(row=5, column=0, padx=PAD, pady=PAD)

        centre_on_screen(self)
        self.lift()
        self.after(100, self.entry.focus_set)

    # ── the step machine ────────────────────────────────────────────

    def _show_step(self, step: str) -> None:
        self.step = step
        self.prompt.configure(text=PROMPTS[step])
        self.action_button.configure(text=BUTTONS[step])
        self.entry.delete(0, "end")
        self.entry.configure(
            show="•" if step == PASSWORD_STEP else "",
            width=ENTRY_WIDTHS[step],
            justify=ENTRY_JUSTIFY[step],
        )
        self.entry.focus_set()

    def _submit(self) -> None:
        value = self.entry.get()
        self.error_label.configure(text="")
        self._busy(True)
        if self.step == PHONE_STEP:
            self._call(self._session.send_code(value), lambda _: self._show_and_idle(CODE_STEP))
        elif self.step == CODE_STEP:
            self._call(self._session.sign_in_with_code(value), self._code_accepted)
        else:
            self._call(self._session.sign_in_with_password(value), lambda _: self._done())

    def _code_accepted(self, needs_password: bool) -> None:
        if needs_password:
            self._show_and_idle(PASSWORD_STEP)
        else:
            self._done()

    def _show_and_idle(self, step: str) -> None:
        # Unbusy first: a disabled CTkEntry silently ignores the delete that
        # _show_step performs, which would leave the previous value behind.
        self._busy(False)
        self._show_step(step)

    def _call(self, coroutine, on_result) -> None:
        poll_future(self, self._bridge.submit(coroutine), on_result, self._failed)

    def _failed(self, error: Exception) -> None:
        self._busy(False)
        if isinstance(error, (LoginError, TelegramError)):
            self.error_label.configure(text=str(error))
            # An expired code means Telegram wants the dance restarted.
            if "expired" in str(error).lower():
                self._show_step(PHONE_STEP)
        else:
            raise error

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.action_button.configure(state=state)
        self.entry.configure(state=state)

    def _done(self) -> None:
        self._on_success()
        self.destroy()

    def _abandon(self) -> None:
        # No session, nothing to do: closing the login closes the app.
        self._parent.destroy()
