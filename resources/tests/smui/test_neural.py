#!/usr/bin/env python3
"""Analyze > Predictive Modeling > Neural's backend (resources/py/smui/neural.py),
checked against scikit-learn's MLPRegressor and MLPClassifier called
directly with the same settings (the design, the standardization, the
penalty path replayed with warm starts, the random states), the network
written out from its Estimates (the forward pass by hand, the log odds
against the last level), closed forms (an identity network without a
penalty is least squares, weighted least squares with a Freq column, and
logistic regression), the sets (Holdback, KFold chosen as JMP chooses,
Excluded Rows Holdback, a Validation column with a test set), Informative
Missing's fills from the training rows, boosting by hand (the residuals
and, for a categorical response, the gradient and its line search),
Transform Covariates (PowerTransformer on the training rows), tours, the
profiler's traces, Save Columns, JMP's defaults and names, the warnings,
and the Python shown under each model run on a CSV export of the table.

    python3 resources/tests/smui/test_neural.py
"""
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
check('neural.py imports', 'neural' in FAILED, False)
from smui import neural as NN, predictive as pv, registry  # noqa: E402

try:
    import sklearn
    from scipy.optimize import minimize_scalar
    from sklearn import metrics
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.neural_network import MLPClassifier, MLPRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import PowerTransformer, StandardScaler
    import statsmodels.api as sm
except ImportError:
    print('scikit-learn 1.8 and statsmodels are needed for these tests (Pyodide 314.0.7 has scikit-learn 1.8.0)')
    sys.exit(1)

check('scikit-learn is 1.8 (as in Pyodide 314.0.7)', sklearn.__version__.startswith('1.8'), True)
# the replays here stop at max_iter as the backend's do; the backend's own
# warnings are caught by registry.dispatch whatever the filter
warnings.filterwarnings('ignore', category=ConvergenceWarning)

# ---- the table ------------------------------------------------------------------------------------
rng = np.random.default_rng(20260927)
n = 300
x1 = rng.normal(0, 1, n)
x2 = rng.uniform(-2, 2, n)
x3 = np.exp(rng.normal(0, 0.8, n))                     # skewed, for Transform Covariates
g = rng.choice(['a', 'b', 'c'], n, p=[0.5, 0.3, 0.2])
y = np.sin(2 * x1) + 0.5 * x2 ** 2 + np.where(g == 'b', 1.0, 0.0) + 0.3 * np.log(x3) + rng.normal(0, 0.3, n)
y2 = x1 * x2 + rng.normal(0, 0.5, n)
cls = np.where(y + rng.normal(0, 0.6, n) > np.median(y), 'hi', 'lo')
three = np.where(y < np.quantile(y, 0.3), 'L', np.where(y < np.quantile(y, 0.7), 'M', 'H'))
fq = rng.integers(1, 4, n).astype(float)
vnum = rng.choice([0.0, 1.0, 2.0], n, p=[0.6, 0.25, 0.15])
vtxt = np.array(['Training', 'Validation', 'Test'])[vnum.astype(int)]
x1m = x1.copy()
x1m[rng.choice(n, 15, replace=False)] = np.nan
ym = y.copy()
ym[[4, 40, 140]] = np.nan
kcode = np.array([{'L': 3.0, 'M': 1.0, 'H': 2.0}[v] for v in three])      # a numeric nominal response
cols = {'y': list(y), 'y2': list(y2), 'ym': [None if np.isnan(v) else v for v in ym], 'x1': list(x1), 'x2': list(x2), 'x3': list(x3), 'g': list(g),
        'cls': list(cls), 'three': list(three), 'f': list(fq), 'v': list(vnum), 'vt': list(vtxt), 'x1m': [None if np.isnan(v) else v for v in x1m], 'k': list(kcode)}
T = table(cols, types={'g': 'nominal', 'cls': 'nominal', 'three': 'ordinal', 'vt': 'nominal', 'k': 'nominal'}, levels={'three': ['L', 'M', 'H'], 'cls': ['hi', 'lo']})
XS = ['x1', 'x2', 'g']
SEED = 4242


def rs_of(seed, *k):
    """The random_state the backend should use, written out here."""
    return int(np.random.SeedSequence([int(seed) % (2 ** 32)] + list(k)).generate_state(1)[0] % (2 ** 31 - 1))


def mx(a, b):
    return float(np.max(np.abs(np.asarray(a, float) - np.asarray(b, float))))


def fit(model=None, y=('y',), x=XS, **kw):
    return call('neural.fit', table=T, y=list(y), x=list(x), seed=kw.pop('seed', SEED), model=model or {}, **kw)


def pipe(cls_, layers, act, rs, max_iter=200):
    return Pipeline([('scale', StandardScaler()), ('mlp', cls_(hidden_layer_sizes=layers, activation=act, solver='lbfgs', max_iter=max_iter, random_state=rs, warm_start=True))])


def alphas_of(net):
    """The penalty path up to the alpha chosen, from the report."""
    out = []
    for r in net['path']:
        out.append(r['alpha'])
        if r['chosen']:
            return out
    return out


def replay_cont(P, Ys, X, tr, alphas, layers, act, rs, w=None, max_iter=200):
    """A continuous network fitted here as the backend should fit it."""
    Y = np.column_stack(Ys)
    wt = np.ones(len(X)) if w is None else w
    mu = np.average(Y[tr], axis=0, weights=wt[tr])
    sd = np.sqrt(np.average((Y[tr] - mu) ** 2, axis=0, weights=wt[tr]))
    sd = np.where(sd > 0, sd, 1.0)
    Z = (Y - mu) / sd
    if Z.shape[1] == 1:
        Z = Z[:, 0]
    net = pipe(MLPRegressor, layers, act, rs, max_iter)
    fw = {} if w is None else {'scale__sample_weight': w[tr], 'mlp__sample_weight': w[tr]}
    for a in alphas:
        net.set_params(mlp__alpha=a).fit(X[tr], Z[tr], **fw)
    return mu + sd * net.predict(X).reshape(len(X), -1), net, mu, sd


def clip(p):
    p = np.clip(p, 1e-15, 1 - 1e-15)
    return p / p.sum(axis=1, keepdims=True)


