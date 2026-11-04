"""Regression, curve fitting and features of data, run natively (CPython
with numpy and scipy): linear, robust, generalized linear and nonlinear
models (fitlm, fitglm, fitnlm and the functions before them), curve fits
(fit, fittype, confint, predint, smoothing splines, interpolants, smooth),
local extrema, abrupt changes and trend decomposition. The expected values
come from the formulas worked here with NumPy, from SciPy called directly,
or are worked out by hand.

    python3 test_regression.py          (from any folder)
"""
import asyncio
import itertools
import math
import os
import sys
import tempfile

import numpy as np
import scipy.stats as st
from scipy import interpolate as I
from scipy.optimize import minimize, curve_fit
from scipy.signal import peak_prominences

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-regression-')


def run(code):
    R.BASE.clear()
    R.take_output()
    asyncio.run(R.execute(f"cd('{TMP}');\n" + code))
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
        parts = [np.asarray(v, dtype=float).reshape(-1) for v in x]
        return np.concatenate(parts) if parts else np.zeros(0)
    return np.asarray(x, dtype=float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 6).tolist() if g.size < 30 else g.shape}, want {np.round(w, 6).tolist() if w.size < 30 else w.shape}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)


def text(v):
    return v.str() if isinstance(v, Char) else str(v)


col = lambda v: np.asarray(v, float).reshape(-1, 1)  # noqa: E731
row = lambda v: np.asarray(v, float).reshape(1, -1)  # noqa: E731

# the data most checks share: deterministic, with a little wobble for noise
t = np.arange(1, 21, dtype=float)
x1, x2 = t, np.sin(t)
noise = 0.3 * np.cos(3 * t)
y = 1 + 2 * x1 - 3 * x2 + noise
DATA = "t = (1:20)'; x1 = t; x2 = sin(t); y = 1 + 2*x1 - 3*x2 + 0.3*cos(3*t); X = [x1 x2];"
Xd = np.column_stack([np.ones(20), x1, x2])
b = np.linalg.lstsq(Xd, y, rcond=None)[0]
res = y - Xd @ b
sse = res @ res
dfe = 17
s2 = sse / dfe
cov = s2 * np.linalg.inv(Xd.T @ Xd)
se = np.sqrt(np.diag(cov))
tq = st.t.ppf(0.975, dfe)

# ---- fitlm ----------------------------------------------------------------------------------------------------------
W, out = run(DATA + " mdl = fitlm(X, y); e = mdl.Coefficients.Estimate; s = mdl.Coefficients.SE; ts = mdl.Coefficients.tStat; "
             "pv = mdl.Coefficients.pValue; r2 = mdl.Rsquared.Ordinary; r2a = mdl.Rsquared.Adjusted; rm = mdl.RMSE; d = mdl.DFE; "
             "ll = mdl.LogLikelihood; aic = mdl.ModelCriterion.AIC; nm = mdl.CoefficientNames; cv = mdl.CoefficientCovariance; "
             "rr = mdl.Residuals.Raw; ff = mdl.Fitted; n = mdl.NumObservations;\nmdl")
near('fitlm: estimates, standard errors, t and p as least squares gives them', (W['e'], W['s'], W['ts'], W['pv']),
     (b, se, b / se, 2 * st.t.sf(np.abs(b / se), dfe)), 1e-9)
sst = np.sum((y - y.mean()) ** 2)
ll = -20 / 2 * (math.log(2 * math.pi * sse / 20) + 1)
near('fitlm: R-squared (ordinary, adjusted), RMSE, DFE, log-likelihood, AIC', (W['r2'], W['r2a'], W['rm'], W['d'], W['ll'], W['aic']),
     (1 - sse / sst, 1 - (sse / dfe) / (sst / 19), math.sqrt(s2), dfe, ll, -2 * ll + 6), 1e-9)
same('fitlm: coefficient names from x1, x2', [text(c) for c in W['nm'].a.reshape(-1)], ['(Intercept)', 'x1', 'x2'])
near('fitlm: covariance, residuals, fitted values', (W['cv'], W['rr'], W['ff'], W['n']), (cov, res, Xd @ b, 20), 1e-9)
C('fitlm: shown as a model with its table of estimates', 'Linear regression model:' in out and 'y ~ 1 + x1 + x2' in out and 'Estimate' in out
  and 'R-squared' in out and 'Number of observations: 20' in out, out)

W, _ = run(DATA + " mdl = fitlm(X, y); [yp, yci] = predict(mdl, [3 0.5; 10 -1]); [yo, yoi] = predict(mdl, [3 0.5], 'Prediction', 'observation'); "
           "ci = coefCI(mdl); ci90 = coefCI(mdl, 0.1); [p, F, r] = coefTest(mdl); [p2, F2] = coefTest(mdl, [0 1 0]); "
           "tb = anova(mdl, 'summary'); ss = tb.SumSq; df = tb.DF;")
x0 = np.array([[1, 3, 0.5], [1, 10, -1]])
yp = x0 @ b
hw = tq * np.sqrt(np.einsum('ij,jk,ik->i', x0, cov, x0))
near('predict: values and confidence bounds of the curve', (W['yp'], W['yci']), (yp, np.column_stack([yp - hw, yp + hw])), 1e-9)
hwo = tq * math.sqrt(x0[0] @ cov @ x0[0] + s2)
near("predict 'observation': bounds wider by the residual variance", W['yoi'], row([yp[0] - hwo, yp[0] + hwo]), 1e-9)
near('coefCI at 95 % and at 90 %', (W['ci'], W['ci90']), (np.column_stack([b - tq * se, b + tq * se]), np.column_stack([b - st.t.ppf(0.95, dfe) * se, b + st.t.ppf(0.95, dfe) * se])), 1e-9)
H = np.array([[0, 1, 0], [0, 0, 1]])
Fv = (H @ b) @ np.linalg.solve(H @ cov @ H.T, H @ b) / 2
near('coefTest: the F-test of all slopes 0, and of one (F = t^2)', (W['p'], W['F'], W['r'], W['F2']), (st.f.sf(Fv, 2, dfe), Fv, 2, (b[1] / se[1]) ** 2), 1e-9)
near("anova 'summary': the sums of squares of total, model and residual", (W['ss'], W['df']), ((sst, sst - sse, sse), (19, 2, 17)), 1e-9)

