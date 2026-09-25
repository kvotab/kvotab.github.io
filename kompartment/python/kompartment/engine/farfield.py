"""The far-field pathway (FARFCOMP): a dual-porosity transport model behind one block.

A port of ``src/domain/farfield.js`` (the geometry, the rates, the cell matrix,
the release) and of ``FarfPath`` in ``src/sim/farfield.js`` (the runtime),
which here works on whole index arrays at once: one gather and one weighted
``bincount`` per call for every nuclide and every cell of a path.

The references are SKB TR-19-06 appendix B and TR-90-01 chapter 3; the
arithmetic follows the reference implementation line for line, with the two
deliberate differences the application documents (the upper bound of the layer
ratio search, and the release through extra outflow cells).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np


class FarfError(ValueError):
    """A far-field path whose settings cannot describe a path."""


OUTFLOWS = (0, 1, 2, 3)
FARF_NUCLIDE_KEYS = ('kd_f', 'eps_m', 'kd_m', 'de_m')
FARF_SINGLE_KEYS = ('tw', 'f', 'rho_m', 'pe', 'pen_dep', 'pen_dep_0')
FARF_EQUATION_KEYS = ('tw', 'f', 'kd_f', 'kd_m', 'de_m', 'eps_m', 'rho_m', 'pe', 'pen_dep', 'pen_dep_0')
FARF_STRUCTURE_KEYS = ('n_f', 'n_m', 'o_b', 'n_b')
FARF_DEFAULTS: Dict[str, Any] = {
    'tw': '100', 'f': '1e5', 'kd_f': '0', 'kd_m': '0', 'de_m': '1e-4', 'eps_m': '0.0018',
    'rho_m': '2700', 'pe': '10', 'pen_dep': '12.5', 'pen_dep_0': '', 'n_f': 20, 'n_m': 20,
    'o_b': 1, 'n_b': 0, 'handle_decay': True, 'report_cells': False,
}


def spacing(x: float) -> float:
    """numpy's ``spacing``: the distance to the next double away from zero, signed like x."""
    return float(np.spacing(x))


def zeroin(fn: Any, a: float, b: float) -> float:
    """Dekker's zeroin (1969), as the reports write it."""
    fa = fn(a)
    fc = fa
    c = a
    fb = 0.0
    for _ in range(1000):
        fb = fn(b)
        if np.sign(fb) == np.sign(fc):
            c = a
            fc = fa
        if abs(fc) < abs(fb):
            a, b, c = b, c, b
            fa, fb, fc = fb, fc, fb
        m = (b + c) / 2
        if abs(m - b) <= spacing(abs(b)):
            return b
        p = (b - a) * fb
        q = fa - fb
        if p < 0:
            q = -q
            p = -p
        a = b
        fa = fb
        if p <= spacing(q):
            b += float(np.sign(c - b)) * spacing(b)
        elif p <= (m - b) * q:
            b += p / q
        else:
            b = m
    return b


def layer_depths(pen_dep: float, nm: int, aw: float, first: Optional[float] = None) -> np.ndarray:
    """The rock matrix's layer thicknesses in metres: a geometric series adding
    up to the penetration depth (``get_d``)."""
    if not (pen_dep > 0) or not math.isfinite(pen_dep):
        raise FarfError(f'The penetration depth must be a positive length (got {pen_dep})')
    if not (aw > 0) or not math.isfinite(aw):
        raise FarfError(f'F/TW must be positive: it is the flow-wetted surface per unit volume of water (got {aw})')
    d0 = first
    if d0 is None or not math.isfinite(d0) or d0 <= 0:
        def geo(x: float) -> float:
            s = 0.0
            for k in range(1, nm + 1):
                s += x * math.exp(k)
            return s - pen_dep
        E = math.e
        d0 = zeroin(geo, 1e-12 / E, 2 / aw / E) * E
    if d0 * nm > pen_dep * (1 + 1e-12):
        raise FarfError(
            f'{nm} matrix layers starting at {d0} m cannot add up to a penetration depth of {pen_dep} m: the '
            f'layers grow with depth, so the first must be smaller than {pen_dep / nm} m. Use a thinner first '
            'layer, fewer layers, a greater depth, or leave the first layer empty to have it worked out.')

    def total(q: float) -> float:
        s = 0.0
        for j in range(nm):
            s += d0 * q ** j
        return s - pen_dep

    hi = 100.0
    while total(hi) < 0 and hi < 1e300:
        hi *= 100
    q = zeroin(total, 1.0, hi)
    return np.array([d0 * q ** j for j in range(nm)], dtype=float)


