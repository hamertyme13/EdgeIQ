# EdgeIQ Consumer Product Upgrade

## Status

September 12, 2026. Implementation milestones 1 through 3, not completion of all fourteen
requested phases. Work is on `codex-edgeiq-alpha-hardening`, based on `a55bf3a`.
The existing game-evidence sprint is already present. No model is promoted and
no paid-entry safeguards are removed by this consumer presentation work.

## Product Goal

Make evidence, risk, line quality, and model limitations understandable without
turning EdgeIQ into an unqualified pick service. Preserve provider caching,
snapshot identity, settlement audits, paper calibration, and model governance.

## Audit and Reuse Map

| Capability | Existing implementation | Consumer gap |
| --- | --- | --- |
| Today opportunities | `web/application/briefing_service.py`, `advantage_service.py`, `recommendation_policy.py`, existing opportunity board in `app.js` | Several different internal scores; detailed proof overwhelms the shortlist |
| Player research | `web/application/player_service.py`, `research_service.py`, player routes, hit-ranking JS module | Research metrics appear simultaneously; no unified presentation score |
| Best lines | `web/routers/market.py`, `services/odds.py`, existing line-shop form | Hidden inside advanced Research; needs a focused comparison workspace |
| Entry analysis | `analytics/card_probability.py`, `correlation.py`, entry/portfolio services | Needs a compact summary of existing independent and adjusted probabilities |
| Games | game intelligence application service, game routers, `js/games.js` | Keep challenger results visibly distinct from market baseline |
| Model performance | results service, versioned prediction repositories, `js/model-version-evaluation.js` | Consumer segments and sample warnings need a unified view |
| Beta | beta service/router and `js/beta.js` | Existing auth/attribution should support a shorter preference-led onboarding |
| Alerts | alert delivery service and existing notification drawer | Add event-specific preferences without a parallel delivery system |
| Navigation | main HTML, UI shell, Core/Model Lab toggle | Players and Best Lines still require a safe navigation migration |

The major application areas, analytics modules, repository models, repositories,
services, and test layout were inventoried before edits. Existing calculations
are reused rather than replicated in JavaScript. Duplicate snapshot stamping
was removed from `web/app.py`; snapshot assembly now uses one shared service.

## Implemented: EdgeIQ Score v1

`analytics/opportunity_score.py` is a pure, bounded presentation function.
It performs no provider requests, database scans, settlement writes, or model
training. It never authorizes an entry or modifies its forecast.

Input probabilities are percentages, consistent with the existing decision
receipt. The formula is:

- Model: 40% of the decision-receipt probability, falling back to confidence.
- Data quality: 25% of the existing 0-100 quality score.
- Player history: 15% of `min(100, 5 * comparable games)`. This is player-history
  coverage, NOT a claim that twenty games qualify a model segment.
- Market: 20% of `clamp(50 + 5 * (model probability - exact-line market
  probability), 0, 100)`. Missing comparison data contributes zero, not a
  fabricated neutral market probability.
- Existing push risk subtracts up to ten points.
- An explicitly supplied correlation-risk score subtracts up to ten points.
  No correlation is inferred from unrelated fields or recomputed in the UI.

Scores are bounded to 0-100, with labels Elite (90+), Strong (80+), Watch (70+),
Marginal (60+), and Pass (below 60). This initial formula is transparent product
presentation, not an empirically validated predictor of profitability.

A score is capped at 59 when probability or quality is invalid, quality is
below 60, comparable history is below twenty games, the forecast is not paid
eligible, the existing recommendation policy has not explicitly approved paid
use, or timestamped evidence is missing/future/stale. Freshness requires an
aware timestamp no more than thirty minutes old; an explicit expired/stale
state also blocks. A missing market comparison caps the score at 79.

The policy and model-release gates remain authoritative. A high score cannot
override them, authorize a card, verify a payout, or imply guaranteed returns.
Missing matchup, role, injury, and calibration metrics receive no invented
positive contribution. Their existing evidence-policy restrictions still apply.

Responses include version, score, label, components, weights, penalties,
restrictions, missing evidence, sample warning, and a plain-language summary.
Zero is preserved; NaN, infinity, booleans, and invalid values fail closed.

## API Integration

No new endpoints. Existing payloads receive additive `edgeiq_score` fields:

- `/api/daily-briefing`: top opportunity rows.
- `/api/dashboard/advantage-center`: opportunity feed rows.
- `/api/players/{player}/research`: the selected recommendation, only when its
  line equals the research line. An averaged or manually changed research line
  must not inherit the score of a different offer.

`services/recommendation_snapshot.py` stores scores on newly captured props in
the existing immutable snapshot JSON. Each score has a version, capture time,
snapshot ID, and SHA-256 fingerprint of the offer identity and scoring inputs.
The response presenter reuses a stored score only when its snapshot ID and
input fingerprint still match. Legacy or changed offers receive response-time
scores without a claimed historical snapshot ID. No older snapshots are rewritten.