W, _ = run(DATA + " tbl = table(x1, x2, y); m1 = fitlm(tbl, 'y ~ x1*x2'); n1 = m1.CoefficientNames; e1 = m1.Coefficients.Estimate; "
           "m2 = fitlm(X, y, 'quadratic'); n2 = m2.NumCoefficients; m3 = fitlm(tbl, 'y ~ x1 - 1'); e3 = m3.Coefficients.Estimate; "
           "m4 = fitlm(X, y, 'Intercept', false); n4 = m4.CoefficientNames;")
same("fitlm(tbl, 'y ~ x1*x2'): main effects and their product", [text(c) for c in W['n1'].a.reshape(-1)], ['(Intercept)', 'x1', 'x2', 'x1:x2'])
near("the product's estimate as least squares with x1.*x2", W['e1'], col(np.linalg.lstsq(np.column_stack([np.ones(20), x1, x2, x1 * x2]), y, rcond=None)[0]), 1e-8)
near("'quadratic': intercept, 2 linear, 1 product, 2 squares; 'y ~ x1 - 1' through the origin", (W['n2'], W['e3']), (6, x1 @ y / (x1 @ x1)), 1e-9)
same("'Intercept', false leaves the constant out", [text(c) for c in W['n4'].a.reshape(-1)], ['x1', 'x2'])

W, _ = run("g = categorical({'a';'b';'c';'a';'b';'c';'a';'b'}); v = [1;2;3;4;5;6;7;8]; r = [2;5;9;3;6;10;4;7]; tbl = table(g, v, r); "
           "m = fitlm(tbl, 'r ~ v + g'); nm = m.CoefficientNames; e = m.Coefficients.Estimate;")
G = np.array(list('abcabcab'))
Xg = np.column_stack([np.ones(8), G == 'b', G == 'c', np.arange(1, 9)]).astype(float)
same('a categorical predictor: a dummy for each level but the first, terms in the order of the table', [text(c) for c in W['nm'].a.reshape(-1)], ['(Intercept)', 'g_b', 'g_c', 'v'])
near('its estimates as least squares on the dummies', W['e'], col(np.linalg.lstsq(Xg, np.array([2, 5, 9, 3, 6, 10, 4, 7.]), rcond=None)[0]), 1e-9)

W, _ = run(DATA + " w = 1 + mod(t, 3); m = fitlm(X, y, 'Weights', w); e = m.Coefficients.Estimate; s = m.Coefficients.SE;")
wv = 1 + np.mod(t, 3)
sw = np.sqrt(wv)
bw = np.linalg.lstsq(Xd * sw[:, None], y * sw, rcond=None)[0]
s2w = np.sum(wv * (y - Xd @ bw) ** 2) / dfe
near('fitlm with weights: weighted least squares and its standard errors', (W['e'], W['s']), (bw, np.sqrt(np.diag(s2w * np.linalg.inv((Xd * wv[:, None]).T @ Xd)))), 1e-9)


def bisquare_irls(X, yv, tune=4.685):
    """robustfit's algorithm written out: bisquare weights of leverage-adjusted residuals over MAD/0.6745 (p-1 smallest left out)."""
    n, p = X.shape
    bb = np.linalg.lstsq(X, yv, rcond=None)[0]
    h = np.sum(np.linalg.qr(X)[0] ** 2, axis=1)
    adj = 1 / np.sqrt(1 - np.minimum(h, 0.9999))
    for _ in range(50):
        r = (yv - X @ bb) * adj
        s = np.median(np.sort(np.abs(r))[p - 1:]) / 0.6745
        u = r / (tune * s)
        w = (np.abs(u) < 1) * (1 - u ** 2) ** 2
        sw_ = np.sqrt(w)
        bn = np.linalg.lstsq(X * sw_[:, None], yv * sw_, rcond=None)[0]
        if np.max(np.abs(bn - bb)) <= 1e-6 * max(np.max(np.abs(bb)), np.max(np.abs(bn))):
            return bn, w
        bb = bn
    return bb, w


yo = y.copy()
yo[[4, 13]] += [25, -30]
W, _ = run(DATA + " y([5 14]) = y([5 14]) + [25; -30]; [rb, stats] = robustfit(X, y); w = stats.w; m = fitlm(X, y, 'RobustOpts', 'on'); "
           "e = m.Coefficients.Estimate; o = fitlm(X, y); eo = o.Coefficients.Estimate;")
rb, rw = bisquare_irls(Xd, yo)
near('robustfit: bisquare IRLS as written out here', (W['rb'], W['w']), (rb, rw), 1e-6)
C('robustfit: the two outliers get weight 0, the line comes back', np.all(rw[[4, 13]] == 0) and np.max(np.abs(rb - b)) < 0.05, (rb, b))
near("fitlm 'RobustOpts' 'on' as robustfit", W['e'], col(rb), 1e-6)
C('ordinary least squares is pulled away by the outliers', np.max(np.abs(a(W['eo']).reshape(-1) - b)) > 0.3, W['eo'])

