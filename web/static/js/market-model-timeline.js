function renderMarketModelTimeline(timeline) {
  const events = Array.isArray(timeline?.events) ? timeline.events : [];
  const groups = new Map();
  for (const event of events) {
    const key = event.market_series_key || JSON.stringify([event.platform, event.game, event.stat, event.direction, event.offer_type]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(event);
  }
  const chartFor = (group) => {
    const observations = group.filter((event) => event.line != null && event.projection != null && Number.isFinite(Number(event.line)) && Number.isFinite(Number(event.projection)));
    if (!observations.length) return `<p class="subtle">No paired line and projection snapshots are available yet.</p>`;
    const values = observations.flatMap((event) => [Number(event.line), Number(event.projection)]);
    const low = Math.min(...values);
    const span = Math.max(Math.max(...values) - low, 1);
    const x = (index) => 32 + index * (436 / Math.max(observations.length - 1, 1));
    const y = (value) => 116 - ((Number(value) - low) / span) * 92;
    const series = (field, color) => {
      const points = observations.map((event, index) => `${x(index)},${y(event[field])}`).join(" ");
      return `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="2.5" />${observations.map((event, index) => `<circle cx="${x(index)}" cy="${y(event[field])}" r="3.5" fill="${color}" />`).join("")}`;
    };
    return `<div class="timeline-chart" role="img" aria-label="Market line and EdgeIQ projection across ${observations.length} saved observation${observations.length === 1 ? "" : "s"}">
      <svg viewBox="0 0 500 140" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
        <line x1="32" y1="116" x2="468" y2="116" stroke="currentColor" opacity=".25" />
        ${series("line", "#20c6d7")}${series("projection", "#39ff88")}
      </svg>
    </div>`;
  };
  const chart = [...groups.values()].map((group) => `<div><p class="subtle">${escapeHtml(group[0].game || "Game unavailable")} · ${escapeHtml(group[0].offer_type || "standard")} offer · ${escapeHtml(group[0].direction || "Side unavailable")}</p>${chartFor(group)}</div>`).join("") || `<p class="subtle">No saved observations are available yet.</p>`;
  const format = (value, suffix = "") => value == null || !Number.isFinite(Number(value)) ? "Unavailable" : `${Number(value).toFixed(1)}${suffix}`;
  return `<h3>Edge Timeline</h3><p>${escapeHtml(timeline?.summary || "No saved history yet.")}</p>
    <div class="timeline-legend"><span class="timeline-market-key">Market line</span><span class="timeline-model-key">EdgeIQ projection</span></div>
    ${chart}
    <p class="subtle">Closing-line value: ${timeline?.clv == null ? "Unavailable. No exact closing line has been verified for this market." : escapeHtml(format(timeline.clv))}</p>
    <ol class="timeline-observations">${events.map((event) => `<li>
      <strong>${escapeHtml(formatDateTime(event.created_at))}</strong> · ${escapeHtml(event.platform || "Provider")} · ${escapeHtml(event.model_version || "Model version unavailable")}
      <div>${escapeHtml((event.changes || []).map((change) => change.replaceAll("_", " ")).join(", ") || "No change")} · ${escapeHtml(event.offer_type || "standard")} offer</div>
      ${(event.change_reasons || []).map((reason) => `<p class="subtle">${escapeHtml(reason)}</p>`).join("")}
      <div>Line ${escapeHtml(format(event.line))} · Projection ${escapeHtml(format(event.projection))}</div>
      <div>Model probability ${escapeHtml(format(event.model_probability, "%"))} · ${event.calibration_context?.status && event.calibration_context.status !== "UNAVAILABLE" && event.calibrated_probability != null
        ? `Calibrated ${escapeHtml(format(event.calibrated_probability, "%"))} · ${escapeHtml(event.calibration_context.label || event.calibration_context.status)} · n=${Number(event.calibration_context.sample_size || 0)}`
        : "Calibration evidence status not saved for this snapshot"}</div>
    </li>`).join("")}</ol>`;
}
