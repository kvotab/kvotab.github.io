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
W, _ = run("a = wilkinson(0); b = compan(4); c = full(speye()); d = speye([3 2]); e = str2num('[1e999 -1e999]'); f = [1e999];")
same('wilkinson(0), compan of a scalar: empty; speye() and speye([m n])', (size(W['a']), size(W['b']), W['c'], list(W['d'].shape)), ([0, 0], [0, 0], 1.0, [3, 2]))
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

# ---- dates: year 0 and before, text, rounding ---------------------------------------------------------------------------------------
W, _ = run("a = datenum(0, 1, 1); b = datenum(-1, 12, 31); c = datenum(2000, 1, 1); v = datevec(-400.25); d = datenum(2024, 14, 1) - datenum(2025, 2, 1);")
same('day 1 is 1 January of year 0; the day before is 0; 2000-01-01 is 730486', (W['a'], W['b'], W['c']), (1.0, 0.0, 730486.0))
near('a date before year 0 (proleptic Gregorian)', W['v'], [-2, 11, 25, 18, 0, 0])
same('months past 12 roll into the next year', W['d'], 0.0)
W, _ = run("a = datevec('2024-02-29 13:45:30'); b = datevec('Mar.05,2021 07:08:09'); c = datevec('20240229T134530'); y = clock; e = datevec('15:38:21.25', 'HH:MM:SS.FFF'); f = datevec('07/04/1999');")
near('datevec of ISO text', W['a'], [2024, 2, 29, 13, 45, 30])
near("datevec of 'mmm.dd,yyyy HH:MM:SS' and of 'yyyymmddTHHMMSS'", (W['b'], W['c']), [2021, 3, 5, 7, 8, 9, 2024, 2, 29, 13, 45, 30])
near('a time alone is 1 January of this year; FFF reads the fraction as written', W['e'], [v(W['y'])[0], 1, 1, 15, 38, 21.25])
near('mm/dd/yyyy', W['f'], [1999, 7, 4, 0, 0, 0])
W, _ = run("a = datestr(datenum(2024,1,1,10,0,0) - datenum(2024,1,1,9,55,0), 'HH:MM:SS.FFF'); b = datestr(730486.5); c = datestr(730486); d = datestr(730486, 'dddd mmmm dd, yyyy'); e = datestr(730486.75, 'HH:MM PM');")
same('a difference of date numbers shows as whole minutes (rounded to milliseconds)', text(W['a']), '00:05:00.000')
same('datestr: time shown unless it is midnight', (text(W['b']), text(W['c'])), ('01-Jan-2000 12:00:00', '01-Jan-2000'))
same('day and month names, and PM', (text(W['d']), text(W['e'])), ('Saturday January 01, 2000', ' 6:00 PM'))
W, _ = run("a = weekday(730486); [n, s] = weekday(730487); b = addtodate(datenum(2024, 1, 31), 1, 'month'); c = eomday(1900, 2); d = eomday(2000, 2); [~, ~, dd] = datevec([730486 730487; 730488 730489]); sz = size(dd); e = etime([2024 1 1 0 0 0], [2023 12 31 23 59 0.5]);")
same('weekday: 1 January 2000 was a Saturday (7); the next day Sun', (W['a'], W['n'], text(W['s'])), (7.0, 1.0, 'Sun'))
same('a month after 31 January 2024 is its last day, 29 February', W['b'], 739311.0)
same('1900 is not a leap year, 2000 is', (W['c'], W['d']), (28.0, 29.0))
same('[~, ~, d] = datevec(A) keeps the shape of A', v(W['sz']).tolist(), [2.0, 2.0])
same('etime counts seconds exactly across midnight', W['e'], 59.5)

