"""Built-in functions at their edges, run natively (CPython with numpy and
scipy): dimensions past an array's own and vectors of dimensions (vecdim),
empty inputs, the classes results keep (single, integers, logical), options
(weights, output types, comparison methods), complex values and branches,
and shapes (orientation of results, char arrays, cells). The expected values
are worked out here by hand, from identities, or with NumPy and SciPy.

    python3 test_funcs.py          (from any folder)
"""
import asyncio
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
TMP = tempfile.mkdtemp(prefix='pylab-funcs-')


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


# ---- dimensions past an array's own, and vectors of them ---------------------------------------------------------------
W, _ = run("x = magic(3); a = sum(x, 99); b = prod(x, 50); c = mean(x, 40); d = median(x, 99); e = sort(x, 100); f = max(x, [], 7);")
same('a dimension past the array\'s own is a singleton one (sum, prod, mean, median, sort, max)',
     [np.array_equal(np.asarray(W[k]), np.asarray(W['x'])) for k in 'abcdef'], [True] * 6)
W, _ = run("x = reshape(1:24, 2, 3, 4); a = sum(x, [1 2]); b = mean(x, [1 3]); c = max(x, [], [2 3]); d = median(x, [1 2]); e = var(x, 0, [1 2]); f = any(x > 23, [1 2]);")
X = np.arange(1, 25, dtype=float).reshape(2, 3, 4, order='F')
near('sum over [1 2]', W['a'], X.sum(axis=(0, 1)))
same('its shape: 1 by 1 by 4', size(W['a']), [1, 1, 4])
near('mean over [1 3]', W['b'], X.mean(axis=(0, 2)))
near('max over [2 3]', W['c'], X.max(axis=(1, 2)))
near('median over [1 2]', W['d'], np.median(X, axis=(0, 1)))
near('var over [1 2]', W['e'], X.reshape(6, 4, order='F').var(axis=0, ddof=1))
near('any over [1 2]', W['f'], [0, 0, 0, 1])
W, _ = run("x = reshape([5 1 7 3 9 2 8 4], 2, 2, 2); [m, i] = min(x, [], [2 3], 'linear'); ok = isequal(x(i), m);")
near('min over [2 3] with linear indices that index the minima', (W['m'], W['i']), [5, 1, 1, 2])
same('x(i) is m', W['ok'], True)
raises('cumsum(ones(2), [1 2])', 'Dimension argument must be')

# ---- mode, var, std, mean, median --------------------------------------------------------------------------------------
W, _ = run("[m, f, c] = mode([]); a = isnan(m); [m2, f2] = mode(ones(0, 3)); s = size(m2); m3 = mode(single([1 2 2])); k = class(m3); m4 = mode([1 2 2; 3 3 1], 'all');")
same('mode of nothing: NaN, frequency 0', (W['a'], W['f']), (True, 0.0))
same('mode of 0 by 3: 1 by 3', v(W['s']).tolist(), [1.0, 3.0])
same('mode keeps single', text(W['k']), 'single')
same("mode over 'all'", W['m4'], 1.0)
W, _ = run("x = [2 4 4 4 5 5 7 9]; w = [1 1 1 1 1 1 1 1]; a = var(x, w); [v, m] = var(x); b = var(x, [2 0 0 0 0 0 0 1]); c = var([1 NaN 3], [1 1 1], 'omitnan'); d = var([1 2; 3 4], 0, 'all'); e = std(x, 1);")
near('var with unit weights is var with w = 1 (by N)', W['a'], 4.0)
near('[v, m] = var(x): the variance and its mean', (W['v'], W['m']), [32 / 7, 5.0])
near('var with weights: about the weighted mean', W['b'], ((2 - 13 / 3) ** 2 * 2 + (9 - 13 / 3) ** 2) / 3)
near("weights with 'omitnan' drop the NaN and its weight", W['c'], 1.0)
near("var(A, 0, 'all')", W['d'], np.var([1, 2, 3, 4], ddof=1))
near('std with w = 1', W['e'], 2.0)
raises('var([1 2 3], [1 1])', 'weights must have as many elements')
W, _ = run("a = mean([1 2; 3 4], 'Weights', [3 1]'); b = mean([1 NaN 3], 'omitnan', 'Weights', [1 5 3]); c = class(mean(single([1 2]), 'double')); d = class(mean(int8([1 2]))); e = class(mean(int8([1 3]), 'native'));")
near("mean with 'Weights' down the columns", W['a'], [(3 + 3) / 4, (6 + 4) / 4])
near("weights with 'omitnan'", W['b'], (1 + 9) / 4)
same("mean's output types: 'double', the default for integers, 'native'", (text(W['c']), text(W['d']), text(W['e'])), ('double', 'double', 'int8'))
W, _ = run("a = median(uint8([253 254])); b = class(a); c = median([true false true]); d = class(c); e = median(int8([1 3]), 'default'); f = class(e); g = median([1 3 3i 2 1i]); h = median(single([1 2 3 4]));")
same('median keeps integers, rounding the mean of the middle two (253.5 to 254)', (int(np.asarray(W['a']).reshape(-1)[0]), text(W['b'])), (254, 'uint8'))
same('and logicals', text(W['d']), 'logical')
same("'default' gives double", (W['e'], text(W['f'])), (2.0, 'double'))
near('complex values in order of size, then angle: the middle is 2', W['g'], 2.0)
same('single stays single', str(np.asarray(W['h']).dtype), 'float32')

