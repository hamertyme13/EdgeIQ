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
const paired = global.EdgeIQPlayerWorkspace.verifiedLineComparisonSummary;
assert.match(paired({status:'exploratory_paired_comparison',samples:118,mae_advantage_points:-0.571,date_block_interval_95:[-2.6,0.1]}), /trailed the exact line by 0.6 points of MAE.*difference is uncertain/);
assert.equal(paired({status:'insufficient_paired_evidence',samples:2}), '');
const namedPrices = global.EdgeIQPlayerWorkspace.namedBookPriceSummary;
assert.match(namedPrices({named_book_prices:{over:{american_odds:105,bookmaker:'Book A',break_even_probability:48.78},under:{american_odds:-105,bookmaker:'Book B',break_even_probability:51.22}}}), /Over \+105 at Book A \(break-even 48.8%\); Under -105 at Book B \(break-even 51.2%\)/);
assert.match(namedPrices({named_book_prices:{over:{american_odds:105,bookmaker:'Book A',break_even_probability:48.78},under:{american_odds:-105,bookmaker:'Book B',break_even_probability:51.22}}}), /not PrizePicks or Underdog payouts/);
assert.equal(namedPrices({}), '');
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
  last_5:{games:1,unverified_games:0,thresholds:[{points:20,hits:1,decisions:1,games:1,
    hit_rate:100,average:24,median:24,standard_deviation:0,pushes:0,interval_95:[20.7,100]}]},
  home:{games:1,unverified_games:0,thresholds:[]},
  away:{games:1,unverified_games:1,thresholds:[]},
  opponent:{games:0,unverified_games:0,thresholds:[]}
};
global.EdgeIQPlayerWorkspace.mount(root,{player:'Example',sport:'NBA',stat:'Points',line:19.5,
  team_context:{team:'PHI',source:'latest_verified_final',as_of:'2026-10-25'},
  nba_points_intelligence:{sample_size:1,thresholds,matchup:{opponent:'NYK',opponent_injuries:{status:'reported',retrieved_at:'2026-11-09T16:00:00Z',reports:[{player:'Opponent Player',status:'Questionable'}]},team_points_allowed:{sample_size:2,last_5:102.5,last_10:102.5,last_20:102.5,
    home_sample_size:1,home_points_allowed_last_10:90,away_sample_size:1,away_points_allowed_last_10:115,days_rest:2,
    pace_comparison:{status:'descriptive_comparison',opponent_pace_last_5:96.9,league_pace_average:100.7,
      pace_rank_fastest_first:27,ranked_teams:30},
    status:'Small opponent team sample; descriptive only.'}},season_provenance:{}}},
  {escapeHtml:x=>String(x ?? ''),pct:x=>String(x),formatDateTime:x=>x,api:async()=>({})});
const overview = created.find(node=>node.className==='player-workspace-overview');
assert.match(overview.innerHTML,/Last recorded team/);
assert.match(overview.innerHTML,/PHI · verified final 2026-10-25/);
assert.match(overview.innerHTML,/No current matching offer/);
assert.match(overview.innerHTML,/No exact-line recommendation/);
assert.doesNotMatch(overview.innerHTML,/Research Over chance/);
assert.match(overview.innerHTML,/Verified historical finals; no current exact-line offer/);
const points = created.find(node=>node.className==='consumer-research-section nba-points-intelligence');
assert.match(points.innerHTML,/data-points-window/);
assert.match(points.innerHTML,/1\/1 decided/);
assert.match(points.innerHTML,/Average 24.0 · Median 24.0 · SD 0.0/);
assert.match(points.innerHTML,/95% historical hit-rate interval 20.7–100%/);
assert.match(points.innerHTML,/Opponent location splits/);
assert.match(points.innerHTML,/Last 5: 102.5 · Last 10: 102.5 · Last 20: 102.5/);
assert.match(points.innerHTML,/90.0 allowed in 1 game/);
assert.match(points.innerHTML,/2 full rest days before this game/);
assert.match(points.innerHTML,/League pace comparison:<\/strong> Opponent 96.9 vs 100.7/);
assert.match(points.innerHTML,/rank 27 of 30 \(1 fastest\)/);
assert.match(points.innerHTML,/1 opponent injury report · ESPN feed/);
assert.match(points.innerHTML,/Opponent Player: Questionable/);
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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_verified_research_forecast_is_visible_without_becoming_a_recommendation():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
const created = [];
global.document = {createElement() {
  const element = {innerHTML:'',querySelector(selector){
    if (selector === '[data-points-window]') return {addEventListener(){}};
    if (selector === '.nba-points-window-results') return {innerHTML:''};
    return null;
  },querySelectorAll(){return []},addEventListener(){},append(){},prepend(){},after(){},setAttribute(){}};
  created.push(element);
  return element;
}};
require('./web/static/js/player-workspace.js');
const root = {prepend(){},append(){},querySelectorAll(){return []}};
const base = {player:'Example',sport:'NBA',stat:'Points',line:19.5,platform:'PrizePicks',
  recommendation:{line:20.5,confidence:0.7,projection:22},edgeiq_score_freshness:{status:'fresh'},
  nba_points_intelligence:{sample_size:10,thresholds:{last_5:{games:0}},matchup:{team_points_allowed:{}},
    projection:{source:'verified_history_distribution',expected_points:21.3,over_probability:0.61,under_probability:0.39,
      observed_scoring_spread:{sample_size:10,p10:12,p25:17,median:21,p75:25,p90:31,label:'Observed recent scoring spread, not a calibrated next-game prediction interval.'},
      uncertainty_level:'High',uncertainty_drivers:['Minutes vary']}}};
const deps = {escapeHtml:x=>String(x ?? ''),pct:x=>`${(x*100).toFixed(0)}%`,formatDateTime:x=>x,api:async()=>({})};
global.EdgeIQPlayerWorkspace.mount(root,base,deps);
let overview = created[0].innerHTML;
assert.match(overview,/Research projection<\/dt><dd>21.3 points/);
assert.match(overview,/Research Over chance<\/dt><dd>61%/);
assert.match(overview,/Research Under chance<\/dt><dd>39%/);
assert.match(overview,/Hit probability<\/dt><dd>No exact-line recommendation/);
assert.match(overview,/Verified historical finals; no current exact-line offer/);
assert.doesNotMatch(overview,/Current exact-line offer/);
assert.match(overview,/Research only: paid-use evidence has not been confirmed/);
const points = created.find(node=>node.className==='consumer-research-section nba-points-intelligence');
assert.match(points.innerHTML,/middle half 17.0–25.0 points/);
assert.match(points.innerHTML,/not a calibrated next-game prediction interval/);
assert.match(points.innerHTML,/Model uncertainty: High/);
created.length = 0;
global.EdgeIQPlayerWorkspace.mount(root,{...base,nba_points_intelligence:{...base.nba_points_intelligence,
  projection:{source:'market_prior',expected_points:null,over_probability:null,under_probability:null}}},deps);
overview = created[0].innerHTML;
assert.doesNotMatch(overview,/Research Over chance/);
created.length = 0;
global.EdgeIQPlayerWorkspace.mount(root,{...base,recommendation:{...base.recommendation,line:19.5}},deps);
overview = created[0].innerHTML;
assert.match(overview,/Evidence<\/dt><dd>Current exact-line offer/);
assert.match(overview,/Hit probability<\/dt><dd>70%/);
"""
    subprocess.run(["node", "-e", script], check=True)
