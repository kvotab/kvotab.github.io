"""Analyze > Fit Model: the mixed models (REML), JMP's Mixed Model personality
and Standard Least Squares with random effects.

The names the page calls:

  fitmodel.mixed        the report: Fit Statistics (or Summary of Fit), the
                        random effects' covariance parameters, the repeated
                        structure's, the fixed effects' estimates and tests
                        (Kenward-Roger by default, Satterthwaite), the random
                        effects' predictions (BLUPs with prediction errors),
                        Random Coefficients, the diagnostics' values
  mixed.lsmeans         least squares means of a fixed effect (the mixed
                        covariance, Kenward-Roger or Satterthwaite df)
  mixed.compare         LSMeans Student's t and Tukey HSD, connecting letters
  mixed.contrast        LSMeans Contrast
  mixed.slices          Test Slices of an interaction
  mixed.structures      Compare Structures: the repeated structures by AICc/BIC
  mixed.variogram       the semivariogram of the marginal residuals
  mixed.simulate        Simulate: power and interval coverage from the model
  mixed.save            Save Columns and the formulas, for every row
  mixed.profile_ci      profile-likelihood intervals of the covariance
                        parameters
  mixed.skeleton        the Skeleton ANOVA (df per source)

The estimation is this module's own (numpy, scipy): JMP's Unbounded
Variance Components (on by default) lets a variance component go below
zero as long as V = Var(y) stays positive definite, which statsmodels'
MixedLM does not allow; JMP's repeated structures, correlated random
coefficients, Kenward-Roger's adjustment and the generalized linear mixed
models (RSPL) are not in statsmodels either. fit_model.py keeps names that
delegate here (_mixed_model, _reml, _satterthwaite, _mixed_predict,
_mixed_fit_code, _mixed_plots, _mixed_interaction_parts, mixed), so its
profilers and interaction plots use this module's fit.
"""
import itertools
import math
import re

import numpy as np
import pandas as pd
from scipy import stats

from . import data, models
from . import profile as profile_mod
from .registry import api
from .util import one_line
from .fit_model import (AVG, FIT, J, PLT, Coder, _attach, _code_frame, _design, _eff_of, _effect_of, _factor_names,
                        _factors, _key, _letters, _lvl, _pylit, _q, _row_plot, _setting, _spec, _tlabel, _uncenter)

# ---------------------------------------------------------------------------
# The REML engine
# ---------------------------------------------------------------------------
#
# The model is y = X b + Z u + e, u ~ N(0, G), e ~ N(0, R), so that
# V = Var(y) = Z G Z' + R. G is block diagonal over the random effects: a
# variance component s2 I for each random effect (JMP's variance components,
# which may be negative as long as V stays positive definite: Unbounded
# Variance Components), or an unstructured c x c matrix per subject for a
# group of correlated random coefficients (I (x) Sigma). R is block diagonal
# over subjects: the residual variance s2 W^-1 (W the weights), or one of
# JMP's repeated structures within each subject.
#
# The rows are cut into blocks such that V is block diagonal over them: the
# subjects of the repeated structure, joined by every random effect whose
# levels stay within a block of moderate size ("absorbed"). A random effect
# that would join too many rows (crossed effects of a large table) stays
# out as a low-rank part: V = B + Zl Gl Zl' with B block diagonal, and
# V^-1 = B^-1 - U K U' (U = B^-1 Zl, K = Gl (I + M Gl)^-1, M = Zl' U) by
# Woodbury's identity in a form that needs no Gl^-1, so that negative or
# zero variances are fine. P = V^-1 - V^-1 X (X'V^-1 X)^-1 X'V^-1 is then
# B^-1 - L Q L' with L = [U, V^-1 X] and Q = diag(K, (X'V^-1 X)^-1), and
# every trace the REML score and information need is a sum over blocks of
# small matrices plus products of the thin L (Searle, Casella and
# McCulloch 1992, ch. 6; the derivatives as in Harville 1977).
#
# Parameters are natural (a variance, a covariance, a correlation, a
# range); the optimizer works on a transform of each (a variance on the
# log scale, a correlation through tanh, an unstructured matrix by its
# log-Cholesky factor, an unbounded variance component as it is) and takes
# Fisher scoring steps, then Newton steps with the observed information,
# halving a step that does not raise the REML log-likelihood or leaves V
# not positive definite.

_BLOCK_MAX = 240       # rows a block may reach when a random effect is absorbed into the blocks
_DENSE_ALL = 400       # up to this many rows every random effect is absorbed (one block at most this large)
_LOW_MAX = 6_000_000   # rows x levels of the low-rank part the engine takes
_AI_BLOCK = 250        # a block larger than this: average-information steps (n^2 per parameter, not n^3)
_LOG2PI = math.log(2 * math.pi)


class _Par:
    """One covariance parameter: its report name, the side it belongs to (G:
    random effects, R: repeated / residual), what it is, and how the
    optimizer moves it."""
    __slots__ = ('label', 'side', 'kind', 'tr', 'subject', 'group', 'linear', 'fixed', 'value')

    def __init__(self, label, side, kind, tr, subject='', group=None, linear=True):
        self.label, self.side, self.kind, self.tr = label, side, kind, tr
        self.subject, self.group, self.linear = subject, group, linear
        self.fixed, self.value = False, None


def _vech(c):
    return [(i, j) for i in range(c) for j in range(i + 1)]


class _GComp:
    """A random effect: rows' levels (codes, -1 for none) times the values of
    its coefficients (vals, n x c: 1 for an intercept, the column's values for
    a slope). c == 1: a variance component, G = s2 I; c > 1: correlated random
    coefficients, G = I (x) Sigma with Sigma unstructured (vech order)."""

    def __init__(self, label, codes, vals, levels, coefs, pidx, subject=''):
        self.label = label
        self.codes = np.asarray(codes, dtype=np.int64)
        self.vals = np.asarray(vals, dtype=float).reshape(len(self.codes), -1)
        self.c = self.vals.shape[1]
        self.levels = levels            # labels of the levels (subjects)
        self.nl = len(levels)
        self.q = self.nl * self.c
        self.coefs = coefs              # the coefficients' names
        self.pidx = list(pidx)
        self.subject = subject

    def sigma(self, theta):
        c = self.c
        S = np.zeros((c, c))
        for k, (i, j) in zip(self.pidx, _vech(c)):
            S[i, j] = S[j, i] = theta[k]
        return S

    def zt(self, v):
        """Z'v for a vector or an n x k matrix, as nl x c (x k)."""
        v = np.asarray(v, dtype=float)
        ok = self.codes >= 0
        if v.ndim == 1:
            out = np.zeros((self.nl, self.c))
            for a in range(self.c):
                out[:, a] = np.bincount(self.codes[ok], weights=(self.vals[ok, a] * v[ok]), minlength=self.nl)
            return out.reshape(-1)
        out = np.zeros((self.nl, self.c, v.shape[1]))
        for a in range(self.c):
            np.add.at(out[:, a, :], self.codes[ok], self.vals[ok, a][:, None] * v[ok])
        return out.reshape(self.q, v.shape[1])

    def dense(self):
        n = len(self.codes)
        Z = np.zeros((n, self.q))
        ok = self.codes >= 0
        for a in range(self.c):
            Z[np.arange(n)[ok], self.codes[ok] * self.c + a] = self.vals[ok, a]
        return Z

    def sparse(self):
        from scipy import sparse
        n = len(self.codes)
        ok = self.codes >= 0
        r = np.repeat(np.arange(n)[ok], self.c)
        cidx = (self.codes[ok][:, None] * self.c + np.arange(self.c)[None, :]).reshape(-1)
        return sparse.csr_matrix((self.vals[ok].reshape(-1), (r, cidx)), shape=(n, self.q))


# ---- the repeated (R-side) structures ---------------------------------------------------------------------

_R_LABEL = {'residual': 'Residual', 'uneqvar': 'Unequal Variances', 'un': 'Unstructured', 'ar1': 'AR(1)', 'cs': 'Compound Symmetry',
            'antevar': 'Antedependent Equal Variance', 'toep': 'Toeplitz', 'csh': 'Compound Symmetry Unequal Variances',
            'ante': 'Antedependent', 'toeph': 'Toeplitz Unequal Variances', 'arh': 'AR(1) Unequal Variances',
            'sp': 'Spatial', 'spn': 'Spatial with Nugget'}
_SP_LABEL = {'pow': 'Power', 'exp': 'Exponential', 'gau': 'Gaussian', 'sph': 'Spherical'}
_R_CATEG = {'uneqvar', 'un', 'cs', 'antevar', 'toep', 'csh', 'ante', 'toeph'}      # need the levels of a Repeated column
_R_UNEQ = {'uneqvar', 'csh', 'ante', 'toeph', 'arh'}                                 # a variance for each level


def _powcorr(rho, d):
    """rho ** d and its derivative in rho (AR(1) and the power spatial
    correlation); d is 0 on the diagonal. rho may be negative only when
    every d is a whole number (the caller keeps it positive otherwise)."""
    if rho == 0:
        return (d == 0).astype(float), (d == 1).astype(float)
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        F = np.power(rho, d)
        dF = np.where(d > 0, d * np.power(rho, d - 1), 0.0)
    return F, dF


class _RStruct:
    """The residual covariance R, block diagonal over subjects. kind is one
    of _R_LABEL's keys; sub the subject of each row; lev the level index of
    the Repeated column (categorical structures; J levels, lev_names their
    labels); t the time (AR(1)); coords the coordinates (spatial); winv the
    reciprocal weights; fixed_scale a residual variance held fixed (the
    binomial and Poisson pseudo-data, scale 1)."""

    def __init__(self, kind, n, pidx, sub=None, lev=None, lev_names=(), t=None, coords=None, sptype='exp', winv=None,
                 fixed_scale=None, rep_name=''):
        self.kind = kind
        self.n = n
        self.pidx = list(pidx)
        self.sub = np.arange(n) if sub is None else np.asarray(sub, dtype=np.int64)
        self.lev = None if lev is None else np.asarray(lev, dtype=np.int64)
        self.J = len(lev_names)
        self.lev_names = list(lev_names)
        self.t = None if t is None else np.asarray(t, dtype=float)
        self.coords = None if coords is None else np.asarray(coords, dtype=float).reshape(n, -1)
        self.sptype = sptype
        self.winv = np.ones(n) if winv is None else np.asarray(winv, dtype=float)
        self.fixed_scale = fixed_scale
        self.rep_name = rep_name

    # parameters, in the order the structure uses them ----------------------------------------------------
    @staticmethod
    def params(kind, J=0, sptype='exp', rep_name='', lev_names=(), fixed_scale=None, subject=''):
        """The structure's parameters, JMP's names."""
        P = []
        vname = [f'Var({v})' for v in lev_names]

        def var(label, tr='log'):
            P.append(_Par(label, 'R', 'var', tr, subject))

        def corr(label, linear=False, tr='tanh'):
            P.append(_Par(label, 'R', 'corr', tr, subject, linear=linear))
        rn = f' {rep_name}' if rep_name else ''
        if kind == 'residual':
            if fixed_scale is None:
                var('Residual')
        elif kind == 'uneqvar':
            for v in vname:
                var(v)
        elif kind == 'un':
            for i, j in _vech(J):
                if i == j:
                    var(vname[i])
                else:
                    P.append(_Par(f'Cov({lev_names[j]},{lev_names[i]})', 'R', 'cov', 'chol', subject, group='un'))
            for p in P:
                p.tr = 'chol'
                p.group = 'un'
        elif kind == 'cs':
            corr('Compound Symmetry')
            var('Residual')
        elif kind in ('ar1', 'arh'):
            if kind == 'arh':
                for v in vname:
                    var(v)
            corr(f'AR(1){rn}')
            if kind == 'ar1':
                var('Residual')
        elif kind in ('toep', 'toeph'):
            if kind == 'toeph':
                for v in vname:
                    var(v)
            for h in range(1, max(J, 1)):
                corr(f'Toeplitz {h}')
            if kind == 'toep':
                var('Residual')
        elif kind in ('ante', 'antevar'):
            if kind == 'ante':
                for v in vname:
                    var(v)
            for h in range(1, max(J, 1)):
                corr(f'Antedependent ({lev_names[h - 1]},{lev_names[h]})' if lev_names else f'Antedependent {h}')
            if kind == 'antevar':
                var('Residual')
        elif kind == 'csh':
            for v in vname:
                var(v)
            corr('Compound Symmetry')
        elif kind in ('sp', 'spn'):
            P.append(_Par(f'Spatial {_SP_LABEL[sptype]}', 'R', 'range', 'logit' if sptype == 'pow' else 'log', subject, linear=False))
            if kind == 'spn':
                P.append(_Par('Nugget', 'R', 'nugget', 'log', subject, linear=False))
            var('Residual')
        for p in P:
            if p.kind in ('corr',) or kind in ('sp', 'spn', 'ar1', 'arh', 'toep', 'toeph', 'ante', 'antevar', 'csh'):
                p.linear = p.linear and kind not in ('ar1', 'arh', 'toep', 'toeph', 'ante', 'antevar', 'csh', 'sp', 'spn')
        return P

    def prepare(self, rows):
        """Arrays for one group of blocks (rows: nb x m row numbers)."""
        sub = self.sub[rows]
        same = sub[:, :, None] == sub[:, None, :]
        sw = np.sqrt(self.winv[rows])
        g = {'same': same, 'sw2': sw[:, :, None] * sw[:, None, :], 'eye': np.broadcast_to(np.eye(rows.shape[1], dtype=bool), same.shape)}
        if self.lev is not None:
            lv = self.lev[rows]
            g['lev'] = lv
            g['lag'] = np.abs(lv[:, :, None] - lv[:, None, :])
            g['lo'] = np.minimum(lv[:, :, None], lv[:, None, :])
            g['hi'] = np.maximum(lv[:, :, None], lv[:, None, :])
        if self.kind in ('ar1', 'arh'):
            tv = self.t[rows]
            g['dist'] = np.abs(tv[:, :, None] - tv[:, None, :])
        if self.kind in ('sp', 'spn'):
            c = self.coords[rows]
            g['dist'] = np.sqrt(np.sum((c[:, :, None, :] - c[:, None, :, :]) ** 2, axis=-1))
        return g

    def block(self, theta, g):
        """R over a group of blocks and its derivatives: (R, [(k, dR)])."""
        th = [theta[k] for k in self.pidx]
        same, sw2, eye = g['same'], g['sw2'], g['eye']
        kind = self.kind
        D = []
        if kind == 'residual':
            base = np.where(eye, sw2, 0.0)
            if self.fixed_scale is not None:
                return self.fixed_scale * base, D
            D.append((self.pidx[0], base))
            return th[0] * base, D
        J = self.J
        if kind == 'uneqvar':
            lv = g['lev']
            R = np.zeros(same.shape)
            for t in range(J):
                m = eye & (lv[:, :, None] == t)
                Dt = np.where(m, sw2, 0.0)
                D.append((self.pidx[t], Dt))
                R += th[t] * Dt
            return R, D
        if kind == 'un':
            lv = g['lev']
            R = np.zeros(same.shape)
            li, lj = lv[:, :, None], lv[:, None, :]
            for k, (a, b) in zip(self.pidx, _vech(J)):
                m = same & (((li == a) & (lj == b)) | ((li == b) & (lj == a)))
                Dk = np.where(m, sw2, 0.0)
                D.append((k, Dk))
                R += theta[k] * Dk
            return R, D
        # the structures with a correlation matrix C (times variances)
        if kind in ('ar1', 'arh'):
            rho = th[J] if kind == 'arh' else th[0]
            F, dF = _powcorr(rho, g['dist'])
            C = np.where(same, F, 0.0)
            dC = [np.where(same, dF, 0.0)]
            cidx = [self.pidx[J] if kind == 'arh' else self.pidx[0]]
        elif kind in ('toep', 'toeph'):
            off = J if kind == 'toeph' else 0
            lag = g['lag']
            C = np.where(same & (lag == 0), 1.0, 0.0)
            dC, cidx = [], []
            for h in range(1, J):
                m = same & (lag == h)
                C = C + np.where(m, th[off + h - 1], 0.0)
                dC.append(np.where(m, 1.0, 0.0))
                cidx.append(self.pidx[off + h - 1])
        elif kind in ('ante', 'antevar'):
            off = J if kind == 'ante' else 0
            rhos = np.array([th[off + h] for h in range(J - 1)])
            lo, hi = g['lo'], g['hi']
            # the product of the adjacent correlations from lo to hi - 1
            cum = np.concatenate([[0.0], np.cumsum(np.log(np.abs(rhos) + 1e-300))])
            sgn = np.concatenate([[1.0], np.cumprod(np.sign(rhos) + (rhos == 0))])
            with np.errstate(over='ignore', invalid='ignore'):
                prod = np.exp(cum[hi] - cum[lo]) * sgn[hi] / sgn[lo]
            prod = np.where(lo == hi, 1.0, prod)
            C = np.where(same, prod, 0.0)
            dC, cidx = [], []
            for h in range(J - 1):
                inside = same & (lo <= h) & (hi > h)
                # d prod / d rho_h: the product without rho_h
                with np.errstate(divide='ignore', invalid='ignore'):
                    wo = np.where(np.abs(rhos[h]) > 1e-12, prod / rhos[h], self._ante_without(rhos, lo, hi, h))
                dC.append(np.where(inside, wo, 0.0))
                cidx.append(self.pidx[off + h])
        elif kind in ('cs', 'csh'):
            rho = th[J] if kind == 'csh' else th[0]
            C = np.where(same, np.where(eye, 1.0, rho), 0.0)
            dC = [np.where(same & ~eye, 1.0, 0.0)]
            cidx = [self.pidx[J] if kind == 'csh' else self.pidx[0]]
        elif kind in ('sp', 'spn'):
            rho = th[0]
            d = g['dist']
            F, dF = self._spatial(d, rho)
            C = np.where(same, F, 0.0)
            dC, cidx = [np.where(same, dF, 0.0)], [self.pidx[0]]
            if kind == 'spn':
                nug = th[1]
                C = C + np.where(eye, nug, 0.0)
                dC.append(np.where(eye, 1.0, 0.0))
                cidx.append(self.pidx[1])
        else:
            raise ValueError(f'unknown repeated structure {kind}')
        if kind in _R_UNEQ:
            lv = g['lev']
            sd = np.sqrt(np.maximum([th[t] for t in range(J)], 0.0))
            s = sd[lv]                                   # nb x m
            S2 = s[:, :, None] * s[:, None, :] * sw2
            R = C * S2
            for k, dCk in zip(cidx, dC):
                D.append((k, dCk * S2))
            for t in range(J):
                # d(s_i s_j)/d var_t = (1[i=t] s_j + 1[j=t] s_i) / (2 s_t)
                mi = (lv == t).astype(float)
                num = mi[:, :, None] * s[:, None, :] + s[:, :, None] * mi[:, None, :]
                D.append((self.pidx[t], C * num * sw2 / (2 * max(sd[t], 1e-300))))
            return R, D
        s2 = th[-1]
        R = s2 * C * sw2
        for k, dCk in zip(cidx, dC):
            D.append((k, s2 * dCk * sw2))
        D.append((self.pidx[-1], C * sw2))
        return R, D

    @staticmethod
    def _ante_without(rhos, lo, hi, h):
        r = rhos.copy()
        r[h] = 1.0
        cum = np.concatenate([[1.0], np.cumprod(r)])
        with np.errstate(divide='ignore', invalid='ignore'):
            return np.where(lo == hi, 0.0, cum[hi] / np.where(cum[lo] == 0, 1e-300, cum[lo]))

    def _spatial(self, d, rho):
        t = self.sptype
        if t == 'pow':
            return _powcorr(rho, d)
        if t == 'exp':
            F = np.exp(-d / rho)
            return F, F * d / rho ** 2
        if t == 'gau':
            F = np.exp(-(d / rho) ** 2)
            return F, F * 2 * d ** 2 / rho ** 3
        u = d / rho
        inside = u < 1
        F = np.where(inside, 1 - 1.5 * u + 0.5 * u ** 3, 0.0)
        dF = np.where(inside, 1.5 * d / rho ** 2 - 1.5 * d ** 3 / rho ** 4, 0.0)
        return F, dF


# ---- the engine -----------------------------------------------------------------------------------------------

class _Uf:
    """Union-find over the rows."""

    def __init__(self, n):
        self.p = np.arange(n)

    def find(self, i):
        p = self.p
        r = i
        while p[r] != r:
            r = p[r]
        while p[i] != r:
            p[i], i = r, p[i]
        return r

    def union_groups(self, keys):
        """Join rows with the same key (-1: none)."""
        first = {}
        for i, k in enumerate(keys.tolist()):
            if k < 0:
                continue
            j = first.setdefault(k, i)
            if j != i:
                a, b = self.find(i), self.find(j)
                if a != b:
                    self.p[a] = b

    def labels(self):
        return np.array([self.find(i) for i in range(len(self.p))])


def _block_sizes(n, keysets):
    uf = _Uf(n)
    for k in keysets:
        uf.union_groups(k)
    lab = uf.labels()
    return lab, np.bincount(np.unique(lab, return_inverse=True)[1])


