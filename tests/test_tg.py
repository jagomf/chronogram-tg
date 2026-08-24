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


def test_a_saved_takeout_id_survives_reloading_the_session(tmp_path):
    # Telethon 1.44.0 writes takeout_id and tmp_auth_key in swapped columns,
    # so a plain SQLiteSession loads a saved id back as an empty blob and
    # then destroys it on the next write. RepairedSQLiteSession undoes that.
    from chronogram_tg.tg import RepairedSQLiteSession

    path = str(tmp_path / "takeout.session")
    first = RepairedSQLiteSession(path)
    first.takeout_id = 123456789
    first.close()

    second = RepairedSQLiteSession(path)
    try:
        assert second.takeout_id == 123456789
    finally:
        second.close()


def test_a_session_that_never_had_a_takeout_loads_as_none(tmp_path):
    from chronogram_tg.tg import RepairedSQLiteSession

    path = str(tmp_path / "fresh.session")
    first = RepairedSQLiteSession(path)
    first.takeout_id = None
    first.close()

    second = RepairedSQLiteSession(path)
    try:
        assert second.takeout_id is None
    finally:
        second.close()


MOMENT = __import__("datetime").datetime(2024, 8, 15, 14, 30, 22, tzinfo=__import__("datetime").UTC)


def media_message(*, photo=None, document=None, size=None, message_id=7):
    return SimpleNamespace(
        id=message_id,
        date=MOMENT,
        photo=photo,
        document=document,
        file=SimpleNamespace(size=size) if size is not None else None,
    )


def test_a_photo_message_reports_its_size():
    from chronogram_tg.tg import PHOTO_KIND, describe_media

    record = describe_media(media_message(photo=object(), size=123456))

    assert (record.kind, record.extension, record.size) == (PHOTO_KIND, "jpg", 123456)


def test_a_sticker_is_not_worth_rescuing():
    from telethon.tl.types import DocumentAttributeSticker

    from chronogram_tg.tg import describe_media

    sticker = SimpleNamespace(
        mime_type="image/webp",
        attributes=[DocumentAttributeSticker(alt="", stickerset=None)],
    )

    assert describe_media(media_message(document=sticker, size=999)) is None


def test_a_video_document_takes_its_extension_from_its_filename():
    from telethon.tl.types import DocumentAttributeFilename

    from chronogram_tg.tg import VIDEO_KIND, describe_media

    clip = SimpleNamespace(
        mime_type="video/quicktime",
        attributes=[DocumentAttributeFilename(file_name="holiday.MOV")],
    )
    record = describe_media(media_message(document=clip, size=5_000_000))

    assert (record.kind, record.extension, record.size) == (VIDEO_KIND, "MOV", 5_000_000)
