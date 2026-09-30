"""Design of Experiments: the design tables of DOE > Classical (Full
Factorial, Screening, Response Surface) and DOE > Special Purpose (Space
Filling), and the diagnostics of DOE > Design Diagnostics > Evaluate Design.

  Full Factorial   every combination of the levels; continuous factors at
                   their low and high values, with optional center points;
                   a split plot when some factors are hard to change (the
                   whole plots: each a setting of the hard-to-change factors
                   with every combination of the others, the randomization
                   restricted to them), or the replicates as blocks; the
                   design's model (with the whole-plot or block random
                   effect) for Fit Model, and a Simulate Responses formula
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
from .util import code_head, col, one_line, table as rtable

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
            out.append({'name': name, 'kind': 'continuous', 'low': lo, 'high': hi, 'hard': f.get('changes') == 'hard'})
        else:
            levels = [str(v) for v in (f.get('levels') or []) if str(v).strip() != '']
            if len(levels) < 2:
                raise ValueError(f'{name}: a categorical factor needs two or more levels')
            if len(set(levels)) != len(levels):
                raise ValueError(f'{name}: the levels must differ')
            out.append({'name': name, 'kind': 'categorical', 'levels': levels, 'hard': f.get('changes') == 'hard'})
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
def full_factorial(factors, responses=None, replicates=0, center_points=0, order='randomize', seed=None, whole_plots=None, blocks=False):
    fs = _clean_factors(factors)
    if any(f.get('hard') for f in fs):
        return _split_plot(fs, responses, replicates, center_points, order, seed, whole_plots)
    if blocks and int(replicates or 0) >= 1:
        return _blocked(fs, responses, replicates, center_points, order, seed)
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
    out = _table_out('Full Factorial', fs, coded, pattern, resp, order, seed, notes, code=code)
    terms = _model_terms(fs, len(coded), 0)
    out['model'] = _model_spec(fs, resp, terms, [])
    out['random'] = []
    out['simulate'] = _sim_parts(fs, terms, [])
    return out


def _levels_of(f):
    return [-1, 1] if f['kind'] == 'continuous' else list(range(len(f['levels'])))


def _model_terms(fs, n_runs, used_df):
    """The design's model: the full factorial when it leaves the residual a
    degree of freedom (after used_df for the random terms), else the main
    effects and two-factor interactions, else the main effects."""
    names = [f['name'] for f in fs]

    def width(t):
        w = 1
        for nm in t:
            f = fs[names.index(nm)]
            w *= 1 if f['kind'] == 'continuous' else len(f['levels']) - 1
        return w
    for top in (len(names), 2, 1):
        terms = [list(c) for r in range(1, min(top, len(names)) + 1) for c in itertools.combinations(names, r)]
        p = 1 + sum(width(t) for t in terms)
        if n_runs - p - used_df >= 1:
            return terms
    return [[nm] for nm in names]


def _model_spec(fs, responses, terms, random_terms):
    """The design's model as a Fit Model launch takes it, by column names:
    every response as Y, the terms, the random terms."""
    effects = [{'names': t, 'nest': [], 'nestNames': [], 'random': False} for t in terms]
    effects += [{'names': t, 'nest': [], 'nestNames': [], 'random': True} for t in random_terms]
    return {'roles': {'y': [r['name'] for r in responses]}, 'options': {'personality': 'standard'}, 'effects': effects}


def whole_plots_default(n_hard_combos, replicates=0):
    """The number of whole plots when none is given: each setting of the
    hard-to-change factors twice (so that the whole plots' variance can be
    told from those factors' effects), or once per copy of the design when
    there are more replicates."""
    return n_hard_combos * max(2, int(replicates or 0) + 1)


def _split_plot(fs, responses, replicates, center_points, order, seed, whole_plots):
    """A split-plot full factorial: the hard-to-change factors' settings are
    the whole plots, each repeated whole_plots / (their combinations) times;
    every combination of the easy-to-change factors within each whole plot.
    Randomized: the whole plots in a random order, the runs in a random
    order within each."""
    resp = _responses(responses)
    seed = _seed(seed)
    order = order if order in ORDERS else 'randomize'
    hard = [j for j, f in enumerate(fs) if f.get('hard')]
    easy = [j for j, f in enumerate(fs) if not f.get('hard')]
    if not easy:
        raise ValueError('every factor is hard to change: make at least one easy to change (its levels change within a whole plot)')
    hc = [list(c) for c in itertools.product(*[_levels_of(fs[j]) for j in hard])]
    ec = [list(c) for c in itertools.product(*[_levels_of(fs[j]) for j in easy])]
    H = len(hc)
    W = int(whole_plots) if whole_plots not in (None, '') else whole_plots_default(H, replicates)
    if W < H or W % H:
        raise ValueError(f'the number of whole plots must be a multiple of {H}, the combinations of the hard-to-change factors')
    if W * len(ec) > 100000:
        raise ValueError(f'{W * len(ec)} runs: more than 100000')
    rng = np.random.default_rng(seed)
    wp_settings = [hc[i % H] for i in range(W)]
    wp_order = rng.permutation(W) if order == 'randomize' else np.arange(W)
    coded, wp_col = [], []
    for k, w in enumerate(wp_order):
        inner = rng.permutation(len(ec)) if order == 'randomize' else np.arange(len(ec))
        for i in inner:
            run = [0] * len(fs)
            for j, v in zip(hard, wp_settings[w]):
                run[j] = v
            for j, v in zip(easy, ec[i]):
                run[j] = v
            coded.append(run)
            wp_col.append(str(k + 1))
    n = len(coded)
    pattern = [''.join(_pattern_char(f, c) for f, c in zip(fs, run)) for run in coded]
    notes = [f'Split-plot full factorial: {W} whole plots (the {H} settings of the hard-to-change factor{"s" if len(hard) > 1 else ""} '
             f'{", ".join(fs[j]["name"] for j in hard)}, each in {W // H}), with the {len(ec)} combinations of the others in each: {n} runs.',
             f'The whole plots are in a random order and the runs in a random order within each, a restricted randomization (seed {seed}): '
             'analyse it with Whole Plots as a random effect.' if order == 'randomize' else 'The whole plots and their runs in standard order.']
    if W == H:
        notes.append('With one whole plot for each setting of the hard-to-change factors, their effects cannot be told from the '
                     'whole plots\' variation: the model has no Whole Plots term, and the tests of those factors are not valid. '
                     'Give more whole plots.')
    if center_points:
        notes.append('Center points are not added to a split-plot design.')
    extra = [{'name': 'Whole Plots', 'dataType': 'character', 'modelingType': 'nominal', 'values': wp_col, 'valueOrder': [str(i + 1) for i in range(W)],
              'notes': 'The whole plot of each run: the runs that share the setting of the hard-to-change factors, set once.'}]
    terms = _model_terms(fs, n, W - H)
    model = _model_spec(fs, resp, terms, [['Whole Plots']] if W > H else [])
    code = '\n'.join(['import itertools, numpy as np, pandas as pd',
                      f'rng = np.random.default_rng({seed})',
                      f'hard = {json.dumps({fs[j]["name"]: ([fs[j]["low"], fs[j]["high"]] if fs[j]["kind"] == "continuous" else fs[j]["levels"]) for j in hard})}',
                      f'easy = {json.dumps({fs[j]["name"]: ([fs[j]["low"], fs[j]["high"]] if fs[j]["kind"] == "continuous" else fs[j]["levels"]) for j in easy})}',
                      'hc, ec = list(itertools.product(*hard.values())), list(itertools.product(*easy.values()))',
                      f'W = {W}   # whole plots: each setting of the hard-to-change factors W / len(hc) times',
                      'wp = [hc[i % len(hc)] for i in range(W)]',
                      'rows = []',
                      ('for k, w in enumerate(rng.permutation(W)):   # the whole plots in a random order' if order == 'randomize' else 'for k, w in enumerate(range(W)):'),
                      ('    for i in rng.permutation(len(ec)):   # the runs in a random order within each' if order == 'randomize' else '    for i in range(len(ec)):'),
                      '        rows.append({"Whole Plots": str(k + 1), **dict(zip(hard, wp[w])), **dict(zip(easy, ec[i]))})',
                      'd = pd.DataFrame(rows)', 'print(d)'])
    out = _table_out('Split Plot', fs, coded, pattern, resp, 'keep', seed, notes, extra_cols=extra, code=code)
    out['order'] = order
    out['notes'] = ' '.join(notes)
    out['model'] = model
    out['random'] = ['Whole Plots'] if W > H else []
    out['whole_plots'] = W
    out['simulate'] = _sim_parts(fs, terms, out['random'])
    return out


def _blocked(fs, responses, replicates, center_points, order, seed):
    """The replicates of a full factorial as blocks (a randomized complete
    block design): each block a complete replicate, the runs randomized
    within each block."""
    resp = _responses(responses)
    seed = _seed(seed)
    order = order if order in ORDERS else 'randomize'
    base = [list(c) for c in itertools.product(*[_levels_of(f) for f in fs])]
    B = int(replicates) + 1
    rng = np.random.default_rng(seed)
    coded, blk = [], []
    ncp = max(0, int(center_points or 0))
    cont = [j for j, f in enumerate(fs) if f['kind'] == 'continuous']
    for b in range(B):
        runs = [list(r) for r in base]
        if ncp and cont:
            for i in range(ncp):
                runs.append([0 if f['kind'] == 'continuous' else i % len(f['levels']) for f in fs])
        idx = rng.permutation(len(runs)) if order == 'randomize' else np.arange(len(runs))
        for i in idx:
            coded.append(runs[i])
            blk.append(str(b + 1))
    n = len(coded)
    pattern = [''.join(_pattern_char(f, c) for f, c in zip(fs, run)) for run in coded]
    notes = [f'Full factorial in {B} blocks: each block a complete replicate of the {len(base)} combinations'
             + (f' with {ncp} center point{"s" if ncp > 1 else ""}' if ncp and cont else '') + f'; {n} runs, '
             + (f'randomized within each block (seed {seed}).' if order == 'randomize' else 'in standard order within each block.')]
    extra = [{'name': 'Block', 'dataType': 'character', 'modelingType': 'nominal', 'values': blk, 'valueOrder': [str(i + 1) for i in range(B)],
              'notes': 'The block of each run: a complete replicate of the design, run together.'}]
    terms = _model_terms(fs, n, B - 1)
    model = _model_spec(fs, resp, terms, [['Block']])
    centers = [[_decode(f, [c])[0] if f['kind'] == 'continuous' else f['levels'][int(c)] for f, c in zip(fs, run)] for run in (
        [[0 if f['kind'] == 'continuous' else i % len(f['levels']) for f in fs] for i in range(ncp)] if ncp and cont else [])]
    code = '\n'.join(['import itertools, numpy as np, pandas as pd', f'rng = np.random.default_rng({seed})',
                      f'levels = {json.dumps({f["name"]: ([f["low"], f["high"]] if f["kind"] == "continuous" else f["levels"]) for f in fs})}',
                      'base = list(itertools.product(*levels.values()))' + (f' + [tuple(c) for c in {json.dumps(centers)}]   # the center points' if centers else ''),
                      'rows = []',
                      f'for b in range({B}):   # each block a complete replicate' + (', randomized within it' if order == 'randomize' else ''),
                      ('    rows += [(*base[i], str(b + 1)) for i in rng.permutation(len(base))]' if order == 'randomize' else '    rows += [(*r, str(b + 1)) for r in base]'),
                      'd = pd.DataFrame(rows, columns=[*levels, "Block"])',
                      'print(d)'])
    out = _table_out('Blocked Full Factorial', fs, coded, pattern, resp, 'keep', seed, notes, extra_cols=extra, code=code)
    out['order'] = order
    out['notes'] = ' '.join(notes)
    out['model'] = model
    out['random'] = ['Block']
    out['simulate'] = _sim_parts(fs, terms, out['random'])
    return out


def _sim_parts(fs, terms, random_terms):
    """The coefficients Simulate Responses asks for: each term's, one per
    combination of its categorical factors' levels but the last (effect
    coding), labelled as Fit Model's estimates are (X3[L1]*X1); 1 for a main
    effect and 0 for an interaction to begin with; a standard deviation for
    each random column and the error."""
    by_name = {f['name']: f for f in fs}
    out = []
    for t in terms:
        fl = [by_name[nm] for nm in t]
        opts = [[f['name']] if f['kind'] == 'continuous' else [f'{f["name"]}[{lv}]' for lv in f['levels'][:-1]] for f in fl]
        labels = ['*'.join(c) for c in itertools.product(*opts)]
        out.append({'names': list(t), 'labels': labels, 'defaults': [1.0 if len(t) == 1 else 0.0] * len(labels)})
    return {'terms': out, 'random': list(random_terms), 'sigmas': {**{r: 1.0 for r in random_terms}, 'Error': 1.0}}


def _fnum(x):
    """A number for formula text, integers without their .0."""
    from .util import formula_num
    x = float(x)
    return str(int(x)) if x == int(x) and abs(x) < 1e15 else formula_num(x)


@api('doe.simulate_formula')
def simulate_formula(factors, terms, coefficients, intercept=0.0, sigmas=None):
    """Simulate Responses: the design's model as a formula of random draws in
    the page's formula language: the intercept, each term's coefficient
    times its coded columns (a continuous factor coded -1 to +1 from its low
    and high, a categorical one effect coded: its level j 1, the last -1),
    one normal draw per level of each random column (the mean of Random
    Normal() over the level's rows times the square root of their count: a
    standard normal shared by the level) times its standard deviation, and a
    normal error per row."""
    from .util import formula_ref, formula_str
    fs = _clean_factors(factors)
    by_name = {f['name']: f for f in fs}
    if len(terms) != len(coefficients):
        raise ValueError('one list of coefficients for each term')

    def coded(f, j=None):
        if f['kind'] == 'continuous':
            mid, half = (f['low'] + f['high']) / 2, (f['high'] - f['low']) / 2
            x = formula_ref(f['name'])
            x = f'({x} - {_fnum(mid)})' if mid else x
            return f'({x} / {_fnum(half)})' if half != 1 else x
        lv = f['levels']
        return f'Match({formula_ref(f["name"])}, {formula_str(lv[j])}, 1, {formula_str(lv[-1])}, -1, 0)'
    parts = [_fnum(intercept)] if float(intercept) else []
    for t, cs in zip(terms, coefficients):
        # a term's coefficients: one per combination of its categorical factors' first levels (effect coding)
        fl = [by_name[nm] for nm in t]
        widths = [1 if f['kind'] == 'continuous' else len(f['levels']) - 1 for f in fl]
        combos = list(itertools.product(*[range(w) for w in widths]))
        cs = list(np.atleast_1d(np.asarray(cs, dtype=float)))
        if len(cs) != len(combos):
            raise ValueError(f'{"*".join(t)}: {len(combos)} coefficient{"s" if len(combos) > 1 else ""}, not {len(cs)}')
        for c, combo in zip(cs, combos):
            if not math.isfinite(c):
                raise ValueError(f'{"*".join(t)}: a coefficient is not a number')
            if c == 0:
                continue
            parts.append(' * '.join(([_fnum(c)] if c != 1 else []) + [coded(f, j) for f, j in zip(fl, combo)]))
    for name, sd in (sigmas or {}).items():
        sd = float(sd)
        if not math.isfinite(sd) or sd < 0:
            raise ValueError(f'{name} σ: a standard deviation of 0 or more')
        if sd == 0:
            continue
        if name == 'Error':
            parts.append(f'Random Normal(0, {_fnum(sd)})')
        else:
            ref = formula_ref(name)
            parts.append(f'{_fnum(sd)} * Col Mean(Random Normal(), {ref}) * Sqrt(Col Number({ref}, {ref}))')
    if not parts:
        return {'expr': '0'}
    # a negative coefficient after the first term as a minus (only a coefficient's text starts with one)
    return {'expr': parts[0] + ''.join(f' - {q[1:]}' if q.startswith('-') else f' + {q}' for q in parts[1:])}


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
                 f'gens = {json.dumps([list(g) for g in d["generators"]])}   # {one_line("; ".join(gen_text))}',
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
def evaluate(table, factors, rows=None, model='main', alpha=0.05, rmse=1.0, coefficient=1.0, coding=None, where=None, table_name='data'):
    """factors: column names; coding: {name: [low, high]} for continuous
    factors (else the column's range). The code under the report and under
    its graphs comes back as 'code' and 'plot_code' (profile: one for each
    factor; fds; colormap)."""
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
    E = _EvalCode(table, rows, where, table_name, fs, coding, model, terms, alias_terms, names, names2)
    out['code'] = E.diagnostics(alpha, rmse, coefficient, df_e, corners is not None)
    out['plot_code'] = _dated({'profile': [E.profile(f) for f in fs], 'fds': E.fds(), 'colormap': E.colormap(len(names) - 1)}, table)
    return out


# ---- Evaluate Design as code --------------------------------------------------------------------------
# The code under the report and under each of its graphs: from a CSV export of
# the table, the report's rows, the factors coded as the report codes them, the
# model matrix and V = (X'X)^-1, then the diagnostics or a graph (matplotlib,
# the light theme's colours, the graph's size at 100 pixels an inch).
MODEL_LABELS = {'main': 'Main Effects', '2fi': 'Main Effects and Two-Factor Interactions', 'rsm': 'Response Surface (with squares)', 'full': 'Full Factorial'}
BASE, TEXT, MUTED = '#2f6690', '#352921', '#786b5d'
J = json.dumps


def _dated(obj, table):
    """Code that reads the table's CSV (a string, or the strings of a list
    or dict) with the line that turns each date column it names back into
    the page's number, as dispatch does for the keys code and *_code."""
    from .util import date_columns, dated_code
    cols = date_columns(table)
    if not cols:
        return obj
    if isinstance(obj, str):
        return dated_code(obj, cols)
    if isinstance(obj, list):
        return [_dated(v, table) for v in obj]
    if isinstance(obj, dict):
        return {k: _dated(v, table) for k, v in obj.items()}
    return obj


