"""Functions added to PyLAB from the language's set, run natively (CPython
with numpy and scipy): argument checking (the mustBe validators,
inputParser), missing data, outliers and smoothing, groups, JSON, arrays
and cells (bsxfun, repelem, mat2cell, celldisp), coordinates, text, and the
linear algebra, geometry, files and plots added with them. The expected
values are worked out here by hand, from identities, or with NumPy and
SciPy.

    python3 test_added.py          (from any folder)
"""
import asyncio
import json
import math
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char, Cell  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-added-')


def run(code):
    R.BASE.clear()
    R.BASE.gnames.clear()
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


def v(x):
    if isinstance(x, (bool, float, int, complex)):
        return np.array([x])
    return np.asarray(x).reshape(-1, order='F')


def near(label, got, want, tol=1e-9):
    g = np.concatenate([v(x) for x in got]) if isinstance(got, tuple) else v(got)
    w = np.asarray(want).reshape(-1)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {g.tolist()}, want {w.tolist()}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def text(x):
    return x.str() if isinstance(x, Char) else x


def size(x):
    return list(np.shape(x.a if isinstance(x, (Char, Cell)) else x)) if not isinstance(x, (float, bool, int, complex)) else [1, 1]


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = text(W['e'])
    return C(f'refused: {code}', words in msg and 'Error:' not in msg and 'Traceback' not in msg, msg)


def write(name, text):
    with open(os.path.join(TMP, name), 'w') as f:
        f.write(text)


# ---- the mustBe validators ------------------------------------------------------------------------------------------------
for code, words in (('mustBePositive([1 0])', 'positive'), ('mustBeNonnegative(-1)', 'nonnegative'), ('mustBeInteger(1.5)', 'integer'),
                    ('mustBeInteger(Inf)', 'integer'), ("mustBeNumeric('a')", 'numeric'), ('mustBeFinite([1 NaN])', 'finite'),
                    ('mustBeNonempty([])', 'empty'), ('mustBeReal(1i)', 'real'), ('mustBeGreaterThan(2, 2)', 'greater than 2'),
                    ('mustBeLessThanOrEqual(3, 2)', 'less than or equal to 2'), ("mustBeInRange(4, 1, 4, 'exclude-upper')", 'less than 4'),
                    ("mustBeMember('c', {'a', 'b'})", 'member'), ('mustBeText(5)', 'character vector'), ("mustBeTextScalar({'a'})", 'string scalar'),
                    ('mustBeVector(ones(2))', 'vector'), ('mustBeScalarOrEmpty([1 2])', 'scalar or empty'), ("mustBeA(1, 'char')", "'char'"),
                    ('mustBeNonzero([1 0])', 'zero'), ("mustBeValidVariableName('1x')", 'variable name'), ("mustBeFile('no-such-file.txt')", 'do not exist'),
                    ('mustBeNumericOrLogical({})', 'numeric or logical'), ('mustBeNonNan(NaN)', 'NaN')):
    raises(code, words)
W, _ = run("""mustBePositive([1 2]); mustBeInteger(int8(3)); mustBeInRange(1, 1, 4); mustBeMember(2, [1 2 3]); mustBeText({'a', 'b'});
mustBeVector(zeros(1, 0)); mustBeA(int8(1), 'integer'); mustBeA(1, {'char', 'numeric'}); mustBeNumericOrLogical(true); ok = true;
try, mustBePositive(-1), catch e, id = e.identifier; end""")
same('validators that hold give no error; the identifier names the validator', (W.get('ok'), text(W['id'])), (True, 'MATLAB:validators:mustBePositive'))
W, _ = run("a = nargchk(1, 2, 3); b = nargchk(1, 2, 1); s = nargchk(2, 3, 1, 'struct'); n = namelengthmax;")
same('nargchk gives the message (or nothing); struct form; namelengthmax', (text(W['a']), text(W['b']), text(W['s'].get1('identifier')), W['n']),
     ('Too many input arguments.', '', 'MATLAB:nargchk:notEnoughInputs', 63.0))

# ---- inputParser ------------------------------------------------------------------------------------------------------------
write('boxsize.m', """function r = boxsize(w, varargin)
p = inputParser;
p.FunctionName = 'boxsize';
addRequired(p, 'width', @(x) isnumeric(x) && x > 0);
addOptional(p, 'height', 1, @isnumeric);
p.addParameter('Units', 'cm', @(s) any(strcmp(s, {'cm', 'm'})));
addParameter(p, 'Color', 'red');
p.parse(w, varargin{:});
r = p.Results;
r.used = p.UsingDefaults;
end
""")
W, _ = run("""a = boxsize(3); b = boxsize(3, 4, 'units', 'm'); c = boxsize(2, 'Col', 'blue'); f = fieldnames(a)';
s.Units = 'm'; d = boxsize(5, s);
try, boxsize(-1), catch e, m1 = e.message; end
try, boxsize(2, 'Units', 'km'), catch e, m2 = e.message; end
try, boxsize(2, 'Size', 3), catch e, m3 = e.message; end
try, boxsize(), catch e, m4 = e.message; end""")
A, B, Cc, D = W['a'], W['b'], W['c'], W['d']
same('inputParser: required, optional and parameters with defaults', (A.get1('width'), A.get1('height'), text(A.get1('Units')), text(A.get1('Color'))), (3.0, 1.0, 'cm', 'red'))
same('Results fields in alphabetical order (here with the added used)', [text(x) for x in W['f'].a.reshape(-1)], ['Color', 'height', 'Units', 'width', 'used'])
same('an optional value, a parameter in another case', (B.get1('height'), text(B.get1('Units'))), (4.0, 'm'))
same('a prefix picks a parameter; UsingDefaults lists the others', (text(Cc.get1('Color')), [text(x) for x in Cc.get1('used').a.reshape(-1)]), ('blue', ['height', 'Units']))
same('a struct stands for its name-value pairs', text(D.get1('Units')), 'm')
C('a check that fails names the input and the function', "The value of 'width' is invalid" in text(W['m1']) and 'isnumeric' in text(W['m1']), text(W['m1']))
C('a parameter value that fails its check', "'Units' is invalid" in text(W['m2']), text(W['m2']))
C('an unknown parameter', "'Size' is not a recognized parameter" in text(W['m3']), text(W['m3']))
C('a missing required input', 'Not enough input arguments' in text(W['m4']), text(W['m4']))
W, _ = run("p = inputParser; p.KeepUnmatched = true; addParameter(p, 'a', 1); parse(p, 'a', 5, 'zz', 2); r = p.Results; u = p.Unmatched; k = class(p); pn = p.Parameters;")
same('KeepUnmatched keeps unknown pairs in Unmatched', (W['r'].get1('a'), W['u'].get1('zz'), text(W['k']), [text(x) for x in W['pn'].a.reshape(-1)]), (5.0, 2.0, 'inputParser', ['a']))

