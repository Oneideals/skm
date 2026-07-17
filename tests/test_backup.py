import subprocess

import pytest

from skm import backup
from skm.config import ToolCfg, load_config, save_config
from skm.state import ToolState, save_state


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True)


@pytest.fixture
def bare(tmp_path):
    b = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(b)], check=True,
                   capture_output=True)
    # 模拟 CI/无 init.defaultBranch 环境:裸仓 HEAD 指向 master(而 skm 只推 main)
    subprocess.run(["git", "-C", str(b), "symbolic-ref", "HEAD",
                    "refs/heads/master"], check=True, capture_output=True)
    return b


def test_init_and_autosync_push(paths, bare, make_skill):
    make_skill("s1")
    backup.init_repo(paths, str(bare))
    log = _git(bare, "log", "--oneline", "main").stdout
    assert "skm backup init" in log                       # 首推已到远端
    # 变更 → autosync 推送
    cfg = load_config(paths)
    cfg.universal = ["s1"]
    save_config(paths, cfg)                               # 内部 mark_dirty
    backup.autosync(paths, "use test", wait=True)
    log = _git(bare, "log", "--oneline", "main").stdout
    assert "skm: use test" in log


def test_autosync_noop_without_init(paths, make_skill):
    make_skill("s1")
    cfg = load_config(paths)
    cfg.universal = ["s1"]
    save_config(paths, cfg)
    backup.autosync(paths, "x", wait=True)                # 不应抛错、不建 .git
    assert not (paths.home / ".git").exists()


def test_restore_relinks(paths, bare, make_skill, tool_dir):
    make_skill("s1")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    cfg.universal = ["s1"]
    save_config(paths, cfg)
    save_state(paths, {"claude": ToolState(groups=[], links=["s1"])})
    backup.init_repo(paths, str(bare))
    backup.autosync(paths, "seed", wait=True)
    # 模拟换机:清空 home 与工具目录里的链
    import shutil
    shutil.rmtree(paths.home)
    (tool_dir / "s1").unlink(missing_ok=True)
    rep = backup.restore(paths, str(bare))
    assert (paths.home / "skills" / "s1" / "SKILL.md").exists()
    assert (tool_dir / "s1").is_symlink()                 # 已按 state 重链
    assert rep["tools"] == ["claude"]


def test_restore_existing_requires_force(paths, bare, make_skill):
    make_skill("s1")
    backup.init_repo(paths, str(bare))
    with pytest.raises(backup.BackupError):
        backup.restore(paths, str(bare))                  # 已存在,无 --force
    rep = backup.restore(paths, str(bare), force=True)
    assert rep["safety"] and (paths.home / "skills").exists()
