# EdgeIQ Consumer Product Upgrade

Living status: September 20, 2026. The consumer reset is **not complete**.

## Completed

- EdgeIQ Score remains presentation-only; policy and release gates are authoritative.
- Best Lines initial single-player threshold comparison is present, not verified EV.
- Daily Agent stage counts, immutable scores, and provider/sport snapshot retention.
- Today, Advantage Center and read-only opportunity feed share saved recommendations.
- Incremental season updates and verified, deduplicated prop win history.
- Visible game borders and responsive grouping.
- Existing fixes checkpointed as 0482d52; origin/main 566db4e merged as 1e0ba90.
  Main's divergence was two PR merge commits with no extra source changes.
  No rebase/force-push; Railway, consumer and history changes were preserved.

## In Progress

| Phase | Present | Remaining |
| --- | --- | --- |
| Player workspace | Exact-line-aware overview, eight section links, latest-15 chart, direction-aware 5/10/15 form, bounded independent model record | Metadata coverage, stored-score outcome linkage, final mobile polish |
| Entry analyzer | Compact independent/adjusted probability summary, correlation difference, positive/negative pairs, five exposure dimensions, payout caveats | Final workflow acceptance and portfolio-level integration |
| Model track record | On-demand Results panel, five filters, bounded chronological ledger query, locked/settled/win/loss/push counts, existing evaluation metrics | Stored score-version linkage, verified CLV/ROI, broader acceptance testing |
| Navigation | Six consumer destinations; Players, System + Settings, and Tools + Signals accessible in Core; advanced panels moved off Today; More shortcuts preserve workspace IDs and legacy props route; hidden tools defer loading | Full deep-link acceptance and remaining mobile polish |
| Best Lines | Bounded five-player same-stat comparison with partial-failure reporting, local sportsbook/offer-type filters, exact-offer entry transfer; restricted directions, duplicate legs, provider mixing and leg limits guarded | Full-board browsing, pre-handoff live availability confirmation |
| Notifications | Existing delivery/settings | Event preferences and stale-event suppression tests |
| Beta onboarding | Existing sessions, acknowledgment and general preferences | One user-scoped preference flow, responsible-use step, feedback polish |
| Mobile | Responsive research overview and section links | All-route sheets, tables, navigation, sticky actions and installation checks |

## Deferred

- New analytics, scoring, recommendation or authentication engines.
- New prediction-market connectors, billing, App Store distribution.
- Model promotion and live provider purchases.
- Railway verification, deferred after its public URL returned Application not found.

## Known Limitations

- Handoff now distinguishes line changes, missing identity, stale provider evidence,
  unavailable verification time, and forecast age. A cached line match alone no
  longer receives positive styling; stale flags override recent timestamp claims.

- Sleeper configured feeds preserve supplied player/event/offer identifiers and
  offer type. Missing identity stays explicit; generated display IDs are not
  provider offer IDs. Configured URLs and local files do not claim direct provider
  verification. Sleeper public roster/trending APIs do not verify betting offers.

- Pick6 cache reads now retain the original collector retrieval time and expose
  cache age/staleness without additional billable actor runs. Collector retrieval
  is not promoted to direct sportsbook verification; handoff remains conservative.

- Best Lines distinguishes model-input timestamps from offer refresh timestamps.
  PrizePicks and Underdog now retain successful HTTP fetch/revalidation timestamps,
  including original cache times; stale fallbacks do not receive verification.
  Handoff requires an exact identified offer verified within five minutes, separate
  from forecast freshness. Other providers remain unverified without this evidence.
  This is board evidence, not guaranteed account-specific availability or payout.
  Handoff also rejects conflicting event IDs or start times; without shared event
  IDs it requires the same timezone-aware start and matchup. Rescheduled games
  require refreshed identity evidence rather than silently matching another event.

- Best Lines shows completed player comparisons progressively and supports stopping
  further lookups while retaining results. Each lookup has a ten-second timeout;
  stopping the browser request does not guarantee server-side provider work stops.
  Missing and unfinished players can be retried independently using the original
  search parameters without reloading successful player comparisons.

- Research splits now display the recommended direction explicitly; Over remains
  the labeled fallback when no recommendation exists. Recorded ledger results remain separate.
- Research line may be an average, not an available offer; exact-line mismatch
  suppresses recommendation metadata and paid-use wording in the new overview.
- Model Performance uses up to 1,000 recent player/sport/stat/provider ledger rows,
  excludes anonymous, legacy, unverified, inconsistent and non-pregame predictions,
  and preserves the first forecast per market within that window. Version/provider/
  direction segments use existing evaluation math. Samples below 100 are flagged.
  ROI and score buckets remain unavailable; no promotion decision is exposed.
- General onboarding and beta acknowledgment remain separate flows.
- Generator candidate/live-validation workflows are not fully feed-consolidated.
- No profitability, subscription readiness, or hosted release readiness is claimed.

## Implementation Boundaries

Reuse opportunity_score/opportunity_presentation, existing prediction ledgers,
card_probability/correlation, market services, beta sessions and alert delivery.
Do not create parallel models or remove eligibility, quarantine or freshness checks.

Latest increment adds web/static/js/player-workspace.js and an additive freshness
field to the existing research response. It corrects the chart from oldest 12
to newest 15 games displayed chronologically. No new endpoint or migration.

## Verification

Run Ruff, complete CI mypy scope, pytest, JS syntax checks and isolated visual
regression. Added coverage checks 5/10/15 samples, latest-15 chart selection,
eight section links, research-only default and unavailable model-performance text.
Local validation is not proof of hosted CI, production PostgreSQL or live providers.

The model track record endpoint is GET /api/analytics/model-track-record. It
reads at most 5,001 matching records and reports truncation; summaries use the
first 5,000 chronologically. Deduplication is per model/provider/direction,
not a claim that predictions across models or providers are independent.
Missing ROI, CLV and score linkage stay null. No migrations or promotions.

## Next Sprint

Next: extend Best Lines with safe exact-offer transfer and broader browsing, reusing
existing validation. Navigation now rejects unknown destinations, exposes the active
page to assistive technology, and retries failed view loads on the next visit.
The remaining phases above are acceptance work, not completed features.
