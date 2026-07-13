import http.client
import json
import threading

from skm.config import ToolCfg, load_config, save_config
from skm.panel import make_server


def _serve(paths):
    httpd = make_server(paths, port=0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def _req(port, method, path, obj=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = json.dumps(obj) if obj is not None else None
    headers = {"Content-Type": "application/json"} if obj is not None else {}
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def test_server_end_to_end(paths, make_skill, tmp_path):
    make_skill("uni")
    make_skill("s2")
    cfg = load_config(paths)
    cfg.tools = {"claude": ToolCfg(path=tmp_path / "claude")}
    save_config(paths, cfg)
    httpd, port = _serve(paths)
    try:
        status, body = _req(port, "GET", "/")
        assert status == 200 and b"skm" in body

        status, body = _req(port, "GET", "/api/state")
        state = json.loads(body)
        assert [s["name"] for s in state["skills"]] == ["s2", "uni"]
        assert "universal" in state and "tools" in state and "groups" in state

        status, body = _req(port, "POST", "/api/save", {
            "universal": ["uni"],
            "tools": {"claude": {"skills": [], "groups": ["coding"]}},
            "groups": {"coding": {"label": "写代码", "skills": ["s2"], "packs": []}},
        })
        assert status == 200 and json.loads(body)["ok"] is True
        c = load_config(paths)
        assert c.universal == ["uni"]
        assert c.groups["coding"].skills == ["s2"]
        assert (tmp_path / "claude" / "s2").is_symlink()   # 保存即应用

        # 非法 skill → 400,不写坏
        status, body = _req(port, "POST", "/api/save",
                            {"universal": [], "tools": {},
                             "groups": {"x": {"skills": ["ghost"]}}})
        assert status == 400
        assert "ghost" in json.loads(body)["error"]
        assert "coding" in load_config(paths).groups   # 旧配置仍在
    finally:
        httpd.shutdown()
        httpd.server_close()
