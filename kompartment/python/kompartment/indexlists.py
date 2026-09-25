"""The rules of Kompartment's index lists. Ports from ``src/domain/indexlists.js``.

Every block is indexed by an ordered list of **index lists** -- its dimensions
-- and holds one value per combination of their indices. A list is one of:

* a **root** list, an axis of its own;
* a **sub-set** of another list (``sub_set_of``): some of its indices, by name;
* a **mapping** onto another list (``mapping: {to, pairs}``): a grouping, many
  of the other list's indices to one of this list's.

Two lists are built in and always present: the **material catalogue**
(``for_contaminants``, called ``Contaminants``) holding every material the model
knows, and the **radionuclides** (``for_nuclides``, called ``Radionuclides``),
the sub-set of it that has half-lives. Three more are *derived* from the model
and never written to the file: ``Elements`` (a grouping of the materials by
element), ``Compartments`` (one index per compartment) and ``Transfers`` (one
per transfer). A list flagged ``for_scenarios`` holds the scenarios: one of its
indices is live at a time.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from .decay import element_of

MATERIAL_LIST = 'Contaminants'
NUCLIDE_LIST = 'Radionuclides'
ELEMENT_LIST = 'Elements'
COMPARTMENT_LIST = 'Compartments'
TRANSFER_LIST = 'Transfers'

#: What the built-in lists used to be called, for files written then.
WAS = {NUCLIDE_LIST: 'Nuclide', ELEMENT_LIST: 'Element', MATERIAL_LIST: 'Materials'}

#: The kinds of block that may be indexed by ``Compartments`` or ``Transfers``.
AUTO_DIM_KINDS = frozenset({
    'expression', 'parameter', 'lookup', 'block_reduction', 'index_reduction',
})

#: The words that stand for a transfer's own two ends inside its equations:
#: ``Kd[_source_]`` is the donor's value, ``Kd[_target_]`` the receiver's.
SOURCE_INDEX = '_source_'
TARGET_INDEX = '_target_'

RawList = Dict[str, Any]


def index_name(index: Any) -> Optional[str]:
    """An index's name, whether it is written as a string or an object."""
    return index if isinstance(index, str) else (index or {}).get('name')


def normalise_indices(indices: Iterable[Any]) -> List[Dict[str, Any]]:
    """Indices as objects: ``'Cs-137'`` becomes ``{'name': 'Cs-137', 'enabled': True}``."""
    out = []
    for i in indices or []:
        if isinstance(i, str):
            out.append({'name': i, 'enabled': True})
        else:
            j = dict(i)
            if 'enabled' not in j:
                j['enabled'] = True
            out.append(j)
    return out


def find_list(lists: Sequence[RawList], name: Optional[str]) -> Optional[RawList]:
    return next((l for l in lists or [] if isinstance(l, dict) and l.get('name') == name), None)


def parent_list_name(lst: Optional[RawList]) -> Optional[str]:
    """The list a list is taken from, or ``None`` for a root."""
    if not lst:
        return None
    if lst.get('sub_set_of'):
        return lst['sub_set_of']
    m = lst.get('mapping')
    if not m:
        return None
    return m if isinstance(m, str) else m.get('to')


def lineage(lists: Sequence[RawList], name: str) -> Dict[str, Any]:
    """How a list reaches its root: ``{root, mapped, above}``.

    ``above`` is the chain of lists above it, nearest first, each
    ``{name, mapped}``; ``mapped`` says whether a mapping is on the way.
    """
    at: Optional[str] = name
    mapped = False
    above: List[Dict[str, Any]] = []
    seen = set()
    while at and at not in seen:
        seen.add(at)
        lst = find_list(lists, at)
        m = (lst or {}).get('mapping')
        mto = (m.get('to') if isinstance(m, dict) else m) if m else None
        nxt = mto or (lst or {}).get('sub_set_of')
        if not nxt:
            break
        if mto:
            mapped = True
        above.append({'name': nxt, 'mapped': bool(mto)})
        at = nxt
    return {'root': at or name, 'mapped': mapped, 'above': above}


