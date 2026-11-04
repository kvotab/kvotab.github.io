"""Econometrics, run natively (CPython with numpy and scipy): the sample
correlations, the unit-root, stationarity, residual and cointegration tests
against statsmodels; the variance ratio and Phillips-Perron statistics
against their formulas computed here; the likelihood tests and information
criteria; hpfilter against statsmodels; ARIMA models (a pure AR against
least squares, the conditional likelihood's maximum, forecasts and their
errors in closed form, seasonal and ARIMAX models, t innovations), garch,
egarch and gjr (their variance recursions written out here, estimates on
long simulated series, forecasts), and varm against statsmodels' VAR.

statsmodels is a reference only (the page does not use it); the suite says
so and stops when it is missing.

    python3 test_econ.py          (from any folder)
"""
import asyncio
import math
import os
import sys
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

try:
    from statsmodels.tsa.stattools import adfuller, kpss, acf, pacf, ccf, coint
    from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
    from statsmodels.tsa.filters.hp_filter import hpfilter as sm_hp
    from statsmodels.tsa.api import VAR
except ImportError as e:
    print(f'test_econ needs statsmodels as a reference ({e}).')
    sys.exit(1)

R.setup()
warnings.filterwarnings('ignore')


def run(code):
    R.BASE.clear()
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
        return np.concatenate([np.asarray(v, float).reshape(-1) for v in x])
    return np.asarray(x, float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 8).tolist() if g.size < 30 else g.shape}, want {np.round(w, 8).tolist() if np.size(w) < 30 else np.shape(w)}')


def text(v):
    return v.str() if isinstance(v, Char) else str(v)


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = text(W['e'])
    return C(f'refused: {code}', words in msg, msg)


def col(x):
    return f"{np.asarray(x, float).reshape(-1).tolist()}'"


rs = np.random.default_rng(4)
y = np.cumsum(rs.standard_normal(200)) * 0.3 + 0.2 * rs.standard_normal(200)
x = rs.standard_normal(300)
Y2 = np.column_stack([y, 2 * y + x[:200]])

# ---- sample correlations ------------------------------------------------------------------------------------------------------

W, _ = run(f"x = {col(x)}; [r, lags, b] = autocorr(x, 'NumLags', 8, 'NumMA', 2, 'NumSTD', 3); p1 = parcorr(x, 'NumLags', 6); p2 = parcorr(x, 'NumLags', 6, 'Method', 'yule-walker');"
           f"y = {col(y)}; [xc, xl] = crosscorr(x(1:200), y, 'NumLags', 4); r0 = autocorr(x);")
near('autocorr: statsmodels acf', W['r'], acf(x, nlags=8).reshape(-1, 1), 1e-12)
ra = acf(x, nlags=8)
near("autocorr: Bartlett's bounds under MA(2)", W['b'], [[3 * math.sqrt((1 + 2 * np.sum(ra[1:3] ** 2)) / 300)], [-3 * math.sqrt((1 + 2 * np.sum(ra[1:3] ** 2)) / 300)]], 1e-12)
C('autocorr: lags 0 to 20 unless given', a(W['r0']).size == 21 and a(W['lags']).reshape(-1).tolist() == list(range(9)))
near("parcorr: statsmodels pacf by OLS", W['p1'], pacf(x, nlags=6, method='ols').reshape(-1, 1), 1e-12)
near("parcorr 'yule-walker': statsmodels pacf (ywm)", W['p2'], pacf(x, nlags=6, method='ywm').reshape(-1, 1), 1e-12)
cc = ccf(x[:200], y, adjusted=False)
near('crosscorr: y1(t+k) with y2(t) for k >= 0 as statsmodels ccf', a(W['xc']).reshape(-1)[4:], cc[:5], 1e-12)
cc2 = ccf(y, x[:200], adjusted=False)
near('crosscorr: negative lags the other way round', a(W['xc']).reshape(-1)[:4][::-1], cc2[1:5], 1e-12)
W, out = run(f"x = {col(x)}; figure; autocorr(x); ax = gca; t = ax.Title.String; n = numel(ax.Children);")
C('autocorr without outputs: a stem plot with two bounds', text(W['t']) == 'Sample Autocorrelation Function' and W['n'] == 3.0)