def _lit(v):
    """A value as a Python literal: 12.0 as 12, text quoted."""
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        f = float(v)
        return str(int(f)) if f.is_integer() and abs(f) < 1e15 else repr(f)
    return J(str(v))


def _keep_lines(table, rows, where=None):
    """After the code's head: the By group's rows (its where lines) and, of
    those, the ones the report uses (excluded and filtered rows dropped)."""
    L = []
    n = data.TABLES[table]['n'] if table in data.TABLES else 0
    match = np.ones(n, dtype=bool)
    for w in where or []:
        v = data.raw(table, w['column'])
        num = data.meta(table, w['column']).get('dataType') == 'numeric'
        match &= (np.asarray(v, dtype=float) == float(w['value'])) if num else np.array([x == w['value'] for x in v], dtype=bool)
        shown = w['value'] if isinstance(w['value'], str) else _lit(w['value'])
        # (a comment of one line: a name or level with a line break would end it and start code)
        L.append(f'df = df[df[{J(w["column"])}] == {_lit(w["value"])}]   # only the rows where {one_line(w["column"])} is {one_line(shown)}')
    if rows is not None and n:
        keep = np.zeros(n, dtype=bool)
        keep[np.asarray(rows, dtype=int)] = True
        drop = np.flatnonzero(match & ~keep).tolist()
        if drop and not where and keep.sum() <= n / 2:
            return [f'df = df.loc[{np.flatnonzero(keep).tolist()}]   # the rows of the report']
        if drop:
            L.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
    return L


