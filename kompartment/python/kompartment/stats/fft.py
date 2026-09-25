"""The discrete Fourier transform, as Kompartment computes it.

A port of ``src/domain/fft.js``, for the spectral sensitivity methods: eFAST,
RBD-FAST and EASI read a variance off the power spectrum of the output taken
along a curve through the inputs, and Borgonovo's delta smooths densities by
convolving with a Gaussian in Fourier space. So all of them want ``rfft``, at
whatever length the reader asked for. A power of two is done radix-2, anything
else by Bluestein's algorithm, which is the same transform written as a
convolution of power-of-two length.

The arithmetic is the application's, butterfly for butterfly: the butterflies
of one stage are independent, so doing a stage's all at once with numpy gives
the same numbers as the JavaScript's loop over them. The twiddle factors come
from the platform's ``cos`` and ``sin``, which can differ from V8's in the last
bit, so the results agree to a few parts in 1e16 of the largest coefficient
rather than bit for bit.

The convention is FFTW's: the forward transform is unnormalised,
``F_k = sum_n y_n exp(-2 pi i k n / N)``, and :func:`irfft` divides by ``N``,
so the two are inverses. Arrays are numpy ``float64`` arrays; ``rfft`` returns
``{'re': ..., 'im': ...}`` as the application's does.
"""

from __future__ import annotations

import math
from typing import Dict, List, MutableSequence, Optional, Sequence, Tuple

import numpy as np

__all__ = ['fft', 'rfft', 'irfft', 'power_spectrum', 'dct2']

# The bit-reversal permutation, the twiddles of each stage and the butterfly
# positions depend on the length alone; they are worked out once per length.
# Caching them changes no number: the JavaScript recomputes the same values.
_BITREV: Dict[int, np.ndarray] = {}
_STAGES: Dict[Tuple[int, int], List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]] = {}
_CACHE_LIMIT = 64


def _is_pow2(n: int) -> bool:
    """Whether ``n`` is a power of two."""
    return n > 0 and (n & (n - 1)) == 0


def _bit_reversal(n: int) -> np.ndarray:
    """Where each element of a length-``n`` vector comes from after the swaps."""
    perm = _BITREV.get(n)
    if perm is None:
        p = list(range(n))
        j = 0
        for i in range(1, n):
            bit = n >> 1
            while j & bit:
                j ^= bit
                bit >>= 1
            j ^= bit
            if i < j:
                p[i], p[j] = p[j], p[i]
        perm = np.array(p, dtype=np.intp)
        if len(_BITREV) > _CACHE_LIMIT:
            _BITREV.clear()
        _BITREV[n] = perm
    return perm


def _stages(n: int, sign: int) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Per stage: the butterflies' two positions and their twiddles."""
    key = (n, sign)
    out = _STAGES.get(key)
    if out is None:
        out = []
        length = 2
        while length <= n:
            half = length >> 1
            # The twiddles from a table computed per stage, as the JavaScript
            # computes them: cos(step * k) for each k, not by recurrence.
            step = (sign * 2 * math.pi) / length
            k = np.arange(half, dtype=np.float64)
            wr = np.cos(step * k)
            wi = np.sin(step * k)
            starts = np.arange(0, n, length)
            a = (starts[:, None] + np.arange(half)[None, :]).ravel()
            b = a + half
            groups = n // length
            out.append((a, b, np.tile(wr, groups), np.tile(wi, groups)))
            length <<= 1
        if len(_STAGES) > _CACHE_LIMIT:
            _STAGES.clear()
        _STAGES[key] = out
    return out


def _radix2(re: np.ndarray, im: np.ndarray, sign: int) -> Tuple[np.ndarray, np.ndarray]:
    """Radix-2 decimation in time of a power-of-two length; new arrays."""
    n = len(re)
    perm = _bit_reversal(n)
    re = re[perm]
    im = im[perm]
    for a, b, wr, wi in _stages(n, sign):
        ra = re[a]
        ia = im[a]
        rb = re[b]
        ib = im[b]
        xr = rb * wr - ib * wi
        xi = rb * wi + ib * wr
        re[b] = ra - xr
        im[b] = ia - xi
        re[a] = ra + xr
        im[a] = ia + xi
    return re, im


def _bluestein(re: np.ndarray, im: np.ndarray, sign: int) -> Tuple[np.ndarray, np.ndarray]:
    """The transform of any length as a convolution with a chirp; new arrays."""
    n = len(re)
    m = 1
    while m < 2 * n - 1:
        m <<= 1
    # The chirp's angle from k^2 mod 2n, exactly, so it stays right for large n.
    k = np.arange(n, dtype=np.int64)
    q = ((k * k) % (2 * n)).astype(np.float64)
    ang = (sign * math.pi) * q / n
    cr = np.cos(ang)
    ci = np.sin(ang)
    ar = np.zeros(m)
    ai = np.zeros(m)
    ar[:n] = re * cr - im * ci
    ai[:n] = re * ci + im * cr
    br = np.zeros(m)
    bi = np.zeros(m)
    br[0] = cr[0]
    bi[0] = -ci[0]
    if n > 1:
        br[1:n] = cr[1:]
        bi[1:n] = -ci[1:]
        br[m - n + 1:] = cr[1:][::-1]
        bi[m - n + 1:] = -ci[1:][::-1]
    ar, ai = _radix2(ar, ai, -1)
    br, bi = _radix2(br, bi, -1)
    r = ar * br - ai * bi
    ai = ar * bi + ai * br
    ar = r
    ar, ai = _radix2(ar, ai, 1)
    rr = ar[:n] / m
    ii = ai[:n] / m
    return rr * cr - ii * ci, rr * ci + ii * cr


