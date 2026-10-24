# NBA Points Intelligence

NBA Points research is available from Research > Prop Research 2.0. Select NBA,
enter a player and Points, and optionally enter an exact sportsbook line.
The response extends the existing player research API with
`nba_points_intelligence`; no champion forecast, grade, recommendation, or paid
eligibility is changed.

## Evidence and calculations

- Uses deduplicated, played NBA Points finals from the existing ESPN, NBA API,
  Ball Don't Lie, or StatsHawk final-stat records. Missing, live, inactive,
  non-finite, future, and unverified-source rows are excluded.
- NBA Points research reads bounded raw final-stat rows separately from the
  shared deduplicated history. Identical multi-source finals count once;
  conflicting point totals, conflicting season labels, missing matchup IDs,
  and implausible totals are withheld with visible exclusion counts. Existing
  stored rows are preserved for diagnosis, with source counts and the latest
  stored-final timestamp in the API. An ingest that already overwrote a row
  cannot be reconstructed by this screen. This research-only screen does
  not alter settlement or the production recommendation feed.
- If raw stored finals disagree on points or season type, the NBA research pane
  withholds its forecast and exact-line probability even when the separate
  production forecast exists. The production forecast and recommendation
  gates are not changed by this research safeguard.
- Uses the tracked NBA season window beginning September 15. ESPN finals now
  retain explicit season labels when supplied; known preseason and postseason
  games are excluded. Legacy rows and feeds without a season label remain in
  the window but are counted as unverified, so it is **not** necessarily a
  regular-season-only statistic.
- Run `python -m scripts.backfill_nba_season_type` to preview exact current-season
  matches from cached ESPN scoreboards. The command does not fetch the network
  or change records by default. After reviewing the report and migrating the
  database, add `--apply` to persist labels. Uncached, incomplete, unlabeled,
  and ambiguous games remain untouched.
- Shows 10+, 15+, 20+, 25+, 30+, and 35+ inclusive thresholds for Last 5,
  Last 10, Last 20, and the season window. Exact custom lines use `actual >
  line`; equality is a push excluded from the decision denominator.
- Reports numerator, denominator, pushes, mean, median, population standard
  deviation, and a 95% Wilson interval for historical hit rates. The interval
  describes sampling uncertainty in past outcomes, not next-game probability.
- The Verified season tab includes only finals explicitly labeled regular
  season. The Tracked window tab retains unlabeled games with a visible count;
  an unlabeled game is never assumed to be regular season.
- Scoring variability is the last-20 standard deviation divided by mean;
  lower values indicate less relative variation. It is not a probability.
- The existing verified-history forecast is shown separately from historical
  rates. Market-prior forecasts do not produce a validated points probability
  in this pane. The pane never computes EV without an exact price.
- An optional **Check exact market** action uses the existing The Odds API
  integration only for a current provider offer with the same player, game,
  and Points line. Paired Over/Under prices produce an external-book no-vig
  comparison when quote timestamps are within 30 minutes. A forecast from
  another game or a market-prior forecast is not compared. The gap is research
  context, not an EdgeIQ edge; DFS payout and EV remain unverified.
- A separate minutes-based challenger uses only regular-season Points finals
  paired with provider-verified Minutes from the same game. With at least five
  such games, it multiplies median minutes from the last five by aggregate
  points per minute from up to the last ten. A walk-forward comparison against
  the preceding five-game points average reports MAE and RMSE when later games
  exist. This is a simple shadow baseline, not a calibrated probability or a
  production forecast; unverified minutes and preseason games are excluded.
- A rolling check predicts each game after the first five using only earlier
  results. It reports MAE and RMSE for previous-five and prior-season-average
  baselines. It does not calculate a Brier score without locked pregame
  probabilities or compare the champion on this small descriptive window.
- **Explain briefly** and **Explain in detail** run only when requested. Ollama
  may reorder a closed list of verified research facts; EdgeIQ itself writes
  all numerical statements and caveats. If Ollama is off, slow, or produces
  invalid IDs, the same facts appear in deterministic order. Explanations do
  not change forecasts, grades, or paid eligibility.
- Head-to-head is descriptive. Opponent defensive ranking, position-specific
  points allowed, injury effect, and a 0-100 matchup score remain unavailable
  until verified pregame data and a chronologically validated method exist.
