"""配置面板:SKILL.md 描述解析、状态构建、保存校验。HTTP 服务见文件末尾。"""
from __future__ import annotations

import re
from pathlib import Path

from .config import (ID_RE, Config, Scenario, missing_in_repo, save_config)
from .paths import Paths
from .state import load_state

_KEY_RE = re.compile(r"^[A-Za-z_][\w-]*:")
_BLOCK_INDICATORS = {">", "|", ">-", "|-", ">+", "|+"}


class PanelError(Exception):
    pass


def skill_description(skill_dir: Path) -> str:
    """从 SKILL.md frontmatter 取 description(支持内联引号与 >/| 块标量)。"""
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return ""
    lines = md.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    fm: list[str] = []
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        fm.append(ln)
    for i, ln in enumerate(fm):
        if not ln.startswith("description:"):
            continue
        value = ln[len("description:"):].strip()
        if value and value not in _BLOCK_INDICATORS:
            return _clean(value)
        # 块标量:收集后续更缩进的行,直到下一个顶层 key
        collected: list[str] = []
        for cont in fm[i + 1:]:
            if _KEY_RE.match(cont):
                break
            if cont.strip():
                collected.append(cont.strip())
        return _clean(" ".join(collected))
    return ""


def _clean(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        text = text[1:-1]
    return re.sub(r"\s+", " ", text).strip()


def build_state(paths: Paths, cfg: Config) -> dict:
    skills = []
    if paths.skills.exists():
        for d in sorted(paths.skills.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists():
                skills.append({"name": d.name, "description": skill_description(d)})
    state = load_state(paths)
    return {
        "skills": skills,
        "base": sorted(cfg.base),
        "packs": {n: sorted(p.skills) for n, p in sorted(cfg.packs.items())},
        "scenarios": {
            n: {"label": s.label, "packs": sorted(s.packs), "skills": sorted(s.skills)}
            for n, s in sorted(cfg.scenarios.items())
        },
        "tools": {t: (state[t].scenario if t in state else None)
                  for t in sorted(cfg.tools)},
    }


def apply_payload(paths: Paths, cfg: Config, payload: dict) -> None:
    """把面板提交的 base+scenarios 校验后写回 config。packs/tools 不动。"""
    base = list(payload.get("base", []))
    scenarios_in = payload.get("scenarios", {})
    referenced = set(base)
    new_scenarios: dict[str, Scenario] = {}
    for name, body in scenarios_in.items():
        if not ID_RE.match(name):
            raise PanelError(f"场景名 '{name}' 不合法:只允许小写字母/数字/短横线")
        packs = list(body.get("packs", []))
        skills = list(body.get("skills", []))
        for p in packs:
            if p not in cfg.packs:
                raise PanelError(f"场景 '{name}' 引用了不存在的 pack: {p}")
        referenced.update(skills)
        new_scenarios[name] = Scenario(packs=packs, skills=skills,
                                       label=body.get("label") or None)
    missing = missing_in_repo(paths, referenced)
    if missing:
        raise PanelError("以下 skill 不在中央仓: " + ", ".join(missing))
    cfg.base = base
    cfg.scenarios = new_scenarios
    save_config(paths, cfg)
