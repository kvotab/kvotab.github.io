#!/usr/bin/env python3
"""Analyze > Predictive Modeling > K Nearest Neighbors, Naive Bayes and
Support Vector Machines (resources/py/smui/learners.py), through
registry.dispatch as the page calls them, checked against scikit-learn
called directly with the same settings:

  K Nearest Neighbors      every K's misclassification rate and RASE on each
                           set against KNeighborsClassifier / Regressor(k)
                           .predict (predict(None) for the training rows,
                           which leaves each row out), the standardization,
                           the best K, the vote-tie rule, the probabilities
                           (never 0 or 1), Save Predicteds and Save Near
                           Neighbor Rows against kneighbors, the profiler
  Naive Bayes              the probabilities against GaussianNB and
                           CategoricalNB combined (the class shares once),
                           with weights and another alpha; a missing value
                           left out, worked by hand; Save; the profiler
  Support Vector Machines  SVC(probability=True) and SVR on the standardized
                           factors, the tuning design against a brute-force
                           search (validation rows, and 5-fold
                           cross-validation), the decision boundary against
                           decision_function, the seed, Save, the profiler

and by running the Python shown under each report on a CSV export of the
table: it prints the report's numbers.

    python3 resources/tests/smui/test_learners.py
"""
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

from backend import FAILED, Checks, call, table

check = Checks()
check('learners.py imports', 'learners' in FAILED, False)
from smui import predictive as pv, registry  # noqa: E402

try:
    from sklearn.model_selection import KFold, StratifiedKFold
    from sklearn.naive_bayes import CategoricalNB, GaussianNB
    from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
    from sklearn.svm import SVC, SVR
    from sklearn import metrics
except ImportError:
    print('scikit-learn 1.8 is needed for these tests (Pyodide 314.0.7 has 1.8.0)')
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.abspath(os.path.join(HERE, '..', '..', 'py'))


def mx(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.max(np.abs(a - b))) if a.size else 0.0


# ---- the registry ------------------------------------------------------------------------------------------------------
NAMES = ['knn.fit', 'knn.save', 'knn.neighbors', 'knn.profile', 'knn.maximize', 'knn.importance',
         'naivebayes.fit', 'naivebayes.save', 'naivebayes.profile', 'svm.fit', 'svm.boundary', 'svm.save', 'svm.profile']
check('every entry point is registered', [nm for nm in NAMES if nm not in registry.names()], [])
check('... and each needs scikit-learn (the worker loads it on the first call)', sorted({registry.packages_for(nm) for nm in NAMES}), ['["scikit-learn"]'])
out = subprocess.run([sys.executable, '-c', f'import sys; sys.path.insert(0, {PY!r}); import smui.learners; print("sklearn" in sys.modules)'], capture_output=True, text=True)
check('importing the module does not import scikit-learn (the page loads it at the start)', out.stdout.strip(), 'False')

# ---- the data ----------------------------------------------------------------------------------------------------------
rng = np.random.default_rng(20260927)
n = 240
x1 = rng.normal(10, 3, n)
x2 = rng.uniform(0, 1, n)
g = rng.choice(['a', 'b', 'c'], n, p=[0.5, 0.3, 0.2])
lin = 0.6 * (x1 - 10) - 2.5 * (x2 - 0.5) + np.where(g == 'b', 1.2, np.where(g == 'c', -0.8, 0.0))
cls = np.where(lin + rng.normal(0, 1.2, n) > 0, 'high', 'low')
three = np.where(lin < -0.9, 'lo', np.where(lin < 0.9, 'mid', 'hi'))
three = np.where(rng.random(n) < 0.12, rng.choice(['lo', 'mid', 'hi'], n), three)
yc = 2 + 0.8 * x1 - 3 * np.sin(4 * x2) + np.where(g == 'b', 1.5, 0.0) + rng.normal(0, 0.8, n)
w = rng.uniform(0.5, 2.0, n).round(3)
fq = rng.integers(1, 4, n).astype(float)
vnum = rng.choice([0.0, 1.0, 2.0], n, p=[0.6, 0.25, 0.15])
vtxt = np.array(['Training', 'Validation', 'Test'])[vnum.astype(int)]
x1m = x1.copy()
x1m[rng.choice(n, 14, replace=False)] = np.nan
gm = g.astype(object).copy()
gm[rng.choice(n, 10, replace=False)] = None
cols = {'x1': list(x1), 'x2': list(x2), 'g': list(g), 'cls': list(cls), 'three': list(three), 'yc': list(yc), 'w': list(w), 'f': list(fq),
        'v': list(vnum), 'vt': list(vtxt), 'x1m': [None if np.isnan(v) else v for v in x1m], 'gm': list(gm)}
TYPES = {'g': 'nominal', 'cls': 'nominal', 'three': 'ordinal', 'vt': 'nominal', 'gm': 'nominal'}
LEVELS = {'three': ['lo', 'mid', 'hi'], 'cls': ['high', 'low'], 'g': ['a', 'b', 'c'], 'gm': ['a', 'b', 'c']}
T = table(cols, types=TYPES, levels=LEVELS)


def zof(P):
    """The factors standardized as the report says: a continuous factor by the
    training rows' mean and standard deviation, 0/1 columns as they are."""
    cont = [P.groups[e['name']][0] for e in P.enc if e['type'] == 'continuous']
    Xt = P.X[P.train()][:, cont]
    center, scale = np.zeros(P.X.shape[1]), np.ones(P.X.shape[1])
    center[cont] = Xt.mean(0)
    scale[cont] = Xt.std(0, ddof=1)
    return (P.X - center) / scale, center, scale


def at_rows(saved, rows):
    """The positions in a Save result of the given table rows."""
    pos = {rr: i for i, rr in enumerate(saved['rows'])}
    return [pos[int(rr)] for rr in rows]


# =======================================================================================================================
# K NEAREST NEIGHBORS
# =======================================================================================================================
r = call('knn.fit', table=T, y='cls', x=['x1', 'x2', 'g'], k=10, validation='v', seed=1)
check('knn.fit: no error, a categorical response, K = 10', (r.get('error'), r['kind'], r['k']), (None, 'categorical', 10))
P = pv.prepare(T, 'cls', ['x1', 'x2', 'g'], validation='v')
Z, _, _ = zof(P)
tr = P.train()
check('the continuous factors are standardized by the training rows (mean 0, SD 1 there); the level columns stay 0/1',
      (bool(np.allclose(Z[tr][:, [0, 1]].mean(0), 0, atol=1e-12)), bool(np.allclose(Z[tr][:, [0, 1]].std(0, ddof=1), 1)), bool(np.array_equal(Z[:, 2:], P.X[:, 2:]))), (True, True, True))
check('the report names the standardized factors', r['scaled'], ['x1', 'x2'])


def ties(P, seed, rows=None):
    """The uniform numbers that break a tied vote, by the table's row number: default_rng([seed, 7]), a row and level each."""
    rows = P.index if rows is None else np.asarray(rows)
    return np.random.default_rng([seed, 7]).random((int(max(rows.max() + 1, len(cols[next(iter(cols))]))), len(P.levels)))[rows]


def knn_pred(k, Z, P, reg=False, seed=1):
    """scikit-learn's own predictions: training rows by predict(None) (a row is not its own neighbour); a tied vote
    (scikit-learn gives it to the first level) broken instead by the seeded numbers, the tied level with the largest."""
    tr = P.train()
    m = (KNeighborsRegressor if reg else KNeighborsClassifier)(n_neighbors=k).fit(Z[tr], P.target[tr])
    if reg:
        pred = np.empty(len(Z), dtype=float)
        pred[tr] = m.predict(None)
        if (~tr).any():
            pred[~tr] = m.predict(Z[~tr])
        return pred, m
    votes = np.empty((len(Z), len(P.levels)))
    votes[tr] = np.round(m.predict_proba(None) * k)
    if (~tr).any():
        votes[~tr] = np.round(m.predict_proba(Z[~tr]) * k)
    top = votes == votes.max(1, keepdims=True)
    return np.argmax(np.where(top, ties(P, seed), -1.0), 1), m


worst = {0: 0.0, 1: 0.0, 2: 0.0}
for row in r['path']['rows']:
    pred, _ = knn_pred(row['k'], Z, P)
    for s in (0, 1, 2):
        ms = P.sets == s
        worst[s] = max(worst[s], abs(row[f'rate{s}'] - float(np.mean(pred[ms] != P.target[ms]))), 0.0 if row[f'miss{s}'] == int(np.sum(pred[ms] != P.target[ms])) else 1.0)
for s in (0, 1, 2):
    check(f'every K: the {pv.SETS[s]} misclassification rate and count = KNeighborsClassifier(n_neighbors=K).predict{"(None), each row left out" if s == 0 else ""}, a tied vote broken at random from the seed', worst[s], 0.0)
