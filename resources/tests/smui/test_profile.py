#!/usr/bin/env python3
"""The profiler of any model (resources/py/smui/profile.py): JMP's
desirability functions (scipy's PchipInterpolator through the three points,
flat beyond, JMP's default values), the overall desirability (the weighted
geometric mean), the Desirability row of the traces, Maximize Desirability
on surfaces whose optimum is known (smooth, with a categorical factor, and a
tree's steps against a fine grid), and Assess Variable Importance on the
Ishigami function (Sobol's analytic indices) and against
scipy.stats.sobol_indices called directly; everything also through
registry.dispatch as the page calls it.

    python3 resources/tests/smui/test_profile.py
"""
import json
import math
import sys

import numpy as np
from scipy import stats
from scipy.interpolate import PchipInterpolator

from backend import FAILED, Checks, call, table

check = Checks()
check('profile.py imports', 'profile' in FAILED, False)
from smui import profile as pf, registry  # noqa: E402

# ---- desirability functions ----------------------------------------------------------------------
sp = {'goal': 'max', 'points': pf.default_points('max', 10, 30), 'importance': 1}
check('JMP\'s default points for Maximize: 0.0183, 0.5, 0.9817 at the low, middle and high', sp['points'], [[10.0, 0.0183], [20.0, 0.5], [30.0, 0.9817]])
check('... for Minimize the other way round', [p[1] for p in pf.default_points('min', 0, 1)], [0.9817, 0.5, 0.0183])
check('... for Match Target 1 in the middle', [p[1] for p in pf.default_points('target', 0, 1)], [0.0183, 1.0, 0.0183])
y = np.linspace(0, 40, 401)
d = pf.desirability(sp, y)
ref = PchipInterpolator([10, 20, 30], [0.0183, 0.5, 0.9817])(np.clip(y, 10, 30))
check('d(y) is scipy\'s PchipInterpolator through the points', bool(np.allclose(d, ref, atol=1e-15)), True)
check('flat beyond the points', (float(d[0]), float(d[-1])), (0.0183, 0.9817))
check('monotone for Maximize', bool(np.all(np.diff(d) >= -1e-15)), True)
tg = pf.desirability({'goal': 'target', 'points': [[0, 0.1], [5, 1.0], [10, 0.1]]}, np.array([0, 2.5, 5, 7.5, 10.0]))
check('Match Target peaks at the target', (float(tg[2]), bool(tg[1] < 1 and tg[3] < 1), float(tg[0])), (1.0, True, 0.1))
check('no goal: desirability 1', pf.desirability({'goal': 'none', 'points': []}, [1, 2]).tolist(), [1.0, 1.0])
check('points in any order, desirabilities kept within 0 and 1', pf.desirability({'goal': 'max', 'points': [[3, 1.2], [1, -0.5], [2, 0.5]]}, [1, 3]).tolist(), [0.0, 1.0])
# the overall desirability
specs = {'a': {'goal': 'max', 'points': [[0, 0.1], [1, 0.5], [2, 0.9]], 'importance': 2}, 'b': {'goal': 'min', 'points': [[0, 0.9], [1, 0.5], [2, 0.1]], 'importance': 1}, 'c': {'goal': 'none'}}
pa, pb = np.array([0.5, 1.5]), np.array([0.2, 1.9])
D = pf.overall(specs, {'a': pa, 'b': pb, 'c': np.array([9.0, 9.0])})
want = (pf.desirability(specs['a'], pa) ** 2 * pf.desirability(specs['b'], pb)) ** (1 / 3)
check('overall: the importance-weighted geometric mean of the responses with a goal', bool(np.allclose(D, want)), True)
check('a desirability of 0 makes the whole 0', float(pf.overall({'a': {'goal': 'max', 'points': [[0, 0], [1, 0.5], [2, 1]]}}, {'a': np.array([-1.0])})[0]), 0.0)
check('no goal anywhere: no overall desirability', pf.overall({'c': {'goal': 'none'}}, {'c': np.array([1.0])}), None)


# ---- a model with a known surface --------------------------------------------------------------------
def smooth(settings):
    x1 = np.array([s['x1'] for s in settings]); x2 = np.array([s['x2'] for s in settings])
    g = np.array([{'a': 0.0, 'b': 0.5, 'c': 0.1}[s.get('g', 'a')] for s in settings])
    return [{'name': 'y', 'pred': 1 - (x1 - 0.3) ** 2 - (x2 - 0.7) ** 2 + g, 'lower': None, 'upper': None, 'bounded': False},
            {'name': 'z', 'pred': x1 + x2, 'lower': None, 'upper': None, 'bounded': False}]


