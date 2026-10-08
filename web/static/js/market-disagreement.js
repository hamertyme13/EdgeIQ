(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const number = value => value == null || !Number.isFinite(Number(value)) ? "Unavailable" : `${Number(value).toFixed(1)}%`;
  const points = value => value == null || !Number.isFinite(Number(value)) ? "Unavailable" : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(1)} pts`;
  function render(data) {
    const rows = data.rows || [];
    return `<p class="subtle">${escape(data.message || "Market comparison is unavailable.")}</p>
      ${rows.map(row => `<div class="market-disagreement-row">
        <div><strong>${escape(row.player)} ${escape(row.direction)} ${escape(row.line)} ${escape(row.stat)}</strong><small>${escape(row.platform)} · ${escape(row.sport)} · ${escape(row.market_book_count)} paired book${row.market_book_count === 1 ? "" : "s"}</small></div>
        <div><span>Model</span><strong>${number(row.model_probability)}</strong></div>
        <div><span>Market no-vig</span><strong>${number(row.market_probability)}</strong></div>
        <div><span>Raw difference</span><strong>${points(row.raw_difference)}</strong></div>
        <div><span>Calibrated</span><strong>${number(row.calibrated_probability)}</strong><small>${row.calibrated_probability == null ? "Unsupported calibration" : `${escape(row.calibration_samples)} matching samples · ${escape(row.calibration_status || "status unavailable")}`}</small></div>
        <div><span>Effective difference</span><strong>${points(row.effective_difference)}</strong></div>
        <p class="subtle">${escape(row.context)}${row.calibration_uncertainty_points == null ? " · Calibration uncertainty unavailable" : ` · Calibration uncertainty ±${escape(row.calibration_uncertainty_points)} pts`}${row.within_calibration_uncertainty === true ? " · Effective difference is within calibration uncertainty" : ""}${row.market_timestamp_coverage < row.market_book_count ? " · Some book timestamps unavailable" : ""}</p>
      </div>`).join("") || `<p>No validated exact-line comparison is available for the current top opportunities.</p>`}
      <p class="subtle">${escape(data.note || "A probability difference is not a profit estimate.")}</p>`;
  }
  window.EdgeIQMarketDisagreement = {render};
})();
