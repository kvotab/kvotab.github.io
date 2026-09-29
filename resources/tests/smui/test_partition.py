#!/usr/bin/env python3
"""Analyze > Predictive Modeling > Partition (resources/py/smui/partition.py),
through registry.dispatch as the page calls it.

The best split of every kind of column is checked against a brute-force
search written here (every cut, every grouping of levels, every side for the
missing rows) and against scikit-learn's DecisionTreeRegressor and
DecisionTreeClassifier (log loss) on the same column with the same minimum
leaf size; the split statistics against scipy (f_oneway, chi2_contingency
with the log-likelihood); the LogWorth adjustment against the formulas
written out here and by Monte Carlo (with no effect an adjusted p-value is
below 0.05 in at most about 5% of samples, the unadjusted one far more
often); JMP's smoothing of the leaf probabilities by hand; the steps (Split,
Prune, Go, a node's own splits), the split history, the Measures of Fit,
the column contributions, Freq against duplicated rows, Save Columns, the
profiler, K-fold crossvalidation by hand, CART against scikit-learn called
directly, and the Python the report shows, run on a CSV export of the table.

    python3 resources/tests/smui/test_partition.py
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
import pandas as pd
from scipy import stats

from backend import FAILED, Checks, call, table

check = Checks()
check('partition.py imports', 'partition' in FAILED, False)
from smui import partition as pt, predictive as pv, registry  # noqa: E402

try:
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
except ImportError:
    print('scikit-learn 1.8 is needed for these tests (Pyodide 314.0.7 has 1.8.0)')
    sys.exit(1)

rng = np.random.default_rng(20260927)
n = 400
x1 = rng.normal(0, 1, n)
x2 = rng.uniform(0, 10, n).round(2)                      # ties
g = rng.choice(list('abcde'), n, p=[0.3, 0.25, 0.2, 0.15, 0.1])
o = rng.choice(['o1', 'o2', 'o3', 'o4', 'o5'], n)
y = 2 + 2.5 * (x1 > 0.4) + np.where(np.isin(g, ['b', 'd']), 1.5, 0.0) + 0.15 * x2 + rng.normal(0, 1, n)
x1m = x1.copy()
x1m[rng.choice(n, 30, replace=False)] = np.nan
ym = np.where(np.isnan(x1m), y + 3, y)                     # missing x1m means a higher response
gm = g.astype(object).copy()
gm[rng.choice(n, 25, replace=False)] = None
cls = np.where(y + rng.normal(0, 1.2, n) > 3.8, 'yes', 'no')
three = np.where(y < 2.8, 'lo', np.where(y < 4.5, 'mid', 'hi'))
w = rng.uniform(0.5, 2.0, n).round(3)
fq = rng.integers(1, 4, n).astype(float)
vnum = rng.choice([0.0, 1.0, 2.0], n, p=[0.6, 0.25, 0.15])
vtxt = np.array(['Training', 'Validation', 'Test'])[vnum.astype(int)]
cols = {'y': list(y), 'ym': list(ym), 'x1': list(x1), 'x1m': [None if np.isnan(v) else v for v in x1m], 'x2': list(x2), 'g': list(g), 'gm': list(gm),
        'o': list(o), 'cls': list(cls), 'three': list(three), 'w': list(w), 'f': list(fq), 'v': list(vnum), 'vt': list(vtxt)}
TYPES = {'g': 'nominal', 'gm': 'nominal', 'o': 'ordinal', 'cls': 'nominal', 'three': 'ordinal', 'vt': 'nominal'}
LEVELS = {'o': ['o1', 'o2', 'o3', 'o4', 'o5'], 'three': ['lo', 'mid', 'hi'], 'cls': ['no', 'yes'], 'g': list('abcde'), 'gm': list('abcde')}
T = table(cols, types=TYPES, levels=LEVELS)
SK = ['scikit-learn']


def fit(**kw):
    kw.setdefault('table', T)
    return call('partition.fit', **kw)


def grown(y_, x_, steps=(), **kw):
    """The engine's tree for these settings, as the report builds it."""
    sp = pt._spec(y_, x_, steps=list(steps), **kw)
    return pt._grown(kw.pop('table', T), None, sp)


# ---- registration -----------------------------------------------------------------------------------------------
names = registry.names()
want = ['partition.fit', 'partition.save', 'partition.leaves', 'partition.kfold', 'partition.profile', 'partition.maximize', 'partition.importance']
check('the JMP method\'s functions are registered', all(nm in names for nm in want), True)
check('... and none of them loads scikit-learn', [json.loads(registry.packages_for(nm)) for nm in want], [[]] * len(want))
cart = ['partition.cart_fit', 'partition.cart_save', 'partition.cart_leaves', 'partition.cart_kfold', 'partition.cart.profile']
check('the CART functions load scikit-learn', [json.loads(registry.packages_for(nm)) for nm in cart], [SK] * len(cart))

# ---- the best cut of a continuous X, by brute force and by scikit-learn -----------------------------------------


def brute_cut(x, yv, wv=None, minsize=5):
    """Every cut between neighbouring distinct values: the largest SS between the sides."""
    wv = np.ones(len(yv)) if wv is None else wv
    vals = np.unique(x)
    best = (-1.0, None)
    for k in range(1, len(vals)):
        left = x < vals[k]
        if left.sum() < minsize or (~left).sum() < minsize:
            continue
        a, b = wv[left], wv[~left]
        ml, mr = np.sum(a * yv[left]) / a.sum(), np.sum(b * yv[~left]) / b.sum()
        ss = a.sum() * b.sum() / wv.sum() * (ml - mr) ** 2
        if ss > best[0] * (1 + 1e-12):
            best = (ss, (vals[k - 1], vals[k]))
    return best


P, t, _ = grown('y', ['x1', 'x2', 'g', 'o'])
root = t.root
cands = root.candidates()
ss, (lo, hi) = brute_cut(x1, y)
c1 = cands[0]
check.near('continuous X: the best cut\'s SS is the brute-force maximum', c1['stat'], ss, 1e-9)
check('... and its cut lies between the same two neighbouring values', lo < c1['rule'].cut <= hi, True)
check('... written as the shortest decimal between them', len(pt.num_text(c1['rule'].cut)) <= len(repr(hi)), True)
side = c1['rule'].side(x1)
check('... the rows below the cut go to one side', bool(np.all(side == (x1 >= c1['rule'].cut))), True)
sk = DecisionTreeRegressor(max_depth=1, min_samples_leaf=5).fit(x1[:, None], y)
tr_ = sk.tree_
sk_ss = tr_.impurity[0] * tr_.weighted_n_node_samples[0] - tr_.impurity[1] * tr_.weighted_n_node_samples[1] - tr_.impurity[2] * tr_.weighted_n_node_samples[2]
check.near('... the SS scikit-learn\'s regressor (max_depth 1) finds on that column', c1['stat'], sk_ss, 1e-9)
check('... and the same rows on each side', bool(np.all((x1 <= tr_.threshold[0]) == (x1 < c1['rule'].cut))), True)
ss2, _ = brute_cut(x2, y)
check.near('a continuous X with ties: the brute-force maximum', cands[1]['stat'], ss2, 1e-9)
left = side == 0
f_p = stats.f_oneway(y[left], y[~left]).pvalue
check.near('the split\'s p-value is the two-group F test (scipy f_oneway)', math.exp(c1['lp']), f_p, 1e-8)
check('between(): the shortest decimal in (lo, hi]', [pt.between(0.2994, 0.31), pt.between(41, 42), pt.between(-1.5, -1.2), pt.between(2.34567, 2.3457)], [0.3, 42.0, -1.4, 2.3457])
check('num_text: 12 not 12.0, else exact', [pt.num_text(12.0), pt.num_text(0.1), pt.num_text(-3.25)], ['12', '0.1', '-3.25'])

