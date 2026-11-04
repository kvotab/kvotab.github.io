"""Odds and ends, run natively (CPython with numpy and scipy): mink and
maxk, clip, rmoutliers, isuniform, resize and its kin, cbrt, interpft (an
interpolated sine against the sine), the table functions (groupcounts,
grouptransform, groupfilter, pivot, topkrows, lag), patterns in the text
functions, symmlq and bicgstabl against numpy.linalg.solve, futures,
memoize, timeit and preferences, import options, XML documents, bwmorph
and bwboundaries, and the language's multiple assignment to the fields of
a struct array.

    python3 test_more.py          (from any folder)
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
TMP = tempfile.mkdtemp(prefix='pylab-more-')
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


def text(v):
    from plab.values import py_str
    return v.str() if isinstance(v, Char) else py_str(v)


def texts(v):
    return [text(x) for x in v.a.reshape(-1, order='F')]


def write(name, body):
    with open(os.path.join(TMP, name), 'w') as f:
        f.write(body)


# ---- the language: [s.f] = ... and arrayfun's structs --------------------------------------------------------------------------
W, _ = run("s = struct('a', {1, 2, 3}); [s.b] = deal('x'); b = {s.b}; [s.a] = deal(10, 20, 30); a1 = [s.a]; [s(2:3).a] = deal(7, 8); a2 = [s.a]; "
           "c = {4, 5, 6}; [s.a] = c{:}; a3 = [s.a]; [u.v] = deal(5); uv = u.v; r = arrayfun(@(k) struct('v', k^2), 1:3); rv = [r.v]; rs = size(r);")
same('[s.b] = deal(x): a field new to a struct array, a value for each element', texts(W['b']), ['x', 'x', 'x'])
near('[s.a] = deal(...), [s(2:3).a] = ..., [s.a] = c{:}', (W['a1'], W['a2'], W['a3'], W['uv']), ([10, 20, 30], [10, 7, 8], [4, 5, 6], 5))
near('arrayfun gives a struct array when each call gives a struct', (W['rv'], W['rs']), ([1, 4, 9], [1, 3]))

# ---- data functions --------------------------------------------------------------------------------------------------------------
W, _ = run("[b, i] = mink([5 1 NaN 3 2], 2); mx = maxk([1 7; 9 2; 4 8], 2); ma = maxk([-9 3 2], 1, 'ComparisonMethod', 'abs'); m2 = mink([4 1; 3 2], 1, 2); "
           "cl = clip([-2 0.5 NaN 7], 0, 1); ci = clip(int8([-100 5 100]), -10, 10); af = [allfinite([1 Inf]) allfinite(1:3) anynan([1 NaN]) anynan(1:3)]; "
           "[tf, st] = isuniform(0:0.1:1); [tf2, st2] = isuniform([1 2 4]); c3 = cbrt([-8 27 2]);")
near('mink and maxk: smallest (largest) first, NaN last; by absolute value; along rows', (W['b'], W['i'], W['mx'], W['ma'], W['m2']),
     ([1, 2], [2, 5], [[9, 8], [4, 7]], -9, [[1], [2]]))
near('clip (NaN kept, integers saturated); allfinite, anynan', (W['cl'], W['ci'], W['af']), ([0, 0.5, np.nan, 1], [-10, 5, 10], [0, 1, 1, 0]))
near('isuniform with its step; cbrt', (W['tf'], W['st'], W['tf2'], W['st2'], W['c3']), (1, 0.1, 0, np.nan, [-2, 3, 2 ** (1 / 3)]), 1e-12)
W, _ = run("x = sin(2*pi*(0:15)/16); y = interpft(x, 64); z = interpft([1 2 3 4 5 6]', 3); [B, rm] = rmoutliers([1 2 3 2 100 3]'); "
           "M = [1 2; 2 3; 50 4; 3 3; 2 2; 3 1]; RM = rmoutliers(M); r1 = resize(1:5, 3); r2 = resize(1:3, 5); r3 = resize([1 2; 3 4], [3 3]); "
           "p1 = paddata([1 2 3], 6, 'Pattern', 'circular'); p2 = paddata([1 2], 4, 'Side', 'leading', 'FillValue', 9); p3 = paddata([1 2 3], 2); t1 = trimdata(1:6, 4, 'Side', 'both');")
near('interpft: a sine sampled 16 times, interpolated to 64 points, is the sine at them', W['y'], np.sin(2 * np.pi * np.arange(64) / 64).reshape(1, -1), 1e-12)
near('interpft down to fewer points: every second of the doubled', W['z'], [[1], [3], [5]], 1e-12)
near("rmoutliers: the outlier taken out (isoutlier's median rule); the row of a matrix with one", (W['B'], W['rm'], np.shape(W['RM'])), ([[1], [2], [3], [2], [3]], [[0], [0], [0], [0], [1], [0]], [5, 2]))
near('resize cuts and pads (zeros after); a matrix in both dimensions', (W['r1'], W['r2'], W['r3']), ([1, 2, 3], [1, 2, 3, 0, 0], [[1, 2, 0], [3, 4, 0], [0, 0, 0]]))
near("paddata 'circular', 'leading' with a fill value, never cutting; trimdata from both sides", (W['p1'], W['p2'], W['p3'], W['t1']), ([1, 2, 3, 1, 2, 3], [9, 9, 1, 2], [1, 2, 3], [2, 3, 4, 5]))

# ---- tables ------------------------------------------------------------------------------------------------------------------------
W, _ = run("T = table([1;1;2;2;2], {'a';'b';'a';'a';'b'}, [10;20;30;40;50], 'VariableNames', {'g', 'k', 'v'}); G = groupcounts(T, 'g'); gc = G.GroupCount; gp = G.Percent; "
           "[c, gg, pp] = groupcounts([3 1 3 3]'); X = grouptransform(T, 'g', 'meancenter', 'v'); xv = X.v; Z = grouptransform(T, 'g', 'zscore', 'v', 'ReplaceValues', false); zn = Z.Properties.VariableNames; "
           "F = groupfilter(T, 'g', @(x) numel(x) > 2); fh = height(F); F2 = groupfilter(T, 'g', @(x) x > 15, 'v'); fv = F2.v; "
           "P = pivot(T, 'Columns', 'k', 'Rows', 'g'); pa = P.a; pb = P.b; pn = P.Properties.VariableNames; P2 = pivot(T, 'Columns', 'k', 'Rows', 'g', 'DataVariable', 'v', 'Method', 'mean'); p2a = P2.a; "
           "P3 = pivot(T, 'Columns', 'k', 'DataVariable', 'v'); p3 = [P3.a P3.b]; "
           "[top, ti] = topkrows([3 1; 5 2; 4 9; 5 0], 2); tt = topkrows(T, 2, 'v'); ttv = tt.v; ta = topkrows([3 1; 5 2; 4 9], 2, 2, 'ascend'); "
           "TT = timetable(datetime(2024,1,1:4)', [1;2;3;4]); L = lag(TT); l1 = L.Var1; L2 = lag(TT, -2); l2 = L2.Var1;")
near('groupcounts of a table and of an array', (W['gc'], W['gp'], W['c'], W['gg'], W['pp']), ([[2], [3]], [[40], [60]], [[1], [3]], [[1], [3]], [[25], [75]]))
near("grouptransform 'meancenter' in place; 'zscore' as a new variable", W['xv'], [[-5], [5], [-10], [0], [10]])
same('the new variable is named after the method', texts(W['zn']), ['g', 'k', 'v', 'zscore_v'])
near('groupfilter: groups by a scalar test, rows by a vector one', (W['fh'], W['fv']), (3, [[20], [30], [40], [50]]))
near('pivot: counts by row and column groups; means of a data variable; sums without Rows', (W['pa'], W['pb'], W['p2a'], W['p3']), ([[1], [2]], [[1], [1]], [[10], [35]], [[80, 70]]))
same('pivot names the columns by their groups', texts(W['pn']), ['g', 'a', 'b'])
near('topkrows: largest first by the first column, ties by the next; a table by a variable; ascending by column 2', (W['top'], W['ti'], W['ttv'], W['ta']),
     ([[5, 2], [5, 0]], [[2], [4]], [[50], [40]], [[3, 1], [5, 2]]))
near('lag: later by one, NaN first; earlier by two', (W['l1'], W['l2']), ([[np.nan], [1], [2], [3]], [[3], [4], [np.nan], [np.nan]]))

# ---- patterns ---------------------------------------------------------------------------------------------------------------------
W, out = run('p = digitsPattern(3) + "-" + digitsPattern(4); c = contains(["call 555-1234", "none"], p); e = extract("tel 555-1234 or 555-9876", p); '
             "d = extract('a1b22c333', digitsPattern); sw = [startsWith(\"abc123\", lettersPattern) endsWith(\"abc123\", digitsPattern(2)) startsWith(\"1abc\", lettersPattern)]; "
             'm = matches(["12", "1a", ""], digitsPattern); n = count("a1b22c333", digitsPattern); r = replace("x1y22", digitsPattern, "#"); er = erase("a  b   c", whitespacePattern); '
             'sp = split("a1b22c", digitsPattern); eb = extractBefore("key=value", "=" | ":"); ea = extractAfter("key:value", "=" | ":"); '
             'w = extract("start-mid-end-end", "start" + wildcardPattern + "end"); q = matches(["cat", "cats", "catss"], "cat" + optionalPattern("s")); '
             'ci = contains("Hello", caseInsensitivePattern("hello")); cs = contains("Hello", "hello"); '
             'wb = extract("one two three", letterBoundary("start") + lettersPattern(3) + letterBoundary("end")); '
             'rx = extract("pi 3.14 e 2.72", regexpPattern(\'\\d+\\.\\d+\')); ia = insertAfter("a1b2", digitsPattern, "!"); '
             'sf = strfind("a1b22", digitsPattern); am = extract("aaaa", asManyOfPattern("a", 1, 3)); af = extract("aaaa", asFewOfPattern("a", 1, 3)); '
             'cl = extract("hello world", characterListPattern("aeiou")); ex = extract("x1 y2", wildcardPattern(1, \'Except\', " ") + digitsPattern(1)); '
             'lb = extract("$5 and 10", lookBehindBoundary("$") + digitsPattern); la = extract("10kg 20m", digitsPattern + lookAheadBoundary("kg")); '
             'eb2 = extractBetween("<a><b>", "<", ">"); arr = contains(["ab", "cd", "ef"], [characterListPattern("a") "d"]);\np')
same('a pattern joined with + is shown as written', 'digitsPattern(3) + "-" + digitsPattern(4)' in out, True)
near('contains and startsWith/endsWith with patterns', (W['c'], W['sw']), ([1, 0], [1, 1, 0]))
same('extract: every match, a column', ([str(x) for x in W['e'].a.reshape(-1)], texts(W['d'])), (['555-1234', '555-9876'], ['1', '22', '333']))
near('matches the whole text; count non-overlapping matches', (W['m'], W['n']), ([1, 0, 0], 3))
same('replace, erase and split by a pattern', (text(W['r']), text(W['er']), [str(x) for x in W['sp'].a.reshape(-1)]), ('x#y#', 'abc', ['a', 'b', 'c']))
same('"=" | ":" is a pattern of alternatives; extractBefore and extractAfter take it', (text(W['eb']), text(W['ea'])), ('key', 'value'))
same('wildcardPattern takes as little as will do; optionalPattern', ([str(x) for x in W['w'].a.reshape(-1)], a(W['q']).tolist()), (['start-mid-end'], [[1.0, 1.0, 0.0]]))
same('caseInsensitivePattern; letter boundaries keep whole words of three letters', (bool(W['ci']), bool(W['cs']), [str(x) for x in W['wb'].a.reshape(-1)]), (True, False, ['one', 'two']))
same('regexpPattern, insertAfter, strfind with a pattern', ([str(x) for x in W['rx'].a.reshape(-1)], text(W['ia']), a(W['sf']).tolist()), (['3.14', '2.72'], 'a1!b2!', [[2.0, 4.0]]))
same('asManyOfPattern greedy, asFewOfPattern lazy; characterListPattern; wildcard with Except',
     ([str(x) for x in W['am'].a.reshape(-1)], [str(x) for x in W['af'].a.reshape(-1)], [str(x) for x in W['cl'].a.reshape(-1)], [str(x) for x in W['ex'].a.reshape(-1)]),
     (['aaa', 'a'], ['a', 'a', 'a', 'a'], ['e', 'o', 'o'], ['x1', 'y2']))
same('look-behind and look-ahead boundaries take nothing themselves', ([str(x) for x in W['lb'].a.reshape(-1)], [str(x) for x in W['la'].a.reshape(-1)]), (['5'], ['10']))
same('an array of patterns: any of them', a(W['arr']).tolist(), [[1.0, 1.0, 0.0]])
raises('lookBehindBoundary(digitsPattern)', 'fixed length')

# ---- symmlq and bicgstabl ---------------------------------------------------------------------------------------------------------
rng = np.random.default_rng(4)
n = 30
Q = np.linalg.qr(rng.standard_normal((n, n)))[0]
A_ind = Q @ np.diag(np.concatenate([np.linspace(-6, -1, 10), np.linspace(1, 9, 20)])) @ Q.T
A_ns = rng.standard_normal((n, n)) + 8 * np.eye(n)
b = rng.standard_normal(n)
np.savetxt(os.path.join(TMP, 'aind.txt'), A_ind, fmt='%.17g')
np.savetxt(os.path.join(TMP, 'ans.txt'), A_ns, fmt='%.17g')
np.savetxt(os.path.join(TMP, 'b.txt'), b, fmt='%.17g')
W, _ = run("A = load('aind.txt'); B = load('ans.txt'); b = load('b.txt'); [x, fl, rr, it, rv] = symmlq(A, b, 1e-10, 200); "
           "[y, fy] = bicgstabl(B, b, 1e-10, 100); [z, fz] = symmlq(A, b, 1e-10, 200, diag(abs(diag(A)) + 1)); [w, fw] = bicgstabl(B, b, 1e-10, 100, diag(diag(B))); "
           "S = gallery('poisson', 6); bs = ones(36, 1); [xs, fs] = symmlq(S, bs, 1e-12, 100); f3 = symmlq(@(v) A*v, b, 1e-10, 200); [~, f4] = symmlq(A, b, 1e-10, 3);")
near('symmlq on a symmetric indefinite matrix: numpy.linalg.solve, flag 0', (W['x'], W['fl']), (np.linalg.solve(A_ind, b).reshape(-1, 1), 0), 1e-8)
near('bicgstabl on a nonsymmetric matrix', (W['y'], W['fy']), (np.linalg.solve(A_ns, b).reshape(-1, 1), 0), 1e-8)
near('with preconditioners: the same solutions', (W['z'], W['fz'], W['w'], W['fw']), (np.linalg.solve(A_ind, b).reshape(-1, 1), 0, np.linalg.solve(A_ns, b).reshape(-1, 1), 0), 1e-8)
C('symmlq on a sparse Poisson matrix and with a function handle; flag 1 when maxit is too few', W['fs'] == 0 and np.allclose(a(W['f3']).reshape(-1), np.linalg.solve(A_ind, b), atol=1e-8) and W['f4'] == 1,
  (W['fs'], W['f4']))
C('resvec starts at the first residual and relres meets the tolerance', abs(a(W['rv'])[0, 0] - np.linalg.norm(b)) < 1e-9 and W['rr'] <= 1e-10, (W['rr'],))

# ---- futures, memoize, timeit, preferences --------------------------------------------------------------------------------------
W, _ = run("f = parfeval(@max, 2, [3 9 4]); [m, i] = fetchOutputs(f); st = f.State; for k = 1:3, F(k) = parfeval(@(x) x^2, 1, k); end; "
           "[idx, v] = fetchNext(F); all3 = fetchOutputs(F); G = afterEach(F, @(x) x + 1, 1); g = fetchOutputs(G); A = afterAll(F, @(x) sum(x), 1); s = fetchOutputs(A); "
           "e = parfeval(@() error('my:id', 'boom'), 0); try, fetchOutputs(e); msg = ''; catch me, msg = me.message; end; U = fetchOutputs(F, 'UniformOutput', false); uc = class(U); "
           "ok = wait(F); bp = class(backgroundPool); cf = class(f);")
near('parfeval: the outputs fetched; futures from a loop; fetchNext first', (W['m'], W['i'], W['idx'], W['v'], W['all3']), (9, 2, 1, 1, [[1], [4], [9]]))
near('afterEach and afterAll run on the outputs', (W['g'], W['s']), ([[2], [5], [10]], 14))
same("a future's State; an error in it raised by fetchOutputs; cells when not uniform; the classes",
     (text(W['st']), 'boom' in text(W['msg']), text(W['uc']), bool(W['ok']), text(W['bp']), text(W['cf'])),
     ('finished', True, 'cell', True, 'parallel.BackgroundPool', 'parallel.FevalFuture'))
W, _ = run("calls = 0; mf = memoize(@(x) x^3); a1 = mf(2); a2 = mf(2); a3 = mf(3); s = stats(mf); h = s.Cache.TotalHits; mi = s.Cache.TotalMisses; "
           "mf.CacheSize = 1; cs = mf.CacheSize; a4 = mf(2); s2 = stats(mf); cl = class(mf); m1 = memoize(@sin); m2 = memoize(@sin); same = m1 == m2; clearCache(mf); t = timeit(@() sum(rand(50)));")
near('memoize: results kept and found again; misses for new inputs', (W['a1'], W['a2'], W['a3'], W['h'], W['mi']), (8, 8, 27, 1, 2))
near('CacheSize 1 keeps only the last', (W['cs'], W['a4']), (1, 8))
same('the class; a named function gives the same memoized function; timeit gives a positive time', (text(W['cl']), bool(W['same']), W['t'] > 0), ('matlab.lang.MemoizedFunction', True, True))
W, _ = run("setpref('tool', 'size', 5); setpref('tool', {'a', 'b'}, {1, 'x'}); g = getpref('tool', 'size'); gb = getpref('tool', 'b'); d = getpref('tool', 'other', 7); dd = getpref('tool', 'other'); "
           "i1 = ispref('tool', 'size'); i2 = ispref('tool', 'none'); i3 = ispref('tool'); S = getpref('tool'); fn = fieldnames(S); rmpref('tool', 'a'); i4 = ispref('tool', 'a'); rmpref('tool'); i5 = ispref('tool');")
same('setpref, getpref (a default set when there is none), ispref, rmpref', (W['g'], text(W['gb']), W['d'], W['dd'], bool(W['i1']), bool(W['i2']), bool(W['i3']), sorted(texts(W['fn'])), bool(W['i4']), bool(W['i5'])),
     (5.0, 'x', 7.0, 7.0, True, False, True, ['a', 'b', 'other', 'size'], False, False))
C('preferences are kept in a file of the home folder', os.path.isfile(os.path.join(TMP, '.pylab-prefs.json')), os.listdir(TMP))
raises("addpref('tool2', 'k', 1); addpref('tool2', 'k', 2)", 'is there already')

# ---- import options ---------------------------------------------------------------------------------------------------------------
write('p.csv', 'name,age,city,day\nann,31,Lund,2024-01-05\nbo,42,Umea,2024-02-06\ncy,,Kiruna,2024-03-07\n')
write('h.txt', 'title line\nx;y\n1;2\n3;4\n5;6\n')
W, out = run("opts = detectImportOptions('p.csv'); vn = opts.VariableNames; vt = opts.VariableTypes; dl = opts.DataLines; "
             "opts = setvartype(opts, 'city', 'categorical'); opts = setvaropts(opts, 'age', 'FillValue', 0); opts.SelectedVariableNames = {'age', 'city'}; "
             "T = readtable('p.csv', opts); tn = T.Properties.VariableNames; age = T.age; cc = class(T.city); g = getvaropts(opts, 'age'); fv = g.FillValue; "
             "o2 = detectImportOptions('h.txt', 'NumHeaderLines', 1); dlm = o2.Delimiter; o2.DataLines = [2 3]; T2 = readtable('h.txt', o2); x2 = T2.x; "
             "[n, a] = readvars('p.csv'); M = readmatrix('h.txt', o2); C2 = readcell('p.csv', setvartype(detectImportOptions('p.csv'), 'age', 'double'));\nopts")
same('detectImportOptions: names and types as readtable reads them, data from line 2', (texts(W['vn']), texts(W['vt']), a(W['dl']).tolist()),
     (['name', 'age', 'city', 'day'], ['char', 'double', 'char', 'datetime'], [[2.0, np.inf]]))
same('read with options: the selected variables, typed, missing numbers filled', (texts(W['tn']), a(W['age']).reshape(-1).tolist(), text(W['cc']), W['fv']),
     (['age', 'city'], [31.0, 42.0, 0.0], 'categorical', 0.0))
same('the delimiter found; DataLines take rows 2 to 3 of the data', (texts(W['dlm']), a(W['x2']).reshape(-1).tolist()), ([';'], [1.0, 3.0]))
near('readvars gives the columns; readmatrix with options', (W['a'], W['M']), ([[31], [42], [np.nan]], [[1, 2], [3, 4]]))
C('the options are shown in their groups', 'Variable Import Properties' in out and 'SelectedVariableNames' in out and 'DataLines' in out, out)

# ---- XML documents ----------------------------------------------------------------------------------------------------------------
write('b.xml', '<?xml version="1.0"?>\n<lib name="home"><book id="1"><title>A</title></book><book id="2"><title>B</title><note>n</note></book></lib>\n')
W, _ = run("doc = xmlread('b.xml'); root = doc.getDocumentElement(); rn = char(root.getNodeName()); nm = char(root.getAttribute('name')); "
           "books = doc.getElementsByTagName('book'); nb = books.getLength(); b2 = books.item(1); id2 = char(b2.getAttribute('id')); "
           "t = char(b2.getElementsByTagName('title').item(0).getTextContent()); kids = b2.getChildNodes; nk = kids.getLength; "
           "at = root.getAttributes; na = at.getLength; an = char(at.item(0).getName); has = b2.hasAttribute('id'); "
           "d = com.mathworks.xml.XMLUtils.createDocument('cfg'); r = d.getDocumentElement; e = d.createElement('item'); e.setAttribute('k', 'v'); "
           "e.appendChild(d.createTextNode('hello')); r.appendChild(e); s = xmlwrite(d); xmlwrite('out.xml', d); back = xmlread('out.xml'); "
           "it = back.getElementsByTagName('item').item(0); k = char(it.getAttribute('k')); tx = char(it.getTextContent);")
same('xmlread: the root, its attribute, elements by name, item from 0, text, children, attributes',
     (text(W['rn']), text(W['nm']), W['nb'], text(W['id2']), text(W['t']), W['nk'], W['na'], text(W['an']), bool(W['has'])),
     ('lib', 'home', 2.0, '2', 'B', 2.0, 1.0, 'name', True))
same('a document made, written with xmlwrite and read back', ('<item k="v">hello</item>' in text(W['s']), text(W['k']), text(W['tx'])), (True, 'v', 'hello'))
write('bad.xml', '<a><b></a>')
raises("xmlread('bad.xml')", 'not well-formed')

# ---- bwmorph and bwboundaries ----------------------------------------------------------------------------------------------------------
BW = np.zeros((11, 11), bool)
BW[2:9, 2:9] = True
BW[5, 5] = False
np.savetxt(os.path.join(TMP, 'bw.txt'), BW.astype(float), fmt='%d')
W, _ = run("BW = logical(load('bw.txt')); sk = bwmorph(BW, 'skel', Inf); th1 = bwmorph(BW, 'thin', 1); rem = bwmorph(BW, 'remove'); fi = bwmorph(BW, 'fill'); "
           "cl = bwmorph([0 0 0; 0 1 0; 0 0 0], 'clean'); dl = bwmorph(BW, 'dilate'); er = bwmorph(BW, 'erode'); mj = bwmorph(logical([1 1 1; 1 0 1; 0 0 0]), 'majority'); "
           "L = false(7); L(2:6, 4) = true; ep = bwmorph(L, 'endpoints'); sp = bwmorph(L, 'spur'); sh = bwmorph(L, 'shrink', Inf); "
           "[B, Lab, N, A] = bwboundaries(BW); nb = numel(B); B1 = B{1}; B2 = B{2}; Af = full(A); nh = numel(bwboundaries(BW, 'noholes'));")
sq = np.ones((3, 3), bool)
P = np.pad(BW, 1)
interior = BW & P[:-2, 1:-1] & P[2:, 1:-1] & P[1:-1, :-2] & P[1:-1, 2:]
filled = BW.copy()
filled[5, 5] = True
near("bwmorph 'remove' leaves the pixels with a 4-neighbour outside; 'fill' fills the one-pixel hole", (W['rem'], W['fi']), (BW & ~interior, filled))
near("'clean' takes a lone pixel; 'dilate' and 'erode' with a 3-by-3 square", (W['cl'], W['dl'], W['er']),
     (np.zeros((3, 3)), ndimage.binary_dilation(BW, sq), ndimage.binary_erosion(BW, sq, border_value=1)))
near("'majority': set when 5 of the 3-by-3 are (zeros beyond the edge)", W['mj'], [[0, 1, 0], [0, 1, 0], [0, 0, 0]])
sk = a(W['sk']).astype(bool)
C("'skel': thinner than the shape, inside it, still one piece around the hole", sk.sum() < BW.sum() and not (sk & ~BW).any() and ndimage.label(sk, sq)[1] == 1 and sk.sum() > 4, sk.sum())
near("'endpoints' of a line; 'spur' takes them; 'shrink' leaves a point", (a(W['ep']).sum(), a(W['sp']).sum(), a(W['sh']).sum()), (2, 3, 1))
same('bwboundaries: an object and its hole, nested', (W['N'], W['nb'], a(W['Af']).tolist()), (1.0, 2.0, [[0.0, 0.0], [1.0, 0.0]]))
B1 = a(W['B1']).astype(int) - 1
perimeter = np.zeros_like(BW)
perimeter[2:9, 2:9] = True
perimeter[3:8, 3:8] = False
C("the object's boundary: closed, clockwise, the outer boundary pixels and only them, steps of one pixel",
  tuple(B1[0]) == tuple(B1[-1]) and set(map(tuple, B1)) == set(map(tuple, np.argwhere(perimeter)))
  and np.abs(np.diff(B1, axis=0)).max() == 1 and 0.5 * np.sum(B1[:-1, 1] * -B1[1:, 0] - B1[1:, 1] * -B1[:-1, 0]) < 0, B1[:5].tolist())
near('the hole traced as its own pixel; noholes leaves it out', (a(W['B2'])[0], W['nh']), ([6, 6], 1))

# isuniform: a scalar or an empty array is not uniform; a single vector's step is single
W, _ = run("[t1, s1] = isuniform(5); [t2, s2] = isuniform([]); [t3, s3] = isuniform(single(10:-1.5:1)); [t4, s4] = isuniform(single([1 2 4]));")
near('isuniform of a scalar and of an empty array: false, step NaN', (W['t1'], W['s1'], W['t2'], W['s2']), (0, np.nan, 0, np.nan))
same('isuniform of single: uniform, its step single', (bool(W['t3']), np.asarray(W['s3']).dtype.name, float(np.asarray(W['s3']).reshape(-1)[0]), np.asarray(W['s4']).dtype.name),
     (True, 'float32', -1.5, 'float32'))

sys.exit(C.done())
