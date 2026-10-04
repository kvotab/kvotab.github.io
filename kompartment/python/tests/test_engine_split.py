"""Split into parts: the plan against the application's, and split runs against whole ones.

* The partition of every bundled example, and of made-up models, is the
  application's (``partitionOf``), and so are the jobs, the names every state
  is filed back by, the plan (``planSplit``) and every refusal's words -- the
  automatic choice with the application's constants put in, since this
  engine's are its own.
* A split run agrees with the whole model's to within the tolerance, every
  series. Its parts are packed into one bin per process and each bin is
  built once, as the application does; a bin is the same run, filed back as
  it came, in whichever process takes it.
* What a split measured is weighed against a whole solve estimated from its
  bins, and the series after a compiled split are worked out on the whole
  model compiled, to the Python passes' last bit.
* Where this engine does what the application does not -- a SciPy solver
  split, the histories of a min/max and a running mean carried back, a
  min/max that reads more than one part refused -- it is tested here too.

Set ``KOMPARTMENT_SPLIT_TIMING=1`` for a timing on a made-up model of
independent decay chains, whole against split.
"""

from __future__ import annotations

import copy
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import numpy as np

from helpers import EXAMPLES as EXAMPLES_DIR, PACKAGE, example, needs_app
from test_engine_lang import engine

from kompartment.engine.builder import build_system
from kompartment.engine.partition import partition_of, state_partition
from kompartment.engine.project import Project
from kompartment.engine.runner import run
from kompartment.engine.solvers import SolverError

try:
    import numba  # noqa: F401
    HAVE_NUMBA = True
except Exception:  # noqa: BLE001 - optional
    HAVE_NUMBA = False

S = importlib.import_module('kompartment.engine.split')

EXAMPLES = ['four-compartment', 'decay-chain', 'biosphere', 'lookup-driver', 'post-processing', 'scenarios',
            'landscape', 'recorders', 'farfield', 'waste-packages']

#: How far a split run may be from the whole run, as a share of each series'
#: peak: the application's own test allows the same.
AGREE = 2e-4

SIM = {'start_time': 0, 'end_time': 100, 'output_points': 21, 'spacing': 'linear', 'solver': 'ndf',
       'rtol': 1e-8, 'abstol': 1e-14, 'time_unit': 'year'}


# --- made-up models -------------------------------------------------------------------------

def chains(count: int, length: int, compartments: int, *, points: int = 40, rtol: float = 1e-6) -> Dict[str, Any]:
    """``count`` decay chains of ``length`` made-up nuclides, through
    ``compartments`` compartments in a line. No chain reaches another, so the
    model is ``count`` parts, each with its own stiffness."""
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
    """Two nuclides through three compartments, the middle one filling and
    emptying: two parts, one per nuclide."""
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


def with_split(model: Dict[str, Any], mode: str, **simulation: Any) -> Project:
    m = copy.deepcopy(model)
    m['simulation'] = {**(m.get('simulation') or {}), 'split': mode, **simulation}
    return Project(m)


#: Models that are refused, one for each reason the application gives, and
#: what they are refused for.
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

#: A min/max and a running mean per nuclide, whose histories a split carries
#: back; and a min/max of the total over nuclides, which no part can give.
RECORDING = two(min_maxes=[{'name': 'PeakB', 'target': 'B', 'operation': 'max'},
                           {'name': 'LowA', 'target': 'A', 'operation': 'min'}],
                running_means=[{'name': 'MeanB', 'target': 'B'}])
ACROSS = two(index_reductions=[{'name': 'TotalB', 'target': 'B', 'operation': 'sum', 'per_nuclide': False,
                                'index_lists': []}],
             min_maxes=[{'name': 'PeakTotal', 'target': 'TotalB', 'operation': 'max', 'index_lists': []}])

#: Coef[Cs-137] read by every nuclide: strontium's part has caesium switched
#: off and must switch it back on to build (the application's own case).
PINNED = {
    'name': 'pinned', 'nuclides': ['Cs-137', 'Sr-90'],
    'simulation': {**SIM, 'output_points': 11, 'rtol': 1e-9},
    'parameters': [{'name': 'Coef', 'index_lists': ['Radionuclides'], 'value': 0.01,
                    'entries': [{'index': {'Radionuclides': 'Cs-137'}, 'value': 0.05}]}],
    'compartments': [{'name': 'A', 'initial': '1'}, {'name': 'B', 'initial': '0'}],
    'transfers': [{'name': 'AB', 'from': 'A', 'to': 'B', 'rate': 'Coef[Cs-137]'}],
}


# --- comparing ------------------------------------------------------------------------------

def worst(a: Any, b: Any) -> float:
    """The largest difference over every series, each as a share of its peak."""
    outs = a.outputs()
    theirs = {o['label']: o for o in b.outputs()}
    ca = a.series_many(outs)
    cb = b.series_many([theirs[x['label']] for x in outs])
    out = 0.0
    for x, y in zip(ca, cb):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        peak = float(np.max(np.abs(x))) if x.size else 0.0
        out = max(out, float(np.max(np.abs(x - y))) / (peak or 1.0) if x.size else 0.0)
    return out


def python_opts(o: Dict[str, Any]) -> Dict[str, Any]:
    """The application's ``planSplit`` options, as :func:`plan_split` takes them."""
    out: Dict[str, Any] = {'mode': o.get('mode', 'auto'), 'workers': o.get('workers', 1),
                           'nest': o.get('nest', True), 'build_ms': o.get('buildMs', 0)}
    if o.get('known') is not None:
        out['known'] = {'solve_ms': o['known'].get('solveMs'), 'gain': o['known'].get('gain')}
    return out


