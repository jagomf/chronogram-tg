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
        assert application.progress_bar.get() == 0
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
