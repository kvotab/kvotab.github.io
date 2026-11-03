"""Regression models: fitlm (LinearModel), fitglm (GeneralizedLinearModel,
fitted by iteratively reweighted least squares), fitnlm and nlinfit
(NonLinearModel, Levenberg-Marquardt), and the functions around them:
predict, feval, coefCI, coefTest, anova, plot and plotResiduals of a
model; regress, robustfit, ridge, glmfit, glmval, nlparci, nlpredci,
partialcorr and randg.

A model's terms come from Wilkinson notation ('y ~ 1 + x1*x2 - x2',
'y ~ x1^2') or a model spec ('constant', 'linear', 'interactions',
'purequadratic', 'quadratic', 'polyIJK'); a categorical predictor (or
text) becomes indicator columns, its first category the reference.
"""
import math
import re

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, darr, out, opt_str, is_str
from ..values import MError, Obj, Char, Cell, Struct, Str, FH, EMPTY, class_of, numel, py_str
from .. import runtime as R


def _st():
    import scipy.stats as st
    return st


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy or SciPy refuses told as the function's own error."""
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        if kw.get('aw'):
            async def h(*a):
                try:
                    return await f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
            h.__name__, h.__doc__ = f.__name__, f.__doc__
            return _register(*names, **kw)(h)
        return _register(*names, **kw)(g)
    return deco


def _opts(args, names):
    """Name-value options (any case, or a unique start) and the rest."""
    low = {n.lower(): n for n in names}
    got, rest = {}, []
    i = 0
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and i + 1 < len(args):
            k = low.get(s.lower())
            if k is None:
                hits = [v for kk, v in low.items() if kk.startswith(s.lower())]
                k = hits[0] if len(hits) == 1 else None
            if k is not None:
                got[k] = args[i + 1]
                i += 2
                continue
        rest.append(args[i])
        i += 1
    return got, rest


def _flag(v):
    if is_str(v):
        return py_str(v).lower() in ('on', 'true')
    return bool(np.asarray(darr(v)).reshape(-1)[0])


def _tbl(cols, names, rownames=None):
    from .tables import Table
    return Table([np.asarray(c, float).reshape(-1, 1) for c in cols], names, rownames)


def _fmt(v, width=None):
    """A number as the model displays show it (5 significant digits)."""
    if not np.isfinite(v):
        s = 'NaN' if np.isnan(v) else ('Inf' if v > 0 else '-Inf')
    else:
        s = f'{v:.5g}'
    return s if width is None else s.rjust(width)


# ---- the data and the terms --------------------------------------------------------------------------------------------

class Data:
    """The variables of a fit: name -> a column of numbers, or (codes, levels) for a categorical one."""

    def __init__(self, names, cols, response):
        self.names = names
        self.cols = cols
        self.response = response

    @property
    def predictors(self):
        return [n for n in self.names if n != self.response]


def _column(v, name, fn):
    """A variable as numbers, or (codes 0.., levels) when it is categorical or text."""
    from .categoricals import Categorical
    if isinstance(v, Categorical):
        codes = np.asarray(v.a, float).reshape(-1)
        return (codes.astype(int) - 1, list(v.cats))
    if type(v) in (Str, Cell) or (type(v) is Char and v.a.ndim == 2 and v.a.shape[0] > 1):
        if type(v) is Str:
            items = [s if s is not None else '' for s in v.a.reshape(-1, order='F')]
        elif type(v) is Cell:
            items = [py_str(x) for x in v.a.reshape(-1, order='F')]
        else:
            items = v.row_strs()
        levels = sorted(set(items))
        return (np.array([levels.index(s) for s in items]), levels)
    a = darr(v, fn)
    if a.ndim == 2 and a.shape[1] != 1 and a.shape[0] != 1:
        raise err(f'MATLAB:{fn}:variable', f"The variable '{name}' must be a vector.", fn)
    return a.reshape(-1).astype(float)


def _data_from(args, fn, opts):
    """(Data, the arguments after the data) from fitlm(tbl, ...) or fitlm(X, y, ...)."""
    from .tables import Table
    if isinstance(args[0], Table):
        t = args[0]
        names = list(t.names)
        cols = {nm: _column(v, nm, fn) for nm, v in zip(names, t.vars)}
        resp = py_str(opts['ResponseVar']) if 'ResponseVar' in opts else names[-1]
        return Data(names, cols, resp), list(args[1:])
    if len(args) < 2:
        raise err('MATLAB:minrhs', f'{fn} takes a table, or predictors X and a response y.', fn)
    X = darr(args[0], fn)
    if X.ndim != 2:
        raise err(f'MATLAB:{fn}:X', 'X is a matrix of predictors, one column each.', fn)
    if X.shape[0] == 1 and X.shape[1] > 1:
        X = X.T
    y = darr(args[1], fn)
    if min(y.shape) != 1 and y.shape[1] != 2:
        raise err(f'MATLAB:{fn}:y', 'y is a vector.', fn)
    p = X.shape[1]
    if 'VarNames' in opts:
        vn = [py_str(x) for x in opts['VarNames'].a.reshape(-1, order='F')] if type(opts['VarNames']) is Cell else \
            [s for s in opts['VarNames'].a.reshape(-1, order='F')]
        if len(vn) != p + 1:
            raise err(f'MATLAB:{fn}:VarNames', f'VarNames has a name for each predictor and the response ({p + 1}).', fn)
    else:
        vn = [f'x{k + 1}' for k in range(p)] + ['y']
    cols = {vn[k]: X[:, k].astype(float) for k in range(p)}
    cols[vn[-1]] = y if y.ndim == 2 and y.shape[1] == 2 else y.reshape(-1).astype(float)
    cat = opts.get('CategoricalVars')
    if cat is not None:
        idx = [int(i) - 1 for i in np.asarray(darr(cat)).reshape(-1)] if not is_str(cat) and type(cat) is not Cell else \
            [vn.index(py_str(x)) for x in (cat.a.reshape(-1) if type(cat) is Cell else [cat])]
        if np.asarray(darr(cat)).dtype == bool if not is_str(cat) and type(cat) is not Cell else False:
            idx = [k for k, f in enumerate(np.asarray(darr(cat)).reshape(-1)) if f]
        for k in idx:
            levels = sorted(set(cols[vn[k]].tolist()))
            cols[vn[k]] = (np.array([levels.index(x) for x in cols[vn[k]]]), [_fmt(x) for x in levels])
    return Data(vn, cols, vn[-1]), list(args[2:])


def _term_key(term, order):
    """Terms sorted by degree, then by the variables' order."""
    deg = sum(p for _, p in term)
    return (deg, [order.index(v) for v, _ in term], [p for _, p in term])


def _term_name(term):
    if not term:
        return '(Intercept)'
    return ':'.join(v if p == 1 else f'{v}^{p}' for v, p in term)


def _mul(a, b):
    """The product of two terms (powers added)."""
    d = dict(a)
    for v, p in b:
        d[v] = d.get(v, 0) + p
    return tuple(sorted(d.items()))


def _parse_rhs(text, names, fn):
    """A formula's right-hand side as (terms, intercept)."""
    s = text.replace(' ', '')
    if not s:
        raise err(f'MATLAB:{fn}:formula', 'The formula has nothing after ~.', fn)
    parts = re.findall(r'([+-]?)([^+-]+)', s)
    add, drop = set(), set()
    intercept = True
    for sign, piece in parts:
        if piece in ('1', '0'):
            if (piece == '1') == (sign == '-'):
                intercept = False
            else:
                intercept = True
            continue
        terms = _expand(piece, names, fn)
        (drop if sign == '-' else add).update(terms)
    return add - drop, intercept


def _expand(piece, names, fn):
    """A product of factors as a set of terms. A factor is a:b (one term,
    the product), or a^k (a, a^2, ..., a^k), or a; factors joined by * give
    every product of one term from each of a non-empty subset of them."""
    def var(v):
        if v not in names:
            raise err(f'MATLAB:{fn}:formula', f"'{v}' is not a variable of the data.", fn)
        return v

    def factor(f):
        if ':' in f:
            t = ()
            for x in f.split(':'):
                m = re.fullmatch(r'([A-Za-z]\w*)(?:\^(\d+))?', x)
                if not m:
                    raise err(f'MATLAB:{fn}:formula', f"'{x}' is not read in a formula here.", fn)
                t = _mul(t, ((var(m.group(1)), int(m.group(2) or 1)),))
            return {t}
        m = re.fullmatch(r'([A-Za-z]\w*)(?:\^(\d+))?', f)
        if not m:
            raise err(f'MATLAB:{fn}:formula', f"'{f}' is not read in a formula here.", fn)
        v, k = var(m.group(1)), int(m.group(2) or 1)
        return {((v, j),) for j in range(1, k + 1)}
    sets = [factor(f) for f in piece.split('*')]
    import itertools
    result = set()
    for r in range(1, len(sets) + 1):
        for subset in itertools.combinations(sets, r):
            for combo in itertools.product(*subset):
                t = ()
                for c in combo:
                    t = _mul(t, c)
                result.add(t)
    return result


