#!/usr/bin/env python3
"""The tree's menu: the selection sent to the User Interface for statsmodels
(smui.html), or saved as an HDF5 file (rb-smui.js).

A right-click on a row of the tree selects it, unless it is already part of
the selection, and opens a menu naming the selection: Send to User
Interface for statsmodels, and Save as HDF5…. Both package the selection as
one HDF5 file. A selection with distributions (a pdf attribute) asks first
how many values to draw from each: 1,000, which are the histogram's own
values when it shows them, or more. The rest goes at once.

Checked here, with real mouse and key events (the new tab needs the click):

  * the menu: what it names and offers, its keys, what closes it, a row
    outside the selection selected first and the selection kept otherwise,
    nothing on a right-click beside the rows, only Save in VS Code
  * the question: its words, Escape and Cancel doing nothing, a number of
    one's own (refused unless 2 to 1,000,000), Enter
  * the package, read back with h5py: datasets at their paths with their
    and their groups' attributes, /time made the dimension scale of every
    series, the values drawn under /samples (the right distributions, a
    lookup table's point without one at its value, a raw distribution's
    values left as they are), the histogram's own values at 1,000, the
    root's source and description, a name from what was right-clicked
  * the send: smui.html opens in a tab of its own and makes tables of it
    (a lookup table with its times, the samples side by side, a run's
    realisations a row each); the next send goes to the same tab; a pop-up
    blocker is reported
  * a file read lazily packages as the same file in memory does, and two
    files combined (∩) go under a group each, sharing /time when their times
    are the same, their samples named kd (fx), kd (fx2)
  * a dataset's name holding markup stays text, and an empty group is
    refused with a message
  * smui's receiver (smui-handoff.js), in a frame: it answers only with
    #handoff, only its own origin or the one the hash declares, refuses
    bytes that are not HDF5 and a message without a file, and opens a file
    under a name of one line without a path

The files are built in the page with h5wasm. Start the server and the
browser as in README.md, then

    python3 resources/tests/rb/test-smui.py

Needs h5py and numpy. Exit status is 0 when every check passes.
"""
import asyncio
import base64
import io
import json
import math
import re
import sys
import urllib.parse
import urllib.request

import h5py
import numpy as np
import websockets

from driver import open_page

BASE = 'http://127.0.0.1:8765'
SEND = 'Send to User Interface for statsmodels'
SAVE = 'Save as HDF5…'
ODD = '<img src=x onerror=window.__pwned=1>'

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


def near(label, got, want, tol):
    check(f'{label} ({got:.4g}, expected {want:.4g} ± {tol:.2g})', bool(abs(got - want) <= tol))


# A file as a run and its data file make them: series over /time, a run's
# realisations, parameters with distributions (a lookup table among them, one
# of whose points has none, and a raw one), an empty group and a name holding
# markup. scale multiplies the series, shift moves the times.
BUILD = r"""(async (name, opts) => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = '/smui-test-' + Date.now() + '-' + Math.random().toString(36).slice(2) + '.h5';
  const n = 24, runs = 30, scale = opts.scale || 1, shift = opts.shift || 0;
  const t = Float64Array.from({ length: n }, (_, i) => shift + (i ? Math.pow(10, 5 * i / (n - 1)) : 0));
  const w = new File(path, 'w');
  const put = (g, name, data, shape, attrs = {}) => {
    // ('<d': h5wasm reads '<f8' as '<f', single precision)
    const d = g.create_dataset({ name, data: Float64Array.from(data), shape, dtype: '<d' });
    for (const [k, v] of Object.entries(attrs)) d.create_attribute(k, v);
  };
  try {
    w.create_attribute('Information', 'A file for the tree menu');
    put(w, 'time', t, [n], { unit: 'year' });
    const soil = w.create_group('Soil');
    soil.create_attribute('IndexLists', ['Radionuclides']);
    soil.create_attribute('time_dependent', 'TRUE');
    put(soil, 'Cs-137', Array.from(t, (_, i) => scale * 100 * Math.exp(-i / 5)), [n], { unit: 'Bq' });
    put(soil, 'I-129', Array.from(t, (_, i) => scale * 3 * (1 + i)), [n], { unit: 'Bq' });
    const prob = w.create_group('Prob');
    prob.create_attribute('time_dependent', 'TRUE');
    put(prob, 'Dose', Array.from({ length: n * runs }, (_, k) => scale * 1e-6 * (1 + Math.floor(k / runs)) * (1 + (k % runs) / runs)),
        [n, runs], { unit: 'Sv/year', probabilistic: 'TRUE' });
    const params = w.create_group('params');
    params.create_attribute('description', 'The parameters');
    put(params, 'kd', [0.25], [1], { unit: 'm3/kg', pdf: '{"type": "logn", "gm": 0.25, "gsd": 2}' });
    put(params, 'por', [0.3], [1], { pdf: '{"type": "unif", "a": 0.2, "b": 0.4}' });
    put(params, 'flow', [10, 11, 12], [3], { unit: 'm3/year', index: '0,100,1000',
        pdf: '[{"type": "norm", "mean": 10, "std": 1}, null, {"type": "unif", "a": 11, "b": 13}]' });
    put(params, 'raw', Array.from({ length: 41 }, (_, i) => (i ? 1 + i / 10 : 5)), [41], { pdf: '{"type": "raw", "include_deterministic": true}' });
    w.create_group('empty');
    put(w.create_group('odd'), opts.odd, [2], [1], { pdf: '{"type": "unif", "a": 1, "b": 3}' });
  } finally {
    w.close();
  }
  const bytes = FS.readFile(path).slice();
  FS.unlink(path);
  if (opts.lazy) await ingestHdf5Lazy(new window.File([bytes], name));
  else await ingestHdf5Buffer(name, bytes.buffer);
  await updateTabs(true);
  return !!loadedFiles[name].__lazy;
})"""

