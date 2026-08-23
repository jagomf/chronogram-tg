"""Writing the date of the message into the downloaded files.

Three rules from docs/DECISIONS.md drive everything here:

* Compressed photos arrive stripped of EXIF (D2), so the message date is the
  best date available and is written unconditionally.
* Images sent as files may still carry their original EXIF (D3). That date
  is more faithful than the message date and must never be overwritten.
* Videos are stamped with ffmpeg in copy mode, never re-encoded, so the file
  is rewritten losslessly and in seconds rather than minutes.

Every file also gets its modification time set, as a fallback for viewers
that ignore EXIF. All times are UTC (D15).
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from pathlib import Path

import piexif

EXIF_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"
VIDEO_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
FFMPEG_TIMEOUT_SECONDS = 300


def _empty_exif() -> dict:
    """A fresh, empty piexif structure.

    Built per call on purpose: a shared constant would hand out the same
    inner dictionaries every time, so one file's tags would leak into the
    next file's.
    """
    return {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}


class MetadataError(Exception):
    """A file could not be stamped. The message is written for the user."""


class Stamped(Enum):
    """What was actually done to a file, for the end-of-run summary."""

    EXIF_WRITTEN = "exif written"
    EXIF_KEPT = "original exif kept"
    VIDEO_METADATA_WRITTEN = "video metadata written"
    MODIFICATION_TIME_ONLY = "modification time only"


def as_utc(moment: datetime) -> datetime:
    """Naive datetimes are taken as UTC; aware ones are converted to it."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def set_modification_time(path: Path, moment: datetime) -> None:
    """Set the file's modification (and access) time, in UTC."""
    timestamp = as_utc(moment).timestamp()
    os.utime(path, (timestamp, timestamp))


def read_original_date(path: Path) -> datetime | None:
    """Return the EXIF DateTimeOriginal already in the file, if any."""
    try:
        exif = piexif.load(str(path))
    except (ValueError, struct.error, OSError):
        return None
    raw = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
    if not raw:
        return None
    try:
        return datetime.strptime(raw.decode("ascii", "replace"), EXIF_DATE_FORMAT).replace(
            tzinfo=UTC
        )
    except ValueError:
        return None


def _write_exif_dates(path: Path, moment: datetime) -> None:
    try:
        exif = piexif.load(str(path))
    except (ValueError, struct.error, OSError):
        exif = _empty_exif()

    stamp = as_utc(moment).strftime(EXIF_DATE_FORMAT).encode("ascii")
    exif.setdefault("0th", {})[piexif.ImageIFD.DateTime] = stamp
    exif.setdefault("Exif", {})[piexif.ExifIFD.DateTimeOriginal] = stamp
    exif["Exif"][piexif.ExifIFD.DateTimeDigitized] = stamp
    try:
        piexif.insert(piexif.dump(exif), str(path))
    except (ValueError, struct.error, OSError) as error:
        raise MetadataError(f"Could not write the date into {path.name}: {error}") from error


def stamp_photo(path: Path, moment: datetime) -> Stamped:
    """Stamp a compressed photo, whose original EXIF Telegram already removed."""
    _write_exif_dates(path, moment)
    set_modification_time(path, moment)
    return Stamped.EXIF_WRITTEN


def stamp_image_document(path: Path, moment: datetime) -> Stamped:
    """Stamp an image sent as a file, respecting any EXIF that survived.

    Formats piexif cannot write, such as PNG or WebP, keep their pixels
    untouched and get the modification time only.
    """
    original = read_original_date(path)
    if original is not None:
        # The file knows when the picture was taken; the message date is only
        # when it was forwarded. Keep the better one, mtime included.
        set_modification_time(path, original)
        return Stamped.EXIF_KEPT

    try:
        _write_exif_dates(path, moment)
    except MetadataError:
        set_modification_time(path, moment)
        return Stamped.MODIFICATION_TIME_ONLY

    set_modification_time(path, moment)
    return Stamped.EXIF_WRITTEN


@lru_cache(maxsize=1)
def detect_ffmpeg() -> str | None:
    """Locate ffmpeg on the system PATH. Cached; call cache_clear() to retry."""
    return shutil.which("ffmpeg")


def stamp_video(path: Path, moment: datetime) -> Stamped:
    """Write creation_time into a video, copying streams instead of re-encoding."""
    ffmpeg = detect_ffmpeg()
    if ffmpeg is None:
        raise MetadataError("ffmpeg is not installed, so videos cannot be dated.")

    stamped = path.with_name(f"{path.stem}.stamping{path.suffix}")
    command = [
        ffmpeg,
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(path),
        "-map",
        "0",
        "-c",
        "copy",
        "-metadata",
        f"creation_time={as_utc(moment).strftime(VIDEO_DATE_FORMAT)}",
        str(stamped),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        stamped.unlink(missing_ok=True)
        raise MetadataError(f"ffmpeg took too long on {path.name}.") from error

    if result.returncode != 0 or not stamped.exists():
        stamped.unlink(missing_ok=True)
        detail = (result.stderr or "").strip().splitlines()
        raise MetadataError(
            f"ffmpeg could not write the date into {path.name}"
            + (f": {detail[-1]}" if detail else ".")
        )

    os.replace(stamped, path)
    set_modification_time(path, moment)
    return Stamped.VIDEO_METADATA_WRITTEN
