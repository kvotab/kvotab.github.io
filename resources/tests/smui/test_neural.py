#!/usr/bin/env python3
"""Analyze > Predictive Modeling > Neural's backend (resources/py/smui/neural.py),
the network of our own that fits JMP's model as JMP documents it.

Checked here: the gradient of the objective (every activation, one and two
layers, continuous and categorical responses together, Robust Fit, every
penalty, a boosting offset) against central finite differences; the
likelihoods against scipy's normal, Laplace and categorical densities at the
profiled scale; a network of Linear nodes without a penalty against least
squares, weighted least squares with a Freq column, logistic regression,
multinomial logistic regression (statsmodels) and median regression with
Robust Fit (QuantReg); the design (effect coding with the last level, and the
missing level last, written out here; centred and scaled on the training
rows; Transform Covariates' Johnson Su or Sb fitted by scipy on the training
rows, the better one); the penalty path, early stopping, tours, KFold and a
K-fold Validation column chosen as documented; boosting's sum of base
models; the Estimates' network written out by hand (a forward pass on the
design's own scale); the names JMP gives the models and the settings saved
before; Save Columns; Save Formulas and Save Profile Formulas run in the
page's own formula engine (node) on every row; the profiler; and the Python
shown under each model, and every graph's code, run on a CSV export.

    python3 resources/tests/smui/test_neural.py
"""
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
from scipy import stats

from backend import FAILED, Checks, call, table

check = Checks()
check('neural.py imports', 'neural' in FAILED, False)
from smui import neural as NN, predictive as pv  # noqa: E402
import statsmodels.api as sm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.abspath(os.path.join(HERE, '..', '..', 'js'))

# ---- the table ------------------------------------------------------------------------------------
rng = np.random.default_rng(20260929)
n = 300
x1 = rng.normal(0, 1, n)
x2 = rng.uniform(-2, 2, n)
x3 = np.exp(rng.normal(0, 0.8, n))                     # skewed, for Transform Covariates
g = rng.choice(['a', 'b', 'c'], n, p=[0.5, 0.3, 0.2])
y = np.sin(2 * x1) + 0.5 * x2 ** 2 + np.where(g == 'b', 1.0, 0.0) + 0.3 * np.log(x3) + rng.normal(0, 0.3, n)
ylin = 1 + 0.8 * x1 - 0.5 * x2 + np.where(g == 'b', 0.7, np.where(g == 'c', -0.4, 0.0)) + rng.standard_t(3, n) * 0.5
cls = np.where(y + rng.normal(0, 0.6, n) > np.median(y), 'hi', 'lo')
three = np.where(y < np.quantile(y, 0.3), 'L', np.where(y < np.quantile(y, 0.7), 'M', 'H'))
fq = rng.integers(1, 4, n).astype(float)
vnum = rng.choice([0.0, 1.0, 2.0], n, p=[0.6, 0.25, 0.15])
vall = np.zeros(n)                                     # a Validation column with no validation rows
kfold_col = rng.integers(1, 6, n).astype(float)        # a K-fold Validation column (5 folds)
x1m = x1.copy()
x1m[rng.choice(n, 15, replace=False)] = np.nan
gm = g.astype(object).copy()
gm[rng.choice(n, 12, replace=False)] = None
ym = y.copy()
ym[[4, 40, 140]] = np.nan
cols = {'y': list(y), 'ylin': list(ylin), 'ym': [None if np.isnan(v) else v for v in ym], 'x1': list(x1), 'x2': list(x2), 'x3': list(x3), 'g': list(g),
        'gm': list(gm), 'x1m': [None if np.isnan(v) else v for v in x1m], 'cls': list(cls), 'three': list(three), 'f': list(fq), 'v': list(vnum),
        'v0': list(vall), 'kf': list(kfold_col)}
T = table(cols, types={'g': 'nominal', 'gm': 'nominal', 'cls': 'nominal', 'three': 'ordinal'}, levels={'three': ['L', 'M', 'H'], 'cls': ['hi', 'lo'], 'g': ['a', 'b', 'c'], 'gm': ['a', 'b', 'c']})
XS = ['x1', 'x2', 'g']
SEED = 4242


def fit(model=None, y=('y',), x=XS, **kw):
    kw.setdefault('table', T)
    return call('neural.fit', y=list(y), x=list(x), seed=kw.pop('seed', SEED), model=model or {}, **kw)


def built(model=None, y=('y',), x=XS, **kw):
    """The backend's fitted model (the cache the report fills)."""
    return NN._model(kw.pop('table', T), kw.pop('rows', None), list(y), list(x), kw.pop('freq', None), kw.pop('validation', None), kw.pop('seed', SEED),
                     kw.pop('missing', 'informative'), model or {}, kw.pop('holdback', None))


def mx(a, b):
    return float(np.max(np.abs(np.asarray(a, float) - np.asarray(b, float))))


