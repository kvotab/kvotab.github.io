"""Design of Experiments: the design tables of DOE > Classical (Full
Factorial, Screening, Response Surface) and DOE > Special Purpose (Space
Filling), and the diagnostics of DOE > Design Diagnostics > Evaluate Design.

  Full Factorial   every combination of the levels; continuous factors at
                   their low and high values, with optional center points
  Screening        two-level fractional factorials 2^(k-p) by generators
                   (the minimum-aberration designs of Box, Hunter and Hunter
                   and Montgomery's table), their resolution and aliases
                   computed from the defining relation; Plackett-Burman
                   designs of 12, 20 and 24 runs (the 1946 cyclic generators)
  Response Surface central composite designs (rotatable, orthogonal,
                   face-centred, spherical or a given axial distance, cube
                   portion a full or resolution V+ fractional factorial) and
                   Box-Behnken designs for 3 to 7 factors
  Space Filling    scipy.stats.qmc: Latin hypercube (optimised for the
                   centred discrepancy), Sobol, Halton, a uniform design
                   (minimum discrepancy) and a maximin (sphere packing) LHS
  Evaluate Design  in coded units (continuous -1 to +1, categorical effect
                   coded): the power of each term, the variance of the
                   coefficients, VIF, correlations and the alias matrix,
                   D, G and A efficiencies, the prediction variance profile
                   and the fraction of design space

numpy does the arithmetic; nothing here is statsmodels, which has no DOE,
except the VIF (statsmodels' variance_inflation_factor).
"""
import inspect
import itertools
import json
import math

import numpy as np
from scipy import stats
from scipy.stats import qmc

from . import data
from .registry import api
from .util import col, table as rtable

# ---------------------------------------------------------------------------
# Common pieces
# ---------------------------------------------------------------------------

ORDERS = ('randomize', 'sort_lr', 'sort_rl', 'keep')


def _seed(seed):
    if seed is None or seed == '':
        return int(np.random.default_rng().integers(1, 2 ** 31 - 1))
    return int(seed)


def _rng_kw(cls):
    """scipy's qmc engines take the generator as `rng` (1.15+) or `seed`."""
    try:
        params = inspect.signature(cls).parameters
    except (TypeError, ValueError):
        return 'seed'
    return 'rng' if 'rng' in params else 'seed'


def _order(n, order, seed, keys=None):
    """The run order: a permutation of range(n)."""
    if order == 'randomize':
        return np.random.default_rng(seed).permutation(n)
    if order in ('sort_lr', 'sort_rl') and keys is not None:
        k = np.asarray(keys)
        cols = [k[:, j] for j in range(k.shape[1])]
        if order == 'sort_lr':
            cols = cols[::-1]      # lexsort: the last key is the primary one
        return np.lexsort(cols)
    return np.arange(n)


def _clean_factors(factors):
    out = []
    names = set()
    for i, f in enumerate(factors or []):
        name = str(f.get('name') or f'X{i + 1}').strip() or f'X{i + 1}'
        if name in names:
            raise ValueError(f'two factors are called {name}')
        names.add(name)
        kind = f.get('kind') or 'continuous'
        if kind == 'continuous':
            lo = float(f.get('low', -1) if f.get('low') is not None else -1)
            hi = float(f.get('high', 1) if f.get('high') is not None else 1)
            if not lo < hi:
                raise ValueError(f'{name}: the low value must be below the high')
            out.append({'name': name, 'kind': 'continuous', 'low': lo, 'high': hi})
        else:
            levels = [str(v) for v in (f.get('levels') or []) if str(v).strip() != '']
            if len(levels) < 2:
                raise ValueError(f'{name}: a categorical factor needs two or more levels')
            if len(set(levels)) != len(levels):
                raise ValueError(f'{name}: the levels must differ')
            out.append({'name': name, 'kind': 'categorical', 'levels': levels})
    if not out:
        raise ValueError('add at least one factor')
    return out


def _decode(f, coded):
    """Coded values (-1..+1, or level indices for categorical) to settings."""
    if f['kind'] == 'continuous':
        mid, half = (f['low'] + f['high']) / 2, (f['high'] - f['low']) / 2
        return [float(round(mid + half * c, 12)) for c in coded]
    return [f['levels'][int(c)] for c in coded]


def _coding_note(f):
    if f['kind'] == 'continuous':
        return f'Coding [low, high]: {f["low"]:.10g}, {f["high"]:.10g}'
    return 'Levels: ' + ', '.join(f['levels'])


def _responses(responses):
    out = []
    for i, r in enumerate(responses or [{'name': 'Y'}]):
        name = str((r or {}).get('name') or f'Y{i + 1 if i else ""}').strip() or 'Y'
        out.append({'name': name, 'goal': (r or {}).get('goal') or 'Maximize'})
    return out


def _table_out(design_name, factors, coded, pattern, responses, order, seed, notes, extra_cols=None, code=''):
    """The columns of a design table, in run order."""
    n = len(pattern)
    perm = _order(n, order, seed, keys=np.asarray(coded, dtype=float))
    cols = [{'name': 'Pattern', 'dataType': 'character', 'modelingType': 'nominal', 'values': [pattern[i] for i in perm],
             'notes': 'The run\'s levels: − low, + high, 0 center, a and A the axial points, a number the level of a categorical factor.'}]
    for j, f in enumerate(factors):
        vals = _decode(f, [coded[i][j] for i in perm]) if f['kind'] == 'continuous' else [f['levels'][int(coded[i][j])] for i in perm]
        cols.append({'name': f['name'], 'dataType': 'numeric' if f['kind'] == 'continuous' else 'character',
                     'modelingType': 'continuous' if f['kind'] == 'continuous' else 'nominal', 'values': vals,
                     'valueOrder': f['levels'] if f['kind'] == 'categorical' else None, 'notes': f'Factor. {_coding_note(f)}'})
    for c in (extra_cols or []):
        cols.append({**c, 'values': [c['values'][i] for i in perm]})
    for r in responses:
        cols.append({'name': r['name'], 'dataType': 'numeric', 'modelingType': 'continuous', 'values': [None] * n,
                     'notes': f'Response. Goal: {r["goal"]}.'})
    order_text = {'randomize': f'randomized (seed {seed})', 'sort_lr': 'sorted left to right', 'sort_rl': 'sorted right to left', 'keep': 'in standard order'}[order]
    return {'name': design_name, 'columns': cols, 'n_runs': n, 'seed': seed, 'order': order,
            'notes': ' '.join(notes + [f'Runs {order_text}.']), 'code': code}


