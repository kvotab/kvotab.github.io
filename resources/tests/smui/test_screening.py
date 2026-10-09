#!/usr/bin/env python3
"""Analyze > Predictive Modeling > Fit Many Models and Make Validation Column
(resources/py/smui/screening.py).

Each fitter against scikit-learn (or statsmodels) called directly with the
same settings: the best-first tree after s splits against sklearn's tree
with s + 1 leaves, the tuned size, number of trees, layers, K and penalty
against brute-force searches over separate fits, the forest and the
boosted trees against their own predictions, Platt's sigmoid against
CalibratedClassifierCV, the discriminant against Bayes' rule with scipy's
normal densities, least squares against statsmodels WLS, the logits
against MNLogit and OrderedModel, the lasso against enet_path and AICc by
hand, stepwise against OLS fits; a frequency column against replicated
rows; the Measures of Fit helper against predictive.measures; K-fold
crossvalidation against the fitters run fold by fold; the probabilities
that must never be 0 or 1; the profiler, Save Columns and Decision
Threshold through dispatch; Make Validation Column's rounding (largest
remainders, controlled rounding of strata) by its properties; and the
Python shown under the report and in the column's notes, run on a CSV
export. It pins the scikit-learn 1.8 warning worked around, and the pandas
float parser that makes the code read with float_precision='round_trip'.

    python3 resources/tests/smui/test_screening.py
"""
import contextlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import warnings

import numpy as np
import pandas as pd

from backend import FAILED, Checks, call, table

check = Checks()
check('screening.py imports', 'screening' in FAILED, False)
from smui import predictive as pv, registry, screening as S  # noqa: E402

try:
    import sklearn
    from scipy import stats
    from scipy.special import expit
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.frozen import FrozenEstimator
    from sklearn.linear_model import Lasso, LogisticRegression, enet_path
    from sklearn.naive_bayes import CategoricalNB, GaussianNB
    from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
    from sklearn.neural_network import MLPClassifier, MLPRegressor
    from sklearn.svm import SVC, SVR
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
    from sklearn import metrics
    import statsmodels.api as sm
    from statsmodels.miscmodels.ordinal_model import OrderedModel
except ImportError as e:
    print(f'scikit-learn 1.8 and statsmodels are needed for these tests: {e}')
    sys.exit(1)
SK18 = sklearn.__version__.startswith('1.8')


def mx(a, b):
    return float(np.max(np.abs(np.asarray(a, dtype=float) - np.asarray(b, dtype=float))))


# ---- the data ------------------------------------------------------------------------------------
rng = np.random.default_rng(20260927)
n = 360
x1 = rng.normal(size=n)
x2 = rng.uniform(-2, 2, n)
x3 = rng.normal(size=n)
g = rng.choice(['a', 'b', 'c'], n, p=[0.45, 0.35, 0.2])
eta = x1 - 0.8 * x2 + 0.6 * x1 * x3 + np.where(g == 'b', 0.7, 0.0)
y = eta + rng.normal(size=n)
cls = np.where(eta + rng.logistic(size=n) > 0, 'yes', 'no')
three = np.array(['lo', 'mid', 'hi'])[np.digitize(eta + rng.logistic(size=n), [-1, 1])]
nom3 = np.array(['red', 'green', 'blue'])[np.digitize(x1 + 0.5 * rng.normal(size=n), [-0.4, 0.5])]
x1m = x1.copy()
x1m[rng.choice(n, 20, replace=False)] = np.nan
gm = g.astype(object).copy()
gm[rng.choice(n, 12, replace=False)] = None
w = rng.uniform(0.5, 2.0, n).round(3)
fq = rng.integers(1, 4, n).astype(float)
vset = rng.choice([0, 1, 2], n, p=[0.6, 0.25, 0.15])
vtxt = np.array(['Training', 'Validation', 'Test'])[vset]
cols = {'y': list(y), 'x1': list(x1), 'x2': list(x2), 'x3': list(x3), 'g': list(g), 'x1m': [None if np.isnan(v) else v for v in x1m], 'gm': list(gm),
        'cls': list(cls), 'three': list(three), 'nom3': list(nom3), 'w': list(w), 'f': list(fq), 'v': list(vtxt), 'vn': [float(v) for v in vset]}
TYPES = {'g': 'nominal', 'gm': 'nominal', 'cls': 'nominal', 'three': 'ordinal', 'nom3': 'nominal', 'v': 'nominal'}
LEVELS = {'three': ['lo', 'mid', 'hi'], 'cls': ['no', 'yes'], 'nom3': ['red', 'green', 'blue']}
T = table(cols, types=TYPES, levels=LEVELS)
X4 = ['x1', 'x2', 'x3', 'g']
SEED = 17


def prep(yname, x=X4, **kw):
    P = pv.prepare(T, yname, x, **kw)
    L = len(P.levels) if P.kind == 'categorical' else 0
    return P, L, S.factors_of(P)


# ============================================================================
# the helpers
# ============================================================================
A = np.column_stack([x1, x2, np.ones(n)])
c, s_ = S.weighted_scaler(A, w)
check.near('weighted_scaler: the weighted mean', mx(c[:2], [np.average(x1, weights=w), np.average(x2, weights=w)]), 0.0, abs_=1e-12)
check.near('... the weighted (population) standard deviation', mx(s_[:2], [math.sqrt(np.average((x1 - c[0]) ** 2, weights=w)), math.sqrt(np.average((x2 - c[1]) ** 2, weights=w))]), 0.0, abs_=1e-12)
check('... a constant column gets 1', float(s_[2]), 1.0)
yy = np.array([0, 2, 2, 1, 0, 2])
check.near('level_shares: the weighted shares', mx(S.level_shares(yy, np.array([1, 2, 1, 1, 1, 3.0]), 3), np.array([2, 1, 6]) / 9), 0.0, abs_=1e-15)
ff = np.full((6, 3), 0.2)
ff[np.arange(6), yy] = 0.6
check.near('loss: -Σ w log p of the actual level', S.loss(yy, ff, None, 3), -6 * math.log(0.6), rel=1e-12)
check.near('loss: the weighted sum of squared errors', S.loss(np.array([1.0, 2.0]), np.array([0.5, 2.5]), np.array([2.0, 1.0]), 0), 0.75, rel=1e-12)
counts = np.array([[3.0, 0.0, 0.0], [0.0, 0.0, 5.0]])
sh = np.array([0.5, 0.3, 0.2])
sm_ = S.smooth_counts(counts, sh)
check.near('smooth_counts: (count + share)/(total + 1)', mx(sm_, [[3.5 / 4, 0.3 / 4, 0.2 / 4], [0.5 / 6, 0.3 / 6, 5.2 / 6]]), 0.0, abs_=1e-15)
check('... never 0 or 1 where a leaf holds one level only', bool(np.all((sm_ > 0) & (sm_ < 1))), True)
fac = [{'name': 'a', 'kind': 'continuous', 'cols': [0], 'missing': 1}, {'name': 'b', 'kind': 'categorical', 'cols': [2, 3, 4], 'missing': 5}, {'name': 'c', 'kind': 'categorical', 'cols': [6, 7], 'missing': None}]
check('linear_columns: a categorical factor\'s last level left out, Missing columns kept', S.linear_columns(fac), [0, 1, 2, 3, 5, 6])
tr = np.zeros(50, dtype=bool)
tr[5:45] = True
fo = S.inner_folds(tr, 5, [3, 1])
check('inner_folds: every training row in one of k folds of 8, the other rows -1', (sorted(np.bincount(fo[tr]).tolist()), set(fo[~tr].tolist())), ([8] * 5, {-1}))
check('... reproducible from the seed', S.inner_folds(tr, 5, [3, 1]).tolist(), fo.tolist())
cvs = S.crossvalidation(tr, 4, 2, 9)
ok = all(np.array_equal(np.sum([h for r_, j, fr, h in cvs if r_ == r], axis=0), tr.astype(int)) for r in range(2))
check('crossvalidation: in each repeat the held-out folds cover every training row once', ok, True)
check('... a fold is fitted on the other training rows only', all(np.array_equal(fr, tr & ~h) for _, _, fr, h in cvs), True)
check('... each repeat draws new folds, the same ones from the same seed', (cvs[0][3].tolist() != cvs[4][3].tolist(), [h.tolist() for *_, h in S.crossvalidation(tr, 4, 2, 9)] == [h.tolist() for *_, h in cvs]), (True, True))

# the tree after s best-first splits is sklearn's tree with s + 1 leaves
Pc, _, _ = prep('y')
Pk, Lk, _ = prep('three')
big_r = DecisionTreeRegressor(max_leaf_nodes=40, min_samples_leaf=5, random_state=3).fit(Pc.X, Pc.target)
big_c = DecisionTreeClassifier(criterion='entropy', max_leaf_nodes=40, min_samples_leaf=5, random_state=3).fit(Pk.X, Pk.target)
paths_r, paths_c = S.tree_paths(big_r, Pc.X), S.tree_paths(big_c, Pk.X)
for s in (1, 3, 8, 20):
    small = DecisionTreeRegressor(max_leaf_nodes=s + 1, min_samples_leaf=5, random_state=3).fit(Pc.X, Pc.target)
    check.near(f'the regression tree after {s} best-first splits = sklearn\'s tree with {s + 1} leaves', mx(big_r.tree_.value[S.leaf_after(paths_r, s), 0, 0], small.predict(Pc.X)), 0.0, abs_=1e-12)
    smallc = DecisionTreeClassifier(criterion='entropy', max_leaf_nodes=s + 1, min_samples_leaf=5, random_state=3).fit(Pk.X, Pk.target)
    check.near(f'the classification tree after {s} splits = sklearn\'s with {s + 1} leaves', mx(big_c.tree_.value[S.leaf_after(paths_c, s), 0, :], smallc.predict_proba(Pk.X)), 0.0, abs_=1e-12)
check('after 0 splits every row is in the root', set(S.leaf_after(paths_r, 0).tolist()), {0})

# Platt's sigmoid = scikit-learn's calibration of a frozen SVC
Z = (Pk.X - Pk.X.mean(0)) / Pk.X.std(0)
for yv, label in ((Pk.target == 2).astype(int), 'two levels'), (Pk.target, 'three levels'):
    svc = SVC(C=1.0, gamma=1 / Z.shape[1]).fit(Z, yv)
    cal = CalibratedClassifierCV(FrozenEstimator(svc), method='sigmoid').fit(Z, yv)
    F = svc.decision_function(Z)
    if F.ndim == 1:
        a, b = S.platt(F, yv == 1)
        mine = np.column_stack([1 - expit(-(a * F + b)), expit(-(a * F + b))])
    else:
        mine = np.column_stack([expit(-(a * F[:, j] + b)) for j, (a, b) in enumerate([S.platt(F[:, j], yv == j) for j in range(3)])])
        mine /= mine.sum(1, keepdims=True)
    check.near(f'platt: = CalibratedClassifierCV(FrozenEstimator(SVC), method="sigmoid"), {label}', mx(mine, cal.predict_proba(Z)), 0.0, abs_=1e-7)
for yv in ((Pk.target == 2).astype(int), Pk.target):
    lr = LogisticRegression(C=1.0, max_iter=1000).fit(Z, yv)
    check.near(f'logit_proba = LogisticRegression.predict_proba ({len(set(yv))} levels)', mx(S.logit_proba(Z, lr.coef_, lr.intercept_), lr.predict_proba(Z)), 0.0, abs_=1e-12)

