#!/usr/bin/env python3
"""Analyze > Multivariate Methods > Partial Least Squares' backend
(resources/py/smui/pls.py), through registry.dispatch as the page calls it:
the fit against NIPALS written out here (Wold's PLS2: weights, scores,
loadings, deflation) and against scikit-learn's PLSRegression called
directly; the uncentred fit (the mirrored rows) against NIPALS on the raw
data; the sub-models against PLSRegression with fewer components; the
cross validation (KFold, Leave-One-Out, Holdback, a Validation column)
against refitting by hand; van der Voet's statistic and its randomization
p-value by the formula; Percent Variation Explained against the deflated
sums of squares; VIP by its formula (the mean of VIP² is 1); the scores,
DModX, DModY and T² by hand; Save; the profiler; and the Python shown
under the report run on a CSV export. Data: simulated latent-factor tables
and scikit-learn's bundled Linnerud data (read at run time).

    python3 resources/tests/smui/test_pls.py
"""
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

from backend import FAILED, Checks, call, table

check = Checks()
check('pls.py imports', 'pls' in FAILED, False)
from smui import pls as PL, predictive, registry  # noqa: E402

try:
    from scipy import stats
    from sklearn.cross_decomposition import PLSRegression
    from sklearn.datasets import load_linnerud
    from sklearn.model_selection import KFold
except ImportError:
    print('scikit-learn 1.8 is needed for these tests (Pyodide 314.0.7 has 1.8.0)')
    sys.exit(1)

PL.PROGRESS = False


def mx(a, b):
    return float(np.max(np.abs(np.asarray(a, float) - np.asarray(b, float))))


def nipals(X, Y, A, center=True, scale=True, tol=1e-12, max_iter=2000):
    """Wold's NIPALS PLS2, written out: for each factor, from the first Y
    column that is not zero, w = X'u/u'u normalized, t = Xw, c = Y't/t't,
    u = Yc/c'c until w settles (at once with one Y); the sign that makes the
    largest |w| positive (scikit-learn's convention); p = X't/t't and
    q = Y't/t't; X and Y deflated by t p' and t q'."""
    X, Y = np.array(X, float), np.array(Y, float)
    xm = X.mean(0) if center else np.zeros(X.shape[1])
    ym = Y.mean(0) if center else np.zeros(Y.shape[1])
    xs = X.std(0, ddof=1) if scale else np.ones(X.shape[1])
    ys = Y.std(0, ddof=1) if scale else np.ones(Y.shape[1])
    E, F = (X - xm) / xs, (Y - ym) / ys
    E0, F0 = E.copy(), F.copy()
    n, p = E.shape
    q = F.shape[1]
    out = {k: np.zeros(s_) for k, s_ in (('W', (p, A)), ('C', (q, A)), ('P', (p, A)), ('Q', (q, A)), ('T', (n, A)), ('U', (n, A)))}
    ssx, ssy = [float((E ** 2).sum())], [float((F ** 2).sum())]
    for a in range(A):
        u = next(col for col in F.T if np.any(np.abs(col) > np.finfo(float).eps))
        w_old = None
        for _ in range(max_iter):
            w = E.T @ u / (u @ u)
            w = w / np.linalg.norm(w)
            t = E @ w
            c = F.T @ t / (t @ t)
            u = F @ c / (c @ c)
            if q == 1 or (w_old is not None and np.sum((w - w_old) ** 2) < tol):
                break
            w_old = w
        if w[np.argmax(np.abs(w))] < 0:
            w, c = -w, -c
        t = E @ w
        u = F @ c / (c @ c)
        pp = E.T @ t / (t @ t)
        qq = F.T @ t / (t @ t)
        E = E - np.outer(t, pp)
        F = F - np.outer(t, qq)
        for k, v in (('W', w), ('C', c), ('P', pp), ('Q', qq), ('T', t), ('U', u)):
            out[k][:, a] = v
        ssx.append(float((E ** 2).sum()))
        ssy.append(float((F ** 2).sum()))
    out.update({'xm': xm, 'xs': xs, 'ym': ym, 'ys': ys, 'ssx': ssx, 'ssy': ssy, 'E0': E0, 'F0': F0, 'E': E, 'F': F})
    return out