# ---------------------------------------------------------------------------
# Full factorial
# ---------------------------------------------------------------------------

def _pattern_char(f, c):
    if f['kind'] == 'continuous':
        return {-1: '−', 1: '+', 0: '0'}.get(int(round(c)), '?')
    return str(int(c) + 1)


@api('doe.full_factorial')
def full_factorial(factors, responses=None, replicates=0, center_points=0, order='randomize', seed=None):
    fs = _clean_factors(factors)
    resp = _responses(responses)
    seed = _seed(seed)
    order = order if order in ORDERS else 'randomize'
    levels = [[-1, 1] if f['kind'] == 'continuous' else list(range(len(f['levels']))) for f in fs]
    base = [list(c) for c in itertools.product(*levels)]
    reps = max(0, int(replicates or 0))
    coded = [list(r) for _ in range(reps + 1) for r in base]
    ncp = max(0, int(center_points or 0))
    cont = [j for j, f in enumerate(fs) if f['kind'] == 'continuous']
    notes = [f'Full factorial design: {len(base)} combinations' + (f' × {reps + 1} (replicates)' if reps else '') + '.']
    if ncp and cont:
        for i in range(ncp):
            coded.append([0 if f['kind'] == 'continuous' else i % len(f['levels']) for f in fs])
        notes.append(f'{ncp} center point{"s" if ncp > 1 else ""}' + (' (the categorical factors cycle through their levels).' if len(cont) < len(fs) else '.'))
    elif ncp:
        notes.append('Center points need a continuous factor; none were added.')
    pattern = [''.join(_pattern_char(f, c) for f, c in zip(fs, run)) for run in coded]
    code = '\n'.join(['import itertools, numpy as np, pandas as pd',
                      f'levels = {json.dumps({f["name"]: ([f["low"], f["high"]] if f["kind"] == "continuous" else f["levels"]) for f in fs})}',
                      f'd = pd.DataFrame(list(itertools.product(*levels.values())) * {reps + 1}, columns=list(levels))',
                      f'd = d.sample(frac=1, random_state={seed}).reset_index(drop=True)   # randomized' if order == 'randomize' else 'print(d)'])
    return _table_out('Full Factorial', fs, coded, pattern, resp, order, seed, notes, code=code)


# ---------------------------------------------------------------------------
# Two-level screening: fractional factorials and Plackett-Burman
# ---------------------------------------------------------------------------

# Generators of the 2^(k-p) designs: for k factors and 2^m runs (m = k - p),
# the added factors as products of the base factors (0-based), after Box,
# Hunter and Hunter (1978, table 12.15) and Montgomery (Design and Analysis
# of Experiments, table 8.14). The resolution is computed, not trusted.
GENERATORS = {
    3: {4: [(0, 1)]},
    4: {8: [(0, 1, 2)]},
    5: {16: [(0, 1, 2, 3)], 8: [(0, 1), (0, 2)]},
    6: {32: [(0, 1, 2, 3, 4)], 16: [(0, 1, 2), (1, 2, 3)], 8: [(0, 1), (0, 2), (1, 2)]},
    7: {64: [(0, 1, 2, 3, 4, 5)], 32: [(0, 1, 2, 3), (0, 1, 3, 4)], 16: [(0, 1, 2), (1, 2, 3), (0, 2, 3)], 8: [(0, 1), (0, 2), (1, 2), (0, 1, 2)]},
    8: {64: [(0, 1, 2, 3), (0, 1, 4, 5)], 32: [(0, 1, 2), (0, 1, 3), (1, 2, 3, 4)], 16: [(1, 2, 3), (0, 2, 3), (0, 1, 2), (0, 1, 3)]},
    9: {128: [(0, 2, 3, 5, 6), (1, 2, 4, 5, 6)], 64: [(0, 1, 2, 3), (0, 2, 4, 5), (2, 3, 4, 5)], 32: [(1, 2, 3, 4), (0, 2, 3, 4), (0, 1, 3, 4), (0, 1, 2, 4)],
        16: [(0, 1, 2), (1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2, 3)]},
    10: {128: [(0, 1, 2, 6), (1, 2, 3, 4), (0, 2, 3, 5)], 64: [(1, 2, 3, 5), (0, 2, 3, 5), (0, 1, 3, 4), (0, 1, 2, 4)],
         32: [(0, 1, 2, 3), (0, 1, 2, 4), (0, 1, 3, 4), (0, 2, 3, 4), (1, 2, 3, 4)], 16: [(0, 1, 2), (1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2, 3), (0, 1)]},
    11: {128: [(0, 1, 2, 6), (1, 2, 3, 4), (0, 2, 3, 5), (0, 1, 2, 3, 4, 5, 6)], 64: [(2, 3, 4), (0, 1, 2, 3), (0, 1, 5), (1, 3, 4, 5), (0, 3, 4, 5)],
         32: [(0, 1, 2), (1, 2, 3), (2, 3, 4), (0, 2, 3), (0, 3, 4), (1, 3, 4)], 16: [(0, 1, 2), (1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2, 3), (0, 1), (0, 2)]},
}

# Plackett and Burman (1946): the first row of the cyclic designs; the last
# run is every factor low.
PB_ROWS = {12: '++-+++---+-', 20: '++--++++-+-+----++-', 24: '+++++-+-++--++--+-+----'}
ROMAN = {1: 'I', 2: 'II', 3: 'III', 4: 'IV', 5: 'V', 6: 'VI', 7: 'VII', 8: 'VIII', 9: 'IX', 10: 'X', 11: 'XI', 12: 'XII'}


