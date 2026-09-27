#!/usr/bin/env python3
"""Analyze > Predictive Modeling > Bootstrap Forest and Boosted Tree's
backend (resources/py/smui/ensemble.py), through registry.dispatch as the
page calls it, checked against scikit-learn called directly with the same
settings (RandomForestRegressor/Classifier and GradientBoostingRegressor/
Classifier: the same trees, predictions and staged predictions), against
brute force (every cut-back tree's out-of-bag loss, JMP's node
probabilities node by node, the forest as the mean of its trees, the
permutation importance), against JMP's documented formulas and examples
(Prob = (n + prior)/(N + 1) with the prior 0.9 of the parent's prior and
0.1 of its Prob; Multiple Fits' numbers of terms 4, 5, 6, 8, 10; the
default number of terms 13 -> 10; G² and SS of the splits), the measures
against scikit-learn's metrics, and by running the Python shown under the
report on a CSV export of the table.

    python3 resources/tests/smui/test_ensemble.py
"""
import contextlib
import io
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
check('ensemble.py imports', 'ensemble' in FAILED, False)
from smui import ensemble as E, predictive as pv, registry  # noqa: E402

try:
    import sklearn
    from sklearn import metrics
    from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
except ImportError:
    print('scikit-learn 1.8 is needed for these tests (Pyodide 314.0.7 has 1.8.0)')
    sys.exit(1)
check('scikit-learn 1.8 (as in Pyodide 314.0.7)', sklearn.__version__.startswith('1.8'), True)


def mx(a, b):
    return float(np.max(np.abs(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)))) if np.size(a) else 0.0


