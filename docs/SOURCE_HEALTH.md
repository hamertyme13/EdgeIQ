# Source Health

The Source Health section under Provider Status is loaded only when requested. It reports operational evidence, not prediction accuracy or provider quality rankings.

- Freshness and source role come from the existing provider health report.
- Availability and error rate use successful, not-modified, and failed network requests observed by the current app process. They are unavailable when no attempts were observed; they are not lifetime or cross-worker metrics.
- Offer-feed settlement coverage counts distinct tracked pregame prop market keys from the most recent 10,000 prediction records in the past 30 days, after a 24-hour final-stat window. A market counts as verified only with a settled outcome and recognized final-stat source. If the record cap is reached, the UI marks this coverage partial.
- Final-stat source coverage counts distinct ledger legs attempted with that source in the past 30 days, and how many were verified by that source. It is not coverage of every event that source might offer.
- Research fact counts and use/outcome-link counts cover individually attributed source records captured in the past 30 days. Composite source labels are deliberately not split among their component providers. Links can repeat across entries and are descriptive, not evidence of a causal improvement.

Unavailable metrics remain unavailable rather than becoming zero or an implied success rate. This report is intentionally read-only and does not trigger a provider refresh or settlement attempt.