# weights: the weighted SS
Pw, tw, _ = grown('y', ['x1'], weight='w')
ssw, _ = brute_cut(x1, y, w)
check.near('with a Weight: the weighted SS between the sides', tw.root.candidates()[0]['stat'], ssw, 1e-9)

# ---- a nominal X: the best grouping of its levels -----------------------------------------------------------------


def groupings(levels):
    """Every split of the levels in two, each once."""
    first, rest = levels[0], levels[1:]
    for mask in range(0, 2 ** len(rest)):
        a = [first] + [lv for i, lv in enumerate(rest) if not (mask >> i) & 1]
        b = [lv for i, lv in enumerate(rest) if (mask >> i) & 1]
        if b:
            yield a, b


def brute_group_ss(gv, yv, minsize=5):
    best = -1
    for a, b in groupings(sorted(set(gv))):
        L = np.isin(gv, a)
        if L.sum() < minsize or (~L).sum() < minsize:
            continue
        best = max(best, L.sum() * (~L).sum() / len(yv) * (yv[L].mean() - yv[~L].mean()) ** 2)
    return best


cg = cands[2]
check.near('nominal X, continuous Y: the levels in the order of their means find the best of all 15 groupings', cg['stat'], brute_group_ss(g, y), 1e-9)
check('... here b and d apart from the rest (the truth)', sorted([cg['labels'][0], cg['labels'][1]]), ['g(a, c, e)', 'g(b, d)'])


def g2(tab):
    tab = np.asarray(tab, float)
    tab = tab[:, tab.sum(0) > 0]
    return float(stats.chi2_contingency(tab, correction=False, lambda_='log-likelihood')[0]) if tab.shape[1] > 1 else 0.0


def brute_group_g2(gv, yv, labels, minsize=5):
    best = (-1, None)
    for a, b in groupings(sorted(set(gv))):
        L = np.isin(gv, a)
        if L.sum() < minsize or (~L).sum() < minsize:
            continue
        s = g2([[np.sum(L & (yv == lv)) for lv in labels], [np.sum(~L & (yv == lv)) for lv in labels]])
        if s > best[0] + 1e-9:
            best = (s, sorted(a))
    return best


Pc, tc, _ = grown('three', ['x1', 'g', 'o'])
cc = tc.root.candidates()
best3, grp = brute_group_g2(g, three, ['lo', 'mid', 'hi'])
check.near('nominal X, a three-level response: every grouping tried, the brute-force G² maximum', cc[1]['stat'], best3, 1e-9)
Pb, tb, _ = grown('cls', ['x1', 'g'])
bb = tb.root.candidates()
check.near('nominal X, a two-level response: the levels by rate find the best grouping', bb[1]['stat'], brute_group_g2(g, cls, ['no', 'yes'])[0], 1e-9)
# G² and its p-value against scipy; the cut against scikit-learn's classifier
sideb = bb[0]['rule'].side(x1)
tab = [[np.sum((sideb == s) & (cls == lv)) for lv in ('no', 'yes')] for s in (0, 1)]
chi = stats.chi2_contingency(np.array(tab), correction=False, lambda_='log-likelihood')
check.near('G² of a split is the likelihood-ratio chi-square of its 2 × levels table (scipy)', bb[0]['stat'], float(chi[0]), 1e-9)
check.near('... and its p-value', math.exp(bb[0]['lp']), float(chi[1]), 1e-8)
skc = DecisionTreeClassifier(criterion='log_loss', max_depth=1, min_samples_leaf=5).fit(x1[:, None], cls)
tc_ = skc.tree_
g2_sk = 2 * math.log(2) * (tc_.impurity[0] * n - tc_.impurity[1] * tc_.weighted_n_node_samples[1] - tc_.impurity[2] * tc_.weighted_n_node_samples[2])
check.near('... the entropy decrease scikit-learn\'s classifier (log loss) finds, as G² (2 ln 2 × N × bits)', bb[0]['stat'], g2_sk, 1e-9)
check('... and the same rows on each side', bool(np.all((x1 <= tc_.threshold[0]) == (x1 < bb[0]['rule'].cut))), True)
# the node's G²
rates = np.bincount(np.searchsorted(['lo', 'mid', 'hi'], three) * 0 + np.array([['lo', 'mid', 'hi'].index(v) for v in three]), minlength=3)
check.near('a node\'s G² is −2 Σ n log(n/N)', tc.root.g2, -2 * float(np.sum(rates * np.log(rates / n))), 1e-9)

# an ordinal X is cut between neighbouring levels
co = cands[3]
codes = np.array([LEVELS['o'].index(v) for v in o])
best_o = max((codes < k).sum() * (codes >= k).sum() / n * (y[codes < k].mean() - y[codes >= k].mean()) ** 2 for k in range(1, 5))
check.near('ordinal X: the best of its 4 cuts between neighbouring levels', co['stat'], best_o, 1e-9)
Pn, tn, _ = grown('y', ['o'], ordinal_order=False)
check.near('Ordinal Restricts Order off: its levels grouped freely (the best of 15)', tn.root.candidates()[0]['stat'], brute_group_ss(o, y), 1e-9)
check('... never worse than the ordered cuts', tn.root.candidates()[0]['stat'] >= co['stat'] - 1e-9, True)

# ---- Informative Missing: missing rows to the side that fits best ------------------------------------------------------
Pm, tm, _ = grown('ym', ['x1m'])
cm = tm.root.candidates()[0]
miss = np.isnan(x1m)
best_m = (-1, None)
vals = np.unique(x1m[~miss])
for k in range(0, len(vals) + 1):
    for side_m in (0, 1):
        L = (x1m < vals[k]) if k < len(vals) else ~miss
        L = np.where(miss, side_m == 0, L & ~miss)
        if L.sum() < 5 or (~L).sum() < 5:
            continue
        s = L.sum() * (~L).sum() / n * (ym[L].mean() - ym[~L].mean()) ** 2
        if s > best_m[0] + 1e-9:
            best_m = (s, side_m)
check.near('Informative Missing: the best over every cut and both sides for the missing rows (brute force)', cm['stat'], best_m[0], 1e-9)
check('... the missing rows go to the side the brute force puts them', cm['rule'].miss, best_m[1])
check('... which is the side with the larger mean (their response is 3 higher)', cm['rule'].miss, cm['first'])
check('... and its condition says so', any('or Missing' in lab for lab in cm['labels']), True)
Pd, td, _ = grown('ym', ['x1m'], missing='drop')
check('Informative Missing off: the rows missing the factor are left out', len(Pd.index), int((~miss).sum()))
# a nominal X with a missing level: a level of its own
Pgm, tgm, _ = grown('y', ['gm'])
check('a missing level of a nominal X is a level of its own', 'Missing' in ''.join(tgm.root.candidates()[0]['labels']), True)

