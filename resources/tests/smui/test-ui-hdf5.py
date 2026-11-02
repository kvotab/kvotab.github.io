#!/usr/bin/env python3
"""smui.html opening HDF5 files, in a real browser.

The fixtures are written here (h5py; Kompartment's own writer through
make-kompartment-h5.mjs; hdf5plugin's filters when it is installed) and
handed to the page as a user does: File > Open's own input
(DOM.setFileInputFiles) and a dropped file (Input.dispatchDragEvent).

Checked: the scripts and the file input; the Open HDF5 dialog (the tree,
what each line says, the boxes that cannot be ticked, the (i), Find and
Tick shown, a group's box, ⇄, Side by side, the summary and Open), the
tables against what was written (a probabilistic Kompartment run as a
table of realisations), a file of one table opened without asking, the
compression plugins fetched by their pins; MATLAB MAT-files (the HDF5
Browser's fixtures, written by MATLAB, and SciPy's): the Open MAT-file
dialog, a struct's and a table's lines, a cell with its headings opened
as a table, a one-table file opened without asking, -v4, a file over the
size read whole (-v7.3 opened as HDF5, others refused with the reason);
files that are not HDF5 or are damaged (and binary data never read as
text, UTF-16 text read), hostile names and attributes (in an HDF5 file and
a MAT-file) shown as text only, Cancel during a long listing (the reader
works again after), a Distribution report on an opened column, the dark
theme and phone width; and that the worker pins h5wasm and its plugins
exactly as rb.html does.

Start a server on the repository root and headless Chrome (the recipe is in
../rb/README.md) on SMUI_HTTP_PORT and SMUI_CDP_PORT (defaults 8791, 9291),
then

    python3 resources/tests/smui/test-ui-hdf5.py

Needs numpy, h5py and node; hdf5plugin adds the plugin checks, SciPy those
on the MAT-files it writes. With
SMUI_SHOTS=<folder> it saves screenshots. Exit status 0 when every check
passes.
"""
import asyncio
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import h5py

from cdp import BASE, Checks, open_page, open_report_js, table_under_js, wait_engine

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
SHOTS = os.environ.get('SMUI_SHOTS')
check = Checks()
TMP = tempfile.mkdtemp(prefix='smui-h5ui-')


async def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.shot(os.path.join(SHOTS, name))