tie_rows = sum(int(np.sum(np.sum(np.round(knn_pred(k_, Z, P)[1].predict_proba(None) * k_) == np.round(knn_pred(k_, Z, P)[1].predict_proba(None) * k_).max(1, keepdims=True), 1) > 1)) for k_ in (2, 4, 6))
check('... and there were tied votes to break (even K)', tie_rows > 0, True)
rates = [row['rate1'] for row in r['path']['rows']]
check('the best K: the smallest validation rate (the smallest K of equal ones)', r['best'], int(np.argmin(rates)) + 1)
check('with no chosen K the best is shown', r['chosen'], r['best'])
Mk = {m_['set']: m_ for m_ in r['fit']['measures']}
check.near('the shown fit\'s validation misclassification rate is the best K\'s', Mk['Validation']['misclassification'], rates[r['best'] - 1], abs_=1e-15)
r5 = call('knn.fit', table=T, y='cls', x=['x1', 'x2', 'g'], k=10, validation='v', seed=1, chosen=5)
check('chosen = 5: the fit of K = 5, the best unchanged', (r5['chosen'], r5['best']), (5, r['best']))
M5 = {m_['set']: m_ for m_ in r5['fit']['measures']}
check.near('... its training misclassification = K = 5\'s in the table', M5['Training']['misclassification'], r['path']['rows'][4]['rate0'], abs_=1e-15)
pred5, m5 = knn_pred(5, Z, P)
votes = np.empty((len(Z), 2))
votes[tr] = m5.predict_proba(None) * 5
votes[~tr] = m5.predict_proba(Z[~tr]) * 5
sv = call('knn.save', table=T, y='cls', x=['x1', 'x2', 'g'], k=10, validation='v', seed=1, chosen=5)
prob = np.array(sv['prob'])
at = at_rows(sv, P.index)
check.near('Save Predicteds: each level\'s share of the K votes with a prior of 1/L, (votes + 1/L)/(K + 1)', mx(prob[at], (votes + 0.5) / 6), 0.0, abs_=1e-15)
check('... never 0 or 1', (float(prob.min()) > 0, float(prob.max()) < 1), (True, True))
check('... the most likely level is scikit-learn\'s predict, a training row left out of its own vote (a tie at random, as in the report)', [P.labels.index(v) for v in np.array(sv['most_likely'])[at]], pred5.tolist())
check('... for every row of the table, named as JMP names them', (len(sv['rows']), sv['names'], sv['most_name'], sv['k']), (n, ['Prob[high]', 'Prob[low]'], 'Most Likely cls', 5))
# a row outside the report (a By group, an exclusion) is predicted from the report's training rows
sub = [i for i in range(n) if i % 4]
Ps = pv.prepare(T, 'cls', ['x1', 'x2', 'g'], validation='v', rows=sub)
Zs, cs, ss = zof(Ps)
svs = call('knn.save', table=T, y='cls', x=['x1', 'x2', 'g'], rows=sub, k=10, validation='v', seed=1, chosen=3)
outside = [i for i in range(n) if not i % 4]
ms3 = KNeighborsClassifier(n_neighbors=3).fit(Zs[Ps.train()], Ps.target[Ps.train()])
Xo = (Ps.encode(pd.DataFrame({c: pd.Series(cols[c], dtype=object if c == 'g' else float) for c in ['x1', 'x2', 'g']}).iloc[outside])[0] - cs) / ss
check.near('rows outside the report: (votes + 1/L)/(K + 1) of their nearest training rows', mx(np.array(svs['prob'])[at_rows(svs, outside)], (ms3.predict_proba(Xo) * 3 + 0.5) / 4), 0.0, abs_=1e-15)
# Save Near Neighbor Rows
nb = call('knn.neighbors', table=T, y='cls', x=['x1', 'x2', 'g'], k=10, validation='v', seed=1)
m10 = KNeighborsClassifier(n_neighbors=10).fit(Z[tr], P.target[tr])
ind = np.empty((len(Z), 10), dtype=int)
ind[tr] = m10.kneighbors(return_distance=False)
ind[~tr] = m10.kneighbors(Z[~tr], return_distance=False)
want = P.index[tr][ind] + 1
near = np.array(nb['near']).T
check('Save Near Neighbor Rows: K columns RowNear 1 … RowNear K', nb['names'], [f'RowNear {j}' for j in range(1, 11)])
check('... the row numbers (from 1) of each row\'s K nearest training rows, nearest first (kneighbors)', near[at_rows(nb, P.index)].tolist(), want.tolist())
check('... a training row is not among its own neighbours', bool(np.all(near[at_rows(nb, P.index[tr])] != (P.index[tr] + 1)[:, None])), True)
# the vote-tie rule, on a table made for it: a validation row halfway between an 'A' row and a 'B' row, K = 2
tt = table({'x': [0.0, 1.0, 5.0, 6.0, 0.5, 5.5], 'c': ['B', 'A', 'B', 'A', 'A', 'B'], 'v': [0, 0, 0, 0, 1, 1]}, types={'c': 'nominal'}, levels={'c': ['B', 'A']})
rt_ = call('knn.fit', table=tt, y='c', x=['x'], k=2, validation='v', seed=1, chosen=2)
svt = call('knn.save', table=tt, y='c', x=['x'], k=2, validation='v', seed=1, chosen=2)
Ptt = pv.prepare(tt, 'c', ['x'], validation='v')
u_ = np.random.default_rng([1, 7]).random((6, 2))
check('a tied vote goes to one of the tied levels at random, from the seed (JMP breaks ties at random): the level with the larger of the row\'s two seeded numbers', [svt['most_likely'][4], svt['most_likely'][5]], [Ptt.labels[int(np.argmax(u_[4]))], Ptt.labels[int(np.argmax(u_[5]))]])
svt2 = call('knn.save', table=tt, y='c', x=['x'], k=2, validation='v', seed=5, chosen=2)
u5 = np.random.default_rng([5, 7]).random((6, 2))
check('... another seed, its own draws (scikit-learn would give both to B, the first level)', ([svt2['most_likely'][4], svt2['most_likely'][5]], KNeighborsClassifier(n_neighbors=2).fit(np.array([[0.0], [1], [5], [6]]), [0, 1, 0, 1]).predict(np.array([[0.5], [5.5]])).tolist()),
      ([Ptt.labels[int(np.argmax(u5[4]))], Ptt.labels[int(np.argmax(u5[5]))]], [0, 0]))
check('... and the tie leaves both probabilities at 1/2', svt['prob'][4], [0.5, 0.5])
check('K larger than the training rows allow: one less than them, with a note', (rt_['k'], bool(rt_['notes'])), (2, False))
rk = call('knn.fit', table=tt, y='c', x=['x'], k=9, validation='v', seed=1)
check('... K = 9 on 4 training rows becomes 3, said in a note', (rk['k'], 'K is 3' in ' '.join(rk['notes'])), (3, True))
check('K of 0: an error', 'error' in call('knn.fit', table=T, y='cls', x=['x1'], k=0, seed=1), True)
# no validation rows: the best K by the training rows, each left out
rn = call('knn.fit', table=T, y='three', x=['x1', 'x2'], k=12, seed=1)
Pn = pv.prepare(T, 'three', ['x1', 'x2'])
Zn, _, _ = zof(Pn)
tr_rates = [float(np.mean(knn_pred(k, Zn, Pn)[0] != Pn.target)) for k in range(1, 13)]
check('no validation: every K\'s training rate leaves each row out; the best K by it', ([row['rate0'] for row in rn['path']['rows']] == tr_rates, rn['best'], rn['by']), (True, int(np.argmin(tr_rates)) + 1, 'Training'))
check('three levels: the table has the training set only', [c['label'] for c in rn['path']['columns']], ['K', 'Training Count', 'Training Misclassification Rate', 'Training Misclassifications'])
# a continuous response: RASE per K
rc = call('knn.fit', table=T, y='yc', x=['x1', 'x2', 'g'], k=8, validation='vt', seed=1)
Pc = pv.prepare(T, 'yc', ['x1', 'x2', 'g'], validation='vt')
Zc, _, _ = zof(Pc)
worst = 0.0
for row in rc['path']['rows']:
    pred, _ = knn_pred(row['k'], Zc, Pc, reg=True)
    for s in (0, 1, 2):
        ms = Pc.sets == s
        worst = max(worst, abs(row[f'rase{s}'] - math.sqrt(np.mean((Pc.target[ms] - pred[ms]) ** 2))) / row[f'rase{s}'])
check.near('a continuous response: every K\'s RASE on each set = KNeighborsRegressor(n_neighbors=K).predict (training rows left out)', worst, 0.0, abs_=1e-13)
Mc = {m_['set']: m_ for m_ in rc['fit']['measures']}
check.near('... the fit shown is the best K by the validation RASE', Mc['Validation']['rase'], min(row['rase1'] for row in rc['path']['rows']), rel=1e-13)
svc_ = call('knn.save', table=T, y='yc', x=['x1', 'x2', 'g'], k=8, validation='vt', seed=1, chosen=rc['chosen'])
pr_c, _ = knn_pred(rc['chosen'], Zc, Pc, reg=True)
check.near('Save Predicteds (continuous): the mean of the K nearest', mx(np.array(svc_['values'])[at_rows(svc_, Pc.index)], pr_c), 0.0, abs_=1e-12)
check.near('... and Save Residuals: the response minus it', mx(np.array(svc_['residuals'])[at_rows(svc_, Pc.index)], Pc.target - pr_c), 0.0, abs_=1e-12)
# Informative Missing: a missing continuous value is the training mean plus a Missing column (0/1, not scaled)
ri = call('knn.fit', table=T, y='cls', x=['x1m', 'gm'], k=5, seed=1)
Pi = pv.prepare(T, 'cls', ['x1m', 'gm'])
check('Informative Missing: the factors the distances use', (Pi.features, ri['scaled']), (['x1m', 'x1m Missing', 'gm[a]', 'gm[b]', 'gm[c]', 'gm[Missing]'], ['x1m']))
Zi, _, _ = zof(Pi)
# every missing x1m is at the same point, so rows tie: each K is the first K of scikit-learn's search for the 5 nearest
near5 = KNeighborsClassifier(n_neighbors=5).fit(Zi, Pi.target).kneighbors(return_distance=False)
prefix = []
ui = ties(Pi, 1)
for k in range(1, 6):
    votes = np.stack([np.sum(Pi.target[near5[:, :k]] == c, 1) for c in range(2)], 1)
    prefix.append(float(np.mean(np.argmax(np.where(votes == votes.max(1, keepdims=True), ui, -1.0), 1) != Pi.target)))
