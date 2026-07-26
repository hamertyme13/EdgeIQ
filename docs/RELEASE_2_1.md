# EdgeIQ v2.1 - Validation and Reliability

## Release Standard

EdgeIQ v2.1 is evidence-gated. Results displays the live release scorecard and
does not describe the model as validated until all gates pass:

- 100 settled paper entries
- 300 verified settled props, with 500 preferred
- Accuracy tables for confidence, grade, sport, stat, and provider
- Passing chronological holdout and walk-forward checks
- At least 50 reliable closing-line snapshots
- At least 100 calibrated props with mean absolute calibration error at or below 10 points

Paper outcomes count only when a supported final-stat source verified the leg.
Projection estimates, unknown sources, and unmatched rows are excluded.

## Primary Journey

The Advantage Center is the primary validation journey:

1. Retrieve current provider props.
2. Review provider freshness.
3. Rank the opportunity feed.
4. Inspect the top recommendation, trust score, and supporting evidence.
5. Add the recommendation as a paper entry.
6. Let the normal final-stat workflow settle every leg.
7. Review the release gates and segmented calibration in Results.

## Development Gates

GitHub Actions runs on Python 3.11 and 3.13. It checks:

```bash
ruff check .
mypy analytics/release_validation.py services/data_management.py utils/entity_normalization.py
pytest
```

Provider parsing is covered with saved fixtures, migrations are tested against a
legacy schema, and every pytest session receives an isolated temporary database.

## Data Recovery

The SQLite database and generated recovery artifacts are ignored by Git.
Use **Create Backup** in Data Health for a transaction-safe SQLite copy, or
**Export Data** for a versioned JSON export. Files are written to
`.edgeiq_backups/` and `.edgeiq_exports/`.

Audit snapshots created in v2.1 include a schema version and model version so
future reviews can identify the recommendation logic that produced each entry.
