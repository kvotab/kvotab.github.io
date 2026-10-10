"""Reference plans and split runs for the Julia engine's tests, from the Python engine.

For every bundled example and the made-up models of the Python package's own
split tests (``python/tests/test_engine_split.py``) this writes, as JSON: the
partition, the names states are filed back by, their materials, the jobs, the
plan under each of a set of options (with the constants it was planned with,
for the Julia planner to be given the same) and the bins' jobs; and, for some
of them, split runs at several worker counts -- the output times, every
state's values (each float as its hex text) and each bin's materials and
steps.

    PYTHONPATH=../python python3 tools/split_fixtures.py OUT_DIR

The split runs start processes (``spawn``); a run takes a few seconds.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent.parent / 'examples'

SIM = {'start_time': 0, 'end_time': 100, 'output_points': 21, 'spacing': 'linear', 'solver': 'ndf',
       'rtol': 1e-8, 'abstol': 1e-14, 'time_unit': 'year'}


# --- the made-up models of python/tests/test_engine_split.py ---------------------------------

def chains(count: int, length: int, compartments: int, *, points: int = 40, rtol: float = 1e-6) -> Dict[str, Any]:
    letters = 'abcdefghijklmnopqrstuvwxyz'
    names: List[str] = []
    half: Dict[str, float] = {}
    pairs: List[List[Any]] = []
    for c in range(count):
        element = 'Q' + letters[c % 26] + ('' if c < 26 else letters[c // 26])
        chain = [f'{element}-{100 + k}' for k in range(length)]
        for k, name in enumerate(chain):
            names.append(name)
            half[name] = 10 ** (1 + ((k * 7 + c * 3) % 11) * 0.5)
        pairs += [[chain[k], chain[k + 1], 1.0] for k in range(length - 1)]
    return {
        'name': f'{count} chains of {length} through {compartments}',
        'nuclides': names,
        'half_lives': half,
        'chains': pairs,
        'simulation': {'start_time': 0, 'end_time': 1e5, 'output_points': points, 'spacing': 'log',
                       'solver': 'ndf', 'rtol': rtol, 'abstol': 1e-6, 'time_unit': 'year'},
        'parameters': [{'name': f'k{j}', 'value': 10 ** (-1 - j * 0.7), 'index_lists': []} for j in range(5)],
        'compartments': [{'name': f'C{i}', 'initial': '1e6' if i == 0 else '0', 'index_lists': ['Radionuclides']}
                         for i in range(compartments)],
        'transfers': [{'name': f'T{i}', 'from': f'C{i}', 'to': f'C{i + 1}', 'rate': f'k{i % 5}',
                       'index_lists': ['Radionuclides']} for i in range(compartments - 1)],
    }


def two(**extra: Any) -> Dict[str, Any]:
    m = {
        'name': 'two',
        'nuclides': ['Cs-137', 'Sr-90'],
        'simulation': dict(SIM),
        'parameters': [{'name': 'k1', 'value': 0.2}, {'name': 'k2', 'value': 0.05}],
        'compartments': [{'name': 'A', 'initial': '1'}, {'name': 'B', 'initial': '0'}, {'name': 'C', 'initial': '0'}],
        'transfers': [{'name': 'AB', 'from': 'A', 'to': 'B', 'rate': 'k1'},
                      {'name': 'BC', 'from': 'B', 'to': 'C', 'rate': 'k2'}],
    }
    m.update(extra)
    return m


REFUSED = {
    'nothing to integrate': {'name': 'no states', 'simulation': dict(SIM), 'parameters': [{'name': 'a', 'value': 1}]},
    'no analytic Jacobian': two(transfers=[{'name': 'AB', 'from': 'A', 'to': 'B', 'rate': '0.1 * factorial(B)'}]),
    'a delay': two(delays=[{'name': 'Late', 'target': 'B', 'delay': '10'}]),
    'a trigger': two(triggers=[{'name': 'Half', 'first': 'B', 'second': '0.5', 'direction': 'rising'}]),
    'one material in two parts': {
        'name': 'shared', 'nuclides': ['Cs-137'], 'simulation': dict(SIM),
        'compartments': [{'name': n, 'initial': '1' if n in 'AC' else '0'} for n in 'ABCD'],
        'transfers': [{'name': 'AB', 'from': 'A', 'to': 'B', 'rate': '0.1'},
                      {'name': 'CD', 'from': 'C', 'to': 'D', 'rate': '0.3'}],
    },
}

RECORDING = two(min_maxes=[{'name': 'PeakB', 'target': 'B', 'operation': 'max'},
                           {'name': 'LowA', 'target': 'A', 'operation': 'min'}],
                running_means=[{'name': 'MeanB', 'target': 'B'}])
ACROSS = two(index_reductions=[{'name': 'TotalB', 'target': 'B', 'operation': 'sum', 'per_nuclide': False,
                                'index_lists': []}],
             min_maxes=[{'name': 'PeakTotal', 'target': 'TotalB', 'operation': 'max', 'index_lists': []}])
PINNED = {
    'name': 'pinned', 'nuclides': ['Cs-137', 'Sr-90'],
    'simulation': {**SIM, 'output_points': 11, 'rtol': 1e-9},
    'parameters': [{'name': 'Coef', 'index_lists': ['Radionuclides'], 'value': 0.01,
                    'entries': [{'index': {'Radionuclides': 'Cs-137'}, 'value': 0.05}]}],
    'compartments': [{'name': 'A', 'initial': '1'}, {'name': 'B', 'initial': '0'}],
    'transfers': [{'name': 'AB', 'from': 'A', 'to': 'B', 'rate': 'Coef[Cs-137]'}],
}


def example(name: str) -> Dict[str, Any]:
    return json.loads((EXAMPLES / f'{name}.json').read_text('utf-8'))


def farfield_two_parts() -> Dict[str, Any]:
    """The far-field example with I-129 beside its U-238 chain: two parts on one path's layers."""
    model = example('farfield')
    model['nuclides'] = model['nuclides'] + ['I-129']
    model['simulation'] = {**model['simulation'], 'spacing': 'log'}
    model['simulation'].pop('output_times', None)
    model['expressions'] = []
    model['compartments'][0].setdefault('entries', []).append(
        {'index': {'Radionuclides': 'I-129'}, 'initial': '1e12'})
    next(p for p in model['parameters'] if p['name'] == 'Kd_matrix')['entries'].append(
        {'index': {'Radionuclides': 'I-129'}, 'value': 0})
    return model


