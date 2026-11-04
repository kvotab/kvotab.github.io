"""Finance, run natively (CPython with numpy and scipy): Black-Scholes prices
against the formulas written out here, put-call parity, the sensitivities
against central differences, implied volatilities back, Black's formula,
the binomial tree against one written out and against Black-Scholes; cash
flows (present values at the rates found are 0, the annuity functions
inverting one another, a mortgage's payment); returns and prices back and
forth; moving averages, Bollinger bands and MACD against pandas, RSI written
out; day counts and the exchange's holidays worked by hand; portfolios
against the closed forms when only the budget binds, and against
scipy.optimize's trust-constr when bounds do.

pandas is a reference only; the suite says so and stops when it is missing.

    python3 test_finance.py          (from any folder)
"""
import asyncio
import datetime as dt
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
    import pandas as pd
except ImportError as e:
    print(f'test_finance needs pandas as a reference ({e}).')
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


def Ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, r, T, v, q=0.0):
    d1 = (math.log(S / K) + (r - q + v * v / 2) * T) / (v * math.sqrt(T))
    d2 = d1 - v * math.sqrt(T)
    c = S * math.exp(-q * T) * Ncdf(d1) - K * math.exp(-r * T) * Ncdf(d2)
    return c, c - S * math.exp(-q * T) + K * math.exp(-r * T)


# ---- options -----------------------------------------------------------------------------------------------------------------

W, _ = run("[c, p] = blsprice([90 100 110], 100, 0.03, 0.75, 0.25, 0.01); [dc, dp] = blsdelta(100, 105, 0.03, 0.5, 0.3, 0.02); g = blsgamma(100, 105, 0.03, 0.5, 0.3, 0.02);"
           "v = blsvega(100, 105, 0.03, 0.5, 0.3, 0.02); [tc, tp] = blstheta(100, 105, 0.03, 0.5, 0.3, 0.02); [rc, rp] = blsrho(100, 105, 0.03, 0.5, 0.3, 0.02);"
           "[lc, lp] = blslambda(100, 105, 0.03, 0.5, 0.3, 0.02); [c0, p0] = blsprice(100, 90, 0.05, 0, 0.2);")
ref = [bs(S, 100, 0.03, 0.75, 0.25, 0.01) for S in (90, 100, 110)]
near('blsprice: the formula written out, with a dividend yield', (W['c'], W['p']), ([[r[0] for r in ref]], [[r[1] for r in ref]]), 1e-12)
near('blsprice at expiry: the payoff', (W['c0'], W['p0']), (10.0, 0.0), 1e-12)
h = 1e-4
f = lambda S=100.0, K=105.0, r=0.03, T=0.5, v=0.3, q=0.02: bs(S, K, r, T, v, q)
near('blsdelta: central differences in the price', (W['dc'], W['dp']), ((f(S=100 + h)[0] - f(S=100 - h)[0]) / (2 * h), (f(S=100 + h)[1] - f(S=100 - h)[1]) / (2 * h)), 1e-7)
near('blsgamma: the second difference', W['g'], (f(S=100 + h)[0] - 2 * f()[0] + f(S=100 - h)[0]) / h ** 2, 1e-5)
near('blsvega: the difference in the volatility', W['v'], (f(v=0.3 + h)[0] - f(v=0.3 - h)[0]) / (2 * h), 1e-6)
near('blstheta: minus the difference in the time to expiry', (W['tc'], W['tp']), (-(f(T=0.5 + h)[0] - f(T=0.5 - h)[0]) / (2 * h), -(f(T=0.5 + h)[1] - f(T=0.5 - h)[1]) / (2 * h)), 1e-6)
near('blsrho: the difference in the rate', (W['rc'], W['rp']), ((f(r=0.03 + h)[0] - f(r=0.03 - h)[0]) / (2 * h), (f(r=0.03 + h)[1] - f(r=0.03 - h)[1]) / (2 * h)), 1e-6)
near('blslambda: delta times price over the option price', (W['lc'], W['lp']), (W['dc'] * 100 / f()[0], W['dp'] * 100 / f()[1]), 1e-12)
W, _ = run("[c, p] = blsprice(100, [80 100 130], 0.04, 1, [0.2 0.35 0.5]); vc = blsimpv(100, [80 100 130], 0.04, 1, c); vp = blsimpv(100, [80 100 130], 0.04, 1, p, 'Class', {'put'});"
           "vn = blsimpv(100, 100, 0.04, 1, 150); vo = blsimpv(100, 100, 0.04, 1, c(2), 10, 0, 1e-6, false);")
