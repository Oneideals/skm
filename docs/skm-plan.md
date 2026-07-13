# skm 跨工具 Skill 管理器 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `skm` CLI:中央 skill 仓 + 软链分发到四个 AI CLI 工具,支持 pack(集合)成组启停与 scenario(场景)按工具切换。

**Architecture:** 纯 Python 标准库 CLI。`~/.skm/skills/` 为扁平中央仓;`config.toml` 声明 tools/base/packs/scenarios;`state.json` 记录每工具当前场景与 skm 所建软链(删除的唯一依据);切换 = 算差集 → 备份 → 增删软链。设计 spec 见 `/Users/jerrycheng/LocalStorage/Vibecoding/docs/skm-design.md`。

**Tech Stack:** Python ≥ 3.11(tomllib)、pathlib、json、os.symlink、subprocess(git clone)。测试用 pytest(仅开发依赖)。

## Global Constraints

- 运行时零第三方依赖;pytest 仅用于开发测试。
- Python ≥ 3.11(需要 `tomllib`)。
- 标识符(skill/pack/scenario 名)必须匹配 `^[a-z0-9][a-z0-9-]*$`;scenario 的 `label` 可为中文。
- 单文件 ≤ 400 行,单函数 ≤ 50 行,嵌套 ≤ 4 层(用户全局规范)。
- **删除软链三重校验**:①名字在 state 的 links 名单里 ②`is_symlink()` 为真 ③链接目标位于 `~/.skm/skills/` 下。任一不满足 → 跳过并警告,绝不删除。
- 中央仓永远扁平:`~/.skm/skills/<skill-name>/SKILL.md`。
- 所有破坏性操作(use/reset/rollback)先写备份快照到 `backups/`。
- 项目目录:`/Users/jerrycheng/LocalStorage/Vibecoding/skm/`(独立 git 仓)。
- 提交格式:`<type>: <description>`(feat/fix/test/chore/docs)。
- 测试一律从项目根目录跑:`python3 -m pytest`(该方式会把 cwd 加入 sys.path)。

---

### Task 1: 项目脚手架 + paths.py

**Files:**
- Create: `skm/__init__.py`
- Create: `skm/paths.py`
- Create: `tests/conftest.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: 无(首个任务)
- Produces: `Paths` dataclass — `Paths(home: Path)`;属性 `skills/config/state/backups -> Path`;`Paths.from_env() -> Paths`(读 `SKM_HOME` 环境变量,默认 `~/.skm`);`ensure() -> None`(建 home/skills/backups 目录)。所有后续模块以 `Paths` 实例为第一参数做依赖注入。测试 fixture:`paths`(临时 Paths)、`make_skill(name)`(在中央仓造假 skill)、`tool_dir`(临时工具目录)。

- [ ] **Step 1: 初始化项目与 git**

```bash
mkdir -p /Users/jerrycheng/LocalStorage/Vibecoding/skm/{skm,tests,bin}
cd /Users/jerrycheng/LocalStorage/Vibecoding/skm
git init
printf '__pycache__/\n*.pyc\n.pytest_cache/\n' > .gitignore
python3 --version   # 确认 ≥ 3.11
python3 -m pytest --version || python3 -m pip install --user pytest
```

预期:`git init` 成功;python ≥ 3.11;pytest 可用。

- [ ] **Step 2: 写失败测试**

`tests/test_paths.py`:
```python
from pathlib import Path

from skm.paths import Paths


def test_paths_layout(tmp_path):
    p = Paths(home=tmp_path / "skm")
    assert p.skills == tmp_path / "skm" / "skills"
    assert p.config == tmp_path / "skm" / "config.toml"
    assert p.state == tmp_path / "skm" / "state.json"
    assert p.backups == tmp_path / "skm" / "backups"


def test_from_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SKM_HOME", str(tmp_path / "custom"))
    assert Paths.from_env().home == tmp_path / "custom"


def test_ensure_creates_dirs(tmp_path):
    p = Paths(home=tmp_path / "skm")
    p.ensure()
    assert p.skills.is_dir() and p.backups.is_dir()
```

`tests/conftest.py`(共享 fixture,后续任务复用):
```python
from pathlib import Path

import pytest

from skm.paths import Paths


@pytest.fixture
def paths(tmp_path) -> Paths:
    p = Paths(home=tmp_path / "skm")
    p.ensure()
    return p


@pytest.fixture
def make_skill(paths):
    def _make(name: str) -> Path:
        d = paths.skills / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
        return d
    return _make