# ---- the LogWorth adjustment ---------------------------------------------------------------------------------------


def upcross(lp, m, N, d):
    """1 + Σ min(1, t_i f(r)/(√(2π) p)): the leading term of the improved Bonferroni bound, written out here."""
    p = math.exp(lp)
    r = math.sqrt(stats.chi2.isf(p, d))
    total = 1.0
    for a, b in zip(m[:-1], m[1:]):
        t_ = math.sqrt(1 - a * (N - b) / (b * (N - a)))
        total += min(1.0, t_ * stats.chi.pdf(r, d) / (math.sqrt(2 * math.pi) * p))
    return total


mw = np.array([w_ for w_ in np.cumsum(np.ones(n))[4:n - 5]])
check.near('ordered cuts: the multiplicity is 1 + the expected upcrossings between neighbouring cuts',
           math.exp(pt.ordered_mult(math.log(1e-4), mw, float(n), 1)), upcross(math.log(1e-4), mw, float(n), 1), 1e-9)
check.near('... for a chi process of 2 degrees of freedom too', math.exp(pt.ordered_mult(math.log(1e-6), mw, float(n), 2)), upcross(math.log(1e-6), mw, float(n), 2), 1e-9)
lsl = 1 / math.pi * math.exp(-stats.norm.isf(0.5e-4) ** 2 / 2)
tt = np.sqrt(1 - mw[:-1] * (n - mw[1:]) / (mw[1:] * (n - mw[:-1])))
check.near('... which for one degree of freedom is Lausen, Sauerbrei and Schumacher\'s (pLausen94) leading term',
           math.exp(pt.ordered_mult(math.log(1e-4), mw, float(n), 1)), 1 + np.sum(np.minimum(1, lsl * tt / 1e-4)), 1e-9)
check('... never more than Bonferroni over the cuts', math.exp(pt.ordered_mult(math.log(1e-30), mw, float(n), 1)) <= len(mw) + 1e-9, True)
check('LogWorth = −log10 of the p-value times the multiplicity', math.isclose(c1['logworth'], -(c1['lp'] + c1['lnM']) / math.log(10), rel_tol=1e-12), True)
# a nominal X: the smaller of Bonferroni over its groupings and Scheffé's bound
k_lv = 5
lnG = math.log(2 ** (k_lv - 1) - 1)
means = pd.Series(y).groupby(g).agg(['sum', 'count'])
ssb = float(np.sum(means['sum'] ** 2 / means['count']) - y.sum() ** 2 / n)
sse = float(np.sum((y - y.mean()) ** 2)) - ssb
lpS = stats.f.logsf(cg['stat'] / ((k_lv - 1) * sse / (n - k_lv)), k_lv - 1, n - k_lv)
check.near('nominal X: the multiplicity is min(Bonferroni over the 15 groupings, Scheffé\'s F bound)', cg['lnM'], max(0, min(lnG, lpS - cg['lp'])), 1e-9)
lpS3 = stats.chi2.logsf(cc[1]['stat'], (k_lv - 1) * 2)
check.near('... for a categorical response Scheffé\'s is the chi-square of the whole levels table', cc[1]['lnM'], max(0, min(lnG, lpS3 - cc[1]['lp'])), 1e-9)

# with no effect: the adjusted p-values reject about as often as they should, the unadjusted ones far more
mc = np.random.default_rng(7)


def null_rates(kind, reps, nn=200, L=0, u=None):
    adj, raw = [], []
    for _ in range(reps):
        x = mc.normal(size=nn) if kind == 'continuous' else mc.integers(0, u, nn).astype(float)
        col = pt.Col('x', kind, 0, None, None if kind == 'continuous' else [str(i) for i in range(u)])
        yy = mc.integers(0, L, nn) if L else mc.normal(size=nn)
        c = pt.Tree([col], x[:, None], yy, L).root.best()
        if c is not None:
            adj.append(math.exp(min(0.0, c['lp'] + c['lnM'])))
            raw.append(math.exp(c['lp']))
    return float(np.mean(np.array(adj) < 0.05)), float(np.mean(np.array(raw) < 0.05))


for label, args, most in [('a continuous X (200 values), continuous Y', ('continuous', 600), 0.06), ('a continuous X, a two-level Y', ('continuous', 600, 200, 2), 0.06),
                          ('a continuous X, a three-level Y', ('continuous', 600, 200, 3), 0.06), ('a nominal X of 6 levels', ('nominal', 600, 200, 0, 6), 0.06),
                          ('a nominal X of 6 levels, a three-level Y', ('nominal', 600, 200, 3, 6), 0.07), ('an ordinal X of 5 levels', ('ordinal', 600, 200, 0, 5), 0.075)]:
    a_, r_ = null_rates(*args)
    check(f'no effect, {label}: adjusted p < 0.05 in {a_:.3f} of samples (at most about 0.05), unadjusted {r_:.3f}', (a_ <= most, r_ > a_), (True, True))
a_, r_ = null_rates('continuous', 600)
check('... the best of 200 unadjusted cuts is below 0.05 in more than half the samples', r_ > 0.5, True)

# ---- JMP's smoothed probabilities -----------------------------------------------------------------------------------
Ps, ts, _ = grown('three', ['x1', 'g'], steps=[{'op': 'split', 'n': 3}])
r0 = ts.root
check('the root\'s probabilities are its rates', bool(np.allclose(r0.prob, r0.rate)), True)
deep = [nd for nd in ts.nodes() if len(nd.path) >= 2][0]
par, gp = deep.parent, deep.parent.parent
prior_par = 0.9 * gp.prior + 0.1 * gp.prob
prior_deep = 0.9 * prior_par + 0.1 * par.prob
cnt_deep = np.array([np.sum(three[deep.tr] == lv) for lv in ('lo', 'mid', 'hi')], float)
check('a node two levels down: Prob = (n + prior)/(N + 1), prior = 0.9 × parent\'s prior + 0.1 × parent\'s Prob (JMP, by hand)',
      bool(np.allclose(deep.prob, (cnt_deep + prior_deep) / (cnt_deep.sum() + 1), atol=1e-12)), True)
check('... the probabilities add to 1', bool(np.allclose(sum(nd.prob.sum() for nd in ts.leaves()) / len(ts.leaves()), 1)), True)
pure = pt.Tree([pt.Col('x', 'continuous', 0)], np.r_[np.zeros(20), np.ones(20)][:, None], np.r_[np.zeros(20, int), np.r_[np.zeros(4, int), np.ones(16, int)]], 2)
pure.split_best()
pl = pure.leaves()
check('a pure leaf: its rate is 0 but its probability is not', (min(pl[0].rate.min(), pl[1].rate.min()) == 0, min(pl[0].prob.min(), pl[1].prob.min()) > 0), (True, True))