# ---- textscan --------------------------------------------------------------------------------------------------------------------
W, _ = run(r"c = textscan(sprintf('a,1,2.5\nb,,4'), '%s %d %f', 'Delimiter', ','); a = c{1}; b = c{2}; k = class(b); f = c{3};")
same('textscan: text, int32 (an empty field is 0) and double columns', ([text(x) for x in W['a'].a.reshape(-1)], v(W['b']).tolist(), text(W['k']), v(W['f']).tolist()),
     (['a', 'b'], [1, 0], 'int32', [2.5, 4.0]))
W, _ = run(r"c = textscan('123456', '%2f'); d = textscan('12.5e1x', '%4f %s'); e = textscan(sprintf('x y\n1 2\n3 4'), '%f %f', 'HeaderLines', 1, 'CollectOutput', true);")
near('widths: %2f reads two characters at a time', W['c'].a[0, 0], [12, 34, 56])
near('%4f reads 12.5 of 12.5e1 and leaves the rest', W['d'].a[0, 0], [12.5])
near('HeaderLines and CollectOutput: one 2-by-2 matrix', W['e'].a[0, 0], [1, 3, 2, 4])
W, _ = run(r"c = textscan(sprintf('1,NA,3\n4,5,-\n'), '%f %f %f', 'Delimiter', ',', 'TreatAsEmpty', {'NA', '-'}, 'EmptyValue', -1); a = [c{:}];")
near('TreatAsEmpty fields take EmptyValue', W['a'], [1, 4, -1, 5, 3, -1])
W, _ = run(r"""c = textscan(sprintf('1 2 3\n4 x 6'), '%f %f %f'); n = cellfun(@numel, c); d = textscan('"a b" c', '%q'); q = d{1}; e = textscan('2+3i -1.5e2 inf', '%f'); z = e{1};""")
near('a field that does not read stops the scan: columns of unequal length', W['n'], [2, 1, 1])
same('%q reads a quoted field whole and strips the quotes', [text(x) for x in W['q'].a.reshape(-1)], ['a b', 'c'])
near('complex numbers, exponents and Inf', W['z'], [2 + 3j, -150, np.inf])
W, _ = run(r"c = textscan(sprintf('1 %% one\n2 %% two'), '%f', 'CommentStyle', '%'); [d, p] = textscan('1 2 3 4 5', '%f %f', 1); e = textscan('7;8;9', '%d8', 'Delimiter', ';'); k = class(e{1});")
near('CommentStyle skips to the end of the line', W['c'].a[0, 0], [1, 2])
same('N applies the format N times; the second output is where reading stopped', (v(W['d'].a[0, 0]).tolist(), W['p']), ([1.0], 4.0))
same('%d8 gives int8', text(W['k']), 'int8')