def _spec_terms(spec, preds, fn):
    s = spec.lower()
    terms = set()
    if s == 'constant':
        return set(), True
    lin = {((v, 1),) for v in preds}
    if s == 'linear':
        return lin, True
    inter = {tuple(sorted(((a, 1), (b, 1)))) for i, a in enumerate(preds) for b in preds[i + 1:]}
    sq = {((v, 2),) for v in preds}
    if s == 'interactions':
        return lin | inter, True
    if s == 'purequadratic':
        return lin | sq, True
    if s == 'quadratic':
        return lin | inter | sq, True
    m = re.fullmatch(r'poly(\d+)', s)
    if m and len(m.group(1)) == len(preds):
        degs = [int(c) for c in m.group(1)]
        maxdeg = max(degs)
        import itertools
        for powers in itertools.product(*[range(d + 1) for d in degs]):
            if 0 < sum(powers) <= maxdeg:
                terms.add(tuple((v, p) for v, p in zip(preds, powers) if p))
        return terms, True
    raise err(f'MATLAB:{fn}:modelspec', "The model is a formula 'y ~ ...' or one of 'constant', 'linear', 'interactions', 'purequadratic', 'quadratic', 'polyIJK'.", fn)


class Design:
    """A model's terms and the columns they make."""

    def __init__(self, data, terms, intercept):
        order = data.names
        self.data = data
        self.terms = sorted(terms, key=lambda t: _term_key(t, order))
        self.intercept = intercept
        for t in self.terms:
            for v, p in t:
                if isinstance(data.cols[v], tuple) and p > 1:
                    raise err('MATLAB:fitlm:formula', f"A categorical variable ('{v}') cannot be raised to a power.", 'fitlm')

    def formula_text(self):
        parts = (['1'] if self.intercept else []) + [_term_name(t) for t in self.terms]
        return f'{self.data.response} ~ ' + (' + '.join(parts) if parts else '-1')

    def matrix(self, cols):
        """The design matrix for columns (a dict like data.cols) and the coefficient names."""
        n = len(next(iter(cols.values()))[0]) if isinstance(next(iter(cols.values())), tuple) else len(next(iter(cols.values())))
        mats, names, groups = [], [], []
        if self.intercept:
            mats.append(np.ones((n, 1)))
            names.append('(Intercept)')
            groups.append(-1)
        for ti, t in enumerate(self.terms):
            blocks = [(np.ones((n, 1)), '')]
            for v, p in t:
                c = cols[v]
                if isinstance(c, tuple):
                    codes, levels = c
                    nl = len(self.data.cols[v][1])
                    D = np.zeros((n, nl - 1))
                    for k in range(1, nl):
                        D[:, k - 1] = (codes == k)
                    labs = [f'{v}_{lv}' for lv in self.data.cols[v][1][1:]]
                else:
                    D = (np.asarray(c, float) ** p).reshape(-1, 1)
                    labs = [v if p == 1 else f'{v}^{p}']
                new = []
                for M, nm in blocks:
                    for j, lab in enumerate(labs):
                        new.append((M * D[:, [j]], nm + (':' if nm else '') + lab))
                blocks = new
            for M, nm in blocks:
                mats.append(M)
                names.append(nm)
                groups.append(ti)
        X = np.hstack(mats) if mats else np.zeros((n, 0))
        return X, names, groups


def _design(data, rest, opts, fn):
    """The model's terms from a formula or model spec (and Intercept)."""
    preds = [p for p in data.predictors]
    if 'PredictorVars' in opts:
        pv = opts['PredictorVars']
        if type(pv) is Cell or type(pv) is Str:
            preds = [py_str(x) if type(pv) is Cell else x for x in pv.a.reshape(-1, order='F')]
        else:
            preds = [data.names[int(k) - 1] for k in np.asarray(darr(pv)).reshape(-1)]
    spec = py_str(rest[0]) if rest and is_str(rest[0]) else 'linear'
    if '~' in spec:
        lhs, rhs = spec.split('~', 1)
        lhs = lhs.strip()
        if lhs not in data.names:
            raise err(f'MATLAB:{fn}:formula', f"The response '{lhs}' is not a variable of the data.", fn)
        data.response = lhs
        terms, icpt = _parse_rhs(rhs, [n for n in data.names if n != lhs], fn)
    else:
        terms, icpt = _spec_terms(spec, [p for p in preds if p != data.response], fn)
    if 'Intercept' in opts:
        icpt = _flag(opts['Intercept'])
    return Design(data, terms, icpt)


# ---- least squares --------------------------------------------------------------------------------------------------------

def _wls(X, y, w):
    sw = np.sqrt(w)
    Xw, yw = X * sw[:, None], y * sw
    b, _, rank, _ = np.linalg.lstsq(Xw, yw, rcond=None)
    XtWX_inv = np.linalg.pinv(Xw.T @ Xw)
    return b, rank, XtWX_inv


def _weights(opts, n):
    if 'Weights' in opts:
        w = darr(opts['Weights']).reshape(-1).astype(float)
        if w.size != n or np.any(w < 0):
            raise err('MATLAB:fitlm:Weights', 'Weights has a non-negative value for each observation.', 'fitlm')
        return w
    return np.ones(n)


_TUNE = {'bisquare': 4.685, 'andrews': 1.339, 'cauchy': 2.385, 'fair': 1.400, 'huber': 1.345, 'logistic': 1.205, 'talwar': 2.795, 'welsch': 2.985}


def _robust_w(u, wfun):
    a = np.abs(u)
    if wfun == 'bisquare':
        return (a < 1) * (1 - u ** 2) ** 2
    if wfun == 'andrews':
        with np.errstate(all='ignore'):
            return np.where(a < np.pi, np.where(a < 1e-12, 1.0, np.sin(u) / np.where(u == 0, 1, u)), 0.0)
    if wfun == 'cauchy':
        return 1 / (1 + u ** 2)
    if wfun == 'fair':
        return 1 / (1 + a)
    if wfun == 'huber':
        return 1 / np.maximum(1, a)
    if wfun == 'logistic':
        with np.errstate(all='ignore'):
            return np.where(a < 1e-12, 1.0, np.tanh(u) / np.where(u == 0, 1, u))
    if wfun == 'talwar':
        return (a < 1).astype(float)
    if wfun == 'welsch':
        return np.exp(-u ** 2)
    raise err('MATLAB:robustfit:wfun', f"The weight function is one of {', '.join(sorted(_TUNE))} or 'ols'.", 'robustfit')


def _robust(X, y, w0, wfun='bisquare', tune=None, iters=50):
    """Iteratively reweighted least squares with the weight function; the
    scale from the median absolute deviation of the leverage-adjusted
    residuals (the p smallest left out)."""
    tune = tune or _TUNE[wfun]
    n, p = X.shape
    b, rank, _ = _wls(X, y, w0)
    Q = np.linalg.qr(X * np.sqrt(w0)[:, None])[0]
    h = np.minimum(0.9999, np.sum(Q ** 2, axis=1))
    adj = 1 / np.sqrt(1 - h)
    w = w0.copy()
    s = 1.0
    for _ in range(iters):
        r = (y - X @ b) * adj
        rs = np.sort(np.abs(r))
        s = np.median(rs[max(rank - 1, 0):]) / 0.6745 if rs.size else 1.0
        if s == 0:
            s = 1.0
        w = w0 * _robust_w(r / (s * tune), wfun)
        b_new, _, _ = _wls(X, y, w)
        if np.max(np.abs(b_new - b)) <= 1e-6 * max(np.max(np.abs(b)), np.max(np.abs(b_new)), 1e-12):
            b = b_new
            break
        b = b_new
    return b, w, s


# ---- LinearModel ---------------------------------------------------------------------------------------------------------

