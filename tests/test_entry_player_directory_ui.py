from pathlib import Path

from repository.repositories.board_offer_repository import BoardOfferRepository
from repository.repositories.player_identity_repository import PlayerIdentityRepository


def test_entry_builder_requires_sport_before_player_lookup() -> None:
    html = Path("web/static/index.html").read_text(encoding="utf-8")
    javascript = Path("web/static/app.js").read_text(encoding="utf-8")

    sport_position = html.index('id="prop-sport"')
    player_position = html.index('id="prop-player"')
    assert sport_position < player_position
    assert 'id="entry-player-options"' in html
    assert 'id="prop-player" list="entry-player-options"' in html
    assert "loadEntryPlayerDirectory" in javascript
    assert "/api/players/directory" in javascript
    assert "entryPlayerProviderLabel" in javascript
    assert "player_identity_id: state.entrySelectedPlayerIdentityId" in javascript


def test_today_game_predictions_can_be_added_to_entry_builder() -> None:
    javascript = Path("web/static/app.js").read_text(encoding="utf-8")

    assert "Add Winner Prediction" in javascript
    assert "data-add-game-prediction" in javascript
    assert 'prediction_leg?.stat === "Game Winner"' in javascript
    assert '$("entry-mode").value = "paper"' in javascript


def test_player_directory_includes_current_provider_board_players() -> None:
    BoardOfferRepository.record_many([{
        "player": "Directory Board Player",
        "league": "NCAAF",
        "team": "TEX",
        "stat": "Passing Yards",
        "line": 250.5,
        "direction": "Over",
        "provider_player_id": "directory-player-1",
        "game": "TEX @ OSU",
        "game_time": "2026-09-05T19:00:00Z",
    }], "DraftKings Pick6")

    matches = PlayerIdentityRepository.search("NCAAF", "Directory Board", 20)

    assert len(matches) == 1
    assert matches[0] == {
        "id": matches[0]["id"],
        "name": "Directory Board Player",
        "sport": "NCAAF",
        "team": "TEX",
        "source": "verified_history",
        "provider": "",
        "provider_player_id": "",
        "provider_aliases": [{
            "provider": "draftkingspick6",
            "provider_player_id": "directory-player-1",
            "name": "Directory Board Player",
        }],
    }
