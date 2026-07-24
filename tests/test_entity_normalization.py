from utils.entity_normalization import canonical_matchup_key, canonical_person_key
from repository.repositories.final_stats_repository import _player_name_matches


def test_person_key_ignores_accents_and_punctuation():
    assert canonical_person_key("Azura Stevens") == canonical_person_key("Azurá Stevens")
    assert canonical_person_key("A.J. Brown") == canonical_person_key("AJ Brown")
    assert _player_name_matches(canonical_person_key("Azura Stevens"), "Azurá Stevens") is True


def test_matchup_key_ignores_home_away_order_and_aliases():
    aliases = {"NYL": "NY", "LVA": "LV"}

    assert canonical_matchup_key("NYL vs LVA", aliases) == canonical_matchup_key("LVA@NYL", aliases)
