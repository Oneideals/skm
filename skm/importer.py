"""导入:skill 目录发现、本地安装、git 仓库拍平导入与 pack 注册。"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import upstream
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
    dropped: list[str] = field(default_factory=list)    # 升级时从 pack 摘除的
    duplicates: list[str] = field(default_factory=list)  # 拍平后同名被折叠的 skill 名
    unmatched: list[str] = field(default_factory=list)   # 升级时 base 对不上的存量 pack


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


def _common_word_prefix(names: list[str]) -> str:
    """按 '-' 词边界取公共前缀,用于无 base 记录的存量多 pack 推断 base。

    os.path.commonprefix 是字符级:'coding-skills'/'coding-style' 会被截成
    'coding-s'(词中间截断),据此重建的 pack 名与原 pack 名对不上。按整词切
    分可得到干净的 'coding'。无整词公共前缀时回退到字典序首个 pack 名。
    """
    if len(names) == 1:
        return names[0]
    parts = [n.split("-") for n in sorted(names)]
    common: list[str] = []
    for segs in zip(*parts):
        if all(s == segs[0] for s in segs):
            common.append(segs[0])
        else:
            break
    return "-".join(common) if common else sorted(names)[0]


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
        seen: set[str] = set()
        for d in dirs:
            skill_name = base if d == root else d.name
            # 拍平导入按 basename 落目录;不同路径下的同名 skill 会静默折叠成
            # 一份(后一个被 skipped)。显式记录,避免"看起来装了其实丢了一个"。
            if skill_name in seen and skill_name not in rep.duplicates:
                rep.duplicates.append(skill_name)
            seen.add(skill_name)
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
    inferred = False
    if anchor:
        base, split = anchor.base, anchor.split
    elif len(group) == 1:
        base, split = next(iter(group)), False        # 整仓单 pack 导入的存量
    else:
        # 存量多 pack 同源(二期前的 --split-by-dir 产物):推断为 split,
        # base = pack 名的整词公共前缀(matt-engineering/matt-misc… → matt)。
        # 用字符级 commonprefix 会把 coding-skills/coding-style 截成 coding-s,
        # 导致下面 pack 名对不上、名单被静默清空,故改按 '-' 词边界切分。
        base, split = _common_word_prefix(sorted(group)), True
        inferred = True
    old_lists = {n: list(p.skills) for n, p in group.items()}

    rep = import_repo(paths, cfg, url, name=base, split_by_dir=split, force=True)

    # fresh 名单:覆盖 import_repo 的 old∪new 合并;上游消失的从 pack 摘除。
    # 只有在 base 是"推断"出来的不确定路径上,rep.packs 缺 key 才可能是推断
    # 错位(会把用户原名单静默清空)——此时保留原样并告警。base 明确时(anchor/
    # 单 pack),缺 key 就是合法的"上游删空",必须清空,不能当作推断失败。
    for pname, old in old_lists.items():
        if pname not in rep.packs:
            if inferred:
                rep.unmatched.append(pname)
                continue
            fresh = []
        else:
            fresh = rep.packs[pname]
        cfg.packs[pname] = Pack(skills=sorted(fresh), source=url,
                                commit=rep.commit, base=base, split=split)
        rep.dropped += [f"{pname}/{s}" for s in sorted(set(old) - set(fresh))]
    save_config(paths, cfg)
    # 刚克隆到的就是当下的远端 head,记进缓存;否则 24h TTL 内 outdated 会拿
    # 旧缓存跟刚写的新 commit 比,假报一个并不存在的落后。
    upstream.record_head(paths, url, rep.commit)
    return rep


def upgrade(paths: Paths, cfg: Config, pack_name: str) -> ImportReport:
    p = cfg.packs.get(pack_name)
    if p is None or not p.source:
        raise ImporterError(f"pack '{pack_name}' 不存在或没有 source,无法升级")
    return upgrade_source(paths, cfg, p.source)