def _words(k, m, gens):
    """The defining relation: every product of the generator words, as sets
    of factor indices (the generated factor j = m + i is word gens[i] + j)."""
    base = [frozenset(g) | {m + i} for i, g in enumerate(gens)]
    words = set()
    for r in range(1, len(base) + 1):
        for combo in itertools.combinations(base, r):
            w = frozenset()
            for b in combo:
                w = w ^ b
            words.add(w)
    return sorted(words, key=lambda w: (len(w), sorted(w)))


def resolution(k, m, gens):
    ws = _words(k, m, gens)
    return min(len(w) for w in ws) if ws else None


def word_length_pattern(k, m, gens):
    ws = _words(k, m, gens)
    out = [0] * (k + 1)
    for w in ws:
        out[len(w)] += 1
    return out[3:]


def _ff_matrix(k, m, gens):
    """The 2^m runs in standard order (the first factor changing fastest, as
    Yates), base factors and generated ones, coded -1/+1."""
    runs = np.array(list(itertools.product([-1, 1], repeat=m)))[:, ::-1]
    cols = [runs[:, j] for j in range(m)]
    for g in gens:
        cols.append(np.prod(runs[:, list(g)], axis=1))
    return np.column_stack(cols).astype(int)


def _pb_matrix(N):
    row = np.array([1 if c == '+' else -1 for c in PB_ROWS[N]])
    rows = [np.roll(row, i) for i in range(N - 1)] + [-np.ones(N - 1, dtype=int)]
    return np.array(rows, dtype=int)


def _greedy_gens(k, m):
    """Generators for a 2^(k-p) design not in the table: the largest
    interactions of the base factors first, keeping the resolution high."""
    cands = []
    for r in range(m, 1, -1):
        cands += [c for c in itertools.combinations(range(m), r)]
    chosen = []
    for _ in range(k - m):
        best, best_key = None, None
        for c in cands:
            if c in chosen:
                continue
            trial = chosen + [c]
            key = (resolution(m + len(trial), m, trial) or 99, -sum(word_length_pattern(m + len(trial), m, trial)[:1]))
            if best_key is None or key > best_key:
                best, best_key = c, key
        if best is None:
            return None
        chosen.append(best)
    return chosen


def _screening_list(k):
    out = []
    if k < 2:
        return out
    if 2 ** k <= 128:
        out.append({'key': 'full', 'runs': 2 ** k, 'type': 'Full Factorial', 'resolution': 'Full', 'res': 99})
    for m in range(int(math.ceil(math.log2(k + 1))), k):
        runs = 2 ** m
        if runs > 128:
            continue
        gens = GENERATORS.get(k, {}).get(runs)
        if gens is None:
            if k - m == 1:
                gens = [tuple(range(m))]
            elif k <= 11 and k - m <= 6:
                gens = _greedy_gens(k, m)   # not reached for the table's designs
            else:
                continue   # past 11 factors: the defining relation has 2^(k-m) words; Plackett-Burman instead
        if not gens:
            continue
        res = resolution(k, m, gens)
        if res is None or res < 3:
            continue
        out.append({'key': f'ff:{runs}', 'runs': runs, 'type': 'Fractional Factorial', 'resolution': ROMAN.get(res, str(res)), 'res': res,
                    'generators': [list(g) for g in gens], 'wlp': word_length_pattern(k, m, gens)})
    for N in (12, 20, 24):
        if k <= N - 1 and N < 2 ** k:
            out.append({'key': f'pb:{N}', 'runs': N, 'type': 'Plackett-Burman', 'resolution': 'III', 'res': 3})
    out.sort(key=lambda d: (d['runs'], d['type']))
    return out


@api('doe.screening_designs')
def screening_designs(n_factors):
    k = int(n_factors)
    return {'designs': _screening_list(k), 'k': k}


def _effect_name(names, s):
    return '*'.join(names[i] for i in sorted(s))


