#!/usr/bin/env python3
"""Analyze > Consumer Research > Uplift (resources/py/smui/uplift.py), through
registry.dispatch as the page calls it.

The split statistics are checked against statsmodels fitted directly: the
interaction F against the squared t of the interaction in OLS and WLS of the
response on the split, the treatment and their interaction; the
likelihood-ratio chi-square against two logistic fits (GLM binomial, with
frequency weights) and, with an empty cell, against the Poisson log-linear
model with the three two-way margins. The best split of every kind of column
at the root against a brute-force search written here (every cut, every
grouping of levels, both sides for the missing rows); the LogWorth of a cut
given against the unadjusted p-value, and by Monte Carlo under no
interaction (the adjusted p-value below 0.05 in about 5% of samples or
fewer, the best cut's unadjusted one far more often); the nodes' group
means, counts, uplifts and t ratios against pandas and scipy's ttest_ind;
Freq against duplicated rows; the summary (RSquare, RMSE, AICc) against OLS
on the leaf-by-group cells; Go against the validation RSquare worked out
split by split; the leaf rules; the Qini curve by brute force; Save
Difference, Save Predicteds and both formulas (run in the page's formula
engine, in node) on every row; the treatment's and the response's levels;
and the Python the report shows, and every graph's matplotlib code, run on a
CSV export of the table.

    python3 resources/tests/smui/test_uplift.py
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
check('uplift.py imports', 'uplift' in FAILED, False)
from smui import partition as pt, predictive as pv, uplift as up  # noqa: E402
import statsmodels.api as sm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.abspath(os.path.join(HERE, '..', '..', 'js'))

rng = np.random.default_rng(20260929)
n = 900
x1 = rng.normal(0, 1, n).round(2)                            # ties
x2 = rng.uniform(0, 10, n).round(1)
x2m = x2.copy()
x2m[rng.choice(n, 60, replace=False)] = np.nan
g = rng.choice(list('abcde'), n, p=[0.3, 0.25, 0.2, 0.15, 0.1])
o = rng.choice(['o1', 'o2', 'o3', 'o4'], n)
trt_txt = rng.choice(['Treated', 'Control'], n)
T1 = trt_txt == 'Treated'
# the treatment helps where x1 > 0.3 and g in (b, d); a main effect of x2
eff = np.where(x1 > 0.3, 1.5, 0.0) + np.where(np.isin(g, ['b', 'd']), 1.0, -0.3)
yc = 5 + 0.4 * x2 + T1 * eff + rng.normal(0, 1, n)
pb = 1 / (1 + np.exp(-(-1.0 + 0.1 * x2 + T1 * (1.2 * (x1 > 0.3) - 0.4))))
yb = np.where(rng.uniform(size=n) < pb, 'yes', 'no')
y3 = np.where(yc < 6, 'lo', np.where(yc < 8, 'mid', 'hi'))
three = rng.choice(['A', 'B', 'C'], n)                        # a treatment of three levels
w = rng.uniform(0.5, 2.0, n).round(3)
fq = rng.integers(1, 4, n).astype(float)
vnum = rng.choice([0.0, 1.0, 2.0], n, p=[0.6, 0.25, 0.15])
cols = {'yc': list(yc), 'yb': list(yb), 'y3': list(y3), 'x1': list(x1), 'x2': list(x2), 'x2m': [None if np.isnan(v) else v for v in x2m],
        'g': list(g), 'o': list(o), 'trt': list(trt_txt), 'three': list(three), 'w': list(w), 'f': list(fq), 'v': list(vnum)}
TYPES = {'g': 'nominal', 'o': 'ordinal', 'yb': 'nominal', 'y3': 'ordinal', 'trt': 'nominal', 'three': 'nominal'}
LEVELS = {'g': list('abcde'), 'o': ['o1', 'o2', 'o3', 'o4'], 'yb': ['yes', 'no'], 'y3': ['lo', 'mid', 'hi'], 'trt': ['Treated', 'Control'], 'three': ['A', 'B', 'C']}
T = table(cols, types=TYPES, levels=LEVELS)


def fit(**kw):
    kw.setdefault('table', T)
    kw.setdefault('treatment', 'trt')
    return call('uplift.fit', **kw)


def grown(**kw):
    """The engine's tree for these settings, as the report builds it."""
    tid = kw.pop('table', T)
    kw.setdefault('treatment', 'trt')
    return up._grown(tid, kw.pop('rows', None), up._spec(**kw))


# ---- the interaction statistics against statsmodels --------------------------------------------------------------
def cells_of(y, t, s, wt):
    """The engine's aggregates of each side: [W0, W1, S0, S1, Q0, Q1] (continuous) about the mean of y."""
    m = np.average(y, weights=wt)
    yc_ = y - m
    out = []
    for side in (0, 1):
        k = s == side
        c, tt = wt * (1 - t) * k, wt * t * k
        out.append(np.array([c.sum(), tt.sum(), (c * yc_).sum(), (tt * yc_).sum(), (c * yc_ ** 2).sum(), (tt * yc_ ** 2).sum()]))
    return out


def ols_interaction_F(y, t, s, wt=None, freq=None):
    X = np.column_stack([np.ones(len(y)), s, t, s * t])
    if wt is None:
        r = sm.OLS(y, X).fit()
    else:
        r = sm.WLS(y, X, weights=wt).fit()
    return float(r.tvalues[3] ** 2), float(r.df_resid)