# ---- quantiles, iqr, trapz ---------------------------------------------------------------------------------------------
W, _ = run("a = quantile(1:10, [0.25; 0.75]); b = quantile((1:10)', [0.25 0.75]); c = quantile([], [0.5 0.9]); d = quantile(magic(4), 0.5, 'all'); e = quantile(reshape(1:8, 2, 2, 2), 0.5, [1 3]); f = iqr(1:8);")
same("a vector's quantiles laid out as p is", (size(W['a']), size(W['b'])), ([2, 1], [1, 2]))
near('their values ((i - 0.5)/n, linear between)', (W['a'], W['b']), [3, 8, 3, 8])
same('of nothing: NaN', (size(W['c']), bool(np.all(np.isnan(W['c'])))), ([1, 2], True))
near("'all'", W['d'], 8.5)
same('over [1 3]: 1 by 2', size(W['e']), [1, 2])
near('its values', W['e'], [np.median([1, 2, 5, 6]), np.median([3, 4, 7, 8])])
near('iqr', W['f'], 4.0)
W, _ = run("y = [1 2 3; 4 5 6]; a = trapz(y, 2); b = cumtrapz(y, 2); x = [0 0 0; 2 2 2]; c = trapz(x, y); d = cumtrapz([1 2 4], [1 1 1]);")
near('trapz(y, dim): a scalar second argument is the dimension', W['a'], [4, 10])
near('cumtrapz(y, 2)', W['b'], [0, 0, 1.5, 4.5, 4, 10])
near('x the size of y', W['c'], [5, 7, 9])
near('points as coordinates', W['d'], [0, 1, 3])

# ---- convolution ---------------------------------------------------------------------------------------------------------
W, _ = run("a = conv([1 1 1]', [1 1]); b = conv([1 1], [1; 1; 1]); c = conv([], [1 2]); s = size(c); d = conv(1:4, [1 1], 'same'); [q, r] = deconv([3 6], [1 2 3]);")
same('conv takes the orientation of the longer vector', (size(W['a']), size(W['b'])), ([4, 1], [4, 1]))
same('of nothing: 1 by 0', v(W['s']).tolist(), [1.0, 0.0])
near("'same': the middle, the size of the first", W['d'], [3, 5, 7, 4])
near('deconv when the divisor is longer: 0 and the rest', (W['q'], W['r']), [0, 3, 6])
W, _ = run("A = magic(4); B = [1 2; 3 4]; f = conv2(A, B); s = conv2(A, B, 'same'); v = conv2(A, B, 'valid'); e = conv2([1 2], ones(3), 'valid'); k = class(conv2(single(A), B));")
from scipy import signal as _sig  # noqa: E402
A_ = np.array([[16, 2, 3, 13], [5, 11, 10, 8], [9, 7, 6, 12], [4, 14, 15, 1]], float)
B_ = np.array([[1, 2], [3, 4]], float)
F_ = _sig.convolve2d(A_, B_)
near("conv2 'same' starts at floor(size(B)/2)", W['s'], F_[1:5, 1:5].reshape(-1, order='F'))
near("'valid'", W['v'], F_[1:4, 1:4].reshape(-1, order='F'))
same("'valid' with a larger B is empty", size(W['e']), [0, 0])
same('single stays single', text(W['k']), 'single')

