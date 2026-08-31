"""The login window's pure logic; the widgets themselves live in smoke_gui.py."""

import pytest

from chronogram_tg.gui.login import CODE_STEP, PASSWORD_STEP, PHONE_STEP, sanitise


def test_a_clean_phone_number_passes_through():
    assert sanitise("+34600112233", PHONE_STEP) == "+34600112233"


def test_a_pasted_phone_number_is_stripped_of_decoration():
    assert sanitise("+34 600-11.22.33 ", PHONE_STEP) == "+34600112233"
    assert sanitise("tel: +34 600 112 233", PHONE_STEP) == "+34600112233"


def test_the_plus_only_survives_at_the_front():
    assert sanitise("+34+600", PHONE_STEP) == "+34600"
    assert sanitise("34+600", PHONE_STEP) == "34600"


def test_a_login_code_keeps_only_digits():
    assert sanitise("12345", CODE_STEP) == "12345"
    assert sanitise(" 1 2 3 4 5 ", CODE_STEP) == "12345"
    assert sanitise("+12345", CODE_STEP) == "12345"


def test_a_password_is_never_touched():
    password = " hunter2 +*? con espacios "
    assert sanitise(password, PASSWORD_STEP) == password


@pytest.mark.parametrize("step", [PHONE_STEP, CODE_STEP, PASSWORD_STEP])
def test_an_empty_value_stays_empty(step):
    assert sanitise("", step) == ""
