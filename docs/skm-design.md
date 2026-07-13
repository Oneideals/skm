# skm — 跨工具 Skill 管理器 设计文档

> 状态:设计已确认,待用户复审 → 转实现计划
> 日期:2026-07-12
> 作者:与 Claude 协同设计

## 1. 背景与痛点

用户在四个 AI CLI 工具间工作:**Claude Code、Codex、Grok build CLI、Hermes**。要解决两个痛点:

1. **集合的成组启停 + 省上下文**:有的 skill 是"集合"(如 superpowers 含 14 个 skill),整体使用才有意义。但全装会让每个 skill 的描述在会话启动时都注入系统提示,占用上下文。需要按需成组启用/禁用,不用的集合不占上下文。
2. **一次安装,处处可用**:一个 skill/集合装一次,四个工具都能调用,不必装四遍。

### 关键技术约束(已探明)

- 四个工具的 skill 机制**高度一致**:`<tool>/skills/` 目录下有某 skill 文件夹 = 该 skill 被加载。
- Skill 的上下文开销分两层:**菜单层**(name+description,会话启动时全量注入)和**正文层**(完整 SKILL.md,调用时才懒加载)。省上下文的唯一杠杆是**控制启动时进入菜单的 skill 有哪些**。
- 因此"启停"本质是**文件系统动作 + 下次启动生效**,不是会话内实时。"AI 自动按需挂载"不成立(菜单不列它,AI 就不知道它存在)。

## 2. 领域模型

三层结构 + 一个常驻层:

```
Skill(原子技能,含 SKILL.md 的文件夹)
  └─ Pack(集合:一组配合使用的 skill,成组启停)
       └─ Scenario(场景:一个或多个 Pack 的组合,一键切换)

Base(常驻层):无视场景,永远启用的 skill/pack
```

**启停规则:**
```
某工具最终启用的 skill = 展开(base) ∪ 展开(该工具当前 scenario 的所有 packs)   去重
其余全部禁用(软链移出该工具 skills/ 目录)
```

**四条确定约束:**
1. **base 常驻**:切场景不动 base。
2. **场景/集合可重合**:同一 skill 可属多个 pack、同一 pack 可属多个 scenario;解析时去重。
3. **按工具分别切**:每个工具独立持有自己的当前场景(Hermes 调研 + Claude 写代码 可并存)。
4. **下次启动生效**:切换后需重启对应工具的会话。

## 3. 目录结构

```
~/.skm/
├── skills/                  # 中央仓:所有 skill 真身(扁平,一层)
│   ├── web-research/SKILL.md
│   ├── brainstorming/SKILL.md
│   └── ...
├── config.toml              # 声明式配置:tools / base / packs / scenarios
├── state.json               # 运行时状态:每个工具当前场景 + skm 建的软链清单
└── backups/                 # 每次切换前的软链快照,可回滚
```

**中央仓永远扁平**:import 时把任意深度的源仓库"拍平"——找到含 `SKILL.md` 的文件夹,归一到 `~/.skm/skills/<skill-name>/`。

**四个工具目标目录:**
```
claude → ~/.claude/skills/
codex  → ~/.codex/skills/
grok   → ~/.grok/skills/
hermes → ~/.hermes/skills/
```

## 4. 配置文件 config.toml

```toml
[tools]
claude = "~/.claude/skills"
codex  = "~/.codex/skills"
grok   = "~/.grok/skills"
hermes = "~/.hermes/skills"

# base:常驻层,无视场景永远启用
[base]
skills = ["using-superpowers", "code-review"]

# Pack:集合。skills 列表引用中央仓的目录名
[packs.superpowers]
skills = ["brainstorming", "test-driven-development", "systematic-debugging", "..."]
source = "https://github.com/obra/superpowers"   # 可选:记录来源,便于 upgrade

[packs.research]
skills = ["web-research", "agent-reach", "arxiv"]

[packs.figma]
skills = ["figma-use", "figma-generate-design", "figma-implement-design"]

# Scenario:场景。英文 id 作命令参数,中文 label 仅用于显示
[scenarios.research]
label = "调研"
packs = ["research"]

[scenarios.coding]
label = "写代码"
packs = ["research", "superpowers"]     # packs 可重合复用

[scenarios.design]
label = "做设计"
packs = ["figma"]
```

**命名规范**:所有标识符(pack / scenario / skill 名)一律**英文小写短横线**。scenario 额外带一个中文 `label` 供 `skm list` 显示。三类标识符分属不同命名空间(packs.* / scenarios.*),同名不冲突。

**解析校验**:引用了中央仓不存在的 skill → 报错提示,不静默跳过。

## 5. 状态文件 state.json

```json
{
  "tools": {
    "hermes": {
      "scenario": "research",
      "links": ["web-research", "agent-reach", "arxiv", "using-superpowers", "code-review"]
    },
    "claude": { "scenario": "coding", "links": ["..."] },
    "codex":  { "scenario": null, "links": [] },
    "grok":   { "scenario": null, "links": [] }
  }
}
```

