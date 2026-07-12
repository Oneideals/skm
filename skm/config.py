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
