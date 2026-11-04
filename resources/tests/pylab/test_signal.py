"""Signal processing, run natively (CPython with numpy and scipy): filter
design (IIR, FIR, orders, designfilt), filtering (filtfilt, sosfilt,
fftfilt, filtic, medfilt1, Savitzky-Golay, hilbert, envelope), frequency
responses and forms of a filter, correlation, resampling, peaks, windows,
spectra, waveforms and decibels. The expected values come from SciPy called
here directly, from identities, or are worked out by hand.

    python3 test_signal.py          (from any folder)
"""
import asyncio
import math
import os
import sys
import tempfile

import numpy as np
import scipy.signal as S

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-signal-')


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
        # several values compared together: flattened and joined
        parts = [np.asarray(v, dtype=complex).reshape(-1) for v in x]
        joined = np.concatenate(parts) if parts else np.zeros(0)
        return joined.real if not np.any(joined.imag) else joined
    return np.asarray(x, dtype=complex if np.iscomplexobj(x) else float)


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


row = lambda v: np.asarray(v).astype(complex if np.iscomplexobj(v) else float).reshape(1, -1)  # noqa: E731
col = lambda v: np.asarray(v).reshape(-1, 1)  # noqa: E731

# ---- IIR design -------------------------------------------------------------------------------------------------------
W, _ = run("[b, a] = butter(4, 0.3); [bh, ah] = butter(3, 0.4, 'high'); [bb, ab] = butter(2, [0.2 0.5]); [z, p, k] = butter(3, 0.25); "
           "[c1b, c1a] = cheby1(3, 0.5, 0.4); [c2b, c2a] = cheby2(4, 30, 0.3, 'high'); [eb, ea] = ellip(4, 1, 40, 0.3); [sb, sa] = butter(2, 10, 's');")
b, a_ = S.butter(4, 0.3)
near('butter: lowpass coefficients as rows', (W['b'], W['a']), (row(b), row(a_)))
near('butter high and bandpass (order 2n)', (W['bh'], W['bb']), (row(S.butter(3, 0.4, 'highpass')[0]), row(S.butter(2, [0.2, 0.5], 'bandpass')[0])))
z, p, k = S.butter(3, 0.25, output='zpk')
near('butter: zeros, poles (columns) and gain', (np.sort_complex(np.asarray(W['p']).reshape(-1)), W['k']), (np.sort_complex(p), k))
near('cheby1, cheby2 high, ellip', (W['c1b'], W['c2a'], W['ea']), (row(S.cheby1(3, 0.5, 0.4)[0]), row(S.cheby2(4, 30, 0.3, 'highpass')[1]), row(S.ellip(4, 1, 40, 0.3)[1])))
near("butter 's': an analog filter", (W['sb'], W['sa']), (row(S.butter(2, 10, analog=True)[0]), row(S.butter(2, 10, analog=True)[1])))
W, _ = run("[n, wn] = buttord(0.2, 0.3, 1, 40); [n1, w1] = cheb1ord(0.2, 0.3, 1, 40); [n2, w2] = ellipord([0.2 0.5], [0.15 0.55], 1, 40);")
n, wn = S.buttord(0.2, 0.3, 1, 40)
near('buttord, cheb1ord, ellipord as SciPy', (W['n'], W['wn'], W['n1'], W['n2']), (n, wn, S.cheb1ord(0.2, 0.3, 1, 40)[0], S.ellipord([0.2, 0.5], [0.15, 0.55], 1, 40)[0]))
raises('butter(4, 1.2)', 'between 0 and 1')
raises("butter(4, 0.3, 'bandpass')", 'A band needs two cutoff frequencies')

# ---- FIR design --------------------------------------------------------------------------------------------------------
W, _ = run("b = fir1(20, 0.3); bh = fir1(21, 0.4, 'high'); bp = fir1(30, [0.2 0.5]); bk = fir1(20, 0.3, kaiser(21, 4)); bn = fir1(20, 0.3, 'noscale'); "
           "b2 = fir2(30, [0 0.4 0.5 1], [1 1 0 0]); bl = firls(20, [0 0.3 0.4 1], [1 1 0 0]); bpm = firpm(20, [0 0.3 0.4 1], [1 1 0 0]);")