# ---- missing data -----------------------------------------------------------------------------------------------------------
W, _ = run("""x = [NaN 2 NaN 4 NaN NaN 7 NaN];
a = fillmissing(x, 'linear'); b = fillmissing(x, 'previous'); c = fillmissing(x, 'nearest'); d = fillmissing(x, 'constant', 0);
e = fillmissing(x, 'linear', 'EndValues', 'none'); [f, tf] = fillmissing(x, 'movmean', 3); g = fillmissing(x, 'linear', 'MaxGap', 2);
h = fillmissing({'a', '', 'c'}, 'previous'); k = fillmissing([1 NaN; NaN 4; 5 6], 'linear', 2); m = fillmissing([1 NaN 3 NaN], 'next', 'EndValues', 0);""")
near("fillmissing 'linear' extrapolates past the ends", W['a'], [1, 2, 3, 4, 5, 6, 7, 8])
near("'previous' leaves what has nothing before it", W['b'], [math.nan, 2, 2, 4, 4, 4, 7, 7])
near("'nearest' (a tie to the earlier) and 'constant'", (W['c'], W['d']), [2, 2, 2, 4, 4, 7, 7, 7, 0, 2, 0, 4, 0, 0, 7, 0])
near("EndValues 'none' and MaxGap", (W['e'], W['g']), [math.nan, 2, 3, 4, 5, 6, 7, math.nan, math.nan, 2, 3, 4, math.nan, math.nan, 7, math.nan])
near("'movmean' over a window, with the filled entries marked", (W['f'], W['tf']), [2, 2, 3, 4, 4, 7, 7, 7, 1, 0, 1, 0, 1, 1, 0, 1])
same('text: empty entries filled', [text(x) for x in W['h'].a.reshape(-1)], ['a', 'a', 'c'])
near('along rows; an EndValues constant', (W['k'], W['m']), [1, 4, 5, 1, 4, 6, 1, 3, 3, 0])
W, _ = run("a = rmmissing([1 NaN 3]); [b, t] = rmmissing([1 2; NaN 4; 5 6]); c = rmmissing([1 NaN; 2 3], 2); d = rmmissing([1 NaN NaN; 1 2 NaN], 'MinNumMissing', 2); s = standardizeMissing([1 -99 3], -99);")
near('rmmissing: a vector, rows, columns, MinNumMissing', (W['a'], W['b'], W['t'], W['c'], W['d']), [1, 3, 1, 5, 2, 6, 0, 1, 0, 1, 2, 1, 2, math.nan])
near('standardizeMissing', W['s'], [1, math.nan, 3])

# ---- outliers and smoothing --------------------------------------------------------------------------------------------------
W, _ = run("""d = [2 3 2 3 2 50 3 2 -40 3];
[t1, L, U, Cc] = isoutlier(d); t2 = isoutlier(d, 'mean'); t3 = isoutlier(d, 'quartiles'); t4 = isoutlier(d, 'median', 'ThresholdFactor', 30);
t5 = isoutlier([1 2 3 2 1 2 30 2 1], 'grubbs'); t6 = isoutlier([2 3 2 3 2 50 3 2 -40 3 2 3], 'gesd');
b1 = filloutliers(d, 'center'); b2 = filloutliers(d, 'clip'); b3 = filloutliers(d, 'previous'); b4 = filloutliers(d, 0);""")
dd = np.array([2, 3, 2, 3, 2, 50, 3, 2, -40, 3.])
med = np.median(dd)
smad = 1.482602218505602 * np.median(np.abs(dd - med))
near("isoutlier 'median': 3 scaled MADs; L, U, C", (W['t1'], W['L'], W['U'], W['Cc']), [0, 0, 0, 0, 0, 1, 0, 0, 1, 0, med - 3 * smad, med + 3 * smad, med])
near("'mean' (none: the two pull the mean), 'quartiles', a larger ThresholdFactor", (W['t2'], W['t3'], W['t4']), [0] * 10 + [0, 0, 0, 0, 0, 1, 0, 0, 1, 0] + [0, 0, 0, 0, 0, 1, 0, 0, 1, 0])
near("'grubbs' and 'gesd'", (W['t5'], W['t6']), [0, 0, 0, 0, 0, 0, 1, 0, 0] + [0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0])
near("filloutliers: 'center', 'clip', 'previous', a number", (W['b1'], W['b2'], W['b3'], W['b4']),
     list(np.where([0, 0, 0, 0, 0, 1, 0, 0, 1, 0], med, dd)) + list(np.clip(dd, med - 3 * smad, med + 3 * smad)) + [2, 3, 2, 3, 2, 2, 3, 2, 2, 3] + [2, 3, 2, 3, 2, 0, 3, 2, 0, 3])
W, _ = run("a = smoothdata([1 2 10 4 5], 'movmean', 3); [b, w] = smoothdata(1:10); c = smoothdata([1 5 2 6 3 7 4 8], 'sgolay', 5); d = smoothdata([1 NaN 3 4], 'movmedian', 3); e = smoothdata([1 5 2 6 3 7], 'gaussian', 3);")
near("smoothdata 'movmean'; the default window and its size", (W['a'], W['b'], W['w']), [1.5, 13 / 3, 16 / 3, 19 / 3, 4.5, 1.5, 2, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9, 4])
from scipy.signal import savgol_filter  # noqa: E402
near("'sgolay' is a Savitzky-Golay filter (degree 2)", W['c'], savgol_filter(np.array([1, 5, 2, 6, 3, 7, 4, 8.]), 5, 2, mode='interp'))
near("NaN left out", W['d'], [1, 2, 3.5, 3.5])
yy = np.array([1, 5, 2, 6, 3, 7.])
wts = [np.exp(-0.5 * ((np.arange(max(0, j - 1), min(6, j + 2)) - j) / 0.6) ** 2) for j in range(6)]
near("'gaussian': weights of a normal curve, sd a fifth of the window", W['e'], [np.sum(w * yy[max(0, j - 1):min(6, j + 2)]) / w.sum() for j, w in enumerate(wts)])

# ---- groups and counts ------------------------------------------------------------------------------------------------------
W, _ = run("""[G, ID] = findgroups([3 1 3 2 NaN]'); [G2, A, B] = findgroups({'x'; 'y'; 'x'; 'y'}, [1; 1; 1; 2]);
m = splitapply(@mean, [1 2 3 4]', [1 2 1 2]'); [mx, mn] = splitapply(@(v) deal(max(v), min(v)), [5 1 7 3]', [1 1 2 2]);
cc = splitapply(@(v) {v'}, [1 2 3]', [1 2 1]); r = splitapply(@(a, b) sum(a .* b), [1 2 3]', [4 5 6]', [1 1 2]);
[N, xe, ye, bx, by] = histcounts2([1 2 2 3 NaN], [1 1 2 3 5], [2 2]); k = class(xe);""")
near('findgroups numbers the sorted values; NaN has no group', (W['G'], W['ID']), [3, 1, 3, 2, math.nan, 1, 2, 3])
same('combinations of two grouping variables', (v(W['G2']).tolist(), [text(x) for x in W['A'].a.reshape(-1)], v(W['B']).tolist()), ([1.0, 2.0, 1.0, 3.0], ['x', 'y', 'y'], [1.0, 1.0, 2.0]))
near('splitapply: one row per group; several outputs; two inputs', (W['m'], W['mx'], W['mn'], W['r']), [2, 3, 5, 7, 1, 3, 14, 18])
same('splitapply with a cell for values that are not scalars', [v(x).tolist() for x in W['cc'].a.reshape(-1)], [[1.0, 3.0], [2.0]])
near('histcounts2: counts in a grid, the bins of each pair (NaN in none)', (W['N'], W['bx'], W['by']), [1, 1, 0, 2, 1, 2, 2, 2, 0, 1, 1, 2, 2, 0])
same('the edges are doubles', text(W['k']), 'double')
raises("splitapply(@sum, [1 2 3]', [1 3 3]')", 'no members')

