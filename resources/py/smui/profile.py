"""The Prediction Profiler of any model.

A platform lets the page profile its models with

    profile.expose('partition', build, packages=SK)

where build(table, rows=None, **spec) returns a Predictor: the factors
(each column's range and mean, or its levels) and predict(settings), the
responses at a list of settings ({factor name: value}, a categorical factor
by its level as the table holds it). expose() registers '<area>.profile',
which gives the traces the page's SM.profiler draws: for each factor, every
response as that factor runs over its range and the others stay at their
current values; with the responses' desirability specs (des), also the
Desirability row. It registers '<area>.maximize' (Maximize Desirability),
'<area>.importance' (Assess Variable Importance), '<area>.marginal'
(Marginal Model Plots: partial dependence, with ICE lines) and
'<area>.shapley' (Save Shapley Values: permutation SHAP over the prediction)
too. Their own arguments are named des, max_seed, imp_method, imp_n,
imp_seed, mm_n, mm_ice, mm_seed, sh_rows, sh_n, sh_perm and sh_seed, so they
never meet a platform's (a model's seed, say).
"""
import math

import numpy as np

from .registry import api


class Predictor:
    """factors: [{'name', 'type': 'continuous', 'min', 'max', 'mean'} or
    {'name', 'type': 'categorical', 'levels', 'labels'}]; predict(settings)
    -> [{'name', 'pred', 'lower', 'upper', 'bounded'}], one per response,
    each an array over the settings (lower and upper may be None; bounded:
    a probability, drawn from 0 to 1)."""

    def __init__(self, factors, predict, data=None):
        self.factors = factors
        self.predict = predict
        self.data = data          # {factor name: the values the model learned from}, for resampled inputs


def expose(area, build, packages=(), alpha=False):
    """alpha=True: build also takes the report's alpha (for confidence limits)."""
    pass_alpha = alpha
    @api(f'{area}.profile', packages=packages)
    def _profile(table, current=None, rows=None, grid=41, alpha=0.05, table_name=None, des=None, **spec):
        return traces(build(table, rows=rows, **({'alpha': alpha} if pass_alpha else {}), **spec), current, grid, des)

    @api(f'{area}.maximize', packages=packages)
    def _maximize(table, current=None, rows=None, grid=41, alpha=0.05, table_name=None, des=None, max_seed=0, **spec):
        pr = build(table, rows=rows, **({'alpha': alpha} if pass_alpha else {}), **spec)
        best = maximize(pr, des, current, seed=max_seed)
        return {'best': best, 'profile': traces(pr, best['setting'], grid, des)}

    @api(f'{area}.importance', packages=packages)
    def _importance(table, rows=None, alpha=0.05, table_name=None, current=None, des=None, imp_method='uniform', imp_n=1024, imp_seed=0, **spec):
        pr = build(table, rows=rows, **({'alpha': alpha} if pass_alpha else {}), **spec)
        return importance(pr, imp_method, imp_n, imp_seed, pr.data)

    @api(f'{area}.marginal', packages=packages)
    def _marginal(table, rows=None, alpha=0.05, table_name=None, current=None, des=None, grid=41, mm_n=200, mm_ice=0, mm_seed=0, **spec):
        pr = build(table, rows=rows, **({'alpha': alpha} if pass_alpha else {}), **spec)
        return marginal(pr, background(pr, table, rows), grid, mm_n, mm_ice, mm_seed)

    @api(f'{area}.shapley', packages=packages)
    def _shapley(table, rows=None, alpha=0.05, table_name=None, current=None, des=None, sh_rows=None, sh_n=50, sh_perm=10, sh_seed=0, **spec):
        pr = build(table, rows=rows, **({'alpha': alpha} if pass_alpha else {}), **spec)
        return shapley(pr, explained(pr, table, sh_rows), background(pr, table, rows), sh_n, sh_perm, sh_seed)
    for fn, name in ((_profile, 'profile'), (_maximize, 'maximize'), (_importance, 'importance'), (_marginal, 'marginal'), (_shapley, 'shapley')):
        fn.__name__ = f'{area}_{name}'
    return _profile


