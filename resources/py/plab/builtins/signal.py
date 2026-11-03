"""Signal processing on SciPy (scipy.signal, scipy.fft): filter design (IIR
and FIR, their orders, designfilt's digital filters), filtering (filtfilt,
sosfilt, medfilt1, sgolayfilt ...), frequency responses, correlation,
resampling, peaks and envelopes, windows, spectra (periodogram, pwelch,
spectrogram, cpsd, mscohere, tfestimate), waveforms and the decibel
conversions.

Frequencies of digital filters are normalized as the language normalizes
them, 1 being half the sampling rate (pi rad/sample), unless a sampling
rate is given. A signal that is a matrix is its columns; a row vector
gives a row back.
"""
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, arr, darr, out, opt_str, is_str
from ..values import MError, Obj, Char, Cell, Struct, FH, EMPTY, class_of, numel, py_str, shape_of
from .. import runtime as R


def _S():
    import scipy.signal as S
    return S


def bi(*names, **kw):
    """Registered as builtins are, with what SciPy or NumPy refuses (a signal
    shorter than its window, sections that are none ...) told as the
    language's error of that function."""
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _int(v, fn, what='order'):
    """A whole number from a scalar argument."""
    a = darr(v, fn).reshape(-1)
    if a.size != 1 or not np.isfinite(a[0]) or a[0] != int(a[0]):
        raise err(f'MATLAB:{fn}:{what}', f'The {what} must be a whole number.', fn)
    return int(a[0])


# ---- shapes ---------------------------------------------------------------------------------------------------

def _signal(v, fn):
    """A signal as columns (a vector as one column) and whether it was a row."""
    a = darr(v, fn)
    if a.ndim > 2:
        raise err(f'MATLAB:{fn}:ndims', f'{fn} takes vectors and matrices.', fn)
    row = a.shape[0] == 1 and a.shape[1] != 1
    return (a.T.copy() if row else a), row


def _back(Y, row):
    Y = np.asarray(Y)
    if Y.ndim == 1:
        Y = Y.reshape(-1, 1)
    return out(Y.T if row else Y)


def _col(v):
    a = np.asarray(v)
    return out(a.reshape(-1, 1))


def _rowv(v):
    return out(np.asarray(v).reshape(1, -1))


def _coef(v, fn):
    return darr(v, fn).reshape(-1)


def _opts(args, names, fn):
    """Name-value options (any case) from args: ({name: value}, the rest)."""
    low = {n.lower(): n for n in names}
    got, rest = {}, []
    i = 0
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s.lower() in low and i + 1 < len(args):
            got[low[s.lower()]] = args[i + 1]
            i += 2
            continue
        rest.append(args[i])
        i += 1
    return got, rest


def _words(args):
    """The text arguments, in lower case, and the others."""
    words, rest = [], []
    for a in args:
        s = opt_str(a)
        (words if s is not None else rest).append(s.lower() if s is not None else a)
    return words, rest


# ---- IIR filters ------------------------------------------------------------------------------------------------

_BTYPE = {'low': 'lowpass', 'high': 'highpass', 'bandpass': 'bandpass', 'stop': 'bandstop', 'bandstop': 'bandstop',
          'lowpass': 'lowpass', 'highpass': 'highpass'}


def _iir(fn, design, n, rp, rs, wn, rest, nargout):
    words, _ = _words(rest)
    analog = 's' in words
    kinds = [w for w in words if w in _BTYPE]
    W = _coef(wn, fn)
    n = _int(n, fn)
    if n < 1:
        raise err(f'MATLAB:{fn}:order', 'The filter order must be a positive whole number.', fn)
    if W.size not in (1, 2):
        raise err(f'MATLAB:{fn}:Wn', 'The cutoff frequency is one number, or two for a band.', fn)
    if not analog and (np.any(W <= 0) or np.any(W >= 1)):
        raise err(f'MATLAB:{fn}:Wn', 'The cutoff frequencies must be between 0 and 1 (1 is half the sampling rate).', fn)
    btype = _BTYPE[kinds[0]] if kinds else ('lowpass' if W.size == 1 else 'bandpass')
    if (btype in ('bandpass', 'bandstop')) != (W.size == 2):
        raise err(f'MATLAB:{fn}:Wn', 'A band needs two cutoff frequencies; low and high one.', fn)
    output = 'zpk' if nargout == 3 else 'ss' if nargout == 4 else 'ba'
    r = _S().iirfilter(n, W if W.size == 2 else W[0], rp=rp, rs=rs, btype=btype, analog=analog, ftype=design, output=output)
    if output == 'ba':
        return _rowv(np.real_if_close(r[0])), _rowv(np.real_if_close(r[1]))
    if output == 'zpk':
        return _col(r[0]), _col(r[1]), float(r[2])
    return tuple(out(np.atleast_2d(m)) for m in r)


@bi('butter', nout=4)
def butter(nargout, *args):
    """[b, a] = butter(n, Wn, ftype, 's'): a Butterworth filter."""
    nargchk(args, 2, 4, 'butter')
    return _iir('butter', 'butter', args[0], None, None, args[1], args[2:], nargout)


@bi('cheby1', nout=4)
def cheby1(nargout, *args):
    """[b, a] = cheby1(n, Rp, Wp, ftype, 's'): a Chebyshev type I filter, Rp dB of passband ripple."""
    nargchk(args, 3, 5, 'cheby1')
    return _iir('cheby1', 'cheby1', args[0], _num(args[1], 'cheby1'), None, args[2], args[3:], nargout)


@bi('cheby2', nout=4)
def cheby2(nargout, *args):
    """[b, a] = cheby2(n, Rs, Ws, ftype, 's'): a Chebyshev type II filter, its stopband Rs dB down."""
    nargchk(args, 3, 5, 'cheby2')
    return _iir('cheby2', 'cheby2', args[0], None, _num(args[1], 'cheby2'), args[2], args[3:], nargout)


@bi('ellip', nout=4)
def ellip(nargout, *args):
    """[b, a] = ellip(n, Rp, Rs, Wp, ftype, 's'): an elliptic filter."""
    nargchk(args, 4, 6, 'ellip')
    return _iir('ellip', 'ellip', args[0], _num(args[1], 'ellip'), _num(args[2], 'ellip'), args[3], args[4:], nargout)


def _num(v, fn):
    a = darr(v, fn).reshape(-1)
    if a.size != 1:
        raise err(f'MATLAB:{fn}:scalar', 'The ripple and attenuation are numbers (in dB).', fn)
    return float(a[0])


def _ord(fn, scipy_fn, args, nargout):
    words, rest = _words(args)
    analog = 's' in words
    wp, ws = _coef(rest[0], fn), _coef(rest[1], fn)
    gp, gs = float(darr(rest[2]).flat[0]), float(darr(rest[3]).flat[0])
    n, wn = scipy_fn(wp if wp.size > 1 else wp[0], ws if ws.size > 1 else ws[0], gp, gs, analog=analog)
    wn = np.atleast_1d(wn)
    return float(n), (_rowv(wn) if wn.size > 1 else float(wn[0]))


@bi('buttord', nout=2)
def buttord(nargout, *args):
    nargchk(args, 4, 5, 'buttord')
    return _ord('buttord', _S().buttord, args, nargout)


@bi('cheb1ord', nout=2)
def cheb1ord(nargout, *args):
    nargchk(args, 4, 5, 'cheb1ord')
    return _ord('cheb1ord', _S().cheb1ord, args, nargout)


@bi('cheb2ord', nout=2)
def cheb2ord(nargout, *args):
    nargchk(args, 4, 5, 'cheb2ord')
    return _ord('cheb2ord', _S().cheb2ord, args, nargout)


@bi('ellipord', nout=2)
def ellipord(nargout, *args):
    nargchk(args, 4, 5, 'ellipord')
    return _ord('ellipord', _S().ellipord, args, nargout)


# ---- FIR filters --------------------------------------------------------------------------------------------------

def _fir_scale(h, bands_pass):
    """h scaled to 1 at the middle of its first passband (0 when it starts
    at 0, 1 when it ends at 1), as SciPy's firwin scales."""
    n = h.size - 1
    lo, hi = bands_pass[0]
    f0 = 0.0 if lo == 0 else 1.0 if hi == 1 else (lo + hi) / 2
    k = np.arange(h.size) - n / 2
    s = np.sum(h * np.cos(np.pi * f0 * k))
    return h / s


@bi('fir1')
def fir1(nargout, *args):
    """b = fir1(n, Wn, ftype, window, scaleopt): a window-method FIR filter of order n."""
    nargchk(args, 2, 5, 'fir1')
    n = int(darr(args[0]).flat[0])
    W = _coef(args[1], 'fir1')
    words, rest = _words(args[2:])
    if np.any(W <= 0) or np.any(W >= 1):
        raise err('MATLAB:fir1:Wn', 'The cutoff frequencies must be between 0 and 1 (1 is half the sampling rate).', 'fir1')
    kinds = [w for w in words if w in ('low', 'high', 'bandpass', 'stop', 'dc-0', 'dc-1')]
    kind = kinds[0] if kinds else ('low' if W.size == 1 else 'bandpass' if W.size == 2 else 'dc-0')
    pass_zero = kind in ('low', 'stop', 'dc-1')
    if not pass_zero and kind == 'high' or kind == 'stop':
        # a highpass or bandstop filter has an even order
        if n % 2:
            n += 1
    win = None
    for r in rest:
        if numel(r):
            win = darr(r).reshape(-1)
    if win is None:
        win = _S().get_window('hamming', n + 1, fftbins=False)
    elif win.size != n + 1:
        raise err('MATLAB:fir1:window', f'The window must have n+1 = {n + 1} points.', 'fir1')
    h = _S().firwin(n + 1, W, window='boxcar', pass_zero=pass_zero, scale=False) * win
    if 'noscale' not in words:
        edges = np.concatenate([[0.0], W, [1.0]])
        bands = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
        passing = bands[0::2] if pass_zero else bands[1::2]
        h = _fir_scale(h, passing)
    return _rowv(h)


@bi('fir2')
def fir2(nargout, *args):
    """b = fir2(n, f, m, npt, window): an FIR filter of order n with the magnitude m at the frequencies f."""
    nargchk(args, 3, 6, 'fir2')
    n = int(darr(args[0]).flat[0])
    f, m = _coef(args[1], 'fir2'), _coef(args[2], 'fir2')
    if f[0] != 0 or f[-1] != 1:
        raise err('MATLAB:fir2:f', 'The frequencies must run from 0 to 1.', 'fir2')
    if n % 2 and m[-1] != 0:
        n += 1
    npt = int(darr(args[3]).flat[0]) if len(args) > 3 and numel(args[3]) == 1 and not is_str(args[3]) else 512
    win = darr(args[-1]).reshape(-1) if len(args) > 3 and numel(args[-1]) == n + 1 else 'hamming'
    if isinstance(win, np.ndarray):
        h = _S().firwin2(n + 1, f, m, nfreqs=max(npt, n + 2) + 1, window=None) * win
    else:
        h = _S().firwin2(n + 1, f, m, nfreqs=max(npt, n + 2) + 1, window=win)
    return _rowv(h)


