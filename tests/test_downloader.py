import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import piexif
import pytest
from telethon.errors import FloodWaitError

from chronogram_tg import downloader
from chronogram_tg.downloader import (
    MAX_CONSECUTIVE_ERRORS,
    DownloadControl,
    DownloadError,
    download_chat,
    plan_names,
)
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

    async def download(self, chat_id, message_id, path, on_bytes=None, gate=None):
        self.download_calls.append(message_id)
        if message_id in self.flood_pending:
            self.flood_pending.discard(message_id)
            raise FloodWaitError(request=None, capture=0)
        if message_id in self.missing:
            return False
        if message_id in self.broken:
            path.write_bytes(b"half of a download")
            raise OSError("connection reset")
        # Two chunks with the gate between them, like _append_download does.
        half = len(MINIMAL_JPEG) // 2
        path.write_bytes(MINIMAL_JPEG[:half])
        if on_bytes is not None:
            on_bytes(half, len(MINIMAL_JPEG))
        if gate is not None:
            await gate()
        path.write_bytes(MINIMAL_JPEG)
        if on_bytes is not None:
            on_bytes(len(MINIMAL_JPEG), len(MINIMAL_JPEG))
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
    # The half-downloaded temporary survives so the next run can resume it.
    assert (tmp_path / "IMG_20240815_143023_000.part.jpg").read_bytes() == b"half of a download"


def test_an_unwritable_destination_is_one_clear_error_not_hundreds(tmp_path):
    blocker = tmp_path / "not-a-folder.txt"
    blocker.write_bytes(b"a file where the destination path needs a folder")
    source = FakeSource([record(1)])

    with pytest.raises(DownloadError, match="Cannot write into the destination"):
        run(source, blocker / "photos")

    assert source.download_calls == []


def test_a_run_where_everything_fails_stops_after_a_streak(tmp_path):
    ids = range(1, MAX_CONSECUTIVE_ERRORS + 3)
    source = FakeSource([record(n, seconds_later=n) for n in ids], broken=set(ids))

    with pytest.raises(DownloadError, match="in a row failed"):
        run(source, tmp_path)

    assert len(source.download_calls) == MAX_CONSECUTIVE_ERRORS


def test_scattered_failures_do_not_trip_the_streak(tmp_path):
    # Four broken, one good, one broken: never five in a row.
    source = FakeSource([record(n, seconds_later=n) for n in range(1, 7)], broken={1, 2, 3, 4, 6})

    summary = run(source, tmp_path)

    assert summary.downloaded == 1
    assert len(summary.errors) == 5


def test_a_leftover_temporary_next_to_its_finished_file_is_swept(tmp_path):
    # A crash between the stamp and the rename leaves both files behind.
    (tmp_path / "IMG_20240815_143022_000.jpg").write_bytes(b"finished earlier")
    stray = tmp_path / "IMG_20240815_143022_000.part.jpg"
    stray.write_bytes(b"crash relic")
    source = FakeSource([record(1)])

    summary = run(source, tmp_path)

    assert summary.already_there == 1
    assert not stray.exists()


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
        if done >= 1:
            control.cancel()

    summary = run(source, tmp_path, control=control, on_progress=cancel_after_first)

    assert summary.cancelled is True
    assert summary.downloaded == 1


