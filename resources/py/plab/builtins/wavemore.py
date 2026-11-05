"""More wavelets: filter banks as objects (cwtfilterbank, dwtfilterbank:
wt, freqz, wavelets, scales, centerFrequencies, scalingfunctions,
framebounds, dwtpassbands), the wavelet synchrosqueezed transform and its
inverse (wsst, iwsst), wavelet coherence (wcoherence) and the empirical
wavelet transform (ewt)."""
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, darr, out, opt_str, is_str
from ..values import MError, Obj, Char, Struct, numel, py_str
from .. import runtime as R
from . import wavelets as WV


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'Wavelet:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0]) from None
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


def _col(v):
    return out(np.asarray(v).reshape(-1, 1))


def _nv(args, names, fn):
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


def _num(v):
    return float(np.asarray(darr(v), float).reshape(-1)[0])


# ---- the continuous wavelet filter bank -----------------------------------------------------------------------------------

class CWTFilterBank(Obj):
    cls = 'cwtfilterbank'
    is_handle = False
    METHODS = ('wt', 'freqz', 'wavelets', 'scales', 'centerFrequencies', 'centerPeriods', 'timeSpreads')

    def __init__(self, kind, params, N, fs, nv, flim, boundary):
        self.kind, self.params, self.N, self.fs, self.nv, self.flim, self.boundary = kind, params, N, fs, nv, flim, boundary
        self.wav = WV._CWave(kind, params)
        f = None if flim is None else np.asarray(flim, float) / fs
        self.sc = WV._scales(self.wav, N, nv, f)

    def value_copy(self):
        return CWTFilterBank(self.kind, self.params, self.N, self.fs, self.nv, self.flim, self.boundary)

    def freqs(self):
        return self.wav.wp / (2 * np.pi * self.sc) * self.fs

    def length(self):
        return 2 * self.N if self.boundary == 'reflection' else self.N

    def dft(self):
        """The filters' frequency responses (scales by DFT bins of the extended length) and the bins' frequencies."""
        M = self.length()
        w = 2 * np.pi * np.fft.fftfreq(M)
        return self.wav(np.outer(self.sc, w)), np.arange(M) * self.fs / M

    def getprop(self, name):
        k = name.lower()
        props = {'wavelet': lambda: Char.of({'morse': 'Morse', 'amor': 'amor', 'bump': 'bump'}[self.kind]),
                 'signallength': lambda: float(self.N), 'samplingfrequency': lambda: float(self.fs),
                 'voicesperoctave': lambda: float(self.nv), 'boundary': lambda: Char.of(self.boundary),
                 'frequencylimits': lambda: out(np.array([[self.freqs()[-1], self.freqs()[0]]])),
                 'waveletparameters': lambda: out(np.array([[self.wav.g, self.wav.g * self.wav.b]])) if self.kind == 'morse' else np.zeros((0, 0)),
                 'timebandwidth': lambda: float(self.wav.g * self.wav.b) if self.kind == 'morse' else math.nan}
        if k in props:
            return props[k]()
        hit = next((m for m in self.METHODS if m.lower() == k), None)
        if hit:
            from .classdef import BoundBuiltin
            return BoundBuiltin(self, hit)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'cwtfilterbank'.")

    def propnames(self):
        return ['Wavelet', 'SignalLength', 'SamplingFrequency', 'VoicesPerOctave', 'FrequencyLimits', 'WaveletParameters', 'Boundary']

    def display_lines(self):
        f = self.freqs()
        return ['  cwtfilterbank with properties:', '', f"              Wavelet: '{self.getprop('Wavelet').str()}'",
                f'         SignalLength: {self.N}', f'    SamplingFrequency: {self.fs:g}', f'      VoicesPerOctave: {self.nv}',
                f'      FrequencyLimits: [{f[-1]:.4g} {f[0]:.4g}]', f"             Boundary: '{self.boundary}'", '',
                f'  {self.sc.size} filters']


