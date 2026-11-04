"""More statistics, run natively (CPython with numpy, scipy, statsmodels and
scikit-learn, the last two as references only): lasso and elastic net
against scikit-learn, stepwiselm, anovan (types 1, 2 and 3) and manova1
against statsmodels, bootci, ansaribradley against SciPy, the copulas
(their rank correlations, densities and fits), the designs of
experiments, the hidden Markov model functions against brute-force
enumeration, coxphfit against statsmodels' PHReg, feature selection, and
the plots of many variables.

    python3 test_statsmore.py          (from any folder)
"""
import asyncio
import itertools
import math
import os
import sys
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
warnings.filterwarnings('ignore')
PRESET = {}


def run(code):
    R.BASE.clear()
    R.BASE.update(PRESET)
    R.take_output()
    asyncio.run(R.execute(code))
    return dict(R.BASE), R.take_output()


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()


def a(x):
    if isinstance(x, tuple):
        return np.concatenate([np.asarray(v, dtype=float).reshape(-1) for v in x])
    return np.asarray(x, dtype=float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 8).tolist() if g.size < 30 else g.shape}, want {np.round(w, 8).tolist() if w.size < 30 else w.shape}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)


rs = np.random.RandomState(11)
X = rs.randn(80, 5)
y = 3 * X[:, 0] - 2 * X[:, 2] + 0.5 * rs.randn(80)
PRESET.update({'X': X, 'y': y.reshape(-1, 1)})

# ---- lasso -----------------------------------------------------------------------------------------------------------------------------
from sklearn.linear_model import ElasticNet, Lasso  # noqa: E402
W, _ = run("[B, F] = lasso(X, y, 'Lambda', [0.05 0.3], 'Standardize', false, 'RelTol', 1e-10); b0 = F.Intercept; "
           "[Be, Fe] = lasso(X, y, 'Alpha', 0.5, 'Lambda', 0.2, 'Standardize', false, 'RelTol', 1e-10); be0 = Fe.Intercept; "
           "[Bp, Fp] = lasso(X, y); L = Fp.Lambda; df = Fp.DF; rng(3); [Bc, Fc] = lasso(X, y, 'CV', 5); i1 = Fc.Index1SE; im = Fc.IndexMinMSE;")
for k, lam in enumerate((0.05, 0.3)):
    sk = Lasso(alpha=lam, tol=1e-12, max_iter=100000).fit(X, y)
    near(f'lasso, lambda {lam}: 1/(2n)|y - b0 - Xb|^2 + lambda|b|_1 (scikit-learn Lasso)', (a(W['B'])[:, k], a(W['b0']).reshape(-1)[k]), (sk.coef_, sk.intercept_), 1e-7)
en = ElasticNet(alpha=0.2, l1_ratio=0.5, tol=1e-12, max_iter=100000).fit(X, y)
near("elastic net, 'Alpha' 0.5 (scikit-learn ElasticNet, l1_ratio)", (W['Be'], W['be0']), (en.coef_.reshape(-1, 1), en.intercept_), 1e-7)
L = a(W['L']).reshape(-1)
C('the path: 100 lambdas, ascending, geometric, the largest giving no predictors', L.size == 100 and np.all(np.diff(L) > 0) and np.allclose(L[0] / L[-1], 1e-4)
  and a(W['df']).reshape(-1)[-1] == 0 and a(W['df']).reshape(-1)[0] == 5, (L[0], L[-1]))
B1 = a(W['Bc'])[:, int(W['i1']) - 1]
C("cross-validated: the one-standard-error lambda keeps x1 and x3, at most a small rest", abs(B1[0]) > 2 and abs(B1[2]) > 1 and np.sum(np.abs(B1[[1, 3, 4]])) < 0.3 and W['i1'] >= W['im'], B1)

