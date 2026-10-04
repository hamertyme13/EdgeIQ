import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_recommendation_model_record_is_honest_and_escaped():
    script = r"""
const assert = require('node:assert/strict');
global.document = { addEventListener() {} };
global.window = global;
require('./web/static/js/model-track-record.js');
const render = global.EdgeIQModelTrackRecord.renderRecommendation;
const context = { model_version: 'v2.4', sport: 'WNBA', stat: 'Points', platform: 'PrizePicks', direction: 'Over' };
const row = { model_version: 'v2.4', platform: 'PrizePicks', direction: 'Over', settled_predictions: 2,
  actual_hit_rate: 50, predicted_hit_rate: 70, calibration_gap: -20, brier_score: 0.31, small_sample: true };
const html = render({ versions: [row], truncated: false }, context);
assert.match(html, /Small sample/);
assert.match(html, /Hit rate 50\.0%/);
assert.match(html, /Calibration gap -20\.0 pts/);
assert.match(render({ versions: [], truncated: false }, context), /no qualifying verified settled decisions/);
assert.match(render({ versions: [row], truncated: true }, context), /window is incomplete/);
assert.doesNotMatch(render({ versions: [row], truncated: false }, { ...context, stat: '<script>' }), /<script>/);
"""
    subprocess.run(["node", "-e", script], check=True)
