"""Entry point: ``python -m chronogram_tg``.

The console subcommands exist to validate credentials and the download
pipeline before the graphical interface is built; they stay afterwards as a
way to diagnose problems without the GUI in the way.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from getpass import getpass
from pathlib import Path

from . import __version__
from .config import LOG_FILE, ConfigError, Credentials, load_credentials, load_settings
from .downloader import Summary, download_chat, human_size
from .metadata import detect_ffmpeg
from .tg import LoginError, TelegramError, TelegramSession

CODE_ATTEMPTS = 3


def utc_day(text: str) -> datetime:
    """Parse YYYY-MM-DD into midnight UTC, for argparse."""
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        raise argparse.ArgumentTypeError(f'"{text}" is not a date like 2024-08-15.') from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chronogram-tg",
        description="Rescue your Telegram photos and videos with their original dates.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Chronogram TG {__version__}",
    )
    subcommands = parser.add_subparsers(dest="command")

    chats = subcommands.add_parser(
        "chats",
        help="log in if needed and list your chats, most recent first",
    )
    chats.add_argument(
        "--limit",
        type=int,
        default=50,
        help="how many chats to list (default: 50)",
    )

    download = subcommands.add_parser(
        "download",
        help="download a chat's photos and videos with their original dates",
    )
    download.add_argument(
        "--chat",
        type=int,
        required=True,
        help="chat id, as printed by the chats command",
    )
    download.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="folder to download into (created if missing)",
    )
    download.add_argument(
        "--from",
        dest="since",
        type=utc_day,
        metavar="YYYY-MM-DD",
        help="only messages on or after this day (UTC)",
    )
    download.add_argument(
        "--to",
        dest="until",
        type=utc_day,
        metavar="YYYY-MM-DD",
        help="only messages on or before this day (UTC)",
    )
    download.add_argument(
        "--no-videos",
        action="store_true",
        help="skip videos even when ffmpeg is available",
    )
    download.add_argument(
        "--clean",
        action="store_true",
        help="delete this download's files from the destination first, "
        "then download everything again",
    )
    return parser


async def interactive_login(session: TelegramSession) -> None:
    """Log in from the console, asking only for what Telegram needs."""
    print("You need to log in to Telegram. This is only asked once.\n")
    while True:
        try:
            await session.send_code(input("Phone number (with country code): "))
            break
        except LoginError as error:
            print(f"{error}\n")

    print("Telegram has sent you a login code.")
    needs_password = False
    for attempt in range(1, CODE_ATTEMPTS + 1):
        try:
            needs_password = await session.sign_in_with_code(input("Login code: "))
            break
        except LoginError as error:
            if attempt == CODE_ATTEMPTS:
                raise
            print(f"{error}\n")

    while needs_password:
        try:
            await session.sign_in_with_password(
                getpass("Two-step verification password (not shown): ")
            )
            needs_password = False
        except LoginError as error:
            print(f"{error}\n")

    print("Logged in. The session is saved, so this will not be asked again.\n")


def print_chats(chats) -> None:
    if not chats:
        print("No chats found.")
        return
    width = max(len(str(chat.id)) for chat in chats)
    for chat in chats:
        print(f"{str(chat.id).rjust(width)}  {chat.kind:<7}  {chat.title}")
    print(f"\n{len(chats)} chats. Use the id on the left to download from one.")


def progress_percent(done: int, total: int) -> int:
    return (done * 100 + total - 1) // total if total else 100  # ceiling


def format_progress(done: int, total: int, name: str) -> str:
    line = f"{progress_percent(done, total):3d}%: {done} / {total}"
    return f"{line} - {name:.60}" if name else line


def taskbar_progress(percent: int | None) -> str:
    """OSC 9;4 - the taskbar-progress escape ConEmu introduced.

    Windows Terminal paints it on the app's taskbar icon; a few terminals
    (Ghostty, WezTerm) show it too; everything else, macOS Terminal
    included, silently ignores it. None clears the indicator.
    """
    if not sys.stdout.isatty():
        return ""
    if percent is None:
        return "\x1b]9;4;0;0\x07"
    return f"\x1b]9;4;1;{percent}\x07"


def print_summary(summary: Summary) -> None:
    print()
    if summary.cancelled:
        print("Cancelled. Run the same command again to resume where it left off.")
        print("(To start over from scratch instead, run it again with --clean.)")
    lines = [
        ("removed first by --clean", summary.cleaned),
        ("downloaded", summary.downloaded),
        ("already there from a previous run", summary.already_there),
        ("videos skipped", summary.videos_skipped),
        ("gone from the chat since the scan", summary.missing),
        ("dated by file time only", summary.dated_by_file_time_only),
    ]
    print(f"Done: {summary.total} items considered.")
    for label, count in lines:
        if count:
            print(f"  {count} {label}")
    if summary.errors:
        print(f"\n{len(summary.errors)} problems (the rest of the run was unaffected):")
        for problem in summary.errors:
            print(f"  - {problem}")


async def with_session(credentials: Credentials, action) -> None:
    session = TelegramSession(credentials)
    await session.connect()
    try:
        if not await session.is_authorized():
            await interactive_login(session)
        await action(session)
    finally:
        await session.disconnect()


async def run_chats(credentials: Credentials, limit: int) -> None:
    async def action(session):
        print_chats(await session.list_chats(limit))

    await with_session(credentials, action)


async def run_download(credentials: Credentials, arguments) -> None:
    if arguments.since and arguments.until and arguments.since > arguments.until:
        raise TelegramError("--from must be on or before --to.")
    until_exclusive = arguments.until + timedelta(days=1) if arguments.until else None

    include_videos = not arguments.no_videos
    if include_videos and detect_ffmpeg() is None:
        include_videos = False
        print("ffmpeg was not found, so videos will be skipped. See the README to add it.\n")

    counts = {"done": 0, "total": 0, "width": 0}

    def render(line: str, percent: int) -> None:
        # Pad to the widest line printed so far, so a shorter update fully
        # covers the remains of a longer one on the same terminal row.
        counts["width"] = max(counts["width"], len(line))
        padded = line.ljust(counts["width"])
        print(f"\r{padded}{taskbar_progress(percent)}", end="", flush=True)

    def show_progress(done: int, total: int, name: str) -> None:
        counts["done"], counts["total"] = done, total
        render(format_progress(done, total, name), progress_percent(done, total))

    def show_bytes(name: str, received: int | None, expected: int) -> None:
        # Movement while a single large file downloads, so a long video does
        # not look like a hang. None means "not known yet" - the download is
        # about to begin and may resume a partial file, so it renders as an
        # ellipsis rather than as a zero.
        if not expected:
            return
        got = "…" if received is None else human_size(received)
        current = min(counts["done"] + 1, counts["total"]) or 1
        line = (
            format_progress(current, counts["total"], name) + f" ({got} / {human_size(expected)})"
        )
        render(line, progress_percent(current, counts["total"]))

    def show_status(message: str) -> None:
        print(f"\n{message}")

    async def action(session):
        summary = await download_chat(
            session,
            arguments.chat,
            arguments.dest,
            load_settings().filename_template,
            since=arguments.since,
            until_exclusive=until_exclusive,
            include_videos=include_videos,
            clean=arguments.clean,
            on_progress=show_progress,
            on_status=show_status,
            on_bytes=show_bytes,
        )
        print_summary(summary)

    await with_session(credentials, action)


def configure_logging() -> None:
    """Send Telethon's operational log to a file instead of the console.

    Telethon warns about reconnects and auth-key retries while downloading;
    harmless, but printed to the console they tear through the progress
    line. The file keeps them for diagnosis.
    """
    telethon_logger = logging.getLogger("telethon")
    if telethon_logger.handlers:
        return
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    telethon_logger.addHandler(handler)
    telethon_logger.setLevel(logging.WARNING)
    telethon_logger.propagate = False


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    configure_logging()

    try:
        credentials = load_credentials()
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1

    if arguments.command is None:
        print("Telegram credentials loaded.")
        print("The graphical interface is not implemented yet - see PLAN.md, task 6.")
        print("Meanwhile, try: python -m chronogram_tg chats")
        return 0

    try:
        if arguments.command == "chats":
            asyncio.run(run_chats(credentials, arguments.limit))
        else:
            asyncio.run(run_download(credentials, arguments))
    except TelegramError as error:
        print(f"\n{error}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print(
            "\nCancelled. Run the same command again to resume, or add --clean "
            "to start over from scratch.",
            file=sys.stderr,
        )
        return 1
    finally:
        print(taskbar_progress(None), end="", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