class _Engine:
    """The REML fit of y = X b + Z u + e for the components comps (G side) and
    the structure rs (R side), parameters pars (natural values theta)."""

    def __init__(self, y, X, comps, rs, pars):
        self.y = np.asarray(y, dtype=float)
        self.X = np.asarray(X, dtype=float)
        self.n, self.p = self.X.shape
        self.comps, self.rs, self.pars = comps, rs, pars
        self.r = len(pars)
        self._partition()
        self._prepare()

    # ---- the blocks ------------------------------------------------------------------------------------------
    def _partition(self):
        n = self.n
        keys = [self.rs.sub.copy()]
        absorbed, low = [], []
        comps = sorted(range(len(self.comps)), key=lambda i: -self.comps[i].nl)
        for i in comps:
            c = self.comps[i]
            trial = keys + [c.codes]
            _lab, sizes = _block_sizes(n, trial)
            if sizes.max() <= _BLOCK_MAX or n <= _DENSE_ALL:
                keys = trial
                absorbed.append(i)
            else:
                low.append(i)
        lab, _ = _block_sizes(n, keys)
        self.absorbed = sorted(absorbed)
        self.low = sorted(low)
        # groups of blocks of one size, rows sorted within each block
        order = np.argsort(lab, kind='stable')
        ul, start, counts = np.unique(lab[order], return_index=True, return_counts=True)
        groups = {}
        for s, m in zip(start, counts):
            groups.setdefault(int(m), []).append(order[s:s + m])
        self.grows = [np.array(v, dtype=np.int64) for _m, v in sorted(groups.items())]
        self.maxblock = max((g.shape[1] for g in self.grows), default=0)
        if self.low:
            ql = sum(self.comps[i].q for i in self.low)
            if n * ql > _LOW_MAX:
                raise ValueError(f'the model is too large for REML here: {n} rows and {ql} levels of crossed random effects')

    def _prepare(self):
        """The constant parts of each group: the absorbed random effects'
        derivative matrices (their contribution is linear in the parameters)
        and the repeated structure's arrays."""
        self.gd = []        # per group: [(k, D)] of absorbed parameters
        self.gr = []        # per group: the structure's arrays
        for rows in self.grows:
            lst = []
            for i in self.absorbed:
                c = self.comps[i]
                cd = c.codes[rows]
                same = (cd[:, :, None] == cd[:, None, :]) & (cd[:, :, None] >= 0)
                v = c.vals[rows]                    # nb x m x c
                for k, (a, b) in zip(c.pidx, _vech(c.c)):
                    if a == b:
                        D = same * (v[:, :, a][:, :, None] * v[:, :, a][:, None, :])
                    else:
                        D = same * (v[:, :, a][:, :, None] * v[:, :, b][:, None, :] + v[:, :, b][:, :, None] * v[:, :, a][:, None, :])
                    lst.append((k, D))
            self.gd.append(lst)
            self.gr.append(self.rs.prepare(rows))
        # the low-rank part
        if self.low:
            from scipy import sparse
            self.Zl = sparse.hstack([self.comps[i].sparse() for i in self.low], format='csr')
            self.ql = self.Zl.shape[1]
            self.low_off = np.cumsum([0] + [self.comps[i].q for i in self.low])
            self.dGl = {}
            for j, i in enumerate(self.low):
                c = self.comps[i]
                o = self.low_off[j]
                for k, (a, b) in zip(c.pidx, _vech(c.c)):
                    E = np.zeros((c.c, c.c))
                    E[a, b] = E[b, a] = 1.0
                    blk = sparse.kron(sparse.identity(c.nl, format='csr'), sparse.csr_matrix(E), format='coo')
                    self.dGl[k] = sparse.csr_matrix((blk.data, (blk.row + o, blk.col + o)), shape=(self.ql, self.ql))
        else:
            self.Zl, self.ql = None, 0

    def Gl(self, theta):
        from scipy import linalg as sla
        return sla.block_diag(*[np.kron(np.eye(self.comps[i].nl), self.comps[i].sigma(theta)) for i in self.low]) if self.low else np.zeros((0, 0))

    # ---- blockwise products ---------------------------------------------------------------------------------
    def _bmm(self, Ag, B):
        """A B for the block-diagonal A (per group) and an n (x k) B."""
        one = B.ndim == 1
        B2 = B[:, None] if one else B
        out = np.empty((self.n, B2.shape[1]))
        for A, rows in zip(Ag, self.grows):
            out[rows] = np.einsum('bij,bjk->bik', A, B2[rows])
        return out[:, 0] if one else out

    # ---- one evaluation ------------------------------------------------------------------------------------
    def evaluate(self, theta, level=0):
        """The REML log-likelihood at theta and what goes with it; level 1 adds
        the score, 2 the expected information, 3 the observed information
        (analytic, without the second-derivative terms of non-linear
        structures). None when V is not positive definite."""
        theta = np.asarray(theta, dtype=float)
        n, p = self.n, self.p
        Vg, Dg = [], []
        for g, rows in enumerate(self.grows):
            R, dR = self.rs.block(theta, self.gr[g])
            V = R.copy()
            for k, D in self.gd[g]:
                V += theta[k] * D
            Vg.append(V)
            Dg.append(list(self.gd[g]) + dR)
        logdet = 0.0
        Ag = []
        try:
            for V in Vg:
                ld, A = _chol_inv(V)
                logdet += ld
                Ag.append(A)
        except np.linalg.LinAlgError:
            return None
        X, y = self.X, self.y
        AX, Ay = self._bmm(Ag, X), self._bmm(Ag, y)
        if self.ql:
            Zl = self.Zl
            U = self._bmm(Ag, Zl.toarray()) if self.ql * n <= 4_000_000 else np.column_stack([self._bmm(Ag, Zl[:, j].toarray()[:, 0]) for j in range(self.ql)])
            M = np.asarray(Zl.T @ U)
            M = 0.5 * (M + M.T)
            G = self.Gl(theta)
            IGM = np.eye(self.ql) + G @ M
            sign, ld = np.linalg.slogdet(IGM)
            if sign <= 0 or not np.isfinite(ld):
                return None
            if any(theta[k] < 0 for i in self.low for k in self.comps[i].pidx):
                w, Q = np.linalg.eigh(M)
                Mh = (Q * np.sqrt(np.maximum(w, 0))) @ Q.T
                if np.linalg.eigvalsh(np.eye(self.ql) + Mh @ G @ Mh).min() <= 1e-12:
                    return None
            logdet += ld
            K = np.linalg.solve(IGM, G)
            K = 0.5 * (K + K.T)
            UX, Uy = U.T @ X, U.T @ y
            W = AX - U @ (K @ UX)
            Viy = Ay - U @ (K @ Uy)
        else:
            U = M = G = K = None
            W, Viy = AX, Ay
        XtViX = X.T @ W
        XtViX = 0.5 * (XtViX + XtViX.T)
        try:
            Lx = np.linalg.cholesky(XtViX)
        except np.linalg.LinAlgError:
            return None
        ldx = 2.0 * float(np.sum(np.log(np.diag(Lx))))
        Phi = np.linalg.inv(XtViX)
        Phi = 0.5 * (Phi + Phi.T)
        beta = Phi @ (W.T @ y)
        e = Viy - W @ beta                 # V^-1 r = P y
        r = y - X @ beta
        rVr = float(r @ e)
        ll = -0.5 * ((n - p) * _LOG2PI + logdet + ldx + rVr)
        out = {'ll': ll, 'logdet': logdet, 'ldx': ldx, 'rVr': rVr, 'beta': beta, 'Phi': Phi, 'e': e, 'r': r, 'W': W,
               'Ag': Ag, 'Dg': Dg, 'U': U, 'M': M, 'G': G, 'K': K, 'theta': theta}
        return self.derive(out, level)

    def derive(self, E, level):
        """Add the score (level 1), the information (2) and the observed
        information (3) to an evaluation."""
        if level >= 1 and 'score' not in E:
            self._score(E)
        if level >= 2 and 'info' not in E:
            self._info(E, observed=level >= 3)
        elif level >= 3 and 'obs' not in E:
            self._info(E, observed=True)
        return E

    # ---- derivatives -------------------------------------------------------------------------------------------
    def _lowparts(self, E):
        """Z'L, T = Z'PZ, Z'e and PZ for the low-rank part."""
        if 'T' in E:
            return
        U, M, K, W, Phi = E['U'], E['M'], E['K'], E['W'], E['Phi']
        Zl = self.Zl
        ZW = np.asarray(Zl.T @ W)
        # Z'P Z = M - [M, ZW] Q [M, ZW]'
        T = M - M @ K @ M - ZW @ Phi @ ZW.T
        E['T'] = 0.5 * (T + T.T)
        E['ZW'] = ZW
        E['Ze'] = np.asarray(Zl.T @ E['e']).reshape(-1)
        # P Z = U - U K M - W Phi ZW'
        E['PZ'] = U - U @ (K @ M) - W @ (Phi @ ZW.T)

    def _L(self, E):
        if 'L' not in E:
            if self.ql:
                E['L'] = np.hstack([E['U'], E['W']])
                s = self.ql + self.p
                Q = np.zeros((s, s))
                Q[:self.ql, :self.ql] = E['K']
                Q[self.ql:, self.ql:] = E['Phi']
                E['Q'] = Q
            else:
                E['L'], E['Q'] = E['W'], E['Phi']
        return E['L'], E['Q']

    def _blocklist(self, E):
        """For each block parameter: [(group, D)]."""
        if 'bl' in E:
            return E['bl']
        bl = {}
        for g, lst in enumerate(E['Dg']):
            for k, D in lst:
                bl.setdefault(k, []).append((g, D))
        E['bl'] = bl
        return bl

    def _score(self, E):
        r = self.r
        L, Q = self._L(E)
        e = E['e']
        tr = np.zeros(r)
        eve = np.zeros(r)
        bl = self._blocklist(E)
        LtDL = {}
        for k, lst in bl.items():
            t, v = 0.0, 0.0
            S = np.zeros((L.shape[1], L.shape[1]))
            for g, D in lst:
                rows = self.grows[g]
                A = E['Ag'][g]
                t += float(np.einsum('bij,bji->', A, D))
                eg = e[rows]
                v += float(np.einsum('bi,bij,bj->', eg, D, eg))
                Lg = L[rows]
                S += np.einsum('bik,bij,bjl->kl', Lg, D, Lg)
            LtDL[k] = S
            tr[k] += t - float(np.sum(Q * S))
            eve[k] += v
        if self.ql:
            self._lowparts(E)
            T, Ze = E['T'], E['Ze']
            for k, dG in self.dGl.items():
                tr[k] += float(dG.multiply(T).sum())
                eve[k] += float(Ze @ (dG @ Ze))
        E['trPV'], E['eVe'], E['LtDL'] = tr, eve, LtDL
        E['score'] = -0.5 * tr + 0.5 * eve

    def _average_info(self, E):
        """The average information 1/2 e'V_k P V_l e (Gilmour, Thompson and
        Cullis 1995): matrix-vector products only, for large blocks, where
        the expected information's tr(P V_k P V_l) costs n^3 per parameter.
        It stands in for the information in the steps; near the maximum it is
        close to the observed information."""
        r = self.r
        L, Q = self._L(E)
        bl = self._blocklist(E)
        e = E['e']
        Amat = np.zeros((self.n, r))
        for k, lst in bl.items():
            for g, D in lst:
                rows = self.grows[g]
                Amat[rows, k] += np.einsum('bij,bj->bi', D, e[rows])
        if self.ql:
            self._lowparts(E)
            Ze = E['Ze']
            for k, dG in self.dGl.items():
                Amat[:, k] += np.asarray(self.Zl @ (dG @ Ze)).reshape(-1)
        PA = self._bmm(E['Ag'], Amat) - L @ (Q @ (L.T @ Amat))
        aPa = Amat.T @ PA
        AI = 0.25 * (aPa + aPa.T)
        E['info'] = AI
        E['obs'] = AI
        E['ai'] = True

    def _info(self, E, observed=False):
        """The expected information 1/2 tr(P V_k P V_l) and, when asked, the
        analytic part of the observed information: -1/2 tr(P V_k P V_l) +
        e'V_k P V_l e."""
        if self.maxblock > _AI_BLOCK and not E.get('exact'):
            self._average_info(E)
            return
        r = self.r
        L, Q = self._L(E)
        bl = self._blocklist(E)
        LtDL = E['LtDL']
        I = np.zeros((r, r))
        keys = sorted(bl)
        # A D per block parameter, per group
        AD = {k: {g: np.einsum('bij,bjk->bik', E['Ag'][g], D) for g, D in lst} for k, lst in bl.items()}
        DL = {k: {g: np.einsum('bij,bjk->bik', D, L[self.grows[g]]) for g, D in lst} for k, lst in bl.items()}
        for ai, k in enumerate(keys):
            for l in keys[ai:]:
                t1 = 0.0
                cross = np.zeros((L.shape[1], L.shape[1]))
                for g in AD[k]:
                    if g not in AD[l]:
                        continue
                    t1 += float(np.einsum('bij,bji->', AD[k][g], AD[l][g]))
                    # L' D_k A D_l L
                    cross += np.einsum('bik,bij,bjl->kl', DL[k][g], E['Ag'][g], DL[l][g])
                val = t1 - 2.0 * float(np.sum(Q * cross)) + float(np.sum((Q @ LtDL[k]) * (Q @ LtDL[l]).T))
                I[k, l] = I[l, k] = 0.5 * val
        if self.ql:
            self._lowparts(E)
            T, PZ = E['T'], E['PZ']
            lk = sorted(self.dGl)
            TdG = {k: np.asarray(self.dGl[k].T @ T.T).T for k in lk}      # T dG_k
            for ai, k in enumerate(lk):
                for l in lk[ai:]:
                    I[k, l] = I[l, k] = 0.5 * float(np.sum(TdG[k] * TdG[l].T))
            # low x block: tr(dG_k (PZ)' D_l (PZ))
            for l in keys:
                S = np.zeros((self.ql, self.ql))
                for g, D in bl[l]:
                    Pg = PZ[self.grows[g]]
                    S += np.einsum('bik,bij,bjl->kl', Pg, D, Pg)
                for k in lk:
                    I[k, l] = I[l, k] = 0.5 * float(self.dGl[k].multiply(S).sum())
        E['info'] = I
        if observed:
            # a_k = V_k e; a_k' P a_l
            e = E['e']
            Amat = np.zeros((self.n, r))
            for k, lst in bl.items():
                for g, D in lst:
                    rows = self.grows[g]
                    Amat[rows, k] += np.einsum('bij,bj->bi', D, e[rows])
            if self.ql:
                Ze = E['Ze']
                for k, dG in self.dGl.items():
                    Amat[:, k] += np.asarray(self.Zl @ (dG @ Ze)).reshape(-1)
            PA = self._bmm(E['Ag'], Amat) - L @ (Q @ (L.T @ Amat))
            aPa = Amat.T @ PA
            E['obs'] = -I + 0.5 * (aPa + aPa.T)

    def apply_vinv(self, E, B):
        """V^-1 B."""
        AB = self._bmm(E['Ag'], B)
        if self.ql:
            ZAB = np.asarray(self.Zl.T @ AB)
            return AB - E['U'] @ (E['K'] @ ZAB)
        return AB

    def vk_times(self, E, k, B):
        """V_k B for the derivative of V with respect to parameter k."""
        one = B.ndim == 1
        B2 = B[:, None] if one else B
        out = np.zeros((self.n, B2.shape[1]))
        for g, D in self._blocklist(E).get(k, []):
            rows = self.grows[g]
            out[rows] += np.einsum('bij,bjk->bik', D, B2[rows])
        if self.ql and k in self.dGl:
            out += np.asarray(self.Zl @ (self.dGl[k] @ np.asarray(self.Zl.T @ B2)))
        return out[:, 0] if one else out


# ---- transforms of the parameters for the optimizer ------------------------------------------------------------

class _Trans:
    """eta <-> theta: a variance component unbounded (free) or bounded at zero
    (nonneg) as it is, a variance on the log scale, a correlation through
    tanh, the power spatial correlation through the logistic function, an
    unstructured matrix by its log-Cholesky factor."""

    def __init__(self, pars, chol_groups):
        self.pars = pars
        self.r = len(pars)
        self.groups = chol_groups        # [(c, [param indices in vech order])]
        self.in_group = {k for _c, ks in chol_groups for k in ks}

    def eta(self, theta):
        eta = np.array(theta, dtype=float)
        for k, p in enumerate(self.pars):
            if k in self.in_group:
                continue
            if p.tr == 'log':
                eta[k] = math.log(max(theta[k], 1e-300))
            elif p.tr == 'tanh':
                eta[k] = math.atanh(min(max(theta[k], -0.999999), 0.999999))
            elif p.tr == 'logit':
                t = min(max(theta[k], 1e-9), 1 - 1e-9)
                eta[k] = math.log(t / (1 - t))
        for c, ks in self.groups:
            S = np.zeros((c, c))
            for k, (i, j) in zip(ks, _vech(c)):
                S[i, j] = S[j, i] = theta[k]
            w, Q = np.linalg.eigh(S)
            S = (Q * np.maximum(w, 1e-8 * max(1.0, float(np.max(np.abs(w)))))) @ Q.T
            Lc = np.linalg.cholesky(S)
            for k, (i, j) in zip(ks, _vech(c)):
                eta[k] = math.log(Lc[i, i]) if i == j else Lc[i, j]
        return eta

    def theta(self, eta):
        th = np.array(eta, dtype=float)
        for k, p in enumerate(self.pars):
            if k in self.in_group:
                continue
            if p.tr == 'log':
                th[k] = math.exp(min(eta[k], 700.0))
            elif p.tr == 'tanh':
                th[k] = math.tanh(eta[k])
            elif p.tr == 'logit':
                th[k] = 1.0 / (1.0 + math.exp(-min(max(eta[k], -700.0), 700.0)))
        for c, ks in self.groups:
            Lc = np.zeros((c, c))
            for k, (i, j) in zip(ks, _vech(c)):
                Lc[i, j] = math.exp(min(eta[k], 350.0)) if i == j else eta[k]
            S = Lc @ Lc.T
            for k, (i, j) in zip(ks, _vech(c)):
                th[k] = S[i, j]
        return th

    def jac(self, eta):
        """d theta / d eta (r x r)."""
        J = np.eye(self.r)
        for k, p in enumerate(self.pars):
            if k in self.in_group:
                continue
            if p.tr == 'log':
                J[k, k] = math.exp(min(eta[k], 700.0))
            elif p.tr == 'tanh':
                J[k, k] = 1.0 - math.tanh(eta[k]) ** 2
            elif p.tr == 'logit':
                s = 1.0 / (1.0 + math.exp(-min(max(eta[k], -700.0), 700.0)))
                J[k, k] = s * (1 - s)
        for c, ks in self.groups:
            Lc = np.zeros((c, c))
            vh = _vech(c)
            for k, (i, j) in zip(ks, vh):
                Lc[i, j] = math.exp(min(eta[k], 350.0)) if i == j else eta[k]
            for col, (k2, (a, b)) in enumerate(zip(ks, vh)):
                dL = np.zeros((c, c))
                dL[a, b] = Lc[a, b] if a == b else 1.0
                dS = dL @ Lc.T + Lc @ dL.T
                for k, (i, j) in zip(ks, vh):
                    J[k, k2] = dS[i, j]
        return J


# ---- the fit -----------------------------------------------------------------------------------------------------

_LAPACK_MIN = 96   # blocks this large or larger: scipy's LAPACK (numpy's own, in Pyodide, is several times slower)


def _chol_inv(Vs):
    """A stack of symmetric positive definite blocks (b, m, m): the log
    determinant of them all and their inverses (symmetric). Small blocks by
    numpy's batched routines; large ones by LAPACK's Cholesky (potrf) and
    the inverse from it (potri), a third of the work of an LU inverse.
    Raises LinAlgError when a block is not positive definite."""
    b, m = Vs.shape[0], Vs.shape[1]
    if m < _LAPACK_MIN:
        Lc = np.linalg.cholesky(Vs)
        A = np.linalg.inv(Vs)
        return 2.0 * float(np.sum(np.log(np.diagonal(Lc, axis1=1, axis2=2)))), 0.5 * (A + np.swapaxes(A, 1, 2))
    from scipy.linalg import lapack
    out = np.empty_like(Vs)
    logdet = 0.0
    for i in range(b):
        c, info = lapack.dpotrf(Vs[i], lower=1, clean=1)
        if info != 0:
            raise np.linalg.LinAlgError('not positive definite')
        d = np.diag(c)
        if not np.all(d > 0):
            raise np.linalg.LinAlgError('not positive definite')
        logdet += 2.0 * float(np.sum(np.log(d)))
        inv, info = lapack.dpotri(c, lower=1)
        if info != 0:
            raise np.linalg.LinAlgError('singular')
        lo = np.tril(inv)
        out[i] = lo + np.tril(inv, -1).T
    return logdet, out


def _relgrad(g, H):
    try:
        return float(g @ np.linalg.solve(H, g))
    except np.linalg.LinAlgError:
        return float(g @ np.linalg.pinv(H) @ g)


def _optimize(eng, theta0, tr, fixed=(), maxit=250, tol=1e-10, log=None):
    """Maximize the REML log-likelihood from theta0: Fisher scoring, then
    Newton steps with the observed information (for structures linear in
    their parameters), each step halved until the likelihood rises and V
    stays positive definite. Bounded (nonneg) parameters stay at or above
    zero; one at zero whose score points below zero is held there.
    Returns (theta, E, converged, iterations, history)."""
    pars = eng.pars
    r = len(pars)
    nonneg = np.array([p.tr == 'nonneg' for p in pars])
    fixed = set(fixed)
    linear = all(p.linear for p in pars)
    eta = tr.eta(theta0)
    theta = tr.theta(eta)
    for k in fixed:
        theta[k] = theta0[k]
    E = eng.evaluate(theta, 3 if linear else 2)
    if E is None:
        return theta, None, False, 0, []
    hist = [(0, -2 * E['ll'], theta.copy())]
    converged = False
    newton = False
    polish = 0
    it = 0
    rg = float('inf')
    rgs = []
    for it in range(1, maxit + 1):
        J = tr.jac(eta)
        g = J.T @ E['score']
        Hf = J.T @ E['info'] @ J
        Hn = J.T @ E['obs'] @ J if 'obs' in E else None
        active = [k for k in range(r) if k not in fixed and not (nonneg[k] and theta[k] <= 0 and g[k] <= 0)]
        if not active:
            converged = True
            break
        ai = np.array(active)
        gA = g[ai]
        H = Hf[np.ix_(ai, ai)]
        if newton and Hn is not None:
            HnA = Hn[np.ix_(ai, ai)]
            try:
                np.linalg.cholesky(HnA)
                H = HnA
            except np.linalg.LinAlgError:
                pass
        rg = _relgrad(gA, Hf[np.ix_(ai, ai)])
        rgs.append(rg)
        if log is not None:
            log.append((it, -2 * E['ll'], rg))
        if rg < tol:
            # converged; a few more steps polish the estimates to the precision of the arithmetic
            converged = True
            polish += 1
            if rg < 1e-22 or polish > 4:
                break
        elif len(hist) > 6 and len(rgs) > 7 and rg < 1e-6 * (1 + abs(hist[-1][1])):
            # a likelihood flat to the rounding of its score (a spatial range, a large block's average
            # information): -2 log likelihood still over the last six steps, the relative gradient no
            # longer falling (it bounces at the score's rounding) and the relative Hessian criterion
            # (g'H^-1 g / |-2LL|, SAS's) far below 1e-8: converged, where rg cannot go lower
            last = [h[1] for h in hist[-6:]]
            if max(last) - min(last) < 1e-10 * (1 + abs(last[-1])) and min(rgs[-3:]) > 0.25 * min(rgs[-7:-3]):
                converged = True
                break
        if rg < 1e-3:
            newton = True
        try:
            step = np.linalg.solve(H + 1e-12 * np.eye(len(ai)) * max(1.0, float(np.trace(H)) / len(ai)), gA)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(H, gA, rcond=None)[0]
        full = np.zeros(r)
        full[ai] = step
        # keep the steps of log/tanh parameters moderate
        big = np.max(np.abs(full)) if len(full) else 0.0
        t = 1.0 if big <= 5 else 5.0 / big
        accepted = False
        while t > 1e-10:
            eta2 = eta + t * full
            th2 = tr.theta(eta2)
            for k in fixed:
                th2[k] = theta0[k]
            th2 = np.where(nonneg & (th2 < 0), 0.0, th2)
            eta2 = np.where(nonneg, th2, eta2)
            E2 = eng.evaluate(th2, 0)
            if E2 is not None and E2['ll'] >= E['ll'] - 1e-11 * (1 + abs(E['ll'])):
                accepted = True
                eng.derive(E2, 3 if linear else 2)
                break
            t *= 0.5
        if not accepted:
            converged = converged or rg < 1e-6
            break
        dll = E2['ll'] - E['ll']
        eta, theta, E = eta2, th2, E2
        hist.append((it, -2 * E['ll'], theta.copy()))
        if abs(dll) < 1e-15 * (1 + abs(E['ll'])) and rg < 1e-12:
            converged = True
            break
    E = eng.evaluate(theta, 3 if linear else 2)
    return theta, E, converged, it, hist


def _numeric_obs(eng, theta, fixed_idx):
    """The observed information by central differences of the analytic
    score (for structures with second derivatives)."""
    r = len(theta)
    H = np.zeros((r, r))
    for k in range(r):
        if k in fixed_idx:
            continue
        h = 1e-5 * max(abs(theta[k]), 1e-2)
        tp, tm = theta.copy(), theta.copy()
        tp[k] += h
        tm[k] -= h
        Ep, Em = eng.evaluate(tp, 1), eng.evaluate(tm, 1)
        if Ep is None or Em is None:
            # a one-sided difference at the edge of the positive definite region
            E0 = eng.evaluate(theta, 1)
            Ep = Ep or E0
            Em = Em or E0
            H[:, k] = -(Ep['score'] - Em['score']) / (h if (Ep is E0 or Em is E0) else 2 * h)
        else:
            H[:, k] = -(Ep['score'] - Em['score']) / (2 * h)
    return 0.5 * (H + H.T)


class _Result:
    """A fitted mixed model: estimates, covariances and the pieces of the
    Kenward-Roger and Satterthwaite approximations."""

    def __init__(self, eng, theta, E, converged, iters, hist, boundary):
        self.eng, self.theta, self.E = eng, theta, E
        self.converged, self.iters, self.hist = converged, iters, hist
        self.boundary = sorted(boundary)          # parameters on the zero boundary (or fixed)
        pars = eng.pars
        r = len(pars)
        self.free = [k for k in range(r) if k not in self.boundary]
        if all(p.linear for p in pars) and 'obs' in E and not E.get('ai'):
            H = E['obs']
        else:
            H = _numeric_obs(eng, theta, set(self.boundary))
        self.H = H
        f = np.array(self.free, dtype=int)
        Wc = np.zeros((r, r))
        if len(f):
            Hf = H[np.ix_(f, f)]
            try:
                Wf = np.linalg.inv(Hf)
                if not np.all(np.isfinite(Wf)) or np.any(np.diag(Wf) < 0):
                    raise np.linalg.LinAlgError
            except np.linalg.LinAlgError:
                Wf = np.linalg.pinv(Hf)
            Wc[np.ix_(f, f)] = 0.5 * (Wf + Wf.T)
        self.Wcov = Wc                            # covariance of the covariance parameters
        self.beta, self.Phi = E['beta'], E['Phi']
        self.ll = E['ll']
        self._kr = None

    # -- Kenward-Roger (first order) and Satterthwaite -------------------------------------------------------------
    def kr_parts(self):
        """P_k = X' dV^-1/dtheta_k X = -X'V^-1 V_k V^-1 X and
        Q_kl = X'V^-1 V_k V^-1 V_l V^-1 X for the free parameters, and the
        adjusted covariance Phi_A = Phi + 2 Phi (sum W_kl (Q_kl - P_k Phi P_l)) Phi
        (Kenward and Roger 1997, without the second-derivative term: JMP's
        and PROC MIXED's KENWARDROGER(FIRSTORDER))."""
        if self._kr is not None:
            return self._kr
        eng, E = self.eng, self.E
        W = E['W']
        Phi = self.Phi
        f = self.free
        VW = {k: eng.vk_times(E, k, W) for k in f}
        P = {k: -(W.T @ VW[k]) for k in f}
        P = {k: 0.5 * (v + v.T) for k, v in P.items()}
        ViVW = {k: eng.apply_vinv(E, VW[k]) for k in f}
        Lam = np.zeros_like(Phi)
        for a in f:
            for b in f:
                w = self.Wcov[a, b]
                if w == 0:
                    continue
                Qab = VW[a].T @ ViVW[b]
                Lam += w * (Qab - P[a] @ Phi @ P[b])
        PhiA = Phi + 2 * Phi @ Lam @ Phi
        PhiA = 0.5 * (PhiA + PhiA.T)
        dPhi = {k: -(Phi @ P[k] @ Phi) for k in f}      # d Phi / d theta_k
        self._kr = {'P': P, 'PhiA': PhiA, 'dPhi': dPhi, 'VW': VW}
        return self._kr

    def cov(self, method='kr'):
        return self.kr_parts()['PhiA'] if method == 'kr' else self.Phi

    def ddf(self, L, method='kr'):
        """(F scale lambda, denominator df) for the test of L b = 0 (L: l x p),
        Kenward-Roger or Satterthwaite (Fai and Cornelius for l > 1)."""
        L = np.atleast_2d(np.asarray(L, dtype=float))
        Phi = self.Phi
        f = self.free
        K = self.kr_parts()
        W = self.Wcov
        if not f:
            return 1.0, float('inf')
        if method == 'kr':
            LPL = L @ Phi @ L.T
            l = int(np.linalg.matrix_rank(LPL, tol=1e-10 * max(1.0, float(np.max(np.abs(LPL))))))
            if l == 0:
                return 1.0, float('nan')
            if l < L.shape[0]:
                # a full-rank basis of the rows
                u, s, vt = np.linalg.svd(L, full_matrices=False)
                L = (vt[:l].T * s[:l]).T if False else vt[:l]
                LPL = L @ Phi @ L.T
            Theta = L.T @ np.linalg.inv(LPL) @ L
            M = {k: Theta @ Phi @ K['P'][k] @ Phi for k in f}
            tr1 = {k: float(np.trace(M[k])) for k in f}
            A1 = sum(W[a, b] * tr1[a] * tr1[b] for a in f for b in f)
            A2 = sum(W[a, b] * float(np.sum(M[a] * M[b].T)) for a in f for b in f)
            if A2 <= 1e-300:
                return 1.0, float('inf')
            B = (A1 + 6 * A2) / (2 * l)
            g = ((l + 1) * A1 - (l + 4) * A2) / ((l + 2) * A2)
            den = 3 * l + 2 * (1 - g)
            c1, c2, c3 = g / den, (l - g) / den, (l + 2 - g) / den
            Es = 1.0 / (1 - A2 / l)
            Vs = (2.0 / l) * (1 + c1 * B) / ((1 - c2 * B) ** 2 * (1 - c3 * B))
            rho = Vs / (2 * Es * Es)
            m = 4 + (l + 2) / (l * rho - 1) if l * rho - 1 != 0 else float('inf')
            lam = m / (Es * (m - 2)) if m > 2 else 1.0
            if l == 1:
                lam, m = 1.0, 2.0 / A1 if A1 > 0 else float('inf')
            return float(lam), float(m)
        # Satterthwaite
        C = L @ Phi @ L.T
        vals, vecs = np.linalg.eigh(C)
        keep = vals > 1e-10 * max(float(vals.max()), 1e-300)
        nus = []
        for d, v in zip(vals[keep], vecs[:, keep].T):
            lm = v @ L
            gk = np.array([lm @ K['dPhi'][k] @ lm for k in f])
            den = float(gk @ W[np.ix_(f, f)] @ gk)
            nus.append(2 * d * d / den if den > 0 else float('inf'))
        q = len(nus)
        if q == 0:
            return 1.0, float('nan')
        if q == 1:
            return 1.0, float(nus[0])
        nus = np.asarray(nus)
        if np.all(np.abs(np.diff(nus)) < 1e-8 * max(1.0, float(np.max(np.abs(nus))))):
            return 1.0, float(nus.mean())
        if np.any(nus <= 2):
            return 1.0, 2.0
        Ev = float(np.sum(nus / (nus - 2)))
        return 1.0, (2 * Ev / (Ev - q) if Ev > q else float('nan'))

    def test(self, L, method='kr'):
        """F test of L b = 0: (F, numerator df, denominator df, p)."""
        L = np.atleast_2d(np.asarray(L, dtype=float))
        C = L @ self.cov(method) @ L.T
        Lb = L @ self.beta
        q = int(np.linalg.matrix_rank(L @ self.Phi @ L.T, tol=1e-10 * max(1.0, float(np.max(np.abs(L @ self.Phi @ L.T))))))
        if q == 0:
            return float('nan'), 0, float('nan'), float('nan')
        F = float(Lb @ np.linalg.pinv(C) @ Lb) / q
        lam, m = self.ddf(L, method)
        Fs = lam * F
        p = float(stats.f.sf(Fs, q, m)) if np.isfinite(m) else float(stats.chi2.sf(Fs * q, q))
        return Fs, q, m, p

    # -- BLUPs --------------------------------------------------------------------------------------------------------
    def blups(self):
        """The random effects' predictions u = G Z'V^-1 r for each component,
        their prediction error variances (G - G Z'P Z G) and Satterthwaite
        degrees of freedom (JMP: no Kackar-Harville correction for BLUPs)."""
        if hasattr(self, '_blups'):
            return self._blups
        eng, E, theta = self.eng, self.E, self.theta
        e = E['e']
        out = []
        comps = eng.comps
        if not comps:
            self._blups = out
            return out
        # Z of every component (dense, for the prediction errors)
        Zs = [c.dense() for c in comps]
        Z = np.hstack(Zs)
        G = np.zeros((Z.shape[1], Z.shape[1]))
        off = np.cumsum([0] + [c.q for c in comps])
        dG = {}
        for j, c in enumerate(comps):
            o = off[j]
            G[o:o + c.q, o:o + c.q] = np.kron(np.eye(c.nl), c.sigma(theta))
            for k, (a, b) in zip(c.pidx, _vech(c.c)):
                Ek = np.zeros((c.c, c.c))
                Ek[a, b] = Ek[b, a] = 1.0
                M = np.zeros_like(G)
                M[o:o + c.q, o:o + c.q] = np.kron(np.eye(c.nl), Ek)
                dG[k] = M
        PZ = eng.apply_vinv(E, Z) - E['W'] @ (self.Phi @ (E['W'].T @ Z))
        T = Z.T @ PZ
        T = 0.5 * (T + T.T)
        u = G @ (Z.T @ e)
        C = G - G @ T @ G
        pev = np.maximum(np.diag(C), 0.0)
        # d diag(C) / d theta_k = diag(dG_k - dG_k T G - G T dG_k + G Z'P V_k P Z G)
        f = self.free
        B = PZ @ G                               # P Z G
        dd = {}
        for k in f:
            VB = eng.vk_times(E, k, B)
            term = np.einsum('ij,ij->j', B, VB)
            if k in dG:
                D = dG[k]
                term = term + np.diag(D) - 2 * np.einsum('ij,ji->i', D, T @ G)
            dd[k] = term
        W = self.Wcov
        df = np.full(len(u), np.inf)
        if f:
            Dm = np.array([dd[k] for k in f])            # |f| x q
            var = np.einsum('ki,kl,li->i', Dm, W[np.ix_(f, f)], Dm)
            with np.errstate(divide='ignore', invalid='ignore'):
                df = np.where(var > 0, 2 * pev ** 2 / var, np.inf)
        for j, c in enumerate(comps):
            o = off[j]
            out.append({'comp': c, 'u': u[o:o + c.q].reshape(c.nl, c.c), 'pev': pev[o:o + c.q].reshape(c.nl, c.c),
                        'df': df[o:o + c.q].reshape(c.nl, c.c)})
        self._blups = out
        self._Zu = Z @ u
        return out

    def zu(self):
        if not hasattr(self, '_Zu'):
            if self.eng.comps:
                self.blups()
            else:
                self._Zu = np.zeros(self.eng.n)
        return self._Zu