# ---- splines and piecewise polynomials --------------------------------------------------------------------------------------
W, _ = run("x = 0:4; y = [sin(x); cos(x)]; a = spline(x, y, 2.5); b = [spline(x, y(1,:), 2.5); spline(x, y(2,:), 2.5)]; c = spline([3 1 2 0], [9 1 4 0], 1.5); d = pchip(x, y, [1 2]); pp = spline(x, y); dd = pp.dim; e = ppval(pp, [1 2; 3 4]);")
near('spline of a matrix: each row a curve', W['a'], v(W['b']))
near('points out of order are sorted (x^2 again)', W['c'], 2.25)
same('pchip of a matrix', size(W['d']), [2, 2])
same('its pp has dim 2', W['dd'], 2.0)
same('ppval of a matrix of points: dim by size', size(W['e']), [2, 2, 2])
W, _ = run("x = 1:5; y = x.^2; y(3) = NaN; a = spline(x, y, 3); pp = mkpp([0 1 2], 1:4); c = pp.coefs; [b, P, n, k, d] = unmkpp(pp);")
near('spline leaves out points of a vector whose value is NaN', W['a'], 9.0, 1e-9)
near('mkpp takes a vector of coefficients in column order', W['c'], [1, 2, 3, 4])
same('2 pieces of order 2', (W['n'], W['k']), (2.0, 2.0))

# ---- shiftdim, strings ------------------------------------------------------------------------------------------------------
W, _ = run("a = shiftdim(1:3); [b, n] = shiftdim(ones(1, 1, 3)); c = size(shiftdim(ones(2, 3, 4), 1)); d = size(shiftdim(ones(2, 3), -2));")
same('shiftdim', (size(W['a']), size(W['b']), W['n'], v(W['c']).tolist(), v(W['d']).tolist()), ([3, 1], [3, 1], 2.0, [3, 4, 2], [1, 1, 2, 3]))
W, _ = run("a = strsplit('a,b,,c', ','); b = strsplit('a,b,,c', ',', 'CollapseDelimiters', false); c = strsplit('a1b22c', '\\d+', 'DelimiterType', 'R');")
same('strsplit: collapsed by default, not when asked; RegularExpression by prefix',
     ([x.str() for x in W['a'].a.reshape(-1)], [x.str() for x in W['b'].a.reshape(-1)], [x.str() for x in W['c'].a.reshape(-1)]),
     (['a', 'b', 'c'], ['a', 'b', '', 'c'], ['a', 'b', 'c']))