# ---- steps: Split, Prune, a node's own splits, Go ------------------------------------------------------------------------
r = fit(y='y', x=['x1', 'x2', 'g', 'o'], steps=[{'op': 'split', 'n': 5}])
check('Split 5 times: 5 splits, 6 leaves', (r['splits'], len(r['leaves'])), (5, 6))
check('... the first split is the root\'s best by LogWorth', r['nodes'][0]['split']['column'], t.cols[max(cands, key=lambda c: c['logworth'])['j']].name)
Pq, tq, _ = grown('y', ['x1', 'x2', 'g', 'o'], steps=[{'op': 'split', 'n': 5}])
last = [nd for nd in tq.nodes() if nd.children and all(ch.children is None for ch in nd.children)]
worst = min(last, key=lambda nd: (nd.cand['logworth'], nd.cand['stat']))
r2 = fit(y='y', x=['x1', 'x2', 'g', 'o'], steps=[{'op': 'split', 'n': 5}, {'op': 'prune'}])
check('Prune takes back the split with two leaves and the smallest LogWorth', (r2['splits'], worst.path in {nd['path'] for nd in r2['nodes'] if nd['leaf']}), (4, True))
lw_leaves = sorted([(c['logworth'], nd['path']) for nd in r['nodes'] if nd['leaf'] for c in nd['cands'] if c['best']], reverse=True)
r3 = fit(y='y', x=['x1', 'x2', 'g', 'o'], steps=[{'op': 'split', 'n': 6}])
new = [nd['path'] for nd in r3['nodes'] if nd['split'] and nd['split']['order'] == 5]
check('the next Split takes the leaf whose best split has the largest LogWorth', new, [lw_leaves[0][1]])
check('every leaf keeps at least 5 rows (Minimum Size Split)', min(nd['count'] for nd in r3['nodes'] if nd['leaf']) >= 5, True)
r4 = fit(y='y', x=['x1', 'x2', 'g', 'o'], steps=[{'op': 'split', 'n': 30}], minsize=40)
check('Minimum Size Split 40: no leaf below 40 rows', min(nd['count'] for nd in r4['nodes'] if nd['leaf']) >= 40, True)
r5 = fit(y='y', x=['x1'], steps=[{'op': 'split'}], minsize=0.2)
check('Minimum Size Split 0.2: a share of the training rows (80 of 400)', (r5['minsize'], min(nd['count'] for nd in r5['nodes'] if nd['leaf']) >= 80), (80.0, True))
r6 = fit(y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'specific', 'node': '', 'col': 'x2', 'cut': 5}, {'op': 'here', 'node': 'L'}])
check('Split Specific at a value: the root split by x2 at 5, as asked', (r6['nodes'][0]['split']['column'], sorted(ch['label'] for ch in r6['nodes'] if ch['parent'] == '')), ('x2', ['x2<5', 'x2>=5']))
check('Split Here: the left child split at its best', r6['nodes'][1]['split'] is not None and r6['splits'] == 2, True)
r7 = fit(y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 4}, {'op': 'below', 'node': 'L'}])
check('Prune Below takes away everything under a node', all(not nd['path'].startswith('L') or nd['path'] == 'L' for nd in r7['nodes']), True)
r8 = fit(y='y', x=['x1', 'x2'], steps=[{'op': 'here', 'node': 'LRLR'}, {'op': 'specific', 'node': '', 'col': 'nope'}, {'op': 'split'}])
check('a step that cannot be done is noted and skipped; the rest are done', (len(r8['notes']), r8['splits']), (2, 1))
check('... the notes say which step and why', 'Step 1 (here)' in r8['notes'][0] and 'Step 2 (specific)' in r8['notes'][1], True)
r9 = fit(y='y', x=['x1'], steps=[{'op': 'go'}])
check('Go without validation rows: a note, nothing done', ('Go needs validation rows' in ' '.join(r9['notes']), r9['splits']), (True, 0))
# Go with a validation column
rg = fit(y='y', x=['x1', 'x2', 'g', 'o'], validation='v', steps=[{'op': 'go'}])
tr_ = rg['go']['trace']
bestv = max(e['Validation'] for e in tr_)
check('Go keeps the tree with the best validation RSquare', (rg['splits'], rg['go']['best']), (next(e['splits'] for e in tr_ if e['Validation'] == bestv), rg['splits']))
check('... after looking at the 10 splits past it, none better', (tr_[-1]['splits'] - rg['go']['best'], all(e['Validation'] <= bestv for e in tr_ if e['splits'] > rg['go']['best'])), (10, True))
check('... the summary\'s validation RSquare is that best', math.isclose(next(s_['rsquare'] for s_ in rg['summary'] if s_['set'] == 'Validation'), bestv, rel_tol=1e-12), True)
rgc = fit(y='cls', x=['x1', 'x2', 'g'], validation='vt', steps=[{'op': 'split'}, {'op': 'go'}])
trc = rgc['go']['trace']
check('Go for a categorical response: the best validation entropy RSquare, from where the tree stood', (rgc['go']['start'], rgc['splits'] == max(trc, key=lambda e: (e['Validation'], -e['splits']))['splits']), (1, True))

# ---- the split history, the summary, the Measures of Fit, contributions --------------------------------------------------
rh = fit(y='y', x=['x1', 'x2', 'g', 'o'], steps=[{'op': 'split', 'n': 4}], validation='v')
hist = rh['history']
ks = []
for k in range(5):
    rk = fit(y='y', x=['x1', 'x2', 'g', 'o'], steps=[{'op': 'split', 'n': k}] if k else [], validation='v')
    ks.append((rk['summary'][0]['rsquare'], rk['summary'][1]['rsquare']))
check('the split history: RSquare of each set after k splits is the tree of k splits\'', all(math.isclose(hist[k]['Training'], ks[k][0], rel_tol=1e-10, abs_tol=1e-12) and math.isclose(hist[k]['Validation'], ks[k][1], rel_tol=1e-10, abs_tol=1e-12) for k in range(5)), True)
Pm_, tm_, _ = grown('y', ['x1', 'x2', 'g', 'o'], steps=[{'op': 'split', 'n': 4}], validation='v')
fitted = tm_.fitted()
M = {m['set']: m for m in pv.measures(Pm_, fitted)}
check.near('the summary\'s RSquare and RASE are the Measures of Fit\'s', rh['summary'][0]['rase'], M['Training']['rase'], 1e-12)
check('... N counts the rows of each set', [s_['n'] for s_ in rh['summary']], [float((vnum == k).sum()) for k in (0, 1, 2)])
sst = float(np.sum((y[vnum == 0] - y[vnum == 0].mean()) ** 2))
split_ss = sum(nd['split']['stat'] for nd in rh['nodes'] if nd['split'])
check.near('training RSquare = the splits\' SS over the total SS', rh['summary'][0]['rsquare'], split_ss / sst, 1e-9)
con = rh['contributions']
check.near('column contributions: the columns\' SS add to the splits\'', sum(c['value'] for c in con['rows']), split_ss, 1e-9)
check('... with each column\'s number of splits', sum(c['splits'] for c in con['rows']), 4)
check('... and label SS (G^2 for a categorical response)', (con['label'], fit(y='cls', x=['x1', 'g'], steps=[{'op': 'split'}])['contributions']['label']), ('SS', 'G^2'))
check('the leaves\' predictions are their means', bool(np.allclose([lf['mean'] for lf in rh['leaves']], [float(np.mean(y[np.array(rh['assign']['rows'])[np.array(rh['assign']['leaf']) == i][np.array(rh['assign']['set'])[np.array(rh['assign']['leaf']) == i] == 0]])) for i in range(len(rh['leaves']))])), True)
rc = fit(y='three', x=['x1', 'g'], steps=[{'op': 'split', 'n': 3}], validation='v')
check('a categorical response: Measures of Fit, confusion matrices, ROC and lift', all(k in rc['fit'] for k in ('measures', 'confusion', 'roc', 'lift')), True)
check('... its summary is the entropy RSquare and the misclassification rate', sorted(rc['summary'][0]), sorted(['set', 'entropy_rsquare', 'misclassification', 'n', 'splits']))
check('... no probability the tree gives is 0 (the validation log-likelihood stays finite)', all(min(nd['probs']) > 0 for nd in rc['nodes']), True)

