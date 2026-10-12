(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const metric = (label, value) => `<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`;
  const percent = value => value != null && value !== "" && Number.isFinite(Number(value))
    ? `${Number(value).toFixed(0)}%` : "Unavailable";
  const quantity = value => value != null && value !== "" && Number.isFinite(Number(value))
    ? Number(value).toFixed(1).replace(/\.0$/, "") : "Unavailable";

  function render(prop, options = {}) {
    const index = Number(prop._sourceIndex);
    const calibration = prop.calibration_presentation || {};
    const receipt = prop.decision_receipt || {};
    const eligibility = prop.recommendation_eligibility || {};
    const score = prop.edgeiq_score || {};
    const expired = prop.recommendation_freshness?.status === "expired"
      || (prop.edgeiq_score_freshness && prop.edgeiq_score_freshness.status !== "fresh");
    const actionable = prop.actionable ?? Boolean(
      prop.market_supported !== false && Number(prop.trust?.score || 0) >= 50
      && Number(prop.confidence || 0) >= 52
    );
    const hasCalibration = ["CALIBRATED", "PARTIAL", "DEGRADED"].includes(calibration.status)
      && Number(calibration.sample_size) > 0 && Number.isFinite(Number(calibration.calibrated_probability));
    const calibrated = hasCalibration ? percent(calibration.calibrated_probability) : "Unavailable";
    const market = receipt.market_probability == null
      ? "No exact-line odds" : `${Number(receipt.market_book_count || 0)} book${Number(receipt.market_book_count || 0) === 1 ? "" : "s"} · ${percent(receipt.market_probability)}`;
    const freshness = expired ? "Expired · refresh" : prop.recommendation_freshness?.status === "fresh"
      ? "Fresh" : "Unverified";
    const offerType = prop.adjusted_line
      ? prop.is_discounted_line ? "Discounted line" : String(prop.line_offer_type || "").toLowerCase() === "demon" ? "Demon · Over only" : "Adjusted payout"
      : "Standard line";
    const status = expired ? prop.edgeiq_score_freshness?.label || "Expired · refresh required"
      : eligibility.label || (!actionable ? "Research only · cannot add" : "Fresh recommendation");
    const high = !expired && (Number(prop.confidence) >= 90 || Number(score.score) >= 90);
    const primaryProbability = hasCalibration ? calibrated : percent(prop.confidence);
    const primaryLabel = hasCalibration ? "Calibrated probability" : "Model probability";
    const fragility = prop.counterargument?.fragility_label || "Unavailable";
    const marketProbability = receipt.market_probability == null ? null : Number(receipt.market_probability);
    const edgeProbability = hasCalibration ? Number(calibration.calibrated_probability) : Number(prop.confidence);
    const comparison = Number.isFinite(marketProbability) && Number.isFinite(edgeProbability)
      ? `<div class="recommendation-probability-compare" aria-label="Market ${percent(marketProbability)}, EdgeIQ ${percent(edgeProbability)}">
          <span>Market ${percent(marketProbability)}</span><span>EdgeIQ ${percent(edgeProbability)}</span>
          <div class="recommendation-probability-track"><i style="left:${Math.max(0, Math.min(100, marketProbability))}%" title="Market probability"></i><b style="left:${Math.max(0, Math.min(100, edgeProbability))}%" title="EdgeIQ probability"></b></div>
        </div>` : "";
    return `<article class="opportunity-row recommendation-card ${expired ? "opportunity-expired" : ""} ${high ? "high-confidence-card" : ""}" data-risk-lane="${escape(prop.risk_profile?.key || "aggressive")}">
      ${high ? `<span class="high-confidence-banner">${Number(prop.confidence) >= 90 ? "High model confidence" : "High EdgeIQ score"}</span>` : ""}
      <div class="recommendation-card-heading">
        <label aria-label="Select ${escape(prop.player || `opportunity ${index + 1}`)}"><input class="opportunity-select" type="checkbox" data-select-opportunity="${index}" ${expired || !actionable ? "disabled" : ""} /></label>
        <div class="recommendation-card-identity"><strong>${escape(prop.player || "Player unavailable")}</strong><span>${escape(prop.stat || "Stat unavailable")} · <b>${escape(prop.direction || "Over")} ${quantity(prop.line)}</b></span><small>${escape(prop.platform || options.platform || "Provider")} · ${escape(prop.sport || options.sport || "Sport unavailable")} · ${escape(offerType)}</small></div>
        <div class="recommendation-card-score"><strong>${score.score == null ? "-" : quantity(score.score)}</strong><small>EdgeIQ Score · ${escape(score.label || "Unrated")}</small></div>
      </div>
      <dl class="recommendation-card-metrics">
        ${metric(primaryLabel, primaryProbability)}
        ${metric("Grade", score.label || "Unrated")}
        ${metric("Fragility", fragility)}
        ${metric("Evidence", freshness)}
      </dl>
      ${comparison}
      <p class="recommendation-card-context">Model ${percent(prop.confidence)} · Projection ${quantity(receipt.projection ?? prop.projection)} · ${escape(market)}</p>
      <p class="recommendation-card-status ${eligibility.paid_ready ? "success-text" : expired || !actionable ? "danger-text" : "warning-text"}">${escape(status)}</p>
      <div class="opportunity-actions recommendation-card-actions">
        <button class="secondary" type="button" data-add-opportunity="${index}" ${expired || !actionable ? "disabled" : ""}>Add to Entry</button>
        <button class="secondary" type="button" data-inspect-opportunity="${index}">Proof</button>
        <button class="secondary" type="button" data-timeline-opportunity="${index}">Timeline</button>
        <button class="secondary" type="button" data-compare-opportunity="${index}" aria-pressed="false">Compare</button>
      </div>
      ${window.EdgeIQRecommendationDisclosure?.render(prop) || ""}
    </article>`;
  }
  window.EdgeIQRecommendationCard = {render};
})();
