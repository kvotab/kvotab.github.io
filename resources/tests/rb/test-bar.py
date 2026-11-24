#!/usr/bin/env python3
"""The files bar: the files open, a box each, Open, and the full window.

Above the two panels, since 2026-11-24, in place of the tabs and buttons that
hung from the site's header:

    a box a file      its tick puts the file in the tree and the charts; its
                      number is its place among the ticked ones (1 is drawn
                      with full lines in a chart of several files, the others
                      thinner); a drag or Alt with an arrow moves it; × or
                      Delete closes it, and the keyboard goes to the next box
    Open              a menu of the ways in: files on this computer, a URL,
                      Google Drive (when configured), the sample data, and the
                      VS Code extension
    the right end     ∅ ∩ ∪ for two files ticked or more, and the full window:
                      the page without the site's header and footer, the kvot
                      mark then going home and the light/dark switch beside the
                      button; kept in localStorage kvot.rb.full and put on by
                      the page's head before the first paint
    many files        the boxes wrap to more rows, and the kvot mark, Open and
                      the right end stay on the first (they slid down to the
                      middle of the rows until they were set at the top)

Clicks and keys are real ones, sent with CDP's Input domain, since what is
tested is what the browser does with them: a label that ticks its box, a key
on a focused tick. A drag is not: SortableJS moves the box with the browser's
own drag and drop, which CDP's mouse does not start, so its end is played by
moving the box in the list and calling the end it was given.

Uses the committed fixtures sample-a.h5 and sample-b.h5. Start the server and
the browser as in README.md, then

    python3 resources/tests/rb/test-bar.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

from driver import open_page, load_samples

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


A, B = 'sample-a.h5', 'sample-b.h5'

# Every box, in order: its file, tick, number, class, and whether it is drawn.
BOXES = r"""[...document.querySelectorAll('#fileTabs .file-tab')].map(b => [b.dataset.file,
  b.querySelector('.file-tab-check').checked, b.querySelector('.file-tab-order').textContent,
  b.classList.contains('enabled') ? 'enabled' : 'disabled'])"""

# What has the keyboard: a box's tick or ×, Open, or something else.
FOCUS = r"""(() => { const e = document.activeElement, b = e && e.closest('.file-tab');
  return b ? [b.dataset.file, e.classList.contains('file-tab-close') ? 'close' : 'tick'] : (e && e.id) || e.tagName; })()"""

CENTER = r"""((sel) => { const e = document.querySelector(sel); if (!e) return null;
  const r = e.getBoundingClientRect(); return r.width ? [r.left + r.width / 2, r.top + r.height / 2] : null; })(%s)"""

FULL = r"""(() => { const h = document.querySelector('body > header'), f = document.querySelector('body > footer'),
  b = document.getElementById('rbFull'), shown = (s) => { const e = document.querySelector(s); return !!e && getComputedStyle(e).display !== 'none'; };
  return { on: document.documentElement.classList.contains('rb-full'), header: getComputedStyle(h).display,
    footer: getComputedStyle(f).display, barTop: Math.round(document.getElementById('rbBar').getBoundingClientRect().top),
    mark: shown('#rbBar .rb-homelink'), theme: shown('#rbBar .theme-toggle'),
    corners: [...b.querySelectorAll('path')].map(p => getComputedStyle(p).display),
    pressed: b.getAttribute('aria-pressed'), key: localStorage.getItem('kvot.rb.full'),
    panelsEnd: Math.round(document.getElementById('leftPanel').getBoundingClientRect().bottom) }; })()"""

# With the boxes on more than one row: where the bar's other parts stand
# against the first row, in px (0: level with its top, or its middle for the mark).
TOPS = r"""(() => { const r = (s) => document.querySelector(s).getBoundingClientRect();
  const boxes = [...document.querySelectorAll('#fileTabs .file-tab')].map(b => b.getBoundingClientRect());
  const first = boxes[0], m = r('#rbBar .rb-homelink');
  return { rows: new Set(boxes.map(b => Math.round(b.top))).size, open: Math.round(r('#rbOpen').top - first.top),
    trees: Math.round(r('#treeModeContainer').top - first.top), full: Math.round(r('#rbFull').top - first.top),
    mark: m.height ? Math.round(m.top + m.height / 2 - (first.top + first.height / 2)) : null }; })()"""

# Files enough to wrap the boxes: copies of sample-a.h5 under longer names.
MANY = r"""(async () => { const { FS, File } = window.h5wasm; const names = [];
  for (let i = 1; i <= %d; i++) { const n = 'run-' + String(i).padStart(2, '0') + '-of-the-assessment.h5'; names.push(n);
    loadedFileBuffers[n] = loadedFileBuffers['sample-a.h5']; const p = '/many-' + n;
    FS.writeFile(p, new Uint8Array(loadedFileBuffers[n])); loadedFiles[n] = new File(p, 'r');
    fileStates[n] = true; if (!fileOrder.includes(n)) fileOrder.push(n); }
  await updateTabs(true); await new Promise(r => setTimeout(r, 1500)); return names; })()"""

# The site's message banner (kvot-errors.js): where it stands against the bar.
BANNER = r"""(async () => { showFailureBanner('A message from the page', 'info');
  await new Promise(r => setTimeout(r, 100));
  const b = document.getElementById('failureBanner').getBoundingClientRect(), bar = document.getElementById('rbBar').getBoundingClientRect();
  hideFailureBanner(); return [b.top >= bar.bottom, Math.round(b.top - bar.bottom)]; })()"""

# The page's state when the parser puts rb-tabs.js in: before the page's own
# script has run (the button is not marked pressed yet), so only the head can
# have put it in the full window. The parser runs a microtask checkpoint
# before it runs a script, so this record comes first.
EARLY = r"""new MutationObserver((records, observer) => {
  if (window.rbEarly || !document.querySelector('script[src*="rb-tabs.js"]')) return;
  const h = document.querySelector('body > header'), b = document.getElementById('rbFull');
  window.rbEarly = { full: document.documentElement.classList.contains('rb-full'),
    header: h ? getComputedStyle(h).display : null,
    barTop: Math.round(document.getElementById('rbBar').getBoundingClientRect().top),
    corners: [...b.querySelectorAll('path')].map((p) => getComputedStyle(p).display),
    pressed: b.getAttribute('aria-pressed') };
  observer.disconnect();
}).observe(document, { childList: true, subtree: true });"""


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)

        async def click_at(x, y):
            for kind in ('mousePressed', 'mouseReleased'):
                await page.send('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})

        async def click(selector):
            pos = await page.ev(CENTER % json.dumps(selector))
            if not pos:
                raise RuntimeError(f'nothing to click at {selector}')
            await click_at(*pos)
            await asyncio.sleep(0.4)

        async def key(name, code, vk, modifiers=0, text=None):
            down = {'type': 'keyDown' if text else 'rawKeyDown', 'key': name, 'code': code,
                    'windowsVirtualKeyCode': vk, 'modifiers': modifiers}
            if text:
                down['text'] = text
            await page.send('Input.dispatchKeyEvent', down)
            await page.send('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': name, 'code': code,
                                                      'windowsVirtualKeyCode': vk, 'modifiers': modifiers})
            await asyncio.sleep(0.5)

        async def settle():
            # toggleFileState redraws the boxes after a short pause (scheduleUpdateTabs)
            await asyncio.sleep(1.2)

        def box(name, part=''):
            return f'#fileTabs .file-tab[data-file="{name}"] {part}'.strip()

        try:
            await page.ev("localStorage.removeItem('kvot.rb.full'); true")

            # --- no file open ---------------------------------------------
            empty = await page.ev(r"""(() => { const hint = document.querySelector('.rb-files-hint');
              return [document.querySelectorAll('#fileTabs .file-tab').length, getComputedStyle(hint).display !== 'none',
                hint.textContent.trim(), document.getElementById('rbOpen').textContent.trim(),
                getComputedStyle(document.querySelector('body > header')).display,
                getComputedStyle(document.getElementById('treeModeContainer')).display]; })()""")
            check('with no file the bar says how to open one, beside Open',
                  empty, [0, True, 'No files open: drop them on the page, or', 'Open', 'grid', 'none'])
            check('and nothing is left in the site\'s header but its name',
                  await page.ev("[...document.querySelectorAll('body > header button, body > header #fileTabs')].length"), 0)

            # --- boxes ------------------------------------------------------
            await load_samples(page, [A, B])
            await asyncio.sleep(2)
            check('a file opened is a box, ticked and numbered in order',
                  await page.ev(BOXES), [[A, True, '1', 'enabled'], [B, True, '2', 'enabled']])
            check('  with ∅ ∩ ∪ at the bar\'s right end, for two files ticked',
                  await page.ev("getComputedStyle(document.getElementById('treeModeContainer')).display !== 'none'"), True)
            check('  and the hint gone', await page.ev("getComputedStyle(document.querySelector('.rb-files-hint')).display"), 'none')
            check('the site\'s message banner stands under the bar, not over its boxes and Open', await page.ev(BANNER), [True, 8])

            await click(box(B, '.file-tab-check'))
            await settle()
            check('a click on a tick takes the file out: unticked, unnumbered, and the other is 1',
                  await page.ev(BOXES), [[A, True, '1', 'enabled'], [B, False, '', 'disabled']])
            check('  the tree has the one file, and ∅ ∩ ∪ go',
                  (await page.ev("[...document.querySelectorAll('#tree .tree-item.root-node, #tree .tree-item[data-path=\"/\"]')].length"),
                   await page.ev("getComputedStyle(document.getElementById('treeModeContainer')).display")), (1, 'none'))
            await click(box(B, '.file-tab-name'))
            await settle()
            check('a click on the name ticks it again, as on the tick',
                  await page.ev(BOXES), [[A, True, '1', 'enabled'], [B, True, '2', 'enabled']])
            await page.ev(f"(() => {{ const b = document.querySelector({json.dumps(box(A))});"
                          " b.dispatchEvent(new MouseEvent('click', { bubbles: true })); })()")
            await settle()
            check('and a click on the box\'s edge, beside its label, ticks it as well',
                  await page.ev(BOXES), [[A, False, '', 'disabled'], [B, True, '1', 'enabled']])
            await page.ev("toggleFileState('sample-a.h5'); true")
            await settle()
            check('toggleFileState keeps the tick in step', await page.ev(BOXES),
                  [[A, True, '1', 'enabled'], [B, True, '2', 'enabled']])

            # --- keys -------------------------------------------------------
            await page.ev(f"document.querySelector({json.dumps(box(B, '.file-tab-check'))}).focus(); true")
            await key(' ', 'Space', 32, text=' ')
            await settle()
            check('Space on a tick takes the file out', await page.ev(BOXES),
                  [[A, True, '1', 'enabled'], [B, False, '', 'disabled']])
            check('  and the keyboard stays on that tick, though the boxes were drawn anew', await page.ev(FOCUS), [B, 'tick'])
            await key(' ', 'Space', 32, text=' ')
            await settle()
            await key('ArrowLeft', 'ArrowLeft', 37, modifiers=1)
            await settle()
            check('Alt+← moves a box one place, and the numbers follow',
                  await page.ev(BOXES), [[B, True, '1', 'enabled'], [A, True, '2', 'enabled']])
            check('  in the files\' order', await page.ev('fileOrder.slice()'), [B, A])
            check('  the keyboard still on the box moved', await page.ev(FOCUS), [B, 'tick'])
            await key('ArrowLeft', 'ArrowLeft', 37, modifiers=1)
            check('  not past the first place', await page.ev('fileOrder.slice()'), [B, A])
            await key('ArrowRight', 'ArrowRight', 39, modifiers=1)
            await settle()
            check('Alt+→ moves it back', await page.ev(BOXES), [[A, True, '1', 'enabled'], [B, True, '2', 'enabled']])

            # --- a drag's end -----------------------------------------------
            dragged = await page.ev(r"""(async () => {
              const list = document.getElementById('fileTabs');
              const [a, b] = list.querySelectorAll('.file-tab');
              list.insertBefore(b, a);
              Sortable.get(list).options.onEnd({});
              await new Promise(r => setTimeout(r, 1200));
              return [fileOrder.slice(), document.querySelectorAll('#fileTabs .file-tab-order')[0].textContent,
                Sortable.get(list) ? 1 : 0];
            })()""")
            check('a drag\'s end puts the files in the boxes\' order and numbers them again', dragged, [[B, A], '1', 1])
            await page.ev(r"""(async () => { const list = document.getElementById('fileTabs');
              const [b, a] = list.querySelectorAll('.file-tab'); list.insertBefore(a, b);
              Sortable.get(list).options.onEnd({}); await new Promise(r => setTimeout(r, 1200)); })()""")
            check('  and back', await page.ev('fileOrder.slice()'), [A, B])
            again = await page.ev(r"""(async () => { const list = document.getElementById('fileTabs'); let drawn = 0;
              const keep = window.updateTabs; window.updateTabs = (...a) => { drawn++; return keep(...a); };
              try { Sortable.get(list).options.onEnd({}); } finally { window.updateTabs = keep; }
              await new Promise(r => setTimeout(r, 300)); return drawn; })()""")
            check('a box let go where it was draws nothing again', again, 0)

            # --- Open ------------------------------------------------------
            await click('#rbOpen')
            menu = await page.ev(r"""(() => { const m = document.getElementById('rbOpenMenu'), b = document.getElementById('rbOpen');
              const r = m.getBoundingClientRect(), q = b.getBoundingClientRect();
              return { open: m.matches(':popover-open'), expanded: b.getAttribute('aria-expanded'),
                under: r.top >= q.bottom && r.top - q.bottom < 10, left: Math.round(r.left - q.left),
                items: [...m.querySelectorAll('.rb-menu-item')].filter(i => !i.hidden).map(i => i.textContent.trim()),
                first: document.activeElement === m.querySelector('.rb-menu-item:not([hidden])') }; })()""")
            shown = [i for i in menu.pop('items') if i != 'Google Drive…']
            check('Open opens its menu under it, left edges together, the first way focused',
                  menu, {'open': True, 'expanded': 'true', 'under': True, 'left': 0, 'first': True})
            check('  the ways in, and the extension last',
                  shown, ['Files on this computer…', 'From a URL…', 'Sample data…', 'VS Code extension…'])
            await key('ArrowDown', 'ArrowDown', 40)
            check('  ↓ moves to the next way', await page.ev("document.activeElement.textContent.trim()"), 'From a URL…')
            await key('Escape', 'Escape', 27)
            check('  Escape shuts it', await page.ev("document.getElementById('rbOpenMenu').matches(':popover-open')"), False)
            await click('#rbOpen')
            await click_at(700, 600)
            await asyncio.sleep(0.3)
            check('  and so does a click elsewhere', await page.ev("document.getElementById('rbOpenMenu').matches(':popover-open')"), False)
            await page.ev("window.__picked = 0; document.getElementById('fileInput').click = () => { window.__picked++; }; true")
            await click('#rbOpen')
            await click('#rbOpenMenu [data-on-click="openFilePicker"]')
            check('choosing "Files on this computer…" asks for files, and the menu shuts',
                  await page.ev("[window.__picked, document.getElementById('rbOpenMenu').matches(':popover-open')]"), [1, False])
            await click('#rbOpen')
            await click('#rbOpenMenu [data-on-click="openSampleDataDialog"]')
            await asyncio.sleep(0.8)
            check('choosing "Sample data…" opens its dialog',
                  await page.ev("getComputedStyle(document.getElementById('sampleDataDialog')).display !== 'none'"), True)
            await page.ev("closeSampleDataDialog(); true")

            # --- closing ----------------------------------------------------
            await page.ev(f"document.querySelector({json.dumps(box(A, '.file-tab-check'))}).focus(); true")
            await key('Delete', 'Delete', 46)
            await settle()
            check('Delete on a box closes its file', await page.ev(BOXES), [[B, True, '1', 'enabled']])
            check('  and the keyboard goes to the next box', await page.ev(FOCUS), [B, 'tick'])
            await click(box(B, '.file-tab-close'))
            await settle()
            check('× closes the last: no box, the hint again', await page.ev(
                "[document.querySelectorAll('#fileTabs .file-tab').length, getComputedStyle(document.querySelector('.rb-files-hint')).display !== 'none']"),
                [0, True])
            check('  and the tree says how to start', await page.ev("document.getElementById('tree').textContent.trim()"),
                  'Drop files on the page, or use Open, to start…')
            await load_samples(page, [A, B])
            await asyncio.sleep(2)
            await page.ev(f"document.querySelector({json.dumps(box(B, '.file-tab-check'))}).focus(); true")
            await key('Delete', 'Delete', 46)
            await settle()
            check('Delete on the last box: the keyboard goes to the one before', await page.ev(FOCUS), [A, 'tick'])
            await page.ev(f"document.querySelector({json.dumps(box(A, '.file-tab-check'))}).focus(); true")
            await key('Delete', 'Delete', 46)
            await settle()
            check('  and on the only one, to Open', await page.ev(FOCUS), 'rbOpen')
            await load_samples(page, [A, B])
            await asyncio.sleep(2)

            # --- the full window ---------------------------------------------
            before = await page.ev(FULL)
            check('the page starts with the site\'s header and footer, the mark and switch hidden',
                  (before['on'], before['header'], before['footer'], before['mark'], before['theme'], before['corners'], before['pressed']),
                  (False, 'grid', 'block', False, False, ['inline', 'none'], 'false'))
            await click('#rbFull')
            on = await page.ev(FULL)
            height = await page.ev('innerHeight')
            check('the four corners make the full window: no header or footer, the bar at the top',
                  (on['on'], on['header'], on['footer'], on['barTop'], on['pressed'], on['key']),
                  (True, 'none', 'none', 0, 'true', '1'))
            check('  the kvot mark at the bar\'s left, the light/dark switch beside the button, which now points in',
                  (on['mark'], on['theme'], on['corners']), (True, True, ['none', 'inline']))
            check('  the panels down to the window\'s foot, 16px above it', height - on['panelsEnd'], 16)
            check('  the mark goes home', await page.ev("document.querySelector('#rbBar .rb-homelink').getAttribute('href')"), './index.html')
            check('  and the message banner under the bar there too', await page.ev(BANNER), [True, 8])
            theme0 = await page.ev("document.documentElement.getAttribute('data-theme')")
            await click('#rbBar .theme-toggle')
            theme1 = await page.ev("document.documentElement.getAttribute('data-theme')")
            check('  the switch switches light and dark', theme1 != theme0 and theme1 in ('light', 'dark'), True)
            await click('#rbBar .theme-toggle')

            early = await page.send('Page.addScriptToEvaluateOnNewDocument', {'source': EARLY})
            await page.send('Page.reload', {})
            await asyncio.sleep(7)
            await page.send('Page.removeScriptToEvaluateOnNewDocument', {'identifier': early['result']['identifier']})
            check('the next visit is in the full window before the page\'s script runs: no header while it loads',
                  await page.ev('window.rbEarly || null'),
                  {'full': True, 'header': 'none', 'barTop': 0, 'corners': ['none', 'inline'], 'pressed': 'false'})
            check('  and once it has run, its button is pressed', (await page.ev(FULL))['pressed'], 'true')
            await click('#rbFull')
            off = await page.ev(FULL)
            check('the button again: the header and footer are back, and remembered so',
                  (off['on'], off['header'], off['footer'], off['mark'], off['key']), (False, 'grid', 'block', False, '0'))

            # --- many files: the boxes wrap, the rest stays on the first row ------
            await load_samples(page, [A, B])
            await asyncio.sleep(2)
            many = await page.ev(MANY % 14, timeout=120)
            tops = await page.ev(TOPS)
            check('sixteen files wrap the boxes onto more rows', tops['rows'] >= 2, True)
            check('  and Open, ∅ ∩ ∪ and the corners stay on the first row, at its top',
                  (tops['open'], tops['trees'], tops['full']), (0, 0, 0))
            await click('#rbFull')
            tops = await page.ev(TOPS)
            check('  and in the full window the kvot mark too, level with the first row',
                  (tops['mark'], tops['open'], tops['full']), (0, 0, 0))
            await click('#rbFull')
            await page.ev(f"(async () => {{ for (const n of {json.dumps(many)}) await removeFile(n); return true; }})()")
            await settle()

            # --- a phone ----------------------------------------------------
            await load_samples(page, [A, B, 'sample-a.h5'])
            await page.ev(r"""(async () => { for (const n of ['third-file-with-a-long-name.h5', 'fourth.h5']) {
              loadedFileBuffers[n] = loadedFileBuffers['sample-a.h5']; const { FS, File } = window.h5wasm;
              const p = '/copy-' + n; FS.writeFile(p, new Uint8Array(loadedFileBuffers[n])); loadedFiles[n] = new File(p, 'r');
              fileStates[n] = true; if (!fileOrder.includes(n)) fileOrder.push(n); }
              await updateTabs(true); })()""")
            await page.send('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 2, 'mobile': True})
            await asyncio.sleep(1.5)
            phone = await page.ev(r"""(() => { const list = document.getElementById('fileTabs'), right = (s) => document.querySelector(s).getBoundingClientRect().right;
              return [list.scrollWidth > list.clientWidth, right('#rbOpen') <= innerWidth, right('#rbFull') <= innerWidth,
                document.documentElement.scrollWidth <= innerWidth + 1, document.querySelectorAll('#fileTabs .file-tab').length]; })()""")
            check('phone: four boxes scroll sideways, Open and the corners in sight, the page no wider than the screen',
                  phone, [True, True, True, True, 4])

            check('no console errors throughout', page.logs[:3], [])
        finally:
            try:
                await page.ev("localStorage.removeItem('kvot.rb.full'); true")
            except Exception:
                pass
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))
            await bws.recv()

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