@api('doe.screening')
def screening(factors, design='auto', responses=None, center_points=0, replicates=0, order='randomize', seed=None, max_order=3):
    fs = _clean_factors(factors)
    for f in fs:
        if f['kind'] == 'categorical' and len(f['levels']) != 2:
            raise ValueError(f'{f["name"]}: a screening design takes two-level factors')
    k = len(fs)
    if k < 2:
        raise ValueError('a screening design needs two or more factors')
    resp = _responses(responses)
    seed = _seed(seed)
    order = order if order in ORDERS else 'randomize'
    designs = _screening_list(k)
    if not designs:
        raise ValueError('no screening design for this many factors')
    if design == 'auto' or design is None:
        # the smallest design of resolution IV or better, else the smallest
        good = [d for d in designs if d['res'] >= 4]
        d = good[0] if good else designs[0]
    else:
        d = next((x for x in designs if x['key'] == design), None)
        if d is None:
            raise ValueError(f'no design {design} for {k} factors')
    names = [f['name'] for f in fs]
    aliases = []
    words = []
    if d['key'] == 'full':
        X = np.array(list(itertools.product([-1, 1], repeat=k)))[:, ::-1]
        notes = [f'Full factorial 2^{k}: {2 ** k} runs, every interaction estimable.']
        gen_text = []
    elif d['key'].startswith('ff:'):
        m = int(round(math.log2(d['runs'])))
        gens = [tuple(g) for g in d['generators']]
        X = _ff_matrix(k, m, gens)
        ws = _words(k, m, gens)
        words = ['I = ' + '*'.join(names[i] for i in sorted(w)) for w in ws]
        gen_text = [f'{names[m + i]} = {"*".join(names[j] for j in g)}' for i, g in enumerate(gens)]
        # the aliases of the main effects and two-factor interactions, up to max_order
        effects = [frozenset([i]) for i in range(k)] + [frozenset(c) for c in itertools.combinations(range(k), 2)]
        seen = set()
        for e in effects:
            if e in seen:
                continue
            al = sorted({e ^ w for w in ws}, key=lambda s: (len(s), sorted(s)))
            al = [a for a in al if len(a) <= int(max_order)]
            group = [e] + [a for a in al if a != e]
            for a in group:
                seen.add(a)
            others = [a for a in group if a != e]
            if others:
                aliases.append({'effect': _effect_name(names, e), 'aliases': ' = '.join(_effect_name(names, a) for a in others)})
        notes = [f'Fractional factorial 2^({k}−{k - m}), {d["runs"]} runs, resolution {d["resolution"]}. Generators: {"; ".join(gen_text)}.']
    else:
        N = int(d['key'].split(':')[1])
        X = _pb_matrix(N)[:, :k]
        gen_text = [f'first row {PB_ROWS[N][:N - 1]}, cycled; the last run all low']
        notes = [f'Plackett-Burman design, {N} runs, resolution III: every main effect is partially aliased with the two-factor interactions that do not contain it (coefficients ±1/3 for 12 runs); Evaluate Design shows the alias matrix.']
    coded = [[int(v) if fs[j]['kind'] == 'continuous' else (0 if v < 0 else 1) for j, v in enumerate(r)] for r in X]
    reps = max(0, int(replicates or 0))
    coded = [list(r) for _ in range(reps + 1) for r in coded]
    ncp = max(0, int(center_points or 0))
    if ncp and any(f['kind'] == 'continuous' for f in fs):
        for i in range(ncp):
            coded.append([0 if f['kind'] == 'continuous' else i % 2 for f in fs])
        notes.append(f'{ncp} center point{"s" if ncp > 1 else ""}.')
    if reps:
        notes.append(f'{reps} replicate{"s" if reps > 1 else ""} of the design.')
    pattern = [''.join(('−' if c < 0 else '+' if c > 0 else '0') if f['kind'] == 'continuous' else ('−' if c == 0 else '+') for f, c in zip(fs, run)) for run in coded]
    if aliases:
        notes.append('Aliases: ' + '; '.join(f'{a["effect"]} = {a["aliases"]}' for a in aliases[:40]) + ('; …' if len(aliases) > 40 else '') + '.')
    code = ['import itertools, numpy as np']
    if d['key'].startswith('ff:'):
        m = int(round(math.log2(d['runs'])))
        code += [f'base = np.array(list(itertools.product([-1, 1], repeat={m})))[:, ::-1]   # {2 ** m} runs, standard order',
                 f'gens = {json.dumps([list(g) for g in d["generators"]])}   # {"; ".join(gen_text)}',
                 'X = np.column_stack([base] + [base[:, g].prod(axis=1) for g in gens])',
                 'print(X.T @ X)   # orthogonal columns: len(X) on the diagonal, 0 elsewhere']
    elif d['key'].startswith('pb:'):
        N = int(d['key'].split(':')[1])
        code += [f'row = np.array([1 if c == "+" else -1 for c in "{PB_ROWS[N]}"])',
                 f'X = np.vstack([np.roll(row, i) for i in range({N - 1})] + [-np.ones({N - 1}, int)])[:, :{k}]', 'print(X.T @ X)']
    else:
        code += [f'X = np.array(list(itertools.product([-1, 1], repeat={k})))', 'print(X.T @ X)']
    out = _table_out('Screening Design', fs, coded, pattern, resp, order, seed, notes, code='\n'.join(code))
    out['design'] = {k2: v for k2, v in d.items()}
    out['aliases'] = aliases
    out['defining_relation'] = words
    out['generators'] = gen_text
    return out


# ---------------------------------------------------------------------------
# Response surface designs
# ---------------------------------------------------------------------------

CCD_CENTER = {2: 5, 3: 6, 4: 7, 5: 6, 6: 9, 7: 14, 8: 20}
BBD_CENTER = {3: 3, 4: 3, 5: 6, 6: 6, 7: 6}
# Box and Behnken (1960): the groups of factors varied together (+-1) in each
# block of runs, the others at 0. Three, four and five factors: every pair;
# six: the partially balanced design in triples; seven: the Fano plane.
BBD_BLOCKS = {
    6: [(0, 1, 3), (1, 2, 4), (2, 3, 5), (0, 3, 4), (1, 4, 5), (0, 2, 5)],
    7: [(3, 4, 5), (0, 5, 6), (1, 4, 6), (0, 1, 3), (2, 3, 6), (0, 2, 4), (1, 2, 5)],
}


def _ccd_cube(k):
    """The cube portion of a CCD: a full factorial for up to 4 factors, else
    a fraction of resolution V or better."""
    if k <= 4:
        return np.array(list(itertools.product([-1, 1], repeat=k)))[:, ::-1], 'full factorial'
    m = {5: 4, 6: 5, 7: 6, 8: 6}[k]
    gens = GENERATORS[k][2 ** m]
    return _ff_matrix(k, m, [tuple(g) for g in gens]), f'2^({k}−{k - m}) resolution {ROMAN[resolution(k, m, gens)]} fraction'


def ccd_alpha(k, axial, n_center, alpha=None):
    F = len(_ccd_cube(k)[0])
    if axial == 'rotatable':
        return F ** 0.25
    if axial == 'orthogonal':
        T = 2 * k + n_center
        return ((F * (math.sqrt(F + T) - math.sqrt(F)) ** 2) / 4) ** 0.25
    if axial == 'face':
        return 1.0
    if axial == 'spherical':
        return math.sqrt(k)
    if axial == 'custom':
        if alpha is None or not float(alpha) > 0:
            raise ValueError('give the axial distance α')
        return float(alpha)
    raise ValueError(f'unknown axial value {axial}')


