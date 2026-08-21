# 🚀 Project Progress & Agent Handover — skm

> **Last Updated:** 2026-08-21T14:55:29Z (read-only projection)
> **Git State:** `dirty` | **Branch:** `main` | **Events Count:** 16

---

## 🎯 Recent Milestones & Completed Tasks ([DONE])

- [DONE] `ci-restore-clone` — CI 红:restore 对 HEAD≠main 的远端空检出;e553a55 热修(clone -b main 优先+回退+fixture 复现),已推 main
- [DONE] `skm-protocol-commit` — Committed protocol migration on main
- [DONE] (claude, 2026-08-21) upgrade_source 完成后调用新增的 upstream.record_head(paths, url, rep.commit) 把刚克隆到的 head 写进缓存;顺带把 cached_head 里的写盘逻辑抽成 _save_cache 复用。修的是:升级后 config 记新 commit 而 cache-upstream.json 停在旧值,24h TTL 内 outdated 拿旧缓存比新 config,假报落后(2026-08-21 在 mattpocock 上实际踩到)。TDD:先加 test_upgrade_refreshes_cache 复现失败(断言 remote==head2 报旧 hash),实现后转绿。全量 104 测试通过(原 103)。生产路径端到端验证:skm upgrade karpathy 后缓存 checked_at 由 1563 秒前归零、head 与 config commit 一致。未提交,留给用户决定。
- [DONE] (claude, 2026-07-17) skill 二期完成并合入 main(dbbf17f,14 提交,103 测试):上游更新检测(Pack溯源/upstream.py缓存检查/outdated/doctor提示/面板一键更新/upgrade_source修串包+存量split推断bug)+GitHub备份(backup.py变更驱动autosync/restore重链,私有仓Oneideals/skm-backup已建并首推)。运维:ponytail/karpathy收编pack,matt5包入轨,superpowers全套14导入,血统规则加溯源豁免。45→58 skill全部归8个pack,doctor绿,CI待确认
- [DONE] (hermes, 2026-07-17) Committed AGENTS.md CLAUDE.md .gitignore for Agent Baton protocol migration
- [DONE] (hermes, 2026-07-17) Replaced skm AGENTS.md/CLAUDE.md with baton protocol; gitignore now ignores .agent-baton/; archived 6 legacy v1 markdown logs under .agent-baton/archive/legacy-v1-md/

## 📋 Open Issues & Backlog ([TODO])

_No open issues._

## 🔄 Active Leases & In-Progress Work

_No active leases._

## 📝 Working Tree Changes

- `.M` `PROGRESS.md`
- `.M` `skm/importer.py`
- `.M` `skm/upstream.py`
- `.M` `tests/test_upstream.py`

## 💡 Handoff Instructions for Next Agent

1. Before making changes, register your task: `baton start --project . --tool <tool-name> --summary "<task-description>"`
2. Review the `[TODO]` items above and implement the required features/fixes.
3. Upon completion, close the lease and sync to GitHub: `baton finish --project . --tool <tool-name> --session <id> --summary "<what-was-done>" --push`

