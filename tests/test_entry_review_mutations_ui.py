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


def test_analysis_preserves_offer_rules_and_snapshot_identity():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
global.state = {entryProps:[{player:'A', allowed_directions:['Over'], recommendation_snapshot_id:'snapshot-1', end_to_end_confirmed:true, settlement_provider:'ESPN'}]};
global.entryPropFromFeed = value => value;
global.uniqueUploadedProps = value => value;
global.syncEntryPlatformFromProps = global.renderEntryProps = () => {};
global.invalidateEntryReview = () => {throw Error('review should remain current')};
eval(source.slice(source.indexOf('function renderEntryPropsFromAnalyzed('), source.indexOf('function uniqueUploadedProps(')));
renderEntryPropsFromAnalyzed([{player:'A', confidence:91, projection:12.5}], false, true);
assert.deepEqual(state.entryProps[0].allowed_directions,['Over']);
assert.equal(state.entryProps[0].recommendation_snapshot_id,'snapshot-1');
assert.equal(state.entryProps[0].end_to_end_confirmed,true);
assert.equal(state.entryProps[0].confidence,91);
state.entryProps=[{player:'A'},{player:'A'}];
renderEntryPropsFromAnalyzed([{player:'A',line:12.5},{player:'A',line:12.5}], false, true);
assert.equal(state.entryProps.length,2);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)


def test_entry_market_duplicate_check_normalizes_player_and_stat():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
global.uploadedStatKey = value => String(value).toLowerCase().replace(/[^a-z0-9]/g,'');
eval(source.slice(source.indexOf('function sameEntryMarket('), source.indexOf('function syncEntryPlatformFromProps(')));
const existing = {player:'Azurá Stevens', sport:'WNBA', stat:'Points', line:12.5, game_time:''};
assert.equal(sameEntryMarket(existing,{player:'Azura Stevens',sport:'WNBA',stat:'Points',line:12.5,game_time:''}),true);
assert.equal(sameEntryMarket(existing,{player:'Azura Stevens',sport:'WNBA',stat:'Points',line:13.5,game_time:''}),false);
assert.equal(sameEntryMarket(existing,{player:'Azura Stevens',sport:'WNBA',stat:'Points',line:12.5,game_time:'2026-09-27T20:00:00Z'}),true);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)


def test_analysis_rejects_duplicate_markets_before_request():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
global.entrySourcePlatforms = () => ['PrizePicks'];
global.providerMaximumLegs = () => 6;
global.sameEntryMarket = (left,right) => left.player === right.player && left.stat === right.stat && left.line === right.line;
eval(source.slice(source.indexOf('function entryAnalysisValidationMessage('), source.indexOf('function parsePayoutSchedule(')));
const prop = {player:'A',sport:'WNBA',stat:'Points',line:12.5,direction:'Over'};
const message = entryAnalysisValidationMessage({platform:'PrizePicks',props:[prop,{...prop,direction:'Under'}]});
assert.match(message,/repeats a player, stat, and line/);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)


def test_editing_player_discards_old_provider_and_forecast_identity():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const original = {player:'Old', stat:'Points', line:12.5, projection:14, direction:'Over',
  platform:'PrizePicks', provider_player_id:'old-player', provider_event_id:'old-event',
  provider_offer_id:'old-offer', player_identity_id:8, game:'OLD @ OPP', game_time:'2026-09-27T20:00:00Z',
  team:'OLD', confidence:92, forecast_snapshot:{model:'old'}, recommendation_snapshot_id:'old-snapshot',
  end_to_end_confirmed:true, projection_source:'provider', auto_projected:false};
global.state = {entryProps:[original], lastAnalysis:null, recommendationOrigin:true};
const elements = {};
global.$ = id => elements[id] ||= {innerHTML:'', textContent:'', value:'PrizePicks'};
global.escapeHtml = value => String(value);
global.directionBadge = value => value;
global.pct = value => String(value);
global.entryDirectionAllowed = () => true;
global.entrySourcePlatforms = () => ['PrizePicks'];
global.syncMobileSlip = () => {};
global.invalidateEntryReview = () => {};
const fields = {player:'New', stat:'Points', line:'12.5', projection:'14', direction:'Over'};
const editor = {querySelector: selector => ({value:fields[selector.match(/data-edit-field="([^"]+)/)[1]]})};
let saveHandler;
global.document = {
  querySelector: () => editor,
  querySelectorAll: selector => selector === '[data-save-prop]'
    ? [{dataset:{saveProp:'0'}, addEventListener:(_event, handler) => {saveHandler=handler}}]
    : [],
};
eval(source.slice(source.indexOf('function renderEntryProps()'), source.indexOf('function propFromForm()')));
renderEntryProps();
saveHandler();
const updated = state.entryProps[0];
for (const key of ['provider_player_id','provider_event_id','provider_offer_id','game','game_time','team','recommendation_snapshot_id']) assert.equal(updated[key],'');
assert.equal(updated.player_identity_id,null);
assert.equal(updated.projection,null);
assert.equal(updated.confidence,null);
assert.deepEqual(updated.forecast_snapshot,{});
assert.equal(updated.end_to_end_confirmed,false);
assert.equal(state.recommendationOrigin,false);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)


def test_clear_entry_renders_empty_state_without_analysis_data():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const element = {className:'',innerHTML:''};
global.$ = () => element;
eval(source.slice(source.indexOf('function renderEmptyEntryAnalysis('), source.indexOf('function setupProviderGeneratorTabs(')));
renderEmptyEntryAnalysis();
assert.match(element.innerHTML,/Ready when your card is/);
assert.ok(!element.innerHTML.includes('Complete-card outlook'));
assert.match(source.slice(source.indexOf('function renderAnalysis('), source.indexOf('async function analyzeEntry(')),/EdgeIQEntrySummary\?\.render\(data/);
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
