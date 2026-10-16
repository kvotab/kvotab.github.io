"""Reference analyses for the Julia port's tests, from the Python package.

Writes, as JSON with every float as its hex text (``float.hex``), what the
Julia ports of the sensitivity designs (``kompartment/stats/gsa.py`` and
``salib.py``), the calibration (``kompartment/engine/calibrate.py`` and
``kompartment/stats/optimise.py``) and the local sensitivity
(``kompartment/engine/localsens.py``) must reproduce bit for bit:

- ``designs/<case>.json``: a sensitivity design over a variant of the
  biosphere example -- every method, settings given as text, correlation
  groups, correlated pairs (Shapley's copula, weakened where they are not
  consistent), lists read by probability, a varied subset -- with each
  factor's probability at every run, every value drawn and the statistics the
  page reads;
- ``calibrations/<case>.json``: a calibration of a bundled example by each
  method -- every step the search took, and the result -- and the refusals;
- ``sensitivity/<case>.json``: dy/dp of the bundled examples whose augmented
  system is below 64 states, where its iteration matrix is factorised dense
  (from 64 on it may be factorised sparse, by SuperLU here and KLU in Julia,
  which round differently), with df/dp differentiated and differenced: the
  times, every state and every sensitivity; and the refusals.

    python3 tools/analysis_fixtures.py OUT_DIR

Run it with the repository's Python package on the path
(``PYTHONPATH=kompartment/python``). Nothing is written in the repository.
"""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent.parent / 'examples'


def hexes(v):
    return [float(x).hex() for x in np.asarray(v, dtype=float).ravel()]


def plain(v):
    """Something JSON can hold, floats as hex text."""
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, np.ndarray):
        return [plain(x) for x in v.tolist()]
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return {'$f': float(v).hex()}
    return v


def example(name):
    return json.loads((EXAMPLES / name).read_text())


# --- sensitivity designs -----------------------------------------------------------------------

def variant(name):
    raw = example('biosphere.json')
    sim = raw['simulation']
    params = {p['name']: p for p in raw['parameters']}
    if name == 'corr':
        sim['correlations'] = [{'group': 'Kd', 'r': 0.9}, {'a': 'soilLeach', 'b': 'geoTransit', 'r': -0.6},
                               {'a': 'wellVolume', 'b': 'intake', 'r': 0.5}]
    elif name == 'clash':
        # Not consistent with each other: Shapley's copula is weakened until they are.
        sim['correlations'] = [{'a': 'leachRate[I-129]', 'b': 'leachRate[Cl-36]', 'r': 0.95},
                               {'a': 'leachRate[Cl-36]', 'b': 'leachRate[Tc-99]', 'r': 0.95},
                               {'a': 'leachRate[I-129]', 'b': 'leachRate[Tc-99]', 'r': -0.95},
                               {'a': 'rho', 'b': 'porosity', 'r': 0.7}, {'a': 'rho', 'b': 'nothere', 'r': 0.2}]
    elif name == 'grouped':
        for e in params['leachRate']['entries']:
            e['pdf']['group'] = 'G'
        params['rho']['pdf']['group'] = 'H'
        params['porosity']['pdf']['group'] = 'H'
        sim['correlations'] = [{'a': 'leachRate[I-129]', 'b': 'soilLeach', 'r': 0.4},
                               {'a': 'rho', 'b': 'intake', 'r': -0.3}, {'a': 'rho', 'b': 'porosity', 'r': 0.3}]
    elif name == 'kinds':
        params['geoTransit']['pdf'] = {'kind': 'norm', 'params': {'mean': 300, 'sd': 40}, 'values': None,
                                       'trmin': 250, 'trmax': None, 'inorder': True, 'pos': 0}
        params['soilLeach']['pdf'] = {'kind': 'unif', 'params': {'min': 0.001, 'max': 0.01}, 'values': None,
                                      'trmin': None, 'trmax': None, 'inorder': True, 'pos': 0}
        params['wellVolume']['pdf'] = {'kind': 'pg', 'params': {}, 'values': [1e5, 2e5, 4e5, 3e5],
                                       'trmin': None, 'trmax': None, 'inorder': True, 'pos': 1}
        params['wellTurnover']['pdf'] = {'kind': 'pg', 'params': {}, 'values': [0.5, 1, 2],
                                         'trmin': None, 'trmax': None, 'inorder': False, 'pos': 0}
        params['intake']['pdf'] = {'kind': 'logu', 'params': {'min': 0.5, 'max': 2}, 'values': None,
                                   'trmin': None, 'trmax': None, 'inorder': True, 'pos': 0}
    return raw


