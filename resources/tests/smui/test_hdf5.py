#!/usr/bin/env python3
"""HDF5 files as tables (resources/js/smui-hdf5-read.js), outside the browser.

The fixtures are written here by the programs that write such files: h5py
(vectors, matrices, compound and enumerated types, text in both character
sets, both byte orders, float16, dimension scales, links, references,
compression, hostile names), pandas' to_hdf (fixed and table formats, with
PyTables), netCDF4 (CF dates, packing, fill values, char arrays, an
unlimited dimension), hdf5storage (MATLAB v7.3 files) and Kompartment's own
result writer (make-kompartment-h5.mjs: a run and a probabilistic run).

The page's reader runs on each through h5wasm's Node build (hdf5-read.mjs:
the inspect(), defaults(), plan() and read() the browser's worker runs),
and its tables are checked against what was written, as those programs
read it back: h5py, pd.read_hdf, netCDF4 with its masking and scaling,
hdf5storage.loadmat, the values Kompartment's writer was given. Then the
pickle reader on pickles of every protocol and on hostile ones, and what
the first bytes of a file say it is.

Needs node, numpy and h5py; pandas with PyTables, netCDF4 and hdf5storage
each add their checks (skipped without them). h5wasm's Node build comes
from local/h5wasm/ (git-ignored): copied from rb-vscode/node/h5wasm, or
fetched from jsDelivr, and checked against the hashes rb-vscode/build.mjs
pins for it either way.

    python3 resources/tests/smui/test_hdf5.py
"""
import base64
import datetime
import hashlib
import json
import math
import os
import pickle
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import warnings

import numpy as np
import h5py

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
LOCAL = os.path.join(HERE, 'local', 'h5wasm')
DRIVER = os.path.join(HERE, 'hdf5-read.mjs')
# h5wasm 0.10.3's Node build, as rb-vscode/build.mjs pins it
H5WASM = {
    'hdf5_hl.js': ('https://cdn.jsdelivr.net/npm/h5wasm@0.10.3/dist/node/hdf5_hl.js', 'sha384-QKBAPPTKU9XHH3lAoW5hl4rfG/HPYTKR/DL0ACyi7nPmCt/GnloB2C6tDRZg/41x'),
    'hdf5_util.js': ('https://cdn.jsdelivr.net/npm/h5wasm@0.10.3/dist/node/hdf5_util.js', 'sha384-AVanQsMzkodQFWEOGoE6PzX1XzHnUG4IbSjwE8Om6l1Lckxmx9NMKL1JP6wue6by'),
}
MAX_CELLS = 50e6


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, got, want=True):
        self.n += 1
        ok = got == want
        print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {str(got)[:600]} (expected {str(want)[:600]})'))
        if not ok:
            self.failed.append(label)
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        if self.failed:
            print('failed:', *self.failed, sep='\n  ')
        return 0 if not self.failed else 1


check = Checks()


def sri(data):
    return 'sha384-' + base64.b64encode(hashlib.sha384(data).digest()).decode()


def h5wasm_dir():
    """h5wasm's Node build in local/h5wasm, each file as its pin says."""
    os.makedirs(LOCAL, exist_ok=True)
    for name, (url, pin) in H5WASM.items():
        dest = os.path.join(LOCAL, name)
        if os.path.isfile(dest) and sri(open(dest, 'rb').read()) == pin:
            continue
        built = os.path.join(REPO, 'rb-vscode', 'node', 'h5wasm', name)
        if os.path.isfile(built) and sri(open(built, 'rb').read()) == pin:
            shutil.copyfile(built, dest)
            continue
        try:
            with urllib.request.urlopen(url, context=ssl.create_default_context()) as r:
                data = r.read()
        except (urllib.error.URLError, ssl.SSLError):
            # without certificates Python can use: curl, with the system's
            data = subprocess.run(['curl', '-fsSL', url], check=True, capture_output=True).stdout
        if sri(data) != pin:
            raise SystemExit(f'{url}: not the pinned build')
        with open(dest, 'wb') as w:
            w.write(data)
        print('fetched', name)
    with open(os.path.join(LOCAL, 'package.json'), 'w') as w:
        w.write('{ "type": "module" }')
    return LOCAL


TMP = tempfile.mkdtemp(prefix='smui-h5-')
H5DIR = h5wasm_dir()


def run(mode, path, state=None):
    args = ['node', DRIVER, H5DIR, mode, path]
    if state is not None:
        sp = os.path.join(TMP, 'state.json')
        with open(sp, 'w') as w:
            json.dump(state, w)
        args.append(sp)
    r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f'{mode} {path}: {r.stderr[-3000:]}')
    return json.loads(r.stdout)


def read(name, state=None):
    out = run('read', os.path.join(TMP, name), state)
    out['node'] = {n['path']: n for n in out['nodes']}
    for t in out['tables']:
        for c in t['columns']:
            # (JSON writes a whole double without a point: back to a float)
            if c['dataType'] == 'numeric':
                c['values'] = [float(v) if isinstance(v, int) else v for v in c['values']]
        t['col'] = {c['name']: c for c in t['columns']}
    return out


def fin(v):
    """A value as the driver writes it: NaN null, infinities as text."""
    if isinstance(v, (float, np.floating)):
        v = float(v)
        return None if math.isnan(v) else 'inf' if v == math.inf else '-inf' if v == -math.inf else v
    if isinstance(v, (np.integer,)):
        return float(v)
    return v


def nums(a):
    return [fin(float(x)) for x in np.asarray(a, dtype='f8').ravel()]


def texts(a):
    out = []
    for x in a:
        if isinstance(x, bytes):
            x = x.decode('utf-8')
        out.append(None if x is None or x == '' else str(x))
    return out


def ms(dt):
    return (dt - datetime.datetime(1970, 1, 1)).total_seconds() * 1000


def table(out, name):
    for t in out['tables']:
        if t['name'] == name:
            return t
    raise KeyError(f'no table {name}: {[t["name"] for t in out["tables"]]}')


