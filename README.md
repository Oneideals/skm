# skm — 跨工具 Skill 管理器

一个 skill 装一次,分发给四个 AI CLI 工具(Claude Code / Codex / Grok / Hermes);按 **场景** 成组启停 skill,只让当前需要的进上下文。

## 模型

```
Skill(原子)  →  Pack(集合)  →  Scenario(场景 = 若干 Pack 的组合)
Base:无视场景永远启用的常驻层

某工具最终启用的 skill = base ∪ 当前场景的所有 pack,其余禁用(软链移出)
```

- **按工具分别切**:每个工具独立持有自己的当前场景。
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
skm use <tool> <scenario>               # 把某工具切到某场景(tool=all 切全部)
skm reset <tool>                        # 清到只剩 base
skm rollback <tool>                     # 回滚到上次切换前

# 查看 / 体检
skm list                                # 各工具当前场景 + 启用的 skill
skm packs / skm scenarios               # 列所有集合 / 场景
skm doctor                              # 断链、孤儿链、缺失 skill 检查
```

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
