# EdgeIQ v2.2 - Model Rehabilitation

This release separates historical performance, calibration evidence, and
prospective shadow evaluation.

- Calibration uses plausible, versioned, independent markets with verified outcomes.
- Uncalibrated probabilities are capped at 69%; thin calibrated segments remain capped below extreme confidence.
- Entry grades use calibrated joint card probability relative to payout break-even probability.
- DFS expected value is verified only when the exact provider card payout table is captured.
- Scheduled line refreshes preserve same-game and same-offer closing snapshots, including unchanged closing lines.
- Recommendations share one persisted normalized provider snapshot.
- The v2.2 candidate model remains in shadow mode until at least 100 verified shadow decisions settle at 55% accuracy or better.

The 227 queued shadow predictions are prospective records. They do not count as
settled evidence and cannot unlock paid recommendations until verified final
results arrive.
