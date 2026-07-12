"""skm 命令行入口。所有子命令都在这里分发。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import importer, linker, switcher
from . import panel as _panel
from .config import (ID_RE, Config, ConfigError, Pack, load_config,
                     missing_in_repo, save_config)
from .paths import Paths
from .state import load_state
from .switcher import Report, SwitchError


def _print_report(rep: Report) -> None:
    label = rep.scenario if rep.scenario is not None else "(仅 base)"
    print(f"{rep.tool} → {label}")
    if rep.created:
        print(f"  新增 {len(rep.created)}: {', '.join(rep.created)}")
    if rep.removed:
        print(f"  移除 {len(rep.removed)}: {', '.join(rep.removed)}")
    if rep.kept:
        print(f"  保留 {len(rep.kept)}: {', '.join(rep.kept)}")
    for c in rep.conflicts:
        print(f"  ⚠ 冲突未动: {c}")
    for s in rep.skipped:
        print(f"  ⚠ 跳过删除: {s}")
    print(f"  重启 {rep.tool} 会话后生效")


def _cmd_use(paths: Paths, cfg: Config, args) -> int:
    tools = sorted(cfg.tools) if args.tool == "all" else [args.tool]
    for t in tools:
        _print_report(switcher.use(paths, cfg, t, args.scenario))
    return 0


def _cmd_reset(paths: Paths, cfg: Config, args) -> int:
    _print_report(switcher.use(paths, cfg, args.tool, None))
    return 0


def _cmd_rollback(paths: Paths, cfg: Config, args) -> int:
    _print_report(switcher.rollback(paths, cfg, args.tool))
    return 0


def _cmd_list(paths: Paths, cfg: Config, args) -> int:
    state = load_state(paths)
    for tool in sorted(cfg.tools):
        ts = state.get(tool)
        if ts is None:
            print(f"{tool}: (未由 skm 管理)")
            continue
        label = "(仅 base)"
        if ts.scenario:
            sc = cfg.scenarios.get(ts.scenario)
            zh = f"({sc.label})" if sc and sc.label else ""
            label = f"{ts.scenario}{zh}"
        print(f"{tool}: {label} — {len(ts.links)} 个 skill")
        if ts.links:
            print(f"  {', '.join(ts.links)}")
    return 0


def _cmd_packs(paths: Paths, cfg: Config, args) -> int:
    if not cfg.packs:
        print("(还没有 pack,用 skm import 或 skm pack create)")
    for name in sorted(cfg.packs):
        p = cfg.packs[name]
        src = f"  [{p.source}]" if p.source else ""
        print(f"{name} ({len(p.skills)}){src}")
        print(f"  {', '.join(p.skills)}")
    return 0


def _cmd_scenarios(paths: Paths, cfg: Config, args) -> int:
    if not cfg.scenarios:
        print("(还没有场景,直接编辑 config.toml 的 [scenarios.*])")
    for name in sorted(cfg.scenarios):
        s = cfg.scenarios[name]
        zh = f"({s.label})" if s.label else ""
        print(f"{name}{zh}: packs = {', '.join(s.packs) or '(空)'}")
    return 0


def _cmd_install(paths: Paths, cfg: Config, args) -> int:
    status = importer.install_local(
        paths, Path(args.path), name=args.name, force=args.force)
    print(f"{args.path}: {status}")
    return 0


def _cmd_import(paths: Paths, cfg: Config, args) -> int:
    if args.name and not ID_RE.match(args.name):
        print(f"pack 名 '{args.name}' 不合法(小写字母/数字/短横线)", file=sys.stderr)
        return 1
    rep = importer.import_repo(paths, cfg, args.url, name=args.name,
                               split_by_dir=args.split_by_dir, force=args.force)
    print(f"安装 {len(rep.installed)},跳过(已存在) {len(rep.skipped)}")
    for pname, skills in sorted(rep.packs.items()):
        print(f"pack {pname}: {', '.join(skills)}")
    return 0


def _cmd_pack_create(paths: Paths, cfg: Config, args) -> int:
    if not ID_RE.match(args.pack_name):
        print(f"pack 名 '{args.pack_name}' 不合法(小写字母/数字/短横线)",
              file=sys.stderr)
        return 1
    skills = [s.strip() for s in args.skills.split(",") if s.strip()]
    missing = missing_in_repo(paths, set(skills))
    if missing:
        print(f"⚠ 以下 skill 不在中央仓(仍会登记): {', '.join(missing)}")
    cfg.packs[args.pack_name] = Pack(skills=sorted(set(skills)))
    save_config(paths, cfg)
    print(f"pack {args.pack_name}: {len(skills)} 个 skill 已登记")
    return 0


def _cmd_upgrade(paths: Paths, cfg: Config, args) -> int:
    rep = importer.upgrade(paths, cfg, args.pack)
    print(f"pack {args.pack} 已升级:更新 {len(rep.installed)} 个 skill")
    return 0


def doctor(paths: Paths, cfg: Config) -> list[str]:
    problems: list[str] = []
    referenced = set(cfg.base)
    for p in cfg.packs.values():
        referenced |= set(p.skills)
    for m in missing_in_repo(paths, referenced):
        problems.append(f"config 引用的 skill 不在中央仓: {m}")
    if paths.skills.exists():
        for d in sorted(paths.skills.iterdir()):
            if d.is_dir() and not (d / "SKILL.md").exists():
                problems.append(f"中央仓目录缺 SKILL.md: {d.name}")
    state = load_state(paths)
    for tool, ts in sorted(state.items()):
        tool_dir = cfg.tools.get(tool)
        if tool_dir is None:
            problems.append(f"state 里有未知工具: {tool}")
            continue
        for skill in ts.links:
            link = tool_dir / skill
            if not link.is_symlink():
                problems.append(f"{tool}: state 记录的链不存在或非软链: {skill}")
            elif not (paths.skills / skill / "SKILL.md").exists():
                problems.append(f"{tool}: 断链(中央仓已无此 skill): {skill}")
        if tool_dir.exists():
            recorded = set(ts.links)
            for entry in sorted(tool_dir.iterdir()):
                if (entry.is_symlink() and linker.points_into_repo(paths, entry)
                        and entry.name not in recorded):
                    problems.append(f"{tool}: 孤儿 skm 软链(不在 state): {entry.name}")
    return problems


def _cmd_doctor(paths: Paths, cfg: Config, args) -> int:
    problems = doctor(paths, cfg)
    if not problems:
        print("✓ 无问题")
        return 0
    for p in problems:
        print(f"✗ {p}")
    return 1


def _cmd_panel(paths: Paths, cfg: Config, args) -> int:
    _panel.serve(paths, port=args.port, open_browser=not args.no_open)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="skm", description="跨工具 skill 管理器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("use", help="切工具到场景(all = 所有工具)")
    p.add_argument("tool")
    p.add_argument("scenario")
    p.set_defaults(fn=_cmd_use)

    p = sub.add_parser("reset", help="清到仅 base")
    p.add_argument("tool")
    p.set_defaults(fn=_cmd_reset)

    p = sub.add_parser("rollback", help="回滚到上次切换前")
    p.add_argument("tool")
    p.set_defaults(fn=_cmd_rollback)

    sub.add_parser("list", help="各工具当前场景").set_defaults(fn=_cmd_list)
    sub.add_parser("packs", help="所有集合").set_defaults(fn=_cmd_packs)
    sub.add_parser("scenarios", help="所有场景").set_defaults(fn=_cmd_scenarios)

    p = sub.add_parser("install", help="装单个本地 skill 进中央仓")
    p.add_argument("path")
    p.add_argument("--name")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=_cmd_install)

    p = sub.add_parser("import", help="导入 git 仓库为 pack")
    p.add_argument("url")
    p.add_argument("--name")
    p.add_argument("--split-by-dir", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=_cmd_import)

    p = sub.add_parser("pack", help="pack 管理")
    psub = p.add_subparsers(dest="pack_cmd", required=True)
    pc = psub.add_parser("create", help="手挑集合")
    pc.add_argument("pack_name")
    pc.add_argument("--skills", required=True, help="逗号分隔")
    pc.set_defaults(fn=_cmd_pack_create)

    p = sub.add_parser("upgrade", help="按 source 升级 pack")
    p.add_argument("pack")
    p.set_defaults(fn=_cmd_upgrade)

    sub.add_parser("doctor", help="健康检查").set_defaults(fn=_cmd_doctor)

    p = sub.add_parser("panel", help="打开可视化配置面板")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    p.set_defaults(fn=_cmd_panel)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    paths = Paths.from_env()
    try:
        cfg = load_config(paths)
        return args.fn(paths, cfg, args)
    except (ConfigError, SwitchError, importer.ImporterError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
