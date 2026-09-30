(function () {
  function render(score, escapeHtml, compact = false) {
    if (!score || !Number.isFinite(score.score)) return "";
    const number = Number(score.score).toFixed(0);
    const recorded = score.snapshot_id ? "Recorded EdgeIQ" : "EdgeIQ";
    const cap = score.cap_reason ? `Score capped: ${score.cap_reason}` : score.meaning;
    if (compact) {
      return `<span class="edgeiq-score-compact" title="${escapeHtml(cap)}" aria-label="EdgeIQ score ${number} out of 100. ${escapeHtml(cap)}"><b>${number}</b><small>${recorded} · ${escapeHtml(score.label)}${score.cap_reason ? " · Evidence capped" : ""}</small></span>`;
    }
    return `<section class="edgeiq-score-summary" aria-label="EdgeIQ Score">
      <div class="edgeiq-score-heading"><strong>${number}<small>/100</small></strong><div><h3>EdgeIQ Score · ${escapeHtml(score.label)}</h3><p>${escapeHtml(score.meaning)}</p></div></div>
      <p>${escapeHtml(score.summary)}</p>
      ${score.cap_reason ? `<p class="subtle">Score cap: ${escapeHtml(score.cap_reason)}</p>` : ""}
      ${score.paid_ready === false ? `<p class="subtle">This research score does not clear the recommendation for paid use.</p>` : ""}
      ${score.snapshot_id ? `<p class="subtle">Recorded ${escapeHtml(score.scored_at || "at scan time")}. Check current offer freshness before use.</p>` : ""}
      <details><summary>How this score is calculated</summary>
        <dl class="edgeiq-score-components">${Object.entries(score.components || {}).map(([key, value]) => `<div><dt>${escapeHtml(key.replaceAll("_", " "))}</dt><dd>${Number(value).toFixed(1)} / 100</dd></div>`).join("")}</dl>
        <ul>${[...(score.restrictions || []), ...(score.missing_evidence || [])].map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>
        <ul>${Object.entries(score.penalties || {}).filter(([, value]) => Number(value) < 0).map(([key, value]) => `<li>${escapeHtml(key.replaceAll("_", " "))}: ${Number(value).toFixed(1)} points</li>`).join("")}</ul>
      </details>
    </section>`;
  }
  window.EdgeIQOpportunityScore = { render };
}());