W, _ = run(DATA + " m = fitlm(X, y); close all; plotResiduals(m, 'caseorder'); c = get(gca, 'Children'); xc = get(c(1), 'XData'); "
           "figure; plotResiduals(m, 'lagged'); c = get(gca, 'Children'); xl = get(c(1), 'XData'); yl = get(c(1), 'YData'); "
           "figure; plotResiduals(m, 'fitted'); c = get(gca, 'Children'); xf = get(c(1), 'XData'); close all;")
near("plotResiduals 'caseorder', 'lagged' (r(t) against r(t-1)) and 'fitted'", (W['xc'], W['xl'], W['yl'], W['xf']), (t, res[:-1], res[1:], Xd @ b), 1e-9)
raises(DATA + " plotResiduals(fitlm(X, y), 'sideways')", "The plot type is")
W, _ = run(DATA + " [bb, bint, r, rint, stats] = regress(y, [ones(20,1) X]); bb90 = regress(y, [ones(20,1) X], 0.1);")
Fall = ((sst - sse) / 2) / s2
near('regress: estimates, their bounds, residuals, and [R2 F p s2]', (W['bb'], W['bint'], W['r'], W['stats']),
     (b, np.column_stack([b - tq * se, b + tq * se]), res, (1 - sse / sst, Fall, st.f.sf(Fall, 2, dfe), s2)), 1e-9)
C('regress: residual intervals bracket the residuals', np.all(a(W['rint'])[:, 0] <= res + 1e-12) and np.all(a(W['rint'])[:, 1] >= res - 1e-12), W['rint'])

W, _ = run(DATA + " B = ridge(y, X, [0 1 10]); B0 = ridge(y, X, 5, 0);")
Z = (np.column_stack([x1, x2]) - [x1.mean(), x2.mean()]) / [x1.std(ddof=1), x2.std(ddof=1)]
rid = lambda k: np.linalg.solve(Z.T @ Z + k * np.eye(2), Z.T @ (y - y.mean()))  # noqa: E731
r5 = rid(5) / [x1.std(ddof=1), x2.std(ddof=1)]
near('ridge: standardized predictors, one column for each k', W['B'], np.column_stack([rid(0), rid(1), rid(10)]), 1e-9)
near('ridge scaled 0: on the data scale with an intercept first', W['B0'], col(np.concatenate([[y.mean() - np.array([x1.mean(), x2.mean()]) @ r5], r5])), 1e-9)

W, _ = run(DATA + " [rho, pv] = partialcorr([y x1 x2]); r12 = partialcorr(y, x1, x2);")
e_y = y - np.column_stack([np.ones(20), x2]) @ np.linalg.lstsq(np.column_stack([np.ones(20), x2]), y, rcond=None)[0]
e_1 = x1 - np.column_stack([np.ones(20), x2]) @ np.linalg.lstsq(np.column_stack([np.ones(20), x2]), x1, rcond=None)[0]
rho = np.corrcoef(e_y, e_1)[0, 1]
tv = rho * math.sqrt(17 / (1 - rho ** 2))
near('partialcorr: the correlation of residuals with the others held fixed, and its p-value', (W['rho'][0, 1], W['r12'], W['pv'][0, 1]), (rho, rho, 2 * st.t.sf(abs(tv), 17)), 1e-9)
near('partialcorr: 1 down the diagonal, symmetric', (np.diag(W['rho']), W['rho'] - np.asarray(W['rho']).T), (np.ones(3), np.zeros((3, 3))), 1e-12)
W, _ = run(DATA + " pz = partialcorr([y x1], x2);")
near('partialcorr(x, z): the columns of x with each other, z held fixed', W['pz'], np.array([[1, rho], [rho, 1]]), 1e-9)

# ---- generalized linear models --------------------------------------------------------------------------------------
xb = np.linspace(-2, 2, 12)
nb = np.full(12, 10.0)
kb = np.array([1, 1, 2, 2, 3, 5, 4, 6, 7, 8, 9, 9.])
Xb = np.column_stack([np.ones(12), xb])


def nll_binom(beta):
    eta = Xb @ beta
    return -np.sum(kb * eta - nb * np.logaddexp(0, eta))


bh = minimize(nll_binom, np.zeros(2), method='BFGS', options={'gtol': 1e-12}).x
mu = nb / (1 + np.exp(-Xb @ bh))
Wb = mu * (1 - mu / nb)
seb = np.sqrt(np.diag(np.linalg.inv(Xb.T @ (Xb * Wb[:, None]))))
dev = 2 * np.sum(np.where(kb > 0, kb * np.log(kb / mu), 0) + np.where(nb - kb > 0, (nb - kb) * np.log((nb - kb) / (nb - mu)), 0))
W, out = run("x = linspace(-2, 2, 12)'; k = [1 1 2 2 3 5 4 6 7 8 9 9]'; n = 10*ones(12,1); "
             "m = fitglm(x, [k n], 'linear', 'Distribution', 'binomial'); e = m.Coefficients.Estimate; s = m.Coefficients.SE; dv = m.Deviance; "
             "[bg, dg, sg] = glmfit(x, [k n], 'binomial'); [yh, lo, hi] = glmval(bg, [0; 1], 'logit', sg); mp = predict(m, [0; 1]);\nm")
