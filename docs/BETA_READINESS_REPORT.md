# EdgeIQ beta readiness status

Updated: 2026-09-28. This is an implementation status, not a claim of model profitability or production readiness.

## Architecture

FastAPI routes in `web/` call application services, provider adapters, and SQLAlchemy repositories. Recommendation feeds and entry props carry stable offer snapshot identifiers. The versioned recommendation feed is retained for compatibility alongside a dedicated immutable per-leg recommendation table.

## Completed integrity protections

- Provider offer terms are fingerprinted and stored separately from their last observation time. A changed line creates a new identifier.
- Entry placement resolves supplied offer IDs server-side, compares submitted terms, checks direction restrictions, detects duplicate markets, and distinguishes fresh, expired, and started-game evidence.
- A collector timestamp alone does not count as direct sportsbook verification. Missing snapshots and unlinked recommendations remain explicitly unverified.
- Saved entry legs retain offer, recommendation feed, and immutable per-leg recommendation IDs for later audit. Entry analysis shows per-leg evidence status.
- New complete-board observations, including rejected props, carry the offer snapshot ID through scheduled final-stat settlement. The read-only market outcome endpoint reports Over or Under results without regrading the underlying board row.
- The new table and entry-prop columns have an Alembic migration and SQLite migration tests.

## Provider limitations

An observed offer is not proof that it is still available in a user's account. Third-party collectors, cached feeds, and adjusted lines require an exact provider confirmation before a paid decision. Exact complete-card payout evidence remains a separate requirement. Billable provider calls remain opt-in.

## Model calibration status

Existing release machinery is unchanged. New per-leg recommendation records freeze projection, confidence, model version, feature timestamp, evidence flags, and a no-vig market baseline only when at least two paired exact-line sportsbook quotes are timely and match the pregame offer. The complete-board ledger links newly captured offers to final stats. `/api/analytics/linked-offer-evaluation` evaluates deduplicated, pregame recommendations on a chronological holdout and reports exclusions and sport/stat/provider segments. Its review gate requires both a neutral 50% comparison and a paired exact-line market comparison on at least 30 holdout legs; it never promotes a model or asserts profitability. Missing market evidence stays unavailable. The settled board count includes recommended and rejected offers, but rejected offers do not have model probabilities; coverage is not proof that selection bias has been eliminated.

Contributing sportsbook quote timestamps are parsed as UTC instants before oldest/newest selection. Missing, naive, or malformed quote times do not count toward the all-books-timestamped baseline requirement.

## Risks and security

- An entry can still be manually submitted without an offer snapshot, but it cannot be described as a verified provider offer.
- Older recommendation feed IDs are coarse-grained and remain readable but cannot verify a leg by themselves. Previously captured board observations have no exact offer snapshot link and are not backfilled by guesswork. Independent model-feature freshness remains unfinished.
- Provider source identity is hashed in the new table; raw credentials and payloads are not stored there. Secrets must stay in environment configuration and out of Git.
- Model Inputs status now counts current materialized segments and segments backed by dated source games without loading full history payloads. A recent materialization or game date still does not prove that an external source has delivered every final stat; that independent freshness check remains open.
- Provider-offer observation updates now use an atomic upsert, and parallel SQLite captures are tested for one stable offer with monotonic first/last timestamps. The source label follows the latest observation, so a newer collector refresh cannot extend an older direct-verification claim; a fresh direct check can restore it. Background jobs now atomically claim a deduplication key in SQLite or PostgreSQL before starting; simultaneous SQLite claims are covered by a database test. Provider retries, PostgreSQL runtime concurrency, and upgrade/downgrade still need deployment-environment verification.

## Deployment and testing

Run `alembic upgrade head` against a backed-up database before serving code that reads the new columns. Existing SQLite migration tests cover upgrade/downgrade; a Railway PostgreSQL migration was not run here. Focused and full Python tests, Ruff, mypy, and JavaScript syntax checks were run locally. The Today schedule control was checked in an isolated local browser and database; live sportsbook availability was not verified.

The Today page now offers an optional daily Briefing refresh time separate from the existing morning provider scan. It uses the selected default platform and sport and retains other scheduled jobs when saved. Scheduled jobs record their actual completion or failure; a failed job stays due but waits at least 15 minutes before retry, and Today reports a failed briefing attempt. Execution requires the app's scheduler loop or installed desktop background scheduler to be running; a saved time alone does not create a Railway cron service.

## Remaining beta blockers

Collect enough independent, verified linked outcomes and paired no-vig quotes to assess the chronological review gate; incorporate approved evidence into model-release governance only after validation; verify provider refresh races on deployed PostgreSQL, and verify PostgreSQL migrations and a real browser workflow. Runtime Status now requires both a fresh player-feature cache and a successful daily season-source check for each sport represented in that cache. This is an observability signal, not proof of complete final-stat coverage or a paid-model promotion. These are the recommended next milestones before expanding consumer access.

