"""Entry point: ``python -m chronogram_tg``.

The console subcommands exist to validate credentials and the download
pipeline before the graphical interface is built; they stay afterwards as a
way to diagnose problems without the GUI in the way.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from getpass import getpass

from . import __version__
from .config import ConfigError, Credentials, load_credentials
from .tg import LoginError, TelegramError, TelegramSession

CODE_ATTEMPTS = 3


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


async def run_chats(credentials: Credentials, limit: int) -> None:
    session = TelegramSession(credentials)
    await session.connect()
    try:
        if not await session.is_authorized():
            await interactive_login(session)
        print_chats(await session.list_chats(limit))
    finally:
        await session.disconnect()


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
        asyncio.run(run_chats(credentials, arguments.limit))
    except TelegramError as error:
        print(error, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