# the cumulative logit against statsmodels' OrderedModel
Ao = np.column_stack([x1, x2, x3])
yo = Pk.target
prob = S.ordinal_logit(Ao[Pk.index], yo, None, 3)
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    om = OrderedModel(yo, Ao[Pk.index], distr='logit').fit(method='bfgs', disp=False, maxiter=5000, gtol=1e-10)
ll_mine = float(np.sum(np.log(prob(Ao[Pk.index])[np.arange(len(yo)), yo])))
check('ordinal_logit: its log likelihood is at least OrderedModel\'s (both maximum likelihood)', ll_mine >= om.llf - 1e-7, True)
check.near('... and its probabilities are OrderedModel\'s', mx(prob(Ao[Pk.index]), om.predict(Ao[Pk.index])), 0.0, abs_=1e-4)
rep = np.repeat(np.arange(len(yo)), fq[Pk.index].astype(int))
check.near('... a frequency is that many copies of the row', mx(S.ordinal_logit(Ao[Pk.index], yo, fq[Pk.index], 3)(Ao[Pk.index]), S.ordinal_logit(Ao[Pk.index][rep], yo[rep], None, 3)(Ao[Pk.index])), 0.0, abs_=1e-8)
gap = S.ordinal_logit(Ao[Pk.index][yo != 1], yo[yo != 1], None, 3)(Ao[Pk.index][:5])
check('... a level with no rows gets probability 0, the others add to 1', (float(np.abs(gap[:, 1]).max()), bool(np.allclose(gap.sum(1), 1))), (0.0, True))

# the measures of the code = predictive.measures
for yname, kw in (('y', {'validation': 'v', 'weight': 'w'}), ('cls', {'validation': 'v', 'freq': 'f'}), ('three', {'validation': 'vn'})):
    P, L, _ = prep(yname, **kw)
    f = DecisionTreeRegressor(max_depth=3, random_state=0).fit(P.X, P.target).predict(P.X) if not L else \
        DecisionTreeClassifier(max_depth=3, random_state=0).fit(P.X, P.target).predict_proba(P.X) * 0.9 + 0.1 / L
    mine = S.measures(P.target, f, P.w, P.sets, L)
    theirs = {m['set']: m for m in pv.measures(P, f)}
    worst = max(abs((mine[s][k] or 0) - (theirs[s][k] or 0)) for s in theirs for k in theirs[s] if k != 'set')
    check.near(f'measures() = predictive.measures, {yname} with {", ".join(kw)}', worst, 0.0, abs_=1e-10)
check.near('auc() = predictive\'s (ties counted half, weighted)', S.auc(np.array([0.2, 0.5, 0.5, 0.9]), np.array([False, True, False, True]), np.array([1, 2, 1, 1.0])), pv._auc(np.array([0.2, 0.5, 0.5, 0.9]), np.array([False, True, False, True]), np.array([1, 2, 1, 1.0])), rel=1e-12)


# ============================================================================
# the fitters against scikit-learn called directly
# ============================================================================
Pv, _, Fv = prep('y', validation='v')
trv, tv = Pv.train(), Pv.mask(1)
Pn, _, Fn = prep('y')
trn = Pn.train()
Pb, Lb, Fb = prep('cls', validation='v')
Pt, Lt, Ft = prep('three', validation='v')

# ---- Decision Tree
pred, info = S.fit_tree(Pv.X, Pv.target, None, trv, tv, 0, Fv, SEED)
brute = []
for s in range(64):
    if s == 0:
        brute.append(float(np.sum((Pv.target[tv] - Pv.target[trv].mean()) ** 2)))
        continue
    m = DecisionTreeRegressor(max_leaf_nodes=s + 1, min_samples_leaf=5, random_state=SEED).fit(Pv.X[trv], Pv.target[trv])
    if m.get_n_leaves() < s + 1:
        break
    brute.append(float(np.sum((Pv.target[tv] - m.predict(Pv.X[tv])) ** 2)))
sb = int(np.argmin(brute))
check('Decision Tree: the number of splits with the smallest validation SSE, by separate sklearn fits', info['splits'], sb)
mb = DecisionTreeRegressor(max_leaf_nodes=sb + 1, min_samples_leaf=5, random_state=SEED).fit(Pv.X[trv], Pv.target[trv])
check.near('... its predictions are that tree\'s', mx(pred(Pv.X), mb.predict(Pv.X)), 0.0, abs_=1e-12)
pred, info = S.fit_tree(Pn.X, Pn.target, None, trn, None, 0, Fn, SEED)
fold = S.inner_folds(trn, 5, [SEED, 1])
tot = np.zeros(64)
for k in range(5):
    fit_rows, held = (fold >= 0) & (fold != k), fold == k
    curve = [float(np.sum((Pn.target[held] - Pn.target[fit_rows].mean()) ** 2))]
    for s in range(1, 64):
        m = DecisionTreeRegressor(max_leaf_nodes=s + 1, min_samples_leaf=5, random_state=SEED).fit(Pn.X[fit_rows], Pn.target[fit_rows])
        if m.get_n_leaves() < s + 1:
            break
        curve.append(float(np.sum((Pn.target[held] - m.predict(Pn.X[held])) ** 2)))
    tot += np.array(curve + [curve[-1]] * (64 - len(curve)))
full = DecisionTreeRegressor(max_leaf_nodes=64, min_samples_leaf=5, random_state=SEED).fit(Pn.X, Pn.target)
check('... without validation rows: the size with the best 5-fold crossvalidation in the training rows (separate fits)', info['splits'], int(np.argmin(tot[:full.get_n_leaves()])))
pred, info = S.fit_tree(Pt.X, Pt.target, None, Pt.train(), Pt.mask(1), Lt, Ft, SEED)
m = DecisionTreeClassifier(criterion='entropy', max_leaf_nodes=max(2, info['splits'] + 1), min_samples_leaf=5, random_state=SEED).fit(Pt.X[Pt.train()], Pt.target[Pt.train()])
leaf = m.apply(Pt.X)
cnt = m.tree_.value[:, 0, :] * m.tree_.weighted_n_node_samples[:, None]
share = np.bincount(Pt.target[Pt.train()], minlength=3) / Pt.train().sum()
if info['splits'] > 0:
    check.near('... categorical: the leaf rates with a prior of one row, (count + training share)/(n + 1)', mx(pred(Pt.X), (cnt[leaf] + share) / (cnt[leaf].sum(1, keepdims=True) + 1)), 0.0, abs_=1e-12)
pt = pred(Pt.X)
check('... never exactly 0 or 1', bool(np.all((pt > 0) & (pt < 1))), True)

# ---- Decision Forest
pred, info = S.fit_forest(Pn.X, Pn.target, None, trn, None, 0, Fn, SEED)
rf = RandomForestRegressor(n_estimators=100, max_features=max(1, round(Pn.X.shape[1] / 3)), min_samples_leaf=5, random_state=SEED, n_jobs=1).fit(Pn.X, Pn.target)
check.near('Decision Forest: = RandomForestRegressor(100 trees, a third of the columns, 5 rows a leaf)', mx(pred(Pn.X), rf.predict(Pn.X)), 0.0, abs_=1e-12)
pred, info = S.fit_forest(Pv.X, Pv.target, None, trv, tv, 0, Fv, SEED)
rf = RandomForestRegressor(n_estimators=100, max_features=max(1, round(Pv.X.shape[1] / 3)), min_samples_leaf=5, random_state=SEED, n_jobs=1).fit(Pv.X[trv], Pv.target[trv])
per = np.array([t.predict(Pv.X.astype(np.float32)) for t in rf.estimators_])
sizes = list(range(10, 101, 10))
kb = sizes[int(np.argmin([np.sum((Pv.target[tv] - per[:k, tv].mean(0)) ** 2) for k in sizes]))]
check('... with validation rows: the number of trees (10, 20, …) with the smallest validation SSE', info['trees'], kb)
check.near('... the average of those first trees', mx(pred(Pv.X), per[:kb].mean(0)), 0.0, abs_=1e-12)
pred, info = S.fit_forest(Pb.X, Pb.target, None, Pb.train(), None, Lb, Fb, SEED)
rc = RandomForestClassifier(n_estimators=100, criterion='entropy', max_features=max(1, round(math.sqrt(Pb.X.shape[1]))), min_samples_leaf=5, random_state=SEED, n_jobs=1).fit(Pb.X[Pb.train()], Pb.target[Pb.train()])
shb = np.bincount(Pb.target[Pb.train()], minlength=2) / Pb.train().sum()
avg = np.mean([((t.tree_.value[:, 0, :] * t.tree_.weighted_n_node_samples[:, None] + shb) / (t.tree_.weighted_n_node_samples[:, None] + 1))[t.apply(Pb.X.astype(np.float32))] for t in rc.estimators_], axis=0)
check.near('... categorical: the mean over the trees of their leaf rates with a prior of one row', mx(pred(Pb.X), avg), 0.0, abs_=1e-12)
check('... close to sklearn\'s own predict_proba, which has no prior', mx(pred(Pb.X), rc.predict_proba(Pb.X)) < 0.2, True)
pb_ = pred(Pb.X)
check('... never exactly 0 or 1', bool(np.all((pb_ > 0) & (pb_ < 1))), True)

# ---- Boosted Tree
pred, info = S.fit_boosted(Pn.X, Pn.target, None, trn, None, 0, Fn, SEED)
gb = GradientBoostingRegressor(n_estimators=50, learning_rate=0.1, max_leaf_nodes=4, max_depth=None, min_samples_leaf=5, random_state=SEED).fit(Pn.X, Pn.target)
check.near('Boosted Tree: = GradientBoostingRegressor(50 layers, 3 splits, learning rate 0.1)', mx(pred(Pn.X), gb.predict(Pn.X)), 0.0, abs_=1e-12)
pred, info = S.fit_boosted(Pt.X, Pt.target, None, Pt.train(), Pt.mask(1), Lt, Ft, SEED)
gc = GradientBoostingClassifier(n_estimators=50, learning_rate=0.1, max_leaf_nodes=4, max_depth=None, min_samples_leaf=5, random_state=SEED).fit(Pt.X[Pt.train()], Pt.target[Pt.train()])
stages = list(gc.staged_predict_proba(Pt.X))
vt = Pt.mask(1)
kb = int(np.argmin([-np.sum(np.log(np.clip(p[vt][np.arange(vt.sum()), Pt.target[vt]], 1e-15, 1))) for p in stages]))
check('... with validation rows: the number of layers with the smallest validation -log likelihood (staged)', info['layers'], kb + 1)
check.near('... its probabilities are that stage\'s', mx(pred(Pt.X), stages[kb]), 0.0, abs_=1e-12)

# ---- K Nearest Neighbors
pred, info = S.fit_knn(Pv.X, Pv.target, None, trv, tv, 0, Fv, SEED)
cz, sz = S.weighted_scaler(Pv.X[trv])
Zt, Zv = (Pv.X[trv] - cz) / sz, (Pv.X - cz) / sz
errs = [np.sum((Pv.target[tv] - KNeighborsRegressor(n_neighbors=k).fit(Zt, Pv.target[trv]).predict(Zv[tv])) ** 2) for k in range(1, 11)]
check('K Nearest Neighbors: K with the smallest validation SSE (KNeighborsRegressor for each K)', info['k'], int(np.argmin(errs)) + 1)
check.near('... the mean of the K nearest standardized training rows', mx(pred(Pv.X), KNeighborsRegressor(n_neighbors=info['k']).fit(Zt, Pv.target[trv]).predict(Zv)), 0.0, abs_=1e-12)
pred, info = S.fit_knn(Pn.X, Pn.target, None, trn, None, 0, Fn, SEED)
cz, sz = S.weighted_scaler(Pn.X)
Zn = (Pn.X - cz) / sz
loo = np.zeros(10)
for i in range(len(Zn)):
    others = np.arange(len(Zn)) != i
    dist = np.sqrt(((Zn[others] - Zn[i]) ** 2).sum(1))
    near = Pn.target[others][np.argsort(dist, kind='stable')[:10]]
    loo += (Pn.target[i] - np.cumsum(near) / np.arange(1, 11)) ** 2
check('... without validation rows: K with the smallest leave-one-out SSE, by hand', info['k'], int(np.argmin(loo)) + 1)
pred, info = S.fit_knn(Pt.X, Pt.target, None, Pt.train(), Pt.mask(1), Lt, Ft, SEED)
ct, st_ = S.weighted_scaler(Pt.X[Pt.train()])
Zt, Zall = (Pt.X[Pt.train()] - ct) / st_, (Pt.X - ct) / st_
sht = np.bincount(Pt.target[Pt.train()], minlength=3) / Pt.train().sum()
mis = []
for k in range(1, 11):
    kc = KNeighborsClassifier(n_neighbors=k).fit(Zt, Pt.target[Pt.train()])
    pk = (kc.predict_proba(Zall[vt]) * k + sht) / (k + 1)
    mis.append(np.sum(np.argmax(pk, 1) != Pt.target[vt]))
