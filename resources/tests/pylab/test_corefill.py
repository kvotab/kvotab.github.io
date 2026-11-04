"""Core fill-ins, run natively (CPython with numpy and scipy): datastores
of every kind with mapreduce, tall arrays against the same computations in
memory, Parquet files against pyarrow, FITS files against astropy, the
desktop functions, the ez functions and the other plot fill-ins, copy and
events of classes, surface fits against least squares done here, and
corrcov's refusals.

pyarrow and astropy are references only (the page loads pyarrow itself and
has its own FITS reader); the suite says so and stops when either is
missing.

    python3 test_corefill.py          (from any folder)
"""
import asyncio
import math
import os
import shutil
import sys
import tempfile
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    from astropy.io import fits
except ImportError as e:
    print(f'test_corefill needs pyarrow and astropy as references ({e}).')
    sys.exit(1)

R.setup()
warnings.filterwarnings('ignore')
TMP = tempfile.mkdtemp(prefix='plab-corefill-')
EVENTS = []
R.EVENT_HOOK[0] = EVENTS.append


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
        return np.concatenate([np.asarray(v).reshape(-1) for v in x])
    return np.asarray(x)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 8).tolist() if g.size < 30 else g.shape}, want {np.round(w, 8).tolist() if np.size(w) < 30 else np.shape(w)}')


def text(v):
    return v.str() if isinstance(v, Char) else str(v)


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = text(W['e'])
    return C(f'refused: {code}', words in msg, msg)