near('fir1: the Hamming-window design, 1 at DC', (W['b'], np.sum(W['b'])), (row(S.firwin(21, 0.3)), 1.0))
same("fir1 'high' with an odd order is made one higher", np.shape(W['bh']), (1, 23))
near('fir1: bandpass, with a given window, and not scaled', (W['bp'], W['bk']), (row(S.firwin(31, [0.2, 0.5], pass_zero=False)), row(S.firwin(21, 0.3, window=('kaiser', 4)))))
near("fir1 'noscale': the windowed ideal response", W['bn'], row(S.firwin(21, 0.3, window='boxcar', scale=False) * S.get_window('hamming', 21, fftbins=False)))
near('firls and firpm as SciPy', (W['bl'], W['bpm']), (row(S.firls(21, [0, 0.3, 0.4, 1], [1, 1, 0, 0], fs=2)), row(S.remez(21, [0, 0.3, 0.4, 1], [1, 0], fs=2))))
C('fir2: a lowpass of 31 taps, near 1 at DC and 0 at Nyquist', np.shape(W['b2']) == (1, 31) and abs(np.sum(W['b2']) - 1) < 0.02 and abs(np.sum(W['b2'] * (-1) ** np.arange(31))) < 0.02, W['b2'])
W, _ = run("[n, Wn, beta, ftype] = kaiserord([0.3 0.4], [1 0], [0.01 0.01]); b = fir1(n, Wn, ftype, kaiser(n+1, beta), 'noscale'); [h, w] = freqz(b, 1, 1024);")
h, w = np.abs(a(W['h']).reshape(-1)), a(W['w']).reshape(-1)
C('kaiserord: the design meets 40 dB (0.01) beyond the stopband edge and stays within 0.01 in the passband',
  np.max(h[w >= 0.4 * np.pi]) <= 0.012 and np.max(np.abs(h[w <= 0.3 * np.pi] - 1)) <= 0.012 and W['ftype'].str() == 'low', (W['n'], W['beta']))

# ---- filtering -------------------------------------------------------------------------------------------------------
x = np.sin(0.1 * np.arange(1, 101)) + 0.3 * np.cos(1.7 * np.arange(1, 101))
R.BASE.clear()
W, _ = run("x = sin(0.1*(1:100)) + 0.3*cos(1.7*(1:100)); [b, a] = butter(3, 0.2); y = filtfilt(b, a, x); yc = filtfilt(b, a, x'); "
           "[sos, g] = tf2sos(b, a); ys = filtfilt(sos, g, x); b4 = butter(4, 0.3); [b4, a4] = butter(4, 0.3); s4 = tf2sos(b4, a4); "
           "y4 = filtfilt(b4, a4, x); y4s = filtfilt(s4, 1, x);")
b, a_ = S.butter(3, 0.2)
near('filtfilt: odd padding of 3 times the order, a row back for a row', W['y'], row(S.filtfilt(b, a_, x, padlen=9)))
near('filtfilt: a column back for a column', W['yc'], col(S.filtfilt(b, a_, x, padlen=9)))
near('filtfilt by second-order sections as by coefficients', W['y4s'], W['y4'], 1e-9)
W, _ = run("y = sosfilt([1 0 0 1 -0.5 0; 1 1 0 1 0 0], 1:5); f = fftfilt([1 1 1]/3, 1:6); zi = filtic([1 1], [1 -0.5], [2 1], 1); u = upfirdn([1 2 3], [1 1], 2);")
near('sosfilt, fftfilt (as filter), filtic (as lfiltic) and upfirdn',
     (W['y'], W['f'], W['zi'], W['u']), (row(S.sosfilt([[1, 0, 0, 1, -0.5, 0], [1, 1, 0, 1, 0, 0]], np.arange(1.0, 6))), row(np.convolve([1 / 3] * 3, np.arange(1.0, 7))[:6]),
                                         col(S.lfiltic([1, 1], [1, -0.5], [2, 1], [1])), row([1, 1, 2, 2, 3, 3])))
