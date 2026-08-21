import json
import subprocess
import time

from skm import upstream
from skm.config import Pack, load_config, save_config
from skm.importer import import_repo, upgrade


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


def test_upgrade_refreshes_cache(paths, tmp_path):
    """upgrade 后缓存必须跟上,否则 TTL 内 outdated 会假报落后。

    实际踩到过(2026-08-21):19:00 查询把 remote 写进缓存,之后上游前进一格,
    upgrade 抓到新 commit 写进 config,但缓存仍是旧值;24h TTL 内再查就拿
    旧缓存跟新 config 比,报一个并不存在的 outdated。
    """
    r, head1 = _mkrepo(tmp_path)
    cfg = load_config(paths)
    import_repo(paths, cfg, str(r), name="p1")
    cfg = load_config(paths)

    upstream.outdated_report(paths, cfg, force=True)          # 缓存记下 head1
    cache = json.loads((paths.home / "cache-upstream.json").read_text())
    assert cache[str(r)]["head"] == head1

    # 上游前进一格
    (r / "skills" / "s1" / "SKILL.md").write_text("v2", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v2")

    upgrade(paths, cfg, "p1")                                  # config 记到 head2
    cfg = load_config(paths)
    head2 = upstream.remote_head(str(r))
    assert cfg.packs["p1"].commit == head2 != head1

    # 不带 force(即 TTL 未过期的日常路径)→ 必须是 up-to-date,不能假报落后
    rep = upstream.outdated_report(paths, cfg, force=False)
    assert rep[str(r)]["remote"] == head2
    assert rep[str(r)]["status"] == "up-to-date"
