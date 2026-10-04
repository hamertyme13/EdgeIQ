(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const finite = value => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) ? Number(value) : null;
  const value = (number, suffix = "") => finite(number) === null ? "Unavailable" : `${finite(number).toFixed(1)}${suffix}`;
  const labels = {calibrated: "Highest calibrated probability", fragility: "Lowest fragility", score: "Highest EdgeIQ Score"};
  const trackKey = prop => [prop.model_version, prop.sport, prop.stat, prop.platform, prop.direction].join("|");
  function metric(prop, selected) {
    if (selected === "calibrated") return finite(prop.calibration_presentation?.calibrated_probability);
    if (selected === "fragility") return finite(prop.counterargument?.fragility_score);
    return finite(prop.edgeiq_score?.score);
  }
  function sorted(props, selected) {
    return props.map((prop, index) => ({prop, index, score: metric(prop, selected)})).sort((a, b) => {
      if (a.score === null) return b.score === null ? a.index - b.index : 1;
      if (b.score === null) return -1;
      return (selected === "fragility" ? a.score - b.score : b.score - a.score) || a.index - b.index;
    }).map(row => row.prop);
  }
  function render(props, selected = "calibrated", records = {}) {
    if (props.length < 2 || props.length > 5) return '<p>Select 2 to 5 recommendations to compare.</p>';
    const ordered = sorted(props, selected);
    const cells = getter => ordered.map(prop => `<td>${escape(getter(prop))}</td>`).join("");
    const line = (label, getter) => `<tr><th scope="row">${escape(label)}</th>${cells(getter)}</tr>`;
    const record = prop => {
      const data = records[trackKey(prop)];
      if (!prop.model_version) return "Unavailable: no model version";
      if (!data) return "Loading verified record...";
      if (data.error) return "Record unavailable";
      if (data.truncated) return "Incomplete record window";
      const item = (data.versions || []).find(row => row.model_version === prop.model_version && row.platform === prop.platform && row.direction === prop.direction);
      return item ? `${value(item.actual_hit_rate, "%")} observed · ${item.settled_predictions} decisions` : "No qualifying settled decisions";
    };
    const availability = prop => {
      const freshness = prop.recommendation_freshness?.status;
      if (freshness === "expired") return "Expired · refresh required";
      if (prop.recommendation_eligibility?.paid_ready) return "Paid-ready in EdgeIQ; confirm live offer";
      if (prop.recommendation_eligibility?.paper_ready) return "Paper-ready; paid evidence incomplete";
      return "Not verified for entry";
    };
    return `<p class="subtle">Sorted by ${escape(labels[selected] || labels.calibrated)}. Missing values sort last. This is a comparison, not a guaranteed winner.</p>
      <div class="recommendation-compare-scroll" role="region" aria-label="Recommendation comparison" tabindex="0"><table class="recommendation-compare-table" style="min-width:${180 + ordered.length * 180}px">
        <thead><tr><th scope="col">Evidence</th>${ordered.map(prop => `<th scope="col">${escape(prop.player)}<small>${escape(prop.platform)} · ${escape(prop.sport)}</small></th>`).join("")}</tr></thead>
        <tbody>
          ${line("Stat / direction", prop => `${prop.stat || "Unavailable"} · ${prop.direction || "Unavailable"}`)}
          ${line("Line", prop => value(prop.line))}
          ${line("Projection", prop => value(prop.projection))}
          ${line("Model probability", prop => value(prop.calibration_presentation?.model_probability, "%"))}
          ${line("Calibrated probability", prop => value(prop.calibration_presentation?.calibrated_probability, "%"))}
          ${line("Matching calibration samples", prop => prop.calibration_presentation?.segment_sample_size ?? "Unavailable")}
          ${line("Data quality score", prop => value(prop.data_quality?.score, "/100"))}
          ${line("Forecast standard deviation", prop => value(prop.forecast_snapshot?.distribution?.standard_deviation))}
          ${line("Fragility", prop => prop.counterargument?.fragility_label ? `${prop.counterargument.fragility_label} · ${value(prop.counterargument.fragility_score, "/100")}` : "Unavailable")}
          ${line("Line movement", prop => value(prop.decision_receipt?.movement?.change ?? prop.line_movement?.change))}
          ${line("Model track record", record)}
          ${line("Evidence freshness", prop => prop.recommendation_freshness?.status || "Unavailable")}
          ${line("Provider availability", availability)}
          ${line("Portfolio overlap", prop => prop.decision_receipt?.portfolio_exposure?.label || "Unavailable")}
          ${line("EdgeIQ Score", prop => value(prop.edgeiq_score?.score, "/100"))}
        </tbody></table></div>
      <p class="subtle">Observed track records are historical and may include a small sample. Provider availability must be rechecked before any paid entry.</p>`;
  }
  window.EdgeIQRecommendationCompare = {render, sorted, trackKey};
})();
