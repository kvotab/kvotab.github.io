"""Wavelets, run natively (CPython with numpy and scipy), PyWavelets 1.7
the reference where it has the same thing: every filter (db1-38, sym2-20,
coif1-5, bior, rbio) and the exactness of db39-45; dwt and idwt in every
extension mode, signals shorter than the filter included; wavedec,
waverec, appcoef, detcoef, wrcoef, upcoef; the two-dimensional ones; swt
and swt2; wavefun and centfrq. The maximal overlap transform against its
textbook sum, the continuous transform on sinusoids, the empirical Bayes
rule against numerical integration, thresholds against their formulas.

    python3 test_wavelets.py          (from any folder)
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
from plab.values import Char, Cell  # noqa: E402

R.setup()
warnings.filterwarnings('ignore')

try:
    import pywt
except ImportError:
    print('PyWavelets (pip install PyWavelets) is the reference: skipped')
    sys.exit(0)


def run(code, **vals):
    R.BASE.clear()
    R.take_output()
    for k, v in vals.items():
        R.BASE[k] = np.atleast_2d(np.asarray(v, dtype=float))
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


rng = np.random.default_rng(11)

# ---- filters ---------------------------------------------------------------------------------------------------------------------------
bad = []
for name in pywt.wavelist(kind='discrete'):
    if name == 'dmey' or name.startswith('coif') and int(name[4:]) > 5:
        continue
    W, _ = run(f"[a1, a2, a3, a4] = wfilters('{name}');")
    p = pywt.Wavelet(name)
    tol = 1e-10 if name.startswith('sym') else 1e-12          # pywt's symlets are good to about 1e-11
    for k, ref in zip(('a1', 'a2', 'a3', 'a4'), (p.dec_lo, p.dec_hi, p.rec_lo, p.rec_hi)):
        g = a(W[k]).reshape(-1)
        if g.shape != (len(ref),) or not np.allclose(g, ref, atol=tol, rtol=0):
            bad.append(name)
            break
C('wfilters: every wavelet pywt has (db1-38, sym2-20, coif1-5, bior, rbio, haar) the same four filters', not bad, bad)
W, _ = run("o = []; m = []; for N = 39:45, h = wfilters(sprintf('db%d', N), 'r'); h = h(1, :); L = numel(h); k = 0:L-1; "
           "o(end+1) = max(abs(arrayfun(@(s) sum(h(1:L-2*s).*h(1+2*s:L)), 0:L/2-1) - [1, zeros(1, L/2-1)])); "
           "m(end+1) = max(abs(arrayfun(@(p) sum((-1).^k.*(k/L).^p.*h), 0:N-1))); end")
C('db39 to db45 (beyond pywt): orthonormal and N vanishing moments to rounding', a(W['o']).max() < 1e-14 and a(W['m']).max() < 1e-13, (a(W['o']).max(), a(W['m']).max()))
W, _ = run("f = dbwavf('db3'); s = symwavf('sym4'); c = coifwavf('coif2'); [a1, a2, a3, a4] = orthfilt(f); [b1, b2, b3, b4] = wfilters('db3'); "
           "q = qmf([1 2 3 4]); q1 = qmf([1 2 3 4], 1); [d1, d2, d3, d4] = biorfilt([-1 2 6 2 -1]/8, [1 2 1]/4); [e1, e2, e3, e4] = wfilters('bior2.2');")
near('dbwavf, symwavf, coifwavf: the scaling filters, summing to 1', (W['f'], W['s'], W['c']),
     (np.array(pywt.Wavelet('db3').rec_lo) / math.sqrt(2), np.array(pywt.Wavelet('sym4').rec_lo) / math.sqrt(2), np.array(pywt.Wavelet('coif2').rec_lo) / math.sqrt(2)), 1e-10)
near('orthfilt of dbwavf gives wfilters\' four', (W['a1'], W['a2'], W['a3'], W['a4']), (W['b1'], W['b2'], W['b3'], W['b4']), 1e-14)
near('qmf: reversed, every second sign changed', (W['q'], W['q1']), ([[4, -3, 2, -1]], [[-4, 3, -2, 1]]))
near('biorfilt of the spline pair (2, 2) gives bior2.2', (W['d1'], W['d2'], W['d3'], W['d4']), (W['e1'], W['e2'], W['e3'], W['e4']), 1e-14)

# ---- one dimension -----------------------------------------------------------------------------------------------------------------------
MODES = {'sym': 'symmetric', 'symw': 'reflect', 'asym': 'antisymmetric', 'asymw': 'antireflect', 'zpd': 'zero', 'sp0': 'constant',
         'sp1': 'smooth', 'ppd': 'periodic', 'per': 'periodization'}
bad = []
for name in ('haar', 'db4', 'sym5', 'coif2', 'bior3.5', 'rbio2.4'):
    pn = 'db1' if name == 'haar' else name
    for n in (2, 3, 5, 12, 37):
        x = rng.normal(size=n)
        for m, pm in MODES.items():
            W, _ = run(f"[cA, cD] = dwt(x, '{name}', 'mode', '{m}'); y = idwt(cA, cD, '{name}', 'mode', '{m}');", x=x)
            ra, rd = pywt.dwt(x, pn, pm)
            if not (np.allclose(a(W['cA']).ravel(), ra) and np.allclose(a(W['cD']).ravel(), rd)
                    and np.allclose(a(W['y']).ravel(), pywt.idwt(ra, rd, pn, pm))):
                bad.append((name, n, m))
C('dwt and idwt: six wavelets, lengths 2 to 37 (shorter than the filters too), all nine modes, as pywt', not bad, bad[:5])
x = rng.normal(size=29)
W, _ = run("[a1, d1] = dwt(x', 'db2'); [Lo, Hi] = wfilters('db2', 'd'); [a2, d2] = dwt(x, Lo, Hi); dwtmode('per', 'nodisp'); [a3, d3] = dwt(x, 'db2'); m = dwtmode('status'); "
           "dwtmode('sym', 'nodisp'); y = idwt(a3, d3, 'db2', 29, 'mode', 'per'); y0 = idwt([], d1, 'db2'); s = size(a1);", x=x)
near('dwt: a column gives columns; filters given instead of a name', (W['s'], W['a2']), ([[16, 1]], [pywt.dwt(x, 'db2')[0]]))
C('dwtmode sets the mode for later calls, and says it', W['m'].str() == 'per' and np.allclose(a(W['a3']).ravel(), pywt.dwt(x, 'db2', 'periodization')[0]), W['m'])
near('idwt: L keeps the middle; [] is zeros', (W['y'], W['y0']), ([x], pywt.idwt(None, pywt.dwt(x, 'db2')[1], 'db2').reshape(-1, 1)))
x = rng.normal(size=100)
W, _ = run("[c, l] = wavedec(x, 4, 'sym4'); y = waverec(c, l, 'sym4'); a2 = appcoef(c, l, 'sym4', 2); a4 = appcoef(c, l, 'sym4'); d3 = detcoef(c, l, 3); "
           "[e1, e3] = detcoef(c, l, [1 3]); dc = detcoef(c, l, 'cells'); n = numel(dc); s = wrcoef('a', c, l, 'sym4', 4); for k = 1:4, s = s + wrcoef('d', c, l, 'sym4', k); end; "
           "r2 = wrcoef('d', c, l, 'sym4', 2); [Ea, Ed] = wenergy(c, l); ml = wmaxlev(100, 'sym4');", x=x)
cs = pywt.wavedec(x, 'sym4', 'symmetric', level=4)
near('wavedec: c = [cA4 cD4 ... cD1] and l the lengths, as pywt', (W['c'], W['l']), (np.concatenate(cs), [len(v) for v in cs] + [100]))
near('waverec gives the signal back; appcoef at level 4 is cA4', (W['y'], W['a4']), ([x], [cs[0]]))
near('appcoef at level 2: from cA4, cD4, cD3', W['a2'], [pywt.waverec(cs[:3], 'sym4')[:len(pywt.wavedec(x, 'sym4', level=2)[0])]])
near('detcoef: one level, several outputs, every level in a cell', (W['d3'], W['e1'], W['e3'], W['n']), ([cs[2]], [cs[4]], [cs[2]], 4))
near('wrcoef: the approximation and the details add up to the signal', W['s'], [x])
ref = pywt.waverec([np.zeros_like(cs[0]), np.zeros_like(cs[1]), np.zeros_like(cs[2]), cs[3], np.zeros_like(cs[4])], 'sym4')
near('wrcoef of level-2 details: waverec with the rest zero', W['r2'], [ref])
near('wenergy: shares adding to 100, Ed(k) level k', (W['Ea'] + a(W['Ed']).sum(), W['Ed']), (100, [100 * np.array([np.sum(cs[5 - k] ** 2) for k in range(1, 5)]) / np.sum(np.concatenate(cs) ** 2)]))
near('wmaxlev: floor(log2(100/7))', W['ml'], 3)
xs = rng.normal(size=7)
W, _ = run("u1 = upcoef('a', x, 'db3', 1); u2 = upcoef('d', x, 'db3', 3); u3 = upcoef('a', x, 'db3', 2, 20);", x=xs)
near('upcoef: straight up in full, n steps, or the middle lx', (W['u1'], W['u2'], W['u3']),
     ([pywt.upcoef('a', xs, 'db3', 1)], [pywt.upcoef('d', xs, 'db3', 3)], [pywt.upcoef('a', xs, 'db3', 2, take=20)]))

# ---- two dimensions --------------------------------------------------------------------------------------------------------------------
X = rng.normal(size=(21, 30))
bad = []
for name, m, pm in (('db2', 'sym', 'symmetric'), ('sym4', 'per', 'periodization'), ('bior2.2', 'zpd', 'zero'), ('coif1', 'sp1', 'smooth')):
    W, _ = run(f"[A, H, V, D] = dwt2(X, '{name}', 'mode', '{m}'); Y = idwt2(A, H, V, D, '{name}', size(X), 'mode', '{m}');", X=X)
    rA, rest = pywt.dwt2(X, name, pm)
    if not (all(np.allclose(a(W[k]), r) for k, r in zip('AHVD', (rA,) + rest)) and np.allclose(a(W['Y']), X)):
        bad.append((name, m))
C('dwt2 and idwt2: cA, cH, cV, cD as pywt in four modes, and the image back', not bad, bad)
W, _ = run("[C, S] = wavedec2(X, 3, 'db2'); Y = waverec2(C, S, 'db2'); A2 = appcoef2(C, S, 'db2', 2); H1 = detcoef2('h', C, S, 1); [h, v, d] = detcoef2('all', C, S, 2); "
           "cc = detcoef2('c', C, S, 3); T = wrcoef2('a', C, S, 'db2', 3); for k = 1:3, T = T + wrcoef2('h', C, S, 'db2', k) + wrcoef2('v', C, S, 'db2', k) + wrcoef2('d', C, S, 'db2', k); end", X=X)
cs = pywt.wavedec2(X, 'db2', level=3)
flat = np.concatenate([cs[0].ravel('F')] + [m.ravel('F') for d in cs[1:] for m in d])
near('wavedec2: C packed column by column as [A3 H3 V3 D3 ... D1], S the sizes', (W['C'], W['S']), ([flat], [cs[0].shape] + [d[0].shape for d in cs[1:]] + [X.shape]))
near('waverec2 gives the image back; detcoef2 one kind, all three, compact', (W['Y'], W['H1'], W['h'], W['v'], W['d'], W['cc']),
     (X, cs[3][0], cs[2][0], cs[2][1], cs[2][2], [np.concatenate([m.ravel('F') for m in cs[1]])]))
near('appcoef2 at level 2', W['A2'], pywt.waverec2(cs[:2], 'db2')[:a(W['A2']).shape[0], :a(W['A2']).shape[1]])
near('wrcoef2: the parts add up to the image', W['T'], X)

# ---- stationary and maximal overlap --------------------------------------------------------------------------------------------------
x = rng.normal(size=64)
W, _ = run("[sa, sd] = swt(x, 3, 'db3'); y = iswt(sa, sd, 'db3'); c = swt(x, 3, 'bior2.2'); y2 = iswt(c, 'bior2.2');", x=x)
ref = pywt.swt(x, 'db3', 3)
near('swt: rows level 1 to 3, as pywt (its list deepest first)', (W['sa'], W['sd']), (np.vstack([r[0] for r in ref[::-1]]), np.vstack([r[1] for r in ref[::-1]])))
near('iswt gives the signal back, from [swa, swd] or swc', (W['y'], W['y2']), ([x], [x]))
X2 = rng.normal(size=(16, 24))
W, _ = run("[A, H, V, D] = swt2(X, 2, 'sym2'); Y = iswt2(A, H, V, D, 'sym2'); c = swt2(X, 2, 'sym2'); Y2 = iswt2(c, 'sym2'); s = size(c);", X=X2)
ref = pywt.swt2(X2, 'sym2', 2)
near('swt2: level k on page k, as pywt', tuple(a(W[k])[:, :, 0] for k in 'AHVD'), (ref[1][0],) + ref[1][1], 1e-9)
near('iswt2 gives the image back; one output is cat(3, H, V, D, A(:,:,end))', (W['Y'], W['Y2'], W['s']), (X2, X2, [[16, 24, 7]]))
raises("swt(1:30, 2, 'db1')", 'multiple of 2^2')
x = rng.normal(size=50)
W, _ = run("w = modwt(x, 'db2', 3); y = imodwt(w, 'db2'); m = modwtmra(w, 'db2'); e = [sum(x.^2), sum(w(:).^2)]; w0 = modwt(x); "
           "wr = modwt(x, 'sym4', 2, 'reflection'); yr = imodwt(wr, 'sym4', 'reflection'); mr = modwtmra(wr, 'sym4', 'reflection'); [Lo, Hi] = wfilters('db2', 'r'); wf = modwt(x, Lo, Hi, 3);", x=x)
g = np.array(pywt.Wavelet('db2').rec_lo) / math.sqrt(2)
h = np.array(pywt.Wavelet('db2').rec_hi) / math.sqrt(2)


def pw_modwt(x, g, h, J):
    """Percival and Walden: W_j,t = sum_l h_j,l X_(t-l mod N), h_j the level-j equivalent filter."""
    N, rows = x.size, []
    gj, hj = np.array([1.0]), None
    for j in range(1, J + 1):
        up = lambda f: np.concatenate([[v] + [0] * (2 ** (j - 1) - 1) for v in f])[:(f.size - 1) * 2 ** (j - 1) + 1]
        hj = np.convolve(gj, up(h))
        gj = np.convolve(gj, up(g))
        rows.append([sum(hj[l] * x[(t - l) % N] for l in range(hj.size)) for t in range(N)])
    rows.append([sum(gj[l] * x[(t - l) % N] for l in range(gj.size)) for t in range(N)])
    return np.array(rows)


near('modwt: Percival and Walden\'s sum, circular, by FFT; filters given work too', (W['w'], W['wf']), (pw_modwt(x, g, h, 3), pw_modwt(x, g, h, 3)), 1e-12)
xr = x[::-1][:48]
ref = pywt.swt(xr, 'db2', 3, norm=True, trim_approx=True)
W2, _ = run("w = modwt(fliplr(x), 'db2', 3);", x=xr)
sh_ok = all(any(np.allclose(np.roll(ref[3 - j][::-1], s), a(W2['w'])[j]) for s in range(48)) for j in range(3))
C('modwt of a reversed signal is pywt\'s normalized swt reversed, up to a circular shift (pywt correlates, modwt convolves)', sh_ok)
near('energy kept; imodwt gives x back; modwtmra rows sum to x', (W['e'][0, 0], W['y'], a(W['m']).sum(0)), (W['e'][0, 1], [x], x))
near('modwt by default: sym4 to level floor(log2(50)) = 5; reflection doubles, and comes back', (a(W['w0']).shape, a(W['wr']).shape, W['yr'], a(W['mr']).sum(0)), ((6, 50), (3, 100), [x], x))

# ---- wavelet functions -------------------------------------------------------------------------------------------------------------
bad = []
for name in ('haar', 'db2', 'sym4', 'coif1', 'db7'):
    W, _ = run(f"[phi, psi, xv] = wavefun('{name}', 6); cf = centfrq('{name}'); f = scal2frq([1 2 10], '{name}', 0.5);")
    r = pywt.Wavelet(name).wavefun(level=6)
    if not (all(np.allclose(a(W[k]).ravel(), r[i]) for i, k in enumerate(('phi', 'psi', 'xv')))
            and np.isclose(W['cf'], pywt.central_frequency(name, 8)) and np.allclose(a(W['f']).ravel(), pywt.scale2frequency(name, [1, 2, 10]) / 0.5)):
        bad.append(name)
C('wavefun, centfrq and scal2frq as pywt\'s wavefun, central_frequency and scale2frequency', not bad, bad)
W, _ = run("[p1, s1, p2, s2, xv] = wavefun('bior2.2', 5);")
r = pywt.Wavelet('bior2.2').wavefun(level=5)
C('wavefun of a biorthogonal wavelet: both pairs (pywt\'s wavelets have the other sign)', all(np.allclose(a(W[k]).ravel(), r[i]) or np.allclose(a(W[k]).ravel(), -np.asarray(r[i]))
                                                                                            for i, k in enumerate(('p1', 's1', 'p2', 's2', 'xv'))))

# ---- continuous transform ------------------------------------------------------------------------------------------------------------
fs = 1000.0
t = np.arange(2000) / fs
x = 3 * np.cos(2 * np.pi * 50 * t) + 1.5 * np.cos(2 * np.pi * 170 * t)
for wn, tol, nv in (('morse', 0.01, 10), ('amor', 0.02, 10), ('bump', 0.06, 32)):     # bump's narrow band needs closer scales
    W, _ = run(f"[wt, f, coi] = cwt(x, '{wn}', 1000, 'VoicesPerOctave', {nv}); xr = icwt(wt, '{wn}', 'VoicesPerOctave', {nv}); "
               f"[lo, hi] = cwtfreqbounds(2000, 1000, 'Wavelet', '{wn}', 'VoicesPerOctave', {nv});", x=x)
    wt, f = np.asarray(W['wt']), a(W['f']).ravel()
    mag = np.abs(wt[:, 1000])
    p50 = mag[(f > 40) & (f < 60)].max()
    p170 = mag[(f > 150) & (f < 190)].max()
    ok = abs(p50 - 3) < 0.05 and abs(p170 - 1.5) < 0.08 and abs(f[np.argmax(mag)] - 50) < 3 and np.all(np.diff(f) < 0)
    C(f'cwt ({wn}): abs(wt) is the amplitude at each cosine\'s frequency (3 at 50 Hz, 1.5 at 170 Hz); f falls row by row', ok, (p50, p170, f[np.argmax(mag)]))
    xr = a(W['xr']).ravel()
    err = np.linalg.norm((xr - x)[200:-200]) / np.linalg.norm(x[200:-200])
    C(f'icwt ({wn}): the signal back away from the ends, to {tol:.0%}', err < tol, err)
    near(f'cwtfreqbounds ({wn}): the range of cwt\'s f', (W['lo'], W['hi']), (f[-1], f[0]), 1e-12)
W, _ = run("[wt, f, coi] = cwt(x, 1000, 'VoicesPerOctave', 16, 'FrequencyLimits', [20 200]); [w2, f2] = cwt(x); [w3, f3] = cwt(x, 'amor', 'ExtendSignal', false); "
           "[w4, f4] = cwt(x, 1000, 'WaveletParameters', [3 120]);", x=x)
f, coi = a(W['f']).ravel(), a(W['coi']).ravel()
C('VoicesPerOctave and FrequencyLimits: 16 to an octave within 20 to 200 Hz', f.max() <= 200 + 1e-9 and f.min() >= 20 - 1e-9 and np.allclose(np.diff(np.log2(f)), -1 / 16), (f.min(), f.max()))
C('coi: highest at the ends, lowest in the middle; no sampling rate: cycles per sample', coi[0] > coi[1000] and coi[-1] > coi[1000] and a(W['f2']).max() < 0.5)
C('a wider Morse wavelet (P^2 = 120) has more scales; ExtendSignal false still a transform', np.asarray(W['w4']).shape[0] != np.asarray(W['wt']).shape[0] and np.asarray(W['w3']).shape[1] == 2000)
raises("cwt([1 2 3])", 'four samples')
raises("cwt(1:100, 'mexh')", 'is not')

# ---- thresholds and denoising ---------------------------------------------------------------------------------------------------------
x = rng.normal(size=200) * 1.3
x[:10] += 8


def sure(v):
    s = np.sort(np.abs(v)) ** 2
    n = v.size
    r = [(n - 2 * (i + 1) + s[:i + 1].sum() + (n - 1 - i) * s[i]) / n for i in range(n)]
    return math.sqrt(s[int(np.argmin(r))])


W, _ = run("t = [thselect(x, 'sqtwolog'), thselect(x, 'minimaxi'), thselect(x, 'rigrsure'), thselect(x, 'heursure'), thselect(randn(1, 20), 'minimaxi')]; "
           "s = wthresh([-3 -1 0 2 5], 's', 1.5); h = wthresh([-3 -1 0 2 5], 'h', 1.5);", x=x)
eta, crit = (np.sum(x ** 2) - 200) / 200, math.log2(200) ** 1.5 / math.sqrt(200)
near('thselect: sqrt(2 log n), the minimax formula, SURE, and the heuristic', W['t'],
     [[math.sqrt(2 * math.log(200)), 0.3936 + 0.1829 * math.log2(200), sure(x), math.sqrt(2 * math.log(200)) if eta < crit else min(sure(x), math.sqrt(2 * math.log(200))), 0]])
near('wthresh: soft and hard', (W['s'], W['h']), ([[-1.5, 0, 0, 0.5, 3.5]], [[-3, 0, 0, 2, 5]]))
N = 512
tt = np.linspace(0, 1, N)
clean = np.sin(4 * np.pi * tt) + (tt > 0.5)
noisy = clean + 0.25 * rng.normal(size=N)
W, _ = run("[c, l] = wavedec(x, 4, 'db4'); s = wnoisest(c, l, 1:4); [xd, cxd, lxd] = wden(x, 'heursure', 's', 'mln', 4, 'db4'); [xs, cs] = wden(x, 'sqtwolog', 'h', 'sln', 4, 'db4'); "
           "[thr, sorh, keep] = ddencmp('den', 'wv', x);", x=noisy)
cs4 = pywt.wavedec(noisy, 'db4', level=4)
sig = [np.median(np.abs(cs4[5 - k])) / 0.6744897501960817 for k in range(1, 5)]
near('wnoisest: median(abs(cD))/0.6745 at each level', W['s'], [sig])


def wden_ref(rule, sorh, scal):
    out_ = [cs4[0]]
    for k, d in enumerate(cs4[1:]):
        s = 1 if scal == 'one' else sig[0] if scal == 'sln' else np.median(np.abs(d)) / 0.6744897501960817
        z = d / s
        n = z.size
        if rule == 'sqtwolog':
            t = math.sqrt(2 * math.log(n))
        else:
            e, cr = (np.sum(z ** 2) - n) / n, math.log2(n) ** 1.5 / math.sqrt(n)
            t = math.sqrt(2 * math.log(n)) if e < cr else min(sure(z), math.sqrt(2 * math.log(n)))
        out_.append(pywt.threshold(d, t * s, 'soft' if sorh == 's' else 'hard'))
    return pywt.waverec(out_, 'db4')[:N], np.concatenate(out_)


r1, c1 = wden_ref('heursure', 's', 'mln')
r2, c2 = wden_ref('sqtwolog', 'h', 'sln')
near('wden: per-level thresholds (heursure, soft, noise per level; universal, hard, noise from level 1)', (W['xd'], W['cxd'], W['xs'], W['cs']), ([r1], [c1], [r2], [c2]), 1e-9)
d1 = pywt.dwt(noisy, 'db1')[1]
near('ddencmp: sqrt(2 log n) times the noise of the db1 details, soft, keep', (W['thr'], W['keep']), (math.sqrt(2 * math.log(N)) * np.median(np.abs(d1)) / 0.6744897501960817, 1))
from plab.builtins import wavelets as WV  # noqa: E402
from scipy.stats import norm  # noqa: E402
w = 0.3
mu = np.linspace(-30, 30, 600001)
dmu = mu[1] - mu[0]
ok = True
for z in (0.5, 1.5, 2.5, 3.5, 6.0, -2.7):
    cont = w * 0.25 * np.exp(-0.5 * np.abs(mu)) * norm.pdf(z - mu)
    atom = (1 - w) * norm.pdf(z)
    tot = atom + cont.sum() * dmu
    cdf = (np.cumsum(cont) * dmu + atom * (mu >= 0)) / tot
    med = mu[np.searchsorted(cdf, 0.5)]
    med = 0.0 if abs(med) < 1e-3 else med
    mean = (mu * cont).sum() * dmu / tot
    ok &= abs(WV._eb_rule(np.array([z]), w, 'median')[0] - med) < 2e-4 and abs(WV._eb_rule(np.array([z]), w, 'mean')[0] - mean) < 2e-4
C('the Bayes rule: posterior median and mean under zero-or-Laplace(0.5) equal numerical integration', ok)
res = {}
for m in ('Bayes', 'SURE', 'UniversalThreshold', 'Minimax', 'BlockJS', 'FDR'):
    W, _ = run(f"[y, d, o] = wdenoise(x, 'DenoisingMethod', '{m}'); n = numel(d); same = isequal(o{{end}}, d{{end}});", x=noisy)
    res[m] = (np.sqrt(np.mean((a(W['y']).ravel() - clean) ** 2)), W['n'], bool(W['same']))
rm = np.sqrt(np.mean((noisy - clean) ** 2))
C('wdenoise: every method at least halves the error; cells level 1 first, the approximation (kept) last', all(v[0] < rm / 2 and v[1] == 7 and v[2] for v in res.values()), (rm, res))
W, _ = run("Y = wdenoise([x', 2*x'], 3, 'Wavelet', 'db2', 'DenoisingMethod', 'SURE', 'ThresholdRule', 'Hard', 'NoiseEstimate', 'LevelDependent'); "
           "y1 = wdenoise(x', 3, 'Wavelet', 'db2', 'DenoisingMethod', 'SURE', 'ThresholdRule', 'Hard', 'NoiseEstimate', 'LevelDependent'); y2 = wdenoise(x, 'DenoisingMethod', {'FDR', 0.01});", x=noisy)
near('wdenoise: the columns of a matrix one by one; options', (a(W['Y'])[:, 0], a(W['Y'])[:, 1]), (a(W['y1']).ravel(), 2 * a(W['y1']).ravel()), 1e-12)
raises("wdenoise(randn(1, 64), 'DenoisingMethod', 'FDR', 'ThresholdRule', 'Soft')", "ThresholdRule is 'Hard'")
W, _ = run("Y = wcodemat([-4 0 2; 1 3 -1], 8); Yr = wcodemat([1 2 3; 4 6 8], 4, 'row', 0);")
near('wcodemat: 1..nb in proportion, over the matrix or by rows', (W['Y'], W['Yr']), ([[8, 1, 5], [3, 7, 3]], [[1, 3, 4], [1, 3, 4]]))
raises("dwt(1:10, 'db50')", 'db1 to db45')
raises("dwt(1:10, 'sym4', 'mode', 'foo')", 'extension mode')
raises("waverec(1:10, [3 3 5], 'db1')", 'do not match')

sys.exit(C.done())
