from skm import boundary, linker


def test_skill_name_from_frontmatter(paths, make_skill):
    d = make_skill("alpha")
    assert boundary.skill_name(d / "SKILL.md") == "alpha"


def test_skill_name_falls_back_to_dirname(paths, tool_dir):
    d = tool_dir / "beta"
    d.mkdir()
    (d / "SKILL.md").write_text("no frontmatter here\n", encoding="utf-8")
    assert boundary.skill_name(d / "SKILL.md") == "beta"


def test_foreign_names_includes_native_excludes_skm_links(paths, make_skill, tool_dir):
    # 工具自带:嵌套真目录(非 skm 建)
    nat = tool_dir / "cat" / "native-skill"
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: native-skill\n---\n", encoding="utf-8")
    # skm 链(指向中央仓)不算外来
    make_skill("mine")
    linker.create_link(paths, tool_dir, "mine")
    names = boundary.foreign_skill_names(paths, tool_dir)
    assert "native-skill" in names
    assert "mine" not in names


def test_foreign_names_empty_when_dir_absent(paths, tmp_path):
    assert boundary.foreign_skill_names(paths, tmp_path / "nope") == set()


from skm.config import ToolCfg, load_config, save_config


def _cfg_one_tool(paths, tool_dir):
    c = load_config(paths)
    c.tools = {"claude": ToolCfg(path=tool_dir)}
    save_config(paths, c)
    return c


def test_prune_collisions_removes_only_colliding_skm_links(paths, tool_dir, make_skill):
    make_skill("plan")
    make_skill("solo")
    linker.create_link(paths, tool_dir, "plan")
    linker.create_link(paths, tool_dir, "solo")
    nat = tool_dir / "sd" / "plan"
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: plan\n---\n", encoding="utf-8")
    cfg = _cfg_one_tool(paths, tool_dir)

    dry = boundary.prune_collisions(paths, cfg, apply=False)
    assert dry.removed == ["claude/plan"]
    assert (tool_dir / "plan").is_symlink()             # dry-run 不动

    boundary.prune_collisions(paths, cfg, apply=True)
    assert not (tool_dir / "plan").exists()             # 撞名链删了
    assert (tool_dir / "solo").is_symlink()             # 不撞名的留着
    assert (nat / "SKILL.md").exists()                  # 工具自带真身不动


from skm.config import Group, Pack


def test_purge_candidates_and_dry_run(paths, tool_dir, make_skill):
    make_skill("plan")                                  # 与工具自带撞名 → 应 purge
    make_skill("mine")                                  # 纯自有 → 保留
    nat = tool_dir / "sd" / "plan"
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: plan\n---\n", encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    cfg.groups["coding"] = Group(skills=["plan", "mine"])
    save_config(paths, cfg)

    assert boundary.purge_candidates(paths, cfg) == {"plan"}

    rep = boundary.sync_boundary(paths, cfg, apply=False)
    assert rep.purge == ["plan"]
    assert "groups.coding:plan" in rep.deref
    assert rep.applied is False
    assert (paths.skills / "plan" / "SKILL.md").exists()   # 预览不删
    assert "plan" in load_config(paths).groups["coding"].skills  # 预览不改 config


from skm.state import load_state
from skm.switcher import use


def test_sync_boundary_apply_purges_copies_links_and_refs(paths, tool_dir, make_skill):
    make_skill("plan")                                  # 撞名 → purge
    make_skill("mine")                                  # 保留
    nat = tool_dir / "sd" / "plan"
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: plan\n---\n", encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    cfg.groups["coding"] = Group(skills=["plan", "mine"])
    save_config(paths, cfg)
    # 先给 claude 建一条 plan 的 skm 链并登记到 state
    linker.create_link(paths, tool_dir, "plan")
    from skm.state import ToolState, save_state
    save_state(paths, {"claude": ToolState(groups=["coding"], links=["plan", "mine"])})

    rep = boundary.sync_boundary(paths, cfg, apply=True)
    assert rep.applied is True
    assert rep.purge == ["plan"]
    # 中央仓副本删除,保留 mine
    assert not (paths.skills / "plan").exists()
    assert (paths.skills / "mine" / "SKILL.md").exists()
    # skm 撞名链删除,工具自带真身保留
    assert not (tool_dir / "plan").exists()
    assert (nat / "SKILL.md").exists()
    # config 引用摘除
    assert "plan" not in load_config(paths).groups["coding"].skills
    assert "mine" in load_config(paths).groups["coding"].skills
    # state 里 plan 去掉、mine 保留
    assert load_state(paths)["claude"].links == ["mine"]
    # 有备份 → 可回滚
    assert list(paths.backups.glob("claude-*.json"))
    # config.toml 也快照到 backups(2a)
    assert list(paths.backups.glob("config-*.toml"))


def test_owned_skill_names_manifest_and_tree(paths, make_skill, tool_dir, tmp_path):
    nat = tool_dir / "native"
    nat.mkdir()
    (nat / "SKILL.md").write_text("---\nname: native\n---\n", encoding="utf-8")
    make_skill("mine")
    linker.create_link(paths, tool_dir, "mine")
    manifest = tmp_path / "managed.json"
    manifest.write_text('{"webby": {"owner": "x"}}', encoding="utf-8")
    shipped = tmp_path / "bundle" / "cat" / "shipped"
    shipped.mkdir(parents=True)
    (shipped / "SKILL.md").write_text("---\nname: shipped\n---\n", encoding="utf-8")
    tc = ToolCfg(path=tool_dir, owned_sources=[manifest, tmp_path / "bundle"])
    names = boundary.owned_skill_names(paths, tc)
    assert {"native", "webby", "shipped"} <= names
    assert "mine" not in names                      # skm 链不算工具所有


def test_owned_skill_names_manifest_array(paths, tool_dir, tmp_path):
    m = tmp_path / "list.json"
    m.write_text('["a", "b"]', encoding="utf-8")
    tc = ToolCfg(path=tool_dir, owned_sources=[m])
    assert {"a", "b"} <= boundary.owned_skill_names(paths, tc)


def test_owned_skill_names_missing_source_skipped(paths, tool_dir, tmp_path):
    tc = ToolCfg(path=tool_dir,
                 owned_sources=[tmp_path / "nope.json", tmp_path / "nodir"])
    assert boundary.owned_skill_names(paths, tc) == set()


def test_owned_source_dir_excludes_skm_links(paths, make_skill, tmp_path):
    faux_live = tmp_path / "live"
    faux_live.mkdir()
    make_skill("mine")
    linker.create_link(paths, faux_live, "mine")
    tc = ToolCfg(path=tmp_path / "none", owned_sources=[faux_live])
    assert "mine" not in boundary.owned_skill_names(paths, tc)


def test_purge_candidates_via_owned_source(paths, make_skill, tool_dir, tmp_path):
    make_skill("webby")                     # 中央仓有 webby
    manifest = tmp_path / "managed.json"
    manifest.write_text('{"webby": {}}', encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"hermes": ToolCfg(path=tool_dir, owned_sources=[manifest])}
    save_config(paths, cfg)
    # tool_dir 里没有 webby 的物理真身,仅清单声明 → 仍应被判为工具血统
    assert "webby" in boundary.purge_candidates(paths, cfg)
