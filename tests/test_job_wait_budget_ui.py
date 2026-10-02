import shutil
import subprocess
from pathlib import Path

import pytest


def test_browser_job_waiters_report_unfinished_work() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');

let clock = 0;
const fakeDate = {now: () => clock};
const window = {setTimeout: (callback, delay) => {clock += delay; callback();}};
const running = {job_id: 'test-job', label: 'Provider refresh', status: 'running', progress: 50};
const api = async () => running;

const app = fs.readFileSync('web/static/app.js', 'utf8');
const appFunction = app.slice(app.indexOf('async function waitForBackgroundJob('), app.indexOf('\nasync function runDailyRefresh('));
const waitForBackgroundJob = new Function('api', 'window', 'Date', `${appFunction}; return waitForBackgroundJob;`)(api, window, fakeDate);

const games = fs.readFileSync('web/static/js/games.js', 'utf8');
const gamesFunction = games.slice(games.indexOf('  async function waitForJob('), games.indexOf('\n  function predictionCard('));
const waitForJob = new Function('request', 'window', 'Date', 'byId', `${gamesFunction}; return waitForJob;`)(api, window, fakeDate, () => null);

(async () => {
  await assert.rejects(waitForBackgroundJob(running), /still running in the background/);
  assert(clock < 180000);
  clock = 0;
  await assert.rejects(waitForJob(running), /still refreshing in the background/);
  assert(clock < 180000);
  assert.equal((await waitForBackgroundJob({status: 'complete', result: {ok: true}})).result.ok, true);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    subprocess.run([node, "-e", script], cwd=Path(__file__).resolve().parents[1], check=True)