def _match(levels, v):
    for lv in levels:
        if lv == v or str(lv) == str(v):
            return lv
        try:
            if float(lv) == float(v):
                return lv
        except (TypeError, ValueError):
            pass
    return levels[0]


def setting(factors, current):
    """The current values from the page as a setting: a missing or unknown
    value is the factor's mean or first level, a number is kept inside the
    factor's range."""
    s = {}
    for f in factors:
        v = (current or {}).get(f['name'])
        if f['type'] == 'categorical':
            s[f['name']] = f['levels'][0] if v is None else _match(f['levels'], v)
        else:
            try:
                x = float(v)
                if not np.isfinite(x):
                    raise ValueError
            except (TypeError, ValueError):
                x = f['mean']
            s[f['name']] = float(min(max(x, f['min']), f['max']))
    return s


def _grid(f, n):
    if f['type'] == 'categorical':
        return list(f['levels'])
    lo, hi = f['min'], f['max']
    return [float(v) for v in np.linspace(lo, hi, n)] if hi > lo else [lo]


def traces(pr, current=None, grid=41, des=None):
    facs = [dict(f) for f in pr.factors]
    cur = setting(facs, current)
    settings = [dict(cur)]
    spans = []
    for f in facs:
        g = _grid(f, int(grid))
        spans.append((len(settings), len(g), g))
        for v in g:
            s = dict(cur)
            s[f['name']] = v
            settings.append(s)
    preds = pr.predict(settings)
    for f in facs:
        f['current'] = cur[f['name']]
    out = {'factors': facs, 'responses': []}
    for p in preds:
        pred = np.asarray(p['pred'], dtype=float)
        lo = None if p.get('lower') is None else np.asarray(p['lower'], dtype=float)
        up = None if p.get('upper') is None else np.asarray(p['upper'], dtype=float)
        resp = {'name': p['name'], 'bounded': bool(p.get('bounded')), 'traces': [],
                'current': {'pred': float(pred[0]), 'lower': None if lo is None else float(lo[0]), 'upper': None if up is None else float(up[0])}}
        for f, (at, k, g) in zip(facs, spans):
            sl = slice(at, at + k)
            resp['traces'].append({'factor': f['name'], 'x': f['labels'] if f['type'] == 'categorical' else g,
                                   'pred': pred[sl], 'lower': None if lo is None else lo[sl], 'upper': None if up is None else up[sl]})
        out['responses'].append(resp)
    if des:
        out['desirability'] = _desirability_parts(pr, des, facs, spans, settings, preds)
    return out


# ---------------------------------------------------------------------------
# desirability (JMP's Desirability Functions, Maximize Desirability)
# ---------------------------------------------------------------------------
#
# A response's desirability spec: {'goal': 'max' | 'min' | 'target' | 'none',
# 'points': [[y, d], [y, d], [y, d]], 'importance': 1}. The function runs
# through the three points (a monotone piecewise cubic, scipy's
# PchipInterpolator) and stays flat beyond them; JMP's default values at the
# points are 0.0183, 0.5 and 0.9817 for Maximize (the logistic at -4, 0, 4).
# The overall desirability is the geometric mean of the responses' (with a
# goal), weighted by their importance.

DEFAULT_D = {'max': (0.0183, 0.5, 0.9817), 'min': (0.9817, 0.5, 0.0183), 'target': (0.0183, 1.0, 0.0183)}


def default_points(goal, lo, hi):
    """The three points of a goal over a response's range, as JMP sets them."""
    if goal not in DEFAULT_D:
        return None
    lo, hi = float(lo), float(hi)
    if not hi > lo:
        hi = lo + 1.0
    return [[lo, DEFAULT_D[goal][0]], [(lo + hi) / 2, DEFAULT_D[goal][1]], [hi, DEFAULT_D[goal][2]]]


