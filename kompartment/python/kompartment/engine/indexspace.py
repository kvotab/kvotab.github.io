"""The index-list model of one project: enabled indices, strides, and the tables
that carry a position from one list into another.

A port of ``IndexSpace`` in ``src/domain/indexlists.js``. The hard part is not
storing values but reading a block of one dimension from inside a block of
another: :meth:`IndexSpace.projection` says, for each dimension of the block
being read, which dimension of the reader supplies its position -- directly,
through a sub-set's or a mapping's table, or pinned to one index -- and the
builder turns that into index arrays.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np


class IndexError_(ValueError):
    """An index-list problem: a list that does not exist, a sub-set holding what
    its root does not, a reference that cannot be carried across."""

    def __init__(self, message: str, detail: Optional[str] = None) -> None:
        super().__init__(message)
        self.detail = detail


def _identity(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.int64)


def _compose(inner: np.ndarray, outer: np.ndarray) -> np.ndarray:
    out = np.full(len(inner), -1, dtype=np.int64)
    ok = inner >= 0
    out[ok] = outer[inner[ok]]
    return out


class IndexList:
    """One list, resolved: its enabled indices, root and translation tables."""

    __slots__ = ('name', 'for_contaminants', 'for_nuclides', 'for_scenarios', 'sub_set_of', 'mapping',
                 'comment', 'auto', 'derived', 'indices', 'enabled', 'size', 'position_of', 'names',
                 'root_name', 'up', 'down', 'is_scenario')

    def __init__(self, raw: Dict[str, Any]) -> None:
        self.name: str = raw['name']
        self.for_contaminants = bool(raw.get('for_contaminants'))
        self.for_nuclides = bool(raw.get('for_nuclides'))
        self.for_scenarios = bool(raw.get('for_scenarios'))
        self.sub_set_of = raw.get('sub_set_of') or None
        self.mapping = raw.get('mapping') or None
        self.comment = raw.get('comment') or ''
        self.auto = raw.get('auto')
        self.derived = bool(raw.get('derived'))
        self.indices = [({'name': i, 'enabled': True} if isinstance(i, str)
                         else {'name': i.get('name'), 'enabled': i.get('enabled') is not False})
                        for i in raw.get('indices') or []]
        self.enabled: List[Dict[str, Any]] = []
        self.size = 0
        self.position_of: Dict[str, int] = {}
        self.names: set = set()
        self.root_name: Optional[str] = None
        self.up = _identity(0)
        self.down = _identity(0)
        self.is_scenario = False

    def enabled_names(self) -> List[str]:
        return [i['name'] for i in self.enabled]


class IndexSpace:
    """Every index list of a project, with what the builder needs precomputed."""

    def __init__(self, raw_lists: Sequence[Dict[str, Any]] = ()) -> None:
        self.lists: Dict[str, IndexList] = {}
        self.order: List[str] = []
        for raw in raw_lists:
            if not raw or not raw.get('name'):
                raise IndexError_('An index list needs a name')
            if raw['name'] in self.lists:
                raise IndexError_(f"Duplicate index list '{raw['name']}'")
            lst = IndexList(raw)
            self.lists[lst.name] = lst
            self.order.append(lst.name)
        self._stride_cache: Dict[tuple, List[int]] = {}
        self._resolve()

    # --- scenarios --------------------------------------------------------------

    def _place_scenarios(self) -> None:
        self.scenario_root: Optional[str] = None
        for name in self.order:
            lst = self.lists[name]
            if lst.for_scenarios and lst.root_name == lst.name:
                self.scenario_root = lst.name
                break
        if not self.scenario_root:
            for name in self.order:
                lst = self.lists[name]
                if lst.for_scenarios:
                    self.scenario_root = lst.root_name
                    break
        for lst in self.lists.values():
            lst.is_scenario = bool(self.scenario_root) and lst.root_name == self.scenario_root
        found = self.scenarios()
        self.scenario: Optional[str] = found[0] if found else None

    def scenarios(self) -> List[str]:
        return self.index_names(self.scenario_root) if self.scenario_root else []

    def is_scenario_dim(self, name: str) -> bool:
        lst = self.lists.get(name)
        return bool(lst and lst.is_scenario)

    def set_scenario(self, name: Optional[str]) -> Optional[str]:
        available = self.scenarios()
        self.scenario = name if name is not None and name in available else None
        return self.scenario

    def scenario_index_in(self, dim: str) -> Optional[str]:
        lst = self.lists.get(dim)
        if not lst or not lst.is_scenario or self.scenario is None:
            return None
        root = self.lists[self.scenario_root]  # type: ignore[index]
        root_pos = root.position_of.get(self.scenario)
        if root_pos is None:
            return None
        pos = root_pos if lst is root else int(lst.down[root_pos])
        return lst.enabled[pos]['name'] if pos >= 0 else None

    def without_scenarios(self, dims: Optional[Sequence[str]]) -> List[str]:
        if not self.scenario_root:
            return list(dims or [])
        return [d for d in dims or [] if not self.is_scenario_dim(d)]

    def pin_scenario(self, dims: Optional[Sequence[str]], tuple_: Dict[str, str]) -> Dict[str, str]:
        if not self.scenario_root or self.scenario is None:
            return tuple_
        out = tuple_
        for d in dims or []:
            if not self.is_scenario_dim(d):
                continue
            name = self.scenario_index_in(d)
            if name is None:
                continue
            if out is tuple_:
                out = dict(tuple_)
            out[d] = name
        return out

    # --- resolution -------------------------------------------------------------

    def _resolve(self) -> None:
        for lst in self.lists.values():
            lst.enabled = [i for i in lst.indices if i['enabled']]
            lst.size = len(lst.enabled)
            lst.position_of = {i['name']: k for k, i in enumerate(lst.enabled)}
            lst.names = {i['name'] for i in lst.indices}
        for lst in self.lists.values():
            if lst.sub_set_of:
                root = self.lists.get(lst.sub_set_of)
                if root is None:
                    raise IndexError_(f"Index list '{lst.name}' is a sub-set of '{lst.sub_set_of}', which does "
                                      'not exist', lst.name)
                if root.sub_set_of:
                    raise IndexError_(f"'{lst.name}' is a sub-set of '{root.name}', which is itself a sub-set. "
                                      'Sub-sets must be taken from a root list.', lst.name)
                for idx in lst.enabled:
                    if idx['name'] not in root.names:
                        raise IndexError_(f"'{idx['name']}' is in the sub-set '{lst.name}' but not in its root "
                                          f"list '{root.name}'", lst.name)
                off = [i for i in lst.enabled if i['name'] not in root.position_of]
                if off:
                    lst.enabled = [i for i in lst.enabled if i['name'] in root.position_of]
                    lst.size = len(lst.enabled)
                    lst.position_of = {i['name']: k for k, i in enumerate(lst.enabled)}
            if lst.mapping:
                target = self.lists.get(lst.mapping.get('to'))
                if target is None:
                    raise IndexError_(f"Index list '{lst.name}' maps to '{lst.mapping.get('to')}', which does not "
                                      'exist', lst.name)
        for lst in self.lists.values():
            self._place(lst)
        self._place_scenarios()

    def _place(self, lst: IndexList, seen: Optional[set] = None) -> IndexList:
        if lst.root_name:
            return lst
        seen = set() if seen is None else seen
        if lst.name in seen:
            raise IndexError_(f"Index list '{lst.name}' is defined in terms of itself", lst.name)
        seen.add(lst.name)
        parent_name = lst.sub_set_of or ((lst.mapping or {}).get('to') if lst.mapping else None)
        if not parent_name:
            lst.root_name = lst.name
            lst.up = _identity(lst.size)
            lst.down = _identity(lst.size)
            return lst
        parent = self._place(self.get(parent_name), seen)
        step_up = self._by_name(lst, parent) if lst.sub_set_of else self._mapped_up(lst, parent)
        step_down = self._by_name(parent, lst) if lst.sub_set_of else self._mapped_down(lst, parent)
        lst.root_name = parent.root_name
        lst.up = _compose(step_up, parent.up)
        lst.down = _compose(parent.down, step_down)
        return lst

    @staticmethod
    def _by_name(a: IndexList, b: IndexList) -> np.ndarray:
        table = np.full(a.size, -1, dtype=np.int64)
        for k, idx in enumerate(a.enabled):
            pos = b.position_of.get(idx['name'])
            table[k] = -1 if pos is None else pos
        return table

    @staticmethod
    def _mapped_up(lst: IndexList, parent: IndexList) -> np.ndarray:
        table = np.full(lst.size, -1, dtype=np.int64)
        for pair in (lst.mapping or {}).get('pairs') or []:
            k = lst.position_of.get(pair.get('from'))
            pos = parent.position_of.get(pair.get('to'))
            if k is None or pos is None or table[k] >= 0:
                continue
            table[k] = pos
        return table

    @staticmethod
    def _mapped_down(lst: IndexList, parent: IndexList) -> np.ndarray:
        table = np.full(parent.size, -1, dtype=np.int64)
        for pair in (lst.mapping or {}).get('pairs') or []:
            k = parent.position_of.get(pair.get('to'))
            pos = lst.position_of.get(pair.get('from'))
            if k is None or pos is None:
                continue
            table[k] = pos
        return table

    def missing_from(self, dim: str, frm: str) -> List[str]:
        rel = self.relate(dim, frm)
        if not rel or rel['kind'] == 'same':
            return []
        names = self.index_names(frm)
        out = [names[k] for k in range(len(rel['table'])) if rel['table'][k] < 0 and k < len(names)]
        return out or ['missing indices']

    # --- queries ---------------------------------------------------------------

    def has(self, name: Optional[str]) -> bool:
        return name in self.lists

    def get(self, name: Optional[str]) -> IndexList:
        lst = self.lists.get(name)  # type: ignore[arg-type]
        if lst is None:
            raise IndexError_(f"No index list named '{name}'")
        return lst

    def names(self) -> List[str]:
        return list(self.order)

    def size(self, name: str) -> int:
        return self.get(name).size

    def index_names(self, name: Optional[str]) -> List[str]:
        return [i['name'] for i in self.get(name).enabled]

    def material_list(self) -> Optional[IndexList]:
        for name in self.order:
            if self.lists[name].for_contaminants:
                return self.lists[name]
        return None

    def nuclide_list(self) -> Optional[IndexList]:
        for name in self.order:
            if self.lists[name].for_nuclides:
                return self.lists[name]
        return None

    def strides(self, dims: Sequence[str]) -> List[int]:
        key = tuple(dims)
        hit = self._stride_cache.get(key)
        if hit is not None:
            return hit
        sizes = [self.size(d) for d in dims]
        strides = [1] * len(dims)
        for i in range(len(dims) - 2, -1, -1):
            strides[i] = strides[i + 1] * sizes[i + 1]
        self._stride_cache[key] = strides
        return strides

    def width(self, dims: Iterable[str]) -> int:
        n = 1
        for d in dims:
            n *= self.size(d)
        return n

    def offset_of(self, dims: Sequence[str], tuple_: Sequence[str]) -> int:
        strides = self.strides(dims)
        off = 0
        for i, d in enumerate(dims):
            pos = self.get(d).position_of.get(tuple_[i])
            if pos is None:
                raise IndexError_(f"'{tuple_[i]}' is not an enabled index of '{d}'")
            off += pos * strides[i]
        return off

    def tuple_at(self, dims: Sequence[str], offset: int) -> List[str]:
        strides = self.strides(dims)
        out = []
        rest = offset
        for i, d in enumerate(dims):
            k = rest // strides[i]
            rest -= k * strides[i]
            out.append(self.get(d).enabled[k]['name'])
        return out

    def positions(self, dims: Sequence[str]) -> List[np.ndarray]:
        """For every offset of a block of these dimensions, its position along
        each dimension: one int array per dimension, in offset order."""
        if not dims:
            return []
        sizes = [self.size(d) for d in dims]
        width = int(np.prod(sizes)) if sizes else 1
        if width == 0:
            return [np.zeros(0, dtype=np.int64) for _ in dims]
        grids = np.indices(sizes).reshape(len(dims), -1)
        return [grids[i].astype(np.int64) for i in range(len(dims))]

    def relate(self, from_list: str, to_list: str) -> Optional[Dict[str, Any]]:
        """How a position in ``to_list`` translates into ``from_list``: ``{'kind':
        'same'}``, ``{'kind': 'map', 'table', 'partial'}``, or ``None`` for
        unrelated lists."""
        if from_list == to_list:
            return {'kind': 'same'}
        a = self.get(from_list)
        b = self.get(to_list)
        if a.root_name != b.root_name:
            return None
        table = np.full(b.size, -1, dtype=np.int64)
        root = b.up
        ok = root >= 0
        table[ok] = a.down[root[ok]]
        return {'kind': 'map', 'table': table, 'partial': bool(np.any(table < 0))}

    def projection(self, source_dims: Sequence[str], target_dims: Sequence[str],
                   fixed_indices: Optional[Dict[str, str]] = None,
                   context: Optional[Dict[str, Optional[str]]] = None) -> List[Dict[str, Any]]:
        """How to read a block of ``target_dims`` from inside one of
        ``source_dims``: one term per target dimension, ``{stride, from}``
        (carried directly), ``{stride, from, table}`` (through a sub-set or
        mapping) or ``{stride, fixed}`` (an explicit index)."""
        fixed_indices = fixed_indices or {}
        context = context or {}
        strides = self.strides(target_dims)
        terms: List[Dict[str, Any]] = []
        for i, dim in enumerate(target_dims):
            stride = strides[i]
            if dim in fixed_indices:
                pos = self.get(dim).position_of.get(fixed_indices[dim])
                if pos is None:
                    raise IndexError_(f"'{fixed_indices[dim]}' is not an enabled index of '{dim}'")
                terms.append({'stride': stride, 'fixed': pos, 'dim': dim})
                continue
            best: Optional[Dict[str, Any]] = None
            for s, sd in enumerate(source_dims):
                rel = self.relate(dim, sd)
                if not rel:
                    continue
                if rel['kind'] == 'same':
                    best = {'stride': stride, 'from': s, 'dim': dim}
                    break
                here = {'stride': stride, 'from': s, 'table': rel['table'], 'dim': dim, 'partial': rel['partial']}
                if best is None or (best.get('partial') and not here['partial']):
                    best = here
            if best is not None and best.get('partial'):
                what = f"'{context['target']}'" if context.get('target') else 'that block'
                where = f"'{context['owner']}'" if context.get('owner') else 'this block'
                frm = source_dims[best['from']]
                first = (self.index_names(dim) or ['index'])[0]
                raise IndexError_(
                    f"{what} is indexed by '{dim}', which does not cover every index of '{frm}' -- so for some "
                    f"of them {where} has no value to read. Give '{dim}' the missing "
                    f"{', '.join(self.missing_from(dim, frm))}, or write an explicit index, as in "
                    f"{context.get('target') or 'block'}[{first}].", dim)
            if best is None:
                what = f"'{context['target']}'" if context.get('target') else 'that block'
                where = f"'{context['owner']}'" if context.get('owner') else 'this block'
                first = (self.index_names(dim) or ['index'])[0]
                raise IndexError_(
                    f"{what} is indexed by '{dim}', which {where} is not indexed by and cannot reach. Give an "
                    f"explicit index, as in {context.get('target') or 'block'}[{first}], or add '{dim}' to "
                    f'{where}.', dim)
            terms.append(best)
        return terms

    @staticmethod
    def normalise_dims(dims: Optional[Sequence[str]]) -> List[str]:
        seen = set()
        out = []
        for d in dims or []:
            if d in seen:
                raise IndexError_(f"Index list '{d}' is used twice on the same block")
            seen.add(d)
            out.append(d)
        return out