def fixtures():
    rng = np.random.default_rng(11)
    f = {}
    # several tables, a group, a matrix, things that cannot be read
    p = os.path.join(TMP, 'many.h5')
    with h5py.File(p, 'w') as h:
        h['x'] = rng.normal(size=8)
        h['n'] = np.arange(8, dtype='i4')
        h['grp/a'] = rng.normal(size=8)
        h['grp/b'] = rng.normal(size=8)
        h['grp/sub/c'] = np.arange(8.0) * 3
        h['mat'] = np.arange(15.0).reshape(5, 3)
        h['long'] = np.arange(20.0)
        h['ref'] = h['grp'].ref
        h['soft'] = h5py.SoftLink('/x')
        h['note'] = 'a single value'
    f['many'] = p
    # one table: opens without the dialog
    p = os.path.join(TMP, 'one.h5')
    rec = np.zeros(6, [('id', 'i4'), ('w', 'f8'), ('name', 'S5')])
    rec['id'] = np.arange(6) + 1
    rec['w'] = np.linspace(1, 2, 6)
    rec['name'] = [b'a', b'b', b'c', b'd', b'e', b'f']
    with h5py.File(p, 'w') as h:
        h['records'] = rec
    f['one'] = p
    f['one_values'] = rec
    # hostile names and attributes
    p = os.path.join(TMP, 'evil.h5')
    with h5py.File(p, 'w') as h:
        h.attrs['Information'] = '<img src=x onerror="window.__h5pwned=1"><script>window.__h5pwned=2</script>'
        g = h.create_group('<img src=x onerror="window.__h5pwned=3">')
        d = g.create_dataset('line\nbreak', data=np.arange(3.0))
        d.attrs['units'] = '<svg onload="window.__h5pwned=4">'
        g.create_dataset('two', data=np.arange(3.0) * 2)
        h['other'] = np.arange(5.0)       # (two lengths: the dialog shows)
    f['evil'] = p
    # many small datasets: a listing long enough to cancel
    p = os.path.join(TMP, 'big.h5')
    with h5py.File(p, 'w') as h:
        for g in range(60):
            grp = h.create_group(f'g{g}')
            for k in range(400):
                grp.create_dataset(f'd{k}', data=np.zeros(2))
    f['big'] = p
    # not HDF5, damaged, binary, UTF-16
    for name, data in [('classic.nc', b'CDF\x01' + b'\0' * 60), ('old.mat', b'MATLAB 5.0 MAT-file, Platform: PCWIN64' + b'\0' * 200),
                       ('damaged.h5', b'\x89HDF\r\n\x1a\n' + bytes(range(256)) * 4), ('binary.csv', bytes(range(256)) * 8),
                       ('utf16.csv', '﻿a,b\n1,åäö\n2,x\n'.encode('utf-16-le'))]:
        p = os.path.join(TMP, name)
        with open(p, 'wb') as w:
            w.write(data if name != 'utf16.csv' else b'\xff\xfe' + 'a,b\n1,åäö\n2,x\n'.encode('utf-16-le'))
        f[name] = p
    # Kompartment's own result files
    r = subprocess.run(['node', os.path.join(HERE, 'make-kompartment-h5.mjs'), TMP], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    f['komp-prob'] = os.path.join(TMP, 'komp-prob.h5')
    f['komp-run'] = os.path.join(TMP, 'komp-run.h5')
    with open(os.path.join(TMP, 'komp.json')) as j:
        f['komp'] = json.load(j)
    try:
        import hdf5plugin
        p = os.path.join(TMP, 'squeezed.h5')
        with h5py.File(p, 'w') as h:
            h.create_dataset('blosc', data=np.arange(500.0), chunks=(50,), **hdf5plugin.Blosc(cname='lz4', clevel=5))
            h.create_dataset('zstd', data=np.arange(500.0) * 2, chunks=(50,), **hdf5plugin.Zstd())
            h.create_dataset('lzf', data=np.arange(500.0) * 3, chunks=(50,), compression='lzf')
        f['squeezed'] = p
    except ImportError:
        print('   (hdf5plugin is not installed: the plugin checks use lzf alone)')
        p = os.path.join(TMP, 'squeezed.h5')
        with h5py.File(p, 'w') as h:
            h.create_dataset('lzf', data=np.arange(500.0) * 3, chunks=(50,), compression='lzf')
        f['squeezed'] = p
    # MATLAB: the Data Browser's fixtures (written by MATLAB, mat_fixtures.m),
    # and SciPy's: a struct array alone, and hostile names
    for v in ('v4', 'v7', 'v73'):
        f[f'matlab-{v}'] = os.path.join(REPO, 'resources', 'tests', 'rb', 'fixtures', f'matlab-{v}.mat')
    try:
        import scipy.io as sio
        sa = np.zeros((1, 3), dtype=[('dose', 'O'), ('site', 'O')])
        for k in range(3):
            sa[0, k] = (k + 0.5, 'ABC'[k])
        f['onemat'] = os.path.join(TMP, 'onemat.mat')
        sio.savemat(f['onemat'], {'sa': sa})
        cells = np.empty((3, 2), dtype=object)
        cells[0, 0], cells[0, 1] = '<img src=x onerror="window.__matpwned=1">', 'line\nbreak'
        cells[1, 0], cells[1, 1], cells[2, 0], cells[2, 1] = 'a', 1.0, 'b', 2.0
        s = np.zeros((1, 1), dtype=[('<svg onload="window.__matpwned=2">', 'O')])
        s[0, 0] = (np.arange(3.0),)
        f['evilmat'] = os.path.join(TMP, 'evilmat.mat')
        sio.savemat(f['evilmat'], {'cells': cells, 's': s}, long_field_names=True)
    except ImportError:
        print('   (SciPy is not installed: the MAT-file checks use MATLAB\'s files alone)')
    return f


async def choose(page, path):
    """Pick a file with File > Open's own input, as a user does."""
    await page.ev("SM.app.fileInput.id = 'smFileInput'; 0")
    doc = await page.call('DOM.getDocument', {}, session=page.sid)
    q = await page.call('DOM.querySelector', {'nodeId': doc['result']['root']['nodeId'], 'selector': '#smFileInput'}, session=page.sid)
    await page.call('DOM.setFileInputFiles', {'nodeId': q['result']['nodeId'], 'files': [path]}, session=page.sid)


async def until(page, expr, seconds=60):
    for _ in range(int(seconds * 10)):
        v = await page.ev(expr)
        if v and not (isinstance(v, str) and v.startswith('EXCEPTION')):
            return v
        await asyncio.sleep(0.1)
    return None


DIALOG = "document.querySelector('.sm-h5-dialog')"
OPEN = f'!!{DIALOG}'
ROWS = '''[...document.querySelectorAll('.sm-h5-row')].map(r => ({ name: r.querySelector('.sm-h5-name').textContent, level: +r.getAttribute('aria-level'),
  checked: r.querySelector('input').checked, mixed: r.querySelector('input').indeterminate, disabled: r.querySelector('input').disabled, desc: r.querySelector('.sm-h5-desc').textContent }))'''
SUMMARY = "document.querySelector('.sm-h5-summary').innerText"
OPEN_BTN = "document.querySelector('.sm-h5-dialog .sm-dialog-foot .primary')"


def row_box(name):
    return f"[...document.querySelectorAll('.sm-h5-row')].find(r => r.querySelector('.sm-h5-name').textContent === {json.dumps(name)}).querySelector('input')"


async def tables_since(page, n):
    return await page.ev(f'''SM.app.tables.slice({n}).map(t => ({{ name: t.name, rows: t.nrows, notes: t.notes, source: t.source,
      cols: t.columns.map(c => ({{ name: c.name, type: c.dataType, mt: c.modelingType, values: c.values.map(v => typeof v === 'number' && !Number.isFinite(v) ? null : v),
        labels: c.valueLabels ? Object.keys(c.valueLabels).length : 0, notes: c.notes }})) }}))''')


async def main():
    fx = fixtures()
    page = await open_page(f'{BASE}/smui.html?example=students')
    ok = await until(page, '!!(window.SM && SM.app && SM.hdf5 && SM.h5)')
    check('the page has the HDF5 reader (SM.h5) and its dialog (SM.hdf5)', bool(ok), True)
    r = await page.ev('''(async () => {
      const html = await (await fetch('smui.html', { cache: 'no-cache' })).text();
      const doc = new DOMParser().parseFromString(html, 'text/html');
      const s = (n) => doc.querySelector(`script[src*="${n}"]`);
      return { read: !!s('smui-hdf5-read.js') && s('smui-hdf5-read.js').defer, page: !!s('smui-hdf5.js') && s('smui-hdf5.js').defer,
        css: !!doc.querySelector('link[href*="smui-hdf5.css"]'), accept: SM.app.fileInput.accept };
    })()''')
    check('its scripts are deferred and its stylesheet linked', (r['read'], r['page'], r['css']), (True, True, True))
    check('File > Open takes HDF5, netCDF and MATLAB files', all(x in r['accept'].split(',') for x in ['.h5', '.hdf5', '.nc', '.mat']), True)

    # ---- the dialog ---------------------------------------------------------
    n0 = await page.ev('SM.app.tables.length')
    await choose(page, fx['many'])
    check('a file of several tables opens the Open HDF5 dialog', bool(await until(page, OPEN, 120)), True)
    title = await page.ev(f"{DIALOG}.querySelector('h2').textContent")
    check('... titled with the file', title, 'Open HDF5: many.h5')
    rows = await page.ev(ROWS)
    by = {x['name']: x for x in rows}
    check('the tree: groups open, their children indented', [(x['name'], x['level']) for x in rows],
          [('grp', 1), ('a', 2), ('b', 2), ('sub', 2), ('c', 3), ('long', 1), ('mat', 1), ('n', 1), ('note', 1), ('ref', 1), ('soft', 1), ('x', 1)])
    check('what a line says: values and type, a matrix\'s shape and its table, a link', (by['x']['desc'], by['mat']['desc'], by['soft']['desc'], by['grp']['desc']),
          ('8 values · float64', '5 × 3 float64 · 5 rows × 3 columns', 'link to /x', '3 items'))
    check('what cannot be read cannot be ticked, and says why', (by['ref']['disabled'], by['ref']['desc'], by['soft']['disabled']), (True, 'references to other objects (not read)', True))
    check('ticked to start: every vector, the matrix and the single value', {k: by[k]['checked'] for k in ['x', 'n', 'a', 'b', 'c', 'mat', 'long', 'note']},
          {'x': True, 'n': True, 'a': True, 'b': True, 'c': True, 'mat': True, 'long': True, 'note': True})
    check('the summary: a table per length, and the single values', await page.ev(SUMMARY),
          'Opens 4 tables:\n\nmany — 8 rows — 5 columns\nmany — long — 20 rows × 1 column\nmany — mat — 5 rows × 3 columns\nmany — values — 1 row × 2 columns')
    await shot(page, 'h5-dialog.png')
    # the (i)
    await page.ev(f"{DIALOG}.querySelector('.sm-dialog-head .info-btn').click(); 0")
    t = await until(page, "document.querySelector('#kvot-info-panel .info-panel-title')?.textContent", 10)
    sections = await page.ev("[...document.querySelectorAll('#kvot-info-panel .info-panel-body h3')].map(h => h.textContent)")
    check('the dialog\'s (i) explains it', (t, sections), ('Open HDF5', ['Tables', 'What the file says', 'Not read', 'Find and tick', 'From the Data Browser']))
    await page.ev("document.querySelector('#kvot-info-panel .info-panel-close').click(); 0")
    # a group's box, and its mixed state
    await page.ev(f"{row_box('sub')}.click(); 0")
    rows = {x['name']: x for x in await page.ev(ROWS)}
    check('unticking a group unticks what is in it, and the group above is mixed', (rows['c']['checked'], rows['sub']['checked'], rows['grp']['mixed']), (False, False, True))
    await page.ev(f"{row_box('grp')}.click(); 0")
    rows = {x['name']: x for x in await page.ev(ROWS)}
    check('ticking a group ticks everything in it', (rows['a']['checked'], rows['c']['checked'], rows['grp']['checked'], rows['grp']['mixed']), (True, True, True, False))
    # Untick all: nothing to open
    await page.ev("[...document.querySelectorAll('.sm-h5-bar .sm-btn')].find(b => b.textContent === 'Untick all').click(); 0")
    check('Untick all: nothing ticked, and Open is off', (await page.ev(SUMMARY), await page.ev(f'{OPEN_BTN}.disabled')), ('Nothing is ticked.', True))
    # Find, then Tick shown
    await page.ev("const f = document.querySelector('.sm-h5-find'); f.value = 'c'; f.dispatchEvent(new Event('input')); 0")
    await asyncio.sleep(0.4)
    rows = await page.ev(ROWS)
    check('Find shows what matches and the groups above it', [x['name'] for x in rows], ['grp', 'sub', 'c'])
    await page.ev("[...document.querySelectorAll('.sm-h5-bar .sm-btn')].find(b => b.textContent === 'Tick shown').click(); 0")
    check('Tick shown ticks what Find shows (one table: the file\'s name)', await page.ev(SUMMARY), 'Opens one table:\n\nmany — 8 rows × 1 column')
    await page.ev("document.querySelector('.sm-h5-find').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })); 0")
    await asyncio.sleep(0.3)
    check('Escape in Find clears it; the dialog stays', (await page.ev("document.querySelector('.sm-h5-find').value"), await page.ev(OPEN), len(await page.ev(ROWS))), ('', True, 12))
    # ⇄ and Side by side
    await page.ev(f"{row_box('mat')}.click(); 0")
    await page.ev("[...document.querySelectorAll('.sm-h5-row')].find(r => r.querySelector('.sm-h5-name').textContent === 'mat').querySelector('.sm-h5-flip').click(); 0")
    rows = {x['name']: x for x in await page.ev(ROWS)}
    check('⇄ swaps a matrix: its line says so', rows['mat']['desc'], '5 × 3 float64 · 3 rows × 5 columns (swapped)')
    check('... and so does the summary', await page.ev(SUMMARY), 'Opens 2 tables:\n\nmany — c — 8 rows × 1 column\nmany — mat — 3 rows × 5 columns')
    await page.ev(f"{row_box('x')}.click(); 0")
    check('a vector of the same length goes beside the other', await page.ev(SUMMARY), 'Opens 2 tables:\n\nmany — 8 rows — 2 columns\nmany — mat — 3 rows × 5 columns')
    await page.ev("document.querySelector('.sm-h5-together input').click(); 0")
    check('Side by side off: a table each', await page.ev(SUMMARY), 'Opens 3 tables:\n\nmany — c — 8 rows × 1 column\nmany — mat — 3 rows × 5 columns\nmany — x — 8 rows × 1 column')
    await page.ev(f'{OPEN_BTN}.click(); 0')
    got = await until(page, f'SM.app.tables.length >= {n0 + 3} && !{OPEN}', 60)
    tabs = await tables_since(page, n0)
    with h5py.File(fx['many']) as h:
        mat, x, c = h['mat'][()], h['x'][()], h['grp/sub/c'][()]
    check('Open makes the tables ticked', [(t['name'], t['rows'], [c['name'] for c in t['cols']]) for t in tabs] if got else tabs,
          [('many — c', 8, ['c']), ('many — mat', 3, ['mat 1', 'mat 2', 'mat 3', 'mat 4', 'mat 5']), ('many — x', 8, ['x'])])
    check('... their values: a vector, a swapped matrix', (tabs[2]['cols'][0]['values'], [tabs[1]['cols'][j]['values'] for j in range(5)]),
          ([float(v) for v in x], [[float(v) for v in mat[j, :]] for j in range(5)]))
    check('... where they came from, in the table\'s notes', (tabs[0]['notes'], tabs[0]['source']), ('From many.h5: /grp/sub/c.', 'many.h5, /grp/sub/c'))
    check('... the first of them in front', await page.ev('SM.app.current && SM.app.current.name'), 'many — c')

    # ---- a file of one table opens without asking; a drop --------------------
    n0 = await page.ev('SM.app.tables.length')
    await page.call('Input.dispatchDragEvent', {'type': 'dragEnter', 'x': 700, 'y': 400, 'data': {'items': [], 'files': [fx['one']], 'dragOperationsMask': 1}}, session=page.sid)
    await page.call('Input.dispatchDragEvent', {'type': 'dragOver', 'x': 700, 'y': 400, 'data': {'items': [], 'files': [fx['one']], 'dragOperationsMask': 1}}, session=page.sid)
    await page.call('Input.dispatchDragEvent', {'type': 'drop', 'x': 700, 'y': 400, 'data': {'items': [], 'files': [fx['one']], 'dragOperationsMask': 1}}, session=page.sid)
    got = await until(page, f'SM.app.tables.length > {n0}', 60)
    t = (await tables_since(page, n0))[0] if got else {}
    rec = fx['one_values']
    check('a dropped file of one table opens without the dialog', (bool(got), await page.ev(OPEN)), (True, False))
    check('... a compound dataset, a column per field', ([c['name'] for c in t['cols']], t['cols'][1]['values'], t['cols'][2]['values']),
          (['id', 'w', 'name'], [float(v) for v in rec['w']], [v.decode() for v in rec['name']]))
    check('... and says so', await page.ev("document.querySelector('.sm-toast')?.textContent"), 'Opened one.h5: 6 rows × 3 columns')

    # ---- Kompartment: a probabilistic run as a table of its realisations ---------
    n0 = await page.ev('SM.app.tables.length')
    await choose(page, fx['komp-prob'])
    await until(page, OPEN, 60)
    rows = {x['name']: x for x in await page.ev(ROWS)}
    check('Kompartment: a run\'s series open a row per realisation', rows['Dose']['desc'], '24 × 30 float32 · 30 rows × 24 columns (swapped) · Sv/year')
    check('... its index lists and the time are not ticked', (rows['Radionuclides']['checked'], rows['time']['checked']), (False, False))
    await page.ev(f'{OPEN_BTN}.click(); 0')
    await until(page, f'SM.app.tables.length > {n0}', 60)
    t = (await tables_since(page, n0))[0]
    k = fx['komp']
    by = {o['label']: o for o in k['outputs']}
    S, nt = k['S'], len(k['t'])
    names = [c['name'] for c in t['cols']]
    check('Kompartment: the sampled values, then each series by time', (t['rows'], names[:3], len(names)), (S, ['kd', 'depth', 'Dose t=0'], 2 + 4 * nt))
    col = {c['name']: c for c in t['cols']}
    i = 10
    tname = names[2 + i]
    check('Kompartment: a column is one time of a series, a value per realisation (float32 as written)', col[tname]['values'], by['Dose']['prob'][i * S:(i + 1) * S])
    check('Kompartment: the parameters', (col['kd']['values'], col['depth']['values']), (by['Soil.kd']['prob'][:S], by['Water.depth']['prob'][:S]))
    # a Distribution of a parameter: the engine takes the table as any other
    st = await wait_engine(page)
    check('the engine is ready', st, 'ready')
    await page.ev(f"SM.app.showTable(SM.app.tables[{n0}].id); 0")
    rep = await page.ev(open_report_js('distribution', {'y': ['kd']}), timeout=240)
    moments = await page.ev(table_under_js('Summary Statistics'))
    mean = next((r[1] for r in moments or [] if r and r[0] == 'Mean'), None)
    want = sum(by['Soil.kd']['prob'][:S]) / S
    check('a Distribution report on an opened column: no error, its mean as computed here',
          (rep['errors'] if isinstance(rep, dict) else rep, mean is not None and math.isclose(float(mean.replace('−', '-')), want, rel_tol=1e-6)), ([], True))

    # ---- compression plugins, fetched by their pins -------------------------------
    n0 = await page.ev('SM.app.tables.length')
    await choose(page, fx['squeezed'])
    got = await until(page, f'SM.app.tables.length > {n0}', 120)
    t = (await tables_since(page, n0))[0] if got else {'cols': []}
    with h5py.File(fx['squeezed']) as h:
        want = {k: [float(v) for v in h[k][()]] for k in h}
    check(f'compressed data ({", ".join(sorted(want))}): the decoders fetched and the values right', {c['name']: c['values'] for c in t['cols']}, want)

    # ---- MATLAB MAT-files ----------------------------------------------------------------
    n0 = await page.ev('SM.app.tables.length')
    await choose(page, fx['matlab-v7'])
    check('a MAT-file opens the Open MAT-file dialog', bool(await until(page, OPEN, 120)), True)
    check('... titled with the file', await page.ev(f"{DIALOG}.querySelector('h2').textContent"), 'Open MAT-file: matlab-v7.mat')
    lead = await page.ev(f"{DIALOG}.querySelector('.sm-dialog-lead').textContent")
    check('... nothing ticked (more tables than it ticks at once), and it says so', 'The file holds 53 arrays that can be tables' in lead, True)
    rows = {x['name']: x for x in await page.ev(ROWS)}
    check('a MAT-file\'s lines: a struct, a table and a cell by class and size; arrays by size and class',
          [rows[k]['desc'] for k in ('sa', 'tbl', 'c_long', 'd_mat', 'ch', 'lg', 'c_table')],
          ['struct 1×3 · 4 items', 'table 2×2 · 2 items', 'cell 1×12 · 12 items', '4 × 4 double · 4 rows × 4 columns', 'a single value · char',
           '2 × 3 logical · 2 rows × 3 columns', '2 rows · cell, 2 named columns'])
    check('... a large sparse matrix says how it opens; an empty array cannot be ticked', (rows['sp_big']['desc'], rows['d_empty']['disabled'], rows['d_empty']['desc']),
          ('double 1100×1100 · 3 items · Too large to show with its zeros: each value with its row and column.', True, 'empty'))
    await shot(page, 'mat-dialog.png')
    await page.ev(f"{DIALOG}.querySelector('.sm-dialog-head .info-btn').click(); 0")
    t = await until(page, "document.querySelector('#kvot-info-panel .info-panel-title')?.textContent", 10)
    sections = await page.ev("[...document.querySelectorAll('#kvot-info-panel .info-panel-body h3')].map(h => h.textContent)")
    check('the dialog\'s (i) explains MAT-files', (t, sections), ('Open MAT-file', ['Variables', 'What is said', 'Larger files', 'Find and tick']))
    await page.ev("document.querySelector('#kvot-info-panel .info-panel-close').click(); 0")
    await page.ev(f"{row_box('c_table')}.click(); {row_box('tbl')}.click(); 0")
    check('a cell with its headings is a table of its own; a table\'s variables one', await page.ev(SUMMARY),
          'Opens 2 tables:\n\nmatlab-v7 — c_table — 2 rows × 2 columns\nmatlab-v7 — tbl — 2 rows × 2 columns')
    await page.ev(f'{OPEN_BTN}.click(); 0')
    got = await until(page, f'SM.app.tables.length >= {n0 + 2} && !{OPEN}', 60)
    tabs = await tables_since(page, n0)
    check('Open makes them: the headings name the columns, numbers are numbers again; a MATLAB table\'s variables in its order',
          [(t['name'], [(c['name'], c['type'], c['values']) for c in t['cols']]) for t in tabs] if got else tabs,
          [('matlab-v7 — c_table', [('Nuclide', 'character', ['Cs-135', 'I-129']), ('Q', 'numeric', [1.5, None])]),
           ('matlab-v7 — tbl', [('n', 'numeric', [1.0, 2.0]), ('name', 'character', ['a', 'b'])])])
    check('... the notes say where each column came from', tabs[0]['cols'][1]['notes'] if got else None, '/c_table; MATLAB cell 3×2; column 2, headed Q')
    if 'onemat' in fx:
        n0 = await page.ev('SM.app.tables.length')
        for kind in ('dragEnter', 'dragOver', 'drop'):
            await page.call('Input.dispatchDragEvent', {'type': kind, 'x': 700, 'y': 400, 'data': {'items': [], 'files': [fx['onemat']], 'dragOperationsMask': 1}}, session=page.sid)
        got = await until(page, f'SM.app.tables.length > {n0}', 60)
        t = (await tables_since(page, n0))[0] if got else {'cols': []}
        check('a MAT-file of one struct array opens as its table without the dialog, its fields in order',
              (await page.ev(OPEN), [(c['name'], c['values']) for c in t['cols']], await page.ev("document.querySelector('.sm-toast')?.textContent")),
              (False, [('dose', [0.5, 1.5, 2.5]), ('site', ['A', 'B', 'C'])], 'Opened onemat.mat: 3 rows × 2 columns'))
    n0 = await page.ev('SM.app.tables.length')
    await choose(page, fx['matlab-v4'])
    await until(page, OPEN, 60)
    check('-v4: the dialog, every table ticked', await page.ev(SUMMARY),
          'Opens 3 tables:\n\nmatlab-v4 — 2 rows — 3 columns\nmatlab-v4 — v4_cplx — 2 rows × 2 columns\nmatlab-v4 — v4_mat — 3 rows × 3 columns')
    await page.ev(f'{OPEN_BTN}.click(); 0')
    await until(page, f'SM.app.tables.length >= {n0 + 3}', 60)
    t = (await tables_since(page, n0))[2]
    check('... magic(3) as MATLAB shows it', [c['values'] for c in t['cols']], [[8.0, 3.0, 4.0], [1.0, 5.0, 9.0], [6.0, 7.0, 2.0]])
    # over the size this page reads whole (a File whose size says 2 GB to the
    # page; the worker gets the bytes there are)
    big = '''const big = async (name) => { const b = await (await fetch(`resources/tests/rb/fixtures/${name}`, { cache: 'no-cache' })).arrayBuffer();
      const f = new File([b], name); Object.defineProperty(f, 'size', { value: 2e9 }); return f; };'''
    msg = await page.ev(f'''(async () => {{ {big}
      document.querySelectorAll('.sm-toast').forEach(t => t.remove());
      await SM.app.openFiles([await big('matlab-v7.mat')]);
      return document.querySelector('.sm-toast.error')?.textContent; }})()''')
    check('a MAT-file over 1 GB, not -v7.3: refused, saying how to save it', msg,
          "matlab-v7.mat: 1.9 GB, more than this page reads of a MAT-file (1.0 GB); saved with save(..., '-v7.3') it opens without being read whole")
    await page.ev(f'(async () => {{ {big} SM.hdf5.open(SM.app, await big("matlab-v73.mat")); }})(); 0')
    await until(page, OPEN, 60)
    r = await page.ev(f'''(() => ({{ title: {DIALOG}.querySelector('h2').textContent, lead: {DIALOG}.querySelector('.sm-dialog-lead').textContent,
      cell: [...document.querySelectorAll('.sm-h5-row')].find(r => r.querySelector('.sm-h5-name').textContent === 'c_str').querySelector('.sm-h5-desc').textContent }}))()''')
    check('a -v7.3 file over 1 GB opens as the HDF5 file it is, and says so; its cells are not read',
          (r['title'], r['lead'].endswith('At 1.9 GB it is too large to read whole, and opens as the HDF5 file it is: its cell arrays and objects are not read.'), r['cell']),
          ('Open HDF5: matlab-v73.mat', True, "a MATLAB cell (not read: MATLAB's own format)"))
    await page.ev("[...document.querySelectorAll('.sm-h5-dialog .sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Cancel').click(); 0")
    await until(page, f'!{OPEN}', 10)

    # ---- not HDF5, damaged, binary, UTF-16 ------------------------------------------
    async def toast_of(path):
        await page.ev("document.querySelectorAll('.sm-toast').forEach(t => t.remove()); 0")
        await choose(page, path)
        return await until(page, "document.querySelector('.sm-toast.error')?.textContent", 30)
    check('a netCDF-3 file says what it is', await toast_of(fx['classic.nc']), 'classic.nc: a netCDF-3 (classic) file, which is not HDF5: save it as netCDF-4, or as CSV')
    check('a MATLAB 5 file of no variables says so', await toast_of(fx['old.mat']), 'old.mat: it holds no variables')
    with open(os.path.join(TMP, 'junk.mat'), 'wb') as w:
        w.write(b'\x07' * 300)
    check('a .mat file that is no MAT-file says so', await toast_of(os.path.join(TMP, 'junk.mat')),
          'junk.mat: it is not a MAT-file this page can read: it starts with none of the headers MATLAB writes')
    msg = await toast_of(fx['damaged.h5'])
    check('a damaged HDF5 file is refused, with HDF5\'s reason', bool(msg) and msg.startswith('damaged.h5: not an HDF5 file this reader can open ('), True)
    n0 = await page.ev('SM.app.tables.length')
    check('binary data is not read as text', await toast_of(fx['binary.csv']),
          "binary.csv: not a text file, nor one of the formats this page reads (delimited text, Excel .xlsx, Stata, SAS, JMP, HDF5 and this page's JSON)")
    check('... and makes no table', await page.ev('SM.app.tables.length'), n0)
    await choose(page, fx['utf16.csv'])
    await until(page, f'SM.app.tables.length > {n0}', 30)
    t = (await tables_since(page, n0))[0]
    check('UTF-16 text (Excel\'s Unicode Text) is read', [(c['name'], c['values']) for c in t['cols']], [('a', [1.0, 2.0]), ('b', ['åäö', 'x'])])

    # ---- hostile names and attributes -------------------------------------------------
    n0 = await page.ev('SM.app.tables.length')
    await choose(page, fx['evil'])
    await until(page, OPEN, 60)
    r = await page.ev(f'''(() => ({{ imgs: {DIALOG}.querySelectorAll('img, script, svg[onload]').length, names: [...document.querySelectorAll('.sm-h5-name')].map(n => n.textContent),
      pwned: window.__h5pwned || null }}))()''')
    check('hostile names are text in the dialog, never markup', (r['imgs'], r['names'][0], r['pwned']), (0, '<img src=x onerror="window.__h5pwned=3">', None))
    await page.ev(f'{OPEN_BTN}.click(); 0')
    await until(page, f'SM.app.tables.length > {n0}', 30)
    t = (await tables_since(page, n0))[0]
    check('... a line break in a name becomes a space in the table', [c['name'] for c in t['cols']], ['line break', 'two'])
    await until(page, f'SM.app.tables.length > {n0 + 1}', 10)
    side = await page.ev("(() => { const s = document.querySelector('.sm-side'); return { tags: s.querySelectorAll('img, script, svg[onload]').length, text: s.textContent }; })()")
    check('... the notes are text (the Information markup\'s tags dropped, a name kept as written), and nothing ran',
          ('<script>' in t['notes'], '/<img src=x' in t['notes'], side['tags'], await page.ev('window.__h5pwned || null')), (False, True, 0, None))
    if 'evilmat' in fx:
        n0 = await page.ev('SM.app.tables.length')
        await choose(page, fx['evilmat'])
        await until(page, OPEN, 60)
        r = await page.ev(f'''(() => ({{ tags: {DIALOG}.querySelectorAll('img, script, svg[onload]').length, names: [...document.querySelectorAll('.sm-h5-name')].map(n => n.textContent) }}))()''')
        check('a MAT-file\'s hostile names are text in the dialog', (r['tags'], r['names']), (0, ['cells', 's', '<svg onload="window.__matpwned=2">']))
        await page.ev(f'{OPEN_BTN}.click(); 0')
        await until(page, f'SM.app.tables.length >= {n0 + 2}', 30)
        tabs = await tables_since(page, n0)
        main = await page.ev("document.querySelector('.sm-main').querySelectorAll('img, script, svg[onload]').length")
        check('... and in the tables: a heading of markup is a name, one with a line break on one line; nothing ran',
              ([c['name'] for t in tabs for c in t['cols']], main, await page.ev('window.__matpwned || null')),
              (['<img src=x onerror="window.__matpwned=1">', 'line break', '<svg onload="window.__matpwned=2">'], 0, None))

    # ---- Cancel during a long listing ------------------------------------------------------
    n0 = await page.ev('SM.app.tables.length')
    await page.ev("document.querySelectorAll('.sm-toast').forEach(t => t.remove()); 0")
    await choose(page, fx['big'])
    busy = await until(page, "[...document.querySelectorAll('.sm-dialog h2')].find(h => h.textContent === 'Opening big.h5') ? document.querySelector('.sm-h5-busytext').textContent : null", 30)
    check('a long listing shows what it is doing, with Cancel', bool(busy) and (busy.startswith('Listing the file') or busy.startswith('Opening big.h5')), True)
    await page.ev("[...document.querySelectorAll('.sm-dialog .sm-dialog-foot .sm-btn')].find(b => b.textContent === 'Cancel').click(); 0")
    toast = await until(page, "document.querySelector('.sm-toast')?.textContent", 20)
    check('Cancel stops it: said, no table, no dialog', (toast, await page.ev('SM.app.tables.length'), await page.ev(OPEN)), ('big.h5: cancelled', n0, False))
    for kind in ('dragEnter', 'dragOver', 'drop'):
        await page.call('Input.dispatchDragEvent', {'type': kind, 'x': 700, 'y': 400, 'data': {'items': [], 'files': [fx['one']], 'dragOperationsMask': 1}}, session=page.sid)
    check('the reader works again after a Cancel', bool(await until(page, f'SM.app.tables.length > {n0}', 60)), True)
    check('no script errors', (page.errors, [c for c in page.console if 'favicon' not in c]), ([], []))
    await page.close()

    # ---- dark theme and phone width ---------------------------------------------------
    for dark, width, tag in [(True, 1400, 'dark'), (False, 390, 'phone')]:
        p2 = await open_page(f'{BASE}/smui.html', width=width, height=760, dark=dark)
        await until(p2, '!!(window.SM && SM.app && SM.hdf5)')
        await choose(p2, fx['komp-prob'])
        await until(p2, OPEN, 60)
        r = await p2.ev(f'''(() => {{
          const d = {DIALOG}, s = getComputedStyle(d), row = [...document.querySelectorAll('.sm-h5-row')].find(r => r.querySelector('.sm-h5-flip'));
          const nm = row.querySelector('.sm-h5-name').getBoundingClientRect(), fl = row.querySelector('.sm-h5-flip').getBoundingClientRect(), ds = row.querySelector('.sm-h5-desc').getBoundingClientRect();
          return {{ bg: s.backgroundColor, color: getComputedStyle(row.querySelector('.sm-h5-desc')).color, w: Math.round(d.getBoundingClientRect().width), vw: innerWidth,
            flipOnNameLine: Math.abs((fl.top + fl.bottom) / 2 - (nm.top + nm.bottom) / 2) < 8, descBelow: ds.top >= nm.bottom - 1, overflow: document.documentElement.scrollWidth > innerWidth }};
        }})()''')
        if dark:
            check('dark theme: the dialog is dark, its text light', (r['bg'] != 'rgb(255, 255, 255)', r['color'] != 'rgb(0, 0, 0)'), (True, True))
        else:
            check('phone: the dialog takes the width; ⇄ on the name\'s line, the description under it; no sideways scroll',
                  (r['w'] == r['vw'], r['flipOnNameLine'], r['descBelow'], r['overflow']), (True, True, True, False))
        await asyncio.sleep(0.5)      # (the site's ☰ fades out under a dialog)
        await shot(p2, f'h5-{tag}.png')
        await p2.close()

    # ---- the pins: the worker takes h5wasm and its plugins as rb.html does ---------------
    def read(p):
        with open(os.path.join(REPO, p)) as f:
            return f.read()
    worker, rbhtml, rbworker = read('resources/js/smui-hdf5-worker.js'), read('rb.html'), read('resources/js/rb-lazy-worker.js')
    tag = re.search(r'<script[^>]+src="(https://cdn\.jsdelivr\.net/npm/h5wasm@[^"]+)"[^>]+integrity="([^"]+)"', rbhtml)
    pins = lambda s: dict(re.findall(r"^\s*(\w+): '(sha384-[^']+)'", s, re.M))
    check('the worker pins the h5wasm rb.html loads', (re.search(r"H5WASM_URL = '([^']+)'", worker).group(1), re.search(r"H5WASM_INTEGRITY = '([^']+)'", worker).group(1)), (tag.group(1), tag.group(2)))
    check('... and the plugins rb\'s worker pins', (pins(worker), re.search(r"PLUGIN_BASE = '([^']+)'", worker).group(1)), (pins(rbworker), re.search(r"PLUGIN_BASE = '([^']+)'", rbworker).group(1)))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(check.done())