for trial in range(6):
    m = rng.uniform(size=n) < 0.2 + 0.1 * trial
    s = (x1 > (trial - 3) * 0.3).astype(float)
    t = T1.astype(float)
    wt = None if trial % 2 == 0 else w
    AL, AR = cells_of(yc, t, s, np.ones(n) if wt is None else wt)
    F = up.interaction_f(AL[None, :], AR[None, :], n)[0]
    Fs, dfr = ols_interaction_F(yc, t, s, wt)
    check.near(f'interaction F = the squared t of the interaction in {"WLS" if wt is not None else "OLS"} (trial {trial + 1})', float(F), Fs, 1e-9)
check('... the error degrees of freedom are n - 4', dfr, float(n - 4))


def g2_counts(z, t, s, wt):
    n8 = np.zeros(8)
    for side in (0, 1):
        for gg in (0, 1):
            for zz in (0, 1):
                n8[4 * side + 2 * gg + zz] = np.sum(wt * ((s == side) & (t == gg) & (z == zz)))
    return n8


def glm_lr(z, t, s, wt):
    """2 (llf with the interaction - llf without): statsmodels' binomial GLM with frequency weights."""
    X1 = np.column_stack([np.ones(len(z)), s, t, s * t])
    X0 = X1[:, :3]
    f1 = sm.GLM(z, X1, family=sm.families.Binomial(), freq_weights=wt).fit()
    f0 = sm.GLM(z, X0, family=sm.families.Binomial(), freq_weights=wt).fit()
    return 2 * (f1.llf - f0.llf)


zb = (yb == 'yes').astype(float)
for trial in range(5):
    s = (x2 > 2 + trial).astype(float)
    t = T1.astype(float)
    wt = np.ones(n) if trial < 3 else w
    g2 = up.interaction_g2(g2_counts(zb, t, s, wt)[None, :])[0]
    check.near(f'interaction chi-square = the likelihood ratio of two binomial GLMs{" (weights as frequencies)" if trial >= 3 else ""} (trial {trial + 1})', float(g2), glm_lr(zb, t, s, wt), 1e-7)
# an empty cell: the fit without the interaction is the log-linear model with the three two-way margins
cnt8 = np.array([30, 12, 25, 0, 18, 22, 9, 14], dtype=float)
g2 = up.interaction_g2(cnt8[None, :])[0]
S_, G_, Z_ = [np.array([(k >> b) & 1 for k in range(8)]) for b in (2, 1, 0)]
D = pd.DataFrame({'n': cnt8, 's': S_, 'g': G_, 'z': Z_})
pois = sm.GLM(D['n'], sm.add_constant(pd.DataFrame({'s': S_, 'g': G_, 'z': Z_, 'sg': S_ * G_, 'sz': S_ * Z_, 'gz': G_ * Z_}).astype(float)), family=sm.families.Poisson()).fit()
mu = pois.fittedvalues.to_numpy()
check.near('with an empty cell: 2 sum n log(n/m), m the Poisson log-linear fit of the two-way margins', float(g2), float(2 * np.sum(np.where(cnt8 > 0, cnt8 * np.log(cnt8 / mu), 0.0))), 1e-7)
check('a table whose two-way margins leave it no freedom has no interaction', float(up.interaction_g2(np.array([[5, 3, 4, 6, 0, 7, 0, 2.0]]))[0]), 0.0)


# ---- the root's best split of each column, by brute force ------------------------------------------------------------
def brute_ordered(v, y, t, cnt, minsize, binary, wt=None):
    """Every cut of an ordered column (values v, NaN missing: the missing rows on either side): the best statistic."""
    wt = np.ones(len(y)) if wt is None else wt
    ok = ~np.isnan(v)
    vals = np.unique(v[ok])
    best = (-1.0, None)
    for k in range(1, len(vals) + 1):
        for miss_side in ((0, 1) if (~ok).any() else (None,)):
            left = ok & (v < (vals[k] if k < len(vals) else np.inf))
            if miss_side == 0:
                left = left | ~ok
            if k == len(vals) and miss_side != 1:
                continue
            s = (~left).astype(float)
            if cnt[left].sum() < minsize or cnt[~left].sum() < minsize:
                continue
            if min(wt[left & (t == 1)].sum(), wt[left & (t == 0)].sum(), wt[~left & (t == 1)].sum(), wt[~left & (t == 0)].sum()) <= 0:
                continue
            if binary:
                st = up.interaction_g2(g2_counts(y, t, s, wt * cnt)[None, :])[0]
            else:
                AL, AR = cells_of(y, t, s, wt * cnt)
                st = up.interaction_f(AL[None, :], AR[None, :], cnt.sum())[0]
            if st > best[0]:
                best = (float(st), (float(vals[k]) if k < len(vals) else math.inf, miss_side))
    return best


tr0 = grown(y='yc', x=['x1'])[2]
cand = tr0.root.candidates()[0]
bb = brute_ordered(x1, yc, T1.astype(int), np.ones(n), tr0.minsize, False)
check.near('continuous response, continuous X: the best cut\'s F is the brute force\'s', cand['stat'], bb[0], 1e-9)
check('... and the cut is the same (between the same two values)', float(cand['rule'].cut) > np.max(x1[x1 < bb[1][0]]) and float(cand['rule'].cut) <= bb[1][0], True)
check('... JMP\'s default Minimum Size Split: 25 (the rows over 2000 are fewer)', tr0.minsize, 25.0)
trm = grown(y='yc', x=['x2m'], minsize=10)[2]
cm = trm.root.candidates()[0]
bm = brute_ordered(x2m, yc, T1.astype(int), np.ones(n), 10, False)
check.near('a continuous X with missing values: the best cut, the missing rows on the better side', cm['stat'], bm[0], 1e-9)
check('... the side of the missing rows is the brute force\'s', cm['rule'].miss, bm[1][1])
trb = grown(y='yb', x=['x2'], minsize=10)[2]
cb_ = trb.root.candidates()[0]
bbb = brute_ordered(x2, zb, T1.astype(int), np.ones(n), 10, True)
check.near('a categorical response: the best cut\'s likelihood-ratio chi-square is the brute force\'s', cb_['stat'], bbb[0], 1e-8)

