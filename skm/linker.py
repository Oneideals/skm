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
