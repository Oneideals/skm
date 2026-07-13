# skm panel — 可视化配置面板 设计+计划

> 状态:设计已批准,直接 TDD 执行
> 日期:2026-07-12

## 目标

`skm panel` 起一个本地 web 面板,把 91 个 skill 可视化地拖进各场景桶,保存写回 `~/.skm/config.toml`。零依赖(Python 标准库 http.server + 单个自包含 HTML)。

## 数据模型小扩展

现状:`Scenario` 只能引用 pack。扩展:`Scenario` 增加直接 `skills: list[str]` 字段(与 base 同构)。
`resolve_skills` 改为:`base ∪ 场景的每个 pack 的 skills ∪ 场景的直接 skills`。
pack 机制不变(给导入的集合用)。向后兼容:旧 config 无 `skills` 字段 → 空列表。

## 组件

- **`skm/config.py`(改)**:`Scenario` 加 `skills` 字段;load/save 读写;`resolve_skills` 并入。
- **`skm/panel.py`(新)**:
  - `skill_description(skill_dir) -> str`:解析 SKILL.md frontmatter 的 description(处理内联引号 + `>`/`|` 块标量)。
  - `build_state(paths, cfg) -> dict`:`{skills:[{name,description}], base:[...], scenarios:{name:{label,skills,packs}}, packs:{name:[skills]}, tools:{tool:scenario|null}}`。
  - `apply_payload(paths, cfg, payload) -> None`:校验 id 合法、skill 存在于中央仓,写回 config(只动 base 和 scenarios,不碰 tools/packs 定义)。
  - `serve(paths, port=8787, open_browser=True) -> None`:stdlib http.server,路由 `GET /`→HTML、`GET /api/state`→build_state、`POST /api/save`→apply_payload。
- **`skm/panel.html`(新)**:单页,原生 JS 拖拽;左 skill 池(搜索+描述),右场景桶(base + 各场景,可增删改名),保存 POST /api/save。
- **`skm/cli.py`(改)**:加 `panel` 子命令(`--port`、`--no-open`)。

## 任务(TDD)

- **Task A**:`Scenario.skills` 字段 + resolve 并入 + 测试。
- **Task B**:`panel.py` 的 `skill_description` / `build_state` / `apply_payload` + 测试。
- **Task C**:`serve()` HTTP 路由 + `panel.html` + 服务器冒烟(curl)。
- **Task D**:`skm panel` CLI 子命令 + 端到端冒烟。

## 边界

- 面板只编辑分组(base/scenarios),不触发切换(切换仍 `skm use` 且需重启工具)。
- 保存后前端提示"记得 skm use 并重启工具生效"。
- 校验:非法 id / 引用不存在的 skill → 返回 400 + 错误信息,不写坏 config。
- 服务器仅监听 127.0.0.1,只读本机 config,无鉴权(本地个人工具)。
