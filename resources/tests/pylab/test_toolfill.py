"""Toolbox fill-ins, run natively (CPython with numpy and scipy): more
signal processing (stft against SciPy, tone and pulse measures on signals
whose answers are known, delays, warping, mode decompositions), special
functions against scipy.special, charpoly, minpoly and jordan, quadv,
frequency-response models and interconnections, staircase forms, lqi and
pidtune, statistics (tiedrank, mnrfit against statsmodels, fitlme against
statsmodels' MixedLM, rocmetrics against scikit-learn, searchers, designs,
quasi-random streams), wavelet filter banks, synchrosqueezing, coherence
and the empirical wavelet transform, and splines (csaps against SciPy).

statsmodels and scikit-learn are references only (the page does not use
them); the suite says so and stops when either is missing.

    python3 test_toolfill.py          (from any folder)
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
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    from statsmodels.miscmodels.ordinal_model import OrderedModel
    import pandas as pd
    from sklearn.metrics import roc_auc_score
except ImportError as e:
    print(f'test_toolfill needs statsmodels, pandas and scikit-learn as references ({e}).')
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
        return np.concatenate([np.asarray(v).reshape(-1) for v in x])
    return np.asarray(x)


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


def mat(X):
    """A matrix as the language's literal."""
    X = np.atleast_2d(np.asarray(X, float))
    return f"reshape({X.reshape(-1, order='F').tolist()}, {X.shape[0]}, {X.shape[1]})"


# ---- filters, transforms ------------------------------------------------------------------------------------------------------------

from scipy import signal as S  # noqa: E402
W, _ = run("[b, a] = besself(4, 3); [z, p, k] = besself(3, 2, 'high');")
bb, aa = S.bessel(4, 3, analog=True)
near("besself: SciPy's analog Bessel filter (the 'phase' normalization)", (W['b'], W['a']), (bb, aa), 1e-12)
W, _ = run("[r, p, k] = residuez([1 0.5], [1 -0.9 0.2]); [b2, a2] = residuez(r, p, k);")
near('residuez: the residues and poles worked by hand', (W['r'], W['p']), [10, -9, 0.5, 0.4], 1e-12)
near('residuez: back again', (W['b2'], W['a2']), [1, 0.5, 1, -0.9, 0.2], 1e-12)

rs = np.random.default_rng(3)
x = rs.standard_normal(700)
W, _ = run(f"x = {x.tolist()}'; w = hamming(64, 'periodic'); [s, f, t] = stft(x, 100, 'Window', w, 'OverlapLength', 48, 'FFTLength', 128, 'FrequencyRange', 'onesided');"
           "[sc, fc] = stft(x, 100, 'Window', w, 'OverlapLength', 48, 'FFTLength', 128); [xr, tr] = istft(sc, 100, 'Window', w, 'OverlapLength', 48, 'FFTLength', 128);")
win = 0.54 - 0.46 * np.cos(2 * np.pi * np.arange(64) / 64)
fS, tS, ZS = S.stft(x, fs=100, window=win, nperseg=64, noverlap=48, nfft=128, boundary=None, padded=False, detrend=False, return_onesided=True, scaling='spectrum')
near("stft: SciPy's transform (unscaled), frequencies and times", (W['s'], W['f'], W['t']), (ZS * win.sum(), fS, tS), 1e-9)
near('stft: centred frequencies, the Nyquist frequency at the end', a(W['fc']).reshape(-1)[[0, -1]], [-50 + 100 / 128, 50], 1e-12)
n = a(W['xr']).size
near('istft: the signal back by weighted overlap-add', np.real(a(W['xr'])).reshape(-1), x[:n], 1e-10)
W, _ = run("y = pulstran(0:0.1:2, [0.5 1; 1.5 2], 'rectpuls', 0.3); z = pulstran(0:0.25:1, 0.5, [1 2 1], 4);")
near('pulstran: delays with amplitudes', a(W['y']).reshape(-1), [0] * 4 + [1] * 3 + [0] * 7 + [2] * 3 + [0] * 4)
near('pulstran: a sampled pulse at its delay', a(W['z']).reshape(-1), [0, 0, 1, 2, 1])
W, _ = run("[xh, nd] = cceps([1 0.5 zeros(1, 30)]); xb = icceps(xh, nd);")
xh = a(W['xh']).reshape(-1)
near('cceps: the complex cepstrum of 1 + 0.5/z, (-1)^(n+1)*0.5^n/n', xh[1:6], [(-1) ** (k + 1) * 0.5 ** k / k for k in range(1, 6)], 1e-9)
near('icceps: the signal back', W['xb'], np.concatenate([[1, 0.5], np.zeros(30)]).reshape(1, -1), 1e-12)

