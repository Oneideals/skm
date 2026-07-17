"""GitHub 备份:~/.skm git 化,变更驱动 commit + push;restore 恢复并重算软链。"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .paths import Paths

_GITIGNORE = "backups/\ncache-upstream.json\npush.log\n"
_dirty = False


class BackupError(Exception):
    pass


def mark_dirty() -> None:
    global _dirty
    _dirty = True


def _git(paths: Paths, *args, check=True):
    return subprocess.run(["git", "-C", str(paths.home), *args],
                          capture_output=True, text=True, check=check)


def _ready(paths: Paths) -> bool:
    if not (paths.home / ".git").exists():
        return False
    return _git(paths, "remote", "get-url", "origin", check=False).returncode == 0


def _commit(paths: Paths, message: str) -> None:
    _git(paths, "add", "-A")
    _git(paths, "-c", "user.email=skm@local", "-c", "user.name=skm",
         "commit", "-qm", message, check=False)   # 无实际变化时容忍失败


def init_repo(paths: Paths, url: str) -> None:
    paths.ensure()
    if not (paths.home / ".git").exists():
        r = subprocess.run(["git", "init", "-q", str(paths.home)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise BackupError(f"git init 失败: {r.stderr.strip()}")
    (paths.home / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    if _git(paths, "remote", "get-url", "origin", check=False).returncode == 0:
        _git(paths, "remote", "set-url", "origin", url)
    else:
        _git(paths, "remote", "add", "origin", url)
    _commit(paths, "skm backup init")
    _git(paths, "branch", "-M", "main")
    push = _git(paths, "push", "-u", "origin", "main", check=False)
    if push.returncode != 0:
        raise BackupError(f"首推失败: {push.stderr.strip()[:300]}")


def autosync(paths: Paths, message: str, wait: bool = False) -> None:
    """变更后自动备份:未 init 静默跳过;push 默认后台、失败不打扰。"""
    global _dirty
    if not _dirty or not _ready(paths):
        return
    _dirty = False
    _commit(paths, f"skm: {message}")
    if wait:
        _git(paths, "push", "origin", "main", check=False)
    else:
        log = open(paths.home / "push.log", "ab")
        subprocess.Popen(["git", "-C", str(paths.home), "push", "origin", "main"],
                         stdout=log, stderr=log)


def backup_now(paths: Paths) -> str:
    if not _ready(paths):
        return "未启用备份:先 skm backup init <git-url>"
    _commit(paths, f"skm: manual backup {time.strftime('%F %T')}")
    push = _git(paths, "push", "origin", "main", check=False)
    if push.returncode != 0:
        return f"⚠ push 失败(本地已 commit,稍后重试): {push.stderr.strip()[:200]}"
    url = _git(paths, "remote", "get-url", "origin").stdout.strip()
    return f"✓ 已推送到 {url}"


def restore(paths: Paths, url: str, force: bool = False) -> dict:
    safety = None
    if paths.home.exists() and any(paths.home.iterdir()):
        if not force:
            raise BackupError(f"{paths.home} 已存在且非空;加 --force 覆盖"
                              "(现状会先移到临时快照)")
        safety = Path(tempfile.mkdtemp(prefix="skm-restore-safety-"))
        for child in list(paths.home.iterdir()):
            shutil.move(str(child), str(safety / child.name))
    paths.home.mkdir(parents=True, exist_ok=True)
    clone = subprocess.run(["git", "clone", "-q", url, str(paths.home)],
                           capture_output=True, text=True)
    if clone.returncode != 0:
        raise BackupError(f"clone 失败: {clone.stderr.strip()[:300]}")

    from . import switcher                       # 延迟导入避免环
    from .config import load_config
    from .state import load_state
    cfg = load_config(paths)
    state = load_state(paths)
    tools: list[str] = []
    skipped: list[str] = []
    for tool, ts in sorted(state.items()):
        tc = cfg.tools.get(tool)
        if tc is None or not tc.path.parent.exists():
            skipped.append(tool)
            continue
        switcher.use(paths, cfg, tool, ts.groups)
        tools.append(tool)
    return {"tools": tools, "skipped": skipped,
            "safety": str(safety) if safety else None}
