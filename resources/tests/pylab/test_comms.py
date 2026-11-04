"""Communications and audio features, run natively (CPython with numpy and
scipy): constellations (average power, Gray neighbours, round trips of
integers and bits, log-likelihood ratios in closed form for BPSK), awgn's
measured noise, error counts, bits and digits; berawgn against the closed
forms (BPSK, QPSK, square QAM by Cho and Yoon's formula, DPSK, FSK) and
against Monte Carlo runs (8-PSK, 4-PAM); rcosdesign against the formulas
written out here; the mel spectrogram and MFCCs against the same steps
written out with scipy; pitch on harmonic signals; the spectral descriptors
and zero-crossing rate against numpy.

    python3 test_comms.py          (from any folder)
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


def col(x):
    return f"{np.asarray(x, float).reshape(-1).tolist()}'"


def bits(k, n):
    return [(k >> (n - 1 - i)) & 1 for i in range(n)]


def popcount(v):
    return bin(int(v)).count('1')


# ---- constellations ---------------------------------------------------------------------------------------------------------

for M in (4, 16, 64):
    W, _ = run(f"y = qammod((0:{M - 1})', {M}); z = qamdemod(y, {M}); u = qammod((0:{M - 1})', {M}, 'UnitAveragePower', true); yb = qammod((0:{M - 1})', {M}, 'bin');")
    y = a(W['y']).reshape(-1)
    h = int(math.sqrt(M))
    ok = True
    for i in range(M):
        for j in range(M):
            if abs(abs(y[i] - y[j]) - 2) < 1e-9:
                ok &= popcount(i ^ j) == 1
    C(f'qammod {M}-QAM: neighbours differ in one bit (Gray), the levels odd numbers', ok and set(np.unique(y.real).tolist()) == set(range(-(h - 1), h, 2)))
    near(f'qammod {M}-QAM: average power 2(M-1)/3, unit with UnitAveragePower', (np.mean(np.abs(y) ** 2), np.mean(np.abs(a(W['u'])) ** 2)), (2 * (M - 1) / 3, 1.0), 1e-12)
    C(f'qamdemod {M}-QAM: the integers back', np.array_equal(a(W['z']).reshape(-1), np.arange(M)))
C("qammod: 0 at the top left; 'bin' runs down the first column", a(W['y'])[0, 0] == -7 + 7j and a(W['yb']).reshape(-1)[1] == -7 + 5j)
rb = np.random.default_rng(1).integers(0, 2, 4 * 50)
W, _ = run(f"b = {col(rb)}; y = qammod(b, 16, 'InputType', 'bit'); bb = qamdemod(y, 16, 'OutputType', 'bit'); k = qamdemod(y, 16);")
C('qammod bits: groups of four, the first the most significant, and back', np.array_equal(a(W['bb']).reshape(-1), rb)
  and np.array_equal(a(W['k']).reshape(-1), [int(''.join(str(int(v)) for v in rb[i:i + 4]), 2) for i in range(0, rb.size, 4)]))
W, _ = run("p = pskmod((0:7)', 8, pi/8); z = pskdemod(p, 8, pi/8); pb = pskmod((0:7)', 8, 0, 'bin'); q = pskmod([0 1 2 3], 4, pi/4);"
           "m = pammod((0:3)', 4); zm = pamdemod(m, 4); cu = qammod((0:3)', 4, [3 2 1 0]);")
ang = np.mod(np.angle(a(W['p']).reshape(-1)) - np.pi / 8, 2 * np.pi) / (2 * np.pi / 8)
pos = np.rint(ang).astype(int) % 8
C('pskmod 8-PSK: the positions in Gray order (neighbours one bit apart), the offset added', all(popcount(np.flatnonzero(pos == j)[0] ^ np.flatnonzero(pos == (j + 1) % 8)[0]) == 1 for j in range(8))
  and np.array_equal(a(W['z']).reshape(-1), np.arange(8)))
near("pskmod 'bin': the integers in order round the circle", a(W['pb']).reshape(-1), np.exp(2j * np.pi * np.arange(8) / 8), 1e-12)
near('pskmod QPSK with pi/4: the Gray points', a(W['q']).reshape(-1), np.exp(1j * (np.pi / 4 + np.pi / 2 * np.array([0, 1, 3, 2]))), 1e-12)
near('pammod: levels -3 -1 1 3 in Gray order, and back', (a(W['m']).reshape(-1), a(W['zm']).reshape(-1)), ([-3, -1, 3, 1], [0, 1, 2, 3]), 1e-12)
near('qammod with a mapping vector', a(W['cu']).reshape(-1), a(run("y = qammod((3:-1:0)', 4, 'bin');")[0]['y']).reshape(-1), 1e-12)
yv = np.array([0.3, -1.2, 2.0])
W, _ = run(f"y = {col(yv)}; L = pamdemod(y, 2, 0, 'bin', 'OutputType', 'llr', 'NoiseVariance', 0.5); La = pamdemod(y, 2, 0, 'bin', 'OutputType', 'approxllr', 'NoiseVariance', 0.5);"
           "Q = qamdemod(qammod((0:15)', 16) + 0.2, 16, 'OutputType', 'llr', 'NoiseVariance', 0.1); Qa = qamdemod(qammod((0:15)', 16) + 0.2, 16, 'OutputType', 'approxllr', 'NoiseVariance', 0.1);")
near('pamdemod BPSK: the log-likelihood ratio -4y/v, exact and approximate alike', (W['L'], W['La']), ((-4 * yv / 0.5).reshape(-1, 1), (-4 * yv / 0.5).reshape(-1, 1)), 1e-12)
C('qamdemod llr: the signs give the bits sent; approximate near exact', np.array_equal((a(W['Q']).reshape(-1) < 0).astype(int), np.concatenate([bits(k, 4) for k in range(16)]))
  and np.allclose(a(W['Q']), a(W['Qa']), rtol=0.05, atol=0.05))

# ---- noise, errors, bits -----------------------------------------------------------------------------------------------------

W, _ = run("x = ones(200000, 1); y = awgn(x, 10); s1 = awgn(x(1:5), 3, 0, 7); s2 = awgn(x(1:5), 3, 0, 7); c = awgn(complex(ones(200000, 1)), 0, 'measured');"
           "z = awgn(2*ones(200000, 1), 6, 'measured'); l = awgn(ones(200000, 1), 4, 1, 'linear');")
nz = a(W['y']).reshape(-1) - 1
near('awgn: noise of power 1/10 at 10 dB for a 0 dBW signal', np.var(nz), 0.1, 0.02)
C('awgn: a seed repeats the noise', np.array_equal(a(W['s1']), a(W['s2'])))
cz = a(W['c']).reshape(-1) - 1
near('awgn complex: half the power in each part', (np.var(cz.real), np.var(cz.imag)), (0.5, 0.5), 0.02)
near("awgn 'measured' and 'linear': the noise power from the signal's", (np.var(a(W['z']) - 2), np.var(a(W['l']) - 1)), (4 / 10 ** 0.6, 0.25), 0.02)
W, _ = run("[n, r, ind] = biterr([0 3 5 7], [1 3 4 0]); [n2, r2] = biterr([1 2], [1 2], 8); [ns, rs, loc] = symerr([1 2 3 4], [1 0 3 0]);"
           "b = int2bit([5; 3], 4); i = bit2int(b, 4); bl = int2bit(6, 3, false); d = de2bi([1 6], 4); dl = de2bi(6, [], 'left-msb'); d3 = de2bi(10, [], 3);"
           "e = bi2de([0 1 1]); el = bi2de([0 1 1], 'left-msb'); [g, mp] = bin2gray(0:7, 'psk', 8); gb = gray2bin(g, 'psk', 8); gq = gray2bin(bin2gray(0:15, 'qam', 16), 'qam', 16);")
near('biterr: the differing bits, over 4 elements of 3 bits', (W['n'], W['r'], W['ind']), (1 + 0 + 1 + 3, 5 / 12, [[1, 0, 1, 3]]))
near('biterr: no errors', (W['n2'], W['r2']), (0, 0))
near('symerr: the symbols that differ and where', (W['ns'], W['rs'], W['loc']), (2, 0.5, [[0, 1, 0, 1]]))
near('int2bit and bit2int: most significant first, and back; least first when asked', (W['b'], W['i'], W['bl']), ([[0], [1], [0], [1], [0], [0], [1], [1]], [[5], [3]], [[0], [1], [1]]))
near('de2bi: right-msb rows, left-msb, base 3', (W['d'], W['dl'], W['d3']), ([[1, 0, 0, 0], [0, 1, 1, 0]], [[1, 1, 0]], [[1, 0, 1]]))
near('bi2de: right-msb and left-msb', (W['e'], W['el']), (6, 3))
near('bin2gray and gray2bin: k xor k/2 and back', (W['g'], W['gb'], W['gq']), ([[0, 1, 3, 2, 6, 7, 5, 4]], [list(range(8))], [list(range(16))]))

# ---- theoretical error rates -----------------------------------------------------------------------------------------------------

from scipy.special import erfc  # noqa: E402
Qf = lambda x: 0.5 * erfc(np.asarray(x) / math.sqrt(2))
eb = np.array([0.0, 4.0, 8.0])
g = 10 ** (eb / 10)
W, _ = run("[b2, s2] = berawgn([0 4 8], 'psk', 2); [b4, s4] = berawgn([0 4 8], 'psk', 4); [b16, s16] = berawgn([0 4 8], 'qam', 16); [b64] = berawgn(10, 'qam', 64);"
           "d = berawgn([0 4 8], 'dpsk', 2); fn = berawgn([0 4 8], 'fsk', 2); fc = berawgn([0 4 8], 'fsk', 2, 'coherent'); [b8, s8] = berawgn(8, 'psk', 8); [b4p, s4p] = berawgn(8, 'pam', 4);")
near('berawgn BPSK and QPSK: Q(sqrt(2Eb/N0)); the QPSK symbol rate 1 - (1 - p)^2', (W['b2'], W['b4'], W['s4']), ([Qf(np.sqrt(2 * g))], [Qf(np.sqrt(2 * g))], [1 - (1 - Qf(np.sqrt(2 * g))) ** 2]), 1e-12)


def cho_yoon(M, gb):
    """Gray square M-QAM bit error rate (Cho and Yoon, 2002)."""
    sm = int(math.sqrt(M))
    out = 0
    for k in range(1, int(math.log2(sm)) + 1):
        pk = 0
        for i in range(int((1 - 2 ** -k) * sm)):
            w = (-1) ** math.floor(i * 2 ** (k - 1) / sm) * (2 ** (k - 1) - math.floor(i * 2 ** (k - 1) / sm + 0.5))
            pk += w * erfc((2 * i + 1) * math.sqrt(3 * math.log2(M) * gb / (2 * (M - 1))))
        out += pk / sm
    return out / math.log2(sm)


near("berawgn 16-QAM and 64-QAM: Cho and Yoon's closed form", (W['b16'], W['b64']), ([[cho_yoon(16, x) for x in g]], cho_yoon(64, 10.0)), 1e-12)
p16 = 3 / 4 * erfc(np.sqrt(4 * g / 10))
near('berawgn 16-QAM: the symbol error rate 1 - (1 - P_PAM)^2', W['s16'], [1 - (1 - p16) ** 2], 1e-12)
TH = {k: W[k] for k in ('b8', 's8', 'b4p', 's4p')}
near('berawgn DPSK and FSK: 0.5 exp(-Eb/N0), 0.5 exp(-Eb/2N0), Q(sqrt(Eb/N0))', (W['d'], W['fn'], W['fc']), ([0.5 * np.exp(-g)], [0.5 * np.exp(-g / 2)], [Qf(np.sqrt(g))]), 1e-12)
rm = np.random.default_rng(5)
N = 400000
k8 = rm.integers(0, 8, N)
W, _ = run(f"rng(9); x = randi([0 7], {N}, 1); y = awgn(pskmod(x, 8), 8 + 10*log10(3), 'measured'); [nb, rb] = biterr(x, pskdemod(y, 8)); [ns, rs] = symerr(x, pskdemod(y, 8));"
           f"x4 = randi([0 3], {N}, 1); y4 = awgn(pammod(x4, 4), 8 + 10*log10(4), 'measured'); [nb4, rb4] = biterr(x4, pamdemod(y4, 4)); [ns4, rs4] = symerr(x4, pamdemod(y4, 4));")
sd = lambda p, n: 4 * math.sqrt(p * (1 - p) / n)
C('berawgn 8-PSK: Monte Carlo of the bits and symbols agrees', abs(W['rb'] - TH['b8']) < sd(TH['b8'], 3 * N) + 1e-5 and abs(W['rs'] - TH['s8']) < sd(TH['s8'], N) + 1e-5,
  f"{W['rb']} {TH['b8']} {W['rs']} {TH['s8']}")
C('berawgn 4-PAM: Monte Carlo agrees', abs(W['rb4'] - TH['b4p']) < sd(TH['b4p'], 2 * N) + 1e-5 and abs(W['rs4'] - TH['s4p']) < sd(TH['s4p'], N) + 1e-5,
  f"{W['rb4']} {TH['b4p']} {W['rs4']} {TH['s4p']}")

# ---- raised cosine ------------------------------------------------------------------------------------------------------------------


def rc_ref(beta, span, sps, shape):
    t = (np.arange(span * sps + 1) - span * sps / 2) / sps
    h = np.empty(t.size)
    for i, ti in enumerate(t):
        if shape == 'normal':
            h[i] = (math.pi / 4) * np.sinc(1 / (2 * beta)) if abs(abs(2 * beta * ti) - 1) < 1e-12 else np.sinc(ti) * math.cos(math.pi * beta * ti) / (1 - (2 * beta * ti) ** 2)
        elif ti == 0:
            h[i] = 1 - beta + 4 * beta / math.pi
        elif abs(abs(4 * beta * ti) - 1) < 1e-12:
            h[i] = beta / math.sqrt(2) * ((1 + 2 / math.pi) * math.sin(math.pi / (4 * beta)) + (1 - 2 / math.pi) * math.cos(math.pi / (4 * beta)))
        else:
            h[i] = (math.sin(math.pi * ti * (1 - beta)) + 4 * beta * ti * math.cos(math.pi * ti * (1 + beta))) / (math.pi * ti * (1 - (4 * beta * ti) ** 2))
    return h / np.linalg.norm(h)


W, _ = run("h = rcosdesign(0.25, 6, 4); n = rcosdesign(0.5, 4, 8, 'normal'); s = rcosdesign(0.5, 4, 2);")
near('rcosdesign sqrt: the formula, its limits at 0 and at 1/(4 beta) symbols, unit energy', W['h'], rc_ref(0.25, 6, 4, 'sqrt').reshape(1, -1), 1e-12)
near("rcosdesign 'normal': the formula and the limit at 1/(2 beta)", W['n'], rc_ref(0.5, 4, 8, 'normal').reshape(1, -1), 1e-12)
nn = a(W['n']).reshape(-1)
C("rcosdesign 'normal': zero at every other symbol time (no intersymbol interference)", np.allclose(nn[np.arange(0, nn.size, 8)][np.arange(5) != 2], 0, atol=1e-12))
near('rcosdesign sqrt at 1/(4 beta) symbols (a limit)', a(W['s']).reshape(-1), rc_ref(0.5, 4, 2, 'sqrt'), 1e-12)
W, _ = run("rng(2); x = pskmod(randi([0 3], 200, 1), 4, pi/4); u = upfirdn(x, rcosdesign(0.35, 6, 8), 8); f = eyediagram(u(49:end-48), 16); nf = numel(findall(f, 'Type', 'axes')); g = scatterplot(x); ng = numel(findall(g, 'Type', 'line'));")
C('eyediagram and scatterplot: figures with the in-phase and quadrature eyes, and the points', W['nf'] == 2.0 and W['ng'] == 1.0)

# ---- audio features --------------------------------------------------------------------------------------------------------------

fs = 16000
t = np.arange(fs) / fs
x = np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 440 * t) + 0.25 * np.sin(2 * np.pi * 660 * t)
W, _ = run("m = hz2mel([0 700 1000]); f = mel2hz(hz2mel([123 4567]));")
near('hz2mel and mel2hz: 2595 log10(1 + f/700) and back', (W['m'], W['f']), ([[0, 2595 * math.log10(2), 2595 * math.log10(1 + 1000 / 700)]], [[123, 4567]]), 1e-9)
xs = np.sin(2 * np.pi * 1000 * t) + 0.3 * np.random.default_rng(3).standard_normal(fs)


def frames(sig, w, hop):
    n = (sig.size - w.size) // hop + 1
    return np.stack([sig[k * hop:k * hop + w.size] * w for k in range(n)])


def mel_ref(nfft, nb, lo, hi, norm=True):
    m = lambda f: 2595 * np.log10(1 + f / 700)
    im = lambda v: 700 * (10 ** (v / 2595) - 1)
    e = im(np.linspace(m(lo), m(hi), nb + 2))
    f = np.arange(nfft // 2 + 1) * fs / nfft
    B = np.zeros((nb, f.size))
    for b in range(nb):
        B[b] = np.clip(np.minimum((f - e[b]) / (e[b + 1] - e[b]), (e[b + 2] - f) / (e[b + 2] - e[b + 1])), 0, None) * (2 / (e[b + 2] - e[b]) if norm else 1)
    return B, e[1:-1]


hann = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(480) / 480)
P = np.abs(np.fft.rfft(frames(xs, hann / hann.sum(), 160), 480, axis=1)) ** 2
B, ctr = mel_ref(480, 32, 0, 8000)
W, _ = run(f"x = {col(xs)}; [S, F, T] = melSpectrogram(x, {fs}); [S2] = melSpectrogram(x, {fs}, 'NumBands', 16, 'FrequencyRange', [100 4000], 'SpectrumType', 'magnitude');")
near('melSpectrogram: the steps written out (periodic Hann, normalized, power, mel triangles)', (W['S'], W['F'], W['T']), ((B @ P.T), ctr.reshape(-1, 1), ((np.arange(P.shape[0]) * 160 + 480) / fs).reshape(-1, 1)), 1e-9)
B2, _ = mel_ref(480, 16, 100, 4000)
near('melSpectrogram: bands, a range and the magnitude spectrum', W['S2'], B2 @ np.sqrt(P.T), 1e-9)
from scipy.fft import dct  # noqa: E402
ham = 0.54 - 0.46 * np.cos(2 * np.pi * np.arange(480) / 480)
Fr = frames(x, ham, 160)
P2 = np.abs(np.fft.rfft(Fr, 480, axis=1)) ** 2
B40, _ = mel_ref(480, 40, 0, 8000)
cc = dct(np.log(P2 @ B40.T), type=2, norm='ortho', axis=1)[:, :13]
le = np.log(np.sum((frames(x, np.ones(480), 160)) ** 2, axis=1))
ref = np.column_stack([le, cc])
W, _ = run(f"x = {col(x)}; [c, d, dd, loc] = mfcc(x, {fs}); c2 = mfcc(x, {fs}, 'LogEnergy', 'ignore', 'NumCoeffs', 20); c3 = mfcc(x, {fs}, 'LogEnergy', 'replace');")
near('mfcc: log energy, then the DCT of the log mel energies (the steps written out)', W['c'], ref, 1e-9)
Pd = np.concatenate([np.repeat(ref[:1], 4, 0), ref, np.repeat(ref[-1:], 4, 0)])
dref = sum(m * (Pd[4 + m:4 + m + ref.shape[0]] - Pd[4 - m:4 - m + ref.shape[0]]) for m in range(1, 5)) / (2 * 30)
near('mfcc: deltas as regression slopes over 9 windows', W['d'], dref, 1e-9)
C("mfcc: 'ignore' and 'replace'", a(W['c2']).shape == (P2.shape[0], 20) and np.allclose(a(W['c3'])[:, 0], le) and np.allclose(a(W['c3'])[:, 1:], cc[:, 1:]))
near('mfcc: each window\'s last sample', a(W['loc'])[:3].reshape(-1), [480, 640, 800])
y2 = np.sin(2 * np.pi * 137 * t) + 0.8 * np.sin(2 * np.pi * 274 * t) + 0.6 * np.sin(2 * np.pi * 411 * t) + 0.01 * np.random.default_rng(4).standard_normal(fs)
for meth in ('NCF', 'CEP', 'LHS'):
    W, _ = run(f"x = {col(x)}; y = {col(y2)}; f1 = median(pitch(x, {fs}, 'Method', '{meth}')); f2 = median(pitch(y, {fs}, 'Method', '{meth}', 'MedianFilterLength', 3));")
    C(f'pitch {meth}: 220 Hz and 137 Hz harmonic signals within 0.5%', abs(W['f1'] / 220 - 1) < 0.005 and abs(W['f2'] / 137 - 1) < 0.005, f"{W['f1']} {W['f2']}")
W, _ = run(f"[f, loc] = pitch(randn({fs}, 1), {fs}); n = numel(f); l1 = loc(1);")
near('pitch: 52 ms windows every 10 ms', (W['n'], W['l1']), ((fs - 832) // 160 + 1, 832))
tone = np.sin(2 * np.pi * 1000 * t)
noise = np.random.default_rng(6).standard_normal(fs)
W, _ = run(f"s = {col(tone)}; w = {col(noise)}; c = spectralCentroid(w, {fs}); sp = spectralSpread(w, {fs}); r = spectralRolloffPoint(w, {fs}); fl = spectralFlatness(w, {fs}); en = spectralEntropy(w, {fs});"
           f"ct = median(spectralCentroid(s, {fs})); ft = median(spectralFlatness(s, {fs})); et = median(spectralEntropy(s, {fs}));")
Pn = np.abs(np.fft.rfft(frames(noise, ham, 160), 480, axis=1)) ** 2
fr = np.arange(241) * fs / 480
cn = Pn @ fr / Pn.sum(1)
near('spectralCentroid and spectralSpread: power-weighted mean and standard deviation of the frequencies', (W['c'], W['sp']),
     (cn.reshape(-1, 1), np.sqrt(((fr[None, :] - cn[:, None]) ** 2 * Pn).sum(1) / Pn.sum(1)).reshape(-1, 1)), 1e-9)
near('spectralRolloffPoint: where 95% of the power lies below', W['r'], fr[np.argmax(np.cumsum(Pn, 1) >= 0.95 * Pn.sum(1, keepdims=True), axis=1)].reshape(-1, 1), 1e-12)
pn = Pn / Pn.sum(1, keepdims=True)
near('spectralFlatness and spectralEntropy', (W['fl'], W['en']), (np.exp(np.log(Pn).mean(1)) / Pn.mean(1), (-(pn * np.log(pn)).sum(1) / math.log(241))), 1e-9)
C('a tone: centroid at its frequency, flatness and entropy low', abs(W['ct'] - 1000) < 5 and W['ft'] < 1e-3 and W['et'] < 0.5)
W, _ = run("z = zerocrossrate([1 -1 2 0 -3 4]'); [zw, cw] = zerocrossrate([1 -1 2 0 -3 4 5 -6]', 'WindowLength', 4, 'OverlapLength', 2);")
near('zerocrossrate: sign changes (zero positive) over the samples, and window by window', (W['z'], W['zw'], W['cw']), (4 / 6, [[2 / 4], [2 / 4], [2 / 4]], [[2], [2], [2]]))

# ---- refusals ---------------------------------------------------------------------------------------------------------------------

raises("qammod(0:7, 8)", 'power of 4')
raises("qammod(16, 16)", 'from 0 to 15')
raises("qammod([1 0 1]', 16, 'InputType', 'bit')", 'groups of 4')
raises("rcosdesign(1.5, 6, 4)", 'beta is from 0 to 1')
raises("berawgn(5, 'ook')", "'psk', 'qam'")
raises("biterr(1.5, 1)", 'whole numbers')
raises("pitch(randn(1000, 1), 8000, 'Method', 'XYZ')", "'NCF', 'CEP' or 'LHS'")
raises("mfcc(randn(4000, 1), 8000, 'NumCoeffs', 50)", 'NumCoeffs is from 1')

sys.exit(C.done())
