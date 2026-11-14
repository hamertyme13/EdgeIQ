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


def test_preliminary_card_without_release_clearance_loads_to_paper():
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
  'prizepicks-generator-legs':{value:'2'},
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
global.providerBaseMultiplier = () => 3;
global.renderEntryPropsFromAnalyzed = () => {};
global.setView = () => {};
global.syncEntryActionLabels = () => {};
global.api = async () => ({suggestions:[{
  rank:1, grade:'B', action:'Track on Paper', leg_count:2, score:72.4, warnings:[],
  release_status:{ok:false}, entry:{props:[{player:'A'}]}, diversification:{prop_keys:[]},
}], diversification:{unique_props:1,reused_props:0}});
eval(source.slice(source.indexOf('async function loadProviderSuggestions('), source.indexOf('async function loadConfirmedEntries(')));
(async () => {
  await loadProviderSuggestions('PrizePicks','prizepicks-generator-sport','prizepicks-generator-legs','prizepicks-suggestions-list');
  assert.match(list.innerHTML, /Preliminary B/);
  assert.match(list.innerHTML, /No cleared entry today/);
  assert.match(list.innerHTML, /Load as Paper/);
  loadButton.click();
  assert.equal(elements['entry-mode'].value, 'paper');
  assert.match(elements['entry-status'].textContent, /grade is preliminary/);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)


def test_reviewed_card_shows_final_grade_and_full_card_probability():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const list = {innerHTML:'', querySelectorAll(){return [];}};
const elements = {
  'prizepicks-suggestions-list':list,
  'prizepicks-generator-sport':{value:'NBA'},
  'prizepicks-generator-legs':{value:'2'},
};
global.$ = id => elements[id];
global.marketState = {generatorRecentProps:{}};
global.escapeHtml = value => String(value);
global.gradeClass = () => '';
global.suggestionMetaRow = global.propPickList = global.confidenceMoveNotes = global.releaseStatusBlock = () => '';
global.api = async () => ({suggestions:[{
  rank:1, grade:'F', ranking_grade:'B', review_status:'complete', action:'Pass',
  leg_count:2, score:50.3, card_probability:24.06, warnings:[],
  release_status:{ok:false}, entry:{props:[{player:'A'}]}, diversification:{prop_keys:[]},
}], diversification:{unique_props:1,reused_props:0}});
eval(source.slice(source.indexOf('async function loadProviderSuggestions('), source.indexOf('async function loadConfirmedEntries(')));
(async () => {
  await loadProviderSuggestions('PrizePicks','prizepicks-generator-sport','prizepicks-generator-legs','prizepicks-suggestions-list');
  assert.match(list.innerHTML, /Reviewed F/);
  assert.match(list.innerHTML, /Reviewed score 50.3/);
  assert.match(list.innerHTML, /Full-card probability 24.1%/);
  assert.doesNotMatch(list.innerHTML, /Preliminary B/);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
