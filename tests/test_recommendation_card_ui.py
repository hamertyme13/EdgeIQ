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
assert.match(html, /Model probability<\/dt><dd>62%/);
assert.doesNotMatch(html, /Calibrated probability<\/dt><dd>99%/);
assert.match(html, /EdgeIQ Score · Strong/);
assert.match(html, /No exact-line odds/);
assert.match(html, /Why EdgeIQ likes it · Why this can lose/);
assert.doesNotMatch(html, /recommendation-probability-track/);
assert.match(html, /data-add-opportunity="3"/);
assert.match(html, /data-select-opportunity="3"/);
assert.match(html, /&lt;Test Player&gt;/);
assert.doesNotMatch(html, /<Test Player>/);
const calibrated = render({...base,
  calibration_presentation: {status: 'CALIBRATED', calibrated_probability: 59, sample_size: 150},
  decision_receipt: {market_probability: 54, market_book_count: 2}});
assert.match(calibrated, /Calibrated probability<\/dt><dd>59%/);
assert.match(calibrated, /Market 54%/);
assert.match(calibrated, /EdgeIQ 59%/);
assert.match(calibrated, /recommendation-probability-track/);
const partial = render({...base,
  confidence: 59,
  calibration_presentation: {status: 'PARTIAL', label: 'Partial calibration evidence', model_probability: 64, calibrated_probability: 59, sample_size: 75},
  decision_receipt: {market_probability: 54, market_book_count: 2}});
assert.match(partial, /Provisional probability<\/dt><dd>59%/);
assert.doesNotMatch(partial, /Calibrated probability<\/dt><dd>59%/);
assert.match(partial, /Partial calibration evidence/);
assert.match(partial, /Provisional adjustment 59%/);
assert.match(partial, /Model 64%/);
assert.match(partial, /EdgeIQ 59%/);
const capped = render({...base, confidence: 65,
  calibration_presentation: {status: 'INSUFFICIENT_SAMPLE', model_probability: 93, sample_size: 0}});
assert.match(capped, /Capped model probability<\/dt><dd>65%/);
assert.match(capped, /Model 93%/);
assert.doesNotMatch(capped, /high-confidence-banner/);
const missingCalibration = render({...base,
  calibration_presentation: {status: 'CALIBRATED', calibrated_probability: null, sample_size: 150}});
assert.match(missingCalibration, /Model probability<\/dt><dd>62%/);
assert.doesNotMatch(missingCalibration, /Calibrated probability<\/dt><dd>0%/);
const expired = render({...base, recommendation_freshness: {status: 'expired'}});
assert.match(expired, /data-add-opportunity="3" disabled/);
assert.match(expired, /data-select-opportunity="3" disabled/);
"""
    subprocess.run(["node", "-e", script], check=True)