near('blsimpv: the volatilities back from calls and from puts', (W['vc'], W['vp']), ([[0.2, 0.35, 0.5]], [[0.2, 0.35, 0.5]]), 1e-8)
C('blsimpv: NaN for a price no volatility gives', np.isnan(W['vn']))
C('blsimpv: the older positional form (a put by Class false)', abs(W['vo'] - 0.2) > 0.01 and np.isfinite(W['vo']))
W, _ = run("[c, p] = blkprice(105, 100, 0.05, 0.5, 0.3); [c2, p2] = blsprice(105*exp(-0.05*0.5), 100, 0.05, 0.5, 0.3);")
near("blkprice: Black's formula is Black-Scholes on the discounted futures price", (W['c'], W['p']), (W['c2'], W['p2']), 1e-12)
W, _ = run("[A, O] = binprice(50, 52, 0.05, 2, 0.25, 0.3, 0); [A2, O2] = binprice(50, 52, 0.05, 1, 1/500, 0.3, 1); cb = blsprice(50, 52, 0.05, 1, 0.3);")
S0, K0, r0, T0, dt0, v0 = 50, 52, 0.05, 2, 0.25, 0.3
n0 = 8
u = math.exp(v0 * math.sqrt(dt0))
d = 1 / u
pu = (math.exp(r0 * dt0) - d) / (u - d)
vals = [max(K0 - S0 * u ** (n0 - i) * d ** i, 0) for i in range(n0 + 1)]
for j in range(n0 - 1, -1, -1):
    vals = [max(math.exp(-r0 * dt0) * (pu * vals[i] + (1 - pu) * vals[i + 1]), K0 - S0 * u ** (j - i) * d ** i) for i in range(j + 1)]
near('binprice: an American put by the tree written out', a(W['O'])[0, 0], vals[0], 1e-12)
C('binprice: the asset tree upper triangular, the most up moves first', a(W['A'])[0, n0] == S0 * u ** n0 and a(W['A'])[n0, 0] == 0)
near('binprice: an American call without dividends tends to Black-Scholes', a(W['O2'])[0, 0], W['cb'], 2e-3)

# ---- cash flows ---------------------------------------------------------------------------------------------------------------

cf = [-1000, 300, 400, 500, 200]
W, out = run(f"r = irr({col(cf)}); r2 = irr([-100 110]'); rm = irr([-100 230 -132]'); m = mirr({col(cf)}, 0.08, 0.06);"
             "dts = [datenum(2023,1,15) datenum(2023,6,30) datenum(2024,2,1) datenum(2024,11,20)]; x = xirr([-500; 150; 200; 250], dts); pv = pvvar([-500; 150; 200; 250], x, dts);"
             f"p1 = pvvar({col(cf)}, 0.07); fv = fvvar({col(cf)}, 0.07);")