near('fitglm binomial (logit): maximum likelihood, SE from the information, deviance', (W['e'], W['s'], W['dv']), (bh, seb, dev), 1e-6)
near('glmfit as fitglm; glmval the probabilities; predict on the probability scale', (W['bg'], W['dg'], W['yh'], W['mp']),
     (bh, dev, 1 / (1 + np.exp(-(bh[0] + bh[1] * np.array([0, 1])))), 1 / (1 + np.exp(-(bh[0] + bh[1] * np.array([0, 1]))))), 1e-6)
C('fitglm: shown as a generalized linear model', 'Generalized linear regression model:' in out and 'Distribution = Binomial' in out, out)
C('glmval: bounds on both sides of the prediction', np.all(a(W['lo']) > 0) and np.all(a(W['hi']) > 0), (W['lo'], W['hi']))

cp = np.array([2, 3, 6, 7, 8, 9, 10, 12, 15, 20.])
xp = np.arange(1, 11, dtype=float)
Xp = np.column_stack([np.ones(10), xp])
bp = minimize(lambda bb: -np.sum(cp * (Xp @ bb) - np.exp(Xp @ bb)), np.array([1.0, 0.1]), method='BFGS', options={'gtol': 1e-12}).x
mp = np.exp(Xp @ bp)
W, _ = run("x = (1:10)'; c = [2 3 6 7 8 9 10 12 15 20]'; m = fitglm(x, c, 'Distribution', 'poisson'); e = m.Coefficients.Estimate; s = m.Coefficients.SE; "
           "d = m.Deviance; ln = m.Link.Name;")
near('fitglm poisson (log): estimates, SE and deviance', (W['e'], W['s'], W['d']),
     (bp, np.sqrt(np.diag(np.linalg.inv(Xp.T @ (Xp * mp[:, None])))), 2 * np.sum(cp * np.log(cp / mp) - (cp - mp))), 1e-6)
same('fitglm poisson: the log link by default', text(W['ln']), 'log')

# ---- nonlinear regression --------------------------------------------------------------------------------------------
xn = np.linspace(0, 4, 15)
yn = 3 * np.exp(-0.7 * xn) + 0.5 + 0.02 * np.sin(5 * xn)
f_n = lambda x, b1, b2, b3: b1 * np.exp(-b2 * x) + b3  # noqa: E731
popt, pcov = curve_fit(f_n, xn, yn, p0=[1, 1, 0], method='lm', xtol=1e-14, ftol=1e-14)
rn = yn - f_n(xn, *popt)
mse = rn @ rn / 12
Jn = np.column_stack([np.exp(-popt[1] * xn), -popt[0] * xn * np.exp(-popt[1] * xn), np.ones(15)])
covn = mse * np.linalg.inv(Jn.T @ Jn)
W, out = run("x = linspace(0, 4, 15)'; y = 3*exp(-0.7*x) + 0.5 + 0.02*sin(5*x); f = @(b, x) b(1)*exp(-b(2)*x) + b(3); "
             "[beta, R, J, CovB, MSE] = nlinfit(x, y, f, [1 1 0]); ci = nlparci(beta, R, 'Jacobian', J); ci2 = nlparci(beta, R, 'Covar', CovB); "
             "[yp, dl] = nlpredci(f, [1; 2], beta, R, 'Jacobian', J); m = fitnlm(x, y, f, [1 1 0]); e = m.Coefficients.Estimate; s = m.Coefficients.SE;")
near('nlinfit: estimates as curve_fit, residuals, MSE, covariance', (W['beta'], W['R'], W['MSE'], W['CovB']), (popt, rn, mse, covn), 1e-6)
tn = st.t.ppf(0.975, 12)
near('nlparci from the Jacobian and from the covariance', (W['ci'], W['ci2']),
     (np.column_stack([popt - tn * np.sqrt(np.diag(covn)), popt + tn * np.sqrt(np.diag(covn))]),) * 2, 1e-6)
x0n = np.array([1.0, 2.0])
J0 = np.column_stack([np.exp(-popt[1] * x0n), -popt[0] * x0n * np.exp(-popt[1] * x0n), np.ones(2)])
near('nlpredci: predictions and half widths of the curve', (W['yp'], W['dl']), (f_n(x0n, *popt), tn * np.sqrt(np.einsum('ij,jk,ik->i', J0, covn, J0))), 1e-6)
near('fitnlm: the same estimates and SE', (W['e'], W['s']), (popt, np.sqrt(np.diag(covn))), 1e-6)

W, _ = run("rng(7); r = randg(3, 1, 20000); r2 = randg(2, [2 3]); rng(7); q = randg(3, 1, 20000); rs = randg([1 2; 3 4]);")
rv = a(W['r']).reshape(-1)
C('randg: shape 3, scale 1: mean and variance near 3, all positive', abs(rv.mean() - 3) < 0.06 and abs(rv.var() - 3) < 0.15 and rv.min() > 0, (rv.mean(), rv.var()))
C('randg: sizes, a shape per element, and the generator seed', np.shape(W['r2']) == (2, 3) and np.shape(W['rs']) == (2, 2) and np.array_equal(W['r'], W['q']), np.shape(W['rs']))
raises('fitlm([1 2 3]\', [1 2])', '')
raises("fitglm((1:5)', [0 1 0 1 1]', 'Distribution', 'weird')", 'The distribution is')

