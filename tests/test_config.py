"""Tests for cal_widget.config."""

import json
from pathlib import Path

import pytest

from cal_widget.config import Config, load_config, parse_config


def test_first_run_creates_file_with_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    assert load_config(path) == Config()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "refresh_minutes": 5,
        "show_tomorrow": True,
        "bar_uses_calendar_color": False,
        "max_title_chars": 40,
        "excluded_calendars": [],
    }


def test_valid_values_are_used(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "refresh_minutes": 10,
                "show_tomorrow": False,
                "bar_uses_calendar_color": True,
                "max_title_chars": 25,
                "excluded_calendars": ["Holidays in Spain"],
            }
        ),
        encoding="utf-8",
    )
    assert load_config(path) == Config(10, False, True, 25, ["Holidays in Spain"])


def test_missing_keys_get_defaults() -> None:
    assert parse_config({"refresh_minutes": 15}) == Config(refresh_minutes=15)


@pytest.mark.parametrize(
    ("key", "bad_value"),
    [
        ("refresh_minutes", 0),
        ("refresh_minutes", 500),
        ("refresh_minutes", "5"),
        ("refresh_minutes", 2.5),
        ("refresh_minutes", True),  # bool is an int in Python: must still be rejected
        ("show_tomorrow", "yes"),
        ("show_tomorrow", 1),
        ("bar_uses_calendar_color", None),
        ("max_title_chars", -1),
        ("excluded_calendars", "Work"),
        ("excluded_calendars", ["Work", 3]),
    ],
)
def test_bad_value_falls_back_to_default_and_logs(
    key: str, bad_value: object, caplog: pytest.LogCaptureFixture
) -> None:
    config = parse_config({key: bad_value})
    assert getattr(config, key) == getattr(Config(), key)
    assert key in caplog.text


def test_one_bad_value_keeps_the_good_ones() -> None:
    config = parse_config({"refresh_minutes": -3, "show_tomorrow": False})
    assert config == Config(show_tomorrow=False)


def test_unknown_key_is_ignored_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    assert parse_config({"colour": "red"}) == Config()
    assert "colour" in caplog.text


def test_not_an_object_uses_defaults() -> None:
    assert parse_config([1, 2, 3]) == Config()


def test_file_with_utf8_bom_is_read(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"max_title_chars": 12}', encoding="utf-8-sig")  # starts with a BOM
    assert load_config(path).max_title_chars == 12


def test_broken_json_uses_defaults_and_keeps_file(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"refresh_minutes": 10,', encoding="utf-8")
    assert load_config(path) == Config()
    assert path.read_text(encoding="utf-8") == '{"refresh_minutes": 10,'  # not overwritten
