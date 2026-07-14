# Tool-Owned Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `skm` recognize skills that belong to a tool by *provenance/ownership* (not just physical duplication), so `doctor`/`sync-boundary` auto-detect "tool-bloodline" residuals in the central repo and `--apply` hands them back to the tool non-destructively.

**Architecture:** Add an optional per-tool `owned_sources` config field (manifest files + bundle trees). `boundary.owned_skill_names(T)` = existing live-dir scan `∪` names declared by those sources. This feeds the existing `purge_candidates`, so detection widens with no change to that function. `sync_boundary --apply` gains a handoff step: when purging a skill whose only live copy is skm's symlink, materialize a real directory in the tool before deleting the central copy.

**Tech Stack:** Python ≥3.11, standard library only (`json`, `os`, `shutil`, `pathlib`), `pytest`.

## Global Constraints

- Standard library only — no third-party dependencies.
- Single file ≤ 400 lines (≤ 800 hard cap).
- TDD: failing test first, minimal implementation, then commit.
- Immutability-first; validate inputs at boundaries; no silent error swallowing.
- Commit format `<type>: <description>`; every commit message ends with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Work happens on branch `feat/tool-owned-boundary` (already created; spec committed there).
- Spec of record: `docs/skm-tool-owned-boundary-design.md`.

---

### Task 1: Config field `owned_sources` (load + save round-trip)

**Files:**
- Modify: `skm/config.py` (`ToolCfg` dataclass; `load_config` tools loop; `save_config` tools loop)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `ToolCfg(path: Path, skills: list[str] = [], owned_sources: list[Path] = [])`. `load_config`/`save_config` persist `owned_sources` as a TOML string array under `[tools.<name>]`, expanded via `Path(...).expanduser()` on load, sorted by string on save, written only when non-empty.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_owned_sources_roundtrip(paths, tmp_path):
    from skm.config import ToolCfg, load_config, save_config
    src1 = tmp_path / "manifest.json"
    src2 = tmp_path / "bundle"
    cfg = load_config(paths)
    cfg.tools = {"hermes": ToolCfg(path=tmp_path / "h", owned_sources=[src1, src2])}
    save_config(paths, cfg)
    got = load_config(paths)
    assert set(got.tools["hermes"].owned_sources) == {src1, src2}


