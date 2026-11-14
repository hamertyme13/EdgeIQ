import shutil
import subprocess
from pathlib import Path

import pytest


def test_selected_sport_follows_shared_active_scan():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const requests = [];
let displayed;
let polls = 0;
global.$ = id => ({value: id === 'today-sport' ? 'NBA' : 'PrizePicks'});
global.api = async path => {
  requests.push(path);
  return path.endsWith('platform=')
    ? {current:{status:'scanning_props',sport:'All Sports'}}
    : {current:{status:'ready',sport:'NBA'}};
};
global.renderDailyScanStatus = data => {displayed = data.current};
global.pollDailyScanStatus = () => {polls++};
eval(source.slice(source.indexOf('async function loadDailyScanStatus('), source.indexOf('function pollDailyScanStatus(')));
(async () => {
  await loadDailyScanStatus();
  assert.equal(displayed.status, 'scanning_props');
  assert.equal(displayed.sport, 'All Sports');
  assert.equal(polls, 1);
  assert.match(requests[0], /sport=NBA/);
  assert.equal(requests[1], '/api/daily-briefing/scan-status?platform=');
})().catch(error => {console.error(error); process.exitCode = 1});
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