# ---- cov, mad, normalize -------------------------------------------------------------------------------------------------------------
W, _ = run("a = cov([1 2 3], [1 2 4]); b = cov([1 2 3 4], 1); c = cov(5, 3); d = cov([1 2; 3 5; 4 4], [1 1 2]'); e = cov([1 NaN; 2 3; 4 5], 'omitrows'); f = class(cov(single([1 2 3])));")
near('cov(x, y) is 2 by 2', W['a'], np.cov([1, 2, 3], [1, 2, 4]).reshape(-1, order='F'))
near('cov(x, 1) normalizes by N', W['b'], 1.25)
near('cov of two scalars: zeros', W['c'], [0, 0, 0, 0])
X = np.array([[1, 2], [3, 5], [4, 4.]])
w = np.array([1, 1, 2.])
mu = w @ X / w.sum()
near('cov with weights, normalized by their sum', W['d'], (((X - mu).T * w) @ (X - mu) / w.sum()).reshape(-1, order='F'))
near("'omitrows' drops rows with NaN", W['e'], np.cov(np.array([[2, 3], [4, 5.]]), rowvar=False).reshape(-1, order='F'))
same('cov keeps single', text(W['f']), 'single')
W, _ = run("a = mad([1 2 3 100]); b = mad([1 2 3 100], 1); c = mad([1 NaN 3]); d = mad(magic(4), 0, 'all'); e = class(mad(single([1 2]))); f = mad([2 Inf]);")
near('mad: mean absolute deviation; flag 1, median absolute deviation', (W['a'], W['b']), [np.mean(np.abs(np.array([1, 2, 3, 100]) - 26.5)), 1.0])
near("NaN is left out; 'all'", (W['c'], W['d']), [1.0, np.mean(np.abs(np.arange(1, 17) - 8.5))])
same('mad keeps single; Inf stays Inf', (text(W['e']), W['f']), ('single', math.inf))
W, _ = run("[n, c, s] = normalize([2 4 6]); r = normalize([2 4 6], 'range'); m = normalize([1 2 3; 4 6 8], 2, 'norm', 1); q = normalize([1 2 3 4 100], 'medianiqr'); z = normalize([1 NaN 3]); t = normalize([1 2 3], 3); [~, c2, s2] = normalize([1 2 3], 'center', 'median', 'scale', 2);")
near('normalize: z-scores with C and S', (W['n'], W['c'], W['s']), [-1, 0, 1, 4, 2])
near("'range' fills [0, 1]; 'norm' 1 along rows", (W['r'], W['m']), [0, 0.5, 1, 1 / 6, 4 / 18, 2 / 6, 6 / 18, 3 / 6, 8 / 18])
Q = np.percentile([1, 2, 3, 4, 100], [25, 75], method='hazen')
near("'medianiqr' centres on the median, scales by the interquartile range", W['q'], (np.array([1, 2, 3, 4, 100]) - 3) / (Q[1] - Q[0]))
near('NaN stays NaN and is left out of the statistics', W['z'], [-1 / math.sqrt(2), math.nan, 1 / math.sqrt(2)])
near("along a dimension of one element: 0/0; 'center' and 'scale' together", (W['t'], W['c2'], W['s2']), [math.nan, math.nan, math.nan, 2, 2])

# ---- special functions -----------------------------------------------------------------------------------------------------------------
from scipy import special as SP  # noqa: E402
W, _ = run("a = gammainc([1 2], 1, 'scaledlower'); b = gammainc([1 2], 1, 'scaledupper'); c = gammainc(0, [0 1]); d = class(gammainc(single(1), 2)); e = gammainc(3, 2.5, 'scaledupper'); f = gammainc(2, Inf, 'scaledupper');")
near('scaled lower for a = 1: (exp(x) - 1)/x; scaled upper: 1/x', (W['a'], W['b']), [math.e - 1, (math.e ** 2 - 1) / 2, 1, 0.5], 1e-14)
near('P(0, 0) is 1, P(0, 1) is 0', W['c'], [1, 0])
same('gammainc keeps single', text(W['d']), 'single')
near('scaled upper = Q(a, x)*gamma(a+1)*exp(x)/x^a', W['e'], SP.gammaincc(2.5, 3) * SP.gamma(3.5) * math.exp(3) / 3 ** 2.5, 1e-12)
same('scaled upper with an infinite a is Inf', W['f'], math.inf)
W, _ = run("a = airy(0, 1, 1); b = airy(0, -1, true); c = expint(-1); d = expint(-Inf); e = complex(-Inf, Inf); f = class(complex(single(1), 2)); g = gammaincinv(0.25, 2, 'upper'); h = class(gammaincinv(single(0.5), 1)); k = betaincinv(0.9, 2, 3, 'upper');")
near('airy(0, z, 1) scales Ai by exp(2/3 z^(3/2)), complex for z < 0', (W['a'], W['b']), [SP.airye(1.0)[0], SP.airye(-1.0 + 0j)[0]], 1e-14)
near('expint of a negative number: -Ei(-x) - i*pi; at -Inf, -Inf - i*pi', (W['c'], W['d']), [-SP.expi(1.0) - 1j * math.pi, complex(-math.inf, -math.pi)])
W2, _ = run("a = complex(1 + 2i); b = dot([1 2; 3 4], [5 6; 7 8], 3);")
same('complex(z) of a complex z is z; dot along a dimension past the arrays\' own', (W2['a'], v(W2['b']).tolist()), (1 + 2j, [5.0, 21.0, 12.0, 32.0]))
same('complex() keeps an infinite part as it is; single stays single', (W['e'], text(W['f'])), (complex(-math.inf, math.inf), 'single'))
near('gammaincinv upper tail', W['g'], SP.gammainccinv(2, 0.25), 1e-12)
same('gammaincinv keeps single', text(W['h']), 'single')
near('betaincinv upper tail', W['k'], SP.betaincinv(2, 3, 0.1), 1e-12)
W, _ = run("a = inv(-0); b = inv(Inf); c = inv(single(4)); k = class(c); [N, D] = rat([Inf 0 -Inf]); r = rat(pi); r2 = rat(1.5, 0.01); [n2, d2] = rat(0.75);")
same('inv of a scalar is 1/x: -0 gives -Inf, Inf gives 0; single stays single', (W['a'], W['b'], text(W['k'])), (-math.inf, 0.0, 'single'))
near('rat of Inf is 1/0', (W['N'], W['D']), [1, 0, -1, 0, 1, 0])
same('rat as a continued fraction', (text(W['r']), text(W['r2'])), ('3 + 1/(7 + 1/16)', '2 + 1/(-2)'))
same('[n, d] = rat(0.75)', (W['n2'], W['d2']), (3.0, 4.0))