# ---- arrays, cells, coordinates ---------------------------------------------------------------------------------------------
W, _ = run("""a = bsxfun(@minus, [1 2 3; 4 5 6], [1 2 3]); b = bsxfun(@(x, y) x .* y, [1; 2], [3 4]);
c = repelem([1 2 3], [2 0 1]); d = repelem([1 2; 3 4], 2, 3); e = repelem('ab', 2); f = repelem({1, 'x'}, 1, 2); g = repelem(5, 3);
q = mat2cell(magic(4), [1 3], [2 2]); q22 = q{2, 2}; sq = size(q); r = mat2cell('abcdef', 1, [2 4]); sw = swapbytes(uint16(1)); sp = full(spfun(@exp, [0 1; 2 0])); spk = issparse(spfun(@exp, [0 1; 2 0]));""")
near('bsxfun expands singleton dimensions; any function of two inputs', (W['a'], W['b']), [0, 3, 0, 3, 0, 3, 3, 6, 4, 8])
near('repelem of a vector with counts; of a matrix down and across; a scalar gives a row', (W['c'], W['d'], W['g']), [1, 1, 3] + list(np.repeat(np.repeat([[1, 2], [3, 4]], 2, 0), 3, 1).reshape(-1, order='F')) + [5, 5, 5])
same('repelem of characters and of a cell', (text(W['e']), size(W['f'])), ('aabb', [1, 4]))
near('mat2cell: blocks of a matrix', (W['q22'], W['sq']), [10, 6, 15, 8, 12, 1, 2, 2])
same('mat2cell of characters', [text(x) for x in W['r'].a.reshape(-1)], ['ab', 'cdef'])
same('swapbytes: 1 as uint16 is 256 with its bytes swapped', int(np.asarray(W['sw']).reshape(-1)[0]), 256)
near('spfun applies the function to the nonzeros only, giving a sparse matrix', (W['sp'], W['spk']), [0, math.exp(2), math.e, 0, 1])
raises('mat2cell(ones(3), [1 1], 3)', 'must sum to each dimension')
raises('bsxfun(@plus, ones(2, 3), ones(3, 2))', 'Non-singleton dimensions')
_, o = run("Z = {1, 'ab', {2, 3}}; celldisp(Z)")
C('celldisp names each element by its index, cells inside cells too', all(s in o for s in ('Z{1} =', 'Z{2} =', 'Z{3}{1} =', 'Z{3}{2} =')), o)
W, _ = run("[t, r] = cart2pol([1 0], [1 2]); [x, y, z] = pol2cart(pi/2, 2, 5); [az, el, rr] = cart2sph(1, 1, sqrt(2)); [x2, y2, z2] = sph2cart(pi/4, pi/4, 2); k = class(cart2pol(single(1), 1));")
near('cart2pol and pol2cart', (W['t'], W['r'], W['x'], W['y'], W['z']), [math.pi / 4, math.pi / 2, math.sqrt(2), 2, 0, 2, 5], 1e-12)
near('cart2sph and sph2cart', (W['az'], W['el'], W['rr'], W['x2'], W['y2'], W['z2']), [math.pi / 4, math.pi / 4, 2, 1, 1, math.sqrt(2)], 1e-12)
same('single in, single out', text(W['k']), 'single')
W, _ = run("a = rms([3 4]); b = rms([1 NaN 3], 'omitnan'); c = rms([1 2; 3 4], 2); d = rms(magic(3), 'all');")
near('rms', (W['a'], W['b'], W['c'], W['d']), [math.sqrt(12.5), math.sqrt(5), math.sqrt(2.5), math.sqrt(12.5), math.sqrt(np.mean(np.arange(1, 10) ** 2))])

# ---- text and JSON ----------------------------------------------------------------------------------------------------------
W, _ = run("""a = replaceBetween('a [b] c [d]', '[', ']', 'X'); b = eraseBetween("hello world", 2, 4); c = replaceBetween('a [b] c', '[', ']', 'X', 'Boundaries', 'inclusive');
d = eraseBetween({'x(1)', 'y(22)'}, '(', ')'); [u, mod] = matlab.lang.makeUniqueStrings({'a', 'a', 'b', 'a'}); u2 = matlab.lang.makeUniqueStrings('b', {'b', 'b_1'});""")
same('replaceBetween and eraseBetween: markers kept unless inclusive; positions', (text(W['a']), str(W['b'].a.reshape(-1)[0]), text(W['c'])), ('a [X] c [X]', 'ho world', 'a X c'))
same('on a cell of texts', [text(x) for x in W['d'].a.reshape(-1)], ['x()', 'y()'])
same('makeUniqueStrings: repeats get _1, _2; names to avoid', ([text(x) for x in W['u'].a.reshape(-1)], v(W['mod']).tolist(), text(W['u2'])),
     (['a', 'a_1', 'b', 'a_2'], [False, True, False, True], 'b_2'))
W, _ = run("""s = jsondecode('{"name":"A","vals":[1,2,null],"m":[[1,2],[3,4]],"pts":[{"x":1,"y":2},{"x":3,"y":4}],"ok":[true,false],"mix":[1,"a"],"e":[],"1st":5}');
v = s.vals; m = s.m; p = [s.pts.x]; ok = s.ok; mix = s.mix; f = fieldnames(s);
j = jsonencode(struct('a', [1 2 3], 'b', 'text', 'c', [1 2; 3 4], 'd', NaN, 'e', true, 'f', {{1, 'x'}}));
j2 = jsonencode(pi); j3 = jsonencode(single([0.1 2.5])); j4 = jsonencode(struct('a', {1, 2})); j5 = jsonencode({}); j6 = jsonencode([]);
back = jsondecode(jsonencode(struct('k', [1 2; 3 4])));""")
near('jsondecode: numbers with null as NaN in a column; arrays of rows as a matrix', (W['v'], W['m']), [1, 2, math.nan, 1, 3, 2, 4])
same('objects in an array as a struct array; booleans as logical; mixed as a cell', (v(W['p']).tolist(), v(W['ok']).tolist(), size(W['mix'])), ([1.0, 3.0], [True, False], [2, 1]))
same('names made valid', [text(x) for x in W['f'].a.reshape(-1)][-1], 'x1st')
same('jsonencode of a struct of many kinds', text(W['j']), '{"a":[1,2,3],"b":"text","c":[[1,2],[3,4]],"d":null,"e":true,"f":[1,"x"]}')
same('numbers: shortest digits, singles as singles; struct arrays and empties', (text(W['j2']), text(W['j3']), text(W['j4']), text(W['j5']), text(W['j6'])),
     ('3.141592653589793', '[0.1,2.5]', '[{"a":1},{"a":2}]', '[]', '[]'))