def replay_cat(P, X, tr, alphas, layers, act, rs, w=None, max_iter=200, Xp=None):
    net = pipe(MLPClassifier, layers, act, rs, max_iter)
    fw = {} if w is None else {'scale__sample_weight': w[tr], 'mlp__sample_weight': w[tr]}
    for a in alphas:
        net.set_params(mlp__alpha=a).fit(X[tr], P.target[tr], **fw)
    Xp = X if Xp is None else Xp
    p = np.zeros((len(Xp), len(P.levels)))
    p[:, net.classes_] = net.predict_proba(Xp)
    return clip(p), net


def predicted(res, j=0):
    return np.array(res['responses'][j]['fit']['residuals']['predicted'])


def sets_of(res, j=0):
    return np.array(res['responses'][j]['fit']['residuals']['set'])


def saved_prob(model, y, x=XS, **kw):
    r = call('neural.save', table=T, y=list(y), x=list(x), seed=kw.pop('seed', SEED), model=model, what='predicteds', **kw)
    return r


def measures(res, j=0):
    return {m['set']: m for m in res['responses'][j]['fit']['measures']}


def nll_cont(yy, ff, w=None):
    w = np.ones(len(yy)) if w is None else w
    sse = float(np.sum(w * (yy - ff) ** 2))
    N = float(w.sum())
    return 0.5 * N * (math.log(2 * math.pi * sse / N) + 1)


# ---- the registry, JMP's defaults and names ----------------------------------------------------
names = registry.names()
check('neural.fit, neural.save and the profiler\'s three are registered', all(k in names for k in ('neural.fit', 'neural.save', 'neural.profile', 'neural.maximize', 'neural.importance')), True)
check('... and need scikit-learn', [json.loads(registry.packages_for(k)) for k in ('neural.fit', 'neural.save', 'neural.profile')], [['scikit-learn']] * 3)
d = NN.spec_of({})
check('JMP\'s Model Launch defaults: Holdback 0.3333, three TanH nodes in one layer, no boosting, Squared, one tour',
      (d['method'], d['portion'], d['activation'], d['n1'], d['n2'], d['boost'], d['penalty'], d['tours'], d['transform']), ('holdback', 0.3333, 'tanh', 3, 0, 0, 'squared', 1, False))
check('the learning rate (JMP\'s default 0.1) counts only with boosting', (NN.spec_of({'boost': 5})['rate'], d['rate']), (0.1, None))
check('scikit-learn\'s max_iter default is the Maximum Iterations\' default', d['max_iter'], MLPRegressor().max_iter)
check('JMP\'s model names', [NN.name_of(NN.spec_of(m)) for m in ({}, {'n1': 3, 'n2': 2}, {'n1': 2, 'boost': 10}, {'activation': 'identity', 'n1': 4}, {'activation': 'relu', 'n1': 2}, {'activation': 'logistic', 'n1': 1})],
      ['NTanH(3)', 'NTanH(3)NTanH2(2)', 'NTanH(2)NBoost(10)', 'NLinear(4)', 'NReLU(2)', 'NLogistic(1)'])
check('boosting takes one layer: a second is ignored (JMP)', NN.spec_of({'boost': 4, 'n2': 3})['n2'], 0)
check('JMP\'s second layer is next to the X\'s: scikit-learn\'s first', NN._layers(NN.spec_of({'n1': 3, 'n2': 2})), (2, 3))
for bad, word in (({'robust': True}, 'Robust Fit'), ({'penalty': 'absolute'}, 'Absolute'), ({'penalty': 'weight_decay'}, 'Weight Decay'), ({'activation': 'gaussian'}, 'gaussian'),
                  ({'portion': 1}, 'Holdback Proportion'), ({'n1': 0}, 'first layer'), ({'rate': 0, 'boost': 2}, 'Learning Rate'), ({'tours': 1.5}, 'whole number'), ({'method': 'kfold', 'folds': 1}, 'Folds')):
    r = fit(bad)
    check(f'refused: {bad} ({word})', 'error' in r and word.lower() in r['error'].lower(), True)
r = fit({'robust': True})
check('Robust Fit says scikit-learn has no least absolute deviations', 'scikit-learn' in r['error'] and 'squared error' in r['error'], True)
check('random states from the seed, the tour and the base model', (NN._rs(SEED, 0), NN._rs(SEED, 1), NN._rs(SEED, 0, 3)), (rs_of(SEED, 0), rs_of(SEED, 1), rs_of(SEED, 0, 3)))

# ---- one continuous response: scikit-learn called directly ------------------------------------------
res = fit()
check('a model: no error, JMP\'s name', (res.get('error'), res['name']), (None, 'NTanH(3)'))
P = pv.prepare(T, 'y', XS, portion=0.3333, seed=SEED)
tr = P.train()
check('Holdback: 0.3333 of the rows validate, drawn from the seed (predictive.prepare)', (sets_of(res).tolist(), int((P.sets == 1).sum())), (P.sets.tolist(), round(0.3333 * n)))
net = res['nets'][0]
check('the random_state is the seed\'s', net['random_states'], [rs_of(SEED, 0)])
alphas = alphas_of(net)
check('the penalty path starts with almost no penalty and goes up (JMP starts at none)', alphas[0] == NN.GRID[0] and alphas == list(NN.GRID[:len(alphas)]), True)
pred, est, mu, sd = replay_cont(P, [P.target], P.X, tr, alphas, (3,), 'tanh', rs_of(SEED, 0))
check.near('the predictions are scikit-learn\'s MLPRegressor, replayed here (Pipeline of StandardScaler, the path warm-started)', mx(predicted(res), pred[:, 0]), 0.0, abs_=1e-10)
path = net['path']
ch = [i for i, r in enumerate(path) if r['chosen']]
check('one alpha is chosen: the one with the smallest validation -LogLikelihood on the path', (len(ch), ch[0] == int(np.argmin([r['valid'] for r in path]))), (1, True))
tail = path[ch[0] + 1:]
check('the path stops after two steps that do not improve (or at the end of the grid)', (len(tail) == 2 and all(r['valid'] >= path[ch[0]]['valid'] for r in tail)) or len(path) == len(NN.GRID), True)
va = P.sets == 1
check.near('the path\'s validation -LogLikelihood is the normal likelihood with variance SSE/N', path[ch[0]]['valid'], nll_cont(P.target[va], pred[va, 0]), rel=1e-9)
M = measures(res)
for k, name in enumerate(pv.SETS[:2]):
    m = P.sets == k
    check.near(f'{name}: RSquare = sklearn r2_score of the replayed fit', M[name]['rsquare'], metrics.r2_score(P.target[m], pred[m, 0]), rel=1e-9)
