# skm 工具血统边界(tool-owned boundary)— 设计

- 日期:2026-07-14
- 状态:待评审
- 关联:`docs/skm-tool-boundary-design.md`(前身:边界 + 重名守卫 + sync-boundary)、`skm/boundary.py`、`skm/config.py`、`skm/cli.py`

## 1. 背景

前身 spec 确立了边界:中央仓只放 skm 自有 skill,工具自带的归工具自己管;并用 `sync-boundary` 把中央仓里"其实是工具自带的冗余副本"收敛掉。其判定源是**决策 X=①**:扫工具 `skills/` 目录下**物理存在、且非 skm 建软链**的 `SKILL.md` 的 `name`。

**问题:X=① 会漏判。** 当一个工具自带的 skill,其在工具 live 目录里的**唯一副本恰恰就是 skm 的那条软链**(工具没有独立真身),`foreign_skill_names` 会把该软链剪掉,于是这个 skill **既不被算作"工具自带",也就不会被 `sync-boundary` 收敛**。实测:`~/.hermes/skills/` 下有 7 个中央仓 skill 属于 Hermes 血统,但 `sync-boundary` 报告"✓ 无冗余副本"——全部漏网:

- `apikey-image-gen`、`grok-image-to-video`:功能上只能走 Hermes Web UI,别的工具用不了;唯一真身只在中央仓,live 目录里是 skm 软链。
- `hyperframes`、`markdown-viewer`、`remotion`:Hermes Web UI 托管安装(`~/.hermes/skills/.webui-managed-skills.json` 里 `owner: hermes-web-ui`)。
- `dogfood`、`yuanbao`:Hermes 出厂树(`~/.hermes/hermes-agent/skills`)自带,升级会恢复;`dogfood` 甚至没链进任何工具,纯躺中央仓。

这些"血统残留"已于 2026-07-14 手工剔除(备份 `~/.skm/backups/purge-hermes-lineage-*`)。本 spec 的目的是**把判定固化进代码**,让 `doctor` / `sync-boundary` 今后自动识别,避免再攒新残留。

## 2. 原则精化

**工具血统(tool-owned)= 出厂/托管 ∪ 功能锁死。** 一个 skill 属于工具 T,若:

- T 会在升级/重装时恢复它(出厂树 or 托管清单),**或**
- 它功能上离不开 T(如必须走 Hermes Web UI),换到别的工具跑不起来 —— 这类"其他工具用不了"的,放中央仓做分发无意义。

**判定源(在 X=① 之上扩充,而非替换):**

```
owned(T) = foreign(T)                     ← 现有:live 目录里非 skm 的物理真身(X=①)
         ∪ ⋃ declared(T)                  ← 新增:T 在 config 里声明的 owned_sources
```

功能锁死这一类无需单独的启发式检测(如 grep "Hermes Web UI"):实测中 `apikey-image-gen` / `grok-image-to-video` 已被 Web UI 托管清单覆盖。故本 spec **只实现两类权威、基于文件的信号**(清单 + 树),不做脆弱的文本启发式。

## 3. 决策记录

- **决策 X 修订(X=①+④)**:保留 X=① 作为默认与兜底(工具无关、能抓物理存在的);在其上**新增按工具声明的 owned_sources**,以覆盖"唯一副本是 skm 软链"和"出厂但未在 live 目录物化"两种漏判。owned_sources 是**每工具可选配置**,Hermes 特异性只落 config、不进 `boundary.py`,维持跨工具核心的通用性。
- **决策 W=A(移交)**:`sync-boundary --apply` 收敛正被工具软链的血统 skill 时,**默认自动移交**(见 §6),保证 convergence 操作对工具非破坏。
- **命令面 = 扩展现有 `sync-boundary` + `doctor` 联报**,不新开命令(同一个"中央仓收敛"概念,只是判定更准)。

## 4. 机制 A — Config 扩展 `owned_sources`

- `ToolCfg` 增可选字段 `owned_sources: list[Path]`(默认 `[]`)。
- 条目两类:
  - **清单文件**(JSON):对象则取其 **key** 为 skill 名(适配 `.webui-managed-skills.json`);数组则取元素为名。
  - **目录树**:递归扫 `SKILL.md`,按 frontmatter `name`(缺省目录名)取名。
- `load_config`:读 `body.get("owned_sources", [])` 并 `expanduser()`。
- `save_config`:仅当非空时回写 `owned_sources = [...]`(不污染无此配置的工具);**必须回写**,否则任何一次 config 写入(如 panel 保存、sync-boundary 备份重写)都会把它抹掉。
- `default_config()`:**保持空**——不把 Hermes 路径写进代码默认值。

## 5. 机制 B — boundary 检测 `owned_skill_names`