W, _ = run("m = medfilt1([1 5 2 8 3 9 4]); m4 = medfilt1([1 5 2 8 3 9 4], 4); mt = medfilt1([1 5 2 8 3 9 4], 3, [], 2, 'truncate'); mc = medfilt1([1 9; 5 2; 2 7]);")
near('medfilt1: n = 3 with zeros beyond the ends; n = 4 from k-2; truncated windows; down columns',
     (W['m'], W['m4'], W['mt'], W['mc']), (row([1, 2, 5, 3, 8, 4, 4]), row([0.5, 1.5, 3.5, 4, 5.5, 6, 3.5]), row([3, 2, 5, 3, 8, 4, 6.5]), np.array([[1, 2], [2, 7], [2, 2]])))
W, _ = run("[B, G] = sgolay(2, 5); y = sgolayfilt(sin(0:0.1:2), 3, 7);")
near('sgolay: the middle row 1/35*[-3 12 17 12 -3]; G and B = G*S\'', (W['B'][2], np.asarray(W['G']).shape), (np.array([-3, 12, 17, 12, -3]) / 35, (5, 3)))
near('sgolayfilt as savgol_filter (polynomial fits at the ends)', W['y'], row(S.savgol_filter(np.sin(np.arange(0, 2.05, 0.1)), 7, 3, mode='interp')))
W, _ = run("h = hilbert([1 2 3 4]); [up, lo] = envelope(3 + 2*sin(2*pi*(0:399)/100)); x = sin(0:0.1:20); [pu, pl] = envelope(x, 5, 'peak');")
near('hilbert: the analytic signal of [1 2 3 4]', W['h'], np.array([[1 + 1j, 2 - 1j, 3 - 1j, 4 + 1j]]))
up = a(W['up']).reshape(-1)
C('envelope: the analytic envelope of 3 + 2*sin (whole periods) is 5 and 1', np.allclose(up, 5, atol=1e-9) and np.allclose(a(W['lo']).reshape(-1), 1, atol=1e-9), up[:5])
pu, pl, xv = a(W['pu']).reshape(-1), a(W['pl']).reshape(-1), a(W['x']).reshape(-1)
pk = S.find_peaks(xv, distance=5)[0]
C("envelope 'peak': splines through the peaks (and the troughs)", np.allclose(pu[pk], xv[pk]) and np.allclose(pl[S.find_peaks(-xv, distance=5)[0]], xv[S.find_peaks(-xv, distance=5)[0]]), pu[pk])

# ---- responses and forms ------------------------------------------------------------------------------------------------
W, _ = run("[b, a] = butter(3, 0.3); [h, w] = freqz(b, a, 8); [hw, ww] = freqz(b, a, 8, 'whole'); [hf, f] = freqz(b, a, 4, 100); hv = freqz(b, a, [0 pi/2]); "
           "[ha, wa] = freqs(1, [1 1], [0 1 10]); h1 = impz([1 2 3]); h2 = impz(1, [1 -0.5], 5); s2 = stepz(1, [1 -0.5], 4); [gd, wg] = grpdelay([1 1 1], 1, 4);")
b, a_ = S.butter(3, 0.3)
wz, hz = S.freqz(b, a_, 8)
near('freqz: n points from 0 below pi, as columns', (W['h'], W['w']), (col(hz), col(wz)))
near("freqz 'whole', with fs (Hz), at frequencies given", (W['ww'], W['f'], W['hv']), (col(S.freqz(b, a_, 8, whole=True)[0]), col([0, 12.5, 25, 37.5]), col(S.freqz(b, a_, [0, np.pi / 2])[1])))
near('freqs of 1/(s+1): 1, 1/sqrt(2), 1/sqrt(101)', np.abs(a(W['ha'])), col([1, 1 / math.sqrt(2), 1 / math.sqrt(101)]))
near('impz: an FIR filter its coefficients; an IIR one 0.5^k; stepz the sums', (W['h1'], W['h2'], W['s2']), (col([1, 2, 3]), col(0.5 ** np.arange(5)), col([1, 1.5, 1.75, 1.875])))
near('grpdelay of a symmetric FIR filter of 3 taps: 1 sample', W['gd'], col([1, 1, 1, 1]))
W, _ = run("[z, p, k] = tf2zp([1 -1], [1 -0.5]); [b, a] = zp2tf([1; -1], 0.5, 2); [sos, g] = tf2sos([1 2 1], [1 -0.5 0.06]); [bs, as] = sos2tf([1 2 1 1 -0.5 0.06], 3); "
           "n = filtord([1 2 3], [1 0.5]); [b4, a4] = butter(4, 0.2); s4 = tf2sos(b4, a4); [bb, aa] = sos2tf(s4);")
