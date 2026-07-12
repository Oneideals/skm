import http.client
import json
import threading

from skm.config import load_config
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


def test_server_end_to_end(paths, make_skill):
    make_skill("s1")
    make_skill("s2")
    load_config(paths)
    httpd, port = _serve(paths)
    try:
        # 首页 HTML
        status, body = _req(port, "GET", "/")
        assert status == 200 and b"skm" in body

        # 状态接口
        status, body = _req(port, "GET", "/api/state")
        state = json.loads(body)
        assert [s["name"] for s in state["skills"]] == ["s1", "s2"]
        assert set(state["tools"]) == {"claude", "codex", "grok", "hermes"}

        # 保存
        status, body = _req(port, "POST", "/api/save", {
            "base": ["s1"],
            "scenarios": {"coding": {"label": "写代码", "skills": ["s2"], "packs": []}},
        })
        assert status == 200 and json.loads(body)["ok"] is True
        cfg = load_config(paths)
        assert cfg.base == ["s1"]
        assert cfg.scenarios["coding"].skills == ["s2"]
        assert cfg.scenarios["coding"].label == "写代码"

        # 保存非法(skill 不存在)→ 400,config 不被写坏
        status, body = _req(port, "POST", "/api/save",
                            {"base": [], "scenarios": {"x": {"skills": ["ghost"]}}})
        assert status == 400
        assert "ghost" in json.loads(body)["error"]
        assert "coding" in load_config(paths).scenarios   # 旧配置仍在,未被坏写覆盖
    finally:
        httpd.shutdown()
        httpd.server_close()