def coefficients(s: Dict[str, Any]) -> Dict[str, Any]:
    """One path's rates for one nuclide: everything the transport matrix is written in."""
    nf, nm = s['nf'], s['nm']
    if not (s['pe'] > 0) or not math.isfinite(s['pe']):
        raise FarfError(f"The Peclet number must be greater than zero: the dispersion is TW/Pe (got {s['pe']})")
    with np.errstate(all='ignore'):
        aw = s['f'] / s['tw'] if s['tw'] != 0 else math.copysign(math.inf, s['f']) if s['f'] != 0 else math.nan
    r_m = s['eps_m'] + s['rho_m'] * s['kd_m']
    if not (r_m > 0) or not math.isfinite(r_m):
        raise FarfError(
            f"The matrix capacity eps + rho*Kd must be greater than zero (got {s['eps_m']} + {s['rho_m']}*"
            f"{s['kd_m']} = {r_m}). A rock with no porosity and no sorption has nothing for the nuclide to "
            'diffuse into.')
    f_df = 1 / (1 + s['kd_f'] * aw)
    adv_f = (f_df * nf) / s['tw']
    d_f = max(0.0, adv_f * (nf / s['pe'] - 0.5))
    d = layer_depths(s['pen_dep'], nm, aw, s.get('pen_dep_0'))
    diff_fm1 = (f_df * 2 * aw * s['de_m']) / d[0]
    diff_m1f = (2 * s['de_m']) / (r_m * d[0] * d[0])
    diff_mmf = np.zeros(max(0, nm - 1))
    diff_mmb = np.zeros(max(0, nm - 1))
    for j in range(nm - 1):
        diff_mmf[j] = (2 * s['de_m']) / (r_m * d[j] * (d[j] + d[j + 1]))
        diff_mmb[j] = (2 * s['de_m']) / (r_m * d[j + 1] * (d[j + 1] + d[j]))
    return {'aw': aw, 'rM': r_m, 'fDf': f_df, 'advF': adv_f, 'dF': d_f, 'd': d, 'diffFM1': diff_fm1,
            'diffM1F': diff_m1f, 'diffMMF': diff_mmf, 'diffMMB': diff_mmb}


def cell_index(k: int, j: int, nm: int) -> int:
    return k * (nm + 1) + j


def cell_count(g: Dict[str, Any]) -> int:
    """How many cells one nuclide's path has, extra outflow cells included."""
    return (int(g['n_f']) + int(g.get('n_b', 0) or 0)) * (int(g['n_m']) + 1)


def cell_structure(g: Dict[str, Any]) -> Dict[str, Any]:
    """The (row, column) pairs the transport matrix fills, in cell numbering."""
    nf, nm, ob, nb = int(g['n_f']), int(g['n_m']), int(g['o_b']), int(g.get('n_b', 0) or 0)
    NF = nf + nb
    rows: List[int] = []
    cols: List[int] = []

    def at(r: int, c: int) -> None:
        rows.append(r)
        cols.append(c)

    def cell(k: int, j: int) -> int:
        return cell_index(k, j, nm)

    for k in range(NF):
        at(cell(k, 0), cell(k, 0))
    for k in range(NF):
        for j in range(1, nm + 1):
            at(cell(k, j), cell(k, j))
    for k in range(1, NF):
        at(cell(k, 0), cell(k - 1, 0))
        at(cell(k - 1, 0), cell(k, 0))
    if ob == 3:
        at(cell(NF - 1, 0), cell(NF - 3, 0))
    for k in range(NF):
        at(cell(k, 1), cell(k, 0))
        at(cell(k, 0), cell(k, 1))
    for j in range(nm - 1):
        for k in range(NF):
            at(cell(k, j + 2), cell(k, j + 1))
            at(cell(k, j + 1), cell(k, j + 2))
    return {'rows': np.array(rows, dtype=np.int64), 'cols': np.array(cols, dtype=np.int64), 'nnz': len(rows)}


