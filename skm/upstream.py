"""上游更新检测:git ls-remote 取远端 HEAD,带 TTL 缓存;纯只读。"""
from __future__ import annotations

import json
import subprocess
import time

from .config import Config
from .paths import Paths

CACHE_TTL = 24 * 3600


def remote_head(url: str) -> str | None:
    try:
        proc = subprocess.run(["git", "ls-remote", url, "HEAD"],
                              capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.split()[0]


def _cache_path(paths: Paths):
    return paths.home / "cache-upstream.json"


def _load_cache(paths: Paths) -> dict:
    p = _cache_path(paths)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def cache_snapshot(paths: Paths) -> dict[str, str | None]:
    """只读缓存,url → head;不发任何网络请求(doctor 用)。"""
    return {u: e.get("head") for u, e in _load_cache(paths).items()}


def cached_head(paths: Paths, url: str, force: bool = False) -> str | None:
    """带缓存的远端 HEAD;force 绕过 TTL。失败结果也记录(防重复慢查)。"""
    cache = _load_cache(paths)
    ent = cache.get(url)
    if not force and ent and time.time() - ent.get("checked_at", 0) < CACHE_TTL:
        return ent.get("head")
    head = remote_head(url)
    cache[url] = {"head": head, "checked_at": time.time()}
    paths.ensure()
    _cache_path(paths).write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return head


def outdated_report(paths: Paths, cfg: Config, force: bool = False) -> dict:
    """按 source url 汇总:up-to-date / outdated / untracked / unreachable。"""
    by_url: dict[str, list[str]] = {}
    for name, p in sorted(cfg.packs.items()):
        if p.source:
            by_url.setdefault(p.source, []).append(name)
    out: dict[str, dict] = {}
    for url, packs in by_url.items():
        commits = {cfg.packs[n].commit for n in packs}
        local = next(iter(commits - {None}), None)
        if None in commits:
            status, remote = "untracked", None
        else:
            remote = cached_head(paths, url, force=force)
            if remote is None:
                status = "unreachable"
            elif remote != local:
                status = "outdated"
            else:
                status = "up-to-date"
        out[url] = {"status": status, "packs": packs,
                    "local": local, "remote": remote}
    return out
