"""Reference texts for the Julia package's model loading, from the Python package.

For every model given -- the bundled examples, the made-up models below
(transport sub-systems, numbers written with a unit, files in older shapes),
and the Ecolego projects named with ``--eco`` -- this writes, under OUT_DIR:

* ``text/NAME.input.json``: the model as given (an Ecolego project as the
  importer hands it over, before anything is normalised);
* ``text/NAME.expected.json``: ``kp.Model.from_dict(raw).to_json()``, the text
  the Julia package's ``to_json(Model(raw))`` must equal byte for byte -- or
  ``text/NAME.error.txt`` when Python refuses the model;
* ``text/NAME.saved.json``: the file ``Model.save`` writes, stamped at
  ``SAVED_STAMP`` (``saved``, and ``created`` when the model has no date of
  its own);
* ``text/NAME.project.json``: the engine's ``Project`` of the settled model,
  as its ``to_json()`` writes it, and ``text/NAME.expanded.json`` the same
  of the project with its transports written out (``expand_transports``),
  for a model that has transports;
* ``text/NAME.source.txt``: for an Ecolego project, the file it came from;
* ``runnable/NAME.json``: the made-up models that are meant to be built and
  run, for ``tools/engine_fixtures.py`` and ``tools/run_fixtures.py``.

    python3 tools/model_fixtures.py OUT_DIR [--eco FILE ...] [model.json ...]

Run it with the repository's Python package on the path
(``PYTHONPATH=kompartment/python``). An Ecolego project is someone's model:
keep OUT_DIR outside the repository.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent.parent / 'examples'

#: The time ``NAME.saved.json`` is stamped with.
SAVED_STAMP = '2026-01-02T03:04:05.678Z'

#: How the transport chains of the application's tests are run.
CHAIN_SIM = {'start_time': 0, 'end_time': 30, 'output_points': 4, 'spacing': 'linear',
             'solver': 'dp45', 'rtol': 1e-10, 'abstol': 1e-14}


def column(path: str = 'Col') -> Dict[str, Any]:
    """The soil column of the application's transport tests: a chain of three
    with a counter, a pair-reading expression, a flow back up, an inflow, an
    outflow, and an operation of each kind."""
    return {
        'simulation': dict(CHAIN_SIM),
        'parameters': [{'name': 'k', 'value': 0.2}, {'name': 'kb', 'value': 0.05}],
        'transports': [path],
        'compartments': [
            {'name': 'Begin', 'system': path, 'transport': 'begin', 'initial': 'if(Counter == 1, 10, 0)'},
            {'name': 'End', 'system': path, 'transport': 'end', 'initial': '999'},
            {'name': 'Sink', 'initial': '0'},
        ],
        'expressions': [
            {'name': 'N', 'system': path, 'transport': 'number', 'equation': '3'},
            {'name': 'Counter', 'system': path, 'transport': 'counter'},
            {'name': 'Rate', 'system': path, 'equation': 'k * Counter'},
            {'name': 'Diff', 'system': path, 'equation': 'Begin - End'},
            {'name': 'Mid', 'system': path, 'transport': 'operation', 'operation': 'sum', 'argument': 'point'},
            {'name': 'Lower', 'system': path, 'transport': 'operation', 'operation': 'mean', 'argument': 'range'},
            {'name': 'Whole', 'system': path, 'transport': 'operation', 'operation': 'sum', 'argument': 'all'},
            {'name': 'AtHalf', 'equation': f'{path}.Mid(0.5)'},
            {'name': 'LowerMean', 'equation': f'{path}.Lower(0.5, 1)'},
        ],
        'transfers': [
            {'name': 'Down', 'system': path, 'from': f'{path}.Begin', 'to': f'{path}.End',
             'rate': 'Rate * (1 + 0 * Diff)'},
            {'name': 'Up', 'system': path, 'from': f'{path}.End', 'to': f'{path}.Begin', 'rate': 'kb'},
            {'name': 'Out', 'system': path, 'from': f'{path}.End', 'to': 'Sink', 'rate': 'k'},
        ],
        'inflows': [{'name': 'Feed', 'to': f'{path}.Begin', 'rate': '0.5'}],
    }


def with_number(m: Dict[str, Any], equation: str) -> Dict[str, Any]:
    m = copy.deepcopy(m)
    next(x for x in m['expressions'] if x.get('transport') == 'number')['equation'] = equation
    return m


def two_columns() -> Dict[str, Any]:
    """Two transports whose blocks read their own counter by the same bare name."""
    def part(path: str) -> Dict[str, Any]:
        return {
            'compartments': [
                {'name': 'Begin', 'system': path, 'transport': 'begin', 'initial': 'if(Counter == 1, 10, 0)'},
                {'name': 'End', 'system': path, 'transport': 'end', 'initial': '999'},
            ],
            'expressions': [
                {'name': 'N', 'system': path, 'transport': 'number', 'equation': '3'},
                {'name': 'Counter', 'system': path, 'transport': 'counter'},
                {'name': 'Rate', 'system': path, 'equation': 'k * Counter'},
            ],
            'transfers': [
                {'name': 'Down', 'system': path, 'from': f'{path}.Begin', 'to': f'{path}.End', 'rate': 'Rate'},
                {'name': 'Up', 'system': path, 'from': f'{path}.End', 'to': f'{path}.Begin', 'rate': 'kb'},
                {'name': 'Out', 'system': path, 'from': f'{path}.End', 'to': 'Sink', 'rate': 'k'},
            ],
        }
    a, b = part('Col'), part('Col2')
    return {
        'simulation': dict(CHAIN_SIM),
        'parameters': [{'name': 'k', 'value': 0.2}, {'name': 'kb', 'value': 0.05}],
        'transports': ['Col', 'Col2'],
        'compartments': [*a['compartments'], *b['compartments'], {'name': 'Sink', 'initial': '0'}],
        'expressions': [*a['expressions'], *b['expressions']],
        'transfers': [*a['transfers'], *b['transfers']],
        'inflows': [{'name': 'Feed', 'to': 'Col.Begin', 'rate': '0.5'},
                    {'name': 'Feed2', 'to': 'Col2.Begin', 'rate': '0.5'}],
    }


def transports() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    out['transport-column'] = column()
    out['transport-one'] = with_number(column(), '1.9')
    out['transport-param-number'] = with_number(column(), 'kb * 40 + 1')
    out['transport-erlang'] = {
        'simulation': {**CHAIN_SIM, 'end_time': 50, 'output_points': 6},
        'parameters': [{'name': 'k', 'value': 0.1}],
        'transports': ['Col'],
        'compartments': [
            {'name': 'Begin', 'system': 'Col', 'transport': 'begin', 'initial': 'if(i == 1, 1, 0)'},
            {'name': 'End', 'system': 'Col', 'transport': 'end', 'initial': '0'},
            {'name': 'Sink', 'initial': '0'},
        ],
        'expressions': [
            {'name': 'N', 'system': 'Col', 'transport': 'number', 'equation': '2 * 2'},
            {'name': 'i', 'system': 'Col', 'transport': 'counter'},
            {'name': 'Total', 'system': 'Col', 'transport': 'operation', 'operation': 'sum', 'argument': 'all'},
            {'name': 'Avg', 'system': 'Col', 'transport': 'operation', 'operation': 'mean', 'argument': 'all'},
        ],
        'transfers': [
            {'name': 'Down', 'system': 'Col', 'from': 'Col.Begin', 'to': 'Col.End', 'rate': 'k'},
            {'name': 'Out', 'system': 'Col', 'from': 'Col.End', 'to': 'Sink', 'rate': 'k'},
        ],
    }
    out['transport-decay'] = {
        'nuclides': ['Sr-90', 'Y-90'],
        'simulation': {**CHAIN_SIM, 'end_time': 10},
        'parameters': [{'name': 'k', 'value': 0.3}],
        'transports': ['Col'],
        'compartments': [
            {'name': 'Begin', 'system': 'Col', 'transport': 'begin', 'initial': 'if(i == 1, 1, 0)',
             'index_lists': ['Radionuclides']},
            {'name': 'End', 'system': 'Col', 'transport': 'end', 'initial': '0', 'index_lists': ['Radionuclides']},
        ],
        'expressions': [
            {'name': 'N', 'system': 'Col', 'transport': 'number', 'equation': '3', 'per_nuclide': False},
            {'name': 'i', 'system': 'Col', 'transport': 'counter', 'per_nuclide': False},
            {'name': 'Mean', 'system': 'Col', 'transport': 'operation', 'operation': 'mean', 'argument': 'all'},
        ],
        'transfers': [{'name': 'Down', 'system': 'Col', 'from': 'Col.Begin', 'to': 'Col.End', 'rate': 'k'}],
    }
    out['transport-two-columns'] = two_columns()
    # Per-index values and a dy/dt on the chain, a rate that reads a point of
    # it, and an entry that reads a stretch of it.
    out['transport-entries'] = {
        'nuclides': ['Cs-137', 'Sr-90'],
        'simulation': {**CHAIN_SIM, 'end_time': 20, 'solver': 'ndf', 'rtol': 1e-8, 'abstol': 1e-12},
        'parameters': [
            {'name': 'k', 'value': 0.2, 'per_nuclide': False},
            {'name': 'kd', 'value': 0.01, 'entries': [{'index': {'Radionuclides': 'Sr-90'}, 'value': 0.03}]},
        ],
        'transports': ['Soil'],
        'compartments': [
            {'name': 'Begin', 'system': 'Soil', 'transport': 'begin', 'initial': 'if(j == 1, 5, 0)',
             'entries': [{'index': {'Radionuclides': 'Sr-90'}, 'initial': 'if(j == 2, 7, 1)'}],
             'dydt': '-kd * Begin'},
            # Begin, read in End's own equations, is the last element itself (Python's
            # engine fails on End read there, where the application keeps the name).
            {'name': 'End', 'system': 'Soil', 'transport': 'end', 'initial': '0', 'dydt': '-kd * Begin',
             'entries': [{'index': {'Radionuclides': 'Cs-137'}, 'dydt': '-2 * kd * Begin'}]},
            {'name': 'Well', 'initial': '0'},
        ],
        'expressions': [
            {'name': 'N', 'system': 'Soil', 'transport': 'number', 'equation': 'n0 + 1', 'per_nuclide': False},
            {'name': 'n0', 'system': 'Soil', 'equation': '4', 'per_nuclide': False},
            {'name': 'j', 'system': 'Soil', 'transport': 'counter', 'per_nuclide': False},
            {'name': 'Speed', 'system': 'Soil', 'equation': 'k * (1 + j / 10)',
             'entries': [{'index': {'Radionuclides': 'Sr-90'}, 'equation': 'k * (1 + j / 5)'}]},
            {'name': 'Depth', 'system': 'Soil', 'transport': 'operation', 'operation': 'mean', 'argument': 'point'},
            {'name': 'Band', 'system': 'Soil', 'transport': 'operation', 'operation': 'sum', 'argument': 'range'},
            {'name': 'Probe', 'equation': 'Soil.Depth(0.3)',
             'entries': [{'index': {'Radionuclides': 'Sr-90'}, 'equation': 'Soil.Band(0.2, 0.9) / 2'}]},
        ],
        'transfers': [
            {'name': 'Down', 'system': 'Soil', 'from': 'Soil.Begin', 'to': 'Soil.End', 'rate': 'Speed'},
            {'name': 'Seep', 'system': 'Soil', 'from': 'Soil.End', 'to': 'Well', 'rate': '0.05 + 0 * Soil.Depth(1)'},
        ],
    }
    # Nothing says what the chain is indexed by: it takes what it is drawn
    # between, the scalar source and well here.
    out['transport-inherits'] = {
        'nuclides': ['Cs-137', 'Sr-90'],
        'simulation': {**CHAIN_SIM, 'solver': 'ndf', 'rtol': 1e-8, 'abstol': 1e-12},
        'parameters': [{'name': 'k', 'value': 0.2, 'per_nuclide': False}],
        'transports': ['Pipe'],
        'compartments': [
            {'name': 'Tank', 'initial': '100', 'index_lists': []},
            {'name': 'Begin', 'system': 'Pipe', 'transport': 'begin', 'initial': '0'},
            {'name': 'End', 'system': 'Pipe', 'transport': 'end', 'initial': '0'},
            {'name': 'Pond', 'initial': '0', 'index_lists': []},
        ],
        'expressions': [
            {'name': 'N', 'system': 'Pipe', 'transport': 'number', 'equation': '3', 'per_nuclide': False},
            {'name': 'Held', 'system': 'Pipe', 'transport': 'operation', 'operation': 'sum', 'argument': 'all'},
        ],
        'transfers': [
            {'name': 'Fill', 'from': 'Tank', 'to': 'Pipe.Begin', 'rate': 'k'},
            {'name': 'Flow', 'system': 'Pipe', 'from': 'Begin', 'to': 'End', 'rate': 'k'},
            {'name': 'Drain', 'from': 'Pipe.End', 'to': 'Pond', 'rate': 'k'},
        ],
    }
    off = column()
    for c in off['compartments']:
        if c.get('system') == 'Col':
            c['enabled'] = False
    for t in off['transfers']:
        if t.get('system') == 'Col':
            t['enabled'] = False
    for x in off['expressions']:
        if x.get('system') == 'Col' or x['name'] in ('AtHalf', 'LowerMean'):
            x['enabled'] = False
    off['inflows'][0]['enabled'] = False
    out['transport-switched-off'] = off
    half = column()
    for c in half['compartments']:
        if c['name'] in ('Begin', 'End'):
            c['enabled'] = False
    half['expressions'] = [x for x in half['expressions'] if x['name'] not in ('AtHalf', 'LowerMean')]
    for x in half['expressions']:
        if x.get('system') == 'Col' and not x.get('transport'):
            x['enabled'] = False
    half['expressions'].append({'name': 'ReadsN', 'equation': 'Col.N'})
    out['transport-error-half-off'] = half
    # What a transport refuses, and why.
    out['transport-error-number-reads-state'] = with_number(column(), 'Begin + 1')
    out['transport-error-below-one'] = with_number(column(), '0.5')
    two = column()
    two['compartments'].append({'name': 'Begin2', 'system': 'Col', 'transport': 'begin', 'initial': '0'})
    out['transport-error-two-begins'] = two
    args = column()
    next(x for x in args['expressions'] if x['name'] == 'AtHalf')['equation'] = 'Col.Mid(0.5, 0.7)'
    out['transport-error-arity'] = args
    unequal = column()
    unequal['index_lists'] = [{'name': 'Layer', 'indices': ['clay', 'sand']}]
    next(c for c in unequal['compartments'] if c['name'] == 'End')['index_lists'] = ['Layer']
    out['transport-error-unequal'] = unequal
    peek = two_columns()
    peek['expressions'].append({'name': 'Peek', 'system': 'Col2', 'equation': 'Col.Counter * 2'})
    out['transport-error-counter-outside'] = peek
    no_end = column()
    no_end['compartments'] = [c for c in no_end['compartments'] if c.get('transport') != 'end']
    out['transport-error-no-end'] = no_end
    return out


def units() -> Dict[str, Dict[str, Any]]:
    """Numbers written with a unit: scaled where they are added to, compared
    with or chosen against something whose unit is known."""
    out: Dict[str, Dict[str, Any]] = {}
    expressions = {
        'Lkm': 'L + 5[km]', 'Lsame': 'L + 0.01[m]', 'Lmm': 'L + 5[km] + 3[mm]', 'Lneg': '-5[km] + L',
        'Lsub': 'L - 250[cm]', 'Mg': 'M + 500[g]', 'Mmg': 'M + 2[mg]', 'Acm2': 'A + 2[cm2]',
        'Vlit': 'V + 1[L]', 'Vcm3': 'V + 10[cm^3]', 'Vdm': 'V + 7[dm3]', 'kd': 'k + 1[1/d]',
        'kpers': 'k + 1e-9[s-1]', 'kper': 'k + 2[per day]', 'cmg': 'c + 5[mg/m3]', 'cgL': 'c + 1[g/L]',
        'cmix': 'c + 3[g m-3]', 'Dcm': 'D + 1[cm^2/s]', 'Dyear': 'D + 1[m2/year]', 'T1': 'if(time > 30[d], 1, 0)',
        'T2': 'time() > 6[month] ? 1 : 0', 'T3': 'min(time, 100[d])', 'T4': 'max(L, 300[cm])',
        'T5': 'if(time >= 0.5, 2[km], L)', 'T6': 'time < 2[h] || time > 5[a]',
        'T7': '(L + 1[km]) * (M + 1[g])', 'T8': 'L + 5[ km ]', 'T9': 'L + 5[furlong]', 'T10': '1[km] + 1[m]',
        'T11': 'L + 1[m*m/m]', 'T12': 'L == 2000[mm] ? 1 : 0', 'T13': 'time + 1[year]',
        'T14': 'sqrt(A) + 10[cm]', 'T15': 'L^2 + 1[km^2]', 'T16': 'power(L, 2) + 3[dm2]',
        'T17': 'abs(L) + 1[km]', 'T18': 'mod(L, 3) + 1[cm]', 'T19': 'exp(1[km] / L)',
        'T20': 'L + 1[µm] + 1[μm] + 1[um]', 'T21': 'Lkm + 2[km]', 'T22': 'sum(L, 1[km])',
        'T23': 'hypot(L, 30[cm])', 'T24': 'L + 2[1/(m*s)]', 'T25': 'k + 3[1 per year]', 'T26': 'L + 1[ft]',
        'T27': 'time + 12[ month ]', 'T28': 'k * 2[d] + 1', 'T29': 'L + 1[m^(1/2) * m^(1/2)]',
        'T30': 'L + 1[(km)]', 'T31': 'A + 1[km·km]', 'T32': 'L != 1[km]', 'T33': 'L + 2[kmol]',
        'T34': 'M + 3[Mg] - 2[kg]', 'T35': 'L >= 1[km] && L <= 3[km]', 'T36': 'min(L, 2[km], 900[mm])',
        'T37': 'if(L > 1, 1[km], 2[km])', 'T38': 'L + 1e3[mm]', 'T39': 'L + .5[km]', 'T40': 'L + 1[]',
        'T41': 'L + 1[-]', 'T42': 'L + 1[unitless]', 'T43': 'L + 1[m3/m2]', 'T44': 'L + 1[m^-1 m^2]',
        'T45': 'L + 1[%]', 'T46': 'c + 1[kg per m3]', 'T47': 'c + 1[kg/(m*m*m)]', 'T48': 'L + 2[Tm] + 3[pm]',
    }
    out['units-literals'] = {
        'simulation': {'start_time': 0, 'end_time': 10, 'output_points': 5, 'spacing': 'linear', 'time_unit': 'year',
                       'solver': 'ndf', 'rtol': 1e-8, 'abstol': 1e-12},
        'parameters': [
            {'name': 'L', 'value': 2, 'unit': 'm'}, {'name': 'M', 'value': 3, 'unit': 'kg'},
            {'name': 'A', 'value': 1.5, 'unit': 'm2'}, {'name': 'V', 'value': 4, 'unit': 'm3'},
            {'name': 'k', 'value': 0.1, 'unit': '1/year'}, {'name': 'c', 'value': 1, 'unit': 'kg/m3'},
            {'name': 'D', 'value': 1e-3, 'unit': 'm^2/s'},
        ],
        'expressions': [{'name': n, 'equation': e} for n, e in expressions.items()],
        'compartments': [
            {'name': 'C', 'initial': '1[g] + M', 'unit': 'kg'},
            {'name': 'D2', 'initial': '0', 'unit': 'kg'},
        ],
        'transfers': [
            {'name': 'Move', 'from': 'C', 'to': 'D2', 'rate': 'k + 0.5[1/d]'},
            {'name': 'Leak', 'from': 'D2', 'rate': 'if(time < 2[year], k, k + 1[1/year])'},
        ],
    }
    for name in ('Lkm', 'Lmm', 'Mg', 'T5'):
        next(x for x in out['units-literals']['expressions'] if x['name'] == name)['unit'] = \
            'kg' if name == 'Mg' else 'm'
    out['units-seconds'] = {
        'simulation': {'start_time': 0, 'end_time': 3600, 'output_points': 5, 'spacing': 'linear',
                       'time_unit': 'second', 'solver': 'ndf', 'rtol': 1e-8, 'abstol': 1e-12},
        'parameters': [{'name': 'k', 'value': 1e-3, 'unit': '1/s'}, {'name': 'H', 'value': 10, 'unit': 'm'}],
        'expressions': [
            {'name': 'Late', 'equation': 'if(time > 2[ks], 1, 0)'},
            {'name': 'Soon', 'equation': 'time + 500[ms]', 'unit': 's'},
            {'name': 'Edge', 'equation': 'time >= 1.5[ks] ? 2[km] : H', 'unit': 'm'},
            {'name': 'Rate2', 'equation': 'k + 1[1/ks]', 'unit': '1/s'},
            {'name': 'Rate3', 'equation': 'k + 2[ms-1]', 'unit': '1/s'},
        ],
        'compartments': [{'name': 'Box', 'initial': '1', 'unit': 'kg'}],
        'transfers': [{'name': 'Out', 'from': 'Box', 'rate': 'k * Late + 1[1/ks] * (1 - Late) + 0 * Rate3'}],
    }
    out['units-in-systems'] = {
        'nuclides': ['Cs-137'],
        'simulation': {'start_time': 0, 'end_time': 100, 'output_points': 5, 'spacing': 'linear',
                       'solver': 'ndf', 'rtol': 1e-8, 'abstol': 1e-12},
        'systems': ['Lake'],
        'parameters': [
            {'name': 'depth', 'value': 4, 'unit': 'm', 'per_nuclide': False},
            {'name': 'depth', 'system': 'Lake', 'value': 7, 'unit': 'km', 'per_nuclide': False},
        ],
        'expressions': [
            {'name': 'Deeper', 'system': 'Lake', 'equation': 'depth + 300[m]', 'per_nuclide': False},
            {'name': 'Deeper', 'equation': 'depth + 300[cm]', 'per_nuclide': False},
            {'name': 'Both', 'equation': 'Lake.depth + 1[m]', 'per_nuclide': False},
        ],
        'compartments': [{'name': 'Water', 'system': 'Lake', 'initial': '1e6'}],
        'transfers': [{'name': 'Out', 'system': 'Lake', 'from': 'Water',
                       'rate': '0.01 * (Deeper - 3[km] + 1[mm]) / Deeper'}],
    }
    return out


def legacy() -> Dict[str, Dict[str, Any]]:
    """Files in the shapes older versions wrote."""
    out: Dict[str, Dict[str, Any]] = {}
    out['legacy-camel-case'] = {
        'nuclides': ['Cs-137'],
        'halfLives': {'Cs-137': 30.08},
        'simulation': {'startTime': 0, 'endTime': 10, 'outputPoints': 3, 'spacing': 'linear', 'timeUnit': 'year',
                       'solver': 'ode15s', 'rtol': 1e-10, 'abstol': 1e-14},
        'indexLists': [
            {'name': 'Radionuclides', 'forMaterials': True, 'indices': ['Cs-137']},
            {'name': 'Object', 'indices': ['Lake', 'Mire']},
            {'name': 'Wetland', 'subSetOf': 'Object', 'indices': ['Lake']},
        ],
        'parameters': [{'name': 'q', 'value': 2, 'valuesByNuclide': {'Cs-137': 5}}],
        'compartments': [
            {'name': 'A', 'initial': '1e6', 'handleDecay': False},
            {'name': 'B', 'initial': '0', 'handleDecay': False},
        ],
        'expressions': [{'name': 'E', 'equation': 'A[Cs-137]', 'perNuclide': False}],
        'transfers': [{'name': 'T', 'from': 'A', 'to': 'B', 'rate': 'q', 'multiplyByDonor': False}],
        'view': {'showParameters': True, 'showSinks': False, 'connectionLabel': 'rate'},
        'layout': {'A': {'x': 0, 'y': 0}, 'myBlock': {'x': 10, 'y': 20}},
    }
    out['legacy-maps-and-defaults'] = {
        'nuclides': ['Cs-137', 'Sr-90'],
        'simulation': {'start_time': 0, 'end_time': 10, 'output_points': 5, 'spacing': 'linear',
                       'rtol': 1e-10, 'abstol': 1e-16},
        'compartments': [
            {'name': 'A', 'initial': {'Cs-137': '100', 'Sr-90': 50}},
            {'name': 'B', 'initial': '0', 'default': '3'},
            {'name': 'Z', 'initial': {'Cs-137': 1.5}, 'per_nuclide': False},
        ],
        'parameters': [
            {'name': 'k', 'default': 0.01, 'values_by_nuclide': {'Cs-137': 0.2}},
            {'name': 'kk', 'value': 1, 'values_by_nuclide': {'Cs-137': 9, 'Sr-90': ''},
             'entries': [{'index': {'Radionuclides': 'Cs-137'}, 'value': 5}]},
            {'name': 'a', 'default': 7},
            {'name': 'flat', 'value': 4, 'values_by_nuclide': {'Cs-137': 1}, 'per_nuclide': False},
            {'name': 'empty_map', 'value': 4, 'values_by_nuclide': {}},
            {'name': 'texts', 'value': 1, 'values_by_nuclide': {'Cs-137': ' 2.5 ', 'Sr-90': 'nan'}},
        ],
        'expressions': [{'name': 'E', 'default': 'k * 2'}, {'name': 'F', 'equation': '1', 'default': '2'}],
        'lookups': [{'name': 'Q', 'default': [[0, 1], [10, 2]], 'per_nuclide': False}],
        'transfers': [{'name': 'T', 'from': 'A', 'to': 'B', 'rate': 'k', 'default': 'kk'}],
        'min_maxes': [{'name': 'Peak', 'target': 'B', 'default': 'ignored'}],
    }
    out['legacy-old-list-names'] = {
        'index_lists': [
            {'name': 'Materials', 'for_materials': True, 'indices': [{'name': 'Cs-137'}]},
            {'name': 'Radionuclides', 'for_nuclides': True, 'sub_set_of': 'Materials', 'indices': [{'name': 'Cs-137'}]},
        ],
        'compartments': [{'name': 'Soil', 'index_lists': ['Materials'], 'initial': '1',
                          'entries': [{'index': {'Materials': 'Cs-137'}, 'initial': '5'}]}],
        'sources': [{'name': 'Fallout', 'to': 'Soil', 'rate': '1'}],
        'discrete_events': [{'name': 'Half_way', 'first': 'time()', 'second': '50'}],
        'snapshots': [{'name': 'Kept', 'target': 'Soil', 'event': 'Half_way', 'initial': '-1'}],
        'min_maxes': [{'name': 'Peak', 'target': 'Soil', 'reset_event': 'Half_way', 'start_event': 'Half_way',
                       'stop_event': 'Half_way'}],
        'running_means': [{'name': 'Mean', 'target': 'Soil', 'start_event': 'Half_way'}],
        'index_operations': [{'name': 'Total', 'target': 'Soil', 'operation': 'sum'}],
        'aggregates': [{'name': 'Both', 'targets': ['Soil'], 'operation': 'max'}],
        'disruptions': [{'name': 'Quake', 'timing': 'at', 'at': '10'}],
    }
    out['legacy-nuclide-list'] = {
        'nuclides': ['I-129', 'Cs-135'],
        'index_lists': [{'name': 'Nuclide', 'for_contaminants': True, 'indices': ['I-129', 'Cs-135']},
                        {'name': 'Element', 'mapping': {'to': 'Nuclide', 'pairs': []}, 'indices': ['I', 'Cs']}],
        'compartments': [{'name': 'Soil', 'index_lists': ['Nuclide'], 'initial': '1'},
                         {'name': 'Well', 'initial': '0'}],
        'parameters': [{'name': 'Kd', 'index_lists': ['Element'], 'value': 0.1,
                        'entries': [{'index': {'Element': 'I'}, 'value': 0.001}]}],
        'transfers': [{'name': 'Leach', 'from': 'Soil', 'to': 'Well', 'rate': '1 / (1 + Kd)'}],
    }
    out['legacy-single-material-list'] = {
        'index_lists': [{'name': 'Isotopes', 'for_contaminants': True, 'indices': ['U-238', 'Th-234']},
                        {'name': 'Heavy', 'sub_set_of': 'Isotopes', 'indices': ['U-238']}],
        'compartments': [{'name': 'Rock', 'initial': '1'}, {'name': 'Water', 'initial': '0', 'unit': ''}],
        'transfers': [{'name': 'Dissolve', 'from': 'Rock', 'to': 'Water', 'rate': '1e-3'}],
    }
    out['legacy-no-materials'] = {
        'name': 'Chemistry',
        'simulation': {'end_time': 5, 'solver': 'ros23'},
        'compartments': [{'name': 'A', 'initial': '1', 'unit': 'mol'}, {'name': 'B', 'initial': '0'}],
        'transfers': [{'name': 'r', 'from': 'A', 'to': 'B', 'rate': '2'}],
        'inflows': [{'name': 'feed', 'to': 'A', 'rate': '0.1'}],
    }
    out['legacy-empty'] = {}
    out['legacy-nuclides-only'] = {'nuclides': ['Cs-137']}
    out['legacy-stale-dimensions'] = {
        'index_lists': [
            {'name': 'Contaminants', 'for_contaminants': True, 'indices': ['C-14', 'Cl-36']},
            {'name': 'Radionuclides', 'for_nuclides': True, 'sub_set_of': 'Contaminants', 'indices': ['C-14']},
            {'name': 'Object', 'indices': ['Lake', 'Mire']},
            {'name': 'Wet', 'sub_set_of': 'Object', 'indices': ['Lake']},
            {'name': 'Scenarios', 'for_scenarios': True, 'indices': ['Base', 'Wet']},
        ],
        'compartments': [
            {'name': 'A', 'initial': '1', 'index_lists': ['Object']},
            {'name': 'B', 'initial': '0', 'index_lists': ['Object']},
            {'name': 'C', 'initial': '0', 'index_lists': ['Radionuclides', 'Scenarios']},
            {'name': 'D', 'initial': '0', 'index_lists': ['Contaminants']},
            {'name': 'E', 'initial': '0', 'index_lists': ['Wet']},
        ],
        'transfers': [
            {'name': 'stale', 'from': 'A', 'to': 'B', 'rate': '1', 'index_lists': ['Radionuclides']},
            {'name': 'narrow', 'from': 'A', 'to': 'B', 'rate': '1', 'index_lists': ['Wet']},
            {'name': 'scen', 'from': 'C', 'to': 'D', 'rate': '1', 'index_lists': ['Contaminants'],
             'entries': [{'index': {'Contaminants': 'C-14'}, 'rate': '2'}]},
            {'name': 'out', 'from': 'D', 'rate': '1', 'index_lists': []},
            {'name': 'mixed', 'from': 'B', 'to': 'E', 'rate': '1'},
            {'name': 'nowhere', 'from': 'C', 'to': 'B', 'rate': '1'},
        ],
        'inflows': [{'name': 'in', 'to': 'C', 'rate': '1', 'index_lists': ['Object']},
                    {'name': 'in2', 'to': 'E', 'rate': '1'}],
    }
    out['legacy-units'] = {
        'decay_unit': 'mol',
        'index_lists': [
            {'name': 'Contaminants', 'for_contaminants': True,
             'indices': [{'name': 'Cs-137', 'enabled': True}, {'name': 'Fe', 'enabled': True, 'unit': 'kg'},
                         {'name': 'Ni', 'enabled': True, 'unit': 'kg'}, {'name': 'Pu-239', 'enabled': False}]},
            {'name': 'Radionuclides', 'for_nuclides': True, 'sub_set_of': 'Contaminants',
             'indices': [{'name': 'Cs-137', 'enabled': True}, {'name': 'Pu-239', 'enabled': False}]},
            {'name': 'Metals', 'sub_set_of': 'Contaminants', 'indices': ['Fe', 'Ni']},
            {'name': 'Mix', 'sub_set_of': 'Contaminants', 'indices': ['Fe', 'Cs-137']},
        ],
        'simulation': {'time_unit': 'day', 'end_time': 10},
        'compartments': [
            {'name': 'Rad', 'initial': '1', 'unit': ''},
            {'name': 'Metal', 'initial': '1', 'index_lists': ['Metals']},
            {'name': 'Both', 'initial': '1', 'index_lists': ['Mix']},
            {'name': 'Conc', 'initial': '1', 'unit': 'Bq/m3', 'index_lists': ['Radionuclides']},
            {'name': 'Plain', 'initial': '1', 'index_lists': []},
            {'name': 'Spaced', 'initial': '1', 'unit': 'mol per kg', 'index_lists': ['Radionuclides']},
        ],
        'transfers': [
            {'name': 'ByDonor', 'from': 'Rad', 'to': 'Conc', 'rate': '1'},
            {'name': 'Flux', 'from': 'Conc', 'to': 'Rad', 'rate': '1', 'multiply_by_donor': False, 'unit': 'Bq'},
            {'name': 'MetalFlux', 'from': 'Metal', 'rate': '1', 'multiply_by_donor': False},
            {'name': 'BothFlux', 'from': 'Both', 'rate': '1', 'multiply_by_donor': False},
            {'name': 'PlainFlux', 'from': 'Plain', 'rate': '1', 'multiply_by_donor': 'no'},
            {'name': 'SpacedFlux', 'from': 'Spaced', 'rate': '1', 'multiply_by_donor': False},
            {'name': 'Into', 'to': 'Conc', 'rate': '1', 'multiply_by_donor': False},
        ],
        'inflows': [{'name': 'Feed', 'to': 'Conc', 'rate': '1', 'unit': 'whatever'},
                    {'name': 'FeedPlain', 'to': 'Plain', 'rate': '1'},
                    {'name': 'FeedNowhere', 'rate': '1', 'unit': 'x'}],
        'farfields': [{'name': 'Path', 'unit': 'mol/day'}],
    }
    out['legacy-donor-copies'] = {
        'nuclides': ['Cs-137', 'Sr-90'],
        'compartments': [{'name': 'A', 'initial': '1'}, {'name': 'B', 'initial': '0'}],
        'transfers': [
            {'name': 'T', 'from': 'A', 'to': 'B', 'rate': '1', 'multiply_by_donor': True,
             'entries': [{'index': {'Radionuclides': 'Cs-137'}, 'multiply_by_donor': True},
                         {'index': {'Radionuclides': 'Sr-90'}, 'rate': '2', 'multiply_by_donor': True}]},
            {'name': 'F', 'from': 'B', 'to': 'A', 'rate': '1', 'multiply_by_donor': False,
             'entries': [{'index': {'Radionuclides': 'Cs-137'}, 'multiply_by_donor': False, 'rate': '3'}]},
        ],
    }
    out['legacy-systems-and-layout'] = {
        'nuclides': ['Cs-137'],
        'systems': ['Geo', {'name': 'Bio.Lake'}],
        'disabled_systems': ['Bio.Lake'],
        'compartments': [
            {'name': 'Water', 'system': 'Geo', 'initial': '1'},
            {'name': 'Rock', 'system': 'Geo', 'initial': '1'},
            {'name': 'Water', 'system': 'Bio.Lake', 'initial': '0'},
            {'name': 'Sea', 'initial': '0'},
        ],
        'transfers': [
            {'name': 'Seep', 'system': 'Geo', 'from': 'Rock', 'to': 'Water', 'rate': '1'},
            {'name': 'Up', 'system': 'Geo', 'from': 'Water', 'to': 'Bio.Lake.Water', 'rate': '1'},
            {'name': 'Out', 'system': 'Bio.Lake', 'from': 'Water', 'to': 'Sea', 'rate': '1'},
            {'name': 'Lost', 'from': 'Nowhere', 'to': 'Sea', 'rate': '1'},
        ],
        'inflows': [{'name': 'In', 'system': 'Geo', 'to': 'Rock', 'rate': '1'}],
        'layout': {
            'Geo': {'x': 0, 'y': 0}, 'Geo.Water': {'x': 1, 'y': 1}, 'Gone': {'x': 2, 'y': 2},
            'edge:Geo.Seep': {'points': []}, 'edge:Geo.Seep@Geo': {'points': []},
            'edge:Geo.Seep@Nope': {'points': []}, 'edge:Missing': {'points': []}, 'edge:Geo.Up@': {},
            'Bio': {'x': 3}, 'Bio.Lake': {'x': 4}, 'Bio.Lake.Water': {'x': 5},
        },
        'view': {},
        'chains': [],
    }
    out['legacy-header-order'] = {
        'simulation': {'end_time': 1},
        'saved': '2020-01-01T00:00:00.000Z',
        'created': 'not a date',
        'compartments': [{'name': 'A', 'initial': '1'}],
        'author': 'Someone',
        'description': 'Header keys out of order',
        'name': 'Header',
    }
    out['legacy-created-kept'] = {'name': 'Dated', 'created': '2025-03-04T05:06:07.890+02:00',
                                  'compartments': [{'name': 'A', 'initial': '1'}]}
    # One character between the time and the zone is let through by Python's reader.
    out['legacy-created-quirk'] = {'created': '2025-03-04T05:06:07x+00:00', 'name': 'Quirk',
                                   'compartments': [{'name': 'A', 'initial': '1'}]}
    out['legacy-created-not-a-date'] = {'created': 20250304, 'saved': 'yesterday',
                                        'compartments': [{'name': 'A', 'initial': '1'}]}
    out['legacy-transport-shapes'] = {
        'nuclides': ['Cs-137', 'Sr-90'],
        'index_lists': [{'name': 'Layer', 'indices': ['top', 'bottom']}],
        'transports': ['Col', {'name': 'Pipe'}, '', None],
        'compartments': [
            {'name': 'Begin', 'system': 'Col', 'transport': 'begin', 'initial': '1', 'index_lists': ['Layer'],
             'entries': [{'index': {'Radionuclides': 'Cs-137'}, 'initial': '2'}, {'index': {'Layer': 'top'}, 'initial': '3'}]},
            {'name': 'End', 'system': 'Col', 'transport': 'end', 'initial': '0'},
            {'name': 'Begin', 'system': 'Pipe', 'transport': 'begin', 'initial': '0'},
            {'name': 'End', 'system': 'Pipe', 'transport': 'end', 'initial': '0', 'index_lists': []},
            {'name': 'Src', 'initial': '1', 'index_lists': ['Radionuclides', 'Layer']},
            {'name': 'Dst', 'initial': '0', 'index_lists': ['Layer']},
        ],
        'expressions': [
            {'name': 'N', 'system': 'Col', 'transport': 'number', 'equation': '3', 'per_nuclide': False},
            {'name': 'Op', 'system': 'Col', 'transport': 'operation', 'operation': 'sum'},
            {'name': 'N', 'system': 'Pipe', 'transport': 'number', 'equation': '2', 'per_nuclide': False},
        ],
        'transfers': [
            {'name': 'In', 'from': 'Src', 'to': 'Col.Begin', 'rate': '1'},
            {'name': 'Flow', 'system': 'Col', 'from': 'Begin', 'to': 'End', 'rate': '1'},
            {'name': 'Out', 'from': 'Col.End', 'to': 'Dst', 'rate': '1'},
            {'name': 'Feed', 'from': 'Dst', 'to': 'Pipe.Begin', 'rate': '1'},
            {'name': 'Flow', 'system': 'Pipe', 'from': 'Begin', 'to': 'End', 'rate': '1'},
        ],
    }
    return out


def made_up() -> Dict[str, Dict[str, Any]]:
    return {**transports(), **units(), **legacy()}


#: The made-up models meant to be built and run (some to be refused while they are built).
def runnable(name: str) -> bool:
    return name.startswith(('transport-', 'units-')) or name in (
        'legacy-camel-case', 'legacy-maps-and-defaults', 'legacy-donor-copies', 'legacy-no-materials')


def dumps(value: Any) -> str:
    from kompartment.jsonio import dumps as kdumps
    return kdumps(value, 2)


def write(out: Path, name: str, raw: Dict[str, Any], source: str = '') -> str:
    import kompartment as kp
    text = out / 'text'
    text.mkdir(parents=True, exist_ok=True)
    (text / f'{name}.input.json').write_text(dumps(raw), encoding='utf-8')
    if source:
        (text / f'{name}.source.txt').write_text(source, encoding='utf-8')
    for stale in (text / f'{name}.expected.json', text / f'{name}.error.txt', text / f'{name}.saved.json',
                  text / f'{name}.project.json', text / f'{name}.expanded.json'):
        if stale.exists():
            stale.unlink()
    try:
        # From the text written, so that both sides start from the same JSON.
        expected = kp.Model.from_dict(json.loads(dumps(raw))).to_json()
    except Exception as e:  # noqa: BLE001 - the refusal is the fixture
        (text / f'{name}.error.txt').write_text(f'{type(e).__name__}: {e}', encoding='utf-8')
        return f'error: {type(e).__name__}: {e}'
    (text / f'{name}.expected.json').write_text(expected, encoding='utf-8')
    (text / f'{name}.saved.json').write_text(saved_text(raw), encoding='utf-8')
    write_projects(text, name, raw)
    return f'{len(expected)} characters'


def write_projects(text: Path, name: str, raw: Dict[str, Any]) -> None:
    """The engine's Project of the model, and of it with its transports
    written out, where the engine takes the model that far."""
    import kompartment as kp
    from kompartment.engine import Project
    from kompartment.engine.transport import expand_transports
    try:
        project = Project(kp.Model.from_dict(json.loads(dumps(raw))).to_dict())
    except Exception:  # noqa: BLE001 - a model the engine refuses has no Project to compare
        return
    (text / f'{name}.project.json').write_text(dumps(project.to_json()), encoding='utf-8')
    if not project.transports:
        return
    try:
        expanded = expand_transports(project)
    except Exception:  # noqa: BLE001 - the refusal is compared where the model is built
        return
    (text / f'{name}.expanded.json').write_text(dumps(expanded.to_json()), encoding='utf-8')


def saved_text(raw: Dict[str, Any]) -> str:
    """What ``Model.save`` writes for ``raw``, stamped at ``SAVED_STAMP``."""
    import kompartment as kp
    import kompartment.model as kmodel
    m = kp.Model.from_dict(json.loads(dumps(raw)))
    real = kmodel._stamp
    kmodel._stamp = lambda when=None: SAVED_STAMP
    try:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'model.json'
            m.save(path)
            return path.read_text(encoding='utf-8')
    finally:
        kmodel._stamp = real


def main() -> None:
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    out = Path(args[0])
    out.mkdir(parents=True, exist_ok=True)
    eco: List[Path] = []
    paths: List[Path] = []
    rest = args[1:]
    while rest:
        a = rest.pop(0)
        if a == '--eco':
            eco.append(Path(rest.pop(0)))
        else:
            paths.append(Path(a))
    if not paths and not eco:
        paths = sorted(EXAMPLES.glob('*.json'))
        models = made_up()
        run_dir = out / 'runnable'
        run_dir.mkdir(parents=True, exist_ok=True)
        for name, raw in models.items():
            print(name, write(out, name, raw))
            if runnable(name):
                (run_dir / f'{name}.json').write_text(dumps(raw), encoding='utf-8')
    for path in paths:
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
        print(path.name, write(out, path.stem, raw))
    if eco:
        from kompartment.importers.eco import import_eco_file
        for k, path in enumerate(eco):
            try:
                project, _report = import_eco_file(str(path))
            except Exception as e:  # noqa: BLE001 - a file the importer cannot read is skipped
                print(path, f'not imported: {type(e).__name__}: {e}')
                continue
            name = f'eco-{k:02d}-{path.stem}'
            print(name, write(out, name, project, str(path)))


if __name__ == '__main__':
    main()