# ---- the gradient against finite differences ---------------------------------------------------------------------
def fd_check(net, Tg, Z, rows, lam, pen, offset=None, h=1e-6):
    th = net.start(np.random.default_rng(3)) + np.random.default_rng(4).normal(0, 0.3, net.size)
    f0, g0 = NN.objective(th, net, Tg, Z, rows, lam, pen, offset)
    num = np.zeros_like(th)
    for i in range(net.size):
        e = np.zeros_like(th)
        e[i] = h
        num[i] = (NN.objective(th + e, net, Tg, Z, rows, lam, pen, offset)[0] - NN.objective(th - e, net, Tg, Z, rows, lam, pen, offset)[0]) / (2 * h)
    return mx(g0, num) / max(1.0, float(np.max(np.abs(num))))


Zg = np.random.default_rng(5).normal(size=(60, 4))
yc_ = np.random.default_rng(6).normal(size=60)
yk_ = np.random.default_rng(7).integers(0, 3, 60)
wg = np.random.default_rng(8).integers(1, 3, 60).astype(float)
rows_g = np.arange(50)
for label, layers, ys, kinds, robust, pen, lam in [
        ('one layer of TanH, a continuous response', [['tanh'] * 3], [yc_], [0], False, 'squared', 0.01),
        ('Linear and Gaussian nodes, Robust Fit, the Absolute penalty', [['linear', 'gauss', 'gauss']], [yc_], [0], True, 'absolute', 0.05),
        ('two layers, a continuous and a categorical response together, Weight Decay', [['tanh', 'gauss'], ['tanh', 'linear', 'gauss']], [yc_, yk_], [0, 3], False, 'weight_decay', 0.1),
        ('two levels, no penalty', [['tanh', 'tanh']], [yk_ % 2], [2], False, 'none', 0.0)]:
    net = NN.Net(Zg.shape[1], layers, sum(k - 1 if k else 1 for k in kinds))
    Tg = NN.Targets(ys, kinds, wg, np.isin(np.arange(60), rows_g), robust)
    check(f'gradient: {label}: the objective\'s gradient is the finite differences\'', fd_check(net, Tg, Zg, rows_g, lam, pen) < 1e-6, True)
netb = NN.Net(4, [['tanh', 'tanh']], 2)
Tb = NN.Targets([yk_], [3], wg, np.ones(60, dtype=bool))
check('gradient: ... with a boosting offset on the log odds', fd_check(netb, Tb, Zg, rows_g, 0.01, 'squared', np.random.default_rng(9).normal(size=(60, 2))) < 1e-6, True)

# ---- the likelihoods: JMP's, against scipy ------------------------------------------------------------------------------
O = np.random.default_rng(10).normal(size=(60, 1)) * 0.3
Tc = NN.Targets([yc_], [0], wg, np.ones(60, dtype=bool))
z = Tc.blocks[0]['z']
r_ = z - O[:, 0]
s2 = np.sum(wg * r_ ** 2) / wg.sum()
check.near('the Gaussian likelihood with the variance profiled: -sum w log normal(r; 0, SSE/N)', Tc.loss(O, np.arange(60), grad=False)[0], -np.sum(wg * stats.norm.logpdf(r_, 0, math.sqrt(s2))), 1e-10)
Tr = NN.Targets([yc_], [0], wg, np.ones(60, dtype=bool), robust=True)
bhat = np.sum(wg * np.abs(r_)) / wg.sum()
check.near('Robust Fit: the Laplace likelihood with the scale profiled, -sum w log laplace(r; 0, SAD/N) (|r| smoothed by 1e-4)', Tr.loss(O, np.arange(60), grad=False)[0], -np.sum(wg * stats.laplace.logpdf(r_, 0, bhat)), 5e-4)
Ok = np.random.default_rng(11).normal(size=(60, 2))
Tk = NN.Targets([yk_], [3], wg, np.ones(60, dtype=bool))
Pk = np.exp(np.column_stack([Ok, np.zeros(60)]))
Pk /= Pk.sum(axis=1, keepdims=True)
check.near('the multinomial likelihood, the log odds of each level against the last: -sum w log p', Tk.loss(Ok, np.arange(60), grad=False)[0], -np.sum(wg * np.log(Pk[np.arange(60), yk_])), 1e-10)
check('... and the probabilities it predicts', mx(Tk.predict(Ok)[0], Pk) < 1e-12, True)