near('a matrix goes there and back', W['back'].get1('k'), [1, 3, 2, 4])
raises("jsondecode('{bad')", 'Unable to parse')

# ---- linear algebra: structure, iterative solvers, updates, Schur forms ----------------------------------------------------
W, _ = run("""A = [4 1 0; 1 3 1; 0 1 2];
a = [issymmetric(A), issymmetric([1 2; 3 1]), issymmetric([0 1; -1 0], 'skew'), issymmetric([1 2+1e-12; 2 1], 1e-10), issymmetric(ones(2, 3))];
b = [ishermitian([1 1i; -1i 2]), ishermitian([1 1i; 1i 2]), istril(tril(magic(4))), istriu(magic(4)), isbanded(A, 1, 1), isbanded(A, 0, 1)];
[lo, up] = bandwidth([1 0 0; 2 3 0; 0 4 5]); bl = bandwidth(zeros(3), 'upper');""")
same('issymmetric: exactly, skew, within a tolerance, not square', v(W['a']).tolist(), [True, False, True, True, False])
same('ishermitian, istril, istriu, isbanded', v(W['b']).tolist(), [True, False, True, False, True, False])
near('bandwidth', (W['lo'], W['up'], W['bl']), [1, 0, 0])
A3 = np.array([[4, 1, 0], [1, 3, 1], [0, 1, 2.]])
b3 = np.array([1, 2, 3.])
xs = np.linalg.solve(A3, b3)
W, _ = run("""A = [4 1 0; 1 3 1; 0 1 2]; b = [1; 2; 3];
[x1, f1, r1, i1, rv] = pcg(A, b, 1e-12, 50); [x2, f2, r2, i2] = gmres(A, b, [], 1e-12, 10); [x3, f3] = bicgstab(A, b, 1e-12, 50);
[x4, f4] = minres(A, b, 1e-12, 50); [x5, f5] = pcg(@(v) A*v, b, 1e-12, 50); [x6, f6] = cgs(A, b, 1e-12, 50); [x7, f7] = tfqmr(A, b, 1e-12, 50);
[x8, f8] = bicg(@(v, t) A*v, b, 1e-12, 50); [x9, f9] = qmr(A, b, 1e-12, 50); [x10, f10] = pcg(A, b, 1e-12, 50, diag(diag(A)));
[x11, f11, r11] = pcg(A, b, 1e-12, 1); x12 = lsqr([1 0; 0 1; 1 1], [1; 2; 3.5]);""")
for k in ('x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7', 'x8', 'x9', 'x10'):
    near(f'{k}: the iterative solution of a 3-by-3 system', W[k], xs, 1e-9)
same('converged: flag 0 for each', [W[k] for k in ('f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10')], [0.0] * 10)
C('pcg: relres within the tolerance, three iterations, resvec from norm(b) down', W['r1'] < 1e-12 and W['i1'] == 3 and abs(v(W['rv'])[0] - np.linalg.norm(b3)) < 1e-12 and v(W['rv']).size == 4, (W['r1'], W['i1']))
same('gmres counts [outer inner]', v(W['i2']).tolist(), [1.0, 3.0])
same('one iteration is not enough: flag 1', (W['f11'], W['r11'] > 1e-6), (1.0, True))
near('lsqr: least squares', W['x12'], np.linalg.lstsq(np.array([[1, 0], [0, 1], [1, 1.]]), np.array([1, 2, 3.5]), rcond=None)[0], 1e-8)
W, _ = run("""A = [4 1 0; 1 3 1; 0 1 2]; R = chol(A);
R1 = cholupdate(R, [1; 0; 1]); d1 = norm(R1'*R1 - (A + [1; 0; 1]*[1 0 1])); [R2, p] = cholupdate(R, [3; 0; 0], '-');
M = magic(3); [Q, Rq] = qr(M); [Q1, R1q] = qrupdate(Q, Rq, [1; 2; 3], [1; 0; 0]); d2 = norm(Q1*R1q - (M + [1; 2; 3]*[1 0 0])); t2 = istriu(R1q);
[Q2, R2q] = qrinsert(Q, Rq, 2, [1; 1; 1]); d3 = norm(Q2*R2q - [M(:, 1) [1; 1; 1] M(:, 2:3)]);
[Q3, R3q] = qrdelete(Q, Rq, 1); d4 = norm(Q3*R3q - M(:, 2:3)); [Q4, R4q] = qrdelete(Q, Rq, 2, 'row'); d5 = norm(Q4*R4q - M([1 3], :));""")
C('cholupdate adds x*x\'', W['d1'] < 1e-12, W['d1'])
same('a downdate that is not positive definite: p = 1', W['p'], 1.0)
C('qrupdate, qrinsert and qrdelete (column and row) keep Q*R equal to the changed matrix', max(W['d2'], W['d3'], W['d4'], W['d5']) < 1e-12 and W['t2'], (W['d2'], W['d3'], W['d4'], W['d5']))
W, _ = run("""A = magic(3); B = [2 1 0; 1 3 1; 0 1 4];
[AA, BB, Q, Z, V, Wl] = qz(A, B); d1 = norm(Q*A*Z - AA) + norm(Q*B*Z - BB); t1 = istriu(AA) && istriu(BB); d2 = norm(A*V - B*V*diag(diag(AA)./diag(BB)));
[AAr, BBr] = qz(A, B, 'real'); r1 = isreal(AAr);
[U, T] = schur(magic(4)); [US, TS] = ordschur(U, T, logical([0 0 0 1])); e1 = ordeig(TS); d3 = norm(US*TS*US' - magic(4));
[US2, TS2] = ordschur(U, T, [1 3 2 4]); e2 = ordeig(TS2);
e3 = ordeig([1 2; -2 1]);
p1 = polyeig([2 0; 0 3], eye(2), eye(2)); [X, e4, s] = polyeig([1 2; 3 4], eye(2)); d4 = norm(([1 2; 3 4] + e4(2)*eye(2))*X(:, 2)); n4 = norm(X(:, 1));""")
C('qz: Q*A*Z = AA, Q*B*Z = BB, both triangular; V the eigenvectors', W['d1'] < 1e-12 and W['t1'] and W['d2'] < 1e-10, (W['d1'], W['d2']))
same("qz with 'real' stays real", W['r1'], True)
ev = np.linalg.eigvals(np.array([[16, 2, 3, 13], [5, 11, 10, 8], [9, 7, 6, 12], [4, 14, 15, 1.]]))
zero = ev[np.argmin(np.abs(ev))]
C('ordschur moves the selected eigenvalue first and keeps U*T*U\'', abs(v(W['e1'])[0] - zero) < 1e-9 and W['d3'] < 1e-12, (v(W['e1']), W['d3']))
near('cluster keys: largest key first', W['e2'], [zero.real, math.sqrt(80), -math.sqrt(80), 34], 1e-9)
near('ordeig of a 2-by-2 block: the pair, positive imaginary part first', W['e3'], [1 + 2j, 1 - 2j])
p1 = np.concatenate([np.roots([1, 1, 2]), np.roots([1, 1, 3])])
C('polyeig: the roots of each diagonal polynomial', np.allclose(np.sort_complex(v(W['p1'])), np.sort_complex(p1), atol=1e-12), v(W['p1']))
C('[X, e, s]: (A0 + e A1) x = 0 with unit x; s finite', W['d4'] < 1e-12 and abs(W['n4'] - 1) < 1e-12 and np.all(np.isfinite(v(W['s']))), (W['d4'], W['n4']))