@bi('firls')
def firls(nargout, *args):
    """b = firls(n, f, a, w): the least-squares FIR filter of order n."""
    nargchk(args, 3, 4, 'firls')
    n = int(darr(args[0]).flat[0])
    if n % 2:
        raise err('MATLAB:firls:order', 'firls here takes an even order (an odd number of coefficients).', 'firls')
    f, a = _coef(args[1], 'firls'), _coef(args[2], 'firls')
    w = _coef(args[3], 'firls') if len(args) > 3 else None
    return _rowv(_S().firls(n + 1, f, a, weight=w, fs=2))


@bi('firpm', 'remez')
def firpm(nargout, *args):
    """b = firpm(n, f, a, w, ftype): the equiripple (Parks-McClellan) FIR filter of order n."""
    nargchk(args, 3, 5, 'firpm')
    n = int(darr(args[0]).flat[0])
    f, a = _coef(args[1], 'firpm'), _coef(args[2], 'firpm')
    if f.size % 2 or a.size != f.size:
        raise err('MATLAB:firpm:bands', 'f and a give the edges of the bands in pairs, a amplitude at each edge.', 'firpm')
    if np.any(a[0::2] != a[1::2]):
        raise err('MATLAB:firpm:slope', 'Each band has one amplitude here (a(k) = a(k+1) for each band).', 'firpm')
    words, rest = _words(args[3:])
    w = _coef(rest[0], 'firpm') if rest else None
    kind = 'hilbert' if 'hilbert' in words else 'differentiator' if 'differentiator' in words else 'bandpass'
    return _rowv(_S().remez(n + 1, f, a[0::2], weight=w, type=kind, fs=2))


@bi('kaiserord', nout=4)
def kaiserord(nargout, *args):
    """[n, Wn, beta, ftype] = kaiserord(f, a, dev, fs): the order and Kaiser beta for a window-method design."""
    nargchk(args, 3, 4, 'kaiserord')
    f, a, dev = _coef(args[0], 'kaiserord'), _coef(args[1], 'kaiserord'), _coef(args[2], 'kaiserord')
    fs = float(darr(args[3]).flat[0]) if len(args) > 3 else 2.0
    if f.size != 2 * (a.size - 1) or dev.size != a.size:
        raise err('MATLAB:kaiserord:sizes', 'f gives the band edges in pairs; a and dev a value for each band.', 'kaiserord')
    A = -20 * math.log10(float(np.min(dev)))
    width = float(np.min(f[1::2] - f[0::2])) / (fs / 2) * np.pi
    n = int(math.ceil((A - 7.95) / (2.285 * width))) if A > 21 else int(math.ceil(5.79 / width))
    beta = 0.1102 * (A - 8.7) if A > 50 else 0.5842 * (A - 21) ** 0.4 + 0.07886 * (A - 21) if A >= 21 else 0.0
    wn = (f[0::2] + f[1::2]) / 2 / (fs / 2)
    if a[0] == 0 and a.size == 2 or (a.size > 2 and a[0] == 0):
        kind = 'high' if a.size == 2 else 'DC-0'
    else:
        kind = 'low' if a.size == 2 else ('stop' if a.size == 3 else 'DC-1')
    if a.size == 3 and a[0] == 0:
        kind = 'bandpass'
    if kind in ('high', 'stop') and n % 2:
        n += 1
    return float(n), (float(wn[0]) if wn.size == 1 else _rowv(wn)), float(beta), Char.of(kind)


# ---- filtering ---------------------------------------------------------------------------------------------------------

def _ba(args, fn):
    """(b, a) or ('sos', sos, g) from a filter's arguments, and the arguments after them."""
    if args and isinstance(args[0], DigitalFilter):
        d = args[0]
        return (('sos', d.sos, 1.0) if d.sos is not None else ('ba', d.b, np.array([1.0]))), args[1:]
    b = darr(args[0], fn)
    if b.ndim == 2 and b.shape[1] == 6 and b.shape[0] > 1:
        # second-order sections (one 1-by-6 row is a transfer function's coefficients)
        g = darr(args[1]).reshape(-1) if numel(args[1]) else np.array([1.0])
        return ('sos', np.array(b), float(np.prod(g))), args[2:]
    return ('ba', b.reshape(-1), darr(args[1], fn).reshape(-1)), args[2:]


@bi('filtfilt')
def filtfilt(nargout, *args):
    """y = filtfilt(b, a, x), filtfilt(sos, g, x), filtfilt(d, x): zero-phase filtering, forward and backward."""
    nargchk(args, 2, 3, 'filtfilt')
    if len(args) < 3 and not isinstance(args[0], DigitalFilter):
        raise err('MATLAB:minrhs', 'filtfilt takes b, a and x (or a digital filter and x).', 'filtfilt')
    f, rest = _ba(args, 'filtfilt')
    X, row = _signal(rest[0], 'filtfilt')
    S = _S()
    if f[0] == 'sos':
        _, sos, g = f
        pad = 3 * (2 * sos.shape[0])
        if X.shape[0] <= pad:
            raise err('MATLAB:filtfilt:InvalidDimensionsDataShortForFiltOrder', f'The data must have more than {pad} samples (3 times the filter order).', 'filtfilt')
        Y = S.sosfiltfilt(sos, X, axis=0, padtype='odd', padlen=pad) * g * g
    else:
        _, b, a = f
        nf = max(b.size, a.size)
        pad = 3 * (nf - 1)
        if X.shape[0] <= pad:
            raise err('MATLAB:filtfilt:InvalidDimensionsDataShortForFiltOrder', f'The data must have more than {pad} samples (3 times the filter order).', 'filtfilt')
        Y = S.filtfilt(b, a, X, axis=0, padtype='odd', padlen=pad)
    return _back(Y, row)


@bi('sosfilt')
def sosfilt(nargout, *args):
    """y = sosfilt(sos, x): filtering by second-order sections (rows b0 b1 b2 a0 a1 a2)."""
    nargchk(args, 2, 3, 'sosfilt')
    sos = darr(args[0], 'sosfilt')
    if sos.ndim != 2 or sos.shape[1] != 6:
        raise err('MATLAB:sosfilt:sos', 'The sections are an L-by-6 matrix.', 'sosfilt')
    X, row = _signal(args[1], 'sosfilt')
    return _back(_S().sosfilt(np.array(sos), X, axis=0), row)


@bi('fftfilt')
def fftfilt(nargout, *args):
    """y = fftfilt(b, x): FIR filtering by the overlap-add FFT method (as filter(b, 1, x))."""
    nargchk(args, 2, 3, 'fftfilt')
    b = _coef(args[0], 'fftfilt')
    X, row = _signal(args[1], 'fftfilt')
    Y = _S().oaconvolve(X, b.reshape(-1, 1), axes=0)[:X.shape[0]]
    return _back(np.real_if_close(Y) if np.isrealobj(X) and np.isrealobj(b) else Y, row)


@bi('filtic')
def filtic(nargout, *args):
    """zi = filtic(b, a, y, x): initial conditions for filter from past outputs y and inputs x (latest first)."""
    nargchk(args, 3, 4, 'filtic')
    b, a = _coef(args[0], 'filtic'), _coef(args[1], 'filtic')
    y = _coef(args[2], 'filtic')
    x = _coef(args[3], 'filtic') if len(args) > 3 else None
    return _col(_S().lfiltic(b, a, y, x))


@bi('upfirdn')
def upfirdn(nargout, *args):
    """y = upfirdn(x, h, p, q): upsample by p, FIR filter by h, downsample by q."""
    nargchk(args, 2, 4, 'upfirdn')
    X, row = _signal(args[0], 'upfirdn')
    h = _coef(args[1], 'upfirdn')
    p = int(darr(args[2]).flat[0]) if len(args) > 2 else 1
    q = int(darr(args[3]).flat[0]) if len(args) > 3 else 1
    return _back(_S().upfirdn(h, X, p, q, axis=0), row)


def _sliding(X, n, fill, trunc):
    """Windows of n samples down each column: for sample k, from k - floor(n/2) on."""
    m = X.shape[0]
    lo = n // 2
    P = np.full((m + n, X.shape[1]), np.nan if trunc else fill, dtype=float)
    P[lo:lo + m] = X
    idx = np.arange(m)[:, None] + np.arange(n)[None, :]
    return P[idx]           # m x n x columns


@bi('medfilt1')
def medfilt1(nargout, *args):
    """y = medfilt1(x, n, blksz, dim, nanflag, padding): the median of n samples about each one (n = 3)."""
    nargchk(args, 1, 7, 'medfilt1')
    words, rest = _words(args[1:])
    n = int(darr(rest[0]).flat[0]) if rest and numel(rest[0]) else 3
    dim = int(darr(rest[2]).flat[0]) if len(rest) > 2 and numel(rest[2]) else None
    a = darr(args[0], 'medfilt1')
    if dim is None:
        row = a.shape[0] == 1 and a.shape[1] != 1
        X = a.T if row else a
    else:
        row = dim == 2
        X = a.T if row else a
    W = _sliding(X.astype(float), n, 0.0, 'truncate' in words)
    with np.errstate(all='ignore'):
        if 'truncate' in words or 'omitnan' in words:
            Y = np.nanmedian(W, axis=1) if 'omitnan' in words or 'truncate' in words else np.median(W, axis=1)
        else:
            Y = np.median(W, axis=1)
    return _back(Y, row)


@bi('sgolay', nout=2)
def sgolay(nargout, *args):
    """[B, G] = sgolay(order, framelen): the Savitzky-Golay projection matrix and differentiation filters."""
    nargchk(args, 2, 3, 'sgolay')
    k, f = int(darr(args[0]).flat[0]), int(darr(args[1]).flat[0])
    if f % 2 == 0 or k >= f:
        raise err('MATLAB:sgolay:frame', 'The frame length must be odd and larger than the order.', 'sgolay')
    t = np.arange(f) - (f - 1) / 2
    Sv = t[:, None] ** np.arange(k + 1)[None, :]
    G = Sv @ np.linalg.inv(Sv.T @ Sv)
    B = G @ Sv.T
    return (out(B), out(G)) if nargout > 1 else out(B)


