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


#: How the downstream end is closed: the reference implementation's four, and
#: 4, the rock going on past the release point (semi-infinite, as in FARF31).
OUTFLOWS = (0, 1, 2, 3, 4)
CONTINUES = 4
OUTFLOW_ORDER = (4, 1, 0, 2, 3)
#: How the block works the path out: on cells, or semi-analytically from its
#: transfer function (:mod:`kompartment.engine.farfield_semi`), which has no
#: cells and one state per nuclide for what the path holds.
FARF_METHODS = ('discretized', 'semi-analytical')
#: How the flow-wetted surface is given: F, a_w, or the aperture (a_w = 2/aperture).
SURFACES = ('f', 'aw', 'aperture')
SURFACE_KEY = {'f': 'f', 'aw': 'aw', 'aperture': 'aperture'}
#: How the matrix layers are laid out.
GRIDS = ('matched', 'reference')
FARF_NUCLIDE_KEYS = ('kd_f', 'eps_m', 'kd_m', 'de_m')
FARF_SINGLE_KEYS = ('tw', 'f', 'aw', 'aperture', 'rho_m', 'pe', 'pen_dep', 'pen_dep_0')
FARF_EQUATION_KEYS = ('tw', 'f', 'aw', 'aperture', 'kd_f', 'kd_m', 'de_m', 'eps_m', 'rho_m', 'pe', 'pen_dep',
                      'pen_dep_0')
FARF_STRUCTURE_KEYS = ('n_f', 'n_m', 'o_b', 'n_b')
FARF_CHOICE_KEYS = ('surface', 'grid', 'method')
#: What a new path starts with (``FARF_DEFAULTS`` in src/domain/farfield.js).
FARF_DEFAULTS: Dict[str, Any] = {
    'method': 'discretized',
    'tw': '100', 'surface': 'f', 'f': '1e5', 'kd_f': '0', 'kd_m': '0', 'de_m': '1e-4', 'eps_m': '0.0018',
    'rho_m': '2700', 'pe': '10', 'pen_dep': '12.5', 'pen_dep_0': '', 'n_f': 20, 'n_m': 20,
    'o_b': CONTINUES, 'n_b': '', 'grid': 'matched', 'handle_decay': True, 'report_cells': False,
}
#: What a saved path that does not mention these meant: the reference
#: implementation's numerics, written into the block on the way in.
FARF_LEGACY: Dict[str, Any] = {'o_b': 1, 'n_b': 0, 'grid': 'reference', 'surface': 'f', 'method': 'discretized'}
#: A surface setting's equation when the path gives none.
FARF_SURFACE_DEFAULTS: Dict[str, str] = {'f': '1e5', 'aw': '1000', 'aperture': '0.002'}

#: How far down the transfer function may fall before a frequency stops
#: mattering (e^-25), and how many times thinner than the depth diffusion
#: reaches there the first matched layer is.
ATTENUATION = 25.0
RESOLVE = 10.0


def uses_cells(block: Dict[str, Any]) -> bool:
    """Whether a path is worked out on cells, which is what gives it states."""
    m = block.get('method') if isinstance(block, dict) else None
    return m is None or m == '' or m == 'discretized'


def is_semi_analytic(block: Dict[str, Any]) -> bool:
    """Whether a path is worked out semi-analytically: no cells, a state per
    nuclide for what it holds (``isSemiAnalytic``)."""
    return isinstance(block, dict) and block.get('method') == 'semi-analytical'


def surface_of(block: Dict[str, Any]) -> str:
    """How a path gives its flow-wetted surface: F unless it says otherwise."""
    s = block.get('surface') if isinstance(block, dict) else None
    return s if s in SURFACES else 'f'


def active_equation_keys(block: Dict[str, Any]) -> List[str]:
    """Every equation but the two ways of giving the surface the path does not use."""
    used = SURFACE_KEY[surface_of(block)]
    others = set(SURFACE_KEY.values()) - {used}
    return [k for k in FARF_EQUATION_KEYS if k not in others]


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
                s += x * _js_exp(k)
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
            s += d0 * _js_pow(q, j)
        return s - pen_dep

    hi = 100.0
    while total(hi) < 0 and hi < 1e300:
        hi *= 100
    q = zeroin(total, 1.0, hi)
    return np.array([d0 * _js_pow(q, j) for j in range(nm)], dtype=float)


