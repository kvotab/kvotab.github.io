"""Files, tables, animation and the desktop's tools, run natively
(CPython with numpy, scipy, h5py and Pillow): HDF5 (checked with h5py
itself), structs in XML and JSON, spreadsheets (checked with zipfile's
view of the workbook), readtimetable, stack and unstack, animated lines,
AVI videos (their RIFF chunks read here), the diary, the profiler,
breakpoints from commands, dbstack, the code checker, the clipboard,
lookfor and datetick.

    python3 test_tools.py          (from any folder)
"""
import asyncio
import os
import struct
import sys
import tempfile
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab import worker_api as WA  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-tools-')


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


def text(v):
    from plab.values import py_str
    return v.str() if isinstance(v, Char) else py_str(v)


def path(name):
    return os.path.join(TMP, name)


def write(name, body):
    with open(path(name), 'w') as f:
        f.write(body)


# ---- HDF5 --------------------------------------------------------------------------------------------------------------------
import h5py  # noqa: E402

W, out = run("h5create('d.h5', '/x', [3 4]); A = reshape(1:12, 3, 4); h5write('d.h5', '/x', A); B = h5read('d.h5', '/x'); "
             "p = h5read('d.h5', '/x', [2 2], [2 3]); st = h5read('d.h5', '/x', [1 1], [2 2], [2 2]); "
             "h5create('d.h5', '/g/u', [Inf 2], 'ChunkSize', [4 2], 'Datatype', 'int16', 'Deflate', 4); "
             "h5write('d.h5', '/g/u', int16([1 2; 3 4]), [1 1], [2 2]); h5write('d.h5', '/g/u', int16([5 6]), [3 1], [1 2]); U = h5read('d.h5', '/g/u'); cu = class(U); "
             "h5writeatt('d.h5', '/x', 'units', 'm/s'); h5writeatt('d.h5', '/', 'version', int32(3)); un = h5readatt('d.h5', '/x', 'units'); ve = h5readatt('d.h5', '/', 'version'); cv = class(ve); "
             "info = h5info('d.h5'); dn = info.Datasets(1).Name; ds = info.Datasets(1).Dataspace.Size; gn = info.Groups(1).Name; gm = info.Groups(1).Datasets(1).Dataspace.MaxSize; "
             "ch = info.Groups(1).Datasets(1).ChunkSize; fl = info.Groups(1).Datasets(1).Filters(1).Name; an = info.Attributes(1).Name;\nh5disp('d.h5')")
near('h5write then h5read: the matrix back; part of it by start and count; and with a stride', (W['B'], W['p'], W['st']),
     (np.arange(1, 13).reshape(4, 3).T, [[5, 8, 11], [6, 9, 12]], [[1, 7], [3, 9]]))
with h5py.File(path('d.h5'), 'r') as f:
    fx = f['x'][()]
    fu = f['g/u']
    fu_shape, fu_max, fu_chunks, fu_comp, fu_dt = fu.shape, fu.maxshape, fu.chunks, fu.compression, fu.dtype
    att = f['x'].attrs['units']
near('in the file the dimensions are reversed (h5py sees 4 by 3, the same elements in order)', fx, np.arange(1, 13).reshape(4, 3))
same('a dataset that grows: h5py sees its shape, unlimited rows, chunks, gzip and int16', (fu_shape, fu_max, fu_chunks, fu_comp, str(fu_dt)),
     ((2, 3), (2, None), (2, 4), 'gzip', 'int16'))
near('written in two parts and read back as int16', W['U'], [[1, 2], [3, 4], [5, 6]])
same('attributes: text and int32', (text(W['un']), a(W['ve']).item(), text(W['cv']), att if isinstance(att, str) else att.decode()), ('m/s', 3.0, 'int32', 'm/s'))
same('h5info: datasets, sizes, groups, chunks, filters and attributes', (text(W['dn']), a(W['ds']).tolist(), text(W['gn']), a(W['gm']).tolist(), a(W['ch']).tolist(), text(W['fl']), text(W['an'])),
     ('x', [[3.0, 4.0]], '/g', [[np.inf, 2.0]], [[4.0, 2.0]], 'deflate', 'version'))