# ---- tones and pulses ------------------------------------------------------------------------------------------------------------------

t = np.arange(4000) / 1000
xt = np.sin(2 * np.pi * 50.3 * t) + 0.01 * np.sin(2 * np.pi * 100.6 * t) + 0.005 * np.sin(2 * np.pi * 150.9 * t)
W, _ = run(f"x = {xt.tolist()}'; [r, hp, hf] = thd(x, 1000); sf = sfdr(x, 1000); [p, f] = pspectrum(x, 1000); [pm, k] = max(p); fp = f(k);")
near('thd: the harmonics against the fundamental, exactly', W['r'], 10 * math.log10((0.01 ** 2 + 0.005 ** 2) / 1), 1e-6)
near('thd: the harmonics found at their frequencies', a(W['hf'])[:3].reshape(-1), [50.3, 100.6, 150.9], 1e-4)
near('sfdr: the fundamental against the largest spur', W['sf'], 40.0, 1e-6)
near('pspectrum: a sinusoid of amplitude 1 peaks at 1/2 at its frequency', (W['pm'], W['fp']), (0.5, 50.3), 2e-3)
noise = 1e-3 * np.random.default_rng(9).standard_normal(t.size)
W, _ = run(f"x = {(xt + noise).tolist()}'; r = snr(x, 1000); q = sinad(x, 1000); r2 = snr([1 2 3], [0.1 0.1 0.1]);")
near('snr: the tone against white noise (harmonics left out)', W['r'], 10 * math.log10(0.5 / 1e-6), 0.01)
near('sinad: noise and distortion together', W['q'], 10 * math.log10(0.5 / (1e-6 + 0.01 ** 2 / 2 + 0.005 ** 2 / 2)), 0.01)
near('snr(x, y): the energies', W['r2'], 10 * math.log10(14 / 0.03), 1e-12)

W, _ = run("fs = 100; t = (0:299)/fs; x = interp1([0 0.5 0.6 1.1 1.3 1.6 1.7 2.2 2.4 3], [0 0 1 1 0 0 1 1 0 0], t);"
           "lv = statelevels(x); r = risetime(x, fs); f = falltime(x, fs); w = pulsewidth(x, fs); p = pulseperiod(x, fs); d = dutycycle(x, fs);"
           "sp = pulsesep(x, fs); m = midcross(x, fs); sr = slewrate(x, fs); y = x; y(62:64) = [1.1 1.05 1.02]; os = overshoot(y, fs);"
           "st = settlingtime(y, fs, 0.3); us = undershoot(y, fs);")
near('statelevels: the two levels', W['lv'], [[0, 1]])
near('risetime and falltime of trapezoids (10% to 90%)', (W['r'], W['f']), [0.08, 0.08, 0.16, 0.16], 1e-9)
near('pulsewidth, pulseperiod, dutycycle and pulsesep', (W['w'], W['p'], W['d'], W['sp']), [0.65, 0.65, 1.1, 0.65 / 1.1, 0.45], 1e-9)
near('midcross and slewrate', (W['m'], W['sr']), [0.55, 1.2, 1.65, 2.3, 10, -5, 10, -5], 1e-9)
near('overshoot: 10% past the high state, none after the others', a(W['os']).reshape(-1), [10, 0, 0, 0], 1e-9)
near('settlingtime: from the mid crossing into the 2% band', W['st'], [[0.08], [0.1], [0.05], [0.1]], 1e-9)
near('undershoot: none here', W['us'], np.zeros((4, 1)))
W, _ = run("close all; fs = 100; t = (0:299)/fs; x = interp1([0 0.5 0.6 1.1 1.3 1.6 1.7 2.2 2.4 3], [0 0 1 1 0 0 1 1 0 0], t); "
           "risetime(x, fs); yl = ylim; L = findobj(gca, 'Type', 'constantline'); v = sort(cell2mat(get(L, 'Value')))';")
near('risetime drawn: room above and below the levels, the state levels and the 10% and 90% references marked', (W['yl'], W['v']),
     ([[-0.1, 1.1]], [[0, 0.1, 0.9, 1]]), 1e-9)

# ---- delays, warping --------------------------------------------------------------------------------------------------------------------

W, _ = run("D = finddelay([0 0 1 2 3 0 0 0], [0 0 0 0 1 2 3 0]); D2 = finddelay([0 0 0 0 1 2 3 0], [0 0 1 2 3 0 0 0]); [xa, ya, D3] = alignsignals([1 2 3 0 0], [0 0 1 2 3]);")
near('finddelay: y behind x, and ahead', (W['D'], W['D2']), [2, -2])
near('alignsignals: the earlier one delayed', (W['xa'], W['D3']), [0, 0, 1, 2, 3, 0, 0, 2])