facs = [{'name': 'x1', 'type': 'continuous', 'min': 0.0, 'max': 1.0, 'mean': 0.5}, {'name': 'x2', 'type': 'continuous', 'min': 0.0, 'max': 1.0, 'mean': 0.5},
        {'name': 'g', 'type': 'categorical', 'levels': ['a', 'b', 'c'], 'labels': ['a', 'b', 'c']}]
PR = pf.Predictor(facs, smooth)
des = {'y': {'goal': 'max', 'points': [[0.0, 0.0183], [0.75, 0.5], [1.5, 0.9817]], 'importance': 1}}
best = pf.maximize(PR, des, seed=3)
s = best['setting']
check('Maximize: the smooth optimum x1 = 0.3, x2 = 0.7 (within 1e-3)', (abs(s['x1'] - 0.3) < 1e-3, abs(s['x2'] - 0.7) < 1e-3), (True, True))
check('... and the best level of the categorical factor', s['g'], 'b')
check.near('... its desirability is d(1.5)', best['desirability'], 0.9817, 1e-6)
des2 = {'y': des['y'], 'z': {'goal': 'target', 'points': [[0.0, 0.0183], [0.6, 1.0], [2.0, 0.0183]], 'importance': 1}}
b2 = pf.maximize(PR, des2, seed=3)
grid = np.linspace(0, 1, 201)
X1, X2 = np.meshgrid(grid, grid)
sets = [{'x1': a, 'x2': b, 'g': 'b'} for a, b in zip(X1.ravel(), X2.ravel())]
Dg = pf.overall(des2, {p['name']: p['pred'] for p in smooth(sets)})
check('two responses: no worse than the best of a 201 x 201 grid', b2['desirability'] >= float(Dg.max()) - 1e-9, True)

try:
    from sklearn.tree import DecisionTreeRegressor
    rng = np.random.default_rng(1)
    Xt = rng.uniform(0, 1, (400, 2))
    yt = np.sin(6 * Xt[:, 0]) + Xt[:, 1] ** 2 + rng.normal(0, 0.05, 400)
    tree = DecisionTreeRegressor(max_depth=5, random_state=0).fit(Xt, yt)
    tf = [{'name': 'u', 'type': 'continuous', 'min': 0.0, 'max': 1.0, 'mean': 0.5}, {'name': 'v', 'type': 'continuous', 'min': 0.0, 'max': 1.0, 'mean': 0.5}]
    TP = pf.Predictor(tf, lambda S: [{'name': 'y', 'pred': tree.predict(np.array([[q['u'], q['v']] for q in S])), 'lower': None, 'upper': None, 'bounded': False}])
    tdes = {'y': {'goal': 'max', 'points': pf.default_points('max', float(yt.min()), float(yt.max())), 'importance': 1}}
    bt = pf.maximize(TP, tdes, seed=0)
    G = np.linspace(0, 1, 301)
    U, V = np.meshgrid(G, G)
    gridD = pf.desirability(tdes['y'], tree.predict(np.column_stack([U.ravel(), V.ravel()])))
    check('a tree\'s steps: the best leaf, as a 301 x 301 grid finds it', bt['desirability'] >= float(gridD.max()) - 1e-12, True)
except ImportError:
    check('scikit-learn for the tree check', False, True)

# ---- the Desirability row of the traces ----------------------------------------------------------------
tr = pf.traces(PR, {'x1': 0.2, 'x2': 0.9, 'g': 'c'}, grid=11, des=des2)
dr = tr['desirability']
cur = smooth([{'x1': 0.2, 'x2': 0.9, 'g': 'c'}])
check.near('the current overall desirability', dr['current'], float(pf.overall(des2, {p['name']: p['pred'] for p in cur})[0]), 1e-12)
row = dr['traces'][0]
sets = [{'x1': v, 'x2': 0.9, 'g': 'c'} for v in np.linspace(0, 1, 11)]
check('D over a factor\'s trace, the others at their current values', bool(np.allclose(row['D'], pf.overall(des2, {p['name']: p['pred'] for p in smooth(sets)}))), True)
check('each response\'s d now, and its curve to draw', (sorted(dr['individual']), len(dr['curves']['y']['y'])), (['y', 'z'], 81))
check('no specs: no Desirability row', 'desirability' in pf.traces(PR, None, 11), False)

