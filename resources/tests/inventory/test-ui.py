"""End-to-end checks of canister_inventory.html in headless Chrome.

Every file is made here, from made-up numbers, in a temporary folder: a
canister inventory (JSON), and a PSAR-shaped workbook (.xlsx) and report
(.docx). They are opened through the page's file input and by a drop
(Chrome's own file machinery, over CDP). Checked:

- the page starts with no error, with its drop zone, tabs and Help;
- the files are told apart and show as chips; a broken JSON and a file of
  another kind are reported in the bar, and the page goes on;
- the Overview's numbers (canisters, elements, planned elements) and its
  three charts, with PSAR's counts beside them;
- an element name that is markup stays text;
- Time: a year brings every canister to it, a year too early is marked and
  the year in use stays, the unit and half-lives settings;
- Nuclides: the table, the chart, CSV and Excel saved;
- Canisters: each element, a click on a row opens its canister;
- Over time: the curves, with PSAR's of the same kind beside them;
- Compare with PSAR: the ratio chart only when both hold for one time, the
  totals by kind of fuel, the reactors;
- the dark theme, and a 390 px phone with no sideways scroll and 16 px
  fields.

Serve the repository root and start headless Chrome, by default on ports
8765 and 9222 (INV_HTTP_PORT and INV_CDP_PORT choose others):

    python3 -m http.server 8765
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \\
        --remote-debugging-port=9222 --user-data-dir=<fresh dir> about:blank
    python3 resources/tests/inventory/test-ui.py

Needs websockets and openpyxl. Exit status is 0 when every check passes.
"""
import asyncio
import base64
import csv as csvlib
import gzip
import io
import json
import os
import random
import re
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import websockets
from openpyxl import Workbook, load_workbook

HTTP = int(os.environ.get('INV_HTTP_PORT', '8765'))
CDP = int(os.environ.get('INV_CDP_PORT', '9222'))
URL = f'http://127.0.0.1:{HTTP}/canister_inventory.html'
ROOT = Path(__file__).resolve().parents[3]

checks = 0
failures = []


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


# ---------------------------------------------------------------- fixtures
NUCLIDES = ['cs137', 'sr90', 'pu241', 'am241', 'pu239', 'pu240', 'np237', 'u238', 'u235', 'c14', 'ni59', 'cm244', 'h3']
HOSTILE = '<img src=x onerror="window.__xss=1">'
# long names, as real ones are: a chip must shrink to a phone's width
INV = 'canister_inventory_of_all_canisters_preliminary_version_for_testing.json'
BOOK = 'Data för radionuklidinventariet (test, made-up numbers) 2 nov 2026.xlsx'
REPORT = 'Använt kärnbränsle att hantera (test, made-up numbers).docx'
GZ = 'canister_inventory_gzipped.json.gz'


def icrp107_halflives():
    """ICRP 107's half-lives (years) by nuclide, from the page's own decay data."""
    text = (ROOT / 'resources/js/rndecaydata.js').read_text(encoding='utf-8')
    out = {}
    # one record at a time: a stable nuclide has no Halflife_y of its own
    for record in text.split('{name:"')[1:]:
        t = re.search(r'Halflife_y:([-0-9.eE+]+)', record.split('Progenies')[0])
        if t:
            out.setdefault(record[:record.index('"')], float(t.group(1)))
    return out


def make_inventory(path):
    rnd = random.Random(7)
    canisters = {}
    for c in range(40):
        pwr = c % 4 == 0
        els = {}
        for e in range(4 if pwr else 12):
            reactor = 'Ringhals 4' if pwr else ('Ågesta' if (c, e) == (1, 0) else 'Kahl' if (c, e) == (2, 1) else 'Forsmark 2')
            el = {'reactor': reactor, 'reactor_type': 'PWR' if pwr else 'BWR', 'fuel_type': 'F 17*17' if pwr else 'SVEA 96'}
            for part in ('fuel', 'crud', 'structural_material'):
                scale = {'fuel': 1.0, 'crud': 1e-7, 'structural_material': 1e-3}[part]
                el[part] = {n: round(rnd.uniform(0.5, 2) * scale * (500 if n == 'u238' else 1), 6 if part == 'fuel' else 12)
                            for n in NUCLIDES}
            el['decay_heat_W'] = round(rnd.uniform(80, 160), 3)
            el['declared_heat_W'] = round(el['decay_heat_W'] * 0.97, 3)
            name = f'PLAN-ELEMENT-{c}-{e}' if e == 2 else (HOSTILE if (c, e) == (3, 3) else f'E{c:03d}{e:02d}')
            els[name] = el
        canisters[str(100 + c)] = {
            'packing_date': f'{2040 + c // 4}-{1 + c % 12:02d}-{1 + c % 27:02d}', 'fuel_elements': els,
            'decay_heat_W': round(sum(x['decay_heat_W'] for x in els.values()), 3),
            'declared_heat_W': round(sum(x['declared_heat_W'] for x in els.values()), 3),
        }
    path.write_text(json.dumps(canisters, indent=1), encoding='utf-8')
    return canisters


NAMES = ['Cs-137', 'Sr-90', 'Pu-241', 'Am-241', 'Pu-239', 'Pu-240', 'Np-237', 'U-238', 'U-235', 'C-14', 'Ni-59', 'Cm-244', 'H-3']
D1 = NAMES + ['I-129']  # the made-up report's Table D-1, two nuclides to a row


