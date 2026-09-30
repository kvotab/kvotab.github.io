#!/usr/bin/env python3
"""Fit Model's mixed models (resources/py/smui/mixed.py), checked against
closed forms and independent computations:

  - balanced designs, where REML with unbounded variance components is the
    ANOVA (expected mean squares) estimator, negative estimates included
    (quality._ems solves the expected mean squares before it clips them),
    and the textbook standard error of the one-way estimator;
  - the exact F tests of a balanced split plot (the whole-plot factor on
    the whole-plot error), which Kenward and Roger's approximation gives
    exactly (F and denominator df);
  - a dense reference written here from the published formulas: the REML
    log-likelihood, the observed information by numerical differences of
    the log-likelihood, Kenward and Roger's (1997) adjusted covariance and
    denominator df (first order), Satterthwaite's df, the BLUPs and their
    prediction errors, for unbalanced data, crossed and nested effects,
    random coefficients and every repeated structure;
  - statsmodels' MixedLM where its model is the same and its estimates are
    inside the bounds;
  - the Python code under the reports, run on the table as a CSV.
"""
import contextlib
import io
import math
import os
import sys
import tempfile

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from backend import FAILED, Checks, call, table
from smui import mixed as mx, quality

check = Checks()
for mod in ('fit_model', 'mixed'):
    if mod in FAILED:
        print(f'{mod} failed to import:', FAILED[mod])
        sys.exit(1)

tmp = tempfile.mkdtemp(prefix='smui-mixed-')


def run_code(code, frame, name):
    """Write frame as the page exports it (File > Export CSV) and run code there."""
    frame.to_csv(os.path.join(tmp, f'{name}.csv'), index=False)
    ns = {}
    here = os.getcwd()
    os.chdir(tmp)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(code, ns)
        return ns, None
    except Exception as e:  # reported as a failed check
        import traceback
        return ns, f'{type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}'
    finally:
        os.chdir(here)


def by(rows, key):
    return {r[key]: r for r in rows}


def E(*effects):
    out = []
    for e in effects:
        out.append(e if isinstance(e, dict) else {'names': list(e) if isinstance(e, (list, tuple)) else [e]})
    return out


# ---- a dense reference: REML, the observed information, Kenward-Roger, Satterthwaite -------------------------

class Dense:
    """y = X b + e, Var(y) = V(theta): REML and its inference from the
    formulas, with numerical derivatives of V and of the log-likelihood."""

    def __init__(self, X, y, Vfun, theta):
        self.X, self.y, self.Vfun = np.asarray(X, float), np.asarray(y, float), Vfun
        self.theta = np.asarray(theta, float)
        self.n, self.p = self.X.shape

    def m2ll(self, th):
        V = self.Vfun(th)
        Vi = np.linalg.inv(V)
        A = self.X.T @ Vi @ self.X
        b = np.linalg.solve(A, self.X.T @ Vi @ self.y)
        r = self.y - self.X @ b
        return (self.n - self.p) * math.log(2 * math.pi) + np.linalg.slogdet(V)[1] + np.linalg.slogdet(A)[1] + r @ Vi @ r

    def dV(self, th, h=1e-6):
        out = []
        for k in range(len(th)):
            a, b = th.copy(), th.copy()
            hk = h * max(1.0, abs(th[k]))
            a[k] += hk
            b[k] -= hk
            out.append((self.Vfun(a) - self.Vfun(b)) / (2 * hk))
        return out

    def obs(self, th, h=1e-4):
        """The observed information: half the Hessian of -2 log L, by central differences."""
        r = len(th)
        H = np.zeros((r, r))
        f0 = self.m2ll(th)
        hs = [h * max(abs(t), 0.05) for t in th]
        for i in range(r):
            for j in range(i, r):
                if i == j:
                    a, b = th.copy(), th.copy()
                    a[i] += hs[i]
                    b[i] -= hs[i]
                    H[i, i] = (self.m2ll(a) - 2 * f0 + self.m2ll(b)) / hs[i] ** 2
                else:
                    pp, pm, mp, mm_ = th.copy(), th.copy(), th.copy(), th.copy()
                    pp[i] += hs[i]; pp[j] += hs[j]
                    pm[i] += hs[i]; pm[j] -= hs[j]
                    mp[i] -= hs[i]; mp[j] += hs[j]
                    mm_[i] -= hs[i]; mm_[j] -= hs[j]
                    H[i, j] = H[j, i] = (self.m2ll(pp) - self.m2ll(pm) - self.m2ll(mp) + self.m2ll(mm_)) / (4 * hs[i] * hs[j])
        return H / 2

    def fit_parts(self, free=None):
        th = self.theta
        V = self.Vfun(th)
        Vi = np.linalg.inv(V)
        X = self.X
        Phi = np.linalg.inv(X.T @ Vi @ X)
        b = Phi @ X.T @ Vi @ self.y
        D = self.dV(th)
        free = list(range(len(th))) if free is None else free
        W = np.zeros((len(th), len(th)))
        Hf = self.obs(th)[np.ix_(free, free)]
        W[np.ix_(free, free)] = np.linalg.inv(Hf)
        P = [-(X.T @ Vi @ Dk @ Vi @ X) for Dk in D]
        Lam = np.zeros_like(Phi)
        for a in free:
            for c in free:
                Q = X.T @ Vi @ D[a] @ Vi @ D[c] @ Vi @ X
                Lam += W[a, c] * (Q - P[a] @ Phi @ P[c])
        PhiA = Phi + 2 * Phi @ Lam @ Phi
        return {'b': b, 'Phi': Phi, 'PhiA': PhiA, 'P': P, 'W': W, 'free': free, 'Vi': Vi, 'D': D}

    @staticmethod
    def kr(fp, L):
        """Kenward and Roger (1997): the F scale and the denominator df of L b = 0."""
        L = np.atleast_2d(L)
        Phi, W, P, f = fp['Phi'], fp['W'], fp['P'], fp['free']
        l = np.linalg.matrix_rank(L)
        Th = L.T @ np.linalg.inv(L @ Phi @ L.T) @ L
        M = {a: Th @ Phi @ P[a] @ Phi for a in f}
        A1 = sum(W[a, c] * np.trace(M[a]) * np.trace(M[c]) for a in f for c in f)
        A2 = sum(W[a, c] * np.trace(M[a] @ M[c]) for a in f for c in f)
        B = (A1 + 6 * A2) / (2 * l)
        g = ((l + 1) * A1 - (l + 4) * A2) / ((l + 2) * A2)
        c1, c2, c3 = g / (3 * l + 2 * (1 - g)), (l - g) / (3 * l + 2 * (1 - g)), (l + 2 - g) / (3 * l + 2 * (1 - g))
        Es = 1 / (1 - A2 / l)
        Vs = 2 / l * (1 + c1 * B) / ((1 - c2 * B) ** 2 * (1 - c3 * B))
        rho = Vs / (2 * Es ** 2)
        m = 4 + (l + 2) / (l * rho - 1)
        lam = m / (Es * (m - 2))
        b = fp['b']
        F = float((L @ b) @ np.linalg.inv(L @ fp['PhiA'] @ L.T) @ (L @ b)) / l
        return lam * F, m

    @staticmethod
    def satt(fp, L):
        """Satterthwaite's df of one contrast L b."""
        Phi, W, P, f = fp['Phi'], fp['W'], fp['P'], fp['free']
        L = np.asarray(L, float).ravel()
        g = np.array([L @ (-(Phi @ P[a] @ Phi)) @ L for a in f])
        return 2 * (L @ Phi @ L) ** 2 / (g @ W[np.ix_(f, f)] @ g)


def indicators(codes):
    codes = np.asarray(codes)
    u, inv = np.unique(codes, return_inverse=True)
    Z = np.zeros((len(codes), len(u)))
    Z[np.arange(len(codes)), inv] = 1
    return Z


rng = np.random.default_rng(20260929)

# ---- 1. one-way random effects: REML = ANOVA, negative estimates included --------------------------------------
a, n0 = 8, 5
g1 = np.repeat(np.arange(a), n0)
found = None
for trial in range(200):          # a sample whose ANOVA estimate of the group variance is negative
    y1 = 3 + rng.normal(0, 0.25, a)[g1] + rng.normal(0, 1, a * n0)
    means = np.array([y1[g1 == i].mean() for i in range(a)])
    msb = n0 * np.sum((means - y1.mean()) ** 2) / (a - 1)
    mse = np.sum((y1 - means[g1]) ** 2) / (a * (n0 - 1))
    if msb < mse:
        found = y1
        break
check('a one-way sample with MSB < MSE', found is not None)
t1 = table({'g': [f'G{i}' for i in g1], 'y': found.tolist()})
r1 = call('fitmodel.mixed', table=t1, y='y', effects=E({'names': ['g'], 'random': True}), mixed={}, alpha=0.05)
vc1 = by(r1['varcomp'], 'effect')
check.near('one-way, unbounded: REML = (MSB - MSE)/n, negative', vc1['g']['var'], (msb - mse) / n0, rel=1e-8)
check('... and it is below zero', vc1['g']['var'] < 0)
check.near('one-way, unbounded: the residual = MSE', vc1['Residual']['var'], mse, rel=1e-8)
se_tb = math.sqrt(2 / n0 ** 2 * (msb ** 2 / (a - 1) + mse ** 2 / (a * (n0 - 1))))
check.near('one-way: the standard error = the textbook formula (observed = expected information here)', vc1['g']['se'], se_tb, rel=1e-6)
z = stats.norm.ppf(0.975)
check.near('unbounded: a Wald interval (lower)', vc1['g']['lower'], vc1['g']['var'] - z * vc1['g']['se'], rel=1e-10)
check.near('unbounded: the Wald p-value, two-sided', vc1['g']['p'], 2 * stats.norm.sf(abs(vc1['g']['var']) / vc1['g']['se']), rel=1e-10)
dfr = 2 * (mse / vc1['Residual']['se']) ** 2
check.near('the residual: a Satterthwaite interval (lower)', vc1['Residual']['lower'], dfr * mse / stats.chi2.ppf(0.975, dfr), rel=1e-8)
check.near('the residual\'s Satterthwaite df = the error df a(n - 1) here', dfr, a * (n0 - 1), rel=1e-6)
check('the residual has no Wald p-value', vc1['Residual']['p'], None)
check.near('the intercept\'s DFDen = a - 1', r1['estimates'][0]['dfden'], a - 1, rel=1e-7)
check('a note says the estimate is negative', any('negative' in n for n in r1['notes']), True)
tot = vc1['Total']['var']
check.near('Total: the sum of the positive components only', tot, mse, rel=1e-10)
check.near('the sum of all components is given beside it', r1['allsum'], mse + (msb - mse) / n0, rel=1e-8)
rb1 = call('fitmodel.mixed', table=t1, y='y', effects=E({'names': ['g'], 'random': True}), mixed={'unbounded': False})
vb1 = by(rb1['varcomp'], 'effect')
check.near('bounded: the component is 0 on the boundary', vb1['g']['var'], 0.0, abs_=1e-12)
check.near('bounded: the residual is then the total variance', vb1['Residual']['var'], float(np.var(found, ddof=1)), rel=1e-8)
check('bounded: a note says the estimate is on the boundary', any('boundary' in n for n in rb1['notes']), True)
check('bounded: no Wald p-values', vb1['Residual']['p'] is None and vb1['g']['p'] is None, True)
check.near('bounded: the intercept\'s DFDen = n - 1 (the component is a known zero)', rb1['estimates'][0]['dfden'], a * n0 - 1, rel=1e-6)
# a sample with a positive estimate: MixedLM (bounded at zero) agrees
y1b = 3 + rng.normal(0, 1.5, a)[g1] + rng.normal(0, 1, a * n0)
t1b = table({'g': [f'G{i}' for i in g1], 'y': y1b.tolist()})
r1b = call('fitmodel.mixed', table=t1b, y='y', effects=E({'names': ['g'], 'random': True}))
ml = smf.mixedlm('y ~ 1', pd.DataFrame({'y': y1b, 'g': g1}), groups='g').fit(reml=True)
means_b = np.array([y1b[g1 == i].mean() for i in range(a)])
msb_b = n0 * np.sum((means_b - y1b.mean()) ** 2) / (a - 1)
mse_b = np.sum((y1b - means_b[g1]) ** 2) / (a * (n0 - 1))
check.near('positive estimate: = the ANOVA estimate', by(r1b['varcomp'], 'effect')['g']['var'], (msb_b - mse_b) / n0, rel=1e-9)
check.near('positive estimate: = MixedLM\'s variance (its optimizer\'s precision)', by(r1b['varcomp'], 'effect')['g']['var'], float(ml.cov_re.iloc[0, 0]), rel=1e-4)
check.near('positive estimate: -2 Residual Log Likelihood = -2 MixedLM llf', r1b['fit']['m2rll'], -2 * float(ml.llf), rel=1e-9)

