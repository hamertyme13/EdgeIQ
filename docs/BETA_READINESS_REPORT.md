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
- Provider-offer observation updates now use an atomic upsert, and parallel SQLite captures are tested for one stable offer with monotonic first/last timestamps. The source label follows the latest observation, so a newer collector refresh cannot extend an older direct-verification claim; a fresh direct check can restore it. Provider retries and PostgreSQL concurrency and upgrade/downgrade still need deployment-environment verification.

## Deployment and testing

Run `alembic upgrade head` against a backed-up database before serving code that reads the new columns. Existing SQLite migration tests cover upgrade/downgrade; a Railway PostgreSQL migration was not run here. Focused and full Python tests, Ruff, mypy, and JavaScript syntax checks were run locally. The Today schedule control was checked in an isolated local browser and database; live sportsbook availability was not verified.

The Today page now offers an optional daily Briefing refresh time separate from the existing morning provider scan. It uses the selected default platform and sport and retains other scheduled jobs when saved. Scheduled jobs record their actual completion or failure; a failed job stays due but waits at least 15 minutes before retry, and Today reports a failed briefing attempt. Execution requires the app's scheduler loop or installed desktop background scheduler to be running; a saved time alone does not create a Railway cron service.

## Remaining beta blockers

Collect enough independent, verified linked outcomes and paired no-vig quotes to assess the chronological review gate; incorporate approved evidence into model-release governance only after validation; test provider refresh deduplication and asynchronous races; expose provider/model freshness independently; verify PostgreSQL migrations and a real browser workflow. These are the recommended next milestones before expanding consumer access.
