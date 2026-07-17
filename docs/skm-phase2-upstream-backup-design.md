# skm skill 二期:上游更新 + GitHub 备份 — 设计

- 日期:2026-07-17
- 状态:待评审
- 关联:`skm/importer.py`(import/upgrade)、`skm/config.py`(Pack)、`skm/panel.py`/`panel.html`(面板)、`skm/cli.py`;新增 `skm/backup.py`、`skm/upstream.py`

## 1. 目标

1. **上游更新**:远端 skill 仓更新后,skm 能感知并提示;更新由用户显式触发(面板按钮 / CLI)。
2. **GitHub 备份**:中央仓(`skills/` 真身)+ 三层/分组配置(`config.toml`)+ 每工具状态(`state.json`)可推送到用户的 GitHub 私有仓,并可从其恢复。

## 2. 决策记录(brainstorming 结论)

- **更新体验 = 自动检查 + 手动应用**:检查便宜且只读(`git ls-remote` 取远端 HEAD,不 clone),自动做;应用改变 agent 行为(skill 即注入指令,且有供应链风险),必须显式。不做全自动更新、不做守护进程。
- **追踪范围 = 仅有 source 的 pack**:不为散装 skill 另建 per-skill source 双轨机制。运维上把 ponytail 收编成 pack(盲区 8→2);剩余散装(karpathy-guidelines、using-superpowers)保持手动,文档写明"要追踪就 import 其上游成 pack"。
- **备份范围 = 整个 `~/.skm`** 排除 `backups/` 与上游缓存:`skills/` 含无 source 散装(唯一不可再生部分),`config.toml` + `state.json` 即"每个工具的分组配置"。
- **备份触发 = 变更驱动自动推 + 手动命令**:每次配置落盘后 commit、异步 push,失败静默、下次补推;`skm backup` 立即强推,`skm restore` 恢复。不做 launchd 定时器(无变更时定时推是空转)。
- **升级粒度 = 按 source 仓**:同仓多 pack(matt-*×5)一次克隆全刷新。
- 备份功能 **opt-in**:未 `backup init` 时全部静默不生效。

## 3. Part 1 — 上游更新

### 3.1 Pack 元数据扩展(config.py)

`Pack` 增三个可选字段,import/upgrade 时写入:

- `commit: str | None` —— 安装时克隆仓的 HEAD 完整 hash(`git -C <clone> rev-parse HEAD`);
- `base: str | None` —— 当初 `--name` 的 base(如 `matt`);
- `split: bool = False` —— 当初是否 `--split-by-dir`。

TOML 往返:`commit = "..."`、`base = "..."`、`split = true`(仅非默认时写)。存量 pack 无 `commit` → 状态"未追踪",升级一次即入轨。

### 3.2 修复现存 upgrade bug(importer.py)

现状:`upgrade(pack)` 调 `import_repo(name=pack, force=True)` **不带 split** —— 对 split 导入的 pack(如 matt-engineering)会把整仓 41 个 skill 灌进一个 pack。修复:

- `upgrade_source(paths, cfg, url)`:按 **source 仓**升级。克隆一次;找出该 url 的全部 pack,按其记录的 `base`/`split` 重跑注册逻辑;
- **fresh 名单语义**:pack.skills 以上游最新为准(替换,不再 `old ∪ new` 合并);上游消失的 skill 从 pack 摘除、**真身留在中央仓**(变散装),报告中列明"已从 pack 摘除(真身保留)";
- 上游仍存在的 skill `force=True` 重装(内容刷新);全部 pack 记录新 `commit`;
- `skm upgrade <pack>` 保留为入口,内部解析出 source 后走 `upgrade_source`(同仓兄弟 pack 一起刷新,输出注明)。

### 3.3 检查(新 `skm/upstream.py`)

- `remote_head(url) -> str | None`:`git ls-remote <url> HEAD` 首列 hash;失败(离线/仓没了)返回 None。
- 缓存:`~/.skm/cache-upstream.json`,`{url: {"head": hash, "checked_at": epoch}}`,TTL 24h;`force=True` 绕过。缓存文件加入备份排除。
- `outdated_report(paths, cfg, force=False) -> dict[url, {"status", "packs", "local", "remote"}]`,status ∈ `up-to-date` / `outdated` / `untracked`(无 commit)/ `unreachable`(remote_head None)。

### 3.4 CLI(cli.py)

- `skm outdated [--force]`:按 source 分组列出三态 + 未追踪提示("upgrade 一次开始追踪")。
- `doctor`:**只读缓存**(不发网络),缓存显示有 outdated 时附一句提示;无缓存/未过期不提。

### 3.5 面板(panel.py + panel.html)

