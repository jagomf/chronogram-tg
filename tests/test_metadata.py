import subprocess
from datetime import UTC, datetime, timedelta, timezone

import piexif
import pytest

from chronogram_tg.metadata import (
    EXIF_DATE_FORMAT,
    MetadataError,
    Stamped,
    as_utc,
    detect_ffmpeg,
    read_original_date,
    set_modification_time,
    stamp_image_document,
    stamp_photo,
    stamp_video,
)

MOMENT = datetime(2024, 8, 15, 14, 30, 22, tzinfo=UTC)
EARLIER = datetime(2019, 3, 1, 9, 0, 0, tzinfo=UTC)

# The smallest byte sequence piexif accepts as a JPEG: start of image, a JFIF
# header, a start-of-scan segment and end of image. Keeping the fixture inline
# avoids committing binary files just to test a date.
MINIMAL_JPEG = (
    b"\xff\xd8"
    b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    b"\x00"
    b"\xff\xd9"
)


def jpeg(tmp_path, name="photo.jpg", *, taken=None):
    path = tmp_path / name
    path.write_bytes(MINIMAL_JPEG)
    if taken is not None:
        exif = {
            "0th": {},
            "Exif": {piexif.ExifIFD.DateTimeOriginal: taken.strftime(EXIF_DATE_FORMAT).encode()},
            "GPS": {},
            "1st": {},
            "thumbnail": None,
        }
        piexif.insert(piexif.dump(exif), str(path))
    return path


def exif_original(path):
    return piexif.load(str(path))["Exif"][piexif.ExifIFD.DateTimeOriginal].decode()


def test_a_compressed_photo_gets_the_message_date(tmp_path):
    path = jpeg(tmp_path)

    assert stamp_photo(path, MOMENT) is Stamped.EXIF_WRITTEN
    assert exif_original(path) == "2024:08:15 14:30:22"


def test_stamping_writes_the_three_date_tags(tmp_path):
    path = jpeg(tmp_path)
    stamp_photo(path, MOMENT)

    exif = piexif.load(str(path))
    assert exif["0th"][piexif.ImageIFD.DateTime].decode() == "2024:08:15 14:30:22"
    assert exif["Exif"][piexif.ExifIFD.DateTimeDigitized].decode() == "2024:08:15 14:30:22"


def test_stamping_keeps_the_rest_of_the_exif(tmp_path):
    path = jpeg(tmp_path)
    exif = piexif.load(str(path))
    exif["0th"][piexif.ImageIFD.Make] = b"Pixel 6a"
    piexif.insert(piexif.dump(exif), str(path))

    stamp_photo(path, MOMENT)

    assert piexif.load(str(path))["0th"][piexif.ImageIFD.Make].decode() == "Pixel 6a"


