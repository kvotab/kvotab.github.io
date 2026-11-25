"""Groups: a way of sorting the blocks of one sub-system that changes no id.

The application's ``src/domain/groups.js``, as far as the editing API and the
Ecolego export need it. A declaration in a model's ``groups`` is
``{name, system?, group?}``: the group's name, the sub-system it belongs to
(absent at the top level) and the group it is inside. A block says which group
it is in with ``group``; a sub-system says so in its entry under ``layout``,
having no object of its own.

A group is known by an id, ``group:`` and its qualified name, which no block or
sub-system can have. Read leniently, as the application reads it: a member
naming a group its sub-system does not have is in no group, a group naming a
parent that is not there is at the top of its sub-system, and a loop of parents
is cut where it closes.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .keys import COLLECTIONS
from .names import NAME_RE, base_name, parent_of, qualify, system_of, system_paths

GROUP_PREFIX = 'group:'


def group_id(system: str, name: str) -> str:
    """The id of the group called ``name`` in ``system`` (``''``: the top level)."""
    return GROUP_PREFIX + qualify(system or '', name)


def is_group_id(key: Any) -> bool:
    """Whether ``key`` is a group's id rather than a block's or a sub-system's name."""
    return isinstance(key, str) and len(key) > len(GROUP_PREFIX) and key.startswith(GROUP_PREFIX)


def split_group_id(key: Any) -> Optional[Tuple[str, str]]:
    """A group's id taken apart: ``(system, name)``. None for anything else."""
    if not is_group_id(key):
        return None
    q = key[len(GROUP_PREFIX):]
    return parent_of(q), base_name(q)


def group_name(key: Any) -> str:
    """The name a group's id ends in, or the key itself when it is not one."""
    split = split_group_id(key)
    return split[1] if split else ('' if key is None else str(key))


def group_list(raw: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The declarations as the file has them, the malformed ones left out (``groupList``)."""
    groups = raw.get('groups')
    if not isinstance(groups, list):
        return []
    out = []
    for g in groups:
        if not isinstance(g, dict) or not isinstance(g.get('name'), str) or not NAME_RE.fullmatch(g['name']):
            continue
        if g.get('system') is not None and not isinstance(g.get('system'), str):
            continue
        out.append(g)
    return out


def model_paths(raw: Mapping[str, Any]) -> List[str]:
    """Every sub-system of a model: declared, transports, and those its blocks are in."""
    blocks = (b for c in COLLECTIONS for b in raw.get(c) or [] if isinstance(b, dict))
    return system_paths(raw.get('systems') or [], raw.get('transports') or [], (system_of(b) for b in blocks))


def group_index(raw: Mapping[str, Any], paths: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Every group, by id: ``{id, name, system, parent, decl}`` (``groupIndex``).

    The first declaration of an id wins; a group of a sub-system the model does
    not have is not one. ``paths`` are the model's sub-systems, when the caller
    has them already.
    """
    index: Dict[str, Dict[str, Any]] = {}
    declared = group_list(raw)
    if not declared:
        return index
    known = {''} | set(model_paths(raw) if paths is None else paths)
    for g in declared:
        system = g.get('system') or ''
        if system not in known:
            continue
        gid = group_id(system, g['name'])
        if gid in index:
            continue
        index[gid] = {'id': gid, 'name': g['name'], 'system': system, 'parent': None, 'decl': g}
    for info in index.values():
        p = info['decl'].get('group')
        if not isinstance(p, str) or not p:
            continue
        pid = group_id(info['system'], p)
        if pid != info['id'] and pid in index:
            info['parent'] = pid
    for info in index.values():
        seen = {info['id']}
        at = info
        while at['parent']:
            if at['parent'] in seen:
                at['parent'] = None
                break
            seen.add(at['parent'])
            at = index[at['parent']]
    return index


def group_of_block(block: Mapping[str, Any], index: Mapping[str, Any]) -> Optional[str]:
    """The group a block is in, as an id, or None."""
    name = block.get('group')
    if not isinstance(name, str) or not name:
        return None
    gid = group_id(system_of(block), name)
    return gid if gid in index else None


def group_of_system(raw: Mapping[str, Any], path: str, index: Mapping[str, Any]) -> Optional[str]:
    """The group a sub-system sits in -- one of its parent's -- as an id, or None."""
    layout = raw.get('layout')
    entry = layout.get(path) if isinstance(layout, dict) else None
    name = entry.get('group') if isinstance(entry, dict) else None
    if not path or not isinstance(name, str) or not name:
        return None
    gid = group_id(parent_of(path), name)
    return gid if gid in index else None


def group_chain(index: Mapping[str, Any], gid: Optional[str]) -> List[str]:
    """The groups ``gid`` is in, outermost first, ending with ``gid`` itself."""
    out: List[str] = []
    at = gid
    while at and at in index:
        out.insert(0, at)
        at = index[at]['parent']
    return out


def group_within(index: Mapping[str, Any], gid: Optional[str], outer: str) -> bool:
    """Whether group ``gid`` is ``outer`` or lies inside it, however deep."""
    at = gid
    while at:
        if at == outer:
            return True
        info = index.get(at)
        at = info['parent'] if info else None
    return False


def groups_on(index: Mapping[str, Any], system: Optional[str]) -> List[Dict[str, Any]]:
    """The groups of one sub-system (``''``: the top level), in the file's order."""
    here = system or ''
    return [g for g in index.values() if g['system'] == here]


def group_members(raw: Mapping[str, Any], gid: str, index: Mapping[str, Any], paths: Iterable[str], *,
                  deep: bool = False) -> Dict[str, List[str]]:
    """What a group holds: ``{'blocks', 'systems', 'groups'}``, directly or, with ``deep``,
    however many groups down. Blocks by qualified name, sub-systems by path, groups by id
    (``groupMembers``)."""
    out: Dict[str, List[str]] = {'blocks': [], 'systems': [], 'groups': []}
    info = index.get(gid)
    if info is None:
        return out

    def inside(g: str) -> bool:
        return group_within(index, g, gid) if deep else g == gid

    for g in index.values():
        if g['id'] != gid and g['parent'] and inside(g['parent']):
            out['groups'].append(g['id'])
    for collection in COLLECTIONS:
        for b in raw.get(collection) or []:
            if not isinstance(b, dict) or system_of(b) != info['system']:
                continue
            g = group_of_block(b, index)
            if g and inside(g):
                out['blocks'].append(qualify(info['system'], b.get('name')))
    for path in paths:
        if parent_of(path) != info['system']:
            continue
        g = group_of_system(raw, path, index)
        if g and inside(g):
            out['systems'].append(path)
    return out
