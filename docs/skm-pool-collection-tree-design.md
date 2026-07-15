# skm 面板 · 池子集合树分组 — 设计

- 日期:2026-07-15
- 状态:待评审
- 关联:`skm/panel.py`(`build_state`)、`skm/panel.html`(`renderPool`)、`docs/skm-panel-design.md`

## 1. 背景

`skm panel` 左侧「Skill 池」目前把中央仓所有 skill **扁平**列出(`build_state` 的 `skills` 表 → `renderPool` 逐个渲染,每个是独立可拖的 `.skill` 行)。当一个"集合"由多个 skill 组成时(如 ponytail:`ponytail` + `ponytail-audit/debt/gain/help/review`),它们散落在池子里、看不出归属,也看不出谁是**总领**(`ponytail` 是核心本体,其余是它的 `ponytail-*` 派生)。

目标:把这类"有总领的前缀家族"在池子里收成**一块可折叠的树**(根在上、成员缩进),散装 skill 照旧;并把渲染结构设计成将来能容纳 pack 分块。

## 2. 决策记录(brainstorming 结论)

- **X=A+B(骨架)**:用**命名前缀 + 存在根**推断集合与层级(A);渲染结构对 `kind` 通用,预留 pack 分块(B),但 **pack 数据本期不 emit**。
- **不做 C**(frontmatter 声明父子):要手改导入 skill 的 frontmatter,会被 import/upgrade 覆盖(与 hyperframes 分叉同坑)。将来若需显式层级,写在 **pack/config**(skm 自有、重装不丢),作为 B 的可选字段,不是第三套系统。
- **拖拽 = A**:根/成员/散装每个节点各自是一个 skill,单独拖;树只做视觉分组,拖拽载荷 `{kind:"skill", name}` 不变。
- **视觉 = 样式 2**:可折叠边框块;搜索命中自动展开;子项行只显示名字、描述移 hover;根行保留描述。
- **算在哪 = 服务端**:分组逻辑放 `build_state`(Python,可 pytest 测);`panel.html` 只做傻渲染。

## 3. 分组算法(`build_state`,纯派生)

输入:中央仓 skill 列表(已有,`[{name, description}]`,按名排序)。设 `names` = 全部 skill 名集合。

1. **是否为根**:`is_root(S)` ⟺ 存在另一 skill `T`(`T≠S`)使 `T.name` 以 `S + "-"` 开头。
2. **roots** = 所有 `is_root` 为真的 skill。
3. **成员归属**:对每个 skill `M`,取 `roots` 中**最长**的 `R` 使 `M.name` 以 `R + "-"` 开头(`M≠R`);若存在则 `M` 归为 `R` 的成员(最长匹配 → 规避嵌套双重归属)。根自身不作为任何更短根的成员(根永远是顶层块)。
4. **成块条件**:仅当根 `R` 的成员非空才成一块;成员全被更长根claim 导致为空的根,退化为散装(规避空块)。
5. **loose** = 既非根、又未归入任何根的 skill。
6. **两层即止**:块 = 根 + 其直接成员(成员即便自身也是根,也各自成顶层块;不渲染更深层级)。

对当前数据的结果:roots = `{ponytail}`;`ponytail` 块成员 = `ponytail-audit/debt/gain/help/review`;loose = `grill-me`、`grill-with-docs`、`karpathy-guidelines`、`using-superpowers`(`grill-*` 无 `grill` 根 → 全散装)。

## 4. 数据结构(`/api/state` 新增 `pool`)

保留原 `skills` 扁平表不变(header 计数、`effective()`、向后兼容都依赖它);**新增**派生字段:

```json
"pool": {
  "collections": [
    {
      "kind": "prefix",
      "root": {"name": "ponytail", "description": "…"},
      "members": [
        {"name": "ponytail-audit", "description": "…"},
        {"name": "ponytail-debt",  "description": "…"}
      ]
    }
  ],
  "loose": [ {"name": "grill-me", "description": "…"} ]
}
```

- `kind` 预留:将来 pack 分块 emit `"kind": "pack"`(附 `name`/`source`,`root` 可为 null),渲染无需改。
- `collections` 按根名排序;`members` 按名排序;`loose` 按名排序。

## 5. 渲染(`panel.html` `renderPool`)

- 遍历 `pool.collections`,每块渲成**可折叠边框块**(样式 2):根行 = `📚 <root.name>` 粗体 + `▾/▸` 折叠钮 + 成员计数;根行下缩进列成员。根行、成员行均 `draggable`。
- 再遍历 `pool.loose`,平铺为现有 `.skill` 行。
- 渲染**对 `kind` 通用**:块头/成员的渲染只依赖 `{root, members}`,不分 prefix/pack —— 这是 B 的骨架。
- **拖拽**:每个节点 `dragstart` 发 `{kind:"skill", name}`(与现状完全一致),`dropzone`/`drop` 零改动。

**折叠 / 搜索 / 描述:**

- 折叠态:前端一个 `Set`(记已折叠的根名),会话内保留;默认展开。
- 搜索:在 `pool` 内按名/描述过滤(根 + 成员 + 散装);某块有命中 → 强制展开并只显命中项;整块无命中 → 隐藏。
- 子项行只显示 `name`,`description` 放 `title`(hover 显示,省窄列空间);根行保留描述。

## 6. 测试

- **pytest**(`tests/test_panel.py`,测 `build_state`):
  - 前缀有根 → 成一块,`root`/`members` 正确且排序;
  - 有前缀无根(`grill-me`+`grill-with-docs`,无 `grill`)→ 全进 `loose`;
  - 单个孤立 skill → `loose`;
  - 嵌套(`a`,`a-b`,`a-b-c`)→ `a-b-c` 归最长根 `a-b`,不双重归属;空块根退化散装;
  - `skills` 扁平表保持不变(回归);`pool.loose`+所有 `members`+所有 `root` 覆盖全部 skill(不丢不重)。
- **面板 JS** 仓库无 JS 测试框架 → 用**跑起来的面板 + 截图**肉眼验收:块渲染、折叠/展开、每节点可拖、搜索自动展开。

## 7. 代码触点

- `skm/panel.py`:`build_state` 新增 `pool` 派生(新内部函数 `_pool_groups(skills)`);`skills` 表不动。
- `skm/panel.html`:`renderPool` 重写为"集合块 + 散装";新增折叠态与 hover 描述;`dropzone`/`chip`/`renderAll`/`effective` 不动。
- 约束保持:纯标准库、单文件 ≤ 400 行、`build_state` 逻辑 TDD。

## 8. 非目标(YAGNI)

- 不 emit pack 分块数据(只留 `kind` 扩展点 + 通用渲染)。
- 不做 C(frontmatter 父子);不做"拖根加整族";不做三层以上嵌套树。
- 不改拖拽载荷、drop 逻辑、保存/应用链路。
