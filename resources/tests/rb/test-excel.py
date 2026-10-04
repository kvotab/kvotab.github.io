#!/usr/bin/env python3
"""The chart's Excel export (rb-chart-excel.js): a workbook with the chart as
the page draws it, over the data it is drawn from.

Each case draws a chart, exports it with XlsxWriter.saveAs stubbed to catch
the workbook, and reads the workbook back with the standard library:

  * every series points at cells of the Data sheet, and they hold what the
    series' cache says, name included;
  * no series on a log axis points at a zero or a negative value. Excel puts
    up an alert for one every time the workbook is opened, and a modal one,
    which holds up the whole of Excel until it is answered;
  * the legend lists what the page's legend lists, in the page's order;
  * the axes are lin or log as on the page, over its range;
  * a linear axis's labels are over the page's exponent (display units and
    the ×10⁻¹¹ or the M in the format), with fixed decimals: never General
    with text after it, which makes Excel move the plot area (xlTickFormat);
  * a chart of several groups is a chart a panel, all of one width and with
    their plot areas lined up, each under its label;
  * the Data sheet says over each column what it is of: its panel, or its
    file when the lines are of two files.

How Excel draws it is not checked here. That was compared by eye when the
export was written (2026-09-27), the page's screenshot against Excel's own
rendering of the workbook; the top of rb-chart-excel.js lists what Excel
cannot draw the same way.

The panels, the overlay and a zero on a log axis come from a file built in
the page with h5wasm, so nothing binary is committed; the rest from the two
sample fixtures. Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-excel.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import io
import json
import re
import sys
import urllib.request
import zipfile
from xml.etree import ElementTree as ET

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


GROUP = '/biosphere/vault_A/mire/total'

# time: 0, then 10 .. 1e5 log-spaced. /geo/flux draws positive; /geo/gap is
# zero for a stretch in the middle; /geo/_phase is a background source.
# /bio/areaA and /bio/areaB in Bq and /dose in Sv/year are groups that draw a
# chart each, as in test-groups.py.
BUILD = r"""(async () => {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = '/excel-test-' + Date.now() + '.h5';
  const n = 40;
  const t = Float64Array.from({ length: n }, (_, i) => i === 0 ? 0 : Math.pow(10, 1 + 4 * (i - 1) / (n - 2)));
  const w = new File(path, 'w');
  const put = (g, name, data, shape, attrs) => {
    const d = g.create_dataset({ name, data: Float64Array.from(data), shape, dtype: '<f8' });
    for (const [k, v] of Object.entries(attrs)) d.create_attribute(k, v);
  };
  const nuclides = (g, unit, scale) => {
    g.create_attribute('IndexLists', ['Radionuclides']);
    g.create_attribute('time_dependent', 'TRUE');
    g.create_attribute('unit', unit);
    for (const [nuc, f] of [['Cs-137', 1], ['I-129', 0.3]]) {
      put(g, nuc, Array.from(t, v => scale * f * (v + 1) / 1e4), [n], { unit, time_dependent: 'TRUE' });
    }
  };
  try {
    put(w, 'time', t, [n], { unit: 'years' });
    const geo = w.create_group('geo');
    put(geo, 'flux', Array.from(t, (_, i) => Math.sin(i / 5) + 2), [n], { unit: 'Bq/year', time_dependent: 'True' });
    put(geo, 'gap', Array.from(t, (_, i) => (i >= 15 && i < 20 ? 0 : Math.exp(-i / 9))), [n],
        { unit: 'mol/year', time_dependent: 'True' });
    geo.create_dataset({ name: '_phase', data: Float64Array.from([1000, 10000, 100000]), shape: [3], dtype: '<f8' })
      .create_attribute('Index', '["Submerged","Shore","Terrestrial"]');
    const bio = w.create_group('bio');
    nuclides(bio.create_group('areaA'), 'Bq', 100);
    nuclides(bio.create_group('areaB'), 'Bq', 10);
    nuclides(w.create_group('dose'), 'Sv/year', 1e-6);
  } finally {
    w.close();
  }
  const name = 'excel.h5';
  loadedFileBuffers[name] = FS.readFile(path).slice().buffer;
  loadedFiles[name] = new File(path, 'r');
  fileStates[name] = true;
  if (!fileOrder.includes(name)) fileOrder.push(name);
  await updateTabs(true);
  return fileOrder.slice();
})()"""

HELPERS = r"""(() => {
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  // The workbook, caught instead of downloaded.
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
  // What the page shows: its legend, in its order, and each axis.
  window.__page = () => {
    const gd = document.getElementById('plotlyChart');
    const fl = gd._fullLayout;
    const legend = gd._fullData
      .filter(t => t.visible === true && t.showlegend !== false)
      .map(t => ({ name: t.name, rank: isFinite(t.legendrank) ? t.legendrank : 1000, i: t.index }))
      .sort((a, b) => (a.rank - b.rank) || (a.i - b.i)).map(t => t.name);
    const axes = Object.keys(fl).filter(k => /^[xy]axis\d*$/.test(k)).sort().map(k => ({
      key: k, type: fl[k].type, range: fl[k].range.map(Number), labels: fl[k].showticklabels !== false,
      exponent: fl[k]._tickexponent || 0, format: fl[k].exponentformat || 'B',
      domain: fl[k].domain.map(Number) }));
    const segments = (gd.__bgSegments || []).map(s => ({ name: String(s.category), x0: Number(s.x0), x1: Number(s.x1) }));
    const shapes = (fl.shapes || []).filter(s => s.name === BACKGROUND_SHAPE_NAME).map(s => [Number(s.x0), Number(s.x1)]);
    return { legend, axes, segments, shapes };
  };
  window.__row = (path) => findTreeItem(path, { extra: '.group', root: document.getElementById('tree') });
  window.__click = async (path, ctrl) => {
    __row(path).dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: !!ctrl }));
    await __wait(2500);
  };
  window.__scale = async (axis, value) => {
    document.querySelector(`#${axis}ScaleToggle button[data-value=${value}]`).click();
    await __wait(1500);
  };
  return true;
})()"""


# --- the workbook, read with the standard library ------------------------

A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
NS = {
    'm': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'pr': 'http://schemas.openxmlformats.org/package/2006/relationships',
    'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
}


class Book:
    def __init__(self, b64):
        self.zip = zipfile.ZipFile(io.BytesIO(base64.b64decode(b64)))
        wb = ET.fromstring(self.zip.read('xl/workbook.xml'))
        rels = ET.fromstring(self.zip.read('xl/_rels/workbook.xml.rels'))
        target = {r.get('Id'): r.get('Target') for r in rels.findall('pr:Relationship', NS)}
        self.sheets = {s.get('name'): 'xl/' + target[s.get(f"{{{NS['r']}}}id")]
                       for s in wb.find('m:sheets', NS).findall('m:sheet', NS)}
        strings = []
        if 'xl/sharedStrings.xml' in self.zip.namelist():
            for si in ET.fromstring(self.zip.read('xl/sharedStrings.xml')).findall('m:si', NS):
                strings.append(''.join(t.text or '' for t in si.iter(f"{{{NS['m']}}}t")))
        # Each style as a cell shows it: bold, italic, size and number format.
        st = ET.fromstring(self.zip.read('xl/styles.xml'))
        codes = {n.get('numFmtId'): n.get('formatCode') for n in st.iter(f"{{{NS['m']}}}numFmt")}
        fonts = [{'bold': f.find('m:b', NS) is not None, 'italic': f.find('m:i', NS) is not None,
                  'size': float(f.find('m:sz', NS).get('val'))}
                 for f in st.find('m:fonts', NS).findall('m:font', NS)]
        self.xf = []
        for x in st.find('m:cellXfs', NS).findall('m:xf', NS):
            fmt = x.get('numFmtId', '0')
            self.xf.append(dict(fonts[int(x.get('fontId', '0'))],
                                format=codes.get(fmt, 'General' if fmt == '0' else fmt)))
        self.cells = {}
        self.styles = {}
        self.merged = {}
        for name, part in self.sheets.items():
            root = ET.fromstring(self.zip.read(part))
            cells = {}
            styles = {}
            for c in root.iter(f"{{{NS['m']}}}c"):
                v = c.find('m:v', NS)
                if v is None:
                    continue
                cells[c.get('r')] = strings[int(v.text)] if c.get('t') == 's' else float(v.text)
                styles[c.get('r')] = self.xf[int(c.get('s', '0'))]
            self.cells[name] = cells
            self.styles[name] = styles
            self.merged[name] = [m.get('ref') for m in root.iter(f"{{{NS['m']}}}mergeCell")]
        self.charts = [ET.fromstring(self.zip.read(n)) for n in sorted(
            (n for n in self.zip.namelist() if re.fullmatch(r'xl/charts/chart\d+\.xml', n)),
            key=lambda n: int(re.search(r'(\d+)\.xml$', n).group(1)))]

    def range(self, ref):
        m = re.fullmatch(r"(?:'?([^'!]+)'?!)\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?", ref)
        sheet, col, r0 = m.group(1), m.group(2), int(m.group(3))
        r1 = int(m.group(5) or r0)
        return [self.cells[sheet].get(f'{col}{r}') for r in range(r0, r1 + 1)]


def value_formats(book, names):
    """For each column headed by one of `names`, the format the page gives its
    values (xlValueFormat: scientific where General would print a long
    decimal) and the styles they are in: [(name, wanted, set of (format,
    bold, italic))]. The values start two rows under the name, below the unit."""
    out = []
    cells, styles = book.cells['Data'], book.styles['Data']
    for ref, head in cells.items():
        if head not in names:
            continue
        col, row = re.fullmatch(r'([A-Z]+)(\d+)', ref).groups()
        refs = [k for k, v in cells.items() if isinstance(v, float)
                and re.fullmatch(col + r'\d+', k) and int(k[len(col):]) >= int(row) + 2]
        mags = [abs(cells[k]) for k in refs if cells[k] != 0]
        wanted = '0.000E+00' if mags and (max(mags) >= 1e6 or min(mags) < 1e-3) else 'General'
        out.append((head, wanted, {(styles[k]['format'], styles[k]['bold'], styles[k]['italic']) for k in refs}))
    return out


def chart_info(book, chart):
    """What one chart part says: its axes, its series with what they point at, its legend."""
    axes = {}
    for ax in chart.iter(f"{{{NS['c']}}}valAx"):
        fmt = ax.find('c:numFmt', NS)
        unit = ax.find('c:dispUnits/c:custUnit', NS)
        axes[ax.find('c:axId', NS).get('val')] = {
            'log': ax.find('c:scaling/c:logBase', NS) is not None,
            'min': float(ax.find('c:scaling/c:min', NS).get('val')),
            'max': float(ax.find('c:scaling/c:max', NS).get('val')),
            'format': fmt.get('formatCode') if fmt is not None else None,
            'unit': float(unit.get('val')) if unit is not None else None,
            'labels': ax.find('c:tickLblPos', NS).get('val') != 'none',
        }
    x_id, y_id = [a.get('val') for a in chart.find('.//c:scatterChart', NS).findall('c:axId', NS)]
    deleted = {int(e.find('c:idx', NS).get('val')) for e in chart.iter(f"{{{NS['c']}}}legendEntry")
               if e.find('c:delete', NS).get('val') == '1'}
    series = []
    for s in chart.iter(f"{{{NS['c']}}}ser"):
        one = {'idx': int(s.find('c:idx', NS).get('val')),
               'name': s.find('c:tx/c:strRef/c:strCache/c:pt/c:v', NS).text,
               'nameCell': book.range(s.find('c:tx/c:strRef/c:f', NS).text)[0]}
        for tag in ('xVal', 'yVal'):
            lit = s.find(f'c:{tag}/c:numLit', NS)
            if lit is not None:   # written into the chart, not taken from cells
                values = [float(p.find('c:v', NS).text) for p in lit.findall('c:pt', NS)]
                one[tag] = {'ref': None, 'cells': values, 'cache': dict(enumerate(values)), 'literal': True}
                continue
            ref = s.find(f'c:{tag}/c:numRef/c:f', NS).text
            cache = {int(p.get('idx')): float(p.find('c:v', NS).text)
                     for p in s.findall(f'c:{tag}/c:numRef/c:numCache/c:pt', NS)}
            one[tag] = {'ref': ref, 'cells': book.range(ref), 'cache': cache, 'literal': False}
        ln = s.find('c:spPr/{%s}ln' % A_NS, NS)
        one['line'] = {'w': int(ln.get('w', 0)), 'cap': ln.get('cap')} if ln is not None else None
        series.append(one)
    layout = chart.find('c:chart/c:plotArea/c:layout/c:manualLayout', NS)
    title = chart.find('c:chart/c:title', NS)
    fill = lambda el: (el.find('{%s}solidFill/{%s}srgbClr' % (A_NS, A_NS)).get('val') if el is not None
                       and el.find('{%s}solidFill/{%s}srgbClr' % (A_NS, A_NS)) is not None else None)
    return {
        'fills': {'chart': fill(chart.find('c:spPr', NS)), 'plot': fill(chart.find('c:chart/c:plotArea/c:spPr', NS))},
        'x': axes[x_id], 'y': axes[y_id], 'series': series,
        'legend': [s['name'] for s in series if s['idx'] not in deleted] if chart.find('.//c:legend', NS) is not None else [],
        'plot': {k: float(layout.find(f'c:{k}', NS).get('val')) for k in ('x', 'w')},
        'title': ''.join(t.text or '' for t in title.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}t')) if title is not None else '',
    }


def refs_hold_the_cache(info):
    """Every series' cells are what its cache says, and its name is the name cell's."""
    bad = []
    for s in info['series']:
        if s['name'] != s['nameCell']:
            bad.append(f"{s['name']!r}: name cell {s['nameCell']!r}")
        for tag in ('xVal', 'yVal'):
            if s[tag]['literal']:
                continue
            for i, v in enumerate(s[tag]['cells']):
                c = s[tag]['cache'].get(i)
                if (v is None) != (c is None) or (v is not None and abs(v - c) > 1e-12 * max(1.0, abs(v))):
                    bad.append(f"{s['name']!r} {tag} {s[tag]['ref']} row {i}: cell {v!r}, cache {c!r}")
                    break
    return bad


def nothing_undrawable_on_log(info):
    """Cells or values written into the chart alike: either would bring up Excel's alert."""
    bad = []
    for s in info['series']:
        for tag, axis in (('xVal', info['x']), ('yVal', info['y'])):
            if axis['log'] and any(v is not None and v <= 0 for v in s[tag]['cells']):
                bad.append(f"{s['name']!r} {tag} {s[tag]['ref'] or 'in the chart'}")
    return bad