def make_workbook(path):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Totalt radionuklidinventarium'
    ws.append([None, None, 'BWR', 'PWR', 'Stavskelett', 'Ågesta', 'Swap MOX BWR', 'Swap MOX PWR', 'Summa', 'Antal kapslar',
               'Average canister', None, 'Källa antal kapslar: test'])
    ws.append([None, 'Nuklid'] + ['Aktivitet (Bq)'] * 6 + ['Totalt', 50, 'Aktivitet (Bq)'])
    for i, n in enumerate(NAMES):
        total = 1e12 * (i + 1) * 60
        ws.append([i + 1, n, total * 0.6, total * 0.3, total * 0.04, total * 0.03, total * 0.02, total * 0.01, total, None, total / 50])
    ws.append([None, 'Summa'])
    m = wb.create_sheet('Medelkapslar')
    m.append([])
    m.append(['BWR', None, None, None, 'BWR', 'Avvikelse (%)', 'Avvikelse (%)', None, 'PWR', None, 'PWR', 'PWR', 'En styrstav', None,
              'PWR +0,0863 styrstav ', None, 'Avvikelse (%)', 'Avvikelse (%)'])
    m.append([None, 'Nuklid', 'Medelelement', 'Nuklid', 'Medelkapsel', 'Låg BU (30)', 'Hög BU (50)', 'Nuklid', 'Medelelement', 'Nuklid',
              'Medelkapsel utan styrstav', 'Med en styrstav', 'Nuklid', 'Aktivitet (Bq)', 'Nuklid', 'Aktivitet (Bq)', 'Låg BU (35)', 'Hög BU (55)'])
    for i, n in enumerate(NAMES):
        m.append([i + 1, n, 1, n, 1e12 * (i + 1), -0.2, 0.25, n, 1, n, 1, 1, None, None, n, 1.2e12 * (i + 1), -0.3, 0.3])
    for kind, count in (('PWR', 4), ('BWR', 12)):
        s = wb.create_sheet(f'Medelutbränning {kind}-kapslar')
        s.append(['Patron nr', 'Reaktor', 'Reaktortyp', 'Bränslekonstr.', 'Kapsel nr', 'Dep.år', 'Resteffekt', 'Utbränn'])
        for c in range(6):
            for e in range(count):
                s.append([c * 100 + e, 'R4' if kind == 'PWR' else ('F2' if e else 'ÅGESTA'), kind, '17*17' if kind == 'PWR' else '10*10',
                          c + (1 if kind == 'PWR' else 101), 2040 + c, 1650 / count, 40 + e])
    wb.save(path)


def docx_table(rows, spans=None):
    spans = spans or {}

    def cell(t, s=1):
        span = '<w:gridSpan w:val="%d"/>' % s if s > 1 else ''
        return f'<w:tc><w:tcPr>{span}</w:tcPr><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:tc>'

    out = []
    for r, row in enumerate(rows):
        out.append('<w:tr>' + ''.join(cell(t, spans.get((r, j), 1)) for j, t in enumerate(row)) + '</w:tr>')
    return '<w:tbl><w:tblPr/>' + ''.join(out) + '</w:tbl>'


def para(text):
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def sv(x):
    return f'{x:.2E}'.replace('.', ',')


def make_report(path, halflives):
    d1 = [['nuklid', 'halverings-tid(år)', 'specifik aktivitet (Bq/g)', 'specifik aktivitet(Bq/mol)'] * 2]
    for i in range(0, len(D1), 2):
        row = []
        for n, t in ((D1[i], halflives[i]), (D1[i + 1], halflives[i + 1])):
            row += [n, sv(t), '1', '1']
        d1.append(row)
    d2 = [['', 'BWR40 MWd/kgU', 'PWR45 MWd/kgU', 'Ågesta', 'swap MOX', 'stav-skelett', 'total aktivitet'],
          ['antal', '60 000', '60 000', '60 000', '9 000', '9 000', '700', '9 000', '222', '217', '65', 'alla delar'],
          ['nuklid', 'bränsle-kutsar', 'konstr.mtrl', 'crud', 'bränsle-kutsar', 'konstr.mtrl', 'styr-stavar', 'crud', 'totalt', 'totalt', 'totalt', '']]
    for i, n in enumerate(NAMES):
        t = 1e12 * (i + 1) * 60
        d2.append([n, sv(t * 0.6), '0', '1,0E+05', sv(t * 0.3), '', '0', '0', sv(t * 0.03), sv(t * 0.03), sv(t * 0.04), sv(t)])
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + para('Detta ger 3 900 BWR-kapslar och 1 600 PWR-kapslar.')
           + para('Tabell D-1. Halveringstider och beräknad specifik aktivitet.') + docx_table(d1)
           + para('Tabell D-2. Totala radionuklidinventariet. Det redovisade aktivitetsinnehållet gäller år 2045.')
           + docx_table(d2, {(0, 1): 3, (0, 2): 4})
           + '</w:body></w:document>')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('word/document.xml', xml)


