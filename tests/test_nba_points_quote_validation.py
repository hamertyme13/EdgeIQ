from datetime import UTC, datetime, timedelta

from analytics.nba_points_quote_validation import evaluate_nba_points_quotes
from web.routers.players import nba_points_quote_validation

NOW = datetime(2026, 10, 24, 16, tzinfo=UTC)


def _quote(player="Research Guard", *, game="BOS @ NYK", line=19.5, captured="2026-10-23T16:00:00Z"):
    return {
        "player": player, "player_key": player.lower(), "platform": "PrizePicks",
        "game": game, "game_time": "2026-10-23T23:00:00Z", "line": line,
        "captured_at": captured, "oldest_quote_at": "2026-10-23T15:55:00Z",
        "market_event_id": "odds-1", "book_count": 3,
        "market_over_probability": 54.0, "market_under_probability": 46.0,
        "model_over_probability": 62.0, "model_version": "points-v1",
    }


def _final(player="Research Guard", *, actual=27, game="BOS @ NYK", source="espn"):
    return {
        "player": player, "game": game, "game_date": "2026-10-23", "actual": actual,
        "source": source, "status": "played", "season_type": "regular",
    }


def test_quote_audit_uses_one_earliest_pregame_player_game_and_paired_brier():
    duplicate = {**_quote(captured="2026-10-23T16:05:00Z"), "platform": "Underdog"}
    report = evaluate_nba_points_quotes({
        "quotes": [_quote(), duplicate], "finals": [_final(), {**_final(), "source": "nba_api"}],
    }, now=NOW)

    assert report["status"] == "exploratory"
    assert report["eligible_independent"] == 1
    assert report["excluded"]["duplicate_player_game"] == 1
    assert report["market"]["brier"] == 0.2116
    assert report["paired"]["model_brier"] == 0.1444
    assert report["paired"]["market_brier"] == 0.2116
    assert report["promotion_ready"] is False


def test_quote_audit_excludes_push_conflict_unverified_and_postgame():
    push = _quote("Push Player")
    conflict = _quote("Conflict Player")
    unverified = _quote("Unknown Player")
    postgame = _quote("Late Player", captured="2026-10-24T00:00:00Z")
    report = evaluate_nba_points_quotes({
        "quotes": [push, conflict, unverified, postgame],
        "finals": [
            _final("Push Player", actual=19.5),
            _final("Conflict Player", actual=20), _final("Conflict Player", actual=21, source="nba_api"),
            _final("Unknown Player", source="manual"), _final("Late Player"),
        ],
    }, now=NOW)

    assert report["eligible_independent"] == 0
    assert report["excluded"]["push"] == 1
    assert report["excluded"]["conflicting_final"] == 1
    assert report["excluded"]["no_verified_final"] == 1
    assert report["excluded"]["not_locked_pregame"] == 1


def test_quote_audit_does_not_score_truncated_final_scan_or_future_game():
    truncated = evaluate_nba_points_quotes({
        "quotes": [_quote()], "finals": [_final()], "finals_truncated": True,
    }, now=NOW)
    future = evaluate_nba_points_quotes({
        "quotes": [{**_quote(), "game_time": (NOW + timedelta(days=1)).isoformat()}],
        "finals": [_final()],
    }, now=NOW)
    assert truncated["status"] == "unavailable"
    assert future["excluded"]["game_not_started"] == 1


def test_quote_validation_route_uses_bounded_reader(monkeypatch):
    from repository.repositories.market_quote_repository import MarketQuoteRepository

    monkeypatch.setattr(MarketQuoteRepository, "validation_inputs", lambda: {
        "quotes": [_quote()], "finals": [_final()],
    })
    assert nba_points_quote_validation()["eligible_independent"] == 1


def test_quote_audit_separates_versions_and_uses_later_game_dates():
    quotes = []
    finals = []
    for version, probability in (("points-v1", 40.0), ("points-v2", 80.0)):
        for offset in range(5):
            day = 10 + offset
            for index in range(6):
                player = f"{version} player {offset} {index}"
                quote = _quote(player)
                quote.update({
                    "game_time": f"2026-10-{day:02d}T23:00:00Z",
                    "captured_at": f"2026-10-{day:02d}T16:00:00Z",
                    "oldest_quote_at": f"2026-10-{day:02d}T15:55:00Z",
                    "model_over_probability": probability,
                    "model_version": version,
                })
                quotes.append(quote)
                finals.append({**_final(player), "game_date": f"2026-10-{day:02d}"})
    report = evaluate_nba_points_quotes({"quotes": quotes, "finals": finals}, now=NOW)

    assert report["eligible_independent"] == 60
    assert [row["model_version"] for row in report["versions"]] == ["points-v1", "points-v2"]
    assert report["versions"][0]["model_brier"] == 0.36
    assert report["versions"][1]["model_brier"] == 0.04
    assert report["versions"][1]["later_games"] == {
        "from_game_date": "2026-10-13", "samples": 12,
        "model_brier": 0.04, "market_brier": 0.2116,
    }
    assert report["promotion_ready"] is False


