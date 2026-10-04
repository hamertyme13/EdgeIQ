# Evidence Lab

Results > Evidence Lab is a read-only comparison of evidence recorded in locked prop forecasts. It uses the first eligible forecast per independent market, requires a named player identity, a pregame feature snapshot, verified final stats, and a matching line outcome. Legacy, estimated, postgame, tied, and contradictory records are excluded.

For each recorded evidence category, EdgeIQ shows the number of outcomes, hit rate, and Brier score when the evidence was present and absent. These are **descriptive associations**, not estimates of causal feature contribution. Sport, provider, stat, and model-version filters come from Model Performance. The comparison is marked thin when either side has fewer than 100 outcomes. It is capped at 5,000 matching settled prediction records and reports truncation.

Evidence is read from the immutable forecast feature snapshot and its pregame signals. Post-settlement research-evidence counters are not used for this comparison because a fact fetched after the forecast must not be treated as information available to the model at prediction time. Categories without captured pregame evidence are omitted from the display.

Controlled ablation is not available yet. It requires deterministic reconstruction of the original forecast with and without one feature, using only information available at the original prediction time. Until that replay path and chronological holdout evaluation exist, no evidence category is promoted to a weighted recommendation influence based on this view.
