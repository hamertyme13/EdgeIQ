import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the browser-module test")
def test_timeline_charts_do_not_connect_different_offer_types():
    script = r"""
const assert = require('node:assert/strict');
global.escapeHtml = value => String(value ?? '').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
global.formatDateTime = value => String(value);
require('node:vm').runInThisContext(require('node:fs').readFileSync('./web/static/js/market-model-timeline.js', 'utf8'));
const event = (key, offer, line, projection) => ({market_series_key:key, game:'A vs B', offer_type:offer,
  direction:'Over', line, projection, created_at:'2026-10-07T12:00:00Z', platform:'PrizePicks',
  model_probability:60, calibration_context:{status:'UNAVAILABLE'}});
const html = renderMarketModelTimeline({events:[event('standard','standard',20,22),
  event('standard','standard',21,22), event('discount','discounted',17,22)]});
assert.equal((html.match(/<polyline /g) || []).length, 4);
assert.match(html, /standard offer/);
assert.match(html, /discounted offer/);
assert.match(html, /across 2 saved observations/);
assert.match(html, /across 1 saved observation"/);
"""
    subprocess.run(["node", "-e", script], check=True)
