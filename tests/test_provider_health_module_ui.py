import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_provider_health_module_renders_compact_and_runtime_status():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/provider-health.js');
const elements = new Map();
const $ = (id) => {
  if (!elements.has(id)) elements.set(id, {innerHTML:'',textContent:'',value:'',classList:{toggle(){return true}},addEventListener(){},setAttribute(){}});
  return elements.get(id);
};
const calls = [];
const api = async (path) => {
  calls.push(path);
  if (path === '/api/runtime/status') return {items:[{label:'Model release',value:'Ready',status:'ready'},{label:'Settlement worker',value:'Running',status:'ready'}]};
  return {providers:[{name:'<PrizePicks>',status:'stale',configured:true,message:'Refresh needed'}],summary:{connected:0,total:1},operations:{}};
};
const state = {};
const module = global.EdgeIQProviderHealth.create({$,api,state,document:{querySelector:()=>({id:'dashboard'})},
  escapeHtml:x=>String(x ?? '').replaceAll('<','&lt;').replaceAll('>','&gt;'),friendlyStatus:x=>x,formatDateTime:x=>x,humanizeText:x=>x,sortProviderHealth:x=>x});
(async () => {
  await module.loadProviderStatus();
  assert.deepEqual(calls,['/api/data-health?compact=true']);
  assert.equal(state.providerHealth.providers.length,1);
  assert.match($('today-provider-status').textContent,/1 provider needs a refresh/);
  assert.match($('global-health-strip').innerHTML,/PrizePicks/);
  await module.loadRuntimeStatus();
  assert.match($('runtime-status-list').innerHTML,/Settlement worker/);
  assert.match($('global-model-status').textContent,/Ready/);
  await module.loadDataHealth();
  assert.equal(calls.at(-1),'/api/data-health');
  assert.match($('data-health-list').innerHTML,/Evidence collection/);
  assert.match($('data-health-list').innerHTML,/App response times/);
  assert.match($('data-health-list').innerHTML,/&lt;PrizePicks&gt;/);
  assert.doesNotMatch($('data-health-list').innerHTML,/<PrizePicks>/);
})().catch(error => { console.error(error); process.exitCode=1; });
"""
    subprocess.run(["node", "-e", script], check=True)


def test_provider_health_module_loads_before_app():
    html = Path("web/static/index.html").read_text(encoding="utf-8")
    app = Path("web/static/app.js").read_text(encoding="utf-8")
    assert html.index('src="/static/js/provider-health.js') < html.index('src="/static/app.js')
    assert "window.EdgeIQProviderHealth.create" in app
    assert "async function loadProviderStatus()" not in app
    assert "async function loadDataHealth()" not in app
