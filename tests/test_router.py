"""Exercise SPA history guards with a deterministic History API model, without a browser service."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ESBUILD = ROOT / 'frontend/node_modules/.bin/esbuild'
pytestmark = pytest.mark.skipif(not ESBUILD.exists(), reason='install frontend dependencies to test the router')


def test_navigation_guard_preserves_history_on_cancel(tmp_path: Path):
    compiled = tmp_path / 'router.cjs'
    subprocess.run(
        [str(ESBUILD), str(ROOT / 'frontend/app/src/router.ts'), '--format=cjs', f'--outfile={compiled}'],
        check=True,
        capture_output=True,
        text=True,
    )
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let entries = [{ path: '/', state: null }], index = 0, pop;
const location = { pathname: '/', search: '', hash: '' };
const history = {
  get state() { return entries[index].state },
  replaceState(state, title, path) { entries[index] = { path, state }; location.pathname = path },
  pushState(state, title, path) { entries = entries.slice(0, index + 1); entries.push({ path, state }); index++; location.pathname = path },
  go(delta) { assert.notEqual(delta, 0, 'cancel must not reload the page'); index += delta; location.pathname = entries[index].path; pop() },
};
const moduleObject = { exports: {} };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  module: moduleObject, exports: moduleObject.exports,
  require(name) { assert.equal(name, 'react'); return {} },
  window: { history, location, addEventListener(name, callback) { if (name === 'popstate') pop = callback } },
});
const router = moduleObject.exports;
router.navigate('/edit/first');
router.navigate('/edit/second');
const targets = [];
router.setNavigationGuard(to => { targets.push(to); return false });
router.navigate('/');
assert.equal(location.pathname, '/edit/second');
assert.equal(index, 2);
history.go(-1);
assert.equal(location.pathname, '/edit/second');
assert.equal(index, 2);
assert.deepEqual(targets, ['/', '/edit/first']);
router.setNavigationGuard(null);
history.go(-1);
assert.equal(location.pathname, '/edit/first');
history.go(1);
assert.equal(location.pathname, '/edit/second');
router.navigate('/');
assert.equal(location.pathname, '/');
assert.equal(index, 3);
"""
    subprocess.run(['node', '-e', script, str(compiled)], check=True, capture_output=True, text=True)
