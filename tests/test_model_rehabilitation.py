from analytics.hierarchical_calibration import calibrate_probability
from repository.repositories.model_rehabilitation_repository import ModelRehabilitationRepository


def test_uncalibrated_probability_is_capped_below_extreme_confidence():
    result = calibrate_probability(
        0.98,
        sport="WNBA",
        stat="Points",
        provider="PrizePicks",
        direction="Over",
        projection_source="provider",
        rows=[],
    )

    assert result["probability"] == 69.0
    assert result["paid_eligible"] is False


def test_shadow_registry_does_not_release_unsettled_predictions(monkeypatch):
    storage = {}
    monkeypatch.setattr(
        "repository.repositories.model_rehabilitation_repository.SettingsRepository.get",
        lambda key, default="": storage.get(key, default),
    )
    monkeypatch.setattr(
        "repository.repositories.model_rehabilitation_repository.SettingsRepository.set",
        lambda key, value: storage.__setitem__(key, value),
    )
    queued = ModelRehabilitationRepository.queue_shadow([{
        "player": "Player One",
        "sport": "WNBA",
        "stat": "Points",
        "line": 20.5,
        "direction": "Over",
        "platform": "PrizePicks",
        "game": "A @ B",
        "game_time": "2026-08-09T20:00:00Z",
        "confidence": 62,
    }], model_version="shadow-test", target=1)

    assert queued["created"] == 1
    assert ModelRehabilitationRepository.shadow_status()["release_ready"] is False