Snapshot saves deep-copy the caller's data. Previously cached sections keep
their original snapshot IDs and scores when another feed is saved. Previously,
the merge re-stamped those retained sections as if they were newly produced.
Only newly supplied data is submitted to shadow capture. The Daily Briefing and
opportunity-feed builders now return the persisted, stamped sections rather
than separately assembling and stamping a second response.

Response-time freshness is separate from recorded scores. The board marks
expired or unverified source timestamps and disables selection until refresh;
the historical score remains unchanged. A locked score is labeled Recorded.
Score-bucket outcome evaluation still requires a verified linkage to independently
settled outcomes; immutable score storage alone is not proof of predictive skill.

## Player Detail and Design

Opportunity rows show a compact numeric score and label in place of decorative
stars. Their existing Proof action includes the score's meaning and limitation.
The research overview shows score and season assessment, then six native
keyboard-accessible expandable sections:

1. Recent form and hit rankings.
2. Projection and uncertainty.
3. Matchup and game context.
4. Game logs.
5. Market and recorded lines.
6. Evidence and limitations.

The score has an expandable component/penalty explanation. Research citations
show source, capture time, and current/expired status. Missing exact-line
probability says Unavailable instead of the old misleading 50% default.
The current research model-performance section is not yet redesigned.

`js/opportunity-score.js` only renders server results and escapes text. It does
not calculate probabilities or score weights. CSS is scoped to the new score
and research sections, with wrapping and touch-size summaries. Static asset
versions and the service-worker shell list include the new module.

## Next Milestones / Deferred Work

### Daily Agent Coverage

The confirmed-provider pipeline now reports actual retrieved, scheduled-today,
eligible, analyzed, accepted, deferred, outside-today, eligibility-rejected, and
analysis-rejected counts. Previously every retrieved row was labeled analyzed,
and deferred rows were included in rejections. The extracted
`web/application/daily_agent_service.py` preserves the existing analysis budget
and selection callbacks. Today stores and displays these counts in its snapshot.
Shortlist paper/paid readiness is labeled separately because those checks operate
on a different, already-selected pool. Legacy snapshots show coverage unavailable
instead of fabricated zeros. Counts apply to the selected provider, not all
providers tried during fallback. Shared-feed consolidation remains the next step.

Advantage Center now consumes the saved Today snapshot instead of invoking the
command-center recommendation scan. It preserves opportunity order, scores,
and snapshot IDs. Provider and sport must match; snapshots older than thirty
minutes, future-dated, or from a prior Eastern calendar day are not reused.
The page explicitly asks for a Today refresh when no matching snapshot exists.
Other diagnostics (CLV, provider health, watchlist, bankroll) retain their existing
services. Remaining generator/feed consumers still need migration; this is not
yet an app-wide consolidation. Four regression tests cover scope, age,
midnight rollover, immutable response copies, and prevention of independent scans.

September 13 validation: 674 tests passed; Ruff, JavaScript syntax checks, and
application/router/schema mypy checks passed. Fourteen desktop/mobile browser
captures passed. No production database repair or model promotion was performed.

### Read-Only Opportunity Feed Migration

`/api/market/opportunity-feed` now reads the matching Today snapshot through
`shared_opportunity_feed`. It no longer runs EV/timing/watchlist scans, creates
a second recommendation snapshot, or queues shadow evidence on a read request.
Order, offer identity, and policy fields are preserved. Response-time scoring
uses the same presenter as Advantage Center. Stale/wrong-scope snapshots return
an explicit refresh message and no opportunities.

API behavior change: `min_ev` defaults to null (no EV filter). When explicitly
provided, only finite values with `expected_value_verified: true` can pass.
Existing Today rows without that evidence remain visible in the unfiltered feed
but cannot pass EV filters. The legacy `odds` argument is retained for client
compatibility and explicitly marked `odds_applied: false`; assumed prices do not
rewrite locked model forecasts. This does not claim that verified offer-specific
EV is currently populated for all rows. The old feed's independent cache and
three duplicate row-building helpers were removed from `web/app.py`.

Generators still use their existing candidate and live-validation workflows;
this milestone does not restrict them to Today's small displayed shortlist.
Validation: 676 tests passed after cleanup;
configured mypy passed across 82 files and Ruff passed. No frontend changes or migrations
were required for this feed migration.

### Provider/Sport Snapshot Retention

September 13: Daily scans now maintain provider-and-sport-specific snapshot
pointers in the existing settings table. Pointers contain only immutable
snapshot IDs; reads use the existing unique snapshot-ID index. Saving a scan
for NFL/Underdog no longer displaces the WNBA/PrizePicks snapshot for its
consumers. Both requested and explicitly selected fallback provider scopes are
recorded. Legacy scopes without a pointer fall back to the compatibility feed,
then undergo the same strict scope and freshness validation. No schema migration
or production backfill is required. One new regression covers provider/sport
switching and case-normalized pointer lookup.

