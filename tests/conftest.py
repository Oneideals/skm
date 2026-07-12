from pathlib import Path

import pytest

from skm.paths import Paths


@pytest.fixture
def paths(tmp_path) -> Paths:
    p = Paths(home=tmp_path / "skm")
    p.ensure()
    return p


@pytest.fixture
def make_skill(paths):
    def _make(name: str) -> Path:
        d = paths.skills / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
        return d
    return _make


@pytest.fixture
def tool_dir(tmp_path) -> Path:
    d = tmp_path / "tools" / "claude"
    d.mkdir(parents=True)
    return d
