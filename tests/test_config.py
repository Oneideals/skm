import pytest

from skm.config import (ConfigError, Group, Pack, ToolCfg, load_config,
                        missing_in_repo, resolve_for_tool, save_config)


def test_load_creates_default(paths):
    cfg = load_config(paths)
    assert set(cfg.tools) == {"claude", "codex", "grok", "hermes"}
    assert cfg.universal == [] and cfg.packs == {} and cfg.groups == {}
    assert all(t.skills == [] for t in cfg.tools.values())
    assert paths.config.exists()


def test_roundtrip_all_three_layers(paths):
    cfg = load_config(paths)
    cfg.universal = ["using-superpowers"]
    cfg.tools["hermes"].skills = ["hermes-agent", "petdex"]
    cfg.packs["sp"] = Pack(skills=["tdd"], source="https://x/y.git")
    cfg.groups["coding"] = Group(skills=["debug"], packs=["sp"], label="写代码")
    save_config(paths, cfg)
    c = load_config(paths)
    assert c.universal == ["using-superpowers"]
    assert c.tools["hermes"].skills == ["hermes-agent", "petdex"]
    assert c.packs["sp"].skills == ["tdd"] and c.packs["sp"].source == "https://x/y.git"
    assert c.groups["coding"].skills == ["debug"]
    assert c.groups["coding"].packs == ["sp"]
    assert c.groups["coding"].label == "写代码"


def test_resolve_three_layer_union(paths):
    cfg = load_config(paths)
    cfg.universal = ["u1"]
    cfg.tools["claude"].skills = ["c-only"]
    cfg.tools["hermes"].skills = ["h-only"]
    cfg.packs["p"] = Pack(skills=["pk"])
    cfg.groups["coding"] = Group(skills=["cd"], packs=["p"])
    cfg.groups["design"] = Group(skills=["ds"])
    # claude 勾选 coding+design:通用 ∪ claude专用 ∪ 两个分组
    assert resolve_for_tool(cfg, "claude", ["coding", "design"]) == {
        "u1", "c-only", "cd", "pk", "ds"}
    # hermes 不勾选任何分组:只有通用 ∪ hermes专用
    assert resolve_for_tool(cfg, "hermes", []) == {"u1", "h-only"}


def test_resolve_dedupes_across_groups(paths):
    cfg = load_config(paths)
    cfg.groups["a"] = Group(skills=["shared", "a1"])
    cfg.groups["b"] = Group(skills=["shared", "b1"])
    assert resolve_for_tool(cfg, "claude", ["a", "b"]) == {"shared", "a1", "b1"}


def test_resolve_unknown_group_raises(paths):
    cfg = load_config(paths)
    with pytest.raises(ConfigError):
        resolve_for_tool(cfg, "claude", ["nope"])


def test_resolve_unknown_tool_raises(paths):
    cfg = load_config(paths)
    with pytest.raises(ConfigError):
        resolve_for_tool(cfg, "vim", [])


def test_group_referencing_missing_pack_raises(paths):
    cfg = load_config(paths)
    cfg.groups["bad"] = Group(packs=["ghost"])
    save_config(paths, cfg)
    with pytest.raises(ConfigError):
        load_config(paths)


def test_invalid_group_id_rejected(paths):
    load_config(paths)
    text = paths.config.read_text(encoding="utf-8")
    paths.config.write_text(text + '\n[groups."Bad Name"]\nskills = []\npacks = []\n',
                            encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(paths)


def test_missing_in_repo(paths, make_skill):
    make_skill("here")
    assert missing_in_repo(paths, {"here", "gone"}) == ["gone"]


def test_owned_sources_roundtrip(paths, tmp_path):
    src1 = tmp_path / "manifest.json"
    src2 = tmp_path / "bundle"
    cfg = load_config(paths)
    cfg.tools = {"hermes": ToolCfg(path=tmp_path / "h", owned_sources=[src1, src2])}
    save_config(paths, cfg)
    got = load_config(paths)
    assert set(got.tools["hermes"].owned_sources) == {src1, src2}


def test_owned_sources_default_empty(paths):
    cfg = load_config(paths)
    assert all(tc.owned_sources == [] for tc in cfg.tools.values())