check('... categorical: K with the smallest validation misclassification', info['k'], int(np.argmin(mis)) + 1)
kc = KNeighborsClassifier(n_neighbors=info['k']).fit(Zt, Pt.target[Pt.train()])
check.near('... the neighbours\' level counts with a prior of one row, (count + share)/(K + 1)', mx(pred(Pt.X), (kc.predict_proba(Zall) * info['k'] + sht) / (info['k'] + 1)), 0.0, abs_=1e-12)
pk = pred(Pt.X)
check('... never exactly 0 or 1', bool(np.all((pk > 0) & (pk < 1))), True)

# ---- Naive Bayes
Pc3, L3, F3 = prep('three', x=['x1', 'x2', 'x3'])
pred, _ = S.fit_nb(Pc3.X, Pc3.target, None, Pc3.train(), None, L3, F3, SEED)
check.near('Naive Bayes, continuous factors: = GaussianNB', mx(pred(Pc3.X), GaussianNB().fit(Pc3.X, Pc3.target).predict_proba(Pc3.X)), 0.0, abs_=1e-12)
Pg, Lg, Fg = prep('three', x=['g', 'nom3'])
pred, _ = S.fit_nb(Pg.X, Pg.target, None, Pg.train(), None, Lg, Fg, SEED)
codes = np.column_stack([np.argmax(Pg.X[:, f['cols']], 1) for f in Fg])
check.near('... categorical factors: = CategoricalNB(alpha=1) on their level codes', mx(pred(Pg.X), CategoricalNB(alpha=1.0, min_categories=[3, 3]).fit(codes, Pg.target).predict_proba(codes)), 0.0, abs_=1e-12)
Pm, Lm, Fm = prep('three', x=['x1m', 'x2', 'gm'])
pred, _ = S.fit_nb(Pm.X, Pm.target, Pm.w, Pm.train(), None, Lm, Fm, SEED)
cont = [Fm[0]['cols'][0], Fm[1]['cols'][0]]
kcodes = np.column_stack([np.argmax(Pm.X[:, Fm[2]['cols'] + [Fm[2]['missing']]], 1), Pm.X[:, Fm[0]['missing']].astype(int)])
gn = GaussianNB().fit(Pm.X[:, cont], Pm.target)
cn = CategoricalNB(alpha=1.0, min_categories=[4, 2]).fit(kcodes, Pm.target)
jl = np.log(gn.class_prior_) + np.stack([np.sum(stats.norm.logpdf(Pm.X[:, cont], gn.theta_[k], np.sqrt(gn.var_[k])), 1) for k in range(3)], 1)
jl += np.stack([sum(cn.feature_log_prob_[j][k][kcodes[:, j]] for j in range(2)) for k in range(3)], 1)
check.near('... both, with Missing columns: log prior + normal log densities + level log shares, by hand', mx(pred(Pm.X), np.exp(jl - jl.max(1, keepdims=True)) / np.exp(jl - jl.max(1, keepdims=True)).sum(1, keepdims=True)), 0.0, abs_=1e-10)

# ---- Neural
pred, info = S.fit_neural(Pv.X, Pv.target, None, trv, tv, 0, Fv, SEED)
cz, sz = S.weighted_scaler(Pv.X[trv])
(ym,), (ys,) = S.weighted_scaler(Pv.target[trv][:, None])
nets = [MLPRegressor(hidden_layer_sizes=(3,), activation='tanh', solver='lbfgs', alpha=a, max_iter=2000, random_state=SEED).fit((Pv.X[trv] - cz) / sz, (Pv.target[trv] - ym) / ys) for a in (0.001, 0.01, 0.1)]
vl = [np.sum((Pv.target[tv] - (ym + ys * m.predict((Pv.X[tv] - cz) / sz))) ** 2) for m in nets]
check('Neural: the penalty with the smallest validation SSE, of MLPRegressor fits (3 tanh nodes, L-BFGS)', info['penalty'], (0.001, 0.01, 0.1)[int(np.argmin(vl))])
check.near('... its predictions are that network\'s', mx(pred(Pv.X), ym + ys * nets[int(np.argmin(vl))].predict((Pv.X - cz) / sz)), 0.0, abs_=1e-10)
pred, info = S.fit_neural(Pb.X, Pb.target, None, Pb.train(), None, Lb, Fb, SEED)
idx = np.flatnonzero(Pb.train())
hold = np.zeros(len(Pb.target), dtype=bool)
hold[idx[np.random.default_rng([SEED, 2]).permutation(len(idx))[:round(len(idx) / 3)]]] = True
cz, sz = S.weighted_scaler(Pb.X[Pb.train()])
netc = [MLPClassifier(hidden_layer_sizes=(3,), activation='tanh', solver='lbfgs', alpha=a, max_iter=2000, random_state=SEED).fit((Pb.X[Pb.train() & ~hold] - cz) / sz, Pb.target[Pb.train() & ~hold]) for a in (0.001, 0.01, 0.1)]
hl = [-np.sum(np.log(np.clip(m.predict_proba((Pb.X[hold] - cz) / sz)[np.arange(hold.sum()), Pb.target[hold]], 1e-15, 1))) for m in netc]
check('... without validation rows: the penalty by a holdback of a third of the training rows', info['penalty'], (0.001, 0.01, 0.1)[int(np.argmin(hl))])
final = MLPClassifier(hidden_layer_sizes=(3,), activation='tanh', solver='lbfgs', alpha=info['penalty'], max_iter=2000, random_state=SEED).fit((Pb.X[Pb.train()] - cz) / sz, Pb.target[Pb.train()])
check.near('... then refitted to every training row', mx(pred(Pb.X), final.predict_proba((Pb.X - cz) / sz)), 0.0, abs_=1e-10)

# ---- Support Vector Machines
pred, info = S.fit_svm(Pn.X, Pn.target, None, trn, None, 0, Fn, SEED)
cz, sz = S.weighted_scaler(Pn.X)
(ym,), (ys,) = S.weighted_scaler(Pn.target[:, None])
svr = SVR(kernel='rbf', C=1.0, gamma=1 / Pn.X.shape[1], epsilon=0.1).fit((Pn.X - cz) / sz, (Pn.target - ym) / ys)
check.near('Support Vector Machines: = SVR(RBF, cost 1, gamma 1/columns) on standardized X and Y', mx(pred(Pn.X), ym + ys * svr.predict((Pn.X - cz) / sz)), 0.0, abs_=1e-10)
pred, info = S.fit_svm(Pt.X, Pt.target, None, Pt.train(), None, Lt, Ft, SEED)
cz, sz = S.weighted_scaler(Pt.X[Pt.train()])
svc = SVC(kernel='rbf', C=1.0, gamma=1 / Pt.X.shape[1]).fit((Pt.X[Pt.train()] - cz) / sz, Pt.target[Pt.train()])
cal = CalibratedClassifierCV(FrozenEstimator(svc), method='sigmoid').fit((Pt.X[Pt.train()] - cz) / sz, Pt.target[Pt.train()])
check.near('... SVC with Platt\'s sigmoid on the training decision values = CalibratedClassifierCV(FrozenEstimator(SVC))', mx(pred(Pt.X), cal.predict_proba((Pt.X - cz) / sz)), 0.0, abs_=1e-7)

# ---- Discriminant
pred, info = S.fit_lda(Pt.X, Pt.target, None, Pt.train(), None, Lt, Ft, SEED)
cl = S.linear_columns(Ft)
At, yt = Pt.X[Pt.train()][:, cl], Pt.target[Pt.train()]
mu = np.array([At[yt == k].mean(0) for k in range(3)])
Sp = sum(((At[yt == k] - mu[k]).T @ (At[yt == k] - mu[k])) for k in range(3)) / (len(yt) - 3)
pri = np.bincount(yt) / len(yt)
lp = np.column_stack([np.log(pri[k]) + stats.multivariate_normal(mu[k], Sp).logpdf(Pt.X[:, cl]) for k in range(3)])
check.near('Discriminant: Bayes\' rule with normal densities of the pooled covariance (n - levels) and the training priors', mx(pred(Pt.X), np.exp(lp - lp.max(1, keepdims=True)) / np.exp(lp - lp.max(1, keepdims=True)).sum(1, keepdims=True)), 0.0, abs_=1e-9)
lda = LinearDiscriminantAnalysis(solver='lsqr', store_covariance=True).fit(At, yt)
check.near('... its pooled covariance is sklearn LDA\'s times n/(n - levels)', mx(Sp, lda.covariance_ * len(yt) / (len(yt) - 3)), 0.0, abs_=1e-10)

# ---- Fit Least Squares, Nominal and Ordinal Logistic
Pw, _, Fw = prep('y', validation='v', weight='w')
pred, _ = S.fit_linear(Pw.X, Pw.target, Pw.w, Pw.train(), None, 0, Fw, SEED)
cl = S.linear_columns(Fw)
wls = sm.WLS(Pw.target[Pw.train()], sm.add_constant(Pw.X[Pw.train()][:, cl]), weights=Pw.w[Pw.train()]).fit()
check.near('Fit Least Squares: = statsmodels WLS of the main effects (one level of g left out)', mx(pred(Pw.X), wls.predict(sm.add_constant(Pw.X[:, cl]))), 0.0, abs_=1e-9)
Pnm, Lnm, Fnm = prep('nom3', x=['x1', 'x2', 'g'])
pred, _ = S.fit_linear(Pnm.X, Pnm.target, None, Pnm.train(), None, Lnm, Fnm, SEED)
cl = S.linear_columns(Fnm)
mn = sm.MNLogit(Pnm.target, sm.add_constant(Pnm.X[:, cl])).fit(disp=False, method='newton', maxiter=100)
check.near('Nominal Logistic: = statsmodels MNLogit (maximum likelihood)', mx(pred(Pnm.X), mn.predict(sm.add_constant(Pnm.X[:, cl]))), 0.0, abs_=1e-6)
pred, _ = S.fit_linear(Pt.X, Pt.target, None, Pt.train(), None, Lt, Ft, SEED, ordinal=True)
cl = S.linear_columns(Ft)
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    om = OrderedModel(Pt.target[Pt.train()], Pt.X[Pt.train()][:, cl], distr='logit').fit(method='bfgs', disp=False, maxiter=5000, gtol=1e-10)
check.near('Ordinal Logistic: = statsmodels OrderedModel (cumulative logit)', mx(pred(Pt.X), om.predict(Pt.X[:, cl])), 0.0, abs_=1e-4)

# ---- Penalized Regression
pred, info = S.fit_genreg(Pv.X, Pv.target, None, trv, tv, 0, Fv, SEED)
cl = S.linear_columns(Fv)
Av = Pv.X[:, cl]
cz, sz = S.weighted_scaler(Av[trv])
Zt = (Av[trv] - cz) / sz
ym = Pv.target[trv].mean()
lams, coefs, _ = enet_path(Zt, Pv.target[trv] - ym, l1_ratio=1.0, n_alphas=100, eps=1e-3, tol=1e-8, max_iter=10000)
fits = ym + ((Av - cz) / sz) @ coefs
jv = int(np.argmin(((Pv.target[tv][:, None] - fits[tv]) ** 2).sum(0)))
check.near('Penalized Regression Lasso: the lasso path\'s penalty with the smallest validation SSE', mx(pred(Pv.X), fits[:, jv]), 0.0, abs_=1e-10)
la = Lasso(alpha=lams[jv], fit_intercept=False, tol=1e-10, max_iter=100000).fit(Zt, Pv.target[trv] - ym)
check.near('... = sklearn Lasso fitted alone at that penalty', mx(pred(Pv.X), ym + ((Av - cz) / sz) @ la.coef_), 0.0, abs_=1e-6)
pred, info = S.fit_genreg(Pn.X, Pn.target, None, trn, None, 0, Fn, SEED)
An = Pn.X[:, cl]
cz, sz = S.weighted_scaler(An)
ym = Pn.target.mean()
lams, coefs, _ = enet_path((An - cz) / sz, Pn.target - ym, l1_ratio=1.0, n_alphas=100, eps=1e-3, tol=1e-8, max_iter=10000)
N = len(Pn.target)
aicc = []
for j in range(len(lams)):
    sse = np.sum((Pn.target - ym - ((An - cz) / sz) @ coefs[:, j]) ** 2)
    k = np.count_nonzero(coefs[:, j]) + 2
    aicc.append(N * math.log(2 * math.pi * sse / N) + N + 2 * k + 2 * k * (k + 1) / (N - k - 1))