def close(a, b, rel=1e-9):
    return abs(a - b) <= rel * max(abs(a), abs(b), 1e-300)


def axis_matches(xl, page):
    """Lin or log as on the page, over its range (a linear minimum may be snapped onto a tick)."""
    lo, hi = sorted(page['range'])
    if page['type'] == 'log':
        return xl['log'] and close(xl['min'], 10 ** lo, 1e-9) and close(xl['max'], 10 ** hi, 1e-9)
    span = hi - lo
    return (not xl['log']) and close(xl['max'], hi, 1e-9) and lo - 0.02 * span - 1e-12 <= xl['min'] <= lo + 1e-12


SUP = str.maketrans('-0123456789', '⁻⁰¹²³⁴⁵⁶⁷⁸⁹')


def format_says_exponent(xl, page):
    """A linear axis's labels over the page's exponent: ×10⁻¹¹, k, M ... with fixed decimals."""
    fmt = xl['format'] or ''
    if any('General' in part and '"' in part for part in fmt.split(';')):
        return f'General with text: {fmt}'
    e = page['exponent']
    if not page['labels'] or page['type'] == 'log' or not e:
        return xl['unit'] is None or f'unit {xl["unit"]} for exponent {e}'
    if xl['unit'] is None or not close(xl['unit'], 10.0 ** e):
        return f'unit {xl["unit"]} for exponent {e}'
    want = {3: 'k', 6: 'M', 9: 'B'}.get(e) if page['format'] in ('B', 'SI') else None
    want = want or '×10' + str(e).translate(SUP)
    return want in fmt or f'{fmt} lacks {want}'


