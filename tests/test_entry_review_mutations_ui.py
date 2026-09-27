import shutil
import subprocess
from pathlib import Path

import pytest


def test_adding_a_leg_invalidates_previous_analysis_and_save_payload():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const elements = {};
global.$ = id => elements[id] ||= {disabled:false, textContent:'', classList:{add(){}}, value:'PrizePicks'};
global.state = {
  entryProps:[{player:'A',stat:'Points',game_time:'1',platform:'PrizePicks'}],
  lastAnalysis:{score:90}, lastEntryPayload:{props:[{player:'A'}]},
  recommendationSnapshotId:'old-id', entryAnalysisRequestId:4
};
global.setView = global.renderEntryProps = global.trackProductEvent = () => {};
eval(source.slice(source.indexOf('function entryDirectionAllowed('), source.indexOf('function loadPaperProps(')));
eval(source.slice(source.indexOf('function invalidateEntryReview('), source.indexOf('function loadPaperProps(')));
const added = addFeedProp({player:'B', stat:'Points', line:12.5, game_time:'2',
  platform:'PrizePicks', direction:'Over', recommendation_snapshot_id:'new-id'});
assert.equal(added, true);
assert.equal(state.entryProps.length, 2);
assert.equal(state.lastAnalysis, null);
assert.equal(state.lastEntryPayload, null);
assert.equal(state.entryAnalysisRequestId, 5);
assert.equal(state.recommendationSnapshotId, 'new-id');
for (const id of ['ai-review-entry','prepare-handoff','place-entry']) assert.equal($(id).disabled,true);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)


def test_save_ignores_stale_provider_check_and_preserves_newer_builder_edits():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const elements = {};
global.$ = id => elements[id] ||= {value:'', textContent:'', disabled:false};
const button = {textContent:'Place Paid Entry'};
global.state = {entryProps:[{player:'A'}], lastEntryPayload:{props:[{player:'A'}], entry_mode:'real'}, entryAnalysisRequestId:1};
global.syncEntryPlatformFromProps = () => ['PrizePicks'];
global.parsePayoutSchedule = () => [];
global.renderPlacementAudit = global.trackProductEvent = global.playCircuitSound = global.finishCircuitFeedback = () => {};
global.money = value => `$${value}`;
global.renderEntryProps = global.loadPending = global.loadDashboard = global.loadCommandCenter = () => {};
global.window = {confirm:() => true};
$('entry-mode').value='real'; $('entry-wager').value='10'; $('entry-multiplier').value='3';
eval(source.slice(source.indexOf('async function placeEntry('), source.indexOf('async function loadProviderSuggestions(')));
(async () => {
  let finishCheck;
  let saves=0;
  global.api = path => path.endsWith('placement-check')
    ? new Promise(resolve => finishCheck=resolve)
    : (saves++, Promise.resolve({id:1,settlement_tracking:'verified'}));
  const first=placeEntry(button);
  state.lastEntryPayload=null;
  state.entryAnalysisRequestId++;
  state.entryProps=[{player:'B'}];
  finishCheck({ok:true, blocks:[], warnings:[]});
  assert.equal(await first,false);
  assert.equal(saves,0);
  assert.deepEqual(state.entryProps,[{player:'B'}]);

  state.lastEntryPayload={props:[{player:'C'}], entry_mode:'real'};
  state.entryProps=[{player:'C'}];
  let finishSave;
  global.api = path => path.endsWith('placement-check')
    ? Promise.resolve({ok:true, blocks:[], warnings:[]})
    : (saves++, new Promise(resolve => finishSave=resolve));
  const second=placeEntry(button);
  await new Promise(resolve => setImmediate(resolve));
  state.lastEntryPayload=null;
  state.entryAnalysisRequestId++;
  state.entryProps=[{player:'D'}];
  finishSave({id:2,settlement_tracking:'verified'});
  assert.equal(await second,true);
  assert.equal(saves,1);
  assert.deepEqual(state.entryProps,[{player:'D'}]);
})().catch(error => {console.error(error); process.exit(1);});
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
