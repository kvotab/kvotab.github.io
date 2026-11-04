"""NetCDF files, run natively: nccreate, ncwrite, ncread, ncinfo, ncdisp,
ncreadatt and ncwriteatt in each format (netcdf4_classic, netcdf4, classic,
64bit), the files read back by SciPy's netcdf_file and by h5py on their
own (the netCDF-4 layout: dimension scales attached, _Netcdf4Dimid,
_nc3_strict, fill values, creation order), unlimited dimensions growing,
scale_factor, add_offset and _FillValue both ways, start, count and stride,
char and string variables, compression, and files SciPy writes read by
ncread.

    python3 test_netcdf.py          (from any folder)
"""
import asyncio
import math
import os
import sys
import tempfile

import numpy as np
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-netcdf-')
R.STATE['home'] = TMP


def run(code):
    R.BASE.clear()
    R.take_output()
    asyncio.run(R.execute(f"cd('{TMP}');\n" + code))
    return dict(R.BASE), R.take_output()


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()


def a(x):
    if isinstance(x, tuple):
        parts = [np.asarray(v, dtype=float).reshape(-1) for v in x]
        return np.concatenate(parts) if parts else np.zeros(0)
    return np.asarray(x, dtype=float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 6).tolist() if g.size < 30 else g.shape}, want {np.round(w, 6).tolist() if w.size < 30 else w.shape}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)



import h5py  # noqa: E402
from scipy.io import netcdf_file  # noqa: E402


def text(v):
    from plab.values import py_str
    return py_str(v)


for fmt in ('netcdf4_classic', 'netcdf4', 'classic', '64bit'):
    fn = os.path.join(TMP, f'{fmt}.nc')
    W, out = run(f"""fn = '{fmt}.nc';
nccreate(fn, 'temp', 'Dimensions', {{'x', 4, 'y', 3}}, 'Format', '{fmt}', 'FillValue', -999);
nccreate(fn, 'x', 'Dimensions', {{'x'}});
nccreate(fn, 'series', 'Dimensions', {{'x', 4, 'time', Inf}}, 'Datatype', 'int16');
ncwriteatt(fn, 'series', 'scale_factor', 0.5); ncwriteatt(fn, 'series', 'add_offset', 10); ncwriteatt(fn, 'series', '_FillValue', int16(-1));
ncwriteatt(fn, 'temp', 'units', 'K'); ncwriteatt(fn, '/', 'title', 'test file');
T = reshape(1:12, 4, 3); T(2,2) = NaN; ncwrite(fn, 'temp', T); ncwrite(fn, 'x', [10 20 30 40]);
ncwrite(fn, 'series', [11 12; 13 14; 15 NaN; 17 18]); ncwrite(fn, 'series', [20; 21; 22; 23], [1 3]);
A = ncread(fn, 'temp'); same = isequaln(A, T); cls = class(A); xr = ncread(fn, 'x'); s = ncread(fn, 'series'); part = ncread(fn, 'temp', [2 1], [2 Inf], [1 2]);
u = ncreadatt(fn, 'temp', 'units'); ti = ncreadatt(fn, '/', 'title'); info = ncinfo(fn); vi = ncinfo(fn, 'series'); ncdisp(fn)""")
    same(f'{fmt}: temp back as written, double, NaN for its fill value', (bool(W['same']), text(W['cls'])), (True, 'double'))
    near(f'{fmt}: x a column; series scaled, NaN kept, grown along time; start, count and stride',
         (W['xr'], W['s'], W['part']), ([[10], [20], [30], [40]], [[11, 12, 20], [13, 14, 21], [15, np.nan, 22], [17, 18, 23]], [[2, 10], [3, 11]]))
    info = W['info']
    D = info.get1('Dimensions')
    same(f'{fmt}: attributes; ncinfo: the format and the dimensions (time unlimited)',
         (text(W['u']), text(W['ti']), text(info.get1('Format')), sorted((text(D.f['Name'][0, i]), float(D.f['Length'][0, i]), bool(D.f['Unlimited'][0, i])) for i in range(D.shape[1]))),
         ('K', 'test file', fmt, [('time', 3.0, True), ('x', 4.0, False), ('y', 3.0, False)]))
    vi = W['vi']
    same(f'{fmt}: ncinfo of a variable: its size, type and dimensions in the language\'s order', (np.asarray(vi.get1('Size')).reshape(-1).tolist(), text(vi.get1('Datatype')),
         [text(vi.get1('Dimensions').f['Name'][0, i]) for i in range(2)]), ([4.0, 3.0], 'int16', ['x', 'time']))
    C(f'{fmt}: ncdisp prints the format, dimensions and variables', 'Format:' in out and 'time = 3   (UNLIMITED)' in out and 'Size:       4x3' in out, out[:200])
    # the file read on its own
    if fmt in ('classic', '64bit'):
        with netcdf_file(fn, 'r', mmap=False, maskandscale=False) as f:
            same(f'{fmt}: SciPy reads the version, the dimensions, raw values and attributes',
                 (f.version_byte, dict(f.dimensions), f.variables['series'][:].tolist(), f.variables['temp'][:].tolist(), f.variables['temp']._attributes['_FillValue'],
                  f._attributes['title']),
                 (1 if fmt == 'classic' else 2, {'time': None, 'x': 4, 'y': 3}, [[2, 6, 10, 14], [4, 8, -1, 16], [20, 22, 24, 26]],
                  [[1.0, 2.0, 3.0, 4.0], [5.0, -999.0, 7.0, 8.0], [9.0, 10.0, 11.0, 12.0]], -999.0, b'test file'))
    else:
        with h5py.File(fn, 'r') as f:
            t = f['temp']
            dims = [t.dims[i][0].name for i in range(2)]
            same(f"{fmt}: h5py finds the netCDF-4 layout: scales attached in the file's order, ids, fill value, the classic flag",
                 (dims, int(f['x'].attrs['_Netcdf4Dimid']), int(f['y'].attrs['_Netcdf4Dimid']), f['x'].attrs['CLASS'], f['y'].attrs['NAME'][:20],
                  float(t.fillvalue), f['series'].maxshape, f['series'][...].tolist(), '_nc3_strict' in f.attrs),
                 (['/y', '/x'], 0, 1, b'DIMENSION_SCALE', b'This is a netCDF dim', -999.0, (None, 4), [[2, 6, 10, 14], [4, 8, -1, 16], [20, 22, 24, 26]],
                  fmt == 'netcdf4_classic'))
