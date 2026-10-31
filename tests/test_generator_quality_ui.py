import shutil
import subprocess
from pathlib import Path

import pytest


def test_pass_card_loads_to_paper_and_is_not_presented_as_cleared():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const loadButton = {dataset:{loadProviderSuggestion:'0'}, addEventListener(_name, callback){this.click = callback;}};
const list = {
  innerHTML:'',
  querySelectorAll(selector){return selector === '[data-load-provider-suggestion]' ? [loadButton] : [];},
};
const elements = {
  'prizepicks-suggestions-list':list,
  'prizepicks-generator-sport':{value:'NBA'},
  'prizepicks-generator-legs':{value:'3'},
  'entry-mode':{value:'real'},
  'entry-multiplier':{value:'3'},
  'entry-payout-type':{value:'standard'},
  'entry-status':{textContent:''},
};
global.$ = id => elements[id];
global.marketState = {generatorRecentProps:{}};
global.state = {recommendationOrigin:false};
global.escapeHtml = value => String(value);
global.gradeClass = () => '';
global.suggestionMetaRow = global.propPickList = global.confidenceMoveNotes = global.releaseStatusBlock = () => '';
global.providerBaseMultiplier = () => 5;
global.renderEntryPropsFromAnalyzed = () => {};
global.setView = () => {};
let labelSyncs = 0;
global.syncEntryActionLabels = () => {labelSyncs++;};
global.api = async () => ({suggestions:[{
  rank:1, grade:'F', action:'Pass', leg_count:3, score:20, warnings:[],
  entry:{props:[{player:'A'}]}, diversification:{prop_keys:[]},
}], diversification:{unique_props:1,reused_props:0}});
eval(source.slice(source.indexOf('async function loadProviderSuggestions('), source.indexOf('async function loadConfirmedEntries(')));
(async () => {
  await loadProviderSuggestions('PrizePicks','prizepicks-generator-sport','prizepicks-generator-legs','prizepicks-suggestions-list');
  assert.match(list.innerHTML, /No cleared entry today/);
  assert.match(list.innerHTML, /Load as Paper/);
  loadButton.click();
  assert.equal(elements['entry-mode'].value, 'paper');
  assert.equal(labelSyncs, 1);
  assert.match(elements['entry-status'].textContent, /graded it Pass/);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