EVERY_METHOD = [
    ('morris', 'morris', {}),
    ('morris2', 'morris', {'trajectories': 4, 'points': 6, 'levels': 8}),
    ('traj', 'morris', {'design': 'trajectories', 'trajectories': 4, 'levels': 6, 'candidates': 10}),
    ('traj0', 'morris', {'design': 'trajectories', 'trajectories': 3, 'levels': 5}),
    ('radial', 'radial', {'samples': 20}),
    ('sobol', 'sobol', {'samples': 16}),
    ('sobol2', 'sobol', {'samples': 8, 'second': True, 'blocks': 2}),
    ('efast', 'efast', {'samples': 70, 'harmonics': 4}),
    ('efast2', 'efast', {'samples': '200', 'harmonics': 2}),
    ('rbdfast', 'rbdfast', {'samples': 64}),
    ('ff', 'ff', {}),
    ('ff2', 'ff', {'low': 0.1, 'high': '0.8'}),
    ('dgsm', 'dgsm', {'samples': 10}),
    ('dgsm2', 'dgsm', {'samples': 6, 'crossed': True, 'step': 0.01}),
    ('shapley', 'shapley', {'perms': 3, 'nVar': 20, 'nOuter': 2, 'nInner': 3}),
]


def design_cases():
    out = []
    for v in ('base', 'grouped', 'kinds'):
        for tag, method, options in EVERY_METHOD:
            out.append((f'{v}-{tag}', v, None, {'method': method, 'options': options}))
    for v in ('corr', 'clash', 'grouped'):
        out.append((f'{v}-shapleyc', v, None,
                    {'method': 'shapley', 'options': {'perms': 2, 'nVar': 30, 'nOuter': 2, 'nInner': 2}}))
        out.append((f'{v}-sobolc', v, None, {'method': 'sobol', 'options': {'samples': 10}}))
    small = ['geoTransit', 'Kd[I-129]', 'soilLeach']
    out.append(('small-shapley', 'corr', small, {'method': 'shapley', 'options': {}}))
    out.append(('small-shapley1', 'corr', small,
                {'method': 'shapley', 'options': {'perms': 0, 'nVar': 50, 'nOuter': 3, 'nInner': 2}}))
    out.append(('small-traj', 'corr', small, {'method': 'morris', 'options': {
        'design': 'trajectories', 'trajectories': 2, 'candidates': 6, 'levels': 4}}))
    return out


def write_designs(root):
    from kompartment.engine.builder import build_system
    from kompartment.engine.probabilistic import design_for
    from kompartment.engine.project import Project
    (root / 'designs').mkdir(parents=True, exist_ok=True)
    for case, v, varied, gsa in design_cases():
        raw = variant(v)
        project = Project(raw)
        d = design_for(project, build_system(project), seed=7, gsa=gsa, varied=varied)
        values = [[d.value_for(k, i) for i in range(d.iterations)] for k in range(len(d.plan))]
        (root / 'designs' / f'{case}.json').write_text(json.dumps({
            'case': case, 'model': raw, 'seed': 7, 'gsa': gsa, 'varied': varied, 'names': d.names,
            'iterations': d.iterations, 'u': [hexes(row) for row in np.asarray(d.gsa_design['u'])],
            'values': [hexes(row) for row in values], 'stats': plain(d.stats['gsa']),
        }))
        print('design', case, d.iterations)


# --- calibrations ------------------------------------------------------------------------------

