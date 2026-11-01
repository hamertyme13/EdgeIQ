# NBA Points Intelligence

NBA Points research is available from Research > Prop Research 2.0. Select NBA,
enter a player and Points, and optionally enter an exact sportsbook line.
The response extends the existing player research API with
`nba_points_intelligence`; no champion forecast, grade, recommendation, or paid
eligibility is changed by the research interface. A separate NBA Points history
integrity gate now withholds ambiguous zero-point games without verified positive
minutes or shooting attempts from both research and the existing forecast inputs; this may reduce
forecast sample size or paid eligibility, but does not introduce a new model.

## Evidence and calculations

- Uses deduplicated, played NBA Points finals from the existing ESPN, NBA API,
  Ball Don't Lie, or StatsHawk final-stat records. Missing, live, inactive,
  non-finite, future, and unverified-source rows are excluded. A zero-point
  final without positive provider-verified minutes or shooting attempts is
  withheld as participation unverified. A genuine zero-point game with either
  verified signal still counts. New ESPN NBA imports omit all-zero box-score
  rows without a participation signal; explicit DNP records remain DNP.
  Skipped NBA box-score rows are deduplicated in Data Health's provider
  rejection diagnostics with their original athlete payload and reason.
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
- The research history cutoff follows the NBA game's Eastern calendar date,
  including late tips that fall on the next UTC day. When a stored final has an
  import timestamp and a precise tipoff is supplied, historical replay
  withholds it if that timestamp is at or after tipoff; malformed timestamps
  are withheld with a reason. A date-only lookup cannot apply this time check.
  Legacy finals without an import timestamp remain visible as history, but
  cannot prove they were available before a historical game. The adjacent NBA
  Points Research forecast uses that same Eastern date-only history cutoff;
  this does not change the production recommendation forecast.
- Run `python -m scripts.backfill_nba_season_type` to preview exact current-season
  matches from cached ESPN scoreboards. The command does not fetch the network
  or change records by default. After reviewing the report and migrating the
  database, add `--apply` to persist labels. Uncached, incomplete, unlabeled,
  and ambiguous games remain untouched.
- Shows 10+, 15+, 20+, 25+, 30+, and 35+ inclusive thresholds for Last 5,
  Last 10, Last 20, the season window, home, away, and previous games against
  the selected opponent. The compact history selector shows each split's own
  confirmed/unverified season count; an empty split displays no hit rate.
  Exact custom lines use `actual >
  line`; equality is a push excluded from the decision denominator.
- Reports numerator, denominator, pushes, mean, median, population standard
  deviation, and a 95% Wilson interval for historical hit rates. The interval
  describes sampling uncertainty in past outcomes, not next-game probability.
- The Verified season tab includes only finals explicitly labeled regular
  season. The Tracked window tab retains unlabeled games with a visible count;
  an unlabeled game is never assumed to be regular season.
- The descriptive prior-five and prior-to-game season-average error checks
  use only explicitly verified regular-season finals. Unlabeled games remain
  visible in tracked history but cannot improve or worsen these baselines.
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
  Every contributing sportsbook quote must carry a reliable timestamp, and
  the returned event must match the provider offer's start time. Malformed
  quote fields fail closed. The Research pane shows the oldest contributing
  quote time; it never treats external-book prices as a verified DFS payout.
  Successful on-demand checks store an immutable, deduplicated market quote
  snapshot in a dedicated table with the provider offer identity, exact line,
  sportsbook event, contributing prices, quote time, and model version when
  available. This table is not the research-memory ledger and does not receive
  automatic win/loss attribution. A failed save is shown separately from the
  valid comparison; neither state verifies DFS payout or EV.
  Repeated exact-line checks can display up to 20 saved quotes for the same
  player, platform, game, start time, and line. The first-to-latest no-vig
  probability change is external market movement, not closing-line value,
  model edge, or a promise that the provider payout improved.
  Data Health reports the count captured over the past 24 hours and the latest
  successful quote save. This is an on-demand collection metric, not a provider
  outage alert; zero quotes may simply mean nobody ran the exact-market check.
  The Research pane can audit saved quotes against verified NBA regular-season
  Points finals. It pairs exact player, game, and Eastern game date, excludes
  stale or post-start quotes, conflicted results, and pushes, and uses the
  earliest eligible quote per player-game. It reports market Brier score and
  a paired model comparison only when an independent pregame model probability
  was saved. The audit reads at most 500 quotes from the last 45 days and
  20,000 matching finals; truncated input is reported instead of scored.
  Quotes are captured only when someone requests the exact-market check, so
  this selected sample cannot qualify a model for promotion or establish
  whole-board accuracy. It never verifies DFS payout or EV.
  The audit separates paired Brier scores by locked model version. Only a
  version with at least 30 distinct outcomes over five game dates receives a
  later-games slice, and that slice needs at least ten outcomes. This is a
  chronological descriptive check, not a trained holdout or promotion gate.
  One player-game counts once in the overall market summary but can inform
  multiple locked model versions. Version cohorts may cover different games,
  so their aggregate Brier scores are not a head-to-head model comparison.
  A separate paired check compares versions only where both captured a
  pregame probability for the same player, game, and exact Points line. It
  counts a player-game once even when multiple matching lines were saved.
  Quotes captured more than 30 minutes apart do not qualify as a paired
  comparison; the excluded count is visible in Research.
  Its later-games slice uses the same minimum evidence thresholds. The paired
  check remains selected on-demand evidence, not a promotion decision.
