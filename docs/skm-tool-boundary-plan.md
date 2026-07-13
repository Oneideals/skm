# skm 跨工具边界与重名守卫 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 skm 只分发自有 skill、绝不与各工具自带 skill 撞名——加建链守卫、doctor 撞名检测、撞名链清理,并把中央仓收敛为"仅 skm 自有"。

**Architecture:** 新增 `skm/boundary.py` 承载边界域逻辑(识别工具"外来"skill 名、检测撞名、中央仓收敛)。`switcher._apply` 建链前查外来名并跳过;`cli.doctor` 增撞名报告;新增 `prune-collisions` 与 `sync-boundary` 两个子命令。判定"外来" = 扫工具 `skills/` 目录下非 skm 建(顶层不是指向中央仓的软链)的 SKILL.md 的 `name`。

**Tech Stack:** Python ≥3.11 纯标准库(`os`/`re`/`shutil`/`pathlib`/`dataclasses`),pytest。

## Global Constraints

- 纯标准库,零第三方运行时依赖(`pytest` 仅测试用)。
- 单文件 ≤ 400 行;小函数、不可变优先。
- TDD:先写失败测试(RED)→ 最小实现(GREEN)→ 重构。
- 标识符一律小写字母/数字/短横线。
- 删除软链沿用既有三重校验(`linker.points_into_repo`);破坏性操作前 `state.backup`,支持 `skm rollback`。
- 中央仓条目是真目录(非软链);工具自带真身**绝不删改**。

---

### Task 1: `boundary.py` 基础 — 解析 skill 名 + 工具外来名集合

**Files:**
- Create: `skm/boundary.py`
- Test: `tests/test_boundary.py`

**Interfaces:**
- Consumes: `linker.points_into_repo(paths, link) -> bool`;`Paths.skills`。
- Produces:
  - `skill_name(skill_md: Path) -> str` —— 取 frontmatter `name`,缺省用父目录名。
  - `foreign_skill_names(paths: Paths, tool_dir: Path) -> set[str]` —— 工具自带(非 skm 建)skill 的 name 集合。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_boundary.py
from skm import boundary, linker


def test_skill_name_from_frontmatter(paths, make_skill):
    d = make_skill("alpha")
    assert boundary.skill_name(d / "SKILL.md") == "alpha"


def test_skill_name_falls_back_to_dirname(paths, tool_dir):
    d = tool_dir / "beta"
    d.mkdir()
    (d / "SKILL.md").write_text("no frontmatter here\n", encoding="utf-8")
    assert boundary.skill_name(d / "SKILL.md") == "beta"


def test_foreign_names_includes_native_excludes_skm_links(paths, make_skill, tool_dir):
    # 工具自带:嵌套真目录(非 skm 建)
    nat = tool_dir / "cat" / "native-skill"
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: native-skill\n---\n", encoding="utf-8")
    # skm 链(指向中央仓)不算外来
    make_skill("mine")
    linker.create_link(paths, tool_dir, "mine")
    names = boundary.foreign_skill_names(paths, tool_dir)
    assert "native-skill" in names
    assert "mine" not in names


