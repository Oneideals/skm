"""场景切换核心:use(含 reset)与 rollback。"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import linker
from .config import Config, missing_in_repo, resolve_skills
from .paths import Paths
from .state import ToolState, backup, latest_backup, load_state, save_state


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


def rollback(paths: Paths, cfg: Config, tool: str) -> Report:
    if tool not in cfg.tools:
        raise SwitchError(f"未知工具 '{tool}'。可用: {', '.join(sorted(cfg.tools))}")
    snap = latest_backup(paths, tool)   # 必须在 _apply 写新备份之前读
    if snap is None:
        raise SwitchError(f"'{tool}' 没有可回滚的备份")
    state = load_state(paths)
    return _apply(paths, cfg, state, tool, snap.scenario, set(snap.links))