@api('doe.rsm_designs')
def rsm_designs(n_factors):
    k = int(n_factors)
    out = []
    if 3 <= k <= 7:
        runs = {3: 12, 4: 24, 5: 40, 6: 48, 7: 56}[k]
        out.append({'key': 'bbd', 'label': 'Box-Behnken', 'runs': runs + BBD_CENTER[k], 'center': BBD_CENTER[k], 'blocks': 1})
    if 2 <= k <= 8:
        F = len(_ccd_cube(k)[0])
        for ax, label in (('rotatable', 'CCD, rotatable'), ('orthogonal', 'CCD, orthogonal'), ('face', 'CCD, face centred'), ('spherical', 'CCD, spherical')):
            out.append({'key': f'ccd:{ax}', 'label': label, 'runs': F + 2 * k + CCD_CENTER[k], 'center': CCD_CENTER[k],
                        'alpha': ccd_alpha(k, ax, CCD_CENTER[k]), 'cube': _ccd_cube(k)[1]})
    return {'designs': out, 'k': k}


@api('doe.rsm')
def rsm(factors, design='ccd:rotatable', responses=None, center_points=None, alpha=None, inscribe=False, replicates=0,
        order='randomize', seed=None):
    fs = _clean_factors(factors)
    if any(f['kind'] != 'continuous' for f in fs):
        raise ValueError('a response surface design takes continuous factors only')
    k = len(fs)
    resp = _responses(responses)
    seed = _seed(seed)
    order = order if order in ORDERS else 'randomize'
    kind, _, axial = (design or 'ccd:rotatable').partition(':')
    notes = []
    pattern = []
    if kind == 'bbd':
        if not 3 <= k <= 7:
            raise ValueError('Box-Behnken designs are for 3 to 7 factors')
        nc = BBD_CENTER[k] if center_points is None else max(0, int(center_points))
        groups = list(itertools.combinations(range(k), 2)) if k <= 5 else BBD_BLOCKS[k]
        pts = []
        for g in groups:
            for signs in itertools.product([-1, 1], repeat=len(g)):
                r = [0] * k
                for j, s in zip(g, signs):
                    r[j] = s
                pts.append(r)
        X = np.array(pts, dtype=float)
        pattern = [''.join('−' if v < 0 else '+' if v > 0 else '0' for v in r) for r in X]
        notes.append(f'Box-Behnken design for {k} factors: {len(X)} runs on the edges' + (' (every pair of factors)' if k <= 5 else ' (Box and Behnken\'s groups of three)') + f', plus {nc} center points.')
        alpha_used = None
    elif kind == 'ccd':
        nc = CCD_CENTER.get(k, 6) if center_points is None else max(0, int(center_points))
        if not 2 <= k <= 8:
            raise ValueError('central composite designs here are for 2 to 8 factors')
        cube, cube_label = _ccd_cube(k)
        a = ccd_alpha(k, axial or 'rotatable', nc, alpha)
        ax = []
        ax_pat = []
        for j in range(k):
            for s in (-1, 1):
                r = [0.0] * k
                r[j] = s * a
                ax.append(r)
                ax_pat.append(''.join(('a' if s < 0 else 'A') if i == j else '0' for i in range(k)))
        X = np.vstack([cube.astype(float), np.array(ax)])
        pattern = [''.join('−' if v < 0 else '+' for v in r) for r in cube] + ax_pat
        if inscribe:
            X = X / a
            notes.append(f'Inscribed: the design is shrunk by 1/α so the axial points lie at the factor limits and the cube at ±{1 / a:.4g}.')
        notes.append(f'Central composite design, {axial or "rotatable"}: the cube is a {cube_label} ({len(cube)} runs), {2 * k} axial points at α = {a:.6g}, and {nc} center points.')
        alpha_used = a
    else:
        raise ValueError(f'unknown design {design}')
    reps = max(0, int(replicates or 0))
    X = np.vstack([X] * (reps + 1))
    pattern = pattern * (reps + 1)
    X = np.vstack([X, np.zeros((nc, k))]) if nc else X
    pattern += ['0' * k] * nc
    coded = X.tolist()
    code = ['import itertools, numpy as np']
    if kind == 'ccd':
        code += [f'k, alpha, n0 = {k}, {alpha_used!r}, {nc}']
        if k <= 4:
            code.append('cube = np.array(list(itertools.product([-1, 1], repeat=k)))')
        else:
            m_ = int(round(math.log2(len(_ccd_cube(k)[0]))))
            code += [f'base = np.array(list(itertools.product([-1, 1], repeat={m_})))[:, ::-1]',
                     f'gens = {json.dumps([list(g) for g in GENERATORS[k][2 ** m_]])}   # the added factors as products of the base ones',
                     'cube = np.column_stack([base] + [base[:, g].prod(axis=1) for g in gens])   # a resolution V+ fraction']
        code += ['axial = np.vstack([s * alpha * np.eye(k)[j] for j in range(k) for s in (-1, 1)])',
                 'X = np.vstack([cube, axial, np.zeros((n0, k))])   # coded units',
                 'print(X.shape)']
    else:
        if k <= 5:
            code += [f'k, n0 = {k}, {nc}',
                     'X = np.array([[s1 if i == a else s2 if i == b else 0 for i in range(k)] for a, b in itertools.combinations(range(k), 2) for s1 in (-1, 1) for s2 in (-1, 1)] + [[0] * k] * n0)']
        else:
            code += [f'k, n0, groups = {k}, {nc}, {json.dumps([list(g) for g in BBD_BLOCKS[k]])}   # Box and Behnken\'s groups of three',
                     'X = np.array([[dict(zip(g, s)).get(i, 0) for i in range(k)] for g in groups for s in itertools.product([-1, 1], repeat=3)] + [[0] * k] * n0)']
        code.append('print(X.shape)')
    out = _table_out('Response Surface Design', fs, coded, pattern, resp, order, seed, notes, code='\n'.join(code))
    out['alpha'] = alpha_used
    return out


# ---------------------------------------------------------------------------
# Space filling
# ---------------------------------------------------------------------------

