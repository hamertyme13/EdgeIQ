from __future__ import annotations

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.repositories.settlement_audit_repository as audit_module
import web.app as web_app
import web.application.results_service as results_service
from analytics.entry_suggestions import suggest_entries
from analytics.pickem_payouts import payout_analysis
from analytics.probabilistic_forecast import forecast_prop
from models.platform import Platform
from repository.database import Base
from repository.models.settlement_audit_model import SettlementAuditModel
from repository.repositories.settlement_audit_repository import SettlementAuditRepository
from utils.entity_normalization import canonical_matchup_key, canonical_person_key
from web.application.portfolio_service import portfolio_intelligence_payload


def _elapsed_ms(callback, iterations=1):
    started = time.perf_counter()
    for _ in range(iterations):
        callback()
    return (time.perf_counter() - started) * 1000


@pytest.mark.performance
def test_forecast_ranking_primitives_stay_within_budget():
    history = [
        {
            "actual": 15 + index % 12,
            "status": "played",
            "game_date": f"2026-06-{1 + index % 27:02d}",
            "game": "AAA@BBB",
            "team": "AAA",
        }
        for index in range(100)
    ]
    elapsed = _elapsed_ms(
        lambda: forecast_prop(
            "Player", "WNBA", "Points", 20.5,
            history=history, team="AAA", game="AAA@BBB",
        ),
        iterations=250,
    )
    assert elapsed < 750


@pytest.mark.performance
def test_payout_and_normalization_hot_paths_stay_within_budget():
    payout_ms = _elapsed_ms(
        lambda: payout_analysis([0.51, 0.57, 0.61, 0.54, 0.59], "PrizePicks", "flex"),
        1000,
    )
    normalization_ms = _elapsed_ms(
        lambda: (
            canonical_person_key("Azurá Stevens"),
            canonical_matchup_key("Minnesota Lynx vs Dallas Wings"),
        ),
        10_000,
    )
    assert payout_ms < 500
    assert normalization_ms < 750


@pytest.mark.performance
def test_advantage_ranking_stays_within_budget():
    props = [
        {
            "player": f"Player {index}",
            "team": f"T{index % 12}",
            "league": "WNBA",
            "stat": "Points",
            "line": 15.5 + index % 10,
            "projection": 17 + index % 10,
            "platform": "PrizePicks",
            "game": f"T{index % 12}@T{(index + 1) % 12}",
        }
        for index in range(80)
    ]
    elapsed = _elapsed_ms(
        lambda: suggest_entries(props, "WNBA", Platform.PRIZEPICKS, limit=5, leg_count=3),
        iterations=5,
    )
    assert elapsed < 1500


@pytest.mark.performance
def test_portfolio_and_results_reports_stay_within_budget(monkeypatch):
    entries = [
        {
            "id": index,
            "entry_mode": "real",
            "platform": "PrizePicks",
            "wager": 5,
            "props": [{
                "player": f"Player {index % 30}",
                "team": f"T{index % 10}",
                "sport": "WNBA",
                "stat": "Points",
                "direction": "Over",
                "line": 19.5,
                "game": f"T{index % 10}@T{(index + 1) % 10}",
            }],
        }
        for index in range(250)
    ]
    strategy = {
        "max_player_entries": 2,
        "max_game_entries": 3,
        "max_market_entries": 1,
        "max_player_exposure_pct": 7.5,
    }
    portfolio_ms = _elapsed_ms(
        lambda: portfolio_intelligence_payload(pending_entries=entries, bankroll=1000, strategy=strategy),
        iterations=20,
    )
    monkeypatch.setattr(results_service, "get_dashboard", lambda: {
        "bankroll_curve": list(range(500)),
        "by_sport": {},
        "by_stat": {},
        "by_platform": {},
        "entries": {},
        "monthly_profit": {},
    })
    results_ms = _elapsed_ms(results_service.performance_payload, iterations=1000)
    assert portfolio_ms < 750
    assert results_ms < 250


@pytest.mark.performance
def test_provider_cache_and_health_api_latency_stay_within_budget(monkeypatch):
    web_app._PROP_FETCH_CACHE.clear()
    monkeypatch.setattr(web_app, "_platform_prop_fetcher", lambda _platform: object())
    monkeypatch.setattr(web_app, "_platform_fetcher_cache_token", lambda _platform: 2)
    monkeypatch.setattr(
        web_app,
        "_fetch_platform_props_uncached",
        lambda platform, _fetcher: [{"player": "A", "platform": platform}],
    )
    web_app._fetch_platform_props("PrizePicks")
    cache_ms = _elapsed_ms(lambda: web_app._fetch_platform_props("PrizePicks"), iterations=1000)
    api_ms = _elapsed_ms(web_app.health, iterations=10_000)
    assert cache_ms < 150
    assert api_ms < 100


@pytest.mark.performance
def test_settlement_queue_processing_stays_within_budget(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'queue.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(audit_module, "SessionLocal", sessions)
    monkeypatch.setattr(audit_module, "initialize_database", lambda: None)
    with sessions() as session:
        session.add_all([
            SettlementAuditModel(
                entry_id=index,
                entry_prop_id=index,
                status="waiting",
                provider="ESPN",
                reason_code="final_not_available",
            )
            for index in range(1, 501)
        ])
        session.commit()

    elapsed = _elapsed_ms(lambda: SettlementAuditRepository.queue(limit=500), iterations=10)
    assert elapsed < 1000
