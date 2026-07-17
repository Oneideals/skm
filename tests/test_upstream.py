import json
import subprocess
import time

from skm import upstream
from skm.config import Pack, load_config, save_config


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _mkrepo(tmp_path, name="up"):
    r = tmp_path / name
    d = r / "skills" / "s1"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: s1\n---\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r,
                          capture_output=True, text=True).stdout.strip()
    return r, head


def test_remote_head_and_unreachable(tmp_path):
    r, head = _mkrepo(tmp_path)
    assert upstream.remote_head(str(r)) == head
    assert upstream.remote_head(str(tmp_path / "nope")) is None


def _cfg_with_pack(paths, url, commit):
    cfg = load_config(paths)
    cfg.packs["p1"] = Pack(skills=["s1"], source=url, commit=commit)
    save_config(paths, cfg)
    return load_config(paths)


def test_report_three_states(paths, tmp_path):
    r, head = _mkrepo(tmp_path)
    cfg = _cfg_with_pack(paths, str(r), head)
    rep = upstream.outdated_report(paths, cfg, force=True)
    assert rep[str(r)]["status"] == "up-to-date"
    # 上游前进一格 → outdated
    (r / "skills" / "s1" / "SKILL.md").write_text("v2", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v2")
    rep = upstream.outdated_report(paths, cfg, force=True)
    assert rep[str(r)]["status"] == "outdated"
    # 无 commit 记录 → untracked
    cfg.packs["p1"].commit = None
    rep = upstream.outdated_report(paths, cfg, force=True)
    assert rep[str(r)]["status"] == "untracked"


def test_cache_ttl(paths, tmp_path):
    r, head = _mkrepo(tmp_path)
    cfg = _cfg_with_pack(paths, str(r), head)
    upstream.outdated_report(paths, cfg, force=True)        # 写缓存
    cache = json.loads((paths.home / "cache-upstream.json").read_text())
    assert cache[str(r)]["head"] == head
    # 篡改缓存指向假 hash;TTL 内不发网络 → 用缓存(状态变 outdated)
    cache[str(r)]["head"] = "fakehash"
    (paths.home / "cache-upstream.json").write_text(json.dumps(cache))
    rep = upstream.outdated_report(paths, cfg, force=False)
    assert rep[str(r)]["remote"] == "fakehash"
    # 过期缓存 → 重新拉取,恢复真 head
    cache[str(r)]["checked_at"] = time.time() - upstream.CACHE_TTL - 1
    (paths.home / "cache-upstream.json").write_text(json.dumps(cache))
    rep = upstream.outdated_report(paths, cfg, force=False)
    assert rep[str(r)]["remote"] == head