def _maximin_lhs(n, d, rng, iters=None):
    """A Latin hypercube improved by swaps within columns that raise the
    smallest distance between points (a simple sphere-packing search)."""
    kw = {_rng_kw(qmc.LatinHypercube): rng}
    x = qmc.LatinHypercube(d, **kw).random(n)
    if n < 3:
        return x
    D = np.sqrt(((x[:, None, :] - x[None, :, :]) ** 2).sum(-1))
    np.fill_diagonal(D, np.inf)
    iters = iters or min(4000, 60 * n)
    for _ in range(iters):
        i, j = rng.choice(n, 2, replace=False)
        c = rng.integers(d)
        y = x.copy()
        y[[i, j], c] = y[[j, i], c]
        Di = np.sqrt(((y[i] - y) ** 2).sum(-1))
        Dj = np.sqrt(((y[j] - y) ** 2).sum(-1))
        Di[i], Dj[j] = np.inf, np.inf
        E = D.copy()
        E[i, :], E[:, i] = Di, Di
        E[j, :], E[:, j] = Dj, Dj
        E[i, i] = E[j, j] = np.inf
        if E.min() > D.min() or (E.min() == D.min() and (E == E.min()).sum() < (D == D.min()).sum()):
            x, D = y, E
    return x


@api('doe.space_filling')
def space_filling(factors, n_runs=20, method='lhs', responses=None, seed=None):
    fs = _clean_factors(factors)
    if any(f['kind'] != 'continuous' for f in fs):
        raise ValueError('a space filling design takes continuous factors only')
    n = int(n_runs)
    if n < 2:
        raise ValueError('ask for two or more runs')
    d = len(fs)
    resp = _responses(responses)
    seed = _seed(seed)
    rng = np.random.default_rng(seed)
    notes = []
    if method == 'lhs':
        eng = qmc.LatinHypercube(d, optimization='random-cd', **{_rng_kw(qmc.LatinHypercube): rng})
        u = eng.random(n)
        label = 'Latin hypercube, optimised for the centred L2 discrepancy (scipy random-cd)'
    elif method == 'sobol':
        eng = qmc.Sobol(d, scramble=True, **{_rng_kw(qmc.Sobol): rng})
        m = int(round(math.log2(n)))
        u = eng.random_base2(m) if 2 ** m == n else eng.random(n)
        label = 'scrambled Sobol sequence'
        if 2 ** m != n:
            notes.append('A Sobol sequence is balanced for a power of two runs.')
    elif method == 'halton':
        u = qmc.Halton(d, scramble=True, **{_rng_kw(qmc.Halton): rng}).random(n)
        label = 'scrambled Halton sequence'
    elif method == 'uniform':
        try:
            u = qmc.Halton(d, scramble=True, optimization='random-cd', **{_rng_kw(qmc.Halton): rng}).random(n)
        except TypeError:
            u = qmc.LatinHypercube(d, optimization='random-cd', **{_rng_kw(qmc.LatinHypercube): rng}).random(n)
        label = 'uniform design: a scrambled Halton sequence optimised for the centred L2 discrepancy'
    elif method == 'maximin':
        u = _maximin_lhs(n, d, rng)
        label = 'sphere packing: a Latin hypercube with the smallest distance between points made large (maximin)'
    else:
        raise ValueError(f'unknown method {method}')
    lo = np.array([f['low'] for f in fs])
    hi = np.array([f['high'] for f in fs])
    X = qmc.scale(u, lo, hi)
    disc = float(qmc.discrepancy(u, method='CD'))
    dmin = float(np.min(np.sqrt(((u[:, None, :] - u[None, :, :]) ** 2).sum(-1))[~np.eye(n, dtype=bool)])) if n > 1 else None
    notes = [f'Space filling design, {n} runs: {label}.', f'Centred L2 discrepancy {disc:.4g}; smallest distance between points {dmin:.4g} (in the unit cube).'] + notes
    cols = [{'name': f['name'], 'dataType': 'numeric', 'modelingType': 'continuous', 'values': [float(v) for v in X[:, j]], 'notes': f'Factor. {_coding_note(f)}'} for j, f in enumerate(fs)]
    for r in resp:
        cols.append({'name': r['name'], 'dataType': 'numeric', 'modelingType': 'continuous', 'values': [None] * n, 'notes': f'Response. Goal: {r["goal"]}.'})
    kw = _rng_kw(qmc.LatinHypercube)   # the scipy of the engine: rng (1.15+) or seed
    engine = {'lhs': f'qmc.LatinHypercube(d, optimization="random-cd", {kw}=rng)', 'sobol': f'qmc.Sobol(d, scramble=True, {kw}=rng)',
              'halton': f'qmc.Halton(d, scramble=True, {kw}=rng)', 'uniform': f'qmc.Halton(d, scramble=True, optimization="random-cd", {kw}=rng)',
              'maximin': f'qmc.LatinHypercube(d, {kw}=rng)'}[method]
    lines = ['import numpy as np', 'from scipy.stats import qmc', f'd, n, rng = {d}, {n}, np.random.default_rng({seed})', f'u = {engine}.random(n)']
    if method == 'maximin':
        lines += ['dist = lambda x: np.sqrt(((x[:, None, :] - x[None, :, :]) ** 2).sum(-1)) + np.diag(np.full(len(x), np.inf))',
                  'D = dist(u)',
                  f'for _ in range({min(4000, 60 * n)}):   # swaps within a column that raise the smallest distance',
                  '    i, j = rng.choice(n, 2, replace=False); c = rng.integers(d)',
                  '    y = u.copy(); y[[i, j], c] = y[[j, i], c]; E = dist(y)',
                  '    if E.min() > D.min() or (E.min() == D.min() and (E == E.min()).sum() < (D == D.min()).sum()): u, D = y, E']
    lines += [f'X = qmc.scale(u, {lo.tolist()!r}, {hi.tolist()!r})', 'print(qmc.discrepancy(u, method="CD"))']
    code = '\n'.join(lines)
    # the seed, drawn or given, so that the design can be made again
    return {'name': 'Space Filling Design', 'columns': cols, 'n_runs': n, 'seed': seed, 'notes': ' '.join(notes + [f'Random seed {seed}.']), 'discrepancy': disc, 'min_distance': dmin, 'code': code}