- A separate minutes-based challenger uses only regular-season Points finals
  paired with provider-verified Minutes from the same game. With at least five
  such games, it multiplies median minutes from the last five by aggregate
  points per minute from up to the last ten. A walk-forward comparison against
  the preceding five-game points average reports MAE and RMSE when later games
  exist. This is a simple shadow baseline, not a calibrated probability or a
  production forecast; unverified minutes and preseason games are excluded.
  The Points final itself must also come from a verified final-stat provider;
  manual entry history cannot qualify the minutes baseline. A saved pregame
  estimate remains in the prediction ledger unchanged when its result settles.
- A second research-only baseline pairs regular-season Points finals with
  provider-verified field-goal and free-throw attempts from the same game.
  Conflicting provider totals, unlabeled seasons, and unverified sources do not
  qualify. It projects from the median combined attempt count in the prior
  five games and the points-per-recorded-attempt ratio in up to ten prior
  games. This simple volume proxy is not possessions or a calibrated
  probability. A chronological check compares it with the prior-five points
  average; new pregame forecasts lock the shadow estimate for later audit.
  It does not change the champion model, recommendations, or paid eligibility.
- A rolling check predicts each game after the first five using only earlier
  results. It reports MAE and RMSE for previous-five and prior-season-average
  baselines. It does not calculate a Brier score without locked pregame
  probabilities or compare the champion on this small descriptive window.
- **Explain briefly** and **Explain in detail** run only when requested. The
  brief version is deterministic and always includes exact-line history (or
  sample size), the separate forecast status, and the no-EV caveat without
  waiting for Ollama. For the detailed version, Ollama may reorder a closed
  list of verified research facts. EdgeIQ itself writes all numerical
  statements and caveats, including the team-defense percentile's
  non-predictive meaning. If Ollama is off, slow, or produces invalid IDs,
  the facts appear in deterministic order. Explanations do not change
  forecasts, grades, or paid eligibility. Each displayed fact names
  its final-stat, model-version, team-final, or evidence-check provenance. The
  opponent-defense and pace facts link up to three exact official ESPN games
  when those URLs are present and valid. Player-final records currently lack
  exact game URLs, so their source names are shown without fabricated links.
  The links are evidence for team context, not for the model's probability.
  The explanation reads the research pane's eligible projection, so a general
  forecast withheld there because of conflicting finals cannot leak into its
  bullets.
- Head-to-head is descriptive. When at least ten NBA teams each have five
  official regular-season games before tipoff, Research ranks the opponent's
  last-ten team points allowed among those qualifying teams. Rank 1 allows the
  fewest points. The 0-100 matchup indicator is the opponent's empirical
  percentile in that same comparison (higher means more team points allowed;
  ties receive a midpoint). This is a descriptive team-defense comparison,
  not a validated player hit probability, projection adjustment, or edge.
  Sparse league coverage withholds the rank and indicator. Position-specific
  points allowed and injury effects remain unavailable without verified data.