def plan_view(p: Dict[str, Any]) -> Dict[str, Any]:
    """What a plan says, in the application's terms."""
    out = {'use': p['use'], 'mode': p['mode'], 'why': p['why'], 'predicted': p.get('predicted')}
    if p['use']:
        out.update(jobs=[{'materials': j['materials'], 'states': j['states']} for j in p['jobs']],
                   owner=[int(v) for v in p['owner']], bins=[list(b) for b in p['bins']], parts=p['parts'])
    return out


def app_view(p: Dict[str, Any]) -> Dict[str, Any]:
    out = {'use': p['use'], 'mode': p['mode'], 'why': p['why'], 'predicted': p['predicted']}
    if p['use']:
        out.update(jobs=p['jobs'], owner=p['owner'], bins=p['bins'], parts=p['parts'])
    return out


#: The options every model is planned under by both: off, on at several
#: core counts and one, and every branch of auto.
OPTIONS = [
    {'mode': 'off', 'workers': 4},
    {'mode': 'on', 'workers': 4},
    {'mode': 'on', 'workers': 3},
    {'mode': 'on', 'workers': 16},
    {'mode': 'on', 'workers': 1},
    {'mode': 'auto', 'workers': 4},
    {'mode': 'auto', 'workers': 8, 'known': {'solveMs': 200}},
    {'mode': 'auto', 'workers': 4, 'known': {'solveMs': 60000}, 'buildMs': 100},
    {'mode': 'auto', 'workers': 2, 'known': {'solveMs': 5000}, 'buildMs': 2000},
    {'mode': 'auto', 'workers': 4, 'known': {'solveMs': 60000, 'gain': 1.1}},
    {'mode': 'auto', 'workers': 4, 'known': {'solveMs': 900, 'gain': 2.1}},
    {'mode': 'nonsense', 'workers': 4, 'known': {'solveMs': 60000}, 'buildMs': 10},
]


# --- the plan, against the application's ------------------------------------------------------

class PartitionByHand(unittest.TestCase):
    def test_the_applications_cases(self) -> None:
        class P:
            def __init__(self, n: int, col_ptr: List[int], row_idx: List[int]) -> None:
                self.n, self.col_ptr, self.row_idx = n, col_ptr, row_idx

        three = state_partition(P(5, [0, 2, 4, 5, 7, 9], [0, 1, 0, 1, 2, 3, 4, 3, 4]))
        self.assertEqual(three['count'], 3)
        self.assertEqual(three['of'].tolist(), [0, 0, 1, 2, 2])
        self.assertEqual(three['sizes'].tolist(), [2, 1, 2])
        self.assertEqual(three['largest'], 2)
        # One direction is enough to join two states.
        one_way = state_partition(P(4, [0, 1, 2, 3, 4], [3, 1, 2, 3]))
        self.assertEqual(one_way['count'], 3)
        self.assertEqual(one_way['of'][0], one_way['of'][3])
        # Numbered by first appearance, whatever the components' own order.
        late = state_partition(P(4, [0, 1, 2, 3, 4], [2, 3, 0, 1]))
        self.assertEqual(late['of'].tolist(), [0, 1, 0, 1])
        self.assertEqual(state_partition(P(0, [0], []))['count'], 0)


@needs_app
class PartitionParity(unittest.TestCase):
    def check(self, name: str, model: Dict[str, Any]) -> None:
        theirs = engine('partition', model=model)
        self.assertNotIn('error', theirs, theirs.get('stack'))
        mine = partition_of(build_system(Project(copy.deepcopy(model))))
        got = {'ok': mine['ok'], 'refusal': mine['refusal'], 'count': mine['count'],
               'of': None if mine['of'] is None else mine['of'].tolist(),
               'sizes': None if mine['sizes'] is None else mine['sizes'].tolist(), 'largest': mine['largest']}
        self.assertEqual(got, theirs, name)

    def test_every_bundled_example(self) -> None:
        for name in EXAMPLES:
            with self.subTest(name):
                self.check(name, example(name))

    def test_made_up_models(self) -> None:
        models = {'chains': chains(3, 4, 3), 'two': two(), 'recording': RECORDING, 'across': ACROSS,
                  'pinned': PINNED, **REFUSED}
        for name, model in models.items():
            with self.subTest(name):
                self.check(name, model)