# ---- stepwise regression ------------------------------------------------------------------------------------------------------------------
W, out = run("m = stepwiselm(X, y, 'constant', 'Upper', 'linear'); f = m.Formula; c = m.Coefficients;")
C('stepwiselm: x1 and x3 added, by their F tests, and nothing else', '1. Adding x1' in out and '2. Adding x3' in out and '3.' not in out, out)
W, out = run("m = stepwiselm(X, y, 'linear', 'Upper', 'linear', 'Verbose', 0); n = m.NumCoefficients; m2 = stepwiselm(X, y, 'linear'); f2 = m2.Formula;")
C('from a linear model the three idle predictors are removed', W['n'] == 3, W['n'])
C('with interactions allowed (the default upper model), one enters only when its main effects are in', W['f2'].str() in ('y ~ 1 + x1 + x3', 'y ~ 1 + x1 + x3 + x1:x3'), W['f2'])

# ---- n-way ANOVA and MANOVA -----------------------------------------------------------------------------------------------------------
import pandas as pd  # noqa: E402
import statsmodels.api as sm  # noqa: E402
import statsmodels.formula.api as smf  # noqa: E402
import patsy  # noqa: E402
PATSY_ENV = patsy.EvalEnvironment([{'C': patsy.builtins.C, 'Sum': patsy.contrasts.Sum}])
n = 60
g1 = np.tile([1, 2, 3], 20)
g2 = np.repeat([1, 2], 30)
keep = np.ones(n, bool)
keep[[0, 4, 7, 11, 20]] = False             # unbalanced
yy = g1 * 0.8 + (g2 == 2) * 0.5 + (g1 == 3) * (g2 == 2) * 1.0 + rs.randn(n)
df = pd.DataFrame({'y': yy[keep], 'fa': g1[keep], 'fb': g2[keep]})
PRESET.update({'yy': yy[keep].reshape(-1, 1), 'g1': g1[keep].reshape(-1, 1).astype(float), 'g2': g2[keep].reshape(-1, 1).astype(float)})
for ss in (1, 2, 3):
    W, _ = run(f"[p, tbl] = anovan(yy, {{g1, g2}}, 'model', 'interaction', 'sstype', {ss}, 'display', 'off'); s1 = tbl{{2, 2}}; s2 = tbl{{3, 2}}; s3 = tbl{{4, 2}};")
    fit = smf.ols('y ~ C(fa, Sum) * C(fb, Sum)', df, eval_env=PATSY_ENV).fit()
    ref = sm.stats.anova_lm(fit, typ=ss)
    near(f'anovan sstype {ss}: the sums of squares and p-values (statsmodels anova_lm)', (W['s1'], W['s2'], W['s3'], W['p']),
         (ref['sum_sq'].iloc[0 if ss != 3 else 1], ref['sum_sq'].iloc[1 if ss != 3 else 2], ref['sum_sq'].iloc[2 if ss != 3 else 3],
          ref['PR(>F)'].iloc[0 if ss != 3 else 1:(3 if ss != 3 else 4)].values.reshape(-1, 1)), 1e-8)
W, out = run("p = anovan(yy, {g1, g2}, 'varnames', {'A', 'B'});")
C('anovan shows its table', 'Analysis of Variance' in out and 'Error' in out and 'A' in out, out[:200])
Y2 = np.column_stack([X[:60, 0] + 0.6 * (g1 == 2), X[:60, 1] - 0.4 * (g1 == 3)])
PRESET.update({'Y2': Y2, 'g': g1.reshape(-1, 1).astype(float)})
W, _ = run("[d, p, st] = manova1(Y2, g); lam = st.lambda;")
Wm = sum((Y2[g1 == c] - Y2[g1 == c].mean(0)).T @ (Y2[g1 == c] - Y2[g1 == c].mean(0)) for c in (1, 2, 3))
Tm = (Y2 - Y2.mean(0)).T @ (Y2 - Y2.mean(0))
near("manova1: Wilks' lambda det(W)/det(T)", a(W['lam']).reshape(-1)[0], np.linalg.det(Wm) / np.linalg.det(Tm), 1e-10)
C('and the dimension of the means found (the effects are there)', W['d'] >= 1, W['d'])