@pytest.fixture
def tool_dir(tmp_path) -> Path:
    d = tmp_path / "tools" / "claude"
    d.mkdir(parents=True)
    return d
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /Users/jerrycheng/LocalStorage/Vibecoding/skm && python3 -m pytest tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'skm'`(或 paths 不存在)

- [ ] **Step 4: 最小实现**

`skm/__init__.py`:
```python
__version__ = "0.1.0"
```

`skm/paths.py`:
```python
"""skm 路径解析。SKM_HOME 环境变量可覆盖(测试与隔离用)。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    home: Path

    @classmethod
    def from_env(cls) -> "Paths":
        return cls(home=Path(os.environ.get("SKM_HOME", "~/.skm")).expanduser())

    @property
    def skills(self) -> Path:
        return self.home / "skills"

    @property
    def config(self) -> Path:
        return self.home / "config.toml"

    @property
    def state(self) -> Path:
        return self.home / "state.json"

    @property
    def backups(self) -> Path:
        return self.home / "backups"

    def ensure(self) -> None:
        for d in (self.home, self.skills, self.backups):
            d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 -m pytest tests/test_paths.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: project scaffold and Paths with SKM_HOME override"
```

---

### Task 2: config.py — 配置读写、校验与 skill 集解析

**Files:**
- Create: `skm/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Paths`(Task 1)
- Produces:
  - `ConfigError(Exception)`
  - `@dataclass Pack(skills: list[str], source: str | None = None)`
  - `@dataclass Scenario(packs: list[str], label: str | None = None)`
  - `@dataclass Config(tools: dict[str, Path], base: list[str], packs: dict[str, Pack], scenarios: dict[str, Scenario])`
  - `ID_RE`(编译后的正则 `^[a-z0-9][a-z0-9-]*$`)
  - `load_config(paths) -> Config`(文件不存在 → 自动写默认配置:四工具路径、空 base/packs/scenarios)
  - `save_config(paths, cfg) -> None`(受控 TOML 序列化,字符串用 `json.dumps` 转义,支持中文 label)
  - `resolve_skills(cfg, scenario: str | None) -> set[str]`(base ∪ 场景所有 packs;`None` = 仅 base;未知场景抛 ConfigError)
  - `missing_in_repo(paths, skills: set[str]) -> list[str]`(中央仓缺 `<skill>/SKILL.md` 的名字,排序)

- [ ] **Step 1: 写失败测试**

`tests/test_config.py`:
```python
import pytest

from skm.config import (ConfigError, Pack, Scenario, load_config,
                        missing_in_repo, resolve_skills, save_config)


def test_load_creates_default(paths):
    cfg = load_config(paths)
    assert set(cfg.tools) == {"claude", "codex", "grok", "hermes"}
    assert cfg.base == [] and cfg.packs == {} and cfg.scenarios == {}
    assert paths.config.exists()


def test_roundtrip_with_chinese_label(paths):
    cfg = load_config(paths)
    cfg.base = ["code-review"]
    cfg.packs["research"] = Pack(skills=["web-research", "arxiv"], source="https://x/y.git")
    cfg.scenarios["research"] = Scenario(packs=["research"], label="调研")
    save_config(paths, cfg)
    cfg2 = load_config(paths)
    assert cfg2.packs["research"].skills == ["arxiv", "web-research"]  # 保存时排序
    assert cfg2.packs["research"].source == "https://x/y.git"
    assert cfg2.scenarios["research"].label == "调研"
    assert cfg2.base == ["code-review"]


def test_resolve_skills_union_and_dedupe(paths):
    cfg = load_config(paths)
    cfg.base = ["base-skill"]
    cfg.packs["a"] = Pack(skills=["s1", "s2"])
    cfg.packs["b"] = Pack(skills=["s2", "s3"])
    cfg.scenarios["mix"] = Scenario(packs=["a", "b"])
    assert resolve_skills(cfg, "mix") == {"base-skill", "s1", "s2", "s3"}
    assert resolve_skills(cfg, None) == {"base-skill"}


def test_resolve_unknown_scenario_raises(paths):
    cfg = load_config(paths)
    with pytest.raises(ConfigError):
        resolve_skills(cfg, "nope")


def test_scenario_referencing_missing_pack_raises(paths):
    cfg = load_config(paths)
    cfg.scenarios["bad"] = Scenario(packs=["ghost"])
    save_config(paths, cfg)
    with pytest.raises(ConfigError):
        load_config(paths)


def test_invalid_id_rejected_on_load(paths):
    load_config(paths)
    text = paths.config.read_text(encoding="utf-8")
    paths.config.write_text(text + '\n[packs."Bad Name"]\nskills = []\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(paths)


def test_missing_in_repo(paths, make_skill):
    make_skill("here")
    assert missing_in_repo(paths, {"here", "gone"}) == ["gone"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: FAIL — `No module named 'skm.config'`

- [ ] **Step 3: 实现 skm/config.py**

```python
"""config.toml 的读取、校验、写回与 skill 集解析。"""
from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .paths import Paths

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

DEFAULT_TOOLS = {
    "claude": "~/.claude/skills",
    "codex": "~/.codex/skills",
    "grok": "~/.grok/skills",
    "hermes": "~/.hermes/skills",
}


class ConfigError(Exception):
    pass


@dataclass
class Pack:
    skills: list[str] = field(default_factory=list)
    source: str | None = None


@dataclass
class Scenario:
    packs: list[str] = field(default_factory=list)
    label: str | None = None


@dataclass
class Config:
    tools: dict[str, Path]
    base: list[str]
    packs: dict[str, Pack]
    scenarios: dict[str, Scenario]


def _check_id(kind: str, name: str) -> None:
    if not ID_RE.match(name):
        raise ConfigError(f"{kind} 名 '{name}' 不合法:只允许小写字母/数字/短横线")


def default_config() -> Config:
    return Config(
        tools={k: Path(v).expanduser() for k, v in DEFAULT_TOOLS.items()},
        base=[], packs={}, scenarios={},
    )


def load_config(paths: Paths) -> Config:
    if not paths.config.exists():
        cfg = default_config()
        paths.ensure()
        save_config(paths, cfg)
        return cfg
    raw = tomllib.loads(paths.config.read_text(encoding="utf-8"))
    tools = {k: Path(str(v)).expanduser() for k, v in raw.get("tools", {}).items()}
    base = list(raw.get("base", {}).get("skills", []))
    packs: dict[str, Pack] = {}
    for name, body in raw.get("packs", {}).items():
        _check_id("pack", name)
        packs[name] = Pack(skills=list(body.get("skills", [])), source=body.get("source"))
    scenarios: dict[str, Scenario] = {}
    for name, body in raw.get("scenarios", {}).items():
        _check_id("scenario", name)
        scenarios[name] = Scenario(packs=list(body.get("packs", [])), label=body.get("label"))
    cfg = Config(tools=tools, base=base, packs=packs, scenarios=scenarios)
    _validate_refs(cfg)
    return cfg


def _validate_refs(cfg: Config) -> None:
    for sname, sc in cfg.scenarios.items():
        missing = [p for p in sc.packs if p not in cfg.packs]
        if missing:
            raise ConfigError(f"场景 '{sname}' 引用了不存在的 pack: {', '.join(missing)}")


def _toml_str(v: str) -> str:
    return json.dumps(v, ensure_ascii=False)


def _toml_list(items: list[str]) -> str:
    return "[" + ", ".join(_toml_str(i) for i in items) + "]"


def save_config(paths: Paths, cfg: Config) -> None:
    lines: list[str] = ["[tools]"]
    for k in sorted(cfg.tools):
        lines.append(f"{k} = {_toml_str(str(cfg.tools[k]))}")
    lines += ["", "[base]", f"skills = {_toml_list(sorted(cfg.base))}"]
    for name in sorted(cfg.packs):
        p = cfg.packs[name]
        lines += ["", f"[packs.{name}]", f"skills = {_toml_list(sorted(p.skills))}"]
        if p.source:
            lines.append(f"source = {_toml_str(p.source)}")
    for name in sorted(cfg.scenarios):
        s = cfg.scenarios[name]
        lines += ["", f"[scenarios.{name}]"]
        if s.label:
            lines.append(f"label = {_toml_str(s.label)}")
        lines.append(f"packs = {_toml_list(sorted(s.packs))}")
    paths.config.parent.mkdir(parents=True, exist_ok=True)
    paths.config.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_skills(cfg: Config, scenario: str | None) -> set[str]:
    """base ∪ scenario 所有 packs 的 skill,去重。scenario=None 表示仅 base。"""
    result = set(cfg.base)
    if scenario is not None:
        if scenario not in cfg.scenarios:
            known = ", ".join(sorted(cfg.scenarios)) or "(无)"
            raise ConfigError(f"场景 '{scenario}' 不存在。可用: {known}")
        for pname in cfg.scenarios[scenario].packs:
            result.update(cfg.packs[pname].skills)
    return result


def missing_in_repo(paths: Paths, skills: set[str]) -> list[str]:
    return sorted(s for s in skills if not (paths.skills / s / "SKILL.md").exists())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: config load/save/validate and skill-set resolution"
```

---

### Task 3: state.py — 状态与备份

**Files:**
- Create: `skm/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `Paths`
- Produces:
  - `@dataclass ToolState(scenario: str | None = None, links: list[str] = [])`
  - `load_state(paths) -> dict[str, ToolState]`(缺文件 → `{}`)
  - `save_state(paths, state) -> None`(links 排序后写 JSON)
  - `backup(paths, tool, ts: ToolState) -> Path`(写 `backups/<tool>-<YYYYmmdd-HHMMSS>-<NNN>.json`,含 `{"scenario","links"}`;同秒冲突递增 NNN)
  - `latest_backup(paths, tool) -> ToolState | None`(按文件名排序取最新)

- [ ] **Step 1: 写失败测试**

`tests/test_state.py`:
```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: FAIL — `No module named 'skm.state'`

- [ ] **Step 3: 实现 skm/state.py**

```python
"""state.json 读写与切换前备份。links 是 skm 所建软链的唯一记录。"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .paths import Paths


