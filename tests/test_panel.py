import pytest

from skm.config import Group, Pack, ToolCfg, load_config
from skm.panel import PanelError, apply_payload, build_state, skill_description
from skm.state import load_state


def _skill(paths, name, frontmatter):
    d = paths.skills / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(frontmatter, encoding="utf-8")
    return d


def test_description_inline_quoted(paths):
    d = _skill(paths, "a", '---\nname: a\ndescription: "Hello world."\n---\nbody\n')
    assert skill_description(d) == "Hello world."


def test_description_block_scalar(paths):
    d = _skill(paths, "b", "---\nname: b\ndescription: >\n  Line one\n  line two\nother: x\n---\n")
    assert skill_description(d) == "Line one line two"


def test_description_missing(paths):
    d = _skill(paths, "c", "---\nname: c\n---\nbody\n")
    assert skill_description(d) == ""


def test_build_state_three_layers(paths, make_skill, tool_dir):
    for s in ("uni", "h-only", "cd"):
        make_skill(s)
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir),
                 "hermes": ToolCfg(path=tool_dir.parent / "h", skills=["h-only"])}
    cfg.universal = ["uni"]
    cfg.groups["coding"] = Group(skills=["cd"], label="写代码")
    st = build_state(paths, cfg)
    assert [s["name"] for s in st["skills"]] == ["cd", "h-only", "uni"]
    assert st["universal"] == ["uni"]
    assert st["tools"]["hermes"]["skills"] == ["h-only"]
    assert st["tools"]["claude"]["groups"] == []
    assert st["groups"]["coding"] == {"label": "写代码", "skills": ["cd"], "packs": []}


def test_apply_payload_writes_and_applies(paths, make_skill, tool_dir):
    for s in ("uni", "h-only", "cd", "ds"):
        make_skill(s)
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir),
                 "hermes": ToolCfg(path=tool_dir.parent / "h")}
    payload = {
        "universal": ["uni"],
        "tools": {
            "claude": {"skills": [], "groups": ["coding", "design"]},
            "hermes": {"skills": ["h-only"], "groups": []},
        },
        "groups": {
            "coding": {"label": "写代码", "skills": ["cd"], "packs": []},
            "design": {"label": "做设计", "skills": ["ds"], "packs": []},
        },
    }
    apply_payload(paths, cfg, payload)
    c = load_config(paths)
    assert c.universal == ["uni"]
    assert c.tools["hermes"].skills == ["h-only"]
    assert c.groups["coding"].skills == ["cd"]
    # 保存即应用:claude 勾了 coding+design → 软链已建
    assert (tool_dir / "cd").is_symlink() and (tool_dir / "ds").is_symlink()
    assert (tool_dir / "uni").is_symlink()
    st = load_state(paths)
    assert st["claude"].groups == ["coding", "design"]
    # hermes 无分组但有专用层 h-only + 通用 uni
    hdir = tool_dir.parent / "h"
    assert (hdir / "h-only").is_symlink() and (hdir / "uni").is_symlink()


def test_apply_rejects_missing_skill(paths, make_skill, tool_dir):
    make_skill("uni")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    payload = {"universal": [], "tools": {}, "groups": {"x": {"skills": ["ghost"]}}}
    with pytest.raises(PanelError, match="ghost"):
        apply_payload(paths, cfg, payload)
    assert load_config(paths).groups == {}


def test_apply_rejects_tool_selecting_unknown_group(paths, make_skill, tool_dir):
    make_skill("cd")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    payload = {"universal": [], "groups": {"coding": {"skills": ["cd"]}},
               "tools": {"claude": {"skills": [], "groups": ["ghost"]}}}
    with pytest.raises(PanelError, match="ghost"):
        apply_payload(paths, cfg, payload)


def test_pool_prefix_family_forms_tree(paths):
    for n in ["ponytail", "ponytail-audit", "ponytail-debt", "ponytail-help",
              "grill-me", "grill-with-docs", "karpathy-guidelines"]:
        _skill(paths, n, f"---\nname: {n}\n---\n")
    pool = build_state(paths, load_config(paths))["pool"]
    assert len(pool["collections"]) == 1
    c = pool["collections"][0]
    assert c["kind"] == "prefix"
    assert c["root"]["name"] == "ponytail"
    assert [m["name"] for m in c["members"]] == \
        ["ponytail-audit", "ponytail-debt", "ponytail-help"]
    # grill-* 无 grill 根 → 散装;karpathy 单个 → 散装
    assert [s["name"] for s in pool["loose"]] == \
        ["grill-me", "grill-with-docs", "karpathy-guidelines"]


