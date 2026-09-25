import shutil
import subprocess
from pathlib import Path

import pytest


def test_analysis_ignores_changed_entries_and_preserves_completed_review():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const elements = {};
global.$ = id => elements[id] ||= {disabled:true, textContent:''};
global.state = {entryProps:[{line:1},{line:2}]};
global.entryPayload = () => ({props:state.entryProps, entry_mode:'paper'});
global.entrySourcePlatforms = () => ['Sleeper'];
global.entryAnalysisValidationMessage = () => '';
global.trackProductEvent = global.renderEntryProps = global.syncEntryActionLabels = () => {};
let rendered = null;
global.renderAnalysis = data => rendered = data;
global.renderEntryPropsFromAnalyzed = props => {state.lastAnalysis=null; state.entryProps=props;};
eval(source.slice(source.indexOf('async function analyzeEntry('), source.indexOf('async function reviewEntryWithAi(')));
(async () => {
  let finish;
  global.api = () => new Promise(resolve => finish=resolve);
  const data = {entry:{props:[{line:3},{line:4}]}};
  const first = analyzeEntry();
  state.entryProps = [{line:5},{line:6}];
  finish(data);
  await first;
  assert.equal(rendered,null);
  assert.equal(state.entryProps[0].line,5);
  assert.equal($('place-entry').disabled,true);
  const second = analyzeEntry();
  finish(data);
  await second;
  assert.equal(state.lastAnalysis,data);
  assert.equal(rendered,data);
  assert.equal($('place-entry').disabled,false);
})().catch(error => {console.error(error); process.exit(1);});
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
