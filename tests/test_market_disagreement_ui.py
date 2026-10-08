import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_market_disagreement_renders_calibration_and_uncertainty_safely():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/market-disagreement.js');
const render = global.EdgeIQMarketDisagreement.render;
const html = render({message: 'One comparison', rows: [{player:'<script>',direction:'Over',line:19.5,stat:'Points',
  platform:'PrizePicks',sport:'WNBA',market_book_count:2,model_probability:61,market_probability:54,
  raw_difference:7,calibrated_probability:58,effective_difference:4,calibration_samples:120,
  calibration_uncertainty_points:3,within_calibration_uncertainty:true,market_timestamp_coverage:1,context:'One-book or thin-calibration evidence'}]});
assert.match(html, /\+7\.0 pts/);
assert.match(html, /\+4\.0 pts/);
assert.match(html, /Calibration uncertainty/);
assert.match(html, /within calibration uncertainty/);
assert.match(html, /Some book timestamps unavailable/);
assert.match(html, /&lt;script&gt;/);
assert.doesNotMatch(html, /<script>/);
const unsupported = render({rows:[{player:'A',direction:'Over',line:19.5,stat:'Points',
  calibrated_probability:null,effective_difference:null,context:'Calibration unsupported; raw model difference only'}]});
assert.match(unsupported, /Unsupported calibration/);
assert.match(unsupported, /raw model difference only/);
assert.match(render({message:'No current market',rows:[]}), /No validated exact-line comparison/);
"""
    subprocess.run(["node", "-e", script], check=True)