# ---- geometry and interpolation objects ---------------------------------------------------------------------------------------
W, _ = run("""x = [0 1 0 1 0.5]; y = [0 0 1 1 0.5];
T = delaunay(x, y); st = size(T); [K, A] = convhull(x, y); K2 = convhull([0 1 2 2 0], [0 0 0 2 2], 'Simplify', false);
[Kv, Vol] = convhull([0 1 0 0 1], [0 0 1 0 1], [0 0 0 1 1]); T3 = delaunay([0 1 0 0], [0 0 1 0], [0 0 0 1]);
[V, Cc] = voronoin([x' y']); c5 = sort(Cc{5}); c1 = Cc{1};
t = tsearchn([x' y'], T, [0.5 0.1; 5 5]); [k, d] = dsearchn([x' y'], [0.9 0.9; 0.4 0.6]); k2 = dsearchn([x' y'], T, [3 3], -1);
r = rectint([0 0 2 2; 1 1 1 1], [1 1 2 2; 5 5 1 1]);""")
same('delaunay of a square and its centre: four triangles', v(W['st']).tolist(), [4.0, 3.0])
near('convhull: the corners counterclockwise, closed; the area', (W['K'], W['A']), [1, 2, 4, 3, 1, 1])
near("'Simplify', false keeps the points on the edges", W['K2'], [1, 2, 3, 4, 5, 1])
same('in 3-D: triangles of the hull, its volume (1/6 + 2/6); delaunay gives tetrahedra', (size(W['Kv'])[1], round(W['Vol'], 12), size(W['T3'])), (3, 0.5, [1, 4]))
same('voronoin: the centre cell is bounded; a corner cell holds the point at infinity (1)', (len(v(W['c5'])), 1.0 in v(W['c1'])), (4, True))
same('tsearchn: the triangle holding a point, NaN outside', (math.isnan(v(W['t'])[1]), math.isnan(v(W['t'])[0])), (True, False))
near('dsearchn: nearest points and distances; outval outside the hull', (W['k'], W['d'], W['k2']), [4, 5, math.sqrt(0.02), math.sqrt(0.02), -1])
near('rectint: overlap areas', W['r'], [1, 1, 0, 0])
W, _ = run("""[X, Y, Z] = meshgrid(1:3, 1:4, 1:2); V = X + 10*Y + 100*Z; q = interp3(X, Y, Z, V, [2.5 1], [3.5 2], [1.5 2]); q2 = interp3(V, 2, 3, 1.25);
F = griddedInterpolant({1:3, 1:4}, (1:3)' + 10*(1:4)); g1 = F(2.5, 3.5); g2 = F(4, 1); g3 = F({[1 2], [1 2]}); F.ExtrapolationMethod = 'none'; g4 = F(4, 1);
G = griddedInterpolant([1 2 3], [1 4 9], 'spline'); g5 = G([1.5 4]); H = griddedInterpolant([1 2 3], [1 4 9], 'previous'); g6 = H(2.5);
S = scatteredInterpolant([0 1 0 1]', [0 0 1 1]', [0 1 2 3]'); s1 = S(0.3, 0.6); s2 = S([2 2]); S.ExtrapolationMethod = 'nearest'; s3 = S(2, 2); S.Values = [1 1 1 1]'; s4 = S(0.5, 0.5);""")
near('interp3 in meshgrid layout, and on the grid 1:n', (W['q'], W['q2']), [2.5 + 35 + 150, 1 + 20 + 200, 2 + 30 + 125])
near('griddedInterpolant: inside, extrapolated linearly, on a grid of vectors', (W['g1'], W['g2'], W['g3']), [37.5, 14, 11, 12, 21, 22])
same("ExtrapolationMethod 'none' gives NaN", math.isnan(W['g4']), True)
near("a spline through three points is the parabola (2.25 and 16); 'previous'", (W['g5'], W['g6']), [2.25, 16, 4])
near('scatteredInterpolant: linear inside, the nearest plane outside; nearest; new values', (W['s1'], W['s2'], W['s3'], W['s4']), [0.3 + 2 * 0.6, 6, 3, 1])
W, _ = run("x = [0 1 0 1 0.5]; y = [0 0 1 1 0.5]; T = delaunay(x, y); figure; h1 = triplot(T, x, y); t1 = get(h1, 'Type'); figure; h2 = trisurf(T, x, y, x + y); t2 = get(h2, 'Type'); f2 = size(get(h2, 'Faces')); [az, el] = view; figure; h3 = trimesh(T, x, y, x + y); fc = get(h3, 'FaceColor'); close all")
same('triplot draws a line; trisurf a patch of the triangles, seen in 3-D; trimesh white faces', (text(W['t1']), text(W['t2']), v(W['f2']).tolist(), (W['az'], W['el']), v(W['fc']).tolist()),
     ('line', 'patch', [4.0, 3.0], (-37.5, 30.0), [1.0, 1.0, 1.0]))
W, _ = run("a = interp1([1 2 3], [1 4 9], [1.5 4], 'spline'); b = interp1([1 2], [1 4], 3, 'spline');")
near("interp1 'spline' through three points is the parabola, through two the line", (W['a'], W['b']), [2.25, 16, 7])