# ---- bootstrap intervals and the Ansari-Bradley test -------------------------------------------------------------------------------------
from scipy import stats as st  # noqa: E402
z = rs.randn(40) + 2
PRESET['z'] = z.reshape(-1, 1)
W, _ = run("rng(1); a = bootci(2000, @mean, z, 'Type', 'norm'); rng(1); b = bootci(2000, @mean, z, 'Type', 'per'); rng(1); c = bootci(2000, @mean, z); "
           "rng(1); d = bootci(2000, {@mean, z}, 'Type', 'cper', 'Alpha', 0.1);")
tci = st.t.interval(0.95, 39, z.mean(), z.std(ddof=1) / math.sqrt(40))
for k in ('a', 'b', 'c'):
    near(f'bootci {k}: near the t interval of the mean', W[k], np.array(tci).reshape(-1, 1), 0.06)
C('a 90% interval is narrower', np.ptp(a(W['d'])) < np.ptp(a(W['b'])), (W['d'], W['b']))
x1, x2 = rs.randn(25), 2.5 * rs.randn(30)
PRESET.update({'x1': x1.reshape(-1, 1), 'x2': x2.reshape(-1, 1)})
W, _ = run("[h, p, s] = ansaribradley(x1, x2); [hr, pr] = ansaribradley(x1, x2, 'Tail', 'right');")
near('ansaribradley: the p-value of scipy.stats.ansari, both tails and one', (W['p'], W['pr']), (st.ansari(x1, x2).pvalue, st.ansari(x1, x2, alternative='greater').pvalue), 1e-10)

# ---- copulas -----------------------------------------------------------------------------------------------------------------------------
for fam, prm in (('Clayton', '2'), ('Gumbel', '2'), ('Frank', '5'), ('Gaussian', '0.6'), ('t', '0.6, 5')):
    W, _ = run(f"rng(4); U = copularnd('{fam}', {prm}, 4000); tau = corr(U(:, 1), U(:, 2), 'type', 'Kendall'); t0 = copulastat('{fam}', {prm.split(',')[0]});")
    near(f"copularnd '{fam}': Kendall's tau of the sample near copulastat's", W['tau'], W['t0'], 0.03)
from scipy.integrate import dblquad  # noqa: E402
for fam, prm in (('Clayton', 2.0), ('Frank', 5.0), ('Gumbel', 2.0)):
    W, _ = run(f"u = [0.3 0.6; 0.7 0.2; 0.5 0.5]; c = copulapdf('{fam}', u, {prm}); h = 1e-5; "
               f"d = (copulacdf('{fam}', u + h, {prm}) - copulacdf('{fam}', [u(:, 1) + h, u(:, 2) - h], {prm}) - copulacdf('{fam}', [u(:, 1) - h, u(:, 2) + h], {prm}) + copulacdf('{fam}', u - h, {prm})) / (4*h^2);")
    near(f'copulapdf {fam}: the mixed derivative of copulacdf', W['c'], W['d'], 1e-4)
W, _ = run("u = [0.3 0.6; 0.7 0.2]; c = copulapdf('Gaussian', u, 0.5); cdf = copulacdf('Gaussian', u, 0.5);")
zz = st.norm.ppf([[0.3, 0.6], [0.7, 0.2]])
ref = st.multivariate_normal([0, 0], [[1, 0.5], [0.5, 1]]).pdf(zz) / np.prod(st.norm.pdf(zz), 1)
near('Gaussian copula: its density and distribution function', (W['c'], W['cdf']), (ref.reshape(-1, 1), st.multivariate_normal([0, 0], [[1, 0.5], [0.5, 1]]).cdf(zz).reshape(-1, 1)), 1e-6)
W, _ = run("rng(5); U = copularnd('Clayton', 3, 3000); a = copulafit('Clayton', U); rng(6); G = copularnd('Gaussian', 0.7, 3000); r = copulafit('Gaussian', G); "
           "p1 = copulaparam('Clayton', 0.6); p2 = copulaparam('Gumbel', 0.5); p3 = copulaparam('Frank', copulastat('Frank', 4));")
near('copulafit: Clayton 3 and Gaussian 0.7 back from samples', (W['a'], a(W['r'])[0, 1]), (3, 0.7), 0.15)
near('copulaparam inverts copulastat', (W['p1'], W['p2'], W['p3']), (3, 2, 4), 1e-6)