# ---- Assess Variable Importance: the Ishigami function ------------------------------------------------------
def ishigami(settings):
    x = np.array([[s['x1'], s['x2'], s['x3']] for s in settings])
    return [{'name': 'f', 'pred': np.sin(x[:, 0]) + 7 * np.sin(x[:, 1]) ** 2 + 0.1 * x[:, 2] ** 4 * np.sin(x[:, 0]), 'lower': None, 'upper': None, 'bounded': False}]


pi = math.pi
IF = [{'name': f'x{i}', 'type': 'continuous', 'min': -pi, 'max': pi, 'mean': 0.0} for i in (1, 2, 3)]
imp = pf.importance(pf.Predictor(IF, ishigami), n=2 ** 14, seed=5)
rows = {r['column']: r for r in imp['responses'][0]['rows']}
a, b = 7.0, 0.1
V = a ** 2 / 8 + b * pi ** 4 / 5 + b ** 2 * pi ** 8 / 18 + 0.5
S1 = 0.5 * (1 + b * pi ** 4 / 5) ** 2 / V
S2 = a ** 2 / 8 / V
ST1 = S1 + b ** 2 * pi ** 8 * (1 / 18 - 1 / 50) / V
ST3 = b ** 2 * pi ** 8 * (1 / 18 - 1 / 50) / V
for name, got, want in [('x1 main', rows['x1']['main'], S1), ('x2 main', rows['x2']['main'], S2), ('x3 main', rows['x3']['main'], 0.0),
                        ('x1 total', rows['x1']['total'], ST1), ('x2 total', rows['x2']['total'], S2), ('x3 total', rows['x3']['total'], ST3)]:
    check(f'Ishigami {name}: {want:.4f} (within 0.03)', abs(got - want) < 0.03, True)
direct = stats.sobol_indices(func=lambda x: np.sin(x[0]) + 7 * np.sin(x[1]) ** 2 + 0.1 * x[2] ** 4 * np.sin(x[0]), n=2 ** 14,
                             dists=[stats.uniform(loc=-pi, scale=2 * pi)] * 3, rng=np.random.default_rng(5))
check('the same as scipy.stats.sobol_indices called directly', bool(np.allclose([rows[f'x{i}']['main'] for i in (1, 2, 3)], direct.first_order) and np.allclose([rows[f'x{i}']['total'] for i in (1, 2, 3)], direct.total_order)), True)
check('n rounds up to a power of two', pf.importance(pf.Predictor(IF, ishigami), n=1000, seed=1)['n'], 1024)
ci = pf.importance(pf.Predictor(facs, smooth), n=2048, seed=2)
yv = {r['column']: r for r in ci['responses'][0]['rows']}
check('a categorical factor drawn over its levels has its share', 0.2 < yv['g']['total'] < 0.9 and yv['g']['main'] > 0.1, True)
zr = {r['column']: r for r in ci['responses'][1]['rows']}
check('z = x1 + x2: each half, the level nothing', (abs(zr['x1']['main'] - 0.5) < 0.05, abs(zr['x2']['total'] - 0.5) < 0.05, abs(zr['g']['total']) < 0.02), (True, True, True))
res = pf.importance(pf.Predictor(IF[:2], lambda S: [{'name': 'f', 'pred': np.array([q['x1'] + q['x2'] for q in S]), 'lower': None, 'upper': None, 'bounded': False}], {'x1': [0.0] * 50 + [0.01] * 50, 'x2': list(np.linspace(-3, 3, 100))}), 'resampled', 2048, 3, {'x1': [0.0] * 50 + [0.01] * 50, 'x2': list(np.linspace(-3, 3, 100))})
rr = {r['column']: r for r in res['responses'][0]['rows']}
check('resampled inputs: a factor whose data barely vary barely matters', (rr['x1']['total'] < 0.01, rr['x2']['main'] > 0.98), (True, True))