def root_of(lists: Sequence[RawList], name: str) -> str:
    return lineage(lists, name)['root']


def list_applies(lst: Optional[RawList], kind: str) -> bool:
    """Whether a block of ``kind`` may be indexed by ``lst``."""
    if not lst:
        return False
    if not lst.get('auto'):
        return True
    return kind in AUTO_DIM_KINDS


def list_applies_why(lst: Optional[RawList], kind: str) -> str:
    """Why not, in words."""
    if list_applies(lst, kind):
        return ''
    if not lst:
        return 'That index list is not in this model.'
    one = 'compartment' if lst.get('auto') == 'compartments' else 'transfer'
    own = (f"A {one} is one of them already: that is what lets a value indexed by "
           f"'{lst['name']}' be read inside a {one} with no index at all. ") if kind == one else ''
    return (f"'{lst['name']}' has one index per {one}, and a {kind.replace('_', ' ')} "
            f"cannot be indexed by them. {own}Only an expression, a parameter, a lookup "
            'table, an aggregate or an index operation can.')


def clashing_dimensions(lists: Sequence[RawList], dims: Sequence[str]) -> Optional[Dict[str, Any]]:
    """The first pair of dimensions that are one dimension twice, or ``None``.

    Two lists sharing a root -- a list and a sub-set of it, a list and a
    grouping of it, two sub-sets of one list -- cannot index one block; nor can
    ``Compartments`` and ``Transfers`` together.
    """
    seen = [dict(name=d, **lineage(lists, d)) for d in dims or []]

    def auto_of(n: str) -> Optional[str]:
        lst = find_list(lists, n)
        return lst.get('auto') if lst else None

    for i in range(len(seen)):
        for j in range(i + 1, len(seen)):
            a, b = seen[i], seen[j]
            if a['name'] == b['name']:
                continue
            if a['root'] == b['root']:
                b_above_a = next((x for x in a['above'] if x['name'] == b['name']), None)
                a_above_b = next((x for x in b['above'] if x['name'] == a['name']), None)
                link = b_above_a or a_above_b
                how = 'siblings' if not link else ('grouping' if link['mapped'] else 'sub_set')
                below = a['name'] if b_above_a else (b['name'] if a_above_b else None)
                above = (b['name'] if below == a['name'] else a['name'] if below == b['name'] else None)
                return {'a': a['name'], 'b': b['name'], 'root': a['root'], 'how': how,
                        'below': below, 'above': above}
            ra, rb = auto_of(a['root']), auto_of(b['root'])
            if ra and rb and ra != rb:
                return {'a': a['name'], 'b': b['name'], 'root': None, 'how': 'blocks'}
    return None


def clashing_dimensions_why(clash: Optional[Dict[str, Any]]) -> str:
    """Why not, in words."""
    if not clash:
        return ''
    a, b, root, how = clash['a'], clash['b'], clash['root'], clash['how']
    if how == 'blocks':
        return (f"'{a}' has one index per compartment and '{b}' one per transfer, and a "
                'block cannot be indexed by both. Pick one.')
    if how == 'siblings':
        return (f"'{a}' and '{b}' are both taken from '{root}', so a block indexed by "
                'both would be indexed by the same dimension twice. Pick one.')
    below, above = clash['below'], clash['above']
    if how == 'grouping':
        return (f"'{below}' is a grouping of '{above}', so a block indexed by both would "
                'be indexed by the same dimension twice. Pick one.')
    return (f"'{below}' is a sub-set of '{above}', so a block indexed by both would be "
            'indexed by the same dimension twice. Pick one.')


def _plain(lists: Sequence[RawList], dims: Optional[Sequence[str]]) -> List[str]:
    """The dimensions a flux varies along: the scenario list is not one."""
    out = []
    for d in dims or []:
        lst = find_list(lists, d)
        if lst and lst.get('for_scenarios'):
            continue
        out.append(d)
    return out


