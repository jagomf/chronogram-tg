"""The About modal's pure logic; the widget itself lives in smoke_gui.py."""

from chronogram_tg.gui.about import DIRECT_DEPENDENCIES, dependency_licences


def test_every_direct_dependency_reports_name_version_and_licence():
    rows = dependency_licences()

    assert len(rows) == len(DIRECT_DEPENDENCIES)
    for name, version, licence in rows:
        assert name and version and licence


def test_the_licences_are_names_not_full_texts():
    for _name, _version, licence in dependency_licences():
        assert len(licence) < 60
        assert "\n" not in licence


def test_telethon_is_among_the_credited_packages():
    names = [name.lower() for name, _version, _licence in dependency_licences()]

    assert "telethon" in names
