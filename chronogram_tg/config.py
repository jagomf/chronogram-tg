"""Credentials, file locations and persisted settings.

Nothing here ever prints or logs a credential value: errors point at the
``.env`` file instead. The Telethon session file is as sensitive as a
password, so its location is defined here but its contents are never read.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import dotenv_values

from .naming import TELEGRAM_TEMPLATE, TemplateError, validate_template

APP_NAME = "Chronogram TG"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def user_data_dir(platform: str | None = None, environ=None) -> Path:
    """The platform's folder for an app's own files (session, settings, log)."""
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    if platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if platform.startswith("win"):
        base = environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / APP_NAME
    base = environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_NAME


# Running from the source tree, everything lives next to the code, which is
# what a developer expects. A packaged app (PyInstaller sets sys.frozen)
# must not write inside its own bundle - macOS mounts it read-only - so its
# files live in the user's application-data folder instead.
if getattr(sys, "frozen", False):
    DATA_DIR = user_data_dir()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    DATA_DIR = PROJECT_ROOT

ENV_FILE = DATA_DIR / ".env"
SESSION_FILE = DATA_DIR / "chronogram.session"
SETTINGS_FILE = DATA_DIR / "settings.json"
LOG_FILE = DATA_DIR / "chronogram.log"

# The destination offered when none was ever chosen. Not created until a
# download actually starts. ~/Downloads exists on macOS, Windows and Linux.
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "Chronogram"

API_ID_KEY = "TELEGRAM_API_ID"
API_HASH_KEY = "TELEGRAM_API_HASH"

# naming.py owns the token vocabulary and the preset list; this is only the
# fallback used when no settings file exists yet.
DEFAULT_FILENAME_TEMPLATE = TELEGRAM_TEMPLATE

MISSING_CREDENTIALS_MESSAGE = """\
Telegram credentials not found.

Chronogram TG needs your own api_id and api_hash to talk to Telegram. They
are free and take about two minutes to get:

  1. Go to https://my.telegram.org and log in with your phone number.
  2. Open "API development tools" and fill in the form.
  3. Create a file named .env at the location shown below, containing:

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
    last_destination: str = ""  # preselected on the next launch; "" = never chosen


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
