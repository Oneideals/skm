# skm 跨工具边界与重名守卫 — 设计

- 日期:2026-07-14
- 状态:待评审
- 关联:`docs/skm-design.md`(三层模型)、`skm/linker.py`、`skm/switcher.py`、`skm/importer.py`

## 1. 背景

skm 通过"从各工具的 `skills/` 目录软链到中央仓 `~/.skm/skills/`"分发 skill。但每个工具可能**自带**一批 skill,放在同一个 `skills/` 目录里 —— Hermes 就是如此:按类别嵌套,如 `~/.hermes/skills/software-development/plan/`。

工具在会话启动时扫描整个 `skills/` 构建名册。以 Hermes 为例(已核对源码 `tools/skills_tool.py`):

- **名册去重**:按 frontmatter `name` 去重;`os.walk(..., followlinks=True)` 收集后 `sorted()`,**完整路径字母序在前者胜出**。
- **加载**:`skill_view(name)` 重新扫描,按解析后真实路径收集全部同名候选;**一旦 >1 个即拒绝** —— 返回 `Ambiguous skill name 'X' … Refusing to guess — load one explicitly by its categorized path.`

即:**同名不是"覆盖",而是"冲突即失效"** —— 名册可能显示一个、而 agent 加载时报错。skm 把工具自带 skill 的副本软链回该工具目录,就会与自带真身撞名。

**现状已有 7 个活冲突**(`~/.hermes/skills/` 实测):`hermes-agent`、`hermes-agent-skill-authoring`、`kanban-orchestrator`、`kanban-worker`、`petdex`、`plan`、`teams-meeting-pipeline` —— 每个都「Hermes 自带嵌套副本 + skm 平铺软链」并存,现按裸名均无法加载。

## 2. 目标 / 非目标

**目标**

- 确立边界:中央仓只放 skm 自己装的 skill;工具自带的归工具自己管。
- 防新撞车:skm 建链前做跨工具重名守卫(撞名跳过 + 告警)。
- 清旧账:`doctor` 检测重名;清掉现有撞名软链;把中央仓收敛为"只剩 skm 自有"。

**非目标**

- 不替工具管理其自带 skill(绝不改工具目录里的自带真身)。
- 不自动为被掏空的分组从上游重装 skill(见 §10,留作用户后续动作)。

## 3. 边界原则

- `~/.skm/skills/` = **仅 skm 自有**(用户经 `skm install` / `skm import` 主动装的)。
- 工具自带 skill 不进中央仓、不被 skm 管理。
- 判定"某名是否属于某工具自带" = 扫该工具 `skills/` 目录下**非 skm 建**的 SKILL.md 的 `name`(**决策 X=①**:工具无关、不依赖任何工具的内部清单;能抓到不在清单里但物理存在的,如 `kanban-*`)。

## 4. 机制 A — 跨工具重名守卫(linker)

- **外来名集合 `foreign(T)`**:遍历 `T.path` 下所有 SKILL.md,排除 skm 在 `state.json` 记录的、指向 `~/.skm/skills/` 的软链;其余按 frontmatter `name`(缺省目录名)收集。每次操作按工具构建一次并在调用内缓存。
- **建链前检查**:skm 要把 skill `N` 链入工具 `T` 前,若 `N ∈ foreign(T)` → **跳过该条 + 告警**(打印 `N` 与外来路径),继续处理其余(**决策 Y=①**:不中断整个 use/enable)。
- 落点:`linker.link()` 增加检查;`switcher`(use/enable/reset/rollback 重建链路时)透传告警。

## 5. 机制 B — doctor 重名检测

- `skm doctor` 在现有检查(断链 / 孤儿链 / 缺失)上新增一类「**重名冲突**」:对每个工具报出 `skm 链 ↔ 外来 skill` 撞名项(当场报出现有 7 个);`外来 ↔ 外来` 仅告知、不处理(那是工具自己的事)。

## 6. 机制 C — 中央仓收敛(purge 迁移,Z=不分期)

