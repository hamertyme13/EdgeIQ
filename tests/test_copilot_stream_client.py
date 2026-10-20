import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for stream parser coverage")
def test_browser_stream_parser_handles_split_events_and_old_server_fallback():
    script = r"""
const assert = require('node:assert/strict');
global.window = global;
global.location = {protocol: 'http:'};
global.localStorage = {getItem: () => ''};
global.document = {getElementById: () => null};
require('./web/static/js/api.js');
const encoder = new TextEncoder();
const parts = [
  'event: status\r', '\ndata: {"stage":"retrieval","label":"Checking evidence"}\r\n\r',
  '\nevent: answer\ndata: {"grounded":true,"response":{"answer":"Verified"}}\n\n',
  'event: done\ndata: {}\n\n',
];
let calls = 0;
global.fetch = async () => {
  calls++;
  return {ok: true, status: 200, body: {getReader() {
    let index = 0;
    return {read: async () => index < parts.length
      ? {done: false, value: encoder.encode(parts[index++])} : {done: true}};
  }}};
};
(async () => {
  const statuses = [];
  const result = await global.EdgeIQApi.streamCopilot({question: 'Check'}, label => statuses.push(label));
  assert.deepEqual(statuses, ['Checking evidence']);
  assert.equal(result.response.answer, 'Verified');
  assert.equal(calls, 1);
  global.fetch = async (url) => url.endsWith('/stream')
    ? {ok: false, status: 404}
    : {ok: true, status: 200, json: async () => ({response: {answer: 'Old server'}})};
  const fallback = await global.EdgeIQApi.streamCopilot({question: 'Check'});
  assert.equal(fallback.response.answer, 'Old server');
})().catch(error => {console.error(error); process.exitCode = 1});
"""
    subprocess.run(["node", "-e", script], check=True)