@needs_app
class PlanParity(unittest.TestCase):
    """The jobs, the state names and every plan -- its bins included, packed
    by states as the application packs them -- with the application's
    constants put in for auto: its structure is the application's, its numbers
    this engine's own.

    Except where a plan weighs a whole solve that has been timed against what
    a split costs. The application takes a bin to cost half a whole build
    whatever it holds, its generated code not shrinking with the part; here a
    build is taken to shrink with the part (a twelfth of a 10,080-state model
    built in 0.18 of the whole's time, half of it in 0.46) until a split of
    the model has measured it. Such a plan is held to this engine's own
    formula (``OwnConstants``); against the application's it is compared in
    everything but the weighing."""

    def check(self, name: str, model: Dict[str, Any]) -> None:
        theirs = engine('plan', model=model, opts=OPTIONS)
        self.assertNotIn('error', theirs, theirs.get('stack'))
        project = Project(copy.deepcopy(model))
        system = build_system(project)
        if system.layout.nstate:
            self.assertEqual(S.state_keys(system.layout), theirs['keys'], f'{name}: the names states are filed by')
            self.assertEqual(S.state_materials(system.layout), theirs['materials'], f'{name}: the materials')
        jobs = S.split_jobs(system)
        if theirs['jobs']['ok']:
            self.assertTrue(jobs['ok'], f"{name}: {jobs.get('why')}")
            self.assertEqual([{'materials': j['materials'], 'states': j['states']} for j in jobs['jobs']],
                             theirs['jobs']['jobs'], name)
            self.assertEqual(jobs['owner'].tolist(), theirs['jobs']['owner'], name)
            self.assertEqual(jobs['parts'], theirs['jobs']['parts'], name)
        else:
            self.assertEqual(jobs.get('why'), theirs['jobs']['why'], name)
        app = theirs['constants']
        with mock.patch.multiple(S, SHARED_WORK=app['SHARED_WORK'], START_MS=app['START_MS'],
                                 AUTO_SOLVE_MS=app['AUTO_SOLVE_MS'], AUTO_STATES=app['AUTO_STATES'],
                                 AUTO_GAIN=app['AUTO_GAIN'], AUTO_GAIN_UNTIMED=app['AUTO_GAIN_UNTIMED']):
            for o, p in zip(OPTIONS, theirs['plans']):
                mine = plan_view(S.plan_split(system, project, **python_opts(o)))
                app = app_view(p)
                known = o.get('known') or {}
                if p['predicted'] is not None and known.get('gain') is None and known.get('solveMs') is not None:
                    # A timed solve weighed against a split, each engine by its
                    # own build costs: the same model and the same question,
                    # and the answer may differ. The bins do not.
                    self.assertIsNotNone(mine['predicted'], f'{name} {o}')
                    self.assertEqual((mine['mode'], mine['why'].split(';')[0]), (app['mode'], app['why'].split(';')[0]),
                                     f'{name} {o}')
                    if app['use'] and mine['use']:
                        self.assertEqual(mine['bins'], app['bins'], f'{name} {o}')
                    continue
                self.assertEqual(mine, app, f'{name} {o}')
                if app['use']:
                    # What each process is given: the bin's jobs' materials
                    # together, and the states it files.
                    binned = S.bin_jobs(S.plan_split(system, project, **python_opts(o)))
                    self.assertEqual({'jobs': binned['jobs'], 'owner': binned['owner'].tolist()}, p['binned'],
                                     f'{name} {o}')

    def test_every_bundled_example(self) -> None:
        for name in EXAMPLES:
            with self.subTest(name):
                self.check(name, example(name))

    def test_made_up_models(self) -> None:
        models = {'chains': chains(5, 3, 4), 'big chains': chains(12, 4, 45), 'two': two(), 'recording': RECORDING,
                  'pinned': PINNED, **REFUSED}
        for name, model in models.items():
            with self.subTest(name):
                self.check(name, model)

    def test_every_refusal_in_the_applications_words(self) -> None:
        """Each reason the application gives, given here in its words."""
        cases = [(example('biosphere'), {'mode': 'off', 'workers': 4}, 'switched off'),
                 (REFUSED['nothing to integrate'], {'mode': 'on', 'workers': 4}, 'nothing to integrate'),
                 (example('farfield'), {'mode': 'on', 'workers': 4}, 'solver’s own steps'),
                 (REFUSED['no analytic Jacobian'], {'mode': 'on', 'workers': 4}, 'no analytic Jacobian'),
                 (example('recorders'), {'mode': 'on', 'workers': 4}, 'is a snapshot'),
                 (REFUSED['a delay'], {'mode': 'on', 'workers': 4}, 'is a delay'),
                 (REFUSED['a trigger'], {'mode': 'on', 'workers': 4}, 'is a trigger'),
                 (example('scenarios'), {'mode': 'on', 'workers': 4}, 'no materials'),
                 (example('decay-chain'), {'mode': 'on', 'workers': 4}, 'is one part'),
                 (REFUSED['one material in two parts'], {'mode': 'on', 'workers': 4}, 'builds as one job'),
                 (example('biosphere'), {'mode': 'on', 'workers': 1}, 'one core')]
        for model, o, words in cases:
            with self.subTest(words):
                theirs = engine('plan', model=model, opts=[o])['plans'][0]
                project = Project(copy.deepcopy(model))
                mine = S.plan_split(build_system(project), project, **python_opts(o))
                self.assertFalse(theirs['use'])
                self.assertIn(words, theirs['why'])
                self.assertFalse(mine['use'])
                self.assertEqual(mine['why'], theirs['why'])

    def test_where_this_engine_differs(self) -> None:
        """SciPy is split here, where the application's workers would each
        download it; and the words for a run in a worker are this engine's."""
        model = example('biosphere')
        model['simulation'] = {**model['simulation'], 'solver': 'scipy_bdf'}
        theirs = engine('plan', model=model, opts=[{'mode': 'on', 'workers': 4, 'scipy': True},
                                                   {'mode': 'on', 'workers': 4, 'nest': False}])['plans']
        self.assertIn('Python runtime', theirs[0]['why'])
        self.assertIn('worker from a worker', theirs[1]['why'])
        project = Project(model)
        system = build_system(project)
        self.assertTrue(S.plan_split(system, project, mode='on', workers=4)['use'])
        nested = S.plan_split(system, project, mode='on', workers=4, nest=False)
        self.assertEqual(nested['why'], 'this run is itself in a worker process, which does not start more')