def shared_dims(lists: Sequence[RawList], source: Optional[Sequence[str]],
                target: Optional[Sequence[str]]) -> Optional[Dict[str, Any]]:
    """What a transfer between two blocks is indexed by: the indices both ends have.

    ``source``/``target`` are the two ends' dimensions, ``None`` for the model
    boundary. Returns ``{'dims', 'shared'}``, or ``None`` where the ends do not
    correspond and no list of the model holds what they have in common.
    """
    if source is None and target is None:
        return None
    if source is None or target is None:
        return {'dims': _plain(lists, source if source is not None else target), 'shared': []}
    a, b = _plain(lists, source), _plain(lists, target)
    if len(a) != len(b):
        return None
    if not a:
        return {'dims': [], 'shared': []}
    rest = list(b)
    matched: List[Optional[str]] = []
    for s in a:
        k = next((i for i, t in enumerate(rest) if root_of(lists, t) == root_of(lists, s)), -1)
        matched.append(None if k < 0 else rest.pop(k))
    dims: List[str] = []
    shared = []
    for s, t in zip(a, matched):
        if t is None:
            return None
        if s == t:
            dims.append(s)
            continue
        ls, lt = find_list(lists, s), find_list(lists, t)
        narrower = s if (ls or {}).get('sub_set_of') == t else (t if (lt or {}).get('sub_set_of') == s else None)
        if narrower is None:
            return None
        dims.append(narrower)
        shared.append({'from': s, 'to': t, 'dims': narrower})
    return {'dims': dims, 'shared': shared}


def summed_dims(lists: Sequence[RawList], flux_dims: Sequence[str],
                end_dims: Sequence[str]) -> List[str]:
    """The flux's dimensions one of its ends cannot follow -- the ones it would
    have to add up over, which needs ``sum_extra_indices`` on the flux."""
    roots = {root_of(lists, d) for d in _plain(lists, end_dims)}
    return [d for d in _plain(lists, flux_dims) if root_of(lists, d) not in roots]


def is_decay_dim(lists: Sequence[RawList], name: Optional[str], material: Optional[str]) -> bool:
    """Whether the nuclides decay along a dimension: the material list or a
    sub-set of it (a mapping, such as the elements, decays along nothing)."""
    if not name or not material:
        return False
    lst = find_list(lists, name)
    if not lst or lst.get('mapping'):
        return False
    return root_of(lists, name) == root_of(lists, material)


# --- reading a file -----------------------------------------------------------