def desirability(spec, y):
    """d(y) of one response's spec; 1 when it has no goal."""
    y = np.asarray(y, dtype=float)
    if not spec or spec.get('goal') in (None, 'none') or not spec.get('points'):
        return np.ones_like(y)
    from scipy.interpolate import PchipInterpolator
    pts = sorted((float(a), min(max(float(b), 0.0), 1.0)) for a, b in spec['points'])
    xs, ds = [p[0] for p in pts], [p[1] for p in pts]
    for i in range(1, len(xs)):          # equal points: nudge apart, keep the order
        if xs[i] <= xs[i - 1]:
            xs[i] = xs[i - 1] + 1e-9 * max(1.0, abs(xs[i - 1]))
    out = PchipInterpolator(xs, ds, extrapolate=False)(np.clip(y, xs[0], xs[-1]))
    out = np.where(np.isfinite(y), out, 0.0)
    return np.clip(out, 0.0, 1.0)


def overall(specs, preds):
    """The overall desirability over settings: the importance-weighted
    geometric mean of the responses that have a goal. preds: {name: array}."""
    ws, logs = [], []
    n = len(next(iter(preds.values()))) if preds else 0
    for name, p in preds.items():
        sp = (specs or {}).get(name)
        if not sp or sp.get('goal') in (None, 'none'):
            continue
        w = float(sp.get('importance', 1) or 0)
        if w <= 0:
            continue
        d = desirability(sp, p)
        with np.errstate(divide='ignore'):
            logs.append(w * np.log(d))
        ws.append(w)
    if not ws:
        return None
    return np.exp(np.sum(logs, axis=0) / sum(ws)) if n else np.zeros(0)


def _desirability_parts(pr, specs, facs, spans, settings, preds):
    """The Desirability row of the profiler: D over each factor's trace, the
    current D and each response's d, and each function's curve to draw."""
    by = {p['name']: np.asarray(p['pred'], dtype=float) for p in preds}
    D = overall(specs, by)
    if D is None:
        return None
    out = {'current': float(D[0]), 'traces': [], 'individual': {}, 'curves': {}}
    for f, (at, k, g) in zip(facs, spans):
        out['traces'].append({'factor': f['name'], 'x': f['labels'] if f['type'] == 'categorical' else g, 'D': D[at:at + k]})
    for name, p in by.items():
        sp = (specs or {}).get(name)
        if not sp or sp.get('goal') in (None, 'none'):
            continue
        ys = [float(a) for a, _ in sp['points']]
        lo, hi = min(ys + [float(np.nanmin(p))]), max(ys + [float(np.nanmax(p))])
        pad = 0.05 * (hi - lo or 1.0)
        yg = np.linspace(lo - pad, hi + pad, 81)
        out['curves'][name] = {'y': yg, 'd': desirability(sp, yg)}
        out['individual'][name] = float(desirability(sp, p[:1])[0])
    return out


def _as_settings(facs, cont_vals, cat_idx):
    """Settings from arrays: cont_vals (n, number of continuous factors) and
    cat_idx (n, number of categorical factors, level indices)."""
    n = cont_vals.shape[0] if cont_vals is not None else cat_idx.shape[0]
    out = [dict() for _ in range(n)]
    ci = ki = 0
    for f in facs:
        if f['type'] == 'categorical':
            lv = f['levels']
            col = cat_idx[:, ki]
            for i in range(n):
                out[i][f['name']] = lv[int(col[i])]
            ki += 1
        else:
            col = cont_vals[:, ci]
            for i in range(n):
                out[i][f['name']] = float(col[i])
            ci += 1
    return out