class _EvalCode:
    """Evaluate Design's code, a snippet at a time."""

    def __init__(self, table, rows, where, table_name, fs, coding, model, terms, alias_terms, names, names2):
        self.table, self.rows, self.where, self.table_name = table, rows, where, table_name
        self.fs, self.coding, self.model = fs, coding, model
        self.terms, self.alias_terms, self.names, self.names2 = terms, alias_terms, names, names2

    def _terms_lit(self, terms):
        return '[' + ', '.join('(' + ', '.join(J(self.fs[j]['name']) for j in t) + (',)' if len(t) == 1 else ')') for t in terms) + ']'

    def design(self, imports=()):
        """The head, the report's runs, the coding, the model matrix X and V."""
        fs = self.fs
        L = [code_head(self.table_name, ['import itertools', *imports])] + _keep_lines(self.table, self.rows, self.where)
        L.append(f'factors = {J([f["name"] for f in fs])}')
        L.append('d = df[factors].dropna()   # the runs with every factor')
        cont = [f for f in fs if f['kind'] == 'continuous']
        cat = [f for f in fs if f['kind'] != 'continuous']
        if cont:
            L.append('coding = {   # each continuous factor\'s low and high values: -1 and +1 in coded units')
            for f in cont:
                nm = J(f['name'])
                if f['name'] in self.coding:
                    L.append(f'    {nm}: ({_lit(f["low"])}, {_lit(f["high"])}),   # from its column notes (Coding [low, high])')
                else:
                    L.append(f'    {nm}: (d[{nm}].min(), d[{nm}].max()),   # the data\'s range (its notes give no coding)')
            L.append('}')
        else:
            L.append('coding = {}')
        if cat:
            L.append('levels = {   # each categorical factor\'s levels in these runs, in the table\'s order')
            for f in cat:
                L.append(f'    {J(f["name"])}: {J(f["levels"])},')
            L.append('}')
            L += ['label = lambda v: str(int(v)) if isinstance(v, (int, float, np.number)) and float(v).is_integer() else str(v)   # a level as text: 12.0 as 12',
                  'for f in levels:', '    d[f] = d[f].map(label)']
        else:
            L.append('levels = {}')
        L += ['',
              'def columns(f, v):',
              '    """A factor\'s columns of the model matrix in coded units: a continuous factor from -1 at its low',
              '    value to +1 at its high one; a categorical one effect coded, a column for each level but the last',
              '    (1 at that level, -1 at the last, 0 at the others)."""',
              '    if f in coding:',
              '        lo, hi = coding[f]',
              '        return [(np.asarray(v, dtype=float) - (lo + hi) / 2) / ((hi - lo) / 2)]',
              '    v, lv = np.asarray(v, dtype=object), levels[f]',
              '    return [np.where(v == a, 1.0, np.where(v == lv[-1], -1.0, 0.0)) for a in lv[:-1]]',
              '',
              '',
              'def model_matrix(frame, terms):',
              '    """The intercept, then the columns of each term: the products of its factors\' columns (a factor',
              '    twice is its square)."""',
              '    n = len(frame[factors[0]])',
              '    cols = [np.ones(n)]',
              '    for t in terms:',
              '        for combo in itertools.product(*[columns(f, frame[f]) for f in t]):',
              '            v = np.ones(n)',
              '            for c in combo:',
              '                v = v * c',
              '            cols.append(v)',
              '    return np.column_stack(cols)',
              '',
              '',
              f'terms = {self._terms_lit(self.terms)}   # the model: {one_line(MODEL_LABELS.get(self.model, self.model))}',
              'X = model_matrix({f: d[f].to_numpy() for f in factors}, terms)',
              'V = np.linalg.inv(X.T @ X)   # the variances and covariances of the estimates, over sigma squared']
        return L

    def sample(self):
        """The design space: 4096 points, as the report samples it (the same seed)."""
        cont = [f['name'] for f in self.fs if f['kind'] == 'continuous']
        L = ['rng = np.random.default_rng(20260926)   # the report\'s seed']
        if cont:
            kw = _rng_kw(qmc.Sobol)
            L += [f'cont = {J(cont)}',
                  f'u = qmc.Sobol(len(cont), scramble=True, {kw}=rng).random(4096)   # continuous factors: a scrambled Sobol sample of the coded cube',
                  'space = {f: coding[f][0] + (coding[f][1] - coding[f][0]) * u[:, i] for i, f in enumerate(cont)}']
        else:
            L.append('space = {}')
        if any(f['kind'] != 'continuous' for f in self.fs):
            L += ['for f in factors:   # categorical factors: every level equally likely',
                  '    if f in levels:',
                  '        space[f] = np.array(levels[f], dtype=object)[rng.integers(len(levels[f]), size=4096)]']
        L += ['Xs = model_matrix(space, terms)',
              'pv = np.einsum("ij,jk,ik->i", Xs, V, Xs)   # the relative prediction variance x\'Vx at each point']
        return L

    def diagnostics(self, alpha, rmse, coefficient, df_e, corners):
        L = self.design(['from scipy import stats', 'from scipy.stats import qmc']) + ['', 'N, p = X.shape']
        L.append(f'names = {J(self.names)}   # the parameters, as the report names them')
        if df_e > 0:
            L += [f'alpha, rmse, coefficient = {alpha!r}, {rmse!r}, {coefficient!r}   # Power Settings',
                  'crit = stats.f.ppf(1 - alpha, 1, N - p)',
                  'power = stats.ncf.sf(crit, 1, N - p, (coefficient / rmse) ** 2 / np.diag(V))   # each parameter\'s test when it is the anticipated coefficient']
        else:
            L.append('power = np.full(p, np.nan)   # no error degrees of freedom: nothing can be tested')
        L += self.sample()
        runs = ['pv', 'np.einsum("ij,jk,ik->i", X, V, X)']
        if corners:
            L += ['vertices = list(itertools.product(*[coding[f] if f in coding else levels[f] for f in factors]))   # the corners of the design space',
                  'Xc = model_matrix({f: np.array([v[i] for v in vertices], dtype=float if f in coding else object) for i, f in enumerate(factors)}, terms)']
            runs.append('np.einsum("ij,jk,ik->i", Xc, V, Xc)')
        L += [f'pmax = max(c.max() for c in ({", ".join(runs)}))   # the largest prediction variance: the sample, the runs{", the corners" if corners else ""}',
              'd_efficiency = 100 * np.exp(np.linalg.slogdet(X.T @ X / N)[1] / p)',
              'a_efficiency = 100 * p / (N * np.trace(V))',
              'g_efficiency = 100 * np.sqrt(p / N) / np.sqrt(pmax)',
              'print(pd.DataFrame({"Term": names, "Power": power, "Variance": np.diag(V), "Relative Std Error": np.sqrt(np.diag(V))}))',
              'print("D, G and A efficiency:", d_efficiency, g_efficiency, a_efficiency)',
              'print("Average variance of prediction:", pv.mean(), "maximum:", pmax)']
        return '\n'.join(L)

    def profile(self, f):
        """The prediction variance profile of one factor, the others at their centre."""
        L = self.design(['import matplotlib.pyplot as plt']) + [
            '',
            'def profile(f):',
            '    """The relative prediction variance along one factor, the others at their centre (a categorical',
            '    factor at its first level)."""',
            '    grid = np.linspace(*coding[f], 41) if f in coding else np.array(levels[f], dtype=object)',
            '    frame = {g: grid if g == f else np.full(len(grid), (coding[g][0] + coding[g][1]) / 2) if g in coding',
            '             else np.array([levels[g][0]] * len(grid), dtype=object) for g in factors}',
            '    Xp = model_matrix(frame, terms)',
            '    return grid, np.einsum("ij,jk,ik->i", Xp, V, Xp)',
            '',
            '',
            'top = 1.08 * max(profile(g)[1].max() for g in factors)   # the same scale for every factor\'s graph',
            f'grid, var = profile({J(f["name"])})',
            'fig, ax = plt.subplots(figsize=(2, 2), layout="constrained")']
        if f['kind'] == 'continuous':
            L.append(f'ax.plot(grid, var, color="{BASE}", linewidth=1.44)')
        else:
            L += [f'ax.plot(range(len(grid)), var, color="{BASE}", linewidth=0.72, marker="o", markersize=5)',
                  'ax.set_xticks(range(len(grid)), grid)   # the levels']
        L += ['ax.set_ylim(0, top)', f'ax.set_xlabel({J(f["name"])})', 'ax.set_ylabel("Variance")',
              f'ax.set_title({J("Prediction variance " + f["name"])})', 'plt.show()']
        return '\n'.join(L)

    def fds(self):
        """The Fraction of Design Space plot."""
        L = self.design(['from scipy.stats import qmc', 'import matplotlib.pyplot as plt']) + [''] + self.sample() + [
            'fraction = np.linspace(0, 1, 101)',
            'variance = np.quantile(pv, fraction)   # the share of the design space with at most this prediction variance',
            'fig, ax = plt.subplots(figsize=(3.8, 2.6), layout="constrained")',
            f'ax.plot(fraction, variance, color="{BASE}", linewidth=1.44)',
            'ax.set_xlim(0, 1)', 'ax.set_ylim(bottom=0)',
            'ax.set_xlabel("Fraction of Space")', 'ax.set_ylabel("Prediction Variance")', 'ax.set_title("Fraction of design space")', 'plt.show()']
        return '\n'.join(L)

    def colormap(self, n_model):
        """The colour map on the correlations of the model terms and the alias terms."""
        names = self.names[1:] + self.names2
        k = len(names)
        w, h = max(320, min(720, 140 + 26 * k)), max(300, min(720, 120 + 26 * k))
        L = self.design(['from matplotlib.colors import LinearSegmentedColormap', 'import matplotlib.pyplot as plt'])
        if self.alias_terms:
            L += [f'alias_terms = {self._terms_lit(self.alias_terms)}   # the terms left out of the model',
                  'Z = np.column_stack([X[:, 1:], model_matrix({f: d[f].to_numpy() for f in factors}, alias_terms)[:, 1:]])']
        else:
            L.append('Z = X[:, 1:]')
        L += [f'names = {J(names)}   # the model\'s terms, then the alias terms',
              'with np.errstate(invalid="ignore", divide="ignore"):',
              '    R = np.corrcoef(Z, rowvar=False) if Z.shape[1] > 1 else np.ones((1, 1))',
              'R = np.nan_to_num(np.atleast_2d(R), nan=0.0)',
              'cmap = LinearSegmentedColormap.from_list("corr", ["#f4f7fb", "#8fa9c2", "#c0392b"])   # the page\'s colours for |r| from 0 to 1',
              f'fig, ax = plt.subplots(figsize=({w / 100:g}, {h / 100:g}), layout="constrained")',
              'im = ax.imshow(np.abs(R), cmap=cmap, vmin=0, vmax=1)',
              'ax.set_xticks(range(len(names)), names, rotation=45, ha="right")',
              'ax.set_yticks(range(len(names)), names)']
        if n_model < k:
            L.append(f'ax.axvline({n_model - 0.5:g}, color="{TEXT}", linewidth=0.72, linestyle=":")   # right of the line: the alias terms (after the model\'s {n_model})')
        L += ['fig.colorbar(im, ax=ax, label="|r|")', 'ax.set_title("Color map on correlations")', 'plt.show()']
        return '\n'.join(L)
