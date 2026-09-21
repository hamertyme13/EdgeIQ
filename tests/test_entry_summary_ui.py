import shutil
import subprocess
from pathlib import Path

import pytest


def test_summary_preserves_probabilities_and_payout_uncertainty():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for frontend presentation test")
    script = r'''
global.window = {};
require('./web/static/js/entry-summary.js');
const assert = require('node:assert/strict');
const data = {
 entry: {platform:'PrizePicks', props:[{player:'A',stat:'Points',game:'A-B'},{player:'B',stat:'Points',game:'A-B'},{player:'C',stat:'Assists'}]},
 model_payout_analysis: {all_hit_probability:22, independent_all_hit_probability:20, correlation_matrix:[[1,.3,-.2],[.3,1,0],[-.2,0,1]]},
 payout_analysis: {expected_value:80,displayed_multiplier:5}, platform_value:{payout_verified:false}
};
const render = () => window.EdgeIQEntrySummary.render(data, String);
const html = render();
for (const text of ['22.0%', '20.0%', '2.0 percentage points', 'Unverified payout', '(0.30)', '(-0.20)', 'A-B (2 legs)']) assert.ok(html.includes(text),text);
assert.ok(!html.includes('80.0%'));
data.platform_value.payout_verified=true;
assert.ok(render().includes('80.0%'));
data.model_payout_analysis={all_hit_probability:0};
assert.ok(render().includes('0.0%'));
assert.ok(render().includes('Unavailable'));
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