def maximize(pr, specs, current=None, seed=0, n_starts=512, refine=5):
    """Maximize Desirability: a quasi-random search over the factors (all
    level combinations of up to 256 for the categorical ones, else random
    levels), the best few refined by scipy.optimize.minimize (Powell, within
    the ranges: a tree's surface has no gradient), and then each
    categorical factor's levels tried in turn."""
    from scipy import optimize
    from scipy.stats import qmc
    facs = pr.factors
    cont = [f for f in facs if f['type'] != 'categorical']
    cats = [f for f in facs if f['type'] == 'categorical']
    rng = np.random.default_rng(int(seed))

    def D_of(settings):
        preds = pr.predict(settings)
        d = overall(specs, {p['name']: np.asarray(p['pred'], dtype=float) for p in preds})
        return np.zeros(len(settings)) if d is None else d
    lo = np.array([f['min'] for f in cont], dtype=float)
    hi = np.array([f['max'] for f in cont], dtype=float)
    n = int(n_starts)
    if cont:
        U = qmc.Sobol(len(cont), scramble=True, seed=int(seed)).random(n)
        C = qmc.scale(U, lo, np.where(hi > lo, hi, lo + 1e-12))
    else:
        C = np.zeros((n, 0))
    if cats:
        combos = np.array(np.meshgrid(*[np.arange(len(f['levels'])) for f in cats], indexing='ij')).reshape(len(cats), -1).T
        if len(combos) <= 256:
            K = combos[np.arange(n) % len(combos)]
        else:
            K = np.column_stack([rng.integers(0, len(f['levels']), n) for f in cats])
    else:
        K = np.zeros((n, 0), dtype=int)
    cur = setting(facs, current)
    C = np.vstack([np.array([[cur[f['name']] for f in cont]], dtype=float).reshape(1, -1), C])
    K = np.vstack([np.array([[f['levels'].index(cur[f['name']]) for f in cats]], dtype=int).reshape(1, -1), K])
    D = D_of(_as_settings(facs, C, K))
    best = []
    for i in np.argsort(-D)[:max(1, int(refine))]:
        c, k, d = C[i].copy(), K[i].copy(), float(D[i])
        if cont and np.any(hi > lo):
            span = np.where(hi > lo, hi - lo, 1.0)
            f_ = lambda z, k=k: -float(D_of(_as_settings(facs, (lo + z * span).reshape(1, -1), k.reshape(1, -1)))[0])  # noqa: E731
            z0 = (c - lo) / span
            res = optimize.minimize(f_, z0, method='Powell', bounds=[(0, 1)] * len(cont), options={'xtol': 1e-6, 'ftol': 1e-10, 'maxfev': 4000})
            if -res.fun > d:
                c, d = lo + np.clip(res.x, 0, 1) * span, -float(res.fun)
        changed = True
        while cats and changed:
            changed = False
            for j, f in enumerate(cats):
                trial = np.repeat(k.reshape(1, -1), len(f['levels']), axis=0)
                trial[:, j] = np.arange(len(f['levels']))
                dd = D_of(_as_settings(facs, np.repeat(c.reshape(1, -1), len(trial), axis=0), trial))
                if dd.max() > d + 1e-12:
                    k, d, changed = trial[int(np.argmax(dd))].copy(), float(dd.max()), True
        best.append((d, c, k))
    d, c, k = max(best, key=lambda t: t[0])
    s = _as_settings(facs, c.reshape(1, -1), k.reshape(1, -1))[0]
    preds = pr.predict([s])
    return {'setting': s, 'desirability': d, 'predictions': {p['name']: float(np.asarray(p['pred'])[0]) for p in preds},
            'individual': {p['name']: float(desirability((specs or {}).get(p['name']), np.asarray(p['pred'])[:1])[0]) for p in preds if (specs or {}).get(p['name'], {}).get('goal') not in (None, 'none')},
            'evaluations': int(len(C))}


