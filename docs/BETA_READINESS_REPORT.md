# EdgeIQ beta readiness status

Updated: 2026-09-28. This is an implementation status, not a claim of model profitability or production readiness.

## Architecture

FastAPI routes in `web/` call application services, provider adapters, and SQLAlchemy repositories. Recommendation feeds and entry props now carry stable offer snapshot identifiers. The existing versioned recommendation feed remains the recommendation record; a dedicated per-leg recommendation snapshot table has not yet been added.

## Completed integrity protections

- Provider offer terms are fingerprinted and stored separately from their last observation time. A changed line creates a new identifier.
- Entry placement resolves supplied offer IDs server-side, compares submitted terms, checks direction restrictions, detects duplicate markets, and distinguishes fresh, expired, and started-game evidence.
- A collector timestamp alone does not count as direct sportsbook verification. Missing snapshots and unlinked recommendations remain explicitly unverified.
- Saved entry legs retain offer and recommendation feed IDs for later audit. Entry analysis shows per-leg evidence status.
- The new table and entry-prop columns have an Alembic migration and SQLite migration tests.

## Provider limitations

An observed offer is not proof that it is still available in a user's account. Third-party collectors, cached feeds, and adjusted lines require an exact provider confirmation before a paid decision. Exact complete-card payout evidence remains a separate requirement. Billable provider calls remain opt-in.

## Model calibration status

Existing calibration and model-release machinery is unchanged by this slice. No new evidence supports higher accuracy or profitability claims. Provider offer snapshots are not yet automatically settled as a complete-board cohort, so selection bias remains.

## Risks and security

- An entry can still be manually submitted without an offer snapshot, but it cannot be described as a verified provider offer.
- Existing recommendation feed IDs are coarse-grained; per-leg immutable recommendation evidence, independently dated model features, and settlement-to-snapshot outcome linkage remain unfinished.
- Provider source identity is hashed in the new table; raw credentials and payloads are not stored there. Secrets must stay in environment configuration and out of Git.
- Concurrent writes, provider retries, and PostgreSQL upgrade/downgrade need deployment-environment verification.

## Deployment and testing

Run `alembic upgrade head` against a backed-up database before serving code that reads the new columns. Existing SQLite migration tests cover upgrade/downgrade; a Railway PostgreSQL migration was not run here. Focused and full Python tests, Ruff, mypy, and JavaScript syntax checks were run locally. Browser layout and live sportsbook availability were not verified.

## Remaining beta blockers

Complete per-leg recommendation snapshots; settle all captured offers and link outcomes to immutable evidence; add chronological calibration and baseline quality gates; test provider refresh deduplication and asynchronous races; expose provider/model freshness independently; verify PostgreSQL migrations and a real browser workflow. These are the recommended next milestone before expanding consumer access.