# ---- the design: effect coding, the missing level last, centred and scaled; Johnson transforms ----------------------------
M = built(y=['y'], x=['x1m', 'gm', 'x2'])
P0 = M.Ps[0]
D = M.design.raw(P0.X)
xv = pd.to_numeric(pd.Series(np.asarray(x1m)[P0.index]), errors='coerce').to_numpy()
fill = P0.enc[0]['fill']
gv = np.asarray(gm, dtype=object)[P0.index]
eff = np.column_stack([np.where(gv == lv, 1.0, np.where(pd.isna(gv), -1.0, 0.0)) for lv in ('a', 'b', 'c')])
want = np.column_stack([np.where(np.isnan(xv), fill, xv), np.isnan(xv).astype(float), eff, np.asarray(x2)[P0.index]])
check('the design: a continuous factor\'s value (a missing one the training mean) and its missing column; a categorical one\'s effect coding, the missing level last', mx(D, want) < 1e-12, True)
check('... its names, JMP\'s', NN._design_names(P0, M.design), ['x1m', 'x1m Missing', 'gm[a]', 'gm[b]', 'gm[c]', 'x2'])
tr = P0.sets == 0
Zd = M.design.apply(P0.X)
check('... centred and scaled by the training rows\' mean and standard deviation', (mx(Zd[tr].mean(axis=0), 0) < 1e-12, mx(Zd[tr].std(axis=0), 1) < 1e-12), (True, True))
M2 = built(y=['y'], x=['x1', 'g'])
D2 = M2.design.raw(M2.Ps[0].X)
g2 = np.asarray(g)[M2.Ps[0].index]
check('without a missing level: a column per level but the last, the last -1', mx(D2[:, 1:], np.column_stack([np.where(g2 == lv, 1.0, np.where(g2 == 'c', -1.0, 0.0)) for lv in ('a', 'b')])) < 1e-12, True)
MT = built(y=['y'], x=['x1', 'x3', 'g'], model={'transform': True})
PT = MT.Ps[0]
trT = PT.sets == 0
for j, name in ((0, 'x1'), (1, 'x3')):
    par = MT.design.johnson[j]
    v = PT.X[trT, j]
    su = stats.johnsonsu.fit(v)
    lo, hi = v.min(), v.max()
    pad = 0.05 * (hi - lo)
    sb = stats.johnsonsb.fit(v, loc=lo - pad, scale=hi - lo + 2 * pad)
    llsu, llsb = np.sum(stats.johnsonsu.logpdf(v, *su)), np.sum(stats.johnsonsb.logpdf(v, *sb))
    want_kind = 'su' if (not math.isfinite(llsb) or llsu >= llsb) else 'sb'
    check(f'Transform Covariates: {name}: the Johnson {want_kind.upper()} fitted by scipy on the training rows (the one of the larger likelihood)', (par[0], mx(par[1:], su if want_kind == 'su' else sb) < 1e-12), (want_kind, True))
    zz = NN.johnson_z(par, v)
    check(f'... its transform of the training rows is near normal (Shapiro-Wilk p > 0.01)', stats.shapiro(zz).pvalue > 0.01, True)
zx3 = MT.design.raw(PT.X)[:, 1]
check('... the design holds the transform (T(x3))', (NN._design_names(PT, MT.design)[:2], mx(zx3, NN.johnson_z(MT.design.johnson[1], PT.X[:, 1])) < 1e-12), (['T(x1)', 'T(x3)'], True))

# ---- a network of Linear nodes, no penalty: the linear models it is ------------------------------------------------------
lin = {'t1': 0, 'l1': 1, 'penalty': 'none', 'max_iter': 5000}
for label, kw, fam in [('least squares', dict(y=['ylin']), 'ols'), ('weighted least squares, a Freq column', dict(y=['ylin'], freq='f'), 'wls'),
                       ('logistic regression', dict(y=['cls']), 'logit'), ('Robust Fit: median regression', dict(y=['ylin'], model=dict(lin, robust=True)), 'lad')]:
    kw.setdefault('model', lin)
    Mx = built(validation='v0', **kw)
    Px = Mx.Ps[0]
    X_ = np.column_stack([np.ones(len(Px.index)), Mx.design.raw(Px.X)])
    pred = Mx.res['model'].predict(Mx.Z)[0]
    if fam == 'ols':
        ref = sm.OLS(Px.target, X_).fit().fittedvalues
        check.near(f'Linear nodes, no penalty: {label}: the network\'s predictions are OLS\'s', mx(pred, ref), 0.0, 1e-6)
    elif fam == 'wls':
        ref = sm.WLS(Px.target, X_, weights=Px.w).fit().fittedvalues
        check.near(f'Linear nodes, no penalty: {label}: the network\'s predictions are WLS\'s', mx(pred, ref), 0.0, 1e-6)
    elif fam == 'logit':
        ref = sm.Logit((Px.target == 0).astype(float), X_).fit(disp=0).predict()
        check.near(f'Linear nodes, no penalty: {label}: Prob[hi] is statsmodels Logit\'s', mx(pred[:, 0], ref), 0.0, 1e-5)
    else:
        ref = sm.QuantReg(Px.target, X_).fit(q=0.5).fittedvalues
        check(f'Linear nodes, no penalty: {label}: the network\'s predictions are QuantReg\'s median regression\'s (|r| smoothed)', mx(pred, ref) < 2e-3 * np.std(Px.target), True)