# ---- 2. crossed random effects with their interaction: REML = the expected mean squares -------------------------
no, npart, nrep = 4, 6, 3
op = np.repeat(np.tile(np.arange(no), npart), nrep)
pt = np.repeat(np.repeat(np.arange(npart), no), nrep)
hit_neg = None
for trial in range(300):
    y2 = 10 + rng.normal(0, 1.0, no)[op] + rng.normal(0, 2.0, npart)[pt] + rng.normal(0, 0.15, no * npart)[op * npart + pt] + rng.normal(0, 1, len(op))
    df2 = pd.DataFrame({'op': [f'o{i}' for i in op], 'part': [f'p{i}' for i in pt], 'y': y2})
    comp, mse2, _rows, unb, _dfe = quality._ems(df2, 'y', ['op', 'part'], [('op', ['op']), ('part', ['part']), ('op*part', ['op', 'part'])])
    if unb['op*part'] < 0:
        hit_neg = (df2, unb, mse2)
        break
check('a crossed sample with a negative interaction component', hit_neg is not None)
df2, unb, mse2 = hit_neg
t2 = table({c: df2[c].tolist() for c in df2.columns})
r2 = call('fitmodel.mixed', table=t2, y='y', effects=E({'names': ['op'], 'random': True}, {'names': ['part'], 'random': True},
                                                         {'names': ['op', 'part'], 'random': True}))
vc2 = by(r2['varcomp'], 'effect')
for lab in ('op', 'part', 'op*part'):
    check.near(f'crossed, unbounded: {lab} = the EMS estimate', vc2[lab]['var'], unb[lab], rel=1e-7, abs_=1e-9)
check.near('crossed: the residual = the within mean square', vc2['Residual']['var'], mse2, rel=1e-8)
check('crossed: the interaction estimate is negative', vc2['op*part']['var'] < 0)

# ---- 3. a balanced split plot: Kenward-Roger's F and df are the exact tests --------------------------------------
nb, na, nbb = 6, 3, 4     # blocks, whole-plot levels, split-plot levels
blk = np.repeat(np.arange(nb), na * nbb)
A = np.tile(np.repeat(np.arange(na), nbb), nb)
B = np.tile(np.arange(nbb), nb * na)
for case, sd_wp in (('positive whole-plot error', 1.2), ('small whole-plot error', 0.05)):
    ys = 20 + 0.6 * A + 0.3 * (B == 1) + rng.normal(0, 1.0, nb)[blk] + rng.normal(0, sd_wp, nb * na)[blk * na + A] + rng.normal(0, 1, len(blk))
    dsp = pd.DataFrame({'blk': [f'b{i}' for i in blk], 'A': [f'a{i}' for i in A], 'B': [f'c{i}' for i in B], 'y': ys})
    tsp = table({c: dsp[c].tolist() for c in dsp.columns})
    eff = E('A', 'B', ['A', 'B'], {'names': ['blk'], 'random': True}, {'names': ['blk', 'A'], 'random': True})
    rs_ = call('fitmodel.mixed', table=tsp, y='y', effects=eff)
    # the ANOVA of the split plot
    ols = smf.ols('y ~ C(blk, Sum) + C(A, Sum) * C(B, Sum) + C(blk, Sum):C(A, Sum)', dsp).fit()
    an = sm.stats.anova_lm(ols, typ=1)
    ms = an['mean_sq']
    ms_wp, df_wp = float(ms['C(blk, Sum):C(A, Sum)']), float(an['df']['C(blk, Sum):C(A, Sum)'])
    mse_, dfe_ = float(ms['Residual']), float(an['df']['Residual'])
    FA = float(ms['C(A, Sum)']) / ms_wp
    FB = float(ms['C(B, Sum)']) / mse_
    FAB = float(ms['C(A, Sum):C(B, Sum)']) / mse_
    ts = by(rs_['tests'], 'source')
    check.near(f'split plot ({case}): F of the whole-plot factor = MS_A / MS_wholeplot', ts['A']['f'], FA, rel=1e-6)
    check.near(f'split plot ({case}): its DFDen = (blocks - 1)(A levels - 1)', ts['A']['dfden'], df_wp, rel=1e-6)
    check.near(f'split plot ({case}): F of the split-plot factor = MS_B / MSE', ts['B']['f'], FB, rel=1e-6)
    check.near(f'split plot ({case}): its DFDen = the error df', ts['B']['dfden'], dfe_, rel=1e-6)
    check.near(f'split plot ({case}): F of A*B = MS_AB / MSE', ts['A*B']['f'], FAB, rel=1e-6)
    check.near(f'split plot ({case}): its DFDen', ts['A*B']['dfden'], dfe_, rel=1e-6)
    vcs = by(rs_['varcomp'], 'effect')
    check.near(f'split plot ({case}): the whole-plot component = (MS_wp - MSE)/b', vcs['blk*A']['var'], (ms_wp - mse_) / nbb, rel=1e-6, abs_=1e-9)
    check.near(f'split plot ({case}): the p-value of A = the exact F test\'s', ts['A']['p'], float(stats.f.sf(FA, na - 1, df_wp)), rel=1e-5)
    rsat = call('fitmodel.mixed', table=tsp, y='y', effects=eff, mixed={'ddfm': 'sat'})
    tsat = by(rsat['tests'], 'source')
    check.near(f'split plot ({case}): Satterthwaite gives the same exact test here', tsat['A']['f'], FA, rel=1e-6)
    check.near(f'split plot ({case}): ... and the same df', tsat['A']['dfden'], df_wp, rel=1e-6)
    if case == 'positive whole-plot error':
        ml = smf.mixedlm('y ~ C(A, Sum) * C(B, Sum)', dsp, groups='blk', re_formula='1', vc_formula={'wp': '0 + C(A)'}).fit(reml=True)
        check.near('split plot: -2 Residual Log Likelihood = -2 MixedLM llf', rs_['fit']['m2rll'], -2 * float(ml.llf), rel=1e-6)

# ---- 4. unbalanced data: the dense reference (Kenward-Roger, Satterthwaite, the observed information) -------------
ns, maxr = 14, 6
sub = np.concatenate([np.full(k, i) for i, k in enumerate(rng.integers(2, maxr + 1, ns))])
n4 = len(sub)
x4 = rng.normal(0, 1, n4)
trt = np.array(['A', 'B', 'C'])[sub % 3]
y4 = 1 + 0.5 * x4 + (trt == 'B') * 0.8 + rng.normal(0, 0.9, ns)[sub] + rng.normal(0, 1, n4)
t4 = table({'s': [f's{i:02d}' for i in sub], 'trt': trt.tolist(), 'x': x4.tolist(), 'y': y4.tolist()})
eff4 = E('trt', 'x', {'names': ['s'], 'random': True})
r4 = call('fitmodel.mixed', table=t4, y='y', effects=eff4, table_name='unbal')
vc4 = by(r4['varcomp'], 'effect')
th4 = np.array([vc4['s']['var'], vc4['Residual']['var']])
Z4 = indicators(sub)
X4 = np.column_stack([np.ones(n4), (trt == 'A').astype(float) - (trt == 'C'), (trt == 'B').astype(float) - (trt == 'C'), x4])
D4 = Dense(X4, y4, lambda th: th[0] * Z4 @ Z4.T + th[1] * np.eye(n4), th4)
g4 = np.zeros(2)
for k in range(2):
    h = 1e-5
    a_, b_ = th4.copy(), th4.copy()
    a_[k] += h
    b_[k] -= h
    g4[k] = (D4.m2ll(a_) - D4.m2ll(b_)) / (2 * h)
