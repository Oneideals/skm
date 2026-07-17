# skm MCP 管理 — 设计草案(已存档,未实施)

- 日期:2026-07-16
- 状态:**存档搁置** —— 用户决定暂不实施;本文记录勘察事实与已敲定的决策,供日后重启
- 关联:`docs/skm-design.md`(三层模型)、`docs/skm-tool-owned-boundary-design.md`(边界原则)

## 1. 动机(已确认痛点)

MCP server 配置与 skill 有同构的两个痛点,且已在用户机器上实测:

1. **重复维护**:`chrome-devtools`/`agent-browser` 在 4 个工具里各配一遍,`figma-console`/`node_repl`/`drawio` 配了 3 遍;
2. **常驻上下文**:MCP server 会话启动时加载,每个 server 的全部工具定义注入上下文(figma-console 一家数十个工具),无法按场景启停。

skm 的"中央注册 + 三层(通用/工具专用/分组)+ 重启生效"模型原样适用。

## 2. 勘察事实(2026-07-16,用户机器实测)

| 工具 | 配置文件 | 格式 | 现有 server |
|---|---|---|---|
| claude | `~/.claude.json` | JSON `mcpServers`(另有 projects 级,当前 0 个) | figma-console(env×2), node_repl(env×12), chrome-devtools, drawio, agent-browser |
| codex | `~/.codex/config.toml` | TOML `[mcp_servers.*]`(+`.env` 子表) | 同上 5 + computer-use, pencil |
| grok | `~/.grok/config.toml` | TOML `[mcp_servers.*]` | chrome-devtools, agent-browser, pencil |
| hermes | `~/.hermes/config.yaml` | YAML `mcp_servers:`,**每 server 带 `enabled:` 开关**;另有独立 `mcp:` 段(node_repl) | chrome-devtools, agent-browser, drawio, figma-console, node_repl |

要点:
- 三种格式(JSON / TOML×2 / YAML);TOML 两家(codex/grok)结构同款。
- 配置文件里混着用户的其他设置与密钥 → **写入必须外科手术式**,不能整文件重排。
- hermes 的 `enabled` 开关可用于启停(免删条目);其余工具启停 = 增删条目。
- 所有工具的 MCP 都是**会话启动时加载** → "切换后重启生效"模型成立。

## 3. 已敲定的决策

- **范围 = C(完整三层),不分期,一次完工**:中央注册表 + 通用层/工具专用层/分组,与 skill 同构;分组复用与否见 §5 未决。
- **接管策略 = C 变体("全接管 + 吸收不删除")**:
  - 单一真源:所有 MCP 条目最终归中央注册表,无永久"外来"类;
  - **不认识就自动收编**:sync 发现工具配置里注册表没有的条目 → 吸进注册表并提示,**绝不因"注册表里没有"而隐式删除**(堵住"手加实验 server 被静默吞掉"的洞);
  - 删除只走显式命令(`skm mcp remove`);
  - 每次写工具配置前自动备份该文件。
  - 背景:纯 C(不认识就删)违背 skm"管理者只拥有自己写入的东西"的安全纪律(linker 三重校验 / boundary 外来判定的同源原则),已向用户解释并获认可换成此变体。

## 4. 实现草图(勘察时的技术判断,未验证)

- **中央注册表**:`~/.skm/mcp.toml`(或并入 config.toml `[mcp.*]`):name → {command, args, env, transport(stdio/sse/http), url}。
- **每工具适配器**(零依赖约束下):
  - claude:JSON 整读整写 `mcpServers` 键(`.claude.json` 本就是机器管理的,格式重排可接受);
  - codex/grok:TOML **文本外科**——只增删替换 `[mcp_servers.<name>]` 到下一个 `[` 头之间的段,其余字节不动(stdlib tomllib 只读不写,整文件重生成会毁注释);
  - hermes:YAML **文本外科**——按缩进管理 `mcp_servers:` 下的 `<name>:` 块;或优先翻转 `enabled:` 开关。
- **state.json** 扩展:每工具记 skm 写入的 mcp 条目名(同 links 语义),备份/rollback 沿用。
- **三层解析**:`resolve_for_tool` 同款并集逻辑作用于 mcp 名单;`skm use` 一次切换同时重算 skill 链 + MCP 条目。
- **doctor**:注册表 vs 各工具配置漂移检测(条目内容不一致)、收编提示。
- **panel**:池子加 MCP 区(或独立列),分组/工具桶接受 mcp chip。
- **CLI**:`skm mcp add/list/remove/adopt`;use/enable/disable/reset/rollback 透传。

## 5. 未决问题(重启时需先答)

1. **密钥存放**(问到一半,未确认):提案 = 中央注册表明文存完整 env(`chmod 600`),与现状各工具配置明文同水位、不新增暴露面、不引第三方 secret manager;替代 = env 不进中央、每工具自留(但"装一次分发四处"就废一半)。
2. **分组复用**(未问):MCP 复用现有 skill 分组(切 coding 同时启停该场景的 skill+MCP,"场景"一个概念)vs 独立 mcp 分组(两套开关)。倾向前者,待确认。
3. hermes 独立 `mcp:` 段(node_repl 所在)与 `mcp_servers:` 段的关系需再勘察。
4. claude projects 级 `mcpServers` 是否纳管(当前 0 个,倾向 YAGNI 不管)。

## 6. 风险清单

- 写用户配置文件 = 高危面;文本外科的段边界解析必须有充分测试(注释、多行 args、引号内 `[`)。
- 收编时同名 server 在不同工具定义不一致(env 差异)→ 需合并策略(取最全?逐字段问?)。
- 密钥进中央文件 → 备份目录(`~/.skm/backups/`)也会含密钥,同样需 600。
