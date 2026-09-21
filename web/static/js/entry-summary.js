(() => {
  function render(data, escape) {
    const props = data.entry?.props || [];
    const model = data.model_payout_analysis || {};
    const finite = (value) => typeof value === "number" && Number.isFinite(value);
    const percent = (value) => finite(value) ? `${value.toFixed(1)}%` : "Unavailable";
    const adjusted = model.all_hit_probability, independent = model.independent_all_hit_probability;
    const delta = finite(adjusted) && finite(independent) ? `${(adjusted - independent).toFixed(1)} percentage points` : "Unavailable";
    const payout = data.payout_analysis || {};
    const exposure = [["Player", "player"], ["Team", "team"], ["Game", "game"], ["Stat", "stat"], ["Direction", "direction"]].map(([label, key]) => {
      const counts = new Map();
      props.forEach((prop) => { const value = String(prop[key] || "Unknown"); counts.set(value, (counts.get(value) || 0) + 1); });
      return `<li><strong>${label}:</strong> ${[...counts].map(([value, count]) => `${escape(value)} (${count} legs)`).join(", ") || "Unavailable"}</li>`;
    }).join("");
    const pairs = [];
    props.forEach((left, i) => props.slice(i + 1).forEach((right, offset) => {
      const value = model.correlation_matrix?.[i]?.[i + offset + 1];
      if (finite(value) && value !== 0) pairs.push({ value, label: `${left.player} ${left.stat} / ${right.player} ${right.stat}` });
    }));
    const positive = pairs.filter(p => p.value > 0).sort((a, b) => b.value - a.value)[0];
    const negative = pairs.filter(p => p.value < 0).sort((a, b) => a.value - b.value)[0];
    const pairLabel = (pair) => pair ? `${escape(pair.label)} (${pair.value.toFixed(2)})` : "None reported";
    return `<section class="consumer-entry-summary"><h3>Entry summary</h3>
      <p>${escape(data.entry?.platform || "Platform unavailable")} · ${props.length} legs · ${escape(data.risk?.level || "Unknown")} risk</p>
      <dl><div><dt>Complete-card probability (correlation adjusted)</dt><dd>${percent(adjusted)}</dd></div>
      <div><dt>Independent probability</dt><dd>${percent(independent)}</dd></div>
      <div><dt>Correlation difference</dt><dd>${delta}</dd></div>
      <div><dt>Displayed multiplier</dt><dd>${finite(payout.displayed_multiplier) ? `${payout.displayed_multiplier}x` : "Unavailable"}</dd></div>
      <div><dt>Expected value</dt><dd>${data.platform_value?.payout_verified === true ? percent(payout.expected_value) : "Unverified payout"}</dd></div></dl>
      <p class="subtle">All-leg win probability is not profit probability. These are estimates, not guaranteed outcomes.</p>
      <details><summary>Correlation and diversification</summary><ul><li>Strongest positive pair: ${pairLabel(positive)}</li><li>Strongest negative pair: ${pairLabel(negative)}</li></ul>
      <p>${positive ? "Some legs share outcome risk. A higher joint probability does not mean better diversification." : "No positive pair was reported; this does not establish independence."}</p>
      ${negative ? "<p>The negatively related legs may work against each other.</p>" : ""}
      <h4>Exposure within this entry</h4><ul>${exposure}</ul><p class="subtle">Repeated players and games concentrate exposure. Unknown labels mean exposure could not be fully assessed.</p></details></section>`;
  }
  window.EdgeIQEntrySummary = { render };
})();
