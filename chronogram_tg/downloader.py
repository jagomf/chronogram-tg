"""Orchestration: plan the names, download what is missing, stamp the dates.

The run happens in two passes (decision D11). Pass one scans the chat and
allocates every filename up front, so a file's name depends only on the
message order - never on what already sits in the destination folder. Pass
two downloads whatever is not there yet, which is also all it takes to
resume an interrupted run.

Each item is downloaded to a temporary name, stamped, and only then renamed
to its final name: a file that carries its final name is always complete
and dated. The temporary name keeps the real extension at the end
(IMG_x.part.jpg) because ffmpeg picks the output container by extension.

This module never touches Telethon types: it talks to Telegram through the
small surface TelegramSession offers (scan_media, takeout_downloads) and to
the caller through plain callbacks, so the CLI today and the GUI later can
drive the same code.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from telethon.errors import FloodWaitError

from .metadata import (
    MetadataError,
    Stamped,
    set_modification_time,
    stamp_image_document,
    stamp_photo,
    stamp_video,
)
from .naming import NameAllocator
from .tg import (
    IMAGE_DOCUMENT_KIND,
    PHOTO_KIND,
    VIDEO_KIND,
    MediaRecord,
    TelegramError,
)

# The prudent pace of decision D10: one item, then a breath.
ITEM_PAUSE_SECONDS = 1.0
PAUSE_POLL_SECONDS = 0.2
FLOOD_RETRY_LIMIT = 5

ProgressCallback = Callable[[int, int, str], None]  # items dealt with, total, latest name
StatusCallback = Callable[[str], None]
BytesCallback = Callable[[str, int, int], None]  # filename, bytes received, bytes expected


@dataclass(frozen=True)
class PlannedItem:
    record: MediaRecord
    filename: str


@dataclass
class Summary:
    """What the run did, for the closing report."""

    total: int = 0
    downloaded: int = 0
    already_there: int = 0  # resume: found on disk and skipped
    videos_skipped: int = 0  # videos excluded by choice or missing ffmpeg
    missing: int = 0  # deleted from the chat between scan and download
    cleaned: int = 0  # files removed up front by --clean
    dated_by_file_time_only: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


class DownloadControl:
    """Pause/resume/cancel flags, safe to flip from another thread.

    The GUI toggles these from the interface thread while the download loop
    reads them from the asyncio thread; threading.Event is safe for that.
    """

    def __init__(self):
        self._running = threading.Event()
        self._running.set()
        self._cancelled = threading.Event()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._running.set()  # a paused download must be able to die

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    async def wait_while_paused(self) -> bool:
        """Block while paused; True means carry on, False means cancelled."""
        while not self._running.is_set():
            await asyncio.sleep(PAUSE_POLL_SECONDS)
        return not self.cancelled


def human_size(count: int) -> str:
    """1234567 -> '1.2 MB', for people rather than programs."""
    value = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            break
        value /= 1000
    return f"{count} B" if unit == "B" else f"{value:.1f} {unit}"


def plan_names(records: list[MediaRecord], template: str) -> list[PlannedItem]:
    """Give every record its final filename, in message order.

    Every record takes part - even videos that will not be downloaded this
    run - so that toggling the videos checkbox between runs cannot shift the
    names of the photos around them and break resume.
    """
    allocator = NameAllocator(template)
    return [
        PlannedItem(record, allocator.allocate(record.moment, record.extension))
        for record in records
    ]


def _temporary_path(destination: Path, filename: str) -> Path:
    final = Path(filename)
    return destination / f"{final.stem}.part{final.suffix}"


def _stamp(item: PlannedItem, path: Path, summary: Summary) -> None:
    moment = item.record.moment
    try:
        if item.record.kind == PHOTO_KIND:
            result = stamp_photo(path, moment)
        elif item.record.kind == IMAGE_DOCUMENT_KIND:
            result = stamp_image_document(path, moment)
        else:
            result = stamp_video(path, moment)
    except MetadataError as error:
        # A file whose date tag failed is still worth keeping: the
        # modification time carries the date, and the report says so.
        set_modification_time(path, moment)
        summary.dated_by_file_time_only += 1
        summary.errors.append(f"{item.filename}: dated by file time only ({error})")
        return
    if result is Stamped.MODIFICATION_TIME_ONLY:
        summary.dated_by_file_time_only += 1


async def _download_patiently(
    downloads,
    chat_id: int,
    item: PlannedItem,
    path: Path,
    say: StatusCallback,
    on_bytes: BytesCallback | None,
) -> bool:
    """Download one item, sitting out however long Telegram asks us to."""
    report = None
    if on_bytes is not None:

        def report(received, expected):
            on_bytes(item.filename, int(received), int(expected or 0))

    attempts = 0
    while True:
        try:
            return await downloads.download(chat_id, item.record.message_id, path, on_bytes=report)
        except FloodWaitError as error:
            attempts += 1
            if attempts >= FLOOD_RETRY_LIMIT:
                raise
            wait = int(error.seconds) + 1
            say(f"Telegram asked to wait {wait} s - resuming automatically.")
            await asyncio.sleep(wait)


async def download_chat(
    source,
    chat_id: int,
    destination: Path,
    template: str,
    *,
    since: datetime | None = None,
    until_exclusive: datetime | None = None,
    include_videos: bool = True,
    clean: bool = False,
    control: DownloadControl | None = None,
    on_progress: ProgressCallback | None = None,
    on_status: StatusCallback | None = None,
    on_bytes: BytesCallback | None = None,
) -> Summary:
    """Download a chat's media into `destination`. Returns the run's Summary."""
    control = control or DownloadControl()
    say: StatusCallback = on_status or (lambda message: None)
    tick: ProgressCallback = on_progress or (lambda done, total, name: None)

    destination.mkdir(parents=True, exist_ok=True)
    say("Scanning the chat for photos and videos...")
    records = await source.scan_media(chat_id, since, until_exclusive)
    plan = plan_names(records, template)
    summary = Summary(total=len(plan))
    total_bytes = sum(item.record.size for item in plan)
    if total_bytes:
        say(f"{summary.total} items to consider, {human_size(total_bytes)} in total.")
    else:
        say(f"{summary.total} items to consider.")
    if not plan:
        return summary

    if clean:
        # Start over: remove exactly the files this run would produce (plus
        # their temporaries) and nothing else, so pointing --dest at a folder
        # with unrelated files in it cannot destroy them.
        for item in plan:
            for stale in (destination / item.filename, _temporary_path(destination, item.filename)):
                if stale.exists():
                    stale.unlink()
                    summary.cleaned += 1
        if summary.cleaned:
            say(f"Removed {summary.cleaned} files from a previous run; starting over.")

    dealt_with = 0
    tick(0, summary.total, "")  # the baseline, so the counter is visible at once
    async with source.takeout_downloads() as downloads:
        for item in plan:
            if not await control.wait_while_paused():
                summary.cancelled = True
                break
            dealt_with += 1
            target = destination / item.filename

            if target.exists():
                summary.already_there += 1
                tick(dealt_with, summary.total, item.filename)
                continue
            if item.record.kind == VIDEO_KIND and not include_videos:
                summary.videos_skipped += 1
                tick(dealt_with, summary.total, item.filename)
                continue

            temporary = _temporary_path(destination, item.filename)
            try:
                if not await _download_patiently(
                    downloads, chat_id, item, temporary, say, on_bytes
                ):
                    summary.missing += 1
                    tick(dealt_with, summary.total, item.filename)
                    continue
                _stamp(item, temporary, summary)
                temporary.replace(target)
                summary.downloaded += 1
            except TelegramError:
                # Session-level trouble (expired export, lost login) affects
                # every remaining item: stop the run instead of logging it
                # once per file.
                temporary.unlink(missing_ok=True)
                raise
            except Exception as error:  # one broken item must not sink the rescue
                temporary.unlink(missing_ok=True)
                summary.errors.append(f"{item.filename}: {error}")

            tick(dealt_with, summary.total, item.filename)
            await asyncio.sleep(ITEM_PAUSE_SECONDS)

    return summary