Mm = built(y=['three'], validation='v0', model={'t1': 0, 'l1': 2, 'penalty': 'none', 'max_iter': 5000})
Pm = Mm.Ps[0]
Xm = np.column_stack([np.ones(len(Pm.index)), Mm.design.raw(Pm.X)])
mn = sm.MNLogit(Pm.target, Xm).fit(disp=0, maxiter=500)
check.near('two Linear nodes (the levels less one), no penalty: a three-level response\'s probabilities are MNLogit\'s', mx(Mm.res['model'].predict(Mm.Z)[0], mn.predict()), 0.0, 1e-5)
Mz = built(y=['ylin'], validation='v0', model={'t1': 3, 'penalty': 'none', 'max_iter': 20000})
th = np.concatenate([np.concatenate([W.ravel(), c]) for W, c in Mz.res['model'].layers])
netz = Mz.res['net']
gz = NN.objective(th, netz, Mz.T, Mz.Z, np.arange(len(Mz.Z)), 0.0, 'none')[1]
check('without validation rows or a penalty the fit runs to the optimum: the gradient there is about 0', (Mz.res['iterations'] < 20000, float(np.max(np.abs(gz))) < 1e-4), (True, True))

# ---- the penalty path, early stopping, tours ------------------------------------------------------------------------------
r = fit(model={'t1': 4, 'tours': 3})
net = r['nets'][0]
path = net['path']
vals = [p['valid'] for p in path]
check('the penalty path starts with none, as JMP\'s search does', path[0]['lambda'], 0.0)
check('... the penalty chosen has the best validation -LogLikelihood of those tried', [p['lambda'] for p in path if p['chosen']] == [path[int(np.argmin(vals))]['lambda']], True)
check('... it stops after two penalties in a row that were no better', len(path) == len(NN.LAMBDAS) or (len(path) >= 3 and all(vals[-k] > min(vals) for k in (1, 2))), True)
check('the tour with the best validation likelihood is kept', [t['chosen'] for t in r['tours']] == [t['criterion'] == min(q['criterion'] for q in r['tours']) for t in r['tours']], True)
Mt = built(model={'t1': 4, 'tours': 3})
tr_, va_ = Mt.splits[0]
theta_k = np.concatenate([np.concatenate([W.ravel(), c]) for W, c in Mt.res['model'].layers])
check.near('the model is the chosen penalty\'s fit: its validation -LogLikelihood is the path\'s', NN.nll_of(theta_k, Mt.res['net'], Mt.T, Mt.Z, va_), [p['valid'] for p in path if p['chosen']][0], 1e-9)
# early stopping: the kept iterate is the best validation likelihood seen along the fit
seen = []
netE = NN.Net(Mt.Z.shape[1], [['tanh'] * 4], Mt.T.q)
th0 = netE.start(np.random.default_rng([SEED, 7, 0]))
orig = NN.optimize.minimize


def spy(fun, x0, **kw):
    cb = kw.get('callback')

    def wrapped(intermediate_result):
        seen.append(NN.nll_of(intermediate_result.x, netE, Mt.T, Mt.Z, va_))
        return cb(intermediate_result)
    kw['callback'] = wrapped
    return orig(fun, x0, **kw)


NN.optimize.minimize = spy
fo = NN.fit_once(netE, Mt.T, Mt.Z, tr_, va_, 0.0, 'squared', th0, 200)
NN.optimize.minimize = orig
check('early stopping: the fit keeps the iterate with the best validation likelihood of those it went through', (len(seen) > 0, math.isclose(fo['valid'], min(seen), rel_tol=1e-12)), (True, True))
check('... and stops 10 iterations after it (or at the optimum)', len(seen) - fo['kept'] <= NN.PATIENCE, True)
check('No Penalty: one fit, no penalty', [p['lambda'] for p in fit(model={'penalty': 'none'})['nets'][0]['path']], [0.0])
for pen in ('absolute', 'weight_decay'):
    rp = fit(model={'penalty': pen, 't1': 4})
    check(f'the {pen.replace("_", " ")} penalty is JMP\'s option too: its path from none', (rp.get('error'), rp['nets'][0]['path'][0]['lambda']), (None, 0.0))

# ---- KFold, a K-fold Validation column, Excluded Rows Holdback, a Validation column --------------------------------------
Mk = built(model={'method': 'kfold', 'folds': 4})
nk = len(Mk.Ps[0].index)
fk = np.empty(nk, dtype=int)
fk[np.random.default_rng(SEED).permutation(nk)] = np.arange(nk) % 4
check('KFold: the folds drawn from the seed', np.array_equal(Mk.folds, fk), True)
rk = fit(model={'method': 'kfold', 'folds': 4})
check('... the fold whose model fits every row best is the model, and that fold validates it', [f['chosen'] for f in rk['folds']] == [f['all'] == min(q['all'] for q in rk['folds']) for f in rk['folds']]
      and rk['validation']['fold'] == [f['fold'] for f in rk['folds'] if f['chosen']][0], True)