check('the iterations reported are the chosen fit\'s', net['iterations'], int(est[-1].n_iter_))
check.near('the alpha reported is the chosen one', net['alpha'], alphas[-1], rel=0)

# the Estimates written out: the forward pass on the columns' own scale
def forward(estimates, X, feats, act, layers_names, outs):
    E = {r['parameter']: r['estimate'] for r in estimates}
    f = {'tanh': np.tanh, 'logistic': lambda a: 1 / (1 + np.exp(-a)), 'relu': lambda a: np.maximum(a, 0), 'identity': lambda a: a}[act]
    h = X
    ins = feats
    for lname, nk in layers_names:
        nodes = [f'{lname}_{i + 1}' for i in range(nk)]
        h = f(np.column_stack([E[f'{o}:Intercept'] + sum(E[f'{o}:{a}'] * h[:, j] for j, a in enumerate(ins)) for o in nodes]))
        ins = nodes
    return np.column_stack([E[f'{o}:Intercept'] + sum(E[f'{o}:{a}'] * h[:, j] for j, a in enumerate(ins)) for o in outs])


F = forward(net['estimates'], P.X, P.features, 'tanh', [('H1', 3)], ['y'])
check.near('the Estimates are the network on the columns\' own scale: their forward pass gives the predictions', mx(F[:, 0], pred[:, 0]), 0.0, abs_=1e-9)
check('JMP\'s parameter names: H1_1:x1 ... H1_1:Intercept, y:H1_1 ... y:Intercept',
      [r['parameter'] for r in net['estimates']][:len(P.features) + 1] + [r['parameter'] for r in net['estimates']][-4:],
      [f'H1_1:{a}' for a in P.features] + ['H1_1:Intercept', 'y:H1_1', 'y:H1_2', 'y:H1_3', 'y:Intercept'])
W0 = est[-1].coefs_[0]
check.near('the first layer\'s weights: scikit-learn\'s coefs_ over the StandardScaler\'s scale', mx([r['estimate'] for r in net['estimates'][:len(P.features)]], W0[:, 0] / est[0].scale_), 0.0, abs_=1e-12)
dg = net['diagram']
check('the Diagram: the X columns as inputs (a categorical one with its level columns), one hidden layer, the response',
      ([i['name'] for i in dg['inputs']], dg['inputs'][2]['features'], [h['n'] for h in dg['hidden']], [o['name'] for o in dg['outputs']]), (XS, ['g[a]', 'g[b]', 'g[c]'], [3], ['y']))
check.near('... with the Estimates\' weights on its edges', dg['weights'][0][0][0], net['estimates'][0]['estimate'], rel=1e-12)
check('the same call again comes from the model cache (the same result)', predicted(fit()).tolist(), predicted(res).tolist())
check('another seed draws another holdback and other weights', sets_of(fit(seed=SEED + 1)).tolist() != sets_of(res).tolist(), True)

# ---- closed forms: an identity network with no penalty is least squares; a Freq is a row count --------------
lin = {'activation': 'identity', 'n1': 1, 'penalty': 'none', 'max_iter': 5000}
Xo = np.column_stack([np.ones(n), x1, x2])
r = call('neural.fit', table=T, y=['y'], x=['x1', 'x2'], seed=SEED, model=lin, validation='v')
Pl = pv.prepare(T, 'y', ['x1', 'x2'], validation='v')
ols = sm.OLS(y[Pl.index][Pl.train()], Xo[Pl.index][Pl.train()]).fit()
check.near('NLinear(1), No Penalty: the least squares fit of the training rows (JMP: a linear combination of the X\'s)', mx(predicted(r), ols.predict(Xo[Pl.index])), 0.0, abs_=2e-4)
check('No Penalty: alpha 0, one fit', (r['nets'][0]['alpha'], len(r['nets'][0]['path'])), (0.0, 1))
rf = call('neural.fit', table=T, y=['y'], x=['x1', 'x2'], seed=SEED, model=lin, validation='v', freq='f')
wls = sm.WLS(y[Pl.index][Pl.train()], Xo[Pl.index][Pl.train()], weights=fq[Pl.index][Pl.train()]).fit()
check.near('with Freq: weighted least squares, the frequencies as weights (scikit-learn 1.8\'s sample_weight)', mx(predicted(rf), wls.predict(Xo[Pl.index])), 0.0, abs_=2e-4)
rep = np.repeat(np.arange(n), fq.astype(int))
T_rep = table({'y': list(y[rep]), 'x1': list(x1[rep]), 'x2': list(x2[rep]), 'v': list(vnum[rep])})
rr = call('neural.fit', table=T_rep, y=['y'], x=['x1', 'x2'], seed=SEED, model=lin, validation='v')
first = np.array([np.flatnonzero(rep == i)[0] for i in range(n)])
check.near('... which is the fit of the table with every row repeated Freq times', mx(predicted(rf), np.array(predicted(rr))[first]), 0.0, abs_=3e-4)
check.near('... to the -LogLikelihood of the training rows', measures(rf)['Training']['neg_loglik'], measures(rr)['Training']['neg_loglik'], rel=1e-5)
Pf = pv.prepare(T, 'y', XS, freq='f', portion=0.3333, seed=SEED)
res_f = fit(freq='f')
pf, *_ = replay_cont(Pf, [Pf.target], Pf.X, Pf.train(), alphas_of(res_f['nets'][0]), (3,), 'tanh', rs_of(SEED, 0), w=Pf.w)
check.near('Freq reaches both the StandardScaler and the MLP as sample weights', mx(predicted(res_f), pf[:, 0]), 0.0, abs_=1e-10)
lgt = call('neural.fit', table=T, y=['cls'], x=['x1', 'x2'], seed=SEED, model=lin, validation='v')
sv = call('neural.save', table=T, y=['cls'], x=['x1', 'x2'], seed=SEED, model=lin, validation='v', what='predicteds')
Pc = pv.prepare(T, 'cls', ['x1', 'x2'], validation='v')
logit = sm.Logit((Pc.target == 1).astype(float)[Pc.train()], Xo[Pc.index][Pc.train()]).fit(disp=0)
check.near('NLinear(1), No Penalty, a binary response: logistic regression (JMP: it reduces to it)', mx(np.array(sv['responses'][0]['prob'])[:, 1], logit.predict(Xo)), 0.0, abs_=2e-4)

