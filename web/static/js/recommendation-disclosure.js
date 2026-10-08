(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const number = (value, suffix = "") => value != null && value !== "" && Number.isFinite(Number(value))
    ? `${Number(value).toFixed(1)}${suffix}` : "Unavailable";
  const list = (items, fallback) => items.length
    ? `<ul>${items.map(item => `<li>${escape(item)}</li>`).join("")}</ul>`
    : `<p>${escape(fallback)}</p>`;

  function render(prop) {
    const receipt = prop.decision_receipt || {};
    const calibration = prop.calibration_presentation || {};
    const argument = prop.counterargument || {};
    const movement = receipt.movement || {};
    const features = prop.forecast_snapshot?.features || {};
    const distribution = prop.forecast_snapshot?.distribution || {};
    const supports = (argument.supporting_factors || []).slice(0, 4);
    const risks = (argument.risk_factors || []).slice(0, 4);
    const market = receipt.market_probability == null
      ? "Exact-line market probability unavailable"
      : `Exact-line market probability ${number(receipt.market_probability, "%")} from ${Number(receipt.market_book_count || 0)} books`;
    const history = [
      features.recent_5_mean == null ? null : `Last 5 average: ${number(features.recent_5_mean)}`,
      features.last_10_average == null ? null : `Last 10 average: ${number(features.last_10_average)}`,
      features.season_average == null ? null : `Season average: ${number(features.season_average)}`,
      features.opponent_sample == null ? null : `Opponent sample: ${escape(features.opponent_sample)}`,
    ].filter(Boolean);
    return `<details class="opportunity-disclosure">
      <summary>Why this pick?</summary>
      <div class="opportunity-disclosure-body">
        <p><strong>Projection</strong> ${number(receipt.projection ?? prop.projection)} against ${escape(prop.direction || "Over")} ${number(prop.line)}. ${escape(market)}.</p>
        <div class="opportunity-disclosure-columns">
          <div><strong>Supporting factors</strong>${list(supports, "No supporting factors recorded for this snapshot.")}</div>
          <div><strong>What could go wrong</strong>${list(risks, "No counterarguments recorded. This does not mean the pick is risk-free.")}</div>
        </div>
        <details><summary>Evidence</summary>
          <p>${escape(calibration.label || "Calibration unavailable")} · ${Number(calibration.sample_size || 0)} matching settled forecasts.</p>
          <p>${escape(prop.recommendation_freshness?.status || "Freshness unavailable")} · Line move ${number(movement.change)} across ${Number(movement.snapshots || 0)} snapshots.</p>
          ${list(history, "No historical feature summary was stored with this recommendation.")}
          <details><summary>Advanced diagnostics</summary>
            <dl>
              <div><dt>Original model estimate</dt><dd>${number(calibration.model_probability, "%")}</dd></div>
              <div><dt>Calibrated estimate</dt><dd>${["CALIBRATED", "PARTIAL", "DEGRADED"].includes(calibration.status) && Number(calibration.sample_size) > 0 ? number(calibration.calibrated_probability, "%") : "Unavailable"}</dd></div>
              <div><dt>Forecast deviation</dt><dd>${number(prop.forecast_snapshot?.standard_deviation)}</dd></div>
              <div><dt>Distribution interval</dt><dd>${distribution.p25 == null || distribution.p75 == null ? "Unavailable" : `${number(distribution.p25)} to ${number(distribution.p75)}`}</dd></div>
              <div><dt>Model version</dt><dd>${escape(prop.model_version || "Unavailable")}</dd></div>
              <div><dt>Recommendation snapshot</dt><dd>${escape(prop.recommendation_snapshot_id || "Unavailable")}</dd></div>
            </dl>
            <p>Historical accuracy, Brier score and calibration curves are in Results. These diagnostics do not guarantee a winning entry.</p>
          </details>
        </details>
      </div>
    </details>`;
  }
  window.EdgeIQRecommendationDisclosure = {render};
})();
