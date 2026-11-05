"""More signal processing on NumPy and SciPy: besself, residuez, the
short-time Fourier transform and its inverse (stft, istft), pulstran, the
complex cepstrum (cceps, icceps), pspectrum and instfreq, the measures of
a tone (snr, thd, sinad, sfdr), the pulse and transition measures
(statelevels, midcross, risetime, falltime, slewrate, pulsewidth,
pulsesep, pulseperiod, dutycycle, overshoot, undershoot, settlingtime),
delays (finddelay, alignsignals), dynamic time warping and the edit
distance of real signals (dtw, edr), empirical and variational mode
decomposition (emd, vmd) and the Wigner-Ville distribution (wvd).

Times are in seconds when a sampling rate is given (the first sample at
0), else in samples; a signal that is a matrix is its columns where a
function takes several.
"""
import math

import numpy as np

from . import bi as _register
from ._util import err, nargchk, darr, out, opt_str, is_str
from ..values import MError, Char, Struct, FH, EMPTY, numel, py_str
from .. import runtime as R


def bi(*names, **kw):
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0]) from None
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _S():
    import scipy.signal as S
    return S


def _b(name, *args):
    return R._builtin(name, *args)


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


def _vec(v, fn, what='x'):
    a = darr(v, fn)
    if a.ndim > 2 or (a.ndim == 2 and min(a.shape) > 1):
        raise err(f'MATLAB:{fn}:notVector', f'{what} must be a vector.', fn)
    return a.reshape(-1)


def _isrow(v):
    s = np.shape(darr(v)) if not isinstance(v, np.ndarray) else v.shape
    return len(s) == 2 and s[0] == 1 and s[1] != 1


def _like(y, v):
    """y (a vector) shaped as the vector v was: a row stays a row."""
    y = np.asarray(y)
    return out(y.reshape(1, -1) if _isrow(v) else y.reshape(-1, 1))


def _col(y):
    return out(np.asarray(y).reshape(-1, 1))


def _nv(args, names, fn):
    """Name-value options (any case) at the end of args: ({name: value}, the arguments before them)."""
    low = {n.lower(): n for n in names}
    got = {}
    rest = list(args)
    k = 0
    while k < len(rest):
        s = opt_str(rest[k])
        if s is not None and s.lower() in low:
            if k + 1 >= len(rest):
                raise err(f'MATLAB:{fn}:missingValue', f"The option '{s}' needs a value.", fn)
            got[low[s.lower()]] = rest[k + 1]
            del rest[k:k + 2]
            continue
        k += 1
    return got, rest


def _num(v, fn, what):
    a = np.asarray(darr(v, fn), float).reshape(-1)
    if a.size != 1:
        raise err(f'MATLAB:{fn}:scalar', f'{what} must be a number.', fn)
    return float(a[0])


def _fs(args, k, fn):
    """The sampling rate at args[k] (1 when it is not there or []), and whether one was given."""
    if len(args) > k and numel(args[k]):
        fs = _num(args[k], fn, 'The sampling rate')
        if not fs > 0:
            raise err(f'MATLAB:{fn}:fs', 'The sampling rate must be positive.', fn)
        return fs, True
    return 1.0, False


# ---- filters --------------------------------------------------------------------------------------------------------------

@bi('besself', nout=4)
def besself(nargout, *args):
    """[b, a] = besself(n, Wo, ftype): an analog Bessel filter (s domain), Wo in rad/s; [z, p, k] and [A, B, C, D] too."""
    nargchk(args, 2, 3, 'besself')
    S = _S()
    n = int(_num(args[0], 'besself', 'The order'))
    Wo = np.asarray(darr(args[1]), float).reshape(-1)
    kind = py_str(args[2]).lower() if len(args) > 2 else ('bandpass' if Wo.size == 2 else 'low')
    btype = {'low': 'lowpass', 'high': 'highpass', 'bandpass': 'bandpass', 'stop': 'bandstop', 'bandstop': 'bandstop'}.get(kind)
    if btype is None:
        raise err('MATLAB:besself:ftype', "ftype is 'low', 'high', 'bandpass' or 'stop'.", 'besself')
    w = Wo if Wo.size == 2 else float(Wo[0])
    if nargout == 3:
        z, p, k = S.bessel(n, w, btype, analog=True, output='zpk')
        return _col(z), _col(p), float(k)
    if nargout == 4:
        A, B, C, D = S.bessel(n, w, btype, analog=True, output='ss')
        return out(A), out(B), out(C), out(D)
    b, a = S.bessel(n, w, btype, analog=True, output='ba')
    return _outs(nargout, out(b.reshape(1, -1)), out(a.reshape(1, -1)))


@bi('residuez', nout=3)
def residuez(nargout, *args):
    """[r, p, k] = residuez(b, a): the partial fractions of b(z)/a(z) in powers of 1/z (SciPy's residuez, the poles grouped by decreasing magnitude); [b, a] = residuez(r, p, k) puts them back."""
    nargchk(args, 2, 3, 'residuez')
    S = _S()
    if len(args) == 3:
        b, a = S.invresz(darr(args[0]).reshape(-1), darr(args[1]).reshape(-1), darr(args[2]).reshape(-1), tol=1e-3, rtype='avg')
        b, a = (np.real_if_close(np.asarray(v), tol=1e6) for v in (b, a))
        return _outs(nargout, out(b.reshape(1, -1)), out(a.reshape(1, -1)))
    r, p, k = S.residuez(darr(args[0]).reshape(-1), darr(args[1]).reshape(-1), tol=1e-3, rtype='avg')
    groups, i = [], 0
    while i < p.size:
        j = i + 1
        while j < p.size and abs(p[j] - p[i]) <= 1e-3 * max(abs(p[i]), 1):
            j += 1
        groups.append((i, j))
        i = j
    groups.sort(key=lambda g: -abs(p[g[0]]))
    order = [t for g0, g1 in groups for t in range(g0, g1)]
    r, p = np.real_if_close(r[order], tol=1e6), np.real_if_close(p[order], tol=1e6)
    k = np.real_if_close(np.asarray(k).reshape(-1), tol=1e6)
    return _outs(nargout, _col(r), _col(p), out(k.reshape(1, -1)) if k.size else EMPTY())


# ---- the short-time Fourier transform -------------------------------------------------------------------------------------

_STFT_OPTS = ('Window', 'OverlapLength', 'FFTLength', 'FrequencyRange', 'OutputTimeDimension', 'InputTimeDimension', 'ConjugateSymmetric', 'Method')


def _stft_setup(o, fn, n=None):
    w = np.asarray(darr(o['Window']), float).reshape(-1) if 'Window' in o else 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(128) / 128)
    L = w.size
    nov = int(_num(o['OverlapLength'], fn, 'OverlapLength')) if 'OverlapLength' in o else int(math.floor(0.75 * L))
    nfft = int(_num(o['FFTLength'], fn, 'FFTLength')) if 'FFTLength' in o else L
    rng = py_str(o['FrequencyRange']).lower() if 'FrequencyRange' in o else 'centered'
    if not 0 <= nov < L:
        raise err(f'MATLAB:{fn}:overlap', 'OverlapLength must be smaller than the window.', fn)
    if nfft < L:
        raise err(f'MATLAB:{fn}:nfft', 'FFTLength must be at least the window length.', fn)
    if rng not in ('centered', 'twosided', 'onesided'):
        raise err(f'MATLAB:{fn}:range', "FrequencyRange is 'centered', 'twosided' or 'onesided'.", fn)
    if n is not None and n < L:
        raise err(f'MATLAB:{fn}:short', 'The signal must be at least as long as the window.', fn)
    return w, L, nov, nfft, rng


