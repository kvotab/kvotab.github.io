#!/usr/bin/env python3
"""An axis's unit with a prefix: kBq on the axis, its values divided by 1000.

Beside each axis's lin/log is a select of SI prefixes (changeAxisPrefix in
rb-chart-axes.js). What is drawn is put in the prefixed unit -- the traces,
the background's segments, the ranges -- while what the page keeps stays in
the file's units: a trace's _fileX and _fileY, a preset's limits, the lock's.
This checks:

  the unit as written: kBq; mSv/year with k is Sv/year; m3/year with k is
  10³ m3/year, since km3 would be 10⁹ m3; no unit is 10³ alone;
  a change of prefix redraws the chart in place over the same stretch of
  data, its values the file's digits moved, not multiplied: a range set by
  hand moves with it, a log axis on auto range stays on it, the background's
  phases stay where they are in time and are named so, Show Max's numbers
  are the axis's, and the preset selected stays so;
  a chart drawn afterwards is drawn in the prefix, and so is a band a toggle
  adds later; several groups' panels each take it, in their own units;
  presets keep their limits in the file's units and may carry a prefix:
  saving one, choosing it, choosing one without (it keeps the chart's), the
  manager's summaries, its edit form (another prefix moves the numbers typed
  to the same limits), the Current view editor, and an imported preset whose
  prefix is not one of the page's;
  the axes lock keeps the prefix and disables its select;
  the CSV holds the file's values, the Excel workbook the axis's, under the
  prefixed unit and with a note saying so, and the Python script divides its
  labels (test-python.py runs such scripts);
  a click on the select is the select's: the label's own control is lin.

The files are built in the page with h5wasm, as test-axes.py and
test-groups.py build theirs. The pointer is driven with real CDP mouse events.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-prefix.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import io
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal

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


def shifted(v, e):
    """v as the page puts it in units of 10^e: its shortest digits, moved -e places."""
    return None if v is None else float(Decimal(repr(float(v))).scaleb(-e))


def all_shifted(display, file_values, e):
    return len(display) == len(file_values) and all(d == shifted(f, e) for d, f in zip(display, file_values))


# overlay.h5, as test-axes.py builds it: time 0, then 10 .. 1e5 years, two
# datasets in Bq/year and a background (Submerged 0-1000, Shore 1000-10000,
# Terrestrial 10000-100000). groups.h5, as test-groups.py builds it: areaA and
# areaB in Bq, areaB with three realisations, and dose in Sv/year.
BUILD = r"""(async () => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const load = async (name, build) => {
    const path = '/' + name.replace('.h5', '') + '-' + Date.now() + '.h5';
    const w = new File(path, 'w');
    try { build(w); } finally { w.close(); }
    loadedFileBuffers[name] = FS.readFile(path).slice().buffer;
    loadedFiles[name] = new File(path, 'r');
    fileStates[name] = true;
    if (!fileOrder.includes(name)) fileOrder.push(name);
  };
  await load('overlay.h5', (w) => {
    const n = 60;
    const t = Float64Array.from({ length: n }, (_, i) => i === 0 ? 0 : Math.pow(10, 1 + 4 * (i - 1) / (n - 2)));
    w.create_dataset({ name: 'time', data: t, shape: [n], dtype: '<f8' }).create_attribute('unit', 'years');
    const g = w.create_group('geosphere').create_group('near_field');
    for (const [name, fn] of [['flux', Math.sin], ['flux2', Math.cos]]) {
      const d = g.create_dataset({ name, data: Float64Array.from(t, (_, i) => fn(i / 5) + 2), shape: [n], dtype: '<f8' });
      d.create_attribute('unit', 'Bq/year');
      d.create_attribute('time_dependent', 'True');
    }
    g.create_dataset({ name: '_phase', data: Float64Array.from([1000, 10000, 100000]), shape: [3], dtype: '<f8' })
      .create_attribute('Index', '["Submerged","Shore","Terrestrial"]');
  });
  await load('groups.h5', (w) => {
    const n = 12;
    const t = Float64Array.from({ length: n }, (_, i) => Math.pow(10, 4 * i / (n - 1)));
    const put = (g, name, data, shape, attrs) => {
      const d = g.create_dataset({ name, data: Float64Array.from(data), shape, dtype: '<f8' });
      for (const [k, v] of Object.entries(attrs)) d.create_attribute(k, v);
    };
    const nuclides = (g, unit, scale, runs) => {
      g.create_attribute('IndexLists', ['Radionuclides']);
      g.create_attribute('time_dependent', 'TRUE');
      g.create_attribute('unit', unit);
      for (const [nuc, f] of [['Cs-137', 1], ['I-129', 0.3]]) {
        const series = Array.from(t, v => scale * f * v / 1e4);
        if (runs) put(g, nuc, series.flatMap(v => [0.5 * v, v, 2 * v]), [n, 3],
                      { unit, time_dependent: 'TRUE', probabilistic: 'TRUE', n_iter: 3 });
        else put(g, nuc, series, [n], { unit, time_dependent: 'TRUE' });
      }
    };
    w.create_attribute('n_iter', 3);
    put(w, 'time', t, [n], { unit: 'years' });
    const bio = w.create_group('bio');
    nuclides(bio.create_group('areaA'), 'Bq', 100, false);
    nuclides(bio.create_group('areaB'), 'Bq', 10, true);
    nuclides(w.create_group('dose'), 'Sv/year', 1e-6, false);
  });
  await updateTabs(true);
  return fileOrder.slice();
})()"""

HELPERS = r"""(() => {
  window.__notes = [];
  window.notifyUser = (m) => { window.__notes.push(String(m)); };
  // The page's own dialogs; test-ask.py drives those.
  window.rbAskConfirm = async () => true;
  window.rbAskText = async () => window.__askText || null;
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__only = async (...names) => {
    for (const n of fileOrder) fileStates[n] = names.includes(n);
    await updateTabs(true);
    await __wait(1200);
  };
  window.__pick = async (file, path, { group = false, ctrl = false } = {}) => {
    await expandAndLoadPath(file, path);
    const row = findTreeItem(path, { extra: group ? '.group' : '.dataset' });
    if (!row) throw new Error('no row for ' + path);
    row.dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: ctrl, metaKey: ctrl }));
    await __wait(2500);
  };
  // A prefix chosen as a reader chooses it: the select, and its change.
  window.__prefix = async (axis, p) => {
    const s = document.getElementById(axis + 'PrefixSelect');
    s.value = p;
    s.dispatchEvent(new Event('change', { bubbles: true }));
    await _axisUnitsQueue;
    await __wait(400);
  };
  window.__scale = async (axis, value) => {
    const b = document.querySelector(`#${axis}ScaleToggle button[data-value=${value}]`);
    if (!b.classList.contains('active')) b.click();
    await __wait(1200);
  };
  window.__tick = async (id, on) => {
    const cb = document.getElementById(id);
    if (!!cb.checked !== on) { cb.checked = on; cb.dispatchEvent(new Event('change', { bubbles: true })); }
    await __wait(1500);
  };
  window.__choose = (id) => {
    const sel = document.getElementById('presetSelect');
    sel.value = id;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return __wait(900);
  };
  window.__zoomY = async (lo, hi) => {
    await Plotly.relayout(document.getElementById('plotlyChart'), { 'yaxis.range': [lo, hi] });
    await __wait(500);
  };
  window.__background = async (on) => {
    const sel = document.getElementById('backgroundSourceSelect');
    sel.value = on ? [...sel.options].map(o => o.value).find(v => v.endsWith('_phase')) : '__none__';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    await __wait(1800);
  };
  window.__row = (id) => [...document.querySelectorAll('#presetManagerList .preset-manager-row')]
    .find(r => r.dataset.presetId === id);
  window.__btn = (id, label) => [...__row(id).querySelectorAll('button')].find(b => b.textContent === label);
  window.__set = (fields) => { for (const [k, v] of Object.entries(fields)) document.getElementById('pe_' + k).value = v; };
  window.__form = () => {
    const v = (id) => (document.getElementById(id) || {}).value;
    return { xPrefix: v('pe_xPrefix'), yPrefix: v('pe_yPrefix'), xMin: v('pe_xMin'), xMax: v('pe_xMax'),
             yMin: v('pe_yMin'), yMax: v('pe_yMax'),
             options: [...document.getElementById('pe_yPrefix').options].map(o => o.value) };
  };
  window.__formPrefix = (axis, p) => {
    const s = document.getElementById('pe_' + axis + 'Prefix');
    s.value = p;
    s.dispatchEvent(new Event('change'));
    return __form();
  };
  window.__state = () => {
    const pd = document.getElementById('plotlyChart');
    const fl = pd._fullLayout;
    const axes = Object.fromEntries(Object.keys(fl).filter(k => /^[xy]axis\d*$/.test(k)).sort().map(k => [k, {
      type: fl[k].type, range: (fl[k].range || []).map(Number), auto: fl[k].autorange,
      title: (fl[k].title && fl[k].title.text) || '' }]));
    const list = (a) => (a ? Array.from(a, v => (v === null || v === undefined ? null : Number(v))) : null);
    return {
      axes,
      exp: chartExponents(),
      selects: { x: xPrefixSelect.value, y: yPrefixSelect.value },
      disabled: { x: xPrefixSelect.disabled, y: yPrefixSelect.disabled },
      sel: presetSelect.value,
      autoLogY: isAutoLogY(pd),
      traces: pd.data.map(t => ({
        name: t.name, x: list(t.x), y: list(t.y), fileX: list(t._fileX), fileY: list(t._fileY),
        band: !!(t._isCIBand || t._isSDOMBand),
        maxText: (() => { const m = (t.y || []).reduce((a, v) => (v > a ? v : a), -Infinity); return isFinite(m) ? m.toPrecision(3) : null; })()
      })),
      shapes: (pd.layout.shapes || []).map(s => [s.x0, s.x1]),
      notes: __notes.slice(),
      rows: [...document.querySelectorAll('#presetManagerList .preset-manager-row')].map(r => ({
        id: r.dataset.presetId, summary: r.querySelector('.preset-manager-summary').textContent }))
    };
  };
  // The workbook, caught instead of downloaded (as test-excel.py catches it).
  XlsxWriter.prototype.saveAs = async function (name) {
    const blob = await this.save();
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let s = '';
    for (let i = 0; i < bytes.length; i += 32768) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
    window.__xl = { name, b64: btoa(s) };
  };
  window.__export = async () => {
    window.__xl = null;
    await downloadChartDataAsExcel();
    for (let i = 0; i < 50 && !window.__xl; i++) await __wait(100);
    return window.__xl;
  };
  // The CSV, caught as the blob it is downloaded as.
  window.__csv = async () => {
    let blob = null;
    const create = URL.createObjectURL;
    const click = HTMLAnchorElement.prototype.click;
    URL.createObjectURL = (b) => { blob = b; return 'blob:none'; };
    HTMLAnchorElement.prototype.click = function () {};
    try { downloadChartData(); } finally { URL.createObjectURL = create; HTMLAnchorElement.prototype.click = click; }
    return blob ? await blob.text() : null;
  };
  return true;
})()"""

# Where `years` is on screen, in whatever unit the time axis is in, if it is on the axis at all.
WHERE = """((years) => {
  const pd = document.getElementById('plotlyChart');
  const xa = pd._fullLayout.xaxis, ya = pd._fullLayout.yaxis;
  const x = shiftDecimal(years, -chartExponents().x);
  const r = pd.getBoundingClientRect();
  const lin = xa.type === 'log' ? Math.log10(x) : x;
  if (lin < Math.min(...xa.range) || lin > Math.max(...xa.range)) return null;
  return [r.left + xa._offset + xa.l2p(lin), r.top + ya._offset + ya._length / 2];
})(%s)"""

TIP = """(() => {
  const t = document.getElementById('backgroundOverlayTooltip');
  return t && t.style.display !== 'none' ? t.textContent : null;
})()"""

PHASES = [(30, 'Submerged'), (999, 'Submerged'), (1500, 'Shore'),
          (5000, 'Shore'), (20000, 'Terrestrial'), (60000, 'Terrestrial')]

NS = {
    'm': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'pr': 'http://schemas.openxmlformats.org/package/2006/relationships',
}


def workbook(b64):
    """The cells of each sheet, {sheet: {ref: value}}, and every chart part's text."""
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(b64)))
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    target = {r.get('Id'): r.get('Target') for r in rels.findall('pr:Relationship', NS)}
    strings = [''.join(t.text or '' for t in si.iter(f"{{{NS['m']}}}t"))
               for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS)]
    cells = {}
    for s in wb.find('m:sheets', NS).findall('m:sheet', NS):
        root = ET.fromstring(z.read('xl/' + target[s.get(f"{{{NS['r']}}}id")]))
        cells[s.get('name')] = {c.get('r'): (strings[int(c.find('m:v', NS).text)] if c.get('t') == 's'
                                             else float(c.find('m:v', NS).text))
                                for c in root.iter(f"{{{NS['m']}}}c") if c.find('m:v', NS) is not None}
    charts = ' '.join(z.read(n).decode('utf-8') for n in z.namelist() if re.fullmatch(r'xl/charts/chart\d+\.xml', n))
    return cells, charts