class LinearModel(Obj):
    cls = 'LinearModel'
    is_handle = False

    def __init__(self, design, b, names, groups, X, y, w, robust=None):
        self.design, self.b, self.names, self.groups = design, b, names, groups
        self.X, self.y, self.w = X, y, w
        n, p = X.shape
        self.n, self.p = n, p
        self.fitted = X @ b
        self.resid = y - self.fitted
        # a robust fit: its final weights stand in for the given ones in the variance
        ww = w if robust is None else robust
        _, rank, inv = _wls(X, y, ww)
        self.rank = rank
        self.dfe = n - rank
        self.sse = float(np.sum(w * self.resid ** 2))
        self.mse = float(np.sum(ww * self.resid ** 2)) / self.dfe if self.dfe > 0 else np.nan
        self.cov = self.mse * inv
        self.se = np.sqrt(np.maximum(np.diag(self.cov), 0))
        with np.errstate(all='ignore'):
            self.t = self.b / self.se
        self.pv = 2 * _st().t.sf(np.abs(self.t), self.dfe) if self.dfe > 0 else np.full(p, np.nan)
        ybar = np.sum(w * y) / np.sum(w)
        self.sst = float(np.sum(w * (y - ybar) ** 2)) if design.intercept else float(np.sum(w * y ** 2))
        self.ssr = self.sst - self.sse
        self.r2 = 1 - self.sse / self.sst if self.sst > 0 else np.nan
        dft = n - 1 if design.intercept else n
        self.r2adj = 1 - (self.sse / self.dfe) / (self.sst / dft) if self.dfe > 0 and self.sst > 0 else np.nan
        self.loglik = -n / 2 * (math.log(2 * math.pi) + math.log(max(self.sse / n, 1e-300)) + 1)
        Q = np.linalg.qr(X * np.sqrt(w)[:, None])[0]
        self.h = np.sum(Q ** 2, axis=1)
        self.robust = robust is not None

    # what is shown and read
    def coef_table(self):
        return _tbl([self.b, self.se, self.t, self.pv], ['Estimate', 'SE', 'tStat', 'pValue'], self.names)

    def fstat(self):
        k = self.rank - (1 if self.design.intercept else 0)
        if k <= 0 or self.dfe <= 0:
            return np.nan, np.nan
        F = (self.ssr / k) / self.mse
        return F, float(_st().f.sf(F, k, self.dfe))

    def residual_table(self):
        rmse = math.sqrt(self.mse)
        with np.errstate(all='ignore'):
            s_i = np.sqrt(np.maximum((self.sse - self.resid ** 2 / (1 - self.h)) / (self.dfe - 1), 0))
            stud = self.resid / (s_i * np.sqrt(1 - self.h))
            stand = self.resid / (rmse * np.sqrt(1 - self.h))
        return _tbl([self.resid, self.resid / rmse, stud, stand], ['Raw', 'Pearson', 'Studentized', 'Standardized'])

    def getprop(self, name):
        n = name.lower()
        F, pf = self.fstat()
        props = {
            'coefficients': lambda: self.coef_table(),
            'coefficientnames': lambda: Cell.of_list([Char.of(s) for s in self.names]),
            'coefficientcovariance': lambda: out(self.cov),
            'numcoefficients': lambda: float(self.p),
            'numestimatedcoefficients': lambda: float(self.rank),
            'numobservations': lambda: float(self.n),
            'numpredictors': lambda: float(len({v for t in self.design.terms for v, _ in t})),
            'dfe': lambda: float(self.dfe),
            'sse': lambda: self.sse, 'sst': lambda: self.sst, 'ssr': lambda: self.ssr,
            'mse': lambda: self.mse, 'rmse': lambda: math.sqrt(self.mse),
            'rsquared': lambda: Struct.scalar({'Ordinary': self.r2, 'Adjusted': self.r2adj}),
            'fitted': lambda: out(self.fitted.reshape(-1, 1)),
            'residuals': lambda: self.residual_table(),
            'loglikelihood': lambda: self.loglik,
            'modelcriterion': lambda: Struct.scalar({'AIC': -2 * self.loglik + 2 * self.rank, 'AICc': -2 * self.loglik + 2 * self.rank + 2 * self.rank * (self.rank + 1) / max(self.n - self.rank - 1, 1),
                                                     'BIC': -2 * self.loglik + self.rank * math.log(self.n), 'CAIC': -2 * self.loglik + self.rank * (math.log(self.n) + 1)}),
            'formula': lambda: Char.of(self.design.formula_text()),
            'responsename': lambda: Char.of(self.design.data.response),
            'predictornames': lambda: Cell.of_list([Char.of(v) for v in self.predictor_names()]),
            'variablenames': lambda: Cell.of_list([Char.of(v) for v in self.design.data.names]),
            'numvariables': lambda: float(len(self.design.data.names)),
            'robust': lambda: self.robust,
            'diagnostics': lambda: _tbl([self.h], ['Leverage']),
        }
        if n in props:
            return props[n]()
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")

    def predictor_names(self):
        seen = []
        for t in self.design.terms:
            for v, _ in t:
                if v not in seen:
                    seen.append(v)
        return [v for v in self.design.data.names if v in seen]

    def propnames(self):
        return ['Coefficients', 'CoefficientNames', 'CoefficientCovariance', 'NumCoefficients', 'NumEstimatedCoefficients', 'NumObservations',
                'NumPredictors', 'NumVariables', 'DFE', 'SSE', 'SST', 'SSR', 'MSE', 'RMSE', 'Rsquared', 'Fitted', 'Residuals', 'LogLikelihood',
                'ModelCriterion', 'Formula', 'ResponseName', 'PredictorNames', 'VariableNames', 'Robust', 'Diagnostics']

    def coef_lines(self, cols=('Estimate', 'SE', 'tStat', 'pValue')):
        vals = [self.b, self.se, self.t, self.pv]
        w = max(len(s) for s in self.names) + 4
        cells = [[_fmt(v) for v in col] for col in vals]
        cw = [max(10, max(len(c) for c in col) + 2) for col in cells]
        head = ' ' * w + ''.join(h.center(cw[i] + 2) for i, h in enumerate(cols))
        under = ' ' * w + ''.join(('_' * max(len(h), 8)).center(cw[i] + 2) for i, h in enumerate(cols))
        lines = [head, under, '']
        for r, nm in enumerate(self.names):
            lines.append('    ' + nm.ljust(w - 4) + ''.join(cells[i][r].rjust(cw[i]) + '  ' for i in range(len(cols))))
        return lines

    def display_lines(self):
        F, pf = self.fstat()
        lines = [('Linear regression model (robust fit):' if self.robust else 'Linear regression model:'), '    ' + self.design.formula_text(), '',
                 'Estimated Coefficients:'] + self.coef_lines() + ['',
                 f'Number of observations: {self.n}, Error degrees of freedom: {self.dfe}', f'Root Mean Squared Error: {_fmt(math.sqrt(self.mse))}']
        if self.design.intercept and self.rank > 1:
            lines += [f'R-squared: {_fmt(self.r2)},  Adjusted R-Squared: {_fmt(self.r2adj)}',
                      f'F-statistic vs. constant model: {_fmt(F)}, p-value = {_fmt(pf)}']
        return lines

    def x_for(self, Xnew, fn='predict'):
        """The design matrix for new predictor values (a matrix of the predictors, or a table)."""
        from .tables import Table
        d = self.design.data
        if isinstance(Xnew, Table):
            cols = {nm: _column(v, nm, fn) for nm, v in zip(Xnew.names, Xnew.vars)}
            for v in self.predictor_names():
                if v not in cols:
                    raise err(f'MATLAB:{fn}:variable', f"The table has no variable '{v}'.", fn)
        else:
            A = darr(Xnew, fn)
            preds = [n for n in d.names if n != d.response]
            if A.ndim != 2:
                raise err(f'MATLAB:{fn}:X', 'X has a column for each predictor.', fn)
            if A.shape[1] != len(preds) and A.shape[0] == len(preds) and A.shape[1] == 1:
                A = A.T
            if A.shape[1] != len(preds):
                raise err(f'MATLAB:{fn}:X', f'X must have {len(preds)} columns, one for each predictor.', fn)
            cols = {}
            for k, v in enumerate(preds):
                c = A[:, k]
                if isinstance(d.cols[v], tuple):
                    levels = d.cols[v][1]
                    cols[v] = (np.array([levels.index(_fmt(x)) if _fmt(x) in levels else 0 for x in c]), levels)
                else:
                    cols[v] = c.astype(float)
        cols = {k: v for k, v in cols.items() if k != d.response}
        for v in d.names:
            if v != d.response and v not in cols:
                cols[v] = np.zeros(len(next(iter(cols.values()))[0]) if isinstance(next(iter(cols.values())), tuple) else len(next(iter(cols.values()))))
        X, _, _ = self.design.matrix(cols)
        return X

    def predict(self, Xnew, alpha=0.05, obs=False, simultaneous=False):
        X = self.x_for(Xnew)
        y = X @ self.b
        var = np.einsum('ij,jk,ik->i', X, self.cov, X)
        if obs:
            var = var + self.mse
        if simultaneous:
            k = self.rank + (1 if obs else 0)
            crit = math.sqrt(k * _st().f.ppf(1 - alpha, k, self.dfe))
        else:
            crit = _st().t.ppf(1 - alpha / 2, self.dfe)
        d = crit * np.sqrt(np.maximum(var, 0))
        return y, np.column_stack([y - d, y + d])


# ---- GeneralizedLinearModel ------------------------------------------------------------------------------------------------

_CANON = {'normal': 'identity', 'binomial': 'logit', 'poisson': 'log', 'gamma': -1.0, 'inverse gaussian': -2.0}


def _link(spec):
    """(name, g, g', ginv) of a link: a name or a power."""
    if isinstance(spec, float):
        p = spec
        if p == 0:
            return _link('log')
        return (f'power({p:g})' if p not in (-1.0, -2.0) else ('reciprocal' if p == -1 else f'power({p:g})'), lambda m: m ** p,
                lambda m: p * m ** (p - 1), lambda e: np.maximum(e, 1e-300) ** (1 / p) if p < 0 else np.abs(e) ** (1 / p))
    st = _st()
    s = spec.lower()
    if s == 'identity':
        return ('identity', lambda m: m, lambda m: np.ones_like(m), lambda e: e)
    if s == 'log':
        return ('log', np.log, lambda m: 1 / m, np.exp)
    if s == 'logit':
        return ('logit', lambda m: np.log(m / (1 - m)), lambda m: 1 / (m * (1 - m)), lambda e: 1 / (1 + np.exp(-e)))
    if s == 'probit':
        return ('probit', st.norm.ppf, lambda m: 1 / st.norm.pdf(st.norm.ppf(m)), st.norm.cdf)
    if s == 'comploglog':
        return ('comploglog', lambda m: np.log(-np.log(1 - m)), lambda m: -1 / ((1 - m) * np.log(1 - m)), lambda e: 1 - np.exp(-np.exp(e)))
    if s == 'loglog':
        return ('loglog', lambda m: np.log(-np.log(m)), lambda m: 1 / (m * np.log(m)), lambda e: np.exp(-np.exp(e)))
    if s == 'reciprocal':
        return _link(-1.0)
    raise err('MATLAB:fitglm:link', "The link is 'identity', 'log', 'logit', 'probit', 'comploglog', 'loglog', 'reciprocal' or a power.", 'fitglm')


def _variance(dist, mu, N):
    if dist == 'normal':
        return np.ones_like(mu)
    if dist == 'binomial':
        return mu * (1 - mu) / N
    if dist == 'poisson':
        return mu
    if dist == 'gamma':
        return mu ** 2
    return mu ** 3


