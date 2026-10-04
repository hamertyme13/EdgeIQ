# Model Probability and Calibration

Recommendation cards distinguish the model's exact-line estimate from the confidence displayed after hierarchical calibration or an evidence cap. A capped uncalibrated estimate is **not** described as a calibrated probability.

Calibration uses independent, versioned, settled Win/Loss outcomes and tries narrow sport/stat/provider/direction/source peers before broader fallback groups. Cards display the matching tier, comparable settled sample count, and sport/stat/provider segment count. Status labels mean:

- **Calibrated:** at least 100 comparable settled predictions and 100 in the sport/stat/provider segment, with uncertainty no greater than 10 percentage points.
- **Partial:** some relevant settled evidence exists, but the comparable or segment sample is below 100.
- **Degraded:** estimated calibration uncertainty exceeds 10 percentage points.
- **Insufficient sample:** no qualifying calibration tier; the displayed confidence may be capped, but is not empirically calibrated.
- **Unavailable:** the recommendation snapshot has no calibration evidence.

These are presentation labels, not model-release approvals. Paid-entry eligibility remains governed by the separate release, provider-offer, settlement, trust, and payout checks. A recommendation does not receive a fabricated Brier score or observed calibration error; those metrics belong to aggregate Results evaluation when measured. Existing immutable snapshots retain their original evidence and can display unavailable status.
