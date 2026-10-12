import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-state test")
def test_review_state_invalidates_payload_and_guards_duplicate_placement():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/state.js');
const review = window.EdgeIQState.entry.review;
assert.equal(review.beginPlacement(),false);
review.lastAnalysis = {score:88};
review.lastEntryPayload = {props:[{player:'A'}]};
assert.equal(review.beginPlacement(),true);
assert.equal(review.beginPlacement(),false);
const previous = review.analysisRequestId;
assert.equal(review.invalidate(),previous + 1);
assert.equal(review.lastAnalysis,null);
assert.equal(review.lastEntryPayload,null);
review.endPlacement();
assert.equal(review.placementInFlight,false);
assert.equal(review.beginPlacement(),false);
"""
    subprocess.run(["node", "-e", script], check=True)