# ---- Freq against duplicated rows ----------------------------------------------------------------------------------------
dup = np.repeat(np.arange(n), fq.astype(int))
T2 = table({k: [v[i] for i in dup] for k, v in cols.items()}, types=TYPES, levels=LEVELS)
ra = fit(y='cls', x=['x1', 'g', 'o'], freq='f', steps=[{'op': 'split', 'n': 4}])
rb = fit(table=T2, y='cls', x=['x1', 'g', 'o'], steps=[{'op': 'split', 'n': 4}])
same = [(a_['label'], a_['count'], round(a_['g2'], 8)) for a_ in ra['nodes']] == [(b_['label'], b_['count'], round(b_['g2'], 8)) for b_ in rb['nodes']]
check('Freq: the same tree as the table with each row repeated Freq times', same, True)
check('... and the same LogWorths', all(math.isclose(a_['split']['logworth'], b_['split']['logworth'], rel_tol=1e-9) for a_, b_ in zip(ra['nodes'], rb['nodes']) if a_['split']), True)

# ---- the page's JSON ---------------------------------------------------------------------------------------------------------
nodes = r3['nodes']
check('nodes come parents first; each has its leaf range', all(nd['lo'] <= nd['hi'] for nd in nodes) and nodes[0]['path'] == '', True)
check('... a split node\'s range is its children\'s', all(nd['lo'] == next(c for c in nodes if c['path'] == nd['split']['children'][0])['lo'] and nd['hi'] == next(c for c in nodes if c['path'] == nd['split']['children'][1])['hi'] for nd in nodes if nd['split']), True)
check('... each has every column\'s candidate, one marked best at a leaf', all(len(nd['cands']) == 4 and (not nd['leaf'] or sum(c['best'] for c in nd['cands']) <= 1) for nd in nodes), True)
check('every row of the report is in one leaf', (len(r3['assign']['rows']), sorted(set(r3['assign']['leaf']))), (n, list(range(len(r3['leaves'])))))
check('the left child has the larger mean', all(next(c for c in nodes if c['path'] == nd['split']['children'][0])['mean'] >= next(c for c in nodes if c['path'] == nd['split']['children'][1])['mean'] for nd in nodes if nd['split']), True)
check('Difference = the left child\'s mean minus the right\'s', all(math.isclose(nd['split']['difference'], next(c for c in nodes if c['path'] == nd['split']['children'][0])['mean'] - next(c for c in nodes if c['path'] == nd['split']['children'][1])['mean']) for nd in nodes if nd['split']), True)
check('leaf labels: the conditions from the root joined by &', r3['leaves'][0]['label'].count('&') == len(r3['leaves'][0]['path']) - 1, True)

# ---- Save Columns, the profiler ------------------------------------------------------------------------------------------------
base = dict(table=T, y='ym', x=['x1m', 'x2', 'g'], steps=[{'op': 'split', 'n': 5}], rows=list(range(0, 300)))
sv = call('partition.save', **base)
Pv, tv, _ = pt._grown(T, list(range(0, 300)), pt._spec('ym', ['x1m', 'x2', 'g'], steps=[{'op': 'split', 'n': 5}]))
X_all, rws = Pv.all_rows()
check('Save Predicteds: every row of the table, the excluded ones too', sv['rows'], list(range(n)))
check('... each its leaf\'s mean', bool(np.allclose(sv['values'], tv.predict(X_all))), True)
check('... and Save Residuals the response minus it', bool(np.allclose(sv['residuals'], ym - np.array(sv['values']))), True)
lv_ = call('partition.leaves', **base)
leaf_json = fit(**{k: v for k, v in base.items() if k != 'table'})['leaves']
check('Save Leaf Numbers: the leaf of each row, numbered as the Leaf Report', (lv_['rows'][:3], lv_['numbers'][:300] == [leaf_json[i]['number'] for i in tv.leaf_index(X_all)][:300]), ([0, 1, 2], True))
check('Save Leaf Labels: its label', lv_['labels'][5] == leaf_json[lv_['numbers'][5] - 1]['label'], True)
svc = call('partition.save', table=T, y='three', x=['x1', 'g'], steps=[{'op': 'split', 'n': 3}])
check('Save Predicteds, categorical: Prob columns and the most likely level', (svc['names'], len(svc['prob'][0])), (['Prob[lo]', 'Prob[mid]', 'Prob[hi]'], 3))
pr = call('partition.profile', table=T, y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 4}], current={'x1': 1.0, 'g': 'b'}, grid=11)
Pp, tp, _ = grown('y', ['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 4}])
f0 = pr['factors'][0]
Xg = Pp.encode_settings([{'x1': v, 'x2': pr['factors'][1]['current'], 'g': 'b'} for v in np.linspace(f0['min'], f0['max'], 11)])
check('the profiler: the tree\'s prediction over a factor, the others at their current values', bool(np.allclose(pr['responses'][0]['traces'][0]['pred'], tp.predict(Xg))), True)
prc = call('partition.profile', table=T, y='cls', x=['x1', 'g'], steps=[{'op': 'split', 'n': 2}])
check('... for a categorical response a row per level, adding to 1', ([p_['name'] for p_ in prc['responses']], bool(np.allclose(np.sum([p_['traces'][0]['pred'] for p_ in prc['responses']], axis=0), 1))), (['Prob[no]', 'Prob[yes]'], True))

# ---- K Fold Crossvalidation, by hand -------------------------------------------------------------------------------------------
kf = call('partition.kfold', table=T, y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 3}], k=5, seed=11)
Pk, tk, msk = grown('y', ['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 3}], seed=11)
fold = np.random.default_rng([11, 2]).permutation(np.arange(n) % 5)
oof = np.zeros(n)
for f_ in range(5):
    tt_ = pt.Tree(tk.cols, Pk.X, Pk.target, 0, None, None, np.where(fold == f_, 1, 0), 5)
    for _ in range(3):
        tt_.split_best()
    oof[fold == f_] = tt_.fitted()[fold == f_]
check('K Fold: the folds drawn from the report\'s seed', kf['fold'], fold.tolist())
check.near('... each fold predicted by a 3-split tree grown on the others (by hand)', kf['folded']['rsquare'], 1 - np.sum((y - oof) ** 2) / np.sum((y - y.mean()) ** 2), 1e-10)
check.near('... Overall is the tree\'s own training RSquare', kf['overall']['rsquare'], fit(y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 3}])['summary'][0]['rsquare'], 1e-12)
check('... below it (the folds do not see their own rows)', kf['folded']['rsquare'] < kf['overall']['rsquare'], True)

