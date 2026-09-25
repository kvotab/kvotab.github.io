"""Distributions, sampling, correlations, fits and summaries against the application's own.

Every test runs the application's modules -- ``src/domain/pdf.js``,
``sample.js``, ``correlate.js``, ``fit.js`` and ``distribution.js`` -- through
Node (``tests/node/stats_sampling.mjs``) beside this package's ports in
:mod:`kompartment.stats`, on the same inputs, and compares the answers.

What has to match exactly: the generator's raw output, every per-name stream,
every column of uniforms, integers, strings, booleans and the order of a
permutation. Floats are compared to a relative 1e-12: the ports do V8's own
``exp`` and ``log`` and agree bit for bit almost everywhere, but a result that
passes through ``phi``/``probit`` (:mod:`kompartment.stats._normal`, which uses
Python's ``math``) or a power (the platform's ``pow``) may differ in the last
bit or two. Where a test allows more, it says why. The largest difference seen
in each area, and how many floats were identical, is printed at the end.
"""

from __future__ import annotations

import json
import math
import subprocess
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from helpers import NODE, SRC, example, needs_app

from kompartment.stats import _normal
from kompartment.stats import correlate as C
from kompartment.stats import distribution as D
from kompartment.stats import fit as F
from kompartment.stats import pdf as P
from kompartment.stats import sample as S

SCRIPT = Path(__file__).resolve().parent / 'node' / 'stats_sampling.mjs'


class _Undefined:
    def __repr__(self) -> str:
        return 'undefined'


UNDEFINED = _Undefined()
_SPECIAL = {'NaN': math.nan, 'Infinity': math.inf, '-Infinity': -math.inf, '-0': -0.0,
            'undefined': UNDEFINED, 'function': 'function'}


def _enc(x: Any) -> Any:
    """A value as the script reads it (see its header)."""
    if x is None or isinstance(x, (bool, str)):
        return x
    if x is UNDEFINED:
        return {'$': 'undefined'}
    if isinstance(x, np.ndarray):
        tag = {'float32': '$f32', 'uint8': '$u8', 'bool': '$u8'}.get(str(x.dtype), '$f64')
        return {tag: [_enc(v) for v in x.ravel().tolist()]}
    if isinstance(x, (np.integer, np.floating)):
        x = x.item()
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        if x != x:
            return {'$': 'NaN'}
        if math.isinf(x):
            return {'$': 'Infinity' if x > 0 else '-Infinity'}
        if x == 0 and math.copysign(1.0, x) < 0:
            return {'$': '-0'}
        return x
    if isinstance(x, (list, tuple)):
        return [_enc(v) for v in x]
    if isinstance(x, dict):
        return {str(k): _enc(v) for k, v in x.items()}
    raise TypeError(f'cannot send {type(x).__name__} to the script')


def _dec(x: Any) -> Any:
    if isinstance(x, list):
        return [_dec(v) for v in x]
    if isinstance(x, dict):
        if list(x) == ['$']:
            return _SPECIAL[x['$']]
        return {k: _dec(v) for k, v in x.items()}
    return x


def _parse_int(text: str) -> Any:
    # JSON.stringify writes an integral double below 1e21 without an exponent;
    # past 2**53 that is a float that happens to be whole, not an integer.
    v = int(text)
    return v if abs(v) < 2 ** 53 else float(text)


def js(calls: List[List[Any]]) -> List[Dict[str, Any]]:
    """Runs the calls through the application's modules: one ``{value}`` or ``{error, type}`` each."""
    assert NODE is not None
    proc = subprocess.run([NODE, str(SCRIPT), str(SRC)], input=json.dumps(_enc({'calls': calls})),
                          capture_output=True, text=True, timeout=600, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return [_dec(r) for r in json.loads(proc.stdout, parse_int=_parse_int)['results']]


def values(calls: List[List[Any]]) -> List[Any]:
    """The values of the calls, failing on any the application refused."""
    out = []
    for call, r in zip(calls, js(calls)):
        if 'error' in r:
            raise AssertionError(f'{call[:2]}: the application raised {r["type"]}: {r["error"]}')
        out.append(r['value'])
    return out


# ---------------------------------------------------------------------------
# Comparing, and keeping count.
# ---------------------------------------------------------------------------

WORST: Dict[str, float] = {}
TALLY: Dict[str, List[int]] = {}


def _plain(x: Any) -> Any:
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (np.integer, np.floating, np.bool_)):
        return x.item()
    if isinstance(x, tuple):
        return list(x)
    return x


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _compare(py: Any, want: Any, area: str, rtol: float, atol: float, path: str, out: List[str]) -> None:
    py = _plain(py)
    tally = TALLY.setdefault(area, [0, 0])
    if want is UNDEFINED and _is_number(py) and py != py:
        return  # an index out of range: undefined there, NaN here
    if isinstance(py, bool) or isinstance(want, bool):
        if py is not want:
            out.append(f'{path}: {py!r} != {want!r}')
        return
    if _is_number(py) and _is_number(want):
        tally[1] += 1
        if py == want or (py != py and want != want):
            tally[0] += 1
            return
        if isinstance(py, int) and isinstance(want, int):
            out.append(f'{path}: {py} != {want} (integers)')
            return
        if math.isinf(py) or math.isinf(want) or py != py or want != want:
            out.append(f'{path}: {py!r} != {want!r}')
            return
        diff = abs(py - want)
        scale = max(abs(py), abs(want))
        WORST[area] = max(WORST.get(area, 0.0), diff / scale)
        if diff > rtol * scale + atol:
            out.append(f'{path}: {py!r} != {want!r} (relative {diff / scale:.2e})')
        return
    if isinstance(py, str) or isinstance(want, str) or py is None or want is None:
        if py != want or type(py) is not type(want):
            out.append(f'{path}: {py!r} != {want!r}')
        return
    if isinstance(py, list) and isinstance(want, list):
        if len(py) != len(want):
            out.append(f'{path}: {len(py)} items != {len(want)}')
            return
        for i, (a, b) in enumerate(zip(py, want)):
            _compare(a, b, area, rtol, atol, f'{path}[{i}]', out)
        return
    if isinstance(py, dict) and isinstance(want, dict):
        if list(py) != list(want):
            out.append(f'{path}: keys {list(py)} != {list(want)}')
            return
        for k in py:
            _compare(py[k], want[k], area, rtol, atol, f'{path}/{k}', out)
        return
    out.append(f'{path}: {type(py).__name__} {py!r:.60} != {type(want).__name__} {want!r:.60}')


def assert_same(tc: unittest.TestCase, py: Any, want: Any, area: str, rtol: float = 1e-12,
                atol: float = 0.0, what: str = '') -> None:
    """Fails with every difference between ``py`` and ``want`` beyond the tolerance."""
    out: List[str] = []
    _compare(py, want, area, rtol, atol, what, out)
    if out:
        tc.fail(f'{area}: {len(out)} differences\n' + '\n'.join(out[:25]))


