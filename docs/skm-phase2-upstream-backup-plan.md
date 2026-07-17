# Skill Phase 2 (Upstream Updates + GitHub Backup) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Packs track their upstream commit; skm detects remote updates (auto-check, cached), surfaces them in CLI + panel with a manual "更新" action; the whole `~/.skm` can auto-push to a user GitHub repo on every change and be restored from it.

**Architecture:** Two new small modules — `skm/upstream.py` (remote HEAD check + 24h cache + outdated report) and `skm/backup.py` (git-ify `~/.skm`, change-driven commit + async push, restore + relink). `Pack` gains `commit/base/split` so upgrades are per-source and split-safe. Panel gets `/api/outdated` + `/api/upgrade`. All tests use local git repos (`file://`-style paths) as fake remotes — no network.

**Tech Stack:** Python ≥3.11 stdlib (`subprocess`, `json`, `time`, `shutil`), git CLI, pytest; vanilla JS in `panel.html`.

## Global Constraints

- Standard library only; git CLI is an accepted external (import already depends on it).
- Single file ≤ 400 lines target (≤ 800 hard cap); new modules each < 200 lines.
- TDD: failing test → minimal implementation → commit. Panel JS has no test framework → running panel + screenshot.
- Auto-check never mutates; apply is always explicit. Backup is opt-in (silent no-op until `backup init`).
- Commit format `<type>: <description>`; every commit ends with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Branch: `feat/skill-phase2` (spec committed there). Spec of record: `docs/skm-phase2-upstream-backup-design.md`.

---

### Task 1: `Pack.commit/base/split` config round-trip

**Files:**
- Modify: `skm/config.py` (`Pack` dataclass; `load_config` packs loop; `save_config` packs loop)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Pack(skills, source=None, commit=None, base=None, split=False)`; TOML persists `commit`/`base` when set, `split = true` only when true.

- [ ] **Step 1: Write the failing test** — add to `tests/test_config.py`:

```python
def test_pack_upstream_fields_roundtrip(paths):
    from skm.config import Pack
    cfg = load_config(paths)
    cfg.packs["mp"] = Pack(skills=["a"], source="https://x/y",
                           commit="abc123", base="mp", split=True)
    cfg.packs["plain"] = Pack(skills=["b"])
    save_config(paths, cfg)
    got = load_config(paths)
    p = got.packs["mp"]
    assert (p.commit, p.base, p.split) == ("abc123", "mp", True)
    q = got.packs["plain"]
    assert (q.commit, q.base, q.split) == (None, None, False)
```

- [ ] **Step 2: Run to verify FAIL** — `.venv/bin/python -m pytest tests/test_config.py::test_pack_upstream_fields_roundtrip -v` → `TypeError: Pack.__init__() got an unexpected keyword argument 'commit'`.

- [ ] **Step 3: Implement** — in `skm/config.py`:

```python
@dataclass
class Pack:
    skills: list[str] = field(default_factory=list)
    source: str | None = None
    commit: str | None = None    # 安装时上游 HEAD hash(更新检测锚点)
    base: str | None = None      # import 时的 --name base(升级复现用)
    split: bool = False          # import 时是否 --split-by-dir
```

In `load_config` packs loop replace the constructor call:

```python
        packs[name] = Pack(skills=list(body.get("skills", [])),
                           source=body.get("source"),
                           commit=body.get("commit"),
                           base=body.get("base"),
                           split=bool(body.get("split", False)))
```

In `save_config` packs loop, after the `source` line:

```python
        if p.source:
            lines.append(f"source = {_toml_str(p.source)}")
        if p.commit:
            lines.append(f"commit = {_toml_str(p.commit)}")
        if p.base:
            lines.append(f"base = {_toml_str(p.base)}")
        if p.split:
            lines.append("split = true")
```

- [ ] **Step 4: Run to verify PASS** — `.venv/bin/python -m pytest tests/test_config.py -v` → all pass.
- [ ] **Step 5: Commit** — `git add skm/config.py tests/test_config.py && git commit -m "feat: Pack.commit/base/split upstream metadata"` (with co-author line).

---

### Task 2: import records commit/base/split

**Files:**
- Modify: `skm/importer.py` (`ImportReport`; `import_repo` registration loop)
- Test: `tests/test_import_repo.py`

**Interfaces:**
- Consumes: Task 1 fields.
- Produces: `ImportReport.commit: str | None`; after `import_repo(url, name=…, split_by_dir=…)`, every registered pack has `commit=<clone HEAD>`, `base=<effective base>`, `split=<flag>`.

- [ ] **Step 1: Write the failing test** — add to `tests/test_import_repo.py`:

```python
def test_import_records_commit_base_split(paths, repo):
    cfg = load_config(paths)
    rep = import_repo(paths, cfg, str(repo), name="mp", split_by_dir=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    assert rep.commit == head
    cfg2 = load_config(paths)
    for pname in ("mp", "mp-engineering"):
        p = cfg2.packs[pname]
        assert p.commit == head and p.base == "mp" and p.split is True
```

- [ ] **Step 2: FAIL** — `pytest tests/test_import_repo.py::test_import_records_commit_base_split -v` → `AttributeError: 'ImportReport' object has no attribute 'commit'`.

- [ ] **Step 3: Implement** — in `skm/importer.py`:

```python
@dataclass
class ImportReport:
    installed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    packs: dict[str, list[str]] = field(default_factory=dict)
    commit: str | None = None
    dropped: list[str] = field(default_factory=list)   # 升级时从 pack 摘除的
```

In `import_repo`, inside the `with tempfile...` block after the clone succeeds:

```python
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone_dir,
                              capture_output=True, text=True).stdout.strip()
        rep.commit = head or None
