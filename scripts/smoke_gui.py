"""Manual smoke check for the main window shell (decisions D6/D7).

Run with:  .venv/bin/python scripts/smoke_gui.py

This lives outside the pytest suite on purpose: building and destroying Tk
roots inside a long-lived pytest process hangs or crashes at teardown
(CustomTkinter keeps appearance/scaling watchers alive), so each scenario
here runs in its own subprocess instead. Exit code 0 means every check
passed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

SCENARIOS = {
    "with_ffmpeg": """
        from chronogram_tg.config import Credentials
        from chronogram_tg.gui import app as app_module
        from chronogram_tg.gui.bridge import TelegramBridge

        app_module.detect_ffmpeg = lambda: "/fake/ffmpeg"
        bridge = TelegramBridge()
        bridge.start()
        application = app_module.ChronogramApp(Credentials(1, "x"), bridge)
        for _ in range(10):
            application.update()
        assert application.banner is None, "no banner expected with ffmpeg"
        assert application.videos_checkbox.get() == 1
        assert application.videos_checkbox.cget("state") == "normal"
        for control in (
            application.start_button, application.pause_button,
            application.cancel_button, application.chat_button,
            application.destination_button, application.range_button,
            application.settings_button,
        ):
            assert control.cget("state") == "disabled", "skeleton controls must start disabled"
        from chronogram_tg.gui.widgets import DISABLED_FG
        button = application.chat_button
        assert button.cget("fg_color") == DISABLED_FG, "disabled buttons dim fully"
        button.configure(state="normal")
        application.update()
        assert button.cget("fg_color") != DISABLED_FG, "enabling restores the colour"
        button.configure(state="disabled")

        assert application.progress_bar.get() == 0
        assert application.progress_bar.winfo_manager() == "", "bar starts hidden"
        application.show_progress_bar()
        application.update()
        assert application.progress_bar.winfo_manager() == "pack", "bar shows on demand"
        before = application.winfo_reqheight()
        application.hide_progress_bar()
        application.update()
        assert application.progress_bar.winfo_manager() == "", "bar hides again"
        assert application.winfo_reqheight() == before, "hiding must not resize the window"
        assert application._icon is not None, "the app icon must load"
        assert application.resizable() == (False, False), "window must be fixed-size"
        application.update_idletasks()
        assert application.winfo_height() < 420, "window should hug its content"
        application.destroy()
        bridge.stop()
        assert not bridge.running, "bridge must stop with the window"
    """,
    "without_ffmpeg": """
        from chronogram_tg.config import Credentials
        from chronogram_tg.gui import app as app_module

        app_module.detect_ffmpeg = lambda: None
        application = app_module.ChronogramApp(Credentials(1, "x"), bridge=None)
        for _ in range(10):
            application.update()
        assert application.banner is not None, "banner expected without ffmpeg"
        assert application.banner.cget("text") == app_module.BANNER_TEXT
        assert application.videos_checkbox.get() == 0
        assert application.videos_checkbox.cget("state") == "disabled"
        application.destroy()
    """,
    "login_flow": """
        import time
        import customtkinter as ctk
        from chronogram_tg.tg import LoginError
        from chronogram_tg.gui.bridge import TelegramBridge
        from chronogram_tg.gui.login import LoginWindow, CODE_STEP, PASSWORD_STEP, PHONE_STEP

        class FakeSession:
            async def send_code(self, phone):
                if not phone.strip():
                    raise LoginError("Enter your phone number.")

            async def sign_in_with_code(self, code):
                if code != "12345":
                    raise LoginError("That code is not correct. Try again.")
                return True  # 2FA still needed

            async def sign_in_with_password(self, password):
                pass

        def pump(condition, why):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                root.update()
                if condition():
                    return
                time.sleep(0.01)
            raise AssertionError("timed out waiting for: " + why)

        root = ctk.CTk()
        root.withdraw()
        bridge = TelegramBridge()
        bridge.start()
        logged_in = []
        window = LoginWindow(root, bridge, FakeSession(), on_success=lambda: logged_in.append(True))

        window._submit()  # empty phone: inline error, still on the phone step
        pump(lambda: window.error_label.cget("text") != "", "empty-phone error")
        assert window.step == PHONE_STEP

        window.entry.insert(0, "tel: +34 600-112.233")  # pasted with decoration
        assert window.entry.get() == "+34600112233", "the phone field cleans itself"
        window._submit()
        pump(lambda: window.step == CODE_STEP, "advance to the code step")

        window.entry.insert(0, "x9y9z9 9-9!")  # the code field keeps digits only
        assert window.entry.get() == "99999"
        window._submit()  # wrong code: error, stays on code step
        pump(lambda: window.error_label.cget("text") != "", "wrong-code error")
        assert window.step == CODE_STEP

        window.entry.delete(0, "end")
        window.entry.insert(0, "12345")
        window._submit()
        pump(lambda: window.step == PASSWORD_STEP, "advance to the password step")
        assert window.entry.cget("show") == "•", "password must be masked"
        assert window.entry.get() == "", "the code must not linger in the password field"

        window.entry.insert(0, "hunter2")
        window._submit()
        pump(lambda: logged_in, "the success callback")

        root.destroy()
        bridge.stop()
    """,
    "chat_picker": """
        import time
        import customtkinter as ctk
        from chronogram_tg.tg import Chat, TelegramError
        from chronogram_tg.gui.bridge import TelegramBridge
        from chronogram_tg.gui.chat_picker import ChatPicker

        CHATS = [
            Chat(id=1, title="Mum", kind="person"),
            Chat(id=2, title="Family group", kind="group"),
            Chat(id=3, title="Family news channel", kind="channel"),
            Chat(id=4, title="Work", kind="group"),
        ]

        class FakeSession:
            def __init__(self):
                self.fail_next = True

            async def list_chats(self, limit=None):
                if self.fail_next:
                    self.fail_next = False
                    raise TelegramError("Could not reach Telegram.")
                return CHATS

        def pump(condition, why):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                root.update()
                if condition():
                    return
                time.sleep(0.01)
            raise AssertionError("timed out waiting for: " + why)

        root = ctk.CTk()
        root.withdraw()
        bridge = TelegramBridge()
        bridge.start()
        chosen = []
        picker = ChatPicker(root, bridge, FakeSession(), on_choose=chosen.append)

        # First load fails: the error shows and Try again appears.
        pump(lambda: "Could not reach" in picker.status.cget("text"), "the load error")
        pump(lambda: picker.retry_button.winfo_manager() != "", "the retry button")

        picker._load()  # what Try again invokes
        pump(lambda: len(picker.filtered) == 4, "all chats after a retry")

        picker.search.insert(0, "fam")  # case-insensitive substring filter
        picker._refilter()
        pump(lambda: len(picker.filtered) == 2, "the filtered list")
        assert [c.title for c in picker.filtered] == ["Family group", "Family news channel"]

        picker.kind_pills.set("📢 Channels")  # pills combine with the search text
        picker._refilter()
        pump(lambda: len(picker.filtered) == 1, "the pill-narrowed list")
        assert picker.filtered[0].title == "Family news channel"

        picker.kind_pills.set("All")
        picker._refilter()
        pump(lambda: len(picker.filtered) == 2, "back to the search-only filter")

        picker._choose(picker.filtered[0])
        assert chosen and chosen[0].title == "Family group"
        pump(lambda: not picker.winfo_exists(), "the picker to close on choice")

        root.destroy()
        bridge.stop()
    """,
    "download_run": """
        from pathlib import Path
        from chronogram_tg.config import Credentials
        from chronogram_tg.downloader import DownloadControl, Summary
        from chronogram_tg.gui import app as app_module
        from chronogram_tg.gui.app import PAUSE_TEXT, RESUME_TEXT, RunFeed
        from chronogram_tg.tg import Chat

        app_module.detect_ffmpeg = lambda: "/fake/ffmpeg"
        application = app_module.ChronogramApp(Credentials(1, "x"), bridge=None)
        for _ in range(10):
            application.update()

        # Arm the window as if a chat and a folder had been picked, then
        # drive the run state machine directly - the downloader itself is
        # unit-tested; this checks the wiring around it.
        application.selected_chat = Chat(id=1, title="Mum", kind="person")
        application.selected_destination = Path.home()
        application._control = DownloadControl()
        application._feed = RunFeed()
        application._set_running(True)
        application._bar_scanning()
        application.show_progress_bar()
        application.update()
        assert application.progress_bar.cget("mode") == "indeterminate", "the bar sweeps at first"
        for widget in (
            application.chat_button, application.range_button,
            application.destination_button, application.start_button,
        ):
            assert widget.cget("state") == "disabled", "the form must sleep while running"
        assert application.videos_checkbox.cget("state") == "disabled"
        assert application.pause_button.cget("state") == "normal"
        assert application.cancel_button.cget("state") == "normal"
        assert application.progress_bar.winfo_manager() == "pack", "the bar shows during a run"

        application._feed.on_status("161 items to consider, 6.5 GB in total.")
        application._poll_feed()
        application.update()
        assert "161 items" in application.progress_label.cget("text"), "statuses reach the label"
        assert application.progress_bar.cget("mode") == "indeterminate", "no ticks: keep sweeping"

        application._feed.on_progress(74, 161, "IMG_a.jpg")
        application._feed.on_bytes("VID_b.mp4", 292, 1000)
        application._poll_feed()
        application.update()
        assert application.progress_bar.cget("mode") == "determinate", "progress ends the sweep"
        assert "VID_b.mp4" in application.progress_label.cget("text")
        assert application.progress_bar.get() > 74 / 161, "in-flight bytes advance the bar"

        assert application.resume_hint.cget("text") == "", "the hint rests during a run"

        application._toggle_pause()
        assert application._control.paused
        assert application.pause_button.cget("text") == RESUME_TEXT
        assert application.progress_label.cget("text") == "Paused."
        application._feed.on_bytes("VID_b.mp4", 300, 1000)  # a chunk already in flight
        application._poll_feed()
        application.update()
        assert application.progress_label.cget("text") == "Paused.", "no repaint while paused"
        application._toggle_pause()
        assert not application._control.paused
        assert application.pause_button.cget("text") == PAUSE_TEXT
        application._poll_feed()
        application.update()
        assert "VID_b.mp4" in application.progress_label.cget("text"), "resume repaints"

        application._cancel_download()
        application.update()
        assert application._control.cancelled
        assert application.pause_button.cget("state") == "disabled"
        assert application.cancel_button.cget("state") == "disabled"
        assert "Cancelling" in application.progress_label.cget("text")

        application._download_finished(Summary(total=161, downloaded=40, cancelled=True))
        application.update()
        assert application.progress_bar.winfo_manager() == "", "the bar hides after a run"
        assert not application._download_active
        assert application.start_button.cget("state") == "normal", "Start re-arms after the run"
        assert application.chat_button.cget("state") == "normal"
        assert application.pause_button.cget("text") == PAUSE_TEXT
        assert application.progress_label.cget("text").startswith("Cancelled: 161 items")
        assert "Start continues it" in application.resume_hint.cget("text"), "the hint returns"
        application.destroy()
    """,
    "settings": """
        import customtkinter as ctk
        from chronogram_tg.gui import settings as settings_module
        from chronogram_tg.gui.settings import CUSTOM_LABEL, SettingsWindow
        from chronogram_tg.naming import PIXEL_TEMPLATE, TELEGRAM_TEMPLATE

        root = ctk.CTk()
        root.withdraw()
        saved, logged_out = [], []
        window = SettingsWindow(
            root, TELEGRAM_TEMPLATE, on_save=saved.append, on_logout=lambda: logged_out.append(True)
        )
        root.update()
        assert window.preset_menu.get() == "Telegram", "the current template picks its preset"
        preview_text = window.preview_label.cget("text")
        assert "IMG_20240815_143022_000.jpg" in preview_text
        assert "VID_20240815_143022_000.mp4" in preview_text, "the video example shows {kind}"
        assert window.save_button.cget("state") == "disabled", "no changes yet: Save sleeps"

        window._preset_picked("Pixel")  # what the dropdown invokes
        root.update()
        assert window.template_value.get() == PIXEL_TEMPLATE
        assert "PXL_20240815_143022000.jpg" in window.preview_label.cget("text")
        assert window.save_button.cget("state") == "normal", "a change arms Save"

        window._preset_picked("Telegram")  # back to how the window opened
        root.update()
        assert window.save_button.cget("state") == "disabled", "back to the start: Save sleeps"

        window.template_value.set("{bad}")  # unknown token: inline error, Save sleeps
        root.update()
        assert "{bad}" in window.error_label.cget("text")
        assert window.save_button.cget("state") == "disabled"
        assert window.preview_label.cget("text") == ""
        assert window.preset_menu.get() == CUSTOM_LABEL

        window.template_value.set("{kind}-{date}")  # valid again
        root.update()
        assert window.error_label.cget("text") == ""
        assert window.save_button.cget("state") == "normal"
        window._save()
        root.update()
        assert saved == ["{kind}-{date}"]
        assert not window.winfo_exists(), "saving closes the window"

        window = SettingsWindow(
            root, TELEGRAM_TEMPLATE, on_save=saved.append, on_logout=lambda: logged_out.append(True)
        )
        root.update()
        settings_module.messagebox.askyesno = lambda *args, **kwargs: True
        window._confirm_logout()
        root.update()
        assert logged_out == [True]
        assert not window.winfo_exists(), "logging out closes the window"

        root.destroy()
    """,
    "date_range": """
        from datetime import UTC, datetime
        import customtkinter as ctk
        from chronogram_tg.gui.date_range import UNSET, DateRangeWindow

        def set_date(menus, day, month, year):
            for menu, value in zip(menus, (day, month, year)):
                menu.set(value)

        root = ctk.CTk()
        root.withdraw()
        accepted, closed = [], []
        window = DateRangeWindow(
            root, None, None,
            on_accept=lambda since, until: accepted.append((since, until)),
            on_close=lambda: closed.append(True),
        )
        root.update()
        assert all(menu.get() == UNSET for menu in window.from_menus), "starts unset"

        set_date(window.from_menus, "15", UNSET, "2024")  # half-set: inline error
        window._accept()
        root.update()
        assert "Complete the date" in window.error_label.cget("text")
        assert window.winfo_exists() and not accepted

        set_date(window.from_menus, "30", "February", "2023")  # impossible day
        window._accept()
        root.update()
        assert "not a real date" in window.error_label.cget("text")

        set_date(window.from_menus, "01", "June", "2023")
        set_date(window.to_menus, "01", "January", "2023")  # backwards
        window._accept()
        root.update()
        assert "on or before" in window.error_label.cget("text")

        set_date(window.to_menus, "31", "December", "2023")
        window._accept()
        root.update()
        assert accepted == [(datetime(2023, 6, 1, tzinfo=UTC), datetime(2023, 12, 31, tzinfo=UTC))]
        assert closed, "on_close must fire when the window goes away"

        root.destroy()
    """,
}


def main() -> int:
    failures = 0
    for name, body in SCENARIOS.items():
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(body)], capture_output=True, text=True
        )
        status = "ok" if result.returncode == 0 else "FAILED"
        print(f"{name}: {status}")
        if result.returncode != 0:
            failures += 1
            print(textwrap.indent(result.stderr.strip()[-800:], "    "))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
