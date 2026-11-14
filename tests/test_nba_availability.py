from datetime import date

import pytest

from data.providers.nba_availability import exact_out_match, exact_report_match, parse_report_pages, report_day
from scripts.reconcile_nba_shadow_availability import confirmed_exclusion


def test_only_official_dated_pdf_urls_are_accepted():
    url = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-10_08_30PM.pdf"
    assert report_day(url) == date(2026, 11, 10)
    with pytest.raises(ValueError):
        report_day("https://example.com/referee/injury/Injury-Report_2026-11-10_08_30PM.pdf")


def test_layout_parser_tracks_date_matchup_and_split_player_name():
    page = "\n".join(reversed([
        "11/10/2026    07:30 (ET)    MIL@NYK    Milwaukee Bucks    Herro, Tyler    Out    Injury",
        "                              New York Knicks    Hart,    Josh    Out    Illness",
        "            MIA@UTA    Utah Jazz    Markkanen,   Lauri    Out    Injury",
        "            NOP@GSW    New Orleans Pelicans    Murphy    III,Trey    Out    Injury",
        "11/11/2026    BOS@NYK    Some Player, One    Out    Injury",
    ]))
    rows = parse_report_pages([page], report_date=date(2026, 11, 10), source_url="official")
    assert [(row["player"], row["game"]) for row in rows] == [
        ("Tyler Herro", "MIL@NYK"), ("Josh Hart", "MIL@NYK"),
        ("Lauri Markkanen", "MIA@UTA"),
        ("Trey Murphy III", "NOP@GSW"),
    ]


def test_out_match_requires_exact_date_player_game_and_completed_game_without_final():
    rows = [{"player": "Josh Hart", "game": "MIL@NYK", "game_date": "2026-11-10",
             "status": "Out", "source_url": "official"}]
    offer = {"player": "Josh Hart", "game": "MIL @ NYK", "game_day": "2026-11-10"}
    assert exact_out_match(offer, rows) == rows[0]
    assert confirmed_exclusion(offer, rows, {"MIL@NY"}, None) == rows[0]
    assert confirmed_exclusion(offer, rows, set(), None) is None
    assert confirmed_exclusion(offer, rows, {"MIL@NY"}, {"actual": 8}) is None
    assert exact_out_match({**offer, "game_day": "2026-11-11"}, rows) is None
    assert exact_out_match({**offer, "player": "Other Player"}, rows) is None
    questionable = [{**rows[0], "status": "Questionable"}]
    assert exact_report_match(offer, questionable) == questionable[0]
    assert exact_out_match(offer, questionable) is None