```

And change the pack registration loop tail:

```python
    for pname in rep.packs:
        rep.packs[pname] = sorted(set(rep.packs[pname]))
        old = cfg.packs.get(pname)
        merged = sorted(set(rep.packs[pname]) | set(old.skills if old else []))
        cfg.packs[pname] = Pack(skills=merged, source=url, commit=rep.commit,
                                base=base, split=split_by_dir)
```

- [ ] **Step 4: PASS** — `pytest tests/test_import_repo.py -v` → all pass (existing tests unaffected: extra fields default-compatible).
- [ ] **Step 5: Commit** — `feat: import records upstream commit + base/split provenance`.

---

### Task 3: `upgrade_source` — split-safe, fresh-list upgrade

**Files:**
- Modify: `skm/importer.py` (add `upgrade_source`; rewrite `upgrade`)
- Test: `tests/test_import_repo.py`

**Interfaces:**
- Consumes: Task 2.
- Produces: `upgrade_source(paths, cfg, url) -> ImportReport` — one clone refreshes ALL packs with that source using their recorded `base`/`split`; pack skill lists become the fresh upstream set (no old∪new merge); skills dropped upstream are removed from packs (central copies kept) and listed in `rep.dropped` as `"<pack>/<skill>"`; new commit recorded. `upgrade(paths, cfg, pack_name)` resolves the pack's source and delegates.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_import_repo.py`:

```python
def test_upgrade_source_split_safe_and_fresh(paths, repo):
    cfg = load_config(paths)
    import_repo(paths, cfg, str(repo), name="mp", split_by_dir=True)
    # 上游:alpha 删除,engineering 新增 gamma
    import shutil
    shutil.rmtree(repo / "skills" / "alpha")
    g = repo / "skills" / "engineering" / "gamma"
    g.mkdir()
    (g / "SKILL.md").write_text("---\nname: gamma\n---\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v2")

    cfg = load_config(paths)
    from skm.importer import upgrade_source
    rep = upgrade_source(paths, cfg, str(repo))

    cfg2 = load_config(paths)
    assert cfg2.packs["mp"].skills == []                       # alpha 上游已删 → fresh 名单为空
    assert cfg2.packs["mp-engineering"].skills == ["beta", "gamma"]
    assert "mp/alpha" in rep.dropped
    assert (paths.skills / "alpha" / "SKILL.md").exists()      # 真身保留(变散装)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    assert cfg2.packs["mp-engineering"].commit == head


def test_upgrade_by_pack_delegates_to_source(paths, repo):
    cfg = load_config(paths)
    import_repo(paths, cfg, str(repo), name="mp", split_by_dir=True)
    (repo / "skills" / "alpha" / "SKILL.md").write_text("v2", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v2")
    cfg = load_config(paths)
    upgrade(paths, cfg, "mp-engineering")                      # 升级任一兄弟 pack
    assert (paths.skills / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "v2"
    cfg2 = load_config(paths)
    assert "beta" in cfg2.packs["mp-engineering"].skills       # 不串包(split 修复)
    assert "beta" not in cfg2.packs["mp"].skills
```

- [ ] **Step 2: FAIL** — `pytest tests/test_import_repo.py -k upgrade -v` → ImportError (`upgrade_source` missing);旧 `test_upgrade_uses_source` 仍应过。

- [ ] **Step 3: Implement** — in `skm/importer.py` replace `upgrade` with:

```python
def upgrade_source(paths: Paths, cfg: Config, url: str) -> ImportReport:
    """按 source 仓升级:一次克隆刷新该 url 的全部 pack(fresh 名单,split 安全)。"""
    group = {n: p for n, p in cfg.packs.items() if p.source == url}
    if not group:
        raise ImporterError(f"没有 source 为 {url} 的 pack")
    anchor = next((p for p in group.values() if p.base), None)
    base = anchor.base if anchor else sorted(group)[0]
    split = anchor.split if anchor else False
    old_lists = {n: list(p.skills) for n, p in group.items()}

    rep = import_repo(paths, cfg, url, name=base, split_by_dir=split, force=True)

    # fresh 名单:覆盖 import_repo 的 old∪new 合并;上游消失的从 pack 摘除
    for pname, old in old_lists.items():
        fresh = rep.packs.get(pname, [])
        cfg.packs[pname] = Pack(skills=sorted(fresh), source=url,
                                commit=rep.commit, base=base, split=split)
        rep.dropped += [f"{pname}/{s}" for s in sorted(set(old) - set(fresh))]
    save_config(paths, cfg)
    return rep


def upgrade(paths: Paths, cfg: Config, pack_name: str) -> ImportReport:
    p = cfg.packs.get(pack_name)
    if p is None or not p.source:
        raise ImporterError(f"pack '{pack_name}' 不存在或没有 source,无法升级")
    return upgrade_source(paths, cfg, p.source)
```