C('h5disp shows the tree with sizes and types', "Dataset 'x'" in out and 'Size:  3x4' in out and 'H5T_STD_I16LE (int16)' in out and "Group '/g'" in out and 'MaxSize:  Infx2' in out, out)
with h5py.File(path('py.h5'), 'w') as f:
    f['m'] = np.arange(6.0).reshape(2, 3)
    f['v'] = np.arange(4, dtype=np.int32)
    f.create_dataset('s', data=np.array(['ab', 'cde'], dtype=object), dtype=h5py.string_dtype())
    f['c'] = np.array([(1, 2.5), (3, 4.5)], dtype=[('a', 'i4'), ('b', 'f8')])
W, _ = run("m = h5read('py.h5', '/m'); v = h5read('py.h5', '/v'); s = h5read('py.h5', '/s'); c = h5read('py.h5', '/c'); cb = c.b;")
near('a file h5py wrote: 2-by-3 read as 3-by-2, a vector as a column', (W['m'], W['v']), (np.arange(6.0).reshape(2, 3).T, [[0], [1], [2], [3]]))
same('strings as a cell; a compound type as a struct of columns', ([text(x) for x in W['s'].a.reshape(-1)], a(W['cb']).tolist()), (['ab', 'cde'], [[2.5], [4.5]]))
raises("h5read('d.h5', '/nope')", 'does not exist')
raises("h5write('d.h5', '/x', ones(2))", 'The data are 2x2 and the dataset 3x4')
raises("h5create('d.h5', '/x', [3 4])", 'already exists')
raises("h5create('d.h5', '/y', [Inf 3])", 'needs ChunkSize')

# ---- structs in XML and JSON --------------------------------------------------------------------------------------------------
W, _ = run('S.name = "pump"; S.flow = 12.5; S.tags = ["a" "b"]; S.unitAttribute = "l/s"; S.part(1).id = 1; S.part(2).id = 2; S.part(2).note = "x"; '
           "writestruct(S, 's.xml'); R = readstruct('s.xml'); rn = R.name; rf = R.flow; rt = R.tags; ru = R.unitAttribute; p2 = R.part(2).id; p2n = R.part(2).note; "
           "np = numel(R.part); writestruct(S, 's.json'); J = readstruct('s.json'); jf = J.flow;")
xml = open(path('s.xml')).read()
C('writestruct XML: a root element struct, the Attribute field as an attribute, arrays as repeated elements',
  '<struct unit="l/s">' in xml and xml.count('<tags>') == 2 and xml.count('<part>') == 2 and '<flow>12.5</flow>' in xml, xml)
same('readstruct reads it back: strings, numbers, a string array, attributes and a struct array',
     (text(W['rn']), float(W['rf']), [str(x) for x in W['rt'].a.reshape(-1)], text(W['ru']), float(W['p2']), text(W['p2n']), W['np']),
     ('pump', 12.5, ['a', 'b'], 'l/s', 2.0, 'x', 2.0))
near('JSON round trip', W['jf'], 12.5)
W, _ = run('p(1).id = 1; p(2).id = 2; q = p; q(3).note = "x"; fq = fieldnames(q); fp = fieldnames(p); e1 = isempty(q(1).note); sz = size(q);')
same('s(k).f = v with a new field: every element gets it, a copy keeps its own fields', ([text(x) for x in W['fq'].a.reshape(-1)], [text(x) for x in W['fp'].a.reshape(-1)], bool(W['e1']), a(W['sz']).tolist()),
     (['id', 'note'], ['id'], True, [[1.0, 3.0]]))
