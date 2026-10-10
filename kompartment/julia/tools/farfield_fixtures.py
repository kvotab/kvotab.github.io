"""Reference numbers for the Julia port of the far-field pathway, from the Python engine.

Writes, under OUT_DIR:

* ``models/``  -- the bundled far-field example and variants of it made from
  the Python tests (test_engine_compiled_farfield.py, test_farfield_semi.py):
  matched and reference layers, every outflow condition, settings following
  the clock (expressions and lookup tables) and the state, rates per nuclide,
  other index lists, no decay, every cell reported, a path with no nuclide
  list, the semi-analytical method (decay chains, jumps, switches, plug flow,
  an unlimited matrix) and what it refuses. Paths on cells are shortened to
  6 x 6 cells and solved with the dense matrix -- the application's own LU on
  both engines -- so that whole runs compare to the last bit;
* ``engine/`` and ``runs/`` -- tools/engine_fixtures.py and tools/run_fixtures.py
  for every model;
* ``jac/``     -- the analytic Jacobian (pattern, colouring, values) at the
  engine fixture's probe states;
* ``resp/``    -- every unit response a semi-analytical path tabulates, with
  the evaluation counter after each (the same control flow, not just the
  same numbers), and those of the hard cases of test_farfield_laplace.py
  (``laplace_cases.json``).

    python3 tools/farfield_fixtures.py OUT_DIR

Run it with the repository's Python package on the path
(``PYTHONPATH=kompartment/python``); test/engine/farfield.jl reads OUT_DIR
from ``KOMPARTMENT_FARFIELD_FIXTURES``.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent.parent / 'examples'
sys.path.insert(0, str(HERE))

import engine_fixtures  # noqa: E402
import run_fixtures  # noqa: E402


def hexes(v):
    return [float(x).hex() for x in np.asarray(v, dtype=float).ravel()]


# --- the models -------------------------------------------------------------------------------

def models() -> dict:
    base = json.loads((EXAMPLES / 'farfield.json').read_text())
    out = {'farfield': copy.deepcopy(base)}

    def farfield(n_f=6, n_m=6, **block):
        m = copy.deepcopy(base)
        m['farfields'][0].update({'n_f': n_f, 'n_m': n_m, **block})
        m['simulation'].update(end_time=2e4, matrix='dense')
        return m

    out['ff_matched_cells'] = farfield(report_cells=True)
    out['ff_ref_ob0'] = farfield(grid='reference', o_b=0, n_b='')
    out['ff_ref_ob1'] = farfield(grid='reference', o_b=1, n_b=2)
    out['ff_ref_ob2'] = farfield(grid='reference', o_b=2, n_b='')
    out['ff_ref_ob3'] = farfield(grid='reference', o_b=3, n_b=1, report_cells=True)
    out['ff_matched_ob0'] = farfield(grid='matched', o_b=0, n_b='')
    out['ff_matched_ob3'] = farfield(grid='matched', o_b=3, n_b='')
    out['ff_matched_ob4_nb2'] = farfield(grid='matched', o_b=4, n_b=2, pe='25')
    m = farfield(grid='matched', tw='50 * TW_factor')
    m['lookups'] = [{'name': 'TW_factor', 'unit': '', 'interpolation': 'linear', 'per_nuclide': False,
                     'points': [[0, 1.0], [1000, 1.0], [5000, 1.6], [12000, 0.8], [20000, 1.2]]}]
    out['ff_clock_tw_lookup'] = m
    m = farfield(grid='reference', f='F_table')
    m['lookups'] = [{'name': 'F_table', 'unit': 'year/m', 'interpolation': 'linear', 'per_nuclide': False,
                     'points': [[0, 1e5], [3000, 2e5], [9000, 5e4], [20000, 1e5]]}]
    out['ff_clock_f_lookup_ref'] = m
    out['ff_clock_f_ref'] = farfield(grid='reference', f='1e5 * (1 + interpolationUseEndValues(time, 0, 0, 2e4, 1))')
    out['ff_clock_tw_matched'] = farfield(grid='matched', tw='50 * (1 + 0.5 * rampUp(time, 1e3, 1e4))')
    out['ff_clock_kdm_ref'] = farfield(grid='reference', kd_m='Kd_matrix * (1 + rampUp(time, 1e3, 1e4))')
    out['ff_clock_pendep_matched'] = farfield(grid='matched', pen_dep='12.5 * (1 + rampUp(time, 1e3, 1e4))')
    m = farfield(grid='matched', tw='50 * (1 + 0.5 * rampUp(time, 1e3, 1e4))')
    m['simulation']['min_change_time'] = 500
    out['ff_min_change'] = m
    out['ff_kd_per_nuclide'] = farfield(grid='matched', surface='aw', aw='2000', kd_f='1e-4', eps_m='0.002',
                                        entries=[{'index': {'Radionuclides': 'Th-230'}, 'kd_f': '5e-3', 'eps_m': '0.001'},
                                                 {'index': {'Radionuclides': 'U-234'}, 'kd_f': '2e-4'}])
    out['ff_aperture_ref'] = farfield(grid='reference', surface='aperture', aperture='0.001', pen_dep_0='0.001')
    out['ff_aperture_matched_first'] = farfield(grid='matched', surface='aperture', aperture='0.002',
                                                pen_dep_0='0.0005')
    out['ff_nodecay'] = farfield(grid='matched', handle_decay=False)
    out['ff_nodecay_ref'] = farfield(grid='reference', handle_decay=False, o_b=1, n_b=0)
    out['ff_state_tw'] = farfield(grid='reference', tw='50 * (1 + Vault[U-238] / 1e12)')
    out['ff_state_kdm'] = farfield(grid='matched', kd_m='Kd_matrix * (1 + Well / (1e3 + Well))')
    out['ff_bad_pe'] = farfield(grid='reference', pe='10 - 20 * (time > 1e4)')

    def two_paths(grid, n_f=4, n_m=4):
        m = copy.deepcopy(base)
        m['simulation'].update(end_time=2e4, matrix='dense')
        m['index_lists'] = [{'name': 'Paths', 'indices': [{'name': 'Short', 'enabled': True},
                                                          {'name': 'Long', 'enabled': True}]}]
        m['farfields'][0].update(n_f=n_f, n_m=n_m, grid=grid, index_lists=['Radionuclides', 'Paths'],
                                 tw='TW_path * (1 + 0.5 * rampUp(time, 1e3, 1e4))')
        for c in m['compartments']:
            c['index_lists'] = ['Radionuclides', 'Paths']
        for t in m['transfers']:
            if t.get('index_lists'):
                t['index_lists'] = ['Radionuclides', 'Paths']
        m['parameters'].append({'name': 'TW_path', 'value': 50, 'index_lists': ['Paths'],
                                'entries': [{'index': {'Paths': 'Long'}, 'value': 120}]})
        m['expressions'] = []
        return m

    out['ff_two_paths_matched'] = two_paths('matched')
    out['ff_two_paths_ref'] = two_paths('reference')
    m = copy.deepcopy(base)
    m['simulation'].update(end_time=2e4, matrix='dense')
    m['index_lists'] = [{'name': 'Paths', 'indices': [{'name': 'Short', 'enabled': True},
                                                      {'name': 'Long', 'enabled': True}]},
                        {'name': 'Zones', 'indices': [{'name': 'North', 'enabled': True},
                                                      {'name': 'South', 'enabled': True}]}]
    dims = ['Paths', 'Radionuclides', 'Zones']
    m['farfields'][0].update(n_f=3, n_m=3, grid='matched', index_lists=dims, tw='TW_path * TW_zone',
                             report_cells=True)
    for c in m['compartments']:
        c['index_lists'] = dims
    for t in m['transfers']:
        if t.get('index_lists'):
            t['index_lists'] = dims
    m['parameters'].append({'name': 'TW_path', 'value': 50, 'index_lists': ['Paths'],
                            'entries': [{'index': {'Paths': 'Long'}, 'value': 120}]})
    m['parameters'].append({'name': 'TW_zone', 'value': 1, 'index_lists': ['Zones'],
                            'entries': [{'index': {'Zones': 'South'}, 'value': 1.5}]})
    m['expressions'] = []
    out['ff_three_dims'] = m
    out['ff_tracer'] = {
        'name': 'tracer',
        'simulation': {'start_time': 0, 'end_time': 5000, 'output_points': 60, 'spacing': 'log', 'solver': 'ndf',
                       'rtol': 1e-8, 'abstol': 1e-16, 'time_unit': 'year', 'matrix': 'dense'},
        'compartments': [{'name': 'Source', 'initial': '1000'}, {'name': 'Sink', 'initial': '0'}],
        'transfers': [{'name': 'Leach', 'from': 'Source', 'to': 'Rock', 'rate': '1e-3', 'multiply_by_donor': True},
                      {'name': 'Out', 'from': 'Rock', 'to': 'Sink', 'rate': 'Rock', 'multiply_by_donor': False}],
        'farfields': [{'name': 'Rock', 'index_lists': [], 'tw': '20', 'surface': 'f', 'f': '2e4', 'kd_f': '0',
                       'kd_m': '1e-3', 'de_m': '1e-4', 'eps_m': '0.005', 'rho_m': '2700', 'pe': '10',
                       'pen_dep': '0.5', 'pen_dep_0': '', 'n_f': 8, 'n_m': 6, 'o_b': 4, 'n_b': '', 'grid': 'matched',
                       'handle_decay': True, 'report_cells': True}],
    }

    # --- semi-analytical -----------------------------------------------------------------------
    m = copy.deepcopy(base)
    m['farfields'][0]['method'] = 'semi-analytical'
    out['semi_farfield'] = m
    m = copy.deepcopy(base)
    m['farfields'][0].update(method='semi-analytical', report_cells=True, handle_decay=False)
    m['simulation'].update(end_time=2e4)
    out['semi_nodecay_cells'] = m

    def semi_model(**changes):
        m = {
            'name': 'semi',
            'simulation': {'start_time': 0, 'end_time': 3e4, 'output_points': 40, 'spacing': 'log',
                           'solver': 'ndf', 'rtol': 1e-8, 'abstol': 1e-16, 'time_unit': 'year'},
            'nuclides': ['Aa-1', 'Bb-2', 'Cc-3'], 'half_lives': {'Aa-1': 2000, 'Bb-2': 800, 'Cc-3': 5000},
            'chains': [['Aa-1', 'Bb-2', 0.6], ['Aa-1', 'Cc-3', 0.4]], 'decay_unit': 'mol',
            'waste_packages': [{'name': 'Pack', 'index_lists': ['Radionuclides'], 'failure': 'at', 'fail_at': '700',
                                'inventory': '0', 'irf': '0.2', 'degradation_rate': '2e-3', 'handle_decay': True,
                                'entries': [{'index': {'Radionuclides': 'Aa-1'}, 'inventory': '1000'}]}],
            'compartments': [{'name': 'Near', 'initial': '0', 'index_lists': ['Radionuclides']},
                             {'name': 'Down', 'initial': '0', 'index_lists': ['Radionuclides']}],
            'transfers': [{'name': 'Carrier', 'from': 'Pack', 'to': 'Near', 'rate': 'Pack',
                           'multiply_by_donor': False, 'index_lists': ['Radionuclides']},
                          {'name': 'Leach', 'from': 'Near', 'to': 'Rock', 'rate': '1e-3', 'multiply_by_donor': True},
                          {'name': 'Out', 'from': 'Rock', 'to': 'Down', 'rate': 'Rock', 'multiply_by_donor': False,
                           'index_lists': ['Radionuclides']}],
            'inflows': [{'name': 'Drip', 'to': 'Rock', 'rate': '1e-3 * (time() > 2000)',
                         'index_lists': ['Radionuclides']}],
            'farfields': [{'name': 'Rock', 'index_lists': ['Radionuclides'], 'method': 'semi-analytical',
                           'surface': 'f', 'tw': '50', 'f': '5e4', 'kd_f': '2e-4', 'kd_m': '1e-3', 'de_m': '1e-4',
                           'eps_m': '0.005', 'rho_m': '2700', 'pe': '10', 'pen_dep': '0.1', 'pen_dep_0': '',
                           'n_f': 20, 'n_m': 20, 'o_b': 4, 'n_b': '', 'grid': 'matched', 'handle_decay': True,
                           'report_cells': False,
                           'entries': [{'index': {'Radionuclides': 'Bb-2'}, 'kd_f': '5e-4', 'kd_m': '3e-3',
                                        'de_m': '2e-4'},
                                       {'index': {'Radionuclides': 'Cc-3'}, 'kd_f': '1e-4', 'kd_m': '5e-4'}]}],
        }
        m.update(changes)
        return m

    out['semi_model'] = semi_model()
    out['semi_model_stable'] = semi_model(half_lives={'Aa-1': 'stable', 'Bb-2': 'stable', 'Cc-3': 'stable'},
                                          chains=[])

    def leaching_model(k=1e-3, lam_half=3000.0):
        return {
            'name': 'leaching',
            'simulation': {'start_time': 0, 'end_time': 2e4, 'spacing': 'series',
                           'output_times': [{'kind': 'times', 'times': [100 * 200 ** (q / 29) for q in range(30)]}],
                           'solver': 'ndf', 'rtol': 1e-9, 'abstol': 1e-16, 'time_unit': 'year'},
            'nuclides': ['Xx-1'], 'half_lives': {'Xx-1': lam_half}, 'decay_unit': 'mol',
            'compartments': [{'name': 'Near', 'initial': '1000', 'index_lists': ['Radionuclides']},
                             {'name': 'Down', 'initial': '0', 'index_lists': ['Radionuclides']}],
            'transfers': [{'name': 'Leach', 'from': 'Near', 'to': 'Rock', 'rate': repr(k),
                           'multiply_by_donor': True},
                          {'name': 'Out', 'from': 'Rock', 'to': 'Down', 'rate': 'Rock', 'multiply_by_donor': False,
                           'index_lists': ['Radionuclides']}],
            'farfields': [{'name': 'Rock', 'index_lists': ['Radionuclides'], 'method': 'semi-analytical',
                           'surface': 'f', 'tw': '40', 'f': '4e4', 'kd_f': '5e-4', 'kd_m': '1e-3', 'de_m': '1e-4',
                           'eps_m': '0.005', 'rho_m': '2700', 'pe': '12', 'pen_dep': '0.2', 'pen_dep_0': '',
                           'n_f': 20, 'n_m': 20, 'o_b': 4, 'n_b': '', 'grid': 'matched', 'handle_decay': True,
                           'report_cells': False}],
        }

    out['semi_leaching'] = leaching_model()
    m = leaching_model()
    m['farfields'][0].update(surface='aperture', aperture='0.002', pen_dep='1/0')
    out['semi_leaching_aperture_inf'] = m
    times = [60 * (2e4 / 60) ** (q / 24) for q in range(25)]
    out['semi_plug'] = {
        'name': 'plug flow',
        'simulation': {'start_time': 0, 'end_time': 2e4, 'spacing': 'series',
                       'output_times': [{'kind': 'times', 'times': times}],
                       'solver': 'ndf', 'rtol': 1e-9, 'abstol': 1e-16, 'time_unit': 'year'},
        'nuclides': ['Dd-1'], 'half_lives': {'Dd-1': 8.216e5}, 'decay_unit': 'mol',
        'compartments': [{'name': 'Near', 'initial': '1000', 'index_lists': ['Radionuclides']},
                         {'name': 'Down', 'initial': '0', 'index_lists': ['Radionuclides']}],
        'transfers': [{'name': 'Leach', 'from': 'Near', 'to': 'Rock', 'rate': '1e-3', 'multiply_by_donor': True},
                      {'name': 'Out', 'from': 'Rock', 'to': 'Down', 'rate': 'Rock', 'multiply_by_donor': False,
                       'index_lists': ['Radionuclides']}],
        'farfields': [{'name': 'Rock', 'index_lists': ['Radionuclides'], 'method': 'semi-analytical',
                       'surface': 'aw', 'tw': '50.27', 'aw': '0.3922', 'kd_f': '0', 'kd_m': '0',
                       'de_m': '1.508e-6', 'eps_m': '1.888e-4', 'rho_m': '2700', 'pe': '1/0', 'pen_dep': '1/0',
                       'pen_dep_0': '', 'n_f': 20, 'n_m': 20, 'o_b': 4, 'n_b': '', 'grid': 'matched',
                       'handle_decay': True, 'report_cells': False}],
    }
    m = two_paths('matched')
    m['farfields'][0].update(method='semi-analytical', tw='TW_path')
    m['simulation'].pop('matrix', None)
    out['semi_two_paths'] = m
    m = semi_model()
    m['farfields'][0]['tw'] = '50 + time() / 1000'
    out['semi_refuse_clock'] = m
    m = semi_model()
    m['farfields'][0]['f'] = '5e4 * (1 + Down[Aa-1])'
    out['semi_refuse_state'] = m
    m = semi_model()
    m['inflows'] = [{'name': 'Drip', 'to': 'Rock', 'rate': 'Rock * 0.5', 'index_lists': ['Radionuclides']}]
    out['semi_refuse_loop'] = m
    m = semi_model()
    m['farfields'][0]['entries'][0]['de_m'] = '0'
    out['semi_refuse_half'] = m
    return out


# --- the Jacobian and the responses ---------------------------------------------------------------

def jacobian(name: str, path: Path, engine: dict) -> dict:
    import kompartment as kp
    from kompartment.engine import Project, build_system
    system = build_system(Project(kp.Model.load(path).to_dict()))
    j = system.jacobian
    p = j['pattern']
    out = {'name': name, 'available': bool(j.get('available')), 'reason': j.get('reason'),
           'constant': bool(j.get('constant')), 'col_ptr': p.col_ptr.tolist(), 'row_idx': p.row_idx.tolist(),
           'groups': [g.tolist() for g in j['groups']], 'values': []}
    if j.get('available'):
        for pr in engine['probes']:
            t = float.fromhex(pr['t'])
            y = np.array([float.fromhex(v) for v in pr['y']])
            with np.errstate(all='ignore'):
                J = j['evaluate'](t, y)
            out['values'].append(None if J is None else hexes(J))
    return out


def responses(name: str, path: Path) -> dict:
    import kompartment as kp
    from kompartment.engine import Project, build_system
    from kompartment.engine import farfield_laplace as L
    from kompartment.engine.farfield_semi import LaplaceFarfPath
    system = build_system(Project(kp.Model.load(path).to_dict()))
    out = {'name': name, 'paths': []}
    for F in system.FARF:
        if not isinstance(F, LaplaceFarfPath):
            continue
        for o in range(F.other_width):
            s = F.settings_of(system.X, o)
            lp = L.prepare_path(s, F.D, n=F.nnuc, names=F.names)
            T0 = L.transfer_at_zero(lp)
            evals0 = lp.ws.evaluations
            resps = []
            for j in range(F.nnuc):
                for i in range(F.nnuc):
                    if not lp.reach[j][i]:
                        continue
                    r = L.unit_response(lp, i, j, kind='release', t_max=F.span)
                    resps.append({'i': i, 'j': j, 't': hexes(r['t']), 'h': hexes(r['h']), 'dh': hexes(r['dh']),
                                  'd2h': hexes(r['d2h']), 'm0': float(r.get('m0') or 0.0).hex(),
                                  'integral': float(r['integral']).hex(), 'T0': float(r['T0']).hex(),
                                  'balanced': r.get('balanced'), 'rel': float(r.get('rel', 0.0)).hex(),
                                  'evals': lp.ws.evaluations})
            D = None
            if F.D is not None:
                D = {k: list(F.D[k]) for k in ('ioff', 'icnt', 'ipar')}
                D['lam'] = hexes(F.D['lam'])
                D['icoef'] = hexes(F.D['icoef'])
            out['paths'].append({'o': o, 'surface': s.get('surface'),
                                 'single': {k: float(v).hex() for k, v in s.items()
                                            if k != 'surface' and not isinstance(v, list)},
                                 'each': {k: hexes(v) for k, v in s.items() if isinstance(v, list)},
                                 'D': D, 'span': float(F.span).hex(), 'nnuc': F.nnuc, 'names': F.names,
                                 'T0': hexes(T0), 'evals0': evals0, 'responses': resps})
    return out


def laplace_cases() -> dict:
    """The hard cases of test_farfield_laplace.py, each as a path of its own: sharp fronts (Pe 3000,
    5440, 1e5, 1e6), plug flow (a spike after the delay, point masses, a thin matrix), no matrix,
    a long tail -- what reaches the own-parabola fallbacks, failed cells and de Hoog's method."""
    import math
    from kompartment.engine import farfield_laplace as FL
    ln2 = math.log(2)

    def page_path(params, nucs):
        lam = [ln2 / n['thalf'] if math.isfinite(n['thalf']) else 0.0 for n in nucs]
        pairs = [(q, q + 1, lam[q]) for q, n in enumerate(nucs) if n.get('daughter')]
        return ({'surface': 'aw', 'aw': params['aw'], 'tw': params['tw'], 'rho_m': 2700, 'pe': params['Pe'],
                 'pen_dep': params['x0'], 'kd_f': [n.get('ka', 0.0) for n in nucs], 'eps_m': params['eps'],
                 'kd_m': [n['kd'] for n in nucs], 'de_m': [n['de'] for n in nucs]}, FL.decay_table(lam, pairs))

    def chain(settings, half):
        lam = [ln2 / h if math.isfinite(h) else 0.0 for h in half]
        return settings, FL.decay_table(lam, [(k, k + 1, lam[k]) for k in range(len(lam) - 1)])

    cases = {
        'sharp_5440': page_path({'tw': 260, 'Pe': 5440, 'aw': 4.9, 'eps': 0.002, 'x0': 0.038},
                                [{'thalf': 1.4e7, 'kd': 0, 'de': 7.1e-7, 'ka': 6.6e-5}]) + (None,),
        'spike': page_path({'tw': 119.84, 'Pe': math.inf, 'aw': 380.5, 'eps': 1.085e-4, 'x0': 0.0817},
                           [{'thalf': 2.727e5, 'kd': 0, 'de': 3.157e-3}]) + (None,),
        'hair': page_path({'tw': 50.27, 'Pe': math.inf, 'aw': 0.3922, 'eps': 1.888e-4, 'x0': math.inf},
                          [{'thalf': 13.05, 'kd': 3.703e-4, 'de': 1.508e-6, 'daughter': True},
                           {'thalf': 8.216e5, 'kd': 0, 'de': 1.508e-6}]) + (None,),
        'like_example': chain({'tw': 50, 'f': 1e5, 'rho_m': 2700, 'pe': 10, 'pen_dep': 12.5, 'kd_f': 0,
                               'eps_m': 0.0018, 'kd_m': [0.0017, 0.0017, 0.05], 'de_m': 3.15e-5},
                              [4.468e9, 2.455e5, 7.54e4]) + (1e6,),
        'plug_thin': chain({'tw': 100, 'f': 2e4, 'rho_m': 2700, 'pe': math.inf, 'pen_dep': 0.05, 'kd_f': 1e-4,
                            'eps_m': 0.005, 'kd_m': [1e-3, 0.01], 'de_m': 1e-5}, [2.4e5, math.inf]) + (None,),
        'front_3000': chain({'tw': 20, 'f': 3e3, 'rho_m': 2700, 'pe': 3000, 'pen_dep': 1, 'kd_f': 0,
                             'eps_m': 0.003, 'kd_m': [5e-4, 2e-3], 'de_m': 2e-5}, [1e5, 3e4]) + (None,),
        'tail_300': chain({'tw': 50, 'f': 1e3, 'rho_m': 2700, 'pe': 300, 'pen_dep': math.inf, 'kd_f': 0,
                           'eps_m': 0.002, 'kd_m': [0], 'de_m': 1e-5}, [math.inf]) + (None,),
        'tube_1e5': ({'tw': 100, 'f': 20, 'rho_m': 2700, 'pe': 1e5, 'pen_dep': 1, 'kd_f': 0, 'eps_m': 0.005,
                      'kd_m': 0, 'de_m': 1e-4}, None, 1e6),
        'tube_1e6': ({'tw': 100, 'f': 20, 'rho_m': 2700, 'pe': 1e6, 'pen_dep': 1, 'kd_f': 0, 'eps_m': 0.005,
                      'kd_m': 0, 'de_m': 1e-4}, None, 1e6),
        'no_matrix': ({'tw': 30, 'f': 5e4, 'rho_m': 2700, 'pe': 20, 'pen_dep': 1, 'kd_f': 1e-4, 'eps_m': 0.005,
                       'kd_m': 0, 'de_m': 0}, FL.decay_table([1e-5]), None),
        'thin_chain_plug': ({'surface': 'aw', 'aw': 4.401, 'tw': 2741.36, 'rho_m': 2700, 'pe': math.inf,
                             'pen_dep': 0.001016, 'kd_f': 0.00096121, 'eps_m': 0.0138, 'kd_m': [0.0, 0.0, 0.0],
                             'de_m': [1e-5, 1e-5, 1e-5]},
                            FL.decay_table([1e-4, 2e-5, 1e-6], [(0, 1, 1e-4), (1, 2, 2e-5)]), None),
    }
    out = {'name': 'laplace_cases', 'paths': []}
    for name, (settings, decay, tmax) in cases.items():
        lp = FL.prepare_path(settings, decay)
        T0 = FL.transfer_at_zero(lp)
        evals0 = lp.ws.evaluations
        resps = []
        for j in range(lp.n):
            for i in range(lp.n):
                if not lp.reach[j][i]:
                    continue
                r = FL.unit_response(lp, i, j, kind='release', t_max=tmax)
                resps.append({'i': i, 'j': j, 't': hexes(r['t']), 'h': hexes(r['h']), 'dh': hexes(r['dh']),
                              'd2h': hexes(r['d2h']), 'm0': float(r.get('m0') or 0.0).hex(),
                              'integral': float(r['integral']).hex(), 'T0': float(r['T0']).hex(),
                              'balanced': r.get('balanced'), 'rel': float(r.get('rel', 0.0)).hex(),
                              'evals': lp.ws.evaluations})
        D = None
        if decay is not None:
            D = {k: list(decay[k]) for k in ('ioff', 'icnt', 'ipar')}
            D['lam'] = hexes(decay['lam'])
            D['icoef'] = hexes(decay['icoef'])
        out['paths'].append({'o': name, 'surface': settings.get('surface'),
                             'single': {k: float(v).hex() for k, v in settings.items()
                                        if k != 'surface' and not isinstance(v, list)},
                             'each': {k: hexes(v) for k, v in settings.items() if isinstance(v, list)},
                             'D': D, 'span': float(1e12 if tmax is None else tmax).hex(), 'nnuc': lp.n,
                             'names': None, 'T0': hexes(T0), 'evals0': evals0, 'responses': resps})
    return out