def _deviance(dist, y, mu, N, w):
    with np.errstate(all='ignore'):
        if dist == 'normal':
            d = (y - mu) ** 2
        elif dist == 'binomial':
            d = 2 * N * (np.where(y > 0, y * np.log(y / mu), 0) + np.where(y < 1, (1 - y) * np.log((1 - y) / (1 - mu)), 0))
        elif dist == 'poisson':
            d = 2 * (np.where(y > 0, y * np.log(y / mu), 0) - (y - mu))
        elif dist == 'gamma':
            d = 2 * (-np.log(y / mu) + (y - mu) / mu)
        else:
            d = (y - mu) ** 2 / (mu ** 2 * y)
    return float(np.sum(w * d))


def _irls(X, y, dist, link, N, w, offset=0.0):
    name, g, gd, ginv = link
    if dist == 'binomial':
        mu = (N * y + 0.5) / (N + 1)
    elif dist == 'poisson':
        mu = y + 0.25
    else:
        mu = np.where(y == 0, 0.01, y) if dist != 'normal' else y.astype(float).copy()
    eta = g(mu)
    b = np.zeros(X.shape[1])
    dev_old = np.inf
    it = 0
    for it in range(1, 101):
        z = eta - offset + (y - mu) * gd(mu)
        W = w / (gd(mu) ** 2 * _variance(dist, mu, N))
        b, _, inv = _wls(X, z, W)
        eta = X @ b + offset
        mu = ginv(eta)
        if dist == 'binomial':
            mu = np.clip(mu, 1e-10, 1 - 1e-10)
        elif dist in ('poisson', 'gamma', 'inverse gaussian'):
            mu = np.maximum(mu, 1e-10)
        dev = _deviance(dist, y, mu, N, w)
        if abs(dev - dev_old) <= 1e-10 * max(abs(dev), 1e-10):
            break
        dev_old = dev
    W = w / (gd(mu) ** 2 * _variance(dist, mu, N))
    _, rank, inv = _wls(X, np.zeros_like(y), W)
    return b, mu, eta, dev, inv, rank, it


class GeneralizedLinearModel(LinearModel):
    cls = 'GeneralizedLinearModel'

    def __init__(self, design, X, y, N, w, dist, link, names, groups, disp_flag=False):
        self.design, self.names, self.groups = design, names, groups
        self.X, self.y, self.N, self.w = X, y, N, w
        self.dist, self.link = dist, link
        b, mu, eta, dev, inv, rank, it = _irls(X, y, dist, link, N, w)
        self.b, self.mu, self.eta, self.deviance, self.rank, self.iters = b, mu, eta, dev, rank, it
        self.n, self.p = X.shape
        self.dfe = self.n - rank
        V = _variance(dist, mu, N)
        self.pearson = (y - mu) / np.sqrt(V / w)
        fixed = dist in ('binomial', 'poisson') and not disp_flag
        self.dispersion = 1.0 if fixed else float(np.sum(self.pearson ** 2) / self.dfe) if self.dfe > 0 else np.nan
        self.estdisp = not fixed
        self.cov = self.dispersion * inv
        self.se = np.sqrt(np.maximum(np.diag(self.cov), 0))
        with np.errstate(all='ignore'):
            self.t = b / self.se
        self.pv = 2 * (_st().t.sf(np.abs(self.t), self.dfe) if self.estdisp else _st().norm.sf(np.abs(self.t)))
        # the constant model's deviance
        if design.intercept:
            b0, mu0, _, dev0, _, _, _ = _irls(np.ones((self.n, 1)), y, dist, link, N, w)
            self.dev0 = dev0
        else:
            self.dev0 = np.nan
        self.fitted = mu
        self.resid = y - mu

    def fstat(self):
        k = self.rank - 1
        if k <= 0 or not np.isfinite(self.dev0):
            return np.nan, np.nan
        if self.estdisp:
            F = (self.dev0 - self.deviance) / k / self.dispersion
            return F, float(_st().f.sf(F, k, self.dfe))
        c = self.dev0 - self.deviance
        return c, float(_st().chi2.sf(c, k))

    def link_text(self):
        nm = self.link[0]
        return self.design.data.response if nm == 'identity' else f'{nm}({self.design.data.response})'

    def display_lines(self):
        F, pf = self.fstat()
        f = self.design.formula_text()
        rhs = f.split('~', 1)[1]
        dname = {'normal': 'Normal', 'binomial': 'Binomial', 'poisson': 'Poisson', 'gamma': 'Gamma', 'inverse gaussian': 'InverseGaussian'}[self.dist]
        lines = ['Generalized linear regression model:', f'    {self.link_text()} ~{rhs}', f'    Distribution = {dname}', '',
                 'Estimated Coefficients:'] + self.coef_lines() + ['',
                 f'{self.n} observations, {self.dfe} error degrees of freedom',
                 'Dispersion is 1' if not self.estdisp else f'Estimated Dispersion: {_fmt(self.dispersion)}']
        if np.isfinite(F):
            lines.append(('F-statistic' if self.estdisp else 'Chi^2-statistic') + f' vs. constant model: {_fmt(F)}, p-value = {_fmt(pf)}')
        return lines

    def getprop(self, name):
        n = name.lower()
        if n == 'deviance':
            return self.deviance
        if n == 'dispersion':
            return self.dispersion
        if n == 'distribution':
            return Struct.scalar({'Name': Char.of(self.dist)})
        if n == 'link':
            return Struct.scalar({'Name': Char.of(self.link[0])})
        if n == 'fitted':
            return _tbl([self.mu, self.eta], ['Response', 'LinearPredictor'])
        if n == 'residuals':
            dev_r = np.sign(self.y - self.mu) * np.sqrt(np.maximum([_deviance(self.dist, self.y[i:i + 1], self.mu[i:i + 1], self.N if np.isscalar(self.N) else self.N[i:i + 1], self.w[i:i + 1]) for i in range(self.n)], 0))
            return _tbl([self.y - self.mu, self.pearson, dev_r], ['Raw', 'Pearson', 'Deviance'])
        if n in ('rsquared',):
            return Struct.scalar({'Ordinary': 1 - self.deviance / self.dev0 if np.isfinite(self.dev0) else np.nan})
        if n in ('sse', 'sst', 'ssr', 'mse', 'rmse'):
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")
        return super().getprop(name)

    def propnames(self):
        return ['Coefficients', 'CoefficientNames', 'CoefficientCovariance', 'NumCoefficients', 'NumObservations', 'DFE', 'Deviance',
                'Dispersion', 'Distribution', 'Link', 'Fitted', 'Residuals', 'Formula', 'ResponseName', 'PredictorNames', 'VariableNames']

    def predict(self, Xnew, alpha=0.05, obs=False, simultaneous=False):
        X = self.x_for(Xnew)
        eta = X @ self.b
        var = np.einsum('ij,jk,ik->i', X, self.cov, X)
        crit = _st().t.ppf(1 - alpha / 2, self.dfe) if self.estdisp else _st().norm.ppf(1 - alpha / 2)
        d = crit * np.sqrt(np.maximum(var, 0))
        ginv = self.link[3]
        lo, hi = ginv(eta - d), ginv(eta + d)
        return ginv(eta), np.column_stack([np.minimum(lo, hi), np.maximum(lo, hi)])


# ---- NonLinearModel ---------------------------------------------------------------------------------------------------------

def _call_model(f, beta, X):
    r = f.scall(1, out(beta.reshape(1, -1)), out(X))
    return darr(r).reshape(-1).astype(float)


def _jacobian(f, beta, X, f0):
    J = np.empty((f0.size, beta.size))
    for j in range(beta.size):
        h = math.sqrt(np.finfo(float).eps) * max(abs(beta[j]), 1.0)
        bb = beta.copy()
        bb[j] += h
        J[:, j] = (_call_model(f, bb, X) - f0) / h
    return J


def _nlfit(X, y, f, beta0, w, opts_maxiter=400):
    from scipy.optimize import least_squares
    sw = np.sqrt(w)
    n = y.size

    def res(beta):
        m = _call_model(f, beta, X)
        if m.size != n:
            raise err('stats:nlinfit:WrongSizeFunOutput', f'The model function must return {n} values, one for each observation.', 'nlinfit')
        return (y - m) * sw
    r = least_squares(res, beta0, method='lm' if n >= beta0.size else 'trf', max_nfev=opts_maxiter * (beta0.size + 1), xtol=1e-8, ftol=1e-8)
    beta = r.x
    f0 = _call_model(f, beta, X)
    J = _jacobian(f, beta, X, f0)
    R_ = y - f0
    dfe = max(n - beta.size, 1)
    mse = float(np.sum(w * R_ ** 2) / dfe)
    Jw = J * sw[:, None]
    cov = mse * np.linalg.pinv(Jw.T @ Jw)
    return beta, R_, J, cov, mse, r


def _fh_text(f):
    """A model function's text as a formula: b(2) as b2, x(:, 1) as x1, x as x1."""
    t = f.text() if hasattr(f, 'text') else str(f)
    m = re.match(r'@\(\s*([A-Za-z]\w*)\s*,\s*([A-Za-z]\w*)\s*\)\s*(.*)$', t, re.S)
    if not m:
        return t
    b, x, body = m.groups()
    body = re.sub(rf'\b{b}\s*\(\s*(\d+)\s*\)', r'b\1', body)
    body = re.sub(rf'\b{x}\s*\(\s*:\s*,\s*(\d+)\s*\)', r'x\1', body)
    body = re.sub(rf'\b{x}\b(?!\d)', 'x1', body)
    return body.strip()


