# Ask EdgeIQ Commands

Ask EdgeIQ now recognizes bounded, read-only questions about cached recommendation filters, evidence freshness and fragility, portfolio concentration, paid Personal Edge, a sport-filtered model track record, and a named player's saved recommendation timeline. The default flow is: fixed intent parser, typed query plan, existing EdgeIQ service response, deterministic answer with a snapshot citation. The local LLM is not used for recognized commands; open-ended questions retain the existing grounded Ollama path and citation checks. No command generates arbitrary SQL or places a wager.

The market filter searches only the cached briefing's top nine opportunities. A sample threshold checks the **matching calibration segment** count, not the broader fallback count. The timeline requires a player name and covers at most 30 saved changes, not a full-slate ranking. A comparison without identified offers, a full-slate change request, and market-disagreement ranking without matched no-vig evidence receive explicit limitations instead of invented results. Snapshot citations describe which app evidence was used; they are not external source URLs.

These commands do not claim profit, measured correlation, or complete market coverage. Refresh the briefing or select the relevant player/offer before acting on stale or incomplete evidence.

## Semantic Planner Preview

The existing rules-based commands remain the default fast path. Set `EDGEIQ_SEMANTIC_PLANNER_ENABLED=true` to let a local Ollama model classify questions that do not match those commands. The planner can only choose from a validated, read-only set of existing EdgeIQ analyses. It cannot request SQL, provider refreshes, URLs, file access, or entry changes. Invalid plans and local-model failures fall back to the existing grounded answer path.

Semantic plans now pass through a typed tool allowlist: cached briefing (top nine opportunities), portfolio risk, verified paid Personal Edge, a named player's latest 30 saved timeline changes, and sport-filtered model track record. Unknown tools and extra arguments are rejected. These are existing private-app data scopes, not yet per-account isolated tools; multi-user session memory and cross-account access must wait for explicit user identity and authorization boundaries.

`OLLAMA_PLANNER_MODEL` optionally selects a planner model and `OLLAMA_ANALYST_MODEL` selects the grounded answer model; both fall back to `OLLAMA_MODEL`. `OLLAMA_KEEP_ALIVE` controls residency for typed planner, analyst, and vision calls. `OLLAMA_PLANNER_NUM_PREDICT`, `OLLAMA_ANALYST_NUM_PREDICT`, and `OLLAMA_VISION_NUM_PREDICT` provide bounded output-token budgets. `EDGEIQ_COPILOT_MAX_TOOL_CALLS` and `EDGEIQ_COPILOT_MAX_EVIDENCE` may lower, but cannot raise, the current two-call and nine-fact safety ceilings. The preview searches cached briefing results only.

The app's **Check Model** button is a single-card grounding smoke test, not a qualification. The fixed 40-case suite (20 planner and 20 analyst) is documented in [Ollama qualification](OLLAMA_QUALIFICATION.md). It defaults to three repetitions and reports per-case failures, security screening, and local latency for both roles. `automatic_gates_passed` means only that the current fixture checks passed; it is not a release decision. The runner never promotes a model and always reports `qualified: false`. Schema/fact audit, a comparison with the currently qualified model, target-hardware profile, and human review remain required before promotion.

## Player Follow-ups

After research finds a player with saved history or a current recommendation, the browser temporarily keeps that player's name, sport, platform, and stat. A follow-up such as “What about her rebounds?” resolves the stat deterministically and runs a new research lookup. The focus expires after 45 minutes or a sport/platform switch; ambiguous questions ask for a player rather than guessing. This is browser-session focus, not a canonical player ID or authenticated cross-device conversation. It never asserts that a previous offer is still live. Multi-user server-side session persistence remains deferred until individual account authorization exists.

## Bounded Research Workflows

Two fixed, local-only workflows combine at most two read-only lookups and make no additional model call. A question about today's sport-specific model trust reads the cached briefing and that sport's settled prediction record, then explicitly warns that the historical record may not cover the same players. A question about recommendations and portfolio concentration reads paid exposure and the cached briefing. Its shortlist excludes only the **displayed top player exposures**; it does not certify that player, game, team, or exact-market overlap is absent. The result is a research lead, never a cleared paid pick. Expired snapshots and failed secondary lookups return partial or unavailable evidence without inventing validation. The six-second elapsed budget stops further tool calls but cannot interrupt an already-blocked repository read.