def _js_pow(q: float, j: int) -> float:
    """``q ** j`` as JavaScript has it: Infinity where it overflows, rather
    than Python's OverflowError -- which a search over many layers reaches
    (160 layers from 10 micrometres bracketed at q = 100 is 1e318)."""
    try:
        return q ** j
    except OverflowError:
        return math.inf


def _js_exp(x: float) -> float:
    """``Math.exp``: Infinity past the largest double, not OverflowError."""
    try:
        return math.exp(x)
    except OverflowError:
        return math.inf


def _div(a: float, b: float) -> float:
    """``a / b`` as JavaScript has it: signed infinities and NaN, not ZeroDivisionError."""
    if b != 0:
        return a / b
    if a == 0 or a != a:
        return math.nan
    return math.copysign(math.inf, a) * math.copysign(1.0, b)


def penetration_scale(n: Dict[str, float], aw: float, tw: float, pe: float) -> float:
    """The depth diffusion reaches into the rock at the fastest frequency the
    path lets through, for one nuclide (``penetrationScale``): the positive root
    of rf*u**2 + aw*sqrt(De*Rm)*u = A*(1 + A/Pe)/TW, or the nuclide's own decay
    constant when that is faster. Square roots and the four operations only, so
    the application and this engine agree on it to the last bit."""
    de, rm = n['de'], n['rm']
    lam = n.get('lam', 0.0)
    rf = n.get('rf', 1.0)
    if not (de > 0) or not (rm > 0) or not (aw > 0) or not math.isfinite(aw):
        return math.inf
    if not (tw > 0) or not (pe > 0):
        return math.inf
    G = (ATTENUATION * (1 + ATTENUATION / pe)) / tw
    A = aw * math.sqrt(de * rm)
    u = (2 * G) / (A + math.sqrt(A * A + 4 * rf * G))
    u2 = max(u * u, lam if (math.isfinite(lam) and lam > 0) else 0.0)
    if not (u2 > 0) or not math.isfinite(u2):
        return math.inf
    return math.sqrt(de / rm / u2)


def auto_first_layer(pen_dep: float, nm: int, aw: float, tw: float, pe: float,
                     nucs: Sequence[Dict[str, float]]) -> float:
    """The matched layers' first thickness: the shallowest penetration scale of
    every nuclide on the path over ``RESOLVE``, never thicker than an even split."""
    L = math.inf
    for n in nucs:
        v = penetration_scale(n, aw, tw, pe)
        if v < L:
            L = v
    even = pen_dep / nm
    if not (L < math.inf):
        return even
    d0 = L / RESOLVE
    return d0 if d0 < even else even


def matched_grid(pen_dep: float, nm: int, first: Optional[float], aw: float, tw: float, pe: float,
                 nucs: Sequence[Dict[str, float]]) -> Dict[str, Any]:
    """The matched layers (``matchedGrid``): a geometric series to exactly the
    depth, built by repeated multiplication, with nodes spaced by the geometric
    mean of the layers they join and the first at d0/(1 + sqrt q) from the wall."""
    if not (pen_dep > 0) or not math.isfinite(pen_dep):
        raise FarfError(f'The penetration depth must be a positive length (got {_num_text(pen_dep)})')
    d0 = first
    if d0 is None or not math.isfinite(d0) or d0 <= 0:
        d0 = auto_first_layer(pen_dep, nm, aw, tw, pe, nucs)
    if d0 * nm > pen_dep * (1 + 1e-12):
        raise FarfError(
            f'{nm} matrix layers starting at {_num_text(d0)} m cannot add up to a penetration depth of '
            f'{_num_text(pen_dep)} m: the layers grow with depth, so the first must be smaller than '
            f'{_num_text(pen_dep / nm)} m. Use a thinner first layer, fewer layers, a greater depth, or leave '
            'the first layer empty to have it worked out.')
    d = np.zeros(nm)
    h = np.zeros(nm)
    q = 1.0
    if nm == 1 or d0 * nm >= pen_dep * (1 - 1e-12):
        d[:] = pen_dep / nm
    else:
        def total(r: float) -> float:
            acc = 0.0
            t = d0
            for _ in range(nm):
                acc += t
                t *= r
            return acc - pen_dep
        hi = 2.0
        while total(hi) < 0 and hi < 1e300:
            hi *= 2
        q = zeroin(total, 1.0, hi)
        d[0] = d0
        for j in range(1, nm):
            d[j] = d[j - 1] * q
    h[0] = d[0] / (1 + math.sqrt(q))
    for j in range(1, nm):
        h[j] = math.sqrt(d[j - 1] * d[j])
    return {'kind': 'matched', 'd': d, 'h': h, 'q': q}


