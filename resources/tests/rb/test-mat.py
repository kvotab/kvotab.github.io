#!/usr/bin/env python3
"""MATLAB MAT-files (.mat) opened as files: each variable a dataset or a group.

A MAT-file opens as an HDF5 file the page writes in memory from its variables
(rb-mat.js has the layout). The files read here:

    fixtures/matlab-v7.mat    written by MATLAB R2023a (mat_fixtures.m): a
    fixtures/matlab-v73.mat   variable of each kind it saves -- numbers of
                              several classes, complex, logical, empty, text
                              in UTF-8 and UTF-16, cell, struct and struct
                              array, sparse small and large, function
                              handles, string arrays, a table, a datetime, a
                              global -- compressed (-v7) and as HDF5 (-v7.3)
    fixtures/matlab-v4.mat    the classes Level 4 holds
    written by this script    Level 5 uncompressed in both byte orders, Level
                              4 big-endian, and damaged and hostile files

The checks read the HDF5 file the page wrote, through the page's own h5wasm:
each variable's values in MATLAB's shape, its class and size, a struct
array's fields, the text of strings and function handles; and that -v7 and
-v7.3 give the same tree, as do the two byte orders. A damaged file opens with
what can be read, a variable that cannot is said so, and a file that is no
MAT-file is refused with the reason. Nothing in a file reaches the page as
markup.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-mat.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import json
import os
import struct
import sys
import tempfile
import urllib.request
import zlib

import websockets

from driver import open_page

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, 'fixtures')

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


# --- Level 5 written here ----------------------------------------------------------
# Elements as the format has them: a tag of type and size, the data, padding to
# eight bytes. e is the byte order, '<' or '>'.

def element(t, data, e):
    return struct.pack(e + 'II', t, len(data)) + data + b'\0' * (-len(data) % 8)


def matrix(cls, dims, name, parts, e, flags=0):
    body = (element(6, struct.pack(e + 'II', cls | flags, 0), e)
            + element(5, struct.pack(e + f'{len(dims)}i', *dims), e)
            + element(1, name.encode('utf-8'), e) + b''.join(parts))
    return struct.pack(e + 'II', 14, len(body)) + body


def doubles(values, e):
    return element(9, struct.pack(e + f'{len(values)}d', *values), e)


def chars(text, e):
    return element(4, struct.pack(e + f'{len(text)}H', *(ord(c) for c in text)), e)


def struct_(name, fields, values, e):
    """A 1×1 struct: values[k] is the k-th field's array."""
    width = 32
    names = b''.join(f.encode('utf-8')[:width - 1].ljust(width, b'\0') for f in fields)
    return matrix(2, [1, 1], name, [element(5, struct.pack(e + 'i', width), e), element(1, names, e)] + values, e)


def header(e, text='MATLAB 5.0 MAT-file, written by test-mat.py'):
    return (text.encode('utf-8').ljust(116, b' ')[:116] + b' ' * 8
            + struct.pack(e + 'H', 0x0100) + (b'IM' if e == '<' else b'MI'))


def compressed(elem, e):
    z = zlib.compress(elem)
    return struct.pack(e + 'II', 15, len(z)) + z


def plain(e):
    """The same small workspace in either byte order, uncompressed."""
    return header(e) + b''.join([
        matrix(6, [2, 3], 'a', [doubles([1, 4, 2, 5, 3, 6], e)], e),
        matrix(4, [1, 4], 't', [chars('text', e)], e),
        matrix(1, [1, 2], 'c', [matrix(6, [1, 1], '', [doubles([7], e)], e),
                                matrix(4, [1, 1], '', [chars('x', e)], e)], e),
        struct_('s', ['f'], [matrix(6, [1, 1], '', [doubles([9], e)], e)], e),
        matrix(10, [1, 2], 'i', [element(3, struct.pack(e + '2h', -5, 300), e)], e),
    ])


def level4_big_endian():
    """A 2×2 double, big-endian: the type's thousands say so."""
    return struct.pack('>5i', 1000, 2, 2, 0, 2) + b'm\0' + struct.pack('>4d', 1, 3, 2, 4)


def deep():
    inner = matrix(6, [1, 1], '', [doubles([1], '<')], '<')
    for k in range(70):
        inner = matrix(1, [1, 1], 'deep' if k == 69 else '', [inner], '<')
    return header('<') + inner + matrix(6, [1, 1], 'after', [doubles([2], '<')], '<')


VECTOR = [1 + (k * 37 % 1000) / 10 for k in range(1000)]


HOSTILE_VECTOR = '<img src=x onerror="window.__matXss=3">'


