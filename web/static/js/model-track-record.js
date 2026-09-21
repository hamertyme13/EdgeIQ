(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const metric = value => typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "Unavailable";
  function render(data) {
    const counts = [["Locked predictions", data.locked_predictions], ["Verified settled", data.settled_predictions], ["Wins", data.wins], ["Losses", data.losses], ["Pushes", data.pushes], ["Unresolved or excluded", data.unresolved_or_excluded]];
    return `<div class="model-track-counts">${counts.map(([label, value]) => `<div><strong>${escape(value)}</strong><small>${label}</small></div>`).join("")}</div>
      <p class="subtle">${escape(data.counting_note)}</p>
      ${data.truncated ? `<p role="status">This view is limited to the first 5,000 matching records. Narrow the filters to review a smaller segment.</p>` : ""}
      ${(data.versions || []).map(row => `<article class="model-track-segment"><h4>${escape(row.model_version)} · ${escape(row.platform)} · ${escape(row.direction)}</h4>
        <p>${row.settled_predictions} independent decisions${row.small_sample ? " · Small sample: not proof of a reliable edge" : ""}</p>
        <dl><div><dt>Win rate</dt><dd>${metric(row.actual_hit_rate)}%</dd></div><div><dt>Average forecast</dt><dd>${metric(row.predicted_hit_rate)}%</dd></div><div><dt>Calibration gap</dt><dd>${metric(row.calibration_gap)} percentage points</dd></div><div><dt>Brier score</dt><dd>${escape(row.brier_score)}</dd></div></dl></article>`).join("") || "<p>No qualifying settled decisions match these filters. Locked or legacy records alone are not proof of model accuracy.</p>"}
      <p class="subtle">Verified ROI, CLV, and stored-score bucket linkage are unavailable in this view. No profitability or paid-use approval is implied.</p>`;
  }
  document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("model-track-form");
    form?.addEventListener("submit", async event => {
      event.preventDefault();
      const button = form.querySelector("button");
      if (button.disabled) return;
      const output = document.getElementById("model-track-output");
      const params = new URLSearchParams(new FormData(form));
      button.disabled = true; button.textContent = "Loading...";
      output.setAttribute("aria-busy", "true"); output.textContent = "Checking locked prediction evidence...";
      try { output.innerHTML = render(await window.EdgeIQApi.api(`/api/analytics/model-track-record?${params}`, {timeoutMs:20000})); }
      catch { output.textContent = "The model record could not load. Try a narrower filter or refresh again shortly."; }
      finally { button.disabled = false; button.textContent = "View Record"; output.setAttribute("aria-busy", "false"); }
    });
  });
  window.EdgeIQModelTrackRecord = { render };
})();