def _num_text(x: float) -> str:
    """A number as JavaScript's String() writes it, for messages."""
    if x != x:
        return 'NaN'
    if math.isinf(x):
        return 'Infinity' if x > 0 else '-Infinity'
    if float(x).is_integer() and abs(x) < 1e21:
        return str(int(x))
    return repr(float(x))


def wetted_surface(s: Dict[str, Any]) -> float:
    """The flow-wetted surface per unit volume of water, however the path gives it."""
    how = s.get('surface') if s.get('surface') in SURFACES else 'f'
    if how == 'aw':
        return s['aw']
    if how == 'aperture':
        return _div(2.0, s['aperture'])
    return _div(s['f'], s['tw'])


def _surface_problem(s: Dict[str, Any], aw: float) -> Optional[str]:
    if aw > 0 and math.isfinite(aw):
        return None
    how = s.get('surface') if s.get('surface') in SURFACES else 'f'
    if how == 'aw':
        return ('The flow-wetted surface a_w must be positive: it is the wetted surface per unit volume of water '
                f'(got {_num_text(aw)})')
    if how == 'aperture':
        return ('The fracture aperture must be a positive length: the wetted surface is 2/\u03b4 per unit volume '
                f"of water (got \u03b4 = {_num_text(s['aperture'])})")
    return f'F/TW must be positive: it is the flow-wetted surface per unit volume of water (got {_num_text(aw)})'