# Saves caught instead of downloaded, and a few handles on the page.
SETUP = r"""(() => {
  window.__saved = [];
  window.rbDownload = (buffer, name) => {
    const u8 = new Uint8Array(buffer);
    let s = '';
    for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    window.__saved.push({ name, b64: btoa(s) });
  };
  window.__row = (p, kind) => [...document.querySelectorAll('#tree .tree-item')]
    .find(r => r.getAttribute('data-path') === p && (!kind || r.classList.contains(kind))) || null;
  window.__at = (el) => {
    if (!el) return null;
    el.scrollIntoView({ block: 'center' });
    const r = el.getBoundingClientRect();
    return [r.left + Math.min(40, r.width / 2), r.top + r.height / 2];
  };
  window.__open = async (p) => {
    const row = __row(p, 'group');
    const t = row && row.querySelector('.tree-toggle');
    if (t && t.classList.contains('collapsed')) { t.click(); await new Promise(r => setTimeout(r, 700)); }
    return !!row;
  };
  window.__banner = () => {
    const b = document.getElementById('failureBanner');
    return b && b.classList.contains('show') ? b.querySelector('.failure-banner-text').textContent : null;
  };
  window.__quiet = () => { if (typeof hideFailureBanner === 'function') hideFailureBanner(); };
  return true;
})()"""

MENU = """(() => {
  const m = document.querySelector('.rb-tree-menu');
  if (!m) return null;
  const r = m.getBoundingClientRect();
  return {
    head: m.querySelector('.rb-tree-menu-head').textContent,
    items: [...m.querySelectorAll('button.rb-tree-menu-item')].map(b => b.textContent),
    focus: document.activeElement && m.contains(document.activeElement) ? document.activeElement.textContent : null,
    inView: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight,
    markup: m.querySelectorAll('img, script, iframe').length,
  };
})()"""

DIALOG = """(() => {
  const d = document.querySelector('.rb-sample-ask');
  if (!d) return null;
  return {
    heading: d.querySelector('h3').textContent,
    text: d.querySelector('p').textContent,
    radios: [...d.querySelectorAll('input[type=radio]')].map(r => r.value),
    checked: (d.querySelector('input[type=radio]:checked') || {}).value || null,
    detail: (d.querySelector('.rb-ask-detail') || {}).textContent || null,
    ok: d.querySelector('.url-btn-load').textContent,
    error: d.querySelector('.url-error').textContent,
  };
})()"""

KEYS = {'Escape': 27, 'ArrowDown': 40, 'ArrowUp': 38, 'Home': 36, 'End': 35, 'Enter': 13}


async def mouse(page, kind, x, y, button='left', clicks=1, modifiers=0):
    await page.send('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': button,
                                                 'clickCount': clicks, 'modifiers': modifiers})


async def click(page, xy, button='left', modifiers=0):
    x, y = xy
    await mouse(page, 'mouseMoved', x, y, 'none')
    await mouse(page, 'mousePressed', x, y, button, 1, modifiers)
    await mouse(page, 'mouseReleased', x, y, button, 1, modifiers)


async def key(page, name):
    code = KEYS[name]
    for kind in ('rawKeyDown', 'keyUp'):
        await page.send('Input.dispatchKeyEvent', {'type': kind, 'key': name, 'code': name, 'windowsVirtualKeyCode': code})
    await asyncio.sleep(0.15)


async def row_xy(page, path, kind):
    return await page.ev(f'__at(__row({json.dumps(path)}, {json.dumps(kind)}))')


async def menu_on(page, path, kind, modifiers=0):
    """Right-click a row: the menu it opens, or None."""
    xy = await row_xy(page, path, kind)
    if not xy:
        return None
    await click(page, xy, button='right', modifiers=modifiers)
    await asyncio.sleep(0.3)
    return await page.ev(MENU)


async def choose(page, text):
    xy = await page.ev(f"__at([...document.querySelectorAll('button.rb-tree-menu-item')].find(b => b.textContent === {json.dumps(text)}))")
    await click(page, xy)
    await asyncio.sleep(0.4)


async def press(page, sel):
    await click(page, await page.ev(f'__at(document.querySelector({json.dumps(sel)}))'))
    await asyncio.sleep(0.3)


async def wait_for(page, expr, secs=30):
    for _ in range(secs * 10):
        if await page.ev(expr):
            return True
        await asyncio.sleep(0.1)
    return False


async def saved(page, count, secs=60):
    """The count-th file saved, as (name, h5py.File), or (None, None)."""
    if not await wait_for(page, f'window.__saved.length >= {count}', secs):
        return None, None
    s = await page.ev(f'window.__saved[{count - 1}]')
    return s['name'], h5py.File(io.BytesIO(base64.b64decode(s['b64'])), 'r')


def datasets(f):
    out = []
    f.visititems(lambda name, obj: out.append('/' + name) if isinstance(obj, h5py.Dataset) else None)
    return sorted(out)


