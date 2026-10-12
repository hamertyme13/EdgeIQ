import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-state test")
def test_entry_directory_ignores_out_of_order_queries():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
global.window = global;
require('./web/static/js/state.js');
global.entryState = global.EdgeIQState.entry;
const elements = new Map();
const $ = (id) => {
  if (!elements.has(id)) elements.set(id, {value:'',textContent:'',innerHTML:'',disabled:false,placeholder:''});
  return elements.get(id);
};
global.$ = $;
global.escapeHtml = (value) => String(value).replaceAll('<','&lt;').replaceAll('>','&gt;');
const pending = [];
global.api = () => new Promise((resolve) => pending.push(resolve));
const source = fs.readFileSync('./web/static/app.js','utf8');
eval(source.slice(source.indexOf('function entryPlayerProviderLabel('), source.indexOf('function entryPayload()')));
$('prop-sport').value = 'NCAAF';
$('prop-player').value = 'Arc';
(async () => {
  const oldRequest = loadEntryPlayerDirectory('Ar');
  entryState.invalidatePlayerLookup();
  const latestRequest = loadEntryPlayerDirectory('Arc');
  pending[1]({players:[{id:2,name:'Arch Manning',team:'TEX'}],count:1});
  await latestRequest;
  pending[0]({players:[{id:1,name:'Aaron Older',team:'OLD'}],count:1});
  await oldRequest;
  assert.equal(entryState.playerDirectory[0].name,'Arch Manning');
  assert.match($('entry-player-options').innerHTML,/Arch Manning/);
  assert.doesNotMatch($('entry-player-options').innerHTML,/Aaron Older/);
  $('prop-sport').value = 'WNBA';
  const staleSport = loadEntryPlayerDirectory('Pa');
  $('prop-sport').value = 'NBA';
  entryState.invalidatePlayerLookup();
  pending[2]({players:[{id:3,name:'Paige Example'}],count:1});
  await staleSport;
  assert.equal(entryState.playerDirectory[0].name,'Arch Manning');
})().catch(error => { console.error(error); process.exitCode=1; });
"""
    subprocess.run(["node", "-e", script], check=True)


def test_entry_directory_is_owned_by_entry_state():
    state = Path("web/static/js/state.js").read_text(encoding="utf-8")
    app = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "const entryState = state.entry;" in app
    assert "entryState.acceptPlayerLookup(requestId, data.players)" in app
    assert '$("entry-player-options").innerHTML = "";' in app
    assert "entryPlayerDirectory:" not in state
