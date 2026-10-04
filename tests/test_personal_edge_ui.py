import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_personal_edge_marks_small_samples_and_escapes_provider_names():
    script = r"""
const assert = require('node:assert/strict');
global.document = { addEventListener() {} };
global.window = global;
require('./web/static/js/personal-edge.js');
const render = global.EdgeIQPersonalEdge.render;
const data = {mode: 'real', summary: {settled_entries: 2, verified_leg_decisions: 2, leg_hit_rate: 50, excluded_legs: 1},
  segments: {provider: [{name: '<script>', wins: 1, losses: 1, decisions: 2, hit_rate: 50, small_sample: true}]},
  card_size: [], grade: [], limitations: [], sample_threshold: 30, truncated: true};
const html = render(data, 'provider');
assert.match(html, /Small sample/);
assert.match(html, /Rankings are withheld/);
assert.match(html, /&lt;script&gt;/);
assert.doesNotMatch(html, /<script>/);
"""
    subprocess.run(["node", "-e", script], check=True)