check('... every K is the first K of the neighbours scikit-learn finds for the largest K (its kneighbors)', [row['rate0'] for row in ri['path']['rows']], prefix)
sep = [int(np.sum(np.any(np.sort(KNeighborsClassifier(n_neighbors=k).fit(Zi, Pi.target).kneighbors(return_distance=False), 1) != np.sort(near5[:, :k], 1), 1))) for k in range(1, 5)]
check('scikit-learn 1.8: with rows at the same distance, its search for k neighbours picks other tied rows than the first k of its search for 5 (so the report takes one search, and the code shows it)', min(sep) > 0, True)
# the profiler: the prediction as one factor runs, the others held
pk = call('knn.profile', table=T, y='cls', x=['x1', 'x2', 'g'], k=10, validation='v', seed=1, chosen=4, current={'x2': 0.3, 'g': 'b'}, grid=9)
check('knn.profile: a probability per level, bounded', [(q['name'], q['bounded']) for q in pk['responses']], [('Prob[high]', True), ('Prob[low]', True)])
f0 = pk['factors'][0]
Zs0, c0, s0 = zof(P)
grid = np.linspace(f0['min'], f0['max'], 9)
Xg = P.encode_settings([{'x1': v, 'x2': 0.3, 'g': 'b'} for v in grid])
m4 = KNeighborsClassifier(n_neighbors=4).fit(Z[tr], P.target[tr])
check.near('... the trace over x1 = (votes + 1/L)/(K + 1) of the settings\' 4 nearest training rows', mx(pk['responses'][0]['traces'][0]['pred'], (m4.predict_proba((Xg - c0) / s0)[:, 0] * 4 + 0.5) / 5), 0.0, abs_=1e-15)
imp = call('knn.importance', table=T, y='cls', x=['x1', 'x2', 'g'], k=10, validation='v', seed=1, chosen=4, imp_method='resampled', imp_n=64, imp_seed=2)
check('Assess Variable Importance runs on it (resampled inputs from the training rows)', isinstance(imp, dict) and not imp.get('error'), True)

# ---- Distance Weights, Standardize off, a K-fold Validation column, Score Rows --------------------------------------
kf_col = (np.arange(n) % 5 + 1).astype(float)
Tk = table({**cols, 'fold': list(kf_col)}, types={**TYPES, 'fold': 'nominal'}, levels=LEVELS)
rd = call('knn.fit', table=T, y='cls', x=['x1', 'x2', 'g'], k=8, validation='v', seed=1, weights='distance', chosen=6)
Pd_ = pv.prepare(T, 'cls', ['x1', 'x2', 'g'], validation='v')
Zd, _, _ = zof(Pd_)
trd = Pd_.train()
md = KNeighborsClassifier(n_neighbors=6, weights='distance').fit(Zd[trd], Pd_.target[trd])
sk_share = np.empty((len(Zd), 2))
sk_share[trd] = md.predict_proba(None)
sk_share[~trd] = md.predict_proba(Zd[~trd])
svd = call('knn.save', table=T, y='cls', x=['x1', 'x2', 'g'], k=8, validation='v', seed=1, weights='distance', chosen=6)
check.near('Distance Weights: each level\'s share of the 1/distance weights is scikit-learn\'s KNeighborsClassifier(weights="distance"): the probability (6 share + 1/L)/(6 + 1)', mx(np.array(svd['prob'])[at_rows(svd, Pd_.index)], (6 * sk_share + 0.5) / 7), 0.0, abs_=1e-12)
sk_pred = np.argmax(sk_share, 1)
check('... the level called is scikit-learn\'s predict (a tie of weights at random)', ([Pd_.labels.index(v) for v in np.array(svd['most_likely'])[at_rows(svd, Pd_.index)]] == sk_pred.tolist()), True)
rdc = call('knn.fit', table=T, y='yc', x=['x1', 'x2', 'g'], k=5, validation='vt', seed=1, weights='distance', chosen=4)
Pdc = pv.prepare(T, 'yc', ['x1', 'x2', 'g'], validation='vt')
Zdc, _, _ = zof(Pdc)
mdc = KNeighborsRegressor(n_neighbors=4, weights='distance').fit(Zdc[Pdc.train()], Pdc.target[Pdc.train()])
pdc = np.empty(len(Zdc))
pdc[Pdc.train()] = mdc.predict(None)
pdc[~Pdc.train()] = mdc.predict(Zdc[~Pdc.train()])
check.near('Distance Weights, a continuous response: the fit\'s validation RASE is scikit-learn\'s weighted mean\'s', {m_['set']: m_ for m_ in rdc['fit']['measures']}['Validation']['rase'], float(np.sqrt(np.mean((Pdc.target[Pdc.mask(1)] - pdc[Pdc.mask(1)]) ** 2))), rel=1e-12)
rs_ = call('knn.fit', table=T, y='cls', x=['x1', 'x2', 'g'], k=8, validation='v', seed=1, standardize=False, chosen=3)
m3 = KNeighborsClassifier(n_neighbors=3).fit(Pd_.X[trd], Pd_.target[trd])
v3 = np.round(m3.predict_proba(Pd_.X[Pd_.mask(1)]) * 3)
u3 = ties(Pd_, 1)[Pd_.mask(1)]
call3 = np.argmax(np.where(v3 == v3.max(1, keepdims=True), u3, -1.0), 1)
check.near('Standardize off: the distances on the factors as they are (scikit-learn on the raw columns), K = 3\'s validation rate', rs_['path']['rows'][2]['rate1'], float(np.mean(call3 != Pd_.target[Pd_.mask(1)])), abs_=1e-15)
check('... and the report says so', (rs_['standardize'], rs_['scaled']), (False, []))
rf_ = call('knn.fit', table=Tk, y='cls', x=['x1', 'x2', 'g'], k=6, validation='fold', seed=2)
Pf_ = pv.prepare(Tk, 'cls', ['x1', 'x2', 'g'], validation='fold')
Zf, _, _ = zof(Pf_)
uf = ties(Pf_, 2)
cv_rates = []
for k_ in range(1, 7):
    wrong = 0
    for j in range(5):
        held = Pf_.folds == j
        mj = KNeighborsClassifier(n_neighbors=k_).fit(Zf[~held], Pf_.target[~held])
        vj = np.round(mj.predict_proba(Zf[held]) * k_)
        cj = np.argmax(np.where(vj == vj.max(1, keepdims=True), uf[held], -1.0), 1)
        wrong += int(np.sum(cj != Pf_.target[held]))
    cv_rates.append(wrong / n)
check('a K-fold Validation column: every row trains; each fold predicted from its neighbours in the other folds (scikit-learn fitted without the fold), every K', [round(r_['ratecv'], 12) for r_ in rf_['path']['rows']], [round(v, 12) for v in cv_rates])
check('... the best K by the folds, a Crossvalidation line in the path and the fit', (rf_['by'], rf_['best'], [c_['label'] for c_ in rf_['path']['columns'] if 'Crossvalidation' in c_['label'] and not c_.get('hidden')], rf_['cv']['measures']['set']),
      ('Crossvalidation', int(np.argmin(cv_rates)) + 1, ['Crossvalidation Misclassification Rate'], 'Crossvalidation'))
rk_ = call('knn.fit', table=T, y='cls', x=['x1', 'x2', 'g'], k=8, validation='v', seed=1, chosen=5, keep='test-knn')
Tother = table({'x1': list(x1[:40] + 0.5), 'x2': list(x2[:40]), 'g': list(g[:40])}, types={'g': 'nominal'}, levels={'g': ['a', 'b', 'c']})
sc = call('knn.score', table=Tother, keep='test-knn')
m5o = KNeighborsClassifier(n_neighbors=5).fit(Zd[trd], Pd_.target[trd])
Xo_, _ = pv.score_frame(Pd_, Tother)
_, cen_, sca_ = zof(Pd_)
vo = np.round(m5o.predict_proba((Xo_ - cen_) / sca_) * 5)
check.near('Score Rows: another table, each row from its 5 nearest training rows of the report\'s model (the probabilities)', mx(sc['prob'], (vo + 0.5) / 6), 0.0, abs_=1e-12)
uo = np.random.default_rng([1, 7]).random((40, 2))
check('... the level called, a tie at random by the scored table\'s row numbers', [Pd_.labels.index(v) for v in sc['most_likely']], np.argmax(np.where(vo == vo.max(1, keepdims=True), uo, -1.0), 1).tolist())
same = call('knn.score', table=T, keep='test-knn', target_rows=[3, 50, 51])
sv5 = call('knn.save', table=T, y='cls', x=['x1', 'x2', 'g'], k=8, validation='v', seed=1, chosen=5)
check.near('... rows of the report\'s own table: as Save Predicteds gives them (a training row without itself)', mx(same['prob'], np.array(sv5['prob'])[at_rows(sv5, [3, 50, 51])]), 0.0, abs_=1e-15)
check('... without the kept model: fitted again, and said', call('knn.score', table=Tother, keep='gone', source=T, y='cls', x=['x1', 'x2', 'g'], k=8, validation='v', seed=1, chosen=5)['note'] is not None, True)


# =======================================================================================================================
# NAIVE BAYES
# =======================================================================================================================


