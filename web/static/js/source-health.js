(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const percent = value => value == null ? "Unavailable" : `${Number(value).toFixed(1)}%`;

  function render(data) {
    const sources = data.sources || [];
    return `${data.truncated ? `<p role="status">The 10,000-prediction window is incomplete. Treat tracked-prop coverage as partial.</p>` : ""}
      <div class="source-health-list">${sources.map(row => {
        const coverage = row.settlement_coverage || {};
        const research = row.research_evidence || {};
        const network = Number(row.network_attempts_this_session || 0);
        return `<section class="source-health-row">
          <div class="source-health-title"><strong>${escape(row.name)}</strong><span>${escape(String(row.status || "unknown").replaceAll("_", " "))}</span></div>
          <p>${escape(row.data_role || "Source role unavailable")} · ${escape(row.settlement_suitability || "Settlement scope unavailable")}</p>
          <dl>
            <div><dt>Freshness</dt><dd>${row.last_success_at ? `${escape(String(row.status || "unknown").replaceAll("_", " "))} · ${row.age_minutes == null ? "age unavailable" : `${Number(row.age_minutes)} min since success`}` : "No successful refresh recorded"}</dd></div>
            <div><dt>Availability</dt><dd>${network ? `${percent(row.availability_percent_this_session)} of ${network} network attempts this session` : "Unavailable; no network attempts measured this session"}</dd></div>
            <div><dt>Error rate</dt><dd>${network ? `${percent(row.error_percent_this_session)} this session` : "Unavailable"}</dd></div>
            <div><dt>Settlement coverage</dt><dd>${coverage.percent == null ? "Unavailable" : `${percent(coverage.percent)} · ${Number(coverage.verified || 0)}/${Number(coverage.eligible || 0)}`}<small>${escape(coverage.scope || "Scope unavailable")}</small></dd></div>
            <div><dt>Evidence use</dt><dd>${Number(research.facts || 0)} facts · ${Number(research.uses || 0)} uses · ${Number(research.linked_outcomes || 0)} outcome links</dd></div>
          </dl>
          <p class="subtle">${escape(String(row.source_type || "unknown").replaceAll("_", " "))} · ${row.officially_documented ? "Documented source" : "Undocumented or unverified contract"}</p>
        </section>`;
      }).join("") || `<p>No source measurements are available.</p>`}</div>
      <p class="subtle">${escape(data.note || "Source measurements are limited to tracked activity.")}</p>`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("source-health-load");
    const output = document.getElementById("source-health-output");
    button?.addEventListener("click", async () => {
      if (button.disabled || !output) return;
      button.disabled = true;
      output.setAttribute("aria-busy", "true");
      output.textContent = "Checking source measurements...";
      try {
        const data = await window.EdgeIQApi.api("/api/providers/source-health", {timeoutMs: 20000});
        output.innerHTML = render(data);
      } catch {
        output.textContent = "Source measurements could not load. Try again after provider status refreshes.";
      } finally {
        button.disabled = false;
        output.setAttribute("aria-busy", "false");
      }
    });
  });

  window.EdgeIQSourceHealth = {render};
})();
