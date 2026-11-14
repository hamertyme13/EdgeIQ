import shutil
import subprocess
from pathlib import Path

import pytest


def test_entry_builder_has_three_gated_steps_and_one_primary_review_action() -> None:
    html = Path("web/static/index.html").read_text(encoding="utf-8")
    css = Path("web/static/styles.css").read_text(encoding="utf-8")
    assert html.index('data-entry-step="settings"') < html.index('data-entry-step="props"') < html.index('data-entry-step="review"')
    assert 'data-entry-step="review" disabled' in html
    assert 'id="entry-props-next"' in html
    assert 'id="entry-review-overview"' in html
    assert 'id="entry-find-offers"' in html
    assert 'id="entry-posted-offers"' in html
    assert '.entry-builder-table tr[data-entry-leg]' in css
    assert '.entry-review-overview[hidden]' in css


def test_review_step_switches_primary_action_only_after_current_analysis() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const elements = {
  'prop-form': {dataset:{activeStep:'review'}},
  'entry-mode': {value:'paper'}, 'entry-platform': {value:'PrizePicks'},
  'entry-wager': {value:'10'}, 'entry-payout-type': {value:'flex'},
  'entry-review-overview': {hidden:true, innerHTML:''},
  'analyze-entry': {hidden:true}, 'place-entry': {hidden:true},
};
global.$ = id => elements[id];
global.escapeHtml = value => String(value);
global.entrySourcePlatforms = () => [];
global.state = {entryProps:[{provider_backed:true,end_to_end_confirmed:true},{provider_backed:false,end_to_end_confirmed:false}]};
global.entryReviewState = {lastAnalysis:null,lastEntryPayload:null};
eval(source.slice(source.indexOf('function renderEntryReviewOverview()'), source.indexOf('function setupPerformanceDetails()')));
renderEntryReviewOverview();
assert.equal($('entry-review-overview').hidden,false);
assert.equal($('analyze-entry').hidden,false);
assert.equal($('place-entry').hidden,true);
assert.match($('entry-review-overview').innerHTML,/1\/2 legs/);
entryReviewState.lastAnalysis = {model_payout_analysis:{all_hit_probability:62.3},recommendation:{score:71},release_verdict:{verdict:'Paper first'}};
entryReviewState.lastEntryPayload = {props:[{},{}]};
renderEntryReviewOverview();
assert.equal($('analyze-entry').hidden,true);
assert.equal($('place-entry').hidden,false);
assert.match($('entry-review-overview').innerHTML,/62.3% estimate/);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
