import pytest

from skm.config import Pack, Scenario, load_config, save_config
from skm.panel import PanelError, apply_payload, build_state, skill_description
from skm.state import ToolState, save_state


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


def test_description_unquoted(paths):
    d = _skill(paths, "e", "---\nname: e\ndescription: Plain text here\n---\n")
    assert skill_description(d) == "Plain text here"


def test_build_state_shape(paths, make_skill):
    make_skill("s1")
    make_skill("s2")
    cfg = load_config(paths)
    cfg.base = ["s1"]
    cfg.packs["p"] = Pack(skills=["s2"])
    cfg.scenarios["research"] = Scenario(packs=["p"], skills=["s1"], label="调研")
    save_state(paths, {"claude": ToolState(scenario="research", links=["s1"])})
    st = build_state(paths, cfg)
    names = [s["name"] for s in st["skills"]]
    assert names == ["s1", "s2"]
    assert all("description" in s for s in st["skills"])
    assert st["base"] == ["s1"]
    assert st["scenarios"]["research"] == {"label": "调研", "packs": ["p"], "skills": ["s1"]}
    assert st["tools"]["claude"] == "research"
    assert st["tools"]["codex"] is None


def test_apply_payload_writes_config(paths, make_skill):
    for s in ("s1", "s2", "s3"):
        make_skill(s)
    cfg = load_config(paths)
    payload = {
        "base": ["s1"],
        "scenarios": {
            "coding": {"label": "写代码", "packs": [], "skills": ["s2", "s3"]},
        },
    }
    apply_payload(paths, cfg, payload)
    cfg2 = load_config(paths)
    assert cfg2.base == ["s1"]
    assert cfg2.scenarios["coding"].skills == ["s2", "s3"]
    assert cfg2.scenarios["coding"].label == "写代码"


def test_apply_payload_rejects_missing_skill(paths, make_skill):
    make_skill("s1")
    cfg = load_config(paths)
    payload = {"base": [], "scenarios": {"x": {"skills": ["ghost"]}}}
    with pytest.raises(PanelError, match="ghost"):
        apply_payload(paths, cfg, payload)
    assert load_config(paths).scenarios == {}   # 未写坏


def test_apply_payload_rejects_bad_id(paths):
    cfg = load_config(paths)
    payload = {"base": [], "scenarios": {"Bad Name": {"skills": []}}}
    with pytest.raises(PanelError):
        apply_payload(paths, cfg, payload)


def test_apply_payload_rejects_unknown_pack(paths):
    cfg = load_config(paths)
    payload = {"base": [], "scenarios": {"x": {"packs": ["ghost"], "skills": []}}}
    with pytest.raises(PanelError, match="ghost"):
        apply_payload(paths, cfg, payload)