# ---------------------------------------------------------------------------
# the options of a mixed model, the design, the covariance structure
# ---------------------------------------------------------------------------

_STRUCTS = tuple(_R_LABEL)
_GLMM_DISTS = {'binomial': 'logit', 'poisson': 'log'}
_GLMM_LINKS = {'binomial': ('logit', 'probit', 'cloglog'), 'poisson': ('log',)}


def _opts(spec):
    """The mixed options of a spec (spec['mixed'], as the page sends them),
    with their defaults: JMP's Unbounded Variance Components, Kenward-Roger,
    the Residual structure."""
    o = dict(spec.get('mixed') or {})
    st = o.get('structure') if o.get('structure') in _STRUCTS else 'residual'
    g = o.get('glmm') or None
    if g:
        dist = g.get('dist') if g.get('dist') in _GLMM_DISTS else 'binomial'
        link = g.get('link') if g.get('link') in _GLMM_LINKS[dist] else _GLMM_DISTS[dist]
        g = {'dist': dist, 'link': link, 'scale': 'estimated' if g.get('scale') == 'estimated' else 'fixed', 'target': g.get('target')}
    return {'unbounded': o.get('unbounded', True) is not False, 'ddfm': 'sat' if o.get('ddfm') == 'sat' else 'kr', 'structure': st,
            'sptype': o.get('sptype') if o.get('sptype') in _SP_LABEL else 'exp',
            'repeated': [str(c) for c in (o.get('repeated') or []) if c], 'subject': [str(c) for c in (o.get('subject') or []) if c],
            'rc': sorted([str(l), int(k)] for l, k in (o.get('rc') or [])), 'glmm': g}


def _mx_spec(y=None, effects=(), weight=None, freq=None, no_intercept=False, center=True, mixed=None, **_kw):
    """The spec of a mixed model: fit_model's, with the mixed options; the
    random-coefficient groups of the effects ({names, nest, random, rc}) go
    into mixed['rc'] (fit_model's spec keeps names, nest and random only)."""
    mx = dict(mixed or {})
    rc = [list(p) for p in (mx.get('rc') or [])]
    for e in effects or ():
        if isinstance(e, dict) and e.get('random') and e.get('rc'):
            lab = '*'.join(str(n) for n in e.get('names') or []) + ('[' + ','.join(str(n) for n in e.get('nest') or []) + ']' if e.get('nest') else '')
            if not any(p[0] == lab for p in rc):
                rc.append([lab, int(e['rc'])])
    if rc:
        mx['rc'] = sorted(rc)
    return _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, center=center, mixed=mx or None)


class _Mixed:
    """A fitted mixed model and everything the reports need of it."""


def _cat_codes(d, tid, cols):
    """The combinations of the categorical columns among cols, as row codes
    (0..k-1, in the columns' level order), labels (value labels shown) and
    the raw level values of each combination."""
    cats = [c for c in dict.fromkeys(cols) if d.alias[c] in d.categorical]
    if not cats:
        return None, [], [], []
    M = np.column_stack([d.df[d.alias[c]].cat.codes.to_numpy() for c in cats])
    uniq, inv = np.unique(M, axis=0, return_inverse=True)
    raw = [[d.levels[d.alias[c]][k] for c, k in zip(cats, u)] for u in uniq]
    labels = [','.join(data.level_label(tid, c, v, _lvl(v)) for c, v in zip(cats, r)) for r in raw]
    return inv.reshape(-1).astype(np.int64), labels, cats, raw


def _nocenter(d, cols):
    """JMP leaves a continuous column that is in a random effect uncentred,
    Center Polynomials or not: its centred forms in the fixed effects' terms
    become the column itself."""
    alias = {d.alias[c] for c in cols if c in d.alias and d.alias[c] not in d.categorical}
    alias = {a for a in alias if a in d.means}
    if not alias:
        return set()
    changed = set()

    def fix(term):
        out = term
        for a in alias:
            m = d.means[a]
            for pat, rep in ((f'I(({a} - {m!r}) ** ', f'I({a} ** '), (f'I({a} - {m!r})', a)):
                if pat in out:
                    out = out.replace(pat, rep)
                    changed.add(a)
        return out
    for e in d.effects:
        e['term'] = fix(e['term'])
    cm = getattr(d, 'centered_main', {})
    for t in list(cm):
        if any(t == f'I({a} - {d.means[a]!r})' for a in alias):
            cm.pop(t)
    rhs = ' + '.join(e['term'] for e in d.effects) or '1'
    if d.rhs.endswith(' - 1'):
        rhs += ' - 1'
    d.rhs = rhs
    d.formula = f'{d.y_alias} ~ {rhs}' if d.y_alias else rhs
    return changed


def _mx_formula(d, lhs=True, indicator=False):
    """fit_model._code_formula, with the columns JMP leaves uncentred (in a
    random effect) uncentred. indicator: every categorical factor coded 0/1,
    its last level the reference (the Indicator Parameterization), written
    here from the levels themselves (never parsed back out of the text: a
    level from the table may hold brackets and quotes)."""
    nc = getattr(d, 'nocenter', set())
    parts = []
    for e in d.effects:
        counts = {}
        for nm in e['names']:
            counts[nm] = counts.get(nm, 0) + 1
        crossed = len(e['names']) > 1
        ps = []
        for nm, k in counts.items():
            a = d.alias[nm]
            if a in d.categorical:
                lv = [x.item() if hasattr(x, 'item') else x for x in d.levels[a]]
                coding = f'Treatment(reference={lv[-1]!r})' if indicator else ('Sum' if d.coding == 'effect' else 'Treatment')
                ps.append(f'C({_q(nm)}, {coding}, levels={lv!r})')
            elif a not in nc and ((crossed and d.center) or (k == 1 and f'I({a} - {d.means.get(a)!r})' in getattr(d, 'centered_main', {}))):
                m = d.means[a]
                ps.append(f'I(({_q(nm)} - {m!r}) ** {k})' if k > 1 else f'I({_q(nm)} - {m!r})')
            elif k > 1:
                ps.append(f'I({_q(nm)} ** {k})')
            else:
                ps.append(_q(nm))
        parts.append(':'.join(ps))
    rhs = ' + '.join(parts) if parts else '1'
    if d.rhs.endswith(' - 1'):
        rhs += ' - 1'
    y = d.y if isinstance(d.y, str) else (d.y[0] if d.y else '')
    return f'{_q(y)} ~ {rhs}' if (y and lhs) else rhs


def _col_num(tid, name, index):
    return data.series(tid, name, index, as_category=False).to_numpy(float)


def _random_parts(d, tid, effs, opts):
    """The G side: a _GComp and its parameters for each random effect (a
    variance component), and one for each group of correlated random
    coefficients (an unstructured matrix per subject)."""
    rand = [e for e in effs if e['random']]
    rcmap = {lab: k for lab, k in opts['rc']}
    pars, comps, info = [], [], []
    seen = set()
    for e in rand:
        k = rcmap.get(e['label'])
        if k is not None:
            if k in seen:
                continue
            seen.add(k)
            group = [x for x in rand if rcmap.get(x['label']) == k]
            subj = None
            coefs, vals = [], []
            for x in group:
                cats = [c for c in dict.fromkeys(x['cols']) if d.alias[c] in d.categorical]
                nums = [c for c in x['cols'] if d.alias[c] not in d.categorical]
                if not cats:
                    raise ValueError(f'the random coefficient {x["label"]} has no subject: nest it in a categorical column')
                if subj is None:
                    subj = cats
                elif sorted(cats) != sorted(subj):
                    raise ValueError(f'the random coefficients ({k}) are nested in different columns: {", ".join(subj)} and {", ".join(cats)}')
                v = np.ones(len(d.df))
                for c in nums:
                    v = v * d.df[d.alias[c]].to_numpy(float)
                coefs.append('*'.join(nums) if nums else 'Intercept')
                vals.append(v)
            order = sorted(range(len(coefs)), key=lambda i: (coefs[i] != 'Intercept', i))
            coefs = [coefs[i] for i in order]
            vals = [vals[i] for i in order]
            if len(set(coefs)) < len(coefs):
                raise ValueError(f'the random coefficients ({k}) repeat a coefficient')
            codes, labels, cats, raw = _cat_codes(d, tid, subj)
            subject = ','.join(subj)
            k0 = len(pars)
            for i, j in _vech(len(coefs)):
                lab = f'Var({coefs[i]})' if i == j else f'Cov({coefs[i]},{coefs[j]})'
                pars.append(_Par(lab, 'G', 'var' if i == j else 'cov', 'chol', subject, group=k))
            comps.append(_GComp(f'Random Coefficients({k})', codes, np.column_stack(vals), labels, coefs, range(k0, len(pars)), subject))
            info.append({'label': f'Random Coefficients({k})', 'rc': k, 'effects': [x['label'] for x in group], 'cats': cats, 'raw': raw,
                         'coefs': coefs, 'subject': subject, 'slope': False})
            continue
        codes, labels, cats, raw = _cat_codes(d, tid, e['cols'])
        if codes is None:
            raise ValueError(f'the random effect {e["label"]} has no categorical column (a random effect is a factor, or a slope within one)')
        nums = [c for c in e['cols'] if d.alias[c] not in d.categorical]
        v = np.ones(len(d.df))
        for c in nums:
            v = v * d.df[d.alias[c]].to_numpy(float)
        pars.append(_Par(e['label'], 'G', 'var', 'free' if opts['unbounded'] else 'nonneg'))
        comps.append(_GComp(e['label'], codes, v, labels, ['*'.join(nums) if nums else 'Intercept'], [len(pars) - 1]))
        info.append({'label': e['label'], 'rc': None, 'effects': [e['label']], 'cats': cats, 'raw': raw, 'coefs': comps[-1].coefs,
                     'subject': '', 'slope': bool(nums), 'nums': nums})
    return comps, pars, info


def _levels_of_column(d, tid, name):
    """A Repeated column's levels (value order) and each row's index; a
    continuous one's distinct values in increasing order."""
    a = d.alias[name]
    if a in d.categorical:
        return d.df[a].cat.codes.to_numpy().astype(np.int64), [data.level_label(tid, name, v, _lvl(v)) for v in d.levels[a]], list(d.levels[a])
    x = d.df[a].to_numpy(float)
    u, inv = np.unique(x, return_inverse=True)
    return inv.astype(np.int64), [_lvl(v) for v in u], list(u)


_NEEDS_SUBJECT = {'un', 'cs', 'antevar', 'toep', 'csh', 'ante', 'toeph'}
_ONE_PER = {'un', 'antevar', 'toep', 'ante', 'toeph', 'ar1', 'arh', 'sp'}   # a repeated value at most once per subject


def _repeated_part(d, tid, opts, n, winv, k0, glmm=None):
    """The R side: the structure (_RStruct), its parameters and a
    description for the report."""
    kind = opts['structure']
    rep, subj = opts['repeated'], opts['subject']
    notes = []
    fixed_scale = 1.0 if glmm and glmm['scale'] == 'fixed' else None
    if kind == 'residual':
        if rep or subj:
            notes.append('Repeated columns and subject columns are ignored when the Residual covariance structure is selected.')
        pars = _RStruct.params('residual', fixed_scale=fixed_scale)
        return _RStruct('residual', n, range(k0, k0 + len(pars)), winv=winv, fixed_scale=fixed_scale), pars, {'kind': kind}, notes
    label = _R_LABEL[kind] + (f' {_SP_LABEL[opts["sptype"]]}' if kind in ('sp', 'spn') else '')
    for c in subj:
        if d.alias[c] not in d.categorical:
            raise ValueError(f'{c} is continuous: Subject columns must be categorical (nominal or ordinal)')
    if kind in _NEEDS_SUBJECT and not subj:
        raise ValueError(f'the {label} structure needs a Subject column: the rows that belong together')
    if not rep:
        raise ValueError(f'the {label} structure needs a Repeated column' + (' (the coordinates)' if kind in ('sp', 'spn') else ''))
    sub = _cat_codes(d, tid, subj)[0] if subj else np.zeros(n, dtype=np.int64)
    sub_labels = _cat_codes(d, tid, subj)[1] if subj else ['']
    desc = {'kind': kind, 'label': label, 'repeated': rep, 'subject': subj, 'sptype': opts['sptype']}
    if kind in ('sp', 'spn'):
        for c in rep:
            if d.alias[c] in d.categorical:
                raise ValueError(f'{c} is categorical: the spatial structures take continuous Repeated columns (the coordinates)')
        coords = np.column_stack([d.df[d.alias[c]].to_numpy(float) for c in rep])
        _check_once(sub, [tuple(r) for r in coords.tolist()], label, kind == 'sp')
        pars = _RStruct.params(kind, sptype=opts['sptype'])
        rs = _RStruct(kind, n, range(k0, k0 + len(pars)), sub=sub, coords=coords, sptype=opts['sptype'], winv=winv, rep_name=','.join(rep))
        desc.update(coords=coords, sub=sub, sub_labels=sub_labels)
        return rs, pars, desc, notes
    if len(rep) != 1:
        raise ValueError(f'the {label} structure takes one Repeated column')
    rname = rep[0]
    lev, names, raw = _levels_of_column(d, tid, rname)
    t = None
    if kind in ('ar1', 'arh'):
        a = d.alias[rname]
        t = d.df[a].to_numpy(float) if a not in d.categorical else lev.astype(float)
        if a in d.categorical:
            notes.append(f'{rname} is categorical: AR(1) takes its levels as equally spaced times (1, 2, 3, ...).')
    if kind in _ONE_PER or kind in _R_UNEQ:
        if kind in _ONE_PER:
            _check_once(sub, lev.tolist(), label, True)
    J = len(names)
    if J < 2 and kind not in ('uneqvar', 'ar1'):
        raise ValueError(f'{rname} has one value: the {label} structure needs two or more')
    pars = _RStruct.params(kind, J=J, lev_names=names, rep_name=rname)
    whole = kind in ('ar1', 'arh') and t is not None and np.allclose(t, np.round(t))
    for p in pars:
        if kind in ('ar1', 'arh') and p.kind == 'corr' and not whole:
            p.tr = 'logit'      # rho ** d for a fractional d: rho between 0 and 1
    rs = _RStruct(kind, n, range(k0, k0 + len(pars)), sub=sub, lev=lev, lev_names=names, t=t, winv=winv, rep_name=rname)
    desc.update(levels=names, raw=raw, lev=lev, sub=sub, sub_labels=sub_labels, t=t)
    return rs, pars, desc, notes


def _check_once(sub, keys, label, strict):
    if not strict:
        return
    seen = set()
    for s, k in zip(sub.tolist(), keys):
        if (s, k) in seen:
            raise ValueError(f'a subject has two rows with the same repeated value: the {label} structure takes each value at most once per subject')
        seen.add((s, k))


def _start(eng, pars, y, X, winv):
    """Starting values: the residual variance of least squares for the
    variances, a quarter of it for each variance component (scaled by its
    column for a slope), small correlations, a spatial range of a third of
    the median distance."""
    n, p = X.shape
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    r = y - X @ b
    s2 = float(np.sum(r * r / winv) / max(n - np.linalg.matrix_rank(X), 1))
    s2 = s2 if s2 > 0 else 1.0
    th = np.zeros(len(pars))
    for c in eng.comps:
        for k, (i, j) in zip(c.pidx, _vech(c.c)):
            if i == j:
                v = c.vals[:, i]
                ms = float(np.mean(v * v)) or 1.0
                th[k] = 0.25 * s2 / ms
    rs = eng.rs
    kind = rs.kind
    for k in rs.pidx:
        pk = pars[k]
        if pk.kind == 'var':
            th[k] = s2 * (0.75 if eng.comps else 1.0)
        elif pk.kind == 'corr':
            th[k] = 0.3 if kind in ('ar1', 'arh', 'ante', 'antevar') else 0.1
        elif pk.kind == 'cov':
            th[k] = 0.0 if kind == 'un' else 0.1 * s2
        elif pk.kind == 'range':
            if rs.sptype == 'pow':
                th[k] = 0.5
            else:
                cs = rs.coords
                m = min(len(cs), 300)
                dd = np.sqrt(((cs[:m, None, :] - cs[None, :m, :]) ** 2).sum(-1))
                pos = dd[dd > 0]
                med = float(np.median(pos)) if len(pos) else 1.0
                th[k] = med if rs.sptype == 'sph' else med / 3
        elif pk.kind == 'nugget':
            th[k] = 0.1
    if kind == 'un':
        for kk, (i, j) in zip(rs.pidx, _vech(rs.J)):
            th[kk] = s2 if i == j else 0.0
    return th


def _fit(eng, pars, theta0, fixed=()):
    """REML from theta0 (and from a second start when the first stalls)."""
    groups = [(c.c, c.pidx) for c in eng.comps if c.c > 1]
    if eng.rs.kind == 'un':
        groups.append((eng.rs.J, eng.rs.pidx))
    tr = _Trans(pars, groups)
    best = None
    starts = []
    for scale in (1.0, 0.1, 3.0):
        t0 = np.array(theta0, dtype=float)
        if scale != 1.0:
            for c in eng.comps:
                for k in c.pidx:
                    t0[k] *= scale
        starts.append((t0, True))
    rs = eng.rs
    if rs.kind in ('sp', 'spn'):
        # the spatial likelihood can have several maxima: more starts, the best kept
        base = np.array(theta0, dtype=float)
        kr_ = rs.pidx[0]
        alts = [(0.5, 0.01), (2.0, 0.1), (1.0, 0.01), (0.25, 0.1)] if eng.n <= 400 else [(0.5, 0.01)] if eng.n <= 1000 else []
        for fr, nug in alts:
            t0 = base.copy()
            t0[kr_] = min(t0[kr_] * fr, 0.95) if rs.sptype == 'pow' else t0[kr_] * fr
            if rs.kind == 'spn':
                t0[rs.pidx[1]] = nug
            starts.insert(1, (t0, False))
    # the same start twice (no G-side component for the scales to change) is fitted once
    uniq = []
    for t0, stop in starts:
        if not any(np.array_equal(t0, u) for u, _s in uniq):
            uniq.append((t0, stop))
    starts = uniq
    for t0, stop in starts:
        th, E, conv, it, hist = _optimize(eng, t0, tr, fixed=fixed)
        if E is None:
            continue
        if best is None or E['ll'] > best[1]['ll'] + 1e-9:
            best = (th, E, conv, it, hist, t0)
        if conv and stop and rs.kind not in ('sp', 'spn'):
            break
    if best is None:
        raise ValueError('the REML fit found no covariance parameters that give a positive definite V: try another structure, '
                         'or bounded variance components')
    th, E, conv, it, hist, t0 = best
    bnd = [k for k, p in enumerate(pars) if (p.tr == 'nonneg' and th[k] <= 0) or k in set(fixed)]
    res = _Result(eng, th, E, conv, it, hist, bnd)
    res.start = np.asarray(t0, dtype=float)
    res.starts = len(starts)
    return res


def _glmm_response(tid, ys, d, g, idx):
    """A GLMM's response: events and trials (binomial), counts (Poisson)."""
    if g['dist'] == 'binomial':
        if len(ys) >= 2:
            ev = _col_num(tid, ys[0], idx)
            nt = _col_num(tid, ys[1], idx)
            if np.any(nt <= 0) or np.any(ev < 0) or np.any(ev > nt):
                raise ValueError(f'events must lie between 0 and the trials ({ys[1]}), and the trials above 0')
            return ev, nt, None
        a = d.y_alias
        s = d.df[a]
        if isinstance(s.dtype, pd.CategoricalDtype):
            lv = list(s.cat.categories)
            if len(lv) != 2:
                raise ValueError(f'{ys[0]} has {len(lv)} levels: a binomial response has two (or give events and trials as two Y columns)')
            tgt = g.get('target')
            ti = next((i for i, v in enumerate(lv) if tgt is not None and (str(v) == str(tgt) or _lvl(v) == str(tgt))), 0)
            ev = (s.cat.codes.to_numpy() == ti).astype(float)
            return ev, np.ones(len(ev)), lv[ti]
        v = s.to_numpy(float)
        if not np.all(np.isin(v, (0.0, 1.0))):
            raise ValueError(f'{ys[0]} is continuous: a binomial response is 0 or 1, a two-level column, or events and trials')
        return v, np.ones(len(v)), None
    v = d.df[d.y_alias].to_numpy(float)
    if np.any(v < 0):
        raise ValueError(f'{ys[0]} has negative values: a Poisson response is a count')
    return v, np.ones(len(v)), None


_LINKS = {
    'logit': (lambda m: np.log(m / (1 - m)), lambda e: 1 / (1 + np.exp(-e)), lambda m: 1 / (m * (1 - m))),
    'probit': (lambda m: stats.norm.ppf(m), lambda e: stats.norm.cdf(e), lambda m: 1 / stats.norm.pdf(stats.norm.ppf(m))),
    'cloglog': (lambda m: np.log(-np.log(1 - m)), lambda e: 1 - np.exp(-np.exp(e)), lambda m: -1 / ((1 - m) * np.log(1 - m))),
    'log': (np.log, np.exp, lambda m: 1 / m),
}