# ---- registration --------------------------------------------------------------------------------------------------
for fn in ('pls.fit', 'pls.save', 'pls.profile', 'pls.maximize', 'pls.importance'):
    check(f'{fn} is registered and loads scikit-learn first', (fn in registry.names(), json.loads(registry.packages_for(fn))), (True, ['scikit-learn']))

# ---- a table: three latent factors behind 12 X's and 2 Y's --------------------------------------------------------------
rng = np.random.default_rng(20260927)
n, p = 90, 12
Z = rng.normal(size=(n, 3))
X = Z @ rng.normal(size=(3, p)) * rng.uniform(0.5, 30, p) + rng.uniform(-5, 50, p) + 0.4 * rng.normal(size=(n, p))
Y = np.column_stack([Z[:, 0] + 0.5 * Z[:, 1], 3 * (Z[:, 1] - Z[:, 2]) + 10]) + 0.3 * rng.normal(size=(n, 2))
xs_names = [f'x{j + 1}' for j in range(p)]
cols = {nm: list(X[:, j]) for j, nm in enumerate(xs_names)}
cols.update({'y1': list(Y[:, 0]), 'y2': list(Y[:, 1])})
vnum = rng.choice([0.0, 1.0, 2.0], n, p=[0.6, 0.25, 0.15])
cols['v'] = list(vnum)
cols['vt'] = list(np.array(['Training', 'Validation', 'Test'])[vnum.astype(int)])
x5m = X[:, 4].copy()
x5m[[3, 30]] = np.nan
cols['x5m'] = [None if np.isnan(v) else v for v in x5m]
y1m = Y[:, 0].copy()
y1m[[7]] = np.nan
cols['y1m'] = [None if np.isnan(v) else v for v in y1m]
T_ = table(cols, types={'vt': 'nominal'})
YN = ['y1', 'y2']

# ---- the fit against NIPALS written out, and scikit-learn -------------------------------------------------------------------
for label, Ys, center, scale in (('two Y\'s, centred and scaled', Y, True, True), ('one Y, centred and scaled', Y[:, :1], True, True),
                                 ('two Y\'s, centred only', Y, True, False), ('two Y\'s, not centred, scaled', Y, False, True), ('one Y, neither', Y[:, 1:], False, False)):
    A = 5
    f = PL.pls_fit(X, Ys, A, center, scale)
    ref = nipals(X, Ys, A, center, scale)
    worst = max(mx(f[k], ref[k]) / max(1.0, float(np.max(np.abs(ref[k])))) for k in ('W', 'C', 'P', 'Q', 'T', 'U'))
    check.near(f'{label}: weights, Y weights, loadings, scores are NIPALS written out', worst, 0.0, abs_=1e-9)
    for a in (1, 3, 5):
        B, Bo, b0 = PL.pls_coef(f, a)
        Wa, Pa, Qa = ref['W'][:, :a], ref['P'][:, :a], ref['Q'][:, :a]
        Bref = Wa @ np.linalg.inv(Pa.T @ Wa) @ Qa.T
        pred = b0 + X @ Bo
        pred_ref = ref['ym'] + (((X - ref['xm']) / ref['xs']) @ Bref) * ref['ys']
        check.near(f'{label}, {a} factors: the predictions are NIPALS\'s B = W(P\'W)⁻¹Q\'', mx(pred, pred_ref) / float(np.ptp(Ys)), 0.0, abs_=1e-9)
    if center:
        sk = PLSRegression(n_components=A, scale=scale, tol=1e-12, max_iter=2000).fit(X, Ys)
        B, Bo, b0 = PL.pls_coef(f, A)
        check.near(f'{label}: the original-scale coefficients are PLSRegression\'s coef_', mx(Bo.T, sk.coef_), 0.0, abs_=1e-10 * float(np.max(np.abs(sk.coef_))))
        check.near(f'{label}: and so are its predictions', mx(b0 + X @ Bo, sk.predict(X).reshape(len(X), -1)), 0.0, abs_=1e-9)
        check.near(f'{label}: the scores of the rows are its transform()', mx(PL.pls_scores(f, A, X)[0], sk.transform(X)), 0.0, abs_=1e-9)
        for a in (1, 2, 4):
            ska = PLSRegression(n_components=a, scale=scale, tol=1e-12, max_iter=2000).fit(X, Ys)
            check.near(f'{label}: the first {a} factors of 5 are PLSRegression(n_components={a})', mx(PL.pls_coef(f, a)[1].T, ska.coef_), 0.0, abs_=1e-9 * float(np.max(np.abs(ska.coef_))))
    else:
        check.near(f'{label}: no intercept without Centering', mx(PL.pls_coef(f, A)[2], 0.0), 0.0, abs_=0.0)
    Tr, Ur = PL.pls_scores(f, A, X, Ys)
    check.near(f'{label}: the Y scores of the rows by the deflation are the fit\'s', mx(Ur, f['U']) / max(1.0, float(np.max(np.abs(f['U'])))), 0.0, abs_=1e-9)

