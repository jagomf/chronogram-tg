"""The About modal: who made this, which version, on whose shoulders.

The dependency licences come from importlib.metadata at runtime, so the
list is always what is actually installed - no hand-maintained table to
drift out of date, and no extra package needed to produce it.
"""

from __future__ import annotations

import webbrowser
from importlib import metadata
from tkinter import TclError

import customtkinter as ctk

from .. import __version__
from .placement import centre_on_screen

PAD = 16

CREATOR_PREFIX = "Created by Jago / "
LUNADEVEL_URL = "https://lunadevel.com"
REPOSITORY_URL = "https://github.com/jagomf/chronogram-tg"
APP_LICENCE = "Released under the MIT license."

# The app's direct dependencies, as pinned in requirements.txt.
DIRECT_DEPENDENCIES = ("telethon", "customtkinter", "piexif", "python-dotenv")

LINK_COLOR = ("#1f6aa5", "#4d9fdb")


def _licence_of(dist) -> str:
    """The distribution's licence, from the tidiest field that has one."""
    fields = dist.metadata
    expression = (fields.get("License-Expression") or "").strip()
    if expression:
        return expression
    # The classifier beats the free-form License field, which sometimes
    # holds the licence's full text rather than its name.
    for classifier in fields.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    field = (fields.get("License") or "").strip()
    if field and len(field) < 40 and "\n" not in field:
        return field
    return "see the package's page"


def dependency_licences() -> list[tuple[str, str, str]]:
    """(name, version, licence) for each direct dependency, best effort.

    A package that cannot be found is skipped rather than crashing the
    About window: the list is informative, never load-bearing.
    """
    rows = []
    for name in DIRECT_DEPENDENCIES:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        rows.append((dist.metadata.get("Name") or name, dist.version, _licence_of(dist)))
    return rows


class AboutWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("About")
        self.resizable(False, False)
        self.transient(parent)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.after(150, self._make_modal)

        ctk.CTkLabel(self, text="Chronogram TG", font=ctk.CTkFont(size=20, weight="bold")).grid(
            row=0, column=0, padx=PAD * 2, pady=(PAD, 0)
        )
        self.version_label = ctk.CTkLabel(self, text=f"Version {__version__}")
        self.version_label.grid(row=1, column=0, padx=PAD * 2)
        def link(parent, text: str, url: str) -> ctk.CTkLabel:
            label = ctk.CTkLabel(parent, text=text, text_color=LINK_COLOR, cursor="hand2")
            label.bind("<Button-1>", lambda _event: webbrowser.open(url))
            return label

        # Two labels on one line, because only the LunaDevel half is a link.
        creator = ctk.CTkFrame(self, fg_color="transparent")
        creator.grid(row=2, column=0, padx=PAD * 2, pady=(8, 0))
        self.creator_label = ctk.CTkLabel(creator, text=CREATOR_PREFIX)
        self.creator_label.grid(row=0, column=0)
        self.lunadevel_link = link(creator, "LunaDevel", LUNADEVEL_URL)
        self.lunadevel_link.grid(row=0, column=1)

        link(self, REPOSITORY_URL.removeprefix("https://"), REPOSITORY_URL).grid(
            row=3, column=0, padx=PAD * 2
        )

        rows = "\n".join(
            f"{name} {version} — {licence}" for name, version, licence in dependency_licences()
        )
        self.licences_label = ctk.CTkLabel(
            self,
            text=f"{APP_LICENCE} Built on:\n{rows}",
            text_color="gray",
            font=ctk.CTkFont(size=11),
            justify="center",
        )
        self.licences_label.grid(row=4, column=0, padx=PAD * 2, pady=(12, 0))

        ctk.CTkButton(self, text="Close", width=110, command=self.destroy).grid(
            row=5, column=0, pady=PAD
        )

        centre_on_screen(self)

    def _make_modal(self) -> None:
        try:
            self.grab_set()
        except TclError:
            pass  # not mapped yet (or headless); being non-modal is harmless
