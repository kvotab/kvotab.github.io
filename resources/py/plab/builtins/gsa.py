"""Global sensitivity analysis and the samples it starts from.

Sampling: lhsdesign and lhsnorm (Latin hypercubes), sobolset and haltonset
(low-discrepancy point sets, read with net or by indexing).

From any sample of inputs X (a row per run) and outputs Y: the regression
measures (src, srrc, pcc, prcc), a first-order index by binning
(firstorderindex), EASI, Borgonovo's moment-independent delta, mutual
information, PAWN, each input's share of the discrepancy, and regional
sensitivity analysis (rsa).

Designed methods, each a design function giving the runs (X, in the unit
hypercube: an input's probabilities, mapped to its distribution with icdf)
and a description D, and an indices function reading the outputs of those
runs: Morris's elementary effects, Sobol's indices by Saltelli's design,
eFAST, RBD-FAST, a two-level fractional factorial, derivative-based
measures (DGSM), the radial one-at-a-time design and Shapley effects.

These are Kompartment's methods (kompartment/src/domain/gsa.js, which ports
GlobalSensitivity.jl, salib.js, which ports SALib, and sensitivity.js), in
Python as smui's sensitivity.py has the sample-based ones; the arithmetic is
the same, and test_gsa.py checks it against Kompartment's functions on the
same designs. Random draws come from the generator rng sets."""
import math
import warnings

import numpy as np
from scipy import linalg, stats

from . import bi
from ._util import err, nargchk, darr, out, num, opt_str, sval, ival
from ..values import MError, Char, Cell, Struct, Str, text_list, numel
from ..vobj import VObj


def _rs():
    from .elmat import RNG
    return RNG.rs


def _next():
    rs = _rs()
    return lambda: float(rs.random_sample())


def _opts(args, names, fn):
    """Name-value options (any case) after the positional inputs: (positional, {name: value}).
    Text that is no option name, once the positional inputs have begun, is an error."""
    pos, opts = [], {}
    args = list(args)
    k = 0
    while k < len(args):
        o = opt_str(args[k])
        if o is not None and o.lower() in names:
            if k + 1 >= len(args):
                raise err(f'MATLAB:{fn}:missingValue', f"'{o}' needs a value.", fn)
            opts[o.lower()] = args[k + 1]
            k += 2
            continue
        if o is not None and pos and isinstance(args[k], Char):
            raise err(f'MATLAB:{fn}:unknownOption', f"'{o}' is not an option of {fn}; the options are {', '.join(sorted(names))}.", fn)
        pos.append(args[k])
        k += 1
    return pos, opts


def _int_opt(opts, key, default, fn, lo=1):
    if key not in opts:
        return default
    v = num(opts[key])
    if v != int(v) or v < lo:
        raise err(f'MATLAB:{fn}:invalidOption', f"'{key}' must be a whole number of at least {lo}.", fn)
    return int(v)


def _num_opt(opts, key, default, fn):
    return float(num(opts[key])) if key in opts else default


def _bool_opt(opts, key, default):
    if key not in opts:
        return default
    v = opts[key]
    s = opt_str(v)
    if s is not None:
        return s.lower() in ('on', 'true', 'yes')
    return bool(num(v))


def _text_opt(opts, key, default, choices, fn):
    if key not in opts:
        return default
    s = (opt_str(opts[key]) or '').lower()
    if s not in choices:
        raise err(f'MATLAB:{fn}:invalidOption', f"'{key}' is one of {', '.join(choices)}.", fn)
    return s


def _whole(v, what, fn, lo=1):
    x = num(v)
    if x != int(x) or x < lo:
        raise err(f'MATLAB:{fn}:invalidInput', f'{what} must be a whole number of at least {lo}.', fn)
    return int(x)


# ---- Latin hypercubes ----------------------------------------------------------------------------------

def _lhs(n, p, smooth, rs):
    perm = np.argsort(rs.random_sample((n, p)), axis=0) + 1
    jitter = rs.random_sample((n, p)) if smooth else 0.5
    return (perm - jitter) / n


@bi('lhsdesign')
def lhsdesign(nargout, *args):
    """lhsdesign(n, p): a Latin hypercube sample of n points in p dimensions,
    each column one point in each of n equal slices of 0 to 1, in random
    order. 'criterion' 'maximin' (the default: of 'iterations' samples, the
    one whose closest two points are farthest apart), 'correlation' (the one
    whose columns are least correlated) or 'none'; 'smooth' 'off' puts each
    point in the middle of its slice."""
    pos, opts = _opts(args, ('criterion', 'iterations', 'smooth'), 'lhsdesign')
    if len(pos) != 2:
        raise err('MATLAB:lhsdesign:invalidInput', 'Give n and p: lhsdesign(n, p).', 'lhsdesign')
    n, p = _whole(pos[0], 'n', 'lhsdesign', 0), _whole(pos[1], 'p', 'lhsdesign', 0)
    crit = _text_opt(opts, 'criterion', 'maximin', ('maximin', 'correlation', 'none'), 'lhsdesign')
    iters = _int_opt(opts, 'iterations', 5, 'lhsdesign')
    smooth = _bool_opt(opts, 'smooth', True)
    rs = _rs()
    best, score = _lhs(n, p, smooth, rs), None
    if crit != 'none' and n > 1:
        def quality(X):
            if crit == 'maximin':
                from scipy.spatial.distance import pdist
                return float(np.min(pdist(X)))
            if p < 2:
                return 0.0
            c = np.corrcoef(X, rowvar=False)
            return -float(np.sum(np.triu(c, 1) ** 2))
        score = quality(best)
        for _ in range(iters - 1):
            X = _lhs(n, p, smooth, rs)
            q = quality(X)
            if q > score:
                best, score = X, q
    return out(best)


@bi('lhsnorm', nout=2)
def lhsnorm(nargout, *args):
    """lhsnorm(mu, Sigma, n): a Latin hypercube sample of n points from the
    normal distribution of mean mu and covariance Sigma: a normal sample whose
    columns are given the values of one point in each of n slices of equal
    probability, in the order of their ranks, so that the correlations stay.
    lhsnorm(..., 'off') takes the middle of each slice; [X, Z] gives the
    normal sample too."""
    nargchk(args, 3, 4, 'lhsnorm')
    mu = np.asarray(darr(args[0]), float).reshape(-1)
    S = np.asarray(darr(args[1]), float)
    n = _whole(args[2], 'n', 'lhsnorm', 0)
    smooth = True
    if len(args) > 3:
        s = (opt_str(args[3]) or '').lower()
        if s not in ('on', 'off'):
            raise err('MATLAB:lhsnorm:invalidFlag', "The flag is 'on' or 'off'.", 'lhsnorm')
        smooth = s == 'on'
    d = mu.size
    if S.shape != (d, d):
        raise err('MATLAB:lhsnorm:invalidSigma', 'Sigma must be a square matrix of the size of mu.', 'lhsnorm')
    rs = _rs()
    try:
        L = np.linalg.cholesky((S + S.T) / 2)
    except np.linalg.LinAlgError:
        w, V = np.linalg.eigh((S + S.T) / 2)
        if np.min(w) < -1e-10 * max(1.0, np.max(np.abs(w))):
            raise err('MATLAB:lhsnorm:notPSD', 'Sigma must be symmetric and positive semi-definite.', 'lhsnorm')
        L = V * np.sqrt(np.maximum(w, 0))
    Z = mu + rs.standard_normal((n, d)) @ L.T
    X = np.empty_like(Z)
    sd = np.sqrt(np.diag(S))
    for j in range(d):
        r = stats.rankdata(Z[:, j], method='ordinal')
        u = (r - (rs.random_sample(n) if smooth else 0.5)) / n
        X[:, j] = mu[j] + sd[j] * stats.norm.ppf(u)
    return (out(X), out(Z)) if nargout > 1 else out(X)


# ---- low-discrepancy point sets ------------------------------------------------------------------------

class PointSet(VObj):
    """sobolset and haltonset: an endless sequence of points in the unit
    hypercube, read by net(p, n) or p(rows, cols)."""
    ARRAYS = ()

    def __init__(self, kind, d, skip=0, leap=0, scramble=None, seed=None):
        self.kind, self.d, self.skip, self.leap, self.scramble_method, self.seed = kind, d, skip, leap, scramble, seed
        self.cls = 'sobolset' if kind == 'sobol' else 'haltonset'

    @property
    def shape(self):
        return (2 ** 53 if self.kind == 'sobol' else 2 ** 53, self.d)

    def value_copy(self):
        return PointSet(self.kind, self.d, self.skip, self.leap, self.scramble_method, self.seed)

    def points(self, rows):
        """The points at the 0-based positions rows (after Skip and Leap)."""
        from scipy.stats import qmc
        rows = np.asarray(rows, np.int64).reshape(-1)
        if not rows.size:
            return np.zeros((0, self.d))
        idx = self.skip + rows * (self.leap + 1)
        top = int(idx.max()) + 1
        if top > 50_000_000:
            raise MError('MATLAB:qrandset:tooFar', 'Points that far into the sequence are not made here.')
        scr = self.scramble_method is not None
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            if self.kind == 'sobol':
                g = qmc.Sobol(self.d, scramble=scr, seed=self.seed if scr else None)
            else:
                g = qmc.Halton(self.d, scramble=scr, seed=self.seed if scr else None)
            P = g.random(top)
        return P[idx]

    def index(self, args):
        from ..index import conv
        if len(args) == 1:
            rows = conv(args[0])[0]
            if rows is not None and not isinstance(rows, np.ndarray):
                raise MError('MATLAB:qrandset:index', 'Index a point set by rows, or by rows and columns: p(1:10, :).')
            return out(self.points(rows).reshape(-1, 1) if self.d == 1 else self.points(rows))
        if len(args) != 2:
            raise MError('MATLAB:qrandset:index', 'Index a point set by rows and columns: p(1:10, :).')
        r, c = conv(args[0])[0], conv(args[1])[0]
        if not isinstance(r, np.ndarray):
            raise MError('MATLAB:qrandset:index', 'A point set has no end: give the rows, p(1:10, :).')
        P = self.points(r)
        if isinstance(c, np.ndarray):
            if c.size and c.max() >= self.d:
                raise MError('MATLAB:badsubscript', f'Index exceeds the {self.d} dimensions of the point set.')
            P = P[:, c]
        return out(P)

    def propnames(self):
        return ['Dimensions', 'Skip', 'Leap', 'ScrambleMethod', 'Type', 'PointOrder']

    def getprop(self, name):
        if name == 'Dimensions':
            return float(self.d)
        if name == 'Skip':
            return float(self.skip)
        if name == 'Leap':
            return float(self.leap)
        if name == 'ScrambleMethod':
            if self.scramble_method is None:
                return np.zeros((0, 0))
            return Struct.scalar({'Type': Char.of(self.scramble_method), 'Options': Cell.empty()})
        if name == 'Type':
            return Char.of('Sobol' if self.kind == 'sobol' else 'Halton')
        if name == 'PointOrder':
            return Char.of('standard')
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class '{self.cls}'.")

    def setprop(self, name, value):
        if name in ('Skip', 'Leap'):
            v = num(value)
            if v != int(v) or v < 0:
                raise MError('MATLAB:qrandset:invalid', f'{name} must be a whole number of at least 0.')
            setattr(self, name.lower(), int(v))
            return
        if name == 'ScrambleMethod':
            if numel(value) == 0:
                self.scramble_method = None
                return
        raise MError('MATLAB:qrandset:readOnly', f"Set {name} with the point set's functions (scramble).")

    def elem_strings(self):
        return np.array([[f'{self.d}-D {self.cls}']], object)

    def summary_text(self, brackets='[]'):
        return f'[1×1 {self.cls}]' if brackets == '[]' else f'1×1 {self.cls}'

    def display_lines(self):
        name = 'Sobol' if self.kind == 'sobol' else 'Halton'
        lines = [f'    {name} point set in {self.d} dimensions', '', '    Properties:',
                 f'              Skip : {self.skip}', f'              Leap : {self.leap}',
                 f'    ScrambleMethod : {self.scramble_method or "none"}', '        PointOrder : standard']
        return lines

    def disp_lines(self):
        return self.display_lines()

    def columns(self):
        raise MError('MATLAB:qrandset:loop', 'A point set has no end: loop over net(p, n) instead.')


