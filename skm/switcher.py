"""场景切换核心:use(设定分组集)、enable/disable(增删单个分组)、rollback。

某工具最终 skill = universal ∪ tool.skills ∪ ⋃(勾选的 groups),软链增删见 _apply。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import boundary, linker
from .config import Config, missing_in_repo, resolve_for_tool
from .paths import Paths
from .state import ToolState, backup, latest_backup, load_state, save_state


class SwitchError(Exception):
    pass


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


def use(paths: Paths, cfg: Config, tool: str, groups: list[str]) -> Report:
    """把某工具的启用分组设为 groups(覆盖)。groups=[] 即只留通用+专用层。"""
    if tool not in cfg.tools:
        raise SwitchError(f"未知工具 '{tool}'。可用: {', '.join(sorted(cfg.tools))}")
    unknown = [g for g in groups if g not in cfg.groups]
    if unknown:
        known = ", ".join(sorted(cfg.groups)) or "(无)"
        raise SwitchError(f"分组不存在: {', '.join(unknown)}。可用: {known}")
    target = resolve_for_tool(cfg, tool, groups)
    missing = missing_in_repo(paths, target)
    if missing:
        raise SwitchError(
            "中央仓缺少以下 skill,请先 skm install/import: " + ", ".join(missing))
    state = load_state(paths)
    return _apply(paths, cfg, state, tool, list(groups), target)


def enable(paths: Paths, cfg: Config, tool: str, group: str) -> Report:
    """给某工具增开一个分组(叠加到已勾选的)。"""
    state = load_state(paths)
    cur = state.get(tool, ToolState()).groups
    return use(paths, cfg, tool, sorted(set(cur) | {group}))


def disable(paths: Paths, cfg: Config, tool: str, group: str) -> Report:
    """给某工具关掉一个分组。"""
    state = load_state(paths)
    cur = state.get(tool, ToolState()).groups
    return use(paths, cfg, tool, sorted(set(cur) - {group}))


def rollback(paths: Paths, cfg: Config, tool: str) -> Report:
    if tool not in cfg.tools:
        raise SwitchError(f"未知工具 '{tool}'。可用: {', '.join(sorted(cfg.tools))}")
    snap = latest_backup(paths, tool)   # 必须在 _apply 写新备份之前读
    if snap is None:
        raise SwitchError(f"'{tool}' 没有可回滚的备份")
    target = resolve_for_tool(cfg, tool, snap.groups)
    state = load_state(paths)
    return _apply(paths, cfg, state, tool, snap.groups, target)
