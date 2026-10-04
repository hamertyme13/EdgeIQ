from fastapi.testclient import TestClient

from web.app import app


def test_version_identifies_only_desktop_launched_process(monkeypatch):
    monkeypatch.delenv("EDGEIQ_DESKTOP_INSTANCE", raising=False)
    assert TestClient(app).get("/api/version").json()["desktop_instance"] is False
    monkeypatch.setenv("EDGEIQ_DESKTOP_INSTANCE", "1")
    assert TestClient(app).get("/api/version").json()["desktop_instance"] is True