# ---- two continuous responses: one network ---------------------------------------------------------------------
res2 = fit(y=('y', 'y2'))
P2 = pv.prepare(T, 'y2', XS, portion=0.3333, seed=SEED)
check('two continuous responses: one network, two outputs', ([nt['responses'] for nt in res2['nets']], res2['nets'][0]['diagram']['out_names']), ([['y', 'y2']], ['y', 'y2']))
pred2, est2, mu2, sd2 = replay_cont(P, [P.target, P2.target], P.X, tr, alphas_of(res2['nets'][0]), (3,), 'tanh', rs_of(SEED, 0))
check.near('... MLPRegressor on both, each standardized by its training mean and SD', max(mx(predicted(res2, 0), pred2[:, 0]), mx(predicted(res2, 1), pred2[:, 1])), 0.0, abs_=1e-10)
check('the path\'s likelihood is the sum of the responses\' (JMP sums them)',
      abs(res2['nets'][0]['path'][0]['valid'] - (lambda p: nll_cont(P.target[va], p[va, 0]) + nll_cont(P2.target[va], p[va, 1]))(
          replay_cont(P, [P.target, P2.target], P.X, tr, [NN.GRID[0]], (3,), 'tanh', rs_of(SEED, 0))[0])) < 1e-8, True)
F2 = forward(res2['nets'][0]['estimates'], P.X, P.features, 'tanh', [('H1', 3)], ['y', 'y2'])
check.near('the Estimates\' forward pass gives both responses', mx(F2, pred2), 0.0, abs_=1e-9)
rm = fit(y=('ym', 'y2'))
check('rows missing a response are left out of every network, and said so', (rm['n']['Training'] + rm['n']['Validation'], any('missing one of the responses' in t for t in rm['notes'])), (n - 3, True))

# ---- categorical responses ------------------------------------------------------------------------------------
resb = fit(y=('cls',))
Pb = pv.prepare(T, 'cls', XS, portion=0.3333, seed=SEED)
svb = saved_prob({}, ('cls',))['responses'][0]
Xall, rows_all = Pb.all_rows()
pb, estb = replay_cat(Pb, Pb.X, Pb.train(), alphas_of(resb['nets'][0]), (3,), 'tanh', rs_of(SEED, 0), Xp=Xall)
check.near('a binary response: MLPClassifier replayed here, the probabilities clipped off 0 and 1', mx(svb['prob'], pb), 0.0, abs_=1e-12)
pbm, _ = replay_cat(Pb, Pb.X, Pb.train(), alphas_of(resb['nets'][0]), (3,), 'tanh', rs_of(SEED, 0))
Mb = measures(resb)
for k, name in enumerate(pv.SETS[:2]):
    m = Pb.sets == k
    check.near(f'{name}: Misclassification Rate = 1 - sklearn accuracy of the replayed fit', Mb[name]['misclassification'], 1 - metrics.accuracy_score(Pb.target[m], pbm[m].argmax(1)), rel=1e-12)
    check.near(f'{name}: AUC = sklearn roc_auc_score', Mb[name]['auc'], metrics.roc_auc_score(Pb.target[m], pbm[m, 1]), rel=1e-12)
E = {r['parameter']: r['estimate'] for r in resb['nets'][0]['estimates']}
check('a binary response has one output, the first level\'s log odds (JMP\'s)', [k for k in E if k.startswith('cls[')], ['cls[hi]:H1_1', 'cls[hi]:H1_2', 'cls[hi]:H1_3', 'cls[hi]:Intercept'])
theta = forward(resb['nets'][0]['estimates'], Pb.X, Pb.features, 'tanh', [('H1', 3)], ['cls[hi]'])[:, 0]
check.near('... whose forward pass gives P(hi) = 1/(1 + exp(-θ))', mx(1 / (1 + np.exp(-theta)), estb.predict_proba(Pb.X)[:, 0]), 0.0, abs_=1e-9)

res3 = fit({'n1': 4}, y=('three',))
P3 = pv.prepare(T, 'three', XS, portion=0.3333, seed=SEED)
sv3 = saved_prob({'n1': 4}, ('three',))['responses'][0]
X3all, _ = P3.all_rows()
p3, est3 = replay_cat(P3, P3.X, P3.train(), alphas_of(res3['nets'][0]), (4,), 'tanh', rs_of(SEED, 0), Xp=X3all)
check.near('three ordered levels: MLPClassifier\'s softmax, replayed', mx(sv3['prob'], p3), 0.0, abs_=1e-12)
check('... Save Predicteds: a Prob column per level and the most likely level', (sv3['names'], sv3['most_name'], sv3['ordinal']), (['Prob[L]', 'Prob[M]', 'Prob[H]'], 'Most Likely three', True))
th3 = forward(res3['nets'][0]['estimates'], P3.X, P3.features, 'tanh', [('H1', 4)], ['three[L]', 'three[M]'])
pp = np.column_stack([np.exp(th3), np.ones(len(th3))])
pp /= pp.sum(1, keepdims=True)
check.near('the log odds against the last level (JMP\'s k - 1 outputs) give the softmax probabilities', mx(pp, est3.predict_proba(P3.X)), 0.0, abs_=1e-9)
M3 = measures(res3)
m = P3.sets == 1
check.near('Validation: Mean -Log p = sklearn log_loss', M3['Validation']['mean_neg_log_p'], metrics.log_loss(P3.target[m], clip(est3.predict_proba(P3.X))[m], labels=[0, 1, 2]), rel=1e-9)
cm = next(c for c in res3['responses'][0]['fit']['confusion'] if c['set'] == 'Validation')
check('the confusion matrix is sklearn\'s', cm['matrix'], metrics.confusion_matrix(P3.target[m], est3.predict_proba(P3.X)[m].argmax(1), labels=[0, 1, 2]).tolist())

resm = fit(y=('y', 'three'))
check('a continuous and a categorical response: a network each (MLPClassifier takes one response)', [(nt['kind'], nt['responses']) for nt in resm['nets']], [('continuous', ['y']), ('categorical', ['three'])])
check('... on the same rows and sets', sets_of(resm).tolist(), P.sets.tolist())
check('... in the order of the responses', [r['y'] for r in resm['responses']], ['y', 'three'])
check.near('... the continuous network is the one fitted alone', mx(predicted(resm), predicted(res)), 0.0, abs_=1e-12)

