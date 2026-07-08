from web.app import EntryPayload, EvPayload, analyze_entry, analyze_ev, health


def test_web_health_endpoint():
    assert health() == {"ok": True}


def test_web_ev_endpoint():
    body = analyze_ev(EvPayload(odds=-110, probability=55))

    assert body["recommendation"]["grade"] == "B"
    assert body["expected_value"] == 5.0


def test_web_entry_analysis_auto_projects_missing_projection():
    body = analyze_entry(
        EntryPayload.model_validate(
            {
            "platform": "PrizePicks",
            "props": [
                {
                    "player": "A",
                    "team": "AAA",
                    "sport": "WNBA",
                    "stat": "Points",
                    "line": 20.5,
                    "trending_count": 100000,
                },
                {
                    "player": "B",
                    "team": "BBB",
                    "sport": "WNBA",
                    "stat": "Assists",
                    "line": 7.5,
                    "trending_count": 90000,
                },
            ],
            }
        )
    )

    props = body["entry"]["props"]
    assert all(prop["auto_projected"] for prop in props)
    assert all(prop["projection"] > prop["line"] for prop in props)
