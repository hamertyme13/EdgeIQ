import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_locked_model_summary_explains_market_prior_exclusions():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/player-workspace.js');
const summary = global.EdgeIQPlayerWorkspace.lockedModelSummary;
assert.match(summary({eligible_independent:0,excluded_by_origin:{prospective_board:{market_prior_only:66}}}), /66 settled board forecasts used a market prior/);
assert.match(summary({eligible_independent:0,excluded_by_origin:{prospective_board:{market_prior_only:66}}}), /five verified regular-season games/);
assert.doesNotMatch(summary({eligible_independent:0}), /market prior/);
assert.match(summary({eligible_independent:13,evidence_origins:{placed_entry:13,prospective_board:0},evidence_maturity:'exploratory',excluded_by_origin:{prospective_board:{market_prior_only:1}}}), /1 settled board forecast used a market prior and is excluded/);
assert.match(summary({eligible_independent:0,excluded:{history_imported_after_lock:1,invalid_history_import_time:1}}), /2 forecasts excluded because stored history import timing/);
"""
    subprocess.run(["node", "-e", script], check=True)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_scoring_selector_exposes_and_switches_home_away_opponent_splits():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
const created = [];
global.document = {createElement(tag) {
  const element = {tagName:tag.toUpperCase(),innerHTML:'',handlers:{},
    addEventListener(name, handler){this.handlers[name]=handler},
    querySelector(selector){
      if (selector === '[data-points-window]' || selector === '.nba-points-window-results') {
        this.nodes ||= {};
        return this.nodes[selector] ||= {innerHTML:'',addEventListener(name,handler){this.handler=handler}};
      }
      return null;
    },
    querySelectorAll(){return []},append(){},prepend(){},after(){},setAttribute(){}};
  created.push(element);
  return element;
}};
require('./web/static/js/player-workspace.js');
const root = {prepend(){},append(){},querySelectorAll(){return []}};
const thresholds = {
  last_5:{games:1,unverified_games:0,thresholds:[]},
  home:{games:1,unverified_games:0,thresholds:[]},
  away:{games:1,unverified_games:1,thresholds:[]},
  opponent:{games:0,unverified_games:0,thresholds:[]}
};
global.EdgeIQPlayerWorkspace.mount(root,{player:'Example',sport:'NBA',stat:'Points',line:19.5,
  team_context:{team:'PHI',source:'latest_verified_final',as_of:'2026-10-25'},
  nba_points_intelligence:{thresholds,matchup:{opponent:'NYK'},season_provenance:{}}},
  {escapeHtml:x=>String(x ?? ''),pct:x=>String(x),formatDateTime:x=>x,api:async()=>({})});
const overview = created.find(node=>node.className==='player-workspace-overview');
assert.match(overview.innerHTML,/Last recorded team/);
assert.match(overview.innerHTML,/PHI · verified final 2026-10-25/);
assert.match(overview.innerHTML,/No current matching offer/);
const points = created.find(node=>node.className==='consumer-research-section nba-points-intelligence');
assert.match(points.innerHTML,/data-points-window/);
assert.match(points.innerHTML,/Shot-volume baseline \(research only\)/);
assert.match(points.innerHTML,/<option value="home">Home<\/option>/);
assert.match(points.innerHTML,/<option value="away">Away<\/option>/);
assert.match(points.innerHTML,/<option value="opponent">Vs NYK<\/option>/);
const selector = points.querySelector('[data-points-window]');
const output = points.querySelector('.nba-points-window-results');
selector.handler({currentTarget:{value:'away'}});
assert.match(output.innerHTML,/1 with season type unverified/);
selector.handler({currentTarget:{value:'opponent'}});
assert.match(output.innerHTML,/No verified final-score games in this view yet/);
"""
    subprocess.run(["node", "-e", script], check=True)