- When stored official NBA team finals exist before tipoff, the research pane
  shows the opponent's recent team points allowed and the league sample average.
  This is team-level context, not points allowed to a position or a validated
  player projection adjustment; sparse samples are labeled accordingly.
- The desktop scheduler collects a bounded NBA team-final slice daily at 05:30
  Eastern while the app is running. The collection preserves official ESPN
  regular/preseason/postseason labels, retries failures, and uses an operation
  lock so a Games-page scan cannot overlap the scheduled run. A versioned
  one-time pass recaptures the previous seven days when older evidence lacks
  season labels. Research uses only explicitly regular-season games; older
  unlabeled audit evidence remains stored but is not used for opponent defense.
- Evidence collected after a game cannot be treated as pregame evidence for
  a historical forecast. It can inform future research, but chronological
  model evaluation needs separately locked pregame snapshots.
- **View locked model record** reads a bounded slice of NBA Points prediction
  ledger records on demand. It excludes legacy, unverified, duplicated,
  postgame, push, and contradictory outcomes. Versioned forecasts are scored
  against the same settled offers' exact lines and, where captured, the locked
  recent-five mean. It reports MAE, RMSE, Brier, calibration, line bands, and
  sample-depth segments. A market line is not a no-vig probability. Matchup
  difficulty, EV, and challenger-vs-champion promotion remain unavailable
  without paired, locked pregame evidence.

## Safe rollout and next validation

This is research-only. It does not modify the recommendation feed or paid
release gates. Before using a points-specific model for paid suggestions:

1. Backfill trustworthy season-type labels for legacy finals and capture
   verified opponent defense and pace with timestamps.
2. Persist immutable pregame NBA points forecasts and settle them against
   independent final results.
3. Compare MAE, RMSE, Brier score, and calibration with the current champion,
   a recent-average baseline, and the exact market line on chronological
   holdout games.
4. Add exact over/under prices and provider payout evidence before showing EV.
5. Expand the existing Ollama grounding tests to cover threshold-language
   mistakes and make source-linked explanations available directly from the
   points pane. Ask EdgeIQ already receives the structured history fact and
   falls back to deterministic language when Ollama is unavailable.

## Delivery status (October 2026)

- **Implemented:** NBA Points analysis in the existing player Research API and
  workspace; threshold and custom-line history; pregame opponent team context;
  a minutes-based shadow baseline; exact-market comparison on request;
  bounded locked-prediction validation; concise/detailed grounded explanations;
  raw-final conflict screening; and persisted research evidence containing
  provenance and exclusion counts.
- **Primary files:** `web/application/nba_points_intelligence.py`,
  `web/application/nba_points_market.py`,
  `web/application/nba_points_explanation.py`,
  `analytics/nba_points_validation.py`, `web/application/research_service.py`,
  `web/routers/players.py`, `web/static/js/player-workspace.js`, and
  `repository/repositories/final_stats_repository.py`. The related tests are
  `tests/test_nba_points_*.py`, `tests/test_research_evidence.py`, and the NBA
  Research cases in `tests/test_web_api.py`.
- **Data sources:** Existing stored ESPN/NBA API/Ball Don't Lie/StatsHawk
  player finals, official ESPN team scores, captured provider offers, and
  on-demand paired odds when available. Missing results and prices are not
  synthesized. A source name alone does not prove a row was available before
  a particular historical game.
- **Model assumptions:** The September-to-present NBA season window is
  descriptive, unlabeled season types remain unverified, head-to-head and team
  points allowed are context rather than causal adjustments, and the minutes
  challenger needs at least five paired verified games. The existing champion
  forecast remains separate; research history and an external no-vig line do
  not establish a profitable DFS entry.
- **Validation:** Tests cover thresholds, pushes, custom lines, DNP and
  unfinished games, missing provider context, conflicting finals, route
  payloads, market gating, locked chronological outcomes, and Ollama fallback.
  Rolling MAE/RMSE and the locked ledger's Brier/calibration are displayed only
  when the required observations exist. No NBA points challenger promotion or
  improved paid-entry win rate has been demonstrated.
- **Rollout:** Research-only. No recommendation score, entry generator,
  settlement result, or paid eligibility is changed. Keep this boundary until
  independent pregame snapshots and settled holdout outcomes show improvement
  against both the champion and simple/market baselines. Before deployment,
  run migrations, the full test suite, and a fresh desktop/mobile Research
  smoke test; the current local browser check covered desktop only.
