# Panel Pool Collection Tree — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group prefix families (a root skill `X` plus its `X-*` members) into collapsible tree blocks in the panel's left skill pool; loose skills stay flat.

**Architecture:** `build_state` derives a `pool = {collections, loose}` structure (Python, unit-tested) and adds it to `/api/state`, keeping the flat `skills` list untouched. `panel.html`'s `renderPool` renders that structure — collections as collapsible bordered blocks, loose skills as today. Rendering is generic over a collection's `{root, members}` so future `kind:"pack"` blocks slot in with no render change.

**Tech Stack:** Python ≥3.11 stdlib, `pytest`; vanilla JS in a single self-contained `panel.html`.

## Global Constraints

- Standard library only; single file ≤ 400 lines (≤ 800 hard cap).
- TDD for `build_state` logic (Python). `panel.html` JS has no test framework in-repo → verify by running the panel and screenshotting.
- Drag payload stays `{kind:"skill", name}`; `dropzone`/`chip`/`renderAll`/`effective`/save flow unchanged.
- Commit format `<type>: <description>`; every commit ends with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Branch: `feat/pool-collection-tree` (already created; spec committed there).
- Spec of record: `docs/skm-pool-collection-tree-design.md`.

---

### Task 1: `build_state` — derive `pool` grouping

