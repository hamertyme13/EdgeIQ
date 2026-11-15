import shutil
import subprocess
from pathlib import Path

import pytest


def test_ready_now_requires_fresh_exact_today_offer_and_one_best_stat_per_player():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const window = {};
new Function('window', fs.readFileSync('web/static/js/ready-now.js', 'utf8'))(window);
const now = new Date('2026-11-14T15:00:00Z');
const base = {
  player: 'Example Player', game: 'BOS @ NYK', game_time: '2026-11-14T23:00:00Z',
  platform: 'PrizePicks', provider_offer_id: 'offer-1', provider_backed: true,
  provider_offer_verified_at: '2026-11-14T14:58:00Z',
  feature_as_of: '2026-11-14T14:45:00Z',
  end_to_end_confirmed: true, recommendation_freshness: {status: 'fresh'},
  recommendation_eligibility: {paid_ready: true}, actionable: true,
};
const {lane, prepare} = window.EdgeIQReadyNow;
assert.equal(lane(base, now), 'ready');
assert.equal(lane({...base, provider_offer_id: ''}, now), 'review');
assert.equal(lane({...base, game_time: '2026-11-15T23:00:00Z'}, now), 'review');
assert.equal(lane({...base, game_time: '2026-11-14T14:00:00Z'}, now), 'review');
assert.equal(lane({...base, recommendation_eligibility: {paid_ready: false}}, now), 'paper');
assert.equal(lane({...base, provider_offer_verified_at: '2026-11-14T14:54:00Z'}, now), 'paper');
assert.equal(lane({...base, provider_offer_verified_at: '2026-11-14T14:29:00Z'}, now), 'review');
assert.equal(lane({...base, provider_offer_verified_at: ''}, now), 'review');
assert.equal(lane({...base, feature_as_of: '2026-11-14T14:29:00Z'}, now), 'review');
assert.equal(lane({...base, decision_receipt: {valid_until: '2026-11-14T14:59:00Z'}}, now), 'review');
const rows = prepare([
  {...base, _sourceIndex: 0, edgeiq_score: {score: 80}},
  {...base, _sourceIndex: 1, player: 'Exámple Player', edgeiq_score: {score: 92}},
  {...base, _sourceIndex: 2, player: 'Other Player', edgeiq_score: {score: 75}},
], now);
assert.deepEqual(rows.map(row => row._sourceIndex), [1, 2]);
const {planTransfer} = window.EdgeIQReadyNow;
const existing = [{player:'Alyssa Thomas', platform:'PrizePicks', stat:'Points'}];
const next = [{player:'Breanna Stewart', platform:'PrizePicks', direction:'Over', allowed_directions:['Over']}];
assert.equal(planTransfer(existing, next, 6).added, 1);
assert.deepEqual(planTransfer(existing, next, 6).props.map(prop => prop.player), ['Alyssa Thomas', 'Breanna Stewart']);
assert.equal(existing.length, 1);
assert.match(planTransfer(existing, [{...next[0], platform:'Underdog'}], 6).error, /one sportsbook/i);
assert.match(planTransfer(existing, [{...next[0], player:'Alýssa Thomas'}], 6).error, /already on the slip/i);
assert.match(planTransfer(existing, next, 1).error, /up to 1 legs/i);
assert.match(planTransfer(existing, [{...next[0], direction:'Under'}], 6).error, /does not offer Under/i);
assert.match(planTransfer([], [next[0], {...next[0]}], 6).error, /already on the slip/i);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)


def test_ready_now_and_selected_handoff_are_visible_in_frontend():
    root = Path(__file__).resolve().parents[1]
    index = (root / "web/static/index.html").read_text()
    app = (root / "web/static/app.js").read_text()
    assert 'js/ready-now.js' in index
    assert 'data-opportunity-ready="ready"' in app
    assert 'data-opportunity-ready="paper"' in app
    assert 'data-opportunity-ready="review"' in app
    assert 'data.handoff_platform || data.platform' in app
    assert 'EdgeIQReadyNow.planTransfer(' in app