check('... the penalty chosen by the validation likelihood summed over the folds', math.isclose([p['valid'] for p in rk['nets'][0]['path'] if p['chosen']][0], sum(f['valid'] for f in rk['folds']), rel_tol=1e-9), True)
rf = fit(validation='kf')
Mf = built(validation='kf')
check('a K-fold Validation column (5 values): KFold by its folds, not random ones', (rf['validation']['method'], rf['validation']['folds'], np.array_equal(Mf.folds, Mf.Ps[0].folds)), ('folds', 5, True))
check('... each fold validates the model of the others', all(np.array_equal(va, np.flatnonzero(Mf.folds == k)) for k, (_, va) in enumerate(Mf.splits)), True)
rc = fit(validation='v')
check('a Validation column: its training, validation and test rows', (rc['validation']['method'], rc['n']), ('column', {'Training': int(np.sum(vnum == 0)), 'Validation': int(np.sum(vnum == 1)), 'Test': int(np.sum(vnum == 2))}))
held = [int(i) for i in np.flatnonzero(vnum == 2)]
re = fit(model={'method': 'excluded'}, rows=[i for i in range(n) if i not in held] + held, holdback=held)
check('Excluded Rows Holdback: the excluded rows validate, the others train', (re['validation']['method'], re['n']['Validation'], re['n']['Training']), ('excluded', len(held), n - len(held)))

# ---- boosting ----------------------------------------------------------------------------------------------------------------
rb = fit(model={'t1': 2, 'boost': 6, 'rate': 0.2})
Mb = built(model={'t1': 2, 'boost': 6, 'rate': 0.2})
kept = rb['nets'][0]['components']
check('boosting: JMP\'s name, one layer', rb['name'], 'NTanH(2)NBoost(6)')
rows_b = rb['nets'][0]['boost']
check('... base models are kept while the validation likelihood improves', all(rw['kept'] for rw in rows_b[:kept]) and (len(rows_b) == kept or not rows_b[kept]['kept']), True)
check('... each kept one bettered the validation likelihood of the ones before', all(rows_b[i]['valid'] < rows_b[i - 1]['valid'] for i in range(1, kept)), True)
mod = Mb.res['model']
check('... the model is one network: its hidden layer holds every base model\'s nodes', mod.layers[0][0].shape[1], 2 * kept)
# the base models again, from the engine's boost with the starting values fit_neural gives them
netB = NN.Net(Mb.Z.shape[1], [['tanh', 'tanh']], Mb.T.q)
bb = NN.boost(netB, Mb.T, Mb.Z, Mb.splits, 'squared', netB.start(np.random.default_rng([SEED % 2 ** 32, 7, 0])), 200, 6, 0.2, [[SEED % 2 ** 32, 7, 0, k, 0] for k in range(6)])
check('... the base models kept, each weighted by the learning rate but the last, by 1', [w_ for _, w_ in bb['parts']], [0.2] * (kept - 1) + [1.0])
by_hand = bb['offset'] + sum(w_ * netB.forward(th_, Mb.Z)[2] for th_, w_ in bb['parts'])
check('... the model\'s outputs: the start plus the weighted sum of the base models\' outputs', mx(mod.outputs(Mb.Z), by_hand) < 1e-9, True)

# ---- the Estimates: the network written out by hand ---------------------------------------------------------------------------
for label, kw in [('one layer', dict(model={'t1': 3})), ('two layers of every activation, two responses', dict(y=['y', 'three'], model={'t1': 2, 'l1': 1, 'g1': 1, 't2': 2, 'g2': 1})),
                  ('Transform Covariates, a missing value', dict(x=['x1m', 'x3', 'g'], model={'transform': True})), ('boosted, a categorical response', dict(y=['cls'], model={'t1': 2, 'boost': 4}))]:
    r = fit(**kw)
    Mx = built(**kw)
    est = {e['parameter']: e['estimate'] for e in r['nets'][0]['estimates']}
    names = r['features']
    Dx = Mx.design.raw(Mx.Ps[0].X)
    acts = [[NN.ACTIVATIONS[c] for c in code] for code in Mx.res['model'].codes]
    hn = ['H2', 'H1'] if len(acts) == 2 else ['H1']
    H = Dx
    ins = names
    for li, la in enumerate(acts):
        outs = [f'{hn[li]}_{i + 1}' for i in range(len(la))]
        A = np.column_stack([est[f'{o}:Intercept'] + sum(est[f'{o}:{a}'] * H[:, j] for j, a in enumerate(ins)) for o in outs])
        H = np.column_stack([np.tanh(A[:, i]) if a == 'tanh' else A[:, i] if a == 'linear' else np.exp(-A[:, i] ** 2) for i, a in enumerate(la)])
        ins = outs
    preds = Mx.res['model'].predict(Mx.Z)
    ok = True
    for P, b, pr in zip(Mx.Ps, Mx.T.blocks, preds):
        if b['kind'] == 'cont':
            o = P.y
            ok &= mx(est[f'{o}:Intercept'] + sum(est[f'{o}:{a}'] * H[:, j] for j, a in enumerate(ins)), pr) < 1e-9
        else:
            th_ = np.column_stack([est[f'{P.y}[{lab}]:Intercept'] + sum(est[f'{P.y}[{lab}]:{a}'] * H[:, j] for j, a in enumerate(ins)) for lab in P.labels[:-1]] + [np.zeros(len(H))])
            pp = np.exp(th_ - th_.max(axis=1, keepdims=True))
            ok &= mx(pp / pp.sum(axis=1, keepdims=True), pr) < 1e-9
    check(f'the Estimates ({label}): the network written out from them, on the design\'s own scale, gives the model\'s predictions', ok, True)