# ---- 64-bit integers, numbers as digits ---------------------------------------------------------------------------------------------
W, _ = run("a = intmax('int64') - 1; b = -intmin('int64'); c = int64(2)^62 + int64(3); d = int64(7) ./ int64([2 -2 0]); e = intmax('uint64') - 5; f = int64(5) .* 2.5; g = uint64(2)^63 + 0.5;")
same('int64 arithmetic is exact past 2^53', (int(W['a'].reshape(-1)[0]), int(W['b'].reshape(-1)[0]), int(W['c'].reshape(-1)[0])),
     (2 ** 63 - 2, 2 ** 63 - 1, 2 ** 62 + 3))
same('integer division rounds half away and saturates', [int(x) for x in v(W['d'])], [4, -4, 2 ** 63 - 1])
W2, _ = run("a = int64(9007199254740881); b = int32(0.49999999999999994); c = int8([2.5 -2.5]);")
same('conversion to an integer rounds exactly: no + 0.5 that itself rounds', (int(W2['a'].reshape(-1)[0]), int(W2['b'].reshape(-1)[0]), [int(x) for x in v(W2['c'])]),
     (9007199254740881, 0, [3, -3]))
same('uint64 and a double operand', (int(W['e'].reshape(-1)[0]), int(W['f'].reshape(-1)[0]), int(W['g'].reshape(-1)[0])), (2 ** 64 - 6, 13, 2 ** 63 + 1))
W, _ = run("a = dec2bin(-3); b = dec2hex(-1); c = dec2bin(-3, 10); d = dec2base(intmax('uint64'), 16); e = dec2bin(-129); f = dec2hex(int64(-2)^63 + 1); g = num2hex(single(1)); h = num2str(intmin('int64') + 1);")
same("two's complement in 8 bits (16 when needed), sign-extended to a width", (text(W['a']), text(W['b']), text(W['c']), text(W['e'])),
     ('11111101', 'FF', '1111111101', '1111111101111111'))
