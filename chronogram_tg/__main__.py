"""Entry point: ``python -m chronogram_tg``.

Subcommands are added as the plan progresses (chats, download); for now the
default action only checks that the credentials are readable.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import ConfigError, load_credentials


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
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)

    try:
        load_credentials()
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1

    print("Telegram credentials loaded.")
    print("The graphical interface is not implemented yet - see PLAN.md, task 6.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