def _not_for_pointsets(name):
    def fn(nargout, args):
        if name in ('isequal', 'isequaln'):
            a = args[0]
            return all(isinstance(b, PointSet) and (b.kind, b.d, b.skip, b.leap, b.scramble_method, b.seed)
                       == (a.kind, a.d, a.skip, a.leap, a.scramble_method, a.seed) for b in args[1:]) if isinstance(a, PointSet) else False
        raise MError('MATLAB:qrandset:UndefinedFunction', f'{name} is not defined for point sets: take their points with net(p, n) first.')
    return fn


PointSet.FUNCS = {n: _not_for_pointsets(n) for n in ('reshape', 'repmat', 'fliplr', 'flipud', 'flip', 'circshift', 'permute', 'ipermute',
                                                    'squeeze', 'transpose', 'ctranspose', 'rot90', 'sort', 'issorted', 'min', 'max',
                                                    'unique', 'isequal', 'isequaln', 'ismember')}


def _pointset(kind, args, fn):
    pos, opts = _opts(args, ('skip', 'leap', 'pointorder'), fn)
    if len(pos) != 1:
        raise err(f'MATLAB:{fn}:invalidInput', f'Give the number of dimensions: {fn}(d).', fn)
    d = _whole(pos[0], 'The number of dimensions', fn)
    if kind == 'sobol' and d > 21201:
        raise err(f'MATLAB:{fn}:tooManyDims', 'A Sobol point set has at most 21201 dimensions here.', fn)
    return PointSet(kind, d, _int_opt(opts, 'skip', 0, fn, 0), _int_opt(opts, 'leap', 0, fn, 0))


@bi('sobolset', arr=False)
def sobolset(nargout, *args):
    """sobolset(d): Sobol's sequence in d dimensions (Joe and Kuo's direction
    numbers), 'Skip' points left out at the start and 'Leap' between."""
    return _pointset('sobol', args, 'sobolset')


@bi('haltonset', arr=False)
def haltonset(nargout, *args):
    """haltonset(d): Halton's sequence in d dimensions (the first d primes as bases), with 'Skip' and 'Leap'."""
    return _pointset('halton', args, 'haltonset')


@bi('net', arr=False)
def net(nargout, *args):
    """net(p, n): the first n points of a point set, an n-by-d matrix."""
    nargchk(args, 2, 2, 'net')
    p = args[0]
    if not isinstance(p, PointSet):
        raise err('MATLAB:net:invalidInput', 'The first input must be a sobolset or a haltonset.', 'net')
    n = _whole(args[1], 'n', 'net', 0)
    return out(p.points(np.arange(n)))


@bi('scramble', arr=False)
def scramble(nargout, *args):
    """scramble(p, type): the point set scrambled: 'MatousekAffineOwen' for a
    Sobol set, 'RR2' for a Halton set; scramble(p, 'clear') undoes it."""
    nargchk(args, 1, 2, 'scramble')
    p = args[0]
    if not isinstance(p, PointSet):
        raise err('MATLAB:scramble:invalidInput', 'The first input must be a sobolset or a haltonset.', 'scramble')
    q = p.value_copy()
    t = sval(args[1], 'type', 'scramble') if len(args) > 1 else ('MatousekAffineOwen' if p.kind == 'sobol' else 'RR2')
    if t.lower() == 'clear':
        q.scramble_method, q.seed = None, None
        return q
    want = 'matousekaffineowen' if p.kind == 'sobol' else 'rr2'
    if t.lower() != want:
        raise err('MATLAB:scramble:invalidType', f"A {p.cls} is scrambled by '{'MatousekAffineOwen' if p.kind == 'sobol' else 'RR2'}' (or 'clear').", 'scramble')
    q.scramble_method = 'MatousekAffineOwen' if p.kind == 'sobol' else 'RR2'
    q.seed = int(_rs().randint(0, 2 ** 31 - 1))
    return q


# ---- sample-based measures -------------------------------------------------------------------------------

def _xy(args, fn, multi=False):
    """X (n-by-K) and Y (n, or n-by-m when multi) as float arrays, rows with NaN in either left out."""
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', fn)
    X = np.asarray(darr(args[0]), float)
    Y = np.asarray(darr(args[1]), float)
    if X.ndim != 2 or np.iscomplexobj(X):
        raise err(f'MATLAB:{fn}:invalidX', 'X must be a real matrix, a row per run and a column per input.', fn)
    if Y.ndim == 2 and 1 in Y.shape and not multi:
        Y = Y.reshape(-1)
    elif Y.ndim == 2 and Y.shape[0] == 1 and multi:
        Y = Y.reshape(-1, 1)
    if (Y.shape[0] if Y.ndim else 1) != X.shape[0] or (Y.ndim == 2 and not multi):
        raise err(f'MATLAB:{fn}:sizeMismatch', 'Y must have one value per row of X' + (' (or a column per output)' if multi else '') + '.', fn)
    Y2 = Y.reshape(Y.shape[0], -1)
    ok = np.all(np.isfinite(X), axis=1) & np.all(np.isfinite(Y2), axis=1)
    return X[ok], (Y[ok] if Y.ndim == 1 else Y2[ok])


def regression_measures(X, y):
    """The standardized regression coefficients (SRC), the partial correlation
    coefficients (PCC) and the R² of the least-squares fit of y on every
    column of X. With every column standardized, SRC_k is the coefficient
    beta_k, and PCC_k = beta_k / sqrt(beta_k² + (1 - R²) (R⁻¹)_kk), R the
    inputs' correlation matrix, with beta_k's sign. A constant column gets
    NaN; all do when R is singular or there are too few rows."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    m, K = X.shape
    src, pcc = np.full(K, np.nan), np.full(K, np.nan)
    sd = X.std(axis=0, ddof=1) if m > 1 else np.zeros(K)
    use = np.flatnonzero(sd > 0)
    sy = y.std(ddof=1) if m > 1 else 0.0
    if m < 4 or not sy > 0 or not 0 < len(use) < m - 1:
        return src, pcc, np.nan
    Z = (X[:, use] - X[:, use].mean(axis=0)) / sd[use]
    zy = (y - y.mean()) / sy
    R = Z.T @ Z / (m - 1)
    r = Z.T @ zy / (m - 1)
    try:
        L = np.linalg.cholesky(R)
    except np.linalg.LinAlgError:
        return src, pcc, np.nan
    if np.min(np.diag(L)) ** 2 <= 1e-10:
        return src, pcc, np.nan
    Rinv = linalg.cho_solve((L, True), np.eye(len(use)))
    beta = Rinv @ r
    r2 = float(r @ beta)
    denom = beta ** 2 + max(0.0, 1 - r2) * np.diag(Rinv)
    src[use] = beta
    pcc[use] = np.sign(beta) * np.sqrt(np.divide(beta ** 2, denom, out=np.zeros_like(beta), where=denom > 0))
    return src, pcc, r2


def _regression(args, nargout, which, ranks, fn):
    nargchk(args, 2, 2, fn)
    X, Y = _xy(args, fn, multi=True)
    if ranks:
        X = stats.rankdata(X, axis=0)
        Y = stats.rankdata(Y, axis=0)
    Y = Y.reshape(Y.shape[0], -1)
    res, r2s = [], []
    for j in range(Y.shape[1]):
        s, p, r2 = regression_measures(X, Y[:, j])
        res.append(s if which == 'src' else p)
        r2s.append(r2)
    M = np.column_stack(res) if res else np.zeros((X.shape[1], 0))
    if nargout > 1:
        return out(M), out(np.array(r2s).reshape(1, -1))
    return out(M)


@bi('src', nout=2)
def src(nargout, *args):
    """src(X, Y): the standardized regression coefficients of Y on the columns
    of X, a column (one per input; a column per output for several);
    [S, R2] gives the regression's R²."""
    return _regression(args, nargout, 'src', False, 'src')


@bi('srrc', nout=2)
def srrc(nargout, *args):
    """srrc(X, Y): the standardized rank regression coefficients, src of the ranks."""
    return _regression(args, nargout, 'src', True, 'srrc')


@bi('pcc', nout=2)
def pcc(nargout, *args):
    """pcc(X, Y): the partial correlation coefficients of Y with each column of X, the others accounted for."""
    return _regression(args, nargout, 'pcc', False, 'pcc')


@bi('prcc', nout=2)
def prcc(nargout, *args):
    """prcc(X, Y): the partial rank correlation coefficients, pcc of the ranks."""
    return _regression(args, nargout, 'pcc', True, 'prcc')


