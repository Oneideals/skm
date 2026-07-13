"""state.json 读写与切换前备份。links 是 skm 所建软链的唯一记录。"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .paths import Paths


@dataclass
class ToolState:
    groups: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


def load_state(paths: Paths) -> dict[str, ToolState]:
    if not paths.state.exists():
        return {}
    raw = json.loads(paths.state.read_text(encoding="utf-8"))
    return {
        tool: ToolState(groups=list(body.get("groups", [])),
                        links=list(body.get("links", [])))
        for tool, body in raw.get("tools", {}).items()
    }


def save_state(paths: Paths, state: dict[str, ToolState]) -> None:
    raw = {"tools": {t: {"groups": sorted(s.groups), "links": sorted(s.links)}
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
        json.dumps({"groups": sorted(ts.groups), "links": sorted(ts.links)},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def latest_backup(paths: Paths, tool: str) -> ToolState | None:
    if not paths.backups.exists():
        return None
    cands = sorted(paths.backups.glob(f"{tool}-*.json"))
    if not cands:
        return None
    raw = json.loads(cands[-1].read_text(encoding="utf-8"))
    return ToolState(groups=list(raw.get("groups", [])), links=list(raw.get("links", [])))