check.near('unbalanced: the estimates are the REML maximum (the gradient of -2 log L is zero)', float(np.max(np.abs(g4))), 0.0, abs_=2e-5)
check.near('unbalanced: -2 Residual Log Likelihood = the dense formula', r4['fit']['m2rll'], D4.m2ll(th4), rel=1e-10)
fp4 = D4.fit_parts()
se_ref = np.sqrt(np.diag(np.linalg.inv(D4.obs(th4))))
check.near('unbalanced: the variance component\'s standard error = the inverse observed information', vc4['s']['se'], se_ref[0], rel=2e-4)
check.near('unbalanced: the residual\'s standard error', vc4['Residual']['se'], se_ref[1], rel=2e-4)
est4 = by(r4['estimates'], 'term')
check.near('unbalanced: the slope\'s Kenward-Roger standard error = sqrt of Phi_A', est4['x']['se'], math.sqrt(fp4['PhiA'][3, 3]), rel=1e-5)
check('... which is above the model-based one', est4['x']['se'] > math.sqrt(fp4['Phi'][3, 3]))
Lx = np.array([[0, 0, 0, 1.0]])
_F, m_ref = Dense.kr(fp4, Lx)
check.near('unbalanced: the slope\'s Kenward-Roger df (one df: Satterthwaite\'s with Phi)', est4['x']['dfden'], m_ref, rel=2e-4)
check.near('... = Satterthwaite\'s formula', m_ref, Dense.satt(fp4, Lx[0]), rel=1e-8)
Lt = np.array([[0, 1.0, 0, 0], [0, 0, 1.0, 0]])
F_ref, m2_ref = Dense.kr(fp4, Lt)
ts4 = by(r4['tests'], 'source')
check.near('unbalanced: the F of trt (two df, Kenward-Roger scaled)', ts4['trt']['f'], F_ref, rel=2e-4)
check.near('unbalanced: its Kenward-Roger df', ts4['trt']['dfden'], m2_ref, rel=2e-4)
r4s = call('fitmodel.mixed', table=t4, y='y', effects=eff4, mixed={'ddfm': 'sat'})
e4s = by(r4s['estimates'], 'term')
check.near('Satterthwaite: the model-based standard error', e4s['x']['se'], math.sqrt(fp4['Phi'][3, 3]), rel=1e-5)
check.near('Satterthwaite: its df', e4s['x']['dfden'], Dense.satt(fp4, Lx[0]), rel=2e-4)
ml4 = smf.mixedlm('y ~ C(trt, Sum) + x', pd.DataFrame({'y': y4, 'trt': trt, 'x': x4, 's': sub}), groups='s').fit(reml=True)
check.near('unbalanced: the slope = MixedLM', est4['x']['estimate'], float(ml4.fe_params['x']), rel=1e-5)
check.near('unbalanced: Satterthwaite\'s standard error = MixedLM\'s model-based one', e4s['x']['se'], float(ml4.bse_fe['x']), rel=1e-3)
# the BLUPs and their prediction errors
bl4 = r4['blups'][0]['rows']
Vi4 = np.linalg.inv(D4.Vfun(th4))
u_ref = th4[0] * Z4.T @ Vi4 @ (y4 - X4 @ fp4['b'])
P4 = Vi4 - Vi4 @ X4 @ fp4['Phi'] @ X4.T @ Vi4
C22 = th4[0] * np.eye(ns) - th4[0] ** 2 * Z4.T @ P4 @ Z4
check.near('BLUPs = G Z\'V^-1 (y - X b)', float(np.max(np.abs(np.array([r['blup'] for r in bl4]) - u_ref))), 0.0, abs_=1e-9)
check.near('the BLUPs\' standard errors: the prediction error variance G - G Z\'PZ G', float(np.max(np.abs(np.array([r['se'] for r in bl4]) - np.sqrt(np.diag(C22))))), 0.0, abs_=1e-8)
# Satterthwaite's df of a BLUP: 2 pev^2 / (grad' W grad), the gradient numerically
def pev(th):
    V = th[0] * Z4 @ Z4.T + th[1] * np.eye(n4)
    Vi = np.linalg.inv(V)
    Ph = np.linalg.inv(X4.T @ Vi @ X4)
    P = Vi - Vi @ X4 @ Ph @ X4.T @ Vi
    return np.diag(th[0] * np.eye(ns) - th[0] ** 2 * Z4.T @ P @ Z4)
gr = np.column_stack([(pev(th4 + h * np.eye(2)[k]) - pev(th4 - h * np.eye(2)[k])) / (2 * h) for k in range(2) for h in [1e-6]])
Wobs = np.linalg.inv(D4.obs(th4))
df_ref = 2 * pev(th4) ** 2 / np.einsum('ik,kl,il->i', gr, Wobs, gr)
check.near('the BLUPs\' DFDen: Satterthwaite\'s', float(np.max(np.abs(np.array([r['dfden'] for r in bl4]) - df_ref) / df_ref)), 0.0, abs_=5e-4)
cond4 = X4 @ fp4['b'] + Z4 @ u_ref
check.near('conditional predictions = X b + Z u', float(np.max(np.abs(np.array(r4['diag']['predicted']) - cond4))), 0.0, abs_=1e-9)
check.near('marginal predictions = X b', float(np.max(np.abs(np.array(r4['diag']['marginal']) - X4 @ fp4['b']))), 0.0, abs_=1e-9)
# the fit statistics, as JMP defines them (-2 log likelihood at the REML estimates; k = fixed + covariance parameters)
m2ll = n4 * math.log(2 * math.pi) + np.linalg.slogdet(D4.Vfun(th4))[1] + (y4 - X4 @ fp4['b']) @ Vi4 @ (y4 - X4 @ fp4['b'])
kpar = 4 + 2
check.near('-2 Log Likelihood: the full likelihood at the REML estimates', r4['fit']['m2ll'], m2ll, rel=1e-10)
check.near('AICc = -2 Log Likelihood + 2k + 2k(k+1)/(n-k-1)', r4['fit']['aicc'], m2ll + 2 * kpar + 2 * kpar * (kpar + 1) / (n4 - kpar - 1), rel=1e-10)
check.near('BIC = -2 Log Likelihood + k ln n', r4['fit']['bic'], m2ll + kpar * math.log(n4), rel=1e-10)
# the summary of fit of Standard Least Squares with a random effect (JMP's RSquare from the conditional residuals)
sof = {r['stat']: r['value'] for r in r4['summary']}
sst = float(np.sum((y4 - y4.mean()) ** 2))
sse = float(np.sum((y4 - cond4) ** 2))
check.near('Summary of Fit: RSquare = 1 - SSE(conditional) / SST', sof['RSquare'], 1 - sse / sst, rel=1e-10)
check.near('Summary of Fit: Root Mean Square Error = sqrt(residual variance)', sof['Root Mean Square Error'], math.sqrt(th4[1]), rel=1e-12)
# the code under the report
unbal = pd.DataFrame({'s': [f's{i:02d}' for i in sub], 'trt': trt, 'x': x4, 'y': y4})
nsx, err = run_code(r4['code'], unbal, 'unbal')
check('the code runs (unbalanced, Kenward-Roger)', err, None)
if not err:
    check.near('its fit has the report\'s -2 Residual Log Likelihood', float(-2 * nsx['fit'].llf), r4['fit']['m2rll'], rel=1e-8)
    check.near('its variance component', float(nsx['th'][0]), th4[0], rel=1e-6)
    check.near('its Kenward-Roger covariance of the slope', float(nsx['PhiA'][3, 3]), est4['x']['se'] ** 2, rel=1e-4)
    check.near('its df of trt', float(nsx['ddf'](np.eye(4)[[1, 2]])[1]), ts4['trt']['dfden'], rel=1e-4)


# ---- 5. least squares means with random effects: the balanced split plot in closed form ---------------------------
ys5 = 20 + 0.6 * A + 0.3 * (B == 1) + 0.5 * (A == 2) * (B == 3) + rng.normal(0, 1.0, nb)[blk] + rng.normal(0, 0.8, nb * na)[blk * na + A] + rng.normal(0, 1, len(blk))
d5 = pd.DataFrame({'blk': [f'b{i}' for i in blk], 'A': [f'a{i}' for i in A], 'B': [f'c{i}' for i in B], 'y': ys5})
t5 = table({c: d5[c].tolist() for c in d5.columns})
eff5 = E('A', 'B', ['A', 'B'], {'names': ['blk'], 'random': True}, {'names': ['blk', 'A'], 'random': True})
ols5 = smf.ols('y ~ C(blk, Sum) + C(A, Sum) * C(B, Sum) + C(blk, Sum):C(A, Sum)', d5).fit()
an5 = sm.stats.anova_lm(ols5, typ=1)
ms5 = an5['mean_sq']
mswp5, mse5, msblk5 = float(ms5['C(blk, Sum):C(A, Sum)']), float(ms5['Residual']), float(ms5['C(blk, Sum)'])
dfwp5, dfe5 = float(an5['df']['C(blk, Sum):C(A, Sum)']), float(an5['df']['Residual'])
lsA = call('mixed.lsmeans', table=t5, y='y', effects=eff5, effect='A')['lsmeans']['A']
meansA = d5.groupby('A').y.mean()
check.near('LS means of the whole-plot factor = its means (balanced)', float(np.max(np.abs(np.array(lsA['lsmean']) - meansA.to_numpy()))), 0.0, abs_=1e-9)
varA = (msblk5 + (na - 1) * mswp5) / (na * nb * nbb)       # (sigma_blk^2 + sigma_wp^2)/nb + sigma^2/(nb b), from the mean squares
check.near('... their standard error from the block and whole-plot mean squares', lsA['se'][0], math.sqrt(varA), rel=1e-6)
dfA = (msblk5 + (na - 1) * mswp5) ** 2 / (msblk5 ** 2 / (nb - 1) + ((na - 1) * mswp5) ** 2 / dfwp5)
check.near('... and Satterthwaite\'s df of that combination of mean squares', lsA['dfden'][0], dfA, rel=1e-5)
cA = call('mixed.compare', table=t5, y='y', effects=eff5, effect='A', method='tukey', table_name='sp5')
o0 = cA['ordered'][0]
check.near('Tukey HSD of the whole-plot factor: the difference\'s standard error = sqrt(2 MS_wp / (blocks b))', o0['se'], math.sqrt(2 * mswp5 / (nb * nbb)), rel=1e-6)
check.near('... its df = the whole-plot error df', o0['dfden'], dfwp5, rel=1e-6)
from scipy.stats import studentized_range
check.near('... its p-value from the studentized range', o0['p'], float(studentized_range.sf(o0['diff'] / o0['se'] * math.sqrt(2), na, dfwp5)), rel=1e-6)
check('connecting letters for every level', len(cA['letters']), na)
cB = call('mixed.compare', table=t5, y='y', effects=eff5, effect='B', method='student')
check.near('Student\'s t of the split-plot factor: se = sqrt(2 MSE / (blocks a))', cB['ordered'][0]['se'], math.sqrt(2 * mse5 / (nb * na)), rel=1e-6)
check.near('... its df = the error df', cB['ordered'][0]['dfden'], dfe5, rel=1e-6)
check.near('... its p-value, two-sided t', cB['ordered'][0]['p'], float(2 * stats.t.sf(cB['ordered'][0]['diff'] / cB['ordered'][0]['se'], dfe5)), rel=1e-6)
sl = call('mixed.slices', table=t5, y='y', effects=eff5, effect='A*B', table_name='sp5')
slr = by(sl['rows'], 'slice')
cellm = d5.groupby(['A', 'B']).y.mean()
for i in range(na):
    lab = f'A=a{i}'
    mb = cellm[f'a{i}'].to_numpy()
    Fx = nb * np.sum((mb - mb.mean()) ** 2) / (nbb - 1) / mse5
    check.near(f'Test Slices, {lab}: F = the simple effect of B on the error mean square', slr[lab]['f'], Fx, rel=1e-6)
    check.near(f'Test Slices, {lab}: df (b - 1, the error df)', (slr[lab]['dfnum'], slr[lab]['dfden'])[1], dfe5, rel=1e-6)
