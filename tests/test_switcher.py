import pytest

from skm.config import Group, Pack, ToolCfg, load_config, save_config
from skm.state import load_state
from skm.switcher import SwitchError, disable, enable, use


@pytest.fixture
def cfg(paths, tool_dir, make_skill):
    for s in ("uni", "h-only", "cd1", "cd2", "ds1", "pk"):
        make_skill(s)
    c = load_config(paths)
    c.tools = {"claude": ToolCfg(path=tool_dir),
               "hermes": ToolCfg(path=tool_dir.parent / "hermes", skills=["h-only"])}
    c.universal = ["uni"]
    c.packs["p"] = Pack(skills=["pk"])
    c.groups["coding"] = Group(skills=["cd1", "cd2"], packs=["p"])
    c.groups["design"] = Group(skills=["ds1"])
    save_config(paths, c)
    return c


def test_use_universal_plus_group(paths, cfg, tool_dir):
    rep = use(paths, cfg, "claude", ["coding"])
    # 通用 uni + 分组 coding(cd1,cd2 + pack pk)
    assert sorted(rep.created) == ["cd1", "cd2", "pk", "uni"]
    st = load_state(paths)
    assert st["claude"].groups == ["coding"]
    assert (tool_dir / "cd1").is_symlink()


def test_use_multiple_groups(paths, cfg, tool_dir):
    rep = use(paths, cfg, "claude", ["coding", "design"])
    assert sorted(rep.created) == ["cd1", "cd2", "ds1", "pk", "uni"]
    assert load_state(paths)["claude"].groups == ["coding", "design"]


def test_tool_specific_layer_always_on(paths, cfg):
    # hermes 有专用层 h-only,即使不勾选任何分组也在
    hdir = cfg.tools["hermes"].path
    rep = use(paths, cfg, "hermes", [])
    assert sorted(rep.created) == ["h-only", "uni"]
    assert (hdir / "h-only").is_symlink()


def test_enable_disable_toggles_groups(paths, cfg, tool_dir):
    use(paths, cfg, "claude", ["coding"])
    enable(paths, cfg, "claude", "design")
    assert load_state(paths)["claude"].groups == ["coding", "design"]
    assert (tool_dir / "ds1").is_symlink()
    rep = disable(paths, cfg, "claude", "coding")
    assert load_state(paths)["claude"].groups == ["design"]
    assert not (tool_dir / "cd1").exists()   # coding 的 skill 移除
    assert (tool_dir / "ds1").is_symlink()   # design 仍在
    assert (tool_dir / "uni").is_symlink()   # 通用仍在


def test_use_empty_keeps_universal_and_tool(paths, cfg, tool_dir):
    use(paths, cfg, "claude", ["coding"])
    rep = use(paths, cfg, "claude", [])
    assert rep.removed == ["cd1", "cd2", "pk"]
    assert load_state(paths)["claude"].links == ["uni"]   # 通用保留,claude 无专用层


def test_diff_between_group_sets(paths, cfg, tool_dir):
    use(paths, cfg, "claude", ["coding"])
    rep = use(paths, cfg, "claude", ["design"])
    assert rep.removed == ["cd1", "cd2", "pk"]
    assert rep.created == ["ds1"]
    assert rep.kept == ["uni"]                # 通用原地不动


def test_unknown_group_aborts(paths, cfg, tool_dir):
    with pytest.raises(SwitchError, match="nope"):
        use(paths, cfg, "claude", ["nope"])
    assert not (tool_dir / "uni").exists()


def test_missing_skill_aborts_before_fs(paths, cfg, tool_dir):
    cfg.groups["coding"].skills.append("ghost")
    with pytest.raises(SwitchError, match="ghost"):
        use(paths, cfg, "claude", ["coding"])
    assert not (tool_dir / "cd1").exists()


def test_never_touches_user_dirs(paths, cfg, tool_dir):
    (tool_dir / "my-own").mkdir()
    use(paths, cfg, "claude", ["coding"])
    use(paths, cfg, "claude", [])
    assert (tool_dir / "my-own").is_dir()