# ---- unit roots and stationarity -----------------------------------------------------------------------------------------------

W, _ = run(f"y = {col(y)}; [h, p, s, c, reg] = adftest(y, 'model', 'ARD', 'lags', 2); [h2, p2, s2, c2] = adftest(y, 'model', 'TS', 'lags', [0 1 3]);"
           "[h3, p3, s3, c3] = adftest(y); [h4, p4, s4, c4] = adftest(diff(y), 'model', 'ARD'); cf = reg.coeff;")
r = adfuller(y, maxlag=2, autolag=None, regression='c')
near("adftest 'ARD': statsmodels adfuller's statistic and MacKinnon p-value", (W['s'], W['p']), (r[0], r[1]), 1e-9)
for k, L in enumerate([0, 1, 3]):
    r = adfuller(y, maxlag=L, autolag=None, regression='ct')
    near(f"adftest 'TS', lags {L} (a test for each lag)", (a(W['s2']).reshape(-1)[k], a(W['p2']).reshape(-1)[k]), (r[0], r[1]), 1e-9)
r = adfuller(y, maxlag=0, autolag=None, regression='n')
near("adftest 'AR' (the default, no constant)", (W['s3'], W['p3']), (r[0], r[1]), 1e-9)
from plab.builtins import econtests as ET  # noqa: E402
C('adftest: the critical value is where the p-value is alpha', abs(ET.tau_p(W['c'], 'c') - 0.05) < 1e-9 and W['h'] == (W['s'] < W['c']))
C('adftest: a stationary series rejects the unit root, a random walk does not', W['h4'] is True and W['h'] is False)
near('adftest reg: the regression coefficients', a(W['cf']).reshape(-1)[:2], np.linalg.lstsq(np.column_stack([y[2:-1], np.ones(197), np.diff(y)[1:-1], np.diff(y)[:-2]]), y[3:], rcond=None)[0][:2], 1e-9)
# t2 and F: simulated null distributions, so the rejection rate of random walks is near alpha
rw = np.random.default_rng(11)
hits = {'t2': 0, 'f': 0}
for i in range(120):
    w = np.cumsum(rw.standard_normal(150))
    W, _ = run(f"w = {col(w)}; ht = adftest(w, 'model', 'ARD', 'test', 't2'); hf = adftest(w, 'model', 'ARD', 'test', 'F');")
    hits['t2'] += W['ht'] is True
    hits['f'] += W['hf'] is True
C("adftest 't2' and 'F': random walks rejected about 5% of the time", 1 <= hits['t2'] <= 15 and 1 <= hits['f'] <= 15, str(hits))
W, _ = run(f"y = {col(y)}; [h, p, s, c] = pptest(y, 'model', 'ARD', 'lags', 3); [h2, p2, s2] = pptest(y, 'model', 'TS', 'lags', 2, 'test', 't2');")
# Phillips-Perron written out here
T = y.size - 1
X = np.column_stack([y[:-1], np.ones(T)])
b, *_ = np.linalg.lstsq(X, y[1:], rcond=None)
u = y[1:] - X @ b
s2 = u @ u / (T - 2)
se = math.sqrt(s2 * np.linalg.inv(X.T @ X)[0, 0])
g0 = u @ u / T
lam2 = g0 + 2 * sum((1 - j / 4) * (u[j:] @ u[:-j]) / T for j in range(1, 4))
zt = math.sqrt(g0 / lam2) * (b[0] - 1) / se - (lam2 - g0) * T * se / (2 * math.sqrt(lam2) * math.sqrt(s2))
near('pptest t1: Z(t) written out, with MacKinnon\'s p-value', (W['s'], W['p']), (zt, ET.tau_p(zt, 'c')), 1e-9)
C('pptest t2: a statistic and a p-value', np.isfinite(W['s2']) and 0 < W['p2'] <= 1)
for trend, reg in ((False, 'c'), (True, 'ct')):
    W, _ = run(f"y = {col(y)}; [h, p, s, c] = kpsstest(diff(y), 'lags', 4, 'trend', {str(trend).lower()});")
    r = kpss(np.diff(y), regression=reg, nlags=4)
    near(f"kpsstest {'trend' if trend else 'level'}: statsmodels kpss's statistic and p-value", (W['s'], W['p']), (r[0], r[1]), 1e-9)