### Railway observation, October 15, 2026

A read-only inspection of the configured production Railway environment showed no active deployment for either EdgeIQ or Postgres; their recent deployments were marked removed. No cron service was present. This does not establish why they are offline, and no recovery or migration was attempted. The user asked to leave production untouched. Hosted PostgreSQL migration, scheduler execution, and end-to-end phone workflow remain unverified until a separately authorized recovery and backed-up test can be performed.

### Local qualification and verification, October 15, 2026

The fixed-case `llama3.1:8b` qualification run did not pass either planner or analyst gates (18/60 and 15/60, respectively). A subsequent one-pass v2 diagnostic found two analyst instruction/paid-clearance echoes, three missing-data disclosure failures, and ten safe fallbacks. The answer guard now rejects control-token echoes and any paid-clearance assertion; focused service tests cover the fallback. A full three-repetition post-fix run reached the local Ollama service: planner 18/60, analyst 15/60, zero analyst forbidden claims, 36 analyst fallbacks, and nine missing-data disclosure failures. Neither role passed its automatic gate or was promoted. The fixed fixture is a safety screen, not proof that all possible prompts are grounded. One-pass reports cannot qualify a role.

Local Ruff, the CI mypy scope, full Python tests, visual regression, and an isolated SQLite Alembic upgrade/downgrade/upgrade passed during this work. No hosted PostgreSQL migration or remote CI result was verified. These local checks do not establish model accuracy or production readiness.

### Isolated local validation, October 18, 2026

An ephemeral localhost PostgreSQL 16 container passed Alembic base-to-head upgrade, latest-revision downgrade, and re-upgrade. The Model Inputs aggregate status query returned successfully on that schema. The container was removed after the check. Playwright validated 30 desktop/mobile views against a separate temporary SQLite database. These checks do not validate the offline Railway services or a real beta account workflow. Source-game dates and cache age remain observability only: no independent external final-stat completeness or freshness audit has been established, so that beta blocker remains open.

### Local source and offer checks, October 20, 2026

Runtime Model Inputs now requires a successful daily season-source check for each sport represented in the player-feature cache. A successful check means the source was queried, not that every final stat is complete. An opt-in concurrency test against an ephemeral localhost PostgreSQL 16 database found and fixed a driver-specific inserted-row count bug in complete-board offer capture; six simultaneous writers now produce one offer and report one new row. The test uses a disposable schema and does not establish deployed Railway behavior.

The linked-offer evaluation also deduplicates opposite Over/Under decisions on the same player, game, and stat before counting evidence. Provider copies were already deduplicated. Distinct stats in one game can remain correlated, so this count is not a claim of fully independent games.

The local desktop database has 16,896,120 board-offer observations but no settled observations linked to its 1,555 recommendation snapshots. The prior evaluation query timed out while scanning the full board. It now starts from recommendation snapshots and defers the complete-board distinct count on large boards; the desktop API returned in 0.115 seconds on this database. Its zero linked outcomes cannot support a model promotion. Capture and settlement linkage must be investigated before treating the evaluation as evidence of accuracy.

An exact-offer trace found that verified Today candidates dropped provider offer/player/event IDs and offer terms when converting a provider row into an analyzed recommendation. The new candidate and top-opportunity paths preserve those fields, and a fingerprint regression test confirms the candidate matches the provider row. This is forward-looking: old recommendation snapshots are immutable, and a matching visible player/stat/line is not sufficient to backfill an exact provider identity. Newly captured recommendations still need observed settlement outcomes before the linked evaluation can be measured.

An isolated provider-row-to-Today-to-board-to-final-stat test now proves the full new-capture path links and settles. A bounded local linkage diagnostic reports 1,555 recommendation snapshots, nine with an exact board-offer match, and zero with a settled board match. The evaluation API exposes these counts without a complete-board scan. The local counts are not production evidence and do not justify backfilling old snapshots or promoting the model.

Four distinct October 18 NFL board markets underlying those nine linked snapshots were due but had zero settlement attempts; the general board cursor had not reached them. The board settlement and final-stat retrieval cursors now prioritize exact-linked due offers within the same batch limit, then continue their normal rotation. An isolated queue test proves the linked market runs first and older unlinked markets still settle. A read-only local selection of ten rows took 0.103 seconds and included all four linked markets. No local ledger result was changed by this diagnostic; actual final-stat verification remains required.

Subsequent read-only final-stat checks found ESPN results for all four markets on the correct game date. The local board now stores those four outcomes, and the evaluation reports four independent settled legs from nine linked recommendation snapshots; its model review gate still fails for insufficient holdout and paired market evidence. Settlement and retrieval also had a separate default-clock bug: `utc_now()` returns naive UTC, but `astimezone(UTC)` interpreted it as local Eastern time, shifting due and retry timing four hours forward. Both board entry points now interpret that naive timestamp as UTC, with timezone-specific regression tests. The observed concurrent settlement activity does not establish which worker completed each market; no paid-entry ledger result was changed by this check.