def nb_sklearn(P, frame, alpha=1.0, sw=None):
    """GaussianNB on the continuous factors and CategoricalNB on the
    categorical ones (level numbers), fitted to the training rows, their
    joint log likelihoods added with the class shares counted once."""
    tr = P.train()
    cont = [e['name'] for e in P.enc if e['type'] == 'continuous']
    cats = [e for e in P.enc if e['type'] != 'continuous']
    y = P.target
    jll = 0.0
    prior = None
    if cont:
        Xc = frame[cont].to_numpy(float)
        gnb = GaussianNB().fit(Xc[tr], y[tr], sample_weight=None if sw is None else sw[tr])
        jll = jll + gnb.predict_joint_log_proba(Xc)
        prior = np.log(gnb.class_prior_)
    if cats:
        Xk = np.column_stack([pd.Categorical(frame[e['name']].astype(object), categories=e['levels']).codes for e in cats])
        cnb = CategoricalNB(alpha=alpha, min_categories=[len(e['levels']) for e in cats]).fit(Xk[tr], y[tr], sample_weight=None if sw is None else sw[tr])
        jll = jll + cnb.predict_joint_log_proba(Xk)
        if prior is not None:
            jll = jll - prior           # the class shares once, not twice
    jll = jll - jll.max(1, keepdims=True)
    p = np.exp(jll)
    return p / p.sum(1, keepdims=True)


Pb = pv.prepare(T, 'three', ['x1', 'x2', 'g'], validation='v', weight='w', freq='f')
frame = pd.DataFrame({c: cols[c] for c in ['x1', 'x2', 'g']}).iloc[Pb.index].reset_index(drop=True)
rb = call('naivebayes.fit', table=T, y='three', x=['x1', 'x2', 'g'], validation='v', weight='w', freq='f', seed=1)
check('naivebayes.fit: no error, three levels', (rb.get('error'), rb['fit']['levels']), (None, ['lo', 'mid', 'hi']))
sb = call('naivebayes.save', table=T, y='three', x=['x1', 'x2', 'g'], validation='v', weight='w', freq='f', seed=1)
ps = np.array(sb['prob'])[at_rows(sb, Pb.index)]
want = nb_sklearn(Pb, frame, sw=Pb.w)
check.near('the probabilities = GaussianNB + CategoricalNB (joint log likelihoods, the class shares once), weighted by Weight × Freq', mx(ps, want), 0.0, abs_=1e-12)
check('... the most likely level is the largest', sb['most_likely'][:30], [Pb.labels[j] for j in np.argmax(np.array(sb['prob'])[:30], 1)])
share = np.array([Pb.w[Pb.train() & (Pb.target == c)].sum() for c in range(3)]) / Pb.w[Pb.train()].sum()
check.near('the class shares: of Weight × Freq on the training rows', mx([q['share'] for q in rb['priors']], share), 0.0, abs_=1e-15)
Mb = {m_['set']: m_ for m_ in rb['fit']['measures']}
yv = Pb.target[Pb.mask(1)]
check.near('Fit Details: the validation misclassification rate of those probabilities', Mb['Validation']['misclassification'],
           float(np.sum(Pb.w[Pb.mask(1)] * (want[Pb.mask(1)].argmax(1) != yv)) / Pb.w[Pb.mask(1)].sum()), abs_=1e-15)
# the class parameters: GaussianNB's theta_ and var_, CategoricalNB's feature_log_prob_
gnb = GaussianNB().fit(frame[['x1', 'x2']].to_numpy(float)[Pb.train()], Pb.target[Pb.train()], sample_weight=Pb.w[Pb.train()])
par = {q['factor']: q for q in rb['parameters']}
check.near('Class Parameters: the means are GaussianNB\'s theta_', mx([[row['mean'] for row in par[c]['rows']] for c in ('x1', 'x2')], gnb.theta_.T), 0.0, abs_=1e-12)
check.near('... the standard deviations the root of its var_ (var_smoothing included)', mx([[row['sd'] for row in par[c]['rows']] for c in ('x1', 'x2')], np.sqrt(gnb.var_).T), 0.0, abs_=1e-12)
check.near('... and the smoothing added is GaussianNB\'s epsilon_', rb['eps'], float(gnb.epsilon_), rel=1e-12)
cnb = CategoricalNB(alpha=1.0, min_categories=[3]).fit(pd.Categorical(frame['g'], categories=['a', 'b', 'c']).codes[Pb.train()].reshape(-1, 1), Pb.target[Pb.train()], sample_weight=Pb.w[Pb.train()])
check.near('... the level shares CategoricalNB\'s exp(feature_log_prob_)', mx([[row[f'p{j}'] for j in range(3)] for row in par['g']['rows']], np.exp(cnb.feature_log_prob_[0])), 0.0, abs_=1e-12)
# another alpha, no weights
Pa = pv.prepare(T, 'cls', ['x2', 'g'], validation='v')
fa = pd.DataFrame({c: cols[c] for c in ['x2', 'g']}).iloc[Pa.index].reset_index(drop=True)
sa = call('naivebayes.save', table=T, y='cls', x=['x2', 'g'], validation='v', seed=1, alpha=0.4)
check.near('alpha = 0.4: CategoricalNB(alpha=0.4)', mx(np.array(sa['prob'])[at_rows(sa, Pa.index)], nb_sklearn(Pa, fa, alpha=0.4)), 0.0, abs_=1e-12)
sg = call('naivebayes.save', table=T, y='cls', x=['g'], seed=1)
Pg = pv.prepare(T, 'cls', ['g'])
check.near('categorical factors only: CategoricalNB alone', mx(np.array(sg['prob'])[at_rows(sg, Pg.index)], nb_sklearn(Pg, pd.DataFrame({'g': cols['g']}).iloc[Pg.index].reset_index(drop=True))), 0.0, abs_=1e-12)
sx = call('naivebayes.save', table=T, y='cls', x=['x1'], seed=1, var_smoothing=0.01)
Px = pv.prepare(T, 'cls', ['x1'])
gx = GaussianNB(var_smoothing=0.01).fit(np.array(x1)[Px.index].reshape(-1, 1), Px.target)
check.near('continuous factors only, var_smoothing 0.01: GaussianNB(var_smoothing=0.01)', mx(np.array(sx['prob'])[at_rows(sx, Px.index)], gx.predict_proba(np.array(x1).reshape(-1, 1))), 0.0, abs_=1e-12)
# missing values: left out of the product; with Informative Missing that a value is missing is a factor of its own
rm = call('naivebayes.fit', table=T, y='cls', x=['x1m', 'gm'], seed=1)
sm_ = call('naivebayes.save', table=T, y='cls', x=['x1m', 'gm'], seed=1)
check('Informative Missing: every row is saved', len(sm_['rows']), n)
Pm = pv.prepare(T, 'cls', ['x1m', 'gm'])
yy = Pm.target
vx = np.array(x1m)[Pm.index]
gg = np.array([{'a': 0, 'b': 1, 'c': 2, None: 3}[v] for v in np.array(gm, dtype=object)[Pm.index]])
okx = np.isfinite(vx)
eps = 1e-9 * np.var(vx[okx])
logp = np.log(np.array([np.mean(yy == c) for c in range(2)]))[None, :].repeat(len(yy), 0)
for c in range(2):
    mu, var = vx[okx & (yy == c)].mean(), vx[okx & (yy == c)].var() + eps
    logp[okx, c] += -0.5 * np.log(2 * np.pi * var) - (vx[okx] - mu) ** 2 / (2 * var)
    miss = (~okx).astype(int)
    cnt = np.bincount(miss[yy == c], minlength=2) + 1.0
    logp[:, c] += np.log(cnt / cnt.sum())[miss]
    cg = np.bincount(gg[yy == c], minlength=4) + 1.0
    logp[:, c] += np.log(cg / cg.sum())[gg]
hand = np.exp(logp - logp.max(1, keepdims=True))
hand /= hand.sum(1, keepdims=True)
check.near('a missing x1m is left out of its row\'s product, and "x1m is missing" and a missing gm are factors of their own (by hand)', mx(np.array(sm_['prob'])[at_rows(sm_, Pm.index)], hand), 0.0, abs_=1e-12)
check('... the Class Parameters list them', [q['factor'] for q in rm['parameters']], ['x1m', 'x1m Missing', 'gm'])
check('... gm has a Missing level', rm['parameters'][2]['labels'], ['a', 'b', 'c', 'Missing'])
rd = call('naivebayes.save', table=T, y='cls', x=['x1m', 'gm'], seed=1, missing='drop')
Pd = pv.prepare(T, 'cls', ['x1m', 'gm'], missing='drop')
fd = pd.DataFrame({'x1m': cols['x1m'], 'gm': cols['gm']}).iloc[Pd.index].reset_index(drop=True)
check('Informative Missing off: the rows missing a factor are neither fitted nor saved', sorted(rd['rows']), sorted(Pd.index.tolist()))
check.near('... and the others are GaussianNB + CategoricalNB on the complete rows', mx(np.array(rd['prob'])[at_rows(rd, Pd.index)], nb_sklearn(Pd, fd)), 0.0, abs_=1e-12)
# a level no training row has
tl = table({'x': list(x1[:60]), 'c': ['p'] * 25 + ['q'] * 25 + ['r'] * 10, 'v': [0] * 50 + [1] * 10}, types={'c': 'nominal'})
rl = call('naivebayes.fit', table=tl, y='c', x=['x'], validation='v', seed=1)
sl = call('naivebayes.save', table=tl, y='c', x=['x'], validation='v', seed=1)
check('a level only in the validation rows: probability 1e-15 (its class share is 0), with a note', (max(q[2] for q in sl['prob']), bool(rl['notes'])), (1e-15, True))
check('a continuous response: an error that says so', 'continuous' in call('naivebayes.fit', table=T, y='yc', x=['x1'], seed=1).get('error', ''), True)
# the profiler
pn = call('naivebayes.profile', table=T, y='three', x=['x1', 'x2', 'g'], validation='v', weight='w', freq='f', seed=1, current={'x1': 9.0, 'g': 'c'}, grid=7)
fr = pn['factors'][1]
gx2 = np.linspace(fr['min'], fr['max'], 7)
frg = pd.DataFrame({'x1': [9.0] * 7, 'x2': gx2, 'g': ['c'] * 7})
jl = GaussianNB().fit(frame[['x1', 'x2']].to_numpy(float)[Pb.train()], Pb.target[Pb.train()], sample_weight=Pb.w[Pb.train()]).predict_joint_log_proba(frg[['x1', 'x2']].to_numpy(float))
jl = jl + cnb.predict_joint_log_proba(np.full((7, 1), 2)) - np.log(share)
pp = np.exp(jl - jl.max(1, keepdims=True))
pp /= pp.sum(1, keepdims=True)
check.near('naivebayes.profile: the trace over x2 (x1 = 9, g = c) = GaussianNB + CategoricalNB there', mx([q['traces'][1]['pred'] for q in pn['responses']], pp.T), 0.0, abs_=1e-12)