# a nominal X: every grouping of its five levels
trg = grown(y='yc', x=['g'], minsize=10)[2]
cg = trg.root.candidates()[0]
best = (-1.0, None)
for mask in range(1, 2 ** 4):
    grp = {'a'} | {lv for b, lv in enumerate('bcde') if (mask >> b) & 1}
    grp = set('abcde') - grp if len(grp) == 5 else grp
    if len(grp) == 5:
        continue
    left = np.isin(g, sorted(grp))
    if left.sum() < 10 or (~left).sum() < 10:
        continue
    F, _ = ols_interaction_F(yc, T1.astype(float), (~left).astype(float))
    if F > best[0]:
        best = (F, grp)
check.near('a nominal X: the best grouping of its levels is the brute force\'s (every grouping), by OLS', cg['stat'], best[0], 1e-8)
low = {pt.Col.level(trg.cols[0], q) for q in cg['rule'].low}
check('... the same grouping', low in (best[1], set('abcde') - best[1]), True)
check('... its LogWorth is adjusted by Bonferroni over the 15 groupings', math.isclose(cg['lnM'], math.log(15), rel_tol=1e-12), True)
# an ordinal X: cuts between neighbouring levels only
tro = grown(y='yc', x=['o'], minsize=10)[2]
co = tro.root.candidates()[0]
codes = pd.Categorical(o, categories=['o1', 'o2', 'o3', 'o4']).codes
bo = max(ols_interaction_F(yc, T1.astype(float), (codes >= k).astype(float))[0] for k in (1, 2, 3))
check.near('an ordinal X: the best cut between neighbouring levels', co['stat'], bo, 1e-8)
check('... a run of levels on each side', co['rule'].kind, 'cut')

# ---- the LogWorth: a cut given is not adjusted; the adjustment under no interaction -----------------------------
t_sp = grown(y='yc', x=['x1'], steps=[{'op': 'specific', 'col': 'x1', 'cut': 0.3}])[2]
c_sp = t_sp.root.cand
F_sp, dfr = ols_interaction_F(yc, T1.astype(float), (x1 >= 0.3).astype(float))
check.near('Split Specific at a cut: its F is OLS\'s', c_sp['stat'], F_sp, 1e-9)
check.near('... and its LogWorth -log10 p of F(1, n - 4), unadjusted', c_sp['logworth'], -math.log10(stats.f.sf(F_sp, 1, n - 4)), 1e-9)
check('the best cut\'s LogWorth is below its unadjusted one (the adjustment for the cuts)', cand['logworth'] < -math.log10(stats.f.sf(cand['stat'], 1, n - 4)), True)
mc_rng = np.random.default_rng(7)
adj = raw = 0
N_MC = 150
for i in range(N_MC):
    nn = 400
    xx = mc_rng.normal(0, 1, nn)
    tt = mc_rng.integers(0, 2, nn)
    yy = 1 + 0.8 * xx + 0.5 * tt + mc_rng.normal(0, 1, nn)     # main effects, no interaction
    tid = table({'y': list(yy), 'x': list(xx), 't': [['c', 'd'][k] for k in tt]}, types={'t': 'nominal'}, levels={'t': ['d', 'c']})
    tree = grown(table=tid, y='y', treatment='t', x=['x'], minsize=10)[2]
    c = tree.root.candidates()[0]
    adj += 10 ** -c['logworth'] < 0.05
    raw += stats.f.sf(c['stat'], 1, nn - 4) < 0.05
check(f'no interaction: the adjusted p-value is below 0.05 in at most about 5% of {N_MC} samples ({adj})', adj <= 0.09 * N_MC, True)
check(f'... the best cut\'s unadjusted p-value far more often ({raw})', raw >= 3 * max(adj, 1) and raw >= 0.2 * N_MC, True)


# ---- the nodes: each group's mean, count, the uplift and its t ratio ---------------------------------------------------
res = fit(y='yc', x=['x1', 'g', 'x2'], steps=[{'op': 'split', 'n': 4}])
check('the report fits', 'error' not in res, True)
a = res['assign']
rows_ = np.array(a['rows'])
leaf = np.array(a['leaf'])
ok_all = True
for nd in res['nodes']:
    m = np.isin(np.arange(n), rows_[(leaf >= nd['lo']) & (leaf <= nd['hi'])])
    for gg, sel in ((1, T1), (0, ~T1)):
        yy = yc[m & sel]
        ok_all &= math.isclose(nd['means'][gg], yy.mean(), rel_tol=1e-12) and nd['counts'][gg] == len(yy)
    tt = stats.ttest_ind(yc[m & T1], yc[m & ~T1], equal_var=True)
    ok_all &= math.isclose(nd['diff'], yc[m & T1].mean() - yc[m & ~T1].mean(), rel_tol=1e-10, abs_tol=1e-12) and math.isclose(nd['t'], tt.statistic, rel_tol=1e-9)