near('kpsstest: the 5% critical values of Kwiatkowski et al.', (run("[~, ~, ~, c1] = kpsstest(1:30, 'trend', false); [~, ~, ~, c2] = kpsstest(1:30);")[0]['c1'],
                                                               run("[~, ~, ~, c2] = kpsstest(1:30);")[0]['c2']), (0.463, 0.146))
W, _ = run(f"x = {col(x)}; [h, p, s, c] = lbqtest(x, 'Lags', 10); [h2, p2, s2] = lbqtest(x, 'Lags', [5 10], 'DOF', [3 8]); [ha, pa, sa] = archtest(x, 'Lags', 3);")
lb = acorr_ljungbox(x, lags=[10])
near('lbqtest: statsmodels Ljung-Box', (W['s'], W['p']), (float(lb['lb_stat'].iloc[0]), float(lb['lb_pvalue'].iloc[0])), 1e-10)
lb2 = acorr_ljungbox(x, lags=[5, 10], model_df=2)
near('lbqtest with DOF: the p-values with fewer degrees of freedom', a(W['p2']).reshape(-1), lb2['lb_pvalue'].to_numpy(), 1e-10)
ha = het_arch(x - x.mean(), nlags=3)
near("archtest: statsmodels het_arch (Engle's T*R^2)", (W['sa'], W['pa']), (ha[0], ha[1]), 1e-10)
W, _ = run(f"y = {col(y)}; [h, p, s, c, ratio] = vratiotest(y, 'period', [2 4], 'IID', [true false]); hw = vratiotest({col(np.cumsum(np.random.default_rng(31).standard_normal(500)))});")
r1 = np.diff(y)
Tn = r1.size
mu = r1.mean()
s1 = np.sum((r1 - mu) ** 2) / (Tn - 1)
rq = y[2:] - y[:-2] - 2 * mu
vr2 = np.sum(rq ** 2) / (2 * (Tn - 1) * (1 - 2 / Tn)) / s1
z2 = (vr2 - 1) / math.sqrt(2 * 3 * 1 / (3 * 2 * Tn))
near('vratiotest: the period-2 ratio and the IID statistic of Lo and MacKinlay', (a(W['ratio']).reshape(-1)[0], a(W['s']).reshape(-1)[0]), (vr2, z2), 1e-9)
rq4 = y[4:] - y[:-4] - 4 * mu
vr4 = np.sum(rq4 ** 2) / (4 * (Tn - 3) * (1 - 4 / Tn)) / s1
dd = (r1 - mu) ** 2
theta = sum((2 * (4 - j) / 4) ** 2 * Tn * np.sum(dd[j:] * dd[:-j]) / np.sum(dd) ** 2 for j in range(1, 4))
near('vratiotest: the period-4 ratio and the heteroscedasticity-robust statistic', (a(W['ratio']).reshape(-1)[1], a(W['s']).reshape(-1)[1]),
     (vr4, math.sqrt(Tn) * (vr4 - 1) / math.sqrt(theta)), 1e-9)
C('vratiotest: a random walk is not rejected; noise added to one makes its returns mean-revert (rejected)', W['hw'] is False and bool(np.all(a(W['h']))))
W, _ = run(f"Y = reshape({Y2.reshape(-1, order='F').tolist()}, 200, 2); [h, p, s, c, reg] = egcitest(Y); [h2, p2, s2] = egcitest(Y, 'creg', 'ct', 'lags', 1);")
r = coint(Y2[:, 0], Y2[:, 1], trend='c', maxlag=0, autolag=None)
near("egcitest: statsmodels coint's statistic and p-value", (W['s'], W['p']), (r[0], r[1]), 1e-9)
r = coint(Y2[:, 0], Y2[:, 1], trend='ct', maxlag=1, autolag=None)
near("egcitest 'ct' with a lag", (W['s2'], W['p2']), (r[0], r[1]), 1e-9)
C('egcitest: cointegrated series reject no cointegration', W['h'] is True)

# ---- likelihood tests, information criteria, filters ---------------------------------------------------------------------------