def test_owned_sources_default_empty(paths):
    from skm.config import load_config
    cfg = load_config(paths)
    assert all(tc.owned_sources == [] for tc in cfg.tools.values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_config.py -k owned_sources -v`
Expected: FAIL — `TypeError: ToolCfg.__init__() got an unexpected keyword argument 'owned_sources'`.

- [ ] **Step 3: Add the field**

In `skm/config.py`, extend `ToolCfg`:

```python
@dataclass
class ToolCfg:
    path: Path
    skills: list[str] = field(default_factory=list)   # 工具专用常驻层
    owned_sources: list[Path] = field(default_factory=list)  # 工具所有权来源:清单文件/出厂树
```

- [ ] **Step 4: Read `owned_sources` in `load_config`**

In the `for name, body in raw.get("tools", {}).items():` loop, replace the `else` branch:

```python
        else:
            tools[name] = ToolCfg(
                path=Path(str(body["path"])).expanduser(),
                skills=list(body.get("skills", [])),
                owned_sources=[Path(str(p)).expanduser()
                               for p in body.get("owned_sources", [])])
```

- [ ] **Step 5: Write `owned_sources` in `save_config`**

In the `for name in sorted(cfg.tools):` loop, after the `skills = ...` line:

```python
    for name in sorted(cfg.tools):
        t = cfg.tools[name]
        lines += ["", f"[tools.{name}]", f"path = {_toml_str(str(t.path))}",
                  f"skills = {_toml_list(sorted(t.skills))}"]
        if t.owned_sources:
            lines.append(
                f"owned_sources = {_toml_list(sorted(str(p) for p in t.owned_sources))}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS (all config tests, including the two new ones).

- [ ] **Step 7: Commit**

```bash
git add skm/config.py tests/test_config.py
git commit -m "feat: ToolCfg.owned_sources config field (load/save round-trip)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `boundary.owned_skill_names` (live scan ∪ manifest ∪ tree)

**Files:**
- Modify: `skm/boundary.py` (refactor `foreign_skill_names`; add `_names_in_tree`, `_names_from_manifest`, `_names_from_source`, `owned_skill_names`)
- Test: `tests/test_boundary.py`

**Interfaces:**
- Consumes: `ToolCfg.owned_sources` (Task 1); existing `skill_name`, `linker.points_into_repo`.
- Produces: `owned_skill_names(paths: Paths, tool_cfg: ToolCfg) -> set[str]` = names physically native in the tool's live dir `∪` names declared by each owned_source. Directory sources are walked with skm-symlink exclusion; JSON manifest sources contribute dict keys (or list elements); missing sources contribute nothing.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_boundary.py`:

```python
from skm.config import ToolCfg


def test_owned_skill_names_manifest_and_tree(paths, make_skill, tool_dir, tmp_path):
    nat = tool_dir / "native"
    nat.mkdir()
    (nat / "SKILL.md").write_text("---\nname: native\n---\n", encoding="utf-8")
    make_skill("mine")
    linker.create_link(paths, tool_dir, "mine")
    manifest = tmp_path / "managed.json"
    manifest.write_text('{"webby": {"owner": "x"}}', encoding="utf-8")
    shipped = tmp_path / "bundle" / "cat" / "shipped"
    shipped.mkdir(parents=True)
    (shipped / "SKILL.md").write_text("---\nname: shipped\n---\n", encoding="utf-8")
    tc = ToolCfg(path=tool_dir, owned_sources=[manifest, tmp_path / "bundle"])
    names = boundary.owned_skill_names(paths, tc)
    assert {"native", "webby", "shipped"} <= names
    assert "mine" not in names                      # skm 链不算工具所有


def test_owned_skill_names_manifest_array(paths, tool_dir, tmp_path):
    m = tmp_path / "list.json"
    m.write_text('["a", "b"]', encoding="utf-8")
    tc = ToolCfg(path=tool_dir, owned_sources=[m])
    assert {"a", "b"} <= boundary.owned_skill_names(paths, tc)


def test_owned_skill_names_missing_source_skipped(paths, tool_dir, tmp_path):
    tc = ToolCfg(path=tool_dir,
                 owned_sources=[tmp_path / "nope.json", tmp_path / "nodir"])
    assert boundary.owned_skill_names(paths, tc) == set()


def test_owned_source_dir_excludes_skm_links(paths, make_skill, tmp_path):
    faux_live = tmp_path / "live"
    faux_live.mkdir()
    make_skill("mine")
    linker.create_link(paths, faux_live, "mine")
    tc = ToolCfg(path=tmp_path / "none", owned_sources=[faux_live])
    assert "mine" not in boundary.owned_skill_names(paths, tc)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_boundary.py -k owned -v`
Expected: FAIL — `AttributeError: module 'skm.boundary' has no attribute 'owned_skill_names'`.

- [ ] **Step 3: Refactor `foreign_skill_names` onto a reusable tree walk**

In `skm/boundary.py`, replace the body of `foreign_skill_names` and add `_names_in_tree` above it:

```python
def _names_in_tree(paths: Paths, root: Path) -> set[str]:
    """扫 root 下所有 SKILL.md 的 name;剪掉指向中央仓的 skm 软链目录(不进其递归)。"""
    names: set[str] = set()
    if not root.exists():
        return names
    for cur, dirs, files in os.walk(root, followlinks=True):
        cur_p = Path(cur)
        dirs[:] = [
            d for d in dirs
            if not ((cur_p / d).is_symlink()
                    and linker.points_into_repo(paths, cur_p / d))
        ]
        if "SKILL.md" in files:
            names.add(skill_name(cur_p / "SKILL.md"))
    return names


def foreign_skill_names(paths: Paths, tool_dir: Path) -> set[str]:
    """工具自带(非 skm 建)skill 的 name 集合(见 _names_in_tree)。"""
    return _names_in_tree(paths, tool_dir)
```

- [ ] **Step 4: Add manifest/source parsing and `owned_skill_names`**

Add after `foreign_skill_names` (keep `import json` — add it to the top-of-file imports next to `import os`):

```python
def _names_from_manifest(source: Path) -> set[str]:
    """清单文件(JSON):对象取 key,数组取元素;解析失败返回空。"""
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if isinstance(data, dict):
        return {str(k) for k in data}
    if isinstance(data, list):
        return {str(x) for x in data}
    return set()


def _names_from_source(paths: Paths, source: Path) -> set[str]:
    if not source.exists():
        return set()
    if source.is_dir():
        return _names_in_tree(paths, source)
    return _names_from_manifest(source)


def owned_skill_names(paths: Paths, tool_cfg) -> set[str]:
    """工具所有的 skill 名:live 目录物理真身 ∪ 各 owned_source 声明。"""
    names = foreign_skill_names(paths, tool_cfg.path)
    for source in tool_cfg.owned_sources:
        names |= _names_from_source(paths, source)
    return names
```

At the top of `skm/boundary.py`, ensure `import json` is present (add it alongside `import os`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_boundary.py -v`
Expected: PASS (new `owned_*` tests plus all existing boundary tests, since `foreign_skill_names` behavior is unchanged).

- [ ] **Step 6: Commit**

```bash
git add skm/boundary.py tests/test_boundary.py
git commit -m "feat: owned_skill_names — detect tool ownership via manifest + tree

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Wire ownership into `purge_candidates`

**Files:**
- Modify: `skm/boundary.py` (`_tool_owned_names`)
- Test: `tests/test_boundary.py`

**Interfaces:**
- Consumes: `owned_skill_names` (Task 2).
- Produces: `_tool_owned_names(paths, cfg)` now unions `owned_skill_names` across tools, so `purge_candidates` flags central-repo skills that a tool owns *only via an owned_source* (no physical duplicate in the live dir).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_boundary.py`:

```python
def test_purge_candidates_via_owned_source(paths, make_skill, tool_dir, tmp_path):
    from skm.config import ToolCfg, load_config, save_config
    make_skill("webby")                     # 中央仓有 webby
    manifest = tmp_path / "managed.json"
    manifest.write_text('{"webby": {}}', encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"hermes": ToolCfg(path=tool_dir, owned_sources=[manifest])}
    save_config(paths, cfg)
    # tool_dir 里没有 webby 的物理真身,仅清单声明 → 仍应被判为工具血统
    assert "webby" in boundary.purge_candidates(paths, cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_boundary.py::test_purge_candidates_via_owned_source -v`
Expected: FAIL — `assert 'webby' in set()` (current `_tool_owned_names` only sees physical live-dir names).

- [ ] **Step 3: Union ownership across tools**

In `skm/boundary.py`, replace `_tool_owned_names`:

```python
def _tool_owned_names(paths: Paths, cfg: Config) -> set[str]:
    owned: set[str] = set()
    for tc in cfg.tools.values():
        owned |= owned_skill_names(paths, tc)
    return owned
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_boundary.py -v`
Expected: PASS (new test plus existing `purge`/`sync` tests unchanged — physical duplicates are still a subset of ownership).

- [ ] **Step 5: Commit**

```bash
git add skm/boundary.py tests/test_boundary.py
git commit -m "feat: purge_candidates sees ownership from owned_sources

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `sync_boundary --apply` handoff

**Files:**
- Modify: `skm/boundary.py` (`SyncReport`; `sync_boundary` apply link-loop)
- Test: `tests/test_boundary.py`

**Interfaces:**
- Consumes: `foreign_skill_names`, `skill_name`, `linker.remove_link` (returns after unlinking a repo-pointing symlink), `shutil.copytree`.
- Produces: `SyncReport.handoff: list[str]` (`"<tool>/<skill>"`). On `--apply`, for each purged link: if the skill's `name` is in the tool's independent native set → unlink only; else remove the skm symlink and `copytree` the central copy into the tool's live dir (materialize a real directory), recorded in `handoff`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_boundary.py`:

```python
def test_sync_apply_handoff_when_no_native(paths, make_skill, tool_dir, tmp_path):
    from skm.config import ToolCfg, load_config, save_config
    from skm.state import ToolState, save_state
    make_skill("webby")
    linker.create_link(paths, tool_dir, "webby")
    manifest = tmp_path / "m.json"
    manifest.write_text('{"webby": {}}', encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"hermes": ToolCfg(path=tool_dir, owned_sources=[manifest])}
    save_config(paths, cfg)
    save_state(paths, {"hermes": ToolState(links=["webby"])})

    rep = boundary.sync_boundary(paths, cfg, apply=True)

    assert "webby" in rep.purge
    assert "hermes/webby" in rep.handoff
    live = tool_dir / "webby"
    assert live.is_dir() and not live.is_symlink()      # 已移交实体真身
    assert (live / "SKILL.md").exists()
    assert not (paths.skills / "webby").exists()        # 中央仓副本已删


def test_sync_apply_unlink_only_when_native_exists(paths, make_skill, tool_dir):
    from skm.config import ToolCfg, load_config, save_config
    from skm.state import ToolState, save_state
    make_skill("plan")
    linker.create_link(paths, tool_dir, "plan")
    nat = tool_dir / "sd" / "plan"                       # 工具原生嵌套真身
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: plan\n---\n", encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    save_config(paths, cfg)
    save_state(paths, {"claude": ToolState(links=["plan"])})

    rep = boundary.sync_boundary(paths, cfg, apply=True)

    assert "plan" in rep.purge
    assert rep.handoff == []                             # 有原生副本 → 不移交
    assert not (tool_dir / "plan").is_symlink()          # 顶层 skm 链已删
    assert (nat / "SKILL.md").exists()                   # 原生真身留存
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_boundary.py -k "handoff or unlink_only" -v`
Expected: FAIL — `AttributeError: 'SyncReport' object has no attribute 'handoff'`.

- [ ] **Step 3: Add the `handoff` report field**

In `skm/boundary.py`, extend `SyncReport`:

```python
@dataclass
class SyncReport:
    purge: list[str] = field(default_factory=list)     # 中央仓 skill id
    unlinked: list[str] = field(default_factory=list)   # "<tool>/<skill>"
    deref: list[str] = field(default_factory=list)      # "<where>:<skill>"
    handoff: list[str] = field(default_factory=list)    # "<tool>/<skill>" 移交实体真身
    applied: bool = False
```

- [ ] **Step 4: Materialize on purge in `sync_boundary`**

In `sync_boundary`, replace the tool link-removal loop (the block that builds `keep` and calls `linker.remove_link`) with:

```python
    for tool, tc in sorted(cfg.tools.items()):
        ts = state.get(tool)
        if not ts:
            continue
        native = foreign_skill_names(paths, tc.path)   # 移交前算:此刻 skm 链被排除
        keep: list[str] = []
        for s in ts.links:
            if s not in purge:
                keep.append(s)
                continue
            nm = skill_name(paths.skills / s / "SKILL.md")
            src = paths.skills / s
            linker.remove_link(paths, tc.path, s)
            if nm not in native and src.is_dir() and not (tc.path / s).exists():
                shutil.copytree(src, tc.path / s)      # 移交:落实体真身给工具
                rep.handoff.append(f"{tool}/{s}")
        ts.links = keep
    save_state(paths, state)
```

(`shutil` and `skill_name` are already available in `skm/boundary.py`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_boundary.py -v`
Expected: PASS (both new tests; existing `sync-boundary` tests still pass — they exercise the native-exists / no-link paths).

- [ ] **Step 6: Commit**

```bash
git add skm/boundary.py tests/test_boundary.py
git commit -m "feat: sync-boundary --apply hands off real dir to tool

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `doctor` reporting + CLI handoff line

**Files:**
- Modify: `skm/cli.py` (`doctor` — append residual + missing-source checks; `_cmd_sync_boundary` — print handoff)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `boundary.purge_candidates`, `ToolCfg.owned_sources`, `SyncReport.handoff`.
- Produces: `doctor(paths, cfg)` appends `中央仓存在工具血统残留(可 sync-boundary 收敛): <name>` per residual and `<tool>: owned_source 路径不存在: <path>` per missing source; `_cmd_sync_boundary` prints a `移交实体真身给工具 N: ...` line when handoffs occurred.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def test_doctor_flags_owned_residual(paths, make_skill, tool_dir, tmp_path):
    from skm.cli import doctor
    from skm.config import ToolCfg, load_config, save_config
    make_skill("webby")
    manifest = tmp_path / "m.json"
    manifest.write_text('{"webby": {}}', encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"hermes": ToolCfg(path=tool_dir, owned_sources=[manifest])}
    save_config(paths, cfg)
    probs = doctor(paths, cfg)
    assert any("webby" in p and "血统残留" in p for p in probs)


def test_doctor_flags_missing_owned_source(paths, tool_dir, tmp_path):
    from skm.cli import doctor
    from skm.config import ToolCfg, load_config, save_config
    cfg = load_config(paths)
    cfg.tools = {"hermes": ToolCfg(path=tool_dir,
                                   owned_sources=[tmp_path / "gone.json"])}
    save_config(paths, cfg)
    probs = doctor(paths, cfg)
    assert any("owned_source 路径不存在" in p for p in probs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k "owned_residual or missing_owned" -v`
Expected: FAIL — the assertions find no matching problem string.

- [ ] **Step 3: Extend `doctor`**

In `skm/cli.py`, in `doctor()`, immediately before `return problems`:

```python
    for name in sorted(boundary.purge_candidates(paths, cfg)):
        problems.append(
            f"中央仓存在工具血统残留(可 sync-boundary 收敛): {name}")
    for tool, tc in sorted(cfg.tools.items()):
        for src in tc.owned_sources:
            if not src.exists():
                problems.append(f"{tool}: owned_source 路径不存在: {src}")
    return problems
```

- [ ] **Step 4: Print handoff in `_cmd_sync_boundary`**

In `skm/cli.py`, in `_cmd_sync_boundary`, after the `if rep.deref:` block and before `if rep.applied:`:

```python
    if rep.handoff:
        print(f"  移交实体真身给工具 {len(rep.handoff)}: {', '.join(rep.handoff)}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS (new doctor tests plus existing CLI tests).

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (entire suite green).

```bash
git add skm/cli.py tests/test_cli.py
git commit -m "feat: doctor flags tool-bloodline residuals + bad owned_source paths

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Apply to the real config (operator step — not TDD, gated)

**Files:**
- Modify: `~/.skm/config.toml` (`[tools.hermes]` — add `owned_sources`)

**Interfaces:**
- Consumes: the whole feature. Turns detection on for the user's real Hermes install.

> This task edits the user's real `~/.skm/config.toml`. **Confirm with the user before running it.** It is not covered by tests; verify by observing `skm doctor` output before/after.

- [ ] **Step 1: Snapshot current config**

```bash
cp ~/.skm/config.toml ~/.skm/config.toml.bak.$(date +%Y%m%d-%H%M%S)
```

- [ ] **Step 2: Add `owned_sources` via skm's own config API (avoids hand-editing TOML)**

Run:

```bash
cd /Users/jerrycheng/LocalStorage/GitHub/skm
.venv/bin/python - <<'PY'
from pathlib import Path
from skm.paths import Paths
from skm.config import load_config, save_config
paths = Paths.from_env()
cfg = load_config(paths)
cfg.tools["hermes"].owned_sources = [
    Path("~/.hermes/skills/.webui-managed-skills.json").expanduser(),
    Path("~/.hermes/hermes-agent/skills").expanduser(),
    Path("~/.hermes/hermes-agent/optional-skills").expanduser(),
]
save_config(paths, cfg)
print("owned_sources 已写入 [tools.hermes]")
PY
```

- [ ] **Step 3: Verify detection is live and clean**

Run: `.venv/bin/python bin/skm doctor`
Expected: `✓ 无问题` (the 7 residuals were already purged manually on 2026-07-14; no `owned_source 路径不存在` warnings, confirming all three paths resolve).

Run: `.venv/bin/python bin/skm sync-boundary`
Expected: `✓ 中央仓无工具自带的冗余副本,无需收敛` (central repo is already clean; this now proves detection runs against the Hermes ownership sources).

---

## Notes for the executor

- Run tests with the project venv: `.venv/bin/python -m pytest`.
- Tasks 1→5 are code (TDD, commit each). Task 6 is a one-time operator action on real state — do it last, only after the user confirms.
- Do **not** stage `skm/panel.html` (a pre-existing unrelated modification in the working tree).
