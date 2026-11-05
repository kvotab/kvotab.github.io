"""System identification, run natively (CPython with numpy and scipy): iddata
and idinput; ARX and AR against least squares written out here; ARMAX, OE,
BJ, N4SID, SSEST and TFEST recovering known systems exactly from noise-free
data and closely from noisy data; predictions against the model iterated by
hand; compare's fit, sim, pe and resid against their formulas; the models
as linear models for step, bode and tfdata.

    python3 test_sysid.py          (from any folder)
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
from scipy.signal import lfilter, cont2discrete  # noqa: E402

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


rs = np.random.default_rng(1)
N = 1200
u = np.sign(rs.standard_normal(N))
e = 0.1 * rs.standard_normal(N)
A0, B0, C0 = np.array([1, -1.5, 0.7]), np.array([0, 0.5, 0.3]), np.array([1, 0.4])
y_arx = lfilter(B0, A0, u) + lfilter([1], A0, e)
y_armax = lfilter(B0, A0, u) + lfilter(C0, A0, e)
DATA = lambda y, uu=u, Ts=0.1: f"iddata({col(y)}, {col(uu)}, {Ts})"

# ---- data -------------------------------------------------------------------------------------------------------------------

W, out = run(f"d = {DATA(y_arx)}; n = size(d); yy = d.y; uu = d.u; t = d.SamplingInstants; s = d(11:20); sn = size(s); st = s.Tstart; d.OutputName = {{'temp'}}; on = d.OutputName; d2 = detrend(d); m = mean(d2.y); d")
near('iddata: size [N ny nu], the signals, the sampling instants from Ts', (W['n'], W['yy'], W['uu'], a(W['t'])[[0, -1]].reshape(-1)), ([[N, 1, 1]], y_arx.reshape(-1, 1), u.reshape(-1, 1), [0.1, 0.1 * N]), 1e-12)
near('iddata indexing: the samples picked, the start moved', (W['sn'], W['st']), ([[10, 1, 1]], 1.1), 1e-12)
C('iddata names and display; detrend takes the means off', text(W['on'].a[0, 0]) == 'temp' and abs(W['m']) < 1e-12 and 'Time domain data set with 1200 samples' in out)
W, _ = run("p = idinput(127, 'prbs'); r = idinput(1000, 'rbs', [0 1], [2 5]); g = idinput(5000, 'rgs', [0 1], [-2 4]); s = idinput(400, 'sine'); bl = idinput(4096, 'rgs', [0 0.2]);")
p = a(W['p']).reshape(-1)
C('idinput prbs: a maximum-length sequence (period 127, 64 highs), levels -1 and 1', set(p.tolist()) == {-1.0, 1.0} and int(np.sum(p == 1)) == 64)
C('idinput rbs: the two levels given', set(a(W['r']).reshape(-1).tolist()) == {2.0, 5.0})
near('idinput rgs: mean and mean + one standard deviation at the levels', (np.mean(a(W['g'])), np.mean(a(W['g'])) + np.std(a(W['g']))), (1.0, 4.0), 1e-9)
F = np.abs(np.fft.rfft(a(W['bl']).reshape(-1)))
C('idinput band: no power above the band', np.max(F[int(0.21 * F.size):]) < 1e-9 * np.max(F))

# ---- ARX, AR -----------------------------------------------------------------------------------------------------------------

W, out = run(f"d = {DATA(y_arx)}; m = arx(d, [2 2 1]); A = m.A; B = m.B; v = m.NoiseVariance; r = m.Report; f = r.Fit.FitPercent; [Ap, Bp, Cp, Dp, Fp, dA, dB] = polydata(m); m")
Phi = np.column_stack([-y_arx[1:-1], -y_arx[:-2], u[1:-1], u[:-2]])
th, *_ = np.linalg.lstsq(Phi, y_arx[2:], rcond=None)
near('arx: least squares on the past outputs and inputs', (W['A'], W['B']), ([[1, th[0], th[1]]], [[0, th[2], th[3]]]), 1e-10)
res = y_arx[2:] - Phi @ th
cov = (res @ res / (N - 2 - 4)) * np.linalg.inv(Phi.T @ Phi)
near('polydata: the coefficients\' standard deviations from s^2 (Phi\'Phi)^-1', (a(W['dA']).reshape(-1)[1:], a(W['dB']).reshape(-1)[1:]), (np.sqrt(np.diag(cov))[:2], np.sqrt(np.diag(cov))[2:]), 1e-9)
C('arx: shown with its polynomials, fit and FPE', 'A(z) = 1 - 1.' in out and 'B(z) =' in out and 'Fit to estimation data' in out and W['f'] > 90)
ts = lfilter([1], [1, -0.6, 0.2], rs.standard_normal(3000))
W, _ = run(f"y = {col(ts)}; m = ar(y, 2); A = m.A; my = ar(y, 2, 'yw'); Ay = my.A; m2 = arx(y, 2); A2 = m2.A;")
P2 = np.column_stack([-ts[1:-1], -ts[:-2]])
th2, *_ = np.linalg.lstsq(P2, ts[2:], rcond=None)
from scipy.linalg import solve_toeplitz  # noqa: E402
rr = np.array([ts[:3000 - k] @ ts[k:] / 3000 for k in range(3)])
near('ar: least squares, and arx of a time series the same', (W['A'], W['A2']), ([[1, th2[0], th2[1]]], [[1, th2[0], th2[1]]]), 1e-10)
near("ar 'yw': the Yule-Walker equations", W['Ay'], [[1, *(-solve_toeplitz(rr[:2], rr[1:3]))]], 1e-10)

# ---- prediction-error models: exact from noise-free data ---------------------------------------------------------------------

y_oe = lfilter([0, 0.4, -0.2], [1, -1.2, 0.5], u)
W, _ = run(f"d = {DATA(y_oe)}; m = oe(d, [2 2 1]); B = m.B; Fp = m.F;")
near('oe: the true system from noise-free data', (W['B'], W['Fp']), ([[0, 0.4, -0.2]], [[1, -1.2, 0.5]]), 1e-8)
yc = y_armax
W, _ = run(f"d = {DATA(yc)}; m = armax(d, [2 2 1 1]); A = m.A; B = m.B; Cc = m.C; v = m.NoiseVariance;")
C('armax: near the true A, B and C from noisy data', np.allclose(a(W['A']), [A0], atol=0.03) and np.allclose(a(W['B']), [B0], atol=0.03) and np.allclose(a(W['Cc']), [C0], atol=0.06)
  and abs(W['v'] - 0.01) < 0.002, f"{a(W['A'])} {a(W['B'])} {a(W['Cc'])} {W['v']}")


def armax_sse(Ap, Bp, Cp):
    w = lfilter(Ap, [1], yc) - lfilter(Bp, [1], u)
    r = lfilter([1], Cp, w)
    return r @ r


base = armax_sse(a(W['A']).reshape(-1), a(W['B']).reshape(-1), a(W['Cc']).reshape(-1))
worse = True
for k, d in ((0, 1), (0, 2), (1, 1), (1, 2), (2, 1)):
    for h in (1e-4, -1e-4):
        P = [a(W['A']).reshape(-1).copy(), a(W['B']).reshape(-1).copy(), a(W['Cc']).reshape(-1).copy()]
        P[k][d] += h
        worse &= armax_sse(*P) > base
C('armax: the prediction errors written out here, at their least sum of squares', worse)
e2 = 0.05 * rs.standard_normal(N)
ybj = lfilter([0, 1.0, 0.5], [1, -0.8], u) + lfilter([1, 0.3], [1, -0.6], e2)
W, _ = run(f"d = {DATA(ybj)}; m = bj(d, [2 1 1 1 1]); B = m.B; Cc = m.C; D = m.D; Fp = m.F;")
C('bj: near the true B, C, D and F', np.allclose(a(W['B']), [[0, 1, 0.5]], atol=0.03) and np.allclose(a(W['Fp']), [[1, -0.8]], atol=0.02)
  and np.allclose(a(W['Cc']), [[1, 0.3]], atol=0.1) and np.allclose(a(W['D']), [[1, -0.6]], atol=0.1), f"{a(W['B'])} {a(W['Cc'])} {a(W['D'])} {a(W['Fp'])}")

# ---- state space and continuous time -------------------------------------------------------------------------------------------

W, _ = run(f"d = {DATA(y_oe)}; s = n4sid(d, 2); p = sort(abs(eig(s.A))); h = impulse(s, 10); s2 = ssest(d, 2); p2 = sort(abs(eig(s2.A)));")
truep = np.sort(np.abs(np.roots([1, -1.2, 0.5])))
near('n4sid: the true poles from noise-free data', W['p'], truep.reshape(-1, 1), 1e-6)
C('ssest: the same poles', np.allclose(a(W['p2']).reshape(-1), truep, atol=1e-6))
Ts = 0.05
bd, ad, _ = cont2discrete(([2.0, 8.0], [1.0, 3.0, 8.0]), Ts, method='zoh')
y_ct = lfilter(np.ravel(bd), ad, u)
W, _ = run(f"d = {DATA(y_ct, u, Ts)}; t = tfest(d, 2, 1); nu = t.Numerator; de = t.Denominator; [z, p] = tfdata(t, 'v'); f = t.Report.Fit.FitPercent;")
near('tfest: the continuous transfer function from data held between samples', (W['nu'], W['de']), ([[2, 8]], [[1, 3, 8]]), 1e-6)
C('tfest: a perfect fit', W['f'] > 99.99)

# ---- predictions, simulation, comparison -----------------------------------------------------------------------------------------

W, _ = run(f"d = {DATA(y_arx)}; m = arx(d, [2 2 1]); p1 = predict(m, d, 1); p1 = p1.y; p3 = predict(m, d, 3); p3 = p3.y; pi_ = predict(m, d, Inf); pi_ = pi_.y;"
           "s = sim(m, d); s = s.y; e = pe(m, d); e = e.y; A = m.A; B = m.B;")
Am, Bm = a(W['A']).reshape(-1), a(W['B']).reshape(-1)
p1 = lfilter(Bm, [1], u) - lfilter(Am, [1], y_arx) + y_arx
near('predict K = 1: the one-step predictor B u + (1 - A) y', a(W['p1']).reshape(-1), p1, 1e-10)
p3 = np.zeros(N)
for t in range(N):
    yy = {j: y_arx[j] for j in range(max(0, t - 5), t - 2)} if t >= 3 else {}
    for s_ in range(max(0, t - 2), t + 1):
        v = sum(-Am[i] * (yy[s_ - i] if s_ - i in yy else (y_arx[s_ - i] if 0 <= s_ - i <= t - 3 else 0.0)) for i in (1, 2))
        v += sum(Bm[j] * (u[s_ - j] if s_ - j >= 0 else 0) for j in (1, 2))
        yy[s_] = v
    p3[t] = yy[t]
near('predict K = 3: the model iterated by hand from the outputs three samples back', a(W['p3']).reshape(-1)[10:], p3[10:], 1e-8)
near('sim and predict Inf: B/A of the input from rest; pe the one-step errors', (a(W['s']).reshape(-1), a(W['pi_']).reshape(-1), a(W['e']).reshape(-1)),
     (lfilter(Bm, Am, u), lfilter(Bm, Am, u), y_arx - p1), 1e-10)
y_ic = lfilter([0, 0.4, -0.2], [1, -1.2, 0.5], u, zi=np.array([3.0, -1.0]))[0]
W, out = run(f"d = {DATA(y_oe)}; m = oe(d, [2 2 1]); d2 = {DATA(y_ic)}; [y, fit] = compare(d2, m); [y1, f1] = compare(d, arx(d, [2 2 1]), 1);")
C('compare: a perfect fit with the initial state estimated', W['fit'] > 99.999, str(W['fit']))
C('compare with K = 1: an exact ARX model of noise-free OE data predicts perfectly', W['f1'] > 99.99, str(W['f1']))
W, out = run(f"d = {DATA(y_armax)}; m = armax(d, [2 2 1 1]); [E, Rr] = resid(d, m); ac = Rr.AutoCorr; xc = Rr.CrossCorr; b = Rr.Bound; ee = E.y; figure; resid(d, m); figure; compare(d, m); nh = numel(findall(gcf, 'Type', 'line'));")
ee = a(W['ee']).reshape(-1)
ec = ee - ee.mean()
near('resid: the autocorrelation of the one-step errors and the 99% bound', (a(W['ac']).reshape(-1)[:4], W['b']),
     (np.array([ec[:N - k] @ ec[k:] for k in range(4)]) / (ec @ ec), 2.576 / math.sqrt(N)), 1e-10)
C('resid: white residuals of the right model stay inside the bounds', np.mean(np.abs(a(W['ac']).reshape(-1)[1:]) < W['b']) > 0.9 and np.mean(np.abs(a(W['xc'])) < W['b']) > 0.9)
C('compare without outputs: measured and simulated drawn', W['nh'] == 2.0, str(W['nh']))
W, _ = run(f"d = {DATA(y_arx)}; m1 = arx(d, [1 1 1]); m2 = arx(d, [2 2 1]); figure; compare(d, m1, m2); L1 = findobj(gcf, 'Type', 'legend'); s1 = L1.String;\n"
           "figure; compare(d, arx(d, [2 2 1]), m1); L2 = findobj(gcf, 'Type', 'legend'); s2 = L2.String; tx = evalc('m3 = tfest(d, 2)');")
C("compare's legend: each model by its variable's name, 'Model k' for an expression",
  [text(v).split(':')[0] for v in W['s1'].items()] == ['Measured', 'm1', 'm2'] and [text(v).split(':')[0] for v in W['s2'].items()] == ['Measured', 'Model 1', 'm1'],
  (W['s1'], W['s2']))
C('an identified transfer function shows one closing line, its own', 'Continuous-time identified transfer function.' in text(W['tx']) and 'Continuous-time transfer function.' not in text(W['tx']), text(W['tx']))
W, _ = run(f"d = {DATA(y_arx)}; m = arx(d, [2 2 1]); m2 = arx(d, [4 4 1]); v = aic(m, m2); f = fpe(m); r = m.Report.Fit; [n, dd] = tfdata(m, 'v'); y = step(m, 1); [mag] = bode(m, 1);")
rf = W['r']
near('aic and fpe: from the fit report', (a(W['v'])[0, 0], W['f']), (rf.get1('AIC'), rf.get1('FPE')), 1e-12)
C('aic: the larger model is no better on noisy ARX data (aic rises)', a(W['v'])[0, 1] > a(W['v'])[0, 0] - 5)
mse = rf.get1('MSE')
near('the report: FPE = MSE(1 + d/N)/(1 - d/N), AIC = N log MSE + 2d + N(log 2 pi + 1)', (rf.get1('FPE'), rf.get1('AIC')),
     (mse * (1 + 4 / N) / (1 - 4 / N), N * math.log(mse) + 8 + N * (math.log(2 * math.pi) + 1)), 1e-10)
near('tfdata of an ARX model: B and A in powers of z', (a(W['n']), a(W['dd'])), (a(run(f"d = {DATA(y_arx)}; m = arx(d, [2 2 1]); B = m.B; A = m.A;")[0]['B']).reshape(-1),
                                                                                 a(run(f"d = {DATA(y_arx)}; m = arx(d, [2 2 1]); A = m.A;")[0]['A']).reshape(-1)), 1e-12)
C('step and bode take an identified model', a(W['y']).size > 2 and np.all(np.isfinite(a(W['mag']))))

# ---- refusals --------------------------------------------------------------------------------------------------------------------

raises("arx(iddata(randn(50,1), randn(50,1)), [2 2])", '[na nb nk]')
raises("oe(randn(50, 1), [1 1 1])", 'needs data with an input')
raises("compare(randn(10,1), arx(randn(50,1), 2))", 'iddata first')
raises("iddata(randn(10,1), randn(9,1))", 'same number of samples')
raises("idinput(100, 'chirp')", "'rgs', 'rbs', 'prbs' or 'sine'")
raises("tfest(iddata(randn(50,1), randn(50,1)), 0)", 'np is a whole number from 1')
raises("polydata(n4sid(iddata(randn(200,1), randn(200,1)), 1))", 'polynomial model')
raises("resid(randn(20, 1), 3)", 'identified model')

sys.exit(C.done())