write('doc.xml', '<?xml version="1.0"?>\n<catalog lang="en"><book id="7">Odd<title>Rocks</title><year>1999</year></book><book id="8"><title>Water</title><year>2004</year></book></catalog>')
W, _ = run("D = readstruct('doc.xml'); b2 = D.book(2).title; y1 = D.book(1).year; i2 = D.book(2).idAttribute; t1 = D.book(1).Text; la = D.langAttribute; "
           "B = readstruct('doc.xml', 'StructNodeName', 'book'); bt = B.title; N = readstruct('doc.xml', 'ReadAttributes', false); f = isfield(N, 'langAttribute');")
same('a hand-written XML: repeated elements, numbers, attributes, text beside children; StructNodeName; ReadAttributes',
     (text(W['b2']), float(W['y1']), float(W['i2']), text(W['t1']), text(W['la']), text(W['bt']), bool(W['f'])),
     ('Water', 1999.0, 8.0, 'Odd', 'en', 'Rocks', False))
write('bad.xml', '<a><b></a>')
raises("readstruct('bad.xml')", 'not well-formed')

# ---- spreadsheets ---------------------------------------------------------------------------------------------------------------
W, _ = run("xlswrite('b.xlsx', [1 2; 3 4]); xlswrite('b.xlsx', {'name', 'val'; 'x', 5}, 'Other', 'B2'); xlswrite('b.xlsx', [9 9], 1, 'C1'); "
           "[st, sh] = xlsfinfo('b.xlsx'); [n, t, r] = xlsread('b.xlsx', 'Other'); n1 = xlsread('b.xlsx'); n2 = xlsread('b.xlsx', 1, 'A2:B2'); nr = xlsread('b.xlsx', 'A1:A2');")
same('xlsfinfo: a spreadsheet with both sheets', (text(W['st']), [text(x) for x in W['sh'].a.reshape(-1)]), ('Microsoft Excel Spreadsheet', ['Sheet1', 'Other']))
near('xlsread: the first sheet, rewritten in place (C1:D1 added); a range; a range alone', (W['n1'], W['n2'], W['nr']), ([[1, 2, 9, 9], [3, 4, np.nan, np.nan]], [[3, 4]], [[1], [3]]))
same('num, txt and raw of the other sheet', (a(W['n']).tolist(), [text(x) for x in W['t'].a.reshape(-1, order='F')], W['r'].a.shape),
     ([[5.0]], ['name', 'x', 'val', ''], (3, 3)))
with zipfile.ZipFile(path('b.xlsx')) as z:
    names = set(z.namelist())
C('the workbook has two worksheets, shared strings and its relationships', {'xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml', 'xl/sharedStrings.xml', 'xl/_rels/workbook.xml.rels', '[Content_Types].xml'} <= names, names)
try:
    import openpyxl
    wb = openpyxl.load_workbook(path('b.xlsx'))
    C('openpyxl opens it: the sheets and their values', wb.sheetnames == ['Sheet1', 'Other'] and wb['Other']['B2'].value == 'name' and wb['Other']['C3'].value == 5 and wb['Sheet1']['D1'].value == 9,
      (wb.sheetnames, wb['Other']['B2'].value))
except ImportError:
    pass
write('tt.csv', 't,x\n2024-01-01,1\n2024-01-02,2\n2024-01-03,4\n')
W, _ = run("TT = readtimetable('tt.csv'); c = class(TT); x = TT.x; d = day(TT.t);")
same('readtimetable: the dates as row times', (text(W['c']), a(W['x']).tolist(), a(W['d']).tolist()), ('timetable', [[1.0], [2.0], [4.0]], [[1.0], [2.0], [3.0]]))