near('irr: the present value at the rate is 0', sum(c / (1 + W['r']) ** t for t, c in enumerate(cf)), 0.0, 1e-9)
near('irr: one period', W['r2'], 0.1, 1e-12)
C('irr: several rates, the one nearest 0 with a warning', abs(W['rm'] - 0.1) < 1e-9 and 'rates of return' in out, out)
near('mirr: inflows compounded at 6%, outflows discounted at 8%', W['m'], ((300 * 1.06 ** 3 + 400 * 1.06 ** 2 + 500 * 1.06 + 200) / 1000) ** 0.25 - 1, 1e-12)
near('xirr: the flows on their dates are worth 0 at the rate', W['pv'], 0.0, 1e-8)
near('pvvar and fvvar: discounted to the first flow, compounded to the last', (W['p1'], W['fv']),
     (sum(c / 1.07 ** t for t, c in enumerate(cf)), sum(c * 1.07 ** (4 - t) for t, c in enumerate(cf))), 1e-9)
W, _ = run("pm = payper(0.06/12, 360, 250000, 0); pv = pvfix(0.06/12, 360, pm); fv = fvfix(0.005, 24, 100, 1000, 1); pmd = payper(0.01, 12, 1000, 0, 1);"
           "[P, I, B, pay] = amortize(0.01, 12, 1000); [Pd, Id, Bd, payd] = amortize(0.01, 12, 1000, 0, 1); [Pf, If, Bf] = amortize(0.01, 6, 1000, 200);"
           "ra = annurate(360, pm, 250000); n = annuterm(0.005, pm, 250000); e = effrr(0.09, 12); nr = nomrr(e, 12); ec = effrr(0.05, Inf); pz = payper(0, 10, 1000);")
i = 0.005
near("payper: a mortgage's payment by the annuity formula", W['pm'], 250000 * i / (1 - (1 + i) ** -360), 1e-9)
near('pvfix: the loan back from the payment', W['pv'], 250000, 1e-6)
near('fvfix: payments at the starts and a starting balance', W['fv'], 100 * ((1.005 ** 24 - 1) / 0.005) * 1.005 + 1000 * 1.005 ** 24, 1e-9)
near('payper due at the starts', W['pmd'], 1000 * 0.01 / (1 - 1.01 ** -12) / 1.01, 1e-10)
C('amortize: principal adds up to the loan, the balance ends at 0', abs(np.sum(a(W['P'])) - 1000) < 1e-9 and abs(a(W['B'])[0, -1]) < 1e-9
  and abs(a(W['I'])[0, 0] - 10) < 1e-12)
C('amortize due at the starts: no interest in the first payment', a(W['Id'])[0, 0] == 0 and abs(np.sum(a(W['Pd'])) - 1000) < 1e-9 and abs(a(W['Bd'])[0, -1]) < 1e-9)
near('amortize with a future value: the balance ends at it', a(W['Bf'])[0, -1], 200, 1e-9)
near('annurate and annuterm: the rate and the term back', (W['ra'], W['n']), (0.005, 360), 1e-9)
near('effrr and nomrr: one another\'s inverse; continuous compounding', (W['e'], W['nr'], W['ec']), (1.0075 ** 12 - 1, 0.09, math.exp(0.05) - 1), 1e-12)
near('payper at a zero rate', W['pz'], 100, 1e-12)

# ---- returns ---------------------------------------------------------------------------------------------------------------------

P = np.array([[100, 50], [102, 49], [101, 51], [105, 52.5]])
W, _ = run(f"P = [100 50; 102 49; 101 51; 105 52.5]; r = price2ret(P); rp = price2ret(P, 'Method', 'periodic'); [rt, it] = price2ret(P(:,1), 'Ticks', [0; 1; 3; 4]);"
           "Pb = ret2price(r, 'StartPrice', [100 50]); Pc = ret2price(rp, 'StartPrice', [100 50], 'Method', 'periodic'); s = tick2ret(P); Pt = ret2tick(s, 'StartPrice', [100 50]);"
           "c = tick2ret(P, 'Method', 'continuous');")