def vectors():
    """Vectors and matrices of numbers, which are drawn, and a scalar, which is not.
    A matrix's values are written as MATLAB keeps them, a column at a time."""
    e = '<'
    return header(e) + b''.join([
        matrix(6, [1000, 1], 'v', [doubles(VECTOR, e)], e),
        matrix(7, [1, 50], 'w', [element(7, struct.pack(e + '50f', *[k - 25 for k in range(50)]), e)], e),
        matrix(6, [5, 1], 'gaps', [doubles([1, float('nan'), 3, float('inf'), 5], e)], e),
        matrix(6, [20000, 1], 'long', [doubles([k % 97 for k in range(20000)], e)], e),
        matrix(12, [1, 5], 'iv', [element(5, struct.pack(e + '5i', 1, 2, 3, 4, 5), e)], e),
        matrix(6, [3, 4], 'mtx', [doubles(list(range(12)), e)], e),
        matrix(6, [2, 2], 'pm', [doubles([1, 100, 10, 1000], e)], e),
        matrix(6, [2, 2], 'nm', [doubles([1, float('inf'), float('nan'), 4], e)], e),
        matrix(6, [150, 120], 'big', [doubles([k % 7 for k in range(150 * 120)], e)], e),
        matrix(6, [1, 1], 'sc', [doubles([7], e)], e),
        matrix(6, [3, 1], HOSTILE_VECTOR, [doubles([1, 2, 3], e)], e),
        matrix(6, [2, 3, 4], 'cube', [doubles(list(range(24)), e)], e),
        matrix(6, [2, 2, 2, 3], 'hyper', [doubles(list(range(24)), e)], e),
    ])


HOSTILE = '<img src=x onerror="window.__matXss=1">'


def hostile():
    return header('<', 'MATLAB 5.0 MAT-file <img src=x onerror="window.__matXss=2">') + b''.join([
        matrix(6, [1, 1], HOSTILE, [doubles([1], '<')], '<'),
        struct_('s', ['a/b', '..'], [matrix(6, [1, 1], '', [doubles([2], '<')], '<'),
                                     matrix(6, [1, 1], '', [doubles([3], '<')], '<')], '<'),
    ])


def damaged_compressed():
    garbage = bytes(range(7, 200))
    return header('<') + struct.pack('<II', 15, len(garbage)) + garbage + matrix(6, [1, 1], 'ok', [doubles([5], '<')], '<')


def huge_cell():
    return header('<') + matrix(1, [100000, 100000], 'huge', [], '<') + matrix(6, [1, 1], 'ok', [doubles([5], '<')], '<')


# --- in the page -------------------------------------------------------------------

SETTLE = """(async () => {
  for (let i = 0; i < 300; i++) {
    if (document.getElementById('fileLoadTicker').hidden) break;
    await new Promise(r => setTimeout(r, 100));
  }
  await new Promise(r => setTimeout(r, 300));
  return fileOrder.slice();
})()"""

# Every dataset and group of an open file, by path: shape, type, attributes and
# values, with what JSON cannot say -- NaN, -0, 64-bit integers -- as text.
DUMP = """((file) => {
  const f = loadedFiles[file];
  if (!f) return 'no file';
  const say = (x) => typeof x === 'bigint' ? String(x) : (typeof x === 'number' && (!Number.isFinite(x) || Object.is(x, -0)) ? (Object.is(x, -0) ? '-0' : String(x)) : x);
  const list = (v) => ArrayBuffer.isView(v) || Array.isArray(v) ? Array.from(v, x => Array.isArray(x) ? x.map(say) : say(x)) : say(v);
  const out = {};
  const walk = (g, prefix) => {
    for (const k of Array.from(g.keys()).sort()) {
      const n = g.get(k);
      const path = prefix + '/' + k;
      const attrs = {};
      for (const a of Object.keys(n.attrs || {})) attrs[a] = list(n.attrs[a].value);
      if (n.type === 'Group') { out[path] = { group: true, attrs }; walk(n, path); }
      else out[path] = { shape: n.shape, dtype: n.dtype, attrs, value: list(n.value) };
    }
  };
  walk(f, '');
  const root = {};
  for (const a of Object.keys(f.attrs || {})) root[a] = list(f.attrs[a].value);
  return { root, tree: out };
})(%s)"""

HELPERS = r"""(() => {
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__row = (path, group) => findTreeItem(path, { extra: group ? '.group' : '', root: document.getElementById('tree') });
  window.__click = async (path, group) => {
    const r = __row(path, group);
    if (!r) return false;
    r.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await __wait(1500);
    return true;
  };
  return true;
})()"""


# What the data preview draws: whether it shows, the traces by kind, name and
# length, the first few points, the axes, and the controls offered beside it.
PREVIEW = """(async () => {
  await __wait(900);
  const pd = document.getElementById('plotlyChart');
  const shown = document.getElementById('plotlyChartContainer').classList.contains('visible') && currentPdfHistogram;
  const traces = (shown ? pd.data || [] : []).map(t => ({ type: t.type, name: t.name, n: (t.y || t.x || []).length,
    x: Array.from(t.x || []).slice(0, 3), y: Array.from(t.y || []).slice(0, 3).map(v => (Number.isFinite(v) ? v : String(v))),
    z: t.z ? t.z.map(r => Array.from(r)) : undefined, xaxis: t.xaxis }));
  const fl = pd._fullLayout || {};
  const visible = (id) => { const el = document.getElementById(id); return !!el && getComputedStyle(el).display !== 'none'; };
  return { shown, traces, x: fl.xaxis && fl.xaxis.title && fl.xaxis.title.text, y: fl.yaxis && fl.yaxis.title && fl.yaxis.title.text,
           yType: fl.yaxis && fl.yaxis.type, yReversed: !!(fl.yaxis && fl.yaxis.range && fl.yaxis.range[0] > fl.yaxis.range[1]),
           mode: (document.querySelector('#histModeToggle button.active') || {}).dataset?.mode,
           vector: !!(currentPdfHistogramData && currentPdfHistogramData.vector),
           pressed: [...document.querySelectorAll('#histModeToggle button')].filter(b => !b.hidden).map(b => [b.dataset.mode, b.getAttribute('aria-pressed')]),
           disabled: [...document.querySelectorAll('#histModeToggle button')].filter(b => b.disabled).map(b => [b.dataset.mode, b.title]),
           colorbar: ((pd.data || []).find(t => t.showscale) || {}).colorbar?.title?.text,
           panels: (fl.annotations || []).map(a => a.text), element: visible('histIterLabel'), stats: visible('histStatsLabel'),
           slice: visible('histSliceLabel') ? document.getElementById('histSliceText').textContent : null,
           log: visible('histLogLabel'), pdf: visible('histPdfLabel'), place: document.getElementById('histIterText').textContent };
})()"""