# ---- CART: scikit-learn's trees, grown best first ---------------------------------------------------------------------------------
cr = call('partition.cart_fit', table=T, y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 5}], seed=3)
Pc_ = pv.prepare(T, 'y', ['x1', 'x2', 'g'], seed=3)
skm = DecisionTreeRegressor(max_leaf_nodes=6, min_samples_leaf=5, random_state=3).fit(Pc_.X, Pc_.target)
check('CART: six leaves for five splits, as scikit-learn grows them (max_leaf_nodes)', (len(cr['leaves']), cr['splits']), (6, 5))
check.near('... its training RSquare is scikit-learn\'s own score', cr['summary'][0]['rsquare'], skm.score(Pc_.X, Pc_.target), 1e-10)
sk_leaf_means = sorted(round(float(v), 8) for v in skm.tree_.value[skm.tree_.children_left == -1, 0, 0])
check('... and its leaves\' means scikit-learn\'s', sorted(round(lf['mean'], 8) for lf in cr['leaves']), sk_leaf_means)
orders = sorted(nd['split']['order'] for nd in cr['nodes'] if nd['split'])
check('... the splits in the order best-first growth made them', orders, list(range(5)))
cr4 = call('partition.cart_fit', table=T, y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 4}], seed=3)
check('... the tree of 4 splits is the first 4 of the tree of 5 (nested)', math.isclose(cr4['summary'][0]['rsquare'], cr['history'][4]['Training'], rel_tol=1e-10), True)
crs = call('partition.cart_fit', table=T, y='y', x=['x1'], steps=[{'op': 'here', 'node': ''}, {'op': 'split'}], seed=3)
check('... a node\'s own split is not CART\'s: noted', ('Step 1 (here) was not done' in ' '.join(crs['notes']), crs['splits']), (True, 1))
crc = call('partition.cart_fit', table=T, y='cls', x=['x1', 'g'], validation='v', steps=[{'op': 'go'}], seed=3)
check('CART Go: the number of leaves with the best validation entropy RSquare', crc['splits'] == max(crc['go']['trace'], key=lambda e: (e['Validation'], -e['splits']))['splits'], True)
cs = call('partition.cart_save', table=T, y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 5}], seed=3)
check('CART Save Predicteds: scikit-learn\'s predictions', bool(np.allclose(cs['values'], skm.predict(Pc_.X))), True)
cl = call('partition.cart_leaves', table=T, y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 5}], seed=3)
check('CART Save Leaf Numbers: one number per scikit-learn leaf', len(set(cl['numbers'])), 6)
cp = call('partition.cart.profile', table=T, y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 5}], seed=3)
check('the CART profiler', len(cp['responses'][0]['traces']), 3)
ck = call('partition.cart_kfold', table=T, y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 5}], seed=3, k=4)
check('CART K Fold: a fold each', (len(ck['folds']), ck['folded']['rsquare'] < ck['overall']['rsquare']), (4, True))

# ---- the edges -----------------------------------------------------------------------------------------------------------
Tc = table({'y': [1.0] * 30, 'x': list(range(30))})
re_ = call('partition.fit', table=Tc, y='y', x=['x'], steps=[{'op': 'split'}])
check('a constant response: nothing to split, and a note', (re_['splits'], 'no leaf can be split' in ' '.join(re_['notes'])), (0, True))
Tk = table({'y': list(rng.normal(size=30)), 'x': ['a'] * 30})
check('a single-level factor has no candidate', call('partition.fit', table=Tk, y='y', x=['x'])['nodes'][0]['cands'][0]['stat'], None)
try:
    call('partition.fit', table=T, y='y', x=['x1'], minsize=0)
    check('Minimum Size Split 0 is refused', 'no error', 'an error')
except ValueError as e:
    check('Minimum Size Split 0 is refused', 'Minimum Size Split' in str(e), True)

# ---- speed: 5000 rows, 10 columns --------------------------------------------------------------------------------------------
big = np.random.default_rng(3)
N = 5000
bc = {f'c{j}': list(big.normal(size=N)) for j in range(7)}
bc.update({'n1': list(big.choice(list('abcdefgh'), N)), 'n2': list(big.choice(list('xyz'), N)), 'n3': list(big.choice(list('pqrstu'), N))})
bc['y'] = list(np.array(bc['c0']) * 2 + (np.array(bc['n1']) == 'c') + big.normal(size=N))
bc['k'] = list(np.where(np.array(bc['y']) > 0.5, 'hi', 'lo'))
TB = table(bc, types={'n1': 'nominal', 'n2': 'nominal', 'n3': 'nominal', 'k': 'nominal'})
xs_ = [c for c in bc if c not in ('y', 'k')]
t0 = time.time()
rb = call('partition.fit', table=TB, y='y', x=xs_, steps=[{'op': 'split', 'n': 20}], portion=0.3, seed=1)
t1 = time.time()
rk = call('partition.fit', table=TB, y='k', x=xs_, steps=[{'op': 'go'}], portion=0.3, seed=1)
t2 = time.time()
check(f'5000 rows × 10 columns: 20 splits in {t1 - t0:.2f} s, Go for a categorical response in {t2 - t1:.2f} s (under 3 s natively)', (rb['splits'], t1 - t0 < 3, t2 - t1 < 3), (20, True, True))

# ---- the code under the report, run on a CSV export --------------------------------------------------------------------------------


def run_code(script, extra, tbl=cols):
    with tempfile.TemporaryDirectory() as tmp:
        pd.DataFrame(tbl).to_csv(os.path.join(tmp, 'data.csv'), index=False)
        with open(os.path.join(tmp, 'code.py'), 'w') as fh:
            fh.write(script.replace('\n\n# ----\n', '\n\n') + '\n' + extra)
        out = subprocess.run([sys.executable, 'code.py'], cwd=tmp, capture_output=True, text=True, timeout=300)
        if out.returncode:
            print(out.stderr[-3000:])
            return None, out.stdout
        last = [ln for ln in out.stdout.splitlines() if ln.startswith('JSON')]
        return json.loads(last[-1][4:]) if last else None, out.stdout


