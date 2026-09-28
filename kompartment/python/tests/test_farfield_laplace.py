"""The semi-analytical far-field path, ``engine/farfield_laplace.py``.

* Against the application's own (``src/domain/farfield-laplace.js``, through
  ``tests/node/farfield_laplace.mjs``): transforms, direct inversions,
  tabulated responses and the convolutions of inflows with them, to 1e-10.
  The two are the same algorithms decision for decision; they part only in
  the last digits of the C library's exp and trigonometric functions against
  V8's.
* On its own: the independent 40-digit solution of the page FARF31.html's
  made-up chain with sorption on the fracture surfaces; the closed forms (the
  inverse Gaussian in t/Rf without a matrix, the classical solution under plug
  flow with an unlimited matrix, and what the path holds in both); the Bateman
  solution for nuclides that move alike on a branched network; the mass
  balance; the ways of giving the surface and the refusals.

Every number in here is made up.
"""

from __future__ import annotations

import json
import math
import subprocess
import unittest
from pathlib import Path
from typing import Any, Dict, List, Sequence

from helpers import APP, HERE, NODE, SRC, needs_app

from kompartment.engine import farfield_laplace as FL

LN2 = math.log(2)
REFERENCE = APP.parent / 'resources' / 'tests' / 'farf31' / 'ref' / 'mpmath-ref.json'