check('every node: each group\'s mean and count (pandas), the uplift, and its t ratio (scipy\'s pooled ttest_ind)', ok_all, True)
check('each split\'s side with the larger uplift is on the left', all(res['nodes'][[q['path'] for q in res['nodes']].index(nd['path'] + 'L')]['diff'] >= res['nodes'][[q['path'] for q in res['nodes']].index(nd['path'] + 'R')]['diff'] for nd in res['nodes'] if nd['split']), True)
by = {nd['path']: nd for nd in res['nodes']}
check('the first split is on the interaction\'s column: x1 or g', by['']['split']['column'] in ('x1', 'g'), True)
gam_ok = all(nd['split']['gamma'] is not None and math.isclose(nd['split']['gamma'], by[nd['path'] + 'L']['diff'] - by[nd['path'] + 'R']['diff'], rel_tol=1e-9) for nd in res['nodes'] if nd['split'])
check('Gamma (a continuous response) is the left side\'s uplift less the right side\'s', gam_ok, True)
rb = fit(y='yb', x=['x1', 'x2'], steps=[{'op': 'split'}])
nd0, L_, R_ = rb['nodes'][0], rb['nodes'][1], rb['nodes'][2]
lor = lambda d: math.log(d['means'][1] / (1 - d['means'][1])) - math.log(d['means'][0] / (1 - d['means'][0]))
check.near('Gamma (a categorical response) is the left side\'s log odds ratio of the treatment less the right side\'s', nd0['split']['gamma'], lor(L_) - lor(R_), 1e-9)
check('... the rates are of the first level (yes): the level of interest', rb['interest'] == 'yes' and math.isclose(nd0['means'][1], float(np.mean(zb[T1])), rel_tol=1e-12), True)

# ---- Freq is repeated rows ------------------------------------------------------------------------------------------------
rep_idx = np.repeat(np.arange(n), fq.astype(int))
TD = table({k: [v[i] for i in rep_idx] for k, v in cols.items()}, types=TYPES, levels=LEVELS)
rf = fit(y='yc', x=['x1', 'g'], freq='f', steps=[{'op': 'split', 'n': 3}], minsize=30)
rd = fit(table=TD, y='yc', x=['x1', 'g'], steps=[{'op': 'split', 'n': 3}], minsize=30)
same = [(q['label'], round(q['diff'], 10), q['counts']) for q in rf['nodes']] == [(q['label'], round(q['diff'], 10), q['counts']) for q in rd['nodes']]
check('Freq counts a row that many times: the same tree as the rows repeated', same, True)
check.near('... the same LogWorth of the first split', rf['nodes'][0]['split']['logworth'], rd['nodes'][0]['split']['logworth'], 1e-9)

# ---- the summary: the regression model the tree is ------------------------------------------------------------------
rs = fit(y='yc', x=['x1', 'g'], validation='v', steps=[{'op': 'split', 'n': 3}])
a = rs['assign']
sets = np.array(a['set'])
cell = np.array(a['leaf']) * 2 + np.array(a['trt'])
yy = np.array(a['y'])
trm = sets == 0
Xd = pd.get_dummies(pd.Series(cell[trm]).astype('category')).to_numpy(float)
ols = sm.OLS(yy[trm], Xd).fit()
S0 = rs['summary'][0]
check.near('summary: the training RSquare is OLS\'s on the leaf-by-group cells', S0['rsquare'], ols.rsquared, 1e-10)
check.near('... RMSE its root mean squared error over the error degrees of freedom', S0['rmse'], math.sqrt(ols.mse_resid), 1e-10)
k_ = Xd.shape[1] + 1
check.near('... AICc -2 log L + 2k + 2k(k+1)/(n-k-1), k the cell means and the variance', S0['aicc'], -2 * ols.llf + 2 * k_ + 2 * k_ * (k_ + 1) / (trm.sum() - k_ - 1), 1e-10)
check('... the Number of Splits', S0['splits'], 3)
cm_ = {c: yy[trm][cell[trm] == c].mean() for c in np.unique(cell[trm])}
vm = sets == 1
pred_v = np.array([cm_[c] for c in cell[vm]])
S1 = rs['summary'][1]
check.near('the validation RSquare: the training cells\' means as predictions, about the validation rows\' own mean', S1['rsquare'], 1 - np.sum((yy[vm] - pred_v) ** 2) / np.sum((yy[vm] - yy[vm].mean()) ** 2), 1e-10)
check.near('... and its RMSE the root mean squared error', S1['rmse'], math.sqrt(np.mean((yy[vm] - pred_v) ** 2)), 1e-10)

# ---- Go: the validation RSquare after each split, the best kept --------------------------------------------------------
rg = fit(y='yc', x=['x1', 'g', 'x2'], validation='v', steps=[{'op': 'go'}])
tr_go = grown(y='yc', x=['x1', 'g', 'x2'], validation='v')[2]
valid = tr_go.sets == 1
r2s = [tr_go.rsquare(tr_go.fitted(), valid)]
while True:
    nd_ = tr_go.split_best()
    if nd_ is None or len(r2s) > 60:
        break
    r2s.append(tr_go.rsquare(tr_go.fitted(), valid))
best_k = int(np.argmax(r2s))
check('Go keeps the tree whose validation RSquare is the best of the splits looked at', rg['splits'], best_k)
check('... its trace is the validation RSquare after each split', np.allclose([e['Validation'] for e in rg['go']['trace']], r2s[:len(rg['go']['trace'])], rtol=1e-12), True)
check('... it looked 10 splits past the best', len(rg['go']['trace']) - 1 - rg['go']['best'] == 10 or len(rg['go']['trace']) == len(r2s), True)
check('the split history has the AICc of each tree it went through', all('aicc' in h for h in rg['history']) and len(rg['history']) == rg['splits'] + 1, True)
check('Go without validation rows is not done, and says why', any('Go needs validation rows' in t for t in fit(y='yc', x=['x1'], steps=[{'op': 'go'}])['notes']), True)

