# Tennis result verification

EdgeIQ can read PrizePicks ATP/WTA/TENNIS offers, but only match-level **Aces**, **Double Faults**, and **Games Won** have an automatic tennis settlement path. Configure `SPORTRADAR_TENNIS_API_KEY` in the app environment and, if needed, set `SPORTRADAR_TENNIS_ACCESS_LEVEL=production` (default: `trial`). Do not commit the key.

The entry gate checks Sportradar Tennis v3 Daily Summaries for one exact singles matchup near the provider's start time. Aces and double faults require `coverage.sport_event_properties.detailed_serve_outcomes=true`; games won requires `scores=live` or `scores=post`. Unmatched or ambiguous matches, doubles, and other markets stay unavailable. This is **result coverage**, not proof that EdgeIQ's tennis projection is calibrated or that the exact PrizePicks offer is still live.

Settlement imports only explicit statistics from ended/closed matches. Missing stat fields are not treated as zero. Retirements and walkovers remain unresolved for review because the sportsbook's void rules can differ. The final-stat source is recorded as `sportradar_tennis_v3`.

Run `pytest -q tests/test_tennis_sportradar.py` to exercise parser, coverage, and missing-key behavior. Before treating tennis as paid-ready, validate a real PrizePicks offer against the configured Sportradar feed and settle a completed paper entry end to end. No live Sportradar credential was available during implementation, so that production check remains outstanding.
