import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_recommendation_disclosure_keeps_advanced_evidence_optional_and_escaped():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/forecast-range.js');
require('./web/static/js/recommendation-disclosure.js');
const render = global.EdgeIQRecommendationDisclosure.render;
const html = render({player: '<Player>', stat: 'Points', line: 20.5, direction: 'Under',
  projection: 18.2, model_version: '<script>',
  counterargument: {supporting_factors: ['Recent form <strong>'], risk_factors: ['Minutes uncertain']},
  calibration_presentation: {status: 'UNAVAILABLE', calibrated_probability: 99, sample_size: 200},
  decision_receipt: {market_probability: null, movement: {change: 0, snapshots: 1}}});
assert.match(html, /Why EdgeIQ likes it · Why this can lose/);
assert.match(html, /<details><summary>Evidence<\/summary>/);
assert.match(html, /<details><summary>Advanced diagnostics<\/summary>/);
assert.match(html, /Calibrated estimate<\/dt><dd>Unavailable/);
assert.match(html, /&lt;script&gt;/);
assert.doesNotMatch(html, /<script>/);
assert.match(html, /Recent form &lt;strong&gt;/);
assert.match(html, /Exact-line market probability unavailable/);
const partial = render({line: 20.5, projection: 22,
  calibration_presentation: {status: 'PARTIAL', label: 'Limited segment history', calibrated_probability: 59, sample_size: 30},
  forecast_snapshot: {distribution: {p25: 18, p75: 25}}});
assert.match(partial, /Calibrated estimate<\/dt><dd>Unavailable/);
assert.match(partial, /Provisional adjustment<\/dt><dd>59.0% · Limited segment history/);
assert.match(partial, /forecast-range-track/);
"""
    subprocess.run(["node", "-e", script], check=True)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_forecast_range_renders_only_valid_distribution_data():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/forecast-range.js');
const render = global.EdgeIQForecastRange.render;
const html = render({p25: 18.2, p75: 25.4, projection: 22, line: 20.5});
assert.match(html, /Expected range/);
assert.match(html, /Middle 50% of model outcomes 18.2 to 25.4/);
assert.match(html, /Projection 22/);
assert.match(html, /Line 20.5/);
assert.match(html, /forecast-range-band/);
assert.equal(render({p25: null, p75: 25, projection: 22, line: 20.5}), '');
assert.equal(render({p25: 30, p75: 25, projection: 22, line: 20.5}), '');
"""
    subprocess.run(["node", "-e", script], check=True)


def test_forecast_range_loads_before_disclosure_and_is_available_offline():
    html = Path("web/static/index.html").read_text(encoding="utf-8")
    service_worker = Path("web/static/sw.js").read_text(encoding="utf-8")
    assert html.index('src="/static/js/forecast-range.js') < html.index('src="/static/js/recommendation-disclosure.js')
    assert '"/static/js/forecast-range.js"' in service_worker
