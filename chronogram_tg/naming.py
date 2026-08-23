"""Deterministic filenames derived from the date of the message.

Determinism is the point: the same messages, in the same order, must always
produce the same names regardless of what is already on disk. That is what
lets an interrupted download resume by simply skipping the files it finds
(decision D11). Nothing here may depend on the clock, on randomness or on
the destination folder's contents.

All times are UTC (decision D15); Telegram already reports them that way.
"""

from __future__ import annotations

import string
from datetime import UTC, datetime

DATE_TOKEN = "date"
TIME_TOKEN = "time"
MS_TOKEN = "ms"
TOKENS = (DATE_TOKEN, TIME_TOKEN, MS_TOKEN)

PIXEL_TEMPLATE = "PXL_{date}_{time}{ms}"
GENERIC_TEMPLATE = "IMG_{date}_{time}{ms}"
PLAIN_TEMPLATE = "{date}_{time}{ms}"

# Shown in the settings dropdown, in this order. The first one is the default.
PRESETS: dict[str, str] = {
    "Pixel": PIXEL_TEMPLATE,
    "Generic IMG": GENERIC_TEMPLATE,
    "Plain date": PLAIN_TEMPLATE,
}

# Fixed sample for the live preview, so the preview never moves on its own.
SAMPLE_MOMENT = datetime(2024, 8, 15, 14, 30, 22, tzinfo=UTC)
SAMPLE_EXTENSION = "jpg"

FALLBACK_EXTENSION = "bin"

# Windows rejects these in a filename. Forbidden on every platform so the
# downloads stay portable: the files are meant to be copied to a phone.
ILLEGAL_CHARACTERS = frozenset('\\/:*?"<>|')

# Windows still refuses these names, with or without an extension.
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in range(1, 10)}
    | {f"LPT{digit}" for digit in range(1, 10)}
)

TOKEN_HELP = "Available tokens: {date}, {time}, {ms}."


class TemplateError(ValueError):
    """The filename pattern is unusable.

    The message is written for the user and is shown next to the pattern
    field in the settings dialog.
    """


def validate_template(template: str) -> None:
    """Raise TemplateError if `template` cannot produce portable filenames."""
    if not template.strip():
        raise TemplateError(f"The filename pattern cannot be empty. {TOKEN_HELP}")
    if template != template.strip():
        raise TemplateError("The filename pattern cannot start or end with a space.")

    try:
        fields = [field for _, field, _, _ in string.Formatter().parse(template)]
    except ValueError as error:
        raise TemplateError(
            "The pattern has an unmatched { or }. To write a real brace, double it: {{ or }}."
        ) from error

    if "" in fields:
        raise TemplateError(f"Write the name of the token inside the braces. {TOKEN_HELP}")
    unknown = sorted({field for field in fields if field and field not in TOKENS})
    if unknown:
        spelled = ", ".join(f"{{{field}}}" for field in unknown)
        raise TemplateError(f"Unknown token {spelled}. {TOKEN_HELP}")

    illegal = sorted(ILLEGAL_CHARACTERS.intersection(template))
    if illegal:
        raise TemplateError(
            f"The pattern cannot contain {' '.join(illegal)} - "
            f"those characters are not allowed in filenames."
        )
    if any(character < " " for character in template):
        raise TemplateError("The pattern cannot contain control characters.")
    if template.endswith("."):
        raise TemplateError("The pattern cannot end with a dot.")

    stem = _render(template, SAMPLE_MOMENT, 0)
    if stem.upper() in RESERVED_NAMES:
        raise TemplateError(f'"{stem}" is a name Windows reserves. Add something to it.')


def _render(template: str, moment: datetime, milliseconds: int) -> str:
    moment = moment.astimezone(UTC) if moment.tzinfo else moment
    try:
        return template.format(
            **{
                DATE_TOKEN: moment.strftime("%Y%m%d"),
                TIME_TOKEN: moment.strftime("%H%M%S"),
                MS_TOKEN: f"{milliseconds:03d}",
            }
        )
    except (KeyError, IndexError, ValueError) as error:
        raise TemplateError(f"The filename pattern is not usable. {TOKEN_HELP}") from error


def normalise_extension(extension: str) -> str:
    """Turn whatever the media reports into a safe, lowercase extension."""
    cleaned = extension.strip().lstrip(".").lower()
    cleaned = "".join(c for c in cleaned if c not in ILLEGAL_CHARACTERS and c >= " ")
    return cleaned or FALLBACK_EXTENSION


def preview(template: str, extension: str = SAMPLE_EXTENSION) -> str:
    """Render the settings dialog's live example. Raises TemplateError."""
    validate_template(template)
    return f"{_render(template, SAMPLE_MOMENT, 0)}.{normalise_extension(extension)}"


class NameAllocator:
    """Hands out unique filenames for a run, in message order.

    Telegram dates are only precise to the second, so items sharing a second
    are told apart by a millisecond counter that runs 000, 001, 002... in the
    order the messages are handed over. Patterns without `{ms}` fall back to
    a numeric suffix, so a pattern can never silently overwrite a file.
    """

    def __init__(self, template: str):
        validate_template(template)
        self._template = template
        self._counter_by_second: dict[str, int] = {}
        self._used: set[str] = set()

    def allocate(self, moment: datetime, extension: str) -> str:
        second = moment.astimezone(UTC) if moment.tzinfo else moment
        key = second.strftime("%Y%m%d%H%M%S")
        index = self._counter_by_second.get(key, 0)
        self._counter_by_second[key] = index + 1

        stem = _render(self._template, moment, min(index, 999))
        name = f"{stem}.{normalise_extension(extension)}"
        # Case-insensitive: macOS and Windows would treat A.JPG and a.jpg as
        # the same file, and the destination is usually one of the two.
        if name.lower() in self._used:
            name = self._disambiguate(stem, normalise_extension(extension))
        self._used.add(name.lower())
        return name

    def _disambiguate(self, stem: str, extension: str) -> str:
        suffix = 2
        while f"{stem}_{suffix}.{extension}".lower() in self._used:
            suffix += 1
        return f"{stem}_{suffix}.{extension}"