# ---- a K-fold Validation column: Fit Details crossvalidated --------------------------------------------------------
rnf = call('naivebayes.fit', table=Tk, y='cls', x=['x1', 'x2', 'g'], validation='fold', seed=1)
Pnf = pv.prepare(Tk, 'cls', ['x1', 'x2', 'g'], validation='fold')
fr_nf = pd.DataFrame({c: pd.Series(np.asarray(cols[c], dtype=object)[Pnf.index]) if c == 'g' else np.asarray(cols[c], dtype=float)[Pnf.index] for c in ['x1', 'x2', 'g']})
oof_nf = np.zeros((len(Pnf.index), 2))
for j in range(5):
    Q = pv.prepare(Tk, 'cls', ['x1', 'x2', 'g'], validation='fold')
    Q.sets = np.where(Pnf.folds == j, 1, 0)
    oof_nf[Pnf.folds == j] = nb_sklearn(Q, fr_nf)[Pnf.folds == j]
cvm_nf = rnf['cv']['measures']
check.near('Naive Bayes with a K-fold Validation column: each fold predicted by GaussianNB and CategoricalNB fitted to the other folds (the crossvalidated Mean -Log p)', cvm_nf['mean_neg_log_p'], float(metrics.log_loss(Pnf.target, np.clip(oof_nf, 1e-15, 1 - 1e-15), labels=[0, 1])), rel=1e-9)
check('... the crossvalidated line named, for the 5 folds', (cvm_nf['set'], rnf['cv']['k'], len(rnf['cv']['folds'])), ('Crossvalidation', 5, 5))


# =======================================================================================================================
# SUPPORT VECTOR MACHINES
# =======================================================================================================================
rs = call('svm.fit', table=T, y='three', x=['x1', 'x2', 'g'], validation='v', weight='w', seed=7)
check('svm.fit: no error', rs.get('error'), None)
Ps = pv.prepare(T, 'three', ['x1', 'x2', 'g'], validation='v', weight='w')
Zs, cs, ss = zof(Ps)
trs = Ps.train()
check('the default Gamma is one over the columns of X (5 here), Cost 1, radial basis function', (rs['summary']['gamma'], rs['summary']['cost'], rs['summary']['kernel']), (0.2, 1.0, 'rbf'))
svc = SVC(kernel='rbf', C=1.0, gamma=0.2, probability=True, random_state=7).fit(Zs[trs], Ps.target[trs], sample_weight=Ps.w[trs])
ss_ = call('svm.save', table=T, y='three', x=['x1', 'x2', 'g'], validation='v', weight='w', seed=7)
want = np.zeros((len(Zs), 3))
want[:, svc.classes_] = svc.predict_proba(Zs)
got = np.array(ss_['prob'])[at_rows(ss_, Ps.index)]
check.near('the probabilities = SVC(probability=True, random_state=seed) on the standardized factors, weighted', mx(got, want), 0.0, abs_=1e-10)
check('... never exactly 0 or 1', (float(got.min()) > 0, float(got.max()) < 1), (True, True))
check('the number of support vectors, per level', (rs['summary']['n_sv'], [q['n'] for q in rs['summary']['sv_per_level']]), (len(svc.support_), svc.n_support_.tolist()))
check('the rows where the decision function\'s level differs from the most likely', rs['summary']['differs'], int(np.sum(svc.predict(Zs) != want.argmax(1))))
Ms = {m_['set']: m_ for m_ in rs['fit']['measures']}
check.near('Fit Details: the test set\'s Mean -Log p of those probabilities', Ms['Test']['mean_neg_log_p'], float(np.average(-np.log(want[Ps.mask(2), Ps.target[Ps.mask(2)]]), weights=Ps.w[Ps.mask(2)])), rel=1e-9)
ss2 = call('svm.save', table=T, y='three', x=['x1', 'x2', 'g'], validation='v', weight='w', seed=8)
check('another seed: other Platt folds, slightly other probabilities', mx(ss2['prob'], ss_['prob']) > 1e-6, True)
check('the same seed: the same probabilities', mx(call('svm.save', table=T, y='three', x=['x1', 'x2', 'g'], validation='v', weight='w', seed=7)['prob'], ss_['prob']), 0.0)
# the linear kernel, a given gamma and cost
sl_ = call('svm.save', table=T, y='cls', x=['x1', 'x2'], seed=3, kernel='linear', cost=0.5)
Pl = pv.prepare(T, 'cls', ['x1', 'x2'])
Zl, _, _ = zof(Pl)
lin_ = SVC(kernel='linear', C=0.5, probability=True, random_state=3).fit(Zl, Pl.target)
check.near('the linear kernel, Cost 0.5: SVC(kernel="linear")', mx(np.array(sl_['prob'])[at_rows(sl_, Pl.index)], lin_.predict_proba(Zl)), 0.0, abs_=1e-10)
# regression: SVR on the standardized response
rr = call('svm.fit', table=T, y='yc', x=['x1', 'x2', 'g'], validation='v', seed=3, cost=4, gamma=0.3)
Pr = pv.prepare(T, 'yc', ['x1', 'x2', 'g'], validation='v')
Zr, _, _ = zof(Pr)
trr = Pr.train()
ym, ys = Pr.target[trr].mean(), Pr.target[trr].std(ddof=1)
svr = SVR(kernel='rbf', C=4.0, gamma=0.3, epsilon=0.1).fit(Zr[trr], (Pr.target[trr] - ym) / ys)
pr_ = ym + ys * svr.predict(Zr)
sr = call('svm.save', table=T, y='yc', x=['x1', 'x2', 'g'], validation='v', seed=3, cost=4, gamma=0.3)
check.near('a continuous response: SVR(epsilon=0.1) on the standardized response, back on its scale', mx(np.array(sr['values'])[at_rows(sr, Pr.index)], pr_), 0.0, abs_=1e-9)
Mr = {m_['set']: m_ for m_ in rr['fit']['measures']}
check.near('... Fit Details: the validation RASE', Mr['Validation']['rase'], math.sqrt(np.mean((Pr.target[Pr.mask(1)] - pr_[Pr.mask(1)]) ** 2)), rel=1e-9)
check('... the summary gives Gamma and Cost as asked, and epsilon', (rr['summary']['gamma'], rr['summary']['cost'], rr['summary']['epsilon']), (0.3, 4.0, 0.1))
# the tuning design, judged by the validation rows
rt = call('svm.fit', table=T, y='cls', x=['x1', 'x2', 'g'], validation='v', seed=5, tune=True, points=12)
Pt = pv.prepare(T, 'cls', ['x1', 'x2', 'g'], validation='v')
Zt, _, _ = zof(Pt)
trt, vat = Pt.train(), Pt.mask(1)
g0 = 1 / Zt.shape[1]
design = [(c, g0 * gg_) for c in np.logspace(-1, 3, 4) for gg_ in np.logspace(-2, 1, 3)]
check('the design: 12 points, Cost 0.1 to 1000 crossed with Gamma 1/100 to 10 times the default, on the log scale',
      (len(rt['tuning']['rows']), mx([q['cost'] for q in rt['tuning']['rows']], [c for c, _ in design]), mx([q['gamma'] for q in rt['tuning']['rows']], [gg_ for _, gg_ in design])), (12, 0.0, 0.0))
brute = []
for c, gg_ in design:
    p_ = SVC(kernel='rbf', C=c, gamma=gg_, random_state=5).fit(Zt[trt], Pt.target[trt]).predict(Zt[vat])
    brute.append(float(np.mean(p_ != Pt.target[vat])))
check.near('each point\'s validation misclassification rate = SVC(C, gamma).fit(training).predict(validation)', mx([q['crit'] for q in rt['tuning']['rows']], brute), 0.0, abs_=1e-15)
bi = min(range(len(design)), key=lambda i: (brute[i], design[i][0], design[i][1]))
check('the best: the smallest rate, then the smaller Cost and Gamma; the model is fitted again with it', (rt['tuning']['best'], rt['summary']['cost'], rt['summary']['gamma']), (bi, design[bi][0], design[bi][1]))
check('... judged by the validation rows', rt['tuning']['how'], 'validation')
# with no validation rows: 5-fold cross-validation from the seed
rcv = call('svm.fit', table=T, y='cls', x=['x1', 'x2'], seed=11, tune=True, points=6)
Pv = pv.prepare(T, 'cls', ['x1', 'x2'])
Zv, _, _ = zof(Pv)
g0 = 1 / Zv.shape[1]
design = [(c, g0 * gg_) for c in np.logspace(-1, 3, 3) for gg_ in np.logspace(-2, 1, 2)]
folds = list(StratifiedKFold(n_splits=5, shuffle=True, random_state=11).split(np.arange(len(Zv)), Pv.target))
brute = []
for c, gg_ in design:
    wrong = 0
    for a, b in folds:
        wrong += int(np.sum(SVC(C=c, gamma=gg_, random_state=11).fit(Zv[a], Pv.target[a]).predict(Zv[b]) != Pv.target[b]))
    brute.append(wrong / len(Zv))
