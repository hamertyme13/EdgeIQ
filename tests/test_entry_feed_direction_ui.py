import shutil
import subprocess
from pathlib import Path

import pytest


def test_entry_feed_direction_guard():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const fs = require('fs');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/static/app.js', 'utf8');
eval(source.slice(source.indexOf('function entryDirectionAllowed('), source.indexOf('function loadPaperProps(')));
const status = {textContent: ''};
global.$ = () => status;
global.setView = () => {};
const prop = {platform:'Sleeper', player:'Example', direction:'Over', allowed_directions:['Under']};
assert.equal(addFeedProp(prop), false);
assert.match(status.textContent, /does not support Over/);
for (const value of [[], null, 'Over']) {
  assert.equal(addFeedProp({...prop, allowed_directions:value}), false);
}
const premium = {...prop, platform:'PrizePicks', line_offer_type:'demon', direction:'Under'};
assert.equal(addFeedProp(premium), false);
assert.equal(entryPropFromFeed(premium).direction, 'Under');
assert.deepEqual(entryPropFromFeed({...prop, direction:'Under'}).allowed_directions, ['Under']);
assert.deepEqual(entryPropFromFeed({platform:'Sleeper'}).allowed_directions, ['Over','Under']);
assert.equal(entryDirectionAllowed(prop, 'Over'), false);
assert.equal(entryDirectionAllowed(prop, 'Under'), true);
assert.equal(entryDirectionAllowed(premium, 'Under'), false);
assert.equal(entryDirectionAllowed({...premium, allowed_directions:['Over']}, 'Over'), true);
assert.equal(entryDirectionAllowed({...prop, allowed_directions:[]}, 'Under'), false);
assert.equal(entryDirectionAllowed({platform:'Sleeper'}, 'Under'), true);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