near('tf2zp, zp2tf', (W['z'], W['p'], W['k'], W['b'], W['a']), (1.0, 0.5, 1.0, row([2, 0, -2]), row([1, -0.5])))
near('tf2sos with the gain apart; sos2tf with a gain; filtord', (W['sos'], W['g'], W['bs'], W['n']), (row([1, 2, 1, 1, -0.5, 0.06]), 1.0, row([3, 6, 3]), 2.0))
near('tf2sos then sos2tf gives the filter back', (W['bb'], W['aa']), (row(S.butter(4, 0.2)[0]), row(S.butter(4, 0.2)[1])), 1e-9)

# ---- correlation -----------------------------------------------------------------------------------------------------------
W, _ = run("[r, lags] = xcorr([1 2 3], [1 1]); r1 = xcorr([1 2 3]); rn = xcorr([1 2 3], 'normalized'); rb = xcorr([1 2 3], 'biased'); ru = xcorr([1 2 3], 'unbiased'); "
           "rm = xcorr([1 2 3], 1); rc = xcorr([1; 2; 3]); c = xcov([1 2 3]); rz = xcorr([1 1i], [1 1]); X = xcorr([1 2; 3 4]);")
near('xcorr: r(m) = sum of x(n+m)*conj(y(n)), the shorter padded; its lags', (W['r'], W['lags']), (row([0, 1, 3, 5, 3]), row([-2, -1, 0, 1, 2])))
near("xcorr scalings: none, 'normalized', 'biased', 'unbiased'; maxlag", (W['r1'], W['rn'], W['rb'], W['ru'], W['rm']),
     (row([3, 8, 14, 8, 3]), row(np.array([3, 8, 14, 8, 3]) / 14), row(np.array([3, 8, 14, 8, 3]) / 3), row([3, 4, 14 / 3, 4, 3]), row([8, 14, 8])))
near('xcorr of a column is a column; xcov less the means; complex', (W['rc'], W['c'], W['rz']), (col([3, 8, 14, 8, 3]), row([-1, 0, 2, 0, -1]), row([1, 1 + 1j, 1j])))
near('xcorr of a matrix: every pair of columns', np.asarray(W['X']).shape, np.array([3, 4]))

# ---- resampling ------------------------------------------------------------------------------------------------------------
W, _ = run("x = sin(0.2*(0:59)); y = resample(x, 3, 2); d = decimate(1:100, 4); i = interp(1:5, 2); xi = sin(0.3*(0:40)); yi = interp(xi, 3); "
           "ds = downsample(1:10, 3); ds1 = downsample(1:10, 3, 1); us = upsample(1:3, 2); bf = buffer(1:7, 3, 1); [bf2, z] = buffer(1:7, 3); bn = buffer(1:10, 3, -1);")
xs = np.sin(0.2 * np.arange(60))
near('resample: resample_poly with a Kaiser window, beta 5', W['y'], row(S.resample_poly(xs, 3, 2, window=('kaiser', 5.0))))
near('decimate: as scipy.signal.decimate (zero phase), from the first sample', W['d'], row(S.decimate(np.arange(1.0, 101), 4, zero_phase=True)))
near('interp of a ramp: the midpoints; its own samples kept', W['i'][0][:9], np.array([1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]), 0.01)
t = np.arange(123) / 3
C('interp of a sine: within 0.01 of the sine between the ends', np.max(np.abs(a(W['yi']).reshape(-1)[9:-9] - np.sin(0.3 * t[9:-9]))) < 0.01, W['yi'])
near('downsample, its phase, upsample', (W['ds'], W['ds1'], W['us']), (row([1, 4, 7, 10]), row([2, 5, 8]), row([1, 0, 2, 0, 3, 0])))
near('buffer: frames overlapping by 1, the first starting with a zero', W['bf'], np.array([[0, 2, 4, 6], [1, 3, 5, 7], [2, 4, 6, 0]]))
near('buffer: whole frames and the rest apart; skipping a sample between frames', (W['bf2'], W['z'], W['bn']),
     (np.array([[1, 4], [2, 5], [3, 6]]), 7.0, np.array([[1, 5, 9], [2, 6, 10], [3, 7, 0]])))

