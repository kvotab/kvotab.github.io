#!/usr/bin/env python3
"""Whether the debug gate actually gates.

An ordinary load of rb.html used to print around ninety console lines: a
running commentary from the tree worker at debug level, and one warning per
dataset for every optional attribute that happened to be missing. Those are now
routed through kvotTrace and kvotWarn in kvot-errors.js.

What has to be true, and is asserted below:

    off by default      kvotTrace prints nothing at all
    warnings survive    kvotWarn still prints, because a missing unit explains
                        what the reader is looking at
    but only once       the same message from inside a two-hundred dataset
                        loop is one line, not two hundred
    ?debug=1            brings back every trace and every repeat
    localStorage        does the same, and outlasts a reload

The counting is done with spies installed in the page rather than through the
CDP console feed, because the driver only forwards error and warning and the
whole question here is what happens at debug level.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-debug-gate.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

from driver import open_page

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


# Spy, exercise, report. Each message is sent three times so that
# deduplication is visible as a count and not just as presence.
EXERCISE = """(() => {
  const n = { debug: 0, warn: 0 };
  const realDebug = console.debug, realWarn = console.warn;
  console.debug = (...a) => { n.debug++; };
  console.warn  = (...a) => { n.warn++; };
  try {
    kvotTrace('trace one'); kvotTrace('trace two'); kvotTrace('trace three');
    kvotWarn('same message', 1);
    kvotWarn('same message', 2);
    kvotWarn('same message', 3);
    kvotWarn('a different message');
    ignoreFailure('someOperation', new Error('optional thing missing'));
  } finally {
    console.debug = realDebug; console.warn = realWarn;
  }
  return JSON.stringify({ ...n, flag: KVOT_DEBUG });
})()"""


async def run(url, before=None):
    """One page, on its own browser connection.

    open_page reads the createTarget reply off the browser socket as the very
    next message, so a connection that has already been used for a closeTarget
    hands it that reply instead. A connection per page keeps that honest.
    """
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=64 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, url=url, settle=7)
        try:
            if before:
                await page.ev(before)
                await page.ev("location.reload()")
                await asyncio.sleep(6)
            return json.loads(await page.ev(EXERCISE))
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))


async def main():
    if True:
        base = 'http://127.0.0.1:8765/rb.html'

        off = await run(base)
        print('\n-- an ordinary load --')
        check('the flag is off', off['flag'], False)
        check('three kvotTrace calls print nothing', off['debug'], 0)
        check('ignoreFailure prints nothing either', off['debug'], 0)
        check('four kvotWarn calls print two lines, one per message',
              off['warn'], 2)

        on = await run(base + '?debug=1')
        print('\n-- ?debug=1 --')
        check('the flag is on', on['flag'], True)
        # Three kvotTrace calls plus ignoreFailure, which routes through it.
        check('every trace prints, ignoreFailure included', on['debug'], 4)
        check('every warning prints, repeats included', on['warn'], 4)

        # localStorage has to survive the reload that follows setting it, so
        # this proves the stored form and not just the query parameter.
        stored = await run(base, before="localStorage.setItem('kvotDebug', '1')")
        print('\n-- localStorage.kvotDebug = 1, after a reload --')
        check('the flag is on', stored['flag'], True)
        check('traces print', stored['debug'], 4)
        check('warnings repeat', stored['warn'], 4)

        cleared = await run(base, before="localStorage.removeItem('kvotDebug')")
        print('\n-- and cleared again --')
        check('the flag is off', cleared['flag'], False)
        check('back to silence', cleared['debug'], 0)
        check('and one line per message', cleared['warn'], 2)

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