# ---- designs of experiments ---------------------------------------------------------------------------------------------------------------
W, _ = run("a = fullfact([2 3]); b = ff2n(3); c = fracfact('a b c abc'); d = bbdesign(3); [e, blk] = ccdesign(2); f = ccdesign(3, 'type', 'faced', 'center', 2); C = candgen(2, 'quadratic');")
near('fullfact: the first factor fastest', a(W['a']), [[1, 1], [2, 1], [1, 2], [2, 2], [1, 3], [2, 3]])
near('ff2n: binary counting', a(W['b']), list(itertools.product([0, 1], repeat=3)))
cc = a(W['c'])
C('fracfact a b c abc: the fourth column the product of the first three, eight runs, orthogonal', cc.shape == (8, 4) and np.allclose(cc[:, 3], cc[:, :3].prod(1)) and np.allclose(cc.T @ cc, 8 * np.eye(4)), cc)
dd = a(W['d'])
C('bbdesign(3): the twelve edge midpoints of the cube and a centre', dd.shape == (13, 3) and np.all(np.sum(dd[:12] != 0, 1) == 2) and np.all(dd[12] == 0), dd.shape)
e = a(W['e'])
near('ccdesign(2): corners, axial points at sqrt(2) (rotatable), two centres', (e.shape, np.max(np.abs(e[4:8]))), ((10, 2), math.sqrt(2)), 1e-12)
C("ccdesign 'faced': axial points on the faces", np.max(np.abs(a(W['f']))) == 1 and a(W['f']).shape == (16, 3), a(W['f']).shape)
near('candgen quadratic: the 3^2 grid', a(W['C']).shape, (9, 2))
W, _ = run("rng(7); [D, Xm] = rowexch(3, 8, 'interaction', 'tries', 5); d1 = det(Xm' * Xm); rng(8); r = candexch(fullfact([3 3]) - 2, 4, 'tries', 3);")
F = np.array(list(itertools.product([-1, 1], repeat=3)), float)
Ff = np.column_stack([np.ones(8), F, F[:, 0] * F[:, 1], F[:, 0] * F[:, 2], F[:, 1] * F[:, 2]])
near('rowexch: 8 runs of the interaction model reach the full factorial\'s determinant (D-optimal)', W['d1'], np.linalg.det(Ff.T @ Ff), 1e-6)
C('candexch picks four rows that make a nonsingular design', np.linalg.matrix_rank((np.array(list(itertools.product([1, 2, 3], repeat=2)))[:, ::-1] - 2)[a(W['r']).astype(int).reshape(-1) - 1]) == 2, W['r'])

# ---- hidden Markov models ---------------------------------------------------------------------------------------------------------------
T = np.array([[0.8, 0.2], [0.3, 0.7]])
E = np.array([[0.6, 0.3, 0.1], [0.1, 0.3, 0.6]])
seq = np.array([1, 3, 3, 2, 1])
PRESET.update({'T': T, 'E': E, 'seq': seq.reshape(1, -1).astype(float)})
paths = list(itertools.product(range(2), repeat=5))


def path_prob(path):
    p, prev = 1.0, 0
    for s_, o_ in zip(path, seq - 1):
        p *= T[prev, s_] * E[s_, o_]
        prev = s_
    return p


probs = np.array([path_prob(pth) for pth in paths])
W, _ = run("[P, lp] = hmmdecode(seq, T, E); v = hmmviterbi(seq, T, E);")
post = np.array([[probs[[pth[t] == k for pth in paths]].sum() for t in range(5)] for k in range(2)]) / probs.sum()
near('hmmdecode: the posterior state probabilities and log P(seq), by enumerating every path (state 1 before the first step)', (W['P'], W['lp']), (post, math.log(probs.sum())), 1e-12)
near('hmmviterbi: the most probable path', W['v'], np.array(paths[int(np.argmax(probs))]).reshape(1, -1) + 1)
W, _ = run("rng(9); [s, st] = hmmgenerate(3000, T, E); [Te, Ee] = hmmestimate(s, st); [Tt, Et, ll] = hmmtrain(s, [0.6 0.4; 0.4 0.6], [0.5 0.3 0.2; 0.2 0.3 0.5]); dl = diff(ll);")
near('hmmgenerate then hmmestimate: the counts give the model back', (W['Te'], W['Ee']), (T, E), 0.05)
near('hmmtrain (Baum-Welch): the model back from the symbols alone', (W['Tt'], W['Et']), (T, E), 0.08)
C('and its log-likelihood never falls', np.all(a(W['dl']) > -1e-8), a(W['dl'])[:5])