W, _ = run("""nccreate('c.nc', 'name', 'Dimensions', {'len', 5}, 'Datatype', 'char'); ncwrite('c.nc', 'name', 'hello'); n = ncread('c.nc', 'name'); ns = size(n); nt = n';
nccreate('c.nc', 'names', 'Dimensions', {'len', 5, 'k', 2}, 'Datatype', 'char'); ncwrite('c.nc', 'names', ['abcde'; 'fghij']'); nn = ncread('c.nc', 'names'); nn2 = nn';
nccreate('s.nc', 'labels', 'Dimensions', {'k', 2}, 'Datatype', 'string', 'Format', 'netcdf4'); ncwrite('s.nc', 'labels', ["one"; "two"]); lb = ncread('s.nc', 'labels'); lc = class(lb);
nccreate('z.nc', 'big', 'Dimensions', {'a', 100}, 'DeflateLevel', 5, 'Shuffle', true, 'ChunkSize', 50); ncwrite('z.nc', 'big', (1:100)'); vz = ncinfo('z.nc', 'big');
zd = [vz.DeflateLevel vz.ChunkSize vz.Shuffle]; zs = sum(ncread('z.nc', 'big'));""")
same('char variables: a column for one dimension, the language\'s order for two', (np.asarray(W['ns']).reshape(-1).tolist(), text(W['nt']), W['nn2'].row_strs()),
     ([5.0, 1.0], 'hello', ['abcde', 'fghij']))
same('string variables in netcdf4 files', (text(W['lc']), [s for s in W['lb'].a.reshape(-1)]), ('string', ['one', 'two']))
near('compression, shuffle and chunks kept, the values whole', (W['zd'], W['zs']), ([[5, 50, 1]], 5050))
with h5py.File(os.path.join(TMP, 'z.nc'), 'r') as f:
    same('h5py sees the gzip filter and the chunks', (f['big'].compression, f['big'].compression_opts, f['big'].chunks, f['big'].shuffle), ('gzip', 5, (50,), True))
# a classic file SciPy writes, read by ncread
with netcdf_file(os.path.join(TMP, 'sp.nc'), 'w') as f:
    f.createDimension('t', None)
    f.createDimension('lat', 3)
    v = f.createVariable('rain', 'f', ('t', 'lat'))
    v[0:2] = np.array([[1, 2, 3], [4, 5, 6]], np.float32)
    v.units = b'mm'
W, _ = run("r = ncread('sp.nc', 'rain'); u = ncreadatt('sp.nc', 'rain', 'units'); c = class(r);")
near('a file SciPy wrote: read in the language\'s order, single kept', W['r'], [[1, 4], [2, 5], [3, 6]])
same('... its attribute and class', (text(W['u']), text(W['c'])), ('mm', 'single'))
raises("ncread('netcdf4.nc', 'nope')", "Could not find variable or group 'nope'")
raises("nccreate('classic.nc', 'u', 'Dimensions', {'x', 4}, 'Datatype', 'uint16')", 'A classic file holds')
raises("nccreate('netcdf4_classic.nc', 'u', 'Dimensions', {'x', 4}, 'Datatype', 'uint16')", 'A netcdf4_classic file holds the classic types')
raises("nccreate('netcdf4.nc', 'temp', 'Dimensions', {'x', 4})", 'already in the file')
raises("ncread('nothing-here.nc', 'x')", 'does not exist')

sys.exit(C.done())