class OwnConstants(unittest.TestCase):
    """This engine's own numbers for auto: the application's structure, with
    a start measured in processes rather than threads."""

    def setUp(self) -> None:
        self.bio = Project(example('biosphere'))
        self.system = build_system(self.bio)

    def plan(self, **opts: Any) -> Dict[str, Any]:
        return S.plan_split(self.system, self.bio, **{'mode': 'auto', 'workers': 8, **opts})

    def test_structure(self) -> None:
        self.assertEqual(S.job_cost(25, 100), S.SHARED_WORK + (1 - S.SHARED_WORK) * 0.25)
        self.assertEqual(S.pack_jobs([5, 3, 3, 2, 1], 2), [[0, 3], [1, 2, 4]])
        # The prediction is the application's formula with this engine's start.
        p = self.plan(known={'solve_ms': 40000.0}, build_ms=500.0)
        load = S.SHARED_WORK + (1 - S.SHARED_WORK) * 0.25
        self.assertEqual(p['predicted'], 40000.0 / (load * 40500.0 + S.START_MS))
        self.assertTrue(p['use'], p['why'])

    def test_decisions(self) -> None:
        small = self.plan()
        self.assertFalse(small['use'])
        self.assertEqual(small['why'], '16 states, too few to be worth dividing before a run has been timed')
        short = self.plan(known={'solve_ms': S.AUTO_SOLVE_MS - 1})
        self.assertFalse(short['use'])
        self.assertIn('too short to be worth dividing', short['why'])
        # Long enough, but the start eats the gain on two cores.
        two_cores = self.plan(workers=2, known={'solve_ms': 1600.0}, build_ms=100.0)
        self.assertFalse(two_cores['use'], two_cores['why'])
        self.assertRegex(two_cores['why'], r'expected \d\.\d× on 2 cores, not enough')
        # A measured split decides, either way.
        self.assertTrue(self.plan(known={'solve_ms': 10.0, 'gain': 1.3})['use'])
        self.assertFalse(self.plan(known={'solve_ms': 1e6, 'gain': 1.1})['use'])

    def test_a_measured_build_that_does_not_shrink(self) -> None:
        # A split measured parts that each cost a whole build: the same
        # solve, weighed with that, is not worth dividing.
        S_ms, B_ms = 4000.0, 3000.0
        shrinking = self.plan(known={'solve_ms': S_ms}, build_ms=B_ms)
        self.assertTrue(shrinking['use'], shrinking['why'])
        whole_builds = self.plan(known={'solve_ms': S_ms, 'build_fixed': 1.0}, build_ms=B_ms)
        self.assertFalse(whole_builds['use'], whole_builds['why'])
        self.assertIn('not enough', whole_builds['why'])
        # The learned share at the default is the default's prediction, to rounding.
        same = self.plan(known={'solve_ms': S_ms, 'build_fixed': S.SHARED_WORK}, build_ms=B_ms)
        self.assertAlmostEqual(same['predicted'], shrinking['predicted'], places=12)

    def test_the_bins_and_their_weight(self) -> None:
        """Packed by states, as the application packs them, and a bin of two
        parts weighed as one build: the work every part repeats paid once."""
        project = Project(chains(12, 4, 6))
        system = build_system(project)
        n = system.layout.nstate
        p = S.plan_split(system, project, mode='on', workers=8)
        sizes = [j['states'] for j in p['jobs']]
        self.assertEqual(len(sizes), 12)
        self.assertEqual(p['bins'], S.pack_jobs(sizes, 8))
        heaviest = max(sum(sizes[j] for j in b) for b in p['bins'])
        self.assertEqual(heaviest, 2 * sizes[0])
        timed = S.plan_split(system, project, mode='auto', workers=8, known={'solve_ms': 40000.0}, build_ms=500.0)
        self.assertEqual(timed['predicted'], 40000.0 / (S.job_cost(heaviest, n) * 40500.0 + S.START_MS))
        measured = S.plan_split(system, project, mode='auto', workers=8,
                                known={'solve_ms': 40000.0, 'build_fixed': 0.8}, build_ms=500.0)
        bin_ms = 500.0 * (0.8 + 0.2 * heaviest / n) + 40000.0 * S.job_cost(heaviest, n)
        self.assertAlmostEqual(measured['predicted'], 40000.0 / (bin_ms + S.START_MS), places=12)

    def test_the_jobs_a_process_is_given(self) -> None:
        plan = {'jobs': [{'materials': ['A'], 'states': 3}, {'materials': ['B', 'C'], 'states': 5},
                         {'materials': ['D'], 'states': 2}],
                'bins': [[1], [0, 2]], 'owner': np.array([0, 0, 0, 1, 1, 1, 1, 1, 2, 2]),
                'recorders': [('min_max:Peak[D]', 2, 7), ('running_mean:Mean[B]', 1, 3)]}
        got = S.bin_jobs(plan)
        self.assertEqual(got['jobs'], [{'materials': ['B', 'C'], 'states': 5}, {'materials': ['A', 'D'], 'states': 5}])
        self.assertEqual(got['owner'].tolist(), [1, 1, 1, 0, 0, 0, 0, 0, 1, 1])
        self.assertEqual(got['recorders'], [('min_max:Peak[D]', 1, 7), ('running_mean:Mean[B]', 0, 3)])

    def test_the_whole_solve_estimated_from_the_bins(self) -> None:
        # Bins that cost what their states say: the two estimates agree.
        even = [{'states': 50, 'nsteps': 1000}, {'states': 50, 'nsteps': 1000}]
        self.assertAlmostEqual(S.whole_solve_ms(even, [1000.0, 1000.0], 100), 1000.0 / S.job_cost(50, 100))
        # A small bin that costs the most per state -- nuclides decaying into
        # each other -- stretched by its states overstates the whole; its
        # cost per step summed with the other's, over the most steps either
        # took, is the estimate.
        uneven = [{'states': 10, 'nsteps': 1000}, {'states': 90, 'nsteps': 800}]
        summed = (900.0 / 1000 + 300.0 / 800) / (2 * S.SHARED_WORK + 1 - S.SHARED_WORK) * 1000
        self.assertLess(summed, 900.0 / S.job_cost(10, 100))
        self.assertAlmostEqual(S.whole_solve_ms(uneven, [900.0, 300.0], 100), summed)
        # A small bin that took a tenth of the steps and repeats more than the
        # shared work at each: summed over the most steps, it would overstate
        # the whole, and the stretched is the smaller.
        apart = [{'states': 10, 'nsteps': 100}, {'states': 90, 'nsteps': 1000}]
        self.assertAlmostEqual(S.whole_solve_ms(apart, [100.0, 1000.0], 100), 1000.0 / S.job_cost(90, 100))
        # A bin that did not say how many steps it took: the stretched alone.
        unsaid = [{'states': 10, 'nsteps': None}, {'states': 90, 'nsteps': 800}]
        self.assertEqual(S.whole_solve_ms(unsaid, [900.0, 300.0], 100), 900.0 / S.job_cost(10, 100))

    def test_the_build_share_measured(self) -> None:
        jobs = [{'states': 10, 'buildMs': 550.0}, {'states': 30, 'buildMs': 650.0}]
        # Each part paid a whole build (500 ms) and a tenth more.
        f = S.build_fixed(jobs, 100, 500.0)
        self.assertAlmostEqual(f, ((1.1 - 0.1) / 0.9 + (1.3 - 0.3) / 0.7) / 2)
        self.assertEqual(S.build_fixed(jobs, 100, 0.0), None)
        self.assertEqual(S.build_fixed([{'states': 100, 'buildMs': 1.0}], 100, 1.0), None)
        self.assertEqual(S.build_fixed([{'states': 10, 'buildMs': 1e9}], 100, 1.0), 2.0)

    def test_untimed_needs_a_large_model_of_many_parts(self) -> None:
        big = chains(12, 4, 210)                       # 10,080 states, twelve parts
        project = Project(big)
        system = build_system(project)
        self.assertGreaterEqual(system.layout.nstate, S.AUTO_STATES)
        p = S.plan_split(system, project, mode='auto', workers=8)
        self.assertTrue(p['use'], p['why'])
        self.assertIn('up to', p['why'])
        # Two parts, the largest half the model, promise too little.
        few = S.plan_split(system, project, mode='auto', workers=2)
        self.assertFalse(few['use'], few['why'])
        self.assertIn('not enough', few['why'])


