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


def test_progress_shows_percentage_then_counter():
    from chronogram_tg.__main__ import format_progress

    assert format_progress(347, 1520, "IMG_x.jpg") == " 23%: 347 / 1520 - IMG_x.jpg"
    assert format_progress(1520, 1520, "IMG_x.jpg") == "100%: 1520 / 1520 - IMG_x.jpg"
    assert format_progress(1, 1520, "IMG_x.jpg") == "  1%: 1 / 1520 - IMG_x.jpg"
    assert format_progress(0, 1520, "IMG_x.jpg") == "  0%: 0 / 1520 - IMG_x.jpg"


def test_the_baseline_tick_has_no_dangling_separator():
    from chronogram_tg.__main__ import format_progress

    assert format_progress(0, 161, "") == "  0%: 0 / 161"


def test_telethon_logging_goes_to_a_file_not_the_console():
    import logging

    from chronogram_tg.__main__ import configure_logging

    configure_logging()
    configure_logging()  # a second call must not stack handlers

    telethon_logger = logging.getLogger("telethon")
    assert telethon_logger.propagate is False
    assert len(telethon_logger.handlers) == 1
    assert isinstance(telethon_logger.handlers[0], logging.FileHandler)
