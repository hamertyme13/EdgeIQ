(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const rate = value => value == null ? "Unavailable" : `${Number(value).toFixed(1)}%`;
  const brier = value => value == null ? "Unavailable" : Number(value).toFixed(4);

  function render(data) {
    const eligible = (data.categories || []).filter(row => row.included?.samples);
    if (!data.independent_outcomes) return `<p>No independently verified pregame prop outcomes match these filters yet.</p>`;
    return `<p><strong>${Number(data.independent_outcomes)} independent outcomes</strong> from ${Number(data.records_examined)} examined forecasts.</p>
      ${data.truncated ? `<p role="status">The 5,000-record window is incomplete. Narrow the Model Performance filters before interpreting this comparison.</p>` : ""}
      <div class="evidence-lab-list">${eligible.map(row => `<article class="evidence-lab-row">
        <h4>${escape(row.label)}</h4>
        <div><strong>Recorded</strong><span>${Number(row.included.samples)} outcomes · ${rate(row.included.hit_rate)} hit · Brier ${brier(row.included.brier)}</span></div>
        <div><strong>Not recorded</strong><span>${Number(row.not_included.samples)} outcomes · ${rate(row.not_included.hit_rate)} hit · Brier ${brier(row.not_included.brier)}</span></div>
        ${row.small_sample ? `<small>Small comparison group; interpret cautiously.</small>` : ""}
      </article>`).join("")}</div>
      <p class="subtle">${escape(data.note || "Descriptive associations only.")}</p>
      <p class="subtle">Ablation: ${escape(data.ablation?.reason || "Unavailable.")}</p>`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("evidence-lab-load");
    const output = document.getElementById("evidence-lab-output");
    button?.addEventListener("click", async () => {
      if (button.disabled || !output) return;
      const form = document.getElementById("model-track-form");
      const values = form ? new FormData(form) : new FormData();
      const params = new URLSearchParams();
      for (const name of ["sport", "provider", "stat", "model_version"]) params.set(name, String(values.get(name) || ""));
      button.disabled = true;
      output.setAttribute("aria-busy", "true");
      output.textContent = "Reviewing verified pregame outcomes...";
      try {
        const data = await window.EdgeIQApi.api(`/api/analytics/evidence-lab?${params}`, {timeoutMs: 20000});
        output.innerHTML = render(data);
      } catch {
        output.textContent = "Evidence Lab could not load. Try a narrower sport or model filter.";
      } finally {
        button.disabled = false;
        output.setAttribute("aria-busy", "false");
      }
    });
  });

  window.EdgeIQEvidenceLab = {render};
})();