Also add `from .config import Config, Pack, save_config` is already imported — verify imports unchanged.

- [ ] **Step 4: PASS** — `pytest tests/test_import_repo.py -v`;然后全套 `pytest -q`(旧 `test_upgrade_uses_source` 走新路径仍应过)。
- [ ] **Step 5: Update `_cmd_upgrade` output** — in `skm/cli.py`:

```python
def _cmd_upgrade(paths: Paths, cfg: Config, args) -> int:
    rep = importer.upgrade(paths, cfg, args.pack)
    print(f"已按 source 升级(同仓 pack 一起刷新):更新 {len(rep.installed)} 个 skill")
    for pname, skills in sorted(rep.packs.items()):
        print(f"  pack {pname}: {len(skills)} 个")
    if rep.dropped:
        print(f"  从 pack 摘除(真身保留): {', '.join(rep.dropped)}")
    return 0
```

- [ ] **Step 6: Commit** — `feat: upgrade_source — split-safe per-source upgrade with fresh lists`.

---

### Task 4: `skm/upstream.py` — remote check + cache + report

**Files:**
- Create: `skm/upstream.py`
- Test: `tests/test_upstream.py` (new)

**Interfaces:**
- Produces: `remote_head(url) -> str | None`; `outdated_report(paths, cfg, force=False) -> dict[str, dict]` where value = `{"status": "up-to-date"|"outdated"|"untracked"|"unreachable", "packs": [names], "local": str|None, "remote": str|None}`. Cache file `paths.home / "cache-upstream.json"`, TTL 24h.

- [ ] **Step 1: Write the failing tests** — create `tests/test_upstream.py`:

```python
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
```

- [ ] **Step 2: FAIL** — `pytest tests/test_upstream.py -v` → `ModuleNotFoundError: skm.upstream`.

- [ ] **Step 3: Implement** — create `skm/upstream.py`:

```python
"""上游更新检测:git ls-remote 取远端 HEAD,带 TTL 缓存;纯只读。"""
from __future__ import annotations

import json
import subprocess
import time

from .config import Config
from .paths import Paths

CACHE_TTL = 24 * 3600


def remote_head(url: str) -> str | None:
    proc = subprocess.run(["git", "ls-remote", url, "HEAD"],
                          capture_output=True, text=True, timeout=30)
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


def cached_head(paths: Paths, url: str, force: bool = False) -> str | None:
    """带缓存的远端 HEAD;force 绕过 TTL。失败时缓存 None 亦记录(防重复慢查)。"""
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
```

- [ ] **Step 4: PASS** — `pytest tests/test_upstream.py -v`,再全套。

  注意:`test_cache_ttl` 里 untracked 分支不查网络——实现里 untracked 时**不调 `cached_head`**(如上),测试三态用 `force=True` 时 up-to-date/outdated 都会写缓存。
- [ ] **Step 5: Commit** — `feat: upstream module — remote HEAD check with 24h cache`.

---

### Task 5: CLI `skm outdated` + doctor cache hint

**Files:**
- Modify: `skm/cli.py` (new `_cmd_outdated`; `_cmd_doctor` info line; parser wiring)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `upstream.outdated_report`, `upstream._load_cache` semantics via `upstream.cached-file` (doctor reads the cache file directly through a small helper `upstream.cache_snapshot(paths) -> dict`).
- Produces: `skm outdated [--force]` prints per-source status; `_cmd_doctor` appends an informational line (exit code unaffected) when the cache already shows an outdated source.

- [ ] **Step 1: Add helper to `skm/upstream.py`** (needed by doctor; no network):

```python
def cache_snapshot(paths: Paths) -> dict[str, str | None]:
    """只读缓存,url → head;不发任何网络请求(doctor 用)。"""
    return {u: e.get("head") for u, e in _load_cache(paths).items()}
```

- [ ] **Step 2: Write the failing tests** — add to `tests/test_cli.py`:

