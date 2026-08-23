"""Telegram access, wrapped so the rest of the app never imports Telethon.

The login is exposed as separate steps (`send_code`, `sign_in_with_code`,
`sign_in_with_password`) rather than one blocking helper, because the GUI
drives them one window at a time later on. Telethon errors are translated
into `TelegramError`, whose message is written for the user and can be shown
as-is in a console or a dialog.

The session file this creates grants full access to the Telegram account.
Nothing here ever logs its contents or the credentials.
"""

from __future__ import annotations

from dataclasses import dataclass

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from .config import SESSION_FILE, Credentials


class TelegramError(Exception):
    """Something went wrong talking to Telegram.

    The message is meant to be shown to the user as-is.
    """


class LoginError(TelegramError):
    """The user can fix this by retrying the step (bad code, bad password)."""


@dataclass(frozen=True)
class Chat:
    """A chat the user can download from."""

    id: int
    title: str
    kind: str  # person | bot | group | channel


def describe_dialog(dialog) -> Chat:
    """Turn a Telethon dialog into the plain record the rest of the app uses."""
    if getattr(dialog, "is_group", False):
        kind = "group"
    elif getattr(dialog, "is_channel", False):
        kind = "channel"
    elif getattr(getattr(dialog, "entity", None), "bot", False):
        kind = "bot"
    else:
        kind = "person"
    title = (getattr(dialog, "name", None) or "").strip() or "(no name)"
    return Chat(id=dialog.id, title=title, kind=kind)


def _flood_wait_message(error: FloodWaitError) -> str:
    minutes, seconds = divmod(int(error.seconds), 60)
    spelled = f"{minutes} min {seconds} s" if minutes else f"{seconds} s"
    return f"Telegram is rate-limiting this account and asks to wait {spelled} before trying again."


class TelegramSession:
    """A connected Telethon client with an explicit, step-by-step login."""

    def __init__(self, credentials: Credentials, session_file=SESSION_FILE):
        self._credentials = credentials
        self._session_file = str(session_file)
        self._client: TelegramClient | None = None
        self._phone: str | None = None
        self._code_hash: str | None = None

    @property
    def client(self) -> TelegramClient:
        if self._client is None:
            raise TelegramError("Not connected to Telegram yet.")
        return self._client

    async def connect(self) -> None:
        self._client = TelegramClient(
            self._session_file,
            self._credentials.api_id,
            self._credentials.api_hash,
        )
        try:
            await self._client.connect()
        except OSError as error:
            self._client = None
            raise TelegramError(
                f"Could not reach Telegram ({error}). Check your internet connection."
            ) from error

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def is_authorized(self) -> bool:
        return await self.client.is_user_authorized()

    async def send_code(self, phone: str) -> None:
        """Ask Telegram to send the login code to `phone`."""
        phone = phone.strip()
        if not phone:
            raise LoginError("Enter your phone number, including the country code.")
        try:
            sent = await self.client.send_code_request(phone)
        except PhoneNumberInvalidError as error:
            raise LoginError(
                f'"{phone}" is not a valid phone number. Include the country '
                f"code, for example +34600112233."
            ) from error
        except ApiIdInvalidError as error:
            raise TelegramError(
                "Telegram rejected the api_id/api_hash pair. Check the values "
                "in your .env file against my.telegram.org."
            ) from error
        except FloodWaitError as error:
            raise TelegramError(_flood_wait_message(error)) from error
        self._phone = phone
        self._code_hash = sent.phone_code_hash

    async def sign_in_with_code(self, code: str) -> bool:
        """Finish the login with the code. Returns True if 2FA is still needed."""
        if self._phone is None or self._code_hash is None:
            raise LoginError("Ask for a login code before sending one.")
        try:
            await self.client.sign_in(
                phone=self._phone,
                code=code.strip(),
                phone_code_hash=self._code_hash,
            )
        except SessionPasswordNeededError:
            return True
        except PhoneCodeInvalidError as error:
            raise LoginError("That code is not correct. Try again.") from error
        except PhoneCodeExpiredError as error:
            self._code_hash = None
            raise LoginError("That code has expired. Ask for a new one.") from error
        except FloodWaitError as error:
            raise TelegramError(_flood_wait_message(error)) from error
        return False

    async def sign_in_with_password(self, password: str) -> None:
        """Complete a login that requires the two-step verification password."""
        try:
            await self.client.sign_in(password=password)
        except PasswordHashInvalidError as error:
            raise LoginError("That password is not correct. Try again.") from error
        except FloodWaitError as error:
            raise TelegramError(_flood_wait_message(error)) from error

    async def list_chats(self, limit: int | None = 50) -> list[Chat]:
        """List the most recent chats, most recently active first."""
        try:
            return [describe_dialog(d) async for d in self.client.iter_dialogs(limit=limit)]
        except FloodWaitError as error:
            raise TelegramError(_flood_wait_message(error)) from error

    async def log_out(self) -> None:
        """End the session on Telegram's side and delete the local session file."""
        await self.client.log_out()
        self._client = None
