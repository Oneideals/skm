import pytest

from skm.config import Pack, Scenario, load_config, save_config
from skm.state import load_state
from skm.switcher import SwitchError, rollback, use


@pytest.fixture
def cfg(paths, tool_dir, make_skill):
    for s in ("s1", "s2"):
        make_skill(s)
    c = load_config(paths)
    c.tools = {"claude": tool_dir}
    c.packs["p1"] = Pack(skills=["s1"])
    c.packs["p2"] = Pack(skills=["s2"])
    c.scenarios["one"] = Scenario(packs=["p1"])
    c.scenarios["two"] = Scenario(packs=["p2"])
    save_config(paths, c)
    return c


def test_rollback_restores_previous(paths, cfg, tool_dir):
    use(paths, cfg, "claude", "one")
    use(paths, cfg, "claude", "two")
    rep = rollback(paths, cfg, "claude")
    assert rep.scenario == "one"
    st = load_state(paths)
    assert st["claude"].scenario == "one"
    assert st["claude"].links == ["s1"]
    assert (tool_dir / "s1").is_symlink() and not (tool_dir / "s2").exists()


def test_rollback_twice_toggles(paths, cfg):
    use(paths, cfg, "claude", "one")
    use(paths, cfg, "claude", "two")
    rollback(paths, cfg, "claude")      # → one
    rep = rollback(paths, cfg, "claude")  # → two
    assert rep.scenario == "two"
    assert load_state(paths)["claude"].links == ["s2"]


def test_rollback_without_backup_raises(paths, cfg):
    with pytest.raises(SwitchError):
        rollback(paths, cfg, "claude")
