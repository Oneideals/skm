import pytest

from skm.config import (ConfigError, Pack, Scenario, load_config,
                        missing_in_repo, resolve_skills, save_config)


def test_load_creates_default(paths):
    cfg = load_config(paths)
    assert set(cfg.tools) == {"claude", "codex", "grok", "hermes"}
    assert cfg.base == [] and cfg.packs == {} and cfg.scenarios == {}
    assert paths.config.exists()


def test_roundtrip_with_chinese_label(paths):
    cfg = load_config(paths)
    cfg.base = ["code-review"]
    cfg.packs["research"] = Pack(skills=["web-research", "arxiv"], source="https://x/y.git")
    cfg.scenarios["research"] = Scenario(packs=["research"], label="调研")
    save_config(paths, cfg)
    cfg2 = load_config(paths)
    assert cfg2.packs["research"].skills == ["arxiv", "web-research"]  # 保存时排序
    assert cfg2.packs["research"].source == "https://x/y.git"
    assert cfg2.scenarios["research"].label == "调研"
    assert cfg2.base == ["code-review"]


def test_resolve_skills_union_and_dedupe(paths):
    cfg = load_config(paths)
    cfg.base = ["base-skill"]
    cfg.packs["a"] = Pack(skills=["s1", "s2"])
    cfg.packs["b"] = Pack(skills=["s2", "s3"])
    cfg.scenarios["mix"] = Scenario(packs=["a", "b"])
    assert resolve_skills(cfg, "mix") == {"base-skill", "s1", "s2", "s3"}
    assert resolve_skills(cfg, None) == {"base-skill"}


def test_resolve_unknown_scenario_raises(paths):
    cfg = load_config(paths)
    with pytest.raises(ConfigError):
        resolve_skills(cfg, "nope")


def test_scenario_referencing_missing_pack_raises(paths):
    cfg = load_config(paths)
    cfg.scenarios["bad"] = Scenario(packs=["ghost"])
    save_config(paths, cfg)
    with pytest.raises(ConfigError):
        load_config(paths)


def test_invalid_id_rejected_on_load(paths):
    load_config(paths)
    text = paths.config.read_text(encoding="utf-8")
    paths.config.write_text(text + '\n[packs."Bad Name"]\nskills = []\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(paths)


def test_missing_in_repo(paths, make_skill):
    make_skill("here")
    assert missing_in_repo(paths, {"here", "gone"}) == ["gone"]
