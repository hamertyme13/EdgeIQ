import shutil
import subprocess
from pathlib import Path

import pytest


def test_today_renders_monthly_metrics_and_polls_briefing_once():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const source = require('fs').readFileSync('web/static/app.js', 'utf8');
const elements = {};
global.$ = id => elements[id] ||= {innerHTML:'',textContent:'',value:id==='props-platform'?'PrizePicks':'WNBA'};
global.pct = value => `${Number(value).toFixed(1)}%`;
global.money = value => `$${Number(value || 0).toFixed(2)}`;
global.escapeHtml = value => String(value);
eval(source.slice(source.indexOf('function renderStats('),source.indexOf('async function loadDashboard(')));
renderStats({record:'7-2',wins:7,losses:2,profit:120,bankroll:220,pending_entry_exposure:10,
  bankroll_transactions:{deposits:100,withdrawals:0},monthly_performance:{label:'October 2026',record:'0-1',
  wins:0,losses:1,profit:-10,roi:-100,wagered:10,current_streak:-1,max_drawdown:10,
  paper:{accuracy:100,decisions:1},recommendation_accuracy:{wins:0,losses:1,accuracy:0,tracked:1,pending:0,pushes:0}}});
assert.match($('dashboard-stats').innerHTML,/0-1/);
assert.doesNotMatch($('dashboard-stats').innerHTML,/7-2/);
assert.match($('today-performance-period').textContent,/October 2026/);
assert.match($('recommendation-accuracy').innerHTML,/0-1/);

const queued=[];
global.window={clearTimeout:()=>{},setTimeout:fn=>(queued.push(fn),queued.length)};
global.document={querySelector:()=>({dataset:{dailyScanStatus:'scanning_props'}})};
global.state={dailyScanPoll:null,dailyScanPollStartedAt:Date.now()};
global.api=async()=>({current:{status:'scanning_props'},runs:[]});
global.renderDailyScanStatus=()=>{};
eval(source.slice(source.indexOf('async function loadDailyScanStatus('),source.indexOf('function renderDailyScanStatus(')));
pollDailyScanStatus(true);
assert.equal(queued.length,1);
Promise.resolve(queued.shift()()).then(async()=>{
  assert.equal(queued.length,1);
  pollDailyScanStatus(true);
  assert.equal(queued.length,2);
  await queued.shift()();
  assert.equal(queued.length,1);
  await queued.shift()();
  assert.equal(queued.length,1);
}).catch(error=>{throw error});
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
