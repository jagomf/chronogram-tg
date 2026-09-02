"""The date-range modal's pure validation; the widget lives in smoke_gui.py."""

from datetime import UTC, datetime

import pytest

from chronogram_tg.gui.date_range import UNSET, YEARS, build_day, validate_range

EMPTY = (UNSET, UNSET, UNSET)


def test_a_full_range_parses_to_utc_days():
    since, until = validate_range(("01", "January", "2023"), ("31", "December", "2023"))

    assert since == datetime(2023, 1, 1, tzinfo=UTC)
    assert until == datetime(2023, 12, 31, tzinfo=UTC)


def test_one_side_may_be_left_open():
    since, until = validate_range(EMPTY, ("15", "August", "2024"))

    assert since is None
    assert until == datetime(2024, 8, 15, tzinfo=UTC)


def test_both_sides_unset_is_not_a_range():
    with pytest.raises(ValueError, match="at least one"):
        validate_range(EMPTY, EMPTY)


def test_a_backwards_range_is_rejected():
    with pytest.raises(ValueError, match="on or before"):
        validate_range(("31", "December", "2023"), ("01", "January", "2023"))


def test_a_half_set_date_asks_to_complete_it():
    with pytest.raises(ValueError, match="Complete the date"):
        build_day("15", UNSET, "2024")


def test_an_impossible_day_is_named_not_crashed_on():
    with pytest.raises(ValueError, match="not a real date"):
        build_day("30", "February", "2023")


def test_the_same_day_twice_is_a_valid_one_day_range():
    since, until = validate_range(("15", "August", "2024"), ("15", "August", "2024"))

    assert since == until


def test_the_year_menu_spans_telegram_history_to_today():
    assert YEARS[0] == "2013"
    assert int(YEARS[-1]) >= 2026
