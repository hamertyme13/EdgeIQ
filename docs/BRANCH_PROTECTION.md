# Branch Protection for EdgeIQ

Protect `main` with a GitHub ruleset before accepting beta or production changes.
This document recommends settings; it does not change repository administration or deploy anything.

1. Require a pull request before merging. Require at least one approval from a reviewer other than the author, and dismiss stale approvals after new commits.
2. Require the `EdgeIQ CI` checks from `.github/workflows/ci.yml`: both `validate` matrix jobs (Python 3.11 and 3.13) and `visual-regression`. Confirm their exact displayed names in a recent pull request before saving the ruleset.
3. Require the branch to be up to date before merging, block force pushes and deletion, and apply the ruleset to administrators unless an emergency process explicitly requires a bypass.
4. Keep provider credentials and billable actor flags out of CI. The workflow uses an isolated SQLite database; passing it does not verify Railway PostgreSQL migrations, live provider freshness, scheduler operation, or settled-model accuracy.
5. For changes touching migrations, release gates, provider contracts, or the paid-entry path, record a human review of the relevant evidence in the pull request. Run PostgreSQL migration and rollback checks on a backed-up nonproduction database before any hosted rollout.

Do not treat the local Ollama `Check Model` smoke test or the fixed qualification runner as an automatic approval for paid recommendations. Model promotion requires the separate evidence and human-review gates in [Ollama qualification](OLLAMA_QUALIFICATION.md).
