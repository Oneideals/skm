import os

from skm import linker


def test_create_and_exists_ok(paths, make_skill, tool_dir):
    make_skill("s1")
    assert linker.create_link(paths, tool_dir, "s1") == linker.CREATED
    assert (tool_dir / "s1").is_symlink()
    assert linker.create_link(paths, tool_dir, "s1") == linker.EXISTS_OK


def test_create_no_skill(paths, tool_dir):
    assert linker.create_link(paths, tool_dir, "ghost") == linker.NO_SKILL


def test_create_conflict_real_dir(paths, make_skill, tool_dir):
    make_skill("s1")
    (tool_dir / "s1").mkdir()
    assert linker.create_link(paths, tool_dir, "s1") == linker.CONFLICT
    assert (tool_dir / "s1").is_dir() and not (tool_dir / "s1").is_symlink()


def test_create_conflict_foreign_symlink(paths, make_skill, tool_dir, tmp_path):
    make_skill("s1")
    other = tmp_path / "other" / "s1"
    other.mkdir(parents=True)
    os.symlink(other, tool_dir / "s1")
    assert linker.create_link(paths, tool_dir, "s1") == linker.CONFLICT


def test_remove_only_own_links(paths, make_skill, tool_dir, tmp_path):
    make_skill("s1")
    linker.create_link(paths, tool_dir, "s1")
    assert linker.remove_link(paths, tool_dir, "s1") == linker.REMOVED
    assert not (tool_dir / "s1").exists()
    # 真目录不删
    (tool_dir / "d").mkdir()
    assert linker.remove_link(paths, tool_dir, "d") == linker.NOT_SYMLINK
    assert (tool_dir / "d").is_dir()
    # 外部软链不删
    other = tmp_path / "elsewhere"
    other.mkdir()
    os.symlink(other, tool_dir / "f")
    assert linker.remove_link(paths, tool_dir, "f") == linker.FOREIGN
    assert (tool_dir / "f").is_symlink()
    # 不存在
    assert linker.remove_link(paths, tool_dir, "nope") == linker.MISSING


def test_remove_broken_own_link(paths, make_skill, tool_dir):
    import shutil
    make_skill("s2")
    linker.create_link(paths, tool_dir, "s2")
    shutil.rmtree(paths.skills / "s2")   # 中央仓删掉 → 断链
    assert linker.remove_link(paths, tool_dir, "s2") == linker.REMOVED
