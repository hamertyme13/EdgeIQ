import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-state test")
def test_market_state_keeps_latest_trending_response():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/state.js');
const market = global.EdgeIQState.market;
market.opportunitySelections.add(1);
market.compareSelections.add(2);
market.resetBriefingSelections();
assert.equal(market.opportunitySelections.size,0);
assert.equal(market.compareSelections.size,0);
market.trendingSelections.add(0);
const first = market.beginTrendingLoad();
assert.equal(market.trendingSelections.size,0);
const second = market.beginTrendingLoad();
assert.equal(market.acceptTrendingLoad(first,[{player:'Old'}]),false);
assert.equal(market.acceptTrendingLoad(second,[{player:'New'}]),true);
assert.equal(market.trendingProps[0].player,'New');
assert.equal(market.acceptTrendingLoad(second,null),true);
assert.deepEqual(market.trendingProps,[]);
"""
    subprocess.run(["node", "-e", script], check=True)


def test_market_state_is_single_source_for_app():
    app = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "const marketState = state.market;" in app
    assert "marketState.acceptTrendingLoad(requestId, data.props)" in app
    for field in ("opportunitySelections", "compareSelections", "compareTrackRecords", "trendingProps", "trendingSelections", "generatorRecentProps", "boardEvidence"):
        assert f"state.{field}" not in app