def text(v):
    if isinstance(v, bytes):
        return v.decode()
    if isinstance(v, np.ndarray):
        return [text(x) for x in v.tolist()]
    return v


def attrs(obj):
    return {k: text(v) for k, v in obj.attrs.items() if k not in ('DIMENSION_LIST', 'REFERENCE_LIST')}


def scale_of(ds):
    """The path of the dimension scale on a dataset's first dimension."""
    try:
        return ds.dims[0][0].name
    except (IndexError, KeyError, RuntimeError):
        return None


async def browser(bws, method, params, ident=[1000]):
    ident[0] += 1
    await bws.send(json.dumps({'id': ident[0], 'method': method, 'params': params}))
    while True:
        r = json.loads(await bws.recv())
        if r.get('id') == ident[0]:
            return r


def smui_targets():
    lst = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list'))
    return [x for x in lst if x.get('type') == 'page' and '/smui.html' in x.get('url', '')]


async def smui_ev(expr):
    t = smui_targets()
    if not t:
        return None
    async with websockets.connect(t[0]['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as ws:
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                                  'params': {'expression': expr, 'returnByValue': True, 'awaitPromise': True}}))
        while True:
            r = json.loads(await ws.recv())
            if r.get('id') == 1:
                return r.get('result', {}).get('result', {}).get('value')


TABLES = "window.SM && SM.app ? SM.app.tables.map(t => ({ name: t.name, rows: t.nrows, columns: t.columns.map(c => c.name) })) : null"


async def smui_tables(more_than, secs=60):
    got = None
    for _ in range(secs * 2):
        got = await smui_ev(TABLES)
        if got and len(got) > more_than:
            return got
        await asyncio.sleep(0.5)
    return got or []


async def smui_column(table, column):
    return await smui_ev(f"""(() => {{
      const t = SM.app.tables.find(t => t.name === {json.dumps(table)});
      const c = t && t.columns.find(c => c.name === {json.dumps(column)});
      return c ? Array.from(c.values) : null;
    }})()""")


async def menu_and_dialog(page):
    """The menu's keys, what closes it, and the question before a save."""
    print('\nthe menu')
    m = await menu_on(page, '/params', 'group')
    check('a right-click on a group selects it', await page.ev('JSON.stringify(rbSelectionPayload())'), '{"mode":"group","path":"/params"}')
    check('the menu names the group', m and m['head'], 'params (a group)')
    check('the menu offers Send and Save', m and m['items'], [SEND, SAVE])
    check('the first item has the focus', m and m['focus'], SEND)
    check('the menu is in view', m and m['inView'], True)
    await key(page, 'ArrowDown')
    check('ArrowDown moves to Save', (await page.ev(MENU))['focus'], SAVE)
    await key(page, 'ArrowDown')
    check('and on round to Send', (await page.ev(MENU))['focus'], SEND)
    await key(page, 'End')
    check('End goes to the last', (await page.ev(MENU))['focus'], SAVE)
    await key(page, 'Home')
    check('Home to the first', (await page.ev(MENU))['focus'], SEND)
    await key(page, 'Escape')
    check('Escape closes the menu', await page.ev(MENU), None)

    await menu_on(page, '/params', 'group')
    await click(page, [1300, 950])
    await asyncio.sleep(0.2)
    check('a press outside closes it', await page.ev(MENU), None)

    m = await menu_on(page, '/Soil', 'group')
    check('a right-click on a row outside the selection selects that row', await page.ev('JSON.stringify(rbSelectionPayload())'), '{"mode":"group","path":"/Soil"}')
    check('and the menu names it', m and m['head'], 'Soil (a group)')
    await key(page, 'Escape')
    blank = await page.ev("""(() => {
      const tree = document.getElementById('tree').getBoundingClientRect();
      const rows = [...document.querySelectorAll('#tree .tree-item')].map(r => r.getBoundingClientRect().bottom);
      const below = Math.max(...rows);
      return tree.bottom - below > 30 ? [tree.left + 40, (below + tree.bottom) / 2] : null;
    })()""")
    if blank:
        await click(page, blank, button='right')
        await asyncio.sleep(0.3)
        check('a right-click beside the rows opens no menu', await page.ev(MENU), None)
    else:
        check('the tree has room below its rows for the check beside them', False)

    await page.ev('window.KvotVscodeHost = {}')
    m = await menu_on(page, '/params', 'group')
    check('in VS Code the menu only saves', m and m['items'], [SAVE])
    await key(page, 'Escape')
    await page.ev('delete window.KvotVscodeHost')

    print('\nthe question')
    await menu_on(page, '/params', 'group')
    await choose(page, SAVE)
    d = await page.ev(DIALOG)
    check('Save asks how many values', d and d['heading'], 'Values from the distributions')
    check('it says what is selected', d and d['text'],
          "4 datasets with 4 distributions. How many values should be drawn from each? Each distribution's values become a column, a row per value.")
    check('it offers 1,000 to 1,000,000 or another number', d and d['radios'], ['1000', '10000', '100000', '1000000', 'other'])
    check('1,000 is chosen', d and d['checked'], '1000')
    check('which are drawn anew when the histogram does not show them', d and d['detail'], 'drawn anew, as many as the histogram draws')
    check('its button says Save', d and d['ok'], 'Save')
    await key(page, 'Escape')
    check('Escape closes it', await page.ev(DIALOG), None)
    await menu_on(page, '/params', 'group')
    await choose(page, SAVE)
    await press(page, '.rb-sample-ask .url-btn-cancel')
    check('and so does Cancel', await page.ev(DIALOG), None)
    await asyncio.sleep(1)
    check('neither saved anything', await page.ev('window.__saved.length'), 0)

    await menu_on(page, '/params', 'group')
    await choose(page, SAVE)
    await press(page, '.rb-sample-other')
    check('the field chooses Another number', (await page.ev(DIALOG))['checked'], 'other')
    await page.send('Input.insertText', {'text': 'many'})
    await press(page, '.rb-sample-ask .url-btn-load')
    d = await page.ev(DIALOG)
    check('a number that is not one is refused', d and d['error'], 'A whole number from 2 to 1,000,000.')
    await page.ev("document.querySelector('.rb-sample-other').value = ''")
    await press(page, '.rb-sample-other')
    await page.send('Input.insertText', {'text': '1'})
    await key(page, 'Enter')
    check('and so is 1', (await page.ev(DIALOG) or {}).get('error'), 'A whole number from 2 to 1,000,000.')
    await page.ev("document.querySelector('.rb-sample-other').value = ''")
    await press(page, '.rb-sample-other')
    await page.send('Input.insertText', {'text': '2,500'})
    await key(page, 'Enter')
    name, f = await saved(page, 1)
    check('2,500 and Enter save', f is not None)
    if f:
        check('2,500 values drawn from each', [f['samples/kd'].shape, f['samples/flow'].shape], [(2500,), (2500, 3)])


