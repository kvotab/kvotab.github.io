#!/usr/bin/env python3
"""The file tabs, and the tooltip that hangs off them.

A tab's tooltip is a div on the body, not a title attribute: it is shown on the
tab's mouseenter and hidden on its mouseleave. A tab that is REMOVED never gets
a mouseleave, so closing a file used to leave its tooltip on the screen.

Hiding it when the strip is rebuilt is not enough on its own, which is what
makes this worth a test rather than a one-line change. Closing a tab shuffles
the ones after it leftwards; one slides under the stationary pointer, Chrome
fires mouseenter on it, and a tooltip appears again immediately -- for the next
file along, which nobody pointed at. What a title attribute does after a click
is stay away until the pointer actually moves, and that is what is checked
here, on both of the two removal paths:

    an ENABLED file   removeFile calls updateTabs(), which rebuilds the strip
    a DISABLED file   removeFile removes the one element and returns

The pointer is driven with real CDP mouse events rather than dispatched DOM
events, because the thing being tested is what the browser does with hover
when the element under the pointer is replaced -- which a synthetic
MouseEvent would not reproduce.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-tabs.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import sys

import websockets
import urllib.request

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


# Files with no data behind them: the tabs, their tooltips and removeFile are
# all this is about, and a real HDF5 file would only add a dependency on one
# being in the repository. They do need a close(), because removeFile releases
# the handle and says so in the console when it cannot.
SETUP = """(() => {
  for (const k of Object.keys(fileStates)) { delete fileStates[k]; delete loadedFiles[k]; }
  fileOrder = [];
  for (const [name, on] of %s) {
    loadedFiles[name] = { name, get: () => null, keys: () => [], close: () => {} };
    fileStates[name] = on;
    fileOrder.push(name);
  }
  updateTabs(true);
  return document.querySelectorAll('.file-tab').length;
})()"""

# A file whose root Information -- markup the file writes, shown in its tab's
# tooltip -- tries everything the allowlist in kvot-safe.js is there to stop.
# Built with h5wasm, since the tooltip reads the root of a real file.
HOSTILE_INFO = (
    '<meta http-equiv="refresh" content="0;url=./404.html?moved-by-a-tooltip">'
    '<link rel="stylesheet" href="./resources/css/kvot.css?loaded-by-a-tooltip">'
    '<a href="java&#x09;script:window.__ran=1">a link</a>'
    '<svg><a xlink:href="javascript:window.__ran=2"><text y="20">svg</text></a></svg>'
    '<p>Base case, <b>2026</b></p>')

HOSTILE = """(async (info) => {
  await waitForH5Wasm();
  for (const k of Object.keys(fileStates)) { delete fileStates[k]; delete loadedFiles[k]; }
  fileOrder = [];
  const f = new h5wasm.File('/hostile-info.h5', 'w');
  f.create_attribute('Information', info);
  f.create_dataset({ name: 'x', data: new Float64Array([1, 2]) });
  f.close();
  const bytes = h5wasm.FS.readFile('/hostile-info.h5');
  h5wasm.FS.unlink('/hostile-info.h5');
  await ingestHdf5Buffer('hostile.h5', bytes.slice().buffer);
  updateTabs(true);
  return fileOrder.slice();
})(%s)"""

AFTER_HOVER = """(() => {
  const t = document.getElementById('fileTabTooltip');
  const info = t && t.querySelector('.file-tab-tooltip-info');
  return {
    href: location.pathname,
    shown: t ? t.style.display : 'absent',
    info: info ? info.innerHTML : null,
    sheets: [...document.querySelectorAll('link[rel=stylesheet]')].filter(l => /loaded-by-a-tooltip/.test(l.href)).length,
    foreign: t ? [...t.querySelectorAll('meta, link, svg, base, style, form')].map(e => e.localName) : [],
    ran: typeof window.__ran
  };
})()"""

TIP = ("(() => { const t = document.getElementById('fileTabTooltip');"
       " return t ? t.style.display : 'absent'; })()")

BOX = """(() => {
  const t = [...document.querySelectorAll('.file-tab')].find(x => x.dataset.file === %s);
  if (!t) return null;
  const el = %s;
  const b = el.getBoundingClientRect();
  return [b.x + b.width / 2, b.y + b.height / 2];
})()"""


async def move(page, x, y):
    await page.send('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y})
    await asyncio.sleep(0.25)


async def click(page, x, y):
    await move(page, x, y)
    for kind in ('mousePressed', 'mouseReleased'):
        await page.send('Input.dispatchMouseEvent',
                        {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
    await asyncio.sleep(0.6)


async def hover_then_close(page, name):
    """Hover a tab, then click its close button without moving away first."""
    tab = await page.ev(BOX % (json.dumps(name), 't'))
    await move(page, tab[0], tab[1])
    shown = await page.ev(TIP)
    close = await page.ev(BOX % (json.dumps(name), "t.querySelector('.file-tab-close')"))
    await click(page, close[0], close[1])
    return shown


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            # --- an enabled file: removeFile rebuilds the whole strip --------
            check('two tabs to start with',
                  await page.ev(SETUP % "[['alpha.h5', true], ['beta.h5', true]]"), 2)
            shown = await hover_then_close(page, 'alpha.h5')
            check('hovering a tab shows its tooltip', shown, 'block')
            check('closing it removes the tab', await page.ev(
                "document.querySelectorAll('.file-tab').length"), 1)
            check('and the tooltip goes with it', await page.ev(TIP), 'none')

            # It must come back when the pointer really moves, or the fix has
            # simply broken the tooltip.
            here = await page.ev(BOX % (json.dumps('beta.h5'), 't'))
            await move(page, here[0] + 40, here[1] + 50)
            await move(page, here[0], here[1])
            check('a real move onto a tab brings it back', await page.ev(TIP), 'block')
            check('  showing that tab, not the closed one', await page.ev(
                "document.getElementById('fileTabTooltip').textContent.includes('beta.h5')"), True)

            # --- a disabled file: removeFile drops the one element -----------
            check('four tabs, two of them disabled', await page.ev(
                SETUP % ("[['a.h5', true], ['b.h5', false], "
                         "['c.h5', false], ['d.h5', true]]")), 4)
            shown = await hover_then_close(page, 'b.h5')
            check('hovering a disabled tab shows its tooltip too', shown, 'block')
            check('closing it takes the tooltip away as well', await page.ev(TIP), 'none')
            check('  and the other three are still there', await page.ev(
                "document.querySelectorAll('.file-tab').length"), 3)

            # --- the last tab: nothing slides under the pointer --------------
            check('one tab left', await page.ev(SETUP % "[['only.h5', true]]"), 1)
            await hover_then_close(page, 'only.h5')
            check('closing the only tab leaves no tooltip behind', await page.ev(TIP), 'none')
            check('  and no tabs', await page.ev(
                "document.querySelectorAll('.file-tab').length"), 0)

            # --- what a file says about itself --------------------------------
            check('a file whose Information is hostile is open',
                  await page.ev(HOSTILE % json.dumps(HOSTILE_INFO)), ['hostile.h5'])
            tab = await page.ev(BOX % (json.dumps('hostile.h5'), 't'))
            await move(page, tab[0] + 40, tab[1] + 300)
            await move(page, tab[0], tab[1])
            await asyncio.sleep(1.5)
            after = await page.ev(AFTER_HOVER)
            check('  hovering its tab shows the tooltip, and the page stays where it is',
                  (after['shown'], after['href']), ('block', '/rb.html'))
            check('  no stylesheet of the file\'s is loaded', after['sheets'], 0)
            check('  nothing the allowlist leaves out reaches the page', after['foreign'], [])
            check('  a link keeps its text and loses its javascript: address; formatting stays',
                  after['info'], '<a>a link</a><p>Base case, <b>2026</b></p>')
            check('  and nothing ran', after['ran'], 'undefined')

            check('no console errors throughout', page.logs[:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
