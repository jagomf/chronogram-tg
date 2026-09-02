"""The main window.

Every control is live: session startup and login (task 7), the chat picker
(task 8), scope and destination (task 9), the download itself (task 10)
and the settings dialog with logout (task 11).
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import PhotoImage, filedialog, messagebox

import customtkinter as ctk

from ..config import DEFAULT_DOWNLOAD_DIR, Credentials, load_settings, save_settings
from ..downloader import DownloadControl, DownloadError, Summary, download_chat, human_size
from ..metadata import detect_ffmpeg
from ..tg import Chat, SessionRevokedError, TelegramError, TelegramSession
from .bridge import TelegramBridge, poll_future
from .chat_picker import FALLBACK_EMOJI, KIND_EMOJI, ChatPicker, ellipsise
from .date_range import DATE_FORMAT, DateRangeWindow
from .login import LoginWindow
from .placement import centre_on_screen
from .settings import SettingsWindow
from .widgets import DimButton

PAD = 12
BANNER_TEXT = "⚠ ffmpeg not found — videos are unavailable. See README."
ICON_FILE = Path(__file__).resolve().parent.parent / "assets" / "icon.png"

# Field styling: a placeholder reads dimmer than a chosen value, and a
# barely-there underline ties the left label to its right-hand button.
VALUE_COLOR = ("gray10", "gray90")
PLACEHOLDER_COLOR = ("gray60", "gray45")
UNDERLINE_COLOR = ("gray75", "gray30")

MAX_PATH_CHARS = 38

CHAT_PLACEHOLDER = "No chat selected"
PAUSE_TEXT = "⏸️ Pause"
RESUME_TEXT = "▶️ Resume"
RESUME_HINT = "If an earlier download was cut short, Start continues it — nothing is fetched twice."
MAX_LISTED_PROBLEMS = 20
FEED_POLL_MS = 100


class RunFeed:
    """Where the downloader's callbacks land during a run.

    The callbacks fire on the Telegram thread, and Tk widgets must only be
    touched from the interface thread — so they write plain data under a
    lock here, and a Tk `after` loop drains it. Only the latest progress
    and byte counts matter; status lines are kept in order.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._progress: tuple[int, int, str] | None = None
        self._bytes: tuple[str, int | None, int] | None = None
        self._statuses: list[str] = []

    def on_progress(self, done: int, total: int, name: str) -> None:
        with self._lock:
            self._progress = (done, total, name)
            self._bytes = None  # the finished file's byte count is stale now

    def on_bytes(self, name: str, received: int | None, expected: int) -> None:
        with self._lock:
            self._bytes = (name, received, expected)

    def on_status(self, message: str) -> None:
        with self._lock:
            self._statuses.append(message)

    def drain(self) -> tuple[tuple | None, tuple | None, list[str]]:
        with self._lock:
            statuses, self._statuses = self._statuses, []
            return self._progress, self._bytes, statuses


def run_fraction(progress: tuple[int, int, str], bytes_state: tuple | None) -> float:
    """The bar's fill: items done, plus the in-flight file's byte share."""
    done, total, _ = progress
    if not total:
        return 1.0
    fraction = done / total
    if bytes_state is not None:
        _, received, expected = bytes_state
        if received and expected:
            fraction = (done + min(received / expected, 1.0)) / total
    return min(fraction, 1.0)


def run_line(progress: tuple[int, int, str], bytes_state: tuple | None) -> str:
    """The one-line counter under the bar, byte counts included in-flight."""
    done, total, name = progress
    if bytes_state is not None:
        in_flight, received, expected = bytes_state
        if expected:
            got = "…" if received is None else human_size(received)
            current = min(done + 1, total)
            return f"{current} / {total} — {in_flight} ({got} / {human_size(expected)})"
    return f"{done} / {total} — {name}" if name else f"{done} / {total}"


def summary_line(summary: Summary) -> str:
    """The run's closing report, sized for a one-line label."""
    counts = [
        (summary.downloaded, "downloaded"),
        (summary.already_there, "already there"),
        (summary.videos_skipped, "videos skipped"),
        (summary.missing, "gone from the chat"),
        (summary.dated_by_file_time_only, "dated by file time only"),
        (len(summary.errors), "problems"),
    ]
    parts = ", ".join(f"{count} {label}" for count, label in counts if count)
    head = "Cancelled" if summary.cancelled else "Done"
    line = f"{head}: {summary.total} items" + (f" — {parts}." if parts else ".")
    return f"{line} Start resumes where it left off." if summary.cancelled else line


