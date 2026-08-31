"""The settings modal: filename pattern with live preview, and logout.

The pattern machinery (presets, validation, sample rendering) lives in
naming.py; this window only puts a face on it. The preview shows a photo
and a video example so the {kind} token's effect is visible at a glance.
"""

from __future__ import annotations

from tkinter import TclError, messagebox

import customtkinter as ctk

from ..naming import PRESETS, TOKEN_HELP, TemplateError, preview
from .placement import centre_on_screen
from .widgets import DimButton

PAD = 16
CUSTOM_LABEL = "Custom"

LOGOUT_QUESTION = "Log out of Telegram?\n\nYou will need to enter a login code again."


def preset_for(template: str) -> str:
    """The preset name a template belongs to, or the Custom label."""
    for name, value in PRESETS.items():
        if value == template:
            return name
    return CUSTOM_LABEL


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent, template: str, on_save, on_logout):
        super().__init__(parent)
        self._on_save = on_save
        self._on_logout = on_logout
        self._initial = template  # Save only arms once the pattern differs

        self.title("Settings")
        self.resizable(False, False)
        self.transient(parent)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._save())
        self.after(150, self._make_modal)

        ctk.CTkLabel(self, text="Filename pattern", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=PAD, pady=(PAD, 4)
        )

        ctk.CTkLabel(self, text="Preset", anchor="w").grid(
            row=1, column=0, sticky="w", padx=(PAD, 6)
        )
        self.preset_menu = ctk.CTkOptionMenu(
            self, values=[*PRESETS, CUSTOM_LABEL], width=160, command=self._preset_picked
        )
        self.preset_menu.grid(row=1, column=1, sticky="w", padx=(0, PAD))

        ctk.CTkLabel(self, text="Pattern", anchor="w").grid(
            row=2, column=0, sticky="w", padx=(PAD, 6), pady=(8, 0)
        )
        self.template_value = ctk.StringVar(value=template)
        self.template_value.trace_add("write", lambda *_args: self._refresh())
        self.entry = ctk.CTkEntry(self, textvariable=self.template_value, width=280)
        self.entry.grid(row=2, column=1, sticky="w", padx=(0, PAD), pady=(8, 0))

        ctk.CTkLabel(self, text=TOKEN_HELP, text_color="gray", anchor="w").grid(
            row=3, column=1, sticky="w", padx=(0, PAD)
        )

        # The fixed-sample preview: one photo line, one video line.
        self.preview_label = ctk.CTkLabel(self, text="", anchor="w", justify="left")
        self.preview_label.grid(row=4, column=1, sticky="w", padx=(0, PAD), pady=(8, 0))

        self.error_label = ctk.CTkLabel(
            self,
            text="",
            text_color=("#b02a37", "#ea868f"),
            anchor="w",
            justify="left",
            wraplength=300,
        )
        self.error_label.grid(row=5, column=1, sticky="ew", padx=(0, PAD))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=6, column=0, columnspan=2, pady=(4, PAD))
        self.save_button = DimButton(buttons, text="Save", width=110, command=self._save)
        self.save_button.grid(row=0, column=0)
        ctk.CTkButton(buttons, text="Cancel", width=110, command=self.destroy).grid(
            row=0, column=1, padx=(8, 0)
        )

        divider = ctk.CTkFrame(self, height=1, corner_radius=0, fg_color=("gray75", "gray30"))
        divider.grid(row=7, column=0, columnspan=2, sticky="ew", padx=PAD)

        account = ctk.CTkFrame(self, fg_color="transparent")
        account.grid(row=8, column=0, columnspan=2, sticky="ew", padx=PAD, pady=PAD)
        account.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(account, text="Signed in to Telegram.", anchor="w", text_color="gray").grid(
            row=0, column=0, sticky="w"
        )
        self.logout_button = ctk.CTkButton(
            account,
            text="Log out…",
            width=110,
            fg_color=("#b02a37", "#7a1f28"),
            hover_color=("#8b2129", "#5c171e"),
            command=self._confirm_logout,
        )
        self.logout_button.grid(row=0, column=1, sticky="e", padx=(12, 0))

        self._refresh()
        centre_on_screen(self)

    # ── the pattern editor ──────────────────────────────────────────

    def _preset_picked(self, name: str) -> None:
        # Custom is a state, not a preset: picking it keeps the pattern.
        if name in PRESETS:
            self.template_value.set(PRESETS[name])

    def _refresh(self) -> None:
        template = self.template_value.get()
        self.preset_menu.set(preset_for(template))
        try:
            examples = f"{preview(template)}\n{preview(template, 'mp4')}"
        except TemplateError as error:
            self.preview_label.configure(text="")
            self.error_label.configure(text=str(error))
            self.save_button.configure(state="disabled")
            return
        self.preview_label.configure(text=examples)
        self.error_label.configure(text="")
        changed = template != self._initial
        self.save_button.configure(state="normal" if changed else "disabled")

    def _save(self) -> None:
        template = self.template_value.get()
        if template == self._initial:
            self.destroy()  # Return with nothing to save: close, like Cancel
            return
        try:
            preview(template)  # validates; the button state could be stale
        except TemplateError as error:
            self.error_label.configure(text=str(error))
            return
        self._on_save(template)
        self.destroy()

    # ── the account ─────────────────────────────────────────────────

    def _confirm_logout(self) -> None:
        if messagebox.askyesno("Chronogram TG", LOGOUT_QUESTION, parent=self):
            self.destroy()
            self._on_logout()

    def _make_modal(self) -> None:
        try:
            self.grab_set()
        except TclError:
            pass  # not mapped yet (or headless); being non-modal is harmless
