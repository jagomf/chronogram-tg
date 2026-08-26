"""The date-range modal: day/month/year dropdowns, validated inline.

Nobody types dates by hand (owner's review), and Tk offers no native OS
date dialog, so each bound is three dropdowns. A side left fully unset is
an open end, mirroring the console's --from/--to. All dates are UTC days.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from tkinter import TclError

import customtkinter as ctk

from .placement import centre_on_screen

PAD = 16
DATE_FORMAT = "%Y-%m-%d"

UNSET = "—"
MONTHS = list(calendar.month_name)[1:]  # January..December
DAYS = [f"{day:02d}" for day in range(1, 32)]
FIRST_TELEGRAM_YEAR = 2013  # message dates cannot predate Telegram itself
YEARS = [str(year) for year in range(FIRST_TELEGRAM_YEAR, datetime.now(UTC).year + 1)]


def build_day(day: str, month: str, year: str) -> datetime | None:
    """The dropdowns' selection as midnight UTC; all-unset means open end."""
    values = (day, month, year)
    if all(value == UNSET for value in values):
        return None
    if any(value == UNSET for value in values):
        raise ValueError("Complete the date, or leave its three fields unset.")
    try:
        return datetime(int(year), MONTHS.index(month) + 1, int(day), tzinfo=UTC)
    except ValueError:
        raise ValueError(f"{day} {month} {year} is not a real date.") from None


def validate_range(
    from_parts: tuple[str, str, str], to_parts: tuple[str, str, str]
) -> tuple[datetime | None, datetime | None]:
    """Both bounds of the range, or ValueError with a user-facing message."""
    since, until = build_day(*from_parts), build_day(*to_parts)
    if since is None and until is None:
        raise ValueError("Set at least one of the two dates.")
    if since is not None and until is not None and since > until:
        raise ValueError("The start date must be on or before the end date.")
    return since, until


class DateRangeWindow(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        since: datetime | None,
        until: datetime | None,
        on_accept,
        on_close=None,
    ):
        super().__init__(parent)
        self._on_accept = on_accept
        self._on_close = on_close

        self.title("Choose a date range")
        self.resizable(False, False)
        self.transient(parent)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._accept())
        self.after(150, self._make_modal)

        def date_row(row: int, label: str, prefill: datetime | None):
            holder = ctk.CTkFrame(self, fg_color="transparent")
            # No sticky: each row centres itself in the window.
            holder.grid(row=row, column=0, padx=PAD, pady=(PAD, 0))
            ctk.CTkLabel(holder, text=label, width=44, anchor="w").grid(row=0, column=0)
            day = ctk.CTkOptionMenu(holder, values=[UNSET, *DAYS], width=64)
            month = ctk.CTkOptionMenu(holder, values=[UNSET, *MONTHS], width=110)
            year = ctk.CTkOptionMenu(holder, values=[UNSET, *YEARS], width=84)
            for column, menu in enumerate((day, month, year), start=1):
                menu.grid(row=0, column=column, padx=(6, 0))
            if prefill is not None:
                day.set(f"{prefill.day:02d}")
                month.set(MONTHS[prefill.month - 1])
                year.set(str(prefill.year))
            else:
                for menu in (day, month, year):
                    menu.set(UNSET)
            return day, month, year

        self.from_menus = date_row(0, "From", since)
        self.to_menus = date_row(1, "To", until)

        ctk.CTkLabel(self, text="Leave one side unset for an open end.", text_color="gray").grid(
            row=2, column=0, padx=PAD, pady=(8, 0)
        )

        self.error_label = ctk.CTkLabel(
            self,
            text="",
            text_color=("#b02a37", "#ea868f"),
            justify="center",
            wraplength=330,
        )
        self.error_label.grid(row=3, column=0, padx=PAD)

        self.accept_button = ctk.CTkButton(self, text="OK", width=110, command=self._accept)
        self.accept_button.grid(row=4, column=0, pady=(6, PAD))

        centre_on_screen(self)  # natural size: no spare space around the form

    def _accept(self) -> None:
        gather = lambda menus: tuple(menu.get() for menu in menus)  # noqa: E731
        try:
            since, until = validate_range(gather(self.from_menus), gather(self.to_menus))
        except ValueError as error:
            self.error_label.configure(text=str(error))
            return
        self._on_accept(since, until)
        self.destroy()

    def destroy(self) -> None:
        # Runs on accept, Esc and the close button alike; the owner of the
        # callback decides what an unset range means.
        if self._on_close is not None:
            callback, self._on_close = self._on_close, None
            callback()
        super().destroy()

    def _make_modal(self) -> None:
        try:
            self.grab_set()
        except TclError:
            pass  # not mapped yet (or headless); being non-modal is harmless