def put(name, content):
    p = os.path.join(TMP, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write(content)


# ---- tabular text datastores ---------------------------------------------------------------------------------------------------

put('dd/a.csv', 'x,y,name\n1,2,a\n3,4,b\n5,6,c\n')
put('dd/b.csv', 'x,y,name\n7,8,d\n9,10,e\n')
put('dd/notes.md', 'not data\n')
W, out = run("ds = datastore('dd'); n = numel(ds.Files); ds.ReadSize = 2; [t1, info] = read(ds); t2 = read(ds); t3 = read(ds); h = hasdata(ds);"
             "reset(ds); A = readall(ds); p = preview(ds); pr = progress(ds); c = class(ds); k = numpartitions(ds);"
             "ds.SelectedVariableNames = {'name', 'x'}; S = readall(ds); P2 = readall(partition(ds, 2, 2));")
C('datastore: a folder of .csv files is a TabularTextDatastore (other files left out)', text(W['c']) == 'matlab.io.datastore.TabularTextDatastore' and W['n'] == 2, text(W['c']))
near('read: ReadSize rows at a time, never across files', (a(W['t1'].vars[0]), a(W['t2'].vars[0]), a(W['t3'].vars[0])), [1, 3, 5, 7, 9])
C('read: info of the file read (Filename, FileSize, Offset)', text(W['info'].get1('Filename')).endswith('a.csv') and W['info'].get1('FileSize') == 27.0 and W['info'].get1('Offset') == 9.0)
C('hasdata: false after the last block', W['h'] is False)
near('readall: every file, joined', a(W['A'].vars[1]).reshape(-1), [2, 4, 6, 8, 10])
C('preview: the first rows without moving the datastore', W['p'].n == 3 and W['pr'] == 0.0)
C('numpartitions: one for each file', W['k'] == 2.0)
C('SelectedVariableNames: the variables read, in that order', W['S'].names == ['name', 'x'])
near('partition(ds, 2, 2): the second file', a(W['P2'].vars[1]).reshape(-1), [7, 9])
W, _ = run("ds = tabularTextDatastore('dd/*.csv', 'ReadSize', 'file'); n = 0; while hasdata(ds), t = read(ds); n = n + 1; end;"
           "c = copy(ds); reset(ds); read(ds); pc = progress(c); pd = progress(ds); sh = shuffle(ds); ns = numel(sh.Files); sb = subset(ds, 2); nb = height(readall(sb));")
C("ReadSize 'file': one read a file", W['n'] == 2.0)
C('copy: a datastore of its own (reading one leaves the other)', W['pc'] == 1.0 and W['pd'] == 0.5)
C('shuffle and subset: the files kept or picked', W['ns'] == 2.0 and W['nb'] == 2.0)
raises("datastore('nowhere/*.csv')", 'Cannot find files')
raises("ds = datastore('dd'); ds.ReadSize = 0", 'ReadSize')
raises("ds = datastore('dd'); ds.SelectedVariableNames = {'zz'}", "'zz' is not one of the variable names")
raises("ds = datastore('dd'); while hasdata(ds), read(ds); end; read(ds)", 'No more data')

# ---- spreadsheets, images, files, arrays ---------------------------------------------------------------------------------------

os.makedirs(os.path.join(TMP, 'sh'), exist_ok=True)
W, _ = run("T = table([1;2;3], {'p';'q';'r'}, 'VariableNames', {'v', 'w'}); writetable(T, 'sh/one.xlsx'); writetable(T(1:2,:), 'sh/two.xlsx');"
           "ss = spreadsheetDatastore('sh'); A = readall(ss); c = class(ss);")
near('spreadsheetDatastore: the sheets of every file', a(W['A'].vars[0]).reshape(-1), [1, 2, 3, 1, 2])
os.makedirs(os.path.join(TMP, 'imgs', 'cats'), exist_ok=True)
os.makedirs(os.path.join(TMP, 'imgs', 'dogs'), exist_ok=True)
W, _ = run("imwrite(uint8(magic(4)), 'imgs/cats/c1.png'); imwrite(uint8(2*magic(4)), 'imgs/cats/c2.png'); imwrite(uint8(ones(3)), 'imgs/dogs/d1.png');"
           "imds = imageDatastore('imgs', 'IncludeSubfolders', true, 'LabelSource', 'foldernames'); [img, info] = read(imds);"
           "tbl = countEachLabel(imds); [tr, te] = splitEachLabel(imds, 0.5); all_ = readall(imds); imds.ReadSize = 2; reset(imds); two = read(imds);"
           "cl = class(info.Label);")
near('imageDatastore: the first image as imread reads it', a(W['img']).astype(float), np.array([[16, 2, 3, 13], [5, 11, 10, 8], [9, 7, 6, 12], [4, 14, 15, 1]], float))
C("LabelSource 'foldernames': categorical labels, counted by countEachLabel", text(W['cl']) == 'categorical' and list(W['tbl'].vars[0].cats) == ['cats', 'dogs']
  and a(W['tbl'].vars[1]).reshape(-1).tolist() == [2.0, 1.0])
C('splitEachLabel: half of each label (rounded) in the first, the rest in the second', len(W['tr'].files) == 2 and len(W['te'].files) == 1)
C('readall and a ReadSize of 2: cells of images', W['all_'].a.shape == (3, 1) and W['two'].a.shape == (2, 1))
W, _ = run("fds = fileDatastore('dd', 'ReadFcn', @(f) height(readtable(f)), 'FileExtensions', '.csv', 'UniformRead', true); r = readall(fds);"
           "bds = fileDatastore('dd/a.csv', 'ReadMode', 'bytes', 'BlockSize', 10, 'ReadFcn', @(f) 0); b1 = read(bds); b2 = read(bds); b3 = read(bds); hb = hasdata(bds);"
           "ads = arrayDatastore(magic(4), 'ReadSize', 3); d1 = read(ads); d2 = read(ads); ads.OutputType = 'same'; reset(ads); s1 = read(ads);"
           "ac = arrayDatastore(reshape(1:6, 2, 3), 'IterationDimension', 2); cc = readall(ac);")
near('fileDatastore: ReadFcn on each file, joined (UniformRead)', W['r'], [[3], [2]])
C("ReadMode 'bytes': BlockSize bytes at a time", a(W['b1']).size == 10 and a(W['b2']).size == 10 and a(W['b3']).size == 7 and W['hb'] is False
  and bytes(a(W['b1']).astype(np.uint8).reshape(-1)) == b'x,y,name\n1')
C("arrayDatastore: ReadSize rows in cells, the last read shorter", W['d1'].a.shape == (3, 1) and W['d2'].a.shape == (1, 1))
near("arrayDatastore 'same': the rows as an array", W['s1'], np.array([[16, 2, 3, 13], [5, 11, 10, 8], [9, 7, 6, 12]], float))
C('arrayDatastore along dimension 2: one column a cell', W['cc'].a.shape == (3, 1) and a(W['cc'].a[2, 0]).reshape(-1).tolist() == [5.0, 6.0])

# ---- transform, combine, writeall, mapreduce -----------------------------------------------------------------------------------

W, _ = run("ads = arrayDatastore((1:4)', 'OutputType', 'same', 'ReadSize', 2); read(ads); t = transform(ads, @(x) 10*x); r = read(t);"
           "t2 = transform(t, @(x) x + 1); r2 = readall(t2);"
           "ti = transform(ads, @(x, info) deal(x, info.Index'), 'IncludeInfo', true); [d, ix] = read(ti);"
           "c = combine(arrayDatastore([1;2;3]), arrayDatastore([4;5;6])); rc = read(c); ac = readall(c);"
           "s = combine(arrayDatastore([1;2], 'OutputType', 'same'), arrayDatastore([3], 'OutputType', 'same'), 'ReadOrder', 'sequential'); as = readall(s);"
           "tt = combine(datastore('dd/a.csv'), datastore('dd/a.csv')); ")
near('transform: from the start of the datastore, whatever it had read', W['r'], [[10], [20]])
near('transform of a transform: the functions in turn', W['r2'], [[11], [21], [31], [41]])
near("transform with 'IncludeInfo': the info passed and given back", W['ix'], [[1, 2]])
C('combine: one block of each, side by side in a cell', W['rc'].a.shape == (1, 2) and W['ac'].a.shape == (3, 2))
near("combine 'sequential': one datastore after the other", W['as'], [[1], [2], [3]])
raises("combine(datastore('dd/a.csv'), datastore('dd/a.csv')); readall(ans)", 'Duplicate table variable name')
W, _ = run("ds = datastore('dd'); writeall(ds, 'out', 'OutputFormat', 'txt', 'FilenamePrefix', 'n_'); d = dir('out/*.txt'); names = {d.name};")
C("writeall: each file written again with the prefix and format", sorted(text(c) for c in W['names'].a.reshape(-1)) == ['n_a.txt', 'n_b.txt'])
put('mr.m', """ds = datastore('dd');
outds = mapreduce(ds, @mapf, @redf, 'OutputFolder', 'mrout');
T = readall(outds);
kv = readall(datastore('mrout/results_1.mat'));
function mapf(data, info, store)
  add(store, 'sumx', sum(data.x));
  addmulti(store, {'n', 'maxy'}, {height(data), max(data.y)});
end
function redf(key, it, store)
  acc = [];
  while hasnext(it)
    acc(end+1) = getnext(it);
  end
  if strcmp(key, 'maxy'), add(store, key, max(acc)); else, add(store, key, sum(acc)); end
end
""")
W, out = run("mr")
T = W['T']
C('mapreduce: the reduce results by key (sum of x, rows, largest y)', [text(c) for c in T.vars[0].a.reshape(-1)] == ['sumx', 'n', 'maxy']
  and [float(a(v)) for v in T.vars[1].a.reshape(-1)] == [25.0, 5.0, 10.0], str(T.vars[1].a.reshape(-1)))
C('mapreduce: the progress shown, to 100% both', 'Map 100% Reduce 100%' in out)
C("mapreduce 'OutputFolder': results_1.mat read back as a key-value datastore", W['kv'].n == 3 and text(W['kv'].vars[0].a[0, 0]) == 'sumx')
raises("mapreduce(datastore('dd'), 1, 2)", 'function handles')

# ---- tall arrays --------------------------------------------------------------------------------------------------------------

rs = np.random.default_rng(5)
v = rs.standard_normal(50)
W, out = run(f"A = {v.tolist()}'; t = tall(A); m = gather(mean(t)); [s, mx, mn] = gather(std(t), max(t), min(t));"
             "u = t.^2 + 2*t - 1; g = gather(u); [~, k] = max(t); ik = gather(k); n = gather(numel(t)); sz = gather(size(t));"
             "t2 = t; t2(t2 < 0) = 0; z = gather(sum(t2)); A1 = A(1); c = class(t); it = istall(t); cu = classUnderlying(t2);"
             "b = gather(t(t > 1)); h = gather(head(t, 3)); srt = gather(sort(t)); f = gather(cumsum(t));")
near('tall: mean, std, max and min as in memory', (W['m'], W['s'], W['mx'], W['mn']), (v.mean(), v.std(ddof=1), v.max(), v.min()), 1e-12)
near('tall: element-wise steps', W['g'], (v ** 2 + 2 * v - 1).reshape(-1, 1), 1e-12)
C('tall: the second output of max, numel and size', W['ik'] == float(np.argmax(v) + 1) and W['n'] == 50.0 and a(W['sz']).tolist() == [[50.0, 1.0]])
near('tall: an assignment by a logical index changes the copy, not the array it came from', (W['z'], W['A1']), (np.maximum(v, 0).sum(), v[0]), 1e-12)
C("tall: class 'tall', istall, classUnderlying", text(W['c']) == 'tall' and W['it'] is True and text(W['cu']) == 'double')
near('tall: logical indexing, head, sort, cumsum', (W['b'], W['h'], W['srt'], W['f']), (v[v > 1], v[:3], np.sort(v), np.cumsum(v)), 1e-12)
C('tall: shown not yet computed, with its size when known', 'tall double column vector' in run("t = tall((1:20)')")[1] and 'gather computes' in run("t = tall((1:3)'); u = t + 1")[1])
W, _ = run("tt = tall(datastore('dd')); y2 = tt.y * 2; g = gather(y2); r = gather(tt(tt.x > 4, :)); tt.z = tt.x + tt.y; T = gather(tt); mx = gather(max(tt.x));")
near('tall of a datastore: a variable, a row selection, a new variable', (W['g'], a(W['r'].vars[0]), a(W['T'].vars[3]), W['mx']),
     ([[4], [8], [12], [16], [20]], [[5], [7], [9]], [[3], [7], [11], [15], [19]], 9), 1e-12)
W, _ = run("t = tall([1;2;3]); x = gather(5); [p, q] = gather(t + 1, 'text');")
C('gather: values that are not tall given back as they are', W['x'] == 5.0 and text(W['q']) == 'text')
W, _ = run("t = tall([3;1;2]); figure; h = plot(t); y = h.YData;")
near('plot of a tall array: gathered, then drawn', W['y'], [[3, 1, 2]])

# ---- Parquet files against pyarrow -----------------------------------------------------------------------------------------

W, _ = run("T = table([1.5;2;3], int32([4;5;6]), [\"a\";\"b\";missing], [true;false;true], datetime(2024,1,[1;2;3]), categorical({'r';'g';'r'}, {'r','g','b'}), "
           "hours([1;2;NaN]), 'VariableNames', {'d','i','s','b','t','c','h'}); parquetwrite('t.parquet', T); T2 = parquetread('t.parquet');"
           "T3 = parquetread('t.parquet', 'SelectedVariableNames', {'i', 's'}); info = parquetinfo('t.parquet');"
           "TT = timetable(datetime(2024,1,[1;2]), [10;20]); parquetwrite('tt.parquet', TT); TT2 = parquetread('tt.parquet', 'OutputType', 'timetable');"
           "pds = parquetDatastore({'t.parquet', 't.parquet'}); n = height(readall(pds));")
tab = pq.read_table(os.path.join(TMP, 't.parquet'))
rows = tab.to_pylist()
C('parquetwrite: the types pyarrow reads', [str(f.type) for f in tab.schema] == ['double', 'int32', 'string', 'bool', 'timestamp[us]', 'dictionary<values=string, indices=int32, ordered=0>', 'duration[us]'],
  str(tab.schema))
C('parquetwrite: the values pyarrow reads (missing as null)', rows[0]['d'] == 1.5 and rows[2]['s'] is None and rows[1]['c'] == 'g' and rows[2]['h'] is None
  and str(rows[0]['t']) == '2024-01-01 00:00:00' and rows[1]['h'].total_seconds() == 7200)
T2 = W['T2']
C('parquetread: the classes back', [type(x).__name__ if not isinstance(x, np.ndarray) else str(x.dtype) for x in T2.vars] == ['float64', 'int32', 'Str', 'bool', 'DateTime', 'Categorical', 'Duration'])
C('parquetread: categories in the dictionary order, an unused one kept', list(T2.vars[5].cats) == ['r', 'g', 'b'])
C('parquetread: SelectedVariableNames', W['T3'].names == ['i', 's'])
C('parquetinfo: rows and variables', a(W['info'].get1('RowGroupHeights')).reshape(-1).tolist() == [3.0] and [text(c) for c in W['info'].get1('VariableNames').a.reshape(-1)] == ['d', 'i', 's', 'b', 't', 'c', 'h'])
C("parquetread 'OutputType' 'timetable': the row times back", type(W['TT2']).__name__ == 'TimeTable' and a(W['TT2'].vars[0]).reshape(-1).tolist() == [10.0, 20.0])
C('parquetDatastore: the files read as tables', W['n'] == 6.0)
pq.write_table(pa.table({'k': pa.array([1, None, 3], pa.int64()), 'f': pa.array([0.5, 1.5, None], pa.float32()),
                         'l': pa.array([[1.0, 2.0], [], [3.0]], pa.list_(pa.float64())), 'z': pa.array(['x', 'y', 'z'], pa.large_string()),
                         'ts': pa.array([0, 3600, None], pa.timestamp('s', tz='UTC'))}), os.path.join(TMP, 'ref.parquet'))
W, _ = run("R = parquetread('ref.parquet'); k = R.k; f = R.f; l = R.l; z = R.z; tz = R.ts.TimeZone; ts = R.ts;")
near('parquetread of pyarrow\'s file: integers with a null become double with NaN', W['k'], [[1], [np.nan], [3]])
C('parquetread: float32 stays single, lists become cells, large strings strings', a(W['f']).dtype == np.float32 and W['l'].a.shape == (3, 1)
  and a(W['l'].a[0, 0]).reshape(-1).tolist() == [1.0, 2.0] and type(W['z']).__name__ == 'Str')
C('parquetread: a time zone kept', text(W['tz']) == 'UTC' and np.isnan(a(W['ts'].a)[2, 0]) and a(W['ts'].a)[1, 0] == 3600.0)
raises("parquetwrite('c.parquet', table([1+2i; 3]))", 'complex')
raises("parquetread('nofile.parquet')", 'Unable to find')

# ---- FITS files against astropy ------------------------------------------------------------------------------------------------

img = np.arange(12, dtype=np.int16).reshape(3, 4)
h0 = fits.PrimaryHDU(img)
h0.header['BSCALE'] = 2.0
h0.header['BZERO'] = 10.0
h0.header['OBJECT'] = "M31 'x'"
cube = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
cols = fits.ColDefs([fits.Column(name='a', format='J', array=np.array([1, 2, 3])),
                     fits.Column(name='b', format='2E', array=np.array([[1.5, 2.5], [3, 4], [5, 6]], np.float32)),
                     fits.Column(name='s', format='5A', array=np.array(['ab', 'cde', 'f'])),
                     fits.Column(name='l', format='L', array=np.array([True, False, True])),
                     fits.Column(name='k', format='K', array=np.array([7, 8, 9], np.int64)),
                     fits.Column(name='v', format='PD()', array=np.array([np.array([1.0, 2.0]), np.array([3.0]), np.array([])], dtype=object))])
at = fits.TableHDU.from_columns([fits.Column(name='x', format='F8.3', array=np.array([1.25, 2.5])), fits.Column(name='n', format='A4', array=np.array(['ab', 'c']))])
fits.HDUList([h0, fits.ImageHDU(cube), fits.BinTableHDU.from_columns(cols), at, fits.ImageHDU(np.array([[0, 65535], [1, 32768]], np.uint16))]).writeto(os.path.join(TMP, 'ref.fits'))
W, _ = run("p = fitsread('ref.fits'); r = fitsread('ref.fits', 'raw'); c = fitsread('ref.fits', 'image'); u = fitsread('ref.fits', 'image', 2);"
           "b = fitsread('ref.fits', 'binarytable'); q = fitsread('ref.fits', 'asciitable'); info = fitsinfo('ref.fits');"
           "sel = fitsread('ref.fits', 'binarytable', 'TableColumns', [1 3], 'TableRows', [3 1]); pr = fitsread('ref.fits', 'PixelRegion', {2:3, 1:2});")
near('fitsread: the primary image scaled by BSCALE and BZERO, NAXIS2 rows', W['p'], img * 2.0 + 10)
C("fitsread 'raw': the stored class", a(W['r']).dtype == np.int16 and a(W['r']).tolist() == img.tolist())
near('fitsread: a cube with NAXIS3 as the third dimension', W['c'], np.transpose(cube, (1, 2, 0)).astype(float))
near('fitsread: uint16 stored with BZERO', W['u'], [[0, 65535], [1, 32768]])
b = W['b'].a.reshape(-1)
C('fitsread binary table: columns of their classes', a(b[0]).dtype == np.int32 and a(b[1]).dtype == np.float32 and a(b[4]).dtype == np.int64 and a(b[3]).dtype == bool)
C('fitsread binary table: text, a repeat count, variable-length arrays', [text(x) for x in b[2].a.reshape(-1)] == ['ab', 'cde', 'f'] and a(b[1]).shape == (3, 2)
  and a(b[5].a[0, 0]).reshape(-1).tolist() == [1.0, 2.0] and a(b[5].a[2, 0]).size == 0)
C('fitsread ASCII table: numbers and text', a(W['q'].a[0, 0]).reshape(-1).tolist() == [1.25, 2.5] and [text(x) for x in W['q'].a[0, 1].a.reshape(-1)] == ['ab', 'c'])
C("fitsread 'TableColumns' and 'TableRows'", W['sel'].a.shape == (1, 2) and a(W['sel'].a[0, 0]).reshape(-1).tolist() == [3, 1])
near("fitsread 'PixelRegion'", W['pr'], (img * 2.0 + 10)[1:3, 0:2])
info = W['info']
C('fitsinfo: the parts and the primary header', [text(c) for c in info.get1('Contents').a.reshape(-1)] == ['Primary', 'Image', 'Binary Table', 'ASCII Table', 'Image']
  and a(info.get1('PrimaryData').get1('Size')).tolist() == [[3.0, 4.0]] and info.get1('PrimaryData').get1('Slope') == 2.0)
kw = info.get1('PrimaryData').get1('Keywords').a
C("fitsinfo: a string keyword with a quote in it", any(text(kw[i, 0]) == 'OBJECT' and text(kw[i, 1]) == "M31 'x'" for i in range(kw.shape[0])))
W, _ = run("fitswrite(uint16([1 2 3; 4 5 65535]), 'w.fits'); fitswrite(single(reshape(1:24, 2, 3, 4)), 'w.fits', 'WriteMode', 'append');"
           "fitswrite(int8([-128 5; 127 0]), 'w8.fits'); fitswrite(uint64([0 2^63; 5 7]), 'w64.fits'); fitswrite(logical([1 0 1]), 'wl.fits');"
           "back = fitsread('w.fits', 'image'); fitsdisp('w.fits', 'Index', 1);")
f = fits.open(os.path.join(TMP, 'w.fits'))
C('fitswrite: astropy reads uint16 with its class, NAXIS1 the columns', f[0].data.dtype == np.uint16 and f[0].data.tolist() == [[1, 2, 3], [4, 5, 65535]])
C("fitswrite 'append': an image extension astropy reads", f[1].data.shape == (4, 2, 3) and f[1].data[2].tolist() == [[13, 15, 17], [14, 16, 18]])
C('fitswrite: int8, uint64 and logical as astropy reads them', fits.open(os.path.join(TMP, 'w8.fits'))[0].data.tolist() == [[-128, 5], [127, 0]]
  and fits.open(os.path.join(TMP, 'w64.fits'))[0].data.tolist() == [[0, 2 ** 63], [5, 7]] and fits.open(os.path.join(TMP, 'wl.fits'))[0].data.tolist() == [[1, 0, 1]])
near('fitsread of the appended image', a(W['back'])[:, :, 2], [[13, 15, 17], [14, 16, 18]])
raises("fitsread('t.parquet')", 'not a FITS file')
raises("fitsread('ref.fits', 'image', 5)", 'parts of the kind')
raises("fitswrite({1}, 'x.fits')", 'numeric or logical')

# ---- writetimetable --------------------------------------------------------------------------------------------------------------

W, _ = run("TT = timetable(datetime(2024,1,[1;2]), [10;20], 'VariableNames', {'v'}); writetimetable(TT, 'tt.csv'); T = readtable('tt.csv');")
C('writetimetable: the row times first, then the variables', W['T'].names == ['Time', 'v'] and a(W['T'].vars[1]).reshape(-1).tolist() == [10.0, 20.0])
raises("writetimetable(table(1), 'x.csv')", 'takes a timetable')

# ---- the desktop and the engine ------------------------------------------------------------------------------------------------

EVENTS.clear()
W, out = run("commandwindow; commandhistory; workspace; filebrowser; x = struct('d', 1); openvar('x.d'); r = matlabRelease; rel = r.Release;"
             "n = maxNumCompThreads; old = maxNumCompThreads(1); m = maxNumCompThreads; maxNumCompThreads('automatic');"
             "[u, s] = memory; ts = license('test', 'statistics_toolbox'); te = license('test', 'Econometrics_Toolbox'); [tc, msg] = license('checkout', 'Econometrics_Toolbox'); memory")
desk = [(e.get('what'), e.get('name')) for e in EVENTS if e.get('type') == 'desktop']
C('commandwindow, commandhistory, workspace, filebrowser and openvar: what the page is asked to show',
  desk == [('commandwindow', None), ('history', None), ('workspace', None), ('files', None), ('openvar', 'x.d')], str(desk))
C('matlabRelease: Release "PyLAB"', text(W['rel'].a[0, 0]) == 'PyLAB' if hasattr(W['rel'], 'a') else False)
C('maxNumCompThreads: the number before, the number set', W['old'] == W['n'] and W['m'] == 1.0)
C('memory: what the engine uses', W['u'].get1('MemUsedMATLAB') > 0 and 'Memory used by PyLAB' in out)
C("license: 'test' and 'checkout' by the functions PyLAB has", W['ts'] == 1.0 and W['te'] == 0.0 and W['tc'] == 0.0 and 'does not have' in text(W['msg']))
raises("openvar('x; disp(1)')", 'the name of a variable')
raises("license('frobnicate')", "'test', 'checkout' or 'inuse'")

# ---- plots ------------------------------------------------------------------------------------------------------------------------

W, _ = run("figure; h = ezsurfc('x^2 - y^2', [-1 1 -1 1], 20); tt = get(gca, 'Title'); t1 = tt.String; z = h.ZData; xl = h.XData;"
           "figure; ezplot3('cos(t)', 'sin(t)', 't', [0 6*pi], 'animate'); tt = get(gca, 'Title'); t2 = tt.String;"
           "figure; ezpolar('1 + cos(t)'); tt = get(gca, 'Title'); t3 = tt.String;"
           "figure; h2 = ezsurf(@(x, y) x.*y); lim = [min(h2.XData(:)) max(h2.XData(:))]; nz = size(h2.ZData);"
           "figure; ezcontourf('x*y'); figure; ezmeshc('sin(x)*cos(y)');")
near("ezsurfc: f(x, y) of text on the grid asked for", W['z'], a(W['xl']) ** 2 - np.linspace(-1, 1, 20).reshape(-1, 1) ** 2, 1e-12)
C('ez functions: titled with the function', text(W['t1']) == 'x^2 - y^2' and text(W['t2']) == 'x = cos(t), y = sin(t), z = t' and text(W['t3']) == 'r = 1 + cos(t)')
near('ezsurf: -2*pi to 2*pi on a 60-by-60 grid unless given', (W['lim'], W['nz']), ([-2 * math.pi, 2 * math.pi], [60, 60]), 1e-12)
W, _ = run("figure; [X, Y, Z] = peaks(20); surf(X, Y, Z); hold on; p = plot3([0 1], [0 1], [2 4], 'o'); camlookat(p); va = camva; tg = camtarget; md = get(gca, 'CameraViewAngleMode');"
           "camlookat(gca); md2 = get(gca, 'CameraViewAngleMode');")
near('camlookat: the target the middle of the objects', W['tg'], [[0.5, 0.5, 3]])
C('camlookat: a narrower view, back to automatic for the axes', W['va'] < 10.3396 and text(W['md']) == 'manual' and text(W['md2']) == 'auto')
W, _ = run("[x, y, z] = meshgrid(-2:0.5:2); u = -y; v = x; w = 0.2*ones(size(x)); figure; h = streamribbon(x, y, z, u, v, w, 1, 0, -2); n = numel(h); s = size(h(1).XData);"
           "X = h(1).XData; Y = h(1).YData; Z = h(1).ZData;")
X, Y, Z = a(W['X']), a(W['Y']), a(W['Z'])
mid = np.column_stack([X.mean(1), Y.mean(1), Z.mean(1)])
width = np.sqrt((X[:, 1] - X[:, 0]) ** 2 + (Y[:, 1] - Y[:, 0]) ** 2 + (Z[:, 1] - Z[:, 0]) ** 2)
C('streamribbon: one ribbon of two edges about the streamline, a grid cell wide', W['n'] == 1.0 and a(W['s'])[0, 1] == 2 and np.allclose(width, 0.5)
  and np.allclose(np.hypot(mid[:, 0], mid[:, 1])[:20], 1.0, atol=0.02))
from plab.builtins import plotfill as PF  # noqa: E402
L = np.column_stack([np.cos(np.linspace(0, 1, 11)), np.sin(np.linspace(0, 1, 11)), np.zeros(11)])
tw = PF._integrate_twist(L, np.full(11, 0.6), np.full(11, 2.0))
near('streamribbon: the twist is the spin over the speed, summed along the arc', tw[-1], 0.3 * np.sum(np.linalg.norm(np.diff(L, axis=0), axis=1)), 1e-12)
W, _ = run("n1 = diffuse([0 0 1], [0 1 0], [1 0 0], [0 0 1]); s1 = specular(0, 0, 1, [1 0 1], [-1 0 1]); s2 = specular(0, 0, 1, [1 0 1], [0 0 1], 2);"
           "s3 = specular(0, 0, -1, [0 0 1], [0 0 1]); n2 = diffuse(0, 0, 1, [0 90]);")
near('diffuse: the cosine of normal and light', W['n1'], [[1, 0, 0]])
near('specular: the mirrored light into the view gives 1, away from it its cosine to the spread, 0 behind', (W['s1'], W['s2'], W['s3']), (1.0, 0.5, 0.0), 1e-12)
near('diffuse: a light given by azimuth and elevation', W['n2'], 1.0, 1e-12)
W, _ = run("f = figure; orient(f, 'landscape'); o = orient(f); ps = get(f, 'PaperSize'); orient tall; o2 = orient(f); pp = get(f, 'PaperPosition');")
C("orient: 'landscape' turns the paper, 'tall' fills the page", text(W['o']) == 'landscape' and a(W['ps']).tolist() == [[11.0, 8.5]] and text(W['o2']) == 'portrait'
  and a(W['pp']).tolist() == [[0.25, 0.25, 8.0, 10.5]])
raises("orient('sideways')", "'portrait', 'landscape' or 'tall'")
raises("specular(0, 0, 1, [0 0 0], [0 0 1])", 'A direction is')
W, out = run("figure; plot(1:3); copygraphics(gcf); ok = 1;")
C('copygraphics: asks the page (here no page: a warning)', W['ok'] == 1.0 and 'could not be copied' in out)

# ---- copy and events ----------------------------------------------------------------------------------------------------------

put('cls/Counter.m', """classdef Counter < matlab.mixin.Copyable
  properties
    Count = 0
    Child
  end
  properties (NonCopyable)
    Id = 7
  end
  events
    Overflow
  end
  methods
    function bump(obj)
      obj.Count = obj.Count + 1;
      if obj.Count > 2, notify(obj, 'Overflow'); end
    end
  end
end
""")
put('cls/Deep.m', """classdef Deep < matlab.mixin.Copyable
  properties
    Inner
  end
  methods (Access = protected)
    function cp = copyElement(obj)
      cp = copyElement@matlab.mixin.Copyable(obj);
      cp.Inner = copy(obj.Inner);
    end
  end
end
""")
put('cls/Plain.m', """classdef Plain < handle
  properties
    v = 1
  end
end
""")
W, out = run("addpath('cls'); a = Counter; a.Count = 5; a.Id = 99; a.Child = Plain; b = copy(a); b.Count = 1; ca = a.Count; cb = b.Count; ib = b.Id;"
             "b.Child.v = 42; shared = a.Child.v; d = Deep; d.Inner = Counter; d.Inner.Count = 3; e = copy(d); e.Inner.Count = 8; di = d.Inner.Count;"
             "ev = events(a); hits = 0; l = addlistener(a, 'Overflow', @(s, e) disp('overflow!')); bump(a);"
             "gone = addlistener(Plain, 'ObjectBeingDestroyed', @(s, e) disp('going')); p = Plain; addlistener(p, 'ObjectBeingDestroyed', @(s, e) disp(['bye ' e.EventName])); delete(p); evp = events('Plain');")
C('copy: a new handle with the values (changing it leaves the original)', W['ca'] == 5.0 and W['cb'] == 1.0)
C('copy: NonCopyable properties at their defaults', W['ib'] == 7.0)
C('copy: handles in properties shared (a shallow copy)', W['shared'] == 42.0)
C('copy: a copyElement override that copies deeper', W['di'] == 3.0)
C('events: the class events, then ObjectBeingDestroyed', [text(c) for c in W['ev'].a.reshape(-1)] == ['Overflow', 'ObjectBeingDestroyed']
  and [text(c) for c in W['evp'].a.reshape(-1)] == ['ObjectBeingDestroyed'])
C('notify: a listener runs', 'overflow!' in out)
C('delete: ObjectBeingDestroyed notified', 'bye ObjectBeingDestroyed' in out)
raises("addpath('cls'); copy(Plain)", 'matlab.mixin.Copyable')
raises("copy(5)", "Undefined function 'copy'")
raises("events(5)", 'takes an object or a class name')

# ---- surface fits ---------------------------------------------------------------------------------------------------------------

rs = np.random.default_rng(1)
x, y = rs.uniform(-2, 2, 60), rs.uniform(-2, 2, 60)
z = 1 + 2 * x - 3 * y + 0.5 * x ** 2 + x * y + 0.01 * rs.standard_normal(60)
xs = f"x = {x.tolist()}'; y = {y.tolist()}'; z = {z.tolist()}';"
B = np.column_stack([np.ones(60), x, y, x ** 2, x * y, y ** 2])
cref, *_ = np.linalg.lstsq(B, z, rcond=None)
res = z - B @ cref
cov = res @ res / 54 * np.linalg.inv(B.T @ B)
W, out = run(xs + "[sf, gof, op] = fit([x y], z, 'poly22'); c = coeffvalues(sf); ci = confint(sf); v = sf(0.5, -1); v2 = sf([0.5 -1; 0 0]); v3 = feval(sf, 0.5, -1);"
             "[fx, fy, fxx, fxy, fyy] = differentiate(sf, 0.5, -1); names = coeffnames(sf); nc = numcoeffs(sf); fo = formula(sf); p00 = sf.p00;"
             "sfn = fit([x y], z, 'poly22', 'Normalize', 'on'); vn = sfn(0.5, -1); [gx, gy] = differentiate(sfn, 0.5, -1); pint = predint(sf, [0.5 -1]);"
             "sf3 = fit(x, y, z, 'poly11'); c3 = coeffvalues(sf3); disp(sf)")
from scipy import stats as SS  # noqa: E402
near('fit poly22: the coefficients of least squares on 1, x, y, x^2, xy, y^2', W['c'], cref.reshape(1, -1), 1e-9)
near('fit poly22: confidence bounds from the residual variance', W['ci'], np.vstack([cref - SS.t.ppf(0.975, 54) * np.sqrt(np.diag(cov)), cref + SS.t.ppf(0.975, 54) * np.sqrt(np.diag(cov))]), 1e-9)
C('fit: gof and output of a surface', W['gof'].get1('dfe') == 54.0 and abs(W['gof'].get1('sse') - res @ res) < 1e-9 and W['op'].get1('numobs') == 60.0)
p = np.array([1, 0.5, -1, 0.25, -0.5, 1])
near('sf(x, y), sf([x y]) and feval', (W['v'], W['v2'], W['v3']), (p @ cref, [[p @ cref], [cref[0]]], p @ cref), 1e-9)
near('differentiate: fx, fy, fxx, fxy, fyy of a polynomial surface', (W['fx'], W['fy'], W['fxx'], W['fxy'], W['fyy']),
     (cref[1] + 2 * cref[3] * 0.5 + cref[4] * -1, cref[2] + cref[4] * 0.5 + 2 * cref[5] * -1, 2 * cref[3], cref[4], 2 * cref[5]), 1e-9)
C('coeffnames, numcoeffs, formula, sf.p00', [text(c) for c in W['names'].a.reshape(-1)] == ['p00', 'p10', 'p01', 'p20', 'p11', 'p02'] and W['nc'] == 6.0
  and text(W['fo']) == 'p00 + p10*x + p01*y + p20*x^2 + p11*x*y + p02*y^2' and abs(W['p00'] - cref[0]) < 1e-9)
near("'Normalize' 'on': the same surface, derivatives through the scaling", (W['vn'], W['gx'], W['gy']), (W['v'], W['fx'], W['fy']), 1e-8)
J = p.reshape(1, -1)
var = J @ cov @ J.T + res @ res / 54
near('predint: new observations', W['pint'], [[p @ cref - SS.t.ppf(0.975, 54) * math.sqrt(var[0, 0]), p @ cref + SS.t.ppf(0.975, 54) * math.sqrt(var[0, 0])]], 1e-8)
c11, *_ = np.linalg.lstsq(np.column_stack([np.ones(60), x, y]), z, rcond=None)
near('fit(x, y, z, type): the two variables apart', W['c3'], c11.reshape(1, -1), 1e-9)
C('sfit: shown as a model with bounds', 'Linear model Poly22:' in out and 'f(x,y) = p00 + p10*x' in out and 'with 95% confidence bounds' in out)
W, _ = run(xs + "s1 = fit([x y], z, 'a + b*x + c*y + d*x^2', 'StartPoint', [0 0 0 0]); c1 = coeffvalues(s1);"
           "s2 = fit([x y], z, @(a, b, x, y) a + b*x.*y); c2 = coeffvalues(s2);"
           "ft = fittype('a*x^2 + b*y', 'independent', {'x', 'y'}, 'dependent', 'z'); s4 = sfit(ft, 2, 3); v4 = s4(1, 2); f4 = ft(2, 3, 1, 2);"
           "cf = cfit(fittype('poly1'), 2, 1); v5 = cf(3);")
c4, *_ = np.linalg.lstsq(np.column_stack([np.ones(60), x, y, x ** 2]), z, rcond=None)
near('fit: a surface written in x and y, by nonlinear least squares', W['c1'], c4.reshape(1, -1), 1e-6)
c5, *_ = np.linalg.lstsq(np.column_stack([np.ones(60), x * y]), z, rcond=None)
near('fit: a surface as an anonymous function of the coefficients, x and y', W['c2'], c5.reshape(1, -1), 1e-6)
near('sfit and fittype of two variables: evaluated', (W['v4'], W['f4'], W['v5']), (8.0, 8.0, 7.0))
from scipy import interpolate as SI  # noqa: E402
W, _ = run(xs + "a1 = fit([x y], z, 'linearinterp'); v1 = a1(0.3, -0.2); a2 = fit([x y], z, 'cubicinterp'); v2 = a2(0.3, -0.2);"
           "a3 = fit([x y], z, 'biharmonicinterp'); v3 = a3(x(1:5), y(1:5)); a4 = fit([x y], z, 'thinplateinterp'); v4 = a4(x(6), y(6)); v4b = a4(0.3, -0.2);"
           "a5 = fit([x y], z, 'nearestinterp'); v5 = a5(x(7), y(7)); out5 = a5(50, 50);")
P = np.column_stack([x, y])
near('linearinterp: scipy LinearNDInterpolator', W['v1'], float(SI.LinearNDInterpolator(P, z)([[0.3, -0.2]])[0]), 1e-12)
U, iu = np.unique(P, axis=0, return_index=True)
near('cubicinterp: scipy CloughTocher2DInterpolator (of the points in sorted order)', W['v2'], float(SI.CloughTocher2DInterpolator(U, z[iu])([[0.3, -0.2]])[0]), 1e-12)
near('biharmonicinterp: through the points', W['v3'], z[:5].reshape(-1, 1), 1e-8)
near('thinplateinterp: through the points, and scipy RBFInterpolator between them', (W['v4'], W['v4b']),
     (z[5], float(SI.RBFInterpolator(P, z, kernel='thin_plate_spline', degree=1)([[0.3, -0.2]])[0])), 1e-8)
C('nearestinterp: the nearest value, NaN outside the points', abs(W['v5'] - z[6]) < 1e-12 and np.isnan(W['out5']))
plane = 1 + 2 * x - 3 * y
W, _ = run(f"x = {x.tolist()}'; y = {y.tolist()}'; z = {plane.tolist()}'; l1 = fit([x y], z, 'lowess', 'Span', 0.4); v = l1(0.2, 0.3);"
           "l2 = fit([x y], z + 0*x.^2, 'loess'); w = l2(-0.5, 0.5); l3 = fit([x y], z, 'lowess', 'Robust', 'on'); r = l3(0, 0);")
near('lowess and loess: a plane kept exactly (local least squares)', (W['v'], W['w'], W['r']), (1 + 0.4 - 0.9, 1 - 1 - 1.5, 1.0), 1e-9)
W, _ = run(xs + "tf = excludedata(x, y, 'box', [-1 1 -1 1]); td = excludedata(x, y, 'domain', [0 2]); tr = excludedata(x, y, 'range', [-2 0]);"
           "ti = excludedata(x, y, 'indices', [2 4]); se = fit([x y], z, 'poly11', 'Exclude', tf); ce = coeffvalues(se);")
inbox = (np.abs(x) <= 1) & (np.abs(y) <= 1)
C('excludedata: true outside the box, domain and range, and at the indices', a(W['tf']).reshape(-1).tolist() == (~inbox).tolist()
  and a(W['td']).reshape(-1).tolist() == (x < 0).tolist() and a(W['tr']).reshape(-1).tolist() == (y > 0).tolist() and np.flatnonzero(a(W['ti'])).tolist() == [1, 3])
ck, *_ = np.linalg.lstsq(np.column_stack([np.ones(inbox.sum()), x[inbox], y[inbox]]), z[inbox], rcond=None)
near("fit 'Exclude': the points left out", W['ce'], ck.reshape(1, -1), 1e-9)
W, _ = run(xs + "sf = fit([x y], z, 'poly11'); figure; plot(sf, [x y], z); ax = gca; k1 = numel(ax.Children); figure; plot(sf, [x y], z, 'Style', 'Residuals');"
           "figure; plot(sf, 'Style', 'Contour'); figure; h = plot(sf, [x y], z, 'Style', 'PredObs'); ax = gca; k2 = numel(ax.Children);")
C('plot of an sfit: the surface and the data; the bounds with PredObs', W['k1'] == 2.0 and W['k2'] == 4.0)
raises("fit([1 2; 3 4; 5 6], [1;2;3], 'poly1')", 'is a curve model')
raises("fit([1 2; 3 4; 5 6], [1;2;3], 'a + b')", 'no surface model')
raises("fit([1 2; 3 4], [1;2], 'poly22')", 'fewer data points')
raises("excludedata(1:3, 1:3, 'circle', 1)", "'box', 'domain', 'range' or 'indices'")
raises("sfit(fittype('poly11'), 1, 2)", 'Give a value for each of the 3 coefficients')

# ---- corrcov --------------------------------------------------------------------------------------------------------------------------

raises('corrcov(NaN)', 'symmetric')
raises('corrcov(NaN(2, 2))', 'symmetric')
raises('corrcov(-ones(2))', 'positive semi-definite')
W, _ = run("r1 = corrcov(zeros(2)); r2 = corrcov(ones(2)); [r3, s3] = corrcov(cov(magic(4)));")
near('corrcov: a zero variance gives NaN; ones stay ones', (W['r1'], W['r2']), (np.full((2, 2), np.nan), np.ones((2, 2))))
near('corrcov: the correlation of a covariance matrix', W['r3'], np.corrcoef(np.array([[16, 2, 3, 13], [5, 11, 10, 8], [9, 7, 6, 12], [4, 14, 15, 1]], float).T), 1e-12)

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(C.done())