check('no validation rows: stratified 5-fold cross-validation', rcv['tuning']['how'], 'stratified 5-fold cross-validation')
check.near('... each point\'s cross-validated misclassification = the folds of StratifiedKFold(5, shuffle, random_state=seed)', mx([q['crit'] for q in rcv['tuning']['rows']], brute), 0.0, abs_=1e-15)
rcr = call('svm.fit', table=T, y='yc', x=['x1', 'x2'], seed=11, tune=True, points=4, kernel='linear')
check('the linear kernel: Cost alone, 0.01 to 100', [round(q['cost'], 10) for q in rcr['tuning']['rows']], [round(c, 10) for c in np.logspace(-2, 2, 4)])
Pcr = pv.prepare(T, 'yc', ['x1', 'x2'])
Zcr, _, _ = zof(Pcr)
ym, ys = Pcr.target.mean(), Pcr.target.std(ddof=1)
brute = []
for c in np.logspace(-2, 2, 4):
    sq = 0.0
    for a, b in KFold(n_splits=5, shuffle=True, random_state=11).split(np.arange(len(Zcr))):
        p_ = ym + ys * SVR(kernel='linear', C=c, epsilon=0.1).fit(Zcr[a], (Pcr.target[a] - ym) / ys).predict(Zcr[b])
        sq += float(np.sum((Pcr.target[b] - p_) ** 2))
    brute.append(math.sqrt(sq / len(Zcr)))
check.near('a continuous response: each point\'s cross-validated RASE = KFold(5) of SVR', mx([q['crit'] for q in rcr['tuning']['rows']], brute), 0.0, abs_=1e-9)
# the decision boundary
bd = call('svm.boundary', table=T, y='cls', x=['x1', 'x2', 'g'], validation='v', seed=5, m=21, current={'g': 'b'})
Pb2 = pv.prepare(T, 'cls', ['x1', 'x2', 'g'], validation='v')
Zb, cb, sb_ = zof(Pb2)
svb = SVC(C=1.0, gamma=0.2, probability=True, random_state=5).fit(Zb[Pb2.train()], Pb2.target[Pb2.train()])
XX, YY = np.meshgrid(bd['x'], bd['y'])
Xg = Pb2.encode_settings([{'x1': u, 'x2': v, 'g': 'b'} for u, v in zip(XX.ravel(), YY.ravel())])
check('svm.boundary: the pair, the other factor held where the profiler has it', (bd['pair'], bd['held']), (['x1', 'x2'], [{'name': 'g', 'value': 'b'}]))
check.near('... the grid holds decision_function over the two factors', mx(bd['decision'], svb.decision_function((Xg - cb) / sb_).reshape(21, 21)), 0.0, abs_=1e-9)
check('... from the smallest to the largest value, 4% beyond', (round(bd['x'][0], 9), round(bd['x'][-1], 9)), (round(x1.min() - 0.04 * np.ptp(x1), 9), round(x1.max() + 0.04 * np.ptp(x1), 9)))
check('... the rows on it, and which are support vectors', (bd['points']['rows'] == Pb2.index.tolist(), sum(bd['points']['sv']), len(svb.support_)), (True, sum(bd['points']['sv']), len(svb.support_)))
check('... the support vectors are the training rows SVC keeps', sorted(np.array(bd['points']['rows'])[np.array(bd['points']['sv'], dtype=bool)].tolist()), sorted(Pb2.index[Pb2.train()][svb.support_].tolist()))
bm = call('svm.boundary', table=T, y='three', x=['x1', 'x2'], seed=5, m=11)
check('three levels: the most likely level over the grid', (len(bm['most']), 'decision' in bm, sorted(set(np.ravel(bm['most']).tolist())) <= [0, 1, 2]), (11, False, True))
try:
    call('svm.boundary', table=T, y='cls', x=['x1', 'g'], seed=1)
    check('svm.boundary needs two continuous factors', 'no error', 'error')
except Exception as e:  # noqa: BLE001
    check('svm.boundary needs two continuous factors', 'two continuous factors' in str(e), True)
check('one training level: an error', 'one level' in call('svm.fit', table=tl, y='c', x=['x'], validation='v', rows=list(range(25)) + list(range(50, 60)), seed=1).get('error', ''), True)
check('a bad Cost: an error', 'Cost' in call('svm.fit', table=T, y='cls', x=['x1'], seed=1, cost=-1).get('error', ''), True)
# the profiler
pz = call('svm.profile', table=T, y='yc', x=['x1', 'x2', 'g'], validation='v', seed=3, cost=4, gamma=0.3, current={'x2': 0.5, 'g': 'a'}, grid=5)
fz = pz['factors'][0]
gz = np.linspace(fz['min'], fz['max'], 5)
Xz = Pr.encode_settings([{'x1': v, 'x2': 0.5, 'g': 'a'} for v in gz])
_, cz, sz = zof(Pr)
ymz, ysz = Pr.target[trr].mean(), Pr.target[trr].std(ddof=1)
check.near('svm.profile: the trace over x1 = SVR\'s prediction there', mx(pz['responses'][0]['traces'][0]['pred'], ymz + ysz * svr.predict((Xz - cz) / sz)), 0.0, abs_=1e-9)

# ---- the tuning design judged by the folds of a K-fold Validation column; Score Rows ----------------------------------
rtf = call('svm.fit', table=Tk, y='cls', x=['x1', 'x2'], validation='fold', seed=3, tune=True, points=4)
Ptf = pv.prepare(Tk, 'cls', ['x1', 'x2'], validation='fold')
Ztf, _, _ = zof(Ptf)
okt = []
for q in rtf['tuning']['rows']:
    wrong = 0
    for j in range(5):
        held = Ptf.folds == j
        est = SVC(kernel='rbf', C=q['cost'], gamma=q['gamma'], random_state=3).fit(Ztf[~held], Ptf.target[~held])
        wrong += int(np.sum(est.predict(Ztf[held]) != Ptf.target[held]))
    okt.append(abs(q['crit'] - wrong / n) < 1e-12)
check('Support Vector Machines: the tuning design judged by the folds of a K-fold Validation column (SVC fitted without each fold)', (rtf['tuning']['how'], okt), ('the 5 folds of the Validation column', [True] * len(okt)))
rsv = call('svm.fit', table=T, y='cls', x=['x1', 'x2', 'g'], validation='v', seed=9, keep='test-svm')
Tso = table({'x1': list(x1[:30] - 1), 'x2': list(x2[:30]), 'g': list(g[:30])}, types={'g': 'nominal'}, levels={'g': ['a', 'b', 'c']})
ss_ = call('svm.score', table=Tso, keep='test-svm')
Psv = pv.prepare(T, 'cls', ['x1', 'x2', 'g'], validation='v')
Zsv, csv_, ssv_ = zof(Psv)
msv = SVC(kernel='rbf', C=1.0, gamma=1 / Zsv.shape[1], probability=True, random_state=9).fit(Zsv[Psv.train()], Psv.target[Psv.train()])
Xso, _ = pv.score_frame(Psv, Tso)
check.near('Score Rows (SVM): another table\'s probabilities are the report\'s SVC\'s (Platt, the same seed)', mx(ss_['prob'], msv.predict_proba((Xso - csv_) / ssv_)), 0.0, abs_=1e-12)
sv_own = call('svm.save', table=T, y='cls', x=['x1', 'x2', 'g'], validation='v', seed=9)
ss2 = call('svm.score', table=T, keep='test-svm', target_rows=[0, 7])
check.near('... and the report\'s own rows as Save Predicteds gives them', mx(ss2['prob'], np.array(sv_own['prob'])[at_rows(sv_own, [0, 7])]), 0.0, abs_=1e-15)


# =======================================================================================================================
# the code under each report, run on a CSV export of the table
# =======================================================================================================================
work = tempfile.mkdtemp()
pd.DataFrame(cols).to_csv(os.path.join(work, 'data.csv'), index=False)


def run(code):
    p_ = subprocess.run([sys.executable, '-c', code], cwd=work, capture_output=True, text=True, timeout=900)
    if p_.returncode:
        print(p_.stderr[-2500:])
    return p_


def printed(text, head):
    return [[float(v) for v in ln.split()[1:]] for ln in text.splitlines() if ln.startswith(head + ' ')]


for label, kw in [('categorical, a Validation column', dict(y='cls', x=['x1', 'x2', 'g'], k=10, validation='v')),
                  ('continuous, a character Validation column', dict(y='yc', x=['x1', 'x2', 'g'], k=8, validation='vt')),
                  ('Informative Missing, no validation', dict(y='three', x=['x1m', 'gm', 'x2'], k=6)),
                  ('rows of the report, a validation portion', dict(y='cls', x=['x1', 'g'], k=7, portion=0.3, rows=list(range(20, 220)))),
                  ('Distance Weights, a K-fold Validation column', dict(table=Tk, y='cls', x=['x1', 'x2', 'g'], k=6, validation='fold', weights='distance')),
                  ('Standardize off, continuous, Distance Weights', dict(y='yc', x=['x1', 'x2'], k=5, validation='v', standardize=False, weights='distance'))]:
    kw = {'table': T, **kw}
    if kw['table'] is Tk:
        pd.DataFrame({**cols, 'fold': list(kf_col)}).to_csv(os.path.join(work, 'data.csv'), index=False)
    else:
        pd.DataFrame(cols).to_csv(os.path.join(work, 'data.csv'), index=False)
    res = call('knn.fit', table_name='data', seed=4, **kw)
    p_ = run(res['code'])
    if not check(f'K Nearest Neighbors code runs: {label}', p_.returncode, 0):
        continue
    got = printed(p_.stdout, 'k')
    key = 'rate' if res['kind'] == 'categorical' else 'rase'
    wantk = [[row['k']] + [row[f'{key}{s}'] for s in (0, 1, 2, 'cv') if f'{key}{s}' in row] for row in res['path']['rows']]
    check.near(f'... it prints every K\'s criterion of each set: {label}', mx(got, wantk) if len(got) == len(wantk) else 1.0, 0.0, abs_=1e-12)

