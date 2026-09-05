from pathlib import Path


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
    assert "player_identity_id: state.entrySelectedPlayerIdentityId" in javascript


def test_today_game_predictions_can_be_added_to_entry_builder() -> None:
    javascript = Path("web/static/app.js").read_text(encoding="utf-8")

    assert "Add Winner Prediction" in javascript
    assert "data-add-game-prediction" in javascript
    assert 'prediction_leg?.stat === "Game Winner"' in javascript
    assert '$("entry-mode").value = "paper"' in javascript