# scikit-learn's default tolerance leaves the weights of two Y's good to about 1e-3
loose = PLSRegression(n_components=3).fit(X, Y)
tight = PL.pls_fit(X, Y, 3)
check('scikit-learn\'s default tol (1e-6 on the squared change) differs from a converged NIPALS; tol=1e-12 does not', (mx(loose.x_weights_, tight['W']) > 1e-9, mx(nipals(X, Y, 3)['W'], tight['W']) < 1e-9), (True, True))

# the Linnerud data (scikit-learn's bundled copy, read at run time): three exercises, three measurements
ln = load_linnerud()
Xl, Yl = np.asarray(ln.data, float), np.asarray(ln.target, float)
fl = PL.pls_fit(Xl, Yl, 2)
skl = PLSRegression(n_components=2, tol=1e-12, max_iter=2000).fit(Xl, Yl)
check.near('Linnerud, 2 factors: coefficients are PLSRegression\'s', mx(PL.pls_coef(fl, 2)[1].T, skl.coef_), 0.0, abs_=1e-10)
check.near('Linnerud: the X scores are its x_scores_', mx(fl['T'], skl.x_scores_), 0.0, abs_=1e-10)
refl = nipals(Xl, Yl, 2)
check.near('Linnerud: and NIPALS written out', mx(fl['W'], refl['W']) + mx(fl['Q'], refl['Q']), 0.0, abs_=1e-9)

# ---- Percent Variation Explained, VIP ------------------------------------------------------------------------------------------
f = PL.pls_fit(X, Y, 6)
ref = nipals(X, Y, 6)
xe, ye, vip = PL.pls_summary(f, 6)
check.near('X Effect of each factor = the drop in the deflated X\'s sum of squares, in %', mx(xe, 100 * -np.diff(ref['ssx']) / ref['ssx'][0]), 0.0, abs_=1e-9)
check.near('Y Effect = the drop in the deflated Y\'s sum of squares, in %', mx(ye, 100 * -np.diff(ref['ssy']) / ref['ssy'][0]), 0.0, abs_=1e-9)
check.near('Cumulative Y = the R² of the centred and scaled Y\'s on the 6 factors, in %', float(np.sum(ye)), 100 * (1 - float(((ref['F0'] - ref['T'] @ ref['Q'].T) ** 2).sum()) / float((ref['F0'] ** 2).sum())), 1e-9)
ssy_a = (ref['T'] ** 2).sum(0) * (ref['Q'] ** 2).sum(0)
vip_ref = np.sqrt(p * np.array([np.sum(ssy_a * ref['W'][j] ** 2 / (ref['W'] ** 2).sum(0)) for j in range(p)]) / ssy_a.sum())
check.near('VIP by its formula √(p Σ SSYₐ w²ⱼₐ/‖wₐ‖² / Σ SSYₐ)', mx(vip, vip_ref), 0.0, abs_=1e-10)
check.near('the mean of VIP² is 1', float(np.mean(vip ** 2)), 1.0, 1e-12)

# ---- the scores of other rows, the distances and T² ---------------------------------------------------------------------------
tr = vnum == 0
f = PL.pls_fit(X[tr], Y[tr], 3)
ref = nipals(X[tr], Y[tr], 3)
Tall, Uall = PL.pls_scores(f, 3, X, Y)
Xc = (X - ref['xm']) / ref['xs']
Yc = (Y - ref['ym']) / ref['ys']
R = ref['W'] @ np.linalg.inv(ref['P'].T @ ref['W'])
check.near('X scores of any row: its centred and scaled X\'s times W(P\'W)⁻¹', mx(Tall, Xc @ R), 0.0, abs_=1e-9)
Ud = np.zeros((n, 3))
Fd = Yc.copy()
for a in range(3):
    c = ref['C'][:, a]
    Ud[:, a] = Fd @ c / (c @ c)
    Fd = Fd - np.outer((Xc @ R)[:, a], ref['Q'][:, a])
