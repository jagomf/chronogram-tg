import asyncio
from concurrent.futures import Future

import pytest

from chronogram_tg.gui.bridge import TelegramBridge, poll_future


class FakeWidget:
    """Stands in for a Tk widget: collects `after` callbacks to run by hand."""

    def __init__(self):
        self.scheduled = []

    def after(self, _delay_ms, callback):
        self.scheduled.append(callback)

    def run_scheduled(self):
        callbacks, self.scheduled = self.scheduled, []
        for callback in callbacks:
            callback()


@pytest.fixture
def bridge():
    bridge = TelegramBridge()
    bridge.start()
    yield bridge
    bridge.stop()


def test_a_submitted_coroutine_runs_and_returns_its_result(bridge):
    async def add(a, b):
        await asyncio.sleep(0)
        return a + b

    assert bridge.submit(add(2, 3)).result(timeout=5) == 5


def test_an_exception_travels_back_through_the_future(bridge):
    async def boom():
        raise ValueError("told you")

    with pytest.raises(ValueError, match="told you"):
        bridge.submit(boom()).result(timeout=5)


def test_work_runs_off_the_calling_thread(bridge):
    import threading

    async def whoami():
        return threading.current_thread().name

    assert bridge.submit(whoami()).result(timeout=5) == "telegram-loop"


def test_stop_ends_the_thread_and_is_idempotent():
    bridge = TelegramBridge()
    bridge.start()
    assert bridge.running

    bridge.stop()
    bridge.stop()

    assert not bridge.running


def test_submitting_after_stop_is_a_clear_error():
    bridge = TelegramBridge()
    bridge.start()
    bridge.stop()

    async def anything():
        return 1

    with pytest.raises(RuntimeError, match="not running"):
        bridge.submit(anything())


def test_poll_future_delivers_the_result_from_the_widget_side():
    widget, future, seen = FakeWidget(), Future(), []
    poll_future(widget, future, seen.append)

    widget.run_scheduled()  # not done yet: re-schedules itself
    assert seen == []

    future.set_result("hello")
    widget.run_scheduled()
    assert seen == ["hello"]


def test_poll_future_routes_exceptions_to_the_error_callback():
    widget, future, problems = FakeWidget(), Future(), []
    poll_future(widget, future, on_result=lambda _: None, on_error=problems.append)

    future.set_exception(ValueError("boom"))
    widget.run_scheduled()

    assert len(problems) == 1 and str(problems[0]) == "boom"


def test_poll_future_without_error_callback_reraises():
    widget, future = FakeWidget(), Future()
    poll_future(widget, future, on_result=lambda _: None)
    future.set_exception(ValueError("unhandled"))

    with pytest.raises(ValueError, match="unhandled"):
        widget.run_scheduled()