raises("strsplit('a b', ' ', 'Nonsense', 1)", 'CollapseDelimiters or DelimiterType')
W, _ = run("a = strncmp('abc', 'abc', 100); b = strncmp('abc', 'abcd', 4); c = strncmp('abc', 'xyz', 0); d = strcmp('', char(zeros(0, 2))); e = strcmp({'a'}, {'a'; 'b'}); f = strcmp({'foo'}, char(zeros(0, 2)));")
same('strncmp compares the first n characters as they are', (W['a'], W['b'], W['c']), (True, False, True))
same('strcmp: char arrays of different sizes differ', W['d'], False)
near('a one-element cell against a cell', W['e'], [1, 0])
same('a cell against an empty char array', W['f'], False)
W, _ = run("a = upper(['ab'; 'cd']); b = lower(cat(3, 'AB', 'CD')); s = size(b); c = upper({'ab', ['x'; 'y']}); d = strvcat(65, 'b', [67 68]);")
same('upper of two rows', W['a'].row_strs(), ['AB', 'CD'])
same('lower keeps a 3-D shape', v(W['s']).tolist(), [1.0, 2.0, 2.0])
same('upper of each element of a cell', W['c'].a.reshape(-1, order='F')[1].row_strs(), ['X', 'Y'])
same('strvcat takes numbers as character codes', W['d'].row_strs(), ['A ', 'b ', 'CD'])
W, _ = run("a = [int8(65) 'b']; b = class(a); c = [single(66) 'a']; d = class(c);")
same('characters with integers or single make characters', (text(W['a']), text(W['b']), text(W['d'])), ('Ab', 'char', 'char'))

# ---- small functions: cplxpair, rescale, primes, nchoosek, wilkinson, compan, speye, str2num -----------------------------
W, _ = run("a = cplxpair([1+2i 3 1-2i]); b = cplxpair([1+1i 2; 1-1i 3]); c = cplxpair(5);")
near('cplxpair: the pair (negative imaginary first), then the reals', W['a'], [1 - 2j, 1 + 2j, 3])
near('each column of a matrix', W['b'], [1 - 1j, 1 + 1j, 2, 3])
near('a scalar', W['c'], 5.0)
raises('cplxpair([1+1i 2])', 'can not be paired')
W, _ = run("a = rescale([1 2 3]); b = rescale([1 2 3; 1 2 3], [0; 10], 20); c = rescale(0:4, 'InputMin', 1, 'InputMax', 3); d = rescale([]); e = class(rescale(single([1 2])));")
near('rescale', W['a'], [0, 0.5, 1])
near('bounds that broadcast (rows)', W['b'], [0, 10, 10, 15, 20, 20])
near('InputMin and InputMax clamp first', W['c'], [0, 0, 0.5, 1, 1])
same('of nothing, and single', (size(W['d']), text(W['e'])), ([0, 0], 'single'))
W, _ = run("a = primes(uint8(20)); b = class(a); c = primes(-Inf); d = nchoosek(1:3, 0); e = nchoosek(1:3, 4); f = nchoosek(uint8(10), 5); g = class(f); h = nchoosek({1, 'a', 3}, 2);")
same('primes keeps the class of n', (text(W['b']), v(W['a']).tolist()), ('uint8', [2, 3, 5, 7, 11, 13, 17, 19]))
same('primes(-Inf) is empty', size(W['c']), [1, 0])
same('nchoosek: k = 0 gives 1 by 0, k > n gives 0 by k', (size(W['d']), size(W['e'])), ([1, 0], [0, 4]))
same('the class of n', (float(np.asarray(W['f']).reshape(-1)[0]), text(W['g'])), (252.0, 'uint8'))
same('of a cell: a cell of the combinations', size(W['h']), [3, 2])
W, _ = run("a = wilkinson(0); b = compan(4); c = speye(); d = speye([3 2]); e = str2num('[1e999 -1e999]'); f = [1e999];")
same('wilkinson(0), compan of a scalar: empty; speye() and speye([m n])', (size(W['a']), size(W['b']), W['c'], size(W['d'])), ([0, 0], [0, 0], 1.0, [3, 2]))
near('a literal past realmax is Inf', (W['e'], W['f']), [math.inf, -math.inf, math.inf])

