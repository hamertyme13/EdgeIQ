from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import repository.database as database
from analytics.hierarchical_calibration import calibrate_probability
from repository.database import Base
from repository.repositories import board_offer_repository as board_module
from repository.repositories import model_rehabilitation_repository as rehabilitation_module
from repository.repositories import settings_repository as settings_module
from repository.repositories.board_offer_repository import BoardOfferRepository
from repository.repositories.leg_recommendation_snapshot_repository import LegRecommendationSnapshotRepository
from repository.repositories.model_rehabilitation_repository import ModelRehabilitationRepository


def _isolated_database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'rehabilitation.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'rehabilitation.db'}")
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(rehabilitation_module, "SessionLocal", session_local)
    monkeypatch.setattr(settings_module, "SessionLocal", session_local)
    Base.metadata.create_all(engine)
    return session_local


def test_uncalibrated_probability_is_capped_below_extreme_confidence():
    result = calibrate_probability(0.98, sport="WNBA", stat="Points", provider="PrizePicks", direction="Over", projection_source="provider", rows=[])
    assert result["probability"] == 65.0
    assert result["paid_eligible"] is False


def test_shadow_ledger_uses_daily_cohorts_and_does_not_release_unsettled(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    prop = {"player": "Player One", "sport": "WNBA", "stat": "Points", "line": 20.5, "direction": "Over", "platform": "PrizePicks", "game": "A @ B", "game_time": "2026-08-09T20:00:00Z", "confidence": 62}
    first = ModelRehabilitationRepository.queue_shadow([prop], model_version="shadow-test", target=1, cohort_date="2026-08-09")
    second = ModelRehabilitationRepository.queue_shadow([prop], model_version="shadow-test", target=1, cohort_date="2026-08-10")
    assert first["created"] == second["created"] == 1
    assert ModelRehabilitationRepository.shadow_status()["release_ready"] is False
    assert ModelRehabilitationRepository.shadow_status()["cohorts"] == 2


def test_shadow_queue_deduplicates_repeated_provider_markets(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    prop = {"player": "Player One", "sport": "WNBA", "stat": "Points", "line": 20.5, "direction": "Over", "platform": "PrizePicks", "game": "A @ B", "game_time": "2026-08-09T20:00:00Z", "confidence": 62}
    first = ModelRehabilitationRepository.queue_shadow(
        [prop, dict(prop)], model_version="shadow-test", target=None, cohort_date="2026-08-09"
    )
    second = ModelRehabilitationRepository.queue_shadow(
        [prop], model_version="shadow-test", target=None, cohort_date="2026-08-09"
    )
    assert first["created"] == 1
    assert first["queued"] == 1
    assert second["created"] == 0
    assert second["queued"] == 1


def test_recommendation_snapshots_are_immutable(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    first = ModelRehabilitationRepository.save_feed({"feed": {"platform": "PrizePicks"}, "props": [{"line": 10.5}]})
    second = ModelRehabilitationRepository.save_feed({"feed": {"platform": "Underdog"}, "props": [{"line": 11.5}]})
    history = ModelRehabilitationRepository.snapshot_history()
    assert first["snapshot_id"] != second["snapshot_id"]
    assert len(history) == 2


def test_daily_snapshot_pointers_survive_switching_provider_and_sport(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    first = ModelRehabilitationRepository.save_feed({"daily_briefing": {
        "platform": "PrizePicks", "requested_platform": "Both", "sport": "WNBA", "top_opportunities": [],
    }})
    second = ModelRehabilitationRepository.save_feed({"daily_briefing": {
        "platform": "Underdog", "sport": "NFL", "top_opportunities": [],
    }})
    assert ModelRehabilitationRepository.load_daily_feed("PrizePicks", "WNBA")["snapshot_id"] == first["snapshot_id"]
    assert ModelRehabilitationRepository.load_daily_feed("Both", "WNBA")["snapshot_id"] == first["snapshot_id"]
    assert ModelRehabilitationRepository.load_daily_feed("Underdog", "NFL")["snapshot_id"] == second["snapshot_id"]
    assert ModelRehabilitationRepository.load_daily_feed("prizepicks", "wnba")["snapshot_id"] == first["snapshot_id"]


def test_actionable_rows_receive_the_persisted_snapshot_identity(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    saved = ModelRehabilitationRepository.save_feed({
        "feed": {"platform": "PrizePicks", "purpose": "Shared actionable recommendation feed."},
        "opportunity_feed": {"opportunities": [{"player": "Player One"}]},
    }, model_version="edgeiq-test")
    history = ModelRehabilitationRepository.snapshot_history(1)[0]
    opportunity = history["payload"]["opportunity_feed"]["opportunities"][0]
    assert opportunity["recommendation_snapshot_id"] == saved["snapshot_id"]
    assert opportunity["model_version"] == "edgeiq-test"


def test_scored_feed_leg_links_immutable_offer_and_model_evidence(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    saved = ModelRehabilitationRepository.save_feed({
        "props": [{
            "player": "Player One", "sport": "WNBA", "stat": "Points",
            "line": 18.5, "direction": "Over", "platform": "PrizePicks",
            "game": "A @ B", "game_time": "2026-10-01T20:00:00Z",
            "provider_offer_id": "offer-1", "projection": 21.0,
            "confidence": 61.0, "feature_as_of": "2026-09-28T12:00:00Z",
        }],
    }, model_version="edgeiq-test")
    prop = saved["props"][0]
    assert prop["offer_snapshot_id"]
    evidence = LegRecommendationSnapshotRepository.get(prop["leg_recommendation_snapshot_id"])
    assert evidence["feed_snapshot_id"] == saved["snapshot_id"]
    assert evidence["offer_snapshot_id"] == prop["offer_snapshot_id"]
    assert evidence["projection"] == 21.0
    assert ModelRehabilitationRepository.get_snapshot(saved["snapshot_id"])["props"][0]["leg_recommendation_snapshot_id"] == prop["leg_recommendation_snapshot_id"]


def test_settled_board_result_joins_to_immutable_leg_evidence(tmp_path, monkeypatch):
    session_local = _isolated_database(tmp_path, monkeypatch)
    monkeypatch.setattr(board_module, "SessionLocal", session_local)
    game = (datetime.now(UTC) + timedelta(days=2)).replace(hour=20, minute=0, second=0, microsecond=0)
    feature_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    saved = ModelRehabilitationRepository.save_feed({"props": [{
        "player": "Player One", "sport": "WNBA", "stat": "Points",
        "line": 18.5, "direction": "Over", "platform": "PrizePicks",
        "game": "A @ B", "game_time": game.isoformat(), "provider_offer_id": "offer-1",
        "projection": 21.0, "confidence": 61.0, "feature_as_of": feature_time,
    }]}, model_version="edgeiq-test")
    BoardOfferRepository.record_many(saved["props"], "PrizePicks")
    monkeypatch.setattr(board_module.FinalStatsRepository, "find_result", lambda prop: {
        "actual": 22.0, "status": "played", "source": "espn",
        "game_date": game.date().isoformat(),
    })
    assert BoardOfferRepository.settle_pending(now=game + timedelta(hours=5))["settled"] == 1
    linked = LegRecommendationSnapshotRepository.settled_linked_rows()
    assert linked["settled_board_offers"] == 1
    assert linked["rows"][0]["snapshot_id"] == saved["props"][0]["leg_recommendation_snapshot_id"]
    assert linked["rows"][0]["actual"] == 22.0


def test_feed_freezes_exact_no_vig_market_baseline(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    now = datetime.now(UTC)
    game = now + timedelta(days=2)
    saved = ModelRehabilitationRepository.save_feed({"props": [{
        "player": "Player One", "sport": "WNBA", "stat": "Points",
        "line": 18.5, "direction": "Over", "platform": "PrizePicks",
        "game": "A @ B", "game_time": game.isoformat(), "provider_offer_id": "offer-1",
        "projection": 21.0, "confidence": 61.0,
        "decision_receipt": {"market_consensus": {
            "available": True, "source_type": "multi_book_no_vig", "stale": False,
            "book_count": 3, "timestamped_book_count": 3,
            "market_probability": 54.0, "line": 18.5,
            "direction": "Over", "oldest_update": (now - timedelta(minutes=5)).isoformat(),
            "last_update": (now - timedelta(minutes=3)).isoformat(),
            "event": {"event_id": "event-1", "commence_time": game.isoformat()},
        }},
    }]}, model_version="edgeiq-test")
    evidence = LegRecommendationSnapshotRepository.get(saved["props"][0]["leg_recommendation_snapshot_id"])
    assert evidence["market_baseline"]["probability"] == 54.0
    assert evidence["market_baseline_exclusion"] == ""


def test_new_feed_keeps_retained_section_identity_and_locks_scores(tmp_path, monkeypatch):
    from copy import deepcopy

    _isolated_database(tmp_path, monkeypatch)
    original = {
        "feed": {"platform": "PrizePicks", "sport": "WNBA"},
        "daily_briefing": {"top_opportunities": [{
            "player": "Player", "stat": "Points", "line": 18.5, "confidence": 60,
        }]},
    }
    before = deepcopy(original)
    first = ModelRehabilitationRepository.save_feed(original, model_version="score-test")
    assert original == before
    saved_prop = first["daily_briefing"]["top_opportunities"][0]
    assert saved_prop["edgeiq_score"]["snapshot_id"] == first["snapshot_id"]
    second = ModelRehabilitationRepository.save_feed({
        "feed": {"platform": "Underdog", "sport": "NFL"},
        "opportunity_feed": {"opportunities": [{"player": "Another", "stat": "Passing Yards", "line": 200}]},
    })
    retained = second["daily_briefing"]["top_opportunities"][0]
    assert retained == saved_prop
    assert second["daily_briefing"]["recommendation_snapshot_id"] == first["snapshot_id"]
    assert second["opportunity_feed"]["recommendation_snapshot_id"] == second["snapshot_id"]
    history = ModelRehabilitationRepository.snapshot_history(2)
    assert history[0]["platform"] == "Underdog"
    assert history[0]["sport"] == "NFL"
    assert history[1]["payload"]["daily_briefing"]["top_opportunities"][0] == saved_prop


def test_snapshot_automatically_queues_complete_props_for_shadow_evidence(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    saved = ModelRehabilitationRepository.save_feed({
        "feed": {"platform": "PrizePicks", "purpose": "recommendation_feed"},
        "props": [{
            "player": "College QB", "team": "AAA", "sport": "NCAAF",
            "stat": "Passing Yards", "line": 275.5, "direction": "Over",
            "platform": "PrizePicks", "game": "AAA @ BBB",
            "game_time": "2026-08-30T20:00:00Z", "confidence": 58,
        }],
    }, model_version="edgeiq-test")

    assert saved["evidence_capture"]["eligible_props"] == 1
    assert saved["evidence_capture"]["created"] == 1
    assert ModelRehabilitationRepository.shadow_rows()[0]["sport"] == "NCAAF"

    second = ModelRehabilitationRepository.save_feed({
        "props": [{
            "player": "College Receiver", "team": "BBB", "sport": "NCAAF",
            "stat": "Receiving Yards", "line": 72.5, "direction": "Over",
            "platform": "PrizePicks", "game": "AAA @ BBB",
            "game_time": "2026-08-30T20:00:00Z", "confidence": 57,
        }],
    }, model_version="edgeiq-test")
    assert second["evidence_capture"]["created"] == 1
    assert len(ModelRehabilitationRepository.shadow_rows()) == 2


def test_shadow_settlement_uses_verified_result_evidence(tmp_path, monkeypatch):
    _isolated_database(tmp_path, monkeypatch)
    ModelRehabilitationRepository._legacy_migrated = True
    ModelRehabilitationRepository.queue_shadow([{
        "player": "Player One", "sport": "WNBA", "stat": "Points", "line": 20.5,
        "direction": "Over", "platform": "PrizePicks", "game": "A @ B",
        "game_time": "2026-08-08T20:00:00Z", "confidence": 62,
    }], model_version="shadow-test", target=1, cohort_date="2026-08-08")
    monkeypatch.setattr(
        "repository.repositories.model_rehabilitation_repository.FinalStatsRepository.find_result",
        lambda _prop: {"actual": 24.0, "status": "played", "source": "ESPN public"},
    )
    result = ModelRehabilitationRepository.settle_pending()
    assert result["settled"] == 1
    assert ModelRehabilitationRepository.shadow_rows()[0]["result"] == "Win"