def dtw_ref(x, y):
    n, m = len(x), len(y)
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i, j] = abs(x[i - 1] - y[j - 1]) + min(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])
    return D[n, m]


xa_, ya_ = rs.standard_normal(40), rs.standard_normal(55)
W, _ = run(f"[d, ix, iy] = dtw({xa_.tolist()}, {ya_.tolist()}); x = {xa_.tolist()}; y = {ya_.tolist()}; s = sum(abs(x(ix) - y(iy)));")
near('dtw: the dynamic program written out', W['d'], dtw_ref(xa_, ya_), 1e-12)
near('dtw: the path adds up to the distance', W['s'], W['d'], 1e-12)
W, _ = run("d0 = dtw([1 2 3], [1 2 2 3]); de = edr([1 2 3 4], [1 2 4], 0.1); de2 = edr([1 2 3], [1.05 2.2 3], 0.1);")
near('dtw of a stretched copy is 0; edr counts edits', (W['d0'], W['de'], W['de2']), [0, 1, 1])

W, _ = run("fs = 1000; t = (0:999)'/fs; x = sin(2*pi*5*t) + 0.5*sin(2*pi*60*t); [imf, res] = emd(x); rec = max(abs(sum(imf, 2) + res - x));"
           "e1 = max(abs(imf(100:900, 1) - 0.5*sin(2*pi*60*t(100:900)))); [u, ru, iu] = vmd(x, 'NumIMF', 2);"
           "v1 = max(abs(u(50:950, 1) - 0.5*sin(2*pi*60*t(50:950)))); v2 = max(abs(u(50:950, 2) - sin(2*pi*5*t(50:950)))); cf = iu.CentralFrequencies*fs;")
C('emd: the IMFs and the residual add up to the signal', a(W['rec']) < 1e-12, W['rec'])
C('emd: the first IMF is the fast tone', a(W['e1']) < 0.01, W['e1'])
C('vmd: the two tones', a(W['v1']) < 0.01 and a(W['v2']) < 0.02, (W['v1'], W['v2']))
C('vmd: the faster mode first, its centre near 60 Hz', abs(a(W['cf'])[0] - 60) < 1.0, W['cf'])
W, _ = run("x = cos(2*pi*100*(0:255)'/1000); [d, f] = wvd(x, 1000); [~, k] = max(d(:, 128)); fw = f(k); [ds] = wvd(x, 1000, 'smoothedPseudo'); [~, k2] = max(ds(:, 128)); fs2 = f(k2);"
           "ifq = instfreq(cos(2*pi*(50*(0:999)'/1000 + 20*((0:999)'/1000).^2)), 1000, 'Method', 'hilbert');")
C('wvd: a tone concentrates at its frequency', abs(a(W['fw']) - 100) < 2 and abs(a(W['fs2']) - 100) < 2, (W['fw'], W['fs2']))
near('instfreq (hilbert): a linear chirp', a(W['ifq'])[[199, 499, 799]].reshape(-1), 50 + 40 * np.array([0.199, 0.499, 0.799]), 1e-3)

# ---- special functions, matrices, quadv ----------------------------------------------------------------------------------------------------

from scipy import special as SP  # noqa: E402
xs = np.array([0.3, 1.0, 2.5, 7.0])
W, _ = run(f"x = {xs.tolist()}; s = sinint(x); c = cosint(x); d = dawson(x); fs = fresnels(x); fc = fresnelc(x); cn = cosint(-2);")
near('sinint and cosint: scipy.special.sici', (W['s'], W['c']), (SP.sici(xs)[0], SP.sici(xs)[1]), 1e-14)
near('dawson, fresnels, fresnelc: scipy.special', (W['d'], W['fs'], W['fc']), (SP.dawsn(xs), SP.fresnel(xs)[0], SP.fresnel(xs)[1]), 1e-14)
near('cosint of a negative number: Ci(2) + i*pi', W['cn'], SP.sici(2.0)[1] + 1j * np.pi, 1e-14)
W, _ = run("p = charpoly([1 2; 3 4]); m = minpoly([2 1 0; 0 2 0; 0 0 2]); A = [4 1; 2 3]; [V, J] = jordan(A); res = norm(A*V - V*J); m2 = minpoly([1 1; 0 1]);"
           "[Q, n] = quadv(@(x) [x, x.^2; sin(x), exp(x)], 0, 1);")
near('charpoly: det(xI - A)', W['p'], [[1, -5, -2]])
near('minpoly: (x - 2)^2 for a Jordan block and one more eigenvalue 2', (W['m'], W['m2']), [1, -4, 4, 1, -2, 1])
C('jordan: A*V = V*J with J diagonal here', a(W['res']) < 1e-12 and np.allclose(np.sort(np.diag(a(W['J']))), [2, 5]), W['J'])
near('quadv: an array-valued integral', W['Q'], [[0.5, 1 / 3], [1 - math.cos(1), math.e - 1]], 1e-8)