# ---- the leaves' rules, the Qini curve ---------------------------------------------------------------------------------
rr = fit(y='yc', x=['x1', 'g'], minsize=10, steps=[{'op': 'specific', 'col': 'x1', 'cut': 0.0}, {'op': 'specific', 'node': 'L', 'col': 'x1', 'cut': 1.0},
                                                   {'op': 'specific', 'node': 'LL', 'col': 'g'}, {'op': 'specific', 'node': 'LLL', 'col': 'g'}])
rules = {lf['path']: lf['rule'] for lf in rr['leaves']}
labels_ = {lf['path']: lf['label'] for lf in rr['leaves']}
xl = {nd['path']: nd['label'] for nd in rr['nodes']}
check('a leaf\'s rule merges the cuts on one column into a range', any(r.startswith('0<=x1<1') or r.startswith('x1>=1') for r in rules.values()), True)
first_x1 = [p for p in rules if p.startswith('LL') and len(p) == 2]
lab = rr['nodes'][[q['path'] for q in rr['nodes']].index('L')]['label']
check('... and its conditions on one categorical column as the levels they share', all(r.count('g(') <= 1 for r in rules.values()) and any('g(' in r for r in rules.values()), True)
check('... each column once, where the label has it twice', all(labels_[p].count('x1') >= rules[p].count('x1') for p in rules), True)
for q in rr['qini']:
    k = pv.SETS.index(q['set'])
    a = rr['assign']
    u = np.array([rr['leaves'][l]['diff'] for l in a['leaf']])
    m = np.array(a['set']) == k
    order = sorted(set(u[m].tolist()), reverse=True)
    xs, qs = [0.0], [0.0]
    for v in order:
        tk = m & (u >= v)
        yy_, tt_ = np.array(a['y'])[tk], np.array(a['trt'])[tk]
        nt, nc = (tt_ == 1).sum(), (tt_ == 0).sum()
        xs.append(tk.sum() / m.sum())
        qs.append((yy_[tt_ == 1].sum() - yy_[tt_ == 0].sum() * nt / nc) / m.sum() if nc else 0.0)
    area = np.trapezoid(qs, xs) - qs[-1] / 2
    check(f'the Qini curve of the {q["set"].lower()} rows, by sorting the rows (and its coefficient)', np.allclose(q['x'], xs) and np.allclose(q['q'], qs) and math.isclose(q['coef'], area, rel_tol=1e-9, abs_tol=1e-12), True)

# ---- Save Difference, Save Predicteds, and the formulas in the page's own formula engine --------------------------------
NODE = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const sandbox = { console }; sandbox.self = sandbox; vm.createContext(sandbox);
for (const f of ['smui-util.js', 'smui-table.js', 'smui-formula.js']) vm.runInContext(fs.readFileSync(path.join(process.argv[1], f), 'utf8'), sandbox, { filename: f });
const SM = sandbox.SM;
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const t = new SM.Table({ name: 'data', columns: job.columns.map((c) => ({ ...c, values: c.values.map((v) => (v == null ? (c.dataType === 'numeric' ? NaN : '') : v)) })) });
const out = job.exprs.map((e) => { try { return Array.from(SM.formula.evaluate(t, e), (x) => (typeof x === 'number' && !Number.isFinite(x) ? null : x)); } catch (err) { return { error: String(err.message || err) }; } });
process.stdout.write(JSON.stringify(out));
"""


def eval_formulas(columns, exprs):
    """Each formula's value on every row of a table of these columns ({name: values}; text or numbers, None missing),
    in smui-formula.js run by node, as the page computes a formula column."""
    spec = []
    for name, vals in columns.items():
        char = any(isinstance(v, str) for v in vals)
        spec.append({'name': name, 'dataType': 'character' if char else 'numeric',
                     'values': [None if v is None or (isinstance(v, float) and math.isnan(v)) else v for v in vals]})
    with tempfile.TemporaryDirectory() as tmp:
        jf = os.path.join(tmp, 'job.json')
        with open(jf, 'w') as fh:
            json.dump({'columns': spec, 'exprs': exprs}, fh)
        out = subprocess.run(['node', '-e', NODE, JS, jf], capture_output=True, text=True, timeout=120)
    if out.returncode:
        return [{'error': out.stderr[-400:]}] * len(exprs)
    return json.loads(out.stdout)


def same_values(got, rows, want, tol=1e-12):
    """A formula's values at the rows equal want; missing (None) everywhere else."""
    if isinstance(got, dict):
        return got
    got = list(got)
    at = dict(zip(rows, want))
    for i, v in enumerate(got):
        w_ = at.get(i)
        if w_ is None:
            if not (v is None or v == ''):
                return f'row {i}: {v!r}, expected missing'
        elif isinstance(w_, str):
            if v != w_:
                return f'row {i}: {v!r}, expected {w_!r}'
        elif v is None or not math.isclose(v, w_, rel_tol=tol, abs_tol=1e-14):
            return f'row {i}: {v!r}, expected {w_!r}'
    return True


# rows the report leaves out still get a difference; a missing treatment gets no prediction; missing factors
cols_f = dict(cols)
tv_f = list(trt_txt)
for i in (3, 17, 40):
    tv_f[i] = None
