import shutil
import subprocess
from pathlib import Path

import pytest


def test_caller_cancellation_does_not_cancel_shared_request():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
global.document = {getElementById() {}};
global.window = {location:{protocol:'http:'}, setTimeout, clearTimeout};
const requests = [];
global.fetch = (url, options) => new Promise((resolve, reject) => {
  const abort = () => reject(Object.assign(new Error('aborted'), {name:'AbortError'}));
  if (options.signal.aborted) return abort();
  options.signal.addEventListener('abort', abort);
  requests.push({resolve, signal:options.signal});
});
require('./web/static/js/api.js');
(async () => {
  const shared = window.EdgeIQApi.api('/same');
  const controller = new AbortController();
  const cancellable = window.EdgeIQApi.api('/same', {signal:controller.signal});
  controller.abort();
  await assert.rejects(cancellable);
  assert.equal(requests[0].signal.aborted, false);
  requests[0].resolve({ok:true, json:() => ({ok:true})});
  assert.deepEqual(await shared, {ok:true});
  await assert.rejects(window.EdgeIQApi.api('/already-aborted', {signal:controller.signal}));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
