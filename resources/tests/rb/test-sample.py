#!/usr/bin/env python3
"""The Sample Data dialog, with and without sample files behind it.

The samples are not committed -- they were taken out of the repository so as
not to publish them -- and may come back later, so the dialog has to be
sensible in every state rather than only in the one where files exist:

    no manifest at all      the same thing as none published. A reader should
                            be told there are none, not shown "HTTP 404" as
                            though the page were broken.
    an empty manifest       the same, and Load disabled: a live button whose
                            only answer is "Select at least one file" is a
                            dead end.
    files listed            listed, Load enabled.
    a name with no file     reported by name when Load is pressed.
    a broken manifest       reported: that one IS a fault.

The manifest is stubbed by replacing window.fetch rather than by writing files
into the served tree, so the test says nothing about what happens to be in
resources/data when it runs.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-sample.py

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


# Answer the manifest request with whatever this test wants, and leave every
# other request alone. `body` of None stands for a 404.
STUB = """(() => {
  if (!window._realFetch) window._realFetch = window.fetch;
  window.fetch = (input, init) => {
    const url = String(input && input.url ? input.url : input);
    if (url.includes('files.json')) {
      const body = %s;
      return Promise.resolve(body === null
        ? new Response('not found', { status: 404 })
        : new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    if (url.includes('/resources/data/') && %s) {
      return Promise.resolve(new Response('not found', { status: 404 }));
    }
    return window._realFetch(input, init);
  };
  return true;
})()"""

STATE = """(() => {
  const list = document.getElementById('sampleDataList');
  const err = document.getElementById('sampleDataError');
  const btn = document.getElementById('sampleDataLoadBtn');
  return JSON.stringify({
    list: list.textContent.trim(),
    items: list.querySelectorAll('input[type="checkbox"]').length,
    error: err.style.display === 'none' ? null : err.textContent,
    load: btn.disabled ? 'disabled' : 'enabled',
  });
})()"""


async def shows(page, manifest, missing_files='false'):
    """Stub the manifest, open the dialog, and report what it shows."""
    await page.ev(STUB % (manifest, missing_files))
    await page.ev("(async () => { await openSampleDataDialog(); return 1; })()")
    await asyncio.sleep(0.3)
    return json.loads(await page.ev(STATE))


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            none_published = 'No sample files available.'

            s = await shows(page, 'null')
            check('no manifest at all says there are none', s['list'], none_published)
            check('  and does not report it as an error', s['error'], None)
            check('  with nothing to press', s['load'], 'disabled')

            s = await shows(page, "'[]'")
            check('an empty manifest says the same', s['list'], none_published)
            check('  and leaves Load disabled', s['load'], 'disabled')

            s = await shows(page, "'[\"a.h5\", \"b.h5\"]'")
            check('files listed are offered', s['items'], 2)
            check('  and Load is live', s['load'], 'enabled')
            check('  with no error', s['error'], None)

            # A name in the manifest whose file is not there yet: the reader
            # should be told which one, not left with a dialog that did nothing.
            await page.ev("""(() => {
              const c = document.querySelector('#sampleDataList input[type="checkbox"]');
              c.checked = true; return 1;
            })()""")
            await page.ev("(async () => { await loadSelectedSampleData(); return 1; })()")
            await asyncio.sleep(0.5)
            s2 = json.loads(await page.ev(STATE))
            check('a listed file that is not there is reported by name',
                  bool(s2['error']) and 'a.h5' in s2['error'], True)
            check('  and the dialog stays open to try again', s2['load'], 'enabled')

            # A manifest that is not a list, or not JSON, IS a fault.
            s = await shows(page, "'{\"oops\": 1}'")
            check('a manifest that is not a list says there are none', s['list'], none_published)
            s = await shows(page, "'not json at all'")
            check('a manifest that is not JSON is reported as a failure',
                  bool(s['error']) and 'Could not load sample file list' in s['error'], True)
            check('  and Load stays disabled', s['load'], 'disabled')

            await page.ev("(() => { if (window._realFetch) window.fetch = window._realFetch; return 1; })()")
            check('no console errors throughout', page.logs[:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