near('price2ret: log differences, or simple', (W['r'], W['rp']), (np.diff(np.log(P), axis=0), np.diff(P, axis=0) / P[:-1]), 1e-12)
near('price2ret with ticks: per unit of time', (W['rt'], W['it']), (np.diff(np.log(P[:, 0])) / np.array([1, 2, 1]), [[1], [2], [1]]), 1e-12)
near('ret2price, ret2tick: the prices back', (W['Pb'], W['Pc'], W['Pt']), (P, P, P), 1e-10)
near('tick2ret: simple unless continuous', (W['s'], W['c']), (np.diff(P, axis=0) / P[:-1], np.diff(np.log(P), axis=0)), 1e-12)
X = np.random.default_rng(1).standard_normal((50, 3)) * 0.01
W, _ = run(f"X = reshape({X.reshape(-1, order='F').tolist()}, 50, 3); [m, Cv, ne] = ewstats(X, 0.94, 30);")
w = 0.94 ** np.arange(29, -1, -1)
w /= w.sum()
mx = w @ X[-30:]
near('ewstats: exponentially weighted mean and covariance, the effective observations', (W['m'], W['Cv'], W['ne']),
     (mx, ((X[-30:] - mx) * w[:, None]).T @ (X[-30:] - mx), (1 - 0.94 ** 30) / 0.06), 1e-12)

# ---- indicators -------------------------------------------------------------------------------------------------------------------

z = 100 + np.cumsum(np.random.default_rng(2).standard_normal(80))
s = pd.Series(z)
W, _ = run(f"z = {col(z)}; s5 = movavg(z, 'simple', 5); e10 = movavg(z, 'exponential', 10); w4 = movavg(z, 'linear', 4); m14 = movavg(z, 'modified', 14);"
           "[mid, up, lo] = bollinger(z); [ml, sl] = macd(z); rs = rsindex(z); cu = movavg(z, 'custom', [1 2 3]); tr = movavg(z, 'triangular', 5);")
near('movavg simple: trailing means, shorter windows at the start', W['s5'], s.rolling(5, min_periods=1).mean().to_numpy().reshape(-1, 1), 1e-12)
near('movavg exponential: pandas ewm (span 10, from the first value)', W['e10'], s.ewm(span=10, adjust=False).mean().to_numpy().reshape(-1, 1), 1e-12)
near("movavg modified: Wilder's, alpha 1/14", W['m14'], s.ewm(alpha=1 / 14, adjust=False).mean().to_numpy().reshape(-1, 1), 1e-12)
wl = np.arange(1, 5, dtype=float)
lin = np.array([np.dot(wl[-min(4, t + 1):], z[max(0, t - 3):t + 1]) / wl[-min(4, t + 1):].sum() for t in range(80)])
near('movavg linear: weights 1 to 4, the newest heaviest (the newest weights in the short windows at the start)', W['w4'], lin.reshape(-1, 1), 1e-12)
near('movavg custom and triangular', (a(W['cu'])[2:], W['tr']), ((z[:-2] * 1 + z[1:-1] * 2 + z[2:] * 3) / 6,
                                                                  s.rolling(3, min_periods=1).mean().rolling(3, min_periods=1).mean().to_numpy().reshape(-1, 1)), 1e-12)
near('bollinger: pandas rolling mean and population standard deviation, NaN until full', (W['mid'], W['up']),
     (s.rolling(20).mean().to_numpy().reshape(-1, 1), (s.rolling(20).mean() + 2 * s.rolling(20).std(ddof=0)).to_numpy().reshape(-1, 1)), 1e-10)
ml = s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()
near('macd: pandas ewm 12 less 26, and its 9', (W['ml'], W['sl']), (ml.to_numpy().reshape(-1, 1), ml.ewm(span=9, adjust=False).mean().to_numpy().reshape(-1, 1)), 1e-12)
dz = np.diff(z)
g, l = np.maximum(dz, 0), np.maximum(-dz, 0)
ag, al = g[:14].mean(), l[:14].mean()
rsi = [100 - 100 / (1 + ag / al)]
for t in range(14, dz.size):
    ag, al = (ag * 13 + g[t]) / 14, (al * 13 + l[t]) / 14
    rsi.append(100 - 100 / (1 + ag / al))