check.near('... without validation rows: the smallest AICc (−2 log L + 2k + 2k(k+1)/(N − k − 1), k nonzero + intercept + σ)', mx(pred(Pn.X), ym + ((An - cz) / sz) @ coefs[:, int(np.argmin(aicc))]), 0.0, abs_=1e-10)
pred, info = S.fit_genreg(Pv.X, Pv.target, None, trv, tv, 0, Fv, SEED, l1_ratio=0.9)
cz, sz = S.weighted_scaler(Av[trv])
lams, coefs, _ = enet_path((Av[trv] - cz) / sz, Pv.target[trv] - Pv.target[trv].mean(), l1_ratio=0.9, n_alphas=100, eps=1e-3, tol=1e-8, max_iter=10000)
fits = Pv.target[trv].mean() + ((Av - cz) / sz) @ coefs
check.near('... Elastic Net: the path with l1_ratio 0.9, chosen the same way', mx(pred(Pv.X), fits[:, int(np.argmin(((Pv.target[tv][:, None] - fits[tv]) ** 2).sum(0)))]), 0.0, abs_=1e-10)
pred, info = S.fit_genreg(Pb.X, Pb.target, None, Pb.train(), Pb.mask(1), Lb, Fb, SEED)
cl = S.linear_columns(Fb)
Ab = Pb.X[:, cl]
tb, vb = Pb.train(), Pb.mask(1)
cz, sz = S.weighted_scaler(Ab[tb])
from sklearn.svm import l1_min_c  # noqa: E402
Cs = l1_min_c((Ab[tb] - cz) / sz, Pb.target[tb], loss='log') * np.logspace(0, 4, 30)
cold = [LogisticRegression(solver='saga', l1_ratio=1.0, C=C, max_iter=5000, tol=1e-8, random_state=SEED).fit((Ab[tb] - cz) / sz, Pb.target[tb]) for C in Cs]
vloss = [-np.sum(np.log(np.clip(m.predict_proba((Ab[vb] - cz) / sz)[np.arange(vb.sum()), Pb.target[vb]], 1e-15, 1))) for m in cold]
jb = int(np.argmin(vloss))
check.near('... categorical: the l1 logistic path (30 penalties from the one that zeroes every coefficient), the best validation fit = cold saga fits', mx(pred(Pb.X), cold[jb].predict_proba((Ab - cz) / sz)), 0.0, abs_=2e-3)

# ---- Fit Stepwise
pred, info = S.fit_stepwise(Pn.X, Pn.target, None, trn, None, 0, Fn, SEED)
groups = [f['cols'][:-1] if f['kind'] == 'categorical' else f['cols'] for f in Fn]
chosen, left, steps = [], list(range(len(groups))), []
ols0 = sm.OLS(Pn.target, np.ones((len(Pn.target), 1))).fit()
steps.append(([], -2 * ols0.llf + 2 * math.log(N), ols0))
while left:
    best = min(left, key=lambda gi: sm.OLS(Pn.target, sm.add_constant(Pn.X[:, sum((groups[i] for i in chosen + [gi]), [])])).fit().ssr)
    chosen.append(best)
    left.remove(best)
    o = sm.OLS(Pn.target, sm.add_constant(Pn.X[:, sum((groups[i] for i in chosen), [])])).fit()
    steps.append((list(chosen), -2 * o.llf + (len(o.params) + 1) * math.log(N), o))
jb = int(np.argmin([s_[1] for s_ in steps]))
kept = [Fn[i]['name'] for i in steps[jb][0]]
check('Fit Stepwise: forward by the smallest SSE, stopped at the smallest BIC of statsmodels OLS fits', info['text'].endswith(', '.join(kept) if kept else 'none'), True)
Xs = sm.add_constant(Pn.X[:, sum((groups[i] for i in steps[jb][0]), [])]) if steps[jb][0] else np.ones((N, 1))
check.near('... its predictions are that OLS fit\'s', mx(pred(Pn.X), steps[jb][2].predict(Xs)), 0.0, abs_=1e-9)

# ---- a frequency column is that many copies of the row
Pf, _, Ff = prep('y', freq='f')
Pr = pv.prepare(table({k: [v[i] for i in np.repeat(np.arange(n), fq.astype(int))] for k, v in cols.items()}, types=TYPES, levels=LEVELS), 'y', X4)
allf, allr = Pf.train(), Pr.train()
for key, fn, kw in (('Fit Least Squares', S.fit_linear, {}), ('Penalized Regression Lasso', S.fit_genreg, {}), ('Fit Stepwise', S.fit_stepwise, {})):
    a, _ = fn(Pf.X, Pf.target, Pf.w, allf, None, 0, Ff, SEED, **kw)
    b, _ = fn(Pr.X, Pr.target, None, allr, None, 0, Ff, SEED, **kw)
    check.near(f'{key}: a Freq column = its rows repeated', mx(a(Pf.X), b(Pf.X)), 0.0, abs_=1e-7)
Pf, Lf, Ff = prep('three', freq='f')
Pr = pv.prepare(table({k: [v[i] for i in np.repeat(np.arange(n), fq.astype(int))] for k, v in cols.items()}, types=TYPES, levels=LEVELS), 'three', X4)
for key, fn, kw, tol in (('Nominal Logistic', S.fit_linear, {}, 1e-6), ('Ordinal Logistic', S.fit_linear, {'ordinal': True}, 1e-7), ('Discriminant', S.fit_lda, {}, 1e-10), ('Naive Bayes', S.fit_nb, {}, 1e-10)):
    a, _ = fn(Pf.X, Pf.target, Pf.w, Pf.train(), None, Lf, Ff, SEED, **kw)
    b, _ = fn(Pr.X, Pr.target, None, Pr.train(), None, Lf, Ff, SEED, **kw)
    check.near(f'{key}: a Freq column = its rows repeated', mx(a(Pf.X), b(Pf.X)), 0.0, abs_=tol)

# ---- scikit-learn 1.8, and pandas
if SK18:
    with warnings.catch_warnings(record=True) as wl:
        warnings.simplefilter('always')
        LogisticRegression(C=np.inf, max_iter=1000).fit(Z, Pk.target)
    check('scikit-learn 1.8 warns "Setting penalty=None will ignore the C and l1_ratio parameters" for its own C=np.inf (worked around)',
          any('Setting penalty=None will ignore the C and l1_ratio parameters' in str(x.message) for x in wl), True)
with warnings.catch_warnings(record=True) as wl:
    warnings.simplefilter('always')
    S.fit_quietly(LogisticRegression(C=np.inf, max_iter=1), Z, Pk.target)
msgs = [str(x.message) for x in wl]
check('fit_quietly drops only that warning: a ConvergenceWarning still comes through', (any('Setting penalty=None' in m for m in msgs), any(issubclass(x.category, ConvergenceWarning) for x in wl)), (False, True))
with tempfile.TemporaryDirectory() as tmp:
    pd.DataFrame(cols).to_csv(os.path.join(tmp, 'd.csv'), index=False)
    d0 = pd.read_csv(os.path.join(tmp, 'd.csv'))
    d1 = pd.read_csv(os.path.join(tmp, 'd.csv'), float_precision='round_trip')
check('pandas\' default CSV float parser is off by a unit in the last place in some values (so the code reads with round_trip)', bool(np.any(d0['y'].to_numpy() != y)), True)
check('... the round-trip parser gives every value back exactly', bool(np.array_equal(d1['y'].to_numpy(), y)), True)


# ============================================================================
# the platform: screening.fit and friends, through dispatch
# ============================================================================
ALL = [k for k, _ in S.METHODS]