- 新端点 `GET /api/outdated?force=0|1`:服务端跑 `outdated_report`(带缓存);`POST /api/upgrade` body `{"url": ...}`:跑 `upgrade_source`,返回 `{installed, removed_from_pack, packs}`。
- 前端:`load()` 完成后**异步** fetch `/api/outdated`(不卡首屏);对 `status=outdated` 的 source,其全部 pack 块头显示 `⬆ 可更新` 徽标 + 「更新」按钮(同 source 联动);点击 → POST → toast 摘要 → `load()` 刷新。`untracked` 显示灰色 `·未追踪` 微标(hover 说明)。

### 3.6 ponytail 收编(运维步,代码完成后执行,gated)

`skm import https://github.com/DietrichGebert/ponytail`:6 个已存在跳过安装、注册成带 source+commit 的 pack。**显示代价与补偿**:按"pack 优先于前缀"规则,池子 `📚 ponytail 树` 会变 `📦 ponytail 块`;为保留树形,`_pool_groups` 对 pack 块增加**前缀感知排版**——若 pack 成员恰构成单一前缀家族(存在成员 R,其余全是 `R-*`),emit 时把 R 置于 `root`(kind 仍为 `pack`),前端按"根行+缩进"渲染(📦 图标 + 树形内容)。

## 4. Part 2 — GitHub 备份(新 `skm/backup.py`)

### 4.1 `skm backup init <git-url>`

`~/.skm` 内:`git init`(已是仓则跳过)→ 写 `.gitignore`(`backups/`、`cache-upstream.json`)→ `git remote add origin <url>`(已有则改 url)→ 首次 `git add -A && commit && push -u origin main`。文档注明:**建议私有仓**。

### 4.2 变更驱动自动推

- 咽喉:`save_config()` 与 `save_state()` 落盘后调 `backup.mark_dirty(paths)`(进程内标记);
- CLI 命令结束与面板 `apply_payload` 成功后调 `backup.autosync(paths, message)`:未 init(无 `.git` 或无 origin)→ 静默 no-op;脏 → `git add -A && commit -m "skm: <message>"`,然后 **`git push` 以后台进程发起**(`subprocess.Popen` 脱离等待,输出落 `~/.skm/push.log`);push 失败不影响本次操作,本地 commit 已在,下次 autosync/手动 backup 补推。
- `skm backup`:立即 commit(若脏)+ **同步** push,打印状态(未推提交数、上次成功推送时间、remote url)。

### 4.3 `skm restore <url> [--force]`

- `~/.skm` 不存在/为空:`git clone <url> ~/.skm`;
- 已存在:须 `--force`;先把现有 `~/.skm` 完整移动到 `/tmp/skm-restore-safety-<ts>/`,再克隆;
- 克隆后**重算链路**:遍历 `state.json` 每个工具,`switcher.use(tool, 其记录的 groups)` 重建软链;`config.tools` 里路径不存在的工具跳过并提示(换机器场景);
- 结束打印:恢复了几个 skill、几个工具、几条链,safety 快照位置。

## 5. 测试(pytest,假远端 = 本地 bare 仓 `file://`)

- config:Pack 三字段 TOML 往返;缺省兼容旧 config。
- importer:import 记录 commit/base/split;`upgrade_source` split 修复(5 pack 同仓刷新、不串包);fresh 名单(上游删 skill → pack 摘除、真身保留、报告列出);重装刷新内容。
- upstream:remote_head 取 hash;失败返 None;缓存 TTL 生效与 `--force` 绕过;三态判定。
- backup:init 幂等;autosync 未 init no-op / 脏才 commit;restore 到空目录 + 重链;已存在无 `--force` 拒绝、有则出 safety 快照。
- cli:`outdated` 输出三态;`doctor` 只读缓存。
- panel:`/api/outdated` 返回报告;`/api/upgrade` 触发升级并返回摘要;pack 前缀感知排版(root 非 null 的 pack collection)。
- 面板 JS:跑起来 + 截图验收(徽标、更新按钮、toast、树形 pack 块)。

## 6. 代码触点与约束

- 新文件:`skm/upstream.py`、`skm/backup.py`(各 <200 行);改:`config.py`、`importer.py`、`cli.py`、`panel.py`、`panel.html`。
- 纯标准库;git CLI(import 已依赖);单文件 ≤400 行;TDD。

## 7. 非目标(YAGNI)

- 不做全自动更新、不做 launchd/cron 定时器、不做常驻进程。
- 不做 per-skill source、升级前 diff 预览、多备份远端、备份加密。
- 不做 backups/ 目录入备份(临时快照,体积不可控)。