rcc = fit(y=('cls', 'three'))
check('two categorical responses: a network each', [(nt['kind'], nt['responses']) for nt in rcc['nets']], [('categorical', ['cls']), ('categorical', ['three'])])
check('... the first is the one fitted alone', [m_['misclassification'] for m_ in rcc['responses'][0]['fit']['measures']], [m_['misclassification'] for m_ in resb['responses'][0]['fit']['measures']])
check('... the profiler names each level with its response', [r_['name'] for r_ in call('neural.profile', table=T, y=['cls', 'three'], x=XS, seed=SEED, model={}, grid=5)['responses']],
      ['cls Prob[hi]', 'cls Prob[lo]', 'three Prob[L]', 'three Prob[M]', 'three Prob[H]'])
rd = fit(x=('x1m', 'x2', 'g'), missing='drop')
check('Informative Missing off: the rows missing a factor are left out', (rd.get('error'), rd['n']['Training'] + rd['n']['Validation'], rd['features']), (None, n - 15, ['x1m', 'x2', 'g[a]', 'g[b]', 'g[c]']))
ri = fit(x=('x1m', 'x2', 'g'))
check('Informative Missing on: a Missing column for x1m', ri['features'], ['x1m', 'x1m Missing', 'x2', 'g[a]', 'g[b]', 'g[c]'])
check('a response among the factors is left out of them', fit(x=('y', 'x1', 'x2', 'g'))['x'], XS)
check('no factor but the response: refused', 'error' in fit(x=('y',)), True)

# ---- probabilities never exactly 0 or 1 --------------------------------------------------------------------------
sep = {'penalty': 'none', 'max_iter': 3000, 'n1': 3}
Tsep = table({'x': list(np.linspace(-3, 3, 80)), 'c': ['lo' if v < 0 else 'hi' for v in np.linspace(-3, 3, 80)]}, types={'c': 'nominal'})
ss = call('neural.save', table=Tsep, y=['c'], x=['x'], seed=1, model=sep, what='predicteds')['responses'][0]
pr_ = np.array(ss['prob'])
check('separable classes, No Penalty: every probability strictly between 0 and 1', bool(np.all((pr_ > 0) & (pr_ < 1))), True)
check('... yet the classes are told apart', ss['most_likely'][:3] + ss['most_likely'][-3:], ['lo', 'lo', 'lo', 'hi', 'hi', 'hi'])

# ---- KFold, as JMP chooses the model ------------------------------------------------------------------------------
K = 4
resk = fit({'method': 'kfold', 'folds': K})
Pk = pv.prepare(T, 'y', XS)
nk = len(Pk.index)
fold = np.empty(nk, dtype=int)
fold[np.random.default_rng(SEED).permutation(nk)] = np.arange(nk) % K
alph = alphas_of(resk['nets'][0])
fits = []
for k in range(K):
    trk = fold != k
    pk, *_ = replay_cont(Pk, [Pk.target], Pk.X, trk, alph, (3,), 'tanh', rs_of(SEED, 0))
    fits.append(pk[:, 0])
vals = [nll_cont(Pk.target[fold == k], fits[k][fold == k]) for k in range(K)]
alls = [nll_cont(Pk.target, fits[k]) for k in range(K)]
kbest = int(np.argmin(alls))
check('KFold: the folds from the seed\'s permutation', [r['rows'] for r in resk['folds']], [int((fold == k).sum()) for k in range(K)])
check.near('... each fold\'s validation -LogLikelihood at the chosen alpha, replayed here', mx([r['valid'] for r in resk['folds']], vals), 0.0, abs_=1e-7)
check.near('... the alpha chosen by the validation likelihood summed over the folds', resk['nets'][0]['path'][len(alph) - 1]['valid'], sum(vals), rel=1e-9)
check('... the model shown is the fold whose model fits every row best (JMP), that fold its validation set',
      (resk['validation']['fold'], sets_of(resk).tolist()), (kbest + 1, (fold == kbest).astype(int).tolist()))
check.near('... and its predictions are that fold\'s model', mx(predicted(resk), fits[kbest]), 0.0, abs_=1e-10)
check('KFold with more folds than rows is refused', 'error' in call('neural.fit', table=table({'y': [1.0, 2, 3], 'x': [1.0, 2, 3]}), y=['y'], x=['x'], seed=1, model={'method': 'kfold', 'folds': 5}), True)

# ---- Excluded Rows Holdback, and Informative Missing's fills ------------------------------------------------------------
held = sorted(rng.choice(n, 60, replace=False).tolist())
rese = fit({'method': 'excluded'}, x=('x1m', 'x2', 'g'), rows=list(range(n)), holdback=held)
Pe = pv.prepare(T, 'y', ['x1m', 'x2', 'g'], rows=list(range(n)))
se = np.isin(Pe.index, held).astype(int)
check('Excluded Rows Holdback: the excluded rows validate, the others train', sets_of(rese).tolist(), se.tolist())
miss = np.isnan(x1m[Pe.index])
fill = float(np.mean(x1m[Pe.index][(se == 0) & ~miss]))
NN._apply_sets(Pe, se)
check.near('Informative Missing: a missing x1m is the mean of the training rows (not of every row)', float(Pe.X[miss, 0][0]), fill, rel=1e-12)
pe, *_ = replay_cont(Pe, [Pe.target], Pe.X, se == 0, alphas_of(rese['nets'][0]), (3,), 'tanh', rs_of(SEED, 0))
check.near('... and the fit is scikit-learn\'s on that design', mx(predicted(rese), pe[:, 0]), 0.0, abs_=1e-10)
r0 = fit({'method': 'excluded'}, rows=list(range(n)), holdback=[])
check('no excluded rows: no validation, and the penalty cannot be chosen (scikit-learn\'s default alpha)', (r0['sets'], r0['nets'][0]['alpha'], any('penalty cannot be chosen' in t for t in r0['notes'])), (['Training'], 1e-4, True))
check('every row excluded is refused', 'error' in fit({'method': 'excluded'}, rows=list(range(n)), holdback=list(range(n))), True)

