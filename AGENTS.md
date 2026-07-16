# 跨工具工作协议

## 启动时自动执行

当你（agent）启动并定位到本项目时，执行以下步骤：

1. **检查 handoff 结构**
   - 如果 `.agent-handoff.md` 不存在，运行 `handoff-init` 创建它（如无此命令则手动创建目录和文件）
2. **感知当前变更状态**
   - 运行 `git status --short`，了解当前有哪些未提交的改动
3. **读取进度**
   - 读取 `.agent-handoff.md`，了解所有工具的总进度和遗留
   - 读取 `.agent-handoff/` 目录下时间最新的一条操作记录，精确了解上一轮作业的内容
4. **决策**
   - 基于以上信息决定从哪继续，而不是从头扫描整个项目

## 完成任务后自动执行

当你完成一组文件改动（准备进入响应结尾）后，执行以下步骤：

1. **确认改动清单**
   - 运行 `git diff --name-only` 或 `git status --short` 获取实际改动列表
2. **在 `.agent-handoff/` 写一条操作日志**
   - 文件名格式：`<YYYY-MM-DD_HHMM>_<工具名>.md`
   - 使用下面给出的模板
3. **不手动更新 `.agent-handoff.md`**
   - 该文件由 sync_agent_memory 自动汇总汇总，手改会被覆盖
4. **通知用户**
   - 告知用户已更新操作日志，提示下一步建议

## 操作日志模板

```markdown
tool: <hermes/codex/claude/grok>
time: <YYYY-MM-DD HH:MM>
project: <项目名>

## 改动的文件

| 文件 | 操作 | 状态 |
|---|---|---|
| src/auth/login.ts | edit | ✅ 完成 |
| src/api/routes.ts | edit | 🔧 进行中 |

## 未完成

- 逐条记录未完成的项

## 已知结论

- 已验证、可复用的结论
```

## .gitignore 提示

确保项目的 `.gitignore` 包含以下内容（handoff-init 会自动加，但手动确认也行）：

```
# Agent handoff
.agent-handoff.md
.agent-handoff/
```