Publication validation: 677 tests passed; Ruff passed; configured mypy passed
across 82 files. The accumulated change preserves the local database backup
outside Git. The full consumer-upgrade roadmap is still in progress.

### Best Lines Milestone Delivered

Best Lines is now a primary desktop/mobile destination, available in Core mode.
The existing line-shop form is moved, not duplicated. Its player/stat/sport/
platform inputs remain shared with Research, and optional manual odds remain
available with explicit user-entered, unverified labeling. DraftKings Pick6 is
included. The module has a busy state, duplicate-submit prevention, a bounded
20-second browser wait, and a readable failure/empty state.

New endpoint: `GET /api/market/best-lines`, backed by the existing line-shop
dependency and `web/application/best_lines_service.py`. Comparison badges use
standard offers for the same sport/stat/matchup/start time, with at least two
providers. Over chooses the lowest threshold; Under the highest. Ties are shown.
Adjusted, premium, direction-restricted, and missing-identity rows remain visible
without a best-threshold badge. No payout-equivalence or live-availability claim
is made. Comparing thresholds is not recommending an entry.

This milestone uses provider snapshots, not a new just-in-time availability
check. It does not yet include multi-player browsing, minimum-edge/score filters,
or automatic transfer to Entry Builder. The existing line-shop backend still
performs analysis and market lookups; client timeout bounds waiting, not server
work. No extra provider queries were added on top of that existing path.

Added `web/static/js/best-lines.js` and `tests/test_best_lines.py`; modified market
router, shell navigation, service-worker assets, scoped styles, and browser checks.
Five tests cover directional ranking, ties, adjusted restrictions, different
games/start times, missing identity, invalid lines, and equivalent timezone offsets.

1. **Complete shared snapshot presentation:** extend the stored-score presenter
   to every remaining generator/recommendation surface, and add honest Daily
   Agent filtering counts at the actual pipeline stages. Do not
   claim the nine-row shortlist represents the complete scanned board.
2. **Best Lines follow-through:** add snapshot-backed browsing and score/edge
   filters, bounded server-side comparison work, and verified live payout evidence.
3. **Player workspace:** finish overview metadata, recent-15 coverage, source
   links, and comparable-market model performance. Keep unavailable fields
   explicit rather than estimating them for visual completeness.
4. **Entry summary:** present existing simulation output, correlated pairs and
   exposure, with independent versus correlation-adjusted probability. Preserve
   the Monte Carlo implementation; never substitute naive multiplication.
5. **Track record:** use locked, independently settled chronological predictions;
   segment by sport/provider/stat/direction/model. Score segments must join the
   stored score version to independent outcomes. Show small samples and only verified ROI.
6. **Consumer navigation:** Today, Games, Players, Best Lines, Entries, Results;
   advanced/admin tools under More. Test all deep links before removing old tabs.
7. **Notifications:** add preferences for high-score opportunities, line/role/
   injury/projection changes, entry risk, settlement, and model updates through
   existing channels. No new notification triggers were enabled in these milestones.
8. **Beta onboarding:** reuse sessions and tester attribution for sport/platform/
   risk preferences and responsible-use acknowledgment. Do not activate billing.

The next sprint should complete shared snapshot consumers and Daily Agent stage
counts, before adding more scoring inputs or a separate agent engine.

## Tests and Operations

Added files: `analytics/opportunity_score.py`,
`services/recommendation_snapshot.py`,
`web/application/opportunity_presentation.py`,
`web/static/js/opportunity-score.js`, `tests/test_opportunity_score.py`, and this
document. Modified files: the CI workflow, model rehabilitation repository and
tests, visual regression script, `web/app.py`, the advantage/briefing/player
routers, main frontend JS/CSS/HTML, service worker, and static version module.

- 36 new tests cover formula, boundaries, missing evidence, penalties, invalid
  numbers, zero probability, cache immutability, route integration, and exact-line
  research score identity, locked-score reuse, stale presentation, preservation
  of retained snapshot sections, and caller immutability.
- Browser regression now additionally exercises populated research with all
  sections collapsed and expanded on desktop and mobile, using explicit fixture
  data rather than live recommendations.
- Run Ruff, the workflow's complete mypy list, pytest, JavaScript syntax checks,
  and the visual regression script. Browser checks use an isolated test database.
- No database schema changes, migrations, environment variables, or additional
  provider/API costs. No edits to the user's database backup.
- Results: 668 pytest tests passed, including the UTC-clock and Best Lines
  regressions; Ruff passed; configured mypy scope passed across 80 source files.
  Browser validation covers populated research and Best Lines on desktop/mobile,
  with final counts recorded in the task report.

Hosted CI is not claimed green by local validation. The prior sprint observed a
GitHub billing lock; that external account condition was not changed here.