# ---- control systems --------------------------------------------------------------------------------------------------------------------

W, _ = run("G = tf(1, [1 2 1]); w = logspace(-1, 1, 7); F = frd(G, w); H = frdata(F, 'v'); Hg = squeeze(freqresp(G, w));"
           "F2 = 2*F + 1; H2 = frdata(F2, 'v'); Fc = feedback(F, 1); Hc = frdata(Fc, 'v'); Gc = squeeze(freqresp(feedback(G, 1), w)); FG = F*G; Hm = frdata(FG, 'v');"
           "[m, ph] = bode(F); mg = squeeze(m);")
near("frd: a model's response at the frequencies", W['H'], W['Hg'], 1e-14)
near('frd: arithmetic and feedback at each frequency', (W['H2'], W['Hc'], W['Hm']), (2 * a(W['Hg']) + 1, W['Gc'], a(W['Hg']) ** 2), 1e-13)
near('bode of an frd model: its gains', W['mg'], np.abs(a(W['Hg'])), 1e-14)
W, _ = run("w = logspace(-1, 1, 7); g = tf(1, [1 1]); g.InputName = 'u'; g.OutputName = 'y'; Cn = pid(2, 1); Cn.InputName = 'e'; Cn.OutputName = 'u';"
           "T = connect(g, Cn, sumblk('e = r - y'), 'r', 'y'); a1 = squeeze(freqresp(T, w)); a2 = squeeze(freqresp(feedback(g*Cn, 1), w));"
           "Tq = connect(append(tf(2, [1 3]), tf(1, [1 0])), [2 1; 1 -2], 1, 2); b1 = squeeze(freqresp(Tq, w)); b2 = squeeze(freqresp(feedback(tf(1, [1 0])*tf(2, [1 3]), 1), w));"
           "Ap = append(tf(1, [1 1]), ss(-2, 1, 1, 0)); sa = size(Ap); Gd = c2d(tf(1, [1 2 1]), 0.1); d1 = squeeze(freqresp(d2d(Gd, 0.2), w)); d2 = squeeze(freqresp(c2d(tf(1, [1 2 1]), 0.2), w));")
near('connect by names: the loop feedback closes', W['a1'], W['a2'], 1e-12)
near('connect by indices: the same', W['b1'], W['b2'], 1e-12)
near('append: the inputs and outputs side by side', W['sa'], [[2, 2]])
near('d2d: resampled as c2d at the new rate would make it', W['d1'], W['d2'], 1e-10)
W, _ = run("A = [1 1 0; 0 1 0; 0 0 2]; B = [0; 1; 0]; Cm = [1 0 1]; [Ab, Bb, Cb, T, k] = ctrbf(A, B, Cm); r1 = norm(T*A*T' - Ab); r2 = norm(T*T' - eye(3));"
           "[Ao, Bo, Co, To, ko] = obsvf([1 0; 0 2], [1; 1], [1 0]);")
Ab, Bb, k = a(W['Ab']), a(W['Bb']).reshape(-1), a(W['k']).reshape(-1)
C('ctrbf: an orthogonal T, Abar = T*A*T\'', a(W['r1']) < 1e-12 and a(W['r2']) < 1e-12, (W['r1'], W['r2']))
C('ctrbf: the uncontrollable state first, cut off from the input and the others', abs(Bb[0]) < 1e-12 and np.all(np.abs(Ab[0, 1:]) < 1e-12) and k.sum() == 2 and abs(Ab[0, 0] - 2) < 1e-12, (Ab, Bb, k))
Ao, Co, ko = a(W['Ao']), a(W['Co']).reshape(-1), a(W['ko']).reshape(-1)
C('obsvf: the unobservable state first (C zero there, and the block below it)', abs(Co[0]) < 1e-12 and abs(Ao[1, 0]) < 1e-12 and ko.sum() == 1 and abs(Ao[0, 0] - 2) < 1e-12, (Ao, Co, ko))
from scipy.linalg import solve_continuous_are  # noqa: E402
W, _ = run("K = lqi(ss(tf(1, [1 1])), diag([1 2]), 1);")
Aa, Ba = np.array([[-1.0, 0], [-1, 0]]), np.array([[1.0], [0]])
X = solve_continuous_are(Aa, Ba, np.diag([1.0, 2.0]), np.eye(1))
near('lqi: lqr on the plant with the integrator of the error', W['K'], (Ba.T @ X).reshape(1, -1), 1e-10)
W, _ = run("G = tf(1, [1 3 3 1]); [C1, i1] = pidtune(G, 'PI'); s1 = i1.Stable; pm1 = i1.PhaseMargin; wc1 = i1.CrossoverFrequency;"
           "L = C1*G; mg = abs(squeeze(freqresp(L, wc1))); [C2, i2] = pidtune(G, 'PID', 0.5); pm2 = i2.PhaseMargin; s2 = i2.Stable; cl = pole(feedback(C2*G, 1)); mr = max(real(cl));"
           "S = lsiminfo([0 1 2 1.5 1.1 1.02 1.0 1.0], 0:7, 1); st = S.SettlingTime; mx = S.Max;")