check.near('Y scores of any row: its deflated Y\'s times c/c\'c', mx(Uall, Ud), 0.0, abs_=1e-9)
dmx, dmy, t2 = PL.pls_distances(f, 3, X, Y, tr)
ntr = int(tr.sum())
E = Xc - (Xc @ R) @ ref['P'].T
F = Yc - (Xc @ R) @ ref['Q'].T
corr = np.where(tr, math.sqrt(ntr / (ntr - 3 - 1)), 1.0)
check.near('DModX = √(Σ e²/(p − k)), times √(n/(n − k − 1)) for training rows', mx(dmx, np.sqrt((E ** 2).sum(1) / (p - 3)) * corr), 0.0, abs_=1e-10)
check.near('DModY = √(Σ f²/q), the same factor', mx(dmy, np.sqrt((F ** 2).sum(1) / 2) * corr), 0.0, abs_=1e-10)
s2 = (ref['T'] ** 2).sum(0) / (ntr - 1)
check.near('T² = Σ tₐ²/sₐ², sₐ² the training variance of factor a', mx(t2, ((Xc @ R) ** 2 / s2).sum(1)), 0.0, abs_=1e-9)
check.near('the training rows\' T² average (n − 1)/n × k', float(np.mean(t2[tr])), (ntr - 1) / ntr * 3, 1e-9)

# ---- cross validation ---------------------------------------------------------------------------------------------------------
r = call('pls.fit', table=T_, y=YN, x=xs_names, method='kfold', folds=5, factors=8, seed=13)
ysd = Y.std(0, ddof=1)
E_ref = [np.zeros((n, 2)) for _ in range(9)]
for tr_i, te_i in KFold(n_splits=5, shuffle=True, random_state=13).split(X):
    for a in range(9):
        if a == 0:
            pr_ = np.repeat(Y[tr_i].mean(0, keepdims=True), len(te_i), axis=0)
        else:
            pr_ = PLSRegression(n_components=a, tol=1e-12, max_iter=2000).fit(X[tr_i], Y[tr_i]).predict(X[te_i])
        E_ref[a][te_i] = (Y[te_i] - pr_) / ysd
rm_ref = [math.sqrt(np.mean(e ** 2)) for e in E_ref]
check('KFold: a line for 0 to 8 factors', [row['factors'] for row in r['cv']['rows']], list(range(9)))
check.near('KFold 5 (scikit-learn KFold, shuffled with the seed): Root Mean PRESS = refitting each fold by hand', mx([row['rmpress'] for row in r['cv']['rows']], rm_ref), 0.0, abs_=1e-9)
best = int(np.argmin(rm_ref))
check('the fit takes the number with the minimum Root Mean PRESS', (r['cv']['best'], r['factors']), (best, max(1, best)))
check('the title is JMP\'s', r['cv']['title'], 'KFold Cross Validation with K=5 and Method=NIPALS')
signs = np.random.default_rng(13).choice([-1.0, 1.0], size=(1000, n))
for a in [k_ for k_ in (1, 2, 3, 5) if k_ != best]:
    D = E_ref[a] ** 2 - E_ref[best] ** 2
    d = D.sum(0)
    S = D.T @ D
    C = float(d @ np.linalg.solve(S, d))
    sim = signs @ D
    Cs = np.array([s_ @ np.linalg.solve(S, s_) for s_ in sim])
    row = r['cv']['rows'][a]
    check.near(f'van der Voet T² for {a} factors: d\'S⁻¹d, d the sums of D = R²ₐ − R²_best, S = D\'D', row['t2'], C, 1e-8)
    check.near('... its p-value: the share of 1000 random swaps (seed) with a larger C', row['p'], float(np.mean(Cs > C)), abs_=1e-12)