def test_cancelling_mid_file_stops_at_once_and_keeps_the_partial(tmp_path):
    source = FakeSource([record(1), record(2, seconds_later=1)])
    control = DownloadControl()

    summary = run(
        source,
        tmp_path,
        control=control,
        on_bytes=lambda name, received, expected: control.cancel(),
    )

    assert summary.cancelled is True
    assert (summary.downloaded, summary.errors) == (0, [])
    assert source.download_calls == [1]
    partial = tmp_path / "IMG_20240815_143022_000.part.jpg"
    assert partial.read_bytes() == MINIMAL_JPEG[: len(MINIMAL_JPEG) // 2]
    assert not (tmp_path / "IMG_20240815_143022_000.jpg").exists()


def test_pausing_mid_file_holds_the_stream_until_resumed(tmp_path):
    source = FakeSource([record(1)])
    control = DownloadControl()
    half = len(MINIMAL_JPEG) // 2
    events = []

    def pause_at_half(name, received, expected):
        events.append(received)
        if received == half:
            control.pause()
            threading.Timer(0.05, lambda: (events.append("resumed"), control.resume())).start()

    summary = run(source, tmp_path, control=control, on_bytes=pause_at_half)

    assert summary.downloaded == 1
    # The second chunk only flowed after the resume: the pause held mid-file.
    assert events == [half, "resumed", len(MINIMAL_JPEG)]


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

    assert seen == [(0, 3), (1, 3), (2, 3), (3, 3)]


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


def test_session_level_trouble_stops_the_run_instead_of_repeating_per_file(tmp_path):
    # An expired export would otherwise be logged once per remaining item.
    from chronogram_tg.tg import TelegramError

    class ExpiredSource(FakeSource):
        async def download(self, chat_id, message_id, path, on_bytes=None, gate=None):
            raise TelegramError("The Telegram export session had expired.")

    source = ExpiredSource([record(1), record(2, seconds_later=1)])

    with pytest.raises(TelegramError):
        run(source, tmp_path)

    assert not list(tmp_path.glob("*.part*"))


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, "0 B"),
        (999, "999 B"),
        (1_500, "1.5 KB"),
        (2_340_000, "2.3 MB"),
        (1_200_000_000, "1.2 GB"),
    ],
)
def test_sizes_are_reported_in_human_units(count, expected):
    from chronogram_tg.downloader import human_size

    assert human_size(count) == expected


def test_the_scan_status_includes_the_total_size_when_known(tmp_path):
    source = FakeSource(
        [
            MediaRecord(1, MOMENT, PHOTO_KIND, "jpg", 1_500_000),
            MediaRecord(2, MOMENT + timedelta(seconds=1), PHOTO_KIND, "jpg", 500_000),
        ]
    )
    heard = []

    run(source, tmp_path, on_status=heard.append)

    assert any("2 items to consider, 2.0 MB in total." == message for message in heard)


def test_clean_removes_this_downloads_files_and_nothing_else(tmp_path):
    (tmp_path / "IMG_20240815_143022_000.jpg").write_bytes(b"from an old run")
    (tmp_path / "IMG_20240815_143022_000.part.jpg").write_bytes(b"half a download")
    (tmp_path / "holiday-plans.txt").write_bytes(b"unrelated, keep me")
    source = FakeSource([record(1)])

    summary = run(source, tmp_path, clean=True)

    assert (summary.cleaned, summary.downloaded, summary.already_there) == (2, 1, 0)
    assert (tmp_path / "holiday-plans.txt").read_bytes() == b"unrelated, keep me"
    assert (tmp_path / "IMG_20240815_143022_000.jpg").read_bytes() != b"from an old run"


def test_clean_on_a_fresh_folder_is_a_quiet_no_op(tmp_path):
    source = FakeSource([record(1)])
    heard = []

    summary = run(source, tmp_path, clean=True, on_status=heard.append)

    assert (summary.cleaned, summary.downloaded) == (0, 1)
    assert not any("Removed" in message for message in heard)


def test_byte_progress_reports_the_file_being_downloaded(tmp_path):
    source = FakeSource([record(1)])
    seen = []

    run(
        source,
        tmp_path,
        on_bytes=lambda name, received, expected: seen.append((name, received, expected)),
    )

    assert seen == [
        ("IMG_20240815_143022_000.jpg", len(MINIMAL_JPEG) // 2, len(MINIMAL_JPEG)),
        ("IMG_20240815_143022_000.jpg", len(MINIMAL_JPEG), len(MINIMAL_JPEG)),
    ]


def test_byte_progress_is_not_reported_for_skipped_files(tmp_path):
    (tmp_path / "IMG_20240815_143022_000.jpg").write_bytes(b"already here")
    source = FakeSource([record(1)])
    seen = []

    run(source, tmp_path, on_bytes=lambda *call: seen.append(call))

    assert seen == []


def test_a_starting_download_is_announced_before_its_first_byte(tmp_path):
    source = FakeSource([MediaRecord(1, MOMENT, PHOTO_KIND, "jpg", 5000)])
    seen = []

    run(
        source,
        tmp_path,
        on_bytes=lambda name, received, expected: seen.append((received, expected)),
    )

    # None, not 0: the announcement must not claim "starting from zero"
    # when a partial file may be about to resume.
    assert seen[0] == (None, 5000)
    assert all(isinstance(received, int) for received, _ in seen[1:])
