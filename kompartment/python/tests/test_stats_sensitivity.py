"""Kompartment's sensitivity analysis in Python, against the application's own.

Every public function of ``kompartment.stats.fft``, ``sensitivity``,
``categories``, ``gsa`` and ``salib`` is run beside the application's
(``tests/node/stats_sensitivity.mjs``) on made-up samples -- several sizes and
distributions, ties, constant columns, failed realisations, masks -- and every
design and estimator the application offers. Then the checks the application's
own tests make against GlobalSensitivity.jl 2.12.8 and SALib 1.6.0
(``test/fixtures/gsa-reference.json``, ``salib-reference.json``), the FFT
against the DFT, and the known answers of the designed methods.

What the application computes with ``+ - * /`` and square roots comes out bit
for bit; ``exp``, ``log``, ``sin``, ``cos``, ``asin`` and ``pow`` of the
platform can differ from V8's in the last bit, so floats are compared to a
relative 1e-12 unless a comment says why an estimator needs more. Integers --
designs, orderings, ranks, counts -- must match exactly. The largest relative
difference seen in each area is printed at the end.
"""

from __future__ import annotations

import base64
import json
import math
import subprocess
import sys
import unittest
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from helpers import HERE, NODE, SRC, needs_app

from kompartment.stats import categories as C
from kompartment.stats import fft as F
from kompartment.stats import gsa as G
from kompartment.stats import salib as SL
from kompartment.stats import sensitivity as S

FIXTURES = SRC.parent / 'test' / 'fixtures'
needs_fixtures = unittest.skipUnless((FIXTURES / 'gsa-reference.json').is_file(), 'needs the reference fixtures')

# ---------------------------------------------------------------------------
# The bridge to the application's code.
# ---------------------------------------------------------------------------


class _Undefined:
    def __repr__(self) -> str:
        return 'undefined'


UNDEFINED = _Undefined()
_NUMS = {'NaN': math.nan, 'Infinity': math.inf, '-Infinity': -math.inf, '-0': -0.0}


def f64(a: Any) -> Dict[str, str]:
    """A Float64Array argument."""
    return {'$f64': base64.b64encode(np.ascontiguousarray(a, dtype='<f8').tobytes()).decode('ascii')}


def i32(a: Any) -> Dict[str, List[int]]:
    return {'$i32': [int(v) for v in a]}


def u8(a: Any) -> Dict[str, List[int]]:
    return {'$u8': [int(v) for v in a]}


def num(x: float) -> Any:
    """A number argument, tagged when JSON cannot carry it."""
    x = float(x)
    if math.isnan(x):
        return {'$num': 'NaN'}
    if math.isinf(x):
        return {'$num': 'Infinity' if x > 0 else '-Infinity'}
    if x == 0 and math.copysign(1, x) < 0:
        return {'$num': '-0'}
    return x


def enc(v: Any) -> Any:
    """A Python value as an argument: numpy float arrays become Float64Arrays."""
    if isinstance(v, np.ndarray):
        if v.dtype.kind == 'f':
            if v.ndim == 2:
                return [f64(row) for row in v]
            return f64(v)
        return [enc(x) for x in v.tolist()]
    if isinstance(v, float):
        return num(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (list, tuple)):
        return [enc(x) for x in v]
    if isinstance(v, dict):
        return {k: enc(x) for k, x in v.items()}
    return v


def dec(v: Any) -> Any:
    """The application's answer as Python values: typed arrays as numpy arrays."""
    if isinstance(v, list):
        return [dec(x) for x in v]
    if not isinstance(v, dict):
        return v
    if '$f64' in v:
        return np.frombuffer(base64.b64decode(v['$f64']), dtype='<f8').copy()
    for tag, dtype in (('$i32', np.int32), ('$u8', np.uint8), ('$u16', np.uint16), ('$i8', np.int8)):
        if tag in v:
            return np.array(v[tag], dtype=dtype)
    if '$num' in v:
        return _NUMS[v['$num']]
    if '$undefined' in v:
        return UNDEFINED
    return {k: dec(x) for k, x in v.items()}


def js(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Runs the calls through the application's code, in one Node process."""
    assert NODE is not None
    proc = subprocess.run([NODE, str(HERE / 'node' / 'stats_sensitivity.mjs'), str(SRC)],
                          input=json.dumps({'calls': calls}), capture_output=True, text=True,
                          timeout=900, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)['results']


def call(module: str, fn: str, *args: Any, **extra: Any) -> Dict[str, Any]:
    return {'module': module, 'fn': fn, 'args': [enc(a) for a in args], **extra}


def const(module: str, name: str) -> Dict[str, Any]:
    return {'module': module, 'fn': name}


# ---------------------------------------------------------------------------
# Comparing, and keeping the worst difference of each area for the summary.
# ---------------------------------------------------------------------------

WORST: Dict[str, Any] = {}
COMPARED: Dict[str, int] = {}
IDENTICAL: Dict[str, int] = {}


def _is_int(v: Any) -> bool:
    return isinstance(v, (int, np.integer)) and not isinstance(v, (bool, np.bool_))


def _note(area: str, a: float, b: float, path: str = '', atol: float = 0.0) -> None:
    """Counts a comparison, and keeps the area's worst relative difference above the absolute floor.

    Below ``atol`` a number is rounding noise of something much larger, and its relative
    difference means nothing; it is compared to the floor instead and not ranked here.
    """
    COMPARED[area] = COMPARED.get(area, 0) + 1
    same = a == b or (math.isnan(a) and math.isnan(b))
    if same:
        IDENTICAL[area] = IDENTICAL.get(area, 0) + 1
        rel = 0.0
    elif math.isinf(a) or math.isinf(b) or math.isnan(a) or math.isnan(b) or max(abs(a), abs(b)) <= atol:
        return
    else:
        rel = abs(a - b) / max(abs(a), abs(b))
    if rel >= WORST.get(area, (0.0, ''))[0]:
        WORST[area] = (rel, path) if rel > 0 or area not in WORST else WORST[area]


def _close(a: float, b: float, rtol: float, atol: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if math.isinf(a) or math.isinf(b):
        return a == b
    return abs(a - b) <= max(rtol * max(abs(a), abs(b)), atol)


def compare(got: Any, want: Any, *, area: str, rtol: float = 1e-12, atol: float = 0.0, path: str = '',
            out: Optional[List[str]] = None) -> List[str]:
    """Where a Python result differs from the application's, as readable lines."""
    out = [] if out is None else out
    if want is UNDEFINED:
        if not (got is None or got is UNDEFINED or (isinstance(got, float) and math.isnan(got))):
            out.append(f'{path}: {got!r} where the application has undefined')
        return out
    if isinstance(want, dict):
        if not isinstance(got, dict):
            out.append(f'{path}: {type(got).__name__} where the application has an object')
            return out
        if set(got) != set(want):
            out.append(f'{path}: keys {sorted(got)} != {sorted(want)}')
        for k in want:
            if k in got:
                compare(got[k], want[k], area=area, rtol=rtol, atol=atol, path=f'{path}/{k}', out=out)
        return out
    if isinstance(want, np.ndarray) and want.dtype.kind in 'iu':
        g = np.asarray(got)
        if g.shape != want.shape or (g.size and not np.all(np.asarray(got, dtype=float) == want)):
            out.append(f'{path}: {g.tolist()!r:.200} != {want.tolist()!r:.200} (integers, exactly)')
        elif g.size and g.dtype.kind == 'f' and not np.all(np.floor(g) == g):
            out.append(f'{path}: not integers')
        return out
    if isinstance(want, (list, np.ndarray)):
        g = got
        if isinstance(g, np.ndarray) and g.ndim == 0:
            g = [g.item()]
        if not hasattr(g, '__len__') or isinstance(g, (str, dict)):
            out.append(f'{path}: {got!r:.80} where the application has a list')
            return out
        if len(g) != len(want):
            out.append(f'{path}: {len(g)} items != {len(want)}')
            return out
        if isinstance(want, np.ndarray):
            ga = np.asarray(g, dtype=float)
            if ga.shape != want.shape:
                out.append(f'{path}: shape {ga.shape} != {want.shape}')
                return out
            for i, (a, b) in enumerate(zip(ga.tolist(), want.tolist())):
                _note(area, a, b, f'{path}[{i}]', atol)
                if not _close(a, b, rtol, atol):
                    out.append(f'{path}[{i}]: {a!r} != {b!r}')
                    if len(out) > 20:
                        return out
            return out
        for i, (a, b) in enumerate(zip(g, want)):
            compare(a, b, area=area, rtol=rtol, atol=atol, path=f'{path}[{i}]', out=out)
        return out
    if isinstance(want, bool) or isinstance(got, (bool, np.bool_)):
        if bool(got) is not bool(want) or not isinstance(got, (bool, np.bool_)):
            out.append(f'{path}: {got!r} != {want!r}')
        return out
    if isinstance(want, (int, float)):
        if not isinstance(got, (int, float, np.integer, np.floating)) or isinstance(got, bool):
            out.append(f'{path}: {got!r:.80} where the application has {want!r}')
            return out
        if _is_int(got) and _is_int(want):
            if int(got) != int(want):
                out.append(f'{path}: {got} != {want} (integers, exactly)')
            return out
        _note(area, float(got), float(want), path, atol)
        if not _close(float(got), float(want), rtol, atol):
            out.append(f'{path}: {got!r} != {want!r}')
        return out
    if got != want:
        out.append(f'{path}: {got!r:.120} != {want!r:.120}')
    return out


class Case:
    """One comparison: a Python computation and the application's call that should give the same."""

    def __init__(self, name: str, py: Callable[[], Any], js_call: Dict[str, Any], *, rtol: float = 1e-12,
                 atol: float = 0.0, view: Optional[Callable[[Any], Any]] = None) -> None:
        self.name = name
        self.py = py
        self.call = js_call
        self.rtol = rtol
        self.atol = atol
        self.view = view


def run_cases(test: unittest.TestCase, area: str, cases: List[Case]) -> None:
    """Runs every case's call in one Node process and compares each answer with Python's."""
    results = js([c.call for c in cases])
    for c, r in zip(cases, results):
        with test.subTest(c.name):
            if 'error' in r:
                with test.assertRaises(Exception, msg=f'{c.name}: the application refuses ({r["error"]})'):
                    c.py()
                continue
            want = dec(r['value'])
            got = c.py()
            if c.view is not None:
                got, want = c.view(got), c.view(want)
            problems = compare(got, want, area=area, rtol=c.rtol, atol=c.atol, path=c.name)
            test.assertFalse(problems, '\n'.join(problems[:20]))


def tearDownModule() -> None:  # noqa: N802 - unittest's name
    if COMPARED:
        lines = ['', 'largest relative difference from the reference, by area (numbers compared, identical):']
        for area in sorted(COMPARED):
            rel, where = WORST.get(area, (0.0, ''))
            lines.append(f'  {area:13s} {rel:9.3g}  ({COMPARED[area]}, {IDENTICAL.get(area, 0)})  {where}')
        print('\n'.join(lines), file=sys.stderr)


# ---------------------------------------------------------------------------
# Random streams: the test suite's congruential generator, and a port of
# src/domain/sample.js's streams for the designs drawn from a seed (the
# application's own are checked against it below).
# ---------------------------------------------------------------------------


def lcg(seed: int = 0) -> Callable[[], float]:
    """``n = (n * 9301 + 49297) % 233280``, as ``{ $lcg: seed }`` in the Node script."""
    state = [seed]

    def nxt() -> float:
        state[0] = (state[0] * 9301 + 49297) % 233280
        return state[0] / 233280

    return nxt


_M32 = 0xFFFFFFFF


def _hash(text: str) -> int:
    h = 2166136261
    units = text.encode('utf-16-le')
    for i in range(0, len(units), 2):
        h = ((h ^ (units[i] | units[i + 1] << 8)) * 16777619) & _M32
    return h


def _mix(a: int, b: int) -> int:
    h = (a ^ (((b ^ (b >> 16)) * 2246822507) & _M32)) & _M32
    h = (((h ^ (h >> 13)) * 3266489909) & _M32)
    return (h ^ (h >> 16)) & _M32


def rng(seed: int = 1) -> Callable[[], float]:
    state = [(int(seed) & _M32) or 1]

    def nxt() -> float:
        a = (state[0] + 0x6D2B79F5) & _M32
        state[0] = a
        t = (((a ^ (a >> 15)) * (a | 1)) & _M32)
        t = (t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & _M32)) & _M32)) & _M32
        return ((t ^ (t >> 14)) & _M32) / 4294967296

    return nxt


def stream_for(seed: int, name: str) -> Callable[[], float]:
    return rng(_mix(int(seed) & _M32, _hash(str(name))))


def uniforms(n: int, nxt: Callable[[], float], latin: bool = True) -> np.ndarray:
    if not latin:
        return np.array([nxt() for _ in range(n)], dtype=np.float64)
    out = [(i + nxt()) / n for i in range(n)]
    for i in range(n - 1, 0, -1):
        j = math.floor(nxt() * (i + 1))
        out[i], out[j] = out[j], out[i]
    return np.array(out, dtype=np.float64)


STREAMS = {'stream_for': stream_for, 'uniforms': uniforms}

# ---------------------------------------------------------------------------
# Made-up data.
# ---------------------------------------------------------------------------


def sample_columns(n: int, seed: int) -> List[np.ndarray]:
    """Inputs of several distributions: uniform, normal, log-normal, a few values with ties, a constant."""
    r = np.random.default_rng(seed)
    return [
        r.uniform(0, 1, n),
        r.normal(3, 2, n),
        np.exp(r.normal(0, 1.5, n)),
        r.integers(0, 4, n).astype(float),
        np.full(n, 2.5),
    ]


