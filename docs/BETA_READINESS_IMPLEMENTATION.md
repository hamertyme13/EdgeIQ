# EdgeIQ Founding Beta Readiness

## Current Architecture

EdgeIQ uses SQLAlchemy through `repository.database`, Alembic migrations in
`migrations/versions`, modular repository classes, FastAPI routers, and a browser-first
desktop interface. The existing `prediction_records` table and
`PredictionLedgerRepository` are the authoritative performance evidence. Entries,
entry props, final statistics, recommendation snapshots, settlement audits, line
history, research evidence, and product events already have dedicated stores.

Product usage is currently recorded by `ProductExperienceRepository`, but events are
anonymous. The existing onboarding profile is device-wide rather than user-aware.
There is no persistent user, login session, structured beta feedback, issue queue, or
tester-level admin report.

## Implementation Plan

The beta layer extends the current architecture:

```text
BetaUser -> BetaSession -> ProductEvent
                         -> Analysis / Entry -> PredictionRecord
                         -> BetaFeedback -----^
                         -> BetaIssue
                         -> BetaAnalytics
```

The implementation adds:

- persistent beta users with normalized unique email, roles, cohorts, activation,
  PBKDF2 password hashes, onboarding state, and activity timestamps;
- revocable, expiring beta sessions whose raw bearer token is never stored;
- nullable `user_id` and `session_id` attribution on the existing product-event table;
- structured feedback linked to existing prediction, entry, and entry-prop rows;
- a compact bug and feature-request queue;
- beta KPI, funnel, tester-activity, feedback, issue, model-performance, and segment
  analytics built in repositories/services rather than UI code;
- browser UI for login, onboarding, analysis feedback, issue submission, and an
  admin-only beta dashboard.

The legacy PyQt application remains importable and unchanged. Beta administration is
implemented in the browser application because that is EdgeIQ's current flagship and
installable desktop/mobile surface.

## Database Changes

One Alembic revision will add `beta_users`, `beta_sessions`, `beta_feedback`, and
`beta_issues`, plus nullable attribution columns and indexes on `product_events`.
Foreign keys point to existing records; no historical ownership is fabricated and no
prediction or settlement evidence is rewritten.

## UI Changes

- A compact Founding Beta control in the global header opens login/account tools.
- First login presents a concise acknowledgment and responsible-use notice.
- Research includes optional pre-analysis opinion and post-analysis feedback.
- Problem reports and feature requests live in the same beta drawer.
- Admin users receive cohort controls and aggregate beta/model reporting in that
  drawer without adding clutter for testers.

## Test Plan

- User creation, uniqueness, hashing, authentication, roles, and activation.
- Session creation, lookup, expiration, logout, and activity attribution.
- Backward-compatible anonymous product events and attributed events.
- Feedback linkage, decision-change derivation, deduplication, and aggregates.
- Bug/feature submission and recent queues.
- Zero, single, and multi-user beta analytics including ledger metrics and segments.
- Alembic upgrade/downgrade against an isolated database.
- Existing prediction recording, settlement, evidence, web, GUI import, and full-suite
  regression tests.

## Compatibility and Security

- Authentication is optional until beta users exist, so local non-beta workflows keep
  working.
- Passwords use salted PBKDF2-HMAC-SHA256 and are never returned or logged.
- Session tokens are random; only SHA-256 token hashes are persisted.
- Admin APIs require an active authenticated admin session.
- User-supplied text is length-limited, validated, stored through SQLAlchemy, and
  escaped by the existing UI helpers.
- Existing prediction deduplication, quarantine, evidence-quality, settlement, and
  bankroll rules remain authoritative.

## Manual Validation Checklist

1. Create an initial admin through the documented CLI command.
2. Log in, acknowledge onboarding, and create a Founding 25 tester.
3. Log in as the tester and run Research with an initial opinion.
4. Submit a final decision and analysis feedback.
5. Save an entry and verify attributed product events.
6. Submit one problem report and one feature request.
7. Log in as admin and confirm users, activity, feedback, issues, funnel, and model
   metrics are visible.
8. Verify existing recommendations, entries, settlement, Results, and Research still
   operate normally.

## Launch Procedure

Use the beta-management wrapper. It selects a dependency-complete EdgeIQ Python
interpreter and applies pending Alembic migrations before managing an account:

```bash
./scripts/manage_beta.sh create-admin \
  --email admin@example.com --username admin --cohort FOUNDING_25
./scripts/manage_beta.sh create-tester \
  --email tester@example.com --username tester01 --cohort FOUNDING_25
./scripts/launch_edgeiq.sh
```

`./scripts/manage_beta.sh list` shows the current accounts without exposing password
hashes or session tokens. The optional `/api/beta/bootstrap` route is disabled unless
`EDGEIQ_BETA_BOOTSTRAP_TOKEN` is set, works only while no users exist, and should be
unset immediately after first use.

For a hosted release, terminate TLS at the deployment boundary and replace browser
local-storage bearer tokens with secure, HTTP-only, same-site cookies. The local beta
implementation deliberately avoids email delivery, password reset, and billing until
those services have an explicit owner and privacy policy.

## Event and KPI Definitions

The beta layer records `beta_login`, `beta_logout`, `beta_session_started`,
`beta_session_ended`, `beta_onboarding_viewed`, `beta_onboarding_completed`,
`analysis_started`, `initial_opinion_recorded`, `feedback_submitted`,
`decision_changed`, `bug_reported`, `feature_requested`, and `beta_user_created`.
Existing recommendation, entry, and settlement events remain unchanged and now accept
optional user/session attribution. Anonymous local workflows remain valid.

| Event | Purpose |
| --- | --- |
| `beta_login`, `beta_logout` | Measure authenticated access boundaries. |
| `beta_session_started`, `beta_session_ended` | Group activity into an identifiable visit. |
| `beta_onboarding_viewed`, `beta_onboarding_completed` | Measure responsible-use onboarding completion. |
| `analysis_started`, `initial_opinion_recorded` | Preserve the tester's pre-recommendation state. |
| `feedback_submitted`, `decision_changed` | Measure usefulness and recommendation influence. |
| `bug_reported`, `feature_requested` | Feed the structured beta review queues. |
| `beta_user_created` | Audit cohort provisioning by an administrator. |

The existing `recommendation_viewed`, `entry_analyzed`, `recommendation_added`,
`entry_saved`, and `entry_settled` events supply the attributed beta funnel. The beta
dashboard intentionally excludes anonymous historical events from that funnel.

Admin KPIs are derived from attributed events and structured records:

- active testers are enabled accounts active within seven days;
- analyses count attributed `entry_analyzed` events;
- useful and decision-change rates use answered feedback only where appropriate;
- model outcome and error metrics come from the existing versioned prediction ledger;
- segment rows exclude quarantined legacy predictions and label small samples clearly;
- settlement ownership may inherit from the latest attributed save event for the same
  entry, allowing background settlement to remain correctly attributed.

## Known Deferred Items

- Email invitations, password-reset email, OAuth, subscription billing, and hosted
  multi-tenant deployment are intentionally deferred.
- Historical anonymous events and entries remain unowned.
- PyQt receives no separate beta login surface; the supported founding-beta surface is
  the browser/PWA desktop application.