def importance(pr, method='uniform', n=1024, seed=0, data=None):
    """Assess Variable Importance: Sobol's main (first-order) and total
    effects of each factor on each response (scipy.stats.sobol_indices,
    Saltelli's and Jansen's estimators), the factors drawn independently:
    uniform over their ranges (a categorical factor's levels equally
    likely), or resampled from the data's values (data: {name: values})."""
    from scipy import stats
    facs = pr.factors
    dists = []
    for f in facs:
        if f['type'] == 'categorical':
            if method == 'resampled' and data and f['name'] in data:
                v = [x for x in data[f['name']] if x is not None]
                idx = np.array([f['levels'].index(x) if x in f['levels'] else 0 for x in v])
                p = np.bincount(idx, minlength=len(f['levels'])) / max(1, len(idx))
                dists.append(stats.rv_discrete(values=(np.arange(len(f['levels'])), np.maximum(p, 0) / p.sum())))
            else:
                dists.append(stats.randint(0, len(f['levels'])))
        elif method == 'resampled' and data and f['name'] in data:
            v = np.asarray([x for x in data[f['name']] if x is not None], dtype=float)
            v = np.sort(v[np.isfinite(v)])
            dists.append(_Empirical(v))
        else:
            dists.append(stats.uniform(loc=f['min'], scale=max(f['max'] - f['min'], 1e-12)))
    names = []

    def func(x):
        # x: (factors, draws)
        settings = [dict() for _ in range(x.shape[1])]
        for j, f in enumerate(facs):
            for i in range(x.shape[1]):
                settings[i][f['name']] = f['levels'][int(min(max(round(x[j, i]), 0), len(f['levels']) - 1))] if f['type'] == 'categorical' else float(x[j, i])
        preds = pr.predict(settings)
        names[:] = [p['name'] for p in preds]
        return np.vstack([np.asarray(p['pred'], dtype=float) for p in preds])
    m = int(n)
    m = 1 << max(4, (m - 1).bit_length())      # a power of two, as Sobol sequences need
    res = stats.sobol_indices(func=func, n=m, dists=dists, rng=np.random.default_rng(int(seed)))
    first, total = np.atleast_2d(res.first_order), np.atleast_2d(res.total_order)
    out = []
    for r, name in enumerate(names):
        out.append({'response': name, 'rows': [{'column': f['name'], 'main': float(first[r, j]), 'total': float(total[r, j])} for j, f in enumerate(facs)]})
    return {'responses': out, 'n': m, 'evaluations': m * (len(facs) + 2), 'method': method}


class _Empirical:
    """An empirical distribution with a ppf (for resampled inputs)."""

    def __init__(self, sorted_values):
        self.v = sorted_values

    def ppf(self, u):
        u = np.asarray(u, dtype=float)
        i = np.clip(np.floor(u * len(self.v)).astype(int), 0, len(self.v) - 1)
        return self.v[i]


# ---------------------------------------------------------------------------
# Marginal Model Plots and Shapley values (JMP Pro's, from the prediction alone)
# ---------------------------------------------------------------------------

