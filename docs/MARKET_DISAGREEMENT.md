# Market Disagreement

Today's Market Disagreement view compares EdgeIQ's pre-calibration model probability and calibrated probability with a **paired, exact-line, no-vig** sportsbook consensus captured in the cached briefing. It displays raw difference (`model - market`) and effective difference (`calibrated - market`) in percentage points, matching calibration sample count, available calibration uncertainty, book count, and timestamp coverage. Differences inside the stated calibration uncertainty are labeled as such. Ask EdgeIQ uses the same calculation for disagreement questions.

The service requires The Odds API's multi-book no-vig source, matching player/stat/direction/line, a current cached market response, and valid paired American over/under odds for every contributing book. It recalculates the no-vig side probability from those odds and rejects a conflicting stored probability. Stale briefings, missing odds, mismatched lines, invalid probabilities, and unsupported model estimates do not produce a comparison. One-book or thin-calibration results carry a caution label.

The view reads only the briefing's top nine opportunities; it does not scan the full board or call a live odds provider. A percentage-point difference is **not EV or a profit estimate**. Provider-specific payout and exact offer availability still require separate verification before paid use.
