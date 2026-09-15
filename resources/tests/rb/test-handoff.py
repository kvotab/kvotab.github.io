"""Tests for the in-memory file handoff into rb.html.

Covers the two transports a producing page can use — a postMessage handshake
and a ?url= link — plus the checks that stop an unwanted file getting in.

Run the server and Chrome as described in README.md, then:

    python3 test-handoff.py
"""
import asyncio
import json
import urllib.request

import websockets

from driver import open_page

BASE = 'http://127.0.0.1:8765'
DEMO = BASE + '/resources/tests/rb/handoff-demo.html'


async def check(page, label, expr, want, results):
    """Evaluate expr in the page and record whether it matched want."""
    got = await page.ev(expr)
    ok = got == want
    results.append((label, ok, got))
    print(('  PASS  ' if ok else '  FAIL  ') + label + ('' if ok else f'\n          got {got!r}\n          want {want!r}'))


async def main():
    results = []
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'],
                                  max_size=200 * 1024 * 1024) as bws:

        # ── postMessage handshake, producer page → rb.html in an iframe ──
        print('postMessage handoff')
        _tid, page = await open_page(bws, DEMO, settle=2)
        await check(page, 'producer hands the buffer over and rb.html opens it',
                    '(async () => (await sendToIframe()).join(","))()',
                    'produced-in-memory.h5', results)
        await check(page, 'the file is mounted and enabled inside the frame',
                    """(() => {
                      const w = document.querySelector('iframe').contentWindow;
                      return w.eval(`JSON.stringify({
                        order: fileOrder,
                        enabled: fileStates['produced-in-memory.h5'] === true,
                        mounted: typeof loadedFiles['produced-in-memory.h5'] === 'object',
                        tabs: [...document.querySelectorAll('.file-tab-name')].map(t => t.textContent)
                      })`);
                    })()""",
                    json.dumps({'order': ['produced-in-memory.h5'], 'enabled': True,
                                'mounted': True, 'tabs': ['produced-in-memory.h5']},
                               separators=(',', ':')),
                    results)
        await check(page, 'the tree rendered from the handed-over file',
                    """(() => {
                      const w = document.querySelector('iframe').contentWindow;
                      return w.document.querySelectorAll('#tree .tree-item').length > 0;
                    })()""",
                    True, results)

        # ── the receiver's guards ──
        print('receiver guards')
        await check(page, 'a message from a disallowed origin is ignored',
                    """(() => {
                      const w = document.querySelector('iframe').contentWindow;
                      return w.isHandoffOriginAllowed('https://evil.example') === false
                          && w.isHandoffOriginAllowed(location.origin) === true;
                    })()""",
                    True, results)
        await check(page, 'the listed dev origin is allowed, near misses are not',
                    """(() => {
                      const w = document.querySelector('iframe').contentWindow;
                      return JSON.stringify([
                        w.isHandoffOriginAllowed('http://localhost:8080'),
                        w.isHandoffOriginAllowed('http://localhost:8081'),
                        w.isHandoffOriginAllowed('http://127.0.0.1:8080'),
                        w.isHandoffOriginAllowed('https://localhost:8080')
                      ]);
                    })()""",
                    json.dumps([True, False, False, False], separators=(',', ':')), results)
        await check(page, 'non-HDF5 bytes are refused',
                    """(async () => {
                      const w = document.querySelector('iframe').contentWindow;
                      const junk = new TextEncoder().encode('not an hdf5 file at all').buffer;
                      try { await w.ingestHdf5Buffer('junk.h5', junk, 'test'); return 'accepted'; }
                      catch (e) { return e.message.includes('HDF5 signature') ? 'refused' : e.message; }
                    })()""",
                    'refused', results)
        await check(page, 'an empty buffer is refused',
                    """(async () => {
                      const w = document.querySelector('iframe').contentWindow;
                      try { await w.ingestHdf5Buffer('empty.h5', new ArrayBuffer(0), 'test'); return 'accepted'; }
                      catch (e) { return e.message.includes('is empty') ? 'refused' : e.message; }
                    })()""",
                    'refused', results)
        await check(page, 'a hostile name is reduced to a plain file name',
                    """(() => {
                      const w = document.querySelector('iframe').contentWindow;
                      return JSON.stringify([
                        w.sanitizeHandoffName('../../etc/passwd'),
                        w.sanitizeHandoffName(''),
                        w.sanitizeHandoffName('plain')
                      ]);
                    })()""",
                    json.dumps(['.._.._etc_passwd.h5', 'handoff.h5', 'plain.h5'],
                               separators=(',', ':')), results)
        await check(page, 'rb.html without #handoff does not listen',
                    """(async () => {
                      const f = document.createElement('iframe');
                      f.src = '../../../rb.html';
                      document.body.appendChild(f);
                      await new Promise(r => f.addEventListener('load', r));
                      await new Promise(r => setTimeout(r, 1500));
                      const buf = await (await fetch('../../data/SFR_FSAR_CCP14.h5')).arrayBuffer();
                      f.contentWindow.postMessage({kvot:'rb-open', name:'sneaky.h5', buffer: buf},
                                                 location.origin, [buf]);
                      await new Promise(r => setTimeout(r, 2500));
                      const count = f.contentWindow.eval('fileOrder.length');
                      f.remove();
                      return count;
                    })()""",
                    0, results)

        # ── ?url= with a blob: URL, the same bytes by the cheaper route ──
        print('?url= blob handoff')
        await check(page, 'a blob: URL made here opens in rb.html',
                    """(async () => {
                      const buf = await (await fetch('../../data/SFR_FSAR_CCP14.h5')).arrayBuffer();
                      const blobUrl = URL.createObjectURL(new Blob([buf]));
                      const f = document.createElement('iframe');
                      f.src = '../../../rb.html?url=' + encodeURIComponent(blobUrl);
                      document.body.appendChild(f);
                      for (let i = 0; i < 60; i++) {
                        await new Promise(r => setTimeout(r, 500));
                        let first = null;
                        try { first = f.contentWindow.eval('fileOrder[0] || null'); } catch (_) {}
                        if (first) { f.remove(); return first; }
                      }
                      f.remove();
                      return 'timed out';
                    })()""",
                    'handoff.h5', results)
        await check(page, 'an unsupported scheme in ?url= is refused',
                    """(async () => {
                      const w = document.querySelector('iframe').contentWindow;
                      try { await w.ingestHdf5FromUrl('ftp://example.com/x.h5', 'test'); return 'accepted'; }
                      catch (e) { return e.message.includes('Unsupported URL scheme') ? 'refused' : e.message; }
                    })()""",
                    'refused', results)

        bad = [entry for entry in page.logs if entry[0] == 'exception']
        print(f'\nconsole exceptions: {len(bad)}')
        for kind, text in bad:
            print(f'  {kind}: {text}')

    failed = [label for label, ok, _ in results if not ok]
    print(f'\n{len(results) - len(failed)}/{len(results)} passed')
    if failed or bad:
        raise SystemExit(1)


asyncio.run(main())