```python
def test_outdated_command_lists_states(paths, tmp_path, capsys):
    import subprocess
    from skm.config import Pack, save_config
    r = tmp_path / "up"
    d = r / "sk"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: sk\n---\n", encoding="utf-8")
    for a in (("init", "-q"), ("add", "-A"),
              ("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")):
        subprocess.run(["git", *a], cwd=r, check=True, capture_output=True)
    cfg = load_config(paths)
    cfg.packs["p1"] = Pack(skills=["sk"], source=str(r), commit="oldhash")
    cfg.packs["p2"] = Pack(skills=[], source="https://no/net")   # untracked(无 commit)
    save_config(paths, cfg)
    rc = cli.main(["outdated", "--force"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "可更新" in out and "p1" in out
    assert "未追踪" in out and "p2" in out


def test_doctor_hints_outdated_from_cache_only(paths, tmp_path, capsys):
    import json
    from skm.config import Pack, save_config
    cfg = load_config(paths)
    cfg.packs["p1"] = Pack(skills=[], source="https://x/y", commit="aaa")
    save_config(paths, cfg)
    (paths.home / "cache-upstream.json").write_text(
        json.dumps({"https://x/y": {"head": "bbb", "checked_at": 9e12}}))
    rc = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0                                # 更新提示不算健康问题
    assert "上游更新" in out
```

  说明:`tests/test_cli.py` 现有测试通过 `cli.main([...])` 调用吗?——检查文件头部;若现有风格是直接调 `_cmd_*`,改用同风格(`cli.main` 需要 `SKM_HOME` 指向 `paths.home`:conftest 的 `paths` fixture 用 `tmp_path/skm`,`cli.main` 里 `Paths.from_env()` 读环境变量——测试里用 `monkeypatch.setenv("SKM_HOME", str(paths.home))`)。两个测试签名各加 `monkeypatch` 并首行设置该环境变量。

- [ ] **Step 3: FAIL** — `pytest tests/test_cli.py -k "outdated or hints" -v` → argparse error(无 outdated 子命令)。

- [ ] **Step 4: Implement in `skm/cli.py`** — import `upstream` in the module import block (`from . import boundary, importer, linker, switcher, upstream`), then:

```python
_STATUS_LABEL = {"up-to-date": "✓ 最新", "outdated": "⬆ 可更新",
                 "untracked": "· 未追踪(upgrade 一次开始追踪)",
                 "unreachable": "⚠ 无法访问"}


def _cmd_outdated(paths: Paths, cfg: Config, args) -> int:
    rep = upstream.outdated_report(paths, cfg, force=args.force)
    if not rep:
        print("(没有带 source 的 pack,无可检查项)")
        return 0
    for url, r in sorted(rep.items()):
        print(f"{_STATUS_LABEL[r['status']]}  {url}")
        print(f"    packs: {', '.join(r['packs'])}")
        if r["status"] == "outdated":
            print(f"    本地 {str(r['local'])[:9]} → 远端 {str(r['remote'])[:9]}"
                  f";应用: skm upgrade {r['packs'][0]}")
    return 0
```

In `_cmd_doctor`, after printing problems / the ✓ line, append (before `return`):

```python
    snap = upstream.cache_snapshot(paths)
    urls = {p.source for p in cfg.packs.values() if p.source and p.commit}
    stale = [u for u in sorted(urls)
             if snap.get(u) and snap[u] != next(
                 p.commit for p in cfg.packs.values() if p.source == u and p.commit)]
    for u in stale:
        print(f"ℹ 有上游更新(skm outdated 查看 / skm upgrade 应用): {u}")
```

(放在两个分支都能走到的位置:把原函数改为先算 problems、打印、再打提示、最后按 problems 是否为空返回 0/1。)

Parser wiring in `_build_parser()` after the `upgrade` parser:

```python
    p = sub.add_parser("outdated", help="检查各 pack 上游是否有更新(带 24h 缓存)")
    p.add_argument("--force", action="store_true", help="绕过缓存强制检查")
    p.set_defaults(fn=_cmd_outdated)
```

- [ ] **Step 5: PASS** — targeted then full suite.
- [ ] **Step 6: Commit** — `feat: skm outdated command + doctor cache-only update hint`.

---

### Task 6: panel server — `/api/outdated`, `/api/upgrade`, pack 前缀感知 root

**Files:**
- Modify: `skm/panel.py` (`_pool_groups` pack-root; handler GET/POST routes)
- Test: `tests/test_panel.py`, `tests/test_panel_server.py`

**Interfaces:**
- Consumes: `upstream.outdated_report`, `importer.upgrade_source`.
- Produces: `GET /api/outdated?force=1` → outdated_report JSON. `POST /api/upgrade` body `{"url": …}` → `{"ok": true, "installed": N, "dropped": […], "packs": […]}` (400 on error). Pack collections whose members form one prefix family emit that root member as `"root"` (removed from `members`); otherwise `root: null`.

- [ ] **Step 1: Failing tests** — add to `tests/test_panel.py`:

```python
def test_pool_pack_prefix_aware_root(paths, make_skill):
    for n in ("pt", "pt-a", "pt-b", "solo"):
        make_skill(n)
    cfg = load_config(paths)
    cfg.packs["ptpack"] = Pack(skills=["pt", "pt-a", "pt-b"])
    pool = build_state(paths, cfg)["pool"]
    c = pool["collections"][0]
    assert c["kind"] == "pack" and c["name"] == "ptpack"
    assert c["root"]["name"] == "pt"                       # 前缀感知:根提出来
    assert [m["name"] for m in c["members"]] == ["pt-a", "pt-b"]
```

  同时**修改既有测试** `test_pool_pack_beats_prefix_and_dedups`:pack `alpha` 的成员 `[ponytail, ponytail-audit]` 构成前缀家族 → 断言改为 `alpha["root"]["name"] == "ponytail"` 且 `members == ["ponytail-audit"]`;"不丢不重"统计里把非空 `root` 也计入 `seen`。

  Add to `tests/test_panel_server.py`(沿用该文件现有的起 server/HTTP 请求模式;若其模式是 `make_server` + `http.client`,照抄该模式):

```python
def test_api_outdated_and_upgrade(paths, tmp_path):
    import json, subprocess, urllib.request
    from skm.panel import make_server
    import threading
    r = tmp_path / "up"
    d = r / "skills" / "s1"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: s1\n---\n", encoding="utf-8")
    for a in (("init", "-q"), ("add", "-A"),
              ("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")):
        subprocess.run(["git", *a], cwd=r, check=True, capture_output=True)
    from skm.config import load_config
    from skm.importer import import_repo
    cfg = load_config(paths)
    import_repo(paths, cfg, str(r), name="pp")
    # 上游前进
    (d / "SKILL.md").write_text("---\nname: s1\n---\nv2\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "v2"], cwd=r, check=True, capture_output=True)

    srv = make_server(paths, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        rep = json.loads(urllib.request.urlopen(f"{base}/api/outdated?force=1").read())
        assert rep[str(r)]["status"] == "outdated"
        body = json.dumps({"url": str(r)}).encode()
        req = urllib.request.Request(f"{base}/api/upgrade", data=body,
                                     headers={"Content-Type": "application/json"})
        out = json.loads(urllib.request.urlopen(req).read())
        assert out["ok"] is True and "s1" in str(out)
        rep2 = json.loads(urllib.request.urlopen(f"{base}/api/outdated?force=1").read())
        assert rep2[str(r)]["status"] == "up-to-date"
    finally:
        srv.shutdown()
```

- [ ] **Step 2: FAIL** — pack-root 断言失败(root 为 None)+ /api/outdated 404。

- [ ] **Step 3: Implement `_pool_groups` pack-root** — in `skm/panel.py`, in the pack-claiming loop, after computing `present`:

```python
        members = [by_name[n] for n in present]
        root = None
        for cand in members:
            rest = [m for m in members if m is not cand]
            if rest and all(m["name"].startswith(cand["name"] + "-") for m in rest):
                root, members = cand, rest
                break
        collections.append({"kind": "pack", "name": pname, "root": root,
                            "members": members})
```

- [ ] **Step 4: Implement handlers** — in `skm/panel.py` `_make_handler`,`do_GET` 增分支(在 `/api/state` 之后):

```python
            elif self.path.startswith("/api/outdated"):
                from . import upstream
                cfg = load_config(paths)
                force = "force=1" in (self.path.split("?", 1) + [""])[1]
                rep = upstream.outdated_report(paths, cfg, force=force)
                self._send(200, json.dumps(rep, ensure_ascii=False),
                           "application/json; charset=utf-8")
```

  `do_POST` 增分支(在 `/api/save` 判断之前改为 if/elif 结构):

```python
            if self.path == "/api/upgrade":
                length = int(self.headers.get("Content-Length", 0))
                try:
                    payload = json.loads(self.rfile.read(length))
                    from . import importer, upstream
                    cfg = load_config(paths)
                    rep = importer.upgrade_source(paths, cfg, payload["url"])
                    upstream.cached_head(paths, payload["url"], force=True)  # 刷新缓存
                    self._send(200, json.dumps(
                        {"ok": True, "installed": len(rep.installed),
                         "dropped": rep.dropped,
                         "packs": sorted(rep.packs)}, ensure_ascii=False),
                        "application/json; charset=utf-8")
                except Exception as e:            # ImporterError/KeyError/ValueError
                    self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False),
                               "application/json; charset=utf-8")
                return
```

- [ ] **Step 5: PASS** — `pytest tests/test_panel.py tests/test_panel_server.py -v`,后全套。
- [ ] **Step 6: Commit** — `feat: panel api — outdated report, source upgrade, pack prefix root`.

---### Task 7: `skm/backup.py` + hooks + CLI backup/restore

**Files:**
- Create: `skm/backup.py`
- Modify: `skm/config.py` (`save_config` 末尾标脏), `skm/state.py` (`save_state` 末尾标脏), `skm/cli.py` (backup/restore 命令 + `main` 尾部 autosync), `skm/panel.py` (`apply_payload` 尾部 autosync)
- Test: `tests/test_backup.py` (new)