C('pidtune PI: stable, 60 degrees of phase margin where the loop gain is 1', bool(a(W['s1'])) and abs(a(W['pm1']) - 60) < 1e-6 and abs(a(W['mg']) - 1) < 1e-9,
  (W['s1'], W['pm1'], W['mg']))
C('pidtune PID at a given crossover: stable with the margin', bool(a(W['s2'])) and abs(a(W['pm2']) - 60) < 1e-6 and a(W['mr']) < 0, (W['pm2'], W['mr']))
near('lsiminfo: settling (2% of the largest error) and the maximum', (W['st'], W['mx']), [5, 2], 1e-12)

# ---- statistics -----------------------------------------------------------------------------------------------------------------------------

from scipy.stats import rankdata  # noqa: E402
v = rs.integers(0, 6, 25).astype(float)
W, _ = run(f"[r, t] = tiedrank({v.tolist()}); b = tiedrank([1 2 3 4 5], 0, 1);")
_, counts = np.unique(v, return_counts=True)
near("tiedrank: scipy.stats.rankdata's average ranks and the tie adjustment", (W['r'], W['t']), (rankdata(v), np.sum(counts ** 3 - counts) / 2), 1e-12)
near('tiedrank: ranks from both ends', W['b'], [[1, 2, 3, 2, 1]])

Xm = rs.standard_normal((300, 2))
eta = np.column_stack([0.5 + Xm @ [1, -1], -0.3 + Xm @ [0.5, 0.8], np.zeros(300)])
Pm = np.exp(eta)
Pm /= Pm.sum(1, keepdims=True)
ym = np.array([rs.choice(3, p=p) for p in Pm]) + 1
W, _ = run(f"X = {mat(Xm)}; y = {ym.tolist()}'; [B, dev] = mnrfit(X, y); pr = mnrval(B, X(1:6, :));")
mn = sm.MNLogit(ym, sm.add_constant(Xm)).fit(disp=0, tol=1e-12, maxiter=500)
near("mnrfit nominal: statsmodels' MNLogit probabilities", W['pr'], mn.predict(sm.add_constant(Xm)[:6]), 1e-6)
near("mnrfit nominal: the deviance, -2 log-likelihood", W['dev'], -2 * mn.llf, 1e-8)
lat = Xm @ [1.0, -0.5] + rs.logistic(size=300)
yo = np.digitize(lat, [-1, 0.5]) + 1
W, _ = run(f"X = {mat(Xm)}; y = {yo.tolist()}'; [B, dev] = mnrfit(X, y, 'model', 'ordinal'); pr = mnrval(B, X(1:6, :), 'model', 'ordinal');")
om = OrderedModel(yo, Xm, distr='logit').fit(method='bfgs', disp=0, maxiter=5000, gtol=1e-10)
near("mnrfit ordinal: statsmodels' OrderedModel probabilities", W['pr'], om.predict(Xm[:6]), 1e-5)
C("mnrfit ordinal: a deviance at least as small as statsmodels'", a(W['dev']) <= -2 * om.llf + 1e-6, (W['dev'], -2 * om.llf))
near('mnrfit ordinal: slopes with the opposite sign to the latent model (alpha_j + x*beta)', a(W['B']).reshape(-1)[2:], -om.params[:2], 1e-3)

