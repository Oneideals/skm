"""配置面板:SKILL.md 描述解析、状态构建、保存并应用。HTTP 服务见文件末尾。

面板编辑三层:universal(通用)、tools[*].skills(工具专用)、groups(分组,可多选)。
保存时写回 config 并对每个工具按其勾选的分组重算软链。
"""
from __future__ import annotations

import json
import re
import socketserver
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import switcher
from .config import (ID_RE, Config, Group, ToolCfg, load_config,
                     missing_in_repo, save_config)
from .paths import Paths
from .state import load_state

_KEY_RE = re.compile(r"^[A-Za-z_][\w-]*:")
_BLOCK_INDICATORS = {">", "|", ">-", "|-", ">+", "|+"}


class PanelError(Exception):
    pass


def skill_description(skill_dir: Path) -> str:
    """从 SKILL.md frontmatter 取 description(支持内联引号与 >/| 块标量)。"""
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return ""
    lines = md.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    fm: list[str] = []
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        fm.append(ln)
    for i, ln in enumerate(fm):
        if not ln.startswith("description:"):
            continue
        value = ln[len("description:"):].strip()
        if value and value not in _BLOCK_INDICATORS:
            return _clean(value)
        collected: list[str] = []
        for cont in fm[i + 1:]:
            if _KEY_RE.match(cont):
                break
            if cont.strip():
                collected.append(cont.strip())
        return _clean(" ".join(collected))
    return ""


def _clean(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        text = text[1:-1]
    return re.sub(r"\s+", " ", text).strip()


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


def build_state(paths: Paths, cfg: Config) -> dict:
    skills = []
    if paths.skills.exists():
        for d in sorted(paths.skills.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists():
                skills.append({"name": d.name, "description": skill_description(d)})
    state = load_state(paths)
    return {
        "skills": skills,
        "pool": _pool_groups(skills),
        "universal": sorted(cfg.universal),
        "packs": {n: sorted(p.skills) for n, p in sorted(cfg.packs.items())},
        "groups": {
            n: {"label": g.label, "skills": sorted(g.skills), "packs": sorted(g.packs)}
            for n, g in sorted(cfg.groups.items())
        },
        "tools": {
            t: {"skills": sorted(tc.skills),
                "groups": (state[t].groups if t in state else [])}
            for t, tc in sorted(cfg.tools.items())
        },
    }


def apply_payload(paths: Paths, cfg: Config, payload: dict) -> None:
    """把面板提交的三层配置校验后写回 config,并对每个工具按勾选分组重算软链。"""
    universal = list(payload.get("universal", []))
    tools_in = payload.get("tools", {})
    groups_in = payload.get("groups", {})

    new_groups: dict[str, Group] = {}
    for name, body in groups_in.items():
        if not ID_RE.match(name):
            raise PanelError(f"分组名 '{name}' 不合法:只允许小写字母/数字/短横线")
        packs = list(body.get("packs", []))
        for p in packs:
            if p not in cfg.packs:
                raise PanelError(f"分组 '{name}' 引用了不存在的 pack: {p}")
        new_groups[name] = Group(skills=list(body.get("skills", [])), packs=packs,
                                 label=body.get("label") or None)

    new_tools: dict[str, ToolCfg] = {}
    for name, tc in cfg.tools.items():
        body = tools_in.get(name, {})
        new_tools[name] = ToolCfg(path=tc.path, skills=list(body.get("skills", tc.skills)))

    referenced = set(universal)
    for tc in new_tools.values():
        referenced |= set(tc.skills)
    for g in new_groups.values():
        referenced |= set(g.skills)
    missing = missing_in_repo(paths, referenced)
    if missing:
        raise PanelError("以下 skill 不在中央仓: " + ", ".join(missing))

    for name, body in tools_in.items():
        for g in body.get("groups", []):
            if g not in new_groups:
                raise PanelError(f"工具 '{name}' 选了不存在的分组: {g}")

    cfg.universal = universal
    cfg.tools = new_tools
    cfg.groups = new_groups
    save_config(paths, cfg)

    # 保存即应用:对每个工具按其勾选的分组重算软链
    for name, body in tools_in.items():
        if name in cfg.tools:
            switcher.use(paths, cfg, name, list(body.get("groups", [])))


_HTML = Path(__file__).parent / "panel.html"


class _Server(ThreadingHTTPServer):
    """跳过 socket.getfqdn(反向 DNS,某些网络下会卡数十秒)。"""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def _make_handler(paths: Paths):
    html = _HTML.read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def address_string(self):
            return self.client_address[0]

        def _send(self, code: int, body: str, ctype: str) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/" or self.path.startswith("/index"):
                self._send(200, html, "text/html; charset=utf-8")
            elif self.path == "/api/state":
                cfg = load_config(paths)
                self._send(200, json.dumps(build_state(paths, cfg), ensure_ascii=False),
                           "application/json; charset=utf-8")
            else:
                self._send(404, json.dumps({"error": "not found"}), "application/json")

        def do_POST(self):
            if self.path != "/api/save":
                self._send(404, json.dumps({"error": "not found"}), "application/json")
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw)
                cfg = load_config(paths)
                apply_payload(paths, cfg, payload)
                self._send(200, json.dumps({"ok": True}), "application/json")
            except (PanelError, ValueError) as e:
                self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False),
                           "application/json; charset=utf-8")

    return Handler


def make_server(paths: Paths, port: int = 8787) -> ThreadingHTTPServer:
    paths.ensure()
    return _Server(("127.0.0.1", port), _make_handler(paths))


def serve(paths: Paths, port: int = 8787, open_browser: bool = True) -> None:
    httpd = make_server(paths, port)
    actual = httpd.server_address[1]
    url = f"http://127.0.0.1:{actual}/"
    print(f"skm 配置面板: {url}  (Ctrl-C 停止)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
