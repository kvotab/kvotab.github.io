"""Communications: noise (awgn), modulation and demodulation (qammod,
qamdemod, pskmod, pskdemod, pammod, pamdemod) with Gray or binary labels,
bits and integers (int2bit, bit2int, de2bi, bi2de, bin2gray, gray2bin),
error counts (biterr, symerr), the theoretical error rates in white noise
(berawgn), raised-cosine filters (rcosdesign), and eye and constellation
diagrams (eyediagram, scatterplot).

Square QAM (M a power of 4, or 2) puts the integer's high bits on the
in-phase axis and its low bits on the quadrature axis, each Gray coded, the
first point at the top left; PSK and PAM order their points by the Gray
code of the integer.
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
            except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError, OverflowError) as e:
                raise err(f'comm:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
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
        pos.append(args[k])
        k += 1
    return pos, opts


def _M(v, fn, square=False):
    M = float(num(v))
    k = math.log2(M) if M > 0 else -1
    if M < 2 or k != int(k):
        raise err(f'comm:{fn}:InvalidM', 'M is a power of 2, at least 2.', fn)
    if square and M > 2 and int(k) % 2:
        raise err(f'comm:{fn}:InvalidM', 'M is 2 or a power of 4 here (square constellations).', fn)
    return int(M)


def gray(k):
    k = np.asarray(k, np.int64)
    return k ^ (k >> 1)


def igray(g):
    g = np.asarray(g, np.int64).copy()
    out_ = g.copy()
    s = g >> 1
    while np.any(s):
        out_ ^= s
        s >>= 1
    return out_


# ---- bits and integers ------------------------------------------------------------------------------------------------------

def _bits(ints, k, msbfirst=True):
    """The k bits of each integer, as rows."""
    ints = np.asarray(ints, np.int64).reshape(-1)
    sh = np.arange(k - 1, -1, -1) if msbfirst else np.arange(k)
    return ((ints[:, None] >> sh[None, :]) & 1).astype(float)


def _ints(bits, k, msbfirst=True):
    b = np.asarray(bits, np.int64).reshape(-1, k)
    w = 2 ** (np.arange(k - 1, -1, -1) if msbfirst else np.arange(k))
    return b @ w


@bi('int2bit')
def int2bit(nargout, *args):
    """Y = int2bit(X, n, msbfirst): each integer of X as n bits (most significant first unless msbfirst is false), stacked down each column."""
    nargchk(args, 2, 3, 'int2bit')
    X = np.asarray(darr(args[0]), float)
    n = int(num(args[1]))
    msb = bool(num(args[2])) if len(args) > 2 else True
    if np.any(X < 0) or np.any(X != np.round(X)):
        raise err('comm:int2bit:InvalidInput', 'X holds nonnegative whole numbers.', 'int2bit')
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    cols = [_bits(X[:, j], n, msb).reshape(-1) for j in range(X.shape[1])]
    return out(np.column_stack(cols))


@bi('bit2int')
def bit2int(nargout, *args):
    """Y = bit2int(X, n, msbfirst): each n bits down the columns of X as an integer (most significant first unless msbfirst is false)."""
    nargchk(args, 2, 3, 'bit2int')
    X = np.asarray(darr(args[0]), float)
    n = int(num(args[1]))
    msb = bool(num(args[2])) if len(args) > 2 else True
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    if X.shape[0] % n:
        raise err('comm:bit2int:InvalidLength', 'Each column holds a multiple of n bits.', 'bit2int')
    return out(np.column_stack([_ints(X[:, j], n, msb) for j in range(X.shape[1])]).astype(float))


@bi('de2bi')
def de2bi(nargout, *args):
    """B = de2bi(D, n, p, flg): each number of D as a row of n digits in base p (2): 'right-msb' (the first column the least significant, the default) or 'left-msb'."""
    nargchk(args, 1, 4, 'de2bi')
    D = np.asarray(darr(args[0]), float).reshape(-1)
    flg = 'right-msb'
    rest = [a for a in args[1:]]
    if rest and is_str(rest[-1]):
        flg = py_str(rest.pop()).lower()
    p = int(num(rest[1])) if len(rest) > 1 and numel(rest[1]) else 2
    if np.any(D < 0) or np.any(D != np.round(D)):
        raise err('comm:de2bi:InvalidInput', 'D holds nonnegative whole numbers.', 'de2bi')
    need = int(np.max(np.floor(np.log(np.maximum(D, 1)) / np.log(p) + 1e-12)) + 1) if D.size else 1
    n = int(num(rest[0])) if rest and numel(rest[0]) else need
    if n < need:
        raise err('comm:de2bi:TooFewDigits', f'{n} digits cannot hold these numbers.', 'de2bi')
    digits = np.zeros((D.size, n))
    v = D.astype(np.int64)
    for j in range(n):
        digits[:, j] = v % p
        v //= p
    if flg == 'left-msb':
        digits = digits[:, ::-1]
    elif flg != 'right-msb':
        raise err('comm:de2bi:InvalidFlag', "The flag is 'right-msb' or 'left-msb'.", 'de2bi')
    return out(digits)


@bi('bi2de')
def bi2de(nargout, *args):
    """D = bi2de(B, p, flg): each row of digits in base p (2) as a number, 'right-msb' (the default) or 'left-msb'."""
    nargchk(args, 1, 3, 'bi2de')
    B = np.atleast_2d(np.asarray(darr(args[0]), float))
    rest = list(args[1:])
    flg = 'right-msb'
    if rest and is_str(rest[-1]):
        flg = py_str(rest.pop()).lower()
    p = int(num(rest[0])) if rest and numel(rest[0]) else 2
    if flg == 'left-msb':
        B = B[:, ::-1]
    return out((B @ (float(p) ** np.arange(B.shape[1]))).reshape(-1, 1))


@bi('bin2gray', nout=2)
def bin2gray(nargout, *args):
    """[y, map] = bin2gray(x, modulation, M): the Gray-coded labels of integers for 'qam', 'psk', 'pam' or 'fsk' (qam: each axis's half of the bits)."""
    nargchk(args, 3, 3, 'bin2gray')
    x = np.asarray(darr(args[0]), float)
    mod = py_str(args[1]).lower()
    M = _M(args[2], 'bin2gray', mod == 'qam')
    mp = _gray_map(mod, M, 'bin2gray')
    return (out(mp[x.astype(np.int64)].astype(float)), out(mp.reshape(-1, 1).astype(float))) if nargout > 1 else out(mp[x.astype(np.int64)].astype(float))


@bi('gray2bin', nout=2)
def gray2bin(nargout, *args):
    """[y, map] = gray2bin(x, modulation, M): the integers of Gray-coded labels (bin2gray undone)."""
    nargchk(args, 3, 3, 'gray2bin')
    x = np.asarray(darr(args[0]), float)
    mod = py_str(args[1]).lower()
    M = _M(args[2], 'gray2bin', mod == 'qam')
    mp = _gray_map(mod, M, 'gray2bin')
    inv = np.argsort(mp)
    return (out(inv[x.astype(np.int64)].astype(float)), out(inv.reshape(-1, 1).astype(float))) if nargout > 1 else out(inv[x.astype(np.int64)].astype(float))


def _gray_map(mod, M, fn):
    if mod in ('psk', 'pam', 'fsk'):
        return gray(np.arange(M))
    if mod == 'qam':
        if M == 2:
            return np.arange(2)
        h = int(round(math.sqrt(M)))
        k = np.arange(M)
        return gray(k // h) * h + gray(k % h)
    raise err(f'comm:{fn}:InvalidModulation', "The modulation is 'qam', 'psk', 'pam' or 'fsk'.", fn)


# ---- constellations -----------------------------------------------------------------------------------------------------------

def qam_points(M, order='gray'):
    """The constellation point of each integer 0 .. M-1."""
    if M == 2:
        return np.array([-1.0 + 0j, 1.0 + 0j])
    h = int(round(math.sqrt(M)))
    k = np.arange(M)
    hi, lo = k // h, k % h
    if order == 'gray':
        hi, lo = igray(hi), igray(lo)
    levels = 2 * np.arange(h) - (h - 1)
    return levels[hi] + 1j * levels[::-1][lo]


def psk_points(M, phase=0.0, order='gray'):
    k = np.arange(M)
    pos = igray(k) if order == 'gray' else k
    return np.exp(1j * (2 * np.pi * pos / M + phase))


def pam_points(M, order='gray'):
    k = np.arange(M)
    pos = igray(k) if order == 'gray' else k
    return (2 * pos - (M - 1)).astype(complex)


def _order(v, M, fn):
    if v is None:
        return 'gray', None
    if is_str(v):
        o = py_str(v).lower()
        if o not in ('gray', 'bin'):
            raise err(f'comm:{fn}:InvalidSymbolOrder', "The symbol order is 'gray', 'bin' or a mapping vector.", fn)
        return o, None
    m = np.asarray(darr(v), float).reshape(-1).astype(np.int64)
    if sorted(m.tolist()) != list(range(M)):
        raise err(f'comm:{fn}:InvalidSymbolOrder', f'A mapping vector holds 0 to {M - 1}, each once.', fn)
    return 'custom', m


def _apply_map(pts_bin, order, mapping):
    """The points for a custom mapping: integer mapping[j] goes where the binary order puts j."""
    if order != 'custom':
        return pts_bin
    pts = np.empty_like(pts_bin)
    pts[mapping] = pts_bin
    return pts


def _symbols_in(x, M, input_type, fn):
    a = np.asarray(darr(x, fn), float)
    k = int(round(math.log2(M)))
    if input_type == 'bit':
        if a.ndim == 2 and a.shape[0] == 1:
            a = a.T
        if a.shape[0] % k:
            raise err(f'comm:{fn}:InvalidBits', f'The bits come in groups of {k}: a column with a multiple of {k} rows.', fn)
        if np.any((a != 0) & (a != 1)):
            raise err(f'comm:{fn}:InvalidBits', 'Bits are 0 and 1.', fn)
        return np.column_stack([_ints(a[:, j], k) for j in range(a.shape[1])]) if a.ndim == 2 else _ints(a, k).reshape(-1, 1)
    if np.any(a < 0) or np.any(a >= M) or np.any(a != np.round(a)):
        raise err(f'comm:{fn}:InvalidInput', f'The symbols are whole numbers from 0 to {M - 1}.', fn)
    return a.astype(np.int64)


def _modulate(fn, args, names, make):
    pos, opts = _pairs(args, fn, names)
    if len(pos) < 2:
        raise err('MATLAB:minrhs', 'Give the symbols and M.', fn)
    M = _M(pos[1], fn, fn == 'qammod')
    pts, extra = make(M, pos[2:], opts)
    itype = (opt_str(opts['inputtype']) or 'integer').lower() if 'inputtype' in opts else 'integer'
    if itype not in ('integer', 'bit'):
        raise err(f'comm:{fn}:InvalidInputType', "InputType is 'integer' or 'bit'.", fn)
    ints = _symbols_in(pos[0], M, itype, fn)
    y = pts[ints]
    if 'plotconstellation' in opts and bool(num(opts['plotconstellation'])):
        _constellation_plot(pts, M, fn)
    return out(y)


def _unit(pts, opts):
    if 'unitaveragepower' in opts and bool(num(opts['unitaveragepower'])):
        return pts / math.sqrt(np.mean(np.abs(pts) ** 2))
    return pts


def _qam_make(M, rest, opts):
    order, mapping = _order(rest[0] if rest else opts.get('symbolorder'), M, 'qammod')
    pts = qam_points(M, 'bin' if order == 'custom' else order)
    return _unit(_apply_map(pts, order, mapping), opts), None


def _psk_make(M, rest, opts):
    phase = float(num(rest[0])) if rest and numel(rest[0]) else 0.0
    order, mapping = _order(rest[1] if len(rest) > 1 else opts.get('symbolorder'), M, 'pskmod')
    pts = psk_points(M, phase, 'bin' if order == 'custom' else order)
    return _apply_map(pts, order, mapping), None


def _pam_make(M, rest, opts):
    phase = float(num(rest[0])) if rest and numel(rest[0]) else 0.0
    order, mapping = _order(rest[1] if len(rest) > 1 else opts.get('symbolorder'), M, 'pammod')
    pts = pam_points(M, 'bin' if order == 'custom' else order) * np.exp(1j * phase)
    return _apply_map(pts, order, mapping), None


_MOD_OPTS = ('inputtype', 'unitaveragepower', 'plotconstellation', 'outputdatatype', 'symbolorder')
_DEMOD_OPTS = ('outputtype', 'unitaveragepower', 'noisevariance', 'plotconstellation', 'outputdatatype', 'symbolorder')


@bi('qammod')
def qammod(nargout, *args):
    """y = qammod(x, M, symOrder, 'InputType', 'bit', 'UnitAveragePower',
    true, 'PlotConstellation', true): square M-QAM symbols of integers 0 to
    M-1 (or of groups of log2(M) bits), Gray coded unless symOrder is 'bin'
    or a mapping."""
    y = _modulate('qammod', args, _MOD_OPTS, _qam_make)
    return _real_if_pam(y)


@bi('pskmod')
def pskmod(nargout, *args):
    """y = pskmod(x, M, phaseoffset, symOrder, 'InputType', 'bit'): M-PSK symbols exp(1i*(2*pi*k/M + phaseoffset)), Gray coded unless 'bin'."""
    return _modulate('pskmod', args, _MOD_OPTS, _psk_make)


@bi('pammod')
def pammod(nargout, *args):
    """y = pammod(x, M, phaseoffset, symOrder, 'InputType', 'bit'): M-PAM symbols -(M-1), ..., M-1 in steps of 2, Gray coded unless 'bin'."""
    y = _modulate('pammod', args, _MOD_OPTS, _pam_make)
    return _real_if_pam(y)


def _real_if_pam(y):
    a = np.asarray(y)
    if a.dtype.kind == 'c' and np.all(a.imag == 0):
        return out(a.real.copy())
    return y


def _demodulate(fn, args, make):
    pos, opts = _pairs(args, fn, _DEMOD_OPTS)
    if len(pos) < 2:
        raise err('MATLAB:minrhs', 'Give the received symbols and M.', fn)
    M = _M(pos[1], fn, fn == 'qamdemod')
    pts, _ = make(M, pos[2:], opts)
    y = np.asarray(darr(pos[0], fn))
    if y.ndim == 1:
        y = y.reshape(-1, 1)
    otype = (opt_str(opts['outputtype']) or 'integer').lower() if 'outputtype' in opts else 'integer'
    if otype not in ('integer', 'bit', 'llr', 'approxllr'):
        raise err(f'comm:{fn}:InvalidOutputType', "OutputType is 'integer', 'bit', 'llr' or 'approxllr'.", fn)
    yc = y.astype(complex)
    d2 = np.abs(yc[..., None] - pts.reshape((1,) * yc.ndim + (-1,))) ** 2
    ints = np.argmin(d2, axis=-1)
    if otype == 'integer':
        return out(ints.astype(float))
    k = int(round(math.log2(M)))
    if otype == 'bit':
        cols = []
        for j in range(ints.shape[1]):
            cols.append(_bits(ints[:, j], k).reshape(-1))
        return out(np.column_stack(cols))
    nv = np.asarray(darr(opts['noisevariance']), float) if 'noisevariance' in opts else np.array(1.0)
    labels = _bits(np.arange(M), k)               # M x k
    cols = []
    for j in range(yc.shape[1]):
        D = d2[:, j, :]                           # n x M
        v = float(nv.reshape(-1)[min(j, nv.size - 1)]) if nv.size > 1 else float(nv)
        L = np.zeros((D.shape[0], k))
        for b in range(k):
            s0, s1 = labels[:, b] == 0, labels[:, b] == 1
            if otype == 'approxllr':
                L[:, b] = (D[:, s1].min(axis=1) - D[:, s0].min(axis=1)) / v
            else:
                from scipy.special import logsumexp
                L[:, b] = logsumexp(-D[:, s0] / v, axis=1) - logsumexp(-D[:, s1] / v, axis=1)
        cols.append(L.reshape(-1))
    return out(np.column_stack(cols))


@bi('qamdemod')
def qamdemod(nargout, *args):
    """z = qamdemod(y, M, symOrder, 'OutputType', 'integer', 'bit', 'llr' or
    'approxllr', 'UnitAveragePower', true, 'NoiseVariance', v): the nearest
    QAM points' integers, their bits, or each bit's log-likelihood ratio
    log(P(0)/P(1))."""
    return _demodulate('qamdemod', args, _qam_make)


@bi('pskdemod')
def pskdemod(nargout, *args):
    """z = pskdemod(y, M, phaseoffset, symOrder, 'OutputType', ...): the nearest PSK points' integers, bits or log-likelihood ratios."""
    return _demodulate('pskdemod', args, _psk_make)


@bi('pamdemod')
def pamdemod(nargout, *args):
    """z = pamdemod(y, M, phaseoffset, symOrder, 'OutputType', ...): the nearest PAM points' integers, bits or log-likelihood ratios."""
    return _demodulate('pamdemod', args, _pam_make)


# ---- noise and errors -----------------------------------------------------------------------------------------------------------

@bi('awgn')
def awgn(nargout, *args):
    """y = awgn(x, snr), awgn(x, snr, sigpower), awgn(x, snr, 'measured'),
    awgn(..., seed), awgn(..., 'linear'): x with white Gaussian noise added
    at the signal-to-noise ratio snr (dB): the signal power sigpower (dBW,
    0 unless given, or measured from x); complex x gets complex noise."""
    nargchk(args, 2, 5, 'awgn')
    x = np.asarray(darr(args[0], 'awgn'))
    rest = list(args[1:])
    linear = False
    if rest and is_str(rest[-1]) and py_str(rest[-1]).lower() in ('db', 'linear'):
        linear = py_str(rest.pop()).lower() == 'linear'
    snr = float(num(rest[0]))
    sig = rest[1] if len(rest) > 1 else None
    seed = rest[2] if len(rest) > 2 else None
    if sig is not None and is_str(sig):
        if py_str(sig).lower() != 'measured':
            raise err('comm:awgn:InvalidSignalPower', "The signal power is a number or 'measured'.", 'awgn')
        p = float(np.mean(np.abs(x) ** 2)) if x.size else 0.0
    elif sig is not None and numel(sig):
        p = float(num(sig))
        p = p if linear else 10 ** (p / 10)
    else:
        p = 1.0
    snr_lin = snr if linear else 10 ** (snr / 10)
    npow = p / snr_lin
    if seed is not None and numel(seed):
        rs = np.random.RandomState(int(num(seed)))
        draw = lambda shape: rs.standard_normal(shape)
    else:
        from .elmat import RNG
        draw = lambda shape: RNG.rs.standard_normal(shape)
    if np.iscomplexobj(x):
        noise = math.sqrt(npow / 2) * (draw(x.shape) + 1j * draw(x.shape))
    else:
        noise = math.sqrt(npow) * draw(x.shape)
    return out(x + noise)


def _bitcount(v):
    v = np.asarray(v, np.int64)
    c = np.zeros(v.shape, np.int64)
    while np.any(v):
        c += v & 1
        v >>= 1
    return c


@bi('biterr', nout=3)
def biterr(nargout, *args):
    """[number, ratio, individual] = biterr(x, y, k): the bits that differ
    between the integers of x and y (k bits each, as many as the largest
    needs unless given)."""
    nargchk(args, 2, 4, 'biterr')
    x = np.asarray(darr(args[0]), float)
    y = np.asarray(darr(args[1]), float)
    if np.any(x < 0) or np.any(y < 0) or np.any(x != np.round(x)) or np.any(y != np.round(y)):
        raise err('comm:biterr:InvalidInput', 'x and y hold nonnegative whole numbers.', 'biterr')
    x, y = np.broadcast_arrays(x, y)
    top = max(float(x.max()) if x.size else 0, float(y.max()) if y.size else 0)
    need = int(math.floor(math.log2(top))) + 1 if top >= 1 else 1
    k = int(num(args[2])) if len(args) > 2 and numel(args[2]) else need
    if k < need:
        raise err('comm:biterr:TooFewBits', f'{k} bits cannot hold these numbers.', 'biterr')
    ind = _bitcount(x.astype(np.int64) ^ y.astype(np.int64))
    n = float(ind.sum())
    vals = (n, n / (x.size * k) if x.size else np.nan, out(ind.astype(float)))
    return vals[:nargout] if nargout > 1 else vals[0]


@bi('symerr', nout=3)
def symerr(nargout, *args):
    """[number, ratio, loc] = symerr(x, y): the symbols that differ, their share, and where (logical)."""
    nargchk(args, 2, 3, 'symerr')
    x, y = np.broadcast_arrays(np.asarray(darr(args[0])), np.asarray(darr(args[1])))
    loc = x != y
    n = float(loc.sum())
    vals = (n, n / x.size if x.size else np.nan, out(loc.astype(float)))
    return vals[:nargout] if nargout > 1 else vals[0]


# ---- theoretical error rates --------------------------------------------------------------------------------------------------

def _q(x):
    from scipy.special import erfc
    return 0.5 * erfc(np.asarray(x, float) / math.sqrt(2))


def pam_rates(M, es_n0):
    """Bit and symbol error rates of Gray M-PAM (points 2i - (M-1)) in white noise: each sent point's chances of landing in
    each decision region, the bits that differ counted."""
    pts = 2 * np.arange(M) - (M - 1)
    Es = np.mean(pts ** 2)
    sigma = np.sqrt(Es / (2 * es_n0))                          # per dimension: N0/2
    edges = np.concatenate([[-np.inf], (pts[:-1] + pts[1:]) / 2, [np.inf]])
    lab = gray(np.arange(M))                                    # label at each position
    k = int(round(math.log2(M)))
    ber = np.zeros_like(sigma)
    ser = np.zeros_like(sigma)
    for i in range(M):
        hi = _q((edges[:-1] - pts[i])[:, None] / sigma[None, :])
        lo = _q((edges[1:] - pts[i])[:, None] / sigma[None, :])
        P = hi - lo                                             # M x len(snr)
        dh = _bitcount(lab ^ lab[i]).astype(float)
        ber += (dh[:, None] * P).sum(axis=0)
        ser += 1 - P[i]
    return ber / (M * k), ser / M


def psk_rates(M, es_n0):
    """Bit and symbol error rates of Gray M-PSK: the received phase's density integrated over each decision sector."""
    from scipy.integrate import quad
    k = int(round(math.log2(M)))
    if M == 2:
        p = _q(np.sqrt(2 * es_n0))
        return p, p
    if M == 4:
        pb = _q(np.sqrt(es_n0))
        return pb, 1 - (1 - pb) ** 2
    lab = gray(np.arange(M))                                    # label of the sector at position j
    ber, ser = np.zeros_like(es_n0), np.zeros_like(es_n0)
    for n, g in enumerate(es_n0):
        def dens(th):
            c = math.cos(th)
            return (1 / (2 * math.pi)) * math.exp(-g) * (1 + math.sqrt(4 * math.pi * g) * c * math.exp(g * c * c) * (1 - float(_q(math.sqrt(2 * g) * c)))) \
                if g * c * c < 700 else 0.0
        b = s = 0.0
        for j in range(M):
            lo, hi = (2 * j - 1) * math.pi / M, (2 * j + 1) * math.pi / M
            P = quad(dens, lo, hi, limit=200, epsabs=1e-15)[0]
            b += _bitcount(np.array(lab[j] ^ lab[0])) * P
            if j:
                s += P
        ber[n], ser[n] = b / k, s
    return ber, ser


@bi('berawgn', nout=2)
def berawgn(nargout, *args):
    """[ber, ser] = berawgn(EbNo, modtype, M, ...): the bit and symbol error
    rates of Gray-coded modulation in white Gaussian noise at EbNo (dB):
    'psk' (M, with 'nondiff'), 'qam' (square M), 'pam', 'dpsk' (M = 2),
    'fsk' (M = 2, 'coherent' or 'noncoherent'), 'msk'."""
    nargchk(args, 2, 6, 'berawgn')
    eb = np.asarray(darr(args[0]), float)
    mod = py_str(args[1]).lower()
    ebl = 10 ** (eb.reshape(-1) / 10)
    if mod in ('psk', 'qam', 'pam'):
        M = _M(args[2] if len(args) > 2 else 2, 'berawgn', mod == 'qam')
        k = int(round(math.log2(M)))
        es = ebl * k
        if mod == 'psk':
            ber, ser = psk_rates(M, es)
        elif mod == 'pam':
            ber, ser = pam_rates(M, es)
        elif M == 2:
            ber, ser = psk_rates(2, es)
        else:
            # square QAM: two independent sqrt(M)-PAMs, each with half the symbol energy
            h = int(round(math.sqrt(M)))
            pb, ps = pam_rates(h, es / 2)
            ber, ser = pb, 1 - (1 - ps) ** 2
    elif mod == 'dpsk':
        M = int(num(args[2])) if len(args) > 2 else 2
        if M != 2:
            raise err('comm:berawgn:DPSK', 'DPSK error rates are given for M = 2 here.', 'berawgn')
        ber = ser = 0.5 * np.exp(-ebl)
    elif mod in ('fsk', 'msk'):
        if mod == 'msk':
            ber = ser = _q(np.sqrt(2 * ebl))
        else:
            M = int(num(args[2])) if len(args) > 2 else 2
            if M != 2:
                raise err('comm:berawgn:FSK', 'FSK error rates are given for M = 2 here.', 'berawgn')
            coh = 'coherent' in [py_str(a).lower() for a in args[3:] if is_str(a)]
            ber = ser = _q(np.sqrt(ebl)) if coh else 0.5 * np.exp(-ebl / 2)
    else:
        raise err('comm:berawgn:InvalidModulation', "The modulation is 'psk', 'qam', 'pam', 'dpsk', 'fsk' or 'msk'.", 'berawgn')
    ber, ser = np.asarray(ber).reshape(eb.shape), np.asarray(ser).reshape(eb.shape)
    return (out(ber), out(ser)) if nargout > 1 else out(ber)


# ---- filters and pictures -------------------------------------------------------------------------------------------------

@bi('rcosdesign')
def rcosdesign(nargout, *args):
    """b = rcosdesign(beta, span, sps, shape): a raised-cosine FIR filter of
    span symbols at sps samples a symbol, roll-off beta; shape 'sqrt' (root
    raised cosine, the default) or 'normal'; scaled to unit energy."""
    nargchk(args, 3, 4, 'rcosdesign')
    beta, span, sps = float(num(args[0])), int(num(args[1])), int(num(args[2]))
    shape = py_str(args[3]).lower() if len(args) > 3 else 'sqrt'
    if not 0 <= beta <= 1:
        raise err('comm:rcosdesign:InvalidBeta', 'beta is from 0 to 1.', 'rcosdesign')
    if span < 1 or sps < 1 or (span * sps) % 2:
        raise err('comm:rcosdesign:InvalidSpan', 'span and sps are whole numbers from 1 with an even product.', 'rcosdesign')
    if shape not in ('sqrt', 'normal'):
        raise err('comm:rcosdesign:InvalidShape', "The shape is 'sqrt' or 'normal'.", 'rcosdesign')
    n = span * sps
    t = (np.arange(n + 1) - n / 2) / sps
    b = np.empty(n + 1)
    eps = 1e-9
    for i, ti in enumerate(t):
        if shape == 'normal':
            if beta and abs(abs(ti) - 1 / (2 * beta)) < eps:
                b[i] = math.pi / 4 * np.sinc(1 / (2 * beta))
            else:
                b[i] = np.sinc(ti) * math.cos(math.pi * beta * ti) / (1 - (2 * beta * ti) ** 2)
        else:
            if abs(ti) < eps:
                b[i] = 1 - beta + 4 * beta / math.pi
            elif beta and abs(abs(ti) - 1 / (4 * beta)) < eps:
                b[i] = beta / math.sqrt(2) * ((1 + 2 / math.pi) * math.sin(math.pi / (4 * beta)) + (1 - 2 / math.pi) * math.cos(math.pi / (4 * beta)))
            else:
                b[i] = (math.sin(math.pi * ti * (1 - beta)) + 4 * beta * ti * math.cos(math.pi * ti * (1 + beta))) / (math.pi * ti * (1 - (4 * beta * ti) ** 2))
    b = b / math.sqrt(np.sum(b ** 2))
    return out(b.reshape(1, -1))


def _constellation_plot(pts, M, fn):
    b = lambda name, *a: R._builtin(name, *a)
    b('figure')
    b('plot', out(pts.real.reshape(-1, 1)), out(pts.imag.reshape(-1, 1)), Char.of('o'), Char.of('MarkerFaceColor'), Char.of('auto'))
    k = int(round(math.log2(M)))
    for i, p in enumerate(pts):
        b('text', float(p.real), float(p.imag) + 0.15 * max(1.0, float(np.abs(pts).max()) / 3), Char.of(format(i, f'0{k}b')),
          Char.of('HorizontalAlignment'), Char.of('center'))
    b('axis', Char.of('equal'))
    b('grid', Char.of('on'))
    b('title', Char.of(f'{M}-{fn[:3].upper()}'))
    b('xlabel', Char.of('In-Phase'))
    b('ylabel', Char.of('Quadrature'))


@bi('scatterplot', arr=False)
def scatterplot(nargout, *args):
    """h = scatterplot(x, n, offset, plotstring): the constellation of a
    signal: every n-th sample (1) from offset (0), quadrature against
    in-phase."""
    nargchk(args, 1, 5, 'scatterplot')
    x = np.asarray(darr(args[0]), complex).reshape(-1)
    n = int(num(args[1])) if len(args) > 1 and numel(args[1]) else 1
    off = int(num(args[2])) if len(args) > 2 and numel(args[2]) else 0
    ps = py_str(args[3]) if len(args) > 3 and is_str(args[3]) else 'b.'
    pts = x[off::n]
    b = lambda name, *a: R._builtin(name, *a)
    h = b('figure', args[4]) if len(args) > 4 else b('figure')
    if len(args) > 4:
        h = args[4]
    b('plot', out(pts.real.reshape(-1, 1)), out(pts.imag.reshape(-1, 1)), Char.of(ps))
    b('axis', Char.of('equal'))
    b('grid', Char.of('on'))
    b('title', Char.of('Scatter plot'))
    b('xlabel', Char.of('In-Phase'))
    b('ylabel', Char.of('Quadrature'))
    return h if nargout else None


@bi('eyediagram', arr=False)
def eyediagram(nargout, *args):
    """h = eyediagram(x, n, period, offset): the eye diagram of a signal:
    traces of n + 1 samples (a symbol at n samples each), from offset (0),
    laid over one another over -period/2 to period/2 (period 1); a complex
    signal draws its in-phase and quadrature parts apart."""
    nargchk(args, 2, 5, 'eyediagram')
    x = np.asarray(darr(args[0]), complex).reshape(-1)
    n = int(num(args[1]))
    period = float(num(args[2])) if len(args) > 2 and numel(args[2]) else 1.0
    off = int(num(args[3])) if len(args) > 3 and numel(args[3]) else 0
    if n < 2:
        raise err('comm:eyediagram:InvalidN', 'n is a whole number from 2.', 'eyediagram')
    seg = x[off:]
    m = (seg.size - 1) // n
    t = np.linspace(-period / 2, period / 2, n + 1).reshape(-1, 1)
    tr = np.column_stack([seg[k * n:k * n + n + 1] for k in range(m)]) if m else np.zeros((n + 1, 0), complex)
    b = lambda name, *a: R._builtin(name, *a)
    h = b('figure')
    parts = [('In-phase', tr.real)] + ([('Quadrature', tr.imag)] if np.any(x.imag != 0) else [])
    for i, (nm, P) in enumerate(parts):
        if len(parts) > 1:
            b('subplot', float(len(parts)), 1.0, float(i + 1))
        if P.shape[1]:
            b('plot', out(np.repeat(t, P.shape[1], axis=1)), out(P), Char.of('b'))
        b('title', Char.of(f'Eye Diagram for {nm} Signal'))
        b('xlabel', Char.of('Time'))
        b('ylabel', Char.of('Amplitude'))
        b('grid', Char.of('on'))
    return h if nargout else None