def _mixed_model(tid, rows, spec):
    key = _key('mixed', tid, rows, spec)
    m = models.recall(key)
    if m is not None:
        return m
    opts = _opts(spec)
    g = opts['glmm']
    ys = spec['y']
    if not ys:
        raise ValueError('choose a Y')
    effs = _eff_of(spec)
    rand = [e for e in effs if e['random']]
    if not rand and opts['structure'] == 'residual' and not g:
        raise ValueError('no random effects and no repeated structure: mark effects with Attributes > Random Effect, or choose a Repeated Structure')
    extra = list(dict.fromkeys(opts['repeated'] + opts['subject'] + (ys[1:2] if g and g['dist'] == 'binomial' and len(ys) > 1 else [])))
    d = _design(tid, ys[0], effs, rows, spec['weight'], spec['freq'], not spec['no_intercept'], extra=extra,
                y_as_category=bool(g), center=spec.get('center', True))
    if not g and isinstance(d.df[d.y_alias].dtype, pd.CategoricalDtype):
        raise ValueError(f'{ys[0]} is categorical: the mixed model needs a continuous Y (a Generalized Linear Model with a random effect takes a binomial one)')
    d.nocenter = _nocenter(d, [c for e in rand for c in e['cols']])
    import patsy
    Xf = patsy.dmatrix(d.rhs, d.df, return_type='dataframe')
    di = Xf.design_info
    _attach(d, di)
    X0 = np.asarray(Xf, dtype=float)
    fe_names = list(di.column_names)
    idx = d.df.index
    n0 = len(idx)
    w0 = _col_num(tid, spec['weight'], idx) if spec['weight'] else np.ones(n0)
    f0 = _col_num(tid, spec['freq'], idx) if spec['freq'] else np.ones(n0)
    fi = np.floor(f0 + 1e-9).astype(int)
    notes = []
    if spec['freq'] and np.any(np.abs(f0 - np.round(f0)) > 1e-9):
        notes.append(f'{spec["freq"]} has values that are not whole numbers: each row counts as many times as its whole part.')
    keep = fi > 0
    rep = np.repeat(np.arange(n0), fi)          # the rows of the fit: each row as many times as its Freq
    comps, gpars, ginfo = _random_parts(d, tid, effs, opts)
    if g:
        ev, nt, target = _glmm_response(tid, ys, d, g, idx)
        y0 = ev / nt
    else:
        y0 = d.df[d.y_alias].to_numpy(float)
        target = None
    winv0 = 1.0 / w0
    rs, rpars, rdesc, rnotes = _repeated_part(d, tid, opts, n0, winv0, len(gpars), g)
    notes += rnotes
    pars = gpars + rpars
    # the expanded rows (Freq)
    X = X0[rep]
    for c in comps:
        c.codes0, c.vals0 = c.codes, c.vals
        c.codes = c.codes[rep]
        c.vals = c.vals[rep]
    rs.n = len(rep)
    rs.sub = rs.sub[rep]
    rs.winv = rs.winv[rep]
    for att in ('lev', 't', 'coords'):
        if getattr(rs, att) is not None:
            setattr(rs, att, getattr(rs, att)[rep])
    if spec['freq'] and rs.kind in _ONE_PER and np.any(fi > 1):
        raise ValueError(f'a Freq above 1 repeats a row within its subject, which the {rdesc.get("label", "")} structure does not allow')
    rank = int(np.linalg.matrix_rank(X))
    if rank < X.shape[1]:
        raise ValueError('the fixed effects are linearly dependent (some are aliased in these rows): take one of them out')
    m = _Mixed()
    m.__dict__.update({'kind': 'mixed', 'd': d, 'di': di, 'X0': X0, 'X': X, 'fe_names': fe_names, 'coder': Coder(d, di), 'rep': rep,
                       'keep': keep, 'w0': w0, 'f0': f0, 'comps': comps, 'ginfo': ginfo, 'pars': pars, 'rs': rs, 'rdesc': rdesc,
                       'opts': opts, 'spec': spec, 'tid': tid, 'key': key, 'notes': notes, 'glmm': g, 'target': target})
    if g:
        _fit_glmm(m, ev[rep], nt[rep])
    else:
        yv = y0[rep]
        eng = _Engine(yv, X, comps, rs, pars)
        res = _fit(eng, pars, _start(eng, pars, yv, X, rs.winv))
        m.__dict__.update({'eng': eng, 'res': res, 'y': yv})
    _finish(m)
    models.remember(key, m)
    return m


def _fit_glmm(m, ev, nt):
    """Residual pseudo-likelihood (RSPL; Wolfinger and O'Connell 1993): the
    linearized pseudo-response y* = eta + (y - mu) deta/dmu with weights
    1/(v(mu) (deta/dmu)^2) is fitted by REML as a linear mixed model, the
    linear predictor (fixed and random effects) updated, until the fixed
    effects and the covariance parameters stop changing."""
    g = m.glmm
    link, inv, deriv = _LINKS[g['link']]
    X, comps, rs, pars = m.X, m.comps, m.rs, m.pars
    ybar = ev / nt
    if g['dist'] == 'binomial':
        mu = (ev + 0.5) / (nt + 1.0)
        var = lambda mm: mm * (1 - mm) / nt          # noqa: E731
    else:
        mu = ev + 0.5
        var = lambda mm: mm                          # noqa: E731
    base_winv = rs.winv.copy()
    theta = None
    prev = None
    res = None
    for it in range(1, 101):
        eta = link(mu)
        dd = deriv(mu)
        ystar = eta + (ybar - mu) * dd
        w = 1.0 / (var(mu) * dd * dd)
        rs.winv = base_winv / w
        eng = _Engine(ystar, X, comps, rs, pars)
        if theta is None:
            theta = _start(eng, pars, ystar, X, rs.winv)
        res = _fit(eng, pars, theta)
        theta = res.theta
        eta_new = X @ res.beta + res.zu()
        lo, hi = (1e-10, 1 - 1e-10) if g['dist'] == 'binomial' else (1e-10, np.inf)
        mu = np.clip(inv(eta_new), lo, hi)
        cur = np.r_[res.beta, res.theta]
        if prev is not None and np.max(np.abs(cur - prev) / np.maximum(np.abs(prev), 1e-8)) < 1e-8:
            break
        prev = cur
    m.__dict__.update({'eng': eng, 'res': res, 'y': ystar, 'glmm_iter': it, 'glmm_conv': it < 100, 'mu': mu, 'ev': ev, 'nt': nt,
                       'pseudo_w': w})


def _finish(m):
    """Names and orders the reports use."""
    res = m.res
    m.scale = float(res.theta[m.rs.pidx[-1]]) if m.rs.kind == 'residual' and m.rs.fixed_scale is None else (m.rs.fixed_scale or 1.0)
    m.T = _uncenter(m.d, m.fe_names)
    rank = {'Intercept': -1}
    for i, e in enumerate(m.d.effects):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    m.order = sorted(range(len(m.fe_names)), key=lambda j: rank.get(m.fe_names[j], len(m.d.effects)))


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------

def _satt_ci(v, se, alpha):
    """The Satterthwaite interval of a variance: df = 2 (v / se)^2, bounded
    at zero (JMP's, for a variance bounded at zero and for the residual)."""
    if v is None or not np.isfinite(v) or v <= 0 or se is None or not np.isfinite(se) or se <= 0:
        return (0.0, 0.0) if v is not None and v == 0 else (None, None)
    df = 2 * (v / se) ** 2
    return float(df * v / stats.chi2.ppf(1 - alpha / 2, df)), float(df * v / stats.chi2.ppf(alpha / 2, df))


def _wald_ci(v, se, z):
    if se is None or not np.isfinite(se):
        return None, None
    return float(v - z * se), float(v + z * se)


def _se_of(res, k):
    if k in res.boundary:
        return None
    s = res.Wcov[k, k]
    return float(math.sqrt(s)) if s > 0 else None


def _vc_only(m):
    """A variance-components model (JMP's REML model): the Total row and Pct of Total."""
    return all(c.c == 1 for c in m.comps) and m.rs.kind == 'residual' and m.rs.fixed_scale is None


def _fit_stats(m):
    res, n = m.res, len(m.rep)
    p = m.X.shape[1]
    E = res.E
    q = len([p_ for p_ in m.pars])
    m2rll = -2 * res.ll
    m2ll = n * _LOG2PI + E['logdet'] + E['rVr']
    k = p + q
    aicc = m2ll + 2 * k + 2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else float('nan')
    bic = m2ll + k * math.log(n) if n > 0 else float('nan')
    return {'rows': int(np.sum(m.keep)), 'sumfreq': n, 'm2rll': m2rll, 'm2ll': m2ll, 'aicc': aicc, 'bic': bic, 'k': k, 'p': p, 'q': q}


def _summary_of_fit(m):
    """Standard Least Squares' Summary of Fit for a REML fit, as JMP gives it:
    RSquare from the conditional residuals (fixed effects and BLUPs), RSquare
    Adj with n - rank(X) error degrees of freedom, the root of the residual
    variance, the mean, the observations (the sum of the weights)."""
    yv = m.y
    w = 1.0 / m.rs.winv
    cond = m.X @ m.res.beta + m.res.zu()
    sw = float(np.sum(w))
    mean = float(np.sum(w * yv) / sw)
    sst = float(np.sum(w * (yv - mean) ** 2))
    sse = float(np.sum(w * (yv - cond) ** 2))
    n = len(yv)
    p = m.X.shape[1]
    rsq = 1 - sse / sst if sst > 0 else float('nan')
    adj = 1 - (sse / (n - p)) / (sst / (n - 1)) if sst > 0 and n > p and n > 1 else float('nan')
    return [{'stat': 'RSquare', 'value': rsq}, {'stat': 'RSquare Adj', 'value': adj},
            {'stat': 'Root Mean Square Error', 'value': math.sqrt(m.scale) if m.scale > 0 else None},
            {'stat': 'Mean of Response', 'value': mean}, {'stat': 'Observations (or Sum Wgts)', 'value': sw}]


def _covparm_rows(m, alpha):
    """The random effects' covariance parameters (and the residual, with the
    Residual structure): JMP's Wald intervals and Wald p-values for the G
    side when the variance components are unbounded, Satterthwaite
    intervals for variances bounded at zero and for the residual."""
    res, opts = m.res, m.opts
    z = float(stats.norm.ppf(1 - alpha / 2))
    rows = []
    vc = _vc_only(m)
    slope = {c.pidx[0]: inf['slope'] for c, inf in zip(m.comps, m.ginfo) if c.c == 1}
    tot = m.scale + sum(res.theta[k] for k, sl in slope.items() if not sl and res.theta[k] > 0) if vc else None
    allsum = m.scale + sum(res.theta[k] for k, sl in slope.items() if not sl) if vc else None
    for c, inf in zip(m.comps, m.ginfo):
        for k in c.pidx:
            p = m.pars[k]
            v = float(res.theta[k])
            se = _se_of(res, k)
            if p.tr == 'nonneg' and p.kind == 'var':
                lo, hi = _satt_ci(v, se, alpha)
            else:
                lo, hi = _wald_ci(v, se, z)
            wald = float(2 * stats.norm.sf(abs(v) / se)) if opts['unbounded'] and se else None
            rows.append({'effect': p.label, 'subject': p.subject or None, 'ratio': v / m.scale if p.kind == 'var' and m.scale > 0 else None,
                         'var': v, 'se': se, 'lower': lo, 'upper': hi, 'p': wald,
                         'pct': 100 * v / tot if vc and tot and not slope.get(k) else None,
                         'sqrt': math.sqrt(v) if p.kind == 'var' and v >= 0 else None, 'boundary': k in res.boundary, 'side': 'G'})
    if m.rs.kind == 'residual' and m.rs.fixed_scale is None:
        k = m.rs.pidx[0]
        se = _se_of(res, k)
        lo, hi = _satt_ci(m.scale, se, alpha)
        rows.append({'effect': 'Residual', 'subject': None, 'ratio': None, 'var': m.scale, 'se': se, 'lower': lo, 'upper': hi, 'p': None,
                     'pct': 100 * m.scale / tot if vc and tot else None, 'sqrt': math.sqrt(m.scale), 'side': 'R'})
    if vc:
        rows.append({'effect': 'Total', 'subject': None, 'ratio': None, 'var': tot, 'se': None, 'lower': None, 'upper': None, 'p': None,
                     'pct': 100.0, 'sqrt': math.sqrt(tot) if tot and tot > 0 else None, 'total': True})
    return rows, allsum


def _repeated_rows(m, alpha):
    res = m.res
    z = float(stats.norm.ppf(1 - alpha / 2))
    rows = []
    if m.rs.kind == 'residual':
        return rows
    for k in m.rs.pidx:
        p = m.pars[k]
        v = float(res.theta[k])
        se = _se_of(res, k)
        if p.kind == 'var':
            lo, hi = _satt_ci(v, se, alpha)
        else:
            lo, hi = _wald_ci(v, se, z)
            if p.kind == 'corr' and lo is not None:
                lo, hi = max(lo, -1.0), min(hi, 1.0)
            if p.kind in ('range', 'nugget') and lo is not None:
                lo = max(lo, 0.0)
        rows.append({'param': p.label, 'subject': ','.join(m.rdesc.get('subject') or []) or None, 'estimate': v, 'se': se, 'lower': lo, 'upper': hi})
    return rows


def _rmatrix(m):
    """The repeated structure's covariance and correlation matrices over the
    levels of the Repeated column (the categorical structures), a subject
    with every level."""
    rs = m.rs
    if rs.kind in ('residual', 'sp', 'spn') or rs.lev is None:
        return None
    J = rs.J
    lev = np.arange(J)
    fake = _RStruct(rs.kind, J, rs.pidx, sub=np.zeros(J, dtype=np.int64), lev=lev, lev_names=rs.lev_names,
                    t=np.array(sorted(set(rs.t.tolist())))[:J] if rs.t is not None and len(set(rs.t.tolist())) == J else lev.astype(float),
                    winv=np.ones(J))
    R, _ = fake.block(m.res.theta, fake.prepare(np.arange(J)[None, :]))
    R = R[0]
    sd = np.sqrt(np.maximum(np.diag(R), 1e-300))
    return {'levels': rs.lev_names, 'cov': R, 'corr': R / np.outer(sd, sd)}


def _fixed_rows(m, alpha, method):
    res = m.res
    b = res.beta
    C = res.cov(method)
    p = len(b)
    rows = []
    for j in m.order:
        L = m.T[j].copy() if m.T is not None else np.eye(p)[j]
        est = float(L @ b)
        se = float(math.sqrt(max(L @ C @ L, 0.0)))
        _lam, df = res.ddf(L[None, :], method)
        t = est / se if se > 0 else float('nan')
        tc = float(stats.t.ppf(1 - alpha / 2, df)) if np.isfinite(df) and df > 0 else float(stats.norm.ppf(1 - alpha / 2))
        pv = float(2 * stats.t.sf(abs(t), df)) if np.isfinite(df) and df > 0 else float(2 * stats.norm.sf(abs(t)))
        rows.append({'term': _tlabel(m.d, m.fe_names[j]), 'estimate': est, 'se': se, 'dfden': df, 't': t, 'p': pv,
                     'lower': est - tc * se, 'upper': est + tc * se, 'name': m.fe_names[j]})
    return rows


def _effect_L(m, e):
    cols = [m.fe_names.index(t) for t in e.get('terms', []) if t in m.fe_names]
    L = np.zeros((len(cols), len(m.fe_names)))
    for i, c in enumerate(cols):
        L[i, c] = 1.0
    return L


def _cov_fixed(m, method):
    """The covariance of the report's fixed-effect parameters (the
    intercept at 0 where a main effect was centred), in the report's order."""
    C = m.res.cov(method)
    T = m.T if m.T is not None else np.eye(len(m.fe_names))
    CJ = T @ C @ T.T
    return CJ[np.ix_(m.order, m.order)]


def _test_rows(m, method):
    rows = []
    for e in m.d.effects:
        L = _effect_L(m, e)
        if not len(L):
            continue
        F, q, dfd, p = m.res.test(L, method)
        rows.append({'source': e['label'], 'nparm': len(L), 'dfnum': q, 'dfden': dfd, 'f': F, 'p': p})
    return rows


def _blup_rows(m, alpha):
    """Random Effects Predictions: each level's BLUP with its prediction
    error (JMP: not Kackar-Harville corrected) and Satterthwaite's df; the
    Random Coefficients table (a row per level, a column per coefficient)."""
    res = m.res
    preds, coefs = [], []
    for b, inf in zip(res.blups(), m.ginfo):
        c = b['comp']
        rows = []
        for li, lv in enumerate(c.levels):
            for a, cname in enumerate(c.coefs):
                u = float(b['u'][li, a])
                pev = float(b['pev'][li, a])
                se = math.sqrt(pev) if pev > 0 else None
                df = float(b['df'][li, a])
                t = u / se if se else None
                ok = t is not None and np.isfinite(df) and df > 0
                tc = float(stats.t.ppf(1 - alpha / 2, df)) if ok else None
                rows.append({'term': f'{cname}[{lv}]' if c.c > 1 or inf['slope'] else lv, 'level': lv, 'coef': cname, 'blup': u, 'se': se,
                             'dfden': df if np.isfinite(df) else None, 't': t,
                             'p': float(2 * stats.t.sf(abs(t), df)) if ok else None,
                             'lower': u - tc * se if ok else None, 'upper': u + tc * se if ok else None})
        preds.append({'effect': inf['label'], 'rows': rows, 'subject': inf['subject'] or None})
        coefs.append({'effect': inf['label'], 'coefs': list(c.coefs), 'levels': list(c.levels), 'u': b['u'],
                      'sigma': c.sigma(res.theta) if c.c > 1 else None, 'subject': inf['subject'] or None})
    return preds, coefs


def _zu_rows(m, idx=None):
    """Z u for the design's own rows (every row of the frame, Freq 0 too)."""
    out = np.zeros(len(m.d.df))
    for b in m.res.blups():
        c = b['comp']
        codes, vals = c.codes0, c.vals0
        ok = codes >= 0
        out[ok] += np.einsum('ij,ij->i', b['u'][codes[ok]], vals[ok])
    return out


def _notes(m, method):
    res = m.res
    out = list(m.notes)
    if method == 'kr':
        out.append('The fixed effects\' standard errors and tests use the Kenward-Roger adjusted covariance, and their denominator degrees of '
                   'freedom Kenward and Roger\'s (the first-order approximation, as JMP and SAS\'s DDFM=KENWARDROGER(FIRSTORDER)).')
    else:
        out.append('The fixed effects\' standard errors are the model-based ones, (X\'V⁻¹X)⁻¹; their denominator degrees of freedom are '
                   'Satterthwaite\'s (Fai and Cornelius\'s for several), as SAS\'s DDFM=SATTERTHWAITE.')
    bnd = [m.pars[k].label for k in res.boundary if m.pars[k].tr == 'nonneg']
    if bnd:
        out.append(f'{", ".join(bnd)}: the estimate is on the boundary, 0 (Unbounded Variance Components is off). The standard errors, '
                   'intervals and degrees of freedom treat it as a known zero; with the option on, its REML estimate may be below zero.')
    neg = [m.pars[k].label for k in range(len(m.pars)) if m.pars[k].tr == 'free' and m.res.theta[k] < 0]
    if neg:
        out.append(f'{", ".join(neg)}: the estimate is negative. With Unbounded Variance Components (JMP\'s default) a variance component may '
                   'be below zero as long as the covariance of the rows stays positive definite: a negative covariance within its levels.')
    if not res.converged:
        sc = _score_test(m)
        out.append(f'The REML fit did not converge (the relative gradient did not reach 1e-10). Convergence score test: '
                   f'ChiSquare {sc["stat"]:.4g} on {sc["df"]} DF, p = {sc["p"]:.4g}' + ('; not significant, so the final estimates may be '
                   'used with caution.' if sc['p'] > 0.05 else '; significant: the estimates are not at the maximum.'))
    if m.glmm and not m.glmm_conv:
        out.append('The pseudo-likelihood iterations did not settle within 100 steps: the estimates are the last ones.')
    return out


def _score_test(m):
    """JMP's convergence score test: g' I^-1 g at the final iterate, the
    observed information, chi-square with as many DF as unbounded
    parameters."""
    res = m.res
    f = res.free
    if not f:
        return {'stat': 0.0, 'df': 0, 'p': 1.0}
    E = m.eng.evaluate(res.theta, 1)
    g = E['score'][f]
    H = res.H[np.ix_(f, f)]
    try:
        s = float(g @ np.linalg.solve(H, g))
    except np.linalg.LinAlgError:
        s = float(g @ np.linalg.pinv(H) @ g)
    return {'stat': s, 'df': len(f), 'p': float(stats.chi2.sf(max(s, 0.0), len(f)))}


@api('fitmodel.mixed')
def mixed(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, center=True, mixed=None, table_name='data'):
    spec = _mx_spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, center=center, mixed=mixed)
    m = _mixed_model(table, rows, spec)
    return _report(m, alpha, table, rows, table_name)


def _report(m, alpha, table, rows, table_name):
    method = m.opts['ddfm']
    res, d = m.res, m.d
    fs = _fit_stats(m)
    vcrows, allsum = _covparm_rows(m, alpha)
    preds, coefs = _blup_rows(m, alpha)
    X0 = m.X0
    marg = X0 @ res.beta
    cond = marg + _zu_rows(m)
    if m.glmm:
        inv = _LINKS[m.glmm['link']][1]
        actual = d.df[d.y_alias].to_numpy(float) if not isinstance(d.df[d.y_alias].dtype, pd.CategoricalDtype) else None
        ev0, nt0, _t = _glmm_response(m.tid, m.spec['y'], d, m.glmm, d.df.index)
        actual = ev0 / nt0
        diag = {'rows': [int(i) for i in d.df.index], 'actual': actual, 'predicted': inv(cond), 'marginal': inv(marg),
                'residual': actual - inv(cond), 'marg_resid': actual - inv(marg), 'linpred': cond, 'marg_linpred': marg}
    else:
        actual = d.df[d.y_alias].to_numpy(float)
        diag = {'rows': [int(i) for i in d.df.index], 'actual': actual, 'predicted': cond, 'marginal': marg, 'residual': actual - cond,
                'marg_resid': actual - marg}
    rm = _rmatrix(m)
    out = {
        'fit': {**fs, 'n': fs['sumfreq'], 'converged': bool(res.converged), 'iterations': res.iters, 'method': 'REML',
                'ddfm': method, 'unbounded': m.opts['unbounded'], 'glmm': m.glmm},
        'summary': _summary_of_fit(m) if not m.glmm else None,
        'varcomp': vcrows, 'vc_only': _vc_only(m), 'allsum': allsum,
        'repeated': _repeated_rows(m, alpha), 'structure': {k: v for k, v in m.rdesc.items() if k in ('kind', 'label', 'repeated', 'subject', 'sptype')},
        'rmatrix': rm,
        'estimates': _fixed_rows(m, alpha, method), 'tests': _test_rows(m, method),
        'blups': preds, 'coefs': coefs,
        'history': [{'iter': i, 'm2ll': v, 'params': list(th)} for i, v, th in res.hist],
        'param_names': [p.label for p in m.pars],
        'factors': _factors(d), 'key': m.key, 'alpha': alpha, 'notes': _notes(m, method),
        'diag': diag, 'score': _score_test(m) if not res.converged else None,
        'lsm_effects': [e['label'] for e in d.effects if all(d.alias[c] in d.categorical for c in e['cols'])],
        'covfixed': {'names': [_tlabel(d, m.fe_names[j]) for j in m.order], 'cov': _cov_fixed(m, method)},
        'covparms': {'names': [p.label for p in m.pars], 'cov': res.Wcov},
        'random_effects': [inf['label'] for inf in m.ginfo],
    }
    out['code'] = _mixed_code(m, table, table_name, rows, alpha)
    out['plot_code'] = _mixed_plots(m, table, rows, table_name, None)
    if m.glmm:
        out['fit']['gen_chisq'] = float(res.E['rVr'])
        out['fit']['gen_chisq_df'] = float(res.E['rVr']) / max(len(m.rep) - m.X.shape[1], 1)
        out['fit']['glmm_iter'] = m.glmm_iter
    return out


# ---------------------------------------------------------------------------
# the code under the reports: the same REML, dense, in plain numpy
# ---------------------------------------------------------------------------

