from datetime import UTC, datetime, timedelta, timezone

import pytest

from chronogram_tg.naming import (
    PIXEL_TEMPLATE,
    PLAIN_TEMPLATE,
    PRESETS,
    TELEGRAM_TEMPLATE,
    NameAllocator,
    TemplateError,
    kind_for_extension,
    normalise_extension,
    preview,
    validate_template,
)

MOMENT = datetime(2024, 8, 15, 14, 30, 22, tzinfo=UTC)


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        (TELEGRAM_TEMPLATE, "IMG_20240815_143022_000.jpg"),
        (PIXEL_TEMPLATE, "PXL_20240815_143022000.jpg"),
        (PLAIN_TEMPLATE, "20240815_143022000.jpg"),
    ],
)
def test_each_preset_produces_its_documented_name(template, expected):
    assert NameAllocator(template).allocate(MOMENT, "jpg") == expected


def test_the_telegram_preset_is_the_first_offered():
    # Decision D18: the rescued files join the phone's Telegram gallery
    # folders, so they are named the way Telegram itself names files there.
    assert next(iter(PRESETS)) == "Telegram"
    assert PRESETS["Telegram"] == TELEGRAM_TEMPLATE
    assert "Pixel" in PRESETS


def test_items_sharing_a_second_are_numbered_in_message_order():
    allocator = NameAllocator(PIXEL_TEMPLATE)

    names = [allocator.allocate(MOMENT, "jpg") for _ in range(3)]

    assert names == [
        "PXL_20240815_143022000.jpg",
        "PXL_20240815_143022001.jpg",
        "PXL_20240815_143022002.jpg",
    ]


def test_a_different_second_restarts_the_counter():
    allocator = NameAllocator(PIXEL_TEMPLATE)

    first = allocator.allocate(MOMENT, "jpg")
    second = allocator.allocate(MOMENT + timedelta(seconds=1), "jpg")

    assert first.endswith("143022000.jpg")
    assert second.endswith("143023000.jpg")


def test_the_same_messages_always_get_the_same_names():
    # Resume-by-filename depends on this: a second run must rebuild exactly
    # the names the first run produced.
    def run():
        allocator = NameAllocator(PIXEL_TEMPLATE)
        return [
            allocator.allocate(MOMENT, "jpg"),
            allocator.allocate(MOMENT, "mp4"),
            allocator.allocate(MOMENT + timedelta(seconds=5), "jpg"),
        ]

    assert run() == run()


def test_dates_are_named_in_utc_whatever_timezone_they_arrive_in():
    madrid = MOMENT.astimezone(timezone(timedelta(hours=2)))

    assert NameAllocator(PIXEL_TEMPLATE).allocate(madrid, "jpg").startswith("PXL_20240815_1430")


def test_a_naive_datetime_is_taken_as_utc_rather_than_rejected():
    assert NameAllocator(PIXEL_TEMPLATE).allocate(MOMENT.replace(tzinfo=None), "jpg") == (
        "PXL_20240815_143022000.jpg"
    )


def test_a_pattern_without_milliseconds_still_cannot_overwrite_a_file():
    allocator = NameAllocator("{date}")

    names = [allocator.allocate(MOMENT, "jpg") for _ in range(3)]

    assert names == ["20240815.jpg", "20240815_2.jpg", "20240815_3.jpg"]


def test_names_differing_only_in_case_are_treated_as_the_same_file():
    # The destination is usually a case-insensitive disk (macOS, Windows).
    allocator = NameAllocator("{date}")

    first = allocator.allocate(MOMENT, "JPG")
    second = allocator.allocate(MOMENT, "jpg")

    assert (first, second) == ("20240815.jpg", "20240815_2.jpg")


@pytest.mark.parametrize(
    ("extension", "expected"),
    [("jpg", "jpg"), (".JPG", "jpg"), ("  .Mp4 ", "mp4"), ("", "bin"), ("/:*", "bin")],
)
def test_extensions_are_cleaned_up(extension, expected):
    assert normalise_extension(extension) == expected


@pytest.mark.parametrize(
    ("template", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        (" {date}", "space"),
        ("{date} ", "space"),
        ("{year}", "Unknown token"),
        ("{}", "name of the token"),
        ("{date", "unmatched"),
        ("photos/{date}", "not allowed in filenames"),
        ("{date}:{time}", "not allowed in filenames"),
        ("{date}.", "end with a dot"),
        ("NUL", "windows reserves"),
    ],
)
def test_unusable_patterns_are_rejected_with_an_explanation(template, reason):
    with pytest.raises(TemplateError) as raised:
        validate_template(template)

    assert reason.lower() in str(raised.value).lower()


def test_a_rejected_pattern_never_reaches_the_allocator():
    with pytest.raises(TemplateError):
        NameAllocator("{year}")


def test_literal_braces_can_be_written_by_doubling_them():
    assert preview("{{{date}}}") == "{20240815}.jpg"


def test_the_preview_shows_the_documented_pixel_example():
    assert preview(PIXEL_TEMPLATE) == "PXL_20240815_143022000.jpg"


def test_the_preview_reports_the_problem_instead_of_a_name():
    with pytest.raises(TemplateError):
        preview("{nope}")


@pytest.mark.parametrize(
    ("extension", "kind"),
    [("jpg", "IMG"), ("png", "IMG"), (".JPG", "IMG"), ("mp4", "VID"), (".MOV", "VID"), ("", "IMG")],
)
def test_the_kind_token_matches_telegrams_own_prefixes(extension, kind):
    assert kind_for_extension(extension) == kind


def test_a_video_gets_the_vid_prefix_in_the_telegram_preset():
    assert NameAllocator(TELEGRAM_TEMPLATE).allocate(MOMENT, "mp4") == (
        "VID_20240815_143022_000.mp4"
    )


def test_a_photo_and_a_video_in_the_same_second_share_the_counter():
    # Determinism across kinds: the counter follows message order, so a
    # rerun rebuilds the same names even when kinds interleave.
    allocator = NameAllocator(TELEGRAM_TEMPLATE)

    names = [allocator.allocate(MOMENT, "jpg"), allocator.allocate(MOMENT, "mp4")]

    assert names == ["IMG_20240815_143022_000.jpg", "VID_20240815_143022_001.mp4"]


def test_the_preview_of_the_telegram_preset_follows_the_extension():
    assert preview(TELEGRAM_TEMPLATE) == "IMG_20240815_143022_000.jpg"
    assert preview(TELEGRAM_TEMPLATE, "mp4") == "VID_20240815_143022_000.mp4"