W, _ = run("[aic, bic, ic] = aicbic([-100 -95], [3 5], 50); [h, p, s, c] = lratiotest(-90, -95, 2); [hw, pw, sw] = waldtest([0.5; -0.2], [1 0 0; 0 1 0], diag([0.04 0.01 1]));"
           "[hl, pl, sl] = lmtest([1; 2], [0.5 0; 0 0.25], 2); [aicn, bicn] = aicbic(-100, 3, 50, 'Normalize', true);")
near('aicbic: aic, bic and the other criteria', (W['aic'], W['bic'], W['ic'].get1('aicc'), W['ic'].get1('hqc')),
     ([206, 200], [206 + 3 * math.log(50) - 6, 200 + 5 * math.log(50) - 10], [206 + 24 / 46, 200 + 60 / 44], [200 + 6 * math.log(math.log(50)), 190 + 10 * math.log(math.log(50))]), 1e-12)
near('aicbic Normalize: divided by n', (W['aicn'], W['bicn']), (206 / 50, (200 + 3 * math.log(50)) / 50), 1e-12)
from scipy import stats as SS  # noqa: E402
near('lratiotest: 2*(uLogL - rLogL) against chi-square', (W['s'], W['p'], W['c']), (10, SS.chi2.sf(10, 2), SS.chi2.ppf(0.95, 2)), 1e-12)
near('waldtest: r\'(R C R\')^-1 r', (W['sw'], W['pw']), (0.25 / 0.04 + 0.04 / 0.01, SS.chi2.sf(10.25, 2)), 1e-12)
near("lmtest: score'*C*score", (W['sl'], W['pl']), (0.5 + 1, SS.chi2.sf(1.5, 2)), 1e-12)
W, _ = run(f"y = {col(y)}; [t, c] = hpfilter(y); [t2, c2] = hpfilter([y 2*y], 100); L = lagmatrix([1 2 3 4; 5 6 7 8]', [0 1 -1]);")
cyc, tr = sm_hp(y, 1600)
near('hpfilter: statsmodels hpfilter', (W['t'], W['c']), (tr.reshape(-1, 1), cyc.reshape(-1, 1)), 1e-9)
near('hpfilter: each column, another smoothing', a(W['t2'])[:, 1], 2 * sm_hp(y, 100)[1], 1e-9)
near('lagmatrix: both series at each lag (a lead for -1)', W['L'], [[1, 5, np.nan, np.nan, 2, 6], [2, 6, 1, 5, 3, 7], [3, 7, 2, 6, 4, 8], [4, 8, 3, 7, np.nan, np.nan]])

# ---- ARIMA ----------------------------------------------------------------------------------------------------------------------

z = np.zeros(400)
e = np.random.default_rng(6).standard_normal(400) * 0.7
for t in range(2, 400):
    z[t] = 0.4 + 0.6 * z[t - 1] - 0.25 * z[t - 2] + e[t]
W, out = run(f"y = {col(z)}; [E, C, L, info] = estimate(arima(2, 0, 0), y); c = E.Constant; ar = cell2mat(E.AR); v = E.Variance; [res, V, L2] = infer(E, y); ex = info.exitflag;"
             "S = summarize(E); disp(E.Description)")
Xr = np.column_stack([np.ones(398), z[1:-1], z[:-2]])
br, *_ = np.linalg.lstsq(Xr, z[2:], rcond=None)
ur = z[2:] - Xr @ br
near('arima AR(2): the conditional maximum likelihood is least squares on the lags', (W['c'], W['ar'], W['v']), (br[0], br[1:], ur @ ur / 398), 1e-6)
near('infer: the residuals (the presample NaN) and the same log-likelihood', (a(W['res'])[2:].reshape(-1), W['L2']), (ur, W['L']), 1e-6)
near('estimate: the Gaussian log-likelihood at the estimates', W['L'], -199 * (math.log(2 * math.pi * (ur @ ur / 398)) + 1), 1e-6)
C('estimate: shows the parameters with their standard errors', 'StandardError' in out and 'AR{2}' in out and W['ex'] == 1.0)
C('summarize: the fit as a struct with a table', W['S'].get1('NumEstimatedParameters') == 4.0 and W['S'].get1('Table').n == 4)
Cv = a(W['C'])
seOLS = np.sqrt(np.diag((ur @ ur / 398) * np.linalg.inv(Xr.T @ Xr)))
near('estimate: standard errors near those of least squares', np.sqrt(np.diag(Cv))[:3], seOLS, 2e-2)
m = np.zeros(500)
e = np.random.default_rng(8).standard_normal(500)
for t in range(1, 500):
    m[t] = 0.5 * m[t - 1] + e[t] + 0.4 * e[t - 1]
