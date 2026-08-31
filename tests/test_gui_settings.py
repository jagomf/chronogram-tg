"""The settings modal's pure logic; the widgets themselves live in smoke_gui.py."""

from chronogram_tg.gui.settings import CUSTOM_LABEL, preset_for
from chronogram_tg.naming import PRESETS, TemplateError, preview


def test_each_preset_template_maps_back_to_its_name():
    for name, template in PRESETS.items():
        assert preset_for(template) == name


def test_anything_else_is_custom():
    assert preset_for("{kind}-{date}") == CUSTOM_LABEL
    assert preset_for("") == CUSTOM_LABEL


def test_the_custom_label_does_not_shadow_a_real_preset():
    assert CUSTOM_LABEL not in PRESETS


def test_every_preset_produces_a_previewable_pair_of_examples():
    # The dialog renders a photo and a video line for whatever is picked.
    for template in PRESETS.values():
        assert preview(template).endswith(".jpg")
        assert preview(template, "mp4").endswith(".mp4")


def test_the_preview_rejects_what_the_validator_rejects():
    try:
        preview("{unknown}")
    except TemplateError as error:
        assert "{unknown}" in str(error)
    else:
        raise AssertionError("an unknown token must not preview")