#: The options every model is planned under: off, on at several worker counts and one, and
#: every branch of auto (the Python package's OPTIONS, with ``build_fixed`` and ``nest`` too).
OPTIONS = [
    {'mode': 'off', 'workers': 4},
    {'mode': 'on', 'workers': 4},
    {'mode': 'on', 'workers': 3},
    {'mode': 'on', 'workers': 16},
    {'mode': 'on', 'workers': 1},
    {'mode': 'on', 'workers': 4, 'nest': False},
    {'mode': 'auto', 'workers': 4},
    {'mode': 'auto', 'workers': 8, 'known': {'solve_ms': 200}},
    {'mode': 'auto', 'workers': 4, 'known': {'solve_ms': 60000}, 'build_ms': 100},
    {'mode': 'auto', 'workers': 2, 'known': {'solve_ms': 5000}, 'build_ms': 2000},
    {'mode': 'auto', 'workers': 4, 'known': {'solve_ms': 60000, 'gain': 1.1}},
    {'mode': 'auto', 'workers': 4, 'known': {'solve_ms': 900, 'gain': 2.1}},
    {'mode': 'auto', 'workers': 4, 'known': {'solve_ms': 4000, 'build_fixed': 1.0}, 'build_ms': 3000},
    {'mode': 'auto', 'workers': 8, 'known': {'solve_ms': 40000, 'build_fixed': 0.8}, 'build_ms': 500},
    {'mode': 'nonsense', 'workers': 4, 'known': {'solve_ms': 60000}, 'build_ms': 10},
]

#: The models whose split runs are recorded, and the worker counts each is run at.
RUNS = {
    'biosphere': [2, 3, 4],
    'landscape': [3],
    'waste-packages': [4],
    'chains(6,5,4)': [3],
    'recording': [2],
    'pinned': [2],
    'farfield and I-129': [2],
}


def models() -> Dict[str, Dict[str, Any]]:
    out = {path.stem: json.loads(path.read_text('utf-8')) for path in sorted(EXAMPLES.glob('*.json'))}
    out.update({'chains(3,4,3)': chains(3, 4, 3), 'chains(5,3,4)': chains(5, 3, 4), 'chains(6,5,4)': chains(6, 5, 4),
                'chains(12,4,45)': chains(12, 4, 45), 'two': two(), 'recording': RECORDING, 'across': ACROSS,
                'pinned': PINNED, 'farfield and I-129': farfield_two_parts()})
    out.update({f'refused: {k}': v for k, v in REFUSED.items()})
    return out