EXTRA = 'import json\nprint("JSON" + json.dumps({"labels": [nd.label for nd in tree.nodes()], "counts": [nd.count for nd in tree.nodes()], "lw": [nd.cand["logworth"] for nd in tree.nodes() if nd.children], "r2": {str(k): v for k, v in tree.rsquares(tree.fitted()).items()}, "fitted": np.asarray(tree.fitted()).tolist()}))'
for label, kw in [
        ('continuous, Informative Missing, a validation column, Go', dict(y='ym', x=['x1m', 'x2', 'gm', 'o'], validation='v', steps=[{'op': 'split', 'n': 2}, {'op': 'go'}])),
        ('categorical, weight and frequency, a validation portion', dict(y='three', x=['x1', 'g', 'o'], weight='w', freq='f', portion=0.3, seed=5, steps=[{'op': 'split', 'n': 4}])),
        ('a node\'s own splits, Informative Missing off, rows of the report', dict(y='cls', x=['x1m', 'gm', 'x2'], missing='drop', rows=list(range(20, 380)), steps=[{'op': 'specific', 'node': '', 'col': 'x2', 'cut': 4.5}, {'op': 'here', 'node': 'R'}, {'op': 'split', 'n': 2}, {'op': 'prune'}])),
        ('ordinal grouped freely, a minimum size share', dict(y='y', x=['o', 'x1'], ordinal_order=False, minsize=0.05, steps=[{'op': 'split', 'n': 3}]))]:
    res = fit(**kw)
    if 'error' in res:
        check(f'the fit runs: {label}', res['error'], None)
        continue
    got, out = run_code(res['script'], EXTRA)
    if got is None:
        check(f'the code runs: {label}', False, True)
        continue
    nodes_r = res['nodes']
    check(f'the code grows the same tree: {label}', (got['labels'], got['counts']), ([nd['label'] for nd in nodes_r], [nd['count'] for nd in nodes_r]))
    check('... with the same LogWorths', bool(np.allclose(got['lw'], [nd['split']['logworth'] for nd in nodes_r if nd['split']], rtol=1e-10)), True)
    r2s = {s_['set']: s_.get('rsquare', s_.get('entropy_rsquare')) for s_ in res['summary']}
    check('... and the report\'s RSquare of each set', all(math.isclose(got['r2'][str(k)], r2s[pv.SETS[k]], rel_tol=1e-9) for k in range(3) if pv.SETS[k] in r2s), True)
    check('... and prints the tree', 'All Rows  Count' in out, True)
kf2 = call('partition.kfold', table=T, y='three', x=['x1', 'g'], steps=[{'op': 'split', 'n': 3}], k=4, seed=9)
got, out = run_code(kf2['script'], '')
check('the K Fold code prints the folded entropy RSquare', any(ln.startswith('Folded Entropy RSquare') and math.isclose(float(ln.split()[-1]), kf2['folded']['entropy_rsquare'], rel_tol=1e-9) for ln in out.splitlines()), True)
kf3 = call('partition.kfold', table=T, y='y', x=['x1', 'g'], steps=[{'op': 'split', 'n': 3}], k=4, seed=9, weight='w')
got, out = run_code(kf3['script'], '')
check('... and the folded RSquare, with a weight', any(ln.startswith('Folded RSquare') and math.isclose(float(ln.split()[-1]), kf3['folded']['rsquare'], rel_tol=1e-9) for ln in out.splitlines()), True)
crx = call('partition.cart_fit', table=T, y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 5}], seed=3)
got, out = run_code(crx['script'], '')
check('the CART code prints scikit-learn\'s tree and its training RSquare', ('|--- ' in out and any(ln.startswith('Training RSquare') and math.isclose(float(ln.split()[-1]), crx['summary'][0]['rsquare'], rel_tol=1e-9) for ln in out.splitlines())), True)
ckx = call('partition.cart_kfold', table=T, y='y', x=['x1', 'x2', 'g'], steps=[{'op': 'split', 'n': 5}], seed=3, k=4)
got, out = run_code(ckx['script'], '')
check('the CART K Fold code prints the folded RSquare', any(ln.startswith('Folded RSquare') and math.isclose(float(ln.split()[-1]), ckx['folded']['rsquare'], rel_tol=1e-9) for ln in out.splitlines()), True)
check('the engine the code shows is the module\'s own', pt.engine_source().startswith('# ==== ENGINE') and 'class Tree:' in pt.engine_source() and 'from . import' not in pt.engine_source(), True)

# ---- the graphs' matplotlib code, run on a CSV export: every graph of the report -------------------------------------------------
from test_predictive import check_contrib_native, check_shared_native, joined, run_graph as run_graph_native, scatter_pts  # noqa: E402
from smui import data as sdata, util  # noqa: E402

GTMP = tempfile.mkdtemp(prefix='smui-partition-charts-')
BOX, TRACK = '#fcf7f2ff', '#e0d7ceff'


