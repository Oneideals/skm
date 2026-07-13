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