def quiet(fn, *a, **kw):
    """call(...) with its progress lines kept out of the test's output."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn(*a, **kw)
    return out, buf.getvalue()


def fit(**kw):
    return quiet(call, 'screening.fit', table=T, **kw)


r, out = fit(y='y', x=['x1m', 'x2', 'x3', 'gm'], validation='v', weight='w', seed=SEED, methods=ALL)
check('continuous Y: every method but Naive Bayes and Discriminant, in JMP\'s order', [m['key'] for m in r['methods']], [k for k in ALL if k not in ('nb', 'lda')])
check('the sets of the Validation column', (r['sets'], r['n']), (['Training', 'Validation', 'Test'], {'Training': int((vset == 0).sum()), 'Validation': int((vset == 1).sum()), 'Test': int((vset == 2).sum())}))
Pr_ = pv.prepare(T, 'y', ['x1m', 'x2', 'x3', 'gm'], validation='v', weight='w')
worst = 0.0
for m in r['methods']:
    fn = S.FITTERS[m['key']]
    p_, _ = fn(Pr_.X, Pr_.target, Pr_.w, Pr_.train(), Pr_.mask(1), 0, S.factors_of(Pr_), SEED, **S.EXTRA.get(m['key'], {}))
    want = {x['set']: x for x in pv.measures(Pr_, p_(Pr_.X))}
    worst = max(worst, max(abs((m['measures'][s][k] or 0) - (want[s][k] or 0)) for s in want for k in want[s] if k != 'set'))
check.near('each method\'s measures are predictive.measures of the fitter run directly', worst, 0.0, abs_=1e-10)
comp = r['compare']
vals = {m['key']: m['measures'][comp]['rsquare'] for m in r['methods']}
check('compared on the validation rows, ranked by validation RSquare', (comp, r['order']), ('Validation', sorted(vals, key=lambda k: -vals[k])))
check('the best of each column is marked', r['best']['Test']['rase'], [min(r['methods'], key=lambda m: m['measures']['Test']['rase'])['key']])
check('with RSquare and RASE of one set the dominant method is the best one', r['dominant'], [r['order'][0]])
prog = [ln.split() for ln in out.splitlines() if ln.startswith('smui:progress screening')]
check('progress lines count the fits up to the total', (prog[-1][2] == prog[-1][3], int(prog[-1][3])), (True, len(r['methods'])))
check('actual by predicted: every method\'s predictions of every row', (len(r['residuals']['rows']), sorted(r['residuals']['predicted'])), (len(Pr_.index), sorted(m['key'] for m in r['methods'])))

r, _ = fit(y='nom3', x=['x1', 'x2', 'g'], portion=0.25, seed=SEED, methods=ALL)
check('nominal Y: every method, the linear one Nominal Logistic', ([m['key'] for m in r['methods']], r['methods'][ALL.index('linear')]['label']), (ALL, 'Nominal Logistic'))
check('a holdback of 25%', (r['sets'], r['n']['Validation']), (['Training', 'Validation'], int(round(0.25 * n))))
Pq = pv.prepare(T, 'nom3', ['x1', 'x2', 'g'], portion=0.25, seed=SEED)
f_ = S.FITTERS['boosted'](Pq.X, Pq.target, None, Pq.train(), Pq.mask(1), 3, S.factors_of(Pq), SEED)[0](Pq.X)
check('ROC and lift curves: predictive.roc and lift of each method', (r['roc']['boosted'] == json.loads(json.dumps(pv.roc(Pq, f_, most=160))), len(r['lift']['boosted'])), (True, 6))
check.near('... their AUC is the method\'s', next(c_['auc'] for c_ in r['roc']['boosted'] if c_['set'] == 'Validation' and c_['level'] == 'red'), pv.roc(Pq, f_)[3]['auc'], rel=1e-12)
keys3 = ['generalized_rsquare', 'entropy_rsquare', 'misclassification']
up = {'generalized_rsquare', 'entropy_rsquare'}
good = [(m['key'], m['measures']['Validation']) for m in r['methods']]
brute = [k for k, v in good if not any(all(u[q] >= v[q] if q in up else u[q] <= v[q] for q in keys3) and any(u[q] > v[q] if q in up else u[q] < v[q] for q in keys3) for k2, u in good if k2 != k)]
check('dominant: no other method as good on Generalized and Entropy RSquare and misclassification and better on one (by brute force)', r['dominant'], brute)
check('three levels: no AUC in the summary, Generalized RSquare first (JMP ranks by it)', r['summary'], keys3)
vg = {m['key']: m['measures']['Validation']['generalized_rsquare'] for m in r['methods']}
check('... the methods ranked by the validation Generalized RSquare', r['order'], sorted(vg, key=lambda k: -vg[k]))

r, _ = fit(y='cls', x=X4, validation='v', freq='f', seed=SEED, methods=['tree', 'forest', 'knn', 'linear'])
check('two levels: AUC in the summary', r['summary'], ['generalized_rsquare', 'entropy_rsquare', 'misclassification', 'auc'])
check('the curves are there for every set', sorted({c_['set'] for c_ in r['roc']['tree']}), ['Test', 'Training', 'Validation'])

# ---- XGBoost, LightGBM and Ridge against the packages called directly ------------------------------------------------
import xgboost as xgb  # noqa: E402
import lightgbm as lgbm  # noqa: E402
import warnings as _w  # noqa: E402
_w.filterwarnings('ignore', message='X does not have valid feature names')   # lightgbm's own column names, called here directly
from sklearn.linear_model import LinearRegression, Ridge  # noqa: E402
Pv = pv.prepare(T, 'cls', X4, validation='v', freq='f')
tr_, va_ = Pv.train(), Pv.mask(1)
fx, ix = S.fit_xgboost(Pv.X, Pv.target, Pv.w, tr_, va_, 2, S.factors_of(Pv), SEED)
bx = xgb.XGBClassifier(n_estimators=100, max_depth=6, learning_rate=0.3, n_jobs=1, random_state=SEED).fit(Pv.X[tr_], Pv.target[tr_], sample_weight=Pv.w[tr_])
lx = [float(-np.sum(Pv.w[va_] * np.log(np.clip(bx.predict_proba(Pv.X[va_], iteration_range=(0, k))[np.arange(va_.sum()), Pv.target[va_]], 1e-15, 1)))) for k in range(1, 101)]
ux = int(np.argmin(lx)) + 1
check('XGBoost: the rounds with the smallest validation -log-likelihood, by hand', ix['rounds'], ux)
check.near('... its probabilities are xgboost\'s XGBClassifier at that many rounds (defaults: depth 6, learning rate 0.3)', mx(fx(Pv.X), bx.predict_proba(Pv.X, iteration_range=(0, ux))), 0.0, abs_=1e-7)
Pc_ = pv.prepare(T, 'y', X4, validation='v', weight='w')
trc, vac = Pc_.train(), Pc_.mask(1)
fl, il = S.fit_lightgbm(Pc_.X, Pc_.target, Pc_.w, trc, vac, 0, S.factors_of(Pc_), SEED)
bl = lgbm.LGBMRegressor(n_estimators=100, num_leaves=31, learning_rate=0.1, min_child_samples=20, n_jobs=1, random_state=SEED, verbose=-1, deterministic=True, force_row_wise=True).fit(Pc_.X[trc], Pc_.target[trc], sample_weight=Pc_.w[trc])
ll_ = [float(np.sum(Pc_.w[vac] * (Pc_.target[vac] - bl.predict(Pc_.X[vac], num_iteration=k)) ** 2)) for k in range(1, bl.booster_.current_iteration() + 1)]
ul = int(np.argmin(ll_)) + 1
check('LightGBM: the rounds with the smallest validation squared error, by hand', il['rounds'], ul)
check.near('... its predictions are lightgbm\'s LGBMRegressor at that many rounds (its defaults)', mx(fl(Pc_.X), bl.predict(Pc_.X, num_iteration=ul)), 0.0, abs_=1e-9)
fr_, ir_ = S.fit_ridge(Pc_.X, Pc_.target, Pc_.w, trc, None, 0, S.factors_of(Pc_), SEED)
cols_r = S.linear_columns(S.factors_of(Pc_))
A_ = Pc_.X[:, cols_r]
cen, sc_ = S.weighted_scaler(A_[trc], Pc_.w[trc])
Z_ = (A_ - cen) / sc_
sw_ = Pc_.w[trc] / Pc_.w[trc].mean()
lam_ = float(ir_['text'].split('penalty ')[1].split(' ')[0])
U_, sv_, Vt_ = np.linalg.svd(Z_[trc] * np.sqrt(sw_)[:, None], full_matrices=False)
grid_ = float(sv_[0] ** 2) * np.logspace(-6, 2, 60)[::-1]
ym_ = np.average(Pc_.target[trc], weights=sw_)
aicc_ = []
for lam in grid_:
    b_ = Ridge(alpha=lam, fit_intercept=False).fit(Z_[trc] * np.sqrt(sw_)[:, None], (Pc_.target[trc] - ym_) * np.sqrt(sw_)).coef_
    e_ = float(Pc_.w[trc] @ (Pc_.target[trc] - ym_ - Z_[trc] @ b_) ** 2)
    k_ = float(np.sum(sv_ ** 2 / (sv_ ** 2 + lam))) + 2
    N_ = Pc_.w[trc].sum()
    aicc_.append(N_ * (math.log(2 * math.pi * e_ / N_) + 1) + 2 * k_ + 2 * k_ * (k_ + 1) / (N_ - k_ - 1))
jb = int(np.argmin(aicc_))
rb_ = Ridge(alpha=grid_[jb], fit_intercept=True).fit(Z_[trc], Pc_.target[trc], sample_weight=sw_)
check.near('Ridge: the penalty of the smallest AICc (the degrees of freedom the hat matrix\'s trace), by sklearn\'s Ridge along the same path', lam_, float(grid_[jb]), rel=5e-4)
check.near('... its predictions are sklearn Ridge\'s at that penalty (weighted, on the centred and scaled columns)', mx(fr_(Pc_.X), rb_.predict(Z_)), 0.0, abs_=1e-8)
frc, irc = S.fit_ridge(Pv.X, Pv.target, Pv.w, tr_, va_, 2, S.factors_of(Pv), SEED)
Av = Pv.X[:, S.linear_columns(S.factors_of(Pv))]
cv_, scv = S.weighted_scaler(Av[tr_], Pv.w[tr_])
Zv = (Av - cv_) / scv
best_ = min(np.logspace(-4, 3, 30), key=lambda C: -np.sum(Pv.w[va_] * np.log(np.clip(LogisticRegression(C=C, max_iter=2000, tol=1e-8).fit(Zv[tr_], Pv.target[tr_], sample_weight=Pv.w[tr_]).predict_proba(Zv[va_])[np.arange(va_.sum()), Pv.target[va_]], 1e-15, 1))))
check.near('Ridge, two levels: the probabilities of sklearn\'s LogisticRegression at the C of the best validation log-likelihood', mx(frc(Pv.X), LogisticRegression(C=best_, max_iter=2000, tol=1e-8).fit(Zv[tr_], Pv.target[tr_], sample_weight=Pv.w[tr_]).predict_proba(Zv)), 0.0, abs_=1e-6)
# the Two Way Interactions and Quadratic options: least squares on the design written out by hand
f2, i2 = S.fit_linear(Pc_.X, Pc_.target, Pc_.w, trc, vac, 0, S.factors_of(Pc_), SEED, terms={'interactions': True, 'quadratic': True})
fac = S.factors_of(Pc_)
parts_ = [(f_['cols'][:-1] if f_['kind'] == 'categorical' else f_['cols'], f_['kind']) for f_ in fac]
ctr = {c: Pc_.X[trc, c].mean() for f_ in fac if f_['kind'] == 'continuous' for c in f_['cols']}
cols2 = [Pc_.X[:, S.linear_columns(fac)]]
for a_ in range(len(parts_)):
    for b2 in range(a_ + 1, len(parts_)):
        for i_ in parts_[a_][0]:
            for j_ in parts_[b2][0]:
                cols2.append(((Pc_.X[:, i_] - ctr.get(i_, 0)) * (Pc_.X[:, j_] - ctr.get(j_, 0)))[:, None])
cols2 += [((Pc_.X[:, c] - ctr[c]) ** 2)[:, None] for c in ctr]
D2 = np.hstack(cols2)
check('Two Way Interactions and Quadratics: every pair of factors\' columns and every continuous square (x1, x2, x3 and g: 3 + 2 main-effect columns, 3 + 6 products, 3 squares)', D2.shape[1], 17)
check.near('... Fit Least Squares on that design is sklearn\'s LinearRegression (weighted), the continuous columns centred at their training means', mx(f2(Pc_.X), LinearRegression().fit(D2[trc], Pc_.target[trc], sample_weight=Pc_.w[trc]).predict(D2)), 0.0, abs_=1e-9)
rt_, _ = fit(y='y', x=X4, validation='v', weight='w', seed=SEED, methods=['linear', 'lasso', 'tree'], interactions=True, quadratic=True)
check('... the report\'s Fit Least Squares is that model, the tree is untouched by the options', (next(m for m in rt_['methods'] if m['key'] == 'linear')['info'], abs(next(m for m in rt_['methods'] if m['key'] == 'tree')['measures']['Validation']['rsquare'] - next(m for m in fit(y='y', x=X4, validation='v', weight='w', seed=SEED, methods=['tree'])[0]['methods'])['measures']['Validation']['rsquare']) < 1e-12),
      ('the main effects and two-way interactions and squares, 17 terms and an intercept', True))

# ---- Ensemble of Selected: the average and the stacking weights ---------------------------------------------------------
en, _ = quiet(call, 'screening.ensemble', table=T, y='y', x=X4, validation='v', weight='w', seed=SEED, methods=['linear', 'tree', 'knn'])
ms_ = {k: S._model(T, None, S._spec({'y': 'y', 'x': X4, 'validation': 'v', 'weight': 'w', 'seed': SEED, 'kfold': 0}), k)['predict'](Pc_.X) for k in ['linear', 'tree', 'knn']}
avg_ = np.mean([ms_[k] for k in ['tree', 'knn', 'linear'] if k in ms_], axis=0)
check.near('Average of Selected: the measures of the mean of the methods\' predictions', en['rows'][0]['measures']['Validation']['rsquare'], next(q for q in pv.measures(Pc_, avg_) if q['set'] == 'Validation')['rsquare'], rel=1e-12)
wts_ = [q['weight'] for q in en['weights']]
check('Stacked: the weights 0 or more, adding to 1', (min(wts_) >= 0, abs(sum(wts_) - 1) < 1e-12), (True, True))
F2 = np.stack([rng.normal(size=80) + np.linspace(0, 3, 80), np.linspace(0, 3, 80) + 0.3 * rng.normal(size=80)])
t2 = np.linspace(0, 3, 80) + 0.2 * rng.normal(size=80)
sw2 = S.stack_weights(F2, t2, None, 0)
grid2 = np.linspace(0, 1, 20001)
obj = [np.mean((t2 - (a * F2[0] + (1 - a) * F2[1])) ** 2) for a in grid2]
check('stack_weights, two methods: the convex combination of the smallest squared error (a grid of 20001 weights)', abs(float(sw2[0]) - float(grid2[int(np.argmin(obj))])) <= 1e-4, True)
P3_ = np.stack([np.column_stack([1 - q, q]) for q in (np.clip(0.5 + 0.3 * rng.normal(size=60), 0.01, 0.99), np.clip(0.5 + 0.1 * rng.normal(size=60), 0.01, 0.99))])
y3_ = (rng.uniform(size=60) < 0.5).astype(int)
sw3 = S.stack_weights(P3_, y3_, None, 2)
obj3 = [-np.mean(np.log((a * P3_[0] + (1 - a) * P3_[1])[np.arange(60), y3_])) for a in grid2]
check('stack_weights, probabilities: the convex combination of the largest log-likelihood (the grid)', abs(float(sw3[0]) - float(grid2[int(np.argmin(obj3))])) <= 1e-4, True)

# a method that cannot fit these rows says so; the others still fit
bad = {'y2': ['no'] * 30 + ['yes'] * 10 + ['no'] * 10, 'x': list(rng.normal(size=50)), 'v': ['Training'] * 30 + ['Validation'] * 20}
Tb = table(bad, types={'y2': 'nominal', 'v': 'nominal'})
rb, _ = quiet(call, 'screening.fit', table=Tb, y='y2', x=['x'], validation='v', seed=1, methods=['tree', 'svm', 'linear'])
errs = {m['key']: m.get('error') for m in rb['methods']}
check('a training set with one level: SVC and the logit fail with their messages, the tree still fits', (errs['tree'] is None, 'ValueError' in (errs['svm'] or ''), 'ValueError' in (errs['linear'] or '')), (True, True, True))
check('... and the failed ones are ranked last', rb['order'][-2:], ['svm', 'linear'])

# K-fold crossvalidation, repeated
small = {k: v[:150] for k, v in cols.items()}
Ts = table(small, types=TYPES, levels=LEVELS)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rk = call('screening.fit', table=Ts, y='cls', x=X4, portion=0.3, seed=SEED, methods=['tree', 'knn', 'linear', 'nb'], kfold=3, repeats=2)
check('K-fold: the Validation Portion is left out, and said so', (rk['sets'], rk['kfold'], rk['repeats'], any('Validation Portion is not used' in t for t in rk['notes'])), (['Training'], 3, 2, True))
Pks = pv.prepare(Ts, 'cls', X4)
worst, nf = 0.0, 0
for m in rk['methods']:
    held = []
    for r_, j, fr, h in S.crossvalidation(Pks.train(), 3, 2, SEED):
        p_, _ = S.FITTERS[m['key']](Pks.X, Pks.target, None, fr, None, 2, S.factors_of(Pks), SEED)
        held.append(S.measures(Pks.target, p_(Pks.X), None, np.where(h, 1, np.where(fr, 0, -1)), 2)['Validation'])
    nf = len(held)
    for k in ('entropy_rsquare', 'misclassification', 'auc', 'rase'):
        worst = max(worst, abs(m['measures']['Crossvalidation'][k] - np.mean([x[k] for x in held])))
        worst = max(worst, abs(m['cv']['sd'][k] - np.std([x[k] for x in held], ddof=1)))
check.near('the Crossvalidation means and SDs are those of the folds refitted here, each tuned without its fold', worst, 0.0, abs_=1e-10)
check('six folds in all, each fold listed', (nf, len(rk['methods'][0]['cv']['folds'])), (6, 6))
check('the curves of the out-of-fold predictions are the Crossvalidation set', sorted({c_['set'] for c_ in rk['roc']['tree']}), ['Crossvalidation', 'Training'])
prog = [ln.split() for ln in buf.getvalue().splitlines() if ln.startswith('smui:progress screening')]
check('progress: 4 methods fitted once and 6 times more', (int(prog[-1][2]), int(prog[-1][3])), (28, 28))
rk2, _ = quiet(call, 'screening.fit', table=Ts, y='cls', x=X4, validation='v', seed=SEED, methods=['tree'], kfold=5)
check('K-fold with a Validation column: its sets win, and the report says so', (rk2['kfold'], any('K-fold crossvalidation is not used' in t for t in rk2['notes'])), (0, True))

# warnings of a fit come back with the method's name
with warnings.catch_warnings(record=True) as wl:
    warnings.simplefilter('always')
    (_, caught) = S._caught(lambda: warnings.warn('lbfgs failed to converge after 5 iteration(s) (status=1):\nSTOP: TOTAL NO. OF ITERATIONS', ConvergenceWarning))
    S._warn('Neural', caught)
check('a method\'s warning is shown with its name, first line only', [str(x.message) for x in wl], ['Neural: lbfgs failed to converge after 5 iteration(s) (status=1)'])

# ---- the profiler, Save Columns, Decision Threshold
base = dict(y='three', x=X4, validation='v', seed=SEED)
Pp = pv.prepare(T, 'three', X4, validation='v')
M, _ = quiet(S._model, T, None, S._spec({**base, 'kfold': 0}), 'lda')
rp, _ = quiet(call, 'screening.profile', table=T, method='lda', current={'x1': 0.5, 'g': 'b'}, grid=9, **base)
check('Prediction Profiler of a method: one probability per level, summing to 1', ([q['name'] for q in rp['responses']], bool(np.allclose(np.sum([q['traces'][0]['pred'] for q in rp['responses']], axis=0), 1))), (['Prob[lo]', 'Prob[mid]', 'Prob[hi]'], True))
cur = {f_['name']: f_['current'] for f_ in rp['factors']}
check.near('... the current prediction is the method\'s', rp['responses'][2]['current']['pred'], float(M['predict'](Pp.encode_settings([cur]))[0, 2]), rel=1e-12)
check('... and the profiler has its maximize and importance functions', ('screening.maximize' in registry.names(), 'screening.importance' in registry.names()), (True, True))
sv, _ = quiet(call, 'screening.save', table=T, method='knn', **base)
Mk, _ = quiet(S._model, T, None, S._spec({**base, 'kfold': 0}), 'knn')
Xall, rows_all = Pp.all_rows()
check('Save Columns: every row of the table, with the method in the names', (len(sv['rows']), sv['names'][0], sv['most_name']), (n, 'Prob[lo] K Nearest Neighbors', 'Most Likely three K Nearest Neighbors'))
check.near('... the probabilities are the method\'s for every row', mx(sv['prob'], Mk['predict'](Xall)), 0.0, abs_=1e-12)
svc_, _ = quiet(call, 'screening.save', table=T, method='linear', y='y', x=X4, validation='v', seed=SEED)
check('... continuous: the prediction and its name', svc_['name'], 'Predicted y Fit Least Squares')
th, _ = quiet(call, 'screening.threshold', table=T, y='cls', x=X4, validation='v', seed=SEED, methods=['tree', 'linear'], plot={'order': ['linear', 'tree']})
Pc2 = pv.prepare(T, 'cls', X4, validation='v')
Ml, _ = quiet(S._model, T, None, S._spec({'y': 'cls', 'x': X4, 'validation': 'v', 'seed': SEED, 'kfold': 0}), 'linear')
pl = Ml['predict'](Pc2.X)[:, 1]
check('Decision Threshold: the methods in the order asked for, each row\'s probability of the second level the method\'s', ([m['label'] for m in th['models']], mx(th['models'][0]['p'], pl) <= 1e-12),
      (['Nominal Logistic', 'Decision Tree'], True))
check('... the levels, the sets, each row\'s number, set and level', (th['levels'], th['sets'], th['points']['rows'] == Pc2.index.tolist(), th['points']['set'] == Pc2.sets.tolist(), th['points']['actual'] == Pc2.target.tolist()),
      (Pc2.labels, ['Training', 'Validation', 'Test'], True, True, True))
vm = Pc2.mask(1)
tp = int(np.sum((pl >= 0.4) & (Pc2.target == 1) & vm))
fp = int(np.sum((pl >= 0.4) & (Pc2.target == 0) & vm))
fn_ = int(np.sum((pl < 0.4) & (Pc2.target == 1) & vm))
tn = int(np.sum((pl < 0.4) & (Pc2.target == 0) & vm))
cvl = pv.cut_table(np.asarray(th['models'][0]['p'])[vm], Pc2.target[vm] == 1)
lv = pv.rates_at(*pv.counts_at(cvl, 0.4))
check('Decision Threshold: the counts at 0.4 from the rows\' probabilities (as the page computes them), by hand', (lv['tp'], lv['fp'], lv['fn'], lv['tn']), (tp, fp, fn_, tn))
check.near('... sensitivity, specificity, precision and F1', mx([lv['sensitivity'], lv['specificity'], lv['precision'], lv['f1']], [tp / (tp + fn_), tn / (tn + fp), tp / (tp + fp), 2 * tp / (2 * tp + fp + fn_)]), 0.0, abs_=1e-12)
th3, _ = quiet(call, 'screening.threshold', table=Ts, y='cls', x=X4, kfold=3, repeats=2, seed=SEED, methods=['knn', 'linear'])
cvk, _ = quiet(S._crossvalidated, Ts, None, S._spec({'y': 'cls', 'x': X4, 'seed': SEED, 'kfold': 3}), 'knn', 2)
check('Decision Threshold with K Fold: a Crossvalidation set of every row, each predicted by the model fitted without its fold (the first repeat)', (th3['sets'], mx(th3['models'][0]['p_cv'], cvk['oof'][:, 1]) <= 1e-12), (['Training', 'Crossvalidation'], True))
try:
    call('screening.threshold', table=T, y='three', x=X4, seed=SEED)
    check('Decision Threshold is for two levels', 'no error', 'error')
except ValueError as e:
    check('Decision Threshold is for two levels', 'two levels' in str(e), True)


# ============================================================================
# Make Validation Column
# ============================================================================
check('split_counts: 10 rows at .6/.2/.2', S.split_counts(10, [0.6, 0.2, 0.2]).tolist(), [6, 2, 2])
check('... 7 rows: floors 4, 1, 1 and the row left over to the larger remainder (a tie to the earlier set)', S.split_counts(7, [0.6, 0.2, 0.2]).tolist(), [4, 2, 1])
check('... proportions that do not add to 1 are scaled', S.split_counts(100, [3, 1, 1]).tolist(), [60, 20, 20])
rs = np.random.default_rng(1)
okc = True
for _ in range(400):
    m_ = int(rs.integers(1, 500))
    pr_ = rs.dirichlet([1, 1, 1])
    k_ = S.split_counts(m_, pr_)
    exact = m_ * pr_
    up_ = np.flatnonzero(k_ > np.floor(np.round(exact, 9)))
    down = np.flatnonzero(k_ == np.floor(np.round(exact, 9)))
    okc &= int(k_.sum()) == m_ and bool(np.all(np.abs(k_ - exact) < 1)) and (not len(up_) or not len(down) or min(exact[up_] - np.floor(exact[up_])) >= max(exact[down] - np.floor(exact[down])) - 1e-9)
check('... 400 random cases: the counts add up, each within one row of its share, the largest remainders rounded up', okc, True)
okc, hard = True, 0
for _ in range(400):
    J = int(rs.integers(1, 25))
    sizes = rs.integers(1, 12, J)
    pr_ = rs.dirichlet([2, 1, 1])
    C_ = S.stratum_counts(sizes, pr_)
    E = sizes[:, None] * pr_[None, :]
    okc &= bool(np.array_equal(C_.sum(1), sizes)) and bool(np.array_equal(C_.sum(0), S.split_counts(int(sizes.sum()), pr_))) and bool(np.all((C_ >= np.floor(E - 1e-9)) & (C_ <= np.ceil(E + 1e-9))))
    # would the largest remainders alone have done it?
    Fl = np.floor(np.round(E, 9)).astype(int)
    nr, nc = sizes - Fl.sum(1), S.split_counts(int(sizes.sum()), pr_) - Fl.sum(0)
    for _, j, k in sorted((-(E[j, k] - Fl[j, k]), j, k) for j in range(J) for k in range(3) if E[j, k] - Fl[j, k] > 1e-9):
        if nr[j] > 0 and nc[k] > 0:
            nr[j] -= 1
            nc[k] -= 1
    hard += int(nr.any())
check('stratum_counts, 400 random tables: every stratum placed, the set totals those of the unstratified split, each cell its share rounded down or up', okc, True)
check(f'... including the {hard} tables the largest remainders alone could not round (augmenting paths)', hard > 0, True)
sets = S.make_sets(1000, [0.7, 0.2, 0.1], 5)
check('make_sets, random: exactly the counts', np.bincount(sets).tolist(), [700, 200, 100])
check('... the same seed the same rows, another seed others', (S.make_sets(1000, [0.7, 0.2, 0.1], 5).tolist() == sets.tolist(), S.make_sets(1000, [0.7, 0.2, 0.1], 6).tolist() == sets.tolist()), (True, False))
strata = rs.integers(0, 7, 500)
sets = S.make_sets(500, [0.6, 0.2, 0.2], 3, strata=strata)
per = np.array([[np.sum((strata == j) & (sets == k)) for k in range(3)] for j in range(7)])
E = np.bincount(strata)[:, None] * np.array([0.6, 0.2, 0.2])
check('... stratified: every stratum\'s count of each set its share rounded down or up', bool(np.all((per >= np.floor(E - 1e-9)) & (per <= np.ceil(E + 1e-9)))), True)
check('... and the totals exactly the random split\'s', np.bincount(sets).tolist(), S.split_counts(500, [0.6, 0.2, 0.2]).tolist())
grp = rs.integers(0, 60, 500)
sets = S.make_sets(500, [0.6, 0.2, 0.2], 3, groups=grp)
check('... grouped: every group in one set', all(len(set(sets[grp == q].tolist())) == 1 for q in np.unique(grp)), True)
check('... the counts within the largest group of the targets', bool(np.all(np.abs(np.bincount(sets, minlength=3) - [300, 100, 100]) <= np.bincount(grp).max())), True)
tm = rs.integers(0, 90, 400).astype(float)
tm[[3, 50]] = np.nan
sets = S.make_sets(400, [0.6, 0.2, 0.2], 3, time=tm)
okt = np.isfinite(tm)
check('... cutpoint: the sets never go back in time, rows at one time together, no set without a time', (bool(np.all(np.diff(sets[okt][np.argsort(tm[okt], kind='stable')]) >= 0)), all(len(set(sets[tm == q].tolist())) == 1 for q in np.unique(tm[okt])), sets[[3, 50]].tolist()), (True, True, [-1, -1]))

vc = call('screening.validation_column', table=T, training=0.6, validation=0.25, test=0.15, strata=['g'], seed=42)
check('validation_column: Training/Validation/Test for every row, the counts the unstratified split\'s', (len(vc['values']), vc['counts'], set(vc['values'])), (n, S.split_counts(n, [0.6, 0.25, 0.15]).tolist(), {'Training', 'Validation', 'Test'}))
check('... the notes say how and with which seed', all(t_ in vc['notes'] for t_ in ('stratified by g', 'seed 42', f'{vc["counts"][0]} training')), True)
vn = call('screening.validation_column', table=T, training=0.5, validation=0.5, test=0, values='numeric', seed=None)
check('... numeric 0/1/2, a seed drawn when none is given', (set(vn['values']), isinstance(vn['seed'], int)), ({0, 1}, True))
Tv = table({**cols, 'Validation': vc['values'], 'Vnum': [float(v) for v in vn['values']]}, types={**TYPES, 'Validation': 'nominal', 'Vnum': 'nominal'}, levels={**LEVELS, 'Validation': ['Training', 'Validation', 'Test']})
Pa = pv.prepare(Tv, 'y', ['x1'], validation='Validation')
Pb2 = pv.prepare(Tv, 'y', ['x1'], validation='Vnum')
check('predictive.prepare takes the made column, text or numeric: its sets are the column\'s', (Pa.sets.tolist() == [['Training', 'Validation', 'Test'].index(v) for v in vc['values']], Pb2.sets.tolist() == vn['values']), (True, True))
for kw, label in (({'strata': ['g', 'cls']}, 'stratified by two columns'), ({'groups': ['nom3']}, 'grouped'), ({'time': 'x1'}, 'cutpoint'), ({}, 'random'),
                  ({'kfold': 6, 'strata': ['cls']}, 'K Fold, stratified'), ({'strata': ['cls'], 'groups': ['nom3']}, 'Stratify by Group'), ({'strata': ['cls'], 'balance': True}, 'the training set balanced'),
                  ({'kfold': 4, 'strata': ['g'], 'groups': ['nom3']}, 'K Fold, stratified by group')):
    vv = call('screening.validation_column', table=T, training=0.6, validation=0.2, test=0.2, seed=7, **kw)
    with tempfile.TemporaryDirectory() as tmp:
        pd.DataFrame(cols).to_csv(os.path.join(tmp, 'data.csv'), index=False)
        code = vv['code'] + '\nprint(json.dumps([None if v is None or v != v else v for v in df["Validation"].tolist()]))'
        o_ = subprocess.run([sys.executable, '-c', 'import json\n' + code], cwd=tmp, capture_output=True, text=True, timeout=300)
    got = json.loads(o_.stdout.strip().splitlines()[-1]) if o_.returncode == 0 else o_.stderr[-800:]
    check(f'the code of the column\'s notes makes the same column from a CSV export: {label}', got == vv['values'], True)
# ---- K Fold, Stratify by Group, Balance the Training Set ----------------------------------------------------------------
kf = S.make_sets(1003, [1.0] * 5, 11)
check('make_sets, K Fold: five folds, 0 to 4, of equal size (the rows left over one each to the first folds)', np.bincount(kf).tolist(), [201, 201, 201, 200, 200])
kfs = S.make_sets(500, [1.0] * 6, 3, strata=strata)
per = np.array([[np.sum((strata == j) & (kfs == k)) for k in range(6)] for j in range(7)])
E6 = np.bincount(strata)[:, None] / 6.0
check('... stratified K Fold: every stratum\'s count in each fold its share rounded down or up, the fold totals the random split\'s', (bool(np.all((per >= np.floor(E6 - 1e-9)) & (per <= np.ceil(E6 + 1e-9)))), np.bincount(kfs).tolist()),
      (True, S.split_counts(500, [1.0] * 6).tolist()))
kfg = S.make_sets(500, [1.0] * 5, 3, groups=grp)
check('... grouped K Fold: every group in one fold', all(len(set(kfg[grp == q].tolist())) == 1 for q in np.unique(grp)), True)
lab2 = rs.choice(3, 500, p=[0.6, 0.3, 0.1])
grp2 = rs.integers(0, 80, 500)
sg = S.make_sets(500, [0.6, 0.2, 0.2], 9, strata=lab2, groups=grp2)
check('Stratify by Group: every group in one set', all(len(set(sg[grp2 == q].tolist())) == 1 for q in np.unique(grp2)), True)
dev = lambda z: float(np.abs(np.array([[np.sum((lab2 == j) & (z == k)) for k in range(3)] for j in range(3)]) - np.bincount(lab2)[:, None] * np.array([0.6, 0.2, 0.2])).sum())
gr_only = S.make_sets(500, [0.6, 0.2, 0.2], 9, groups=grp2)
check('... each stratum\'s count in each set nearer its share than a grouped split\'s, and within the largest group of it', (dev(sg) < dev(gr_only), bool(np.all(np.abs(np.array([[np.sum((lab2 == j) & (sg == k)) for k in range(3)] for j in range(3)]) - np.bincount(lab2)[:, None] * np.array([0.6, 0.2, 0.2])) <= np.bincount(grp2).max()))), (True, True))
sgk = S.make_sets(500, [1.0] * 4, 2, strata=lab2, groups=grp2)
check('... and as K folds: groups whole, four folds, each near a quarter of every stratum', (all(len(set(sgk[grp2 == q].tolist())) == 1 for q in np.unique(grp2)), sorted(set(sgk.tolist())),
      bool(np.all(np.abs(np.array([[np.sum((lab2 == j) & (sgk == k)) for k in range(4)] for j in range(3)]) - np.bincount(lab2)[:, None] / 4) <= np.bincount(grp2).max()))), (True, [0, 1, 2, 3], True))
bal = S.make_sets(500, [0.6, 0.2, 0.2], 4, strata=lab2, balance=True)
unb = S.make_sets(500, [0.6, 0.2, 0.2], 4, strata=lab2)
trc = [int(np.sum((lab2 == j) & (bal == 0))) for j in range(3)]
check('Balance the Training Set: every stratum the same count of training rows, that of the smallest', (len(set(trc)), trc[0]), (1, min(int(np.sum((lab2 == j) & (unb == 0))) for j in range(3))))
check('... validation and test as the stratified split\'s, the rows cut from training with no set', (bool(np.array_equal(bal[unb != 0], unb[unb != 0])), bool(np.all(bal[(unb == 0) & (bal != 0)] == -1)), int(np.sum(bal == -1))),
      (True, True, int(np.sum(unb == 0)) - 3 * trc[0]))
vk = call('screening.validation_column', table=T, kfold=5, strata=['g'], seed=21)
check('validation_column, K Fold: the folds 1 to 5, stratified, the counts equal', (sorted(set(vk['values'])), vk['counts'], vk['kfold']), ([1, 2, 3, 4, 5], S.split_counts(n, [1.0] * 5).tolist(), 5))
Tk = table({**cols, 'Fold': [float(v) for v in vk['values']]}, types={**TYPES, 'Fold': 'nominal'}, levels=LEVELS)
Pk5 = pv.prepare(Tk, 'y', ['x1', 'x2'], validation='Fold')
check('predictive.prepare reads the K Fold column as folds: every row trains, P.folds the fold of each row', (Pk5.k, Pk5.fold_values, set(Pk5.sets.tolist()), (Pk5.folds + 1).tolist() == [int(v) for v in np.asarray(vk['values'])[Pk5.index]]), (5, [1.0, 2.0, 3.0, 4.0, 5.0], {0}, True))
fm = pv.fold_masks(Pk5)
check('... fold_masks: each fold held out once, fitted on the others', (len(fm), all(bool(np.array_equal(f_, ~h_)) for f_, h_ in fm), bool(np.array_equal(np.sum([h_ for _, h_ in fm], axis=0), np.ones(len(Pk5.index))))), (5, True, True))
from sklearn.linear_model import LinearRegression as _LR  # noqa: E402
cvr = pv.crossvalidate(Pk5, lambda fit_rows: _LR().fit(Pk5.X[fit_rows], Pk5.target[fit_rows]).predict(Pk5.X))
oof_ = np.zeros(len(Pk5.index))
for j in range(5):
    lr_ = _LR().fit(Pk5.X[Pk5.folds != j], Pk5.target[Pk5.folds != j])
    oof_[Pk5.folds == j] = lr_.predict(Pk5.X[Pk5.folds == j])
check.near('... crossvalidate: each row predicted by the least squares fit without its fold', mx(cvr['oof'], oof_), 0.0, abs_=1e-12)
check.near('... its pooled RSquare is sklearn\'s r2_score of those predictions', cvr['measures']['rsquare'], metrics.r2_score(Pk5.target, oof_), rel=1e-12)
check.near('... and each fold\'s RASE is the held-out fold\'s', cvr['folds'][2]['rase'], float(np.sqrt(np.mean((Pk5.target[Pk5.folds == 2] - oof_[Pk5.folds == 2]) ** 2))), rel=1e-12)
Tt = table({**cols, 'FoldT': [f'fold {v}' for v in vk['values']]}, types={**TYPES, 'FoldT': 'nominal'}, levels=LEVELS)
check('... a character column of more than three values is read as folds too', pv.prepare(Tt, 'y', ['x1'], validation='FoldT').k, 5)
rk, _ = quiet(call, 'screening.fit', table=Tk, y='y', x=X4, validation='Fold', seed=SEED, methods=['linear', 'knn'])
lin_cv = next(m for m in rk['methods'] if m['key'] == 'linear')
want_r2 = np.mean([metrics.r2_score(Pk5.target[Pk5.folds == j], _LR().fit(pv.prepare(Tk, 'y', X4, validation='Fold').X[Pk5.folds != j], Pk5.target[Pk5.folds != j]).predict(pv.prepare(Tk, 'y', X4, validation='Fold').X[Pk5.folds == j])) for j in range(5)])
check('Fit Many Models crossvalidates by the column\'s folds: 5 folds, the fold column named, Crossvalidation the set compared', (rk['kfold'], rk['fold_column'], rk['compare'], len(lin_cv['cv']['folds'])), (5, 'Fold', 'Crossvalidation', 5))
check.near('... Fit Least Squares\' crossvalidated RSquare is the mean of its folds\' by sklearn', lin_cv['measures']['Crossvalidation']['rsquare'], float(want_r2), rel=1e-9)
for kw, what in (({'strata': ['g'], 'time': 'x1'}, 'a cutpoint column with stratification'), ({'training': 0}, 'no training share'), ({'time': 'g'}, 'a character cutpoint column'),
                 ({'kfold': 3}, 'K Fold of three folds (read as sets)'), ({'kfold': 5, 'time': 'x1'}, 'K Fold by a cutpoint'), ({'balance': True}, 'Balance without stratification columns'),
                 ({'balance': True, 'strata': ['g'], 'groups': ['nom3']}, 'Balance with grouping columns')):
    try:
        call('screening.validation_column', table=T, seed=1, **{'training': 0.6, 'validation': 0.2, 'test': 0.2, **kw})
        check(f'validation_column refuses {what}', 'no error', 'error')
    except ValueError:
        check(f'validation_column refuses {what}', True, True)


# ============================================================================
# the Python under the report, on a CSV export of the table
# ============================================================================
def run_code(code, data=cols):
    with tempfile.TemporaryDirectory() as tmp:
        pd.DataFrame(data).to_csv(os.path.join(tmp, 'data.csv'), index=False)
        with open(os.path.join(tmp, 'code.py'), 'w') as fh:
            fh.write(code)
        o_ = subprocess.run([sys.executable, 'code.py'], cwd=tmp, capture_output=True, text=True, timeout=900)
    if o_.returncode:
        print(o_.stderr[-2000:])
        return None
    return [json.loads(ln) for ln in o_.stdout.splitlines() if ln.startswith('{')]


for label, kw, data in (
        ('continuous, Informative Missing, a weight, a Validation column with test rows', dict(table=T, y='y', x=['x1m', 'x2', 'x3', 'gm'], validation='v', weight='w'), cols),
        ('ordinal, a holdback, a frequency', dict(table=T, y='three', x=X4, portion=0.3, freq='f'), cols),
        ('two levels, 3-fold crossvalidation repeated twice', dict(table=Ts, y='cls', x=X4, kfold=3, repeats=2), small),
        ('continuous, a K Fold Validation column', dict(table=Tk, y='y', x=X4, validation='Fold'), {**cols, 'Fold': [float(v) for v in vk['values']]})):
    rr, _ = quiet(call, 'screening.fit', seed=SEED, methods=ALL, table_name='data', **kw)
    got = run_code(rr['code'], data)
    if got is None:
        check(f'the code runs: {label}', False, True)
        continue
    want = {(m['label'], s_): v for m in rr['methods'] for s_, v in m.get('measures', {}).items()}
    worst, folds = 0.0, {}
    for d in got:
        if 'fold' in d:
            folds.setdefault(d['method'], []).append(d)
            continue
        wv = want[(d['method'], d['set'])]
        worst = max([worst] + [abs(v - wv[k]) for k, v in d.items() if k not in ('method', 'set') and v is not None])
    for mth, fl in folds.items():
        wv = want[(mth, 'Crossvalidation')]
        worst = max([worst] + [abs(np.mean([f_[k] for f_ in fl]) - wv[k]) for k in wv if wv[k] is not None and k != 'n'])
    check(f'the code gives the report\'s numbers exactly, every method: {label}', (worst, len({d['method'] for d in got}) == len(rr['methods']), bool(folds) == bool(kw.get('kfold') or kw.get('validation') == 'Fold')), (0.0, True, True))

# the Ensemble of Selected's code: the report's stacking weights, and the measures of its average and stacking
for label, kw, data in (('continuous, a Validation column, a weight', dict(table=T, y='y', x=X4, validation='v', weight='w', methods=['linear', 'tree', 'knn']), cols),
                        ('two levels, 3-fold crossvalidation', dict(table=Ts, y='cls', x=X4, kfold=3, methods=['linear', 'knn', 'nb']), small)):
    en2, _ = quiet(call, 'screening.ensemble', seed=SEED, table_name='data', **kw)
    got_e = run_code(en2['code'], data)
    if got_e is None:
        check(f'Ensemble of Selected, {label}: its code runs', False, True)
        continue
    wline = next((d_ for d_ in got_e if 'set' not in d_), {})
    worst_e = max([abs(d_[k_] - next(q for q in en2['rows'] if q['method'] == d_['method'])['measures'][d_['set']][k_]) for d_ in got_e if 'set' in d_ for k_ in d_ if k_ not in ('method', 'set') and d_[k_] is not None] + [0.0])
    check(f'Ensemble of Selected, {label}: its code gives the report\'s stacking weights and the measures of the average and the stacking', (worst_e < 1e-9, all(abs(wline.get(q['method'], -1) - q['weight']) < 1e-9 for q in en2['weights'])), (True, True))


# ============================================================================
# the graphs' matplotlib code, run on a CSV export: every comparison's graph
# ============================================================================
from test_charts import find_line  # noqa: E402
from test_predictive import SEP, run_graph, scatter_pts, subset_in_order  # noqa: E402

GTMP = tempfile.mkdtemp(prefix='smui-screening-charts-')
graphs = 0


def gcheck(label, code, tid):
    """The figure of a graph's code (None when it fails, which is checked)."""
    global graphs
    F, err = run_graph(code, tid, GTMP)
    check(f'{label}: the code runs, ending in plt.show()', (err, code.rstrip().split('\n')[-1]), (None, 'plt.show()'))
    if F:
        graphs += 1
        return F, F['axes'][0]
    return None, None