**Files:**
- Modify: `skm/panel.py` (add `_pool_groups`; add `"pool"` to `build_state`'s return dict)
- Test: `tests/test_panel.py`

**Interfaces:**
- Consumes: the flat `skills` list already built in `build_state` — `list[{"name": str, "description": str}]`.
- Produces: `_pool_groups(skills) -> {"collections": [{"kind":"prefix","root":{name,description},"members":[{name,description}]}], "loose": [{name,description}]}`. Root = a skill with ≥1 `name-*` sibling; each non-root skill joins its longest matching root; roots with no members degrade to loose. `build_state(...)["pool"]` returns this.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_panel.py`:

```python
def test_pool_prefix_family_forms_tree(paths):
    for n in ["ponytail", "ponytail-audit", "ponytail-debt", "ponytail-help",
              "grill-me", "grill-with-docs", "karpathy-guidelines"]:
        _skill(paths, n, f"---\nname: {n}\n---\n")
    pool = build_state(paths, load_config(paths))["pool"]
    assert len(pool["collections"]) == 1
    c = pool["collections"][0]
    assert c["kind"] == "prefix"
    assert c["root"]["name"] == "ponytail"
    assert [m["name"] for m in c["members"]] == \
        ["ponytail-audit", "ponytail-debt", "ponytail-help"]
    # grill-* 无 grill 根 → 散装;karpathy 单个 → 散装
    assert [s["name"] for s in pool["loose"]] == \
        ["grill-me", "grill-with-docs", "karpathy-guidelines"]


def test_pool_covers_every_skill_once(paths):
    for n in ["a", "a-b", "a-b-c", "x", "x-1", "zzz"]:
        _skill(paths, n, f"---\nname: {n}\n---\n")
    pool = build_state(paths, load_config(paths))["pool"]
    seen = [s["name"] for s in pool["loose"]]
    for c in pool["collections"]:
        seen.append(c["root"]["name"])
        seen += [m["name"] for m in c["members"]]
    assert sorted(seen) == ["a", "a-b", "a-b-c", "x", "x-1", "zzz"]   # 不丢
    assert len(seen) == len(set(seen))                               # 不重


def test_pool_present_and_skills_flat_unchanged(paths, make_skill):
    make_skill("solo")
    st = build_state(paths, load_config(paths))
    assert [s["name"] for s in st["skills"]] == ["solo"]   # 扁平表不变
    assert st["pool"]["collections"] == []
    assert [s["name"] for s in st["pool"]["loose"]] == ["solo"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_panel.py -k pool -v`
Expected: FAIL — `KeyError: 'pool'`.

- [ ] **Step 3: Add `_pool_groups` and wire it into `build_state`**

In `skm/panel.py`, add this function just above `build_state`:

```python
def _pool_groups(skills: list[dict]) -> dict:
    """按"命名前缀 + 存在根"把扁平 skill 表分成集合树 + 散装(设计 §3)。"""
    names = {s["name"] for s in skills}
    by_name = {s["name"]: s for s in skills}
    roots = {n for n in names
             if any(o != n and o.startswith(n + "-") for o in names)}
    members: dict[str, list[dict]] = {r: [] for r in roots}
    loose: list[dict] = []
    for s in sorted(skills, key=lambda x: x["name"]):
        n = s["name"]
        if n in roots:
            continue                       # 根是顶层块,不作更短根的成员
        owner = ""
        for r in roots:
            if n.startswith(r + "-") and len(r) > len(owner):
                owner = r                  # 最长匹配根 → 规避嵌套双重归属
        (members[owner] if owner else loose).append(s)
    collections: list[dict] = []
    for r in sorted(roots):
        if members[r]:
            collections.append({"kind": "prefix", "root": by_name[r],
                                 "members": members[r]})
        else:
            loose.append(by_name[r])       # 空成员的根 → 退化散装
    loose.sort(key=lambda x: x["name"])
    return {"collections": collections, "loose": loose}
```

Then in `build_state`, add `"pool"` to the returned dict. Change:

```python
    return {
        "skills": skills,
        "universal": sorted(cfg.universal),
```

to:

```python
    return {
        "skills": skills,
        "pool": _pool_groups(skills),
        "universal": sorted(cfg.universal),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_panel.py -v`
Expected: PASS (3 new `pool` tests + existing panel tests).

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (whole suite green).

- [ ] **Step 6: Commit**

```bash
git add skm/panel.py tests/test_panel.py
git commit -m "feat: build_state derives pool collection grouping (prefix trees)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `panel.html` — render collapsible collection blocks

**Files:**
- Modify: `skm/panel.html` (CSS additions; rewrite `renderPool`; add `collapsed` state + `matches`/`skillRow` helpers)

**Interfaces:**
- Consumes: `S.pool` from Task 1 (`{collections, loose}`); falls back to `{collections:[], loose:S.skills}` if absent.
- Produces: pool UI — each collection is a bordered block with a `▾/▸` toggle, draggable `📚 root` header (emits `{kind:"skill", name:root.name}`), member count, and indented member rows (name only, description on hover). Loose skills render as flat `.skill` rows. Search filters within the pool and force-expands blocks with matches.

- [ ] **Step 1: Add CSS for collection blocks**

In `skm/panel.html`, inside `<style>`, immediately after the `.skill .desc { ... }` rule, add:

```css
  .collection { border:1px solid var(--line); border-radius:8px; margin-bottom:6px;
    background:var(--panel2); overflow:hidden; }
  .chead { display:flex; align-items:center; gap:6px; padding:6px 8px; }
  .chead .tog { cursor:pointer; color:var(--muted); width:12px; user-select:none; }
  .chead .cname { font-weight:700; cursor:grab; white-space:nowrap; }
  .chead .cdesc { color:var(--muted); font-size:12px; flex:1; overflow:hidden;
    text-overflow:ellipsis; white-space:nowrap; }
  .chead .ccount { color:var(--muted); font-size:12px; background:var(--chip);
    border-radius:20px; padding:0 8px; }
  .cbody { padding:2px 6px 6px 22px; }
  .skill.member { padding:5px 8px; }
```

- [ ] **Step 2: Add collapse state + helpers, rewrite `renderPool`**

In `skm/panel.html` `<script>`, change the top state line:

```javascript
let S = null, model = null;
```

to:

```javascript
let S = null, model = null;
const collapsed = new Set();

function matches(s, q) {
  return !q || s.name.toLowerCase().includes(q) ||
         (s.description || "").toLowerCase().includes(q);
}

function skillRow(s, member) {
  const d = document.createElement("div");
  d.className = "skill" + (member ? " member" : "");
  d.draggable = true;
  if (member) { d.title = s.description || "";
    d.innerHTML = `<div class="name">${s.name}</div>`; }
  else d.innerHTML = `<div class="name">${s.name}</div><div class="desc">${s.description||""}</div>`;
  d.addEventListener("dragstart", e =>
    e.dataTransfer.setData("text/plain", JSON.stringify({kind:"skill", name:s.name})));
  return d;
}
```

Then replace the entire `renderPool` function:

```javascript
function renderPool() {
  const q = (document.getElementById("search").value||"").toLowerCase();
  const pool = document.getElementById("pool"); pool.innerHTML = "";
  const P = S.pool || {collections:[], loose:S.skills};
  for (const col of P.collections) {
    const root = col.root;
    const memHits = col.members.filter(m => matches(m, q));
    if (q && !matches(root, q) && !memHits.length) continue;   // 整块无命中 → 隐藏
    const shown = q ? memHits : col.members;
    const open = q ? true : !collapsed.has(root.name);         // 搜索强制展开
    const box = document.createElement("div"); box.className = "collection";
    const head = document.createElement("div"); head.className = "chead";
    const tog = document.createElement("span"); tog.className = "tog";
    tog.textContent = open ? "▾" : "▸";
    tog.addEventListener("click", () => {
      collapsed.has(root.name) ? collapsed.delete(root.name) : collapsed.add(root.name);
      renderPool();
    });
    const nm = document.createElement("span"); nm.className = "cname";
    nm.textContent = `📚 ${root.name}`; nm.draggable = true;
    nm.addEventListener("dragstart", e =>
      e.dataTransfer.setData("text/plain", JSON.stringify({kind:"skill", name:root.name})));
    const desc = document.createElement("span"); desc.className = "cdesc";
    desc.textContent = root.description || "";
    const cnt = document.createElement("span"); cnt.className = "ccount";
    cnt.textContent = col.members.length;
    head.append(tog, nm, desc, cnt); box.appendChild(head);
    if (open) {
      const body = document.createElement("div"); body.className = "cbody";
      for (const m of shown) body.appendChild(skillRow(m, true));
      box.appendChild(body);
    }
    pool.appendChild(box);
  }
  for (const s of P.loose) if (matches(s, q)) pool.appendChild(skillRow(s, false));
}
```

- [ ] **Step 3: Restart the panel server so it serves the new HTML**

`panel.html` is read once at server startup, so the running instance must be restarted (Task 1's `build_state` change is already live per-request; this step is for the HTML).

Run:
```bash
lsof -ti:8790 | xargs kill 2>/dev/null; sleep 1
cd /Users/jerrycheng/LocalStorage/GitHub/skm
nohup .venv/bin/python bin/skm panel --port 8790 --no-open > /tmp/skm-panel-8790.log 2>&1 < /dev/null &
disown
sleep 1.5; curl -s -m3 -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8790/
```
Expected: `HTTP 200`.

- [ ] **Step 4: Verify in the browser (screenshot)**

Reload the panel tab and screenshot the pool. Confirm ALL of:
- A bordered `📚 ponytail` block with `▾` and count `5`, members `ponytail-audit/debt/gain/help/review` indented beneath.
- Loose skills (`grill-me`, `grill-with-docs`, `karpathy-guidelines`, `using-superpowers`) flat below, unchanged.
- Clicking `▾` collapses members to a single header row (`▸ 📚 ponytail  5`); clicking again expands.
- Dragging `📚 ponytail` onto a group bucket adds `ponytail`; dragging a member adds that member (drag still works).
- Typing `audit` in search hides everything except the ponytail block auto-expanded showing only `ponytail-audit`.

If any check fails, fix `renderPool`/CSS and re-verify (max 3 iterations).

- [ ] **Step 5: Commit**

```bash
git add skm/panel.html
git commit -m "feat: panel pool renders collapsible collection tree blocks

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the executor

- Run tests with `.venv/bin/python -m pytest`.
- Task 1 is pure Python/TDD. Task 2 is UI — its "test" is the running panel + screenshot (Step 4); there is no pytest for `panel.html`.
- The panel server on 8790 is a detached process; Task 2 Step 3 restarts it to pick up the new HTML.
