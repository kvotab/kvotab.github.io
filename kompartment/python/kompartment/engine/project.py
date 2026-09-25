"""The project a run is built from: a model file read, normalised and checked.

A port of ``Project`` in ``src/domain/project.js``. It takes the model as the
file has it -- or as :class:`kompartment.Model` holds it -- and produces the
typed, validated shape the builder reads: every block with its defaults, its
dimensions and its entries resolved; the index space; the decay model; the
connections' ends qualified; disabled blocks set aside. Anything the
application would refuse to load is refused here with the same message, as a
:class:`ValidationError`.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import numpy as np

from .. import decay as _decay
from ..errors import KompartmentError
from ..jsonio import js_number as number_text
from ..jsonio import js_text
from ..indexlists import (
    clashing_dimensions, clashing_dimensions_why, derive_block_lists, derive_elements, desugar_nuclides,
    list_applies, list_applies_why, shared_dims, summed_dims,
)
from ..keys import COLLECTIONS, migrate_keys
from ..names import NAME_RE, RESERVED, is_valid_path, is_within, qualified_name, resolve_reference, system_paths
from ..simulation import DEFAULTS as DEFAULT_SIMULATION
from ..simulation import TIME_UNITS
from .farfield import FARF_DEFAULTS, FARF_EQUATION_KEYS, FARF_NUCLIDE_KEYS, FARF_STRUCTURE_KEYS
from .farfield import geometry_problem, structure_problem
from .. import jsmath
from .indexspace import IndexError_, IndexSpace

MAX_OUTPUT_POINTS = 100000
SECONDS_PER_YEAR = 365.25 * 24 * 3600
LN2 = math.log(2)
DECAY_UNITS = ('Bq', 'mol')
SPACINGS = ('log', 'linear', 'series', 'solver', 'both')
INTERPOLATIONS = ('linear', 'extrapolate', 'below', 'above', 'nearest')
OPERATIONS = ('sum', 'product', 'min', 'max', 'mean', 'percentile')
AGGREGATE_OPERATIONS = ('sum', 'product', 'min', 'max', 'mean')
EXTREMES = ('max', 'min')
DIRECTIONS = ('rising', 'falling', 'both')
FAILURES = ('never', 'at', 'uniform', 'exponential', 'weibull')
FAILURE_KEYS = {
    'never': (), 'at': ('fail_at',), 'uniform': ('fail_from', 'fail_to'),
    'exponential': ('fail_start', 'fail_rate'), 'weibull': ('fail_start', 'fail_scale', 'fail_shape'),
}
FAILURE_LABEL = {
    'never': 'never', 'at': 'all at one time', 'uniform': 'evenly over a window',
    'exponential': 'at a constant rate', 'weibull': 'Weibull',
}
WASTE_NUCLIDE_KEYS = ('inventory', 'irf', 'degradation_rate')
WASTE_SINGLE_KEYS = ('fail_at', 'fail_from', 'fail_to', 'fail_start', 'fail_rate', 'fail_scale', 'fail_shape')
WASTE_EQUATION_KEYS = WASTE_NUCLIDE_KEYS + WASTE_SINGLE_KEYS
WASTE_LABEL = {
    'inventory': 'Inventory', 'irf': 'Instant release fraction', 'degradation_rate': 'Matrix degradation rate',
    'fail_at': 'Fail at', 'fail_from': 'Failures from', 'fail_to': 'Failures until', 'fail_start': 'Failures start',
    'fail_rate': 'Failure rate', 'fail_scale': 'Weibull scale', 'fail_shape': 'Weibull shape',
}
WASTE_DEFAULTS: Dict[str, Any] = {
    'failure': 'never', 'packages': 1, 'inventory': '0', 'irf': '0', 'degradation_rate': '0',
    'fail_at': '', 'fail_from': '', 'fail_to': '', 'fail_start': '0', 'fail_rate': '', 'fail_scale': '',
    'fail_shape': '1', 'handle_decay': True,
}
TIMINGS = ('at', 'poisson')
ACTIONS = ('fail', 'move')
DIS_EQUATION_KEYS = ('at', 'rate', 'from', 'until')
DIS_DEFAULTS: Dict[str, Any] = {'timing': 'at', 'at': '', 'rate': '', 'from': '', 'until': '', 'sampled': True,
                                'actions': []}
TIMING_KEYS = {'at': ('at',), 'poisson': ('rate', 'from', 'until')}
TRANSPORT_ROLES = {'compartment': ('begin', 'end'), 'expression': ('number', 'counter', 'operation')}

INTERPOLATION_FROM_ECO = {
    'Interpolation-Use End Values': 'linear', 'Interpolation-Extrapolation': 'extrapolate',
    'Use Input Below': 'below', 'Use Input Above': 'above', 'Use Input Nearest': 'nearest',
}
OPERATION_FROM_ECO = {
    'SUM': 'sum', 'PRODUCT': 'product', 'MIN': 'min', 'MAX': 'max', 'MEAN': 'mean', 'PERCENTILE': 'percentile',
    'Sum': 'sum', 'Product': 'product', 'Minimum': 'min', 'Maximum': 'max', 'Mean': 'mean',
    'Percentile': 'percentile',
}
DIRECTION_FROM_ECO = {'RIGHT': 'rising', 'LEFT': 'falling', 'BOTH': 'both'}

VALUE_KEYS: Dict[str, Sequence[str]] = {
    'compartment': ('initial', 'abstol', 'non_negative', 'dydt'),
    'function': ('equation',),
    'transfer': ('rate', 'multiply_by_donor'),
    'expression': ('equation',),
    'parameter': ('value', 'pdf'),
    'inflow': ('rate',),
    'lookup': ('points',),
    'index_reduction': ('target',),
    'block_reduction': ('targets',),
    'min_max': ('target', 'reset_trigger', 'start_trigger', 'stop_trigger'),
    'running_mean': ('target', 'reset_trigger', 'start_trigger', 'stop_trigger'),
    'snapshot': ('target', 'trigger', 'initial'),
    'delay': ('target', 'delay'),
    'trigger': ('first', 'second', 'direction'),
    'farfield': FARF_EQUATION_KEYS,
    'waste_package': WASTE_EQUATION_KEYS,
    'event': DIS_EQUATION_KEYS,
}

BLOCK_COLLECTIONS = (
    'parameters', 'compartments', 'expressions', 'transfers', 'inflows', 'lookups', 'index_reductions',
    'block_reductions', 'functions', 'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers',
    'farfields', 'waste_packages', 'events',
)
KIND_OF = {
    'parameters': 'parameter', 'compartments': 'compartment', 'expressions': 'expression',
    'transfers': 'transfer', 'inflows': 'inflow', 'lookups': 'lookup', 'index_reductions': 'index_reduction',
    'block_reductions': 'block_reduction', 'functions': 'function', 'min_maxes': 'min_max',
    'running_means': 'running_mean', 'snapshots': 'snapshot', 'delays': 'delay', 'triggers': 'trigger',
    'farfields': 'farfield', 'waste_packages': 'waste_package', 'events': 'event',
}

DEFAULTS: Dict[str, Dict[str, Any]] = {
    'compartment': {'initial': '0', 'non_negative': True, 'handle_decay': True, 'color': None, 'unit': 'Bq'},
    'transfer': {'from': None, 'to': None, 'rate': '0', 'multiply_by_donor': True, 'unit': '1/year'},
    'expression': {'equation': '0', 'unit': ''},
    'parameter': {'value': 0, 'unit': ''},
    'inflow': {'to': None, 'rate': '0', 'unit': 'Bq/year'},
    'lookup': {'points': [], 'interpolation': 'linear', 'cyclic': False, 'argument': None, 'unit': ''},
    'index_reduction': {'target': None, 'operation': 'sum', 'percentile': None, 'unit': ''},
    'block_reduction': {'targets': [], 'operation': 'sum', 'unit': ''},
    'function': {'parameters': [], 'equation': '', 'unit': ''},
    'min_max': {'target': '0', 'operation': 'max', 'reset_trigger': None, 'start_trigger': None,
                'stop_trigger': None, 'unit': ''},
    'running_mean': {'target': '0', 'reset_trigger': None, 'start_trigger': None, 'stop_trigger': None, 'unit': ''},
    'snapshot': {'target': '0', 'trigger': None, 'initial': '0', 'unit': ''},
    'delay': {'target': '0', 'delay': '0', 'unit': ''},
    'trigger': {'first': '0', 'second': '0', 'direction': 'rising', 'unit': ''},
    'farfield': {**FARF_DEFAULTS, 'unit': ''},
    'waste_package': {**WASTE_DEFAULTS, 'unit': ''},
    'event': {**DIS_DEFAULTS, 'unit': ''},
}

INDEX_NAME_BAD = re.compile('[\r\n  <>]')


class ValidationError(KompartmentError):
    """A model the application would refuse to load. ``block`` names the block
    the problem is about, when it is about one."""

    def __init__(self, message: str, block: Optional[str] = None) -> None:
        super().__init__(f'{block}: {message}' if block else message)
        self.block = block
        self.problems = [str(self)]


def js_number(v: Any) -> float:
    """``Number(v)``."""
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == '':
        return 0.0
    try:
        return float(s)
    except ValueError:
        if s.lower() in ('infinity', '+infinity'):
            return math.inf
        if s.lower() == '-infinity':
            return -math.inf
        return math.nan


def js_truthy_switch(v: Any, default: bool) -> bool:
    if default:
        return v is not False and v != 'false' and v != 0
    return v is True or v == 'true' or v == 1


def value_at(block: Dict[str, Any], key: str, tuple_by_list: Dict[str, str]) -> Any:
    """The value of ``key`` at one index tuple: the most specific matching entry,
    else the block's own."""
    best = None
    best_score = -1
    for entry in block.get('entries') or []:
        if key not in entry:
            continue
        score = 0
        ok = True
        for list_name, index_name in (entry.get('index') or {}).items():
            if tuple_by_list.get(list_name) != index_name:
                ok = False
                break
            score += 1
        if ok and score > best_score:
            best_score = score
            best = entry[key]
    if best_score >= 0:
        return best
    return block.get(key)