@bi('sgolayfilt')
def sgolayfilt(nargout, *args):
    """y = sgolayfilt(x, order, framelen): Savitzky-Golay smoothing (each sample the value of a polynomial fitted about it)."""
    nargchk(args, 3, 5, 'sgolayfilt')
    X, row = _signal(args[0], 'sgolayfilt')
    k, f = int(darr(args[1]).flat[0]), int(darr(args[2]).flat[0])
    if len(args) > 3 and numel(args[3]):
        raise err('MATLAB:sgolayfilt:weights', 'Weights are not taken here.', 'sgolayfilt')
    if f % 2 == 0 or k >= f:
        raise err('MATLAB:sgolayfilt:frame', 'The frame length must be odd and larger than the order.', 'sgolayfilt')
    if X.shape[0] < f:
        raise err('MATLAB:sgolayfilt:short', f'The signal must have at least {f} samples (the frame length).', 'sgolayfilt')
    return _back(_S().savgol_filter(X, f, k, axis=0, mode='interp'), row)


@bi('hilbert')
def hilbert(nargout, *args):
    """y = hilbert(x, n): the analytic signal, x + i*(its Hilbert transform)."""
    nargchk(args, 1, 2, 'hilbert')
    X, row = _signal(args[0], 'hilbert')
    n = int(darr(args[1]).flat[0]) if len(args) > 1 else None
    if np.iscomplexobj(X):
        X = X.real
    return _back(_S().hilbert(X, N=n, axis=0), row)


@bi('envelope', nout=2)
def envelope(nargout, *args):
    """[up, lo] = envelope(x), envelope(x, np, 'peak'): upper and lower envelopes."""
    nargchk(args, 1, 3, 'envelope')
    X, row = _signal(args[0], 'envelope')
    words, rest = _words(args[1:])
    S = _S()
    if 'peak' in words:
        npk = int(darr(rest[0]).flat[0]) if rest else 1
        from scipy.interpolate import CubicSpline
        t = np.arange(X.shape[0])
        U, L = np.empty_like(X, dtype=float), np.empty_like(X, dtype=float)
        for j in range(X.shape[1]):
            x = X[:, j].astype(float)
            for target, sign in ((U, 1), (L, -1)):
                pk, _ = S.find_peaks(sign * x, distance=max(npk, 1))
                pts = np.unique(np.concatenate([[0], pk, [x.size - 1]]))
                target[:, j] = CubicSpline(pts, x[pts])(t) if pts.size > 2 else np.interp(t, pts, x[pts])
    elif not words or 'analytic' in words:
        if rest:
            raise err('MATLAB:envelope:length', 'An FIR Hilbert filter of length n is not made here: use envelope(x) or the peak method.', 'envelope')
        m = X.mean(axis=0, keepdims=True)
        A = np.abs(S.hilbert(X - m, axis=0))
        U, L = m + A, m - A
    else:
        raise err('MATLAB:envelope:method', "The method is 'analytic' or 'peak'.", 'envelope')
    if nargout == 0:
        _plot_envelope(X, U, L)
        return None
    return (_back(U, row), _back(L, row)) if nargout > 1 else _back(U, row)


def _plot_envelope(X, U, L):
    t = np.arange(1, X.shape[0] + 1, dtype=float).reshape(-1, 1)
    _b('plot', t, X, t, U, Char.of('--'), t, L, Char.of('--'))
    _b('title', Char.of('Upper and lower envelopes'))


def _b(name, *args):
    return R._builtin(name, *args)


# ---- correlation -----------------------------------------------------------------------------------------------------

def _xcorr(x, y, maxlag, scale):
    n = max(x.size, y.size)
    xp = np.concatenate([x, np.zeros(n - x.size)])
    yp = np.concatenate([y, np.zeros(n - y.size)])
    r = np.correlate(xp, yp, 'full') if np.iscomplexobj(xp) or np.iscomplexobj(yp) else np.correlate(xp, yp, 'full')
    lags = np.arange(-(n - 1), n)
    if scale == 'biased':
        r = r / n
    elif scale == 'unbiased':
        r = r / (n - np.abs(lags))
    elif scale in ('normalized', 'coeff'):
        r = r / math.sqrt(float(np.sum(np.abs(x) ** 2) * np.sum(np.abs(y) ** 2)))
    if maxlag is not None:
        keep = np.abs(lags) <= maxlag
        r = np.concatenate([np.zeros(max(0, maxlag - (n - 1))), r[keep], np.zeros(max(0, maxlag - (n - 1)))])
        lags = np.arange(-maxlag, maxlag + 1)
    return r, lags


def _xcorr_args(args, fn):
    x = darr(args[0], fn)
    rest = list(args[1:])
    y = None
    if rest and not is_str(rest[0]) and numel(rest[0]) > 1 or (rest and not is_str(rest[0]) and len(rest) >= 2 and not is_str(rest[1]) and numel(rest[0]) >= 1 and numel(rest[1]) <= 1 and numel(rest[0]) != 1):
        y = darr(rest.pop(0), fn)
    maxlag = None
    if rest and not is_str(rest[0]):
        if numel(rest[0]):
            maxlag = int(darr(rest[0]).flat[0])
        rest.pop(0)
    scale = opt_str(rest[0]).lower() if rest and is_str(rest[0]) else 'none'
    if scale not in ('none', 'biased', 'unbiased', 'normalized', 'coeff'):
        raise err(f'MATLAB:{fn}:scale', "The scaling is 'none', 'biased', 'unbiased' or 'normalized'.", fn)
    return x, y, maxlag, scale


def _xcorr_main(nargout, args, fn, remove_mean):
    nargchk(args, 1, 4, fn)
    x, y, maxlag, scale = _xcorr_args(args, fn)
    row = x.shape[0] == 1
    if y is None and x.ndim == 2 and x.shape[0] > 1 and x.shape[1] > 1:
        # a matrix: every pair of columns, column (i-1)*P + j being xcorr(x(:, i), x(:, j))
        cols = [x[:, j] - (x[:, j].mean() if remove_mean else 0) for j in range(x.shape[1])]
        rs = []
        for a_ in cols:
            for b_ in cols:
                r, lags = _xcorr(a_, b_, maxlag, scale)
                rs.append(r)
        R_ = np.column_stack(rs)
        return (out(R_), _rowv(lags.astype(float))) if nargout > 1 else out(R_)
    xv = x.reshape(-1)
    yv = xv if y is None else y.reshape(-1)
    if remove_mean:
        xv, yv = xv - xv.mean(), yv - yv.mean()
    if scale == 'unbiased' and x.size != yv.size:
        pass
    r, lags = _xcorr(xv, yv, maxlag, scale)
    r = np.real_if_close(r) if not (np.iscomplexobj(xv) or np.iscomplexobj(yv)) else r
    res = _rowv(r) if row else _col(r)
    return (res, _rowv(lags.astype(float))) if nargout > 1 else res


@bi('xcorr', nout=2)
def xcorr(nargout, *args):
    """[r, lags] = xcorr(x, y, maxlag, scaleopt): cross-correlation, r(m) = sum of x(n+m)*conj(y(n))."""
    return _xcorr_main(nargout, args, 'xcorr', False)


@bi('xcov', nout=2)
def xcov(nargout, *args):
    """[c, lags] = xcov(x, y, maxlag, scaleopt): cross-covariance (xcorr of the signals less their means)."""
    return _xcorr_main(nargout, args, 'xcov', True)


# ---- resampling -----------------------------------------------------------------------------------------------------

@bi('resample', nout=2)
def resample(nargout, *args):
    """y = resample(x, p, q): x at p/q times its sampling rate, by polyphase filtering."""
    nargchk(args, 3, 5, 'resample')
    X, row = _signal(args[0], 'resample')
    p, q = int(darr(args[1]).flat[0]), int(darr(args[2]).flat[0])
    if p < 1 or q < 1:
        raise err('MATLAB:resample:pq', 'p and q are positive whole numbers.', 'resample')
    g = math.gcd(p, q)
    p, q = p // g, q // g
    Y = _S().resample_poly(X, p, q, axis=0, window=('kaiser', 5.0))
    return _back(Y, row)


@bi('decimate')
def decimate(nargout, *args):
    """y = decimate(x, r, n, 'fir'): lowpass filtered and every r-th sample kept (a Chebyshev type I filter of order 8, both ways)."""
    nargchk(args, 2, 4, 'decimate')
    X, row = _signal(args[0], 'decimate')
    r = int(darr(args[1]).flat[0])
    words, rest = _words(args[2:])
    n = int(darr(rest[0]).flat[0]) if rest else None
    ftype = 'fir' if 'fir' in words else 'iir'
    if r < 1:
        raise err('MATLAB:decimate:r', 'r is a positive whole number.', 'decimate')
    need = 3 * ((n or (30 if ftype == 'fir' else 8)) + 1)
    if X.shape[0] <= need:
        raise err('MATLAB:decimate:short', f'The signal must have more than {need} samples for the filter decimate uses.', 'decimate')
    Y = _S().decimate(X, r, n=n, ftype=ftype, axis=0, zero_phase=True)
    return _back(Y, row)


@bi('interp')
def interp(nargout, *args):
    """y = interp(x, r): r times as many samples, by lowpass interpolation; the samples of x are kept."""
    nargchk(args, 2, 4, 'interp')
    X, row = _signal(args[0], 'interp')
    r = int(darr(args[1]).flat[0])
    if r < 1:
        raise err('MATLAB:interp:r', 'r is a positive whole number.', 'interp')
    # the ends extended by odd reflection (repeated for a short signal) as far as the
    # filter reaches, so they are no steps to zero
    m = X.shape[0]
    k = 10 + 1
    P = np.pad(X, ((k, k), (0, 0)), mode='reflect', reflect_type='odd') if m > 1 else np.repeat(X, 2 * k + 1, axis=0)
    Y = _S().resample_poly(P, r, 1, axis=0)[k * r:(k + m) * r]
    Y[::r] = X
    return _back(Y, row)


@bi('downsample')
def downsample(nargout, *args):
    """y = downsample(x, n, phase): every n-th sample, from sample phase+1."""
    nargchk(args, 2, 3, 'downsample')
    X, row = _signal(args[0], 'downsample')
    n = int(darr(args[1]).flat[0])
    ph = int(darr(args[2]).flat[0]) if len(args) > 2 else 0
    if n < 1 or not 0 <= ph < n:
        raise err('MATLAB:downsample:args', 'n is a positive whole number and phase one of 0 to n-1.', 'downsample')
    return _back(X[ph::n], row)