pd.DataFrame(cols).to_csv(os.path.join(work, 'data.csv'), index=False)
for label, kw in [('weights, a Validation column', dict(y='three', x=['x1', 'x2', 'g'], validation='v', weight='w', freq='f')),
                  ('Informative Missing (both kinds)', dict(y='cls', x=['x1m', 'gm', 'x2'], validation='vt')),
                  ('Informative Missing off, alpha 0.3', dict(y='cls', x=['x1m', 'gm'], missing='drop', alpha=0.3)),
                  ('categorical factors only, rows of the report', dict(y='three', x=['g'], rows=list(range(0, 240, 2))))]:
    res = call('naivebayes.fit', table=T, table_name='data', seed=4, **kw)
    p_ = run(res['code'])
    if not check(f'Naive Bayes code runs: {label}', p_.returncode, 0):
        continue
    got = {ln.split()[0]: [float(ln.split()[2]), float(ln.split()[6])] for ln in p_.stdout.splitlines() if ln.split() and ln.split()[0] in pv.SETS}   # 'name misclassification r mean -log p m'
    wantm = {m_['set']: [m_['misclassification'], m_['mean_neg_log_p']] for m_ in res['fit']['measures']}
    check.near(f'... it prints the misclassification rate and Mean -Log p of each set: {label}', mx([got[s] for s in wantm], [wantm[s] for s in wantm]) if set(got) == set(wantm) else 1.0, 0.0, abs_=1e-12)

# pandas' default CSV parser rounds some numbers one unit in the last place off (35 of the 240 x1 here); libsvm
# stops at a tolerance of 1e-3, so a loosely converged fit (the linear SVR at Cost 100) moves by more than
# round-off. Those cases are checked to 1e-3 as shown, and to 1e-9 with the exact parser.
check('pandas\' default read_csv returns some floats one unit in the last place off (the exact parser: none)',
      (int(np.sum(pd.read_csv(os.path.join(work, 'data.csv'))['x1'].to_numpy() != x1)) > 0, int(np.sum(pd.read_csv(os.path.join(work, 'data.csv'), float_precision='round_trip')['x1'].to_numpy() != x1))), (True, 0))
EXACT = 'float_precision="round_trip")'
SVM_CASES = [('three levels, weights, a Validation column', dict(y='three', x=['x1', 'x2', 'g'], validation='v', weight='w'), 1e-9),
             ('the tuning design on the validation rows', dict(y='cls', x=['x1', 'x2', 'g'], validation='v', tune=True, points=6), 1e-9),
             ('the tuning design by cross-validation', dict(y='cls', x=['x1', 'x2'], tune=True, points=4), 1e-9),
             ('SVR, the linear kernel tuned by cross-validation', dict(y='yc', x=['x1', 'x2'], tune=True, points=3, kernel='linear'), 1e-3),
             ('SVR, Informative Missing, rows of the report', dict(y='yc', x=['x1m', 'gm'], cost=2, gamma=0.5, rows=list(range(30, 240))), 1e-9)]
for label, kw, tol in SVM_CASES:
    res = call('svm.fit', table=T, table_name='data', seed=9, **kw)
    runs = [(label, res['code'], tol)]
    if tol > 1e-9:
        runs.append((f'{label}, with the exact CSV parser', res['code'].replace('.csv")', '.csv", ' + EXACT, 1), 1e-9))
    for label_, code, tol_ in runs:
        p_ = run(code)
        if not check(f'Support Vector Machines code runs: {label_}', p_.returncode, 0):
            continue
        lines = [ln.split() for ln in p_.stdout.splitlines() if ln.split() and ln.split()[0] in pv.SETS]
        if res['kind'] == 'categorical':
            got = {t[0]: [float(t[2]), float(t[6])] for t in lines}
            wantm = {m_['set']: [m_['misclassification'], m_['mean_neg_log_p']] for m_ in res['fit']['measures']}
        else:
            got = {t[0]: [float(t[2])] for t in lines}
            wantm = {m_['set']: [m_['rase']] for m_ in res['fit']['measures']}
        check.near(f'... it prints the report\'s measures of each set: {label_}', mx([got[s] for s in wantm], [wantm[s] for s in wantm]) if set(got) == set(wantm) else 1.0, 0.0, abs_=tol_)
        if res.get('tuning'):
            des = [[float(t[1]), float(t[3])] for t in (ln.split() for ln in p_.stdout.splitlines()) if t and t[0] == 'design']
            check.near(f'... and every design point\'s criterion: {label_}', mx([d[1] for d in des], [q['crit'] for q in res['tuning']['rows']]) if len(des) == len(res['tuning']['rows']) else 1.0, 0.0, abs_=tol_)

bd = call('svm.boundary', table=T, table_name='data', y='cls', x=['x1', 'x2', 'g'], validation='v', seed=9, m=15, current={'g': 'c', 'x2': 0.2})
fit_code = call('svm.fit', table=T, table_name='data', y='cls', x=['x1', 'x2', 'g'], validation='v', seed=9)['code']
p_ = run(fit_code + '\n' + bd['code'] + '\nprint("dec", *np.ravel(dec))')
if check('the decision boundary\'s code runs after the fit\'s', p_.returncode, 0):
    check.near('... and gives the grid of the report', mx(printed(p_.stdout, 'dec')[0], np.ravel(bd['decision'])), 0.0, abs_=1e-9)

# =======================================================================================================================
# the graphs' matplotlib code, run on a CSV export: every graph of the reports
# =======================================================================================================================
from test_charts import find_line  # noqa: E402
from test_predictive import SEP, check_shared_native, joined, run_graph as run_graph_native  # noqa: E402

from smui.learners import HUES  # noqa: E402

GTMP = tempfile.mkdtemp(prefix='smui-learners-charts-')
graphs = 0


def pts_of(sc):
    return sorted((round(a, 9), round(b, 9)) for a, b in sc['xy'])


for label, kw in [('graphs: K Nearest Neighbors, two levels, a Validation column', dict(y='cls', x=['x1', 'x2', 'g'], k=10, validation='v')),
                  ('graphs: K Nearest Neighbors, continuous, K = 3 picked, rows of the report', dict(y='yc', x=['x1', 'x2', 'g'], k=8, chosen=3, validation='vt', rows=list(range(20, 220)))),
                  ('graphs: K Nearest Neighbors, three levels, Informative Missing, no validation', dict(y='three', x=['x1m', 'gm', 'x2'], k=6))]:
    res = call('knn.fit', table=T, table_name='data', seed=4, **kw)
    plots = res['fit']['plots']
    if 'rows' in kw:
        check(f'{label}: the head leaves out the rows the report leaves out', f'df = df.drop(index={sorted(set(range(n)) - set(kw["rows"]))})   # the rows the report leaves out' in plots['head_code'], True)
    graphs += check_shared_native(check, label, res['fit'], T, GTMP)
    F, err = run_graph_native(joined(plots, 'selection'), T, GTMP)
    check(f'{label}: Model Selection: the code runs, ending in plt.show()', (err, plots['selection'].rstrip().split('\n')[-1]), (None, 'plt.show()'))
    if not F:
        continue
    graphs += 1
    ax = F['axes'][0]
    cat = res['kind'] == 'categorical'
    key = 'rate' if cat else 'rase'
    what = 'Misclassification Rate' if cat else 'RASE'
    shown = [s for s in range(3) if f'{key}{s}' in res['path']['rows'][0]]
    ks = [row['k'] for row in res['path']['rows']]
    ok = []
    for i, s in enumerate(shown):
        ln = find_line(ax, ks, [row[f'{key}{s}'] for row in res['path']['rows']], rel=1e-12)
        ok.append(ln is not None and ln['label'] == pv.SETS[s] and ln['color'][:7] == HUES[i])
    check(f'{label}: Model Selection: each set\'s {what} by K, as the report has it, in its colour', ok, [True] * len(shown))
    check(f'{label}: Model Selection: the best K dotted and named', (any(q['x'] == [res['best']] * 2 and q['ls'] == ':' for q in ax['lines']), [t['s'] for t in ax['texts']]), (True, [f' best K = {res["best"]}']))
    check(f'{label}: Model Selection: the K shown (when picked), solid', any(q['x'] == [res['chosen']] * 2 and q['ls'] == '-' for q in ax['lines']), res['chosen'] != res['best'])
    check(f'{label}: Model Selection: the legend, the titles, the size', (F['legend'], ax['xlabel'], ax['ylabel'], ax['title'], F['size']), ([pv.SETS[s] for s in shown], 'K', what, f'{what} by K', [4.3, 3.0]))
    if cat:
        # the Mosaic Plot of every set: a bar per actual level as wide as its share, cut by the shares called
        for st, tail in plots['mosaic'].items():
            Fm, errm = run_graph_native(plots['head_code'] + SEP + tail, T, GTMP)
            check(f'{label}: Mosaic {st}: the code runs, ending in plt.show()', (errm, tail.rstrip().split('\n')[-1]), (None, 'plt.show()'))
            if not Fm:
                continue
            graphs += 1
            D_ = res['decided']
            k_ = pv.SETS.index(st)
            L_ = len(res['fit']['levels'])
            cm_ = np.zeros((L_, L_))
            for a_, p_ in zip([a for a, s_ in zip(D_['actual'], D_['set']) if s_ == k_], [q for q, s_ in zip(D_['pred'], D_['set']) if s_ == k_]):
                cm_[a_, p_] += 1
            wd = cm_.sum(1) / cm_.sum()
            lf = np.r_[0, np.cumsum(wd)[:-1]]
            want_b = sorted((round(lf[a_] + wd[a_] / 2 - wd[a_] * 0.98 / 2, 9), round(cm_[a_, :j].sum() / max(cm_[a_].sum(), 1), 9), round(wd[a_] * 0.98, 9), round(cm_[a_, j] / max(cm_[a_].sum(), 1), 9)) for j in range(L_) for a_ in range(L_))
            got_b = sorted((round(b_['x'], 9), round(b_['y'], 9), round(b_['w'], 9), round(b_['h'], 9)) for b_ in Fm['axes'][0]['bars'])
            check(f'{label}: Mosaic {st}: each actual level\'s bar cut by the shares of the levels called (the report\'s calls, ties at random)', got_b, want_b)
            check(f'{label}: Mosaic {st}: the legend, the titles', (Fm['legend'], Fm['axes'][0]['xlabel'], Fm['axes'][0]['title']), ([str(v) for v in res['fit']['levels']], 'Actual', f'Mosaic {st}'))