for label, tid, kw, th_kw in (
        ('two levels, a Validation column, a frequency', T, dict(y='cls', x=X4, validation='v', freq='f', methods=['tree', 'forest', 'knn', 'linear']), dict(cut=0.4, level=1)),
        ('three levels, a holdback, rows of the report, other levels picked', T, dict(y='three', x=X4, portion=0.3, methods=['tree', 'knn', 'linear', 'nb'], rows=list(range(0, 330)), plot={'roc': 2, 'lift': 0}), None),
        ('two levels, 3-fold crossvalidation repeated twice', Ts, dict(y='cls', x=X4, kfold=3, repeats=2, methods=['tree', 'knn', 'linear', 'nb']), dict(cut=0.6, level=0)),
        ('continuous, a Validation column, the test rows shown', T, dict(y='y', x=X4, validation='v', methods=['tree', 'knn', 'linear', 'lasso'], plot={'abp': 'Test'}), None),
        ('continuous, 3-fold crossvalidation, the out-of-fold predictions shown', Ts, dict(y='y', x=X4, kfold=3, methods=['tree', 'linear'], plot={'abp': 'Crossvalidation'}), None)):
    lab = f'graphs: {label}'
    rr, _ = quiet(call, 'screening.fit', table=tid, seed=SEED, table_name='data', **kw)
    pl = rr['plots']
    head = pl['head_code']
    lab_of = {m['key']: m['label'] for m in rr['methods']}
    if 'rows' in kw:
        check(f'{lab}: the head leaves out the rows the report leaves out', f'df = df.drop(index={sorted(set(range(n)) - set(kw["rows"]))})   # the rows the report leaves out' in head, True)
    if rr['kind'] == 'categorical':
        nl = len(rr['levels'])
        for kind in ('roc', 'lift'):
            v = (kw.get('plot') or {}).get(kind)
            lv = v if v is not None else (1 if nl == 2 else 0)
            level = rr['levels'][lv]
            check(f'{lab}: {kind}: a graph per set shown', list(pl[kind]), rr['shown_sets'])
            for i, st in enumerate(rr['shown_sets']):
                F, ax = gcheck(f'{lab}: {kind} {st} {level}', head + SEP + pl[kind][st], tid)
                if not F:
                    continue
                last = i == len(rr['shown_sets']) - 1
                ok, names = [], []
                for key in rr['order']:
                    c_ = next((c for c in rr[kind][key] if c['set'] == st and c['level'] == level), None)
                    if c_ is None:
                        continue
                    name = f'{lab_of[key]} ({c_["auc"]:.3f})' if kind == 'roc' else lab_of[key]
                    names.append(name)
                    ln = next((q for q in ax['lines'] if q['label'] == name), None)
                    pts = list(zip(c_['fpr'], c_['tpr'])) if kind == 'roc' else list(zip(c_['portion'], c_['lift']))
                    ok.append(bool(ln) and subset_in_order(pts, list(zip(ln['x'], ln['y']))) and ln['color'][:7] == S.COLORS[key])
                check(f'{lab}: {kind} {st} {level}: every method\'s curve (the report\'s points on it), named and coloured as the page\'s', (len(ok) > 0, ok), (True, [True] * len(ok)))
                check(f'{lab}: {kind} {st} {level}: the legend on the last graph, the reference, the titles, the size',
                      (F['legend'], find_line(ax, [0, 1], [0, 1] if kind == 'roc' else [1, 1]) is not None, ax['xlabel'], ax['title'], F['size']),
                      (names if last else [], True, '1 - Specificity' if kind == 'roc' else 'Portion', f'{"ROC" if kind == "roc" else "Lift"} {st} {level}', [5.6 if last else 3.6, 3.3]))
        if th_kw:
            # the Decision Threshold's code is written in the page (smui-predict.js; test-ui-screening.py runs it): its head here fits every
            # method as the report does, fitted[label] (and oof[label] with K Fold) the probabilities the page draws
            th, _ = quiet(call, 'screening.threshold', table=tid, seed=SEED, table_name='data', **{k_: v_ for k_, v_ in kw.items() if k_ != 'plot'}, plot={'order': rr['order']})
            from test_predictive import run_names  # noqa: E402
            got, err = run_names(th['plots']['head_code'], tid, GTMP, ['fitted', 'oof', 'y', 'sets', 'w'])
            check(f'{lab}: Decision Threshold: its head runs', err, None)
            if got:
                okp = [mx(got['fitted'][m['label']][:, 1], m['p']) <= 1e-12 and (('p_cv' not in m) or mx(got['oof'][m['label']][:, 1], m['p_cv']) <= 1e-12) for m in th['models']]
                check(f'{lab}: Decision Threshold: every method\'s probabilities (and out-of-fold ones) from the head are the report\'s', okp, [True] * len(th['models']))
                check(f'{lab}: Decision Threshold: the head\'s y and sets are the report\'s rows\'', (np.asarray(got['y']).tolist() == th['points']['actual'], np.asarray(got['sets']).tolist() == th['points']['set']), (True, True))
                check(f'{lab}: Decision Threshold: the code\'s names of the probabilities', [m['code'] for m in th['models']], [[f'fitted[{json.dumps(m["label"])}]', f'oof[{json.dumps(m["label"])}]'] for m in th['models']])
    else:
        st = (kw.get('plot') or {}).get('abp') or rr['compare']
        res = rr['residuals']
        k_ = S.SETS.index(st) if st in S.SETS else None
        idx = [i for i, sv_ in enumerate(res['set']) if k_ is None or sv_ == k_]
        check(f'{lab}: a graph per method, in the Summary\'s order', list(pl['abp']), [k for k in rr['order'] if k in (res['oof'] if st == S.CV else res['predicted'])])
        for key, tail in pl['abp'].items():
            F, ax = gcheck(f'{lab}: actual by predicted {lab_of[key]} {st}', head + SEP + tail, tid)
            if not F:
                continue
            pred = res['oof'][key] if st == S.CV else res['predicted'][key]
            want = [(pred[i], res['actual'][i]) for i in idx]
            vv = [q for pq in want for q in pq]
            check.near(f'{lab}: actual by predicted {lab_of[key]} {st}: every row at its prediction and value', mx(scatter_pts(ax), want), 0.0, abs_=1e-9)
            check(f'{lab}: actual by predicted {lab_of[key]} {st}: the line of equality, the titles, the size', (find_line(ax, [min(vv), max(vv)], [min(vv), max(vv)], rel=1e-9) is not None, ax['xlabel'], ax['ylabel'], ax['title'], F['size']),
                  (True, 'Predicted', 'Actual', f'Actual by predicted {lab_of[key]} {st}', [2.5, 2.35]))
check('graphs: every graph\'s code ran and drew the report\'s graph', graphs, 20)

sys.exit(check.done())