def plain(v: Any) -> Any:
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.ndarray):
        return [plain(x) for x in v.tolist()]
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    return v


def hexes(v: Any) -> List[str]:
    return [float(x).hex() for x in np.asarray(v, dtype=float).ravel()]


def fixture(name: str, model: Dict[str, Any]) -> Dict[str, Any]:
    from kompartment.engine import split as S
    from kompartment.engine.builder import build_system
    from kompartment.engine.partition import partition_of
    from kompartment.engine.project import Project
    from kompartment.engine.runner import run
    out: Dict[str, Any] = {'name': name, 'model': model}
    project = Project(copy.deepcopy(model))
    system = build_system(project)
    p = partition_of(system)
    out['partition'] = {'ok': p['ok'], 'refusal': p['refusal'], 'count': p['count'], 'of': plain(p['of']),
                        'sizes': plain(p['sizes']), 'largest': p['largest']}
    if system.layout.nstate:
        out['keys'] = S.state_keys(system.layout)
        out['materials'] = S.state_materials(system.layout)
    jobs = S.split_jobs(system)
    out['jobs'] = ({'ok': True, 'jobs': plain(jobs['jobs']), 'owner': plain(jobs['owner']), 'parts': jobs['parts'],
                    'recorders': plain(jobs['recorders'])} if jobs['ok'] else {'ok': False, 'why': jobs['why']})
    out['constants'] = {k: getattr(S, k) for k in ('SHARED_WORK', 'AUTO_STATES', 'AUTO_SOLVE_MS', 'AUTO_GAIN',
                                                   'AUTO_GAIN_UNTIMED', 'START_MS')}
    plans = []
    for o in OPTIONS:
        plan = S.plan_split(system, project, mode=o['mode'], workers=o['workers'], nest=o.get('nest', True),
                            build_ms=o.get('build_ms', 0.0), known=o.get('known'))
        view = {'use': plan['use'], 'mode': plan['mode'], 'why': plan['why'], 'predicted': plan.get('predicted')}
        if plan['use']:
            view.update(jobs=plain(plan['jobs']), owner=plain(plan['owner']), bins=plain(plan['bins']),
                        parts=plan['parts'])
            binned = S.bin_jobs(plan)
            view['binned'] = {'jobs': plain(binned['jobs']), 'owner': plain(binned['owner']),
                              'recorders': plain(binned['recorders'])}
        plans.append({'options': o, 'plan': view})
    out['plans'] = plans
    layers = S.whole_layers(system, project)
    if layers is not None:
        out['layers'] = {path: {key: {'d': hexes(g['d']), 'h': hexes(g['h']), 'q': float(g['q']).hex()}
                                for key, g in combos.items()} for path, combos in layers.items()}
    runs = []
    for workers in RUNS.get(name, []):
        m = copy.deepcopy(model)
        m['simulation'] = {**(m.get('simulation') or {}), 'split': 'on'}
        res = run(Project(m), workers=workers)
        account = res.stats['split']
        if not account['used']:
            raise RuntimeError(f"{name}: not split ({account['why']})")
        runs.append({'workers': workers, 't': hexes(res.t), 'y': hexes(np.asarray(res.y)),
                     'nstate': int(np.asarray(res.y).shape[1]),
                     'jobs': [{'materials': j['materials'], 'states': j['states'], 'nsteps': j['nsteps']}
                              for j in account['jobs']],
                     'why': account['why'], 'nsteps': int(res.stats['nsteps']),
                     'labels': [o['label'] for o in res.outputs()],
                     'series': [hexes(c) for c in res.series_many(res.outputs())]})
    out['runs'] = runs
    return out


def main() -> None:
    # What auto learns from these runs is not kept: they are not this machine's runs of a model.
    os.environ.setdefault('KOMPARTMENT_SPLIT_MEMORY', '0')
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, (name, model) in enumerate(models().items()):
        data = fixture(name, model)
        (out_dir / f'{k:02d}.json').write_text(json.dumps(data))
        print(name, '-', data['jobs'].get('why') or f"{len(data['jobs']['jobs'])} jobs",
              f"{len(data['runs'])} split runs" if data['runs'] else '')


if __name__ == '__main__':
    main()