- **purge 判定**:复用外来名检测。中央仓某 skill 的 `name` 若命中**任一**受管工具的 `foreign(T)`(即它其实是某工具自带的冗余副本)→ 列为 purge 候选。
- **动作**(每个候选):① 从中央仓删除该目录;② 删除所有指向它的 skm 软链(跨全部工具);③ 从所有 `groups` / `packs` 引用中摘除;④ 计入报告。
- **保留清单**:12 个 skm 自有 skill —— `using-superpowers`、`ponytail`(+ `ponytail-audit/debt/gain/help/review`)、`karpathy-guidelines`、`grill-me`、`grill-with-docs`、`orchestration`、`macos-computer-use` —— 不在任何工具自带集合中,**不动**。
- **规模**:中央仓 91 → 约 12;清掉约 79 个(Hermes 来源副本,含 `kanban-*`)。
- **安全**:`--dry-run` 预览;`--apply` 前把 state 与 `config.toml` 快照到 `~/.skm/backups/`;删除软链走既有三重校验。**注意**:被 purge 的中央仓副本是工具自带的冗余份,单向移除、不自动恢复(需要时重新 `skm import`);`skm rollback <tool>` 恢复该工具的链路状态,但不重建已删的副本。

**分组后果(明确记录)**:purge 后引用 Hermes 副本的三组会瘦身 ——

| 分组 | 现在 | purge 后 |
|---|---|---|
| coding | 11 | 2(`karpathy-guidelines`、`ponytail`) |
| design | 10 | 0(清空) |
| research | 8 | 0(清空) |

即:**claude / codex / grok 经 skm 将不再获得这些 Hermes 来源的能力**。若日后要在其他工具用其中某些(如 `systematic-debugging` / `test-driven-development` / `requesting-code-review` 本是 superpowers 正源),由用户**从真正上游 `skm import` 成 skm 自有**,再纳入分组 —— 不在本 spec 自动完成(§10)。

## 7. 命令面

- `skm doctor` —— 扩展重名检测(只读报告)。
- `skm doctor --fix` / `skm prune-collisions` —— 删除与工具自带撞名的 skm 软链(即现有 7 条)。
- `skm sync-boundary --dry-run | --apply` —— 中央仓收敛(§6),预览 / 执行,带备份。
- (后续 / 用户动作)`skm import <upstream>` —— 需跨工具复用的能力,从正源重装。

## 8. 代码触点

- `linker.py`:`foreign(T)` 构建 + 建链前检查 + 告警返回。
- `switcher.py`:use / enable / disable / reset / rollback 透传守卫告警。
- `importer.py`:install / import 完成后提示"某些名与工具自带冲突,未链入"。
- `config.py`:purge 时安全摘除 `groups` / `packs` 引用并 `save_config`。
- `state.py`:已记录 skm 建链,用于判定"外来"与 purge 时清链。
- `cli.py` + doctor:新增子命令 `sync-boundary`、`prune-collisions`;doctor 报告扩展。
- 约束保持:纯标准库、单文件 ≤ 400 行、TDD。

## 9. 测试计划(pytest)

- **守卫**:`foreign(T)` 含名 `N` 时,链 `N` → 跳过 + 告警;链无冲突名 `M` → 正常建链。
- **外来判定**:排除 skm 自建链(指向中央仓的不算外来);真实目录 / 别的工具建的链算外来。
- **doctor**:构造撞名 → 报出;无撞名 → 干净。
- **prune-collisions**:只删 skm 撞名链;工具自带真身与非撞名链不动。
- **sync-boundary**:dry-run 不改动;apply 删中央仓副本 + 清链 + 摘 `groups` 引用 + 写备份;rollback 可复原。
- **回归**:纯自有 skill(`superpowers` / `ponytail` / `karpathy` / `grill` …)不被误 purge。

## 10. 分期 / 后续

- 本 spec 一次落地:边界 + 守卫 + doctor + 清障 + 中央仓收敛。
- 后续(用户按需):对确需跨工具复用的能力,从各自上游 `skm import` 重建为 skm 自有,再纳入分组。