def main() -> None:
    out = Path(sys.argv[1])
    for sub in ('models', 'engine', 'runs', 'jac', 'resp'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    for name, m in models().items():
        m = copy.deepcopy(m)
        path = out / 'models' / f'{name}.json'
        path.write_text(json.dumps(m, indent=1))
        try:
            eng = engine_fixtures.fixture(path)
        except Exception as e:  # noqa: BLE001 - a derivative that raises at a probe: no engine fixture
            print(name, 'no engine fixture:', e)
            eng = None
        if eng is not None:
            (out / 'engine' / f'{name}.json').write_text(json.dumps(eng))
            if 'error' not in eng:
                (out / 'jac' / f'{name}.json').write_text(json.dumps(jacobian(name, path, eng)))
                if name.startswith('semi_'):
                    (out / 'resp' / f'{name}.json').write_text(json.dumps(responses(name, path)))
        run = run_fixtures.fixture(path)
        (out / 'runs' / f'{name}.json').write_text(json.dumps(run))
        st = run.get('stats') or {}
        print(name, run.get('error') or f"{st.get('solver')} {st.get('nsteps')} steps, {len(run['t'])} times")
    (out / 'resp' / 'laplace_cases.json').write_text(json.dumps(laplace_cases()))
    print('laplace_cases')


if __name__ == '__main__':
    main()
