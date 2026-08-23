"""Credentials, file locations and persisted settings.

Nothing here ever prints or logs a credential value: errors point at the
``.env`` file instead. The Telethon session file is as sensitive as a
password, so its location is defined here but its contents are never read.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import dotenv_values

from .naming import PIXEL_TEMPLATE, TemplateError, validate_template

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
SESSION_FILE = PROJECT_ROOT / "chronogram.session"
SETTINGS_FILE = PROJECT_ROOT / "settings.json"

API_ID_KEY = "TELEGRAM_API_ID"
API_HASH_KEY = "TELEGRAM_API_HASH"

# naming.py owns the token vocabulary and the preset list; this is only the
# fallback used when no settings file exists yet.
DEFAULT_FILENAME_TEMPLATE = PIXEL_TEMPLATE

MISSING_CREDENTIALS_MESSAGE = """\
Telegram credentials not found.

Chronogram TG needs your own api_id and api_hash to talk to Telegram. They
are free and take about two minutes to get:

  1. Go to https://my.telegram.org and log in with your phone number.
  2. Open "API development tools" and fill in the form.
  3. Create a file named .env in the project folder containing:

         TELEGRAM_API_ID=1234567
         TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef

     (There is an .env.example file you can copy and edit.)

Expected location: {env_file}

See the "Get your Telegram API credentials" section of README.md for the
step-by-step version."""


class ConfigError(Exception):
    """The app cannot start because configuration is missing or invalid.

    The message is written for the user and is meant to be shown as-is,
    without a traceback.
    """


@dataclass(frozen=True)
class Credentials:
    api_id: int
    api_hash: str


@dataclass
class Settings:
    """User preferences that survive between runs."""

    filename_template: str = DEFAULT_FILENAME_TEMPLATE


def load_credentials(env_file: Path | str | None = None) -> Credentials:
    """Read the Telegram credentials, preferring real environment variables.

    Raises ConfigError with a user-facing message when they are missing or
    malformed.
    """
    env_path = ENV_FILE if env_file is None else Path(env_file)
    values = dict(dotenv_values(env_path)) if env_path.is_file() else {}
    for key in (API_ID_KEY, API_HASH_KEY):
        from_environment = os.environ.get(key)
        if from_environment:
            values[key] = from_environment

    api_id_raw = (values.get(API_ID_KEY) or "").strip()
    api_hash = (values.get(API_HASH_KEY) or "").strip()
    if not api_id_raw or not api_hash:
        raise ConfigError(MISSING_CREDENTIALS_MESSAGE.format(env_file=env_path))
    if not api_id_raw.isdigit():
        raise ConfigError(
            f"{API_ID_KEY} must be the number shown at my.telegram.org, "
            f'but {env_path} has "{api_id_raw}". Check that you did not swap '
            f"it with {API_HASH_KEY}."
        )
    return Credentials(api_id=int(api_id_raw), api_hash=api_hash)


def load_settings(path: Path | str | None = None) -> Settings:
    """Read persisted settings, falling back to defaults.

    A missing, unreadable or corrupt file is not an error: preferences are
    replaceable, and refusing to start over them would be unhelpful.
    """
    settings_path = SETTINGS_FILE if path is None else Path(path)
    try:
        stored = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(stored, dict):
        return Settings()

    known = {field: stored[field] for field in Settings.__dataclass_fields__ if field in stored}
    settings = Settings(**{k: v for k, v in known.items() if isinstance(v, str)})
    try:
        # A hand-edited file could hold a pattern the app cannot use. Falling
        # back beats failing later, halfway through a download.
        validate_template(settings.filename_template)
    except TemplateError:
        settings.filename_template = DEFAULT_FILENAME_TEMPLATE
    return settings


def save_settings(settings: Settings, path: Path | str | None = None) -> None:
    settings_path = SETTINGS_FILE if path is None else Path(path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