# ---- images, sound and the web -----------------------------------------------------------------------------------------------
W, _ = run("""A = uint8(cat(3, [255 0; 0 128], [0 255; 0 128], [0 0; 255 128]));
imwrite(A, 'rgb.png'); B = imread('rgb.png'); same1 = isequal(A, B); c = class(B);
imwrite([0 0.5; 1 0.25], 'g.png'); G = imread('g.png'); info = imfinfo('g.png');
imwrite(uint8([0 1; 2 1]), [1 0 0; 0 1 0; 0 0 1], 'ix.png'); [X, map] = imread('ix.png'); m3 = map(1:3, :);
imwrite(A, 'a.jpg', 'Quality', 95); J = imread('a.jpg'); sj = size(J);
imwrite(A, 'al.png', 'Alpha', [1 0.5; 0 1]); [P, ~, al] = imread('al.png');
imwrite(uint16([0 1000; 65535 7]), 'w.png'); H = imread('w.png'); kh = class(H);""")
same('imwrite and imread give back an RGB image', (W['same1'], text(W['c'])), (True, 'uint8'))
near('a gray image of doubles is scaled by 255 and rounded', W['G'], [0, 255, 128, 64])
same('imfinfo', (text(W['info'].get1('Format')), W['info'].get1('Width'), text(W['info'].get1('ColorType'))), ('png', 2.0, 'grayscale'))
near('an image with a palette: indices from 0 and the colormap', (W['X'], W['m3']), [0, 2, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 1])
same('JPEG with Quality; the alpha channel', (v(W['sj']).tolist(), v(W['al']).tolist()), ([2.0, 2.0, 3.0], [255, 0, 128, 255]))
same('16-bit PNG stays uint16', (text(W['kh']), v(W['H']).tolist()), ('uint16', [0, 65535, 1000, 7]))
W, _ = run("""y = [sin(2*pi*440*(0:99)'/8000), cos(2*pi*440*(0:99)'/8000)];
audiowrite('t.wav', y, 8000); [z, fs] = audioread('t.wav'); e = max(abs(z(:) - y(:))); ai = audioinfo('t.wav');
zn = audioread('t.wav', 'native'); cn = class(zn); z2 = audioread('t.wav', [11 20]); s2 = size(z2);
audiowrite('f.wav', y(:, 1), 8000, 'BitsPerSample', 32); zf = audioread('f.wav'); ef = max(abs(zf - y(:, 1)));""")
C('audiowrite (16-bit) and audioread: within a step of 1/32768', W['e'] <= 1 / 32768 and W['fs'] == 8000, W['e'])
same('audioinfo', (W['ai'].get1('NumChannels'), W['ai'].get1('TotalSamples'), W['ai'].get1('BitsPerSample')), (2.0, 100.0, 16.0))
same("'native' keeps int16; a range of samples", (text(W['cn']), v(W['s2']).tolist()), ('int16', [10.0, 2.0]))
C('32 bits per sample: floating point', W['ef'] < 1e-7, W['ef'])

