"""Split into parts: the plan against the application's, and split runs against whole ones.

* The partition of every bundled example, and of made-up models, is the
  application's (``partitionOf``), and so are the jobs, the names every state
  is filed back by, the plan (``planSplit``) and every refusal's words -- the
  automatic choice with the application's constants put in, since this
  engine's are its own.
* A split run agrees with the whole model's to within the tolerance, every
  series, and does not depend on how many processes take the parts.
* Where this engine does what the application does not -- a SciPy solver
  split, the histories of a min/max and a running mean carried back, a
  min/max that reads more than one part refused -- it is tested here too.

Set ``KOMPARTMENT_SPLIT_TIMING=1`` for a timing on a made-up model of
independent decay chains, whole against split.
"""

from __future__ import annotations

import copy
import importlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
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
    """The jobs, the state names and every plan, with the application's
    constants put in for auto: its structure is the application's, its numbers
    this engine's own."""

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
                self.assertEqual(mine, app_view(p), f'{name} {o}')

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
        self.assertEqual([j['materials'] for j in account['jobs']], [['I-129'], ['Cl-36'], ['Tc-99'], ['Se-79']])
        for job in account['jobs']:
            self.assertEqual(list(job), ['materials', 'states', 'nsteps', 'buildMs', 'solveMs'])
            self.assertGreater(job['nsteps'], 0)
        self.assertGreater(account['wallMs'], 0)
        self.assertGreater(account['gain'], 0)
        self.assertEqual(parted.timing['solve_ms'], account['wallMs'])
        log = parted.run_log()
        self.assertIn('split: 4 independent parts on 3 cores (on) — asked for: 4 parts', log)
        self.assertIn('I-129: 4 states,', log)

    def test_the_worker_count_changes_nothing(self) -> None:
        model = example('biosphere')
        runs = {w: run(with_split(model, 'on'), workers=w) for w in (2, 3, 4)}
        first = runs[2]
        for w, r in runs.items():
            self.assertEqual(r.stats['split']['workers'], w)
            self.assertTrue(np.array_equal(np.asarray(r.t), np.asarray(first.t)))
            self.assertTrue(np.array_equal(np.asarray(r.y), np.asarray(first.y)), f'{w} workers')
            self.assertEqual([j['nsteps'] for j in r.stats['split']['jobs']],
                             [j['nsteps'] for j in first.stats['split']['jobs']])
            self.assertEqual(r.stats['nsteps'], first.stats['nsteps'])

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
        try:
            import numba  # noqa: F401
        except ImportError:
            return
        # Insisted on: every part compiled. One part built and run here first,
        # so that the processes find its compiled model on disk rather than
        # all writing it at once.
        project = with_split(model, 'on')
        first = S.split_jobs(build_system(project))['jobs'][0]
        part_project, part_system, _ = S.build_part(S.part_model(project.to_json(), first['materials']))
        run(part_project, system=part_system, on_grid=True, compiled=True)
        fast = run(project, workers=2, compiled=True)
        self.assertTrue(fast.stats['split']['used'], fast.stats['split']['why'])
        self.assertIs(fast.stats['compiled'], True)
        self.assertTrue(np.array_equal(np.asarray(fast.y), np.asarray(python.y)))

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
                      'print(res.stats["split"]["used"], len(res.stats["split"].get("jobs", [])))\n')
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