near("rsindex: Wilder's smoothing written out, NaN for the first 14", W['rs'], np.concatenate([np.full(14, np.nan), rsi]).reshape(-1, 1), 1e-10)

# ---- dates ------------------------------------------------------------------------------------------------------------------------

dn = lambda y, m, d: dt.date(y, m, d).toordinal() + 366
W, _ = run("a = daysact(datenum(2024,1,15), datenum(2024,3,1)); b = days360(datenum(2023,1,31), datenum(2023,3,31)); c = days360(datenum(2023,2,28), datenum(2023,3,31));"
           "d = days360(datenum(2024,2,29), datenum(2025,2,28)); y0 = yearfrac(datenum(2023,7,1), datenum(2024,7,1), 0); y2 = yearfrac(datenum(2024,1,1), datenum(2024,7,1), 2);"
           "y3 = yearfrac(datenum(2024,1,1), datenum(2024,7,1), 3); y6 = yearfrac(datenum(2024,1,31), datenum(2024,3,31), 6); y7 = yearfrac(datenum(2024,1,1), datenum(2025,1,1), 7);"
           "dt2 = daysact(datetime(2024,1,1), datetime(2024,12,31));")
near('daysact: the actual days', (W['a'], W['dt2']), (46, 365))
near('days360 (SIA): the 31st and the end of February as the 30th', (W['b'], W['c'], W['d']), (60, 30, 360))
near('yearfrac: actual/actual across a leap year, actual/360, actual/365, 30/360 European, actual/365 Japanese', (W['y0'], W['y2'], W['y3'], W['y6'], W['y7']),
     (184 / 365 + 182 / 366, 182 / 360, 182 / 365, 60 / 360, 365 / 365), 1e-12)
W, _ = run("h = holidays(datenum(2024,1,1), datenum(2024,12,31)); h21 = holidays('01-Jan-2021', '31-Dec-2022'); b1 = isbusday([datenum(2024,7,4) datenum(2024,7,5) datenum(2024,7,6)]);"
           "n = busdate(datenum(2024,11,27)); p = busdate(datenum(2024,9,3), -1); f = fbusdate(2025, 9); l = lbusdate(2024, 3); w = isbusday(datenum(2024,7,6), [], [0 0 0 0 0 1 0]);"
           "nh = isbusday(datenum(2024,7,4), datenum(2024,1,1));")
want2024 = [dn(2024, 1, 1), dn(2024, 1, 15), dn(2024, 2, 19), dn(2024, 3, 29), dn(2024, 5, 27), dn(2024, 6, 19), dn(2024, 7, 4), dn(2024, 9, 2), dn(2024, 11, 28), dn(2024, 12, 25)]
near("holidays: the exchange's 2024 holidays", W['h'], np.array(want2024).reshape(-1, 1))
hs = [x for x in a(W['h21']).reshape(-1)]
C('holidays: weekend holidays moved (Juneteenth from 2022; New Year 2022 on a Saturday not moved back)', dn(2021, 12, 31) not in hs and dn(2021, 6, 18) not in hs
  and dn(2022, 6, 20) in hs and dn(2021, 7, 5) in hs and dn(2022, 12, 26) in hs, str(hs))
C('isbusday: a holiday, a Friday, a Saturday', a(W['b1']).reshape(-1).tolist() == [0, 1, 0])
near('busdate: past Thanksgiving, back over Labor Day; fbusdate after Labor Day; lbusdate before Good Friday', (W['n'], W['p'], W['f'], W['l']),
     (dn(2024, 11, 29), dn(2024, 8, 30), dn(2025, 9, 2), dn(2024, 3, 28)))
C('isbusday: own weekend (only Friday: a Saturday works) and holidays', W['w'] is True and W['nh'] is True)