# ---- interpolation ------------------------------------------------------------------------------------------------------------
W, _ = run("x = 1:4; y = x.^2; a = interp1(x, y, 2.5, '*linear'); b = interp1(y, 2.5, 'linear', 0); c = interp1(y, 9, 'linear', -1); pp = interp1(x, y, 'linear', 'pp'); d = ppval(pp, 2.5); e = interp1(x, y, [0 5], 'previous', 'extrap'); f = interp1(x, y, 2.5, 'nearest');")
near("'*linear' is linear", W['a'], 6.5)
near('interp1(v, xq, method, extrapval): no x', (W['b'], W['c']), [6.5, -1])
near("the 'pp' form", W['d'], 6.5)
near("'previous' and 'next' with 'extrap': the end values", W['e'], [1, 16])
near("'nearest': a half rounds up", W['f'], 9.0)
W, _ = run("Z = [1 2; 3 4]; a = interp2(Z); s = size(a); b = interp2(Z, 1.5, 1.5); c = interp2(1:3, 1:2, [1 2 3; 4 5 6], [1.5 2.5], [1; 2]); d = interp2(Z, 3, 1); e = interp2([1 2 3; 4 5 6], 2.5, 1.5, 'nearest'); Zn = magic(4); Zn(1, 1) = NaN; f = interp2(Zn, 3.5, 3.5);")
same('interp2(Z): refined once', v(W['s']).tolist(), [3.0, 3.0])
near('its middle', v(W['a'])[4], 2.5)
near('a point', W['b'], 2.5)
same('a row of x and a column of y make a grid', size(W['c']), [2, 2])
near('its values', W['c'], [1.5, 4.5, 2.5, 5.5])
C('outside the grid: NaN', math.isnan(W['d']), str(W['d']))
near("'nearest' rounds a half up", W['e'], 6.0)
C('a NaN reaches only the points next to it', np.isfinite(W['f']), str(W['f']))
W, _ = run("V = magic(4); a = interpn(V, 2, 3); b = interpn(V, [1 2], [1 2 3]); s = size(b);")
near('interpn(V, xq, yq)', W['a'], 10.0)
same('vectors of different sizes make a grid', v(W['s']).tolist(), [2.0, 3.0])

# ---- trigonometry in degrees, branches, special functions ------------------------------------------------------------------
W, _ = run("a = cosd(23) == cosd(-23); b = sind(23) == -sind(-23); c = [sind(180) cosd(90) sind(270) cosd(360)]; d = sind(1e6); e = cosd(30 + 0i); f = sind(90 + 60i);")
same('cosd is even and sind odd, exactly', (W['a'], W['b']), (True, True))
near('exact at multiples of 90', W['c'], [0, 0, -1, 1])
near('reduced first: sind(1e6) = sind(280)', W['d'], math.sin(math.radians(280)), 1e-15)
near('of complex angles: sin(a + ib) = sin(a) cosh(b) + i cos(a) sinh(b)', W['f'], math.cosh(math.radians(60)))
W, _ = run("a = acos([2 -2]); b = asin([2 -2]); c = acscd(0.5); d = asecd(0.5);")
near("acos and asin past 1 and -1 take the language's branches", (W['a'], W['b']),
     [complex(0, math.acosh(2)), complex(math.pi, -math.acosh(2)), complex(math.pi / 2, -math.acosh(2)), complex(-math.pi / 2, math.acosh(2))])
near('acscd and asecd with complex results', (W['c'], W['d']), [np.arcsin(2 + 0j) * 180 / np.pi, np.arccos(2 + 0j) * 180 / np.pi])
W, _ = run("[sn, cn, dn] = ellipj(0.3 + 0.4i, 0.6); a = sn.^2 + cn.^2; b = dn.^2 + 0.6*sn.^2; c = pow2(1+1i, 2); d = class(pow2(single(3), 2));")
near('ellipj of a complex argument: sn^2 + cn^2 = 1 and dn^2 + m sn^2 = 1', (W['a'], W['b']), [1, 1], 1e-12)
near('pow2 of a complex value', W['c'], 4 + 4j)
same('pow2 keeps single', text(W['d']), 'single')