def clipped(s, px, cw):
    """A label as the tree's box shortens it (smui-p-partition.js clip)."""
    k = max(3, int(px // cw))
    return s[:k - 1] + '…' if len(s) > k else s


def graph_checks(label, res, tid, plot=None):
    """Every graph of a Partition report: its code run on the CSV, the figure against the report."""
    Pc = res['fit']['plots']
    plot = plot or {}
    points, prob = plot.get('points', True), plot.get('prob', True)
    a = res['assign']
    L = len(res['levels']) if res['kind'] == 'categorical' else 0
    nl = len(res['leaves'])
    idx = [[i for i in range(len(a['rows'])) if a['set'][i] == 0 and a['leaf'][i] == lf] for lf in range(nl)]
    edges = np.r_[0, np.cumsum([len(r) for r in idx])] / sum(len(r) for r in idx)
    # the partition graph
    F, err = run_graph_native(joined(Pc, 'partition'), tid, GTMP)
    check(f'{label}: the partition graph\'s code runs', err, None)
    if F:
        ax = F['axes'][0]
        check(f'{label}: ... the leaves\' edges', sorted(ln['x'][0] for ln in ax['lines'] if ln['ls'] == ':'), sorted(edges[1:-1].tolist()))
        check(f'{label}: ... the leaves numbered at their bands\' centres', (np.allclose(ax['xticks'], (edges[:-1] + edges[1:]) / 2), [t for t in ax['xticklabels'] if t]), (True, [str(k + 1) for k in range(nl)]))
        if not L:
            want = [(edges[lf] + (k + 0.5) / len(r) * (edges[lf + 1] - edges[lf]), a['y'][i]) for lf, r in enumerate(idx) for k, i in enumerate(r)]
            got = scatter_pts(ax)
            check(f'{label}: ... the training rows in their leaves\' bands, in order', len(got) == len(want) and np.allclose(got, want, rtol=1e-12, atol=1e-12), True)
            means = sorted((round(ln['x'][0], 12), round(ln['y'][0], 9)) for ln in ax['lines'] if ln['ls'] == '-')
            check(f'{label}: ... each leaf\'s mean across its band', means, sorted((round(edges[lf], 12), round(res['leaves'][lf]['mean'], 9)) for lf in range(nl)))
        else:
            rates = np.array([lf['rates'] for lf in res['leaves']])
            cum = np.c_[np.zeros(nl), np.cumsum(rates, axis=1)]
            want = sorted((round(edges[lf], 9), round(cum[lf, j], 9), round(rates[lf, j], 9)) for j in range(L) for lf in range(nl))
            got = sorted((round(b['x'], 9), round(b['y'], 9), round(b['h'], 9)) for b in ax['bars'])
            check(f'{label}: ... each leaf\'s rates stacked in its band', got, want)
            inside = 0
            for x_, y_ in scatter_pts(ax):
                lf = int(np.searchsorted(edges, x_) - 1)
                inside += any(cum[lf, j] + 0.1 * rates[lf, j] - 1e-12 <= y_ <= cum[lf, j] + 0.9 * rates[lf, j] + 1e-12 for j in range(L)) and edges[lf] < x_ < edges[lf + 1]
            want_n = sum(len(r) for r in idx) if points else 0
            check(f'{label}: ... every training row inside its leaf, in its level\'s part{"" if points else " (Show Points off: none)"}', (inside, len(scatter_pts(ax))), (want_n, want_n))
            check(f'{label}: ... the levels in the legend', F['legend'], res['levels'])
    # the tree and the small tree view
    for key, small in (('tree', False), ('small', True)):
        F, err = run_graph_native(joined(Pc, key), tid, GTMP)
        check(f'{label}: the {"small tree" if small else "tree"}\'s code runs', err, None)
        if not F:
            continue
        ax = F['axes'][0]
        boxes = [b for b in ax['bars'] if b['fc'] == BOX]
        texts = [t['s'] for t in ax['texts']]
        check(f'{label}: ... a box per node, two lines per split', (len(boxes), len(ax['lines'])), (len(res['nodes']), 2 * res['splits']))
        bw = 118 if small else (184 if not L else None)
        if bw:
            want = sorted(clipped(nd['label'], bw - (8 if small else 24), 6.2 if small else 7.1) for nd in res['nodes'])
            check(f'{label}: ... every node\'s condition', sorted(t for t in texts if t in want), want)
        if not small:
            if L:
                check(f'{label}: ... every node\'s rates{" and probabilities" if prob else " (Show Split Prob off)"}', sorted(t for t in texts if len(t) == 6 and t[1] == '.'),
                      sorted([f'{v:.4f}' for nd in res['nodes'] for v in nd['rates'] + (nd['probs'] if prob else [])]))
            else:
                check(f'{label}: ... every node\'s count', sorted(t for t in texts if t.isdigit()), sorted(str(int(nd['count'])) for nd in res['nodes']))
    # the split history
    if 'history' in res and res['history']:
        F, err = run_graph_native(joined(Pc, 'history'), tid, GTMP)
        check(f'{label}: the split history\'s code runs', err, None)
        if F:
            ax = F['axes'][0]
            for s in ('Training', 'Validation', 'Test'):
                if s in res['history'][0]:
                    ln = next((q for q in ax['lines'] if q['label'] == s), None)
                    check(f'{label}: ... the {s.lower()} RSquare after each split', ln is not None and np.allclose(ln['y'], [h[s] for h in res['history']], rtol=1e-12, atol=1e-12) and ln['x'] == list(range(len(res['history']))), True)
            dotted = [q for q in ax['lines'] if q['ls'] == ':']
            if res['go']:
                g = res['go']
                after = [e for e in g['trace'] if e['splits'] > g['best']]
                check(f'{label}: ... what Go looked at past the best, dotted, and the best marked', (len(dotted), any(q['ls'] == '--' and q['x'][:2] == [g['best'], g['best']] for q in ax['lines']),
                                                                                                         all(q['x'] == [g['best']] + [e['splits'] for e in after] for q in dotted)), (len([s for s in res['history'][0] if s != 'splits']), True, True))
            else:
                check(f'{label}: ... no Go: nothing dotted', dotted, [])
            check(f'{label}: ... the titles', (ax['xlabel'], ax['ylabel'], ax['title']), ('Number of Splits', 'Entropy RSquare' if L else 'RSquare', 'Split history'))
    # the leaf report's bars
    F, err = run_graph_native(joined(Pc, 'leaves'), tid, GTMP)
    check(f'{label}: the leaf report\'s code runs', err, None)
    if F:
        ax = F['axes'][0]
        check(f'{label}: ... a bar per leaf, the first at the top', ([t for t in ax['yticklabels'] if t], ax['yinverted']), ([str(k + 1) for k in range(nl)], True))
        if L:
            probs = np.array([lf['probs'] for lf in res['leaves']])
            want = [(round(probs[lf, :j].sum(), 9), round(probs[lf, j], 9)) for j in range(L) for lf in range(nl)]
            check(f'{label}: ... each leaf\'s probabilities stacked', [(round(b['x'], 9), round(b['w'], 9)) for b in ax['bars']], want)
        else:
            check(f'{label}: ... each leaf\'s mean', np.allclose([b['w'] for b in ax['bars']], [lf['mean'] for lf in res['leaves']], rtol=1e-12), True)
    check_contrib_native(check, label, res['contributions'], Pc['head_code'], tid, GTMP)
    check_shared_native(check, label, res['fit'], tid, GTMP)


# a date factor (text in the CSV) and a level named None, beside the table's own columns
days = (np.datetime64('2023-06-01') + rng.integers(0, 500, n).astype('timedelta64[D]')).astype('datetime64[ms]').astype(np.int64).astype(float)
TD = table({**cols, 'day': list(days), 'net': list(np.where(x2 < 3, 'None', np.where(x2 < 7, 'DSL', 'Fiber')))}, types={**TYPES, 'net': 'nominal'}, levels={**LEVELS, 'net': ['None', 'DSL', 'Fiber']})
sdata.TABLES[TD]['meta']['day']['format'] = {'kind': 'date'}
check('the table with a date column: the dispatch dates the graphs\' code', 'date' in [m.get('format', {}) and m['format'].get('kind') for m in sdata.TABLES[TD]['meta'].values() if m.get('format')], True)
for label, kw, cart in [
        ('graphs: categorical, a validation column, Go', dict(y='three', x=['x1', 'g', 'o', 'net'], validation='v', steps=[{'op': 'split', 'n': 2}, {'op': 'go'}]), False),
        ('graphs: two levels, weight and frequency, the Show Split options off', dict(y='cls', x=['x1m', 'gm', 'x2'], weight='w', freq='f', steps=[{'op': 'split', 'n': 3}], plot={'points': False, 'stats': False, 'bar': False, 'prob': False, 'count': False}), False),
        ('graphs: continuous, a validation portion, a date factor', dict(y='y', x=['x1', 'day', 'g', 'net'], portion=0.3, seed=5, steps=[{'op': 'split', 'n': 4}]), False),
        ('graphs: continuous, Informative Missing off, rows left out', dict(y='ym', x=['x1m', 'gm'], missing='drop', rows=list(range(15, 390)), steps=[{'op': 'split', 'n': 3}]), False),
        ('graphs: CART, categorical, a validation column, Go', dict(y='three', x=['x1', 'g', 'net'], validation='v', seed=4, steps=[{'op': 'split', 'n': 2}, {'op': 'go'}]), True),
        ('graphs: CART, continuous, weight, rows left out', dict(y='y', x=['x1m', 'day', 'gm'], weight='w', seed=2, rows=list(range(0, 380)), steps=[{'op': 'split', 'n': 3}, {'op': 'prune'}]), True)]:
    res = call('partition.cart_fit' if cart else 'partition.fit', table=TD, table_name='data', **kw)
    if 'error' in res:
        check(f'{label}: fits', res['error'], None)
        continue
    if 'day' in kw['x']:
        check(f'{label}: the head turns the date text back into the page\'s number', 'df["day"] = (pd.to_datetime(df["day"])' in res['fit']['plots']['head_code'], True)
    if 'rows' in kw:
        check(f'{label}: the head leaves out the rows the report leaves out', f'df = df.drop(index={sorted(set(range(n)) - set(kw["rows"]))})   # the rows the report leaves out' in res['fit']['plots']['head_code'], True)
    check(f'{label}: the go trace shown', res['go'] is not None, kw['steps'][-1]['op'] == 'go')
    graph_checks(label, res, TD, kw.get('plot'))

sys.exit(check.done())