cols_f['trt'] = tv_f
yc_f = list(yc)
yc_f[5] = None
cols_f['yc'] = yc_f
TF = table(cols_f, types=TYPES, levels=LEVELS)
for label, kw in [('informative missing, a continuous response', dict(y='yc', x=['x1', 'x2m', 'g', 'o'], steps=[{'op': 'split', 'n': 5}], minsize=15)),
                  ('Informative Missing off', dict(y='yc', x=['x2m', 'g', 'o'], missing='drop', steps=[{'op': 'split', 'n': 4}], minsize=15)),
                  ('a categorical response, rows left out', dict(y='yb', x=['x1', 'x2m', 'g'], rows=list(range(30, n)), steps=[{'op': 'split', 'n': 4}], minsize=15)),
                  ('a treatment of three levels (A against B and C)', dict(y='yc', treatment='three', x=['x1', 'g'], steps=[{'op': 'split', 'n': 3}], minsize=15))]:
    kw = dict(kw, table=TF)
    kw.setdefault('treatment', 'trt')
    d = call('uplift.save', what='difference', **kw)
    pr = call('uplift.save', what='predicteds', **kw)
    fo = call('uplift.formula', **kw)
    tree = up._grown(TF, kw.get('rows'), up._spec(**{k: v for k, v in kw.items() if k != 'table'}))[2]
    rows_all = set(range(n))
    need = ['x1', 'x2m', 'g', 'o', 'x2'] if kw.get('missing') == 'drop' else []
    want_rows = sorted(r for r in rows_all if not any(cols_f[c][r] is None or (isinstance(cols_f[c][r], float) and math.isnan(cols_f[c][r])) for c in kw['x'] if c in need))
    check(f'{label}: Save Difference gives every row whose factors the tree can take (excluded, no response, no treatment too)', sorted(d['rows']), want_rows)
    tcol = kw['treatment']
    has_t = [r for r in d['rows'] if cols_f[tcol][r] is not None]
    check(f'{label}: Save Predicteds, every such row with a treatment', sorted(pr['rows']), sorted(has_t))
    ev = eval_formulas(cols_f, [fo['difference']['expr'], fo['prediction']['expr']])
    check(f'{label}: the Difference Formula, in the page\'s formula engine, is Save Difference on every row', same_values(ev[0], d['rows'], d['values']), True)
    pv_ = pr['values'] if 'values' in pr else [p_[0] if len(p_) == 1 else p_[pr['names'].index(fo['prediction']['name'])] for p_ in pr['prob']]
    check(f'{label}: the Prediction Formula is Save Predicteds on every row', same_values(ev[1], pr['rows'], pv_), True)
    if 'three' == tcol:
        g3 = np.array(three)
        nd = tree.root
        ok5 = np.arange(n) != 5   # the row with no response
        check(f'{label}: the treatment is the first level (A), the control the others', math.isclose(nd.mg[1], float(np.mean(yc[(g3 == 'A') & ok5])), rel_tol=1e-12) and math.isclose(nd.mg[0], float(np.mean(yc[(g3 != 'A') & ok5])), rel_tol=1e-12), True)
check('a categorical response of two levels: Save Predicteds gives both Prob[] columns and the most likely level', (lambda r: (r['names'], len(r['prob'][0]), r['most_name']))(call('uplift.save', table=T, y='yb', treatment='trt', x=['x1'], what='predicteds', steps=[{'op': 'split'}])),
      (['Prob[yes]', 'Prob[no]'], 2, 'Most Likely yb'))

# ---- the Treatment's level, the response's level of interest --------------------------------------------------------
r1 = fit(y='yc', x=['x1'], treat_level='Control')
check('Treatment Level: another level is the treatment, and the uplift changes its sign', (r1['treat'], math.isclose(r1['nodes'][0]['diff'], -fit(y='yc', x=['x1'])['nodes'][0]['diff'], rel_tol=1e-12)), ('Control', True))
r3 = fit(y='y3', x=['x1'], response_level='hi')
check('Response Level: the rate of another level (hi) against the others', (r3['interest'], math.isclose(r3['nodes'][0]['means'][1], float(np.mean(y3[T1] == 'hi')), rel_tol=1e-12)), ('hi', True))
check('... a response of three levels: its first level (lo) by default', fit(y='y3', x=['x1'])['interest'], 'lo')
check('the report names the treatment\'s levels and the control\'s', (fit(y='yc', x=['x1'])['treat'], fit(y='yc', x=['x1'])['control']), ('Treated', ['Control']))
for label, kw, frag in [('a continuous Treatment', dict(y='yc', treatment='x2', x=['x1']), 'nominal or ordinal'),
                        ('the Treatment as a factor too', dict(y='yc', treatment='trt', x=['x1', 'trt']), 'cannot be'),
                        ('a treatment of one level in the rows', dict(y='yc', treatment='trt', x=['x1'], rows=[i for i in range(n) if T1[i]]), 'one level')]:
    try:
        fit(**kw)
        msg = ''
    except ValueError as e:
        msg = str(e)
    check(f'an error: {label} ({msg})', frag in msg, True)
big = table({'y': list(rng.normal(size=60000)), 'x': list(rng.normal(size=60000)), 't': list(rng.choice(['a', 'b'], 60000))}, types={'t': 'nominal'})
check('JMP\'s default Minimum Size Split: the rows over 2000 when that is more than 25 (60000 rows: 30)', grown(table=big, y='y', treatment='t', x=['x'])[3], 30.0)

# ---- the code under the report, and every graph's code, run on a CSV export -----------------------------------------------
from test_predictive import joined, run_graph as run_graph_native, scatter_pts  # noqa: E402

GTMP = tempfile.mkdtemp(prefix='smui-uplift-charts-')


