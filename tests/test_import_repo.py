import subprocess

import pytest

from skm.config import load_config
from skm.importer import ImporterError, import_repo, upgrade


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """本地 git 仓:skills/alpha(扁平) + skills/engineering/beta(分类)。"""
    r = tmp_path / "srcrepo"
    for rel in ("skills/alpha", "skills/engineering/beta"):
        d = r / rel
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return r


def test_import_whole_repo_one_pack(paths, repo):
    cfg = load_config(paths)
    rep = import_repo(paths, cfg, str(repo), name="mypack")
    assert sorted(rep.installed) == ["alpha", "beta"]
    assert rep.packs == {"mypack": ["alpha", "beta"]}
    cfg2 = load_config(paths)
    assert cfg2.packs["mypack"].skills == ["alpha", "beta"]
    assert cfg2.packs["mypack"].source == str(repo)
    assert (paths.skills / "beta" / "SKILL.md").exists()  # 拍平了


def test_import_split_by_dir(paths, repo):
    cfg = load_config(paths)
    rep = import_repo(paths, cfg, str(repo), name="mp", split_by_dir=True)
    assert rep.packs == {"mp": ["alpha"], "mp-engineering": ["beta"]}


def test_import_records_commit_base_split(paths, repo):
    cfg = load_config(paths)
    rep = import_repo(paths, cfg, str(repo), name="mp", split_by_dir=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    assert rep.commit == head
    cfg2 = load_config(paths)
    for pname in ("mp", "mp-engineering"):
        p = cfg2.packs[pname]
        assert p.commit == head and p.base == "mp" and p.split is True


def test_import_no_skills_raises(paths, tmp_path):
    r = tmp_path / "empty"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "README.md").write_text("x", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
    cfg = load_config(paths)
    with pytest.raises(ImporterError):
        import_repo(paths, cfg, str(r))
    assert "empty" not in load_config(paths).packs


def test_upgrade_uses_source(paths, repo):
    cfg = load_config(paths)
    import_repo(paths, cfg, str(repo), name="mypack")
    (repo / "skills" / "alpha" / "SKILL.md").write_text("v2", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v2")
    cfg = load_config(paths)
    rep = upgrade(paths, cfg, "mypack")
    assert "alpha" in rep.installed   # force 覆盖
    assert (paths.skills / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "v2"


def test_upgrade_without_source_raises(paths):
    cfg = load_config(paths)
    with pytest.raises(ImporterError):
        upgrade(paths, cfg, "ghost")