async def move(page, x, y):
    await page.send('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y})


async def tooltip_at(page, years):
    at = await page.ev(WHERE % json.dumps(years))
    if at is None:
        return 'off the axis'
    await move(page, at[0] - 4, at[1])
    await move(page, at[0], at[1])
    await asyncio.sleep(0.05)
    return await page.ev(TIP)


async def phases_named(page, label):
    named = {x: await tooltip_at(page, x) for x, _ in PHASES}
    check(f'{label}: every phase named where it is in time', named, {x: want for x, want in PHASES})


async def st(page):
    return await page.ev('__state()')


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        # The presets live in the browser profile, which every test here
        # shares; this one adds some, and puts back what it found.
        stored = await page.ev("localStorage.getItem('chartPresets')")
        try:
            await page.ev("localStorage.removeItem('chartPresets'); populatePresetDropdown(); true")
            check('files built and loaded', await page.ev(BUILD, timeout=120), ['overlay.h5', 'groups.h5'])
            await page.ev(HELPERS)

            # --- the unit as written ------------------------------------------
            units = await page.ev("""[['Bq', 3], ['Bq/year', -6], ['mSv/year', 3], ['m3/year', 3], ['years', 3],
                                      ['', -6], ['pH', 3], ['kg', 3], ['µSv/h', 3], ['Bq', 0]].map(([u, e]) => unitWithPrefix(u, e))""")
            check('units with a prefix: kBq, µBq/year, Sv/year from mSv/year, 10³ m3/year, kyears, 10⁻⁶ alone, '
                  '10³ pH, Mg from kg, mSv/h from µSv/h, and Bq as it was',
                  units, ['kBq', 'µBq/year', 'Sv/year', '10³ m3/year', 'kyears', '10⁻⁶', '10³ pH', 'Mg', 'mSv/h', 'Bq'])

            # --- a dataset, its prefixes changed in place ----------------------
            await page.ev("(async () => { await __only('overlay.h5'); await __pick('overlay.h5', '/geosphere/near_field/flux'); })()",
                          timeout=120)
            s0 = await st(page)
            check('drawn with no prefix: the units the file says',
                  (s0['axes']['xaxis']['title'], s0['axes']['yaxis']['title']), ('Time (years)', 'Value (Bq/year)'))
            check('  and its traces as they were, with nothing kept beside them', (s0['traces'][0]['fileX'], s0['exp']),
                  (None, {'x': 0, 'y': 0}))
            flux = s0['traces'][0]
            await page.ev('__zoomY(1.5, 2.5)')
            check('a zoom by hand on y: Custom', (await st(page))['sel'], '__custom__')

            await page.ev("__prefix('y', 'm')")
            s = await st(page)
            t = s['traces'][0]
            check('y in m: the title says mBq/year', s['axes']['yaxis']['title'], 'Value (mBq/year)')
            check('  its values are the file\'s, their digits moved three places', all_shifted(t['y'], flux['y'], -3), True)
            check('  which it keeps as they were', t['fileY'], flux['y'])
            check('  the range set by hand shows the same stretch: 1500 to 2500', s['axes']['yaxis']['range'], [1500, 2500])
            check('  the time axis is as it was', (s['axes']['xaxis']['title'], t['x']), ('Time (years)', flux['x']))
            check('  and the dropdown still says Custom', s['sel'], '__custom__')

            await page.ev('__background(true)')
            await phases_named(page, 'the background, no prefix on x')
            await page.ev("__prefix('x', 'k')")
            s = await st(page)
            check('x in k: Time (kyears)', s['axes']['xaxis']['title'], 'Time (kyears)')
            check('  its values the file\'s in thousands', all_shifted(s['traces'][0]['x'], flux['x'], 3), True)
            check('  the background\'s first phase drawn from 0 to 1 kyears', s['shapes'][:1], [[0, 1]])
            check('  y as it was: still in m, over 1500 to 2500',
                  (s['axes']['yaxis']['title'], s['axes']['yaxis']['range']), ('Value (mBq/year)', [1500, 2500]))
            await phases_named(page, 'x in kyears')
            await page.ev("__scale('x', 'log')")
            s = await st(page)
            check('log x in kyears: the first phase clamped above zero, the axis not dragged to 1e-9',
                  (s['shapes'][0][0] > 0, s['axes']['xaxis']['range'][0] > -3), (True, True))
            await phases_named(page, 'log x in kyears')
            await page.ev("__scale('x', 'linear')")

            await page.ev("__tick('showMax', true)")
            s = await st(page)
            t = s['traces'][0]
            check('Show Max: the maximum in mBq/year', t['name'], f"flux ({t['maxText']})")
            check('  a number in the thousands', 2000 < float(t['maxText']) < 3001, True)
            await page.ev("__prefix('y', '')")
            s = await st(page)
            t = s['traces'][0]
            check('  and in Bq/year once the prefix is gone', (t['name'], float(t['maxText']) < 3.001), (f"flux ({t['maxText']})", True))
            check('no prefix on y: the file\'s values exactly, and its title',
                  (t['y'] == flux['y'], s['axes']['yaxis']['title']), (True, 'Value (Bq/year)'))
            await page.ev("__tick('showMax', false)")

            await page.ev("(async () => { await __choose('default'); await __scale('y', 'log'); })()")
            s = await st(page)
            check('log y on auto range: the decades of the data, 1 to 10', (s['axes']['yaxis']['range'], s['autoLogY']), ([0, 1], True))
            await page.ev("__prefix('y', 'm')")
            s = await st(page)
            check('  in m: 1e3 to 1e4, still on auto range, Auto range still selected',
                  (s['axes']['yaxis']['range'], s['autoLogY'], s['sel']), ([3, 4], True, 'default'))

            # --- a chart drawn after the change --------------------------------
            await page.ev("__pick('overlay.h5', '/geosphere/near_field/flux2')")
            s = await st(page)
            t = s['traces'][0]
            check('a chart drawn afterwards is drawn in the prefixes',
                  (s['exp'], s['axes']['xaxis']['title'], s['axes']['yaxis']['title']),
                  ({'x': 3, 'y': -3}, 'Time (kyears)', 'Value (mBq/year)'))
            check('  its values the file\'s, moved', (all_shifted(t['x'], t['fileX'], 3), all_shifted(t['y'], t['fileY'], -3)), (True, True))
            check('  its background in kyears too', s['shapes'][:1], [[0, 1]])
            await phases_named(page, 'drawn in kyears')

            csv = await page.ev('__csv()')
            rows = [r.split(',') for r in csv.strip().splitlines()[1:]]
            check('the CSV holds the file\'s values, not the axis\'s',
                  ([float(r[1]) for r in rows] == t['fileX'], [float(r[2]) for r in rows] == t['fileY']), (True, True))

            xl = await page.ev('__export()', timeout=60)
            cells, charts = workbook(xl['b64'])
            data = cells['Data']
            texts = [v for v in data.values() if isinstance(v, str)]
            check('the Excel workbook: its time unit kyears and its line\'s unit mBq/year',
                  ('kyears' in texts, 'mBq/year' in texts), (True, True))
            check('  a note on each axis\'s prefix',
                  [x for x in texts if 'has the prefix' in x],
                  ["The x axis has the prefix k: its values, here and in the chart, are the files' divided by 10³.",
                   "The y axis has the prefix m: its values, here and in the chart, are the files' times 10³."])
            head = next(ref for ref, v in data.items() if v == 'flux2')
            col, row = re.fullmatch(r'([A-Z]+)(\d+)', head).groups()
            check('  the values in the axis\'s unit', data.get(f'{col}{int(row) + 2}'), t['y'][0])
            check('  and the chart\'s titles in it', ('Value (mBq/year)' in charts, 'Time (kyears)' in charts), (True, True))
            script = await page.ev("pyChartScript(document.getElementById('plotlyChart')).code")
            check('the Python script labels its axes divided: factor 1e3 on x, 1e-3 on y',
                  ('factor=1e3' in script, 'factor=1e-3' in script), (True, True))

            # --- presets ------------------------------------------------------
            await page.ev("(async () => { await __scale('y', 'linear'); await __zoomY(1500, 2500); })()")
            await page.ev("(async () => { window.__askText = 'Milli'; await saveCurrentAsPreset(); await __wait(300); })()")
            milli = await page.ev("loadPresets().find(p => p.name === 'Milli')")
            check('saving the view: its limits in the file\'s units, and its prefixes',
                  (milli['yMin'], milli['yMax'], milli['yPrefix'], milli['xPrefix'], milli['xMin']), (1.5, 2.5, 'm', 'k', None))
            check('  and it is the one selected', (await st(page))['sel'], milli['id'])
            await page.ev("__prefix('y', '')")
            s = await st(page)
            check('another prefix by hand: the view is not the preset\'s any more, Custom', s['sel'], '__custom__')
            check('  the same stretch in Bq/year', s['axes']['yaxis']['range'], [1.5, 2.5])
            await page.ev(f"__choose({json.dumps(milli['id'])})")
            s = await st(page)
            check('choosing the preset brings its prefix back, over its limits',
                  (s['selects']['y'], s['axes']['yaxis']['title'], s['axes']['yaxis']['range'], s['sel']),
                  ('m', 'Value (mBq/year)', [1500, 2500], milli['id']))

            await page.ev("__choose('release')")
            s = await st(page)
            check('a preset with no prefix keeps the chart\'s: SFR Release in kyears and mBq/year',
                  (s['selects'], s['axes']['xaxis']['range'], s['axes']['yaxis']['range']),
                  ({'x': 'k', 'y': 'm'}, [-1, 2], [7, 12]))

            await page.ev('openPresetManager(); true')
            s = await st(page)
            summary = {r['id']: r['summary'] for r in s['rows']}
            check('the manager: a preset\'s summary in its prefix',
                  ('X: linear, prefix k [auto]' in summary[milli['id']], 'Y: linear, prefix m [1500 – 2500]' in summary[milli['id']]),
                  (True, True))
            check('  SFR Release\'s as it was, without one', summary['release'], 'X: log [100 – 100000]   Y: log [10000 – 1000000000]')
            check('  the Current view\'s in the prefixes on screen', summary['__current__'],
                  'X: log, prefix k [0.1 – 100]   Y: log, prefix m [10000000 – 1000000000000]')

            await page.ev(f"__btn({json.dumps(milli['id'])}, 'Edit').click(); true")
            form = await page.ev('__form()')
            check('editing a preset: its prefix, and its limits in it', (form['yPrefix'], form['yMin'], form['yMax']), ('m', '1500', '2500'))
            check('  offering "as is" and "none" before the prefixes', form['options'][:3], ['', 'none', 'P'])
            form = await page.ev("__formPrefix('y', 'k')")
            check('  choosing k moves the numbers to the same limits in k', (form['yMin'], form['yMax']), ('0.0015', '0.0025'))
            form = await page.ev("__formPrefix('y', '')")
            check('  and "as is" to the file\'s units', (form['yMin'], form['yMax']), ('1.5', '2.5'))
            await page.ev("__formPrefix('y', 'k'); pe_save.click(); __wait(500)")
            edited = await page.ev(f"loadPresets().find(p => p.id === {json.dumps(milli['id'])})")
            check('  saved: the same limits, now with k', (edited['yPrefix'], edited['yMin'], edited['yMax']), ('k', 1.5, 2.5))
            s = await st(page)
            check('  and the chart, on another preset, did not move',
                  (s['sel'], s['selects'], s['axes']['yaxis']['range']), ('release', {'x': 'k', 'y': 'm'}, [7, 12]))

            await page.ev("__btn('__current__', 'Edit').click(); true")
            form = await page.ev('__form()')
            check('the Current view editor: the prefix on screen, no "as is"',
                  (form['yPrefix'], form['options'][:2], form['yMin'], form['yMax']), ('m', ['none', 'P'], '10000000', '1000000000000'))
            form = await page.ev("__formPrefix('y', 'k')")
            check('  choosing k moves its numbers too', (form['yMin'], form['yMax']), ('10', '1000000'))
            await page.ev('pe_save.click(); __wait(900)')
            s = await st(page)
            check('  applying the prefix alone: the same stretch, 1e4 to 1e9 Bq/year as 10 to 1e6 kBq/year',
                  (s['selects']['y'], s['axes']['yaxis']['title'], s['axes']['yaxis']['range'], s['sel']),
                  ('k', 'Value (kBq/year)', [1, 6], '__custom__'))
            await page.ev("__btn('__current__', 'Edit').click(); __formPrefix('y', 'M'); __set({ yMax: '100' }); pe_save.click(); __wait(900)")
            s = await st(page)
            check('  a prefix and a limit typed in it: 0.01 to 100 MBq/year',
                  (s['selects']['y'], s['axes']['yaxis']['range']), ('M', [-2, 2]))

            imported = await page.ev(r"""(async () => {
              const json = JSON.stringify([
                { id: 'imp1', name: 'Imported', xPrefix: 'μ', yPrefix: 'x' },
                { id: 'imp2', name: 'Imported 2', xPrefix: 'u', yPrefix: '' },
                { id: 'imp3', name: 'Imported 3', xPrefix: { k: 1 }, yPrefix: 'k' }]);
              const realClick = HTMLInputElement.prototype.click;
              HTMLInputElement.prototype.click = function () {
                if (this.type !== 'file') return realClick.call(this);
                const dt = new DataTransfer();
                dt.items.add(new File([json], 'presets.json', { type: 'application/json' }));
                this.files = dt.files;
                this.onchange();
              };
              try { importPresets(); } finally { HTMLInputElement.prototype.click = realClick; }
              await __wait(600);
              return loadPresets().filter(p => p.id.startsWith('imp')).map(p => [p.xPrefix, p.yPrefix]);
            })()""")
            check('an imported prefix is one of the page\'s: Greek mu and u are µ, anything else keeps the chart\'s',
                  imported, [['µ', None], ['µ', ''], [None, 'k']])
            await page.ev('closePresetManager(); true')

            # --- the axes lock ------------------------------------------------
            await page.ev("(async () => { await __prefix('y', 'm'); await __scale('y', 'linear'); await __zoomY(1500, 2500); toggleAxesLock(); await __wait(200); })()")
            s = await st(page)
            check('locked: the prefix selects are disabled', s['disabled'], {'x': True, 'y': True})
            await page.ev("__pick('overlay.h5', '/geosphere/near_field/flux')")
            s = await st(page)
            check('  a chart drawn locked has the locked stretch, in the locked prefix',
                  (s['selects']['y'], s['axes']['yaxis']['title'], s['axes']['yaxis']['range']), ('m', 'Value (mBq/year)', [1500, 2500]))
            await page.ev('toggleAxesLock(); true')
            check('  and unlocking enables them again', (await st(page))['disabled'], {'x': False, 'y': False})

            # --- several groups, a band ---------------------------------------
            await page.ev("""(async () => { await __background(false); await __only('groups.h5'); await __prefix('x', '');
                await __scale('x', 'log'); await __scale('y', 'log'); await __prefix('y', 'k');
                await __pick('groups.h5', '/bio/areaA', { group: true }); await __pick('groups.h5', '/dose', { group: true, ctrl: true }); })()""",
                          timeout=120)
            s = await st(page)
            check('two groups a panel each: each in its own unit, with the prefix',
                  (s['axes']['yaxis']['title'], s['axes']['yaxis2']['title'], s['axes']['xaxis2']['title']), ('kBq', 'kSv/year', 'Time (years)'))
            before = s
            await page.ev("__prefix('y', 'µ')")
            s = await st(page)
            check('  µ in place: µBq and µSv/year', (s['axes']['yaxis']['title'], s['axes']['yaxis2']['title']), ('µBq', 'µSv/year'))
            check('  every line\'s values the file\'s, moved',
                  all(all_shifted(t['y'], t['fileY'], -6) for t in s['traces']), True)
            check('  each panel on auto range still, nine decades up',
                  [[round(v - w, 9) for v, w in zip(s['axes'][k]['range'], before['axes'][k]['range'])] for k in ('yaxis', 'yaxis2')],
                  [[9, 9], [9, 9]])

            await page.ev("(async () => { await __pick('groups.h5', '/bio/areaB', { group: true }); await __tick('showCI', true); })()")
            s = await st(page)
            bands = [t for t in s['traces'] if t['band']]
            check('a band the CI toggle adds is in the prefix', (len(bands) > 0, all(all_shifted(b['y'], b['fileY'], -6) for b in bands)), (True, True))
            await page.ev("__prefix('y', 'k')")
            s = await st(page)
            bands = [t for t in s['traces'] if t['band']]
            check('  and is redrawn in the next one', all(all_shifted(b['y'], b['fileY'], 3) for b in bands), True)
            await page.ev("__tick('showCI', false)")

            # --- the select in its label --------------------------------------
            clicks = await page.ev("""(async () => {
              const select = document.getElementById('xPrefixSelect');
              const before = getScaleValue('x');
              select.dispatchEvent(new MouseEvent('click', { bubbles: true }));
              await __wait(600);
              const onSelect = getScaleValue('x');
              select.closest('label').click();
              await __wait(900);
              const onLabel = getScaleValue('x');
              select.closest('label').click();
              await __wait(900);
              return [before, onSelect, onLabel, getScaleValue('x')];
            })()""")
            check('a click on the prefix select leaves lin/log alone; one on the label still toggles it',
                  clicks, ['log', 'log', 'linear', 'log'])

            await page.ev("(async () => { await __prefix('x', ''); await __prefix('y', ''); })()")
            check('no console errors throughout', page.logs[:3], [])
        finally:
            await page.ev("(v => { if (v === null) localStorage.removeItem('chartPresets');"
                          " else localStorage.setItem('chartPresets', v); return true; })(%s)" % json.dumps(stored))
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