@bi('cwtfilterbank')
def cwtfilterbank(nargout, *args):
    """fb = cwtfilterbank('SignalLength', N, 'SamplingFrequency', fs, 'Wavelet', w, 'VoicesPerOctave', nv, 'FrequencyLimits', [f1 f2], 'WaveletParameters', [g p2], 'Boundary', 'reflection'): the filters of cwt as an object: wt(fb, x), freqz(fb), wavelets(fb), scales(fb), centerFrequencies(fb), centerPeriods(fb), timeSpreads(fb)."""
    o, rest = _nv(args, ('SignalLength', 'SamplingFrequency', 'SamplingPeriod', 'Wavelet', 'VoicesPerOctave', 'FrequencyLimits', 'WaveletParameters',
                         'TimeBandwidth', 'Boundary'), 'cwtfilterbank')
    if rest:
        raise err('Wavelet:cwtfilterbank:args', 'cwtfilterbank takes names and values.', 'cwtfilterbank')
    N = int(_num(o['SignalLength'])) if 'SignalLength' in o else 1024
    fs = _num(o['SamplingFrequency']) if 'SamplingFrequency' in o else (1 / _num(o['SamplingPeriod']) if 'SamplingPeriod' in o else 1.0)
    copts = {k.lower(): v for k, v in o.items() if k in ('Wavelet', 'VoicesPerOctave', 'WaveletParameters', 'TimeBandwidth')}
    wav, nv = WV._cwave(copts, [], 'cwtfilterbank')
    params = None
    if wav.kind == 'morse':
        params = (wav.g, wav.g * wav.b)
    flim = np.asarray(darr(o['FrequencyLimits']), float).reshape(-1) if 'FrequencyLimits' in o else None
    bnd = py_str(o['Boundary']).lower() if 'Boundary' in o else 'reflection'
    if bnd not in ('reflection', 'periodic'):
        raise err('Wavelet:cwtfilterbank:Boundary', "Boundary is 'reflection' or 'periodic'.", 'cwtfilterbank')
    return CWTFilterBank(wav.kind, params, N, fs, nv, flim, bnd)


def _cfb(v, fn):
    if not isinstance(v, CWTFilterBank):
        raise err(f'Wavelet:{fn}:fb', f'{fn} takes a cwtfilterbank here.', fn)
    return v


def _fb_wt(nargout, fb, *rest):
    x, col = WV._vec(rest[0], 'wt')
    if x.size != fb.N:
        raise err('Wavelet:wt:length', f'The signal must have SignalLength ({fb.N}) samples.', 'wt')
    W = WV._cwt(x, fb.wav, fb.sc, fb.boundary == 'reflection')
    f = fb.freqs()
    t = np.arange(x.size)
    edge = np.minimum(t + 1, x.size - t).astype(float)
    coi = np.minimum(fb.wav.wp / (2 * np.pi * edge / (math.sqrt(2) * fb.wav.sigma_t())) * fb.fs, f[0])
    if nargout == 0:
        WV._draw_scalogram(W, f, coi, x.size, fb.fs if fb.fs != 1 else None)
        return None
    return _outs(nargout, out(W), _col(f), _col(coi))


def _fb_freqz(nargout, fb, *rest):
    if isinstance(fb, DWTFilterBank):
        return _dwt_freqz(nargout, fb)
    P, f = fb.dft()
    if nargout == 0:
        half = f <= fb.fs / 2 + 1e-12
        R._builtin('plot', _col(f[half]), out(P[:, half].T))
        R._builtin('xlabel', Char.of('Frequency (Hz)' if fb.fs != 1 else 'Frequency (cycles/sample)'))
        R._builtin('ylabel', Char.of('Magnitude'))
        R._builtin('title', Char.of('CWT Filter Bank'))
        R._builtin('grid', Char.of('on'))
        return None
    return _outs(nargout, out(P), out(f.reshape(1, -1)))