# ---- curve fits -------------------------------------------------------------------------------------------------------
xc = np.arange(0, 10.5, 0.5)
yc = 2 + 0.5 * xc + 0.3 * xc ** 2 + 0.1 * np.sin(7 * xc)
CDATA = "x = (0:0.5:10)'; y = 2 + 0.5*x + 0.3*x.^2 + 0.1*sin(7*x);"
pc = np.polyfit(xc, yc, 2)
Bc = np.column_stack([xc ** 2, xc, np.ones(21)])
rc = yc - Bc @ pc
s2c = rc @ rc / 18
covc = s2c * np.linalg.inv(Bc.T @ Bc)
tc = st.t.ppf(0.975, 18)
W, out = run(CDATA + " [f, g] = fit(x, y, 'poly2'); f\nc = coeffvalues(f); ci = confint(f); nm = coeffnames(f); k = numcoeffs(f); "
             "v = f(2); fv = feval(f, [2 3]); sse = g.sse; r2 = g.rsquare; ar = g.adjrsquare; rm = g.rmse; d = g.dfe; p1 = f.p1; fo = formula(f);")
near('fit poly2: polyfit\'s coefficients, highest power first', (W['c'], W['p1']), (pc, pc[0]), 1e-9)
near('confint: coefficients -/+ t times their SE', W['ci'], np.vstack([pc - tc * np.sqrt(np.diag(covc)), pc + tc * np.sqrt(np.diag(covc))]), 1e-9)
sstc = np.sum((yc - yc.mean()) ** 2)
near('gof: sse, rsquare, adjrsquare, rmse, dfe', (W['sse'], W['r2'], W['ar'], W['rm'], W['d']),
     (rc @ rc, 1 - rc @ rc / sstc, 1 - (1 - (1 - rc @ rc / sstc)) * 20 / 18, math.sqrt(s2c), 18), 1e-9)
near('f(x) and feval(f, x) evaluate the fit', (W['v'], W['fv']), (np.polyval(pc, 2), np.polyval(pc, [2, 3])), 1e-9)
same('coeffnames, numcoeffs, formula', ([text(c) for c in W['nm'].a.reshape(-1)], W['k'], text(W['fo'])), (['p1', 'p2', 'p3'], 3.0, 'p1*x^2 + p2*x + p3'))
C('a fit is shown with its model and 95 % bounds', 'Linear model Poly2:' in out and 'f(x) = p1*x^2 + p2*x + p3' in out and 'Coefficients (with 95% confidence bounds):' in out, out)

W, _ = run(CDATA + " f = fit(x, y, 'poly2'); [ci, yp] = predint(f, [1; 4]); cf = predint(f, [1; 4], 0.95, 'functional'); "
           "[d1, d2] = differentiate(f, [1; 2]); I = integrate(f, [2; 3], 0);")
x0c = np.column_stack([[1, 16], [1, 4], [1, 1]])
ypc = x0c @ pc
hwc = tc * np.sqrt(np.einsum('ij,jk,ik->i', x0c, covc, x0c) + s2c)
hwf = tc * np.sqrt(np.einsum('ij,jk,ik->i', x0c, covc, x0c))
near('predint: bounds for a new observation, and for the curve', (W['ci'], W['yp'], W['cf']),
     (np.column_stack([ypc - hwc, ypc + hwc]), ypc, np.column_stack([ypc - hwf, ypc + hwf])), 1e-9)
P = np.poly1d(pc)
near('differentiate (first and second) and integrate from 0', (W['d1'], W['d2'], W['I']), (P.deriv()([1, 2]), P.deriv(2)([1, 2]), P.integ()([2, 3]) - P.integ()(0)), 1e-9)

xe = np.arange(0, 10.5, 0.5)
W, _ = run("x = (0:0.5:10)'; ye = 3*exp(-0.4*x); f = fit(x, ye, 'exp1'); c = coeffvalues(f); "
           "g = fit(x, ye + 1, 'a*exp(-b*x)+c', 'StartPoint', [1 1 0]); cg = coeffvalues(g); "
           "h = fit(x, ye + 1, 'a*exp(-b*x)+c', 'StartPoint', [1 1 0], 'Lower', [0 0 1.5], 'Upper', [10 10 10]); ch = coeffvalues(h); "
           "ft = fittype(@(a, b, x) a*x.^b); q = fit(x + 1, 2*(x+1).^1.5, ft, 'StartPoint', [1 1]); cq = coeffvalues(q); "
           "s = fit(x, 2*sin(1.3*x + 0.4), 'sin1'); cs = coeffvalues(s); gg = fit(x, exp(-(x-4).^2/2), 'gauss1'); cgg = coeffvalues(gg); "
           "p = fit(x + 1, 2*(x+1).^1.5, 'power1'); cp = coeffvalues(p); r = fit(x, (1+x)./(2+x), 'rat11'); cr = coeffvalues(r);")
near('fit exp1, a custom text model, a model from a handle: exact data, exact coefficients', (W['c'], W['cg'], W['cq']), ((3, -0.4), (3, 0.4, 1), (2, 1.5)), 1e-6)
C('Lower and Upper bounds are kept (c held at 1.5 or more)', a(W['ch'])[0, 2] >= 1.5 - 1e-12, W['ch'])
near('sin1, gauss1, power1, rat11 from their own start points', (W['cs'], W['cgg'], W['cp'], W['cr']), ((2, 1.3, 0.4), (1, 4, math.sqrt(2)), (2, 1.5), (1, 1, 2)), 1e-6)

W, _ = run(CDATA + " ft = fittype({'x^2', 'x', '1'}); f = fit(x, y, ft); c = coeffvalues(f); nm = coeffnames(ft); "
           "u = fittype('a*u+b', 'independent', 'u', 'coefficients', {'a', 'b'}); fu = fit(x, y, u); cu = coeffvalues(fu); fs = formula(ft);")
near('fittype of terms: a linear model, as poly2', W['c'], row(pc), 1e-9)
same('its coefficients a, b, c and its formula', ([text(c) for c in W['nm'].a.reshape(-1)], text(W['fs'])), (['a', 'b', 'c'], 'a*x^2 + b*x + c'))
near("'independent', 'u': a straight line in u", W['cu'], row(np.polyfit(xc, yc, 1)), 1e-6)