# ---------------------------------------------------------------------------
# Evaluate Design
# ---------------------------------------------------------------------------

class _Model:
    """The model matrix of a design in coded units, with JMP's term names."""

    def __init__(self, factors):
        self.factors = factors          # [{'name', 'kind', 'low', 'high'} | {'name', 'kind': 'categorical', 'levels'}]

    def columns(self, f, values):
        if f['kind'] == 'continuous':
            mid, half = (f['low'] + f['high']) / 2, (f['high'] - f['low']) / 2
            return [((np.asarray(values, dtype=float) - mid) / half, f['name'])]
        lv = f['levels']
        v = np.asarray(values, dtype=object)
        out = []
        for i, lev in enumerate(lv[:-1]):
            col_ = np.where(v == lev, 1.0, np.where(v == lv[-1], -1.0, 0.0))
            out.append((col_, f'{f["name"]}[{lev}]'))
        return out

    def matrix(self, frame, terms):
        """frame: {factor name: values}; terms: tuples of factor indices, a
        repeated index a power. Returns X, the parameter names and, for each
        term, the slice of its columns."""
        n = len(next(iter(frame.values())))
        cols = [np.ones(n)]
        names = ['Intercept']
        slices = [(0, 1)]
        base = {j: self.columns(f, frame[f['name']]) for j, f in enumerate(self.factors)}
        for t in terms:
            parts = [base[j] for j in t]
            start = len(cols)
            for combo in itertools.product(*parts):
                v = np.ones(n)
                for c, _nm in combo:
                    v = v * c
                cols.append(v)
                names.append('*'.join(nm for _c, nm in combo))
            slices.append((start, len(cols)))
        return np.column_stack(cols), names, slices


def _terms(factors, model):
    k = len(factors)
    cont = [j for j, f in enumerate(factors) if f['kind'] == 'continuous']
    main = [(j,) for j in range(k)]
    two = [c for c in itertools.combinations(range(k), 2)]
    if model == 'main':
        return main, two
    if model == '2fi':
        return main + two, [c for c in itertools.combinations(range(k), 3)] if k <= 8 else []
    if model == 'rsm':
        quad = [(j, j) for j in cont]
        return main + two + quad, [c for c in itertools.combinations(range(k), 3)] if k <= 6 else []
    if model == 'full':
        full = [c for r in range(1, k + 1) for c in itertools.combinations(range(k), r)]
        return full, []
    raise ValueError(f'unknown model {model}')


def _term_label(factors, t):
    return '*'.join(factors[j]['name'] for j in t)


def _space_sample(factors, m, rng):
    """m points of the design space in settings: continuous uniform over
    the coded cube [-1, 1] (Sobol, scrambled), categorical levels equally
    likely."""
    cont = [f for f in factors if f['kind'] == 'continuous']
    frame = {}
    if cont:
        u = qmc.Sobol(len(cont), scramble=True, **{_rng_kw(qmc.Sobol): rng}).random(m)
        for i, f in enumerate(cont):
            frame[f['name']] = f['low'] + (f['high'] - f['low']) * u[:, i]
    for f in factors:
        if f['kind'] != 'continuous':
            frame[f['name']] = np.array(f['levels'], dtype=object)[rng.integers(len(f['levels']), size=m)]
    return frame


def _corners(factors):
    grids = [[f['low'], f['high']] if f['kind'] == 'continuous' else f['levels'] for f in factors]
    if np.prod([len(g) for g in grids]) > 4096:
        return None
    pts = list(itertools.product(*grids))
    return {f['name']: np.array([p[j] for p in pts], dtype=float if f['kind'] == 'continuous' else object) for j, f in enumerate(factors)}


