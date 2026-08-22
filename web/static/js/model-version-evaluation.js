(function () {
  function render(evaluation, helpers) {
    const escapeHtml = helpers.escapeHtml;
    const versions = evaluation?.versions || [];
    const comparison = evaluation?.v2_4_vs_v2_3 || {};
    const history = evaluation?.history_filter_comparison || {};
    return `
      <div class="suggestion ${comparison.ready && Number(comparison.brier_improvement) > 0 ? "insight-positive" : "insight-warning"}">
        <div class="suggestion-top"><strong>Model Version Comparison</strong><span class="status-pill ${comparison.ready ? "status-connected" : "status-degraded"}">${comparison.ready ? "Tracking" : "Collecting"}</span></div>
        <div class="metric-strip">
          ${versions.slice(-3).map((row) => `<span><strong>${Number(row.brier_score).toFixed(3)}</strong><small>${escapeHtml(row.model_version.replace("edgeiq-", ""))} · ${Number(row.settled_predictions)} finals</small></span>`).join("")}
        </div>
        <p class="subtle">${escapeHtml(comparison.message || (comparison.ready ? `v2.4 Brier improvement versus v2.3: ${Number(comparison.brier_improvement).toFixed(4)}.` : evaluation?.message || "Waiting for settled versioned outcomes."))}</p>
        <p class="subtle">${history.ready ? `${Number(history.samples)} paired outcomes · ${escapeHtml(history.preferred)} currently has the lower Brier score.` : escapeHtml(history.message || "Current-season versus trailing-history comparison is collecting outcomes.")}</p>
      </div>`;
  }
  window.EdgeIQModelVersionEvaluation = { render };
}());
