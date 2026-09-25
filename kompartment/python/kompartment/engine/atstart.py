"""What a model's equations work out to at the first instant of a run.

A port of ``src/sim/atstart.js`` (the editor's preview) and of running every
scenario of a model. The values at the start are one pass of the same code a
run begins with -- the initial state, then the algebraic slots once -- read
back through the same descriptors the results use, so a value here is the
first row of the run's table for the same block.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .builder import build_system
from .project import Project
from .runner import Results, describe_entry, run

SOURCE = {'state': 'y', 'algebraic': 'X', 'parameter': 'P'}


class ValuesAtStart:
    """``of(name)`` -> what one block and each of its settings comes to at the start."""

    def __init__(self, project: Project, system: Any = None) -> None:
        sys_ = system if system is not None else build_system(project, jacobian=False)
        self.project = project
        self.system = sys_
        self.t0 = float(project.simulation['start_time'])
        y = sys_.initial_state()
        sys_.prime_recorders(self.t0, y)
        X = sys_.evaluate_algebraic(self.t0, y).copy()
        self._rows = {'y': y, 'X': X, 'P': sys_.P}
        self._own: Dict[str, Dict[str, Any]] = {}
        self._fields: Dict[int, Dict[str, Dict[str, Any]]] = {}
        layout = sys_.layout

        def remember(entry: Any, kind: str, where: str) -> None:
            self._own.setdefault(entry.name, {'entry': entry, 'kind': kind, 'where': where})

        def fields_of(block: Any) -> Dict[str, Dict[str, Any]]:
            return self._fields.setdefault(id(block), {}) if block is not None else {}

        for s in layout.states:
            if s.kind == 'waste_package':
                remember(s, 'waste_inventory', 'state')
                continue
            if s.kind == 'event':
                remember(s, 'event', 'state')
                continue
            if s.kind != 'compartment':
                continue
            remember(s, 'compartment', 'state')
            fields_of(s.block)['initial'] = {'entry': s, 'where': 'state'}
        for a in layout.algebraic:
            if not a.get('hidden'):
                remember(a, a.kind, 'algebraic')
            if a.get('value_key'):
                fields_of(a.block)[a.value_key] = {'entry': a, 'where': 'algebraic'}
        for p in layout.parameters:
            remember(p, 'parameter', 'parameter')
            fields_of(p.block)['value'] = {'entry': p, 'where': 'parameter'}
        self._asked: Dict[str, Any] = {}

    @property
    def size(self) -> int:
        return len(self._own)

    def _unit_of_field(self, key: str, derived: str) -> str:
        if key in ('target', 'initial'):
            return derived
        if key == 'delay':
            return self.project.simulation.get('time_unit') or ''
        if key == 'dydt':
            t = self.project.simulation.get('time_unit')
            return (f'{derived}/{t}' if t else derived) if derived else ''
        return ''

    def _read(self, entry: Any, where: str, kind: str, aux: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        out = []
        for d in describe_entry(self.system.layout, entry, kind, SOURCE[where]):
            out.append({'index': d['index'],
                        'label': d['label'].replace(entry.name, aux['owner'], 1) if aux else d['label'],
                        'unit': self._unit_of_field(aux['key'], d['unit']) if aux else d['unit'],
                        'value': float(self._rows[d['source']][d['offset']])})
        return out

    def of(self, name: str) -> Optional[Dict[str, Any]]:
        if name in self._asked:
            return self._asked[name]
        it = self._own.get(name)
        block = it['entry'].block if it else None
        fields = self._fields.get(id(block)) if block is not None else None
        if it is None and not fields:
            self._asked[name] = None
            return None
        out = {'kind': it['kind'] if it else None, 'dims': list(it['entry'].dims) if it else [],
               'own': self._read(it['entry'], it['where'], it['kind']) if it else None, 'fields': {}}
        for key, f in (fields or {}).items():
            aux = {'owner': name, 'key': key} if f['entry'].get('hidden') else None
            out['fields'][key] = self._read(f['entry'], f['where'], it['kind'] if it else key, aux)
        self._asked[name] = out
        return out


def values_at_start(project: Project, system: Any = None) -> ValuesAtStart:
    return ValuesAtStart(project, system)


def run_scenarios(model: Any, scenarios: Optional[Sequence[str]] = None, *, workers: int = 1,
                  **simulation: Any) -> Dict[str, Results]:
    """Runs the model once per scenario (every one, or those named) and returns
    ``{scenario: Results}``. ``workers`` > 1 runs them in parallel processes."""
    if hasattr(model, 'to_dict'):
        raw = model.to_dict()
    elif isinstance(model, Project):
        raw = model.to_json()
    else:
        raw = dict(model)
    if simulation:
        raw['simulation'] = {**(raw.get('simulation') or {}), **simulation}
    names = list(scenarios) if scenarios is not None else Project(raw).scenarios
    if not names:
        raise ValueError('This model has no scenarios: an index list marked as the scenario list, with indices.')
    if workers <= 1 or len(names) == 1:
        return {name: run(Project({**raw, 'scenario': name})) for name in names}
    import concurrent.futures as cf
    with cf.ProcessPoolExecutor(max_workers=min(workers, len(names))) as pool:
        futures = {name: pool.submit(_run_one, {**raw, 'scenario': name}) for name in names}
        out = {}
        for name, fut in futures.items():
            # A system holds compiled code and cannot travel between
            # processes. The solution and what the run left on its system
            # (the recorders' histories) can, and are put on the same model
            # built here: all a Results needs to work every series out.
            solution, state, timing = fut.result()
            project = Project({**raw, 'scenario': name})
            system = build_system(project, jacobian=False)
            system.restore_run_state(state)
            out[name] = Results(project, system, solution, timing)
        return out


def _run_one(raw: Dict[str, Any]) -> Any:
    res = run(Project(raw))
    return {'t': res.t, 'y': res.y, 'stats': res.stats}, res.system.run_state(), res.timing
