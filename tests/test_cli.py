import pytest

from chronogram_tg.__main__ import build_parser, print_chats
from chronogram_tg.tg import Chat


def parse(argv):
    return build_parser().parse_args(argv)


def test_no_subcommand_is_allowed():
    assert parse([]).command is None


def test_chats_lists_fifty_by_default():
    arguments = parse(["chats"])

    assert (arguments.command, arguments.limit) == ("chats", 50)


def test_chats_limit_can_be_changed():
    assert parse(["chats", "--limit", "5"]).limit == 5


def test_version_exits_without_running_anything():
    with pytest.raises(SystemExit) as exited:
        parse(["--version"])

    assert exited.value.code == 0


def test_chats_are_printed_with_aligned_ids(capsys):
    print_chats(
        [
            Chat(id=7, title="Mum", kind="person"),
            Chat(id=123456, title="Family", kind="group"),
        ]
    )

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "     7  person   Mum"
    assert lines[1] == "123456  group    Family"
    assert "2 chats" in lines[-1]


def test_an_empty_chat_list_says_so_instead_of_printing_nothing(capsys):
    print_chats([])

    assert "No chats found." in capsys.readouterr().out