# ---- Cox regression ----------------------------------------------------------------------------------------------------------------------
from statsmodels.duration.hazard_regression import PHReg  # noqa: E402
Xc = rs.randn(60, 2)
tt = np.round(rs.exponential(1, 60) * np.exp(-Xc @ [0.8, -0.5]), 1) + 0.1
cens = rs.random_sample(60) < 0.2
PRESET.update({'Xc': Xc, 'tt': tt.reshape(-1, 1), 'cens': cens.reshape(-1, 1).astype(float)})
for ties in ('breslow', 'efron'):
    W, _ = run(f"[b, ll, H, s] = coxphfit(Xc, tt, 'Censoring', cens, 'Ties', '{ties}'); se = s.se;")
    ph = PHReg(tt, Xc, status=(~cens).astype(int), ties=ties).fit()
    near(f'coxphfit, ties {ties}: the coefficients, standard errors and log partial likelihood (statsmodels PHReg)', (W['b'], W['se'], W['ll']),
         (ph.params.reshape(-1, 1), ph.bse.reshape(-1, 1), ph.llf), 1e-6)

# ---- feature selection ---------------------------------------------------------------------------------------------------------------------
yc = (X[:, 0] - X[:, 2] > 0).astype(float)
PRESET['yc'] = yc.reshape(-1, 1)
W, _ = run("[i1, w1] = relieff(X, yc, 10); [i2, s2] = fscchi2(X, yc); i3 = fscmrmr(X, yc); [i4, w4] = relieff(X, y, 10, 'method', 'regression'); "
           "rng(10); inm = sequentialfs(@(xt, yt, xs, ys) sum(ys ~= predict(fitcdiscr(xt, yt), xs)), X, yc, 'cv', 5);")
for k in ('i1', 'i2', 'i3', 'i4'):
    C(f'{k}: x1 and x3 ranked first', set(a(W[k]).reshape(-1)[:2].astype(int)) == {1, 3}, W[k])
C('sequentialfs: x1 and x3 chosen', set(np.flatnonzero(a(W['inm']).reshape(-1)) + 1) >= {1, 3} and a(W['inm']).sum() <= 3, W['inm'])

# ---- plots of many variables -------------------------------------------------------------------------------------------------------------
W, _ = run("f = figure('Visible', 'off'); h = andrewsplot(X(1:10, :), 'Group', [ones(5, 1); 2*ones(5, 1)]); n1 = numel(h); "
           "clf; h2 = parallelcoords(X(1:10, :), 'Labels', {'a', 'b', 'c', 'd', 'e'}); n2 = numel(h2); xl = xlim; "
           "clf; h3 = probplot(z); xd = h3.XData; yd = h3.YData;")
near('andrewsplot: a line for each group; parallelcoords across the variables', (W['n1'], W['n2'], W['xl']), (2, 1, [[0.5, 5.5]]))
near('probplot: the sorted data against the normal quantiles at (i - 0.5)/n', (W['xd'], W['yd']), (np.sort(z).reshape(1, -1), st.norm.ppf((np.arange(1, 41) - 0.5) / 40).reshape(1, -1)), 1e-12)
raises("lasso([1 2; 3 4], [1 2 3]')", 'as many rows')
raises("copularnd('Joe', 2, 10)", "The family is")
raises("hmmviterbi([1 4], [0.5 0.5; 0.5 0.5], [0.5 0.5; 0.5 0.5])", 'numbered 1 to 2')

raises("ccdesign('abc')", 'not text')
raises("ff2n(40)", 'at most 1048576')
raises("fullfact([1000 1000 1000])", 'at most 1048576')
sys.exit(C.done())