class NonLinearModel(LinearModel):
    cls = 'NonLinearModel'

    def __init__(self, data, X, y, f, beta, R_, J, cov, mse, w, names, xnames):
        self.data, self.Xd, self.y, self.f, self.w = data, X, y, f, w
        self.b, self.resid, self.J, self.cov, self.mse = beta, R_, J, cov, mse
        self.names, self.xnames = names, xnames
        self.n, self.p = y.size, beta.size
        self.dfe = self.n - self.p
        self.rank = self.p
        self.se = np.sqrt(np.maximum(np.diag(cov), 0))
        with np.errstate(all='ignore'):
            self.t = beta / self.se
        self.pv = 2 * _st().t.sf(np.abs(self.t), self.dfe) if self.dfe > 0 else np.full(self.p, np.nan)
        self.fitted = y - R_
        self.sse = float(np.sum(w * R_ ** 2))
        ybar = np.sum(w * y) / np.sum(w)
        self.sst = float(np.sum(w * (y - ybar) ** 2))
        self.ssr = self.sst - self.sse
        self.r2 = 1 - self.sse / self.sst if self.sst > 0 else np.nan
        self.r2adj = 1 - (self.sse / self.dfe) / (self.sst / (self.n - 1)) if self.dfe > 0 and self.sst > 0 else np.nan
        self.loglik = -self.n / 2 * (math.log(2 * math.pi) + math.log(max(self.sse / self.n, 1e-300)) + 1)
        self.h = np.zeros(self.n)
        self.robust = False

    def formula_text(self):
        return f'{self.data} ~ {_fh_text(self.f)}'

    def fstat(self):
        k = self.p - 1
        if k <= 0 or self.dfe <= 0 or not self.mse > 0:
            return np.nan, np.nan
        F = (self.ssr / k) / self.mse
        return F, float(_st().f.sf(F, k, self.dfe))

    def display_lines(self):
        F, pf = self.fstat()
        lines = ['Nonlinear regression model:', '    ' + self.formula_text(), '', 'Estimated Coefficients:'] + self.coef_lines() + ['',
                 f'Number of observations: {self.n}, Error degrees of freedom: {self.dfe}', f'Root Mean Squared Error: {_fmt(math.sqrt(self.mse))}',
                 f'R-Squared: {_fmt(self.r2)},  Adjusted R-Squared {_fmt(self.r2adj)}']
        if np.isfinite(F):
            lines.append(f'F-statistic vs. constant model: {_fmt(F)}, p-value = {_fmt(pf)}')
        return lines

    def getprop(self, name):
        n = name.lower()
        if n == 'formula':
            return Char.of(self.formula_text())
        if n == 'responsename':
            return Char.of(self.data)
        if n in ('predictornames', 'variablenames'):
            return Cell.of_list([Char.of(v) for v in (self.xnames + ([self.data] if n == 'variablenames' else []))])
        if n == 'fitted':
            return out(self.fitted.reshape(-1, 1))
        if n == 'residuals':
            rmse = math.sqrt(self.mse)
            return _tbl([self.resid, self.resid / rmse], ['Raw', 'Pearson'])
        if n == 'numpredictors':
            return float(len(self.xnames))
        return super().getprop(name)

    def predict(self, Xnew, alpha=0.05, obs=False, simultaneous=False):
        X = darr(Xnew, 'predict')
        if X.ndim == 2 and X.shape[0] == 1 and self.Xd.shape[1] == 1 and X.shape[1] != 1:
            X = X.T
        y = _call_model(self.f, self.b, X)
        J = _jacobian(self.f, self.b, X, y)
        var = np.einsum('ij,jk,ik->i', J, self.cov, J)
        if obs:
            var = var + self.mse
        crit = math.sqrt(self.p * _st().f.ppf(1 - alpha, self.p, self.dfe)) if simultaneous else _st().t.ppf(1 - alpha / 2, self.dfe)
        d = crit * np.sqrt(np.maximum(var, 0))
        return y, np.column_stack([y - d, y + d])


# ---- fitlm, fitglm, fitnlm ---------------------------------------------------------------------------------------------------

_FIT_OPTS = ('ResponseVar', 'PredictorVars', 'Intercept', 'Weights', 'VarNames', 'CategoricalVars', 'RobustOpts', 'Exclude',
             'Distribution', 'Link', 'BinomialSize', 'DispersionFlag', 'Offset', 'CoefficientNames', 'Options', 'ErrorModel')


def _excluded(opts, n):
    keep = np.ones(n, bool)
    if 'Exclude' in opts:
        e = np.asarray(darr(opts['Exclude'])).reshape(-1)
        if e.dtype == bool or (e.size == n and set(np.unique(e)).issubset({0, 1})):
            keep &= ~(e.astype(bool))
        else:
            keep[(e.astype(int) - 1)] = False
    return keep


def _fit_data(args, fn):
    nargchk(args, 1, 40, fn)
    opts, rest = _opts(list(args), _FIT_OPTS)
    data, rest = _data_from(rest, fn, opts)
    design = _design(data, rest, opts, fn)
    X, names, groups = design.matrix(data.cols)
    yv = data.cols[data.response]
    if isinstance(yv, tuple):
        raise err(f'MATLAB:{fn}:response', 'The response must be numeric.', fn)
    n = X.shape[0]
    w = _weights(opts, n)
    keep = _excluded(opts, n)
    # rows with a missing value are left out
    ok = keep & np.all(np.isfinite(X), axis=1) & (np.all(np.isfinite(yv), axis=1) if yv.ndim == 2 else np.isfinite(yv))
    return opts, design, X[ok], (yv[ok] if yv.ndim == 1 else yv[ok]), w[ok], names, groups


@bi('fitlm')
def fitlm(nargout, *args):
    """mdl = fitlm(X, y), fitlm(tbl), fitlm(tbl, 'y ~ x1 + x2'), fitlm(X, y, 'quadratic', Name, Value): a linear regression model."""
    opts, design, X, y, w, names, groups = _fit_data(args, 'fitlm')
    if X.shape[0] <= 0:
        raise err('MATLAB:fitlm:noData', 'There are no observations to fit.', 'fitlm')
    robust = None
    if 'RobustOpts' in opts and (not is_str(opts['RobustOpts']) or py_str(opts['RobustOpts']).lower() != 'off'):
        wf = 'bisquare' if not is_str(opts['RobustOpts']) or py_str(opts['RobustOpts']).lower() == 'on' else py_str(opts['RobustOpts']).lower()
        b, rw, s = _robust(X, y, w, wf)
        robust = rw
    else:
        b, _, _ = _wls(X, y, w)
    return LinearModel(design, b, names, groups, X, y, w, robust)


@bi('fitglm')
def fitglm(nargout, *args):
    """mdl = fitglm(X, y, modelspec, 'Distribution', d, 'Link', l, ...): a generalized linear model."""
    opts, design, X, y, w, names, groups = _fit_data(args, 'fitglm')
    dist = py_str(opts['Distribution']).lower() if 'Distribution' in opts else 'normal'
    if dist not in _CANON:
        raise err('MATLAB:fitglm:distribution', "The distribution is 'normal', 'binomial', 'poisson', 'gamma' or 'inverse gaussian'.", 'fitglm')
    lk = opts.get('Link')
    link = _link(_CANON[dist] if lk is None else (py_str(lk) if is_str(lk) else float(darr(lk).flat[0])))
    N = np.ones(X.shape[0])
    if y.ndim == 2:
        # [successes trials]
        N = y[:, 1].astype(float)
        y = y[:, 0] / N
    elif 'BinomialSize' in opts:
        N = np.broadcast_to(np.asarray(darr(opts['BinomialSize']), float).reshape(-1), y.shape).astype(float)
        y = y / N
    if dist == 'binomial' and (np.any(y < 0) or np.any(y > 1)):
        raise err('MATLAB:fitglm:binomial', 'A binomial response is between 0 and 1 (or counts with BinomialSize).', 'fitglm')
    if dist == 'poisson' and np.any(y < 0):
        raise err('MATLAB:fitglm:poisson', 'A Poisson response is not negative.', 'fitglm')
    if dist in ('gamma', 'inverse gaussian') and np.any(y <= 0):
        raise err('MATLAB:fitglm:positive', 'A gamma or inverse Gaussian response is positive.', 'fitglm')
    flag = _flag(opts['DispersionFlag']) if 'DispersionFlag' in opts else False
    return GeneralizedLinearModel(design, X, y.astype(float), N, w, dist, link, names, groups, flag)


@bi('fitnlm')
def fitnlm(nargout, *args):
    """mdl = fitnlm(X, y, modelfun, beta0) or fitnlm(tbl, modelfun, beta0): a nonlinear regression model."""
    nargchk(args, 3, 30, 'fitnlm')
    opts, rest = _opts(list(args), _FIT_OPTS)
    from .tables import Table
    if isinstance(rest[0], Table):
        t = rest[0]
        resp = py_str(opts['ResponseVar']) if 'ResponseVar' in opts else t.names[-1]
        xn = [n for n in t.names if n != resp]
        X = np.column_stack([darr(t.vars[t.names.index(n)]).reshape(-1) for n in xn])
        y = darr(t.vars[t.names.index(resp)]).reshape(-1)
        f, beta0 = rest[1], rest[2]
    else:
        X = darr(rest[0], 'fitnlm')
        X = X.T if X.shape[0] == 1 and X.shape[1] > 1 else X
        y = darr(rest[1], 'fitnlm').reshape(-1)
        f, beta0 = rest[2], rest[3]
        xn = [f'x{k + 1}' for k in range(X.shape[1])]
        resp = 'y'
    if not isinstance(f, FH):
        raise err('MATLAB:fitnlm:modelfun', 'The model is a function handle, as @(b, x) b(1)*exp(-b(2)*x).', 'fitnlm')
    b0 = darr(beta0).reshape(-1).astype(float)
    w = _weights(opts, y.size)
    beta, R_, J, cov, mse, _ = _nlfit(X, y, f, b0, w)
    names = [py_str(x) for x in opts['CoefficientNames'].a.reshape(-1)] if 'CoefficientNames' in opts else [f'b{k + 1}' for k in range(beta.size)]
    return NonLinearModel(resp, X, y, f, beta, R_, J, cov, mse, w, names, xn)