def test_pool_covers_every_skill_once(paths):
    for n in ["a", "a-b", "a-b-c", "x", "x-1", "zzz"]:
        _skill(paths, n, f"---\nname: {n}\n---\n")
    pool = build_state(paths, load_config(paths))["pool"]
    seen = [s["name"] for s in pool["loose"]]
    for c in pool["collections"]:
        seen.append(c["root"]["name"])
        seen += [m["name"] for m in c["members"]]
    assert sorted(seen) == ["a", "a-b", "a-b-c", "x", "x-1", "zzz"]   # 不丢
    assert len(seen) == len(set(seen))                               # 不重


def test_pool_present_and_skills_flat_unchanged(paths, make_skill):
    make_skill("solo")
    st = build_state(paths, load_config(paths))
    assert [s["name"] for s in st["skills"]] == ["solo"]   # 扁平表不变
    assert st["pool"]["collections"] == []
    assert [s["name"] for s in st["pool"]["loose"]] == ["solo"]


def test_pool_pack_block_claims_members(paths, make_skill):
    for n in ("tdd", "research", "zzz"):
        make_skill(n)
    cfg = load_config(paths)
    cfg.packs["engineering"] = Pack(skills=["tdd", "research", "ghost"])  # ghost 不在仓
    pool = build_state(paths, cfg)["pool"]
    assert len(pool["collections"]) == 1
    c = pool["collections"][0]
    assert c["kind"] == "pack" and c["name"] == "engineering" and c["root"] is None
    assert [m["name"] for m in c["members"]] == ["research", "tdd"]   # 排序;ghost 忽略
    assert [s["name"] for s in pool["loose"]] == ["zzz"]


def test_pool_pack_beats_prefix_and_dedups(paths, make_skill):
    for n in ("ponytail", "ponytail-audit", "ponytail-debt"):
        make_skill(n)
    cfg = load_config(paths)
    cfg.packs["alpha"] = Pack(skills=["ponytail", "ponytail-audit"])
    cfg.packs["beta"] = Pack(skills=["ponytail-audit"])          # 同名:名序首个认领
    pool = build_state(paths, cfg)["pool"]
    kinds = [(c["kind"], c.get("name") or c["root"]["name"]) for c in pool["collections"]]
    assert ("pack", "alpha") in kinds
    assert ("pack", "beta") not in kinds                          # 成员被 alpha 抢光 → 无块
    alpha = next(c for c in pool["collections"] if c["kind"] == "pack")
    # 前缀感知:成员构成 ponytail 家族 → 根提出来
    assert alpha["root"]["name"] == "ponytail"
    assert [m["name"] for m in alpha["members"]] == ["ponytail-audit"]
    # 前缀树的根被 pack 认领 → 剩余 ponytail-debt 无根,散装
    assert all(c["kind"] == "pack" for c in pool["collections"])
    assert [s["name"] for s in pool["loose"]] == ["ponytail-debt"]
    # 不丢不重(pack 的非空 root 也计入)
    seen = [s["name"] for s in pool["loose"]]
    for c in pool["collections"]:
        if c["root"]:
            seen.append(c["root"]["name"])
        seen += [m["name"] for m in c["members"]]
    assert sorted(seen) == ["ponytail", "ponytail-audit", "ponytail-debt"]
    assert len(seen) == len(set(seen))


def test_pool_pack_prefix_aware_root(paths, make_skill):
    for n in ("pt", "pt-a", "pt-b", "solo"):
        make_skill(n)
    cfg = load_config(paths)
    cfg.packs["ptpack"] = Pack(skills=["pt", "pt-a", "pt-b"])
    pool = build_state(paths, cfg)["pool"]
    c = pool["collections"][0]
    assert c["kind"] == "pack" and c["name"] == "ptpack"
    assert c["root"]["name"] == "pt"                       # 前缀感知:根提出来
    assert [m["name"] for m in c["members"]] == ["pt-a", "pt-b"]