def shorten_path(path: Path) -> str:
    """A folder path fit for a one-line label: home as ~, tail preserved.

    Paths are cut from the front - the deepest folders are what tells a
    destination apart, not the volume prefix. The separator is the
    platform's own, so the label reads like the paths users see elsewhere
    (backslashes on Windows).
    """
    try:
        text = "~" + os.sep + str(path.relative_to(Path.home()))
    except ValueError:
        text = str(path)
    return text if len(text) <= MAX_PATH_CHARS else "…" + text[-(MAX_PATH_CHARS - 1) :]


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
        self.selected_destination: Path | None = None
        self.selected_since: datetime | None = None
        # The inclusive day the user picked; _start_download adds the +1.
        self.selected_until: datetime | None = None
        self._control: DownloadControl | None = None
        self._feed: RunFeed | None = None
        self._download_active = False
        self._rendered: tuple | None = None  # last (progress, bytes) painted
        self._bar_indeterminate = False

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
        self.settings_button = DimButton(
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
            button = DimButton(self, text=button_text, width=130, state="disabled")
            button.grid(row=row, column=2, sticky="e", padx=(6, PAD), pady=(PAD, 0))
            label_widget.bind("<Button-1>", lambda _event, target=button: target.focus_set())
            row += 1
            return value_label, button

        self.chat_label, self.chat_button = picker_row("💬 Chat", CHAT_PLACEHOLDER, "Choose chat…")

        scope_label = ctk.CTkLabel(self, text="📅 Scope", anchor="w", cursor="hand2")
        scope_label.grid(row=row, column=0, sticky="w", padx=(PAD, 6), pady=(PAD, 0))
        self.scope_value = ctk.StringVar(value="all")
        scope = ctk.CTkFrame(self, fg_color="transparent")
        scope.grid(row=row, column=1, sticky="ew", pady=(PAD, 0))
        self.whole_chat_radio = ctk.CTkRadioButton(
            scope, text="Whole chat", variable=self.scope_value, value="all", state="disabled"
        )
        self.whole_chat_radio.grid(row=0, column=0, sticky="w")
        scope_label.bind("<Button-1>", lambda _event: self.whole_chat_radio.focus_set())
        self.range_radio = ctk.CTkRadioButton(
            scope,
            text="Date range",
            variable=self.scope_value,
            value="range",
            state="disabled",
            command=self._range_scope_selected,
        )
        self.range_radio.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.range_button = DimButton(self, text="Choose dates…", width=130, state="disabled")
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
        # Nobody should fear that Start throws away a half-done rescue. The
        # text is blanked (not removed) during a run so the window keeps its
        # natural size.
        self.resume_hint = ctk.CTkLabel(
            self,
            text=RESUME_HINT,
            anchor="w",
            text_color="gray",
            font=ctk.CTkFont(size=11, slant="italic"),
        )
        self.resume_hint.grid(row=row, column=0, columnspan=3, sticky="ew", padx=PAD)
        row += 1

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        # No sticky: the frame centres itself in its row, resize or not.
        buttons.grid(row=row, column=0, columnspan=3, padx=PAD, pady=PAD)
        # The command is what makes CTk show the pointing-hand cursor on an
        # enabled button, so Start carries one from the beginning.
        self.start_button = DimButton(
            buttons, text="▶️ Start", state="disabled", command=self._start_download
        )
        self.start_button.grid(row=0, column=0)
        self.pause_button = DimButton(
            buttons, text=PAUSE_TEXT, state="disabled", command=self._toggle_pause
        )
        self.pause_button.grid(row=0, column=1, padx=(8, 0))
        self.cancel_button = DimButton(
            buttons, text="⏹️ Cancel", state="disabled", command=self._cancel_download
        )
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
        self.chat_button.configure(state="normal", command=self._pick_chat)
        self.whole_chat_radio.configure(state="normal")
        self.range_radio.configure(state="normal")
        self.range_button.configure(state="normal", command=self._open_range_modal)
        self.destination_button.configure(state="normal", command=self._pick_destination)
        self.settings_button.configure(state="normal", command=self._open_settings)
        # The destination is never empty: the remembered folder if it still
        # exists, else ~/Downloads/Chronogram (created when a download runs).
        stored = load_settings().last_destination
        if stored and Path(stored).is_dir():
            self._destination_chosen(Path(stored), persist=False)
        else:
            self._destination_chosen(DEFAULT_DOWNLOAD_DIR, persist=False)

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

    # ── scope and destination (task 9) ──────────────────────────────

    def _range_scope_selected(self) -> None:
        # Picking the radio without dates yet leads straight into the modal;
        # cancelling it falls back to the whole chat (see _range_modal_closed).
        if self.selected_since is None and self.selected_until is None:
            self._open_range_modal()

    def _open_range_modal(self) -> None:
        DateRangeWindow(
            self,
            self.selected_since,
            self.selected_until,
            on_accept=self._range_chosen,
            on_close=self._range_modal_closed,
        )

    def _range_chosen(self, since: datetime | None, until: datetime | None) -> None:
        self.selected_since = since
        self.selected_until = until
        self.scope_value.set("range")

        def day(moment: datetime | None) -> str:
            return moment.strftime(DATE_FORMAT) if moment else "…"

        self.range_radio.configure(text=f"{day(since)} → {day(until)}")

    def _range_modal_closed(self) -> None:
        if self.selected_since is None and self.selected_until is None:
            self.scope_value.set("all")

    def _pick_destination(self) -> None:
        # The preselected folder may not exist yet; the dialog needs a real
        # starting point, so walk up to the nearest existing ancestor.
        initial = self.selected_destination or Path.home()
        while not initial.is_dir() and initial.parent != initial:
            initial = initial.parent
        chosen = filedialog.askdirectory(
            parent=self, initialdir=str(initial), title="Choose the destination folder"
        )
        if chosen:
            self._destination_chosen(Path(chosen), persist=True)

    def _destination_chosen(self, path: Path, persist: bool) -> None:
        self.selected_destination = path
        self.destination_label.configure(text=shorten_path(path), text_color=VALUE_COLOR)
        if persist:
            settings = load_settings()
            settings.last_destination = str(path)
            save_settings(settings)
        self._refresh_start()

    # ── the download itself (task 10) ───────────────────────────────

    def _start_download(self) -> None:
        since = until_exclusive = None
        if self.scope_value.get() == "range":
            since = self.selected_since
            if self.selected_until is not None:
                until_exclusive = self.selected_until + timedelta(days=1)

        self._control = DownloadControl()
        self._feed = RunFeed()
        self._rendered = None
        self._set_running(True)
        self._bar_scanning()
        self.show_progress_bar()
        self.progress_label.configure(text="Starting…")

        future = self.bridge.submit(
            download_chat(
                self.session,
                self.selected_chat.id,
                self.selected_destination,
                load_settings().filename_template,
                since=since,
                until_exclusive=until_exclusive,
                include_videos=bool(self.videos_checkbox.get()),
                control=self._control,
                on_progress=self._feed.on_progress,
                on_status=self._feed.on_status,
                on_bytes=self._feed.on_bytes,
            )
        )
        poll_future(self, future, self._download_finished, self._download_failed)
        self.after(FEED_POLL_MS, self._poll_feed)

    def _set_running(self, running: bool) -> None:
        """While a run is on, the form sleeps and Pause/Cancel wake up."""
        form_state = "disabled" if running else "normal"
        for widget in (
            self.chat_button,
            self.whole_chat_radio,
            self.range_radio,
            self.range_button,
            self.destination_button,
            self.settings_button,
        ):
            widget.configure(state=form_state)
        if self.ffmpeg_available:
            self.videos_checkbox.configure(state=form_state)
        run_state = "normal" if running else "disabled"
        self.pause_button.configure(state=run_state, text=PAUSE_TEXT)
        self.cancel_button.configure(state=run_state)
        self.resume_hint.configure(text="" if running else RESUME_HINT)
        if running:
            self.start_button.configure(state="disabled")
        else:
            self._refresh_start()
        self._download_active = running

    def _bar_scanning(self) -> None:
        """While the scan runs there is no total yet: sweep, do not sit at 0."""
        self._bar_indeterminate = True
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

    def _bar_tracking(self) -> None:
        """Back to a plain 0..1 bar; called once real progress exists."""
        if self._bar_indeterminate:
            self._bar_indeterminate = False
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            self.progress_bar.set(0)

    def _poll_feed(self) -> None:
        if not self._download_active:
            return
        progress, bytes_state, statuses = self._feed.drain()
        # While paused nothing new should paint over "Paused." - at most one
        # already-received chunk trickles in after the click.
        paused = self._control.paused
        if progress is not None and not paused:
            self._bar_tracking()
            self.progress_bar.set(run_fraction(progress, bytes_state))
        snapshot = (progress, bytes_state)
        if statuses:
            # A status line (flood wait, scan report) holds the label until
            # something newer than what arrived alongside it comes in.
            self.progress_label.configure(text=statuses[-1])
            self._rendered = snapshot
        elif not paused and progress is not None and snapshot != self._rendered:
            self._rendered = snapshot
            self.progress_label.configure(text=run_line(progress, bytes_state))
        self.after(FEED_POLL_MS, self._poll_feed)

    def _toggle_pause(self) -> None:
        # The pause gate sits between chunks, so even a gigabyte video
        # holds almost immediately.
        if self._control.paused:
            self._control.resume()
            self.pause_button.configure(text=PAUSE_TEXT)
            self._rendered = None  # repaint the counter as soon as bytes flow
        else:
            self._control.pause()
            self.pause_button.configure(text=RESUME_TEXT)
            self.progress_label.configure(text="Paused.")

    def _cancel_download(self) -> None:
        self._control.cancel()
        self.pause_button.configure(state="disabled")
        self.cancel_button.configure(state="disabled")
        self.progress_label.configure(text="Cancelling…")

    def _download_finished(self, summary: Summary) -> None:
        self._set_running(False)
        self._bar_tracking()  # a run can end while the bar still sweeps
        self.hide_progress_bar()
        self.progress_bar.set(0)
        self.progress_label.configure(text=summary_line(summary))
        if summary.errors:
            listed = summary.errors[:MAX_LISTED_PROBLEMS]
            if len(summary.errors) > len(listed):
                listed.append(f"…and {len(summary.errors) - len(listed)} more")
            messagebox.showwarning(
                "Chronogram TG",
                "Some items had problems (the rest of the run was unaffected):\n\n"
                + "\n".join(listed),
            )

    def _download_failed(self, error: Exception) -> None:
        # Session-level trouble (expired export, lost login): the run is
        # over, but the window stays usable so Start can try again.
        self._set_running(False)
        self._bar_tracking()
        self.hide_progress_bar()
        self.progress_bar.set(0)
        self.progress_label.configure(text="The download stopped.")
        if isinstance(error, SessionRevokedError):
            # Signed out from another device: back to the login window,
            # exactly like an in-app logout (D8).
            messagebox.showwarning("Chronogram TG", str(error))
            self._session_revoked()
            return
        friendly = isinstance(error, (TelegramError, DownloadError))
        prefix = "" if friendly else f"{type(error).__name__}: "
        messagebox.showerror("Chronogram TG", f"{prefix}{error}")

    # ── settings and logout (task 11) ───────────────────────────────

    def _open_settings(self) -> None:
        SettingsWindow(
            self,
            load_settings().filename_template,
            on_save=self._template_saved,
            on_logout=self._log_out,
        )

    def _template_saved(self, template: str) -> None:
        settings = load_settings()
        settings.filename_template = template
        save_settings(settings)

    def _reset_form_for_login(self) -> None:
        # Back towards the login window (D8). The selection is account-bound,
        # so it resets; the destination and pattern are this machine's, they
        # stay.
        self.selected_chat = None
        self.chat_label.configure(text=CHAT_PLACEHOLDER, text_color=PLACEHOLDER_COLOR)
        for widget in (
            self.chat_button,
            self.whole_chat_radio,
            self.range_radio,
            self.range_button,
            self.destination_button,
            self.settings_button,
            self.start_button,
        ):
            widget.configure(state="disabled")
        self.withdraw()

    def _log_out(self) -> None:
        self._reset_form_for_login()
        poll_future(
            self,
            self.bridge.submit(self.session.log_out()),
            lambda _: self._reconnect_for_login(),
            self._fatal,
        )

    def _session_revoked(self) -> None:
        # No log_out call: Telegram already killed the session. Disconnect
        # and reconnect so the login starts from a clean client.
        self._reset_form_for_login()
        poll_future(
            self,
            self.bridge.submit(self.session.disconnect()),
            lambda _: self._reconnect_for_login(),
            self._fatal,
        )

    def _reconnect_for_login(self) -> None:
        # log_out tears the client down and deletes the session file, so a
        # fresh connection must exist before the login steps can run.
        poll_future(
            self,
            self.bridge.submit(self.session.connect()),
            lambda _: LoginWindow(self, self.bridge, self.session, on_success=self._show_main),
            self._fatal,
        )

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
        if self._download_active and self._control is not None:
            # The window dies now; asking the loop to stop keeps the
            # session teardown in launch() from fighting a live download.
            self._control.cancel()
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