@bi('upsample')
def upsample(nargout, *args):
    """y = upsample(x, n, phase): n-1 zeros put after each sample (the sample at phase+1)."""
    nargchk(args, 2, 3, 'upsample')
    X, row = _signal(args[0], 'upsample')
    n = int(darr(args[1]).flat[0])
    ph = int(darr(args[2]).flat[0]) if len(args) > 2 else 0
    if n < 1 or not 0 <= ph < n:
        raise err('MATLAB:upsample:args', 'n is a positive whole number and phase one of 0 to n-1.', 'upsample')
    Y = np.zeros((X.shape[0] * n, X.shape[1]), dtype=X.dtype)
    Y[ph::n] = X
    return _back(Y, row)


@bi('buffer', nout=3)
def buffer(nargout, *args):
    """y = buffer(x, n, p): x in frames (columns) of n samples, each overlapping the one before by p (or skipping -p)."""
    nargchk(args, 2, 4, 'buffer')
    x = darr(args[0], 'buffer').reshape(-1)
    n = int(darr(args[1]).flat[0])
    p = int(darr(args[2]).flat[0]) if len(args) > 2 else 0
    if p >= n:
        raise err('MATLAB:buffer:overlap', 'The overlap must be less than the frame length.', 'buffer')
    frames = []
    if p >= 0:
        seq = np.concatenate([np.zeros(p), x])
        step = n - p
        k = 0
        while k + p < seq.size:
            frames.append(seq[k:k + n])
            k += step
    else:
        step = n - p
        k = 0
        while k < x.size:
            frames.append(x[k:k + n])
            k += step
    rest = np.zeros(0)
    if nargout > 1 and frames and frames[-1].size < n:
        rest = frames.pop()
    Y = np.zeros((n, len(frames)))
    for j, f in enumerate(frames):
        Y[:f.size, j] = f
    return (out(Y), _col(rest)) if nargout > 1 else out(Y)


# ---- peaks ----------------------------------------------------------------------------------------------------------

@bi('findpeaks', nout=4)
def findpeaks(nargout, *args):
    """[pks, locs, w, p] = findpeaks(y, x, Name, Value): the local maxima, where they are, their widths and prominences."""
    nargchk(args, 1, 30, 'findpeaks')
    opts, rest = _opts(list(args[1:]), ('MinPeakHeight', 'MinPeakProminence', 'MinPeakDistance', 'Threshold', 'NPeaks', 'SortStr',
                                         'MinPeakWidth', 'MaxPeakWidth', 'WidthReference', 'Annotate'), 'findpeaks')
    yv = darr(args[0], 'findpeaks')
    if yv.ndim != 2 or min(yv.shape) > 1:
        raise err('MATLAB:findpeaks:vector', 'findpeaks takes a vector.', 'findpeaks')
    row = yv.shape[0] == 1
    y = yv.reshape(-1).astype(float)
    x = np.arange(1, y.size + 1, dtype=float)
    if rest:
        xv = darr(rest[0], 'findpeaks').reshape(-1)
        if xv.size == 1:
            x = np.arange(y.size, dtype=float) / float(xv[0])
        elif xv.size == y.size:
            x = xv.astype(float)
        else:
            raise err('MATLAB:findpeaks:x', 'x has a value for each sample, or is the sampling rate.', 'findpeaks')
    S = _S()
    num = lambda k, d: float(darr(opts[k]).flat[0]) if k in opts else d  # noqa: E731
    finite = np.where(np.isfinite(y), y, -np.inf)
    pk, props = S.find_peaks(finite, plateau_size=1)
    # a flat peak is where it starts
    locs = props['left_edges'] if pk.size else pk
    keep = np.isfinite(y[locs])
    locs = locs[keep]
    thr = num('Threshold', 0.0)
    if thr > 0 and locs.size:
        left = y[locs] - y[np.maximum(locs - 1, 0)]
        right = y[locs] - y[np.minimum(props['right_edges'][keep] + 1, y.size - 1)]
        locs = locs[(left >= thr) & (right >= thr)]
    locs = locs[y[locs] >= num('MinPeakHeight', -np.inf)] if locs.size else locs
    prom = S.peak_prominences(finite, locs)[0] if locs.size else np.zeros(0)
    mp = num('MinPeakProminence', 0.0)
    if mp > 0:
        locs, prom = locs[prom >= mp], prom[prom >= mp]
    ref = py_str(opts['WidthReference']).lower() if 'WidthReference' in opts else 'halfprom'
    if locs.size:
        if ref == 'halfheight':
            # measured at half the peak's height (its prominence's bases still bound it)
            pd = S.peak_prominences(finite, locs)
            wl = S.peak_widths(finite, locs, rel_height=0.5, prominence_data=(y[locs], pd[1], pd[2]))
        else:
            wl = S.peak_widths(finite, locs, rel_height=0.5)
        # widths in the units of x (interpolated between samples)
        xi = lambda pos: np.interp(pos, np.arange(y.size), x)  # noqa: E731
        width = xi(wl[3]) - xi(wl[2])
    else:
        width = np.zeros(0)
    lo_w, hi_w = num('MinPeakWidth', 0.0), num('MaxPeakWidth', np.inf)
    sel = (width >= lo_w) & (width <= hi_w)
    locs, prom, width = locs[sel], prom[sel], width[sel]
    md = num('MinPeakDistance', 0.0)
    if md > 0 and locs.size > 1:
        # the highest first; each later one kept only when far enough from those kept
        order = np.argsort(-y[locs], kind='stable')
        kept = []
        for i in order:
            if all(abs(x[locs[i]] - x[locs[j]]) >= md for j in kept):
                kept.append(i)
        kept = np.sort(np.array(kept, int))
        locs, prom, width = locs[kept], prom[kept], width[kept]
    srt = py_str(opts['SortStr']).lower() if 'SortStr' in opts else 'none'
    if srt in ('ascend', 'descend'):
        o = np.argsort(y[locs] if srt == 'ascend' else -y[locs], kind='stable')
        locs, prom, width = locs[o], prom[o], width[o]
    if 'NPeaks' in opts:
        k = int(num('NPeaks', locs.size))
        locs, prom, width = locs[:k], prom[:k], width[:k]
    pks, xl = y[locs], x[locs]
    if nargout == 0:
        xx = x.reshape(-1, 1)
        _b('plot', xx, y.reshape(-1, 1), xl.reshape(-1, 1), pks.reshape(-1, 1), Char.of('v'))
        return None
    shape = (lambda v: _rowv(v)) if row else (lambda v: _col(v))
    res = (shape(pks), shape(xl), shape(width), shape(prom))
    return res[:max(nargout, 1)] if nargout > 1 else res[0]


# ---- windows -------------------------------------------------------------------------------------------------------

def _win_n(args, fn):
    nargchk(args, 1, 3, fn)
    n = darr(args[0], fn).reshape(-1)
    if n.size != 1 or n[0] < 0 or n[0] != int(n[0]):
        raise err(f'MATLAB:{fn}:n', 'The window length is a whole number, 0 or more.', fn)
    return int(n[0])


def _sym(args, fn):
    """'symmetric' (the default) or 'periodic' among the arguments."""
    for a in args:
        s = opt_str(a)
        if s is not None:
            s = s.lower()
            if s not in ('symmetric', 'periodic'):
                raise err(f'MATLAB:{fn}:flag', "The window's form is 'symmetric' or 'periodic'.", fn)
            return s == 'symmetric'
    return True


def _window(fn, name, params=(), takes_flag=False):
    def f(nargout, *args):
        n = _win_n(args, fn)
        if n == 0:
            return np.zeros((0, 1))
        if n == 1:
            return 1.0
        extra = [a for a in args[1:] if not is_str(a)]
        p = [float(darr(extra[i]).flat[0]) if i < len(extra) else d for i, d in enumerate(params)]
        sym = _sym(args[1:], fn) if takes_flag else True
        w = name(n, sym, *p) if callable(name) else _S().get_window((name, *p) if p else name, n, fftbins=not sym)
        return _col(w)
    f.__name__ = fn
    return f


def _gausswin(n, sym, alpha):
    k = np.arange(n) - (n - 1) / 2
    return np.exp(-0.5 * (alpha * k / ((n - 1) / 2)) ** 2)


def _hanning(n, sym):
    # the Hann window without its zero end points
    w = _S().windows.hann(n + 2, sym=True)[1:-1] if sym else _S().windows.hann(n + 1, sym=True)[1:]
    return w


for _fn, _name, _params, _flag in (('hamming', 'hamming', (), True), ('hann', 'hann', (), True), ('hanning', _hanning, (), True),
                                   ('blackman', 'blackman', (), True), ('flattopwin', 'flattop', (), True), ('blackmanharris', 'blackmanharris', (), True),
                                   ('nuttallwin', 'nuttall', (), True), ('kaiser', 'kaiser', (0.5,), False), ('bartlett', 'bartlett', (), False),
                                   ('triang', 'triang', (), False), ('rectwin', 'boxcar', (), False), ('gausswin', _gausswin, (2.5,), False),
                                   ('tukeywin', 'tukey', (0.5,), False), ('chebwin', 'chebwin', (100.0,), False), ('barthannwin', 'barthann', (), False),
                                   ('bohmanwin', 'bohman', (), False), ('parzenwin', 'parzen', (), False)):
    bi(_fn)(_window(_fn, _name, _params, _flag))


@bi('window')
def window(nargout, *args):
    """w = window(@fn, n, args): the window fn of length n."""
    nargchk(args, 2, 4, 'window')
    f = args[0]
    name = f.name() if isinstance(f, FH) and hasattr(f, 'name') else (py_str(f) if is_str(f) else None)
    if name not in REG or not name or name == 'window':
        raise err('MATLAB:window:fn', 'window takes a window function, as @hamming.', 'window')
    return R._builtin(name, *args[1:])


# ---- frequency responses ---------------------------------------------------------------------------------------------

def _filter_args(args, fn):
    """(kind, coefficients) from b[, a] or sos or a digital filter, and the arguments after them."""
    if args and isinstance(args[0], DigitalFilter):
        d = args[0]
        return (('sos', d.sos) if d.sos is not None else ('ba', (d.b, np.array([1.0])))), list(args[1:])
    b = darr(args[0], fn)
    if b.ndim == 2 and b.shape[1] == 6 and b.shape[0] > 1:
        return ('sos', b), list(args[1:])
    a = darr(args[1], fn).reshape(-1) if len(args) > 1 and not is_str(args[1]) and numel(args[1]) else np.array([1.0])
    return ('ba', (b.reshape(-1), a)), list(args[2:] if len(args) > 1 else [])