same('64-bit values exactly', (text(W['d']), text(W['f']), text(W['h'])), ('FFFFFFFFFFFFFFFF', '8000000000000001', '-9223372036854775807'))
same('num2hex of a single: 8 digits', text(W['g']), '3f800000')
raises('dec2base(-1, 10)', 'must not be negative')
W, _ = run("a = nextpow2(int64(2)^62 + 1); b = nextpow2(single(5)); k = class(b); c = nextpow2(NaN); d = num2str([1, 1.34; 3, 3.56], '%6.2f'); e = num2str([1e23 pi]); f = intmax('like', int8(1)); g = class(eps('like', single(1)));")
same('nextpow2 of a large int64 is exact; single stays single; NaN gives NaN', (int(W['a'].reshape(-1)[0]), text(W['k']), math.isnan(W['c'])), (63, 'single', True))
same('num2str with a format trims the blanks the rows share', [r.rstrip() for r in W['d'].row_strs()], ['1.00  1.34', '3.00  3.56'])
same('num2str: at most 16 significant digits', text(W['e']).split(), ['9.999999999999999e+22', '3.141592653589793'])
same("intmax('like', p) and eps('like', p)", (int(W['f'].reshape(-1)[0]), text(W['g'])), (127, 'single'))

# ---- statistics along dimensions -----------------------------------------------------------------------------------------------------
from scipy import stats as ST  # noqa: E402
W, _ = run("x = [1 2 3 10; 4 4 6 8]; a = moment(x, 3, 'all'); b = skewness(x, 0, 2); c = kurtosis(x, [], 'all'); d = class(skewness(single([1 2 5]))); [s, l] = bounds(x, 2); r = range(single([1 NaN 4])); k = class(r); z = zscore(x, 0, [1 2]);")
X = np.array([[1, 2, 3, 10], [4, 4, 6, 8.]])
near("moment over 'all'", W['a'], np.mean((X - X.mean()) ** 3))
near('corrected skewness along rows', W['b'], ST.skew(X, axis=1, bias=False))
near("kurtosis with flag [] over 'all'", W['c'], ST.kurtosis(X.reshape(-1), fisher=False))
same('skewness keeps single', text(W['d']), 'single')
near('bounds along rows', (W['s'], W['l']), [1, 4, 10, 8])
same('range leaves NaN out and keeps single', (float(np.asarray(W['r']).reshape(-1)[0]), text(W['k'])), (3.0, 'single'))
near('zscore over a vector of dimensions', W['z'], ((X - X.mean()) / X.std(ddof=1)).reshape(-1, order='F'))
W, _ = run("a = corr([1 2 3]); b = corr([1 2; 2 4; 3 5], [1; 2; 4]); s = size(b); k = class(corr(single([1;2;3]), [1;2;4]));")
same('corr of a row vector: three variables of one observation, NaN', bool(np.all(np.isnan(np.asarray(W['a'])))) and size(W['a']) == [3, 3], True)
same('corr(X, Y): columns of X against columns of Y; single stays single', (v(W['s']).tolist(), text(W['k'])), ([2.0, 1.0], 'single'))

# ---- moving windows ----------------------------------------------------------------------------------------------------------------
W, _ = run("x = [4 8 6 -1 -2 -3]; a = movstd(x, 3, 1); b = movvar(x, [1 0]); c = movprod(x, 2); d = movmad(x, 3); e = movmean(x, 3, 'Endpoints', 'discard'); f = movsum(x, 3, 'Endpoints', 'fill'); g = movmean([1 NaN 3], 3, 'omitnan'); h = movmax(magic(3), 2, 2);")
xx = np.array([4, 8, 6, -1, -2, -3.])
win3 = [xx[max(0, i - 1):i + 2] for i in range(6)]
near('movstd with weight 1 (by N)', W['a'], [np.std(w) for w in win3])
near('movvar with [kb kf] = [1 0]', W['b'], [0] + [np.var(xx[i - 1:i + 1], ddof=1) for i in range(1, 6)])
near('movprod of 2: the element and the one before', W['c'], [4, 32, 48, -6, 2, 6])
near('movmad: the median absolute deviation of each window', W['d'], [np.median(np.abs(w - np.median(w))) for w in win3])
near("Endpoints 'discard' and 'fill'", (W['e'], W['f']), [6, 13 / 3, 1, -2, math.nan, 18, 13, 3, -6, math.nan])
near("'omitnan'", W['g'], [1, 2, 3])
near('movmax along dimension 2', W['h'], [8, 3, 4, 8, 5, 9, 6, 7, 9])