# ---- a Validation column, with a test set -----------------------------------------------------------------------------
resv = fit({'method': 'kfold'}, validation='vt')
check('a Validation column overrides the method: its training, validation and test rows', (resv['validation']['method'], sets_of(resv).tolist(), resv['sets']), ('column', vnum.astype(int).tolist(), ['Training', 'Validation', 'Test']))
Pv = pv.prepare(T, 'y', XS, validation='vt')
pvv, *_ = replay_cont(Pv, [Pv.target], Pv.X, Pv.train(), alphas_of(resv['nets'][0]), (3,), 'tanh', rs_of(SEED, 0))
check.near('... the test rows choose nothing: the path is judged on the validation rows', resv['nets'][0]['path'][0]['valid'],
           nll_cont(Pv.target[Pv.sets == 1], replay_cont(Pv, [Pv.target], Pv.X, Pv.train(), [NN.GRID[0]], (3,), 'tanh', rs_of(SEED, 0))[0][Pv.sets == 1, 0]), rel=1e-9)
check.near('... and the fit is replayed here', mx(predicted(resv), pvv[:, 0]), 0.0, abs_=1e-10)
Mv = measures(resv)
m = Pv.sets == 2
check.near('Test: RSquare of the test rows', Mv['Test']['rsquare'], metrics.r2_score(Pv.target[m], pvv[m, 0]), rel=1e-9)

# ---- tours ----------------------------------------------------------------------------------------------------------
rest = fit({'tours': 3})
tours = rest['tours']
check('three tours, each from its own random_state', [t['random_state'] for t in tours], [rs_of(SEED, t) for t in range(3)])
best = int(np.argmin([t['criterion'] for t in tours]))
check('the tour with the best validation likelihood is kept', (rest['tour'], [t['chosen'] for t in tours].index(True)), (best + 1, best))
pt, *_ = replay_cont(P, [P.target], P.X, tr, alphas_of(rest['nets'][0]), (3,), 'tanh', rs_of(SEED, best))
check.near('... and its fit is replayed from that random_state', mx(predicted(rest), pt[:, 0]), 0.0, abs_=1e-10)

# ---- two layers, other activations ------------------------------------------------------------------------------------
res22 = fit({'n1': 3, 'n2': 2})
p22, est22, *_ = replay_cont(P, [P.target], P.X, tr, alphas_of(res22['nets'][0]), (2, 3), 'tanh', rs_of(SEED, 0))
check.near('two layers: hidden_layer_sizes (second, first), replayed', mx(predicted(res22), p22[:, 0]), 0.0, abs_=1e-10)
names22 = [r['parameter'] for r in res22['nets'][0]['estimates']]
check('... JMP\'s names: H2_ next to the X\'s, H1_1:H2_1, y:H1_1', ('H2_1:x1' in names22, 'H1_1:H2_1' in names22, 'H1_3:H2_2' in names22, 'y:H1_3' in names22, names22[0]), (True, True, True, True, 'H2_1:x1'))
F22 = forward(res22['nets'][0]['estimates'], P.X, P.features, 'tanh', [('H2', 2), ('H1', 3)], ['y'])
check.near('... the forward pass through both layers gives the predictions', mx(F22[:, 0], p22[:, 0]), 0.0, abs_=1e-9)
check('... the Diagram has both layers, the second first', [(h['name'], h['n']) for h in res22['nets'][0]['diagram']['hidden']], [('H2', 2), ('H1', 3)])
for act in ('logistic', 'relu', 'identity'):
    ra = fit({'activation': act, 'n1': 2})
    pa, *_ = replay_cont(P, [P.target], P.X, tr, alphas_of(ra['nets'][0]), (2,), act, rs_of(SEED, 0))
    Fa = forward(ra['nets'][0]['estimates'], P.X, P.features, act, [('H1', 2)], ['y'])
    check.near(f'{act}: replayed, and its Estimates\' forward pass', max(mx(predicted(ra), pa[:, 0]), mx(Fa[:, 0], pa[:, 0])), 0.0, abs_=1e-9)

# ---- Transform Covariates -----------------------------------------------------------------------------------------------
rtf = fit({'transform': True}, x=('x1', 'x3', 'g'))
Pt = pv.prepare(T, 'y', ['x1', 'x3', 'g'], portion=0.3333, seed=SEED)
cont = [0, 1]
ptf = PowerTransformer().fit(Pt.X[Pt.train()][:, cont])
Xt = Pt.X.copy()
Xt[:, cont] = ptf.transform(Pt.X[:, cont])
ptt, *_ = replay_cont(Pt, [Pt.target], Xt, Pt.train(), alphas_of(rtf['nets'][0]), (3,), 'tanh', rs_of(SEED, 0))
check.near('Transform Covariates: PowerTransformer (Yeo-Johnson) on the continuous columns, fitted on the training rows', mx(predicted(rtf), ptt[:, 0]), 0.0, abs_=1e-10)
check('... the transformed columns are named T(x) in the Estimates', [r['parameter'] for r in rtf['nets'][0]['estimates']][:3], ['H1_1:T(x1)', 'H1_1:T(x3)', 'H1_1:g[a]'])
tsave = call('neural.save', table=T, y=['y'], x=['x1', 'x3', 'g'], seed=SEED, model={'transform': True}, what='transformed')
check('Save Transformed Covariates: the transformed continuous columns', [c['name'] for c in tsave['columns']], ['T(x1)', 'T(x3)'])
check.near('... their values', mx(np.array(tsave['columns'][1]['values']), ptf.transform(np.column_stack([x1, x3]))[:, 1]), 0.0, abs_=1e-10)
check('... the skewed column comes out near symmetric', abs(pd.Series(tsave['columns'][1]['values']).skew()) < abs(pd.Series(x3).skew()) / 3, True)

# ---- boosting, by hand ----------------------------------------------------------------------------------------------------
bm = {'n1': 2, 'boost': 6, 'rate': 0.3}
rbo = fit(bm)
nb = rbo['nets'][0]
Y = P.target
wt = np.ones(n)
muB = np.average(Y[tr], weights=wt[tr])
sdB = math.sqrt(np.average((Y[tr] - muB) ** 2, weights=wt[tr]))
Zb = (Y - muB) / sdB
Fb = np.zeros(n)
steps = []
rss = [rs_of(SEED, 0)] + [rs_of(SEED, 0, k) for k in range(1, 6)]
check('boosting: each base model\'s random_state from the seed, the tour and its number', nb['random_states'], rss[:nb['components']])
Kb = nb['components']
prev_v = None
ok_rule = True
for k in range(Kb):
    e = pipe(MLPRegressor, (2,), 'tanh', rss[k])
    for a in (alphas_of(nb) if k == 0 else [nb['alpha']]):
        e.set_params(mlp__alpha=a).fit(P.X[tr], (Zb - Fb)[tr])
    Fb = Fb + (0.3 if k < Kb - 1 else 1.0) * e.predict(P.X)