@api('doe.evaluate')
def evaluate(table, factors, rows=None, model='main', alpha=0.05, rmse=1.0, coefficient=1.0, coding=None, table_name='data'):
    """factors: column names; coding: {name: [low, high]} for continuous
    factors (else the column's range)."""
    coding = coding or {}
    df = data.frame(table, factors, rows, dropna=True, as_category=True)
    if len(df) < 2:
        return {'error': 'fewer than two runs with every factor'}
    fs = []

    def lab(v):
        if isinstance(v, (float, np.floating)) and float(v).is_integer():
            return str(int(v))
        return str(v)
    for name in factors:
        s = df[name]
        if hasattr(s, 'cat'):
            lv = [lab(v) for v in s.cat.remove_unused_categories().cat.categories]
            fs.append({'name': name, 'kind': 'categorical', 'levels': lv})
            df[name] = s.astype(object).map(lab)
        else:
            lo, hi = (coding.get(name) or [float(s.min()), float(s.max())])[:2]
            if not float(hi) > float(lo):
                return {'error': f'{name} has a single value: it is not a factor of this design'}
            fs.append({'name': name, 'kind': 'continuous', 'low': float(lo), 'high': float(hi)})
    terms, alias_terms = _terms(fs, model)
    M = _Model(fs)
    frame = {f['name']: df[f['name']].to_numpy() for f in fs}
    X, names, slices = M.matrix(frame, terms)
    N, p = X.shape
    XtX = X.T @ X
    rank = int(np.linalg.matrix_rank(X))
    out = {'n': N, 'p': p, 'model': model, 'factors': fs, 'terms': ['Intercept'] + [_term_label(fs, t) for t in terms], 'names': names}
    if rank < p:
        out['error'] = f'the model has {p} parameters but the design supports only {rank}: some terms cannot be estimated (use a smaller model)'
        return out
    V = np.linalg.inv(XtX)
    v = np.diag(V)
    df_e = N - p
    out['df_error'] = df_e
    # ---- power of each parameter and each effect
    delta = float(coefficient) / float(rmse)
    prm_rows = []
    for j, nm in enumerate(names):
        lam = delta * delta / v[j]
        if df_e > 0:
            crit = stats.f.ppf(1 - alpha, 1, df_e)
            pw = float(stats.ncf.sf(crit, 1, df_e, lam))
        else:
            pw = None
        prm_rows.append({'term': nm, 'coef': float(coefficient), 'power': pw, 'variance': float(v[j]), 'se': math.sqrt(v[j]),
                         'ci_increase': math.sqrt(N * v[j]) - 1})
    eff_rows = []
    for t, (a, b) in zip([None] + list(terms), slices):
        if t is None or b - a < 2:
            continue
        beta = np.array([coefficient if i % 2 == 0 else -coefficient for i in range(b - a)], dtype=float) / float(rmse)
        lam = float(beta @ np.linalg.solve(V[a:b, a:b], beta))
        pw = float(stats.ncf.sf(stats.f.ppf(1 - alpha, b - a, df_e), b - a, df_e, lam)) if df_e > 0 else None
        eff_rows.append({'effect': _term_label(fs, t), 'df': b - a, 'power': pw})
    out['power'] = rtable([col('term', 'Term', 'text'), col('coef', 'Anticipated Coefficient'), col('power', 'Power')], [{k: r[k] for k in ('term', 'coef', 'power')} for r in prm_rows])
    if eff_rows:
        out['effect_power'] = rtable([col('effect', 'Effect', 'text'), col('df', 'DF', 'int'), col('power', 'Power')], eff_rows)
    out['variance'] = rtable([col('term', 'Term', 'text'), col('variance', 'Variance'), col('se', 'Relative Std Error of Estimate'), col('ci_increase', 'Fractional Increase in CI Length')],
                             [{k: r[k] for k in ('term', 'variance', 'se', 'ci_increase')} for r in prm_rows])
    # ---- VIF (statsmodels)
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    vif_rows = []
    for j, nm in enumerate(names):
        if j == 0:
            continue
        try:
            vv = float(variance_inflation_factor(X, j))
        except Exception:
            vv = None
        vif_rows.append({'term': nm, 'vif': vv})
    out['vif'] = rtable([col('term', 'Term', 'text'), col('vif', 'VIF')], vif_rows)
    # ---- alias matrix and correlations
    if alias_terms:
        X2, names2, _sl2 = M.matrix(frame, alias_terms)
        X2 = X2[:, 1:]
        names2 = names2[1:]
        A = V @ X.T @ X2
        out['alias'] = {'rows': names, 'cols': names2, 'matrix': np.where(np.abs(A) < 1e-12, 0.0, A)}
    else:
        X2, names2 = np.zeros((N, 0)), []
    Z = np.column_stack([X[:, 1:], X2]) if X2.shape[1] else X[:, 1:]
    with np.errstate(invalid='ignore', divide='ignore'):
        R = np.corrcoef(Z, rowvar=False) if Z.shape[1] > 1 else np.ones((1, 1))
    R = np.nan_to_num(np.atleast_2d(R), nan=0.0)
    out['correlation'] = {'names': names[1:] + names2, 'n_model': len(names) - 1, 'matrix': R}
    # ---- efficiencies and the prediction variance over the design space
    rng = np.random.default_rng(20260926)
    samp = _space_sample(fs, 4096, rng)
    Xs, _n, _s = M.matrix(samp, terms)
    pv = np.einsum('ij,jk,ik->i', Xs, V, Xs)
    cand = [pv, np.einsum('ij,jk,ik->i', X, V, X)]
    corners = _corners(fs)
    if corners is not None:
        Xc, _n, _s = M.matrix(corners, terms)
        cand.append(np.einsum('ij,jk,ik->i', Xc, V, Xc))
    pmax = float(max(c.max() for c in cand))
    sign, logdet = np.linalg.slogdet(XtX / N)
    d_eff = 100 * math.exp(logdet / p) if sign > 0 else 0.0
    a_eff = 100 * p / (N * float(np.trace(V)))
    g_eff = 100 * math.sqrt(p / N) / math.sqrt(pmax)
    out['diagnostics'] = [['D Efficiency', d_eff], ['G Efficiency', g_eff], ['A Efficiency', a_eff],
                          ['Average Variance of Prediction', float(np.mean(pv))], ['Maximum Relative Prediction Variance', pmax],
                          ['Runs', N, 'int'], ['Parameters', p, 'int'], ['Error Degrees of Freedom', df_e, 'int']]
    qs = np.linspace(0, 1, 101)
    out['fds'] = {'fraction': qs, 'variance': np.quantile(pv, qs)}
    # the profile: one factor at a time, the others at the center (first level)
    prof = []
    for f in fs:
        if f['kind'] == 'continuous':
            grid = np.linspace(f['low'], f['high'], 41)
        else:
            grid = np.array(f['levels'], dtype=object)
        fr = {}
        for g in fs:
            if g is f:
                fr[g['name']] = grid
            elif g['kind'] == 'continuous':
                fr[g['name']] = np.full(len(grid), (g['low'] + g['high']) / 2)
            else:
                fr[g['name']] = np.array([g['levels'][0]] * len(grid), dtype=object)
        Xp, _n, _s = M.matrix(fr, terms)
        prof.append({'factor': f['name'], 'kind': f['kind'], 'x': grid.tolist(), 'variance': np.einsum('ij,jk,ik->i', Xp, V, Xp)})
    out['profile'] = prof
    out['code'] = '\n'.join([
        'import numpy as np, pandas as pd', f'df = pd.read_csv({json.dumps(table_name + ".csv")})',
        '# coded units: continuous (x - mid) / half range; categorical effect coded',
        *[f'x{j} = (df[{json.dumps(f["name"])}] - {(f["low"] + f["high"]) / 2!r}) / {(f["high"] - f["low"]) / 2!r}' for j, f in enumerate(fs) if f['kind'] == 'continuous'],
        '# X: the model matrix (intercept, then the terms); V = inv(X.T @ X)',
        f'# D efficiency = 100 det(X.T X / N)^(1/p); A = 100 p / (N trace V); power of a term: ncf.sf(F(1-{alpha}, 1, N-p), 1, N-p, (coef/rmse)^2 / V_jj)',
    ])
    return out