# ---- stack and unstack ---------------------------------------------------------------------------------------------------------------
W, out = run("T = table([1;1;2;2;2], {'a';'b';'a';'b';'b'}, [10;20;30;40;5], 'VariableNames', {'id', 'k', 'v'}); W = unstack(T, 'v', 'k'); "
             "wn = W.Properties.VariableNames; wa = W.a; wb = W.b; M = unstack(T, 'v', 'k', 'AggregationFunction', @max); mb = M.b; "
             "T2 = T([1 3 4], :); G = unstack(T2, 'v', 'k'); gb = G.b; "
             "S = stack(W, {'a', 'b'}); sn = S.Properties.VariableNames; sv = S.a_b; si = cellstr(S.a_b_Indicator); sid = S.id; "
             "S2 = stack(W, {'a', 'b'}, 'NewDataVariableName', 'v', 'IndexVariableName', 'k'); s2 = S2.Properties.VariableNames;")
same('unstack: a row for each id, a variable for each k, values summed', ([text(x) for x in W['wn'].a.reshape(-1)], a(W['wa']).tolist(), a(W['wb']).tolist()),
     (['id', 'a', 'b'], [[10.0], [30.0]], [[20.0], [45.0]]))
near("'AggregationFunction' @max; a missing pair is NaN", (W['mb'], W['gb']), ([[20], [40]], [[np.nan], [40]]))
same('stack: the stacked pair after the constants, rows interleaved', ([text(x) for x in W['sn'].a.reshape(-1)], a(W['sv']).reshape(-1).tolist(), [text(x) for x in W['si'].a.reshape(-1)], a(W['sid']).reshape(-1).tolist()),
     (['id', 'a_b_Indicator', 'a_b'], [10.0, 20.0, 30.0, 45.0], ['a', 'b', 'a', 'b'], [1.0, 1.0, 2.0, 2.0]))
same('stack with new names', [text(x) for x in W['s2'].a.reshape(-1)], ['id', 'k', 'v'])
raises("unstack(table({'a';'a'}, {'x';'x'}, {'p';'q'}, 'VariableNames', {'g','k','v'}), 'v', 'k')", 'give an AggregationFunction')

# ---- animated lines -----------------------------------------------------------------------------------------------------------------
W, _ = run("close all; an = animatedline('Color', 'r', 'MaximumNumPoints', 4); for k = 1:6, addpoints(an, k, k^2); end; [x, y] = getpoints(an); "
           "ty = get(an, 'Type'); c = an.Color; clearpoints(an); [x0, y0] = getpoints(an); a3 = animatedline(1, 2, 3); addpoints(a3, [4 5], [6 7], [8 9]); "
           "[p, q, r] = getpoints(a3); kids = numel(get(gca, 'Children')); close all")
same('addpoints adds to the end, the oldest dropped beyond MaximumNumPoints', (a(W['x']).tolist(), a(W['y']).tolist()), ([[3.0, 4.0, 5.0, 6.0]], [[9.0, 16.0, 25.0, 36.0]]))
same("Type 'animatedline'; a line's properties; clearpoints empties it", (text(W['ty']), a(W['c']).tolist(), np.size(W['x0'])), ('animatedline', [[1.0, 0.0, 0.0]], 0))
same('3-D animated lines; both in the axes', (a(W['p']).tolist(), a(W['r']).tolist(), W['kids']), ([[1.0, 4.0, 5.0]], [[3.0, 8.0, 9.0]], 2.0))
raises("close all; h = plot(1:3); addpoints(h, 4, 5)", 'takes an animated line')
raises("close all; an = animatedline(1, 2, 3); addpoints(an, 4, 5)", 'is 3-D')