# ---- portfolios --------------------------------------------------------------------------------------------------------------------

mu = np.array([0.06, 0.08, 0.11, 0.15])
sd = np.array([0.10, 0.14, 0.20, 0.28])
Cr = np.array([[1, 0.3, 0.2, 0.1], [0.3, 1, 0.4, 0.25], [0.2, 0.4, 1, 0.35], [0.1, 0.25, 0.35, 1]])
Cv = Cr * np.outer(sd, sd)
Ci = np.linalg.inv(Cv)
one = np.ones(4)
mat = lambda M: f"reshape({np.asarray(M, float).reshape(-1, order='F').tolist()}, {np.shape(M)[0]}, {np.shape(M)[1]})"
A_, B_, C_ = one @ Ci @ one, one @ Ci @ mu, mu @ Ci @ mu
t1, t2 = B_ / A_ + 0.005, B_ / A_ + 0.03
W, _ = run(f"m = {col(mu)}; Cv = {mat(Cv)}; p = Portfolio('AssetMean', m, 'AssetCovar', Cv, 'Budget', 1, 'LowerBound', -10, 'UpperBound', 10);"
           f"w = estimateFrontierByReturn(p, [{t1!r} {t2!r}]); lim = estimateFrontierLimits(p, 'min'); p.RiskFreeRate = 0.02; ws = estimateMaxSharpeRatio(p);"
           "[rk, rt] = estimatePortMoments(p, w);")
Dd = A_ * C_ - B_ ** 2
front = lambda t: (Ci @ ((C_ - t * B_) * one + (t * A_ - B_) * mu)) / Dd
near('frontier by return: the closed form when only the budget binds', W['w'], np.column_stack([front(t1), front(t2)]), 1e-6)
near('least-risk portfolio: C^-1*1/(1\'*C^-1*1)', W['lim'], (Ci @ one / A_).reshape(-1, 1), 1e-6)
tan = Ci @ (mu - 0.02)
near('largest Sharpe ratio: the tangency portfolio C^-1*(mu - rf), scaled', W['ws'], (tan / tan.sum()).reshape(-1, 1), 1e-5)
near('estimatePortMoments: sqrt(w\'Cw) and w\'mu', (W['rk'], W['rt']), ([[math.sqrt(front(t1) @ Cv @ front(t1))], [math.sqrt(front(t2) @ Cv @ front(t2))]], [[t1], [t2]]), 1e-6)
W, _ = run(f"m = {col(mu)}; Cv = {mat(Cv)}; p = setDefaultConstraints(Portfolio('AssetMean', m, 'AssetCovar', Cv)); p = setBounds(p, 0, 0.4);"
           "F = estimateFrontier(p, 6); [r, e] = estimatePortMoments(p, F); [pr, pe, pw] = portopt(m', Cv, 6, [], [eye(4) 0.4*ones(4, 1)]); wr = estimateFrontierByRisk(p, 0.15);"
           "p2 = setInequality(p, [1 1 0 0], 0.5); w2 = estimateFrontierLimits(p2, 'max');")
from scipy.optimize import minimize  # noqa: E402
Fm = a(W['F'])
e_ = a(W['e']).reshape(-1)
ok = True
for k in range(1, 5):
    ref = minimize(lambda w: w @ Cv @ w, np.full(4, 0.25), method='trust-constr', bounds=[(0, 0.4)] * 4,
                   constraints=[{'type': 'eq', 'fun': lambda w: w.sum() - 1}, {'type': 'eq', 'fun': lambda w, t=e_[k]: mu @ w - t}],
                   options={'gtol': 1e-12, 'xtol': 1e-12, 'maxiter': 5000})
    ok &= Fm[:, k] @ Cv @ Fm[:, k] <= ref.fun + 1e-9 and np.all(Fm[:, k] >= -1e-9) and np.all(Fm[:, k] <= 0.4 + 1e-9) and abs(Fm[:, k].sum() - 1) < 1e-9
