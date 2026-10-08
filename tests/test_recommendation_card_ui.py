import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_recommendation_card_keeps_score_probability_and_eligibility_distinct():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/recommendation-disclosure.js');
require('./web/static/js/recommendation-card.js');
const render = global.EdgeIQRecommendationCard.render;
const base = {_sourceIndex: 3, player: '<Test Player>', sport: 'WNBA', platform: 'PrizePicks',
  stat: 'Points', line: 20.5, direction: 'Under', confidence: 62, projection: 18,
  edgeiq_score: {score: 85, label: 'Strong'},
  calibration_presentation: {status: 'UNAVAILABLE', calibrated_probability: 99, sample_size: 200},
  recommendation_eligibility: {label: 'Paper only', paper_ready: true, paid_ready: false},
  recommendation_freshness: {status: 'fresh'},
  counterargument: {fragility_label: 'Moderate'},
  decision_receipt: {market_probability: null}};
const html = render(base);
assert.match(html, /EdgeIQ probability<\/dt><dd>62%/);
assert.match(html, /Calibrated probability<\/dt><dd>Unavailable/);
assert.match(html, /EdgeIQ Score · Strong/);
assert.match(html, /Market status<\/dt><dd>No exact-line odds/);
assert.match(html, /data-add-opportunity="3"/);
assert.match(html, /data-select-opportunity="3"/);
assert.match(html, /&lt;Test Player&gt;/);
assert.doesNotMatch(html, /<Test Player>/);
const expired = render({...base, recommendation_freshness: {status: 'expired'}});
assert.match(expired, /data-add-opportunity="3" disabled/);
assert.match(expired, /data-select-opportunity="3" disabled/);
"""
    subprocess.run(["node", "-e", script], check=True)
