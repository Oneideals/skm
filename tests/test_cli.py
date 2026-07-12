import pytest

from skm.cli import main
from skm.config import Pack, Scenario, load_config, save_config


@pytest.fixture
def env(paths, tool_dir, make_skill, monkeypatch):
    monkeypatch.setenv("SKM_HOME", str(paths.home))
    for s in ("s1", "s2"):
        make_skill(s)
    cfg = load_config(paths)
    cfg.tools = {"claude": tool_dir}
    cfg.packs["p1"] = Pack(skills=["s1"])
    cfg.scenarios["research"] = Scenario(packs=["p1"], label="调研")
    save_config(paths, cfg)
    return paths, tool_dir


def test_use_and_list(env, capsys):
    paths, tool_dir = env
    assert main(["use", "claude", "research"]) == 0
    assert (tool_dir / "s1").is_symlink()
    out = capsys.readouterr().out
    assert "research" in out and "重启" in out
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "调研" in out and "s1" in out


def test_reset_and_rollback(env):
    paths, tool_dir = env
    main(["use", "claude", "research"])
    assert main(["reset", "claude"]) == 0
    assert not (tool_dir / "s1").exists()
    assert main(["rollback", "claude"]) == 0
    assert (tool_dir / "s1").is_symlink()


def test_use_unknown_scenario_fails(env, capsys):
    assert main(["use", "claude", "nope"]) == 1
    assert "不存在" in capsys.readouterr().err


def test_pack_create(env, capsys):
    paths, _ = env
    assert main(["pack", "create", "p2", "--skills", "s1,s2"]) == 0
    assert load_config(paths).packs["p2"].skills == ["s1", "s2"]
    assert main(["pack", "create", "Bad!", "--skills", "s1"]) == 1


def test_install_cli(env, tmp_path, capsys):
    paths, _ = env
    src = tmp_path / "newskill"
    src.mkdir()
    (src / "SKILL.md").write_text("x", encoding="utf-8")
    assert main(["install", str(src)]) == 0
    assert (paths.skills / "newskill" / "SKILL.md").exists()


def test_doctor_reports_problems(env, capsys):
    paths, tool_dir = env
    cfg = load_config(paths)
    cfg.packs["p1"].skills.append("ghost")
    save_config(paths, cfg)
    assert main(["doctor"]) == 1
    assert "ghost" in capsys.readouterr().out


def test_doctor_clean(env, capsys):
    assert main(["doctor"]) == 0
    assert "无问题" in capsys.readouterr().out