W, _ = run(f"y = {col(m)}; [E, C, L] = estimate(arima('Constant', 0, 'ARLags', 1, 'MALags', 1), y, 'Display', 'off'); ph = E.AR{{1}}; th = E.MA{{1}}; v = E.Variance;")
from scipy.signal import lfilter  # noqa: E402


def cond_ll(ph, th, ys):
    w = ys[1:] - ph * ys[:-1]
    ee = lfilter([1], [1, th], w)
    s2 = ee @ ee / ee.size
    return -ee.size / 2 * (math.log(2 * math.pi * s2) + 1)


L0 = cond_ll(W['ph'], W['th'], m)
C('arima ARMA(1,1): the conditional likelihood written out here, at its maximum', abs(L0 - W['L']) < 1e-6
  and all(cond_ll(W['ph'] + dp, W['th'] + dq, m) < L0 for dp, dq in ((1e-3, 0), (-1e-3, 0), (0, 1e-3), (0, -1e-3))), f'{L0} {W["L"]}')
C('arima ARMA(1,1): near the true 0.5 and 0.4', abs(W['ph'] - 0.5) < 0.1 and abs(W['th'] - 0.4) < 0.1)
W, _ = run("M = arima('Constant', 1, 'AR', {0.8}, 'Variance', 2); [f, mse] = forecast(M, 4, [3; 5]);"
           "M2 = arima('Constant', 0, 'D', 1, 'MA', {0.5}, 'Variance', 1); [f2, mse2] = forecast(M2, 3, [1; 2; 4]);")
near('forecast AR(1): c + phi*y and the error variance sigma^2*(1 - phi^2h)/(1 - phi^2)', (W['f'], W['mse']),
     ([[1 + 0.8 * 5], [1 + 0.8 * (1 + 0.8 * 5)], [1 + 0.8 * (1 + 0.8 * (1 + 0.8 * 5))], [1 + 0.8 * (1 + 0.8 * (1 + 0.8 * (1 + 0.8 * 5)))]],
      [[2 * (1 - 0.8 ** (2 * h)) / (1 - 0.64)] for h in range(1, 5)]), 1e-12)
# ARIMA(0,1,1): the innovation inferred from Y0 (e(3) = (4 - 2) - 0.5*e(2), e(2) = 1), forecasts flat after one step
near('forecast ARIMA(0,1,1): the innovation inferred from Y0, the MSE 1 + (h-1)(1+theta)^2', (W['f2'], W['mse2']),
     ([[4 + 0.5 * 1.5], [4.75], [4.75]], [[1], [1 + 2.25], [1 + 2 * 2.25]]), 1e-12)
W, _ = run("M = arima('Constant', 0.5, 'AR', {0.5}, 'Variance', 1); rng(1); [y1, e1] = simulate(M, 5, 'NumPaths', 3); rng(1); y2 = simulate(M, 5, 'NumPaths', 3);"
           "rng(2); yl = simulate(M, 20000); m = mean(yl);")
C('simulate: paths from rng, repeatable', a(W['y1']).shape == (5, 3) and np.array_equal(a(W['y1']), a(W['y2'])))
near('simulate: the mean of a long path is c/(1 - phi)', W['m'], 1.0, 0.05)
W, _ = run("S = arima('Constant', 0, 'D', 1, 'Seasonality', 12, 'MALags', 1, 'SMALags', 12, 'MA', {0.4}, 'SMA', {-0.3}, 'Variance', 0.1); p = S.P; q = S.Q;"
           "rng(3); ys = simulate(S, 600); Es = estimate(arima('Constant', 0, 'D', 1, 'Seasonality', 12, 'MALags', 1, 'SMALags', 12), ys, 'Display', 'off');"
           "th = Es.MA{1}; Th = Es.SMA{12}; d = S.Description;")
