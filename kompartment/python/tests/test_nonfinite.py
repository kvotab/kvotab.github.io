"""A run that meets a value that is not a number says where it starts, in the
application's words (``engine/nonfinite.py``, ``src/sim/nonfinite.js``); the
warnings at the start of a run say the same before one; and the seeds of the
blocks that remember are worked out until they settle."""

from __future__ import annotations

import copy
import math
import re
import unittest
from typing import Any, Dict

from helpers import needs_app
from test_engine_lang import engine

from kompartment.engine.atstart import values_at_start
from kompartment.engine.project import Project
from kompartment.engine.runner import run
from kompartment.engine.solvers import SolverError

SIMULATION = {'start_time': 0, 'end_time': 10, 'output_points': 3, 'spacing': 'linear', 'solver': 'ndf',
              'rtol': 1e-6, 'abstol': 1e-9, 'time_unit': 'year'}

#: Packages that may crack: none have, and the concentration in them is 0/0.
CRACKED: Dict[str, Any] = {
    'name': 'cracked packages', 'nuclides': ['Cs-137', 'Sr-90'], 'simulation': SIMULATION,
    'index_lists': [{'name': 'Radionuclides', 'for_contaminants': True,
                     'indices': [{'name': 'Cs-137'}, {'name': 'Sr-90'}]}],
    'parameters': [{'name': 'N_cracked', 'value': 0}, {'name': 'V', 'value': 2}, {'name': 'limit', 'value': 100}],
    'compartments': [{'name': 'Waste', 'initial': '0', 'index_lists': ['Radionuclides']},
                     {'name': 'Wall', 'initial': '0', 'index_lists': ['Radionuclides']}],
    'expressions': [
        {'name': 'C_waste', 'equation': 'min(Waste/(V*N_cracked), limit)', 'index_lists': ['Radionuclides']},
        {'name': 'C_out', 'equation': 'Wall/(V*N_cracked)', 'index_lists': ['Radionuclides']},
    ],
    'transfers': [{'name': 'Diffusion', 'from': 'Waste', 'to': 'Wall', 'rate': 'N_cracked*C_waste',
                   'multiply_by_donor': False, 'index_lists': ['Radionuclides']}],
    'inflows': [],
}

#: What the engines say of it, word for word (test/run.js holds the same).
CRACKED_SAYS = ('The simulation produced a value that is not a number at t=0. It starts in C_waste '
                '[Radionuclides=Cs-137] (and 1 more of its indices): Waste/(V*N_cracked) comes to 0/0, with Waste = 0, '
                'V = 2 and N_cracked = 0. It reaches 2 compartments, 4 states in all: Waste and Wall, through the '
                'transfer Diffusion.')

STOPS = ('Comes to NaN at the start at Radionuclides=Cs-137 (and 1 more of its indices): Waste/(V*N_cracked) comes to '
         '0/0, with Waste = 0, V = 2 and N_cracked = 0. The run reads it, through the transfer Diffusion, so it will '
         'stop at its first step.')
GOES_ON = ('Comes to NaN at the start at Radionuclides=Cs-137 (and 1 more of its indices): Wall/(V*N_cracked) comes to '
           '0/0, with Wall = 0, V = 2 and N_cracked = 0. Only results read it, so a run goes on, with these values at '
           'its first point.')


def cracked(solver: str = 'ndf') -> Dict[str, Any]:
    m = copy.deepcopy(CRACKED)
    m['simulation']['solver'] = solver
    return m


def failure(model: Dict[str, Any], compiled: Any = False) -> SolverError:
    try:
        run(Project(model), compiled=compiled)
    except SolverError as e:
        return e
    raise AssertionError('the run went')


class WhereItStarts(unittest.TestCase):
    def test_every_solver_on_either_path_says_where_it_starts_and_what_it_reaches(self) -> None:
        for solver in ('ndf', 'ros23', 'dp45'):
            for compiled in (False, 'auto'):
                with self.subTest(solver=solver, compiled=compiled):
                    e = failure(cracked(solver), compiled)
                    self.assertEqual(str(e), CRACKED_SAYS)
                    self.assertEqual(e.block_name, 'C_waste')
                    self.assertNotEqual(e.solver_message, str(e))
                    self.assertIsNone(e.hint)

    @needs_app
    def test_the_application_says_it_in_the_same_words(self) -> None:
        for solver in ('ndf', 'ros23', 'dp45'):
            with self.subTest(solver=solver):
                theirs = engine('run', model=cracked(solver))
                self.assertEqual(theirs['error'], CRACKED_SAYS)
                self.assertEqual(theirs['block'], 'C_waste')

    def test_a_value_that_is_not_a_number_a_step_past_the_state_held_is_found_there(self) -> None:
        model = {
            'name': 'below zero',
            'simulation': {**SIMULATION, 'output_points': 20, 'non_negative': False},
            'compartments': [{'name': 'A', 'initial': '1', 'non_negative': False}, {'name': 'B', 'initial': '0'}],
            'expressions': [{'name': 'R', 'equation': 'sqrt(A)'}],
            'transfers': [{'name': 'Drain', 'from': 'A', 'to': 'B', 'rate': '0.5 + 0*R', 'multiply_by_donor': False},
                          {'name': 'Leak', 'from': 'B', 'to': None, 'rate': '0.01*R', 'multiply_by_donor': False}],
            'parameters': [], 'inflows': [],
        }
        said = re.compile(r'^The simulation produced a value that is not a number at t=([\d.e+-]+)\. The state it held '
                          r'there gives numbers; a step of [\d.e+-]+ past it does not\. It starts in R: sqrt\(A\) comes '
                          r'to sqrt\(-[\d.e+-]+\), with A = -[\d.e+-]+\. It reaches 2 compartments, 2 states in all: A '
                          r'and B, through the transfers Drain and Leak\.$')
        for solver in ('ndf', 'ros23', 'dp45'):
            with self.subTest(solver=solver):
                model['simulation']['solver'] = solver
                e = failure(model)
                m = said.match(str(e))
                self.assertIsNotNone(m, str(e))
                self.assertAlmostEqual(float(m.group(1)), 2.0, places=9)
                self.assertEqual(e.block_name, 'R')