CALIBRATIONS = [
    {'case': 'exp-nelder', 'file': 'exponential-decay.json', 'method': 'nelder', 'maxEvals': 60,
     'variables': [{'key': 'k', 'lower': 0.1, 'upper': 3, 'space': 'linear', 'start': None}],
     'targets': [{'output': 'y', 'when': 'at', 'time': 2, 'value': 0.2, 'scale': 'relative'}]},
    {'case': 'exp-lm', 'file': 'exponential-decay.json', 'method': 'lm', 'maxEvals': 60,
     'variables': [{'key': 'k', 'lower': 0.1, 'upper': 3, 'space': 'log'}, {'key': 'y0', 'lower': 0.5, 'upper': 2}],
     'targets': [{'output': 'y', 'when': 'at', 'time': 2, 'value': 0.2},
                 {'output': 'y', 'when': 'end', 'value': 1e-4, 'scale': 'log'}]},
    {'case': 'exp-de', 'file': 'exponential-decay.json', 'method': 'de', 'maxEvals': 50, 'seed': 3,
     'variables': [{'key': 'k', 'lower': 0.1, 'upper': 3}, {'key': 'y0', 'lower': 0.5, 'upper': 2, 'start': 1.5}],
     'targets': [{'output': 'y', 'when': 'peak', 'value': 1.2, 'weight': 2},
                 {'output': 'y', 'when': 'at', 'time': 5, 'value': 0.01, 'scale': 'absolute'}]},
    {'case': 'mm-nelder', 'file': 'michaelis-menten.json', 'method': 'nelder', 'maxEvals': 40,
     'variables': [{'key': 'kf', 'lower': 0.1, 'upper': 10, 'space': 'log'},
                   {'key': 'kcat', 'lower': 0.05, 'upper': 5, 'space': 'log'}],
     'targets': [{'output': 'P', 'when': 'at', 'time': 100, 'value': 3}, {'output': 'S', 'when': 'at', 'time': 300,
                                                                          'value': 1}]},
    {'case': 'four-lm', 'file': 'four-compartment.json', 'method': 'lm', 'maxEvals': 30,
     'variables': [{'key': 'p12[Fo-42]', 'lower': 1e-7, 'upper': 1e-3, 'space': 'log'},
                   {'key': 'p23[Fo-42]', 'lower': 1e-7, 'upper': 1e-3, 'space': 'log'}],
     'targets': [{'output': 'C2 [Fo-42]', 'when': 'peak', 'value': 2e9, 'scale': 'log'},
                 {'output': 'C3 [Fo-42]', 'when': 'end', 'value': 1e4, 'scale': 'log'}]},
    {'case': 'four-unknown-method', 'file': 'four-compartment.json', 'method': 'simplex', 'maxEvals': 12,
     'variables': [{'key': 'p13[Fo-42]', 'lower': 1e-7, 'upper': 1e-3, 'space': 'nonsense'}],
     'targets': [{'output': 'nothere', 'when': 'peak', 'value': 2}, {'output': 'C4 [Fo-42]', 'when': 'peak',
                                                                     'value': 1e9}]},
    {'case': 'err-no-targets', 'file': 'exponential-decay.json', 'method': 'nelder',
     'variables': [{'key': 'k', 'lower': 0.1, 'upper': 3}], 'targets': [{'output': '', 'value': 1}]},
    {'case': 'err-no-variables', 'file': 'exponential-decay.json', 'variables': [],
     'targets': [{'output': 'y', 'value': 1}]},
    {'case': 'err-unknown', 'file': 'exponential-decay.json', 'variables': [{'key': 'kk', 'lower': 0, 'upper': 1}],
     'targets': [{'output': 'y', 'value': 1}]},
    {'case': 'err-range', 'file': 'exponential-decay.json', 'variables': [{'key': 'k', 'lower': 2, 'upper': 1}],
     'targets': [{'output': 'y', 'value': 1}]},
    {'case': 'err-log', 'file': 'exponential-decay.json',
     'variables': [{'key': 'k', 'lower': 0, 'upper': 1, 'space': 'log'}], 'targets': [{'output': 'y', 'value': 1}]},
]


def write_calibrations(root):
    from kompartment.engine.calibrate import calibrate
    (root / 'calibrations').mkdir(parents=True, exist_ok=True)
    for c in CALIBRATIONS:
        steps = []
        out = dict(c)
        try:
            res = calibrate(example(c['file']), targets=c.get('targets'), variables=c.get('variables'),
                            method=c.get('method'), max_evals=c.get('maxEvals'), seed=c.get('seed'),
                            on_progress=steps.append)
            res.pop('ms')
            out.update({'result': plain(res), 'steps': plain(steps)})
        except Exception as e:  # noqa: BLE001 - a refusal is what is being recorded
            out['error'] = [type(e).__name__, str(e)]
        (root / 'calibrations' / f"{c['case']}.json").write_text(json.dumps(out))
        print('calibration', c['case'], out.get('error') or out['result']['reason'])


