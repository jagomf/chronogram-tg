import json

import pytest

from chronogram_tg import config
from chronogram_tg.config import (
    ConfigError,
    Credentials,
    Settings,
    load_credentials,
    load_settings,
    save_settings,
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Keep the developer's own exported credentials out of the tests."""
    monkeypatch.delenv(config.API_ID_KEY, raising=False)
    monkeypatch.delenv(config.API_HASH_KEY, raising=False)


def write_env(tmp_path, body):
    env_file = tmp_path / ".env"
    env_file.write_text(body, encoding="utf-8")
    return env_file


def test_reads_credentials_from_env_file(tmp_path):
    env_file = write_env(tmp_path, "TELEGRAM_API_ID=1234567\nTELEGRAM_API_HASH=abc123\n")

    assert load_credentials(env_file) == Credentials(api_id=1234567, api_hash="abc123")


def test_environment_variables_win_over_the_file(tmp_path, monkeypatch):
    env_file = write_env(tmp_path, "TELEGRAM_API_ID=1111111\nTELEGRAM_API_HASH=from_file\n")
    monkeypatch.setenv(config.API_ID_KEY, "2222222")
    monkeypatch.setenv(config.API_HASH_KEY, "from_environment")

    assert load_credentials(env_file) == Credentials(api_id=2222222, api_hash="from_environment")


def test_missing_env_file_explains_how_to_get_credentials(tmp_path):
    with pytest.raises(ConfigError) as raised:
        load_credentials(tmp_path / "absent.env")

    message = str(raised.value)
    assert "my.telegram.org" in message
    assert "README.md" in message


def test_incomplete_env_file_is_rejected(tmp_path):
    env_file = write_env(tmp_path, "TELEGRAM_API_ID=1234567\nTELEGRAM_API_HASH=\n")

    with pytest.raises(ConfigError):
        load_credentials(env_file)


def test_non_numeric_api_id_is_rejected(tmp_path):
    env_file = write_env(tmp_path, "TELEGRAM_API_ID=abc123\nTELEGRAM_API_HASH=1234567\n")

    with pytest.raises(ConfigError) as raised:
        load_credentials(env_file)

    assert config.API_ID_KEY in str(raised.value)


def test_settings_survive_a_save_and_load_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(filename_template="IMG_{date}_{time}{ms}"), path)

    assert load_settings(path).filename_template == "IMG_{date}_{time}{ms}"


def test_settings_fall_back_to_defaults_when_absent(tmp_path):
    assert load_settings(tmp_path / "absent.json") == Settings()


@pytest.mark.parametrize("body", ["{ not json", '"a string"', '{"filename_template": 42}'])
def test_unusable_settings_file_does_not_stop_the_app(tmp_path, body):
    path = tmp_path / "settings.json"
    path.write_text(body, encoding="utf-8")

    assert load_settings(path) == Settings()


def test_unknown_settings_keys_are_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"filename_template": "{date}", "legacy": "x"}), encoding="utf-8")

    assert load_settings(path) == Settings(filename_template="{date}")
