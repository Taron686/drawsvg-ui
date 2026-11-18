import tomllib

import pytest

import app_info


def test_version_lookup_falls_back_after_invalid_toml(tmp_path, monkeypatch):
    source = tmp_path / "src" / "app_info.py"
    source.parent.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        'version = "1.2.3"\ninvalid = [\n', encoding="utf-8"
    )
    monkeypatch.setattr(app_info, "__file__", str(source))

    assert app_info._read_version_from_pyproject() == "1.2.3"


def test_version_lookup_does_not_hide_unexpected_parser_errors(tmp_path, monkeypatch):
    source = tmp_path / "src" / "app_info.py"
    source.parent.mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(app_info, "__file__", str(source))

    def fail(_content):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(tomllib, "loads", fail)
    with pytest.raises(RuntimeError, match="unexpected failure"):
        app_info._read_version_from_pyproject()
