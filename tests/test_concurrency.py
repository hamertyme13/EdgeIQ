from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.repositories.settlement_audit_repository as audit_module
import web.app as web_app
from repository.database import Base
from repository.repositories.settlement_audit_repository import SettlementAuditRepository
from services.data_management import backup_database
from services.operation_lock import named_operation_lock
from web.application.alert_delivery_service import deliver_alert


@pytest.mark.concurrency
def test_named_operation_lock_allows_only_one_scheduler_instance():
    entered = []
    barrier = threading.Barrier(2)

    def worker(index):
        barrier.wait()
        with named_operation_lock("concurrency-test") as acquired:
            if acquired:
                entered.append(index)
                time.sleep(0.05)
            return acquired

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(worker, range(2)))

    assert outcomes.count(True) == 1
    assert len(entered) == 1


@pytest.mark.concurrency
def test_line_write_during_database_backup_is_consistent(tmp_path):
    database = tmp_path / "source.db"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE lines (id INTEGER PRIMARY KEY, line REAL)")
        connection.executemany("INSERT INTO lines(line) VALUES (?)", [(float(index),) for index in range(100)])
        connection.commit()

    started = threading.Event()

    def write_lines():
        with sqlite3.connect(database, timeout=5) as connection:
            started.set()
            connection.executemany("INSERT INTO lines(line) VALUES (?)", [(float(index),) for index in range(100, 200)])
            connection.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(write_lines)
        started.wait(timeout=2)
        backup = backup_database(tmp_path / "backups", database_url=f"sqlite:///{database}")
        writer.result(timeout=5)

    with sqlite3.connect(backup["path"]) as connection:
        count = connection.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    assert count in {100, 200}
    assert integrity == "ok"


@pytest.mark.concurrency
def test_scheduler_and_manual_settlement_retry_do_not_duplicate_audit_rows(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'settlement.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(audit_module, "SessionLocal", sessions)
    monkeypatch.setattr(audit_module, "initialize_database", lambda: None)
    payload = {
        "entry_id": 7,
        "entry_prop_id": 19,
        "status": "waiting",
        "provider": "ESPN",
        "reason_code": "final_not_available",
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _index: SettlementAuditRepository.record(payload), range(2)))

    with sessions() as session:
        rows = session.query(audit_module.SettlementAuditModel).all()
    assert len(rows) == 1
    assert rows[0].attempt_count == 2


@pytest.mark.concurrency
def test_provider_refresh_is_coalesced_during_recommendation_load(monkeypatch):
    calls = []
    started = threading.Barrier(2)
    web_app._PROP_FETCH_CACHE.clear()
    monkeypatch.setattr(web_app, "_platform_prop_fetcher", lambda _platform: object())
    monkeypatch.setattr(web_app, "_platform_fetcher_cache_token", lambda _platform: 1)

    def uncached(platform, _fetcher):
        calls.append(platform)
        time.sleep(0.05)
        return [{"player": "A", "platform": platform}]

    monkeypatch.setattr(web_app, "_fetch_platform_props_uncached", uncached)

    def load():
        started.wait()
        return web_app._fetch_platform_props("PrizePicks")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: load(), range(2)))

    assert len(calls) == 1
    assert results[0] == results[1]


@pytest.mark.concurrency
def test_alert_delivery_uses_immutable_entry_snapshot():
    entered = threading.Event()
    release = threading.Event()
    alert = {"priority": 80, "title": "Line moved", "message": "Original entry state"}

    class Response:
        status_code = 200

    def post(*_args, **_kwargs):
        entered.set()
        release.wait(timeout=2)
        return Response()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            deliver_alert,
            alert,
            {"webhook_enabled": True, "webhook_url": "https://example.test", "min_priority": 0},
            sent_at="2026-08-11T12:00:00Z",
            post=post,
        )
        entered.wait(timeout=2)
        alert["message"] = "Changed while retrying"
        release.set()
        result = future.result(timeout=2)

    assert result["alert"]["message"] == "Original entry state"
