# Local PostgreSQL desktop database

## Current desktop status (October 27, 2026)

The Mac desktop app now uses the local PostgreSQL 17 database `edgeiq_staging` on
`127.0.0.1:55432`. This is **not** the Railway database. The final stopped-SQLite
snapshot and PostgreSQL reconciled across all 28 tables, including full entry,
leg, bet, and settlement-audit hashes (2,198 entries and 8,283 legs at cutover).
The desktop icon and scheduled maintenance start/check the local PostgreSQL
server. `.env` holds the local `DATABASE_URL`, `EDGEIQ_LOCAL_POSTGRES=1`, and
`EDGEIQ_DEPLOYMENT_MODE=local`. The ignored `.edgeiq_postgres_cutover` marker
prevents a missing database URL from silently creating an empty SQLite ledger.

The former root `edgeiq.db` and older SQLite backup copies were removed after
verification. The retained rollback snapshot is
`.edgeiq_backups/edgeiq-cutover-20261027.db.zst`; the PostgreSQL-native backup
is `.edgeiq_backups/edgeiq-20261027T194137630962Z.dump`. The October 2 preview
database was retained separately. Backup and Export now produce PostgreSQL
custom-format archives (`pg_restore`), not SQLite/JSON, when this backend is
active. A rollback to the cutover snapshot would lose subsequent PostgreSQL
writes; take a fresh PostgreSQL backup and plan a reverse migration first.

The evaluation notes below describe the **pre-cutover** process and are kept
for audit history, not as the current desktop configuration.

EdgeIQ's desktop database remains SQLite until its records are deliberately migrated and reconciled. The local PostgreSQL service is an isolated migration target, not an automatic speed upgrade or a Railway deployment.

Run from the repository root:

```bash
bash scripts/local_postgres.sh start
bash scripts/local_postgres.sh schema
bash scripts/local_postgres.sh status
bash scripts/local_postgres.sh preflight
bash scripts/local_postgres.sh stop
```

`start` creates a private, ignored credential file, binds PostgreSQL only to `127.0.0.1:55432`, and persists data in the `edgeiq-local` Docker volume. `stop` leaves that volume intact. Do not use `docker compose down -v` unless you intend to erase the local PostgreSQL copy.

The `schema` command builds the current web image and applies Alembic migrations to the empty local database. It does **not** import existing SQLite entries, stats, snapshots, or provider history. Do not point the desktop launcher at PostgreSQL after only running `schema`; the UI would appear to have lost its data.

`preflight` reads the SQLite ledger and local PostgreSQL target without modifying either. It reports storage, schema revisions, selected table counts, and whether SQLite changed during inspection. Counts can time out on a large table and are then shown as unavailable. A preflight is not a backup or authorization to copy live data.

Before any 44 GB ledger transfer: take and verify a separate SQLite backup, stop writes, inventory row counts and foreign-key relationships, stream data into a staging PostgreSQL database, reconcile counts and critical entry outcomes, then switch `DATABASE_URL` only after a rollback plan is tested. Keep the original SQLite file unchanged through cutover. The hosted Railway PostgreSQL service is separate and remains untouched.

PostgreSQL can improve concurrent reader/writer behavior and avoid SQLite's last-connection WAL checkpoint, but query plans, indexes, archive policy, provider latency, and refresh orchestration still determine most of EdgeIQ's user-visible speed. Benchmark the same workload on both databases before deciding to migrate the desktop.

## Homebrew staging on macOS

When Docker is unavailable, install PostgreSQL 17 with Homebrew. Start its local
cluster on port 55432 and create a separate staging database:

```bash
brew install postgresql@17
/opt/homebrew/opt/postgresql@17/bin/pg_ctl -D /opt/homebrew/var/postgresql@17 \
  -o '-h 127.0.0.1 -p 55432' -l /private/tmp/edgeiq-postgres.log start
/opt/homebrew/opt/postgresql@17/bin/createdb -h 127.0.0.1 -p 55432 edgeiq_staging
DATABASE_URL='postgresql+psycopg://YOUR_MAC_USER@127.0.0.1:55432/edgeiq_staging' \
  .ci-venv/bin/alembic upgrade head
```

The importer requires a **completed, separate, current SQLite backup**. Pause
desktop writes while making that backup and through the final cutover. Never
use the live `edgeiq.db` file as the import source. Point the migration tool at
the empty staging database; it refuses mismatched schemas, existing data, and
an unclosed backup WAL. The default is a read-only dry run:

```bash
export EDGEIQ_MIGRATION_TARGET_URL='postgresql://YOUR_MAC_USER@127.0.0.1:55432/edgeiq_staging'
.ci-venv/bin/python scripts/migrate_sqlite_to_postgres.py \
  --source /path/to/current-completed-backup.db
.ci-venv/bin/python scripts/migrate_sqlite_to_postgres.py \
  --source /path/to/current-completed-backup.db --execute
```

The copy streams rows in foreign-key order in one PostgreSQL transaction. It
checks every table's row count and hashes complete entry, leg, bet, and
settlement-audit records before committing. A failed check rolls back the copy.
The desktop continues to use SQLite afterward. Compare critical application
workflows against staging and reconcile any writes made since the backup before
changing the desktop `DATABASE_URL`. Keep the SQLite backup for rollback.

### Bring staging up to a newer snapshot

Keep the old completed backup that was used for the PostgreSQL copy. Make a new
SQLite online backup, close it, and verify it with `PRAGMA quick_check(1)`.
The desktop may resume using SQLite immediately after the backup closes.
Then run the staging sync against the old and new snapshots:

```bash
export EDGEIQ_MIGRATION_TARGET_URL='postgresql://YOUR_MAC_USER@127.0.0.1:55432/edgeiq_staging'
.ci-venv/bin/python scripts/sync_postgres_staging.py \
  --old-backup /path/to/previous-completed-backup.db \
  --new-backup /path/to/new-completed-backup.db
.ci-venv/bin/python scripts/sync_postgres_staging.py \
  --old-backup /path/to/previous-completed-backup.db \
  --new-backup /path/to/new-completed-backup.db --execute
```

The command first checks that PostgreSQL still matches the old backup. It then
streams inserted rows, applies changed rows (including settled outcomes), and
removes deleted rows in dependency order. Every table count and the entry,
leg, bet, and settlement-audit contents must reconcile before its transaction
commits. On success, retain the new backup as the baseline for the next sync.
This is a **point-in-time staging refresh**, not live replication or a desktop
database switch. New writes after the snapshot remain only in SQLite.

## October 19 preflight

The read-only inventory found 28 SQLite tables at Alembic revision `s12e4b7c9d30`, matching the empty local PostgreSQL schema revision. It counted 1,329 entries, 4,907 entry props, 1,794,641 final-player-stat rows, 4,907 prediction records, 16,583,019 board observations, 286,857 provider offer snapshots, and 11,989 settlement audits. The source database occupied 47,274,446,848 bytes, with ample free disk space for a separate copy.

An SQLite online backup was created at `.edgeiq_backups/edgeiq-20261019T082737137143Z.db`. Its size, schema revision, and all seven critical counts matched the source preflight. A full `PRAGMA quick_check(1)` on the backup was stopped after five minutes without a result, so structural integrity has **not** been certified. The desktop was still using SQLite during this preflight. A later maintenance window should finish integrity and foreign-key checks, then test a staged PostgreSQL import and reconcile exact entry outcomes before cutover.
