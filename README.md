# skm — 跨工具 Skill 管理器

一个 skill 装一次,分发给四个 AI CLI 工具(Claude Code / Codex / Grok / Hermes);按 **场景** 成组启停 skill,只让当前需要的进上下文。

## 模型

```
某工具最终启用的 skill = 通用层 ∪ 该工具专用层 ∪ ⋃(该工具勾选的各分组)
```

- **通用层(universal)**:所有工具常驻的 skill。
- **工具专用层**:每个工具自己的常驻 skill(如 Hermes 专属的 hermes-agent、petdex 只给 Hermes)。
- **分组(group)**:命名的 skill 集(coding / design / research…),**一个工具可同时勾选多个**。

- **按工具分别切**:每个工具独立持有自己勾选的分组。
- **下次启动生效**:切换是软链增删,重启对应工具的会话后才生效。

## 安装

```bash
ln -sf "$PWD/bin/skm" ~/.local/bin/skm   # 已在 PATH 里则直接可用
```

中央仓与配置在 `~/.skm/`(可用 `SKM_HOME` 覆盖)。

## 常用命令

```bash
# 装 skill / 集合
skm import <git-url> [--split-by-dir]   # 导入仓库为 pack(可按子目录拆多个 pack)
skm install <path>                      # 装单个本地 skill 进中央仓
skm pack create <name> --skills a,b,c   # 手挑若干 skill 组一个 pack
skm upgrade <pack>                      # 按来源 URL 更新

# 切场景(核心)
skm use <tool> [group...]               # 设定某工具启用哪些分组(可多个;不给=清空)
skm enable <tool> <group>               # 给工具增开一个分组
skm disable <tool> <group>              # 给工具关掉一个分组
skm use all coding                      # 便捷:所有工具都设为 coding
skm reset <tool>                        # 清空该工具所有分组(留通用层+专用层)
skm rollback <tool>                     # 回滚到上次切换前

# 查看 / 体检
skm list                                # 各工具三层现状(通用 N + 专用 M + 分组[...])
skm groups / skm packs                  # 列所有分组 / 集合
skm doctor                              # 断链、孤儿链、缺失 skill 检查
skm panel                               # 打开可视化配置面板
```

## 可视化面板

```bash
skm panel                 # 浏览器打开 http://127.0.0.1:8787,拖 skill 进场景桶,保存写回 config.toml
skm panel --port 9000 --no-open
```

左边是全部 skill(可搜索、带描述),右边是 base 和各场景桶;拖进去、点 ✕ 移除,顶部显示四工具当前场景。保存后 `skm use <工具> <场景>` 并重启工具生效。

## 配置 `~/.skm/config.toml`

```toml
[tools]
claude = "~/.claude/skills"
codex  = "~/.codex/skills"
grok   = "~/.grok/skills"
hermes = "~/.hermes/skills"

[base]
skills = ["using-superpowers", "code-review"]

[packs.research]
skills = ["web-research", "arxiv"]

[scenarios.research]
label = "调研"          # 仅用于 skm list 显示,命令参数用英文 id
packs = ["research"]
```

## 安全保证

删除软链需**三重校验**:①在 state 记录里 ②确实是软链 ③指向 `~/.skm/skills/`。
你手工放进工具 `skills/` 的真实目录、别的工具建的软链,skm 永不触碰。每次切换前自动备份,`skm rollback` 可逆。

## 开发

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q      # 47 tests
```
