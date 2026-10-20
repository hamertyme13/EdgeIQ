# Local PostgreSQL evaluation

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

## October 19 preflight

The read-only inventory found 28 SQLite tables at Alembic revision `s12e4b7c9d30`, matching the empty local PostgreSQL schema revision. It counted 1,329 entries, 4,907 entry props, 1,794,641 final-player-stat rows, 4,907 prediction records, 16,583,019 board observations, 286,857 provider offer snapshots, and 11,989 settlement audits. The source database occupied 47,274,446,848 bytes, with ample free disk space for a separate copy.

An SQLite online backup was created at `.edgeiq_backups/edgeiq-20261019T082737137143Z.db`. Its size, schema revision, and all seven critical counts matched the source preflight. A full `PRAGMA quick_check(1)` on the backup was stopped after five minutes without a result, so structural integrity has **not** been certified. The desktop was still using SQLite during this preflight. A later maintenance window should finish integrity and foreign-key checks, then test a staged PostgreSQL import and reconcile exact entry outcomes before cutover.
