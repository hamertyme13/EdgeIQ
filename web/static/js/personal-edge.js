(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const cache = new Map();
  const dimensions = {sport: "Sport", stat: "Stat", sport_stat: "Sport and stat", provider: "Provider", direction: "Direction", confidence_bucket: "Confidence bucket", card_size: "Card size", grade: "Card grade"};
  const rate = value => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)}%` : "Unavailable";
  function render(data, dimension = "sport") {
    const summary = data.summary || {};
    const cards = dimension === "card_size" || dimension === "grade";
    const rows = cards ? (data[dimension] || []) : ((data.segments || {})[dimension] || []);
    const label = dimensions[dimension] || "Segment";
    const highlight = (title, item) => item ? `<p><strong>${title}:</strong> ${escape(item.name)} (${rate(item.hit_rate)}, ${escape(item.decisions)} verified legs). Descriptive only.</p>` : "";
    return `<div class="personal-edge-overview">
        <div><strong>${escape(summary.settled_entries ?? 0)}</strong><small>Settled ${data.mode === "paper" ? "paper" : "paid"} cards</small></div>
        <div><strong>${escape(summary.verified_leg_decisions ?? 0)}</strong><small>Verified leg decisions</small></div>
        <div><strong>${rate(summary.leg_hit_rate)}</strong><small>Tracked leg hit rate</small></div>
        <div><strong>${escape(summary.excluded_legs ?? 0)}</strong><small>Excluded legs</small></div>
      </div>
      ${data.truncated ? '<p role="status">Only the newest 5,000 placements are shown. Rankings are withheld because the history is incomplete.</p>' : ""}
      ${highlight("Highest observed", data.strongest)}${highlight("Lowest observed", data.weakest)}
      <h4>${escape(label)}</h4>
      <div class="personal-edge-rows">${rows.map(row => `<div class="personal-edge-row">
        <strong>${escape(row.name)}</strong><span>${escape(row.wins)} won · ${escape(row.losses)} lost</span>
        <span>${rate(cards ? row.win_rate : row.hit_rate)} ${cards ? "card win rate" : "leg hit rate"}</span>
        <small>${escape(row.decisions)} ${cards ? "cards" : "verified legs"}${row.small_sample ? " · Small sample" : ""}</small>
        ${cards && data.mode === "real" ? `<small>Max recorded drawdown: ${row.max_drawdown == null ? "Unavailable" : `$${Number(row.max_drawdown).toFixed(2)}`}</small>` : ""}
      </div>`).join("") || `<p>No ${escape(label.toLowerCase())} results are available from settled history.</p>`}</div>
      <p class="subtle">Segments with fewer than ${escape(data.sample_threshold ?? 30)} decisions are small samples. ${escape((data.limitations || [])[0] || "")}</p>
      <p class="subtle">${escape((data.limitations || [])[1] || "")} ${escape((data.limitations || [])[2] || "")} ${escape((data.limitations || [])[3] || "")}</p>`;
  }
  document.addEventListener("DOMContentLoaded", () => {
    const panel = document.getElementById("personal-edge");
    const output = document.getElementById("personal-edge-output");
    const mode = document.getElementById("personal-edge-mode");
    const dimension = document.getElementById("personal-edge-dimension");
    const refresh = document.getElementById("refresh-personal-edge");
    if (!panel || !output || !mode || !dimension || !refresh) return;
    let requestId = 0;
    async function load(force = false) {
      if (!panel.open) return;
      const selected = mode.value;
      const current = ++requestId;
      const cached = cache.get(selected);
      if (!force && cached && Date.now() - cached.at < 60000) {
        output.innerHTML = render(cached.data, dimension.value);
        return;
      }
      refresh.disabled = true;
      output.setAttribute("aria-busy", "true");
      output.textContent = "Reviewing settled entries...";
      try {
        const data = await window.EdgeIQApi.api(`/api/analytics/personal-edge?mode=${encodeURIComponent(selected)}`, {timeoutMs: 20000});
        cache.set(selected, {data, at: Date.now()});
        if (current === requestId) output.innerHTML = render(data, dimension.value);
      } catch {
        if (current === requestId) output.textContent = "Personal Edge could not load. Please refresh and try again.";
      } finally {
        if (current === requestId) {
          refresh.disabled = false;
          output.setAttribute("aria-busy", "false");
        }
      }
    }
    panel.addEventListener("toggle", () => { if (panel.open) load(); });
    mode.addEventListener("change", () => load());
    dimension.addEventListener("change", () => {
      const cached = cache.get(mode.value);
      if (cached) output.innerHTML = render(cached.data, dimension.value);
    });
    refresh.addEventListener("click", () => load(true));
  });
  window.EdgeIQPersonalEdge = {render};
})();