# ---- JMP's names, the settings saved before, errors ------------------------------------------------------------------------------
check('JMP\'s names of the models', [NN.name_of(NN.spec_of(m)) for m in ({}, {'t1': 2, 'l1': 1, 'g1': 1}, {'t1': 3, 't2': 2}, {'g1': 2, 'boost': 10}, {'t1': 0, 'l1': 2, 'l2': 1})],
      ['NTanH(3)', 'NTanH(2)NLinear(1)NGaussian(1)', 'NTanH(3)NTanH2(2)', 'NGaussian(2)NBoost(10)', 'NLinear(2)NLinear2(1)'])
old = NN.spec_of({'activation': 'identity', 'n1': 4, 'n2': 2})
check('a model saved with one activation (activation, n1, n2) reads as its nodes', (old['l1'], old['l2'], old['t1']), (4, 2, 0))
check('... scikit-learn\'s ReLU as TanH, with a note', (NN.spec_of({'activation': 'relu', 'n1': 3})['t1'], bool(NN.spec_of({'activation': 'relu', 'n1': 3})['notes'])), (3, True))
check('boosting takes one layer: a second is set aside, as in JMP', NN.spec_of({'t1': 2, 't2': 3, 'boost': 4})['t2'], 0)
for bad, frag in [({'t1': 0}, 'at least one node'), ({'penalty': 'lasso'}, 'unknown penalty'), ({'tours': 0}, 'Number of Tours'), ({'rate': 0, 'boost': 2}, 'Learning Rate')]:
    try:
        NN.spec_of(bad)
        msg = ''
    except ValueError as e:
        msg = str(e)
    check(f'a bad setting is refused: {frag}', frag in msg, True)

# ---- the measures, Save Columns, the profiler -------------------------------------------------------------------------------------
r = fit(y=['ym'], x=['x1m', 'gm', 'x2'], model={'t1': 3})
Mx = built(y=['ym'], x=['x1m', 'gm', 'x2'], model={'t1': 3})
Px = Mx.Ps[0]
pred = Mx.res['model'].predict(Mx.Z)[0]
meas = {m_['set']: m_ for m_ in r['responses'][0]['fit']['measures']}
for k, s_ in ((0, 'Training'), (1, 'Validation')):
    m_ = Px.sets == k
    yy = Px.target[m_]
    check.near(f'Measures of Fit: the {s_.lower()} RSquare, 1 - SSE/SST of the network\'s predictions', meas[s_]['rsquare'], 1 - np.sum((yy - pred[m_]) ** 2) / np.sum((yy - yy.mean()) ** 2), 1e-10)
check('rows with no response are left out, and said so', any('3 rows with no ym' in t for t in r['notes']), True)
sv = call('neural.save', table=T, y=['ym'], x=['x1m', 'gm', 'x2'], seed=SEED, model={'t1': 3})
sr = sv['responses'][0]
check('Save Predicteds: every row whose factors the model can take, the three with no response too', len(sr['rows']), n)
Xa, rws = Px.all_rows()
check('... the network\'s prediction of each', mx(sr['values'], Mx.res['model'].predict(Mx.design.apply(Xa))[0]) < 1e-12, True)
hv = call('neural.save', table=T, y=['ym'], x=['x1m', 'gm', 'x2'], seed=SEED, model={'t1': 3}, what='hidden')
est = {e['parameter']: e['estimate'] for e in r['nets'][0]['estimates']}
Da = Mx.design.raw(Xa)
h1 = np.tanh(est['H1_1:Intercept'] + sum(est[f'H1_1:{a}'] * Da[:, j] for j, a in enumerate(r['features'])))
check('Save Hidden Layer Values: each node\'s value, TanH of its sum (from the Estimates)', ([c['name'] for c in hv['columns']], mx(hv['columns'][0]['values'], h1) < 1e-9), (['H1_1', 'H1_2', 'H1_3'], True))
one = call('neural.save', table=T, y=['ym', 'cls'], x=['x1', 'x2'], seed=SEED, model={}, response='cls')
check('Save of one response (the Decision Threshold\'s): its Prob[] columns, named with it among several', (one['names'], len(one['prob'][0])), (['cls Prob[hi]', 'cls Prob[lo]'], 2))
pr = call('neural.profile', table=T, y=['y', 'three'], x=XS, seed=SEED, model={}, current={'x1': 0.5, 'x2': -1.0, 'g': 'b'}, grid=5)
Mp = built(y=['y', 'three'], x=XS)
Xs, _ = Mp.Ps[0].encode(pd.DataFrame({'x1': [0.5], 'x2': [-1.0], 'g': ['b']}))
pp = Mp.res['model'].predict(Mp.design.apply(Xs))
check('the profiler: each response\'s prediction at the current setting (y, then Prob[] of each level of three)', ([q['name'] for q in pr['responses']], mx([q['current']['pred'] for q in pr['responses']], [pp[0][0]] + list(pp[1][0])) < 1e-12),
      (['y', 'three Prob[L]', 'three Prob[M]', 'three Prob[H]'], True))