yo = 1 + 2 * xc
yo[[4, 11]] = [40, -20]
W, _ = run("x = (0:0.5:10)'; y = 1 + 2*x; y([5 12]) = [40 -20]; f = fit(x, y, 'poly1'); g = fit(x, y, 'poly1', 'Robust', 'Bisquare'); "
           "h = fit(x, y, 'poly1', 'Robust', 'LAR'); c = [coeffvalues(f); coeffvalues(g); coeffvalues(h)];")
cr = a(W['c'])
C("Robust 'Bisquare' and 'LAR' see through two outliers that pull least squares away",
  np.allclose(cr[1], [2, 1], atol=1e-6) and np.allclose(cr[2], [2, 1], atol=1e-3) and abs(cr[0, 0] - 2) > 0.3, cr)
W, _ = run("x = (0:0.5:10)'; w = 1 + mod(1:21, 3)'; y = 2 + 0.5*x + 0.1*sin(7*x); f = fit(x, y, 'poly1', 'Weights', w); c = coeffvalues(f); "
           "g = fit(x, y, 'poly1', 'Exclude', x > 8); cg = coeffvalues(g);")
wv = 1 + np.mod(np.arange(1, 22), 3)
yw = 2 + 0.5 * xc + 0.1 * np.sin(7 * xc)
near("'Weights' (weighted least squares) and 'Exclude' (points left out)", (W['c'], W['cg']), (np.polyfit(xc, yw, 1, w=np.sqrt(wv)), np.polyfit(xc[xc <= 8], yw[xc <= 8], 1)), 1e-9)

rng = np.random.default_rng(5)
xs_ = np.sort(rng.uniform(0, 10, 40))
ys_ = np.sin(xs_) + 0.2 * rng.standard_normal(40)
np.savetxt(os.path.join(TMP, 'ss.txt'), np.column_stack([xs_, ys_]), fmt='%.17g')
W, out = run("d = load('ss.txt'); x = d(:,1); y = d(:,2); f = fit(x, y, 'smoothingspline', 'SmoothingParam', 0.7); v = f([1; 2.5; 9]); "
             "g = fit(x, y, 'smoothingspline'); vg = g(x); f1 = fit(x, y, 'smoothingspline', 'SmoothingParam', 1); v1 = f1(x); "
             "f0 = fit(x, y, 'smoothingspline', 'SmoothingParam', 0); v0 = f0([0; 5]); g\n")
near('smoothingspline with p: SciPy\'s spline with lambda = (1 - p)/p', W['v'], col(I.make_smoothing_spline(xs_, ys_, lam=0.3 / 0.7)([1, 2.5, 9])), 1e-8)
near('smoothingspline, p by cross-validation: SciPy\'s choice by GCV', W['vg'], col(I.make_smoothing_spline(xs_, ys_)(xs_)), 1e-5)
near('p = 1 interpolates (natural cubic); p = 0 is the least-squares line', (W['v1'], W['v0']), (ys_, np.polyval(np.polyfit(xs_, ys_, 1), [0, 5])), 1e-9)
C('a smoothing spline is shown with its p', 'Smoothing spline:' in out and 'p = 0.' in out, out)
W, _ = run(CDATA + " a = fit(x, y, 'pchipinterp'); b = fit(x, y, 'cubicinterp'); c = fit(x, y, 'linearinterp'); d = fit(x, y, 'nearestinterp'); "
           "q = [0.3; 4.7; 9.9]; v = [a(q) b(q) c(q) d(q)];")
q = np.array([0.3, 4.7, 9.9])
near('interpolants: pchip, cubic (not-a-knot), linear, nearest', W['v'],
     np.column_stack([I.PchipInterpolator(xc, yc)(q), I.CubicSpline(xc, yc)(q), np.interp(q, xc, yc), yc[np.round(q / 0.5).astype(int)]]), 1e-10)

W, _ = run("y = [1 5 2 8 3 9 4 7 6 2]'; m = smooth(y); m3 = smooth(y, 3); r = smooth(1:10); sg = smooth(y, 5, 'sgolay', 2); lw = smooth(y, 5, 'lowess'); yr = (1:20)'; yr(8) = 40; rl = smooth(yr, 7, 'rlowess');")
yv = np.array([1, 5, 2, 8, 3, 9, 4, 7, 6, 2.])
mv = [1, (1 + 5 + 2) / 3, np.mean(yv[0:5]), np.mean(yv[1:6]), np.mean(yv[2:7]), np.mean(yv[3:8]), np.mean(yv[4:9]), np.mean(yv[5:10]), (7 + 6 + 2) / 3, 2]
near('smooth: moving average of 5, the window shrinking at the ends; a column back', (W['m'], W['m3'][1], W['r']), (col(mv), (1 + 5 + 2) / 3, col(np.arange(1, 11))), 1e-12)
from scipy.signal import savgol_filter  # noqa: E402
near("smooth 'sgolay': Savitzky-Golay of degree 2", W['sg'], col(savgol_filter(yv, 5, 2, mode='interp')), 1e-10)
xi = np.arange(1, 11.)
d_ = np.abs(xi - 5)
idx = np.argsort(d_, kind='stable')[:5]
w_ = (1 - (d_[idx] / d_[idx].max()) ** 3) ** 3
A_ = np.column_stack([np.ones(5), xi[idx] - 5])
lw5 = np.linalg.lstsq(A_ * np.sqrt(w_)[:, None], yv[idx] * np.sqrt(w_), rcond=None)[0][0]
near("smooth 'lowess': a tricube-weighted line about each point", a(W['lw'])[4, 0], lw5, 1e-10)
C("smooth 'rlowess': the outlier (40) is pulled back to its neighbours' line", abs(a(W['rl'])[7, 0] - 8) < 0.01 and abs(a(W['rl'])[2, 0] - 3) < 0.01, W['rl'])
W, _ = run("y = [1 5 2 8 3 9 4 7 6 2]'; s3 = smooth(y, 7, 'sgolay', 3); sd = smooth(y, 'sgolay');")
near("smooth(y, span, 'sgolay', degree), and the default span 5 and degree 2", (W['s3'], W['sd']), (col(savgol_filter(yv, 7, 3, mode='interp')), col(savgol_filter(yv, 5, 2, mode='interp'))), 1e-10)

