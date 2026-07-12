from pathlib import Path

from skm.paths import Paths


def test_paths_layout(tmp_path):
    p = Paths(home=tmp_path / "skm")
    assert p.skills == tmp_path / "skm" / "skills"
    assert p.config == tmp_path / "skm" / "config.toml"
    assert p.state == tmp_path / "skm" / "state.json"
    assert p.backups == tmp_path / "skm" / "backups"


def test_from_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SKM_HOME", str(tmp_path / "custom"))
    assert Paths.from_env().home == tmp_path / "custom"


def test_ensure_creates_dirs(tmp_path):
    p = Paths(home=tmp_path / "skm")
    p.ensure()
    assert p.skills.is_dir() and p.backups.is_dir()
