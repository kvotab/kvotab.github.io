#!/usr/bin/env python3
"""Fixtures for the Julia package's editing API: the Python package's edits, replayed.

    python3 tools/edit_fixtures.py OUTDIR

Writes one ``CASE.json`` per case into OUTDIR (a scratch directory outside the
repository). A case is a starting model -- made up here, or one of the bundled
examples in kompartment/examples -- and a list of operations, each a method of
the Python package's API with its arguments: on the model, on a block, an index
list, the simulation settings, the view, a shape, an output series, or a
function of ``kompartment.distributions``; or a property read or set. Each is
applied in order with the Python package (kompartment/python), and recorded
after it is:

* ``json``  -- the model's ``to_json()`` text, or null when it is the text
  recorded last;
* ``error`` -- the class and message of what the package raised, or null;
* ``result`` -- what the call returned, as ``dumps`` writes it (blocks, lists
  and shapes by name), or null for a property set.

Arguments are recorded the way the Julia package takes them: Python's
positional-or-keyword parameters positionally (in order, defaults filled in
up to the last one given), keyword-only ones as keywords. A few values have
an encoding of their own: ``{"$float": "inf"}``, ``{"$tuple": [...]}``,
``{"$block": name}`` (the block of that name, looked up when the operation
runs) and ``{"$dist": [function, args, kwargs]}`` (a distribution made by
that function when the operation runs).

test/model/edit.jl replays every case through the Julia API and compares the
texts byte for byte, the refusals by class and message, and the results:

    KOMPARTMENT_EDIT_FIXTURES=OUTDIR julia --project=. test/model/edit.jl

The last cases are edits drawn at random (seeded, so the same every time):
KOMPARTMENT_EDIT_FUZZ sets how many sequences of them there are (40).
"""

from __future__ import annotations

import datetime as _dt
import inspect
import json
import math
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
KOMPARTMENT = HERE.parents[2]
sys.path.insert(0, str(KOMPARTMENT / 'python'))

import kompartment as kp  # noqa: E402
from kompartment import distributions as dist  # noqa: E402
from kompartment.jsonio import dumps  # noqa: E402
from kompartment.model import IndexList, Shape, View  # noqa: E402
from kompartment.simulation import OutputSeries, Simulation  # noqa: E402

EXAMPLES = KOMPARTMENT / 'examples'
STAMP = '2026-01-02T03:04:05.678Z'
INF = float('inf')


# --- values that are made when an operation runs ---------------------------------------------------

class Dist:
    """A distribution, made by a function of kompartment.distributions as the operation runs."""

    def __init__(self, fn, *args, **kwargs):
        self.fn, self.args, self.kwargs = fn, args, kwargs


class Ref:
    """A block of the model, looked up by name as the operation runs."""

    def __init__(self, name):
        self.name = name


def encv(v):
    """A value as the fixture writes it."""
    if isinstance(v, Dist):
        return {'$dist': [v.fn, [encv(a) for a in v.args], {k: encv(x) for k, x in v.kwargs.items()}]}
    if isinstance(v, Ref):
        return {'$block': v.name}
    if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
        return {'$float': 'nan' if math.isnan(v) else ('inf' if v > 0 else '-inf')}
    if isinstance(v, tuple):
        return {'$tuple': [encv(x) for x in v]}
    if isinstance(v, list):
        return [encv(x) for x in v]
    if isinstance(v, dict):
        return {str(k): encv(x) for k, x in v.items()}
    return v


def resolve(v, m):
    """A value as the Python package is given it."""
    if isinstance(v, Dist):
        return getattr(dist, v.fn)(*[resolve(a, m) for a in v.args], **{k: resolve(x, m) for k, x in v.kwargs.items()})
    if isinstance(v, Ref):
        return m.block(v.name)
    if isinstance(v, tuple):
        return tuple(resolve(x, m) for x in v)
    if isinstance(v, list):
        return [resolve(x, m) for x in v]
    if isinstance(v, dict):
        return {k: resolve(x, m) for k, x in v.items()}
    return v