def has_dydt(block: Dict[str, Any]) -> bool:
    def is_set(v: Any) -> bool:
        return isinstance(v, str) and v.strip() != ''
    return is_set(block.get('dydt')) or any(is_set(e.get('dydt')) for e in block.get('entries') or [])


def lam(nuclide: Optional[str], time_unit: str, half_lives: Dict[str, float]) -> float:
    """Decay constant per ``time_unit``: ln 2 over the half-life converted into it."""
    hl = half_lives.get(nuclide) if nuclide is not None else None
    if hl is None or not math.isfinite(hl):
        return 0.0
    return LN2 / (hl / TIME_UNITS[time_unit])


def build_decay_model(names: Sequence[str], time_unit: str, half_lives: Dict[str, float],
                      decay_unit: str, chains: Sequence[Sequence[Any]]) -> Dict[str, Any]:
    """Decay constants and, per nuclide, the parents growing into it with their
    coefficients (``buildDecayModel``)."""
    idx = {n: i for i, n in enumerate(names)}
    lambdas = [lam(n, time_unit, half_lives) for n in names]
    parents: List[List[Dict[str, Any]]] = [[] for _ in names]
    amounts = decay_unit == 'mol'
    for pair in chains:
        parent, daughter, ratio = pair[0], pair[1], pair[2] if len(pair) > 2 else 1
        pi = idx.get(parent)
        di = idx.get(daughter)
        if pi is None or di is None:
            continue
        parents[di].append({'index': pi, 'lambda': lambdas[pi] if amounts else lambdas[di], 'ratio': float(ratio)})
    return {'names': list(names), 'lambdas': lambdas, 'parents': parents}


def _check_index_name(name: Any, list_name: str) -> str:
    text = '' if name is None else str(name)
    if not text.strip():
        raise ValidationError(f"An index of '{list_name}' has no name", list_name)
    if INDEX_NAME_BAD.search(text):
        shown = INDEX_NAME_BAD.sub('?', text)
        raise ValidationError(f"'{shown}' is not a usable index name: an index may not contain a line break or "
                              'angle brackets', list_name)
    return text


