# Recommendation Fragility

`edgeiq-fragility-v1` is a deterministic evidence-sensitivity score for an individual prop. It is **not** the probability of losing, and it does not modify the forecast, calibration, grade, or EdgeIQ Score. The Opportunity Board displays the label; Proof shows the contributing factors and conditions that require rechecking.

Uncertainty points:

| Evidence | Points |
| --- | ---: |
| Historical sample unavailable or fewer than 15 effective games | 20 |
| 15–29 effective games | 10 |
| Forecast spread or projection unavailable | 15 |
| Standard deviation at least 35% of absolute projection | 15 |
| Standard deviation at least 22% of absolute projection | 8 |
| Data-quality score unavailable | 10 |
| Data-quality score below 50 | 15 |
| Data-quality score 50–69 | 8 |

Additional fragility points:

| Condition | Points |
| --- | ---: |
| Projection within 0.25 standard deviations of the line | 15 |
| Projection within 0.5 standard deviations of the line | 8 |
| Provider offer expired | 25 |
| Provider freshness unconfirmed | 12 |
| Required role/minutes evidence unverified | 20 |
| Premium or demon offer | 10 |
| Same market already pending | 15 |
| Model favors the side at 60% or more while exact-line market is below 50% | 12 |
| Paid-evidence policy has one or more blocks | 15 |

The score is the sum of uncertainty and additional fragility, capped at 100. `Low` is 0–24, `Moderate` is 25–49, and `High` is 50–100. The output also carries specific support, risk, and invalidation statements. Missing data always raises uncertainty or remains neutral; it never creates favorable evidence.

These thresholds are product-policy heuristics, not fitted coefficients. They must be evaluated against settled outcomes before any claim that the labels predict losses. Paid-entry release policy remains independent and authoritative.
