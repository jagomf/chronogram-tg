"""The chat picker: a modal list of chats with a search box.

Chats load through the bridge with a visible loading state; typing filters
by case-insensitive substring. Only a page of matches is rendered at a
time - building hundreds of rows per keystroke would make typing sticky,
and nobody scans 200 rows when typing three letters narrows them to five.
"""

from __future__ import annotations

from tkinter import TclError

import customtkinter as ctk

from ..tg import Chat
from .bridge import TelegramBridge, poll_future
from .placement import centre_on_screen

PAD = 12
CHAT_LOAD_LIMIT = 200
VISIBLE_LIMIT = 50

# Long titles give way to the kind marker at the end of the row.
MAX_TITLE_CHARS = 34
KIND_EMOJI = {"person": "👤", "group": "👥", "bot": "🤖", "channel": "📢"}
FALLBACK_EMOJI = "💬"

# The filter pills above the list, in display order. None means no filter.
KIND_FILTERS = {
    "All": None,
    "👤 People": "person",
    "👥 Groups": "group",
    "📢 Channels": "channel",
    "🤖 Bots": "bot",
}

ROW_HOVER = ("gray80", "gray28")


def ellipsise(title: str, limit: int = MAX_TITLE_CHARS) -> str:
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def filter_chats(chats: list[Chat], needle: str, kind: str | None) -> list[Chat]:
    """The picker's filter: search text and kind pill combined."""
    needle = needle.strip().lower()
    return [
        chat
        for chat in chats
        if needle in chat.title.lower() and (kind is None or chat.kind == kind)
    ]


