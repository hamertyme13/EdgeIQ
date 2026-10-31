from types import SimpleNamespace

import pytest

from scripts import ensure_local_postgres as module


def test_local_postgres_is_opt_in(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "load_dotenv", lambda *_: None)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.delenv("EDGEIQ_LOCAL_POSTGRES", raising=False)
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("unexpected command"))
    module.ensure_local_postgres()


def test_cutover_marker_requires_postgres(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "load_dotenv", lambda *_: None)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / ".edgeiq_postgres_cutover").write_text("enabled")
    monkeypatch.delenv("EDGEIQ_LOCAL_POSTGRES", raising=False)
    with pytest.raises(RuntimeError, match="migrated to PostgreSQL"):
        module.ensure_local_postgres()


def test_local_postgres_rejects_other_database(monkeypatch):
    monkeypatch.setattr(module, "load_dotenv", lambda *_: None)
    monkeypatch.setenv("EDGEIQ_LOCAL_POSTGRES", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///edgeiq.db")
    with pytest.raises(RuntimeError, match="does not point"):
        module.ensure_local_postgres()


def test_local_postgres_starts_when_needed(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "load_dotenv", lambda *_: None)
    monkeypatch.setenv("EDGEIQ_LOCAL_POSTGRES", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://me@127.0.0.1:55432/edgeiq_staging")
    monkeypatch.setattr(module, "POSTGRES_DATA", tmp_path)
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0 if len(calls) > 1 else 1)

    monkeypatch.setattr(module.subprocess, "run", run)
    module.ensure_local_postgres()
    assert len(calls) == 3
    assert calls[1][-1] == "start"