# ---- functions of a model --------------------------------------------------------------------------------------------------

def _model(v, fn):
    if not isinstance(v, LinearModel):
        raise err(f'MATLAB:{fn}:model', f'{fn} takes a fitted model (fitlm, fitglm, fitnlm).', fn)
    return v


@bi('predict', nout=2)
def predict(nargout, *args):
    """[ypred, yci] = predict(mdl, Xnew, 'Alpha', a, 'Prediction', 'curve'|'observation', 'Simultaneous', tf)."""
    nargchk(args, 1, 10, 'predict')
    m = _model(args[0], 'predict')
    opts, rest = _opts(list(args[1:]), ('Alpha', 'Prediction', 'Simultaneous'))
    Xn = rest[0] if rest else (m.Xd if isinstance(m, NonLinearModel) else None)
    alpha = float(darr(opts['Alpha']).flat[0]) if 'Alpha' in opts else 0.05
    obs = 'Prediction' in opts and py_str(opts['Prediction']).lower() == 'observation'
    sim = _flag(opts['Simultaneous']) if 'Simultaneous' in opts else False
    if Xn is None:
        # the data it was fitted to
        y, ci = m.fitted, None
        if nargout > 1:
            X = m.X
            var = np.einsum('ij,jk,ik->i', X, m.cov, X) + (m.mse if obs else 0)
            d = _st().t.ppf(1 - alpha / 2, m.dfe) * np.sqrt(np.maximum(var, 0))
            ci = np.column_stack([y - d, y + d])
        return (out(y.reshape(-1, 1)), out(ci)) if nargout > 1 else out(y.reshape(-1, 1))
    y, ci = m.predict(Xn, alpha, obs, sim)
    return (out(y.reshape(-1, 1)), out(ci)) if nargout > 1 else out(y.reshape(-1, 1))


@bi('coefCI')
def coefCI(nargout, *args):
    """ci = coefCI(mdl, alpha): confidence intervals of the coefficients."""
    nargchk(args, 1, 2, 'coefCI')
    m = _model(args[0], 'coefCI')
    alpha = float(darr(args[1]).flat[0]) if len(args) > 1 else 0.05
    est = getattr(m, 'estdisp', True)
    crit = _st().t.ppf(1 - alpha / 2, m.dfe) if est else _st().norm.ppf(1 - alpha / 2)
    return out(np.column_stack([m.b - crit * m.se, m.b + crit * m.se]))


@bi('coefTest', nout=3)
def coefTest(nargout, *args):
    """[p, F, r] = coefTest(mdl, H, c): the F-test of H*b = c (by default, all coefficients but the intercept 0)."""
    nargchk(args, 1, 3, 'coefTest')
    m = _model(args[0], 'coefTest')
    if len(args) > 1:
        H = np.atleast_2d(darr(args[1]))
    else:
        keep = [i for i, nm in enumerate(m.names) if nm != '(Intercept)']
        H = np.eye(m.p)[keep]
    c = darr(args[2]).reshape(-1) if len(args) > 2 else np.zeros(H.shape[0])
    d = H @ m.b - c
    r = np.linalg.matrix_rank(H)
    F = float(d @ np.linalg.pinv(H @ m.cov @ H.T) @ d / r)
    p = float(_st().f.sf(F, r, m.dfe))
    return (p, F, float(r))[:max(nargout, 1)] if nargout > 1 else p


@bi('anova')
def anova(nargout, *args):
    """tbl = anova(mdl) (each term), anova(mdl, 'summary'): the analysis of variance of a linear model."""
    nargchk(args, 1, 3, 'anova')
    m = args[0]
    if not isinstance(m, LinearModel) or isinstance(m, (GeneralizedLinearModel, NonLinearModel)):
        raise err('MATLAB:anova:model', 'anova takes a linear model (fitlm); for groups see anova1 and anovan.', 'anova')
    kind = py_str(args[1]).lower() if len(args) > 1 and is_str(args[1]) else 'component'
    if kind == 'summary':
        k = m.rank - (1 if m.design.intercept else 0)
        F = (m.ssr / k) / m.mse if k > 0 else np.nan
        p = float(_st().f.sf(F, k, m.dfe)) if k > 0 else np.nan
        return _tbl([[m.sst, m.ssr, m.sse], [m.n - 1, k, m.dfe], [m.sst / (m.n - 1), m.ssr / k if k else np.nan, m.mse],
                     [np.nan, F, np.nan], [np.nan, p, np.nan]], ['SumSq', 'DF', 'MeanSq', 'F', 'pValue'], ['Total', 'Model', 'Residual'])
    rows, ss, df = [], [], []
    for ti, t in enumerate(m.design.terms):
        cols = [j for j, g in enumerate(m.groups) if g != ti]
        Xr = m.X[:, cols]
        br, _, _ = _wls(Xr, m.y, m.w)
        sse_r = float(np.sum(m.w * (m.y - Xr @ br) ** 2))
        rows.append(_term_name(t))
        ss.append(sse_r - m.sse)
        df.append(m.p - len(cols))
    ss, df = np.array(ss), np.array(df, float)
    ms = ss / df
    F = ms / m.mse
    p = _st().f.sf(F, df, m.dfe)
    return _tbl([np.append(ss, m.sse), np.append(df, m.dfe), np.append(ms, m.mse), np.append(F, np.nan), np.append(p, np.nan)],
                ['SumSq', 'DF', 'MeanSq', 'F', 'pValue'], rows + ['Error'])


def _b(name, *args):
    return R._builtin(name, *args)


@bi('plotResiduals')
def plotResiduals(nargout, *args):
    """plotResiduals(mdl, plottype): a histogram of the residuals ('histogram'), or them against the fitted values ('fitted'), the row
    number ('caseorder') or the residual before ('lagged'), or a normal probability plot ('probability')."""
    nargchk(args, 1, 2, 'plotResiduals')
    m = _model(args[0], 'plotResiduals')
    kind = py_str(args[1]).lower() if len(args) > 1 else 'histogram'
    r = m.resid
    if kind == 'fitted':
        _b('plot', m.fitted.reshape(-1, 1), r.reshape(-1, 1), Char.of('o'))
        _b('xlabel', Char.of('Fitted values'))
        _b('ylabel', Char.of('Residuals'))
        _b('title', Char.of('Plot of residuals vs. fitted values'))
    elif kind == 'caseorder':
        _b('plot', np.arange(1, r.size + 1, dtype=float).reshape(-1, 1), r.reshape(-1, 1), Char.of('o'))
        _b('xlabel', Char.of('Row number'))
        _b('ylabel', Char.of('Residuals'))
        _b('title', Char.of('Case order plot of residuals'))
    elif kind == 'lagged':
        _b('plot', r[:-1].reshape(-1, 1), r[1:].reshape(-1, 1), Char.of('o'))
        _b('xlabel', Char.of('Residual(t-1)'))
        _b('ylabel', Char.of('Residual(t)'))
        _b('title', Char.of('Plot of residuals vs. lagged residuals'))
    elif kind == 'probability':
        _b('normplot', r.reshape(-1, 1))
    elif kind != 'histogram':
        raise err('MATLAB:plotResiduals:type', "The plot type is 'histogram', 'fitted', 'caseorder', 'lagged' or 'probability'.", 'plotResiduals')
    if kind == 'histogram':
        _b('histogram', r.reshape(-1, 1))
        _b('xlabel', Char.of('Residuals'))
        _b('title', Char.of('Histogram of residuals'))
    return None


def _plot_model(m):
    """plot(mdl): with one numeric predictor, the data, the fit and its confidence bounds; else the response against the fitted values."""
    preds = m.predictor_names() if not isinstance(m, NonLinearModel) else m.xnames
    resp = m.design.data.response if not isinstance(m, NonLinearModel) else m.data
    if len(preds) == 1 and (isinstance(m, NonLinearModel) or not isinstance(m.design.data.cols[preds[0]], tuple)):
        x = (m.Xd[:, 0] if isinstance(m, NonLinearModel) else m.design.data.cols[preds[0]])
        xx = np.linspace(np.nanmin(x), np.nanmax(x), 200)
        y, ci = m.predict(xx.reshape(-1, 1))
        _b('plot', np.asarray(x).reshape(-1, 1), (m.y if not isinstance(m, GeneralizedLinearModel) else m.y).reshape(-1, 1), Char.of('x'))
        _b('hold', Char.of('on'))
        _b('plot', xx.reshape(-1, 1), y.reshape(-1, 1))
        _b('plot', xx.reshape(-1, 1), ci, Char.of(':'))
        _b('hold', Char.of('off'))
        _b('legend', Char.of('Data'), Char.of('Fit'), Char.of('Confidence bounds'))
        _b('xlabel', Char.of(preds[0]))
        _b('ylabel', Char.of(resp))
        _b('title', Char.of(f'{resp} vs. {preds[0]}'))
    else:
        _b('plot', m.fitted.reshape(-1, 1), m.y.reshape(-1, 1), Char.of('x'))
        lo, hi = float(np.nanmin(m.fitted)), float(np.nanmax(m.fitted))
        _b('hold', Char.of('on'))
        _b('plot', np.array([[lo], [hi]]), np.array([[lo], [hi]]))
        _b('hold', Char.of('off'))
        _b('xlabel', Char.of('Fitted values'))
        _b('ylabel', Char.of(resp))
        _b('title', Char.of(f'{resp} against the fitted values'))
    return None


