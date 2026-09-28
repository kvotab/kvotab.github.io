#!/usr/bin/env python3
"""A file dropped on an HDF5 Browser goes into it, as another file tab.

VS Code keeps a drag out of every webview unless Shift is held: it turns the
webview's pointer events off as soon as a drag is over its own window, so a
plain drop never reaches the page. VS Code opens the file as another editor
in the group instead, and the extension puts it into the browser that was
showing there (extension.js, browserShowingBehind). With Shift held the drop
does reach the page: files from the Finder the page reads itself
(rb-dragdrop.js), addresses from VS Code's Explorer it hands to the extension
(webview/late.js).

The drags are CDP's Input.dispatchDragEvent on the workbench's window. One that
comes in over the activity bar, as a drag from outside VS Code does, is kept
out of the webview by VS Code as a real one is. CDP cannot carry a drag from
the workbench into the webview's frame, so the drop with Shift is one that
starts over the page, which is what the page gets of a real one.

    RB_VSCODE_EXE=... python3 test/test-drop.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile

import websockets

from vscode_driver import VSCode

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, '..', '..', 'resources', 'tests', 'rb', 'fixtures')

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'), flush=True)
    if not ok:
        failures.append(label)


def fixture(name):
    return os.path.abspath(os.path.join(FIXTURES, name))


class Workbench:
    """CDP on VS Code's own window: where a drag is dispatched and the webviews sit."""

    def __init__(self, ws):
        self.ws = ws
        self.seq = 0

    async def send(self, method, params=None):
        self.seq += 1
        await self.ws.send(json.dumps({'id': self.seq, 'method': method, 'params': params or {}}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get('id') == self.seq:
                return r

    async def ev(self, expr):
        r = await self.send('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        return r.get('result', {}).get('result', {}).get('value')

    async def webview_box(self):
        boxes = await self.ev("[...document.querySelectorAll('iframe.webview')].map(f => { const r = f.getBoundingClientRect();"
                              " return { x: r.x, y: r.y, w: r.width, h: r.height }; }).filter(b => b.w > 100 && b.h > 100)")
        return boxes[0] if boxes else None

    async def drag(self, box, data, shift=False, from_outside=True):
        """A drag onto the middle of the webview; from outside it comes in over the activity bar."""
        x, y = box['x'] + box['w'] / 2, box['y'] + box['h'] / 2
        # The pointer comes to the drag as a real one does: moving, no button
        # down. That is what hands a webview its pointer events back after the
        # drag before (VS Code's drag monitor); without it one that starts over
        # the page here would start over the workbench instead.
        await self.send('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 20 if from_outside else x, 'y': y, 'buttons': 0})
        await asyncio.sleep(0.2)
        path = ([('dragEnter', 20), ('dragOver', 20), ('dragOver', x / 2)] if from_outside else [('dragEnter', x)])
        path += [('dragOver', x), ('dragOver', x), ('drop', x)]
        for kind, px in path:
            r = await self.send('Input.dispatchDragEvent', {'type': kind, 'x': px, 'y': y, 'data': data,
                                                            'modifiers': 8 if shift else 0})
            if 'error' in r:
                raise RuntimeError(f'{kind}: {r["error"]}')
            await asyncio.sleep(0.2)
        # What ends a real drag for VS Code: the button up, a move with none down.
        await self.send('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y, 'buttons': 0})
        await asyncio.sleep(0.3)

    async def pointer_events(self):
        return await self.ev("getComputedStyle(document.querySelector('iframe.webview')).pointerEvents")


def files(*paths):
    return {'items': [], 'files': list(paths), 'dragOperationsMask': 1}


def addresses(*paths):
    """What a drag from VS Code's Explorer carries: addresses, not files."""
    uris = ['file://' + p for p in paths]
    return {'items': [{'mimeType': 'application/vnd.code.uri-list', 'data': '\r\n'.join(uris)},
                      {'mimeType': 'text/uri-list', 'data': '\r\n'.join(uris)},
                      {'mimeType': 'ResourceURLs', 'data': json.dumps(uris)}], 'dragOperationsMask': 7}


async def files_in(page, want, seconds=20):
    got = None
    for _ in range(int(seconds / 0.25)):
        got = await page.ev('fileOrder.slice()')
        if got == want:
            break
        await asyncio.sleep(0.25)
    return got


async def tabs_become(vs, want, seconds=10):
    got = None
    for _ in range(int(seconds / 0.25)):
        got = [t['label'] for t in vs.command('tabs')]
        if got == want:
            break
        await asyncio.sleep(0.25)
    return got


async def main():
    work = tempfile.mkdtemp(prefix='rbv-drop-')
    copies = {}
    for name in ('b1', 'b2', 'b3', 'b4', 'b5', 'b6', 'm1', 'm2', 'm3', 'm4'):
        copies[name] = os.path.join(work, f'{name}.h5')
        shutil.copy(fixture('sample-b.h5'), copies[name])
    notes = os.path.join(work, 'notes.txt')
    with open(notes, 'w') as fh:
        fh.write('not HDF5\n')

    vs = VSCode().start()
    page = None
    try:
        m = vs.mark()
        vs.command('open', paths=[fixture('sample-a.h5')])
        vs.wait_event(lambda e: e['type'] == 'status' and e.get('kind') == 'opened', 180, 'sample-a.h5 to open', since=m)
        page = await vs.page()
        target = [t for t in vs.targets() if t['type'] == 'page' and 'workbench' in t.get('url', '')][0]
        async with websockets.connect(target['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as ws:
            wb = Workbench(ws)
            box = await wb.webview_box()

            # --- a plain drop, as from the Finder --------------------------
            m = vs.mark()
            await wb.drag(box, files(fixture('sample-b.h5')))
            e = vs.wait_event(lambda e: e['type'] in ('addedInstead', 'ready'), 60, 'the drop to be taken', since=m)
            check('a plain drop is kept from the page by VS Code, as a real one is, and the file goes into the browser it was dropped on',
                  (e['type'], os.path.basename(e.get('file', ''))), ('addedInstead', 'sample-b.h5'))
            check('  as another file tab there', await files_in(page, ['sample-a.h5', 'sample-b.h5']), ['sample-a.h5', 'sample-b.h5'])
            check('  not in a browser of its own: the editor VS Code opened for it closes again',
                  await tabs_become(vs, ['sample-a.h5']), ['sample-a.h5'])
            check('  and the browser is the editor showing', [t['label'] for t in vs.command('tabs') if t['active']], ['sample-a.h5'])
            check('  one view, as before', len(vs.command('views')), 1)

            # Closed as soon as it showed, that editor left VS Code's handling
            # of the drop unfinished, and every drop after it reached nothing.
            await wb.drag(box, files(copies['b1']))
            check('the next drop is taken too', await files_in(page, ['sample-a.h5', 'sample-b.h5', 'b1.h5']),
                  ['sample-a.h5', 'sample-b.h5', 'b1.h5'])
            await tabs_become(vs, ['sample-a.h5'])
            await wb.drag(box, files(copies['b2'], copies['b3']))
            check('  and so are two files dropped at once', await files_in(page, ['sample-a.h5', 'sample-b.h5', 'b1.h5', 'b2.h5', 'b3.h5']),
                  ['sample-a.h5', 'sample-b.h5', 'b1.h5', 'b2.h5', 'b3.h5'])
            check('  each editor VS Code opened for them closed again', await tabs_become(vs, ['sample-a.h5']), ['sample-a.h5'])

            m = vs.mark()
            await wb.drag(box, files(fixture('sample-b.h5')))
            await asyncio.sleep(2)
            check('the same file dropped again adds nothing', await page.ev('fileOrder.slice()'),
                  ['sample-a.h5', 'sample-b.h5', 'b1.h5', 'b2.h5', 'b3.h5'])
            before = await page.ev('fileOrder.slice()')

            # --- with Shift, from the Explorer: addresses ------------------
            m = vs.mark()
            await wb.drag(box, addresses(fixture('lzf.h5')), shift=True, from_outside=False)
            e = vs.wait_event(lambda e: e['type'] == 'dropped', 30, 'the page to pass the drop on', since=m)
            check('with Shift, a drop from the Explorer reaches the page, which passes its addresses on',
                  [os.path.basename(p) for p in e['files']], ['lzf.h5'])
            check('  and the extension adds the file', await files_in(page, before + ['lzf.h5']), before + ['lzf.h5'])

            m = vs.mark()
            await wb.drag(box, addresses(notes), shift=True, from_outside=False)
            e = vs.wait_event(lambda e: e['type'] == 'dropped', 30, 'the page to pass the drop on', since=m)
            check('  a name that is not HDF5 is not read', e['files'], [])
            await asyncio.sleep(1)
            check('  and nothing is added', await page.ev('fileOrder.slice()'), before + ['lzf.h5'])

            # --- with Shift, from the Finder: files the page reads ---------
            await wb.drag(box, files(copies['b4']), shift=True, from_outside=False)
            check('with Shift, a file from the Finder is read by the page itself',
                  await files_in(page, before + ['lzf.h5', 'b4.h5']), before + ['lzf.h5', 'b4.h5'])
            check('  in this view, no other', len(vs.command('views')), 1)

            await wb.drag(box, files(copies['b5']))
            check('a plain drop after them still goes into the browser',
                  await files_in(page, before + ['lzf.h5', 'b4.h5', 'b5.h5']), before + ['lzf.h5', 'b4.h5', 'b5.h5'])
            await tabs_become(vs, ['sample-a.h5'])

            # --- what still opens a browser of its own --------------------
            vs.command('setting', section='hdf5Browser', key='addToOpenBrowser', value=False)
            m = vs.mark()
            await wb.drag(box, files(copies['b6']))
            vs.wait_event(lambda e: e['type'] == 'ready', 60, 'a new view', since=m)
            check('with hdf5Browser.addToOpenBrowser off, a drop opens a browser of its own', len(vs.command('views')), 2)
            vs.command('setting', section='hdf5Browser', key='addToOpenBrowser', value=True)
            vs.command('closeAll')
            await page.close()
            page = None

            m = vs.mark()
            vs.command('open', paths=[fixture('sample-a.h5')])
            vs.wait_event(lambda e: e['type'] == 'status' and e.get('kind') == 'opened', 180, 'sample-a.h5 to open', since=m)
            m = vs.mark()
            vs.command('open', paths=[copies['b1']], preview=True)
            vs.wait_event(lambda e: e['type'] == 'status' and e.get('kind') == 'opened', 120, 'the preview to open', since=m)
            check('a preview (a single click in the Explorer) opens a browser of its own', len(vs.command('views')), 2)
            vs.command('closeAll')

            m = vs.mark()
            vs.command('open', paths=[fixture('sample-a.h5')])
            vs.wait_event(lambda e: e['type'] == 'status' and e.get('kind') == 'opened', 180, 'sample-a.h5 to open', since=m)
            m = vs.mark()
            vs.command('together', paths=[copies['b2'], fixture('lzf.h5')])
            vs.wait_event(lambda e: e['type'] == 'status' and e.get('kind') == 'opened'
                          and any(f['name'] == 'lzf.h5' for f in e.get('opened', [])), 120, 'Open Together', since=m)
            check('Open Together opens a browser of its own, whatever is showing', len(vs.command('views')), 2)

            # --- several files dropped where no browser is open ------------
            # VS Code opens a tab each and loads only the first; the browser
            # it gets takes the others, which were waiting to be clicked.
            vs.command('closeAll')
            await tabs_become(vs, [])
            area = await wb.ev("(() => { const r = document.querySelector('.part.editor').getBoundingClientRect();"
                               " return { x: r.x, y: r.y, w: r.width, h: r.height }; })()")
            m = vs.mark()
            await wb.drag(area, files(copies['m1'], copies['m2'], copies['m3']))
            vs.wait_event(lambda e: e['type'] == 'gathered', 60, 'the other files to be taken', since=m)
            page = await vs.page_for('m1.h5')
            check('three files dropped where no browser is open go into one browser',
                  await files_in(page, ['m1.h5', 'm2.h5', 'm3.h5']), ['m1.h5', 'm2.h5', 'm3.h5'])
            check('  whose tab is the only one left', await tabs_become(vs, ['m1.h5']), ['m1.h5'])
            check('  one view', len(vs.command('views')), 1)
            box = await wb.webview_box()
            await wb.drag(box, files(copies['m4']))
            check('  and the next drop goes into it too', await files_in(page, ['m1.h5', 'm2.h5', 'm3.h5', 'm4.h5']),
                  ['m1.h5', 'm2.h5', 'm3.h5', 'm4.h5'])
            check('  with no other tab left', await tabs_become(vs, ['m1.h5']), ['m1.h5'])

        check('nothing was logged as an error', [e['text'][:200] for e in vs.events if e['type'] == 'log'], [])
    finally:
        if page:
            await page.close()
        vs.stop()
        shutil.rmtree(work, ignore_errors=True)

    print(f'\n{checks - len(failures)} of {checks} checks passed', flush=True)
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