# ---- accumarray, gradient, del2 -----------------------------------------------------------------------------------------------
W, _ = run("a = accumarray({[1 2 1], [1 1 2]}, [10 20 30]); b = accumarray([1; 2], [3; 4], [1 2], @min, [], 7); c = accumarray([1; 1; 2], [5; 6; 7], [], @(x) {x}); d = accumarray([1; 1; 2], [1; 2; 3], [], @(x) numel(x) > 1); e = class(d); f = accumarray([1; 3], [1; 1], [], @max, 9);")
near('subscripts in a cell', W['a'], [10, 20, 30, 0])
near('a column of linear subscripts into the given size, with a function and a fill value', W['b'], [3, 4])
same('a function that returns cells makes a cell', (type(W['c']).__name__, v(W['c'].a[0, 0]).tolist()), ('Cell', [5.0, 6.0]))
same('one that returns logicals makes logicals', text(W['e']), 'logical')
near('the fill value where nothing falls', W['f'], [1, 9, 1])
W, _ = run("a = gradient([1 2 4 2], [0.25 0.5 1 3]); [gx, gy, gz] = gradient(reshape(1:24, 2, 3, 4)); b = [gx(1) gy(1) gz(1)];")
near('gradient at coordinates: (f(i+1) - f(i-1))/(x(i+1) - x(i-1)) inside', W['a'], [4, 4, 0, -1])
near('three dimensions: x, y, z', W['b'], [2, 1, 6])
W, _ = run("a = zeros(3); a(2, 2) = 1; L = del2(a); b = del2([1 4 9 16 25]);")
near('del2: second differences extended to the edges, over 2N', W['L'], [0, -0.5, 0, -0.5, -1, -0.5, 0, -0.5, 0])
near('of a vector: over 4 (here x^2: 2/4)', W['b'], [0.5] * 5)

# ---- roots, integrals, vector fields -------------------------------------------------------------------------------------------
W, _ = run("o = optimset('TolX', 0); a = fzero(@cos, [0 3], o); b = fminbnd(@(x) (x - 1)^2, 0, 3, o);")
near('fzero and fminbnd with TolX 0', (W['a'], W['b']), [math.pi / 2, 1], 1e-6)
W, _ = run("a = integral(@(z) 1./z, 1, 1, 'Waypoints', [1i, -1, -1i]); b = class(integral(@sin, single(0), 1)); c = integral(@(x) exp(1i*x), 0, pi); d = quadgk(@(x) exp(1i*x), 0, pi); [e, n] = quad(@(x, k) k*x, 0, 1, [], [], 3); f = integral3(@(x, y, z) ones(size(x)), 0, 1, 0, @(x) 1 - x, 0, @(x, y) 1 - x - y);")
near('integral around the origin through complex waypoints: 2 pi i', W['a'], 2j * math.pi, 1e-8)
same('a single limit makes a single result', text(W['b']), 'single')
near('a complex-valued integrand, by integral and by quadgk', (W['c'], W['d']), [2j, 2j], 1e-9)
near('quad passes its extra parameters, and counts its evaluations', W['e'], 1.5, 1e-9)
C('the count is a positive whole number', W['n'] > 0 and W['n'] == int(W['n']), str(W['n']))
near('integral3 with limits that are functions: the tetrahedron, 1/6', W['f'], 1 / 6, 1e-7)
W, _ = run("[X, Y] = meshgrid(-2:2, -3:3); d = divergence(X, Y, X - Y, Y); [cz, cav] = curl(X, Y, -Y, X); o = curl(-Y, X);")
same('divergence of (x - y, y) is 2 everywhere', bool(np.all(np.asarray(W['d']) == 2)), True)
same('curl of (-y, x) is 2, its angular velocity 1 (one output: the angular velocity)',
     (bool(np.all(np.asarray(W['cz']) == 2)), bool(np.all(np.asarray(W['cav']) == 1)), bool(np.all(np.asarray(W['o']) == 1))), (True, True, True))

