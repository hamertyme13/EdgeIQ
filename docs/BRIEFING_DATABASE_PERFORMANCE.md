# Briefing and database performance

## What is timed

A fresh Daily Briefing stores `build_timings_ms` with its snapshot and logs the completed timings. The stages distinguish dashboard and preference reads, provider-board retrieval plus its snapshot, confirmed-prop analysis, command cards, paper cards, and final snapshot persistence. Provider fetch status separately records `provider_fetch_ms` and `offer_filter_ms` in its diagnostics. A cached briefing does not fetch providers or rebuild cards.

These are elapsed times, not independent additive components: the board stage includes provider work and its snapshot write. Compare several runs, especially cache hits versus forced provider refreshes, before changing thresholds or buying a faster database.

## Retention policy

- Keep every observation row, line, projection, selection decision, and settlement outcome in the active database. Complete-board evidence protects against selection bias.
- Keep raw provider JSON for at least 21 days. Older raw payloads may move to compressed cold storage in capped batches after a separate completed backup exists. The archive is reversible by observation ID and captured timestamp.
- Never delete unresolved or unverified markets merely to reduce file size. Use the existing final-stat archive only under its separate 365-day minimum policy.
- An archive batch clears only the raw `provider_payload` field. SQLite will reuse freed pages but the file will not shrink automatically. Do not run `VACUUM` on the live 42 GB file; test a full copy-and-swap strategy with enough free space and a maintenance window first.

`scripts/manage_board_archive.py` defaults to a read-only preview. `--execute --backup-path PATH` archives at most 1,000 old payloads by default; use `--limit` up to 5,000. Preserve the `.edgeiq_archives` files alongside the backup. `--restore ARCHIVE` restores payloads to still-present rows. This is a manual operation; it is not part of the daily scheduler.

## Query changes

Recent player-name fallback now checks at most 5,000 records for the requested sport and stat, instead of reading the entire final-stat table into Python. Composite indexes support that search and identity-backed player history. On a 2026-10-07 maintenance clone, SQLite changed the WNBA Points query from a temporary-sort plan to `ix_final_stat_sport_stat_date`; a single local query took approximately 0.48 seconds before and 0.06 seconds after. Those values are diagnostic observations, not a production latency guarantee.

The new migration was upgraded and downgraded on a cloned backup before any live migration. Backups and archives stay outside Git.