- 新增 `owned_skill_names(paths, tool_cfg) -> set[str]` = `foreign_skill_names(paths, tool_cfg.path)` ∪ ⋃(各 owned_source 解析出的名字)。
- **目录型来源**复用 `foreign_skill_names` 的遍历规则:**排除指向中央仓的 skm 软链**。防止误配(如把 owned_source 指到工具 live 目录)时,把 skm 合法链入的 skill 反噬式判为"工具所有"而自杀式清除。为此把现有 `foreign_skill_names` 的遍历抽成可对任意 root 复用的内部函数。
- **清单型来源**:JSON key/元素即名,无软链顾虑(清单是工具对所有权的显式声明)。
- 来源路径**不存在** → 静默跳过(工具没装 / 路径过期);由 `doctor` 另行告警(§7)。
- `_tool_owned_names(paths, cfg)` 改为对所有工具求 `owned_skill_names` 的并集;`purge_candidates` 因此自动扩容,自身无需改。

## 6. 机制 C — `sync_boundary --apply` 移交逻辑

对 purge 集合中、当前被某工具软链的每个 skill `s`:

- 若 `skill_name(中央仓/s) ∈ foreign_skill_names(该工具 live 目录)`(工具已有**独立原生副本**)→ 仅 `remove_link`。**保持前身"重名冗余副本"场景行为不变**,不制造重复顶层真身。
- 否则(工具唯一副本就是这条 skm 软链)→ **移交**:删该软链 → 从中央仓副本 `copytree` 成实体真身落回工具 live 目录 → 再摘 config / 删中央仓副本。

移交发生在删中央仓副本**之前**(源仍在)。`SyncReport` 增 `handoff: list[str]`(`"tool/skill"`)。前身已有的 state + `config.toml` 快照备份保留不变。

## 7. 机制 D — `doctor` 联报

`doctor()` 末尾新增:

- 算 `purge_candidates(paths, cfg)`,每个残留报 `✗ 中央仓存在工具血统残留(可 sync-boundary 收敛): <name>`。
- 轻量校验:`owned_sources` 中配置了但路径不存在的,报 `✗ tools.<t>: owned_source 路径不存在: <p>`(防手滑写错导致检测静默失效)。

## 8. 命令面 / 代码触点

- `config.py`:`ToolCfg.owned_sources` 字段;`load_config` 读、`save_config` 写。
- `boundary.py`:`owned_skill_names`;`foreign_skill_names` 遍历抽公共内部函数;`_tool_owned_names` 并集扩充;`SyncReport.handoff`;`sync_boundary` apply 分支移交逻辑。
- `cli.py`:`doctor` 报告扩展(残留 + 坏 owned_source 路径);`sync-boundary` 报告打印 `handoff`。
- 约束保持:纯标准库、单文件 ≤ 400 行、TDD。

## 9. 测试计划(pytest,复用 `paths`/`make_skill`/`tool_dir` fixture)

- `test_config`:`owned_sources` load→save→load 往返保真;缺省为空。
- `test_boundary`:清单 JSON key 命中;清单数组命中;目录树 SKILL.md 命中;缺失来源跳过;目录来源排除 skm 软链;`owned_skill_names` 与 `foreign` 求并;`purge_candidates` 抓到"非重名副本"的工具血统(仅经 owned_sources 可见者)。
- `test_boundary`(apply):无原生副本 → 移交出实体真身且内容一致;有原生副本 → 仅解链(回归前身行为,不生重复);config 各层摘引用;中央仓删除;`report.handoff` 正确;dry-run 不改动。
- `doctor`:血统残留被点名;坏 owned_source 路径被点名;无残留时干净。
- **回归**:纯 skm 自有 skill(`using-superpowers`/`ponytail*`/`karpathy-guidelines`/`grill*`)在配了 owned_sources 后仍不被误判/误 purge。

## 10. 落地到真实 config(代码通过后,单独确认再写)

往 `~/.skm/config.toml` 的 `[tools.hermes]` 写:

```toml
owned_sources = [
  "~/.hermes/skills/.webui-managed-skills.json",
  "~/.hermes/hermes-agent/skills",
  "~/.hermes/hermes-agent/optional-skills",
]
```

此后 `skm doctor` / `sync-boundary` 自动识别 Hermes 血统。**这是改用户真实配置**,不在代码里默认写入。

## 11. 非目标(YAGNI)

- 不做"grep 功能依赖 Hermes Web UI"的文本启发式(清单已覆盖)。
- 不为 claude/codex/grok 预置 owned_sources(用户按需声明)。
- 不改 panel UI 展示血统。
- 不自动为被移交/清空的分组从上游重装 skill(延续前身 §10:用户按需 `skm import`)。