import http.server  # noqa: E402
import threading  # noqa: E402


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith('/data.json'):
            body, ct = b'{"name":"probe","vals":[1,2,3],"q":"' + self.path.split('?')[-1].encode() + b'"}', 'application/json'
        elif self.path.startswith('/note.txt'):
            body, ct = 'plain text å'.encode('utf-8'), 'text/plain; charset=utf-8'
        else:
            body, ct = bytes([1, 2, 3, 250]), 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', ct)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        got = self.rfile.read(n)
        body = json.dumps({'type': self.headers.get('Content-Type'), 'body': got.decode()}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_srv = http.server.HTTPServer(('127.0.0.1', 0), _Handler)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{_srv.server_address[1]}'
W, _ = run(f"""d = webread('{base}/data.json', 'k', 'v w', 'n', 5); t = webread('{base}/note.txt'); b = webread('{base}/bytes');
r = webwrite('{base}/post', 'a', 1, 'b', 'x y'); r2 = webwrite('{base}/post', struct('p', [1 2]));
f = websave('saved.json', '{base}/data.json'); g = fileread(f); o = weboptions('Timeout', 3); d2 = webread('{base}/data.json', o);""")
same('webread of JSON: the query on the address, the answer as a struct', (text(W['d'].get1('name')), v(W['d'].get1('vals')).tolist(), text(W['d'].get1('q'))),
     ('probe', [1.0, 2.0, 3.0], 'k=v+w&n=5'))
same('webread of text and of bytes', (text(W['t']), v(W['b']).tolist()), ('plain text å', [1, 2, 3, 250]))
same('webwrite: a form, and a struct as JSON (as jsonencode writes it)', (text(W['r'].get1('type')), text(W['r'].get1('body')), text(W['r2'].get1('type')), text(W['r2'].get1('body'))),
     ('application/x-www-form-urlencoded', 'a=1&b=x+y', 'application/json', '{"p":[1,2]}'))
same('websave writes the answer to a file; weboptions', ('"probe"' in text(W['g']), text(W['d2'].get1('name'))), (True, 'probe'))
_srv.shutdown()

# ---- more plots ----------------------------------------------------------------------------------------------------------
W, _ = run("""figure; compass([1 -1 0], [1 1 2]); k1 = class(gca); n1 = numel(get(gca, 'Children'));
figure; h2 = feather([1 2], [1 -1]); n2 = numel(h2);
[t, r] = rose([0.1 0.2 3], 4);
figure; [H, ax] = pareto([5 20 3 70 2]); nb = numel(get(H(1), 'YData')); yb = get(H(1), 'YData');
figure; h3 = stem3([1 2 3]); z3 = get(h3(2), 'ZData');
figure; comet([1 2 3], [3 1 2]); n4 = numel(get(gca, 'Children'));
figure; h5 = bar3([1 2; 3 4]); v5 = get(h5(2), 'Vertices'); top5 = max(v5(:, 3)); f5 = size(get(h5(1), 'Faces'));
figure; h6 = bar3h([1 2 3]); v6 = get(h6, 'Vertices'); x6 = max(v6(:, 1));
figure; h7 = histogram2([1 2 2 3], [1 1 2 3], [2 2]); v7 = get(h7, 'Vertices'); z7 = max(v7(:, 3));
figure; h8 = pie3([1 2 3]); n8 = numel(h8); t8 = get(h8(4), 'String');
figure; h9 = ribbon([1 2; 3 4; 5 6]); n9 = numel(h9); [az, el] = view; close all""")
same('compass draws in polar axes, one line for all the arrows; feather two lines', (text(W['k1']), W['n1'], W['n2']), ('matlab.graphics.axis.PolarAxes', 1.0, 2.0))
near('rose: the outline of each bin (edges at 0 and at the count)', (W['t'], W['r']), list(np.repeat(np.linspace(0, 2 * math.pi, 5), [2, 4, 4, 4, 2])) + [0, 2, 2, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
near('pareto: the largest values first, until 95 % of the total', W['yb'], [70, 20, 5])
near('stem3: markers at the values', W['z3'], [1, 2, 3])
same('comet: the path and its head', W['n4'], 2.0)
same('bar3: a patch per series, six faces a bar, as tall as the values', (W['top5'], v(W['f5']).tolist()), (4.0, [12.0, 4.0]))
same('bar3h: the values along x; histogram2: the counts as heights', (W['x6'], W['z7']), (3.0, 2.0))
same('pie3: three patches and a label for each wedge', (W['n8'], text(W['t8'])), (12.0, '17%'))
same('ribbon: a surface per column, seen in 3-D', (W['n9'], W['az'], W['el']), (2.0, -37.5, 30.0))
W, _ = run("""[X, Y, Z] = meshgrid(-2:0.5:2); V = X.^2 + Y.^2 + Z.^2;
fv = isosurface(X, Y, Z, V, 1); nf = size(fv.faces, 2); rr = sqrt(sum(fv.vertices.^2, 2)); [Fc, Vc] = isosurface(V, 4);
figure; h = slice(X, Y, Z, V, 0, [], [-1 1]); ns = numel(h); c1 = get(h(1), 'CData'); close all
[x, y] = meshgrid(0:0.1:1); u = -y + 0.5; v = x - 0.5;
XY = stream2(x, y, u, v, 0.8, 0.5); L = XY{1}; rad = max(abs(sqrt((L(:, 1) - 0.5).^2 + (L(:, 2) - 0.5).^2) - 0.3)); nL = size(L, 1);
XYZ = stream3(X, Y, Z, ones(size(X)), zeros(size(X)), zeros(size(X)), -2, 0, 0); P = XYZ{1};
figure; streamline(x, y, u, v, [0.8 0.9], [0.5 0.5]); nl = numel(get(gca, 'Children'));
figure; surf(peaks(10)); view(0, 30); camorbit(10, 5); [az, el] = view; c = [mean(xlim) mean(ylim) mean(zlim)]; campos(c + [0 -20 0]); [az2, el2] = view; close all""")
C('isosurface of a sphere: triangles with corners near the unit sphere (linear between grid points)', W['nf'] == 3 and np.max(np.abs(v(W['rr']) - 1)) < 0.1, np.max(np.abs(v(W['rr']) - 1)))
C('slice: a surface per plane, coloured by the volume (x = 0: y^2 + z^2)', W['ns'] == 3 and np.isclose(np.asarray(W['c1'])[4, 4], 0.0), W['ns'])
C('stream2: a circular flow stays on its circle', W['rad'] < 1e-6 and W['nL'] > 100, (W['rad'], W['nL']))
C('stream3: a uniform flow along x runs straight to within a step (0.05) of the edge', 1.95 - 1e-9 <= np.asarray(W['P'])[-1, 0] <= 2 and abs(np.asarray(W['P'])[-1, 1]) < 1e-12, np.asarray(W['P'])[-1])
same('streamline draws a line per start; camorbit turns the view; campos looks from a point', (W['nl'], W['az'], W['el']), (2.0, 10.0, 35.0))
near('campos from straight in front of the centre (-y) is azimuth 0, elevation 0', (W['az2'], W['el2']), [0, 0], 1e-6)

W, _ = run("""r = rectint([1 1 3 3 3 3], [2 2 2 5 5 5]); AA = 2 * eye(3); M = [1 0 0; 0 1 0; 0 0 0];
[x1, flag] = gmres(@(y) AA * y, ones(3, 1), [], [], [], @(y) M \ y, @(y) y);
n = 30; A = diag(4*ones(n, 1)) + diag(-2*ones(n-1, 1), -1) + diag(-ones(n-1, 1), 1); b = sum(A, 2);
M1 = diag(ones(n, 1)) + diag(-0.5*ones(n-1, 1), -1); M2 = diag(4*ones(n, 1)) + diag(-ones(n-1, 1), 1);
[xq, fq] = qmr(A, b, 1e-10, 30, M1, M2); eq = max(abs(xq - 1));
v = -2:0.5:2; [X, Y, Z] = meshgrid(v, v, v); fv = isosurface(v, [], v, X.^2 + Y.^2 + Z.^2, 1); nv = size(fv.vertices, 2);
[f, vv, c] = isosurface(X, Y, Z, X.^2 + Y.^2 + Z.^2, 1, Y); ec = max(abs(c - vv(:, 2)));
try, qz(1, 2, 3), catch e, mq = e.message; end""")
same('rectint in three dimensions: the volume of the overlap', W['r'], 12.0)
same('a singular preconditioner: flag 2', W['flag'], 2.0)
C('qmr with left and right preconditioners', W['fq'] == 0 and W['eq'] < 1e-8, W['eq'])
C('isosurface with grid vectors (and [] for 1:n); colours carried to the vertices', W['nv'] == 3 and W['ec'] < 1e-12, W['ec'])
C("qz refuses a flag that is not text", 'must be text' in text(W['mq']), text(W['mq']))

# ---- gsvd, ordqz, rsf2csf, gallery -------------------------------------------------------------------
W, _ = run("""A = [1 2 3; 4 5 6; 7 8 10; 1 0 1]; B = [2 1 0; 1 3 1];
[U, V, X, C, S] = gsvd(A, B); e1 = [norm(A - U*C*X') norm(B - V*S*X') norm(C'*C + S'*S - eye(3)) norm(U'*U - eye(4)) norm(V'*V - eye(2))];
sg = gsvd(A, B); sz = [size(U) size(V) size(X) size(C) size(S)];
[U2, V2, X2, C2, S2] = gsvd(B, A); e2 = [norm(B - U2*C2*X2') norm(A - V2*S2*X2')]; c2 = C2; s2 = S2;
[Ue, Ve, Xe, Ce, Se] = gsvd(A, B, 0); se = [size(Ue) size(Ce)];
M = magic(4); H = hilb(4); [AA, BB, Q, Z] = qz(M, H);
[AAS, BBS, QS, ZS] = ordqz(AA, BB, Q, Z, 'udi'); eq = [norm(QS*M*ZS - AAS) norm(QS*H*ZS - BBS)]; ev = ordeig(AAS, BBS);
k = [1 2 3 4]; ev0 = ordeig(AA, BB); [A4, B4] = ordqz(AA, BB, Q, Z, k); ev4 = ordeig(A4, B4);
[Ur, Tr] = schur([1 2 0; -3 1 0; 0 0 5]); [Uc, Tc] = rsf2csf(Ur, Tr); er = norm(Uc*Tc*Uc' - [1 2 0; -3 1 0; 0 0 5]); tu = istriu(Tc);""")
C('gsvd: A = U*C*X\', B = V*S*X\', C\'*C + S\'*S = I, U and V unitary', np.all(np.asarray(W['e1']) < 1e-12), W['e1'])
near('gsvd: the sizes of U, V, X, C and S', W['sz'], [[4, 4, 2, 2, 3, 3, 4, 3, 2, 3]])
sg = np.asarray(W['sg']).reshape(-1)
C('gsvd: the generalized singular values increase, the last infinite (B has fewer rows than columns)', np.all(np.diff(sg[:2]) > 0) and np.isinf(sg[2]), sg)
c2, s2 = np.asarray(W['c2']), np.asarray(W['s2'])
C("gsvd with fewer rows in A than columns: C's nonzeros one diagonal to the right, S's on the main diagonal",
  np.all(np.asarray(W['e2']) < 1e-12) and c2[0, 0] == 0 and c2[0, 1] > 0 and c2[1, 2] > 0 and np.all(np.diag(s2) > 0) and np.diag(s2)[0] == 1, (c2.tolist(), s2.tolist()))
near('gsvd(A, B, 0): the economy size', W['se'], [[4, 3, 3, 3]])
ev = np.asarray(W['ev']).reshape(-1)
C("ordqz 'udi': the eigenvalue inside the unit disk first; the factorization holds", np.all(np.asarray(W['eq']) < 1e-9) and abs(ev[0]) < 1, ev)
ev0, ev4 = np.asarray(W['ev0']).reshape(-1), np.asarray(W['ev4']).reshape(-1)
C('ordqz with keys: the clusters in order of decreasing key', np.allclose(ev4, ev0[::-1], rtol=1e-8), (ev0, ev4))
C('rsf2csf: a complex triangular Schur form of the same matrix', W['er'] < 1e-12 and W['tu'] is True, W['er'])

W, _ = run("""a = gallery('minij', 3); b = gallery('frank', 3); c = gallery('clement', 3); d = gallery('binomial', 4); e = gallery('invol', 5);
f = gallery('poisson', 3); g = gallery('tridiag', 3); h = gallery('lehmer', 3); o = gallery('orthog', 4, 2); p = gallery('kms', 3, 0.5);
r = gallery('redheff', 4); m = gallery('moler', 3); w = gallery('wilk', 21); x1 = gallery('integerdata', 9, [2 2], 4); x2 = gallery('integerdata', 9, [2 2], 4);
[v, beta, s] = gallery('house', [3; 4]); hx = (eye(2) - beta*(v*v'))*[3; 4]; iv = gallery('invhess', 2); em = size(gallery('minij', -1));
try, gallery('nosuch', 3), catch err, mg = err.message; end""")
near("gallery('minij')", W['a'], [[1, 1, 1], [1, 2, 2], [1, 2, 3]])
near("gallery('frank')", W['b'], np.array([[3, 2, 1], [2, 2, 1], [0, 1, 1]]).T)
near("gallery('clement')", W['c'], np.array([[0, 1, 0], [2, 0, 2], [0, 1, 0]]).T)
dd = np.asarray(W['d'])
C("gallery('binomial', n): its square is 2^(n-1) times I", np.allclose(dd @ dd, 8 * np.eye(4)), dd.tolist())
ee = np.asarray(W['e'])
C("gallery('invol'): an involution, A*A = I", np.allclose(ee @ ee, np.eye(5), atol=1e-6 * np.abs(ee).max() ** 2), None)
C("gallery('poisson') and 'tridiag' are sparse", type(W['f']).__name__ == 'Sparse' and type(W['g']).__name__ == 'Sparse' and W['f'].shape == (9, 9), None)
near("gallery('lehmer')", W['h'], [[1, 1 / 2, 1 / 3], [1 / 2, 1, 2 / 3], [1 / 3, 2 / 3, 1]])
oo = np.asarray(W['o'])
C("gallery('orthog', n, 2) is orthogonal", np.allclose(oo.T @ oo, np.eye(4)), None)
near("gallery('kms')", W['p'], [[1, .5, .25], [.5, 1, .5], [.25, .5, 1]])
near("gallery('redheff')", W['r'], np.array([[1, 1, 1, 1], [1, 1, 0, 1], [1, 0, 1, 0], [1, 0, 0, 1]]).T)
near("gallery('moler')", W['m'], [[1, -1, -1], [-1, 2, 0], [-1, 0, 3]])
near("gallery('wilk', 21): the top-left corner", np.asarray(W['w'])[:2, :2], [[10, 1], [1, 9]])
C('the data sets: the same seed gives the same numbers', np.array_equal(np.asarray(W['x1']), np.asarray(W['x2'])) and np.all((np.asarray(W['x1']) >= 1) & (np.asarray(W['x1']) <= 9)), None)
near("gallery('house'): H*x = s*e1, s against the sign of x(1)", (W['hx'], W['s']), [-5, 0, -5])
near("gallery('invhess', 2)", W['iv'], np.array([[1, -1], [1, 2]]).T)
near("gallery('minij', -1) is empty", W['em'], [[0, 0]])
C('an unknown name lists the ones there are', 'lehmer' in str(text(W.get('mg', ''))), W.get('mg'))

# ---- coneplot, streamtube, contourslice, the camera --------------------------------------------------
W, _ = run("""[x, y, z] = meshgrid(-2:0.5:2, -2:0.5:2, -1:0.5:1); u = -y; v = x; w = 0.2*ones(size(x));
f = figure('Visible', 'off');
h = coneplot(x, y, z, u, v, w, [1 0 -1], [0 1 0], [0 0 0]); nv = size(get(h, 'Vertices'), 1); cdat = get(h, 'FaceVertexCData');
P = get(h, 'Vertices'); tipdir = P(13, :) - P(14, :);
t = streamtube(x, y, z, u, v, w, [1 0.5], [0 0], [0 0]); nt = numel(t); tc = size(get(t(1), 'XData'), 2);
V = x.^2 + y.^2 + z.^2; c = contourslice(x, y, z, V, [], [], 0, [1 2]); nc = numel(c);
Pc = get(c(1), 'Vertices'); lev = get(c(1), 'FaceVertexCData'); rr = sqrt(Pc(:,1).^2 + Pc(:,2).^2); zc = Pc(:, 3);
t0 = camtarget; camtarget([1 1 0]); t1 = camtarget; m1 = camtarget('mode'); camtarget('auto'); m2 = camtarget('mode');
u0 = camup; camup([1 0 0]); u1 = camup; camup([0 0 1]); view(0, 90); camroll(90); u2 = camup; close(f);""")
same('coneplot: one cone (12 + 2 points) at each of three points', W['nv'], 42.0)
td = np.asarray(W['tipdir']).reshape(-1)
C("coneplot: the first cone (at (1,0,0), where the field is (0,1,0.2)) points along the field", td[1] > 0 and abs(td[0]) < 1e-9 and td[2] > 0, td)
cdv = np.asarray(W['cdat']).reshape(-1)
C('coneplot: coloured by the speed at each point', np.allclose(cdv[:14], math.sqrt(1 + 0.04)) and np.allclose(cdv[14:28], math.sqrt(1 + 0.04)), cdv[:3])
C('streamtube: a tube (21 points round) for each starting point', W['nt'] == 2 and W['tc'] == 21, (W['nt'], W['tc']))
rr, zc = np.asarray(W['rr']).reshape(-1), np.asarray(W['zc']).reshape(-1)
lev = float(np.asarray(W['lev']).reshape(-1)[0])
C('contourslice: lines of each level on the plane z = 0 (circles of the radius sqrt(level))', W['nc'] >= 2 and np.allclose(zc, 0) and np.allclose(rr, math.sqrt(lev), atol=0.05), (W['nc'], lev, rr[:3]))
near('camtarget: the middle of the limits, then the point set', (W['t0'], W['t1']), [0, 0, 0, 1, 1, 0])
C("camtarget's mode", text(W['m1']) == 'manual' and text(W['m2']) == 'auto', (W['m1'], W['m2']))
near('camup: [0 0 1], then the vector set', (W['u0'], W['u1']), [0, 0, 1, 1, 0, 0])
near('camroll(90) looking down z: the up vector turned a quarter turn about z', W['u2'], [0, 0, 1], 1e-9)

sys.exit(C.done())