def cell_values(g: Dict[str, Any], c: Dict[str, Any], out: np.ndarray) -> np.ndarray:
    """The transport matrix's values, in the order :func:`cell_structure` lists them."""
    nf, nm, ob, nb = int(g['n_f']), int(g['n_m']), int(g['o_b']), int(g.get('n_b', 0) or 0)
    NF = nf + nb
    adv_f, d_f = c['advF'], c['dF']
    diff_fm1, diff_m1f, diff_mmf, diff_mmb = c['diffFM1'], c['diffM1F'], c['diffMMF'], c['diffMMB']
    out[:] = 0.0
    i = 0
    frac_loss = -(adv_f + 2 * d_f + diff_fm1)
    out[i:i + NF] = frac_loss
    out[i] += d_f
    if ob == 1:
        out[i + NF - 1] += d_f
    elif ob == 2:
        out[i + NF - 1] += 2 * d_f
    elif ob == 3:
        out[i + NF - 1] += 3 * d_f
    i += NF
    for k in range(NF):
        for j in range(1, nm + 1):
            if j == 1:
                out[i] = -(diff_m1f + diff_mmf[0])
            elif j == nm:
                out[i] = -diff_mmb[nm - 2]
            else:
                out[i] = -(diff_mmf[j - 1] + diff_mmb[j - 2])
            i += 1
    for k in range(1, NF):
        out[i] = d_f + adv_f
        if k == NF - 1:
            if ob == 2:
                out[i] -= d_f
            elif ob == 3:
                out[i] -= 3 * d_f
        i += 1
        out[i] = d_f
        i += 1
    if ob == 3:
        out[i] = d_f
        i += 1
    for k in range(NF):
        out[i] = diff_fm1
        out[i + 1] = diff_m1f
        i += 2
    for j in range(nm - 1):
        for k in range(NF):
            out[i] = diff_mmf[j]
            out[i + 1] = diff_mmb[j]
            i += 2
    return out


def release_cells(g: Dict[str, Any]) -> List[int]:
    """The cells the release is read from (``get_release``)."""
    nf, nm, nb, ob = int(g['n_f']), int(g['n_m']), int(g.get('n_b', 0) or 0), int(g['o_b'])

    def cell(k: int) -> int:
        return cell_index(k - 1, 0, nm)

    if nb > 0:
        return [cell(nf), cell(nf + 1)]
    if ob == 2:
        return [cell(nf), cell(nf - 1)]
    if ob == 3:
        return [cell(nf), cell(nf - 1), cell(nf - 2)]
    return [cell(nf)]


def release_weights(g: Dict[str, Any], c: Dict[str, Any], out: np.ndarray) -> np.ndarray:
    """The weights for those cells, from the rates."""
    nb, ob = int(g.get('n_b', 0) or 0), int(g['o_b'])
    adv_f, d_f = c['advF'], c['dF']
    if nb > 0:
        out[0] = adv_f + d_f
        out[1] = -d_f
        return out
    if ob == 0:
        out[0] = adv_f + d_f
        return out
    if ob == 1:
        out[0] = adv_f
        return out
    if ob == 2:
        out[0] = adv_f - d_f
        out[1] = d_f
        return out
    out[0] = adv_f - 2 * d_f
    out[1] = 3 * d_f
    out[2] = -d_f
    return out


def _is_whole(v: Any) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f.is_integer()


