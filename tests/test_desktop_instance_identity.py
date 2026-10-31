from fastapi.testclient import TestClient

from repository.database import engine
from web.app import app
from web.build_identity import python_runtime_id, source_build_id


def test_version_identifies_only_desktop_launched_process(monkeypatch):
    monkeypatch.delenv("EDGEIQ_DESKTOP_INSTANCE", raising=False)
    assert TestClient(app).get("/api/version").json()["desktop_instance"] is False
    monkeypatch.setenv("EDGEIQ_DESKTOP_INSTANCE", "1")
    assert TestClient(app).get("/api/version").json()["desktop_instance"] is True


def test_version_exposes_current_source_build_identity():
    version = TestClient(app).get("/api/version").json()
    assert version["source_build_id"] == source_build_id()
    assert version["python_runtime_id"] == python_runtime_id()
    assert version["database_backend"] == engine.url.get_backend_name()


def test_source_build_identity_changes_when_a_source_file_changes(tmp_path):
    module = tmp_path / "web" / "sample.py"
    module.parent.mkdir()
    module.write_text("VALUE = 1\n")
    first = source_build_id(tmp_path)
    module.write_text("VALUE = 2\n")
    assert source_build_id(tmp_path) != first


def test_source_build_identity_changes_when_provider_code_changes(tmp_path):
    provider = tmp_path / "data" / "providers" / "espn.py"
    provider.parent.mkdir(parents=True)
    provider.write_text("VALUE = 1\n")
    first = source_build_id(tmp_path)
    provider.write_text("VALUE = 2\n")
    assert source_build_id(tmp_path) != first
