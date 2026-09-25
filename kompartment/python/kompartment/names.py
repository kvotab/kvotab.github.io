"""Names, sub-systems and how a name written in an equation finds its block.

Ports of ``src/domain/names.js`` and ``src/domain/systems.js``.

A block has a **local name** (``Water``) and lives in a **sub-system**, written
as a dotted path (``NearField.Geosphere``; the top level is ``''``). Its
**qualified name** is the two joined -- ``NearField.Geosphere.Water`` -- and is
what identifies it: two sub-systems may each have a ``Water``.

An equation refers to a block by writing a name, resolved from the sub-system
the equation is written in (:func:`resolve_reference`):

* a dotted name is a full path from the top level;
* a bare name is looked up in the writer's own sub-system first, then at the
  top level -- never in the sub-systems in between.
"""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import Callable, Iterable, List, Optional

#: What a block, index list or sub-system component may be called: letters,
#: digits and underscore, not starting with a digit.
NAME_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')

#: The names no block may take: the functions an equation can call, and the
#: words the language keeps. Kompartment's own set, from ``data/reserved.json``.
RESERVED = frozenset(json.loads(
    resources.files(__package__).joinpath('data', 'reserved.json').read_text('utf-8'),
)['names'])

SEPARATOR = '.'


def is_name(name: object) -> bool:
    """Whether ``name`` passes the identifier rule (reserved names aside)."""
    return isinstance(name, str) and NAME_RE.fullmatch(name) is not None


def name_problem(name: object) -> Optional[str]:
    """What is wrong with ``name`` as a block's local name, or ``None``."""
    if not is_name(name):
        return (f"'{name}' is not a valid name: use letters, digits and underscore, "
                'and do not start with a digit.')
    if name in RESERVED:
        return f"'{name}' is a reserved name."
    return None


def parts(path: Optional[str]) -> List[str]:
    """The components of a sub-system path; ``''`` has none."""
    return [p for p in str(path).split(SEPARATOR) if p] if path else []


def qualify(system: Optional[str], name: str) -> str:
    """``system`` and ``name`` joined into a qualified name."""
    return f'{system}{SEPARATOR}{name}' if system else name


def parent_of(path: Optional[str]) -> str:
    """The sub-system a path is inside: ``A.B.C`` -> ``A.B``, ``A`` -> ``''``."""
    return SEPARATOR.join(parts(path)[:-1])


def base_name(path: Optional[str]) -> str:
    """The last component of a path: ``A.B.C`` -> ``C``."""
    p = parts(path)
    return p[-1] if p else ''


def is_within(path: Optional[str], ancestor: Optional[str]) -> bool:
    """Whether ``path`` is ``ancestor`` or somewhere inside it.

    Everything is within the top level, ``''``.
    """
    if not ancestor:
        return True
    path = path or ''
    return path == ancestor or path.startswith(ancestor + SEPARATOR)


def reparent(path: str, old: str, new: str) -> str:
    """``path`` with its prefix ``old`` replaced by ``new``."""
    if path == old:
        return new
    if old and path.startswith(old + SEPARATOR):
        rest = path[len(old) + 1:]
        return qualify(new, rest)
    if not old:
        return qualify(new, path) if path else new
    return path


def is_valid_path(path: Optional[str]) -> bool:
    """Whether a sub-system path is well formed: every component a name.

    ``''`` (the top level) is valid; ``A..B`` and ``A.`` are not.
    """
    if not path:
        return True
    return all(NAME_RE.fullmatch(c) is not None for c in str(path).split(SEPARATOR))


def system_of(block: dict) -> str:
    """The sub-system a raw block lives in."""
    return block.get('system') or ''


def qualified_name(block: dict) -> str:
    """A raw block's qualified name."""
    return qualify(system_of(block), block.get('name') or '')


def resolve_reference(reference: str, system: str,
                      known: Callable[[str], bool]) -> Optional[str]:
    """The qualified name a reference written in ``system`` means, or ``None``.

    ``known(qualified_name)`` says whether a block of that name exists.
    """
    ref = str(reference)
    if SEPARATOR in ref:
        return ref if known(ref) else None
    own = qualify(system, ref)
    if known(own):
        return own
    return ref if known(ref) else None


def reference_from(target: str, system: str, known: Callable[[str], bool]) -> str:
    """How a reference to ``target`` is written from inside ``system``.

    The bare name where that finds the block -- in its own sub-system or at the
    top level -- and the full path otherwise.
    """
    parent = parent_of(target)
    local = base_name(target)
    if (parent == '' or parent == system) and resolve_reference(local, system, known) == target:
        return local
    return target


def _locale_key(text: str):
    # JavaScript's `localeCompare` for identifier-like names: case folded first,
    # lower case before upper on a tie.
    return (text.casefold(), text.swapcase())


def system_paths(declared: Iterable[object], transports: Iterable[object],
                 block_systems: Iterable[str]) -> List[str]:
    """Every sub-system a model has, shallowest first.

    Every prefix of every declared path, transport path and block's sub-system
    -- so a block in ``A.B`` makes ``A`` and ``A.B`` sub-systems even when
    neither was declared.
    """
    seen = set()
    for source in (declared, transports):
        for item in source or []:
            path = item.get('name') if isinstance(item, dict) else item
            if isinstance(path, str):
                _add_prefixes(seen, path)
    for path in block_systems:
        _add_prefixes(seen, path)
    return sorted(seen, key=lambda p: (len(parts(p)), _locale_key(p)))


def _add_prefixes(seen: set, path: str) -> None:
    ps = parts(path)
    for k in range(1, len(ps) + 1):
        seen.add(SEPARATOR.join(ps[:k]))