def _fb_wavelets(nargout, fb, *rest):
    if isinstance(fb, DWTFilterBank):
        return _dwt_wavelets(nargout, fb)
    P, f = fb.dft()
    M = P.shape[1]
    psi = np.fft.fftshift(np.fft.ifft(P, axis=1), axes=1)
    t = (np.arange(M) - M // 2) / fb.fs
    return _outs(nargout, out(psi), out(t.reshape(1, -1)))


def _fb_scales(nargout, fb, *rest):
    return out(_cfb(fb, 'scales').sc.reshape(-1, 1))


def _fb_centers(nargout, fb, *rest):
    return _col(_cfb(fb, 'centerFrequencies').freqs())


def _fb_periods(nargout, fb, *rest):
    return _col(1 / _cfb(fb, 'centerPeriods').freqs())


def _fb_spreads(nargout, fb, *rest):
    fb = _cfb(fb, 'timeSpreads')
    return _col(fb.wav.sigma_t() * fb.sc / fb.fs)


# ---- the discrete wavelet filter bank ---------------------------------------------------------------------------------------

class DWTFilterBank(Obj):
    cls = 'dwtfilterbank'
    is_handle = False
    METHODS = ('freqz', 'wavelets', 'scalingfunctions', 'framebounds', 'dwtpassbands')

    def __init__(self, wname, N, level, fs, ftype, boundary):
        self.wname, self.N, self.level, self.fs, self.ftype, self.boundary = wname, N, level, fs, ftype, boundary
        w = WV.wavelet(wname, 'dwtfilterbank')
        self.lo, self.hi = (w.lo_d, w.hi_d) if ftype == 'analysis' else (w.lo_r, w.hi_r)

    def value_copy(self):
        return DWTFilterBank(self.wname, self.N, self.level, self.fs, self.ftype, self.boundary)

    def length(self):
        return 2 * self.N if self.boundary == 'reflection' else self.N

    def responses(self):
        """(Psi, Phi): the equivalent filters' DFTs at each level (level-by-M) and the last level's scaling filter's (1-by-M)."""
        M = self.length()
        k = np.arange(M)
        H = np.fft.fft(self.lo, M) if self.lo.size <= M else np.array([np.sum(self.lo * np.exp(-2j * np.pi * kk * np.arange(self.lo.size) / M)) for kk in k])
        G = np.fft.fft(self.hi, M) if self.hi.size <= M else np.array([np.sum(self.hi * np.exp(-2j * np.pi * kk * np.arange(self.hi.size) / M)) for kk in k])
        Psi = np.zeros((self.level, M), complex)
        acc = np.ones(M, complex)
        for j in range(self.level):
            step = 2 ** j
            idx = (k * step) % M
            Psi[j] = acc * G[idx]
            acc = acc * H[idx]
        return Psi, acc.reshape(1, -1)

    def getprop(self, name):
        k = name.lower()
        props = {'wavelet': lambda: Char.of(self.wname), 'signallength': lambda: float(self.N), 'level': lambda: float(self.level),
                 'samplingfrequency': lambda: float(self.fs), 'filtertype': lambda: Char.of(self.ftype.capitalize()),
                 'boundary': lambda: Char.of(self.boundary)}
        if k in props:
            return props[k]()
        hit = next((m for m in self.METHODS if m.lower() == k), None)
        if hit:
            from .classdef import BoundBuiltin
            return BoundBuiltin(self, hit)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'dwtfilterbank'.")

    def propnames(self):
        return ['Wavelet', 'SignalLength', 'Level', 'SamplingFrequency', 'FilterType', 'Boundary']

    def display_lines(self):
        return ['  dwtfilterbank with properties:', '', f"              Wavelet: '{self.wname}'", f'         SignalLength: {self.N}',
                f'                Level: {self.level}', f'    SamplingFrequency: {self.fs:g}', f"           FilterType: '{self.ftype.capitalize()}'",
                f"             Boundary: '{self.boundary}'"]


@bi('dwtfilterbank')
def dwtfilterbank(nargout, *args):
    """fb = dwtfilterbank('Wavelet', 'sym4', 'SignalLength', N, 'Level', L, 'SamplingFrequency', fs, 'FilterType', 'Analysis', 'Boundary', 'reflection'): the discrete wavelet transform's iterated filters as an object: freqz(fb), wavelets(fb), scalingfunctions(fb), framebounds(fb), dwtpassbands(fb)."""
    o, rest = _nv(args, ('Wavelet', 'SignalLength', 'Level', 'SamplingFrequency', 'FilterType', 'Boundary'), 'dwtfilterbank')
    if rest:
        raise err('Wavelet:dwtfilterbank:args', 'dwtfilterbank takes names and values.', 'dwtfilterbank')
    wname = py_str(o['Wavelet']) if 'Wavelet' in o else 'sym4'
    N = int(_num(o['SignalLength'])) if 'SignalLength' in o else 1024
    bnd = py_str(o['Boundary']).lower() if 'Boundary' in o else 'reflection'
    if bnd not in ('reflection', 'periodic'):
        raise err('Wavelet:dwtfilterbank:Boundary', "Boundary is 'reflection' or 'periodic'.", 'dwtfilterbank')
    M = 2 * N if bnd == 'reflection' else N
    level = int(_num(o['Level'])) if 'Level' in o else max(1, int(math.floor(math.log2(M))))
    if level < 1 or 2 ** level > M:
        raise err('Wavelet:dwtfilterbank:Level', f'Level is from 1 to floor(log2({M})).', 'dwtfilterbank')
    fs = _num(o['SamplingFrequency']) if 'SamplingFrequency' in o else 1.0
    ft = py_str(o['FilterType']).lower() if 'FilterType' in o else 'analysis'
    if ft not in ('analysis', 'synthesis'):
        raise err('Wavelet:dwtfilterbank:FilterType', "FilterType is 'Analysis' or 'Synthesis'.", 'dwtfilterbank')
    return DWTFilterBank(wname, N, level, fs, ft, bnd)


def _dwt_freqz(nargout, fb):
    Psi, Phi = fb.responses()
    f = np.arange(Psi.shape[1]) * fb.fs / Psi.shape[1]
    if nargout == 0:
        half = f <= fb.fs / 2 + 1e-12
        R._builtin('plot', _col(f[half]), out(np.abs(Psi[:, half]).T))
        R._builtin('xlabel', Char.of('Frequency (Hz)' if fb.fs != 1 else 'Frequency (cycles/sample)'))
        R._builtin('ylabel', Char.of('Magnitude'))
        R._builtin('title', Char.of('DWT Filter Bank'))
        R._builtin('grid', Char.of('on'))
        return None
    return _outs(nargout, out(Psi), out(f.reshape(1, -1)), out(Phi))


def _centred(D):
    M = D.shape[1]
    return np.real(np.fft.fftshift(np.fft.ifft(D, axis=1), axes=1)), (np.arange(M) - M // 2)


def _dwt_wavelets(nargout, fb):
    Psi, _ = fb.responses()
    psi, t = _centred(Psi)
    return _outs(nargout, out(psi), out((t / fb.fs).reshape(1, -1)))


def _dwt_scalingfunctions(nargout, fb, *rest):
    fb = _dfb(fb, 'scalingfunctions')
    Psi, Phi = fb.responses()
    # the scaling filter at each level
    M = fb.length()
    k = np.arange(M)
    H = np.fft.fft(fb.lo, M)
    acc = np.ones(M, complex)
    rows = []
    for j in range(fb.level):
        acc = acc * H[(k * 2 ** j) % M]
        rows.append(acc.copy())
    phi, t = _centred(np.array(rows))
    return _outs(nargout, out(phi), out((t / fb.fs).reshape(1, -1)))


def _dfb(v, fn):
    if not isinstance(v, DWTFilterBank):
        raise err(f'Wavelet:{fn}:fb', f'{fn} takes a dwtfilterbank.', fn)
    return v


def _dwt_framebounds(nargout, fb, *rest):
    fb = _dfb(fb, 'framebounds')
    Psi, Phi = fb.responses()
    S = np.sum(np.abs(Psi) ** 2 / (2.0 ** np.arange(1, fb.level + 1))[:, None], axis=0) + np.abs(Phi[0]) ** 2 / 2.0 ** fb.level
    return _outs(nargout, float(S.min()), float(S.max()))


def _dwt_passbands(nargout, fb, *rest):
    fb = _dfb(fb, 'dwtpassbands')
    j = np.arange(1, fb.level + 1)
    bands = np.column_stack([fb.fs / 2 ** (j + 1), fb.fs / 2 ** j])
    bands = np.vstack([bands, [0.0, fb.fs / 2 ** (fb.level + 1)]])
    return out(bands)


_HANDLERS = {'wt': _fb_wt, 'freqz': _fb_freqz, 'wavelets': _fb_wavelets, 'scales': _fb_scales, 'centerFrequencies': _fb_centers,
             'centerPeriods': _fb_periods, 'timeSpreads': _fb_spreads, 'scalingfunctions': _dwt_scalingfunctions, 'framebounds': _dwt_framebounds,
             'dwtpassbands': _dwt_passbands}


def _method(name, handler):
    """name as a builtin taking a filter bank first; an existing builtin of that name keeps its other inputs."""
    test = (lambda v: isinstance(v, (CWTFilterBank, DWTFilterBank)))
    info = REG.get(name)
    if info is None:
        def f(nargout, *args):
            if not args or not test(args[0]):
                raise err(f'Wavelet:{name}:fb', f'{name} takes a wavelet filter bank (cwtfilterbank, dwtfilterbank).', name)
            return handler(nargout, *args)
        f.__name__ = name
        f.__doc__ = f'{name}(fb): of a wavelet filter bank.'
        bi(name, nout=3)(f)
        return
    orig, ws, aw = info.fn, info.ws, info.aw
    if aw:
        async def g(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def g(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = g
    info.nout = max(info.nout, 3)


for _n, _h in _HANDLERS.items():
    _method(_n, _h)


# ---- synchrosqueezing ---------------------------------------------------------------------------------------------------------

def _sst_setup(args, fn):
    o, rest = _nv(args, ('VoicesPerOctave', 'ExtendSignal'), fn)
    kind = 'amor'
    fs = None
    for r in rest:
        if is_str(r):
            kind = py_str(r).lower()
            if kind not in ('amor', 'bump'):
                raise err(f'Wavelet:{fn}:wavelet', "The wavelet is 'amor' or 'bump'.", fn)
        elif numel(r):
            fs = _num(r)
    nv = int(_num(o['VoicesPerOctave'])) if 'VoicesPerOctave' in o else 32
    if not 10 <= nv <= 48 or nv % 2:
        raise err(f'Wavelet:{fn}:voices', 'VoicesPerOctave is an even number from 10 to 48.', fn)
    ext = bool(np.asarray(darr(o['ExtendSignal'])).reshape(-1)[0]) if 'ExtendSignal' in o else True
    return kind, fs, nv, ext


@bi('wsst', nout=2)
def wsst(nargout, *args):
    """[sst, f] = wsst(x, fs, wname, 'VoicesPerOctave', 32, 'ExtendSignal', true): the wavelet synchrosqueezed transform: cwt's coefficients (analytic Morlet 'amor', or 'bump') moved along frequency to the instantaneous frequency of each (the phase's derivative in time), onto the transform's own frequencies; drawn when no output is asked for."""
    nargchk(args, 1, 7, 'wsst')
    x, _ = WV._vec(args[0], 'wsst')
    kind, fs, nv, ext = _sst_setup(args[1:], 'wsst')
    wav = WV._CWave(kind)
    sc = WV._scales(wav, x.size, nv)
    N = x.size
    if ext:
        p = N // 2
        xe = np.concatenate([x[:p][::-1], x, x[N - (N - p):][::-1]])
        start = p
    else:
        xe, start = x, 0
    M = xe.size
    X = np.fft.fft(xe)
    w = 2 * np.pi * np.fft.fftfreq(M)
    Psi = wav(np.outer(sc, w))
    W = np.fft.ifft(X[None, :] * Psi, axis=1)[:, start:start + N]
    dW = np.fft.ifft(X[None, :] * Psi * (1j * w)[None, :], axis=1)[:, start:start + N]
    fk = wav.wp / (2 * np.pi * sc)                        # cycles per sample, falling
    with np.errstate(all='ignore'):
        inst = np.imag(dW / W) / (2 * np.pi)
    gamma = 1e-8 * float(np.max(np.abs(W))) if W.size else 0.0
    T = np.zeros_like(W)
    lf = np.log2(fk)
    step = lf[0] - lf[1] if fk.size > 1 else 1.0
    for b in range(N):
        good = (np.abs(W[:, b]) > gamma) & np.isfinite(inst[:, b]) & (inst[:, b] > 0)
        k = np.rint((lf[0] - np.log2(inst[good, b])) / step).astype(int)
        ok = (k >= 0) & (k < fk.size)
        np.add.at(T[:, b], k[ok], W[good, b][ok])
    T *= math.log(2) / nv
    f = fk * (fs if fs else 1.0)
    if nargout == 0:
        # the frequencies are spaced evenly in log2 (voices to an octave): drawn so, ticked in Hz, as cwt's scalogram
        tt = np.arange(N) / (fs if fs else 1.0)
        R._builtin('imagesc', out(tt.reshape(1, -1)), _col(np.log2(f)), out(np.abs(T)))
        R._builtin('axis', Char.of('xy'))
        WV._freq_ticks(R._builtin('gca'), np.log2(f))
        R._builtin('colorbar')
        R._builtin('title', Char.of('Wavelet Synchrosqueezed Transform'))
        R._builtin('xlabel', Char.of('Time (s)' if fs else 'Samples'))
        R._builtin('ylabel', Char.of('Frequency (Hz)' if fs else 'Frequency (cycles/sample)'))
        return None
    return _outs(nargout, out(T), _col(f))


@bi('iwsst')
def iwsst(nargout, *args):
    """xrec = iwsst(sst, wname, f, freqrange): the signal from wsst's transform: 2/C times the real part of the sum over frequency (C the wavelet's admissibility constant), all frequencies or those in freqrange."""
    nargchk(args, 1, 6, 'iwsst')
    T = np.asarray(darr(args[0]), complex)
    kind = 'amor'
    rest = list(args[1:])
    if rest and is_str(rest[0]):
        kind = py_str(rest.pop(0)).lower()
        if kind not in ('amor', 'bump'):
            raise err('Wavelet:iwsst:wavelet', "The wavelet is 'amor' or 'bump'.", 'iwsst')
    rows = np.arange(T.shape[0])
    if len(rest) >= 2:
        f = np.asarray(darr(rest[0]), float).reshape(-1)
        fr = np.asarray(darr(rest[1]), float).reshape(-1)
        rows = rows[(f >= fr.min()) & (f <= fr.max())]
    C = WV._CWave(kind).admissibility()
    return out((2 / C * np.real(T[rows]).sum(axis=0)).reshape(-1, 1))


# ---- wavelet coherence ------------------------------------------------------------------------------------------------------------

@bi('wcoherence', nout=5)
def wcoherence(nargout, *args):
    """[wcoh, wcs, f, coi] = wcoherence(x, y, fs, 'VoicesPerOctave', 12, 'NumScalesToSmooth', 12): the wavelet coherence of x and y (analytic Morlet): |S(Wx.*conj(Wy)./s)|^2 ./ (S(|Wx|.^2./s) .* S(|Wy|.^2./s)), S smoothing in time by a Gaussian as wide as the scale and across scales by a moving average; wcs the smoothed cross spectrum."""
    nargchk(args, 2, 9, 'wcoherence')
    o, rest = _nv(args[2:], ('VoicesPerOctave', 'NumScalesToSmooth', 'NumOctaves', 'PhaseDisplayThreshold'), 'wcoherence')
    x, _ = WV._vec(args[0], 'wcoherence')
    y, _ = WV._vec(args[1], 'wcoherence')
    if x.size != y.size:
        raise err('Wavelet:wcoherence:size', 'x and y must have the same length.', 'wcoherence')
    fs = _num(rest[0]) if rest and numel(rest[0]) else None
    nv = int(_num(o['VoicesPerOctave'])) if 'VoicesPerOctave' in o else 12
    ns = int(_num(o['NumScalesToSmooth'])) if 'NumScalesToSmooth' in o else nv
    wav = WV._CWave('amor')
    sc = WV._scales(wav, x.size, nv)
    Wx = WV._cwt(x, wav, sc)
    Wy = WV._cwt(y, wav, sc)
    inv = (1 / sc)[:, None]

    def smooth(A):
        N = A.shape[1]
        w = 2 * np.pi * np.fft.fftfreq(2 * N)
        B = np.zeros_like(A, dtype=complex)
        for i, s in enumerate(sc):
            g = np.exp(-0.5 * (s * w) ** 2)          # a Gaussian of width s in time
            pad = np.concatenate([A[i], np.zeros(N)])
            B[i] = np.fft.ifft(np.fft.fft(pad) * g)[:N]
        k = max(1, ns // 2)
        C = np.zeros_like(B)
        for i in range(B.shape[0]):
            lo, hi = max(0, i - k), min(B.shape[0], i + k + 1)
            C[i] = B[lo:hi].mean(axis=0)
        return C
    Sxy = smooth(Wx * np.conj(Wy) * inv)
    Sxx = np.real(smooth(np.abs(Wx) ** 2 * inv))
    Syy = np.real(smooth(np.abs(Wy) ** 2 * inv))
    with np.errstate(all='ignore'):
        coh = np.abs(Sxy) ** 2 / (Sxx * Syy)
    coh = np.clip(np.nan_to_num(coh), 0, 1)
    f = wav.wp / (2 * np.pi * sc) * (fs if fs else 1.0)
    t = np.arange(x.size)
    edge = np.minimum(t + 1, x.size - t).astype(float)
    coi = np.minimum(wav.wp / (2 * np.pi * edge / (math.sqrt(2) * wav.sigma_t())) * (fs if fs else 1.0), f[0])
    if nargout == 0:
        tt = t / (fs if fs else 1.0)
        y = np.log2(f)
        R._builtin('imagesc', out(tt.reshape(1, -1)), _col(y), out(coh))
        ax = R._builtin('gca')
        R._builtin('axis', Char.of('xy'))
        R._builtin('hold', Char.of('on'))
        R._builtin('plot', out(tt.reshape(1, -1)), out(np.log2(np.maximum(coi, f[-1])).reshape(1, -1)), Char.of('w--'), Char.of('LineWidth'), 1.5)
        R._builtin('hold', Char.of('off'))
        WV._freq_ticks(ax, y)
        R._builtin('colorbar')
        R._builtin('title', Char.of('Wavelet Coherence'))
        R._builtin('xlabel', Char.of('Time (s)' if fs else 'Samples'))
        R._builtin('ylabel', Char.of('Frequency (Hz)' if fs else 'Frequency (cycles/sample)'))
        return None
    return _outs(nargout, out(coh), out(Sxy), _col(f), _col(coi))


# ---- the empirical wavelet transform ---------------------------------------------------------------------------------------------

def _beta(x):
    x = np.clip(x, 0, 1)
    return x ** 4 * (35 - 84 * x + 70 * x ** 2 - 20 * x ** 3)


@bi('ewt', nout=3)
def ewt(nargout, *args):
    """[mra, mfb, info] = ewt(x, 'MaxNumPeaks', 5, 'PeakThresholdPercent', 70, 'SegmentMethod', 'geomean', 'LogSpectrum', false): the empirical wavelet transform (Gilles): the spectrum's largest peaks (at most MaxNumPeaks, at least PeakThresholdPercent of the largest), boundaries between neighbours (the geometric mean of their frequencies, or 'localmin', the lowest point between), Meyer-type filters with smooth transitions (the widest that keep them a tight frame); mra the components (sum(mra, 2) = x), mfb the filters' frequency responses."""
    o, rest = _nv(args, ('MaxNumPeaks', 'PeakThresholdPercent', 'SegmentMethod', 'LogSpectrum', 'FrequencyResolution'), 'ewt')
    nargchk(rest, 1, 1, 'ewt')
    x, _ = WV._vec(rest[0], 'ewt')
    N = x.size
    maxp = int(_num(o['MaxNumPeaks'])) if 'MaxNumPeaks' in o else 5
    thr = (_num(o['PeakThresholdPercent']) if 'PeakThresholdPercent' in o else 70.0) / 100
    seg = py_str(o['SegmentMethod']).lower() if 'SegmentMethod' in o else 'geomean'
    if seg not in ('geomean', 'localmin'):
        raise err('Wavelet:ewt:SegmentMethod', "SegmentMethod is 'geomean' or 'localmin'.", 'ewt')
    logs = bool(np.asarray(darr(o['LogSpectrum'])).reshape(-1)[0]) if 'LogSpectrum' in o else False
    # the spectrum on [0, pi], smoothed by a short moving average
    X = np.fft.fft(x)
    half = N // 2 + 1
    S = np.abs(X[:half]) ** 2
    if logs:
        S = np.log(S + 1e-300)
    k = max(1, half // 100)
    Ss = np.convolve(S, np.ones(2 * k + 1) / (2 * k + 1), mode='same')
    w = np.arange(half) * 2 * np.pi / N
    pk = np.flatnonzero((Ss[1:-1] > Ss[:-2]) & (Ss[1:-1] >= Ss[2:])) + 1
    # each peak where the unsmoothed spectrum is largest within the smoothing's width
    pk = np.unique([max(p - k, 0) + int(np.argmax(S[max(p - k, 0):p + k + 1])) for p in pk]).astype(int)
    if pk.size:
        top = Ss[pk].max()
        pk = pk[Ss[pk] >= thr * top] if not logs else pk
        pk = np.sort(pk[np.argsort(-Ss[pk])][:maxp])
    bounds = []
    for a, b in zip(pk[:-1], pk[1:]):
        if seg == 'geomean':
            bounds.append(math.sqrt(max(w[a], 1e-12) * w[b]))
        else:
            bounds.append(w[a + int(np.argmin(Ss[a:b + 1]))])
    wb = np.array(bounds)
    # the transition half-width: gamma * omega_n, gamma the largest keeping neighbours' transitions apart
    edges = np.concatenate([[0.0], wb, [np.pi]])
    if wb.size:
        gam = min([(edges[i + 1] - edges[i]) / (edges[i + 1] + edges[i]) for i in range(edges.size - 1) if edges[i + 1] + edges[i] > 0] + [1.0])
        gam = 0.999 * gam
    else:
        gam = 0.0
    wf = np.abs(2 * np.pi * np.fft.fftfreq(N))
    filt = []
    lo = wb[0] if wb.size else np.pi
    if wb.size:
        t = gam * lo
        phi = np.where(wf <= lo - t, 1.0, np.where(wf <= lo + t, np.cos(np.pi / 2 * _beta((wf - lo + t) / (2 * t))) if t > 0 else 0.0, 0.0))
    else:
        phi = np.ones(N)
    filt.append(phi)
    for i in range(wb.size):
        a = wb[i]
        b = wb[i + 1] if i + 1 < wb.size else None
        ta = gam * a
        up = np.where(wf >= a + ta, 1.0, np.where(wf >= a - ta, np.sin(np.pi / 2 * _beta((wf - a + ta) / (2 * ta))) if ta > 0 else 0.0, 0.0))
        if b is not None:
            tb = gam * b
            down = np.where(wf <= b - tb, 1.0, np.where(wf <= b + tb, np.cos(np.pi / 2 * _beta((wf - b + tb) / (2 * tb))) if tb > 0 else 0.0, 0.0))
            filt.append(up * down)
        else:
            filt.append(up)
    F = np.array(filt)
    mra = np.real(np.fft.ifft(X[None, :] * F ** 2, axis=1)).T
    info = Struct.scalar({'PeakFrequencies': _col(w[pk] / (2 * np.pi)) if pk.size else np.zeros((0, 1)),
                          'FilterBank': out(F.T), 'BoundaryFrequencies': _col(wb / (2 * np.pi)) if wb.size else np.zeros((0, 1))})
    if nargout == 0:
        from .signalmore import _modes_plot
        return _modes_plot(x, mra, x - mra.sum(axis=1), 'MRA')
    return _outs(nargout, out(mra), out(F[:, :half].T), info)