# --------------------------------------------------------------------- CDP
class Page:
    def __init__(self, ws):
        self.ws, self.n, self.pending, self.errors = ws, 0, {}, []

    @classmethod
    async def open(cls):
        req = urllib.request.Request(f'http://127.0.0.1:{CDP}/json/new?about:blank', method='PUT')
        t = json.loads(urllib.request.urlopen(req).read())
        p = cls(await websockets.connect(t['webSocketDebuggerUrl'], max_size=2 ** 28))
        p.target = t['id']
        p.reader = asyncio.create_task(p.read())
        for m in ('Page.enable', 'Runtime.enable', 'DOM.enable', 'Network.enable'):
            await p.send(m)
        await p.send('Network.setCacheDisabled', cacheDisabled=True)
        return p

    async def read(self):
        async for msg in self.ws:
            m = json.loads(msg)
            if m.get('id') in self.pending:
                self.pending.pop(m['id']).set_result(m)
            elif m.get('method') == 'Runtime.exceptionThrown':
                d = m['params']['exceptionDetails']
                self.errors.append(d.get('exception', {}).get('description') or d.get('text'))
            elif m.get('method') == 'Runtime.consoleAPICalled' and m['params']['type'] == 'error':
                self.errors.append(' '.join(str(a.get('value', a.get('description', ''))) for a in m['params']['args']))

    async def send(self, method, **params):
        self.n += 1
        fut = asyncio.get_event_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send(json.dumps({'id': self.n, 'method': method, 'params': params}))
        r = await asyncio.wait_for(fut, 120)
        if 'error' in r:
            raise RuntimeError(f'{method}: {r["error"]}')
        return r.get('result', {})

    async def ev(self, expr):
        r = await self.send('Runtime.evaluate', expression=expr, returnByValue=True, awaitPromise=True)
        if 'exceptionDetails' in r:
            raise RuntimeError(json.dumps(r['exceptionDetails'])[:600])
        return r['result'].get('value')

    async def wait(self, expr, timeout=30):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if await self.ev(f'!!({expr})'):
                    return True
            except RuntimeError:
                pass
            await asyncio.sleep(0.1)
        return False

    async def files(self, paths):
        doc = await self.send('DOM.getDocument', depth=-1)
        q = await self.send('DOM.querySelector', nodeId=doc['root']['nodeId'], selector='#invFile')
        await self.send('DOM.setFileInputFiles', files=[str(x) for x in paths], nodeId=q['nodeId'])

    async def change(self, sel, value):
        await self.ev(f'{{ const e = document.querySelector({json.dumps(sel)}); e.value = {json.dumps(value)}; '
                      f'e.dispatchEvent(new Event("input", {{bubbles: true}})); e.dispatchEvent(new Event("change", {{bubbles: true}})); }}')

    async def saved(self, count, timeout=60):
        """The files the page has saved, as (name, bytes), once there are `count` of them."""
        await self.wait(f'(window.__names || []).length >= {count}', timeout)
        names = await self.ev('window.__names || []')
        blobs = await self.ev('Promise.all((window.__saved || []).map(async b => { const a = new Uint8Array(await b.arrayBuffer()); '
                              'let s = ""; for (let i = 0; i < a.length; i += 8192) s += String.fromCharCode.apply(null, a.subarray(i, i + 8192)); return btoa(s); }))')
        return list(zip(names, (base64.b64decode(b) for b in blobs)))

    async def close(self):
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/close/{self.target}')
        except OSError:
            pass
        self.reader.cancel()
        await self.ws.close()