C('seasonal ARIMA: P counts the differences, Q the seasonal MA', W['p'] == 13.0 and W['q'] == 13.0 and 'Seasonally Integrated with Seasonal MA(12)' in str(W['d'].a[0, 0]))
C('seasonal ARIMA: estimates near 0.4 and -0.3', abs(W['th'] - 0.4) < 0.1 and abs(W['Th'] + 0.3) < 0.1, f"{W['th']} {W['Th']}")
xr = np.random.default_rng(12).standard_normal(400)
ex = np.random.default_rng(13).standard_normal(400)
yx = lfilter([1], [1, -0.5], 2 * xr + ex)
W, _ = run(f"x = {col(xr)}; y = {col(yx)}; E = estimate(arima('ARLags', 1, 'Beta', NaN, 'Constant', 0), y, 'X', x, 'Display', 'off'); b = E.Beta; ph = E.AR{{1}};"
           "[f, m] = forecast(E, 2, y, 'XF', [1; -1]);")
Xb = np.column_stack([yx[:-1], xr[1:]])
cb, *_ = np.linalg.lstsq(Xb, yx[1:], rcond=None)
near('ARIMAX: the predictors in the equation, least squares again', (W['ph'], W['b']), (cb[0], cb[1]), 1e-6)
near('ARIMAX forecast: the predictors given for the forecasts', W['f'], [[cb[0] * yx[-1] + cb[1]], [cb[0] * (cb[0] * yx[-1] + cb[1]) - cb[1]]], 1e-5)
tt = SS.t.rvs(6, size=3000, random_state=21) * math.sqrt(4 / 6)
W, _ = run(f"y = {col(tt)}; E = estimate(arima('Constant', 0, 'Distribution', 't'), y, 'Display', 'off'); nu = E.Distribution.DoF; v = E.Variance; [~, ~, L] = infer(E, y);")
near('arima t: the log-likelihood is the t density scaled to the variance', W['L'],
     np.sum(SS.t.logpdf(tt / math.sqrt(W['v'] * (W['nu'] - 2) / W['nu']), W['nu']) - 0.5 * math.log(W['v'] * (W['nu'] - 2) / W['nu'])), 1e-9)
C('arima t: the degrees of freedom and variance near 6 and 1', abs(W['nu'] - 6) < 1.5 and abs(W['v'] - 1) < 0.1, f"{W['nu']} {W['v']}")
W, _ = run("y = impulse(arima('AR', {0.5}, 'MA', {0.4}, 'Constant', 0, 'Variance', 1), 5);")
near('impulse: the MA weights 1, phi + theta, phi*(phi + theta) ...', W['y'], [[1], [0.9], [0.45], [0.225], [0.1125]], 1e-12)
W, _ = run("[yc, tc] = impulse(tf(1, [1 1]), 2); e = max(abs(yc - exp(-tc)));")
C("impulse of a transfer function: still control's (e^-t for 1/(s+1))", W['e'] < 1e-9 and a(W['tc']).size > 10)

# ---- conditional variance models -------------------------------------------------------------------------------------------------


def garch_rec(e, om, b, al, lev=0.0, kind='garch'):
    v = np.empty(e.size)
    ms = np.mean(e ** 2)
    pv, pe2, pneg = ms, ms, 0.5 * ms
    for t in range(e.size):
        if kind == 'egarch':
            continue
        v[t] = om + b * pv + al * pe2 + lev * pneg
        pv, pe2, pneg = v[t], e[t] ** 2, (e[t] < 0) * e[t] ** 2
    return v


ee = np.random.default_rng(14).standard_normal(300)
W, _ = run(f"e = {col(ee)}; [V, L] = infer(garch('Constant', 0.1, 'GARCH', {{0.7}}, 'ARCH', {{0.2}}), e); [V2, L2] = infer(gjr('Constant', 0.1, 'GARCH', {{0.6}}, 'ARCH', {{0.1}}, 'Leverage', {{0.2}}), e);"
           "[V3, L3] = infer(egarch('Constant', 0, 'GARCH', {0.8}, 'ARCH', {0.3}, 'Leverage', {-0.1}), e);")
