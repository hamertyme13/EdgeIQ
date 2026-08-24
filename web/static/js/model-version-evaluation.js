(function () {
  function render(evaluation, boardEvidence, helpers) {
    const escapeHtml = helpers.escapeHtml;
    const versions = evaluation?.versions || [];
    const comparison = evaluation?.v2_4_vs_v2_3 || {};
    const history = evaluation?.history_filter_comparison || {};
    const coverage = boardEvidence?.coverage || {};
    const model = boardEvidence?.model || {};
    const baseline = boardEvidence?.baseline || {};
    const segments = boardEvidence?.by_sport || [];
    const metric = (value, digits = 1) => value == null ? "-" : Number(value).toFixed(digits);
    return `
      <div class="suggestion evidence-dashboard ${comparison.ready && Number(comparison.brier_improvement) > 0 ? "insight-positive" : "insight-warning"}">
        <div class="suggestion-top"><strong>Model Evidence Dashboard</strong><span class="status-pill ${comparison.ready ? "status-connected" : "status-degraded"}">${comparison.ready ? "Version comparison ready" : "Collecting evidence"}</span></div>
        <div class="metric-strip evidence-coverage-strip">
          <span><strong>${Number(coverage.independent_offers || 0)}</strong><small>Board Offers</small></span>
          <span><strong>${Number(coverage.settled_offers || 0)}</strong><small>Verified Finals</small></span>
          <span><strong>${metric(coverage.settlement_rate)}%</strong><small>Settlement Coverage</small></span>
          <span><strong>${Number(coverage.rejected_or_unselected || 0)}</strong><small>Comparison Offers</small></span>
        </div>
        <div class="evidence-comparison-grid">
          <div><strong>EdgeIQ-analyzed</strong><span>${Number(model.samples || 0)} outcomes</span><span>${metric(model.hit_rate)}% hit rate</span><span>${metric(model.brier_score, 3)} Brier</span><span>${metric(model.average_clv, 2)} avg CLV</span></div>
          <div><strong>Unselected baseline</strong><span>${Number(baseline.samples || 0)} outcomes</span><span>${metric(baseline.hit_rate)}% hit rate</span><span>${boardEvidence?.selection_lift == null ? "Lift collecting" : `${metric(boardEvidence.selection_lift)} pt selection lift`}</span><span>Selection-bias check</span></div>
        </div>
        <div class="metric-strip">
          ${versions.slice(-3).map((row) => `<span><strong>${Number(row.brier_score).toFixed(3)}</strong><small>${escapeHtml(row.model_version.replace("edgeiq-", ""))} · ${Number(row.settled_predictions)} finals</small></span>`).join("")}
        </div>
        ${segments.length ? `<div class="evidence-segments">${segments.slice(0, 6).map((row) => `<span><strong>${escapeHtml(row.name)}</strong><small>${Number(row.samples)} finals · ${metric(row.hit_rate)}% hit · ${metric(row.calibration_gap)} pt gap</small></span>`).join("")}</div>` : ""}
        <p class="subtle">${escapeHtml(comparison.message || (comparison.ready ? `v2.4 Brier improvement versus v2.3: ${Number(comparison.brier_improvement).toFixed(4)}.` : evaluation?.message || "Waiting for settled versioned outcomes."))}</p>
        <p class="subtle">${history.ready ? `${Number(history.samples)} paired outcomes · ${escapeHtml(history.preferred)} currently has the lower Brier score.` : escapeHtml(history.message || "Current-season versus trailing-history comparison is collecting outcomes.")}</p>
        <p class="subtle">${escapeHtml(boardEvidence?.message || "Complete-board outcomes will appear after provider offers settle.")}</p>
      </div>`;
  }
  window.EdgeIQModelVersionEvaluation = { render };
}());