# ---- through dispatch -------------------------------------------------------------------------------------------
T = table({'q': [1.0, 2.0]})
pf.expose('ptest2', lambda tid, rows=None, **spec: pf.Predictor(facs, smooth), packages=())
check('expose registers profile, maximize, importance, marginal and shapley', [n for n in registry.names() if n.startswith('ptest2.')], ['ptest2.importance', 'ptest2.marginal', 'ptest2.maximize', 'ptest2.profile', 'ptest2.shapley'])
m = call('ptest2.maximize', table=T, des=des, max_seed=3, grid=11, seed=99)
check('maximize through dispatch: the optimum and the profile there', (abs(m['best']['setting']['x1'] - 0.3) < 1e-3, m['best']['setting']['g'], m['profile']['factors'][2]['current']), (True, 'b', 'b'))
check('a platform\'s own seed does not reach the optimizer', m['best']['setting'] == pf.maximize(PR, des, seed=3)['setting'], True)
i2 = call('ptest2.importance', table=T, imp_n=512, imp_seed=4)
check('importance through dispatch', (i2['n'], [r['response'] for r in i2['responses']]), (512, ['y', 'z']))
p2 = call('ptest2.profile', table=T, des=des2, grid=11)
check('the profile with desirability through dispatch', round(p2['desirability']['current'], 12), round(float(pf.overall(des2, {p['name']: p['pred'] for p in smooth([pf.setting(facs, None)])})[0]), 12))

# ---- Marginal Model Plots: partial dependence and ICE, by brute force -------------------------------------------------
rng2 = np.random.default_rng(11)
bg = [{'x1': float(u), 'x2': float(v_), 'g': str(q)} for u, v_, q in zip(rng2.uniform(0, 1, 60), rng2.uniform(0, 1, 60), rng2.choice(['a', 'b', 'c'], 60))]


def inter(settings):
    x1 = np.array([q['x1'] for q in settings]); x2 = np.array([q['x2'] for q in settings])
    gg = np.array([{'a': 0.0, 'b': 1.0, 'c': -1.0}[q['g']] for q in settings])
    return [{'name': 'y', 'pred': x1 * x2 + gg * x1 + x2 ** 2, 'lower': None, 'upper': None, 'bounded': False}]


PI = pf.Predictor(facs, inter)
mm = pf.marginal(PI, bg, grid=11, n=40, ice=5, seed=3)
used = pf._sample(bg, 40, 3)
gx = np.linspace(0, 1, 11)
pd_x1 = [np.mean([v * b_['x2'] + {'a': 0.0, 'b': 1.0, 'c': -1.0}[b_['g']] * v + b_['x2'] ** 2 for b_ in used]) for v in gx]
t1 = mm['responses'][0]['traces'][0]
check.near('Marginal Model Plots: x1\'s curve is the mean over the background rows with x1 set to each value (partial dependence, by hand)', float(np.max(np.abs(np.asarray(t1['pd']) - pd_x1))), 0.0, 1e-12)
ice0 = [v * used[0]['x2'] + {'a': 0.0, 'b': 1.0, 'c': -1.0}[used[0]['g']] * v + used[0]['x2'] ** 2 for v in gx]
check.near('... an ICE line is one background row\'s own curve', float(np.max(np.abs(np.asarray(t1['ice'][0]) - ice0))), 0.0, 1e-12)
tg_ = mm['responses'][0]['traces'][2]
pd_g = [np.mean([b_['x1'] * b_['x2'] + {'a': 0.0, 'b': 1.0, 'c': -1.0}[lv] * b_['x1'] + b_['x2'] ** 2 for b_ in used]) for lv in ['a', 'b', 'c']]
check.near('... a categorical factor\'s curve over its levels', float(np.max(np.abs(np.asarray(tg_['pd']) - pd_g))), 0.0, 1e-12)
check('... n rows drawn from the seed, ICE lines of the first of them', (mm['n'], mm['ice'], len(t1['ice']), tg_['x']), (40, 5, 5, ['a', 'b', 'c']))

# ---- Shapley values: a linear model's closed form, exact enumeration, additivity -----------------------------------------
lin_f = [{'name': 'a', 'type': 'continuous', 'min': 0.0, 'max': 1.0, 'mean': 0.5}, {'name': 'b', 'type': 'continuous', 'min': 0.0, 'max': 1.0, 'mean': 0.5},
         {'name': 'c', 'type': 'continuous', 'min': 0.0, 'max': 1.0, 'mean': 0.5}, {'name': 'd', 'type': 'continuous', 'min': 0.0, 'max': 1.0, 'mean': 0.5}]