def first_order_index(x, y, bins=None):
    """S1 = Var(E[y | x]) / Var(y), estimated by binning: the rows sorted by x
    and cut into bins of equal count (the square root of the rows, 4 to 50),
    the variance of the bin means over the variance of y, less the bins/n
    that the noise in the bin means adds on average, within [0, 1]."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = len(x)
    if m < 10:
        return np.nan
    order = np.argsort(x, kind='stable')
    if x[order[0]] == x[order[-1]]:
        return np.nan
    mean = y.mean()
    total = np.mean((y - mean) ** 2)
    if not total > 0:
        return np.nan
    B = bins or max(4, min(50, math.floor(math.sqrt(m) + 0.5)))
    ys = y[order]
    between = 0.0
    for b in range(B):
        lo, hi = b * m // B, (b + 1) * m // B
        if hi > lo:
            between += (hi - lo) * (ys[lo:hi].mean() - mean) ** 2
    return float(min(1.0, max(0.0, between / m / total - B / m)))


@bi('firstorderindex')
def firstorderindex(nargout, *args):
    """firstorderindex(X, Y): a first-order Sobol index of each input from any
    sample, by binning; firstorderindex(X, Y, 'Bins', b)."""
    pos, opts = _opts(args, ('bins',), 'firstorderindex')
    X, y = _xy(pos, 'firstorderindex')
    b = _int_opt(opts, 'bins', None, 'firstorderindex', 2)
    return out(np.array([first_order_index(X[:, k], y, b) for k in range(X.shape[1])]).reshape(-1, 1))


def _easi(x, y, harmonics=4):
    y = np.asarray(y, dtype=float)
    n = len(y)
    ys = y[np.argsort(np.asarray(x, dtype=float), kind='stable')]
    folded = np.concatenate([ys[0::2], ys[1::2][::-1]])
    F = np.fft.rfft(folded - folded.mean())
    P = F.real ** 2 + F.imag ** 2
    top = len(P) - 2
    s = P[1:min(harmonics, top) + 1].sum() / P[1:top + 1].sum()
    lam = 2 * harmonics / n
    return float(s), float(s - lam / (1 - lam) * (1 - s))


@bi('easi', nout=2)
def easi(nargout, *args):
    """[S1c, S1] = easi(X, Y): EASI's first-order index of each input from any
    sample, with Tissot and Prieur's correction (S1c) and without (S1);
    'Harmonics' (4)."""
    pos, opts = _opts(args, ('harmonics',), 'easi')
    X, y = _xy(pos, 'easi')
    if len(y) < 8:
        raise err('MATLAB:easi:tooFew', 'EASI needs at least 8 runs.', 'easi')
    H = _int_opt(opts, 'harmonics', 4, 'easi')
    r = [_easi(X[:, k], y, H) for k in range(X.shape[1])]
    s1 = np.array([a for a, _ in r]).reshape(-1, 1)
    s1c = np.array([b for _, b in r]).reshape(-1, 1)
    return (out(s1c), out(s1)) if nargout > 1 else out(s1c)


def kde_bandwidth(v, fallback=None):
    """Silverman's rule, 0.9 min(sd, IQR/1.34) n^(-1/5), as KernelDensity.jl has it."""
    n = len(v)
    if n <= 1:
        return 0.9 if fallback is None else fallback
    sd = np.std(v, ddof=1)
    width = min(sd, (np.quantile(v, 0.75) - np.quantile(v, 0.25)) / 1.34)
    if width == 0:
        if sd == 0 and fallback is not None:
            return fallback
        width = sd if sd > 0 else 1.0
    return 0.9 * width * n ** -0.2


def kde(v, npoints=2048, fallback=None):
    """A Gaussian kernel density estimate as KernelDensity.jl makes one:
    linear binning, smoothing in Fourier space, a quadratic B-spline to read
    it anywhere. Returns (lo, hi, step, spline coefficients)."""
    v = np.asarray(v, dtype=float)
    bw = kde_bandwidth(v, fallback)
    lo, hi = v.min() - 4 * bw, v.max() + 4 * bw
    s = (hi - lo) / (npoints - 1)
    mid = lo + np.arange(npoints) * s
    mid[-1] = hi
    k = np.searchsorted(mid, v)
    ainc, w = 1 / (s * s), 1 / len(v)
    grid = np.bincount(k - 1, (mid[k] - v) * ainc * w, npoints) + np.bincount(k, (v - mid[k - 1]) * ainc * w, npoints)
    f = np.fft.rfft(grid)
    t = np.arange(len(f)) * (-2 * np.pi / (s * npoints))
    dens = np.maximum(np.fft.irfft(f * np.exp(-bw * bw / 2 * t * t), npoints), 0)
    c = np.empty(npoints + 2)
    c[1], c[npoints] = dens[0], dens[-1]
    rhs = dens[1:-1].copy()
    rhs[0] -= c[1] / 8
    rhs[-1] -= c[npoints] / 8
    band = np.array([np.full(npoints - 2, 0.125), np.full(npoints - 2, 0.75), np.full(npoints - 2, 0.125)])
    c[2:npoints] = linalg.solve_banded((1, 1), band, rhs)
    c[0], c[npoints + 1] = 2 * c[1] - c[2], 2 * c[npoints] - c[npoints - 1]
    return lo, hi, s, c


def kde_pdf(k, xs):
    lo, hi, s, c = k
    n = len(c) - 2
    xs = np.asarray(xs, dtype=float)
    res = np.zeros(len(xs))
    inside = (xs >= lo) & (xs <= hi)
    xi = (xs[inside] - lo) / s + 1
    xm = np.where(xi < n + 0.5, np.floor(xi + 0.5), np.ceil(xi + 0.5) - 1).astype(int)
    d = xi - xm
    res[inside] = (d - 0.5) ** 2 / 2 * c[xm - 1] + (0.75 - d * d) * c[xm] + (d + 0.5) ** 2 / 2 * c[xm + 1]
    return res


def _delta_classes(n):
    e = 2 / (7 + math.tanh((1500 - n) / 500))
    return min(math.ceil(n ** e), 48)


def _delta_once(x, y, ygrid, cut):
    if np.all(y == y[0]):
        return 0.0
    fallback = kde_bandwidth(y)
    fy = kde_pdf(kde(y), ygrid)
    rank = stats.rankdata(x, method='min')
    total = 0.0
    for j in range(len(cut) - 1):
        members = y[(rank > cut[j]) & (rank <= cut[j + 1])]
        if len(members):
            diff = np.abs(fy - kde_pdf(kde(members, fallback=fallback), ygrid))
            total += len(members) * np.sum(np.diff(ygrid) * (diff[:-1] + diff[1:])) / 2
    return total / (2 * len(y))


def delta_moment(x, y, resamples, conf=0.95, grid=2048):
    """Borgonovo's δ (Plischke, Borgonovo and Smith 2013): (δ, adjusted δ, low, high)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    M = _delta_classes(n)
    cut = np.arange(M + 1) * n / M
    ygrid = np.linspace(y.min(), y.max(), grid)
    delta = _delta_once(x, y, ygrid, cut)
    if not len(resamples):
        return delta, delta, np.nan, np.nan
    bs = np.array([_delta_once(x[r], y[r], ygrid, cut) for r in resamples])
    adjusted = 2 * delta - bs.mean()
    band = stats.norm.ppf(0.5 + conf / 2) * bs.std(ddof=1) / math.sqrt(len(bs))
    return delta, adjusted, adjusted - band, adjusted + band


def _names(K, given, fn):
    if given is None:
        return [f'x{k + 1}' for k in range(K)]
    names = text_list(given) if not isinstance(given, Char) else ([given.str()] if given.a.shape[0] <= 1 else given.row_strs())
    if len(names) != K:
        raise err(f'MATLAB:{fn}:invalidNames', f'Give {K} names, one per input.', fn)
    if len(set(names)) != len(names):
        raise err(f'MATLAB:{fn}:invalidNames', 'The input names must differ.', fn)
    return names


def _table(cols, rownames):
    from .tables import Table
    names = [c[0] for c in cols]
    return Table([np.asarray(c[1], float).reshape(-1, 1) for c in cols], names, rownames, len(rownames))


@bi('deltamoment')
def deltamoment(nargout, *args):
    """deltamoment(X, Y): Borgonovo's moment-independent δ of each input, how
    far knowing it moves the output's whole distribution; a table of δ, the
    bootstrap-adjusted δ and its interval. Read on the output's normal scores.
    'Resamples' (100), 'Confidence' (0.95), 'Names'."""
    pos, opts = _opts(args, ('resamples', 'confidence', 'names'), 'deltamoment')
    X, y = _xy(pos, 'deltamoment')
    n, K = X.shape
    if n < 20:
        raise err('MATLAB:deltamoment:tooFew', 'δ needs at least 20 runs.', 'deltamoment')
    R = _int_opt(opts, 'resamples', 100, 'deltamoment', 0)
    conf = _num_opt(opts, 'confidence', 0.95, 'deltamoment')
    names = _names(K, opts.get('names'), 'deltamoment')
    scores = stats.norm.ppf((stats.rankdata(y) - 0.5) / n)
    rs = _rs()
    rows = []
    for k in range(K):
        x = X[:, k]
        if np.all(x == x[0]):
            rows.append((np.nan,) * 4)
            continue
        rows.append(delta_moment(x, scores, rs.randint(0, n, size=(R, n)) if R else [], conf))
    r = np.array(rows).reshape(K, 4)
    return _table([('Delta', r[:, 0]), ('Adjusted', r[:, 1]), ('Lower', r[:, 2]), ('Upper', r[:, 3])], names)


def mutual_information(x, y, shuffles, conf=0.95):
    """Mutual information in bits from histograms of √n bins a side, its chance level (the conf quantile of the
    same with y shuffled), and what is above that."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    bins = math.floor(math.sqrt(n) + 0.5)

    def binned(v):
        top = np.nextafter(np.nextafter(v.max(), np.inf), np.inf)
        return np.floor((v - v.min()) / ((top - v.min()) / bins)).astype(np.int64)

    def entropy(keys):
        p = np.unique(keys, return_counts=True)[1] / n
        return float(-np.sum(p * np.log2(p)))
    bx, by = binned(x), binned(y)
    hx, hy = entropy(bx), entropy(by)
    mi = hx + hy - entropy(bx * (bins + 2) + by)
    nulls = np.array([hx + hy - entropy(bx * (bins + 2) + by[s]) for s in shuffles])
    bound = float(np.quantile(nulls, conf)) if len(nulls) else np.nan
    return mi, bound, max(0.0, mi - bound)


