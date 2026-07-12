from skm import panel
from skm.cli import main


def test_panel_command_dispatches(paths, monkeypatch):
    monkeypatch.setenv("SKM_HOME", str(paths.home))
    calls = {}

    def fake_serve(p, port=8787, open_browser=True):
        calls["port"] = port
        calls["open_browser"] = open_browser

    monkeypatch.setattr(panel, "serve", fake_serve)
    assert main(["panel", "--port", "9191", "--no-open"]) == 0
    assert calls == {"port": 9191, "open_browser": False}


def test_panel_defaults(paths, monkeypatch):
    monkeypatch.setenv("SKM_HOME", str(paths.home))
    calls = {}
    monkeypatch.setattr(panel, "serve",
                        lambda p, port=8787, open_browser=True: calls.update(
                            port=port, open_browser=open_browser))
    assert main(["panel"]) == 0
    assert calls == {"port": 8787, "open_browser": True}