coef = np.array([2.0, -1.0, 0.5, 3.0])
LP = pf.Predictor(lin_f, lambda S: [{'name': 'y', 'pred': 1.0 + np.array([[q['a'], q['b'], q['c'], q['d']] for q in S]) @ coef, 'lower': None, 'upper': None, 'bounded': False}])
bgl = [dict(zip('abcd', rng2.uniform(0, 1, 4))) for _ in range(30)]
xs_ = [dict(zip('abcd', rng2.uniform(0, 1, 4)), __row=i) for i in range(8)]
sh = pf.shapley(LP, xs_, bgl, n=30, perms=6, seed=1)
mb = np.array([[q[k] for k in 'abcd'] for q in bgl]).mean(0)
want_l = np.array([[coef[j] * (x[k] - mb[j]) for j, k in enumerate('abcd')] for x in xs_]).T
check.near('Shapley values of a linear model: coefficient x (value - the background\'s mean), whatever the orders (6 random of 24)', float(np.max(np.abs(np.asarray(sh['responses'][0]['values']) - want_l))), 0.0, 1e-12)
check('... the rows named, the orders antithetic', (sh['rows'], sh['orders'], sh['how'].startswith('6 random orderings')), (list(range(8)), 6, True))


def nonlin(S):
    a_ = np.array([q['a'] for q in S]); b_ = np.array([q['b'] for q in S]); c_ = np.array([q['c'] for q in S])
    return [{'name': 'y', 'pred': a_ * b_ + np.sin(3 * c_) * a_ + (b_ > 0.5), 'lower': None, 'upper': None, 'bounded': False}]


NP_ = pf.Predictor(lin_f[:3], nonlin)
bgn = [dict(zip('abc', rng2.uniform(0, 1, 3))) for _ in range(20)]
xn = [dict(zip('abc', rng2.uniform(0, 1, 3)), __row=i) for i in range(5)]
se = pf.shapley(NP_, xn, bgn, n=20, perms=6, seed=0)
import itertools  # noqa: E402


def v_of(x, S_):
    return float(np.mean(nonlin([{k: (x[k] if k in S_ else b_[k]) for k in 'abc'} for b_ in bgn])[0]['pred']))


exact = np.zeros((3, 5))
for i_, x in enumerate(xn):
    for j, k in enumerate('abc'):
        others = [q for q in 'abc' if q != k]
        tot = 0.0
        for r_ in range(3):
            for S_ in itertools.combinations(others, r_):
                wgt = math.factorial(len(S_)) * math.factorial(3 - len(S_) - 1) / math.factorial(3)
                tot += wgt * (v_of(x, set(S_) | {k}) - v_of(x, set(S_)))
        exact[j, i_] = tot
check.near('Shapley values, 3 factors and 6 permutations: every ordering once, the exact values (the subset formula by brute force)', float(np.max(np.abs(np.asarray(se['responses'][0]['values']) - exact))), 0.0, 1e-12)
check('... said so', se['how'], 'every ordering of the 3 factors (exact)')
sr = pf.shapley(NP_, xn, bgn, n=20, perms=2, seed=4)
gap = max(abs(float(np.sum(np.asarray(sr['responses'][0]['values'])[:, i_])) - (float(nonlin([{k: x[k] for k in 'abc'}])[0]['pred'][0]) - float(np.mean(nonlin(bgn)[0]['pred'])))) for i_, x in enumerate(xn))
check.near('... with few permutations the values of a row still add up to its prediction less the background\'s mean', gap, 0.0, 1e-12)
check.near('... and the result says how near (the gap)', sr['responses'][0]['gap'], 0.0, 1e-12)
Ts = table({'x1': list(rng2.uniform(0, 1, 12)), 'x2': list(rng2.uniform(0, 1, 12)), 'g': list(rng2.choice(['a', 'b', 'c'], 12))}, types={'g': 'nominal'}, levels={'g': ['a', 'b', 'c']})
pf.expose('ptest3', lambda tid, rows=None, **spec: pf.Predictor(facs, inter), packages=())
shd = call('ptest3.shapley', table=Ts, sh_rows=[0, 3, 5], sh_n=12, sh_perm=6, sh_seed=2)
check('through dispatch: the table\'s rows explained against the table\'s rows (no training data given), a value per factor and row', (shd['rows'], shd['factors'], len(shd['responses'][0]['values']), len(shd['responses'][0]['values'][0])), ([0, 3, 5], ['x1', 'x2', 'g'], 3, 3))
mmd = call('ptest3.marginal', table=Ts, mm_n=12, mm_ice=2, grid=5)
check('... and the marginal model plots', (mmd['n'], len(mmd['responses'][0]['traces'][0]['x']), len(mmd['responses'][0]['traces'][0]['ice'])), (12, 5, 2))

sys.exit(check.done())