def outputs_of(cols: List[np.ndarray], seed: int, times: int) -> np.ndarray:
    """A realisation-major output over ``times`` times, bent, with ties at the start."""
    r = np.random.default_rng(seed)
    n = len(cols[0])
    out = np.zeros((n, times))
    for j in range(times):
        w = j / max(1, times - 1)
        out[:, j] = (1 - w) * cols[0] ** 2 + w * np.log1p(cols[2]) * cols[1] + 0.1 * r.normal(size=n)
    out[:, 0] = np.round(out[:, 0], 1)
    return out.ravel()


def ishigami_u(u: np.ndarray) -> np.ndarray:
    """Ishigami on [-pi, pi]^3 of a K x runs design's probabilities."""
    x = -math.pi + 2 * math.pi * u
    return np.sin(x[0]) + 7 * np.sin(x[1]) ** 2 + 0.1 * x[2] ** 4 * np.sin(x[0])


def design_outputs(u: np.ndarray, f: Callable[[List[float]], float]) -> np.ndarray:
    return np.array([f(list(u[:, i])) for i in range(u.shape[1])], dtype=np.float64)


def _without_noise_column(r: Any) -> Any:
    """A regression's answer without input 4, the constant column that logarithms turn into rounding noise."""
    r = dict(r)
    for key in ('src', 'b', 'pcc'):
        r[key] = np.delete(np.asarray(r[key], dtype=float), 4)
    return r


# ---------------------------------------------------------------------------
# The FFT.
# ---------------------------------------------------------------------------


@needs_app
class FFTParity(unittest.TestCase):
    """The transforms at powers of two and at every other length, as the application computes them."""

    def test_transforms(self):
        r = np.random.default_rng(11)
        cases = []
        for n in (0, 1, 2, 3, 5, 8, 16, 17, 100, 257, 1000, 1024, 2048):
            x = r.normal(size=n) * 10 ** r.uniform(-3, 3)
            # The twiddle factors come from the platform's cos and sin, which differ from V8's in the
            # last bit, so a coefficient is good to a few parts in 1e16 of the largest, not of itself.
            scale = 1e-13 * (float(np.abs(x).sum()) + 1e-300)
            cases.append(Case(f'rfft {n}', lambda x=x: F.rfft(x), call('fft', 'rfft', x), atol=scale))
            half = F.rfft(x)
            cases.append(Case(f'irfft {n}', lambda h=half, n=n: F.irfft(h, n),
                              call('fft', 'irfft', half, n), atol=1e-13 * (float(np.abs(x).max()) if n else 1)))
            cases.append(Case(f'power {n}', lambda x=x: F.power_spectrum(x), call('fft', 'powerSpectrum', x),
                              atol=scale * (float(np.abs(x).sum()) + 1e-300)))
            cases.append(Case(f'dct2 {n}', lambda x=x: F.dct2(x), call('fft', 'dct2', x), atol=scale))
            cases.append(Case(f'dct2 {n} up to 3', lambda x=x: F.dct2(x, 3), call('fft', 'dct2', x, 3), atol=scale))
            im = r.normal(size=n)

            def complex_fft(x=x, im=im, sign=-1):
                re_ = x.copy()
                im_ = im.copy()
                F.fft(re_, im_, sign)
                return {'value': UNDEFINED, 'args': [re_, im_]}

            for sign in (-1, 1):
                cases.append(Case(f'fft {n} {sign}', lambda f=complex_fft, s=sign: f(sign=s),
                                  call('fft', 'fft', x, im, sign, returnArgs=[0, 1]),
                                  atol=1e-13 * (float(np.abs(x).sum() + np.abs(im).sum()) + 1e-300)))
        # A half-spectrum shorter than the length asks for: the rest reads as NaN, as a typed array's end does.
        short = {'re': np.array([1.0, 2.0]), 'im': np.array([0.0, 1.0])}
        cases.append(Case('irfft short', lambda: F.irfft(short, 6), call('fft', 'irfft', short, 6)))
        run_cases(self, 'fft', cases)


# ---------------------------------------------------------------------------
# sensitivity.js
# ---------------------------------------------------------------------------