check('Test Slices at each level of B too', sum(1 for r in sl['rows'] if r['factor'] == 'B'), nbb)
ct = call('mixed.contrast', table=t5, y='y', effects=eff5, effect='A', coefs=[[1, -1, 0], [1, 1, -2]], table_name='sp5')
dA = meansA.to_numpy()
check.near('LSMeans Contrast: the estimate', ct['rows'][0]['estimate'], dA[0] - dA[1], rel=1e-9)
check.near('... its standard error', ct['rows'][0]['se'], math.sqrt(2 * mswp5 / (nb * nbb)), rel=1e-6)
check.near('... the joint test of both = the whole-plot F test', ct['joint']['f'], float(ms5['C(A, Sum)']) / mswp5, rel=1e-6)
check.near('... on the whole-plot df', ct['joint']['dendf'], dfwp5, rel=1e-6)
for fn, kw in (('mixed.compare', {'effect': 'A', 'method': 'tukey'}), ('mixed.contrast', {'effect': 'A', 'coefs': [[1, -1, 0]]}),
               ('mixed.slices', {'effect': 'A*B'}), ('mixed.lsmeans', {'effect': 'A*B'})):
    rr = call(fn, table=t5, y='y', effects=eff5, table_name='sp5', **kw)
    nsx, err = run_code(rr['code'], d5, 'sp5')
    check(f'{fn} code runs', err, None)
    if not err:
        check.near(f'... its least squares means are the report\'s ({kw["effect"]})', float(np.max(np.abs(nsx['lsm'] - np.array(
            call('mixed.lsmeans', table=t5, y='y', effects=eff5, effect=kw['effect'])['lsmeans'][kw['effect']]['lsmean'])))), 0.0, abs_=1e-7)
# unbalanced: the dense reference
ls4 = call('mixed.lsmeans', table=t4, y='y', effects=eff4, effect='trt')['lsmeans']['trt']
Lb = np.array([[1, 1, 0, x4.mean()], [1, 0, 1, x4.mean()], [1, -1, -1, x4.mean()]])
check.near('unbalanced LS means = L b, the continuous factor at its mean', float(np.max(np.abs(np.array(ls4['lsmean']) - Lb @ fp4['b']))), 0.0, abs_=1e-9)
check.near('... their Kenward-Roger standard error', float(np.max(np.abs(np.array(ls4['se']) - np.sqrt(np.diag(Lb @ fp4['PhiA'] @ Lb.T))))), 0.0, abs_=1e-6)
check.near('... their df', ls4['dfden'][0], Dense.kr(fp4, Lb[:1])[1], rel=2e-4)


# ---- 6. correlated random coefficients (an unstructured G per subject) = MixedLM's random intercept and slope ------
nsub6, nt6 = 12, 6
s6 = np.repeat(np.arange(nsub6), nt6)
x6 = np.tile(np.arange(nt6, dtype=float), nsub6) + rng.uniform(-0.3, 0.3, nsub6 * nt6)
U = rng.multivariate_normal([0, 0], [[2.0, -0.4], [-0.4, 0.3]], nsub6)
y6 = 5 + 0.8 * x6 + U[s6, 0] + U[s6, 1] * x6 + rng.normal(0, 0.7, len(s6))
d6 = pd.DataFrame({'batch': [f'k{i:02d}' for i in s6], 'x': x6, 'y': y6})
t6 = table({c: d6[c].tolist() for c in d6.columns})
eff6 = [{'names': ['x']}, {'names': ['batch'], 'random': True, 'rc': 1}, {'names': ['x'], 'nest': ['batch'], 'random': True, 'rc': 1}]
r6 = call('fitmodel.mixed', table=t6, y='y', effects=eff6, table_name='rc6')
ml6 = smf.mixedlm('y ~ x', d6, groups='batch', re_formula='1 + x').fit(reml=True, method=['lbfgs'])
cr = ml6.cov_re.to_numpy()
v6 = by(r6['varcomp'], 'effect')
check('random coefficients: Var(Intercept), Cov(x,Intercept), Var(x) and the residual', [r['effect'] for r in r6['varcomp']], ['Var(Intercept)', 'Cov(x,Intercept)', 'Var(x)', 'Residual'])
check('... with the subject column', v6['Var(Intercept)']['subject'], 'batch')
check.near('Var(Intercept) = MixedLM', v6['Var(Intercept)']['var'], cr[0, 0], rel=2e-4)
check.near('Cov(x,Intercept) = MixedLM', v6['Cov(x,Intercept)']['var'], cr[0, 1], rel=2e-4, abs_=1e-5)
check.near('Var(x) = MixedLM', v6['Var(x)']['var'], cr[1, 1], rel=2e-4)
check.near('the residual = MixedLM\'s scale', v6['Residual']['var'], float(ml6.scale), rel=2e-4)
check.near('-2 Residual Log Likelihood = -2 MixedLM llf', r6['fit']['m2rll'], -2 * float(ml6.llf), rel=1e-7)
e6 = by(r6['estimates'], 'term')
check.near('the fixed slope = MixedLM', e6['x']['estimate'], float(ml6.fe_params['x']), rel=1e-5)
coef6 = r6['coefs'][0]
check('Random Coefficients: a row per batch, a column per coefficient', (len(coef6['levels']), coef6['coefs']), (nsub6, ['Intercept', 'x']))
reff = np.array([ml6.random_effects[k].to_numpy() for k in sorted(ml6.random_effects)])
check.near('... the BLUPs = MixedLM\'s random effects', float(np.max(np.abs(np.array(coef6['u']) - reff))), 0.0, abs_=2e-4)
# the dense reference with the random coefficients' covariance as three parameters
Z0 = indicators(s6)
Z1 = Z0 * x6[:, None]
th6 = np.array([v6['Var(Intercept)']['var'], v6['Cov(x,Intercept)']['var'], v6['Var(x)']['var'], v6['Residual']['var']])
V6 = lambda th: th[0] * Z0 @ Z0.T + th[1] * (Z0 @ Z1.T + Z1 @ Z0.T) + th[2] * Z1 @ Z1.T + th[3] * np.eye(len(y6))   # noqa: E731
X6 = np.column_stack([np.ones(len(y6)), x6])
D6 = Dense(X6, y6, V6, th6)
fp6 = D6.fit_parts()
check.near('random coefficients: the standard error of Cov = the inverse observed information', v6['Cov(x,Intercept)']['se'],
           math.sqrt(np.linalg.inv(D6.obs(th6))[1, 1]), rel=3e-4)
check.near('... the slope\'s Kenward-Roger standard error', e6['x']['se'], math.sqrt(fp6['PhiA'][1, 1]), rel=1e-5)
check.near('... its Kenward-Roger df', e6['x']['dfden'], Dense.kr(fp6, np.array([[0, 1.0]]))[1], rel=3e-4)
nsx, err = run_code(r6['code'], d6, 'rc6')
check('random coefficients: the code runs', err, None)
if not err:
    check.near('... its -2 Residual Log Likelihood', float(-2 * nsx['fit'].llf), r6['fit']['m2rll'], rel=1e-8)
    check.near('... its BLUPs', float(np.max(np.abs(nsx['blups'][0] - np.array(coef6['u'])))), 0.0, abs_=1e-6)
# independent slopes (Nest, not Nest Random Coefficients): two variance components
r6i = call('fitmodel.mixed', table=t6, y='y', effects=[{'names': ['x']}, {'names': ['batch'], 'random': True}, {'names': ['x'], 'nest': ['batch'], 'random': True}])
ml6i = smf.mixedlm('y ~ x', d6, groups='batch', re_formula='1', vc_formula={'slope': '0 + C(batch):x'}).fit(reml=True)
check.near('independent random slopes: the slope\'s variance = MixedLM', by(r6i['varcomp'], 'effect')['x[batch]']['var'], float(ml6i.vcomp[0]), rel=5e-4)
check('... the likelihood ratio of the covariance: -2RLL(independent) >= -2RLL(correlated)', r6i['fit']['m2rll'] >= r6['fit']['m2rll'] - 1e-6)