# ---- peaks ------------------------------------------------------------------------------------------------------------------
W, _ = run("y = [0 2 1 3 1 4 4 1 0]; [pks, locs, w, p] = findpeaks(y); [pk2, lc2] = findpeaks([0 2 1 3 1 4 1], 'MinPeakDistance', 3); "
           "[pk3, lc3] = findpeaks([0 2 1 3 1 4 1], 'SortStr', 'descend', 'NPeaks', 2); [pk4, lc4] = findpeaks([0 2 1 3 1 4 1], 'MinPeakHeight', 2.5); "
           "[pk5, lc5] = findpeaks([0 2 1 3 1 4 1], 'MinPeakProminence', 2.5); [pk6, lc6] = findpeaks([0 2 1 3 1 4 1], 0.1:0.1:0.7); [pk7, lc7] = findpeaks([0 2 1 3 1 4 1]', 10);")
near('findpeaks: the maxima, where (a flat one where it starts), prominences', (W['pks'], W['locs'], W['p']), (row([2, 3, 4]), row([2, 4, 6]), row([1, 2, 4])))
near('findpeaks: MinPeakDistance keeps the highest first; SortStr and NPeaks; MinPeakHeight; MinPeakProminence',
     (W['lc2'], W['pk3'], W['lc4'], W['lc5']), (row([2, 6]), row([4, 3]), row([4, 6]), 6.0))
near('findpeaks: locations in x, or in time for a sampling rate; a column for a column', (W['lc6'], W['lc7']), (row([0.2, 0.4, 0.6]), col([0.1, 0.3, 0.5])))
yv = np.array([0, 2, 1, 3, 1, 4, 4, 1, 0], float)
wd = S.peak_widths(yv, [1, 3, 5], rel_height=0.5)[0]
near('findpeaks: widths at half the prominence', W['w'], row(wd))

# ---- windows -------------------------------------------------------------------------------------------------------------------
W, _ = run("w1 = hamming(5); w2 = hann(4); w3 = hanning(3); w4 = blackman(5); w5 = kaiser(6, 3); w6 = gausswin(5); w7 = tukeywin(9, 0.4); w8 = chebwin(7, 60); "
           "w9 = hamming(4, 'periodic'); w10 = window(@blackmanharris, 6); w11 = flattopwin(5); w12 = triang(4); w13 = bartlett(5); w14 = rectwin(3); w15 = nuttallwin(5);")
g = lambda name, n, **kw: col(S.get_window(name, n, fftbins=False, **kw))  # noqa: E731
near('windows as columns: hamming, hann, blackman, kaiser, tukey, chebwin', (W['w1'], W['w2'], W['w4'], W['w5'], W['w7'], W['w8']),
     (g('hamming', 5), g('hann', 4), g('blackman', 5), g(('kaiser', 3), 6), g(('tukey', 0.4), 9), g(('chebwin', 60), 7)))
near('hanning without its zero ends; gausswin; periodic hamming', (W['w3'], W['w6'], W['w9']),
     (col([0.5, 1, 0.5]), col(np.exp(-0.5 * (2.5 * np.arange(-2, 3) / 2) ** 2)), col(S.get_window('hamming', 4, fftbins=True))))
near('window(@fn, n), flattop, triang, bartlett, rectwin, nuttall', (W['w10'], W['w11'], W['w12'], W['w13'], W['w14'], W['w15']),
     (g('blackmanharris', 6), g('flattop', 5), g('triang', 4), g('bartlett', 5), col([1, 1, 1]), g('nuttall', 5)))