@needs_app
class SensitivityParity(unittest.TestCase):
    """The correlations, the regression family, the straight line and S1, on made-up samples."""

    def test_correlations(self):
        cases = []
        for n, seed in ((5, 1), (37, 2), (200, 3), (1000, 4)):
            cols = sample_columns(n, seed)
            r = np.random.default_rng(seed + 100)
            y = cols[0] * 2 + cols[1] + r.normal(size=n)
            y_ties = np.round(y)
            y_bad = y.copy()
            y_bad[::7] = np.nan
            y_bad[3 % n] = np.inf
            for k, x in enumerate(cols):
                for tag, yy in (('y', y), ('ties', y_ties), ('failed', y_bad)):
                    cases.append(Case(f'pearson {n} {k} {tag}', lambda x=x, yy=yy: S.pearson(x, yy),
                                      call('sensitivity', 'pearson', x, yy)))
                    cases.append(Case(f'spearman {n} {k} {tag}', lambda x=x, yy=yy: S.spearman(x, yy),
                                      call('sensitivity', 'spearman', x, yy)))
                cases.append(Case(f'rank {n} {k}', lambda x=x: S.rank(x), call('sensitivity', 'rank', x)))
            cases.append(Case(f'rank failed {n}', lambda yy=y_bad: S.rank(yy), call('sensitivity', 'rank', y_bad)))
            m = max(1, n // 2)
            cases.append(Case(f'pearson {n} first half', lambda y=y, x=cols[0], m=m: S.pearson(x, y, m),
                              call('sensitivity', 'pearson', cols[0], y, m)))
            cases.append(Case(f'rank {n} past the end', lambda y=y, n=n: S.rank(y, n + 3),
                              call('sensitivity', 'rank', y, n + 3)))
            cases.append(Case(f'spearman {n} first half', lambda y=y, x=cols[1], m=m: S.spearman(x, y, m),
                              call('sensitivity', 'spearman', cols[1], y, m)))
        cases.append(Case('scratchFor', lambda: S.scratch_for(7), call('sensitivity', 'scratchFor', 7)))
        cases.append(Case('rank ties', lambda: S.rank([10, 20, 20, 40]), call('sensitivity', 'rank', [10, 20, 20, 40])))
        cases.append(Case('pearson short', lambda: S.pearson([1, 2], [3, 4]),
                          call('sensitivity', 'pearson', [1, 2], [3, 4])))
        run_cases(self, 'sensitivity', cases)

    def test_at_time_ranked_over_time(self):
        cases = []
        for n, seed, times in ((6, 5, 3), (60, 6, 5), (400, 7, 12)):
            cols = sample_columns(n, seed)
            values = outputs_of(cols, seed, times)
            mask = (np.random.default_rng(seed).uniform(size=n) > 0.3).astype(np.uint8)
            values_bad = values.copy()
            values_bad[::11] = np.nan
            for at in (0, times // 2, times - 1, times + 4, -1):
                for tag, mk in (('all', None), ('masked', mask)):
                    cases.append(Case(f'atTime {n} {at} {tag}',
                                      lambda cols=cols, values=values, times=times, n=n, at=at, mk=mk:
                                      S.at_time(cols, values, times, n, at, None, mk),
                                      call('sensitivity', 'atTime', cols, values, times, n, at, None,
                                           None if mk is None else u8(mk))))
            for most in (20, 2, -1, 0):
                cases.append(Case(f'ranked {n} most {most}',
                                  lambda cols=cols, values=values_bad, times=times, n=n, most=most:
                                  S.ranked(cols, values, times, n, times - 1, most=most),
                                  call('sensitivity', 'ranked', cols, values_bad, times, n, times - 1, {'most': most})))
            cases.append(Case(f'ranked {n} masked',
                              lambda cols=cols, values=values, times=times, n=n, mask=mask:
                              S.ranked(cols, values, times, n, 1, mask=mask),
                              call('sensitivity', 'ranked', cols, values, times, n, 1, {'mask': u8(mask)})))
            for k in range(len(cols)):
                for rank_based in (True, False):
                    for tag, mk in (('all', None), ('masked', mask)):
                        opts = {'rankBased': rank_based}
                        if mk is not None:
                            opts['mask'] = u8(mk)
                        cases.append(Case(f'overTime {n} {k} {rank_based} {tag}',
                                          lambda x=cols[k], values=values_bad, times=times, n=n, rb=rank_based, mk=mk:
                                          S.over_time(x, values, times, n, rank_based=rb, mask=mk),
                                          call('sensitivity', 'overTime', cols[k], values_bad, times, n, opts)))
        run_cases(self, 'sensitivity', cases)

    def test_regression_family(self):
        cases = []
        for n, seed in ((5, 8), (12, 9), (300, 10), (2000, 11)):
            cols = sample_columns(n, seed)
            r = np.random.default_rng(seed)
            y = 3 * cols[0] + 0.5 * cols[1] + np.log(cols[2]) + 0.05 * r.normal(size=n)
            y_pos = np.exp(y / 4)
            mask = (r.uniform(size=n) > 0.25).astype(np.uint8)
            with_zero = cols[2].copy()
            with_zero[: max(1, n // 10)] = 0.0
            sets = {
                'all': cols,
                'varying': cols[:4],
                'duplicate': [cols[0], cols[0].copy(), cols[1]],
                'zeros': [with_zero, cols[0]],
            }
            for sname, samples in sets.items():
                for translate in ('none', 'rank', 'log'):
                    for yname, yy in (('y', y), ('positive', y_pos)):
                        # On logarithms the platform's log and V8's differ in the last bit in a few per cent of
                        # the values, and a regression amplifies that by its conditioning: 1e-10 there.
                        tol = 1e-10 if translate == 'log' else 1e-12
                        noise = translate == 'log' and sname == 'all'
                        cases.append(Case(f'regression {n} {sname} {translate} {yname}',
                                          lambda s=samples, yy=yy, t=translate: S.regression_measures(s, yy,
                                                                                                      translate=t),
                                          call('sensitivity', 'regressionMeasures', samples, yy,
                                               {'translate': translate}),
                                          rtol=tol, view=_without_noise_column if noise else None))
                cases.append(Case(f'regression {n} {sname} masked',
                                  lambda s=samples, yy=y, mask=mask: S.regression_measures(s, yy, mask=mask),
                                  call('sensitivity', 'regressionMeasures', samples, y, {'mask': u8(mask)})))
            mono = np.exp(-5 * cols[0])
            cases.append(Case(f'regression {n} perfect rank',
                              lambda c=cols, mono=mono: S.regression_measures([c[0], c[3]], mono, translate='rank'),
                              call('sensitivity', 'regressionMeasures', [cols[0], cols[3]], mono,
                                   {'translate': 'rank'})))
            for translate in ('none', 'log'):
                tol = 1e-10 if translate == 'log' else 1e-12
                for k in range(len(cols) - (translate == 'log')):  # the constant column on logs: see above
                    cases.append(Case(f'lineFit {n} {k} {translate}',
                                      lambda x=cols[k], yy=y_pos, t=translate: S.line_fit(x, yy, translate=t),
                                      call('sensitivity', 'lineFit', cols[k], y_pos, {'translate': translate}),
                                      rtol=tol))
                cases.append(Case(f'lineFit {n} zeros {translate}',
                                  lambda x=with_zero, yy=y_pos, t=translate, mask=mask: S.line_fit(x, yy, translate=t,
                                                                                                   mask=mask),
                                  call('sensitivity', 'lineFit', with_zero, y_pos,
                                       {'translate': translate, 'mask': u8(mask)}),
                                  rtol=tol))
            yq = (cols[0] - 0.5) ** 2
            for k in range(len(cols)):
                for bins in (None, 7, 0):
                    opts = {} if bins is None else {'bins': bins}
                    cases.append(Case(f'S1 {n} {k} bins {bins}',
                                      lambda x=cols[k], yq=yq, b=bins: S.first_order_index(x, yq, bins=b),
                                      call('sensitivity', 'firstOrderIndex', cols[k], yq, opts)))
                cases.append(Case(f'S1 {n} {k} masked',
                                  lambda x=cols[k], yy=y, mask=mask: S.first_order_index(x, yy, mask=mask),
                                  call('sensitivity', 'firstOrderIndex', cols[k], y, {'mask': u8(mask)})))
        run_cases(self, 'sensitivity', cases)


# ---------------------------------------------------------------------------
# categories.js
# ---------------------------------------------------------------------------


@needs_app
class CategoriesParity(unittest.TestCase):
    """Reading, checking, classifying and describing categories of realisation."""

    RAW = [
        {'label': 'high peak', 'output': 'Dose', 'stat': 'max', 'op': '>', 'value': 4},
        {'label': 'ends low', 'output': 'Dose', 'stat': 'final', 'op': '<=', 'value': 1, 'include': False},
        {'label': 'mid', 'output': 'Dose', 'stat': 'at', 'at': 1, 'op': 'between', 'value': 3, 'value2': 0.5},
        {'output': 'Other', 'stat': 'min', 'op': '>=', 'value': '2', 'include': 0},
        {'label': 7, 'output': 'Gone', 'stat': 'nonsense', 'op': '!=', 'value': None, 'at': 2.5},
        {'label': '', 'output': '', 'stat': 'at', 'at': 1.0, 'op': 'between', 'value': ' 0x10 ', 'value2': [5]},
        {'label': [1, None, 'x'], 'output': {'a': 1}, 'op': '<', 'value': True, 'value2': '1e3'},
        {'label': 'strings', 'output': 'Dose', 'value': 'Infinity', 'value2': 'infinity'},
        None, 5, 'text', [],
    ]

    def test_reading_and_checking(self):
        project = {'simulation': {'categories': self.RAW}}
        cases = [
            Case('categoriesOf', lambda: C.categories_of(project), call('categories', 'categoriesOf', project)),
            Case('categoriesOf none', lambda: C.categories_of({}), call('categories', 'categoriesOf', {})),
            Case('categoriesOf not a list', lambda: C.categories_of({'simulation': {'categories': {'a': 1}}}),
                 call('categories', 'categoriesOf', {'simulation': {'categories': {'a': 1}}})),
            Case('STATS', lambda: C.STATS, const('categories', 'STATS')),
            Case('STAT_LABEL', lambda: C.STAT_LABEL, const('categories', 'STAT_LABEL')),
            Case('OPS', lambda: C.OPS, const('categories', 'OPS')),
        ]
        cats = C.categories_of(project)
        for labels in (None, ['Dose'], []):
            cases.append(Case(f'categoryProblems {labels}', lambda labels=labels: C.category_problems(cats, labels),
                              call('categories', 'categoryProblems', cats, labels)))
        for c in cats:
            cases.append(Case(f'describe {c["label"]}', lambda c=c: C.describe_category(c),
                              call('categories', 'describeCategory', c)))
        raw_described = {'output': 'D', 'stat': 'at', 'at': '2', 'op': '>', 'value': 1e-7}
        cases.append(Case('describe raw', lambda: C.describe_category(raw_described),
                          call('categories', 'describeCategory', raw_described)))
        run_cases(self, 'categories', cases)

    def test_statistics_and_classes(self):
        r = np.random.default_rng(21)
        times, iterations = 4, 30
        dose = r.normal(2, 2, times * iterations)
        dose[5] = np.nan
        dose[9] = np.inf
        other = r.uniform(0, 5, times * iterations)
        values = [dose, other, r.uniform(0, 5, iterations)]
        outputs = [{'label': 'Dose'}, {'label': 'Other'}, {'label': 'Param'}]
        cases = []
        for i in (0, 1, 2, 29, 30, -1):
            for stat in ('final', 'max', 'min', 'at', 'other'):
                for at in (0, 2, 7, -3, 1.5, math.nan, None):
                    cases.append(Case(f'statisticOf {i} {stat} {at}',
                                      lambda i=i, stat=stat, at=at: C.statistic_of(dose, times, i, stat, at),
                                      call('categories', 'statisticOf', dose, times, i, stat, at)))
        cats = C.categories_of({'simulation': {'categories': self.RAW[:8] + [
            {'label': 'param', 'output': 'Param', 'stat': 'final', 'op': '>', 'value': 2.5}]}})
        for run in (
            {'outputs': outputs, 'values': values, 't': np.zeros(times), 'iterations': iterations},
            {'outputs': outputs, 'values': values, 'times': times, 'iterations': iterations,
             'flat': [False, False, True]},
            {'outputs': outputs, 'values': values, 'iterations': iterations},
        ):
            cases.append(Case(f'classify {sorted(run)}', lambda run=run: C.classify(cats, run),
                              call('categories', 'classify', cats, run)))
        sorted_ = C.classify(cats, {'outputs': outputs, 'values': values, 'times': times, 'iterations': iterations,
                                    'flat': [False, False, True]})
        cases.append(Case('includeMask', lambda: C.include_mask(cats, sorted_['member']),
                          call('categories', 'includeMask', cats, {'$u16': sorted_['member'].tolist()})))
        everyone = [dict(c, include=True) for c in cats]
        cases.append(Case('includeMask all', lambda: C.include_mask(everyone, sorted_['member']),
                          call('categories', 'includeMask', everyone, {'$u16': sorted_['member'].tolist()})))
        run_cases(self, 'categories', cases)


# ---------------------------------------------------------------------------
# salib.js
# ---------------------------------------------------------------------------


@needs_app
class SalibParity(unittest.TestCase):
    """SALib's methods as the application ports them."""

    def test_from_a_sample(self):
        cases = []
        for n, seed in ((9, 31), (150, 32), (700, 33)):
            cols = sample_columns(n, seed)
            r = np.random.default_rng(seed)
            y = np.exp(3 * cols[0]) + cols[3] + 0.2 * r.normal(size=n)
            for k, x in enumerate(cols):
                for slides in (1, 3, 6, 10, 21):
                    cases.append(Case(f'pawn {n} {k} {slides}', lambda x=x, y=y, s=slides: SL.pawn(x, y, slides=s),
                                      call('salib', 'pawn', x, y, {'slides': slides})))
                cases.append(Case(f'ks {n} {k}', lambda x=x, y=y, n=n: SL.ks_statistic(x[: n // 2], np.round(y, 1)),
                                  call('salib', 'ksStatistic', x[: n // 2], np.round(y, 1))))
                cases.append(Case(f'rankProbabilities {n} {k}', lambda x=x: SL.rank_probabilities(x),
                                  call('salib', 'rankProbabilities', x)))
            probs = [SL.rank_probabilities(c) for c in cols[:4]]
            v = SL.rank_probabilities(y)
            for method in SL.DISCREPANCIES + ['unknown']:
                for k in range(4):
                    cases.append(Case(f'discrepancy2d {n} {k} {method}',
                                      lambda u=probs[k], v=v, m=method: SL.discrepancy2d(u, v, m),
                                      call('salib', 'discrepancy2d', probs[k], v, method)))
                cases.append(Case(f'discrepancyShares {n} {method}',
                                  lambda m=method, probs=probs, y=y: SL.discrepancy_shares(probs, y, m),
                                  call('salib', 'discrepancyShares', probs, y, method)))
        cases.append(Case('DISCREPANCIES', lambda: SL.DISCREPANCIES, const('salib', 'DISCREPANCIES')))
        cases.append(Case('ks empty', lambda: SL.ks_statistic([], [1.0]), call('salib', 'ksStatistic', [], [1.0])))
        cases.append(Case('discrepancy empty', lambda: SL.discrepancy2d([], []),
                          call('salib', 'discrepancy2d', [], [])))
        cases.append(Case('pawn nothing', lambda: SL.pawn([1.0, 1.0], [2.0, 3.0]),
                          call('salib', 'pawn', [1.0, 1.0], [2.0, 3.0])))
        run_cases(self, 'salib', cases)

    def test_designs_and_intervals(self):
        cases = []
        cases.append(Case('resampleIndices', lambda: SL.resample_indices(13, 7, lcg(5)),
                          call('salib', 'resampleIndices', 13, 7, {'$lcg': 5})))
        # The radial design and both of its readings.
        K, N = 4, 25
        base = [uniforms(N, stream_for(3, f'b{k}')) for k in range(K)]
        step = [uniforms(N, stream_for(3, f's{k}')) for k in range(K)]
        d = SL.radial_design(K, base, step)
        cases.append(Case('radialDesign', lambda K=K: SL.radial_design(K, base, step),
                          call('salib', 'radialDesign', K, base, step)))
        y = design_outputs(d['u'], lambda u: math.sin(6 * u[0]) + 7 * u[1] ** 2 + 0.1 * u[2] ** 4 * math.sin(6 * u[0]))
        y_tie = y.copy()
        y_tie[: K + 1] = y_tie[0]
        idx = SL.resample_indices(N, 30, lcg(9))
        idx_t = SL.resample_indices(N, 30, lcg(10))
        for tag, yy in (('y', y), ('ties', y_tie)):
            cases.append(Case(f'radialIndices {tag} given',
                              lambda yy=yy: SL.radial_indices(yy, d, resamples=30, indices=idx),
                              call('salib', 'radialIndices', yy, d, {'resamples': 30, 'indices': i32(idx)})))
            cases.append(Case(f'radialIndices {tag} both',
                              lambda yy=yy: SL.radial_indices(yy, d, resamples=30, indices=idx, st_indices=idx_t),
                              call('salib', 'radialIndices', yy, d,
                                   {'resamples': 30, 'indices': i32(idx), 'stIndices': i32(idx_t)})))
            cases.append(Case(f'radialIndices {tag} drawn',
                              lambda yy=yy: SL.radial_indices(yy, d, resamples=20, next=stream_for(4, 'boot')),
                              call('salib', 'radialIndices', yy, d,
                                   {'resamples': 20, 'next': {'$stream': [4, 'boot']}})))
            cases.append(Case(f'radialIndices {tag} none', lambda yy=yy: SL.radial_indices(yy, d, resamples=0),
                              call('salib', 'radialIndices', yy, d, {'resamples': 0})))
        # Morris's trajectories, the distances between them and the optimal selection.
        for K, p in ((3, 4), (5, 6), (1, 2)):
            cases.append(Case(f'morrisTrajectory {K} {p}', lambda K=K, p=p: SL.morris_trajectory(K, p, lcg(K)),
                              call('salib', 'morrisTrajectory', K, p, {'$lcg': K})))
        nxt = lcg(17)
        cands = [SL.morris_trajectory(4, 4, nxt) for _ in range(40)]
        cands.append([list(row) for row in cands[3]])
        for a, b in ((0, 1), (3, 40), (5, 5), (2, 9)):
            cases.append(Case(f'trajectoryDistance {a} {b}',
                              lambda a=a, b=b: SL.trajectory_distance(cands[a], cands[b]),
                              call('salib', 'trajectoryDistance', cands[a], cands[b])))
        for k in (1, 2, 3, 5, 8, 41, 50):
            cases.append(Case(f'optimalTrajectories {k}', lambda k=k: SL.optimal_trajectories(cands, k),
                              call('salib', 'optimalTrajectories', cands, k)))
        for K, t, levels, c in ((5, 7, 4, 20), (3, 4, 6, 0), (2, 3, 5, 9), (4, 1, 4, 0), (4, 1, 4, 3)):
            cases.append(Case(f'morrisTrajectoryDesign {K} {t} {levels} {c}',
                              lambda K=K, t=t, levels=levels, c=c: SL.morris_trajectory_design(
                                  K, trajectories=t, levels=levels, candidates=c, next=lcg(K + t)),
                              call('salib', 'morrisTrajectoryDesign', K,
                                   {'trajectories': t, 'levels': levels, 'candidates': c, 'next': {'$lcg': K + t}})))
        # The interval on mu*: resamples given per input, and drawn.
        effects = [list(np.random.default_rng(k).normal(size=5 + 3 * k)) for k in range(4)] + [[1.0], []]
        given = [SL.resample_indices(len(e), 25, lcg(k)) for k, e in enumerate(effects)]
        cases.append(Case('muStarInterval given',
                          lambda: SL.mu_star_interval(effects, resamples=25, indices=lambda k, n: given[k]),
                          call('salib', 'muStarInterval', effects,
                               {'resamples': 25, 'indices': {'$fnList': [i32(g) for g in given]}})))
        cases.append(Case('muStarInterval drawn',
                          lambda: SL.mu_star_interval(effects, resamples=40, conf=0.9, next=stream_for(2, 'mu')),
                          call('salib', 'muStarInterval', effects,
                               {'resamples': 40, 'conf': 0.9, 'next': {'$stream': [2, 'mu']}})))
        # Sobol's bootstrap, with pairs and without.
        for second in (False, True):
            K, n = 3, 40
            A = [uniforms(n, stream_for(5, f'A{k}')) for k in range(K)]
            B = [uniforms(n, stream_for(5, f'B{k}')) for k in range(K)]
            sd = G.sobol_design(K, n, second=second, draw=lambda k, w, b, A=A, B=B: A[k] if w == 'A' else B[k])
            ys = ishigami_u(sd['u'])
            ind = SL.resample_indices(n, 30, lcg(3))
            cases.append(Case(f'sobolBootstrap {second} given',
                              lambda ys=ys, second=second, ind=ind: SL.sobol_bootstrap(
                                  ys, {'K': 3, 'n': 40, 'second': second}, resamples=30, indices=ind),
                              call('salib', 'sobolBootstrap', ys, {'K': 3, 'n': 40, 'second': second},
                                   {'resamples': 30, 'indices': i32(ind)})))
            cases.append(Case(f'sobolBootstrap {second} drawn',
                              lambda ys=ys, second=second: SL.sobol_bootstrap(
                                  ys, {'K': 3, 'n': 40, 'second': second}, resamples=25, next=stream_for(8, 'sb')),
                              call('salib', 'sobolBootstrap', ys, {'K': 3, 'n': 40, 'second': second},
                                   {'resamples': 25, 'next': {'$stream': [8, 'sb']}})))
        # The factorial's interactions, RBD-FAST's bias correction, DGSM's spread.
        fd = G.ff_design(6)
        yf = design_outputs(fd['u'], lambda x: 3 * x[0] - 2 * x[1] + x[2] * x[3] + 0.5 * x[4] * x[0] + x[5] ** 2)
        cases.append(Case('ffInteractions', lambda: SL.ff_interactions(yf, fd),
                          call('salib', 'ffInteractions', yf, fd)))
        for s1, M, N in ((0.31, 10, 1000), (0.02, 6, 64), (0.9, 4, 17), (0.5, 3, 6)):
            cases.append(Case(f'unskew {s1} {M} {N}', lambda s1=s1, M=M, N=N: SL.unskew(s1, M, N),
                              call('salib', 'unskew', s1, M, N)))
        g = np.random.default_rng(40).normal(size=3 * 30) * 5
        gi = [SL.resample_indices(30, 20, lcg(k + 1)) for k in range(3)]
        cases.append(Case('dgsmSpread given', lambda: SL.dgsm_spread(g, 3, 30, resamples=20, indices=lambda k: gi[k]),
                          call('salib', 'dgsmSpread', g, 3, 30,
                               {'resamples': 20, 'indices': {'$fnList': [i32(v) for v in gi]}})))
        cases.append(Case('dgsmSpread drawn', lambda: SL.dgsm_spread(g, 3, 30, resamples=15, next=stream_for(1, 'dg')),
                          call('salib', 'dgsmSpread', g, 3, 30, {'resamples': 15, 'next': {'$stream': [1, 'dg']}})))
        cases.append(Case('dgsmSpread none', lambda: SL.dgsm_spread(g, 3, 30, resamples=1),
                          call('salib', 'dgsmSpread', g, 3, 30, {'resamples': 1})))
        run_cases(self, 'salib', cases)


# ---------------------------------------------------------------------------
# gsa.js
# ---------------------------------------------------------------------------


@needs_app
class GsaParity(unittest.TestCase):
    """GlobalSensitivity.jl's methods and the registry, as the application runs them."""

    def test_small_things(self):
        cases = []
        r = np.random.default_rng(51)
        data = [r.normal(size=11), np.round(r.normal(size=40)), np.array([3.0]), np.array([]),
                np.array([2.0, np.nan, 1.0, 1.0, 5.0])]
        for i, d in enumerate(data):
            for p in (0, 0.25, 0.5, 0.95, 1, math.nan):
                cases.append(Case(f'quantile7 {i} {p}', lambda d=d, p=p: G.quantile7(d, p),
                                  call('gsa', 'quantile7', d, p)))
        for i, d in enumerate(data[:4]):
            cases.append(Case(f'averageRanks {i}', lambda d=d: G.average_ranks(d), call('gsa', 'averageRanks', d)))
            cases.append(Case(f'competeRank {i}', lambda d=d: G.compete_rank(d), call('gsa', 'competeRank', d)))
            cases.append(Case(f'sortPerm {i}', lambda d=d: G.sort_perm(d), call('gsa', 'sortPerm', d)))
            cases.append(Case(f'normalScores {i}', lambda d=d: G.normal_scores(d), call('gsa', 'normalScores', d)))
        for x in (0.1, 0.3, 0.8, 1.2, 1.6, 1.9, -0.4, -3.7, 12345.25, 0.0, 2.0, math.nan, math.inf):
            cases.append(Case(f'sinpi {x}', lambda x=x: G.sinpi(x), call('gsa', 'sinpi', x)))
        for n in (0, 1, 2, 7, 50):
            cases.append(Case(f'randomPermutation {n}', lambda n=n: G.random_permutation(n, lcg(n)),
                              call('gsa', 'randomPermutation', n, {'$lcg': n})))
        for n in range(5):
            cases.append(Case(f'permutationsOf {n}', lambda n=n: G.permutations_of(n),
                              call('gsa', 'permutationsOf', n)))
        for p in (1e-300, 1e-9, 0.02, 0.3, 0.5, 0.975, 1 - 1e-12, 0, 1):
            cases.append(Case(f'normalQuantile {p}', lambda p=p: G.normal_quantile(p),
                              call('gsa', 'normalQuantile', p)))
        run_cases(self, 'gsa small', cases)

    def test_morris_sobol_efast_rbd(self):
        cases = []
        for K, t, points, levels in ((4, 5, 8, 6), (3, 10, 10, 100), (1, 3, 4, 2), (6, 2, 2, 3)):
            md = G.morris_design(K, trajectories=t, points=points, levels=levels, next=lcg(K))
            cases.append(Case(f'morrisDesign {K} {t}', lambda K=K, t=t, points=points, levels=levels: G.morris_design(
                K, trajectories=t, points=points, levels=levels, next=lcg(K)),
                call('gsa', 'morrisDesign', K,
                     {'trajectories': t, 'points': points, 'levels': levels, 'next': {'$lcg': K}})))
            ym = design_outputs(md['u'], lambda u: sum((j + 1) * v ** 2 for j, v in enumerate(u)) + 1)
            for relative in (False, True):
                cases.append(Case(f'morrisIndices {K} {relative}', lambda ym=ym, md=md, rel=relative:
                                  G.morris_indices(ym, md, relative=rel),
                                  call('gsa', 'morrisIndices', ym, md, {'relative': relative})))
        cases.append(Case('morrisDesign one level', lambda: G.morris_design(3, levels=1, next=lcg(1)),
                          call('gsa', 'morrisDesign', 3, {'levels': 1, 'next': {'$lcg': 1}})))
        cases.append(Case('SOBOL_ESTIMATORS', lambda: G.SOBOL_ESTIMATORS, const('gsa', 'SOBOL_ESTIMATORS')))
        for K, n, second, blocks in ((3, 64, False, 1), (3, 32, True, 1), (4, 20, True, 3), (2, 16, False, 2)):
            cases.append(Case(f'sobolRuns {K} {n} {second} {blocks}', lambda K=K, n=n, s=second, b=blocks:
                              G.sobol_runs(K, n, second=s, blocks=b),
                              call('gsa', 'sobolRuns', K, n, {'second': second, 'blocks': blocks})))
            A = [uniforms(n * blocks, stream_for(K, f'A{k}')) for k in range(K)]
            B = [uniforms(n * blocks, stream_for(K, f'B{k}')) for k in range(K)]

            def draw(k, w, b, A=A, B=B, n=n):
                return (A if w == 'A' else B)[k][b * n:(b + 1) * n]

            sd = G.sobol_design(K, n, second=second, blocks=blocks, draw=draw)
            ab = {'$drawAB': {'A': A, 'B': B, 'n': n}}
            cases.append(Case(f'sobolDesign {K} {n} {second} {blocks}',
                              lambda K=K, n=n, s=second, b=blocks, draw=draw:
                              G.sobol_design(K, n, second=s, blocks=b, draw=draw),
                              call('gsa', 'sobolDesign', K, n, {'second': second, 'blocks': blocks, 'draw': ab})))
            ys = design_outputs(sd['u'], lambda u: math.sin(6 * u[0]) + 7 * math.sin(3 * u[-1]) ** 2 + u[0] * u[-1])
            for est in G.SOBOL_ESTIMATORS + ['unknown']:
                spec = {'K': K, 'n': n, 'second': second, 'blocks': blocks, 'estimator': est}
                cases.append(Case(f'sobolIndices {K} {n} {second} {blocks} {est}', lambda ys=ys, spec=spec:
                                  G.sobol_indices(ys, spec), call('gsa', 'sobolIndices', ys, spec)))
            spec = {'K': K, 'n': n, 'second': second, 'blocks': blocks, 'conf': 0.8}
            cases.append(Case(f'sobolIndices {K} {n} conf', lambda ys=ys, spec=spec: G.sobol_indices(ys, spec),
                              call('gsa', 'sobolIndices', ys, spec)))
        for n, M in ((1001, 4), (1000, 4), (10, 4), (65, 4), (8, 1), (300, 6), (2.5, 2), (257, 3)):
            cases.append(Case(f'efastSamples {n} {M}', lambda n=n, M=M: G.efast_samples(n, M),
                              call('gsa', 'efastSamples', n, M)))
        for K, N, M in ((1, 66, 4), (2, 66, 4), (3, 400, 4), (5, 400, 4), (12, 100, 4), (7, 130, 2)):
            cases.append(Case(f'efastFrequencies {K} {N} {M}', lambda K=K, N=N, M=M: G.efast_frequencies(K, N, M),
                              call('gsa', 'efastFrequencies', K, N, M)))
        for K, N, M in ((3, 400, 4), (5, 130, 4), (2, 66, 4), (4, 150, 2)):
            phases = [2 * stream_for(K, f'p{k}')() for k in range(K)]
            ed = G.efast_design(K, N, harmonics=M, phases=phases)
            # asin and sinpi's sin and cos are the platform's: the design is good to the last bit or two.
            cases.append(Case(f'efastDesign {K} {N}', lambda K=K, N=N, M=M, phases=phases: G.efast_design(
                K, N, harmonics=M, phases=phases),
                              call('gsa', 'efastDesign', K, N, {'harmonics': M, 'phases': phases})))
            ye = design_outputs(ed['u'], lambda u: math.sin(6 * u[0]) + 7 * u[1] ** 2 + sum(u[2:]))
            cases.append(Case(f'efastIndices {K} {N}', lambda ye=ye, ed=ed: G.efast_indices(ye, ed),
                              call('gsa', 'efastIndices', ye, ed)))
        for K, N in ((3, 399), (2, 64), (5, 100)):
            perms = [G.random_permutation(N, stream_for(N, f'r{k}')) for k in range(K)]
            rd = G.rbd_fast_design(K, N, perms=perms)
            cases.append(Case(f'rbdFastDesign {K} {N}',
                              lambda K=K, N=N, perms=perms: G.rbd_fast_design(K, N, perms=perms),
                              call('gsa', 'rbdFastDesign', K, N, {'perms': perms})))
            if K >= 3:
                yr = ishigami_u(rd['u'][:3])
            else:
                yr = design_outputs(rd['u'], lambda u: u[0] ** 3 + u[1])
            for H in (6, 2, 40):
                cases.append(Case(f'rbdFastIndices {K} {N} {H}',
                                  lambda yr=yr, rd=rd, H=H: G.rbd_fast_indices(yr, rd, harmonics=H),
                                  call('gsa', 'rbdFastIndices', yr, rd, {'harmonics': H})))
        run_cases(self, 'gsa designs', cases)

    def test_ff_dgsm_shapley(self):
        cases = []
        for k in (2, 4, 8, 16, 3, 6, 1):
            cases.append(Case(f'hadamard {k}', lambda k=k: G.hadamard(k), call('gsa', 'hadamard', k)))
        for K in range(1, 10):
            cases.append(Case(f'ffDesign {K}', lambda K=K: G.ff_design(K, low=0.1, high=0.7),
                              call('gsa', 'ffDesign', K, {'low': 0.1, 'high': 0.7})))
            fd = G.ff_design(K)
            yf = design_outputs(fd['u'], lambda x: 3 * x[0] + sum(x) ** 2)
            cases.append(Case(f'ffIndices {K}', lambda yf=yf, fd=fd: G.ff_indices(yf, fd),
                              call('gsa', 'ffIndices', yf, fd)))
        for K, N, step, crossed in ((3, 20, 1e-3, False), (3, 15, 0.01, True), (1, 5, 0.2, True), (4, 12, 0.3, True)):
            base = [uniforms(N, stream_for(N, f'd{k}')) for k in range(K)]
            base[0][0] = 0.9995
            dd = G.dgsm_design(K, base, step=step, crossed=crossed)
            cases.append(Case(f'dgsmDesign {K} {N} {crossed}', lambda K=K, base=base, s=step, c=crossed: G.dgsm_design(
                K, base, step=s, crossed=c), call('gsa', 'dgsmDesign', K, base, {'step': step, 'crossed': crossed})))
            yd = design_outputs(dd['u'], lambda u: u[0] * (1 + u[-1] ** 2) + 2 * u[-1] + math.exp(u[0]))
            cases.append(Case(f'dgsmDerivatives {K} {N}', lambda yd=yd, dd=dd: G.dgsm_derivatives(yd, dd),
                              call('gsa', 'dgsmDerivatives', yd, dd)))
            cases.append(Case(f'dgsmIndices {K} {N}', lambda yd=yd, dd=dd: G.dgsm_indices(yd, dd),
                              call('gsa', 'dgsmIndices', yd, dd)))
            der = G.dgsm_derivatives(yd, dd)
            cases.append(Case(f'dgsmStatistics {K} {N} plain',
                              lambda der=der, base=base: G.dgsm_statistics(der['g'], base),
                              call('gsa', 'dgsmStatistics', der['g'], base)))
            cases.append(Case(f'dgsmStatistics {K} {N} y0', lambda der=der, base=base: G.dgsm_statistics(
                der['g'], base, H=der['H'], y0=der['y0']),
                call('gsa', 'dgsmStatistics', der['g'], base, {'H': der['H'], 'y0': der['y0']})))
        spd = np.array([[4, 2, 0.6], [2, 5, 1.5], [0.6, 1.5, 3]], dtype=float)
        for name, A, n in (('spd', spd.ravel(), 3), ('singular', np.array([1.0, 1, 1, 1]), 2),
                           ('nan', np.array([1.0, math.nan, math.nan, 1]), 2), ('empty', np.zeros(0), 0),
                           ('short', np.array([1.0, 0.5, 0.5]), 2)):
            cases.append(Case(f'cholesky {name}', lambda A=A, n=n: G.cholesky(A, n), call('gsa', 'cholesky', A, n)))
        corr = [1, 0.5, 0.2, 0.5, 1, -0.3, 0.2, -0.3, 1]
        for perms, corr_ in ((-1, None), (-1, corr), (4, None), (3, corr)):
            K = 3
            kw = dict(perms=perms, n_var=40, n_outer=4, n_inner=3, corr=corr_)
            sd = G.shapley_design(K, next=stream_for(7, 'sh'), **kw)
            opts = {'perms': perms, 'nVar': 40, 'nOuter': 4, 'nInner': 3, 'corr': corr_, 'next': {'$stream': [7, 'sh']}}
            # With a copula the draws go through log, cos, Phi and its inverse, each the platform's.
            cases.append(Case(f'shapleyDesign {perms} {corr_ is not None}', lambda kw=kw: G.shapley_design(
                3, next=stream_for(7, 'sh'), **kw), call('gsa', 'shapleyDesign', K, opts), rtol=1e-11))
            ysh = design_outputs(sd['u'], lambda u: u[0] + 2 * u[1] + 3 * u[2] * u[0])
            cases.append(Case(f'shapleyIndices {perms} {corr_ is not None}',
                              lambda ysh=ysh, sd=sd: G.shapley_indices(ysh, sd),
                              call('gsa', 'shapleyIndices', ysh, sd)))
        bad = [1, 0.99, 0.99, 0.99, 1, -0.99, 0.99, -0.99, 1]
        cases.append(Case('shapleyDesign invalid',
                          lambda: G.shapley_design(3, perms=-1, n_var=5, n_outer=1, corr=bad, next=stream_for(1, 'x')),
                          call('gsa', 'shapleyDesign', 3,
                               {'perms': -1, 'nVar': 5, 'nOuter': 1, 'corr': bad, 'next': {'$stream': [1, 'x']}})))
        run_cases(self, 'gsa designs', cases)

    def test_from_a_sample(self):
        cases = []
        for n, seed in ((40, 61), (201, 62), (500, 63)):
            cols = sample_columns(n, seed)
            r = np.random.default_rng(seed)
            y = np.sin(3 * cols[0]) + 0.3 * cols[1] + np.round(cols[3]) + 0.1 * r.normal(size=n)
            for k in range(4):
                for H, dct in ((4, False), (4, True), (2, False), (9, True)):
                    # A power spectrum's small entries carry the platform's twiddles; the ratio is still close.
                    cases.append(Case(f'easi {n} {k} {H} {dct}',
                                      lambda x=cols[k], y=y, H=H, dct=dct: G.easi(x, y, harmonics=H, dct=dct),
                                      call('gsa', 'easi', cols[k], y, {'harmonics': H, 'dct': dct})))
                cases.append(Case(f'rsaScore {n} {k}',
                                  lambda x=cols[k], y=y: G.rsa_score(x, (y > np.median(y)).astype(float)),
                                  call('gsa', 'rsaScore', cols[k], (y > np.median(y)).astype(float))))
            dummies = [uniforms(n, stream_for(seed, f'#rsa#dummy#{d}')) for d in range(5)]
            cases.append(Case(f'rsa {n}', lambda cols=cols, y=y, dummies=dummies: G.rsa(cols, y, dummies=dummies),
                              call('gsa', 'rsa', cols, y, {'dummies': dummies})))
            cases.append(Case(f'rsa {n} threshold', lambda cols=cols, y=y: G.rsa(cols[:2], y, threshold=0.5),
                              call('gsa', 'rsa', cols[:2], y, {'threshold': 0.5})))
            bins = G._js_round(math.sqrt(n))  # pylint: disable=protected-access
            for k in range(4):
                cases.append(Case(f'histogramEntropy {n} {k}', lambda x=cols[k], b=bins: G.histogram_entropy(x, b),
                                  call('gsa', 'histogramEntropy', cols[k], bins)))
                cases.append(Case(f'jointEntropy {n} {k}', lambda x=cols[k], y=y, b=bins: G.joint_entropy(x, y, b),
                                  call('gsa', 'jointEntropy', cols[k], y, bins)))
            shuffles = [G.random_permutation(n, lcg(s)) for s in range(6)]
            for k in (0, 1, 3):
                cases.append(Case(f'mutualInformation {n} {k} shuffles',
                                  lambda x=cols[k], y=y, sh=shuffles: G.mutual_information(x, y, shuffles=sh),
                                  call('gsa', 'mutualInformation', cols[k], y, {'shuffles': shuffles})))
                cases.append(Case(f'mutualInformation {n} {k} drawn',
                                  lambda x=cols[k], y=y, k=k:
                                  G.mutual_information(x, y, boots=30, conf=0.9, next=stream_for(1, f'mi{k}')),
                                  call('gsa', 'mutualInformation', cols[k], y,
                                       {'boots': 30, 'conf': 0.9, 'next': {'$stream': [1, f'mi{k}']}})))
            cases.append(Case(f'mutualInformation {n} none', lambda x=cols[0], y=y: G.mutual_information(x, y, boots=0),
                              call('gsa', 'mutualInformation', cols[0], y, {'boots': 0})))
            scores = G.normal_scores(y)
            for data, fb in ((y, None), (np.full(n, 3.0), None), (np.full(n, 3.0), 0.25), (y[:1], None), (y[:1], 0.4)):
                cases.append(Case(f'kdeBandwidth {n} {len(data)} {fb}', lambda d=data, fb=fb: G.kde_bandwidth(d, fb),
                                  call('gsa', 'kdeBandwidth', data, fb)))
            for data, npoints in ((scores, 2048), (y, 256), (np.round(y[:30]), 100)):
                k = G.kde(data, npoints=npoints)
                grid = np.linspace(k['lo'] - 0.5, k['hi'] + 0.5, 301)
                # The bandwidth is n^-0.2 (pow) and the smoothing exp and a transform: the platform's each.
                cases.append(Case(f'kde {n} {npoints}', lambda d=data, p=npoints: G.kde(d, npoints=p),
                                  call('gsa', 'kde', data, {'npoints': npoints}), rtol=1e-10,
                                  atol=1e-13 * float(np.abs(k['density']).max())))
                cases.append(Case(f'kdePdf {n} {npoints}', lambda k=k, grid=grid: G.kde_pdf(k, grid),
                                  call('gsa', 'kdePdf', k, grid), atol=1e-13 * float(np.abs(k['density']).max())))
            cases.append(Case('kde flat refused', lambda: G.kde(np.full(5, 1.0), fallback=0.0),
                              call('gsa', 'kde', np.full(5, 1.0), {'fallback': 0.0})))
            resamples = [[v % n for v in np.random.default_rng(b).integers(0, n, n)] for b in range(3)]
            for k in (0, 3):
                # delta integrates the difference of two kernel density estimates: its rounding is that of the
                # transforms, the exp and the pow behind them, so 1e-10 relative.
                cases.append(Case(f'deltaMoment {n} {k} resamples',
                                  lambda x=cols[k], s=scores, rs=resamples: G.delta_moment(x, s, resamples=rs),
                                  call('gsa', 'deltaMoment', cols[k], scores, {'resamples': resamples}), rtol=1e-10))
                cases.append(Case(f'deltaMoment {n} {k} drawn',
                                  lambda x=cols[k], s=scores:
                                  G.delta_moment(x, s, boots=2, grid=512, classes=5, next=stream_for(3, 'delta')),
                                  call('gsa', 'deltaMoment', cols[k], scores,
                                       {'boots': 2, 'grid': 512, 'classes': 5, 'next': {'$stream': [3, 'delta']}}),
                                  rtol=1e-10))
            cases.append(Case(f'deltaMoment {n} none', lambda x=cols[1], y=y: G.delta_moment(x, y, boots=0),
                              call('gsa', 'deltaMoment', cols[1], y, {'boots': 0}), rtol=1e-10))
            cases.append(Case(f'deltaMoment {n} flat',
                              lambda x=cols[1], n=n: G.delta_moment(x, np.full(n, 2.0), boots=0),
                              call('gsa', 'deltaMoment', cols[1], np.full(n, 2.0), {'boots': 0})))
        for n in (0, 1, 10, 100, 999, 1000, 1500, 4000, 10000, 100000):
            cases.append(Case(f'deltaClasses {n}', lambda n=n: G.delta_classes(n), call('gsa', 'deltaClasses', n)))
        # Degenerate sizes, which the application answers with NaN rather than an exception.
        empty = np.zeros(0)
        cases.append(Case('deltaMoment empty', lambda: G.delta_moment(empty, empty, boots=2, next=lcg(1)),
                          call('gsa', 'deltaMoment', empty, empty, {'boots': 2, 'next': {'$lcg': 1}})))
        cases.append(Case('mutualInformation empty', lambda: G.mutual_information(empty, empty, boots=3, next=lcg(1)),
                          call('gsa', 'mutualInformation', empty, empty, {'boots': 3, 'next': {'$lcg': 1}})))
        cases.append(Case('easi empty', lambda: G.easi(empty, empty), call('gsa', 'easi', empty, empty)))
        cases.append(Case('rsa empty', lambda: G.rsa([empty], empty), call('gsa', 'rsa', [empty], empty)))
        cases.append(Case('sobolIndices n 0', lambda: G.sobol_indices(np.ones(4), {'K': 2, 'n': 0, 'second': True}),
                          call('gsa', 'sobolIndices', np.ones(4), {'K': 2, 'n': 0, 'second': True})))
        cases.append(Case('sobolIndices flat',
                          lambda: G.sobol_indices(np.full(24, 2.0), {'K': 2, 'n': 4, 'second': True}),
                          call('gsa', 'sobolIndices', np.full(24, 2.0), {'K': 2, 'n': 4, 'second': True})))
        cases.append(Case('efastFrequencies no harmonics', lambda: G.efast_frequencies(3, 10, 0),
                          call('gsa', 'efastFrequencies', 3, 10, 0)))
        cases.append(Case('efastDesign empty', lambda: G.efast_design(3, 0, phases=[0.1, 0.2, 0.3]),
                          call('gsa', 'efastDesign', 3, 0, {'phases': [0.1, 0.2, 0.3]})))
        cases.append(Case('shapleyDesign no inputs', lambda: G.shapley_design(0, n_var=4, n_outer=2, next=lcg(1)),
                          call('gsa', 'shapleyDesign', 0, {'nVar': 4, 'nOuter': 2, 'next': {'$lcg': 1}})))
        cases.append(Case('kdePdf outside', lambda: G.kde_pdf(G.kde([1.0, 2.0, 4.0]), [-50.0, math.nan, 50.0]),
                          call('gsa', 'kdePdf', G.kde([1.0, 2.0, 4.0]), [-50.0, math.nan, 50.0])))
        run_cases(self, 'gsa sample', cases)

    def test_registry(self):
        cases = []
        cases.append(Case('GSA_METHOD_IDS', lambda: G.GSA_METHOD_IDS, const('gsa', 'GSA_METHOD_IDS')))
        for K in (1, 3, 4, 5, 9):
            def methods(K=K):
                out = {}
                for mid, m in G.GSA_METHODS.items():
                    options = [[o[0], o[1], o[2](K) if callable(o[2]) else o[2], *o[3:]] for o in m['options']]
                    out[mid] = dict(m, options=options)
                return out
            cases.append(Case(f'GSA_METHODS {K}', methods, {'special': 'methods', 'K': K}))
        givens = [
            {}, {'samples': '250', 'second': 'yes', 'blocks': 2.6, 'estimator': 'janon2014', 'resamples': ''},
            {'trajectories': True, 'points': None, 'levels': ' 12 ', 'design': 'trajectories', 'candidates': '0x10',
             'relative': 0, 'resamples': [7]},
            {'low': '0.2', 'high': 0.8, 'pairs': []}, {'step': 'abc', 'crossed': 'false', 'samples': -2.5},
            {'perms': 2.5, 'nVar': 1e21, 'nOuter': math.inf, 'nInner': '3.5'},
            {'estimator': 'Jansen1999', 'harmonics': 2.5},
        ]
        for method in G.GSA_METHOD_IDS + ['nonsense']:
            for K in (0, 1, 3, 9, 12):
                for i, given in enumerate(givens):
                    cases.append(Case(f'gsaOptions {method} {K} {i}',
                                      lambda m=method, K=K, g=given: G.gsa_options(m, K, g),
                                      call('gsa', 'gsaOptions', method, K, given)))
                    cases.append(Case(f'gsaRuns {method} {K} {i}', lambda m=method, K=K, g=given: G.gsa_runs(m, K, g),
                                      call('gsa', 'gsaRuns', method, K, given)))
                    cases.append(Case(f'gsaRefusal {method} {K} {i}',
                                      lambda m=method, K=K, g=given: G.gsa_refusal(m, K, g),
                                      call('gsa', 'gsaRefusal', method, K, given)))
        refusals = [
            ('morris', {'trajectories': 0}), ('morris', {'points': 1}), ('morris', {'levels': 1}),
            ('morris', {'design': 'trajectories', 'candidates': 3, 'trajectories': 5}), ('radial', {'samples': 1}),
            ('sobol', {'samples': 1}), ('sobol', {'blocks': 0}), ('sobol', {'blocks': 5, 'samples': 4}),
            ('efast', {'samples': 7}), ('efast', {'harmonics': 0}), ('rbdfast', {'samples': 16, 'harmonics': 4}),
            ('ff', {'low': 0.9, 'high': 0.1}), ('ff', {'low': 0, 'high': 0.5}), ('ff', {'high': 1}),
            ('dgsm', {'samples': 1}), ('dgsm', {'step': 0.5}), ('dgsm', {'step': 0}), ('shapley', {'perms': 0}),
            ('shapley', {'nVar': 1}), ('shapley', {'nOuter': 0}), ('shapley', {'nInner': 1}),
        ]
        for method, given in refusals:
            for K in (3, 12):
                cases.append(Case(f'gsaRefusal {method} {given} {K}',
                                  lambda m=method, K=K, g=given: G.gsa_refusal(m, K, g),
                                  call('gsa', 'gsaRefusal', method, K, given)))
        cases.append(Case('gsaRefusal none', lambda: G.gsa_refusal(None, 3), call('gsa', 'gsaRefusal', None, 3)))
        run_cases(self, 'gsa registry', cases)

    DESIGNS = [
        ('morris', {}), ('morris', {'trajectories': 6, 'points': 8}),
        ('morris', {'design': 'trajectories', 'trajectories': 8, 'levels': 4, 'candidates': 30}),
        ('morris', {'design': 'trajectories', 'trajectories': 5, 'levels': 6}),
        ('morris', {'design': 'trajectories', 'trajectories': 1, 'candidates': 4}),
        ('radial', {'samples': 30}), ('radial', {'samples': 20, 'resamples': 0}),
        ('sobol', {'samples': 64}), ('sobol', {'samples': 32, 'second': True}),
        ('sobol', {'samples': 20, 'blocks': 3, 'estimator': 'homma1996'}), ('sobol', {'samples': 40, 'resamples': 0}),
        ('efast', {'samples': 200}), ('efast', {'samples': 70, 'harmonics': 2}),
        ('rbdfast', {'samples': 256}), ('rbdfast', {'samples': 99, 'harmonics': 3}),
        ('ff', {}), ('ff', {'pairs': True, 'low': 0.2, 'high': 0.6}),
        ('dgsm', {'samples': 30}), ('dgsm', {'samples': 12, 'crossed': True, 'step': 0.01}),
        ('dgsm', {'samples': 10, 'resamples': 0}),
        ('shapley', {'nVar': 60, 'nOuter': 3}), ('shapley', {'perms': 5, 'nVar': 50, 'nOuter': 2, 'nInner': 2}),
        ('nonsense', {}), ('sobol', {'samples': 1}),
    ]

    def test_designs_from_a_seed(self):
        # The test's port of the application's streams, checked first against the application's own.
        checks = [{'special': 'stream', 'seed': s, 'name': name, 'count': 50}
                  for s, name in ((1, 'a'), (3, 'Kd[Cs-137]#sobol#A#0'), (0, ''), (4294967301, 'x'), (7, 'ä€𝄞'))]
        checks.append({'special': 'uniforms', 'seed': 5, 'name': 'u', 'n': 37})
        checks.append({'special': 'uniforms', 'seed': 5, 'name': 'u', 'n': 11, 'latin': False})
        got = [dec(r['value']) for r in js(checks)]
        for c, want in zip(checks, got):
            nxt = stream_for(c['seed'], c['name'])
            mine = (np.array([nxt() for _ in range(c['count'])]) if c['special'] == 'stream'
                    else uniforms(c['n'], nxt, c.get('latin', True)))
            self.assertTrue(np.array_equal(mine, want), f'the test streams are not the application\'s: {c}')

        cases = []
        corr = [1, 0.4, 0, 0.4, 1, 0.3, 0, 0.3, 1]
        for method, options in self.DESIGNS:
            for keys, corr_ in ((['a', 'b', 'c'], None), (['k', 'Kd[Cs-137]'], None), (['a', 'b', 'c'], corr)):
                if corr_ is not None and method != 'shapley':
                    continue
                spec = {'method': method, 'keys': keys, 'options': enc(options), 'seed': 3, 'corr': corr_}
                # Designs drawn through asin and sin (eFAST, RBD-FAST) or a copula (Shapley) are good to the
                # platform's last bit or two; the others are the same numbers.
                cases.append(Case(f'buildDesign {method} {options} {keys} {corr_ is not None}',
                                  lambda m=method, o=options, k=keys, c=corr_: G.build_design(m, k, o, seed=3, corr=c,
                                                                                              **STREAMS),
                                  dict(spec, special='buildDesign'), rtol=1e-11))
        run_cases(self, 'gsa designs', cases)

    def test_tables(self):
        cases = []
        for method, options in self.DESIGNS:
            keys = ['a', 'b', 'c']
            try:
                d = G.build_design(method, keys, options, seed=3, **STREAMS)
            except (ValueError, TypeError):
                continue  # refused, by the application too (test_designs_from_a_seed)
            y = ishigami_u(d['u'])
            y_flat = np.full(d['runs'], 1.5)
            y_failed = y.copy()
            y_failed[1] = np.nan
            spec = {'method': method, 'keys': keys, 'options': enc(options), 'seed': 3}
            outputs = (('y', y, True), ('plain', y, False), ('flat', y_flat, True), ('failed', y_failed, True))
            for tag, yy, intervals in outputs:
                # The spectral methods' powers carry the platform's twiddles, and the intervals the normal quantile.
                cases.append(Case(f'gsaTable {method} {options} {tag}',
                                  lambda d=d, yy=yy, iv=intervals:
                                  G.gsa_table(d, yy, next=stream_for(3, '#gsa#bootstrap'), intervals=iv),
                                  dict(spec, special='gsaTable', y=f64(yy), next=[3, '#gsa#bootstrap'],
                                       intervals=intervals),
                                  rtol=1e-11, atol=1e-15 if method in ('efast', 'rbdfast') else 0.0))
            cases.append(Case(f'gsaMain {method} {options}', lambda d=d, y=y: G.gsa_main(d, y),
                              dict(spec, special='gsaMain', y=f64(y)), rtol=1e-11,
                              atol=1e-15 if method in ('efast', 'rbdfast') else 0.0))
        # Designs made directly, without the registry's settings: gsaTable falls back on its own defaults
        # (any bootstrap it then draws is not shown, so Math.random on the application's side does not matter).
        bare = [
            G.morris_design(3, trajectories=4, points=5, levels=6, next=lcg(2)),
            SL.radial_design(3, [uniforms(15, stream_for(1, f'b{k}')) for k in range(3)],
                             [uniforms(15, stream_for(1, f's{k}')) for k in range(3)]),
            G.sobol_design(3, 20, second=True, draw=lambda k, w, b: uniforms(20, stream_for(2, f'{w}{k}'))),
            G.efast_design(3, 66, phases=[0.1, 0.7, 1.3]),
            G.rbd_fast_design(3, 64, perms=[G.random_permutation(64, lcg(k)) for k in range(3)]),
            G.ff_design(3),
            G.dgsm_design(3, [uniforms(10, stream_for(4, f'd{k}')) for k in range(3)], crossed=True),
            G.shapley_design(3, n_var=30, n_outer=2, n_inner=2, next=lcg(6)),
        ]
        for d in bare:
            y = ishigami_u(d['u'])
            cases.append(Case(f"gsaTable bare {d['method']}", lambda d=d, y=y: G.gsa_table(d, y),
                              call('gsa', 'gsaTable', d, y), rtol=1e-11,
                              atol=1e-15 if d['method'] in ('efast', 'rbdfast') else 0.0))
        run_cases(self, 'gsa tables', cases)


# ---------------------------------------------------------------------------
# The application's own reference checks, from its test/run.js.
# ---------------------------------------------------------------------------


def _b64f(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype='<f8').copy()


def _b64i(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype='<i4').copy()


class _Reference(unittest.TestCase):
    area = 'reference'

    def close(self, name: str, got: Any, want: Any, tol: float) -> None:
        """The application's ``close``: relative, or absolute where the reference is zero."""
        g = np.asarray(got, dtype=float).ravel()
        w = np.asarray(want, dtype=float).ravel()
        self.assertEqual(len(g), len(w), f'{name}: {len(g)} values against {len(w)}')
        for i, (a, b) in enumerate(zip(g.tolist(), w.tolist())):
            if math.isnan(a) and math.isnan(b):
                continue
            diff = abs(a - b)
            err = diff if b == 0 else min(diff, diff / abs(b))
            # The summary for these areas is the application's own measure: absolute or relative, the smaller.
            COMPARED[self.area] = COMPARED.get(self.area, 0) + 1
            if a == b:
                IDENTICAL[self.area] = IDENTICAL.get(self.area, 0) + 1
            if err >= WORST.get(self.area, (0.0, ''))[0]:
                WORST[self.area] = (err, f'{name}[{i}]')
            self.assertLessEqual(err, tol, f'{name}[{i}]: {a} against {b}')


@needs_fixtures
class SalibReference(_Reference):
    """The methods from SALib give SALib's numbers on the same samples (test/run.js)."""

    area = 'SALib ref'

    @classmethod
    def setUpClass(cls):
        cls.ref = json.loads((FIXTURES / 'salib-reference.json').read_text('utf-8'))

    def test_ks_pawn_discrepancy(self):
        ref = self.ref
        self.assertEqual(ref['version'], '1.6.0')
        for c in ref['ks']:
            self.close('ks', [SL.ks_statistic(_b64f(c['a']), _b64f(c['b']))], [c['statistic']], 1e-15)
        X = [_b64f(x) for x in ref['sample']['X']]
        Y = _b64f(ref['sample']['Y'])
        for c in ref['pawn']:
            got = [SL.pawn(x, Y, slides=c['S']) for x in X]
            for key, ours in (('minimum', 'minimum'), ('mean', 'mean'), ('median', 'median'), ('maximum', 'maximum'),
                              ('CV', 'cv'), ('stdev', 'stdev')):
                self.close(f"pawn S={c['S']} {key}", [r[ours] for r in got], _b64f(c[key]), 1e-12)
        for method, want in ref['discrepancy'].items():
            self.close(f'discrepancy {method}', SL.discrepancy_shares(X, Y, method)['shares'], _b64f(want), 1e-11)
        # Why a sample's is read on ranks: a skewed output scaled by its extremes sits at the bottom of the square.
        skew = np.exp(12 * X[0]) + X[1]
        by_value = SL.discrepancy_shares(X, skew)['shares']
        by_rank = SL.discrepancy_shares([SL.rank_probabilities(x) for x in X], SL.rank_probabilities(skew))['shares']
        self.assertTrue(max(by_value) - min(by_value) < 0.01 and by_rank[0] > 0.9, f'{by_value} {by_rank}')
        self.assertEqual(SL.rank_probabilities([3, 1, 2, 2]).tolist(), [0.875, 0.125, 0.5, 0.5])

    def test_radial_morris_sobol(self):
        ref = self.ref
        Rd = ref['radial']
        d = SL.radial_design(3, [_b64f(v) for v in Rd['base']], [_b64f(v) for v in Rd['step']])
        yr = _b64f(Rd['y'])
        self.assertEqual(d['runs'], len(yr))
        ri = SL.radial_indices(yr, d, resamples=100, indices=_b64i(Rd['indices']))
        self.close('radial mu', ri['mu'], _b64f(Rd['mu']), 1e-10)
        self.close('radial mu*', ri['muStar'], _b64f(Rd['mu_star']), 1e-10)
        self.close('radial sigma', ri['sigma'], _b64f(Rd['sigma']), 1e-10)
        self.close('radial mu* interval', ri['muStarCi'], _b64f(Rd['mu_star_conf']), 1e-9)
        self.close('radial ST', ri['ST'], _b64f(Rd['ST']), 1e-10)
        self.close('radial ST interval', ri['STci'], _b64f(Rd['ST_conf_resampled']), 1e-9)

        M = ref['morris']

        def trajectories(flat: np.ndarray, K: int) -> List[List[List[float]]]:
            rows = len(flat) // K
            return [[list(flat[(t * (K + 1) + s) * K:(t * (K + 1) + s + 1) * K]) for s in range(K + 1)]
                    for t in range(rows // (K + 1))]

        self.assertEqual(SL.optimal_trajectories(trajectories(_b64f(M['candidates']), M['K']), 6), M['chosen'])
        for c in ref['optimal']:
            self.assertEqual(SL.optimal_trajectories(trajectories(_b64f(c['candidates']), c['K']), c['k']), c['chosen'],
                             f"of {c['N']}")
        Xm = np.array([_b64f(v) for v in M['X']])
        mi = G.morris_indices(_b64f(M['y']), {'K': M['K'], 'trajectories': 6, 'points': M['K'] + 1, 'u': Xm})
        self.close('morris mu', mi['mean'], _b64f(M['mu']), 1e-10)
        self.close('morris mu*', mi['meanStar'], _b64f(M['mu_star']), 1e-10)
        self.close('morris sigma', np.sqrt(mi['variance']), _b64f(M['sigma']), 1e-10)
        idx = [_b64i(v) for v in M['indices']]
        self.close('morris mu* interval',
                   SL.mu_star_interval(mi['effects'], resamples=100, indices=lambda k, n: idx[k]),
                   _b64f(M['mu_star_conf']), 1e-9)

        So = ref['sobol']
        sb = SL.sobol_bootstrap(_b64f(So['y']), {'K': So['K'], 'n': So['n'], 'second': True}, resamples=50,
                                indices=_b64i(So['indices']))
        self.close('sobol S1 interval', sb['S1ci'], _b64f(So['S1_conf']), 1e-9)
        self.close('sobol ST interval', sb['STci'], _b64f(So['ST_conf']), 1e-9)
        S2 = _b64f(So['S2_conf'])
        for j in range(So['K']):
            for k in range(j + 1, So['K']):
                self.close(f'sobol S2 interval {j}{k}', [sb['S2ci'][j * So['K'] + k]], [S2[j * So['K'] + k]], 1e-9)

    def test_ff_unskew_dgsm_and_the_tools_own_trajectories(self):
        ref = self.ref
        Fr = ref['ff']
        fd = G.ff_design(Fr['K'])
        Xf = [_b64f(v) for v in Fr['X']]
        for k in range(Fr['K']):
            for r in range(fd['rows']):
                self.assertEqual(1 if Xf[k][r] > 0.5 else -1, int(np.sign(fd['signs'][r][k])), f'row {r}, input {k}')
        yf = _b64f(Fr['y'])
        self.close('ff main effects', G.ff_indices(yf, fd)['main'], _b64f(Fr['ME']), 1e-12)
        pairs = SL.ff_interactions(yf, fd)
        for p in Fr['pairs']:
            got = next((q for q in pairs if q['a'] == min(p['a'], p['b']) and q['b'] == max(p['a'], p['b'])), None)
            self.close(f"ff interaction {p['a']}{p['b']}", [got['value'] if got else math.nan], [p['value']], 1e-12)
        for c in ref['unskew']:
            self.close('unskew', [SL.unskew(c['S1'], c['M'], c['N'])], [c['value']], 1e-15)
        Dg = ref['dgsm']
        gd = _b64f(Dg['g'])
        di = [_b64i(v) for v in Dg['indices']]
        dsp = SL.dgsm_spread(gd, 3, Dg['N'], resamples=50, indices=lambda k: di[k])
        vi = [sum(gd[i * 3 + k] ** 2 for i in range(Dg['N'])) / Dg['N'] for k in range(3)]
        self.close('dgsm nu', vi, _b64f(Dg['vi']), 1e-12)
        self.close('dgsm nu spread', dsp['sd'], _b64f(Dg['vi_std']), 1e-11)
        self.close('dgsm nu interval', dsp['ci'], _b64f(Dg['dgsm_conf']), 1e-9)
        # The tool's own trajectories: each input moves once, half the levels, and stays on the grid.
        td = SL.morris_trajectory_design(5, trajectories=7, levels=4, candidates=20, next=lcg(0))
        self.assertEqual((td['trajectories'], td['runs']), (7, 42))
        for t in range(7):
            moved = [0] * 5
            for s in range(5):
                changed = []
                for k in range(5):
                    a = td['u'][k][t * 6 + s]
                    b = td['u'][k][t * 6 + s + 1]
                    if a != b:
                        changed.append(k)
                        self.assertLess(abs(abs(b - a) - 0.5), 1e-12)
                    self.assertIn(b, (0.125, 0.375, 0.625, 0.875))
                self.assertEqual(len(changed), 1)
                moved[changed[0]] += 1
            self.assertEqual(moved, [1] * 5)

    def test_registry_with_the_tools_streams(self):
        keys = ['a', 'b', 'c']

        def ishi(u: List[float]) -> float:
            x = [-math.pi + 2 * math.pi * v for v in u]
            return math.sin(x[0]) + 7 * math.sin(x[1]) ** 2 + 0.1 * x[2] ** 4 * math.sin(x[0])

        cases = [
            ('radial', {'samples': 60}, ['ST', 'STci', 'meanStar', 'meanStarCi', 'mean', 'sd']),
            ('morris', {'design': 'trajectories', 'trajectories': 8, 'levels': 4, 'candidates': 30},
             ['meanStar', 'meanStarCi', 'mean', 'sd']),
            ('morris', {'trajectories': 6, 'points': 8}, ['meanStar', 'meanStarCi']),
            ('sobol', {'samples': 128}, ['S1', 'ST', 'S1ci', 'STci']),
            ('ff', {'pairs': True}, ['main']),
            ('rbdfast', {'samples': 256}, ['S1', 'S1c']),
            ('dgsm', {'samples': 40}, ['asq', 'asqCi', 'asqSd']),
        ]
        for method, options, want in cases:
            d = G.build_design(method, keys, options, seed=3, **STREAMS)
            self.assertEqual(d['runs'], G.gsa_runs(method, 3, options), method)
            yy = design_outputs(d['u'], ishi)
            t1 = G.gsa_table(d, yy, next=stream_for(3, '#gsa#bootstrap'))
            t2 = G.gsa_table(d, yy, next=stream_for(3, '#gsa#bootstrap'))
            self.assertEqual(json.dumps(t1['rows']), json.dumps(t2['rows']),
                             f'{method}: the same table came out different')
            keys_of = [c[0] for c in t1['columns']]
            for key in want:
                self.assertIn(key, keys_of, method)
                self.assertTrue(all(math.isfinite(row['values'][key]) for row in t1['rows']), f'{method}: {key}')
            if method == 'ff':
                self.assertTrue(len(t1['pairs']) == 3 and all(math.isfinite(q['value']) for q in t1['pairs']))
            if method == 'rbdfast':
                self.assertEqual(t1['rows'][0]['k'], 1)
            if method in ('radial', 'sobol'):
                self.assertIn(t1['rows'][0]['k'], (0, 1))
        plain = G.build_design('radial', keys, {'samples': 20, 'resamples': 0}, seed=3, **STREAMS)
        self.assertFalse(any(c[0] == 'STci' for c in G.gsa_table(plain, np.arange(plain['runs']) % 7)['columns']))


@needs_fixtures
class GlobalSensitivityReference(_Reference):
    """The global sensitivity methods give GlobalSensitivity.jl's numbers on the same designs (test/run.js)."""

    area = 'GSA.jl ref'

    @classmethod
    def setUpClass(cls):
        cls.ref = json.loads((FIXTURES / 'gsa-reference.json').read_text('utf-8'))

    @staticmethod
    def ishi(x: List[float]) -> float:
        return math.sin(x[0]) + 7 * math.sin(x[1]) ** 2 + 0.1 * x[2] ** 4 * math.sin(x[0])

    def test_sobol(self):
        ref = self.ref
        self.assertEqual(ref['version'], '2.12.8')
        Sr = ref['sobol']
        A = [_b64f(v) for v in Sr['A']]
        B = [_b64f(v) for v in Sr['B']]
        d = G.sobol_design(Sr['d'], Sr['n'], second=True, draw=lambda k, w, b: A[k] if w == 'A' else B[k])
        y = _b64f(Sr['y'])
        self.close('sobol design', design_outputs(d['u'], self.ishi), y, 1e-12)
        for est, want in Sr['estimators'].items():
            r = G.sobol_indices(y, {'K': Sr['d'], 'n': Sr['n'], 'second': True, 'estimator': est})
            self.close(f'sobol {est} S1', r['S1'], _b64f(want['S1']), 1e-9)
            self.close(f'sobol {est} ST', r['ST'], _b64f(want['ST']), 1e-9)
            self.close(f'sobol {est} S2', r['S2'], np.concatenate([_b64f(row) for row in want['S2']]), 1e-9)
        Bk = Sr['blocks']
        A2 = [_b64f(v) for v in Bk['A']]
        B2 = [_b64f(v) for v in Bk['B']]
        d2 = G.sobol_design(Sr['d'], Sr['n'], blocks=2,
                            draw=lambda k, w, b: (A2[k] if w == 'A' else B2[k])[b * Sr['n']:(b + 1) * Sr['n']])
        y2 = _b64f(Bk['y'])
        self.close('sobol blocks design', design_outputs(d2['u'], self.ishi), y2, 1e-12)
        r2 = G.sobol_indices(y2, {'K': Sr['d'], 'n': Sr['n'], 'blocks': 2})
        self.close('sobol blocks S1', r2['S1'], _b64f(Bk['S1']), 1e-9)
        self.close('sobol blocks ST', r2['ST'], _b64f(Bk['ST']), 1e-9)
        self.close('sobol blocks S1 interval', r2['S1ci'], _b64f(Bk['S1ci']), 1e-7)
        self.close('sobol blocks ST interval', r2['STci'], _b64f(Bk['STci']), 1e-7)

    def test_efast_rbd_morris_ff_dgsm_shapley(self):
        ref = self.ref

        def to_box(u: List[float]) -> List[float]:
            return [-math.pi + 2 * math.pi * v for v in u]

        def lin5(x: List[float]) -> float:
            return x[0] + 2 * x[1] + 3 * x[2] + 0.5 * x[3] + 0.1 * x[4] * x[0]

        for c in ref['efast']:
            de = G.efast_design(c['K'], c['N'], phases=list(_b64f(c['phases'])))
            ye = _b64f(c['y'])
            f = self.ishi if c['K'] == 3 else lin5
            self.close(f"efast {c['K']} design", design_outputs(de['u'], lambda u, f=f: f(to_box(u))), ye, 1e-9)
            r = G.efast_indices(ye, de)
            self.close(f"efast {c['K']} S1", r['S1'], _b64f(c['S1']), 1e-9)
            self.close(f"efast {c['K']} ST", r['ST'], _b64f(c['ST']), 1e-9)
        for c in ref['rbdfast']:
            dr = G.rbd_fast_design(c['K'], c['N'], perms=c['perms'])
            yr = _b64f(c['y'])
            self.close(f"rbd-fast {c['N']} design", design_outputs(dr['u'], lambda u: self.ishi(to_box(u))), yr, 1e-12)
            self.close(f"rbd-fast {c['N']} S1", G.rbd_fast_indices(yr, dr), _b64f(c['S1']), 1e-9)
        for which in ('plain', 'relative'):
            c = ref['morris'][which]
            r = G.morris_indices(_b64f(c['y']), {'K': 4, 'trajectories': ref['morris']['trajectories'],
                                                 'points': ref['morris']['points'],
                                                 'u': np.array([_b64f(v) for v in c['u']])},
                                 relative=which == 'relative')
            self.close(f'morris {which} mean', r['mean'], _b64f(c['mean']), 1e-9)
            self.close(f'morris {which} mu*', r['meanStar'], _b64f(c['meanStar']), 1e-9)
            self.close(f'morris {which} variance', r['variance'], _b64f(c['variance']), 1e-9)
        df = G.ff_design(ref['ff']['K'], low=ref['ff']['low'], high=ref['ff']['high'])
        rf = G.ff_indices(design_outputs(df['u'], lambda x: 3 * x[0] - 2 * x[1] + x[2] * x[3] + 0.5 * x[4]), df)
        self.close('ff main effects', rf['main'], _b64f(ref['ff']['main'])[:ref['ff']['K']], 1e-9)
        self.close('ff squared', rf['squared'], _b64f(ref['ff']['squared'])[:ref['ff']['K']], 1e-9)
        X = [_b64f(v) for v in ref['dgsm']['x']]
        N = len(X[0])
        grad = np.zeros(N * 3)
        H = np.zeros(N * 9)
        for i in range(N):
            grad[i * 3] = 1 + X[1][i] ** 2
            grad[i * 3 + 1] = 2 + 2 * X[0][i] * X[1][i]
            grad[i * 3 + 2] = 6
            H[i * 9 + 1] = H[i * 9 + 3] = 2 * X[1][i]
            H[i * 9 + 4] = 2 * X[0][i]
        rd = G.dgsm_statistics(grad, X, H=H)
        for k in ('a', 'absa', 'asq', 'sigma', 'tao'):
            self.close(f'dgsm {k}', rd[k], _b64f(ref['dgsm'][k]), 1e-9)

        def off(a: Any) -> List[float]:
            return [0.0 if i // 3 == i % 3 else v for i, v in enumerate(np.asarray(a).tolist())]

        flat = lambda rows: off(np.concatenate([_b64f(r) for r in rows]))  # noqa: E731
        self.close('dgsm crossed', off(rd['crossed']['mean']), flat(ref['dgsm']['crossed']), 1e-9)
        self.close('dgsm crossed squared', off(rd['crossed']['sq']), flat(ref['dgsm']['crossedsq']), 1e-9)
        c = ref['shapley']
        rs = G.shapley_indices(_b64f(c['y']), {'K': c['K'], 'orders': G.permutations_of(c['K']), 'nVar': c['nVar'],
                                               'nOuter': c['nOuter'], 'nInner': c['nInner']})
        self.close('shapley effects', rs['effects'], _b64f(c['effects']), 1e-9)
        self.close('shapley standard errors', rs['stdErr'], _b64f(c['stdErr']), 1e-9)

    def test_from_a_sample(self):
        ref = self.ref
        XD = [_b64f(v) for v in ref['delta']['x']]
        YD = _b64f(ref['delta']['y'])
        delta = [G.delta_moment(x, YD, resamples=ref['delta']['resamples'][k]) for k, x in enumerate(XD)]
        self.close('delta', [v['delta'] for v in delta], _b64f(ref['delta']['delta']), 1e-8)
        self.close('delta adjusted', [v['adjusted'] for v in delta], _b64f(ref['delta']['adjusted']), 1e-8)
        self.close('delta interval', [v['low'] for v in delta], _b64f(ref['delta']['low']), 1e-7)
        XE = [_b64f(v) for v in ref['easi']['x']]
        YE = _b64f(ref['easi']['y'])
        self.close('easi', [G.easi(x, YE)['s1'] for x in XE], _b64f(ref['easi']['S1']), 1e-9)
        self.close('easi corrected', [G.easi(x, YE)['s1c'] for x in XE], _b64f(ref['easi']['S1c']), 1e-9)
        self.close('easi dct', [G.easi(x, YE, dct=True)['s1'] for x in XE], _b64f(ref['easi']['dctS1']), 1e-9)
        XO = [_b64f(v) for v in ref['easi']['odd']['x']]
        self.close('easi odd', [G.easi(x, _b64f(ref['easi']['odd']['y']))['s1'] for x in XO],
                   _b64f(ref['easi']['odd']['S1']), 1e-9)
        XR = [_b64f(v) for v in ref['rsa']['x']]
        K = ref['rsa']['K']
        rr = G.rsa(XR[:K], _b64f(ref['rsa']['y']), dummies=XR[K:])
        self.close('rsa', rr['scores'], _b64f(ref['rsa']['S']), 1e-9)
        self.close('rsa dummies', [rr['dummyMean']], [ref['rsa']['dummyMean']], 1e-9)
        # GlobalSensitivity.jl's spread of the dummies leaves the first one out; this takes all of them.
        rest = G.rsa(XR[K + 1:], _b64f(ref['rsa']['y']))['scores']
        m = sum(rest) / len(rest)
        self.close('rsa dummies, as Julia takes them', [math.sqrt(sum((v - m) ** 2 for v in rest) / (len(rest) - 1))],
                   [ref['rsa']['dummySdSkippingFirst']], 1e-9)
        XM = [_b64f(v) for v in ref['mi']['x']]
        mi = [G.mutual_information(x, _b64f(ref['mi']['y']),
                                   shuffles=ref['mi']['shuffles'][k]) for k, x in enumerate(XM)]
        self.close('mutual information', [v['mi'] for v in mi], _b64f(ref['mi']['mi']), 1e-9)
        self.close('mutual information, chance level', [v['bound'] for v in mi], _b64f(ref['mi']['bounds']), 1e-9)


# ---------------------------------------------------------------------------
# Known answers: the application's other tests of these modules.
# ---------------------------------------------------------------------------


class KnownAnswers(unittest.TestCase):
    """What test/run.js asks of these modules beyond the reference fixtures."""

    def test_fft_is_the_dft(self):
        nxt = rng(3)
        for n in (1, 2, 3, 5, 8, 16, 17, 100, 257, 1000):
            x = np.array([nxt() - 0.5 for _ in range(n)])
            f = F.rfft(x)
            self.assertEqual(len(f['re']), n // 2 + 1)
            k = np.arange(len(f['re']))[:, None]
            j = np.arange(n)[None, :]
            a = (x * np.cos(2 * math.pi * k * j / n)).sum(axis=1)
            b = -(x * np.sin(2 * math.pi * k * j / n)).sum(axis=1)
            self.assertTrue(np.all(np.abs(f['re'] - a) < 1e-11 * n) and np.all(np.abs(f['im'] - b) < 1e-11 * n), n)
            self.assertTrue(np.all(np.abs(F.irfft(f, n) - x) < 1e-12), n)
            cr = x.copy()
            ci = x / 3
            F.fft(cr, ci, -1)
            F.fft(cr, ci, 1)
            self.assertTrue(np.all(np.abs(cr / n - x) < 1e-12), n)
            X = F.dct2(x)
            self.assertLess(abs(float((x * x).sum()) - float((X * X).sum())), 1e-12 * n)

    def test_correlations_by_hand(self):
        x = np.array([1.0, 2, 3, 4, 5])
        self.assertAlmostEqual(S.pearson(x, 2 * x), 1, places=12)
        self.assertAlmostEqual(S.pearson(x, np.array([4.0, 1, -2, -5, -8])), -1, places=12)
        self.assertAlmostEqual(S.pearson(x, np.array([2.0, 1, 4, 3, 5])), 0.8, places=12)
        self.assertTrue(math.isnan(S.pearson(x, np.full(5, 3.0))))
        self.assertEqual(S.rank(np.array([10.0, 20, 20, 40])).tolist(), [1, 2.5, 2.5, 4])
        xs = np.arange(1, 9, dtype=float)
        self.assertAlmostEqual(S.spearman(xs, xs ** 4), 1, places=12)
        self.assertLess(S.pearson(xs, xs ** 4), 0.95)

    def test_regression_family(self):
        N = 800
        cols = [uniforms(N, stream_for(11, name)) for name in ('x1', 'x2', 'x3')]
        noise = uniforms(N, stream_for(11, 'noise'))
        y = 2 * cols[0] + cols[1] + 0.05 * (noise - 0.5)
        m = S.regression_measures(cols, y)
        self.assertTrue(m['ok'] and m['used'] == N)
        self.assertGreater(m['r2'], 0.99)
        self.assertAlmostEqual(m['src'][0] / m['src'][1], 2, delta=0.1)
        self.assertAlmostEqual(m['src'][0], 2 / math.sqrt(5), delta=0.03)
        self.assertLess(abs(m['src'][2]), 0.03)
        self.assertTrue(m['pcc'][0] > 0.99 and m['pcc'][1] > 0.99 and abs(m['pcc'][2]) < 0.1)
        konst = np.full(N, 3.0)
        mk = S.regression_measures([cols[0], konst], y)
        self.assertTrue(mk['ok'] and math.isnan(mk['src'][1]) and math.isfinite(mk['src'][0]))
        dup = S.regression_measures([cols[0], cols[0].copy()], y)
        self.assertTrue(not dup['ok'] and math.isnan(dup['r2']))
        mono = np.exp(-5 * cols[0])
        perfect = S.regression_measures([cols[0], cols[2]], mono, translate='rank')
        self.assertTrue(perfect['ok'])
        self.assertAlmostEqual(perfect['r2'], 1, delta=1e-9)
        self.assertAlmostEqual(perfect['src'][0], -1, delta=1e-6)
        self.assertAlmostEqual(perfect['pcc'][0], -1, delta=1e-6)
        self.assertTrue(abs(perfect['src'][1]) < 1e-6 and abs(perfect['pcc'][1]) < 1e-3)
        self.assertFalse(S.regression_measures(cols, y[:3])['ok'])
        mask = np.zeros(N, dtype=np.uint8)
        mask[::2] = 1
        self.assertEqual(S.regression_measures(cols, y, mask=mask)['used'], N // 2)
        yq = (cols[0] - 0.5) ** 2
        self.assertLess(abs(S.spearman(cols[0], yq)), 0.05)
        self.assertGreater(S.first_order_index(cols[0], yq), 0.9)
        self.assertLess(S.first_order_index(cols[2], yq), 0.05)
        self.assertAlmostEqual(S.first_order_index(cols[0], y) / S.first_order_index(cols[1], y), 4, delta=0.6)
        self.assertTrue(math.isnan(S.first_order_index(konst, y)))
        lx = np.exp(1 + 3 * cols[0])
        ly = 5 * lx ** 2
        on_logs = S.regression_measures([lx], ly, translate='log')
        self.assertTrue(on_logs['ok'] and abs(on_logs['r2'] - 1) < 1e-9)
        self.assertAlmostEqual(on_logs['b'][0], 2, delta=1e-9)
        self.assertAlmostEqual(on_logs['src'][0], 1, delta=1e-9)
        with_zero = lx.copy()
        with_zero[0] = 0
        with_zero[1] = -3
        some = S.regression_measures([with_zero], ly, translate='log')
        self.assertTrue(some['ok'] and some['dropped'] == 2 and some['used'] == N - 2)
        fit = S.line_fit(1 + 0.05 * np.arange(240), 3 + 2 * (1 + 0.05 * np.arange(240)))
        self.assertTrue(fit['ok'] and abs(fit['a'] - 3) < 1e-9 and abs(fit['b'] - 2) < 1e-9)

    def test_categories(self):
        outputs = [{'label': 'Dose'}, {'label': 'Other'}]
        values = [np.array([1.0, 2, 3, 0, 0, 9, 5, 1, 1, 0, 0, 0]), np.zeros(12)]
        cats = C.categories_of({'simulation': {'categories': [
            {'label': 'high peak', 'output': 'Dose', 'stat': 'max', 'op': '>', 'value': 4},
            {'label': 'ends low', 'output': 'Dose', 'stat': 'final', 'op': '<=', 'value': 1, 'include': False},
        ]}})
        got = C.classify(cats, {'outputs': outputs, 'values': values, 't': np.zeros(3), 'iterations': 4})
        self.assertEqual(got['member'].tolist(), [2, 0, 0, 1])
        self.assertEqual(got['counts'], [2, 1, 1])
        self.assertEqual(C.include_mask(cats, got['member']).tolist(), [1, 1, 1, 0])
        self.assertIsNone(C.include_mask([dict(c, include=True) for c in cats], got['member']))
        self.assertEqual(C.statistic_of(values[0], 3, 1, 'max', 0), 9)
        self.assertEqual(C.statistic_of(values[0], 3, 1, 'min', 0), 0)
        self.assertEqual(C.statistic_of(values[0], 3, 0, 'final', 0), 3)
        self.assertEqual(C.statistic_of(values[0], 3, 0, 'at', 1), 2)
        between = C.categories_of({'simulation': {'categories': [
            {'label': 'mid', 'output': 'Dose', 'stat': 'final', 'op': 'between', 'value': 3, 'value2': 0.5}]}})
        self.assertEqual(C.classify(between,
                                    {'outputs': outputs, 'values': values, 'times': 3, 'iterations': 4})['counts'],
                         [2, 2])
        bad = C.categories_of({'simulation': {'categories': [
            {'label': 'x', 'output': 'Gone', 'stat': 'max', 'op': '>', 'value': 1},
            {'label': 'y', 'output': 'Dose', 'stat': 'max', 'op': 'between', 'value': 1},
            {'label': 'z', 'output': '', 'stat': 'max', 'op': '>'},
        ]}})
        said = C.category_problems(bad, ['Dose'])
        self.assertEqual(len(said), 4)
        self.assertIn('did not keep Gone', said[0])
        self.assertIn('second value', said[1])
        miss = C.classify(bad, {'outputs': outputs, 'values': values, 't': np.zeros(3), 'iterations': 4})
        self.assertEqual(miss['missing'], ['Gone'])
        self.assertEqual(C.describe_category(cats[0]), 'Dose: peak > 4')

    def test_designed_methods_find_known_answers(self):
        ctx = dict(seed=5, **STREAMS)

        def at(t: Dict[str, Any], key: str) -> List[float]:
            return [next(r for r in t['rows'] if r['k'] == k)['values'][key] for k in range(3)]

        def near(got: List[float], want: List[float], tol: float, what: str) -> None:
            for g, w in zip(got, want):
                self.assertLess(abs(g - w), tol, f'{what}: {got} against {want}')

        def ishi(u: List[float]) -> float:
            x = [-math.pi + 2 * math.pi * v for v in u]
            return math.sin(x[0]) + 7 * math.sin(x[1]) ** 2 + 0.1 * x[2] ** 4 * math.sin(x[0])

        S1 = [0.3139, 0.4424, 0]
        ST = [0.5576, 0.4424, 0.2437]
        sob = G.build_design('sobol', ['a', 'b', 'c'], {'samples': 8000}, **ctx)
        ts = G.gsa_table(sob, design_outputs(sob['u'], ishi))
        near(at(ts, 'S1'), S1, 0.03, 'Sobol S1')
        near(at(ts, 'ST'), ST, 0.03, 'Sobol ST')
        ef = G.build_design('efast', ['a', 'b', 'c'], {'samples': 2000}, **ctx)
        te = G.gsa_table(ef, design_outputs(ef['u'], ishi))
        near(at(te, 'S1'), S1, 0.02, 'eFAST S1')
        near(at(te, 'ST'), ST, 0.05, 'eFAST ST')
        rb = G.build_design('rbdfast', ['a', 'b', 'c'], {'samples': 4000}, **ctx)
        near(at(G.gsa_table(rb, design_outputs(rb['u'], ishi)), 'S1'), S1, 0.03, 'RBD-FAST S1')
        self.assertEqual((G.efast_samples(1001), G.efast_samples(1000), G.efast_samples(10)), (1002, 1000, 66))

        def lin(u: List[float]) -> float:
            return u[0] + 2 * u[1] + 3 * u[2]

        mo = G.build_design('morris', ['a', 'b', 'c'], {'trajectories': 20}, **ctx)
        tm = G.gsa_table(mo, design_outputs(mo['u'], lin))
        near(at(tm, 'meanStar'), [1, 2, 3], 1e-9, 'Morris mu*')
        near(at(tm, 'sd'), [0, 0, 0], 1e-9, 'Morris sigma')
        ff = G.build_design('ff', ['a', 'b', 'c'], {}, **ctx)
        near(at(G.gsa_table(ff, design_outputs(ff['u'], lin)), 'main'), [0.45, 0.9, 1.35], 1e-12,
             'fractional factorial')
        dg = G.build_design('dgsm', ['a', 'b', 'c'], {'samples': 50}, **ctx)
        near(at(G.gsa_table(dg, design_outputs(dg['u'], lin)), 'asq'), [1, 4, 9], 1e-6, 'DGSM nu')
        sh = G.build_design('shapley', ['a', 'b', 'c'], {'perms': 0, 'nVar': 4000, 'nOuter': 400}, **ctx)
        near(at(G.gsa_table(sh, design_outputs(sh['u'], lin)), 'effect'), [1 / 14, 4 / 14, 9 / 14], 0.04, 'Shapley')
        corr = [1, 0.5, 0, 0.5, 1, 0, 0, 0, 1]
        sc = G.build_design('shapley', ['a', 'b', 'c'], {'perms': 0, 'nVar': 4000, 'nOuter': 400}, corr=corr, **ctx)
        tc = G.gsa_table(sc, design_outputs(sc['u'], lambda u: sum(G.normal_quantile(v) for v in u)))
        near(at(tc, 'effect'), [0.375, 0.375, 0.25], 0.04, 'Shapley, correlated')
        near([sum(at(tc, 'effect'))], [1], 1e-9, 'Shapley total')
        for mid in G.GSA_METHOD_IDS:
            d0 = G.build_design(mid, ['a', 'b', 'c', 'd'], {}, **ctx)
            self.assertEqual(d0['runs'], G.gsa_runs(mid, 4, {}), mid)
            self.assertTrue(all(len(col) == d0['runs'] and all(0 < v < 1 for v in col) for col in d0['u']), mid)
        self.assertIn('12!', G.gsa_refusal('shapley', 12, {'perms': 0}))
        self.assertTrue(G.gsa_refusal('ff', 3, {'low': 0.9, 'high': 0.1}))
        one = G.build_design('sobol', ['a', 'b'], {'samples': 50}, **ctx)
        two = G.build_design('sobol', ['a', 'b', 'c'], {'samples': 50}, **ctx)
        self.assertTrue(np.array_equal(one['u'][0][:100], two['u'][0][:100]))

    def test_designs_with_the_package_streams(self):
        """build_design without streams uses kompartment.stats.sample's, which must be the application's."""
        try:
            from kompartment.stats import sample  # pylint: disable=import-outside-toplevel
            sample.stream_for, sample.uniforms  # pylint: disable=pointless-statement
        except (ImportError, AttributeError):
            self.skipTest('kompartment.stats.sample is not there yet')
        for method, options in (('sobol', {'samples': 40}), ('radial', {'samples': 12}), ('dgsm', {'samples': 8}),
                                ('rbdfast', {'samples': 64}), ('efast', {'samples': 70}),
                                ('morris', {'design': 'trajectories', 'candidates': 12}), ('shapley', {'nVar': 20})):
            mine = G.build_design(method, ['a', 'Kd[Cs-137]', 'c'], options, seed=11)
            want = G.build_design(method, ['a', 'Kd[Cs-137]', 'c'], options, seed=11, **STREAMS)
            self.assertTrue(np.array_equal(mine['u'], want['u']), method)


if __name__ == '__main__':
    unittest.main()