# ---- filter, qr, sums of integers ------------------------------------------------------------------------------------------------
W, _ = run("a = class(filter(1, 1, single(1:3))); b = filter(1, [1 -0.5], zeros(0, 1)); s = size(b);")
same('filter keeps single, and filters nothing', (text(W['a']), v(W['s']).tolist()), ('single', [0.0, 1.0]))
W, _ = run("A = [1 2; 3 4; 5 6]; [Q, R] = qr(A); [C, R2] = qr(A, eye(3)); [Q3, R3, P] = qr(A, 'econ'); [Q4, R4, p] = qr(A, 0); e = qr(zeros(0, 3)); s = size(e); k = class(qr(single(A)));")
near("qr(A, B): C = Q'*B", W['C'], np.asarray(W['Q']).T.reshape(-1, order='F'), 1e-12)
same("'econ' with three outputs gives a permutation matrix, 0 a vector", (size(W['P']), size(W['p'])), ([2, 2], [1, 2]))
same('qr of nothing, and single', (v(W['s']).tolist(), text(W['k'])), ([0.0, 3.0], 'single'))
W, _ = run("a = sum(uint8([200 200])); b = class(a); c = sum(uint8([200 200]), 'native'); d = class(prod([true true], 'native')); e = sum(single([1 2]), 'double'); f = class(e);")
same('sum of integers: double (400), unless native (saturates at 255)', (W['a'], text(W['b']), int(np.asarray(W['c']).reshape(-1)[0])), (400.0, 'double', 255))
same("prod 'native' of logicals is logical; 'double' makes single double", (text(W['d']), text(W['f'])), ('logical', 'double'))

# ---- mod, eps, hypot, sort, issorted, norm, linspace -------------------------------------------------------------------------------
W, _ = run("a = mod(0.94, 0.01); b = rem(0.94, 0.01); c = eps(realmax('single')); d = class(c); e = class(hypot(single(3), 4)); f = hypot(single(3), 4);")
same('mod and rem give 0 for a whole multiple within rounding', (W['a'], W['b']), (0.0, 0.0))
same('eps(realmax(single)) is 2^104, single', (float(np.asarray(W['c']).reshape(-1)[0]), text(W['d'])), (2.0 ** 104, 'single'))
same('hypot keeps single', (text(W['e']), float(np.asarray(W['f']).reshape(-1)[0])), ('single', 5.0))
W, _ = run("a = sort([NaN 1i -1 2 Inf], 'descend'); b = sort([NaN 1i -1 2], 'ascend');")
same('sort of complex values: NaN first descending, last ascending', (math.isnan(v(W['a'])[0].real), math.isnan(v(W['b'])[-1].real)), (True, True))
W, _ = run("a = issorted([3 2 1], 'descend'); b = issorted([1 1 2], 'strictascend'); c = issorted([3 1 2], 'monotonic'); d = issorted([1 2; 1 3; 2 0], 'rows'); e = issorted({'a', 'b', 'c'}); f = issorted([1 2 NaN]); g = issorted([1 2; 0 3]);")
same('issorted: descend, strict, monotonic, rows, text, NaN last, each column', [W[k] for k in 'abcdefg'], [True, False, False, True, True, True, False])
W, _ = run("a = issorted([]); b = issorted('', 'rows');")
same('issorted of nothing is true', (W['a'], W['b']), (True, True))
W, _ = run("a = norm([1e200 1e200]); b = norm([3 -4], -Inf); c = norm([3 -4], 'fro'); d = norm([1 2], 'inf'); e = class(norm(single([3 4]))); f = norm([1 NaN; 3 4]);")
near('norm scaled so as not to overflow; -Inf, fro and inf of a vector', (W['a'], W['b'], W['c'], W['d']), [math.sqrt(2) * 1e200, 3, 5, 2])
same('norm keeps single; NaN gives NaN', (text(W['e']), math.isnan(W['f'])), ('single', True))
W, _ = run("a = class(linspace(single(0), 1, 3)); b = linspace(-realmax, realmax, 3);")
same('linspace keeps single', text(W['a']), 'single')
near('and does not overflow between -realmax and realmax', W['b'], [-np.finfo(float).max, 0, np.finfo(float).max])

sys.exit(C.done())
