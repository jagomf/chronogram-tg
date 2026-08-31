"""The main window's pure logic; the widgets themselves live in smoke_gui.py."""

from pathlib import Path

from chronogram_tg.downloader import Summary
from chronogram_tg.gui.app import (
    MAX_PATH_CHARS,
    RunFeed,
    run_fraction,
    run_line,
    shorten_path,
    summary_line,
)

# ── shorten_path ─────────────────────────────────────────────────────


def test_a_path_under_home_reads_as_tilde():
    assert shorten_path(Path.home() / "Downloads" / "Chronogram") == "~/Downloads/Chronogram"


def test_a_path_outside_home_is_shown_as_is():
    assert shorten_path(Path("/Volumes/USB/photos")) == "/Volumes/USB/photos"


def test_a_long_path_is_cut_from_the_front():
    path = Path("/Volumes/backup") / ("x" * MAX_PATH_CHARS) / "photos"

    shortened = shorten_path(path)

    assert shortened.startswith("…")
    assert shortened.endswith("/photos")
    assert len(shortened) == MAX_PATH_CHARS


# ── RunFeed ──────────────────────────────────────────────────────────


def test_a_fresh_feed_drains_empty():
    assert RunFeed().drain() == (None, None, [])


def test_the_feed_keeps_only_the_latest_progress_and_bytes():
    feed = RunFeed()
    feed.on_progress(1, 10, "IMG_a.jpg")
    feed.on_progress(2, 10, "IMG_b.jpg")
    feed.on_bytes("VID_c.mp4", None, 500)
    feed.on_bytes("VID_c.mp4", 100, 500)

    progress, bytes_state, statuses = feed.drain()

    assert progress == (2, 10, "IMG_b.jpg")
    assert bytes_state == ("VID_c.mp4", 100, 500)
    assert statuses == []


def test_a_progress_tick_discards_the_finished_files_byte_count():
    feed = RunFeed()
    feed.on_bytes("VID_c.mp4", 500, 500)
    feed.on_progress(3, 10, "VID_c.mp4")

    progress, bytes_state, _ = feed.drain()

    assert progress == (3, 10, "VID_c.mp4")
    assert bytes_state is None


def test_statuses_arrive_in_order_and_drain_clears_them():
    feed = RunFeed()
    feed.on_status("Scanning the chat for photos and videos...")
    feed.on_status("Telegram asked to wait 42 s - resuming automatically.")

    _, _, statuses = feed.drain()
    assert statuses == [
        "Scanning the chat for photos and videos...",
        "Telegram asked to wait 42 s - resuming automatically.",
    ]
    assert feed.drain() == (None, None, [])


# ── run_fraction ─────────────────────────────────────────────────────


def test_the_fraction_is_items_done_over_total():
    assert run_fraction((74, 161, "IMG_a.jpg"), None) == 74 / 161


def test_an_empty_plan_shows_a_full_bar():
    assert run_fraction((0, 0, ""), None) == 1.0


def test_the_inflight_files_bytes_add_their_share():
    assert run_fraction((1, 4, ""), ("VID.mp4", 500, 1000)) == (1 + 0.5) / 4


def test_unknown_received_bytes_add_nothing():
    assert run_fraction((1, 4, ""), ("VID.mp4", None, 1000)) == 1 / 4


def test_an_oversized_partial_cannot_push_the_bar_past_full():
    assert run_fraction((3, 4, ""), ("VID.mp4", 2000, 1000)) == 1.0


# ── run_line ─────────────────────────────────────────────────────────


def test_the_baseline_line_is_just_the_counter():
    assert run_line((0, 161, ""), None) == "0 / 161"


def test_a_finished_item_shows_its_name():
    assert run_line((74, 161, "IMG_a.jpg"), None) == "74 / 161 — IMG_a.jpg"


def test_an_inflight_file_shows_its_byte_counts():
    line = run_line((73, 161, "IMG_a.jpg"), ("VID_b.mp4", 292_000_000, 1_200_000_000))

    assert line == "74 / 161 — VID_b.mp4 (292.0 MB / 1.2 GB)"


def test_bytes_not_yet_known_render_as_an_ellipsis():
    line = run_line((73, 161, ""), ("VID_b.mp4", None, 1_200_000_000))

    assert "(… / 1.2 GB)" in line


def test_a_zero_expected_size_falls_back_to_the_plain_line():
    assert run_line((73, 161, "IMG_a.jpg"), ("VID_b.mp4", None, 0)) == "73 / 161 — IMG_a.jpg"


# ── summary_line ─────────────────────────────────────────────────────


def test_a_clean_run_reads_as_done():
    line = summary_line(Summary(total=161, downloaded=90, already_there=71))

    assert line == "Done: 161 items — 90 downloaded, 71 already there."


def test_an_uneventful_run_has_no_dangling_dash():
    assert summary_line(Summary(total=0)) == "Done: 0 items."


def test_a_cancelled_run_says_how_to_resume():
    line = summary_line(Summary(total=161, downloaded=40, cancelled=True))

    assert line.startswith("Cancelled: 161 items — 40 downloaded.")
    assert line.endswith("Start resumes where it left off.")


def test_every_counter_appears_when_present():
    summary = Summary(
        total=10,
        downloaded=1,
        already_there=2,
        videos_skipped=3,
        missing=1,
        dated_by_file_time_only=1,
        errors=["IMG_a.jpg: boom", "IMG_b.jpg: boom"],
    )

    line = summary_line(summary)

    for piece in (
        "1 downloaded",
        "2 already there",
        "3 videos skipped",
        "1 gone from the chat",
        "1 dated by file time only",
        "2 problems",
    ):
        assert piece in line