`links` 是 skm 在该工具 `skills/` 里**亲手建的**软链清单——是安全清理的唯一依据。

## 6. 切换算法 `skm use <tool> <scenario>`

```
1. 解析目标:  target = 展开(base) ∪ 展开(scenario 的所有 packs),去重
2. 读现状:    current = state.tools[tool].links
3. 算差集:
      要删 = current - target
      要加 = target - current
4. 备份:      当前软链快照 → ~/.skm/backups/<tool>-<时间戳>.json
5. 执行:
      删:仅限 state.links 名单内、且通过三重校验的软链
      加:在 tool 的 skills/ 建软链 → ~/.skm/skills/<skill>
6. 更新 state: scenario = 新场景,links = target
7. 提示:      "hermes 已切到 research(调研),启用 N 个 skill,重启 hermes 会话生效"
```

**幂等**:重复执行差集为空,无操作。

### 删除三重校验(安全核心)

一条软链**同时满足**才删,否则跳过并警告:
1. 在 state 的 links 名单里(是 skm 建的)
2. 确实是软链(不是真目录/文件)
3. 软链目标指向 `~/.skm/skills/`

→ 用户手工放进 `skills/` 的真实目录、别的工具建的软链,永远安全。

## 7. 命令集

```
# 安装/来源
skm import <git-url> [--split-by-dir]   # 导入仓库型集合。默认整仓一个 pack;
                                        # --split-by-dir 按子目录拆成多个 pack
skm install <skill>                     # 装单个 skill 进中央仓
skm pack create <name> --skills a,b,c   # 手挑型集合(如 figma)
skm upgrade [pack]                      # 按 source 拉取更新

# 场景切换(核心)
skm use <tool> <scenario>               # 切某工具到某场景
skm use all <scenario>                  # 便捷:四个工具都切(可选)
skm reset <tool>                        # 该工具清空到只剩 base

# 查看
skm list                                # 各工具当前场景 + 启用的 skill(显示中文 label)
skm packs                               # 所有集合及其 skill
skm scenarios                           # 所有场景及其 packs

# 安全
skm rollback <tool>                     # 回滚到上次切换前的软链快照
skm doctor                              # 校验软链健康(断链/孤链检测)
```

## 8. 从 skills-manager 迁移与卸载

用户决定卸载现有的 `skills-manager.app`。**但四个工具里现有 85 个软链指向 `~/.skills-manager/skills/`(92 个 skill),直接卸载会全断。**必须按安全顺序:

```
1. skm 建中央仓,把 ~/.skills-manager/skills/ 的 92 个 skill import 进 ~/.skm/skills/
2. 定义 base / packs / scenarios(把常用的组织成集合和场景)
3. skm use 各工具到目标场景,建立新软链(指向 ~/.skm/skills/)
4. 验证四个工具能正常加载 skill(实测)
5. 确认无误后,再删除旧的 ~/.skills-manager/ 软链和卸载 GUID app
```

**原则:先接管、再验证、后拆除。** 任何时候旧软链和新软链靠不同中央仓路径隔离,不互相覆盖。

## 9. 技术栈与实现边界

- **语言**:Python 3(标准库为主:`tomllib`/`pathlib`/`json`/`os.symlink`),零重依赖。
- **入口**:`~/.skm/skm.py` + `~/.local/bin/skm` 包装脚本。
- **不做**:GUI(纯 CLI);不碰各工具内部的 skill 加载逻辑(只管软链有无);不做会话内热切换(物理不可行)。
- **文件规模**:按核心开发规范,单文件 200-400 行。预计拆分:`cli.py`(命令分发)、`config.py`(解析+校验)、`linker.py`(软链增删+三重校验)、`state.py`(状态读写+备份)、`importer.py`(import/拍平)。

## 10. 错误处理与边界

- config 引用不存在的 skill → 明确报错,列出缺失项。
- 目标工具 `skills/` 目录不存在 → 自动创建。
- 软链已存在且指向别处 → 不覆盖,警告(可能是手工链或别的工具)。
- 断链检测(`skm doctor`):软链目标已删 → 提示修复。
- import 的仓库无 `SKILL.md` → 跳过并报告,不建空 pack。
- 所有破坏性操作(切换/reset)前自动备份,`rollback` 可逆。

## 11. 成功标准

1. 一个 skill/集合 import 一次,四个工具都能用(软链分发)。
2. `skm use claude coding` 后重启 Claude,只有 base + coding 场景的 skill 出现在菜单,其余不占上下文。
3. 四个工具可各自处于不同场景,互不干扰。
4. 切换是可逆的(rollback),且永不误删用户手工建的目录/链接。
5. 从 skills-manager 平滑迁移,迁移过程中 skill 不中断。
