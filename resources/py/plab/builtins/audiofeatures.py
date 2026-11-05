"""Audio features: hz2mel and mel2hz, melSpectrogram, mfcc (with deltas),
pitch (normalized correlation, cepstrum or log-harmonic summation), the
spectral descriptors spectralCentroid, spectralSpread,
spectralRolloffPoint, spectralFlatness and spectralEntropy, and
zerocrossrate.

The signal is cut into full windows (the last that do not fit are left
out); each window's spectrum comes from numpy.fft.rfft. A feature's
location is the last sample of its window. Columns are channels.
"""
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, darr, out, opt_str, is_str, sval, num
from ..values import MError, Char, Cell, Struct, EMPTY, numel, py_str
from .. import runtime as R


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy or SciPy refuses told as the function's own error."""
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError) as e:
                raise err(f'audio:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _pairs(args, fn, names):
    pos, opts = [], {}
    k = 0
    args = list(args)
    while k < len(args):
        o = opt_str(args[k])
        if o is not None and o.lower() in names and k + 1 < len(args):
            opts[o.lower()] = args[k + 1]
            k += 2
            continue
        if opts:
            raise err(f'audio:{fn}:InvalidOption', f"'{o if o is not None else '?'}' is not an option of {fn}.", fn)
        pos.append(args[k])
        k += 1
    return pos, opts


def hz_to_mel(f):
    return 2595.0 * np.log10(1 + np.asarray(f, float) / 700.0)


def mel_to_hz(m):
    return 700.0 * (10 ** (np.asarray(m, float) / 2595.0) - 1)


@bi('hz2mel')
def hz2mel(nargout, *args):
    """mel = hz2mel(hz): frequencies on the mel scale, 2595*log10(1 + hz/700)."""
    nargchk(args, 1, 1, 'hz2mel')
    return out(hz_to_mel(darr(args[0])))


@bi('mel2hz')
def mel2hz(nargout, *args):
    """hz = mel2hz(mel): mel back to hertz."""
    nargchk(args, 1, 1, 'mel2hz')
    return out(mel_to_hz(darr(args[0])))


def _audio(v, fn):
    x = np.asarray(darr(v, fn), float)
    if x.ndim == 2 and x.shape[0] == 1:
        x = x.T
    if x.ndim != 2:
        raise err(f'audio:{fn}:InvalidAudio', 'The audio is a column (a channel each column).', fn)
    return x


def _periodic(kind, n):
    k = np.arange(n)
    if kind == 'hamming':
        return 0.54 - 0.46 * np.cos(2 * np.pi * k / n)
    return 0.5 - 0.5 * np.cos(2 * np.pi * k / n)


def _window_opts(opts, fs, fn, kind='hamming', win_s=0.03, overlap_s=0.02):
    if 'window' in opts:
        w = np.asarray(darr(opts['window']), float).reshape(-1)
    else:
        w = _periodic(kind, int(round(win_s * fs)))
    ov = int(num(opts['overlaplength'])) if 'overlaplength' in opts else int(round(overlap_s * fs)) if 'window' not in opts else int(round(w.size * overlap_s / win_s))
    if not 0 <= ov < w.size:
        raise err(f'audio:{fn}:InvalidOverlap', 'OverlapLength is from 0 to below the window length.', fn)
    nfft = int(num(opts['fftlength'])) if 'fftlength' in opts else w.size
    if nfft < w.size:
        raise err(f'audio:{fn}:InvalidFFTLength', 'FFTLength is at least the window length.', fn)
    return w, ov, nfft


def _frames(x, wlen, ov):
    """Frame starts (full windows only) and each frame's last sample (1-based)."""
    hop = wlen - ov
    n = x.shape[0]
    if n < wlen:
        return np.zeros(0, int), np.zeros(0)
    starts = np.arange(0, n - wlen + 1, hop)
    return starts, (starts + wlen).astype(float)


def _spectra(x, w, ov, nfft, power=True):
    """The one-sided spectra (bins x frames x channels) and the frames' locations."""
    starts, loc = _frames(x, w.size, ov)
    idx = starts[:, None] + np.arange(w.size)[None, :]
    F = x[idx] * w[None, :, None]                          # frames x wlen x channels
    S = np.abs(np.fft.rfft(F, n=nfft, axis=1)) ** (2 if power else 1)
    return np.transpose(S, (1, 0, 2)), loc


def mel_bank(fs, nfft, nbands, frange, norm):
    """Triangular filters equally spaced on the mel scale over frange (nbands x bins)."""
    lo, hi = frange
    edges = mel_to_hz(np.linspace(hz_to_mel(lo), hz_to_mel(hi), nbands + 2))
    f = np.arange(nfft // 2 + 1) * fs / nfft
    B = np.zeros((nbands, f.size))
    for b in range(nbands):
        a, c, d = edges[b], edges[b + 1], edges[b + 2]
        up = (f - a) / (c - a)
        down = (d - f) / (d - c)
        B[b] = np.maximum(0, np.minimum(up, down))
        if norm == 'bandwidth':
            B[b] *= 2 / (d - a)
        elif norm == 'area':
            s = B[b].sum()
            if s > 0:
                B[b] /= s
    return B, edges[1:-1]


def _range(opts, fs, fn):
    if 'frequencyrange' in opts:
        r = np.asarray(darr(opts['frequencyrange']), float).reshape(-1)
        if r.size != 2 or not 0 <= r[0] < r[1] <= fs / 2:
            raise err(f'audio:{fn}:InvalidRange', 'FrequencyRange is [low high] within 0 and fs/2.', fn)
        return float(r[0]), float(r[1])
    return 0.0, fs / 2


@bi('melSpectrogram', nout=3)
def melSpectrogram(nargout, *args):
    """[S, F, T] = melSpectrogram(audioIn, fs, 'Window', w, 'OverlapLength',
    n, 'FFTLength', nfft, 'NumBands', 32, 'FrequencyRange', [lo hi],
    'SpectrumType', 'power', 'FilterBankNormalization', 'bandwidth',
    'WindowNormalization', true): the mel spectrogram, a row for each band
    (F its centre), a column for each window (T the time of its last
    sample); without outputs, drawn in dB."""
    nargchk(args, 2, 20, 'melSpectrogram')
    pos, opts = _pairs(args, 'melSpectrogram', ('window', 'overlaplength', 'fftlength', 'numbands', 'frequencyrange', 'spectrumtype',
                                                'filterbanknormalization', 'windownormalization', 'applylog'))
    x = _audio(pos[0], 'melSpectrogram')
    fs = float(num(pos[1]))
    w, ov, nfft = _window_opts(opts, fs, 'melSpectrogram', 'hann')
    nb = int(num(opts['numbands'])) if 'numbands' in opts else 32
    stype = (opt_str(opts['spectrumtype']) or 'power').lower() if 'spectrumtype' in opts else 'power'
    if stype not in ('power', 'magnitude'):
        raise err('audio:melSpectrogram:InvalidSpectrumType', "SpectrumType is 'power' or 'magnitude'.", 'melSpectrogram')
    norm = (opt_str(opts['filterbanknormalization']) or 'bandwidth').lower() if 'filterbanknormalization' in opts else 'bandwidth'
    wn = bool(num(opts['windownormalization'])) if 'windownormalization' in opts else True
    ww = w / w.sum() if wn else w
    S, loc = _spectra(x, ww, ov, nfft, stype == 'power')
    B, centres = mel_bank(fs, nfft, nb, _range(opts, fs, 'melSpectrogram'), norm)
    M = np.einsum('bk,kfc->bfc', B, S)
    if 'applylog' in opts and bool(num(opts['applylog'])):
        M = np.log10(np.maximum(M, np.finfo(float).tiny))
    M = M[:, :, 0] if M.shape[2] == 1 else M
    T = loc / fs
    if nargout == 0:
        b = lambda name, *a: R._builtin(name, *a)
        D = 10 * np.log10(np.maximum(M if M.ndim == 2 else M[:, :, 0], 1e-300))
        # the bands are even in mel, not in hertz: rows on a mel axis, ticks labelled in kHz where those frequencies are
        mel = hz_to_mel(centres)
        b('imagesc', out(T.reshape(1, -1)), out(mel.reshape(-1, 1)), out(D))
        b('axis', Char.of('xy'))
        lo, hi = mel[0] - (mel[1] - mel[0]) / 2 if mel.size > 1 else mel[0], mel[-1]
        ticks = [f for f in 1000 * 2.0 ** np.arange(-2, 6) if lo <= hz_to_mel(f) <= hi]
        b('yticks', out(hz_to_mel(np.array(ticks)).reshape(1, -1)))
        b('yticklabels', Cell.of_list([Char.of(f'{f / 1000:g}') for f in ticks], (1, len(ticks))))
        b('colorbar')
        b('title', Char.of('Mel Spectrogram'))
        b('xlabel', Char.of('Time (s)'))
        b('ylabel', Char.of('Frequency (kHz)'))
        return None
    vals = (out(M), out(centres.reshape(-1, 1)), out(T.reshape(-1, 1)))
    return vals[:nargout] if nargout > 1 else vals[0]


def _deltas(C, M):
    """The regression slope over +-M frames, the ends repeated."""
    if C.shape[0] == 0:
        return C.copy()
    P = np.concatenate([np.repeat(C[:1], M, axis=0), C, np.repeat(C[-1:], M, axis=0)])
    den = 2 * sum(m * m for m in range(1, M + 1))
    n = C.shape[0]
    return sum(m * (P[M + m:M + m + n] - P[M - m:M - m + n]) for m in range(1, M + 1)) / den


@bi('mfcc', nout=4)
def mfcc(nargout, *args):
    """[coeffs, delta, deltaDelta, loc] = mfcc(audioIn, fs, 'NumCoeffs', 13,
    'Window', w, 'OverlapLength', n, 'FFTLength', nfft, 'NumBands', 40,
    'FrequencyRange', [lo hi], 'LogEnergy', 'append', 'DeltaWindowLength',
    9): mel-frequency cepstral coefficients of each window (a row each):
    the DCT of the log mel energies; LogEnergy 'append' puts the window's
    log energy first, 'replace' in place of the first coefficient,
    'ignore' leaves it out."""
    nargchk(args, 2, 22, 'mfcc')
    pos, opts = _pairs(args, 'mfcc', ('numcoeffs', 'window', 'overlaplength', 'fftlength', 'numbands', 'frequencyrange', 'logenergy',
                                      'deltawindowlength', 'rectification'))
    x = _audio(pos[0], 'mfcc')
    fs = float(num(pos[1]))
    w, ov, nfft = _window_opts(opts, fs, 'mfcc', 'hamming')
    nc = int(num(opts['numcoeffs'])) if 'numcoeffs' in opts else 13
    nb = int(num(opts['numbands'])) if 'numbands' in opts else 40
    if not 1 <= nc <= nb:
        raise err('audio:mfcc:InvalidNumCoeffs', 'NumCoeffs is from 1 to the number of bands.', 'mfcc')
    le = (opt_str(opts['logenergy']) or 'append').lower() if 'logenergy' in opts else 'append'
    if le not in ('append', 'replace', 'ignore'):
        raise err('audio:mfcc:InvalidLogEnergy', "LogEnergy is 'append', 'replace' or 'ignore'.", 'mfcc')
    dw = int(num(opts['deltawindowlength'])) if 'deltawindowlength' in opts else 9
    if dw < 3 or dw % 2 == 0:
        raise err('audio:mfcc:InvalidDeltaWindow', 'DeltaWindowLength is odd, at least 3.', 'mfcc')
    S, loc = _spectra(x, w, ov, nfft, True)
    B, _ = mel_bank(fs, nfft, nb, _range(opts, fs, 'mfcc'), 'bandwidth')
    E = np.einsum('bk,kfc->bfc', B, S)                     # bands x frames x channels
    from scipy.fft import dct
    L = np.log(np.maximum(E, np.finfo(float).tiny))
    Cc = dct(L, type=2, norm='ortho', axis=0)[:nc]          # coeffs x frames x channels
    starts, _ = _frames(x, w.size, ov)
    energy = np.array([[np.sum(x[s:s + w.size, c] ** 2) for c in range(x.shape[1])] for s in starts]) if starts.size else np.zeros((0, x.shape[1]))
    loge = np.log(np.maximum(energy, np.finfo(float).tiny))
    C = np.transpose(Cc, (1, 0, 2))                         # frames x coeffs x channels
    if le == 'append':
        C = np.concatenate([loge[:, None, :], C], axis=1)
    elif le == 'replace':
        C[:, 0, :] = loge
    D = np.stack([_deltas(C[:, :, c], dw // 2) for c in range(C.shape[2])], axis=2)
    DD = np.stack([_deltas(D[:, :, c], dw // 2) for c in range(D.shape[2])], axis=2)
    sq = lambda A: A[:, :, 0] if A.shape[2] == 1 else A
    vals = (out(sq(C)), out(sq(D)), out(sq(DD)), out(loc.reshape(-1, 1)))
    return vals[:nargout] if nargout > 1 else vals[0]


def _ncf_pitch(frame, fs, lo, hi):
    n = frame.size
    lmin, lmax = int(math.floor(fs / hi)), int(math.ceil(fs / lo))
    lmax = min(lmax, n - 2)
    if lmin >= lmax:
        return np.nan
    x = frame - frame.mean()
    best, bl = -np.inf, None
    r = np.empty(lmax + 2)
    for L in range(max(lmin - 1, 1), lmax + 2):
        a, b = x[:n - L], x[L:]
        den = math.sqrt((a @ a) * (b @ b))
        r[L] = (a @ b) / den if den > 0 else 0.0
    seg = r[lmin:lmax + 1]
    if seg.size == 0:
        return np.nan
    top = float(seg.max())
    # the shortest lag whose peak comes near the best: a multiple of the period correlates as well
    bl = None
    for L in range(lmin, lmax + 1):
        if r[L] >= 0.9 * top and r[L] >= r[L - 1] and (L + 1 > lmax + 1 or r[L] >= r[L + 1]):
            bl = L
            break
    if bl is None:
        bl = lmin + int(np.argmax(seg))
    # a parabola through the peak and its neighbours
    y0, y1, y2 = r[bl - 1], r[bl], r[bl + 1] if bl + 1 <= lmax + 1 else r[bl]
    den = y0 - 2 * y1 + y2
    shift = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    return fs / (bl + max(-0.5, min(0.5, shift)))


def _cep_pitch(frame, fs, lo, hi):
    n = frame.size
    nfft = 1 << int(math.ceil(math.log2(max(2 * n, 2))))
    X = np.abs(np.fft.fft(frame * np.hamming(n), nfft))
    c = np.real(np.fft.ifft(np.log(np.maximum(X, 1e-12))))
    qmin, qmax = int(math.floor(fs / hi)), min(int(math.ceil(fs / lo)), nfft // 2 - 1)
    if qmin >= qmax:
        return np.nan
    q = qmin + int(np.argmax(c[qmin:qmax + 1]))
    # the cepstral peak lands within a sample or two of the period: the normalized correlation refines it there
    x = frame - frame.mean()
    lags = [L for L in range(q - 2, q + 3) if 1 <= L < n - 1]
    r = {}
    for L in range(lags[0] - 1, lags[-1] + 2):
        a, b = x[:n - L], x[L:]
        den = math.sqrt((a @ a) * (b @ b))
        r[L] = (a @ b) / den if den > 0 else 0.0
    bl = max(lags, key=lambda L: r[L])
    y0, y1, y2 = r[bl - 1], r[bl], r[bl + 1]
    den = y0 - 2 * y1 + y2
    shift = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    return fs / (bl + max(-0.5, min(0.5, shift)))


def _lhs_pitch(frame, fs, lo, hi, nh=5):
    n = frame.size
    nfft = 1 << int(math.ceil(math.log2(max(4 * n, 2))))
    X = np.abs(np.fft.rfft(frame * np.hanning(n), nfft))
    # log magnitudes held at most 5 nats below the peak, so a missing harmonic costs no more than leakage near a strong one
    logX = np.log(np.maximum(X, X.max() * math.exp(-5) if X.max() > 0 else 1e-300))
    df = fs / nfft
    cands = np.arange(lo, hi + df / 4, df / 4)
    score = np.zeros(cands.size)
    for k in range(1, nh + 1):
        idx = np.rint(cands * k / df).astype(int)
        ok = idx < logX.size
        score[ok] += logX[idx[ok]]
        score[~ok] += logX.min()
    return float(cands[int(np.argmax(score))])


@bi('pitch', nout=2)
def pitch(nargout, *args):
    """[f0, loc] = pitch(audioIn, fs, 'Method', m, 'Range', [50 400],
    'WindowLength', n, 'OverlapLength', k, 'MedianFilterLength', 1): the
    fundamental frequency of each window: 'NCF' (normalized correlation,
    the default), 'CEP' (the cepstrum's peak) or 'LHS' (log-harmonic
    summation); 52 ms windows every 10 ms unless given."""
    nargchk(args, 2, 12, 'pitch')
    pos, opts = _pairs(args, 'pitch', ('method', 'range', 'windowlength', 'overlaplength', 'medianfilterlength'))
    x = _audio(pos[0], 'pitch')
    fs = float(num(pos[1]))
    method = (opt_str(opts['method']) or 'NCF').upper() if 'method' in opts else 'NCF'
    if method not in ('NCF', 'CEP', 'LHS'):
        raise err('audio:pitch:InvalidMethod', "Method is 'NCF', 'CEP' or 'LHS' here.", 'pitch')
    rng_ = np.asarray(darr(opts['range']), float).reshape(-1) if 'range' in opts else np.array([50.0, 400.0])
    if rng_.size != 2 or not 0 < rng_[0] < rng_[1] < fs / 2:
        raise err('audio:pitch:InvalidRange', 'Range is [low high] in hertz, within fs/2.', 'pitch')
    wl = int(num(opts['windowlength'])) if 'windowlength' in opts else int(round(0.052 * fs))
    ov = int(num(opts['overlaplength'])) if 'overlaplength' in opts else int(round(0.042 * fs))
    if not 0 <= ov < wl:
        raise err('audio:pitch:InvalidOverlap', 'OverlapLength is from 0 to below the window length.', 'pitch')
    mf = int(num(opts['medianfilterlength'])) if 'medianfilterlength' in opts else 1
    starts, loc = _frames(x, wl, ov)
    f = {'NCF': _ncf_pitch, 'CEP': _cep_pitch, 'LHS': _lhs_pitch}[method]
    F0 = np.array([[f(x[s:s + wl, c], fs, rng_[0], rng_[1]) for c in range(x.shape[1])] for s in starts]).reshape(starts.size, x.shape[1])
    if mf > 1 and F0.shape[0]:
        from scipy.signal import medfilt
        F0 = np.column_stack([medfilt(F0[:, c], mf if mf % 2 else mf + 1) for c in range(F0.shape[1])])
    return (out(F0), out(loc.reshape(-1, 1))) if nargout > 1 else out(F0)


# ---- spectral descriptors ---------------------------------------------------------------------------------------------------------

def _spec_frames(args, fn, extra=()):
    pos, opts = _pairs(args, fn, ('window', 'overlaplength', 'fftlength', 'frequencyrange', 'spectrumtype') + extra)
    x = _audio(pos[0], fn)
    fs = float(num(pos[1]))
    w, ov, nfft = _window_opts(opts, fs, fn, 'hamming')
    stype = (opt_str(opts['spectrumtype']) or 'power').lower() if 'spectrumtype' in opts else 'power'
    S, loc = _spectra(x, w, ov, nfft, stype == 'power')
    f = np.arange(nfft // 2 + 1) * fs / nfft
    lo, hi = _range(opts, fs, fn)
    keep = (f >= lo) & (f <= hi)
    return S[keep], f[keep], loc, opts


def _per_frame(v):
    return out(v[:, 0].reshape(-1, 1) if v.shape[1] == 1 else v)


@bi('spectralCentroid', nout=2)
def spectralCentroid(nargout, *args):
    """centroid = spectralCentroid(audioIn, fs, 'Window', w, 'OverlapLength', n, 'FrequencyRange', [lo hi]): each window's spectral centre of mass (Hz)."""
    S, f, loc, _ = _spec_frames(args, 'spectralCentroid')
    with np.errstate(invalid='ignore', divide='ignore'):
        c = np.einsum('k,kfc->fc', f, S) / S.sum(axis=0)
    return (_per_frame(c), out(loc.reshape(-1, 1))) if nargout > 1 else _per_frame(c)


@bi('spectralSpread', nout=2)
def spectralSpread(nargout, *args):
    """spread = spectralSpread(audioIn, fs, ...): each window's spectral standard deviation about its centroid (Hz)."""
    S, f, loc, _ = _spec_frames(args, 'spectralSpread')
    with np.errstate(invalid='ignore', divide='ignore'):
        tot = S.sum(axis=0)
        c = np.einsum('k,kfc->fc', f, S) / tot
        v = np.einsum('kfc,kfc->fc', (f[:, None, None] - c[None]) ** 2, S) / tot
    return (_per_frame(np.sqrt(v)), out(loc.reshape(-1, 1))) if nargout > 1 else _per_frame(np.sqrt(v))


@bi('spectralRolloffPoint', nout=2)
def spectralRolloffPoint(nargout, *args):
    """rolloff = spectralRolloffPoint(audioIn, fs, 'Threshold', 0.95, ...): the frequency below which that share of each window's spectral energy lies."""
    S, f, loc, opts = _spec_frames(args, 'spectralRolloffPoint', ('threshold',))
    th = float(num(opts['threshold'])) if 'threshold' in opts else 0.95
    if not 0 < th < 1:
        raise err('audio:spectralRolloffPoint:InvalidThreshold', 'Threshold is between 0 and 1.', 'spectralRolloffPoint')
    cs = np.cumsum(S, axis=0)
    tot = cs[-1]
    idx = np.argmax(cs >= th * tot[None], axis=0)
    r = f[idx]
    return (_per_frame(r), out(loc.reshape(-1, 1))) if nargout > 1 else _per_frame(r)


@bi('spectralFlatness', nout=2)
def spectralFlatness(nargout, *args):
    """flatness = spectralFlatness(audioIn, fs, ...): each window's geometric over arithmetic mean of its spectrum (1 for white noise, near 0 for a tone)."""
    S, f, loc, _ = _spec_frames(args, 'spectralFlatness')
    tiny = np.finfo(float).tiny
    with np.errstate(invalid='ignore', divide='ignore'):
        g = np.exp(np.mean(np.log(np.maximum(S, tiny)), axis=0))
        r = g / S.mean(axis=0)
    return (_per_frame(r), out(loc.reshape(-1, 1))) if nargout > 1 else _per_frame(r)


@bi('spectralEntropy', nout=2)
def spectralEntropy(nargout, *args):
    """entropy = spectralEntropy(audioIn, fs, ...): each window's spectral entropy, -sum(p log p)/log(N) of its normalized spectrum (from 0 to 1)."""
    S, f, loc, _ = _spec_frames(args, 'spectralEntropy')
    with np.errstate(invalid='ignore', divide='ignore'):
        p = S / S.sum(axis=0, keepdims=True)
        h = -np.sum(np.where(p > 0, p * np.log(np.where(p > 0, p, 1)), 0), axis=0) / math.log(S.shape[0])
    return (_per_frame(h), out(loc.reshape(-1, 1))) if nargout > 1 else _per_frame(h)


@bi('zerocrossrate', nout=2)
def zerocrossrate(nargout, *args):
    """[zcr, countTotal] = zerocrossrate(x, 'WindowLength', n, 'OverlapLength',
    k): the share of samples whose sign differs from the one before (zero
    counting as positive), for the whole signal or each window; countTotal
    the crossings."""
    nargchk(args, 1, 5, 'zerocrossrate')
    pos, opts = _pairs(args, 'zerocrossrate', ('windowlength', 'overlaplength', 'method'))
    x = _audio(pos[0], 'zerocrossrate')
    n = x.shape[0]
    wl = int(num(opts['windowlength'])) if 'windowlength' in opts else n
    ov = int(num(opts['overlaplength'])) if 'overlaplength' in opts else 0
    if not 0 <= ov < wl <= n:
        raise err('audio:zerocrossrate:InvalidWindow', 'WindowLength is up to the signal length, OverlapLength below it.', 'zerocrossrate')
    sgn = np.where(x >= 0, 1, -1)
    starts, _ = _frames(x, wl, ov)
    counts = np.array([[np.sum(sgn[s + 1:s + wl, c] != sgn[s:s + wl - 1, c]) for c in range(x.shape[1])] for s in starts], float).reshape(starts.size, x.shape[1])
    rate = counts / wl
    return (out(rate), out(counts)) if nargout > 1 else out(rate)