def test_foreign_names_empty_when_dir_absent(paths, tmp_path):
    assert boundary.foreign_skill_names(paths, tmp_path / "nope") == set()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_boundary.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'skm.boundary'`

- [ ] **Step 3: 写最小实现**

```python
# skm/boundary.py
"""跨工具边界:识别工具自带(外来)skill 名、检测撞名、中央仓收敛。

中央仓只放 skm 自有 skill;工具自带的归工具自己管。判定"外来" =
扫工具 skills 目录下、顶层不是"指向中央仓的软链"的 SKILL.md 的 name。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import linker
from .paths import Paths

_NAME_RE = re.compile(r"^name:\s*[\"']?([A-Za-z0-9_-]+)", re.M)


def skill_name(skill_md: Path) -> str:
    """从 SKILL.md frontmatter 取 name;缺省用所在目录名。"""
    try:
        text = skill_md.read_text(encoding="utf-8", errors="ignore")[:4000]
    except OSError:
        return skill_md.parent.name
    m = _NAME_RE.search(text)
    return m.group(1) if m else skill_md.parent.name


def foreign_skill_names(paths: Paths, tool_dir: Path) -> set[str]:
    """工具自带(非 skm 建)skill 的 name 集合。

    遍历时剪掉"指向中央仓的软链"目录——那是 skm 自己的,不算外来,
    也不进入其中递归(避免把中央仓的 skill 误当工具自带)。
    """
    names: set[str] = set()
    if not tool_dir.exists():
        return names
    for root, dirs, files in os.walk(tool_dir, followlinks=True):
        root_p = Path(root)
        dirs[:] = [
            d for d in dirs
            if not ((root_p / d).is_symlink()
                    and linker.points_into_repo(paths, root_p / d))
        ]
        if "SKILL.md" in files:
            names.add(skill_name(root_p / "SKILL.md"))
    return names
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_boundary.py -q`
Expected: PASS(4 passed)

- [ ] **Step 5: 提交**

```bash
git add skm/boundary.py tests/test_boundary.py
git commit -m "feat: boundary module — skill_name + foreign_skill_names"
```

---

### Task 2: 建链守卫 —— `_apply` 跳过与工具自带撞名的 skill

**Files:**
- Modify: `skm/switcher.py`(import `boundary`;`Report` 加 `blocked`;`_apply` 建链前过滤)
- Modify: `skm/cli.py:17-30`(`_print_report` 打印 blocked)
- Test: `tests/test_switcher.py`(新增一个用例)

**Interfaces:**
- Consumes: `boundary.foreign_skill_names(paths, tool_dir) -> set[str]`。
- Produces: `Report.blocked: list[str]`(被撞名跳过、未建链的 skill)。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_switcher.py 末尾
from skm.config import save_config


def test_guard_blocks_name_collision_with_tool_bundle(paths, cfg, tool_dir, make_skill):
    make_skill("plan")                                  # 中央仓有 plan
    cfg.groups["coding"].skills.append("plan")
    save_config(paths, cfg)
    nat = tool_dir / "software-development" / "plan"    # 工具自带嵌套同名(非 skm 建)
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: plan\n---\n", encoding="utf-8")
    rep = use(paths, cfg, "claude", ["coding"])
    assert "plan" in rep.blocked
    assert "plan" not in rep.created
    assert not (tool_dir / "plan").is_symlink()         # 没有平铺链进去
    assert "plan" not in load_state(paths)["claude"].links
    assert (nat / "SKILL.md").exists()                  # 工具自带真身不动
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_switcher.py::test_guard_blocks_name_collision_with_tool_bundle -q`
Expected: FAIL —— `AttributeError: 'Report' object has no attribute 'blocked'`

- [ ] **Step 3: 改 `Report` 与 `_apply`**

在 `skm/switcher.py` 顶部 import 增加 `boundary`:

```python
from . import boundary, linker
```

`Report` dataclass 增加字段(放在 `skipped` 之后):

```python
@dataclass
class Report:
    tool: str
    groups: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
```

`_apply` 的建链循环改为(在算出 `tool_dir` 后先取外来名,循环内先查):

```python
def _apply(paths: Paths, cfg: Config, state: dict[str, ToolState],
           tool: str, groups: list[str], target: set[str]) -> Report:
    tool_dir = cfg.tools[tool].path
    cur = state.get(tool, ToolState())
    backup(paths, tool, cur)
    rep = Report(tool=tool, groups=sorted(groups))
    for skill in sorted(set(cur.links) - target):
        status = linker.remove_link(paths, tool_dir, skill)
        if status in (linker.REMOVED, linker.MISSING):
            rep.removed.append(skill)
        else:
            rep.skipped.append(f"{skill}({status})")
    foreign = boundary.foreign_skill_names(paths, tool_dir)
    links: list[str] = []
    for skill in sorted(target):
        if skill in foreign:
            rep.blocked.append(skill)
            continue
        status = linker.create_link(paths, tool_dir, skill)
        if status == linker.CREATED:
            rep.created.append(skill)
            links.append(skill)
        elif status == linker.EXISTS_OK:
            rep.kept.append(skill)
            links.append(skill)
        else:
            rep.conflicts.append(f"{skill}({status})")
    state[tool] = ToolState(groups=sorted(groups), links=sorted(links))
    save_state(paths, state)
    return rep
```

在 `skm/cli.py` 的 `_print_report` 里,`skipped` 循环之后加 blocked 打印:

```python
    for s in rep.skipped:
        print(f"  ⚠ 跳过删除: {s}")
    for b in rep.blocked:
        print(f"  ⚠ 撞名跳过(工具自带同名,建链会致其加载失败): {b}")
    print(f"  重启 {rep.tool} 会话后生效")
```

- [ ] **Step 4: 跑测试确认通过(含回归)**

Run: `.venv/bin/python -m pytest tests/test_switcher.py -q`
Expected: PASS(原有用例 + 新用例全过;tool_dir 无工具自带时 `foreign` 为空,行为不变)

- [ ] **Step 5: 提交**

```bash
git add skm/switcher.py skm/cli.py tests/test_switcher.py
git commit -m "feat: linker guard — skip skills that name-collide with a tool's bundle"
```

---

### Task 3: `doctor` 撞名检测

**Files:**
- Modify: `skm/cli.py:138-172`(`doctor` 末尾增加撞名检查)
- Test: `tests/test_cli.py`(新增用例)

**Interfaces:**
- Consumes: `boundary.foreign_skill_names`、`linker.points_into_repo`。
- Produces: `doctor()` 返回的 problems 中新增形如 `"<tool>: 撞名(skm 链与工具自带同名,加载会失败): <skill>"`。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_cli.py
from skm import cli, linker
from skm.config import Group, ToolCfg, load_config, save_config


def test_doctor_reports_name_collision(paths, tool_dir, make_skill):
    make_skill("plan")
    linker.create_link(paths, tool_dir, "plan")          # skm 链 plan
    nat = tool_dir / "sd" / "plan"                        # 工具自带嵌套同名
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: plan\n---\n", encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    save_config(paths, cfg)
    problems = cli.doctor(paths, cfg)
    assert any("撞名" in p and "plan" in p for p in problems)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_cli.py::test_doctor_reports_name_collision -q`
Expected: FAIL —— `assert any(...)` 为 False(尚无撞名检查)

- [ ] **Step 3: 在 `doctor()` 末尾(`return problems` 之前)加检查**

先确保 `skm/cli.py` 顶部 import 含 `boundary`:

```python
from . import boundary, importer, linker, switcher
```

在 `doctor()` 的 `return problems` 前插入:

```python
    for tool, tc in sorted(cfg.tools.items()):
        tool_dir = tc.path
        if not tool_dir.exists():
            continue
        foreign = boundary.foreign_skill_names(paths, tool_dir)
        skm_names = {
            e.name for e in tool_dir.iterdir()
            if e.is_symlink() and linker.points_into_repo(paths, e)
        }
        for skill in sorted(skm_names & foreign):
            problems.append(
                f"{tool}: 撞名(skm 链与工具自带同名,加载会失败): {skill}")
    return problems
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add skm/cli.py tests/test_cli.py
git commit -m "feat: doctor detects skm-link vs tool-bundle name collisions"
```

---

### Task 4: `skm prune-collisions` —— 清撞名 skm 软链

**Files:**
- Modify: `skm/boundary.py`(加 `PruneReport` + `prune_collisions`)
- Modify: `skm/cli.py`(加 `_cmd_prune_collisions` + 子命令)
- Test: `tests/test_boundary.py`

**Interfaces:**
- Consumes: `foreign_skill_names`、`linker.points_into_repo`、`linker.remove_link`、`state.load_state/save_state`。
- Produces: `prune_collisions(paths, cfg, apply: bool = False) -> PruneReport`;`PruneReport.removed: list[str]`(形如 `"<tool>/<skill>"`)。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_boundary.py
from skm.config import ToolCfg, load_config, save_config


def _cfg_one_tool(paths, tool_dir):
    c = load_config(paths)
    c.tools = {"claude": ToolCfg(path=tool_dir)}
    save_config(paths, c)
    return c


def test_prune_collisions_removes_only_colliding_skm_links(paths, tool_dir, make_skill):
    make_skill("plan")
    make_skill("solo")
    linker.create_link(paths, tool_dir, "plan")
    linker.create_link(paths, tool_dir, "solo")
    nat = tool_dir / "sd" / "plan"
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: plan\n---\n", encoding="utf-8")
    cfg = _cfg_one_tool(paths, tool_dir)

    dry = boundary.prune_collisions(paths, cfg, apply=False)
    assert dry.removed == ["claude/plan"]
    assert (tool_dir / "plan").is_symlink()             # dry-run 不动

    boundary.prune_collisions(paths, cfg, apply=True)
    assert not (tool_dir / "plan").exists()             # 撞名链删了
    assert (tool_dir / "solo").is_symlink()             # 不撞名的留着
    assert (nat / "SKILL.md").exists()                  # 工具自带真身不动
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_boundary.py::test_prune_collisions_removes_only_colliding_skm_links -q`
Expected: FAIL —— `AttributeError: module 'skm.boundary' has no attribute 'prune_collisions'`

- [ ] **Step 3: 实现 `prune_collisions`**

在 `skm/boundary.py` 顶部 import 增补:

```python
from dataclasses import dataclass, field

from . import linker
from .config import Config
from .paths import Paths
from .state import load_state, save_state
```

追加:

```python
@dataclass
class PruneReport:
    removed: list[str] = field(default_factory=list)   # "<tool>/<skill>"


def prune_collisions(paths: Paths, cfg: Config, apply: bool = False) -> PruneReport:
    """删除"与工具自带撞名"的 skm 软链(只动 skm 建的链,不碰工具自带真身)。"""
    rep = PruneReport()
    state = load_state(paths)
    changed = False
    for tool, tc in sorted(cfg.tools.items()):
        tool_dir = tc.path
        if not tool_dir.exists():
            continue
        foreign = foreign_skill_names(paths, tool_dir)
        skm_links = {
            e.name for e in tool_dir.iterdir()
            if e.is_symlink() and linker.points_into_repo(paths, e)
        }
        for skill in sorted(skm_links & foreign):
            rep.removed.append(f"{tool}/{skill}")
            if apply:
                linker.remove_link(paths, tool_dir, skill)
                ts = state.get(tool)
                if ts and skill in ts.links:
                    ts.links = [s for s in ts.links if s != skill]
                    changed = True
    if apply and changed:
        save_state(paths, state)
    return rep
```

在 `skm/cli.py` 增加命令处理函数(放在 `_cmd_doctor` 附近):

```python
def _cmd_prune_collisions(paths: Paths, cfg: Config, args) -> int:
    rep = boundary.prune_collisions(paths, cfg, apply=args.apply)
    if not rep.removed:
        print("✓ 无撞名 skm 软链")
        return 0
    head = "已删除" if args.apply else "将删除(加 --apply 执行)"
    print(f"{head}撞名 skm 软链 {len(rep.removed)}: {', '.join(rep.removed)}")
    return 0
```

在 `_build_parser()` 里(`doctor` 之后)注册子命令:

```python
    p = sub.add_parser("prune-collisions", help="清掉与工具自带撞名的 skm 软链")
    p.add_argument("--apply", action="store_true", help="执行(默认仅预览)")
    p.set_defaults(fn=_cmd_prune_collisions)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_boundary.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add skm/boundary.py skm/cli.py tests/test_boundary.py
git commit -m "feat: skm prune-collisions removes colliding skm links"
```

---

### Task 5: `skm sync-boundary --dry-run` —— 中央仓收敛(预览)

**Files:**
- Modify: `skm/boundary.py`(加 `purge_candidates`、`SyncReport`、`sync_boundary` 的预览逻辑)
- Modify: `skm/cli.py`(加 `_cmd_sync_boundary` + 子命令)
- Test: `tests/test_boundary.py`

**Interfaces:**
- Consumes: `foreign_skill_names`、`Paths.skills`、`state.load_state`、`Config`。
- Produces:
  - `purge_candidates(paths, cfg) -> set[str]` —— 中央仓中 name 命中任一工具外来集合的 skill id。
  - `SyncReport(purge: list[str], unlinked: list[str], deref: list[str], applied: bool)`。
  - `sync_boundary(paths, cfg, apply: bool = False) -> SyncReport`(本任务只实现 `apply=False` 预览;`apply=True` 在 Task 6 补)。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_boundary.py
from skm.config import Group, Pack


def test_purge_candidates_and_dry_run(paths, tool_dir, make_skill):
    make_skill("plan")                                  # 与工具自带撞名 → 应 purge
    make_skill("mine")                                  # 纯自有 → 保留
    nat = tool_dir / "sd" / "plan"
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: plan\n---\n", encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    cfg.groups["coding"] = Group(skills=["plan", "mine"])
    save_config(paths, cfg)

    assert boundary.purge_candidates(paths, cfg) == {"plan"}

    rep = boundary.sync_boundary(paths, cfg, apply=False)
    assert rep.purge == ["plan"]
    assert "groups.coding:plan" in rep.deref
    assert rep.applied is False
    assert (paths.skills / "plan" / "SKILL.md").exists()   # 预览不删
    assert "plan" in load_config(paths).groups["coding"].skills  # 预览不改 config
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_boundary.py::test_purge_candidates_and_dry_run -q`
Expected: FAIL —— `AttributeError: ... has no attribute 'purge_candidates'`

- [ ] **Step 3: 实现 `purge_candidates` + `SyncReport` + 预览版 `sync_boundary`**

在 `skm/boundary.py` 追加:

```python
def _tool_owned_names(paths: Paths, cfg: Config) -> set[str]:
    owned: set[str] = set()
    for tc in cfg.tools.values():
        owned |= foreign_skill_names(paths, tc.path)
    return owned


def purge_candidates(paths: Paths, cfg: Config) -> set[str]:
    """中央仓里其实是某工具自带冗余副本的 skill id(name 命中任一工具外来集合)。"""
    if not paths.skills.exists():
        return set()
    owned = _tool_owned_names(paths, cfg)
    out: set[str] = set()
    for d in sorted(paths.skills.iterdir()):
        smd = d / "SKILL.md"
        if d.is_dir() and not d.is_symlink() and smd.exists():
            if skill_name(smd) in owned:
                out.add(d.name)
    return out


@dataclass
class SyncReport:
    purge: list[str] = field(default_factory=list)     # 中央仓 skill id
    unlinked: list[str] = field(default_factory=list)   # "<tool>/<skill>"
    deref: list[str] = field(default_factory=list)      # "<where>:<skill>"
    applied: bool = False


def _plan_sync(paths: Paths, cfg: Config, purge: set[str]) -> SyncReport:
    rep = SyncReport(purge=sorted(purge))
    state = load_state(paths)
    for tool, ts in sorted(state.items()):
        for s in sorted(set(ts.links) & purge):
            rep.unlinked.append(f"{tool}/{s}")
    for name in sorted(purge):
        if name in cfg.universal:
            rep.deref.append(f"universal:{name}")
        for tn, tc in sorted(cfg.tools.items()):
            if name in tc.skills:
                rep.deref.append(f"tools.{tn}:{name}")
        for pn, p in sorted(cfg.packs.items()):
            if name in p.skills:
                rep.deref.append(f"packs.{pn}:{name}")
        for gn, g in sorted(cfg.groups.items()):
            if name in g.skills:
                rep.deref.append(f"groups.{gn}:{name}")
    return rep


def sync_boundary(paths: Paths, cfg: Config, apply: bool = False) -> SyncReport:
    """中央仓收敛:把"其实是工具自带的冗余副本"清出中央仓。

    apply=False 仅预览(Task 5);apply=True 执行(Task 6)。
    """
    purge = purge_candidates(paths, cfg)
    rep = _plan_sync(paths, cfg, purge)
    if not apply or not purge:
        return rep
    rep.applied = True
    return rep
```

在 `skm/cli.py` 增加命令处理函数:

```python
def _cmd_sync_boundary(paths: Paths, cfg: Config, args) -> int:
    rep = boundary.sync_boundary(paths, cfg, apply=args.apply)
    if not rep.purge:
        print("✓ 中央仓无工具自带的冗余副本,无需收敛")
        return 0
    head = "已收敛" if rep.applied else "将收敛(加 --apply 执行)"
    print(f"{head}:purge {len(rep.purge)} 个中央仓副本")
    print("  " + ", ".join(rep.purge))
    if rep.unlinked:
        print(f"  解链 {len(rep.unlinked)}: {', '.join(rep.unlinked)}")
    if rep.deref:
        print(f"  摘除引用 {len(rep.deref)}: {', '.join(rep.deref)}")
    if rep.applied:
        print("  已备份各工具状态,可 skm rollback <tool> 回滚链路")
    return 0
```

在 `_build_parser()` 里注册(`prune-collisions` 之后):

```python
    p = sub.add_parser("sync-boundary",
                       help="中央仓收敛:清掉其实是工具自带的冗余副本")
    p.add_argument("--apply", action="store_true", help="执行(默认仅预览)")
    p.set_defaults(fn=_cmd_sync_boundary)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_boundary.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add skm/boundary.py skm/cli.py tests/test_boundary.py
git commit -m "feat: sync-boundary dry-run — purge_candidates + preview report"
```

---

### Task 6: `skm sync-boundary --apply` —— 执行收敛(带备份、可回滚)

**Files:**
- Modify: `skm/boundary.py`(`sync_boundary` 补 `apply=True` 的落地逻辑)
- Test: `tests/test_boundary.py`

**Interfaces:**
- Consumes: `state.backup`、`linker.remove_link`、`config.save_config`、`state.save_state`、`shutil.rmtree`。
- Produces: `sync_boundary(..., apply=True)` 副作用:删 skm 撞名链、摘 config 引用、删中央仓副本;操作前对每个工具 `backup`。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_boundary.py
from skm.state import load_state
from skm.switcher import use


def test_sync_boundary_apply_purges_copies_links_and_refs(paths, tool_dir, make_skill):
    make_skill("plan")                                  # 撞名 → purge
    make_skill("mine")                                  # 保留
    nat = tool_dir / "sd" / "plan"
    nat.mkdir(parents=True)
    (nat / "SKILL.md").write_text("---\nname: plan\n---\n", encoding="utf-8")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tool_dir)}
    cfg.groups["coding"] = Group(skills=["plan", "mine"])
    save_config(paths, cfg)
    # 先给 claude 建一条 plan 的 skm 链并登记到 state
    linker.create_link(paths, tool_dir, "plan")
    from skm.state import ToolState, save_state
    save_state(paths, {"claude": ToolState(groups=["coding"], links=["plan", "mine"])})

    rep = boundary.sync_boundary(paths, cfg, apply=True)
    assert rep.applied is True
    assert rep.purge == ["plan"]
    # 中央仓副本删除,保留 mine
    assert not (paths.skills / "plan").exists()
    assert (paths.skills / "mine" / "SKILL.md").exists()
    # skm 撞名链删除,工具自带真身保留
    assert not (tool_dir / "plan").exists()
    assert (nat / "SKILL.md").exists()
    # config 引用摘除
    assert "plan" not in load_config(paths).groups["coding"].skills
    assert "mine" in load_config(paths).groups["coding"].skills
    # state 里 plan 去掉、mine 保留
    assert load_state(paths)["claude"].links == ["mine"]
    # 有备份 → 可回滚
    assert list(paths.backups.glob("claude-*.json"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_boundary.py::test_sync_boundary_apply_purges_copies_links_and_refs -q`
Expected: FAIL —— 中央仓 `plan` 仍在 / config 未改(apply 分支尚未落地)

- [ ] **Step 3: 补 `sync_boundary` 的 apply 落地**

在 `skm/boundary.py` 顶部 import 增补 `shutil` 与 `backup`:

```python
import shutil
```

```python
from .state import backup, load_state, save_state
```

把 `sync_boundary` 替换为完整实现:

```python
def sync_boundary(paths: Paths, cfg: Config, apply: bool = False) -> SyncReport:
    """中央仓收敛:把"其实是工具自带的冗余副本"清出中央仓。

    apply=False 仅预览;apply=True 执行(操作前对每个工具备份,可 rollback)。
    落地顺序:备份 → 删 skm 链 + 更新 state → 摘 config 引用 → 删中央仓副本。
    """
    purge = purge_candidates(paths, cfg)
    rep = _plan_sync(paths, cfg, purge)
    if not apply or not purge:
        return rep

    state = load_state(paths)
    for tool in sorted(state):
        backup(paths, tool, state[tool])

    for tool, tc in sorted(cfg.tools.items()):
        ts = state.get(tool)
        if not ts:
            continue
        keep: list[str] = []
        for s in ts.links:
            if s in purge:
                linker.remove_link(paths, tc.path, s)
            else:
                keep.append(s)
        ts.links = keep
    save_state(paths, state)

    cfg.universal = [s for s in cfg.universal if s not in purge]
    for tc in cfg.tools.values():
        tc.skills = [s for s in tc.skills if s not in purge]
    for p in cfg.packs.values():
        p.skills = [s for s in p.skills if s not in purge]
    for g in cfg.groups.values():
        g.skills = [s for s in g.skills if s not in purge]
    save_config(paths, cfg)

    for name in sorted(purge):
        d = paths.skills / name
        if d.is_dir() and not d.is_symlink():
            shutil.rmtree(d)

    rep.applied = True
    return rep
```

`skm/boundary.py` 顶部 import 需含 `save_config`:

```python
from .config import Config, save_config
```

- [ ] **Step 4: 跑测试确认通过(全量)**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS(原 60 项 + 本计划新增全过)

- [ ] **Step 5: 提交**

```bash
git add skm/boundary.py tests/test_boundary.py
git commit -m "feat: sync-boundary --apply — purge copies, links, config refs with backup"
```

---

## Self-Review

**Spec 覆盖(逐条对照 `docs/skm-tool-boundary-design.md`):**
- §3 边界原则 / §4 守卫(X=①、Y=①)→ Task 1(外来名判定)+ Task 2(建链跳过+告警)。
- §5 doctor 重名检测 → Task 3。
- §6 中央仓收敛(purge、dry-run、apply、备份、rollback、config 摘除)→ Task 5 + Task 6。
- §7 命令面:`prune-collisions` → Task 4;`sync-boundary --dry-run|--apply` → Task 5/6;`doctor` 扩展 → Task 3。
- §8 代码触点:`boundary.py`(新)、`switcher.py`、`cli.py`、`config`/`state` 复用 → 覆盖。
- §9 测试计划各条 → 分布在各 Task 的测试里(守卫跳过/外来排除 skm 链/doctor 报出/prune 只删撞名链/sync dry-run 不动/apply 删副本+清链+摘引用+备份/纯自有不误 purge)。

**Placeholder 扫描:** 无 TBD/TODO;每个改码步骤都给出完整代码。

**类型一致性:** `foreign_skill_names`/`skill_name` 签名跨 Task 一致;`Report.blocked`、`PruneReport.removed`、`SyncReport.{purge,unlinked,deref,applied}` 命名前后统一;`sync_boundary(paths, cfg, apply)` 在 Task 5 定义、Task 6 扩展同签名。

**范围:** 单一子系统(skm 边界),六个任务各自可独立测试与评审。