async def packages(page, count):
    """What a save holds. count: the saves so far."""
    print('\nthe package')
    await menu_on(page, '/params', 'group')
    await choose(page, SAVE)
    await press(page, '.rb-sample-choices input[value="10000"]')
    await press(page, '.rb-sample-ask .url-btn-load')
    count += 1
    name, f = await saved(page, count)
    check('10,000 saves', f is not None)
    if not f:
        return count
    check('the file is named after the group', name, 'fx params.h5')
    check('its datasets, and the values drawn from their distributions', datasets(f),
          ['/params/flow', '/params/kd', '/params/por', '/params/raw', '/samples/flow', '/samples/kd', '/samples/por'])
    check("a group's attributes go with it", attrs(f['params']), {'description': 'The parameters'})
    a = attrs(f['params/flow'])
    check('a lookup table keeps its index and distributions, and says what it is',
          [a.get('index'), a.get('lookup_table'), a.get('unit'), json.loads(a.get('pdf', 'null'))[1]], ['0,100,1000', 'true', 'm3/year', None])
    check('values as they are', [f['params/kd'][()].tolist(), f['params/flow'][()].tolist()], [[0.25], [10, 11, 12]])
    check("a raw distribution's values go as they are, not under /samples", f['params/raw'].shape, (41,))
    kd = f['samples/kd'][()]
    a = attrs(f['samples/kd'])
    check('a sample says what it is', {k: a.get(k) for k in ('probabilistic', 'time_dependent', 'unit', 'drawn', 'source_path')},
          {'probabilistic': 'TRUE', 'time_dependent': 'FALSE', 'unit': 'm3/kg', 'drawn': '10000 values drawn from the distribution', 'source_path': '/params/kd'})
    check('and its distribution', json.loads(a.get('pdf', 'null')), {'type': 'logn', 'gm': 0.25, 'gsd': 2})
    check('10,000 values drawn', kd.shape, (10000,))
    lk = np.log(kd)
    near('kd: log-normal, its logs centred on log 0.25', float(lk.mean()), math.log(0.25), 5 * math.log(2) / 100)
    near('with the spread of a geometric sd of 2', float(lk.std()), math.log(2), 0.05 * math.log(2))
    por = f['samples/por'][()]
    check('por: uniform on 0.2 to 0.4', bool(por.min() >= 0.2 and por.max() <= 0.4))
    near('por: mean 0.3', float(por.mean()), 0.3, 5 * 0.2 / math.sqrt(12) / 100)
    flow = f['samples/flow'][()]
    check("a lookup table's sample: a column per point", [flow.shape, attrs(f['samples/flow']).get('columns')],
          [(10000, 3), ['flow t=0', 'flow t=100', 'flow t=1000']])
    near('flow t=0: normal, mean 10', float(flow[:, 0].mean()), 10, 5 / 100)
    near('with sd 1', float(flow[:, 0].std()), 1, 0.05)
    check('the point without a distribution: its value in every row', bool(np.all(flow[:, 1] == 11)))
    check('flow t=1000: uniform on 11 to 13', bool(flow[:, 2].min() >= 11 and flow[:, 2].max() <= 13))
    check('drawn afresh per point', attrs(f['samples/flow']).get('drawn'), '10000 values drawn per point')
    r = attrs(f)
    check('the root says where it came from', r.get('source'), 'the HDF5 Browser (rb.html): fx.h5')
    check('and when, in local time', bool(re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d', r.get('created_time', ''))))
    check('and what the samples are', r.get('description'),
          '4 datasets sent from the HDF5 Browser. Values from the distributions (under /samples): 10,000 per distribution, '
          "independent random draws (Monte Carlo) from each one's pdf attribute, not the realisations of a run.")

    print('\nthe histogram\'s values')
    await click(page, await row_xy(page, '/params/kd', 'dataset'))
    check('kd alone shows its histogram', await wait_for(page, 'currentPdfHistogram && currentPdfHistogramData && currentPdfHistogramData.type === "single"', 10))
    m = await menu_on(page, '/params/kd', 'dataset')
    check('the menu names the dataset', m and m['head'], 'kd')
    await choose(page, SAVE)
    d = await page.ev(DIALOG)
    check('the question for one', d and d['text'],
          "One dataset with a distribution. How many values should be drawn from it? Each distribution's values become a column, a row per value.")
    check('1,000 are the values the histogram shows', d and d['detail'], 'the values the histogram shows')
    await press(page, '.rb-sample-ask .url-btn-load')
    count += 1
    name, f = await saved(page, count)
    shown = await page.ev('Array.from(currentPdfHistogramData.samples, Number)')
    check('the file is named after the dataset', name, 'fx kd.h5')
    check("the sample is the histogram's 1,000 values", f and f['samples/kd'][()].tolist(), shown)
    check('and says so', f and attrs(f['samples/kd']).get('drawn'), 'the 1000 values the histogram shows')
    check('so does the root', bool(f and 'the 1000 the histogram shows where it shows them' in attrs(f).get('description', '')))
    await menu_on(page, '/params/kd', 'dataset')
    await choose(page, SAVE)
    await press(page, '.rb-sample-choices input[value="10000"]')
    await press(page, '.rb-sample-ask .url-btn-load')
    count += 1
    name, f = await saved(page, count)
    kd = f['samples/kd'][()].tolist() if f else []
    check('10,000 are drawn anew', [len(kd), kd[:1000] == shown], [10000, False])

    await click(page, await row_xy(page, '/params/flow', 'dataset'))
    check('the lookup table shows a histogram per point', await wait_for(page, 'currentPdfHistogram && currentPdfHistogramData && currentPdfHistogramData.type === "lookup"', 10))
    entries = await page.ev("currentPdfHistogramData.entries.map(e => ({ point: e.source && e.source.point, samples: Array.from(e.samples, Number) }))")
    await menu_on(page, '/params/flow', 'dataset')
    await choose(page, SAVE)
    check('1,000 are the values the histogram shows, for every point', (await page.ev(DIALOG) or {}).get('detail'), 'the values the histogram shows')
    await press(page, '.rb-sample-ask .url-btn-load')
    count += 1
    name, f = await saved(page, count)
    flow = f['samples/flow'][()] if f else np.zeros((0, 3))
    by_point = {e['point']: e['samples'] for e in entries}
    check("each point's column is its histogram's values", [flow[:, 0].tolist() == by_point.get(0), flow[:, 2].tolist() == by_point.get(2)], [True, True])
    check('and the point without a distribution its value', bool(flow.shape[0] == 1000 and np.all(flow[:, 1] == 11)))

    print('\nseries, realisations, several datasets')
    await menu_on(page, '/Soil', 'group')
    await choose(page, SAVE)
    check('a selection without distributions asks nothing', await page.ev(DIALOG), None)
    count += 1
    name, f = await saved(page, count)
    check('and saves at once', f is not None)
    if f:
        check('named after the group', name, 'fx Soil.h5')
        check('its series and their times', datasets(f), ['/Soil/Cs-137', '/Soil/I-129', '/time'])
        check('/time is a dimension scale', [text(f['time'].attrs.get('CLASS')), text(f['time'].attrs.get('NAME'))], ['DIMENSION_SCALE', 'time'])
        check('the series are on it', [scale_of(f['Soil/Cs-137']), scale_of(f['Soil/I-129'])], ['/time', '/time'])
        check("the group's attributes", attrs(f['Soil']), {'IndexLists': ['Radionuclides'], 'time_dependent': 'TRUE'})
        check('the values', f['Soil/Cs-137'][()].tolist()[:3], [100 * math.exp(-i / 5) for i in range(3)])
        check('no samples, and no word of them', ['samples' in f, 'Monte Carlo' in attrs(f).get('description', '')], [False, False])
    await menu_on(page, '/Prob', 'group')
    await choose(page, SAVE)
    count += 1
    name, f = await saved(page, count)
    if f:
        check("a run's realisations, on /time", [f['Prob/Dose'].shape, scale_of(f['Prob/Dose']), attrs(f['Prob/Dose']).get('probabilistic')],
              [(24, 30), '/time', 'TRUE'])

    await click(page, await row_xy(page, '/params/kd', 'dataset'))
    await asyncio.sleep(0.5)
    await click(page, await row_xy(page, '/params/por', 'dataset'), modifiers=4)
    await asyncio.sleep(0.8)
    m = await menu_on(page, '/params/kd', 'dataset')
    check('a right-click in a multi-selection keeps it', m and m['head'], '2 datasets')
    await choose(page, SAVE)
    check('the question counts them', (await page.ev(DIALOG) or {}).get('text', '').split('.')[0], '2 datasets with 2 distributions')
    await press(page, '.rb-sample-ask .url-btn-load')
    count += 1
    name, f = await saved(page, count)
    check('both go, with their samples', f and datasets(f), ['/params/kd', '/params/por', '/samples/kd', '/samples/por'])
    check('under the name selection', name, 'fx selection.h5')

    print('\nnames and nothing')
    await page.ev('__open("/odd")')
    m = await menu_on(page, f'/odd/{ODD}', 'dataset')
    check('a name holding markup is shown as text', [m and m['head'], m and m['markup']], [ODD, 0])
    await choose(page, SAVE)
    await press(page, '.rb-sample-ask .url-btn-load')
    count += 1
    name, f = await saved(page, count)
    check('and packaged under its own name', f and datasets(f), [f'/odd/{ODD}', f'/samples/{ODD}'])
    check('nothing in it ran', await page.ev('window.__pwned === undefined'), True)
    await page.ev('__quiet()')
    await menu_on(page, '/empty', 'group')
    await choose(page, SAVE)
    await asyncio.sleep(0.5)
    check('an empty group is refused with a message', await page.ev('__banner()'), 'There is no dataset in the selection to send.')
    check('and nothing is saved', await page.ev('window.__saved.length'), count)
    return count


async def whole_file(page, count):
    """The whole file saved: (dataset paths, the values of those not drawn)."""
    m = await menu_on(page, '/', 'group')
    if not m:
        return None
    check('the root row names the whole file', m['head'], 'the whole file')
    await choose(page, SAVE)
    d = await page.ev(DIALOG)
    check('the question counts the whole file', d and d['text'].split('.')[0], '9 datasets with 5 distributions')
    await press(page, '.rb-sample-ask .url-btn-load')
    name, f = await saved(page, count + 1)
    if not f:
        return None
    paths = datasets(f)
    values = {p: f[p][()].tolist() for p in paths if not p.startswith('/samples/')}
    shapes = {p: f[p].shape for p in paths}
    scales = {p: scale_of(f[p]) for p in paths if p in ('/Soil/Cs-137', '/Prob/Dose')}
    return name, paths, values, shapes, scales


async def sends(page):
    """The selection sent to smui.html: tables, one tab, a pop-up blocker."""
    print('\nsent to the User Interface for statsmodels')
    await page.ev('__quiet()')
    await menu_on(page, '/params', 'group')
    await choose(page, SEND)
    check("Send's question says Send", (await page.ev(DIALOG) or {}).get('ok'), 'Send')
    await press(page, '.rb-sample-ask .url-btn-load')
    tables = await smui_tables(0)
    check('smui opens in a tab of its own, told who sends', [t['url'].split('/')[-1] for t in smui_targets()],
          ['smui.html#handoff=http%3A%2F%2F127.0.0.1%3A8765'])
    check('and makes tables of what it is sent', [t['name'] for t in tables],
          ['fx params — flow', 'fx params — values', 'fx params — raw', 'fx params — samples'])
    by = {t['name']: t for t in tables}
    s = by.get('fx params — samples', {})
    check('the samples side by side, a row per value', [s.get('rows'), s.get('columns')], [1000, ['kd', 'por', 'flow t=0', 'flow t=100', 'flow t=1000']])
    check('a lookup table with its times', [by.get('fx params — flow', {}).get('columns'), await smui_column('fx params — flow', 'time')],
          [['time', 'flow'], [0, 100, 1000]])
    check('the values, with their distributions', by.get('fx params — values', {}).get('columns'), ['Name', 'Value', 'Unit', 'Distribution'])
    kd = await smui_column('fx params — samples', 'kd')
    check('drawn from the distribution', bool(kd and len(kd) == 1000 and min(kd) > 0))
    check('rb says it went', await wait_for(page, "__banner() === 'Sent to the User Interface for statsmodels: 4 tables.'", 10))

    await menu_on(page, '/Soil', 'group')
    await choose(page, SEND)
    check('a send without distributions asks nothing', await page.ev(DIALOG), None)
    tables = await smui_tables(4)
    check('the next send goes to the same tab', len(smui_targets()), 1)
    check('and adds its series there, times first', [(t['name'], t['rows'], t['columns']) for t in tables[4:]],
          [('fx Soil', 24, ['time', 'Cs-137', 'I-129'])])
    check('rb names the table', await wait_for(page, "__banner() === 'Sent to the User Interface for statsmodels: fx Soil.'", 10))

    await menu_on(page, '/Prob', 'group')
    await choose(page, SEND)
    tables = await smui_tables(5)
    check("a run's realisations come a row each, a column per time", [(t['name'], t['rows'], t['columns'][0], t['columns'][-1]) for t in tables[5:]],
          [('fx Prob', 30, 'Dose t=0', 'Dose t=100000')])

    await page.ev('__quiet(); window.__realOpen = window.open; window.open = () => null')
    await menu_on(page, '/Soil', 'group')
    await choose(page, SEND)
    await asyncio.sleep(0.5)
    check('a blocked pop-up is reported', await page.ev('__banner()'),
          'The browser did not let this page open a new tab: allow pop-ups for this site, then send again.')
    await page.ev('window.open = window.__realOpen')
    # (the smui tab came to the front: a page behind it draws no frames)
    await page.send('Page.bringToFront')


async def lazily(bws, memory):
    """The same file read lazily packages as it does in memory."""
    print('\na file read lazily')
    tid, page = await open_page(bws, f'{BASE}/rb.html', settle=4)
    try:
        await page.ev(SETUP)
        lazy = await page.ev(f'({BUILD})("fx.h5", {json.dumps({"lazy": True, "odd": ODD})})')
        check('the file is read lazily', lazy, True)
        await asyncio.sleep(1)
        await page.ev('__open("/")')
        check('/Soil is not read yet', await page.ev("!lazyStateOf(loadedFiles['fx.h5']).groups.has('/Soil')"), True)
        await menu_on(page, '/Soil', 'group')
        await choose(page, SAVE)
        name, f = await saved(page, 1)
        check('a group not read yet saves at once, read first', f and datasets(f), ['/Soil/Cs-137', '/Soil/I-129', '/time'])
        check('with its values', f and f['Soil/Cs-137'][()].tolist(), memory and memory[2].get('/Soil/Cs-137'))
        got = await whole_file(page, 1)
        if got and memory:
            check('the whole file: the datasets the file in memory gives', got[1], memory[1])
            check('the same values', got[2] == memory[2], True)
            check('the same shapes', got[3] == memory[3], True)
            check('on the same scales', got[4], memory[4])
        check('nothing was read before it was fetched', [x for x in page.logs if 'before it was loaded' in x[1]], [])
    finally:
        await browser(bws, 'Target.closeTarget', {'targetId': tid})


async def two_files(page, count):
    """Files combined: a group each, /time shared when the times are the same."""
    print('\ntwo files combined')
    await page.ev(f'({BUILD})("fx2.h5", {json.dumps({"scale": 2, "odd": ODD})})')
    await page.ev("document.querySelector('#treeModeContainer button[data-value=\"intersect\"]').click()")
    await asyncio.sleep(3)
    await page.ev('__open("/")')
    m = await menu_on(page, '/Soil', 'group')
    check('a group of two files is one row', m and m['head'], 'Soil (a group)')
    await choose(page, SAVE)
    count += 1
    name, f = await saved(page, count)
    if f:
        check('named after the group and its files', name, 'Soil (fx and 1 more).h5')
        check('a group per file, one /time for times that are the same', datasets(f),
              ['/fx.h5/Soil/Cs-137', '/fx.h5/Soil/I-129', '/fx2.h5/Soil/Cs-137', '/fx2.h5/Soil/I-129', '/time'])
        check('every series on it', sorted({scale_of(f[p]) for p in datasets(f) if p != '/time'}), ['/time'])
        check("each file's values", f['fx2.h5/Soil/Cs-137'][0] / f['fx.h5/Soil/Cs-137'][0], 2.0)
        check("a file's group says which file", attrs(f['fx.h5']), {'file': 'fx.h5'})
    await page.ev('__open("/params")')
    await menu_on(page, '/params', 'group')
    await choose(page, SAVE)
    await press(page, '.rb-sample-ask .url-btn-load')
    count += 1
    name, f = await saved(page, count)
    if f:
        check("the same sample from two files: named by file", sorted(f['samples'].keys()),
              ['flow (fx)', 'flow (fx2)', 'kd (fx)', 'kd (fx2)', 'por (fx)', 'por (fx2)'])
        check('its columns too', attrs(f['samples/flow (fx2)']).get('columns'), ['flow (fx2) t=0', 'flow (fx2) t=100', 'flow (fx2) t=1000'])
        check('and it says which file', attrs(f['samples/kd (fx2)']).get('source_file'), 'fx2.h5')

    await page.ev(f"""(async () => {{
      fileStates['fx2.h5'] = false;
      await ({BUILD})('fx3.h5', {json.dumps({"shift": 0.5, "odd": ODD})});
      await updateTabs(true);
    }})()""")
    # (one file was enabled for a moment: the tree went back to separate files)
    await page.ev("document.querySelector('#treeModeContainer button[data-value=\"intersect\"]').click()")
    await asyncio.sleep(3)
    await page.ev('__open("/")')
    await menu_on(page, '/Soil', 'group')
    await choose(page, SAVE)
    count += 1
    name, f = await saved(page, count)
    if f:
        check('other times: a /time of its own', datasets(f),
              ['/fx.h5/Soil/Cs-137', '/fx.h5/Soil/I-129', '/fx3.h5/Soil/Cs-137', '/fx3.h5/Soil/I-129', '/fx3.h5/time', '/time'])
        if '/fx3.h5/time' in f:
            check("each file's series on its own times",
                  [scale_of(f['fx.h5/Soil/Cs-137']), scale_of(f['fx3.h5/Soil/Cs-137'])], ['/time', '/fx3.h5/time'])
            check('which are its times', f['fx3.h5/time'][0], 0.5)
    return count


# smui.html in a frame, sent a message: what it answers, what it opens.
RECEIVER = r"""(async (src, message, sameOrigin) => {
  // (the demo page loads h5wasm, pinned as rb.html pins it)
  for (let i = 0; i < 100 && !window.h5wasm; i++) await new Promise(r => setTimeout(r, 100));
  if (window.h5wasm.ready instanceof Promise) await window.h5wasm.ready;
  const f = document.createElement('iframe');
  f.style.cssText = 'position: fixed; left: 0; top: 0; width: 900px; height: 600px';
  f.src = src;
  const heard = [];
  const listen = (e) => { if (e.source === f.contentWindow && e.data) heard.push(e.data); };
  window.addEventListener('message', listen);
  document.body.appendChild(f);
  await new Promise(r => f.addEventListener('load', r));
  await new Promise(r => setTimeout(r, 2500));
  const w = f.contentWindow;
  let buffer = null;
  if (message.bytes === 'hdf5') {
    const { FS, File } = window.h5wasm;
    const path = '/receiver-' + Date.now() + '.h5';
    const h = new File(path, 'w');
    h.create_dataset({ name: 'x', data: Float64Array.of(1, 2, 3), shape: [3], dtype: '<d' });
    h.close();
    buffer = FS.readFile(path).slice().buffer;
    FS.unlink(path);
  } else if (message.bytes === 'text') buffer = new TextEncoder().encode('not an hdf5 file at all').buffer;
  const target = sameOrigin ? location.origin : '*';
  if (message.kind === 'smui-open') w.postMessage({ kvot: 'smui-open', name: message.name, buffer: buffer || 'no file' }, target, buffer ? [buffer] : []);
  else w.postMessage({ kvot: message.kind }, target);
  for (let i = 0; i < 60 && !heard.some(d => d.kvot !== 'smui-ready' || message.kind === 'smui-ping'); i++) await new Promise(r => setTimeout(r, 100));
  await new Promise(r => setTimeout(r, 300));
  const out = { heard: heard.map(d => d.kvot + (d.tables ? ': ' + d.tables.join(', ') : '') + (d.message ? ': ' + d.message : '')) };
  if (sameOrigin) out.tables = w.SM && w.SM.app ? w.SM.app.tables.map(t => t.name) : null;
  window.removeEventListener('message', listen);
  f.remove();
  return out;
})"""


async def receiver(bws):
    """smui-handoff.js: what smui.html takes, and from whom."""
    print("\nsmui's receiver")
    tid, page = await open_page(bws, f'{BASE}/resources/tests/rb/handoff-demo.html', settle=2)
    try:
        mine = f'{BASE}/smui.html#handoff=' + urllib.parse.quote(BASE, safe='')

        async def ask(src, message, same=True):
            return await page.ev(f'({RECEIVER})({json.dumps(src)}, {json.dumps(message)}, {json.dumps(same)})', timeout=60)

        got = await ask(mine, {'kind': 'smui-ping'})
        check('with #handoff it answers a ping', got['heard'], ['smui-ready'])
        got = await ask(mine, {'kind': 'smui-open', 'name': 'junk.h5', 'bytes': 'text'})
        check('bytes that are not HDF5 are refused, and nothing opens',
              [got['heard'], got['tables']], [['smui-error: not an HDF5 file: it does not start with the HDF5 signature'], []])
        got = await ask(mine, {'kind': 'smui-open', 'name': 'nothing.h5'})
        check('a message without a file is refused', got['heard'], ['smui-error: no file in the message'])
        got = await ask(mine, {'kind': 'smui-open', 'name': '../../etc/x\u2028y', 'bytes': 'hdf5'})
        check('a file opens, under a name of one line without a path', [got['heard'], got['tables']],
              [['smui-opened: .._.._etc_x y'], ['.._.._etc_x y']])
        got = await ask(f'{BASE}/smui.html', {'kind': 'smui-open', 'name': 'sneaky.h5', 'bytes': 'hdf5'})
        check('without #handoff it takes nothing', got, {'heard': [], 'tables': []})
        got = await ask(f'{BASE}/smui.html#handoff=' + urllib.parse.quote('http://localhost:8080', safe=''), {'kind': 'smui-ping'})
        check('nor from an origin other than the one it was told', got['heard'], [])
    finally:
        await browser(bws, 'Target.closeTarget', {'targetId': tid})
    # another origin: the same server as localhost. Its own smui answers it
    # (so the origin works), the one at 127.0.0.1 does not
    other = BASE.replace('127.0.0.1', 'localhost')
    tid, page = await open_page(bws, f'{other}/resources/tests/rb/handoff-demo.html', settle=2)
    try:
        async def ask(src, message, same=True):
            return await page.ev(f'({RECEIVER})({json.dumps(src)}, {json.dumps(message)}, {json.dumps(same)})', timeout=60)
        got = await ask(f'{other}/smui.html#handoff=' + urllib.parse.quote(other, safe=''), {'kind': 'smui-ping'})
        check('a page at localhost: its own smui answers it', got['heard'], ['smui-ready'])
        got = await ask(f'{BASE}/smui.html#handoff=' + urllib.parse.quote(BASE, safe=''), {'kind': 'smui-ping'}, same=False)
        check('smui at 127.0.0.1 does not', got['heard'], [])
    finally:
        await browser(bws, 'Target.closeTarget', {'targetId': tid})


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        for t in smui_targets():          # a tab an earlier run left
            await browser(bws, 'Target.closeTarget', {'targetId': t['id']})
        tid, page = await open_page(bws, f'{BASE}/rb.html', settle=4)
        try:
            check('the welcome says what a right-click in the tree does', await page.ev(
                "[...document.querySelectorAll('.welcome-section li')].some(li => /^Right-click in the tree to send the selection to the User Interface for statsmodels/.test(li.textContent))"))
            await page.ev(SETUP)
            await page.ev(f'({BUILD})("fx.h5", {json.dumps({"odd": ODD})})')
            await asyncio.sleep(1)
            for p in ('/', '/params'):
                await page.ev(f'__open({json.dumps(p)})')
            await menu_and_dialog(page)
            count = await packages(page, 1)
            memory = await whole_file(page, count)
            count += 1
            await sends(page)
            count = await two_files(page, count)
        finally:
            for t in smui_targets():
                await browser(bws, 'Target.closeTarget', {'targetId': t['id']})
        logs = [x for x in page.logs if x[0] in ('error', 'exception')]
        check('no errors in the page', logs, [])
        await browser(bws, 'Target.closeTarget', {'targetId': tid})
        await lazily(bws, memory)
        await receiver(bws)

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    sys.exit(1 if failures else 0)


asyncio.run(main())
