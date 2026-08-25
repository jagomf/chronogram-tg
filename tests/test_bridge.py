import asyncio

import pytest

from chronogram_tg.gui.bridge import TelegramBridge


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
