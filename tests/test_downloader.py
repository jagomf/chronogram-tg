import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import piexif
import pytest
from telethon.errors import FloodWaitError

from chronogram_tg import downloader
from chronogram_tg.downloader import DownloadControl, download_chat, plan_names
from chronogram_tg.metadata import MetadataError
from chronogram_tg.naming import TELEGRAM_TEMPLATE
from chronogram_tg.tg import IMAGE_DOCUMENT_KIND, PHOTO_KIND, VIDEO_KIND, MediaRecord

MOMENT = datetime(2024, 8, 15, 14, 30, 22, tzinfo=UTC)

MINIMAL_JPEG = (
    b"\xff\xd8"
    b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    b"\x00"
    b"\xff\xd9"
)


def record(message_id, *, kind=PHOTO_KIND, extension="jpg", seconds_later=0):
    return MediaRecord(message_id, MOMENT + timedelta(seconds=seconds_later), kind, extension)


class FakeSource:
    """Stands in for TelegramSession: same surface, no network."""

    def __init__(self, records, *, flood_once_on=(), missing=(), broken=()):
        self.records = list(records)
        self.flood_pending = set(flood_once_on)
        self.missing = set(missing)
        self.broken = set(broken)
        self.download_calls = []

    async def scan_media(self, chat_id, since=None, until_exclusive=None):
        return self.records

    @asynccontextmanager
    async def takeout_downloads(self):
        yield self

    async def download(self, chat_id, message_id, path):
        self.download_calls.append(message_id)
        if message_id in self.flood_pending:
            self.flood_pending.discard(message_id)
            raise FloodWaitError(request=None, capture=0)
        if message_id in self.missing:
            return False
        if message_id in self.broken:
            raise OSError("connection reset")
        path.write_bytes(MINIMAL_JPEG)
        return True


@pytest.fixture(autouse=True)
def instant_pacing(monkeypatch):
    monkeypatch.setattr(downloader, "ITEM_PAUSE_SECONDS", 0)
    monkeypatch.setattr(downloader, "PAUSE_POLL_SECONDS", 0)


def run(source, tmp_path, **kwargs):
    return asyncio.run(
        download_chat(source, chat_id=1, destination=tmp_path, template=TELEGRAM_TEMPLATE, **kwargs)
    )


def test_a_full_run_downloads_stamps_and_names_everything(tmp_path):
    source = FakeSource([record(1), record(2, kind=IMAGE_DOCUMENT_KIND, seconds_later=1)])

    summary = run(source, tmp_path)

    assert (summary.downloaded, summary.errors) == (2, [])
    first = tmp_path / "IMG_20240815_143022_000.jpg"
    assert first.exists()
    assert (tmp_path / "IMG_20240815_143023_000.jpg").exists()
    exif = piexif.load(str(first))
    assert exif["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2024:08:15 14:30:22"
    assert first.stat().st_mtime == pytest.approx(MOMENT.timestamp())


def test_files_already_there_are_skipped_not_downloaded_again(tmp_path):
    (tmp_path / "IMG_20240815_143022_000.jpg").write_bytes(b"from the previous run")
    source = FakeSource([record(1), record(2, seconds_later=1)])

    summary = run(source, tmp_path)

    assert (summary.already_there, summary.downloaded) == (1, 1)
    assert source.download_calls == [2]
    assert (tmp_path / "IMG_20240815_143022_000.jpg").read_bytes() == b"from the previous run"


def test_excluded_videos_still_hold_their_place_in_the_naming(tmp_path):
    # Toggling videos between runs must not shift photo names (resume, D11).
    source = FakeSource([record(1, kind=VIDEO_KIND, extension="mp4"), record(2)])

    summary = run(source, tmp_path, include_videos=False)

    assert (summary.videos_skipped, summary.downloaded) == (1, 1)
    assert source.download_calls == [2]
    assert (tmp_path / "IMG_20240815_143022_001.jpg").exists()
    assert not (tmp_path / "VID_20240815_143022_000.mp4").exists()


def test_one_broken_item_does_not_sink_the_rest(tmp_path):
    source = FakeSource(
        [record(1), record(2, seconds_later=1), record(3, seconds_later=2)], broken={2}
    )

    summary = run(source, tmp_path)

    assert summary.downloaded == 2
    assert len(summary.errors) == 1 and "connection reset" in summary.errors[0]
    assert not list(tmp_path.glob("*.part*"))


def test_a_message_deleted_after_the_scan_is_only_counted(tmp_path):
    source = FakeSource([record(1)], missing={1})

    summary = run(source, tmp_path)

    assert (summary.missing, summary.downloaded, summary.errors) == (1, 0, [])


def test_a_flood_wait_is_sat_out_and_the_item_retried(tmp_path):
    source = FakeSource([record(1)], flood_once_on={1})
    heard = []

    summary = run(source, tmp_path, on_status=heard.append)

    assert summary.downloaded == 1
    assert source.download_calls == [1, 1]
    assert any("asked to wait" in message for message in heard)


def test_cancelling_stops_between_items_and_reports_it(tmp_path):
    source = FakeSource([record(1), record(2, seconds_later=1)])
    control = DownloadControl()

    def cancel_after_first(done, total, name):
        control.cancel()

    summary = run(source, tmp_path, control=control, on_progress=cancel_after_first)

    assert summary.cancelled is True
    assert summary.downloaded == 1


def test_a_video_that_ffmpeg_rejects_is_kept_with_its_file_time(tmp_path, monkeypatch):
    def refuse(path, moment):
        raise MetadataError("ffmpeg could not write the date")

    monkeypatch.setattr(downloader, "stamp_video", refuse)
    source = FakeSource([record(1, kind=VIDEO_KIND, extension="mp4")])

    summary = run(source, tmp_path)

    target = tmp_path / "VID_20240815_143022_000.mp4"
    assert target.exists()
    assert (summary.downloaded, summary.dated_by_file_time_only) == (1, 1)
    assert "file time only" in summary.errors[0]
    assert target.stat().st_mtime == pytest.approx(MOMENT.timestamp())


def test_progress_counts_every_item_up_to_the_total(tmp_path):
    source = FakeSource([record(n, seconds_later=n) for n in range(1, 4)])
    seen = []

    run(source, tmp_path, on_progress=lambda done, total, name: seen.append((done, total)))

    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_the_plan_is_deterministic_between_runs():
    records = [record(1), record(2), record(3, kind=VIDEO_KIND, extension="mp4")]

    first = [item.filename for item in plan_names(records, TELEGRAM_TEMPLATE)]
    second = [item.filename for item in plan_names(records, TELEGRAM_TEMPLATE)]

    assert first == second
    assert first == [
        "IMG_20240815_143022_000.jpg",
        "IMG_20240815_143022_001.jpg",
        "VID_20240815_143022_002.mp4",
    ]