def structure_problem(g: Dict[str, Any]) -> Optional[str]:
    """What is wrong with a path's cell counts and outflow condition, or ``None``."""
    def whole(key: str, least: int) -> Optional[str]:
        v = g.get(key)
        if not _is_whole(v):
            return f'{key} must be a whole number'
        if float(v) < least:
            return f'{key} must be at least {least}'
        return None

    for problem in (whole('n_f', 1), whole('n_m', 2), whole('n_b', 0)):
        if problem:
            return problem
    try:
        ob = float(g.get('o_b'))
    except (TypeError, ValueError):
        ob = math.nan
    if ob not in OUTFLOWS:
        return f"o_b must be one of {', '.join(map(str, OUTFLOWS))}"
    nf, nb = float(g['n_f']), float(g['n_b'])
    if ob == 2 and nf + nb < 2:
        return 'a linearly extrapolated outflow needs at least two fracture cells'
    if ob == 3 and nf + nb < 3:
        return 'a quadratically extrapolated outflow needs at least three fracture cells'
    if nb == 0 and ob == 3 and nf < 3:
        return 'reading the release under a quadratic outflow needs three fracture cells'
    if nb == 0 and ob == 2 and nf < 2:
        return 'reading the release under a linear outflow needs two fracture cells'
    return None


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


def geometry_problem(block: Dict[str, Any]) -> Optional[str]:
    """The penetration-depth check ahead of a run, when the depths are numbers."""
    nm = _num(block.get('n_m'))
    pen_dep = _num(block.get('pen_dep'))
    raw_first = block.get('pen_dep_0')
    first = None if raw_first == '' or raw_first is None else _num(raw_first)
    if not math.isfinite(pen_dep) or not (math.isfinite(nm) and float(nm).is_integer()):
        return None
    if not (pen_dep > 0):
        return 'the penetration depth must be a positive length'
    if first is None or not math.isfinite(first):
        return None
    if not (first > 0):
        return 'the first matrix layer must be a positive length'
    if first * nm > pen_dep * (1 + 1e-12):
        return (f'{int(nm)} matrix layers starting at {first} m cannot add up to a penetration depth of {pen_dep} '
                f'm: the layers grow with depth, so the first must be smaller than {pen_dep / nm} m')
    return None


def dispersion_warning(g: Dict[str, Any]) -> Optional[str]:
    """A warning when the fracture grid disperses more than the Peclet number asked for."""
    nf = _num(g.get('n_f'))
    pe = _num(g.get('pe'))
    if not (math.isfinite(nf) and nf.is_integer()) or nf < 1:
        return None
    if not math.isfinite(pe) or not (pe > 0):
        return None
    own = 2 * nf
    if own >= pe:
        return None
    need = math.ceil(pe / 2)
    n = int(nf)
    return (f"{n} fracture cell{'' if n == 1 else 's'} disperse{'s' if n == 1 else ''} as a Peclet number of "
            f'{int(own)} would, and {pe:g} was asked for: a coarser grid spreads a front more, and the correction '
            'that would sharpen it back up cannot be negative, so none is applied and the path is more dispersive '
            f"than the setting says. {need} cell{'' if need == 1 else 's'} (Pe/2) is the fewest that reaches Pe {pe:g}")


def cell_names(g: Dict[str, Any]) -> List[str]:
    """What each cell is called: ``F3`` the third fracture cell, ``M3_1`` the first
    matrix layer behind it."""
    nf, nm, nb = int(g['n_f']), int(g['n_m']), int(g.get('n_b', 0) or 0)
    names = [''] * ((nf + nb) * (nm + 1))
    for k in range(nf + nb):
        names[cell_index(k, 0, nm)] = f'F{k + 1}'
        for j in range(1, nm + 1):
            names[cell_index(k, j, nm)] = f'M{k + 1}_{j}'
    return names