def _plot_response(w, h, fs, whole):
    mag = 20 * np.log10(np.maximum(np.abs(h), 1e-300))
    ph = np.unwrap(np.angle(h)) * 180 / np.pi
    x = (w / np.pi) if fs is None else w
    xl = 'Normalized Frequency (\\times\\pi rad/sample)' if fs is None else 'Frequency (Hz)'
    _b('subplot', 2.0, 1.0, 1.0)
    _b('plot', x.reshape(-1, 1), mag.reshape(-1, 1))
    _b('grid', Char.of('on'))
    _b('ylabel', Char.of('Magnitude (dB)'))
    _b('xlabel', Char.of(xl))
    _b('subplot', 2.0, 1.0, 2.0)
    _b('plot', x.reshape(-1, 1), ph.reshape(-1, 1))
    _b('grid', Char.of('on'))
    _b('ylabel', Char.of('Phase (degrees)'))
    _b('xlabel', Char.of(xl))


@bi('freqz', nout=2)
def freqz(nargout, *args):
    """[h, w] = freqz(b, a, n, 'whole', fs) and freqz(b, a, w): a digital filter's frequency response."""
    nargchk(args, 1, 5, 'freqz')
    (kind, c), rest = _filter_args(args, 'freqz')
    words, rest = _words(rest)
    whole = 'whole' in words
    n, fs, wv = 512, None, None
    if rest and numel(rest[0]):
        v = darr(rest[0]).reshape(-1)
        if v.size == 1:
            n = int(v[0])
        else:
            wv = v
    if len(rest) > 1 and numel(rest[1]):
        fs = float(darr(rest[1]).flat[0])
    S = _S()
    worN = wv if wv is not None else n
    if wv is not None and fs is not None:
        worN = wv * 2 * np.pi / fs
    if kind == 'sos':
        w, h = S.sosfreqz(c, worN=worN, whole=whole)
    else:
        w, h = S.freqz(c[0], c[1], worN=worN, whole=whole)
    if fs is not None:
        w = w * fs / (2 * np.pi)
    if nargout == 0:
        _plot_response(w, h, fs, whole)
        return None
    return (_col(h), _col(w)) if nargout > 1 else _col(h)


@bi('freqs', nout=2)
def freqs(nargout, *args):
    """[h, w] = freqs(b, a, w): an analog filter's frequency response (w in rad/s)."""
    nargchk(args, 2, 3, 'freqs')
    b, a = _coef(args[0], 'freqs'), _coef(args[1], 'freqs')
    worN = darr(args[2]).reshape(-1) if len(args) > 2 and numel(args[2]) > 1 else (int(darr(args[2]).flat[0]) if len(args) > 2 else 200)
    w, h = _S().freqs(b, a, worN=worN)
    if nargout == 0:
        _b('subplot', 2.0, 1.0, 1.0)
        _b('loglog', w.reshape(-1, 1), np.abs(h).reshape(-1, 1))
        _b('ylabel', Char.of('Magnitude'))
        _b('subplot', 2.0, 1.0, 2.0)
        _b('semilogx', w.reshape(-1, 1), (np.unwrap(np.angle(h)) * 180 / np.pi).reshape(-1, 1))
        _b('ylabel', Char.of('Phase (degrees)'))
        _b('xlabel', Char.of('Frequency (rad/s)'))
        return None
    return (_col(h), _col(w)) if nargout > 1 else _col(h)


def _impulse(kind, c, n):
    S = _S()
    x = np.zeros(n)
    x[0] = 1.0
    return S.sosfilt(c, x) if kind == 'sos' else S.lfilter(c[0], c[1], x)


def _impulse_len(kind, c):
    """How many samples of the impulse response to give: an FIR filter's length, else until it has died away."""
    if kind == 'ba' and c[1].size == 1:
        return c[0].size
    h = _impulse(kind, c, 5000)
    big = np.abs(h) > 5e-5 * max(np.max(np.abs(h)), 1e-300)
    last = int(np.nonzero(big)[0][-1]) + 1 if big.any() else 1
    return max(last, 2)


@bi('impz', nout=2)
def impz(nargout, *args):
    """[h, t] = impz(b, a, n, fs): a filter's impulse response."""
    nargchk(args, 1, 4, 'impz')
    (kind, c), rest = _filter_args(args, 'impz')
    n = int(darr(rest[0]).flat[0]) if rest and numel(rest[0]) == 1 else _impulse_len(kind, c)
    fs = float(darr(rest[1]).flat[0]) if len(rest) > 1 else 1.0
    h = _impulse(kind, c, n)
    t = np.arange(n) / fs
    if nargout == 0:
        _b('stem', t.reshape(-1, 1), h.reshape(-1, 1))
        _b('title', Char.of('Impulse Response'))
        return None
    return (_col(h), _col(t)) if nargout > 1 else _col(h)


@bi('stepz', nout=2)
def stepz(nargout, *args):
    """[s, t] = stepz(b, a, n, fs): a filter's step response."""
    nargchk(args, 1, 4, 'stepz')
    (kind, c), rest = _filter_args(args, 'stepz')
    n = int(darr(rest[0]).flat[0]) if rest and numel(rest[0]) == 1 else _impulse_len(kind, c)
    fs = float(darr(rest[1]).flat[0]) if len(rest) > 1 else 1.0
    s = np.cumsum(_impulse(kind, c, n))
    t = np.arange(n) / fs
    if nargout == 0:
        _b('stem', t.reshape(-1, 1), s.reshape(-1, 1))
        _b('title', Char.of('Step Response'))
        return None
    return (_col(s), _col(t)) if nargout > 1 else _col(s)


@bi('grpdelay', nout=2)
def grpdelay(nargout, *args):
    """[gd, w] = grpdelay(b, a, n): a filter's group delay in samples."""
    nargchk(args, 1, 4, 'grpdelay')
    (kind, c), rest = _filter_args(args, 'grpdelay')
    if kind == 'sos':
        c = _S().sos2tf(c)
    n = int(darr(rest[0]).flat[0]) if rest and numel(rest[0]) == 1 else 512
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        w, gd = _S().group_delay((c[0], c[1]), w=n)
    if nargout == 0:
        _b('plot', (w / np.pi).reshape(-1, 1), gd.reshape(-1, 1))
        _b('ylabel', Char.of('Group delay (samples)'))
        _b('xlabel', Char.of('Normalized Frequency (\\times\\pi rad/sample)'))
        return None
    return (_col(gd), _col(w)) if nargout > 1 else _col(gd)


@bi('zplane', nout=2)
def zplane(nargout, *args):
    """zplane(b, a) (rows: coefficients) or zplane(z, p) (columns: zeros and poles): the zeros (o) and poles (x) with the unit circle."""
    nargchk(args, 1, 2, 'zplane')
    if isinstance(args[0], DigitalFilter):
        z, p, _ = _S().sos2zpk(args[0].sos) if args[0].sos is not None else _S().tf2zpk(args[0].b, [1.0])
    else:
        A = darr(args[0], 'zplane')
        Bv = darr(args[1], 'zplane') if len(args) > 1 else np.array([[1.0]])
        if A.shape[1] == 1 and A.shape[0] > 1 or Bv.shape[1] == 1 and Bv.shape[0] > 1:
            z, p = A.reshape(-1), Bv.reshape(-1) if len(args) > 1 else np.zeros(0)
        else:
            z, p, _ = _S().tf2zpk(A.reshape(-1), Bv.reshape(-1))
    t = np.linspace(0, 2 * np.pi, 400)
    _b('plot', np.cos(t).reshape(-1, 1), np.sin(t).reshape(-1, 1), Char.of(':'))
    _b('hold', Char.of('on'))
    if z.size:
        _b('plot', np.real(z).reshape(-1, 1), np.imag(z).reshape(-1, 1), Char.of('o'))
    if p.size:
        _b('plot', np.real(p).reshape(-1, 1), np.imag(p).reshape(-1, 1), Char.of('x'))
    _b('hold', Char.of('off'))
    _b('axis', Char.of('equal'))
    _b('xlabel', Char.of('Real Part'))
    _b('ylabel', Char.of('Imaginary Part'))
    return None


# ---- forms of a filter ----------------------------------------------------------------------------------------------

@bi('tf2zp', nout=3)
def tf2zp(nargout, *args):
    """[z, p, k] = tf2zp(b, a)."""
    nargchk(args, 2, 2, 'tf2zp')
    z, p, k = _S().tf2zpk(_coef(args[0], 'tf2zp'), _coef(args[1], 'tf2zp'))
    return _col(z), _col(p), float(k)


@bi('zp2tf', nout=2)
def zp2tf(nargout, *args):
    """[b, a] = zp2tf(z, p, k)."""
    nargchk(args, 3, 3, 'zp2tf')
    b, a = _S().zpk2tf(_coef(args[0], 'zp2tf'), _coef(args[1], 'zp2tf'), float(darr(args[2]).flat[0]))
    return _rowv(np.real_if_close(b)), _rowv(np.real_if_close(a))


@bi('tf2sos', nout=2)
def tf2sos(nargout, *args):
    """[sos, g] = tf2sos(b, a): second-order sections (and the gain apart when asked for)."""
    nargchk(args, 2, 2, 'tf2sos')
    sos = _S().tf2sos(_coef(args[0], 'tf2sos'), _coef(args[1], 'tf2sos'))
    if nargout > 1:
        g = float(np.prod(sos[:, 0]))
        sos = sos.copy()
        sos[:, :3] = sos[:, :3] / sos[:, [0]]
        return out(sos), g
    return out(sos)


@bi('zp2sos', nout=2)
def zp2sos(nargout, *args):
    """[sos, g] = zp2sos(z, p, k)."""
    nargchk(args, 2, 3, 'zp2sos')
    k = float(darr(args[2]).flat[0]) if len(args) > 2 else 1.0
    sos = _S().zpk2sos(_coef(args[0], 'zp2sos'), _coef(args[1], 'zp2sos'), k)
    if nargout > 1:
        g = float(np.prod(sos[:, 0]))
        sos = sos.copy()
        sos[:, :3] = sos[:, :3] / sos[:, [0]]
        return out(sos), g
    return out(sos)


@bi('sos2tf', nout=2)
def sos2tf(nargout, *args):
    """[b, a] = sos2tf(sos, g)."""
    nargchk(args, 1, 2, 'sos2tf')
    b, a = _S().sos2tf(darr(args[0], 'sos2tf'))
    g = float(np.prod(darr(args[1]))) if len(args) > 1 else 1.0
    return _rowv(b * g), _rowv(a)


@bi('sos2zp', nout=3)
def sos2zp(nargout, *args):
    """[z, p, k] = sos2zp(sos, g)."""
    nargchk(args, 1, 2, 'sos2zp')
    z, p, k = _S().sos2zpk(darr(args[0], 'sos2zp'))
    g = float(np.prod(darr(args[1]))) if len(args) > 1 else 1.0
    return _col(z), _col(p), float(k) * g