def _code_R(m):
    """The lines that define R(th) (the residual covariance over the rows,
    th the structure's own parameters) and which parameters are variances,
    correlations, ranges."""
    rs = m.rs
    kind = rs.kind
    L = []
    rd = m.rdesc
    if kind == 'residual':
        if rs.fixed_scale is not None:
            L.append('def R(th):   # the pseudo-data\'s residual covariance, the scale fixed at 1')
            L.append('    return np.diag(winv)')
        else:
            L.append('def R(th):   # the residual variance (divided by the weights)')
            L.append('    return th[0] * np.diag(winv)')
        return L
    subj = rd.get('subject') or []
    if subj:
        L.append(f'sub = codes({J(subj)})   # the subjects: R is block diagonal over them')
    else:
        L.append('sub = np.zeros(n, dtype=int)   # no subject: one block of every row')
    L.append('same = sub[:, None] == sub[None, :]')
    L.append('sw = np.sqrt(np.outer(winv, winv))')
    if kind in ('sp', 'spn'):
        L.append(f'xy = d[{J(rd["repeated"])}].to_numpy(float)   # the coordinates')
        L.append('dist = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1))')
        f = {'pow': 'rho ** dist', 'exp': 'np.exp(-dist / rho)', 'gau': 'np.exp(-(dist / rho) ** 2)',
             'sph': 'np.where(dist < rho, 1 - 1.5 * dist / rho + 0.5 * (dist / rho) ** 3, 0.0)'}[rs.sptype]
        L.append(f'def R(th):   # spatial {_SP_LABEL[rs.sptype].lower()}: th = [range' + (', nugget' if kind == 'spn' else '') + ', residual]')
        L.append('    rho = th[0]')
        L.append(f'    F = {f}')
        if kind == 'spn':
            L.append('    F = F + th[1] * np.eye(n)   # the nugget, scaled by the residual')
        L.append('    return th[-1] * np.where(same, F, 0.0) * sw')
        return L
    rname = rd['repeated'][0]
    a = m.d.alias[rname]
    if a in m.d.categorical:
        L.append(f'lev = d[{J(rname)}].cat.codes.to_numpy()   # the Repeated column\'s level of each row')
    else:
        L.append(f'lev = np.unique(d[{J(rname)}].to_numpy(float), return_inverse=True)[1].ravel()   # the Repeated values, in order')
    L.append(f'J = {rs.J}')
    uneq = kind in _R_UNEQ
    if kind in ('ar1', 'arh'):
        tl = f'd[{J(rname)}].to_numpy(float)' if a not in m.d.categorical else 'lev.astype(float)'
        L.append(f'tt = {tl}')
        L.append('dist = np.abs(tt[:, None] - tt[None, :])')
    L.append('eye = np.eye(n, dtype=bool)')
    if kind == 'uneqvar':
        L += ['def R(th):   # a variance for each level of the Repeated column', '    return np.diag(th[lev] * winv)']
        return L
    if kind == 'un':
        L += ['iu = [(i, j) for i in range(J) for j in range(i + 1)]   # the order of the covariances',
              'def R(th):   # unstructured: a covariance for each pair of levels',
              '    S = np.zeros((J, J))',
              '    for t, (i, j) in zip(th, iu): S[i, j] = S[j, i] = t',
              '    return np.where(same, S[lev][:, lev], 0.0) * sw']
        return L
    corr = {'cs': 'np.where(eye, 1.0, th[k])', 'csh': 'np.where(eye, 1.0, th[k])', 'ar1': 'th[k] ** dist', 'arh': 'th[k] ** dist',
            'toep': 'np.where(eye | (lag == 0), 1.0, np.r_[1.0, th[k:k + J - 1]][lag])',
            'toeph': 'np.where(eye | (lag == 0), 1.0, np.r_[1.0, th[k:k + J - 1]][lag])',
            'ante': 'ante(th[k:k + J - 1])', 'antevar': 'ante(th[k:k + J - 1])'}[kind]
    if kind in ('toep', 'toeph'):
        L.append('lag = np.abs(lev[:, None] - lev[None, :])')
    if kind in ('ante', 'antevar'):
        L += ['lo, hi = np.minimum(lev[:, None], lev[None, :]), np.maximum(lev[:, None], lev[None, :])',
              'def ante(r):   # the product of the adjacent correlations between the two levels',
              '    c = np.r_[1.0, np.cumprod(r)]',
              '    return np.where(lo == hi, 1.0, c[hi] / np.where(c[lo] == 0, 1e-300, c[lo]))']
    if uneq:
        L += [f'def R(th):   # {_R_LABEL[kind]}: th = [a variance for each level, the correlations]',
              '    k = J',
              '    s = np.sqrt(np.maximum(th[:J], 0))[lev]',
              f'    C = {corr}',
              '    return np.where(same, C, 0.0) * np.outer(s, s) * sw']
    else:
        L += [f'def R(th):   # {_R_LABEL[kind]}: th = [the correlations, the variance]',
              '    k = 0',
              f'    C = {corr}',
              '    return th[-1] * np.where(same, C, 0.0) * sw']
    return L


def _mixed_fit_code(m, table, table_name, rows, imports=(), full=False, alpha=0.05, tables=True):
    """Runnable code that fits the model as the report does: the design, V
    as a function of the covariance parameters, REML by Fisher scoring with
    step halving (V kept positive definite), the fixed effects and the
    BLUPs. full: also the Kenward-Roger (or Satterthwaite) tables."""
    d, rs, opts = m.d, m.rs, m.opts
    spec = m.spec
    ycols = list(spec['y'][:2]) if m.glmm and m.glmm['dist'] == 'binomial' and len(spec['y']) > 1 else []
    extra = [c for c in [spec['weight'], spec['freq']] + ycols if c]
    head = _code_frame(d, table, table_name, rows, extra + list(opts['repeated']) + list(opts['subject']),
                       ['import patsy', 'from scipy import stats', *imports])
    L = list(head)
    L.append(f'Xd = patsy.dmatrix({J(_mx_formula(d, lhs=False))}, d)   # the fixed effects, coded as the report codes them')
    if spec['freq']:
        L.append(f'rows = np.repeat(np.arange(len(d)), np.floor(d[{J(spec["freq"])}].to_numpy(float) + 1e-9).astype(int))   # Freq: each row that many times')
        L.append('d = d.iloc[rows]; X = np.asarray(Xd, dtype=float)[rows]')
    else:
        L.append('X = np.asarray(Xd, dtype=float)')
    g = m.glmm
    if g:
        if g['dist'] == 'binomial' and len(spec['y']) > 1:
            L.append(f'ev, nt = d[{J(spec["y"][0])}].to_numpy(float), d[{J(spec["y"][1])}].to_numpy(float)   # events and trials')
        elif g['dist'] == 'binomial':
            yc = spec['y'][0]
            if d.y_alias in d.levels:
                L.append(f'ev = (d[{J(yc)}] == {_pylit(m.target)}).to_numpy(float); nt = np.ones(len(ev))   # the event: {one_line(m.target)}')
            else:
                L.append(f'ev = d[{J(yc)}].to_numpy(float); nt = np.ones(len(ev))')
        else:
            L.append(f'ev = d[{J(spec["y"][0])}].to_numpy(float); nt = np.ones(len(ev))   # the counts')
        L.append('y = ev / nt')
    else:
        L.append(f'y = d[{J(spec["y"][0])}].to_numpy(float)')
    L.append(f'winv = 1 / d[{J(spec["weight"])}].to_numpy(float)   # R = residual variance / weight' if spec['weight'] else 'winv = np.ones(len(y))')
    L += ['n, p = X.shape',
          'def codes(cols):   # each row\'s level of the combination of cols, in the table\'s level order',
          '    c = np.column_stack([d[k].cat.codes.to_numpy() for k in cols])',
          '    return np.unique(c, axis=0, return_inverse=True)[1].ravel()',
          'def indicators(k):',
          '    return (k[:, None] == np.arange(k.max() + 1)[None, :]).astype(float)',
          '# the G side: V = sum of th[k] * VG[k] over the random effects\' covariance parameters, plus R',
          'VG, Zs = [], []']
    for c, inf in zip(m.comps, m.ginfo):
        cats = inf['cats']
        L.append(f'Z = indicators(codes({J(cats)}))   # {one_line(inf["label"])}: its levels')
        zs = []
        for a, cname in enumerate(c.coefs):
            if cname == 'Intercept':
                zs.append('Z')
            else:
                nums = cname.split('*')
                zs.append('Z * ' + ' * '.join(f'd[{J(nm)}].to_numpy(float)[:, None]' for nm in nums))
        if c.c == 1:
            L.append(f'Zs.append([{zs[0]}]); VG.append(Zs[-1][0] @ Zs[-1][0].T)')
        else:
            L.append(f'Zs.append([{", ".join(zs)}])   # the coefficients {one_line(", ".join(c.coefs))}: an unstructured covariance per level')
            L.append(f'for i, j in [(i, j) for i in range({c.c}) for j in range(i + 1)]:')
            L.append('    VG.append(Zs[-1][i] @ Zs[-1][j].T + (Zs[-1][j] @ Zs[-1][i].T if i != j else 0))')
    nG = sum(len(c.pidx) for c in m.comps)
    L += _code_R(m)
    names = [p.label for p in m.pars]
    L.append(f'names = {J(names)}   # the covariance parameters')
    L.append(f'nG = {nG}')
    L += ['def V(th):',
          '    return sum((t * D for t, D in zip(th[:nG], VG)), np.zeros((n, n))) + R(th[nG:])',
          'def dV(th):   # the derivatives of V (the R side numerically)',
          '    out = list(VG)',
          '    for k in range(nG, len(th)):',
          '        h = 1e-6 * max(1.0, abs(th[k])); a, b = th.copy(), th.copy(); a[k] += h; b[k] -= h',
          '        out.append((R(a[nG:]) - R(b[nG:])) / (2 * h))',
          '    return out']
    ok = []
    for k, p in enumerate(m.pars):
        if p.kind == 'var' and (p.side == 'R' or p.tr == 'log'):
            ok.append(f'th[{k}] > 0')
        elif p.kind == 'var' and p.tr == 'nonneg':
            ok.append(f'th[{k}] >= 0')
        elif p.kind == 'corr':
            ok.append(f'0 < th[{k}] < 1' if p.tr == 'logit' else f'-1 < th[{k}] < 1')
        elif p.kind == 'range':
            ok.append(f'0 < th[{k}] < 1' if rs.sptype == 'pow' else f'th[{k}] > 0')
        elif p.kind == 'nugget':
            ok.append(f'th[{k}] >= 0')
    for c in m.comps:
        if c.c > 1:
            k0 = c.pidx[0]
            ok.append(f'min(np.linalg.eigvalsh(unvech(th[{k0}:{k0 + len(c.pidx)}], {c.c}))) >= 0')
    if any(c.c > 1 for c in m.comps):
        L += ['def unvech(v, c):', '    S = np.zeros((c, c))', '    for t, (i, j) in zip(v, [(i, j) for i in range(c) for j in range(i + 1)]): S[i, j] = S[j, i] = t',
              '    return S']
    L += ['def valid(th):   # the parameters\' own ranges (V positive definite is checked by the Cholesky factor)',
          f'    return {" and ".join(ok) if ok else "True"}',
          'def reml(th):   # -2 REML log-likelihood and what goes with it; None where V is not positive definite',
          '    if not valid(th): return None',
          '    V_ = V(th)',
          '    try: Lc = np.linalg.cholesky(V_)',
          '    except np.linalg.LinAlgError: return None',
          '    Vi = np.linalg.inv(V_); A = X.T @ Vi @ X; Cf = np.linalg.inv(A)',
          '    b = Cf @ X.T @ Vi @ y; r = y - X @ b',
          '    val = (n - p) * np.log(2 * np.pi) + 2 * np.sum(np.log(np.diag(Lc))) + np.linalg.slogdet(A)[1] + r @ Vi @ r',
          '    return {"m2": val, "Vi": Vi, "C": Cf, "b": b, "r": r, "P": Vi - Vi @ X @ Cf @ X.T @ Vi, "logdet": 2 * np.sum(np.log(np.diag(Lc)))}',
          'def score(th, f):',
          '    Py = f["P"] @ y',
          '    return np.array([-0.5 * np.trace(f["P"] @ D) + 0.5 * Py @ D @ Py for D in dV(th)])']
    # starting values, as the report's (its search kept the start that reached the highest likelihood)
    th0 = getattr(m.res, 'start', None)
    if th0 is None:
        th0 = _start(m.eng, m.pars, m.y, m.X, m.rs.winv)
    why = ('the start the report kept of the several it tried (the likelihood of a spatial structure can have more than one maximum)'
           if getattr(m.res, 'starts', 1) > 1 and m.rs.kind in ('sp', 'spn') else
           'the least squares residual variance, a quarter of it per variance component')
    L.append(f'th = np.array({J([float(v) for v in th0])})   # starting values: {why}')
    bounded = [k for k, p in enumerate(m.pars) if p.tr == 'nonneg']
    L.append(f'bounded = {J(bounded)}   # variance components held at or above zero (Unbounded Variance Components off)' if bounded else 'bounded = []   # Unbounded Variance Components: any values that keep V positive definite')
    if g:
        L += _scoring_code(call=False)
        L += _glmm_loop_code(g)
    else:
        L += _scoring_code()
    L += ['beta, Phi = f["b"], f["C"]', 'print("-2 Residual Log Likelihood", f["m2"])']
    # BLUPs
    L += ['# the random effects\' predictions (BLUPs): G Z\'V^-1 (y - X b)', 'e = f["Vi"] @ f["r"]', 'k, blups = 0, []']
    for c in m.comps:
        if c.c == 1:
            L.append('blups.append(th[k] * (Zs[len(blups)][0].T @ e)); k += 1')
        else:
            L.append(f'S = unvech(th[k:k + {len(c.pidx)}], {c.c}); Zc = Zs[len(blups)]')
            L.append(f'blups.append(np.column_stack([sum(S[a, b_] * (Zc[b_].T @ e) for b_ in range({c.c})) for a in range({c.c})])); k += {len(c.pidx)}')
    if full:
        L += _kr_code(m, alpha, tables)
    fit_line = 'fit = SimpleNamespace(llf=-f["m2"] / 2, params=th, fe_params=beta, blups=blups)   # the fit, as a results object'
    L.insert(1, 'from types import SimpleNamespace')
    L.append(fit_line)
    return L


def _scoring_code(call=True):
    L = ['def fit_reml(th):   # Fisher scoring, each step halved until -2 log L falls (and V stays positive definite)',
         '    f = reml(th)',
         '    for it in range(500):',
         '        D = dV(th); PD = [f["P"] @ Dk for Dk in D]',
         '        g = score(th, f)',
         '        I = np.array([[0.5 * np.sum(a * b.T) for b in PD] for a in PD])   # the expected information',
         '        free = [k for k in range(len(th)) if not (k in bounded and th[k] <= 0 and g[k] <= 0)]',
         '        step = np.zeros(len(th)); step[free] = np.linalg.solve(I[np.ix_(free, free)], g[free])',
         '        if g[free] @ step[free] < 1e-14: break   # the relative gradient: converged',
         '        t = 1.0',
         '        while t > 1e-10:',
         '            th2 = th + t * step; th2[bounded] = np.maximum(th2[bounded], 0)',
         '            f2 = reml(th2)',
         '            if f2 is not None and f2["m2"] <= f["m2"] + 1e-11 * abs(f["m2"]): break',
         '            t /= 2',
         '        if t <= 1e-10: break',
         '        th, f = th2, f2',
         '    return th, f']
    if call:
        L.append('th, f = fit_reml(th)')
    return L


def _glmm_loop_code(g):
    link = g['link']
    lk = {'logit': ('np.log(mu / (1 - mu))', '1 / (1 + np.exp(-eta))', '1 / (mu * (1 - mu))'),
          'probit': ('stats.norm.ppf(mu)', 'stats.norm.cdf(eta)', '1 / stats.norm.pdf(stats.norm.ppf(mu))'),
          'cloglog': ('np.log(-np.log(1 - mu))', '1 - np.exp(-np.exp(eta))', '-1 / ((1 - mu) * np.log(1 - mu))'),
          'log': ('np.log(mu)', 'np.exp(eta)', '1 / mu')}[link]
    var = 'mu * (1 - mu) / nt' if g['dist'] == 'binomial' else 'mu'
    start = '(ev + 0.5) / (nt + 1)' if g['dist'] == 'binomial' else 'ev + 0.5'
    clip = 'np.clip(mu, 1e-10, 1 - 1e-10)' if g['dist'] == 'binomial' else 'np.maximum(mu, 1e-10)'
    L = [f'mu = {start}; base_winv = winv.copy(); prev = None',
         'for outer in range(100):   # RSPL: the linearized pseudo-response fitted by REML, then the linear predictor updated',
         f'    eta = {lk[0]}; deta = {lk[2]}',
         '    y = eta + (ev / nt - mu) * deta',
         f'    winv = base_winv * ({var}) * deta ** 2   # 1 / the pseudo-data\'s weights']
    L += ['    th, f = fit_reml(th)']
    L += ['    e = f["Vi"] @ f["r"]; k = 0; eta = X @ f["b"]',
          '    for Zc_ in Zs:',
          '        c = len(Zc_); m_ = c * (c + 1) // 2',
          '        S = np.array([[th[k]]]) if c == 1 else unvech(th[k:k + m_], c)',
          '        u = np.column_stack([sum(S[a, b_] * (Zc_[b_].T @ e) for b_ in range(c)) for a in range(c)])',
          '        eta = eta + sum(Zc_[a] @ u[:, a] for a in range(c)); k += m_',
          f'    mu = {lk[1]}; mu = {clip}',
          '    cur = np.r_[f["b"], th]',
          '    if prev is not None and np.max(np.abs(cur - prev) / np.maximum(np.abs(prev), 1e-8)) < 1e-8: break',
          '    prev = cur']
    return L


def _kr_code(m, alpha, tables=True):
    """The Kenward-Roger (first-order) or Satterthwaite tables, as code
    (tables=False: the covariance and the df function only)."""
    method = m.opts['ddfm']
    L = ['def inference(th, f):   # the covariance of the fixed effects and the df function at the fit',
         '    # the covariance of the covariance parameters: the inverse observed information (the score differentiated numerically)',
         '    H = np.zeros((len(th), len(th)))',
         '    for k in range(len(th)):',
         '        h = 1e-5 * max(abs(th[k]), 1e-2); a, b = th.copy(), th.copy(); a[k] += h; b[k] -= h',
         '        H[:, k] = -(score(a, reml(a)) - score(b, reml(b))) / (2 * h)',
         '    free = [k for k in range(len(th)) if not (k in bounded and th[k] <= 0)]',
         '    W = np.zeros_like(H); W[np.ix_(free, free)] = np.linalg.inv((H[np.ix_(free, free)] + H[np.ix_(free, free)].T) / 2)',
         '    Vi, C, D = f["Vi"], f["C"], dV(th)',
         '    Pk = [-(X.T @ Vi @ Dk @ Vi @ X) for Dk in D]',
         '    dPhi = [-(C @ P @ C) for P in Pk]']
    if method == 'kr':
        L += ['    Lam = sum(W[a, b] * (X.T @ Vi @ D[a] @ Vi @ D[b] @ Vi @ X - Pk[a] @ C @ Pk[b]) for a in free for b in free)',
              '    PhiA = C + 2 * C @ Lam @ C   # the Kenward-Roger adjusted covariance of the fixed effects',
              '    def ddf(Lm):   # Kenward and Roger\'s F scale and denominator df for Lm b = 0',
              '        l = np.linalg.matrix_rank(Lm @ C @ Lm.T)',
              '        Th = Lm.T @ np.linalg.inv(Lm @ C @ Lm.T) @ Lm',
              '        M = [Th @ C @ P @ C for P in Pk]',
              '        A1 = sum(W[a, b] * np.trace(M[a]) * np.trace(M[b]) for a in free for b in free)',
              '        A2 = sum(W[a, b] * np.sum(M[a] * M[b].T) for a in free for b in free)',
              '        if l == 1: return 1.0, 2 / A1',
              '        B = (A1 + 6 * A2) / (2 * l); g = ((l + 1) * A1 - (l + 4) * A2) / ((l + 2) * A2)',
              '        c1, c2, c3 = g / (3 * l + 2 * (1 - g)), (l - g) / (3 * l + 2 * (1 - g)), (l + 2 - g) / (3 * l + 2 * (1 - g))',
              '        Es = 1 / (1 - A2 / l); Vs = (2 / l) * (1 + c1 * B) / ((1 - c2 * B) ** 2 * (1 - c3 * B))',
              '        mm = 4 + (l + 2) / (l * Vs / (2 * Es ** 2) - 1)',
              '        return mm / (Es * (mm - 2)), mm']
    else:
        L += ['    PhiA = C   # Satterthwaite: the model-based covariance of the fixed effects',
              '    def ddf(Lm):   # Satterthwaite\'s df (Fai and Cornelius\'s for several rows)',
              '        vals, vecs = np.linalg.eigh(Lm @ C @ Lm.T); nus = []',
              '        for dv, v in zip(vals[vals > 1e-10 * vals.max()], vecs[:, vals > 1e-10 * vals.max()].T):',
              '            gk = np.array([v @ Lm @ dP @ Lm.T @ v for dP in dPhi]); nus.append(2 * dv ** 2 / (gk[free] @ W[np.ix_(free, free)] @ gk[free]))',
              '        nus = np.array(nus)',
              '        if len(nus) == 1 or np.allclose(nus, nus[0]): return 1.0, nus.mean()',
              '        Ev = np.sum(nus / (nus - 2)) if np.all(nus > 2) else None',
              '        return 1.0, (2 * Ev / (Ev - len(nus)) if Ev and Ev > len(nus) else 2.0)']
    L += ['    return PhiA, ddf, W, free, C',
          'PhiA, ddf, W, free, Cm = inference(th, f)   # (Cm: the model-based covariance; C stays patsy\'s)']
    if not tables:
        return L
    T = m.T if m.T is not None else np.eye(len(m.fe_names))
    labels = [_tlabel(m.d, m.fe_names[j]) for j in m.order]
    L.append(f'Tm = np.array({J(np.round(T[m.order], 15).tolist())})   # the report\'s parameters: ' + ('the intercept at 0, not at the means' if m.T is not None else 'as fitted'))
    L.append(f'terms = {J(labels)}')
    L += ['for lab, Lr in zip(terms, Tm):   # Fixed Effects Parameter Estimates',
          '    est = Lr @ beta; se = np.sqrt(Lr @ PhiA @ Lr); dfd = ddf(Lr[None, :])[1]',
          f'    tq = stats.t.ppf(1 - {alpha!r} / 2, dfd)',
          '    print(lab, est, se, dfd, est / se, 2 * stats.t.sf(abs(est / se), dfd), est - tq * se, est + tq * se)']
    tests = []
    for e in m.d.effects:
        cols = [m.fe_names.index(t) for t in e.get('terms', []) if t in m.fe_names]
        if cols:
            tests.append((e['label'], cols))
    if tests:
        L.append(f'effects = {J([[lab, cols] for lab, cols in tests])}   # each effect\'s columns of X')
        L += ['for lab, cols in effects:   # Fixed Effects Tests',
              '    Lm = np.eye(p)[cols]; q = np.linalg.matrix_rank(Lm @ Cm @ Lm.T)',
              '    lam, dfd = ddf(Lm)',
              '    F = lam * (Lm @ beta) @ np.linalg.pinv(Lm @ PhiA @ Lm.T) @ (Lm @ beta) / q',
              '    print(lab, len(cols), q, dfd, F, stats.f.sf(F, q, dfd))']
    L += ['for k, nm in enumerate(names):   # the covariance parameters and their standard errors',
          '    print(nm, th[k], np.sqrt(W[k, k]) if k in free else None)']
    return L


def _mixed_code(m, table, table_name, rows, alpha):
    return '\n'.join(_mixed_fit_code(m, table, table_name, rows, full=True, alpha=alpha))


def _mixed_plots(m, table, rows, table_name, out):
    """The mixed report's graphs as code: actual by marginal and by
    conditional predicted, the conditional and marginal residuals."""
    d = m.d
    y = m.spec['y'][0]
    n = len(d.df)
    head = _mixed_fit_code(m, table, table_name, rows, [PLT])
    head = [ln for ln in head if not ln.startswith('print(')]
    if m.spec['freq']:
        head += ['d = d.iloc[np.unique(rows)]; X = np.asarray(Xd, dtype=float); y = y[np.unique(rows, return_index=True)[1]]   # each row once']
    inv = ''
    if m.glmm:
        inv = {'logit': '1 / (1 + np.exp(-{}))', 'probit': 'stats.norm.cdf({})', 'cloglog': '1 - np.exp(-np.exp({}))', 'log': 'np.exp({})'}[m.glmm['link']]
    marg = 'X @ beta'
    cond_lines = ['cond = X @ beta', 'k = 0']
    for c, inf in zip(m.comps, m.ginfo):
        if c.c == 1:
            cond_lines.append('Zc = Zs[k]; cond = cond + Zc[0] @ blups[k]; k += 1' if not m.spec['freq'] else
                              'Zc = [z[np.unique(rows, return_index=True)[1]] for z in Zs[k]]; cond = cond + Zc[0] @ blups[k]; k += 1')
        else:
            cond_lines.append(('Zc = Zs[k]' if not m.spec['freq'] else 'Zc = [z[np.unique(rows, return_index=True)[1]] for z in Zs[k]]')
                              + f'; cond = cond + sum(Zc[a] @ blups[k][:, a] for a in range({c.c})); k += 1')
    base = head + [f'marg = {inv.format(marg) if inv else marg}   # the marginal prediction: the fixed effects alone'] + cond_lines
    if inv:
        base.append(f'cond = {inv.format("cond")}   # on the scale of the mean')
    base.append('actual = y' + ('' if not m.glmm else '   # the observed proportion (count)'))
    line = lambda a: [f'lo, hi = min({a}.min(), actual.min()), max({a}.max(), actual.max())']   # noqa: E731
    fitline = [f'ax.plot([lo, hi], [lo, hi], color="{FIT}", linewidth=1)']
    return {'actCond': _row_plot(base + line('cond'), 'cond', 'actual', n, f'{y} Conditional Predicted', f'{y} Actual', f'{y} actual by conditional predicted', 400, 320, fitline),
            'actMarg': _row_plot(base + line('marg'), 'marg', 'actual', n, f'{y} Predicted', f'{y} Actual', f'{y} actual by predicted', 400, 320, fitline),
            'resCond': _row_plot(base, 'cond', 'actual - cond', n, f'{y} Conditional Predicted', 'Conditional Residual', 'conditional residuals', zero=True),
            'resMarg': _row_plot(base, 'marg', 'actual - marg', n, f'{y} Predicted', f'{y} Residual', 'marginal residuals', zero=True)}


def _mixed_interaction_parts(m, table, table_name, rows):
    """For fit_model's Interaction Plots code: the lines that fit the model,
    the design's design_info, and the prediction of the design rows L."""
    base = [ln for ln in _mixed_fit_code(m, table, table_name, rows, [PLT]) if not ln.startswith('print(')]
    inv = ''
    if m.glmm:
        inv = {'logit': '1 / (1 + np.exp(-({})))', 'probit': 'stats.norm.cdf({})', 'cloglog': '1 - np.exp(-np.exp({}))', 'log': 'np.exp({})'}[m.glmm['link']]
    pred = f'    return {inv.format("L @ beta") if inv else "L @ beta"}   # the fixed effects\' prediction (the marginal mean)'
    return base, 'Xd.design_info', [pred]


# ---------------------------------------------------------------------------
# predictions (the profilers), and what fit_model's older callers read
# ---------------------------------------------------------------------------