# ---- regress, robustfit, ridge, glmfit, glmval -----------------------------------------------------------------------------------

@bi('regress', nout=5)
def regress(nargout, *args):
    """[b, bint, r, rint, stats] = regress(y, X, alpha): least squares of y on the columns of X (a column of ones for an intercept)."""
    nargchk(args, 2, 3, 'regress')
    y = darr(args[0], 'regress').reshape(-1)
    X = darr(args[1], 'regress')
    alpha = float(darr(args[2]).flat[0]) if len(args) > 2 else 0.05
    ok = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    Xo, yo = X[ok], y[ok]
    n, p = Xo.shape
    b, _, rank, _ = np.linalg.lstsq(Xo, yo, rcond=None)
    r = np.full(y.size, np.nan)
    r[ok] = yo - Xo @ b
    dfe = n - rank
    sse = float(np.sum(r[ok] ** 2))
    s2 = sse / dfe if dfe > 0 else np.nan
    inv = np.linalg.pinv(Xo.T @ Xo)
    se = np.sqrt(np.maximum(np.diag(inv) * s2, 0))
    tc = _st().t.ppf(1 - alpha / 2, dfe) if dfe > 0 else np.nan
    bint = np.column_stack([b - tc * se, b + tc * se])
    res = [out(b.reshape(-1, 1)), out(bint)]
    if nargout > 2:
        res.append(out(r.reshape(-1, 1)))
    if nargout > 3:
        h = np.einsum('ij,jk,ik->i', Xo, inv, Xo)
        with np.errstate(all='ignore'):
            s_i = np.sqrt(np.maximum((sse - r[ok] ** 2 / (1 - h)) / (dfe - 1), 0))
        tci = _st().t.ppf(1 - alpha / 2, dfe - 1) if dfe > 1 else np.nan
        half = tci * s_i * np.sqrt(1 - h)
        rint = np.full((y.size, 2), np.nan)
        rint[ok] = np.column_stack([r[ok] - half, r[ok] + half])
        res.append(out(rint))
    if nargout > 4:
        sst = float(np.sum((yo - yo.mean()) ** 2))
        r2 = 1 - sse / sst if sst > 0 else np.nan
        k = rank - 1
        F = ((sst - sse) / k) / s2 if k > 0 else np.nan
        pF = float(_st().f.sf(F, k, dfe)) if k > 0 else np.nan
        res.append(out(np.array([[r2, F, pF, s2]])))
    return tuple(res[:max(nargout, 1)]) if nargout > 1 else res[0]


@bi('robustfit', nout=2)
def robustfit(nargout, *args):
    """[b, stats] = robustfit(X, y, wfun, tune, const): robust regression (bisquare weights unless asked), an intercept first."""
    nargchk(args, 2, 5, 'robustfit')
    X = darr(args[0], 'robustfit')
    X = X.T if X.shape[0] == 1 and X.shape[1] > 1 else X
    y = darr(args[1], 'robustfit').reshape(-1)
    wfun = py_str(args[2]).lower() if len(args) > 2 and numel(args[2]) else 'bisquare'
    tune = float(darr(args[3]).flat[0]) if len(args) > 3 and numel(args[3]) else None
    const = not (len(args) > 4 and is_str(args[4]) and py_str(args[4]).lower() == 'off')
    ok = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    A = np.column_stack([np.ones(ok.sum()), X[ok]]) if const else X[ok]
    yo = y[ok]
    if wfun == 'ols':
        b, _, _ = _wls(A, yo, np.ones(yo.size))
        w, s = np.ones(yo.size), None
    else:
        b, w, s = _robust(A, yo, np.ones(yo.size), wfun, tune)
    if nargout < 2:
        return out(b.reshape(-1, 1))
    r = yo - A @ b
    p = A.shape[1]
    dfe = yo.size - p
    s_ = s if s is not None else math.sqrt(float(np.sum(r ** 2)) / dfe)
    inv = np.linalg.pinv((A * w[:, None]).T @ A)
    se = np.sqrt(np.maximum(np.diag(inv), 0)) * s_
    with np.errstate(all='ignore'):
        t = b / se
    stats = Struct.scalar({'s': float(s_), 'se': out(se.reshape(-1, 1)), 't': out(t.reshape(-1, 1)),
                           'p': out((2 * _st().t.sf(np.abs(t), dfe)).reshape(-1, 1)), 'w': out(w.reshape(-1, 1)),
                           'resid': out(r.reshape(-1, 1)), 'dfe': float(dfe), 'covb': out(inv * s_ ** 2),
                           'ols_s': math.sqrt(float(np.sum((yo - A @ _wls(A, yo, np.ones(yo.size))[0]) ** 2)) / dfe)})
    return out(b.reshape(-1, 1)), stats


@bi('ridge')
def ridge(nargout, *args):
    """b = ridge(y, X, k, scaled): ridge regression for each k; for standardized predictors (scaled 1, the default) or on the data's scale with an intercept first (scaled 0)."""
    nargchk(args, 3, 4, 'ridge')
    y = darr(args[0], 'ridge').reshape(-1)
    X = darr(args[1], 'ridge')
    ks = darr(args[2]).reshape(-1)
    scaled = bool(darr(args[3]).flat[0]) if len(args) > 3 else True
    ok = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    X, y = X[ok], y[ok]
    mx, sx = X.mean(axis=0), X.std(axis=0, ddof=1)
    Z = (X - mx) / sx
    yc = y - y.mean()
    p = X.shape[1]
    B = np.column_stack([np.linalg.solve(Z.T @ Z + k * np.eye(p), Z.T @ yc) for k in ks])
    if scaled:
        return out(B)
    Bo = B / sx[:, None]
    b0 = y.mean() - mx @ Bo
    return out(np.vstack([b0.reshape(1, -1), Bo]))


@bi('glmfit', nout=3)
def glmfit(nargout, *args):
    """[b, dev, stats] = glmfit(X, y, distr, 'link', l, 'constant', 'on'|'off'): a generalized linear model's coefficients."""
    nargchk(args, 3, 14, 'glmfit')
    opts, rest = _opts(list(args[3:]), ('link', 'constant', 'weights', 'estdisp', 'offset', 'B0'))
    X = darr(args[0], 'glmfit')
    X = X.T if X.shape[0] == 1 and X.shape[1] > 1 else X
    y = darr(args[1], 'glmfit')
    dist = py_str(args[2]).lower()
    if dist not in _CANON:
        raise err('MATLAB:glmfit:distribution', "The distribution is 'normal', 'binomial', 'poisson', 'gamma' or 'inverse gaussian'.", 'glmfit')
    lk = opts.get('link')
    link = _link(_CANON[dist] if lk is None else (py_str(lk) if is_str(lk) else float(darr(lk).flat[0])))
    const = not ('constant' in opts and py_str(opts['constant']).lower() == 'off')
    if y.ndim == 2 and y.shape[1] == 2:
        N, yv = y[:, 1].astype(float), y[:, 0] / y[:, 1]
    else:
        N, yv = np.ones(y.size), y.reshape(-1).astype(float)
    w = darr(opts['weights']).reshape(-1) if 'weights' in opts else np.ones(yv.size)
    A = np.column_stack([np.ones(yv.size), X]) if const else X
    b, mu, eta, dev, inv, rank, _ = _irls(A, yv, dist, link, N, w)
    if nargout < 2:
        return out(b.reshape(-1, 1))
    dfe = yv.size - rank
    V = _variance(dist, mu, N)
    pear = (yv - mu) / np.sqrt(V / w)
    est = dist not in ('binomial', 'poisson') or ('estdisp' in opts and py_str(opts['estdisp']).lower() == 'on')
    s2 = float(np.sum(pear ** 2) / dfe) if est and dfe > 0 else 1.0
    covb = s2 * inv
    se = np.sqrt(np.maximum(np.diag(covb), 0))
    with np.errstate(all='ignore'):
        t = b / se
    p = 2 * (_st().t.sf(np.abs(t), dfe) if est else _st().norm.sf(np.abs(t)))
    stats = Struct.scalar({'beta': out(b.reshape(-1, 1)), 'dfe': float(dfe), 'sfit': math.sqrt(float(np.sum(pear ** 2) / dfe)) if dfe > 0 else np.nan,
                           's': math.sqrt(s2), 'estdisp': bool(est), 'covb': out(covb), 'se': out(se.reshape(-1, 1)), 't': out(t.reshape(-1, 1)),
                           'p': out(p.reshape(-1, 1)), 'resid': out((yv - mu).reshape(-1, 1)), 'residp': out(pear.reshape(-1, 1)),
                           'residd': out((np.sign(yv - mu) * np.sqrt(np.maximum([_deviance(dist, yv[i:i + 1], mu[i:i + 1], N[i:i + 1], np.ones(1)) for i in range(yv.size)], 0))).reshape(-1, 1))})
    return (out(b.reshape(-1, 1)), dev, stats)[:nargout]