@bi('mutualinfo')
def mutualinfo(nargout, *args):
    """mutualinfo(X, Y): the mutual information (bits) of each input with the
    output, read on ranks; a table of it, the level chance gives (Y shuffled,
    'Shuffles' times, the 'Confidence' quantile) and what is above that."""
    pos, opts = _opts(args, ('shuffles', 'confidence', 'names'), 'mutualinfo')
    X, y = _xy(pos, 'mutualinfo')
    n, K = X.shape
    if n < 4:
        raise err('MATLAB:mutualinfo:tooFew', 'Mutual information needs at least 4 runs.', 'mutualinfo')
    S = _int_opt(opts, 'shuffles', 100, 'mutualinfo', 0)
    conf = _num_opt(opts, 'confidence', 0.95, 'mutualinfo')
    names = _names(K, opts.get('names'), 'mutualinfo')
    rs = _rs()
    ry = stats.rankdata(y)
    rows = []
    for k in range(K):
        x = X[:, k]
        if np.all(x == x[0]):
            rows.append((np.nan,) * 3)
            continue
        rows.append(mutual_information(stats.rankdata(x), ry, [rs.permutation(n) for _ in range(S)], conf))
    r = np.array(rows).reshape(K, 3)
    return _table([('MI', r[:, 0]), ('Chance', r[:, 1]), ('Above', r[:, 2])], names)


def _pawn(x, y, slides=10):
    edges = np.quantile(x, np.minimum(1, np.arange(slides + 1) * (1 / slides)))
    ks = []
    for s in range(slides):
        inside = (x >= edges[s]) & (x < edges[s + 1])
        if inside.any():
            ks.append(stats.ks_2samp(y[inside], y).statistic)
    ks = np.array(ks) if ks else np.array([np.nan])
    return [ks.min(), ks.mean(), np.median(ks), ks.max(), ks.std(), ks.std() / ks.mean()]


@bi('pawn')
def pawn(nargout, *args):
    """pawn(X, Y): PAWN (Pianosi and Wagener): each input cut into 'Slides'
    (10) slices of equal count, the Kolmogorov-Smirnov distance between the
    output's distribution in each and overall; a table of the distances'
    minimum, mean, median (the index usually reported), maximum, standard
    deviation and coefficient of variation."""
    pos, opts = _opts(args, ('slides', 'names'), 'pawn')
    X, y = _xy(pos, 'pawn')
    n, K = X.shape
    S = _int_opt(opts, 'slides', 10, 'pawn', 2)
    if n < 2 * S:
        raise err('MATLAB:pawn:tooFew', f'PAWN with {S} slides needs at least {2 * S} runs.', 'pawn')
    names = _names(K, opts.get('names'), 'pawn')
    r = np.array([_pawn(X[:, k], y, S) for k in range(K)]).reshape(K, 6)
    return _table([('Minimum', r[:, 0]), ('Mean', r[:, 1]), ('Median', r[:, 2]), ('Maximum', r[:, 3]),
                   ('StDev', r[:, 4]), ('CV', r[:, 5])], names)


@bi('discrepancyshares')
def discrepancyshares(nargout, *args):
    """discrepancyshares(X, Y): each input's share of the discrepancy (Puy, Roy
    and Saltelli): the discrepancy of the points (input, output) on their
    ranks, over the sum of every input's; an input the output does not
    depend on leaves the points spread evenly, and has a small one. 'Method':
    'WD' (wrap-around, the default), 'CD', 'MD' or 'L2-star'."""
    from scipy.stats import qmc
    pos, opts = _opts(args, ('method',), 'discrepancyshares')
    X, y = _xy(pos, 'discrepancyshares')
    method = {'wd': 'WD', 'cd': 'CD', 'md': 'MD', 'l2-star': 'L2-star'}.get((opt_str(opts.get('method', Char.of('WD'))) or '').lower())
    if method is None:
        raise err('MATLAB:discrepancyshares:invalidMethod', "'Method' is 'WD', 'CD', 'MD' or 'L2-star'.", 'discrepancyshares')
    n, K = X.shape
    if n < 2 or np.all(y == y[0]):
        return out(np.full((K, 1), np.nan))
    v = (stats.rankdata(y) - 0.5) / n
    v = (v - v.min()) / (v.max() - v.min())
    raw = np.array([qmc.discrepancy(np.column_stack([(stats.rankdata(X[:, k]) - 0.5) / n, v]), method=method) for k in range(K)])
    return out((raw / raw.sum()).reshape(-1, 1))


@bi('rsa', nout=2)
def rsa(nargout, *args):
    """[T, chance] = rsa(X, Y, threshold): regional sensitivity analysis
    (Monte Carlo filtering): the runs whose output is above the threshold
    (the mean of Y unless given) against the rest; a table of each input's
    Kolmogorov-Smirnov distance between its two distributions and the test's
    p-value. chance has the mean and standard deviation of the distance for
    'Dummies' (10) uniform inputs the output never saw."""
    pos, opts = _opts(args, ('dummies', 'names'), 'rsa')
    X, y = _xy(pos[:2], 'rsa')
    n, K = X.shape
    t = float(num(pos[2])) if len(pos) > 2 else float(np.mean(y))
    above = y > t
    if not 0 < int(above.sum()) < n:
        raise err('MATLAB:rsa:oneGroup', 'Every run is on one side of the threshold: there are not two groups to compare.', 'rsa')
    D = _int_opt(opts, 'dummies', 10, 'rsa', 0)
    names = _names(K, opts.get('names'), 'rsa')
    tests = [stats.ks_2samp(X[above, k], X[~above, k]) for k in range(K)]
    T = _table([('KS', [t_.statistic for t_ in tests]), ('pValue', [t_.pvalue for t_ in tests])], names)
    if nargout > 1:
        rs = _rs()
        chance = [stats.ks_2samp(u[above], u[~above]).statistic for u in rs.random_sample((D, n))]
        return T, out(np.array([[np.mean(chance) if D else np.nan, np.std(chance, ddof=1) if D > 1 else np.nan]]))
    return T


# ---- designed methods: the designs ------------------------------------------------------------------------
#
# Each design is a list of runs X (rows, in the unit hypercube) and a struct D
# that says how they were laid out; the indices function reads D and the
# outputs Y of the runs in that order. The functions below are the arithmetic
# of Kompartment's gsa.js and salib.js; nxt() is the stream of uniforms a
# design draws from (one at a time, in the order Kompartment draws them), and
# the columns a method samples freely are Latin hypercube columns.

def _lhs_cols(K, n, rs):
    """K Latin hypercube columns of n points each (an n-by-K array)."""
    return _lhs(n, K, True, rs) if n else np.zeros((0, K))


def sinpi(x):
    """sin(πx), reduced exactly first, as Julia's sinpi."""
    x = np.asarray(x, float)
    r = np.mod(x, 2.0)
    return np.where(r < 0.25, np.sin(np.pi * r),
           np.where(r < 0.75, np.cos(np.pi * (r - 0.5)),
           np.where(r < 1.25, -np.sin(np.pi * (r - 1)),
           np.where(r < 1.75, -np.cos(np.pi * (r - 1.5)), np.sin(np.pi * (r - 2))))))


def _perm(n, nxt):
    """A uniformly random permutation of 0..n-1, Fisher-Yates from the end."""
    p = list(range(n))
    for i in range(n - 1, 0, -1):
        j = math.floor(nxt() * (i + 1))
        p[i], p[j] = p[j], p[i]
    return p


def morris_walks(K, trajectories, points, levels, nxt):
    """GlobalSensitivity.jl's Morris design: random walks, each step one input one level up or down."""
    u = np.empty((trajectories * points, K))
    at = np.zeros(K, np.int64)
    for t in range(trajectories):
        for k in range(K):
            at[k] = math.floor(nxt() * levels)
        for s in range(points):
            j = math.floor(nxt() * K)
            at[j] += -1 if nxt() < 0.5 else 1
            if at[j] > levels - 1:
                at[j] -= 2
            elif at[j] < 0:
                at[j] += 2
            u[t * points + s] = (at + 0.5) / levels
    return u


def morris_trajectory(K, p, nxt):
    """One of SALib's Morris trajectories, in levels: K + 1 rows of K."""
    half = p // 2
    order = list(range(K))
    for i in range(K - 1, 0, -1):
        j = math.floor(nxt() * (i + 1))
        order[i], order[j] = order[j], order[i]
    direction = [-1 if nxt() < 0.5 else 1 for _ in range(K)]
    at = [math.floor(nxt() * half) for _ in range(K)]
    for k in range(K):
        if direction[k] < 0:
            at[k] += half
    rows = [list(at)]
    for k in order:
        at[k] += direction[k] * half
        rows.append(list(at))
    return np.array(rows, float)


def trajectory_distance(m, l):
    """SALib's distance between two trajectories, summed point to point, held in single precision."""
    if m.shape == l.shape and np.array_equal(m, l):
        return 0.0
    d = np.sqrt(((m[:, None, :] - l[None, :, :]) ** 2).sum(axis=2))
    s = 0.0
    for a in range(d.shape[0]):
        for b in range(d.shape[1]):
            s += d[a, b]
    return float(np.float32(s))


def optimal_trajectories(candidates, k):
    """The k most spread-out candidates: SALib's local search (Ruano, Ewald and Kolar 2012)."""
    N = len(candidates)
    if k >= N:
        return list(range(N))
    D = np.zeros((N, N))
    for j in range(N):
        for l in range(j + 1, N):
            D[j, l] = D[l, j] = trajectory_distance(candidates[j], candidates[l])

    def spread(idx):
        s = 0.0
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                s += D[idx[a], idx[b]] ** 2
        return math.sqrt(s)

    def last_max(values):
        best = 0
        for i in range(1, len(values)):
            if values[i] >= values[best]:
                best = i
        return best
    by_row = [sorted(range(N), key=lambda c, r=r: (D[r, c], c)) for r in range(N)]
    tried, scores = [], []
    for i in range(1, k):
        sets = [list(reversed(order[N - i:])) + [r] for r, order in enumerate(by_row)]
        best = sets[last_max([spread(s) for s in sets])]
        for _ in range(1, k - i):
            grown = [best + [c] for c in range(N) if c not in best]
            best = grown[last_max([spread(s) for s in grown])]
        tried.append(best)
        scores.append(spread(best))
    return sorted(tried[last_max(scores)])


def morris_indices(y, u, trajectories, points, relative=False):
    """The elementary effects of a Morris design, by input: (mean, mean of magnitudes, variance, count, effects)."""
    K = u.shape[1]
    effects = [[] for _ in range(K)]
    for t in range(trajectories):
        y1 = y[t * points]
        for j in range(t * points, (t + 1) * points - 1):
            y2 = y1
            d = u[j + 1] - u[j]
            moved = np.flatnonzero(np.abs(d) > 0)
            changed = int(moved[0]) if moved.size else -1
            dl = 0.0
            for v in d:
                dl += v
            y1 = y[j + 1]
            if not relative:
                e = (y1 - y2) / dl if dl != 0 else math.nan
            else:
                e = (y1 - y2) / (y2 * dl) if dl > 0 else (y1 - y2) / (y1 * dl) if dl != 0 else math.nan
            if changed >= 0:
                effects[changed].append(e)
    mean = np.full(K, np.nan)
    star = np.full(K, np.nan)
    var = np.full(K, np.nan)
    count = np.zeros(K)
    for k in range(K):
        e = np.array(effects[k])
        count[k] = e.size
        if e.size:
            mean[k] = e.mean()
            star[k] = np.abs(e).mean()
            var[k] = e.var(ddof=1) if e.size > 1 else np.nan
    return mean, star, var, count, effects