# ---- spectra -----------------------------------------------------------------------------------------------------------

def _nfft(n):
    return max(256, 2 ** int(math.ceil(math.log2(max(n, 1)))))


def _spec_args(args, fn, two=False):
    """x (and y), window, noverlap, nfft, fs and the range from a spectral function's arguments."""
    words, rest = _words(args)
    if len(rest) < (2 if two else 1):
        raise err('MATLAB:minrhs', f'{fn} takes a signal' + (' and a second one.' if two else '.'), fn)
    x = darr(rest[0], fn).reshape(-1)
    if x.size < 2:
        raise err(f'MATLAB:{fn}:short', f'{fn} takes a signal of 2 samples or more.', fn)
    k = 1
    y = None
    if two:
        y = darr(rest[1], fn).reshape(-1)
        k = 2
    pos = rest[k:]
    win = pos[0] if len(pos) > 0 and numel(pos[0]) else None
    nov = int(darr(pos[1]).flat[0]) if len(pos) > 1 and numel(pos[1]) else None
    nfft = pos[2] if len(pos) > 2 and numel(pos[2]) else None
    fs = float(darr(pos[3]).flat[0]) if len(pos) > 3 and numel(pos[3]) else None
    side = 'twosided' if 'twosided' in words else 'centered' if 'centered' in words else 'onesided'
    if np.iscomplexobj(x) and side == 'onesided' and 'onesided' not in words:
        side = 'twosided'
    return x, y, win, nov, nfft, fs, side, words