# ---- what the first bytes say ------------------------------------------------
def sniffs():
    files = {}
    p = os.path.join(TMP, 'sig.h5')
    with h5py.File(p, 'w') as f:
        f['x'] = [1.0]
    files['hdf5'] = p
    p = os.path.join(TMP, 'ub.h5')
    with h5py.File(p, 'w', userblock_size=512) as f:
        f['x'] = [1.0]
    with open(p, 'r+b') as w:
        w.write(b'MATLAB 7.3 MAT-file, Platform: x, Created on: y HDF5 schema 1.00 .')
    files['userblock'] = p
    for kind, head in [('netcdf3', b'CDF\x01\x00\x00\x00\x00'), ('netcdf3b', b'CDF\x02\x00\x00\x00\x00'), ('mat5', b'MATLAB 5.0 MAT-file, Platform: PCWIN64'), ('hdf4', b'\x0e\x03\x13\x01' + b'\0' * 20),
                       ('text', b'a,b\n1,2\n'), ('empty', b'')]:
        p = os.path.join(TMP, f'sig-{kind}')
        with open(p, 'wb') as w:
            w.write(head + b'\0' * 100 if head else b'')
        files[kind] = p
    want = {'hdf5': 'hdf5', 'userblock': 'hdf5', 'netcdf3': 'netcdf3', 'netcdf3b': 'netcdf3', 'mat5': 'mat5', 'hdf4': 'hdf4', 'text': None, 'empty': None}
    check('sniff: HDF5 at 0 and after a 512-byte user block (MATLAB v7.3); netCDF-3, MATLAB 5, HDF4 told apart; text and nothing are none',
          {k: run('sniff', p)['kind'] for k, p in files.items()}, want)


