import shutil
import subprocess
from pathlib import Path

import pytest


def test_best_lines_transfer_guards():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for frontend transfer test")
    script = r'''
global.window = {};
global.document = {addEventListener() {}};
require('./web/static/js/best-lines.js');
const assert = require('node:assert/strict');
const check = window.EdgeIQBestLines.transferable;
const row = {platform:'PrizePicks', game:'A vs B', game_time:'2026-09-22T23:00:00Z', line:20.5};
assert.equal(check(row, 'Over'), true);
assert.equal(check(row, 'Under'), true);
assert.equal(check({...row, line_offer_type:'demon'}, 'Under'), false);
assert.equal(check({...row, line_offer_type:'demon'}, 'Over'), true);
assert.equal(check({...row, allowed_directions:['Under']}, 'Over'), false);
for (const value of [null, '', ' ', Infinity, 'invalid']) {
  assert.equal(check({...row, line:value}, 'Over'), false);
}
assert.equal(check({...row, line:0}, 'Over'), true);
assert.equal(check({...row, game_time:'invalid'}, 'Over'), false);
assert.equal(check({...row, game:''}, 'Over'), false);
assert.equal(check({...row, platform:''}, 'Over'), false);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
