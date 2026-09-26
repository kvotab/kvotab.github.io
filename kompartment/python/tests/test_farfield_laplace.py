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
from typing import Any, Dict, List

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
                pk = max(abs(v) for v in theirs['h'])
                for x, y in zip(r['t'], theirs['t']):
                    self.assertLessEqual(abs(x - y), 1e-12 * abs(y))
                for x, y in zip(r['h'], theirs['h']):
                    self.assertLessEqual(abs(x - y), 1e-10 * pk)


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
