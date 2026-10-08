import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_recommendation_disclosure_keeps_advanced_evidence_optional_and_escaped():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/recommendation-disclosure.js');
const render = global.EdgeIQRecommendationDisclosure.render;
const html = render({player: '<Player>', stat: 'Points', line: 20.5, direction: 'Under',
  projection: 18.2, model_version: '<script>',
  counterargument: {supporting_factors: ['Recent form <strong>'], risk_factors: ['Minutes uncertain']},
  calibration_presentation: {status: 'UNAVAILABLE', calibrated_probability: 99, sample_size: 200},
  decision_receipt: {market_probability: null, movement: {change: 0, snapshots: 1}}});
assert.match(html, /Why this pick\?/);
assert.match(html, /<details><summary>Evidence<\/summary>/);
assert.match(html, /<details><summary>Advanced diagnostics<\/summary>/);
assert.match(html, /Calibrated estimate<\/dt><dd>Unavailable/);
assert.match(html, /&lt;script&gt;/);
assert.doesNotMatch(html, /<script>/);
assert.match(html, /Recent form &lt;strong&gt;/);
assert.match(html, /Exact-line market probability unavailable/);
"""
    subprocess.run(["node", "-e", script], check=True)