def sobol_layout(K, n, A, B, second):
    """One block of Saltelli's design: A, B, then A with each column from B, then (second) B with each from A."""
    blocks = [A, B]
    for j in range(K):
        AB = A.copy()
        AB[:, j] = B[:, j]
        blocks.append(AB)
    if second:
        for j in range(K):
            BA = B.copy()
            BA[:, j] = A[:, j]
            blocks.append(BA)
    return np.vstack(blocks)


def _total_effect(estimator, fA, a, n):
    if estimator == 'homma1996':
        m = fA.sum() / n
        ss = np.sum((fA - m) ** 2)
        return ss / (n - 1) - np.sum(fA * a) / n + m ** 2
    if estimator == 'sobol2007':
        return np.sum(fA * (fA - a)) / n
    if estimator == 'janon2014':
        sq = np.sum(fA ** 2 + a ** 2)
        sm = np.sum(fA + a)
        dot = np.sum(fA * a)
        half = np.sum((fA + a) / 2)
        half_sq = np.sum((fA ** 2 + a ** 2) / 2)
        first = sq / (2 * n) - (sm / (2 * n)) ** 2
        numr = dot / n - (half / n) ** 2
        den = half_sq / n - (half / n) ** 2
        return first * (1 - numr / den)
    return np.sum((fA - a) ** 2) / (2 * n)


def sobol_indices(y, K, n, second=False, blocks=1, estimator='jansen1999', conf=0.95):
    """S1, ST, S2 (K-by-K, upper triangle) and, with blocks, their half-widths from the spread between blocks."""
    step = 2 * K + 2 if second else K + 2
    S1s, STs, S2s = [], [], []
    for b in range(blocks):
        base = b * step * n
        fA = y[base:base + n]
        fB = y[base + n:base + 2 * n]
        vary = np.var(y[base:base + 2 * n], ddof=1)
        V = np.empty(K)
        E = np.empty(K)
        for k in range(K):
            a = y[base + (2 + k) * n:base + (3 + k) * n]
            V[k] = np.sum(fB * (a - fA)) / n
            E[k] = _total_effect(estimator, fA, a, n)
        S1s.append(V / vary)
        STs.append(E / vary)
        if second:
            S2 = np.full((K, K), np.nan)
            for k in range(K):
                bk = y[base + (2 + K + k) * n:base + (3 + K + k) * n]
                for j in range(k + 1, K):
                    aj = y[base + (2 + j) * n:base + (3 + j) * n]
                    S2[k, j] = (np.sum(bk * aj - fA * fB) / n - (V[k] + V[j])) / vary
            S2s.append(S2)
    if blocks == 1:
        return S1s[0], STs[0], (S2s[0] if second else None), None, None, None
    z = stats.norm.ppf((1 + conf) / 2)

    def pool(lst):
        a = np.array(lst)
        return a.mean(axis=0), z * a.std(axis=0, ddof=1) / math.sqrt(len(lst))
    S1, S1ci = pool(S1s)
    ST, STci = pool(STs)
    S2, S2ci = pool(S2s) if second else (None, None)
    return S1, ST, S2, S1ci, STci, S2ci


def sobol_bootstrap(y, K, n, second, idx, conf=0.95):
    """SALib's bootstrap interval on the indices of one Saltelli design: the
    rows of A, B and every A_B resampled together (idx: n-by-R, a column per
    resample), the output standardised over the design."""
    R = idx.shape[1]
    per = (2 * K + 2 if second else K + 2) * n
    m = y[:per].mean()
    sd = math.sqrt(np.var(y[:per]))
    Y = (y[:per] - m) / sd
    blk = Y.reshape(-1, n)
    A, B = blk[0], blk[1]
    z = stats.norm.ppf(0.5 + conf / 2)
    vars_ = []
    for r in range(R):
        rows = idx[:, r]
        ab = np.concatenate([A[rows], B[rows]])
        vars_.append(np.var(ab))

    def first(rows, v, ab):
        return np.sum(B[rows] * (ab[rows] - A[rows])) / len(rows) / v
    S1ci, STci = np.empty(K), np.empty(K)
    for k in range(K):
        AB = blk[2 + k]
        f = np.empty(R)
        t = np.empty(R)
        for r in range(R):
            rows = idx[:, r]
            f[r] = first(rows, vars_[r], AB)
            t[r] = 0.5 * np.sum((A[rows] - AB[rows]) ** 2) / len(rows) / vars_[r]
        S1ci[k] = z * f.std(ddof=1)
        STci[k] = z * t.std(ddof=1)
    S2ci = None
    if second:
        S2ci = np.full((K, K), np.nan)
        for j in range(K):
            for k in range(j + 1, K):
                BAj, ABk, ABj = blk[2 + K + j], blk[2 + k], blk[2 + j]
                s2 = np.empty(R)
                for r in range(R):
                    rows = idx[:, r]
                    s2[r] = (np.sum(BAj[rows] * ABk[rows] - A[rows] * B[rows]) / len(rows) / vars_[r]
                             - first(rows, vars_[r], ABj) - first(rows, vars_[r], ABk))
                S2ci[j, k] = z * s2.std(ddof=1)
    return S1ci, STci, S2ci


def efast_samples(n, M=4):
    N = max(int(math.floor(n + 0.5)), 4 * M * M + 1)
    while True:
        w = (N - 1) // (2 * M)
        if w // (2 * M) >= 1 and M * w <= N // 2 - 1:
            return N
        N += 1


