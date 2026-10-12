from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

import repository.repositories.prediction_ledger_repository as ledger_module
from repository.models.prediction_record_model import PredictionRecordModel
from repository.repositories.prediction_ledger_repository import PredictionLedgerRepository


def test_calibration_rows_only_reads_settled_nonlegacy_fields(db_session, monkeypatch):
    monkeypatch.setattr(ledger_module, "SessionLocal", sessionmaker(bind=db_session.connection()))
    monkeypatch.setattr(PredictionLedgerRepository, "_ensure_schema", lambda: None)
    for index, (sport, outcome, legacy) in enumerate((
        ("WNBA", "Win", False),
        ("WNBA", "", False),
        ("WNBA", "Loss", True),
        ("MLB", "Loss", False),
    ), start=1):
        db_session.add(PredictionRecordModel(
            entry_id=index, entry_prop_id=900000 + index,
            independent_market_key=f"market-{index}", offer_key=f"offer-{index}",
            player=f"Player {index}", sport=sport, stat="Points", direction="Over",
            platform="PrizePicks", line=10.5, projection=12.0, probability=61.0,
            model_version="test", outcome=outcome, legacy_quarantined=legacy,
            feature_snapshot="large private feature payload",
            predicted_at=datetime.now(UTC),
        ))
    db_session.flush()

    rows = PredictionLedgerRepository.calibration_rows("WNBA")

    assert [row["independent_market_key"] for row in rows] == ["market-1"]
    assert rows[0]["result"] == "Win"
    assert "feature_snapshot" not in rows[0]