def _mixed_predict(m, settings, alpha):
    """The marginal prediction (the fixed effects) at the settings, with the
    confidence interval of the mean from the report's covariance of the
    fixed effects and degrees of freedom (Kenward-Roger or Satterthwaite)."""
    L = m.coder.rows(settings)
    names = list(m.coder.names)
    idx = [m.fe_names.index(nm) for nm in names]
    b = m.res.beta[idx]
    C = m.res.cov(m.opts['ddfm'])[np.ix_(idx, idx)]
    est = L @ b
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', L, C, L), 0))
    tq = np.empty(len(est))
    cache = {}
    for i, Lr in enumerate(L):
        key = tuple(np.round(Lr, 12))
        if key not in cache:
            Lf = np.zeros(len(m.fe_names))
            Lf[idx] = Lr
            _lam, df = m.res.ddf(Lf[None, :], m.opts['ddfm'])
            cache[key] = float(stats.t.ppf(1 - alpha / 2, df)) if np.isfinite(df) and df > 0 else float(stats.norm.ppf(1 - alpha / 2))
        tq[i] = cache[key]
    lo, hi = est - tq * se, est + tq * se
    name = m.spec['y'][0]
    if m.glmm:
        inv = _LINKS[m.glmm['link']][1]
        return [{'name': f'{name} (mean)', 'pred': inv(est), 'lower': inv(lo), 'upper': inv(hi)}]
    return [{'name': name, 'pred': est, 'lower': lo, 'upper': hi}]


def _zmatrix(d, cols):
    """The random effect's design: an indicator of each combination of its
    categorical columns, times its continuous columns."""
    cats = [d.alias[c] for c in dict.fromkeys(cols) if d.alias[c] in d.categorical]
    nums = [d.alias[c] for c in cols if d.alias[c] not in d.categorical]
    n = len(d.df)
    if cats:
        codes = [tuple(r) for r in np.column_stack([d.df[a].cat.codes.to_numpy() for a in cats]).tolist()]
        uniq = sorted(set(codes))
        pos = {u: i for i, u in enumerate(uniq)}
        Z = np.zeros((n, len(uniq)))
        Z[np.arange(n), [pos[v] for v in codes]] = 1.0
        labels = [','.join(_lvl(d.levels[a][c]) for a, c in zip(cats, u)) for u in uniq]
    else:
        Z = np.ones((n, 1))
        labels = ['']
    for a in nums:
        Z = Z * d.df[a].to_numpy(float)[:, None]
    return Z, labels


def _reml(m):
    """The dense REML quantities of a variance-component model at the fit:
    the covariance of the fixed effects C, the expected information, the
    derivatives of C (Satterthwaite's), the REML log-likelihood and the
    BLUPs (for fit_model's older callers and tests)."""
    res, eng = m.res, m.eng
    E = eng.evaluate(res.theta, 0)
    E['exact'] = True
    eng.derive(E, 2)
    kr = res.kr_parts()
    order = list(range(len(m.pars)))
    return {'C': res.Phi, 'b': res.beta, 'A': np.linalg.pinv(E['info']), 'info': E['info'],
            'dC': [kr['dPhi'].get(k, np.zeros_like(res.Phi)) for k in order], 'llr': res.ll,
            'blups': [b['u'][:, 0] if b['u'].shape[1] == 1 else b['u'] for b in res.blups()]}


def _satterthwaite(dense, L):
    """Satterthwaite's df of L b from _reml's quantities (one row), Fai and
    Cornelius's for several."""
    L = np.atleast_2d(L)
    C, A, dC = dense['C'], dense['A'], dense['dC']
    M = L @ C @ L.T
    vals, vecs = np.linalg.eigh(M)
    keep = vals > 1e-10 * max(vals.max(), 1e-300)
    nus = []
    for dval, vec in zip(vals[keep], vecs[:, keep].T):
        lm = vec @ L
        g = np.array([lm @ D @ lm for D in dC])
        den = float(g @ A @ g)
        nus.append(2 * dval * dval / den if den > 0 else float('inf'))
    q = len(nus)
    if q == 0:
        return float('nan')
    if q == 1:
        return float(nus[0])
    nus = np.asarray(nus)
    if np.all(np.abs(np.diff(nus)) < 1e-8):
        return float(nus.mean())
    if np.any(nus <= 2):
        return 2.0
    Ev = float(np.sum(nus / (nus - 2)))
    return 2 * Ev / (Ev - q) if Ev > q else float('nan')


class _CompatComp(dict):
    """A random effect as fit_model's older code described it."""


def _compat(m):
    """Keys fit_model's older mixed code (and its tests) read: X, y, scale,
    comps [{label, var, Z, levels}], dense."""
    comps = []
    if all(c.c == 1 for c in m.comps) and len(m.rep) * sum(c.q for c in m.comps) <= 4_000_000:
        for c in m.comps:
            Z = np.zeros((len(m.rep), c.q))
            ok = c.codes >= 0
            Z[np.arange(len(m.rep))[ok], c.codes[ok]] = c.vals[ok, 0]
            comps.append(_CompatComp(label=c.label, var=float(m.res.theta[c.pidx[0]]), Z=Z, levels=c.levels))
    return comps


def _mixed_getitem(self, key):
    if key == 'dense':
        if 'dense' not in self.__dict__:
            self.__dict__['dense'] = _reml(self) if self.rs.kind == 'residual' and all(c.c == 1 for c in self.comps) else None
        return self.__dict__['dense']
    if key == 'comps':
        return _compat(self)
    return self.__dict__[key]


_Mixed.__getitem__ = _mixed_getitem
_Mixed.get = lambda self, key, default=None: self.__dict__.get(key, default)


# ---------------------------------------------------------------------------
# least squares means: comparisons, letters, contrasts, slices
# ---------------------------------------------------------------------------

def _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed):
    spec = _mx_spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, center=center, mixed=mixed)
    return _mixed_model(table, rows, spec)


def _estimable_rows(m, L):
    """Rows of L in the row space of X (estimable functions)."""
    X = m.X0
    P = np.linalg.pinv(X) @ X
    dev = np.abs(L - L @ P).max(axis=1) if len(L) else np.zeros(0)
    return dev <= 1e-7 * np.maximum(1.0, np.abs(L).max(axis=1) if len(L) else 1.0)


def _df_of(m, L):
    return m.res.ddf(np.atleast_2d(L), m.opts['ddfm'])[1]


def _tq(alpha, df):
    return float(stats.t.ppf(1 - alpha / 2, df)) if np.isfinite(df) and df > 0 else float(stats.norm.ppf(1 - alpha / 2))


def _mx_lsmeans(m, e, alpha):
    """The least squares means of an effect of categorical factors: the
    fixed effects' prediction at each level (combination), the other
    categorical factors averaged over their levels and the continuous ones
    at their means (JMP's), with the mixed covariance (Kenward-Roger's or
    the model-based one) and each mean's own denominator df."""
    d = m.d
    names = list(dict.fromkeys(e['cols']))
    aliases = [d.alias[n] for n in names]
    if any(a not in d.categorical for a in aliases):
        return None
    levels = [d.levels[a] for a in aliases]
    codes = np.column_stack([d.df[a].cat.codes.to_numpy() for a in aliases])
    if e['spec']['nest']:
        seen = {tuple(r) for r in codes.tolist()}
        combos = [c for c in itertools.product(*[range(len(lv)) for lv in levels]) if c in seen]
    else:
        combos = list(itertools.product(*[range(len(lv)) for lv in levels]))
    others = {a: AVG for a in d.categorical if a not in aliases}
    settings = [dict(others, **{a: i for a, i in zip(aliases, c)}) for c in combos]
    L = m.coder.rows(settings)
    b = m.res.beta
    Cf = m.res.cov(m.opts['ddfm'])
    est = L @ b
    C = L @ Cf @ L.T
    se = np.sqrt(np.maximum(np.diag(C), 0))
    ok = _estimable_rows(m, L)
    est = np.where(ok, est, np.nan)
    se = np.where(ok, se, np.nan)
    dfs = np.array([_df_of(m, L[i]) if ok[i] else np.nan for i in range(len(L))])
    yv = m.y if not m.glmm else None
    raw, cnt = [], []
    w0 = m.w0
    ya = d.df[d.y_alias].to_numpy(float) if not m.glmm else None
    if m.glmm:
        ev0, nt0, _t = _glmm_response(m.tid, m.spec['y'], d, m.glmm, d.df.index)
        ya = ev0 / nt0
    for c in combos:
        mask = np.all(codes == np.asarray(c), axis=1) & m.keep
        wv = (w0 * np.floor(m.f0 + 1e-9))[mask]
        cnt.append(float(np.sum(wv)))
        raw.append(float(np.average(ya[mask], weights=wv)) if mask.any() and np.sum(wv) > 0 else None)
    del yv
    labels = [','.join(data.level_label(m.tid, names[k], levels[k][i], _lvl(levels[k][i])) for k, i in enumerate(c)) for c in combos]
    lo = np.array([est[i] - _tq(alpha, dfs[i]) * se[i] if ok[i] else np.nan for i in range(len(est))])
    hi = np.array([est[i] + _tq(alpha, dfs[i]) * se[i] if ok[i] else np.nan for i in range(len(est))])
    out = {'effect': e['label'], 'factors': names, 'levels': [[levels[k][i] for k, i in enumerate(c)] for c in combos], 'labels': labels,
           'lsmean': est, 'se': se, 'dfden': dfs, 'lower': lo, 'upper': hi, 'mean': raw, 'n': cnt, 'L': L, 'C': C, 'estimable': ok,
           'combos': combos}
    if m.glmm:
        inv = _LINKS[m.glmm['link']][1]
        # the inverse link: the mean (a probability or a rate) and its delta-method standard error
        h = 1e-6
        dmu = (inv(est + h) - inv(est - h)) / (2 * h)
        out.update({'mu': inv(est), 'mu_se': np.abs(dmu) * se, 'mu_lower': inv(lo), 'mu_upper': inv(hi)})
    return out


def _slices(lsm):
    """Test Slices of an interaction's least squares means: for each factor
    and each of its levels, the contrasts among the cells at that level
    (each cell against the first), whose joint test is the slice. Generic:
    lsm needs 'factors', 'combos' (level indices of each cell) and 'labels'
    of the factors' levels as the page shows them ('levels' raw)."""
    out = []
    facs = lsm['factors']
    if len(facs) < 2:
        return out
    combos = lsm['combos']
    for fi, fname in enumerate(facs):
        vals = sorted({c[fi] for c in combos})
        for v in vals:
            cells = [i for i, c in enumerate(combos) if c[fi] == v]
            if len(cells) < 2:
                continue
            K = np.zeros((len(cells) - 1, len(combos)))
            for r, j in enumerate(cells[1:]):
                K[r, cells[0]] = -1.0
                K[r, j] = 1.0
            lv = lsm['levels'][cells[0]][fi]
            out.append({'factor': fname, 'level': lv, 'cells': cells, 'K': K})
    return out


def _lsm_rows(m, lsm, tid):
    rows = []
    for k in range(len(lsm['labels'])):
        r = {'level': lsm['labels'][k], 'lsmean': lsm['lsmean'][k], 'se': lsm['se'][k], 'dfden': lsm['dfden'][k], 'lower': lsm['lower'][k],
             'upper': lsm['upper'][k], 'mean': lsm['mean'][k], 'n': lsm['n'][k]}
        for i, f in enumerate(lsm['factors']):
            v = lsm['levels'][k][i]
            r[f'f{i}'] = data.level_label(tid, f, v, _lvl(v))
        if 'mu' in lsm:
            r.update({'mu': lsm['mu'][k], 'mu_se': lsm['mu_se'][k], 'mu_lower': lsm['mu_lower'][k], 'mu_upper': lsm['mu_upper'][k]})
        rows.append(r)
    return rows


@api('mixed.lsmeans')
def lsmeans(table, y, effects=(), effect=None, rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, center=True, mixed=None,
            table_name='data'):
    m = _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed)
    out = {}
    targets = [e for e in m.d.effects if effect is None or e['label'] == effect]
    for e in targets:
        lsm = _mx_lsmeans(m, e, alpha)
        if lsm is None:
            continue
        out[e['label']] = {'factors': lsm['factors'], 'labels': lsm['labels'], 'levels': lsm['levels'], 'rows': _lsm_rows(m, lsm, table),
                           'lsmean': lsm['lsmean'], 'se': lsm['se'], 'dfden': lsm['dfden'], 'lower': lsm['lower'], 'upper': lsm['upper'],
                           'mean': lsm['mean'], 'estimable': lsm['estimable'], 'glmm': bool(m.glmm),
                           'link': m.glmm['link'] if m.glmm else None,
                           'slices': len(lsm['factors']) >= 2}
    return {'lsmeans': out, 'alpha': alpha, 'code': _lsm_code(m, targets[0] if len(targets) == 1 else None, alpha, table, table_name, rows)
            if targets and _mx_lsmeans(m, targets[0], alpha) is not None else None}


def _mx_compare(m, lsm, method, alpha):
    """All pairwise differences of the least squares means: Student's t or
    Tukey HSD (the studentized range), each difference with its own
    denominator df (Kenward-Roger or Satterthwaite), connecting letters."""
    est, C, L = np.asarray(lsm['lsmean'], dtype=float), lsm['C'], lsm['L']
    idx = [i for i in range(len(est)) if np.isfinite(est[i])]
    k = len(idx)
    if k < 2:
        return {'error': 'fewer than two estimable least squares means'}
    from scipy.stats import studentized_range
    sig = {i: {} for i in idx}
    pairs = []
    for a_, b_ in itertools.combinations(idx, 2):
        dif = est[a_] - est[b_]
        se = math.sqrt(max(C[a_, a_] + C[b_, b_] - 2 * C[a_, b_], 0.0))
        df = _df_of(m, L[a_] - L[b_])
        tv = abs(dif) / se if se > 0 else float('inf')
        dfe = df if np.isfinite(df) and df > 0 else 1e6
        if method == 'tukey':
            p = float(studentized_range.sf(tv * math.sqrt(2), k, dfe)) if np.isfinite(tv) else 0.0
            crit = float(studentized_range.ppf(1 - alpha, k, dfe) / math.sqrt(2))
        else:
            p = float(2 * stats.t.sf(tv, dfe))
            crit = float(stats.t.ppf(1 - alpha / 2, dfe))
        s = p < alpha
        sig[a_][b_] = sig[b_][a_] = s
        hi, lo = (a_, b_) if dif >= 0 else (b_, a_)
        dd = abs(dif)
        pr = {'level': lsm['labels'][hi], 'minus': lsm['labels'][lo], 'diff': dd, 'se': se, 'dfden': df, 't': dd / se if se > 0 else None,
              'lower': dd - crit * se, 'upper': dd + crit * se, 'p': p, 'sig': s, 'crit': crit, 'i': hi, 'j': lo}
        if m.glmm and m.glmm['link'] in ('logit', 'log'):
            pr.update({'ratio': math.exp(dd), 'ratio_lower': math.exp(dd - crit * se), 'ratio_upper': math.exp(dd + crit * se)})
        pairs.append(pr)
    order = sorted(idx, key=lambda i: -est[i])
    let = _letters(order, sig)
    pairs.sort(key=lambda r: -r['diff'])
    return {'method': method, 'alpha': alpha, 'k': k,
            'letters': [{'level': lsm['labels'][i], 'letters': ' '.join(let[i]), 'lsmean': float(est[i]), 'se': float(math.sqrt(max(C[i, i], 0))),
                         **({'mu': float(lsm['mu'][i])} if 'mu' in lsm else {})} for i in order],
            'ordered': pairs, 'ratio': ('Odds Ratio' if m.glmm['link'] == 'logit' else 'Rate Ratio') if m.glmm and m.glmm['link'] in ('logit', 'log') else None}


@api('mixed.compare')
def compare(table, y, effects=(), effect=None, method='tukey', rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, center=True,
            mixed=None, table_name='data'):
    m = _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed)
    e = _effect_of(m.d, effect)
    lsm = _mx_lsmeans(m, e, alpha)
    if lsm is None:
        return {'error': f'{effect} has a continuous factor: least squares means are for categorical effects'}
    out = _mx_compare(m, lsm, 'tukey' if method == 'tukey' else 'student', alpha)
    out['effect'] = effect
    out['code'] = _lsm_code(m, e, alpha, table, table_name, rows, compare='tukey' if method == 'tukey' else 'student')
    return out


@api('mixed.contrast')
def contrast(table, y, effects=(), effect=None, coefs=None, rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, center=True,
             mixed=None, table_name='data'):
    """LSMeans Contrast: each row of coefs weights the effect's least squares
    means; a t test of each (its own df) and the joint F test (Kenward-Roger
    scaled, or Satterthwaite's)."""
    m = _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed)
    e = _effect_of(m.d, effect)
    lsm = _mx_lsmeans(m, e, alpha)
    if lsm is None:
        return {'error': f'{effect} has a continuous factor'}
    K = np.atleast_2d(np.asarray(coefs, dtype=float))
    if K.shape[1] != len(lsm['labels']):
        return {'error': f'give one coefficient per level ({len(lsm["labels"])})'}
    Lc = K @ lsm['L']
    method = m.opts['ddfm']
    b = m.res.beta
    Cf = m.res.cov(method)
    est = Lc @ b
    cov = Lc @ Cf @ Lc.T
    out_rows = []
    for i in range(len(K)):
        se = math.sqrt(max(cov[i, i], 0))
        df = _df_of(m, Lc[i])
        t = est[i] / se if se > 0 else float('nan')
        tc = _tq(alpha, df)
        out_rows.append({'contrast': i + 1, 'estimate': float(est[i]), 'se': se, 'dfden': df, 't': t,
                         'p': float(2 * stats.t.sf(abs(t), df)) if np.isfinite(df) else float(2 * stats.norm.sf(abs(t))),
                         'lower': float(est[i] - tc * se), 'upper': float(est[i] + tc * se)})
        if m.glmm and m.glmm['link'] in ('logit', 'log'):
            out_rows[-1].update({'ratio': math.exp(est[i]), 'ratio_lower': math.exp(est[i] - tc * se), 'ratio_upper': math.exp(est[i] + tc * se)})
    F, q, dfd, p = m.res.test(Lc, method)
    joint = {'numdf': q, 'dendf': dfd, 'f': F, 'p': p} if q else None
    return {'effect': effect, 'labels': lsm['labels'], 'coefs': K, 'rows': out_rows, 'joint': joint,
            'ratio': ('Odds Ratio' if m.glmm['link'] == 'logit' else 'Rate Ratio') if m.glmm and m.glmm['link'] in ('logit', 'log') else None,
            'code': _lsm_code(m, e, alpha, table, table_name, rows, contrast=K)}


@api('mixed.slices')
def slices(table, y, effects=(), effect=None, rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, center=True, mixed=None,
           table_name='data'):
    """Test Slices: for each level of each factor of an interaction, the F
    test that the least squares means of the other factors' combinations at
    that level are equal (Kenward-Roger or Satterthwaite), with the test
    detail (each cell against the first)."""
    m = _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed)
    e = _effect_of(m.d, effect)
    lsm = _mx_lsmeans(m, e, alpha)
    if lsm is None or len(lsm['factors']) < 2:
        return {'error': f'{effect} is not an interaction of categorical factors: Test Slices are for crossings'}
    method = m.opts['ddfm']
    b = m.res.beta
    Cf = m.res.cov(method)
    out = []
    for sl in _slices(lsm):
        cells = sl['cells']
        if not all(lsm['estimable'][c] for c in cells):
            continue
        Lc = sl['K'] @ lsm['L']
        F, q, dfd, p = m.res.test(Lc, method)
        det = []
        for r in range(len(Lc)):
            est = float(Lc[r] @ b)
            se = math.sqrt(max(float(Lc[r] @ Cf @ Lc[r]), 0.0))
            df = _df_of(m, Lc[r])
            t = est / se if se > 0 else float('nan')
            det.append({'contrast': f'{lsm["labels"][cells[r + 1]]} − {lsm["labels"][cells[0]]}', 'estimate': est, 'se': se, 'dfden': df, 't': t,
                        'p': float(2 * stats.t.sf(abs(t), df)) if np.isfinite(df) else None})
        lv = sl['level']
        out.append({'slice': f'{sl["factor"]}={data.level_label(m.tid, sl["factor"], lv, _lvl(lv))}', 'factor': sl['factor'], 'nparm': q,
                    'dfnum': q, 'dfden': dfd, 'f': F, 'p': p, 'detail': det})
    return {'effect': effect, 'rows': out, 'code': _lsm_code(m, e, alpha, table, table_name, rows, slices=True)}


def _lsm_code(m, e, alpha, table, table_name, rows, compare=None, contrast=None, slices=False):
    """Code for the least squares means of an effect (the design rows of each
    level averaged over the other categorical factors' combinations, the
    continuous factors at their means) with the mixed covariance and the
    report's df, and the comparisons, contrasts or slices asked for."""
    if e is None:
        return None
    d = m.d
    names = list(dict.fromkeys(e['cols']))
    others = [n for n in _factor_names(d) if n not in names and d.alias[n] in d.categorical]
    conts = [n for n in _factor_names(d) if d.alias[n] not in d.categorical]
    L = _mixed_fit_code(m, table, table_name, rows, ['import itertools', 'from scipy.stats import studentized_range'], full=True, alpha=alpha,
                        tables=False)
    lev = '[' + ', '.join('[' + ', '.join(_pylit(v) for v in d.levels[d.alias[n]]) + ']' for n in names) + ']'
    oth = '[' + ', '.join('[' + ', '.join(_pylit(v) for v in d.levels[d.alias[n]]) + ']' for n in others) + ']'
    L += [f'effect, others = {J(names)}, {J(others)}   # the effect\'s factors; the categorical factors averaged over',
          f'levels, other_levels = {lev}, {oth}',
          f'means = {{{", ".join(f"{J(n)}: d[{J(n)}].mean()" for n in conts)}}}   # continuous factors at their means',
          'cells = list(itertools.product(*levels))']
    if e['spec']['nest']:
        L.append('cells = [c for c in cells if (d[effect].apply(tuple, axis=1) == c).any()]   # a nested effect: the cells that occur')
    L += ['Lm = []',
          'for cell in cells:',
          '    grid = pd.DataFrame(list(itertools.product(*other_levels)) or [()], columns=others)',
          '    for name, v in zip(effect, cell): grid[name] = v',
          '    for name, v in means.items(): grid[name] = v',
          '    Lm.append(np.asarray(patsy.build_design_matrices([Xd.design_info], grid)[0]).mean(axis=0))',
          'Lm = np.array(Lm); lsm = Lm @ beta; C2 = Lm @ PhiA @ Lm.T',
          'for cell, v, Lr in zip(cells, lsm, Lm):   # Least Squares Means: the estimate, its standard error and df',
          '    se = np.sqrt(Lr @ PhiA @ Lr); dfd = ddf(Lr[None, :])[1]',
          f'    print(cell, v, se, dfd, v - stats.t.ppf(1 - {alpha!r} / 2, dfd) * se, v + stats.t.ppf(1 - {alpha!r} / 2, dfd) * se)']
    if compare:
        L += ['k = len(cells)',
              'for i, j in itertools.combinations(range(k), 2):',
              '    Ld = Lm[i] - Lm[j]; diff = Ld @ beta; se = np.sqrt(Ld @ PhiA @ Ld); dfd = ddf(Ld[None, :])[1]']
        if compare == 'tukey':
            L += [f'    p = studentized_range.sf(abs(diff) / se * np.sqrt(2), k, dfd); crit = studentized_range.ppf(1 - {alpha!r}, k, dfd) / np.sqrt(2)   # Tukey HSD']
        else:
            L += [f'    p = 2 * stats.t.sf(abs(diff) / se, dfd); crit = stats.t.ppf(1 - {alpha!r} / 2, dfd)   # Student\'s t']
        L += ['    print(cells[i], cells[j], diff, se, dfd, diff - crit * se, diff + crit * se, p)']
    if contrast is not None:
        L += [f'K = np.array({J(np.asarray(contrast).tolist())})   # the contrasts\' weights of the levels',
              'Lc = K @ Lm',
              'for Lr in Lc:',
              '    est = Lr @ beta; se = np.sqrt(Lr @ PhiA @ Lr); dfd = ddf(Lr[None, :])[1]',
              '    print(est, se, dfd, est / se, 2 * stats.t.sf(abs(est / se), dfd))',
              'q = np.linalg.matrix_rank(Lc @ Phi @ Lc.T); lam, dfd = ddf(Lc)',
              'F = lam * (Lc @ beta) @ np.linalg.pinv(Lc @ PhiA @ Lc.T) @ (Lc @ beta) / q',
              'print("joint", q, dfd, F, stats.f.sf(F, q, dfd))']
    if slices:
        L += ['for fi, name in enumerate(effect):   # Test Slices: at each level of one factor, the cells of the others equal',
              '    for v in levels[fi]:',
              '        at = [i for i, c in enumerate(cells) if c[fi] == v]',
              '        if len(at) < 2: continue',
              '        Lc = np.array([Lm[j] - Lm[at[0]] for j in at[1:]])',
              '        q = np.linalg.matrix_rank(Lc @ Phi @ Lc.T); lam, dfd = ddf(Lc)',
              '        F = lam * (Lc @ beta) @ np.linalg.pinv(Lc @ PhiA @ Lc.T) @ (Lc @ beta) / q',
              '        print(f"{name}={v}", q, dfd, F, stats.f.sf(F, q, dfd))']
    return '\n'.join(L)


# ---------------------------------------------------------------------------
# Save Columns (every row of the By group whose predictors are present)
# ---------------------------------------------------------------------------

def _row_levels(m, idx):
    """For the rows idx: each random effect's level index (-1 for a level the
    fit did not see or a missing value) and its coefficients' values."""
    tid = m.tid
    out = []
    for c, inf in zip(m.comps, m.ginfo):
        cats = inf['cats']
        fr = data.frame(tid, cats, list(idx), dropna=False)
        pos = {tuple(_lvl(v) for v in r): i for i, r in enumerate(inf['raw'])}
        codes = np.full(len(idx), -1, dtype=np.int64)
        for i, r in enumerate(fr.itertuples(index=False)):
            key = tuple(None if (v is None or (isinstance(v, float) and math.isnan(v))) else _lvl(v) for v in r)
            codes[i] = pos.get(key, -1)
        vals = np.ones((len(idx), c.c))
        for a, cname in enumerate(c.coefs):
            if cname != 'Intercept':
                for nm in cname.split('*'):
                    vals[:, a] = vals[:, a] * _col_num(tid, nm, idx)
        vals[~np.isfinite(vals)] = np.nan
        out.append((codes, vals))
    return out


