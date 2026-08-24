"""Entry point: ``python -m chronogram_tg``.

The console subcommands exist to validate credentials and the download
pipeline before the graphical interface is built; they stay afterwards as a
way to diagnose problems without the GUI in the way.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from getpass import getpass
from pathlib import Path

from . import __version__
from .config import ConfigError, Credentials, load_credentials, load_settings
from .downloader import Summary, download_chat
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


def print_summary(summary: Summary) -> None:
    print()
    if summary.cancelled:
        print("Cancelled. Run the same command again to resume where it left off.")
        print("(To start over from scratch instead, empty the destination folder first.)")
    lines = [
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

    def show_progress(done: int, total: int, name: str) -> None:
        print(f"\r{done} / {total}  {name:<40.40}", end="", flush=True)

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
            on_progress=show_progress,
            on_status=show_status,
        )
        print_summary(summary)

    await with_session(credentials, action)


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)

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
            "\nCancelled. Run the same command again to resume, or empty the "
            "destination folder first to start over from scratch.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