raises("fit((1:3)', (1:3)', 'poly3')", 'fewer data points')
raises("fit([1 2; 3 4; 5 6], [1;2;3], 'poly1')", 'is a curve model')
raises("fit((1:5)', (1:5)', 'nonsense')", 'is no model')
raises("fittype('a*t + b')", 'an expression in x')
raises("fit((1:5)', (1:5)', 'poly1', 'Robust', 'sometimes')", 'Robust is')
raises('confint(3)', 'takes a fit')

# ---- local extrema ---------------------------------------------------------------------------------------------------
A = np.array([1, 3, 2, 5, 5, 5, 1, 4, 4, 0, 2.])
W, _ = run("A = [1 3 2 5 5 5 1 4 4 0 2]; [tf, p] = islocalmax(A); tn = islocalmin(A); [~, pn] = islocalmin(A); fa = islocalmax(A, 'FlatSelection', 'all'); "
           "ff = islocalmax(A, 'FlatSelection', 'first'); fl = islocalmax(A, 'FlatSelection', 'last'); mp = islocalmax(A, 'MinProminence', 3.5); "
           "mx = islocalmax(A, 'MaxNumExtrema', 1); ms = islocalmax(A, 'MinSeparation', 4); c = islocalmax(A'); "
           "M = islocalmax([1 2; 3 1; 2 4; 4 3]); M2 = islocalmax([1 3 2; 0 0 0], 2); sp = islocalmax(A, 'SamplePoints', [0 1 2 3 3.1 3.2 6 7 8 9 10], 'MinSeparation', 3);")
same('islocalmax: peaks at 2, the middle of the flat 5 5 5 and of 4 4 (ends never count)', np.flatnonzero(W['tf']).tolist(), [1, 4, 7])
near('islocalmax: prominences as SciPy\'s', W['p'], row(np.where(np.isin(np.arange(11), [1, 4, 7]), np.r_[0, peak_prominences(A, [1])[0][0], 0, 0, 4, 0, 0, 3, 0, 0, 0], 0)), 1e-12)
same('islocalmin: the troughs at 3, 7 and 10', np.flatnonzero(W['tn']).tolist(), [2, 6, 9])
near('islocalmin prominences as islocalmax of -A', W['pn'], row([0, 0, 1, 0, 0, 0, 3, 0, 0, 2, 0]), 1e-12)
same("'FlatSelection' 'all', 'first', 'last'", (np.flatnonzero(W['fa']).tolist(), np.flatnonzero(W['ff']).tolist(), np.flatnonzero(W['fl']).tolist()),
     ([1, 3, 4, 5, 7, 8], [1, 3, 7], [1, 5, 8]))
same("'MinProminence', 'MaxNumExtrema', 'MinSeparation' (the most prominent kept)", (np.flatnonzero(W['mp']).tolist(), np.flatnonzero(W['mx']).tolist(), np.flatnonzero(W['ms']).tolist()),
     ([4], [4], [4]))
same('a column back for a column; each column of a matrix; along rows', (np.shape(W['c']), a(W['M']).astype(int).tolist(), a(W['M2']).astype(int).tolist()),
     ((11, 1), [[0, 0], [1, 0], [0, 1], [0, 0]], [[0, 1, 0], [0, 0, 0]]))
same("'SamplePoints': separation measured in them", np.flatnonzero(W['sp']).tolist(), [4, 7])

# ---- abrupt changes ---------------------------------------------------------------------------------------------------


def best_cuts(yv, method, thr, kmax=None):
    """Every segmentation tried: least squared residuals (or n*log variance) plus thr per change."""
    n = yv.size
    xs = np.arange(1, n + 1.)
    L = {'mean': 1, 'linear': 2, 'variance': 3}[method]

    def cost(sg, xx):
        if method == 'mean':
            return np.sum((sg - sg.mean()) ** 2)
        if method == 'linear':
            return np.sum((sg - np.polyval(np.polyfit(xx, sg, 1), xx)) ** 2)
        return sg.size * math.log(max(sg.var(), np.var(yv) * 1e-6))
    best = (np.inf, [])
    for k in range(n):
        if kmax is not None and k > kmax:
            break
        for cuts in itertools.combinations(range(1, n), k):
            e = [0, *cuts, n]
            if any(q - p < L for p, q in zip(e[:-1], e[1:])):
                continue
            c = sum(cost(yv[p:q], xs[p:q]) for p, q in zip(e[:-1], e[1:])) + (thr * k if kmax is None else 0)
            if c < best[0] - 1e-9:
                best = (c, list(cuts))
    return best[1]