# ---- spectra --------------------------------------------------------------------------------------------------------------------
W, _ = run("x = sin(2*pi*10*(0:99)/100) + 0.5*cos(2*pi*25*(0:99)/100); [p, f] = periodogram(x, [], 128, 100); [pw, w] = periodogram(x); "
           "[pt, ft] = periodogram(x, [], 128, 100, 'twosided'); [ph, fh] = periodogram(x, hamming(100), 100, 100);")
xs = np.sin(2 * np.pi * 10 * np.arange(100) / 100) + 0.5 * np.cos(2 * np.pi * 25 * np.arange(100) / 100)
fq, P = S.periodogram(xs, fs=100, nfft=128, detrend=False)
near('periodogram with fs: SciPy density, frequencies in Hz', (W['p'], W['f']), (col(P), col(fq)))
fq2, P2 = S.periodogram(xs, fs=2 * np.pi, nfft=256, detrend=False)
near('periodogram without fs: nfft max(256, 2^nextpow2(N)), rad/sample', (W['pw'], W['w']), (col(P2), col(fq2)))
near('periodogram two-sided; with a window', (np.asarray(W['pt']).shape, W['ph']), (np.array([128, 1]), col(S.periodogram(xs, fs=100, window=S.get_window('hamming', 100, fftbins=False), nfft=100, detrend=False)[1])))
W, _ = run("x = sin(0.3*(0:999)) + cos(1.1*(0:999)); [p, w] = pwelch(x); [p2, f2] = pwelch(x, 100, 50, 256, 1000);")
xs = np.sin(0.3 * np.arange(1000)) + np.cos(1.1 * np.arange(1000))
L = int(1000 // 4.5)
fq, P = S.welch(xs, fs=2 * np.pi, window=S.get_window('hamming', L, fftbins=False), nperseg=L, noverlap=L // 2, nfft=256, detrend=False)
near('pwelch: 8 half-overlapping Hamming segments, nfft max(256, 2^nextpow2(L))', (W['p'], W['w']), (col(P), col(fq)))
fq, P = S.welch(xs, fs=1000, window=S.get_window('hamming', 100, fftbins=False), nperseg=100, noverlap=50, nfft=256, detrend=False)
near('pwelch with a window length, overlap, nfft and fs', W['p2'], col(P))
W, _ = run("x = randn(600, 1); y = filter([1 0.5], 1, x) + 0.1*randn(600, 1); [c, f] = mscohere(x, y, [], [], [], 10); [t, ft] = tfestimate(x, y); [pxy, fp] = cpsd(x, y);")
xs, ys = a(W['x']).reshape(-1), a(W['y']).reshape(-1)
L = int(600 // 4.5)
win = S.get_window('hamming', L, fftbins=False)
kw = dict(window=win, nperseg=L, noverlap=L // 2, nfft=256, detrend=False)
near('mscohere as scipy.signal.coherence', W['c'], col(S.coherence(xs, ys, fs=10, **kw)[1]))
near("cpsd = X.*conj(Y) (SciPy's csd of y and x); tfestimate = Pyx/Pxx", (W['pxy'], W['t']),
     (col(S.csd(ys, xs, fs=2 * np.pi, **kw)[1]), col(S.csd(xs, ys, fs=2 * np.pi, **kw)[1] / S.welch(xs, fs=2 * np.pi, **kw)[1])))
tt = np.abs(a(W['t']).reshape(-1))
C('tfestimate of y = x + 0.5*x(n-1): 1.5 at 0 and 0.5 at pi', abs(tt[0] - 1.5) < 0.15 and abs(tt[-1] - 0.5) < 0.15, (tt[0], tt[-1]))
W, _ = run("x = sin(0.2*(0:999)); [s, w, t, ps] = spectrogram(x); [s2, f2, t2] = spectrogram(x, 128, 64, 128, 1000);")
L = int(1000 // 4.5)
win = S.get_window('hamming', L, fftbins=False)
fq, tq, Z = S.stft(xs[:0] if False else np.sin(0.2 * np.arange(1000)), fs=2 * np.pi, window=win, nperseg=L, noverlap=L // 2, nfft=256, boundary=None, padded=False, detrend=False)
near('spectrogram: the windowed segments\' FFTs, 8 segments, their middles in samples', (W['s'], W['t']), (Z * np.sum(win), row(L / 2 + np.arange(Z.shape[1]) * (L - L // 2))), 1e-8)
same('spectrogram with a window length, overlap, nfft and fs', (np.shape(W['s2']), np.shape(W['f2']), np.shape(W['t2'])), ((65, 14), (65, 1), (1, 14)))
W, _ = run("p = bandpower([1 -1 1 -1]); x = sin(2*pi*50*(0:999)/1000); pb = bandpower(x, 1000, [40 60]); pa = bandpower(x, 1000, [0 500]);")
near('bandpower: the mean square; nearly all of a 50 Hz sine within 40-60 Hz', (W['p'], W['pb'] / W['pa'] > 0.99, abs(W['pa'] - 0.5) < 0.01), (1.0, True, True))

# ---- waveforms and decibels --------------------------------------------------------------------------------------------------------
W, _ = run("c = chirp(0:0.25:1, 0, 1, 4); cl = chirp([0 0.5], 1, 1, 10, 'logarithmic'); st = sawtooth([0 pi pi/2]); tw = sawtooth([0 pi/2 pi], 0.5); sq = square([0 1 4 7]); "
           "sd = square([0 1 2], 25); rp = rectpuls([-1 -0.5 0 0.49 0.5]); tp = tripuls([-0.5 0 0.25 0.5]); ts = tripuls([-0.5 -0.25 0 0.5], 1, -0.5); "
           "[gi, gq, ge] = gauspuls([0 1e-3], 1e3, 0.5); dr = diric([0 pi 2*pi], 3); dB = [db2mag(20) mag2db(10) pow2db(100) db2pow(10)]; "
           "pp = peak2peak([1 5 -2]); pr = peak2rms([1 -1 1 -1]); dc = dct([1 2 3 4]); id = idct(dc); r = rceps([1 2 3 4]);")
near('chirp: linear (as SciPy) and logarithmic', (W['c'], W['cl']), (row(S.chirp(np.arange(0, 1.01, 0.25), 0, 1, 4)), row(S.chirp([0, 0.5], 1, 1, 10, method='logarithmic'))))
near('sawtooth, a triangle wave, square waves', (W['st'], W['tw'], W['sq'], W['sd']), (row([-1, 0, -0.5]), row([-1, 0, 1]), row([1, 1, -1, 1]), row([1, 1, -1])))
near('rectpuls, tripuls (and skewed)', (W['rp'], W['tp'], W['ts']), (row([0, 1, 1, 1, 0]), row([0, 1, 0.5, 0]), row([0, 1, 2 / 3, 0])))
gi, gq, ge = S.gausspulse(np.array([0, 1e-3]), fc=1e3, bw=0.5, retquad=True, retenv=True)
near('gauspuls with its quadrature and envelope', (W['gi'], W['gq'], W['ge']), (row(gi), row(gq), row(ge)))
near('diric: 1 at 0 and 2*pi, -1/3 at pi for n = 3', W['dr'], row([1, -1 / 3, 1]))
near('db2mag, mag2db, pow2db, db2pow; peak2peak; peak2rms', (W['dB'], W['pp'], W['pr']), (row([10, 20, 20, 10]), 7.0, 1.0))
import scipy.fft as F
near('dct (orthonormal) and idct back', (W['dc'], W['id']), (row(F.dct([1.0, 2, 3, 4], norm='ortho')), row([1, 2, 3, 4])), 1e-9)
near('rceps', W['r'], row(np.real(np.fft.ifft(np.log(np.abs(np.fft.fft([1, 2, 3, 4])))))))

# ---- lowpass and kin, designfilt ----------------------------------------------------------------------------------------------------
W, _ = run("n = 0:999; x = sin(0.05*pi*n) + sin(0.8*pi*n); y = lowpass(x, 0.2); yh = highpass(x, 0.5); yb = bandpass(x, [0.6 0.9]); ys = bandstop(x, [0.6 0.9]); "
           "[yl, d] = lowpass(x, 100, 1000); cls = class(d);")
xs = np.sin(0.05 * np.pi * np.arange(1000)) + np.sin(0.8 * np.pi * np.arange(1000))
low, high = np.sin(0.05 * np.pi * np.arange(1000)), np.sin(0.8 * np.pi * np.arange(1000))
mid = slice(100, 900)
err_ = lambda got, want: float(np.max(np.abs(a(got).reshape(-1)[mid] - want[mid])))  # noqa: E731
C('lowpass keeps the slow sine and takes out the fast one, without delay', err_(W['y'], low) < 0.01, err_(W['y'], low))
C('highpass and bandpass keep the fast sine; bandstop takes it out', max(err_(W['yh'], high), err_(W['yb'], high), err_(W['ys'], low)) < 0.01,
  (err_(W['yh'], high), err_(W['yb'], high), err_(W['ys'], low)))
same('lowpass gives its filter as a second output', W['cls'].str(), 'digitalFilter')
W, out = run("d = designfilt('lowpassfir', 'FilterOrder', 20, 'CutoffFrequency', 400, 'SampleRate', 2000)")
C('designfilt: a digital filter shown with its properties', 'digitalFilter with properties' in out and "FrequencyResponse: 'lowpass'" in out and 'FilterOrder: 20' in out, out)
W, _ = run("d = designfilt('lowpassfir', 'FilterOrder', 20, 'CutoffFrequency', 400, 'SampleRate', 2000); b = d.Coefficients; y = filter(d, [1 zeros(1, 30)]); "
           "f = filtfilt(d, sin(0.1*(1:100))'); [h, w] = freqz(d); o = filtord(d); "
           "d2 = designfilt('lowpassiir', 'FilterOrder', 4, 'HalfPowerFrequency', 0.3); s2 = d2.Coefficients; [b2, a2] = butter(4, 0.3); [h2, w2] = freqz(d2); [h3, w3] = freqz(b2, a2); "
           "d3 = designfilt('bandpassiir', 'FilterOrder', 8, 'HalfPowerFrequency1', 0.2, 'HalfPowerFrequency2', 0.4); s3 = size(d3.Coefficients); "
           "d4 = designfilt('highpassfir', 'PassbandFrequency', 0.4, 'StopbandFrequency', 0.3, 'StopbandAttenuation', 60); [h4, w4] = freqz(d4, 1024);")
near('designfilt lowpassfir: fir1 of the cutoff over the Nyquist frequency; filter(d, x) is its impulse response', (W['b'], a(W['y'])[0][:21]), (row(S.firwin(21, 0.4)), S.firwin(21, 0.4)))
near('designfilt lowpassiir: second-order sections of butter; freqz(d) as butter\'s', (np.asarray(W['s2']).shape, np.abs(a(W['h2'])), W['o']), (np.array([2, 6]), np.abs(a(W['h3'])), 20.0), 1e-9)
same('designfilt bandpassiir of order 8: 4 sections', np.asarray(W['s3']).tolist(), [[4.0, 6.0]])
h4, w4 = np.abs(a(W['h4']).reshape(-1)), a(W['w4']).reshape(-1)
C('designfilt highpassfir from edges: 60 dB down below the stopband edge', np.max(h4[w4 <= 0.3 * np.pi]) < 1.2e-3 and np.min(h4[w4 >= 0.4 * np.pi]) > 0.99, np.max(h4[w4 <= 0.3 * np.pi]))
raises("designfilt('lowpassfir', 'FilterOrder', 10)", 'a FIR filter needs CutoffFrequency')
raises("designfilt('notchiir')", 'The response is one of')

# hanning's periodic window: 0, then the symmetric one of n - 1 (the same as hann's periodic one)
W, _ = run("p4 = hanning(4, 'periodic'); p16 = hanning(16, 'periodic'); h15 = hanning(15); hp = hann(16, 'periodic');")
near("hanning(n, 'periodic') is 0 followed by hanning(n - 1), as hann(n, 'periodic')",
     (W['p4'], W['p16'][1:], W['p16'], W['p16'][8]), ([0, 0.5, 1, 0.5], W['h15'], W['hp'], 1.0), 1e-15)

sys.exit(C.done())