## Quantitative Grounding

Ollama's numeric statements are checked against typed values in the cited evidence: line, projection, probability, sample, result, EV, score, or stake. The verifier distinguishes players when names appear and accepts a 0–1 stored probability expressed as a percentage. A cited line cannot support a projection claim, and a user-entered requested line is never treated as a provider quote. A wrong-field claim receives one correction attempt, then falls back to the deterministic answer. This is a quantitative guardrail, not a complete semantic proof of every nonnumeric sentence.

Validated numeric claims now also return `fact_references` with the response field, stated number, and exact cited fact ID. This metadata is derived after grounding; it does not let Ollama choose its own fact IDs. Non-numeric prose is still not fact-level verified, so this is an incremental step toward claim-level output rather than a complete semantic guarantee.
The Quant view shows the checked numbers alongside their cited sources. An ambiguous number is not assigned to one source just because both sources contain it.
Explicit injury and starter assertions also require matching cited status fields. A derived “High DNP Risk” score is not proof a player is out, and an unconfirmed lineup is not proof a player is starting. Hypothetical and unknown-status wording remains allowed. This is a narrow categorical guard, not full semantic verification of every claim.

## Challenge a Recommendation

Today's opportunity cards include a Challenge action. It reads the selected prop's recorded counterargument, calibration state, tested line boundary, and offer freshness from the cached briefing. The action requires the exact snapshot ID and player/stat/line identity; if the shortlist changed or the briefing is older than 30 minutes, it asks for a refresh instead of analyzing another prop. This first version is deterministic and makes no Ollama call or live provider request. It identifies recorded risks and missing evidence, not a new probability or a claim that the offer is still available.

## Compare Recommendations

The existing 2–5 prop comparison on Today now supports evidence-based sorting by fully calibrated fresh segment size, calibrated probability, fragility, pending player overlap, model-market probability gap, and EdgeIQ Score. Its table also shows recorded line-sensitivity boundaries and matched market gaps. Missing evidence sorts last. A market gap is not provider-specific EV; pending-player overlap is not a correlation estimate. The comparison remains deterministic and does not ask Ollama to pick a winner.

## Answer Detail

Ask EdgeIQ has Quick, Standard, Analyst, and Quant display modes. Switching modes re-renders the same answer without rerunning Ollama or altering its evidence. Quick retains the bottom line, risk, unknowns, and citations. Analyst exposes source capture times. Quant also shows only finite numeric fields that were actually present in the cited briefing or current player recommendation; it explicitly says when no such breakdown exists. A requested player line is never shown as a provider line. These modes change presentation, not model qualification or the underlying forecast.

## Player Evidence Selection

Player research still retrieves its bounded saved evidence, but Ask EdgeIQ ranks it before prompting the local model. Selection favors the selected game, an exact requested provider line, relevant evidence type, fresh TTL, and verified history, while keeping distinct evidence categories represented. Expired provider markets, availability, and line movement are omitted. At most nine ranked memory facts reach the answer bundle, plus the existing saved recommendation citation. Citation metadata records why each fact was selected. This is an inspectable retrieval heuristic, not a trained evidence-usefulness model or a fresh provider verification.

## Research Progress

Ask EdgeIQ can stream actual planning, evidence retrieval, answer preparation, and grounding stages from `/api/ai/copilot/stream`. Only the fully validated structured answer is emitted as an answer event; raw model tokens are never displayed. The existing POST route remains available, and the browser falls back to it only when an older server returns 404 for the stream route. A failed stream returns a human-readable error without leaking provider internals. This status stream improves responsiveness but does not shorten the underlying provider or local-model work.

## Operational Telemetry

Each Ask EdgeIQ query emits one `copilot_trace` JSON log with a request ID, validated intent, planner/model selection, fallback flag, total and stage timings, tool and citation counts, and available Ollama planner/analyst token and duration counters. Correction attempts are included in the analyst totals and counted separately. It does not log the question, player name, raw answer, or evidence payload. Logging failures cannot interrupt the response. Use these timings to distinguish slow model loading from retrieval, answer generation, and grounding before changing output budgets or model routing. Missing provider counters are omitted rather than invented.