ng, G = 120, 12
g = np.repeat(np.arange(G), ng // G)
xl = rs.standard_normal(ng)
yl = 1.5 + 2.0 * xl + rs.standard_normal(G)[g] * 0.8 + rs.standard_normal(G)[g] * 0.4 * xl + rs.standard_normal(ng) * 0.5
df = pd.DataFrame({'y': yl, 'x': xl, 'g': g})
base = f"x = {xl.tolist()}'; y = {yl.tolist()}'; g = {(g + 1).tolist()}'; tbl = table(x, y, categorical(g), 'VariableNames', {{'x', 'y', 'g'}});"
for reml in (False, True):
    for form, ref in (('y ~ x + (1 | g)', None), ('y ~ x + (1 + x | g)', '~x')):
        W, _ = run(base + f"m = fitlme(tbl, '{form}', 'FitMethod', '{'REML' if reml else 'ML'}'); b = fixedEffects(m); ll = m.LogLikelihood; s2 = m.MSE;"
                          "[psi] = covarianceParameters(m); P = psi{1}; B = randomEffects(m); yh = fitted(m); rr = residuals(m);")
        md = smf.mixedlm('y ~ x', df, groups=df['g'], re_formula=ref).fit(reml=reml, method=['lbfgs'])
        kind = 'REML' if reml else 'ML'
        C(f"fitlme {form} ({kind}): a log-likelihood at least statsmodels' MixedLM's", a(W['ll']) >= md.llf - 1e-6, (W['ll'], md.llf))
        near(f'fitlme {form} ({kind}): the fixed effects', W['b'], md.fe_params.values.reshape(-1, 1), 1e-5)
        near(f'fitlme {form} ({kind}): the residual variance and the random effects\' covariance', (W['s2'], W['P']), (md.scale, np.asarray(md.cov_re)), 1e-3)
        near(f'fitlme {form} ({kind}): the predicted random effects', a(W['B']).reshape(-1),
             np.concatenate([np.asarray(v) for _, v in sorted(md.random_effects.items())]), 1e-4)
        near(f'fitlme {form} ({kind}): fitted plus residuals is the response', a(W['yh']).reshape(-1) + a(W['rr']).reshape(-1), yl, 1e-12)

lab = rs.integers(0, 2, 80)
sc = lab * 0.6 + rs.random(80)
W, _ = run(f"lab = {lab.tolist()}'; s = {sc.tolist()}'; r = rocmetrics(lab, [1 - s, s], [0 1]); auc = r.AUC; M = r.Metrics; nm = height(M);")
near("rocmetrics: scikit-learn's area under the curve for each class", W['auc'], [[roc_auc_score(lab == 0, 1 - sc), roc_auc_score(lab, sc)]], 1e-12)
W, _ = run(f"lab = {lab.tolist()}'; s = {sc.tolist()}'; f = figure('Visible', 'off'); plot(rocmetrics(lab, [1 - s, s], [0 1])); lg = legend; n = numel(lg.String); close(f);"
           "f = figure('Visible', 'off'); plot(1:3); hold on; plot([1 3], [1 3], 'HandleVisibility', 'off'); lg2 = legend; n2 = numel(lg2.String); close(f);")
near("rocmetrics' plot: a legend entry for each class, the chance line left out (its handle hidden)", (W['n'], W['n2']), [2, 1])
from scipy.spatial import cKDTree  # noqa: E402
P = rs.random((60, 3))
Qp = rs.random((5, 3))
W, _ = run(f"P = {mat(P)}; Q = {mat(Qp)}; ns = createns(P); [i, d] = knnsearch(ns, Q, 'K', 3); ns2 = createns(P, 'Distance', 'cityblock'); [i2] = knnsearch(ns2, Q); kd = class(ns);")
dk, ik = cKDTree(P).query(Qp, k=3)
dc, ic = cKDTree(P).query(Qp, k=1, p=1)
near("createns and knnsearch: SciPy's cKDTree", (W['i'], W['d'], W['i2']), (ik + 1, dk, (ic + 1).reshape(-1, 1)), 1e-12)
C('createns: a KDTreeSearcher for few columns', text(W['kd']) == 'KDTreeSearcher', W['kd'])
W, _ = run("rng(2); [d1, X1] = cordexch(3, 8); D1 = det(X1'*X1); [d2, X2] = cordexch(2, 9, 'quadratic'); D2 = det(X2'*X2); [~, X3] = rowexch(2, 9, 'quadratic'); D3 = det(X3'*X3);"
           "[da] = daugment([-1 -1; 1 1], 2); [dc, Xc] = dcovary(2, [-1; 1; -1; 1]); Dc = det(Xc'*Xc);")
near('cordexch: the full factorial for 3 factors in 8 runs (det 8^4)', W['D1'], 4096.0, 1e-9)
near("cordexch quadratic: rowexch's optimum", W['D2'], W['D3'], 1e-9)
C('daugment: the two runs that complete the factorial', sorted(map(tuple, a(W['da'])[2:].tolist())) == [(-1.0, 1.0), (1.0, -1.0)], W['da'])
near('dcovary: an orthogonal design with the covariate', W['Dc'], 256.0, 1e-9)
W, _ = run("q = qrandstream('sobol', 3); a1 = qrand(q, 4); a2 = qrand(q, 2); reset(q); a3 = qrand(q, 1); p = sobolset(3); b = p(1:6, :);")
near('qrandstream: the set read in order, and over again after reset', (W['a1'], W['a2'], W['a3']), (a(W['b'])[:4], a(W['b'])[4:6], a(W['b'])[:1]), 1e-15)
W, _ = run("[f, x] = ecdf([1 2 2 3 4 5 5 5]); [n, c] = ecdfhist(f, x, 4);")
near('ecdfhist: the probability in each bin over its width', (W['n'], W['c']), [0.375, 0.125, 0.125, 0.375, 1.5, 2.5, 3.5, 4.5], 1e-12)

# ---- wavelets -------------------------------------------------------------------------------------------------------------------------------

W, _ = run("fb = cwtfilterbank('SignalLength', 512, 'SamplingFrequency', 100); x = cos(2*pi*10*(0:511)/100)'; [c1, f1] = wt(fb, x); [c2, f2] = cwt(x, 100);"
           "e = max(abs(c1(:) - c2(:))); ef = max(abs(f1 - f2)); [psi, fq] = freqz(fb); np_ = size(psi); cf = centerFrequencies(fb); cfe = max(abs(cf - f1));"
           "d = dwtfilterbank('SignalLength', 256, 'Level', 4); [lo, hi] = framebounds(d); pb = dwtpassbands(d); d2 = dwtfilterbank('Wavelet', 'bior3.5', 'SignalLength', 256); [l2, h2] = framebounds(d2);")
C("cwtfilterbank: wt is cwt's transform, at cwt's frequencies", a(W['e']) == 0 and a(W['ef']) == 0 and a(W['cfe']) == 0, (W['e'], W['ef']))
near('dwtfilterbank: an orthogonal wavelet is a tight frame (bounds 1 and 1)', (W['lo'], W['hi']), [1, 1], 1e-10)
C('dwtfilterbank: a biorthogonal wavelet is not', a(W['h2']) - a(W['l2']) > 0.1, (W['l2'], W['h2']))
near('dwtpassbands: the octave bands', W['pb'], [[0.25, 0.5], [0.125, 0.25], [0.0625, 0.125], [0.03125, 0.0625], [0, 0.03125]])
W, _ = run("x = cos(2*pi*10*(0:511)/100)'; [sst, f] = wsst(x, 100); [~, k] = max(abs(sst(:, 256))); fk = f(k); xr = iwsst(sst); er = max(abs(xr(50:460) - x(50:460)));"
           "c = cwt(x, 'amor', 100, 'VoicesPerOctave', 32); xi = icwt(c, 'amor', 'VoicesPerOctave', 32)'; ei = max(abs(xr(50:460) - xi(50:460))); e0 = max(abs(xi(50:460) - x(50:460)));"
           "rng(0); t = (0:1023)'/100; a = sin(2*pi*5*t) + 0.2*randn(1024, 1); b = sin(2*pi*5*t + 1) + 0.2*randn(1024, 1);"
           "[wc, ~, fw] = wcoherence(a, b, 100); [~, k5] = min(abs(fw - 5)); c5 = mean(wc(k5, 200:800)); [~, k20] = min(abs(fw - 20)); c20 = mean(wc(k20, 200:800));"
           "y = sin(2*pi*0.05*(0:999)') + 0.6*sin(2*pi*0.2*(0:999)'); [mra, ~, info] = ewt(y, 'PeakThresholdPercent', 30); er2 = max(abs(sum(mra, 2) - y));"
           "e1 = max(abs(mra(100:900, 1) - sin(2*pi*0.05*(99:899)'))); pf = info.PeakFrequencies;")
C('wsst: a tone at its frequency', abs(a(W['fk']) - 10) < 0.1, W['fk'])
C('iwsst: the signal back as icwt gives it from the same transform (both within 2% here)', a(W['ei']) < 1e-3 and a(W['er']) < 0.02 and a(W['e0']) < 0.02, (W['ei'], W['er']))
C('wcoherence: high where the signals share a tone, low in the noise', a(W['c5']) > 0.95 and a(W['c20']) < 0.6, (W['c5'], W['c20']))
C('ewt: the components add up to the signal, a tone each', a(W['er2']) < 1e-12 and a(W['e1']) < 1e-3, (W['er2'], W['e1']))
near('ewt: the peaks found', W['pf'], [[0.05], [0.2]], 1e-12)

# ---- splines ---------------------------------------------------------------------------------------------------------------------------------

from scipy.interpolate import CubicSpline, make_smoothing_spline, make_interp_spline  # noqa: E402
xs_ = np.linspace(0, 5, 11)
ys_ = np.sin(xs_) + 0.1 * rs.standard_normal(11)
xq = np.linspace(0, 5, 41)
W, _ = run(f"x = {xs_.tolist()}; y = {ys_.tolist()}; xq = {xq.tolist()}; [pp, p] = csaps(x, y); v = fnval(pp, xq); v1 = csaps(x, y, 1, xq); v3 = csaps(x, y, 0.3, xq);"
           "[sp, vals, rho] = spaps(x, y, 0.02); err = sum((y - vals).^2); b = spapi(4, x, y); vb = fnval(b, xq); dpp = fnder(pp); ipp = fnint(pp);")
lam = (1 - a(W['p'])) / a(W['p'])
near('csaps: p = 1/(1 + h^3/6)', W['p'], 1 / (1 + 0.5 ** 3 / 6), 1e-14)
near("csaps: SciPy's make_smoothing_spline with lambda = (1-p)/p", W['v'], make_smoothing_spline(xs_, ys_, lam=float(lam))(xq).reshape(1, -1), 1e-8)
near("csaps p = 0.3: the same", W['v3'], make_smoothing_spline(xs_, ys_, lam=0.7 / 0.3)(xq).reshape(1, -1), 1e-8)
near("csaps p = 1: the natural cubic spline (SciPy's CubicSpline)", W['v1'], CubicSpline(xs_, ys_, bc_type='natural')(xq).reshape(1, -1), 1e-10)
near('spaps: the error is the tolerance', W['err'], 0.02, 1e-8)
near("spapi: SciPy's interpolating spline of that order", W['vb'], make_interp_spline(xs_, ys_, k=3)(xq).reshape(1, -1), 1e-10)
cs = make_smoothing_spline(xs_, ys_, lam=float(lam))
W2, _ = run(f"x = {xs_.tolist()}; y = {ys_.tolist()}; pp = csaps(x, y); d = fnval(fnder(pp), 2.3); i = fnval(fnint(pp), 4.1);")
near('fnder and fnint: the derivative and the integral from the start', (W2['d'], W2['i']), (cs.derivative()(2.3), cs.integrate(0, 4.1)), 1e-8)
W, _ = run("sm = spmak([0 0 0 1 2 3 3 3], [1 2 3 2 1]); v = fnval(sm, [0 1.5 3]); o = fnbrk(sm, 'order'); iv = fnbrk(sm, 'interval'); br = fnbrk(sm, 'breaks');"
           "ib = fnval(fnint(sm), 3);")
from scipy.interpolate import BSpline  # noqa: E402
bs = BSpline(np.array([0, 0, 0, 1, 2, 3, 3, 3.0]), np.array([1, 2, 3, 2, 1.0]), 2)
near("spmak: SciPy's BSpline with those knots", W['v'], bs(np.array([0, 1.5, 3.0])).reshape(1, -1), 1e-12)
near('fnbrk: order, interval, breaks', (W['o'], W['iv'], W['br']), [3, 0, 3, 0, 1, 2, 3])
near('fnint of a B-form: the integral over its interval', W['ib'], bs.integrate(0, 3), 1e-12)
W, _ = run("b = spmak(0:4, 1); v = fnval(b, [0 0.5 1 2 3 3.5 4]); dv = fnval(fnder(b), [0.5 1 2 3]); iv = fnval(fnint(b), [0 2 4]); "
           "bi = fnbrk(b, 'interval'); x = 0:5; sp = spapi(4, x, x.^3); dk = fnbrk(fnder(sp), 'knots'); kk = fnbrk(sp, 'knots');")
near('a single cubic B-spline (spmak(0:4, 1)) over its whole knot span: x^3/6 at the ends, 2/3 in the middle',
     (W['v'], W['bi']), [0, 0.5 ** 3 / 6, 1 / 6, 2 / 3, 1 / 6, 0.5 ** 3 / 6, 0, 0, 4], 1e-12)
near("its derivative (x^2/2 at the start) and its integral (area 1, half of it by the middle)", (W['dv'], W['iv']), [0.125, 0.5, 0, -0.5, 0, 0.5, 1], 1e-12)
near("fnder of a clamped spline keeps its inner knots", W['dk'], a(W['kk'])[:, 1:-1])

# ---- refusals --------------------------------------------------------------------------------------------------------------------------------

raises("stft(1:10)", 'at least as long as the window')
raises("tiedrank([1 2 2], 1)", 'tieflag 1')
raises("connect(tf(1, [1 1]), 'r', 'y')", 'needs a name')
raises("pidtune(tf(1, [1 1]), 'PX')", "The type is 'P'")
raises("fitlme(table([1;2;3], [1;2;3]), 'Var1 ~ Var2')", 'no random-effects term')
raises("csaps([1 2 3], [1 2 3], 2)", 'from 0 to 1')
raises("fnval(5, 1)", 'takes a spline')
raises("wt(5, 1:10)", 'filter bank')

sys.exit(C.done())
