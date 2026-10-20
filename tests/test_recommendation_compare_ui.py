import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_recommendation_comparison_sorts_only_by_selected_evidence():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/recommendation-compare.js');
const compare = global.EdgeIQRecommendationCompare;
const alpha = {player: '<Alpha>', sport: 'WNBA', platform: 'PrizePicks', stat: 'Points', direction: 'Over', line: 20.5,
  model_version: 'v2.4', score: 99, edgeiq_score: {score: 70},
  calibration_presentation: {status: 'CALIBRATED', calibrated_probability: 64, sample_size: 120, segment_sample_size: 120},
  counterargument: {fragility_label: 'Low', fragility_score: 15},
  forecast_snapshot: {standard_deviation: 4.2},
  recommendation_freshness: {status: 'fresh'},
  sensitivity: {status: 'model_only', first_tested_failing_line: 21.5},
  decision_receipt: {market_probability: 60, model_market_edge: 4, market_book_count: 2,
    portfolio_exposure: {same_player_entries: 2, label: '2 pending player entries'}}};
const beta = {player: 'Beta', sport: 'WNBA', platform: 'Underdog', stat: 'Points', direction: 'Under', line: 18.5,
  model_version: 'v2.4', edgeiq_score: {score: 85},
  calibration_presentation: {status: 'PARTIAL', calibrated_probability: 61, sample_size: 40, segment_sample_size: 40},
  counterargument: {fragility_label: 'High', fragility_score: 60},
  decision_receipt: {market_probability: 50, model_market_edge: 11, market_book_count: 3,
    portfolio_exposure: {same_player_entries: 0, label: 'No matching pending exposure'}}};
assert.equal(compare.sorted([alpha, beta], 'calibrated')[0].player, '<Alpha>');
assert.equal(compare.sorted([alpha, beta], 'fragility')[0].player, '<Alpha>');
assert.equal(compare.sorted([alpha, beta], 'score')[0].player, 'Beta');
assert.equal(compare.sorted([alpha, beta], 'supported')[0].player, '<Alpha>');
assert.equal(compare.sorted([alpha, beta], 'overlap')[0].player, 'Beta');
assert.equal(compare.sorted([alpha, beta], 'market')[0].player, 'Beta');
const unsupported = {...beta, player: 'Unsupported', calibration_presentation: {status: 'UNAVAILABLE', calibrated_probability: 99, sample_size: 200}};
assert.equal(compare.sorted([unsupported, alpha], 'calibrated')[0].player, '<Alpha>');
const records = {[compare.trackKey(alpha)]: {versions: [{model_version: 'v2.4', platform: 'PrizePicks', direction: 'Over', actual_hit_rate: 55, settled_predictions: 30}]}};
const html = compare.render([alpha, beta], 'calibrated', records);
assert.match(html, /Highest calibrated probability/);
assert.match(html, /55\.0% observed/);
assert.match(html, /Forecast standard deviation/);
assert.match(html, /Tested failure at 21\.5/);
assert.match(html, /Model-market gap/);
assert.match(html, /4\.2/);
assert.match(html, /Unavailable/);
assert.match(html, /&lt;Alpha&gt;/);
assert.doesNotMatch(html, /<Alpha>/);
assert.match(compare.render([alpha], 'score'), /Select 2 to 5/);
assert.match(compare.render([alpha, beta], 'market'), /not verified EV/);
assert.match(compare.render([alpha, beta], 'supported'), /fully calibrated segments/);
"""
    subprocess.run(["node", "-e", script], check=True)