C('bounded frontier: no more variance than trust-constr finds for the same returns, within the bounds', ok)
C('bounded frontier: the ends at the least risk and at the largest return within the bounds', abs(e_[-1] - (0.4 * 0.15 + 0.4 * 0.11 + 0.2 * 0.08)) < 1e-9 and np.all(np.diff(e_) > 0))
near('portopt with ConSet rows for the upper bounds: the same frontier (weights a row each)', (W['pr'], W['pe'], W['pw']), (W['r'], W['e'], Fm.T), 1e-6)
wr = a(W['wr']).reshape(-1)
near('estimateFrontierByRisk: the portfolio with that risk', math.sqrt(wr @ Cv @ wr), 0.15, 1e-7)
w2 = a(W['w2']).reshape(-1)
C('setInequality: A*w <= b holds at the largest return', w2[0] + w2[1] <= 0.5 + 1e-9 and abs(w2.sum() - 1) < 1e-9)
Xr = np.random.default_rng(4).standard_normal((60, 3)) * 0.02 + 0.005
W, _ = run(f"X = {mat(Xr)}; p = estimateAssetMoments(Portfolio, X); m = p.AssetMean; Cv = p.AssetCovar; [sg, cr] = cov2corr(Cv); cv2 = corr2cov(sg, cr);"
           "[r, e] = portstats(m', Cv, [1 0 0; 1/3 1/3 1/3]); v = portvrisk(0.01, 0.05, 0.05, 1e6);")
near('estimateAssetMoments: the sample mean and covariance', (W['m'], W['Cv']), (Xr.mean(axis=0).reshape(-1, 1), np.cov(Xr, rowvar=False)), 1e-12)
near('cov2corr and corr2cov: there and back', W['cv2'], np.cov(Xr, rowvar=False), 1e-12)
near('portstats: risk and return of rows of weights', (W['r'], W['e']),
     ([[math.sqrt(np.cov(Xr, rowvar=False)[0, 0])], [math.sqrt(np.full(3, 1 / 3) @ np.cov(Xr, rowvar=False) @ np.full(3, 1 / 3))]],
      [[Xr.mean(axis=0)[0]], [Xr.mean()]]), 1e-12)
from scipy.stats import norm  # noqa: E402
near('portvrisk: the normal quantile loss', W['v'], -(0.01 + norm.ppf(0.05) * 0.05) * 1e6, 1e-9)
W, out = run(f"m = {col(mu)}; Cv = {mat(Cv)}; figure; plotFrontier(setDefaultConstraints(Portfolio('AssetMean', m, 'AssetCovar', Cv))); ax = gca; n = numel(ax.Children); p = Portfolio('AssetMean', m, 'AssetCovar', Cv)")
C('plotFrontier draws; a Portfolio shows its properties', W['n'] == 1.0 and 'Portfolio with properties' in out and 'AssetCovar' in out)

# ---- refusals ----------------------------------------------------------------------------------------------------------------------

raises("blsprice(-1, 100, 0.05, 1, 0.2)", 'not negative')
raises("estimateFrontier(Portfolio('AssetMean', [1; 2], 'AssetCovar', eye(2)))", 'no constraints')
raises("estimateFrontier(setDefaultConstraints(Portfolio('NumAssets', 2)))", 'no asset moments')
raises("estimateFrontierByReturn(setDefaultConstraints(Portfolio('AssetMean', [0.1; 0.2], 'AssetCovar', eye(2))), 0.5)", 'outside the frontier')
raises("yearfrac(1, 100, 9)", 'coupon dates')
raises("busdate(1, 2)", 'Direction is 1')
raises("Portfolio('AssetMean', [1; 2], 'AssetCovar', eye(3))", 'the portfolio has 2')
raises("binprice(50, 52, 0.05, 1, 1, 0.01, 1)", 'up probability')

sys.exit(C.done())