# ---- Save Formulas and Save Profile Formulas, in the page's formula engine ------------------------------------------------------------
NODE = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const sandbox = { console }; sandbox.self = sandbox; vm.createContext(sandbox);
for (const f of ['smui-util.js', 'smui-table.js', 'smui-formula.js']) vm.runInContext(fs.readFileSync(path.join(process.argv[1], f), 'utf8'), sandbox, { filename: f });
const SM = sandbox.SM;
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const t = new SM.Table({ name: 'data', columns: job.columns.map((c) => ({ ...c, values: c.values.map((v) => (v == null ? (c.dataType === 'numeric' ? NaN : '') : v)) })) });
const out = [];
for (const [name, e] of job.exprs) {
  try { const c = t.addColumn({ name, dataType: 'numeric', values: [] }); SM.formula.apply(t, c, e); out.push(Array.from(c.values, (x) => (typeof x === 'number' && !Number.isFinite(x) ? null : x))); }
  catch (err) { out.push({ error: String(err.message || err) }); }
}
process.stdout.write(JSON.stringify(out));
"""


def formula_columns(columns, named):
    """Formula columns [(name, formula)] added in turn to a table of these columns, as Save Formulas adds them (a
    later one may use an earlier), in smui-formula.js run by node: each column's values."""
    spec = []
    for name, vals in columns.items():
        char = any(isinstance(v, str) for v in vals)
        spec.append({'name': name, 'dataType': 'character' if char else 'numeric', 'values': [None if v is None or (isinstance(v, float) and math.isnan(v)) else v for v in vals]})
    with tempfile.TemporaryDirectory() as tmp:
        jf = os.path.join(tmp, 'job.json')
        with open(jf, 'w') as fh:
            json.dump({'columns': spec, 'exprs': named}, fh)
        out = subprocess.run(['node', '-e', NODE, JS, jf], capture_output=True, text=True, timeout=180)
    if out.returncode:
        return [{'error': out.stderr[-400:]}] * len(named)
    return json.loads(out.stdout)


def agrees(got, rows, want, tol=1e-9):
    if isinstance(got, dict):
        return got
    at = dict(zip(rows, want))
    for i, v in enumerate(got):
        w_ = at.get(i)
        if w_ is None:
            if v is not None:
                return f'row {i}: {v!r}, expected missing'
        elif v is None or not math.isclose(v, w_, rel_tol=tol, abs_tol=1e-12):
            return f'row {i}: {v!r}, expected {w_!r}'
    return True


for label, kw in [('continuous, Informative Missing', dict(y=['y'], x=['x1m', 'gm', 'x2'], model={'t1': 3})),
                  ('Informative Missing off', dict(y=['y'], x=['x1m', 'gm', 'x2'], missing='drop', model={'t1': 2, 'l1': 1})),
                  ('two layers of every activation, Transform Covariates', dict(y=['y'], x=['x1', 'x3', 'g'], model={'t1': 2, 'g1': 1, 't2': 2, 'l2': 1, 'transform': True})),
                  ('a continuous and a categorical response', dict(y=['y', 'three'], x=['x1', 'x2', 'g'], model={'t1': 3})),
                  ('boosted, two levels', dict(y=['cls'], x=['x1', 'x2', 'gm'], model={'t1': 2, 'boost': 4}))]:
    base = dict(table=T, seed=SEED, **kw)
    sv = call('neural.save', **base)
    prof = call('neural.formula', what='profile', **base)
    fmls = call('neural.formula', what='formulas', **base)
    want_cols = {}
    for s_ in sv['responses']:
        if 'values' in s_:
            want_cols[f'Predicted {s_["y"]}'] = (s_['rows'], s_['values'])
        else:
            pref = f'{s_["y"]} ' if len(kw['y']) > 1 else ''
            for j, lab in enumerate(s_['levels']):
                want_cols[f'{pref}Prob[{lab}]'] = (s_['rows'], [p[j] for p in s_['prob']])
    got = formula_columns(cols, [(c['name'], c['expr']) for c in prof['columns']])
    check(f'Save Profile Formulas: {label}: every prediction\'s formula (the hidden nodes written in) is Save Predicteds\' on every row',
          [agrees(v, *want_cols[c['name']]) for v, c in zip(got, prof['columns'])], [True] * len(prof['columns']))
    got = formula_columns(cols, [(c['name'], c['expr']) for c in fmls['columns']])
    hidden = [c for c in fmls['columns'] if c.get('hidden')]
    check(f'Save Formulas: {label}: the hidden nodes as columns of their own, the predictions from them, Save Predicteds\' on every row',
          [agrees(v, *want_cols[c['name']]) for v, c in zip(got, fmls['columns']) if not c.get('hidden')], [True] * (len(fmls['columns']) - len(hidden)))
    hv = call('neural.save', what='hidden', **base)
    hmap = {c['name']: c['values'] for c in hv['columns']}
    check(f'Save Formulas: {label}: ... each hidden column is Save Hidden Layer Values\' node', [agrees(v, hv['rows'], hmap[c['name']]) for v, c in zip(got, fmls['columns']) if c.get('hidden')], [True] * len(hidden))