async def preview(page, path):
    await page.ev(f"__click({json.dumps(path)}, false)")
    return await page.ev(PREVIEW, timeout=30)


async def pick_files(page, paths):
    doc = await page.send('DOM.getDocument', {})
    found = await page.send('DOM.querySelector', {'nodeId': doc['result']['root']['nodeId'], 'selector': '#fileInput'})
    await page.send('DOM.setFileInputFiles', {'nodeId': found['result']['nodeId'], 'files': paths})
    await page.ev('__wait(300)')
    return await page.ev(SETTLE, timeout=120)


async def dump(page, name):
    return await page.ev(DUMP % json.dumps(name), timeout=60)


async def ingest(page, name, data):
    """Bytes handed over under a name, as a URL or a handoff hands them."""
    return await page.ev("""(async (name, b64) => {
        const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
        try { return await ingestFileBuffer(name, bytes.buffer, 'test-mat'); }
        catch (e) { return 'refused: ' + e.message; } })(%s, %s)"""
                         % (json.dumps(name), json.dumps(base64.b64encode(data).decode())), timeout=60)


def value(d, path):
    return d['tree'].get(path, {}).get('value')


def attr(d, path, name):
    return d['tree'].get(path, {}).get('attrs', {}).get(name)


async def main():
    tmp = tempfile.mkdtemp(prefix='rb-mat-')
    written = {
        'plain.mat': plain('<'),
        'bigendian.mat': plain('>'),
        'level4-be.mat': level4_big_endian(),
        'deep.mat': deep(),
        'hostile.mat': hostile(),
        'damaged-zlib.mat': damaged_compressed(),
        'huge.mat': huge_cell(),
        'notmat.mat': bytes(range(256)) * 4,
        'vectors.mat': vectors(),
        'vectors-b.mat': vectors(),
    }
    v7 = open(os.path.join(FIXTURES, 'matlab-v7.mat'), 'rb').read()
    written['truncated.mat'] = v7[:len(v7) * 3 // 5]
    for name, data in written.items():
        with open(os.path.join(tmp, name), 'wb') as fh:
            fh.write(data)
    at = lambda name: os.path.join(tmp, name)
    fixture = lambda name: os.path.join(FIXTURES, name)

    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            await page.ev(HELPERS)
            check('the file picker offers .mat', '.mat' in (await page.ev(
                "document.getElementById('fileInput').accept")).split(','), True)

            # --- written by MATLAB ---------------------------------------------
            opened = await pick_files(page, [fixture('matlab-v7.mat'), fixture('matlab-v73.mat'), fixture('matlab-v4.mat')])
            check('the three MATLAB files open, each under its own name',
                  opened, ['matlab-v7.mat', 'matlab-v73.mat', 'matlab-v4.mat'])
            d7 = await dump(page, 'matlab-v7.mat')
            d73 = await dump(page, 'matlab-v73.mat')
            d4 = await dump(page, 'matlab-v4.mat')
            check('-v7 says what it is', (d7['root'].get('MATLAB_format'), d7['root'].get('MATLAB_header', '')[:19]),
                  ('Level 5, compressed (-v7)', 'MATLAB 5.0 MAT-file'))
            check('-v7.3 says what it is', (d73['root'].get('MATLAB_format'), d73['root'].get('MATLAB_header', '')[:19]),
                  ('7.3 (-v7.3, HDF5)', 'MATLAB 7.3 MAT-file'))
            check('-v7 and -v7.3 give the same tree, value for value',
                  [p for p in sorted(set(d7['tree']) | set(d73['tree'])) if d7['tree'].get(p) != d73['tree'].get(p)], [])
            check('every variable, and nothing else, at the top', sorted(p for p in d7['tree'] if p.count('/') == 1), sorted(
                '/' + v for v in ['d_mat', 'd_3d', 'd_empty', 'd_special', 's_single', 'i64', 'u8', 'lg', 'cz', 'ch', 'ch_mat',
                                  'ch_uni', 'ch_emoji', 'c_mixed', 'c_str', 'c_long', 'c_table', 'c_nums', 's', 'sa', 's_empty',
                                  'sp', 'sp_big', 'fh', 'fh_named', 'str_arr', 'str_missing', 'tbl', 'dt', 'gv']))

            t = d7['tree']
            check('a matrix in MATLAB\'s shape, its rows in order',
                  (t['/d_mat']['shape'], t['/d_mat']['value'], attr(d7, '/d_mat', 'MATLAB_class'), attr(d7, '/d_mat', 'MATLAB_size')),
                  ([4, 4], [16, 2, 3, 13, 5, 11, 10, 8, 9, 7, 6, 12, 4, 14, 15, 1], 'double', '4×4'))
            check('  three dimensions too', (t['/d_3d']['shape'], t['/d_3d']['value']),
                  ([2, 3, 4], [1 + i + 2 * j + 6 * k for i in range(2) for j in range(3) for k in range(4)]))
            check('  an empty one keeps its size', (t['/d_empty']['shape'], t['/d_empty']['value']), ([0, 3], []))
            check('  NaN, infinities, -0 and a subnormal as they are', t['/d_special']['value'],
                  ['NaN', 'Infinity', '-Infinity', '-0', 1e-310])
            check('single, int64 and uint8 keep their classes',
                  [(t[p]['dtype'], t[p]['value']) for p in ['/s_single', '/i64', '/u8']],
                  [('<f', [1.5, 2.5, 3.5, 4.5]), ('<q', ['-9223372036854775808', '9223372036854775807']), ('<B', [0, 128, 255])])
            check('a logical is 0 and 1, and says it is logical',
                  (t['/lg']['value'], attr(d7, '/lg', 'MATLAB_class')), ([1, 0, 1, 0, 1, 0], 'logical'))
            check('a complex matrix is (real, imag) pairs, row by row',
                  t['/cz']['value'], [[1, 2], [3, -4], [0, 5], [-6, 0]])
            check('text: a row is a string, a matrix a string per row, UTF-16 and surrogate pairs whole',
                  [t[p]['value'] for p in ['/ch', '/ch_mat', '/ch_uni', '/ch_emoji']],
                  ['hello', ['abc', 'def'], 'Ångström µ ✓ δ', 'smile 😀'])
            check('  with MATLAB\'s size, which a string has no shape to say',
                  [attr(d7, p, 'MATLAB_size') for p in ['/ch', '/ch_mat']], ['1×5', '2×3'])
            check('a cell: its elements by MATLAB\'s subscripts',
                  sorted(p for p in t if p.startswith('/c_mixed/') and p.count('/') == 2),
                  ['/c_mixed/{1,1}', '/c_mixed/{1,2}', '/c_mixed/{1,3}', '/c_mixed/{2,1}', '/c_mixed/{2,2}', '/c_mixed/{2,3}'])
            check('  each read as what it is: a string, a cell, a struct, an empty matrix',
                  [value(d7, '/c_mixed/{1,2}'), (value(d7, '/c_mixed/{2,1}'), attr(d7, '/c_mixed/{2,1}', 'MATLAB_class')),
                   value(d7, '/c_mixed/{2,2}/a'), t['/c_mixed/{2,3}']['shape']], ['two', ([6], 'cell'), [1], [0, 0]])
            check('  numbered so the tree keeps them in order: {01} to {12}',
                  sorted(p.split('/')[2] for p in t if p.startswith('/c_long/')), [f'{{{k:02d}}}' for k in range(1, 13)])
            check('a cell of strings is one dataset of them',
                  (t['/c_str']['shape'], t['/c_str']['value'], attr(d7, '/c_str', 'MATLAB_class')),
                  ([1, 3], ['Ac-227', 'Am-241', 'Cs-135'], 'cell'))
            check('  a cell of numbers and text, as from a spreadsheet, one table of text: numbers in full, an empty element empty',
                  (t['/c_table']['shape'], t['/c_table']['value'], 'text' in attr(d7, '/c_table', 'MATLAB_note')),
                  ([3, 2], ['Nuclide', 'Q', 'Cs-135', '1.5', 'I-129', ''], True))
            check('  a cell of numbers, one dataset of them, an empty element NaN and said to be',
                  (t['/c_nums']['dtype'], t['/c_nums']['value'], attr(d7, '/c_nums', 'empty'), attr(d7, '/c_nums', 'MATLAB_note')),
                  ('<d', [1, 'NaN', 3], 1, '1 empty element is shown as NaN.'))
            check('a struct: a group of its fields, in their order as an attribute',
                  (value(d7, '/s/a'), value(d7, '/s/b'), value(d7, '/s/c/nested'), attr(d7, '/s', 'MATLAB_fields')),
                  ([1], 'text', [8, 1, 6, 3, 5, 7, 4, 9, 2], ['a', 'b', 'c']))
            check('a struct array: a field of numbers is one dataset, as [sa.y] gathers it',
                  (t['/sa/y']['shape'], t['/sa/y']['value'], attr(d7, '/sa', 'MATLAB_size')), ([1, 3], [10, 20, 30], '1×3'))
            check('  a field of strings likewise', t['/sa/z']['value'], ['p', 'q', 'r'])
            check('  a field of numbers and text a table of text, its classes said',
                  (t['/sa/m']['value'], attr(d7, '/sa/m', 'MATLAB_class')), (['1', 'two', ''], 'double, char'))
            check('  any other field a group of (1), (2), (3)',
                  [value(d7, f'/sa/x/({k})') for k in (1, 2, 3)], [[1], [1, 2], 'three'])
            check('an empty struct array is an empty group that says so',
                  (t['/s_empty'].get('group'), attr(d7, '/s_empty', 'MATLAB_size')), (True, '0×0'))
            check('a small sparse matrix is shown with its zeros',
                  (t['/sp']['value'], attr(d7, '/sp', 'MATLAB_sparse'), attr(d7, '/sp', 'nnz')),
                  ([1, 0, 0, 0, 0, 2, 3, 0, 0], 'TRUE', 3))
            check('  a large one as its values, rows and columns, counted from 1',
                  (len(value(d7, '/sp_big/row')), value(d7, '/sp_big/row')[:3], value(d7, '/sp_big/column')[-1],
                   attr(d7, '/sp_big', 'MATLAB_size')), (1100, [1, 2, 3], 1100, '1100×1100'))
            check('function handles are their text', (value(d7, '/fh'), value(d7, '/fh_named')), ('@(x)x.^2+1', '@sin'))
            check('a string array is its strings, a missing one said to be',
                  (t['/str_arr']['shape'], t['/str_arr']['value'], t['/str_missing']['value'], attr(d7, '/str_missing', 'missing')),
                  ([2, 2], ['alpha', 'beta', 'gamma', 'δέλτα'], ['<missing>', 'x', ''], 1))
            check('a table is its variables by name',
                  (value(d7, '/tbl/n'), value(d7, '/tbl/name'), attr(d7, '/tbl', 'MATLAB_class'), attr(d7, '/tbl', 'MATLAB_size')),
                  ([1, 2], ['a', 'b'], 'table', '2×2'))
            check('another object is the properties MATLAB saved',
                  (attr(d7, '/dt', 'MATLAB_class'), value(d7, '/dt/data')), ('datetime', [1793448000000]))
            check('a global variable says it is one', (value(d7, '/gv'), attr(d7, '/gv', 'MATLAB_global')), ([42], 'TRUE'))
            check('Level 4: numbers, text, complex and sparse',
                  [value(d4, p) for p in ['/v4_mat', '/v4_char', '/v4_cplx', '/v4_sp']],
                  [[8, 1, 6, 3, 5, 7, 4, 9, 2], ['ab', 'cd'], [[1, 2], [3, 0]], [0, 1, 2, 0]])

            # --- the page ----------------------------------------------------------
            shown = await page.ev("""(async () => {
                await __click('/d_mat', false);
                return document.getElementById('info').textContent; })()""", timeout=30)
            check('a variable clicked in the tree shows its shape, class and size',
                  all(s in shown for s in ['Shape', '4, 4', 'MATLAB_class', 'double', 'MATLAB_size', '4×4']), True)
            tip = await page.ev("""(() => {
                const tab = [...document.querySelectorAll('.file-tab')].find(t => t.dataset.file === 'matlab-v7.mat');
                tab.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, clientX: 100, clientY: 60 }));
                const text = document.getElementById('fileTabTooltip').textContent;
                tab.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));
                return text; })()""")
            check('the tab\'s tooltip says what the file is', ('matlab-v7.mat: MATLAB 5.0 MAT-file' in tip,
                  'MAT-file Level 5, compressed (-v7), 30 variables.' in tip), (True, True))

            # --- written here ------------------------------------------------------
            opened = await pick_files(page, [at('plain.mat'), at('bigendian.mat'), at('level4-be.mat')])
            dp = await dump(page, 'plain.mat')
            db = await dump(page, 'bigendian.mat')
            check('an uncompressed file reads', [value(dp, p) for p in ['/a', '/t', '/c', '/s/f', '/i']],
                  [[1, 2, 3, 4, 5, 6], 'text', ['7', 'x'], [9], [-5, 300]])
            check('  and the same file written big-endian reads the same', db['tree'], dp['tree'])
            check('a big-endian Level 4 file reads', value(await dump(page, 'level4-be.mat'), '/m'), [1, 2, 3, 4])

            await pick_files(page, [at('deep.mat'), at('damaged-zlib.mat'), at('huge.mat'), at('truncated.mat')])
            dd = await dump(page, 'deep.mat')
            check('arrays nested too deep: the variable says so, the next one reads',
                  (attr(dd, '/deep', 'MATLAB_note'), value(dd, '/after')),
                  ('This variable could not be read: its arrays are nested more than 64 deep', [2]))
            dz = await dump(page, 'damaged-zlib.mat')
            check('a damaged compressed variable: said so, the next one reads',
                  (attr(dz, '/unnamed variable', 'MATLAB_note'), value(dz, '/ok')),
                  ('This variable could not be read: a compressed variable is damaged', [5]))
            dh = await dump(page, 'huge.mat')
            check('a cell that says it is larger than its bytes is refused before it is made',
                  (attr(dh, '/huge', 'MATLAB_note'), value(dh, '/ok')),
                  ('This variable could not be read: the array huge says it holds more than its bytes can', [5]))
            dt = await dump(page, 'truncated.mat')
            tops = [p for p in dt['tree'] if p.count('/') == 1]
            check('a file cut short opens with the variables before the cut, and says where it ends',
                  (0 < len(tops) < 30, attr(dt, '/unnamed variable', 'MATLAB_note'), value(dt, '/c_mixed/{1,2}')),
                  (True, 'This variable could not be read: the file ends part of the way through a variable', 'two'))
            check('a variable that unpacks to more than may be read is not unpacked', await page.ev("""(async () => {
                const packed = %s;
                const bytes = Uint8Array.from(atob(packed), c => c.charCodeAt(0));
                try { await matInflate(bytes, { left: 4096 }); return 'unpacked'; }
                catch (e) { return /unpack to more than/.test(e.message); } })()"""
                % json.dumps(base64.b64encode(zlib.compress(b'\0' * 1000000)).decode())), True)

            # --- vectors drawn -------------------------------------------------------
            await pick_files(page, [at('vectors.mat')])
            v = await preview(page, '/v')
            check('a vector of doubles is drawn: a histogram of its values, under its name',
                  (v['shown'], v['vector'], [(t['type'], t['name'], t['n']) for t in v['traces']], v['x'], v['y']),
                  (True, True, [('histogram', 'v', 1000)], 'Value', 'Probability Density'))
            check('  Histogram and Scatter offered, Histogram pressed; log offered, the values all positive; a place is an Element',
                  (v['pressed'], v['log'], v['place']), ([['histogram', 'true'], ['scatter', 'false']], True, 'Element:'))
            await page.ev("document.querySelector('#histModeToggle button[data-mode=scatter]').click()")
            v = await page.ev(PREVIEW, timeout=30)
            check('Scatter: each value against its place, counted from 1',
                  (v['mode'], v['traces'][0]['type'], v['traces'][0]['n'], v['traces'][0]['x'], v['traces'][0]['y'], v['x'], v['y'], v['pressed']),
                  ('scatter', 'scatter', 1000, [1, 2, 3], VECTOR[:3], 'Element', 'Value', [['histogram', 'false'], ['scatter', 'true']]))
            await page.ev("document.getElementById('histStats').click()")
            v = await page.ev(PREVIEW, timeout=30)
            mean = sum(VECTOR) / len(VECTOR)
            levels = {t['name'].rsplit(' (', 1)[0]: t for t in v['traces'][1:]}
            check('  statistics are levels across it, from the first place to the last',
                  (sorted(levels), levels['Mean']['x'], levels['Mean']['y'][0]),
                  (sorted(['Mean', 'Geo. Mean', 'P5', 'P50 (median)', 'P95']), [1, 1000], mean))
            await page.ev("document.getElementById('histStats').click(); document.getElementById('histLogScale').click()")
            check('  Log₁₀ makes its value axis logarithmic', (await page.ev(PREVIEW, timeout=30))['yType'], 'log')
            await page.ev("""(() => { document.getElementById('histLogScale').click();
                const i = document.getElementById('histIterNum'); i.value = '5'; i.dispatchEvent(new Event('input', { bubbles: true })); })()""")
            v = await page.ev(PREVIEW, timeout=30)
            check('  the element asked for is ringed, and named with its value',
                  [(t['x'], t['y'], t['name']) for t in v['traces'][1:]], [([5], [VECTOR[4]], f'Element 5 ({VECTOR[4]:g})')])
            await page.ev("(() => { const i = document.getElementById('histIterNum'); i.value = ''; i.dispatchEvent(new Event('input', { bubbles: true })); })()")
            w = await preview(page, '/w')
            check('a single row vector is drawn too, still as a scatter; log not offered for values below zero',
                  (w['shown'], w['mode'], w['traces'][0]['n'], w['traces'][0]['y'], w['log']), (True, 'scatter', 50, [-25, -24, -23], False))
            g = await preview(page, '/gaps')
            check('  NaN and Inf keep their places in a scatter', (g['traces'][0]['n'], g['traces'][0]['y']), (5, [1, 'NaN', 3]))
            check('  a long one is drawn with WebGL', (await preview(page, '/long'))['traces'][0]['type'], 'scattergl')
            await page.ev("document.querySelector('#histModeToggle button[data-mode=histogram]').click()")
            g = await preview(page, '/gaps')
            check('  and a histogram counts only the finite values', (g['mode'], g['traces'][0]['type'], g['traces'][0]['n']), ('histogram', 'histogram', 3))
            iv = await preview(page, '/iv')
            check('a vector of integers is drawn as one of doubles is',
                  (iv['shown'], [(t['type'], t['name'], t['n']) for t in iv['traces']]), (True, [('histogram', 'iv', 5)]))
            check('a scalar is not drawn', (await preview(page, '/sc'))['shown'], False)

            # --- matrices drawn ------------------------------------------------------
            m = await preview(page, '/mtx')
            check('a matrix is drawn as a heatmap: a cell for each value, the first row at the top',
                  (m['shown'], m['traces'][0]['type'], m['traces'][0]['z'], m['x'], m['y'], m['yReversed'], m['colorbar']),
                  (True, 'heatmap', [[0, 3, 6, 9], [1, 4, 7, 10], [2, 5, 8, 11]], 'Column', 'Row', True, 'Value'))
            check('  Heatmap, Histogram and Scatter offered, Heatmap pressed; no element to ask for, no statistics',
                  (m['pressed'], m['element'], m['stats']),
                  ([['heatmap', 'true'], ['histogram', 'false'], ['scatter', 'false']], False, False))
            await page.ev("document.querySelector('#histModeToggle button[data-mode=scatter]').click()")
            m = await page.ev(PREVIEW, timeout=30)
            check('  Scatter: a series for each row of a matrix wider than it is tall, against its column',
                  ([(t['name'], t['n'], t['y']) for t in m['traces']], m['x']),
                  ([('Row 1', 4, [0, 3, 6]), ('Row 2', 4, [1, 4, 7]), ('Row 3', 4, [2, 5, 8])], 'Column'))
            v = await preview(page, '/v')
            check('  a vector keeps its own choice, a histogram', (v['mode'], v['traces'][0]['type']), ('histogram', 'histogram'))
            m = await preview(page, '/mtx')
            check('  and the matrix its own, a scatter', m['mode'], 'scatter')
            await page.ev("document.querySelector('#histModeToggle button[data-mode=histogram]').click()")
            m = await page.ev(PREVIEW, timeout=30)
            check('  Histogram: all its values', (m['mode'], [(t['type'], t['n']) for t in m['traces']]), ('histogram', [('histogram', 12)]))
            await page.ev("document.querySelector('#histModeToggle button[data-mode=heatmap]').click()")
            await page.ev("__click('/pm', false)")
            await page.ev("document.getElementById('histLogScale').checked || document.getElementById('histLogScale').click()")
            pm = await page.ev(PREVIEW, timeout=30)
            check('  Log₁₀ colours a positive matrix by the log of its values',
                  (pm['traces'][0]['z'], pm['colorbar']), ([[0, 1], [2, 3]], 'log₁₀(Value)'))
            await page.ev("document.getElementById('histLogScale').click()")
            nm = await preview(page, '/nm')
            check('  NaN and Inf leave their cells blank', nm['traces'][0]['z'], [[1, None], [None, 4]])
            big = await preview(page, '/big')
            check('a matrix of 120 columns and 150 rows: a heatmap, and no scatter of 120 series, saying why',
                  (big['traces'][0]['type'], big['disabled']), ('heatmap', [['scatter', 'More than 100 columns or rows to draw']]))
            await page.ev("__click('/mtx', false)")
            csv = await page.ev("""(async () => {
                await __wait(900);
                const keep = [URL.createObjectURL, HTMLAnchorElement.prototype.click];
                let blob = null;
                URL.createObjectURL = (b) => { blob = b; return 'blob:stub'; };
                HTMLAnchorElement.prototype.click = function () {};
                try { downloadChartData(); } finally { [URL.createObjectURL, HTMLAnchorElement.prototype.click] = keep; }
                return blob ? await blob.text() : null; })()""", timeout=30)
            check('  its CSV is the matrix, a line for each row', csv, '"mtx"\nRow,1,2,3,4\n1,0,3,6,9\n2,1,4,7,10\n3,2,5,8,11\n')
            said = await page.ev("""(async () => {
                const keep = notifyUser;
                let said = null;
                notifyUser = (m) => { said = m; };
                try { await downloadChartDataAsExcel(); } finally { notifyUser = keep; }
                return said; })()""", timeout=30)
            check('  and Excel, which has no heatmap, says where its values are',
                  said, "Excel draws no histogram or heatmap: Download Excel, under the dataset's information, writes its values.")
            c = await preview(page, '/cube')
            check('an array of three dimensions: a heatmap of its first slice, which says which',
                  (c['traces'][0]['type'], c['traces'][0]['name'], c['traces'][0]['z'], c['slice']),
                  ('heatmap', 'cube (:, :, 1)', [[0, 2, 4], [1, 3, 5]], 'of 4 · (:, :, 1)'))
            slice = "(n) => { const i = document.getElementById('histSliceNum'); i.value = String(n); i.dispatchEvent(new Event('input', { bubbles: true })); }"
            await page.ev(f"({slice})(4)")
            c = await page.ev(PREVIEW, timeout=30)
            check('  Slice 4 is A(:, :, 4)', (c['traces'][0]['z'], c['slice']), ([[18, 20, 22], [19, 21, 23]], 'of 4 · (:, :, 4)'))
            await page.ev("document.querySelector('#histModeToggle button[data-mode=histogram]').click()")
            c = await page.ev(PREVIEW, timeout=30)
            check('  and its histogram is the slice\'s values', [(t['type'], t['n']) for t in c['traces']], [('histogram', 6)])
            await page.ev("document.querySelector('#histModeToggle button[data-mode=heatmap]').click()")
            h = await preview(page, '/hyper')
            check('  another array starts at slice 1 again', h['slice'], 'of 6 · (:, :, 1, 1)')
            await page.ev(f"({slice})(5)")
            h = await page.ev(PREVIEW, timeout=30)
            check('  of four dimensions, its slices counted as MATLAB counts pages, the third fastest',
                  (h['traces'][0]['z'], h['slice']), ([[16, 18], [17, 19]], 'of 6 · (:, :, 1, 3)'))
            d3 = await preview(page, '/d_3d')
            await page.ev(f"({slice})(2)")
            d3 = await page.ev(PREVIEW, timeout=30)
            check('  MATLAB\'s own reshape(1:24, 2, 3, 4), slice 2', (d3['traces'][0]['z'], d3['slice']),
                  ([[7, 9, 11], [8, 10, 12]], 'of 4 · (:, :, 2)'))
            check('  a matrix has no slices to choose', (await preview(page, '/mtx'))['slice'], None)
            x = await preview(page, '/' + HOSTILE_VECTOR)
            check('a vector named with markup is drawn under its name as text; nothing runs',
                  (x['shown'], x['traces'][0]['name'], await page.ev("document.querySelectorAll('#plotlyChart img').length"),
                   await page.ev('typeof window.__matXss')), (True, HOSTILE_VECTOR, 0, 'undefined'))
            await pick_files(page, [at('vectors-b.mat')])
            # Two files in one chart: the two alone enabled, their trees joined (∪).
            check('two files with the same vector, their trees joined', await page.ev("""(async () => {
                for (const k of Object.keys(fileStates)) if (fileStates[k] && !['vectors.mat', 'vectors-b.mat'].includes(k)) toggleFileState(k);
                await __wait(800);
                document.querySelector('#treeModeContainer button[data-value="union"]').click();
                await __wait(1500);
                return [getEnabledFiles(), getTreeMode()]; })()""", timeout=60), [['vectors.mat', 'vectors-b.mat'], 'union'])
            two = await preview(page, '/v')
            check('two files open: a histogram of each', (two['vector'], [(t['type'], t['n']) for t in two['traces']]),
                  (True, [('histogram', 1000), ('histogram', 1000)]))
            await page.ev("document.querySelector('#histModeToggle button[data-mode=scatter]').click()")
            two = await page.ev(PREVIEW, timeout=30)
            check('  and a scatter of each', [(t['type'], t['n']) for t in two['traces']], [('scatter', 1000), ('scatter', 1000)])
            await page.ev("document.querySelector('#histModeToggle button[data-mode=histogram]').click()")
            two = await preview(page, '/mtx')
            check('  a matrix in each: their heatmaps side by side, each named',
                  ([(t['type'], t['xaxis']) for t in two['traces']], len(two['panels'])), ([('heatmap', 'x'), ('heatmap', 'x2')], 2))

            # --- hostile -----------------------------------------------------------
            await pick_files(page, [at('hostile.mat')])
            dx = await dump(page, 'hostile.mat')
            check('a name with markup is a name; one with / or .. is made a name HDF5 can hold',
                  sorted(dx['tree']), sorted(['/' + HOSTILE, '/s', '/s/_', '/s/a⁄b']))
            await page.ev(f"__click({json.dumps('/' + HOSTILE)}, false)")
            tip = await page.ev("""(() => {
                const tab = [...document.querySelectorAll('.file-tab')].find(t => t.dataset.file === 'hostile.mat');
                tab.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, clientX: 100, clientY: 60 }));
                const text = document.getElementById('fileTabTooltip').textContent;
                tab.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));
                return text; })()""")
            await page.ev('__wait(500)')
            check('  shown as text in the tree, the panel and the tooltip; nothing in them runs',
                  (await page.ev(f"!!__row({json.dumps('/' + HOSTILE)}, false)"), '<img' in tip,
                   await page.ev("document.querySelectorAll('#tree img, #info img, #fileTabTooltip img').length"),
                   await page.ev('typeof window.__matXss')), (True, True, 0, 'undefined'))

            # --- by content, by address, refused --------------------------------
            check('a MAT-file handed over under another name is still read as one',
                  [await ingest(page, 'handoff.h5', v7), await ingest(page, 'x.h5', open(fixture('matlab-v73.mat'), 'rb').read())],
                  [['handoff.h5'], ['x.h5']])
            check('  as MATLAB wrote it', [(await dump(page, n))['root'].get('MATLAB_format') for n in ('handoff.h5', 'x.h5')],
                  ['Level 5, compressed (-v7)', '7.3 (-v7.3, HDF5)'])
            check('an address ending in .mat keeps its name',
                  await page.ev("hdf5FileNameFromUrl(new URL('https://example.com/runs/result.mat'))"), 'result.mat')
            before = await page.ev('fileOrder.length')
            await pick_files(page, [at('notmat.mat')])
            banner = await page.ev("document.querySelector('#failureBanner .failure-banner-text')?.textContent || ''")
            check('a file named .mat that is no MAT-file is refused, saying why',
                  ('it starts with none of the headers MATLAB writes' in banner, await page.ev('fileOrder.length')), (True, before))

            expected_errors = ('none of the headers MATLAB writes', 'could not be read')
            check('no console errors but the refusal', [m for k, m in page.logs
                  if not any(e in m for e in expected_errors) and 'favicon' not in m][:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
