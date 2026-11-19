"""End-to-end checks of skb_qa_summary.html with folders of workbooks.

A tree of small workbooks is built in a temporary folder, then dropped on the
page, chosen with its folder picker and dropped again, each through Chrome's
own drag and file-chooser machinery (CDP), so the page gets trusted events
and real directory entries. Checked:

- every QC row of every workbook in the tree, with its folder, file, sheet
  and Excel row (a sheet whose header is in row 3 included);
- .xlsm, .xls and a QA-headed sheet are read; Excel's "~$" owner files, "._"
  copies, hidden folders and other files are passed over;
- two workbooks of one name in two folders are two files;
- the Folders filter lists the tree and a folder takes its subfolders along;
- the CSV export starts with the Folder column;
- a folder read again replaces its rows instead of doubling them;
- a workbook added on its own shows no folder;
- a workbook that cannot be read, a folder with no workbook, Stop and
  Clear all in the middle of a read;
- a drop outside the drop zone is taken, and so is a dropped item with no
  entry (a mail attachment, say);
- "Choose a folder", clicked or by Enter, opens the folder chooser and
  nothing else;
- calculation cases from TOML files: a config folder alone, then with its
  Excel folder; each case's input set, data files, workbooks and QC; the case
  filter; a description that carries markup and a script; broken TOML;
- input-set exports: each value traced to its QC row (by row, or along a time
  series whose rows the export gives wrongly), raw data, workbooks not read,
  sheets without QC columns and rows no longer there; the Input set filter;
  the Files view under a filter; the same with the page reading without workers;
- the SheetJS loaded is the vendored copy, 0.20.2 or later;
- no sideways scroll at 1280 px or on a 375 px phone, whose fields are 16 px
  (smaller ones make iOS zoom), and the summary tiles read in the dark theme.

Serve the repository root and start headless Chrome, by default on ports 8765
and 9222 (QC_HTTP_PORT and QC_CDP_PORT choose others):

    python3 -m http.server 8765
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \\
        --remote-debugging-port=9222 --user-data-dir=<fresh dir> about:blank
    python3 resources/tests/skb_qa_summary/test-ui.py

Needs openpyxl and websockets. Exit status is 0 when every check passes.
"""
import asyncio
import base64
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request

import websockets
from openpyxl import Workbook

HTTP = int(os.environ.get('QC_HTTP_PORT', '8765'))
CDP = int(os.environ.get('QC_CDP_PORT', '9222'))
URL = f'http://127.0.0.1:{HTTP}/skb_qa_summary.html'

ROOT = 'QC granskning'
QC_HEAD = ['ID', 'Value', 'QC reviewer', 'QC comment', 'QC status']