# ---- 7. repeated structures: closed forms and the dense reference ----------------------------------------------
nsub7, J7 = 16, 4
s7 = np.repeat(np.arange(nsub7), J7)
tm7 = np.tile(np.arange(J7), nsub7)
grp7 = np.where(s7 < nsub7 // 2, 'P', 'Q')
Sig = 0.5 * np.eye(J7) + 0.9 * 0.7 ** np.abs(np.subtract.outer(np.arange(J7), np.arange(J7)))
Sig = Sig * np.outer([1.0, 1.2, 1.5, 1.9], [1.0, 1.2, 1.5, 1.9])
ey = rng.multivariate_normal(np.zeros(J7), Sig, nsub7).reshape(-1)
y7 = 10 + 0.5 * tm7 + (grp7 == 'Q') * 0.8 + ey
d7 = pd.DataFrame({'subject': [f's{i:02d}' for i in s7], 'time': [f't{j}' for j in tm7], 'hour': tm7.astype(float) + 1, 'grp': grp7, 'y': y7})
t7 = table({c: d7[c].tolist() for c in d7.columns})
# UN with the full group*time fixed structure: REML's covariance = the pooled within-group covariance of the responses
effU = E('grp', 'time', ['grp', 'time'])
rU = call('fitmodel.mixed', table=t7, y='y', effects=effU, mixed={'structure': 'un', 'repeated': ['time'], 'subject': ['subject']}, table_name='rep7')
W7 = y7.reshape(nsub7, J7)
Sp = sum(np.cov(W7[grp7.reshape(nsub7, J7)[:, 0] == gv].T, ddof=1) * (np.sum(grp7.reshape(nsub7, J7)[:, 0] == gv) - 1) for gv in ('P', 'Q')) / (nsub7 - 2)
cm = np.array(rU['rmatrix']['cov'])
check.near('Unstructured: the covariance = the pooled within-group covariance (as MANOVA\'s)', float(np.max(np.abs(cm - Sp))), 0.0, abs_=2e-6)
check('Unstructured: J(J+1)/2 parameters', len(rU['repeated']), J7 * (J7 + 1) // 2)
# one group: the time effect's Kenward-Roger F with UN is Hotelling's T^2 F exactly (Kenward and Roger 1997)
t7a = table({c: d7[d7.grp == 'P'][c].tolist() for c in d7.columns})
rH = call('fitmodel.mixed', table=t7a, y='y', effects=E('time'), mixed={'structure': 'un', 'repeated': ['time'], 'subject': ['subject']})
Wp = W7[: nsub7 // 2]
Cc = np.diff(np.eye(J7), axis=0)                  # successive differences
Dm = Wp @ Cc.T
nP = nsub7 // 2
dbar = Dm.mean(0)
T2 = nP * dbar @ np.linalg.solve(np.cov(Dm.T, ddof=1), dbar)
Fh = (nP - (J7 - 1)) / ((nP - 1) * (J7 - 1)) * T2
tH = by(rH['tests'], 'source')['time']
check.near('Unstructured, one group: the time F (Kenward-Roger) = Hotelling\'s T^2 F', tH['f'], Fh, rel=1e-6)
check.near('... on n - J + 1 df', tH['dfden'], nP - J7 + 1, rel=1e-6)
# compound symmetry = a random subject intercept (the correlation positive)
rCS = call('fitmodel.mixed', table=t7, y='y', effects=E('grp', 'time'), mixed={'structure': 'cs', 'repeated': ['time'], 'subject': ['subject']})
rRI = call('fitmodel.mixed', table=t7, y='y', effects=E('grp', 'time', {'names': ['subject'], 'random': True}))
vRI = by(rRI['varcomp'], 'effect')
rep_cs = by(rCS['repeated'], 'param')
check.near('Compound Symmetry = the random-intercept model: -2 Residual Log Likelihood', rCS['fit']['m2rll'], rRI['fit']['m2rll'], rel=1e-9)
check.near('... its correlation = the intraclass correlation', rep_cs['Compound Symmetry']['estimate'],
           vRI['subject']['var'] / (vRI['subject']['var'] + vRI['Residual']['var']), rel=1e-6)
check.near('... its variance = the total variance', rep_cs['Residual']['estimate'], vRI['subject']['var'] + vRI['Residual']['var'], rel=1e-6)
check.near('... the same F of grp', by(rCS['tests'], 'source')['grp']['f'], by(rRI['tests'], 'source')['grp']['f'], rel=1e-6)
# every structure against the dense reference: the REML optimum (a zero gradient), -2 log L, the standard errors
sub_ = s7
same = sub_[:, None] == sub_[None, :]
eye = np.eye(len(y7), dtype=bool)
lev = tm7
lag = np.abs(lev[:, None] - lev[None, :])
hr = tm7.astype(float) + 1
dist = np.abs(hr[:, None] - hr[None, :])


def Rs(kind, th):
    J = J7
    if kind == 'uneqvar':
        return np.diag(th[lev])
    if kind in ('ar1', 'arh'):
        C = th[J] ** dist if kind == 'arh' else th[0] ** dist
    elif kind in ('toep', 'toeph'):
        k0 = J if kind == 'toeph' else 0
        C = np.r_[1.0, th[k0:k0 + J - 1]][lag]
    elif kind in ('ante', 'antevar'):
        k0 = J if kind == 'ante' else 0
        r = th[k0:k0 + J - 1]
        lo, hi = np.minimum(lev[:, None], lev[None, :]), np.maximum(lev[:, None], lev[None, :])
        C = np.ones_like(lag, dtype=float)
        for i in range(J - 1):
            C = C * np.where((lo <= i) & (hi > i), r[i], 1.0)
    elif kind in ('cs', 'csh'):
        rho = th[J] if kind == 'csh' else th[0]
        C = np.where(eye, 1.0, rho)
    if kind in ('arh', 'toeph', 'ante', 'csh'):
        sd = np.sqrt(th[:J])[lev]
        return np.where(same, C, 0) * np.outer(sd, sd)
    return th[-1] * np.where(same, C, 0)


X7 = np.column_stack([np.ones(len(y7)), (grp7 == 'P').astype(float) - (grp7 == 'Q')] + [(tm7 == j).astype(float) - (tm7 == J7 - 1) for j in range(J7 - 1)])
for kind in ('uneqvar', 'ar1', 'arh', 'toep', 'toeph', 'ante', 'antevar', 'csh'):
    rep_col = ['hour'] if kind in ('ar1', 'arh') else ['time']
    rr = call('fitmodel.mixed', table=t7, y='y', effects=E('grp', 'time'), mixed={'structure': kind, 'repeated': rep_col, 'subject': ['subject']},
              table_name='rep7')
    th = np.array([r['estimate'] for r in rr['repeated']])
    Dk = Dense(X7, y7, lambda t_, kind=kind: Rs(kind, t_), th)
    gg = []
    for k in range(len(th)):
        h = 1e-6 * max(1, abs(th[k]))
        a_, b_ = th.copy(), th.copy()
        a_[k] += h
        b_[k] -= h
        gg.append((Dk.m2ll(a_) - Dk.m2ll(b_)) / (2 * h))
    check.near(f'{kind}: the REML maximum (the gradient of the dense -2 log L)', float(np.max(np.abs(gg))), 0.0, abs_=5e-4)
    check.near(f'{kind}: -2 Residual Log Likelihood = the dense formula', rr['fit']['m2rll'], Dk.m2ll(th), rel=1e-9)
    se_d = np.sqrt(np.diag(np.linalg.inv(Dk.obs(th))))
    se_r = np.array([r['se'] for r in rr['repeated']])
    check.near(f'{kind}: the standard errors = the inverse observed information', float(np.max(np.abs(se_r - se_d) / se_d)), 0.0, abs_=2e-3)
    fpk = Dk.fit_parts()
    tg = by(rr['tests'], 'source')['time']
    Fk, mk = Dense.kr(fpk, np.eye(X7.shape[1])[2:])
    check.near(f'{kind}: the time F (Kenward-Roger)', tg['f'], Fk, rel=2e-3)
    check.near(f'{kind}: its df', tg['dfden'], mk, rel=5e-3)
    nsx, err = run_code(rr['code'], d7, 'rep7')
    check(f'{kind}: the code runs', err, None)
    if not err:
        check.near(f'{kind}: ... its -2 Residual Log Likelihood', float(-2 * nsx['fit'].llf), rr['fit']['m2rll'], rel=1e-7)
# AR(1) with unequally spaced times: the correlation is rho to the power of the time apart
hr2 = np.tile(np.array([0.0, 1.0, 2.5, 6.0]), nsub7)
d7b = d7.assign(hour=hr2)
t7b = table({c: d7b[c].tolist() for c in d7b.columns})
rA = call('fitmodel.mixed', table=t7b, y='y', effects=E('grp', 'time'), mixed={'structure': 'ar1', 'repeated': ['hour'], 'subject': ['subject']})
thA = np.array([r['estimate'] for r in rA['repeated']])
distb = np.abs(hr2[:, None] - hr2[None, :])
DA = Dense(X7, y7, lambda t_: t_[1] * np.where(same, t_[0] ** distb, 0), thA)
gA = [(DA.m2ll(thA + h * np.eye(2)[k]) - DA.m2ll(thA - h * np.eye(2)[k])) / (2 * h) for k in range(2) for h in [1e-6]]
check.near('AR(1), unequal spacing: the REML maximum', float(np.max(np.abs(gA))), 0.0, abs_=5e-4)
check('AR(1): the parameter names', [r['param'] for r in rA['repeated']], ['AR(1) hour', 'Residual'])
# a random effect with a repeated structure: a random block over subjects plus AR(1) within them
blk7 = s7 // 4
d7c = d7.assign(block=[f'B{i}' for i in blk7])
t7c = table({c: d7c[c].tolist() for c in d7c.columns})
rBA = call('fitmodel.mixed', table=t7c, y='y', effects=E('grp', 'time', {'names': ['block'], 'random': True}),
           mixed={'structure': 'ar1', 'repeated': ['hour'], 'subject': ['subject']})
thBA = np.array([rBA['varcomp'][0]['var']] + [r['estimate'] for r in rBA['repeated']])
Zb = indicators(blk7)
DBA = Dense(X7, y7, lambda t_: t_[0] * Zb @ Zb.T + t_[2] * np.where(same, t_[1] ** dist, 0), thBA)
check.near('a random block and AR(1) together: -2 Residual Log Likelihood = the dense formula', rBA['fit']['m2rll'], DBA.m2ll(thBA), rel=1e-9)
gBA = [(DBA.m2ll(thBA + 1e-6 * np.eye(3)[k]) - DBA.m2ll(thBA - 1e-6 * np.eye(3)[k])) / 2e-6 for k in range(3)]
check.near('... the REML maximum', float(np.max(np.abs(gBA))), 0.0, abs_=5e-4)

# ---- 8. spatial structures: the dense reference ---------------------------------------------------------------
n8 = 60
xy = rng.uniform(0, 10, (n8, 2))
Dm8 = np.sqrt(((xy[:, None] - xy[None]) ** 2).sum(-1))
Ctrue = 1.5 * np.exp(-Dm8 / 2.0) + 0.3 * np.eye(n8)
salt = rng.uniform(0, 5, n8)
y8 = 1 - 0.4 * salt + rng.multivariate_normal(np.zeros(n8), Ctrue)
d8 = pd.DataFrame({'east': xy[:, 0], 'north': xy[:, 1], 'salt': salt, 'y': y8})
t8 = table({c: d8[c].tolist() for c in d8.columns})
X8 = np.column_stack([np.ones(n8), salt])
Fsp = {'pow': lambda r: r ** Dm8, 'exp': lambda r: np.exp(-Dm8 / r), 'gau': lambda r: np.exp(-(Dm8 / r) ** 2),
       'sph': lambda r: np.where(Dm8 < r, 1 - 1.5 * Dm8 / r + 0.5 * (Dm8 / r) ** 3, 0.0)}
for sp in ('exp', 'gau', 'sph', 'pow'):
    for kind in ('sp', 'spn'):
        rr = call('fitmodel.mixed', table=t8, y='y', effects=E('salt'), mixed={'structure': kind, 'sptype': sp, 'repeated': ['east', 'north']},
                  table_name='sp8')
        if rr.get('error'):
            check(f'spatial {sp} {kind}: fits', rr.get('error'), None)
            continue
        th = np.array([r['estimate'] for r in rr['repeated']])
        if kind == 'sp':
            Vf = lambda t_, sp=sp: t_[1] * Fsp[sp](t_[0])   # noqa: E731
        else:
            Vf = lambda t_, sp=sp: t_[2] * (Fsp[sp](t_[0]) + t_[1] * np.eye(n8))   # noqa: E731
        D8 = Dense(X8, y8, Vf, th)
        check.near(f'spatial {sp} ({"with nugget" if kind == "spn" else "no nugget"}): -2 Residual Log Likelihood = the dense formula',
                   rr['fit']['m2rll'], D8.m2ll(th), rel=1e-9)
        gg = []
        for k in range(len(th)):
            h = 1e-6 * max(1, abs(th[k]))
            gg.append((D8.m2ll(th + h * np.eye(len(th))[k]) - D8.m2ll(th - h * np.eye(len(th))[k])) / (2 * h))
        ok_max = float(np.max(np.abs(gg))) < 5e-3 or (sp == 'sph' and rr['fit']['converged'])
        check(f'spatial {sp} {kind}: the REML maximum (gradient {float(np.max(np.abs(gg))):.1e})', ok_max, True)
        if sp == 'exp' and kind == 'spn':
            check('spatial names: the range, the nugget, the residual', [r['param'] for r in rr['repeated']], ['Spatial Exponential', 'Nugget', 'Residual'])
            nsx, err = run_code(rr['code'], d8, 'sp8')
            check('spatial: the code runs', err, None)
            if not err:
                check.near('... its -2 Residual Log Likelihood', float(-2 * nsx['fit'].llf), rr['fit']['m2rll'], rel=1e-7)


# a flat likelihood: a smooth field of bumps fitted by the exponential with a nugget, where the relative gradient
# stalls near 1e-8 (the score's rounding) and cannot reach the tolerance: converged when -2LL stops changing
n8b = 300
rng8b = np.random.default_rng(4)
e8b, no8b = rng8b.uniform(0, 30, n8b), rng8b.uniform(0, 30, n8b)
x8b = rng8b.normal(size=n8b)
bumps8b = [(rng8b.uniform(0, 30), rng8b.uniform(0, 30), rng8b.normal()) for _ in range(30)]
y8b = 1 + 0.5 * x8b + sum(h * np.exp(-((e8b - a) ** 2 + (no8b - b) ** 2) / 16) for a, b, h in bumps8b) + rng8b.normal(0, 0.5, n8b)
cols8b = {'east': e8b.round(4), 'north': no8b.round(4), 'x': x8b.round(4), 'y': y8b.round(4)}
t8b = table({k: v.tolist() for k, v in cols8b.items()})
import time as _time  # noqa: E402
_t0 = _time.time()
r8b = call('fitmodel.mixed', table=t8b, y='y', effects=E('x'), mixed={'structure': 'spn', 'sptype': 'exp', 'repeated': ['east', 'north']})
_dt = _time.time() - _t0
check(f'a flat spatial likelihood: converged, in {r8b["fit"]["iterations"]} iterations ({_dt:.1f} s)', (r8b['fit']['converged'], r8b['fit']['iterations'] < 100), (True, True))
th8b = np.array([r_['estimate'] for r_ in r8b['repeated']])
Dm8b = np.hypot(cols8b['east'][:, None] - cols8b['east'][None, :], cols8b['north'][:, None] - cols8b['north'][None, :])
D8b = Dense(np.column_stack([np.ones(n8b), cols8b['x']]), cols8b['y'], lambda t_: t_[2] * (np.exp(-Dm8b / t_[0]) + t_[1] * np.eye(n8b)), th8b)
from scipy.optimize import minimize  # noqa: E402
best8b = minimize(lambda z: D8b.m2ll(np.exp(z)), np.log(th8b) + 0.05, method='Nelder-Mead', options={'xatol': 1e-9, 'fatol': 1e-12, 'maxiter': 4000})
check.near('... its -2 Residual Log Likelihood = the dense formula\'s minimum (Nelder-Mead from nearby)', r8b['fit']['m2rll'], min(best8b.fun, D8b.m2ll(th8b)), rel=1e-9)


# ---- 9. Save Columns for every row, the formulas, Compare Structures, the variogram ----------------------------------
y9 = y4.copy()
y9[[3, 10]] = np.nan                       # rows without a response: predicted all the same
t9 = table({'s': [f's{i:02d}' for i in sub], 'trt': trt.tolist(), 'x': x4.tolist(), 'y': [None if not np.isfinite(v) else float(v) for v in y9]})
sv = call('mixed.save', table=t9, y='y', effects=eff4)
r9 = call('fitmodel.mixed', table=t9, y='y', effects=eff4)
check('Save Columns: every row with its predictors, a missing response too', len(sv['rows']), n4)
keep9 = np.isfinite(y9)
b9 = {e_['term']: e_['estimate'] for e_ in r9['estimates']}
Xp = np.column_stack([np.ones(n4), (trt == 'A').astype(float) - (trt == 'C'), (trt == 'B').astype(float) - (trt == 'C'), x4])
bv = np.array([b9['Intercept'], b9['trt[A]'], b9['trt[B]'], b9['x']])
check.near('the marginal prediction of every row = X b', float(np.max(np.abs(np.array(sv['columns']['predicted']) - Xp @ bv))), 0.0, abs_=1e-9)
bl9 = {r_['level']: r_['blup'] for r_ in r9['blups'][0]['rows']}
condv = Xp @ bv + np.array([bl9[f's{i:02d}'] for i in sub])
check.near('the conditional prediction adds the level\'s BLUP (rows without a response too)', float(np.max(np.abs(np.array(sv['columns']['cond']) - condv))), 0.0, abs_=1e-9)
check('the residuals of rows without a response are missing', [sv['columns']['residual'][i] for i in (3, 10)], [None, None])
fm = {f_['name']: f_['expr'] for f_ in sv['formulas']}
check('Prediction Formula: effect coding as Match', 'Match(:trt' in fm['Pred Formula y'], True)
check('Conditional Prediction Formula: the BLUPs as a Match of the levels, 0 for a new one', 'Match(:s, "s00", ' in fm['Cond Pred Formula y'] and fm['Cond Pred Formula y'].count(', 0)') >= 1, True)
check('Save Simulation Formula: one normal draw per level and one per row', 'Col Mean(Random Normal(), :s)' in sv['simulation']['expr'] and 'Random Normal(0, ' in sv['simulation']['expr'], True)
# conditional mean interval: the prediction error of X b + Z u (the mixed model equations' inverse)
Vi9 = np.linalg.inv(D4.Vfun(th4))
Ph9 = fp4['Phi']
G9 = th4[0] * np.eye(ns)
C21 = -G9 @ Z4.T @ Vi9 @ X4 @ Ph9
P9 = Vi9 - Vi9 @ X4 @ Ph9 @ X4.T @ Vi9
C22 = G9 - G9 @ Z4.T @ P9 @ Z4 @ G9
# (this table has two responses missing: compare on the full table instead)
svf = call('mixed.save', table=t4, y='y', effects=eff4)
vcond = np.einsum('ij,jk,ik->i', X4, fp4['PhiA'], X4) + 2 * np.einsum('ij,jk,ik->i', Z4, C21, X4) + np.einsum('ij,jk,ik->i', Z4, C22, Z4)
check.near('Standard Error of Conditional Predicted = sqrt([x z] C [x z]\')', float(np.max(np.abs(np.array(svf['columns']['se_cond']) - np.sqrt(vcond)))), 0.0, abs_=1e-7)
cs9 = call('mixed.structures', table=t7, y='y', effects=E('grp', 'time'), mixed={'structure': 'ar1', 'repeated': ['time'], 'subject': ['subject']})
check('Compare Structures: a row per structure', len(cs9['rows']) >= 10, True)
aic = {r_['kind']: r_['aicc'] for r_ in cs9['rows'] if 'aicc' in r_}
rTo = call('fitmodel.mixed', table=t7, y='y', effects=E('grp', 'time'), mixed={'structure': 'toep', 'repeated': ['time'], 'subject': ['subject']})
check.near('Compare Structures: Toeplitz\'s AICc = its own report\'s', aic['toep'], rTo['fit']['aicc'], rel=1e-10)
check('... sorted by AICc', [r_['aicc'] for r_ in cs9['rows'] if 'aicc' in r_] == sorted(aic.values()), True)
check('... the best by AICc marked', sum(1 for r_ in cs9['rows'] if r_.get('best_aicc')), 1)
vg = call('mixed.variogram', table=t8, y='y', effects=E('salt'), mixed={'structure': 'spn', 'sptype': 'exp', 'repeated': ['east', 'north']},
          curves=['sp:gau', 'spn:sph'], table_name='sp8')
r8 = call('fitmodel.mixed', table=t8, y='y', effects=E('salt'), mixed={'structure': 'spn', 'sptype': 'exp', 'repeated': ['east', 'north']})
b8 = np.array([r8['estimates'][0]['estimate'], r8['estimates'][1]['estimate']])
res8 = y8 - X8 @ b8
iu = np.triu_indices(n8, 1)
dd8 = Dm8[iu]
sq8 = (res8[iu[0]] - res8[iu[1]]) ** 2
ed = np.linspace(0, dd8.max(), 11)
kk = np.minimum(np.searchsorted(ed, dd8, side='right') - 1, 9)
g_ref = [sq8[kk == b_].sum() / (2 * np.sum(kk == b_)) for b_ in range(10) if np.any(kk == b_)]
check.near('variogram: the semivariance of each distance class (the marginal residuals)', float(np.max(np.abs(np.array([p_['gamma'] for p_ in vg['points']]) - g_ref))), 0.0, abs_=1e-10)
check('variogram: ten equal distance classes', len(vg['points']), 10)
fitc = [c_ for c_ in vg['curves'] if c_['fit']][0]
rp8 = by(r8['repeated'], 'param')
hmid = fitc['h'][60]
gm = rp8['Residual']['estimate'] * (1 - math.exp(-hmid / rp8['Spatial Exponential']['estimate'])) + rp8['Nugget']['estimate'] * rp8['Residual']['estimate']
check.near('variogram: the fitted curve from the estimates (partial sill, range, the nugget scaled by the residual)', fitc['gamma'][60], gm, rel=1e-10)
check('variogram: the added curves', [c_['label'] for c_ in vg['curves'] if not c_['fit']], ['Gaussian', 'Spherical with nugget'])
nsx, err = run_code(vg['plot_code'], d8, 'sp8')
check('variogram code runs', err, None)


# ---- 10. Simulate: power and coverage; the code gives the same samples ---------------------------------------------
fx5 = call('fitmodel.mixed', table=t5, y='y', effects=eff5)
bJ = [r_['estimate'] for r_ in fx5['estimates']]
bJ0 = [bJ[0]] + [0.0] * (len(bJ) - 1)                   # every effect zero: the tests' size
thJ = [r_['var'] for r_ in fx5['varcomp'] if r_['effect'] in ('blk', 'blk*A', 'Residual')]
sims = [call('mixed.simulate', table=t5, y='y', effects=eff5, beta=bJ0, theta=thJ, n=10, seed=7, start=s0) for s0 in (0, 10)]
whole = call('mixed.simulate', table=t5, y='y', effects=eff5, beta=bJ0, theta=thJ, n=20, seed=7, start=0)
check.near('Simulate: two runs of 10 samples = one run of 20 (each sample its own seed)', float(np.max(np.abs(np.array(sims[0]['tests']['A'] + sims[1]['tests']['A']) - np.array(whole['tests']['A'])))), 0.0, abs_=1e-12)
acc = {k: {} for k in ('tests', 'terms', 'cover', 'estimates', 'covparms', 'cp_cover')}
for sm_ in sims:
    for k in acc:
        for name, v in sm_[k].items():
            acc[k].setdefault(name, []).extend(v)
acc['true'] = whole['true']
pw = call('mixed.power', results=acc, levels=[0.01, 0.05, 0.1, 0.2])
rowA = [r_ for r_ in pw['power'] if r_['term'] == 'A' and r_['alpha'] == 0.2][0]
kA = int(np.sum(np.array(whole['tests']['A']) < 0.2))
check.near('the rejection rate at alpha = 0.2', rowA['rate'], kA / 20, rel=1e-12)
zq = stats.norm.ppf(0.975)
ph = kA / 20
wl = (ph + zq ** 2 / 40 - zq * math.sqrt(ph * (1 - ph) / 20 + zq ** 2 / 1600)) / (1 + zq ** 2 / 20)
check.near('... its Wilson interval (lower)', rowA['lower'], max(0.0, wl), rel=1e-10, abs_=1e-12)
sc_ = call('mixed.simulate_code', table=t5, y='y', effects=eff5, beta=bJ0, theta=thJ, n=20, seed=7, table_name='sp5')
nsx, err = run_code(sc_['code'], d5, 'sp5')
check('Simulate\'s code runs', err, None)
if not err:
    check.near('... its p-values of A are the report\'s samples\' (the same draws)', float(np.max(np.abs(np.array(nsx['pvals']['A']) - np.array(whole['tests']['A'])))), 0.0, abs_=1e-6)
# the size of the whole-plot test: close to alpha over many samples (Kenward-Roger's exact test here)
big = call('mixed.simulate', table=t5, y='y', effects=eff5, beta=bJ0, theta=thJ, n=300, seed=11, start=0)
rate = float(np.mean(np.array(big['tests']['A']) < 0.05))
check('Simulate under no effect: the whole-plot test\'s size is near 0.05 (300 samples, within 3 standard errors)', abs(rate - 0.05) < 3 * math.sqrt(0.05 * 0.95 / 300), True)
cov_b = float(np.mean(big['cover']['B[c0]']))
check('... the fixed effects\' 95% intervals cover the truth about 95% of the time', abs(cov_b - 0.95) < 3 * math.sqrt(0.05 * 0.95 / 300), True)

# ---- 11. the Skeleton ANOVA, Compare Models' p-values, profile-likelihood intervals, the Conditional Profiler --------
sk = call('mixed.skeleton', table=t5, y='y', effects=eff5)
skd = {r_['source']: r_['df'] for r_ in sk['rows']}
check('Skeleton ANOVA of the split plot: A 2, B 3, A*B 6, blocks 5, whole plots 10, residual 45',
      [skd['A'], skd['B'], skd['A*B'], skd['blk'], skd['blk*A'], skd['Residual']], [na - 1, nbb - 1, (na - 1) * (nbb - 1), nb - 1, (nb - 1) * (na - 1), int(dfe5)])
check('... no warnings', sk['warnings'], [])
# an unreplicated block by treatment interaction is confounded with the residual
rb_ = np.repeat(np.arange(5), 3)
tr_ = np.tile(np.arange(3), 5)
t11 = table({'blk': [f'b{i}' for i in rb_], 'trt': [f't{i}' for i in tr_], 'y': rng.normal(size=15).tolist()})
sk2 = call('mixed.skeleton', table=t11, y='y', effects=E('trt', {'names': ['blk'], 'random': True}, {'names': ['blk', 'trt'], 'random': True}))
check('Skeleton ANOVA: an unreplicated block*treatment is confounded with the residual', any('confounded with the residual' in w for w in sk2['warnings']), True)
# a random effect confounded with a fixed effect
t12 = table({'inc': [f'i{i % 3}' for i in range(18)], 'batch': [f'k{i % 3}' for i in range(18)], 'y': rng.normal(size=18).tolist()})
sk3 = call('mixed.skeleton', table=t12, y='y', effects=E('inc', {'names': ['batch'], 'random': True}))
check('Skeleton ANOVA: a random effect confounded with a fixed one adds no df', any('adds no degrees of freedom' in w for w in sk3['warnings']), True)
lr_ = call('mixed.lrt', chisq=3.05, df=1, mixture=True)
check.near('Compare Models: the chi-square p-value', lr_['p'], float(stats.chi2.sf(3.05, 1)), rel=1e-12)
check.near('... the 50:50 mixture for a variance at zero: half of it', lr_['p_mix'], 0.5 * float(stats.chi2.sf(3.05, 1)), rel=1e-12)
pc = call('mixed.profile_ci', table=t1b, y='y', effects=E({'names': ['g'], 'random': True}), alpha=0.05)
pg = by(pc['rows'], 'param')['g']
Z1 = indicators(g1)
Xo = np.ones((len(g1), 1))


def m2_prof(t):
    from scipy.optimize import minimize_scalar
    D = Dense(Xo, y1b, lambda th: th[0] * Z1 @ Z1.T + th[1] * np.eye(len(g1)), [t, 1.0])
    rr = minimize_scalar(lambda ls: D.m2ll(np.array([t, math.exp(ls)])), bounds=(-10, 5), method='bounded', options={'xatol': 1e-10})
    return rr.fun


m2min = r1b['fit']['m2rll']
check.near('profile likelihood: -2RLL at the upper limit = the minimum + chi2(1) 95%', m2_prof(pg['upper']) - m2min, float(stats.chi2.ppf(0.95, 1)), rel=1e-4)
check('... a lower limit', pg['lower'] is not None, True)
if pg['lower'] is not None:
    check.near('... at the lower limit', m2_prof(pg['lower']) - m2min, float(stats.chi2.ppf(0.95, 1)), rel=1e-4)
check('... the profile interval is asymmetric (wider above) for a variance', pg['upper'] - pg['estimate'] > pg['estimate'] - pg['lower'], True)
cp = call('mixedcond.profile', table=t4, y='y', effects=eff4, current={'trt': 'B', 'x': 0.5, 's': 's03'})
blv = {r_['level']: r_['blup'] for r_ in r4['blups'][0]['rows']}
check.near('Conditional Profiler: the prediction at a level = X b + its BLUP', cp['responses'][0]['current']['pred'],
           float(np.array([1, 0, 1, 0.5]) @ fp4['b']) + blv['s03'], rel=1e-9)
check('... the random effect is a factor', [f_['name'] for f_ in cp['factors']], ['trt', 'x', 's'])


# ---- 12. generalized linear mixed models by pseudo-likelihood (RSPL): an independent loop written here -------------
from scipy.optimize import minimize_scalar


def rspl(ev, nt, X, Z, dist):
    """Wolfinger and O'Connell's RSPL, dense: the pseudo-response and weights from mu, the variance
    component by REML on them (one-dimensional search, unbounded where V stays positive definite), the
    BLUPs, mu again, until the estimates settle."""
    ZZ = Z @ Z.T
    mu = (ev + 0.5) / (nt + 1) if dist == 'binomial' else ev + 0.5
    prev = None
    for _ in range(200):
        if dist == 'binomial':
            eta = np.log(mu / (1 - mu)); dd = 1 / (mu * (1 - mu)); w = nt * mu * (1 - mu)
        else:
            eta = np.log(mu); dd = 1 / mu; w = mu
        ys = eta + (ev / nt - mu) * dd
        Dg = Dense(X, ys, lambda th: th[0] * ZZ + np.diag(1 / w), [0.0])
        lo = -0.99 / np.max(np.linalg.eigvalsh(np.diag(np.sqrt(w)) @ ZZ @ np.diag(np.sqrt(w))))

        def f(t):
            try:
                return Dg.m2ll(np.array([t]))
            except np.linalg.LinAlgError:
                return 1e300
        t = minimize_scalar(f, bounds=(lo, 20.0), method='bounded', options={'xatol': 1e-12}).x
        V = t * ZZ + np.diag(1 / w)
        Vi = np.linalg.inv(V)
        b = np.linalg.solve(X.T @ Vi @ X, X.T @ Vi @ ys)
        u = t * Z.T @ Vi @ (ys - X @ b)
        eta = X @ b + Z @ u
        mu = 1 / (1 + np.exp(-eta)) if dist == 'binomial' else np.exp(eta)
        cur = np.r_[b, t]
        if prev is not None and np.max(np.abs(cur - prev)) < 1e-10:
            break
        prev = cur
    return b, t, u


nb12, nk12 = 14, 3
blk12 = np.repeat(np.arange(nb12), nk12)
trt12 = np.tile(np.arange(nk12), nb12)
u12 = rng.normal(0, 0.8, nb12)
eta12 = -0.4 + 0.6 * (trt12 == 1) + 1.0 * (trt12 == 2) + u12[blk12]
nt12 = np.full(len(blk12), 25.0)
ev12 = rng.binomial(25, 1 / (1 + np.exp(-eta12))).astype(float)
t12b = table({'block': [f'B{i:02d}' for i in blk12], 'trt': [f't{k}' for k in trt12], 'events': ev12.tolist(), 'trials': nt12.tolist()})
eff12 = E('trt', {'names': ['block'], 'random': True})
rg = call('fitmodel.mixed', table=t12b, y=['events', 'trials'], effects=eff12, mixed={'glmm': {'dist': 'binomial', 'link': 'logit'}}, table_name='glmm')
X12 = np.column_stack([np.ones(len(blk12)), (trt12 == 0).astype(float) - (trt12 == 2), (trt12 == 1).astype(float) - (trt12 == 2)])
Z12 = indicators(blk12)
b_ref, t_ref, u_ref12 = rspl(ev12, nt12, X12, Z12, 'binomial')
eg = by(rg['estimates'], 'term')
check.near('GLMM binomial (events of trials): the block variance = the RSPL loop written here', by(rg['varcomp'], 'effect')['block']['var'], t_ref, rel=1e-5)
check.near('... the intercept', eg['Intercept']['estimate'], b_ref[0], rel=1e-6)
check.near('... trt[t0]', eg['trt[t0]']['estimate'], b_ref[1], rel=1e-6, abs_=1e-7)
check('... the scale fixed at 1: no residual row', [r_['effect'] for r_ in rg['varcomp']], ['block'])
check.near('... the conditional predictions on the probability scale', float(np.max(np.abs(np.array(rg['diag']['predicted']) - 1 / (1 + np.exp(-(X12 @ b_ref + Z12 @ u_ref12)))))), 0.0, abs_=1e-6)
ls12 = call('mixed.lsmeans', table=t12b, y=['events', 'trials'], effects=eff12, effect='trt', mixed={'glmm': {'dist': 'binomial', 'link': 'logit'}})['lsmeans']['trt']
mu12 = 1 / (1 + np.exp(-np.array(ls12['lsmean'])))
check.near('LS means on the inverse link: the probability', float(np.max(np.abs(np.array([r_['mu'] for r_ in ls12['rows']]) - mu12))), 0.0, abs_=1e-10)
check.near('... its delta-method standard error, mu(1 - mu) se', float(np.max(np.abs(np.array([r_['mu_se'] for r_ in ls12['rows']]) - mu12 * (1 - mu12) * np.array(ls12['se'])))), 0.0, abs_=1e-6)
cm12 = call('mixed.compare', table=t12b, y=['events', 'trials'], effects=eff12, effect='trt', method='student', mixed={'glmm': {'dist': 'binomial', 'link': 'logit'}})
o12 = cm12['ordered'][0]
check('the differences as odds ratios', cm12['ratio'], 'Odds Ratio')
check.near('... the odds ratio = exp(difference)', o12['ratio'], math.exp(o12['diff']), rel=1e-12)
check.near('... its interval = exp(the difference\'s)', o12['ratio_lower'], math.exp(o12['lower']), rel=1e-12)
nsx, err = run_code(rg['code'], pd.DataFrame({'block': [f'B{i:02d}' for i in blk12], 'trt': [f't{k}' for k in trt12], 'events': ev12, 'trials': nt12}), 'glmm')
check('GLMM: the code runs (the RSPL loop)', err, None)
if not err:
    check.near('... its block variance', float(nsx['th'][0]), t_ref, rel=1e-5)
    check.near('... its fixed effects', float(np.max(np.abs(nsx['f']['b'] - b_ref))), 0.0, abs_=1e-6)
# a binary response (a two-level Y, the target level) and the GLM limit: no block variance, bounded at zero = the GLM
yb12 = rng.binomial(1, 1 / (1 + np.exp(-(-0.2 + 0.7 * (trt12 == 2)))), len(blk12))
t12c = table({'block': [f'B{i:02d}' for i in blk12], 'trt': [f't{k}' for k in trt12], 'ok': ['yes' if v else 'no' for v in yb12]}, types={'ok': 'nominal'}, levels={'ok': ['yes', 'no']})
rgb = call('fitmodel.mixed', table=t12c, y='ok', effects=eff12, mixed={'unbounded': False, 'glmm': {'dist': 'binomial', 'link': 'logit', 'target': 'yes'}})
import statsmodels.api as sm_
glm12 = sm_.GLM(yb12.astype(float), X12, family=sm_.families.Binomial()).fit()
vcb = by(rgb['varcomp'], 'effect')['block']['var']
if vcb == 0:
    check.near('binary, the block variance at zero: the GLM\'s estimates (IRLS is RSPL without random effects)', float(np.max(np.abs(np.array([r_['estimate'] for r_ in rgb['estimates']]) - glm12.params))), 0.0, abs_=1e-6)
else:
    bb_ref, tb_ref, _ub = rspl(yb12.astype(float), np.ones(len(yb12)), X12, Z12, 'binomial')
    check.near('binary: the block variance = the RSPL loop', vcb, max(tb_ref, 0.0), rel=1e-4, abs_=1e-7)
# a target level with a line break (a table from a file is hostile input): the code's comment stays one line
bad = 'yes\nimport os; os.system("x")'
t12h = table({'block': [f'B{i:02d}' for i in blk12], 'trt': [f't{k}' for k in trt12], 'ok': [bad if v else 'no' for v in yb12]}, types={'ok': 'nominal'}, levels={'ok': [bad, 'no']})
rgh = call('fitmodel.mixed', table=t12h, y='ok', effects=eff12, mixed={'unbounded': False, 'glmm': {'dist': 'binomial', 'link': 'logit', 'target': bad}})
hcode = '\n'.join(v for k, v in rgh.get('code', {}).items() if isinstance(v, str)) if isinstance(rgh.get('code'), dict) else str(rgh.get('code', ''))
check('GLMM: an event level with a line break stays in its string literal and its one-line comment',
      (bool(hcode), any(ln.lstrip().startswith('import os') for ln in hcode.split('\n')), any(ln.endswith('# the event: yes import os; os.system("x")') for ln in hcode.split('\n'))), (True, False, True))
# Poisson counts
cnt12 = rng.poisson(np.exp(0.8 + 0.4 * (trt12 == 1) + rng.normal(0, 0.5, nb12)[blk12])).astype(float)
t12d = table({'block': [f'B{i:02d}' for i in blk12], 'trt': [f't{k}' for k in trt12], 'count': cnt12.tolist()})
rp12 = call('fitmodel.mixed', table=t12d, y='count', effects=eff12, mixed={'glmm': {'dist': 'poisson', 'link': 'log'}})
bp_ref, tp_ref, _up = rspl(cnt12, np.ones(len(cnt12)), X12, Z12, 'poisson')
check.near('GLMM Poisson: the block variance = the RSPL loop', by(rp12['varcomp'], 'effect')['block']['var'], tp_ref, rel=1e-5)
check.near('... the fixed effects', float(np.max(np.abs(np.array([r_['estimate'] for r_ in rp12['estimates']]) - bp_ref))), 0.0, abs_=1e-6)
cp12 = call('mixed.compare', table=t12d, y='count', effects=eff12, effect='trt', method='tukey', mixed={'glmm': {'dist': 'poisson', 'link': 'log'}})
check('... the differences as rate ratios', cp12['ratio'], 'Rate Ratio')

# ---- 13. weights in REML: the residual variance divided by the weight ---------------------------------------------
w13 = rng.uniform(0.5, 3.0, n4)
t13 = table({'s': [f's{i:02d}' for i in sub], 'trt': trt.tolist(), 'x': x4.tolist(), 'y': y4.tolist(), 'w': w13.tolist()})
r13 = call('fitmodel.mixed', table=t13, y='y', effects=eff4, weight='w')
v13 = by(r13['varcomp'], 'effect')
th13 = np.array([v13['s']['var'], v13['Residual']['var']])
D13 = Dense(X4, y4, lambda th: th[0] * Z4 @ Z4.T + th[1] * np.diag(1 / w13), th13)
g13 = [(D13.m2ll(th13 + 1e-6 * np.eye(2)[k]) - D13.m2ll(th13 - 1e-6 * np.eye(2)[k])) / 2e-6 for k in range(2)]
check.near('Weight: the REML maximum of V = s2_s Z Z\' + s2 W^-1', float(np.max(np.abs(g13))), 0.0, abs_=1e-4)
check.near('... -2 Residual Log Likelihood = the dense formula', r13['fit']['m2rll'], D13.m2ll(th13), rel=1e-10)
nsx, err = run_code(r13['code'], pd.DataFrame({'s': [f's{i:02d}' for i in sub], 'trt': trt, 'x': x4, 'y': y4, 'w': w13}), 'data')
check('Weight: the code runs', err, None)
if not err:
    check.near('... its -2 Residual Log Likelihood', float(-2 * nsx['fit'].llf), r13['fit']['m2rll'], rel=1e-8)
# Freq: a row that many times, exactly as the rows repeated
fq = rng.integers(1, 4, n4)
t13f = table({'s': [f's{i:02d}' for i in sub], 'trt': trt.tolist(), 'x': x4.tolist(), 'y': y4.tolist(), 'f': fq.astype(float).tolist()})
rf = call('fitmodel.mixed', table=t13f, y='y', effects=eff4, freq='f')
rep_ = np.repeat(np.arange(n4), fq)
t13r = table({'s': [f's{sub[i]:02d}' for i in rep_], 'trt': trt[rep_].tolist(), 'x': x4[rep_].tolist(), 'y': y4[rep_].tolist()})
rr_ = call('fitmodel.mixed', table=t13r, y='y', effects=eff4)
check.near('Freq: the fit of the rows repeated (-2 Residual Log Likelihood)', rf['fit']['m2rll'], rr_['fit']['m2rll'], rel=1e-9)
check('... Sum of Frequencies', (rf['fit']['sumfreq'], rf['fit']['rows']), (int(fq.sum()), n4))


# ---- 14. Indicator Parameterization Estimates: the same fit in SAS GLM's 0/1 coding ---------------------------------
ind = call('mixed.indicator', table=t4, y='y', effects=eff4, table_name='unbal')
ie = by(ind['rows'], 'term')
Xg = np.column_stack([np.ones(n4), (trt == 'A').astype(float), (trt == 'B').astype(float), x4])      # C the reference
Vg = D4.Vfun(th4)
Vig = np.linalg.inv(Vg)
Cg = np.linalg.inv(Xg.T @ Vig @ Xg)
bg = Cg @ Xg.T @ Vig @ y4
check.near('Indicator Parameterization: trt[A] = the GLS estimate with 0/1 columns, C the reference', ie['trt[A]']['estimate'], bg[1], rel=1e-8)
check.near('... the intercept (the last level\'s mean at x = 0)', ie['Intercept']['estimate'], bg[0], rel=1e-8)
Mg = np.linalg.lstsq(Xg, X4, rcond=None)[0]
check.near('... its Kenward-Roger standard error = M Phi_A M\'', ie['trt[A]']['se'], math.sqrt((Mg @ fp4['PhiA'] @ Mg.T)[1, 1]), rel=1e-5)
check.near('... the same -2 Residual Log Likelihood', ind['m2rll'], r4['fit']['m2rll'], rel=1e-12)
nsx, err = run_code(ind['code'], unbal, 'unbal')
check('Indicator Parameterization: the code runs', err, None)
if not err:
    check.near('... its estimates', float(np.max(np.abs(nsx['bi'] - np.array([ie[k]['estimate'] for k in ('Intercept', 'trt[A]', 'trt[B]', 'x')])))), 0.0, abs_=1e-7)


# levels with brackets and both quotes (a table from a file is hostile input): the formulas are written from the levels
lv14 = ['a])', 'it\'s "x"', 'c, Sum, levels=[1])']
rng14 = np.random.default_rng(14)
blk14 = np.repeat(np.arange(8), 6)
trt14 = np.tile(np.arange(3), 16)
y14 = 5 + np.array([0.0, 1.0, -0.5])[trt14] + rng14.normal(0, 0.8, 8)[blk14] + rng14.normal(0, 1, len(blk14))
d14 = pd.DataFrame({'blk': [f'b{i}' for i in blk14], 'trt': [lv14[k] for k in trt14], 'y': y14})
t14 = table({c: d14[c].tolist() for c in d14.columns}, levels={'trt': lv14})
eff14 = E('trt', {'names': ['blk'], 'random': True})
r14 = call('fitmodel.mixed', table=t14, y='y', effects=eff14, table_name='hostile')
check('levels with brackets and quotes: the fit', r14.get('error'), None)
nsx, err = run_code(r14['code'], d14, 'hostile')
check('... its code runs', err, None)
if not err:
    check.near('... and gives the report\'s -2 Residual Log Likelihood', float(nsx['f']['m2']), r14['fit']['m2rll'], rel=1e-9)
ind14 = call('mixed.indicator', table=t14, y='y', effects=eff14, table_name='hostile')
check('... Indicator Parameterization: the rows, the last level the reference', [r_['term'] for r_ in ind14['rows']], ['Intercept', 'trt[a])]', 'trt[it\'s "x"]'])
nsx, err = run_code(ind14['code'], d14, 'hostile')
check('... its code runs (a Treatment reference written from the level, not parsed back)', err, None)
if not err:
    check.near('... its estimates', float(np.max(np.abs(nsx['bi'] - np.array([r_['estimate'] for r_ in ind14['rows']])))), 0.0, abs_=1e-7)
    check.near('... trt[a])] = the difference of its mean from the last level\'s (balanced)', float(nsx['bi'][1]), float(d14.groupby('trt')['y'].mean()[lv14[0]] - d14.groupby('trt')['y'].mean()[lv14[2]]), rel=1e-7)


# ---- 15. JSL: NoBounds is the launch's Unbounded Variance Components ------------------------------------------------
from smui import jsl_python
TJ = [{'name': 'T', 'columns': [{'name': 'y', 'dataType': 'numeric', 'modelingType': 'continuous'}, {'name': 'trt', 'dataType': 'character', 'modelingType': 'nominal'},
                                {'name': 'block', 'dataType': 'character', 'modelingType': 'nominal'}]}]
for nb_, want in (('1', True), ('0', False)):
    cj = jsl_python.convert_text(f'Fit Model( Y( :y ), Effects( :trt ), Random Effects( :block ), NoBounds( {nb_} ), Personality( "Mixed Model" ), Run );', TJ, 'T')
    st_ = cj['steps'][0]
    check(f'JSL NoBounds({nb_}): Unbounded Variance Components {"on" if want else "off"}', (st_['options'].get('personality'), st_['options'].get('mxUnbounded')), ('mixed', want))
cj = jsl_python.convert_text('Fit Model( Y( :y ), Effects( :trt, :block & Random ), Personality( "Generalized Linear Model" ), GLM Distribution( "Poisson" ), Run );', TJ, 'T')
check('JSL: a Poisson GLM with a random effect is kept without a warning (a GLMM)', [n_['text'] for n_ in cj['notes'] if 'fixed effects only' in n_['text']], [])

print()
sys.exit(check.done())