# ---- videos --------------------------------------------------------------------------------------------------------------------------
W, out = run("v = VideoWriter('m.avi'); v.FrameRate = 12; v.Quality = 90; open(v); for k = 1:5, img = zeros(24, 32, 3); img(:, :, 1) = k/5; img(:, :, 2) = repmat((1:32)/32, 24, 1); writeVideo(v, img); end; close(v); "
             "fc = v.FrameCount; du = v.Duration; "
             "u = VideoWriter('u.avi', 'Uncompressed AVI'); open(u); U = uint8(reshape(0:3*13*10-1, 10, 13, 3)); writeVideo(u, cat(4, U, 255 - U)); close(u); "
             "g = VideoWriter('g', 'Grayscale AVI'); open(g); G = uint8(magic(9) * 3); writeVideo(g, G); close(g); "
             "r = VideoReader('m.avi'); fr = r.FrameRate; nf = r.NumFrames; wd = r.Width; ht = r.Height; f1 = readFrame(r); t1 = r.CurrentTime; n = 1; while hasFrame(r), f = readFrame(r); n = n + 1; end; "
             "ru = VideoReader('u.avi'); A = read(ru); A2 = read(ru, 2); rg = VideoReader('g.avi'); Gr = readFrame(rg); "
             "r.CurrentTime = 0.25; f4 = readFrame(r); m4 = mean(mean(double(f4(:, :, 1)))) / 255;")
same('VideoWriter: frames counted, duration from the frame rate', (W['fc'], float(W['du'])), (5.0, 5 / 12))
near('VideoReader: rate, frames, size; CurrentTime moves on', (W['fr'], W['nf'], W['wd'], W['ht'], W['t1'], W['n']), (12, 5, 32, 24, 1 / 12, 5))
f1 = a(W['f1'])
C('Motion JPEG frames come back close to what was written', f1.shape == (24, 32, 3) and abs(f1[:, :, 0].mean() - 0.2 * 255) < 3 and abs(f1[:, 16, 1].mean() - 17 / 32 * 255) < 4, (f1[:, :, 0].mean(), f1[:, 16, 1].mean()))
U = np.minimum(np.arange(390).reshape(3, 13, 10).transpose(2, 1, 0), 255).astype(float)
near('uncompressed and gray AVI frames come back exactly', (a(W['A'])[:, :, :, 0], a(W['A'])[:, :, :, 1], W['A2'], a(W['Gr'])[:, :, 0]),
     (U, 255 - U, 255 - U, W['G']))
near('CurrentTime set: reading from the fourth frame', W['m4'], 0.8, 0.02)


def chunks(data, start, end):
    i = start
    while i + 8 <= end:
        cid, size = data[i:i + 4], struct.unpack('<I', data[i + 4:i + 8])[0]
        yield cid, i + 8, size
        i += 8 + size + (size & 1)