def quiet(fn, *a, **k):
    """Run fn with its 'smui:progress' lines captured; return (result, lines)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn(*a, **k)
    return out, [ln for ln in buf.getvalue().splitlines() if ln.startswith('smui:progress')]


# ---- the data ---------------------------------------------------------------------------------------
rng = np.random.default_rng(20260927)
n = 900
x1 = rng.normal(0, 1, n)
x2 = rng.uniform(0, 1, n)
g = rng.choice(['a', 'b', 'c'], n, p=[0.5, 0.3, 0.2])
x3 = rng.normal(0, 1, n)
x4 = rng.normal(0, 1, n)
y = 2 * np.sin(2 * x1) + 3 * (x2 > 0.5) + np.where(g == 'b', 1.0, 0.0) + x3 * x4 + rng.normal(0, 0.6, n)
cls = np.where(y + rng.normal(0, 1.2, n) > np.median(y), 'high', 'low')
three = np.where(y < np.quantile(y, 0.3), 'lo', np.where(y < np.quantile(y, 0.72), 'mid', 'hi'))
vt = rng.choice(['Training', 'Validation', 'Test'], n, p=[0.6, 0.25, 0.15])
vnum = np.array([{'Training': 0.0, 'Validation': 1.0, 'Test': 2.0}[v] for v in vt])
w = rng.uniform(0.5, 2.0, n).round(3)
fq = rng.integers(1, 4, n).astype(float)
x1m = x1.copy()
x1m[rng.choice(n, 40, replace=False)] = np.nan
gm = g.astype(object).copy()
gm[rng.choice(n, 25, replace=False)] = None
cols = {'y': list(y), 'x1': list(x1), 'x2': list(x2), 'g': list(g), 'x3': list(x3), 'x4': list(x4), 'cls': list(cls), 'three': list(three),
        'v': list(vt), 'vn': list(vnum), 'w': list(w), 'f': list(fq), 'x1m': [None if np.isnan(v) else v for v in x1m], 'gm': list(gm)}
TYPES = {'g': 'nominal', 'cls': 'nominal', 'three': 'nominal', 'v': 'nominal', 'gm': 'nominal'}
LEVELS = {'three': ['lo', 'mid', 'hi'], 'cls': ['high', 'low'], 'g': ['a', 'b', 'c'], 'gm': ['a', 'b', 'c']}
T = table(cols, types=TYPES, levels=LEVELS)
XS = ['x1', 'x2', 'g', 'x3', 'x4']
SEED = 4242

# ---- the registry --------------------------------------------------------------------------------------
names = registry.names()
for fn in ('ensemble.fit', 'ensemble.save', 'ensemble.profile', 'ensemble.maximize', 'ensemble.importance', 'ensemble.tree', 'ensemble.permutation'):
    check(f'{fn} is registered and needs scikit-learn', (fn in names, json.loads(registry.packages_for(fn))), (True, ['scikit-learn']))
check('scikit-learn is not imported at module level (the page starts without it)', 'import sklearn' not in open(E.__file__).read().split('def parents')[0], True)

# ---- settings: JMP's names and defaults --------------------------------------------------------------------
sf = E.settings_of('forest', {}, 13)
check('Bootstrap Forest defaults: 100 trees, rate 1, splits 10 to 2000, minimum size 5, Early Stopping on',
      (sf['trees'], sf['rate'], sf['minSplits'], sf['maxSplits'], sf['minSize'], sf['early'], sf['multi']), (100, 1.0, 10, 2000, 5, True, False))
check('Number of Terms Sampled per Split: 13 terms -> 10 (JMP 17\'s documented example)', sf['terms'], 10)
check('the default is p - floor(p/4) (6 -> 5, the JMP Community\'s new default; floor(p/4) was the old one)', [E.default_terms(p) for p in (1, 2, 3, 4, 6, 7, 13, 40)], [1, 2, 3, 3, 5, 6, 10, 30])
check('Max Number of Terms defaults to every term', sf['maxTerms'], 13)
sb = E.settings_of('boosted', {}, 5)
check('Boosted Tree defaults: 50 layers, 3 splits, learning rate 0.1, minimum size 5, sampling rates 1, Early Stopping on',
      (sb['layers'], sb['splits'], sb['learn'], sb['minSize'], sb['rowRate'], sb['colRate'], sb['early']), (50, 3, 0.1, 5, 1.0, 1.0, True))
check('the Multiple Fits bounds start at Splits per Tree and the Learning Rate (JMP 17\'s window shows 3 and 0.1)', (sb['maxSplits'], sb['maxLearn']), (3, 0.1))
check('Multiple Fits over Number of Terms, 4 to 10: 4, 5, 6, 8, 10 (JMP\'s documented example)', E.terms_sequence(4, 10), [4, 5, 6, 8, 10])
check('... 1 to 5: 1, 2, 3, 4, 5 (JMP 10\'s Titanic example)', E.terms_sequence(1, 5), [1, 2, 3, 4, 5])
check('Multiple Fits over Splits and Learning Rate: splits in steps of 1, rates in steps of 0.1',
      E.grid_of(E.settings_of('boosted', {'splits': 2, 'maxSplits': 3, 'learn': 0.1, 'maxLearn': 0.3}, 5)),
      [(2, 0.1), (2, 0.2), (2, 0.3), (3, 0.1), (3, 0.2), (3, 0.3)])
for bad, msg in ((('forest', {'trees': 0}), 'at least 1'), (('forest', {'rate': 1.5}), 'at most 1'), (('boosted', {'learn': 0}), 'at least'),
                 (('forest', {'minSplits': 50, 'maxSplits': 20}), 'more than Maximum'), (('boosted', {'splits': 2.5}), 'whole number')):
    try:
        E.settings_of(bad[0], bad[1], 5)
        check(f'a bad setting is refused: {bad[1]}', 'no error', 'error')
    except ValueError as e:
        check(f'a bad setting is refused: {bad[1]}', msg in str(e), True)
check('the terms tried at a split: the terms\' share of X\'s columns', (E.features_for(3, 5, 5), E.features_for(3, 5, 7), E.features_for(1, 5, 7)), (3, 4, 1))

# ---- JMP's node probabilities, node by node --------------------------------------------------------------
P3 = pv.prepare(T, 'three', XS, validation='v')
tr = P3.train()
dt = RandomForestClassifier(n_estimators=1, max_leaf_nodes=30, min_samples_leaf=5, criterion='entropy', random_state=3).fit(P3.X[tr], P3.target[tr]).estimators_[0]
pr = E.jmp_probs(dt, 0.9)
t = dt.tree_
Nn = t.weighted_n_node_samples
cnt = t.value[:, 0, :] * Nn[:, None]
par = E.parents(dt)
prior = np.zeros_like(cnt)
prob = np.zeros_like(cnt)
for node in range(t.node_count):          # a parent's id is smaller than its children's
    if node == 0:
        prior[0] = cnt[0] / Nn[0]
    else:
        prior[node] = 0.9 * prior[par[node]] + 0.1 * prob[par[node]]
    prob[node] = (cnt[node] + prior[node]) / (cnt[node] + prior[node]).sum()
check.near('JMP\'s Prob = (n + prior)/Σ(n + prior), prior = 0.9 prior(parent) + 0.1 Prob(parent): node by node', mx(pr, prob), 0.0, abs_=1e-12)
check('a node\'s probabilities sum to 1', bool(np.allclose(pr.sum(1), 1)), True)
leaf = t.children_left < 0
pure = leaf & (cnt.max(1) == cnt.sum(1))
check('a pure leaf still gives every level a probability above 0 (JMP: "always nonzero")', bool(pure.any() and (pr[pure] > 0).all()), True)
check.near('the root\'s Prob is its share of each level', mx(pr[0], cnt[0] / Nn[0]), 0.0, abs_=1e-15)
# a stump by hand: 30 rows at a node with counts (20, 10), its parent with prior (0.5, 0.5) and Prob (0.6, 0.4)
pri = 0.9 * np.array([0.5, 0.5]) + 0.1 * np.array([0.6, 0.4])
check.near('the formula by hand: counts (20, 10), parent prior (0.5, 0.5) and Prob (0.6, 0.4) -> Prob[1] = (20 + 0.51)/31', float((20 + pri[0]) / 31), 20.51 / 31, 1e-12)

# ---- the out-of-bag loss of every cut-back tree, by brute force --------------------------------------------
Pc = pv.prepare(T, 'y', XS, validation='v')
trc = Pc.train()
rfc = RandomForestRegressor(n_estimators=3, max_features=4, max_leaf_nodes=2001, min_samples_leaf=5, random_state=9).fit(Pc.X[trc], Pc.target[trc])
worst = 0.0
for tree, drawn in zip(rfc.estimators_, rfc.estimators_samples_):
    oob = np.bincount(drawn, minlength=int(trc.sum())) == 0
    Xo, yo = Pc.X[trc][oob], Pc.target[trc][oob]
    est = tree.tree_.value[:, 0, 0]
    loss = E.oob_losses(tree, Xo, yo, np.ones(len(yo)), est, False)
    parent = E.parents(tree)
    for k in range(0, len(loss), max(1, len(loss) // 12)):
        rep = E.stands_for(parent, k)
        direct = float(np.sum((yo - est[rep[tree.apply(Xo)]]) ** 2))
        worst = max(worst, abs(direct - loss[k]) / max(1.0, direct))
check.near('the out-of-bag SSE after k splits = the cut-back tree applied to the out-of-bag rows (every 12th k of 3 trees)', worst, 0.0, abs_=1e-9)
check('the splits in the order scikit-learn made them: the k-th made nodes 2k - 1 and 2k',
      all(tree.tree_.children_left[E.parents(tree)[2 * k - 1]] == 2 * k - 1 for tree in rfc.estimators_ for k in range(1, int((tree.tree_.children_left >= 0).sum()) + 1)), True)
tree = rfc.estimators_[0]
k0 = 7
small = RandomForestRegressor(n_estimators=1, max_features=4, max_leaf_nodes=k0 + 1, min_samples_leaf=5, random_state=9).fit(Pc.X[trc], Pc.target[trc]).estimators_[0]
check('a tree cut back to k splits is the tree scikit-learn grows with k + 1 leaves (the same seed)',
      mx(small.predict(Pc.X), tree.tree_.value[:, 0, 0][E.stands_for(E.parents(tree), k0)[tree.apply(Pc.X)]]), 0.0)
check('kept_splits: at least the minimum, then while the loss falls', [E.kept_splits(np.array(a), 2) for a in ([9, 8, 7, 6, 5.5, 5.6, 5], [9, 8, 7, 7, 6], [9, 8], [9, 8, 7, 6, 5])],
      [4, 2, 1, 4])

# ---- a forest, against scikit-learn and brute force -----------------------------------------------------------
r, lines = quiet(call, 'ensemble.fit', table=T, y='y', x=XS, kind='forest', validation='v', seed=SEED, table_name='data')
check('a forest: no error', 'error' not in r, True)
cum = r['cumulative']
st = E.settings_of('forest', {}, 5)
K, patience = st['trees'], max(5, math.ceil(st['trees'] / 10))
check('progress lines: "smui:progress forest <done> <total>" up to the total', (bool(lines), lines[-1].split()[1:] if lines else None), (True, ['forest', str(K), str(K)]))
rf = RandomForestRegressor(n_estimators=cum['grown'], criterion='squared_error', max_features=E.features_for(st['terms'], 5, Pc.X.shape[1]), max_leaf_nodes=2001,
                           min_samples_leaf=5, bootstrap=True, random_state=SEED, n_jobs=1).fit(Pc.X[trc], Pc.target[trc])
each, kept_s, rows_ = [], [], []
w1 = np.ones(int(trc.sum()))
for tree, drawn in zip(rf.estimators_, rf.estimators_samples_):
    inbag = np.bincount(drawn, minlength=int(trc.sum()))
    oob = inbag == 0
    est = tree.tree_.value[:, 0, 0]
    loss = E.oob_losses(tree, Pc.X[trc][oob], Pc.target[trc][oob], w1[oob], est, False)
    k = E.kept_splits(loss, 10)
    kept_s.append(k)
    p_ = est[E.stands_for(E.parents(tree), k)[tree.apply(Pc.X)]]
    each.append(p_)
    ytr, ptr = Pc.target[trc], p_[trc]
    ib_sse = float(np.sum(inbag * (ytr - ptr) ** 2))
    rows_.append({'splits': k, 'oob_n': float(oob.sum()), 'oob_sse': float(np.sum((ytr[oob] - ptr[oob]) ** 2)), 'ib_sse': ib_sse, 'ib_sse_n': ib_sse / inbag.sum(),
                  'oob_loss': float(loss[k + 1] if k < len(loss) - 1 else loss[k])})
cumsum = np.cumsum(each, axis=0) / np.arange(1, len(each) + 1)[:, None]
vm = Pc.mask(1)
r2v = [metrics.r2_score(Pc.target[vm], c[vm]) for c in cumsum]
kept = cum['kept']
check('Early Stopping keeps the number of trees with the best validation RSquare (scikit-learn\'s r2_score)', kept, int(np.argmax(r2v)) + 1)
check(f'and stops when the last tenth of the trees ({patience}) did not improve it', (cum['stopped'], cum['grown'] - kept), (True, patience))
check('the validation curve is r2_score of the forest of the first k trees', mx(next(s for s in cum['series'] if s['set'] == 'Validation')['stats']['rsquare'], r2v), 0.0)
fitted = cumsum[kept - 1]
M = {m['set']: m for m in r['fit']['measures']}
for k_, name in enumerate(pv.SETS):
    m = Pc.mask(k_)
    check.near(f'{name} RSquare = r2_score of the mean of the kept trees', M[name]['rsquare'], metrics.r2_score(Pc.target[m], fitted[m]), 1e-10)
    check.near(f'{name} RASE', M[name]['rase'], math.sqrt(metrics.mean_squared_error(Pc.target[m], fitted[m])), 1e-10)
check('the forest is scikit-learn\'s: its trees\' splits kept are the ones computed here', [t_['splits'] for t_ in r['trees']], kept_s[:kept])
check('every tree keeps at least Minimum Splits per Tree (10)', min(t_['splits'] for t_ in r['trees']) >= 10, True)
check('... and is cut back well below scikit-learn\'s full tree', np.mean([t_['splits'] for t_ in r['trees']]) < np.mean([int((t_.tree_.children_left >= 0).sum()) for t_ in rf.estimators_[:kept]]), True)
worst = max(max(abs(a[kk] - b[kk]) / max(1.0, abs(b[kk])) for kk in ('oob_n', 'oob_sse', 'ib_sse', 'ib_sse_n', 'oob_loss')) for a, b in zip(r['trees'], rows_[:kept]))
check.near('Per-Tree Summaries: OOB N, OOB SSE, IB SSE, IB SSE/N and OOB Loss (before the split taken back) as computed here', worst, 0.0, abs_=1e-9)
ranks = [t_['rank'] for t_ in sorted(r['trees'], key=lambda t_: (t_['oob_loss_n'], t_['tree']))]
check('Rank: the tree\'s OOB Loss/N in ascending order', ranks, list(range(1, kept + 1)))
check.near('IB SSE/N counts the bootstrap sample (training rows × the rate)', r['trees'][0]['ib_n'], float(trc.sum()), 1e-12)
ind = {i['what']: i['rase'] for i in r['individual']}
check.near('Individual Trees: In Bag RASE, averaged over the trees', ind['In Bag'], float(np.mean([math.sqrt(rw['ib_sse_n']) for rw in rows_[:kept]])), 1e-10)
check.near('Individual Trees: Out of Bag RASE = the mean of √(OOB SSE/N)', ind['Out of Bag'], float(np.mean([math.sqrt(rw['oob_sse'] / rw['oob_n']) for rw in rows_[:kept]])), 1e-10)
# the forest's out-of-bag prediction
num = np.zeros(int(trc.sum()))
den = np.zeros(int(trc.sum()))
for (tree, drawn), p_ in zip(list(zip(rf.estimators_, rf.estimators_samples_))[:kept], each[:kept]):
    oob = np.bincount(drawn, minlength=int(trc.sum())) == 0
    num[oob] += p_[trc][oob]
    den[oob] += 1
ok = den > 0
oo = M['Out of Bag']
check.near('Out of Bag: the RSquare of each training row by the trees that did not see it', oo['rsquare'], metrics.r2_score(Pc.target[trc][ok], num[ok] / den[ok]), 1e-10)
check('... over the training rows some kept tree did not see', oo['n'], float(ok.sum()))
# column contributions: the SS of the splits kept
ss = {c: 0.0 for c in XS}
nsplit = {c: 0 for c in XS}
fcol = {j: c for c in XS for j in Pc.groups[c]}
for tree, k in zip(rf.estimators_[:kept], kept_s[:kept]):
    tt = tree.tree_
    parent = E.parents(tree)
    for s in range(1, k + 1):
        q = parent[2 * s - 1]
        L_, R_ = tt.children_left[q], tt.children_right[q]
        sse = lambda node: float(tt.impurity[node] * tt.weighted_n_node_samples[node])  # noqa: E731
        ss[fcol[int(tt.feature[q])]] += sse(q) - sse(L_) - sse(R_)
        nsplit[fcol[int(tt.feature[q])]] += 1
cc = {row['column']: row for row in r['contributions']['rows']}
check('Column Contributions: the number of splits on each column over the kept trees', {c: cc[c]['splits'] for c in XS}, nsplit)
check.near('... and the SS they take away (SSparent - SSleft - SSright)', max(abs(cc[c]['value'] - ss[c]) / max(1, ss[c]) for c in XS), 0.0, abs_=1e-9)
check.near('the portions add to 1', sum(row['portion'] for row in r['contributions']['rows']), 1.0, 1e-12)
check('x2 (a step of 3) and x1 (a wave) contribute most, x3 and x4 (an interaction) less', [row['column'] for row in r['contributions']['rows']][:2] in (['x2', 'x1'], ['x1', 'x2']), True)
check('the label is SS for a continuous response', r['contributions']['label'], 'SS')

# the same seed, the same forest; another seed, another
r_again = call('ensemble.fit', table=T, y='y', x=XS, kind='forest', validation='v', seed=SEED)
r_other = call('ensemble.fit', table=T, y='y', x=XS, kind='forest', validation='v', seed=SEED + 1)
check('the same seed gives the same forest', r_again['fit']['measures'], r['fit']['measures'])
check('another seed another', r_other['fit']['measures'] != r['fit']['measures'], True)

# no validation: every tree kept; Early Stopping off: every tree too
rn = call('ensemble.fit', table=T, y='y', x=XS, kind='forest', seed=SEED)
check('no validation rows: all 100 trees, no early stopping', (rn['cumulative']['kept'], rn['cumulative']['grown'], rn['cumulative']['stopped']), (100, 100, False))
check('... and the Specifications say Early Stopping is off', [v for k_, v, *_ in rn['spec']['left'] if k_ == 'Early Stopping'], ['Off (no validation rows)'])
check('... and Overall Statistics has Training and Out of Bag', [m['set'] for m in rn['fit']['measures']], ['Training', 'Out of Bag'])
ro = call('ensemble.fit', table=T, y='y', x=XS, kind='forest', validation='v', seed=SEED, settings={'early': False, 'trees': 30})
check('Early Stopping off: every tree asked for', (ro['cumulative']['kept'], ro['cumulative']['grown']), (30, 30))
rg = call('ensemble.fit', table=T, y='y', x=XS, kind='forest', validation='v', seed=SEED, settings={'early': False, 'trees': 30, 'stop': 'none'})
full_splits = [int((t_.tree_.children_left >= 0).sum()) for t_ in RandomForestRegressor(n_estimators=30, max_features=E.features_for(4, 5, 7), max_leaf_nodes=2001, min_samples_leaf=5, random_state=SEED).fit(Pc.X[trc], Pc.target[trc]).estimators_]
check('Tree Size ▸ Grow to Maximum: scikit-learn\'s trees as they are', [t_['splits'] for t_ in rg['trees']], full_splits)
rfb = RandomForestRegressor(n_estimators=30, max_features=E.features_for(4, 5, 7), max_leaf_nodes=2001, min_samples_leaf=5, random_state=SEED).fit(Pc.X[trc], Pc.target[trc])
check.near('... and the forest is RandomForestRegressor.predict', {m['set']: m for m in rg['fit']['measures']}['Test']['rsquare'], metrics.r2_score(Pc.target[Pc.mask(2)], rfb.predict(Pc.X[Pc.mask(2)])), 1e-10)
rr = call('ensemble.fit', table=T, y='y', x=XS, kind='forest', validation='v', seed=SEED, settings={'rate': 0.5, 'early': False, 'trees': 12})
check('Bootstrap Sample Rate 0.5: half the training rows drawn per tree', (rr['trees'][0]['ib_n'], [v for k_, v, *_ in rr['spec']['right'] if k_ == 'Bootstrap Samples']), (float(round(trc.sum() * 0.5)), [int(round(trc.sum() * 0.5))]))

# ---- a categorical forest: JMP's probabilities, never 0 ---------------------------------------------------------
r3 = call('ensemble.fit', table=T, y='three', x=XS, kind='forest', validation='v', seed=SEED, settings={'early': False, 'trees': 25})
rfc3 = RandomForestClassifier(n_estimators=25, criterion='entropy', max_features=E.features_for(4, 5, 7), max_leaf_nodes=2001, min_samples_leaf=5,
                              random_state=SEED).fit(P3.X[tr], P3.target[tr])
ycol = np.searchsorted(rfc3.classes_, P3.target[tr])
probs, g2 = [], {c: 0.0 for c in XS}
fcol3 = {j: c for c in XS for j in P3.groups[c]}
for tree, drawn in zip(rfc3.estimators_, rfc3.estimators_samples_):
    oob = np.bincount(drawn, minlength=int(tr.sum())) == 0
    est = E.jmp_probs(tree, 0.9)
    loss = E.oob_losses(tree, P3.X[tr][oob], ycol[oob], np.ones(int(oob.sum())), est, True)
    k = E.kept_splits(loss, 10)
    rep = E.stands_for(E.parents(tree), k)
    full = np.zeros((tree.tree_.node_count, 3))
    full[:, rfc3.classes_] = est
    probs.append(full[rep[tree.apply(P3.X)]])
    tt = tree.tree_
    cn = tt.value[:, 0, :] * tt.weighted_n_node_samples[:, None]
    G = lambda node: float(-2 * sum(v * math.log(v / cn[node].sum()) for v in cn[node] if v > 0))  # noqa: E731
    parent = E.parents(tree)
    for s in range(1, k + 1):
        q = parent[2 * s - 1]
        g2[fcol3[int(tt.feature[q])]] += G(q) - G(tt.children_left[q]) - G(tt.children_right[q])
fp = np.mean(probs, axis=0)
M3 = {m['set']: m for m in r3['fit']['measures']}
for k_, name in enumerate(pv.SETS):
    m = P3.mask(k_)
    check.near(f'categorical forest, {name}: Mean -Log p = log_loss of the mean of the trees\' JMP probabilities', M3[name]['mean_neg_log_p'], metrics.log_loss(P3.target[m], fp[m], labels=[0, 1, 2]), 1e-10)
    check.near(f'categorical forest, {name}: Misclassification Rate = 1 - accuracy', M3[name]['misclassification'], 1 - metrics.accuracy_score(P3.target[m], fp.argmax(1)[m]), 1e-12)
check('no predicted probability is exactly 0 or 1 (JMP\'s prior), though scikit-learn\'s own forest gives 0s', (float(fp.min()) > 0, float(fp.max()) < 1, bool((rfc3.predict_proba(P3.X) == 0).any())), (True, True, True))
cc3 = {row['column']: row for row in r3['contributions']['rows']}
check('categorical: Column Contributions are G² (2 × the entropy in nats, from the node counts)', r3['contributions']['label'], 'G²')
check.near('... G²parent - G²left - G²right summed over the kept splits', max(abs(cc3[c]['value'] - g2[c]) / max(1, g2[c]) for c in XS), 0.0, abs_=1e-9)
sv = call('ensemble.save', table=T, y='three', x=XS, kind='forest', validation='v', seed=SEED, settings={'early': False, 'trees': 25})
check('Save Predicteds: a probability per level and the most likely level, for every row', (sv['names'], sv['most_name'], len(sv['rows'])), (['Prob[lo]', 'Prob[mid]', 'Prob[hi]'], 'Most Likely three', n))
check.near('... the forest\'s probabilities', mx(np.array(sv['prob'])[P3.index], fp), 0.0, abs_=1e-12)
rb3 = call('ensemble.fit', table=T, y='cls', x=XS, kind='forest', validation='v', seed=SEED, settings={'early': False, 'trees': 20})
check('two levels: AUC in Overall Statistics (and ROC and lift curves)', ('auc' in rb3['fit']['measures'][0], bool(rb3['fit']['roc']), bool(rb3['fit']['lift'])), (True, True, True))

# ---- weights and frequencies -------------------------------------------------------------------------------------------
rw = call('ensemble.fit', table=T, y='y', x=XS, kind='forest', validation='v', weight='w', freq='f', seed=SEED, settings={'early': False, 'trees': 15})
Pw = pv.prepare(T, 'y', XS, validation='v', weight='w', freq='f')
trw = Pw.train()
rfw = RandomForestRegressor(n_estimators=15, max_features=E.features_for(4, 5, 7), max_leaf_nodes=2001, min_samples_leaf=5, random_state=SEED).fit(Pw.X[trw], Pw.target[trw], sample_weight=Pw.w[trw])
eachw = []
for tree, drawn in zip(rfw.estimators_, rfw.estimators_samples_):
    oob = np.bincount(drawn, minlength=int(trw.sum())) == 0
    est = tree.tree_.value[:, 0, 0]
    k = E.kept_splits(E.oob_losses(tree, Pw.X[trw][oob], Pw.target[trw][oob], Pw.w[trw][oob], est, False), 10)
    eachw.append(est[E.stands_for(E.parents(tree), k)[tree.apply(Pw.X)]])
fw = np.mean(eachw, axis=0)
mv = Pw.mask(1)
check.near('Weight × Freq: case weights of the forest and its measures (r2_score with sample_weight)', {m['set']: m for m in rw['fit']['measures']}['Validation']['rsquare'],
           metrics.r2_score(Pw.target[mv], fw[mv], sample_weight=Pw.w[mv]), 1e-10)

# ---- a boosted tree, against scikit-learn ---------------------------------------------------------------------------------
rbt, lines = quiet(call, 'ensemble.fit', table=T, y='y', x=XS, kind='boosted', validation='v', seed=SEED, table_name='data', settings={'layers': 400, 'learn': 0.3})
cb = rbt['cumulative']
check('progress lines: "smui:progress boosted <done> <total>", the total at the end', (bool(lines), lines[-1].split()[1:] if lines else None), (True, ['boosted', '400', '400']))
gb = GradientBoostingRegressor(loss='squared_error', n_estimators=cb['grown'], learning_rate=0.3, max_leaf_nodes=4, max_depth=None, min_samples_leaf=5,
                               subsample=1.0, criterion='squared_error', random_state=SEED).fit(Pc.X[trc], Pc.target[trc])
stg = [metrics.r2_score(Pc.target[vm], p_) for p_ in gb.staged_predict(Pc.X[vm])]
check('boosted: stops at the first layer that does not improve the validation RSquare, keeps the layers before it',
      (cb['stopped'], cb['kept'], cb['grown'], all(stg[i] > stg[i - 1] for i in range(1, cb['kept'])), stg[cb['grown'] - 1] <= stg[cb['kept'] - 1]),
      (True, cb['grown'] - 1, cb['kept'] + 1, True, True))
check('the validation curve is scikit-learn\'s staged_predict', mx(next(s for s in cb['series'] if s['set'] == 'Validation')['stats']['rsquare'], stg), 0.0)
gbk = GradientBoostingRegressor(loss='squared_error', n_estimators=cb['kept'], learning_rate=0.3, max_leaf_nodes=4, max_depth=None, min_samples_leaf=5,
                                subsample=1.0, criterion='squared_error', random_state=SEED).fit(Pc.X[trc], Pc.target[trc])
MB = {m['set']: m for m in rbt['fit']['measures']}
for k_, name in enumerate(pv.SETS):
    m = Pc.mask(k_)
    check.near(f'boosted {name} RSquare = GradientBoostingRegressor(n_estimators=kept).predict', MB[name]['rsquare'], metrics.r2_score(Pc.target[m], gbk.predict(Pc.X[m])), 1e-10)
svb = call('ensemble.save', table=T, y='y', x=XS, kind='boosted', validation='v', seed=SEED, settings={'layers': 400, 'learn': 0.3})
Xall, okrows = Pc.all_rows()
check.near('Save Predicteds and Residuals: every row of the table, by the kept layers', mx(svb['values'], gbk.predict(Xall)), 0.0, abs_=1e-12)
check.near('... residuals = y - predicted', mx(svb['residuals'], np.array(y)[okrows] - gbk.predict(Xall)), 0.0, abs_=1e-12)
ssb = {c: 0.0 for c in XS}
nb = {c: 0 for c in XS}
for tree in gbk.estimators_.ravel():
    tt = tree.tree_
    for q in np.flatnonzero(tt.children_left >= 0):
        L_, R_ = tt.children_left[q], tt.children_right[q]
        ssb[fcol[int(tt.feature[q])]] += tt.impurity[q] * tt.weighted_n_node_samples[q] - tt.impurity[L_] * tt.weighted_n_node_samples[L_] - tt.impurity[R_] * tt.weighted_n_node_samples[R_]
        nb[fcol[int(tt.feature[q])]] += 1
ccb = {row['column']: row for row in rbt['contributions']['rows']}
check('boosted Column Contributions: 3 splits per layer, each on a column', (sum(nb.values()), {c: ccb[c]['splits'] for c in XS}), (3 * cb['kept'], nb))
rb50 = call('ensemble.fit', table=T, y='y', x=XS, kind='boosted', validation='v', seed=SEED)
check('the defaults on these data: all 50 layers improve the validation RSquare, so all are kept', (rb50['cumulative']['kept'], rb50['cumulative']['stopped']), (50, False))
check.near('... and the SS of the residuals each split takes away', max(abs(ccb[c]['value'] - ssb[c]) / max(1, ssb[c]) for c in XS), 0.0, abs_=1e-9)
rbs = call('ensemble.fit', table=T, y='y', x=XS, kind='boosted', validation='v', seed=SEED, settings={'rowRate': 0.6, 'colRate': 0.5, 'early': False, 'layers': 20, 'splits': 5, 'learn': 0.2})
gbs = GradientBoostingRegressor(loss='squared_error', n_estimators=20, learning_rate=0.2, max_leaf_nodes=6, max_depth=None, min_samples_leaf=5, subsample=0.6,
                                max_features=round(0.5 * Pc.X.shape[1]), criterion='squared_error', random_state=SEED).fit(Pc.X[trc], Pc.target[trc])
check.near('Row and Column Sampling Rates: subsample and max_features (per split in scikit-learn)', {m['set']: m for m in rbs['fit']['measures']}['Test']['rsquare'],
           metrics.r2_score(Pc.target[Pc.mask(2)], gbs.predict(Pc.X[Pc.mask(2)])), 1e-10)
check('Early Stopping off: every layer', (rbs['cumulative']['kept'], rbs['cumulative']['grown']), (20, 20))
# categorical boosting
rbc = call('ensemble.fit', table=T, y='cls', x=XS, kind='boosted', validation='v', seed=SEED)
Pb = pv.prepare(T, 'cls', XS, validation='v')
trb = Pb.train()
gbc = GradientBoostingClassifier(n_estimators=rbc['cumulative']['kept'], learning_rate=0.1, max_leaf_nodes=4, max_depth=None, min_samples_leaf=5,
                                 criterion='squared_error', random_state=SEED).fit(Pb.X[trb], Pb.target[trb])
pb_ = Pb.proba(gbc, Pb.X)
MBC = {m['set']: m for m in rbc['fit']['measures']}
for k_, name in enumerate(pv.SETS):
    m = Pb.mask(k_)
    check.near(f'boosted two levels, {name}: AUC = roc_auc_score of GradientBoostingClassifier', MBC[name]['auc'], metrics.roc_auc_score(Pb.target[m], pb_[m, 1]), 1e-10)
ent = [None if s['stats']['entropy_rsquare'] is None else s['stats']['entropy_rsquare'] for s in rbc['cumulative']['series'] if s['set'] == 'Validation'][0]
check('categorical boosting stops by the validation Entropy RSquare', int(np.argmax(ent)) + 1 == rbc['cumulative']['kept'], True)
rb3b = call('ensemble.fit', table=T, y='three', x=XS, kind='boosted', validation='v', seed=SEED, settings={'early': False, 'layers': 15})
gb3 = GradientBoostingClassifier(n_estimators=15, learning_rate=0.1, max_leaf_nodes=4, max_depth=None, min_samples_leaf=5, criterion='squared_error', random_state=SEED).fit(P3.X[tr], P3.target[tr])
check.near('three levels (beyond JMP, which boosts two): a tree per level per layer, log_loss as scikit-learn\'s', {m['set']: m for m in rb3b['fit']['measures']}['Validation']['mean_neg_log_p'],
           metrics.log_loss(P3.target[P3.mask(1)], P3.proba(gb3, P3.X[P3.mask(1)]), labels=[0, 1, 2]), 1e-10)
check('... 3 trees in each of the 15 layers', sum(row['splits'] for row in rb3b['contributions']['rows']), 15 * 3 * 3)

# ---- Multiple Fits ------------------------------------------------------------------------------------------------------
rm = call('ensemble.fit', table=T, y='y', x=XS, kind='forest', validation='v', seed=SEED, settings={'terms': 2, 'maxTerms': 5, 'multi': True, 'trees': 30})
sm = rm['summaries']
check('Multiple Fits over Number of Terms 2 to 5: forests with 2, 3, 4, 5 terms', [row['n_terms'] for row in sm['rows']], [2, 3, 4, 5])
vals = [row['rsquare'] for row in sm['rows']]
check('the fit shown is the one with the largest validation RSquare', (rm['best'], rm['shown'], sm['rows'][rm['best']]['best']), (int(np.argmax(vals)), int(np.argmax(vals)), True))
check.near('... whose Overall Statistics are the summary\'s validation RSquare', {m['set']: m for m in rm['fit']['measures']}['Validation']['rsquare'], max(vals), 1e-12)
other = (rm['best'] + 1) % 4
rm2 = call('ensemble.fit', table=T, y='y', x=XS, kind='forest', validation='v', seed=SEED, settings={'terms': 2, 'maxTerms': 5, 'multi': True, 'trees': 30}, shown=other)
check('shown picks another fit (a click on its line)', (rm2['shown'], [v for k_, v, *_ in rm2['spec']['left'] if k_ == 'Number of Terms Sampled per Split']), (other, [sm['rows'][other]['n_terms']]))
check.near('... with its own statistics', {m['set']: m for m in rm2['fit']['measures']}['Validation']['rsquare'], vals[other], 1e-12)
rmb = call('ensemble.fit', table=T, y='cls', x=XS, kind='boosted', validation='v', seed=SEED, settings={'splits': 2, 'maxSplits': 3, 'learn': 0.1, 'maxLearn': 0.2, 'multi': True})
check('Multiple Fits over Splits and Learning Rate: 2 × 2 boosted trees, best by the validation Entropy RSquare',
      ([(row['splits'], row['learn']) for row in rmb['summaries']['rows']], rmb['best']),
      ([(2, 0.1), (2, 0.2), (3, 0.1), (3, 0.2)], int(np.argmax([row['entropy_rsquare'] for row in rmb['summaries']['rows']]))))
rmn = call('ensemble.fit', table=T, y='y', x=XS, kind='forest', seed=SEED, settings={'terms': 3, 'maxTerms': 4, 'multi': True, 'trees': 20})
check('a forest without validation rows chooses by the out-of-bag statistic', (rmn['by'], len(rmn['summaries']['rows'])), ('oob', 2))
rmbn = call('ensemble.fit', table=T, y='y', x=XS, kind='boosted', seed=SEED, settings={'multi': True, 'maxSplits': 4})
check('boosted Multiple Fits without validation rows: one fit, and a note', (rmbn['multi'], any('no' in s_ or 'none' in s_ for s_ in rmbn['notes'])), (False, True))

# ---- the profiler, the tree views, the permutation importance ---------------------------------------------------------------------
prof = call('ensemble.profile', table=T, y='y', x=XS, kind='forest', validation='v', seed=SEED, current={'x1': 0.5, 'g': 'b'}, grid=9)
F0 = E.model_of(T, None, 'y', XS, 'forest', validation='v', seed=SEED)
fit0 = F0.fits[F0.best]
x2m = prof['factors'][1]['current']
grid = np.linspace(prof['factors'][0]['min'], prof['factors'][0]['max'], 9)
Xg = Pc.encode_settings([{'x1': v, 'x2': x2m, 'g': 'b', 'x3': prof['factors'][3]['current'], 'x4': prof['factors'][4]['current']} for v in grid])
check.near('the profiler: the forest\'s prediction over x1, the others at their current values', mx(prof['responses'][0]['traces'][0]['pred'], fit0.predict(Xg)), 0.0, abs_=1e-12)
check.near('... the current prediction', prof['responses'][0]['current']['pred'], float(fit0.predict(Pc.encode_settings([{'x1': 0.5, 'x2': x2m, 'g': 'b', 'x3': prof['factors'][3]['current'], 'x4': prof['factors'][4]['current']}]))[0]), 1e-12)
profc = call('ensemble.profile', table=T, y='three', x=XS, kind='boosted', validation='v', seed=SEED)
check('a categorical response: a probability row per level, adding to 1', ([p_['name'] for p_ in profc['responses']], bool(np.allclose(np.sum([p_['traces'][0]['pred'] for p_ in profc['responses']], axis=0), 1))),
      (['Prob[lo]', 'Prob[mid]', 'Prob[hi]'], True))
imp = call('ensemble.importance', table=T, y='y', x=XS, kind='boosted', validation='v', seed=SEED, imp_n=256)
check('the profiler\'s Assess Variable Importance runs on the model', 'error' not in imp, True)
tv = call('ensemble.tree', table=T, y='y', x=XS, kind='forest', validation='v', seed=SEED, index=2)
check('Show Trees: tree 2 of the kept trees, from All Rows, as many leaves as splits + 1',
      (tv['index'], tv['count'], tv['lines'][0]['text'], sum(1 for ln in tv['lines'] if ln['leaf'])), (2, kept, 'All Rows', r['trees'][1]['splits'] + 1))
check('... each split in words, and each node\'s count and mean', all(('<=' in ln['text'] or '>' in ln['text'] or '=' in ln['text'] or '≠' in ln['text']) for ln in tv['lines'][1:]) and 'estimate' in tv['lines'][0], True)
check.near('... the root\'s mean is the in-bag mean', tv['lines'][0]['estimate'], float(rf.estimators_[1].tree_.value[0, 0, 0]), 1e-12)
tvb = call('ensemble.tree', table=T, y='cls', x=XS, kind='boosted', validation='v', seed=SEED, index=1, detail='names')
check('a boosted layer with names only: 3 splits, 4 leaves', (sum(1 for ln in tvb['lines'] if ln['leaf']), 'estimate' in tvb['lines'][0], tvb['what']), (4, False, 'Layer'))
check('a one-hot split in words: g = b or g ≠ b', E._condition(Pc, Pc.features.index('g[b]'), True, 0.5), 'g ≠ b')
pm = call('ensemble.permutation', table=T, y='y', x=XS, kind='forest', validation='v', seed=SEED, repeats=3)
rng2 = np.random.default_rng(SEED)
Xv = Pc.X[vm]
base = metrics.r2_score(Pc.target[vm], fit0.predict(Xv))
want = {}
for c in XS:
    idx = Pc.groups[c]
    d_ = []
    for _ in range(3):
        Xp = Xv.copy()
        Xp[:, idx] = Xv[rng2.permutation(len(Xv))][:, idx]
        d_.append(base - metrics.r2_score(Pc.target[vm], fit0.predict(Xp)))
    want[c] = float(np.mean(d_))
got = {row['column']: row['value'] for row in pm['contributions']['rows']}
check('permutation importance on the validation rows, a categorical column\'s 0/1 columns shuffled together', (pm['set'], pm['repeats']), ('Validation', 3))
check.near('... the fall in r2_score, as computed here with the same draws', max(abs(got[c] - want[c]) for c in XS), 0.0, abs_=1e-12)

# ---- errors ----------------------------------------------------------------------------------------------------------
one = table({'y': ['a'] * 30 + ['b'] * 3, 'x': list(range(33)), 'v': ['Training'] * 30 + ['Validation'] * 3}, types={'y': 'nominal', 'v': 'nominal'})
for kind in ('forest', 'boosted'):
    try:
        call('ensemble.fit', table=one, y='y', x=['x'], kind=kind, validation='v', seed=1)
        check(f'{kind}: one level in the training rows is an error that says so', 'no error', 'error')
    except Exception as ex:
        check(f'{kind}: one level in the training rows is an error that says so', 'one level in the training rows' in str(ex), True)
try:
    call('ensemble.fit', table=T, y='y', x=XS, kind='forest', seed=1, settings={'trees': -3})
    check('a bad setting from the page is an error', 'no error', 'error')
except Exception as ex:
    check('a bad setting from the page is an error', 'Number of Trees' in str(ex), True)

# ---- the Python shown, on a CSV export ------------------------------------------------------------------------------------
work = tempfile.mkdtemp()
pd.DataFrame(cols).to_csv(os.path.join(work, 'data.csv'), index=False)


def run_code(res):
    p_ = subprocess.run([sys.executable, '-c', res['code']], cwd=work, capture_output=True, text=True, timeout=900)
    if p_.returncode:
        print(p_.stderr[-3000:])
        return None
    out = {}
    for ln in p_.stdout.splitlines():
        t_ = ln.split()
        if t_ and t_[0] in ('curve', 'measures'):
            out[(t_[0], t_[1])] = [float(v) for v in t_[2:]]
    return out


def compare(res, label):
    got = run_code(res)
    if got is None:
        check(f'the code runs: {label}', False, True)
        return
    worst, cnt_ = 0.0, 0
    keys = E.STAT_KEYS[res['response']]
    for m in res['fit']['measures']:
        if m['set'] == 'Out of Bag':
            continue
        g_ = got[('measures', m['set'])]
        for a, kk in zip(g_, keys):
            worst = max(worst, abs(a - m[kk]) / max(1.0, abs(m[kk])))
            cnt_ += 1
    main = E._main_stat(pv.prepare(T, res['_y'], res['_x'], validation=res['_v']))
    for s in res['cumulative']['series']:
        if s['set'] == 'Out of Bag':
            continue
        g_ = got[('curve', s['set'])]
        worst = max(worst, mx(g_, s['stats'][main]))
        cnt_ += len(g_)
    check.near(f'the code prints the report\'s Overall Statistics and Cumulative Validation ({cnt_} numbers): {label}', worst, 0.0, abs_=1e-9)


cases = [
    ('a forest, continuous, early stopping', dict(y='y', x=XS, kind='forest', validation='v')),
    ('a forest, three levels, JMP\'s probabilities', dict(y='three', x=XS, kind='forest', validation='v', settings={'trees': 30})),
    ('a forest, Informative Missing, weight and frequency, a numeric Validation column', dict(y='y', x=['x1m', 'x2', 'gm', 'x3'], kind='forest', validation='vn', weight='w', freq='f', settings={'trees': 25, 'minSplits': 4})),
    ('a forest grown to its maximum, a row subset, no validation', dict(y='cls', x=XS, kind='forest', settings={'trees': 15, 'stop': 'none'}, rows=list(range(0, 800)))),
    ('a boosted tree, continuous, early stopping', dict(y='y', x=XS, kind='boosted', validation='v')),
    ('a boosted tree, two levels, sampling rates', dict(y='cls', x=XS, kind='boosted', validation='v', settings={'rowRate': 0.7, 'colRate': 0.6})),
    ('a boosted tree, three levels, a validation portion', dict(y='three', x=XS, kind='boosted', portion=0.3, settings={'layers': 20})),
]
for label, kw in cases:
    res = call('ensemble.fit', table=T, seed=SEED, table_name='data', **kw)
    res['_y'], res['_x'], res['_v'] = kw['y'], kw['x'], kw.get('validation')
    if kw.get('portion'):
        res['_v'] = None
    compare(res, label)

# the permutation code after the report's code
res = call('ensemble.fit', table=T, y='y', x=XS, kind='boosted', validation='v', seed=SEED, table_name='data')
pmb = call('ensemble.permutation', table=T, y='y', x=XS, kind='boosted', validation='v', seed=SEED, repeats=2, table_name='data')
p_ = subprocess.run([sys.executable, '-c', res['code'] + '\n\n' + pmb['code']], cwd=work, capture_output=True, text=True, timeout=900)
if p_.returncode:
    print(p_.stderr[-2000:])
gotp = {ln.split()[1]: float(ln.split()[2]) for ln in p_.stdout.splitlines() if ln.startswith('permutation ')}
check.near('the permutation importance code gives the report\'s numbers', max((abs(gotp.get(row['column'], math.inf) - row['value']) for row in pmb['contributions']['rows']), default=math.inf), 0.0, abs_=1e-9)

sys.exit(check.done())
