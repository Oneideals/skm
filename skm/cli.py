"""skm 命令行入口。所有子命令都在这里分发。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import boundary, importer, linker, switcher
from . import panel as _panel
from .config import (ID_RE, Config, ConfigError, Pack, load_config,
                     missing_in_repo, save_config)
from .paths import Paths
from .state import load_state
from .switcher import Report, SwitchError


def _print_report(rep: Report) -> None:
    gl = ", ".join(rep.groups) if rep.groups else "(仅通用层+专用层)"
    print(f"{rep.tool} → 分组: {gl}")
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
    for b in rep.blocked:
        print(f"  ⚠ 撞名跳过(工具自带同名,建链会致其加载失败): {b}")
    print(f"  重启 {rep.tool} 会话后生效")


def _cmd_use(paths: Paths, cfg: Config, args) -> int:
    tools = sorted(cfg.tools) if args.tool == "all" else [args.tool]
    for t in tools:
        _print_report(switcher.use(paths, cfg, t, args.groups))
    return 0


def _cmd_enable(paths: Paths, cfg: Config, args) -> int:
    _print_report(switcher.enable(paths, cfg, args.tool, args.group))
    return 0


def _cmd_disable(paths: Paths, cfg: Config, args) -> int:
    _print_report(switcher.disable(paths, cfg, args.tool, args.group))
    return 0


def _cmd_reset(paths: Paths, cfg: Config, args) -> int:
    _print_report(switcher.use(paths, cfg, args.tool, []))
    return 0


def _cmd_rollback(paths: Paths, cfg: Config, args) -> int:
    _print_report(switcher.rollback(paths, cfg, args.tool))
    return 0


def _cmd_list(paths: Paths, cfg: Config, args) -> int:
    state = load_state(paths)
    uni = ", ".join(sorted(cfg.universal)) or "(空)"
    print(f"通用层({len(cfg.universal)}): {uni}")
    for tool in sorted(cfg.tools):
        tc = cfg.tools[tool]
        ts = state.get(tool)
        gl = ", ".join(ts.groups) if ts and ts.groups else "(无)"
        total = len(ts.links) if ts else 0
        managed = "" if ts else "  (未由 skm 管理)"
        print(f"{tool}: 专用 {len(tc.skills)} + 分组[{gl}] → 共 {total} 个 skill{managed}")
    return 0


def _cmd_groups(paths: Paths, cfg: Config, args) -> int:
    if not cfg.groups:
        print("(还没有分组,用 skm panel 或编辑 config.toml 的 [groups.*])")
    for name in sorted(cfg.groups):
        g = cfg.groups[name]
        zh = f"({g.label})" if g.label else ""
        n = len(g.skills) + sum(len(cfg.packs[p].skills)
                                for p in g.packs if p in cfg.packs)
        extra = f"  [packs: {', '.join(g.packs)}]" if g.packs else ""
        print(f"{name}{zh}: {n} 个 skill{extra}")
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
    referenced = set(cfg.universal)
    for t in cfg.tools.values():
        referenced |= set(t.skills)
    for p in cfg.packs.values():
        referenced |= set(p.skills)
    for g in cfg.groups.values():
        referenced |= set(g.skills)
    for m in missing_in_repo(paths, referenced):
        problems.append(f"config 引用的 skill 不在中央仓: {m}")
    if paths.skills.exists():
        for d in sorted(paths.skills.iterdir()):
            if d.is_dir() and not (d / "SKILL.md").exists():
                problems.append(f"中央仓目录缺 SKILL.md: {d.name}")
    state = load_state(paths)
    for tool, ts in sorted(state.items()):
        tc = cfg.tools.get(tool)
        if tc is None:
            problems.append(f"state 里有未知工具: {tool}")
            continue
        tool_dir = tc.path
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
    for tool, tc in sorted(cfg.tools.items()):
        tool_dir = tc.path
        if not tool_dir.exists():
            continue
        foreign = boundary.foreign_skill_names(paths, tool_dir)
        for entry in sorted(tool_dir.iterdir()):
            if not (entry.is_symlink() and linker.points_into_repo(paths, entry)):
                continue
            if boundary.skill_name(entry / "SKILL.md") in foreign:
                problems.append(
                    f"{tool}: 撞名(skm 链与工具自带同名,加载会失败): {entry.name}")
    return problems


def _cmd_doctor(paths: Paths, cfg: Config, args) -> int:
    problems = doctor(paths, cfg)
    if not problems:
        print("✓ 无问题")
        return 0
    for p in problems:
        print(f"✗ {p}")
    return 1


def _cmd_prune_collisions(paths: Paths, cfg: Config, args) -> int:
    rep = boundary.prune_collisions(paths, cfg, apply=args.apply)
    if not rep.removed:
        print("✓ 无撞名 skm 软链")
        return 0
    head = "已删除" if args.apply else "将删除(加 --apply 执行)"
    print(f"{head}撞名 skm 软链 {len(rep.removed)}: {', '.join(rep.removed)}")
    return 0


def _cmd_sync_boundary(paths: Paths, cfg: Config, args) -> int:
    rep = boundary.sync_boundary(paths, cfg, apply=args.apply)
    if not rep.purge:
        print("✓ 中央仓无工具自带的冗余副本,无需收敛")
        return 0
    head = "已收敛" if rep.applied else "将收敛(加 --apply 执行)"
    print(f"{head}:purge {len(rep.purge)} 个中央仓副本")
    print("  " + ", ".join(rep.purge))
    if rep.unlinked:
        print(f"  解链 {len(rep.unlinked)}: {', '.join(rep.unlinked)}")
    if rep.deref:
        print(f"  摘除引用 {len(rep.deref)}: {', '.join(rep.deref)}")
    if rep.applied:
        print("  已快照 state + config 到 ~/.skm/backups/(可手工恢复配置)")
        print("  注意:purge 的中央仓副本是工具自带的冗余份,已单向移除;需要时重新 skm import")
    return 0


def _cmd_panel(paths: Paths, cfg: Config, args) -> int:
    _panel.serve(paths, port=args.port, open_browser=not args.no_open)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="skm", description="跨工具 skill 管理器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("use", help="设定某工具启用的分组(all = 所有工具;不给分组=清空)")
    p.add_argument("tool")
    p.add_argument("groups", nargs="*")
    p.set_defaults(fn=_cmd_use)

    p = sub.add_parser("enable", help="给工具增开一个分组")
    p.add_argument("tool")
    p.add_argument("group")
    p.set_defaults(fn=_cmd_enable)

    p = sub.add_parser("disable", help="给工具关掉一个分组")
    p.add_argument("tool")
    p.add_argument("group")
    p.set_defaults(fn=_cmd_disable)

    p = sub.add_parser("reset", help="清空该工具所有分组(留通用层+专用层)")
    p.add_argument("tool")
    p.set_defaults(fn=_cmd_reset)

    p = sub.add_parser("rollback", help="回滚到上次切换前")
    p.add_argument("tool")
    p.set_defaults(fn=_cmd_rollback)

    sub.add_parser("list", help="各工具三层现状").set_defaults(fn=_cmd_list)
    sub.add_parser("groups", help="所有分组").set_defaults(fn=_cmd_groups)
    sub.add_parser("packs", help="所有集合").set_defaults(fn=_cmd_packs)

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

    p = sub.add_parser("prune-collisions", help="清掉与工具自带撞名的 skm 软链")
    p.add_argument("--apply", action="store_true", help="执行(默认仅预览)")
    p.set_defaults(fn=_cmd_prune_collisions)

    p = sub.add_parser("sync-boundary",
                       help="中央仓收敛:清掉其实是工具自带的冗余副本")
    p.add_argument("--apply", action="store_true", help="执行(默认仅预览)")
    p.set_defaults(fn=_cmd_sync_boundary)

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