def _wire(x: Any) -> Any:
    if isinstance(x, float) and not math.isfinite(x):
        return 'NaN' if x != x else ('Infinity' if x > 0 else '-Infinity')
    if isinstance(x, dict):
        return {k: _wire(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_wire(v) for v in x]
    return x


def _unwire(x: Any) -> Any:
    if x in ('Infinity', '-Infinity', 'NaN'):
        return float(x.replace('Infinity', 'inf'))
    if isinstance(x, dict):
        return {k: _unwire(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_unwire(v) for v in x]
    return x


def app_laplace(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The application's answers to the same questions."""
    assert NODE is not None
    proc = subprocess.run([NODE, str(HERE / 'node' / 'farfield_laplace.mjs'), str(SRC)],
                          input=json.dumps(_wire({'cases': cases})), capture_output=True, text=True, timeout=600,
                          encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return _unwire(json.loads(proc.stdout))['cases']


def log_grid(a: float, b: float, n: int) -> List[float]:
    return [a * (b / a) ** (k / (n - 1)) for k in range(n)]


def worst_rel(got: List[float], want: List[float], frac: float = 1e-6) -> float:
    pk = max(abs(v) for v in want)
    w = 0.0
    for g, v in zip(got, want):
        if abs(v) > frac * pk:
            w = max(w, abs(g - v) / abs(v))
    return w


def rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), 1e-300)


def ig(t: float, tw: float, Pe: float) -> float:
    return math.sqrt(Pe * tw / (4 * math.pi * t ** 3)) * math.exp(-Pe * (tw - t) ** 2 / (4 * tw * t))


def ig_survival(x: float, tw: float, Pe: float) -> float:
    from scipy.special import erfc, erfcx
    r = math.sqrt(Pe * tw / (2 * x))
    a = r * (x / tw - 1)
    b = r * (x / tw + 1)
    return 0.5 * float(erfc(a / math.sqrt(2))) - 0.5 * float(erfcx(b / math.sqrt(2))) * math.exp(Pe - b * b / 2)


def neret(u: float, k: float) -> float:
    return k / (2 * math.sqrt(math.pi) * u ** 1.5) * math.exp(-k * k / (4 * u)) if u > 0 else 0.0


def network(half_lives: List[float], unit: str = 'mol') -> Dict[str, Any]:
    """P decays into A (0.7) and B (0.3), both into D, D into a stable S;
    listed out of order. The ingrowth coefficient carries the parent's decay
    constant for amounts, the daughter's for activities, as the builder's."""
    canon = ['P', 'A', 'B', 'D', 'S']
    lst = ['D', 'P', 'S', 'B', 'A']
    idx = {x: k for k, x in enumerate(lst)}
    lam = [LN2 / half_lives[canon.index(x)] if math.isfinite(half_lives[canon.index(x)]) else 0.0 for x in lst]
    links = [('P', 'A', 0.7), ('P', 'B', 0.3), ('A', 'D', 1.0), ('B', 'D', 1.0), ('D', 'S', 1.0)]
    pairs = [(idx[p], idx[d], b * (lam[idx[p]] if unit == 'mol' else lam[idx[d]])) for p, d, b in links]
    Lam = [[lam[i] if i == j else 0.0 for j in range(5)] for i in range(5)]
    for p, d, c in pairs:
        Lam[d][p] -= c
    return {'list': lst, 'idx': idx, 'lam': lam, 'pairs': pairs, 'Lam': Lam, 'decay': FL.decay_table(lam, pairs)}


CHEMISTRY = {'tw': 80, 'f': 6.4e4, 'rho_m': 2700, 'pe': 10, 'pen_dep': 0.8, 'kd_f': [0, 1e-3, 2e-3, 0, 5e-3],
             'eps_m': 0.004, 'kd_m': [0.05, 0.2, 0.01, 0.1, 0.02], 'de_m': [3e-6, 2e-6, 4e-6, 3e-6, 1e-6]}


def chemistry() -> Dict[str, Any]:
    net = network([3000, 700, 5000, 1e4, math.inf])
    return {'net': net, 'path': FL.prepare_path(CHEMISTRY, net['decay'], names=net['list'])}


@needs_app
class AppParity(unittest.TestCase):
    def test_transforms_and_inversions_are_the_applications(self) -> None:
        net = network([3000, 700, 5000, 1e4, math.inf])
        chain = FL.decay_table([LN2 / 3000, LN2 / 3000.3, LN2 / 5000],
                               [(0, 1, LN2 / 3000), (1, 2, LN2 / 3000.3)])
        cases = [
            {'settings': CHEMISTRY, 'decay': net['decay'], 'names': net['list']},
            {'settings': {'tw': 100, 'surface': 'aw', 'aw': 1000, 'rho_m': 2700, 'pe': math.inf,
                          'pen_dep': math.inf, 'kd_f': [1e-3, 1e-3, 0], 'eps_m': 0.005, 'kd_m': [0.01, 0.01, 0.1],
                          'de_m': 1e-5}, 'decay': chain, 'names': None},
            {'settings': {'tw': 40, 'f': 2e4, 'rho_m': 2700, 'pe': 12, 'pen_dep': 0.3, 'kd_f': [0, 1e-3, 4e-3],
                          'eps_m': 0.005, 'kd_m': 1e-3, 'de_m': [1e-5, 0, 2e-5]}, 'decay': None, 'names': None},
        ]
        for c in cases:
            path = FL.prepare_path(c['settings'], c['decay'])
            c['s'] = [[sr, si, i, j] for sr, si in [(1e-3, 2e-3), (5e-6, 1e-5), (-2e-7, 3e-6), (0.02, -0.05)]
                      for i, j in FL.pairs(path)]
            c['at'] = [[i, j, t, kind] for i, j in FL.pairs(path) for t in (150, 700, 3e3, 2e4, 1e5)
                       for kind in ('release', 'inventory')]
        js = app_laplace(cases)
        for c, a in zip(cases, js):
            path = FL.prepare_path(c['settings'], c['decay'])
            T0 = FL.transfer_at_zero(path)
            for x, y in zip(T0, a['T0']):
                self.assertLessEqual(rel(x, y), 1e-13)
            for (sr, si, i, j), t, k in zip(c['s'], a['transfer'], a['inventoryTransfer']):
                v = FL.transfer(path, sr, si, i, j)
                w = FL.inventory_transfer(path, sr, si, i, j)
                self.assertLessEqual(abs(v - complex(*t)), 1e-12 * max(abs(complex(*t)), 1e-300))
                self.assertLessEqual(abs(w - complex(*k)), 1e-12 * max(abs(complex(*k)), 1e-300))
            for (i, j, t, kind), r in zip(c['at'], a['at']):
                mine = FL.response_at(path, i, j, t, kind=kind)
                scale = abs(r['h'])
                if scale < 1e-280:
                    continue
                self.assertLessEqual(abs(mine['h'] - r['h']), 1e-10 * scale, (i, j, t, kind))
                self.assertLessEqual(abs(mine['dh'] - r['dh']), 1e-10 * (abs(r['dh']) + scale / t), (i, j, t, kind))
                self.assertLessEqual(abs(mine['d2'] - r['d2']), 1e-9 * (abs(r['d2']) + scale / t / t),
                                     (i, j, t, kind))

    def test_tabulated_responses_and_convolutions_are_the_applications(self) -> None:
        lam = [LN2 / 3000, LN2 / 800, LN2 / 5000]
        decay = FL.decay_table(lam, [(0, 1, 0.6 * lam[0]), (0, 2, 0.4 * lam[0])])
        settings = {'tw': 50, 'f': 5e4, 'rho_m': 2700, 'pe': 10, 'pen_dep': 0.1, 'kd_f': [2e-4, 5e-4, 1e-4],
                    'eps_m': 0.005, 'kd_m': [1e-3, 3e-3, 5e-4], 'de_m': [1e-4, 2e-4, 1e-4]}
        inflows = [[[0, 0], [200, 1], [1500, 1], [2000, 0]], None, [[100, 0.2], [5000, 0.2], [5000, 0], [6000, 0]]]
        times = log_grid(20, 1e5, 25)
        case = {'settings': settings, 'decay': decay, 'responses': {'tMax': 2e5}, 'inflows': inflows,
                'times': times}
        js = app_laplace([case])[0]
        path = FL.prepare_path(settings, decay)
        R = FL.unit_responses(path, t_max=2e5)
        for kind in FL.KINDS:
            for r in R[kind]:
                if r is None:
                    continue
                theirs = js['responses'][f"{kind}:{r['i']},{r['j']}"]
                self.assertEqual(len(r['t']), len(theirs['t']), (kind, r['i'], r['j']))
                # the same cells built and failed, and the same samples served
                # by them, left to a parabola of their own or negligible
                self.assertEqual(r['shared'], theirs['shared'], (kind, r['i'], r['j']))
                pk = max(abs(v) for v in theirs['h'])
                for key in ('t', 'h'):
                    for x, y in zip(r[key], theirs[key]):
                        self.assertLessEqual(abs(x - y), 1e-10 * max(abs(y), 1e-6 * pk if key == 'h' else 0),
                                             (kind, key))
                self.assertLessEqual(rel(r['integral'], theirs['integral']), 1e-10)
        series = [FL.inflow_series(p) if p else None for p in inflows]
        for k, t in enumerate(times):
            for mine, theirs in ((FL.release_at(path, R, series, t), js['release'][k]),
                                 (FL.inventory_at(path, R, series, t), js['inventory'][k])):
                pk = max(abs(v) for v in theirs) or 1.0
                for x, y in zip(mine, theirs):
                    self.assertLessEqual(abs(x - y), 1e-10 * max(abs(y), 1e-8 * pk), t)

    def test_one_parabola_per_time_is_the_applications_too(self) -> None:
        # without the shared parabolas (shared: false) the two are still the
        # same, and neither counts any
        settings = {'tw': 40, 'f': 2e4, 'rho_m': 2700, 'pe': 30, 'pen_dep': 0.3, 'kd_f': 1e-3, 'eps_m': 0.005,
                    'kd_m': 2e-3, 'de_m': 2e-5}
        decay = FL.decay_table([LN2 / 2000])
        case = {'settings': settings, 'decay': decay, 'responses': {'tMax': 1e5, 'shared': False}}
        js = app_laplace([case])[0]
        path = FL.prepare_path(settings, decay)
        R = FL.unit_responses(path, t_max=1e5, shared=False)
        for kind in FL.KINDS:
            r = R[kind][0]
            theirs = js['responses'][f'{kind}:0,0']
            self.assertIsNone(r['shared'])
            self.assertIsNone(theirs['shared'])
            self.assertEqual(len(r['t']), len(theirs['t']), kind)
            pk = max(abs(v) for v in theirs['h'])
            for x, y in zip(r['h'], theirs['h']):
                self.assertLessEqual(abs(x - y), 1e-10 * pk, kind)


def page_path(params: Dict[str, Any], nucs: List[Dict[str, Any]]) -> Any:
    """A made-up case in FARF31.html's terms as a path (rho 2700)."""
    lam = [LN2 / n['thalf'] if math.isfinite(n['thalf']) else 0.0 for n in nucs]
    pairs = [(q, q + 1, lam[q]) for q, n in enumerate(nucs) if n.get('daughter')]
    return {'surface': 'aw', 'aw': params['aw'], 'tw': params['tw'], 'rho_m': 2700, 'pe': params['Pe'],
            'pen_dep': params['x0'], 'kd_f': [n.get('ka', 0.0) for n in nucs], 'eps_m': params['eps'],
            'kd_m': [n['kd'] for n in nucs], 'de_m': [n['de'] for n in nucs]}, FL.decay_table(lam, pairs)


#: A front at Pe 5440, just past its peak; plug flow into a matrix that fills
#: at once (a spike after the delay); and a chain whose daughter arrives within
#: a hair of the delay. FARF31.html's hardest cases, made up.
SHARP = page_path({'tw': 260, 'Pe': 5440, 'aw': 4.9, 'eps': 0.002, 'x0': 0.038},
                  [{'thalf': 1.4e7, 'kd': 0, 'de': 7.1e-7, 'ka': 6.6e-5}])
SPIKE = page_path({'tw': 119.84, 'Pe': math.inf, 'aw': 380.5, 'eps': 1.085e-4, 'x0': 0.0817},
                  [{'thalf': 2.727e5, 'kd': 0, 'de': 3.157e-3}])
HAIR = page_path({'tw': 50.27, 'Pe': math.inf, 'aw': 0.3922, 'eps': 1.888e-4, 'x0': math.inf},
                 [{'thalf': 13.05, 'kd': 3.703e-4, 'de': 1.508e-6, 'daughter': True},
                  {'thalf': 8.216e5, 'kd': 0, 'de': 1.508e-6}])


class PageCases(unittest.TestCase):
    def test_a_front_at_pe_5440_against_its_100_digit_values(self) -> None:
        # mpmath's de Hoog at 60 and 100 digits: just past the peak the step
        # has to follow the fastest phase along the contour
        path = FL.prepare_path(*SHARP)
        for t, v in ((265, 0.0490426509324), (265.5254028201174, 0.0440903175807), (266, 0.0396963774933)):
            self.assertLessEqual(abs(FL.response_at(path, 0, 0, t)['h'] / v - 1), 1e-10, t)
        self.assertTrue(FL.unit_response(path, 0, 0)['balanced'])

    def test_plug_flow_a_spike_after_the_delay_and_a_point_mass_at_it(self) -> None:
        spike = FL.unit_response(FL.prepare_path(*SPIKE), 0, 0)
        self.assertLess(abs(spike['tPeak'] - 120.244), 0.005)
        self.assertLessEqual(abs(spike['integral'] / spike['T0'] - 1), 1e-8)
        hair = FL.prepare_path(*HAIR)
        d = FL.unit_response(hair, 1, 0)
        self.assertGreater(d['m0'], 1e-3)
        self.assertLessEqual(abs(d['integral'] - d['expected']) / d['T0'], 1e-8)
        own = FL.unit_response(hair, 1, 1)
        self.assertTrue(own['balanced'] and own['m0'] > 0.2 * own['T0'], own['m0'])
        # a constant inflow of the daughter comes out at its rate times T(0),
        # the point mass included
        R = {'release': [None, None, None, own], 'inventory': [None] * 4}
        at = FL.release_at(hair, R, [None, FL.inflow_series([[0, 1], [2e6, 1]])], 1e6)[1]
        self.assertLessEqual(abs(at / own['T0'] - 1), 1e-6)

    @needs_app
    def test_they_are_the_applications(self) -> None:
        cases = [{'settings': SHARP[0], 'decay': SHARP[1], 'responses': {'kinds': ['release']}},
                 {'settings': SPIKE[0], 'decay': SPIKE[1], 'responses': {'kinds': ['release']}},
                 {'settings': HAIR[0], 'decay': HAIR[1], 'responses': {'kinds': ['release'], 'sources': [0]}}]
        js = app_laplace(cases)
        for c, a, exact in zip(cases, js, (True, True, False)):
            path = FL.prepare_path(c['settings'], c['decay'])
            R = FL.unit_responses(path, kinds=['release'], sources=c['responses'].get('sources'))
            for r in R['release']:
                if r is None:
                    continue
                theirs = a['responses'][f"release:{r['i']},{r['j']}"]
                self.assertEqual(r['balanced'], theirs['balanced'])
                self.assertLessEqual(rel(r['integral'], theirs['integral']), 1e-8)
                self.assertLessEqual(abs(r['m0'] - theirs['m0']), 1e-8 * r['T0'])
                if not exact:
                    # right after a plug-flow delay t - delay keeps nine digits,
                    # and the two part at 1e-8 there: the grids differ
                    continue
                self.assertEqual(len(r['t']), len(theirs['t']))
                self.assertEqual(r['shared'], theirs['shared'])
                pk = max(abs(v) for v in theirs['h'])
                for x, y in zip(r['t'], theirs['t']):
                    self.assertLessEqual(abs(x - y), 1e-12 * abs(y))
                for x, y in zip(r['h'], theirs['h']):
                    self.assertLessEqual(abs(x - y), 1e-10 * pk)


def chain_path(settings: Dict[str, Any], half: List[float]) -> Any:
    """An unbranched chain, one half-life each (inf: stable)."""
    lam = [LN2 / h if math.isfinite(h) else 0.0 for h in half]
    return FL.prepare_path(settings, FL.decay_table(lam, [(k, k + 1, lam[k]) for k in range(len(lam) - 1)]))


#: A chain like the far-field example's; plug flow into a thin matrix, a
#: parent into a stable daughter (so that K is inverted whole within the run);
#: a sharp front; a long slow tail.
LIKE_EXAMPLE = ({'tw': 50, 'f': 1e5, 'rho_m': 2700, 'pe': 10, 'pen_dep': 12.5, 'kd_f': 0, 'eps_m': 0.0018,
                 'kd_m': [0.0017, 0.0017, 0.05], 'de_m': 3.15e-5}, [4.468e9, 2.455e5, 7.54e4])
PLUG_THIN = ({'tw': 100, 'f': 2e4, 'rho_m': 2700, 'pe': math.inf, 'pen_dep': 0.05, 'kd_f': 1e-4, 'eps_m': 0.005,
              'kd_m': [1e-3, 0.01], 'de_m': 1e-5}, [2.4e5, math.inf])
FRONT_3000 = ({'tw': 20, 'f': 3e3, 'rho_m': 2700, 'pe': 3000, 'pen_dep': 1, 'kd_f': 0, 'eps_m': 0.003,
               'kd_m': [5e-4, 2e-3], 'de_m': 2e-5}, [1e5, 3e4])
TAIL_300 = ({'tw': 50, 'f': 1e3, 'rho_m': 2700, 'pe': 300, 'pen_dep': math.inf, 'kd_f': 0, 'eps_m': 0.002,
             'kd_m': [0], 'de_m': 1e-5}, [math.inf])


def axes_of(path: Any, i: int, j: int, kind: str) -> List[Any]:
    """The axes a response is sampled on: a release's, or an inventory's two
    (A^-1 T for the split, K for the whole)."""
    if kind == 'release':
        return [('release', FL._axis_of(path, FL._pair_of(path, i, j, 'release')))]
    ax_c, ax_k = FL._inventory_axes(path, i, j)
    return [('split', ax_c), ('whole', ax_k)]


def cell_options(ax: Dict[str, Any]) -> Any:
    """The axis's support, and the peak and floor the application holds its
    cells to (a release's peak estimate, an inventory's one unit)."""
    sup = FL._response_support(ax, ax['tLo'], 1e12)
    peak = math.exp(sup['logPeak']) if ax['pr']['kind'] == FL.RELEASE else 1.0
    return sup, {'atol': 1e-3 * FL.RESP_ATOL * peak, 'peak': peak}


def takes_whole(path: Any, ax: Dict[str, Any], t: float) -> bool:
    """Whether the application samples an inventory's K inverted whole at t:
    only once less than half of what the path would hold is left in it."""
    k = FL._invert_parabola(path, path.ws, ax, t)['h']
    return abs(k) < 0.5 * abs(FL._bateman(path, path.ws, ax['pr']['blk'], t)[0])


def from_whole(path: Any, ax: Dict[str, Any], ts: List[float]) -> List[float]:
    """The times from the first at which K is taken whole, which it goes on
    being (by bisection: before it, one parabola runs to its budget)."""
    lo = -1
    hi = len(ts) - 1
    while hi - lo > 1:
        c = (lo + hi) >> 1
        if takes_whole(path, ax, ts[c]):
            hi = c
        else:
            lo = c
    return ts[hi:]


def support_times(ax: Dict[str, Any], sup: Dict[str, float], per: float, least: int) -> List[float]:
    d = ax['pr']['shift']
    u0 = sup['tLo'] - d
    u1 = min(sup['tHi'], 1e12) - d
    n = max(least, math.ceil(per * math.log10(u1 / u0)) + 1)
    return [d + u0 * (u1 / u0) ** (k / (n - 1)) for k in range(n)]


class SharedContours(unittest.TestCase):
    """Nearby times summed from the nodes of one parabola: the application's
    ``makeCells``, whose decisions the parity tests above hold this to."""

    def test_the_cells_agree_with_one_parabola_per_time(self) -> None:
        # h, h' and h'' from the cells against one parabola per time, 8 a
        # decade (40 at least) over each axis's support where the application
        # samples it (K whole only once less than half of what the path would
        # hold is left in it), each over its largest value there; every time
        # left to a parabola of its own is below 1e-10 of the peak (sized by
        # the saddle-point estimate: one parabola may fail there too)
        cases = [(LIKE_EXAMPLE, [(2, 0, 'release'), (1, 0, 'inventory')]),
                 (PLUG_THIN, [(1, 0, 'release'), (1, 0, 'inventory')]),
                 (FRONT_3000, [(1, 0, 'release')]),
                 (TAIL_300, [(0, 0, 'release'), (0, 0, 'inventory')])]
        for spec, pairs_ in cases:
            path = chain_path(*spec)
            for i, j, kind in pairs_:
                for which, ax in axes_of(path, i, j, kind):
                    sup, opt = cell_options(ax)
                    cells = FL._make_cells(path, ax, opt)
                    own: List[Dict[str, Any]] = []
                    shared: List[Dict[str, Any]] = []
                    left: List[float] = []
                    ts = support_times(ax, sup, 8, 40)
                    for t in from_whole(path, ax, ts) if which == 'whole' else ts:
                        p = FL._invert_parabola(path, path.ws, ax, t, {'atol': opt['atol']})
                        if which == 'whole' and not abs(p['h']) < 0.5 * abs(
                                FL._bateman(path, path.ws, ax['pr']['blk'], t)[0]):
                            continue
                        s = FL._invert_shared(path, path.ws, cells, t)
                        if s is None:
                            left.append(math.exp(FL._log_estimate(ax, t)))
                            continue
                        if not math.isfinite(p['h']) or p['err'] > 1e-6 * abs(p['h']) + opt['atol']:
                            continue
                        own.append(p)
                        shared.append(s)
                    what = (spec[1], i, j, which)
                    self.assertGreater(len(own), 10, what)
                    for key in ('h', 'dh', 'd2'):
                        top = max(abs(p[key]) for p in own)
                        worst = max(abs(s[key] - p[key]) for s, p in zip(shared, own))
                        self.assertLessEqual(worst, 1e-10 * top, (what, key))
                    top = max(abs(p['h']) for p in own)
                    self.assertEqual([v for v in left if not v <= 1e-10 * top], [], what)

    def test_a_time_does_not_depend_on_what_was_asked_before_it(self) -> None:
        # each cell comes from the axis's table and its index alone
        path = chain_path(*LIKE_EXAMPLE)
        ax = axes_of(path, 2, 0, 'release')[0][1]
        sup, opt = cell_options(ax)
        ts = support_times(ax, sup, 0, 60)

        def in_order(order: Sequence[int]) -> List[Any]:
            cells = FL._make_cells(path, ax, opt)
            out: List[Any] = [None] * len(ts)
            for k in order:
                out[k] = FL._invert_shared(path, path.ws, cells, ts[k])
            return out

        def same(p: Any, q: Any) -> bool:
            if p is None or q is None:
                return p is None and q is None
            return all(p[key] == q[key] for key in ('h', 'dh', 'd2', 'err'))

        fwd = in_order(range(len(ts)))
        back = in_order(range(len(ts) - 1, -1, -1))
        mixed = in_order([(7 * k) % len(ts) for k in range(len(ts))])
        self.assertTrue(all(r is not None for r in fwd))
        for k in range(len(ts)):
            self.assertTrue(same(fwd[k], back[k]) and same(fwd[k], mixed[k]), k)
        for k in (0, 29, 59):
            self.assertTrue(same(FL._invert_shared(path, path.ws, FL._make_cells(path, ax, opt), ts[k]), fwd[k]), k)
        # and every cell spans at most a factor 2 either side of its middle time
        cells = FL._make_cells(path, ax, opt)
        for t in ts:
            FL._invert_shared(path, path.ws, cells, t)
        for cell in cells['map'].values():
            self.assertLessEqual(cell['tHi'], 2 * cell['tA'] * (1 + 1e-12))
            self.assertLessEqual(cell['tA'], 2 * cell['tLo'] * (1 + 1e-12))


def ln_t(path: Any, i: int, j: int, s: float) -> float:
    """ln T_ij at a real s, held scaled (under plug flow without the delay)."""
    v = FL._eval_block(path, path.ws, FL._block_of(path, i, j), complex(s, 0.0), FL.RELEASE)
    return math.log(v.real) - path.ws.E


def tube(Pe: float) -> Any:
    """One nuclide in a tube 100 a long with a 1 m matrix that takes up little
    (a_w 0.2 1/m): a sharp front at Pe 1e5 or 1e6."""
    return FL.prepare_path({'tw': 100, 'f': 20, 'rho_m': 2700, 'pe': Pe, 'pen_dep': 1, 'kd_f': 0, 'eps_m': 0.005,
                            'kd_m': 0, 'de_m': 1e-5}, FL.decay_table([LN2 / 1e6]))


#: h at Pe 1e5 at 14 times across the front: the subordination integral at 40
#: digits (mpmath, quadrature in ln tau with break points; the same at 60).
TUBE_REF = [(97.0, 7.7425173134802672717e-11), (97.5, 1.0003730354311338361e-7), (97.9, 1.1670634165061735854e-5),
            (98.3, 5.8050957020603802405e-4), (99.0, 0.071743739914590541379), (99.5, 0.47594316089825745417),
            (99.9, 0.8671308692850578021), (100.0, 0.88853639316213341001), (100.02, 0.88754487363082356384),
            (100.052, 0.88229307770110894935), (100.1, 0.86615182604107402573), (100.3, 0.70913263206761010465),
            (101.0, 0.075737186734056615885), (103.0, 2.5422010804685433653e-4)]
TUBE_PEAK = 0.88853639316213341001


def table_at(r: Dict[str, Any], t: float) -> float:
    """A tabulated response between its samples (quintic Hermite)."""
    T = r['t']
    k = 0
    while k + 2 < len(T) and T[k + 1] <= t:
        k += 1
    return FL._hermite5(T[k], r['h'][k], r['dh'][k], r['d2h'][k], T[k + 1], r['h'][k + 1], r['dh'][k + 1],
                        r['d2h'][k + 1], t)


class PlugFlow(unittest.TestCase):
    """Under plug flow the transform lacks the pair's delay, and the step
    follows the members' own phase rates as elsewhere."""

    def test_ln_t_at_large_s_is_its_closed_form(self) -> None:
        # formed as g - Rmin s the transform kept the rounding of Rmin s where
        # the saddles lie right after the delay; over |ln T|, s from 1 to 1e8
        S = (1, 1e2, 1e4, 1e5, 1e6, 1e7, 1e8)
        for p, n in (({'tw': 50.27, 'aw': 0.3922, 'eps': 1.888e-4, 'x0': math.inf}, {'th': 13.05, 'kd': 3.703e-4, 'de': 1.508e-6, 'ka': 0.0}),
                     ({'tw': 100, 'aw': 1500, 'eps': 0.005, 'x0': math.inf}, {'th': 7.6e4, 'kd': 0.01, 'de': 5e-6, 'ka': 0.002}),
                     ({'tw': 119.84, 'aw': 380.5, 'eps': 1.085e-4, 'x0': 0.0817}, {'th': 2.727e5, 'kd': 0.0, 'de': 3.157e-3, 'ka': 0.0})):
            path = FL.prepare_path({'surface': 'aw', 'aw': p['aw'], 'tw': p['tw'], 'rho_m': 2700, 'pe': math.inf,
                                    'pen_dep': p['x0'], 'kd_f': n['ka'], 'eps_m': p['eps'], 'kd_m': n['kd'],
                                    'de_m': n['de']}, FL.decay_table([LN2 / n['th']]))
            R = p['eps'] + n['kd'] * 2700
            lam = LN2 / n['th']
            Rf = 1 + n['ka'] * p['aw']
            for s in S:
                u = math.sqrt(R * (s + lam) / n['de'])
                tau = u * math.tanh(p['x0'] * u) if math.isfinite(p['x0']) else u
                want = -p['tw'] * Rf * lam - p['tw'] * p['aw'] * n['de'] * tau
                self.assertLessEqual(abs(ln_t(path, 0, 0, s) - want), 1e-14 * max(1.0, abs(want)), (p, s))
        # a daughter held back more than its parent: one delay, TW Rmin s,
        # taken out of both; T_21 = G_21 (H(g_2) - H(g_1))/(g_2 - g_1) with an
        # unlimited matrix, its closed form
        tw, aw = 100.0, 1000.0
        kdf, kdm, De = [1e-4, 5e-4], [1e-3, 0.01], [1e-5, 2e-5]
        lam = [LN2 / 2.4e5, LN2 / 3e3]
        path = FL.prepare_path({'surface': 'aw', 'aw': aw, 'tw': tw, 'rho_m': 2700, 'pe': math.inf, 'pen_dep': math.inf,
                                'kd_f': kdf, 'eps_m': 0.005, 'kd_m': kdm, 'de_m': De},
                               FL.decay_table(lam, [(0, 1, lam[0])]))
        Rf = [1 + k * aw for k in kdf]
        Rm = [0.005 + k * 2700 for k in kdm]
        Rmin = min(Rf)
        for s in S:
            tau = [math.sqrt(Rm[p] * (s + lam[p]) / De[p]) for p in (0, 1)]
            g = [Rf[p] * lam[p] + (Rf[p] - Rmin) * s + aw * De[p] * tau[p] for p in (0, 1)]
            G21 = -lam[0] * (Rf[0] + aw * Rm[0] / (tau[0] + tau[1]))
            d = abs(g[1] - g[0])
            want = math.log(-G21) - tw * min(g) + math.log(-math.expm1(-tw * d) / d)
            self.assertLessEqual(abs(ln_t(path, 1, 0, s) - want), 1e-13 * max(1.0, abs(want)), s)

    def test_a_spike_right_after_the_delay_is_the_classical_solution(self) -> None:
        # a nuclide an unlimited matrix barely holds: the response lies within
        # 1e-4 a of the delay; at t less the delay as the path forms it
        tw, aw, De = 50.27, 0.3922, 1.508e-6
        R = 1.888e-4 + 3.703e-4 * 2700
        lam = LN2 / 13.05
        path = FL.prepare_path({'surface': 'aw', 'aw': aw, 'tw': tw, 'rho_m': 2700, 'pe': math.inf, 'pen_dep': math.inf,
                                'kd_f': 0, 'eps_m': 1.888e-4, 'kd_m': 3.703e-4, 'de_m': De}, FL.decay_table([lam]))
        k = tw * aw * math.sqrt(De * R)
        up = k * k / 6
        ts = [tw + u for u in log_grid(up / 20, up * 1e4, 31)]
        want = [math.exp(-lam * t) * neret(t - tw, k) for t in ts]
        got = [FL.response_at(path, 0, 0, t)['h'] for t in ts]
        self.assertLessEqual(worst_rel(got, want, 1e-6), 1e-12)
        r = FL.unit_response(path, 0, 0)
        w = max(abs(h - math.exp(-lam * t) * neret(t - tw, k)) for t, h in zip(r['t'], r['h']))
        self.assertLessEqual(w, 1e-12 * r['peak'])

    def test_a_chain_with_a_thin_matrix_is_right_or_says_it_has_not_converged(self) -> None:
        # members that turn thousands of times faster than the answer along the
        # path: two sums once agreed on values 1e-4 off; against de Hoog at 120
        # and 240 terms
        lam = [LN2 / 6234.3, LN2 / 9884.0, LN2 / 2.7713e8, LN2 / 355.60]
        path = FL.prepare_path({'surface': 'aw', 'aw': 4.401, 'tw': 2741.36, 'rho_m': 2700, 'pe': math.inf,
                                'pen_dep': 0.001016, 'kd_f': 0.00096121, 'eps_m': 0.0138,
                                'kd_m': [0.0078128, 0.031940, 0.35151, 0.0], 'de_m': [1.1566e-7, 2.1815e-5, 1.4778e-4, 1.1650e-5]},
                               FL.decay_table(lam, [(0, 1, lam[0]), (1, 2, lam[1]), (2, 3, lam[2])]))
        for i, j, tts in ((1, 0, (72.5, 72.695, 72.9)), (2, 1, (1085, 1089.4, 1095))):
            pr = FL._pair_of(path, i, j, 'release')
            ax = FL._axis_of(path, pr)
            _, opt = cell_options(ax)
            cells = FL._make_cells(path, ax, opt)
            for tt in tts:
                t = pr['shift'] + tt
                a = FL._invert_de_hoog(path, path.ws, pr, t, {'M': 120})
                b = FL._invert_de_hoog(path, path.ws, pr, t, {'M': 240})
                tol = 1e-9 * abs(b) + 1e2 * abs(a - b)
                own = FL._invert_parabola(path, path.ws, ax, t)
                if math.isfinite(own['h']) and not own['err'] > 1e-6 * abs(own['h']):
                    self.assertLessEqual(abs(own['h'] - b), tol, (i, j, tt))
                s = FL._invert_shared(path, path.ws, cells, t)
                self.assertIsNotNone(s, (i, j, tt))
                self.assertLessEqual(abs(s['h'] - b), tol, (i, j, tt))
                self.assertLessEqual(abs(FL.response_at(path, i, j, t)['h'] - b), tol, (i, j, tt))


class SharpFront(unittest.TestCase):
    """A weak singularity next to a sharp front: the first pole of tanh in the
    matrix term within 0.01 of the saddles just after the front, handled by
    nodes spaced as c sinh(u); and the rising edge the real-axis table now
    reaches."""

    def test_pe_1e5_against_its_40_digit_values(self) -> None:
        path = tube(1e5)
        for t, want in TUBE_REF:
            r = FL.response_at(path, 0, 0, t)
            self.assertLessEqual(abs(r['h'] - want), 1e-12 * TUBE_PEAK, t)
        r = FL.unit_response(path, 0, 0, t_max=1e6)
        self.assertEqual(r['shared']['dehoog'], 0, r['shared'])
        for t, want in TUBE_REF:
            self.assertLessEqual(abs(table_at(r, t) - want), 1e-9 * TUBE_PEAK, t)
        # the table reaches back to before the rising edge (it once began, in
        # effect, at 97.9 a, 1e-5 of the peak)
        self.assertLess(r['t'][0], 97)
        self.assertLess(r['h'][0], 1e-12 * TUBE_PEAK)
        self.assertTrue(r['balanced'])
        self.assertLessEqual(abs(r['integral'] - r['expected']) / r['T0'], 1e-9)

    def test_pe_1e6_holds_its_mass_balance(self) -> None:
        r = FL.unit_response(tube(1e6), 0, 0, t_max=1e6)
        self.assertTrue(r['balanced'], r['rel'])
        self.assertLessEqual(abs(r['integral'] - r['expected']) / r['T0'], 1e-9)

    def test_response_at_never_returns_a_failed_parabola(self) -> None:
        # far out in a long tail the parabola does not converge: response_at
        # answers with de Hoog's method at twice its terms
        tail = chain_path(*TAIL_300)
        ax = FL._axis_of(tail, FL._pair_of(tail, 0, 0, 'release'))
        replaced = 0
        for t in log_grid(1e10, 1e11, 5):
            own = FL._invert_parabola(tail, tail.ws, ax, t)
            r = FL.response_at(tail, 0, 0, t)
            self.assertTrue(math.isfinite(r['h']) and math.isfinite(r['err']), t)
            if not (math.isfinite(own['h']) and not own['err'] > 1e-6 * abs(own['h'])):
                replaced += 1
                M = min(2 * FL._de_hoog_terms(tail, ax, t), 320)
                self.assertEqual(r['h'], FL._invert_de_hoog(tail, tail.ws, ax['pr'], t, {'M': M}), t)
        self.assertGreater(replaced, 0)
        path = tube(1e5)
        for t in log_grid(96, 1e4, 20):
            r = FL.response_at(path, 0, 0, t)
            self.assertTrue(math.isfinite(r['h']) and not r['err'] > 1e-6 * abs(r['h']), (t, r))

    @needs_app
    def test_the_sharp_front_is_the_applications(self) -> None:
        # responses tabulated, and inverted directly at the 14 times, as the
        # application's: the same grid, the same decisions, to 1e-10
        settings = {'tw': 100, 'f': 20, 'rho_m': 2700, 'pe': 1e5, 'pen_dep': 1, 'kd_f': 0, 'eps_m': 0.005, 'kd_m': 0,
                    'de_m': 1e-5}
        decay = FL.decay_table([LN2 / 1e6])
        case = {'settings': settings, 'decay': decay, 'responses': {'kinds': ['release'], 'tMax': 1e6},
                'at': [[0, 0, t, 'release'] for t, _ in TUBE_REF]}
        js = app_laplace([case])[0]
        path = FL.prepare_path(settings, decay)
        for (t, _), a in zip(TUBE_REF, js['at']):
            self.assertLessEqual(abs(FL.response_at(path, 0, 0, t)['h'] - a['h']), 1e-10 * TUBE_PEAK, t)
        r = FL.unit_response(path, 0, 0, t_max=1e6)
        theirs = js['responses']['release:0,0']
        self.assertEqual(r['shared'], theirs['shared'])
        self.assertEqual(len(r['t']), len(theirs['t']))
        for x, y in zip(r['h'], theirs['h']):
            self.assertLessEqual(abs(x - y), 1e-10 * TUBE_PEAK)


@unittest.skipUnless(REFERENCE.is_file(), 'needs FARF31.html\'s 40-digit references')
class Reference(unittest.TestCase):
    def test_the_page_chain_with_fracture_sorption_to_its_40_digit_solution(self) -> None:
        c = json.loads(REFERENCE.read_text('utf-8'))['cases']['fsorb']
        p = c['input']['params']
        nucs = c['input']['nuclides']
        lam = [LN2 / n['thalf'] for n in nucs]
        pairs = [(q, q + 1, lam[q]) for q, n in enumerate(nucs) if n['daughter']]
        path = FL.prepare_path({'surface': 'aw', 'aw': p['aw'], 'tw': p['tw'], 'rho_m': 2700, 'pe': p['Pe'],
                                'pen_dep': p['x0'], 'kd_f': [n['ka'] for n in nucs], 'eps_m': p['eps'],
                                'kd_m': [n['kd'] for n in nucs], 'de_m': [n['de'] for n in nucs]},
                               FL.decay_table(lam, pairs))
        T0 = FL.transfer_at_zero(path)
        for key, v in c['T0'].items():
            i, j = map(int, key.split(','))
            self.assertLessEqual(abs(T0[i * path.n + j] / v - 1), 1e-12, key)
        for r in c['responses']:
            pk = max(v for _, v in r['values'])
            for t, v in r['values'][::3]:
                if v > 1e-6 * pk:
                    self.assertLessEqual(abs(FL.response_at(path, r['i'], r['j'], t)['h'] / v - 1), 1e-11,
                                         (r['i'], r['j'], t))


class ClosedForms(unittest.TestCase):
    def test_without_a_matrix_the_inverse_gaussian_in_t_over_rf(self) -> None:
        for Pe, kdf in ((2, 2e-4), (10, 1e-3), (300, 2e-2)):
            tw = 100.0
            lam = LN2 / 1e4
            Rf = 1 + kdf * 500
            path = FL.prepare_path({'tw': tw, 'f': 5e4, 'rho_m': 2700, 'pe': Pe, 'pen_dep': 1, 'kd_f': kdf,
                                    'eps_m': 0.005, 'kd_m': 0, 'de_m': 0}, FL.decay_table([lam]))
            ts = log_grid(tw * Rf / 20, tw * Rf * 20, 31)
            want = [math.exp(-lam * t) * ig(t / Rf, tw, Pe) / Rf for t in ts]
            got = [FL.response_at(path, 0, 0, t)['h'] for t in ts]
            self.assertLessEqual(worst_rel(got, want, 1e-10), 1e-9, Pe)
            held = [math.exp(-lam * t) * ig_survival(t / Rf, tw, Pe) for t in ts]
            got = [FL.response_at(path, 0, 0, t, kind='inventory')['h'] for t in ts]
            self.assertLessEqual(worst_rel(got, held, 1e-10), 1e-9, Pe)

    def test_plug_flow_and_an_unlimited_matrix_the_classical_solution(self) -> None:
        from scipy.special import erfc
        for kd, de, aw, th, kdf in ((0.01, 5e-6, 1500, 7.6e4, 1e-3), (2, 4e-6, 800, 432.6, 0.1)):
            tw = 100.0
            Rm = 0.005 + kd * 2700
            k = tw * aw * math.sqrt(de * Rm)
            lam = LN2 / th
            Rf = 1 + kdf * aw
            path = FL.prepare_path({'tw': tw, 'surface': 'aw', 'aw': aw, 'rho_m': 2700, 'pe': math.inf,
                                    'pen_dep': math.inf, 'kd_f': kdf, 'eps_m': 0.005, 'kd_m': kd, 'de_m': de},
                                   FL.decay_table([lam]))
            up = k * k / 6
            ts = [Rf * tw + u for u in log_grid(up * 1e-3, up * 1e4, 36)]
            want = [math.exp(-lam * t) * neret(t - Rf * tw, k) for t in ts]
            got = [FL.response_at(path, 0, 0, t)['h'] for t in ts]
            self.assertLessEqual(worst_rel(got, want, 1e-6), 1e-9)
            self.assertEqual(FL.response_at(path, 0, 0, 0.999 * Rf * tw)['h'], 0.0)
            held = [math.exp(-lam * t) * (1 - float(erfc(k / (2 * math.sqrt(t - Rf * tw))))) for t in ts]
            got = [FL.response_at(path, 0, 0, t, kind='inventory')['h'] for t in ts]
            self.assertLessEqual(worst_rel(got, held, 1e-10), 1e-9)


class Bateman(unittest.TestCase):
    def test_a_network_that_moves_alike_is_e_to_minus_lambda_t_times_one_response(self) -> None:
        from scipy.linalg import expm
        import numpy as np
        for th, unit in (([3000, 700, 5000, 1e4, math.inf], 'mol'), ([1e4, 1e4, 1e4, 1e4, math.inf], 'Bq')):
            net = network(th, unit)
            settings = {'tw': 100, 'f': 1e5, 'rho_m': 2700, 'pe': 10, 'pen_dep': 0.5, 'kd_f': 1e-3, 'eps_m': 0.005,
                        'kd_m': 0.01, 'de_m': 1e-5}
            path = FL.prepare_path(settings, net['decay'])
            one = FL.prepare_path(settings, None)
            ts = log_grid(30, 1e6, 8)
            h0 = [FL.response_at(one, 0, 0, t)['h'] for t in ts]
            k0 = [FL.response_at(one, 0, 0, t, kind='inventory')['h'] for t in ts]
            E = [expm(-np.array(net['Lam']) * t) for t in ts]
            for i, j in FL.pairs(path):
                want = [E[q][i][j] * h0[q] for q in range(len(ts))]
                got = [FL.response_at(path, i, j, t)['h'] for t in ts]
                self.assertLessEqual(worst_rel(got, want, 1e-8), 1e-9, (unit, i, j))
                want = [E[q][i][j] * k0[q] for q in range(len(ts))]
                got = [FL.response_at(path, i, j, t, kind='inventory')['h'] for t in ts]
                self.assertLessEqual(worst_rel(got, want, 1e-8), 1e-9, (unit, i, j, 'inventory'))


class MassBalance(unittest.TestCase):
    def test_every_column_of_t0_sums_to_one(self) -> None:
        path = chemistry()['path']
        T0 = FL.transfer_at_zero(path)
        for j in range(path.n):
            self.assertLessEqual(abs(sum(T0[i * path.n + j] for i in range(path.n)) - 1), 1e-14)

    def test_what_is_held_changes_by_what_arrives_leaves_and_decays(self) -> None:
        c = chemistry()
        net = c['net']
        path = c['path']
        for i, j in [(net['idx']['D'], net['idx']['P']), (net['idx']['A'], net['idx']['P']), (1, 1)]:
            for t in (300, 3e3, 3e4):
                k = FL.response_at(path, i, j, t, kind='inventory')
                lk = net['lam'][i] * k['h']
                for p, d, co in net['pairs']:
                    if d == i and path.reach[j][p]:
                        lk -= co * FL.response_at(path, p, j, t, kind='inventory')['h']
                h = FL.response_at(path, i, j, t)['h']
                scale = max(abs(k['dh']), abs(h), net['lam'][i] * abs(k['h']), 1e-12)
                self.assertLessEqual(abs(k['dh'] + lk + h) / scale, 1e-9, (i, j, t))

    def test_a_tabulated_release_integrates_to_t0(self) -> None:
        path = chemistry()['path']
        r = FL.unit_response(path, 3, 1)
        self.assertLessEqual(abs(r['integral'] / r['T0'] - 1), 1e-9)


class Settings(unittest.TestCase):
    BASE = {'tw': 60, 'rho_m': 2700, 'pe': 10, 'pen_dep': 0.5, 'kd_f': 1e-3, 'eps_m': 0.005, 'kd_m': 0.01,
            'de_m': 1e-5}

    def test_f_a_w_and_the_aperture_give_the_same_path(self) -> None:
        a = FL.prepare_path({**self.BASE, 'f': 6e4})
        b = FL.prepare_path({**self.BASE, 'surface': 'aw', 'aw': 1000})
        c = FL.prepare_path({**self.BASE, 'surface': 'aperture', 'aperture': 0.002})
        for t in (100, 1e3, 1e4):
            h = FL.response_at(a, 0, 0, t)['h']
            self.assertLessEqual(abs(FL.response_at(b, 0, 0, t)['h'] / h - 1), 1e-14)
            self.assertLessEqual(abs(FL.response_at(c, 0, 0, t)['h'] / h - 1), 1e-14)

    def test_species_that_do_not_decay_travel_alone(self) -> None:
        path = FL.prepare_path({**self.BASE, 'f': 3e4, 'kd_f': [0, 1e-3, 4e-3], 'de_m': 0})
        self.assertEqual(path.n, 3)
        self.assertEqual(FL.pairs(path), [(0, 0), (1, 1), (2, 2)])
        for v, want in zip(FL.transfer_at_zero(path), [1, 0, 0, 0, 1, 0, 0, 0, 1]):
            self.assertLessEqual(abs(v - want), 1e-15)

    def test_what_cannot_be_solved_is_refused(self) -> None:
        ok = {'tw': 10, 'f': 1e4, 'rho_m': 2700, 'pe': 10, 'pen_dep': 1, 'kd_f': 0, 'eps_m': 0.005, 'kd_m': 0,
              'de_m': 1e-5}
        for settings, decay, needle in (
                ({**ok, 'pe': math.inf, 'f': 0}, None, 'needs matrix diffusion'),
                ({**ok, 'de_m': [1e-5, 0]}, FL.decay_table([1e-3, 1e-4], [(0, 1, 1e-3)]), 'does not diffuse'),
                (ok, FL.decay_table([1e-3, 1e-4], [(0, 1, 1e-3), (1, 0, 1e-4)]), 'closes on itself'),
                ({**ok, 'eps_m': 0}, None, 'capacity'),
                ({**ok, 'surface': 'volume'}, None, 'wetted surface'),
                (ok, FL.decay_table([1e-3] * 19, [(k, k + 1, 1e-3) for k in range(18)]), 'at most 16')):
            with self.assertRaises(FL.LaplacePathError) as e:
                FL.prepare_path(settings, decay)
            self.assertIn(needle, str(e.exception))


if __name__ == '__main__':
    unittest.main()