def _cond_parts(m, theta):
    """The mixed model equations' inverse at theta (the prediction errors of
    [b, u - u]): C11 = Phi, C21 = -G Z'V^-1 X Phi, C22 = G - G Z'P Z G."""
    eng = m.eng
    E = eng.evaluate(theta, 0)
    comps = m.comps
    Z = np.hstack([c.dense() for c in comps]) if comps else np.zeros((eng.n, 0))
    G = np.zeros((Z.shape[1], Z.shape[1]))
    off = np.cumsum([0] + [c.q for c in comps])
    for j, c in enumerate(comps):
        G[off[j]:off[j] + c.q, off[j]:off[j] + c.q] = np.kron(np.eye(c.nl), c.sigma(theta))
    Phi = E['Phi']
    ViZ = eng.apply_vinv(E, Z)
    PZ = ViZ - E['W'] @ (Phi @ (E['W'].T @ Z))
    C21 = -G @ (ViZ.T @ m.X) @ Phi
    C22 = G - G @ (Z.T @ PZ) @ G
    return Phi, C21, C22, off


def _save_values(m, where, alpha):
    d, tid, res = m.d, m.tid, m.res
    method = m.opts['ddfm']
    idx, X, _ = models.new_rows(d, m.di, tid, where)
    b = res.beta
    Cb = res.cov(method)
    pred = X @ b
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', X, Cb, X), 0))
    tq = np.empty(len(idx))
    cache = {}
    for i, xr in enumerate(X):
        k = tuple(np.round(xr, 10))
        if k not in cache:
            cache[k] = _tq(alpha, _df_of(m, xr))
        tq[i] = cache[k]
    # the random effects of each row (BLUPs of seen levels; 0 for a new level)
    lv = _row_levels(m, idx)
    bl = res.blups()
    zu = np.zeros(len(idx))
    Zrow = []
    for (codes, vals), bb, c in zip(lv, bl, m.comps):
        ok = codes >= 0
        u = np.zeros((len(idx), c.c))
        u[ok] = bb['u'][codes[ok]]
        zu += np.nansum(u * np.where(np.isfinite(vals), vals, 0), axis=1)
        Zc = np.zeros((len(idx), c.q))
        for a in range(c.c):
            Zc[np.arange(len(idx))[ok], codes[ok] * c.c + a] = np.where(np.isfinite(vals[ok, a]), vals[ok, a], 0)
        Zrow.append(Zc)
    cond = pred + zu
    out = {'predicted': pred, 'se_pred': se, 'lower_mean': pred - tq * se, 'upper_mean': pred + tq * se, 'cond': cond}
    if m.comps and len(m.rep) * sum(c.q for c in m.comps) <= 2_000_000:
        Zr = np.hstack(Zrow)
        Phi, C21, C22, _off = _cond_parts(m, res.theta)
        # JMP: the fixed part with the report's covariance, the BLUPs' parts not Kackar-Harville corrected
        vc = np.einsum('ij,jk,ik->i', X, Cb, X) + 2 * np.einsum('ij,jk,ik->i', Zr, C21, X) + np.einsum('ij,jk,ik->i', Zr, C22, Zr)
        se_c = np.sqrt(np.maximum(vc, 0))
        # Satterthwaite's df of each row's conditional prediction: its variance differentiated numerically in theta
        f = res.free
        grads = []
        for k in f:
            h = 1e-5 * max(abs(res.theta[k]), 1e-2)
            tp, tm_ = res.theta.copy(), res.theta.copy()
            tp[k] += h
            tm_[k] -= h
            vs = []
            for th in (tp, tm_):
                try:
                    Ph2, C21b, C22b, _o = _cond_parts(m, th)
                except Exception:
                    Ph2 = None
                if Ph2 is None:
                    vs.append(None)
                    continue
                vs.append(np.einsum('ij,jk,ik->i', X, Ph2, X) + 2 * np.einsum('ij,jk,ik->i', Zr, C21b, X) + np.einsum('ij,jk,ik->i', Zr, C22b, Zr))
            grads.append((vs[0] - vs[1]) / (2 * h) if vs[0] is not None and vs[1] is not None else np.zeros(len(idx)))
        if f:
            G_ = np.array(grads)
            Wf = res.Wcov[np.ix_(f, f)]
            den = np.einsum('ki,kl,li->i', G_, Wf, G_)
            with np.errstate(divide='ignore', invalid='ignore'):
                dfc = np.where(den > 0, 2 * vc ** 2 / den, np.inf)
        else:
            dfc = np.full(len(idx), np.inf)
        tqc = np.array([_tq(alpha, v) for v in dfc])
        out.update({'se_cond': se_c, 'lower_cond': cond - tqc * se_c, 'upper_cond': cond + tqc * se_c})
        # the individual interval (G side only): the prediction's variance plus that of one response
        if m.rs.kind == 'residual':
            wv = _col_num(tid, m.spec['weight'], idx) if m.spec['weight'] else np.ones(len(idx))
            wv = np.where(np.isfinite(wv) & (wv > 0), wv, 1.0)
            s2 = m.scale / wv
            vy = s2 + sum(np.einsum('ij,jk,ik->i', Zc, np.kron(np.eye(c.nl), c.sigma(res.theta)), Zc) for Zc, c in zip(Zrow, m.comps))
            si = np.sqrt(np.maximum(se ** 2 + vy, 0))
            out.update({'lower_indiv': pred - tq * si, 'upper_indiv': pred + tq * si})
            sci = np.sqrt(np.maximum(se_c ** 2 + s2, 0))
            out.update({'lower_cond_indiv': cond - tqc * sci, 'upper_cond_indiv': cond + tqc * sci})
    if m.glmm:
        inv = _LINKS[m.glmm['link']][1]
        for k2 in ('predicted', 'lower_mean', 'upper_mean', 'cond', 'lower_cond', 'upper_cond'):
            if k2 in out:
                out[k2] = inv(out[k2])
        out['linpred'] = pred
        out['cond_linpred'] = cond
        out.pop('se_pred', None)
        out.pop('se_cond', None)
        if m.glmm['dist'] == 'binomial' and len(m.spec['y']) > 1:
            yv = _col_num(tid, m.spec['y'][0], idx) / _col_num(tid, m.spec['y'][1], idx)
        elif m.glmm['dist'] == 'binomial' and m.target is not None:
            raw = data.raw(tid, m.spec['y'][0], idx)
            yv = np.array([np.nan if v is None or (isinstance(v, float) and math.isnan(v)) else float(_lvl(v) == _lvl(m.target)) for v in raw])
        else:
            yv = _col_num(tid, m.spec['y'][0], idx)
    else:
        yv = _col_num(tid, m.spec['y'][0], idx)
    out['residual'] = yv - out['predicted']
    out['cond_residual'] = yv - out['cond']
    return idx, X, out


def _match_expr(m, inf, values, tid):
    """A random effect's BLUPs as formula text: a Match of its levels (nested
    Matches for a combination of columns), 0 for a level the fit did not see."""
    from .util import formula_num, formula_ref, formula_str
    cats = inf['cats']
    raw = inf['raw']

    def lit(nm, v):
        return formula_num(v) if data.meta(tid, nm).get('dataType') == 'numeric' else formula_str(v.item() if hasattr(v, 'item') else v)
    if len(cats) == 1:
        parts = [f'{lit(cats[0], r[0])}, {formula_num(v)}' for r, v in zip(raw, values)]
        return f'Match({formula_ref(cats[0])}, {", ".join(parts)}, 0)'
    # nested: the first column, then the others
    groups = {}
    for r, v in zip(raw, values):
        groups.setdefault(_lvl(r[0]), (r[0], []))[1].append((r[1:], v))

    def inner(k, items):
        if k == len(cats) - 1:
            return f'Match({formula_ref(cats[k])}, ' + ', '.join(f'{lit(cats[k], r[0])}, {formula_num(v)}' for r, v in items) + ', 0)'
        g2 = {}
        for r, v in items:
            g2.setdefault(_lvl(r[0]), (r[0], []))[1].append((r[1:], v))
        return f'Match({formula_ref(cats[k])}, ' + ', '.join(f'{lit(cats[k], key)}, {inner(k + 1, its)}' for key, its in g2.values()) + ', 0)'
    return f'Match({formula_ref(cats[0])}, ' + ', '.join(f'{lit(cats[0], key)}, {inner(1, its)}' for key, its in groups.values()) + ', 0)'


def _coef_expr(cname):
    from .util import formula_ref
    return ' * '.join(formula_ref(nm) for nm in cname.split('*'))


def _formulas(m, where, tid):
    """Prediction Formula (marginal), Conditional Prediction Formula (the
    BLUPs as Matches of the levels) and Save Simulation Formula (Random
    Normal draws: one per level of each random effect, Col Mean of Random
    Normal() within the level times the square root of its count, and one
    per row for the residual)."""
    d, res = m.d, m.res
    lin = models.formula_linear(d, m.di, res.beta, tid)
    cond = [lin]
    for bb, inf, c in zip(res.blups(), m.ginfo, m.comps):
        for a, cname in enumerate(c.coefs):
            mt = _match_expr(m, inf, bb['u'][:, a], tid)
            cond.append(mt if cname == 'Intercept' else f'{mt} * {_coef_expr(cname)}')
    y = m.spec['y'][0]
    inv = models.INVERSE_LINK.get(m.glmm['link']) if m.glmm else None
    F = [{'name': f'Pred Formula {y}', 'expr': models.formula_where(tid, where, inv.format(lin) if inv else lin)},
         {'name': f'Cond Pred Formula {y}', 'expr': models.formula_where(tid, where, inv.format(' + '.join(cond)) if inv else ' + '.join(cond))}]
    return F


def _simulation_formula(m, where, tid, beta=None, theta=None):
    """The model as a formula of random draws (Save Simulation Formula; a
    variance component below zero is drawn as zero, and the repeated
    structures other than Residual are left out: they need correlated
    draws the formula language does not make)."""
    from .util import formula_num, formula_ref
    d = m.d
    b = m.res.beta if beta is None else np.asarray(beta, dtype=float)
    th = m.res.theta if theta is None else np.asarray(theta, dtype=float)
    parts = [models.formula_linear(d, m.di, b, tid)]
    notes = []
    for inf, c in zip(m.ginfo, m.comps):
        cats = inf['cats']
        grp = ', '.join(formula_ref(cn) for cn in cats)
        z = f'Col Mean(Random Normal(), {grp}) * Sqrt(Col Number({formula_ref(cats[0])}, {grp}))'   # one N(0, 1) draw per level
        S = c.sigma(th)
        if c.c == 1:
            v = float(S[0, 0])
            if v <= 0:
                if v < 0:
                    notes.append(f'{inf["label"]}: the variance component is below zero, drawn as zero.')
                continue
            term = f'{formula_num(math.sqrt(v))} * {z}'
            parts.append(term if c.coefs[0] == 'Intercept' else f'{term} * {_coef_expr(c.coefs[0])}')
        else:
            w_, Q = np.linalg.eigh(S)
            Lc = np.linalg.cholesky((Q * np.maximum(w_, 0)) @ Q.T + 1e-12 * np.eye(c.c))
            for a in range(c.c):
                coef = ' + '.join((f'{formula_num(Lc[b_, a])}' if c.coefs[b_] == 'Intercept' else f'{formula_num(Lc[b_, a])} * {_coef_expr(c.coefs[b_])}')
                                  for b_ in range(a, c.c) if Lc[b_, a] != 0)
                if coef:
                    parts.append(f'({coef}) * {z.replace("Random Normal()", "Random Normal()", 1)}')
    if m.rs.kind == 'residual':
        s2 = float(th[m.rs.pidx[0]]) if m.rs.fixed_scale is None else m.rs.fixed_scale
        w = f' / Sqrt({formula_ref(m.spec["weight"])})' if m.spec['weight'] else ''
        parts.append(f'Random Normal(0, {formula_num(math.sqrt(s2))}{w})')
    else:
        notes.append(f'The {m.rdesc.get("label", "")} structure needs correlated draws: the residuals are drawn independently with its variance.')
        diag = float(np.mean([th[k] for k in m.rs.pidx if m.pars[k].kind == 'var'] or [1.0]))
        parts.append(f'Random Normal(0, {formula_num(math.sqrt(diag))})')
    return models.formula_where(tid, where, ' + '.join(parts)), notes


@api('mixed.save')
def save(table, y, effects=(), rows=None, where=None, weight=None, freq=None, no_intercept=False, alpha=0.05, center=True, mixed=None,
         table_name='data'):
    """Save Columns of a mixed model for every row whose predictors are
    present: {rows, columns: {name: values}, formulas: [{name, expr}]}."""
    m = _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed)
    idx, _X, cols = _save_values(m, where, alpha)
    sim, notes = _simulation_formula(m, where, table)
    return {'rows': [int(i) for i in idx], 'columns': cols, 'formulas': _formulas(m, where, table),
            'simulation': {'name': f'{m.spec["y"][0]} Simulation Formula', 'expr': sim, 'notes': notes}, 'n_fit': int(len(m.d.df))}


# ---------------------------------------------------------------------------
# Compare Structures, the variogram
# ---------------------------------------------------------------------------

_CAT_KINDS = ('residual', 'uneqvar', 'cs', 'csh', 'ar1', 'arh', 'toep', 'toeph', 'antevar', 'ante', 'un')


@api('mixed.structures')
def structures(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, center=True, mixed=None, kinds=None, table_name='data'):
    """Compare Structures: the model fitted with each repeated structure its
    Repeated and Subject columns allow, by AICc and BIC (the fixed and
    random effects as in the report)."""
    mx0 = dict(mixed or {})
    rep, subj = list(mx0.get('repeated') or []), list(mx0.get('subject') or [])
    spec0 = _mx_spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, center=center, mixed=mx0)
    base_m = _mixed_model(table, rows, spec0)
    d = base_m.d
    if not rep:
        return {'error': 'Compare Structures needs a Repeated column (and a Subject): choose them in the launch dialog\'s Repeated Structure'}
    cont = all(d.alias[c] not in d.categorical for c in rep)
    if kinds:
        todo = [k for k in kinds if k in _STRUCTS]
    elif len(rep) > 1:
        todo = ['residual'] + [f'sp:{t}' for t in _SP_LABEL] + [f'spn:{t}' for t in _SP_LABEL]
    else:
        todo = list(_CAT_KINDS) if subj else ['residual', 'uneqvar', 'ar1', 'arh']
        if cont:
            todo += ['sp:exp', 'spn:exp']
    out = []
    n_all = len(todo)
    for i, kind in enumerate(todo):
        k, _, t = kind.partition(':')
        opts = dict(mx0, structure=k, **({'sptype': t} if t else {}))
        print(f'smui:progress structures {i} {n_all}', flush=True)
        try:
            m = _mixed_model(table, rows, _mx_spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, center=center, mixed=opts))
            fs = _fit_stats(m)
            label = _R_LABEL[k] + (f' {_SP_LABEL[t]}' if t else '')
            out.append({'structure': label, 'kind': kind, 'params': fs['q'], 'm2rll': fs['m2rll'], 'm2ll': fs['m2ll'], 'aicc': fs['aicc'], 'bic': fs['bic'],
                        'converged': 'yes' if m.res.converged else 'no', 'current': kind == (mx0.get('structure') or 'residual') + (f':{mx0.get("sptype")}' if k in ('sp', 'spn') else '')})
        except ValueError as e:
            out.append({'structure': _R_LABEL.get(k, k), 'kind': kind, 'error': str(e)})
    print(f'smui:progress structures {n_all} {n_all}', flush=True)
    ok = [r for r in out if 'aicc' in r and np.isfinite(r['aicc'])]
    if ok:
        ba = min(r['aicc'] for r in ok)
        bb = min(r['bic'] for r in ok)
        for r in ok:
            r['best_aicc'] = r['aicc'] == ba
            r['best_bic'] = r['bic'] == bb
    out.sort(key=lambda r: r.get('aicc', float('inf')))
    code = '\n'.join(_mixed_fit_code(base_m, table, table_name, rows) + [
        '# each structure is fitted as above with its own R(th); smaller AICc and BIC are better:',
        '# -2 log L = n log(2 pi) + log|V| + r\'V^-1 r at the REML estimates; k = fixed + covariance parameters',
        'm2ll = n * np.log(2 * np.pi) + f["logdet"] + f["r"] @ f["Vi"] @ f["r"]; k = p + len(th)',
        'print("AICc", m2ll + 2 * k + 2 * k * (k + 1) / (n - k - 1), "BIC", m2ll + k * np.log(n))'])
    return {'rows': out, 'code': code}


def _vario_fns():
    return {'pow': lambda h, r: 1 - r ** h, 'exp': lambda h, r: 1 - np.exp(-h / r), 'gau': lambda h, r: 1 - np.exp(-(h / r) ** 2),
            'sph': lambda h, r: np.where(h < r, 1.5 * h / r - 0.5 * (h / r) ** 3, 1.0)}


@api('mixed.variogram')
def variogram(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, center=True, mixed=None, columns=None, curves=None,
              bins=10, table_name='data'):
    """The empirical semivariogram of the marginal residuals y - X b: the
    pairs' distances cut into equal intervals (10, JMP's), the semivariance
    sum (r_i - r_j)^2 / (2 N) of each; pairs within a subject when there is
    one. The fitted structure's curve from its estimates, and the curves
    asked for (AR(1), the spatial types, with a nugget) by weighted least
    squares on the empirical points."""
    m = _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed)
    d, rs = m.d, m.rs
    cols = list(columns or m.opts['repeated'])
    if not cols:
        return {'error': 'the variogram needs the coordinate columns (the Repeated columns, or those you choose)'}
    for c in cols:
        if c not in d.alias:
            return {'error': f'{c} is not in the model: choose it as a Repeated column'}
        if d.alias[c] in d.categorical:
            return {'error': f'{c} is categorical: the variogram takes continuous coordinates'}
    xy = np.column_stack([d.df[d.alias[c]].to_numpy(float) for c in cols])
    r = (d.df[d.y_alias].to_numpy(float) if not m.glmm else m.y[:len(d.df)]) - m.X0 @ m.res.beta
    sub = rs.sub[:len(d.df)] if rs.kind != 'residual' else np.zeros(len(d.df), dtype=np.int64)
    if m.spec['freq']:
        sub = _cat_codes(d, m.tid, m.opts['subject'])[0] if m.opts['subject'] else np.zeros(len(d.df), dtype=np.int64)
    iu = np.triu_indices(len(r), 1)
    same = sub[iu[0]] == sub[iu[1]]
    dist = np.sqrt(((xy[iu[0]] - xy[iu[1]]) ** 2).sum(-1))[same]
    sq = ((r[iu[0]] - r[iu[1]]) ** 2)[same]
    pos = dist > 0
    dist, sq = dist[pos], sq[pos]
    if not len(dist):
        return {'error': 'no pairs of rows at a distance above zero'}
    hi = float(dist.max())
    nb = int(max(1, min(bins, len(np.unique(dist)))))
    edges = np.linspace(0, hi, nb + 1)
    k = np.minimum(np.searchsorted(edges, dist, side='right') - 1, nb - 1)
    pts = []
    for b in range(nb):
        s_ = k == b
        if s_.any():
            pts.append({'lo': float(edges[b]), 'hi': float(edges[b + 1]), 'h': float(dist[s_].mean()), 'n': int(s_.sum()),
                        'gamma': float(sq[s_].sum() / (2 * s_.sum()))})
    hh = np.linspace(0, hi, 121)
    fns = _vario_fns()
    out_curves = []
    th = m.res.theta
    if rs.kind in ('sp', 'spn', 'ar1'):
        if rs.kind == 'ar1':
            rho, s2 = th[rs.pidx[0]], th[rs.pidx[1]]
            g = s2 * (1 - np.power(abs(rho), hh)) if rho > 0 else s2 * np.ones_like(hh)
            lab = 'AR(1) (the fit)'
        else:
            rho = th[rs.pidx[0]]
            s2 = th[rs.pidx[-1]]
            nug = th[rs.pidx[1]] * s2 if rs.kind == 'spn' else 0.0
            g = s2 * fns[rs.sptype](hh, rho) + nug
            lab = f'{_SP_LABEL[rs.sptype]}{" with nugget" if rs.kind == "spn" else ""} (the fit)'
        g = np.where(hh > 0, g, 0.0)
        out_curves.append({'label': lab, 'h': hh, 'gamma': g, 'fit': True})
    from scipy.optimize import least_squares
    H = np.array([p_['h'] for p_ in pts])
    G = np.array([p_['gamma'] for p_ in pts])
    Wt = np.sqrt(np.array([p_['n'] for p_ in pts], dtype=float))
    for cv in curves or []:
        kind, _, t = str(cv).partition(':')
        t = t or 'exp'
        if kind == 'ar1':
            t = 'pow'
        nug = kind == 'spn'
        f = fns.get(t)
        if f is None or len(H) < (3 if nug else 2):
            continue
        r0 = 0.5 if t == 'pow' else max(float(np.median(H)), 1e-6)
        x0 = [r0, float(G.max()), 0.1 * float(G.max())] if nug else [r0, float(G.max())]
        lb = [1e-6, 0.0, 0.0] if nug else [1e-6, 0.0]
        ub = [1 - 1e-9 if t == 'pow' else np.inf, np.inf, np.inf] if nug else [1 - 1e-9 if t == 'pow' else np.inf, np.inf]

        def resid(p_, f=f, nug=nug):
            return Wt * (p_[1] * f(H, p_[0]) + (p_[2] if nug else 0.0) - G)
        try:
            sol = least_squares(resid, x0, bounds=(lb, ub))
            p_ = sol.x
            g = p_[1] * f(hh, p_[0]) + (p_[2] if nug else 0.0)
            g = np.where(hh > 0, g, 0.0)
            out_curves.append({'label': ('AR(1)' if kind == 'ar1' else _SP_LABEL[t]) + (' with nugget' if nug else ''), 'h': hh, 'gamma': g, 'fit': False,
                               'params': {'range': float(p_[0]), 'sill': float(p_[1] + (p_[2] if nug else 0)), 'nugget': float(p_[2]) if nug else 0.0}})
        except Exception:
            continue
    code = _vario_code(m, table, table_name, rows, cols, nb)
    return {'points': pts, 'curves': out_curves, 'columns': cols, 'plot_code': code}


def _vario_code(m, table, table_name, rows, cols, nb):
    L = [ln for ln in _mixed_fit_code(m, table, table_name, rows, [PLT]) if not ln.startswith('print(')]
    subj = m.opts['subject'] if m.rs.kind != 'residual' else []
    L += ['r = y - X @ beta   # the marginal residuals',
          f'xy = d[{J(cols)}].to_numpy(float)',
          (f'sub_ = codes({J(subj)})' if subj else 'sub_ = np.zeros(len(r), dtype=int)'),
          'i, j = np.triu_indices(len(r), 1); keep = sub_[i] == sub_[j]',
          'dist = np.sqrt(((xy[i] - xy[j]) ** 2).sum(-1))[keep]; sq = ((r[i] - r[j]) ** 2)[keep]',
          'sq, dist = sq[dist > 0], dist[dist > 0]',
          f'edges = np.linspace(0, dist.max(), {nb} + 1); k = np.minimum(np.searchsorted(edges, dist, side="right") - 1, {nb - 1})',
          f'h = [dist[k == b].mean() for b in range({nb}) if (k == b).any()]',
          f'gamma = [sq[k == b].sum() / (2 * (k == b).sum()) for b in range({nb}) if (k == b).any()]',
          'fig, ax = plt.subplots(figsize=(5.2, 3.6))',
          'ax.plot(h, gamma, "o", color="#2f6690")']
    rs = m.rs
    if rs.kind in ('sp', 'spn'):
        f = {'pow': 'rho ** hh', 'exp': 'np.exp(-hh / rho)', 'gau': 'np.exp(-(hh / rho) ** 2)',
             'sph': 'np.where(hh < rho, 1 - 1.5 * hh / rho + 0.5 * (hh / rho) ** 3, 0.0)'}[rs.sptype]
        L += ['hh = np.linspace(0, dist.max(), 121); rho, s2 = th[nG], th[-1]',
              f'g = np.where(hh > 0, s2 * (1 - {f})' + (' + th[nG + 1] * s2' if rs.kind == 'spn' else '') + ', 0.0)' + ('   # the nugget: scaled by the residual' if rs.kind == 'spn' else ''),
              f'ax.plot(hh, g, color="{FIT}", linewidth=1.4)']
    elif rs.kind == 'ar1':
        L += ['hh = np.linspace(0, dist.max(), 121); rho, s2 = th[nG], th[-1]', f'ax.plot(hh, np.where(hh > 0, s2 * (1 - rho ** hh), 0.0), color="{FIT}", linewidth=1.4)']
    L += [f'ax.set_xlabel({J("Distance (" + ", ".join(cols) + ")")}); ax.set_ylabel("Semivariance"); ax.set_title({J(m.spec["y"][0] + " variogram")})', 'plt.show()']
    return '\n'.join(L)


# ---------------------------------------------------------------------------
# Simulate: responses from the model (the parameters as given), refitted
# ---------------------------------------------------------------------------

def _sqrt_parts(eng, theta):
    """The symmetric square roots that draw e ~ N(0, V(theta)): one per block
    of V's block-diagonal part B (the same, row for row, as the square root
    of the whole of B, in any order of the rows) and G's of the crossed
    random effects (their variances at or above zero)."""
    roots = []
    for g, rows in enumerate(eng.grows):
        R, _ = eng.rs.block(theta, eng.gr[g])
        V = R.copy()
        for k, D in eng.gd[g]:
            V += theta[k] * D
        w, Q = np.linalg.eigh(V)
        roots.append(np.einsum('bij,bj,bkj->bik', Q, np.sqrt(np.maximum(w, 0)), Q))
    Gh = None
    if eng.ql:
        G = eng.Gl(theta)
        w, Q = np.linalg.eigh(G)
        if w.min() < -1e-10 * max(1.0, abs(w).max()):
            raise ValueError('a crossed random effect has a variance below zero: it cannot be drawn apart (give it zero or more)')
        Gh = (Q * np.sqrt(np.maximum(w, 0))) @ Q.T
    return roots, Gh