def normalise_index_lists(raw_lists: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def shown(v: Any) -> str:
        return INDEX_NAME_BAD.sub('?', str(v))

    for l in raw_lists or []:
        if not isinstance(l, dict) or l.get('derived'):
            continue
        if not NAME_RE.fullmatch(str(l.get('name') or '')):
            raise ValidationError(f"'{shown(l.get('name'))}' is not a valid index list name (letters, digits and "
                                  'underscore; must not start with a digit)', shown(l.get('name')))
        if l['name'] in RESERVED:
            raise ValidationError(f"'{l['name']}' is a reserved name", l['name'])
        seen: Set[str] = set()
        for i in l.get('indices') or []:
            name = _check_index_name(i if isinstance(i, str) else (i or {}).get('name'), l['name'])
            if name in seen:
                raise ValidationError(f"'{name}' appears twice in index list '{l['name']}'. Two indices of the same "
                                      'name are one address for two positions: everything indexed by the list '
                                      'would carry a slot nothing can reach.', l['name'])
            seen.add(name)

    def names_of(l: Dict[str, Any]) -> Set[str]:
        return {i if isinstance(i, str) else (i or {}).get('name') for i in l.get('indices') or []}

    for l in raw_lists or []:
        if not isinstance(l, dict) or l.get('derived') or not isinstance(l.get('mapping'), dict):
            continue
        target = next((x for x in raw_lists if isinstance(x, dict) and x.get('name') == l['mapping'].get('to')), None)
        if target is None:
            continue
        own = names_of(l)
        theirs = names_of(target)
        for pair in l['mapping'].get('pairs') or []:
            if (pair or {}).get('from') not in own:
                raise ValidationError(f"Index list '{l['name']}' maps '{shown((pair or {}).get('from'))}', which is "
                                      'not one of its indices', l['name'])
            if (pair or {}).get('to') not in theirs:
                raise ValidationError(f"Index list '{l['name']}' maps '{pair.get('from')}' onto "
                                      f"'{shown(pair.get('to'))}', which is not an index of '{target['name']}'",
                                      l['name'])
    out = []
    for l in raw_lists or []:
        d: Dict[str, Any] = {'name': l.get('name'), 'for_contaminants': bool(l.get('for_contaminants'))}
        for key in ('for_nuclides', 'for_scenarios', 'for_elements'):
            if l.get(key):
                d[key] = True
        if l.get('sub_set_of'):
            d['sub_set_of'] = l['sub_set_of']
        if l.get('mapping'):
            d['mapping'] = l['mapping']
        if l.get('comment'):
            d['comment'] = l['comment']
        if l.get('derived'):
            d['derived'] = True
        if l.get('auto'):
            d['auto'] = l['auto']
        if l.get('note'):
            d['note'] = l['note']
        idx = []
        for i in l.get('indices') or []:
            if isinstance(i, str):
                idx.append({'name': i, 'enabled': True})
            else:
                e = {'name': i.get('name'), 'enabled': i.get('enabled') is not False}
                if str(i.get('unit') or '').strip():
                    e['unit'] = str(i['unit']).strip()
                idx.append(e)
        d['indices'] = idx
        out.append(d)
    return out


def normalise_series(raw: Any) -> List[Dict[str, Any]]:
    out = []
    for spec in raw if isinstance(raw, list) else []:
        if not isinstance(spec, dict):
            continue
        kind = series_kind_of(spec)
        if kind == 'times':
            times = sorted(v for v in (js_number(x) for x in spec.get('times') or []) if math.isfinite(v))
            if times:
                out.append({'kind': 'times', 'times': times})
            continue
        pts = js_number(spec.get('points', 0))
        points = int(math.floor(pts + 0.5)) if math.isfinite(pts) else 0
        if not (points >= 2):
            continue

        def num(v: Any) -> Optional[float]:
            if v is None or v == '':
                return None
            n = js_number(v)
            return n if math.isfinite(n) else None

        out.append({'kind': kind, 'points': points, 'from': num(spec.get('from')), 'to': num(spec.get('to'))})
    return out


def series_kind_of(spec: Dict[str, Any]) -> str:
    if isinstance(spec.get('times'), list):
        return 'times'
    named = str(spec.get('kind') if spec.get('kind') is not None else spec.get('spacing') or 'log')
    return 'linear' if named == 'linear' else ('times' if named == 'times' else 'log')


def normalise_points(points: Any, block_name: str) -> List[List[Any]]:
    if points is None:
        return []
    if not isinstance(points, list):
        raise ValidationError('Lookup points must be a list of [x, y] pairs', block_name)
    pairs = points
    if (len(points) == 2 and isinstance(points[0], list) and isinstance(points[1], list)
            and len(points[0]) == len(points[1])
            and all(isinstance(v, (int, float, str)) and not isinstance(v, bool) for v in points[0])
            and len(points[0]) != 2):
        pairs = [[x, points[1][i]] for i, x in enumerate(points[0])]
    out = []
    for i, pt in enumerate(pairs):
        if isinstance(pt, list):
            x = pt[0] if len(pt) > 0 else None
            y = pt[1] if len(pt) > 1 else None
            pdf = pt[2] if len(pt) > 2 else None
        elif isinstance(pt, dict):
            x, y, pdf = pt.get('x'), pt.get('y'), pt.get('pdf')
        else:
            x = y = pdf = None
        nx, ny = js_number(x) if x is not None else math.nan, js_number(y) if y is not None else math.nan
        if not math.isfinite(nx) or not math.isfinite(ny):
            raise ValidationError(f'Lookup point {i + 1} is ({js_text(x)}, {js_text(y)}); both parts must be numbers',
                                  block_name)
        out.append([nx, ny, pdf] if pdf else [nx, ny])
    return out


def normalise_targets(targets: Any, block_name: str) -> List[str]:
    if targets is None:
        return []
    if isinstance(targets, str):
        lst: Any = targets.split('+')
    elif isinstance(targets, list):
        lst = targets
    else:
        raise ValidationError('Aggregate targets must be a list of block names', block_name)
    return [str(t).strip() for t in lst if str(t).strip() != '']


def normalise_entry_index(index: Any, material_list_name: Optional[str], dims: Sequence[str]) -> Dict[str, str]:
    if index is None:
        return {}
    if isinstance(index, str):
        lst = dims[0] if len(dims) == 1 else material_list_name
        if not lst:
            raise ValidationError(f"Entry index '{index}' is ambiguous: name the index list explicitly, as "
                                  f'{{ "ListName": "{index}" }}')
        return {lst: index}
    if isinstance(index, list):
        if len(index) != len(dims):
            raise ValidationError(f'Entry index has {len(index)} component(s) but the block has {len(dims)} '
                                  'dimension(s)')
        return {dims[i]: v for i, v in enumerate(index) if v is not None}
    if not isinstance(index, dict):
        raise ValidationError(f"Entry index '{index}' is not an index: write it as a name, a list of names, or an "
                              'object keyed by index list.')
    return dict(index)


def normalise_entries(raw: Dict[str, Any], kind: str, material_list_name: Optional[str],
                      dims: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    keys = VALUE_KEYS[kind]
    for e in raw.get('entries') or []:
        if not isinstance(e, dict):
            continue
        index = normalise_entry_index(e.get('index'), material_list_name, dims)
        values = {k: e[k] for k in keys if k in e}
        if kind == 'lookup' and 'points' in values:
            values['points'] = normalise_points(values['points'], raw.get('name', ''))
        if kind == 'block_reduction' and 'targets' in values:
            values['targets'] = normalise_targets(values['targets'], raw.get('name', ''))
        if 'non_negative' in values:
            v = values['non_negative']
            values['non_negative'] = v is not False and v != 'false' and v != 0
        if kind == 'farfield' and material_list_name and material_list_name in index:
            values = {k: v for k, v in values.items() if k in FARF_NUCLIDE_KEYS}
        if kind == 'waste_package' and material_list_name and material_list_name in index:
            values = {k: v for k, v in values.items() if k in WASTE_NUCLIDE_KEYS}
        out.append({'index': index, **values})
    init = raw.get('initial')
    if kind == 'compartment' and isinstance(init, dict) and material_list_name:
        for nuc, v in init.items():
            out.append({'index': {material_list_name: nuc}, 'initial': str(v)})
    vbn = raw.get('values_by_nuclide')
    if kind == 'parameter' and vbn and material_list_name:
        for nuc, v in vbn.items():
            out.append({'index': {material_list_name: nuc}, 'value': js_number(v)})
    return out


def normalise_actions(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        d: Dict[str, Any] = {'kind': str(a.get('kind') if a.get('kind') is not None else 'move'),
                             'fraction': str(a.get('fraction') if a.get('fraction') is not None else '1')}
        if d['kind'] == 'fail':
            d['block'] = None if a.get('block') is None else str(a['block'])
        else:
            d['from'] = None if a.get('from') is None else str(a['from'])
            d['to'] = None if a.get('to') is None or a.get('to') == '' else str(a['to'])
        out.append(d)
    return out


def summed_dims_why(flux: str, end: str, end_name: str, dims: Sequence[str], size_of: Any = None) -> str:
    named = [f"'{d}'" for d in dims]
    lst = f"{', '.join(named[:-1])} and {named[-1]}" if len(named) > 1 else named[0]
    sizes = [size_of(d) if size_of else None for d in dims]
    count = int(np.prod(sizes)) if all(sizes) else None
    over = f'all {count} of them' if count else 'all of them'
    each = f'each of the {count} of them' if count else 'each of them'
    body = (f": the flux would be added up over {over} and delivered into the one '{end_name}' cell." if end == 'to'
            else f": the flux would be taken out of the one '{end_name}' cell once for {each}.")
    return (f"'{flux}' is indexed by {lst}, which '{end_name}' is not{body} Give both ends the same dimensions, or "
            f"tick \"sum extra indices\" on '{flux}' to ask for that total on purpose.")


class Project:
    """A model, normalised and validated as the application loads one."""

    def __init__(self, raw: Dict[str, Any]) -> None:
        raw = migrate_keys(copy.deepcopy(raw))
        self.name = raw.get('name') if raw.get('name') is not None else 'Untitled project'
        self.description = raw.get('description') or ''
        sim = dict(DEFAULT_SIMULATION)
        sim.update(raw.get('simulation') or {})
        self.simulation = sim
        for key in ('start_time', 'end_time', 'output_points', 'rtol', 'abstol'):
            v = sim.get(key)
            if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)):
                continue
            n = js_number(v)
            if not math.isfinite(n):
                raise ValidationError(f"'{js_text(v)}' is not a number, and {key.replace('_', ' ')} has to be one")
            sim[key] = n
        for key, least, most in (('max_step', 0, math.inf), ('initial_step', 0, math.inf),
                                 ('max_steps', 1, math.inf), ('max_order', 1, 5), ('min_order', 1, 5),
                                 ('newton_kappa', 0, 1), ('max_jac_age', 1, math.inf),
                                 ('below_tol_run', 0, math.inf), ('stagnation_tol', 0, 1)):
            v = sim.get(key)
            if v is None or v == '':
                sim.pop(key, None)
                continue
            n = js_number(v)
            if not math.isfinite(n) or n < least or n > most:
                rng = f'of at least {least}' if most == math.inf else f'between {least} and {most}'
                raise ValidationError(f"'{js_text(v)}' is not a {key.replace('_', ' ')}: a number {rng}")
            sim[key] = n
        if sim.get('min_order') is not None and js_number(sim['min_order']) > js_number(sim.get('max_order', 5)):
            raise ValidationError(f"The lowest order ({js_text(sim['min_order'])}) is above the highest "
                                  f"({js_text(sim.get('max_order', 5))})")
        for key, allowed in (('error_norm', ('rms', 'max')), ('matrix', ('auto', 'refactor', 'sparse', 'dense')),
                             ('jacobian', ('analytic', 'numeric'))):
            v = sim.get(key)
            if v is None or v == '':
                sim.pop(key, None)
                continue
            if v not in allowed:
                raise ValidationError(f"'{v}' is not a {key.replace('_', ' ')} ({', '.join(allowed)})")
        sim['norm_control'] = js_truthy_switch(sim.get('norm_control'), False)
        sim['bdf'] = js_truthy_switch(sim.get('bdf'), False)
        sim['non_negative'] = js_truthy_switch(sim.get('non_negative', True), True)
        sim['mass_balance'] = js_truthy_switch(sim.get('mass_balance'), False)
        sim['auto_abstol'] = js_truthy_switch(sim.get('auto_abstol'), False)
        n = js_number(sim.get('iterations'))
        n = math.floor(n + 0.5) if math.isfinite(n) else n
        sim['iterations'] = int(n) if math.isfinite(n) and n > 0 else 1000
        s = js_number(sim.get('seed'))
        sim['seed'] = int(math.floor(s + 0.5)) if math.isfinite(s) else 1
        if sim.get('sampling') != 'random':
            sim['sampling'] = 'latin'
        if sim.get('time_unit') not in TIME_UNITS:
            raise ValidationError(f"Unknown time unit '{sim.get('time_unit')}'")
        if sim.get('spacing') not in SPACINGS:
            raise ValidationError(f"'{sim.get('spacing')}' is not a way of choosing output times "
                                  f"({', '.join(SPACINGS)})")
        self.output_times = normalise_series(sim.get('output_times'))
        sim['output_times'] = self.output_times
        self.output_mode = 'solver' if sim['spacing'] == 'solver' else ('both' if sim['spacing'] == 'both' else 'grid')
        self.solver_points = self.output_mode != 'grid'

        self.nuclides = list(raw.get('nuclides') or [])
        self.decay_unit = str(raw.get('decay_unit') if raw.get('decay_unit') is not None else 'Bq').strip()
        ceiling = js_number(sim.get('decay_ceiling')) if sim.get('decay_ceiling') is not None else math.nan
        self.decay_ceiling = ceiling if math.isfinite(ceiling) and ceiling > 0 else math.inf
        if self.decay_unit not in DECAY_UNITS:
            raise ValidationError(f"Unknown decay unit '{self.decay_unit}' ({' or '.join(DECAY_UNITS)})")
        self.half_lives_override = dict(raw.get('half_lives') or {})
        self.half_lives: Dict[str, float] = {n: h for n, h in _icrp_half_lives().items()}
        for nuc, v in self.half_lives_override.items():
            if v is None:
                continue
            if re.fullmatch(r'stable|inf(inity)?', str(v).strip(), re.I):
                self.half_lives[nuc] = math.inf
                continue
            years = js_number(v)
            if not math.isfinite(years) or years <= 0:
                raise ValidationError(f"The half-life of '{nuc}' must be a number of years greater than zero, or "
                                      f"'stable' -- '{v}' is neither.", nuc)
            self.half_lives[nuc] = years
        self.chains_override = [list(c) for c in raw['chains']] if raw.get('chains') else None
        self._raw = raw
        for pair in self.chains_override or []:
            parent = pair[0] if len(pair) > 0 else None
            daughter = pair[1] if len(pair) > 1 else None
            named = '[' + ', '.join(_json(x) for x in pair) + ']'
            if not isinstance(parent, str) or not parent.strip() or not isinstance(daughter, str) or not daughter.strip():
                raise ValidationError(f'A decay pair is [parent, daughter, branching]; {named} does not name two '
                                      'nuclides.')
            ratio = pair[2] if len(pair) > 2 else None
            r = 1.0 if len(pair) < 3 else js_number(ratio)
            if not math.isfinite(r) or r <= 0 or r > 1:
                raise ValidationError(f"The branching from '{parent}' to '{daughter}' must be greater than zero and "
                                      f"at most 1; {named} gives {'none' if len(pair) < 3 else _json(ratio)}.")
            if len(pair) < 3:
                pair.append(1)

        declared = desugar_nuclides(raw)
        lists = derive_block_lists(derive_elements(declared), raw)
        self._derived_lists = {l['name'] for l in lists if l.get('derived')}
        self.index_lists = normalise_index_lists(lists)
        try:
            self.index_space = IndexSpace(self.index_lists)
        except IndexError_ as e:
            raise ValidationError(str(e), e.detail) from None
        materials = self.index_space.material_list()
        self.material_list_name = materials.name if materials else None
        nuc = self.index_space.nuclide_list()
        self.nuclide_list_name = nuc.name if nuc else self.material_list_name
        self.chains = self.chains_override or [list(p) for p in _decay.default_chains(self.material_names)]
        if raw.get('scenario') is not None and self.index_space.set_scenario(raw['scenario']) is None:
            sc = self.index_space.scenarios()
            self.index_space.set_scenario(sc[0] if sc else None)
        self.scenario = self.index_space.scenario
        self.scenarios = self.index_space.scenarios()

        self._ends_by_name: Optional[Dict[str, Dict[str, Any]]] = None
        self.blocks: Dict[str, List[Dict[str, Any]]] = {}
        for collection in BLOCK_COLLECTIONS:
            kind = KIND_OF[collection]
            self.blocks[collection] = [self._block(b, kind) for b in raw.get(collection) or [] if isinstance(b, dict)]

        self.disabled: Set[str] = set()
        self.disabled_systems = [str(p).strip() for p in (raw.get('disabled_systems') or []) if p is not None
                                 and str(p).strip()] if isinstance(raw.get('disabled_systems'), list) else []

        def off_by_system(block: Dict[str, Any]) -> Optional[str]:
            home = block.get('system') or ''
            if not home:
                return None
            hits = sorted((p for p in self.disabled_systems if is_within(home, p)), key=len)
            return hits[0] if hits else None

        self.off_reasons: Dict[str, str] = {}
        self.switched_off: Dict[str, List[Dict[str, Any]]] = {}
        for collection in BLOCK_COLLECTIONS:
            kept, off = [], []
            for b in self.blocks[collection]:
                by = None if b.get('enabled') is False else off_by_system(b)
                if b.get('enabled') is False or by:
                    self.disabled.add(b['qname'])
                    off.append(b)
                    if by:
                        self.off_reasons[b['qname']] = f"it is in '{by}', which is disabled"
                else:
                    kept.append(b)
            self.blocks[collection] = kept
            if off:
                self.switched_off[collection] = off
        self.systems = system_paths(raw.get('systems') or [], raw.get('transports') or [],
                                    (b.get('system') or '' for c in COLLECTIONS for b in raw.get(c) or []
                                     if isinstance(b, dict)))
        self.transports = list(dict.fromkeys(
            str(p if p is not None else '').strip() for p in raw.get('transports') or []
            if str(p if p is not None else '').strip())) if isinstance(raw.get('transports'), list) else []
        for p in self.disabled_systems:
            if p not in self.systems:
                raise ValidationError(f"'{p}' is listed as a disabled sub-system, but there is no sub-system of that "
                                      'name', p)
        self._resolve_endpoints()
        self.layout = dict(raw.get('layout') or {})
        self.shapes = copy.deepcopy(raw.get('shapes')) if isinstance(raw.get('shapes'), list) else []
        self.derived = copy.deepcopy(raw.get('derived')) if isinstance(raw.get('derived'), list) else []
        self.view = dict(raw['view']) if raw.get('view') else None
        self.validate()

    def to_json(self) -> Dict[str, Any]:
        """The project as a file holds it (``toJSON``): the blocks that run and
        the ones switched off, normalised."""
        def every(key: str) -> List[Dict[str, Any]]:
            return self.blocks[key] + self.switched_off.get(key, [])

        out: Dict[str, Any] = {
            'name': self.name, 'description': self.description, 'simulation': self.simulation,
            'nuclides': self.nuclides, 'half_lives': self.half_lives_override, 'decay_unit': self.decay_unit,
        }
        if self.chains_override:
            out['chains'] = self.chains_override
        out['index_lists'] = [l for l in self.index_lists if l['name'] not in self._derived_lists]
        if self.scenario:
            out['scenario'] = self.scenario
        for key in ('parameters', 'compartments', 'expressions', 'transfers', 'inflows'):
            out[key] = every(key)
        for key in ('lookups', 'index_reductions', 'block_reductions', 'functions', 'min_maxes', 'running_means',
                    'snapshots', 'delays', 'triggers', 'farfields', 'waste_packages', 'events'):
            present = self.blocks[key] if key in ('index_reductions', 'triggers') else every(key)
            if present:
                out[key] = every(key)
        if self.transports:
            out['transports'] = list(self.transports)
        if self.disabled_systems:
            out['disabled_systems'] = list(dict.fromkeys(self.disabled_systems))
        if self.systems:
            out['systems'] = list(self.systems)
        out['layout'] = self.layout
        if self.shapes:
            out['shapes'] = self.shapes
        if self.derived:
            out['derived'] = self.derived
        if self.view:
            out['view'] = self.view
        return out

    # --- collections by name -------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        blocks = self.__dict__.get('blocks')
        if blocks is not None and name in blocks:
            return blocks[name]
        raise AttributeError(name)

    @property
    def material_names(self) -> List[str]:
        return self.index_space.index_names(self.material_list_name) if self.material_list_name else []

    @property
    def nuclide_names(self) -> List[str]:
        return self.index_space.index_names(self.nuclide_list_name) if self.nuclide_list_name else []

    # --- blocks ---------------------------------------------------------------------

    def _block(self, raw: Dict[str, Any], kind: str) -> Dict[str, Any]:
        base = {**copy.deepcopy(DEFAULTS[kind]), **raw}
        base['kind'] = kind
        role = raw.get('transport') if raw.get('transport') in TRANSPORT_ROLES.get(kind, ()) else None
        if role:
            base['transport'] = role
        else:
            base.pop('transport', None)
        if role == 'counter':
            base['equation'] = '1'
        if role == 'operation':
            base['operation'] = _transport_operation(raw.get('operation')) or 'mean'
            base['argument'] = _transport_argument(raw.get('argument')) or 'all'
        if kind == 'compartment':
            base['non_negative'] = base.get('non_negative') is not False
        if kind in ('transfer', 'inflow'):
            if base.get('sum_extra_indices') is True or base.get('sum_extra_indices') == 'true':
                base['sum_extra_indices'] = True
            else:
                base.pop('sum_extra_indices', None)
        base['comment'] = raw.get('comment') if raw.get('comment') is not None else ''
        if kind == 'lookup':
            interp = raw.get('interpolation')
            base['interpolation'] = 'linear' if interp is None or interp == '' else (
                INTERPOLATION_FROM_ECO.get(str(interp).strip()) or interp)
            base['cyclic'] = bool(raw.get('cyclic'))
            base['argument'] = str(raw['argument']) if raw.get('argument') else None
            base['points'] = normalise_points(raw.get('points'), raw.get('name', ''))
        if kind in ('index_reduction', 'block_reduction'):
            op = raw.get('operation')
            base['operation'] = 'sum' if op is None or op == '' else (OPERATION_FROM_ECO.get(str(op).strip()) or op)
        if kind == 'index_reduction':
            base['target'] = None if raw.get('target') is None else str(raw['target'])
            base['percentile'] = None if raw.get('percentile') is None else js_number(raw['percentile'])
        if kind == 'block_reduction':
            base['targets'] = normalise_targets(raw.get('targets'), raw.get('name', ''))
        if kind == 'function':
            base['parameters'] = [str(p).strip() for p in (raw.get('parameters') if isinstance(raw.get('parameters'),
                                                                                           list) else [])
                                  if p is not None and str(p).strip()]
            base['equation'] = '' if raw.get('equation') is None else str(raw['equation'])
            base['system'] = raw.get('system') or ''
            base['index_lists'] = []
            base['entries'] = []
            base['qname'] = qualified_name(base)
            return base
        if kind == 'min_max':
            op = raw.get('operation')
            base['operation'] = 'max' if op is None or op == '' else (_extreme(op) or op)
        if kind == 'farfield':
            for key in FARF_STRUCTURE_KEYS:
                v = js_number(raw[key] if raw.get(key) is not None else DEFAULTS['farfield'][key])
                base[key] = int(math.floor(v + 0.5)) if math.isfinite(v) else raw.get(key)
            base.pop('to', None)
        if kind == 'waste_package':
            f = raw.get('failure')
            base['failure'] = 'never' if f is None or f == '' else f
            n = js_number(raw.get('packages') if raw.get('packages') is not None else WASTE_DEFAULTS['packages'])
            base['packages'] = int(math.floor(n + 0.5)) if math.isfinite(n) else raw.get('packages')
            v = raw.get('handle_decay')
            base['handle_decay'] = v is not False and v != 'false' and v != 0
            base.pop('to', None)
        if kind == 'event':
            t = raw.get('timing')
            base['timing'] = 'at' if t is None or t == '' else t
            v = raw.get('sampled')
            base['sampled'] = v is not False and v != 'false' and v != 0
            base['actions'] = normalise_actions(raw.get('actions'))
        if kind == 'trigger':
            d = raw.get('direction')
            base['direction'] = 'rising' if d is None or d == '' else (
                DIRECTION_FROM_ECO.get(str(d).strip().upper()) or d)
        base['index_lists'] = self._dimensions_for(raw, kind)
        if kind == 'event':
            base['index_lists'] = []
        unit = raw.get('unit')
        if unit is None and kind in ('transfer', 'inflow'):
            unit = self._derived_unit(base, kind)
        if unit is None and kind == 'compartment':
            unit = self._inventory_unit(base)
        if unit is None and kind in ('farfield', 'waste_package'):
            unit = f"{self.decay_unit}/{self.simulation['time_unit']}"
        if unit is None:
            unit = DEFAULTS[kind].get('unit') or ''
        base['unit'] = unit
        if base.get('transport') in ('number', 'counter'):
            base['unit'] = ''
        base['system'] = raw.get('system') or ''
        base['qname'] = qualified_name(base)
        base['entries'] = normalise_entries(raw, kind, self.nuclide_list_name, base['index_lists'])
        if isinstance(base.get('initial'), dict):
            base['initial'] = '0'
        if kind == 'compartment':
            for holder in [base, *base['entries']]:
                if 'dydt' not in holder:
                    continue
                if holder['dydt'] is None or str(holder['dydt']).strip() == '':
                    del holder['dydt']
                else:
                    holder['dydt'] = str(holder['dydt'])
        value_key = VALUE_KEYS.get(kind, [None])[0]
        if value_key and 'default' in raw and value_key not in raw:
            base[value_key] = raw['default']
        for key in ('values_by_nuclide', 'default', 'per_nuclide'):
            base.pop(key, None)
        return base

    def _derived_unit(self, block: Dict[str, Any], kind: str) -> str:
        t = self.simulation.get('time_unit') or 'year'

        def unit_of(name: Optional[str]) -> str:
            if name is None:
                return ''
            cs = self.blocks.get('compartments', []) if hasattr(self, 'blocks') else []
            c = next((x for x in cs if x['qname'] == name), None) or next((x for x in cs if x['name'] == name), None)
            return str(c.get('unit') or '').strip() if c else ''

        def per(q: str) -> str:
            return f'({q})/{t}' if re.search(r'[/\s]', q) else f'{q}/{t}'

        if kind == 'inflow':
            u = unit_of(block.get('to'))
            return per(u) if u else ''
        if block.get('multiply_by_donor') is not False:
            return f'1/{t}'
        u = unit_of(block.get('from') if block.get('from') is not None else block.get('to'))
        return per(u) if u else ''

    def _inventory_unit(self, base: Dict[str, Any]) -> str:
        dims = base.get('index_lists') or []
        material = next((d for d in dims if (lambda l: bool(l) and (l.get('for_contaminants') or l.get('for_nuclides')
                                                                   or (l.get('sub_set_of') and l.get('sub_set_of') ==
                                                                       self.material_list_name)))(
            next((x for x in self.index_lists if x['name'] == d), None))), None)
        if not material:
            return self.decay_unit
        return self.dimension_unit(material)

    def material_unit(self, name: str) -> str:
        lists = self.index_lists
        catalogue = next((l for l in lists if l.get('for_contaminants')), None)
        own = next((i for i in (catalogue or {}).get('indices') or [] if i.get('name') == name), None)
        stated = str((own or {}).get('unit') or '').strip()
        if stated:
            return stated
        nuclides = next((l for l in lists if l.get('for_nuclides')), None) or catalogue
        if nuclides:
            is_nuclide = any(i.get('name') == name for i in nuclides.get('indices') or [])
        else:
            is_nuclide = name in self.nuclides
        return ('mol' if self.decay_unit == 'mol' else 'Bq') if is_nuclide else ''

    def dimension_unit(self, list_name: str) -> str:
        lists = self.index_lists
        lst = next((l for l in lists if l.get('name') == list_name), None)
        if lst is None:
            return '' if any(l.get('for_contaminants') or l.get('for_nuclides') for l in lists) else (
                'mol' if self.decay_unit == 'mol' else 'Bq')
        one = None
        for i in lst.get('indices') or []:
            if i.get('enabled') is False:
                continue
            u = self.material_unit(i.get('name'))
            if not u:
                return ''
            if one is None:
                one = u
            elif one != u:
                return ''
        return one or ''

    def _endpoint_dims(self, name: Optional[str]) -> Optional[List[str]]:
        if name is None:
            return None
        if self._ends_by_name is None:
            self._ends_by_name = {}
            for key in ('compartments', 'farfields', 'waste_packages'):
                for b in self._raw.get(key) or []:
                    if isinstance(b, dict) and b.get('name'):
                        self._ends_by_name[qualified_name(b)] = b
        ends = self._ends_by_name
        q = resolve_reference(name, '', lambda n: n in ends) or name
        end = ends.get(q)
        if end is None:
            return None
        if isinstance(end.get('index_lists'), list):
            try:
                return IndexSpace.normalise_dims(end['index_lists'])
            except IndexError_ as e:
                raise ValidationError(str(e), end.get('name')) from None
        implied = self.nuclide_list_name if self.nuclide_list_name and self.index_space.size(
            self.nuclide_list_name) else self.material_list_name
        return [implied] if implied and end.get('per_nuclide') is not False else []

    def _dimensions_for(self, raw: Dict[str, Any], kind: str) -> List[str]:
        if kind == 'function':
            return []
        if isinstance(raw.get('index_lists'), list):
            try:
                dims = IndexSpace.normalise_dims(raw['index_lists'])
            except IndexError_ as e:
                raise ValidationError(str(e), raw.get('name')) from None
            for d in dims:
                if not self.index_space.has(d):
                    raise ValidationError(f"Unknown index list '{d}'", raw.get('name'))
                lst = next((l for l in self.index_lists if l['name'] == d), None)
                if not list_applies(lst, kind):
                    raise ValidationError(list_applies_why(lst, kind), raw.get('name'))
            clash = clashing_dimensions(self.index_lists, dims)
            if clash:
                raise ValidationError(clashing_dimensions_why(clash), raw.get('name'))
            return dims
        if kind in ('transfer', 'inflow'):
            shared = shared_dims(self.index_lists, self._endpoint_dims(raw.get('from')),
                                 self._endpoint_dims(raw.get('to')))
            if shared is not None:
                return list(shared['dims'])
        implied = self.nuclide_list_name if self.nuclide_list_name and self.index_space.size(
            self.nuclide_list_name) else self.material_list_name
        if implied and raw.get('per_nuclide') is not False:
            return [implied]
        return []

    def blocks_by_name(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for collection in COLLECTIONS:
            for b in self.blocks.get(collection, []):
                if b['qname'] in out:
                    raise ValidationError(f"Duplicate block name '{b['qname']}'", b['qname'])
                out[b['qname']] = b
        return out

    def all_blocks(self) -> List[Dict[str, Any]]:
        return [b for c in COLLECTIONS for b in self.blocks.get(c, [])]

    # --- connections ----------------------------------------------------------------

    def _resolve_endpoints(self) -> None:
        ends = {b['qname'] for c in ('compartments', 'farfields', 'waste_packages') for b in self.blocks[c]}
        known = ends.__contains__
        for conn in self.blocks['transfers'] + self.blocks['inflows']:
            for end in ('from', 'to'):
                ref = conn.get(end)
                if ref is None:
                    continue
                conn[end] = ref if known(ref) else (resolve_reference(ref, conn.get('system') or '', known) or ref)
        self._follow_disabled_ends()

    def _follow_disabled_ends(self) -> None:
        self.implicitly_disabled = dict(self.off_reasons)
        kept = []
        for t in self.blocks['transfers']:
            if t.get('from') is not None and t['from'] in self.disabled:
                self.implicitly_disabled[t['qname']] = (f"its donor '{t['from']}' is disabled, so there is no "
                                                        'inventory for it to move')
                self.disabled.add(t['qname'])
                continue
            if t.get('to') is not None and t['to'] in self.disabled:
                self.implicitly_disabled[f"{t['qname']}#to"] = (f"it flows into '{t['to']}', which is disabled, so "
                                                                'what it moves leaves the model')
                t['to'] = None
            kept.append(t)
        self.blocks['transfers'] = kept
        kept = []
        for s in self.blocks['inflows']:
            if s.get('to') is not None and s['to'] in self.disabled:
                self.implicitly_disabled[s['qname']] = (f"it flows into '{s['to']}', which is disabled, so there is "
                                                        'nothing for it to feed')
                self.disabled.add(s['qname'])
                continue
            kept.append(s)
        self.blocks['inflows'] = kept

    # --- decay ------------------------------------------------------------------------

    def decay_model(self) -> Dict[str, Any]:
        return self.decay_model_for(self.material_list_name)

    def decay_model_for(self, list_name: Optional[str]) -> Dict[str, Any]:
        names = self.index_space.index_names(list_name) if list_name and self.index_space.has(list_name) else []
        chains = self.chains_override or [list(p) for p in _decay.default_chains(names, self.decay_ceiling)]
        return build_decay_model(names, self.simulation['time_unit'], self.half_lives, self.decay_unit, chains)

    # --- validation -------------------------------------------------------------------

    def validate(self) -> 'Project':
        names: Set[str] = set()
        order = ['parameters', 'compartments', 'expressions', 'transfers', 'inflows', 'lookups', 'index_reductions',
                 'block_reductions', 'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers', 'farfields',
                 'waste_packages', 'events', 'functions']
        everything = [b for c in order for b in self.blocks[c]]
        for b in everything:
            if not b.get('name') or not NAME_RE.fullmatch(str(b['name'])):
                raise ValidationError(f"'{b.get('name')}' is not a valid name (letters, digits and underscore; must "
                                      'not start with a digit)', b.get('name'))
            if b['name'] in RESERVED:
                raise ValidationError(f"'{b['name']}' is a reserved name", b['name'])
            if not is_valid_path(b.get('system')):
                raise ValidationError(f"'{b.get('system')}' is not a valid sub-system path", b['qname'])
            if b['qname'] in self.systems:
                raise ValidationError(f"'{b['qname']}' is both a block and a sub-system, and the two cannot share a "
                                      'name', b['qname'])
            if b['qname'] in names:
                raise ValidationError(f"Duplicate block name '{b['qname']}'"
                                      + (f" in sub-system '{b['system']}'" if b.get('system') else ''), b['qname'])
            names.add(b['qname'])
        for c in self.blocks['compartments']:
            for holder in [c, *c['entries']]:
                if 'abstol' not in holder or holder['abstol'] is None or holder['abstol'] == '':
                    continue
                v = js_number(holder['abstol'])
                if math.isfinite(v) and v > 0:
                    continue
                where = holder.get('index') if holder is not c else None
                at = f" for {', '.join(where.values())}" if where else ''
                raise ValidationError(f"Absolute tolerance{at} must be a number greater than zero "
                                      f"(got {js_text(holder['abstol'])})", c['qname'])
        compartments = {c['qname'] for c in self.blocks['compartments']}
        paths = {b['qname'] for b in self.blocks['farfields'] + self.blocks['waste_packages']}
        releasing: Dict[str, str] = {}
        for t in self.blocks['transfers']:
            if t.get('from') is None or t['from'] not in paths:
                continue
            held = releasing.get(t['from'])
            if held:
                raise ValidationError(f"'{t['from']}' has two releases, '{held}' and '{t['name']}'. A block has one "
                                      '-- for a path the flux out of the far end, for waste packages what leaves '
                                      'them -- and each of these would deliver the whole of it, so the model would '
                                      'release twice what the block let go.', t['name'])
            releasing[t['from']] = t['name']
        for t in self.blocks['transfers']:
            if t.get('from') is not None and t['from'] not in compartments and t['from'] not in paths:
                raise ValidationError(f"Unknown source compartment '{t['from']}'", t['name'])
            if t.get('to') is not None and t['to'] not in compartments and t['to'] not in paths:
                raise ValidationError(f"Unknown target compartment '{t['to']}'", t['name'])
            if t.get('from') is not None and t['from'] in paths:
                if t.get('multiply_by_donor') is not False:
                    raise ValidationError(f"'{t['from']}' is a far-field path, so there is no single donor inventory "
                                          'to multiply by: a release carries the flux out of the path itself.',
                                          t['name'])
                if t.get('to') is not None and t['to'] in paths:
                    raise ValidationError('A release from one far-field path cannot be delivered straight into '
                                          'another: give it a compartment in between.', t['name'])
            if t.get('from') is None and t.get('to') is None:
                raise ValidationError('A transfer must have a source, a target, or both', t['name'])
            if t.get('from') == t.get('to'):
                raise ValidationError(f"Source and target are both '{t.get('from')}'", t['name'])
        for s in self.blocks['inflows']:
            if s.get('to') not in compartments and s.get('to') not in paths:
                raise ValidationError(f"Unknown target compartment '{s.get('to')}'", s['name'])
        holds = {b['qname']: b for b in self.blocks['compartments'] + self.blocks['farfields']
                 + self.blocks['waste_packages']}

        def size_of(name: str) -> Optional[int]:
            return self.index_space.size(name) if self.index_space.has(name) else None

        for flux in self.blocks['transfers'] + self.blocks['inflows']:
            if flux.get('sum_extra_indices'):
                continue
            for end in ('from', 'to'):
                at = holds.get(flux.get(end)) if flux.get(end) is not None else None
                if at is None:
                    continue
                summed = summed_dims(self.index_lists, flux['index_lists'], at['index_lists'])
                if not summed:
                    continue
                raise ValidationError(summed_dims_why(flux['qname'], end, at['qname'], summed, size_of), flux['qname'])
        for p in waste_problems(self):
            raise ValidationError(p['message'], p['name'])
        for p in disruption_problems(self):
            raise ValidationError(p['message'], p['name'])
        root = self.index_space.get(self.material_list_name).root_name if self.material_list_name else None
        for f in self.blocks['farfields'] + self.blocks['waste_packages']:
            problem = (structure_problem(f) or geometry_problem(f)) if f['kind'] == 'farfield' else None
            if problem:
                raise ValidationError(problem, f['qname'])
            chains = [d for d in f['index_lists'] if root and self.index_space.has(d)
                      and not self.index_space.get(d).mapping and self.index_space.get(d).root_name == root]
            if len(chains) > 1:
                what = 'A far-field path runs' if f['kind'] == 'farfield' else 'Waste packages run'
                raise ValidationError(f"{what} one decay chain along one dimension, and '{f['name']}' is indexed by "
                                      f"{len(chains)} of them ({' × '.join(chains)}). A sub-set of the "
                                      'radionuclides is a second set of the same nuclides: pick the one the path '
                                      'carries.', f['qname'])
        for l in self.blocks['lookups']:
            if l['interpolation'] not in INTERPOLATIONS:
                raise ValidationError(f"'{l['interpolation']}' is not an interpolation rule "
                                      f"({', '.join(INTERPOLATIONS)})", l['qname'])
            if l.get('argument') is not None and not NAME_RE.fullmatch(str(l['argument'])):
                raise ValidationError(f"'{l['argument']}' is not a valid argument name", l['qname'])
        for f in self.blocks['functions']:
            seen: Set[str] = set()
            for p in f['parameters']:
                if not NAME_RE.fullmatch(p):
                    raise ValidationError(f"'{p}' is not a valid parameter name (letters, digits and underscore; "
                                          'must not start with a digit)', f['qname'])
                if p in RESERVED:
                    raise ValidationError(f"'{p}' is a reserved name, so it cannot be a parameter", f['qname'])
                if p in seen:
                    raise ValidationError(f"'{p}' is named twice in the parameters of '{f['name']}'", f['qname'])
                seen.add(p)
        for o in self.blocks['index_reductions']:
            if o['operation'] not in OPERATIONS:
                raise ValidationError(f"'{o['operation']}' is not a reduction ({', '.join(OPERATIONS)})", o['qname'])
            if o['operation'] == 'percentile' and not (o.get('percentile') is not None and 0 <= o['percentile'] <= 100):
                raise ValidationError(f"A percentile must be between 0 and 100; '{o.get('percentile')}' is not",
                                      o['qname'])
            if not o.get('target'):
                raise ValidationError('An index operation needs a block to reduce', o['qname'])
        for m in self.blocks['min_maxes']:
            if m['operation'] not in EXTREMES:
                raise ValidationError(f"'{m['operation']}' is not a min/max operation ({', '.join(EXTREMES)})",
                                      m['qname'])
        for e in self.blocks['triggers']:
            if e['direction'] not in DIRECTIONS:
                raise ValidationError(f"'{e['direction']}' is not a crossing direction ({', '.join(DIRECTIONS)})",
                                      e['qname'])
        for a in self.blocks['block_reductions']:
            if a['operation'] not in AGGREGATE_OPERATIONS:
                raise ValidationError(f"'{a['operation']}' is not a reduction an aggregate can do "
                                      f"({', '.join(AGGREGATE_OPERATIONS)})", a['qname'])
            if not a['targets'] and not any(e.get('targets') for e in a['entries']):
                raise ValidationError('An aggregate needs at least one block to reduce', a['qname'])
        unknown = [n for n in self.nuclide_names if self.half_lives.get(n) is None]
        if unknown:
            raise ValidationError(f"No half-life for {', '.join(unknown)}. Set one on the Decay tab -- or type "
                                  '"stable" there for a nuclide that does not decay -- or give it under "half_lives" '
                                  'in the project file.')
        for b in everything:
            for entry in b['entries']:
                for list_name, index_name in (entry.get('index') or {}).items():
                    if not self.index_space.has(list_name):
                        raise ValidationError(f"Entry refers to unknown index list '{list_name}'", b['name'])
                    if list_name not in b['index_lists']:
                        raise ValidationError(f"Entry is keyed by '{list_name}', which '{b['name']}' is not indexed by",
                                              b['name'])
                    if not any(i['name'] == index_name for i in self.index_space.get(list_name).indices):
                        raise ValidationError(f"'{index_name}' is not an index of '{list_name}'", b['name'])
        sim = self.simulation
        start, end = sim['start_time'], sim['end_time']
        if not (end > start):
            raise ValidationError('End time must be greater than start time')
        if sim['spacing'] == 'log' and start < 0:
            raise ValidationError('Logarithmic output needs a non-negative start time')
        points = sim.get('output_points')
        if sim['spacing'] not in ('series', 'both') and not (points is not None and points >= 2):
            raise ValidationError('At least 2 output points are required')
        if points is not None and points > MAX_OUTPUT_POINTS:
            raise ValidationError(f'{points} output points is more than this can report ({MAX_OUTPUT_POINTS}).')
        for key, label in (('rtol', 'Relative'), ('abstol', 'Absolute')):
            v = js_number(sim.get(key))
            if not (v > 0):
                raise ValidationError(f'{label} tolerance must be greater than zero (got {sim.get(key)})')
        return self

    # --- the output grid ---------------------------------------------------------------

    def time_grid(self) -> np.ndarray:
        """The output times: one series over the run, or the combined list of series."""
        from .timeseries import combine_series
        sim = self.simulation
        start, end, points, spacing = sim['start_time'], sim['end_time'], sim.get('output_points'), sim['spacing']
        if spacing == 'series' or (spacing == 'both' and self.output_times):
            return combine_series(self.output_times, start, end)
        n = max(2, int(math.floor(float(points) + 0.5)))
        t = np.zeros(n)
        if spacing in ('log', 'solver', 'both'):
            lo = start if start > 0 else max(end, 1) * 1e-6
            a, b = jsmath.log(lo), jsmath.log(end)
            t[0] = start
            for i in range(1, n):
                t[i] = jsmath.exp(a + ((b - a) * i) / (n - 1))
            t[n - 1] = end
        else:
            for i in range(n):
                t[i] = start + ((end - start) * i) / (n - 1)
        return t


def _json(x: Any) -> str:
    import json
    return json.dumps(x)


def _transport_operation(op: Any) -> Optional[str]:
    v = str(op if op is not None else '').strip().lower()
    if not v:
        return None
    if v in ('sum', 'mean'):
        return v
    if v == 'point':
        return 'sum'
    return None


def _transport_argument(arg: Any) -> Optional[str]:
    v = str(arg if arg is not None else '').strip().lower()
    if not v:
        return None
    return v if v in ('all', 'point', 'range') else None


def _extreme(name: Any) -> Optional[str]:
    s = str(name if name is not None else '').strip().upper()
    return 'min' if s == 'MIN' else ('max' if s == 'MAX' else None)


_ICRP: Optional[Dict[str, float]] = None


def _icrp_half_lives() -> Dict[str, float]:
    global _ICRP
    if _ICRP is None:
        _ICRP = {n: _decay.half_life(n) for n in _decay.known_nuclides()}  # type: ignore[misc]
    return _ICRP


def waste_problems(project: Project) -> List[Dict[str, Any]]:
    out = []
    for b in project.blocks['waste_packages']:
        name = b['qname']
        f = b.get('failure') or 'never'
        if f not in FAILURES:
            out.append({'name': name, 'field': 'failure',
                        'message': f"'{f}' is not a way for packages to fail ({', '.join(FAILURES)})."})
            continue
        for key in FAILURE_KEYS[f]:
            if not str(b.get(key) if b.get(key) is not None else '').strip():
                out.append({'name': name, 'field': key,
                            'message': f'Packages that fail {FAILURE_LABEL[f]} need {WASTE_LABEL[key].lower()}: a '
                                       'number or an equation.'})

        def num(key: str) -> Optional[float]:
            # Number('') is 0, so an empty field reads as 0 here, as in the application.
            v = js_number(str(b.get(key) if b.get(key) is not None else '').strip())
            return v if math.isfinite(v) else None

        if f == 'uniform':
            a, z = num('fail_from'), num('fail_to')
            if a is not None and z is not None and not (z > a):
                out.append({'name': name, 'field': 'fail_to',
                            'message': f'The failures end ({number_text(z)}) before they begin ({number_text(a)}).'})
        if f == 'weibull' and num('fail_shape') is not None and not (num('fail_shape') > 0):  # type: ignore[operator]
            out.append({'name': name, 'field': 'fail_shape', 'message': 'A Weibull shape has to be above 0.'})
        if f == 'weibull' and num('fail_scale') is not None and not (num('fail_scale') > 0):  # type: ignore[operator]
            out.append({'name': name, 'field': 'fail_scale', 'message': 'A Weibull scale has to be above 0.'})
        if f == 'exponential' and num('fail_rate') is not None and num('fail_rate') < 0:  # type: ignore[operator]
            out.append({'name': name, 'field': 'fail_rate', 'message': 'A failure rate cannot be negative.'})
        if b.get('packages') is not None and b.get('packages') != '':
            n = js_number(b['packages'])
            if not (math.isfinite(n) and float(n).is_integer()) or n < 1:
                out.append({'name': name, 'field': 'packages',
                            'message': f"'{b['packages']}' is not a number of packages: a whole number, at least 1."})
        for values, where in [(b, None), *((e, e.get('index')) for e in b.get('entries') or [])]:
            def at(key: str) -> Optional[float]:
                text = str(values.get(key) if values.get(key) is not None else '').strip()
                v = js_number(text)
                return v if text != '' and math.isfinite(v) else None
            cell = f" (at {' · '.join(where.values())})" if where else ''
            irf = at('irf')
            if irf is not None and (irf < 0 or irf > 1):
                out.append({'name': name, 'field': 'irf', 'message': f'The instant release fraction is between 0 and 1{cell}.'})
            d = at('degradation_rate')
            if d is not None and d < 0:
                out.append({'name': name, 'field': 'degradation_rate',
                            'message': f'A degradation rate cannot be negative{cell}.'})
    return out


def disruption_problems(project: Project) -> List[Dict[str, Any]]:
    out = []
    wastes = {w['qname'] for w in project.blocks['waste_packages']}
    compartments = {c['qname'] for c in project.blocks['compartments']}
    for b in project.blocks['events']:
        name = b['qname']
        timing = b.get('timing') or 'at'
        if timing not in TIMINGS:
            out.append({'name': name, 'field': 'timing',
                        'message': f"'{timing}' is not a way for an event to happen ({', '.join(TIMINGS)})."})
            continue
        if timing == 'at' and not str(b.get('at') or '').strip():
            out.append({'name': name, 'field': 'at', 'message': 'An event at a time needs the time: a number or an equation.'})
        if timing == 'poisson' and not str(b.get('rate') or '').strip():
            out.append({'name': name, 'field': 'rate', 'message': 'A random event needs its rate: occurrences per unit time.'})

        def num(text: Any) -> Optional[float]:
            t = str(text if text is not None else '').strip()
            if not t:
                return None
            v = js_number(t)
            return v if math.isfinite(v) else None

        if timing == 'poisson' and num(b.get('rate')) is not None and num(b.get('rate')) < 0:  # type: ignore[operator]
            out.append({'name': name, 'field': 'rate', 'message': 'A rate cannot be negative.'})
        if (timing == 'poisson' and num(b.get('from')) is not None and num(b.get('until')) is not None
                and not (num(b.get('until')) > num(b.get('from')))):  # type: ignore[operator]
            out.append({'name': name, 'field': 'until',
                        'message': f"The window ends ({num(b.get('until'))}) before it opens ({num(b.get('from'))})."})
        for k, a in enumerate(normalise_actions(b.get('actions'))):
            field = f'actions[{k}]'
            if a['kind'] not in ACTIONS:
                out.append({'name': name, 'field': field,
                            'message': f"'{a['kind']}' is not something an event can do ({', '.join(ACTIONS)})."})
                continue
            if a['kind'] == 'fail':
                if not a.get('block'):
                    out.append({'name': name, 'field': field, 'message': 'Which packages fail? Name a waste-package block.'})
                elif a['block'] not in wastes:
                    out.append({'name': name, 'field': field,
                                'message': f"'{a['block']}' is not a set of waste packages, so it has no packages to fail."})
            else:
                if not a.get('from'):
                    out.append({'name': name, 'field': field, 'message': 'Move what? Name a compartment.'})
                elif a['from'] not in compartments:
                    out.append({'name': name, 'field': field,
                                'message': f"'{a['from']}' is not a compartment, so there is nothing to move out of it."})
                if a.get('to') is not None and a['to'] not in compartments:
                    out.append({'name': name, 'field': field,
                                'message': f"'{a['to']}' is not a compartment, so nothing can be moved into it."})
                if a.get('to') is not None and a['to'] == a.get('from'):
                    out.append({'name': name, 'field': field, 'message': f"Moving {a['from']} into itself changes nothing."})
            f = num(a.get('fraction'))
            if f is not None and (f < 0 or f > 1):
                out.append({'name': name, 'field': field, 'message': f'A share is between 0 and 1; {f} is not.'})
    return out
