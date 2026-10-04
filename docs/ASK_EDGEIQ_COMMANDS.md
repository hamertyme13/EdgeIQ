# Ask EdgeIQ Commands

Ask EdgeIQ now recognizes bounded, read-only questions about cached recommendation filters, evidence freshness and fragility, portfolio concentration, paid Personal Edge, a sport-filtered model track record, and a named player's saved recommendation timeline. The flow is: fixed intent parser, typed query plan, existing EdgeIQ service response, deterministic answer with a snapshot citation. The local LLM is not used for these commands; open-ended questions retain the existing grounded Ollama path and citation checks. No command generates arbitrary SQL or places a wager.

The market filter searches only the cached briefing's top nine opportunities. A sample threshold checks the **matching calibration segment** count, not the broader fallback count. The timeline requires a player name and covers at most 30 saved changes, not a full-slate ranking. A comparison without identified offers, a full-slate change request, and market-disagreement ranking without matched no-vig evidence receive explicit limitations instead of invented results. Snapshot citations describe which app evidence was used; they are not external source URLs.

These commands do not claim profit, measured correlation, or complete market coverage. Refresh the briefing or select the relevant player/offer before acting on stale or incomplete evidence.
