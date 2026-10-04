#!/usr/bin/env python3
"""rb.html's tab icon: the HDF Group's H, cut through its crossbar, in the
kvot mark's language (scripts/gen-rb-icon.py draws it).

The page links the SVG first, a 32-pixel PNG for what will not take one, and a
180-pixel touch icon. Each must decode as a picture: an SVG whose comment holds
"--" is not XML, and the browser drops it without a word, leaving the tab
blank. The drawing keeps to the mark's three tones, without gradients, and is
named for the page.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-icon.py

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


ICON = """(async () => {
  const links = Object.fromEntries([...document.querySelectorAll('link[rel~="icon"], link[rel="apple-touch-icon"]')]
    .map((l) => [l.rel, [l.getAttribute('href'), l.type || '', l.getAttribute('sizes') || '']]));
  const load = (src) => new Promise((ok) => {
    const i = new Image();
    i.onload = () => ok([i.naturalWidth, i.naturalHeight]);
    i.onerror = () => ok(null);
    i.src = src;
  });
  const svg = await (await fetch(links.icon[0], { cache: 'no-store' })).text();
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
  return {
    links,
    svg: await load(links.icon[0]),
    png: await load(links['alternate icon'][0]),
    touch: await load(links['apple-touch-icon'][0]),
    xml: !doc.querySelector('parsererror'),
    title: doc.querySelector('svg > title')?.textContent,
    viewBox: doc.documentElement.getAttribute('viewBox'),
    fills: [...new Set([...svg.matchAll(/fill="(#[0-9a-f]{6})"/gi)].map((m) => m[1].toLowerCase()))].sort(),
    other: /<(linearGradient|radialGradient|path|rect|circle|image|text)\\b|stroke=/.test(svg),
  };
})()"""


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=3)
        try:
            icon = await page.ev(ICON)
            check('the SVG first, a 32-pixel PNG for what will not take one, and a touch icon',
                  icon['links'], {
                      'icon': ['./resources/images/rb-icon.svg', 'image/svg+xml', ''],
                      'alternate icon': ['./resources/images/rb-icon-32.png', 'image/png', '32x32'],
                      'apple-touch-icon': ['./resources/images/rb-icon-180.png', '', '']})
            check('each decodes as a picture of its size',
                  (icon['svg'] is not None, icon['png'], icon['touch']), (True, [32, 32], [180, 180]))
            check('the SVG is XML, in the 64-unit square, and named for the page',
                  (icon['xml'], icon['viewBox'], icon['title']), (True, '0 0 64 64', 'HDF5 Browser'))
            check('drawn in the kvot mark’s three tones only: polygons, no strokes, no gradients',
                  (icon['fills'], icon['other']), (['#344126', '#bb6c5d', '#f3b87b'], False))
            check('no console errors', page.logs[:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))
            await bws.recv()

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