W, _ = run("y = [ones(1,10) 5*ones(1,10) 2*ones(1,10)] + 0.01*sin(1:30); [tf, s1, s2] = ischange(y); k1 = ischange(y, 'MaxNumChanges', 1); "
           "z = [1:10, 15*ones(1,10), 13:-1:4]; [tz, sl, ic] = ischange(z, 'linear'); c = ischange(y'); "
           "v = [0.1*sin(1:40) 3*sin(41:80)]; tv = ischange(v, 'variance', 'Threshold', 20);")
yy = np.r_[np.ones(10), 5 * np.ones(10), 2 * np.ones(10)] + 0.01 * np.sin(np.arange(1, 31))
same('ischange: changes in the mean where the steps are', np.flatnonzero(W['tf']).tolist(), [10, 20])
near('ischange: the segment means (S1) and variances (S2)', (W['s1'][0, [0, 15, 25]], W['s2'][0, 0]), ((yy[:10].mean(), yy[10:20].mean(), yy[20:].mean()), yy[:10].var(ddof=1)), 1e-12)
same("'MaxNumChanges', 1: the larger step only; a column for a column", (np.flatnonzero(W['k1']).tolist(), np.shape(W['c'])), ([10], (30, 1)))
same("'linear': changes in slope; slopes and intercepts in S1, S2", (np.flatnonzero(W['tz']).tolist(), a(W['sl'])[0, [0, 15, 25]].round(9).tolist(), a(W['ic'])[0, [0, 15, 25]].round(9).tolist()),
     ([10, 20], [1, 0, -1], [0, 15, 34]))
same("'variance': the change from small to large swings", np.flatnonzero(W['tv']).tolist(), [40])
rng = np.random.default_rng(11)
ok = True
for trial in range(12):
    n = int(rng.integers(5, 10))
    yv = np.round(rng.standard_normal(n) * 3, 1)
    for method, thr, kmax in (('mean', 2, None), ('linear', 1, None), ('variance', 1, None), ('mean', 1, 2)):
        opt = f"'Threshold', {thr}" if kmax is None else f"'MaxNumChanges', {kmax}"
        W, _ = run(f"tf = ischange({np.array2string(yv, separator=' ')}, '{method}', {opt});")
        got = np.flatnonzero(W['tf']).tolist()
        want = best_cuts(yv, method, thr, kmax)
        if got != want:
            ok = C(f'ischange {method} {opt} on {yv.tolist()}', False, f'got {got}, want {want}')
C('ischange: the least cost over every segmentation, on 48 small cases (mean, linear, variance, at most k)', ok)
raises("ischange(1:5, 'median')", "'mean', 'variance' or 'linear'")

# ---- trend decomposition ------------------------------------------------------------------------------------------------
tt = np.arange(1, 121.)
sd = 0.05 * tt + 2 * np.sin(2 * np.pi * tt / 12) + 0.1 * np.cos(3 * tt)
W, _ = run("t = (1:120)'; s = 0.05*t + 2*sin(2*pi*t/12) + 0.1*cos(3*t); [LT, ST, R] = trenddecomp(s); [L2, S2, R2] = trenddecomp(s, 'stl', 12); "
           "r = trenddecomp(s'); [L3, S3] = trenddecomp(s, 'ssa', 24);")
LT, ST, R_ = a(W['LT']), a(W['ST']), a(W['R'])
near("trenddecomp 'ssa': the parts add up to the data", LT.reshape(-1) + ST.sum(axis=1) + R_.reshape(-1), sd, 1e-9)
C("'ssa': the long-term trend near 0.05 t; seasonal trends the sine (period 12) and the small cosine, the larger first; nothing left",
  ST.shape == (120, 2) and np.max(np.abs(LT.reshape(-1) - 0.05 * tt)) < 0.15 and np.max(np.abs(ST[:, 0] - 2 * np.sin(2 * np.pi * tt / 12))) < 0.15
  and np.max(np.abs(ST[:, 1] - 0.1 * np.cos(3 * tt))) < 0.02 and np.max(np.abs(R_)) < 1e-9,
  (ST.shape, np.max(np.abs(LT.reshape(-1) - 0.05 * tt)), np.max(np.abs(ST[:, 0] - 2 * np.sin(2 * np.pi * tt / 12)))))
L2, S2, R2 = a(W['L2']).reshape(-1), a(W['S2']).reshape(-1), a(W['R2']).reshape(-1)
near("'stl': the parts add up to the data", L2 + S2 + R2, sd, 1e-9)
C("'stl' with period 12: the seasonal part is the sine, the remainder the small cosine",
  np.max(np.abs(S2[12:-12] - 2 * np.sin(2 * np.pi * tt[12:-12] / 12))) < 0.15 and np.max(np.abs(R2)) < 0.2, (np.max(np.abs(S2[12:-12] - 2 * np.sin(2 * np.pi * tt[12:-12] / 12))), np.max(np.abs(R2))))
same('a row in, rows out', np.shape(W['r']), (1, 120))
W, _ = run("rng(1); t = (1:120)'; s = 0.05*t + 2*sin(2*pi*t/12) + 0.3*randn(120, 1); [LT, ST, R] = trenddecomp(s);")
LT, ST, R_ = a(W['LT']).reshape(-1), a(W['ST']), a(W['R']).reshape(-1)
C("'ssa' with noise: the noise stays in the remainder (singular values under the Gavish-Donoho threshold)",
  ST.shape == (120, 1) and np.max(np.abs(ST[:, 0] - 2 * np.sin(2 * np.pi * tt / 12))) < 0.4 and 0.2 < np.std(R_) < 0.35, (ST.shape, np.std(R_)))
raises("trenddecomp([1 2 NaN 4 5 6])", 'without NaN')
raises("trenddecomp(1:20, 'stl')", 'needs the period')

sys.exit(C.done())
