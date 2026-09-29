"""The app a model carries, as far as an edit of the model is concerned.

Kompartment's App designer keeps an app -- sliders, charts, a page of them --
in the model file under ``app``. Its controls and results name blocks by their
qualified names and indices by list, so a rename in the model has to follow
into it, as it does in the application (``src/domain/apps.js``): these are the
same four walks, called from the same edits in :mod:`kompartment.model`.

Nothing else about the app is read here. It is kept in the file as it is, and
a model with one round-trips through this package unchanged.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

_UNSAFE_KEYS = {'__proto__', 'constructor', 'prototype'}

# How deep the walks go into panels and tabs written in a file: as deep as
# the application's (WALK_DEPTH in src/domain/apps.js), and no deeper.
_WALK_DEPTH = 8


def _pages(raw: Mapping[str, Any]) -> List[Any]:
    app = raw.get('app')
    pages = app.get('pages') if isinstance(app, dict) else None
    return pages if isinstance(pages, list) else []


def _each_reference(raw: Mapping[str, Any], fn: Callable[[Dict[str, Any]], None]) -> None:
    def walk(components: Any, depth: int) -> None:
        if not isinstance(components, list) or depth > _WALK_DEPTH:
            return
        for c in components:
            if not isinstance(c, dict):
                continue
            if isinstance(c.get('target'), dict):
                fn(c['target'])
            if isinstance(c.get('series'), list):
                for s in c['series']:
                    if isinstance(s, dict):
                        fn(s)
            # A panel holds parts, and a set of tabs holds a grid of them per tab.
            walk(c.get('components'), depth + 1)
            if isinstance(c.get('tabs'), list):
                for t in c['tabs']:
                    if isinstance(t, dict):
                        walk(t.get('components'), depth + 1)

    for page in _pages(raw):
        if isinstance(page, dict):
            walk(page.get('components'), 0)


def count_app_parts(raw: Mapping[str, Any]) -> int:
    """How many parts a model's app has, on every page and inside every container."""
    n = 0

    def walk(components: Any, depth: int) -> None:
        nonlocal n
        if not isinstance(components, list) or depth > _WALK_DEPTH:
            return
        for c in components:
            n += 1
            if not isinstance(c, dict):
                continue
            walk(c.get('components'), depth + 1)
            if isinstance(c.get('tabs'), list):
                for t in c['tabs']:
                    if isinstance(t, dict):
                        walk(t.get('components'), depth + 1)

    for page in _pages(raw):
        if isinstance(page, dict):
            walk(page.get('components'), 0)
    return n


def _follow_name(name: str, new_name_of: Callable[[str], Optional[str]]) -> str:
    to = new_name_of(name)
    if to:
        return to
    # A series a run names after a block -- a far-field path's ``Rock held``
    # and ``Rock.gravel1`` -- follows the block at the front of it.
    for cut in (name.rfind(' '), name.rfind('.')):
        if cut <= 0:
            continue
        head = new_name_of(name[:cut])
        if head:
            return head + name[cut:]
    return name


def retarget_app_names(raw: Mapping[str, Any], new_name_of: Callable[[str], Optional[str]]) -> None:
    """Follows a rename or a move of blocks into the app."""
    def one(ref: Dict[str, Any]) -> None:
        block = ref.get('block')
        if isinstance(block, str) and block:
            ref['block'] = _follow_name(block, new_name_of)
    _each_reference(raw, one)


def retarget_app_indexes(raw: Mapping[str, Any], moves: Mapping[str, Mapping[str, str]]) -> None:
    """Follows several index renames at once: list name -> {old index: new}."""
    def one(ref: Dict[str, Any]) -> None:
        index = ref.get('index')
        if not isinstance(index, dict):
            return
        for list_name, m in moves.items():
            was = index.get(list_name)
            # A string, as the application compares it: a list or an object
            # where an index name belongs is no index, and matches nothing.
            if isinstance(was, str) and was in m:
                index[list_name] = m[was]
    _each_reference(raw, one)


def rename_app_index(raw: Mapping[str, Any], lists: Iterable[str], old: str, new: str) -> None:
    """Follows an index rename in every list named."""
    retarget_app_indexes(raw, {name: {old: new} for name in lists})


def rename_app_index_list(raw: Mapping[str, Any], old: str, new: str) -> None:
    """Follows a list rename: an index keyed by ``old`` is keyed by ``new``."""
    if new in _UNSAFE_KEYS:
        return

    def one(ref: Dict[str, Any]) -> None:
        index = ref.get('index')
        if isinstance(index, dict) and old in index:
            index[new] = index.pop(old)
    _each_reference(raw, one)