for label, kw in [('graphs: Naive Bayes, three levels, weights, Freq, a Validation column', dict(y='three', x=['x1', 'x2', 'g'], validation='v', weight='w', freq='f')),
                  ('graphs: Naive Bayes, Informative Missing, rows of the report', dict(y='cls', x=['x1m', 'gm', 'x2'], validation='vt', rows=list(range(0, 240, 2))))]:
    res = call('naivebayes.fit', table=T, table_name='data', seed=4, **kw)
    graphs += check_shared_native(check, label, res['fit'], T, GTMP)

for label, kw in [('graphs: Support Vector Machines, three levels, weights, a Validation column', dict(y='three', x=['x1', 'x2', 'g'], validation='v', weight='w')),
                  ('graphs: Support Vector Machines, the tuning design on the validation rows', dict(y='cls', x=['x1', 'x2', 'g'], validation='v', tune=True, points=6)),
                  ('graphs: Support Vector Machines, SVR, the linear kernel tuned by cross-validation', dict(y='yc', x=['x1', 'x2'], tune=True, points=3, kernel='linear')),
                  ('graphs: Support Vector Machines, SVR, Informative Missing, rows of the report', dict(y='yc', x=['x1m', 'gm'], cost=2, gamma=0.5, rows=list(range(30, 240))))]:
    res = call('svm.fit', table=T, table_name='data', seed=9, **kw)
    plots = res['fit']['plots']
    graphs += check_shared_native(check, label, res['fit'], T, GTMP)
    if 'tuning' not in res:
        check(f'{label}: no tuning design, no graph of it', 'tuning' in plots, False)
        continue
    F, err = run_graph_native(joined(plots, 'tuning'), T, GTMP)
    check(f'{label}: the tuning design: the code runs, ending in plt.show()', (err, plots['tuning'].rstrip().split('\n')[-1]), (None, 'plt.show()'))
    if not F:
        continue
    graphs += 1
    ax = F['axes'][0]
    rows_, best = res['tuning']['rows'], res['tuning']['rows'][res['tuning']['best']]
    what = res['tuning']['label']
    if res['summary']['kernel'] == 'rbf':
        check.near(f'{label}: the tuning design: a square per Cost and Gamma', mx(ax['scatter'][0]['xy'], [[q['cost'], q['gamma']] for q in rows_]), 0.0, abs_=1e-12)
        check.near(f'{label}: the tuning design: the best ringed', mx(ax['scatter'][1]['xy'], [[best['cost'], best['gamma']]]), 0.0, abs_=1e-12)
        check(f'{label}: the tuning design: coloured by the criterion (the colour bar), log axes, the titles', (F['axes'][1]['ylabel'], ax['xscale'], ax['yscale'], ax['xlabel'], ax['ylabel'], ax['title']),
              (what, 'log', 'log', 'Cost', 'Gamma', 'Tuning design'))
    else:
        check(f'{label}: the tuning design: the criterion by Cost', find_line(ax, [q['cost'] for q in rows_], [q['crit'] for q in rows_], rel=1e-9) is not None, True)
        check(f'{label}: the tuning design: the best ringed', find_line(ax, [best['cost']], [best['crit']], rel=1e-9) is not None, True)
        judged = 'Validation' if res['tuning']['how'] == 'validation' else 'Cross-Validated'
        check(f'{label}: the tuning design: a log axis, the titles', (ax['xscale'], ax['xlabel'], ax['ylabel'], ax['title']), ('log', 'Cost', f'{judged} {what}', 'Tuning design'))

for label, kw, bk in [('graphs: the decision boundary, two levels, the other factors held, support vectors ringed', dict(y='cls', x=['x1', 'x2', 'g'], validation='v', seed=9), dict(m=15, current={'g': 'c', 'x2': 0.2}, pair=['x1', 'x2'], plot={'sv': True})),
                      ('graphs: the decision boundary, three levels, no rings', dict(y='three', x=['x1', 'x2'], seed=5, portion=0.25), dict(m=11, plot={'sv': False})),
                      ('graphs: the prediction surface, a continuous response', dict(y='yc', x=['x1', 'x2', 'g'], validation='v', seed=3, cost=4, gamma=0.3), dict(m=21, current={'g': 'b'}))]:
    res = call('svm.fit', table=T, table_name='data', **kw)
    bd = call('svm.boundary', table=T, table_name='data', **kw, **bk)
    code = res['fit']['plots']['head_code'] + SEP + bd['plot_code']
    F, err = run_graph_native(code, T, GTMP)
    check(f'{label}: the code runs, ending in plt.show()', (err, code.rstrip().split('\n')[-1]), (None, 'plt.show()'))
    if not F:
        continue
    graphs += 1
    ax = F['axes'][0]
    two = 'decision' in bd
    want_img = np.clip(bd['decision'], -2.5, 2.5) if two else np.asarray(bd['most'] if bd['kind'] == 'categorical' else bd['pred'], float)
    check.near(f'{label}: the shading is the report\'s grid (the decision function, the most likely level or the prediction)', mx(ax['images'][0]['data'], np.ravel(want_img)), 0.0, abs_=1e-9)
    if two:
        check(f'{label}: the boundary (0) and the margins (-1, 1)', sorted(v for c in ax['polys'] if 'contour' in c for v in c['contour']), [-1.0, 0.0, 1.0])
    elif bd['kind'] != 'categorical':
        check(f'{label}: the prediction\'s contours, labelled; the colour bar', (len([c for c in ax['polys'] if 'contour' in c]) == 1, len(ax['texts']) > 0, F['axes'][1]['ylabel']), (True, True, 'yc'))
    P_ = bd['points']
    rings = [sc for sc in ax['scatter'] if sc['sizes'][:1] == [100.0]]
    dots = [sc for sc in ax['scatter'] if sc['sizes'][:1] != [100.0]]
    open_ = [not sc['colors'] or all(c_ == '#00000000' for c_ in sc['colors']) for sc in dots]   # facecolors "none": no face colours
    filled = sorted(q for sc, o in zip(dots, open_) if not o for q in pts_of(sc))
    hollow = sorted(q for sc, o in zip(dots, open_) if o for q in pts_of(sc))
    want_f = sorted((round(a, 9), round(b, 9)) for a, b, st in zip(P_['x'], P_['y'], P_['set']) if st == 0)
    want_h = sorted((round(a, 9), round(b, 9)) for a, b, st in zip(P_['x'], P_['y'], P_['set']) if st != 0)
    check(f'{label}: every row at its two values: the training rows filled, the others open', (len(filled), filled == want_f, len(hollow), hollow == want_h), (len(want_f), True, len(want_h), True))
    want_r = sorted((round(a, 9), round(b, 9)) for a, b, v in zip(P_['x'], P_['y'], P_['sv']) if v) if bk.get('plot', {}).get('sv', bd['kind'] == 'categorical') else []
    check(f'{label}: the support vectors ringed as the page rings them', sorted(q for sc in rings for q in pts_of(sc)), want_r)
    want_legend = (['Boundary', 'Margins (±1)'] if two else []) + ([lv for j, lv in enumerate(bd['levels']) if any(int(v) == j for v in P_['value'])] if bd['kind'] == 'categorical' else ['Rows']) + (['Support vectors'] if want_r else [])
    check(f'{label}: the legend', F['legend'], want_legend)
    what = ('Decision boundary' if bd['kind'] == 'categorical' else 'Prediction surface') + f' over {bd["pair"][0]} and {bd["pair"][1]}'
    check(f'{label}: the grid\'s range, the titles, the size', (ax['xlim'], ax['ylim'], ax['xlabel'], ax['ylabel'], ax['title'], F['size']),
          ([bd['x'][0], bd['x'][-1]], [bd['y'][0], bd['y'][-1]], bd['pair'][0], bd['pair'][1], what, [5.0, 4.4]))
check('graphs: every graph\'s code ran and drew the report\'s graph', graphs, 49)

sys.exit(check.done())