- When stored official NBA team finals exist before tipoff, the research pane
  shows the opponent's recent team points allowed and the league sample average.
  This is team-level context, not points allowed to a position or a validated
  player projection adjustment; sparse samples are labeled accordingly. When
  those same official regular-season games include complete team box scores,
  the pane also shows a bounded estimate of opponent game possessions per
  regulation game. Invalid or missing estimates are excluded. Pace is
  descriptive context and does not alter the player projection.
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
  ledger and prospectively captured board-cohort records on demand. The daily
  shadow job now selects fresh, standard, end-to-end-trackable NBA Points
  offers for today's games from the complete provider-board archive, using
  one fixed Over line per player-game regardless of model preference. It
  stores the pregame forecast and later settles through the existing shadow
  worker. The cohort has a 120-second loop budget. Empty, stale, failed,
  timed-out, or truncated scans are not called complete. When the scheduled
  run is incomplete, it waits and retries no more often than hourly before
  10 p.m. Eastern, so late-arriving pregame boards are not silently missed.
  Data Health shows the latest cohort's candidate and
  qualified-forecast counts, including partial and no-board states.
  This does not guarantee every NBA game or player is covered when provider
  offers or final-stat matches are unavailable. The evaluator excludes legacy, unverified, duplicated,
  postgame, push, and contradictory outcomes. Versioned forecasts are scored
  against the same settled offers' exact lines and, where captured, the locked
  recent-five mean. It reports MAE, RMSE, Brier, calibration, line bands, and
  sample-depth segments. Multiple lines, directions, and platforms for one
  player-game count as one outcome per model version; the earliest eligible
  pregame forecast is retained. Overall evidence maturity counts each
  player-game once even when two model versions made forecasts. This ledger
  also includes placed entries, which remain selection-biased. Validation now
  reports prospective board and placed-entry errors separately for each model
  version, even when the same player-game appears in both; the overall total
  still counts that game once. Prospective
  board cohorts are reported separately, and overlapping player-games count
  once toward overall maturity.
  Market-prior-only board captures remain in the shadow ledger for coverage
  and settlement diagnostics, but are excluded from model accuracy. A points
  forecast needs at least five verified regular-season games for its player;
  Data Health reports when that history gate leaves a cohort unqualified and
  shows the largest verified-game count among market-prior captures. The
  board-cohort status also counts which locked forecasts had enough verified
  minutes or shot attempts for each research-only challenger. Conflicting
  NBA minutes finals, preseason minutes, and unplayed records do not qualify.
  A ready estimate is not a settled, paired outcome.
  New shadow rows explicitly store a precise UTC prediction timestamp rather
  than relying on PostgreSQL's session-local `now()` default. Older rows whose
  feature timestamp appears roughly four hours after their stored lock time
  remain excluded as suspected time-zone mismatches; this diagnostic does not
  retroactively prove or repair their pregame provenance.
  The
  locked-model view also reports settled market-prior exclusions even if no
  independently settled forecast qualifies yet.
  Once a model version has at least 30 settled prospective board offers across
  five game dates, a later-games check reserves the final 30% of game dates
  (at least ten offers). It compares the locked forecast, recent-five mean,
  and exact line on those later games. Minutes and shot-volume challenger errors
  use their own paired samples only where each pregame estimate was locked.
  Game dates and the pregame history cutoff use the game's Eastern date,
  including late tips that fall on the next UTC calendar date. A history
  snapshot through that Eastern game date is excluded as possible leakage.
  This is exploratory monitoring, not a
  trained holdout model or a promotion decision; placed entries are excluded.
  A market line is not a no-vig probability. Matchup
  difficulty, EV, and challenger-vs-champion promotion remain unavailable
  without paired, locked pregame evidence.
  A separate hourly NBA Points shadow settlement pass now checks at most 250
  prospective board forecasts against verified final stats. It bypasses the
  older general shadow backlog without changing that backlog or relaxing the
  game-completion window. Data Health reports the latest NBA-specific attempt
  separately from general shadow settlement; unresolved games remain pending
  with a reason and are retried on a later pass.

## Safe rollout and next validation

The NBA Points challengers remain research-only and do not modify recommendation
scoring or paid release gates. The separate zero-point participation integrity
gate can reduce the existing forecast's eligible history. Before using a
points-specific challenger for paid suggestions:

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
  workspace; threshold and custom-line history; pregame opponent team context
  and coverage-gated defensive comparison;
  minutes-based and shot-volume shadow baselines; exact-market comparison on request;
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
  challengers need at least five paired verified games. New NBA Points forecast
  snapshots lock versioned, shadow-only minutes and shot-volume estimates when that evidence
  exists. Prior-season rows no longer substitute for missing current-season
  NBA Points history. The existing champion forecast remains separate; the
  shadow estimate has no calibrated probability or EV.
  New prospective NBA Points board snapshots also lock the opponent's
  team-defense percentile when the comparison has at least ten teams with
  five official pregame results each. The evidence query excludes team finals
  captured after the cohort began. Settled, versioned snapshots are reported
  in descriptive matchup segments. Every fractional 0-100 indicator falls in
  exactly one segment; the report shows prospective board outcomes separately
  from placed-entry selections and compares each segment with the same offers'
  locked recent-five mean and exact line. These segments are not causal evidence,
  do not adjust the production forecast, and cannot qualify the challenger for promotion.
- **Validation:** Tests cover thresholds, pushes, custom lines, DNP and
  unfinished games, missing provider context, conflicting finals, route
  payloads, market gating, locked chronological outcomes, and Ollama fallback.
  Rolling MAE/RMSE and the locked ledger's Brier/calibration are displayed only
  when the required observations exist. No NBA points challenger promotion or
  improved paid-entry win rate has been demonstrated. Settled snapshots with a
  locked minutes or shot-volume estimate can be compared on the same offers
  against the champion, recent-five mean, and market line. Each challenger has
  its own paired count; older snapshots without the estimate remain unpaired.
  Neither shadow estimate has a calibrated exact-line probability.
- **Rollout:** Challengers remain research-only. No new recommendation score,
  entry generator, or settlement result is introduced; the participation gate
  may reduce existing NBA Points forecast sample size and paid eligibility.
  Keep challenger promotion disabled until
  independent pregame snapshots and settled holdout outcomes show improvement
  against both the champion and simple/market baselines. Before deployment,
  run migrations and the full test suite. A local Chrome Research smoke test
  completed at 390 px and 320 px viewport widths without horizontal overflow;
  the 390 px panel was widened for readability. This is not a physical-device
  or hosted-deployment verification.
