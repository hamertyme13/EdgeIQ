import shutil
import subprocess
from pathlib import Path

import pytest


def test_portfolio_batch_shows_request_failure_without_waiting_for_summary():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync('web/static/app.js', 'utf8');
const html = fs.readFileSync('web/static/index.html', 'utf8');
const select = html.match(/<select id="optimizer-sport"[^>]*>([\s\S]*?)<\/select>/)?.[1] || '';
assert.match(select, /<option selected>All Sports<\/option>/);
const elements = {};
global.$ = id => elements[id] ||= {innerHTML:'',value:id==='optimizer-legs'?'2-3':id==='optimizer-platform'?'PrizePicks':id==='optimizer-sport'?'All Sports':'',checked:false};
global.escapeHtml = value => String(value);
global.humanizeErrorText = value => String(value);
let requests = 0;
global.api = async path => { requests++; assert.match(path, /batch=true/); throw new Error('Provider temporarily unavailable'); };
global.loadPortfolioIntelligence = async () => { throw new Error('Summary should not block generation'); };
eval(source.slice(source.indexOf('async function runOptimizer('),source.indexOf('async function loadPending(')));
runOptimizer(true).then(() => {
  assert.equal(requests, 1);
  assert.match($('optimizer-list').innerHTML, /Cards could not be generated/);
  assert.match($('optimizer-list').innerHTML, /Provider temporarily unavailable/);
  assert.doesNotMatch($('optimizer-list').innerHTML, /Building five diversified cards/);
}).catch(error => { throw error; });
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