check('... and 1 at the minimum', (r['cv']['rows'][best]['t2'], r['cv']['rows'][best]['p']), (0.0, 1.0))
fewest = next((a for a in range(1, 9) if r['cv']['rows'][a]['p'] > 0.10), None)
check('van der Voet\'s rule: the fewest factors with Prob > T² above 0.10', r['cv']['fewest'], fewest)
one = call('pls.fit', table=T_, y=['y1'], x=xs_names, method='loo', factors=4, seed=2)
E1 = [np.zeros(n) for _ in range(5)]
sd1 = Y[:, 0].std(ddof=1)
for i in range(n):
    k_ = np.arange(n) != i
    E1[0][i] = (Y[i, 0] - Y[k_, 0].mean()) / sd1
    for a in range(1, 5):
        E1[a][i] = (Y[i, 0] - PLSRegression(n_components=a).fit(X[k_], Y[k_, 0]).predict(X[[i]])[0]) / sd1
check.near('Leave-One-Out: Root Mean PRESS = each row predicted without it, by hand', mx([row_['rmpress'] for row_ in one['cv']['rows']], [math.sqrt(np.mean(e ** 2)) for e in E1]), 0.0, abs_=1e-9)
b1 = int(np.argmin([np.mean(e ** 2) for e in E1]))
D = E1[1] ** 2 - E1[b1] ** 2
check.near('one Y: van der Voet\'s C = (Σ D)²/Σ D²', one['cv']['rows'][1]['t2'], float(D.sum() ** 2 / (D ** 2).sum()) if b1 != 1 else 0.0, 1e-9)
rh = call('pls.fit', table=T_, y=YN, x=xs_names, method='holdback', holdback=0.3, factors=6, seed=21)
Ph = predictive.prepare(T_, 'y1', xs_names + ['y2'], None, portion=0.3, seed=21, missing='drop', categorical_y=False)
trh = Ph.sets == 0
fh = PLSRegression(n_components=6, tol=1e-12, max_iter=2000).fit(X[trh], Y[trh])
Eh = (Y[~trh] - fh.predict(X[~trh])) / Y[trh].std(0, ddof=1)
check('Holdback 0.3: the predictive platforms\' seeded portion', (rh['sets']['Validation'], rh['n_train']), (int(round(0.3 * n)), n - int(round(0.3 * n))))
check.near('Holdback: Root Mean PRESS of the held-back rows (6 factors) by hand', rh['cv']['rows'][6]['rmpress'], math.sqrt(np.mean(Eh ** 2)), 1e-9)
check('Holdback\'s title', rh['cv']['title'], 'Holdback Validation with Holdback=0.3 and Method=NIPALS')
for vcol in ('v', 'vt'):
    rv = call('pls.fit', table=T_, y=YN, x=xs_names, validation=vcol, factors=6, seed=1)
    fv = PLSRegression(n_components=rv['factors'], tol=1e-12, max_iter=2000).fit(X[vnum == 0], Y[vnum == 0])
    check(f'a Validation column ({"numeric" if vcol == "v" else "Training/Validation/Test"}): its sets', (rv['method'], rv['sets']), ('column', {'Training': int((vnum == 0).sum()), 'Validation': int((vnum == 1).sum()), 'Test': int((vnum == 2).sum())}))
    check.near(f'... the model is fitted to its training rows ({vcol})', mx(np.array(rv['coef_orig']).T, fv.coef_), 0.0, abs_=1e-9 * float(np.max(np.abs(fv.coef_))))
rn_ = call('pls.fit', table=T_, y=YN, x=xs_names, method='none', factors=4, seed=1)
check('None: the Initial Number of Factors, no cross validation', (rn_['factors'], rn_['cv']), (4, None))
check('None with 15 asked of 12 X\'s: as many as the X\'s allow', call('pls.fit', table=T_, y=YN, x=xs_names, method='none', seed=1)['factors'], 12)