def _welch_setup(n, win, nov, fn='pwelch'):
    if win is None:
        L = max(int(n // 4.5), 1)
        w = _S().get_window('hamming', L, fftbins=False)
    else:
        wv = darr(win).reshape(-1)
        if wv.size == 1:
            L = int(wv[0])
            w = _S().get_window('hamming', L, fftbins=False)
        else:
            w, L = wv, wv.size
    if L > n or L < 1:
        raise err(f'MATLAB:{fn}:window', f'The window ({L} samples) must not be longer than the signal ({n}).', fn)
    if nov is None:
        nov = L // 2
    if not 0 <= nov < L:
        raise err(f'MATLAB:{fn}:overlap', 'The overlap must be at least 0 and less than the window length.', fn)
    return w, L, nov


def _freqs_out(f, fs, side, nfft):
    if fs is None:
        f = f * 2 * np.pi            # rad/sample
    return f


def _spectrum(kind, nargout, args, fn):
    S = _S()
    two = kind in ('cpsd', 'mscohere', 'tfestimate')
    x, y, win, nov, nfft, fs, side, words = _spec_args(args, fn, two)
    fs_ = fs if fs is not None else 2 * np.pi
    if kind == 'periodogram':
        w = _S().get_window('boxcar', x.size) if win is None else darr(win).reshape(-1)
        if w.size != x.size:
            raise err('MATLAB:periodogram:window', 'The window must be as long as the signal.', fn)
        nf = int(darr(nfft).flat[0]) if nfft is not None else _nfft(x.size)
        f, P = S.periodogram(x, fs=fs_, window=w, nfft=nf, detrend=False, return_onesided=side == 'onesided', scaling='density')
    else:
        w, L, nv = _welch_setup(x.size, win, nov, fn)
        nf = int(darr(nfft).flat[0]) if nfft is not None else _nfft(L)
        kw = dict(fs=fs_, window=w, nperseg=L, noverlap=nv, nfft=nf, detrend=False, return_onesided=side == 'onesided')
        if kind == 'pwelch':
            f, P = S.welch(x, scaling='density', **kw)
        elif kind == 'cpsd':
            f, P = S.csd(y, x, scaling='density', **kw)
        elif kind == 'mscohere':
            kw.pop('return_onesided')
            f, P = S.coherence(x, y, **kw)
        else:
            f, Pxy = S.csd(x, y, scaling='density', **kw)
            _, Pxx = S.welch(x, scaling='density', **kw)
            P = Pxy / Pxx
    if side == 'centered':
        f, P = np.fft.fftshift(f), np.fft.fftshift(P)
        f = np.where(f >= fs_ / 2, f - fs_, f) if False else f
    elif side == 'twosided':
        f = np.mod(f, fs_)
    if fs is None:
        f = f.copy()
    if nargout == 0:
        x_ = f / np.pi if fs is None else f
        val = 10 * np.log10(np.maximum(np.abs(P), 1e-300)) if kind not in ('mscohere', 'tfestimate') else (np.abs(P) if kind == 'mscohere' else 20 * np.log10(np.abs(P)))
        _b('plot', x_.reshape(-1, 1), val.reshape(-1, 1))
        _b('grid', Char.of('on'))
        _b('xlabel', Char.of('Normalized Frequency (\\times\\pi rad/sample)' if fs is None else 'Frequency (Hz)'))
        unit = 'dB/(rad/sample)' if fs is None else 'dB/Hz'
        _b('ylabel', Char.of({'periodogram': f'Power/frequency ({unit})', 'pwelch': f'Power/frequency ({unit})',
                              'cpsd': f'Power/frequency ({unit})', 'mscohere': 'Magnitude-Squared Coherence', 'tfestimate': 'Magnitude (dB)'}[kind]))
        _b('title', Char.of({'periodogram': 'Periodogram Power Spectral Density Estimate', 'pwelch': 'Welch Power Spectral Density Estimate',
                             'cpsd': 'Cross Power Spectral Density Estimate', 'mscohere': 'Coherence Estimate',
                             'tfestimate': 'Transfer Function Estimate'}[kind]))
        return None
    return (_col(P), _col(f)) if nargout > 1 else _col(P)


@bi('periodogram', nout=2)
def periodogram(nargout, *args):
    """[pxx, w] = periodogram(x, window, nfft, fs, freqrange): the power spectral density by the periodogram."""
    nargchk(args, 1, 6, 'periodogram')
    a = list(args)
    # periodogram(x, window, nfft, fs): no overlap argument
    a = a[:2] + [EMPTY()] + a[2:] if len(a) > 2 else a
    return _spectrum('periodogram', nargout, a, 'periodogram')


@bi('pwelch', nout=2)
def pwelch(nargout, *args):
    """[pxx, w] = pwelch(x, window, noverlap, nfft, fs): the power spectral density by Welch's method."""
    nargchk(args, 1, 7, 'pwelch')
    return _spectrum('pwelch', nargout, args, 'pwelch')


@bi('cpsd', nout=2)
def cpsd(nargout, *args):
    """[pxy, w] = cpsd(x, y, window, noverlap, nfft, fs): the cross power spectral density by Welch's method."""
    nargchk(args, 2, 8, 'cpsd')
    return _spectrum('cpsd', nargout, args, 'cpsd')


@bi('mscohere', nout=2)
def mscohere(nargout, *args):
    """[cxy, w] = mscohere(x, y, window, noverlap, nfft, fs): the magnitude-squared coherence."""
    nargchk(args, 2, 8, 'mscohere')
    return _spectrum('mscohere', nargout, args, 'mscohere')


@bi('tfestimate', nout=2)
def tfestimate(nargout, *args):
    """[txy, w] = tfestimate(x, y, window, noverlap, nfft, fs): the transfer function from x to y (H1 = Pyx/Pxx)."""
    nargchk(args, 2, 8, 'tfestimate')
    return _spectrum('tfestimate', nargout, args, 'tfestimate')


@bi('spectrogram', nout=4)
def spectrogram(nargout, *args):
    """[s, w, t, ps] = spectrogram(x, window, noverlap, nfft, fs): the short-time Fourier transform."""
    nargchk(args, 1, 7, 'spectrogram')
    S = _S()
    x, _, win, nov, nfft, fs, side, words = _spec_args(args, 'spectrogram')
    w, L, nv = _welch_setup(x.size, win, nov, 'spectrogram')
    nf = int(darr(nfft).flat[0]) if nfft is not None and numel(nfft) == 1 else _nfft(L)
    fs_ = fs if fs is not None else 2 * np.pi
    f, t, Z = S.stft(x, fs=fs_, window=w, nperseg=L, noverlap=nv, nfft=nf, detrend=False, return_onesided=side == 'onesided',
                     boundary=None, padded=False, scaling='spectrum')
    Z = Z * np.sum(w)            # the unscaled transform: the sums of the windowed segments' terms
    _, _, Pd = S.spectrogram(x, fs=fs_, window=w, nperseg=L, noverlap=nv, nfft=nf, detrend=False, return_onesided=side == 'onesided',
                             scaling='density', mode='psd')
    if fs is None:
        t = t * 2 * np.pi / fs_ if False else (L / 2 + np.arange(Z.shape[1]) * (L - nv))
    if nargout == 0:
        tt = t
        img = 10 * np.log10(np.maximum(Pd, 1e-300))
        _b('imagesc', tt.reshape(1, -1), (f / np.pi if fs is None else f).reshape(-1, 1), img)
        _b('axis', Char.of('xy'))
        _b('colorbar')
        _b('xlabel', Char.of('Samples' if fs is None else 'Time (s)'))
        _b('ylabel', Char.of('Normalized Frequency (\\times\\pi rad/sample)' if fs is None else 'Frequency (Hz)'))
        return None
    res = (out(Z), _col(f), _rowv(t), out(Pd))
    return res[:nargout] if nargout > 1 else res[0]


@bi('bandpower')
def bandpower(nargout, *args):
    """p = bandpower(x) (the average power), bandpower(x, fs, freqrange), bandpower(pxx, f, 'psd') and bandpower(pxx, f, freqrange, 'psd')."""
    nargchk(args, 1, 4, 'bandpower')
    words, rest = _words(args)
    X, row = _signal(rest[0], 'bandpower')
    if 'psd' in words:
        f = darr(rest[1]).reshape(-1)
        rng = darr(rest[2]).reshape(-1) if len(rest) > 2 else np.array([f[0], f[-1]])
        P = X
    elif len(rest) == 1:
        return _back(np.mean(np.abs(X) ** 2, axis=0, keepdims=True), False)
    else:
        fs = float(darr(rest[1]).flat[0])
        rng = darr(rest[2]).reshape(-1) if len(rest) > 2 else np.array([0, fs / 2])
        n = X.shape[0]
        w = _S().get_window('hamming', n, fftbins=False)
        f, P = _S().periodogram(X, fs=fs, window=w, nfft=n, detrend=False, axis=0)
    df = np.diff(f)
    width = np.concatenate([df, [df[-1]]]) if df.size else np.ones(1)
    sel = (f >= rng[0]) & (f <= rng[1])
    return _back(np.sum(P[sel] * width[sel][:, None], axis=0, keepdims=True), False)


# ---- waveforms ----------------------------------------------------------------------------------------------------------

@bi('chirp')
def chirp(nargout, *args):
    """y = chirp(t, f0, t1, f1, method, phi): a cosine sweeping from f0 at t = 0 to f1 at t1 ('linear', 'quadratic', 'logarithmic')."""
    nargchk(args, 1, 6, 'chirp')
    t = darr(args[0], 'chirp')
    g = lambda i, d: float(darr(args[i]).flat[0]) if len(args) > i and numel(args[i]) else d  # noqa: E731
    method = py_str(args[4]).lower() if len(args) > 4 and is_str(args[4]) else 'linear'
    if method not in ('linear', 'quadratic', 'logarithmic'):
        raise err('MATLAB:chirp:method', "The method is 'linear', 'quadratic' or 'logarithmic'.", 'chirp')
    return out(_S().chirp(t, g(1, 0.0), g(2, 1.0), g(3, 100.0), method=method, phi=g(5, 0.0)))


@bi('sawtooth')
def sawtooth(nargout, *args):
    """x = sawtooth(t, xmax): a sawtooth of period 2*pi between -1 and 1, its peak at xmax of the period."""
    nargchk(args, 1, 2, 'sawtooth')
    w = float(darr(args[1]).flat[0]) if len(args) > 1 else 1.0
    return out(_S().sawtooth(darr(args[0], 'sawtooth'), w))


@bi('square')
def square(nargout, *args):
    """x = square(t, duty): a square wave of period 2*pi, 1 for duty percent of the period and -1 after."""
    nargchk(args, 1, 2, 'square')
    d = float(darr(args[1]).flat[0]) if len(args) > 1 else 50.0
    return out(_S().square(darr(args[0], 'square'), d / 100))


@bi('rectpuls')
def rectpuls(nargout, *args):
    """y = rectpuls(t, w): 1 for -w/2 <= t < w/2, else 0."""
    nargchk(args, 1, 2, 'rectpuls')
    t = darr(args[0], 'rectpuls')
    w = float(darr(args[1]).flat[0]) if len(args) > 1 else 1.0
    return out(((t >= -w / 2) & (t < w / 2)).astype(float))


@bi('tripuls')
def tripuls(nargout, *args):
    """y = tripuls(t, w, s): a triangle of width w peaking at t = s*w/2."""
    nargchk(args, 1, 3, 'tripuls')
    t = darr(args[0], 'tripuls')
    w = float(darr(args[1]).flat[0]) if len(args) > 1 else 1.0
    s = float(darr(args[2]).flat[0]) if len(args) > 2 else 0.0
    peak = s * w / 2
    y = np.zeros_like(t, dtype=float)
    left = (t > -w / 2) & (t <= peak)
    right = (t > peak) & (t < w / 2)
    y[left] = (t[left] + w / 2) / (peak + w / 2) if peak + w / 2 > 0 else 1.0
    y[right] = (w / 2 - t[right]) / (w / 2 - peak) if w / 2 - peak > 0 else 1.0
    return out(y)


@bi('gauspuls', nout=3)
def gauspuls(nargout, *args):
    """[yi, yq, ye] = gauspuls(t, fc, bw, bwr): a Gaussian-modulated sinusoid (and its quadrature and envelope)."""
    nargchk(args, 1, 4, 'gauspuls')
    t = darr(args[0], 'gauspuls')
    g = lambda i, d: float(darr(args[i]).flat[0]) if len(args) > i and numel(args[i]) else d  # noqa: E731
    yi, yq, ye = _S().gausspulse(t, fc=g(1, 1000.0), bw=g(2, 0.5), bwr=g(3, -6.0), retquad=True, retenv=True)
    return (out(yi), out(yq), out(ye))[:max(nargout, 1)] if nargout > 1 else out(yi)


@bi('diric')
def diric(nargout, *args):
    """y = diric(x, n): the Dirichlet (periodic sinc) function sin(n*x/2)/(n*sin(x/2))."""
    nargchk(args, 2, 2, 'diric')
    x = darr(args[0], 'diric')
    n = int(darr(args[1]).flat[0])
    with np.errstate(all='ignore'):
        y = np.sin(n * x / 2) / (n * np.sin(x / 2))
    k = np.round(x / (2 * np.pi))
    at = np.abs(x - 2 * np.pi * k) < 1e-12
    y = np.where(at, (-1.0) ** (k * (n - 1)), y)
    return out(y)


# ---- decibels and peaks ------------------------------------------------------------------------------------------------

@bi('db2mag')
def db2mag(nargout, *args):
    nargchk(args, 1, 1, 'db2mag')
    return out(10 ** (darr(args[0], 'db2mag') / 20))


@bi('mag2db')
def mag2db(nargout, *args):
    nargchk(args, 1, 1, 'mag2db')
    a = darr(args[0], 'mag2db')
    with np.errstate(all='ignore'):
        return out(np.where(a < 0, np.nan, 20 * np.log10(np.abs(a))))


@bi('pow2db')
def pow2db(nargout, *args):
    nargchk(args, 1, 1, 'pow2db')
    a = darr(args[0], 'pow2db')
    with np.errstate(all='ignore'):
        return out(np.where(a < 0, np.nan, 10 * np.log10(np.abs(a))))


@bi('db2pow')
def db2pow(nargout, *args):
    nargchk(args, 1, 1, 'db2pow')
    return out(10 ** (darr(args[0], 'db2pow') / 10))


def _along(args, fn):
    a = darr(args[0], fn)
    if len(args) > 1:
        dim = int(darr(args[1]).flat[0]) - 1
    else:
        dim = next((i for i, s in enumerate(a.shape) if s != 1), 0)
    return a, dim


@bi('peak2peak')
def peak2peak(nargout, *args):
    """y = peak2peak(x, dim): the largest less the smallest value."""
    nargchk(args, 1, 2, 'peak2peak')
    a, dim = _along(args, 'peak2peak')
    if np.iscomplexobj(a):
        return out(np.max(np.abs(a), axis=dim, keepdims=True) - np.min(np.abs(a), axis=dim, keepdims=True))
    return out(np.max(a, axis=dim, keepdims=True) - np.min(a, axis=dim, keepdims=True))


@bi('peak2rms')
def peak2rms(nargout, *args):
    """y = peak2rms(x, dim): the largest magnitude over the root mean square."""
    nargchk(args, 1, 2, 'peak2rms')
    a, dim = _along(args, 'peak2rms')
    return out(np.max(np.abs(a), axis=dim, keepdims=True) / np.sqrt(np.mean(np.abs(a) ** 2, axis=dim, keepdims=True)))


@bi('rceps', nout=2)
def rceps(nargout, *args):
    """[y, ym] = rceps(x): the real cepstrum, real(ifft(log(abs(fft(x))))) (and the minimum-phase signal)."""
    nargchk(args, 1, 1, 'rceps')
    X, row = _signal(args[0], 'rceps')
    y = np.real(np.fft.ifft(np.log(np.abs(np.fft.fft(X, axis=0))), axis=0))
    if nargout < 2:
        return _back(y, row)
    n = X.shape[0]
    wn = np.zeros((n, 1))
    wn[0] = 1
    wn[1:(n + 1) // 2] = 2
    if n % 2 == 0:
        wn[n // 2] = 1
    ym = np.real(np.fft.ifft(np.exp(np.fft.fft(wn * y, axis=0)), axis=0))
    return _back(y, row), _back(ym, row)


@bi('dct')
def dct(nargout, *args):
    """y = dct(x, n, dim, 'Type', k): the orthonormal discrete cosine transform (type II unless asked)."""
    nargchk(args, 1, 5, 'dct')
    return _dct(args, 'dct', False)


@bi('idct')
def idct(nargout, *args):
    """x = idct(y, n, dim, 'Type', k): the inverse of dct."""
    nargchk(args, 1, 5, 'idct')
    return _dct(args, 'idct', True)


def _dct(args, fn, inverse):
    import scipy.fft as F
    opts, rest = _opts(list(args), ('Type',), fn)
    a = darr(rest[0], fn)
    n = int(darr(rest[1]).flat[0]) if len(rest) > 1 and numel(rest[1]) else None
    dim = int(darr(rest[2]).flat[0]) - 1 if len(rest) > 2 else next((i for i, s in enumerate(a.shape) if s != 1), 0)
    k = int(darr(opts['Type']).flat[0]) if 'Type' in opts else 2
    f = F.idct if inverse else F.dct
    return out(f(a, type=k, n=n, axis=dim, norm='ortho'))


# ---- lowpass, highpass, bandpass, bandstop --------------------------------------------------------------------------------

def _pass_filter(kind, nargout, args):
    """A filtered signal: a Kaiser-window FIR filter with 60 dB in the stopband,
    its transition band 15 % of the way from the passband edge to the
    nearest end (steepness 0.85), applied with its delay taken back."""
    fn = kind
    nargchk(args, 2, 10, fn)
    opts, rest = _opts(list(args[1:]), ('Steepness', 'StopbandAttenuation', 'ImpulseResponse'), fn)
    X, row = _signal(args[0], fn)
    wp = darr(rest[0], fn).reshape(-1)
    fs = float(darr(rest[1]).flat[0]) if len(rest) > 1 else 2.0
    nyq = fs / 2
    steep = float(darr(opts['Steepness']).flat[0]) if 'Steepness' in opts else 0.85
    att = float(darr(opts['StopbandAttenuation']).flat[0]) if 'StopbandAttenuation' in opts else 60.0
    W = wp / nyq
    band = kind in ('bandpass', 'bandstop')
    if band != (W.size == 2) or np.any(W <= 0) or np.any(W >= 1):
        raise err(f'MATLAB:{fn}:wpass', 'The passband frequency is one number between 0 and half the sampling rate (two for a band).', fn)
    if kind == 'lowpass':
        width = (1 - steep) * (1 - W[0])
        cut = W[0] + width / 2
    elif kind == 'highpass':
        width = (1 - steep) * W[0]
        cut = W[0] - width / 2
    else:
        width = (1 - steep) * min(W[0], 1 - W[1], (W[1] - W[0]) / 2)
        cut = np.array([W[0] - width / 2, W[1] + width / 2]) if kind == 'bandpass' else np.array([W[0] + width / 2, W[1] - width / 2])
    S = _S()
    ntaps, beta = S.kaiserord(att, width)
    if ntaps % 2 == 0:
        # an odd number of taps: a delay of a whole number of samples, taken back exactly
        ntaps += 1
    ntaps = min(ntaps, 20001)
    h = S.firwin(ntaps, cut, window=('kaiser', beta), pass_zero=kind in ('lowpass', 'bandstop'))
    d = (ntaps - 1) // 2
    P = np.concatenate([X, np.zeros((d, X.shape[1]))])
    Y = S.lfilter(h, [1.0], P, axis=0)[d:]
    if nargout == 0:
        t = (np.arange(X.shape[0]) / (fs if len(rest) > 1 else 1.0)).reshape(-1, 1)
        _b('plot', t, X[:, :1], t, Y[:, :1])
        _b('legend', Char.of('Original'), Char.of('Filtered'))
        return None
    return (_back(Y, row), DigitalFilter(b=h, fs=fs, kind=kind + 'fir')) if nargout > 1 else _back(Y, row)


for _k in ('lowpass', 'highpass', 'bandpass', 'bandstop'):
    def _make(k):
        def f(nargout, *args):
            return _pass_filter(k, nargout, args)
        f.__name__ = k
        return f
    bi(_k, nout=2)(_make(_k))


# ---- designfilt and digital filters ------------------------------------------------------------------------------------

class DigitalFilter(Obj):
    """A digital filter (designfilt): FIR coefficients b, or IIR second-order sections."""
    __slots__ = ('b', 'sos', 'fs', 'kind', 'order')
    cls = 'digitalFilter'
    is_handle = False

    def __init__(self, b=None, sos=None, fs=None, kind='', order=None):
        self.b = None if b is None else np.asarray(b, float).reshape(-1)
        self.sos = None if sos is None else np.asarray(sos, float)
        self.fs = fs
        self.kind = kind
        self.order = order if order is not None else (self.b.size - 1 if self.b is not None else 2 * self.sos.shape[0])

    def getprop(self, name):
        n = name.lower()
        if n == 'coefficients':
            return out(self.b.reshape(1, -1)) if self.b is not None else out(self.sos)
        if n == 'samplerate':
            return float(self.fs) if self.fs is not None else 2.0
        if n == 'impulseresponse':
            return Char.of('fir' if self.b is not None else 'iir')
        if n == 'frequencyresponse':
            return Char.of(self.kind.replace('fir', '').replace('iir', ''))
        if n == 'filterorder':
            return float(self.order)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'digitalFilter'.")

    def propnames(self):
        return ['FrequencyResponse', 'ImpulseResponse', 'SampleRate', 'FilterOrder', 'Coefficients']

    def display_lines(self):
        resp = self.kind.replace('fir', '').replace('iir', '')
        return ['  digitalFilter with properties:', '', f"    FrequencyResponse: '{resp}'",
                f"      ImpulseResponse: '{'fir' if self.b is not None else 'iir'}'", f'          FilterOrder: {self.order}',
                f'           SampleRate: {self.fs if self.fs is not None else 2:g}' + ('' if self.fs is not None else ' (normalized frequency)'),
                '         Coefficients: ' + (f'[1x{self.b.size} double]' if self.b is not None else f'[{self.sos.shape[0]}x6 double]')]


_DF_NAMES = ('FilterOrder', 'CutoffFrequency', 'CutoffFrequency1', 'CutoffFrequency2', 'HalfPowerFrequency', 'HalfPowerFrequency1',
             'HalfPowerFrequency2', 'PassbandFrequency', 'StopbandFrequency', 'PassbandFrequency1', 'PassbandFrequency2',
             'StopbandFrequency1', 'StopbandFrequency2', 'PassbandRipple', 'StopbandAttenuation', 'StopbandAttenuation1',
             'StopbandAttenuation2', 'DesignMethod', 'Window', 'SampleRate', 'ScalePassband')


@bi('designfilt')
def designfilt(nargout, *args):
    """d = designfilt(resp, Name, Value): a lowpass, highpass, bandpass or bandstop FIR or IIR filter."""
    nargchk(args, 1, 40, 'designfilt')
    resp = py_str(args[0]).lower() if is_str(args[0]) else ''
    kinds = {f'{k}{t}': (k, t) for k in ('lowpass', 'highpass', 'bandpass', 'bandstop') for t in ('fir', 'iir')}
    if resp not in kinds:
        raise err('MATLAB:designfilt:response', "The response is one of 'lowpassfir', 'lowpassiir', 'highpassfir', 'highpassiir', 'bandpassfir', 'bandpassiir', 'bandstopfir', 'bandstopiir'.", 'designfilt')
    k, t = kinds[resp]
    opts, rest = _opts(list(args[1:]), _DF_NAMES, 'designfilt')
    if rest:
        raise err('MATLAB:designfilt:option', f"The options must be among: {', '.join(_DF_NAMES)}.", 'designfilt')
    g = lambda name: float(darr(opts[name]).flat[0]) if name in opts else None  # noqa: E731
    fs = g('SampleRate')
    nyq = fs / 2 if fs is not None else 1.0
    band = k in ('bandpass', 'bandstop')
    S = _S()
    method = py_str(opts['DesignMethod']).lower() if 'DesignMethod' in opts else None
    order = g('FilterOrder')
    if t == 'fir':
        if order is not None:
            fc = [g('CutoffFrequency1'), g('CutoffFrequency2')] if band else [g('CutoffFrequency')]
            if any(v is None for v in fc):
                raise err('MATLAB:designfilt:spec', 'With FilterOrder, a FIR filter needs CutoffFrequency (or CutoffFrequency1 and 2).', 'designfilt')
            W = np.array(fc) / nyq
            n = int(order)
            if k in ('highpass', 'bandstop') and n % 2:
                raise err('MATLAB:designfilt:order', 'A highpass or bandstop FIR filter has an even order.', 'designfilt')
            win = darr(opts['Window']).reshape(-1) if 'Window' in opts and not is_str(opts['Window']) else \
                S.get_window(py_str(opts['Window']).lower() if 'Window' in opts else 'hamming', n + 1, fftbins=False)
            h = S.firwin(n + 1, W if band else W[0], window='boxcar', pass_zero=k in ('lowpass', 'bandstop'), scale=False) * win
            edges = np.concatenate([[0.0], W, [1.0]])
            bands = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
            h = _fir_scale(h, bands[0::2] if k in ('lowpass', 'bandstop') else bands[1::2])
            return DigitalFilter(b=h, fs=fs, kind=resp)
        fp, fst = g('PassbandFrequency'), g('StopbandFrequency')
        if band:
            fp1, fp2, fs1, fs2 = g('PassbandFrequency1'), g('PassbandFrequency2'), g('StopbandFrequency1'), g('StopbandFrequency2')
            if None in (fp1, fp2, fs1, fs2):
                raise err('MATLAB:designfilt:spec', 'A band FIR filter needs FilterOrder and CutoffFrequency1/2, or the passband and stopband frequencies 1 and 2.', 'designfilt')
            width = min(abs(fp1 - fs1), abs(fs2 - fp2)) / nyq
            cut = np.array([(fp1 + fs1) / 2, (fp2 + fs2) / 2]) / nyq
        else:
            if fp is None or fst is None:
                raise err('MATLAB:designfilt:spec', 'A FIR filter needs FilterOrder and CutoffFrequency, or PassbandFrequency and StopbandFrequency.', 'designfilt')
            width = abs(fst - fp) / nyq
            cut = (fp + fst) / 2 / nyq
        att = g('StopbandAttenuation') or 60.0
        ntaps, beta = S.kaiserord(att, width)
        if k in ('highpass', 'bandstop') and ntaps % 2 == 0:
            ntaps += 1
        h = S.firwin(ntaps, cut, window=('kaiser', beta), pass_zero=k in ('lowpass', 'bandstop'))
        return DigitalFilter(b=h, fs=fs, kind=resp)
    # IIR
    ftype = method if method in ('butter', 'cheby1', 'cheby2', 'ellip') else 'butter'
    btype = k
    if order is not None:
        hp = [g('HalfPowerFrequency1'), g('HalfPowerFrequency2')] if band else [g('HalfPowerFrequency')]
        if any(v is None for v in hp):
            # Chebyshev and elliptic designs are given their passband (or stopband) edge
            hp = [g('PassbandFrequency1'), g('PassbandFrequency2')] if band else [g('PassbandFrequency') or g('StopbandFrequency')]
        if any(v is None for v in hp):
            raise err('MATLAB:designfilt:spec', 'With FilterOrder, an IIR filter needs HalfPowerFrequency (or HalfPowerFrequency1 and 2).', 'designfilt')
        W = np.array(hp) / nyq
        n = int(order) // (2 if band else 1)
        rp = g('PassbandRipple') or 1.0
        rs = g('StopbandAttenuation') or 60.0
        sos = S.iirfilter(n, W if band else W[0], rp=rp, rs=rs, btype=btype, ftype=ftype, output='sos')
        return DigitalFilter(sos=sos, fs=fs, kind=resp, order=int(order))
    if band:
        wp = np.array([g('PassbandFrequency1'), g('PassbandFrequency2')])
        ws = np.array([g('StopbandFrequency1'), g('StopbandFrequency2')])
    else:
        wp, ws = g('PassbandFrequency'), g('StopbandFrequency')
    if wp is None or ws is None or (band and (None in list(wp) or None in list(ws))):
        raise err('MATLAB:designfilt:spec', 'An IIR filter needs FilterOrder and HalfPowerFrequency, or PassbandFrequency and StopbandFrequency.', 'designfilt')
    wp, ws = np.asarray(wp, float) / nyq, np.asarray(ws, float) / nyq
    rp = g('PassbandRipple') or 1.0
    rs = g('StopbandAttenuation') or 60.0
    sos = S.iirdesign(wp, ws, rp, rs, ftype=ftype, output='sos')
    return DigitalFilter(sos=sos, fs=fs, kind=resp)


# filter(d, x) with a digital filter
def _wrap_filter():
    info = REG['filter']
    orig = info.fn

    def f(nargout, *args):
        if args and isinstance(args[0], DigitalFilter):
            d = args[0]
            X, row = _signal(args[1], 'filter')
            Y = _S().sosfilt(d.sos, X, axis=0) if d.sos is not None else _S().lfilter(d.b, [1.0], X, axis=0)
            return _back(Y, row)
        return orig(nargout, *args)
    info.fn = f


@bi('filtord')
def filtord(nargout, *args):
    """n = filtord(b, a) or filtord(d): a filter's order."""
    nargchk(args, 1, 2, 'filtord')
    if isinstance(args[0], DigitalFilter):
        return float(args[0].order)
    b = np.trim_zeros(_coef(args[0], 'filtord'), 'b')
    a = np.trim_zeros(_coef(args[1], 'filtord'), 'b') if len(args) > 1 else np.array([1.0])
    return float(max(b.size, a.size) - 1)


_wrap_filter()