# --- split runs -----------------------------------------------------------------------------

class SplitRuns(unittest.TestCase):
    """Runs through :func:`run`, as a script makes them."""

    def setUp(self) -> None:
        # Each test decides from a clean slate, not from what an earlier one timed.
        patcher = mock.patch.dict(S._MEMORY, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_examples_agree_with_the_whole(self) -> None:
        for name, parts in [('biosphere', 4), ('landscape', 3), ('waste-packages', 4)]:
            with self.subTest(name):
                model = example(name)
                whole = run(with_split(model, 'off'))
                parted = run(with_split(model, 'on'), workers=4)
                account = parted.stats['split']
                self.assertTrue(account['used'], account['why'])
                self.assertEqual(len(account['jobs']), parts)
                self.assertTrue(np.array_equal(np.asarray(parted.t), np.asarray(whole.t)))
                self.assertLess(worst(whole, parted), AGREE)
                self.assertGreater(parted.stats['nsteps'], 0)
                self.assertEqual(parted.stats['solver'], whole.stats['solver'])
                self.assertEqual(whole.stats['split'], {'used': False, 'mode': 'off', 'why': 'switched off',
                                                        'predicted': None})

    def test_the_account_and_the_log(self) -> None:
        parted = run(with_split(example('biosphere'), 'on'), workers=3)
        account = parted.stats['split']
        self.assertEqual(list(account), ['used', 'mode', 'why', 'predicted', 'parts', 'workers', 'jobs', 'wallMs',
                                         'gain'])
        self.assertEqual(account['why'], 'asked for: 4 parts, the largest 25% of the states, on 3 cores')
        self.assertEqual((account['used'], account['mode'], account['parts'], account['workers']), (True, 'on', 4, 3))
        self.assertIsNone(account['predicted'])
        # A line per process: four parts of four states on three cores, the
        # first core given two of them.
        self.assertEqual([j['materials'] for j in account['jobs']], [['I-129', 'Se-79'], ['Cl-36'], ['Tc-99']])
        self.assertEqual([j['states'] for j in account['jobs']], [8, 4, 4])
        for job in account['jobs']:
            self.assertEqual(list(job), ['materials', 'states', 'nsteps', 'buildMs', 'solveMs'])
            self.assertGreater(job['nsteps'], 0)
        self.assertGreater(account['wallMs'], 0)
        self.assertGreater(account['gain'], 0)
        self.assertEqual(parted.timing['solve_ms'], account['wallMs'])
        log = parted.run_log()
        self.assertIn('split: 4 independent parts on 3 cores (on) — asked for: 4 parts', log)
        self.assertIn('I-129, Se-79: 8 states,', log)

    def test_a_bin_is_one_build_and_the_same_run_wherever_it_goes(self) -> None:
        """Each process is given a bin: its parts' materials switched on
        together, built once and solved at the steps they need together. So
        the bins follow the number of processes, and so do the last digits;
        a bin's run is the run of that model, filed back as it came."""
        model = example('biosphere')
        project = with_split(model, 'on')
        two = run(project, workers=2)
        account = two.stats['split']
        self.assertEqual(account['workers'], 2)
        self.assertEqual([j['materials'] for j in account['jobs']], [['I-129', 'Tc-99'], ['Cl-36', 'Se-79']])
        again = run(with_split(model, 'on'), workers=2)
        self.assertTrue(np.array_equal(np.asarray(again.y), np.asarray(two.y)))
        self.assertEqual(again.stats['nsteps'], two.stats['nsteps'])
        # Each bin is a run of the model with its materials alone switched on.
        whole = build_system(project)
        work = S.bin_jobs(S.plan_split(whole, project, mode='on', workers=2))
        where = {key: i for i, key in enumerate(S.state_keys(whole.layout))}
        Y = np.asarray(two.y)
        for b, job in enumerate(account['jobs']):
            part_project, part_system, _ = S.build_part(S.part_model(project.to_json(), job['materials']))
            alone = run(part_project, system=part_system, on_grid=True)
            self.assertEqual(alone.stats['nsteps'], job['nsteps'])
            got = np.asarray(alone.y)
            filed = 0
            for k, key in enumerate(S.state_keys(part_system.layout)):
                i = where[key]
                if work['owner'][i] == b:
                    self.assertTrue(np.array_equal(Y[:, i], got[:, k]), key)
                    filed += 1
            self.assertEqual(filed, job['states'])
        # A process per part: each part at its own steps, which agree with
        # the bins' to the tolerance.
        four = run(with_split(model, 'on'), workers=4)
        self.assertEqual([j['materials'] for j in four.stats['split']['jobs']],
                         [['I-129'], ['Cl-36'], ['Tc-99'], ['Se-79']])
        self.assertLess(worst(two, four), AGREE)

    def test_made_up_chains(self) -> None:
        model = chains(6, 5, 4)
        whole = run(with_split(model, 'off'))
        parted = run(with_split(model, 'on'), workers=3)
        self.assertEqual(parted.stats['split']['parts'], 6)
        self.assertEqual(parted.stats['split']['workers'], 3)
        self.assertLess(worst(whole, parted), AGREE)

    def test_scipy_is_split_here(self) -> None:
        model = example('biosphere')
        model['simulation'] = {**model['simulation'], 'solver': 'scipy_bdf'}
        whole = run(with_split(model, 'off'))
        parted = run(with_split(model, 'on'), workers=4)
        self.assertTrue(parted.stats['split']['used'], parted.stats['split']['why'])
        self.assertLess(worst(whole, parted), AGREE)

    def test_a_min_max_and_a_running_mean_come_back(self) -> None:
        whole = run(with_split(RECORDING, 'off'))
        parted = run(with_split(RECORDING, 'on'), workers=2)
        self.assertTrue(parted.stats['split']['used'], parted.stats['split']['why'])
        # Every series, the remembered ones included: a peak is caught at the
        # steps each run takes, so it agrees to the tolerance as the states do.
        self.assertLess(worst(whole, parted), AGREE)
        # The peak is a peak, not the value at the end.
        peak = parted['PeakB [Cs-137]']
        self.assertGreater(peak[-1], parted['B [Cs-137]'][-1] * 1.5)

    def test_a_min_max_of_more_than_one_part_is_solved_whole(self) -> None:
        r = run(with_split(ACROSS, 'on'), workers=2)
        account = r.stats['split']
        self.assertFalse(account['used'])
        self.assertEqual(account['why'],
                         "'PeakTotal' remembers a value read from more than one part, so no part can give it back")
        whole = run(with_split(ACROSS, 'off'))
        self.assertTrue(np.array_equal(r['PeakTotal'], whole['PeakTotal']))

    def test_a_part_switches_on_what_it_names(self) -> None:
        whole = run(with_split(PINNED, 'off'))
        parted = run(with_split(PINNED, 'on'), workers=2)
        self.assertTrue(parted.stats['split']['used'], parted.stats['split']['why'])
        self.assertLess(worst(whole, parted), 1e-6)

    def test_the_compiled_setting_reaches_the_parts(self) -> None:
        model = example('biosphere')
        # Kept to Python: no part compiled, and none says why not, as a part
        # left at 'auto' would (compiled, or numba missing).
        python = run(with_split(model, 'on'), workers=2, compiled=False)
        self.assertTrue(python.stats['split']['used'], python.stats['split']['why'])
        self.assertIs(python.stats['compiled'], False)
        self.assertNotIn('compiled_why', python.stats)
        if not HAVE_NUMBA:
            return
        # Insisted on: every part compiled. One bin built and run here first,
        # so that the processes find its compiled model on disk rather than
        # all writing it at once.
        project = with_split(model, 'on')
        first = S.bin_jobs(S.plan_split(build_system(project), project, mode='on', workers=2))['jobs'][0]
        part_project, part_system, _ = S.build_part(S.part_model(project.to_json(), first['materials']))
        run(part_project, system=part_system, on_grid=True, compiled=True)
        fast = run(project, workers=2, compiled=True)
        self.assertTrue(fast.stats['split']['used'], fast.stats['split']['why'])
        self.assertIs(fast.stats['compiled'], True)
        self.assertTrue(np.array_equal(np.asarray(fast.y), np.asarray(python.y)))

    @unittest.skipUnless(HAVE_NUMBA, 'needs numba')
    def test_the_series_of_a_compiled_split_are_worked_out_compiled(self) -> None:
        """The whole model's system, on which every series is worked out, was
        never solved in this process: its compiled model is made when a series
        that is not a state is first asked for, and gives the Python passes'
        numbers to the last bit."""
        from kompartment.engine.compiled.model import CompiledModel
        parted = run(with_split(example('biosphere'), 'on'), workers=2, compiled=True)
        self.assertTrue(parted.stats['split']['used'], parted.stats['split']['why'])
        self.assertIs(parted.stats['compiled'], True)
        self.assertIsNone(getattr(parted.system, '_compiled_model', None))
        worked = [o for o in parted.outputs() if o['source'] == 'X']
        self.assertGreater(len(worked), 10)
        compiled = parted.series_many(worked)
        self.assertIsInstance(parted.system._compiled_model, CompiledModel)
        # The Python passes, as a run that was not compiled works them out.
        parted.system._compiled_model = 'kept to the Python passes for the test'
        python = parted.series_many(worked)
        for o, a, b in zip(worked, compiled, python):
            self.assertTrue(np.array_equal(a, b, equal_nan=True), o['label'])
        self.assertTrue(any(np.any(a != 0) for a in compiled))

    @unittest.skipUnless(HAVE_NUMBA, 'needs numba')
    def test_the_whole_model_is_compiled_beside_the_parts(self) -> None:
        """A compiled split starts compiling the whole model in a process of
        its own beside the parts, into the cache; the first series asked for
        waits for it and loads the model from there, compiling nothing."""
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'KOMPARTMENT_CACHE': d}):
            parted = run(with_split(chains(3, 3, 5), 'on'), workers=2, compiled=True)
            self.assertTrue(parted.stats['split']['used'], parted.stats['split']['why'])
            self.assertIs(parted.stats['compiled'], True)
            warming = parted.system._warming
            worked = [o for o in parted.outputs() if o['source'] == 'X']
            self.assertTrue(worked)
            parted.series_many(worked)
            self.assertIsNone(parted.system._warming)
            self.assertEqual(warming.exitcode, 0)
            module = parted.system._compiled_model.module
            for name in ('rhs', 'algebraic_rows'):
                stats = getattr(module, name).stats
                self.assertTrue(stats.cache_hits, name)
                self.assertFalse(stats.cache_misses, name)

    def test_progress_and_stop(self) -> None:
        heard: List[Any] = []
        model = example('biosphere')
        r = run(with_split(model, 'on'), workers=4, on_progress=lambda f, at: heard.append((f, at)))
        self.assertTrue(r.stats['split']['used'])
        self.assertTrue(heard)
        self.assertEqual(heard[-1], (1.0, float(model['simulation']['end_time'])))
        for (f0, t0), (f1, t1) in zip(heard, heard[1:]):
            self.assertLessEqual(f0, f1)
            self.assertLessEqual(t0, t1)
        # Stopped once it has begun: the parts stop and the run says so.
        began: List[float] = []
        long = with_split(model, 'on', end_time=model['simulation']['end_time'] * 1000)
        started = time.perf_counter()
        with self.assertRaises(SolverError) as caught:
            run(long, workers=4, on_progress=lambda f, at: began.append(f), signal=lambda: bool(began))
        self.assertEqual(caught.exception.code, 'aborted')
        self.assertLess(time.perf_counter() - started, 60)

    def test_a_script_needs_no_main_guard(self) -> None:
        """The processes load this package and nothing of the caller's: a
        script with no ``if __name__ == '__main__':`` guard is not run again
        in each of them, and one piped in, with no file to load, is split all
        the same."""
        with tempfile.TemporaryDirectory() as tmp:
            marker = os.path.join(tmp, 'ran')
            script = ('import sys\n'
                      f'sys.path.insert(0, {str(PACKAGE)!r})\n'
                      f'open({marker!r}, "a").write("top level\\n")\n'
                      'import kompartment as kp\n'
                      f'res = kp.run({str(EXAMPLES_DIR / "biosphere.json")!r}, split="on")\n'
                      'print(res.stats["split"]["used"], res.stats["split"].get("parts"))\n')
            path = os.path.join(tmp, 'unguarded.py')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(script)
            for how in ('a file', 'a pipe'):
                with self.subTest(how):
                    with open(marker, 'w', encoding='utf-8'):
                        pass
                    command = [sys.executable, path] if how == 'a file' else [sys.executable, '-']
                    proc = subprocess.run(command, input=None if how == 'a file' else script, capture_output=True,
                                          text=True, timeout=600)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(proc.stdout.split(), ['True', '4'], proc.stderr)
                    with open(marker, encoding='utf-8') as f:
                        self.assertEqual(f.read(), 'top level\n')

    def test_what_auto_learns_is_kept_for_the_next_process(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'split-memory.json')
            with mock.patch.object(S, 'memory_path', return_value=Path(path)), \
                    mock.patch.object(S, '_MEMORY_READ', [False]):
                run(Project(example('biosphere')))
                self.assertTrue(os.path.isfile(path))
                with open(path, encoding='utf-8') as f:
                    kept = json.load(f)
                self.assertEqual(len(kept), 1)
                key, entry = next(iter(kept.items()))
                self.assertIn('|compiled|' if HAVE_NUMBA else '|python|', key)
                self.assertGreater(entry['solve_ms'], 0)
                # A process that starts afresh reads it before it plans.
                S._MEMORY.clear()
                S._MEMORY_READ[0] = False
                again = run(Project(example('biosphere')))
                self.assertRegex(again.stats['split']['why'], r'^a whole solve takes \d+ ms, too short')
                # Kept apart by path: the Python path has not been timed.
                python = run(Project(example('biosphere')), compiled=False)
                if HAVE_NUMBA:
                    self.assertIn('before a run has been timed', python.stats['split']['why'])

    @unittest.skipUnless(HAVE_NUMBA, 'needs numba')
    def test_a_run_that_went_to_python_is_not_kept_as_compiled(self) -> None:
        """A run asked to compile whose model -- or one of whose parts -- went
        to the Python path measured neither path: auto keeps nothing of it."""
        from kompartment.engine.compiled import NotCompiled
        from kompartment.engine.compiled import run as compiled_run

        def refuse(*args: Any, **kwargs: Any) -> Any:
            raise NotCompiled('turned down for the test')

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'split-memory.json')
            with mock.patch.object(S, 'memory_path', return_value=Path(path)), \
                    mock.patch.object(S, '_MEMORY_READ', [False]), mock.patch.object(S, '_MEMORY', {}):
                with mock.patch.object(compiled_run, 'prepare', refuse):
                    r = run(Project(example('biosphere')))
                self.assertIs(r.stats['compiled'], False)
                self.assertEqual(r.stats['compiled_why'], 'turned down for the test')
                self.assertEqual(S._MEMORY, {})
                self.assertFalse(os.path.isfile(path))
                # Compiled, it is kept.
                run(Project(example('biosphere')))
                self.assertEqual([k.split('|')[-2] for k in S._MEMORY], ['compiled'])

        class Ran:
            stats: Dict[str, Any] = {}

        for ran, compiling, kept in ((True, True, True), (False, True, False), (False, False, True),
                                     (True, False, False), (None, True, True)):
            Ran.stats = {} if ran is None else {'compiled': ran}
            self.assertIs(S._ran_as(Ran, compiling), kept, (ran, compiling))

    def test_compiling_is_not_counted_as_solving(self) -> None:
        r = run(Project(example('biosphere')))
        self.assertGreaterEqual(r.compile_ms, 0.0)
        self.assertLessEqual(r.compile_ms, r.timing['solve_ms'])
        self.assertNotIn('compile_ms', r.timing)   # what a saved run carries is the application's

    def test_auto_is_the_default_and_learns(self) -> None:
        model = example('biosphere')
        first = run(Project(model))
        self.assertEqual(first.stats['split'], {
            'used': False, 'mode': 'auto', 'predicted': first.stats['split']['predicted'],
            'why': '16 states, too few to be worth dividing before a run has been timed'})
        again = run(Project(model))
        self.assertFalse(again.stats['split']['used'])
        self.assertRegex(again.stats['split']['why'], r'^a whole solve takes \d+ ms, too short to be worth dividing$')

    def test_not_split_in_a_worker_process_or_with_the_system_given(self) -> None:
        with mock.patch.object(S, '_in_worker_process', return_value=True):
            r = run(with_split(example('biosphere'), 'on'), workers=4)
        self.assertFalse(r.stats['split']['used'])
        self.assertEqual(r.stats['split']['why'], 'this run is itself in a worker process, which does not start more')
        project = with_split(example('biosphere'), 'on')
        self.assertNotIn('split', run(project, system=build_system(project)).stats)

    def test_a_split_that_does_not_add_up_is_solved_whole(self) -> None:
        def broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError('the parts came back on different output times')

        model = example('biosphere')
        with mock.patch.object(S, 'run_split', broken):
            r = run(with_split(model, 'on'), workers=4)
        self.assertFalse(r.stats['split']['used'])
        self.assertEqual(r.stats['split']['why'],
                         'tried, and solved whole instead: the parts came back on different output times')
        self.assertLess(worst(run(with_split(model, 'off')), r), 1e-12)


