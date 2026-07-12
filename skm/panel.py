"""配置面板:SKILL.md 描述解析、状态构建、保存校验。HTTP 服务见文件末尾。"""
from __future__ import annotations

import json
import re
import socketserver
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import (ID_RE, Config, Scenario, load_config, missing_in_repo,
                     save_config)
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
        # 块标量:收集后续更缩进的行,直到下一个顶层 key
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


def build_state(paths: Paths, cfg: Config) -> dict:
    skills = []
    if paths.skills.exists():
        for d in sorted(paths.skills.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists():
                skills.append({"name": d.name, "description": skill_description(d)})
    state = load_state(paths)
    return {
        "skills": skills,
        "base": sorted(cfg.base),
        "packs": {n: sorted(p.skills) for n, p in sorted(cfg.packs.items())},
        "scenarios": {
            n: {"label": s.label, "packs": sorted(s.packs), "skills": sorted(s.skills)}
            for n, s in sorted(cfg.scenarios.items())
        },
        "tools": {t: (state[t].scenario if t in state else None)
                  for t in sorted(cfg.tools)},
    }


def apply_payload(paths: Paths, cfg: Config, payload: dict) -> None:
    """把面板提交的 base+scenarios 校验后写回 config。packs/tools 不动。"""
    base = list(payload.get("base", []))
    scenarios_in = payload.get("scenarios", {})
    referenced = set(base)
    new_scenarios: dict[str, Scenario] = {}
    for name, body in scenarios_in.items():
        if not ID_RE.match(name):
            raise PanelError(f"场景名 '{name}' 不合法:只允许小写字母/数字/短横线")
        packs = list(body.get("packs", []))
        skills = list(body.get("skills", []))
        for p in packs:
            if p not in cfg.packs:
                raise PanelError(f"场景 '{name}' 引用了不存在的 pack: {p}")
        referenced.update(skills)
        new_scenarios[name] = Scenario(packs=packs, skills=skills,
                                       label=body.get("label") or None)
    missing = missing_in_repo(paths, referenced)
    if missing:
        raise PanelError("以下 skill 不在中央仓: " + ", ".join(missing))
    cfg.base = base
    cfg.scenarios = new_scenarios
    save_config(paths, cfg)


_HTML = Path(__file__).parent / "panel.html"


class _Server(ThreadingHTTPServer):
    """ThreadingHTTPServer 会在 server_bind 里调 socket.getfqdn 做反向 DNS,
    某些网络下会卡数十秒。这里跳过它,直接用 host 当 server_name。"""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def _make_handler(paths: Paths):
    html = _HTML.read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 静默日志
            pass

        def address_string(self):  # 跳过反向 DNS(否则每请求卡数秒)
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
