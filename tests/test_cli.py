import pytest

from skm import cli, linker
from skm.cli import main
from skm.config import Group, ToolCfg, load_config, save_config


@pytest.fixture
def env(paths, tool_dir, make_skill, monkeypatch):
    monkeypatch.setenv("SKM_HOME", str(paths.home))
    for s in ("uni", "s1", "s2"):
        make_skill(s)
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    cfg.universal = ["uni"]
    cfg.groups["coding"] = Group(skills=["s1"], label="写代码")
    cfg.groups["design"] = Group(skills=["s2"], label="做设计")
    save_config(paths, cfg)
    return paths, tool_dir


def test_use_multiple_groups_and_list(env, capsys):
    paths, tool_dir = env
    assert main(["use", "claude", "coding", "design"]) == 0
    assert (tool_dir / "s1").is_symlink() and (tool_dir / "s2").is_symlink()
    out = capsys.readouterr().out
    assert "coding" in out and "重启" in out
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "通用层" in out and "coding" in out


def test_enable_disable(env):
    paths, tool_dir = env
    main(["use", "claude", "coding"])
    assert main(["enable", "claude", "design"]) == 0
    assert (tool_dir / "s2").is_symlink()
    assert main(["disable", "claude", "coding"]) == 0
    assert not (tool_dir / "s1").exists()
    assert (tool_dir / "uni").is_symlink()   # 通用保留


def test_reset_and_rollback(env):
    paths, tool_dir = env
    main(["use", "claude", "coding"])
    assert main(["reset", "claude"]) == 0
    assert not (tool_dir / "s1").exists()
    assert (tool_dir / "uni").is_symlink()   # 通用仍在
    assert main(["rollback", "claude"]) == 0
    assert (tool_dir / "s1").is_symlink()


def test_use_unknown_group_fails(env, capsys):
    assert main(["use", "claude", "nope"]) == 1
    assert "不存在" in capsys.readouterr().err


def test_groups_listing(env, capsys):
    assert main(["groups"]) == 0
    out = capsys.readouterr().out
    assert "coding" in out and "写代码" in out


def test_doctor_clean(env, capsys):
    assert main(["doctor"]) == 0
    assert "无问题" in capsys.readouterr().out


def test_doctor_reports_name_collision(paths, tool_dir, make_skill):
    make_skill("plan")
    linker.create_link(paths, tool_dir, "plan")          # skm 链 plan
    nat = tool_dir / "sd" / "plan"                        # 工具自带嵌套同名
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: plan\n---\n", encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    save_config(paths, cfg)
    problems = cli.doctor(paths, cfg)
    assert any("撞名" in p and "plan" in p for p in problems)


def test_doctor_flags_owned_residual(paths, make_skill, tool_dir, tmp_path):
    make_skill("webby")
    manifest = tmp_path / "m.json"
    manifest.write_text('{"webby": {}}', encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"hermes": ToolCfg(path=tool_dir, owned_sources=[manifest])}
    save_config(paths, cfg)
    problems = cli.doctor(paths, cfg)
    assert any("webby" in p and "血统残留" in p for p in problems)


def test_doctor_flags_missing_owned_source(paths, tool_dir, tmp_path):
    cfg = load_config(paths)
    cfg.tools = {"hermes": ToolCfg(path=tool_dir,
                                   owned_sources=[tmp_path / "gone.json"])}
    save_config(paths, cfg)
    problems = cli.doctor(paths, cfg)
    assert any("owned_source 路径不存在" in p for p in problems)


def test_outdated_command_lists_states(paths, tmp_path, monkeypatch, capsys):
    import subprocess

    from skm.config import Pack
    monkeypatch.setenv("SKM_HOME", str(paths.home))
    r = tmp_path / "up"
    d = r / "sk"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: sk\n---\n", encoding="utf-8")
    for a in (("init", "-q"), ("add", "-A"),
              ("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")):
        subprocess.run(["git", *a], cwd=r, check=True, capture_output=True)
    cfg = load_config(paths)
    cfg.packs["p1"] = Pack(skills=["sk"], source=str(r), commit="oldhash")
    cfg.packs["p2"] = Pack(skills=[], source="https://no/net")   # 无 commit → untracked
    save_config(paths, cfg)
    rc = main(["outdated", "--force"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "可更新" in out and "p1" in out
    assert "未追踪" in out and "p2" in out


def test_doctor_hints_outdated_from_cache_only(paths, monkeypatch, capsys):
    import json

    from skm.config import Pack
    monkeypatch.setenv("SKM_HOME", str(paths.home))
    cfg = load_config(paths)
    cfg.packs["p1"] = Pack(skills=[], source="https://x/y", commit="aaa")
    save_config(paths, cfg)
    (paths.home / "cache-upstream.json").write_text(
        json.dumps({"https://x/y": {"head": "bbb", "checked_at": 9e12}}))
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0                                # 更新提示不算健康问题
    assert "上游更新" in out
