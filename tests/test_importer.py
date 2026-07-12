import pytest

from skm.importer import ImporterError, find_skill_dirs, install_local


def _mk_skill(root, rel):
    d = root / rel
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    return d


def test_find_flat_and_nested(tmp_path):
    _mk_skill(tmp_path, "skills/alpha")
    _mk_skill(tmp_path, "skills/engineering/beta")
    _mk_skill(tmp_path, ".git/fake")          # 必须跳过
    _mk_skill(tmp_path, "node_modules/junk")  # 必须跳过
    found = [d.name for d in find_skill_dirs(tmp_path)]
    assert found == ["alpha", "beta"]


def test_install_local_copies_flat(paths, tmp_path):
    src = _mk_skill(tmp_path, "somewhere/deep/gamma")
    assert install_local(paths, src) == "installed"
    assert (paths.skills / "gamma" / "SKILL.md").exists()


def test_install_local_skip_and_force(paths, tmp_path):
    src = _mk_skill(tmp_path, "a/gamma")
    install_local(paths, src)
    (src / "SKILL.md").write_text("v2", encoding="utf-8")
    assert install_local(paths, src) == "skipped"
    assert install_local(paths, src, force=True) == "installed"
    assert (paths.skills / "gamma" / "SKILL.md").read_text(encoding="utf-8") == "v2"


def test_install_local_name_override(paths, tmp_path):
    src = _mk_skill(tmp_path, "b/gamma")
    install_local(paths, src, name="renamed")
    assert (paths.skills / "renamed" / "SKILL.md").exists()


def test_install_local_rejects_non_skill(paths, tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(ImporterError):
        install_local(paths, d)