@dataclass
class ToolState:
    scenario: str | None = None
    links: list[str] = field(default_factory=list)


def load_state(paths: Paths) -> dict[str, ToolState]:
    if not paths.state.exists():
        return {}
    raw = json.loads(paths.state.read_text(encoding="utf-8"))
    return {
        tool: ToolState(scenario=body.get("scenario"), links=list(body.get("links", [])))
        for tool, body in raw.get("tools", {}).items()
    }


def save_state(paths: Paths, state: dict[str, ToolState]) -> None:
    raw = {"tools": {t: {"scenario": s.scenario, "links": sorted(s.links)}
                     for t, s in sorted(state.items())}}
    paths.ensure()
    paths.state.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def backup(paths: Paths, tool: str, ts: ToolState) -> Path:
    paths.ensure()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    n = 0
    while True:
        p = paths.backups / f"{tool}-{stamp}-{n:03d}.json"
        if not p.exists():
            break
        n += 1
    p.write_text(
        json.dumps({"scenario": ts.scenario, "links": sorted(ts.links)},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def latest_backup(paths: Paths, tool: str) -> ToolState | None:
    if not paths.backups.exists():
        return None
    cands = sorted(paths.backups.glob(f"{tool}-*.json"))
    if not cands:
        return None
    raw = json.loads(cands[-1].read_text(encoding="utf-8"))
    return ToolState(scenario=raw.get("scenario"), links=list(raw.get("links", [])))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: tool state persistence and pre-switch backups"
```

---

### Task 4: linker.py — 软链安全增删

**Files:**
- Create: `skm/linker.py`
- Test: `tests/test_linker.py`

**Interfaces:**
- Consumes: `Paths`
- Produces:
  - 状态常量:`CREATED, EXISTS_OK, CONFLICT, NO_SKILL, REMOVED, MISSING, NOT_SYMLINK, FOREIGN`(字符串)
  - `points_into_repo(paths, link: Path) -> bool`(readlink 原始目标归一化后是否位于 `paths.skills` 下;断链也能判定归属;非软链/读失败 → False)
  - `create_link(paths, tool_dir: Path, skill: str) -> str`(返回 CREATED/EXISTS_OK/CONFLICT/NO_SKILL;目标 skill 不在中央仓 → NO_SKILL;已有同名非我方内容 → CONFLICT,绝不覆盖)
  - `remove_link(paths, tool_dir: Path, skill: str) -> str`(三重校验的 ②③ 在此实现:非软链 → NOT_SYMLINK;外部软链 → FOREIGN;都不删。① 由调用方保证只传 state 名单内的名字)

- [ ] **Step 1: 写失败测试**

`tests/test_linker.py`:
```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_linker.py -v`
Expected: FAIL — `No module named 'skm.linker'`

- [ ] **Step 3: 实现 skm/linker.py**

```python
"""软链安全增删。删除三重校验:①state 名单由调用方保证;②③在本模块。"""
from __future__ import annotations

import os
from pathlib import Path

from .paths import Paths

CREATED = "created"
EXISTS_OK = "exists-ok"
CONFLICT = "conflict"
NO_SKILL = "no-skill"
REMOVED = "removed"
MISSING = "missing"
NOT_SYMLINK = "not-symlink"
FOREIGN = "foreign"


def points_into_repo(paths: Paths, link: Path) -> bool:
    if not link.is_symlink():
        return False
    try:
        raw = Path(os.readlink(link)).expanduser()
    except OSError:
        return False
    if not raw.is_absolute():
        raw = link.parent / raw
    # 不用 resolve():目标可能已删除(断链也要能识别归属)
    normalized = os.path.normpath(str(raw))
    return normalized.startswith(str(paths.skills) + os.sep)


def create_link(paths: Paths, tool_dir: Path, skill: str) -> str:
    target = paths.skills / skill
    if not (target / "SKILL.md").exists():
        return NO_SKILL
    tool_dir.mkdir(parents=True, exist_ok=True)
    dest = tool_dir / skill
    if dest.is_symlink():
        if points_into_repo(paths, dest) and os.readlink(dest) == str(target):
            return EXISTS_OK
        return CONFLICT
    if dest.exists():
        return CONFLICT
    os.symlink(target, dest)
    return CREATED


def remove_link(paths: Paths, tool_dir: Path, skill: str) -> str:
    dest = tool_dir / skill
    if not dest.is_symlink():
        return NOT_SYMLINK if dest.exists() else MISSING
    if not points_into_repo(paths, dest):
        return FOREIGN
    dest.unlink()
    return REMOVED
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_linker.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: safe symlink create/remove with ownership checks"
```

---

### Task 5: switcher.py — use / reset 核心算法

**Files:**
- Create: `skm/switcher.py`
- Test: `tests/test_switcher.py`

**Interfaces:**
- Consumes: `resolve_skills/missing_in_repo/Config/ConfigError`(Task 2)、`load_state/save_state/backup/ToolState`(Task 3)、`linker.*`(Task 4)
- Produces:
  - `SwitchError(Exception)`
  - `@dataclass Report(tool: str, scenario: str | None, created: list[str], removed: list[str], kept: list[str], conflicts: list[str], skipped: list[str])`
  - `use(paths, cfg, tool: str, scenario: str | None) -> Report`(scenario=None 即 reset 到仅 base;未知工具/场景抛错;目标 skill 缺失 → 落盘前抛错;流程:resolve → 校验 → 备份 → 差集增删 → 更新 state)
  - 内部 `_apply(paths, cfg, state, tool, scenario, target: set[str]) -> Report`(Task 6 的 rollback 复用)

- [ ] **Step 1: 写失败测试**

`tests/test_switcher.py`:
```python
import pytest

from skm.config import Pack, Scenario, load_config, save_config
from skm.state import load_state
from skm.switcher import SwitchError, use


@pytest.fixture
def cfg(paths, tool_dir, make_skill):
    for s in ("base-a", "s1", "s2", "s3"):
        make_skill(s)
    c = load_config(paths)
    c.tools = {"claude": tool_dir}
    c.base = ["base-a"]
    c.packs["p1"] = Pack(skills=["s1", "s2"])
    c.packs["p2"] = Pack(skills=["s3"])
    c.scenarios["one"] = Scenario(packs=["p1"], label="一")
    c.scenarios["two"] = Scenario(packs=["p2"])
    save_config(paths, c)
    return c


def test_use_links_base_and_scenario(paths, cfg, tool_dir):
    rep = use(paths, cfg, "claude", "one")
    assert sorted(rep.created) == ["base-a", "s1", "s2"]
    st = load_state(paths)
    assert st["claude"].scenario == "one"
    assert st["claude"].links == ["base-a", "s1", "s2"]
    assert (tool_dir / "s1").is_symlink()


def test_switch_scenario_diffs(paths, cfg, tool_dir):
    use(paths, cfg, "claude", "one")
    rep = use(paths, cfg, "claude", "two")
    assert rep.removed == ["s1", "s2"]
    assert rep.created == ["s3"]
    assert rep.kept == ["base-a"]          # base 原地不动
    assert not (tool_dir / "s1").exists()
    assert (tool_dir / "s3").is_symlink()


def test_reset_to_base_only(paths, cfg, tool_dir):
    use(paths, cfg, "claude", "one")
    rep = use(paths, cfg, "claude", None)
    assert rep.removed == ["s1", "s2"]
    assert load_state(paths)["claude"].links == ["base-a"]
    assert load_state(paths)["claude"].scenario is None


def test_idempotent(paths, cfg):
    use(paths, cfg, "claude", "one")
    rep = use(paths, cfg, "claude", "one")
    assert rep.created == [] and rep.removed == []


def test_missing_skill_aborts_before_touching_fs(paths, cfg, tool_dir):
    cfg.packs["p1"].skills.append("ghost")
    with pytest.raises(SwitchError, match="ghost"):
        use(paths, cfg, "claude", "one")
    assert not (tool_dir / "s1").exists()   # 未动文件系统


def test_unknown_tool(paths, cfg):
    with pytest.raises(SwitchError):
        use(paths, cfg, "vim", "one")


def test_never_touches_user_dirs(paths, cfg, tool_dir):
    (tool_dir / "my-own").mkdir()           # 用户手工目录
    use(paths, cfg, "claude", "one")
    use(paths, cfg, "claude", None)
    assert (tool_dir / "my-own").is_dir()   # 全程无恙
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_switcher.py -v`
Expected: FAIL — `No module named 'skm.switcher'`

- [ ] **Step 3: 实现 skm/switcher.py**

```python
"""场景切换核心:use(含 reset)。rollback 在本模块由 Task 6 补充。"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import linker
from .config import Config, missing_in_repo, resolve_skills
from .paths import Paths
from .state import ToolState, backup, load_state, save_state


class SwitchError(Exception):
    pass


@dataclass
class Report:
    tool: str
    scenario: str | None
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _apply(paths: Paths, cfg: Config, state: dict[str, ToolState],
           tool: str, scenario: str | None, target: set[str]) -> Report:
    tool_dir = cfg.tools[tool]
    cur = state.get(tool, ToolState())
    backup(paths, tool, cur)
    rep = Report(tool=tool, scenario=scenario)
    for skill in sorted(set(cur.links) - target):
        status = linker.remove_link(paths, tool_dir, skill)
        if status in (linker.REMOVED, linker.MISSING):
            rep.removed.append(skill)
        else:
            rep.skipped.append(f"{skill}({status})")
    links: list[str] = []
    for skill in sorted(target):
        status = linker.create_link(paths, tool_dir, skill)
        if status == linker.CREATED:
            rep.created.append(skill)
            links.append(skill)
        elif status == linker.EXISTS_OK:
            rep.kept.append(skill)
            links.append(skill)
        else:
            rep.conflicts.append(f"{skill}({status})")
    state[tool] = ToolState(scenario=scenario, links=sorted(links))
    save_state(paths, state)
    return rep


def use(paths: Paths, cfg: Config, tool: str, scenario: str | None) -> Report:
    if tool not in cfg.tools:
        raise SwitchError(f"未知工具 '{tool}'。可用: {', '.join(sorted(cfg.tools))}")
    target = resolve_skills(cfg, scenario)
    missing = missing_in_repo(paths, target)
    if missing:
        raise SwitchError(
            "中央仓缺少以下 skill,请先 skm install/import: " + ", ".join(missing))
    state = load_state(paths)
    return _apply(paths, cfg, state, tool, scenario, target)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_switcher.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: scenario switch core with diff apply and base preservation"
```

---

### Task 6: switcher.py — rollback

**Files:**
- Modify: `skm/switcher.py`(文件末尾追加 rollback 函数)
- Test: `tests/test_rollback.py`

**Interfaces:**
- Consumes: `_apply`、`latest_backup`(Task 3)
- Produces: `rollback(paths, cfg, tool: str) -> Report` — 读最新备份(在写新备份**之前**读,否则会读到自己),按快照的 links 集合恢复,scenario 恢复为快照值;无备份抛 SwitchError。连续 rollback 两次 = 在最近两个状态间切换(toggle),这是预期行为。

- [ ] **Step 1: 写失败测试**

`tests/test_rollback.py`:
```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_rollback.py -v`
Expected: FAIL — `ImportError: cannot import name 'rollback'`

- [ ] **Step 3: 在 skm/switcher.py 末尾追加**

```python
def rollback(paths: Paths, cfg: Config, tool: str) -> Report:
    if tool not in cfg.tools:
        raise SwitchError(f"未知工具 '{tool}'。可用: {', '.join(sorted(cfg.tools))}")
    snap = latest_backup(paths, tool)   # 必须在 _apply 写新备份之前读
    if snap is None:
        raise SwitchError(f"'{tool}' 没有可回滚的备份")
    state = load_state(paths)
    return _apply(paths, cfg, state, tool, snap.scenario, set(snap.links))
```

同时把文件顶部的 state 导入行改为:
```python
from .state import ToolState, backup, latest_backup, load_state, save_state
```

- [ ] **Step 4: 跑全部测试确认通过**

Run: `python3 -m pytest -v`
Expected: 全部 passed(paths/config/state/linker/switcher/rollback)

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: rollback to latest pre-switch snapshot"
```

---

### Task 7: importer.py — 本地安装与 skill 目录发现

**Files:**
- Create: `skm/importer.py`
- Test: `tests/test_importer.py`

**Interfaces:**
- Consumes: `Paths`
- Produces:
  - `ImporterError(Exception)`
  - `SKIP_DIRS = {".git", ".github", "node_modules", "__pycache__"}`
  - `find_skill_dirs(root: Path) -> list[Path]`(递归找含 SKILL.md 的目录;跳过 SKIP_DIRS 与任何以 `.` 开头的路径段;排序稳定)
  - `install_local(paths, src: Path, name: str | None = None, force: bool = False) -> str`(返回 "installed"/"skipped";无 SKILL.md 抛 ImporterError;目标已存在且非 force → skipped;copytree 复制,忽略 SKIP_DIRS)

- [ ] **Step 1: 写失败测试**

`tests/test_importer.py`:
```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_importer.py -v`
Expected: FAIL — `No module named 'skm.importer'`

- [ ] **Step 3: 实现 skm/importer.py(第一部分)**

```python
"""导入:skill 目录发现、本地安装、git 仓库拍平导入与 pack 注册。"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, Pack, save_config
from .paths import Paths

SKIP_DIRS = {".git", ".github", "node_modules", "__pycache__"}


class ImporterError(Exception):
    pass


@dataclass
class ImportReport:
    installed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    packs: dict[str, list[str]] = field(default_factory=dict)


def find_skill_dirs(root: Path) -> list[Path]:
    out: list[Path] = []
    for md in sorted(root.rglob("SKILL.md")):
        d = md.parent
        parts = d.relative_to(root).parts
        if any(p in SKIP_DIRS or p.startswith(".") for p in parts):
            continue
        out.append(d)
    return out


def install_local(paths: Paths, src: Path, name: str | None = None,
                  force: bool = False) -> str:
    src = src.expanduser()
    if not (src / "SKILL.md").exists():
        raise ImporterError(f"{src} 里没有 SKILL.md,不是有效 skill")
    dest = paths.skills / (name or src.name)
    if dest.exists():
        if not force:
            return "skipped"
        shutil.rmtree(dest)
    paths.ensure()
    shutil.copytree(src, dest, symlinks=False,
                    ignore=shutil.ignore_patterns(*SKIP_DIRS))
    return "installed"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_importer.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: skill discovery and flattening local install"
```

---

### Task 8: importer.py — git 仓库导入、split-by-dir 与 upgrade

**Files:**
- Modify: `skm/importer.py`(末尾追加)
- Test: `tests/test_import_repo.py`

**Interfaces:**
- Consumes: Task 7 的 `find_skill_dirs/install_local/ImportReport`、`Config/Pack/save_config`(Task 2)
- Produces:
  - `import_repo(paths, cfg, url: str, name: str | None = None, split_by_dir: bool = False, force: bool = False) -> ImportReport`(`git clone --depth 1`;无 SKILL.md 抛错不建 pack;pack 名 = name 或 repo slug;split_by_dir 时按"skill 目录的父目录名"分组:父目录是仓库根或名为 `skills` → 归入基础 pack,否则 pack 名为 `<base>-<父目录 slug>`;写回 config 时与已有同名 pack 的 skills 合并,source=url)
  - `upgrade(paths, cfg, pack_name: str) -> ImportReport`(按 pack.source 重新 import,force=True;无 source 抛错)
  - 测试用本地 git 仓固定装置(`git init` + commit,clone 本地路径与 URL 走同一代码路径)

- [ ] **Step 1: 写失败测试**

`tests/test_import_repo.py`:
```python
import subprocess

import pytest

from skm.config import load_config
from skm.importer import ImporterError, import_repo, upgrade


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """本地 git 仓:skills/alpha(扁平) + skills/engineering/beta(分类)。"""
    r = tmp_path / "srcrepo"
    for rel in ("skills/alpha", "skills/engineering/beta"):
        d = r / rel
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return r


def test_import_whole_repo_one_pack(paths, repo):
    cfg = load_config(paths)
    rep = import_repo(paths, cfg, str(repo), name="mypack")
    assert sorted(rep.installed) == ["alpha", "beta"]
    assert rep.packs == {"mypack": ["alpha", "beta"]}
    cfg2 = load_config(paths)
    assert cfg2.packs["mypack"].skills == ["alpha", "beta"]
    assert cfg2.packs["mypack"].source == str(repo)
    assert (paths.skills / "beta" / "SKILL.md").exists()  # 拍平了


def test_import_split_by_dir(paths, repo):
    cfg = load_config(paths)
    rep = import_repo(paths, cfg, str(repo), name="mp", split_by_dir=True)
    assert rep.packs == {"mp": ["alpha"], "mp-engineering": ["beta"]}


def test_import_no_skills_raises(paths, tmp_path):
    r = tmp_path / "empty"
    r.mkdir()
    _git(r, "init", "-q")
    (r / "README.md").write_text("x", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
    cfg = load_config(paths)
    with pytest.raises(ImporterError):
        import_repo(paths, cfg, str(r))
    assert "empty" not in load_config(paths).packs


def test_upgrade_uses_source(paths, repo):
    cfg = load_config(paths)
    import_repo(paths, cfg, str(repo), name="mypack")
    (repo / "skills" / "alpha" / "SKILL.md").write_text("v2", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v2")
    cfg = load_config(paths)
    rep = upgrade(paths, cfg, "mypack")
    assert "alpha" in rep.installed   # force 覆盖
    assert (paths.skills / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "v2"


def test_upgrade_without_source_raises(paths):
    cfg = load_config(paths)
    with pytest.raises(ImporterError):
        upgrade(paths, cfg, "ghost")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_import_repo.py -v`
Expected: FAIL — `ImportError: cannot import name 'import_repo'`

- [ ] **Step 3: 在 skm/importer.py 末尾追加**

```python
def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")
    return s or "imported"


def _repo_slug(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    return _slug(tail.removesuffix(".git"))


def _group_key(repo_root: Path, skill_dir: Path, base: str) -> str:
    parent = skill_dir.parent
    if parent == repo_root or parent.name == "skills":
        return base
    return f"{base}-{_slug(parent.name)}"


def import_repo(paths: Paths, cfg: Config, url: str, name: str | None = None,
                split_by_dir: bool = False, force: bool = False) -> ImportReport:
    base = name or _repo_slug(url)
    rep = ImportReport()
    with tempfile.TemporaryDirectory(prefix="skm-import-") as td:
        clone_dir = str(Path(td) / "repo")
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", url, clone_dir],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise ImporterError(f"git clone 失败: {proc.stderr.strip()[:300]}")
        root = Path(clone_dir)
        dirs = find_skill_dirs(root)
        if not dirs:
            raise ImporterError("仓库里没找到任何 SKILL.md,不建 pack")
        for d in dirs:
            skill_name = base if d == root else d.name
            status = install_local(paths, d, name=skill_name, force=force)
            bucket = rep.installed if status == "installed" else rep.skipped
            bucket.append(skill_name)
            key = _group_key(root, d, base) if split_by_dir else base
            rep.packs.setdefault(key, []).append(skill_name)
    for pname in rep.packs:
        rep.packs[pname] = sorted(set(rep.packs[pname]))
        old = cfg.packs.get(pname)
        merged = sorted(set(rep.packs[pname]) | set(old.skills if old else []))
        cfg.packs[pname] = Pack(skills=merged, source=url)
    save_config(paths, cfg)
    return rep


def upgrade(paths: Paths, cfg: Config, pack_name: str) -> ImportReport:
    p = cfg.packs.get(pack_name)
    if p is None or not p.source:
        raise ImporterError(f"pack '{pack_name}' 不存在或没有 source,无法升级")
    return import_repo(paths, cfg, p.source, name=pack_name, force=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_import_repo.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: git repo import with flatten, split-by-dir and upgrade"
```

---

### Task 9: cli.py — 全命令行接口 + doctor

**Files:**
- Create: `skm/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: 前面全部模块
- Produces: `main(argv: list[str] | None = None) -> int`(0 成功;1 失败;有 conflicts/skipped 时打警告但返回 0)。子命令:
  - `skm use <tool|all> <scenario>` / `skm reset <tool>` / `skm rollback <tool>`
  - `skm list` / `skm packs` / `skm scenarios`
  - `skm install <path> [--name N] [--force]`
  - `skm import <url> [--name N] [--split-by-dir] [--force]`
  - `skm pack create <name> --skills a,b,c`
  - `skm upgrade <pack>`
  - `skm doctor`
  - `doctor(paths, cfg) -> list[str]` 检查:config 引用缺失 skill、中央仓无 SKILL.md 的目录、state 记录的链不在磁盘/断链、工具目录里不在 state 的孤儿 skm 链。

- [ ] **Step 1: 写失败测试**

`tests/test_cli.py`:
```python
import pytest

from skm.cli import main
from skm.config import Pack, Scenario, load_config, save_config


@pytest.fixture
def env(paths, tool_dir, make_skill, monkeypatch):
    monkeypatch.setenv("SKM_HOME", str(paths.home))
    for s in ("s1", "s2"):
        make_skill(s)
    cfg = load_config(paths)
    cfg.tools = {"claude": tool_dir}
    cfg.packs["p1"] = Pack(skills=["s1"])
    cfg.scenarios["research"] = Scenario(packs=["p1"], label="调研")
    save_config(paths, cfg)
    return paths, tool_dir


def test_use_and_list(env, capsys):
    paths, tool_dir = env
    assert main(["use", "claude", "research"]) == 0
    assert (tool_dir / "s1").is_symlink()
    out = capsys.readouterr().out
    assert "research" in out and "重启" in out
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "调研" in out and "s1" in out


def test_reset_and_rollback(env):
    paths, tool_dir = env
    main(["use", "claude", "research"])
    assert main(["reset", "claude"]) == 0
    assert not (tool_dir / "s1").exists()
    assert main(["rollback", "claude"]) == 0
    assert (tool_dir / "s1").is_symlink()


def test_use_unknown_scenario_fails(env, capsys):
    assert main(["use", "claude", "nope"]) == 1
    assert "不存在" in capsys.readouterr().err


def test_pack_create(env, capsys):
    paths, _ = env
    assert main(["pack", "create", "p2", "--skills", "s1,s2"]) == 0
    assert load_config(paths).packs["p2"].skills == ["s1", "s2"]
    assert main(["pack", "create", "Bad!", "--skills", "s1"]) == 1


def test_install_cli(env, tmp_path, capsys):
    paths, _ = env
    src = tmp_path / "newskill"
    src.mkdir()
    (src / "SKILL.md").write_text("x", encoding="utf-8")
    assert main(["install", str(src)]) == 0
    assert (paths.skills / "newskill" / "SKILL.md").exists()


def test_doctor_reports_problems(env, capsys):
    paths, tool_dir = env
    cfg = load_config(paths)
    cfg.packs["p1"].skills.append("ghost")
    save_config(paths, cfg)
    assert main(["doctor"]) == 1
    assert "ghost" in capsys.readouterr().out


def test_doctor_clean(env, capsys):
    assert main(["doctor"]) == 0
    assert "无问题" in capsys.readouterr().out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: FAIL — `No module named 'skm.cli'`

- [ ] **Step 3: 实现 skm/cli.py**

```python
"""skm 命令行入口。所有子命令都在这里分发。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import importer, linker, switcher
from .config import (ID_RE, Config, ConfigError, Pack, load_config,
                     missing_in_repo, save_config)
from .paths import Paths
from .state import load_state
from .switcher import Report, SwitchError


def _print_report(rep: Report) -> None:
    label = rep.scenario if rep.scenario is not None else "(仅 base)"
    print(f"{rep.tool} → {label}")
    if rep.created:
        print(f"  新增 {len(rep.created)}: {', '.join(rep.created)}")
    if rep.removed:
        print(f"  移除 {len(rep.removed)}: {', '.join(rep.removed)}")
    if rep.kept:
        print(f"  保留 {len(rep.kept)}: {', '.join(rep.kept)}")
    for c in rep.conflicts:
        print(f"  ⚠ 冲突未动: {c}")
    for s in rep.skipped:
        print(f"  ⚠ 跳过删除: {s}")
    print(f"  重启 {rep.tool} 会话后生效")


def _cmd_use(paths: Paths, cfg: Config, args) -> int:
    tools = sorted(cfg.tools) if args.tool == "all" else [args.tool]
    for t in tools:
        _print_report(switcher.use(paths, cfg, t, args.scenario))
    return 0


def _cmd_reset(paths: Paths, cfg: Config, args) -> int:
    _print_report(switcher.use(paths, cfg, args.tool, None))
    return 0


def _cmd_rollback(paths: Paths, cfg: Config, args) -> int:
    _print_report(switcher.rollback(paths, cfg, args.tool))
    return 0


def _cmd_list(paths: Paths, cfg: Config, args) -> int:
    state = load_state(paths)
    for tool in sorted(cfg.tools):
        ts = state.get(tool)
        if ts is None:
            print(f"{tool}: (未由 skm 管理)")
            continue
        label = "(仅 base)"
        if ts.scenario:
            sc = cfg.scenarios.get(ts.scenario)
            zh = f"({sc.label})" if sc and sc.label else ""
            label = f"{ts.scenario}{zh}"
        print(f"{tool}: {label} — {len(ts.links)} 个 skill")
        if ts.links:
            print(f"  {', '.join(ts.links)}")
    return 0


def _cmd_packs(paths: Paths, cfg: Config, args) -> int:
    if not cfg.packs:
        print("(还没有 pack,用 skm import 或 skm pack create)")
    for name in sorted(cfg.packs):
        p = cfg.packs[name]
        src = f"  [{p.source}]" if p.source else ""
        print(f"{name} ({len(p.skills)}){src}")
        print(f"  {', '.join(p.skills)}")
    return 0


def _cmd_scenarios(paths: Paths, cfg: Config, args) -> int:
    if not cfg.scenarios:
        print("(还没有场景,直接编辑 config.toml 的 [scenarios.*])")
    for name in sorted(cfg.scenarios):
        s = cfg.scenarios[name]
        zh = f"({s.label})" if s.label else ""
        print(f"{name}{zh}: packs = {', '.join(s.packs) or '(空)'}")
    return 0


def _cmd_install(paths: Paths, cfg: Config, args) -> int:
    status = importer.install_local(
        paths, Path(args.path), name=args.name, force=args.force)
    print(f"{args.path}: {status}")
    return 0


def _cmd_import(paths: Paths, cfg: Config, args) -> int:
    if args.name and not ID_RE.match(args.name):
        print(f"pack 名 '{args.name}' 不合法(小写字母/数字/短横线)", file=sys.stderr)
        return 1
    rep = importer.import_repo(paths, cfg, args.url, name=args.name,
                               split_by_dir=args.split_by_dir, force=args.force)
    print(f"安装 {len(rep.installed)},跳过(已存在) {len(rep.skipped)}")
    for pname, skills in sorted(rep.packs.items()):
        print(f"pack {pname}: {', '.join(skills)}")
    return 0


def _cmd_pack_create(paths: Paths, cfg: Config, args) -> int:
    if not ID_RE.match(args.pack_name):
        print(f"pack 名 '{args.pack_name}' 不合法(小写字母/数字/短横线)",
              file=sys.stderr)
        return 1
    skills = [s.strip() for s in args.skills.split(",") if s.strip()]
    missing = missing_in_repo(paths, set(skills))
    if missing:
        print(f"⚠ 以下 skill 不在中央仓(仍会登记): {', '.join(missing)}")
    cfg.packs[args.pack_name] = Pack(skills=sorted(set(skills)))
    save_config(paths, cfg)
    print(f"pack {args.pack_name}: {len(skills)} 个 skill 已登记")
    return 0


def _cmd_upgrade(paths: Paths, cfg: Config, args) -> int:
    rep = importer.upgrade(paths, cfg, args.pack)
    print(f"pack {args.pack} 已升级:更新 {len(rep.installed)} 个 skill")
    return 0


def doctor(paths: Paths, cfg: Config) -> list[str]:
    problems: list[str] = []
    referenced = set(cfg.base)
    for p in cfg.packs.values():
        referenced |= set(p.skills)
    for m in missing_in_repo(paths, referenced):
        problems.append(f"config 引用的 skill 不在中央仓: {m}")
    if paths.skills.exists():
        for d in sorted(paths.skills.iterdir()):
            if d.is_dir() and not (d / "SKILL.md").exists():
                problems.append(f"中央仓目录缺 SKILL.md: {d.name}")
    state = load_state(paths)
    for tool, ts in sorted(state.items()):
        tool_dir = cfg.tools.get(tool)
        if tool_dir is None:
            problems.append(f"state 里有未知工具: {tool}")
            continue
        for skill in ts.links:
            link = tool_dir / skill
            if not link.is_symlink():
                problems.append(f"{tool}: state 记录的链不存在或非软链: {skill}")
            elif not (paths.skills / skill / "SKILL.md").exists():
                problems.append(f"{tool}: 断链(中央仓已无此 skill): {skill}")
        if tool_dir.exists():
            recorded = set(ts.links)
            for entry in sorted(tool_dir.iterdir()):
                if (entry.is_symlink() and linker.points_into_repo(paths, entry)
                        and entry.name not in recorded):
                    problems.append(f"{tool}: 孤儿 skm 软链(不在 state): {entry.name}")
    return problems


def _cmd_doctor(paths: Paths, cfg: Config, args) -> int:
    problems = doctor(paths, cfg)
    if not problems:
        print("✓ 无问题")
        return 0
    for p in problems:
        print(f"✗ {p}")
    return 1


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="skm", description="跨工具 skill 管理器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("use", help="切工具到场景(all = 所有工具)")
    p.add_argument("tool")
    p.add_argument("scenario")
    p.set_defaults(fn=_cmd_use)

    p = sub.add_parser("reset", help="清到仅 base")
    p.add_argument("tool")
    p.set_defaults(fn=_cmd_reset)

    p = sub.add_parser("rollback", help="回滚到上次切换前")
    p.add_argument("tool")
    p.set_defaults(fn=_cmd_rollback)

    sub.add_parser("list", help="各工具当前场景").set_defaults(fn=_cmd_list)
    sub.add_parser("packs", help="所有集合").set_defaults(fn=_cmd_packs)
    sub.add_parser("scenarios", help="所有场景").set_defaults(fn=_cmd_scenarios)

    p = sub.add_parser("install", help="装单个本地 skill 进中央仓")
    p.add_argument("path")
    p.add_argument("--name")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=_cmd_install)

    p = sub.add_parser("import", help="导入 git 仓库为 pack")
    p.add_argument("url")
    p.add_argument("--name")
    p.add_argument("--split-by-dir", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=_cmd_import)

    p = sub.add_parser("pack", help="pack 管理")
    psub = p.add_subparsers(dest="pack_cmd", required=True)
    pc = psub.add_parser("create", help="手挑集合")
    pc.add_argument("pack_name")
    pc.add_argument("--skills", required=True, help="逗号分隔")
    pc.set_defaults(fn=_cmd_pack_create)

    p = sub.add_parser("upgrade", help="按 source 升级 pack")
    p.add_argument("pack")
    p.set_defaults(fn=_cmd_upgrade)

    sub.add_parser("doctor", help="健康检查").set_defaults(fn=_cmd_doctor)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    paths = Paths.from_env()
    try:
        cfg = load_config(paths)
        return args.fn(paths, cfg, args)
    except (ConfigError, SwitchError, importer.ImporterError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_cli.py -v && python3 -m pytest -q`
Expected: test_cli 7 passed;全套无回归

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: full CLI with use/reset/rollback/list/import/doctor"
```

---

### Task 10: bin/skm 入口 + PATH 安装 + 端到端冒烟

**Files:**
- Create: `bin/skm`
- Create: `~/.local/bin/skm`(软链到项目 bin/skm)

**Interfaces:**
- Consumes: `skm.cli.main`
- Produces: 终端里全局可用的 `skm` 命令。冒烟测试全程用 `SKM_HOME=/tmp/skm-smoke` 隔离,**不碰真实 `~/.skm` 和四个工具目录**。

- [ ] **Step 1: 写入口脚本**

`bin/skm`:
```python
#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skm.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

```bash
chmod +x bin/skm
ln -sf /Users/jerrycheng/LocalStorage/Vibecoding/skm/bin/skm ~/.local/bin/skm
```

- [ ] **Step 2: 端到端冒烟(隔离环境)**

```bash
export SKM_HOME=/tmp/skm-smoke
rm -rf /tmp/skm-smoke /tmp/skm-smoke-tools
mkdir -p /tmp/skm-smoke-tools/claude

skm list                      # 触发默认 config 生成
# 把 config 的 tools 改成冒烟目录(避免碰真实工具)
python3 - <<'EOF'
from pathlib import Path
p = Path("/tmp/skm-smoke/config.toml")
text = p.read_text(encoding="utf-8")
import re
text = re.sub(r'\[tools\][^\[]*', '[tools]\nclaude = "/tmp/skm-smoke-tools/claude"\n\n', text, count=1)
p.write_text(text, encoding="utf-8")
EOF

mkdir -p /tmp/fake-skill && printf -- '---\nname: fake\n---\nhi\n' > /tmp/fake-skill/SKILL.md
skm install /tmp/fake-skill
skm pack create demo --skills fake-skill
printf '\n[scenarios.demo]\nlabel = "演示"\npacks = ["demo"]\n' >> /tmp/skm-smoke/config.toml
skm use claude demo
ls -la /tmp/skm-smoke-tools/claude        # 应看到 fake-skill 软链
skm list && skm doctor
skm reset claude && skm rollback claude
skm doctor
unset SKM_HOME
```

Expected: `use` 后软链存在且指向 `/tmp/skm-smoke/skills/fake-skill`;`doctor` 输出 `✓ 无问题`;`rollback` 后软链恢复。

注:install 后的 skill 名是源目录名 `fake-skill`。

- [ ] **Step 3: 清理冒烟残留 + Commit**

```bash
rm -rf /tmp/skm-smoke /tmp/skm-smoke-tools /tmp/fake-skill
git add -A && git commit -m "feat: executable entry and PATH install"
```

---

### Task 11: 从 skills-manager 引导式迁移(交互,需用户确认)

**Files:**
- 无新代码;操作真实环境。**每个检查点必须停下来等用户确认。**

**Interfaces:**
- Consumes: 完整的 skm CLI
- Produces: 四个工具全部由 skm 接管;`~/.skills-manager` 与 GUI app 可安全移除。

**前置事实(迁移时重新核实,以当时实际为准):** 旧中央仓 `~/.skills-manager/skills/` 有 ~92 个 skill;四个工具目录里有 ~85 条软链指向它;Hermes 目录里还有若干**真实目录**(apple 等,skm 永不触碰);Codex 有一条链指向 `~/.cc-switch/skills/`(外部链,FOREIGN,不动)。

- [ ] **Step 1: 批量导入旧中央仓到 skm(只复制,不动旧链)**

```bash
for d in ~/.skills-manager/skills/*/; do
  skm install "$d"
done
skm doctor
ls ~/.skm/skills | wc -l    # 预期 ≈ 92
```

- [ ] **Step 2: 与用户共同定义 packs 与 scenarios(检查点:需用户输入)**

和用户确认场景划分(research/coding/design + base),然后:
```bash
# 三个已知集合从源头干净导入(拿到 source,便于 upgrade):
skm import https://github.com/obra/superpowers --name superpowers
skm import https://github.com/mattpocock/skills --name grill-me --split-by-dir
# figma 系列如用户需要:先逐个 install,再 pack create figma --skills ...
```
再按用户决定编辑 `~/.skm/config.toml` 写入 `[base]` 与 `[scenarios.*]`。

- [ ] **Step 3: 逐工具接管(每个工具一个检查点:先展示将删除的旧链清单,用户确认后执行)**

对每个工具(claude/codex/grok/hermes)重复:
```bash
TOOL_DIR=~/.claude/skills   # 逐工具替换
# 3a. 预览:哪些旧链会被删(仅指向 .skills-manager 的)
find "$TOOL_DIR" -maxdepth 1 -type l | while read -r l; do
  readlink "$l" | grep -q "/.skills-manager/skills/" && echo "将删除: $l"
done
# —— 用户确认后 ——
# 3b. 删除旧链
find "$TOOL_DIR" -maxdepth 1 -type l | while read -r l; do
  readlink "$l" | grep -q "/.skills-manager/skills/" && rm "$l"
done
# 3c. skm 接管
skm use claude <用户选的场景>
ls -la "$TOOL_DIR"
```

- [ ] **Step 4: 验证四个工具能加载 skill(检查点:用户各开一个新会话确认)**

用户在每个工具里开新会话,确认 skill 菜单正常出现。任何异常 → `skm rollback <tool>` + 恢复旧链(旧中央仓此时还在,重建软链即可恢复)。

- [ ] **Step 5: 确认无误后拆除旧系统(最终检查点:破坏性,必须用户明确同意)**

```bash
rm -rf ~/.skills-manager
# GUI app 由用户自行拖到废纸篓(/Applications/skills-manager.app 与 skills-manage.app)
skm doctor
```

- [ ] **Step 6: 收尾提交与记忆**

```bash
cd /Users/jerrycheng/LocalStorage/Vibecoding/skm
git add -A && git commit -m "docs: migration from skills-manager completed" --allow-empty
```
并更新 Claude 记忆(cross-tool 系列)记录 skm 的存在与用法。

---

## Self-Review 结果

1. **Spec 覆盖**:三层模型(T2 config)、按工具切换与 base 保留(T5)、rollback(T6)、拍平导入与 split-by-dir 选项 C(T7/T8)、全命令集含 doctor/upgrade/use all(T9)、中文 label 仅显示(T2/T9)、三重校验与永不误删(T4/T5 测试)、迁移顺序"先接管再验证后拆除"(T11)——逐条有task对应。✅
2. **占位扫描**:无 TBD/TODO;每步含完整代码与命令。✅
3. **类型一致性**:`Paths/Config/Pack/Scenario/ToolState/Report` 的字段与签名在各任务间已交叉核对(如 `install_local(name=...)` 在 T7 定义、T8 使用;`points_into_repo` 在 T4 定义、T9 doctor 使用)。✅
