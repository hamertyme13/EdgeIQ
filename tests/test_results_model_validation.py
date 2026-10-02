from __future__ import annotations

from repository.repositories.board_offer_repository import BoardOfferRepository
from web.application import results_service
from web.routers.results import complete_board_evidence


def test_core_backtest_does_not_scan_complete_board(monkeypatch):
    monkeypatch.setattr(results_service.EntryRepository, "all", lambda: [])
    monkeypatch.setattr(results_service.PredictionLedgerRepository, "backfill_legacy_quarantine", lambda: 0)
    monkeypatch.setattr(results_service.PredictionLedgerRepository, "evidence_rows", lambda **kwargs: [])
    monkeypatch.setattr(results_service.PredictionLedgerRepository, "summary", lambda: {})
    monkeypatch.setattr(results_service.BetRepository, "get_all", lambda self: [])
    monkeypatch.setattr(results_service, "backtest_summary", lambda *args, **kwargs: {"validation_readiness": {}})
    monkeypatch.setattr(results_service, "grouped_rolling_validation", lambda rows: {})
    monkeypatch.setattr(results_service, "validation_readiness", lambda *args, **kwargs: {})
    monkeypatch.setattr(results_service.ModelRehabilitationRepository, "shadow_status", lambda *args, **kwargs: {})
    monkeypatch.setattr(BoardOfferRepository, "evidence_report", lambda: (_ for _ in ()).throw(AssertionError("board scan")))

    assert results_service.backtest_payload({})["shadow_evaluation"] == {}


def test_complete_board_evidence_remains_available_separately(monkeypatch):
    monkeypatch.setattr(BoardOfferRepository, "evidence_report", lambda: {"coverage": {"independent_offers": 42}})

    assert complete_board_evidence()["coverage"]["independent_offers"] == 42