def coefficients(s: Dict[str, Any], grid: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One path's rates for one nuclide: everything the transport matrix is written in.

    ``grid`` is the matrix layout the path's nuclides share; left out, the
    reference layers are worked out from ``s`` as they always were (or, for
    ``s['grid'] == 'matched'``, matched layers for this one nuclide)."""
    nf, nm = s['nf'], s['nm']
    if not (s['pe'] > 0) or not math.isfinite(s['pe']):
        raise FarfError('The Peclet number must be greater than zero: the dispersion is TW/Pe '
                        f"(got {_num_text(s['pe'])})")
    aw = wetted_surface(s)
    bad = _surface_problem(s, aw)
    if bad:
        raise FarfError(bad)
    if not (s['tw'] > 0) or not math.isfinite(s['tw']):
        raise FarfError(f"The travel time T_w must be positive (got {_num_text(s['tw'])})")
    r_m = s['eps_m'] + s['rho_m'] * s['kd_m']
    if not (r_m > 0) or not math.isfinite(r_m):
        raise FarfError(
            f"The matrix capacity eps + rho*Kd must be greater than zero (got {s['eps_m']} + {s['rho_m']}*"
            f"{s['kd_m']} = {r_m}). A rock with no porosity and no sorption has nothing for the nuclide to "
            'diffuse into.')
    f_df = 1 / (1 + s['kd_f'] * aw)
    adv_f = (f_df * nf) / s['tw']
    d_f = max(0.0, adv_f * (nf / s['pe'] - 0.5))
    if grid is None:
        if s.get('grid') == 'matched':
            grid = matched_grid(s['pen_dep'], nm, s.get('pen_dep_0'), aw, s['tw'], s['pe'],
                                [{'de': s['de_m'], 'rm': r_m, 'lam': s.get('lam', 0.0), 'rf': 1 + s['kd_f'] * aw}])
        else:
            grid = {'kind': 'reference', 'd': layer_depths(s['pen_dep'], nm, aw, s.get('pen_dep_0')), 'h': None}
    d = grid['d']
    diff_mmf = np.zeros(max(0, nm - 1))
    diff_mmb = np.zeros(max(0, nm - 1))
    if grid['kind'] == 'matched':
        h = grid['h']
        diff_fm1 = (f_df * aw * s['de_m']) / h[0]
        diff_m1f = s['de_m'] / (r_m * d[0] * h[0])
        for j in range(nm - 1):
            diff_mmf[j] = s['de_m'] / (r_m * d[j] * h[j + 1])
            diff_mmb[j] = s['de_m'] / (r_m * d[j + 1] * h[j + 1])
        return {'aw': aw, 'rM': r_m, 'fDf': f_df, 'advF': adv_f, 'dF': d_f, 'd': d, 'h': h, 'grid': 'matched',
                'diffFM1': diff_fm1, 'diffM1F': diff_m1f, 'diffMMF': diff_mmf, 'diffMMB': diff_mmb}
    diff_fm1 = (f_df * 2 * aw * s['de_m']) / d[0]
    diff_m1f = (2 * s['de_m']) / (r_m * d[0] * d[0])
    for j in range(nm - 1):
        diff_mmf[j] = (2 * s['de_m']) / (r_m * d[j] * (d[j] + d[j + 1]))
        diff_mmb[j] = (2 * s['de_m']) / (r_m * d[j + 1] * (d[j + 1] + d[j]))
    return {'aw': aw, 'rM': r_m, 'fDf': f_df, 'advF': adv_f, 'dF': d_f, 'd': d, 'h': None, 'grid': 'reference',
            'diffFM1': diff_fm1, 'diffM1F': diff_m1f, 'diffMMF': diff_mmf, 'diffMMB': diff_mmb}


def cell_index(k: int, j: int, nm: int) -> int:
    return k * (nm + 1) + j


def auto_extra_cells(nf: Any, pe: Any) -> int:
    """How many cells of rock past the release point the semi-infinite outlet
    needs (``autoExtraCells``): the fewest that bring
    ((2 NF - Pe)/(2 NF + Pe))**NB under a tenth, counted by repeated
    multiplication; a Peclet number that is not a number is taken as 10."""
    n = _num(nf)
    p = _num(pe)
    if not (math.isfinite(n) and n.is_integer()) or n < 1:
        return 0
    if not (p > 0) or not math.isfinite(p):
        p = 10.0
    rho = (2 * n - p) / (2 * n + p)
    if not (rho > 0):
        return 0
    k = 0
    left = 1.0
    while left > 0.1 and k < 10000:
        left *= rho
        k += 1
    return k


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == '')


def extra_cells(block: Dict[str, Any]) -> int:
    """The extra cells past the release point: the count given, or, left empty,
    none -- unless the outlet is the semi-infinite rock, which works it out."""
    nb = block.get('n_b')
    if _empty(nb):
        return auto_extra_cells(block.get('n_f'), block.get('pe')) if _num(block.get('o_b')) == CONTINUES else 0
    return int(_num(nb))


def effective_structure(block: Dict[str, Any]) -> Dict[str, Any]:
    """The structure the cells are built on (``effectiveStructure``): the
    semi-infinite outlet as extra cells closed by linear extrapolation, which
    stand for rock downstream. Idempotent."""
    ob = _num(block.get('o_b'))
    nf = int(_num(block.get('n_f')))
    nm = int(_num(block.get('n_m')))
    nb = extra_cells(block)
    if ob == CONTINUES:
        return {'n_f': nf, 'n_m': nm, 'o_b': 2, 'n_b': nb, 'downstream': True}
    return {'n_f': nf, 'n_m': nm, 'o_b': int(ob), 'n_b': nb, 'downstream': bool(block.get('downstream'))}


def cell_count(g: Dict[str, Any]) -> int:
    """How many cells one nuclide's path has, extra outflow cells included; one
    for a semi-analytical path (what it holds), none for any other way than
    cells (``uses_cells``)."""
    if is_semi_analytic(g):
        return 1
    if not uses_cells(g):
        return 0
    e = effective_structure(g)
    return (e['n_f'] + e['n_b']) * (e['n_m'] + 1)


def held_cells(block: Dict[str, Any]) -> int:
    """The cells whose inventory is the path's: all but a semi-infinite outlet's
    extra cells, which stand for rock past the release point."""
    if is_semi_analytic(block):
        return 1
    if not uses_cells(block):
        return 0
    e = effective_structure(block)
    return (e['n_f'] if e['downstream'] else e['n_f'] + e['n_b']) * (e['n_m'] + 1)


def path_grid(grid: Any, pen_dep: float, nm: int, first: Optional[float], aw: float, tw: float, pe: float,
              nucs: Sequence[Dict[str, float]]) -> Dict[str, Any]:
    """The matrix layout one path shares across its nuclides (``pathGrid``)."""
    if grid == 'matched':
        return matched_grid(pen_dep, nm, first, aw, tw, pe, nucs)
    return {'kind': 'reference', 'd': layer_depths(pen_dep, nm, aw, first), 'h': None, 'q': math.nan}


def cell_structure(g: Dict[str, Any]) -> Dict[str, Any]:
    """The (row, column) pairs the transport matrix fills, in cell numbering."""
    e = effective_structure(g)
    nf, nm, ob, nb = e['n_f'], e['n_m'], e['o_b'], e['n_b']
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
    e = effective_structure(g)
    nf, nm, ob, nb = e['n_f'], e['n_m'], e['o_b'], e['n_b']
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
    """The cells the release is read from (``get_release``); for the
    semi-infinite outlet, the plane at the release point itself."""
    e = effective_structure(g)
    nf, nm, nb, ob = e['n_f'], e['n_m'], e['n_b'], e['o_b']

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
    e = effective_structure(g)
    nb, ob = e['n_b'], e['o_b']
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
    # A semi-analytical path has no cells: the counts and the outlet are the
    # cells' settings and are not read.
    if is_semi_analytic(g):
        v = g.get('surface')
        return None if v is None or v == '' or v in SURFACES else f"surface must be one of {', '.join(SURFACES)}"
    def whole(key: str, least: int) -> Optional[str]:
        v = g.get(key)
        if not _is_whole(v):
            return f'{key} must be a whole number'
        if float(v) < least:
            return f'{key} must be at least {least}'
        return None

    for problem in (whole('n_f', 1), whole('n_m', 2), None if _empty(g.get('n_b')) else whole('n_b', 0)):
        if problem:
            return problem
    try:
        ob = float(g.get('o_b'))
    except (TypeError, ValueError):
        ob = math.nan
    if ob not in OUTFLOWS:
        return f"o_b must be one of {', '.join(map(str, OUTFLOWS))}"
    for key, allowed in (('method', FARF_METHODS), ('grid', GRIDS), ('surface', SURFACES)):
        v = g.get(key)
        if v is not None and v != '' and v not in allowed:
            return f"{key} must be one of {', '.join(allowed)}"
    e = effective_structure(g)
    ob, nf, nb = e['o_b'], e['n_f'], e['n_b']
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
    # Without layers the depth is the only geometry: the rock's own thickness.
    if is_semi_analytic(block):
        return 'the penetration depth must be a positive length' if math.isfinite(pen_dep) and not (pen_dep > 0) \
            else None
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
    # Worked out exactly, the path disperses as its Peclet number says.
    if is_semi_analytic(g):
        return None
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
    e = effective_structure(g)
    nf, nm, nb = e['n_f'], e['n_m'], e['n_b']
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
                 single: Sequence[str], release_base: int, keys: Optional[Sequence[str]] = None,
                 grid: str = 'reference', surface: str = 'f') -> None:
        self.structure = effective_structure(structure)
        self.base = base
        self.nnuc = nnuc
        self.other_width = other_width
        self.dim_off = np.asarray(dim_off, dtype=np.int64)
        self.single_off = np.asarray(single_off, dtype=np.int64)
        self.setting_base = setting_base
        self.is_single = set(single)
        self.release_base = release_base
        self.grid = 'matched' if grid == 'matched' else 'reference'
        self.surface = surface if surface in SURFACES else 'f'
        g = self.structure
        self.ncells = (g['n_f'] + g['n_b']) * (g['n_m'] + 1)
        st = cell_structure(g)
        self.rows, self.cols, self.nnz = st['rows'], st['cols'], st['nnz']
        self.rel_cells = np.array(release_cells(g), dtype=np.int64)
        self.nrel = len(self.rel_cells)
        self.slots = other_width * nnuc
        self.vals = np.zeros((self.slots, self.nnz))
        self.rel_w = np.zeros((self.slots, self.nrel))
        self.keys = tuple(keys) if keys is not None else FARF_EQUATION_KEYS
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
        # Each nuclide's decay constant, for the matched layers; and those
        # layers per combination, laid out once per run (``restart``).
        self.lam = np.zeros(nnuc)
        self.layers: List[Optional[Dict[str, Any]]] = [None] * other_width
        self.laid_out = np.zeros(other_width, dtype=bool)

    def set_decay(self, lam: Optional[np.ndarray]) -> None:
        """The decay constants the path's nuclides decay with, or None for none."""
        self.lam[:] = 0.0
        if lam is not None:
            n = min(self.nnuc, len(lam))
            self.lam[:n] = np.asarray(lam, dtype=float)[:n]
        self.restart()

    def restart(self) -> None:
        """Starts a run: the matched layers are laid out again at its first
        instant and held to its end (``FarfPath.restart``)."""
        self.laid_out[:] = False
        self.seen[:] = np.nan

    def _setting(self, X: np.ndarray, slot: int) -> Dict[str, Any]:
        g = self.structure
        s = {key: float(X[self.setting_idx[slot, k]]) for k, key in enumerate(self.keys)}
        s['nf'] = g['n_f']
        s['nm'] = g['n_m']
        s['surface'] = self.surface
        s['grid'] = self.grid
        s['lam'] = float(self.lam[slot % self.nnuc])
        if not (s['pen_dep_0'] > 0):
            s['pen_dep_0'] = None
        return s

    def _lay_out(self, X: np.ndarray, o: int) -> Dict[str, Any]:
        """The matched layers of one combination, from every nuclide on it."""
        first = self._setting(X, o * self.nnuc)
        aw = wetted_surface(first)
        nucs = []
        for m in range(self.nnuc):
            n = self._setting(X, o * self.nnuc + m)
            nucs.append({'de': n['de_m'], 'rm': n['eps_m'] + n['rho_m'] * n['kd_m'], 'lam': float(self.lam[m]),
                         'rf': 1 + n['kd_f'] * aw})
        return matched_grid(first['pen_dep'], first['nm'], first['pen_dep_0'], aw, first['tw'], first['pe'], nucs)

    def refresh(self, X: np.ndarray) -> None:
        """Works the rates out again for every slot whose settings moved."""
        probe = X[self.setting_idx]
        changed = np.any(probe != self.seen, axis=1)
        matched = self.grid == 'matched'
        fresh = (~self.laid_out) if matched else np.zeros(self.other_width, dtype=bool)
        if not changed.any() and not fresh.any():
            return
        g = self.structure
        for o in range(self.other_width):
            lo, hi = o * self.nnuc, (o + 1) * self.nnuc
            if not fresh[o] and not changed[lo:hi].any():
                continue
            if fresh[o]:
                self.layers[o] = self._lay_out(X, o)
            try:
                for slot in range(lo, hi):
                    if not fresh[o] and not changed[slot]:
                        continue
                    s = self._setting(X, slot)
                    c = coefficients(s, self.layers[o] if matched else None)
                    cell_values(g, c, self.vals[slot])
                    release_weights(g, c, self.rel_w[slot])
                    self.seen[slot] = probe[slot]
            except Exception:
                if fresh[o]:
                    self.laid_out[o] = False
                raise
            if fresh[o]:
                self.laid_out[o] = True

    def release(self, y: np.ndarray, X: np.ndarray) -> None:
        """The release out of the far end of every slot, into its slot of X:
        each slot's weighted sum added up one cell at a time from zero, in the
        cells' order, as the application adds it (``einsum`` may not)."""
        self.refresh(X)
        q = np.zeros(self.slots)
        for r in range(self.nrel):
            q += self.rel_w[:, r] * y[self.rel_idx[:, r]]
        X[self.release_slots] = q

    def transport_contributions(self, y: np.ndarray) -> np.ndarray:
        """The transport terms, ready for a weighted bincount over ``row_flat``."""
        return (self.vals * y[self.col_idx]).ravel()
