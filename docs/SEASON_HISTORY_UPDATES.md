# Daily Season History

The maintenance scheduler updates NBA, WNBA, NFL, NCAAF, MLB, and NHL at
06:00 America/New_York by default. The server must remain running and the
refresh schedule must be enabled. Opening the phone interface is not required.
These changes must be deployed before they affect Railway.

Each sport has a persistent checkpoint in settings. Routine updates revisit
two days before the checkpoint for corrected box scores and process at most
14 dates per run. A first incremental sync checks the most recent seven days;
it does not claim to backfill a missing season. Use Full season rescan in
Research for a deliberate historical backfill. Updates use existing final-stat
upserts rather than scanning the entire sport for duplicates.

Provider failure stops at the failed date without skipping it. The scheduled
job reports failure so maintenance can retry. File locks protect local runs;
PostgreSQL session advisory locks protect season sync across server replicas.
Each successful daily league update is recorded inside that lock, so retries
for a failed league do not repeatedly fetch leagues that already succeeded.
Explicit manual updates remain available after the daily run.
Other maintenance jobs retain their existing locking behavior.

PostgreSQL URLs using postgres:// or postgresql:// are normalized to the
installed psycopg driver in both application startup and Alembic. This does
not migrate the local SQLite records into Railway or verify a deployed server.

# Recorded Prop Results

Player research displays verified recorded wins and losses by stat and
direction, independently of entry outcome. It queries at most the player's
500 latest resolved ledger legs, deduplicates repeated game/line/direction
observations, and excludes unresolved or estimated outcomes. Lines can vary;
this is descriptive history, not an exact-current-line win probability or an
automatic model confidence adjustment.

The record also shows wins and losses at the selected exact line separately.
Stored outcome labels must agree with the final numeric result. Non-finite
values, pushes labeled as decisions, missing game identities, and conflicting
duplicate results are withheld rather than counted as wins. These checks do
not modify or settle the original ledger records.

Prediction-market expansion remains a follow-up after collection, settlement,
and release evidence are dependable. Priorities are verified contract identity,
outcome rules, live price/fees, and chronological game-model evaluation before
new actionable market recommendations.