async def main():
    tmp = Path(tempfile.mkdtemp(prefix='inv-test-'))
    icrp = icrp107_halflives()
    canisters = make_inventory(tmp / INV)
    make_workbook(tmp / BOOK)
    # (Ni-59 as PSAR has it, so that its own half-lives can be told from ICRP 107's)
    make_report(tmp / REPORT, [76000 if n == 'Ni-59' else icrp[n] for n in D1])
    (tmp / 'broken.json').write_text('{"1": {"packing_date": "2040-01-01", "fuel_elements": {', encoding='utf-8')
    (tmp / 'notes.txt').write_text('nothing', encoding='utf-8')
    n_el = sum(len(c['fuel_elements']) for c in canisters.values())
    # everything in one zip archive, in a folder, with what macOS adds to one
    with zipfile.ZipFile(tmp / 'bundle.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('data/', '')
        for name in (INV, BOOK, REPORT):
            z.write(tmp / name, f'data/{name}')
        z.writestr('__MACOSX/data/._' + INV, 'resource fork')
        z.writestr('data/readme.txt', 'not data')
    (tmp / GZ).write_bytes(gzip.compress((tmp / INV).read_bytes()))

    p = await Page.open()
    try:
        await p.send('Emulation.setDeviceMetricsOverride', width=1400, height=1000, deviceScaleFactor=1, mobile=False)
        await p.send('Page.navigate', url=URL)
        await p.wait('typeof InventoryPage !== "undefined"')
        # the page keeps its views' settings: start from none, and light
        await p.ev('localStorage.removeItem("kvot.inventory"); localStorage.removeItem("kvot.inventory.full"); localStorage.setItem("kvot-theme", "light"); window.__before = true; location.reload()')
        await p.wait('typeof InventoryPage !== "undefined" && !window.__before')
        check('the page starts with its drop zone', await p.ev('!document.getElementById("invStart").hidden && !!document.getElementById("invDrop")'))
        check('seven tabs', await p.ev('[...document.querySelectorAll(".inv-tabs [role=tab]")].map(b => b.textContent).join("|")'),
              'Overview|Nuclides|Canisters|Over time|Compare with PSAR|Raw data|Help')
        check('Help explains the time setting', await p.ev('!!document.getElementById("help-time")'))

        # -- files that are not an inventory
        await p.files([tmp / 'broken.json', tmp / 'notes.txt'])
        await p.wait('!document.getElementById("invMsg").hidden')
        msg = await p.ev('document.getElementById("invMsgText").textContent')
        check('a broken JSON is reported', 'broken.json' in msg and 'part of the way' in msg, )
        check('a file of another kind is reported', 'notes.txt' in msg)
        check('and nothing is open', await p.ev('InventoryPage.state.inv === null'))

        # -- everything at once, in one zip archive
        await p.files([tmp / 'bundle.zip'])
        ready = await p.wait('InventoryPage.state.inv && InventoryPage.state.psar.workbook && InventoryPage.state.psar.report '
                             '&& !InventoryPage.state.busy.size', 60)
        check('the three files in a zip archive are read', ready)
        await asyncio.sleep(0.6)
        check('each shows as a chip', await p.ev('[...document.querySelectorAll(".inv-chip-role")].map(e => e.textContent).sort().join("|")'),
              'Inventory|PSAR report|PSAR workbook')
        check('the inventory named by its archive', await p.ev('InventoryPage.state.invFile.name'), f'bundle.zip › data/{INV}')
        check('the archive’s other files passed over quietly', await p.ev('document.getElementById("invMsg").hidden'))
        check('the error from before is gone', await p.ev('document.getElementById("invMsg").hidden'))
        tiles = await p.ev('[...document.querySelectorAll(".inv-tile")].map(t => t.innerText)')
        check('Overview: the canisters', tiles[0].split('\n')[1], '40')
        check('Overview: PSAR’s canisters', 'PSAR: 50' in tiles[0])
        check('Overview: the fuel elements and the planned ones', tiles[1].split('\n')[1].replace('\u202f', '') == str(n_el) and '40 planned' in tiles[1])
        check('Overview: three charts drawn', await p.ev('["invChartYears", "invChartReactors", "invChartHeat"].every(id => document.querySelector("#" + id + " .main-svg"))'))
        # planned fuel: one planned element in every canister of the made-up inventory
        check('Overview: the canisters holding planned elements', 'with planned elements' in tiles[0] and '40 with planned' in tiles[0].replace('\u202f', ''))
        check('Overview: the planned share of the elements, the activity and the heat', '(10.0 %)' in tiles[1] and all('in planned elements' in x for x in (tiles[4], tiles[5])))
        check('Overview: planned fuel hatched in the charts', await p.ev('["invChartYears", "invChartReactors", "invChartHeat"].every(id => document.getElementById(id).data.some(t => t.marker && t.marker.pattern && t.marker.pattern.shape === "/"))'))
        check('Fuel offered, all at first', await p.ev('!document.getElementById("invFuel").disabled && document.getElementById("invFuel").value === "all"'))
        await p.change('#invFuel', 'planned')
        await asyncio.sleep(0.6)
        tiles_p = await p.ev('[...document.querySelectorAll(".inv-tile")].map(t => t.innerText)')
        check('Fuel planned: every canister holds one, the 40 planned elements alone', (tiles_p[0].split('\n')[1], tiles_p[1].split('\n')[1]), ('40', '40'))
        check('Fuel planned: the subtitle says so, and that PSAR’s are all its fuel', 'planned elements only' in await p.ev('document.getElementById("invOverviewSub").textContent'))
        await p.change('#invFuel', 'discharged')
        await asyncio.sleep(0.6)
        tiles_d = await p.ev('[...document.querySelectorAll(".inv-tile")].map(t => t.innerText)')
        check('Fuel discharged: the others', tiles_d[1].split('\n')[1].replace('\u202f', ''), str(n_el - 40))
        await p.change('#invFuel', 'all')
        await asyncio.sleep(0.5)
        check('PSAR’s half-lives can be chosen', await p.ev('!document.querySelector("#invHalf option[value=report]").disabled'))
        own = await p.ev('''(() => { const r = InventoryPage.refs().find((x) => x.id === "workbook:average:all");
            const mol = InventoryPage.refValues(r, 2045, "mol").values.get("Ni-59");
            return mol * 6.02214076e23 * Math.LN2 / (76000 * 365.242196 * 86400) / r.values.get("Ni-59"); })()''')
        check('PSAR’s becquerels made moles with its own half-lives (Table D-1), ICRP 107’s chosen', abs(own - 1) < 1e-9)
        check('ENSDF on the site offered under Half-lives', bool(await p.wait('[...document.querySelectorAll("#invHalf option")].some(o => o.value.startsWith("ensdf:"))', 15)))

        await p.ev('''window.__saved = []; URL.createObjectURL = (b) => { window.__saved.push(b); return 'blob:t'; }; URL.revokeObjectURL = () => {};
                      HTMLAnchorElement.prototype.click = function () { (window.__names = window.__names || []).push(this.download); };''')
        n_saved = 0

        def sheets_of(data):
            return load_workbook(io.BytesIO(data))

        # -- a year
        await p.change('#invAt', 'year')
        await asyncio.sleep(0.3)
        check('a year from the last packing', await p.ev('document.getElementById("invYear").value'), '2050')
        await p.change('#invYear', '2030')
        await asyncio.sleep(0.3)
        check('a year before the last packing is marked', await p.ev('document.getElementById("invYear").getAttribute("aria-invalid")'), 'true')
        check('and the year in use stays', await p.ev('InventoryPage.state.settings.year'), '2050')
        await p.change('#invYear', '2060')
        await asyncio.sleep(0.6)
        check('the Overview in that year', 'in 2060' in (await p.ev('document.querySelector(".inv-tile:nth-child(5) .inv-tile-label").textContent')))
        await p.ev('document.querySelector("[data-on-click=\'inv:overviewExcel\']").click()')
        n_saved += 1
        name, data = (await p.saved(n_saved))[-1]
        wb = sheets_of(data)
        check('Overview: an Excel file of its numbers', (name.endswith('-2060-overview.xlsx'), wb.sheetnames), (True, ['Summary', 'Canisters each year', 'Elements by reactor', 'About']))
        summary = {r[0]: r for r in wb['Summary'].iter_rows(min_row=2, values_only=True)}
        check('Overview Excel: the canisters beside PSAR’s', (summary['Canisters'][1], summary['Canisters'][3]), (40, 50))
        about = dict(wb['About'].iter_rows(min_row=2, values_only=True))
        check('Overview Excel: what the numbers are for', about['Inventory'] == f'bundle.zip › data/{INV}' and about['Time'].startswith('1 January 2060') and about['PSAR workbook'] == BOOK)

        # -- nuclides, CSV and Excel
        await p.ev('InventoryPage.showTab("nuclides")')
        await asyncio.sleep(0.8)
        check('Nuclides: a row per nuclide', await p.ev('document.querySelectorAll("#invNucTable tbody tr").length'), len(NUCLIDES))
        check('Nuclides: the chart', await p.ev('!!document.querySelector("#invChartNuc .main-svg")'))
        check('Nuclides: each nuclide’s planned share', await p.ev('[...document.querySelectorAll("#invNucTable th")].some(t => t.textContent === "Planned") && /\\d/.test([...document.querySelectorAll("#invNucTable tbody tr")][0].children[[...document.querySelectorAll("#invNucTable th")].findIndex(t => t.textContent === "Planned")].textContent)'))
        check('Nuclides: PSAR’s average canister beside it', await p.ev('[...document.querySelectorAll("#invNucTable th")].some(t => /PSAR, 2060/.test(t.textContent))'))
        await p.change('#invUnit', 'Bq')
        await asyncio.sleep(0.5)
        check('the unit in the table', await p.ev('[...document.querySelectorAll("#invNucTable th")].some(t => t.textContent === "Bq per canister")'))
        await p.ev('document.querySelector("[data-on-click=\'inv:nucCsv\']").click()')
        n_saved += 1
        csv_name, csv_data = (await p.saved(n_saved))[-1]
        check('CSV is saved', csv_name.endswith('.csv'))
        csv = csv_data.decode('utf-8-sig')
        check('the CSV names its time and unit', '# Nuclides of the average canister, in 2060, Bq per canister' in csv)
        await p.ev('document.querySelector("[data-on-click=\'inv:nucExcel\']").click()')
        n_saved += 1
        wb = sheets_of((await p.saved(n_saved))[-1][1])
        rows = list(wb['Nuclides'].iter_rows(values_only=True))
        check('Nuclides Excel: the table, a row per nuclide', (wb.sheetnames, rows[0][:3], len(rows) - 1), (['Nuclides', 'About'], ('Nuclide', 'Half-life (y)', 'Bq per canister'), len(NUCLIDES)))
        # (a number of 2^52 or more is a whole number: it may come back as int)
        check('Nuclides Excel: numbers whole, shown as 0.000E+00', isinstance(rows[1][2], (int, float)) and rows[1][2] > 0 and wb['Nuclides']['C2'].number_format == '0.000E+00')
        # ENSDF's half-lives and chains, read when chosen
        await p.change('#invHalf', await p.ev('[...document.querySelectorAll("#invHalf option")].find(o => o.value.startsWith("ensdf:")).value'))
        check('ENSDF: read when chosen, then in use', bool(await p.wait('InventoryPage.state.settings.half.startsWith("ensdf:") && !InventoryPage.state.busy.size', 30)))
        ni59 = 'InventoryPage.system().T[InventoryPage.system().index.get("Ni-59")]'
        check('ENSDF: its own half-life for Ni-59, not ICRP 107’s', (await p.ev(ni59)) not in (0, 101000))
        await p.ev('document.querySelector("[data-on-click=\'inv:nucExcel\']").click()')
        n_saved += 1
        about = dict(list(sheets_of((await p.saved(n_saved))[-1][1])['About'].iter_rows(values_only=True))[1:])
        check('ENSDF: the About sheet names the release', about['Decay'].startswith('ENSDF') and 'ICRP Publication 107’s atomic masses' in about['Decay'])
        await p.change('#invHalf', 'icrp')
        await asyncio.sleep(0.5)
        check('ICRP 107 again', await p.ev(ni59), 101000)

        # -- canisters and elements
        await p.ev('InventoryPage.showTab("canisters")')
        await asyncio.sleep(0.8)
        check('Canisters: a row per canister', await p.ev('document.querySelectorAll("#invCanTable tbody tr").length'), 40)
        check('Canisters: those holding planned elements as rings, how many planned in the table', await p.ev('document.getElementById("invChartScatter").data.some(t => t.marker && t.marker.symbol === "circle-open" && /planned/.test(t.name)) && [...document.querySelectorAll("#invCanTable th")].some(t => t.textContent === "Planned")'))
        await p.ev('document.querySelector("[data-on-click=\'inv:canExcel\']").click()')
        n_saved += 1
        wb = sheets_of((await p.saved(n_saved))[-1][1])
        rows = list(wb['Canisters'].iter_rows(values_only=True))
        head = rows[0]
        check('Canisters Excel: every canister, with every nuclide', (len(rows) - 1, 'Cs-137 (Bq)' in head and 'Reactors' in head), (40, True))
        packed = rows[1][head.index('Packed')]
        check('Canisters Excel: the packing date as a date', hasattr(packed, 'year') and 2040 <= packed.year <= 2049)
        await p.change('#invLevel', 'el')
        await asyncio.sleep(1)
        check('Canisters: a row per element, the first 200', await p.ev('document.querySelectorAll("#invCanTable tbody tr").length'), min(200, n_el))
        await p.ev('document.querySelector("[data-on-click=\'inv:canMore\']").click()')
        await asyncio.sleep(0.6)
        check('Show more shows the rest', await p.ev('document.querySelectorAll("#invCanTable tbody tr").length'), n_el)
        await p.ev('document.querySelector("[data-on-click=\'inv:canExcel\']").click()')
        n_saved += 1
        wb = sheets_of((await p.saved(n_saved))[-1][1])
        rows = list(wb['Fuel elements'].iter_rows(values_only=True))
        check('Elements Excel: every element, the planned ones marked', (len(rows) - 1, sum(1 for r in rows[1:] if r[rows[0].index('Planned')] == 'yes')), (n_el, 40))
        check('an element name that is markup stays text', await p.ev(f'[...document.querySelectorAll("#invCanTable td")].some(td => td.textContent === {json.dumps(HOSTILE)}) && !window.__xss && !document.querySelector("#invCanTable img")'))
        await p.ev('document.querySelector("#invCanTable tbody tr").click()')
        await asyncio.sleep(0.8)
        check('a click opens its canister', await p.ev('!document.getElementById("invDetail").hidden && /^Canister \\d+$/.test(document.getElementById("invDetailTitle").textContent)'))
        check('with its elements', await p.ev('document.querySelectorAll("#invDetailElements tbody tr").length') in (4, 12))

        # -- over time
        await p.ev('InventoryPage.showTab("time")')
        await asyncio.sleep(0.8)
        n_tr = await p.ev('document.getElementById("invChartTime").data.length')
        check('Over time: eight nuclides, their total, and the planned part of it dotted', (n_tr, await p.ev('document.getElementById("invChartTime").data.some(t => t.line && t.line.dash === "dot" && /planned/.test(t.name))')), (10, True))
        await p.ev('{ const s = document.getElementById("invTimeRef"); s.value = s.options[1].value; s.dispatchEvent(new Event("change", {bubbles: true})); }')
        await asyncio.sleep(0.8)
        check('Over time: PSAR beside it', await p.ev('document.getElementById("invChartTime").data.some(t => t.line && t.line.dash === "dash")'))
        await p.ev('document.querySelector("[data-on-click=\'inv:timeExcel\']").click()')
        n_saved += 1
        wb = sheets_of((await p.saved(n_saved))[-1][1])
        rows = list(wb['Over time'].iter_rows(values_only=True))
        check('Over time Excel: every nuclide at every time, the planned part, and PSAR', (wb.sheetnames, len(rows[0]) - 4, len(rows) - 1, rows[0][3].startswith('Of it in planned elements')), (['Over time', 'PSAR beside it', 'About'], len(NUCLIDES), 145, True))
        choices = 'JSON.stringify([...document.getElementById("invTimeRef").options].slice(1).map(o => o.textContent))'
        check('Over time: beside the average canister, PSAR’s average canisters, each named by its document',
              json.loads(await p.ev(choices)), ['PSAR average canister — workbook, Totalt radionuklidinventarium (2045)'])
        await p.change('#invType', await p.ev('[...document.getElementById("invType").options].find(o => o.textContent === "BWR").value'))
        await asyncio.sleep(0.8)
        bwr = json.loads(await p.ev(choices))
        check('Over time: beside the average BWR canister, PSAR’s, the same document’s kept', (len(bwr), all(x.startswith('PSAR average BWR canister — ') for x in bwr),
              await p.ev('document.getElementById("invTimeRef").value')), (1, True, 'workbook:average:BWR'))
        check('Over time: PSAR’s brought to the year shown, said', await p.ev('/given for 1 January 2045 and brought to 2060 by decay and ingrowth/.test(document.getElementById("invTimeNote").textContent)'))
        await p.change('#invType', '-1')
        await p.change('#invTimeOf', 'total')
        await asyncio.sleep(0.8)
        check('Over time: beside all canisters together, PSAR’s totals, not an average', all(x.startswith('PSAR, all its fuel — ') for x in json.loads(await p.ev(choices))))
        await p.change('#invTimeOf', 'average')
        await asyncio.sleep(0.5)

        # -- compare with PSAR
        await p.ev('InventoryPage.showTab("psar")')
        await asyncio.sleep(1)
        check('the ratio chart in 2060, against the workbook’s average canister', await p.ev('!document.getElementById("invChartRatio").hidden && /Totalt/.test(document.getElementById("invRef").selectedOptions[0].textContent)'))
        check('Compare: PSAR’s moles from its own half-lives, said', 'its own half-lives (its report’s Table D-1)' in await p.ev('document.getElementById("invPsarHow").textContent'))
        cats = await p.ev('[...document.querySelectorAll("#invCatTable tbody tr td:first-child")].map(t => t.textContent)')
        check('totals by kind of fuel', all(k in cats for k in ('BWR', 'PWR', 'Ågesta', 'Swap MOX', 'Rod skeletons')), )
        check('elements by reactor, codes read as names', await p.ev('[...document.querySelectorAll("#invReactorTable td")].some(t => t.textContent === "Ringhals 4")'))
        await p.ev('document.querySelector("[data-on-click=\'inv:psarExcel\']").click()')
        n_saved += 1
        wb = sheets_of((await p.saved(n_saved))[-1][1])
        check('Compare Excel: a sheet per table', wb.sheetnames, ['Average canister', 'By kind of fuel', 'By reactor', 'Canisters', 'Canisters each year', 'About'])
        # (the average over all canisters has no spread of its own: its amounts are checked)
        check('Compare Excel: amounts as 0.000E+00', (wb['Average canister']['B2'].number_format, wb['Average canister']['C2'].number_format), ('0.000E+00', '0.000E+00'))
        await p.change('#invAt', 'packed')
        await asyncio.sleep(0.6)
        check('as packed, no ratio: a button for one year instead', await p.ev('document.getElementById("invChartRatio").hidden && /Show both in 2050/.test(document.getElementById("invPsarTime").textContent)'))
        await p.ev('document.querySelector("#invPsarTime button").click()')
        await asyncio.sleep(0.8)
        check('the button sets that year', await p.ev('InventoryPage.state.settings.at === "year" && InventoryPage.state.settings.year === "2050" && !document.getElementById("invChartRatio").hidden'))

        # -- raw data
        await p.change('#invAt', 'packed')
        await p.ev('InventoryPage.showTab("raw")')
        await p.change('#invRawQty', 'mol')
        await asyncio.sleep(0.8)
        count = 'document.getElementById("invRawCount").textContent'
        said = lambda text, start: text[:len(start)]  # noqa: E731  (the start of a line, to compare)
        start = f'{n_el} fuel elements × 48 columns'
        check('Raw data: every element as packed, a column for each part and nuclide', said(await p.ev(count), start), start)
        check('Raw data: the first rows shown', await p.ev('document.querySelectorAll("#invRawPreview tbody tr").length'), 10)
        await p.ev('document.querySelector("[data-on-click=\'inv:rawExcel\']").click()')
        n_saved += 1
        name, data = (await p.saved(n_saved, 120))[-1]
        wb = sheets_of(data)
        rows = list(wb['Fuel elements'].iter_rows(values_only=True))
        head = rows[0]
        check('Raw Excel: a sheet of every element, and one saying what it is', (wb.sheetnames, len(rows) - 1, name.endswith('-raw-elements-packed-mol.xlsx')), (['Fuel elements', 'About'], n_el, True))
        check('Raw Excel: the fields, then each part and nuclide', head[:11], ('Element', 'Canister', 'Packed', 'Reactor', 'Reactor type', 'Fuel type', 'Planned',
                                                                         'Decay heat (W), in the file', 'Declared heat (W), in the file', 'Am-241 fuel (mol)', 'C-14 fuel (mol)'))
        row = next(r for r in rows if r[0] == 'E00101')
        check('Raw Excel: as packed, the file’s own value', row[head.index('Cs-137 structural material (mol)')], canisters['101']['fuel_elements']['E00101']['structural_material']['cs137'])
        about = dict(list(wb['About'].iter_rows(values_only=True))[1:])
        check('Raw Excel: what the values are', about['Values'].startswith('moles; a column for each part and nuclide') and about['Time'].startswith('as packed'))
        # canisters: Forsmark 2's elements, not the planned ones, Cs-137 of every part summed, as CSV
        await p.ev('document.querySelector("input[name=invRawLevel][value=can]").click()')
        await p.change('#invRawApart', 'sum')
        await p.change('#invFuel', 'discharged')
        await p.change('#invRawNuc', 'picked')
        await p.ev('document.querySelector("[data-on-click=\'inv:rawNone\'][data-list=invRawNucList]").click()')
        await p.ev('[...document.querySelectorAll("#invRawNucList input")].find(i => i.parentElement.textContent.trim() === "Cs-137").click()')
        await p.ev('document.querySelector("[data-on-click=\'inv:rawNone\'][data-list=invRawReactorList]").click()')
        await p.ev('[...document.querySelectorAll("#invRawReactorList input")].find(i => i.parentElement.textContent.includes("Forsmark 2")).click()')
        await asyncio.sleep(0.8)
        check('Raw data: the canisters holding elements chosen', said(await p.ev(count), '30 canisters (328 elements)'), '30 canisters (328 elements)')
        await p.ev('document.querySelector("[data-on-click=\'inv:rawCsv\']").click()')
        n_saved += 1
        name, data = (await p.saved(n_saved, 120))[-1]
        rows = list(csvlib.reader([line for line in data.decode('utf-8-sig').split('\r\n') if line and not line.startswith('#')]))
        check('Raw CSV: a canister a row, the elements chosen summed', (len(rows) - 1, rows[0][:6], rows[0][-1]),
              (30, ['Canister', 'Type', 'Packed', 'Elements chosen', 'Planned among them', 'Elements'], 'Cs-137 (mol)'))
        r101 = next(r for r in rows[1:] if r[0] == '101')
        want = sum(sum(el[part]['cs137'] for part in ('fuel', 'crud', 'structural_material'))
                   for nm, el in canisters['101']['fuel_elements'].items() if el['reactor'] == 'Forsmark 2' and not nm.startswith('PLAN'))
        check('Raw CSV: Forsmark 2’s elements, not the planned, Cs-137 of every part', (r101[3], abs(float(r101[-1]) / want - 1) < 1e-12), ('10', True))
        await p.ev('document.querySelector("[data-on-click=\'inv:rawNone\'][data-list=invRawReactorList]").click()')
        await asyncio.sleep(0.5)
        check('Raw data: nothing chosen, nothing to save', await p.ev(f'{count} === "No element is chosen." && document.querySelector("[data-on-click=\'inv:rawExcel\']").disabled'))
        await p.ev('document.querySelector("[data-on-click=\'inv:rawAll\'][data-list=invRawReactorList]").click()')
        await p.change('#invRawFrom', '2045')
        await asyncio.sleep(0.5)
        check('Raw data: canisters packed from 2045, of every reactor again', said(await p.ev(count), '20 canisters'), '20 canisters')
        await p.change('#invRawFrom', '20x5')
        await asyncio.sleep(0.5)
        check('Raw data: no year marked, the one before kept', await p.ev('document.getElementById("invRawFrom").getAttribute("aria-invalid") === "true"') and (await p.ev(count)).startswith('20 canisters'))
        await p.change('#invFuel', 'all')
        await asyncio.sleep(0.4)

        # -- a drop, the dark theme, a phone
        for kind in ('dragEnter', 'dragOver', 'drop'):
            await p.send('Input.dispatchDragEvent', type=kind, x=500, y=400, data={'items': [], 'files': [str(tmp / GZ)], 'dragOperationsMask': 1})
        check('a dropped, gzipped inventory is read', await p.wait(f'InventoryPage.state.invFile && InventoryPage.state.invFile.name === {json.dumps(GZ)} && !InventoryPage.state.reading', 30))
        check('the same as from the archive', await p.ev('InventoryPage.state.inv.nCan === 40 && InventoryPage.state.inv.nEl === ' + str(n_el) + ' && document.querySelectorAll(".inv-chip").length === 3'))
        await p.ev('document.documentElement.setAttribute("data-theme", "dark"); document.documentElement.dispatchEvent(new CustomEvent("kvot-theme-change", {detail: {theme: "dark"}})); InventoryPage.showTab("overview")')
        await asyncio.sleep(1)
        check('dark: the charts take the dark ink', await p.ev('getComputedStyle(document.querySelector("#invChartYears .xtick text")).fill') == 'rgb(176, 185, 195)')
        await p.send('Emulation.setDeviceMetricsOverride', width=390, height=664, deviceScaleFactor=2, mobile=True)
        await p.send('Emulation.setTouchEmulationEnabled', enabled=True)
        await asyncio.sleep(0.8)
        # (a page too wide for the phone widens the layout itself, innerWidth too: measure against 390)
        wide = []
        for tab in ('overview', 'nuclides', 'canisters', 'time', 'psar', 'raw', 'help'):
            await p.ev(f'InventoryPage.showTab("{tab}")')
            await asyncio.sleep(0.6)
            if not await p.ev(f'document.documentElement.scrollWidth <= 390 && document.getElementById("invPane-{tab}").scrollWidth <= 390'):
                what = await p.ev(f'''[...document.querySelectorAll("#invPane-{tab} *, .inv-bar *")].filter(e => !e.closest(".inv-table-wrap")
                                  && e.getBoundingClientRect().right > 391).map(e => e.tagName + "#" + e.id + "." + e.className).slice(0, 3).join(", ")''')
                wide.append(f'{tab}: {what}')
        check('phone: no sideways scroll on any tab', wide, [])
        check('phone: fields of 16 px', await p.ev('getComputedStyle(document.getElementById("invUnit")).fontSize'), '16px')
        # -- the full window: no site header or footer, the mark and the theme switch in the tab row
        await p.send('Emulation.clearDeviceMetricsOverride')
        await p.send('Emulation.setTouchEmulationEnabled', enabled=False)
        await p.ev('InventoryPage.showTab("overview")')
        check('not in the full window at first', await p.ev('!document.documentElement.classList.contains("inv-full") && getComputedStyle(document.querySelector(".inv-homelink")).display === "none"'))
        await p.ev('document.getElementById("invFull").click()')
        await asyncio.sleep(0.5)
        check('full window: no site header or footer', await p.ev('document.documentElement.classList.contains("inv-full") && getComputedStyle(document.querySelector("body > header")).display === "none" && getComputedStyle(document.querySelector("body > footer")).display === "none"'))
        check('full window: the page from the top of the window to its bottom', await p.ev('(() => { const r = document.getElementById("inv").getBoundingClientRect(); return Math.abs(r.top) < 1 && Math.abs(r.bottom - innerHeight) < 2; })()'))
        check('full window: the kvot mark (a new tab) and the theme switch in the row, the button pressed', await p.ev('getComputedStyle(document.querySelector(".inv-homelink")).display !== "none" && document.querySelector(".inv-homelink").target === "_blank" && getComputedStyle(document.querySelector(".inv-tabend .theme-toggle")).display !== "none" && document.getElementById("invFull").getAttribute("aria-pressed") === "true"'))
        check('full window: kept for the next visit', await p.ev('localStorage.getItem("kvot.inventory.full")'), '1')
        await p.ev('document.querySelector("[data-info-key=\'set:half\'] button, [data-info=\'set:half\']").click()')
        await asyncio.sleep(0.4)
        check('full window: an (i) panel the height of the window', await p.ev('(() => { const el = document.getElementById("kvot-info-panel"); if (!el) return false; const r = el.getBoundingClientRect(); return r.top < 2 && Math.abs(r.bottom - innerHeight) < 2; })()'))
        await p.ev('document.querySelector("#kvot-info-panel .info-panel-close") && document.querySelector("#kvot-info-panel .info-panel-close").click()')
        before = await p.ev('document.documentElement.getAttribute("data-theme")')
        await p.ev('document.querySelector(".inv-tabend .theme-toggle").click()')
        await asyncio.sleep(0.3)
        check('full window: its switch changes the theme', await p.ev('document.documentElement.getAttribute("data-theme")'), 'light' if before == 'dark' else 'dark')
        await p.ev('document.querySelector(".inv-tabend .theme-toggle").click()')
        await p.ev('document.getElementById("invFull").click()')
        await asyncio.sleep(0.4)
        check('and back: the header and footer, the button not pressed, kept', await p.ev('!document.documentElement.classList.contains("inv-full") && getComputedStyle(document.querySelector("body > header")).display !== "none" && document.getElementById("invFull").getAttribute("aria-pressed") === "false" && localStorage.getItem("kvot.inventory.full") === "0"'))
        await p.ev('localStorage.removeItem("kvot.inventory.full")')
        check('no errors on the page', p.errors, [])
    finally:
        await p.close()
    print(f'\n{checks - len(failures)} of {checks} checks passed.')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    asyncio.run(main())
