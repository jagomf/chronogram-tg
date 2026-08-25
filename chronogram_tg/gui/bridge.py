"""One asyncio loop in a background thread, for all Telethon work.

Telethon is asyncio and Tk has its own blocking mainloop; the standard
answer is to give the network its own thread-with-loop and cross the gap
explicitly. GUI code submits coroutines here and gets a Future back;
results are marshalled back to the interface with `widget.after`, never by
touching widgets from this thread.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from concurrent.futures import Future


class TelegramBridge:
    """Owns the background loop. start() it once, stop() it on shutdown."""

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="telegram-loop", daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self) -> None:
        self._thread.start()

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and self._loop.is_running()

    def submit(self, coroutine: Coroutine) -> Future:
        """Run a coroutine on the Telegram loop; the Future carries the result."""
        if not self._thread.is_alive():
            coroutine.close()  # avoid the never-awaited warning
            raise RuntimeError("The Telegram thread is not running.")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the loop and wait for the thread. Safe to call twice."""
        if self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout)
        if not self._loop.is_closed():
            self._loop.close()
