import asyncio
from types import SimpleNamespace

import pytest

from chronogram_tg.config import Credentials
from chronogram_tg.tg import (
    Chat,
    LoginError,
    TelegramError,
    TelegramSession,
    _flood_wait_message,
    describe_dialog,
)


def dialog(name="Mum", *, is_group=False, is_channel=False, bot=False, chat_id=42):
    return SimpleNamespace(
        id=chat_id,
        name=name,
        is_group=is_group,
        is_channel=is_channel,
        entity=SimpleNamespace(bot=bot),
    )


def test_a_private_chat_is_a_person():
    assert describe_dialog(dialog()) == Chat(id=42, title="Mum", kind="person")


def test_a_bot_is_not_reported_as_a_person():
    assert describe_dialog(dialog(name="BotFather", bot=True)).kind == "bot"


def test_a_broadcast_channel_is_a_channel():
    assert describe_dialog(dialog(is_channel=True)).kind == "channel"


def test_a_supergroup_is_a_group_even_though_telegram_calls_it_a_channel():
    # Telethon reports megagroups as both; the group answer is the useful one.
    assert describe_dialog(dialog(is_group=True, is_channel=True)).kind == "group"


@pytest.mark.parametrize("name", ["", "   ", None])
def test_a_nameless_chat_still_gets_a_title(name):
    assert describe_dialog(dialog(name=name)).title == "(no name)"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(45, "45 s"), (90, "1 min 30 s"), (3600, "60 min 0 s")],
)
def test_flood_wait_is_explained_in_readable_units(seconds, expected):
    message = _flood_wait_message(SimpleNamespace(seconds=seconds))

    assert expected in message


def session():
    return TelegramSession(Credentials(api_id=1, api_hash="unused"), session_file="unused")


def test_using_the_client_before_connecting_is_a_clear_error():
    with pytest.raises(TelegramError, match="Not connected"):
        _ = session().client


def test_submitting_a_code_that_was_never_requested_is_rejected():
    with pytest.raises(LoginError, match="Ask for a login code"):
        asyncio.run(session().sign_in_with_code("12345"))


@pytest.mark.parametrize("phone", ["", "   "])
def test_an_empty_phone_number_is_rejected_before_calling_telegram(phone):
    with pytest.raises(LoginError, match="country code"):
        asyncio.run(session().send_code(phone))