# ---- polynomials, primes, text search, unwrap ------------------------------------------------------------------------------------------
W, _ = run("x = 0:5; y = [1 3 2 5 4 7]; [p, S] = polyfit(x, y, 1); [yy, dd] = polyval(p, [0 6], S); [b, a] = residue([-2; 7; 3], [2; 2; 1], []); [r, pp, k] = residue([1 1 1], [1 -5 8 -4]); c = class(polyval(single([1 2]), 3));")
V = np.vander(np.arange(6.), 2)
Y = np.array([1, 3, 2, 5, 4, 7.])
P = np.linalg.lstsq(V, Y, rcond=None)[0]
nr = np.linalg.norm(Y - V @ P)
Vi = np.linalg.inv(V.T @ V)
near("polyval delta from polyfit's S: normr/sqrt(df)*sqrt(1 + a inv(V'V) a')", W['dd'], [nr / 2 * math.sqrt(1 + np.array([x0, 1]) @ Vi @ np.array([x0, 1])) for x0 in (0, 6)])
near('residue(r, p, k) puts the fractions together (a repeated pole: powers in order)', (W['b'], W['a']), [1, 1, 1, 1, -5, 8, -4], 1e-12)
near('residue(b, a): repeated poles together, by decreasing size', (W['r'], W['pp']), [-2, 7, 3, 2, 2, 1], 1e-9)
same('polyval keeps single', text(W['c']), 'single')
W, _ = run("a = isprime(uint64(4294967291) * uint64(3)); c = isprime(int64(9007199254740881)); d = strfind('abc', ''); s = size(d); e = strfind('abab', 'ab', 'ForceCellOutput', true); f = unwrap([0; 3*pi], [], 2);")
same('isprime: exact 64-bit tests', (W['a'], W['c']), (False, True))
same('strfind with an empty pattern gives [] (0 by 0); ForceCellOutput gives a cell', (v(W['s']).tolist(), type(W['e']).__name__), ([0.0, 0.0], 'Cell'))
near('unwrap along dimension 2 of a column leaves it as it is', W['f'], [0, 3 * math.pi])

# ---- validateattributes, find, cellfun, cell2mat, colormaps, generators ------------------------------------------------------------------
for code, words in (("validateattributes(ones(2,3), {'numeric'}, {'square'})", 'square'),
                    ("validateattributes([1 2 4], {}, {'increasing', 'even'})", 'even'),
                    ("validateattributes(int8(5), {'float'}, {})", 'one of these types'),
                    ("validateattributes(ones(2,3), {}, {'size', [2 NaN 4]})", 'of size'),
                    ("validateattributes(3, {'numeric'}, {'<=', 2}, 'myfun', 'n', 2)", 'input number 2, n,'),
                    ("validateattributes([1 NaN], {}, {'nonnan'})", 'non-NaN')):
    raises(code, words)
