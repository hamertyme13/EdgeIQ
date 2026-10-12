import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_alert_module_preserves_settings_and_escapes_notices():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
require('./web/static/js/alerts.js');
const elements = new Map();
const $ = (id) => {
  if (!elements.has(id)) elements.set(id, {checked:false,value:'',innerHTML:'',textContent:'',hidden:false,classList:{remove(){}}});
  return elements.get(id);
};
const calls = [];
const api = async (path, options) => {
  calls.push([path, options]);
  if (path === '/api/notifications') return {notifications:[{title:'<Risk>',message:'Line moved',severity:'danger',type:'Smart Alert'}]};
  return {settings:{browser_enabled:true,smart_alerts_enabled:true,smart_alert_types:['upgrades'],smart_alert_line_move:1.5,channels:['browser']},delivery_hooks:{browser:'available'}};
};
const escapeHtml = (value) => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const alerts = global.EdgeIQAlerts.create({$,api,escapeHtml,friendlyStatus:x=>x,pct:x=>`${x}%`,sortNotifications:x=>x});
(async () => {
  await alerts.loadNotifications();
  assert.match($('notification-list').innerHTML,/&lt;Risk&gt;/);
  assert.doesNotMatch($('notification-list').innerHTML,/<Risk>/);
  assert.equal($('notification-center-count').textContent,'1');
  await alerts.loadAlertDeliverySettings();
  assert.equal($('smart-upgrades').checked,true);
  assert.equal($('smart-alert-line-move').value,1.5);
  await alerts.saveAlertDeliverySettings({preventDefault(){}});
  const saved = JSON.parse(calls.at(-1)[1].body);
  assert.deepEqual(saved.smart_alert_types,['upgrades']);
  assert.equal(saved.smart_alert_line_move,1.5);
})().catch(error => { console.error(error); process.exitCode=1; });
"""
    subprocess.run(["node", "-e", script], check=True)


def test_alert_module_loads_before_app():
    html = Path("web/static/index.html").read_text(encoding="utf-8")
    app = Path("web/static/app.js").read_text(encoding="utf-8")
    assert html.index('src="/static/js/alerts.js') < html.index('src="/static/app.js')
    assert "window.EdgeIQAlerts.create" in app
    assert "async function loadNotifications()" not in app