def tearDownModule() -> None:  # noqa: N802 -- unittest's name
    if not TALLY:
        return
    lines = ['', 'stats parity: identical floats / compared, largest relative difference']
    for area in sorted(TALLY):
        same, total = TALLY[area]
        lines.append(f'  {area:28s} {same:7d} / {total:7d}   {WORST.get(area, 0.0):.2e}')
    print('\n'.join(lines))


# ---------------------------------------------------------------------------
# The inputs: made-up distributions of every kind.
# ---------------------------------------------------------------------------


def spec(kind: str, trmin: Any = None, trmax: Any = None, pmin: Any = None, pmax: Any = None,
         group: Any = None, values: Any = None, inorder: Any = True, pos: Any = 0, **params: Any) -> Dict[str, Any]:
    return {'kind': kind, 'params': params, 'values': values, 'trmin': trmin, 'trmax': trmax,
            'pmin': pmin, 'pmax': pmax, 'group': group, 'inorder': inorder, 'pos': pos}


SHAPES = [
    spec('unif', min=2, max=8), spec('unif', min=-3.5, max=-1.25),
    spec('triang', min=1, max=9, mode=3), spec('triang', min=0, max=4, mode=0), spec('triang', min=0, max=4, mode=4),
    spec('dtriang', min=1, max=9, mode=3), spec('dtriang', min=0.6, max=1, mode=1),
    spec('dtriang', min=0, max=0.02, mode=0.005),
    spec('norm', mean=5, sd=1.5), spec('norm', mean=-2, sd=0.1),
    spec('logu', min=0.001, max=10), spec('logu', min=3e-9, max=4e-2),
    spec('logt', min=0.7, max=20, mode=3), spec('logt', min=7e-12, max=5e-11, mode=1e-11),
    spec('logt', min=1e-4, max=1, mode=1e-4),
    spec('logdt', min=0.7, max=20, mode=3), spec('logdt', min=0.7, max=20, mode=0.7),
    spec('Logn4', gm=0.002, gsd=5.2), spec('Logn4', gm=20, gsd=7),
    spec('logn', mean=4, sd=2), spec('logn', mean=2, sd=3),
    spec('logn5', p1=0.05, x1=1, p2=0.95, x2=100), spec('logn5', p1=0.01, x1=3, p2=0.5, x2=4),
]