def efast_frequencies(K, N, M=4):
    omega = [(N - 1) // (2 * M)]
    m = omega[0] // (2 * M)
    if m >= K - 1:
        r = [1.0] if K - 1 == 1 else [1 + i * (m - 1) / (K - 2) for i in range(K - 1)]
        omega += [math.floor(v) for v in r]
    else:
        omega += [(i % m) + 1 for i in range(K - 1)]
    return omega


def efast_design(K, N, M, phases):
    omega = efast_frequencies(K, N, M)
    u = np.empty((K * N, K))
    s = 2 / N * np.arange(N)
    for i in range(K):
        temp = [omega[k + 1] for k in range(i)] + [omega[0]] + [omega[k] for k in range(i + 1, K)]
        for j in range(K):
            u[i * N:(i + 1) * N, j] = 0.5 + (1 / math.pi) * np.arcsin(sinpi(temp[j] * s + phases[i]))
    return u, omega


def _power(y):
    F = np.fft.rfft(y - y.mean())
    return F.real ** 2 + F.imag ** 2


def efast_indices(y, K, N, M, omega):
    S1, ST = np.empty(K), np.empty(K)
    w = omega[0]
    last = N // 2 - 1
    for i in range(K):
        P = _power(y[i * N:(i + 1) * N])
        z = P[1:last + 1].sum()
        first = sum(P[p * w] for p in range(1, M + 1))
        low = P[1:w // 2 + 1].sum()
        S1[i] = first / z
        ST[i] = 1 - low / z
    return S1, ST


def rbdfast_design(K, N, perms):
    s0 = np.linspace(-math.pi, math.pi, N)
    s0[-1] = math.pi
    S = np.column_stack([s0[np.asarray(p)] for p in perms]) if K else np.zeros((N, 0))
    return 0.5 + np.arcsin(np.sin(S)) / math.pi, S


def rbdfast_indices(y, S, H=6):
    K = S.shape[1]
    res = np.empty(K)
    for k in range(K):
        order = np.argsort(S[:, k], kind='stable')
        P = _power(y[order])
        end = len(P) - 1
        V = 2 * P[1:end].sum() + P[end]
        res[k] = 2 * P[1:H + 1].sum() / V
    return res


def unskew(S1, M, N):
    lam = 2 * M / N
    return S1 - lam / (1 - lam) * (1 - S1)


def hadamard(k):
    h = np.ones((k, k), np.int64)
    if k >= 2:
        h[1, 1] = -1
    bot = right = 2
    while bot < k:
        h[bot:2 * bot, :right] = h[:bot, :right]
        h[:bot, right:2 * right] = h[:bot, :right]
        h[bot:2 * bot, right:2 * right] = -h[:bot, :right]
        bot *= 2
        right *= 2
    return h


def ff_design(K, low=0.05, high=0.95):
    k2 = 2
    while k2 < K:
        k2 *= 2
    H = hadamard(k2)
    signs = np.vstack([H, -H])
    return np.where(signs[:, :K] > 0, high, low), signs[:, :K].astype(float)


def dgsm_design(base, step=1e-3, crossed=False):
    N, K = base.shape
    per = 1 + K + (K * (K - 1) // 2 if crossed else 0)
    h = np.where(base + step < 1, step, -step)
    u = np.repeat(base, per, axis=0)
    for i in range(N):
        at = i * per
        for k in range(K):
            u[at + 1 + k, k] += h[i, k]
        if crossed:
            p = at + 1 + K
            for a in range(K):
                for b in range(a + 1, K):
                    u[p, a] += h[i, a]
                    u[p, b] += h[i, b]
                    p += 1
    return u, h, per


def dgsm_derivatives(y, N, K, per, crossed, h):
    Y = y.reshape(N, per)
    g = (Y[:, 1:1 + K] - Y[:, [0]]) / h
    Hm = None
    if crossed:
        Hm = np.zeros((N, K, K))
        p = 1 + K
        for a in range(K):
            for b in range(a + 1, K):
                d = (Y[:, p] - Y[:, 1 + a] - Y[:, 1 + b] + Y[:, 0]) / (h[:, a] * h[:, b])
                Hm[:, a, b] = d
                Hm[:, b, a] = d
                p += 1
    return g, Hm, Y[:, 0]


def dgsm_statistics(g, base, y0):
    a = g.mean(axis=0)
    absa = np.abs(g).mean(axis=0)
    asq = (g * g).mean(axis=0)
    tao = (g * g * (1 - 3 * base + base * base) / 6).mean(axis=0)
    sigma = (0.5 * base * (1 - base) * g * g).mean(axis=0)
    vary = np.var(y0, ddof=1) if len(y0) > 1 else math.nan
    return a, absa, asq, sigma, tao, asq / (math.pi ** 2 * vary)


def radial_indices(y, base, step, idx, conf=0.95):
    """Elementary effects and Jansen's total index of a radial design, with bootstrap half-widths (idx: R-by-N)."""
    N, K = base.shape
    per = K + 1
    Y = y.reshape(N, per)
    yb = Y[:, 0]
    d = yb[:, None] - Y[:, 1:]
    with np.errstate(divide='ignore', invalid='ignore'):
        ee = np.nan_to_num(d / (base - step))
    z = stats.norm.ppf(0.5 + conf / 2)
    varB = np.var(yb)
    mu = ee.mean(axis=0)
    star = np.abs(ee).mean(axis=0)
    sigma = ee.std(axis=0, ddof=1)
    ST = (d ** 2).sum(axis=0) / (2 * N) / varB
    star_ci = np.full(K, np.nan)
    st_ci = np.full(K, np.nan)
    if idx is not None:
        for k in range(K):
            star_ci[k] = z * np.abs(ee[:, k])[idx].mean(axis=1).std(ddof=1)
            at = np.array([(d[r, k] ** 2).sum() / (2 * N) / np.var(yb[r]) for r in idx])
            st_ci[k] = z * at.std(ddof=1)
    return mu, star, sigma, star_ci, ST, st_ci


def _gaussian(nxt):
    u = nxt()
    while not u > 0:
        u = nxt()
    v = nxt()
    return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * v)


def _chol(A):
    """The lower Cholesky factor, or None when A is not positive definite (as Kompartment's, pivots above 1e-14)."""
    n = A.shape[0]
    L = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1):
            s = A[i, j] - L[i, :j] @ L[j, :j]
            if i == j:
                if not s > 1e-14:
                    return None
                L[i, i] = math.sqrt(s)
            else:
                L[i, j] = s / L[j, j]
    return L


def shapley_design(K, orders, nVar, nOuter, nInner, corr, nxt):
    """Song, Nelson and Staum's design: nVar runs for the variance, then for
    each order and step the inputs not yet learnt fixed at nOuter points and
    the rest drawn nInner times given them (a Gaussian copula when corr)."""
    cache = {}

    def draw_z(m, L, mu):
        e = [_gaussian(nxt) for _ in range(m)]
        z = np.empty(m)
        for a in range(m):
            s = mu[a] if mu is not None else 0.0
            for b in range(a + 1):
                s += L[a, b] * e[b]
            z[a] = s
        return z

    def subset(idx, n):
        if corr is None:
            return [[nxt() for _ in idx] for _ in range(n)]
        key = tuple(idx)
        if key not in cache:
            cache[key] = _chol(corr[np.ix_(idx, idx)])
        L = cache[key]
        if L is None:
            raise err('MATLAB:shapleydesign:invalidCorrelation', 'The correlations between these inputs are not a valid correlation matrix.', 'shapleydesign')
        return [list(stats.norm.cdf(draw_z(len(idx), L, None))) for _ in range(n)]

    def given(plus, minus, u_minus, n):
        if corr is None:
            return [[nxt() for _ in plus] for _ in range(n)]
        z_minus = stats.norm.ppf(np.asarray(u_minus))
        D = corr[np.ix_(minus, minus)]
        Ld = _chol(D)
        if Ld is None:
            raise err('MATLAB:shapleydesign:invalidCorrelation', 'The correlations between these inputs are not a valid correlation matrix.', 'shapleydesign')
        C = corr[np.ix_(minus, plus)]
        X = linalg.solve_triangular(Ld.T, linalg.solve_triangular(Ld, C, lower=True), lower=False)
        mu = X.T @ z_minus
        cov = corr[np.ix_(plus, plus)] - C.T @ X
        cov = (cov + cov.T) / 2
        L = _chol(cov)
        eps = 1e-12
        while L is None and eps < 1:
            L = _chol(cov + eps * np.eye(len(plus)))
            eps *= 10
        if L is None:
            raise err('MATLAB:shapleydesign:notFactorised', 'A conditional covariance could not be factorised.', 'shapleydesign')
        return [list(stats.norm.cdf(draw_z(len(plus), L, mu))) for _ in range(n)]
    runs = nVar + len(orders) * (K - 1) * nOuter * nInner
    u = np.empty((runs, K))
    at = 0
    for row in subset(list(range(K)), nVar):
        u[at] = row
        at += 1
    for perm in orders:
        for j in range(1, K):
            plus, minus = list(perm[:j]), list(perm[j:])
            for fixed in subset(minus, nOuter):
                for drawn in given(plus, minus, fixed, nInner):
                    u[at, plus] = drawn
                    u[at, minus] = fixed
                    at += 1
    return u


def shapley_indices(y, K, orders, nVar, nOuter, nInner):
    Sh = np.zeros(K)
    Sh2 = np.zeros(K)
    vary = np.var(y[:nVar], ddof=1)
    at = nVar
    for perm in orders:
        prev = 0.0
        for j in range(K):
            if j == K - 1:
                Sh[perm[j]] += vary - prev
                prev = vary
                continue
            cvar = np.empty(nOuter)
            for l in range(nOuter):
                cvar[l] = np.var(y[at:at + nInner], ddof=1)
                at += nInner
            C = cvar.mean()
            d = C - prev
            Sh2[perm[j]] += np.sum((cvar - prev) ** 2) / nOuter - d * d
            Sh[perm[j]] += d
            prev = C
    m = len(orders)
    effects = Sh / m / vary
    se = np.sqrt(np.maximum(Sh2 / m / (vary * vary) / nOuter, 0))
    return effects, se


# ---- designed methods: the functions -----------------------------------------------------------------------

def _inputs(v, fn):
    """The number of inputs and their names, from a number or a list of names."""
    if isinstance(v, (Cell, Str)):
        names = text_list(v)
        if not names or len(set(names)) != len(names):
            raise err(f'MATLAB:{fn}:invalidNames', 'The input names must be distinct, and there must be some.', fn)
        return len(names), names
    K = _whole(v, 'The number of inputs', fn)
    return K, [f'x{k + 1}' for k in range(K)]


def _design(method, X, names, fields):
    d = {'Method': Char.of(method), 'Inputs': float(len(names)),
         'Names': Cell.of_list([Char.of(n) for n in names], (1, len(names))), 'Runs': float(X.shape[0])}
    for k, v in fields.items():
        d[k] = v if not isinstance(v, (bool, int, float, np.integer, np.floating)) or isinstance(v, bool) else float(v)
    return Struct.scalar(d)


def _get(D, key):
    if key not in D.f:
        raise MError('MATLAB:gsa:invalidDesign', f"The design struct has no field {key}: give the D its design function returned.")
    return D.get1(key)


def _y_for(D, Y, fn, method):
    if not isinstance(D, Struct) or D.size != 1 or 'Method' not in D.f:
        raise err(f'MATLAB:{fn}:invalidDesign', f'The first input is the design struct {method}design gives.', fn)
    m = D.get1('Method')
    if not isinstance(m, Char) or m.str() != method:
        raise err(f'MATLAB:{fn}:wrongDesign', f"This design is {m.str() if isinstance(m, Char) else '?'}'s; {fn} reads a {method}design.", fn)
    y = np.asarray(darr(Y), float)
    if y.ndim == 2 and 1 not in y.shape:
        raise err(f'MATLAB:{fn}:invalidY', 'Y must be a vector, one output per run.', fn)
    y = y.reshape(-1)
    try:
        runs = int(num(_get(D, 'Runs')))
        K = int(num(_get(D, 'Inputs')))
        names = text_list(_get(D, 'Names'))
    except MError as e:
        raise err(f'MATLAB:{fn}:invalidDesign', e.message, fn)
    if y.size != runs:
        raise err(f'MATLAB:{fn}:sizeMismatch', f'The design has {runs} runs, and Y {y.size} values.', fn)
    if not np.all(np.isfinite(y)):
        bad = np.flatnonzero(~np.isfinite(y))[:5] + 1
        raise err(f'MATLAB:{fn}:nonFinite', f'Y must be finite: run {", ".join(str(b) for b in bad)} gave NaN or Inf.', fn)
    if len(names) != K:
        raise err(f'MATLAB:{fn}:invalidDesign', f'The design has {K} inputs and {len(names)} names.', fn)
    return y, names, K


def _flat(y):
    return bool(np.all(y == y[0]))


def _ret(nargout, X, D):
    return (out(X), D) if nargout > 1 else out(X)


# Morris

@bi('morrisdesign', nout=2)
def morrisdesign(nargout, *args):
    """[X, D] = morrisdesign(K): runs for Morris's elementary effects of K
    inputs. 'Design' 'walks' (GlobalSensitivity.jl's random walks, the
    default: 'Trajectories' (10) walks of 'Points' (10) runs, each step one
    input one level) or 'trajectories' (Morris's own, as SALib samples them:
    K + 1 runs each, every input moved once by half the levels; 'Candidates'
    draws more and keeps the most spread out); 'Levels' (100)."""
    pos, opts = _opts(args, ('design', 'trajectories', 'points', 'levels', 'candidates', 'names'), 'morrisdesign')
    nargchk(pos, 1, 1, 'morrisdesign')
    K, names = _inputs(pos[0], 'morrisdesign')
    if 'names' in opts:
        names = _names(K, opts['names'], 'morrisdesign')
    kind = _text_opt(opts, 'design', 'walks', ('walks', 'trajectories'), 'morrisdesign')
    T = _int_opt(opts, 'trajectories', 10, 'morrisdesign')
    P = _int_opt(opts, 'points', 10, 'morrisdesign', 2)
    L = _int_opt(opts, 'levels', 100, 'morrisdesign', 2)
    C = _int_opt(opts, 'candidates', 0, 'morrisdesign', 0)
    nxt = _next()
    if kind == 'walks':
        X = morris_walks(K, T, P, L, nxt)
        points, levels = P, L
    else:
        if 0 < C < T:
            raise err('MATLAB:morrisdesign:fewCandidates', 'Fewer candidates than trajectories to keep; 0 keeps every one drawn.', 'morrisdesign')
        p = max(2, 2 * math.floor(L / 2 + 0.5))
        drawn = max(T, C)
        cands = [morris_trajectory(K, p, nxt) for _ in range(drawn)]
        keep = optimal_trajectories(cands, T) if drawn > T else list(range(drawn))
        X = np.vstack([(cands[c] + 0.5) / p for c in keep])
        points, levels = K + 1, p
    D = _design('morris', X, names, {'Design': Char.of(kind), 'Trajectories': T, 'Points': points, 'Levels': levels, 'X': X})
    return _ret(nargout, X, D)


@bi('morrisindices', nout=2)
def morrisindices(nargout, *args):
    """morrisindices(D, Y): the elementary effects of each input, a table of
    MuStar (the mean of their magnitudes: how much the input matters), its
    bootstrap half-width MuStarConf ('Resamples', 100), Mu (their mean, the
    direction), Sigma (their spread: a curve or an interaction) and Count.
    'Relative', true divides each effect by the output."""
    pos, opts = _opts(args, ('relative', 'resamples', 'confidence'), 'morrisindices')
    nargchk(pos, 2, 2, 'morrisindices')
    D = pos[0]
    y, names, K = _y_for(D, pos[1], 'morrisindices', 'morris')
    X = np.asarray(darr(_get(D, 'X')), float)
    T, P = int(num(_get(D, 'Trajectories'))), int(num(_get(D, 'Points')))
    R = _int_opt(opts, 'resamples', 100, 'morrisindices', 0)
    conf = _num_opt(opts, 'confidence', 0.95, 'morrisindices')
    mean, star, var, count, effects = morris_indices(y, X, T, P, _bool_opt(opts, 'relative', False))
    cols = [('MuStar', star)]
    if R > 1:
        rs = _rs()
        z = stats.norm.ppf(0.5 + conf / 2)
        ci = np.full(K, np.nan)
        for k in range(K):
            e = np.abs(np.array(effects[k]))
            if e.size >= 2:
                idx = rs.randint(0, e.size, size=(R, e.size))
                ci[k] = z * e[idx].mean(axis=1).std(ddof=1)
        cols.append(('MuStarConf', ci))
    cols += [('Mu', mean), ('Sigma', np.sqrt(var)), ('Count', count)]
    return _table(cols, names)


# Sobol

@bi('soboldesign', nout=2)
def soboldesign(nargout, *args):
    """[X, D] = soboldesign(N, K): Saltelli's design for Sobol's indices: two
    samples A and B of N runs and, for each input, A with that input's column
    from B, (K + 2)N runs; 'Second', true adds B with each column from A for
    every pair's index, (2K + 2)N. 'Blocks' repeats it for an interval;
    'Sampling' 'lhs' (the default), 'random' or 'sobol' (a scrambled Sobol
    sequence of 2K dimensions)."""
    pos, opts = _opts(args, ('second', 'blocks', 'sampling', 'names'), 'soboldesign')
    nargchk(pos, 2, 2, 'soboldesign')
    N = _whole(pos[0], 'N', 'soboldesign', 2)
    K, names = _inputs(pos[1], 'soboldesign')
    if 'names' in opts:
        names = _names(K, opts['names'], 'soboldesign')
    second = _bool_opt(opts, 'second', False)
    blocks = _int_opt(opts, 'blocks', 1, 'soboldesign')
    if blocks > 1 and blocks > N:
        raise err('MATLAB:soboldesign:tooManyBlocks', 'More blocks than samples.', 'soboldesign')
    how = _text_opt(opts, 'sampling', 'lhs', ('lhs', 'random', 'sobol'), 'soboldesign')
    rs = _rs()
    parts = []
    for _ in range(blocks):
        if how == 'lhs':
            A, B = _lhs_cols(K, N, rs), _lhs_cols(K, N, rs)
        elif how == 'random':
            A, B = rs.random_sample((N, K)), rs.random_sample((N, K))
        else:
            from scipy.stats import qmc
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                AB = qmc.Sobol(2 * K, scramble=True, seed=int(rs.randint(0, 2 ** 31 - 1))).random(N)
            A, B = AB[:, :K], AB[:, K:]
        parts.append(sobol_layout(K, N, A, B, second))
    X = np.vstack(parts)
    D = _design('sobol', X, names, {'N': N, 'Second': bool(second), 'Blocks': blocks})
    return _ret(nargout, X, D)


@bi('sobolindices', nout=3)
def sobolindices(nargout, *args):
    """[T, S2, S2conf] = sobolindices(D, Y): Sobol's first-order (S1: the share
    of the variance an input explains alone) and total (ST: the share it has a
    hand in) indices, with half-widths S1Conf and STConf from the spread
    between blocks, or a bootstrap of one block ('Resamples', 100); S2 every
    pair's index when the design has them. 'Estimator' of ST: 'jansen1999'
    (the default), 'sobol2007', 'homma1996' or 'janon2014'."""
    pos, opts = _opts(args, ('estimator', 'resamples', 'confidence'), 'sobolindices')
    nargchk(pos, 2, 2, 'sobolindices')
    D = pos[0]
    y, names, K = _y_for(D, pos[1], 'sobolindices', 'sobol')
    N, second, blocks = int(num(_get(D, 'N'))), bool(num(_get(D, 'Second'))), int(num(_get(D, 'Blocks')))
    est = _text_opt(opts, 'estimator', 'jansen1999', ('jansen1999', 'sobol2007', 'homma1996', 'janon2014'), 'sobolindices')
    R = _int_opt(opts, 'resamples', 100, 'sobolindices', 0)
    conf = _num_opt(opts, 'confidence', 0.95, 'sobolindices')
    if _flat(y):
        S1 = ST = np.full(K, np.nan)
        S2 = np.full((K, K), np.nan) if second else None
        S1ci = STci = np.full(K, np.nan)
        S2ci = S2
    else:
        S1, ST, S2, S1ci, STci, S2ci = sobol_indices(y, K, N, second, blocks, est, conf)
        if S1ci is None and R > 1:
            S1ci, STci, S2ci = sobol_bootstrap(y, K, N, second, _rs().randint(0, N, size=(N, R)), conf)
    cols = [('S1', S1), ('ST', ST)]
    if S1ci is not None:
        cols += [('S1Conf', S1ci), ('STConf', STci)]
    T = _table(cols, names)
    if nargout <= 1:
        return T

    def sym(M):
        if M is None:
            return np.zeros((0, 0))
        M = np.array(M, float)
        iu = np.triu_indices(K, 1)
        M[(iu[1], iu[0])] = M[iu]
        np.fill_diagonal(M, np.nan)
        return M
    return T, out(sym(S2)), out(sym(S2ci))


# eFAST and RBD-FAST

@bi('efastdesign', nout=2)
def efastdesign(nargout, *args):
    """[X, D] = efastdesign(N, K): the extended Fourier amplitude test's runs:
    a curve of N runs per input (raised to the next N the harmonics fit), on
    which that input oscillates fast and the others slowly; 'Harmonics' (4)."""
    pos, opts = _opts(args, ('harmonics', 'names'), 'efastdesign')
    nargchk(pos, 2, 2, 'efastdesign')
    n = _whole(pos[0], 'N', 'efastdesign', 8)
    K, names = _inputs(pos[1], 'efastdesign')
    if 'names' in opts:
        names = _names(K, opts['names'], 'efastdesign')
    M = _int_opt(opts, 'harmonics', 4, 'efastdesign')
    N = efast_samples(n, M)
    nxt = _next()
    phases = [2 * nxt() for _ in range(K)]
    X, omega = efast_design(K, N, M, phases)
    D = _design('efast', X, names, {'N': N, 'Harmonics': M, 'Omega': out(np.array(omega, float).reshape(1, -1))})
    return _ret(nargout, X, D)


@bi('efastindices')
def efastindices(nargout, *args):
    """efastindices(D, Y): eFAST's first-order (S1, the power at the input's
    frequency and its harmonics) and total (ST, one less the power at the
    others' frequencies) indices."""
    nargchk(args, 2, 2, 'efastindices')
    D = args[0]
    y, names, K = _y_for(D, args[1], 'efastindices', 'efast')
    N, M = int(num(_get(D, 'N'))), int(num(_get(D, 'Harmonics')))
    omega = [int(v) for v in np.asarray(darr(_get(D, 'Omega'))).reshape(-1)]
    S1, ST = (np.full(K, np.nan),) * 2 if _flat(y) else efast_indices(y, K, N, M, omega)
    return _table([('S1', S1), ('ST', ST)], names)


@bi('rbdfastdesign', nout=2)
def rbdfastdesign(nargout, *args):
    """[X, D] = rbdfastdesign(N, K): the random balance design: N runs along
    one periodic curve, each input in its own random order; 'Harmonics' (6)
    the indices read."""
    pos, opts = _opts(args, ('harmonics', 'names'), 'rbdfastdesign')
    nargchk(pos, 2, 2, 'rbdfastdesign')
    N = _whole(pos[0], 'N', 'rbdfastdesign', 8)
    K, names = _inputs(pos[1], 'rbdfastdesign')
    if 'names' in opts:
        names = _names(K, opts['names'], 'rbdfastdesign')
    H = _int_opt(opts, 'harmonics', 6, 'rbdfastdesign')
    if 2 * H >= N / 2:
        raise err('MATLAB:rbdfastdesign:tooManyHarmonics', 'Too many harmonics for so few runs.', 'rbdfastdesign')
    nxt = _next()
    X, S = rbdfast_design(K, N, [_perm(N, nxt) for _ in range(K)])
    D = _design('rbdfast', X, names, {'N': N, 'Harmonics': H, 'S': out(S)})
    return _ret(nargout, X, D)


@bi('rbdfastindices')
def rbdfastindices(nargout, *args):
    """rbdfastindices(D, Y): RBD-FAST's first-order index of each input (S1),
    and with Tissot and Prieur's correction for a random design's bias
    (S1Corrected)."""
    nargchk(args, 2, 2, 'rbdfastindices')
    D = args[0]
    y, names, K = _y_for(D, args[1], 'rbdfastindices', 'rbdfast')
    N, H = int(num(_get(D, 'N'))), int(num(_get(D, 'Harmonics')))
    S = np.asarray(darr(_get(D, 'S')), float).reshape(N, K)
    S1 = np.full(K, np.nan) if _flat(y) else rbdfast_indices(y, S, H)
    return _table([('S1', S1), ('S1Corrected', unskew(S1, H, N))], names)


# fractional factorial

@bi('ffdesign', nout=2)
def ffdesign(nargout, *args):
    """[X, D] = ffdesign(K): a two-level fractional factorial of resolution IV
    (the columns of a Hadamard matrix and its negative), each input at
    probability 'Low' (0.05) or 'High' (0.95): 2^ceil(log2 K) times 2 runs."""
    pos, opts = _opts(args, ('low', 'high', 'names'), 'ffdesign')
    nargchk(pos, 1, 1, 'ffdesign')
    K, names = _inputs(pos[0], 'ffdesign')
    if 'names' in opts:
        names = _names(K, opts['names'], 'ffdesign')
    lo, hi = _num_opt(opts, 'low', 0.05, 'ffdesign'), _num_opt(opts, 'high', 0.95, 'ffdesign')
    if not 0 < lo < hi < 1:
        raise err('MATLAB:ffdesign:invalidLevels', 'The two levels must be probabilities, the low one below the high.', 'ffdesign')
    X, signs = ff_design(K, lo, hi)
    D = _design('ff', X, names, {'Signs': out(signs), 'Low': lo, 'High': hi})
    return _ret(nargout, X, D)


@bi('ffindices', nout=2)
def ffindices(nargout, *args):
    """[T, I] = ffindices(D, Y): each input's main effect (half the difference
    between the output's mean with it high and with it low) and its square;
    I every pair's interaction effect (aliased with others in this design)."""
    nargchk(args, 2, 2, 'ffindices')
    D = args[0]
    y, names, K = _y_for(D, args[1], 'ffindices', 'ff')
    signs = np.asarray(darr(_get(D, 'Signs')), float)
    rows = signs.shape[0]
    main = signs.T @ y / rows
    T = _table([('Main', main), ('Squared', main ** 2)], names)
    if nargout <= 1:
        return T
    I = np.full((K, K), np.nan)
    for b in range(K):
        for a in range(b):
            I[a, b] = I[b, a] = float(np.sum(y * signs[:, a] * signs[:, b]) / rows)
    return T, out(I)


# DGSM

@bi('dgsmdesign', nout=2)
def dgsmdesign(nargout, *args):
    """[X, D] = dgsmdesign(N, K): derivative-based measures' runs: N points
    (a Latin hypercube) and each moved by 'Step' (0.001, in probability) along
    every input, K + 1 runs a point; 'Crossed', true adds every pair."""
    pos, opts = _opts(args, ('step', 'crossed', 'names'), 'dgsmdesign')
    nargchk(pos, 2, 2, 'dgsmdesign')
    N = _whole(pos[0], 'N', 'dgsmdesign', 2)
    K, names = _inputs(pos[1], 'dgsmdesign')
    if 'names' in opts:
        names = _names(K, opts['names'], 'dgsmdesign')
    step = _num_opt(opts, 'step', 1e-3, 'dgsmdesign')
    if not 0 < step < 0.5:
        raise err('MATLAB:dgsmdesign:invalidStep', 'The step must be a small probability.', 'dgsmdesign')
    crossed = _bool_opt(opts, 'crossed', False)
    base = _lhs_cols(K, N, _rs())
    X, h, per = dgsm_design(base, step, crossed)
    D = _design('dgsm', X, names, {'N': N, 'Step': step, 'Crossed': bool(crossed), 'Base': out(base), 'H': out(h)})
    return _ret(nargout, X, D)


@bi('dgsmindices', nout=2)
def dgsmindices(nargout, *args):
    """[T, C] = dgsmindices(D, Y): the derivative of the output along each
    input, per unit probability: Bound (nu/(pi^2 Var y), an upper bound on the
    total Sobol index), Nu (the mean squared derivative) with its bootstrap
    half-width NuConf, NuSd, Mean, AbsMean, and GlobalSensitivity.jl's Sigma
    and Tau; C every pair's mean squared second derivative (crossed designs)."""
    pos, opts = _opts(args, ('resamples', 'confidence'), 'dgsmindices')
    nargchk(pos, 2, 2, 'dgsmindices')
    D = pos[0]
    y, names, K = _y_for(D, pos[1], 'dgsmindices', 'dgsm')
    N = int(num(_get(D, 'N')))
    crossed = bool(num(_get(D, 'Crossed')))
    base = np.asarray(darr(_get(D, 'Base')), float).reshape(N, K)
    h = np.asarray(darr(_get(D, 'H')), float).reshape(N, K)
    per = 1 + K + (K * (K - 1) // 2 if crossed else 0)
    R = _int_opt(opts, 'resamples', 100, 'dgsmindices', 0)
    conf = _num_opt(opts, 'confidence', 0.95, 'dgsmindices')
    g, Hm, y0 = dgsm_derivatives(y, N, K, per, crossed, h)
    a, absa, asq, sigma, tao, bound = dgsm_statistics(g, base, y0)
    sq = g * g
    sd = sq.std(axis=0)
    ci = np.full(K, np.nan)
    if R > 1:
        rs = _rs()
        z = stats.norm.ppf(0.5 + conf / 2)
        for k in range(K):
            idx = rs.randint(0, N, size=(R, N))
            ci[k] = z * sq[:, k][idx].mean(axis=1).std(ddof=1)
    T = _table([('Bound', bound), ('Nu', asq), ('NuConf', ci), ('NuSd', sd), ('Mean', a), ('AbsMean', absa),
                ('Sigma', sigma), ('Tau', tao)], names)
    if nargout <= 1:
        return T
    if Hm is None:
        return T, out(np.zeros((0, 0)))
    C = (Hm * Hm).mean(axis=0)
    np.fill_diagonal(C, np.nan)
    return T, out(C)


# radial one-at-a-time

@bi('radialdesign', nout=2)
def radialdesign(nargout, *args):
    """[X, D] = radialdesign(N, K): Campolongo, Saltelli and Cariboni's radial
    design: N base points (a Latin hypercube), each moved one input at a time
    to a second point's value, N(K + 1) runs."""
    pos, opts = _opts(args, ('names',), 'radialdesign')
    nargchk(pos, 2, 2, 'radialdesign')
    N = _whole(pos[0], 'N', 'radialdesign', 2)
    K, names = _inputs(pos[1], 'radialdesign')
    if 'names' in opts:
        names = _names(K, opts['names'], 'radialdesign')
    rs = _rs()
    base, step = _lhs_cols(K, N, rs), _lhs_cols(K, N, rs)
    X = np.repeat(base, K + 1, axis=0)
    for j in range(N):
        for k in range(K):
            X[j * (K + 1) + 1 + k, k] = step[j, k]
    D = _design('radial', X, names, {'N': N, 'Base': out(base), 'Perturbed': out(step)})
    return _ret(nargout, X, D)


@bi('radialindices')
def radialindices(nargout, *args):
    """radialindices(D, Y): from a radial design, Jansen's total index (ST)
    and the elementary effects' MuStar, Mu and Sigma, with bootstrap
    half-widths STConf and MuStarConf ('Resamples', 100)."""
    pos, opts = _opts(args, ('resamples', 'confidence'), 'radialindices')
    nargchk(pos, 2, 2, 'radialindices')
    D = pos[0]
    y, names, K = _y_for(D, pos[1], 'radialindices', 'radial')
    N = int(num(_get(D, 'N')))
    base = np.asarray(darr(_get(D, 'Base')), float).reshape(N, K)
    step = np.asarray(darr(_get(D, 'Perturbed')), float).reshape(N, K)
    R = _int_opt(opts, 'resamples', 100, 'radialindices', 0)
    conf = _num_opt(opts, 'confidence', 0.95, 'radialindices')
    idx = _rs().randint(0, N, size=(R, N)) if R > 1 else None
    mu, star, sigma, star_ci, ST, st_ci = radial_indices(y, base, step, idx, conf)
    if _flat(y):
        ST = np.full(K, np.nan)
    cols = [('ST', ST)] + ([('STConf', st_ci)] if R > 1 else []) + [('MuStar', star)] + ([('MuStarConf', star_ci)] if R > 1 else [])
    return _table(cols + [('Mu', mu), ('Sigma', sigma)], names)


# Shapley

@bi('shapleydesign', nout=2)
def shapleydesign(nargout, *args):
    """[X, D] = shapleydesign(K): Song, Nelson and Staum's design for Shapley
    effects: 'NVar' (1000) runs for the variance, then over 'Orders' random
    orders of the inputs (0, all K! of them, is the default up to 4 inputs,
    else 100) 'NOuter' conditioning points a step (10 up to 4 inputs, else 1)
    and 'NInner' (3) draws given each. 'Correlation', C draws the inputs from
    a Gaussian copula of that correlation matrix."""
    pos, opts = _opts(args, ('orders', 'nvar', 'nouter', 'ninner', 'correlation', 'names'), 'shapleydesign')
    nargchk(pos, 1, 1, 'shapleydesign')
    K, names = _inputs(pos[0], 'shapleydesign')
    if 'names' in opts:
        names = _names(K, opts['names'], 'shapleydesign')
    m = _int_opt(opts, 'orders', 0 if K <= 4 else 100, 'shapleydesign', 0)
    nVar = _int_opt(opts, 'nvar', 1000, 'shapleydesign', 2)
    nOuter = _int_opt(opts, 'nouter', 10 if K <= 4 else 1, 'shapleydesign')
    nInner = _int_opt(opts, 'ninner', 3, 'shapleydesign', 2)
    if m == 0 and K > 8:
        raise err('MATLAB:shapleydesign:tooManyOrders', f'All {K}! orders of {K} inputs is too many; give a number of random orders.', 'shapleydesign')
    corr = None
    if 'correlation' in opts:
        corr = np.asarray(darr(opts['correlation']), float)
        if corr.shape != (K, K) or not np.allclose(corr, corr.T) or not np.allclose(np.diag(corr), 1):
            raise err('MATLAB:shapleydesign:invalidCorrelation', 'The correlation matrix must be K-by-K, symmetric, with ones on its diagonal.', 'shapleydesign')
    nxt = _next()
    import itertools
    orders = [list(p) for p in itertools.permutations(range(K))] if m == 0 else [_perm(K, nxt) for _ in range(m)]
    X = shapley_design(K, orders, nVar, nOuter, nInner, corr, nxt)
    D = _design('shapley', X, names, {'Orders': out(np.array(orders, float).reshape(len(orders), K) + 1), 'NVar': nVar,
                                       'NOuter': nOuter, 'NInner': nInner})
    return _ret(nargout, X, D)


@bi('shapleyindices')
def shapleyindices(nargout, *args):
    """shapleyindices(D, Y): each input's Shapley effect, its fair share of the
    output's variance (they add up to one, correlated inputs or not), with
    its standard error and the 95% half-width (none with one outer point)."""
    nargchk(args, 2, 2, 'shapleyindices')
    D = args[0]
    y, names, K = _y_for(D, args[1], 'shapleyindices', 'shapley')
    orders = (np.asarray(darr(_get(D, 'Orders')), float).reshape(-1, K) - 1).astype(int).tolist()
    nVar, nOuter, nInner = (int(num(_get(D, k))) for k in ('NVar', 'NOuter', 'NInner'))
    eff, se = shapley_indices(y, K, orders, nVar, nOuter, nInner)
    if _flat(y[:nVar]):
        eff = se = np.full(K, np.nan)
    return _table([('Shapley', eff), ('StdErr', se), ('Conf', 1.96 * se if nOuter > 1 else np.full(K, np.nan))], names)


def classes():
    return (PointSet,)
