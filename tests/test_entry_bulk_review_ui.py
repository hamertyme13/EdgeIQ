import shutil
import subprocess
from pathlib import Path

import pytest


def test_bulk_loading_invalidates_review_without_changing_picks():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const elements = {};
global.$ = id => elements[id] ||= {disabled:false, textContent:'old', classList:{add(){}}};
global.window = global;
require('./web/static/js/state.js');
global.state = window.EdgeIQState;
global.entryReviewState = state.entry.review;
entryReviewState.lastAnalysis = {score:90};
entryReviewState.lastEntryPayload = {old:true};
state.recommendationSnapshotId = 'old';
global.renderEntryProps = () => {};
global.setView = () => {};
eval(source.slice(source.indexOf('function entryPropFromFeed('), source.indexOf('function entrySourcePlatforms(')));
eval(source.slice(source.indexOf('function invalidateEntryReview('), source.indexOf('async function manageDatabase(')));
const props = [{player:'Example', platform:'Sleeper', direction:'Over', allowed_directions:['Under']}];
loadPaperProps(props);
assert.equal(entryReviewState.lastAnalysis, null);
assert.equal(entryReviewState.lastEntryPayload, null);
assert.equal(state.recommendationSnapshotId, '');
for (const id of ['ai-review-entry','prepare-handoff','place-entry']) assert.equal($(id).disabled,true);
assert.equal(state.entryProps[0].direction, 'Over');
assert.deepEqual(state.entryProps[0].allowed_directions, ['Under']);
assert.equal($('entry-mode').value, 'paper');
loadPaperProps(null);
assert.equal(state.entryProps.length, 0);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
