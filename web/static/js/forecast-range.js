(() => {
  const finite = value => value != null && value !== "" && Number.isFinite(Number(value)) ? Number(value) : null;
  const label = value => Number(value).toFixed(1).replace(/\.0$/, "");

  function render({ p25, p75, projection, line }) {
    const low = finite(p25), high = finite(p75), expected = finite(projection), marketLine = finite(line);
    if (low === null || high === null || expected === null || low > high) return "";
    const values = [low, high, expected, marketLine].filter(value => value !== null);
    const min = Math.min(...values), max = Math.max(...values);
    const padding = Math.max(0.5, (max - min) * 0.12);
    const axisMin = min - padding, axisWidth = max - min + padding * 2;
    const position = value => ((value - axisMin) / axisWidth * 100).toFixed(1);
    const bandWidth = Math.max(1, Number(position(high)) - Number(position(low))).toFixed(1);
    const description = `Middle 50% of model outcomes ${label(low)} to ${label(high)}. Projection ${label(expected)}.${marketLine === null ? "" : ` Current line ${label(marketLine)}.`}`;
    return `<div class="forecast-range" role="img" aria-label="${description}">
      <div class="forecast-range-heading"><strong>Expected range</strong><small>Middle 50% of model outcomes</small></div>
      <div class="forecast-range-track" aria-hidden="true">
        <span class="forecast-range-band" style="left:${position(low)}%;width:${bandWidth}%"></span>
        <span class="forecast-range-marker forecast-range-projection" style="left:${position(expected)}%"></span>
        ${marketLine === null ? "" : `<span class="forecast-range-marker forecast-range-line" style="left:${position(marketLine)}%"></span>`}
      </div>
      <div class="forecast-range-legend"><span>Range ${label(low)}–${label(high)}</span><span>Projection ${label(expected)}</span>${marketLine === null ? "" : `<span>Line ${label(marketLine)}</span>`}</div>
    </div>`;
  }

  window.EdgeIQForecastRange = {render};
})();