class ChatPicker(ctk.CTkToplevel):
    def __init__(self, parent, bridge: TelegramBridge, session, on_choose):
        super().__init__(parent)
        self._bridge = bridge
        self._session = session
        self._on_choose = on_choose
        self._chats: list[Chat] = []
        self.filtered: list[Chat] = []

        self.title("Choose a chat")
        centre_on_screen(self, 440, 520)
        self.resizable(False, False)
        self.transient(parent)
        # Esc closes, as any desktop modal should. (The login window has no
        # such binding on purpose: closing it quits the whole app.)
        self.bind("<Escape>", lambda _event: self.destroy())
        # grab_set fails while the window is not mapped yet, so it waits a
        # beat; modality is a nicety here, not a correctness requirement.
        self.after(150, self._make_modal)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self.search = ctk.CTkEntry(self, placeholder_text="Type to search…")
        self.search.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 0))
        self.search.bind("<KeyRelease>", lambda _event: self._refilter())
        # A magnifier as a suffix inside the box, so the field reads as
        # search at a glance. Parented to the entry's inner text widget, not
        # to the CTkEntry frame: the inner widget's area never includes the
        # rounded border, so the label cannot sit on top of it.
        ctk.CTkLabel(self.search._entry, text="🔍", fg_color="transparent").place(
            relx=1.0, rely=0.5, x=-4, anchor="e"
        )

        self.kind_pills = ctk.CTkSegmentedButton(
            self,
            values=list(KIND_FILTERS),
            command=lambda _value: self._refilter(),
        )
        self.kind_pills.set("All")
        self.kind_pills.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(8, 0))

        self.status = ctk.CTkLabel(self, text="Loading your chats…", text_color="gray")
        self.status.grid(row=2, column=0, sticky="w", padx=PAD, pady=(6, 0))

        self.chat_list = ctk.CTkScrollableFrame(self)
        self.chat_list.grid(row=3, column=0, sticky="nsew", padx=PAD, pady=PAD)
        self.chat_list.grid_columnconfigure(0, weight=1)

        # Tk 9 delivers two-finger trackpad gestures as <TouchpadScroll>,
        # which CustomTkinter (6.0.0) does not listen for - it only binds
        # <MouseWheel>. Without this, the list ignores trackpads entirely.
        self.bind_all("<TouchpadScroll>", self._touchpad_scroll, add=True)

        self.retry_button = ctk.CTkButton(self, text="Try again", command=self._load)
        # gridded only when loading fails

        self._load()
        self.after(100, self.search.focus_set)

    def destroy(self) -> None:
        self.unbind_all("<TouchpadScroll>")
        super().destroy()

    # ── scrolling ───────────────────────────────────────────────────

    def _touchpad_scroll(self, event) -> None:
        # TIP 684 packs the two axes into event.delta as signed 16-bit
        # halves; the low half is the vertical movement in pixels.
        pixels = event.delta & 0xFFFF
        if pixels >= 0x8000:
            pixels -= 0x10000
        canvas = self.chat_list._parent_canvas
        top, bottom = canvas.yview()
        if not pixels or bottom - top >= 1:
            return  # nothing to scroll
        content = canvas.bbox("all")
        content_height = max(content[3] - content[1], 1) if content else 1
        canvas.yview_moveto(top - pixels / content_height)

    # ── loading ─────────────────────────────────────────────────────

    def _load(self) -> None:
        self.retry_button.grid_forget()
        self.status.configure(text="Loading your chats…", text_color="gray")
        poll_future(
            self,
            self._bridge.submit(self._session.list_chats(limit=CHAT_LOAD_LIMIT)),
            self._loaded,
            self._failed,
        )

    def _loaded(self, chats: list[Chat]) -> None:
        self._chats = chats
        self.status.configure(text=f"{len(chats)} chats", text_color="gray")
        self._refilter()

    def _failed(self, error: Exception) -> None:
        self.status.configure(text=str(error), text_color=("#b02a37", "#ea868f"))
        self.retry_button.grid(row=4, column=0, padx=PAD, pady=(0, PAD))

    # ── filtering and choosing ──────────────────────────────────────

    def _refilter(self) -> None:
        kind = KIND_FILTERS.get(self.kind_pills.get())
        self.filtered = filter_chats(self._chats, self.search.get(), kind)

        for row in self.chat_list.winfo_children():
            row.destroy()

        if not self.filtered:
            ctk.CTkLabel(self.chat_list, text="No chats match.", text_color="gray").grid(
                row=0, column=0, pady=PAD
            )
            return

        for index, chat in enumerate(self.filtered[:VISIBLE_LIMIT]):
            self._add_row(index, chat)

        hidden = len(self.filtered) - VISIBLE_LIMIT
        if hidden > 0:
            ctk.CTkLabel(
                self.chat_list,
                text=f"…and {hidden} more — keep typing to narrow down.",
                text_color="gray",
            ).grid(row=VISIBLE_LIMIT, column=0, pady=(6, 0))

    def _add_row(self, index: int, chat: Chat) -> None:
        row = ctk.CTkFrame(self.chat_list, fg_color="transparent", corner_radius=6)
        row.grid(row=index, column=0, sticky="ew", pady=1)
        row.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(row, text=ellipsise(chat.title), anchor="w")
        title.grid(row=0, column=0, sticky="ew", padx=(10, 6), pady=3)
        kind = ctk.CTkLabel(row, text=KIND_EMOJI.get(chat.kind, FALLBACK_EMOJI), anchor="e")
        kind.grid(row=0, column=1, padx=(0, 10))

        def choose(_event, chosen=chat):
            self._choose(chosen)

        for widget in (row, title, kind):
            widget.bind("<Button-1>", choose)
        row.bind("<Enter>", lambda _e, frame=row: frame.configure(fg_color=ROW_HOVER))
        row.bind("<Leave>", lambda _e, frame=row: frame.configure(fg_color="transparent"))

    def _choose(self, chat: Chat) -> None:
        self._on_choose(chat)
        self.destroy()

    def _make_modal(self) -> None:
        try:
            self.grab_set()
        except TclError:
            pass  # not mapped yet (or headless); being non-modal is harmless
