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

import mimetypes
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
    TakeoutInitDelayError,
    TakeoutInvalidError,
    UnauthorizedError,
)
from telethon.sessions import SQLiteSession
from telethon.tl.types import (
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    InputMessagesFilterDocument,
    InputMessagesFilterPhotoVideo,
)

from .config import SESSION_FILE, Credentials

PHOTO_KIND = "photo"
IMAGE_DOCUMENT_KIND = "image_document"
VIDEO_KIND = "video"

# Generous cap so no family video is left out of the takeout scope.
TAKEOUT_MAX_FILE_SIZE = 4 * 1024**3

# Telegram requires download offsets to be multiples of 4 KiB. A partial
# file is truncated down to this boundary and continued from there.
DOWNLOAD_OFFSET_ALIGN = 4096

# Preferred over mimetypes for the formats Telegram actually sends, so the
# extension does not depend on the operating system's mime registry.
KNOWN_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/heic": "heic",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}


class RepairedSQLiteSession(SQLiteSession):
    """Works around a takeout_id/tmp_auth_key column swap in Telethon 1.44.0.

    Telethon's session writer puts `takeout_id` in one column and its loader
    reads it from another. The consequences escalate: a session that never
    had a takeout loads a phantom empty blob as its takeout id (which then
    breaks every takeout request), and if a real id ever reaches the row,
    the next load crashes trying to build an AuthKey out of an integer. So
    the sqlite row cannot be trusted with the takeout id at all: this class
    keeps it in a sidecar file next to the session and always writes None
    into the row. Fixed upstream on 2026-08-19 (codeberg.org/Lonami/Telethon
    commit b6a451e, after v1.44.0): remove this class when bumping to the
    first release that contains it.
    """

    def __init__(self, session_id=None):
        super().__init__(session_id)
        self._sidecar = Path(self.filename + ".takeout")
        self._takeout_id = None  # ignore the row's phantom value
        if self._sidecar.exists():
            try:
                self._takeout_id = int(self._sidecar.read_text().strip())
            except ValueError:
                self._takeout_id = None

    @property
    def takeout_id(self):
        return self._takeout_id

    @takeout_id.setter
    def takeout_id(self, value):
        self._takeout_id = value
        if value is None:
            self._sidecar.unlink(missing_ok=True)
        else:
            self._sidecar.write_text(str(value))

    def _update_session_table(self):
        # Never let the id touch the row - Telethon would store it in the
        # tmp-key column and crash the next load.
        remembered = self._takeout_id
        self._takeout_id = None
        try:
            super()._update_session_table()
        finally:
            self._takeout_id = remembered

    def delete(self):
        # Logging out deletes the session file; the sidecar goes with it,
        # or the next login would resume a takeout of the wrong account.
        self._sidecar.unlink(missing_ok=True)
        return super().delete()


class TelegramError(Exception):
    """Something went wrong talking to Telegram.

    The message is meant to be shown to the user as-is.
    """


class LoginError(TelegramError):
    """The user can fix this by retrying the step (bad code, bad password)."""


class SessionRevokedError(TelegramError):
    """Telegram stopped accepting the session mid-flight (signed out remotely)."""


