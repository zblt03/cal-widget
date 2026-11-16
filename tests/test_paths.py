"""Tests for cal_widget.paths."""

from pathlib import Path

import pytest

from cal_widget import paths


def test_data_dir_uses_localappdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.data_dir() == tmp_path / "cal-widget"
    assert paths.data_dir().is_dir()


def test_runtime_files_live_outside_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for p in (paths.token_path(), paths.cache_path(), paths.config_path(), paths.log_path()):
        assert p.parent == tmp_path / "cal-widget"
