"""系统 review 发现的缺陷回归测试 (TDD)。

每个测试对应一个在全面 review 中确认的真实缺陷:
- disable 未知分组静默 no-op(拼错分组名无反馈)
- 裸跑 pytest 因缺 pythonpath 配置而 ModuleNotFoundError
- upgrade_source 对无 base 的存量多 pack 用字符级 commonprefix 推断 base
- import_repo 同名 skill 目录静默覆盖且无告警
"""
from __future__ import annotations

import json
import subprocess

import pytest

from skm.config import Group, Pack, ToolCfg, load_config, save_config
from skm.importer import upgrade_source
from skm.state import load_state
from skm.switcher import SwitchError, disable, enable, use


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


# --- 缺陷 1: disable 未知分组静默吞掉 -----------------------------------
def test_disable_unknown_group_raises(paths, make_skill, tool_dir):
    """disable 一个不存在的分组应像 enable 一样报错,而非静默 no-op。

    现状: disable 做 set(cur) - {group},未知 group 被无声忽略;
    用户拼错分组名(如 'desgin')得不到任何反馈,以为已关闭。
    """
    for s in ("s1",):
        make_skill(s)
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    cfg.groups = {"design": Group(skills=["s1"])}
    save_config(paths, cfg)
    cfg = load_config(paths)

    with pytest.raises(SwitchError, match="desgin"):
        disable(paths, cfg, "claude", "desgin")


# --- 缺陷 2: 裸跑 pytest 的 pythonpath 配置 -----------------------------
def test_bare_pytest_runs(monkeypatch):
    """`pytest -q`(非 python -m pytest)能收集通过,依赖 pythonpath 配置。

    项目无 pyproject.toml/pytest.ini 声明 pythonpath,裸跑在导入 conftest 时
    就 ModuleNotFoundError。CI 因用 python -m pytest(隐式加 cwd)侥幸通过。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    cfg_files = ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini")
    has_pythonpath = False
    for name in cfg_files:
        f = root / name
        if f.exists():
            text = f.read_text(encoding="utf-8")
            if "pythonpath" in text and "." in text:
                has_pythonpath = True
                break
    assert has_pythonpath, "缺少 pytest pythonpath 配置,裸跑 pytest 会失败"


# --- 缺陷 3: upgrade_source 字符级 commonprefix 推断 base ---------------
def test_upgrade_legacy_base_infers_on_word_boundary(paths, tmp_path):
    """无 base 的存量多 pack,推断 base 必须在词边界切分,不能字符截断。

    'coding-skills' + 'coding-style' 的字符公共前缀是 'coding-s',
    用它当 base 会让 import_repo 生成 'coding-s'/'coding-s-*' 这类
    不存在的 pack,把原 pack 名单清空。正确应回退到不猜测或按 '-' 边界。
    """
    r = tmp_path / "srcrepo"
    for rel in ("skills/coding-skills/a", "skills/coding-style/b"):
        d = r / rel
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")

    cfg = load_config(paths)
    # 存量:两个同源 pack,无 base/split 记录(二期前 --split-by-dir 产物)
    cfg.packs["coding-skills"] = Pack(skills=["a"], source=str(r))
    cfg.packs["coding-style"] = Pack(skills=["b"], source=str(r))
    save_config(paths, cfg)
    cfg = load_config(paths)

    rep = upgrade_source(paths, cfg, str(r))
    cfg2 = load_config(paths)
    # 关键断言:不能因为 base 推断错误把已有 pack 的 skills 清空/串包
    assert cfg2.packs["coding-skills"].skills == ["a"], (
        "base 被错误推断为字符前缀,导致原 pack 名单被清空")
    assert cfg2.packs["coding-style"].skills == ["b"]


# --- 缺陷 4: import_repo 同名 skill 目录静默覆盖 ------------------------
def test_import_reports_duplicate_skill_dirs(paths, tmp_path):
    """同一仓库里两个目录同名(basename 相同)时,拍平导入会静默覆盖。

    用户无从得知其中一个 SKILL.md 已被另一个覆盖。至少应在 report 里
    暴露被折叠的重复名,或拒绝导入,避免"看起来装了其实丢了一个"。
    """
    from skm.importer import import_repo

    r = tmp_path / "srcrepo"
    for rel in ("skills/team-a/plan", "skills/team-b/plan"):
        d = r / rel
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {rel.split('/')[1]}-plan\n---\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")

    cfg = load_config(paths)
    rep = import_repo(paths, cfg, str(r), name="dup")
    # 两个目录都叫 plan,拍平后中央仓只有一份 -> 必然丢失一个
    # 期望: report 明确暴露重复(有 dup 字段),而非静默
    assert hasattr(rep, "duplicates"), "import_report 缺少重复名暴露机制"
    assert "plan" in rep.duplicates, "同名目录折叠未被报告"