def book(path, sheets):
    """A workbook at path; sheets maps a sheet name to its rows, top first (None: an empty row)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r, row in enumerate(rows, 1):
            for c, value in enumerate(row or [], 1):
                if value is not None:
                    ws.cell(row=r, column=c, value=value)
    wb.save(path)


def junk(path, data=b'not a workbook at all'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


def build_tree(base, xls_bytes):
    """The fixture folders, and the rows the page must find in ROOT."""
    root = os.path.join(base, ROOT)
    data_sheet = [['a', 'b', 'c']] + [[i, i * 2, i * 3] for i in range(50)]
    book(os.path.join(root, 'PSAR 2024', 'params.xlsx'), {
        'Params': [QC_HEAD] + [['p1', 1, 'revA', '', 'OK-PSAR']] * 3 + [['p2', 2, 'revB', 'check unit', 'Preliminary']] * 2,
        'Data': data_sheet,
    })
    book(os.path.join(root, 'PSAR 2025', 'params.xlsx'), {
        'Data': data_sheet,
        'Params': [QC_HEAD, ['p1', 1, 'revA', '', 'OK-FSAR'], ['p3', 3, 'revC', '', 'In review'], ['p3', 3, 'revD', '', 'OK-PSAR']],
    })
    book(os.path.join(root, 'PSAR 2025', 'äldre', 'legacy.xlsm'), {
        'QA': [['ID', 'QA reviewer', 'QA comment', 'QA status'], ['p4', 'revD', 'old heading', 'OK-UPSAR']],
    })
    # The header in row 3, rows 1 and 2 empty: the sheet's range starts there.
    book(os.path.join(root, 'PSAR 2025', 'offset.xlsx'), {
        'Lower': [None, None, ['ID', 'QC reviewer', 'QC comment', 'QC status'],
                  ['p6', 'revA', '', 'OK-PSAR'], ['p7', 'revA', '', 'Preliminary']],
    })
    junk(os.path.join(root, 'PSAR 2025', 'gammal.xls'), xls_bytes)
    book(os.path.join(root, 'notes.xlsx'), {'Notes': [['Topic', 'Text'], ['x', 'y']]})
    junk(os.path.join(root, '~$params.xlsx'), b'\x05owner' + b'\x00' * 150)
    junk(os.path.join(root, '._notes.xlsx'), b'\x00\x05\x16\x07' + b'\x00' * 60)
    book(os.path.join(root, '.hidden', 'secret.xlsx'), {'Params': [QC_HEAD, ['p99', 0, 'revZ', '', 'OK-PSAR']]})
    junk(os.path.join(root, 'readme.txt'), b'plain text')

    book(os.path.join(base, 'Trasig', 'ok.xlsx'), {'Params': [QC_HEAD, ['p8', 8, 'revA', '', 'OK-PSAR']]})
    # A workbook cut short. Plain text would not do: SheetJS reads it as a one-cell sheet.
    with open(os.path.join(base, 'Trasig', 'ok.xlsx'), 'rb') as f:
        junk(os.path.join(base, 'Trasig', 'broken.xlsx'), f.read()[:2000])
    junk(os.path.join(base, 'Tom', 'readme.txt'), b'nothing here')
    book(os.path.join(base, 'Lös', 'params.xlsx'), {'Params': [QC_HEAD, ['p1', 1, 'revE', '', 'OK-FSAR']]})
    for k in range(1, 13):
        book(os.path.join(base, 'Många', f'book{k:02}.xlsx'), {'Params': [QC_HEAD, [f'm{k:02}', k, 'revM', '', 'OK-PSAR']]})

    # In the order the page reads them: a folder at a time, "äldre" sorting as "aldre".
    f24, f25 = f'{ROOT}/PSAR 2024', f'{ROOT}/PSAR 2025'
    expected = (
        [(f24, 'params.xlsx', 'Params', r, 'p1', 'revA', 'OK-PSAR', '') for r in (2, 3, 4)]
        + [(f24, 'params.xlsx', 'Params', r, 'p2', 'revB', 'Preliminary', 'check unit') for r in (5, 6)]
        + [(f'{f25}/äldre', 'legacy.xlsm', 'QA', 2, 'p4', 'revD', 'OK-UPSAR', 'old heading')]
        + [(f25, 'gammal.xls', 'Gammal', 2, 'p5', 'revB', 'OK-PSAR', 'old format')]
        + [(f25, 'offset.xlsx', 'Lower', 4, 'p6', 'revA', 'OK-PSAR', ''), (f25, 'offset.xlsx', 'Lower', 5, 'p7', 'revA', 'Preliminary', '')]
        + [(f25, 'params.xlsx', 'Params', 2, 'p1', 'revA', 'OK-FSAR', '')]
        + [(f25, 'params.xlsx', 'Params', 3, 'p3', 'revC', 'In review', ''), (f25, 'params.xlsx', 'Params', 4, 'p3', 'revD', 'OK-PSAR', '')]
    )
    return expected


CC_HEAD = ['ID', 'QC reviewer', 'QC comment', 'QC status']
# A description with markup the page keeps (<b>) and markup that must never run.
HOSTILE_INFO = 'The <b style="color:red;">base</b> case <script>window.__pwned = 1</script><img src=x onerror="window.__pwned = 2">'


def build_config(base):
    """A configuration of three calculation cases in SFR/config, and the workbooks of its data files in SFR/excel."""
    config = os.path.join(base, 'SFR', 'config')
    os.makedirs(config, exist_ok=True)
    files = {
        'link.toml': "info = 'linked files'\n[base]\n    files = ['alpha', 'beta', 'gamma']\n"
                     "[variant]\n    init_file = 'base'\n    skip = ['beta']\n    add = ['delta']\n",
        'data.toml': "[alpha]\n    path = 'base_case'\n[beta]\n    path = 'base_case'\n    sheet_names = 'nearfield'\n"
                     "[gamma]\n    path = 'other'\n    raw_path = 'HYDRO'\n    flows = ['Inflow', 'Outflow']\n[delta]\n    path = 'other'\n",
        'CC001.toml': f"info = '{HOSTILE_INFO}'\nrepositories = 'all'\nparameter_files = 'base.h5'\n"
                      "[nearfield]\nendpoints = 'full'\n[biosphere]\nendpoints = 'full'\n",
        'CC002.toml': 'info = """\nThe variant case,\nover two lines.\n"""\nrepositories = [\'Silo\', \'1BTF\']\n'
                      "parameter_files = 'variant.h5'\nbase_cc = 'CC001'\nn_iter = 100\n[farfield]\nsource_cc = 'CC001'\n"
                      "[solver]\nt_eval = [" + ', '.join(str(t) for t in range(0, 1001, 10)) + "]\n",
        'CC003.toml': "info = 'a case on an old parameter file'\nparameter_files = 'Legacy.h5'\n",
        'broken.toml': 'this is = = not toml\n',
    }
    for name, text in files.items():
        with open(os.path.join(config, name), 'w', encoding='utf-8') as f:
            f.write(text)
    excel = os.path.join(base, 'SFR', 'excel')
    book(os.path.join(excel, 'base_case', 'alpha.xlsx'), {'Params': [CC_HEAD, ['a1', 'revA', '', 'OK-FSAR'], ['a2', 'revB', '', 'Preliminary']]})
    # data.toml takes only the sheet 'nearfield' of beta: b9, on another sheet, is in no case.
    book(os.path.join(excel, 'base_case', 'beta.xlsx'), {'nearfield': [CC_HEAD, ['b1', 'revA', '', 'OK-PSAR']],
                                                         'extra': [CC_HEAD, ['b9', 'revC', '', 'Preliminary']]})
    book(os.path.join(excel, 'other', 'delta.xlsx'), {'Params': [CC_HEAD, ['d1', 'revA', '', 'OK-PSAR']]})
    return config, excel


EXPORT_HEAD = ['id', 'time', 'value', 'type', 'linked_file', 'file', 'sheet', 'row', 'reference', 'sample_mean']


def build_exports(base):
    """An Excel folder and a QC folder of two input-set exports, as the calculation-case code writes them.

    set1 holds a value traced by its row, a time series whose rows the export
    gives wrongly (as it does for a lookup table), a value from raw data, one
    with no source, one from a workbook not read, one from a sheet without QC
    columns and one whose row is no longer in its workbook. set2 holds one
    value of the same workbook."""
    root = os.path.join(base, 'Exp')
    excel = os.path.join(root, 'excel')
    book(os.path.join(excel, 'base_case', 'alpha.xlsx'), {'nearfield': [
        ['ID', 'Time', 'Value', 'QC reviewer', 'QC comment', 'QC status'],
        ['a.one', None, 1, 'revA', '', 'OK-PSAR'],
        ['a.ts', 0, 1, 'revB', '', 'Preliminary'], ['a.ts', 100, 2, 'revB', '', 'Preliminary'], ['a.ts', 200, 3, 'revB', '', 'Preliminary'],
        ['a.two', None, 5, 'revC', '', 'In review'],
    ]})
    book(os.path.join(excel, 'base_case', 'noqc.xlsx'), {'Sheet1': [['ID', 'Value', 'revX', 'PSAR', 'OK-PSAR'], ['n.one', 1, 'x', 'y', 'z']]})
    src = '/Users/someone/data/excel/base_case/alpha.xlsx'
    rows1 = [
        ['nearfield.a.one', None, 1, 'const', '../base_case/alpha_v3.h5', src, 'nearfield', 2],
        # The time series: the export gives rows 2, 3 and 4, its own rows are 3, 4 and 5.
        ['nearfield.a.ts', 0, 1, 'const', '../base_case/alpha_v3.h5', src, 'nearfield', 2],
        ['nearfield.a.ts', 100, 2, 'const', '../base_case/alpha_v3.h5', src, 'nearfield', 3],
        ['nearfield.a.ts', 200, 3, 'const', '../base_case/alpha_v3.h5', src, 'nearfield', 4],
        ['nearfield.a.two', None, 5, 'const', '../base_case/alpha_v3.h5', src, 'nearfield', 6],
        ['nearfield.flow', None, 7, 'raw', '../hydro/NCC1_v1.h5', '/Volumes/raw/HYDRO/NCC1/flow.csv', '', None],
        ['nearfield.computed', None, 8, 'const', '../hydro/NCC1_v1.h5', None, None, None],
        ['nearfield.gone', None, 9, 'const', '../other/gone_v1.h5', '/Users/someone/data/excel/other/gone.xlsx', 'nearfield', 2],
        ['Sheet1.n.one', None, 1, 'const', '../base_case/noqc_v1.h5', '/Users/someone/data/excel/base_case/noqc.xlsx', 'Sheet1', 2],
        ['nearfield.a.removed', None, 9, 'const', '../base_case/alpha_v3.h5', src, 'nearfield', 99],
    ]
    book(os.path.join(root, 'qc', 'set1.xlsx'), {'Data': [EXPORT_HEAD] + [r + [None, None] for r in rows1]})
    book(os.path.join(root, 'qc', 'set2.xlsx'), {'Data': [EXPORT_HEAD, ['nearfield.a.two', None, 5, 'const', '../base_case/alpha_v3.h5', src, 'nearfield', 6, None, None]]})
    return root


class Page:
    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.events = []
        self.errors = []

    async def send(self, method, params=None):
        self.n += 1
        await self.ws.send(json.dumps({'id': self.n, 'method': method, 'params': params or {}}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get('id') == self.n:
                if 'error' in r:
                    raise RuntimeError(f'{method}: {r["error"]}')
                return r.get('result', {})
            self.note(r)

    def note(self, r):
        m = r.get('method')
        if m == 'Runtime.exceptionThrown':
            d = r['params']['exceptionDetails']
            self.errors.append((d.get('exception', {}).get('description') or d.get('text', ''))[:300])
        elif m == 'Runtime.consoleAPICalled' and r['params']['type'] == 'error':
            self.errors.append(' '.join(str(a.get('value', a.get('description', ''))) for a in r['params']['args'])[:300])
        elif m:
            self.events.append(r)

    async def ev(self, expr):
        r = await self.send('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        if 'exceptionDetails' in r:
            raise RuntimeError(f'{expr[:80]}: {r["exceptionDetails"].get("exception", {}).get("description", r["exceptionDetails"])}')
        return r['result'].get('value')

    async def read_after(self, action):
        """Run action, which makes the page queue a read, and wait for it.

        The page's queue is a promise each read replaces, so a new one proves
        the read was queued, and awaiting the queue until it stops changing
        waits for it and anything queued behind it."""
        await self.ev('window.__queue = queue')
        await action()
        for _ in range(200):
            if await self.ev('queue !== window.__queue'):
                break
            await asyncio.sleep(0.02)
        else:
            raise TimeoutError('the page queued no read')
        await asyncio.wait_for(self.ev('(async () => { let q; do { q = queue; await q; } while (q !== queue); })()'), 120)

    async def drop(self, paths, x=200, y=150):
        async def act():
            data = {'items': [], 'files': paths, 'dragOperationsMask': 1}
            for kind in ('dragEnter', 'dragOver', 'drop'):
                await self.send('Input.dispatchDragEvent', {'type': kind, 'x': x, 'y': y, 'data': data})
        await self.read_after(act)

    async def choose(self, selector, paths):
        async def act():
            doc = await self.send('DOM.getDocument')
            node = await self.send('DOM.querySelector', {'nodeId': doc['root']['nodeId'], 'selector': selector})
            await self.send('DOM.setFileInputFiles', {'nodeId': node['nodeId'], 'files': paths})
        await self.read_after(act)


ROWS = 'rows.map(r => [r.folder, r.file, r.sheet, r.row, String(r.id), String(r.reviewer), String(r.status), String(r.comment)])'
STATUS = "({text: $('status-text').textContent, error: $('status').classList.contains('error'), shown: $('status').classList.contains('show'),"\
    " files: [...$('status-files').querySelectorAll('li')].map(li => li.textContent), listed: !$('status-files').hidden,"\
    " stop: !$('stop-btn').hidden, busy: $('status').hasAttribute('aria-busy')})"
OPTIONS = "(key => facetOptions(key).map(o => key === 'folder' ? [o.value, o.label, o.depth || 0] : [o.value, o.label, o.sub || '']))"


async def main():
    failures = []

    def check(ok, what, detail=''):
        print(('ok    ' if ok else 'FAIL  ') + what + ('' if ok else f'\n      {detail}'))
        if not ok:
            failures.append(what)

    version = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    browser = await websockets.connect(version['webSocketDebuggerUrl'], max_size=50_000_000)
    await browser.send(json.dumps({'id': 1, 'method': 'Target.createTarget', 'params': {'url': 'about:blank'}}))
    target = json.loads(await browser.recv())['result']['targetId']
    listing = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/list'))
    ws = await websockets.connect([t for t in listing if t['id'] == target][0]['webSocketDebuggerUrl'], max_size=50_000_000)
    page = Page(ws)
    base = tempfile.mkdtemp(prefix='skb-qc-test-')
    try:
        for domain in ('Runtime', 'Page', 'DOM', 'Network'):
            await page.send(f'{domain}.enable')
        await page.send('Network.setCacheDisabled', {'cacheDisabled': True})
        await page.send('Page.setInterceptFileChooserDialog', {'enabled': True})
        await page.send('Emulation.setDeviceMetricsOverride', {'width': 1280, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
        await page.send('Page.navigate', {'url': URL})
        for _ in range(200):
            if await page.ev("typeof XLSX !== 'undefined' && document.readyState === 'complete'"):
                break
            await asyncio.sleep(0.05)

        # The SheetJS the page loads is its own copy, and not one with the two published vulnerabilities.
        ver = await page.ev('XLSX.version')
        src = await page.ev("[...document.scripts].map(e => e.getAttribute('src') || '').find(x => /xlsx/.test(x)) || ''")
        check(f'vendors/js/xlsx-{ver}.full.min.js' in src and tuple(int(x) for x in ver.split('.')) >= (0, 20, 2),
              'SheetJS is the vendored copy, 0.20.2 or later (CVE-2023-30533, CVE-2024-22363)', [ver, src])

        # An .xls (BIFF8) workbook, written by the page's own SheetJS.
        xls = base64.b64decode(await page.ev(
            "(() => { const wb = XLSX.utils.book_new();"
            " XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([['ID', 'QC reviewer', 'QC comment', 'QC status'],"
            " ['p5', 'revB', 'old format', 'OK-PSAR']]), 'Gammal');"
            " return XLSX.write(wb, {bookType: 'biff8', type: 'base64'}); })()"))
        expected = build_tree(base, xls)
        root = os.path.join(base, ROOT)

        # 1. The folder dropped on the zone.
        check(await page.ev("$('workspace').classList.contains('show')") is False, 'the workspace is hidden before anything is read')
        await page.drop([root])
        got = [tuple(r) for r in await page.ev(ROWS)]
        check(got == expected, 'a dropped folder gives every QC row, with its folder, file, sheet and Excel row',
              f'got {got}')
        st = await page.ev(STATUS)
        check(st['text'] == '6 workbook(s) read from 4 folder(s), 12 data point(s) added. 1 gave no data.' and not st['error'],
              'the status counts workbooks and folders, and is no error', st)
        check(st['files'] == [f'{ROOT}/notes.xlsx: no sheet with ID and the three QC columns, and not an input-set export'] and st['listed'],
              'the workbook without QC columns is listed with its reason', st['files'])
        check(not st['stop'] and not st['busy'], 'Stop is hidden and the status not busy once reading is done', st)
        check(await page.ev("loadedFiles.some(p => /secret|~\\$|\\._/.test(p))") is False,
              'owner files, "._" copies and hidden folders are passed over')
        check(await page.ev("$('workspace').classList.contains('no-folders')") is False
              and await page.ev("getComputedStyle(document.querySelector('th.folder')).display") != 'none',
              'the Folder column is shown')
        cells = await page.ev("(showTab('rows'), [...document.querySelector('#data-body tr').children].slice(0, 4).map(td => td.textContent))")
        check(cells == [f'{ROOT}/PSAR 2024', 'params.xlsx', 'Params', '2'], 'the table row starts with folder, file, sheet, row', cells)

        folders = await page.ev(OPTIONS + "('folder')")
        check(folders == [[ROOT, ROOT, 0], [f'{ROOT}/PSAR 2024', 'PSAR 2024', 1], [f'{ROOT}/PSAR 2025', 'PSAR 2025', 1],
                          [f'{ROOT}/PSAR 2025/äldre', 'äldre', 2]],
              'the Folder filter lists the tree, each folder at its depth', folders)
        files = await page.ev(OPTIONS + "('file')")
        check([v for v, _, _ in files] == [f'{ROOT}/PSAR 2024/params.xlsx', f'{ROOT}/PSAR 2025/äldre/legacy.xlsm', f'{ROOT}/PSAR 2025/gammal.xls',
                                           f'{ROOT}/PSAR 2025/offset.xlsx', f'{ROOT}/PSAR 2025/params.xlsx']
              and files[0][1:] == ['params.xlsx', f'{ROOT}/PSAR 2024'],
              'two workbooks of one name in two folders are two files, named first and their folder after', files)
        p1 = await page.ev("[...parameterIndex(rows).values()].filter(e => e.id === 'p1').map(e => [e.path, e.flagged])")
        check(p1 == [[f'{ROOT}/PSAR 2024/params.xlsx', False], [f'{ROOT}/PSAR 2025/params.xlsx', False]],
              'an ID in two workbooks is two parameters, and that alone is no flag', p1)
        p3 = await page.ev("[...parameterIndex(rows).values()].filter(e => e.id === 'p3').map(e => [e.status, e.why])")
        check(p3 == [['Mixed', ['rows disagree on status', '2 reviewers']]], 'a parameter whose rows disagree, under two reviewers, is flagged', p3)
        counts = await page.ev("[...facetCounts('status')].sort()")
        check(counts == [['In review', 1], ['OK-FSAR', 1], ['OK-PSAR', 4], ['OK-UPSAR', 1], ['Preliminary', 2]],
              'each status in the filter counts the parameters it would keep', counts)

        await page.ev(f"setFilter('folder', [{json.dumps(ROOT + '/PSAR 2025')}])")
        picked = await page.ev("filtered().map(r => r.id)")
        check(sorted(picked) == ['p1', 'p3', 'p3', 'p4', 'p5', 'p6', 'p7'], 'a folder chosen takes its subfolders along', picked)
        listed = await page.ev("(showTab('files'), [...document.querySelectorAll('#books-body tr[data-book]')].map(tr => tr.dataset.book))")
        check(listed == [f'{ROOT}/PSAR 2025/äldre/legacy.xlsm', f'{ROOT}/PSAR 2025/gammal.xls', f'{ROOT}/PSAR 2025/offset.xlsx', f'{ROOT}/PSAR 2025/params.xlsx'],
              'the Files view lists the workbooks with rows that match, not their rows', listed)
        csv_text = await page.ev(
            "(() => { const oc = URL.createObjectURL, orv = URL.revokeObjectURL, ock = HTMLAnchorElement.prototype.click; let blob = null;"
            " URL.createObjectURL = b => { blob = b; return 'blob:stub'; }; URL.revokeObjectURL = () => {}; HTMLAnchorElement.prototype.click = function () {};"
            " try { $('export-btn').click(); } finally { URL.createObjectURL = oc; URL.revokeObjectURL = orv; HTMLAnchorElement.prototype.click = ock; }"
            " return blob.text(); })()")
        table = list(csv.reader(io.StringIO(csv_text.lstrip('﻿')), delimiter=';'))
        check(table[0] == ['Folder', 'File', 'Sheet', 'Excel row', 'ID', 'QC reviewer', 'QC status', 'QC comment']
              and [f'{ROOT}/PSAR 2025', 'offset.xlsx', 'Lower', '4', 'p6', 'revA', 'OK-PSAR', ''] in table and len(table) == 8,
              'the CSV export starts with the Folder column and follows the filter', table[:3])
        await page.ev("setFilter('folder', [])")

        # 2. The same folder dropped again, and 3. chosen with the folder picker.
        await page.drop([root])
        st = await page.ev(STATUS)
        check(await page.ev('rows.length') == 12 and '6 had been read before' in st['text'],
              'a folder dropped again replaces its rows', st['text'])
        await page.choose('#folder-input', [root])
        got = [tuple(r) for r in await page.ev(ROWS)]
        check(sorted(got) == sorted(expected), 'the folder picker gives the same rows, still not doubled', got)

        # 4. A workbook added on its own.
        await page.drop([os.path.join(base, 'Lös', 'params.xlsx')])
        lone = await page.ev("rows.filter(r => r.reviewer === 'revE').map(r => [r.folder, r.path])")
        cell = await page.ev("(showTab('rows'), [...document.querySelectorAll('#data-body tr')].find(tr => tr.textContent.includes('revE')).children[0].textContent)")
        check(lone == [['', 'params.xlsx']] and cell == '—', 'a workbook dropped on its own has no folder, shown as a dash', [lone, cell])
        p1 = await page.ev("[...parameterIndex(rows).values()].filter(e => e.id === 'p1').length")
        check(p1 == 3, 'and is a third file named params.xlsx, with a parameter of its own', p1)

        # 5. A folder with a broken workbook, and 6. one with no workbook.
        await page.drop([os.path.join(base, 'Trasig')])
        st = await page.ev(STATUS)
        check(st['error'] and len(st['files']) == 1 and st['files'][0].startswith('Trasig/broken.xlsx: could not be read')
              and await page.ev("rows.some(r => r.id === 'p8')"),
              'a workbook that cannot be read is named in an error status, the others still read', st)
        await page.drop([os.path.join(base, 'Tom')])
        st = await page.ev(STATUS)
        check(st['error'] and st['text'] == 'No workbook (.xlsx, .xlsm, .xlsb, .xls) and no TOML file among what was added, only 1 other file(s).',
              'a folder without a workbook says so', st['text'])

        # 7. Stop, and 8. Clear all, while the third of twelve workbooks is read.
        stop_at = ("(button => { const t = $('status-text'); window.__seen = null; const mo = new MutationObserver(() => {"
                   " if (t.textContent.startsWith('Reading 3 of 12')) { mo.disconnect(); window.__seen = !$('stop-btn').hidden; $(button).click(); } });"
                   " mo.observe(t, {childList: true, characterData: true, subtree: true}); })")
        many = os.path.join(base, 'Många')
        await page.ev(stop_at + "('stop-btn')")
        await page.drop([many])
        st = await page.ev(STATUS)
        ids = await page.ev("rows.filter(r => r.reviewer === 'revM').map(r => r.id)")
        check(await page.ev('window.__seen') is True and st['text'].startswith('Stopped after 3 of 12 workbook(s)') and ids == ['m01', 'm02', 'm03'],
              'Stop ends the read and keeps what was read', [st['text'], ids])
        await page.ev(stop_at + "('reset-btn')")
        await page.drop([many])
        left = await page.ev("[rows.length, loadedFiles.length, $('workspace').className, $('status').className]")
        check(left == [0, 0, '', ''], 'Clear all in the middle of a read keeps nothing', left)

        # 9. A drop beside the zone, on the page's header.
        await page.ev("window.__prevented = null; window.addEventListener('drop', e => { window.__prevented = e.defaultPrevented; }, {once: true})")
        await page.drop([root], x=640, y=12)
        check(await page.ev('window.__prevented') is True and await page.ev('rows.length') == 12,
              'a folder dropped outside the zone is taken, and the browser does not open it')

        # 10. The plain file chooser: files have no folder.
        await page.choose('#file-input', [os.path.join(base, 'Lös', 'params.xlsx')])
        check(await page.ev("rows.filter(r => r.folder === '').length") == 1, 'a file chosen with Choose files has no folder')

        # 11. "Choose a folder" opens the folder chooser and the zone the file chooser, by click and by Enter.
        #     The inputs sit inside the zone, so the click a button passes on to its input reaches the zone too.
        async def chooser_after(target, how):
            page.events.clear()
            if how == 'enter':
                await page.ev(f"$({json.dumps(target)}).focus()")
                for kind in ('keyDown', 'keyUp'):
                    await page.send('Input.dispatchKeyEvent', {'type': kind, 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13,
                                                               **({'text': '\r'} if kind == 'keyDown' else {})})
            else:
                # The zone is clicked beside its buttons, on its label.
                box = await page.ev(f"(() => {{ const el = {'document.querySelector(\'.dz-label\')' if target == 'dropzone' else f'$({json.dumps(target)})'};"
                                    " el.scrollIntoView({block: 'center'}); const b = el.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()")
                for kind in ('mousePressed', 'mouseReleased'):
                    await page.send('Input.dispatchMouseEvent', {'type': kind, 'x': box[0], 'y': box[1], 'button': 'left', 'clickCount': 1})
            await page.ev('new Promise(r => setTimeout(r, 300))')
            opened = [e['params'] for e in page.events if e.get('method') == 'Page.fileChooserOpened']
            if not opened:
                return None
            doc = await page.send('DOM.getDocument')
            ids = {}
            for sel in ('#file-input', '#folder-input'):
                node = await page.send('DOM.querySelector', {'nodeId': doc['root']['nodeId'], 'selector': sel})
                ids[(await page.send('DOM.describeNode', {'nodeId': node['nodeId']}))['node']['backendNodeId']] = sel
            return [ids.get(o.get('backendNodeId')) for o in opened]
        for how in ('click', 'enter'):
            for target, wanted in (('folder-btn', '#folder-input'), ('choose-btn', '#file-input'), ('dropzone', '#file-input')):
                opened = await chooser_after(target, how)
                check(opened == [wanted], f'{how} on #{target} opens only {wanted}', opened)

        # 12. A dropped item with no entry to it, as a mail attachment has, is taken as a file on its own.
        entry = await page.ev(
            "(() => { const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet("
            "[['ID', 'QC reviewer', 'QC comment', 'QC status'], ['p9', 'revF', '', 'OK-PSAR']]), 'Params');"
            " window.__attachment = new File([XLSX.write(wb, {bookType: 'xlsx', type: 'array'})], 'bilaga.xlsx');"
            " const dt = new DataTransfer(); dt.items.add(window.__attachment); return dt.items[0].webkitGetAsEntry(); })()")
        await page.read_after(lambda: page.ev(
            "(() => { const dt = new DataTransfer(); dt.items.add(window.__attachment);"
            " document.body.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true})); })()"))
        got = await page.ev("rows.filter(r => r.id === 'p9').map(r => [r.folder, r.path])")
        check(entry is None and got == [['', 'bilaga.xlsx']], 'a dropped item with no entry is read as a file on its own', [entry, got])

        # 13. Calculation cases: the config folder alone, then its Excel folder.
        config, excel = build_config(base)
        await page.ev("$('reset-btn').click()")
        await page.drop([config])
        st = await page.ev(STATUS)
        check(st['text'].startswith('6 TOML file(s) read: 3 calculation case(s), link.toml, data.toml.') and st['error']
              and any(f.startswith('config/broken.toml: could not be read as TOML') for f in st['files']),
              'a config folder is read, and a broken TOML file is named', st)
        shown = await page.ev("[!$('cases').hidden, activeTab, $('tab-btn-overview').hidden, $('tab-btn-rows').hidden,"
                              " [...document.querySelectorAll('#cases-body .case-name')].map(b => b.textContent)]")
        check(shown == [True, 'cases', True, True, ['CC001', 'CC002', 'CC003']], 'TOML files alone show the cases, and no view of rows', shown)
        info = await page.ev("(() => { const el = document.querySelector('#cases-body [data-info=\"0\"]');"
                             " return [el.textContent, !!el.querySelector('b'), !!el.querySelector('img, script'), String(window.__pwned)]; })()")
        check(info == ['The base case ', True, False, 'undefined'], 'a description keeps <b> and runs nothing', info)
        checks_text = await page.ev("$('cases-checks').textContent")
        check('config/broken.toml could not be read' in checks_text and 'Legacy.h5 is not built by link.toml' in checks_text
              and 'workbook(s) in data.toml were not among those read' not in checks_text,
              'the checks name the broken file and the unbuilt parameter file, and no workbook before any is read', checks_text)
        cells = await page.ev("[...document.querySelectorAll('#cases-body tr[data-case]')].map(tr => [...tr.children].slice(2, 4).map(td => td.innerText.replace(/\\s+/g, ' ').trim()))")
        check(cells[0][0] == 'base.h5 → base 3 data file(s)' and cells[0][1] == 'workbooks not read'
              and cells[2][0].startswith('Legacy.h5 not built by link.toml') and cells[2][1] == '—',
              'a case\'s input and, before the workbooks, no QC', cells)

        await page.drop([excel])
        cells = await page.ev("[...document.querySelectorAll('#cases-body tr[data-case]')].map(tr => [...tr.children].slice(2, 4).map(td => td.innerText.replace(/\\s+/g, ' ').trim()))")
        check(cells[0] == ['base.h5 → base 3 data file(s), 2 workbook(s) read, 1 from raw data only', '2 of 3 parameters approved by data.toml, whole sheets Filter to this case']
              and cells[1] == ['variant.h5 → variant 3 data file(s), 2 workbook(s) read, 1 from raw data only', '2 of 3 parameters approved by data.toml, whole sheets Filter to this case'],
              'with its Excel folder, each case finds its workbooks and counts its QC', cells)
        await page.ev("setFilter('case', [cases.list.find(c => c.name === 'CC001').key])")
        ids = await page.ev("filtered().map(r => r.id).sort()")
        check(ids == ['a1', 'a2', 'b1'], 'the case filter keeps the rows of its data files, and only the sheets data.toml names', ids)
        await page.ev("document.querySelector('#cases-body tr[data-case=\"1\"] [data-show]').click()")
        ids = await page.ev("[filtered().map(r => r.id).sort(), [...filters.case].map(k => cases.list.find(c => c.key === k).name), activeTab]")
        check(ids == [['a1', 'a2', 'd1'], ['CC002'], 'files'], 'Filter to this case sets the case filter to it, and shows its files', ids)
        await page.ev("document.querySelector('#cases-body tr[data-case=\"1\"] .case-name').click()")
        detail = await page.ev("(() => { const d = document.querySelector('tr.case-detail'); return [d.innerText.includes('base_cc: CC001'),"
                               " d.innerText.includes('[farfield] source_cc: CC001'), d.innerText.includes('101 values, 0 … 1000'),"
                               " [...d.querySelectorAll('ol.steps li')].map(li => li.textContent)]; })()")
        check(detail == [True, True, True, ['base: 3 data file(s) listed', 'variant: from base, without beta, with delta']],
              'a case opens with the cases it takes results from, its settings and how its input set is built', detail)
        await page.ev("document.querySelector('tr.case-detail [data-goto]').click()")
        opened = await page.ev("[...document.querySelectorAll('.case-name[aria-expanded=true]')].map(b => b.textContent)")
        check(opened == ['CC001', 'CC002'], 'a case named in another opens from it', opened)
        sets = await page.ev("[...document.querySelectorAll('#link-sets-body tr')].map(tr => [...tr.children].slice(0, 4).map(td => td.textContent))")
        check(sets == [['base', '3 listed', '3', 'CC001'], ['variant', 'base, without beta, with delta', '3', 'CC002']], 'the input sets, with the cases using them', sets)
        gamma = await page.ev("[...document.querySelectorAll('#data-files-body tr')].map(tr => [...tr.children].map(td => td.textContent)).find(r => r[0] === 'gamma')")
        check(gamma[1] == 'none: raw data only' and gamma[3] == 'HYDRO' and gamma[4] == 'flows Inflow, Outflow', 'a data file from raw data says so', gamma)
        await page.drop([config])
        again = await page.ev("[document.querySelectorAll('#cases-body tr[data-case]').length, $('status-text').textContent]")
        check(again[0] == 3 and '6 had been read before' in again[1], 'a config folder read again replaces its cases', again)
        await page.ev("$('reset-btn').click()")
        check(await page.ev("$('cases').hidden && !cases && !facetOptions('case').length && !filters.case.size"), 'Clear all clears the cases and their filter too')

        # 14. Input-set exports, traced to the rows of the source workbooks.
        exp_root = build_exports(base)
        trace_js = ("exportFiles.map(e => [e.set, e.values, e.trace.traced, e.trace.raw, e.trace.none, e.trace.missing, e.trace.noQc, e.trace.notFound, e.stale,"
                    " [...e.rowIdx].map(i => rows[i].id + '@' + rows[i].row)])")
        want = [['set1', 10, 5, 1, 1, 1, 1, 1, True, ['a.one@2', 'a.ts@3', 'a.ts@4', 'a.ts@5', 'a.two@6']],
                ['set2', 1, 1, 0, 0, 0, 0, 0, False, ['a.two@6']]]
        await page.drop([exp_root])
        st = await page.ev(STATUS)
        traced = await page.ev(trace_js)
        check(traced == want, 'each value of an export is traced to its QC row, along a time series whose rows it gives wrongly;'
              ' the rest counted as raw data, no source, a workbook not read, a sheet without QC columns, or a row no longer there', traced)
        check(st['text'] == '4 workbook(s) read from 2 folder(s), 5 data point(s) added and 2 input-set export(s) of 11 value(s). 1 gave no data.',
              'the status counts the exports and their values', st['text'])
        await page.ev("setFilter('set', ['set1'])")
        ids = await page.ev("filtered().map(r => r.id)")
        check(ids == ['a.one', 'a.ts', 'a.ts', 'a.ts', 'a.two'], 'the Input set filter keeps the rows the set uses', ids)
        await page.ev("setFilter('set', []); setFilter('reviewer', ['revB']); showTab('files')")
        files_view = await page.ev("[[...document.querySelectorAll('#books-body tr[data-book]')].map(tr => tr.dataset.book),"
                                   " [...document.querySelectorAll('#sets-body tr[data-set]')].map(tr => [tr.dataset.set, tr.children[3].textContent]),"
                                   " $('sets-hidden').textContent, $('files-count').textContent]")
        check(files_view == [['Exp/excel/base_case/alpha.xlsx'], [['Exp/qc/set1.xlsx', '1']], '1 export not listed: no value that matches the filters.', '2'],
              'under a filter, the Files view lists the workbooks and the input sets that use the rows that match', files_view)
        flags = await page.ev("[...document.querySelectorAll('#sets-body tr[data-set] .flag')].map(f => f.textContent)")
        check(flags == ['1 from workbooks not read', '1 rows not in their workbook', '1 from sheets without QC columns'], 'an export says what keeps its values from their rows', flags)
        await page.ev("document.querySelector('#sets-body [data-open-set]').click()")
        sources = await page.ev("[...document.querySelectorAll('#sets-body tr.detail .sub-table tbody tr')].map(tr => [tr.children[0].textContent, tr.children[2].textContent])")
        check(len(sources) == 5 and ['Exp/excel/base_case/alpha.xlsx', '5 traced, 1 not found'] in sources and ['/Volumes/raw/HYDRO/NCC1/flow.csv', 'raw data'] in sources,
              'an export opens to its sources, each with what was traced of it', sources)
        await page.ev("clearFilters()")
        csv_files = await page.ev(
            "(() => { const oc = URL.createObjectURL, orv = URL.revokeObjectURL, ock = HTMLAnchorElement.prototype.click; let blob = null;"
            " URL.createObjectURL = b => { blob = b; return 'blob:stub'; }; URL.revokeObjectURL = () => {}; HTMLAnchorElement.prototype.click = function () {};"
            " try { $('export-files-btn').click(); } finally { URL.createObjectURL = oc; URL.revokeObjectURL = orv; HTMLAnchorElement.prototype.click = ock; }"
            " return blob.text(); })()")
        table = list(csv.reader(io.StringIO(csv_files.lstrip('\ufeff')), delimiter=';'))
        check(table[0][:3] == ['Kind', 'Folder', 'File'] and [r[0] for r in table[1:]].count('Input set') == 2 and table[-2][2] == 'set1.xlsx' and table[-2][10:15] == ['5', '2', '1', '1', '1'],
              'the file list exports as CSV, the input sets with what was traced', table)
        # The same, read on the page itself, as where there are no workers.
        await page.ev("$('reset-btn').click(); window.__Worker = window.Worker; window.Worker = undefined")
        await page.drop([exp_root])
        again = await page.ev(trace_js)
        await page.ev("window.Worker = window.__Worker")
        check(again == want, 'read without workers, the exports trace the same', again)
        await page.ev("$('reset-btn').click()")
        await page.drop([root])

        # 15. No sideways scroll, at a desktop width and on a phone (where fields under 16px make iOS zoom).
        wide = "[document.documentElement.scrollWidth, document.documentElement.clientWidth]"
        check((lambda w: w[0] <= w[1])(await page.ev(wide)), 'no sideways scroll at 1280 px', await page.ev(wide))
        await page.send('Emulation.setDeviceMetricsOverride', {'width': 375, 'height': 548, 'deviceScaleFactor': 2, 'mobile': True})
        await page.send('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})
        await page.send('Page.reload', {'ignoreCache': True})
        for _ in range(200):
            if await page.ev("typeof XLSX !== 'undefined' && typeof queue !== 'undefined' && document.readyState === 'complete'"):
                break
            await asyncio.sleep(0.05)
        await page.drop([root])
        phone = await page.ev(wide + ".concat(['id-search'].map(id => parseFloat(getComputedStyle($(id)).fontSize)))")
        check(phone[0] <= phone[1] == 375 and min(phone[2:]) >= 16, 'no sideways scroll on a 375 px phone, and its fields are 16 px', phone)

        # 16. In the dark theme every summary tile's number stands out from its tile (4.5:1 or more).
        contrast = await page.ev(
            "(() => { document.documentElement.setAttribute('data-theme', 'dark');"
            " const c = document.createElement('canvas').getContext('2d', {willReadFrequently: true});"
            " const rgb = s => { c.clearRect(0, 0, 1, 1); c.fillStyle = '#000'; c.fillStyle = s; c.fillRect(0, 0, 1, 1); return [...c.getImageData(0, 0, 1, 1).data].slice(0, 3); };"
            " const lum = a => a.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }).reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);"
            " return [...document.querySelectorAll('.tile')].filter(t => !t.hidden).map(card => { const [x, y] = [lum(rgb(getComputedStyle(card.querySelector('.tile-value')).color)),"
            " lum(rgb(getComputedStyle(card).backgroundColor))].sort((p, q) => q - p); return Math.round((x + 0.05) / (y + 0.05) * 10) / 10; }); })()")
        check(len(contrast) == 4 and min(contrast) >= 4.5, 'in the dark theme every summary tile reads (contrast 4.5:1 or more)', contrast)

        check(not page.errors, 'no exception or console error', page.errors)
    finally:
        shutil.rmtree(base, ignore_errors=True)
        await ws.close()
        await browser.send(json.dumps({'id': 2, 'method': 'Target.closeTarget', 'params': {'targetId': target}}))
        await browser.close()

    print(f'\n{len(failures)} failed' if failures else '\nall passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
