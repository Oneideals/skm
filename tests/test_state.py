from skm.state import ToolState, backup, latest_backup, load_state, save_state


def test_load_missing_returns_empty(paths):
    assert load_state(paths) == {}


def test_roundtrip_sorts_links(paths):
    save_state(paths, {"claude": ToolState(scenario="coding", links=["b", "a"])})
    st = load_state(paths)
    assert st["claude"].scenario == "coding"
    assert st["claude"].links == ["a", "b"]


def test_backup_and_latest(paths):
    p1 = backup(paths, "hermes", ToolState(scenario=None, links=["x"]))
    p2 = backup(paths, "hermes", ToolState(scenario="research", links=["y"]))
    assert p1 != p2 and p1.exists() and p2.exists()
    snap = latest_backup(paths, "hermes")
    assert snap.scenario == "research" and snap.links == ["y"]


def test_latest_backup_none_when_absent(paths):
    assert latest_backup(paths, "codex") is None