def _clean(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return v.item() if hasattr(v, 'item') else v


def background(pr, table=None, rows=None):
    """The background rows, as settings: the rows the model learned from (pr.data, which the predictive platforms
    give), else the report's rows of the table's columns named as the factors."""
    names = [f['name'] for f in pr.factors]
    if pr.data and all(n in pr.data for n in names):
        m = min(len(pr.data[n]) for n in names)
        return [{n: _clean(pr.data[n][i]) for n in names} for i in range(m)]
    return explained(pr, table, rows)


def explained(pr, table, rows):
    """Rows of the table as settings of the factors (a factor is a column by its name); rows None: every row."""
    from . import data
    names = [f['name'] for f in pr.factors]
    have = set(data.TABLES[table]['meta']) if table in data.TABLES else set()
    lack = [n for n in names if n not in have]
    if lack:
        raise ValueError(f'the factors {", ".join(lack)} are not columns of the table: their rows cannot be read')
    frame = data.frame(table, names, rows, dropna=False)
    out = [{n: _clean(v) for n, v in zip(names, row)} for row in frame.astype(object).itertuples(index=False, name=None)]
    for s, r in zip(out, frame.index):
        s['__row'] = int(r)
    return out


def _sample(items, n, seed):
    n = int(n)
    if n <= 0 or n >= len(items):
        return list(items)
    idx = np.sort(np.random.default_rng(int(seed)).choice(len(items), n, replace=False))
    return [items[i] for i in idx]


def marginal(pr, back, grid=41, n=200, ice=0, seed=0):
    """Marginal Model Plots (partial dependence, Friedman's): for each factor, the mean prediction of each response
    over up to n background rows (drawn from the seed) with the factor set to each value of its grid (its range,
    or its levels), the other factors at the rows' own values; ice: that many of those rows' own curves too
    (individual conditional expectation), the first of them."""
    facs = [dict(f) for f in pr.factors]
    B = _sample(back, n, seed)
    if not B:
        raise ValueError('no rows to average over')
    out = {'factors': facs, 'n': len(B), 'responses': [], 'ice': min(int(ice or 0), len(B))}
    by_resp = {}
    for f in facs:
        g = _grid(f, int(grid))
        settings = []
        for v in g:
            for b in B:
                s = {k: val for k, val in b.items() if k != '__row'}
                s[f['name']] = v
                settings.append(s)
        preds = pr.predict(settings)
        for p in preds:
            v = np.asarray(p['pred'], dtype=float).reshape(len(g), len(B))
            r = by_resp.setdefault(p['name'], {'name': p['name'], 'bounded': bool(p.get('bounded')), 'traces': []})
            r['traces'].append({'factor': f['name'], 'x': f['labels'] if f['type'] == 'categorical' else g, 'pd': v.mean(axis=1),
                                'ice': v[:, :out['ice']].T if out['ice'] else []})
    out['responses'] = list(by_resp.values())
    return out


def shapley(pr, rows, back, n=50, perms=10, seed=0):
    """Shapley values of each explained row (Permutation SHAP, as JMP Pro computes them): the contribution of each
    factor to the row's prediction against the mean prediction of the background rows (up to n of them, drawn from
    the seed). Along each of perms random orders of the factors (each order and its reverse, antithetically), the
    factors are set to the row's values one at a time, the others at the background rows' own values, and each
    factor gets the change of the mean prediction when it is set; with as many orders as there are orderings, every
    ordering once, which gives the exact values. The values of a row add up to its prediction less the background's
    mean prediction."""
    import itertools
    facs = pr.factors
    names = [f['name'] for f in facs]
    p = len(names)
    B = _sample(back, n, seed)
    if not B or not rows:
        raise ValueError('no rows to explain, or no background rows')
    rng = np.random.default_rng([int(seed), 1])
    total = math.factorial(p)
    if int(perms) >= total:
        orders = [list(o) for o in itertools.permutations(range(p))]
        how = f'every ordering of the {p} factors (exact)'
    else:
        half = max(1, int(perms) // 2)
        orders = []
        for _ in range(half):
            o = list(rng.permutation(p))
            orders += [o, o[::-1]]
        how = f'{len(orders)} random orderings of the factors (each with its reverse)'
    base_settings = [{k: v for k, v in b.items() if k != '__row'} for b in B]
    base = pr.predict(base_settings)
    resp = [q['name'] for q in base]
    mean0 = {q['name']: float(np.mean(np.asarray(q['pred'], dtype=float))) for q in base}
    phi = {r: np.zeros((len(rows), p)) for r in resp}
    pred = {r: np.zeros(len(rows)) for r in resp}
    for i, x in enumerate(rows):
        settings = []
        for o in orders:
            for step in range(p + 1):
                on = set(o[:step])
                for b in base_settings:
                    settings.append({nm: (x.get(nm) if j in on else b[nm]) for j, nm in enumerate(names)})
        preds = pr.predict(settings)
        for q in preds:
            v = np.asarray(q['pred'], dtype=float).reshape(len(orders), p + 1, len(B)).mean(axis=2)   # the mean over the background at each step
            for oi, o in enumerate(orders):
                phi[q['name']][i, o] += np.diff(v[oi])
            pred[q['name']][i] = v[0, -1]
        if len(rows) > 20 and (i + 1) % max(1, len(rows) // 20) == 0:
            print(f'smui:progress shapley {i + 1} {len(rows)}', flush=True)
    out = {'factors': names, 'rows': [x.get('__row') for x in rows], 'how': how, 'n': len(B), 'orders': len(orders), 'responses': []}
    for r in resp:
        ph = phi[r] / len(orders)
        out['responses'].append({'name': r, 'values': ph.T, 'base': mean0[r], 'pred': pred[r],
                                 'mean_abs': np.mean(np.abs(ph), axis=0), 'gap': float(np.max(np.abs(ph.sum(axis=1) - (pred[r] - mean0[r])))) if len(ph) else 0.0})
    return out