@bi('glmval', nout=3)
def glmval(nargout, *args):
    """[yhat, dylo, dyhi] = glmval(b, X, link, stats, ...): a generalized linear model's predictions (with bounds from glmfit's stats)."""
    nargchk(args, 3, 12, 'glmval')
    b = darr(args[0], 'glmval').reshape(-1)
    X = darr(args[1], 'glmval')
    X = X.T if X.shape[0] == 1 and X.shape[1] == b.size - 1 and X.shape[1] > 1 else X
    lk = args[2]
    link = _link(py_str(lk) if is_str(lk) else float(darr(lk).flat[0]))
    opts, rest = _opts(list(args[3:]), ('confidence', 'size', 'offset', 'constant', 'simultaneous'))
    const = not ('constant' in opts and py_str(opts['constant']).lower() == 'off')
    A = np.column_stack([np.ones(X.shape[0]), X]) if const else X
    eta = A @ b
    yhat = link[3](eta)
    N = darr(opts['size']).reshape(-1) if 'size' in opts else 1.0
    if nargout < 2:
        return out((yhat * N).reshape(-1, 1))
    stats = rest[0] if rest else None
    if not isinstance(stats, Struct):
        raise err('MATLAB:glmval:stats', 'Bounds need the stats glmfit gives.', 'glmval')
    covb = darr(stats.get1('covb'))
    conf = float(darr(opts['confidence']).flat[0]) if 'confidence' in opts else 0.95
    est = bool(stats.get1('estdisp'))
    dfe = float(darr(stats.get1('dfe')).flat[0])
    crit = _st().t.ppf((1 + conf) / 2, dfe) if est else _st().norm.ppf((1 + conf) / 2)
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', A, covb, A), 0))
    lo, hi = link[3](eta - crit * se), link[3](eta + crit * se)
    lo, hi = np.minimum(lo, hi), np.maximum(lo, hi)
    return out((yhat * N).reshape(-1, 1)), out(((yhat - lo) * N).reshape(-1, 1)), out(((hi - yhat) * N).reshape(-1, 1))


# ---- nonlinear least squares ----------------------------------------------------------------------------------------------------

@bi('nlinfit', nout=5)
def nlinfit(nargout, *args):
    """[beta, R, J, CovB, MSE] = nlinfit(X, y, modelfun, beta0): nonlinear least squares (Levenberg-Marquardt)."""
    nargchk(args, 4, 12, 'nlinfit')
    X = darr(args[0], 'nlinfit')
    y = darr(args[1], 'nlinfit')
    f = args[2]
    if not isinstance(f, FH):
        raise err('MATLAB:nlinfit:modelfun', 'The model is a function handle, as @(b, x) b(1)*exp(-b(2)*x).', 'nlinfit')
    b0 = darr(args[3], 'nlinfit')
    opts, _ = _opts(list(args[4:]), ('Weights', 'Options', 'ErrorModel'))
    w = darr(opts['Weights']).reshape(-1) if 'Weights' in opts else np.ones(y.size)
    beta, R_, J, cov, mse, _ = _nlfit(X, y.reshape(-1).astype(float), f, b0.reshape(-1).astype(float), w)
    res = [out(beta.reshape(b0.shape)), out(R_.reshape(y.shape)), out(J), out(cov), mse]
    return tuple(res[:max(nargout, 1)]) if nargout > 1 else res[0]


@bi('nlparci')
def nlparci(nargout, *args):
    """ci = nlparci(beta, R, 'Jacobian', J) or nlparci(beta, R, 'Covar', CovB): confidence intervals of nonlinear least-squares estimates."""
    nargchk(args, 4, 6, 'nlparci')
    beta = darr(args[0]).reshape(-1)
    R_ = darr(args[1]).reshape(-1)
    opts, _ = _opts(list(args[2:]), ('Jacobian', 'Covar', 'alpha'))
    n, p = R_.size, beta.size
    dfe = n - p
    if 'Covar' in opts:
        cov = darr(opts['Covar'])
    elif 'Jacobian' in opts:
        J = darr(opts['Jacobian'])
        cov = float(np.sum(R_ ** 2) / dfe) * np.linalg.pinv(J.T @ J)
    else:
        raise err('MATLAB:nlparci:args', "nlparci needs 'Jacobian', J or 'Covar', CovB.", 'nlparci')
    alpha = float(darr(opts['alpha']).flat[0]) if 'alpha' in opts else 0.05
    se = np.sqrt(np.maximum(np.diag(cov), 0))
    tc = _st().t.ppf(1 - alpha / 2, dfe)
    return out(np.column_stack([beta - tc * se, beta + tc * se]))


@bi('nlpredci', nout=2)
def nlpredci(nargout, *args):
    """[ypred, delta] = nlpredci(modelfun, X, beta, R, 'Covar', CovB (or 'Jacobian', J), 'PredOpt', 'curve'|'observation'): predictions and the half widths of their intervals."""
    nargchk(args, 4, 14, 'nlpredci')
    f, X = args[0], darr(args[1], 'nlpredci')
    beta = darr(args[2]).reshape(-1)
    R_ = darr(args[3]).reshape(-1)
    opts, _ = _opts(list(args[4:]), ('Covar', 'Jacobian', 'MSE', 'PredOpt', 'SimOpt', 'Alpha'))
    n, p = R_.size, beta.size
    dfe = n - p
    mse = float(darr(opts['MSE']).flat[0]) if 'MSE' in opts else float(np.sum(R_ ** 2) / dfe)
    if 'Covar' in opts:
        cov = darr(opts['Covar'])
    elif 'Jacobian' in opts:
        J0 = darr(opts['Jacobian'])
        cov = mse * np.linalg.pinv(J0.T @ J0)
    else:
        raise err('MATLAB:nlpredci:args', "nlpredci needs 'Covar', CovB or 'Jacobian', J.", 'nlpredci')
    y = _call_model(f, beta, X)
    J = _jacobian(f, beta, X, y)
    var = np.einsum('ij,jk,ik->i', J, cov, J)
    if 'PredOpt' in opts and py_str(opts['PredOpt']).lower() == 'observation':
        var = var + mse
    alpha = float(darr(opts['Alpha']).flat[0]) if 'Alpha' in opts else 0.05
    sim = 'SimOpt' in opts and py_str(opts['SimOpt']).lower() == 'on'
    crit = math.sqrt(p * _st().f.ppf(1 - alpha, p, dfe)) if sim else _st().t.ppf(1 - alpha / 2, dfe)
    d = crit * np.sqrt(np.maximum(var, 0))
    return (out(y.reshape(-1, 1)), out(d.reshape(-1, 1))) if nargout > 1 else out(y.reshape(-1, 1))


# ---- partialcorr, randg ---------------------------------------------------------------------------------------------------------

@bi('partialcorr', nout=2)
def partialcorr(nargout, *args):
    """[rho, pval] = partialcorr(X), partialcorr(x, z), partialcorr(x, y, z), partialcorr(..., 'Type', 'Spearman'): correlations with the other variables (or z) held fixed."""
    nargchk(args, 1, 7, 'partialcorr')
    opts, rest = _opts(list(args), ('Type', 'Rows', 'Tail'))
    rank = 'Type' in opts and py_str(opts['Type']).lower() == 'spearman'
    st = _st()

    def prep(a):
        a = darr(a, 'partialcorr')
        a = a.reshape(-1, 1) if a.ndim == 1 or (a.shape[0] == 1 and a.shape[1] > 1) else a
        return np.apply_along_axis(st.rankdata, 0, a) if rank else a
    if len(rest) == 1:
        X = prep(rest[0])
        C = np.corrcoef(X, rowvar=False)
        P = np.linalg.pinv(C)
        d = np.sqrt(np.diag(P))
        rho = -P / np.outer(d, d)
        np.fill_diagonal(rho, 1.0)
        k = X.shape[1] - 2
        n = X.shape[0]
    else:
        if len(rest) == 2:
            # partialcorr(x, z): the columns of x with each other, z held fixed
            x = y = prep(rest[0])
            Z = prep(rest[1])
        else:
            x, y, Z = prep(rest[0]), prep(rest[1]), prep(rest[2])
        Zc = np.column_stack([np.ones(x.shape[0]), Z])

        def resid(a):
            b = np.linalg.lstsq(Zc, a, rcond=None)[0]
            return a - Zc @ b
        rx, ry = resid(x), resid(y)
        rx, ry = rx - rx.mean(0), ry - ry.mean(0)
        rho = (rx.T @ ry) / np.outer(np.sqrt(np.sum(rx ** 2, 0)), np.sqrt(np.sum(ry ** 2, 0)))
        k = Z.shape[1]
        n = x.shape[0]
    df = n - 2 - k
    with np.errstate(all='ignore'):
        t = rho * np.sqrt(df / np.maximum(1 - rho ** 2, 1e-300))
    p = 2 * st.t.sf(np.abs(t), df)
    if len(rest) <= 2:
        np.fill_diagonal(rho, 1.0)
        np.fill_diagonal(p, 0.0)
    return (out(rho), out(p)) if nargout > 1 else out(rho)


@bi('randg')
def randg(nargout, *args):
    """r = randg(a, sz...): gamma random numbers of shape a and scale 1 (from the language's generator)."""
    a = args[0] if args else 1.0
    return R._builtin('gamrnd', a, 1.0, *args[1:]) if len(args) > 1 or numel(a) != 1 else R._builtin('gamrnd', a, 1.0)


# ---- models through the builtins: feval(mdl, X), plot(mdl), disp ---------------------------------------------------------------

def _wrap(name, test, handler):
    info = REG[name]
    orig = info.fn
    ws, aw = info.ws, info.aw
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = f


def _feval_model(nargout, m, *rest):
    if isinstance(m, NonLinearModel):
        X = darr(rest[0]) if len(rest) == 1 else np.column_stack([darr(v).reshape(-1) for v in rest])
        return out(_call_model(m.f, m.b, X).reshape(-1, 1))
    X = rest[0] if len(rest) == 1 else out(np.column_stack([darr(v).reshape(-1) for v in rest]))
    return out(m.predict(X)[0].reshape(-1, 1))


_wrap('feval', lambda v: isinstance(v, LinearModel), _feval_model)
_wrap('plot', lambda v: isinstance(v, LinearModel), lambda nargout, m, *rest: _plot_model(m))
