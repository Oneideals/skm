"""config.toml 的读取、校验、写回与 skill 集解析。

三层模型:某工具最终启用的 skill =
    universal(通用,所有工具共享)
  ∪ tools[tool].skills(该工具专用,常驻)
  ∪ ⋃(该工具勾选的各 group 的 skills + 其 packs 展开)
"""
from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .paths import Paths

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

DEFAULT_TOOL_PATHS = {
    "claude": "~/.claude/skills",
    "codex": "~/.codex/skills",
    "grok": "~/.grok/skills",
    "hermes": "~/.hermes/skills",
}


class ConfigError(Exception):
    pass


@dataclass
class ToolCfg:
    path: Path
    skills: list[str] = field(default_factory=list)   # 工具专用常驻层
    owned_sources: list[Path] = field(default_factory=list)  # 工具所有权来源:清单文件/出厂树


@dataclass
class Pack:
    skills: list[str] = field(default_factory=list)
    source: str | None = None
    commit: str | None = None    # 安装时上游 HEAD hash(更新检测锚点)
    base: str | None = None      # import 时的 --name base(升级复现用)
    split: bool = False          # import 时是否 --split-by-dir


@dataclass
class Group:
    skills: list[str] = field(default_factory=list)
    packs: list[str] = field(default_factory=list)
    label: str | None = None


@dataclass
class Config:
    universal: list[str]
    tools: dict[str, ToolCfg]
    packs: dict[str, Pack]
    groups: dict[str, Group]


def _check_id(kind: str, name: str) -> None:
    if not ID_RE.match(name):
        raise ConfigError(f"{kind} 名 '{name}' 不合法:只允许小写字母/数字/短横线")


def default_config() -> Config:
    return Config(
        universal=[],
        tools={k: ToolCfg(path=Path(v).expanduser())
               for k, v in DEFAULT_TOOL_PATHS.items()},
        packs={}, groups={},
    )


def load_config(paths: Paths) -> Config:
    if not paths.config.exists():
        cfg = default_config()
        paths.ensure()
        save_config(paths, cfg)
        return cfg
    raw = tomllib.loads(paths.config.read_text(encoding="utf-8"))
    universal = list(raw.get("universal", {}).get("skills", []))
    tools: dict[str, ToolCfg] = {}
    for name, body in raw.get("tools", {}).items():
        if isinstance(body, str):          # 容错:旧式 tool = "路径"
            tools[name] = ToolCfg(path=Path(body).expanduser())
        else:
            tools[name] = ToolCfg(
                path=Path(str(body["path"])).expanduser(),
                skills=list(body.get("skills", [])),
                owned_sources=[Path(str(p)).expanduser()
                               for p in body.get("owned_sources", [])])
    packs: dict[str, Pack] = {}
    for name, body in raw.get("packs", {}).items():
        _check_id("pack", name)
        packs[name] = Pack(skills=list(body.get("skills", [])),
                           source=body.get("source"),
                           commit=body.get("commit"),
                           base=body.get("base"),
                           split=bool(body.get("split", False)))
    groups: dict[str, Group] = {}
    for name, body in raw.get("groups", {}).items():
        _check_id("group", name)
        groups[name] = Group(skills=list(body.get("skills", [])),
                             packs=list(body.get("packs", [])),
                             label=body.get("label"))
    cfg = Config(universal=universal, tools=tools, packs=packs, groups=groups)
    _validate_refs(cfg)
    return cfg


def _validate_refs(cfg: Config) -> None:
    for gname, g in cfg.groups.items():
        missing = [p for p in g.packs if p not in cfg.packs]
        if missing:
            raise ConfigError(f"分组 '{gname}' 引用了不存在的 pack: {', '.join(missing)}")


def _toml_str(v: str) -> str:
    return json.dumps(v, ensure_ascii=False)


def _toml_list(items: list[str]) -> str:
    return "[" + ", ".join(_toml_str(i) for i in items) + "]"


def save_config(paths: Paths, cfg: Config) -> None:
    lines: list[str] = ["[universal]", f"skills = {_toml_list(sorted(cfg.universal))}"]
    for name in sorted(cfg.tools):
        t = cfg.tools[name]
        lines += ["", f"[tools.{name}]", f"path = {_toml_str(str(t.path))}",
                  f"skills = {_toml_list(sorted(t.skills))}"]
        if t.owned_sources:
            lines.append(
                f"owned_sources = {_toml_list(sorted(str(p) for p in t.owned_sources))}")
    for name in sorted(cfg.packs):
        p = cfg.packs[name]
        lines += ["", f"[packs.{name}]", f"skills = {_toml_list(sorted(p.skills))}"]
        if p.source:
            lines.append(f"source = {_toml_str(p.source)}")
        if p.commit:
            lines.append(f"commit = {_toml_str(p.commit)}")
        if p.base:
            lines.append(f"base = {_toml_str(p.base)}")
        if p.split:
            lines.append("split = true")
    for name in sorted(cfg.groups):
        g = cfg.groups[name]
        lines += ["", f"[groups.{name}]"]
        if g.label:
            lines.append(f"label = {_toml_str(g.label)}")
        lines.append(f"packs = {_toml_list(sorted(g.packs))}")
        lines.append(f"skills = {_toml_list(sorted(g.skills))}")
    paths.config.parent.mkdir(parents=True, exist_ok=True)
    paths.config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    from . import backup
    backup.mark_dirty()


def resolve_for_tool(cfg: Config, tool: str, groups: list[str]) -> set[str]:
    """某工具在勾选了 groups 时最终启用的 skill 集(三层并集,去重)。"""
    if tool not in cfg.tools:
        raise ConfigError(f"未知工具 '{tool}'。可用: {', '.join(sorted(cfg.tools))}")
    result = set(cfg.universal)
    result.update(cfg.tools[tool].skills)
    for g in groups:
        if g not in cfg.groups:
            known = ", ".join(sorted(cfg.groups)) or "(无)"
            raise ConfigError(f"分组 '{g}' 不存在。可用: {known}")
        grp = cfg.groups[g]
        result.update(grp.skills)
        for p in grp.packs:
            result.update(cfg.packs[p].skills)
    return result


def missing_in_repo(paths: Paths, skills: set[str]) -> list[str]:
    return sorted(s for s in skills if not (paths.skills / s / "SKILL.md").exists())