def rename_built_in_lists(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Renames the built-in lists in a file written under their old names."""
    if not isinstance(raw, dict):
        return raw
    lists = raw.get('index_lists') if isinstance(raw.get('index_lists'), list) else []
    taken = {l.get('name') for l in lists if isinstance(l, dict)}

    def flagged(l: Any) -> bool:
        if not isinstance(l, dict):
            return False
        for k in ('for_contaminants', 'for_materials', 'forMaterials'):
            if l.get(k) is not None:
                return bool(l.get(k))
        return False

    material = next((l for l in lists if flagged(l)), None)
    mapping: Dict[str, str] = {}

    def rename(to: str) -> None:
        was = WAS.get(to)
        if not was or to in taken:
            return
        mapping[was] = to

    if (material['name'] == WAS[NUCLIDE_LIST]) if material else bool(raw.get('nuclides')):
        rename(NUCLIDE_LIST)
    element = next((l for l in lists if isinstance(l, dict) and l.get('name') == WAS[ELEMENT_LIST]
                    and (l.get('for_elements') or (
                        isinstance(l.get('mapping'), dict) and l['mapping'].get('to')
                        and material is not None and l['mapping'].get('to') == material.get('name')))), None)
    if element:
        rename(ELEMENT_LIST)
    if material and material.get('name') == WAS[MATERIAL_LIST]:
        rename(MATERIAL_LIST)
    if not mapping:
        return raw

    def to(name: Any) -> Any:
        return mapping.get(name, name) if isinstance(name, str) else name

    out = dict(raw)
    if lists:
        new_lists = []
        for l in lists:
            if not isinstance(l, dict):
                new_lists.append(l)
                continue
            n = dict(l, name=to(l.get('name')))
            if l.get('sub_set_of'):
                n['sub_set_of'] = to(l['sub_set_of'])
            if isinstance(l.get('mapping'), dict) and l['mapping'].get('to'):
                n['mapping'] = dict(l['mapping'], to=to(l['mapping']['to']))
            new_lists.append(n)
        out['index_lists'] = new_lists
    for key, value in raw.items():
        if key == 'index_lists' or not isinstance(value, list):
            continue
        changed = False
        blocks = []
        for b in value:
            if not isinstance(b, dict):
                blocks.append(b)
                continue
            dims = b.get('index_lists') if isinstance(b.get('index_lists'), list) else None
            needs_dims = bool(dims) and any(d in mapping for d in dims)
            entries = b.get('entries') if isinstance(b.get('entries'), list) else None
            needs_entries = bool(entries) and any(
                isinstance(e, dict) and isinstance(e.get('index'), dict)
                and any(d in mapping for d in e['index']) for e in entries)
            if not needs_dims and not needs_entries:
                blocks.append(b)
                continue
            changed = True
            nb = dict(b)
            if needs_dims:
                nb['index_lists'] = [to(d) for d in dims]
            if needs_entries:
                nb['entries'] = [
                    dict(e, index={to(d): i for d, i in e['index'].items()})
                    if isinstance(e, dict) and isinstance(e.get('index'), dict) else e
                    for e in entries]
            blocks.append(nb)
        if changed:
            out[key] = blocks
    return out


def _free_name(taken: Iterable[Any], want: str) -> str:
    used = set(taken)
    name = want
    n = 2
    while name in used:
        name = f'{want}{n}'
        n += 1
    return name


def split_material_roles(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Tells the two material roles apart in a file that has them as one list."""
    if not isinstance(raw, dict):
        return raw
    lists = raw.get('index_lists') if isinstance(raw.get('index_lists'), list) else []
    if not lists or any(isinstance(l, dict) and l.get('for_nuclides') for l in lists):
        return raw
    flagged = next((l for l in lists if isinstance(l, dict) and l.get('for_contaminants')), None)
    if flagged is None:
        return raw

    def as_nuclides(l: RawList) -> RawList:
        n = dict(l, for_nuclides=True)
        n.pop('for_contaminants', None)
        return n

    parent = find_list(lists, flagged.get('sub_set_of')) if flagged.get('sub_set_of') else None
    if parent is not None:
        root = parent['name']
        nxt = [as_nuclides(l) if l is flagged else (dict(l, for_contaminants=True) if l is parent else l)
               for l in lists]
    else:
        sub = next((l for l in lists if isinstance(l, dict) and l.get('sub_set_of') == flagged.get('name')
                    and l.get('name') in (NUCLIDE_LIST, WAS[NUCLIDE_LIST])), None)
        if sub is not None:
            root = flagged['name']
            nxt = [dict(l, for_nuclides=True) if l is sub else l for l in lists]
        else:
            if flagged.get('name') == MATERIAL_LIST:
                return raw
            root = _free_name([l.get('name') for l in lists if isinstance(l, dict)], MATERIAL_LIST)
            catalogue = {
                'name': root,
                'for_contaminants': True,
                'comment': (f"Every material the model knows. The radionuclides among "
                            f"them are in {flagged.get('name')}."),
                'indices': [{'name': i, 'enabled': True} if isinstance(i, str) else dict(i)
                            for i in flagged.get('indices') or []],
            }
            nxt = []
            for l in lists:
                if l is not flagged:
                    nxt.append(l)
                    continue
                nxt.append(catalogue)
                nxt.append(dict(as_nuclides(l), sub_set_of=root))
    nuclides = next((l['name'] for l in nxt if isinstance(l, dict) and l.get('for_nuclides')), None)
    if not nuclides or nuclides == root:
        return dict(raw, index_lists=nxt)
    fixed = []
    for l in nxt:
        if not isinstance(l, dict) or l.get('for_nuclides'):
            fixed.append(l)
        elif l.get('sub_set_of') == nuclides:
            fixed.append(dict(l, sub_set_of=root))
        elif isinstance(l.get('mapping'), dict) and l['mapping'].get('to') == nuclides:
            fixed.append(dict(l, mapping=dict(l['mapping'], to=root)))
        else:
            fixed.append(l)
    return dict(raw, index_lists=fixed)


def desugar_nuclides(raw: Dict[str, Any]) -> List[RawList]:
    """The ``nuclides: [...]`` shorthand as the two lists it stands for."""
    nuclides = raw.get('nuclides') or []
    existing = raw.get('index_lists') or []
    if not nuclides:
        return existing
    if any(isinstance(l, dict) and (l.get('name') in (NUCLIDE_LIST, WAS[NUCLIDE_LIST])
                                    or l.get('for_contaminants') or l.get('for_nuclides'))
           for l in existing):
        return existing
    root = _free_name([l.get('name') for l in existing if isinstance(l, dict)], MATERIAL_LIST)
    indices = [{'name': n, 'enabled': True} for n in nuclides]
    return [
        {'name': root, 'for_contaminants': True, 'indices': [dict(i) for i in indices]},
        {'name': NUCLIDE_LIST, 'for_nuclides': True, 'sub_set_of': root, 'indices': indices},
        *existing,
    ]


def derive_elements(lists: Sequence[RawList]) -> List[RawList]:
    """The lists with the derived element list added, when the model has none."""
    material = next((l for l in lists if l.get('for_contaminants')), None)
    if material is None:
        return list(lists)
    if any(l.get('for_elements') or l.get('name') in (ELEMENT_LIST, WAS[ELEMENT_LIST]) for l in lists):
        return list(lists)
    names: List[str] = []
    dormant: List[str] = []
    pairs = []
    for raw in material.get('indices') or []:
        nuclide = index_name(raw)
        el = element_of(nuclide or '') or nuclide
        if not el:
            continue
        if isinstance(raw, dict) and raw.get('enabled') is False:
            if el not in dormant:
                dormant.append(el)
            continue
        if el not in names:
            names.append(el)
        pairs.append({'from': el, 'to': nuclide})
    off = [e for e in dormant if e not in names]
    if not names and not off:
        return list(lists)
    return [*lists, {
        'name': ELEMENT_LIST,
        'for_elements': True,
        'derived': True,
        'comment': f"One index per element of {material['name']}, kept in step with it.",
        'mapping': {'to': material['name'], 'pairs': pairs},
        'indices': ([{'name': n, 'enabled': True} for n in names]
                    + [{'name': n, 'enabled': False} for n in off]),
    }]


def derive_block_lists(lists: Sequence[RawList], model: Dict[str, Any]) -> List[RawList]:
    """The lists with ``Compartments`` and ``Transfers`` added."""
    out = list(lists)
    for name, collection, what in ((COMPARTMENT_LIST, 'compartments', 'compartment'),
                                   (TRANSFER_LIST, 'transfers', 'transfer')):
        if any(l.get('name') == name for l in out):
            continue
        names = []
        for b in model.get(collection) or []:
            if not isinstance(b, dict) or b.get('hidden'):
                continue
            n = f"{b['system']}.{b.get('name')}" if b.get('system') else b.get('name')
            if isinstance(n, str) and n:
                names.append(n)
        if not names:
            continue
        out.append({
            'name': name,
            'derived': True,
            'auto': collection,
            'note': (f'One index per {what} in the model, derived from it: add a {what} '
                     'and this list gains an index.'),
            'indices': [{'name': n, 'enabled': True} for n in names],
        })
    return out