def run_script(script, tid):
    """The report's code run on a CSV export of the table: its printed lines."""
    from test_predictive import export_frame
    with tempfile.TemporaryDirectory() as tmp:
        export_frame(tid).to_csv(os.path.join(tmp, 'data.csv'), index=False)
        with open(os.path.join(tmp, 'code.py'), 'w') as fh:
            fh.write(script)
        out = subprocess.run([sys.executable, 'code.py'], cwd=tmp, capture_output=True, text=True, timeout=600)
    return out.stdout, out.stderr[-1500:]


for label, kw in [('continuous, a validation column', dict(y='yc', x=['x1', 'g', 'x2m'], validation='v', steps=[{'op': 'split', 'n': 3}])),
                  ('categorical, weight and frequency, Go on a portion', dict(y='yb', x=['x1', 'o', 'g'], weight='w', freq='f', portion=0.3, seed=4, steps=[{'op': 'go'}])),
                  ('three treatment levels, rows left out, the Show Split options off', dict(y='yc', treatment='three', x=['x1', 'g'], rows=list(range(40, n)), steps=[{'op': 'split', 'n': 2}], plot={'points': False, 'stats': False, 'count': False}))]:
    kw = dict(kw, table=T, table_name='data')
    kw.setdefault('treatment', 'trt')
    res = call('uplift.fit', **kw)
    if 'error' in res:
        check(f'{label}: fits', res['error'], None)
        continue
    out, err = run_script(res['script'], T)
    got = {ln.split()[0]: float(ln.split()[-1]) for ln in out.splitlines() if ln.split() and ln.split()[0] in ('Training', 'Validation', 'Test') and 'RSquare' in ln}
    check(f'{label}: the report\'s code runs on the CSV and prints the summary\'s RSquare of each set', (err if not got else '', {k: round(v, 6) for k, v in got.items()}),
          ('', {r_['set']: round(r_['rsquare'], 6) for r_ in res['summary']}))
    check(f'{label}: ... and the tree: every node\'s condition, the root first', [ln.strip().split('  ')[0] for ln in out.splitlines() if 'Trt Diff' in ln], [nd['label'] for nd in res['nodes']])
    if 'rows' in kw:
        check(f'{label}: the code leaves out the rows the report leaves out', f'df = df.drop(index={sorted(set(range(n)) - set(kw["rows"]))})' in res['script'], True)
    Pc = res['plots']
    a = res['assign']
    plot = kw.get('plot') or {}
    # the model graph
    F, err = run_graph_native(joined(Pc, 'graph'), T, GTMP)
    check(f'{label}: the model graph\'s code runs', err, None)
    if F:
        ax = F['axes'][0]
        parts = [(l, g_, [i for i in range(len(a['rows'])) if a['set'][i] == 0 and a['leaf'][i] == l and a['trt'][i] == g_]) for l in range(len(res['leaves'])) for g_ in (1, 0)]
        edges = np.r_[0, np.cumsum([len(r_) for _, _, r_ in parts])] / sum(len(r_) for _, _, r_ in parts)
        lines = sorted((round(ln['x'][0], 9), round(ln['y'][0], 9)) for ln in ax['lines'] if ln['ls'] == '-' and len(ln['x']) == 2)
        want = sorted((round(edges[k], 9), round(res['leaves'][l]['means'][g_], 9)) for k, (l, g_, _) in enumerate(parts))
        check(f'{label}: ... each group\'s mean across its part of each leaf', lines, want)
        if not res['binary'] and plot.get('points', True):
            want_pts = [(edges[k] + (q + 0.5) / len(r_) * (edges[k + 1] - edges[k]), a['y'][i]) for k, (_, _, r_) in enumerate(parts) for q, i in enumerate(r_)]
            got_pts = scatter_pts(ax)
            check(f'{label}: ... the training rows evenly across their parts', len(got_pts) == len(want_pts) and np.allclose(sorted(got_pts), sorted(want_pts)), True)
        check(f'{label}: ... the treatment and the control in the legend', F['legend'], [res['treat'], res['control_label']])
    # the tree
    F, err = run_graph_native(joined(Pc, 'tree'), T, GTMP)
    check(f'{label}: the tree\'s code runs', err, None)
    if F:
        ax = F['axes'][0]
        texts = [t_['s'] for t_ in ax['texts']]
        boxes = [b for b in ax['bars'] if b['fc'] == '#fcf7f2ff']
        check(f'{label}: ... a box per node, two lines per split', (len(boxes), len(ax['lines'])), (len(res['nodes']), 2 * res['splits']))
        fmt_ = (lambda v: f'{v:.4f}'.replace('-', '−')) if res['binary'] else None
        diffs = [t_ for t_ in texts]
        if res['binary']:
            check(f'{label}: ... every node\'s Trt Diff and rates', all(fmt_(nd['diff']) in texts and fmt_(nd['means'][0]) in texts for nd in res['nodes']), True)
        check(f'{label}: ... the Show Split options: t Ratio {"shown" if plot.get("stats", True) else "hidden"}, Count {"shown" if plot.get("count", True) else "hidden"}', ('t Ratio' in texts, 'Count' in texts), (plot.get('stats', True), plot.get('count', True)))
    # the Uplift Graph, the Qini curve, the split history, the AICc, the contributions
    F, err = run_graph_native(joined(Pc, 'upliftgraph'), T, GTMP)
    check(f'{label}: the Uplift Graph\'s code runs', err, None)
    if F:
        ax = F['axes'][0]
        order = sorted(range(len(res['leaves'])), key=lambda l: -res['leaves'][l]['diff'])
        check(f'{label}: ... each leaf\'s uplift, the largest first, as wide as its share of the training rows', [(round(b['h'], 9), round(b['w'], 9)) for b in ax['bars']],
              [(round(res['leaves'][l]['diff'], 9), round(res['leaves'][l]['count'] / sum(lf['count'] for lf in res['leaves']), 9)) for l in order])
        if 'Validation' in res['sets']:
            vl = [round(ln['y'][0], 9) for ln in ax['lines'] if ln['color'] and ln['color'].startswith('#1c1c1c')]
            check(f'{label}: ... and each leaf\'s validation uplift as a black line', vl, [round(res['leaves'][l]['validation']['diff'], 9) for l in order if res['leaves'][l]['validation']['diff'] is not None and math.isfinite(res['leaves'][l]['validation']['diff'])])
    F, err = run_graph_native(joined(Pc, 'qini'), T, GTMP)
    check(f'{label}: the Qini curve\'s code runs', err, None)
    if F:
        ax = F['axes'][0]
        ok_q = all(any(len(ln['x']) == len(q['x']) and np.allclose(ln['x'], q['x']) and np.allclose(ln['y'], q['q']) for ln in ax['lines']) for q in res['qini'])
        check(f'{label}: ... every set\'s curve is the report\'s, with its coefficient in the legend', (ok_q, len(ax['legend'])), (True, len(res['qini'])))
        check(f'{label}: ... the coefficients written as the page writes them (a true minus sign)', all(lg.startswith(q['set']) and ('−' in lg) == (q['coef'] < 0) for lg, q in zip(ax['legend'], res['qini'])), True)
    F, err = run_graph_native(joined(Pc, 'history'), T, GTMP)
    check(f'{label}: the split history\'s code runs', err, None)
    if F:
        ax = F['axes'][0]
        ok_h = all(any(ln['label'] == s_ and len(ln['y']) == len(res['history']) and np.allclose(ln['y'], [h[s_] for h in res['history']]) for ln in ax['lines']) for s_ in res['sets'])
        check(f'{label}: ... each set\'s RSquare after each split', (ok_h, ax['ylabel']), (True, 'RSquare'))
    F, err = run_graph_native(joined(Pc, 'aicc'), T, GTMP)
    check(f'{label}: the AICc graph\'s code runs', err, None)
    if F:
        ln = F['axes'][0]['lines'][0]
        check(f'{label}: ... the AICc after each split', np.allclose(ln['y'], [h['aicc'] for h in res['history']], rtol=1e-12), True)
    c = res['contributions']
    F, err = run_graph_native(res['plots']['head_code'] + '\n\n# ----\n' + c['plot_code'], T, GTMP)
    check(f'{label}: the Column Uplift Contributions\' code runs', err, None)
    if F:
        ax = F['axes'][0]
        check(f'{label}: ... each column\'s share of the F Ratios (or ChiSquares) of its splits', [round(b['w'], 9) for b in ax['bars']], [round(r_['portion'] or 0, 9) for r_ in c['rows']])