# ---- the report's tables against the fit ----------------------------------------------------------------------------------------
f4 = PL.pls_fit(X, Y, 4)
xe, ye, vip = PL.pls_summary(f4, 4)
B, Bo, b0 = PL.pls_coef(f4, 4)
check.near('Percent Variation Explained: X Effect and Cumulative Y', mx([q_['x'] for q_ in rn_['percent']], xe) + abs(rn_['percent'][-1]['cumy'] - float(ye.sum())), 0.0, abs_=1e-9)
check.near('Model Coefficients for Centered and Scaled Data', mx(rn_['coef'], B), 0.0, abs_=1e-10)
check.near('Model Coefficients for Original Data with the intercepts', mx(rn_['coef_orig'], Bo) + mx(rn_['intercept'], b0), 0.0, abs_=1e-9)
check.near('VIP', mx(rn_['vip'], vip), 0.0, abs_=1e-12)
check('X and Y loadings, one column per factor', (np.array(rn_['x_loadings']).shape, np.array(rn_['y_loadings']).shape), ((12, 4), (2, 4)))
check.near('the X-Y scores are the rows\' t and u', mx(np.array(rn_['scores']['t']), f4['T']) + mx(np.array(rn_['scores']['u']), f4['U']), 0.0, abs_=1e-9)
check.near('the T² limit: ((n − 1)²/n) Beta(0.95; k/2, (n − k − 1)/2)', rn_['ucl'], (n - 1) ** 2 / n * stats.beta.ppf(0.95, 2, (n - 4 - 1) / 2), 1e-12)
check('with fewer factors than X\'s there is a DModX', rn_['dmodx_ok'], True)
rall = call('pls.fit', table=T_, y=YN, x=xs_names[:3], method='none', factors=3, seed=1)
check('with as many factors as X\'s the X\'s are reproduced: no DModX', (rall['dmodx_ok'], all(v is None for v in rall['dist']['dmodx'])), (False, True))

# ---- the rows: missing values, a row list, errors ----------------------------------------------------------------------------------
rm_ = call('pls.fit', table=T_, y=['y1m', 'y2'], x=xs_names[:4] + ['x5m'], method='none', factors=2, seed=1)
check('rows missing a Y or an X are left out and said so', (rm_['n'], any('3 rows missing a Y or an X' in t for t in rm_['notes'])), (n - 3, True))
rr = call('pls.fit', table=T_, y=YN, x=xs_names, method='none', factors=2, rows=list(range(0, 90, 3)), seed=1)
check('a row list (a By group) limits the fit', (rr['n'], rr['scores']['rows'][:3]), (30, [0, 3, 6]))
check('a column in both Y and X: an error that says so', 'both a Y and an X' in call('pls.fit', table=T_, y=['y1'], x=['y1', 'x1']).get('error', ''), True)
check('more folds than rows: an error', 'folds' in call('pls.fit', table=T_, y=YN, x=xs_names, method='kfold', folds=10, rows=list(range(8))).get('error', ''), True)
check('a Holdback that leaves no validation rows: an error', 'error' in call('pls.fit', table=T_, y=YN, x=xs_names, method='holdback', holdback=0.001, rows=list(range(20))), True)

# ---- Save and the profiler ------------------------------------------------------------------------------------------------------
sv = call('pls.save', table=T_, y=YN, x=xs_names[:4] + ['x5m'], method='none', factors=3, rows=list(range(60)), what='pred', seed=1)
okx = ~np.isnan(x5m)
Xs5 = np.column_stack([X[:, :4], x5m])
fs = PL.pls_fit(Xs5[:60][okx[:60]], Y[:60][okx[:60]], 3)
Bs, Bos, b0s = PL.pls_coef(fs, 3)
check('Save Predicteds: every row of the table with every X (the report\'s rows or not)', (sv['rows'], sv['names']), (np.flatnonzero(okx).tolist(), ['Predicted y1', 'Predicted y2']))
check.near('... the model\'s predictions', mx(np.array(sv['values']).T, b0s + Xs5[okx] @ Bos), 0.0, abs_=1e-9)
sx = call('pls.save', table=T_, y=YN, x=xs_names[:4] + ['x5m'], method='none', factors=3, rows=list(range(60)), what='xscores', seed=1)
check.near('Save X Scores: X Score 1..3 of every row with its X\'s', mx(np.array(sx['values']).T, PL.pls_scores(fs, 3, Xs5[okx])[0]), 0.0, abs_=1e-9)
sy = call('pls.save', table=T_, y=YN, x=xs_names[:4] + ['x5m'], method='none', factors=3, rows=list(range(60)), what='yscores', seed=1)
check('Save Y Scores: the rows with every Y and X', (sy['names'], sy['rows']), (['Y Score 1', 'Y Score 2', 'Y Score 3'], np.flatnonzero(okx).tolist()))
pr = call('pls.profile', table=T_, y=YN, x=xs_names[:4] + ['x5m'], method='none', factors=3, rows=list(range(60)), seed=1, grid=5)
cur = np.array([f_['current'] for f_ in pr['factors']])
g = np.linspace(pr['factors'][2]['min'], pr['factors'][2]['max'], 5)
Xg = np.repeat(cur[None, :], 5, axis=0)
Xg[:, 2] = g
check('the profiler: a response per Y', [r_['name'] for r_ in pr['responses']], YN)
check.near('... a trace is the model\'s prediction over the factor', mx(pr['responses'][1]['traces'][2]['pred'], (b0s + Xg @ Bos)[:, 1]), 0.0, abs_=1e-9)
check('... the current values start at the training means', bool(np.allclose(cur, Xs5[:60][okx[:60]].mean(0))), True)