# ---- h5py: vectors, matrices, keys, links, the unreadable --------------------
def basic():
    rng = np.random.default_rng(7)
    n = 12
    x = rng.normal(size=n)
    x[3] = np.nan
    x[5] = np.inf
    i32 = np.arange(n, dtype='i4') - 5
    u8 = (np.arange(n) * 20).astype('u1')
    big = np.array([2 ** 60 + 1, -3] + list(range(n - 2)), dtype='i8')
    flag = np.array([True, False] * (n // 2))
    lvl = np.array([0, 1, 5] * (n // 3), dtype='i1')
    fixed = np.array([b'a', b'bb', b'', 'café'.encode(), b'x' * 8] + [b'k%d' % i for i in range(n - 5)], dtype='S8')
    vls = ['x', 'åäö', '', 'two\nlines', '<b>no</b>'] + [f'v{i}' for i in range(n - 5)]
    f16 = (np.arange(n) / 4 - 1).astype('f2')
    be = (np.arange(n) * 1.5).astype('>f8')
    m = rng.integers(0, 9, size=(n, 3)).astype('f8')
    mm = rng.normal(size=(n, 2))
    y1, y2 = rng.normal(size=n), rng.normal(size=n)
    with h5py.File(os.path.join(TMP, 'basic.h5'), 'w') as f:
        f['x'] = x
        f['i32'] = i32
        f['u8'] = u8
        f['big'] = big
        f['flag'] = flag
        f.create_dataset('level', data=lvl, dtype=h5py.enum_dtype({'low': 0, 'mid': 1, 'high': 5}, basetype='i1'))
        f['fixed'] = fixed
        f.create_dataset('vls', data=np.array(vls, dtype=object), dtype=h5py.string_dtype())
        f['f16'] = f16
        f['be'] = be
        f['m'] = m
        f['m'].attrs['columns'] = np.array(['a', 'b', 'c'], dtype=h5py.string_dtype())
        f['mm'] = mm
        f.create_dataset('gz', data=x * 2, chunks=(4,), compression='gzip', shuffle=True)
        f['grp/y'] = y1
        f['grp/y'].attrs['units'] = 'Bq'
        f['grp/y'].attrs['long_name'] = 'activity'
        f['grp2/y'] = y2
        f['scalar'] = 3.25
        f['scalar'].attrs['unit'] = 'kg'
        f['label'] = 'hello'
        f['soft'] = h5py.SoftLink('/grp/y')
        f['broken'] = h5py.SoftLink('/nowhere')
        f['ext'] = h5py.ExternalLink('other.h5', '/x')
        f['ref'] = f['grp'].ref
        f['opaque'] = np.void(b'\x01\x02\x03')
        f['empty'] = h5py.Empty('f8')
        f['zero'] = np.zeros(0)
        v = f.create_dataset('vlen', (2,), dtype=h5py.vlen_dtype(np.dtype('i4')))
        v[0] = [1, 2]
        f['lzf'] = np.arange(50.0)
        del f['lzf']
        f.create_dataset('lzf', data=np.arange(50.0), chunks=(10,), compression='lzf')
        f.create_dataset('huge', shape=(2 ** 36,), dtype='f8', chunks=(1024,))
    out = read('basic.h5')
    nd = out['node']
    check('basic: forms', {p: nd[p]['form'] for p in ['/x', '/m', '/mm', '/scalar', '/label', '/grp/y', '/lzf']},
          {'/x': 'vector', '/m': 'matrix', '/mm': 'matrix', '/scalar': 'scalar', '/label': 'scalar', '/grp/y': 'vector', '/lzf': 'vector'})
    check('basic: links are links, not data', {p: (nd[p]['kind'], nd[p]['target']) for p in ['/soft', '/broken', '/ext']},
          {'/soft': ('link', '/grp/y'), '/broken': ('broken', '/nowhere'), '/ext': ('external', 'other.h5:/x')})
    why = {p: nd[p]['why'] for p in ['/ref', '/opaque', '/empty', '/zero', '/vlen', '/huge']}
    check('basic: what is not read says why', why, {'/ref': 'references to other objects (not read)', '/opaque': 'opaque bytes (not read)', '/empty': 'empty (no dataspace)',
                                                   '/zero': 'empty', '/vlen': 'variable-length sequences (not read)', '/huge': 'too large (68,719,476,736 values)'})
    check('basic: type texts', {p: nd[p]['typeText'] for p in ['/x', '/i32', '/u8', '/big', '/flag', '/level', '/fixed', '/vls', '/f16']},
          {'/x': 'float64', '/i32': 'int32', '/u8': 'uint8', '/big': 'int64', '/flag': 'true/false', '/level': 'enum (3 levels)', '/fixed': 'text', '/vls': 'text', '/f16': 'float16'})
    check('basic: ticked when it opens: every vector, both matrices and the single values', out['defaults']['picked'],
          sorted(['/x', '/i32', '/u8', '/big', '/flag', '/level', '/fixed', '/vls', '/f16', '/be', '/m', '/mm', '/gz', '/grp/y', '/grp2/y', '/lzf', '/scalar', '/label']))
    check('basic: not opened without asking (it is more than one table)', out['defaults']['direct'], False)
    plan = out['plan']['tables']
    check('basic: the ticks make a table per length (12 and 50 rows), and one of the single values', sorted((t['name'], t['rows'], t['cols']) for t in plan),
          [('basic — 12 rows', 12, 18), ('basic — lzf', 50, 1), ('basic — values', 2, 4)])
    t = table(out, 'basic — 12 rows')
    c = t['col']
    check('basic: column order follows the file, matrices after the columns', [x['name'] for x in t['columns']],
          ['be', 'big', 'f16', 'fixed', 'flag', 'grp/y', 'grp2/y', 'gz', 'i32', 'level', 'u8', 'vls', 'x', 'a', 'b', 'c', 'mm 1', 'mm 2'])
    check('basic: float64 as written (NaN missing, inf kept)', c['x']['values'], nums(x))
    check('basic: int32, uint8 and big-endian float64', (c['i32']['values'], c['u8']['values'], c['be']['values']), (nums(i32), nums(u8), nums(be)))
    check('basic: int64 to the nearest double', c['big']['values'], [float(v) for v in big])
    check('basic: ... and the notes say so', 'beyond 2^53 rounded' in t['notes'], True)
    check('basic: float16 decoded', c['f16']['values'], nums(f16))
    check('basic: bool: 0/1 with labels', (c['flag']['values'], c['flag']['valueLabels'], c['flag']['modelingType']), ([float(v) for v in flag], [[0, 'FALSE'], [1, 'TRUE']], 'nominal'))
    check('basic: enum: codes with their names', (c['level']['values'], c['level']['valueLabels']), ([float(v) for v in lvl], [[0, 'low'], [1, 'mid'], [5, 'high']]))
    check('basic: fixed-length text (UTF-8 in an ASCII string kept; empty missing)', c['fixed']['values'], texts(fixed))
    check('basic: variable-length UTF-8 text, a line break kept', c['vls']['values'], texts(vls))
    check('basic: a matrix named by its columns attribute', (c['a']['values'], c['b']['values'], c['c']['values']), (nums(m[:, 0]), nums(m[:, 1]), nums(m[:, 2])))
    check('basic: a matrix without names, numbered from 1', (c['mm 1']['values'], c['mm 2']['values']), (nums(mm[:, 0]), nums(mm[:, 1])))
    check('basic: compressed (gzip and shuffle)', c['gz']['values'], nums(x * 2))
    check('basic: two y told apart by their groups', (c['grp/y']['values'], c['grp2/y']['values']), (nums(y1), nums(y2)))
    check('basic: a unit and a long name in the notes', c['grp/y']['notes'], '/grp/y; unit: Bq; activity')
    check('basic: lzf with no decoder loaded (Node has no plugins): its table is not made, and the reason is given', out['failed'],
          [{'name': 'basic — lzf', 'why': '/lzf: compressed with lzf, and its decoder did not load'}])
    out2 = read('basic.h5', {'picked': ['/m'], 'transposed': ['/m']})
    t = out2['tables'][0]
    check('basic: a matrix swapped: a row per column', (t['name'], len(t['columns']), [len(x['values']) for x in t['columns']][:2]), ('basic', 12, [3, 3]))
    check('basic: ... its values', t['columns'][4]['values'], nums(m[4, :]))
    out3 = read('basic.h5', {'picked': ['/scalar', '/label']})
    t = out3['tables'][0]
    check('basic: single values: a row each, name, value (text apart), unit', [(x['name'], x['values']) for x in t['columns']],
          [('Name', ['label', 'scalar']), ('Value', [None, 3.25]), ('Text', ['hello', None]), ('Unit', [None, 'kg'])])
    out4 = read('basic.h5', {'picked': ['/x', '/i32'], 'together': False})
    check('basic: Side by side off: a table each', [(t['name'], [c['name'] for c in t['columns']]) for t in out4['tables']], [('basic — i32', ['i32']), ('basic — x', ['x'])])


# ---- compound types -------------------------------------------------------------
def compound():
    dt = np.dtype([('id', 'i4'), ('x', 'f8'), ('name', 'S6'), ('v', h5py.string_dtype()), ('arr', 'f4', (3,)), ('flag', '?'),
                   ('nest', [('a', 'i2'), ('b', 'f4')]), ('c', 'c16'), ('e', h5py.enum_dtype({'A': 1, 'B': 2}, basetype='u1'))])
    a = np.zeros(4, dt)
    a['id'] = [7, 8, 9, 10]
    a['x'] = [0.5, np.nan, -np.inf, 1e300]
    a['name'] = [b'p', b'qq', b'', b'r']
    a['v'] = ['vv', 'wé', '', 'z']
    a['arr'] = np.arange(12).reshape(4, 3)
    a['flag'] = [True, False, True, False]
    a['nest']['a'] = [3, 4, -5, 6]
    a['nest']['b'] = [0.25, 0.5, 0.75, 1.0]
    a['c'] = [1 + 2j, 3 - 4j, 0, -1j]
    a['e'] = [1, 2, 2, 1]
    be = np.zeros(3, np.dtype([('p', '>f8'), ('q', '>i4')]))
    be['p'] = [1.5, -2.25, 1e10]
    be['q'] = [1, -2, 2 ** 31 - 1]
    mixed = np.zeros(3, np.dtype([('p', '>f8'), ('q', '<i4'), ('r', '>u2')]))
    mixed['p'] = [1.5, -2.25, 1e10]
    mixed['q'] = [1, -2, 2 ** 31 - 1]
    mixed['r'] = [0, 65535, 7]
    grid = np.zeros((2, 3), np.dtype([('u', 'f8'), ('w', 'i4')]))
    grid['u'] = np.arange(6).reshape(2, 3) / 2
    grid['w'] = np.arange(6).reshape(2, 3) * 10
    with h5py.File(os.path.join(TMP, 'compound.h5'), 'w') as f:
        f['table'] = a
        f['be'] = be
        f['mixed'] = mixed
        f['grid'] = grid
        f['rec'] = np.array((1.5, 2), dtype=[('s', 'f8'), ('k', 'i4')])
    out = read('compound.h5', {'picked': ['/table']})
    c = out['tables'][0]['col']
    check('compound: a column per field, nested and array fields spread', list(c), ['id', 'x', 'name', 'v', 'arr[1]', 'arr[2]', 'arr[3]', 'flag', 'nest.a', 'nest.b', 'c.r', 'c.i', 'e'])
    check('compound: numbers', (c['id']['values'], c['x']['values'], c['nest.a']['values'], c['nest.b']['values']), (nums(a['id']), nums(a['x']), nums(a['nest']['a']), nums(a['nest']['b'])))
    check('compound: array fields', [c[f'arr[{k}]']['values'] for k in (1, 2, 3)], [nums(a['arr'][:, k]) for k in range(3)])
    check('compound: complex as real and imaginary parts', (c['c.r']['values'], c['c.i']['values']), (nums(a['c'].real), nums(a['c'].imag)))
    check('compound: text fields, fixed and variable length', (c['name']['values'], c['v']['values']), (texts(a['name']), texts(a['v'])))
    check('compound: bool and enum fields with labels', (c['flag']['valueLabels'], c['e']['values'], c['e']['valueLabels']), ([[0, 'FALSE'], [1, 'TRUE']], nums(a['e']), [[1, 'A'], [2, 'B']]))
    out = read('compound.h5', {'picked': ['/be', '/mixed'], 'together': False})
    tb, tm = table(out, 'compound — be')['col'], table(out, 'compound — mixed')['col']
    check('compound: big-endian fields (every one)', (tb['p']['values'], tb['q']['values']), (nums(be['p']), nums(be['q'])))
    check('compound: fields of both byte orders in one type', (tm['p']['values'], tm['q']['values'], tm['r']['values']), (nums(mixed['p']), nums(mixed['q']), nums(mixed['r'])))
    out = read('compound.h5', {'picked': ['/grid', '/rec'], 'together': False})
    g = table(out, 'compound — grid')
    check('compound: 2-D, stacked with its positions', [(x['name'], x['values']) for x in g['columns']],
          [('grid dimension 1', [1.0, 1.0, 1.0, 2.0, 2.0, 2.0]), ('grid dimension 2', [1.0, 2.0, 3.0, 1.0, 2.0, 3.0]), ('grid.u', nums(grid['u'])), ('grid.w', nums(grid['w']))])
    r = table(out, 'compound — rec')
    check('compound: a scalar record is one row', [(x['name'], x['values']) for x in r['columns']], [('s', [1.5]), ('k', [2.0])])


# ---- larger arrays, dimension scales, CF dates ------------------------------------
def cubes():
    rng = np.random.default_rng(3)
    v = rng.normal(size=(4, 3, 2)).astype('f4')
    with h5py.File(os.path.join(TMP, 'cube.h5'), 'w') as f:
        t = f.create_dataset('time', data=np.array([0, 1, 2, 31], dtype='f8'))
        t.attrs['units'] = 'days since 2001-01-01'
        t.make_scale('time')
        s = f.create_dataset('site', data=np.array(['north', 'south', 'east'], dtype=object), dtype=h5py.string_dtype())
        s.make_scale('site')
        d = f.create_dataset('depth', data=np.array([0.5, 2.0]))
        d.make_scale('depth')
        c = f.create_dataset('conc', data=v)
        c.attrs['units'] = 'mg/l'
        for i, sc in enumerate([t, s, d]):
            c.dims[i].attach_scale(sc)
        f['four'] = np.arange(12.0).reshape(2, 1, 3, 2)
    out = read('cube.h5', {'picked': ['/conc', '/four'], 'together': False})
    t = table(out, 'cube — conc')
    names = [c['name'] for c in t['columns']]
    check('cube: stacked, a column per dimension named by its scale', names, ['time', 'site', 'depth', 'conc'])
    days = [ms(datetime.datetime(2001, 1, 1) + datetime.timedelta(days=d)) for d in (0, 1, 2, 31)]
    check('cube: the time scale as dates (CF days since)', (t['col']['time']['values'][:7], t['col']['time']['format']), ([days[0]] * 6 + [days[1]], {'kind': 'date'}))
    check('cube: the text scale', t['col']['site']['values'][:6], ['north', 'north', 'south', 'south', 'east', 'east'])
    check('cube: the values, C order', t['col']['conc']['values'], nums(v))
    f4 = table(out, 'cube — four')
    check('cube: a dimension of 1 left out', [(c['name'], c['values'][:4]) for c in f4['columns']],
          [('four dimension 1', [1.0, 1.0, 1.0, 1.0]), ('four dimension 2', [1.0, 1.0, 2.0, 2.0]), ('four dimension 3', [1.0, 2.0, 1.0, 2.0]), ('four', [0.0, 1.0, 2.0, 3.0])])
    out = read('cube.h5', {'picked': ['/time', '/site']})
    check('cube: scales ticked on their own: a table each, in the file\'s order', [(t['name'], [c['name'] for c in t['columns']]) for t in out['tables']], [('cube — site', ['site']), ('cube — time', ['time'])])


# ---- hostile names and attributes ---------------------------------------------
def hostile():
    evil = '<img src=x onerror="window.__h5pwned=1">'
    with h5py.File(os.path.join(TMP, 'hostile.h5'), 'w') as f:
        f.attrs['Information'] = '<p>Run <b>one</b></p><script>window.__h5pwned=2</script>&lt;ok&gt;'
        f.attrs['title'] = 'line1\nline2 <svg onload=alert(1)>'
        g = f.create_group(evil)
        d = g.create_dataset('a\nb', data=np.arange(3.0))
        d.attrs['units'] = '<script>alert(1)</script>'
        g.create_dataset('x y', data=np.arange(3.0))
        f.create_dataset('wide', shape=(2,), dtype=np.dtype([('a', 'u1', (5000,)), ('b', 'f8')]))
    out = read('hostile.h5')
    t = out['tables'][0]
    check('hostile: names come through as text (the page cleans line breaks)', [c['name'] for c in t['columns']], ['a\nb', 'x y'])
    check('hostile: markup in Information is text in the notes, its script never a tag', ('<script>' in t['notes'], 'Run one' in t['notes'], '<ok>' in t['notes']), (False, True, True))
    check('hostile: an array field of 5000 members is not spread into columns; the rest of the type is read', (out['node']['/wide']['form'], out['node']['/wide']['cols']), ('compound', 1))
    w = read('hostile.h5', {'picked': ['/wide']})['tables'][0]
    check('hostile: ... and the notes say what was left out', ([c['name'] for c in w['columns']], 'a (an array type too large to spread into columns)' in w['notes']), (['b'], True))


# ---- pandas ------------------------------------------------------------------
def pandas_files():
    try:
        import pandas as pd
        import tables  # noqa: F401
    except ImportError:
        print('(pandas with PyTables is not installed: the pandas checks are skipped)')
        return
    warnings.simplefilter('ignore')
    df = pd.DataFrame({
        'a': [1.5, 2.5, np.nan, -4.0],
        'n': np.array([1, 2, 3, 2 ** 40], dtype='i8'),
        's': ['x', None, 'zz', 'åäö'],
        'd': pd.to_datetime(['2020-01-01', '2021-06-30 12:00', None, '1969-12-31'], format='ISO8601'),
        'b': [True, False, True, True],
        'mixed': [1, 'a', None, 2.5],
    }, index=['r1', 'r2', 'r3', 'r4'])
    p = os.path.join(TMP, 'pd-fixed.h5')
    df.to_hdf(p, key='frame', format='fixed')
    df.reset_index(drop=True).drop(columns=['mixed']).to_hdf(p, key='plain', format='fixed')
    pd.Series([1.0, 2.0, np.nan], name='ser', index=[10, 20, 30]).to_hdf(p, key='ser')
    dt = df.drop(columns=['mixed']).copy()
    dt['cat'] = pd.Categorical(['lo', 'hi', 'lo', None], categories=['lo', 'hi'], ordered=True)
    dt['un'] = pd.Categorical(['b', 'a', 'b', 'a'])
    dt.index = [10, 11, 12, 13]
    q = os.path.join(TMP, 'pd-table.h5')
    dt.to_hdf(q, key='frame', format='table', data_columns=['n'])
    dt.reset_index(drop=True).to_hdf(q, key='range', format='table')
    pd.Series(['u', 'v', None], name='s').to_hdf(q, key='sert', format='table')
    df.set_index(['n', 'a']).drop(columns=['mixed']).to_hdf(os.path.join(TMP, 'pd-multi.h5'), key='m', format='fixed')

    def compare(out, name, frame, label):
        t = table(out, name)
        cols = {c['name']: c for c in t['columns']}
        want = [] if list(frame.index) == list(range(len(frame))) else ['index']
        want += [str(c) for c in frame.columns]
        check(f'{label}: the columns, in order (the index first unless it is 0, 1, 2 …)', list(cols), want)
        if 'index' in cols:
            idx = frame.index
            check(f'{label}: the index', cols['index']['values'], texts(idx) if idx.dtype == object or str(idx.dtype) == 'str' else nums(idx))
        for c in frame.columns:
            s = frame[c]
            got = cols[str(c)]
            if isinstance(s.dtype, pd.CategoricalDtype):
                check(f'{label}: {c}, a category: its levels, order and kind', (got['values'], got['valueOrder'], got['modelingType']),
                      ([None if pd.isna(v) else str(v) for v in s], [str(v) for v in s.cat.categories], 'ordinal' if s.cat.ordered else 'nominal'))
            elif pd.api.types.is_datetime64_any_dtype(s):
                check(f'{label}: {c}, datetimes as ms (NaT missing)', got['values'], [None if pd.isna(v) else ms(v.to_pydatetime().replace(tzinfo=None)) for v in s])
            elif pd.api.types.is_bool_dtype(s):
                check(f'{label}: {c}, bool as 0/1', (got['values'], got['valueLabels']), ([float(v) for v in s], [[0, 'False'], [1, 'True']]))
            elif pd.api.types.is_numeric_dtype(s):
                check(f'{label}: {c}, numbers', got['values'], nums(s.to_numpy(dtype='f8')))
            else:
                check(f'{label}: {c}, text (None missing; other values as text)', got['values'], [None if (v is None or (isinstance(v, float) and math.isnan(v))) else str(v) for v in s])

    out = read('pd-fixed.h5', {'picked': 'all'})
    nd = out['node']
    check('pandas fixed: each object is one item, its parts hidden', (nd['/frame']['form'], nd['/frame']['readable'], nd['/frame/axis0']['hidden']), ('pandas', True, 'pandas'))
    back = pd.read_hdf(p, 'frame')
    compare(out, 'pd-fixed — frame', back, 'pandas fixed frame')
    compare(out, 'pd-fixed — plain', pd.read_hdf(p, 'plain'), 'pandas fixed, a RangeIndex')
    s = pd.read_hdf(p, 'ser')
    t = table(out, 'pd-fixed — ser')
    check('pandas fixed series: index and values', [(c['name'], c['values']) for c in t['columns']], [('index', nums(s.index)), ('ser', nums(s))])
    out = read('pd-table.h5', {'picked': 'all'})
    compare(out, 'pd-table — frame', pd.read_hdf(q, 'frame'), 'pandas table frame')
    compare(out, 'pd-table — range', pd.read_hdf(q, 'range'), 'pandas table, a RangeIndex')
    s = pd.read_hdf(q, 'sert')
    check('pandas table series: named as the Series is, None missing', [(c['name'], c['values']) for c in table(out, 'pd-table — sert')['columns']], [(s.name, texts(s.fillna('')))])
    out = read('pd-multi.h5')
    check('pandas: a MultiIndex is said, not read', (out['node']['/m']['readable'], 'MultiIndex' in (out['node']['/m']['why'] or '')), (False, True))


# ---- netCDF-4 ------------------------------------------------------------------
def netcdf():
    try:
        import netCDF4
    except ImportError:
        print('(netCDF4 is not installed: the netCDF checks are skipped)')
        return
    p = os.path.join(TMP, 'clim.nc')
    nt = 5
    with netCDF4.Dataset(p, 'w') as ds:
        ds.title = 'smui test'
        ds.createDimension('time', None)
        ds.createDimension('station', 3)
        ds.createDimension('nchar', 4)
        ds.createDimension('lat', 2)
        ds.createDimension('lon', 2)
        t = ds.createVariable('time', 'f8', ('time',))
        t.units = 'hours since 2000-01-01 00:00:00'
        t.calendar = 'standard'
        t[:] = [0, 6, 12, 18, 30]
        name = ds.createVariable('name', str, ('station',))
        name[:] = np.array(['Forsmark', 'Laxemar', 'Åspö'], dtype=object)
        code = ds.createVariable('code', 'S1', ('station', 'nchar'))
        code[:] = np.array([list(b'FMK'.ljust(4)), list(b'LAX'.ljust(4)), list(b'ASP'.ljust(4))], dtype='u1').view('S1')
        temp = ds.createVariable('temp', 'i2', ('time', 'station'), fill_value=-32767)
        temp.scale_factor = 0.01
        temp.add_offset = 273.15
        temp.units = 'K'
        temp[:] = np.ma.masked_array(np.arange(15).reshape(5, 3) * 1.5 + 270, mask=np.eye(5, 3, dtype=bool))
        pr = ds.createVariable('precip', 'f4', ('time',))
        pr.missing_value = np.float32(-999)
        pr[:] = np.ma.masked_array([0.5, 1.0, -999, 2.0, 0.0], mask=[0, 0, 1, 0, 0])
        lat = ds.createVariable('lat', 'f4', ('lat',))
        lat[:] = [57.1, 57.4]
        lon = ds.createVariable('lon', 'f4', ('lon',))
        lon[:] = [16.4, 18.2]
        fld = ds.createVariable('field', 'f8', ('time', 'lat', 'lon'), fill_value=1e20)
        fld[:] = np.arange(nt * 4).reshape(nt, 2, 2) / 3
        fld[1, 0, 1] = np.ma.masked
    out = read('clim.nc')
    nd = out['node']
    check('netCDF: a dimension without a variable is hidden; the coordinates are row keys', (nd['/station']['hidden'], nd['/time']['key'], nd['/lat']['key']), ('netcdf-dimension', True, True))
    with netCDF4.Dataset(p) as ds:
        tv = ds['time']
        times = [ms(d.replace(tzinfo=None)) if not hasattr(d, '_to_real_datetime') else ms(datetime.datetime(d.year, d.month, d.day, d.hour, d.minute, d.second)) for d in netCDF4.num2date(tv[:], tv.units, tv.calendar, only_use_cftime_datetimes=False)]
        temp = ds['temp'][:]
        pr = ds['precip'][:]
        fld = ds['field'][:]
        lat, lon = ds['lat'][:], ds['lon'][:]
    t = table(out, 'clim — 5 rows')
    c = t['col']
    check('netCDF: the time first, as date-times (CF hours since)', (list(c)[0], c['time']['values'], c['time']['format']), ('time', times, {'kind': 'datetime'}))
    check('netCDF: packed int16 unpacked, fill values missing (as netCDF4 reads them)', [c[f'temp {k}']['values'] for k in (1, 2, 3)],
          [[None if temp.mask[i, k] else fin(float(temp[i, k])) for i in range(5)] for k in range(3)])
    check('netCDF: missing_value is missing', c['precip']['values'], [None if m else fin(float(v)) for v, m in zip(pr.data, np.ma.getmaskarray(pr))])
    s = table(out, 'clim — 3 rows')['col']
    check('netCDF: strings, and a char array as text', (s['name']['values'], s['code']['values']), (['Forsmark', 'Laxemar', 'Åspö'], ['FMK', 'LAX', 'ASP']))
    f = table(out, 'clim — field')
    check('netCDF: a 3-D variable stacked over its coordinates', [c['name'] for c in f['columns']], ['time', 'lat', 'lon', 'field'])
    check('netCDF: ... its coordinates and values (the fill missing)', (f['col']['lat']['values'][:4], f['col']['lon']['values'][:4], f['col']['field']['values']),
          (nums([lat[0], lat[0], lat[1], lat[1]]), nums([lon[0], lon[1], lon[0], lon[1]]), [None if m else fin(float(v)) for v, m in zip(fld.data.ravel(), np.ma.getmaskarray(fld).ravel())]))


# ---- MATLAB v7.3 ---------------------------------------------------------------
def matlab():
    try:
        import hdf5storage
    except ImportError:
        print('(hdf5storage is not installed: the MATLAB checks are skipped)')
        return
    A = np.arange(12.0).reshape(3, 4) / 4
    I = np.array([[1, -2], [3, 4], [5, 6]], dtype='i4')
    L = np.array([[True, False], [False, True], [True, True]])
    p = os.path.join(TMP, 'mlab.mat')
    hdf5storage.savemat(p, {'A': A, 'v': np.arange(5.0).reshape(5, 1), 'r': np.arange(4.0).reshape(1, 4) + 10, 's': 'hello', 'I': I, 'L': L,
                            'st': {'x': np.arange(3.0).reshape(3, 1), 'y': np.array([[9.0], [8.0], [7.0]])}}, format='7.3', matlab_compatible=True)
    out = read('mlab.mat', {'picked': 'all'})
    nd = out['node']
    check('MATLAB: transposed back (rows as MATLAB has them)', (nd['/A']['transposed'], nd['/I']['transposed']), (True, True))
    t = table(out, 'mlab — 3 rows')
    c = t['col']
    check('MATLAB: A as MATLAB shows it, 3 rows × 4 columns', [c[f'A {k}']['values'] for k in (1, 2, 3, 4)], [nums(A[:, k]) for k in range(4)])
    check('MATLAB: int32 matrix', [c[f'I {k}']['values'] for k in (1, 2)], [nums(I[:, k]) for k in range(2)])
    check('MATLAB: logical as 0/1 with labels', (c['L 1']['values'], c['L 1']['valueLabels']), (nums(L[:, 0]), [[0, 'false'], [1, 'true']]))
    check('MATLAB: a struct\'s fields as columns', (c['x']['values'], c['y']['values']), (nums([0, 1, 2]), nums([9, 8, 7])))
    check('MATLAB: column and row vectors', (table(out, 'mlab — v')['col']['v']['values'], table(out, 'mlab — r')['col']['r']['values']), (nums(np.arange(5.0)), nums(np.arange(4.0) + 10)))
    vals = table(out, 'mlab — values')
    check('MATLAB: char as text', [(x['name'], x['values']) for x in vals['columns']], [('Name', ['s']), ('Text', ['hello'])])


# ---- Kompartment's own result files -----------------------------------------------
def kompartment():
    r = subprocess.run(['node', os.path.join(HERE, 'make-kompartment-h5.mjs'), TMP], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    with open(os.path.join(TMP, 'komp.json')) as f:
        k = json.load(f)
    by = {o['label']: o for o in k['outputs']}
    out = read('komp-run.h5')
    check('Kompartment run: ticked: every series, the time and the parameters; not the index lists', out['defaults']['picked'],
          ['/Dose', '/Soil/Cs-137', '/Soil/I-129', '/Soil/kd', '/Water/Cs-137', '/Water/depth', '/time'])
    t = out['tables'][0]
    check('Kompartment run: the series in one table, the time first, two Cs-137 told apart', (t['name'], [c['name'] for c in t['columns']]),
          ('komp-run — 24 rows', ['time', 'Dose', 'Soil/Cs-137', 'I-129', 'Water/Cs-137']))
    p = table(out, 'komp-run — values')
    check('Kompartment run: its parameters, a row each, with their units', [(c['name'], c['values']) for c in p['columns']],
          [('Name', ['Soil/kd', 'Water/depth']), ('Value', [by['Soil.kd']['run'][0], by['Water.depth']['run'][0]]), ('Unit', ['m3/kg', 'm'])])
    c = t['col']
    check('Kompartment run: the values, as the writer was given them', (c['time']['values'], c['Dose']['values'], c['Soil/Cs-137']['values'], c['I-129']['values'], c['Water/Cs-137']['values']),
          (k['t'], by['Dose']['run'], by['Soil.Cs-137']['run'], by['Soil.I-129']['run'], by['Water.Cs-137']['run']))
    check('Kompartment run: units in the notes, the model in the table\'s', (c['Dose']['notes'], 'model: smui test' in t['notes'], 'A run for <smui>' in t['notes']), ('/Dose; unit: Sv/year', True, True))
    out = read('komp-prob.h5')
    nt, S = len(k['t']), k['S']
    check('Kompartment probabilistic: the series open a row per realisation', out['defaults']['transposed'], ['/Dose', '/Soil/Cs-137', '/Soil/I-129', '/Water/Cs-137'])
    t = out['tables'][0]
    names = [c['name'] for c in t['columns']]
    check('Kompartment probabilistic: one table of the realisations: the sampled values, then each series by time', (t['name'], len(t['columns']), names[:3], names[-1]),
          ('komp-prob', 2 + 4 * nt, ['kd', 'depth', 'Dose t=0'], f'Water/Cs-137 t={float(f"{k["t"][-1]:.6g}"):g}'))
    c = t['col']
    check('Kompartment probabilistic: a parameter, a value per realisation', (c['kd']['values'], c['depth']['values']), (by['Soil.kd']['prob'][:S], by['Water.depth']['prob'][:S]))
    prob = by['Soil.Cs-137']['prob']
    col = [x for x in t['columns'] if x['name'].startswith('Soil/Cs-137 ')]
    check('Kompartment probabilistic: a series\' realisations at every time (float32 as written)', [x['values'] for x in col], [prob[i * S:(i + 1) * S] for i in range(nt)])
    out = read('komp-data.h5')
    v, fl = table(out, 'komp-data — values'), table(out, 'komp-data — flow')
    check('Kompartment data file: the parameters, with unit, distribution and reference; a text value apart',
          [(c['name'], c['values']) for c in v['columns']],
          [('Name', ['model/Site/name', 'model/Soil/kd', 'model/Soil/porosity']), ('Value', [None, 0.25, 0.3]), ('Text', ['Forsmark', None, None]),
           ('Unit', [None, 'm3/kg', '-']), ('Distribution', [None, 'logn(mean,sd)', '{"type":"unif","a":0.2,"b":0.4}']), ('Reference', [None, 'SKB R-01-01', None])])
    check('Kompartment data file: a lookup table with its times (its index attribute), in order', [(c['name'], c['values']) for c in fl['columns']],
          [('time', [0.0, 100.0, 1000.0]), ('flow', [10.0, 11.0, 12.5])])


# ---- rb's probabilistic time and Ecolego-like strings ---------------------------
def results_like():
    nt, S = 6, 4
    with h5py.File(os.path.join(TMP, 'rb.h5'), 'w') as f:
        t = f.create_dataset('time', data=np.linspace(0, 5, nt))
        t.attrs['unit'] = 'year'
        g = f.create_group('Bio')
        g.attrs['IndexLists'] = np.array(['Radionuclides'], dtype=h5py.string_dtype())
        g.attrs['time_dependent'] = 'TRUE'
        for k, nm in enumerate(['C-14', 'Cl-36']):
            d = g.create_dataset(nm, data=np.arange(nt * S, dtype='f4').reshape(nt, S) + k)
            d.attrs['time_dependent'] = 'TRUE'
            d.attrs['probabilistic'] = 'TRUE'
        f['IndexLists/Radionuclides'] = np.array(['C-14', 'Cl-36'], dtype=h5py.string_dtype())
    out = read('rb.h5')
    check('result file: TRUE as text counts; the series open by realisation', out['defaults']['transposed'], ['/Bio/C-14', '/Bio/Cl-36'])
    t = out['tables'][0]
    check('result file: columns named by the times', [c['name'] for c in t['columns']][:3], ['C-14 t=0', 'C-14 t=1', 'C-14 t=2'])
    check('result file: the index lists are not ticked', '/IndexLists/Radionuclides' in out['defaults']['picked'], False)
    # the HDF5 Browser's own test files (resources/tests/rb/fixtures, ours)
    a = os.path.join(REPO, 'resources', 'tests', 'rb', 'fixtures', 'sample-a.h5')
    shutil.copyfile(a, os.path.join(TMP, 'sample-a.h5'))
    out = read('sample-a.h5')
    with h5py.File(a) as f:
        ac, tm = f['biosphere/vault_A/mire/total/Ac-227'][()], f['time'][()]
    t = table(out, 'sample-a — total')
    check('HDF5 Browser sample: probabilistic series under a time-dependent group open a row per realisation', (t['rows'] if 'rows' in t else len(t['columns'][0]['values']), len(t['columns'])), (12, 9 * 60))
    check('... a column is a time, its values the realisations', (t['columns'][5]['name'], t['columns'][5]['values']), (f'Ac-227 t={float(f"{tm[5]:.6g}"):g}', nums(ac[5, :])))
    p = os.path.join(REPO, 'resources', 'tests', 'prob-fixture.h5')
    shutil.copyfile(p, os.path.join(TMP, 'prob-fixture.h5'))
    out = read('prob-fixture.h5')
    with h5py.File(p) as f:
        ds, tt, steps = f['grp/DS'][()], f['time'][()], [int(k) for k in f['time'].attrs['n_times']]
    t = out['tables'][0]
    want = [[fin(float(ds[i, k])) if i < steps[k] else None for i in range(ds.shape[0])] for k in range(len(steps))]
    check('HDF5 Browser per-iteration time (n_times): a column per iteration, the padding left out', [c['name'] for c in t['columns']], ['DS 1', 'DS 2', 'DS 3', 'time 1', 'time 2', 'time 3'])
    check('... each iteration to its last step', [c['values'] for c in t['columns'][:3]], want)
    check('... the times alike', [c['values'] for c in t['columns'][3:]], [[fin(float(tt[i, k])) if i < steps[k] else None for i in range(tt.shape[0])] for k in range(len(steps))])


# ---- pickles ---------------------------------------------------------------------
def pickles():
    def unp(data):
        p = os.path.join(TMP, 'x.pkl')
        with open(p, 'wb') as w:
            w.write(data)
        return run('unpickle', p)

    def plain(v):
        if isinstance(v, dict):
            return {'$map': [[plain(k), plain(x)] for k, x in v.items()]}
        if isinstance(v, (bytes, bytearray)):
            return {'$bytes': list(v)}
        if isinstance(v, (list, tuple, set, frozenset)):
            return [plain(x) for x in (sorted(v) if isinstance(v, (set, frozenset)) else v)]
        if isinstance(v, float):
            return fin(v)
        return v

    value = {'a': [1, -2, 3.5, None, True, False, 'åäö', b'\x00\xff'], 2: ('t', (1,)), 'big': 2 ** 70, 'neg': -2 ** 40, 'f': float('nan'), 'set': {3, 1}, 'nest': [[[]]], 'e': ''}
    for proto in range(0, 6):
        r = unp(pickle.dumps(value, protocol=proto))
        got = r.get('value')
        want = plain(value)
        if isinstance(got, dict) and '$map' in got:
            # a set comes back as a list in the pickle's order
            got['$map'] = [[k, sorted(v) if k == 'set' else v] for k, v in got['$map']]
        check(f'pickle protocol {proto}: plain values as Python wrote them', got, want)
    arr = np.array([['x', None], [1.5, 'åäö'], [np.nan, 'z']], dtype=object)
    for order in ('C', 'F'):
        a = np.asarray(arr, order=order)
        r = unp(pickle.dumps(a, protocol=5))
        check(f'pickle: a numpy object array ({order} order) as its values in C order', (r['array']['shape'], r['array']['data']), ([3, 2], [plain(x) for x in arr.ravel()]))

    class Evil:
        def __reduce__(self):
            return (os.system, (f'touch {TMP}/pwned',))
    r = unp(pickle.dumps(Evil(), protocol=2))
    check('pickle: a REDUCE of os.system is only recorded, never called', (r['value']['$call']['$global'].split('.')[-1], r['array'], os.path.exists(os.path.join(TMP, 'pwned'))), ('system', None, False))
    check('pickle: cut short', unp(pickle.dumps([1, 2, 3], protocol=2)[:-3]).get('error'), 'pickle: cut short')
    check('pickle: an opcode it does not take (an extension code)', unp(b'\x80\x02\x82\x01.').get('error'), 'pickle: unsupported opcode 0x82')
    check('pickle: a persistent id is refused', unp(b'\x80\x02Q.').get('error'), 'pickle: unsupported opcode 0x51')
    check('pickle: an unknown memo', unp(b'\x80\x02h\x05.').get('error'), 'pickle: unknown memo')


def main():
    try:
        sniffs()
        basic()
        compound()
        cubes()
        hostile()
        pandas_files()
        netcdf()
        matlab()
        kompartment()
        results_like()
        pickles()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    return check.done()


if __name__ == '__main__':
    sys.exit(main())