**Interfaces:**
- Produces: `backup.mark_dirty()`; `backup.autosync(paths, message, wait=False)`(未 init → no-op;脏 → add/commit + push,`wait=True` 同步 push 供测试);`backup.init_repo(paths, url)`;`backup.backup_now(paths) -> str`(状态文本);`backup.restore(paths, url, force=False) -> dict`(含 `safety` 路径与重链统计)。

- [ ] **Step 1: Failing tests** — create `tests/test_backup.py`:

```python
import subprocess

import pytest

from skm import backup
from skm.config import ToolCfg, load_config, save_config
from skm.state import ToolState, save_state


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True)


@pytest.fixture
def bare(tmp_path):
    b = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(b)], check=True,
                   capture_output=True)
    return b


def test_init_and_autosync_push(paths, bare, make_skill):
    make_skill("s1")
    backup.init_repo(paths, str(bare))
    log = _git(bare, "log", "--oneline", "main").stdout
    assert "skm backup init" in log                       # 首推已到远端
    # 变更 → autosync 推送
    cfg = load_config(paths)
    cfg.universal = ["s1"]
    save_config(paths, cfg)                               # 内部 mark_dirty
    backup.autosync(paths, "use test", wait=True)
    log = _git(bare, "log", "--oneline", "main").stdout
    assert "skm: use test" in log


def test_autosync_noop_without_init(paths, make_skill):
    make_skill("s1")
    cfg = load_config(paths)
    cfg.universal = ["s1"]
    save_config(paths, cfg)
    backup.autosync(paths, "x", wait=True)                # 不应抛错、不建 .git
    assert not (paths.home / ".git").exists()


def test_restore_relinks(paths, bare, make_skill, tool_dir):
    make_skill("s1")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    cfg.universal = ["s1"]
    save_config(paths, cfg)
    save_state(paths, {"claude": ToolState(groups=[], links=["s1"])})
    backup.init_repo(paths, str(bare))
    backup.autosync(paths, "seed", wait=True)
    # 模拟换机:清空 home 与工具目录里的链
    import shutil
    shutil.rmtree(paths.home)
    (tool_dir / "s1").unlink(missing_ok=True)
    rep = backup.restore(paths, str(bare))
    assert (paths.home / "skills" / "s1" / "SKILL.md").exists()
    assert (tool_dir / "s1").is_symlink()                 # 已按 state 重链
    assert rep["tools"] == ["claude"]


def test_restore_existing_requires_force(paths, bare, make_skill):
    make_skill("s1")
    backup.init_repo(paths, str(bare))
    with pytest.raises(backup.BackupError):
        backup.restore(paths, str(bare))                  # 已存在,无 --force
    rep = backup.restore(paths, str(bare), force=True)
    assert rep["safety"] and (paths.home / "skills").exists()
```

- [ ] **Step 2: FAIL** — `ModuleNotFoundError: skm.backup`。

- [ ] **Step 3: Implement** — create `skm/backup.py`:

```python
"""GitHub 备份:~/.skm git 化,变更驱动 commit + push;restore 恢复并重算软链。"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .paths import Paths

_GITIGNORE = "backups/\ncache-upstream.json\npush.log\n"
_dirty = False


class BackupError(Exception):
    pass


def mark_dirty() -> None:
    global _dirty
    _dirty = True


def _git(paths: Paths, *args, check=True):
    return subprocess.run(["git", "-C", str(paths.home), *args],
                          capture_output=True, text=True, check=check)


def _ready(paths: Paths) -> bool:
    if not (paths.home / ".git").exists():
        return False
    r = _git(paths, "remote", "get-url", "origin", check=False)
    return r.returncode == 0


def init_repo(paths: Paths, url: str) -> None:
    paths.ensure()
    if not (paths.home / ".git").exists():
        _git_init = subprocess.run(["git", "init", "-q", str(paths.home)],
                                   capture_output=True, text=True)
        if _git_init.returncode != 0:
            raise BackupError(f"git init 失败: {_git_init.stderr.strip()}")
    (paths.home / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    if _git(paths, "remote", "get-url", "origin", check=False).returncode == 0:
        _git(paths, "remote", "set-url", "origin", url)
    else:
        _git(paths, "remote", "add", "origin", url)
    _git(paths, "add", "-A")
    _git(paths, "-c", "user.email=skm@local", "-c", "user.name=skm",
         "commit", "-qm", "skm backup init", check=False)   # 无变化时容忍失败
    _git(paths, "branch", "-M", "main")
    push = _git(paths, "push", "-u", "origin", "main", check=False)
    if push.returncode != 0:
        raise BackupError(f"首推失败: {push.stderr.strip()[:300]}")


def autosync(paths: Paths, message: str, wait: bool = False) -> None:
    """变更后自动备份:未 init 静默跳过;push 默认后台、失败不打扰。"""
    global _dirty
    if not _dirty or not _ready(paths):
        return
    _dirty = False
    _git(paths, "add", "-A")
    _git(paths, "-c", "user.email=skm@local", "-c", "user.name=skm",
         "commit", "-qm", f"skm: {message}", check=False)
    if wait:
        _git(paths, "push", "origin", "main", check=False)
    else:
        log = open(paths.home / "push.log", "ab")
        subprocess.Popen(["git", "-C", str(paths.home), "push", "origin", "main"],
                         stdout=log, stderr=log)


def backup_now(paths: Paths) -> str:
    if not _ready(paths):
        return "未启用备份:先 skm backup init <git-url>"
    _git(paths, "add", "-A")
    _git(paths, "-c", "user.email=skm@local", "-c", "user.name=skm",
         "commit", "-qm", f"skm: manual backup {time.strftime('%F %T')}",
         check=False)
    push = _git(paths, "push", "origin", "main", check=False)
    if push.returncode != 0:
        return f"⚠ push 失败(本地已 commit,稍后重试): {push.stderr.strip()[:200]}"
    url = _git(paths, "remote", "get-url", "origin").stdout.strip()
    return f"✓ 已推送到 {url}"


def restore(paths: Paths, url: str, force: bool = False) -> dict:
    safety = None
    if paths.home.exists() and any(paths.home.iterdir()):
        if not force:
            raise BackupError(f"{paths.home} 已存在且非空;加 --force 覆盖"
                              "(现状会先移到临时快照)")
        safety = Path(tempfile.mkdtemp(prefix="skm-restore-safety-"))
        for child in list(paths.home.iterdir()):
            shutil.move(str(child), str(safety / child.name))
    paths.home.mkdir(parents=True, exist_ok=True)
    clone = subprocess.run(["git", "clone", "-q", url, str(paths.home)],
                           capture_output=True, text=True)
    if clone.returncode != 0:
        raise BackupError(f"clone 失败: {clone.stderr.strip()[:300]}")

    from . import switcher                       # 延迟导入避免环
    from .config import load_config
    from .state import load_state
    cfg = load_config(paths)
    state = load_state(paths)
    tools, skipped = [], []
    for tool, ts in sorted(state.items()):
        tc = cfg.tools.get(tool)
        if tc is None or not tc.path.parent.exists():
            skipped.append(tool)
            continue
        switcher.use(paths, cfg, tool, ts.groups)
        tools.append(tool)
    return {"tools": tools, "skipped": skipped,
            "safety": str(safety) if safety else None}
```

- [ ] **Step 4: Hook the choke points** —
  `skm/config.py` `save_config` 末行前加:

```python
    from . import backup
    backup.mark_dirty()
```

  (放在 `write_text` 之后。)`skm/state.py` `save_state` 同样在 `write_text` 之后加同两行。

- [ ] **Step 5: CLI wiring** — `skm/cli.py`:

```python
def _cmd_backup(paths: Paths, cfg: Config, args) -> int:
    from . import backup as _backup
    if args.backup_cmd == "init":
        _backup.init_repo(paths, args.url)
        print(f"✓ 已初始化并首推到 {args.url}(建议私有仓)")
        return 0
    print(_backup.backup_now(paths))
    return 0


def _cmd_restore(paths: Paths, cfg: Config, args) -> int:
    from . import backup as _backup
    rep = _backup.restore(paths, args.url, force=args.force)
    print(f"✓ 已恢复;重链工具: {', '.join(rep['tools']) or '(无)'}")
    if rep["skipped"]:
        print(f"  跳过(工具路径不存在): {', '.join(rep['skipped'])}")
    if rep["safety"]:
        print(f"  原 ~/.skm 快照: {rep['safety']}")
    return 0
```

  Parser(在 panel parser 之前):

```python
    p = sub.add_parser("backup", help="备份到 GitHub(无子命令=立即推送)")
    bsub = p.add_subparsers(dest="backup_cmd")
    bi = bsub.add_parser("init", help="初始化:git 化 ~/.skm 并关联远端(建议私有仓)")
    bi.add_argument("url")
    p.set_defaults(fn=_cmd_backup, backup_cmd=None)
    bi.set_defaults(fn=_cmd_backup, backup_cmd="init")

    p = sub.add_parser("restore", help="从 GitHub 恢复 ~/.skm 并重算各工具软链")
    p.add_argument("url")
    p.add_argument("--force", action="store_true", help="覆盖已存在的 ~/.skm(先出安全快照)")
    p.set_defaults(fn=_cmd_restore)
```

  `main()` 成功路径接 autosync + 错误类型扩充:

```python
    try:
        cfg = load_config(paths)
        rc = args.fn(paths, cfg, args)
        if rc == 0:
            from . import backup as _backup
            _backup.autosync(paths, " ".join(argv or sys.argv[1:]))
        return rc
    except (ConfigError, SwitchError, importer.ImporterError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        from . import backup as _backup
        if isinstance(e, _backup.BackupError):
            print(f"错误: {e}", file=sys.stderr)
            return 1
        raise
```

  `skm/panel.py` `apply_payload` 末尾(switcher 循环之后)加:

```python
    from . import backup
    backup.autosync(paths, "panel 保存并应用")
```

- [ ] **Step 6: PASS** — `pytest tests/test_backup.py -v` 后全套(注意:全套里所有 save_config 都会 mark_dirty,但 tmp `paths.home` 无 .git → autosync no-op,零影响)。
- [ ] **Step 7: Commit** — `feat: change-driven GitHub backup (init/autosync/backup/restore)`.

---

### Task 8: panel.html — outdated badge + 更新按钮 + pack 树形

**Files:**
- Modify: `skm/panel.html`

**Interfaces:**
- Consumes: `/api/outdated`, `/api/upgrade`, pack collections with non-null `root`.

- [ ] **Step 1: CSS** — after `.skill.member` rule add:

```css
  .upbadge { color:#e0b341; font-size:12px; cursor:default; }
  .upbtn { padding:0 8px; font-size:12px; border-color:var(--gold); color:var(--gold); }
```

- [ ] **Step 2: JS** — top state line gains `let OUT = {};`. In `load()` after `renderPool(); renderAll();` add:

```javascript
  fetch("/api/outdated").then(r=>r.json()).then(o=>{ OUT=o; renderPool(); }).catch(()=>{});
```

  In `renderPool()` collection loop, before `head.append(...)`, add:

```javascript
    let up = null;
    if (isPack) {
      for (const [u, r] of Object.entries(OUT))
        if (r.packs.includes(col.name) && r.status === "outdated") up = u;
    }
    if (up) {
      const btn = document.createElement("button");
      btn.className = "mini upbtn"; btn.textContent = "⬆ 更新";
      btn.title = "同 source 的 pack 会一起刷新";
      btn.addEventListener("click", async e => {
        e.stopPropagation();
        btn.disabled = true; btn.textContent = "更新中…";
        const r = await fetch("/api/upgrade", {method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({url: up})});
        if (r.ok) {
          const d = await r.json();
          toast(`已更新 ${d.installed} 个 skill(${d.packs.join(", ")})`, true);
          OUT = {}; load();
        } else { toast("更新失败:" + (await r.json()).error, false); btn.disabled = false; }
      });
      head.append(btn);
    }
```

  Pack 树形:body 渲染处改为——当 `isPack && col.root` 时先渲染根行再渲染缩进成员:

```javascript
    if (open) {
      const body = document.createElement("div"); body.className = "cbody";
      if (isPack && col.root && (!q || matches(col.root, q)))
        body.appendChild(skillRow(col.root, false));
      for (const m of shown) body.appendChild(skillRow(m, true));
      box.appendChild(body);
    }
```

  同步两处配套:计数 `cnt.textContent = col.members.length + (isPack && col.root ? 1 : 0);`;搜索命中判定把 `col.root` 纳入(`if (q && !matches(head0, q) && !(isPack && col.root && matches(col.root, q)) && !memHits.length) continue;`)。

- [ ] **Step 3: Restart panel + browser verify** — kill 8790、重启(nohup 同前),浏览器检查:① pack 块正常(暂无 outdated 数据则无徽标,页面无 JS 错);② `/api/outdated` 手动 curl 返回 JSON;③ 若有 outdated source,块头出现 ⬆ 更新按钮,点击 toast + 刷新(可用本地假仓手动造一个过期 pack 验证,验证后清理)。截图留档。
- [ ] **Step 4: Commit** — `feat: panel shows upstream updates with one-click apply; pack tree layout`.

---

### Task 9: Docs + operator steps (gated)

**Files:**
- Modify: `README.md`(命令参考加 `outdated`/`backup`/`restore`;特性列表加两条;工作原理加"备份与恢复"小节)
- Operator(改真实环境,逐项向用户确认后执行):
  1. `skm import https://github.com/DietrichGebert/ponytail` — ponytail 收编为 pack(6 个 skip 安装、登记 source+commit;池子显示为 📦+树形);
  2. `skm upgrade matt-engineering` 或等价 — 给 5 个 matt pack 补记 commit,开始被追踪;
  3. `skm backup init <用户提供的私有仓 url>` — 需要用户先建私有 GitHub 仓并给出 url。

- [ ] Step 1: README edits;commit `docs: phase 2 — outdated/backup/restore usage`。
- [ ] Step 2: 向用户确认后执行 operator 三步,验证 `skm outdated` / 面板徽标 / `skm backup` 状态。

---

## Notes for the executor

- Tests: `.venv/bin/python -m pytest`;假远端全用本地 git 仓路径,无网络。
- `tests/test_cli.py` 若现有风格非 `cli.main([...])`,新测试改随现有风格并用 `monkeypatch.setenv("SKM_HOME", …)`。
- 行数警戒:cli.py 完成后 `wc -l` 检查,>400 时把 `_cmd_backup`/`_cmd_restore`/`_cmd_outdated` 的打印逻辑压缩(仍 ≤800 硬上限)。
- Task 8 需重启 8790 面板进程;Task 9 operator 步骤一律先问用户。
