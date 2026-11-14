import shutil
import subprocess
from pathlib import Path

import pytest


def test_entry_handoffs_open_builder_without_changing_normal_navigation():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const calls = [];
const entry = {classList:{add(){}, contains(){return true}}, matches(){return false}, querySelector(){return null}};
global.$ = id => id === 'entries' ? entry : id === 'view-title' ? {set textContent(value){}} : null;
global.document = {
  querySelectorAll(){return [{classList:{add(){}, remove(){}}, removeAttribute(){}, setAttribute(){}}]},
  querySelector(selector){
    if (selector === '[data-entry-mode="build"]') return {click(){calls.push('build')}};
    return null;
  },
};
global.state = {providerHealth:null};
global.loadViewData = () => calls.push('load');
eval(source.slice(source.indexOf('function setView('), source.indexOf('document.addEventListener("edgeiq:game-to-props"')));
setView('entries');
assert.deepEqual(calls, ['load']);
calls.length = 0;
setView('entries', {showBuilder:true});
assert.deepEqual(calls, ['build', 'load']);
assert.equal((source.match(/setView\("entries", \{ showBuilder: true \}\)/g) || []).length, 17);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
