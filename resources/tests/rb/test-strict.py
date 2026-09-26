#!/usr/bin/env python3
"""Whether the page scripts are actually running in strict mode.

Having 'use strict' in the source is not the same as it taking effect: the
directive only counts when it is the first statement of the script, so a stray
statement above it silently turns the whole thing back into sloppy mode with no
error anywhere. This asserts the runtime behaviour instead of the text.

The discriminator is what V8 puts on the function object. A sloppy function
carries own 'arguments' and 'caller' properties; a strict one does not, and
reading .caller on it throws TypeError. So for one representative function per
script:

    own properties must not include caller or arguments
    reading .caller must throw

rb-actions.js and rb-resize.js declare no top-level functions - they are
top-level wiring only - so there is nothing to probe in them and they are
listed here rather than checked.

Why strict matters here: it is what stops a missing const from quietly
creating a global, which is the failure mode a 300-declaration page of classic
scripts is most exposed to. It is also the one part of the ES-module semantics
that can be adopted without breaking the test suite, which drives this page
entirely through bare global names.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-strict.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

from driver import open_page

# One representative top-level function per script, in load order.
PROBES = {
    'rb-state':          'initDOMReferences',
    'rb-utils':          'waitForH5Wasm',
    'rb-hdf5':           'checkDatasetExistsInFile',
    'rb-lazy':           'wantsLazyFile',
    'rb-file':           'getEnabledFiles',
    'rb-tabs':           'hideFileTabTooltip',
    'rb-tree':           'toggleGroupExpansion',
    'rb-chart-axes':     'getNamedColor',
    'rb-chart-presets':  'loadPresets',
    'rb-chart-export':   'downloadChartData',
    'rb-chart-toggles':  'toggleShowTotal',
    'rb-chart':          'backgroundRectShapes',
    'rb-legend':         'toggleDynamicLegend',
    'rb-info':           'showNodeAttributes',
    'rb-search':         'wildcardToRegex',
    'rb-dragdrop':       'preventDefaults',
    'rb-export':         'copyChartToClipboard',
    'rb-init':           'showSearchTicker',
    'rb-handoff':        'beginHandoffWait',
}
NO_TOP_LEVEL_FUNCTIONS = ['rb-actions', 'rb-resize']

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


PROBE = """(() => {
  const names = %s;
  const out = {};
  for (const n of names) {
    const f = window[n];
    if (typeof f !== 'function') { out[n] = 'missing'; continue; }
    const own = Object.getOwnPropertyNames(f);
    let threw = false;
    try { void f.caller; } catch (e) { threw = e instanceof TypeError; }
    out[n] = (!own.includes('caller') && !own.includes('arguments') && threw)
      ? 'strict' : 'sloppy';
  }
  return JSON.stringify(out);
})()"""

# A control: a function defined by a sloppy evaluation must read as sloppy, or
# the discriminator is measuring nothing.
CONTROL = """(() => {
  const f = new Function('return 1');
  const own = Object.getOwnPropertyNames(f);
  let threw = false;
  try { void f.caller; } catch (e) { threw = true; }
  return (!own.includes('caller') && !own.includes('arguments') && threw)
    ? 'strict' : 'sloppy';
})()"""


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, url='http://127.0.0.1:8765/rb.html', settle=8)
        try:
            check('the discriminator can tell a sloppy function apart',
                  await page.ev(CONTROL), 'sloppy')
            got = json.loads(await page.ev(PROBE % json.dumps(list(PROBES.values()))))
            for script, fn in PROBES.items():
                check(f'{script}.js is strict (via {fn})', got.get(fn), 'strict')
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed'
          f'  ({len(NO_TOP_LEVEL_FUNCTIONS)} scripts have no top-level function to probe: '
          f'{", ".join(NO_TOP_LEVEL_FUNCTIONS)})')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