class FarfPath:
    """One far-field block at run time: its cells for every nuclide and every
    index of its other dimensions, the rates worked out from its setting slots,
    and the release read off its last cells."""

    def __init__(self, structure: Dict[str, Any], base: int, nnuc: int, other_width: int,
                 dim_off: np.ndarray, single_off: np.ndarray, setting_base: Dict[str, int],
                 single: Sequence[str], release_base: int) -> None:
        self.structure = structure
        self.base = base
        self.nnuc = nnuc
        self.other_width = other_width
        self.dim_off = np.asarray(dim_off, dtype=np.int64)
        self.single_off = np.asarray(single_off, dtype=np.int64)
        self.setting_base = setting_base
        self.is_single = set(single)
        self.release_base = release_base
        g = structure
        self.ncells = (int(g['n_f']) + int(g.get('n_b', 0) or 0)) * (int(g['n_m']) + 1)
        st = cell_structure(g)
        self.rows, self.cols, self.nnz = st['rows'], st['cols'], st['nnz']
        self.rel_cells = np.array(release_cells(g), dtype=np.int64)
        self.nrel = len(self.rel_cells)
        self.slots = other_width * nnuc
        self.vals = np.zeros((self.slots, self.nnz))
        self.rel_w = np.zeros((self.slots, self.nrel))
        self.keys = FARF_EQUATION_KEYS
        self.seen = np.full((self.slots, len(self.keys)), np.nan)
        # Where each setting of each slot is read from in X.
        self.setting_idx = np.zeros((self.slots, len(self.keys)), dtype=np.int64)
        for o in range(other_width):
            for m in range(nnuc):
                slot = o * nnuc + m
                off = int(self.dim_off[slot])
                for k, key in enumerate(self.keys):
                    one = int(self.single_off[o]) if len(self.single_off) else 0
                    self.setting_idx[slot, k] = setting_base[key] + (one if key in self.is_single else off)
        # The state indices each slot's matrix entries and release read.
        obase = base + np.repeat(np.arange(other_width) * self.ncells * nnuc, nnuc)
        m_of = np.tile(np.arange(nnuc), other_width)
        self.row_idx = obase[:, None] + self.rows[None, :] * nnuc + m_of[:, None]
        self.col_idx = obase[:, None] + self.cols[None, :] * nnuc + m_of[:, None]
        self.rel_idx = obase[:, None] + self.rel_cells[None, :] * nnuc + m_of[:, None]
        self.release_slots = release_base + self.dim_off
        self.row_flat = self.row_idx.ravel()
        self.col_flat = self.col_idx.ravel()
        # Every cell's states, nuclide innermost, for decay: cell c of combination
        # o is states base + o*ncells*nnuc + c*nnuc + (0..nnuc-1).
        cells = base + (np.arange(other_width)[:, None] * self.ncells * nnuc
                        + np.arange(self.ncells)[None, :] * nnuc).ravel()
        self.cell_starts = cells

    def refresh(self, X: np.ndarray) -> None:
        """Works the rates out again for every slot whose settings moved."""
        probe = X[self.setting_idx]
        changed = np.any(probe != self.seen, axis=1)
        if not changed.any():
            return
        g = self.structure
        for slot in np.nonzero(changed)[0]:
            s = {key: float(probe[slot, k]) for k, key in enumerate(self.keys)}
            s['nf'] = int(g['n_f'])
            s['nm'] = int(g['n_m'])
            if not (s['pen_dep_0'] > 0):
                s['pen_dep_0'] = None
            c = coefficients(s)
            cell_values(g, c, self.vals[slot])
            release_weights(g, c, self.rel_w[slot])
            self.seen[slot] = probe[slot]

    def release(self, y: np.ndarray, X: np.ndarray) -> None:
        """The release out of the far end of every slot, into its slot of X."""
        self.refresh(X)
        X[self.release_slots] = np.einsum('ij,ij->i', self.rel_w, y[self.rel_idx])

    def transport_contributions(self, y: np.ndarray) -> np.ndarray:
        """The transport terms, ready for a weighted bincount over ``row_flat``."""
        return (self.vals * y[self.col_idx]).ravel()