def test_quote_audit_does_not_accept_source_prefix_or_small_later_slice():
    report = evaluate_nba_points_quotes({
        "quotes": [_quote("Suspicious"), _quote("Verified")],
        "finals": [_final("Suspicious", source="espn_manual"), _final("Verified")],
    }, now=NOW)

    assert report["eligible_independent"] == 1
    assert report["versions"][0]["later_games"] is None


def test_same_player_game_can_inform_two_versions_but_one_overall_market_outcome():
    first = _quote()
    second = {
        **_quote(captured="2026-10-23T16:05:00Z"),
        "oldest_quote_at": "2026-10-23T16:04:00Z",
        "model_version": "points-v2", "model_over_probability": 75.0,
    }
    report = evaluate_nba_points_quotes({"quotes": [first, second], "finals": [_final()]}, now=NOW)

    assert report["eligible_independent"] == 1
    assert report["market"]["samples"] == 1
    assert [row["model_version"] for row in report["versions"]] == ["points-v1", "points-v2"]
    assert report["versions"][1]["model_brier"] == 0.0625
    assert report["paired_versions"] == [{
        "first_version": "points-v1", "second_version": "points-v2",
        "samples": 1, "game_dates": 1, "quote_time_mismatches": 0,
        "first_brier": 0.1444, "second_brier": 0.0625,
        "later_games": None,
    }]


def test_version_pair_requires_exact_line_and_counts_player_game_once():
    quotes = [
        _quote(),
        {**_quote(captured="2026-10-23T16:05:00Z"), "oldest_quote_at": "2026-10-23T16:04:00Z",
         "line": 21.5, "model_version": "points-v2"},
    ]
    unmatched = evaluate_nba_points_quotes({"quotes": quotes, "finals": [_final()]}, now=NOW)
    assert unmatched["paired_versions"] == []

    quotes.extend([
        {**_quote(captured="2026-10-23T16:10:00Z"), "oldest_quote_at": "2026-10-23T16:09:00Z",
         "model_version": "points-v2"},
        {**_quote(captured="2026-10-23T16:15:00Z"), "oldest_quote_at": "2026-10-23T16:14:00Z",
         "line": 21.5, "model_version": "points-v1"},
    ])
    matched = evaluate_nba_points_quotes({"quotes": quotes, "finals": [_final()]}, now=NOW)
    assert matched["paired_versions"][0]["samples"] == 1


def test_version_pair_later_games_uses_same_settled_lines():
    quotes = []
    finals = []
    for offset in range(5):
        day = 10 + offset
        for index in range(6):
            player = f"Overlap player {offset} {index}"
            finals.append({**_final(player), "game_date": f"2026-10-{day:02d}"})
            for version, probability, minute in (("points-v1", 40.0, 0), ("points-v2", 80.0, 20)):
                quote = _quote(player)
                quote.update({
                    "game_time": f"2026-10-{day:02d}T23:00:00Z",
                    "captured_at": f"2026-10-{day:02d}T16:{minute:02d}:00Z",
                    "oldest_quote_at": f"2026-10-{day:02d}T16:{minute:02d}:00Z",
                    "model_version": version, "model_over_probability": probability,
                })
                quotes.append(quote)
    report = evaluate_nba_points_quotes({"quotes": quotes, "finals": finals}, now=NOW)

    assert report["eligible_independent"] == 30
    assert report["paired_versions"][0]["samples"] == 30
    assert report["paired_versions"][0]["quote_time_mismatches"] == 0
    assert report["paired_versions"][0]["later_games"] == {
        "from_game_date": "2026-10-13", "samples": 12,
        "first_brier": 0.36, "second_brier": 0.04,
    }
    assert report["promotion_ready"] is False


def test_version_pair_rejects_quotes_captured_too_far_apart():
    first = _quote()
    second = {
        **_quote(captured="2026-10-23T17:00:00Z"),
        "oldest_quote_at": "2026-10-23T16:59:00Z",
        "model_version": "points-v2",
    }
    report = evaluate_nba_points_quotes({"quotes": [first, second], "finals": [_final()]}, now=NOW)

    assert report["eligible_independent"] == 1
    assert report["paired_versions"][0]["samples"] == 0
    assert report["paired_versions"][0]["quote_time_mismatches"] == 1