W, _ = run("validateattributes(int8([2 4]), {'integer'}, {'even', 'positive', 'row', 'size', [1 NaN]}); ok = true;")
same('validateattributes passes what has every attribute', W.get('ok'), True)
W, _ = run("a = find(0); s = size(a); [r, c] = find(0); t = size(r); C = {ones(2, 3), 'ab'; 5, {}}; n = cellfun('size', C, 2); k = cellfun('isclass', C, 'char');")
same('nothing found in a scalar: 0 by 0', (v(W['s']).tolist(), v(W['t']).tolist()), ([0.0, 0.0], [0.0, 0.0]))
near("cellfun('size', C, 2) and cellfun('isclass', C, 'char')", (W['n'], W['k']), [3, 1, 2, 0, 0, 0, 1, 0])
W, _ = run("C = {[1 2], 3; [4 5], 6}; D = C; D(:, :, 2) = {[7 8], 9; [10 11], 12}; M = cell2mat(D); s = size(M);")
same('cell2mat of a 3-D cell', (v(W['s']).tolist(), v(np.asarray(W['M'])[:, :, 1]).tolist()), ([2.0, 3.0, 2.0], [7.0, 10.0, 8.0, 11.0, 9.0, 12.0]))
W, _ = run("a = hot(3); b = jet(2); c = bone(1); d = pink(1);")
near('hot(3), jet(2), bone(1), pink(1)', (W['a'], W['b'], W['c'], W['d']),
     [1, 1, 1, 0, 1, 1, 0, 0, 1, 0, 0, 0, 1, 1, 1, 1 / 8, 1 / 8, 1 / 8] + [math.sqrt(1 / 3)] * 3)
W, _ = run("rng(3); rand(1, 5); s = rng; a = rand(1, 3); randn(2); rng(s); b = rand(1, 3); st = rand('state'); c = rand(1, 2); rand('state', st); d = rand(1, 2);")
same("rng(s) brings back the state s was taken in; so does rand('state', st)", (np.array_equal(W['a'], W['b']), np.array_equal(W['c'], W['d'])), (True, True))

# ---- found writing the function pages ------------------------------------------------------------------
W, _ = run("k = polyder([1 2 3]); kp = polyder([1 1], [1 -1]); [q, d] = polyder([1 2 3], [1 0 1]); [q0, d0] = polyder([2 2], [1 1]); k0 = polyder(5);")
same("polyder: of a polynomial, of a product, and [q, d] of a quotient (q = a'b - ab' over b^2, leading zeros dropped)",
     (v(W['k']).tolist(), v(W['kp']).tolist(), v(W['q']).tolist(), v(W['d']).tolist(), v(W['q0']).tolist(), v(W['d0']).tolist(), v(W['k0']).tolist()),
     ([2.0, 2.0], [2.0, 0.0], [-2.0, -4.0, 2.0], [1.0, 0.0, 2.0, 0.0, 1.0], [0.0], [1.0, 2.0, 1.0], [0.0]))
W, _ = run("a = sscanf('1,2,3,4', '%d,'); [d, n] = sscanf('1,2,3,4', '%d,', [2 2]); f = sscanf('10:20:30', '%d:');")
same("sscanf: literal text after the last conversion matched before the format starts again", (v(W['a']).tolist(), v(W['d']).tolist(), float(v(W['n'])), v(W['f']).tolist()),
     ([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0], 4.0, [10.0, 20.0, 30.0]))
with open(os.path.join(TMP, 'nameOf.m'), 'w') as fh:
    fh.write("function nameOf(a, b)\nfprintf('[%s][%s]\\n', inputname(1), inputname(2));\nend\n")
R.bump_epoch()
_, o1 = run("data = 1:3; nameOf(data, data + 1)")
_, o2 = run("p = 1; nameOf(p, 2), nameOf(3, p)")
_, o3 = run("x = [1 2]; display(x)")
_, o4 = run("disp('before'); s = evalc('disp(1)'); disp('after')")
same("inputname: a variable's name, '' for an expression and where a line has the call twice; display(x) names x; evalc keeps the output before it",
     (o1.strip(), o2.split(), o3.split('\n')[0], o4.split()), ('[data][]', ['[][]', '[][]'], 'x =', ['before', 'after']))
W, _ = run("o = optimoptions('fminunc', 'MaxIterations', 50); o = resetoptions(o, 'MaxIterations'); m = o.MaxIterations; e = optimoptions('fmincon').MaxFunctionEvaluations;")
same("an option's default number reaches the workspace as a double", (type(W['m']).__name__ != 'int', type(W['e']).__name__ != 'int', float(v(W['m'])), float(v(W['e']))), (True, True, 400.0, 3000.0))

sys.exit(C.done())