def _freq_rows(nfft, rng):
    """The rows of a full FFT kept, in order, and their frequencies in cycles per sample."""
    k = np.arange(nfft)
    if rng == 'twosided':
        return k, k / nfft
    if rng == 'onesided':
        k = np.arange(nfft // 2 + 1)
        return k, k / nfft
    half = nfft // 2
    if nfft % 2 == 0:
        k = np.concatenate([np.arange(half + 1, nfft), np.arange(0, half + 1)])
        return k, np.arange(-half + 1, half + 1) / nfft
    k = np.concatenate([np.arange(half + 1, nfft), np.arange(0, half + 1)])
    return k, np.arange(-half, half + 1) / nfft


@bi('stft', nout=3)
def stft(nargout, *args):
    """[s, f, t] = stft(x, fs, 'Window', win, 'OverlapLength', n, 'FFTLength', nfft, 'FrequencyRange', range): the short-time Fourier transform; drawn when no output is asked for."""
    nargchk(args, 1, 13, 'stft')
    o, rest = _nv(args, _STFT_OPTS, 'stft')
    X = darr(rest[0], 'stft')
    if X.ndim == 2 and X.shape[0] == 1:
        X = X.T
    fs, given = _fs(rest, 1, 'stft')
    w, L, nov, nfft, rng = _stft_setup(o, 'stft', X.shape[0])
    hop = L - nov
    nseg = (X.shape[0] - L) // hop + 1
    idx = np.arange(L)[:, None] + hop * np.arange(nseg)[None, :]
    rows, fr = _freq_rows(nfft, rng)
    chans = []
    for c in range(X.shape[1]):
        seg = X[:, c][idx] * w[:, None]
        chans.append(np.fft.fft(seg, nfft, axis=0)[rows])
    s = chans[0] if len(chans) == 1 else np.stack(chans, axis=2)
    f = fr * fs if given else fr * 2 * np.pi
    t = (L / 2 + hop * np.arange(nseg)) / fs
    if 'OutputTimeDimension' in o and py_str(o['OutputTimeDimension']).lower() == 'downrows':
        s = np.swapaxes(s, 0, 1)
    if nargout == 0:
        mag = 20 * np.log10(np.maximum(np.abs(chans[0]), 1e-300))
        _b('imagesc', out(t.reshape(1, -1)), out((f if given else f / np.pi).reshape(-1, 1)), out(mag))
        _b('axis', Char.of('xy'))
        _b('colorbar')
        _b('xlabel', Char.of('Time (s)' if given else 'Samples'))
        _b('ylabel', Char.of('Frequency (Hz)' if given else 'Normalized Frequency (\\times\\pi rad/sample)'))
        _b('title', Char.of('Short-Time Fourier Transform'))
        return None
    return _outs(nargout, out(s), _col(f), _col(t))


@bi('istft', nout=2)
def istft(nargout, *args):
    """[x, t] = istft(s, fs, 'Window', win, 'OverlapLength', n, 'FFTLength', nfft, 'FrequencyRange', range, 'Method', 'wola', 'ConjugateSymmetric', tf): the signal back from its short-time Fourier transform, by weighted overlap-add ('ola': overlap-add)."""
    nargchk(args, 1, 17, 'istft')
    o, rest = _nv(args, _STFT_OPTS, 'istft')
    Sm = np.asarray(darr(rest[0], 'istft'))
    if 'InputTimeDimension' in o and py_str(o['InputTimeDimension']).lower() == 'downrows':
        Sm = np.swapaxes(Sm, 0, 1)
    fs, _ = _fs(rest, 1, 'istft')
    w, L, nov, nfft, rng = _stft_setup(o, 'istft')
    method = py_str(o['Method']).lower() if 'Method' in o else 'wola'
    conj = bool(np.asarray(darr(o['ConjugateSymmetric'])).reshape(-1)[0]) if 'ConjugateSymmetric' in o else False
    rows, _ = _freq_rows(nfft, rng)
    if Sm.shape[0] != rows.size:
        raise err('MATLAB:istft:size', f'The transform must have {rows.size} rows for this FFTLength and FrequencyRange.', 'istft')
    hop = L - nov
    if Sm.ndim == 2:
        Sm = Sm[:, :, None]
    nseg = Sm.shape[1]
    n = L + hop * (nseg - 1)
    xs = []
    for c in range(Sm.shape[2]):
        full = np.zeros((nfft, nseg), complex)
        full[rows] = Sm[:, :, c]
        if rng == 'onesided':
            k = np.arange(1, (nfft + 1) // 2)
            full[nfft - k] = np.conj(full[k])
            conj = True
        frames = np.fft.ifft(full, axis=0)[:L]
        x = np.zeros(n, complex)
        norm = np.zeros(n)
        for m in range(nseg):
            sl = slice(m * hop, m * hop + L)
            if method == 'ola':
                x[sl] += frames[:, m]
                norm[sl] += w
            else:
                x[sl] += frames[:, m] * w
                norm[sl] += w * w
        x = np.where(norm > 1e-10 * norm.max(), x / np.where(norm > 0, norm, 1), 0)
        xs.append(x.real if conj else x)
    X = xs[0].reshape(-1, 1) if len(xs) == 1 else np.column_stack(xs)
    return _outs(nargout, out(X), _col(np.arange(n) / fs))


# ---- pulses and cepstra ---------------------------------------------------------------------------------------------------

@bi('pulstran')
def pulstran(nargout, *args):
    """y = pulstran(t, d, func, p1, p2, ...) (func a name or handle, called at t - d for each delay; d may have a second column of amplitudes) or y = pulstran(t, d, p, fs, method) (p a pulse sampled at fs, interpolated)."""
    nargchk(args, 3, None, 'pulstran')
    tv = darr(args[0], 'pulstran')
    t = tv.reshape(-1).astype(float)
    D = np.asarray(darr(args[1], 'pulstran'), float)
    if D.ndim == 2 and D.shape[1] == 2 and D.shape[0] != 1:
        delays, amps = D[:, 0], D[:, 1]
    else:
        delays, amps = D.reshape(-1), np.ones(D.size)
    f = args[2]
    y = np.zeros(t.size)
    if is_str(f) or isinstance(f, FH):
        fh = R.NamedFH(py_str(f)) if is_str(f) else f
        extra = args[3:]
        for d, a in zip(delays, amps):
            v = np.asarray(darr(fh.scall(1, out((t - d).reshape(tv.shape)), *extra)), float).reshape(-1)
            y += a * v
    else:
        p = np.asarray(darr(f), float).reshape(-1)
        fs = _num(args[3], 'pulstran', 'fs') if len(args) > 3 and numel(args[3]) else 1.0
        method = py_str(args[4]).lower() if len(args) > 4 else 'linear'
        tp = np.arange(p.size) / fs
        from scipy.interpolate import interp1d
        kind = {'linear': 'linear', 'nearest': 'nearest', 'spline': 'cubic', 'cubic': 'cubic', 'pchip': 'cubic', 'previous': 'previous', 'next': 'next'}.get(method)
        if kind is None:
            raise err('MATLAB:pulstran:method', 'The interpolation method is linear, nearest, spline, pchip, cubic, previous or next.', 'pulstran')
        if method == 'pchip':
            from scipy.interpolate import PchipInterpolator
            g = PchipInterpolator(tp, p, extrapolate=False)
        else:
            g = interp1d(tp, p, kind=kind, bounds_error=False, fill_value=0.0) if p.size > 1 else (lambda s: np.where(np.abs(s) < 1e-12, p[0], 0.0))
        for d, a in zip(delays, amps):
            y += a * np.nan_to_num(np.asarray(g(t - d), float))
    return out(y.reshape(tv.shape))


def _rcunwrap(ph):
    n = ph.size
    nh = (n + 1) // 2
    y = np.unwrap(ph)
    nd = int(round(y[nh] / np.pi)) if n > 1 else 0
    return y - np.pi * nd * np.arange(n) / nh, nd


@bi('cceps', nout=3)
def cceps(nargout, *args):
    """[xhat, nd, xhat1] = cceps(x, n): the complex cepstrum, real(ifft(log|X| + i*arg X)) with the phase unwrapped and its linear part (nd samples of delay) taken out; n pads or cuts x first; xhat1 by a second FFT of twice the length."""
    nargchk(args, 1, 2, 'cceps')
    x = _vec(args[0], 'cceps')
    n = int(_num(args[1], 'cceps', 'n')) if len(args) > 1 else x.size

    def one(m):
        h = np.fft.fft(x, m)
        if np.any(h == 0):
            raise err('signal:cceps:ZeroDFT', 'The signal has a zero in its spectrum: its log is not finite.', 'cceps')
        ah, nd = _rcunwrap(np.angle(h))
        return np.real(np.fft.ifft(np.log(np.abs(h)) + 1j * ah)), nd
    xhat, nd = one(n)
    res = [_like(xhat, args[0]), float(nd)]
    if nargout > 2:
        x1, _ = one(2 * n)
        res.append(_like(x1, args[0]))
    return _outs(nargout, *res)


@bi('icceps')
def icceps(nargout, *args):
    """x = icceps(xhat, nd): the signal back from its complex cepstrum and the delay cceps took out."""
    nargchk(args, 1, 2, 'icceps')
    xh = _vec(args[0], 'icceps')
    nd = _num(args[1], 'icceps', 'nd') if len(args) > 1 else 0.0
    n = xh.size
    nh = (n + 1) // 2
    logh = np.fft.fft(xh)
    ph = np.imag(logh) + np.pi * nd * np.arange(n) / nh
    return _like(np.real(np.fft.ifft(np.exp(np.real(logh) + 1j * ph))), args[0])


# ---- spectra ------------------------------------------------------------------------------------------------------------------

def _kaiser(n, beta):
    return np.kaiser(n, beta) if n > 1 else np.ones(n)


@bi('pspectrum', nout=3)
def pspectrum(nargout, *args):
    """[p, f, t] = pspectrum(x, fs, type, 'FrequencyLimits', [f1 f2], 'Leakage', l, 'TimeResolution', tr, 'OverlapPercent', op): the power spectrum ('power') or a spectrogram ('spectrogram'), with a Kaiser window of beta 40*(1 - Leakage) (Leakage 0.5); PyLAB's own choices of lengths (see Help)."""
    nargchk(args, 1, 13, 'pspectrum')
    o, rest = _nv(args, ('FrequencyLimits', 'Leakage', 'TimeResolution', 'OverlapPercent', 'MinThreshold', 'FrequencyResolution'), 'pspectrum')
    kind = 'power'
    if rest and is_str(rest[-1]):
        kind = py_str(rest[-1]).lower()
        rest = rest[:-1]
    if kind not in ('power', 'spectrogram'):
        raise err('MATLAB:pspectrum:type', "The type is 'power' or 'spectrogram' here.", 'pspectrum')
    x = _vec(rest[0], 'pspectrum').astype(float)
    fs, given = _fs(rest, 1, 'pspectrum')
    leak = _num(o['Leakage'], 'pspectrum', 'Leakage') if 'Leakage' in o else 0.5
    beta = 40 * (1 - min(max(leak, 0.0), 1.0))
    p, f, t = _pspec(x, fs, kind, beta, o)
    lim = np.asarray(darr(o['FrequencyLimits']), float).reshape(-1) if 'FrequencyLimits' in o else None
    if lim is not None:
        keep = (f >= lim[0] - 1e-12) & (f <= lim[1] + 1e-12)
        f, p = f[keep], p[keep]
    if 'MinThreshold' in o:
        th = _num(o['MinThreshold'], 'pspectrum', 'MinThreshold')
        p = np.where(10 * np.log10(np.maximum(p, 1e-300)) < th, 0.0, p)
    fo = f if given else f * 2 * np.pi
    if nargout == 0:
        fx = fo if given else fo / np.pi
        if kind == 'power':
            _b('plot', out(fx.reshape(-1, 1)), out(10 * np.log10(np.maximum(p, 1e-300)).reshape(-1, 1)))
            _b('grid', Char.of('on'))
            _b('ylabel', Char.of('Power Spectrum (dB)'))
            _b('xlabel', Char.of('Frequency (Hz)' if given else 'Normalized Frequency (\\times\\pi rad/sample)'))
        else:
            _b('imagesc', out(t.reshape(1, -1)), out(fx.reshape(-1, 1)), out(10 * np.log10(np.maximum(p, 1e-300))))
            _b('axis', Char.of('xy'))
            _b('colorbar')
            _b('xlabel', Char.of('Time (s)' if given else 'Samples'))
            _b('ylabel', Char.of('Frequency (Hz)' if given else 'Normalized Frequency (\\times\\pi rad/sample)'))
        return None
    if kind == 'power':
        return _outs(nargout, _col(p), _col(fo))
    return _outs(nargout, out(p), _col(fo), _col(t))


def _power(seg, w, nfft):
    """The one-sided power spectrum of a windowed segment, scaled so that a sinusoid of amplitude A peaks at A^2/2."""
    X = np.fft.rfft(seg * w, nfft)
    P = np.abs(X) ** 2 / np.sum(w) ** 2
    P[1:(nfft + 1) // 2] *= 2
    return P


def _pspec(x, fs, kind, beta, o):
    n = x.size
    if kind == 'power':
        nfft = max(8190, 1 << int(math.ceil(math.log2(max(n, 2)))))
        w = _kaiser(n, beta)
        P = _power(x, w, nfft)
        return P, np.arange(P.size) * fs / nfft, np.zeros(1)
    if 'TimeResolution' in o:
        L = max(2, int(round(_num(o['TimeResolution'], 'pspectrum', 'TimeResolution') * fs)))
    else:
        L = max(16, 1 << int(round(math.log2(max(n / 8, 16)))))
    L = min(L, n)
    op = _num(o['OverlapPercent'], 'pspectrum', 'OverlapPercent') if 'OverlapPercent' in o else 50.0
    hop = max(1, int(round(L * (1 - op / 100))))
    nseg = (n - L) // hop + 1
    nfft = max(1024, 1 << int(math.ceil(math.log2(L))))
    w = _kaiser(L, beta)
    P = np.column_stack([_power(x[m * hop:m * hop + L], w, nfft) for m in range(nseg)])
    return P, np.arange(P.shape[0]) * fs / nfft, (L / 2 + hop * np.arange(nseg)) / fs


@bi('instfreq', nout=2)
def instfreq(nargout, *args):
    """[ifq, t] = instfreq(x, fs, 'Method', method): the instantaneous frequency: 'tfmoments' (the first moment in frequency of pspectrum's spectrogram at each time) or 'hilbert' (the derivative of the analytic signal's phase)."""
    nargchk(args, 1, 4, 'instfreq')
    o, rest = _nv(args, ('Method', 'FrequencyLimits'), 'instfreq')
    x = _vec(rest[0], 'instfreq').astype(float)
    fs, given = _fs(rest, 1, 'instfreq')
    method = py_str(o['Method']).lower() if 'Method' in o else 'tfmoments'
    if method == 'hilbert':
        z = _S().hilbert(x)
        ph = np.unwrap(np.angle(z))
        ifq = np.gradient(ph) * fs / (2 * np.pi)
        t = np.arange(x.size) / fs
    elif method == 'tfmoments':
        P, f, t = _pspec(x, fs, 'spectrogram', 20.0, {})
        if 'FrequencyLimits' in o:
            lim = np.asarray(darr(o['FrequencyLimits']), float).reshape(-1)
            keep = (f >= lim[0]) & (f <= lim[1])
            P, f = P[keep], f[keep]
        ifq = (f @ P) / np.maximum(P.sum(axis=0), 1e-300)
    else:
        raise err('MATLAB:instfreq:method', "Method is 'tfmoments' or 'hilbert'.", 'instfreq')
    if not given:
        ifq = ifq * 2 * np.pi
    if nargout == 0:
        _b('plot', out(t.reshape(-1, 1)), out(ifq.reshape(-1, 1)))
        _b('xlabel', Char.of('Time (s)' if given else 'Samples'))
        _b('ylabel', Char.of('Instantaneous Frequency (Hz)' if given else 'Instantaneous Frequency (rad/sample)'))
        _b('grid', Char.of('on'))
        return None
    return _outs(nargout, _col(ifq), _col(t))


# ---- measures of a tone ---------------------------------------------------------------------------------------------------------

class _Tone:
    """The one-sided spectrum of a signal through a Kaiser window of beta 38, scaled so that the bins of a tone's
    main lobe add up to its power; the lobes found by walking down from a peak while the spectrum falls."""

    def __init__(self, x, fs):
        x = np.asarray(x, float)
        n = x.size
        if n < 8:
            raise err('MATLAB:snr:short', 'The signal is too short to measure.', 'snr')
        w = _kaiser(n, 38.0)
        X = np.fft.rfft(x * w)
        P = np.abs(X) ** 2 / (n * np.sum(w * w))
        P[1:(n + 1) // 2] *= 2
        self.P, self.n, self.fs = P, n, fs
        self.f = np.arange(P.size) * fs / n
        self.used = np.zeros(P.size, bool)
        self.dc = self.lobe(0)
        rest = np.where(self.used, -1.0, P)
        self.k1 = int(np.argmax(rest))
        self.fund = self.lobe(self.k1)

    def lobe(self, k):
        P = self.P
        lo = k
        while lo > 0 and P[lo - 1] < P[lo]:
            lo -= 1
        hi = k
        while hi < P.size - 1 and P[hi + 1] < P[hi]:
            hi += 1
        sl = np.arange(lo, hi + 1)
        self.used[sl] = True
        return sl

    def power(self, sl):
        return float(np.sum(self.P[sl]))

    def freq(self, sl):
        p = self.P[sl]
        return float(np.sum(self.f[sl] * p) / max(np.sum(p), 1e-300))

    def harmonic(self, h):
        """The lobe of harmonic h: the largest bin within two bins of h times the fundamental's frequency (folded into 0 .. fs/2)."""
        f0 = self.freq(self.fund)
        fh = (h * f0) % self.fs
        if fh > self.fs / 2:
            fh = self.fs - fh
        k = int(round(fh * self.n / self.fs))
        if k >= self.P.size:
            return None, fh
        lo, hi = max(k - 2, 0), min(k + 2, self.P.size - 1)
        kk = lo + int(np.argmax(self.P[lo:hi + 1]))
        if self.used[kk]:
            return None, fh
        return self.lobe(kk), fh

    def noise(self):
        """The power of the bins not used, with the used ones (DC, tones) taken at the others' average."""
        free = ~self.used
        if not free.any():
            return 0.0
        return float(np.mean(self.P[free]) * self.P.size)


def _tone_args(args, fn):
    x = _vec(args[0], fn).astype(float)
    fs, _ = _fs(args, 1, fn)
    nh = int(_num(args[2], fn, 'The number of harmonics')) if len(args) > 2 and numel(args[2]) else 6
    return x, fs, nh


@bi('snr', nout=2)
def snr(nargout, *args):
    """[r, noisepow] = snr(x, fs, n): the signal-to-noise ratio in dBc of a tone: its power against the noise's, with DC and the first n harmonics (6) left out; snr(x, y) = 10*log10(sum(x.^2)/sum(y.^2))."""
    nargchk(args, 1, 3, 'snr')
    if len(args) == 2 and numel(args[1]) > 1:
        x = np.asarray(darr(args[0]), float)
        y = np.asarray(darr(args[1]), float)
        if x.shape != y.shape:
            raise err('MATLAB:snr:size', 'x and y must be the same size.', 'snr')
        return _outs(nargout, 10 * math.log10(float(np.sum(x ** 2)) / float(np.sum(y ** 2))), 10 * math.log10(float(np.sum(y ** 2)) / y.size))
    x, fs, nh = _tone_args(args, 'snr')
    T = _Tone(x, fs)
    for h in range(2, nh + 1):
        T.harmonic(h)
    s, nz = T.power(T.fund), T.noise()
    return _outs(nargout, 10 * math.log10(s / nz), 10 * math.log10(nz))


@bi('thd', nout=3)
def thd(nargout, *args):
    """[r, harmpow, harmfreq] = thd(x, fs, n): the total harmonic distortion in dBc, the power of harmonics 2 to n (6) against the fundamental's; harmpow (dB) and harmfreq from the fundamental on."""
    nargchk(args, 1, 3, 'thd')
    x, fs, nh = _tone_args(args, 'thd')
    T = _Tone(x, fs)
    pows, freqs = [T.power(T.fund)], [T.freq(T.fund)]
    for h in range(2, nh + 1):
        sl, fh = T.harmonic(h)
        pows.append(T.power(sl) if sl is not None else 0.0)
        freqs.append(T.freq(sl) if sl is not None else fh)
    r = 10 * math.log10(sum(pows[1:]) / pows[0]) if sum(pows[1:]) > 0 else -math.inf
    return _outs(nargout, r, _col(10 * np.log10(np.maximum(pows, 1e-300))), _col(freqs))


@bi('sinad', nout=2)
def sinad(nargout, *args):
    """[r, totdistpow] = sinad(x, fs): the signal to noise and distortion ratio in dBc: the tone's power against all else but DC."""
    nargchk(args, 1, 2, 'sinad')
    x, fs, _ = _tone_args(args, 'sinad')
    T = _Tone(x, fs)
    s, nd = T.power(T.fund), T.noise()
    return _outs(nargout, 10 * math.log10(s / nd), 10 * math.log10(nd))


@bi('sfdr', nout=3)
def sfdr(nargout, *args):
    """[r, spurpow, spurfreq] = sfdr(x, fs): the spurious-free dynamic range in dB: the tone's power against the largest other lobe's (DC left out)."""
    nargchk(args, 1, 2, 'sfdr')
    x, fs, _ = _tone_args(args, 'sfdr')
    T = _Tone(x, fs)
    s = T.power(T.fund)
    rest = np.where(T.used, -1.0, T.P)
    k = int(np.argmax(rest))
    if rest[k] <= 0:
        return _outs(nargout, math.inf, -math.inf, math.nan)
    sl = T.lobe(k)
    sp = T.power(sl)
    return _outs(nargout, 10 * math.log10(s / sp), 10 * math.log10(sp), T.freq(sl))


# ---- pulses and transitions -------------------------------------------------------------------------------------------------------

_PULSE_OPTS = ('StateLevels', 'Tolerance', 'PercentReferenceLevels', 'MidPercentReferenceLevel', 'Polarity', 'SeekFactor', 'Region', 'Fs')


def _times(args, fn, xv):
    """Sample times: from fs (the first sample at 0) or a vector of times; 1 when neither is given."""
    if len(args) > 1 and numel(args[1]):
        a = np.asarray(darr(args[1]), float).reshape(-1)
        if a.size == xv.size and a.size > 1:
            return a, True
        if a.size == 1 and a[0] > 0:
            return np.arange(xv.size) / a[0], True
        raise err(f'MATLAB:{fn}:time', 'The second input is a sampling rate or the times of the samples.', fn)
    return np.arange(xv.size, dtype=float), False


def _levels(x, nbins=100):
    """The two state levels: in each half of the histogram's range, the average of the samples in its fullest bin."""
    lo, hi = float(np.min(x)), float(np.max(x))
    if hi == lo:
        return np.array([lo, hi])
    edges = np.linspace(lo, hi, nbins + 1)
    idx = np.clip(np.searchsorted(edges, x, side='right') - 1, 0, nbins - 1)
    counts = np.bincount(idx, minlength=nbins)
    half = nbins // 2
    k1 = int(np.argmax(counts[:half]))
    k2 = half + int(np.argmax(counts[half:]))
    return np.array([float(np.mean(x[idx == k1])), float(np.mean(x[idx == k2]))])


@bi('statelevels', nout=3)
def statelevels(nargout, *args):
    """[levels, histogram, bins] = statelevels(x, nbins): the low and high state levels of a two-state signal: in each half of the range of a histogram of nbins (100) bins, the average of the samples in its fullest bin."""
    nargchk(args, 1, 2, 'statelevels')
    x = _vec(args[0], 'statelevels').astype(float)
    nb = int(_num(args[1], 'statelevels', 'nbins')) if len(args) > 1 else 100
    lv = _levels(x, nb)
    counts, edges = np.histogram(x, bins=nb, range=(x.min(), x.max()) if x.max() > x.min() else None)
    return _outs(nargout, out(lv.reshape(1, -1)), _col(counts.astype(float)), _col((edges[:-1] + edges[1:]) / 2))


class _Trans:
    """A two-state signal's transitions: each a run from one state's tolerance band to the other's."""

    def __init__(self, x, t, o, fn):
        self.x, self.t = x, t
        self.lv = np.asarray(darr(o['StateLevels']), float).reshape(-1) if 'StateLevels' in o else _levels(x)
        if self.lv.size != 2 or not self.lv[1] > self.lv[0]:
            raise err(f'MATLAB:{fn}:levels', 'StateLevels must be two increasing levels.', fn)
        tol = (_num(o['Tolerance'], fn, 'Tolerance') if 'Tolerance' in o else 2.0) / 100
        ref = np.asarray(darr(o['PercentReferenceLevels']), float).reshape(-1) / 100 if 'PercentReferenceLevels' in o else np.array([0.1, 0.9])
        mid = (_num(o['MidPercentReferenceLevel'], fn, 'MidPercentReferenceLevel') if 'MidPercentReferenceLevel' in o else 50.0) / 100
        lo, hi = self.lv
        amp = hi - lo
        self.amp = amp
        self.ref = lo + ref * amp
        self.mid = lo + mid * amp
        self.tol = tol * amp
        state = np.where(x <= lo + self.tol, 0, np.where(x >= hi - self.tol, 1, -1))
        self.list = []                  # (polarity +1/-1, index leaving the first state, index reaching the other)
        last, last_i = None, None
        for i, s in enumerate(state):
            if s < 0:
                continue
            if last is not None and s != last:
                self.list.append((1 if s == 1 else -1, last_i, i))
            last, last_i = s, i

    def cross(self, level, a, b):
        """The time where x crosses level between samples a and b (the first crossing), by linear interpolation."""
        x, t = self.x, self.t
        for i in range(a, b):
            y0, y1 = x[i] - level, x[i + 1] - level
            if y0 == 0:
                return t[i]
            if y0 * y1 < 0 or y1 == 0:
                return t[i] + (t[i + 1] - t[i]) * (y0 / (y0 - y1))
        return math.nan

    def of(self, pol):
        return [tr for tr in self.list if pol == 0 or tr[0] == pol]


def _pulse_setup(args, fn, nmin=1, nmax=2):
    o, rest = _nv(args, _PULSE_OPTS, fn)
    nargchk(rest, nmin, nmax, fn)
    x = _vec(rest[0], fn).astype(float)
    t, _ = _times(rest, fn, x)
    return _Trans(x, t, o, fn), o, rest


def _edge_times(T, pol):
    """For each transition of polarity pol: (lower reference crossing, upper reference crossing)."""
    res = []
    for p, a, b in T.of(pol):
        if p > 0:
            res.append((T.cross(T.ref[0], a, b), T.cross(T.ref[1], a, b)))
        else:
            res.append((T.cross(T.ref[1], a, b), T.cross(T.ref[0], a, b)))
    return res


def _edge_plot(T, fn, marks):
    _b('plot', out(T.t.reshape(-1, 1)), out(T.x.reshape(-1, 1)))
    _b('hold', Char.of('on'))
    for lv in T.lv:
        _b('yline', lv, Char.of('--'))
    # the levels the times are measured at: the reference levels for edges, the mid level for the rest
    for lv in (T.ref if fn in ('risetime', 'falltime', 'slewrate') else [T.mid]):
        _b('yline', float(lv), Char.of(':'))
    if marks:
        m = np.asarray(marks, float)
        _b('plot', out(m.reshape(-1, 1)), out(np.interp(m, T.t, T.x).reshape(-1, 1)), Char.of('o'))
    _b('hold', Char.of('off'))
    # room above and below, so that a level the signal sits on is not drawn on the box
    pad = 0.1 * T.amp
    _b('ylim', out(np.array([[min(np.nanmin(T.x), T.lv[0]) - pad, max(np.nanmax(T.x), T.lv[1]) + pad]])))
    _b('title', Char.of(fn))
    return None


def _duration(nargout, args, fn, pol):
    T, o, _ = _pulse_setup(args, fn)
    e = _edge_times(T, pol)
    d = np.array([b - a for a, b in e])
    if nargout == 0:
        return _edge_plot(T, fn, [v for p in e for v in p])
    lower = np.array([p[0] for p in e])
    upper = np.array([p[1] for p in e])
    return _outs(nargout, _col(d), _col(lower), _col(upper), T.ref[0], T.ref[1])


@bi('risetime', nout=5)
def risetime(nargout, *args):
    """[r, lowercross, uppercross, lowerref, upperref] = risetime(x, fs or t, 'PercentReferenceLevels', [10 90], 'StateLevels', lv, 'Tolerance', 2): the time of each rising transition from the lower reference level to the upper."""
    return _duration(nargout, args, 'risetime', 1)


@bi('falltime', nout=5)
def falltime(nargout, *args):
    """[f, uppercross, lowercross, upperref, lowerref] = falltime(x, fs or t, ...): the time of each falling transition from the upper reference level to the lower."""
    T, o, _ = _pulse_setup(args, 'falltime')
    e = _edge_times(T, -1)
    if nargout == 0:
        return _edge_plot(T, 'falltime', [v for p in e for v in p])
    d = np.array([b - a for a, b in e])
    return _outs(nargout, _col(d), _col([p[0] for p in e]), _col([p[1] for p in e]), T.ref[1], T.ref[0])


@bi('slewrate', nout=5)
def slewrate(nargout, *args):
    """[s, lowercross, uppercross, lowerref, upperref] = slewrate(x, fs or t, ...): (upper reference - lower reference) / the transition's duration, for each transition (negative when falling)."""
    T, o, _ = _pulse_setup(args, 'slewrate')
    e = _edge_times(T, 0)
    pols = [p for p, _, _ in T.of(0)]
    dv = T.ref[1] - T.ref[0]
    s = np.array([p * dv / (b - a) for p, (a, b) in zip(pols, e)])
    if nargout == 0:
        return _edge_plot(T, 'slewrate', [v for p in e for v in p])
    return _outs(nargout, _col(s), _col([min(p) for p in e]), _col([max(p) for p in e]), T.ref[0], T.ref[1])


def _mids(T, pol=0):
    return [(p, T.cross(T.mid, a, b)) for p, a, b in T.of(pol)]


@bi('midcross', nout=2)
def midcross(nargout, *args):
    """[c, midlev] = midcross(x, fs or t, 'MidPercentReferenceLevel', 50, ...): the times each transition crosses the mid reference level."""
    T, o, _ = _pulse_setup(args, 'midcross')
    c = [m for _, m in _mids(T)]
    if nargout == 0:
        return _edge_plot(T, 'midcross', c)
    return _outs(nargout, _col(c), T.mid)


def _pulses(T, pol):
    """(start, end) mid-crossing times of each pulse of polarity pol: positive pulses rise then fall."""
    m = _mids(T)
    res = []
    for k in range(len(m) - 1):
        if m[k][0] == pol and m[k + 1][0] == -pol:
            res.append((m[k][1], m[k + 1][1]))
    return res


def _polarity(o, fn):
    if 'Polarity' not in o:
        return 1
    s = py_str(o['Polarity']).lower()
    if s not in ('positive', 'negative'):
        raise err(f'MATLAB:{fn}:polarity', "Polarity is 'positive' or 'negative'.", fn)
    return 1 if s == 'positive' else -1


@bi('pulsewidth', nout=4)
def pulsewidth(nargout, *args):
    """[w, initcross, finalcross, midlev] = pulsewidth(x, fs or t, 'Polarity', 'positive', ...): each pulse's width between its mid-reference crossings."""
    T, o, _ = _pulse_setup(args, 'pulsewidth')
    ps = _pulses(T, _polarity(o, 'pulsewidth'))
    if nargout == 0:
        return _edge_plot(T, 'pulsewidth', [v for p in ps for v in p])
    return _outs(nargout, _col([b - a for a, b in ps]), _col([a for a, _ in ps]), _col([b for _, b in ps]), T.mid)


@bi('pulsesep', nout=4)
def pulsesep(nargout, *args):
    """[s, initcross, finalcross, midlev] = pulsesep(x, fs or t, 'Polarity', 'positive', ...): the separation from each pulse's end to the next one's start (mid-reference crossings)."""
    T, o, _ = _pulse_setup(args, 'pulsesep')
    ps = _pulses(T, _polarity(o, 'pulsesep'))
    gaps = [(ps[k][1], ps[k + 1][0]) for k in range(len(ps) - 1)]
    if nargout == 0:
        return _edge_plot(T, 'pulsesep', [v for p in gaps for v in p])
    return _outs(nargout, _col([b - a for a, b in gaps]), _col([a for a, _ in gaps]), _col([b for _, b in gaps]), T.mid)


@bi('pulseperiod', nout=4)
def pulseperiod(nargout, *args):
    """[p, initcross, finalcross, nextcross, midlev] = pulseperiod(x, fs or t, ...): the time from each pulse's start to the next one's."""
    T, o, _ = _pulse_setup(args, 'pulseperiod')
    ps = _pulses(T, _polarity(o, 'pulseperiod'))
    per = [(ps[k][0], ps[k][1], ps[k + 1][0]) for k in range(len(ps) - 1)]
    if nargout == 0:
        return _edge_plot(T, 'pulseperiod', [v for p in per for v in (p[0], p[2])])
    return _outs(nargout, _col([c - a for a, _, c in per]), _col([a for a, _, _ in per]), _col([b for _, b, _ in per]), _col([c for _, _, c in per]))


@bi('dutycycle', nout=4)
def dutycycle(nargout, *args):
    """[d, initcross, finalcross, nextcross, midlev] = dutycycle(x, fs or t, ...): each pulse's width over its period."""
    T, o, _ = _pulse_setup(args, 'dutycycle')
    ps = _pulses(T, _polarity(o, 'dutycycle'))
    per = [(ps[k][0], ps[k][1], ps[k + 1][0]) for k in range(len(ps) - 1)]
    d = [(b - a) / (c - a) for a, b, c in per]
    if nargout == 0:
        return _edge_plot(T, 'dutycycle', [v for p in per for v in p])
    return _outs(nargout, _col(d), _col([a for a, _, _ in per]), _col([b for _, b, _ in per]), _col([c for _, _, c in per]))


def _shoot(nargout, args, fn, over):
    T, o, _ = _pulse_setup(args, fn)
    seek = _num(o['SeekFactor'], fn, 'SeekFactor') if 'SeekFactor' in o else 3.0
    region = py_str(o['Region']).lower() if 'Region' in o else 'postshoot'
    if region not in ('preshoot', 'postshoot'):
        raise err(f'MATLAB:{fn}:region', "Region is 'preshoot' or 'postshoot'.", fn)
    vals, levs, insts = [], [], []
    e = _edge_times(T, 0)
    trs = T.of(0)
    for k, ((p, a, b), (c0, c1)) in enumerate(zip(trs, e)):
        dur = abs(c1 - c0)
        # after the signal reaches the state's band (postshoot), or before it leaves the other's (preshoot)
        if region == 'postshoot':
            t0 = T.t[b]
            t1 = t0 + seek * dur
            if k + 1 < len(trs):
                t1 = min(t1, T.t[trs[k + 1][1]])
            final = T.lv[1] if p > 0 else T.lv[0]
        else:
            t1 = T.t[a]
            t0 = t1 - seek * dur
            if k > 0:
                t0 = max(t0, T.t[trs[k - 1][2]])
            final = T.lv[0] if p > 0 else T.lv[1]
        sel = (T.t >= t0) & (T.t <= t1)
        if not sel.any():
            vals.append(0.0)
            levs.append(final)
            insts.append(math.nan)
            continue
        seg, tt = T.x[sel], T.t[sel]
        # overshoot: beyond the state, away from where the transition came from; undershoot: the other way
        sign = (1 if p > 0 else -1) * (1 if region == 'postshoot' else -1) * (1 if over else -1)
        dev = sign * (seg - final)
        i = int(np.argmax(dev))
        vals.append(max(0.0, float(dev[i])) / T.amp * 100)
        levs.append(float(seg[i]))
        insts.append(float(tt[i]))
    if nargout == 0:
        return _edge_plot(T, fn, [v for v in insts if v == v])
    return _outs(nargout, _col(vals), _col(levs), _col(insts))


@bi('overshoot', nout=3)
def overshoot(nargout, *args):
    """[os, oslev, osinst] = overshoot(x, fs or t, 'Region', 'postshoot', 'SeekFactor', 3, ...): each transition's largest excursion beyond its final state, as a percentage of the difference of the states, within SeekFactor times the transition's duration after the signal reaches that state's band (before it leaves the first state's band for 'preshoot')."""
    return _shoot(nargout, args, 'overshoot', True)


@bi('undershoot', nout=3)
def undershoot(nargout, *args):
    """[us, uslev, usinst] = undershoot(x, fs or t, ...): as overshoot, the excursion back towards the state the transition left."""
    return _shoot(nargout, args, 'undershoot', False)


@bi('settlingtime', nout=4)
def settlingtime(nargout, *args):
    """[s, slev, sinst, tolerance] = settlingtime(x, fs or t, D, 'Tolerance', 2, ...): for each transition, the time from its mid-reference crossing until the signal stays within the tolerance (percent of the states' difference) of its final state, looked for within D after the crossing; NaN when it does not settle."""
    o, rest = _nv(args, _PULSE_OPTS, 'settlingtime')
    nargchk(rest, 3, 3, 'settlingtime')
    x = _vec(rest[0], 'settlingtime').astype(float)
    t, _ = _times(rest, 'settlingtime', x)
    D = _num(rest[2], 'settlingtime', 'D')
    T = _Trans(x, t, o, 'settlingtime')
    vals, levs, insts = [], [], []
    eps = 1e-9 * max(1.0, float(np.max(np.abs(T.t))))
    for p, tm in _mids(T):
        final = T.lv[1] if p > 0 else T.lv[0]
        sel = np.flatnonzero((T.t >= tm) & (T.t <= tm + D + eps))
        if sel.size == 0 or T.t[-1] < tm + D - eps:
            vals.append(math.nan)
            levs.append(math.nan)
            insts.append(math.nan)
            continue
        outside = np.abs(T.x[sel] - final) > T.tol * (1 + 1e-9)
        if not outside.any():
            k = sel[0]
        elif outside[-1]:
            vals.append(math.nan)
            levs.append(math.nan)
            insts.append(math.nan)
            continue
        else:
            k = sel[int(np.flatnonzero(outside)[-1]) + 1]
        vals.append(float(T.t[k] - tm))
        levs.append(float(T.x[k]))
        insts.append(float(T.t[k]))
    if nargout == 0:
        return _edge_plot(T, 'settlingtime', [v for v in insts if v == v])
    return _outs(nargout, _col(vals), _col(levs), _col(insts), T.tol / T.amp * 100)


# ---- delays ----------------------------------------------------------------------------------------------------------------------

def _delay(x, y, maxlag):
    """The lag (in samples) by which y is behind x: the largest absolute normalized cross-correlation, the smallest lag on a tie."""
    nx, ny = x.size, y.size
    ex, ey = float(np.sum(np.abs(x) ** 2)), float(np.sum(np.abs(y) ** 2))
    if ex == 0 or ey == 0:
        return 0
    c = np.correlate(y, x, 'full') / math.sqrt(ex * ey)          # lags -(nx-1) .. ny-1
    lags = np.arange(-(nx - 1), ny)
    keep = np.abs(lags) <= maxlag
    c, lags = np.abs(c[keep]), lags[keep]
    best = c.max()
    cand = lags[c >= best - 1e-12 * max(best, 1)]
    return int(cand[np.argmin(np.abs(cand))])


@bi('finddelay')
def finddelay(nargout, *args):
    """D = finddelay(x, y, maxlag): the delay of y behind x in samples (negative when y leads), where their normalized cross-correlation is largest in absolute value; for matrices, column by column."""
    nargchk(args, 2, 3, 'finddelay')
    X, Y = np.asarray(darr(args[0]), float), np.asarray(darr(args[1]), float)
    xs = [X.reshape(-1)] if min(X.shape) == 1 else [X[:, j] for j in range(X.shape[1])]
    ys = [Y.reshape(-1)] if min(Y.shape) == 1 else [Y[:, j] for j in range(Y.shape[1])]
    if len(xs) > 1 and len(ys) > 1 and len(xs) != len(ys):
        raise err('MATLAB:finddelay:size', 'x and y must have the same number of columns.', 'finddelay')
    n = max(len(xs), len(ys))
    ml = np.asarray(darr(args[2]), float).reshape(-1) if len(args) > 2 else None
    D = []
    for j in range(n):
        x, y = xs[min(j, len(xs) - 1)], ys[min(j, len(ys) - 1)]
        m = int(ml[min(j, ml.size - 1)]) if ml is not None else max(x.size, y.size) - 1
        D.append(float(_delay(x, y, m)))
    return D[0] if n == 1 else out(np.array(D).reshape(1, -1))


@bi('alignsignals', nout=3)
def alignsignals(nargout, *args):
    """[xa, ya, D] = alignsignals(x, y, maxlag, 'truncate'): x and y aligned by delaying the earlier one with leading zeros by D = finddelay(x, y) samples; 'truncate' keeps the delayed one at its length."""
    nargchk(args, 2, 4, 'alignsignals')
    words = [py_str(a).lower() for a in args[2:] if is_str(a)]
    nums = [a for a in args[2:] if not is_str(a)]
    x, y = _vec(args[0], 'alignsignals'), _vec(args[1], 'alignsignals')
    m = int(_num(nums[0], 'alignsignals', 'maxlag')) if nums and numel(nums[0]) else max(x.size, y.size) - 1
    D = _delay(x, y, m)
    xa, ya = x, y
    if D > 0:
        xa = np.concatenate([np.zeros(D), x])
        if 'truncate' in words:
            xa = xa[:x.size]
    elif D < 0:
        ya = np.concatenate([np.zeros(-D), y])
        if 'truncate' in words:
            ya = ya[:y.size]
    return _outs(nargout, _like(xa, args[0]), _like(ya, args[1]), float(D))


# ---- dynamic time warping, edit distance ------------------------------------------------------------------------------------------

def _samples(v, fn):
    """A signal as samples (rows of the result): a vector's elements, a matrix's columns."""
    a = np.asarray(darr(v, fn), float)
    if a.ndim == 2 and min(a.shape) == 1:
        return a.reshape(-1, 1)
    return a.T


def _local(X, Y, metric, fn):
    if X.shape[1] != Y.shape[1]:
        raise err(f'MATLAB:{fn}:channels', 'x and y must have the same number of rows (channels).', fn)
    d = X[:, None, :] - Y[None, :, :]
    if metric == 'euclidean':
        return np.sqrt(np.sum(d * d, axis=2))
    if metric == 'absolute':
        return np.sum(np.abs(d), axis=2)
    if metric == 'squared':
        return np.sum(d * d, axis=2)
    if metric == 'symmkl':
        with np.errstate(divide='ignore', invalid='ignore'):
            return np.sum((X[:, None, :] - Y[None, :, :]) * (np.log(X[:, None, :]) - np.log(Y[None, :, :])), axis=2)
    raise err(f'MATLAB:{fn}:metric', "The metric is 'euclidean', 'absolute', 'squared' or 'symmkl'.", fn)


def _band(nx, ny, maxsamp):
    """Cells allowed: within maxsamp of the straight line from the first pair of samples to the last."""
    i = np.arange(nx)[:, None]
    j = np.arange(ny)[None, :]
    line = i * (ny - 1) / max(nx - 1, 1)
    return np.abs(j - line) <= maxsamp + 1e-9


def _warp_args(args, fn, with_tol):
    nargchk(args, 2 + with_tol, 5 + with_tol, fn)
    X, Y = _samples(args[0], fn), _samples(args[1], fn)
    k = 2
    tol = None
    if with_tol:
        tol = _num(args[2], fn, 'tol')
        k = 3
    metric, maxsamp = 'euclidean', math.inf
    for a in args[k:]:
        if is_str(a):
            metric = py_str(a).lower()
        elif numel(a):
            maxsamp = _num(a, fn, 'maxsamp')
    return X, Y, tol, metric, maxsamp


def _path(prev, nx, ny):
    i, j = nx - 1, ny - 1
    ix, iy = [i], [j]
    while i > 0 or j > 0:
        step = prev[i, j]
        if step == 0:
            i, j = i - 1, j - 1
        elif step == 1:
            i = i - 1
        else:
            j = j - 1
        ix.append(i)
        iy.append(j)
    return np.array(ix[::-1]) + 1.0, np.array(iy[::-1]) + 1.0


def _warp_plot(fn, args, ix, iy, dist):
    x, y = _samples(args[0], fn), _samples(args[1], fn)
    _b('subplot', 2.0, 1.0, 1.0)
    _b('plot', out(x), Char.of('-'))
    _b('hold', Char.of('on'))
    _b('plot', out(y), Char.of('-'))
    _b('hold', Char.of('off'))
    _b('title', Char.of('Original Signals'))
    _b('subplot', 2.0, 1.0, 2.0)
    _b('plot', out(x[(ix - 1).astype(int)]))
    _b('hold', Char.of('on'))
    _b('plot', out(y[(iy - 1).astype(int)]))
    _b('hold', Char.of('off'))
    _b('title', Char.of(f'Aligned Signals ({"Euclidean" if fn == "dtw" else "Edit"} Distance: {dist:g})'))
    return None


@bi('dtw', nout=3)
def dtw(nargout, *args):
    """[dist, ix, iy] = dtw(x, y, maxsamp, metric): dynamic time warping: the smallest sum of distances between samples along a path of steps (1, 0), (0, 1) and (1, 1) from the first pair to the last; ix and iy the path; maxsamp keeps it within that many samples of the straight line; metric 'euclidean' (default), 'absolute', 'squared' or 'symmkl'. Matrices' columns are samples."""
    X, Y, _, metric, maxsamp = _warp_args(args, 'dtw', 0)
    nx, ny = X.shape[0], Y.shape[0]
    d = _local(X, Y, metric, 'dtw')
    allowed = _band(nx, ny, maxsamp)
    Dm = np.full((nx, ny), np.inf)
    prev = np.zeros((nx, ny), np.int8)
    for i in range(nx):
        for j in range(ny):
            if not allowed[i, j]:
                continue
            if i == 0 and j == 0:
                Dm[i, j] = d[i, j]
                continue
            best, step = np.inf, 0
            if i > 0 and j > 0 and Dm[i - 1, j - 1] < best:
                best, step = Dm[i - 1, j - 1], 0
            if i > 0 and Dm[i - 1, j] < best:
                best, step = Dm[i - 1, j], 1
            if j > 0 and Dm[i, j - 1] < best:
                best, step = Dm[i, j - 1], 2
            Dm[i, j] = d[i, j] + best
            prev[i, j] = step
    dist = float(Dm[-1, -1])
    if not np.isfinite(dist):
        return _outs(nargout, math.inf, EMPTY(), EMPTY())
    ix, iy = _path(prev, nx, ny)
    if nargout == 0:
        return _warp_plot('dtw', args, ix, iy, dist)
    return _outs(nargout, dist, _col(ix), _col(iy))


@bi('edr', nout=3)
def edr(nargout, *args):
    """[dist, ix, iy] = edr(x, y, tol, maxsamp, metric): the edit distance on real signals: the fewest insertions, deletions and substitutions, two samples matching when their distance is at most tol; ix and iy the alignment."""
    X, Y, tol, metric, maxsamp = _warp_args(args, 'edr', 1)
    nx, ny = X.shape[0], Y.shape[0]
    sub = (_local(X, Y, metric, 'edr') > tol).astype(float)
    allowed = _band(nx, ny, maxsamp)
    Dm = np.full((nx + 1, ny + 1), np.inf)
    Dm[0, :] = np.arange(ny + 1)
    Dm[:, 0] = np.arange(nx + 1)
    prev = np.zeros((nx + 1, ny + 1), np.int8)
    prev[0, 1:] = 2
    prev[1:, 0] = 1
    for i in range(1, nx + 1):
        for j in range(1, ny + 1):
            if not allowed[i - 1, j - 1]:
                continue
            c = (Dm[i - 1, j - 1] + sub[i - 1, j - 1], Dm[i - 1, j] + 1, Dm[i, j - 1] + 1)
            k = int(np.argmin(c))
            Dm[i, j], prev[i, j] = c[k], k
    dist = float(Dm[nx, ny])
    if not np.isfinite(dist):
        return _outs(nargout, math.inf, EMPTY(), EMPTY())
    i, j = nx, ny
    ix, iy = [], []
    while i > 0 and j > 0:
        ix.append(i)
        iy.append(j)
        s = prev[i, j]
        if s == 0:
            i, j = i - 1, j - 1
        elif s == 1:
            i -= 1
        else:
            j -= 1
    while i > 0:
        ix.append(i)
        iy.append(1)
        i -= 1
    while j > 0:
        ix.append(1)
        iy.append(j)
        j -= 1
    ix, iy = np.array(ix[::-1], float), np.array(iy[::-1], float)
    if nargout == 0:
        return _warp_plot('edr', args, ix, iy, dist)
    return _outs(nargout, dist, _col(ix), _col(iy))


# ---- mode decompositions --------------------------------------------------------------------------------------------------------------

def _extrema(h):
    d = np.diff(h)
    mx = np.flatnonzero((np.hstack([d, 0]) < 0) & (np.hstack([0, d]) > 0))
    mn = np.flatnonzero((np.hstack([d, 0]) > 0) & (np.hstack([0, d]) < 0))
    return mx, mn


def _envelope(t, h, idx, kind):
    """A spline through h at idx, the extrema mirrored about both ends so the envelope reaches them."""
    from scipy.interpolate import CubicSpline, PchipInterpolator
    n = h.size
    left = idx[:2]
    right = idx[-2:]
    ti = np.concatenate([-left[::-1].astype(float), idx.astype(float), (2 * (n - 1) - right[::-1]).astype(float)])
    vi = np.concatenate([h[left[::-1]], h[idx], h[right[::-1]]])
    ti, k = np.unique(ti, return_index=True)
    vi = vi[k]
    f = PchipInterpolator(ti, vi) if kind == 'pchip' else CubicSpline(ti, vi)
    return f(t)


@bi('emd', nout=3)
def emd(nargout, *args):
    """[imf, residual, info] = emd(x, 'MaxNumIMF', 10, 'SiftRelativeTolerance', 0.2, 'SiftMaxIterations', 100, 'MaxNumExtrema', 1, 'MaxEnergyRatio', 20, 'Interpolation', 'spline'): empirical mode decomposition: intrinsic mode functions sifted out one by one, the fastest first (columns of imf); x = sum(imf, 2) + residual."""
    o, rest = _nv(args, ('MaxNumIMF', 'SiftRelativeTolerance', 'SiftMaxIterations', 'MaxNumExtrema', 'MaxEnergyRatio', 'Interpolation', 'Display'), 'emd')
    nargchk(rest, 1, 1, 'emd')
    x = _vec(rest[0], 'emd').astype(float)
    g = lambda k, d: _num(o[k], 'emd', k) if k in o else d  # noqa: E731
    maxn, tol, maxit = int(g('MaxNumIMF', 10)), g('SiftRelativeTolerance', 0.2), int(g('SiftMaxIterations', 100))
    maxext, maxratio = g('MaxNumExtrema', 1), g('MaxEnergyRatio', 20)
    kind = py_str(o['Interpolation']).lower() if 'Interpolation' in o else 'spline'
    if kind not in ('spline', 'pchip'):
        raise err('MATLAB:emd:interp', "Interpolation is 'spline' or 'pchip'.", 'emd')
    n = x.size
    t = np.arange(n, dtype=float)
    r = x.copy()
    imfs, nsift, nex, nzc, menv, rtol = [], [], [], [], [], []
    ex0 = float(np.sum(x * x))
    for _ in range(maxn):
        mx, mn = _extrema(r)
        if mx.size + mn.size <= maxext or mx.size < 2 or mn.size < 2:
            break
        if ex0 > 0 and float(np.sum(r * r)) > 0 and 10 * math.log10(ex0 / float(np.sum(r * r))) > maxratio:
            break
        h = r.copy()
        it, sd, envE = 0, math.inf, 0.0
        for it in range(1, maxit + 1):
            mx, mn = _extrema(h)
            if mx.size < 2 or mn.size < 2:
                break
            m = (_envelope(t, h, mx, kind) + _envelope(t, h, mn, kind)) / 2
            hn = h - m
            sd = float(np.sum((h - hn) ** 2) / max(np.sum(h * h), 1e-300))
            envE = float(np.sum(m * m))
            h = hn
            if sd < tol:
                break
        imfs.append(h)
        r = r - h
        mx, mn = _extrema(h)
        nex.append(mx.size + mn.size)
        nzc.append(int(np.sum(np.diff(np.signbit(h).astype(int)) != 0)))
        nsift.append(it)
        menv.append(envE)
        rtol.append(sd)
    imf = np.column_stack(imfs) if imfs else np.zeros((n, 0))
    info = Struct.scalar({'NumIMF': out(np.arange(1, len(imfs) + 1, dtype=float).reshape(-1, 1)) if imfs else EMPTY(),
                          'NumExtrema': _col(np.array(nex, float)) if imfs else EMPTY(), 'NumZerocrossing': _col(np.array(nzc, float)) if imfs else EMPTY(),
                          'NumSifting': _col(np.array(nsift, float)) if imfs else EMPTY(), 'MeanEnvelopeEnergy': _col(menv) if imfs else EMPTY(),
                          'RelativeTolerance': _col(rtol) if imfs else EMPTY()})
    if nargout == 0:
        return _modes_plot(x, imf, r, 'IMF')
    return _outs(nargout, out(imf), _col(r), info)


def _modes_plot(x, imf, r, word):
    k = imf.shape[1]
    rows = float(k + 2)
    _b('subplot', rows, 1.0, 1.0)
    _b('plot', _col(x))
    _b('ylabel', Char.of('Signal'))
    for j in range(k):
        _b('subplot', rows, 1.0, float(j + 2))
        _b('plot', _col(imf[:, j]))
        _b('ylabel', Char.of(f'{word} {j + 1}'))
    _b('subplot', rows, 1.0, rows)
    _b('plot', _col(r))
    _b('ylabel', Char.of('Residual'))
    return None


@bi('vmd', nout=3)
def vmd(nargout, *args):
    """[imf, residual, info] = vmd(x, 'NumIMF', 5, 'PenaltyFactor', 1000, 'LMUpdateRate', 0.01, 'InitializeMethod', 'peaks', 'MaxIterations', 500, 'AbsoluteTolerance', 5e-6, 'RelativeTolerance', 1e-3): variational mode decomposition (Dragomiretskiy and Zosso), by the alternating direction method in the frequency domain on the signal mirrored at both ends; modes from the highest central frequency down."""
    o, rest = _nv(args, ('NumIMF', 'PenaltyFactor', 'LMUpdateRate', 'InitializeMethod', 'CentralFrequencies', 'MaxIterations', 'AbsoluteTolerance',
                         'RelativeTolerance', 'InitialLM', 'Display'), 'vmd')
    nargchk(rest, 1, 1, 'vmd')
    x = _vec(rest[0], 'vmd').astype(float)
    g = lambda k, d: _num(o[k], 'vmd', k) if k in o else d  # noqa: E731
    K = int(g('NumIMF', 5))
    alpha, tau, maxit = g('PenaltyFactor', 1000.0), g('LMUpdateRate', 0.01), int(g('MaxIterations', 500))
    atol, rtol = g('AbsoluteTolerance', 5e-6), g('RelativeTolerance', 1e-3)
    n = x.size
    h1, h2 = n // 2, n - n // 2
    f = np.concatenate([x[:h1][::-1], x, x[n - h2:][::-1]])
    T = f.size
    freqs = np.arange(T) / T - 0.5 - 1.0 / T
    fh = np.fft.fftshift(np.fft.fft(f))
    fp = fh.copy()
    fp[:T // 2] = 0
    method = py_str(o['InitializeMethod']).lower() if 'InitializeMethod' in o else 'peaks'
    if 'CentralFrequencies' in o:
        omega = np.asarray(darr(o['CentralFrequencies']), float).reshape(-1)[:K]
    elif method == 'peaks':
        spec = np.abs(fp[T // 2:])
        fr = freqs[T // 2:]
        pk = np.flatnonzero((spec[1:-1] > spec[:-2]) & (spec[1:-1] >= spec[2:])) + 1
        pk = pk[np.argsort(-spec[pk])][:K]
        omega = np.sort(np.concatenate([fr[pk], np.linspace(0, 0.5, K + 2)[1:-1][:K - pk.size]]))
    elif method == 'grid':
        omega = (0.5 / K) * np.arange(K)
    elif method == 'random':
        from .elmat import RNG
        omega = np.sort(np.exp(np.log(1.0 / n) + (np.log(0.5) - np.log(1.0 / n)) * RNG.rs.random_sample(K)))
    else:
        raise err('MATLAB:vmd:init', "InitializeMethod is 'peaks', 'grid' or 'random', or give CentralFrequencies.", 'vmd')
    u = np.zeros((K, T), complex)
    lam = np.zeros(T, complex)
    half = slice(T // 2, T)
    it, absimp, relimp, flag = 0, math.inf, math.inf, 1
    for it in range(1, maxit + 1):
        old = u.copy()
        for k in range(K):
            others = u.sum(axis=0) - u[k]
            u[k] = (fp - others - lam / 2) / (1 + alpha * (freqs - omega[k]) ** 2)
            pw = np.abs(u[k, half]) ** 2
            omega[k] = float(freqs[half] @ pw / max(pw.sum(), 1e-300))
        lam = lam + tau * (u.sum(axis=0) - fp)
        diff = np.sum(np.abs(u - old) ** 2, axis=1) / T
        absimp = float(np.mean(diff))
        relimp = float(np.mean(diff / np.maximum(np.sum(np.abs(old) ** 2, axis=1) / T, 1e-300)))
        if absimp < atol and relimp < rtol:
            flag = 0
            break
    full = np.zeros((K, T), complex)
    full[:, half] = u[:, half]
    full[:, 1:T // 2 + (T % 2)] = np.conj(u[:, half][:, ::-1][:, :T // 2 - 1 + (T % 2)]) if T > 2 else full[:, 1:1]
    full[:, 0] = np.conj(full[:, -1])
    modes = np.real(np.fft.ifft(np.fft.ifftshift(full, axes=1), axis=1))[:, h1:h1 + n]
    order = np.argsort(-omega)
    modes, omega = modes[order], omega[order]
    imf = modes.T
    r = x - imf.sum(axis=1)
    info = Struct.scalar({'ExitFlag': float(flag), 'CentralFrequencies': _col(omega), 'NumIterations': float(it),
                          'AbsoluteImprovement': absimp, 'RelativeImprovement': relimp, 'LagrangeMultiplier': _col(lam)})
    if nargout == 0:
        return _modes_plot(x, imf, r, 'IMF')
    return _outs(nargout, out(imf), _col(r), info)


# ---- the Wigner-Ville distribution ------------------------------------------------------------------------------------------------------

@bi('wvd', nout=3)
def wvd(nargout, *args):
    """[d, f, t] = wvd(x, fs, 'smoothedPseudo', twin, fwin, 'NumFrequencyPoints', nf): the Wigner-Ville distribution of the analytic signal of x (x itself when complex): sum over lags m of z(n+m) conj(z(n-m)) exp(-2*pi*i*k*m/nf) at each time n, frequencies k*fs/(2*nf); 'smoothedPseudo' smooths in time and frequency with Kaiser windows (or the windows given)."""
    o, rest = _nv(args, ('NumFrequencyPoints', 'NumTimePoints', 'MinThreshold'), 'wvd')
    smooth = False
    tw = fw = None
    if len(rest) > 1 and any(is_str(a) and py_str(a).lower() == 'smoothedpseudo' for a in rest):
        k = next(i for i, a in enumerate(rest) if is_str(a) and py_str(a).lower() == 'smoothedpseudo')
        smooth = True
        extra = rest[k + 1:]
        rest = rest[:k]
        if extra and numel(extra[0]):
            tw = np.asarray(darr(extra[0]), float).reshape(-1)
        if len(extra) > 1 and numel(extra[1]):
            fw = np.asarray(darr(extra[1]), float).reshape(-1)
    nargchk(rest, 1, 2, 'wvd')
    xv = darr(rest[0], 'wvd').reshape(-1)
    fs, given = _fs(rest, 1, 'wvd')
    z = xv.astype(complex) if np.iscomplexobj(xv) else _S().hilbert(xv.astype(float))
    n = z.size
    nf = int(_num(o['NumFrequencyPoints'], 'wvd', 'NumFrequencyPoints')) if 'NumFrequencyPoints' in o else n + (n % 2)
    if smooth:
        if fw is None:
            L = 2 * (max(n // 8, 2) // 2) + 1
            fw = np.kaiser(L, 20.0)
        if tw is None:
            L = 2 * (max(n // 20, 1) // 2) + 1
            tw = np.kaiser(L, 20.0)
    Lh = (fw.size - 1) // 2 if fw is not None else n
    Lg = (tw.size - 1) // 2 if tw is not None else 0
    K = np.zeros((nf, n), complex)
    for tt in range(n):
        mmax = min(tt, n - 1 - tt, nf // 2 - 1, Lh)
        m = np.arange(-mmax, mmax + 1)
        if smooth and Lg > 0:
            acc = np.zeros(m.size, complex)
            gsum = 0.0
            for p in range(-Lg, Lg + 1):
                a, b = tt - p + m, tt - p - m
                ok = (a >= 0) & (a < n) & (b >= 0) & (b < n)
                v = np.zeros(m.size, complex)
                v[ok] = z[a[ok]] * np.conj(z[b[ok]])
                acc += tw[p + Lg] * v
                gsum += tw[p + Lg]
            r = acc / gsum
        else:
            r = z[tt + m] * np.conj(z[tt - m])
        if smooth:
            r = r * fw[Lh + m]
        K[m % nf, tt] = r
    d = np.real(np.fft.fft(K, axis=0))
    f = np.arange(nf) * fs / (2 * nf)
    t = np.arange(n) / fs
    if 'MinThreshold' in o:
        d = np.where(d < _num(o['MinThreshold'], 'wvd', 'MinThreshold'), 0.0, d)
    fo = f if given else f * 2 * np.pi
    if nargout == 0:
        _b('imagesc', out(t.reshape(1, -1)), out((fo if given else fo / np.pi).reshape(-1, 1)), out(d))
        _b('axis', Char.of('xy'))
        _b('colorbar')
        _b('xlabel', Char.of('Time (s)' if given else 'Samples'))
        _b('ylabel', Char.of('Frequency (Hz)' if given else 'Normalized Frequency (\\times\\pi rad/sample)'))
        _b('title', Char.of('Smoothed Pseudo Wigner-Ville Distribution' if smooth else 'Wigner-Ville Distribution'))
        return None
    return _outs(nargout, out(d), _col(fo), _col(t))