data = open(path('m.avi'), 'rb').read()
top = {c: (o, s) for c, o, s in chunks(data, 12, len(data))}
movi = [c for c, o, s in chunks(data, 12, len(data)) if c == b'LIST' and data[o:o + 4] == b'movi']
o, s = next((o, s) for c, o, s in chunks(data, 12, len(data)) if c == b'LIST' and data[o:o + 4] == b'movi')
frames = [c for c, _, _ in chunks(data, o + 4, o + s)]
avih = data.find(b'avih')
us, _, _, flags, total = struct.unpack('<IIIII', data[avih + 8:avih + 28])
same('the AVI file: RIFF size, five 00dc frames in movi, an idx1 index of five, the frame count and time in avih',
     (struct.unpack('<I', data[4:8])[0] == len(data) - 8, frames, top[b'idx1'][1] // 16, total, us, flags & 0x10),
     (True, [b'00dc'] * 5, 5, 5, round(1e6 / 12), 0x10))
from PIL import Image  # noqa: E402
ims = [Image.fromarray(np.full((8, 10, 3), k * 40, np.uint8)) for k in range(4)]
ims[0].save(path('a.gif'), save_all=True, append_images=ims[1:], duration=50, loop=0)
W, _ = run("r = VideoReader('a.gif'); n = r.NumFrames; fr = r.FrameRate; f = read(r, 3); v = f(1, 1, 1);")
near('VideoReader reads an animated GIF', (W['n'], W['fr'], W['v']), (4, 20, 80))
raises("VideoWriter('x.mp4', 'MPEG-4')", 'not written here')
raises("v = VideoWriter('z.avi'); open(v); writeVideo(v, zeros(4, 4)); writeVideo(v, zeros(5, 4)); close(v)", 'as the first was')
raises("v = VideoWriter('w.avi'); writeVideo(v, zeros(4))", 'Open the file first')
write('x.mp4', 'not a video')
raises("VideoReader('x.mp4')", 'reads AVI files')

# ---- the diary ---------------------------------------------------------------------------------------------------------------------
W, _ = run("diary('log.txt'); disp('one'); fprintf('two %d\\n', 2); diary off; disp('three'); diary on; disp('four'); diary off;")
log = open(path('log.txt')).read()
same('diary: output while it is on, added to the file', log, 'one\ntwo 2\nfour\n')

# ---- the profiler ------------------------------------------------------------------------------------------------------------------
write('work.m', 'function y = work(n)\n% WORK adds squares for the profiler\ny = 0;\nfor k = 1:n\n    y = y + helper(k);\nend\nend\n\nfunction r = helper(k)\nr = k^2;\nend\n')
W, out = run("profile on; s = work(50); s = work(10); profile off; p = profile('info'); ft = p.FunctionTable; names = {ft.FunctionName}; calls = [ft.NumCalls]; "
             "el = ft(1).ExecutedLines; st = profile('status'); ps = st.ProfilerStatus; tot = [ft.TotalTime]; self = [ft.SelfTime];\nprofile viewer")
same('profile info: the functions and their calls', ([text(x) for x in W['names'].a.reshape(-1)], a(W['calls']).tolist()), (['work', 'work>helper'], [[2.0, 60.0]]))
el = a(W['el'])
same('each line run: how many times (the loop head once more each call)', {int(r[0]): int(r[1]) for r in el}, {3: 2, 4: 62, 5: 60})
C("total time takes in what the function calls; status 'off'", a(W['tot'])[0, 0] >= a(W['self'])[0, 0] > 0 and text(W['ps']) == 'off', (W['tot'], W['self']))
C('profile viewer lists the functions and their slowest lines', 'work>helper' in out and 'Calls' in out and 'line 5' in out and 'y = y + helper(k);' in out, out)
W, _ = run("profile on; s = work(5); profile off; profile resume; s = work(5); profile off; p = profile('info'); c = [p.FunctionTable.NumCalls]; profile clear; q = profile('info'); e = numel(q.FunctionTable);")
same('profile resume adds on; profile clear empties it', (a(W['c']).tolist(), W['e']), ([[2.0, 10.0]], 0.0))

# ---- breakpoints, dbstack -------------------------------------------------------------------------------------------------------------
saved = R.DEBUGGER
R.DEBUGGER = WA.Debugger()
try:
    W, out = run("dbstop in work at 6\ndbstop in work at 2\ndbstop in work\ndbstop if error\ndbstatus\ns = dbstatus; l = s(1).line; f = s(1).file; c = s(2).cond;")
    same('dbstop: a line with no statement moves to the next one that has one; dbstop in file stops at the first', a(W['l']).tolist(), [[3.0, 10.0]])
    same('dbstatus shows them and the stop at errors', ('Breakpoints for' in out and 'are on lines 3 and 10.' in out and 'Stop if error.' in out, text(W['c'])), (True, 'error'))
    same('the debugger holds them for the file', sorted(R.DEBUGGER.breakpoints.get(text(W['f']), set())), [3, 10])
    W, out = run("dbclear in work at 3\ns = dbstatus; l = s(1).line;\ndbclear all\nn = numel(dbstatus);")
    same('dbclear one line, then all (and the stop at errors)', (a(W['l']).tolist(), W['n'], R.DEBUGGER.stop_on_error), ([[10.0]], 0.0, False))
    raises('dbstop in nosuchfile at 3', 'is not a program file')
    raises('dbstop in work at 40', 'after its last statement')
finally:
    R.DEBUGGER = saved
write('outer.m', 'function s = outer()\ns = inner();\nend\n\nfunction s = inner()\ns = dbstack;\nend\n')
W, out = run("s = outer(); n = {s.name}; l = [s.line];\ndbstack")
same('dbstack: the functions running, the innermost first, with their lines', ([text(x) for x in W['n'].a.reshape(-1)], a(W['l']).tolist()), (['inner', 'outer'], [[6.0, 2.0]]))

# ---- the code checker ---------------------------------------------------------------------------------------------------------------
write('lint1.m', 'function [a, b] = other(x, y)\nq = 1;\na = x\nz = 2; disp(z)\nfor k = 1:3\n    w(k) = k;\nend\nb = w;\nv = 4\n')
write('clean.m', 'function y = clean(x)\n% CLEAN is a function the checker finds nothing in\ny = 2*x;\nend\n')
write('broken.m', 'x = (1 + 2;\n')
W, out = run("checkcode lint1\ninfo = checkcode('lint1', '-id'); ids = {info.id}; lines = [info.line]; c1 = info(1).column; "
             "s = checkcode('clean', '-string'); b = checkcode('broken'); bl = b.line; bm = b.message; m = mlint('clean'); nm = numel(m);")
same('checkcode: unused input y, a function named unlike its file, the unused value q and v, output not suppressed',
     sorted(zip([int(v) for v in a(W['lines']).reshape(-1)], [text(x) for x in W['ids'].a.reshape(-1)])),
     sorted([(1, 'FNDEF'), (1, 'INUSD'), (2, 'NASGU'), (3, 'NOPRT'), (9, 'NASGU'), (9, 'NOPRT')]))
C('the messages are shown with their lines and columns', "L 1 (C 28): Input argument 'y' might be unused." in out and "L 2 (C 1): The value assigned to variable 'q' might be unused." in out, out)
same('a clean file: nothing; a syntax error: one message at its line', (text(W['s']), W['bl'], 'Parse error' in text(W['bm']), W['nm']), ('', 1.0, True, 0.0))
write('noout.m', 'function [p, q] = noout()\np = 1;\nend\n')
W, _ = run("i = checkcode('noout'); m = i(1).message;")
same('an output never set', text(W['m']), "Output argument 'q' might not be set.")

# ---- clipboard, lookfor, datetick -------------------------------------------------------------------------------------------------------
W, _ = run("clipboard('copy', [1 2; 3 4]); a = clipboard('paste'); clipboard('copy', 'some text'); b = clipboard('paste');")
same('clipboard: numbers as mat2str writes them, text as it is', (text(W['a']), text(W['b'])), ('[1 2;3 4]', 'some text'))
W, out = run("lookfor squares\nn = lookfor('butterworth');")
C('lookfor: the first lines of help and of program files on the path', 'adds squares for the profiler' in out and 'polyfit' in out, out)
same('lookfor with an output gives the names', [text(x) for x in W['n'].a.reshape(-1)], ['butter', 'buttord'])
W, _ = run("close all; plot(datenum(2024,1,1):datenum(2024,6,30), 1:182); datetick('x'); l = xticklabels; t = xticks; lim = xlim; "
           "figure; plot(datenum(2010,1,1):100:datenum(2020,1,1), 1:37); datetick; l2 = xticklabels; "
           "figure; plot(datenum(2024,3,5) + (0:0.01:0.5), 1:51); datetick('x', 'HH:MM PM', 'keeplimits'); l3 = xticklabels; close all")
same('datetick over half a year: the months', [text(x) for x in W['l'].a.reshape(-1)], ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'])
near('ticks on the first of each month', W['t'], [[739252, 739283, 739312, 739343, 739373, 739404]])
same('over ten years: the years; with a format of your own', ([text(x) for x in W['l2'].a.reshape(-1)][:3], text(W['l3'].a.reshape(-1)[0])), (['2010', '2012', '2014'], '12:00 AM'))

sys.exit(C.done())
