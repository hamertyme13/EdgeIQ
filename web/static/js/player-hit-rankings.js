(function () {
  function number(value) {
    return value == null || value === "" ? "-" : Number(value).toFixed(1);
  }

  function render(rows, helpers) {
    const escapeHtml = helpers.escapeHtml;
    const pct = helpers.pct;
    return (rows || []).map((row, index) => {
      const uncertainty = row.uncertainty || {};
      const middle = `${number(uncertainty.percentile_25)}-${number(uncertainty.percentile_75)}`;
      const range = `${number(uncertainty.floor)}-${number(uncertainty.ceiling)}`;
      return `
        <article class="hit-stat-row">
          <span class="hit-stat-rank">${index + 1}</span>
          <div><strong>${escapeHtml(row.stat)} · ${escapeHtml(row.direction)} ${Number(row.line).toFixed(1)}</strong><small>${escapeHtml(row.platform || "Current market")} · average ${Number(row.season_average).toFixed(1)}</small></div>
          <div><strong>${pct(row.season_hit_rate)}</strong><small>Season · ${Number(row.sample_size)} games</small></div>
          <div><strong>${pct(row.recent_10_hit_rate)}</strong><small>Last 10</small></div>
          <div><strong>${middle}</strong><small>Middle 50% · ${range} range</small></div>
          <span class="status-pill ${row.sample_strength === "Strong" ? "status-positive" : "status-warning"}" title="${escapeHtml(row.note || "")}">${escapeHtml(row.sample_strength)} · ${escapeHtml(uncertainty.level || "Unknown")}</span>
        </article>`;
    }).join("");
  }

  window.EdgeIQPlayerHitRankings = { render };
}());
