"""The matrix layers of every far-field path, as a run lays them out at its first instant.

A port of ``src/sim/pathlayout.js``, for the Ecolego exporter
(:mod:`kompartment.io.ecoexport`), which writes a path out as the compartments
of its cells: the rates go out as expressions of the path's settings, and the
layers' thicknesses -- which come out of a root-find no Ecolego expression can
do -- as the numbers a run starts from, from the settings as the built model
evaluates them at the start. The matched layers are laid out by the path's own
code; the reference layers by :func:`reference_layers`, which the application
does the same way to the last bit, so that both write the same file.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional

from .. import jsmath
from .farfield import (
    CONTINUES, FARF_DEFAULTS, GRIDS, FarfPath, is_semi_analytic, layer_depths, matched_grid, structure_problem,
    wetted_surface, zeroin,
)


def cell_equivalent(block: Dict[str, Any]) -> Dict[str, Any]:
    """The structure a path is written out on (``cellEquivalent``): its own for a
    path on cells; for one worked out semi-analytically, its cell settings with
    the outlet it solves, or the defaults where those cannot be built."""
    if not is_semi_analytic(block):
        return block
    cells = dict(block)
    cells.update(method='discretized', o_b=CONTINUES, n_b='',
                 grid=block.get('grid') if block.get('grid') in GRIDS else FARF_DEFAULTS['grid'])
    if structure_problem(cells):
        cells['n_f'] = FARF_DEFAULTS['n_f']
        cells['n_m'] = FARF_DEFAULTS['n_m']
    return cells


def path_layouts(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Every path's layers, by its qualified name (``pathLayouts``): the grid,
    the path's other dimensions, and one ``{'index', 'd', 'h'}`` per combination
    of them -- or ``{'error'}``, why none could be had."""
    from .builder import build_system
    from .project import Project

    def qname(b: Dict[str, Any]) -> str:
        return f"{b['system']}.{b.get('name')}" if b.get('system') else str(b.get('name') or '')

    paths = [b for b in raw.get('farfields') or [] if isinstance(b, dict)]
    out: Dict[str, Dict[str, Any]] = {}
    if not paths:
        return out
    try:
        project = Project(copy.deepcopy(raw))
        sys_ = build_system(project, jacobian=False)
        t0 = float(project.simulation['start_time'])
        y = sys_.initial_state()
        sys_.prime_recorders(t0, y)
        X = sys_.evaluate_algebraic(t0, y)
    except Exception as e:  # the application's catch takes whatever the build raised
        why = f'the model does not build, so its layers cannot be laid out: {e}'
        for b in paths:
            out[qname(b)] = {'error': why}
        return out
    space = sys_.layout.index_space
    for p in sys_.layout.farfields or []:
        F = sys_.FARF[p.farf_index]
        block = cell_equivalent(p.block)
        nm = int(float(block.get('n_m')))
        matched = block.get('grid') == 'matched'
        other_dims = list(p.farf.other_dims)
        names = [space.index_names(d) for d in other_dims]
        strides = space.strides(other_dims)
        try:
            combos: List[Dict[str, Any]] = []
            for o in range(p.farf.other_width):
                index = {d: names[k][(o // strides[k]) % len(names[k])] for k, d in enumerate(other_dims)}
                combos.append({'index': index, **_layers_at(F, X, o, nm, matched)})
            out[p.name] = {'grid': 'matched' if matched else 'reference', 'other_dims': other_dims, 'combos': combos}
        except Exception as e:  # FarfError and whatever the settings make of the arithmetic
            out[p.name] = {'error': str(e)}
    return out


def _layers_at(F: Any, X: Any, o: int, nm: int, matched: bool) -> Dict[str, Optional[List[float]]]:
    """One combination's layers, by the path's own code where it has cells."""
    if isinstance(F, FarfPath):
        if matched:
            g = F._lay_out(X, o)
            return {'d': [float(v) for v in g['d']], 'h': [float(v) for v in g['h']]}
        s = F._setting(X, o * F.nnuc)
        return {'d': reference_layers(s['pen_dep'], nm, wetted_surface(s), s['pen_dep_0']), 'h': None}
    s = F.settings_of(X, o)
    first = s['pen_dep_0'] if s['pen_dep_0'] > 0 else None
    aw = wetted_surface(s)
    if not matched:
        return {'d': reference_layers(s['pen_dep'], nm, aw, first), 'h': None}
    lam = (F.D or {}).get('lam') if isinstance(F.D, dict) else None
    nucs = [{'de': de, 'rm': s['eps_m'][m] + s['rho_m'] * s['kd_m'][m],
             'lam': (lam[m] if lam is not None and m < len(lam) else 0.0), 'rf': 1 + s['kd_f'][m] * aw}
            for m, de in enumerate(s['de_m'])]
    g = matched_grid(s['pen_dep'], nm, first, aw, s['tw'], s['pe'], nucs)
    return {'d': [float(v) for v in g['d']], 'h': [float(v) for v in g['h']]}


def reference_layers(pen_dep: float, nm: int, aw: float, first: Optional[float] = None) -> List[float]:
    """The reference layers as the application's ``referenceLayers`` lays them
    out: ``layer_depths``'s first layer and root-find, with V8's ``exp`` and
    every power of the ratio a running product, so that the two agree to the
    last bit."""
    layer_depths(pen_dep, nm, aw, first)  # what cannot be laid out is refused as the path refuses it
    d0 = first
    if d0 is None or not math.isfinite(d0) or d0 <= 0:
        def geo(x: float) -> float:
            s = 0.0
            for k in range(1, nm + 1):
                s += x * jsmath.exp(k)
            return s - pen_dep
        d0 = zeroin(geo, 1e-12 / math.e, 2 / aw / math.e) * math.e

    def total(q: float) -> float:
        s = 0.0
        t = d0
        for _ in range(nm):
            s += t
            t *= q
        return s - pen_dep

    hi = 100.0
    while total(hi) < 0 and hi < 1e300:
        hi *= 100
    q = zeroin(total, 1.0, hi)
    d: List[float] = []
    t = d0
    for _ in range(nm):
        d.append(t)
        t *= q
    return d
