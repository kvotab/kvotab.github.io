"""Renaming the keys an older project file uses. A port of ``src/domain/keys.js``.

Keys are ``snake_case`` now; files written when they were camelCase, or before
some collections were renamed, still open. The rename matters rather than being
cosmetic: an unknown key is ignored rather than reported, so a stale
``multiplyByDonor: false`` would quietly turn back into the default ``true``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

from .indexlists import rename_built_in_lists, split_material_roles

PROJECT = {'halfLives': 'half_lives', 'indexLists': 'index_lists'}
COLLECTION = {
    'sources': 'inflows',
    'discrete_events': 'triggers',
    'disruptions': 'events',
    'index_operations': 'index_reductions',
    'aggregates': 'block_reductions',
}
INDEX_LIST = {
    'forMaterials': 'for_contaminants',
    'for_materials': 'for_contaminants',
    'forNuclides': 'for_nuclides',
    'subSetOf': 'sub_set_of',
}
SIMULATION = {
    'startTime': 'start_time', 'endTime': 'end_time',
    'outputPoints': 'output_points', 'timeUnit': 'time_unit',
}
SOLVER_IDS = {'ode15s': 'ndf', 'ode15s_bdf': 'bdf', 'ode23s': 'ros23', 'ode45': 'dp45'}
VIEW = {
    'showExpressions': 'show_expressions', 'showParameters': 'show_parameters',
    'showLookups': 'show_lookups', 'showReductions': 'show_reductions',
    'showInfluences': 'show_influences', 'showSinks': 'show_sinks',
    'connectionLabel': 'connection_label',
}
BLOCK = {
    'indexLists': 'index_lists', 'handleDecay': 'handle_decay',
    'multiplyByDonor': 'multiply_by_donor',
    'reset_event': 'reset_trigger', 'start_event': 'start_trigger', 'stop_event': 'stop_trigger',
    'event': 'trigger',
    'resetEvent': 'reset_trigger', 'startEvent': 'start_trigger', 'stopEvent': 'stop_trigger',
    'perNuclide': 'per_nuclide', 'valuesByNuclide': 'values_by_nuclide',
}
ENTRY = {
    'multiplyByDonor': 'multiply_by_donor',
    'reset_event': 'reset_trigger', 'start_event': 'start_trigger', 'stop_event': 'stop_trigger',
    'event': 'trigger',
}

#: Every collection of blocks in a project file.
COLLECTIONS = (
    'compartments', 'expressions', 'parameters', 'lookups', 'index_reductions',
    'block_reductions', 'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers',
    'farfields', 'waste_packages', 'events', 'functions', 'transfers', 'inflows',
)


def _rename(obj: Any, mapping: Dict[str, str]) -> Any:
    """``obj`` with its keys renamed, each where the old one stood.

    Where both spellings are present the new one wins and the old is dropped.
    """
    if not isinstance(obj, dict):
        return obj
    out: Dict[str, Any] = {}
    for k, v in obj.items():
        to = mapping.get(k)
        if to is None:
            out[k] = v
            continue
        if to in obj:
            continue
        out[to] = v
    return out


def _migrate_farfield_targets(raw: Dict[str, Any]) -> Dict[str, Any]:
    """A far-field path's release used to be a ``to`` on the path; it is a
    transfer drawn out of it now."""
    farfields = raw.get('farfields')
    if not isinstance(farfields, list):
        return raw
    moved = []
    kept = []
    for f in farfields:
        to = f.get('to') if isinstance(f, dict) else None
        if not isinstance(f, dict) or to is None or to == '':
            kept.append(f)
            continue
        g = {k: v for k, v in f.items() if k != 'to'}
        kept.append(g)
        name = f.get('name')
        t: Dict[str, Any] = {}
        if f.get('system'):
            t['system'] = f['system']
        t.update({
            'name': f'{name}_release' if name else 'release',
            'from': name,
            'to': str(to),
            'rate': name if name else '0',
            'multiply_by_donor': False,
        })
        moved.append(t)
    if not moved:
        return raw
    out = dict(raw)
    out['farfields'] = kept
    out['transfers'] = list(raw.get('transfers') or []) + moved
    return out


def migrate_keys(raw: Dict[str, Any]) -> Dict[str, Any]:
    """A copy of ``raw`` with every older key renamed to the current one.

    Also moves a far-field path's old ``to`` into a release transfer, renames
    the built-in index lists written under their old names (``Nuclide``,
    ``Element``, ``Materials``), and splits a single material list into the
    catalogue and the radionuclides it carries. Nothing is changed in place.
    """
    if not isinstance(raw, dict):
        return raw
    out = _rename(_rename(copy.deepcopy(raw), PROJECT), COLLECTION)
    if isinstance(out.get('index_lists'), list):
        out['index_lists'] = [_rename(l, INDEX_LIST) for l in out['index_lists']]
    out = split_material_roles(rename_built_in_lists(_migrate_farfield_targets(out)))
    sim = out.get('simulation')
    if isinstance(sim, dict):
        sim = _rename(sim, SIMULATION)
        solver = sim.get('solver')
        if isinstance(solver, str) and solver in SOLVER_IDS:
            sim['solver'] = SOLVER_IDS[solver]
        if sim.get('solver') == 'bdf':
            # The plain BDFs are the NDF with its switch on.
            sim['solver'] = 'ndf'
            sim['bdf'] = True
        out['simulation'] = sim
    if isinstance(out.get('view'), dict):
        out['view'] = _rename(out['view'], VIEW)
    for key in COLLECTIONS:
        blocks = out.get(key)
        if not isinstance(blocks, list):
            continue
        renamed = []
        for b in blocks:
            if not isinstance(b, dict):
                renamed.append(b)
                continue
            nb = _rename(b, BLOCK)
            if isinstance(nb.get('entries'), list):
                nb['entries'] = [_rename(e, ENTRY) for e in nb['entries']]
            renamed.append(nb)
        out[key] = renamed
    return out