@unittest.skipUnless(os.environ.get('KOMPARTMENT_SPLIT_TIMING'), 'set KOMPARTMENT_SPLIT_TIMING=1 for the timing')
class Timing(unittest.TestCase):
    def test_independent_chains(self) -> None:
        model = chains(16, 12, 150, points=300, rtol=1e-8)
        started = time.perf_counter()
        whole = run(with_split(model, 'off'))
        whole_s = time.perf_counter() - started
        lines = [f"{len(model['nuclides'])} nuclides x {len(model['compartments'])} compartments = "
                 f"{whole.system.layout.nstate:,} states, {os.cpu_count()} cores",
                 f"  whole: {whole_s:.2f} s (build {whole.timing['build_ms']:.0f} ms, "
                 f"solve {whole.timing['solve_ms']:.0f} ms, {whole.stats['nsteps']} steps)"]
        ref = np.asarray(whole.y)
        for workers in (2, 4, 8, os.cpu_count() or 1):
            started = time.perf_counter()
            parted = run(with_split(model, 'on'), workers=workers)
            split_s = time.perf_counter() - started
            jobs = parted.stats['split']['jobs']
            # Every state, against the largest: the far end of the line holds
            # amounts at the absolute tolerance, which agree only to it.
            off = float(np.max(np.abs(np.asarray(parted.y) - ref)) / np.max(np.abs(ref)))
            lines.append(f"  split on {workers}: {split_s:.2f} s, {whole_s / split_s:.2f}x "
                         f"(solve wall {parted.stats['split']['wallMs']:.0f} ms; parts: build "
                         f"{min(j['buildMs'] for j in jobs):.0f}-{max(j['buildMs'] for j in jobs):.0f} ms, solve "
                         f"{min(j['solveMs'] for j in jobs):.0f}-{max(j['solveMs'] for j in jobs):.0f} ms, "
                         f"{min(j['nsteps'] for j in jobs)}-{max(j['nsteps'] for j in jobs)} steps; "
                         f"worst {off:.1e} of the peak)")
            self.assertLess(off, 1e-6)
        print('\n' + '\n'.join(lines))


if __name__ == '__main__':
    unittest.main()