async def export_case(page, label):
    got = await page.ev('__export()', timeout=120)
    if not isinstance(got, dict):
        check(f'{label}: a workbook is written', got, 'a workbook')
        return None, None
    return Book(got['b64']), await page.ev('__page()')


def common_checks(label, book, shown, want_panels=1):
    infos = [chart_info(book, c) for c in book.charts]
    check(f'{label}: a chart a panel, on the Chart sheet', len(infos), want_panels)
    check(f'{label}:   every series points at the Data cells its cache holds',
          [b for i in infos for b in refs_hold_the_cache(i)], [])
    check(f'{label}:   and none at a zero or a negative value on a log axis',
          [b for i in infos for b in nothing_undrawable_on_log(i)], [])
    check(f'{label}:   the legend is the page\'s, in its order', [n for i in infos for n in i['legend']], shown['legend'])
    check(f'{label}:   on white, round the plot and behind it, whatever theme the page is in',
          {(i['fills']['chart'], i['fills']['plot']) for i in infos}, {('FFFFFF', 'FFFFFF')})
    xs = [a for a in shown['axes'] if a['key'].startswith('x')]
    ys = sorted((a for a in shown['axes'] if a['key'].startswith('y')), key=lambda a: -a['domain'][1])
    if len(ys) == len(infos):
        check(f'{label}:   each y axis lin or log as on the page, over its range',
              [axis_matches(i['y'], a) for i, a in zip(infos, ys)], [True] * len(infos))
        check(f'{label}:   and labelled over its exponent, decimals fixed',
              [format_says_exponent(i['y'], a) for i, a in zip(infos, ys)], [True] * len(infos))
    labelled = [a for a in xs if a['labels']]   # the bottom panel's; the others have none
    bottom = labelled[-1] if labelled else None
    if bottom:
        last = infos[-1]
        check(f'{label}:   the time axis lin or log as on the page, over its range', axis_matches(last['x'], bottom), True)
        check(f'{label}:   and labelled as the page labels it', format_says_exponent(last['x'], bottom), True)
    return infos


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            await page.ev(HELPERS)
            await load_samples(page, ['sample-a.h5'])
            await page.ev("(async () => { await expandAndLoadPath('sample-a.h5', %s); findTreeItem(%s, { extra: '.group' }).click(); await __wait(3500); })()"
                          % (json.dumps(GROUP), json.dumps(GROUP)), timeout=120)

            # --- a radionuclide group, linear ---------------------------------
            book, shown = await export_case(page, 'group')
            if book:
                check('group: the workbook opens on the chart, over its data', list(book.sheets), ['Chart', 'Data'])
                infos = common_checks('group', book, shown)
                names = [s['name'] for s in infos[0]['series']]
                heads = [v for k, v in book.cells['Data'].items() if isinstance(v, str)]
                check('group:   each line\'s column is headed by its name', all(n in heads for n in names), True)
                # In the formats the page asks for. xlsxwrite.js put every
                # format one style late and dropped the number formats until
                # 2026-10-04: the names came out plain and the values in General
                # and in the unit row's small italics.
                looks = {(s['bold'], s['italic'], s['size']) for s in
                         (book.styles['Data'][k] for k, v in book.cells['Data'].items() if v in names)}
                check('group:   the names are bold, at the sheet\'s size', sorted(looks), [(True, False, 11.0)])
                formats = value_formats(book, names)
                check('group:   and each column\'s values plain, in the number format the page chose for them',
                      [(n, sorted(got)) for n, wanted, got in formats if got != {(wanted, False, False)}], [])
                check('group:   scientific for at least one', any(w == '0.000E+00' for _, w, _ in formats), True)

            # --- CI bands, an iteration and log axes --------------------------
            await page.ev("(async () => { document.getElementById('showCI').click(); await __wait(1500); const i = document.getElementById('showIterNum'); i.value = '3'; i.dispatchEvent(new Event('input', { bubbles: true })); await __wait(1500); await __scale('x', 'log'); await __scale('y', 'log'); })()")
            book, shown = await export_case(page, 'CI, log')
            if book:
                infos = common_checks('CI, log', book, shown)
                s = infos[0]['series']
                bands = [x['name'] for x in s if x['name'].endswith((' 5%', ' 95%'))]
                check('CI, log:   each line\'s band is its two edges, left out of the legend',
                      (len(bands) > 0, any(b in infos[0]['legend'] for b in bands)), (True, False))
                total = [c for c, v in book.cells['Data'].items() if v in ('Total', 'Total 5%', 'Total 95%')]
                cols = sorted(re.match(r'[A-Z]+', c).group(0) for c in total)
                check('CI, log:   and its columns stand beside the line\'s', cols, ['B', 'C', 'D'])
                check('CI, log:   the iteration is in the legend', any(n.replace('\xa0', ' ').startswith('Iter. 3') for n in infos[0]['legend']), True)
            await page.ev("(async () => { document.getElementById('showCI').click(); const i = document.getElementById('showIterNum'); i.value = ''; i.dispatchEvent(new Event('input', { bubbles: true })); await __wait(800); await __scale('x', 'linear'); await __scale('y', 'linear'); })()")

            # --- two files ---------------------------------------------------
            await load_samples(page, ['sample-a.h5', 'sample-b.h5'])
            await page.ev("(async () => { document.querySelector('#treeModeContainer button[data-value=intersect]').click(); await __wait(2500); await expandAndLoadPath(fileOrder[0], %s); const el = findTreeItem(%s, { extra: '.group' }); if (el) el.click(); await __wait(3500); })()"
                          % (json.dumps(GROUP), json.dumps(GROUP)), timeout=120)
            book, shown = await export_case(page, 'two files')
            if book:
                common_checks('two files', book, shown)
                groups = sorted(v for k, v in book.cells['Data'].items() if v in ('sample-a.h5', 'sample-b.h5'))
                check('two files:   over the columns, the file each is of, once a file', groups, ['sample-a.h5', 'sample-b.h5'])
                check('two files:   each over its run of columns', len(book.merged['Data']), 2)
            await page.ev("(async () => { document.querySelector('#treeModeContainer button[data-value=separated]').click(); await __wait(1500); })()")

            # --- the built file: panels --------------------------------------
            check('the test file is built and loaded', 'excel.h5' in (await page.ev(BUILD, timeout=120) or []), True)
            await page.ev("(async () => { fileOrder.filter(n => n !== 'excel.h5').forEach(n => { fileStates[n] = false; }); await updateTabs(true); await __wait(1500); await expandAndLoadPath('excel.h5', '/bio/areaA'); await expandAndLoadPath('excel.h5', '/dose'); await __click('/bio/areaA'); await __click('/bio/areaB', true); await __click('/dose', true); })()", timeout=120)
            book, shown = await export_case(page, 'panels')
            if book:
                infos = common_checks('panels', book, shown, want_panels=3)
                check('panels:   every plot area starts and ends where the others do',
                      len({(round(i['plot']['x'], 5), round(i['plot']['w'], 5)) for i in infos}), 1)
                check('panels:   each chart under its panel\'s label',
                      [i['title'].split(' ')[0] for i in infos], ['/bio/areaA', '/bio/areaB', '/dose'])
                check('panels:   the legend once, on the first', [bool(i['legend']) for i in infos], [True, False, False])
                labels = [i['title'] for i in infos]
                check('panels:   over the columns, the panel each is of, each over its run',
                      ([t in book.cells['Data'].values() for t in labels], len(book.merged['Data'])), ([True] * 3, 3))

            # --- the panels again, with a background overlay: in every panel --
            has = await page.ev("(async () => { const sel = document.getElementById('backgroundSourceSelect'); const v = [...sel.options].map(o => o.value).find(v => v.endsWith('_phase')); if (!v) return false; sel.value = v; sel.dispatchEvent(new Event('change', { bubbles: true })); await __wait(2500); return (document.getElementById('plotlyChart')._fullLayout.shapes || []).length > 0; })()", timeout=120)
            if has:
                book, shown = await export_case(page, 'panels, overlay')
                if book:
                    infos = common_checks('panels, overlay', book, shown, want_panels=3)
                    check('panels, overlay:   the overlay in every panel, as the page draws it down all of them',
                          [[x['name'] for x in i['series'][:3]] for i in infos], [['Submerged', 'Shore', 'Terrestrial']] * 3)
                    check('  each at a level of its own panel',
                          all(i['y']['min'] <= i['series'][0]['yVal']['cells'][0] <= i['y']['max'] for i in infos), True)
                await page.ev("(async () => { const sel = document.getElementById('backgroundSourceSelect'); sel.value = ''; sel.dispatchEvent(new Event('change', { bubbles: true })); await __wait(1500); })()")
            else:
                print('skip  the panels with an overlay: the page offers none for them')

            # --- the built file: a background overlay, lin and log ----------
            await page.ev("(async () => { selectedGroups = []; selectDataset('/geo/flux'); await __wait(2000); const sel = document.getElementById('backgroundSourceSelect'); sel.value = [...sel.options].map(o => o.value).find(v => v.endsWith('_phase')); sel.dispatchEvent(new Event('change', { bubbles: true })); await __wait(2000); })()", timeout=120)
            for scale in ('lin', 'log'):
                if scale == 'log':
                    await page.ev("__scale('x', 'log')")
                label = f'overlay, {scale}'
                book, shown = await export_case(page, label)
                if not book:
                    continue
                infos = common_checks(label, book, shown)
                phases = [x for x in infos[0]['series'] if x['name'] in ('Submerged', 'Shore', 'Terrestrial')]
                check(f'{label}:   the phases are drawn behind the line, left out of the legend',
                      ([x['name'] for x in phases], any(x['name'] in infos[0]['legend'] for x in phases), infos[0]['series'][3]['name']),
                      (['Submerged', 'Shore', 'Terrestrial'], False, 'flux'))
                check(f'{label}:   each along the time it spans, as the page draws it, from its cells',
                      [[round(v, 6) for v in x['xVal']['cells']] for x in phases], [[round(v, 6) for v in s2] for s2 in shown['shapes']])
                check(f'{label}:   level, as thick as Excel draws a line, cut square at the ends',
                      {(len(set(x['yVal']['cells'])), x['line']['w'], x['line']['cap']) for x in phases}, {(1, 1584 * 12700, 'flat')})
                table = {v: k for k, v in book.cells['Data'].items() if v in ('Submerged', 'Shore', 'Terrestrial')}
                col = re.match(r'[A-Z]+', table['Submerged']).group(0)
                row = re.sub(r'\D', '', table['Submerged'])
                check(f'{label}:   and tabled from where each starts, not from where the axis clips it',
                      book.cells['Data'].get(f'{chr(ord(col) + 1)}{row}'), min(x['x0'] for x in shown['segments']))
                if scale == 'log':
                    flux = [x for x in infos[0]['series'] if x['name'] == 'flux']
                    check(f'{label}:   the line leaves out t = 0, which a log axis cannot draw',
                          [min(v for v in x['xVal']['cells'] if v is not None) > 0 for x in flux], [True])
                    check(f'{label}:   while the Data sheet keeps it', book.cells['Data'].get('A8'), 0.0)

            # --- a zero in the middle of a line on a log axis -----------------
            await page.ev("(async () => { const sel = document.getElementById('backgroundSourceSelect'); sel.value = ''; sel.dispatchEvent(new Event('change', { bubbles: true })); selectDataset('/geo/gap'); await __wait(2000); await __scale('y', 'log'); })()", timeout=120)
            book, shown = await export_case(page, 'zeros, log')
            if book:
                infos = common_checks('zeros, log', book, shown)
                runs = [s for s in infos[0]['series'] if s['name'] == 'gap']
                check('zeros, log:   the line is its two runs either side of the zeros', len(runs), 2)
                check('zeros, log:   named in the legend once', infos[0]['legend'], ['gap'])

            # A name is a file's: made text in a <template>, whose content is inert. A <div>, even one
            # never attached, fetched an <img> put in it and ran its onerror (until 2026-09-30).
            hostile = await page.ev("""(async () => {
              window.__xlxss = 0;
              const text = xlPlainText('Cs-137<img src="data:," onerror="window.__xlxss = 1"> <b>(10<sup>-3</sup>)</b>');
              await new Promise(r => setTimeout(r, 800));
              return { text, ran: window.__xlxss };
            })()""")
            check('a name with markup in it is its text, and nothing in it runs', hostile, {'text': 'Cs-137 (10-3)', 'ran': 0})
            check('no console errors throughout', page.logs[:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))
            await bws.recv()

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
