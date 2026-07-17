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
    commit: str | None = None
    dropped: list[str] = field(default_factory=list)   # 升级时从 pack 摘除的


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
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone_dir,
                              capture_output=True, text=True).stdout.strip()
        rep.commit = head or None
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
        cfg.packs[pname] = Pack(skills=merged, source=url, commit=rep.commit,
                                base=base, split=split_by_dir)
    save_config(paths, cfg)
    return rep


def upgrade_source(paths: Paths, cfg: Config, url: str) -> ImportReport:
    """按 source 仓升级:一次克隆刷新该 url 的全部 pack(fresh 名单,split 安全)。"""
    group = {n: p for n, p in cfg.packs.items() if p.source == url}
    if not group:
        raise ImporterError(f"没有 source 为 {url} 的 pack")
    anchor = next((p for p in group.values() if p.base), None)
    base = anchor.base if anchor else sorted(group)[0]
    split = anchor.split if anchor else False
    old_lists = {n: list(p.skills) for n, p in group.items()}

    rep = import_repo(paths, cfg, url, name=base, split_by_dir=split, force=True)

    # fresh 名单:覆盖 import_repo 的 old∪new 合并;上游消失的从 pack 摘除
    for pname, old in old_lists.items():
        fresh = rep.packs.get(pname, [])
        cfg.packs[pname] = Pack(skills=sorted(fresh), source=url,
                                commit=rep.commit, base=base, split=split)
        rep.dropped += [f"{pname}/{s}" for s in sorted(set(old) - set(fresh))]
    save_config(paths, cfg)
    return rep


def upgrade(paths: Paths, cfg: Config, pack_name: str) -> ImportReport:
    p = cfg.packs.get(pack_name)
    if p is None or not p.source:
        raise ImporterError(f"pack '{pack_name}' 不存在或没有 source,无法升级")
    return upgrade_source(paths, cfg, p.source)
