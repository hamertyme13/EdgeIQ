import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_slate_change_summary_escapes_observed_events():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/slate-changes.js');
const render = global.EdgeIQSlateChanges.render;
const html = render({available:true,event_count:1,counts:{line_changes:1},
  scope:'Displayed games and ranked props',events:[{label:'<Player>',detail:'Line: 18.5 to 19.5'}]});
assert.match(html,/1 observed change in/);
assert.match(html,/1<\/strong> line moves/);
assert.match(html,/&lt;Player&gt;/);
assert.doesNotMatch(html,/<Player>/);
assert.match(render({available:false,message:'No earlier briefing'}),/No earlier briefing/);
"""
    subprocess.run(["node", "-e", script], check=True)