#: Equations and what every engine writes them back as (test/run.js and the Julia tests hold the same).
WRITTEN_BACK = [
    ('a/(b*c)', 'a/(b*c)'), ('a-b-c', 'a - b - c'), ('a-(b-c)', 'a - (b - c)'), ('-a^2', '-a^2'),
    ('(-a)^2', '(-a)^2'), ('2^-3', '2^-3'), ('2^-3^2', '2^-3^2'), ('a^b^c', 'a^b^c'), ('a^(b^c)', 'a^(b^c)'),
    ('-(a*b)', '-(a*b)'), ('-a*b', '-a*b'), ('a*-b', 'a*-b'), ('min(a, b*c, -d)', 'min(a, b*c, -d)'),
    ('x>1 && y<2', 'x > 1 && y < 2'), ('(a || b) && c', '(a || b) && c'), ('a ? b : c ? d : e', 'a ? b : (c ? d : e)'),
    ('(a ? b : c) + 1', '(a ? b : c) + 1'), ('if(c, a+1, b)', 'if(c, a + 1, b)'), ('a*(b+c)/d', 'a*(b + c)/d'),
    ('1e-5*a', '0.00001*a'), ('0.01[m]*a', '0.01[m]*a'), ('Cs[Cs-137]*2', 'Cs[Cs-137]*2'),
    ('M[_Ra-226][Pb-210]', 'M[_Ra-226][Pb-210]'), ('M[][x]', 'M[][x]'), ('a == b', 'a == b'), ('a ~= b', 'a ~= b'),
    ('not(z)', 'not(z)'), ('exp(-(a+b)/c)', 'exp(-(a + b)/c)'), ('sqrt(a - b)^0.5', 'sqrt(a - b)^0.5'),
]


class WrittenBack(unittest.TestCase):
    def test_an_equation_is_written_back_as_the_parser_read_it_and_as_the_application_writes_it(self) -> None:
        from kompartment.engine.lang import parse
        from kompartment.engine.nonfinite import equation_text
        for eq, written in WRITTEN_BACK:
            with self.subTest(eq=eq):
                text = equation_text(parse(eq))
                self.assertEqual(text, written)
                self.assertEqual(repr(parse(text)), repr(parse(eq)))


class AtTheStart(unittest.TestCase):
    def test_the_warnings_at_the_start_say_which_values_are_not_numbers_and_which_stop_a_run(self) -> None:
        warnings = values_at_start(Project(cracked())).warnings
        self.assertEqual(warnings, [{'block': 'C_waste', 'stops': True, 'message': STOPS},
                                    {'block': 'C_out', 'stops': False, 'message': GOES_ON}])
        fixed = cracked()
        fixed['parameters'][0]['value'] = 1
        self.assertEqual(values_at_start(Project(fixed)).warnings, [])
        bad = cracked()
        bad['compartments'][0]['initial'] = '0/N_cracked'
        self.assertEqual(values_at_start(Project(bad)).warnings, [{
            'block': 'Waste', 'stops': True,
            'message': 'Its initial value comes to NaN at Radionuclides=Cs-137 (and 1 more of its indices), so a run '
                       'cannot start.'}])

    @needs_app
    def test_the_application_warns_in_the_same_words(self) -> None:
        theirs = engine('atstart', model=cracked(), names=[])
        self.assertEqual(theirs['warnings'], values_at_start(Project(cracked())).warnings)

    def test_a_peak_read_through_a_delay_starts_at_its_target(self) -> None:
        # The seeds were worked out in one pass, before any block that remembers
        # had a history: the delayed volume read 0, the dose divided by it, and
        # the peak kept what that made for the whole run.
        model = {
            'name': 'peak through a delay', 'simulation': SIMULATION,
            'lookups': [{'name': 'V', 'points': [[0, 2], [10, 2]]}],
            'delays': [{'name': 'V_delay', 'target': 'V', 'delay': '0.001'}],
            'compartments': [{'name': 'A', 'initial': '1'}],
            'transfers': [{'name': 'Out', 'from': 'A', 'to': None, 'rate': '0.1'}],
            'expressions': [{'name': 'Dose', 'equation': 'A/V_delay'}],
            'min_maxes': [{'name': 'Peak', 'operation': 'max', 'target': 'Dose'}],
            'parameters': [], 'inflows': [],
        }
        for compiled in (False, 'auto'):
            with self.subTest(compiled=compiled):
                res = run(Project(model), compiled=compiled)
                peak, dose = res['Peak'], res['Dose']
                self.assertTrue(all(math.isfinite(v) for v in peak), list(peak))
                self.assertAlmostEqual(peak[0], 0.5, places=12)
                self.assertAlmostEqual(peak[0], dose[0], places=12)
        self.assertEqual(values_at_start(Project(model)).warnings, [])


if __name__ == '__main__':
    unittest.main()