def _draw(eng, parts, rng):
    """e = B^(1/2) z1 + Zl G^(1/2) z2, z1 over the rows (in their order) and
    z2 over the crossed effects' levels, from rng."""
    roots, Gh = parts
    z = rng.standard_normal(eng.n)
    e = np.zeros(eng.n)
    for Rh, rows in zip(roots, eng.grows):
        e[rows] = np.einsum('bij,bj->bi', Rh, z[rows])
    if Gh is not None:
        e += np.asarray(eng.Zl @ (Gh @ rng.standard_normal(Gh.shape[0]))).reshape(-1)
    return e


@api('mixed.simulate')
def simulate(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, center=True, mixed=None, beta=None, theta=None,
             n=25, seed=1, start=0, table_name='data'):
    """Simulate (one chunk of n samples): y* = X b + e, e ~ N(0, V(theta)),
    b and theta as given (the report's parameterization; the fit's by
    default), each sample refitted as the report fits it; the p-values of
    the Fixed Effects Tests and the parameter estimates, and whether each
    interval covers the true value. Sample k (start, start + 1, ...) draws
    from the seed (seed, k): the samples do not depend on how many are asked
    for at once. The draws: the symmetric square root of V's blocks times
    normal deviates (and of G for crossed effects), as the code shows."""
    m = _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed)
    if m.glmm:
        return {'error': 'Simulate is for the linear mixed models here (not the generalized ones)'}
    method = m.opts['ddfm']
    p = len(m.fe_names)
    T = m.T if m.T is not None else np.eye(p)
    bJ = np.asarray(beta, dtype=float) if beta is not None else None
    # the report's order and parameterization back to the fit's
    if bJ is not None:
        full = np.zeros(p)
        full[m.order] = bJ
        b_true = np.linalg.solve(T, full)
    else:
        b_true = m.res.beta.copy()
    th_true = np.asarray(theta, dtype=float) if theta is not None else m.res.theta.copy()
    if len(th_true) != len(m.pars) or len(b_true) != p:
        return {'error': 'give a value for every fixed effect and every covariance parameter'}
    eng0 = m.eng
    if eng0.evaluate(th_true, 0) is None:
        return {'error': 'these covariance parameters do not give a positive definite covariance of the rows'}
    try:
        parts = _sqrt_parts(eng0, th_true)
    except ValueError as e:
        return {'error': str(e)}
    mean = m.X @ b_true
    bJtrue = (T @ b_true)[m.order]
    tests = {e['label']: [] for e in m.d.effects if len(_effect_L(m, e))}
    terms = {_tlabel(m.d, m.fe_names[j]): [] for j in m.order}
    cover = {k: [] for k in terms}
    est_ = {k: [] for k in terms}
    cp = {pp.label: [] for pp in m.pars}
    cp_cover = {pp.label: [] for pp in m.pars}
    failed = 0
    import copy
    for i in range(int(n)):
        rng = np.random.default_rng([int(seed), int(start) + i])      # each sample its own seed
        ys_ = mean + _draw(eng0, parts, rng)
        eng = copy.copy(eng0)
        eng.y = ys_
        try:
            res = _fit(eng, m.pars, th_true)
        except ValueError:
            failed += 1
            continue
        m2 = copy.copy(m)
        m2.res, m2.eng, m2.y = res, eng, ys_
        for r in _test_rows(m2, method):
            tests[r['source']].append(r['p'])
        for (lab, bt), r in zip(zip(terms, bJtrue), _fixed_rows(m2, alpha, method)):
            terms[lab].append(r['p'])
            est_[lab].append(r['estimate'])
            cover[lab].append(1.0 if r['lower'] <= bt <= r['upper'] else 0.0)
        z = float(stats.norm.ppf(1 - alpha / 2))
        for k, pp in enumerate(m.pars):
            v = float(res.theta[k])
            cp[pp.label].append(v)
            se = _se_of(res, k)
            if se:
                lo, hi = (_satt_ci(v, se, alpha) if pp.kind == 'var' and (pp.side == 'R' or pp.tr == 'nonneg') else (v - z * se, v + z * se))
                cp_cover[pp.label].append(1.0 if lo is not None and lo <= th_true[k] <= hi else 0.0)
    return {'tests': tests, 'terms': terms, 'cover': cover, 'estimates': est_, 'covparms': cp, 'cp_cover': cp_cover, 'failed': failed, 'n': int(n),
            'true': {'beta': bJtrue, 'theta': th_true, 'terms': list(terms), 'params': [pp.label for pp in m.pars]}}


def _wilson(k, n, alpha=0.05):
    if n == 0:
        return None, None
    z = float(stats.norm.ppf(1 - alpha / 2))
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


@api('mixed.power')
def power(results=None, levels=(0.01, 0.05, 0.10, 0.20), alpha=0.05, conf=0.95):
    """The Simulate report from the samples' results (mixed.simulate's, joined):
    the rejection rate of each test at each alpha with its Wilson interval,
    and the intervals' coverage."""
    R = results or {}
    rows = []
    for kind, block in (('Fixed Effects Tests', R.get('tests') or {}), ('Fixed Effects Parameter Estimates', R.get('terms') or {})):
        for name, ps in block.items():
            ps = np.array([np.nan if v is None else v for v in ps], dtype=float)
            ps = ps[np.isfinite(ps)]
            for a in levels:
                k = int(np.sum(ps < a))
                lo, hi = _wilson(k, len(ps), 1 - conf)
                rows.append({'report': kind, 'term': name, 'alpha': a, 'rate': k / len(ps) if len(ps) else None, 'lower': lo, 'upper': hi, 'n': len(ps)})
    cov_rows = []
    truth = R.get('true') or {}
    for name, hits in (R.get('cover') or {}).items():
        h = np.array(hits, dtype=float)
        k = int(h.sum())
        lo, hi = _wilson(k, len(h), 1 - conf)
        ests = np.array((R.get('estimates') or {}).get(name) or [], dtype=float)
        tv = truth.get('beta')[truth.get('terms').index(name)] if truth.get('terms') and name in truth.get('terms') else None
        cov_rows.append({'param': name, 'kind': 'fixed', 'true': tv, 'mean': float(ests.mean()) if len(ests) else None,
                         'sd': float(ests.std(ddof=1)) if len(ests) > 1 else None, 'coverage': k / len(h) if len(h) else None, 'lower': lo, 'upper': hi,
                         'n': len(h)})
    for name, hits in (R.get('cp_cover') or {}).items():
        h = np.array(hits, dtype=float)
        k = int(h.sum())
        lo, hi = _wilson(k, len(h), 1 - conf)
        ests = np.array((R.get('covparms') or {}).get(name) or [], dtype=float)
        params = truth.get('params') or []
        tv = truth.get('theta')[params.index(name)] if name in params else None
        cov_rows.append({'param': name, 'kind': 'covariance', 'true': tv, 'mean': float(ests.mean()) if len(ests) else None,
                         'sd': float(ests.std(ddof=1)) if len(ests) > 1 else None, 'coverage': k / len(h) if len(h) else None, 'lower': lo, 'upper': hi,
                         'n': len(h)})
    return {'power': rows, 'coverage': cov_rows, 'levels': list(levels)}


def _simulate_code(m, table, table_name, rows, alpha, beta, theta, n, seed):
    """Simulate as code: the same draws (each sample's seed, the square
    roots of V's blocks and of G's crossed part), each sample refitted by the
    code's REML and Kenward-Roger (or Satterthwaite) tests."""
    L = [ln for ln in _mixed_fit_code(m, table, table_name, rows, full=True, alpha=alpha, tables=False)]
    eng = m.eng
    p = len(m.fe_names)
    T = m.T if m.T is not None else np.eye(p)
    Tm = T[m.order]
    low = set(eng.low)
    L.append(f'Tm = np.array({J(np.round(Tm, 15).tolist())})   # the report\'s parameters from the fit\'s')
    L.append(f'b_true = np.linalg.solve(Tm, np.array({J([float(v) for v in beta])}))   # the true fixed effects (the report\'s coding) in the fit\'s')
    L.append(f'theta_true = np.array({J([float(v) for v in theta])})   # the true covariance parameters, in the order of names')
    lowk = [k for i in sorted(low) for k in m.comps[i].pidx]
    L.append(f'low = {J(lowk)}   # the crossed random effects\' parameters, drawn apart from the rest of V (as the report does)')
    L += ['th_B = theta_true.copy(); th_B[low] = 0   # V without the crossed random effects: block diagonal',
          'w_, Q_ = np.linalg.eigh(V(th_B)); Bh = (Q_ * np.sqrt(np.maximum(w_, 0))) @ Q_.T   # its symmetric square root']
    if low:
        zi = [m.comps.index(m.comps[i]) for i in sorted(low)]
        L += [f'Zl = np.hstack([np.hstack(Zs[i]) for i in {J(zi)}])   # the crossed effects\' levels (a coefficient\'s columns together)']
        L += ['G = np.zeros((Zl.shape[1], Zl.shape[1])); o = 0']
        for i in sorted(low):
            c = m.comps[i]
            if c.c == 1:
                L.append(f'G[o:o + {c.q}, o:o + {c.q}] = theta_true[{c.pidx[0]}] * np.eye({c.q}); o += {c.q}')
        L += ['w2, Q2 = np.linalg.eigh(G); Gh = (Q2 * np.sqrt(np.maximum(w2, 0))) @ Q2.T']
    tests = []
    for e in m.d.effects:
        cols = [m.fe_names.index(t) for t in e.get('terms', []) if t in m.fe_names]
        if cols:
            tests.append((e['label'], cols))
    L.append(f'effects = {J([[lab, cols] for lab, cols in tests])}')
    L += ['pvals = {lab: [] for lab, _ in effects}',
          'y0 = y',
          f'for s in range({int(n)}):',
          f'    rng = np.random.default_rng([{int(seed)}, s])   # each sample its own seed',
          '    e = Bh @ rng.standard_normal(n)' + (' + Zl @ (Gh @ rng.standard_normal(Gh.shape[0]))' if low else ''),
          '    y = X @ b_true + e',
          '    th_s, f_s = fit_reml(theta_true.copy())',
          '    PhiA_s, ddf_s, _W, _free, C_s = inference(th_s, f_s)',
          '    for lab, cols in effects:',
          '        Lm = np.eye(p)[cols]; q = np.linalg.matrix_rank(Lm @ C_s @ Lm.T); lam, dfd = ddf_s(Lm)',
          '        F = lam * (Lm @ f_s["b"]) @ np.linalg.pinv(Lm @ PhiA_s @ Lm.T) @ (Lm @ f_s["b"]) / q',
          '        pvals[lab].append(stats.f.sf(F, q, dfd))',
          'y = y0',
          'for lab, ps in pvals.items():   # the rejection rates',
          '    print(lab, [np.mean(np.array(ps) < a) for a in (0.01, 0.05, 0.1, 0.2)])']
    return '\n'.join(L)


@api('mixed.simulate_code')
def simulate_code(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, center=True, mixed=None, beta=None, theta=None,
                  n=25, seed=1, table_name='data'):
    m = _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed)
    return {'code': _simulate_code(m, table, table_name, rows, alpha, beta if beta is not None else [r['estimate'] for r in _fixed_rows(m, alpha, m.opts['ddfm'])],
                                   theta if theta is not None else list(m.res.theta), n, seed)}


# ---------------------------------------------------------------------------
# the likelihood ratio, the Skeleton ANOVA, profile-likelihood intervals
# ---------------------------------------------------------------------------

@api('mixed.lrt')
def lrt(chisq=0.0, df=1, mixture=False):
    """Compare Models: the likelihood ratio's p-value on df degrees of freedom,
    and for a variance component tested at zero the 50:50 mixture of chi2(0)
    and chi2(1) (Self and Liang 1987): half the chi2(1) p-value."""
    x = max(float(chisq), 0.0)
    p = float(stats.chi2.sf(x, int(df)))
    out = {'p': p, 'code': '\n'.join(['from scipy import stats', f'x, df = {x!r}, {int(df)}   # the difference of the -2 log likelihoods, of the parameters',
                                      'print(stats.chi2.sf(x, df))' + ('   # and the 50:50 mixture of chi2(0) and chi2(1):' if mixture else ''),
                                      *(['print(0.5 * stats.chi2.sf(x, 1))'] if mixture else [])])}
    if mixture:
        out['p_mix'] = 0.5 * float(stats.chi2.sf(x, 1)) if x > 0 else 1.0
    return out


def _rank(M):
    if M.shape[1] == 0:
        return 0
    s = np.linalg.svd(M, compute_uv=False)
    return int(np.sum(s > s.max() * max(M.shape) * np.finfo(float).eps * 10)) if len(s) else 0


@api('mixed.skeleton')
def skeleton(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, center=True, mixed=None, table_name='data'):
    """The Skeleton ANOVA: the degrees of freedom of each source, the rank it
    adds to the design in the model's order (the intercept, the fixed
    effects, the random effects), and the residual's; warnings for a random
    effect that adds nothing (confounded with a fixed effect or an earlier
    random one) or that leaves the residual nothing (confounded with it)."""
    m = _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed)
    X = m.X0
    n = len(X)
    names = m.fe_names
    rows_out, warn = [], []
    cur = np.zeros((n, 0))
    if 'Intercept' in names:
        cur = X[:, [names.index('Intercept')]]
    for e in m.d.effects:
        cols = [names.index(t) for t in e.get('terms', []) if t in names]
        if not cols:
            continue
        new = np.hstack([cur, X[:, cols]])
        rows_out.append({'source': e['label'], 'kind': 'Fixed', 'df': _rank(new) - _rank(cur)})
        cur = new
    for c, inf in zip(m.comps, m.ginfo):
        Z = np.zeros((len(m.d.df), c.q))
        ok = c.codes0 >= 0
        for a in range(c.c):
            Z[np.arange(len(m.d.df))[ok], c.codes0[ok] * c.c + a] = c.vals0[ok, a]
        new = np.hstack([cur, Z])
        dfv = _rank(new) - _rank(cur)
        rows_out.append({'source': inf['label'], 'kind': 'Random', 'df': dfv})
        if dfv == 0:
            warn.append(f'{inf["label"]} adds no degrees of freedom: it is confounded with the effects before it (its levels are those of a fixed effect, or of another random effect), so its variance cannot be told apart.')
        elif _rank(new) == n:
            warn.append(f'{inf["label"]} leaves the residual no degrees of freedom: it is confounded with the residual (each of its levels is a single row, or the rows that share a level share every other effect too); take it out of the model.')
        cur = new
    res_df = n - _rank(cur)
    rows_out.append({'source': 'Residual', 'kind': 'Residual', 'df': res_df})
    rows_out.append({'source': 'Total', 'kind': '', 'df': n - (1 if 'Intercept' in names else 0)})
    code = '\n'.join(_mixed_fit_code(m, table, table_name, rows)[:-1] + [
        'rank = lambda M: np.linalg.matrix_rank(M) if M.shape[1] else 0',
        f'cur = X[:, [{names.index("Intercept")}]]' if 'Intercept' in names else 'cur = np.zeros((n, 0))',
        f'for lab, cols in {J([[e["label"], [names.index(t) for t in e.get("terms", []) if t in names]] for e in m.d.effects])}:   # the fixed effects, in order',
        '    new = np.hstack([cur, X[:, cols]]); print(lab, rank(new) - rank(cur)); cur = new',
        f'for lab, Zc in zip({J([inf["label"] for inf in m.ginfo])}, Zs):   # then the random effects',
        '    new = np.hstack([cur] + Zc); print(lab, rank(new) - rank(cur)); cur = new',
        'print("Residual", n - rank(cur))'])
    return {'rows': rows_out, 'warnings': warn, 'code': code}


@api('mixed.profile_ci')
def profile_ci(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, center=True, mixed=None, table_name='data'):
    """Profile-likelihood intervals of the covariance parameters: where
    -2 log L_R, maximized over the others with the parameter fixed, rises
    by the chi2(1) quantile above its minimum (a limit is missing where V
    stops being positive definite, or a variance reaches zero, first)."""
    m = _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed)
    if m.glmm:
        return {'error': 'profile-likelihood intervals are for the linear mixed models here'}
    res, eng, pars = m.res, m.eng, m.pars
    target = -2 * res.ll + float(stats.chi2.ppf(1 - alpha, 1))
    groups = [(c.c, c.pidx) for c in eng.comps if c.c > 1]
    if eng.rs.kind == 'un':
        groups.append((eng.rs.J, eng.rs.pidx))
    tr = _Trans(pars, groups)
    z = float(stats.norm.ppf(1 - alpha / 2))
    out = []
    total = len(pars)
    for k, pp in enumerate(pars):
        print(f'smui:progress profile {k} {total}', flush=True)
        est = float(res.theta[k])
        se = _se_of(res, k)
        row = {'param': pp.label, 'estimate': est, 'lower': None, 'upper': None, 'wald_lower': est - z * se if se else None, 'wald_upper': est + z * se if se else None}
        if k in res.boundary or not se or k in tr.in_group:
            out.append(row)
            continue
        lo_ok = pp.tr in ('free', 'nonneg') or pp.kind in ('cov',)
        warm = [res.theta.copy()]

        def prof(t):
            th0 = warm[0].copy()
            th0[k] = t
            if pp.tr == 'log' and t <= 0:
                return None
            if pp.tr == 'nonneg' and t < 0:
                return None
            if pp.tr in ('tanh',) and abs(t) >= 1:
                return None
            if pp.tr == 'logit' and not (0 < t < 1):
                return None
            try:
                th, E, _c, _i, _h = _optimize(eng, th0, tr, fixed=(k,), maxit=100)
            except Exception:
                return None
            if E is None:
                return None
            warm[0] = th
            return -2 * E['ll']

        for side in (-1, 1):
            step = se
            a = est
            b = None
            for _ in range(80):
                t = a + side * step
                ft = prof(t)
                if ft is None:
                    # past the positive definite region (or a variance's zero): a shorter step from the last good point
                    step *= 0.5
                    if step < 1e-8 * max(1.0, abs(est)):
                        break
                    continue
                if ft >= target:
                    b = (t, ft)
                    break
                a = t
                step *= 1.6
            warm[0] = res.theta.copy()
            if b is None:
                if side < 0 and not lo_ok and pp.tr == 'log':
                    row['lower'] = None
                continue
            lo_t, hi_t = (a, b[0]) if side > 0 else (b[0], a)
            for _ in range(60):
                mid = 0.5 * (lo_t + hi_t)
                fm = prof(mid)
                if fm is None:
                    break
                if (fm >= target) == (side > 0):
                    hi_t = mid
                else:
                    lo_t = mid
                if abs(hi_t - lo_t) < 1e-7 * max(1.0, abs(est)):
                    break
            row['upper' if side > 0 else 'lower'] = 0.5 * (lo_t + hi_t)
            warm[0] = res.theta.copy()
        out.append(row)
    print(f'smui:progress profile {total} {total}', flush=True)
    code = '\n'.join([ln for ln in _mixed_fit_code(m, table, table_name, rows) if not ln.startswith('print(')] + [
        f'target = f["m2"] + stats.chi2.ppf(1 - {alpha!r}, 1)   # the profile rises by the chi-square quantile',
        'from scipy.optimize import brentq, minimize',
        'def profile(k, t):   # -2 log L_R with th[k] = t, the other parameters at their best',
        '    free_ = [j for j in range(len(th)) if j != k]',
        '    def obj(v):',
        '        t_ = th.copy(); t_[free_] = v; t_[k] = t; r = reml(t_)',
        '        return r["m2"] if r is not None else 1e300',
        '    return minimize(obj, th[free_], method="Nelder-Mead", options={"xatol": 1e-9, "fatol": 1e-10, "maxiter": 20000}).fun if free_ else obj([])',
        'for k, nm in enumerate(names):',
        '    se = np.sqrt(W[k, k]) if "W" in dir() else None',
        '    print(nm, th[k])'])
    return {'rows': out, 'code': code}


# ---------------------------------------------------------------------------
# the Conditional Profiler: the random effects' levels as factors
# ---------------------------------------------------------------------------

def _cond_build(table, rows=None, alpha=0.05, ys=None, **model):
    spec = _mx_spec(**{k: v for k, v in model.items() if k in ('y', 'effects', 'weight', 'freq', 'no_intercept', 'center', 'mixed')})
    m = _mixed_model(table, rows, spec)
    d = m.d
    facs = _factors(d)
    have = {f['name'] for f in facs}
    extra = []
    for inf, c in zip(m.ginfo, m.comps):
        for nm in inf['cats']:
            if nm not in have:
                a = d.alias[nm]
                extra.append({'name': nm, 'type': 'categorical', 'levels': list(d.levels[a]), 'labels': [data.level_label(table, nm, v, _lvl(v)) for v in d.levels[a]]})
                have.add(nm)
        for cname in c.coefs:
            if cname != 'Intercept':
                for nm in cname.split('*'):
                    if nm not in have:
                        x = d.df[d.alias[nm]].to_numpy(float)
                        extra.append({'name': nm, 'type': 'continuous', 'min': float(x.min()), 'max': float(x.max()), 'mean': float(x.mean())})
                        have.add(nm)
    allf = facs + extra
    bl = m.res.blups()
    name = m.spec['y'][0]
    inv = _LINKS[m.glmm['link']][1] if m.glmm else None

    def run(settings):
        L = m.coder.rows([_setting(d, s) for s in settings])
        pred = L @ m.res.beta
        for b, inf, c in zip(bl, m.ginfo, m.comps):
            pos = {tuple(_lvl(v) for v in r): i for i, r in enumerate(inf['raw'])}
            for i, s in enumerate(settings):
                key = tuple(_lvl(s.get(nm)) for nm in inf['cats'])
                li = pos.get(key)
                if li is None:
                    continue
                for a, cname in enumerate(c.coefs):
                    v = 1.0
                    if cname != 'Intercept':
                        for nm in cname.split('*'):
                            xv = s.get(nm)
                            v *= float(xv) if xv is not None else float(d.df[d.alias[nm]].mean())
                    pred[i] += b['u'][li, a] * v
        return [{'name': f'{name} (conditional)', 'pred': inv(pred) if inv else pred, 'lower': None, 'upper': None, 'bounded': bool(m.glmm and m.glmm['dist'] == 'binomial')}]
    observed = {}
    for f in allf:
        a = d.alias[f['name']]
        observed[f['name']] = [None if v is None or (isinstance(v, float) and math.isnan(v)) else (v.item() if hasattr(v, 'item') else v) for v in d.df[a].astype(object)]
    return profile_mod.Predictor(allf, run, observed)


profile_mod.expose('mixedcond', _cond_build, alpha=True)


# ---------------------------------------------------------------------------
# Indicator Parameterization Estimates
# ---------------------------------------------------------------------------

_SUM = re.compile(r'C\((v\d+), Sum\)')


def _indicator_rhs(d):
    """The fixed effects with every categorical factor coded 0/1, its last
    level the reference (SAS GLM's parameterization, as JMP's Indicator
    Parameterization Estimates), over _indicator_frame(d); continuous columns
    as in the report."""
    return _SUM.sub(lambda mo: f'C({mo.group(1)}, Treatment)', d.rhs)


def _indicator_frame(d):
    """The design's frame with each categorical column's last level first,
    so that Treatment coding makes it the reference: no level's text goes
    into the formula (a level from the table may hold brackets and quotes,
    which the names of patsy's columns would then carry)."""
    df = d.df.copy()
    for a in d.categorical:
        if a in df and isinstance(df[a].dtype, pd.CategoricalDtype) and len(df[a].cat.categories) > 1:
            cats = list(df[a].cat.categories)
            df[a] = df[a].cat.reorder_categories(cats[-1:] + cats[:-1])
    return df


@api('mixed.indicator')
def indicator(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, center=True, mixed=None, table_name='data'):
    """The fixed effects' estimates in the indicator coding: the same fit, the
    estimates b_ind = M b with X_ind M = X (both designs span the same
    columns), their covariance M C M' (Kenward-Roger's or the model-based
    one) and each estimate's own df."""
    import patsy
    m = _payload_model(table, rows, y, effects, weight, freq, no_intercept, center, mixed)
    d = m.d
    rhs = _indicator_rhs(d)
    Xi = patsy.dmatrix(rhs, _indicator_frame(d), return_type='dataframe')
    names = list(Xi.columns)
    Xi = np.asarray(Xi, dtype=float)
    M = np.linalg.lstsq(Xi, m.X0, rcond=None)[0]
    if np.max(np.abs(Xi @ M - m.X0)) > 1e-8 * max(1.0, float(np.max(np.abs(m.X0)))):
        return {'error': 'the indicator coding spans other columns than the report\'s design here (an interaction without its main effects)'}
    method = m.opts['ddfm']
    C = m.res.cov(method)
    b = M @ m.res.beta
    V = M @ C @ M.T
    out = []
    for j, nm in enumerate(names):
        se = float(math.sqrt(max(V[j, j], 0.0)))
        df = _df_of(m, M[j])
        t = b[j] / se if se > 0 else float('nan')
        tc = _tq(alpha, df)
        out.append({'term': d.label(nm), 'estimate': float(b[j]), 'se': se, 'dfden': df, 't': t,
                    'p': float(2 * stats.t.sf(abs(t), df)) if np.isfinite(df) and df > 0 else float(2 * stats.norm.sf(abs(t))),
                    'lower': float(b[j] - tc * se), 'upper': float(b[j] + tc * se)})
    code = [ln for ln in _mixed_fit_code(m, table, table_name, rows, full=True, alpha=alpha, tables=False)] + [
        f'Xi = np.asarray(patsy.dmatrix({J(_indicator_code_rhs(d))}, d), dtype=float)   # every level 0/1 but the last',
        'M = np.linalg.lstsq(Xi, X, rcond=None)[0]   # Xi M = X: the indicator parameters from the report\'s',
        'bi, Ci = M @ beta, M @ PhiA @ M.T',
        'for j in range(len(bi)):',
        '    se = np.sqrt(Ci[j, j]); dfd = ddf(M[j][None, :])[1]',
        '    print(j, bi[j], se, dfd, bi[j] / se, 2 * stats.t.sf(abs(bi[j] / se), dfd))']
    return {'rows': out, 'm2rll': -2 * m.res.ll, 'code': '\n'.join(code)}


def _indicator_code_rhs(d):
    """_indicator_rhs over the real column names (for the code)."""
    return _mx_formula(d, lhs=False, indicator=True)