tf = call('neural.formula', table=T, y=['y'], x=['x1', 'x3', 'g'], seed=SEED, model={'transform': True}, what='transformed')
st = call('neural.save', table=T, y=['y'], x=['x1', 'x3', 'g'], seed=SEED, model={'transform': True}, what='transformed')
got = formula_columns(cols, [(c['name'], c['expr']) for c in tf['columns']])
check('Save Transformed Covariates as formulas: the Johnson transforms, the design\'s on every row', [agrees(v, st['rows'], c['values']) for v, c in zip(got, st['columns'])], [True, True])

# ---- the code under a model, and every graph's code, run on a CSV export ------------------------------------------------------------
from test_predictive import check_shared_native, export_frame, joined, run_graph as run_graph_native  # noqa: E402
GTMP = tempfile.mkdtemp(prefix='smui-neural-charts-')


def run_script(script, tid):
    with tempfile.TemporaryDirectory() as tmp:
        export_frame(tid).to_csv(os.path.join(tmp, 'data.csv'), index=False)
        with open(os.path.join(tmp, 'code.py'), 'w') as fh:
            fh.write(script)
        out = subprocess.run([sys.executable, 'code.py'], cwd=tmp, capture_output=True, text=True, timeout=900)
    return out.stdout, out.stderr[-1500:]


for label, kw in [('continuous, Holdback', dict(y=['y'], x=XS, model={'t1': 3})),
                  ('two responses, two layers, Transform Covariates, a Freq column', dict(y=['y', 'three'], x=['x1', 'x3', 'g'], freq='f', model={'t1': 2, 'l1': 1, 't2': 2, 'transform': True})),
                  ('a categorical response, KFold, Robust Fit asked for', dict(y=['cls'], x=XS, model={'method': 'kfold', 'folds': 3, 'robust': True})),
                  ('boosted, a K-fold Validation column, rows left out', dict(y=['ylin'], x=XS, validation='kf', rows=list(range(20, n)), model={'t1': 2, 'boost': 3})),
                  ('Robust Fit, the Absolute penalty, a Validation column', dict(y=['ylin'], x=['x1m', 'gm'], validation='v', model={'robust': True, 'penalty': 'absolute'}))]:
    res = fit(table_name='data', **kw)
    if 'error' in res:
        check(f'code: {label}: fits', res['error'], None)
        continue
    out, err = run_script(res['script'], T)
    got = {}
    for ln in out.splitlines():
        p_ = ln.split()
        if len(p_) >= 4 and p_[1] in ('Training', 'Validation', 'Test'):
            got[(p_[0], p_[1])] = float(p_[3])
    want = {}
    for rr in res['responses']:
        for m_ in rr['fit']['measures']:
            want[(rr['y'], m_['set'])] = m_['rsquare'] if rr['kind'] == 'continuous' else m_['neg_loglik']
    check(f'code: {label}: the model\'s code runs on the CSV and prints the report\'s measures of every set', (err if not got else '', sorted(got) == sorted(want) and all(math.isclose(got[k], want[k], rel_tol=1e-6) for k in want)), ('', True))
    head = res['plots']['head_code']
    F, err = run_graph_native(head + '\n\n# ----\n' + res['nets'][0]['diagram_code'], T, GTMP)
    check(f'code: {label}: the Diagram\'s code runs', err, None)
    if F:
        ax = F['axes'][0]
        d_ = res['nets'][0]['diagram']
        check(f'code: {label}: ... a circle per hidden node, a box per X column and response', (sum(1 for p_ in ax['patches'] if p_['type'] == 'ellipse'), len(ax['bars'])),
              (sum(h['n'] for h in d_['hidden']), len(d_['inputs']) + len(d_['outputs'])))
    for rr in res['responses']:
        P_ = rr['fit']
        n_ = check_shared_native(check, f'code: {label}: {rr["y"]}', P_, T, GTMP)
        if rr['kind'] == 'continuous':
            for s_, code in P_['plots']['rbp'].items():
                F, err = run_graph_native(head + '\n\n# ----\n' + code, T, GTMP)
                check(f'code: {label}: {rr["y"]}: residual by predicted {s_}: the code runs', err, None)

sys.exit(check.done())