def truncated(s: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The shape and its truncations: by value, by percentile, both, reversed, one-sided, at the ends."""
    lo = P.quantile(s, 0.2)
    hi = P.quantile(s, 0.7)
    cuts = [{}, {'trmin': lo, 'trmax': hi}, {'pmin': 0.05, 'pmax': 0.95},
            {'trmin': lo, 'trmax': hi, 'pmin': 0.3, 'pmax': 0.9}, {'trmin': hi, 'trmax': lo},
            {'trmin': lo}, {'pmax': 0.6}, {'pmin': 0, 'pmax': 1}, {'pmin': 0.5, 'pmax': 0.2},
            {'trmin': lo, 'pmax': 0.1}]
    return [dict(s, **c) for c in cuts]


ODD = [
    spec('unif', min=5, max=5), spec('unif', min=5, max=1), spec('triang', min=1, max=9, mode=12),
    spec('triang', min=1, max=9, mode=-3), spec('dtriang', min=2, max=2, mode=2),
    spec('norm', mean=0, sd=0), spec('norm', mean=0, sd=-1), spec('Logn4', gm=1, gsd=1),
    spec('Logn4', gm=1, gsd=0.5), spec('logn5', p1=0.5, x1=1, p2=0.5, x2=2),
    spec('logn5', p1=0.9, x1=1, p2=0.1, x2=2), spec('logn5', p1=0, x1=1, p2=1, x2=2),
    spec('logn5', p1=0.1, x1=-1, p2=0.9, x2=2), spec('logu', min=-1, max=10), spec('logt', min=0, max=10, mode=1),
    spec('logn', mean=0, sd=1), spec('logn', mean=-1, sd=1), spec('unif', min=0, max=6.5, trmin=6.5, trmax=0),
    spec('logt', min=1, max=100, mode=10, trmin=-5), spec('norm', mean=0, sd=1, trmin=-6, trmax=-5),
    spec('norm', mean=0, sd=1, pmin=1.5), spec('unif', min=0, max=1, pmin=-0.5),
    # Declared and not filled in, or not what a distribution holds.
    spec('Logn4', gm=None, gsd=None), spec('logt', min=1, max=None, mode=3),
    {'kind': 'unif', 'params': {'min': 1}}, {'kind': 'norm', 'params': None}, {'kind': 'norm'},
    {'kind': 'weibull', 'params': {'k': 1}}, {'kind': 'logt', 'params': {'min': 1, 'max': 10, 'mode': 2}},
]

LISTS = [
    spec('pg', values=[10, 20, 30]), spec('pg', values=[10, 20, 30], pos=2), spec('pg', values=[10, 20, 30], pos=-1),
    spec('pg', values=[10, 20, 30], pos=1.5), spec('pg', values=[10, 20, 30], inorder=False),
    spec('pg', values=[4.5]), spec('pg', values=[]), spec('pg', values=[3, 1, 2, 2, 8, -1], trmin=0, pmax=0.5),
    spec('pg', values=[3, 1, 2, 2, 8, -1], group='G1'), spec('pg', values=[1, 2], pmin=0, pmax=1),
    spec('pg', values=[7, 8, 9], pos=None), spec('pg', values=[7, 8, 9], pos='1'),
]

EVERY = [t for s in SHAPES for t in truncated(s)] + ODD + LISTS

US = [0.0, 1e-12, 1e-6, 0.001, 0.02, 0.02425, 0.1, 0.25, 0.5, 0.75, 0.9, 0.97575, 0.98, 0.999, 1 - 1e-9, 1.0,
      -0.1, 1.1]


def points(s: Dict[str, Any]) -> List[float]:
    """Where to read a distribution: across its support and past both ends."""
    out = [-1.0, 0.0, 1e-300, 1.0, 1e300]
    span = None
    try:
        span = P.support_of(s)
    except TypeError:
        pass
    if span:
        lo, hi = span
        for f in (-0.1, 0.0, 0.05, 0.3, 0.5, 0.7, 0.95, 1.0, 1.1):
            out.append(lo + f * (hi - lo))
    for v in (s.get('params') or {}).values():
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def sample_of(s: Dict[str, Any], n: int) -> np.ndarray:
    """The distribution's own quantiles: a sample with no noise in it."""
    return np.array([P.quantile(s, (i + 0.5) / n) for i in range(n)])


def drawn(s: Dict[str, Any], n: int, seed: int, name: str) -> np.ndarray:
    """``n`` values drawn from ``s`` on a stream, sorted."""
    u = S.uniforms(n, S.stream_for(seed, name))
    return np.sort(np.array([S.value_at_probability(s, x, i) for i, x in enumerate(u)]))


# ---------------------------------------------------------------------------
# V8's Math, which the ports are built on.
# ---------------------------------------------------------------------------


@needs_app
class V8Math(unittest.TestCase):
    def test_exp_log_log1p_expm1_are_v8_s_bit_for_bit(self):
        rs = np.random.default_rng(20260925)
        edges = [0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 1e-20, -1e-20, 2 ** -29, -2 ** -29, 2 ** -54, 5e-324,
                 1e-310, 2.2250738585072014e-308, 709.78, 709.8, -745.1, -745.2, 0.34657359, 1.03972077,
                 56 * 0.6931471805599453, -56 * 0.6931471805599453, 1 + 2 ** -52, 1 - 2 ** -53, -0.2929,
                 -0.29289, 0.41421, 0.4142, 1e300, 9007199254740992.0, math.inf, -math.inf, math.nan]
        args = np.concatenate([rs.uniform(-40, 40, 4000), rs.uniform(-750, 750, 1000),
                               np.exp(rs.uniform(-700, 700, 3000)), rs.uniform(-1, 1, 3000), edges])
        names = ['exp', 'log', 'log1p', 'expm1']
        got = values([['math', n, args.tolist()] for n in names])
        scalar = {'exp': P._exp, 'log': P._log, 'log1p': P._log1p, 'expm1': P._expm1}
        array = {'log': P._log_array, 'log1p': P._log1p_array}
        for name, want in zip(names, got):
            with self.subTest(fn=name):
                assert_same(self, [scalar[name](x) for x in args.tolist()], want, 'V8 Math (scalar)', rtol=0)
                if name in array:
                    assert_same(self, array[name](args), want, 'V8 Math (array)', rtol=0)


# ---------------------------------------------------------------------------
# pdf.js
# ---------------------------------------------------------------------------

TEXTS = [
    ('logt(min=7.0E-12,max=5.0E-11,mode=1.0E-11)', 'logt'), ('logn(gm=0.002,gsd=5.2)', 'Logn4'),
    ('logn(gm=0.002,gsd=5.2)', ''), ('logn(mean=4,sd=2)', ''), ('logn(p1=0.05,x1=1,p2=0.95,x2=100)', ''),
    ('logn(mean=4,sd=2)', 'logn5'), ('logn(gm,gsd)', ''), ('logn(gm,gsd)', 'Logn4'), ('logn()', ''),
    ('unif(min=0.0,max=6.5,trmin=6.5,trmax=0.0)', 'unif'), ('triang(min=1,max=9,mode=3)', ''),
    ('dtriang(min=1,max=9,mode=3,trmin=2,trmax=8)', ''), ('logdt(min=0.7,max=20,mode=3,pmin=0.05,pmax=0.95)', ''),
    ('norm(mean=5,sd=1.5,group=Kd rock)', 'norm'), ('norm( mean = 5 , sd = 1.5 )', ''),
    ('pg(values=10;20;30,inorder=true,pos=0)', 'pg'), ('pg(values=1;;2;,inorder=false,pos=3)', 'pg'),
    ('pg(values=,pos=x)', 'pg'), ('pg(values= 1 ; 2e3 ;abc; 0x10 ;Infinity; .5; 5.;1_000)', ''),
    ('unif(min=0x1A,max=1e400)', ''), ('unif(min=+.5,max=-0)', ''), ('unif(min=,max=  )', ''),
    ('unif(min=1,min=2,max=3)', ''), ('unif(min=1,max=2', ''), ('unif min=1', ''), ('9unif(min=1)', ''),
    ('weibull(k=1)', ''), ('weibull(k=1)', 'unif'), ('logt(min=1,max=9,mode=3)', 'triang'),
    ('\t logt(min=1,max=9,mode=3) \n', ''), ('﻿\xa0logu(min=1,max=9) ', ''),
    ('logu (min=1,max=9)  ', ''), ('logu(min=1,max=9) x', ''), ('logu(min=1,max=(9))', ''),
    ('logu(min=1,max=9)\n', ''), ('LOGU(min=1,max=9)', ''), ('norm(mean=1,sd=2,group=  )', ''),
    ('norm(mean=1,sd=2,group=7)', ''), ('norm(mean=1,sd=2,pmin=0.05)', 'norm'), ('', ''), ('   ', ''),
    ('norm(mean=1,sd=2,inorder=false,pos=4)', ''), ('pg(values=1;2)', 'nope'), ('logn(x1=1)', ''),
    ('logt(min=1,max=9,mode=3)', 'constructorx'), ('unif(min=1,max=2,trmin=Infinity)', ''),
]


@needs_app
class Distributions(unittest.TestCase):
    def test_the_tables_are_the_application_s(self):
        names = ['PDF_KINDS', 'PDF_KIND_IDS', 'TRUNCATION', 'PERCENTILE_TRUNCATION']
        for name, want in zip(names, values([['pdf', n] for n in names])):
            assert_same(self, getattr(P, name), want, 'pdf tables', rtol=0, what=name)

    def test_reading_writing_and_describing(self):
        calls = [['pdf', 'parsePDF', t, a] for t, a in TEXTS]
        calls += [['pdf', 'parsePDF', 5, ''], ['pdf', 'parsePDF', None, 'unif']]
        got = values(calls)
        parsed = [P.parse_pdf(t, a) for t, a in TEXTS] + [P.parse_pdf(5, ''), P.parse_pdf(None, 'unif')]
        assert_same(self, parsed, got, 'parse_pdf', rtol=0)
        specs = [p for p in parsed if p is not None] + EVERY
        calls = []
        for s in specs:
            calls += [['pdf', 'formatPDF', s], ['pdf', 'complete', s], ['pdf', 'describePDF', s],
                      ['pdf', 'pdfProblems', s]]
        got = values(calls)
        for k, s in enumerate(specs):
            with self.subTest(spec=P.format_pdf(s)):
                assert_same(self, [P.format_pdf(s), P.complete(s), P.describe_pdf(s), P.pdf_problems(s)],
                            got[4 * k:4 * k + 4], 'format/describe/problems', rtol=0)
        # The writing reads back as what it was written from.
        for s in specs:
            text = P.format_pdf(s)
            if text and s['kind'] != 'pg' and P.complete(s):
                back = P.parse_pdf(text, s['kind'])
                self.assertEqual(P.format_pdf(back), text)

    def test_numbers_are_written_as_javascript_writes_them(self):
        nums = [0.0, -0.0, 1.0, 1.5, 1e21, 1e-7, 1e-6, 123456789012345680000.0, 0.1 + 0.2, 5e-324, 1.7976931348623157e308,
                1.125, 9.995, 0.0001235, 12345.5, 1.00005, 99999.5, math.nan, math.inf, -math.inf, -2.5e-5, 314159.26]
        calls = []
        for x in nums:
            calls.append(['pdf', 'describePDF', spec('norm', mean=x, sd=1, trmin=x, pmax=0.123456)])
            calls.append(['pdf', 'formatPDF', spec('norm', mean=x, sd=1)])
            calls.append(['fit', 'fitText', {'kind': 'norm', 'params': {'mean': x, 'sd': x}}])
        got = values(calls)
        py = []
        for x in nums:
            py.append(P.describe_pdf(spec('norm', mean=x, sd=1, trmin=x, pmax=0.123456)))
            py.append(P.format_pdf(spec('norm', mean=x, sd=1)))
            py.append(F.fit_text({'kind': 'norm', 'params': {'mean': x, 'sd': x}}))
        assert_same(self, py, got, 'number formatting', rtol=0)

    def test_curves_cuts_and_supports(self):
        calls = []
        py = []
        for s in EVERY:
            xs = points(s)
            calls += [['pdf', 'cdfAt', s, x] for x in xs] + [['pdf', 'densityAt', s, x] for x in xs]
            calls += [['pdf', 'cumulativeAt', s, x] for x in xs] + [['pdf', 'quantile', s, u] for u in US]
            calls += [['pdf', 'probabilityCuts', s], ['pdf', 'valueCuts', s], ['pdf', 'valueCuts', s, -1.0, 99.0],
                      ['pdf', 'supportOf', s], ['pdf', 'curveOf', s, {'points': 40, 'bins': 7}],
                      ['pdf', 'curveOf', s, {'points': 2, 'bins': 0}]]
            py += [P.cdf_at(s, x) for x in xs] + [P.density_at(s, x) for x in xs]
            py += [P.cumulative_at(s, x) for x in xs] + [P.quantile(s, u) for u in US]
            py += [P.probability_cuts(s), P.value_cuts(s), P.value_cuts(s, -1.0, 99.0), P.support_of(s),
                   P.curve_of(s, points=40, bins=7), P.curve_of(s, points=2, bins=0)]
        for s in SHAPES[::4] + LISTS[:1]:  # the drawing as the editor asks for it
            calls.append(['pdf', 'curveOf', s])
            py.append(P.curve_of(s))
        got = js(calls)
        out: List[str] = []
        for call, mine, theirs in zip(calls, py, got):
            if 'error' in theirs:
                out.append(f'{call[:2]} {P.format_pdf(call[2])}: the application raised {theirs["error"]}')
                continue
            # Probabilities near a cut are differences of two nearly equal CDF values,
            # so a last-bit difference in the normal CDF is a larger relative one there.
            _compare(mine, theirs['value'], 'pdf curves', 1e-12, 1e-15, f'{call[1]} {P.format_pdf(call[2])}', out)
        if out:
            self.fail(f'{len(out)} differences\n' + '\n'.join(out[:30]))

    def test_the_normal_helpers_are_re_exported_and_agree(self):
        for name in ('phi', 'probit', 'normal_quantile', 'erf', 'erfc'):
            self.assertIs(getattr(P, name), getattr(_normal, name))
        zs = [-40, -8, -5, -3, -1, -1e-9, 0, 0.3, 1, 2, 5, 8, 40, math.inf, -math.inf, math.nan]
        ps = [0, 1e-300, 1e-12, 0.001, 0.02425, 0.02426, 0.3, 0.5, 0.97575, 0.97576, 0.999, 1 - 1e-12, 1, -1, 2]
        calls = [['pdf', 'phi', z] for z in zs] + [['pdf', 'probit', p] for p in ps]
        calls += [['pdf', 'normalQuantile', p] for p in ps]
        py = [P.phi(z) for z in zs] + [P.probit(p) for p in ps] + [P.normal_quantile(p) for p in ps]
        # Python's exp and log in `_normal` against V8's: the last bit or two.
        assert_same(self, py, values(calls), 'normal helpers', rtol=1e-13)

    def test_a_name_every_javascript_object_has_is_no_kind_there_or_here(self):
        # The application used to find Object's own property and throw; a kind
        # is now looked up by its own name only (kindInfo), on both sides.
        for name in ('constructor', 'toString', '__proto__', 'hasOwnProperty'):
            got = js([['pdf', 'parsePDF', 'unif(min=1,max=2)', name], ['pdf', 'complete', {'kind': name}],
                      ['pdf', 'describePDF', {'kind': name, 'params': {}}]])
            self.assertFalse(any('error' in r for r in got), (name, got))
            spec = P.parse_pdf('unif(min=1,max=2)', name)
            self.assertEqual(spec['kind'], 'unif', name)
            self.assertEqual(spec['kind'], got[0]['value']['kind'], name)
            self.assertEqual(P.complete({'kind': name}), got[1]['value'], name)
            self.assertIs(P.complete({'kind': name}), False)
            self.assertEqual(P.describe_pdf({'kind': name, 'params': {}}), got[2]['value'], name)


# ---------------------------------------------------------------------------
# sample.js
# ---------------------------------------------------------------------------

SEEDS = [0, 1, 2, 7, 42, 12345, 2 ** 31, 2 ** 32 - 1, 2 ** 32, 2 ** 32 + 5, -1, -123456789, 1.5, -2.7, 1e10, 3e15,
         math.nan, math.inf, None, '17', '0x10', '', 'abc', True]
NAMES = ['', 'k', 'Kd', 'Kd[Tc-99]', 'Kd[I-129]', 'SRF@8700', 'correlation:Kd[Cs-135]', 'Canisters#occurrences#733',
         'Ä sorption', '日本語', 'A😀B', '\ud800lone', 'x' * 300]


@needs_app
class Sampling(unittest.TestCase):
    def test_the_generator_is_the_application_s_bit_for_bit(self):
        got = values([['sample', 'rngSeq', s, 64] for s in SEEDS] + [['sample', 'rngSeq', UNDEFINED, 8]])
        for s, want in zip(SEEDS, got):
            g = S.rng(s)
            mine = [g() for _ in range(64)]
            assert_same(self, mine, want, 'rng', rtol=0, what=f'seed {s!r}')
            self.assertEqual(S.rng(s).take(64).tolist(), mine, f'take, seed {s!r}')
        g = S.rng()
        assert_same(self, [g() for _ in range(8)], got[-1], 'rng', rtol=0, what='no seed')
        # The counter wraps at 2**32 in a batch as it does one draw at a time.
        near_wrap = 2 ** 32 - 0x6D2B79F5 // 2
        one, many = S.rng(near_wrap), S.rng(near_wrap)
        self.assertEqual(many.take(7).tolist(), [one() for _ in range(7)])
        self.assertEqual(many.state, one.state)

    def test_names_hash_and_streams_as_the_application_s(self):
        calls = [['sample', 'hash', n] for n in NAMES]
        calls += [['sample', 'streamSeq', s, n, 24] for s in (1, 7, 2 ** 32 + 7, -3, 99.9, None) for n in NAMES]
        calls += [['sample', 'streamSeq', 5, n, 6] for n in (None, 12, 1.5, True, [1, 2])]
        calls += [['sample', 'hash', 12], ['sample', 'hash', 2.5]]
        got = values(calls)
        got, numbers = got[:-2], got[-2:]
        assert_same(self, [S.hash(12), S.hash(2.5)], numbers, 'hash and streams', rtol=0)
        mine: List[Any] = [S.hash(n) for n in NAMES]
        for s in (1, 7, 2 ** 32 + 7, -3, 99.9, None):
            for n in NAMES:
                g = S.stream_for(s, n)
                mine.append([g() for _ in range(24)])
        for n in (None, 12, 1.5, True, [1, 2]):
            g = S.stream_for(5, n)
            mine.append([g() for _ in range(6)])
        assert_same(self, mine, got, 'hash and streams', rtol=0)

    def test_uniforms_latin_and_not(self):
        cases = [(s, n, m, latin) for s in (1, 3, 7) for n in ('u', 'Kd[Tc-99]', None)
                 for m in (0, 1, 2, 3, 10, 257, 2000) for latin in (True, False)]
        got = values([['sample', 'uniformsOf', s, n, m, latin] for s, n, m, latin in cases])
        for (s, n, m, latin), want in zip(cases, got):
            gen = S.rng(s) if n is None else S.stream_for(s, n)
            mine = S.uniforms(m, gen, latin=latin)
            assert_same(self, mine, want, 'uniforms', rtol=0, what=f'{s} {n} {m} {latin}')
            # Any callable draws the same numbers, one at a time.
            gen = S.rng(s) if n is None else S.stream_for(s, n)
            assert_same(self, S.uniforms(m, lambda: gen(), latin=latin), want, 'uniforms', rtol=0)
        # Latin hypercube covers every slice; independent draws do not.
        n = 200
        self.assertEqual(len({math.floor(x * n) for x in S.uniforms(n, S.rng(5))}), n)
        self.assertLess(len({math.floor(x * n) for x in S.uniforms(n, S.rng(5), latin=False)}), 180)

    def test_a_value_at_a_probability(self):
        stream = S.uniforms(40, S.stream_for(11, 'probe')).tolist()
        calls = []
        py = []
        for s in EVERY:
            for i, u in enumerate(US + stream):
                calls.append(['sample', 'valueAtProbability', s, u, i])
                py.append(S.value_at_probability(s, u, i))
        got = js(calls)
        out: List[str] = []
        for call, mine, theirs in zip(calls, py, got):
            if 'error' in theirs:
                out.append(f'{P.format_pdf(call[2])}: the application raised {theirs["error"]}')
                continue
            _compare(mine, theirs['value'], 'value_at_probability', 1e-12, 0.0,
                     f'{P.format_pdf(call[2])} u={call[3]}', out)
        if out:
            self.fail(f'{len(out)} differences\n' + '\n'.join(out[:30]))
        # skbrnt's own numbers, as the application's tests pin them.
        near = lambda a, b: self.assertLessEqual(abs(a - b), 1e-13 * max(1, abs(b)))  # noqa: E731
        near(S.value_at_probability(P.parse_pdf('dtriang(min=1,max=9,mode=3,trmin=2,trmax=8)'), 0.25),
             2.6499158227686106)
        near(S.value_at_probability(P.parse_pdf('logdt(min=0.7,max=20,mode=3,pmin=0.05,pmax=0.95)'), 1),
             10.977088740209929)

    def test_a_plan_draws_the_application_s_sample(self):
        plan = [{'name': f'p{k}[{s["kind"]}]', 'spec': s} for k, s in enumerate(t for s in SHAPES for t in truncated(s)[:4])]
        plan += [{'name': 'list', 'spec': LISTS[0]}, {'name': 'shuffled', 'spec': LISTS[4]}]
        for seed, n, latin in ((1, 100, True), (7, 257, True), (2026, 50, False)):
            with self.subTest(seed=seed, n=n, latin=latin):
                got = values([['sample', 'draws', seed, plan, n, latin]])[0]
                for entry, want in zip(plan, got):
                    u = S.uniforms(n, S.stream_for(seed, entry['name']), latin=latin)
                    assert_same(self, u, want['u'], 'draws: uniforms', rtol=0)
                    vals = [S.value_at_probability(entry['spec'], x, i) for i, x in enumerate(u)]
                    assert_same(self, vals, want['values'], 'draws: values', what=entry['name'])

    def test_the_bundled_example_s_distributions(self):
        found: List[Any] = []

        def walk(x: Any, where: str) -> None:
            if isinstance(x, dict):
                for k, v in x.items():
                    if k == 'pdf' and isinstance(v, dict):
                        found.append((where, v))
                    walk(v, f'{where}/{k}')
            elif isinstance(x, list):
                for i, v in enumerate(x):
                    walk(v, f'{where}[{i}]')

        walk(example('biosphere'), '')
        self.assertGreater(len(found), 10)
        calls = []
        py: List[Any] = []
        for where, s in found:
            calls += [['pdf', 'formatPDF', s], ['pdf', 'describePDF', s], ['pdf', 'pdfProblems', s],
                      ['pdf', 'supportOf', s], ['pdf', 'curveOf', s], ['sample', 'draws', 5, [{'name': where, 'spec': s}], 500, True]]
            u = S.uniforms(500, S.stream_for(5, where))
            py += [P.format_pdf(s), P.describe_pdf(s), P.pdf_problems(s), P.support_of(s), P.curve_of(s),
                   [{'u': u, 'values': [S.value_at_probability(s, x, i) for i, x in enumerate(u)]}]]
        assert_same(self, py, values(calls), 'biosphere example')

    def test_the_distributed_slots_of_a_layout(self):
        kd = spec('logt', min=1e-3, max=1, mode=0.01)
        layout = {
            'lookupPoints': [
                {'slot': 9, 'name': 'SRF', 'at': 0, 'index': {}, 'spec': spec('triang', min=62, max=1911, mode=300)},
                {'slot': 10, 'name': 'SRF', 'at': 8700.5, 'index': {'Radionuclides': 'I-129'},
                 'spec': spec('unif', min=1, max=23)},
                {'slot': 11, 'name': 'SRF', 'at': 1e21, 'spec': spec('Logn4', gm=None, gsd=None)},
            ],
            'parameters': [
                {'block': {'name': 'k', 'pdf': spec('unif', min=0.1, max=0.3)}, 'name': 'k', 'dims': [], 'base': 0,
                 'width': 1},
                {'block': {'name': 'Kd', 'pdf': kd, 'entries': [
                    {'index': {'Radionuclides': 'Cs-135', 'Object': 'Mire'}, 'pdf': spec('norm', mean=1, sd=0.1)},
                    {'index': {'Radionuclides': 'I-129', 'Object': 'Lake'}, 'pdf': spec('logu', min=1, max=None)}]},
                 'name': 'Kd', 'dims': ['Radionuclides', 'Object'], 'base': 1, 'width': 4},
                {'block': {'name': 'rho'}, 'name': 'rho', 'dims': [], 'base': 5, 'width': 1},
            ],
            'indexSpace': {'Radionuclides': ['Cs-135', 'I-129'], 'Object': ['Lake', 'Mire']},
        }

        def tuple_at(space: Dict[str, List[str]], dims: List[str], off: int) -> Dict[str, str]:
            found: Dict[str, str] = {}
            rest = off
            for d in reversed(dims):
                found[d] = space[d][rest % len(space[d])]
                rest //= len(space[d])
            return {d: found[d] for d in dims}

        def effective(block: Dict[str, Any], key: str, tup: Dict[str, str]) -> Any:
            for e in block.get('entries', []):
                if tup and all(e['index'].get(k) == v for k, v in tup.items()):
                    if key in e:
                        return e[key]
            return block.get(key)

        want = values([['sample', 'slots', layout]])[0]
        assert_same(self, S.distributed_slots(layout, effective, tuple_at), want, 'distributed_slots', rtol=0)
        # snake_case spellings of the layout read the same.
        snake = {'lookup_points': layout['lookupPoints'], 'parameters': layout['parameters'],
                 'index_space': layout['indexSpace']}
        assert_same(self, S.distributed_slots(snake, effective, tuple_at), want, 'distributed_slots', rtol=0)

    def test_a_design_as_the_probabilistic_run_draws_it(self):
        def slot_name(e: Dict[str, Any]) -> str:
            idx = list((e.get('index') or {}).values())
            return f"{e['name']}[{']['.join(idx)}]" if idx else str(e.get('name', ''))

        def group_of(e: Dict[str, Any]) -> Optional[str]:
            g = (e.get('spec') or {}).get('group')
            t = '' if g is None else str(g).strip()
            return t or None

        kd = [{'name': 'Kd', 'index': {'Radionuclides': n}, 'spec': spec('logt', min=1e-3, max=1, mode=m)}
              for n, m in (('Cs-135', 0.01), ('I-129', 0.002), ('Tc-99', 0.1), ('Se-79', 0.05))]
        plan = kd + [
            {'name': 'soilLeach', 'index': {}, 'spec': spec('logu', min=1e-4, max=1e-2)},
            {'name': 'geoTransit', 'index': {}, 'spec': spec('norm', mean=100, sd=15, trmin=50)},
            {'name': 'cr', 'index': {'Eco': 'Lake'}, 'spec': spec('Logn4', gm=3, gsd=2, group='CR')},
            {'name': 'cr', 'index': {'Eco': 'Mire'}, 'spec': spec('logn', mean=5, sd=4, group=' CR ')},
            {'name': 'rho', 'index': {}, 'spec': spec('unif', min=1200, max=1800)},
            {'name': 'porosity', 'index': {}, 'spec': spec('triang', min=0.1, max=0.5, mode=0.3)},
        ]
        projects = [
            {'simulation': {}},
            {'simulation': {'correlations': [{'group': 'Kd', 'r': 0.9}, {'a': 'soilLeach', 'b': 'geoTransit', 'r': -0.6}]}},
            {'simulation': {'correlations': [{'a': 'rho', 'b': 'porosity', 'r': 0.95}, {'a': 'porosity', 'b': 'soilLeach', 'r': 0.9},
                                             {'a': 'rho', 'b': 'soilLeach', 'r': -0.9}, {'a': 'cr[Lake]', 'b': 'rho', 'r': 0.5}]}},
        ]
        for project, seed, n, latin, varied in ((projects[0], 1, 60, True, None), (projects[1], 7, 40, True, None),
                                                (projects[1], 7, 40, True, ['Kd[Cs-135]', 'Kd[I-129]', 'geoTransit']),
                                                (projects[2], 3, 300, True, None), (projects[2], 11, 25, False, None)):
            with self.subTest(seed=seed, n=n, varied=varied):
                want = values([['sample', 'design', project, plan, seed, n, latin, varied]])[0]
                names = [slot_name(e) for e in plan]
                held = None if varied is None else set(varied)
                draws = [S.uniforms(n, S.stream_for(seed, group_of(e) or slot_name(e)), latin=latin) for e in plan]
                found = C.correlation_pairs(project, names)
                grouped = {k for k, e in enumerate(plan) if group_of(e)}
                usable = [pr for pr in found['pairs'] if (held is None or (names[pr['a']] in held and names[pr['b']] in held))
                          and pr['a'] not in grouped and pr['b'] not in grouped]
                corr = C.iman_conover(draws, usable, names, seed)
                vals = [[S.value_at_probability(e['spec'], u, i) for i, u in enumerate(draws[k])]
                        for k, e in enumerate(plan)]
                assert_same(self, names, want['names'], 'design', rtol=0)
                assert_same(self, draws, want['draws'], 'design: uniforms', rtol=0)
                assert_same(self, [found['pairs'], found['problems']], [want['pairs'], want['problems']],
                            'design', rtol=0)
                assert_same(self, corr, want['corr'], 'design: correlation')
                assert_same(self, vals, want['values'], 'design: values')


# ---------------------------------------------------------------------------
# correlate.js
# ---------------------------------------------------------------------------


@needs_app
class Correlations(unittest.TestCase):
    NAMES = ['a', 'b', 'c', 'd', 'Kd[A]', 'Kd[B]', 'Kd[C]', 'rho', 'Kd', 'KdX[A]', 'e']

    def test_the_pairs_a_model_asks_for(self):
        projects = [
            {}, {'simulation': None}, {'simulation': {'correlations': None}},
            {'simulation': {'correlations': [{'a': 'a', 'b': 'b', 'r': 0.8}, {'a': 'a', 'b': 'c', 'r': -0.5}]}},
            {'simulation': {'correlations': [
                {'a': 'a', 'b': 'zz', 'r': 0.5}, {'a': 'a', 'b': 'b', 'r': 1.5}, {'a': 'a', 'b': 'a', 'r': 0.2},
                {'group': 'a', 'r': 0.5}, {'a': 'a', 'b': 'b', 'r': 0.3}, {'a': 'b', 'b': 'a', 'r': 0.4}]}},
            {'simulation': {'correlations': [{'group': 'Kd', 'r': 0.9}, {'group': 'rho', 'r': 0.3},
                                             {'group': 'nothing', 'r': 0.3}, {'group': 'Kd', 'r': 0.1}]}},
            {'simulation': {'correlations': [
                None, 5, 'x', [], {}, {'r': None}, {'a': 'a', 'b': 'b'}, {'a': 'a', 'b': 'c', 'r': '0.25'},
                {'a': 'a', 'b': 'd', 'r': ''}, {'a': 'b', 'b': 'c', 'r': 'abc'}, {'a': 'c', 'b': 'd', 'r': True},
                {'a': 'b', 'b': 'd', 'r': [0.5]}, {'a': 'q', 'b': None, 'r': 0.1}, {'a': 0, 'b': '', 'r': 0.1},
                {'a': 'zz', 'b': 'yy', 'r': 0.2}, {'group': '', 'r': 0.2}, {'group': 7, 'r': 0.1},
                {'a': 'e', 'b': 'rho', 'r': -1}, {'a': 'e', 'b': 'Kd', 'r': 1}, {'a': 'Kd', 'b': 'KdX[A]', 'r': 1e-9},
                {'a': 1.5, 'b': 'a', 'r': 0.3}, {'r': 0.5}]}},
        ]
        got = values([['correlate', 'correlationPairs', p, self.NAMES] for p in projects])
        for p, want in zip(projects, got):
            assert_same(self, C.correlation_pairs(p, self.NAMES), want, 'correlation_pairs', rtol=0)
        self.assertEqual(C.correlation_pairs({'simulation': {'correlations': [{'a': 'x', 'b': 'y', 'r': 0.5}]}},
                                             ['x', 'y', 'x'])['pairs'], [{'a': 1, 'b': 2, 'r': 0.5}])

    def test_describing_one(self):
        cs = [{'group': 'Kd', 'r': 0.9}, {'a': 'x', 'b': 'y', 'r': -0.25}, {'a': 'x'}, None, {'group': 3},
              {'group': None, 'a': 1e21, 'b': True, 'r': 'z'}]
        got = values([['correlate', 'describeCorrelation', c] for c in cs])
        assert_same(self, [C.describe_correlation(c) for c in cs], got, 'describe_correlation', rtol=0)

    def test_iman_conover_permutes_as_the_application_does(self):
        names = ['a', 'b', 'c', 'd', 'e']
        matrices = [
            [{'a': 0, 'b': 1, 'r': 0.8}],
            [{'a': 0, 'b': 1, 'r': 0.8}, {'a': 0, 'b': 2, 'r': -0.5}],
            [{'a': 0, 'b': 1, 'r': 0.9}, {'a': 1, 'b': 2, 'r': 0.9}, {'a': 0, 'b': 2, 'r': -0.9}],
            [{'a': 1, 'b': 3, 'r': 0.3}, {'a': 3, 'b': 4, 'r': -0.99}, {'a': 1, 'b': 4, 'r': 0.2},
             {'a': 0, 'b': 4, 'r': 0.6}],
            [{'a': i, 'b': j, 'r': 0.7} for i in range(5) for j in range(i + 1, 5)],
            [{'a': 2, 'b': 4, 'r': 1.0}, {'a': 2, 'b': 3, 'r': -1.0}],
            [{'a': 0, 'b': 1, 'r': 0.0}],
        ]
        cases = [(m, n, seed) for m in matrices for n, seed in ((3, 1), (4, 7), (10, 3), (100, 42), (500, 7))]
        cases += [(matrices[1], 2, 1), ([], 50, 1)]
        calls = []
        columns = []
        for pairs, n, seed in cases:
            cols = [S.uniforms(n, S.stream_for(seed, nm)) for nm in names]
            if n > 20:  # a skewed column too: the values move, not only the ranks
                cols[2] = np.exp(cols[2] * 10)
            columns.append(cols)
            calls.append(['correlate', 'run', [c.tolist() for c in cols], pairs, names, seed])
        got = values(calls)
        for (pairs, n, seed), cols, want in zip(cases, columns, got):
            with self.subTest(pairs=len(pairs), n=n, seed=seed):
                before = [np.sort(c) for c in cols]
                result = C.iman_conover(cols, pairs, names, seed)
                assert_same(self, result, want['result'], 'iman_conover: result')
                assert_same(self, cols, want['columns'], 'iman_conover: columns', rtol=0)
                for c, b in zip(cols, before):  # a permutation: the marginals are what they were
                    self.assertEqual(np.sort(c).tolist(), b.tolist())
        # Lists are reordered in place too.
        cols = [S.uniforms(30, S.stream_for(9, nm)).tolist() for nm in names]
        arrays = [np.array(c) for c in cols]
        C.iman_conover(cols, matrices[1], names, 9)
        C.iman_conover(arrays, matrices[1], names, 9)
        self.assertEqual(cols, [a.tolist() for a in arrays])


# ---------------------------------------------------------------------------
# fit.js
# ---------------------------------------------------------------------------

FAMILIES = [f['id'] for f in F.FIT_FAMILIES]


def fit_samples() -> List[np.ndarray]:
    truths = [spec('unif', min=2, max=5), spec('triang', min=1, max=9, mode=3), spec('dtriang', min=1, max=9, mode=6),
              spec('norm', mean=10, sd=2), spec('logu', min=1e-4, max=1e-1), spec('logt', min=1e-3, max=10, mode=0.1),
              spec('logdt', min=1e-3, max=10, mode=0.5), spec('Logn4', gm=3, gsd=2.5)]
    out = [sample_of(t, 60) for t in truths]
    out += [drawn(t, 40, 5, f'fit{k}') for k, t in enumerate(truths)]
    out += [np.array(v, dtype=float) for v in (
        [1, 2, 4, 8, 16], [1, 1.1, 1.2, 1.3, 1.5, 2, 9], [0, 1, 2, 3, 4, 5], [5, 5, 5, 5, 5], [1, 2, 3, 4],
        [-3, -1, 0, 2, 7, 8], [1, 1, 1, 1, 2, 3, 3, 3, 3], [1e-9, 1e-7, 1e-3, 1, 1e3, 1e6],
        [100, 100.01, 100.02, 100.03, 100.05, 100.08], [2, 3, 3, 3, 4, 10, 30])]
    return out


@needs_app
class Fits(unittest.TestCase):
    samples = fit_samples()

    def test_the_tables_are_the_application_s(self):
        names = ['FIT_METHODS', 'FIT_TESTS', 'FIT_FAMILIES', 'FIT_MIN_SAMPLE']
        for name, want in zip(names, values([['fit', n] for n in names])):
            assert_same(self, getattr(F, name), want, 'fit tables', rtol=0, what=name)

    def test_moments_and_p_values(self):
        calls = [['fit', 'sampleMoments', x] for x in self.samples] + [['fit', 'sampleMoments', np.zeros(0)]]
        ds = [0, 0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 1, math.nan]
        ns = [0, 1, 5, 30, 1000, 10 ** 6]
        calls += [['fit', 'ksPValue', d, n] for d in ds for n in ns]
        a2s = [-1, 0, 0.1, 0.5, 1, 1.999, 2, 2.492, 3.857, 10, 50, math.inf, math.nan]
        calls += [['fit', 'adPValue', a] for a in a2s]
        py: List[Any] = [F.sample_moments(x) for x in self.samples] + [F.sample_moments(np.zeros(0))]
        py += [F.ks_p_value(d, n) for d in ds for n in ns] + [F.ad_p_value(a) for a in a2s]
        # The skewness is over m2 ** 1.5: the platform's pow, V8's in the application.
        assert_same(self, py, values(calls), 'moments and p-values')

    def test_every_family_by_both_methods(self):
        calls = [['fit', 'fitFamily', fid, x, method] for x in self.samples for fid in FAMILIES + ['weibull']
                 for method in ('mle', 'mom')]
        got = values(calls)
        mine = [F.fit_family(c[2], c[3], c[4]) for c in calls]
        out: List[str] = []
        for call, a, b in zip(calls, mine, got):
            # By likelihood a fit is a search; with V8's logarithms it takes the
            # application's steps and ends where it ends. By moments it solves for
            # a skewness that goes through pow, and the answer moves with it.
            area = 'fit_family (mle)' if call[4] == 'mle' else 'fit_family (mom)'
            _compare(a, b, area, 1e-12 if call[4] == 'mle' else 1e-10, 0.0, f'{call[2]} {call[4]} n={len(call[3])}', out)
        if out:
            self.fail(f'{len(out)} differences\n' + '\n'.join(out[:30]))

    def test_scores_ranks_and_texts(self):
        calls = []
        py: List[Any] = []
        for x in self.samples:
            for method in ('mle', 'mom'):
                calls.append(['fit', 'fitAll', x, method])
                py.append(F.fit_all(x, method))
        got = values(calls)
        # A² is -m less a sum of m terms, a small difference of large numbers: a
        # last-bit difference in a CDF value (the normal CDF, or a moment fit's
        # ends) comes out about m / A² times larger in it.
        assert_same(self, py, got, 'fit_all', rtol=1e-10)
        calls = []
        py = []
        for fits in got:
            for test in ('ad', 'ks', 'aic', 'nonsense'):
                calls.append(['fit', 'rankFits', fits, test])
                py.append(F.rank_fits(fits, test))
            for f in fits:
                if 'spec' in f:
                    calls.append(['fit', 'fitText', f['spec']])
                    py.append(F.fit_text(f['spec']))
        assert_same(self, py, values(calls), 'rank_fits and fit_text', rtol=0)
        # A specified distribution scored against a sample, as the summary does.
        calls = []
        py = []
        for x in self.samples[:8]:
            for s in (SHAPES[0], SHAPES[2], SHAPES[8], SHAPES[12], SHAPES[17], LISTS[0], spec('norm', mean=1, sd=None)):
                for k, edges in ((0, False), (3, True)):
                    calls.append(['fit', 'scoreFit', x, s, k, {'edges': edges}])
                    py.append(F.score_fit(x, s, k, edges=edges))
        assert_same(self, py, values(calls), 'score_fit')


# ---------------------------------------------------------------------------
# distribution.js
# ---------------------------------------------------------------------------


@needs_app
class Summaries(unittest.TestCase):
    def test_a_column_of_realisations(self):
        times, iterations = 4, 50
        vals = np.array(S.uniforms(times * iterations, S.stream_for(3, 'col')))
        vals[[5, 17, 42]] = [math.nan, math.inf, -0.0]
        vals[[9, 13]] = 0.0
        vals[21] = -0.0
        mask = np.ones(iterations, dtype=np.uint8)
        mask[::3] = 0
        f32 = vals.astype(np.float32)
        calls = [['distribution', 'sortedColumn', vals, times, iterations, at, None] for at in range(times)]
        calls += [['distribution', 'sortedColumn', vals, times, iterations, at, mask] for at in range(times)]
        calls += [['distribution', 'sortedColumn', f32, times, iterations, 1, None],
                  ['distribution', 'sortedColumn', vals, times, iterations + 3, 2, mask[:10]],
                  ['distribution', 'sortedColumn', vals, times, iterations, 1, np.zeros(0, dtype=np.uint8)]]
        py = [D.sorted_column(vals, times, iterations, at) for at in range(times)]
        py += [D.sorted_column(vals, times, iterations, at, mask) for at in range(times)]
        py += [D.sorted_column(f32, times, iterations, 1), D.sorted_column(vals, times, iterations + 3, 2, mask[:10]),
               D.sorted_column(vals, times, iterations, 1, np.zeros(0, dtype=np.uint8))]
        got = values(calls)
        assert_same(self, py, got, 'sorted_column', rtol=0)
        for mine, want in zip(py, got):  # -0 before +0, as a typed array sorts
            self.assertEqual([math.copysign(1, v) for v in mine.tolist()], [math.copysign(1, v) for v in want])

    def test_lookups_summaries_and_histograms(self):
        cols = [np.sort(S.uniforms(n, S.stream_for(4, f's{n}'))) for n in (1, 2, 3, 10, 2000)]
        cols += [np.sort(np.exp(S.uniforms(400, S.stream_for(4, 'wide')) * 23 - 11.5)),
                 np.array([0.0, 1, 2, 3, 4, 5]), np.array([2.0, 2, 2, 2]), np.array([-5.0, -1, 0, 0, 3, 1e6]),
                 np.array([1e-300, 1e300]), np.zeros(0)]
        ps = [-1, 0, 1e-9, 0.01, 0.05, 0.25, 0.5, 0.5001, 0.95, 0.99, 1, 2, math.nan]
        calls = []
        py: List[Any] = []
        for c in cols:
            probes = c.tolist()[:5] + [-1e9, 0.5, 1e9, math.nan]
            calls += [['distribution', 'valueAt', c, p] for p in ps]
            calls += [['distribution', 'probabilityOf', c, x] for x in probes]
            calls += [['distribution', 'conditionalTailExpectation', c, q] for q in ps]
            calls += [['distribution', 'describeSample', c]]
            py += [D.value_at(c, p) for p in ps] + [D.probability_of(c, x) for x in probes]
            py += [D.conditional_tail_expectation(c, q) for q in ps] + [D.describe_sample(c)]
            for bins in (None, 0, 1, 2, 2.5, 3.5, 7, 42, 200, 1e9, -4, '12', math.nan):
                for scale in ('auto', 'linear', 'log'):
                    calls.append(['distribution', 'histogram', c, bins, scale])
                    py.append(D.histogram(c, bins, scale))
        calls += [['distribution', n] for n in ('PERCENTILES', 'HIST_BINS')]
        py += [D.PERCENTILES, D.HIST_BINS]
        # The skewness is over v ** 1.5: the platform's pow.
        assert_same(self, py, values(calls), 'summaries and histograms')


class WithoutTheApplication(unittest.TestCase):
    """What the ports accept beyond the application's own shapes of input."""

    def test_a_model_object_is_a_project(self):
        import kompartment as kp
        m = kp.Model.new('Correlated')
        m.raw['simulation']['correlations'] = [{'a': 'x', 'b': 'y', 'r': 0.5}, {'group': 'k', 'r': 0.2}]
        names = ['x', 'y', 'k[A]', 'k[B]']
        self.assertEqual(C.correlation_pairs(m, names), C.correlation_pairs(m.raw, names))
        self.assertEqual(len(C.correlation_pairs(m, names)['pairs']), 2)

    def test_a_layout_of_objects(self):
        from types import SimpleNamespace as NS
        s = spec('unif', min=1, max=2)
        layout = NS(lookup_points=[NS(slot=3, name='T', at=10, index=None, spec=s)],
                    parameters=[NS(block={'pdf': s}, name='k', dims=['L'], base=0, width=2)],
                    index_space={'L': ['a', 'b']})
        got = S.distributed_slots(layout, lambda b, k, t: b[k], lambda sp, dims, off: {'L': sp['L'][off]})
        self.assertEqual([(e['slot'], e['name'], e['index']) for e in got],
                         [(3, 'T@10', {}), (0, 'k', {'L': 'a'}), (1, 'k', {'L': 'b'})])

    def test_the_generator_can_be_drawn_in_batches(self):
        g, h = S.rng(99), S.rng(99)
        batch = g.take(1000).tolist() + g.take(3).tolist()
        self.assertEqual(batch, [h() for _ in range(1003)])
        self.assertEqual(g.state, h.state)
        self.assertEqual(S.uniforms(0, g).tolist(), [])


if __name__ == '__main__':
    unittest.main()
