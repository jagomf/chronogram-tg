"""The picker's pure logic; the widgets themselves live in smoke_gui.py."""

import pytest

from chronogram_tg.gui.chat_picker import (
    KIND_EMOJI,
    KIND_FILTERS,
    MAX_TITLE_CHARS,
    ellipsise,
    filter_chats,
)
from chronogram_tg.tg import Chat

CHATS = [
    Chat(id=1, title="Mum", kind="person"),
    Chat(id=2, title="Family group", kind="group"),
    Chat(id=3, title="Family news", kind="channel"),
    Chat(id=4, title="ReminderBot", kind="bot"),
]


def titles(chats):
    return [chat.title for chat in chats]


def test_no_needle_and_no_kind_shows_everything():
    assert filter_chats(CHATS, "", None) == CHATS


def test_the_needle_is_a_case_insensitive_substring():
    assert titles(filter_chats(CHATS, "  FAM ", None)) == ["Family group", "Family news"]


def test_a_kind_pill_narrows_by_kind():
    assert titles(filter_chats(CHATS, "", "person")) == ["Mum"]


def test_needle_and_kind_combine():
    assert titles(filter_chats(CHATS, "fam", "channel")) == ["Family news"]
    assert filter_chats(CHATS, "fam", "bot") == []


def test_every_pill_maps_to_a_real_kind_or_to_all():
    assert list(KIND_FILTERS)[0] == "All" and KIND_FILTERS["All"] is None
    assert set(KIND_FILTERS.values()) == {None, "person", "group", "channel", "bot"}


def test_every_chat_kind_has_its_emoji():
    # The kinds tg.describe_dialog can produce.
    assert set(KIND_EMOJI) == {"person", "group", "bot", "channel"}


def test_a_short_title_is_left_alone():
    assert ellipsise("Mum") == "Mum"


def test_a_long_title_is_cut_with_an_ellipsis():
    long_title = "A chat name so long it would push the kind marker out of sight"

    shortened = ellipsise(long_title)

    assert shortened.endswith("…")
    assert len(shortened) <= MAX_TITLE_CHARS


def test_the_cut_does_not_leave_a_trailing_space():
    title = "exactly at the boundary " + "x" * MAX_TITLE_CHARS

    assert "  …" not in ellipsise(title) and " …" not in ellipsise(title)


@pytest.mark.parametrize("length", [MAX_TITLE_CHARS, MAX_TITLE_CHARS - 1, 1, 0])
def test_titles_up_to_the_limit_are_untouched(length):
    title = "x" * length

    assert ellipsise(title) == title