def _transform(re: np.ndarray, im: np.ndarray, sign: int) -> Tuple[np.ndarray, np.ndarray]:
    if len(re) <= 1:
        return re, im
    with np.errstate(all='ignore'):
        if _is_pow2(len(re)):
            return _radix2(re, im, sign)
        return _bluestein(re, im, sign)


def fft(re: MutableSequence[float], im: MutableSequence[float], sign: int = -1) -> None:
    """The complex transform of ``re + i im``, in place.

    ``sign`` -1 is the forward transform, +1 the inverse without its 1/N. The
    two sequences are overwritten with the result, as the application's
    ``fft`` overwrites its typed arrays; they may be numpy arrays or lists.
    """
    r = np.array(re, dtype=np.float64)
    i = np.array(im, dtype=np.float64)
    if len(r) <= 1:
        return
    r, i = _transform(r, i, sign)
    re[:] = r
    im[:] = i


def rfft(y: Sequence[float]) -> Dict[str, np.ndarray]:
    """The transform of a real sequence: its ``floor(N/2) + 1`` coefficients from zero frequency up.

    Returns ``{'re': ..., 'im': ...}``, as FFTW's ``rfft`` orders them.
    """
    re = np.array(y, dtype=np.float64)
    n = len(re)
    im = np.zeros(n)
    re, im = _transform(re, im, -1)
    h = n // 2 + 1
    return {'re': re[:h].copy(), 'im': im[:h].copy()}


def _padded(a: Sequence[float], length: int) -> np.ndarray:
    """The first ``length`` of ``a``, NaN past its end as a typed array reads there."""
    v = np.asarray(a, dtype=np.float64)
    out = np.full(length, math.nan)
    t = min(length, len(v))
    out[:t] = v[:t]
    return out


def irfft(half: Dict[str, Sequence[float]], n: int) -> np.ndarray:
    """The inverse of :func:`rfft` for a sequence of length ``n``, divided by ``n``.

    ``half`` holds the ``floor(n/2) + 1`` coefficients as ``{'re': ..., 'im': ...}``.
    The zero-frequency term, and the Nyquist one of an even length, are read as
    real whatever rounding left in them, as FFTW's c2r transform reads them.
    """
    n = int(n)
    if n <= 0:
        return np.zeros(0)
    h = n // 2 + 1
    hre = _padded(half['re'], h)
    him = _padded(half['im'], h)
    re = np.zeros(n)
    im = np.zeros(n)
    re[:h] = hre
    im[:h] = him
    im[0] = 0.0
    if n % 2 == 0:
        im[n // 2] = 0.0
    # The rest from Hermitian symmetry.
    src = n - np.arange(h, n)
    re[h:] = hre[src]
    im[h:] = -him[src]
    re, im = _transform(re, im, 1)
    with np.errstate(all='ignore'):
        return re / n


def power_spectrum(y: Sequence[float]) -> np.ndarray:
    """``|F_k|^2`` of ``rfft(y)``, for the spectral methods."""
    f = rfft(y)
    return f['re'] * f['re'] + f['im'] * f['im']


def dct2(y: Sequence[float], up_to: Optional[int] = None) -> np.ndarray:
    """The orthonormal DCT-II, FFTW's ``dct``, for the first ``up_to`` coefficients.

    ``X_k = w_k sum_n y_n cos(pi k (2n + 1) / 2N)``, with ``w_0 = sqrt(1/N)``
    and ``w_k = sqrt(2/N)``. EASI reads a handful of them and the sum of the
    rest, which is the sum of squares by Parseval.
    """
    v = np.asarray(y, dtype=np.float64)
    n = len(v)
    if up_to is None:
        m = n
    else:
        want = float(up_to)
        # Math.min(n, NaN) is NaN, and a typed array of NaN length is empty.
        m = 0 if math.isnan(want) else n if want >= n else int(want)
        if m < 0:
            raise ValueError('Invalid typed array length: %d' % m)
    out = np.zeros(m)
    odd = 2.0 * np.arange(n) + 1.0
    for k in range(m):
        terms = v * np.cos((math.pi * k) * odd / (2 * n))
        s = float(np.cumsum(terms)[-1]) if n else 0.0
        out[k] = s * math.sqrt((1 if k == 0 else 2) / n)
    return out