def test_stamping_does_not_touch_the_image_itself(tmp_path):
    path = jpeg(tmp_path)

    stamp_photo(path, MOMENT)

    assert path.read_bytes().endswith(b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x00\xff\xd9")


def test_a_document_that_remembers_when_it_was_taken_is_left_alone(tmp_path):
    # Decision D3: a surviving original date beats the date it was sent.
    path = jpeg(tmp_path, taken=EARLIER)

    assert stamp_image_document(path, MOMENT) is Stamped.EXIF_KEPT
    assert exif_original(path) == "2019:03:01 09:00:00"


def test_a_kept_original_date_is_used_for_the_modification_time_too(tmp_path):
    path = jpeg(tmp_path, taken=EARLIER)

    stamp_image_document(path, MOMENT)

    assert path.stat().st_mtime == pytest.approx(EARLIER.timestamp())


def test_a_document_without_a_date_gets_the_message_date(tmp_path):
    path = jpeg(tmp_path)

    assert stamp_image_document(path, MOMENT) is Stamped.EXIF_WRITTEN
    assert exif_original(path) == "2024:08:15 14:30:22"


def test_a_format_exif_cannot_describe_still_gets_its_date_from_the_filesystem(tmp_path):
    png = tmp_path / "sent.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    original = png.read_bytes()

    assert stamp_image_document(png, MOMENT) is Stamped.MODIFICATION_TIME_ONLY
    assert png.stat().st_mtime == pytest.approx(MOMENT.timestamp())
    assert png.read_bytes() == original


def test_the_modification_time_is_written_in_utc(tmp_path):
    path = jpeg(tmp_path)

    set_modification_time(path, MOMENT)

    assert path.stat().st_mtime == pytest.approx(1723732222.0)


def test_a_date_from_another_timezone_is_converted_rather_than_trusted(tmp_path):
    madrid = MOMENT.astimezone(timezone(timedelta(hours=2)))
    path = jpeg(tmp_path)

    stamp_photo(path, madrid)

    assert exif_original(path) == "2024:08:15 14:30:22"


def test_a_naive_date_is_taken_as_utc():
    assert as_utc(MOMENT.replace(tzinfo=None)) == MOMENT


def test_no_original_date_is_reported_for_a_file_without_exif(tmp_path):
    assert read_original_date(jpeg(tmp_path)) is None


def test_no_original_date_is_reported_for_a_file_exif_cannot_read(tmp_path):
    path = tmp_path / "not.jpg"
    path.write_bytes(b"this is not an image")

    assert read_original_date(path) is None


def test_an_unreadable_original_date_does_not_crash_the_stamping(tmp_path):
    path = jpeg(tmp_path)
    exif = {
        "0th": {},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: b"not a date"},
        "GPS": {},
        "1st": {},
        "thumbnail": None,
    }
    piexif.insert(piexif.dump(exif), str(path))

    assert read_original_date(path) is None
    assert stamp_image_document(path, MOMENT) is Stamped.EXIF_WRITTEN


def test_videos_report_a_clear_error_when_ffmpeg_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("chronogram_tg.metadata.detect_ffmpeg", lambda: None)

    with pytest.raises(MetadataError, match="ffmpeg is not installed"):
        stamp_video(tmp_path / "clip.mp4", MOMENT)


needs_ffmpeg = pytest.mark.skipif(detect_ffmpeg() is None, reason="ffmpeg is not installed")


@needs_ffmpeg
def test_a_video_gets_the_message_date_without_being_re_encoded(tmp_path):
    path = tmp_path / "clip.mp4"
    subprocess.run(
        # fmt: off
        [
            detect_ffmpeg(),
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=32x32:rate=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        # fmt: on
        check=True,
        capture_output=True,
    )
    before = path.stat().st_size

    assert stamp_video(path, MOMENT) is Stamped.VIDEO_METADATA_WRITTEN

    probe = subprocess.run(
        [
            detect_ffmpeg().replace("ffmpeg", "ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format_tags=creation_time",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.strip().startswith("2024-08-15T14:30:22")
    assert path.stat().st_mtime == pytest.approx(MOMENT.timestamp())
    # Copying streams keeps the size within a container header's difference.
    assert abs(path.stat().st_size - before) < 4096
    assert not list(tmp_path.glob("*.stamping.*"))


@needs_ffmpeg
def test_a_file_ffmpeg_cannot_read_reports_the_problem_and_cleans_up(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video at all")

    with pytest.raises(MetadataError, match="could not write the date"):
        stamp_video(broken, MOMENT)

    assert not list(tmp_path.glob("*.stamping.*"))


def test_stamping_one_unreadable_file_does_not_affect_the_next(tmp_path):
    # A shared empty-EXIF constant would leak the first file's tags here.
    first = tmp_path / "one.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    stamp_image_document(first, EARLIER)

    second = jpeg(tmp_path, "two.jpg")
    stamp_photo(second, MOMENT)

    assert exif_original(second) == "2024:08:15 14:30:22"
    assert read_original_date(second) == MOMENT