REVOKED_MESSAGE = (
    "Telegram no longer accepts this session - it was probably closed from "
    "another device. Log in again to continue."
)


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
            RepairedSQLiteSession(self._session_file),
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
        except UnauthorizedError as error:
            raise SessionRevokedError(REVOKED_MESSAGE) from error

    async def log_out(self) -> None:
        """End the session on Telegram's side and delete the local session file."""
        await self.client.log_out()
        self._client = None

    async def scan_media(
        self,
        chat_id: int,
        since: datetime | None = None,
        until_exclusive: datetime | None = None,
    ) -> list[MediaRecord]:
        """List the chat's photos and videos, oldest first.

        Uses Telegram's server-side media filters instead of walking every
        message, so scanning a years-long chat costs a handful of requests.
        Two filters are needed because "photos and videos" does not include
        images sent as files; the results are merged and ordered by message
        id, which grows chronologically - a deterministic order is what keeps
        the allocated filenames stable between runs (D11).
        """
        found: dict[int, MediaRecord] = {}
        try:
            for media_filter in (InputMessagesFilterPhotoVideo(), InputMessagesFilterDocument()):
                async for message in self.client.iter_messages(
                    chat_id, filter=media_filter, offset_date=until_exclusive
                ):
                    if since is not None and message.date < since:
                        break
                    record = describe_media(message)
                    if record is not None:
                        found[record.message_id] = record
        except FloodWaitError as error:
            raise TelegramError(_flood_wait_message(error)) from error
        except UnauthorizedError as error:
            raise SessionRevokedError(REVOKED_MESSAGE) from error
        except ValueError as error:
            raise TelegramError(
                f"Chat {chat_id} was not found. Run the chats command and use "
                f"one of the ids it prints."
            ) from error
        return sorted(found.values(), key=lambda record: record.message_id)

    @asynccontextmanager
    async def takeout_downloads(self):
        """Open (or resume) a takeout session and yield a MediaDownloads.

        Takeout is Telegram's blessed channel for bulk exports (D10). It is
        deliberately not finalized on exit: the takeout id lives in the
        session file, so an interrupted rescue resumes into the same export
        instead of asking Telegram to authorise a new one every run. The
        scope arguments may only be sent when *initiating* an export -
        Telethon refuses them while one is already open - so reconnecting to
        an existing takeout must ask for it with no arguments at all.
        """
        if self.client.session.takeout_id is None:
            takeout = self.client.takeout(
                finalize=False,
                users=True,
                chats=True,
                megagroups=True,
                channels=True,
                files=True,
                max_file_size=TAKEOUT_MAX_FILE_SIZE,
            )
        else:
            takeout = self.client.takeout(finalize=False)
        try:
            async with takeout as proxy:
                yield MediaDownloads(self.client, proxy)
        except TakeoutInitDelayError as error:
            hours = max(1, int(error.seconds) // 3600)
            raise TakeoutNotReadyError(
                "Telegram wants to confirm this export first. Open Telegram "
                "on the phone, look for the service message about a data "
                "export request, tap Allow, and run this again. Without the "
                f"confirmation it unlocks by itself in about {hours} h."
            ) from error


@dataclass(frozen=True)
class MediaRecord:
    """One downloadable photo or video, as found while scanning a chat."""

    message_id: int
    moment: datetime  # when the message was sent, UTC
    kind: str  # PHOTO_KIND | IMAGE_DOCUMENT_KIND | VIDEO_KIND
    extension: str
    size: int = 0  # bytes, as reported by Telegram; 0 when unknown


def _document_extension(document) -> str:
    for attribute in document.attributes:
        if isinstance(attribute, DocumentAttributeFilename):
            suffix = Path(attribute.file_name).suffix.lstrip(".")
            if suffix:
                return suffix
    mime = (document.mime_type or "").lower()
    if mime in KNOWN_EXTENSIONS:
        return KNOWN_EXTENSIONS[mime]
    return (mimetypes.guess_extension(mime) or ".bin").lstrip(".")


def describe_media(message) -> MediaRecord | None:
    """Classify a message's media, or None when it is not worth rescuing.

    Stickers and non-image documents (PDFs, audio...) are left behind on
    purpose: this tool rescues photos and videos, not chat attachments.
    """
    size = getattr(getattr(message, "file", None), "size", 0) or 0
    if message.photo is not None:
        return MediaRecord(message.id, message.date, PHOTO_KIND, "jpg", size)

    document = message.document
    if document is None:
        return None
    attributes = document.attributes
    if any(isinstance(a, DocumentAttributeSticker) for a in attributes):
        return None

    mime = (document.mime_type or "").lower()
    is_video = mime.startswith("video/") or any(
        isinstance(a, DocumentAttributeVideo) for a in attributes
    )
    if is_video:
        return MediaRecord(
            message.id, message.date, VIDEO_KIND, _document_extension(document), size
        )
    if mime.startswith("image/"):
        return MediaRecord(
            message.id, message.date, IMAGE_DOCUMENT_KIND, _document_extension(document), size
        )
    return None


async def _append_download(
    path: Path, expected_size: int, open_stream, on_bytes=None, gate=None
) -> None:
    """Download to `path`, continuing a previous partial file if one exists.

    `open_stream(offset)` must return an async iterator of chunks starting at
    that byte. A partial file is truncated down to Telegram's offset
    alignment and continued, so a cancelled 1 GB video does not start over.
    Raises OSError when the result does not reach the expected size; the
    partial is deleted then, so the next run restarts that file cleanly.

    `gate`, when given, is awaited between chunks: it is where a pause
    blocks mid-file, and it may raise to abandon the transfer — the partial
    written so far is kept then, ready to resume.
    """
    start = 0
    if path.exists():
        # A genuine in-progress partial is strictly smaller than the full
        # file; anything else is stale or foreign and gets restarted.
        if path.stat().st_size < expected_size:
            start = (path.stat().st_size // DOWNLOAD_OFFSET_ALIGN) * DOWNLOAD_OFFSET_ALIGN

    received = start
    with path.open("r+b" if path.exists() else "wb") as handle:
        handle.truncate(start)
        handle.seek(start)
        async for chunk in open_stream(start):
            handle.write(chunk)
            received += len(chunk)
            if on_bytes is not None:
                on_bytes(received, expected_size)
            if gate is not None:
                await gate()

    if received != expected_size:
        path.unlink(missing_ok=True)
        raise OSError(
            f"download of {path.name} ended at {received} bytes instead of {expected_size}"
        )


class MediaDownloads:
    """Downloads message media through an open takeout session."""

    def __init__(self, client: TelegramClient, takeout_proxy: TelegramClient):
        self._client = client
        self._takeout = takeout_proxy

    async def download(
        self, chat_id: int, message_id: int, path: Path, on_bytes=None, gate=None
    ) -> bool:
        """Fetch one message and download its media to `path`.

        `on_bytes(received, total)` is called as the transfer advances, so
        the interface can show life during a long video instead of a frozen
        counter. `gate` is awaited between chunks of a resumable document
        download (see _append_download): pauses block there, and it may
        raise to abandon the file mid-transfer, partial kept.

        Returns False when the message or its media no longer exists (it was
        deleted between the scan and now). The message itself is fetched with
        the regular client - only file transfers need takeout's blessing, and
        takeout sessions do not allow every request type.
        """
        try:
            message = await self._client.get_messages(chat_id, ids=message_id)
            if message is None or (message.photo is None and message.document is None):
                return False
            document = message.document
            expected = getattr(message.file, "size", None) or 0
            if document is not None and expected:
                # Documents (videos, images sent as files) resume from a
                # partial download; photos are small and use the plain path.
                def open_stream(offset):
                    return self._takeout.iter_download(document, offset=offset)

                await _append_download(path, expected, open_stream, on_bytes, gate)
                return True
            result = await self._takeout.download_media(
                message, file=str(path), progress_callback=on_bytes
            )
        except TakeoutInvalidError as error:
            # The reused export expired on Telegram's side. Clear it so the
            # next run authorises a fresh one, and stop the run cleanly.
            await self._client.end_takeout(success=False)
            raise TelegramError(
                "The Telegram export session had expired. It has been reset - "
                "run the same command again to continue."
            ) from error
        except UnauthorizedError as error:
            raise SessionRevokedError(REVOKED_MESSAGE) from error
        return result is not None


class TakeoutNotReadyError(TelegramError):
    """Telegram wants the export confirmed (or a wait) before it may start."""
