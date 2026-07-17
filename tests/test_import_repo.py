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


def test_upgrade_source_split_safe_and_fresh(paths, repo):
    import shutil

    from skm.importer import upgrade_source
    cfg = load_config(paths)
    import_repo(paths, cfg, str(repo), name="mp", split_by_dir=True)
    # 上游:alpha 删除,engineering 新增 gamma
    shutil.rmtree(repo / "skills" / "alpha")
    g = repo / "skills" / "engineering" / "gamma"
    g.mkdir()
    (g / "SKILL.md").write_text("---\nname: gamma\n---\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v2")

    cfg = load_config(paths)
    rep = upgrade_source(paths, cfg, str(repo))

    cfg2 = load_config(paths)
    assert cfg2.packs["mp"].skills == []                       # alpha 上游已删 → fresh 名单为空
    assert cfg2.packs["mp-engineering"].skills == ["beta", "gamma"]
    assert "mp/alpha" in rep.dropped
    assert (paths.skills / "alpha" / "SKILL.md").exists()      # 真身保留(变散装)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    assert cfg2.packs["mp-engineering"].commit == head


def test_upgrade_by_pack_delegates_to_source(paths, repo):
    cfg = load_config(paths)
    import_repo(paths, cfg, str(repo), name="mp", split_by_dir=True)
    (repo / "skills" / "alpha" / "SKILL.md").write_text("v2", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v2")
    cfg = load_config(paths)
    upgrade(paths, cfg, "mp-engineering")                      # 升级任一兄弟 pack
    assert (paths.skills / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "v2"
    cfg2 = load_config(paths)
    assert "beta" in cfg2.packs["mp-engineering"].skills       # 不串包(split 修复)
    assert "alpha" not in cfg2.packs["mp-engineering"].skills  # 整仓不灌进单 pack
    assert cfg2.packs["mp"].skills == ["alpha"]


def test_upgrade_legacy_split_packs_without_base(paths, repo):
    """存量 pack(二期前导入,无 base/split 记录):多 pack 同源 → 必须推断为 split。"""
    from skm.config import Pack, save_config
    from skm.importer import upgrade_source
    cfg = load_config(paths)
    # 模拟旧版 import --split-by-dir 的产物:有 source、无 commit/base/split
    cfg.packs["mp"] = Pack(skills=["alpha"], source=str(repo))
    cfg.packs["mp-engineering"] = Pack(skills=["beta"], source=str(repo))
    save_config(paths, cfg)
    cfg = load_config(paths)

    rep = upgrade_source(paths, cfg, str(repo))

    cfg2 = load_config(paths)
    assert cfg2.packs["mp"].skills == ["alpha"]                # 不被清空
    assert cfg2.packs["mp-engineering"].skills == ["beta"]     # 不被灌成整仓
    assert rep.dropped == []
    assert cfg2.packs["mp"].split is True and cfg2.packs["mp"].base == "mp"