Board-offer settlement takes a nonblocking host-local operation lock at the repository boundary, so overlapping desktop/manual calls report an explicit skip while one worker runs. A concurrent-call test proves only the first worker settles on one host.

The board-settlement boundary now also holds a PostgreSQL session advisory lock for the full worker call, while SQLite retains the existing host-local lock. An opt-in test against a disposable localhost PostgreSQL 16 container proved that a separate process was denied during the first process's hold and could acquire after release. The container was removed after testing. This verifies the lock primitive locally, not Railway scheduler configuration, database failover behavior, or hosted multi-replica operation.

Analyzed board props and generated entry legs now retain the exact provider offer/event identity, direction restrictions, and any decision receipt supplied with the source offer. A generated or analyzed prop can therefore carry a timely exact-line multi-book no-vig quote into its immutable leg snapshot; the existing baseline validator still rejects stale, mismatched, or incomplete quotes. New regression tests compare offer fingerprints and validate a retained receipt on both paths. This is forward-looking only: it does not create missing market quotes, rewrite historical snapshots, or clear the review gate.

The read-only linked-offer evaluation now reports holdout market-evidence coverage and exclusion reasons per model version. A local check found four independent settled linked outcomes, all lacking an exact market quote (`exact_market_unavailable`); none can enter a paired no-vig comparison. This identifies quote collection as the immediate evidence gap, not a failed paired comparison. It does not authorize release or establish predictive quality.

A desktop Results audit found historical card/leg inconsistencies in the local ledger: two all-win cards stored as losses, two standard-payout wins with losing legs, and 23 settled cards with unresolved legs (26 distinct entries after overlap). The Settlement tab now shows a read-only integrity warning and bounded examples; visible completed cards with conflicting leg evidence are marked for review instead of receiving an unqualified WIN banner. No historical payout, final stat, or calibration row was changed. Reconciliation requires verifying the original game identity, official final, and sportsbook payout, especially for entries with missing game times or prior manual corrections.

The Results browser also exposed a notification refresh timeout. Notification summaries had been recalculating full market/final-stat progress for every pending entry (about seven seconds locally); they now use already stored leg statuses for a lightweight alert. Detailed entry tracking remains unchanged and can still request fresh results explicitly.

The Entry Builder now starts with card settings, then adds props, so the platform is selected before manually creating legs. The settlement integrity warning expands all flagged cards with per-leg game, line, actual, and source evidence rather than just eight IDs. Local paid entry #45 and paper entry #103 are stored as losses despite all currently stored legs showing wins; several of their legs lack game times or matchups, so neither payout nor result was auto-corrected. The saved payout table is now used to grade a fully resolved flex entry, with a regression test for a paid card whose two-hit return differs from the generic schedule. Any leg-results payload with an unresolved or missing leg is rejected before settlement. Existing historical contradictions still require original game and payout verification before repair.

Same-day final-stat recovery now requires a unique game matching the player's team on the entry placement date when no game was saved. It refuses a different date or conflicting same-game actuals. With a consistent local backup saved under `.edgeiq_backups/`, entries #45 and #103 were reconciled against the July 14 and July 18 WNBA finals. #45 remains a paid loss: Kiki Iriafen assists changed 3 to 1 and Sonia Citron points changed 25 to 2. #103 changed from a paper loss to a paper win: Sabrina Ionescu 3-pointers made changed 4 to 2, which still beats the entered 1.5 line. Linked bet history and prediction outcomes were updated through the normal settlement repository, with an audit reason on both entries. Other historical cards remain untouched where a full set of unambiguous final stats is unavailable.

The provider generator's Load Games control now opens its matchup picker after loading and shows a game count or an explicit empty/error message. A desktop browser check displayed the available PrizePicks matchup instead of leaving it hidden in collapsed content. Ask EdgeIQ's typed-fact guard also distinguishes a calibrated probability claim from a raw model estimate: a matching number alone no longer supports the stronger label. This guard improves explanation honesty, not forecast calibration or model accuracy.

Exact-line market lookup for Today recommendations now matches both teams and the provider's scheduled start before requesting event-level odds. Repeated matchups without a unique start are left unavailable rather than borrowing the first event's quote. Tests cover same-team events at different times and confirm a mismatched date never triggers an event-odds request. This protects future quote identity; it does not create missing paired prices for historical snapshots or increase the four settled linked outcomes already recorded.

Today's EdgeIQ Recommendation Accuracy panel now presents two separate monthly cohorts in the same location: every card with a saved valid complete-card probability and the 60%+ subset. Both show win/loss accuracy, pending, pushes, and tracked counts. Legacy cards without a valid saved probability remain explicitly excluded and counted as unavailable; lower-probability paper cards remain in calibration. The existing top-level 60%+ API fields are preserved for model-health consumers.