# --- dy/dp -------------------------------------------------------------------------------------

SENSITIVITY = [
    # (case, example, parameters, differenced)
    ('biosphere', 'biosphere.json', ['leachRate[I-129]', 'geoTransit'], False),
    ('brusselator', 'brusselator.json', ['A', 'B'], False),
    ('brusselator-d', 'brusselator.json', ['A', 'B'], True),
    ('exponential-decay', 'exponential-decay.json', ['k', 'y0'], False),
    ('four-compartment', 'four-compartment.json', ['p12[Fo-42]', 'p23[Fo-42]', 'p13[Fo-42]'], False),
    ('four-compartment-d', 'four-compartment.json', ['p13[Fo-42]', 'p34[Fo-42]'], True),
    ('harmonic-oscillator', 'harmonic-oscillator.json', ['period', 'zeta', 'x0'], False),
    ('lookup-driver', 'lookup-driver.json', ['V_rego', 'k_sed', 'DC'], False),
    ('lookup-driver-d', 'lookup-driver.json', ['V_rego', 'k_sed'], True),
    ('lotka-volterra', 'lotka-volterra.json', ['alpha', 'beta', 'gamma'], False),
    ('michaelis-menten', 'michaelis-menten.json', ['S0', 'E0', 'kf'], False),
    ('michaelis-menten-d', 'michaelis-menten.json', ['kr', 'kcat'], True),
    ('recorders', 'recorders.json', ['k_out[Cs-137]', 'Volume[Cs-137]', 'DoseCoeff[Cs-137]'], False),
    ('recorders-d', 'recorders.json', ['Volume[Cs-137]', 'Limit'], True),
    ('scenarios', 'scenarios.json', ['Runoff', 'LakeVolume', 'Flush'], False),
    ('sir-epidemic', 'sir-epidemic.json', ['N', 'I0', 'beta'], False),
    ('van-der-pol-stiff', 'van-der-pol-stiff.json', ['mu'], False),
    ('van-der-pol-d', 'van-der-pol.json', ['mu'], True),
    # Refused, each for its own reason.
    ('bouncing-ball', 'bouncing-ball.json', ['g', 'v0'], False),
    ('decay-chain', 'decay-chain.json', [], False),
    ('post-processing', 'post-processing.json', ['DC[I-129]'], False),
    ('waste-packages', 'waste-packages.json', ['matrix_rate'], False),
    ('robertson-d', 'robertson.json', ['k2', 'k3'], True),
]


def write_sensitivities(root):
    from kompartment.engine.localsens import run_sensitivity
    (root / 'sensitivity').mkdir(parents=True, exist_ok=True)
    for case, name, params, differenced in SENSITIVITY:
        out = {'case': case, 'file': name, 'parameters': params, 'differenced': differenced}
        try:
            r = run_sensitivity(example(name), params, differenced=differenced)
        except Exception as e:  # noqa: BLE001 - a refusal is what is being recorded
            out['error'] = [type(e).__name__, str(e)]
        else:
            if len(r['y']) * (1 + len(r['sens'])) >= 64:
                raise SystemExit(f'{case}: 64 states or more, where the iteration matrix may be sparse')
            out.update({'t': hexes(r['t']), 'y': [hexes(v) for v in r['y']],
                        'sens': [[hexes(v) for v in block] for block in r['sens']],
                        'chosen': plain(r['chosen']), 'nsteps': r['stats']['nsteps'],
                        'restarts': r['stats']['restarts'],
                        'series': [{k: s[k] for k in ('offset', 'label', 'hidden')} for s in r['series']]})
        (root / 'sensitivity' / f'{case}.json').write_text(json.dumps(out))
        print('dy/dp', case, out.get('error', [None, ''])[1][:60] or out['nsteps'])


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    root = Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=True)
    write_designs(root)
    write_calibrations(root)
    write_sensitivities(root)


if __name__ == '__main__':
    main()
