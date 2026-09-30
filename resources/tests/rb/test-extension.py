#!/usr/bin/env python3
"""The VS Code button: the dialog that hands out the HDF5 Browser extension.

rb-vscode/release.mjs puts the latest package in rb-vscode/dist, as
hdf5-browser.vsix, with latest.json saying which version it is. The dialog
reads latest.json when it opens, so a release needs no change to the page:

    no note at all       nothing is published; said so, and no Download.
    a note               the version, size, date and the VS Code it needs;
                         Download saves the package under a name with the
                         version in it, and asks for this version's copy
                         (?v=), so a cached older one is not handed out.
    a broken note        reported: that one IS a fault.

The note is stubbed by replacing window.fetch, as test-sample.py stubs its
manifest. What is really published is checked too, when there is something:
the served package is the size and hash the served note says, and the note is
signed with the release key the extension carries (rb-vscode/src/update.js
checks it so before an installed copy updates itself; a note from before the
signing, 0.1.4's, is said to be one).

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-extension.py

Exit status is 0 when every check passes.
"""
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
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


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

# Whether the note's signature is the release key's, checked by the updater's own code.
VERIFY = r"""
const crypto = require('crypto');
const fs = require('fs');
const [update, key, id, version, sha256, signature] = process.argv.slice(1);
const { verifyRelease } = require(update);
process.stdout.write(String(verifyRelease(crypto.createPublicKey(fs.readFileSync(key)), id, version, sha256, signature)));
"""

# Answer the release note with whatever this test wants; `body` of None stands for a 404.
STUB = """(() => {
  if (!window._realFetch) window._realFetch = window.fetch;
  window.fetch = (input, init) => {
    const url = String(input && input.url ? input.url : input);
    if (url.includes('rb-vscode/dist/latest.json')) {
      const body = %s;
      return Promise.resolve(body === null
        ? new Response('not found', { status: 404 })
        : new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    return window._realFetch(input, init);
  };
  return true;
})()"""

STATE = """(() => {
  const d = document.getElementById('vscodeDialog');
  const a = document.getElementById('vscodeDownload');
  const err = document.getElementById('vscodeError');
  return {
    open: d.style.display !== 'none',
    release: document.getElementById('vscodeRelease').textContent,
    download: a.style.display !== 'none',
    href: a.getAttribute('href'),
    saveAs: a.getAttribute('download'),
    cli: document.getElementById('vscodeCli').textContent,
    error: err.style.display === 'none' ? '' : err.textContent
  };
})()"""


async def opened(page, body):
    await page.ev(STUB % json.dumps(body))
    await page.ev("(async () => { closeVscodeDialog(); document.querySelector('header [data-on-click=openVscodeDialog]').click();"
                  " await new Promise(r => setTimeout(r, 400)); })()")
    return await page.ev(STATE)


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            check('the header has a VS Code button', await page.ev(
                "(document.querySelector('header [data-on-click=openVscodeDialog]') || {}).textContent || ''"), ' VS Code')

            s = await opened(page, None)
            check('with nothing published, the dialog says so', (s['open'], s['release']),
                  (True, 'No version of the extension is published at the moment.'))
            check('  and offers no Download', (s['download'], s['error']), (False, ''))

            note = {'name': 'HDF5 Browser', 'version': '9.8.7', 'file': 'hdf5-browser.vsix', 'bytes': 4739681,
                    'sha256': '0' * 64, 'released': '2026-09-30T08:00:00.000Z', 'build': 'abc1234 2026-09-30 08:00', 'vscode': '^1.100.0'}
            s = await opened(page, json.dumps(note))
            check('a release note gives the version, size, date and the VS Code it needs', s['release'],
                  'Version 9.8.7, 4.5 MB, released 2026-09-30, for VS Code 1.100 or later')
            check('  Download asks for this version\'s copy of the package', (s['download'], s['href']),
                  (True, './rb-vscode/dist/hdf5-browser.vsix?v=9.8.7'))
            check('  and saves it under a name with the version in it', s['saveAs'], 'hdf5-browser-9.8.7.vsix')
            check('  as the terminal line installs it', s['cli'], 'code --install-extension hdf5-browser-9.8.7.vsix')

            s = await opened(page, '"not a note"')
            check('a note without a version is reported, and offers no Download',
                  (s['error'], s['download']), ('Could not find the latest version: the release note names no version', False))
            s = await opened(page, '{ broken')
            check('a note that is not JSON is reported', s['error'].startswith('Could not find the latest version:'), True)

            await page.ev("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); true")
            check('Escape closes the dialog', await page.ev(STATE + ".open"), False)
            await page.ev("(async () => { document.querySelector('header [data-on-click=openVscodeDialog]').click(); await new Promise(r => setTimeout(r, 300));"
                          " const d = document.getElementById('vscodeDialog'); d.dispatchEvent(new MouseEvent('click', { bubbles: true })); })()")
            check('  and so does a click beside it', await page.ev(STATE + ".open"), False)

            # What is published, if anything: the package is what its note says.
            try:
                served = json.load(urllib.request.urlopen('http://127.0.0.1:8765/rb-vscode/dist/latest.json'))
            except urllib.error.HTTPError as e:
                served = None
                print(f'skip  the published package: none (HTTP {e.code})')
            if served:
                data = urllib.request.urlopen('http://127.0.0.1:8765/rb-vscode/dist/hdf5-browser.vsix').read()
                check('the published package is the size and hash its note says',
                      (len(data), hashlib.sha256(data).hexdigest()), (served['bytes'], served['sha256']))
                package = json.load(open(os.path.join(ROOT, 'rb-vscode', 'package.json')))
                check('  and a zip, of the version package.json had when it was released',
                      (data[:2], served['version'].count('.')), (b'PK', 2))
                if 'signature' in served:
                    signed = subprocess.run(['node', '-e', VERIFY, os.path.join(ROOT, 'rb-vscode', 'src', 'update.js'),
                                             os.path.join(ROOT, 'rb-vscode', 'src', 'release-public-key.pem'),
                                             f'{package["publisher"]}.{package["name"]}', served['version'], served['sha256'],
                                             served['signature']], capture_output=True, text=True)
                    check('  and signed with the release key the extension carries', signed.stdout or signed.stderr[-300:], 'true')
                else:
                    print(f'skip  the signature: the note of {served["version"]} is from before the releases were signed')
                print(f'      published: {served["version"]} (package.json now {package["version"]})')

            check('no console errors throughout', page.logs[:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))
            await bws.recv()

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