def enc_result(x):
    """What a call returned, as JSON the Julia test can make of its own result."""
    if isinstance(x, kp.Block):
        return {'$block': x.qualified_name}
    if isinstance(x, IndexList):
        return {'$list': x.name}
    if isinstance(x, Shape):
        return {'$shape': x.id}
    if isinstance(x, OutputSeries):
        return {'$series': enc_result(dict(x._raw))}
    if isinstance(x, Simulation):
        return {'$simulation': enc_result(dict(x._raw))}
    if isinstance(x, View):
        return {'$view': enc_result(x.to_dict())}
    if isinstance(x, kp.Model):
        return {'$model': x.name}
    if isinstance(x, _dt.datetime):
        at = x.astimezone(_dt.timezone.utc)
        return {'$time': at.isoformat(timespec='milliseconds').replace('+00:00', 'Z')}
    if isinstance(x, (list, tuple)):
        return [enc_result(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted(enc_result(v) for v in x)
    if isinstance(x, dict):
        return {str(k): enc_result(v) for k, v in x.items()}
    return x


def canonical(fn, args, kwargs):
    """`args` and `kwargs` as the Julia package takes them: positional-or-keyword
    parameters positionally, defaults filled in up to the last one given."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return list(args), dict(kwargs)
    params = list(sig.parameters.values())
    pos = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    given = dict(zip([p.name for p in pos], args))
    rest = dict(kwargs)
    for p in pos:
        if p.name in rest:
            given[p.name] = rest.pop(p.name)
    last = max((k for k, p in enumerate(pos) if p.name in given), default=-1)
    out = []
    for p in pos[:last + 1]:
        if p.name in given:
            out.append(given[p.name])
        elif p.default is not inspect.Parameter.empty:
            out.append(p.default)
        else:
            raise TypeError(f'{fn.__name__}: {p.name} is not given')
    return out, rest


# --- a case ---------------------------------------------------------------------------------------------

class Case:
    """A starting model and the operations applied to it."""

    def __init__(self, name, data=None, new=None):
        self.name = name
        self.data = data
        self.new = new
        self.ops = []

    # The model.
    def m(self, method, *args, **kwargs):
        self.ops.append(('m', method, args, kwargs))
        return self

    def mset(self, attr, value):
        self.ops.append(('m=', attr, value))
        return self

    def mget(self, attr):
        self.ops.append(('m?', attr))
        return self

    def raw(self, key, value):
        """Writes a key of the model's dictionary itself, past every check."""
        self.ops.append(('r=', key, value))
        return self

    # A block.
    def b(self, name, method, *args, **kwargs):
        self.ops.append(('b', name, method, args, kwargs))
        return self

    def bset(self, name, attr, value):
        self.ops.append(('b=', name, attr, value))
        return self

    def bget(self, name, attr):
        self.ops.append(('b?', name, attr))
        return self

    def bitem(self, name, key, value):
        self.ops.append(('b[]=', name, key, value))
        return self

    # An index list.
    def l(self, list_name, method, *args, **kwargs):  # noqa: E743
        self.ops.append(('l', list_name, method, args, kwargs))
        return self

    def lset(self, list_name, attr, value):
        self.ops.append(('l=', list_name, attr, value))
        return self

    def lget(self, list_name, attr):
        self.ops.append(('l?', list_name, attr))
        return self

    # The simulation settings, and an output series.
    def s(self, method, *args, **kwargs):
        self.ops.append(('s', method, args, kwargs))
        return self

    def sset(self, attr, value):
        self.ops.append(('s=', attr, value))
        return self

    def sget(self, attr):
        self.ops.append(('s?', attr))
        return self

    def oset(self, i, attr, value):
        self.ops.append(('o=', i, attr, value))
        return self

    def oget(self, i, attr):
        self.ops.append(('o?', i, attr))
        return self

    # The view, a shape, a distribution.
    def v(self, method, *args, **kwargs):
        self.ops.append(('v', method, args, kwargs))
        return self

    def vset(self, attr, value):
        self.ops.append(('v=', attr, value))
        return self

    def vget(self, attr):
        self.ops.append(('v?', attr))
        return self

    def sh(self, shape_id, method, *args, **kwargs):
        self.ops.append(('sh', shape_id, method, args, kwargs))
        return self

    def shget(self, shape_id, attr):
        self.ops.append(('sh?', shape_id, attr))
        return self

    def d(self, fn, *args, **kwargs):
        self.ops.append(('d', fn, args, kwargs))
        return self


def start_model(case):
    if case.new is not None:
        m = kp.Model.new(*case.new)
        m.raw['created'] = STAMP
        return m
    return kp.Model(case.data)


def apply(m, op):
    """Applies one operation; returns (recorded op, what it returned)."""
    tag = op[0]
    if tag in ('m', 'b', 'l', 's', 'v', 'sh', 'd'):
        if tag == 'm':
            _, method, args, kwargs = op
            target, head = m, ['m']
        elif tag == 'b':
            _, name, method, args, kwargs = op
            target, head = m.block(name), ['b', name]
        elif tag == 'l':
            _, name, method, args, kwargs = op
            target, head = m.index_list(name), ['l', name]
        elif tag == 's':
            _, method, args, kwargs = op
            target, head = m.simulation, ['s']
        elif tag == 'v':
            _, method, args, kwargs = op
            target, head = m.view, ['v']
        elif tag == 'sh':
            _, sid, method, args, kwargs = op
            target = next(s for s in m.shapes if s.id == sid)
            head = ['sh', sid]
        else:
            _, method, args, kwargs = op
            target, head = dist, ['d']
        fn = getattr(target, method)
        cargs, ckwargs = canonical(fn, args, kwargs)
        recorded = head + [method, encv(list(cargs)), encv(dict(ckwargs))]
        return recorded, lambda: fn(*resolve(list(cargs), m), **resolve(dict(ckwargs), m))
    if tag == 'm=':
        _, attr, value = op
        return ['m=', attr, encv(value)], lambda: setattr(m, attr, resolve(value, m))
    if tag == 'm?':
        _, attr = op
        return ['m?', attr], lambda: getattr(m, attr)
    if tag == 'b=':
        _, name, attr, value = op
        return ['b=', name, attr, encv(value)], lambda: setattr(m.block(name), attr, resolve(value, m))
    if tag == 'b?':
        _, name, attr = op
        return ['b?', name, attr], lambda: getattr(m.block(name), attr)
    if tag == 'b[]=':
        _, name, key, value = op
        return ['b[]=', name, key, encv(value)], lambda: m.block(name).__setitem__(key, resolve(value, m))
    if tag == 'l=':
        _, name, attr, value = op
        return ['l=', name, attr, encv(value)], lambda: setattr(m.index_list(name), attr, resolve(value, m))
    if tag == 'l?':
        _, name, attr = op
        return ['l?', name, attr], lambda: getattr(m.index_list(name), attr)
    if tag == 's=':
        _, attr, value = op
        return ['s=', attr, encv(value)], lambda: setattr(m.simulation, attr, resolve(value, m))
    if tag == 's?':
        _, attr = op
        return ['s?', attr], lambda: getattr(m.simulation, attr)
    if tag == 'o=':
        _, i, attr, value = op
        return ['o=', i, attr, encv(value)], lambda: setattr(m.simulation.output_series[i], attr, resolve(value, m))
    if tag == 'o?':
        _, i, attr = op
        return ['o?', i, attr], lambda: getattr(m.simulation.output_series[i], attr)
    if tag == 'v=':
        _, attr, value = op
        return ['v=', attr, encv(value)], lambda: setattr(m.view, attr, resolve(value, m))
    if tag == 'v?':
        _, attr = op
        return ['v?', attr], lambda: getattr(m.view, attr)
    if tag == 'r=':
        _, key, value = op
        return ['r=', key, encv(value)], lambda: m.raw.__setitem__(key, resolve(value, m))
    if tag == 'sh?':
        _, sid, attr = op
        return ['sh?', sid, attr], lambda: getattr(next(s for s in m.shapes if s.id == sid), attr)
    raise ValueError(f'unknown operation {op!r}')


def run_case(case):
    m = start_model(case)
    start = {'new': list(case.new), 'created': STAMP} if case.new is not None else {'model': case.data}
    initial = m.to_json()
    steps = []
    last = initial
    for op in case.ops:
        error = None
        result = None
        try:
            recorded, call = apply(m, op)
        except Exception as e:  # the target itself is not there: recorded as the op's refusal
            raise RuntimeError(f'{case.name}: cannot set up {op!r}: {e}') from e
        try:
            got = call()
            if op[0] not in ('m=', 'b=', 'b[]=', 'l=', 's=', 'o=', 'v=', 'r='):
                result = dumps(enc_result(got), 0)
        except Exception as e:  # noqa: BLE001 -- every refusal is recorded
            error = {'class': type(e).__name__, 'message': str(e)}
        text = m.to_json()
        steps.append({'op': recorded, 'error': error, 'result': result, 'json': None if text == last else text})
        last = text
    return {'name': case.name, 'start': start, 'initial': initial, 'steps': steps}


# --- made-up models -----------------------------------------------------------------------------------------

def two_boxes(name='two-boxes'):
    c = Case(name, new=('Two boxes', 'Made up'))
    c.m('add_nuclides', ['Cs-137', 'Sr-90'])
    c.m('add_compartment', 'Soil', initial='1e10')
    c.m('add_compartment', 'Well')
    c.m('add_parameter', 'k', 0.05, unit='1/year')
    c.m('add_transfer', 'Soil', 'Well', rate='k')
    return c


def case_building():
    c = two_boxes('building')
    for attr in ('nuclides', 'materials', 'name', 'description', 'author', 'created', 'saved', 'decay_unit',
                 'scenarios', 'scenario', 'systems', 'transports', 'has_own_chains', 'review_tracking',
                 'compartments', 'transfers', 'parameters', 'index_lists', 'derived', 'shapes'):
        c.mget(attr)
    c.bget('Soil', 'index_lists').bget('k', 'index_lists').bget('Soil_Well', 'unit')
    for attr in ('source', 'target', 'rate', 'multiply_by_donor', 'is_release', 'kind', 'collection', 'value_key',
                 'entry_keys', 'equation_keys', 'qualified_name', 'system', 'name', 'value', 'shape', 'size',
                 'position', 'color', 'enabled', 'effectively_enabled', 'sum_extra_indices', 'line_color', 'line_width',
                 'dash', 'availability', 'review'):
        c.bget('Soil_Well', attr)
    c.m('state_count').m('check')
    # Default names follow the application.
    c.m('add_compartment').m('add_compartment').m('add_expression').m('add_parameter')
    c.m('add_transfer', 'C', None).m('add_transfer', 'C', 'C1').m('add_transfer', 'C', 'C1')
    c.m('add_inflow', 'C1').m('add_inflow', 'C1', '2', name='Feed')
    c.m('add_lookup').m('add_index_reduction').m('add_block_reduction').m('add_function').m('add_min_max')
    c.m('add_running_mean').m('add_snapshot').m('add_delay').m('add_trigger').m('add_event')
    c.m('add_farfield').m('add_waste_package')
    c.m('names').m('names', 'compartment').m('blocks', 'transfer').m('blocks', None, '', False)
    c.m('get', 'Soil').m('get', 'Nothing').m('block', 'Nothing').m('blocks', 'gizmo')
    c.m('unique_name', 'Soil').m('unique_name', 'C').m('unique_name', 'New')
    for kind in ('compartment', 'parameter', 'lookup', 'expression', 'transfer', 'farfield'):
        c.m('default_dimensions', kind)
    c.m('derived_unit', 'Soil_Well').m('derived_unit', 'In').m('derived_unit', 'Soil')
    c.m('material_dimension').m('index_combinations', ['Radionuclides']).m('combination_count', ['Radionuclides'])
    c.m('index_combinations', []).m('combination_count', [])
    c.m('state_count').m('check').m('settle').m('references_graph')
    c.mset('name', '  Renamed model ').mset('description', 'A new description').mset('author', ' A. Modeller ')
    c.mget('name').mget('author').mset('author', '').mget('author').mset('name', '').mget('name')
    c.m('copy')
    return c


def case_names_refused():
    c = two_boxes('names-refused')
    for bad in ('1abc', 'a-b', 'exp', '__proto__', 'Soil', '', 'time', 'sum'):
        c.m('add_parameter', bad, 1)
    c.m('add_parameter', None, 1)
    c.m('add_parameter', 'q', 'not a number')
    c.m('add_parameter', 'q', True)
    c.m('add_parameter', 'q', '5')
    c.m('add_parameter', 'r', '1e3')
    c.m('add_parameter', 'r2', ' 7.0 ')
    c.m('add_parameter', 'r3', '1_000')
    c.m('add_lookup', 'L', points=[[0, 1], ['x', 2]])
    c.m('add_lookup', 'L', points=[[0, 1], [2]])
    c.m('add_lookup', 'L', points=[{'x': 0, 'y': 1}, {'x': 5, 'y': '2', 'pdf': None}])
    c.m('add_index_reduction', 'R', 'Nothing')
    c.m('add_compartment', 'A', abstol=0)
    c.m('add_compartment', 'A2', abstol='x')
    c.m('add_compartment', 'A3', abstol=1e-3)
    c.m('add_compartment', 'B', True)
    c.m('add_compartment', 'B', index_lists=['Nope'])
    c.m('add_compartment', 'B', system='Nope')
    c.m('add_compartment', 'B', dydt=2.5, non_negative=False, handle_decay=False, comment='c', symbol='B<sub>1</sub>',
        unit='kg', position=(10.4, 20.6))
    c.m('add_compartment', 'B2', 5, index_lists=[], position={'x': 1, 'y': '2'})
    c.m('add_expression', 'E1', 3)
    c.m('add_expression', 'E2', None)
    c.m('add_expression', 'E3', 'Soil * 2', unit='Bq', index_lists=['Radionuclides', 'Contaminants'])
    c.m('add_expression', 'E4', 'Soil * 2', index_lists=['Radionuclides', 'Radionuclides'])
    c.m('add_transfer', None, None)
    c.m('add_transfer', 'Soil', 'Soil')
    c.m('add_transfer', 'Soil', 'Nowhere')
    c.m('add_transfer', 'k', 'Soil')
    c.m('add_inflow', None)
    c.m('add_inflow', 'k')
    c.m('add_lookup', 'L2', interpolation='cubic')
    c.m('add_index_reduction', 'R2', operation='median')
    c.m('add_index_reduction', 'R3', operation='percentile')
    c.m('add_index_reduction', 'R4', 'Soil', operation='percentile', percentile=150)
    c.m('add_index_reduction', 'R5', 'Soil', operation='percentile', percentile=95)
    c.m('add_block_reduction', 'G', operation='percentile')
    c.m('add_block_reduction', 'G2', ['Soil', 'Nope'])
    c.m('add_min_max', 'P', operation='median')
    c.m('add_trigger', 'T9', direction='up')
    c.m('add_farfield', 'F', gizmo=1)
    c.m('add_waste_package', 'W', gizmo=1)
    c.m('add_waste_package', 'W', failure='sometimes')
    c.m('add_waste_package', 'W2', failure='at')
    c.m('add_event', 'Ev', timing='often')
    c.m('add_event', 'Ev', at=True)
    c.m('add_function', 'f', ['x', 'x'])
    c.m('add_function', 'f', ['exp'])
    c.m('add_function', 'f', ['Soil'])
    c.m('add_function', 'f', ['1a'])
    c.m('add_function', 'f', ['a', '', None, ' b '], 'a + b')
    c.m('add_transport_operation', '', 'Op')
    c.m('add_system', 'Soil').m('add_system', '1x').m('add_system', None, 'Nope')
    c.m('check')
    return c


def case_per_index():
    c = two_boxes('per-index')
    c.b('Soil', 'set_value', '5e9', at='Cs-137')
    c.b('Soil', 'set_entry', 'Sr-90', initial='2', abstol=1e-3)
    c.b('Soil', 'value_at', 'Cs-137').b('Soil', 'value_at', {'Radionuclides': 'Sr-90'})
    c.b('Soil', 'value_at', 'Sr-90', key='abstol').b('Soil', 'value_at').bget('Soil', 'value')
    c.b('Soil', 'overrides').b('Soil', 'overrides', 'abstol').b('Soil', 'combinations')
    c.b('Soil', 'clear_value', 'Cs-137').b('Soil', 'value_at', 'Cs-137')
    c.b('Soil', 'set_value', '1', at='U-238')
    c.b('Soil', 'set_value', '1', at='Cs-137', key='rate')
    c.b('Soil', 'set_value', '1', at=('Cs-137', 'x'))
    c.b('Soil', 'set_value', '1', at={'Objects': 'A'})
    c.b('Soil', 'set_value', 3, at=('Cs-137',))
    c.b('Soil', 'set_value', '7', 'Sr-90', 'dydt')
    c.b('Soil', 'set_value', '0.5', key='dydt')
    c.b('Soil', 'set_value', True, key='non_negative', at='Sr-90')
    c.b('Soil', 'set_value', 1e-9, key='abstol')
    c.b('Soil', 'set_entry', 'Cs-137', rate='1')
    c.b('Soil', 'index', 'Cs-137').b('Soil', 'index', ('Sr-90',)).b('Soil', 'index', {'Radionuclides': 'Sr-90'})
    c.b('Soil', 'index', None)
    c.b('Soil', 'clear_value', 'Sr-90', 'abstol').b('Soil', 'clear_value', 'Sr-90', 'dydt')
    c.b('Soil', 'clear_value', 'Sr-90', 'non_negative').b('Soil', 'clear_value', 'Sr-90')
    c.b('Soil', 'overrides')
    c.b('k', 'set_value', '0.07').b('k', 'set_value', '2').b('k', 'set_value', 'x').b('k', 'set_value', 1, at='Cs-137')
    c.b('Soil_Well', 'set_value', 'k * 2', at='Cs-137').b('Soil_Well', 'set_entry', 'Sr-90', multiply_by_donor=False)
    c.b('Soil_Well', 'value_at', 'Sr-90')
    c.bset('Soil', 'value', '3e10').bget('Soil', 'initial')
    c.bset('Soil', 'initial', 4).bset('Soil', 'initial', None).bget('Soil', 'initial')
    c.bset('Soil', 'dydt', '-Soil * 0.1').bset('Soil', 'abstol', '1e-4').bset('Soil', 'abstol', 'tiny')
    c.bset('Soil', 'non_negative', 0).bset('Soil', 'handle_decay', '')
    c.bget('Soil', 'non_negative').bget('Soil', 'handle_decay').bget('Soil', 'transport_role')
    c.b('Soil', 'outflows').b('Well', 'inflows').b('Soil', 'reads').b('Soil', 'references')
    c.m('set_dimensions', 'Soil', ['Contaminants'])
    c.b('Soil', 'combinations').b('Soil', 'overrides')
    return c


def case_two_dimensions():
    c = two_boxes('two-dimensions')
    c.m('add_index_list', 'Object', ['Lake', 'Mire'])
    c.m('set_dimensions', 'Soil', ['Radionuclides', 'Object'])
    c.bget('Soil_Well', 'index_lists')
    c.m('add_parameter', 'Kd', 0, index_lists=['Radionuclides', 'Object'])
    c.b('Kd', 'set_value', 0.03, at={'Radionuclides': 'Cs-137', 'Object': 'Lake'})
    c.b('Kd', 'set_value', 0.01, at=('Sr-90', 'Mire'))
    c.b('Kd', 'value_at', ('Cs-137', 'Lake')).b('Kd', 'value_at', ('Cs-137', 'Mire'))
    c.b('Kd', 'combinations')
    c.b('Kd', 'set_value', 1, at='Lake')
    c.b('Kd', 'value_at', ('Sr-90', 'Lake'))
    c.b('Kd', 'set_value', 2, at=(None, 'Mire'))
    c.b('Kd', 'value_at', ('Sr-90', 'Mire')).b('Kd', 'overrides')
    c.m('set_dimensions', 'Kd', ['Radionuclides', 'Contaminants'])
    c.m('add_index_list', 'Wet', ['Lake'], subset_of='Object')
    c.m('set_dimensions', 'Kd', ['Object', 'Wet'])
    c.m('set_dimensions', 'Kd', ['Wet'])
    c.b('Kd', 'overrides')
    c.m('add_index_list', 'Both', ['Mire', 'Lake'])
    c.b('Kd', 'set_value', 5, at='Lake')
    c.m('set_dimensions', 'Kd', ['Object', 'Both'])
    c.b('Kd', 'set_value', 5, at='Lake')
    c.b('Kd', 'set_value', 5, at='Mire')
    c.m('set_dimensions', 'Well', ['Radionuclides', 'Object'])
    c.bget('Soil_Well', 'index_lists')
    c.m('set_dimensions', 'Well', [])
    c.bget('Soil_Well', 'index_lists').m('settle').bget('Soil_Well', 'index_lists')
    c.m('set_dimensions', 'Soil', ['Compartments'])
    c.m('set_dimensions', 'Kd', ['Compartments'])
    c.b('Kd', 'set_value', 4, at='Soil')
    c.m('set_dimensions', 'Kd', ['Compartments', 'Transfers'])
    c.m('add_function', 'f')
    c.m('set_dimensions', 'f', ['Object']).m('set_dimensions', 'f', [])
    c.bset('f', 'index_lists', ['Object']).bset('f', 'index_lists', [])
    c.m('state_count').m('check')
    return c


def case_distributions():
    c = two_boxes('distributions')
    c.bset('k', 'distribution', Dist('log_triangular', 0.01, 0.1, 0.05))
    c.bget('k', 'distribution')
    c.d('log_uniform', -1, 1).d('uniform', 2, 1).d('uniform', 1, 2).d('triangular', 0, 10, 3, trmin=1, trmax=9)
    c.d('double_triangular', 0, 10, 12).d('normal', 0, -1).d('normal', 5, 1, pmin=0.05, pmax=0.95, group='g1')
    c.d('normal', 5, 1, pmin=5).d('normal', 5, 1, pmin=0.9, pmax=0.1).d('log_triangular', 1, 10, 0.5)
    c.d('log_double_triangular', 1, 10, 3).d('lognormal', 2, 1, trmin=-1).d('lognormal_geometric', 10, 1)
    c.d('lognormal_geometric', 10, 2.5).d('lognormal_quantiles', 0.05, 1, 0.95, 10)
    c.d('lognormal_quantiles', 0.5, 1, 0.5, 10).d('lognormal_quantiles', 0, 1, 0.95, 10)
    c.d('value_list', [1, 2, '3.5']).d('value_list', [3, 1], False, 2).d('make_pdf', 'gamma')
    c.d('make_pdf', 'unif', min=0, max=1, mode=0.5).d('make_pdf', 'pg', mode=1).d('make_pdf', 'unif', min='x')
    c.d('make_pdf', 'unif', min=INF).d('make_pdf', 'unif', min='', max=None).d('make_pdf', 'unif', min=1, max=0, check=False)
    c.d('make_pdf', 'norm', mean=1, sd=2, group='  ', inorder=0, pos=3.7).d('make_pdf', 'logt', min=1, max=2, mode=1.5, trmin=1.2)
    c.d('pdf_problems', {'kind': 'logu', 'params': {'min': -1, 'max': 2}, 'trmin': -1})
    c.d('pdf_problems', {'kind': 'nope'}).d('pdf_problems', None)
    for spec in (dist.log_triangular(0.01, 0.1, 0.05), dist.value_list([1, 2, 3]), None, {'kind': 'zzz'},
                 {'kind': 'norm', 'params': {'mean': 1, 'sd': None}}):
        c.d('describe', spec)
    c.m('set_dimensions', 'k', ['Radionuclides'])
    c.b('k', 'set_distribution', 'norm', at='Cs-137', mean=0.05, sd=0.01, trmin=0)
    c.b('k', 'distribution_at', 'Cs-137').b('k', 'distribution_at', 'Sr-90').b('k', 'distribution_at')
    c.b('k', 'set_distribution', 'norm', 'Sr-90', mean=0.05, sd=-1)
    c.b('k', 'set_distribution', 'unif', min=0.01, max=0.02)
    c.b('k', 'set_distribution', None, at='Cs-137').b('k', 'set_distribution', None)
    c.bset('k', 'distribution', {'kind': 'logu', 'params': {'min': -1, 'max': 1}})
    c.bset('k', 'distribution', {'params': {}})
    c.bset('k', 'distribution', 'logu')
    c.b('k', 'set_value', {'kind': 'unif', 'params': {'min': 1, 'max': 2}}, 'Sr-90', 'pdf')
    c.b('k', 'set_value', None, 'Sr-90', 'pdf')
    c.bset('k', 'distribution', None).bget('k', 'distribution')
    c.m('add_parameter', 'q', 2, distribution=Dist('uniform', 1, 3))
    c.m('add_parameter', 'q2', 2, distribution={'kind': 'unif', 'params': {'min': 3, 'max': 1}})
    return c


def case_lookups():
    c = two_boxes('lookups')
    c.m('add_lookup', 'Q', [[0, 1], [100, 2]], interpolation='nearest', argument='x')
    c.bget('Q', 'points').bget('Q', 'argument').bget('Q', 'interpolation').bget('Q', 'cyclic')
    c.m('add_lookup', 'Flat').bget('Flat', 'points')
    c.sset('start_time', 10).sset('end_time', 5).m('add_lookup', 'Flat2')
    c.sset('end_time', 1000)
    c.bset('Q', 'interpolation', 'cubic').bset('Q', 'interpolation', 'below').bset('Q', 'cyclic', 1)
    c.b('Q', 'set_point_distribution', 1, 'unif', min=1.5, max=2.5)
    c.b('Q', 'set_point_distribution', 0, 'unif', min=3, max=2.5)
    c.b('Q', 'set_point_distribution', 2, 'unif', min=1.5, max=2.5)
    c.b('Q', 'set_point_distribution', -1, 'unif', min=1.5, max=2.5)
    c.bget('Q', 'points')
    c.b('Q', 'set_point_distribution', 1, None).bget('Q', 'points')
    c.bset('Q', 'argument', '1x').bset('Q', 'argument', 'depth').bset('Q', 'argument', '').bget('Q', 'argument')
    c.bset('Q', 'points', [[0, 0], [1.5, '2'], (3, 4, None), {'x': 5, 'y': 6, 'pdf': {'kind': 'unif'}}])
    c.bset('Q', 'points', [[0, 0], ['a', 1]])
    c.b('Q', 'set_value', [[1, 2], [3, 4]])
    c.bget('Q', 'value')
    c.m('add_lookup', 'Tab', [[0, 1]], index_lists=['Radionuclides'], cyclic=True, unit='m3/year', comment='x')
    c.b('Tab', 'set_value', [[0, 5], [1, 6]], at='Cs-137')
    c.b('Tab', 'set_value', [[0, 'x']], at='Sr-90')
    c.b('Tab', 'value_at', 'Cs-137')
    return c


def case_every_kind():
    c = two_boxes('every-kind')
    c.m('add_expression', 'Conc', 'Well / 10')
    c.m('add_index_reduction', 'Total', 'Conc')
    c.m('add_block_reduction', 'Both', ['Soil', 'Well'], operation='max')
    c.m('add_function', 'twice', ['x'], 'x * 2')
    c.m('add_trigger', 'High', 'Conc', '1e3')
    c.m('add_min_max', 'Peak', 'Conc', reset_trigger='High')
    c.m('add_running_mean', 'Mean', 'Conc', start_trigger='High')
    c.m('add_snapshot', 'Snap', 'time', 'High', initial='-1')
    c.m('add_delay', 'Late', 'Conc', 100)
    c.m('add_farfield', 'Rock', n_f=10, kd_m='0.1')
    c.m('set_release', 'Rock', 'Well')
    c.m('add_waste_package', 'Pkgs', failure='weibull', fail_start=1000, fail_scale=5e4, fail_shape=2,
        inventory='1e12')
    c.m('add_compartment', 'Near')
    c.b('Pkgs', 'set_release', 'Near')
    c.m('add_event', 'Quake', timing='poisson', rate='1e-5')
    c.b('Quake', 'add_fail_action', 'Pkgs', 0.05)
    c.b('Quake', 'add_move_action', 'Well', None, '0.5')
    c.bget('Rock', 'n_f').bget('Rock', 'release').bget('Pkgs', 'release').bget('Quake', 'actions')
    c.bget('Rock_Well', 'is_release').bget('Total', 'index_lists').bget('Total', 'over')
    c.bget('Peak', 'index_lists').bget('Snap', 'index_lists').bget('Late', 'index_lists')
    c.m('check')
    c.m('add_transfer', 'Rock', 'Near')
    c.m('references_to', 'Conc').m('references_to', 'High').m('reads', 'Snap').m('reads', 'Quake')
    c.m('references_graph').m('state_count')
    c.m('rename_block', 'High', 'Crossing')
    c.bget('Peak', 'reset_trigger').bget('Mean', 'start_trigger').bget('Snap', 'trigger')
    c.m('rename_block', 'Conc', 'Concentration')
    c.bget('Total', 'target').bget('Crossing', 'first').bget('Late', 'target')
    c.m('rename_block', 'Pkgs', 'Canisters')
    c.bget('Quake', 'actions')
    c.m('rename_block', 'Well', 'Pond')
    c.bget('Quake', 'actions').bget('Rock_Well', 'target').bget('Both', 'targets')
    c.m('delete_block', 'Canisters').m('delete_block', 'Concentration').m('delete_block', 'twice')
    c.m('delete_blocks', ['Crossing', 'Peak', 'Mean', 'Snap'])
    c.m('delete_block', 'Rock')
    c.m('check')
    return c


def case_farfield():
    c = Case('farfield-paths', new=('Paths', ''))
    c.sset('end_time', 1000)
    c.m('add_farfield', 'Rock')
    for attr in ('o_b', 'n_b', 'grid', 'surface', 'method', 'tw', 'f', 'aw', 'aperture', 'kd_f', 'n_f', 'n_m',
                 'handle_decay', 'report_cells', 'index_lists', 'unit', 'release'):
        c.bget('Rock', attr)
    c.bset('Rock', 'surface', 'aperture').bset('Rock', 'aperture', '1e-3').bset('Rock', 'n_b', 3)
    c.bget('Rock', 'n_b').bset('Rock', 'n_b', '').bget('Rock', 'n_b').bset('Rock', 'n_b', '  ')
    c.bset('Rock', 'n_b', 2.5).bset('Rock', 'n_b', 'x').bset('Rock', 'n_f', 2.0).bset('Rock', 'n_f', '7')
    c.bset('Rock', 'surface', 'width').bset('Rock', 'grid', 'fine').bset('Rock', 'o_b', 5).bset('Rock', 'o_b', 4.0)
    c.bset('Rock', 'o_b', '4').bset('Rock', 'method', 'semi-analytical').bget('Rock', 'method')
    c.bset('Rock', 'method', 'exact')
    c.m('add_farfield', 'Rock2', kd_f=-0.1)
    for bad in ('-1e-7', -2, ' -3 '):
        c.bset('Rock', 'kd_f', bad)
    for good in (0, '1e-3', 'Kd_coat', '-Kd_coat', ''):
        c.bset('Rock', 'kd_f', good)
    c.bget('Rock', 'kd_f')
    c.m('add_index_list', 'Species', ['A', 'B'])
    c.bset('Rock', 'index_lists', ['Species'])
    c.b('Rock', 'set_value', '-1', at='A').b('Rock', 'set_entry', 'B', kd_f=-1)
    c.b('Rock', 'set_value', '0.5', at='A').b('Rock', 'value_at', 'A')
    for key in ('kd_m', 'de_m', 'eps_m', 'rho_m'):
        c.bset('Rock', key, '-1e-3').bset('Rock', key, '1e-3')
    c.bset('Rock', 'kd_f', '0')
    c.m('add_compartment', 'Out')
    c.m('add_inflow', 'Rock', rate='1')
    c.m('set_release', 'Rock', 'Out')
    c.m('set_release', 'Rock', 'Out')
    c.bget('Rock', 'release').bget('Rock_Out', 'is_release').bget('Rock_Out', 'rate')
    c.m('add_compartment', 'Out2')
    c.m('set_release', 'Rock', 'Out2')
    c.m('set_connection_end', 'Rock_Out', 'from', 'Out')
    c.m('add_transfer', 'Rock', 'Out')
    c.m('set_release', 'Rock', None)
    c.m('set_release', 'Out', 'Out2')
    c.m('state_count').m('check')
    c.m('add_nuclides', ['Cs-135', 'I-129'])
    c.m('add_farfield', 'Rock3', index_lists=['Radionuclides'], tw='50', aw='500', report_cells=True, handle_decay=0)
    c.b('Rock3', 'set_entry', 'Cs-135', kd_f='0.1', tw='5')
    c.b('Rock3', 'set_entry', 'I-129', kd_m='0.01', de_m='1e-3')
    c.m('add_farfield', 'Rock4', index_lists=['Radionuclides', 'Contaminants'])
    c.m('add_index_list', 'Rad2', ['Cs-135'], subset_of='Contaminants')
    c.m('add_farfield', 'Rock5', index_lists=['Rad2', 'Species'])
    c.m('state_count').m('check')
    return c


def case_waste_and_events():
    c = two_boxes('waste-and-events')
    c.m('add_waste_package', 'Pk', failure='at', fail_at='1000', packages=4)
    for attr in ('failure', 'fail_at', 'packages', 'inventory', 'irf', 'handle_decay', 'release', 'index_lists', 'unit'):
        c.bget('Pk', attr)
    c.b('Pk', 'set_failure', 'uniform', fail_from=100, fail_to=200)
    c.b('Pk', 'set_failure', 'exponential')
    c.b('Pk', 'set_failure', 'exponential', fail_rate='1e-3')
    c.b('Pk', 'set_failure', 'weibull', fail_scale='1e5')
    c.b('Pk', 'set_failure', 'sometimes').b('Pk', 'set_failure', 'at', inventory='5')
    c.bset('Pk', 'packages', 2.5).bset('Pk', 'packages', '3').bset('Pk', 'failure', 'never')
    c.b('Pk', 'set_value', '1e9', at='Cs-137').b('Pk', 'set_entry', 'Sr-90', irf='0.1', degradation_rate='1e-4')
    c.b('Pk', 'set_entry', 'Sr-90', fail_at='5')
    c.b('Pk', 'set_release', 'Well').b('Pk', 'set_release', 'Soil').bget('Pk', 'release')
    c.m('add_waste_package', 'Pk2', inventory='2', irf='0.5', handle_decay=False)
    c.m('add_transfer', 'Well', 'Pk2')
    c.m('add_event', 'Ev', at='500').m('add_event', 'Ev2', timing='poisson', rate=1e-4, start=10, until='1e4',
                                       sampled=False)
    c.m('add_event', 'Ev3', at=None, comment='No time')
    c.b('Ev', 'add_fail_action', 'Pk', '0.5').b('Ev', 'add_fail_action', 'Soil')
    c.b('Ev', 'add_move_action', 'Soil', 'Well', 0.25).b('Ev', 'add_move_action', 'Soil', 'Soil')
    c.b('Ev', 'add_move_action', 'Pk', 'Well').b('Ev', 'add_move_action', 'Soil', 'k')
    c.b('Ev', 'add_move_action', 'Well')
    c.bget('Ev', 'actions').bget('Ev', 'index_lists').bget('Ev', 'start').bget('Ev2', 'start').bget('Ev2', 'until')
    c.bset('Ev2', 'start', '20').bset('Ev2', 'timing', 'never').bset('Ev', 'index_lists', ['Radionuclides'])
    c.bset('Ev', 'index_lists', []).m('set_dimensions', 'Ev', ['Radionuclides'])
    c.b('Ev', 'set_value', '600').b('Ev', 'set_value', '7', key='from').b('Ev', 'set_value', '1', at='x')
    c.m('references_to', 'Pk').m('references_to', 'Soil').m('reads', 'Ev')
    c.m('delete_block', 'Pk')
    c.m('rename_block', 'Pk', 'Packages')
    c.m('rename_block', 'Soil', 'Topsoil')
    c.bget('Ev', 'actions')
    c.m('add_system', 'Near').m('move_block', 'Packages', 'Near').m('move_block', 'Well', 'Near')
    c.bget('Ev', 'actions')
    c.b('Ev', 'clear_actions').bget('Ev', 'actions')
    c.m('delete_block', 'Near.Packages')
    c.m('state_count').m('check')
    return c


def case_decay():
    c = Case('decay', new=('Decay', ''))
    c.m('add_nuclides', ['U-238', 'U-234', 'Th-230'])
    c.mget('decay_chains').mget('has_own_chains').m('half_life', 'U-238').m('half_life', 'Xx-1')
    c.m('add_decay_pair', 'Th-230', 'U-238')
    c.m('add_decay_pair', 'U-238', 'U-238').m('add_decay_pair', '', 'U-238').m('add_decay_pair', 'U-238', 'Th-230', 2)
    c.m('add_decay_pair', 'U-238', 'Th-230', 0).m('add_decay_pair', 'U-238', 'U-234')
    c.m('set_decay_ratio', 'U-238', 'U-234', 0.99)
    c.mget('has_own_chains').mget('decay_chains')
    c.m('set_decay_ratio', 'U-238', 'Th-230', 0.5).m('set_decay_ratio', 'U-238', 'U-234', 1.5)
    c.m('add_decay_pair', 'U-238', 'Th-230', '0.01')
    c.m('remove_decay_pair', 'U-238', 'Th-230').m('remove_decay_pair', 'U-238', 'Th-230')
    c.m('reset_decay_chains').mget('has_own_chains')
    c.m('add_nuclides', ['Xx-1'])
    c.m('half_life', 'Xx-1')
    c.m('set_half_life', 'Xx-1', 12.5).m('half_life', 'Xx-1').m('set_half_life', 'Xx-1', -1)
    c.m('set_half_life', 'Xx-1', 'inf').m('half_life', 'Xx-1').m('set_half_life', 'Xx-1', '25')
    c.m('set_half_life', 'U-234', INF).m('set_half_life', 'U-234', None).m('half_life', 'U-234')
    c.m('remove_nuclide', 'Xx-1')
    c.m('add_material', 'Water', unit='m3').m('material_unit', 'Water').m('material_unit', 'U-238')
    c.m('set_material_unit', 'U-238', 'kg').m('set_material_unit', 'Nope', 'kg')
    c.m('set_material_unit', 'Water', '  ').m('material_unit', 'Water')
    c.m('add_compartment', 'Tank')
    c.mset('decay_unit', 'mol').m('material_unit', 'U-238').mset('decay_unit', 'kg').mget('decay_unit')
    c.m('set_decay_chains', [('U-238', 'U-234', 1), ('U-234', 'Th-230')])
    c.m('set_decay_chains', [('U-238', 'U-234'), ('U-234', 'U-238')])
    c.m('set_decay_chains', [('U-238', 'U-234', 2)])
    c.mget('decay_chains')
    c.m('add_nuclides', ['Ra-226', 'Pb-210', 'U-238'], {'Ra-226': 1600, 'U-238': 'stable', 'Zz-9': 3},
        [('Ra-226', 'Pb-210', 1), ('Pb-210', 'Ra-226'), ('Th-230', 'Ra-226', 1), ('Ra-226', 'Ra-226')])
    c.mget('decay_chains')
    c.m('add_nuclides', ['Cs-137', 'Cs-137', 'Ba-137m'])
    c.m('remove_material', 'Ba-137m').m('remove_material', 'Nope')
    c.mget('nuclides').mget('materials')
    c.m('remove_index', 'Radionuclides', 'Th-230')
    c.m('add_index', 'Contaminants', 'Steel').mget('nuclides').mget('materials')
    c.m('set_index_enabled', 'Radionuclides', 'U-234', False).mget('nuclides')
    c.m('index_combinations', ['Radionuclides'])
    c.m('set_index_enabled', 'Contaminants', 'U-234', True).mget('nuclides')
    c.m('rename_index', 'Radionuclides', 'U-238', 'U238').mget('decay_chains').m('half_life', 'U238')
    c.m('state_count').m('check')
    return c


def case_scenarios():
    c = two_boxes('scenarios')
    c.m('add_scenarios', ['Base', 'Wet'])
    c.mget('scenario').mget('scenarios').mset('scenario', 'Wet').mget('scenario')
    c.l('Scenarios', 'rename_index', 'Wet', 'Humid').mget('scenario')
    c.mset('scenario', 'Dry')
    c.l('Scenarios', 'set_enabled', 'Humid', False).mget('scenarios').mget('scenario')
    c.mset('scenario', None).mget('scenario')
    c.m('add_index_list', 'Climate', ['Warm', 'Cold'])
    c.m('set_scenario_list', 'Climate').mget('scenario').mget('scenarios')
    c.m('set_scenario_list', 'Climate', False).mget('scenarios').mget('scenario')
    c.m('set_scenario_list', 'Radionuclides')
    c.m('set_scenario_list', 'Nope')
    c.m('add_scenarios', ['A'], 'Futures')
    c.m('add_scenarios', ['A', 'A'], 'Futures2')
    c.m('add_parameter', 'q', 1, index_lists=['Futures'])
    c.b('q', 'set_value', 2, at='A')
    c.m('set_dimensions', 'Soil', ['Radionuclides', 'Futures'])
    c.bget('Soil_Well', 'index_lists')
    c.m('check')
    return c


def case_index_lists():
    c = two_boxes('index-lists')
    c.m('add_index_list', 'Object', ['Lake', 'Mire', 'Forest'], comment='The landscape')
    c.m('add_index_list', 'Wetland', ['Mire'], subset_of='Object')
    c.m('add_index_list', 'Kind', ['Water', 'Land'], mapping_to='Object',
        pairs={'Lake': 'Water', 'Mire': 'Land', 'Forest': 'Land'})
    c.m('add_index_list', '1x').m('add_index_list', 'exp').m('add_index_list', 'Object')
    c.m('add_index_list', 'Both', subset_of='Object', mapping_to='Object')
    c.m('add_index_list', 'Dup', ['a', 'a']).m('add_index_list', 'Bad', ['a<b>']).m('add_index_list', 'Blank', [' '])
    c.m('add_index_list', 'Sub', ['Pond'], subset_of='Object').m('add_index_list', 'Sub2', ['Mire'], subset_of='Nope')
    c.m('add_index_list', 'Map2', ['X'], mapping_to='Object', pairs={'Lake': 'Y'})
    c.m('add_index_list', 'Map3', ['X'], mapping_to='Wetland')
    c.m('add_index_list', 'Sub3', ['Mire'], subset_of='Wetland')
    c.lget('Object', 'indices').lget('Object', 'comment').lget('Wetland', 'subset_of').lget('Kind', 'mapping')
    c.lget('Kind', 'is_derived').lget('Radionuclides', 'is_nuclides').lget('Contaminants', 'is_materials')
    c.l('Object', 'add_index', 'Bog').l('Object', 'add_index', 'Bog').l('Object', 'add_index', None)
    c.l('Object', 'rename_index', 'Bog', 'Fen').l('Object', 'rename_index', 'Bog', 'Fen')
    c.l('Object', 'rename_index', 'Fen', '').l('Object', 'rename_index', 'Fen', 'Lake')
    c.l('Object', 'rename_index', 'Fen', '  Fen ')
    c.l('Kind', 'map_index', 'Fen', 'Water').lget('Kind', 'mapping')
    c.l('Kind', 'rename_index', 'Water', 'H2O').lget('Kind', 'mapping').l('Kind', 'rename_index', 'H2O', 'Water')
    c.m('index_combinations', ['Object', 'Nope']).m('combination_count', ['Kind', 'Object'])
    c.l('Kind', 'map_index', 'Fen', None).l('Kind', 'map_index', 'Nope', 'Water').l('Kind', 'map_index', 'Fen', 'Ice')
    c.l('Object', 'map_index', 'Lake', 'Water')
    c.l('Object', 'set_enabled', 'Fen', False).lget('Object', 'enabled_indices')
    c.l('Object', 'set_enabled', 'Nope', False)
    c.l('Object', 'add_indices', ['Sea', 'Lake'])
    c.m('add_parameter', 'K', 1, index_lists=['Object'])
    c.b('K', 'set_value', 2, at='Fen').b('K', 'set_value', 3, at='Mire')
    c.m('add_expression', 'E', 'K[Fen] + K[Mire]', index_lists=[])
    c.l('Object', 'rename_index', 'Fen', 'Marsh')
    c.bget('E', 'equation').b('K', 'overrides')
    c.l('Wetland', 'add_index', 'Marsh').l('Wetland', 'add_index', 'Ocean')
    c.l('Object', 'rename_index', 'Marsh', 'Swamp').lget('Wetland', 'indices')
    c.l('Object', 'remove_index', 'Swamp').lget('Wetland', 'indices').b('K', 'overrides').bget('E', 'equation')
    c.l('Object', 'remove_index', 'Nope')
    c.l('Object', 'users').l('Wetland', 'users').l('Radionuclides', 'users')
    c.l('Object', 'delete').l('Wetland', 'delete').lget('Object', 'indices')
    c.l('Kind', 'rename', 'Sort').lget('Sort', 'name').l('Sort', 'rename', 'Object').l('Sort', 'rename', '9x')
    c.l('Sort', 'rename', 'exp').l('Sort', 'rename', 'Sort')
    c.l('Radionuclides', 'rename', 'Nuclides').l('Contaminants', 'rename', 'Stuff')
    c.l('Object', 'rename', 'Site').bget('K', 'index_lists').b('K', 'overrides')
    c.lset('Site', 'comment', 'Places').lget('Site', 'comment').lset('Site', 'comment', '').lget('Site', 'comment')
    c.m('set_list_role', 'Sort', 'plain').lget('Sort', 'mapping')
    c.m('set_list_role', 'Sort', 'sub_set', 'Site').lget('Sort', 'indices')
    c.m('set_list_role', 'Sort', 'mapping', 'Site').m('set_list_role', 'Sort', 'mapping', 'Sort')
    c.m('set_list_role', 'Sort', 'group', 'Site').m('set_list_role', 'Radionuclides', 'plain')
    c.m('add_index_list', 'Region', ['North', 'South'])
    c.m('set_list_role', 'Region', 'mapping', 'Site')
    c.m('map_index', 'Region', 'Lake', 'North').m('map_index', 'Region', 'Mire', 'South').lget('Region', 'mapping')
    c.m('set_list_role', 'Region', 'mapping', 'Site').lget('Region', 'mapping')
    c.m('set_list_role', 'Sort', 'mapping', 'Region')
    c.m('index_list', 'Elements').m('index_list', 'Compartments').m('index_list', 'Transfers')
    c.lget('Compartments', 'indices').lget('Elements', 'indices').lget('Elements', 'mapping')
    c.l('Compartments', 'add_index', 'X').l('Elements', 'add_index', 'X').m('rename_index_list', 'Transfers', 'T')
    c.m('index_list', 'Nope').m('all_index_lists').mget('index_lists')
    c.m('index_list_users', 'Contaminants').m('delete_index_list', 'Radionuclides')
    c.m('delete_index_list', 'Contaminants')
    c.m('add_parameter', 'ByComp', 1, index_lists=['Compartments'])
    c.b('ByComp', 'set_value', 5, at='Soil')
    c.m('rename_block', 'Soil', 'Topsoil').b('ByComp', 'overrides')
    c.m('add_expression', 'Reads', 'ByComp[Topsoil] * 2', index_lists=[])
    c.m('rename_block', 'Topsoil', 'Ground').bget('Reads', 'equation').b('ByComp', 'overrides')
    c.m('add_compartment', 'Lake')
    c.m('rename_block', 'Lake', 'Pond')
    c.m('delete_block', 'Ground')
    c.m('delete_blocks', ['Ground', 'Reads']).b('ByComp', 'overrides')
    c.m('check')
    return c


def case_systems():
    c = two_boxes('systems')
    c.m('add_system', 'Near').m('add_system', 'Near').m('add_system').m('add_system', None, 'Near')
    c.m('move_block', 'Soil', 'Near')
    c.bget('Near.Soil_Well', 'system').bget('Near.Soil', 'qualified_name')
    c.m('move_block', 'Near.Soil', 'Nope').m('move_block', 'Near.Soil', 'Near')
    c.m('rename_system', 'Near', 'Nearfield').bget('Nearfield.Soil_Well', 'source')
    c.m('rename_system', '', 'X').m('rename_system', 'Nope', 'X').m('rename_system', 'Nearfield', 'A.B')
    c.m('rename_system', 'Nearfield', 'Near1').m('rename_system', 'Nearfield', 'Well')
    c.m('rename_system', 'Nearfield', 'exp').m('rename_system', 'Nearfield', 'Nearfield')
    c.m('add_transport', 'Tube', number='10')
    c.m('add_transfer', 'Nearfield.Soil', 'Tube').m('add_transfer', 'Tube', 'Well')
    c.mget('transports').mget('systems')
    c.m('add_transport_operation', 'Tube', operation='sum').m('add_transport_operation', 'Tube', 'Avg', argument='range')
    c.m('add_transport_operation', 'Tube', operation='max').m('add_transport_operation', 'Tube', argument='half')
    c.m('add_transport_operation', 'Nearfield')
    c.bget('Tube.Begin', 'transport_role').bget('Tube.N', 'transport_role').bget('Tube.TransportOp', 'operation')
    c.m('add_system', 'Inner', 'Tube').m('move_system', 'Nearfield', 'Tube')
    c.m('delete_block', 'Tube.Begin').m('move_block', 'Tube.End', '')
    c.m('set_dimensions', 'Nearfield.Soil', ['Contaminants'])
    c.bget('Tube.Begin', 'index_lists').bget('Tube.TransportOp', 'index_lists')
    c.m('delete_system', 'Tube').m('delete_system', 'Tube', 'erase')
    c.m('delete_system', 'Tube', contents='delete')
    c.mget('systems').mget('transports')
    c.m('set_system_enabled', 'Nearfield', False).bget('Nearfield.Soil', 'effectively_enabled')
    c.m('system_enabled', 'Nearfield').m('system_enabled', 'Nearfield.Deep').m('system_enabled', '')
    c.m('set_system_enabled', 'Nope', False).m('set_system_enabled', '', False)
    c.m('add_system', 'Deep', 'Nearfield').m('add_system', 'Deeper', 'Nearfield.Deep')
    c.m('add_compartment', 'Rock', system='Nearfield.Deep').m('add_parameter', 'q', 2, system='Nearfield.Deep.Deeper')
    c.m('add_expression', 'E', 'Rock * q', system='Nearfield.Deep')
    c.m('add_expression', 'Deeper', 'Rock', system='Nearfield.Deep')
    c.m('add_expression', 'Top', 'Nearfield.Deep.Rock + Nearfield.Deep.Deeper.q')
    c.m('set_system_position', 'Nearfield.Deep', (100.5, 40)).m('system_position', 'Nearfield.Deep')
    c.m('set_system_position', 'Nope', (1, 2)).m('system_position', 'Nearfield')
    c.m('add_shape', 'rect', 10, 10, system='Nearfield.Deep').m('add_shape', 'sticky', system='Nearfield.Deep.Deeper')
    c.m('move_system', 'Nearfield.Deep', '')
    c.mget('systems').bget('Top', 'equation').bget('Deep.E', 'equation').mget('shapes')
    c.m('move_system', 'Deep', 'Deep').m('move_system', 'Deep', 'Deep.Deeper').m('move_system', '', 'Deep')
    c.m('move_system', 'Deep', 'Nearfield').m('move_system', 'Nearfield.Deep', 'Nearfield')
    c.m('set_system_enabled', 'Nearfield.Deep.Deeper', False)
    c.m('rename_system', 'Nearfield', 'Far').mget('systems').bget('Top', 'equation')
    c.m('add_system', 'Deep').m('add_compartment', 'Rock', system='Deep')
    c.m('delete_system', 'Far.Deep').mget('systems').bget('Top', 'equation').mget('shapes')
    c.m('delete_system', 'Far').mget('systems')
    c.m('delete_system', '').m('delete_system', 'Nope')
    c.m('add_system', 'S1').m('add_compartment', 'X', system='S1').m('add_expression', 'Y', 'X * 2', system='S1')
    c.m('delete_system', 'S1', contents='delete').m('delete_blocks', ['S1.X', 'S1.Y']).m('delete_system', 'S1', 'delete')
    c.mget('systems').m('state_count').m('check')
    return c


def case_shadowing():
    c = Case('shadowing', data={
        'name': 'Shadows', 'nuclides': [],
        'systems': ['Sub', 'Other'],
        'compartments': [{'name': 'C1', 'initial': '1'}, {'name': 'C2', 'initial': '0'},
                         {'name': 'Inside', 'system': 'Sub', 'initial': '0'}],
        'parameters': [{'name': 'p12', 'value': 0.1}, {'name': 'k', 'value': 1, 'system': 'Sub'},
                       {'name': 'k', 'value': 2}],
        'expressions': [{'name': 'E', 'equation': 'C1 * p12 + k', 'system': 'Sub'},
                        {'name': 'Top', 'equation': 'C1 + Sub.k + k'}],
        'transfers': [{'name': 'T1', 'from': 'C1', 'to': 'C2', 'rate': 'p12'}],
    })
    c.m('move_block', 'T1', 'Sub')
    c.m('add_parameter', 'p12', system='Sub')
    c.m('move_block', 'C1', 'Sub')
    c.m('move_block', 'k', 'Other').bget('Top', 'equation').bget('Sub.E', 'equation')
    c.m('move_block', 'Sub.k', '')
    c.m('rename_block', 'Sub.k', 'kk').bget('Sub.E', 'equation').bget('Top', 'equation')
    c.m('rename_block', 'Sub.kk', 'p12')
    c.m('rename_block', 'C1', 'Inside').m('rename_block', 'Sub.Inside', 'C1')
    c.m('rename_block', 'C2', 'Sub.C2').m('rename_block', 'C2', 'C2')
    c.m('move_blocks', ['C2', 'Nothing'], 'Sub')
    c.m('move_blocks', ['C2', 'p12'], 'Other')
    c.m('move_blocks', ['Other.C2', 'Sub.T1'], '')
    c.m('references_to', 'Other.p12').m('references_graph')
    c.m('check')
    return c


def case_connections():
    c = two_boxes('connections')
    c.m('add_compartment', 'Lake').m('add_compartment', 'Sea')
    c.m('set_connection_end', 'Soil_Well', 'to', 'Lake')
    c.m('set_connection_end', 'Soil_Well', 'from', None).bget('Soil_Well', 'multiply_by_donor')
    c.m('set_connection_end', 'Soil_Well', 'to', None)
    c.m('set_connection_end', 'Soil_Well', 'from', 'Lake')
    c.m('set_connection_end', 'Soil_Well', 'from', 'Well').bget('Soil_Well', 'multiply_by_donor')
    c.m('set_connection_end', 'Soil_Well', 'side', 'Well').m('set_connection_end', 'k', 'to', 'Well')
    c.m('set_connection_end', 'Soil_Well', 'to', 'k')
    c.m('add_inflow', 'Soil', '1e3', name='Rain').m('set_connection_end', 'Rain', 'from', 'Well')
    c.m('set_connection_end', 'Rain', 'to', None).m('set_connection_end', 'Rain', 'to', 'Lake')
    c.bget('Rain', 'target').bget('Rain', 'source').bget('Rain', 'unit')
    c.m('add_system', 'Sub').m('add_compartment', 'Deep', system='Sub')
    c.m('set_connection_end', 'Soil_Well', 'from', 'Sub.Deep')
    c.bget('Sub.Soil_Well', 'system').bget('Sub.Soil_Well', 'source')
    c.m('set_connection_end', 'Rain', 'to', 'Sub.Deep').bget('Sub.Rain', 'system')
    c.bset('Sub.Soil_Well', 'target', 'Sea').bset('Sub.Soil_Well', 'source', 'Soil').bget('Soil_Well', 'target')
    c.bset('Soil_Well', 'sum_extra_indices', True).bget('Soil_Well', 'sum_extra_indices')
    c.bset('Soil_Well', 'sum_extra_indices', 0)
    c.bset('Soil_Well', 'line_color', '#f00').bset('Soil_Well', 'line_color', None).bset('Soil_Well', 'line_color', 5)
    c.bset('Soil_Well', 'line_width', 30).bset('Soil_Well', 'line_width', 0.1).bset('Soil_Well', 'line_width', '2')
    c.bset('Soil_Well', 'line_width', 0).bset('Soil_Well', 'line_width', 'thick').bset('Soil_Well', 'line_width', '')
    c.bset('Soil_Well', 'dash', 'dotted').bset('Soil_Well', 'dash', 'wavy').bget('Soil_Well', 'dash')
    c.bset('Soil_Well', 'dash', 'solid').bget('Soil_Well', 'dash')
    c.bset('Soil_Well', 'multiply_by_donor', False).bget('Soil_Well', 'unit')
    c.m('add_transfer', 'Soil', 'Lake', '0.1', name='Fixed', multiply_by_donor=False, sum_extra_indices=True,
        comment='abs', symbol='F', index_lists=['Contaminants'])
    c.m('add_transfer', 'Soil', 'Lake', system='Sub')
    c.m('add_transfer', None, 'Lake', '3')
    c.m('add_inflow', 'Lake', 2, index_lists=[], system='Sub', sum_extra_indices=1, comment='c', symbol='s')
    c.m('set_dimensions', 'Lake', ['Radionuclides', 'Contaminants'])
    c.m('add_index_list', 'Grid', ['g1', 'g2'])
    c.m('set_dimensions', 'Lake', ['Grid'])
    c.bget('Fixed', 'index_lists').bget('Soil_Lake', 'index_lists')
    c.m('add_transfer', 'Soil', 'Lake', name='Union')
    c.bget('Union', 'index_lists')
    c.m('settle').m('check')
    return c


def case_availability():
    c = two_boxes('availability')
    c.m('add_parameter', 'Lim', 5).m('add_parameter', 'Cap', 7)
    c.b('Soil_Well', 'set_availability', 'limit', limit='Lim * 2').bget('Soil_Well', 'availability')
    c.b('Soil_Well', 'set_availability', 'langmuir', top='Cap', bottom=3)
    c.b('Soil_Well', 'set_availability', 'shared_langmuir', top='Cap', bottom='Lim', over='Elements', basis='moles',
        unavailable=True)
    c.b('Soil_Well', 'set_availability', 'shared_limit', limit='Lim', basis='atoms')
    c.b('Soil_Well', 'set_availability', 'shared_limit', limit='Lim', over='', basis='amount')
    c.b('Soil_Well', 'set_availability', 'limit').b('Soil_Well', 'set_availability', 'langmuir', top='1')
    c.b('Soil_Well', 'set_availability', 'cap', limit='1')
    c.m('rename_block', 'Lim', 'Solubility').bget('Soil_Well', 'availability')
    c.m('delete_block', 'Solubility').m('references_to', 'Solubility')
    c.b('Soil_Well', 'set_availability', None).m('delete_block', 'Solubility')
    return c


def case_reductions():
    c = two_boxes('reductions')
    c.m('add_index_list', 'Object', ['Lake', 'Mire'])
    c.m('set_dimensions', 'Soil', ['Radionuclides', 'Object'])
    c.m('add_index_reduction', 'ByObject', 'Soil', over='Radionuclides', unit='Bq')
    c.m('add_index_reduction', 'ByNuclide', 'Soil', over='Object', operation='max')
    c.m('add_index_reduction', 'Bad', 'Soil', over='Contaminants')
    c.m('add_index_reduction', 'P95', 'Soil', operation='percentile', percentile=95)
    c.bget('ByObject', 'index_lists').bget('ByObject', 'over').bget('ByNuclide', 'over').bget('P95', 'percentile')
    c.b('ByObject', 'reduce_over', 'Object').bget('ByObject', 'index_lists').b('ByObject', 'reduce_over', 'Nope')
    c.m('set_reduction_target', 'ByObject', 'Well').bget('ByObject', 'index_lists')
    c.m('set_reduction_target', 'ByObject', 'Soil', over='Object').bget('ByObject', 'index_lists')
    c.m('set_reduction_target', 'ByObject', None).bget('ByObject', 'target').bget('ByObject', 'over')
    c.m('set_reduction_target', 'k', 'Soil').m('set_reduction_target', 'ByObject', 'Nope')
    c.bset('ByObject', 'target', 'Soil').bget('ByObject', 'index_lists')
    c.bset('ByNuclide', 'operation', 'median').bset('ByNuclide', 'operation', 'mean')
    c.bset('P95', 'percentile', '50').bset('P95', 'percentile', 'x').bget('P95', 'percentile')
    c.m('set_dimensions', 'Soil', ['Object'])
    c.bget('ByObject', 'index_lists').bget('ByNuclide', 'index_lists').bget('P95', 'index_lists')
    c.m('add_block_reduction', 'Sum2', ['Soil', 'Well', 'k'])
    c.bget('Sum2', 'index_lists').bget('Sum2', 'targets')
    c.m('set_aggregate_targets', 'Sum2', ['Well']).bget('Sum2', 'index_lists')
    c.bset('Sum2', 'targets', ['Soil', 'k']).bget('Sum2', 'index_lists')
    c.m('set_aggregate_targets', 'Soil', ['Well']).m('set_aggregate_targets', 'Sum2', ['Nope'])
    c.bset('Sum2', 'operation', 'product').bset('Sum2', 'operation', 'percentile')
    c.m('set_dimensions', 'Well', ['Object', 'Radionuclides'])
    c.bget('Sum2', 'index_lists')
    c.m('rename_block', 'Soil', 'Ground').bget('ByObject', 'target').bget('Sum2', 'targets')
    c.m('add_system', 'Sub').m('move_block', 'ByNuclide', 'Sub').bget('Sub.ByNuclide', 'target')
    c.m('move_block', 'Sum2', 'Sub').bget('Sub.Sum2', 'targets')
    c.m('add_compartment', 'Ground', system='Sub')
    c.m('move_block', 'Sub.Sum2', '')
    c.m('references_to', 'Ground').m('delete_block', 'Ground').m('check')
    return c


def case_functions():
    c = two_boxes('functions')
    c.m('add_function', 'f', ['x', 'y'], 'x * y + k', unit='Bq', comment='mult')
    c.m('add_expression', 'E', 'f(Soil, 2) + f(Well, k)')
    c.m('set_function_parameters', 'f', ['a', 'b']).bget('f', 'parameters')
    c.m('set_function_parameters', 'f', ['k']).m('set_function_parameters', 'f', ['a', 'a'])
    c.m('set_function_parameters', 'E', ['a']).bset('f', 'parameters', ['x', 'Soil'])
    c.bset('f', 'parameters', ['x', 'y']).bset('f', 'equation', 'x * y + k')
    c.m('rename_block', 'k', 'rate').bget('f', 'equation').bget('E', 'equation')
    c.m('add_parameter', 'x', 3)
    c.m('rename_block', 'x', 'xx').bget('f', 'equation')
    c.m('rename_block', 'f', 'g').bget('E', 'equation')
    c.m('add_system', 'Sub').m('move_block', 'g', 'Sub').bget('E', 'equation')
    c.bget('Sub.g', 'index_lists').bset('Sub.g', 'equation', None).m('check')
    c.m('delete_block', 'Sub.g').m('delete_blocks', ['Sub.g', 'E']).m('check')
    return c


def case_raw_access():
    c = two_boxes('raw-access')
    c.bitem('Soil', 'name', 'X').bitem('Soil', 'system', 'X')
    c.bitem('Soil', 'initial', 7).bitem('Soil', 'custom', [1, 2]).bitem('Soil', 'entries', [])
    c.bitem('Soil', 'kind', 'weird').bitem('Soil', 'qualified_name', 'q').bitem('Soil', 'abstol', 'x')
    c.bitem('Soil', 'value', '9').bitem('Soil', 'index_lists', ['Contaminants'])
    c.bitem('Soil_Well', 'source', 'Well').bitem('Soil_Well', 'from', 'Well').bitem('Soil_Well', 'from', 'Soil')
    c.b('Soil', 'get', 'custom').b('Soil', 'get', 'nothing', 5).b('Soil', 'keys').b('Soil', 'to_dict')
    c.bset('Soil', 'enabled', False).bget('Soil', 'enabled').bset('Soil', 'enabled', 1).bget('Soil', 'enabled')
    c.bset('Soil', 'color', '#123').bset('Soil', 'color', '').bset('Soil', 'color', 0)
    c.bset('Soil', 'shape', 'hexagon').bget('Soil', 'shape').bset('Soil', 'shape', 'rounded').bget('Soil', 'shape')
    c.bset('Soil', 'shape', 'star').bset('k', 'shape', 'hexagon').bset('k', 'shape', 'rect').bset('k', 'shape', None)
    c.bset('Soil', 'symbol', 'S<sub>1</sub>').bset('Soil', 'comment', 42).bset('Soil', 'unit', None)
    c.bget('Soil', 'unit').bget('Soil', 'symbol').bget('Soil', 'comment')
    c.bset('Soil', 'position', (100, 50.4)).bget('Soil', 'position').bset('Soil', 'position', [3.5, -2.5])
    c.bget('Soil', 'position').bset('Soil', 'size', (400, 10)).bget('Soil', 'size').bset('Soil', 'size', (1000, 500))
    c.bset('Soil', 'size', None).bget('Soil', 'size').bset('Soil', 'position', None).bget('Soil', 'position')
    c.bset('Well', 'size', (100, 100)).bget('Well', 'position')
    c.bset('Soil', 'position', (1, 2))
    c.m('rename_block', 'Soil', 'Topsoil').bget('Topsoil', 'position')
    c.mget('layout')
    return c


def case_review():
    c = two_boxes('review')
    c.mset('review_tracking', True).mget('review_tracking')
    c.m('record_review', 'k', by='me', reviewer='you', at='2026-01-01T00:00:00.000Z')
    c.m('record_review', 'Soil_Well', at='2026-01-01T00:00:00.000Z')
    c.m('record_review', 'Soil', 'review', comment=' look ', at='2026-01-02T00:00:00.000Z')
    c.m('record_review', 'Well', locked=True, at='2026-01-03T00:00:00.000Z')
    c.m('review_status')
    c.bset('k', 'value', 0.06).m('review_status')
    c.bset('k', 'position', (5, 5)).bset('k', 'comment', 'not reviewed').m('review_status')
    c.m('review_stamp', Ref('Soil')).m('review_stamp', Ref('Soil_Well')).m('review_stamp', Ref('k'))
    c.m('clear_review', 'Soil').m('review_status').m('clear_review', 'Nope')
    c.mset('review_tracking', False).mget('review_tracking')
    return c


def case_view_shapes_derived():
    c = two_boxes('view-shapes-derived')
    c.vset('show_parameters', True).vget('show_parameters').vset('connection_label', 'bold')
    c.vget('chart_time_scale').vget('chart_value_scale')
    c.v('set', chart_time_scale='linear', chart_value_scale='linear').vset('chart_time_scale', 'loglog')
    c.v('set', show_influences=True).v('set', show_influences='some').v('set', custom_thing=1).v('to_dict')
    c.vset('show_influences', 'all')
    c.m('add_shape', 'sticky', 10, 20, text='Look here')
    c.sh('sh1', 'update', fill='pink').sh('sh1', 'update', fill=' blue ', line='none', text='  ', dash='dashed')
    c.sh('sh1', 'update', text_bold=True, flip_x=1, text_italic=0, text_font='mono', text_align='right')
    c.sh('sh1', 'update', dash='wavy').sh('sh1', 'update', text_font='comic').sh('sh1', 'update', text_align='top')
    c.sh('sh1', 'update', gizmo=1).sh('sh1', 'update', x=5, line_width=4, text_size=12, text='Hi')
    c.m('add_shape', 'rect', 1.5, 2.5, 30, 40, fill='green', line='red')
    c.m('add_shape', '').m('add_shape', 'rect', system='Nope').m('add_shape', 'ellipse', fill='pink')
    c.m('add_system', 'Sub').sh('sh2', 'move_to', 'Sub').sh('sh2', 'move_to', 'Nope').mget('shapes')
    c.sh('sh2', 'move_to', '').sh('sh1', 'delete').mget('shapes').m('remove_shape', 'sh9')
    c.m('add_shape', 'arrow')
    c.m('add_derived', 'Peak dose', 'max', 'Well [Cs-137]')
    c.m('add_derived', 'Annual', 'period_mean', 'Well [Cs-137]')
    c.m('add_derived', 'Annual', 'period_mean', 'Well [Cs-137]', period=1)
    c.m('add_derived', 'At', 'at_time', 'Well [Cs-137]').m('add_derived', 'At', 'at_time', 'Well [Cs-137]', at='x')
    c.m('add_derived', 'At', 'at_time', 'Well [Cs-137]', at=100)
    c.m('add_derived', '', 'max', 'x').m('add_derived', 'X', 'median', 'x').m('add_derived', 'X', 'max', '  ')
    c.m('add_derived', 'Rate', 'period_rate', 'Soil [Cs-137]', period=-1)
    c.mget('derived').m('remove_derived', 'Annual').m('remove_derived', 'Annual').mget('derived')
    return c


def case_simulation():
    c = two_boxes('simulation')
    c.s('update', end_time=1e6, rtol=1e-6, solver='radau5', max_order=3)
    for attr in ('end_time', 'rtol', 'solver', 'abstol', 'start_time', 'time_unit', 'output_points', 'spacing',
                 'non_negative', 'mass_balance', 'split', 'decay_ceiling', 'switch_times', 'iterations', 'seed',
                 'sampling', 'endpoints', 'output_series'):
        c.sget(attr)
    for key, value in (('rtol', 0), ('solver', 'euler'), ('time_unit', 'week'), ('spacing', 'cubic'),
                       ('output_points', 1), ('max_order', 7), ('max_order', 2.5), ('min_order', '1.5'),
                       ('max_steps', 1000.5), ('max_jac_age', 2.5), ('below_tol_run', '0.5'), ('split', 'maybe'),
                       ('abstol', 'x'), ('rtol', INF), ('start_time', 'x'), ('error_norm', 'l2'),
                       ('matrix', 'cholesky'), ('stagnation_tol', 2), ('max_step', -1), ('iterations', 0),
                       ('decay_ceiling', 0), ('output_points', 200000), ('newton_kappa', 0.5),
                       ('jacobian', 'numeric'), ('bdf', 1), ('norm_control', 0), ('auto_abstol', 'yes')):
        c.s('set', key, value)
    c.s('set', 'min_order', 2.0).s('get', 'min_order').s('set', 'min_order', 4).s('get', 'min_order')
    c.s('set', 'max_order', 2).s('get', 'max_order').s('set', 'min_order', None).s('set', 'max_order', '')
    c.s('set', 'spacing', 'series').oget(0, 'kind').oget(0, 'points')
    c.s('add_output_series', 'times', times=[5, 1, 3]).oget(1, 'times')
    c.s('add_output_series').s('add_output_series', 'linear', 5, 0, 100).s('add_output_series', 'linear', 1)
    c.s('add_output_series', 'cubic').s('add_output_series', 'log', None, 'a')
    c.oset(2, 'points', 7.5).oset(2, 'points', 1).oset(3, 'start', '').oset(3, 'end', '50').oset(3, 'end', 'x')
    c.oset(1, 'times', [9, '2', 4.5]).oget(1, 'times').oget(3, 'start').oget(3, 'end').oget(3, 'kind')
    c.s('remove_output_series', 0).s('remove_output_series', 9).s('remove_output_series', -1)
    c.s('remove_output_series', 0).s('remove_output_series', 0).s('remove_output_series', 0)
    c.sget('spacing').sget('output_series')
    c.sset('spacing', 'both').sset('output_points', '17.5').sset('output_points', 2.5)
    c.sset('time_unit', 'day').sset('start_time', '5').sset('end_time', 2e3).sset('seed', 2.5).sset('seed', 3.5)
    c.sset('iterations', '10').sset('sampling', 'sobol').sset('sampling', 'random')
    c.sset('decay_ceiling', 1e6).sset('decay_ceiling', None).sset('switch_times', [10, 'Ev']).sget('switch_times')
    c.sset('switch_times', []).sset('endpoints', ['Well', 'Well', '', 'Soil']).sget('endpoints')
    c.sset('endpoints', None).sset('non_negative', 0).sget('non_negative').sset('mass_balance', 'yes')
    c.sget('mass_balance').sset('split', 'on').sset('solver', 'ros23')
    c.s('set', 'max_step', 10).s('set', 'jacobian', 'analytic').s('solver_settings').s('to_dict')
    c.s('set', 'custom', {'a': 1}).s('get', 'custom').s('get', 'nothing', 3).s('set', 'custom', None)
    c.s('set', 'output_series', 5).s('update', rtol=1e-4, seed=None)
    c.sset('rtol', 0).sset('start_time', None)
    c.m('state_count')
    c.s('set', 'mass_balance', True).m('state_count')
    return c


def case_check():
    data = {
        'name': 'Broken',
        'nuclides': ['Cs-137', 'Xx-9'],
        'index_lists': [{'name': 'Object', 'indices': ['A', 'A', ' ']},
                        {'name': 'Sub', 'sub_set_of': 'Object', 'indices': ['A', 'Z']},
                        {'name': 'Bad', 'sub_set_of': 'Nope', 'indices': []},
                        {'name': 'Map', 'mapping': {'to': 'Object', 'pairs': [{'from': 'q', 'to': 'A'}]}, 'indices': []},
                        {'name': 'Map2', 'mapping': {'to': 'Nowhere', 'pairs': []}, 'indices': []},
                        {'name': 'Object', 'indices': []}, 'not a list'],
        'chains': [['Cs-137'], ['Cs-137', 'Ba-137m', 1]],
        'systems': ['Sys', 'Bad..Path'],
        'compartments': [{'name': 'A1', 'initial': 'Nothing * 2 +', 'index_lists': ['Radionuclides', 'Missing']},
                         {'name': '1bad', 'initial': '(1', 'index_lists': [], 'system': 'Bad..Path'},
                         {'name': 'Sys', 'initial': '1)', 'index_lists': ['Compartments']},
                         {'name': 'Dup', 'initial': '0', 'index_lists': ['Object', 'Sub'],
                          'entries': [{'index': {'Object': 'Q'}, 'initial': '1'}, {'index': {'Gone': 'x'}},
                                      {'initial': '2'}, 'junk']},
                         {'name': 'Dup', 'initial': '0', 'index_lists': []}],
        'expressions': [{'name': 'Ex', 'equation': 'A1 + $', 'index_lists': []},
                        {'name': 'Cnt', 'equation': 'nonsense', 'transport': 'counter', 'index_lists': []},
                        {'name': 'Clock', 'equation': 'time + pi + exp(1)', 'index_lists': []}],
        'functions': [{'name': 'f', 'parameters': ['x'], 'equation': ''},
                      {'name': 'g', 'parameters': ['x'], 'equation': 'x + y'}],
        'transfers': [{'name': 'T1', 'from': 'A1', 'to': 'Nowhere', 'rate': '1', 'index_lists': []},
                      {'name': 'T2', 'from': None, 'to': None, 'rate': '1', 'index_lists': []},
                      {'name': 'T3', 'from': 'Ex', 'to': 'Pk', 'rate': '1', 'index_lists': [],
                       'entries': [{'index': {}, 'rate': '2', 'multiply_by_donor': False}]}],
        'inflows': [{'name': 'I1', 'to': None, 'rate': '1', 'index_lists': []}],
        'waste_packages': [{'name': 'Pk', 'failure': 'often', 'index_lists': []}],
        'farfields': [{'name': 'Rock', 'kd_f': '-1', 'index_lists': [],
                       'availability': {'scheme': 'odd', 'limit': 'Missing2'}}],
        'index_reductions': [{'name': 'R', 'target': 'Nope', 'operation': 'median', 'index_lists': []}],
        'block_reductions': [{'name': 'G', 'targets': ['A1', 'Nope'], 'index_lists': []}],
        'lookups': [{'name': 'L', 'interpolation': 'cubic', 'points': [[0, 1], [5, 2], [3, 1]], 'index_lists': []},
                    {'name': 'L2', 'points': [[0, 1], ['x', 2], [1, 1]], 'index_lists': []},
                    {'name': 'L3', 'points': [[0, 1], [2, 'y']], 'index_lists': []}],
        'min_maxes': [{'name': 'MM', 'target': 'A1', 'operation': 'median', 'reset_trigger': 'Ex', 'index_lists': []}],
        'running_means': [{'name': 'RM', 'target': 'A1', 'start_trigger': 'Nope', 'index_lists': []}],
        'triggers': [{'name': 'Tr', 'first': 'A1', 'second': '1', 'direction': 'up', 'index_lists': []}],
        'snapshots': [{'name': 'Sn', 'target': 'A1', 'trigger': 'Tr', 'index_lists': []}],
        'events': [{'name': 'Ev', 'timing': 'sometimes', 'at': '1', 'actions': [
            {'kind': 'move', 'from': 'Nope', 'to': 'A1', 'fraction': 'q +'}]}],
        'simulation': {'start_time': 10, 'end_time': 1, 'rtol': -1, 'abstol': 'x', 'solver': 'euler',
                       'spacing': 'cubic', 'time_unit': 'week'},
    }
    c = Case('check', data=data)
    c.m('check')
    good = {'name': 'Checks', 'simulation': {'start_time': 0, 'end_time': 'x'},
            'compartments': [{'name': 'A', 'initial': '1'}]}
    c2 = Case('check-times', data=good)
    c2.m('check')
    return [c, c2]


def case_apps():
    raw = json.loads((EXAMPLES / 'landscape.json').read_text('utf-8'))
    deep = {'id': 'z', 'type': 'chart', 'series': [{'block': 'Water', 'index': {'Object': 'Lake'}}]}
    for i in range(12):
        deep = {'id': f'd{i}', 'type': 'panel' if i % 2 else 'tabs', 'components': [deep],
                'tabs': [{'name': 't', 'components': [deep]}, 'not a tab']}
    raw['app'] = {'pages': [{'name': 'Main', 'components': [
        {'id': 'c1', 'type': 'slider', 'target': {'kind': 'value', 'block': 'Kd', 'index': {'Radionuclides': 'Tc-99'}}},
        {'id': 'c2', 'type': 'slider', 'target': {'kind': 'value', 'block': 'discharge', 'factor': True}},
        {'id': 'c3', 'type': 'switch', 'target': {'kind': 'enabled', 'block': 'Discharge'}},
        {'id': 'c4', 'type': 'chart', 'series': [
            {'block': 'Water', 'index': {'Radionuclides': 'I-129', 'Object': 'Lake'}},
            {'block': 'Regolith held', 'index': {'Object': 'Mire'}},
            {'block': 'Water.x', 'index': {'Object': ['Lake'], 'Radionuclides': 5}},
            {'block': 'Downstream', 'index': {'Compartments': 'Water'}},
        ]},
        {'id': 'p1', 'type': 'panel', 'components': [
            {'id': 't1', 'type': 'tabs', 'tabs': [{'name': 'One', 'components': [
                {'id': 'c5', 'type': 'chart', 'series': [{'block': 'Water', 'index': {'Object': 'Lake'}}]}]}]}]},
        deep, 7, None,
    ]}, 'not a page']}
    c = Case('apps', data=raw)
    c.m('rename_block', 'Water', 'Lakewater').m('rename_block', 'Regolith', 'Soil')
    c.m('rename_index', 'Radionuclides', 'Tc-99', 'Tc99').m('rename_index_list', 'Object', 'Site')
    c.m('add_system', 'Sub').m('move_block', 'Kd', 'Sub').m('rename_system', 'Sub', 'Params')
    c.m('rename_index', 'Site', 'Lake', 'Pond').m('rename_index_list', 'Site', '__proto__')
    c.m('rename_index_list', 'Site', 'constructor')
    return c


def case_put_values():
    c = two_boxes('put-values')
    c.m('add_index_list', 'Object', ['Lake', 'Mire'])
    c.m('add_parameter', 'Kd', 0, index_lists=['Radionuclides', 'Object'])
    c.m('put_values', [{'key': 'k', 'value': 0.5}, {'key': 'Kd[Cs-137][Lake]', 'value': 2},
                       {'key': 'Kd[Sr-90]', 'value': 3}, {'key': 'Nope', 'value': 1}, {'key': 'k', 'value': True},
                       {'key': 'k', 'value': 'x'}, {'key': 'Kd[U-238][Lake]', 'value': 4}, {'key': None, 'value': 1},
                       {'key': 'Soil', 'value': 7}, {'key': 'Kd[Cs-137][Lake][x]', 'value': 1e-7}])
    return c


def case_model_from_dict():
    """A file with the older spellings, opened and then edited."""
    raw = {
        'name': 'Old', 'nuclides': ['Cs-137', 'Sr-90'],
        'simulation': {'startTime': 0, 'endTime': 100, 'solver': 'ode15s'},
        'compartments': [
            {'name': 'A', 'initial': {'Cs-137': '5', 'Sr-90': 2}, 'handleDecay': True},
            {'name': 'B', 'default': '3', 'perNuclide': False},
        ],
        'parameters': [{'name': 'k', 'valuesByNuclide': {'Cs-137': 0.1, 'Sr-90': '0.2'}}],
        'transfers': [{'name': 'AB', 'from': 'A', 'to': 'B', 'rate': 'k', 'multiplyByDonor': True}],
        'sources': [{'name': 'In', 'to': 'A', 'rate': '1'}],
        'layout': {'A': {'x': 10, 'y': 20}, 'edge:AB': {'points': []}, 'edge:AB@Sub': {}, 'Gone': {'x': 1}},
    }
    c = Case('older-file', data=raw)
    c.m('rename_block', 'A', 'Alpha').m('rename_block', 'AB', 'Flow').mget('layout')
    c.m('add_system', 'Sub').m('move_block', 'Flow', 'Sub').mget('layout')
    c.m('move_block', 'Alpha', 'Sub').mget('layout').m('move_block', 'Sub.Alpha', '').mget('layout')
    c.m('add_index_list', 'Extra', ['x']).m('delete_block', 'In').m('delete_block', 'B')
    return c


def case_no_chains():
    """A model that states an empty list of decay pairs: no decay chains at all,
    as the application reads `chains: []` -- not the default ones."""
    c = Case('no-chains', data={'name': 'No chains', 'nuclides': ['Sr-90', 'Y-90', 'Cs-137'], 'chains': [],
                                'compartments': [{'name': 'Soil', 'initial': '1'}]})
    c.mget('decay_chains').mget('has_own_chains')
    c.m('add_decay_pair', 'Sr-90', 'Y-90').mget('decay_chains')
    c.m('remove_decay_pair', 'Sr-90', 'Y-90').mget('decay_chains').mget('has_own_chains')
    c.m('add_nuclides', ['Ba-137m']).mget('decay_chains')
    c.m('reset_decay_chains').mget('decay_chains').mget('has_own_chains')
    c.m('set_decay_chains', []).mget('decay_chains').mget('has_own_chains')
    c.m('state_count').m('check')
    return c


MADE_UP = [case_building, case_names_refused, case_per_index, case_two_dimensions, case_distributions,
           case_lookups, case_every_kind, case_farfield, case_waste_and_events, case_decay, case_scenarios,
           case_index_lists, case_systems, case_shadowing, case_connections, case_availability, case_reductions,
           case_functions, case_raw_access, case_review, case_view_shapes_derived, case_simulation, case_check,
           case_apps, case_put_values, case_model_from_dict, case_no_chains]


def case_elements():
    """A stored element list, kept in step as materials come and go."""
    data = {'name': 'Elements', 'index_lists': [
        {'name': 'Contaminants', 'for_contaminants': True, 'indices': ['Cs-137', 'Cs-135']},
        {'name': 'Radionuclides', 'for_nuclides': True, 'sub_set_of': 'Contaminants', 'indices': ['Cs-137', 'Cs-135']},
        {'name': 'Elements', 'for_elements': True, 'indices': ['Cs'],
         'mapping': {'to': 'Contaminants', 'pairs': [{'from': 'Cs', 'to': 'Cs-137'}, {'from': 'Cs', 'to': 'Cs-135'}]}}],
        'compartments': [{'name': 'A', 'initial': '1'}]}
    c = Case('elements', data=data)
    c.m('add_nuclides', ['Sr-90', 'Sr-89']).lget('Elements', 'indices').lget('Elements', 'mapping')
    c.m('add_material', 'Water', 'm3').m('add_material', 'c-14').lget('Elements', 'indices').lget('Elements', 'mapping')
    c.m('remove_material', 'Sr-90').lget('Elements', 'indices').m('remove_material', 'Sr-89').lget('Elements', 'indices')
    c.m('remove_material', 'Cs-137').lget('Elements', 'indices').lget('Elements', 'mapping')
    c.m('rename_index', 'Radionuclides', 'Cs-135', 'Cs135').lget('Elements', 'mapping')
    c.m('rename_index', 'Elements', 'Cs', 'Caesium').lget('Elements', 'mapping')
    c.m('remove_material', 'Cs135').lget('Elements', 'indices').m('remove_material', 'Water')
    c.lget('Elements', 'indices').m('check')
    one = {'name': 'One list',
           'index_lists': [{'name': 'Nuclide', 'for_materials': True, 'indices': ['Cs-137', 'I-129']},
                           {'name': 'Element', 'mapping': {'to': 'Nuclide', 'pairs': []}, 'indices': []}],
           'compartments': [{'name': 'A', 'initial': '1', 'index_lists': ['Nuclide']}]}
    c2 = Case('one-material-list', data=one)
    c2.m('all_index_lists').m('add_nuclides', ['Sr-90']).m('add_material', 'Iron').m('remove_material', 'I-129')
    c2.m('set_index_enabled', 'Radionuclides', 'Cs-137', False).m('index_combinations', ['Radionuclides'])
    c2.m('rename_index_list', 'Elements', 'Elems').m('delete_index_list', 'Elements').m('check')
    return [c, c2]


def case_raw_edits():
    """The model's dictionary written past every check, and the edits that find it so."""
    c = two_boxes('raw-edits')
    c.raw('index_lists', []).m('add_nuclides', ['I-129']).mget('nuclides').mget('materials')
    c.raw('index_lists', []).m('add_material', 'Iron', 'kg').mget('materials')
    c.raw('nuclides', ['Cs-137']).raw('index_lists', []).m('index_combinations', ['Radionuclides', 'Nope'])
    c.m('combination_count', ['Radionuclides'])
    c.m('add_transport', 'Tube').bitem('Tube.End', 'transport', None).m('add_transfer', 'Tube', 'Soil')
    c.bitem('Tube.Begin', 'transport', None).m('add_transfer', 'Soil', 'Tube')
    c.m('add_expression', 'Bad', 'Soil $ 2 + Well[Cs-137]', index_lists=[])
    c.m('rename_block', 'Soil', 'Ground').bget('Bad', 'equation')
    c.m('rename_index', 'Radionuclides', 'Cs-137', 'Cs137').bget('Bad', 'equation')
    c.m('references_to', 'Ground').m('check')
    return c


def case_layout_edges():
    data = {'name': 'Edges', 'systems': ['A', 'A.B', 'C'],
            'compartments': [{'name': 'X', 'system': 'A', 'initial': '1'}, {'name': 'Y', 'system': 'A.B', 'initial': '0'},
                             {'name': 'Z', 'initial': '0'}, {'name': 'X', 'system': 'C', 'initial': '0'}],
            'expressions': [{'name': 'E', 'equation': 'A.X + A.B.Y + Z', 'system': 'C'}],
            'transfers': [{'name': 'T', 'from': 'A.X', 'to': 'A.B.Y', 'rate': '1', 'system': 'A'},
                          {'name': 'U', 'from': 'Z', 'to': 'A.X', 'rate': '1'}],
            'transports': ['C'],
            'layout': {'A': {'x': 1, 'y': 2}, 'A.B': {'x': 3, 'y': 4}, 'A.X': {'x': 5, 'y': 6},
                       'edge:A.T': {'points': [1]}, 'edge:A.T@A.B': {'points': [2]}, 'edge:A.T@A': {'points': [3]},
                       'edge:U@A': {'points': [4]}, 'Z': {'x': 0, 'y': 0}, 'C': {'x': 9, 'y': 9}},
            'disabled_systems': ['A.B', '', None, ' C '],
            'shapes': [{'id': 'sh1', 'figure': 'rect', 'system': 'A.B'}, {'id': 'sh2', 'figure': 'rect', 'system': 'A'},
                       {'id': 'sh3', 'figure': 'line'}, 'junk']}
    c = Case('layout-edges', data=data)
    c.m('system_enabled', 'A.B').m('system_enabled', 'C').m('system_enabled', 'A').mget('layout')
    c.m('rename_system', 'A', 'Q').mget('layout').mget('systems').mget('shapes').bget('C.E', 'equation')
    c.shget('sh1', 'system').shget('sh1', 'figure').shget('sh2', 'fill').shget('sh3', 'system').shget('sh1', 'id')
    c.m('rename_block', 'Q.T', 'T2').mget('layout')
    c.m('move_block', 'Q.T2', '').mget('layout')
    c.m('move_system', 'Q.B', '').mget('layout').mget('systems')
    c.m('add_system', 'B', 'Q').m('move_system', 'Q.B', '').mget('systems')
    c.m('add_compartment', 'X').m('move_block', 'Q.X', '').bget('X1', 'qualified_name').mget('layout')
    c.m('add_system', 'Inner', 'Q').m('add_compartment', 'X', system='Q').m('add_compartment', 'W', system='Q.Inner')
    c.m('add_system', 'Inner').m('set_system_position', 'Q.Inner', (7, 8)).m('set_system_enabled', 'Q', False)
    c.m('delete_system', 'Q').mget('systems').mget('layout').mget('shapes').m('names')
    c.m('set_system_enabled', 'Inner1', False).m('rename_system', 'Inner1', 'Deep').m('delete_system', 'Deep')
    c.m('delete_system', 'C').m('delete_system', 'C', 'delete').mget('transports').m('check')
    return c


def case_numbering():
    data = {'name': 'Numbers', 'systems': ['S', 'S.Inner', 'Inner', 'S.Inner.Deep'],
            'compartments': [{'name': 'X', 'initial': '1'}, {'name': 'X', 'system': 'S', 'initial': '1'},
                             {'name': 'X1', 'initial': '1'}, {'name': 'Y', 'system': 'S.Inner', 'initial': '1'},
                             {'name': 'Y', 'system': 'Inner', 'initial': '1'},
                             {'name': 'Z', 'system': 'S.Inner.Deep', 'initial': '1'}],
            'expressions': [{'name': 'E', 'equation': 'S.X + X + S.Inner.Y + Inner.Y + S.Inner.Deep.Z'},
                            {'name': 'F', 'equation': 'X + Y', 'system': 'S.Inner'}],
            'layout': {'S.Inner': {'x': 1, 'y': 1}, 'S.Inner.Deep': {'x': 2, 'y': 2}, 'S': {'x': 3, 'y': 3}}}
    c = Case('numbering', data=data)
    c.m('move_block', 'S.X', '').bget('E', 'equation')
    c.m('add_compartment', 'Inner', system='S').m('move_system', 'Inner', 'S')
    c.m('add_system', 'Inner2', 'S').m('move_system', 'Inner', 'S').mget('systems').bget('E', 'equation')
    c.m('delete_system', 'S').mget('systems').bget('E', 'equation').m('names').mget('layout')
    c.m('check')
    return c


def case_reduction_entries():
    c = two_boxes('reduction-entries')
    c.m('add_index_list', 'Object', ['Lake', 'Mire'])
    c.m('add_compartment', 'Lakes', index_lists=['Object', 'Radionuclides'])
    c.m('add_index_reduction', 'R', 'Lakes', over='Radionuclides')
    c.b('R', 'set_value', 'Lakes', at='Mire').b('R', 'overrides')
    c.m('add_block_reduction', 'G', ['Soil', 'Well'])
    c.b('G', 'set_value', ['Soil'], at='Cs-137').b('G', 'set_entry', 'Sr-90', targets=['Well', 'Soil'])
    c.m('rename_block', 'Lakes', 'Ponds').b('R', 'overrides')
    c.m('rename_block', 'Soil', 'Ground').b('G', 'overrides')
    c.m('add_system', 'Sub').m('move_block', 'Ground', 'Sub').b('G', 'overrides')
    c.m('references_to', 'Sub.Ground').m('reads', 'G').m('check')
    return c


def case_more_connections():
    c = two_boxes('more-connections')
    c.m('add_farfield', 'Rock').m('add_farfield', 'Rock2').m('set_release', 'Rock', 'Well')
    c.m('add_transfer', 'Soil', None, name='Loose')
    c.m('set_connection_end', 'Loose', 'from', 'Rock')
    c.m('set_connection_end', 'Loose', 'from', 'Rock2').bget('Loose', 'rate').bget('Loose', 'multiply_by_donor')
    c.m('set_release', 'Rock2', 'Soil').m('set_release', 'Rock', None).mget('transfers')
    c.m('add_waste_package', 'Pk').m('add_transfer', 'Pk', 'Soil').m('add_transfer', 'Pk', 'Well')
    c.m('set_release', 'Pk', 'Well').m('set_release', 'Pk', '').m('set_release', 'Soil', 'Well')
    c.m('add_min_max', 'Peak', 'Soil', index_lists=[]).m('add_min_max', 'Peak2', 'Soil', index_lists=['Nope'])
    c.m('add_snapshot', 'Snap', 'Soil', index_lists=['Contaminants'])
    c.bset('Rock', 'n_b', 3).m('state_count').bset('Rock', 'n_b', '').bset('Rock', 'o_b', 1).m('state_count')
    c.bset('Rock', 'method', 'semi-analytical').m('state_count')
    c.d('make_pdf', 'unif', min=1, max=2, pos='3').d('make_pdf', 'unif', min=1, max=2, trmin=5, trmax=5)
    c.d('make_pdf', 'unif', min=1, max=2, pos=True, inorder='')
    c.d('describe', {'kind': 'pg', 'values': None}).d('pdf_problems', {'kind': 'unif', 'params': None})
    c.m('add_derived', 'X', 'at_time', 'Soil', at=INF)
    c.m('check')
    return c


def case_check_shapes():
    data = {'name': 'Odd', 'compartments': 'oops', 'expressions': [5, {'name': 'E', 'equation': '1'}],
            'parameters': [{'name': 'p', 'value': 1, 'index_lists': ['Objects'],
                            'entries': [{'index': {'Objects': 'Lake'}, 'value': 2}]}],
            'index_lists': [{'name': 'Objects', 'indices': [{'name': 'Lake'}, 'Mire']}, 7]}
    c = Case('check-odd-shapes', data=data)
    c.m('check').m('names').m('state_count')
    return c


MADE_UP += [case_elements, case_raw_edits, case_layout_edges, case_numbering, case_reduction_entries,
            case_more_connections, case_check_shapes]


# --- the bundled examples ------------------------------------------------------------------------------------------

def example_cases(path):
    raw = json.loads(path.read_text('utf-8'))
    m = kp.Model(raw)
    stem = path.stem
    names = m.names()
    stored = [l for l in m.index_lists if not l.is_derived]
    out = []

    # What can be read off it, block by block.
    c = Case(f'{stem}-read', data=raw)
    for attr in ('nuclides', 'materials', 'decay_unit', 'decay_chains', 'has_own_chains', 'scenarios', 'scenario',
                 'systems', 'transports', 'review_tracking', 'layout', 'derived', 'shapes', 'index_lists', 'name',
                 'description', 'author', 'created', 'saved', 'simulation', 'view'):
        c.mget(attr)
    c.m('names').m('references_graph').m('state_count').m('check').m('review_status').m('all_index_lists')
    c.m('material_dimension')
    for kind in ('compartment', 'parameter', 'lookup', 'expression', 'transfer', 'farfield', 'waste_package'):
        c.m('blocks', kind).m('default_dimensions', kind)
    for lst in m.all_index_lists():
        for attr in ('indices', 'enabled_indices', 'subset_of', 'mapping', 'is_materials', 'is_nuclides',
                     'is_scenarios', 'is_derived', 'comment'):
            c.lget(lst.name, attr)
        c.l(lst.name, 'users')
        c.m('index_combinations', [lst.name]).m('combination_count', [lst.name])
    for q in names:
        b = m[q]
        c.m('references_to', q).m('reads', q)
        for attr in ('index_lists', 'value', 'unit', 'kind', 'enabled', 'effectively_enabled', 'shape', 'size',
                     'position', 'system', 'name', 'review', 'color', 'comment', 'symbol', 'entries'):
            c.bget(q, attr)
        c.b(q, 'combinations').b(q, 'overrides').b(q, 'value_at')
        combos = b.combinations()
        if combos and b.entry_keys:
            c.b(q, 'value_at', combos[0]).b(q, 'value_at', combos[-1])
        if b.kind in ('transfer', 'inflow'):
            c.m('derived_unit', q)
        if b.kind == 'compartment':
            c.b(q, 'outflows').b(q, 'inflows')
        if b.kind == 'index_reduction':
            c.bget(q, 'over')
        if b.kind in ('farfield', 'waste_package'):
            c.bget(q, 'release')
        c.m('review_stamp', Ref(q))
    out.append(c)

    # Every block renamed, one after the other, and every list and index.
    c = Case(f'{stem}-rename', data=raw)
    for q in names:
        c.m('rename_block', q, kp.names.base_name(q) + 'X')
    for q in names[:3]:
        c.m('rename_block', kp.names.qualify(kp.names.parent_of(q), kp.names.base_name(q) + 'X'), 'exp')
    for lst in stored:
        if lst.indices:
            c.m('rename_index', lst.name, lst.indices[0], f'{lst.indices[0]}_r')
            c.m('rename_index', lst.name, f'{lst.indices[0]}_r', lst.indices[-1])
        c.m('rename_index_list', lst.name, f'{lst.name}2')
    for path in m.systems:
        c.m('rename_system', path, kp.names.base_name(path) + 'S')
    c.m('check').m('state_count')
    out.append(c)

    # Every block moved into a sub-system, and the sub-system moved, renamed and dissolved.
    c = Case(f'{stem}-move', data=raw)
    c.m('add_system', 'Sub').m('add_system', 'Outer')
    for q in names[::2]:
        c.m('move_block', q, 'Sub')
    c.m('move_blocks', names[1::2], 'Sub')
    c.m('move_blocks', names[1::4], 'Outer')
    c.m('move_system', 'Sub', 'Outer').mget('systems')
    c.m('rename_system', 'Outer.Sub', 'Inner').mget('systems')
    c.m('set_system_enabled', 'Outer', False).m('system_enabled', 'Outer.Inner')
    c.m('delete_system', 'Outer').mget('systems').m('check')
    c.m('delete_system', 'Inner').mget('systems').m('check').m('state_count')
    out.append(c)

    # Every block deleted, one after the other (most refused while something reads them), then the rest at once.
    c = Case(f'{stem}-delete', data=raw)
    for q in names:
        c.m('delete_block', q)
    c.m('delete_blocks', list(reversed(names)))
    c.mget('layout').m('check')
    out.append(c)

    # Blocks of every kind added on top, a new dimension, and the per-index values that come with it.
    c = Case(f'{stem}-add', data=raw)
    comps = [q for q in names if m[q].kind == 'compartment']
    first = comps[0] if comps else None
    c.m('add_index_list', 'Extra', ['e1', 'e2'])
    c.m('add_compartment', 'NewC', '1', comment='new').m('add_parameter', 'NewP', 2, index_lists=['Extra'])
    c.b('NewP', 'set_value', 3, at='e2').m('add_expression', 'NewE', 'NewC * NewP[e1]')
    if first:
        c.m('add_transfer', first, 'NewC', 'NewP[e2]').m('add_inflow', first, '1')
        c.m('set_dimensions', first, list(m[first].index_lists) + ['Extra'])
        c.b(first, 'combinations')
        c.m('add_index_reduction', 'NewR', first, over='Extra').m('add_block_reduction', 'NewG', [first, 'NewC'])
        c.m('add_min_max', 'NewM', first).m('add_running_mean', 'NewRM', first).m('add_delay', 'NewD', first, 10)
        c.m('add_trigger', 'NewT', first, 1).m('add_snapshot', 'NewS', first, 'NewT')
        c.m('add_transport', 'Tube').m('add_transfer', first, 'Tube').m('add_transfer', 'Tube', 'NewC')
        c.m('add_transport_operation', 'Tube')
    c.m('add_lookup', 'NewL').m('add_function', 'NewF', ['a'], 'a * 2').m('add_farfield', 'NewFF')
    c.m('add_waste_package', 'NewW').m('add_event', 'NewEv', at='5')
    c.m('add_nuclides', ['Cs-137', 'I-129']).m('add_material', 'Water', 'm3')
    c.m('state_count').m('check')
    if first:
        c.m('set_dimensions', first, [])
        c.bget('NewR', 'index_lists').bget('NewG', 'index_lists')
    c.m('check')
    out.append(c)
    return out


# --- edits drawn at random -----------------------------------------------------------------------------------------

NAMES = ('A', 'B', 'C', 'Soil', 'Well', 'k', 'X1', 'Sub', 'Near', 'Deep', 'q', 'exp', '1bad', 'Lake', 'Tube')


def _spelling(rng, m, q, system):
    """A way of writing a reference to block `q` from `system`: its path, its bare name, or a name that misses."""
    roll = rng.random()
    if roll < 0.45:
        return q
    if roll < 0.9:
        return kp.names.base_name(q)
    return rng.choice(NAMES)


def _equation(rng, m, system):
    names = m.names()
    bits = []
    for _ in range(rng.randint(1, 3)):
        roll = rng.random()
        if names and roll < 0.6:
            q = rng.choice(names)
            ref = _spelling(rng, m, q, system)
            b = m.get(q)
            if b is not None and rng.random() < 0.3 and b.index_lists:
                try:
                    idx = m.index_list(b.index_lists[0]).indices
                except kp.EditError:  # indexed by a list the model no longer has
                    idx = []
                if idx:
                    ref += f'[{rng.choice(idx)}]'
            bits.append(ref)
        elif roll < 0.75:
            bits.append(f'exp(-{rng.randint(1, 9)} * time)')
        else:
            bits.append(rng.choice(('1', '2.5', '1e-3', 'pi')))
    return rng.choice((' + ', ' * ', ' - ')).join(bits)


def random_op(rng, m):
    names = m.names()
    systems = [''] + m.systems
    comps = [q for q in names if m[q].kind == 'compartment']
    lists = [l.name for l in m.all_index_lists()]
    stored = [l for l in m.index_lists]
    q = rng.choice(names) if names else 'Nothing'
    system = rng.choice(systems)
    fresh = rng.choice(NAMES) + rng.choice(('', '', str(rng.randint(1, 3))))
    roll = rng.randrange(52)
    if roll >= 30:
        return more_random_op(rng, m, roll, names, systems, comps, lists, stored, q, system, fresh)
    if roll == 0:
        return ('m', 'rename_block', (q, fresh), {})
    if roll == 1:
        return ('m', 'move_block', (q, system), {})
    if roll == 2:
        return ('m', 'move_blocks', (rng.sample(names, min(len(names), rng.randint(1, 3))), system), {})
    if roll == 3:
        return ('m', 'delete_block', (q,), {})
    if roll == 4:
        return ('m', 'delete_blocks', (rng.sample(names, min(len(names), rng.randint(1, 4))),), {})
    if roll == 5:
        return ('m', 'add_system', (rng.choice((None, fresh)), system), {})
    if roll == 6 and system:
        return ('m', 'rename_system', (system, fresh), {})
    if roll == 7 and system:
        return ('m', 'move_system', (system, rng.choice(systems)), {})
    if roll == 8 and system:
        return ('m', 'delete_system', (system, rng.choice(('move', 'move', 'delete'))), {})
    if roll == 9:
        return ('m', 'add_compartment', (rng.choice((None, fresh)), _equation(rng, m, system)),
                {'system': system})
    if roll == 10:
        return ('m', 'add_expression', (rng.choice((None, fresh)), _equation(rng, m, system)),
                {'system': system, 'index_lists': rng.choice((None, [], rng.sample(lists, min(1, len(lists)))))})
    if roll == 11:
        return ('m', 'add_parameter', (rng.choice((None, fresh)), rng.choice((1, '2.5', 'x'))), {'system': system})
    if roll == 12 and comps:
        src = rng.choice(comps + [None])
        tgt = rng.choice(comps + [None])
        return ('m', 'add_transfer', (src, tgt, _equation(rng, m, system)), {})
    if roll == 13 and comps:
        return ('m', 'add_inflow', (rng.choice(comps), _equation(rng, m, system)), {})
    if roll == 14:
        return ('m', 'add_index_reduction', (rng.choice((None, fresh)), _spelling(rng, m, q, system)),
                {'system': system})
    if roll == 15:
        return ('m', 'add_block_reduction', (rng.choice((None, fresh)),
                                            [_spelling(rng, m, x, system) for x in rng.sample(names, min(2, len(names)))]),
                {'system': system})
    if roll == 16:
        return ('m', 'add_min_max', (rng.choice((None, fresh)), _equation(rng, m, system)), {'system': system})
    if roll == 17:
        transfers = [x for x in names if m[x].kind == 'transfer']
        if transfers:
            return ('m', 'set_connection_end', (rng.choice(transfers), rng.choice(('from', 'to')),
                                                rng.choice(comps + [None])), {})
    if roll == 18:
        dims = rng.sample(lists, min(len(lists), rng.randint(0, 2)))
        return ('m', 'set_dimensions', (q, dims), {})
    if roll == 19:
        parent = rng.choice(stored) if stored else None
        if parent is not None and parent.indices and rng.random() < 0.5:
            return ('m', 'add_index_list', (fresh, rng.sample(parent.indices, 1)), {'subset_of': parent.name})
        return ('m', 'add_index_list', (fresh, rng.sample(['x', 'y', 'z', 'w'], rng.randint(1, 3))), {})
    if roll == 20 and stored:
        lst = rng.choice(stored)
        if lst.indices:
            return ('m', 'rename_index', (lst.name, rng.choice(lst.indices), rng.choice(('r1', 'r2', 'x', 'Cs-137'))), {})
    if roll == 21 and stored:
        lst = rng.choice(stored)
        if lst.indices:
            return ('m', 'remove_index', (lst.name, rng.choice(lst.indices)), {})
    if roll == 22 and stored:
        lst = rng.choice(stored)
        if lst.indices:
            return ('m', 'set_index_enabled', (lst.name, rng.choice(lst.indices), rng.random() < 0.5), {})
    if roll == 23 and stored:
        lst = rng.choice(stored)
        return ('m', 'add_index', (lst.name, rng.choice(('Cs-137', 'I-129', 'n1', 'n2', 'Xx-3'))), {})
    if roll == 24 and stored:
        return ('m', 'rename_index_list', (rng.choice(stored).name, fresh), {})
    if roll == 25 and names:
        b = m[q]
        combos = b.combinations() if b.entry_keys else []
        if combos:
            return ('b', q, 'set_value', (rng.choice(('1', '2', 'k * 2', 3.5)), rng.choice(combos)), {})
    if roll == 26:
        return ('m', 'add_transport', (rng.choice(('Tube', fresh)), rng.choice(systems)), {})
    if roll == 27 and comps:
        return ('m', 'add_trigger', (rng.choice((None, fresh)), _equation(rng, m, system), '1'), {'system': system})
    if roll == 28:
        return ('m', 'add_nuclides', (rng.sample(['Cs-137', 'Sr-90', 'I-129', 'U-238', 'U-234'], 2),), {})
    return ('m', 'references_to', (q,), {}) if names else ('m', 'check', (), {})


def more_random_op(rng, m, roll, names, systems, comps, lists, stored, q, system, fresh):
    """The rest of the API, drawn at random."""
    kinds = {x: m[x].kind for x in names}
    of = lambda kind: [x for x in names if kinds[x] == kind]  # noqa: E731
    if roll == 30:
        return ('m', 'add_scenarios', (rng.sample(['S1', 'S2', 'S3'], rng.randint(1, 3)), fresh), {})
    if roll == 31:
        return ('m=', 'scenario', rng.choice(m.scenarios + ['Nope', None]))
    if roll == 32 and stored:
        lst = rng.choice(stored)
        role = rng.choice(('plain', 'sub_set', 'mapping', 'odd'))
        return ('m', 'set_list_role', (lst.name, role, rng.choice(lists + [None])), {})
    if roll == 33 and stored:
        mapped = [l for l in stored if l.mapping]
        if mapped:
            lst = rng.choice(mapped)
            parent = m.index_list(lst.mapping['to']).indices if lst.mapping.get('to') in lists else ['x']
            return ('m', 'map_index', (lst.name, rng.choice(parent), rng.choice(lst.indices + [None])), {})
    if roll == 34 and stored:
        return ('m', 'delete_index_list', (rng.choice(stored).name,), {})
    if roll == 35 and m.materials:
        return ('m', rng.choice(('remove_material', 'add_material')), (rng.choice(m.materials + ['Water']),), {})
    if roll == 36:
        pool = m.nuclides + ['Xx-1']
        a, b = rng.choice(pool), rng.choice(pool)
        what = rng.choice(('add_decay_pair', 'set_decay_ratio', 'remove_decay_pair'))
        args = (a, b) if what == 'remove_decay_pair' else (a, b, rng.choice((1, 0.5, 2, '0.25')))
        return ('m', what, args, {})
    if roll == 37:
        return ('m', rng.choice(('reset_decay_chains', 'check', 'settle', 'state_count')), (), {})
    if roll == 38:
        params = rng.sample(['x', 'y', 'k', 'Soil', 'exp'], rng.randint(0, 2))
        return ('m', 'add_function', (rng.choice((None, fresh)), params, _equation(rng, m, system)),
                {'system': system})
    if roll == 39:
        return ('m', 'add_farfield', (rng.choice((None, fresh)),), {'system': system, 'tw': rng.choice(('50', 5))})
    if roll == 40:
        releasing = of('farfield') + of('waste_package')
        if releasing:
            return ('m', 'set_release', (rng.choice(releasing), rng.choice(comps + [None, q])), {})
    if roll == 41:
        return ('m', 'add_waste_package', (rng.choice((None, fresh)),),
                {'system': system, 'failure': rng.choice(('never', 'at', 'weibull')), 'fail_at': '10'})
    if roll == 42:
        events = of('event')
        if events and rng.random() < 0.7:
            ev = rng.choice(events)
            if rng.random() < 0.5:
                return ('b', ev, 'add_fail_action', (rng.choice(of('waste_package') + [q]),), {})
            return ('b', ev, 'add_move_action', (rng.choice(comps + [q]), rng.choice(comps + [None])), {})
        return ('m', 'add_event', (rng.choice((None, fresh)),), {'system': system, 'at': '5'})
    if roll == 43 and names:
        b = m[q]
        combos = b.combinations() if b.entry_keys else []
        if combos:
            key = rng.choice(b.entry_keys)
            if rng.random() < 0.5:
                return ('b', q, 'clear_value', (rng.choice(combos), key), {})
            return ('b', q, 'set_entry', (rng.choice(combos),), {key: rng.choice(('1', 'k', 2))})
    if roll == 44:
        flows = of('transfer')
        if flows:
            scheme = rng.choice(('limit', 'langmuir', 'shared_limit', None))
            return ('b', rng.choice(flows), 'set_availability', (scheme,),
                    {'limit': _equation(rng, m, system), 'top': '1', 'bottom': _spelling(rng, m, q, system)})
    if roll == 45 and m.transports:
        return ('m', 'add_transport_operation', (rng.choice(m.transports + ['']),),
                {'operation': rng.choice(('sum', 'mean')), 'argument': rng.choice(('all', 'point', 'range'))})
    if roll == 46:
        what = rng.choice(('add_snapshot', 'add_delay', 'add_running_mean'))
        return ('m', what, (rng.choice((None, fresh)), _equation(rng, m, system)), {'system': system})
    if roll == 47 and system:
        return ('m', 'set_system_enabled', (system, rng.random() < 0.5), {})
    if roll == 48 and names:
        attr, value = rng.choice((('position', (rng.randint(0, 99), 1.5)), ('color', '#abc'), ('shape', 'ellipse'),
                                  ('enabled', False), ('unit', 'Bq'), ('index_lists', rng.sample(lists, min(1, len(lists)))),
                                  ('comment', 'c'), ('size', (200, 50))))
        return ('b=', q, attr, value)
    if roll == 49:
        reductions = of('index_reduction')
        if reductions:
            return ('m', 'set_reduction_target', (rng.choice(reductions), _spelling(rng, m, q, system)), {})
    if roll == 50:
        aggregates = of('block_reduction')
        if aggregates:
            return ('m', 'set_aggregate_targets', (rng.choice(aggregates),
                                                   [_spelling(rng, m, x, system) for x in rng.sample(names, min(2, len(names)))]), {})
    if roll == 51 and m.transports:
        return ('m', rng.choice(('move_system', 'add_system')), (rng.choice(systems), rng.choice(m.transports)), {})
    return ('m', 'reads', (q,), {}) if names else ('m', 'check', (), {})


def fuzz_case(name, seed, n, data=None, new=None):
    rng = random.Random(seed)
    c = Case(name, data=data, new=new)
    m = start_model(c)
    for _ in range(n):
        try:
            op = random_op(rng, m)
        except Exception:  # noqa: BLE001 -- the model is in a state the draw did not foresee
            op = ('m', 'check', (), {})
        try:
            _, call = apply(m, op)
            call()
        except Exception:  # noqa: BLE001 -- a refusal is as good an operation as any
            pass
        c.ops.append(op)
    c.ops.append(('m', 'check', (), {}))
    c.ops.append(('m', 'references_graph', (), {}))
    return c


def fuzz_cases():
    out = []
    base = {'name': 'Fuzz', 'nuclides': ['Cs-137', 'Sr-90'], 'systems': ['Near', 'Near.Deep'],
            'index_lists': [{'name': 'Object', 'indices': ['Lake', 'Mire']}],
            'compartments': [{'name': 'Soil', 'initial': '1'}, {'name': 'Well', 'system': 'Near', 'initial': '0'},
                             {'name': 'A', 'system': 'Near.Deep', 'initial': '0', 'index_lists': ['Object']}],
            'parameters': [{'name': 'k', 'value': 0.1}, {'name': 'k', 'value': 0.2, 'system': 'Near'}],
            'expressions': [{'name': 'E', 'equation': 'Soil * k + Near.Well', 'system': 'Near'},
                            {'name': 'B', 'equation': 'Near.Deep.A[Lake] + k', 'index_lists': []}],
            'transfers': [{'name': 'T', 'from': 'Soil', 'to': 'Near.Well', 'rate': 'k'},
                          {'name': 'U', 'from': 'Near.Well', 'to': 'Near.Deep.A', 'rate': 'k', 'system': 'Near'}]}
    seeds = int(os.environ.get('KOMPARTMENT_EDIT_FUZZ', '40'))
    for seed in range(seeds):
        out.append(fuzz_case(f'fuzz-{seed:02d}', seed, 70, data=base))
    for k, path in enumerate(sorted(EXAMPLES.glob('*.json'))):
        raw = json.loads(path.read_text('utf-8'))
        out.append(fuzz_case(f'fuzz-{path.stem}', 1000 + k, 60, data=raw))
    return out


def all_cases():
    cases = []
    for make in MADE_UP:
        got = make()
        cases.extend(got if isinstance(got, list) else [got])
    for path in sorted(EXAMPLES.glob('*.json')):
        cases.extend(example_cases(path))
    cases.extend(fuzz_cases())
    return cases


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    total = refused = 0
    for case in all_cases():
        rec = run_case(case)
        (out / f'{case.name}.json').write_text(json.dumps(rec, allow_nan=False), 'utf-8')
        total += len(rec['steps'])
        refused += sum(1 for s in rec['steps'] if s['error'])
    print(f'{len(list(out.glob("*.json")))} cases, {total} operations ({refused} refused) written to {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