check.near('the base models fitted in turn to what the scaled sum of those before leaves; the last unscaled (JMP)', mx(predicted(rbo), muB + sdB * Fb), 0.0, abs_=1e-10)
rows_b = nb['boost']
vals_b = [r['valid'] for r in rows_b]
check('the validation likelihood improves with every base model kept', all(b < a for a, b in zip(vals_b[:-1], vals_b[1:])) if all(r['kept'] for r in rows_b) else all(b < a for a, b in zip(vals_b[:Kb - 1], vals_b[1:Kb])), True)
check('a base model that does not improve it ends the boosting', all(r['kept'] for r in rows_b[:Kb]) and (len(rows_b) == Kb or (not rows_b[-1]['kept'] and rows_b[-1]['valid'] >= rows_b[-2]['valid'])), True)
check('the boosted network\'s Estimates: every base model\'s nodes side by side', sum(1 for r in nb['estimates'] if r['parameter'].startswith('y:H1_')), 2 * Kb)
Fbo = forward(nb['estimates'], P.X, P.features, 'tanh', [('H1', 2 * Kb)], ['y'])
check.near('... which as one network give the boosted predictions', mx(Fbo[:, 0], muB + sdB * Fb), 0.0, abs_=1e-9)
rstop = fit({'n1': 1, 'boost': 40, 'rate': 1.0})
check('with many models and a high rate, validation stops the boosting early', rstop['nets'][0]['components'] < 40 and not rstop['nets'][0]['boost'][-1]['kept'], True)

bc = {'n1': 2, 'boost': 4, 'rate': 0.5}
rbc = fit(bc, y=('three',))
nbc = rbc['nets'][0]
L3 = 3
yc = P3.target
Yh = np.eye(L3)[yc]
share = np.array([wt[tr][yc[tr] == j].sum() for j in range(L3)]) / wt[tr].sum()
G = np.tile(np.log(np.clip(share, 1e-15, None)), (n, 1))


def softmax(G):
    Ex = np.exp(G - G.max(axis=1, keepdims=True))
    return Ex / Ex.sum(axis=1, keepdims=True)


Kc = nbc['components']
rows_t = np.flatnonzero(tr)
rhos = []
for k in range(Kc):
    e = pipe(MLPRegressor, (2,), 'tanh', nbc['random_states'][k])
    for a in (alphas_of(nbc) if k == 0 else [nbc['alpha']]):
        e.set_params(mlp__alpha=a).fit(P3.X[tr], (Yh - softmax(G))[tr])
    f = e.predict(P3.X).reshape(G.shape)
    rho = minimize_scalar(lambda r_: -np.sum(np.log(np.clip(softmax(G[rows_t] + r_ * f[rows_t])[np.arange(len(rows_t)), yc[rows_t]], 1e-15, None))), bounds=(0.0, 100.0), method='bounded').x
    rhos.append(rho)
    G = G + (0.5 * rho if k < Kc - 1 else rho) * f
pc = clip(softmax(G))
svc = saved_prob(bc, ('three',))['responses'][0]
check.near('a categorical response boosted on the log-odds scale: the gradient fitted, a line search, replayed here', mx(np.array(svc['prob'])[P3.index], pc), 0.0, abs_=1e-10)
check.near('... the steps of the line search', mx(nbc['steps'], rhos), 0.0, abs_=1e-12)
thc = forward(nbc['estimates'], P3.X, P3.features, 'tanh', [('H1', 2 * Kc)], ['three[L]', 'three[M]'])
ppc = np.column_stack([np.exp(thc), np.ones(n)])
ppc /= ppc.sum(1, keepdims=True)
check.near('... its Estimates are the log odds against the last level of the one network', mx(ppc, softmax(G)), 0.0, abs_=1e-9)

# ---- the warnings ----------------------------------------------------------------------------------------------------
rw = fit({'max_iter': 3})
wl = rw.get('warnings') or []
check('an L-BFGS fit stopped at max_iter warns under the report, with the model\'s name', len(wl) == 1 and wl[0].startswith('ConvergenceWarning: Model NTanH(3): lbfgs failed to converge'), True)
check('... only the chosen fit\'s warning, once', sum('failed to converge' in w for w in wl), 1)
rq = call('neural.fit', table=T, y=['y'], x=['x1', 'x2'], seed=SEED, model=lin)
check('a fit that converges gives no warning', rq.get('warnings'), None)

# ---- the profiler ------------------------------------------------------------------------------------------------------
pr = call('neural.profile', table=T, y=['y', 'three'], x=XS, seed=SEED, model={}, current={'x1': 0.5, 'g': 'b'}, grid=11)
check('the profiler: every response (a continuous one, a probability per level)', [r['name'] for r in pr['responses']], ['y', 'three Prob[L]', 'three Prob[M]', 'three Prob[H]'])
f0 = pr['factors'][0]
grid = np.linspace(f0['min'], f0['max'], 11)
Xg = P.encode_settings([{'x1': v, 'x2': pr['factors'][1]['current'], 'g': 'b'} for v in grid])
check.near('a trace: the network\'s prediction as x1 runs over its range, the others at their current values', mx(pr['responses'][0]['traces'][0]['pred'], est.predict(Xg) * sd[0] + mu[0]), 0.0, abs_=1e-10)
check.near('the current value', pr['responses'][0]['current']['pred'], float(est.predict(P.encode_settings([{'x1': 0.5, 'x2': pr['factors'][1]['current'], 'g': 'b'}]))[0] * sd[0] + mu[0]), rel=1e-12)
check('the probabilities of the levels add to 1 along a trace', bool(np.allclose(np.sum([r['traces'][0]['pred'] for r in pr['responses'][1:]], axis=0), 1)), True)
imp = call('neural.importance', table=T, y=['y'], x=XS, seed=SEED, model={}, imp_method='resampled', imp_n=64, imp_seed=1)
check('Assess Variable Importance runs on the model (resampled inputs from the training rows)', 'error' not in imp and bool(imp), True)

