from skm.config import Pack, Scenario, load_config, resolve_skills, save_config


def test_scenario_direct_skills_resolve(paths, make_skill):
    for s in ("base-s", "loose-1", "loose-2", "pack-s"):
        make_skill(s)
    cfg = load_config(paths)
    cfg.base = ["base-s"]
    cfg.packs["p"] = Pack(skills=["pack-s"])
    cfg.scenarios["mix"] = Scenario(packs=["p"], skills=["loose-1", "loose-2"])
    # base ∪ pack 的 skill ∪ 场景直接 skill
    assert resolve_skills(cfg, "mix") == {"base-s", "pack-s", "loose-1", "loose-2"}


def test_scenario_skills_roundtrip(paths):
    cfg = load_config(paths)
    cfg.scenarios["s"] = Scenario(packs=[], skills=["a", "b"], label="演示")
    save_config(paths, cfg)
    cfg2 = load_config(paths)
    assert cfg2.scenarios["s"].skills == ["a", "b"]
    assert cfg2.scenarios["s"].label == "演示"
    assert cfg2.scenarios["s"].packs == []


def test_scenario_skills_only_no_packs(paths, make_skill):
    make_skill("only")
    cfg = load_config(paths)
    cfg.scenarios["s"] = Scenario(skills=["only"])
    assert resolve_skills(cfg, "s") == {"only"}


def test_old_config_without_skills_field(paths):
    cfg = load_config(paths)
    # 手写一个没有 skills 字段的旧式场景
    paths.config.write_text(
        '[tools]\nclaude = "~/.claude/skills"\n\n[base]\nskills = []\n\n'
        '[packs.p]\nskills = ["x"]\n\n[scenarios.old]\npacks = ["p"]\n',
        encoding="utf-8")
    cfg2 = load_config(paths)
    assert cfg2.scenarios["old"].skills == []   # 向后兼容:缺字段 → 空
    assert cfg2.scenarios["old"].packs == ["p"]
