import pytest

from skm.config import Pack, Scenario, load_config, save_config
from skm.state import load_state
from skm.switcher import SwitchError, use


@pytest.fixture
def cfg(paths, tool_dir, make_skill):
    for s in ("base-a", "s1", "s2", "s3"):
        make_skill(s)
    c = load_config(paths)
    c.tools = {"claude": tool_dir}
    c.base = ["base-a"]
    c.packs["p1"] = Pack(skills=["s1", "s2"])
    c.packs["p2"] = Pack(skills=["s3"])
    c.scenarios["one"] = Scenario(packs=["p1"], label="一")
    c.scenarios["two"] = Scenario(packs=["p2"])
    save_config(paths, c)
    return c


def test_use_links_base_and_scenario(paths, cfg, tool_dir):
    rep = use(paths, cfg, "claude", "one")
    assert sorted(rep.created) == ["base-a", "s1", "s2"]
    st = load_state(paths)
    assert st["claude"].scenario == "one"
    assert st["claude"].links == ["base-a", "s1", "s2"]
    assert (tool_dir / "s1").is_symlink()


def test_switch_scenario_diffs(paths, cfg, tool_dir):
    use(paths, cfg, "claude", "one")
    rep = use(paths, cfg, "claude", "two")
    assert rep.removed == ["s1", "s2"]
    assert rep.created == ["s3"]
    assert rep.kept == ["base-a"]          # base 原地不动
    assert not (tool_dir / "s1").exists()
    assert (tool_dir / "s3").is_symlink()


def test_reset_to_base_only(paths, cfg, tool_dir):
    use(paths, cfg, "claude", "one")
    rep = use(paths, cfg, "claude", None)
    assert rep.removed == ["s1", "s2"]
    assert load_state(paths)["claude"].links == ["base-a"]
    assert load_state(paths)["claude"].scenario is None


def test_idempotent(paths, cfg):
    use(paths, cfg, "claude", "one")
    rep = use(paths, cfg, "claude", "one")
    assert rep.created == [] and rep.removed == []


def test_missing_skill_aborts_before_touching_fs(paths, cfg, tool_dir):
    cfg.packs["p1"].skills.append("ghost")
    with pytest.raises(SwitchError, match="ghost"):
        use(paths, cfg, "claude", "one")
    assert not (tool_dir / "s1").exists()   # 未动文件系统


def test_unknown_tool(paths, cfg):
    with pytest.raises(SwitchError):
        use(paths, cfg, "vim", "one")


def test_never_touches_user_dirs(paths, cfg, tool_dir):
    (tool_dir / "my-own").mkdir()           # 用户手工目录
    use(paths, cfg, "claude", "one")
    use(paths, cfg, "claude", None)
    assert (tool_dir / "my-own").is_dir()   # 全程无恙