# ---- Save Columns ----------------------------------------------------------------------------------------------------------
sp = call('neural.save', table=T, y=['y', 'y2'], x=XS, seed=SEED, model={}, what='predicteds')['responses']
check('Save Predicteds: every response, every row of the table', ([s_['name'] for s_ in sp], [len(s_['rows']) for s_ in sp]), (['Predicted y', 'Predicted y2'], [n, n]))
check.near('... the network\'s predictions', mx(sp[1]['values'], pred2[:, 1]), 0.0, abs_=1e-10)
check.near('... and residuals', mx(sp[0]['residuals'], y - pred2[:, 0]), 0.0, abs_=1e-10)
sh = call('neural.save', table=T, y=['y'], x=XS, seed=SEED, model={}, what='hidden')
Hs = np.tanh(est[0].transform(P.X) @ est[-1].coefs_[0] + est[-1].intercepts_[0])
check('Save Hidden Layer Values: H1_1, H1_2, H1_3 (JMP\'s names)', [c['name'] for c in sh['columns']], ['H1_1', 'H1_2', 'H1_3'])
check.near('... tanh of each node\'s sum', mx(np.column_stack([c['values'] for c in sh['columns']]), Hs), 0.0, abs_=1e-12)
sh2 = call('neural.save', table=T, y=['y'], x=XS, seed=SEED, model={'n1': 3, 'n2': 2}, what='hidden')
check('... two layers: H1 then H2', [c['name'] for c in sh2['columns']], ['H1_1', 'H1_2', 'H1_3', 'H2_1', 'H2_2'])
svd = call('neural.save', table=T, y=['y'], x=XS, seed=SEED, model={}, what='validation')
check('Save Validation: 0 training, 1 validation, for the rows of the model', (svd['name'], svd['rows'], svd['values']), ('Validation', P.index.tolist(), P.sets.tolist()))
sx = call('neural.save', table=T, y=['y'], x=XS, seed=SEED, model={'method': 'excluded'}, rows=[r_ for r_ in range(n) if r_ not in held[:10]], holdback=[])
check('Save Predicteds reaches rows outside the analysis (excluded ones), as a formula column would', len(sx['responses'][0]['rows']), n)


# ---- the code under a model, on a CSV export ----------------------------------------------------------------------------
def run_code(code, dump):
    with tempfile.TemporaryDirectory() as tmp:
        pd.DataFrame(cols).to_csv(os.path.join(tmp, 'data.csv'), index=False)
        with open(os.path.join(tmp, 'code.py'), 'w') as fh:
            fh.write(code + '\nimport json\nprint("@@" + json.dumps(' + dump + '))\n')
        out = subprocess.run([sys.executable, 'code.py'], cwd=tmp, capture_output=True, text=True, timeout=600)
        if out.returncode:
            print(out.stderr[-3000:])
            return None
        line = [ln for ln in out.stdout.splitlines() if ln.startswith('@@')][-1]
        return json.loads(line[2:]), out.stdout


cases = [
    ('Holdback, one continuous response', dict(model={}), 'pred'),
    ('two continuous responses together', dict(model={}, y=('y', 'y2')), 'pred'),
    ('a binary response', dict(model={}, y=('cls',)), 'proba'),
    ('three levels, four nodes', dict(model={'n1': 4}, y=('three',)), 'proba'),
    ('a continuous and a categorical response', dict(model={}, y=('y', 'three')), 'both'),
    ('KFold', dict(model={'method': 'kfold', 'folds': 4}), 'pred'),
    ('Excluded Rows Holdback, Informative Missing', dict(model={'method': 'excluded'}, x=('x1m', 'x2', 'g'), rows=list(range(n)), holdback=held), 'pred'),
    ('a Validation column with a test set, Freq', dict(model={}, validation='vt', freq='f'), 'pred'),
    ('Transform Covariates, two layers, three tours', dict(model={'transform': True, 'n1': 3, 'n2': 2, 'tours': 3}, x=('x1', 'x3', 'g')), 'pred'),
    ('boosting a continuous response', dict(model=bm), 'pred'),
    ('boosting a categorical response', dict(model=bc, y=('three',)), 'proba'),
    ('the rows of a By group', dict(model={'n1': 2}, rows=list(range(0, n, 2))), 'pred'),
    ('No Penalty, ReLU', dict(model={'penalty': 'none', 'activation': 'relu'}), 'pred'),
    ('two categorical responses (the code\'s proba is the last one\'s)', dict(model={}, y=('cls', 'three')), 'proba'),
    ('a numeric nominal response, Informative Missing off', dict(model={}, y=('k',), x=('x1m', 'x2', 'g'), missing='drop'), 'proba'),
]
for label, kw, what in cases:
    kw = dict(kw)
    ys = kw.pop('y', ('y',))
    xs = kw.pop('x', XS)
    model = kw.pop('model')
    rc = fit(model, y=ys, x=xs, **kw)
    dump = {'pred': '{"pred": pred.tolist(), "index": d.index.tolist()}', 'proba': '{"proba": proba.tolist(), "index": d.index.tolist()}',
            'both': '{"pred": pred.tolist(), "proba": proba.tolist(), "index": d.index.tolist()}'}[what]
    got = run_code(rc['code'], dump)
    if got is None:
        check(f'the code runs: {label}', False, True)
        continue
    got, stdout = got
    idx = got['index']
    ok = True
    if what in ('pred', 'both'):
        cont_j = [j for j, r_ in enumerate(rc['responses']) if r_['kind'] == 'continuous']
        for c_, j in enumerate(cont_j):
            resid = rc['responses'][j]['fit']['residuals']
            ok &= resid['rows'] == idx and mx(np.array(got['pred'])[:, c_], resid['predicted']) < 1e-9
    if what in ('proba', 'both'):
        sv_ = call('neural.save', table=T, y=list(ys), x=list(xs), seed=SEED, model=model, what='predicteds', **kw)
        cat_s = [s_ for s_ in sv_['responses'] if 'prob' in s_][-1]
        pos = {r_: i for i, r_ in enumerate(cat_s['rows'])}
        ok &= mx(np.array(got['proba']), np.array(cat_s['prob'])[[pos[r_] for r_ in idx]]) < 1e-9
    check(f'the code gives the report\'s model: {label}', bool(ok), True)
    if label.startswith('Holdback'):
        line = [ln for ln in stdout.splitlines() if ln.startswith('Validation RSquare')]
        check.near('... and prints the validation RSquare of the report (to numpy\'s eight digits)', float(line[0].split('[')[1].split(']')[0]), measures(rc)['Validation']['rsquare'], rel=1e-7)

sys.exit(check.done())
