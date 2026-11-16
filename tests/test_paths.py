"""Tests for cal_widget.paths."""

from pathlib import Path

import pytest

from cal_widget import paths


def test_data_dir_uses_localappdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.data_dir() == tmp_path / "cal-widget"
    assert paths.data_dir().is_dir()


def test_from_source_there_is_no_bundled_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delattr("sys._MEIPASS", raising=False)
    assert paths.bundled_client_path() is None
    assert all(p.name == "credentials.json" for p in paths.credentials_candidates())


def test_own_credentials_come_before_bundled_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path / "bundle"), raising=False)
    candidates = paths.credentials_candidates()
    assert candidates[-1] == tmp_path / "bundle" / paths.BUNDLED_CLIENT_NAME
    assert candidates[0] == tmp_path / "cal-widget" / "credentials.json"


def test_runtime_files_live_outside_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for p in (paths.token_path(), paths.cache_path(), paths.config_path(), paths.log_path()):
        assert p.parent == tmp_path / "cal-widget"