# ---- the Python under the report, on a CSV export ---------------------------------------------------------------------------------
work = tempfile.mkdtemp()
pd.DataFrame(cols).to_csv(os.path.join(work, 'data.csv'), index=False)
DUMP = '''
import json
out = {"a": int(a), "B": B.tolist(), "Bo": Bo.tolist(), "b0": b0.tolist(), "xe": xe.tolist(), "ye": ye.tolist(), "vip": vip.tolist(),
       "dmody": dmody.tolist(), "t2": t2.tolist(), "ucl": float(ucl), "T": T.tolist(), "U": U.tolist(), "rows": d.index.tolist()}
if "rmpress" in globals():
    out["rmpress"] = [float(v) for v in rmpress]; out["vdv"] = vdv
print("JSON" + json.dumps(out))
'''
for label, kw in (('KFold, two Y\'s', {'y': YN, 'x': xs_names, 'method': 'kfold', 'factors': 6}),
                  ('Leave-One-Out, one Y, a row list', {'y': ['y1'], 'x': xs_names, 'method': 'loo', 'factors': 4, 'rows': list(range(10, 80))}),
                  ('Holdback 0.25, missing values', {'y': ['y1m', 'y2'], 'x': xs_names[:4] + ['x5m'], 'method': 'holdback', 'holdback': 0.25, 'factors': 4}),
                  ('a Training/Validation/Test column', {'y': YN, 'x': xs_names, 'validation': 'vt', 'factors': 5}),
                  ('None, not centred, not scaled', {'y': YN, 'x': xs_names, 'method': 'none', 'factors': 3, 'center': False, 'scale': False})):
    r = call('pls.fit', table=T_, seed=77, table_name='data', **kw)
    p_ = subprocess.run([sys.executable, '-c', r['code'] + '\n' + DUMP], cwd=work, capture_output=True, text=True, timeout=600)
    if p_.returncode:
        print(p_.stderr[-2500:])
        check(f'the code runs: {label}', p_.returncode, 0)
        continue
    got = json.loads([ln_ for ln_ in p_.stdout.splitlines() if ln_.startswith('JSON')][-1][4:])
    tr_ = np.array(r['dist']['set']) == 0
    worst = max(mx(got['B'], r['coef']), mx(got['Bo'], r['coef_orig']) / max(1, float(np.max(np.abs(r['coef_orig'])))), mx(got['b0'], r['intercept']) / max(1, float(np.max(np.abs(r['intercept'])))),
                mx(got['xe'], [q_['x'] for q_ in r['percent']]), mx(got['ye'], [q_['y'] for q_ in r['percent']]), mx(got['vip'], r['vip']),
                mx(got['dmody'], r['dist']['dmody']), mx(got['t2'], r['dist']['t2']), abs(got['ucl'] - r['ucl']), mx(got['T'], r['scores']['t']), mx(got['U'], r['scores']['u']))
    if r['cv']:
        worst = max(worst, mx(got['rmpress'], [row['rmpress'] for row in r['cv']['rows']]), mx([v[0] for v in got['vdv']], [row['t2'] for row in r['cv']['rows']]),
                    mx([v[1] for v in got['vdv']], [row['p'] for row in r['cv']['rows']]))
    check(f'the code fits {r["factors"]} factors to the same rows: {label}', (got['a'], got['rows']), (r['factors'], r['dist']['rows']))
    check.near(f'... and prints the report\'s numbers: {label}', worst, 0.0, abs_=1e-9)

sys.exit(check.done())