vg = garch_rec(ee, 0.1, 0.7, 0.2)
near('garch infer: the variance recursion from the mean square presample', (W['V'], W['L']), (vg.reshape(-1, 1), -0.5 * np.sum(np.log(2 * np.pi * vg) + ee ** 2 / vg)), 1e-10)
vj = garch_rec(ee, 0.1, 0.6, 0.1, 0.2)
near('gjr infer: negative innovations weigh Leverage more (the presample half negative)', W['V2'], vj.reshape(-1, 1), 1e-10)
lv = np.empty(300)
plv, pz = math.log(np.mean(ee ** 2)), 0.0
eabs = math.sqrt(2 / math.pi)
for t in range(300):
    lv[t] = 0.8 * plv + 0.3 * (abs(pz) - eabs if t else 0.0) - 0.1 * pz
    plv, pz = lv[t], ee[t] / math.exp(lv[t] / 2)
near('egarch infer: the log-variance recursion', W['V3'], np.exp(lv).reshape(-1, 1), 1e-10)
W, out = run("gm = garch('Constant', 0.1, 'GARCH', {0.8}, 'ARCH', {0.1}); rng(2); [V, Y] = simulate(gm, 4000); [E, C, L] = estimate(garch(1,1), Y);"
             "k = E.Constant; g = E.GARCH{1}; al = E.ARCH{1}; vf = forecast(E, 3, Y); [Vi, Li] = infer(E, Y); u = E.UnconditionalVariance;")
C('garch estimate: near the true 0.1, 0.8 and 0.1', abs(W['k'] - 0.1) < 0.06 and abs(W['g'] - 0.8) < 0.07 and abs(W['al'] - 0.1) < 0.04, f"{W['k']} {W['g']} {W['al']}")
C('garch estimate: the log-likelihood infer gives', abs(W['L'] - W['Li']) < 1e-8)
vi = a(W['Vi']).reshape(-1)
Yv = a(W['Y']).reshape(-1)
v1 = W['k'] + W['g'] * vi[-1] + W['al'] * Yv[-1] ** 2
near('garch forecast: the next variance from the data, then omega + (alpha + beta)*v', W['vf'], [[v1], [W['k'] + (W['g'] + W['al']) * v1], [W['k'] + (W['g'] + W['al']) * (W['k'] + (W['g'] + W['al']) * v1)]], 1e-10)
near('UnconditionalVariance: omega/(1 - alpha - beta)', W['u'], W['k'] / (1 - W['g'] - W['al']), 1e-12)
W, _ = run("gj = gjr('Constant', 0.05, 'GARCH', {0.8}, 'ARCH', {0.05}, 'Leverage', {0.1}); rng(10); [v, y] = simulate(gj, 4000); E = estimate(gjr(1,1), y, 'Display', 'off');"
           "lj = E.Leverage{1}; ej = egarch('Constant', -0.1, 'GARCH', {0.9}, 'ARCH', {0.2}, 'Leverage', {-0.1}); rng(9); [v2, y2] = simulate(ej, 3000);"
           "E2 = estimate(egarch(1,1), y2, 'Display', 'off'); g2 = E2.GARCH{1}; l2 = E2.Leverage{1};")
C('gjr and egarch estimates: near their true leverage and persistence', abs(W['lj'] - 0.1) < 0.06 and abs(W['g2'] - 0.9) < 0.05 and abs(W['l2'] + 0.1) < 0.05,
  f"{W['lj']} {W['g2']} {W['l2']}")
W, out = run("g0 = arima('Constant', 0.1, 'AR', {0.4}, 'Variance', garch('Constant', 0.05, 'GARCH', {0.85}, 'ARCH', {0.1})); rng(4); y = simulate(g0, 2000);"
             "E = estimate(arima('ARLags', 1, 'Variance', garch(1,1)), y); ph = E.AR{1}; gv = E.Variance.GARCH{1}; [f, m] = forecast(E, 2, y);")
C('ARIMA with a GARCH variance: both estimated, the variance model shown apart', abs(W['ph'] - 0.4) < 0.06 and abs(W['gv'] - 0.85) < 0.08
  and 'GARCH(1,1) Conditional Variance Model' in out and a(W['m'])[0, 0] > 0)

# ---- vector autoregressions against statsmodels ----------------------------------------------------------------------------------

rv = np.random.default_rng(2)
T = 300
A1 = np.array([[0.5, 0.1], [-0.2, 0.3]])
A2 = np.array([[0.1, 0.0], [0.05, 0.2]])
YV = np.zeros((T, 2))
for t in range(2, T):
    YV[t] = [0.3, -0.1] + A1 @ YV[t - 1] + A2 @ YV[t - 2] + rv.multivariate_normal([0, 0], [[1, 0.3], [0.3, 0.5]])
