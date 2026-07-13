"""跨工具边界:识别工具自带(外来)skill 名、检测撞名、中央仓收敛。

中央仓只放 skm 自有 skill;工具自带的归工具自己管。判定"外来" =
扫工具 skills 目录下、顶层不是"指向中央仓的软链"的 SKILL.md 的 name。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import linker
from .config import Config
from .paths import Paths
from .state import load_state, save_state

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
