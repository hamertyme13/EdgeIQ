# Edge Timeline

Edge Timeline reconstructs a player's market history from immutable per-leg recommendation snapshots and linked provider-offer snapshots. It does not rewrite prior forecasts or infer an event that was never captured.

The Opportunity Board's **Timeline** button loads `GET /api/recommendations/timeline`. The endpoint requires `player` and accepts optional `sport`, `stat`, `game`, `platform`, and `limit` filters. Results are chronological and capped at 200 displayed events. A request with no saved snapshots returns an explicit empty state.

Events compare each saved state with the preceding state for the same provider, sport, game, stat, and direction. Currently identified changes are provider line, model projection, raw confidence, calibrated confidence, and grade. The initial saved state is marked `recommendation_created`. A snapshot whose tracked values are unchanged is not shown as a change. Event rows retain exact snapshot and offer IDs for audit.

This first phase does not claim to identify the cause of a model change. For example, a changed projection is not labeled as an injury update unless a separately timestamped, linked injury record supports that attribution. Provider-refresh timestamps and contextual evidence changes remain future work.