W, out = run(f"Y = reshape({YV.reshape(-1, order='F').tolist()}, {T}, 2); [E, se, logL, Ei] = estimate(varm(2, 2), Y); c = E.Constant; a1 = E.AR{{1}}; a2 = E.AR{{2}}; S = E.Covariance;"
             "[F, MSE] = forecast(E, 4, Y); r = irf(E, 'NumObs', 5); d = fevd(E, 'NumObs', 5); g = irf(E, 'NumObs', 3, 'Method', 'generalized'); [Ein, lI] = infer(E, Y); sec = se.Constant;"
             "rng(5); Ys = simulate(E, 50, 'NumPaths', 3);")
res = VAR(YV).fit(2, trend='c')
near('varm estimate: statsmodels VAR coefficients', (W['c'], W['a1'], W['a2']), (res.params[0], res.coefs[0], res.coefs[1]), 1e-10)
near('varm estimate: the covariance E\'E/T and the log-likelihood', (W['S'], W['logL'], W['lI']), (res.sigma_u_mle, res.llf, res.llf), 1e-9)
near('varm estimate: the residuals', W['Ei'], res.resid, 1e-10)
near('varm estimate: standard errors from the covariance divided by T', W['sec'], (res.stderr[0] * math.sqrt((T - 2 - 5) / (T - 2))).reshape(-1, 1), 1e-9)
near('varm forecast: statsmodels forecasts', W['F'], res.forecast(YV[-2:], 4), 1e-10)
ma = res.ma_rep(4)
P = np.linalg.cholesky(res.sigma_u_mle)
near('varm forecast: the MSE matrices sum Psi*Sigma*Psi\'', a(W['MSE'].a[3, 0]), sum(m @ res.sigma_u_mle @ m.T for m in ma[:4]), 1e-10)
near('irf orthogonalized: Psi times the Cholesky factor (shock first)', W['r'], np.transpose(ma @ P, (0, 2, 1)), 1e-10)
Gm = np.array([mm @ res.sigma_u_mle / np.sqrt(np.diag(res.sigma_u_mle))[None, :] for mm in ma[:3]])
near('irf generalized: Psi*Sigma*e_j/sqrt(sigma_jj)', W['g'], np.transpose(Gm, (0, 2, 1)), 1e-10)
contrib = np.cumsum((ma @ P) ** 2, axis=0)
near('fevd: each shock\'s share of the forecast error variance', W['d'], np.transpose(contrib / contrib.sum(axis=2, keepdims=True), (0, 2, 1)), 1e-10)
C('varm simulate: numobs by series by paths', a(W['Ys']).shape == (50, 2, 3))
C('varm estimate display off by default; summarize shows the covariance', 'Innovations Covariance' in run(f"Y = reshape({YV.reshape(-1, order='F').tolist()}, {T}, 2); summarize(estimate(varm(2, 1), Y))")[1])

# ---- refusals ---------------------------------------------------------------------------------------------------------------------

raises("adftest(1:30, 'model', 'XX')", "'AR', 'ARD' or 'TS'")
raises("adftest(randn(30, 1), 'test', 'F')", "needs model 'ARD' or 'TS'")
raises("kpsstest(randn(30, 1), 'alpha', 0.5)", 'from 0.01 to 0.1')
raises("forecast(arima('AR', {0.5}, 'Constant', 0, 'Variance', 1), 3)", 'presample responses')
raises("simulate(arima(1, 0, 0), 10)", 'estimate the model first')
raises("arima(-1, 0, 0)", 'whole numbers from 0')
raises("garch(1, 0)", 'has ARCH lags too')
raises("garch('Leverage', {0.1})", 'use gjr or egarch')
raises("estimate(arima('AR', {1.2}, 'Constant', 0, 'Variance', 1), randn(50, 1))", 'stationary')
raises("x = arima(1,0,0); x.Variance = -1", 'positive')
raises("irf(varm(2, 1))", 'estimate the model first')
raises("egcitest(randn(50, 1))", 'at least two')

sys.exit(C.done())