# ---- a K-fold Validation column: every row trains; Go by the crossvalidated RSquare of its folds -----------------------------------
rk_ = np.random.default_rng(78)
kfv = rk_.integers(1, 6, n).astype(float)
TK = table({**cols, 'kf': list(kfv)}, types=TYPES, levels=LEVELS)
fold_u = (kfv - 1).astype(int)
rku = fit(table=TK, y='yc', x=['x1', 'g', 'x2'], validation='kf', steps=[{'op': 'go'}])
Pu, Uu, tu, msu = grown(table=TK, y='yc', x=['x1', 'g', 'x2'], validation='kf')


def cv_uplift(s_):
    """Each row predicted by the uplift tree of s_ best splits grown on the other folds (the engine's UpliftTree)."""
    oofs = np.zeros(n)
    for f_ in range(5):
        tt_ = up.UpliftTree(tu.cols, Pu.X, Uu['y'], Uu['trt'], Uu['binary'], None, None, np.where(fold_u == f_, 1, 0), msu, True)
        for _ in range(s_):
            if tt_.split_best() is None:
                break
        oofs[fold_u == f_] = tt_.fitted()[fold_u == f_]
    yy = Uu['y']
    return 1 - np.sum((yy - oofs) ** 2) / np.sum((yy - yy.mean()) ** 2)


want_u = [cv_uplift(e['splits']) for e in rku['go']['trace']]
check('a K-fold Validation column: five folds, every row trains, no validation rows', (rku['folds']['k'], rku['has_validation'], [r_['set'] for r_ in rku['summary']]), (5, False, ['Training']))
check.near('Go by the folds: the crossvalidated RSquare of each size (the regression of the leaves by treatment), by hand', max(abs(e['Crossvalidation'] - v_) for e, v_ in zip(rku['go']['trace'], want_u)), 0.0, abs_=1e-10)
check('... keeps the size with the best', (rku['splits'], rku['go']['best']), (int(np.argmax(want_u)), int(np.argmax(want_u))))
out, err = run_script(call('uplift.fit', table=TK, treatment='trt', y='yc', x=['x1', 'g', 'x2'], validation='kf', steps=[{'op': 'go'}], table_name='data')['script'], TK)
check('... the report\'s code grows the same tree by the column\'s folds', [ln.strip().split('  ')[0] for ln in out.splitlines() if 'Trt Diff' in ln], [nd['label'] for nd in rku['nodes']])
F, err = run_graph_native(joined(rku['plots'], 'history'), TK, GTMP)
check('... the split history\'s code draws the crossvalidated RSquare Go looked at', (err, F and any(q['label'] == 'Crossvalidation' for q in F['axes'][0]['lines'])), (None, True))

sys.exit(check.done())
