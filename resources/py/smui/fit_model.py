"""Analyze > Fit Model: JMP's Fit Model platform, computed by statsmodels.

A model is the launch dialog's list of effects (Construct Model Effects).
An effect is a crossing of columns (a column twice is a power), possibly
nested in other columns, possibly marked as a random effect:

    {'names': ['fertilizer', 'water'], 'nest': [], 'random': False}
    {'names': ['batch'], 'nest': ['lot'], 'random': True}        batch[lot]&Random

The personalities and the names the page calls:

  fitmodel.ls           Standard Least Squares: the report tables, row
                        diagnostics, leverage plots, least squares means;
                        partial eta and omega squared, optional columns of
                        the Effect Tests
  fitmodel.compare      LSMeans Student's t and Tukey HSD, connecting letters
  fitmodel.contrast     LSMeans Contrast
  fitmodel.boxcox       Box-Cox Y Transformation
  fitmodel.profile      the Prediction Profiler (every personality)
  fitmodel.contour      the Contour Profiler
  fitmodel.interaction  Interaction Plots
  fitmodel.stepwise     Stepwise: forward, backward, mixed; p-values, AICc, BIC
  fitmodel.all_models   All Possible Models
  fitmodel.glm          Generalized Linear Model
  fitmodel.logistic     Nominal and Ordinal Logistic
  fitmodel.mixed        Mixed Model (REML) with variance components (mixed.py)
  fitmodel.manova       MANOVA; Repeated Measures (response='repeated'): the
                        between- and within-subject tests, Mauchly's sphericity
                        test, the Greenhouse-Geisser and Huynh-Feldt adjusted
                        univariate within tests
  fitmodel.penreg       Penalized Regression: lasso, elastic net, ridge, their
                        adaptive forms, forward selection; AICc, BIC, KFold,
                        holdback, leave-one-out or a Validation column
  fitmodel.gee          Generalized Estimating Equations (statsmodels' GEE):
                        working correlations, robust / naive / bias-reduced
                        covariances, QIC; fitmodel.gee_compare fits every
                        working correlation and compares their QIC
  fitmodel.regdiag      Regression Diagnostics of a least squares fit
                        (Breusch-Pagan, White, Goldfeld-Quandt, RESET,
                        Harvey-Collier, Rainbow, Breusch-Godfrey,
                        Jarque-Bera, omnibus)
  fitmodel.recursive    Recursive and Rolling Regression of a least squares
                        fit (RecursiveLS, RollingOLS): recursive estimates,
                        CUSUM and CUSUM of squares with their bounds, in the
                        table's order or sorted by a column
  fitmodel.iv           Instrumental Variables: two-stage least squares
                        (statsmodels' IV2SLS) with the first stages, weak-
                        instrument statistics, the Durbin-Wu-Hausman and
                        Sargan / Hansen J tests
  fitmodel.quantreg     Quantile Regression (QuantReg): the estimates at a
                        quantile, Koenker and Machado's pseudo RSquare, the
                        quantile process beside least squares

Robust Standard Errors (HC0-HC3, Newey-West HAC, cluster) are an argument
of fitmodel.ls, fitmodel.glm and fitmodel.iv (and of the profilers):
statsmodels' get_robustcov_results or fit(cov_type=...), kept beside the
usual fit (for 2SLS on the second stage's regressors with the structural
residuals, _iv_robust).

The designs are models.build's (effect coding, centred crossings, JMP's term
names), with one correction (_center_main_effects): a continuous main effect
that is also centred in a crossing with a factor (x + g + x*g) is centred the
same way, else patsy codes the factor at full rank in the crossing and the
design is singular; the reports give the intercept at x = 0, as JMP does.
Row diagnostics and Lack of Fit are computed in closed form here (see
_diagnostics, _lack_of_fit). Fits are remembered (models.remember) under a
key made of everything that defines them, so the profilers predict from the
fitted model; a profiler call for a fit that has been forgotten refits it.
"""
import hashlib
import itertools
import json
import keyword
import math
import re

import numpy as np
import pandas as pd
from scipy import stats

from . import data, models, predictive
from .registry import api
from . import profile as profile_mod
from .util import code_head, col, one_line, table as rtable

AVG = 'avg'          # a categorical factor averaged over its levels (LS means)


# ---------------------------------------------------------------------------
# effects, designs, the rows of a design for new points
# ---------------------------------------------------------------------------

def _effects(effects):
    out = []
    for e in effects or []:
        if isinstance(e, dict):
            eff = {'names': [str(n) for n in (e.get('names') or [])], 'nest': [str(n) for n in (e.get('nest') or [])],
                   'random': bool(e.get('random'))}
        else:
            eff = {'names': [str(n) for n in e], 'nest': [], 'random': False}
        if not eff['names']:
            continue
        eff['cols'] = eff['names'] + eff['nest']
        eff['label'] = _elabel(eff)
        out.append(eff)
    return out


def _elabel(e):
    s = '*'.join(e['names'])
    if e['nest']:
        s += '[' + ','.join(e['nest']) + ']'
    return s


def _ys(y):
    if y is None:
        return []
    return [y] if isinstance(y, str) else [str(v) for v in y]


def _design(tid, y, effs, rows, weight=None, freq=None, intercept=True, extra=(), y_as_category=False, center=True):
    """models.build over the fixed effects; the random effects' columns (and
    any extra columns) are kept in the frame, so every fit of the model
    uses the same rows."""
    fixed = [e for e in effs if not e['random']]
    rand = [n for e in effs if e['random'] for n in e['cols']]
    d = models.build(tid, y, [e['cols'] for e in fixed], rows, weight, freq, center=center, intercept=intercept,
                     extra=[c for c in list(extra) + rand if c], y_as_category=y_as_category)
    for e, spec in zip(d.effects, fixed):
        e['label'] = spec['label']
        e['spec'] = spec
        e['cols'] = spec['cols']
    if len(d.df) == 0:
        raise ValueError('no rows to fit: every row has a missing value in a column of the model, or is excluded')
    _center_main_effects(d)
    return d


def _center_main_effects(d):
    """A workaround for models.build. In x + g + x*g it writes the crossing
    with x centred, I(x - m), and the main effect as the raw x; patsy takes
    them for two factors and codes g at full rank inside the crossing, which
    adds the column (x - m)*[mean], a copy of x, and a singular design whose
    tests are wrong. The main effect of a column that is centred in a
    crossing is centred the same way here, so patsy sees one factor. Only
    the intercept changes (to the prediction at the mean); the reports put
    it back at x = 0, as JMP has it (_uncenter)."""
    d.centered_main = {}
    terms = [e['term'] for e in d.effects]
    for e in d.effects:
        if len(e['names']) != 1:
            continue
        a = d.alias[e['names'][0]]
        if a in d.categorical or a not in d.means:
            continue
        cterm = f'I({a} - {d.means[a]!r})'
        if any(cterm in models._split_colon(t) for t in terms if t != e['term']):
            e['term'] = cterm
            d.centered_main[cterm] = float(d.means[a])
    if d.centered_main:
        rhs = ' + '.join(e['term'] for e in d.effects) or '1'
        if d.rhs.endswith(' - 1'):
            rhs += ' - 1'
        d.rhs = rhs
        d.formula = f'{d.y_alias} ~ {rhs}' if d.y_alias else rhs


def _tlabel(d, name):
    """JMP's name of a design column: a main effect centred by
    _center_main_effects keeps its column's name."""
    if name in getattr(d, 'centered_main', {}):
        return d.name[_ALIAS_ANY.match(name).group(1)]
    return d.label(name)


def _uncenter(d, names):
    """The linear map from the fitted parameters to JMP's (the intercept at
    x = 0 rather than at the mean of the main effects centred by
    _center_main_effects), or None when nothing was centred."""
    cm = getattr(d, 'centered_main', None)
    if not cm or 'Intercept' not in names:
        return None
    T = np.eye(len(names))
    i0 = names.index('Intercept')
    for t, m in cm.items():
        if t in names:
            T[i0, names.index(t)] = -m
    return T


def _intercept_at_zero_code(d, fit):
    """The line that moves a code's intercept to x = 0 when main effects were centred (as the report shows it)."""
    cm = getattr(d, 'centered_main', None)
    if not cm:
        return []
    terms = {f'I({_q(d.name[_ALIAS_ANY.match(t).group(1)])} - {m!r})': m for t, m in cm.items()}
    return [f'b0 = {fit}.params["Intercept"] - sum(m * {fit}.params[t] for t, m in {terms!r}.items())   # the Intercept at x = 0, as the report']


def _indicator_report(d, R, alpha, dfi, fit_lines, rob, weight, freq):
    """Indicator Parameterization Estimates (models.indicator_estimates) and their code: the model refitted with the
    factors 0/1 coded, the last level the reference."""
    try:
        ind = models.indicator_estimates(d, R, alpha, df=dfi)
    except Exception as e:   # shown in the outline
        return {'error': f'no indicator parameterization: {e}'}
    for r in ind['rows']:
        r['term'] = _tlabel(d, r['name']) if r['name'] in getattr(d, 'centered_main', {}) else r['term']
    wexpr = ' * '.join(f'd[{json.dumps(v)}]' for v in (weight, freq) if v)
    fml = json.dumps(_code_formula(d, indicator=True))
    fi = f'smf.wls({fml}, data=d, weights={wexpr})' if wexpr else f'smf.ols({fml}, data=d)'
    L = list(fit_lines)
    if freq:
        L += [f'mod_i = {fi}   # each factor 0/1 coded: Treatment, the last level the reference',
              f'mod_i.df_resid = d[{json.dumps(freq)}].sum() - np.linalg.matrix_rank(mod_i.exog)', 'fit_i = mod_i.fit()']
    else:
        L.append(f'fit_i = {fi}.fit()   # each factor 0/1 coded: Treatment, the last level the reference')
    if rob:
        L += _robust_code(rob, fit='fit_i', name='rob_i')[:1] + ['print(rob_i.summary())   # Indicator Parameterization Estimates, robust standard errors']
    else:
        L.append('print(fit_i.summary())   # Indicator Parameterization Estimates' + ('' if not ind.get('refit') else ' (a fit of its own: see the note)'))
    if not ind.get('refit'):
        L.append('print(np.max(np.abs(fit_i.fittedvalues - fit.fittedvalues)))   # the same fit, reparametrized: 0 up to rounding')
    L += _intercept_at_zero_code(d, 'rob_i' if rob else 'fit_i')
    ind['code'] = '\n'.join(L)
    return ind


def _expanded_report(d, R, alpha, dfi, fit_lines, rob):
    """Expanded Estimates (models.expanded_estimates) and their code: each line a weighted sum of the fit's parameters."""
    ex = models.expanded_estimates(d, R, alpha, df=dfi)
    Ls = ex.pop('L')
    for r in ex['rows']:
        if r['name'] in getattr(d, 'centered_main', {}) or r['term'] == 'Intercept':
            r['term'] = _tlabel(d, r['name'])
    src = 'rob' if rob else 'fit'
    L = list(fit_lines) + (_robust_code(rob)[:1] if rob else []) + [
        'from scipy import stats',
        f'b, V = np.asarray({src}.params), np.asarray({src}.cov_params())',
        f'dfe = {dfi!r}   # the error degrees of freedom{" (the clusters less one)" if rob and rob.get("type") == "cluster" else ""}',
        f'expanded = {json.dumps({r["term"]: {str(k): v for k, v in Lw.items()} for r, Lw in zip(ex["rows"], Ls)}, ensure_ascii=False)}   # each line\'s weights of the parameters (by position): the last level of effect coding minus the sum of the others',
        'for term, weights in expanded.items():',
        '    L = np.zeros(len(b)); L[[int(k) for k in weights]] = list(weights.values())',
        '    est, se = L @ b, np.sqrt(L @ V @ L); t = est / se',
        f'    print(term, est, se, t, 2 * stats.t.sf(abs(t), dfe), est - stats.t.ppf(1 - {alpha!r} / 2, dfe) * se, est + stats.t.ppf(1 - {alpha!r} / 2, dfe) * se)']
    ex['code'] = '\n'.join(L)
    return ex


def _centred_code(d):
    """The comment the code carries when a main effect was centred."""
    cm = getattr(d, 'centered_main', None)
    if not cm:
        return []
    names = ', '.join(d.name[_ALIAS_ANY.match(t).group(1)] for t in cm)
    return [f'# {names}: the main effect is centred like its crossings, so patsy codes the crossing as JMP does; the report\'s',
            '# Intercept is at 0 instead of the mean: Intercept - sum(mean * slope)']


def _attach(d, di):
    """Which design columns belong to which effect (models.attach_terms for
    a design made without a statsmodels formula fit)."""
    for e in d.effects:
        e['terms'] = []
        e.pop('patsy', None)
    for term, sl in di.term_name_slices.items():
        cols = di.column_names[sl]
        for e in d.effects:
            if models._same_term(term, e['term']):
                e['terms'] = list(cols)
                e['patsy'] = term
    return d


def _matrix(d):
    import patsy
    X = patsy.dmatrix(d.rhs, d.df, return_type='dataframe', NA_action='raise')
    _attach(d, X.design_info)
    return X


def _combos(widths):
    """Column combinations of a subterm, the left-most factor iterating
    fastest, as patsy orders them."""
    for rev in itertools.product(*[range(w) for w in reversed(widths)]):
        yield rev[::-1]


_ALIAS = re.compile(r'C\((v\d+)')
_ALIAS_ANY = re.compile(r'I\((v\d+) ')


class Coder:
    """Design rows for points given by factor settings. The columns are made
    as patsy makes them (term codings, contrast matrices, the left-most
    factor fastest), so a categorical factor can also be averaged over its
    levels (a setting of AVG), which is what least squares means and
    interaction plots need. A setting is {alias: value} for a continuous
    factor, {alias: level index or AVG} for a categorical one; an unset
    factor sits at its mean or its first level."""

    def __init__(self, d, di):
        self.d = d
        self.di = di
        self.names = list(di.column_names)
        self.p = len(self.names)

    def rows(self, settings):
        d = self.d
        n = len(settings)
        ynames = set(_ys(d.y))
        cont, cat = {}, {}
        for name, a in d.alias.items():
            if name in ynames or a not in d.df:
                continue
            if a in d.categorical:
                k = len(d.levels[a])
                idx = np.zeros(n, dtype=int)
                for i, s in enumerate(settings):
                    v = s.get(a)
                    idx[i] = -1 if v == AVG else (0 if v is None else min(max(int(v), 0), k - 1))
                cat[a] = idx
            elif pd.api.types.is_numeric_dtype(d.df[a]):
                m = float(d.df[a].mean())
                vals = np.empty(n)
                for i, s in enumerate(settings):
                    v = s.get(a)
                    vals[i] = m if v is None or v == AVG else float(v)
                cont[a] = vals
        frame = pd.DataFrame(cont, index=range(n))
        X = np.ones((n, self.p))
        j = 0
        for _term, subterms in self.di.term_codings.items():
            for st in subterms:
                blocks = []
                for f in st.factors:
                    fi = self.di.factor_infos[f]
                    if fi.type == 'categorical':
                        cm = np.asarray(st.contrast_matrices[f].matrix, dtype=float)
                        idx = cat[_ALIAS.match(f.code).group(1)]
                        B = cm[np.maximum(idx, 0)].copy()
                        if np.any(idx < 0):
                            B[idx < 0] = cm.mean(axis=0)
                    else:
                        B = np.asarray(f.eval(fi.state, frame), dtype=float).reshape(n, -1)
                    blocks.append(B)
                for combo in _combos([b.shape[1] for b in blocks]):
                    v = np.ones(n)
                    for b, c in zip(blocks, combo):
                        v = v * b[:, c]
                    X[:, j] = v
                    j += 1
        return X


def _lvl(v):
    """A level as text, as the page shows it."""
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return str(int(f)) if f.is_integer() else f'{f:.6g}'
    return str(v)


def _level_index(levels, v):
    for i, lv in enumerate(levels):
        if lv == v:
            return i
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        for i, lv in enumerate(levels):
            if isinstance(lv, (float, np.floating)) and float(lv) == float(v):
                return i
    s = str(v)
    for i, lv in enumerate(levels):
        if _lvl(lv) == s or str(lv) == s:
            return i
    return 0


def _factor_names(d):
    """The model's factors (columns), in the order they first appear."""
    out = []
    for e in d.effects:
        for n in e['names']:
            if n not in out:
                out.append(n)
    return out


def _factors(d):
    out = []
    for n in _factor_names(d):
        a = d.alias[n]
        if a in d.categorical:
            out.append({'name': n, 'type': 'categorical', 'levels': list(d.levels[a]), 'labels': [_lvl(v) for v in d.levels[a]]})
        else:
            x = d.df[a].to_numpy(float)
            out.append({'name': n, 'type': 'continuous', 'min': float(np.min(x)), 'max': float(np.max(x)), 'mean': float(np.mean(x))})
    return out


def _setting(d, values, avg_missing=False):
    """The page's current values ({column name: value}) as a setting."""
    s = {}
    for n in _factor_names(d):
        a = d.alias[n]
        v = (values or {}).get(n)
        if a in d.categorical:
            s[a] = (AVG if avg_missing else 0) if v is None else _level_index(d.levels[a], v)
        elif v is not None:
            try:
                s[a] = float(v)
            except (TypeError, ValueError):
                pass
    return s


# ---------------------------------------------------------------------------
# keys, rows, weights, the code under the reports
# ---------------------------------------------------------------------------

def _rows_sig(rows):
    if rows is None:
        return 'all'
    a = np.asarray(rows, dtype=np.int64)
    return f'{len(a)}:{hashlib.blake2b(a.tobytes(), digest_size=10).hexdigest()}'


def _key(kind, tid, rows, spec):
    return models.model_key(kind, tid, data.version(tid), _rows_sig(rows), spec)


def _spec(y=None, effects=(), weight=None, freq=None, offset=None, no_intercept=False, dist=None, link=None, target=None,
          overdispersion=False, ordinal=None, distr='logit', method='lasso', enet_alpha=0.9, criterion='aicc', n_grid=40,
          choose=None, robust=None, subject=None, time=None, subgroup=None, corr=None, cov=None, scale=None, scale_value=None,
          nb_alpha=None, var_power=None, endog=None, instruments=None, tau=None, qr_cov=None, kernel=None, bandwidth=None,
          adaptive=False, validation=None, portion=None, folds=None, seed=None, center=True, mixed=None, **_ignored):
    """Everything that defines a fit, as a plain dict (the cache key). center:
    JMP's Center Polynomials (the continuous columns of crossings and powers
    centred at their means; on by default, as in JMP). mixed: the mixed
    models' own options (mixed.py), kept so that the profilers refit the
    report's model."""
    return {'y': _ys(y), 'effects': [[e['names'], e['nest'], e['random']] for e in _effects(effects)], 'weight': weight, 'freq': freq,
            'offset': offset, 'no_intercept': bool(no_intercept), 'dist': dist, 'link': link, 'target': target,
            'overdispersion': bool(overdispersion), 'ordinal': ordinal, 'distr': distr, 'method': method, 'enet_alpha': enet_alpha,
            'criterion': criterion, 'n_grid': n_grid, 'choose': choose, 'robust': _robust_spec(robust), 'subject': subject, 'time': time,
            'subgroup': subgroup, 'corr': corr, 'cov': cov, 'scale': scale, 'scale_value': scale_value, 'nb_alpha': nb_alpha,
            'var_power': var_power, 'endog': _ys(endog), 'instruments': _ys(instruments),
            'tau': None if tau in (None, '') else float(tau), 'qr_cov': qr_cov, 'kernel': kernel, 'bandwidth': bandwidth,
            'adaptive': bool(adaptive), 'validation': validation, 'portion': portion, 'folds': folds, 'seed': seed,
            'center': center is not False, 'mixed': mixed}


# Robust Standard Errors: the types of statsmodels' get_robustcov_results
_ROBUST = ('HC0', 'HC1', 'HC2', 'HC3', 'HAC', 'cluster')
_ROBUST_LABEL = {'HC0': 'HC0 (White)', 'HC1': 'HC1 (White, n/(n − p))', 'HC2': 'HC2 (MacKinnon and White, leverage)',
                 'HC3': 'HC3 (MacKinnon and White, jackknife)', 'HAC': 'Newey–West HAC', 'cluster': 'Cluster'}


def _robust_spec(robust):
    """The robust covariance asked for, as a plain dict, or None: 'HC3',
    {'type': 'HAC', 'maxlags': 4}, {'type': 'cluster', 'cluster': 'clinic'}."""
    if not robust:
        return None
    r = {'type': robust} if isinstance(robust, str) else dict(robust)
    t = r.get('type')
    if t in (None, '', 'none', 'nonrobust'):
        return None
    t = {'hac': 'HAC', 'cluster': 'cluster'}.get(str(t).lower(), str(t).upper())
    if t not in _ROBUST:
        raise ValueError(f'no robust covariance {r.get("type")!r}: choose one of HC0, HC1, HC2, HC3, HAC or cluster')
    out = {'type': t}
    if t == 'HAC':
        lags = r.get('maxlags')
        out['maxlags'] = None if lags is None else max(0, int(lags))
    if t == 'cluster':
        if not r.get('cluster'):
            raise ValueError('cluster-robust standard errors need a cluster column')
        out['cluster'] = str(r['cluster'])
    return out


def _nw_lags(n):
    """Newey and West's (1994) rule for the number of lags, 4 (n/100)^(2/9)."""
    return int(math.floor(4 * (max(n, 1) / 100.0) ** (2.0 / 9.0)))


def _robust_label(rob, groups=None):
    t = rob['type']
    if t == 'HAC':
        return f'Newey–West HAC, {rob["maxlags"]} lag{"" if rob["maxlags"] == 1 else "s"}'
    if t == 'cluster':
        return f'Cluster by {rob["cluster"]}' + (f' ({groups} clusters)' if groups else '')
    return _ROBUST_LABEL[t]


def _eff_of(spec):
    return _effects([{'names': n, 'nest': s, 'random': r} for n, s, r in spec['effects']])


def _col_values(tid, name, index):
    return data.series(tid, name, index, as_category=False).to_numpy(float) if name else None


def _freq_total(tid, freq, d):
    return float(np.sum(_col_values(tid, freq, d.df.index))) if freq else None


def _q(name):
    """A column name in a patsy formula: bare only when it is a plain name
    that is not a Python keyword (yield, class, ...) nor one of patsy's C, I, Q."""
    ok = name.isidentifier() and not keyword.iskeyword(name) and name not in ('C', 'I', 'Q')
    return name if ok else f'Q({json.dumps(name)})'


def _code_formula(d, lhs=True, indicator=False):
    """models.code_formula with keyword-safe names, and the '- 1' of a model
    without intercept. lhs=False gives the right-hand side only; indicator:
    the effect-coded factors 0/1 coded, the last level the reference (the
    Indicator Parameterization Estimates)."""
    parts = []
    for e in d.effects:
        counts = {}
        for n in e['names']:
            counts[n] = counts.get(n, 0) + 1
        crossed = len(e['names']) > 1
        ps = []
        for n, k in counts.items():
            a = d.alias[n]
            if a in d.categorical:
                lv = [x.item() if hasattr(x, 'item') else x for x in d.levels[a]]
                coding = (f'Treatment(reference={lv[-1]!r})' if indicator else 'Sum') if d.coding == 'effect' else 'Treatment'
                ps.append(f'C({_q(n)}, {coding}, levels={lv!r})')
            elif (crossed and d.center) or (k == 1 and f'I({a} - {d.means.get(a)!r})' in getattr(d, 'centered_main', {})):
                m = d.means[a]   # the mean in full, so the code gives the report's estimates exactly
                ps.append(f'I(({_q(n)} - {m!r}) ** {k})' if k > 1 else f'I({_q(n)} - {m!r})')
            elif k > 1:
                ps.append(f'I({_q(n)} ** {k})')
            else:
                ps.append(_q(n))
        parts.append(':'.join(ps))
    rhs = ' + '.join(parts) if parts else '1'
    if d.rhs.endswith(' - 1'):
        rhs += ' - 1'
    y = d.y if isinstance(d.y, str) else (d.y[0] if d.y else '')
    return f'{_q(y)} ~ {rhs}' if (y and lhs) else rhs


def _code_frame(d, tid, table_name, rows, extra_cols=(), extra_imports=()):
    """The lines that read the table as the page exported it and keep the
    rows and columns of the model, with the page's level order."""
    lines = [code_head(table_name, list(extra_imports))]
    if rows is not None:
        n = data.TABLES[tid]['n'] if tid in data.TABLES else None
        keep = [int(r) for r in rows]
        if n is not None and len(keep) > n / 2:
            drop = sorted(set(range(n)) - set(keep))
            if drop:
                lines.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
        else:
            lines.append(f'df = df.loc[{keep}]   # the rows of the report')
    cols = list(dict.fromkeys([n for n in d.alias if n in d.df.columns or d.alias[n] in d.df] + [c for c in extra_cols if c]))
    lines.append(f'd = df[{json.dumps(cols)}].dropna()')
    vd = getattr(d, 'valid', None)
    if vd:   # a Validation column: the model learns from its training rows (0, or Training)
        lines.append(_train_line(vd))
    for n in cols:
        a = d.alias.get(n)
        if a is None or a not in d.levels:
            continue
        lv = d.levels[a]
        numeric = all(isinstance(v, (float, int, np.floating, np.integer)) for v in lv)
        cats = json.dumps([float(v) for v in lv] if numeric else [str(v) for v in lv])
        src = f'd[{json.dumps(n)}].astype(float)' if numeric else f'd[{json.dumps(n)}]'
        lines.append(f'd[{json.dumps(n)}] = pd.Categorical({src}, categories={cats})   # the level order of the table')
    return lines


# ---- the Validation column (Standard Least Squares, Stepwise, GLM, the logistic fits) ------------------
# As JMP Pro's Fit Model: the model learns from the training rows (0, or Training) and predicts the
# validation (1) and test (2) rows from the same design (its levels and its centring are the training
# rows'); the Crossvalidation report measures each set. The sets follow predictive.prepare's rules, as
# every predictive platform of the page: rows without a validation value are left out.

def _valid_sets(tid, ys, effs, rows, spec):
    """The sets of the report's rows with the response and every model column:
    {'column', 'P' (predictive.prepare's), 'train' (the training rows)}."""
    vcol = spec['validation']
    if len(ys) > 1:
        raise ValueError('a Validation column takes one Y column (not events and trials)')
    if vcol in ys or any(vcol in e['cols'] for e in effs):
        raise ValueError(f'{vcol} is the Validation column: it cannot also be the Y or in a model effect')
    xcols = list(dict.fromkeys(c for e in effs if not e['random'] for c in e['cols']))
    if not xcols:
        raise ValueError('a Validation column needs model effects: with none there is nothing to validate')
    P = predictive.prepare(tid, ys[0], xcols, rows, spec['weight'], spec['freq'], validation=vcol, missing='drop')
    kfold = int(getattr(P, 'k', 0) or 0)   # more than three values: K folds (Penalized Regression's KFold), no hold-out here
    return {'column': vcol, 'P': P, 'train': [int(r) for r in P.index[P.sets == 0]], 'kfold': kfold,
            'numeric': data.meta(tid, vcol).get('dataType') == 'numeric'}


def _train_line(vd):
    """The code's line that keeps the training rows of the Validation column."""
    q = json.dumps(vd['column'])
    if vd['numeric']:
        return f'd = d[df.loc[d.index, {q}] == 0]   # the training rows of {vd["column"]} (0): the model learns from them'
    return f'd = d[df.loc[d.index, {q}].astype(str).str.strip().str.lower().isin(["training", "train"])]   # the training rows of {vd["column"]}'


def _sets_line(vd, frame='d'):
    """The code's line that gives each row's set, 0 Training, 1 Validation, 2 Test, as predictive.prepare reads them."""
    q = json.dumps(vd['column'])
    if vd['numeric']:
        return f'sets = {frame}[{q}].to_numpy(int)   # 0 training, 1 validation, 2 test'
    return (f'sets = {frame}[{q}].astype(str).str.strip().str.lower().map({json.dumps(predictive._SET_NAMES)}).to_numpy(int)   '
            '# 0 training, 1 validation, 2 test')


def _sub_prepared(P, keep):
    """predictive.prepare's rows, the ones keep marks (the rows the model can predict)."""
    Q = predictive.Prepared()
    for k in ('table', 'y', 'x', 'kind', 'levels', 'labels', 'coding', 'missing', 'spec'):
        setattr(Q, k, getattr(P, k))
    Q.index, Q.sets = P.index[keep], P.sets[keep]
    Q.target = P.target[keep]
    Q.w = None if P.w is None else P.w[keep]
    Q.freq = None if P.freq is None else P.freq[keep]
    Q.notes = list(P.notes)
    return Q


_CV_SHOW = {'continuous': ('set', 'rsquare', 'rase', 'n'),
            'categorical': ('set', 'entropy_rsquare', 'generalized_rsquare', 'misclassification', 'auc', 'n')}


def _cv_report(m, idx, fitted, code=None, head=None, curves=False):
    """The Crossvalidation report of a model with a Validation column:
    predictive.report's measures of each set (their columns JMP's first,
    the rest optional), the confusion matrices of a categorical response
    (curves: its ROC and lift curves by set; head: the lines that make d,
    y, sets and fitted, for their code), each row's actual and predicted
    (the plots mark the hold-out rows). idx: the rows the model predicts
    (models.new_rows), fitted: their predictions (n, or n x levels in P's
    levels)."""
    V = m['valid']
    P = V['P']
    pos = {int(r): i for i, r in enumerate(idx)}
    keep = np.array([int(r) in pos for r in P.index], dtype=bool)
    Q = _sub_prepared(P, keep)
    f = np.asarray(fitted, dtype=float)
    f = f[[pos[int(r)] for r in Q.index]]
    rep = predictive.report(Q, f, roc_curves=curves, head=head)
    show = _CV_SHOW[Q.kind]
    rep['measure_columns'] = [dict(c, hidden=c['key'] not in show) for c in rep['measure_columns']]
    if (~keep).sum():
        rep['notes'].append(f'{int((~keep).sum())} rows the model cannot predict (a level the training rows do not have, or a missing offset) '
                            'are left out.')
    rep['column'] = V['column']
    rep['rows_set'] = {'rows': [int(r) for r in Q.index], 'set': [int(s) for s in Q.sets]}
    if code:
        rep['code'] = code
    return rep


def _kfold_note(d):
    """The note of a Validation column that holds K folds (more than three
    values): the fit takes every row."""
    kf = getattr(d, 'kfold', None)
    if not kf:
        return []
    return [f'{kf[0]} has {kf[1]} values: K folds, which Penalized Regression\'s KFold validation uses (as JMP\'s). This fit takes every '
            'row; a Validation column of 0, 1 and 2 (or Training, Validation and Test) holds rows out.']


def _cv_frame_code(d, tid, V, extra_cols=()):
    """The Crossvalidation code's rows: a, every row with values in every set,
    coded with the training rows' levels (a row with another level is not
    predicted), and sets, each row's set."""
    cols = list(dict.fromkeys([n for n in d.alias if n in d.df.columns or d.alias[n] in d.df] + [c for c in extra_cols if c] + [V['column']]))
    L = [f'a = df[{json.dumps(cols)}].dropna()   # every row with values, in every set']
    for n in cols:
        a_ = d.alias.get(n)
        if a_ is None or a_ not in d.levels:
            continue
        lv = d.levels[a_]
        numeric = all(isinstance(v, (float, int, np.floating, np.integer)) for v in lv)
        cats = json.dumps([float(v) for v in lv] if numeric else [str(v) for v in lv])
        src = f'a[{json.dumps(n)}].astype(float)' if numeric else f'a[{json.dumps(n)}]'
        L.append(f'a[{json.dumps(n)}] = pd.Categorical({src}, categories={cats})   # the training rows\' levels')
    L.append('a = a.dropna()   # a level the training rows do not have is not predicted')
    wparts = [f'a[{json.dumps(c)}]' for c in extra_cols if c and c in (V['P'].spec.get('weight'), V['P'].spec.get('freq'))]
    if wparts:
        L.append(f'a = a[{" * ".join(wparts)} > 0]   # a missing or non-positive weight leaves the row out')
        L.append(f'wa = ({" * ".join(wparts)}).to_numpy(float)')
    else:
        L.append('wa = np.ones(len(a))')
    L.append(_sets_line(V, 'a'))
    return L


def _cv_measure_code(kind, levels=None):
    """The Crossvalidation code's measures of each set from pred (continuous:
    RSquare, RASE, N) or P (the levels' probabilities: Entropy RSquare, against
    the training shares, Generalized RSquare, Misclassification Rate, AUC of two
    levels, N), with ya the actual value or level index, as predictive.measures
    computes them."""
    if kind == 'continuous':
        return ['for k, name in enumerate(["Training", "Validation", "Test"]):',
                '    s = sets == k',
                '    if s.any():',
                '        w_ = wa[s]; e = ya[s] - pred[s]; sse = np.sum(w_ * e ** 2)',
                '        sst = np.sum(w_ * (ya[s] - np.average(ya[s], weights=w_)) ** 2)',
                '        print(name, "RSquare", 1 - sse / sst, "RASE", np.sqrt(sse / w_.sum()), "N", w_.sum())']
    L = ['tr = sets == 0; share = np.array([wa[tr][ya[tr] == j].sum() for j in range(P.shape[1])]) / wa[tr].sum()   # the training shares of the levels',
         'for k, name in enumerate(["Training", "Validation", "Test"]):',
         '    s = sets == k',
         '    if s.any():',
         '        w_, y_, p_ = wa[s], ya[s], P[s]; N = w_.sum()',
         '        ll = np.sum(w_ * np.log(np.clip(p_[np.arange(len(y_)), y_], 1e-15, 1))); ll0 = np.sum(w_ * np.log(np.clip(share[y_], 1e-15, 1)))',
         '        miss = np.sum(w_ * (np.argmax(p_, axis=1) != y_)) / N',
         '        gen = (1 - np.exp(2 * (ll0 - ll) / N)) / (1 - np.exp(2 * ll0 / N))   # Nagelkerke\'s']
    if levels is not None and len(levels) == 2:
        L += ['        pos = y_ == 1; sc = p_[:, 1]   # the AUC: a row of the second level scored above one of the first (ties half)',
              '        auc = sum(w1 * (np.sum(w_[~pos] * (sc[~pos] < s1)) + 0.5 * np.sum(w_[~pos] * (sc[~pos] == s1))) for s1, w1 in zip(sc[pos], w_[pos])) / (w_[pos].sum() * w_[~pos].sum())',
              '        print(name, "Entropy RSquare", 1 - ll / ll0, "Generalized RSquare", gen, "Misclassification Rate", miss, "AUC", auc, "N", N)']
    else:
        L += ['        print(name, "Entropy RSquare", 1 - ll / ll0, "Generalized RSquare", gen, "Misclassification Rate", miss, "N", N)']
    return L


def _tcrit(alpha, df):
    return float(stats.t.ppf(1 - alpha / 2, df)) if df and df > 0 else float('nan')


def _exp(x):
    """exp that gives infinity instead of an overflow error (odds ratios of
    a perfectly separated fit)."""
    try:
        return math.exp(x)
    except OverflowError:
        return float('inf')


def _logworth(p):
    return float(-math.log10(max(p, 1e-300))) if p is not None and np.isfinite(p) else None


# ---------------------------------------------------------------------------
# Standard Least Squares
# ---------------------------------------------------------------------------

def _fit_ols(d, ftot=None):
    """models.fit_ols, with JMP's degrees of freedom for a Freq column (the
    sum of the frequencies, not the number of rows)."""
    import statsmodels.formula.api as smf
    mod = smf.wls(d.formula, data=d.df, weights=d.weights) if d.weights is not None else smf.ols(d.formula, data=d.df)
    if ftot is not None:
        mod.df_resid = ftot - np.linalg.matrix_rank(mod.exog)
    res = mod.fit()
    models.attach_terms(d, res)
    if res.model.rank < res.model.exog.shape[1]:
        _zero_dependent(d, res)
    return res


def _zero_dependent(d, res):
    """JMP's answer to a singular design (linear dependencies among the
    columns): going through the columns in the order of the effects (the
    intercept first), a column that is a linear combination of the ones kept
    before it is Zeroed (its estimate 0, no standard error) and the others
    are fitted by least squares; the kept columns in a dependency are Biased
    (their estimates hold the zeroed ones' parts). The fit, its residuals
    and every estimable function are those of any solution; the estimates
    and their covariance are this one's (the results object is changed in
    place: params, normalized_cov_params). d gets zeroed, biased, keep (the
    kept columns' positions) and singularity (each zeroed column as a
    combination of kept ones)."""
    X = np.asarray(res.model.exog, dtype=float)
    names = list(res.model.exog_names)
    order = [names.index('Intercept')] if 'Intercept' in names else []
    for e in d.effects:
        for c in e.get('terms', []):
            if c in names and names.index(c) not in order:
                order.append(names.index(c))
    order += [j for j in range(len(names)) if j not in order]
    keep, deps = [], {}
    for j in order:
        col_ = X[:, j]
        nrm = float(np.linalg.norm(col_))
        if keep and nrm > 0:
            c, *_ = np.linalg.lstsq(X[:, keep], col_, rcond=None)
            dependent = float(np.linalg.norm(col_ - X[:, keep] @ c)) <= 1e-8 * nrm
        else:
            c, dependent = np.zeros(len(keep)), nrm == 0
        if dependent:
            big = max(1.0, float(np.max(np.abs(c)))) if len(c) else 1.0
            deps[j] = [(keep[k], float(c[k])) for k in range(len(keep)) if abs(c[k]) > 1e-9 * big]
        else:
            keep.append(j)
    Xw = np.asarray(res.model.wexog, dtype=float)[:, keep]
    bk = np.linalg.lstsq(Xw, np.asarray(res.model.wendog, dtype=float), rcond=None)[0]
    p = len(names)
    b = np.zeros(p)
    b[keep] = bk
    nc = np.zeros((p, p))
    nc[np.ix_(keep, keep)] = np.linalg.inv(Xw.T @ Xw)
    res._results.params = b
    res._results.normalized_cov_params = nc
    res._results._cache = {}
    d.keep = sorted(keep)
    d.zeroed = [names[j] for j in order if j in deps]
    d.biased = [names[k] for k in order if any(k == kk for j in deps for kk, _c in deps[j])]
    d.singularity = [{'zeroed': names[j], 'terms': [(names[k], c) for k, c in deps[j]]} for j in order if j in deps]


def _singularity_details(d):
    """JMP's Singularity Details: each zeroed column as the combination of the
    kept columns it equals."""
    rows = []
    for dep in getattr(d, 'singularity', []) or []:
        rhs = ''
        for k, (nm, c) in enumerate(dep['terms']):
            coef = '' if abs(abs(c) - 1) < 1e-9 else f'{_fmt_num(abs(c))}·'
            sign = ('−' if c < 0 else '') if k == 0 else (' − ' if c < 0 else ' + ')
            rhs += f'{sign}{coef}{_tlabel(d, nm)}'
        rows.append({'term': _tlabel(d, dep['zeroed']), 'equation': f'{_tlabel(d, dep["zeroed"])} = {rhs or "0"}'})
    return rtable([col('term', 'Zeroed', 'text'), col('equation', 'Linear dependency', 'text')], rows)


def _zeroed_code(d, fit='fit'):
    """The lines that make the zeroed solution of a singular design from the code's fit (the same columns in the same
    order), as the report shows it."""
    if not getattr(d, 'zeroed', None):
        return []
    return ['# the design is singular: as JMP, a column that is a linear combination of the ones before it (in the order of the',
            '# effects, the intercept first) is Zeroed, and the rest are fitted by least squares (statsmodels\' own answer is pinv\'s)',
            f'keep = {d.keep!r}   # the columns kept, by position',
            f'Xk = {fit}.model.wexog[:, keep]',
            f'b = np.zeros(len({fit}.params)); b[keep] = np.linalg.lstsq(Xk, {fit}.model.wendog, rcond=None)[0]',
            f'V = np.zeros((len(b), len(b))); V[np.ix_(keep, keep)] = np.linalg.inv(Xk.T @ Xk) * {fit}.scale',
            f'print(pd.DataFrame({{"Estimate": b, "Std Error": np.sqrt(np.diag(V))}}, index={fit}.params.index))   # a Zeroed column: 0, no standard error']


def _ls_model(tid, rows, spec):
    key = _key('ls', tid, rows, spec)
    m = models.recall(key)
    if m is not None:
        return m
    ys = spec['y']
    if not ys:
        raise ValueError('choose a Y')
    effs = _eff_of(spec)
    rob = spec.get('robust')
    ccol = rob['cluster'] if rob and rob['type'] == 'cluster' else None
    if ccol and ccol in ys:
        raise ValueError(f'{ccol} is the Y: cluster the standard errors by another column')
    if data.is_categorical(tid, ys[0]):
        raise ValueError(f'{ys[0]} is {data.meta(tid, ys[0]).get("modelingType")}: Standard Least Squares needs a continuous Y '
                         '(Nominal or Ordinal Logistic fits a categorical one)')
    V = _valid_sets(tid, ys, effs, rows, spec) if spec.get('validation') else None
    d = _design(tid, ys[0], effs, V['train'] if V else rows, spec['weight'], spec['freq'], not spec['no_intercept'], extra=[ccol] if ccol else (),
                center=spec.get('center', True))
    if V and V['kfold']:
        d.kfold = (V['column'], V['kfold'])   # K folds: every row fits the model (the report says so)
        V = None
    if V:
        d.valid = V
    res = _fit_ols(d, _freq_total(tid, spec['freq'], d))
    wind = _col_values(tid, spec['weight'], d.df.index)
    m = {'kind': 'ls', 'd': d, 'res': res, 'coder': Coder(d, res.model.data.design_info), 'tid': tid, 'key': key, 'spec': spec,
         'w_indiv': wind if wind is not None else np.ones(len(d.df)), 'valid': V}
    m['rob'] = dict(rob, maxlags=rob['maxlags'] if rob['maxlags'] is not None else _nw_lags(len(d.df))) if rob and rob['type'] == 'HAC' else rob
    m['rres'], m['rob_note'] = _ls_robust(m, m['rob']) if rob else (None, None)
    models.remember(key, m)
    return m


def _cluster_codes(tid, name, index):
    """Integer codes of a column's values for the given rows (the clusters)."""
    v = data.series(tid, name, index, as_category=False)
    return pd.factorize(v, sort=True)[0]


def _ls_robust(m, rob):
    """statsmodels' robust covariance of the least squares fit (a results
    object with it as the default covariance, t tests on the error degrees
    of freedom, or on the clusters less one), and a note when it cannot be
    had."""
    res, d, spec = m['res'], m['d'], m['spec']
    if spec['freq']:
        return None, ('Robust Standard Errors are not computed with a Freq column: statsmodels\' sandwich takes the frequencies as '
                      'weights of single rows, not as repeated rows. The standard errors are the usual ones.')
    from statsmodels.regression.linear_model import RegressionResultsWrapper as Wrap   # the names on the estimates, as the fit's
    t = rob['type']
    if t in ('HC0', 'HC1', 'HC2', 'HC3'):
        kw = {'cov_type': t}
    elif t == 'HAC':
        kw = {'cov_type': 'HAC', 'maxlags': int(rob['maxlags'])}
    else:
        g = _cluster_codes(m['tid'], rob['cluster'], d.df.index)
        if len(np.unique(g)) < 2:
            return None, f'{rob["cluster"]} has a single value in these rows: no cluster-robust standard errors.'
        kw = {'cov_type': 'cluster', 'groups': g}
    R = Wrap(res.get_robustcov_results(use_t=True, **kw))
    if getattr(d, 'zeroed', None):
        # a singular design: the sandwich of the kept columns (the zeroed ones have none), as the estimates are theirs
        import statsmodels.api as sm_
        keep = d.keep
        red = sm_.WLS(np.asarray(res.model.endog, dtype=float), np.asarray(res.model.exog, dtype=float)[:, keep],
                      weights=np.broadcast_to(np.asarray(res.model.weights, dtype=float), (len(d.df),)))
        red.df_resid = res.model.df_resid
        Rr = red.fit().get_robustcov_results(use_t=True, **kw)
        p = len(res.params)
        C = np.zeros((p, p))
        C[np.ix_(keep, keep)] = np.asarray(Rr.cov_params(), dtype=float)
        R._results.params = np.asarray(res.params, dtype=float).copy()
        R._results.cov_params_default = C
        R._results._cache = {}
    return R, None


def _inference_df(r):
    """The degrees of freedom of a result's t and F tests (the clusters less
    one for cluster-robust errors)."""
    return float(getattr(r, 'df_resid_inference', None) or r.df_resid)


def _ls_predict(m, settings, alpha, individual=False):
    res, coder = m['res'], m['coder']
    R = m.get('rres') if m.get('rres') is not None else res   # Robust Standard Errors: the intervals too
    L = coder.rows(settings)
    b = res.params.to_numpy(float)
    V = np.asarray(R.cov_params(), dtype=float)
    est = L @ b
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', L, V, L), 0))
    t = _tcrit(alpha, _inference_df(R))
    out = {'name': m['d'].y, 'pred': est, 'lower': est - t * se, 'upper': est + t * se, 'se': se}
    if individual:
        si = np.sqrt(se ** 2 + float(res.scale))
        out['lower_indiv'], out['upper_indiv'] = est - t * si, est + t * si
    return [out]


def _diagnostics(d, res):
    """models.diagnostics in closed form: the hats from the thin QR (SVD) of
    the whitened design, the studentized residuals and Cook's D from them.
    (statsmodels' external studentized residuals refit the model once per
    row, which is too slow for the page.)"""
    X = np.asarray(res.model.wexog, dtype=float)
    U, sv, _vt = np.linalg.svd(X, full_matrices=False)
    r = int(np.sum(sv > sv.max() * max(X.shape) * np.finfo(float).eps)) if len(sv) else 0
    h = np.sum(U[:, :r] ** 2, axis=1)
    e = np.asarray(res.wresid, dtype=float)
    s2 = float(res.scale)
    dfe = float(res.df_resid)
    with np.errstate(invalid='ignore', divide='ignore'):
        ri = e / np.sqrt(s2 * (1 - h))
        ext = ri * np.sqrt((dfe - 1) / np.maximum(dfe - ri * ri, 1e-300))
        cooks = ri * ri * h / (r * (1 - h))
    return {'rows': [int(i) for i in d.df.index], 'predicted': np.asarray(res.fittedvalues, dtype=float),
            'residual': np.asarray(res.resid, dtype=float), 'actual': d.df[d.y_alias].to_numpy(float), 'studentized': ri,
            'externally': ext, 'hat': h, 'cooks': cooks}


def _lack_of_fit(d, res):
    """models.lack_of_fit, vectorised: pure error from the rows that share
    the values of every factor."""
    xs = [a for a in d.alias.values() if a != d.y_alias and a in d.df]
    if not xs:
        return None
    codes = d.df[xs].groupby(xs, observed=True, sort=False).ngroup().to_numpy()
    groups = int(codes.max()) + 1 if len(codes) else 0
    n = len(codes)
    if groups >= n:
        return None
    y = d.df[d.y_alias].to_numpy(float)
    w = d.weights if d.weights is not None else np.ones(n)
    sw = np.bincount(codes, weights=w, minlength=groups)
    mean = np.bincount(codes, weights=w * y, minlength=groups) / sw
    pe_ss = float(np.sum(w * (y - mean[codes]) ** 2))
    pe_df = n - groups
    lof_df = float(res.df_resid) - pe_df
    if pe_df <= 0 or lof_df <= 0:
        return None
    lof_ss = float(res.ssr) - pe_ss
    f = (lof_ss / lof_df) / (pe_ss / pe_df) if pe_ss > 0 else float('nan')
    p = float(stats.f.sf(f, lof_df, pe_df)) if np.isfinite(f) else None
    max_r2 = 1 - pe_ss / float(res.centered_tss) if res.centered_tss else None
    rows = [
        {'source': 'Lack Of Fit', 'df': lof_df, 'ss': lof_ss, 'ms': lof_ss / lof_df, 'f': f, 'p': p},
        {'source': 'Pure Error', 'df': pe_df, 'ss': pe_ss, 'ms': pe_ss / pe_df, 'f': None, 'p': None},
        {'source': 'Total Error', 'df': float(res.df_resid), 'ss': float(res.ssr), 'ms': None, 'f': None, 'p': None},
    ]
    return rtable([col('source', 'Source', 'text'), col('df', 'DF', 'num'), col('ss', 'Sum of Squares'), col('ms', 'Mean Square'),
                   col('f', 'F Ratio'), col('p', 'Prob > F', 'p')], rows, max_rsquare=max_r2)


def _ls_diag(m, alpha):
    d, res = m['d'], m['res']
    out = _diagnostics(d, res)
    pred = np.asarray(out['predicted'], dtype=float)
    se = np.asarray(res.get_prediction().se_mean, dtype=float)
    s2 = float(res.scale)
    t = _tcrit(alpha, res.df_resid)
    w = m['w_indiv']
    si = np.sqrt(se ** 2 + s2 / w)
    out.update({'se_pred': se, 'lower_mean': pred - t * se, 'upper_mean': pred + t * se, 'se_indiv': si,
                'lower_indiv': pred - t * si, 'upper_indiv': pred + t * si, 'se_resid': np.sqrt(np.maximum(s2 / w - se ** 2, 0))})
    # the limits of JMP's studentized residual plot (external residuals: t with dfe - 1)
    dfe = float(res.df_resid)
    nobs = len(pred)
    out['limits'] = {'individual': _tcrit(alpha, dfe - 1), 'bonferroni': _tcrit(alpha / nobs, dfe - 1) if nobs else None}
    return out


def _hbar(X, w):
    xbar = np.average(X, axis=0, weights=w)
    A = np.linalg.pinv((X * w[:, None]).T @ X)
    return float(xbar @ A @ xbar)


def _conf_curve(x0, x1, c, F, fcrit, t, s2, hbar, slope=None, xbar=None, n=60):
    """Sall's confidence curves of a leverage plot, in its coordinates:
    z +- sqrt(t^2 s^2 hbar + (F_alpha / F) z^2), z the distance from the mean."""
    if not (F and np.isfinite(F) and F > 0 and np.isfinite(fcrit) and np.isfinite(t)):
        return None
    xs = np.linspace(x0, x1, n)
    z = (xs - xbar) * slope if slope is not None else xs - c
    half = np.sqrt(t * t * s2 * hbar + (fcrit / F) * z * z)
    return {'x': xs, 'lower': c + z - half, 'upper': c + z + half}


def _leverage(m, alpha, tests):
    """JMP's effect leverage plots (Sall 1990): for each point the residual
    under the hypothesis that the effect is zero (its distance from the
    horizontal line at the mean) and the model's residual (its distance
    from the line of fit)."""
    d, res = m['d'], m['res']
    X = np.asarray(res.model.exog, dtype=float)
    y = np.asarray(res.model.endog, dtype=float)
    w = d.weights if d.weights is not None else np.ones(len(y))
    sw = np.sqrt(w)
    names = list(res.params.index)
    b = res.params.to_numpy(float)
    r = y - X @ b
    c = float(np.average(y, weights=w)) if 'Intercept' in names else 0.0
    hb = _hbar(X, w)
    dfe = float(res.df_resid)
    s2 = float(res.scale)
    t = _tcrit(alpha, dfe)
    rows = [int(i) for i in d.df.index]
    out = []
    for e in d.effects:
        cols = [names.index(tn) for tn in e.get('terms', []) if tn in names]
        test = tests.get(e['label'])
        if not cols or test is None:
            continue
        keep = [j for j in range(X.shape[1]) if j not in cols]
        if keep:
            b0 = np.linalg.lstsq(X[:, keep] * sw[:, None], y * sw, rcond=None)[0]
            r0 = y - X[:, keep] @ b0
        else:
            r0 = y.copy()
        F, p, q = test['stat'], test['p'], test.get('df', test['nparm'])
        if not q or F is None:
            continue
        fcrit = float(stats.f.ppf(1 - alpha, q, dfe)) if dfe > 0 else float('nan')
        xs, ys = r0 - r + c, r0 + c
        slope = xbar = None
        a = d.alias[e['names'][0]]
        if len(e['cols']) == 1 and a not in d.categorical and len(cols) == 1 and b[cols[0]] != 0 and np.isfinite(b[cols[0]]):
            slope, xbar = float(b[cols[0]]), float(d.df[a].mean())
            xs = (xs - c) / slope + xbar
        lo, hi = float(np.min(xs)), float(np.max(xs))
        pad = 0.04 * (hi - lo if hi > lo else 1.0)
        x0, x1 = lo - pad, hi + pad
        # the line of fit: slope one in the response's units, the estimate in the regressor's
        line_y = [c + (x0 - xbar) * slope, c + (x1 - xbar) * slope] if slope is not None else [x0, x1]
        curve = _conf_curve(x0, x1, c, F, fcrit, t, s2, hb, slope, xbar)
        out.append({'effect': e['label'], 'x': xs, 'y': ys, 'rows': rows, 'f': F, 'p': p, 'nparm': q, 'fcrit': fcrit, 'hbar': hb,
                    'mean': c, 'slope': slope, 'xbar': xbar, 'units': 'x' if slope is not None else 'y',
                    'line': {'x': [x0, x1], 'y': line_y}, 'curve': curve})
    return out


def _estimable(m, L):
    """Rows of L that are estimable functions (in the row space of X)."""
    res = m['res']
    if res.model.rank >= res.model.exog.shape[1]:
        return np.ones(len(L), dtype=bool)
    X = np.asarray(res.model.exog, dtype=float)
    P = np.linalg.pinv(X) @ X
    dev = np.abs(L - L @ P).max(axis=1)
    return dev <= 1e-7 * np.maximum(1.0, np.abs(L).max(axis=1))


def _lsmeans(m, e):
    """Least squares means of an effect of categorical factors: the model's
    prediction at each level (combination), the other categorical factors
    averaged over their levels, the continuous ones at their means."""
    d, res, coder = m['d'], m['res'], m['coder']
    names = list(dict.fromkeys(e['cols']))
    aliases = [d.alias[n] for n in names]
    if any(a not in d.categorical for a in aliases):
        return None
    levels = [d.levels[a] for a in aliases]
    codes = np.column_stack([d.df[a].cat.codes.to_numpy() for a in aliases])
    if e['spec']['nest']:
        seen = sorted({tuple(r) for r in codes.tolist()})
        combos = [c for c in itertools.product(*[range(len(lv)) for lv in levels]) if c in set(seen)]
    else:
        combos = list(itertools.product(*[range(len(lv)) for lv in levels]))
    others = {a: AVG for a in d.categorical if a not in aliases}
    settings = [dict(others, **{a: i for a, i in zip(aliases, c)}) for c in combos]
    L = coder.rows(settings)
    b = res.params.to_numpy(float)
    V = res.cov_params().to_numpy(float)
    est = L @ b
    C = L @ V @ L.T
    se = np.sqrt(np.maximum(np.diag(C), 0))
    ok = _estimable(m, L)
    est = np.where(ok, est, np.nan)
    se = np.where(ok, se, np.nan)
    y = d.df[d.y_alias].to_numpy(float)
    w = d.weights if d.weights is not None else np.ones(len(y))
    raw, cnt = [], []
    for c in combos:
        mask = np.all(codes == np.asarray(c), axis=1)
        cnt.append(float(np.sum(w[mask])))
        raw.append(float(np.average(y[mask], weights=w[mask])) if mask.any() else None)
    labels = [','.join(_lvl(levels[k][i]) for k, i in enumerate(c)) for c in combos]
    return {'effect': e['label'], 'factors': names, 'levels': [[levels[k][i] for k, i in enumerate(c)] for c in combos], 'labels': labels,
            'lsmean': est, 'se': se, 'mean': raw, 'n': cnt, 'L': L, 'C': C, 'estimable': ok, 'combos': [tuple(int(i) for i in c) for c in combos]}


def _effect_of(d, label):
    for e in d.effects:
        if e['label'] == label:
            return e
    raise KeyError(f'no effect {label!r} in the model')


@api('fitmodel.ls')
def ls(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, vif=False, leverage=True,
       dw=False, sequential=False, corr=False, robust=None, ccpr=False, validation=None, center=True, indicator=False, expanded=False,
       table_name='data'):
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, robust=robust, validation=validation, center=center)
    m = _ls_model(table, rows, spec)
    d, res = m['d'], m['res']
    yname = spec['y'][0]
    notes = []
    singular = res.model.rank < res.model.exog.shape[1]
    if singular and getattr(d, 'zeroed', None):
        notes.append(f'The design is singular: {len(d.zeroed)} column(s) are linear combinations of the ones before them (in the order '
                     'of the effects, the intercept first). As JMP, they are Zeroed (their estimates 0) and the estimates they alias are '
                     'Biased: see Singularity Details. The Effect Tests test the other columns of each effect (DF, with LostDFs the '
                     'zeroed ones); the fit and its predictions are those of any solution.')
    elif singular:
        notes.append(f'The design is singular: {res.model.exog.shape[1] - res.model.rank} parameter(s) are not estimable. statsmodels '
                     'gives the minimum-norm solution (pinv); JMP would mark the aliased terms Biased or Zeroed. Tests of '
                     'non-estimable hypotheses are not meaningful.')
    # Robust Standard Errors: the estimates, their tests and the effect tests
    # use the robust covariance; the rest of the report is least squares'.
    R = m['rres'] if m.get('rres') is not None else res
    dfi = _inference_df(R)
    et = models.effect_tests(d, R)
    tests = {r['source']: r for r in (models.effect_tests(d, res)['rows'] if R is not res else et['rows'])}
    if R is not res:
        for r in et['rows']:
            r.pop('ss', None)
            r['dfden'] = dfi
        et['columns'] = [col('source', 'Source', 'text'), col('nparm', 'Nparm', 'int'), col('df', 'DF', 'int'), col('dfden', 'DFDen', 'num'),
                         col('stat', 'F Ratio'), col('p', 'Prob > F', 'p')]
    else:
        _effect_sizes(et, res)
    est = models.estimates(d, R, alpha, vif=vif, std_beta=vif, design_se=vif)   # the optional columns come together (the page asks for them)
    names = list(res.params.index)
    bJ, VJ = res.params.to_numpy(float), np.asarray(R.cov_params(), dtype=float)
    T = _uncenter(d, names)
    if T is not None:
        bJ, VJ = T @ bJ, T @ VJ @ T.T
    for r in est['rows']:
        r['term'] = _tlabel(d, r['name'])
        if r['name'] == 'Intercept' and T is not None:
            i0 = names.index('Intercept')
            se0 = math.sqrt(max(VJ[i0, i0], 0))
            t0 = bJ[i0] / se0 if se0 > 0 else float('nan')
            tc0 = _tcrit(alpha, dfi)
            r.update({'estimate': bJ[i0], 'se': se0, 't': t0, 'p': float(2 * stats.t.sf(abs(t0), dfi)), 'lower': bJ[i0] - tc0 * se0, 'upper': bJ[i0] + tc0 * se0})
    n = float(np.sum(d.weights)) if d.weights is not None else float(len(d.df))
    k = int(res.model.rank) + 1        # the parameters and the error variance
    llf = float(res.llf)
    aicc = -2 * llf + 2 * k + (2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else float('nan'))
    bic = -2 * llf + k * math.log(n)
    # Effect Summary: the effect tests by LogWorth, with FDR-adjusted p-values
    esum = [{'source': r['source'], 'p': r['p'], 'logworth': _logworth(r['p'])} for r in et['rows'] if r['p'] is not None]
    if esum:
        from statsmodels.stats.multitest import multipletests
        adj = multipletests([r['p'] for r in esum], method='fdr_bh')[1]
        for r, a in zip(esum, adj):
            r['fdr_p'] = float(a)
            r['fdr_logworth'] = _logworth(float(a))
    esum.sort(key=lambda r: -(r['logworth'] or 0))
    dfm, dfe = float(res.df_model), float(res.df_resid)
    whole = {'f': float(res.fvalue) if dfm > 0 and dfe > 0 else None, 'p': float(res.f_pvalue) if dfm > 0 and dfe > 0 else None,
             'df_model': dfm, 'df_error': dfe, 'rmse': float(math.sqrt(res.scale)) if dfe > 0 else None, 'rsq': float(res.rsquared),
             'mean': float(np.average(d.df[d.y_alias], weights=d.weights))}
    diag = _ls_diag(m, alpha)
    X = np.asarray(res.model.exog, dtype=float)
    wv = d.weights if d.weights is not None else np.ones(len(d.df))
    whole['hbar'] = _hbar(X, wv)
    if whole['f'] is not None:
        fcrit = float(stats.f.ppf(1 - alpha, dfm, dfe))
        pr = np.asarray(diag['predicted'], dtype=float)
        lo, hi = float(pr.min()), float(pr.max())
        pad = 0.04 * (hi - lo if hi > lo else 1.0)
        c = whole['mean'] if 'Intercept' in res.params.index else 0.0
        whole['curve'] = _conf_curve(lo - pad, hi + pad, c, whole['f'], fcrit, _tcrit(alpha, dfe), float(res.scale), whole['hbar'])
        whole['fcrit'] = fcrit
    out = {'y': yname, 'n': n, 'n_rows': int(len(d.df)), 'key': m['key'], 'summary': models.summary_of_fit(d, res), 'aicc': aicc,
           'bic': bic, 'loglik': llf, 'anova': models.anova(d, res), 'lof': _lack_of_fit(d, res), 'estimates': est,
           'effect_tests': et, 'effect_summary': esum, 'whole': whole, 'diag': diag, 'factors': _factors(d), 'singular': singular,
           'alpha': alpha, 'tcrit': _tcrit(alpha, dfe), 'dfe': dfe}
    out['effects'] = [{'label': e['label'], 'nparm': len(e.get('terms', [])), 'names': e['cols'],
                       'categorical': all(d.alias[n] in d.categorical for n in e['cols'])} for e in d.effects]
    out['lsmeans'] = {}
    tci = _tcrit(alpha, dfi)
    for e in d.effects:
        lsm = _lsmeans(m, e)
        if lsm is not None:
            out['lsmeans'][e['label']] = {k2: lsm[k2] for k2 in ('factors', 'levels', 'labels', 'lsmean', 'se', 'mean', 'n')}
            out['lsmeans'][e['label']].update({'lower': lsm['lsmean'] - tci * lsm['se'], 'upper': lsm['lsmean'] + tci * lsm['se'],
                                              'slices': len(lsm['factors']) >= 2})
    if leverage:
        out['leverage'] = _leverage(m, alpha, tests)
    e2 = np.asarray(diag['residual'], dtype=float)
    h = np.asarray(diag.get('hat', np.zeros(len(e2))), dtype=float)
    ok = h < 1 - 1e-12
    press_r = np.where(ok, e2 / np.where(ok, 1 - h, 1), np.nan)
    press = float(np.nansum(wv * press_r ** 2))
    out['press'] = {'press': press, 'rmse': math.sqrt(press / n) if n else None}
    if dw:
        out['dw'] = _durbin_watson(res)
    if sequential:
        out['sequential'] = _sequential(d, res)
    if corr:
        sd = np.sqrt(np.diag(VJ))
        with np.errstate(invalid='ignore', divide='ignore'):
            Rc = VJ / np.outer(sd, sd)
        order = [r['name'] for r in est['rows']]
        idx = [names.index(o) for o in order]
        out['corr'] = {'terms': [_tlabel(d, o) for o in order], 'matrix': Rc[np.ix_(idx, idx)]}
    out['expression'] = [{'term': r['term'], 'estimate': r['estimate']} for r in est['rows']]
    if any(data.meta(table, nm).get('modelingType') == 'ordinal' for nm in _factor_names(d)):
        notes.append('Ordinal factors are coded like nominal ones (effect coding, the last level the negative sum of the others); JMP codes '
                     'them as differences between adjacent levels. The fit, the tests, the least squares means and the predictions are the '
                     'same; the parameter estimates of ordinal factors are not.')
    if spec['freq']:
        notes.append('Freq counts each row that many times: the error degrees of freedom are the sum of the frequencies minus the '
                     'parameters, as in JMP.')
    out['rank'] = int(res.model.rank)
    rob = m.get('rob')
    if m.get('rob_note'):
        notes.append(m['rob_note'])
    if R is not res:
        ng = int(dfi) + 1 if rob['type'] == 'cluster' else None
        wf = float(np.squeeze(R.fvalue)) if dfm > 0 else None
        out['robust'] = {'type': rob['type'], 'label': _robust_label(rob, groups=ng), 'df': dfi, 'clusters': ng, 'maxlags': rob.get('maxlags'),
                         'wald_f': wf, 'wald_df': dfm, 'wald_p': float(np.squeeze(R.f_pvalue)) if wf is not None else None}
        notes.append(_ls_robust_note(rob, dfi, ng))
    if ccpr:
        out['ccpr'] = _ccpr(m)
    out['notes'] = notes
    lines = _code_frame(d, table, table_name, rows, [weight, freq])
    wexpr = ' * '.join(f'd[{json.dumps(v)}]' for v in (weight, freq) if v)
    fit = f'smf.wls({json.dumps(_code_formula(d))}, data=d, weights={wexpr})' if wexpr else f'smf.ols({json.dumps(_code_formula(d))}, data=d)'
    if freq:
        lines += [f'mod = {fit}   # C(x, Sum): effect coding, as JMP; crossings and powers centred at the means',
                  f'mod.df_resid = d[{json.dumps(freq)}].sum() - np.linalg.matrix_rank(mod.exog)   # Freq: JMP\'s error degrees of freedom',
                  'fit = mod.fit()']
    else:
        lines.append(f'fit = {fit}.fit()   # C(x, Sum): effect coding, as JMP; crossings and powers centred at the means')
    fit_lines = list(lines)
    lines += ['print(fit.summary())   # Summary of Fit, Parameter Estimates', 'print(sm.stats.anova_lm(fit, typ=3))   # Effect Tests (Type III)']
    lines += _zeroed_code(d)
    if getattr(d, 'zeroed', None):
        out['singularity'] = _singularity_details(d)
        out['singularity']['code'] = '\n'.join(fit_lines + _zeroed_code(d) + [
            f'for j in {[list(res.params.index).index(z) for z in d.zeroed]!r}:   # each zeroed column as a combination of the kept ones',
            '    c = np.linalg.lstsq(fit.model.exog[:, keep], fit.model.exog[:, j], rcond=None)[0]',
            '    print(fit.params.index[j], "=", {fit.params.index[k]: round(v, 10) for k, v in zip(keep, c) if abs(v) > 1e-9})'])
    if wexpr:
        lines.append('infl = sm.OLS(fit.model.wendog, fit.model.wexog).fit().get_influence()   # hats, studentized residuals, Cook\'s D (of the weighted fit)')
    else:
        lines.append('infl = fit.get_influence()   # residuals, studentized residuals, hats, Cook\'s D')
    if R is not res:
        lines += _robust_code(rob)
    elif any('pes' in r for r in et['rows']):
        lines += ['et = sm.stats.anova_lm(fit, typ=3).drop(index=["Intercept", "Residual"], errors="ignore")   # Effect Tests, and their optional columns:',
                  'N = fit.df_resid + np.linalg.matrix_rank(fit.model.exog)   # the observations the DF count',
                  'et["Partial eta2"] = et.sum_sq / (et.sum_sq + fit.ssr)',
                  'et["Partial omega2"] = (et.sum_sq - et.df * fit.mse_resid) / (et.sum_sq + (N - et.df) * fit.mse_resid)',
                  'print(et)']
    lines += _centred_code(d)
    out['code'] = '\n'.join(lines)
    # the Estimates menu: Indicator Parameterization Estimates, Expanded Estimates (the report's covariance: robust when asked)
    if indicator:
        out['indicator'] = _indicator_report(d, R, alpha, dfi, fit_lines, rob if R is not res else None, weight, freq)
    if expanded:
        out['expanded'] = _expanded_report(d, R, alpha, dfi, fit_lines, rob if R is not res else None)
    notes.extend(_kfold_note(d))
    V = m.get('valid')
    if V:   # the Validation column: every set predicted from the training fit, and measured
        di = res.model.data.design_info
        idx, Xv, _ = models.new_rows(d, di, table, rows=V['P'].index)
        fv = Xv @ _ls_coef(m)[0]
        cv_code = fit_lines + _cv_frame_code(d, table, V, [weight, freq]) + [
            'pred, ya = fit.predict(a).to_numpy(), a[' + json.dumps(yname) + '].to_numpy(float)   # every set predicted by the training fit'] + _cv_measure_code('continuous')
        out['crossvalidation'] = _cv_report(m, idx, fv, code='\n'.join(cv_code))
        out['holdout'] = _holdout(V, idx, fv, _col_values(table, yname, idx))
        notes.insert(0, f'{V["column"]}: the model is fitted to the training rows (0, or Training); the validation (1) and test (2) rows are '
                        'predicted by it and measured in Crossvalidation, and marked in the plots. Every other table is the training fit\'s.')
    out['plot_code'] = _ls_plots(m, spec, table, rows, table_name, alpha, weight, freq, out)
    return out


def _holdout(V, idx, fitted, actual):
    """The validation and test rows of a model with a Validation column, for
    the plots that mark them: their rows, sets, predictions (a continuous
    response) and actual values."""
    st = dict(zip((int(r) for r in V['P'].index), (int(s_) for s_ in V['P'].sets)))
    keep = [i for i, r in enumerate(idx) if st.get(int(r), 0) > 0]
    f = np.asarray(fitted, dtype=float)
    out = {'rows': [int(idx[i]) for i in keep], 'set': [st[int(idx[i])] for i in keep]}
    if f.ndim == 1:
        a = np.asarray(actual, dtype=float)
        out.update({'predicted': f[keep], 'actual': a[keep], 'residual': a[keep] - f[keep]})
    return out


# ---------------------------------------------------------------------------
# the graphs as matplotlib code
# ---------------------------------------------------------------------------
# Under each graph the report shows Python that draws it with matplotlib from a
# CSV export of the table (the notebook runs it): the model fitted as the
# report's code fits it, the light theme's colours, the graph's size at 100
# pixels an inch.
BASE, BAR, FIT, MEAN, MUTED, TEXT = '#2f6690', '#8fa9c2', '#c0392b', '#2f6690', '#786b5d', '#352921'
PALETTE = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']
PLT = 'import matplotlib.pyplot as plt'
J = json.dumps


def _fig(w, h, extra=''):
    return f'fig, ax = plt.subplots(figsize=({w / 100:g}, {h / 100:g}), layout="constrained"{extra})'


def _p_text(p):
    """The page's P text of a p-value, as a code expression: <.0001 or =0.1234."""
    return f'("<.0001" if {p} < 0.0001 else f"={{{p}:.4f}}")'


def _row_plot(head, x, y, n, xlabel, ylabel, title, w=380, h=300, lines=(), zero=False, xlabel_code=False, label=None):
    """The rows as points (x and y code expressions) with reference lines, as
    the page's rowPlot draws them; xlabel_code: xlabel is an expression;
    label: the points' name in a legend (the Training set, when the hold-out
    rows are marked too)."""
    lab = f', label={J(label)}' if label else ''
    c = list(head) + [_fig(w, h + (22 if label else 0)), f'ax.scatter({x}, {y}, s={8 if n > 500 else 18}, color="{BASE}"{lab})', *lines]
    if zero:
        c.append(f'ax.axhline(0, color="{MEAN}", linewidth=0.7)')
    c += [f'ax.set_xlabel({xlabel if xlabel_code else J(xlabel)})', f'ax.set_ylabel({J(ylabel)})', f'ax.set_title({J(title)})', 'plt.show()']
    return '\n'.join(c)


def _hold_code(m, table, y, extra_cols, xexpr, yexpr):
    """A plot's code lines for the validation and test rows of a model with a
    Validation column (after the fit's code, which makes fit): the head's
    (every set, predicted: pa, and ya the actual values) and the plot's (the
    hold-out rows marked, a legend). Nothing without one."""
    V = m.get('valid')
    if not V:
        return [], []
    head = _cv_frame_code(m['d'], table, V, extra_cols) + [f'pa, ya = fit.predict(a).to_numpy(), a[{J(y)}].to_numpy(float)   # every set, predicted by the training fit']
    lines = ['for k, (name, marker, color) in {1: ("Validation", "^", "#d9822b"), 2: ("Test", "s", "#3a7d44")}.items():   # the hold-out rows, marked',
             '    s_ = sets == k',
             '    if s_.any():',
             f'        ax.scatter({xexpr}[s_], {yexpr}[s_], marker=marker, s=26, color=color, label=name)',
             'fig.legend(loc="outside lower center", ncols=3, fontsize=8, frameon=False)']
    return head, lines


def _positive_weights(weight, freq):
    """The line that keeps the rows with a positive Weight and Freq, as the fit takes them."""
    wexpr = ' * '.join(f'd[{J(v)}]' for v in (weight, freq) if v)
    return [f'd = d[{wexpr} > 0]   # the rows with a positive weight'] if wexpr else []


def _ls_fit_code(d, table, table_name, rows, weight, freq, imports=()):
    """The lines that fit the least squares model as the report's code does."""
    lines = _code_frame(d, table, table_name, rows, [weight, freq], extra_imports=[PLT, *imports]) + _positive_weights(weight, freq)
    wexpr = ' * '.join(f'd[{J(v)}]' for v in (weight, freq) if v)
    fit = f'smf.wls({J(_code_formula(d))}, data=d, weights={wexpr})' if wexpr else f'smf.ols({J(_code_formula(d))}, data=d)'
    if freq:
        lines += [f'mod = {fit}', f'mod.df_resid = d[{J(freq)}].sum() - np.linalg.matrix_rank(mod.exog)   # Freq: JMP\'s error degrees of freedom', 'fit = mod.fit()']
    else:
        lines.append(f'fit = {fit}.fit()   # C(x, Sum): effect coding, as JMP; crossings and powers centred at the means')
    lines.append(f'w = ({wexpr}).to_numpy()' if wexpr else 'w = np.ones(len(d))')
    return lines


def _studentized_code():
    """The externally studentized residuals as the report makes them (the
    hats of the weighted design, Freq's error degrees of freedom)."""
    return ['h = sm.OLS(fit.model.wendog, fit.model.wexog).fit().get_influence().hat_matrix_diag   # the hats',
            'ri = fit.wresid / np.sqrt(fit.scale * (1 - h)); dfe = fit.df_resid',
            'ext = ri * np.sqrt((dfe - 1) / (dfe - ri ** 2))   # externally studentized: the row left out']


def _ls_plots(m, spec, table, rows, table_name, alpha, weight, freq, out):
    """The graphs of a Standard Least Squares report as code: Regression Plot,
    Actual by Predicted, the residual plots, the leverage plots, the influence
    and component plus residual plots, the sorted estimates, the least squares
    means plots."""
    d, res = m['d'], m['res']
    y = spec['y'][0]
    n = len(d.df)
    fitc = lambda imports=(): _ls_fit_code(d, table, table_name, rows, weight, freq, imports)   # noqa: E731
    codes = {}
    # ---- Actual by Predicted, with the mean and Sall's confidence curves
    wh = out['whole']
    hh, hl = _hold_code(m, table, y, [weight, freq], 'pa', 'ya')
    c = fitc(['from scipy import stats']) + [f'pred, actual = fit.fittedvalues.to_numpy(), d[{J(y)}].to_numpy()'] + hh + [
        ('lo, hi = min(pred.min(), actual.min(), pa.min(), ya.min()), max(pred.max(), actual.max(), pa.max(), ya.max())   # the hold-out rows too' if hh
         else 'lo, hi = min(pred.min(), actual.min()), max(pred.max(), actual.max())'),
        'm = np.average(actual, weights=w)   # the mean of Y']
    lines = [f'ax.plot([lo, hi], [lo, hi], color="{FIT}", linewidth=1)   # the line of fit',
             f'ax.plot([lo, hi], [m, m], color="{MEAN}", linewidth=0.9, linestyle=":")   # the mean']
    if wh.get('curve'):
        c += ['X = fit.model.exog; xbar = np.average(X, axis=0, weights=w)',
              'hbar = xbar @ np.linalg.pinv((X * w[:, None]).T @ X) @ xbar',
              f'F, fcrit, t = fit.fvalue, stats.f.ppf({1 - alpha!r}, fit.df_model, fit.df_resid), stats.t.ppf({1 - alpha / 2!r}, fit.df_resid)',
              'pad = 0.04 * (pred.max() - pred.min() or 1.0); gx = np.linspace(pred.min() - pad, pred.max() + pad, 60)',
              f'c0 = {"m" if "Intercept" in res.params.index else "0.0"}; z = gx - c0',
              'half = np.sqrt(t ** 2 * fit.scale * hbar + (fcrit / F) * z ** 2)   # Sall\'s confidence curves (1990)']
        lines.append(f'ax.plot(gx, c0 + z - half, gx, c0 + z + half, color="{FIT}", linewidth=0.7, linestyle="--")')
    if wh.get('p') is not None:   # the whole model's test, RSquare and RMSE in the title, as the page has them
        xl = J(f'{y} Predicted P') + ' + ' + _p_text('fit.f_pvalue') + ' + f" RSq={fit.rsquared:.2f} RMSE={np.sqrt(fit.scale):.5g}"'
        codes['actpred'] = _row_plot(c, 'pred', 'actual', n, xl, f'{y} Actual', f'{y} actual by predicted', 400, 320, lines + hl, xlabel_code=True, label='Training' if hh else None)
    else:
        codes['actpred'] = _row_plot(c, 'pred', 'actual', n, f'{y} Predicted', f'{y} Actual', f'{y} actual by predicted', 400, 320, lines + hl, label='Training' if hh else None)
    # ---- the residual plots
    hh, hl = _hold_code(m, table, y, [weight, freq], 'pa', '(ya - pa)')
    codes['residpred'] = _row_plot(fitc() + hh, 'fit.fittedvalues', 'fit.resid', n, f'{y} Predicted', f'{y} Residual', f'{y} residual by predicted', zero=True, lines=hl,
                                   label='Training' if hh else None)
    codes['residrow'] = _row_plot(fitc(), 'd.index + 1', 'fit.resid', n, 'Row Number', f'{y} Residual', f'{y} residual by row', 460, zero=True)
    lim = out['diag'].get('limits') or {}
    lines = [f'ax.axhline(0, color="{MEAN}", linewidth=0.7)']
    c = fitc(['from scipy import stats']) + _studentized_code()
    if lim.get('individual') is not None:
        c.append(f'ind = stats.t.ppf({1 - alpha / 2!r}, dfe - 1); bonf = stats.t.ppf(1 - {alpha!r} / (2 * len(d)), dfe - 1)   # the individual and the Bonferroni limits')
        lines += [f'ax.axhline(ind, color="{MUTED}", linewidth=0.7, linestyle="--"); ax.axhline(-ind, color="{MUTED}", linewidth=0.7, linestyle="--")',
                  f'ax.axhline(bonf, color="{FIT}", linewidth=0.7); ax.axhline(-bonf, color="{FIT}", linewidth=0.7)']
    codes['student'] = _row_plot(c, 'd.index + 1', 'ext', n, 'Row Number', 'Externally Studentized Residuals', f'{y} studentized residuals', 460, 300, lines)
    c = fitc(['from scipy import stats']) + ['e = fit.resid.to_numpy(); o = np.argsort(e, kind="stable")',
                                             'z = stats.norm.ppf(stats.rankdata(e) / (len(e) + 1))[o]   # each residual\'s normal quantile, Φ⁻¹(r/(n+1))',
                                             'm, s = e.mean(), e.std(ddof=1)']
    codes['residqq'] = _row_plot(c, 'z', 'e[o]', n, 'Normal Quantile', f'{y} Residual', f'{y} residual normal quantile plot', 360, 300,
                                 [f'ax.plot([z.min(), z.max()], [m + s * z.min(), m + s * z.max()], color="{FIT}", linewidth=0.9)'])
    # ---- the leverage plots (Sall 1990): each effect's residuals with and without it
    lev = {}
    names = list(res.params.index)
    has_int = 'Intercept' in names
    for i, e in enumerate(d.effects):
        cols = [names.index(tn) for tn in e.get('terms', []) if tn in names]
        L = next((q for q in out.get('leverage') or [] if q['effect'] == e['label']), None)
        if not cols or L is None:
            continue
        terms = list(res.model.data.design_info.term_names)
        pos = terms.index(e['patsy']) if e.get('patsy') in terms else None   # the effect's line in the Wald tests of the terms
        c = fitc(['from scipy import stats'])
        c += ['X, yv = fit.model.exog, fit.model.endog; sw = np.sqrt(w)',
              'r = yv - X @ fit.params.to_numpy()', f'c0 = {"np.average(yv, weights=w)" if has_int else "0.0"}   # the mean line',
              f'cols = {cols}   # the columns of {e["label"]} in the design',
              'keep = [j for j in range(X.shape[1]) if j not in cols]',
              'b0 = np.linalg.lstsq(X[:, keep] * sw[:, None], yv * sw, rcond=None)[0] if keep else np.zeros(0)',
              'r0 = yv - X[:, keep] @ b0   # the residuals without the effect',
              'xs, ys = r0 - r + c0, r0 + c0']
        if L.get('slope') is not None:
            c += [f'slope, xbar = fit.params.iloc[{cols[0]}], d[{J(e["names"][0])}].mean()   # in the units of {e["names"][0]}', 'xs = (xs - c0) / slope + xbar']
        c += ['pad = 0.04 * (xs.max() - xs.min() or 1.0); x0, x1 = xs.min() - pad, xs.max() + pad']
        c.append('ly = [c0 + (x0 - xbar) * slope, c0 + (x1 - xbar) * slope]' if L.get('slope') is not None else 'ly = [x0, x1]')
        wt = f'fit.wald_test_terms(skip_single=False, scalar=True).table.iloc[{pos}]' if pos is not None else None
        lines = [f'ax.plot([x0, x1], ly, color="{FIT}", linewidth=1)', f'ax.plot([x0, x1], [c0, c0], color="{MEAN}", linewidth=0.9, linestyle=":")']
        if wt:
            c.append(f'test = {wt}   # the effect\'s F test')
            c.append('F, p, q = test["statistic"], test["pvalue"], test["df_constraint"]')
        if L.get('curve') and wt:
            c += ['xb = np.average(X, axis=0, weights=w); hbar = xb @ np.linalg.pinv((X * w[:, None]).T @ X) @ xb',
                  f'fcrit, t = stats.f.ppf({1 - alpha!r}, q, fit.df_resid), stats.t.ppf({1 - alpha / 2!r}, fit.df_resid)',
                  'gx = np.linspace(x0, x1, 60)', 'z = (gx - xbar) * slope' if L.get('slope') is not None else 'z = gx - c0',
                  'half = np.sqrt(t ** 2 * fit.scale * hbar + (fcrit / F) * z ** 2)   # Sall\'s confidence curves']
            lines.append(f'ax.plot(gx, c0 + z - half, gx, c0 + z + half, color="{FIT}", linewidth=0.7, linestyle="--")')
        if wt:
            xl = J(f'{e["label"]} Leverage, P') + ' + ' + _p_text('p') + (' + " (usual F test)"' if out.get('robust') else '')
            lev[e['label']] = _row_plot(c, 'xs', 'ys', n, xl, f'{y} Leverage Residuals', f'{e["label"]} leverage plot', 340, 290, lines, xlabel_code=True)
        else:
            lev[e['label']] = _row_plot(c, 'xs', 'ys', n, f'{e["label"]} Leverage', f'{y} Leverage Residuals', f'{e["label"]} leverage plot', 340, 290, lines)
    codes['leverage'] = lev
    # ---- the Regression Plot: one continuous factor, at most one categorical
    facs = out['factors']
    cont = [f for f in facs if f['type'] == 'continuous']
    cats = [f for f in facs if f['type'] == 'categorical']
    if len(cont) == 1 and len(cats) <= 1:
        xf, gf = cont[0], (cats[0] if cats else None)
        rob = m.get('rob') if m.get('rres') is not None else None
        imports = ['from scipy import stats', 'import patsy'] if rob else []
        c = fitc(imports) + [f'gx = np.linspace(d[{J(xf["name"])}].min(), d[{J(xf["name"])}].max(), 81)']
        if gf is None:
            c.append(_fig(400, 320))
            c.append(f'ax.scatter(d[{J(xf["name"])}], d[{J(y)}], s={8 if n > 500 else 18}, color="{BASE}")')
            if rob:
                c += [_robust_code(rob)[0],
                      f'Xg = np.asarray(patsy.build_design_matrices([fit.model.data.design_info], pd.DataFrame({{{J(xf["name"])}: gx}}))[0])',
                      'fy = Xg @ fit.params.to_numpy(); se = np.sqrt(np.einsum("ij,jk,ik->i", Xg, rob.cov_params(), Xg))',
                      f't = stats.t.ppf({1 - alpha / 2!r}, getattr(rob, "df_resid_inference", None) or rob.df_resid)   # the robust interval',
                      'lower, upper = fy - t * se, fy + t * se']
            else:
                c += [f'band = fit.get_prediction(pd.DataFrame({{{J(xf["name"])}: gx}})).summary_frame(alpha={alpha!r})',
                      'fy, lower, upper = band["mean"], band["mean_ci_lower"], band["mean_ci_upper"]']
            c += [f'ax.plot(gx, lower, gx, upper, color="{FIT}", linewidth=0.7, linestyle=":")   # the confidence band of the mean',
                  f'ax.plot(gx, fy, color="{FIT}", linewidth=1.3)']
        else:
            lv = gf['levels']
            c += [f'levels = [{", ".join(_pylit(v) for v in lv)}]; names = {J(gf["labels"])}   # {gf["name"]}, in the table\'s order',
                  f'colors = {J(PALETTE)}', _fig(440, 320),
                  f'ax.scatter(d[{J(xf["name"])}], d[{J(y)}], s={8 if n > 500 else 18}, c=[colors[levels.index(v) % len(colors)] for v in d[{J(gf["name"])}]])',
                  'for i, v in enumerate(levels):',
                  f'    ax.plot(gx, fit.predict(pd.DataFrame({{{J(xf["name"])}: gx, {J(gf["name"])}: [v] * len(gx)}})), color=colors[i % len(colors)], linewidth=1.3, label=names[i])',
                  f'ax.legend(title={J(gf["name"])}, fontsize=8, frameon=False)']
        c += [f'ax.set_xlabel({J(xf["name"])})', f'ax.set_ylabel({J(y)})', f'ax.set_title({J(y + " regression plot")})', 'plt.show()']
        codes['regression'] = '\n'.join(c)
    # ---- the Influence Plot: the studentized residual against the leverage, the bubble's area Cook's D
    p = int(res.model.rank)
    c = fitc() + _studentized_code() + [f'cooks = np.nan_to_num(ri ** 2 * h / ({p} * (1 - h)))   # Cook\'s D',
                                        f'h2, h3 = 2 * {p} / len(d), 3 * {p} / len(d)   # 2p/n and 3p/n',
                                        _fig(460, 340),
                                        f'ax.scatter(h, ext, s=np.maximum(599 * cooks / max(cooks.max(), 1e-12), 6.35), color="{BASE}", alpha=0.8, edgecolors="white", linewidths=0.4)   # the area of a bubble: its Cook\'s D',
                                        f'ax.axhline(0, color="{MEAN}", linewidth=0.7)',
                                        f'ax.axhline(2, color="{MUTED}", linewidth=0.7, linestyle="--"); ax.axhline(-2, color="{MUTED}", linewidth=0.7, linestyle="--")',
                                        f'ax.axvline(h2, color="{MUTED}", linewidth=0.7, linestyle=":"); ax.axvline(h3, color="{MUTED}", linewidth=0.7, linestyle="--")',
                                        'xl, xh = min(h.min(), h3 * 1.05), max(h.max(), h3 * 1.05)',
                                        'ax.set_xlim(max(0, xl - 0.02 * (xh - xl)), xh + 0.04 * (xh - xl))',
                                        'ax.set_xlabel("Leverage (hat)")', 'ax.set_ylabel("Externally Studentized Residual")', f'ax.set_title({J(y + " influence plot")})', 'plt.show()']
    codes['influence'] = '\n'.join(c)
    # ---- the Component + Residual plots of the continuous terms
    cm_ = getattr(d, 'centered_main', {})
    ccpr = []
    for eff in d.effects:
        if any(d.alias[nm] in d.categorical for nm in eff['cols']):
            continue
        for tn in eff.get('terms', []):
            if tn not in names:
                continue
            j = names.index(tn)
            shift = float(cm_.get(tn, 0.0))
            term = _tlabel(d, tn)
            c = fitc() + [f'b = fit.params.iloc[{j}]; x = fit.model.exog[:, {j}]{" + " + repr(shift) if shift else ""}   # the column of {one_line(term)} in the design',
                          'partial = fit.resid.to_numpy() + b * fit.model.exog[:, ' + str(j) + ']   # the residual plus the term\'s part of the fit']
            ccpr.append(_row_plot(c, 'x', 'partial', n, term, 'Component + Residual', f'{term} component plus residual', 330, 270,
                                  [f'ax.plot([x.min(), x.max()], [b * (x.min() - {shift!r}), b * (x.max() - {shift!r})], color="{FIT}", linewidth=1.1)']))
    codes['ccpr'] = ccpr
    # ---- Sorted Parameter Estimates: the t ratios, by size
    est_rows = [r for r in out['estimates']['rows'] if r['term'] != 'Intercept']
    if est_rows:
        rob = m.get('rob') if m.get('rres') is not None else None
        c = fitc(['from scipy import stats'])
        if rob:
            c.append(_robust_code(rob)[0])
        src = 'rob' if rob else 'fit'
        c += [f'idx, terms = {[names.index(r["name"]) for r in est_rows]}, {J([r["term"] for r in est_rows])}   # the design\'s columns of the terms, as the report names them',
              f't, pv = np.asarray({src}.tvalues)[idx], np.asarray({src}.pvalues)[idx]',
              'o = np.argsort(-np.abs(t), kind="stable")   # the largest t first',
              f'tc = stats.t.ppf({1 - alpha / 2!r}, fit.df_resid)',
              _fig(340, max(160, min(560, 40 + 22 * len(est_rows)))),
              f'ax.barh([terms[i] for i in o], t[o], color=["{FIT}" if pv[i] < {alpha!r} else "{BAR}" for i in o])   # significant at α in red',
              'ax.invert_yaxis()', f'ax.axvline(tc, color="{MUTED}", linewidth=0.7, linestyle="--"); ax.axvline(-tc, color="{MUTED}", linewidth=0.7, linestyle="--")',
              'ax.set_xlabel("t Ratio")', 'ax.set_title("sorted t ratios")', 'plt.show()']
        codes['sorted'] = '\n'.join(c)
    # ---- LSMeans Plots: the least squares means with their intervals
    codes['lsmeans'] = {}
    for e in d.effects:
        lsm = out['lsmeans'].get(e['label'])
        if lsm is None or len(lsm['factors']) > 2 or e['spec']['nest']:
            continue
        codes['lsmeans'][e['label']] = _lsmeans_plot_code(m, e, lsm, fitc, alpha, y)
    return codes


def _lsmeans_plot_code(m, e, lsm, fitc, alpha, y):
    """An effect's LSMeans Plot: the model's prediction at each level (each
    combination), the other categorical factors averaged over their levels
    and the continuous ones at their means, with its t interval."""
    d = m['d']
    cats = [n for n in dict.fromkeys(n for e2 in d.effects for n in e2['names']) if d.alias[n] in d.categorical]
    conts = [n for n in dict.fromkeys(n for e2 in d.effects for n in e2['names']) if d.alias[n] not in d.categorical]
    others = [n for n in cats if n not in lsm['factors']]
    c = fitc(['from scipy import stats', 'import itertools', 'import patsy'])
    c.append(f'levels = {{{", ".join(f"{J(n)}: [{", ".join(_pylit(v) for v in d.levels[d.alias[n]])}]" for n in cats)}}}   # the levels, in the table\'s order')
    c.append(f'means = {{{", ".join(f"{J(n)}: d[{J(n)}].mean()" for n in conts)}}}   # the continuous factors at their means' if conts else 'means = {}')
    c.append(f'effect, others = {J(lsm["factors"])}, {J(others)}')
    c += ['rows, labels = [], []',
          'for combo in itertools.product(*[levels[f] for f in effect]):   # each level of the effect: the design rows averaged over the other factors',
          '    grid = pd.DataFrame([{**dict(zip(effect, combo)), **dict(zip(others, o)), **means} for o in itertools.product(*[levels[f] for f in others])])',
          '    rows.append(np.asarray(patsy.build_design_matrices([fit.model.data.design_info], grid)[0]).mean(axis=0)); labels.append(combo)',
          'L = np.array(rows); ls = L @ fit.params.to_numpy(); se = np.sqrt(np.einsum("ij,jk,ik->i", L, fit.cov_params().to_numpy(), L))',
          f'tc = stats.t.ppf({1 - alpha / 2!r}, fit.df_resid)']
    label = e['label']
    if len(lsm['factors']) == 2:
        f0, f1 = lsm['factors']
        c += ['transpose = False   # Transpose Factors (the red triangle): the second factor on the x axis, the first overlaid',
              'show_ci = True   # Show Confidence Limits',
              f'names = [{J([_lvl(v) for v in d.levels[d.alias[f0]]])}, {J([_lvl(v) for v in d.levels[d.alias[f1]]])}]', f'colors = {J(PALETTE)}',
              'ix, ig = (1, 0) if transpose else (0, 1)',
              _fig(420, 290),
              'for j, vg in enumerate(levels[effect[ig]]):   # a line for each level of the overlaid factor',
              '    k = [i for i, lab in enumerate(labels) if lab[ig] == vg]',
              '    ax.errorbar([names[ix][levels[effect[ix]].index(labels[i][ix])] for i in k], ls[k], yerr=tc * se[k] if show_ci else None, color=colors[j % len(colors)], marker="o", markersize=5, linewidth=1.2, capsize=3, label=names[ig][j])',
              'ax.legend(title=effect[ig], fontsize=8, frameon=False)', 'ax.set_xlabel(effect[ix])']
    else:
        c += ['show_ci = True   # Show Confidence Limits', f'names = {J(lsm["labels"])}', _fig(360, 280),
              f'ax.errorbar(names, ls, yerr=tc * se if show_ci else None, color="{BASE}", marker="o", markersize=6, linewidth=1, capsize=3)', f'ax.set_xlabel({J(label)})']
    c += [f'ax.set_ylabel({J(y + " LS Means")})', f'ax.set_title({J(label + " LS means plot")})', 'plt.show()']
    return '\n'.join(c)


def _robust_code(rob, fit='fit', name='rob'):
    """The lines that make the robust results from the fit."""
    t = rob['type']
    if t == 'HAC':
        call = f'{fit}.get_robustcov_results(cov_type="HAC", maxlags={int(rob["maxlags"])}, use_t=True)   # Newey-West, the rows in the table\'s order'
    elif t == 'cluster':
        call = (f'{fit}.get_robustcov_results(cov_type="cluster", groups=pd.factorize(d[{json.dumps(rob["cluster"])}], sort=True)[0], '
                'use_t=True)   # clusters: t tests on (clusters - 1) DF')
    else:
        call = f'{fit}.get_robustcov_results(cov_type="{t}", use_t=True)   # Robust Standard Errors'
    return [f'{name} = {call}', f'print({name}.summary())   # Parameter Estimates with the robust standard errors',
            f'print({name}.wald_test_terms(skip_single=False, scalar=True))   # Effect Tests: robust Wald F tests']


def _ls_robust_note(rob, dfi, groups):
    t = rob['type']
    what = {'HC0': 'White\'s heteroscedasticity-consistent covariance (HC0)',
            'HC1': 'the heteroscedasticity-consistent covariance HC1 (HC0 times n/(n − p), as Stata\'s robust)',
            'HC2': 'the heteroscedasticity-consistent covariance HC2 (squared residuals divided by 1 − h)',
            'HC3': 'the heteroscedasticity-consistent covariance HC3 (squared residuals divided by (1 − h)², close to the jackknife)',
            'HAC': f'Newey and West\'s heteroscedasticity- and autocorrelation-consistent covariance, Bartlett weights over {rob.get("maxlags")} lags, '
                   'the rows in the order of the table, no small-sample correction (statsmodels\' default)',
            'cluster': f'the cluster-robust covariance by {rob.get("cluster")} ({groups} clusters), with the small-sample factor '
                       'G/(G − 1)·(n − 1)/(n − p)'}[t]
    dft = f'the clusters less one ({_fmt_df(dfi)} DF)' if t == 'cluster' else f'the error degrees of freedom ({_fmt_df(dfi)})'
    return (f'Robust Standard Errors: {what}, from statsmodels\' get_robustcov_results. Parameter Estimates, Effect Tests (Wald F tests), '
            f'the Effect Summary and the profiler\'s intervals use it, with t and F tests on {dft}; Analysis of Variance, the leverage '
            'plots and the least squares means are the usual least squares ones. JMP\'s Standard Least Squares has no robust standard '
            'errors (JMP Pro 19 has a sandwich estimator in its Mixed Model and GLMM platforms).')


def _fmt_df(v):
    return str(int(v)) if float(v).is_integer() else f'{v:.4g}'


def _effect_sizes(et, res):
    """Effect sizes of the least squares Effect Tests, as optional columns
    (hidden until the reader shows them): partial eta squared SS/(SS + SSE)
    (Cohen 1973) and partial omega squared (SS - DF MSE)/(SS + (N - DF) MSE)
    (Keren and Lewis 1979; Olejnik and Algina 2003), N the observations the
    degrees of freedom count (the sum of Freq). Omega is negative when F < 1.
    JMP's Effect Tests have neither."""
    dfe = float(res.df_resid)
    if not et['rows'] or dfe <= 0:
        return
    sse, mse = float(res.ssr), float(res.mse_resid)
    nobs = dfe + float(res.model.rank)
    for r in et['rows']:
        ss, q = r.get('ss'), float(r.get('df') or 0)
        if ss is None or not np.isfinite(ss) or q <= 0:   # an effect whose columns are all zeroed (a singular design) has no test
            continue
        r['pes'] = ss / (ss + sse) if ss + sse > 0 else None
        den = ss + (nobs - q) * mse
        r['pos'] = (ss - q * mse) / den if den > 0 else None
    et['columns'] = et['columns'] + [col('pes', 'Partial η²', 'num', digits=4, hidden=True), col('pos', 'Partial ω²', 'num', digits=4, hidden=True)]
    et['n'] = nobs


def _ccpr(m):
    """Component plus residual (partial residual) plots of the continuous
    terms, as statsmodels' plot_ccpr draws them: the residual plus the
    term's part of the fit, b_j x_j, against x_j (a centred main effect
    against its column's values)."""
    d, res = m['d'], m['res']
    names = list(res.params.index)
    X = np.asarray(res.model.exog, dtype=float)
    e = np.asarray(res.resid, dtype=float)
    b = res.params.to_numpy(float)
    cm = getattr(d, 'centered_main', {})
    out = []
    for eff in d.effects:
        if any(d.alias[n] in d.categorical for n in eff['cols']):
            continue
        for tn in eff.get('terms', []):
            if tn not in names:
                continue
            j = names.index(tn)
            shift = float(cm.get(tn, 0.0))
            x = X[:, j] + shift
            comp = b[j] * X[:, j]
            lo, hi = float(np.min(x)), float(np.max(x))
            out.append({'term': _tlabel(d, tn), 'effect': eff['label'], 'x': x, 'partial': e + comp, 'estimate': float(b[j]),
                        'line': {'x': [lo, hi], 'y': [b[j] * (lo - shift), b[j] * (hi - shift)]}, 'rows': [int(i) for i in d.df.index]})
    return out


def _sequential(d, res):
    import statsmodels.api as sm
    try:
        a1 = sm.stats.anova_lm(res, typ=1)
    except Exception as e:  # e.g. a weighted fit that anova_lm cannot read
        return {'error': str(e)}
    rows = []
    for term, r in a1.iterrows():
        if term == 'Residual':
            continue
        label = next((e['label'] for e in d.effects if e.get('patsy') == term), term)
        rows.append({'source': label, 'nparm': int(r['df']), 'df': int(r['df']), 'ss': float(r['sum_sq']), 'f': float(r['F']), 'p': float(r['PR(>F)'])})
    return rtable([col('source', 'Source', 'text'), col('nparm', 'Nparm', 'int'), col('df', 'DF', 'int'), col('ss', 'Seq SS'),
                   col('f', 'F Ratio'), col('p', 'Prob > F', 'p')], rows)


def _durbin_watson(res):
    """JMP's Durbin-Watson Test: the statistic, the lag-1 autocorrelation
    of the residuals and Prob<DW, the exact p-value for positive
    autocorrelation (Imhof's method on the eigenvalues of M(A - dI)M)."""
    out = models.durbin_watson(res)
    X = np.asarray(res.model.wexog, dtype=float)
    n = X.shape[0]
    out['p'] = None
    if 3 < n <= 800:
        from scipy import integrate
        Q, _ = np.linalg.qr(X)
        M = np.eye(n) - Q @ Q.T
        D = np.diff(np.eye(n), axis=0)
        A = D.T @ D
        lam = np.linalg.eigvalsh(M @ (A - out['dw'] * np.eye(n)) @ M)
        lam = lam[np.abs(lam) > 1e-9 * np.abs(lam).max()]

        def f(u):
            if u == 0:
                return 0.5 * float(np.sum(lam))
            th = 0.5 * np.sum(np.arctan(lam * u))
            return math.sin(th) * math.exp(-0.25 * float(np.sum(np.log1p((lam * u) ** 2)))) / u
        val, _err = integrate.quad(f, 0, np.inf, limit=400)
        out['p'] = float(min(1.0, max(0.0, 0.5 - val / math.pi)))
    return out


# ---- least squares means: comparisons, letters, contrasts ------------------

def _letters(order, sig):
    """Connecting letters by insert and absorb (Piepho 2004): levels not
    sharing a letter are significantly different."""
    cols = [frozenset(order)]
    k = len(order)
    for i in range(k):
        for j in range(i + 1, k):
            a, b = order[i], order[j]
            if not sig[a][b]:
                continue
            new = []
            for c in cols:
                if a in c and b in c:
                    new += [c - {a}, c - {b}]
                else:
                    new.append(c)
            uniq = list(dict.fromkeys(new))
            cols = [c for c in uniq if c and not any(c < o for o in uniq)]
    pos = {lv: i for i, lv in enumerate(order)}
    cols.sort(key=lambda c: sorted(pos[x] for x in c))
    names = []
    for i in range(len(cols)):
        s, q = '', i
        while True:
            s = chr(65 + q % 26) + s
            q = q // 26 - 1
            if q < 0:
                break
        names.append(s)
    return {lv: [names[i] for i, c in enumerate(cols) if lv in c] for lv in order}


def _compare(lsm, method, dfe, alpha):
    est, C = np.asarray(lsm['lsmean'], dtype=float), lsm['C']
    ok = np.isfinite(est)
    idx = [i for i in range(len(est)) if ok[i]]
    k = len(idx)
    if k < 2:
        return {'error': 'fewer than two estimable least squares means'}
    if method == 'tukey':
        from scipy.stats import studentized_range
        crit = float(studentized_range.ppf(1 - alpha, k, dfe) / math.sqrt(2))
    else:
        crit = _tcrit(alpha, dfe)
    sig = {i: {} for i in idx}
    pairs = []
    for a, b in itertools.combinations(idx, 2):
        dif = est[a] - est[b]
        se = math.sqrt(max(C[a, a] + C[b, b] - 2 * C[a, b], 0.0))
        t = abs(dif) / se if se > 0 else float('inf')
        if method == 'tukey':
            from scipy.stats import studentized_range
            p = float(studentized_range.sf(t * math.sqrt(2), k, dfe)) if np.isfinite(t) else 0.0
        else:
            p = float(2 * stats.t.sf(t, dfe))
        s = p < alpha
        sig[a][b] = sig[b][a] = s
        hi, lo = (a, b) if dif >= 0 else (b, a)
        dd = abs(dif)
        pairs.append({'level': lsm['labels'][hi], 'minus': lsm['labels'][lo], 'diff': dd, 'se': se, 'lower': dd - crit * se,
                      'upper': dd + crit * se, 'p': p, 'sig': s})
    order = sorted(idx, key=lambda i: -est[i])
    let = _letters(order, sig)
    pairs.sort(key=lambda r: -r['diff'])
    return {'method': method, 'critical': crit, 'df': dfe, 'alpha': alpha, 'k': k,
            'letters': [{'level': lsm['labels'][i], 'letters': ' '.join(let[i]), 'lsmean': float(est[i]),
                         'se': float(math.sqrt(max(C[i, i], 0)))} for i in order],
            'ordered': pairs}


@api('fitmodel.compare')
def compare(table, y, effects=(), effect=None, method='tukey', rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05,
            validation=None, center=True, table_name='data'):
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, validation=validation, center=center)
    m = _ls_model(table, rows, spec)
    e = _effect_of(m['d'], effect)
    lsm = _lsmeans(m, e)
    if lsm is None:
        return {'error': f'{effect} has a continuous factor: least squares means are for categorical effects'}
    out = _compare(lsm, method, float(m['res'].df_resid), alpha)
    out['effect'] = effect
    out['code'] = _lsmeans_code(m, e, method, alpha, table, table_name, rows, weight, freq)
    return out


def _pylit(v):
    return repr(v.item() if hasattr(v, 'item') else v)


def _lsmeans_code(m, e, method, alpha, table, table_name, rows, weight, freq):
    """Runnable code for the least squares means of an effect and their
    comparisons: the design rows of each level averaged over every
    combination of the other categorical factors (the continuous ones at
    their means), as the report computes them."""
    d = m['d']
    names = list(dict.fromkeys(e['cols']))
    others = [n for n in _factor_names(d) if n not in names and d.alias[n] in d.categorical]
    conts = [n for n in _factor_names(d) if d.alias[n] not in d.categorical]
    lines = _code_frame(d, table, table_name, rows, [weight, freq], ['import itertools', 'import patsy', 'from scipy import stats', 'from scipy.stats import studentized_range'])
    wexpr = ' * '.join(f'd[{json.dumps(v)}]' for v in (weight, freq) if v)
    fit = f'smf.wls({json.dumps(_code_formula(d))}, data=d, weights={wexpr})' if wexpr else f'smf.ols({json.dumps(_code_formula(d))}, data=d)'
    lines.append(f'fit = {fit}.fit()')
    lev = '[' + ', '.join('[' + ', '.join(_pylit(v) for v in d.levels[d.alias[n]]) + ']' for n in names) + ']'
    oth = '[' + ', '.join('[' + ', '.join(_pylit(v) for v in d.levels[d.alias[n]]) + ']' for n in others) + ']'
    lines += [
        f'effect, others = {json.dumps(names)}, {json.dumps(others)}   # the effect\'s factors; the categorical factors averaged over',
        f'levels, other_levels = {lev}, {oth}',
        f'means = {{{", ".join(f"{json.dumps(n)}: d[{json.dumps(n)}].mean()" for n in conts)}}}   # continuous factors at their means',
        'cells = list(itertools.product(*levels))',
        'L = []',
        'for cell in cells:',
        '    grid = pd.DataFrame(list(itertools.product(*other_levels)) or [()], columns=others)',
        '    for name, v in zip(effect, cell): grid[name] = v',
        '    for name, v in means.items(): grid[name] = v',
        '    L.append(np.asarray(patsy.build_design_matrices([fit.model.data.design_info], grid)[0]).mean(axis=0))',
    ]
    lines += [
        'L = np.array(L); lsm = L @ fit.params.to_numpy(); C = L @ fit.cov_params().to_numpy() @ L.T',
        'k, dfe = len(cells), fit.df_resid',
        (f'crit = studentized_range.ppf(1 - {alpha!r}, k, dfe) / np.sqrt(2)   # Tukey HSD' if method == 'tukey' else f'crit = stats.t.ppf(1 - {alpha!r} / 2, dfe)   # Student\'s t'),
        'for i, j in itertools.combinations(range(k), 2):',
        '    diff = lsm[i] - lsm[j]; se = np.sqrt(C[i, i] + C[j, j] - 2 * C[i, j])',
        ('    p = studentized_range.sf(abs(diff) / se * np.sqrt(2), k, dfe)' if method == 'tukey' else '    p = 2 * stats.t.sf(abs(diff) / se, dfe)'),
        '    print(cells[i], cells[j], diff, se, diff - crit * se, diff + crit * se, p)',
    ]
    return '\n'.join(lines)


@api('fitmodel.slices')
def slices(table, y, effects=(), effect=None, rows=None, weight=None, freq=None, no_intercept=False, robust=None, alpha=0.05,
           validation=None, center=True, table_name='data'):
    """LSMeans Test Slices of an interaction of categorical factors: for each
    level of each of its factors, the F test that the least squares means of
    the cells at that level are equal (on the error degrees of freedom), and
    its Test Detail, each cell against the first. The slices are WP2's
    mixed._slices (the contrasts among an effect's cells, fit-independent)."""
    from .mixed import _slices   # here, not at the top: mixed imports this module
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, robust=robust, validation=validation, center=center)
    m = _ls_model(table, rows, spec)
    d, res = m['d'], m['res']
    R = m['rres'] if m.get('rres') is not None else res
    e = _effect_of(d, effect)
    lsm = _lsmeans(m, e)
    if lsm is None or len(lsm['factors']) < 2:
        return {'error': f'{effect} is not a crossing of categorical factors: Test Slices are for interactions'}
    b = res.params.to_numpy(float)
    V = np.asarray(R.cov_params(), dtype=float)
    dfe = _inference_df(R)
    mse = float(res.scale)
    out = []
    for sl in _slices(lsm):
        cells = sl['cells']
        if not all(lsm['estimable'][c] for c in cells):
            continue
        Lc = sl['K'] @ lsm['L']
        est = Lc @ b
        C = Lc @ V @ Lc.T
        q = int(np.linalg.matrix_rank(C))
        if q == 0:
            continue
        F = float(est @ np.linalg.pinv(C) @ est) / q
        det = []
        for r_ in range(len(Lc)):
            se = math.sqrt(max(float(C[r_, r_]), 0.0))
            t = float(est[r_]) / se if se > 0 else float('nan')
            det.append({'contrast': f'{lsm["labels"][cells[r_ + 1]]} − {lsm["labels"][cells[0]]}', 'estimate': float(est[r_]), 'se': se, 't': t,
                        'p': float(2 * stats.t.sf(abs(t), dfe)) if np.isfinite(t) else None})
        out.append({'slice': f'{sl["factor"]}={_lvl(sl["level"])}', 'factor': sl['factor'], 'dfnum': q, 'dfden': dfe, 'ss': F * q * mse, 'f': F,
                    'p': float(stats.f.sf(F, q, dfe)), 'detail': det})
    lines = _code_frame(d, table, table_name, rows, [weight, freq], ['import itertools', 'import patsy', 'from scipy import stats'])
    wexpr = ' * '.join(f'd[{json.dumps(v)}]' for v in (weight, freq) if v)
    fit = f'smf.wls({json.dumps(_code_formula(d))}, data=d, weights={wexpr})' if wexpr else f'smf.ols({json.dumps(_code_formula(d))}, data=d)'
    if freq:
        lines += [f'mod = {fit}', f'mod.df_resid = d[{json.dumps(freq)}].sum() - np.linalg.matrix_rank(mod.exog)   # Freq: JMP\'s error degrees of freedom', 'fit = mod.fit()']
    else:
        lines.append(f'fit = {fit}.fit()')
    if R is not res:
        lines += _robust_code(m['rob'])[:1]
    src = 'rob' if R is not res else 'fit'
    names = list(dict.fromkeys(e['cols']))
    others = [n for n in _factor_names(d) if n not in names and d.alias[n] in d.categorical]
    conts = [n for n in _factor_names(d) if d.alias[n] not in d.categorical]
    lev = '[' + ', '.join('[' + ', '.join(_pylit(v) for v in d.levels[d.alias[n]]) + ']' for n in names) + ']'
    oth = '[' + ', '.join('[' + ', '.join(_pylit(v) for v in d.levels[d.alias[n]]) + ']' for n in others) + ']'
    lines += [
        f'effect, others = {json.dumps(names)}, {json.dumps(others)}   # the interaction\'s factors; the categorical factors averaged over',
        f'levels, other_levels = {lev}, {oth}',
        f'means = {{{", ".join(f"{json.dumps(n)}: d[{json.dumps(n)}].mean()" for n in conts)}}}   # continuous factors at their means',
        'cells = list(itertools.product(*levels))',
        *(['cells = [c for c in cells if (d[effect].apply(tuple, axis=1) == c).any()]   # a nested effect: the cells that occur'] if e['spec']['nest'] else []),
        'L = []',
        'for cell in cells:   # each cell\'s least squares mean: its design rows averaged over the other factors\' levels',
        '    grid = pd.DataFrame(list(itertools.product(*other_levels)) or [()], columns=others)',
        '    for name, v in zip(effect, cell): grid[name] = v',
        '    for name, v in means.items(): grid[name] = v',
        '    L.append(np.asarray(patsy.build_design_matrices([fit.model.data.design_info], grid)[0]).mean(axis=0))',
        f'L = np.array(L); b, V = {src}.params.to_numpy(), np.asarray({src}.cov_params())',
        f'dfe = {dfe!r}   # the error degrees of freedom',
        'for fi, name in enumerate(effect):   # Test Slices: at each level of one factor, the cells of the others are equal',
        '    for v in levels[fi]:',
        '        at = [i for i, c in enumerate(cells) if c[fi] == v]',
        '        if len(at) < 2: continue',
        '        Lc = np.array([L[j] - L[at[0]] for j in at[1:]])   # Test Detail: each cell against the first',
        '        est, C = Lc @ b, Lc @ V @ Lc.T',
        '        q = np.linalg.matrix_rank(C); F = est @ np.linalg.pinv(C) @ est / q',
        '        print(f"{name}={v}", q, dfe, F, stats.f.sf(F, q, dfe))',
        '        for r, j in enumerate(at[1:]):',
        '            se = np.sqrt(C[r, r]); print("   ", cells[j], "-", cells[at[0]], est[r], se, est[r] / se, 2 * stats.t.sf(abs(est[r] / se), dfe))']
    return {'effect': effect, 'rows': out, 'alpha': alpha, 'code': '\n'.join(lines)}


@api('fitmodel.contrast')
def contrast(table, y, effects=(), effect=None, coefs=None, rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05,
             validation=None, center=True, table_name='data'):
    """LSMeans Contrast: each row of coefs weights the least squares means of
    the effect's levels; t tests of each contrast and the joint F test."""
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, validation=validation, center=center)
    m = _ls_model(table, rows, spec)
    res = m['res']
    e = _effect_of(m['d'], effect)
    lsm = _lsmeans(m, e)
    if lsm is None:
        return {'error': f'{effect} has a continuous factor'}
    K = np.atleast_2d(np.asarray(coefs, dtype=float))
    if K.shape[1] != len(lsm['labels']):
        return {'error': f'give one coefficient per level ({len(lsm["labels"])})'}
    Lc = K @ lsm['L']
    b = res.params.to_numpy(float)
    V = res.cov_params().to_numpy(float)
    est = Lc @ b
    cov = Lc @ V @ Lc.T
    dfe = float(res.df_resid)
    rows_out = []
    for i in range(len(K)):
        se = math.sqrt(max(cov[i, i], 0))
        t = est[i] / se if se > 0 else float('nan')
        rows_out.append({'contrast': i + 1, 'estimate': float(est[i]), 'se': se, 't': t, 'p': float(2 * stats.t.sf(abs(t), dfe)),
                         'ss': float(est[i] ** 2 / (cov[i, i] / res.scale)) if cov[i, i] > 0 else None})
    r = np.linalg.matrix_rank(cov)
    joint = None
    if r > 0:
        F = float(est @ np.linalg.pinv(cov) @ est / r)
        joint = {'ss': F * r * float(res.scale), 'numdf': int(r), 'dendf': dfe, 'f': F, 'p': float(stats.f.sf(F, r, dfe))}
    return {'effect': effect, 'labels': lsm['labels'], 'coefs': K, 'rows': rows_out, 'joint': joint}


# ---- Box-Cox -------------------------------------------------------------------

@api('fitmodel.boxcox')
def boxcox(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, lo=-2.0, hi=2.0, n=81,
           validation=None, center=True, table_name='data'):
    """JMP's Box-Cox Y Transformation: the error sum of squares of the model
    fitted to (y^lambda - 1) / (lambda * g^(lambda - 1)), g the geometric mean
    (g log y at lambda 0), over a grid of lambda; the best lambda minimises it.
    The interval holds the lambdas the likelihood ratio test does not reject."""
    from scipy import optimize
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, validation=validation, center=center)
    m = _ls_model(table, rows, spec)
    d, res = m['d'], m['res']
    yv = d.df[d.y_alias].to_numpy(float)
    if np.any(yv <= 0):
        return {'error': 'Box-Cox needs every Y value above zero'}
    X = np.asarray(res.model.exog, dtype=float)
    w = d.weights if d.weights is not None else np.ones(len(yv))
    sw = np.sqrt(w)
    ly = np.log(yv)
    gm = float(np.exp(np.average(ly, weights=w)))
    Xs = X * sw[:, None]
    pinv = np.linalg.pinv(Xs)

    def transform(lam):
        return gm * ly if abs(lam) < 1e-10 else (np.power(yv, lam) - 1) / (lam * gm ** (lam - 1))

    def sse(lam):
        z = transform(lam) * sw
        r = z - Xs @ (pinv @ z)
        return float(r @ r)
    lams = np.linspace(lo, hi, int(n))
    sses = np.array([sse(v) for v in lams])
    i = int(np.argmin(sses))
    a, b = lams[max(i - 1, 0)], lams[min(i + 1, len(lams) - 1)]
    best, sbest = float(lams[i]), float(sses[i])
    if b > a:
        r = optimize.minimize_scalar(sse, bounds=(a, b), method='bounded', options={'xatol': 1e-6})
        if r.fun <= sbest:
            best, sbest = float(r.x), float(r.fun)
    N = float(np.sum(w))
    thr = sbest * math.exp(stats.chi2.ppf(1 - alpha, 1) / N)
    ci = [None, None]
    g = lambda v: sse(v) - thr  # noqa: E731
    if g(lo) > 0:
        ci[0] = float(optimize.brentq(g, lo, best))
    if g(hi) > 0:
        ci[1] = float(optimize.brentq(g, best, hi))
    plot = _ls_fit_code(d, table, table_name, rows, weight, freq, ['from scipy import stats, optimize']) + [
        f'yv = d[{json.dumps(spec["y"][0])}].to_numpy(float); X = fit.model.exog; sw = np.sqrt(w)',
        'ly = np.log(yv); gm = np.exp(np.average(ly, weights=w))   # the geometric mean',
        'Xs = X * sw[:, None]; pinv = np.linalg.pinv(Xs)',
        'transform = lambda lam: gm * ly if abs(lam) < 1e-10 else (yv ** lam - 1) / (lam * gm ** (lam - 1))',
        'def sse(lam):   # the error sum of squares of the model fitted to the transformed Y',
        '    z = transform(lam) * sw; r = z - Xs @ (pinv @ z); return float(r @ r)',
        f'lams = np.linspace({float(lo)!r}, {float(hi)!r}, {int(n)}); sses = np.array([sse(v) for v in lams])',
        'i = int(np.argmin(sses)); best, sbest = lams[i], sses[i]',
        'a_, b_ = lams[max(i - 1, 0)], lams[min(i + 1, len(lams) - 1)]',
        'if b_ > a_:   # the best between the grid\'s neighbours',
        '    r = optimize.minimize_scalar(sse, bounds=(a_, b_), method="bounded", options={"xatol": 1e-6})',
        '    if r.fun <= sbest:', '        best, sbest = r.x, r.fun',
        f'thr = sbest * np.exp(stats.chi2.ppf({1 - alpha!r}, 1) / w.sum())   # the likelihood-ratio interval of lambda',
        'ci = [optimize.brentq(lambda v: sse(v) - thr, lams[0], best) if sse(lams[0]) > thr else None, optimize.brentq(lambda v: sse(v) - thr, best, lams[-1]) if sse(lams[-1]) > thr else None]',
        _fig(360, 260), f'ax.plot(lams, sses, color="{BASE}", linewidth=1.2)',
        f'ax.plot(best, sbest, linestyle="none", marker="o", markersize=6.5, color="{FIT}")   # the best lambda',
        'for v in ci:', '    if v is not None:', f'        ax.axvline(v, color="{MUTED}", linewidth=0.7, linestyle="--")',
        'ax.set_xlabel("λ")', 'ax.set_ylabel("SSE")', f'ax.set_title({json.dumps(spec["y"][0] + " Box-Cox")})', 'plt.show()']
    return {'lambda': lams, 'sse': sses, 'best': best, 'sse_best': sbest, 'ci': ci, 'gm': gm, 'alpha': alpha, 'plot_code': '\n'.join(plot),
            'rows': [int(v) for v in d.df.index], 'values': transform(best),
            'code': '\n'.join(_code_frame(d, table, table_name, rows, [weight, freq]) + [
                f'y = d[{json.dumps(spec["y"][0])}].to_numpy(); g = np.exp(np.log(y).mean())   # the geometric mean',
                f'X = smf.ols({json.dumps(_code_formula(d))}, data=d).exog',
                'def sse(lam):',
                '    z = g * np.log(y) if lam == 0 else (y**lam - 1) / (lam * g**(lam - 1))',
                '    return np.sum((z - X @ np.linalg.lstsq(X, z, rcond=None)[0])**2)',
                'print(min(np.linspace(-2, 2, 81), key=sse))   # the best lambda on the grid'])}


# ---------------------------------------------------------------------------
# the model of any personality, and its predictions (for the profilers)
# ---------------------------------------------------------------------------

def _model(kind, tid, rows, spec):
    if kind == 'ls':
        return _ls_model(tid, rows, spec)
    if kind == 'glm':
        return _glm_model(tid, rows, spec)
    if kind in ('logistic', 'nominal', 'ordinal'):
        return _logit_model(tid, rows, spec)
    if kind == 'mixed':
        return _mixed_model(tid, rows, spec)
    if kind == 'penreg':
        return _penreg_model(tid, rows, spec)
    if kind == 'gee':
        return _gee_model(tid, rows, spec)
    if kind == 'iv':
        return _iv_model(tid, rows, spec)
    if kind == 'qr':
        return _qr_model(tid, rows, spec)
    raise KeyError(f'no model kind {kind!r}')


def _predict(m, settings, alpha):
    kind = m['kind']
    if kind == 'ls':
        return _ls_predict(m, settings, alpha)
    if kind == 'glm':
        return _glm_predict(m, settings, alpha)
    if kind == 'logit':
        return _logit_predict(m, settings, alpha)
    if kind == 'mixed':
        return _mixed_predict(m, settings, alpha)
    if kind == 'penreg':
        return _penreg_predict(m, settings, alpha)
    if kind == 'gee':
        return _gee_predict(m, settings, alpha)
    if kind == 'iv':
        return _iv_predict(m, settings, alpha)
    if kind == 'qr':
        return _qr_predict(m, settings, alpha)
    raise KeyError(kind)


def _grid_of(f, n):
    if f['type'] == 'categorical':
        return list(range(len(f['levels'])))
    lo, hi = f['min'], f['max']
    return list(np.linspace(lo, hi, n)) if hi > lo else [lo]


def _profile_build(table, rows=None, alpha=0.05, kind='ls', ys=None, **model):
    """The Prediction Profiler's view of a fitted model (see profile.py): the
    prediction and its confidence interval at any settings of the factors.
    ys: several responses ({y, robust}), one model each with the same
    effects (the profiler of all the responses of a Standard Least Squares
    report), so that desirability can weigh them together."""
    if ys:
        specs = [_spec(**{**model, 'y': e['y'] if isinstance(e, dict) else e, 'robust': (e.get('robust') if isinstance(e, dict) else None) or model.get('robust')}) for e in ys]
    else:
        specs = [_spec(**model)]
    ms = [_model(kind, table, rows, sp) for sp in specs]
    d = ms[0]['d']
    facs = _factors(d)

    def run(settings):
        out = []
        for m in ms:
            out.extend(_predict(m, [_setting(m['d'], s) for s in settings], alpha))
        return [{'name': q['name'], 'pred': q['pred'], 'lower': q.get('lower'), 'upper': q.get('upper'), 'bounded': q.get('bounded')} for q in out]
    observed = {}
    for f in facs:
        a = d.alias[f['name']]
        observed[f['name']] = [None if v is None or (isinstance(v, float) and math.isnan(v)) else (v.item() if hasattr(v, 'item') else v) for v in d.df[a].astype(object)]
    return profile_mod.Predictor(facs, run, observed)


# fitmodel.profile (the traces), fitmodel.maximize and fitmodel.importance, as every profiled model
profile_mod.expose('fitmodel', _profile_build, alpha=True)


# ---------------------------------------------------------------------------
# Save Columns and Save Prediction Formula, for every row
# ---------------------------------------------------------------------------
# JMP saves a model's predictions for every row whose predictors are present,
# in the fit or not: excluded rows, rows missing the response, a Validation
# column's hold-out rows. Here these are the rows of the report's By group
# (every row without By); residuals are for the rows with a response too.
# The prediction formula is the fitted model in the page's formula language,
# a live column (models.formula_linear): JMP's effect coding as Match, the
# centred crossings as the model has them, the inverse link for the mean.

def _event_values(tid, name, idx, level):
    """1 where a categorical response is the event level, 0 where it is
    another level, NaN where it is missing."""
    v = data.raw(tid, name, idx)
    if data.meta(tid, name).get('dataType') == 'numeric':
        f = np.asarray(v, dtype=float)
        return np.where(np.isfinite(f), (f == float(level)).astype(float), np.nan)
    return np.array([np.nan if x is None else float(x == level) for x in v], dtype=float)


def _ls_coef(m):
    """The least squares estimates and their covariance on the design as
    fitted (a singular design's with its dependent columns zeroed)."""
    if m.get('b_zeroed') is not None:
        return m['b_zeroed'], m['V_zeroed']
    return m['res'].params.to_numpy(float), np.asarray(m['res'].cov_params(), dtype=float)


def _save_ls(m, where, alpha):
    d, res, tid, spec = m['d'], m['res'], m['tid'], m['spec']
    di = res.model.data.design_info
    idx, X, _ = models.new_rows(d, di, tid, where)
    b, V = _ls_coef(m)
    pred = X @ b
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', X, V, X), 0))
    t = _tcrit(alpha, res.df_resid)
    s2 = float(res.scale)
    w = np.ones(len(idx))
    if spec['weight']:
        wv = _col_values(tid, spec['weight'], idx)
        w = np.where(np.isfinite(wv) & (wv > 0), wv, 1.0)   # a row outside the fit: an individual of weight 1
    si = np.sqrt(se ** 2 + s2 / w)
    yv = _col_values(tid, spec['y'][0], idx)
    cols = {'predicted': pred, 'se_pred': se, 'lower_mean': pred - t * se, 'upper_mean': pred + t * se, 'se_indiv': si,
            'lower_indiv': pred - t * si, 'upper_indiv': pred + t * si, 'residual': yv - pred}
    expr = models.formula_where(tid, where, models.formula_linear(d, di, b, tid))
    return idx, cols, [{'name': f'Pred Formula {spec["y"][0]}', 'expr': expr}]


def _glm_response(m, idx):
    """A generalized linear model's response for the rows idx, on the scale
    of its mean: the value, the event's 0/1 or events over trials."""
    ys, tid = m['spec']['y'], m['tid']
    if len(ys) == 2:
        return _col_values(tid, ys[0], idx) / _col_values(tid, ys[1], idx)
    if m['info'].get('levels'):
        return _event_values(tid, ys[0], idx, m['info']['levels'][0])
    return _col_values(tid, ys[0], idx)


def _save_glm(m, where, alpha):
    d, tid, spec = m['d'], m['tid'], m['spec']
    di = m['X'].design_info
    off = spec['offset']
    idx, X, ex = models.new_rows(d, di, tid, where, extra=[off] if off else ())
    b, V, _ = _glm_params(m)
    eta = X @ b + (ex[off] if off else 0.0)
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', X, V, X), 0))
    z = float(stats.norm.ppf(1 - alpha / 2))
    inv = m['res'].family.link.inverse
    mu = inv(eta)
    lo, hi = inv(eta - z * se), inv(eta + z * se)
    cols = {'predicted': mu, 'lower_mean': np.minimum(lo, hi), 'upper_mean': np.maximum(lo, hi), 'linpred': eta, 'residual': _glm_response(m, idx) - mu}
    from .util import formula_ref
    lin = models.formula_linear(d, di, b, tid) + (f' + {formula_ref(off)}' if off else '')
    expr = models.formula_where(tid, where, models.INVERSE_LINK[m['link']].format(lin))
    return idx, cols, [{'name': f'Pred Formula {spec["y"][0]}', 'expr': expr}]


def _save_gee(m, where, alpha):
    d, tid, spec, res = m['d'], m['tid'], m['spec'], m['res']
    di = m['X'].design_info
    off = spec['offset']
    idx, X, ex = models.new_rows(d, di, tid, where, extra=[off] if off else ())
    b = res.params.to_numpy(float)
    eta = X @ b + (ex[off] if off else 0.0)
    mu = res.model.family.link.inverse(eta)
    yv = _event_values(tid, spec['y'][0], idx, m['info']['levels'][0]) if m['info'].get('levels') else _col_values(tid, spec['y'][0], idx)
    cols = {'predicted': mu, 'linpred': eta, 'residual': yv - mu}
    from .util import formula_ref
    lin = models.formula_linear(d, di, b, tid) + (f' + {formula_ref(off)}' if off else '')
    expr = models.formula_where(tid, where, models.INVERSE_LINK[m['link']].format(lin))
    return idx, cols, [{'name': f'Pred Formula {spec["y"][0]}', 'expr': expr}]


def _save_linear(m, where, b, name):
    """The rows' predictions and the formula of a linear model with the
    design m['X'] (Instrumental Variables, Quantile Regression)."""
    d, tid, spec = m['d'], m['tid'], m['spec']
    di = m['X'].design_info
    idx, X, _ = models.new_rows(d, di, tid, where)
    pred = X @ b
    cols = {'predicted': pred, 'residual': _col_values(tid, spec['y'][0], idx) - pred}
    return idx, cols, [{'name': name, 'expr': models.formula_where(tid, where, models.formula_linear(d, di, b, tid))}]


def _save_penreg(m, where, alpha):
    d, tid, spec = m['d'], m['tid'], m['spec']
    di = m['X'].design_info
    idx, X, _ = models.new_rows(d, di, tid, where)
    eta = X @ m['b']
    mu = _gr_mu(m['dist'], eta)
    yv = _event_values(tid, spec['y'][0], idx, m['info']['levels'][0]) if m['info'].get('levels') else _col_values(tid, spec['y'][0], idx)
    lin = models.formula_linear(d, di, m['b'], tid)
    inv = {'binomial': 'Squash({})', 'poisson': 'Exp({})'}.get(m['dist'], '{}')
    return idx, {'predicted': mu, 'residual': yv - mu}, [{'name': f'Pred Formula {spec["y"][0]}', 'expr': models.formula_where(tid, where, inv.format(lin))}]


def _logit_formulas(m, where):
    """Save Probability Formula (models.probability_formulas): the linear
    predictors on the design as fitted, Prob[level] and Most Likely y."""
    d, tid, spec = m['d'], m['tid'], m['spec']
    di = m['X'].design_info
    labels = [_lvl(v) for v in m['levels']]
    mode, res = m['mode'], m['res']

    def lin(b):
        return models.formula_where(tid, where, models.formula_linear(d, di, b, tid))
    if mode == 'binary':
        return models.probability_formulas('binary', labels, [lin(np.asarray(res.params, dtype=float))], spec['y'][0], target=m['target'])
    if mode == 'multinomial':
        B = np.asarray(res.params, dtype=float).reshape(len(m['names']), -1)
        return models.probability_formulas('multinomial', labels, [lin(B[:, q]) for q in range(m['k'] - 1)], spec['y'][0])
    beta, cuts = _ordinal_params(m)
    bfull = np.zeros(len(m['names']))
    bfull[m['beta_cols']] = beta
    return models.probability_formulas('ordinal', labels, [lin(bfull)], spec['y'][0], cuts=cuts, distr=m['distr'])


def _save_logit(m, where, alpha):
    d, tid = m['d'], m['tid']
    di = m['X'].design_info
    idx, X, _ = models.new_rows(d, di, tid, where)
    P, eta = _logit_probs(m, X)
    labels = [_lvl(v) for v in m['levels']]
    cols = {'prob': P, 'lin': eta, 'most_likely': [labels[i] for i in np.argmax(P, axis=1)] if len(idx) else []}
    return idx, cols, _logit_formulas(m, where)


@api('fitmodel.save')
def save(table, kind='ls', rows=None, where=None, alpha=0.05, table_name='data', **model):
    """Save Columns for every row whose predictors are present (see above),
    and the formulas of Save Prediction Formula: {rows, columns: {name:
    values}, formulas: [{name, expr}]}, expr formula text or a list of text
    and {'ref': k} (the k-th formula's column)."""
    spec = _spec(**model)
    m = _model(kind, table, rows, spec)
    k = m['kind']
    if k == 'ls':
        idx, cols, F = _save_ls(m, where, alpha)
    elif k == 'glm':
        idx, cols, F = _save_glm(m, where, alpha)
    elif k == 'logit':
        idx, cols, F = _save_logit(m, where, alpha)
        labels = [_lvl(v) for v in m['levels']]
        return {'rows': [int(i) for i in idx], 'columns': cols, 'formulas': F, 'n_fit': int(len(m['d'].df)),
                'prob': cols['prob'], 'names': [f'Prob[{lab}]' for lab in labels], 'levels': labels, 'most_likely': cols['most_likely'],
                'most_name': f'Most Likely {spec["y"][0]}', 'ordinal': m['mode'] == 'ordinal'}
    elif k == 'gee':
        idx, cols, F = _save_gee(m, where, alpha)
    elif k == 'iv':
        idx, cols, F = _save_linear(m, where, m['res'].params.to_numpy(float), f'Pred Formula {spec["y"][0]}')
    elif k == 'qr':
        idx, cols, F = _save_linear(m, where, m['res'].params.to_numpy(float), f'Pred Formula {spec["y"][0]} Quantile {_fmt_num(m["tau"])}')
    elif k == 'penreg':
        idx, cols, F = _save_penreg(m, where, alpha)
        if m['info'].get('levels'):   # binomial of a two-level Y: the Prob[] columns the Decision Threshold's formula reads
            p_ = np.asarray(cols['predicted'], dtype=float)
            return {'rows': [int(i) for i in idx], 'columns': cols, 'formulas': F, 'n_fit': int(len(m['d'].df)),
                    'prob': np.column_stack([p_, 1 - p_]), 'names': [f'Prob[{_lvl(v)}]' for v in m['info']['levels']]}
    else:
        return {'error': f'no saved predictions for {k}'}
    return {'rows': [int(i) for i in idx], 'columns': cols, 'formulas': F, 'n_fit': int(len(m['d'].df))}


@api('fitmodel.inverse')
def inverse(table, y, effects=(), factor=None, values=(), settings=None, individual=False, rows=None, weight=None, freq=None,
            no_intercept=False, robust=None, alpha=0.05, center=True, table_name='data', **_ignored):
    """Inverse Prediction (JMP's Estimates menu): the value of a continuous
    factor at which the predicted response is each given value, the other
    factors held at settings (continuous: their means unless given;
    categorical: a level, the first unless given), with Fieller's confidence
    limits: the x where (a + b x - y0)^2 = t^2 (Var a + 2 x Cov(a, b) +
    x^2 Var b), a and b the prediction at x = 0 and its slope in x;
    individual: limits for a single new response (plus sigma^2)."""
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, robust=robust, center=center)
    m = _ls_model(table, rows, spec)
    d, res = m['d'], m['res']
    R = m['rres'] if m.get('rres') is not None else res
    if factor not in d.alias or d.alias[factor] in d.categorical:
        return {'error': 'Inverse Prediction needs a continuous factor of the model'}
    a_ = d.alias[factor]
    base = _setting(d, settings or {})
    pts = [dict(base, **{a_: v}) for v in (0.0, 1.0, 2.0)]
    L = m['coder'].rows(pts)
    if np.max(np.abs(L[2] - 2 * L[1] + L[0])) > 1e-9 * max(1.0, float(np.max(np.abs(L)))):
        return {'error': f'the prediction is not a straight line in {factor} (a power of it is in the model): Inverse Prediction needs one'}
    L0, L1 = L[0], L[1] - L[0]
    b = res.params.to_numpy(float)
    V = np.asarray(R.cov_params(), dtype=float)
    a, s_ = float(L0 @ b), float(L1 @ b)
    va, cab, vb = float(L0 @ V @ L0), float(L0 @ V @ L1), float(L1 @ V @ L1)
    dfi = _inference_df(R)
    t = _tcrit(alpha, dfi)
    s2 = float(res.scale) if individual else 0.0
    out = []
    for y0 in values or ():
        try:
            y0 = float(y0)
        except (TypeError, ValueError):
            continue
        x0 = (y0 - a) / s_ if s_ != 0 else None
        A = s_ * s_ - t * t * vb
        B = 2 * ((a - y0) * s_ - t * t * cab)
        C = (a - y0) ** 2 - t * t * (va + s2)
        disc = B * B - 4 * A * C
        lo = hi = None
        if A > 0 and disc >= 0:
            r1, r2 = (-B - math.sqrt(disc)) / (2 * A), (-B + math.sqrt(disc)) / (2 * A)
            lo, hi = min(r1, r2), max(r1, r2)
        out.append({'y': y0, 'x': x0, 'lower': lo, 'upper': hi})
    held = []
    for n in _factor_names(d):
        if n == factor:
            continue
        al = d.alias[n]
        v = base.get(al)
        held.append({'factor': n, 'value': _lvl(d.levels[al][v]) if al in d.categorical else (float(d.df[al].mean()) if v is None else float(v))})
    lines = _code_frame(d, table, table_name, rows, [weight, freq], ['import patsy', 'from scipy import stats'])
    wexpr = ' * '.join(f'd[{json.dumps(v)}]' for v in (weight, freq) if v)
    fit = f'smf.wls({json.dumps(_code_formula(d))}, data=d, weights={wexpr})' if wexpr else f'smf.ols({json.dumps(_code_formula(d))}, data=d)'
    if freq:
        lines += [f'mod = {fit}', f'mod.df_resid = d[{json.dumps(freq)}].sum() - np.linalg.matrix_rank(mod.exog)', 'fit = mod.fit()']
    else:
        lines.append(f'fit = {fit}.fit()')
    if R is not res:
        lines += _robust_code(m['rob'])[:1]
    src = 'rob' if R is not res else 'fit'
    grid = {h['factor']: h['value'] for h in held}
    lines += [f'held = {json.dumps(grid)}   # the other factors, as the report holds them',
              f'pts = pd.DataFrame([{{**held, {json.dumps(factor)}: v}} for v in (0.0, 1.0)])',
              f'L = np.asarray(patsy.build_design_matrices([{src}.model.data.design_info], pts)[0])   # the design rows at {factor} = 0 and 1',
              'L0, L1 = L[0], L[1] - L[0]',
              f'b, V = np.asarray({src}.params), np.asarray({src}.cov_params())',
              'a, s = L0 @ b, L1 @ b   # the prediction at 0 and its slope',
              'va, cab, vb = L0 @ V @ L0, L0 @ V @ L1, L1 @ V @ L1',
              f't = stats.t.ppf(1 - {alpha!r} / 2, {dfi!r})',
              f's2 = {"fit.scale   # a single new response: its own variance too" if individual else "0.0   # the expected response"}',
              f'for y0 in {json.dumps([r["y"] for r in out])}:',
              '    A, B, C = s * s - t * t * vb, 2 * ((a - y0) * s - t * t * cab), (a - y0) ** 2 - t * t * (va + s2)',
              '    disc = B * B - 4 * A * C   # Fieller: (a + s x - y0)^2 = t^2 (va + 2 x cab + x^2 vb (+ s2))',
              '    lims = sorted([(-B - np.sqrt(disc)) / (2 * A), (-B + np.sqrt(disc)) / (2 * A)]) if A > 0 and disc >= 0 else None',
              '    print(y0, (y0 - a) / s, lims)']
    return {'factor': factor, 'rows': out, 'held': held, 'individual': bool(individual), 'alpha': alpha, 'code': '\n'.join(lines)}


@api('fitmodel.contour')
def contour(table, kind='ls', xfactor=None, yfactor=None, current=None, response=0, rows=None, n=36, alpha=0.05, **model):
    spec = _spec(**model)
    m = _model(kind, table, rows, spec)
    d = m['d']
    facs = {f['name']: f for f in _factors(d)}
    fx, fy = facs.get(xfactor), facs.get(yfactor)
    if not fx or not fy or fx['type'] != 'continuous' or fy['type'] != 'continuous' or xfactor == yfactor:
        return {'error': 'the Contour Profiler needs two different continuous factors'}
    cur = _setting(d, current)
    gx = np.linspace(fx['min'], fx['max'], int(n))
    gy = np.linspace(fy['min'], fy['max'], int(n))
    ax, ay = d.alias[xfactor], d.alias[yfactor]
    settings = []
    for yv in gy:
        for xv in gx:
            s = dict(cur)
            s[ax], s[ay] = float(xv), float(yv)
            settings.append(s)
    preds = _predict(m, settings, alpha)
    ri = min(max(int(response), 0), len(preds) - 1)
    z = np.asarray(preds[ri]['pred'], dtype=float).reshape(len(gy), len(gx))
    return {'x': gx, 'y': gy, 'z': z, 'response': preds[ri]['name'], 'responses': [p['name'] for p in preds],
            'points': {'x': d.df[ax].to_numpy(float), 'y': d.df[ay].to_numpy(float), 'rows': [int(i) for i in d.df.index]}}


@api('fitmodel.interaction')
def interaction(table, kind='ls', rows=None, alpha=0.05, max_factors=6, table_name='data', **model):
    """Interaction Plots: for each pair of factors, the prediction across one
    with a line for each level of the other (a continuous factor at its
    minimum and maximum); the other categorical factors averaged, the other
    continuous ones at their means."""
    spec = _spec(**model)
    m = _model(kind, table, rows, spec)
    d = m['d']
    facs = _factors(d)[:int(max_factors)]
    base = {a: AVG for a in d.categorical}
    cells = []
    for i, fr in enumerate(facs):        # the row factor: the lines
        for j, fc in enumerate(facs):    # the column factor: the horizontal axis
            if i == j:
                continue
            ar, ac = d.alias[fr['name']], d.alias[fc['name']]
            xs = _grid_of(fc, 11)
            lines = list(range(len(fr['levels']))) if fr['type'] == 'categorical' else [fr['min'], fr['max']]
            settings = []
            for lv in lines:
                for xv in xs:
                    s = dict(base)
                    s[ar], s[ac] = lv, xv
                    settings.append(s)
            p = _predict(m, settings, alpha)[0]['pred']
            k = len(xs)
            cells.append({'row': i, 'col': j, 'x': fc['labels'] if fc['type'] == 'categorical' else xs,
                          'lines': [{'label': fr['labels'][q] if fr['type'] == 'categorical' else _lvl(float(lines[q])),
                                     'y': p[q * k:(q + 1) * k]} for q in range(len(lines))]})
    response = _predict(m, [{}], alpha)[0]['name']
    return {'factors': [f['name'] for f in facs], 'types': [f['type'] for f in facs], 'cells': cells, 'response': response,
            'plot_code': _interaction_code(m, table, rows, table_name, facs, response) if len(facs) >= 2 else None}


def _interaction_code(m, table, rows, table_name, facs, response):
    """Interaction Plots as code: for each pair of factors, the prediction
    across the column factor with a line for each level of the row factor (a
    continuous one at its minimum and maximum), the other categorical factors
    averaged over their levels (their design rows averaged, as least squares
    means) and the other continuous ones at their means. The model is fitted
    as the report's code fits it, and predicted as the profilers predict it."""
    kind, d, spec = m['kind'], m['d'], m['spec']
    if kind == 'ls':
        base = _ls_fit_code(d, table, table_name, rows, spec['weight'], spec['freq'], ['import patsy'])
        di, pred = 'fit.model.data.design_info', ['    return L @ np.asarray(fit.params)   # the least squares prediction']
    elif kind == 'glm':
        base = _glm_fit_code(m, table, table_name, rows)
        di = 'Xd.design_info'
        pred = [f'    return fit.family.link.inverse(L @ np.asarray(b))   # the mean at the linear predictor{" (the offset left out, as the profilers do)" if spec["offset"] else ""}']
    elif kind == 'logit':
        base = _logit_fit_code(m, table, table_name, rows)
        di, pred = 'Xd.design_info', [f'    return probs(L)[:, 0]   # {one_line(response)}']
    elif kind == 'mixed':
        base, di, pred = _mixed_interaction_parts(m, table, table_name, rows)
    elif kind == 'gee':
        base = _gee_fit_code(m, table, table_name, rows)
        di, pred = 'X.design_info', ['    return fam.link.inverse(L @ np.asarray(fit.params))   # the marginal mean']
    elif kind == 'penreg':
        R = m['path']
        base = _gr_code(m, table, table_name, rows).split('\n')
        base = base[:next(i for i, ln in enumerate(base) if ln.startswith('e = '))]
        base = _after_frame(_with_plt(base), _positive_weights(R['O']['weight'], R['O']['freq']))
        di = f'patsy.dmatrix({J(_code_formula(d, lhs=False))}, d).design_info'
        if R['forward']:
            cc = 'cols' if R.get('crit', R['O']['criterion']) in ('kfold', 'loo') else 'steps[chosen]'
            base.append(f'bz = np.zeros(Z.shape[1]); bz[[0] + {cc}] = fit.params   # the estimates on the scaled predictors')
        else:
            base.append('bz = np.asarray(fit.params)   # the estimates on the scaled predictors')
        mu = {'binomial': f'1 / (1 + np.exp(-np.clip(e_, -{_GR_ETA}, {_GR_ETA})))', 'poisson': 'np.exp(np.minimum(e_, 700))'}.get(m['dist'], 'e_')
        pred = ['    e_ = np.column_stack([np.ones(len(L)), (L[:, 1:] - m) / sd]) @ bz   # the design rows scaled as the fit\'s',
                f'    return {mu}']
    else:
        return None
    names = [f['name'] for f in facs]
    cats = [f for f in facs if f['type'] == 'categorical']
    conts = [f['name'] for f in facs if f['type'] != 'categorical']
    others = [n for n in _factor_names(d) if n not in names]   # beyond the first six: at their means, or averaged
    k = len(facs)
    side = max(260, min(620, 140 * k))
    c = list(base) + [
        f'di = {di}   # the design of the fit (patsy): the design rows of any settings',
        f'factors = {J(names)}   # the factors, in the model\'s order' + (' (the first six)' if others else ''),
        'flevels = {' + ', '.join(f'{J(f["name"])}: [{", ".join(_pylit(v) for v in f["levels"])}]' for f in cats) + '}   # the categorical factors\' levels, in the table\'s order',
        'flabels = {' + ', '.join(f'{J(f["name"])}: {J(f["labels"])}' for f in cats) + '}   # as the page shows them']
    rest_c = [n for n in others if d.alias[n] in d.categorical]
    rest_n = [n for n in others if d.alias[n] not in d.categorical]
    if rest_c:
        c.append('flevels.update({' + ', '.join(f'{J(n)}: [{", ".join(_pylit(v) for v in d.levels[d.alias[n]])}]' for n in rest_c) + '})   # the factors beyond six, averaged')
    c += [f'fmeans = {{f: d[f].mean() for f in {J(conts + rest_n)}}}   # the continuous factors: at their means where a plot does not set them',
          'flo, fhi = {f: d[f].min() for f in fmeans}, {f: d[f].max() for f in fmeans}   # and their ranges',
          'def design(S):',
          '    """The design rows at the settings S (a frame, one setting a row): the',
          '    categorical factors S does not set averaged over their levels, the',
          '    continuous ones at their means."""',
          '    g = S.assign(at_=np.arange(len(S)))',
          '    for f, lv in flevels.items():',
          '        if f not in S:',
          '            g = g.merge(pd.DataFrame({f: lv}), how="cross")   # every level of an averaged factor',
          '    for f, v in fmeans.items():',
          '        if f not in S:',
          '            g[f] = v',
          '    for f, lv in flevels.items():',
          '        g[f] = pd.Categorical(g[f], categories=lv)',
          '    X_ = np.asarray(patsy.build_design_matrices([di], g)[0])',
          '    return pd.DataFrame(X_).groupby(g["at_"].to_numpy()).mean().to_numpy()',
          'def predict(L):', *pred,
          'lab = lambda v: str(int(v)) if float(v).is_integer() else f"{v:.6g}"   # a continuous line\'s label, as the page writes it',
          f'colors = {J(PALETTE)}',
          f'nf = len(factors); fig, axs = plt.subplots(nf, nf, figsize=({side / 100:g}, {side / 100:g}), sharey=True, layout="constrained", squeeze=False)',
          'for i, fr in enumerate(factors):   # the row factor: a line for each of its levels (a continuous one at its minimum and maximum)',
          '    for j, fc in enumerate(factors):   # the column factor: across the axis',
          '        ax = axs[i, j]',
          '        if i == j:',
          '            ax.text(0.5, 0.5, fr, ha="center", va="center", transform=ax.transAxes); ax.set_axis_off()',
          '            continue',
          '        xs = flevels[fc] if fc in flevels else (np.linspace(flo[fc], fhi[fc], 11) if fhi[fc] > flo[fc] else np.array([flo[fc]]))',
          '        lv = flevels[fr] if fr in flevels else [flo[fr], fhi[fr]]',
          '        S = pd.DataFrame({fr: np.repeat(np.asarray(lv), len(xs)), fc: np.tile(np.asarray(xs), len(lv))})',
          '        p = predict(design(S)).reshape(len(lv), len(xs))',
          '        at = np.arange(len(xs)) if fc in flevels else xs',
          '        for q in range(len(lv)):',
          '            color = colors[q % len(colors)]',
          '            ax.plot(at, p[q], color=color, linewidth=1.4, marker="o", markersize=2)',
          '            ax.annotate(flabels[fr][q] if fr in flevels else lab(lv[q]), (at[-1], p[q, -1]), xytext=(3, 0), textcoords="offset points", fontsize=7, color=color, va="center")',
          '        if fc in flevels:',
          '            ax.set_xticks(at, flabels[fc])',
          '        ax.tick_params(labelsize=7)',
          'axs[0, 1].tick_params(labelleft=True)   # the first row\'s scale, as the page shows it',
          f'fig.supylabel({J(response)}, fontsize=9)',
          'fig.suptitle("interaction plots")',
          'plt.show()']
    return '\n'.join(c)


# ---------------------------------------------------------------------------
# Stepwise
# ---------------------------------------------------------------------------

def _contains(small, big):
    """Effect small is contained in effect big (JMP's heredity): its columns,
    counted with multiplicity, are a proper part of big's."""
    from collections import Counter
    a, b = Counter(small['cols']), Counter(big['cols'])
    return a != b and all(b[k] >= v for k, v in a.items())


class _Step:
    """Least squares fits of subsets of the candidate effects, on the design
    of all of them (JMP's stepwise includes and excludes whole effects). With
    a Validation column the fits are the training rows' and each has its
    validation RSquare, 1 - SSE/SST of the validation rows about their own
    mean (predictive.measures'), for Max Validation RSquare."""
    kind = 'ls'

    def __init__(self, tid, rows, spec):
        self.full = _ls_model(tid, rows, spec)
        d, res = self.full['d'], self.full['res']
        self.d = d
        X = np.asarray(res.model.exog, dtype=float)
        y = np.asarray(res.model.endog, dtype=float)
        w = d.weights if d.weights is not None else np.ones(len(y))
        self.sw = np.sqrt(w)
        self.Xs = X * self.sw[:, None]
        self.ys = y * self.sw
        names = list(res.params.index)
        self.names = names
        self.base = [names.index('Intercept')] if 'Intercept' in names else []
        self.effs = d.effects
        self.cols = [[names.index(t) for t in e.get('terms', []) if t in names] for e in self.effs]
        ftot = _freq_total(tid, spec['freq'], d)
        self.n = float(ftot) if ftot is not None else float(len(y))
        self.sumw = float(np.sum(w))
        ybar = float(np.average(y, weights=w))
        self.sst = float(np.sum(w * (y - ybar) ** 2)) if self.base else float(np.sum(w * y * y))
        self.valid = None
        V = self.full.get('valid')
        if V:
            P = V['P']
            vrows = P.index[P.sets == 1]
            if len(vrows):
                idx, Xv, _ = models.new_rows(d, res.model.data.design_info, tid, rows=vrows)
                wv = P.weights()[np.isin(P.index, idx)]
                yv = _col_values(tid, spec['y'][0], idx)
                self.valid = {'X': Xv, 'y': yv, 'w': wv, 'sst': float(np.sum(wv * (yv - np.average(yv, weights=wv)) ** 2)), 'column': V['column']}
        self.cache = {}
        self.mse_full = float('nan')
        full = self.fit(tuple(range(len(self.effs))))
        self.mse_full = full['sse'] / full['dfe'] if full['dfe'] > 0 else float('nan')
        self.cache = {}     # the fits so far have no Cp

    def fit(self, entered):
        key = tuple(sorted(entered))
        if key in self.cache:
            return self.cache[key]
        cols = self.base + [c for i in key for c in self.cols[i]]
        if cols:
            A = self.Xs[:, cols]
            b, _res, rank, _sv = np.linalg.lstsq(A, self.ys, rcond=None)
            r = self.ys - A @ b
            sse = float(r @ r)
        else:
            b, rank, sse = np.zeros(0), 0, float(self.ys @ self.ys)
        dfe = self.n - rank
        p = int(rank)
        k = p + 1
        ll = -0.5 * self.n * (math.log(2 * math.pi * sse / self.n) + 1) if sse > 0 else float('inf')
        rsq = 1 - sse / self.sst if self.sst > 0 else None
        rsq_adj = 1 - (sse / dfe) / (self.sst / (self.n - len(self.base))) if dfe > 0 and self.sst > 0 else None
        if rsq is not None and abs(rsq) < 1e-12:
            rsq = 0.0
        if rsq_adj is not None and abs(rsq_adj) < 1e-12:
            rsq_adj = 0.0
        out = {'sse': sse, 'dfe': dfe, 'p': p, 'b': b, 'cols': cols, 'rsq': rsq, 'rsq_adj': rsq_adj,
               'rmse': math.sqrt(sse / dfe) if dfe > 0 else None,
               'cp': sse / self.mse_full - (self.n - 2 * p) if np.isfinite(self.mse_full) and self.mse_full > 0 else None,
               'aicc': -2 * ll + 2 * k + (2 * k * (k + 1) / (self.n - k - 1) if self.n - k - 1 > 0 else float('nan')),
               'bic': -2 * ll + k * math.log(self.n)}
        if self.valid is not None:
            V = self.valid
            pv = V['X'][:, cols] @ b if cols else np.zeros(len(V['y']))
            out['rsq_v'] = 1 - float(np.sum(V['w'] * (V['y'] - pv) ** 2)) / V['sst'] if V['sst'] > 0 else None
        self.cache[key] = out
        return out

    def ftest(self, small, big):
        """F test of the effects in big but not in small."""
        a, b = self.fit(small), self.fit(big)
        q = b['p'] - a['p']
        if q <= 0 or b['dfe'] <= 0:
            return {'ss': max(a['sse'] - b['sse'], 0.0), 'df': q, 'f': None, 'p': None}
        ss = max(a['sse'] - b['sse'], 0.0)
        f = (ss / q) / (b['sse'] / b['dfe']) if b['sse'] > 0 else float('inf')
        return {'ss': ss, 'df': q, 'f': f, 'p': float(stats.f.sf(f, q, b['dfe']))}

    def cov(self, entered):
        """The covariance of the least squares estimates of a subset (Model Averaging)."""
        f = self.fit(entered)
        if not f['cols']:
            return np.zeros((0, 0))
        A = self.Xs[:, f['cols']]
        s2 = f['sse'] / f['dfe'] if f['dfe'] > 0 else float('nan')
        return s2 * np.linalg.pinv(A.T @ A)


class _StepLogit:
    """Stepwise for a nominal or ordinal Y, as JMP's: the logistic fit of each
    subset of the candidate effects on the design of all of them (statsmodels'
    binomial GLM, MNLogit or OrderedModel, as the logistic personalities fit
    them), likelihood ratio tests of the effects entered or removed, AICc and
    BIC from the log-likelihood, RSquare the entropy RSquare."""
    kind = 'logit'

    def __init__(self, tid, rows, spec):
        self.full = _logit_model(tid, rows, spec)
        m = self.full
        self.d = m['d']
        names = m['names']
        self.names = names
        self.base = [names.index('Intercept')] if 'Intercept' in names else []
        self.effs = self.d.effects
        self.cols = [[names.index(t) for t in e.get('terms', []) if t in names] for e in self.effs]
        self.w = m['w'] if m['w'] is not None else np.ones(len(m['codes']))
        self.n = float(np.sum(self.w))
        self.mode, self.k = m['mode'], m['k']
        self.valid = None
        self.cache = {}
        self.llnull = self._llf(self.base)['ll']   # the model with only the intercept (the thresholds): the entropy RSquare's reference

    def _llf(self, cols):
        """The fit on the design columns cols: its log-likelihood and, binary, its estimates."""
        import statsmodels.api as sm
        m = self.full
        if self.mode == 'binary':
            e = (m['codes'] == m['target']).astype(float)
            if not cols:
                return {'ll': _binary_llf(np.full(len(e), 0.5), e, m['w']), 'b': np.zeros(0)}
            r = sm.GLM(e, m['X'].to_numpy(float)[:, cols], family=sm.families.Binomial(), freq_weights=m['w']).fit(**_IRLS)
            return {'ll': _binary_llf(np.asarray(r.fittedvalues, dtype=float), e, m['w']), 'b': np.asarray(r.params, dtype=float)}
        return {'ll': _logit_llf_reduced(m, list(cols)), 'b': None}

    def fit(self, entered):
        key = tuple(sorted(entered))
        if key in self.cache:
            return self.cache[key]
        cols = self.base + [c for i in key for c in self.cols[i]]
        f = self._llf(cols)
        ll = f['ll']
        nb = len([c for c in cols if c not in self.base])
        if self.mode == 'ordinal':
            p = nb + self.k - 1                           # the thresholds and the slopes
        elif self.mode == 'multinomial':
            p = len(cols) * (self.k - 1)
        else:
            p = len(cols)
        n = self.n
        llnull = getattr(self, 'llnull', ll)
        out = {'ll': ll, 'nll': -ll, 'p': p, 'b': f['b'], 'cols': cols, 'rsq': 1 - ll / llnull if llnull else None,
               'aicc': -2 * ll + 2 * p + (2 * p * (p + 1) / (n - p - 1) if n - p - 1 > 0 else float('nan')),
               'bic': -2 * ll + p * math.log(n)}
        self.cache[key] = out
        return out

    def ftest(self, small, big):
        """The likelihood ratio test of the effects in big but not in small."""
        a, b = self.fit(small), self.fit(big)
        q = b['p'] - a['p']
        chi = max(2 * (b['ll'] - a['ll']), 0.0)
        if q <= 0:
            return {'ss': chi, 'df': q, 'f': None, 'p': None}
        return {'ss': chi, 'df': q, 'f': chi, 'p': float(stats.chi2.sf(chi, q))}


def _stepper(tid, rows, spec):
    """The stepwise fits of the spec's model: least squares for a continuous Y,
    logistic for a nominal or ordinal one."""
    ys = spec['y']
    if ys and data.is_categorical(tid, ys[0]):
        return _StepLogit(tid, rows, spec)
    return _Step(tid, rows, spec)


def _step_moves(st, entered, locked, heredity, forward):
    """The groups of effects that could enter (forward) or leave."""
    k = len(st.effs)
    E = set(entered)
    moves = []
    for i in range(k):
        if forward and i not in E:
            group = {i}
            if heredity == 'restrict' and any(_contains(st.effs[j], st.effs[i]) and j not in E for j in range(k)):
                continue
            if heredity == 'combine':
                group |= {j for j in range(k) if j not in E and _contains(st.effs[j], st.effs[i])}
            if group & set(locked):
                continue
            moves.append(frozenset(group))
        elif not forward and i in E and i not in locked:
            group = {i}
            if heredity == 'restrict' and any(_contains(st.effs[i], st.effs[j]) and j in E for j in range(k)):
                continue
            if heredity == 'combine':
                group |= {j for j in E if _contains(st.effs[i], st.effs[j])}
            if group & set(locked):
                continue
            moves.append(frozenset(group))
    return list(dict.fromkeys(moves))


def _step_row(st, step, group, action, test, state):
    """A line of the Step History: the move, its test (least squares: the
    sequential sum of squares and the F test's p-value; logistic: the L-R
    ChiSquare and its p-value) and the model after it."""
    f = st.fit(tuple(state))
    return {'step': step, 'parameter': ' & '.join(st.effs[i]['label'] for i in sorted(group)), 'action': action,
            'p': test['p'] if test else None, 'seq_ss': test['ss'] if test else None, 'rsq': f['rsq'], 'cp': f.get('cp'),
            'p_params': f['p'], 'aicc': f['aicc'], 'bic': f['bic'], 'rsq_v': f.get('rsq_v')}


def _valid_key(f):
    """Max Validation RSquare as a key to minimise."""
    v = f.get('rsq_v')
    return -v if v is not None and np.isfinite(v) else float('inf')


def _stepwise_run(st, E, locked, rule, heredity, direction, p_enter, p_leave, single, max_steps):
    """Steps from the entered set E. With p-values: forward enters the most
    significant effect while its p-value is below p_enter, backward removes
    the least significant while above p_leave, mixed alternates (one step in,
    then out while any leaves). With AICc or BIC: forward (backward) enters
    (removes) the effect that gives the smallest criterion until none is
    left, then goes back to the model of the path with the smallest one;
    mixed makes the move in or out that lowers the criterion most while one
    does. Max Validation RSquare (a Validation column, JMP Pro's): the most
    significant effect enters (the least significant leaves) at each step,
    to the end, and the model of the path with the largest validation
    RSquare is kept; Mixed goes forward, as JMP offers Mixed with the p-value
    rule only. Returns the new set, the steps and, for a criterion, the best
    model when it is not the last."""
    E = set(E)
    steps = []
    if rule == 'max_valid' and direction == 'mixed':
        direction = 'forward'

    def moves(forward):
        best = None
        for g in _step_moves(st, E, locked, heredity, forward):
            new = (E | g) if forward else (E - g)
            test = st.ftest(tuple(E), tuple(new)) if forward else st.ftest(tuple(new), tuple(E))
            if rule in ('pvalue', 'max_valid'):
                if test['p'] is None:
                    continue
                key = test['p'] if forward else -test['p']
            else:
                key = st.fit(tuple(new))[rule]
            if key is None or not np.isfinite(key):
                continue
            if best is None or key < best[0]:
                best = (key, g, test, new)
        return best

    def apply(b, action):
        nonlocal E
        E = set(b[3])
        steps.append((b[1], action, b[2], set(E)))

    if rule == 'pvalue':
        seen = {frozenset(E)}
        for _ in range(1 if single else int(max_steps)):
            moved = False
            if direction in ('forward', 'mixed'):
                b = moves(True)
                if b and b[2]['p'] < p_enter:
                    apply(b, 'Entered')
                    moved = True
            if direction == 'backward' or (direction == 'mixed' and not (single and moved)):
                while True:
                    b = moves(False)
                    if not (b and b[2]['p'] > p_leave):
                        break
                    apply(b, 'Removed')
                    moved = True
                    if direction == 'backward' or single:
                        break
            if not moved or single:
                break
            if frozenset(E) in seen and direction == 'mixed':
                break
            seen.add(frozenset(E))
        return E, steps, None
    crit = (lambda S: _valid_key(st.fit(tuple(S)))) if rule == 'max_valid' else (lambda S: st.fit(tuple(S))[rule])  # noqa: E731
    if direction in ('forward', 'backward'):
        fwd = direction == 'forward'
        path = [(crit(E), set(E))]
        for _ in range(1 if single else int(max_steps)):
            b = moves(fwd)
            if not b:
                break
            apply(b, 'Entered' if fwd else 'Removed')
            path.append((crit(E), set(E)))
        if single:
            return E, steps, None
        bi = min(range(len(path)), key=lambda i: path[i][0])
        if path[bi][1] != E:
            E = set(path[bi][1])
            return E, steps, set(E)
        return E, steps, None
    for _ in range(1 if single else int(max_steps)):
        c0 = crit(E)
        cands = [b for b in (moves(True), moves(False)) if b]
        if not cands:
            break
        b = min(cands, key=lambda t: t[0])
        if not b[0] < c0 - 1e-10:
            break
        apply(b, 'Entered' if len(b[3]) > len(E) else 'Removed')
    return E, steps, None


@api('fitmodel.stepwise')
def stepwise(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, entered=None, locked=None, action='show',
             index=None, rule='bic', direction='forward', p_enter=0.25, p_leave=0.1, heredity='combine', step0=0, max_steps=200,
             validation=None, center=True, distr='logit', target=None, ordinal=None, table_name='data'):
    """JMP's Stepwise platform: least squares for a continuous Y, logistic
    (likelihood ratio tests) for a nominal or ordinal one. The state (the
    entered and locked effects, by their index in the list of candidates)
    lives in the page: action 'show' reports it, 'step' makes one step, 'go'
    steps until the rule stops, 'toggle' enters or removes the effect at
    index, 'enter_all' and 'remove_all' do what they say. The steps made come
    back as rows of the step history, numbered on from step0. rule: 'bic'
    (Minimum BIC, JMP's default), 'aicc', 'pvalue' (P-value Threshold) or,
    with a Validation column, 'max_valid' (Max Validation RSquare)."""
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, validation=validation, center=center,
                 distr=distr, target=target, ordinal=ordinal)
    st = _stepper(table, rows, spec)
    k = len(st.effs)
    E = set(int(i) for i in (entered or []) if 0 <= int(i) < k)
    locked = set(int(i) for i in (locked or []) if 0 <= int(i) < k)
    rule = rule if rule in ('pvalue', 'aicc', 'bic', 'max_valid') else 'bic'
    if rule == 'max_valid' and st.valid is None:
        rule = 'bic'
    direction = direction if direction in ('forward', 'backward', 'mixed') else 'forward'
    heredity = heredity if heredity in ('combine', 'restrict', 'none') else 'none'
    hist = []
    stepn = int(step0)
    if action == 'enter_all':
        E = set(range(k))
    elif action == 'remove_all':
        E = set(locked & E)
    elif action == 'toggle' and index is not None and 0 <= int(index) < k and int(index) not in locked:
        i = int(index)
        before = set(E)
        E = E - {i} if i in E else E | {i}
        test = st.ftest(tuple(before), tuple(E)) if i in E else st.ftest(tuple(E), tuple(before))
        stepn += 1
        hist.append(_step_row(st, stepn, {i}, 'Entered' if i in E else 'Removed', test, E))
    elif action in ('step', 'go'):
        if action == 'go' and direction == 'backward' and not E:
            E = set(range(k))
        E, steps, best = _stepwise_run(st, E, locked, rule, heredity, direction, float(p_enter), float(p_leave), action == 'step',
                                       max_steps)
        for g, act, test, state in steps:
            stepn += 1
            hist.append(_step_row(st, stepn, g, act, test, state))
        if best is not None:
            f = st.fit(tuple(E))
            hist.append({'step': stepn, 'parameter': 'Best', 'action': 'Best', 'p': None, 'seq_ss': None, 'rsq': f['rsq'], 'cp': f.get('cp'),
                         'p_params': f['p'], 'aicc': f['aicc'], 'bic': f['bic'], 'rsq_v': f.get('rsq_v')})
    cur = st.fit(tuple(E))
    current = []
    for i, e in enumerate(st.effs):
        est = None
        if i in E:
            test = st.ftest(tuple(E - {i}), tuple(E))
            if cur['b'] is not None and len(st.cols[i]) == 1 and st.cols[i][0] in cur['cols']:
                est = float(cur['b'][cur['cols'].index(st.cols[i][0])])
        else:
            test = st.ftest(tuple(E), tuple(E | {i}))
        current.append({'index': i, 'effect': e['label'], 'entered': i in E, 'locked': i in locked, 'estimate': est,
                        'ndf': len(st.cols[i]), 'ss': test['ss'], 'f': test['f'], 'p': test['p']})
    intercept = float(cur['b'][0]) if cur['b'] is not None and st.base and len(cur['b']) else None
    if intercept is not None:
        for t, mean in getattr(st.d, 'centered_main', {}).items():
            j = st.names.index(t) if t in st.names else None
            if j is not None and j in cur['cols']:
                intercept -= mean * float(cur['b'][cur['cols'].index(j)])
    d = st.d
    if st.kind == 'ls':
        stats_out = {k2: cur.get(k2) for k2 in ('sse', 'dfe', 'rmse', 'rsq', 'rsq_adj', 'cp', 'p', 'aicc', 'bic', 'rsq_v')}
        lines = _code_frame(d, table, table_name, rows, [weight, freq])
        lines.append(f'full = smf.ols({json.dumps(_code_formula(d))}, data=d).fit()   # every candidate effect')
        lines.append('# a step: fit the model with and without an effect (the columns of its terms) and compare them: F test, AICc or BIC')
        lines.append('# AICc = -2 log L + 2k + 2k(k + 1)/(n - k - 1), k counting the error variance; Cp = SSE/MSE(full) - (n - 2p)')
        if st.valid is not None:
            lines.append(f'# Max Validation RSquare: each fit on the training rows of {st.valid["column"]}, its RSquare on the validation rows '
                         '(1 - SSE/SST about their own mean)')
    else:
        stats_out = {'nll': cur['nll'], 'rsq': cur['rsq'], 'p': cur['p'], 'aicc': cur['aicc'], 'bic': cur['bic'], 'n': st.n}
        lines = _logit_fit_code(st.full, table, table_name, rows)
        lines = [ln for ln in lines if ln != PLT]
        lines[0] = lines[0].replace('\n' + PLT, '')
        lines.append('print(fit.llf)   # every candidate effect; a step refits without (or with) an effect\'s columns: L-R ChiSquare = 2 (llf - llf of the smaller)')
        lines.append('# AICc = -2 log L + 2k + 2k(k + 1)/(n - k - 1), k the parameters (the intercepts or thresholds too); RSquare = 1 - llf/llf(intercept only)')
    out = {'entered': sorted(E), 'locked': sorted(locked), 'history': hist, 'step': stepn, 'stats': stats_out, 'current': current,
           'intercept': intercept, 'effects': [e['label'] for e in st.effs], 'n': st.n, 'code': '\n'.join(lines), 'kind': st.kind, 'rule': rule,
           'validation': st.valid['column'] if st.valid is not None else None}
    if st.kind == 'logit':
        out['mode'] = st.mode
        out['levels'] = [_lvl(v) for v in st.full['levels']]
    return out


@api('fitmodel.all_models')
def all_models(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, max_terms=None, per_size=5,
               heredity=False, validation=None, center=True, table_name='data'):
    """All Possible Models: every subset of the effects (at most 12; up to
    max_terms effects), the best per_size of each size by R square."""
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, validation=validation, center=center)
    st = _Step(table, rows, spec)
    k = len(st.effs)
    if k > 12:
        return {'error': f'{k} effects: All Possible Models takes at most 12'}
    top = k if not max_terms else min(k, max(1, int(max_terms)))
    per = max(1, int(per_size or 1))
    out = []
    for size in range(1, top + 1):
        fits = []
        for combo in itertools.combinations(range(k), size):
            if heredity and any(_contains(st.effs[j], st.effs[i]) and j not in combo for i in combo for j in range(k)):
                continue
            f = st.fit(combo)
            fits.append((combo, f))
        fits.sort(key=lambda t: -(t[1]['rsq'] or 0))
        for rank, (combo, f) in enumerate(fits[:per]):
            out.append({'model': ','.join(st.effs[i]['label'] for i in combo), 'number': size, 'rsq': f['rsq'], 'rmse': f['rmse'],
                        'aicc': f['aicc'], 'bic': f['bic'], 'cp': f['cp'], 'best': rank == 0, 'effects': list(combo)})
    best_aicc = min((r['aicc'] for r in out if r['aicc'] is not None and np.isfinite(r['aicc'])), default=None)
    for r in out:
        r['min_aicc'] = best_aicc is not None and r['aicc'] == best_aicc
    return {'models': out, 'k': k, 'max_terms': top, 'per_size': per}


@api('fitmodel.model_average')
def model_average(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, max_terms=None, cutoff=0.95,
                  validation=None, center=True, alpha=0.05, table_name='data'):
    """Model Averaging (JMP's, in Stepwise): the least squares fits of every
    subset of the effects up to max_terms of them (at most 12 effects), each
    weighed by its AICc weight exp(-ΔAICc/2) (Burnham and Anderson 2002);
    the models of the largest weights, until their weights reach cutoff,
    are kept and their weights made to sum to one. Each term's average
    estimate is Σ w_i b_i (b_i = 0 in a model without the term), its
    standard error the unconditional Σ w_i √(var_i + (b_i − b̄)²) (their
    eq. 4.9). The intercept is at x = 0, as the reports give it."""
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, validation=validation, center=center)
    st = _Step(table, rows, spec)
    k = len(st.effs)
    if k > 12:
        return {'error': f'{k} effects: Model Averaging takes at most 12 (it fits every subset)'}
    top = k if not max_terms else min(k, max(1, int(max_terms)))
    cut = min(max(float(cutoff), 0.01), 1.0)
    fits = [()] + [c for size in range(1, top + 1) for c in itertools.combinations(range(k), size)]
    rows_m = []
    for combo in fits:
        f = st.fit(combo)
        if f['aicc'] is not None and np.isfinite(f['aicc']):
            rows_m.append((combo, f))
    amin = min(f['aicc'] for _, f in rows_m)
    wts = np.array([math.exp(-0.5 * (f['aicc'] - amin)) for _, f in rows_m])
    wts = wts / wts.sum()
    order = np.argsort(-wts, kind='stable')
    keep, tot = [], 0.0
    for i in order:
        keep.append(int(i))
        tot += float(wts[i])
        if tot >= cut - 1e-12:
            break
    wk = wts[keep] / wts[keep].sum()
    p = len(st.names)
    T = _uncenter(st.d, st.names)
    B = np.zeros((len(keep), p))
    Vd = np.zeros((len(keep), p))
    for r_, i in enumerate(keep):
        combo, f = rows_m[i]
        b = np.zeros(p)
        C = np.zeros((p, p))
        if f['cols']:
            b[f['cols']] = f['b']
            C[np.ix_(f['cols'], f['cols'])] = st.cov(combo)
        if T is not None:
            b, C = T @ b, T @ C @ T.T
        B[r_], Vd[r_] = b, np.maximum(np.diag(C), 0)
    bbar = wk @ B
    se = np.sum(wk[:, None] * np.sqrt(Vd + (B - bbar) ** 2), axis=0)
    z = float(stats.norm.ppf(1 - alpha / 2))
    est = []
    rank = {'Intercept': -1}
    for i, e in enumerate(st.effs):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    for j in sorted(range(p), key=lambda j: rank.get(st.names[j], len(st.effs))):
        inm = [bool(B[r_, j] != 0 or (st.names[j] == 'Intercept')) for r_ in range(len(keep))]
        est.append({'term': _tlabel(st.d, st.names[j]), 'estimate': float(bbar[j]), 'se': float(se[j]),
                    'lower': float(bbar[j] - z * se[j]), 'upper': float(bbar[j] + z * se[j]),
                    'weight': float(np.sum(wk[inm]))})
    models_out = [{'model': ','.join(st.effs[q]['label'] for q in rows_m[i][0]) or '(intercept only)', 'number': len(rows_m[i][0]),
                   'aicc': rows_m[i][1]['aicc'], 'weight': float(w_), 'rsq': rows_m[i][1]['rsq']} for i, w_ in zip(keep, wk)]
    d = st.d
    lines = _code_frame(d, table, table_name, rows, [weight, freq], ['import itertools'])
    lines.append(f'X = np.asarray(patsy.dmatrix({json.dumps(_code_formula(d, lhs=False))}, d)); yv = d[{json.dumps(spec["y"][0])}].to_numpy(float)   # every candidate effect: its design')
    lines[0] = lines[0].replace('import itertools', 'import itertools\nimport patsy')
    wparts = [f'd[{json.dumps(c)}].to_numpy(float)' for c in (weight, freq) if c]
    lines.append(f'w = {" * ".join(wparts)}' if wparts else 'w = np.ones(len(yv))')
    lines.append(f'N = d[{json.dumps(freq)}].sum()   # Freq: the observations' if freq else 'N = len(yv)')
    lines.append('sw = np.sqrt(w); Xs, ys = X * sw[:, None], yv * sw   # (weighted) least squares on these')
    lines.append(f'cols, base = {json.dumps(st.cols)}, {st.base}   # the design columns of each effect; the intercept')
    lines.append('fits = []')
    lines.append(f'for size in range({top + 1}):')
    lines.append(f'    for combo in itertools.combinations(range({k}), size):')
    lines.append('        c = base + [j for i in combo for j in cols[i]]')
    lines.append('        b = np.linalg.lstsq(Xs[:, c], ys, rcond=None)[0] if c else np.zeros(0); sse = np.sum((ys - Xs[:, c] @ b) ** 2) if c else ys @ ys')
    lines.append('        V = sse / (N - len(c)) * np.linalg.pinv(Xs[:, c].T @ Xs[:, c]) if c else np.zeros((0, 0))')
    lines.append('        q = len(c) + 1; ll = -0.5 * N * (np.log(2 * np.pi * sse / N) + 1)   # the error variance counted')
    lines.append('        fits.append((c, b, V, -2 * ll + 2 * q + 2 * q * (q + 1) / (N - q - 1)))   # AICc')
    lines.append('a = np.array([f_[3] for f_ in fits]); wt = np.exp(-0.5 * (a - a.min())); wt /= wt.sum()   # the AICc weights')
    lines.append(f'o = np.argsort(-wt, kind="stable"); keep = o[:np.searchsorted(np.cumsum(wt[o]), {cut!r} - 1e-12) + 1]; wk = wt[keep] / wt[keep].sum()   # the models until their weight reaches {cut:g}')
    lines.append('T = np.eye(X.shape[1])   # the intercept at x = 0 (JMP\'s), where a main effect is centred as its crossings')
    for t_, mean_ in getattr(d, 'centered_main', {}).items():
        if t_ in st.names and 'Intercept' in st.names:
            lines.append(f'T[{st.names.index("Intercept")}, {st.names.index(t_)}] = {-mean_!r}')
    lines.append('B = np.zeros((len(keep), X.shape[1])); Vd = np.zeros_like(B)')
    lines.append('for r, i in enumerate(keep):')
    lines.append('    c, b, V, _ = fits[i]; bf = np.zeros(X.shape[1]); Cf = np.zeros((X.shape[1], X.shape[1])); bf[c] = b; Cf[np.ix_(c, c)] = V')
    lines.append('    B[r], Vd[r] = T @ bf, np.diag(T @ Cf @ T.T)')
    lines.append('bbar = wk @ B; se = np.sum(wk[:, None] * np.sqrt(Vd + (B - bbar) ** 2), axis=0)   # the averages and their unconditional standard errors')
    lines.append('print(bbar, se)')
    return {'estimates': est, 'models': models_out, 'n_models': len(rows_m), 'kept': len(keep), 'cutoff': cut, 'max_terms': top,
            'alpha': alpha, 'code': '\n'.join(lines)}


# ---------------------------------------------------------------------------
# Generalized Linear Model
# ---------------------------------------------------------------------------

_LINKS = {'identity': 'Identity', 'log': 'Log', 'logit': 'Logit', 'probit': 'Probit', 'cloglog': 'CLogLog', 'reciprocal': 'InversePower',
          'inverse_squared': 'InverseSquared', 'sqrt': 'Sqrt'}
_LINK_LABEL = {'identity': 'Identity', 'log': 'Log', 'logit': 'Logit', 'probit': 'Probit', 'cloglog': 'Comp LogLog', 'reciprocal': 'Reciprocal',
               'inverse_squared': 'Inverse Square', 'sqrt': 'Square Root'}
_DEFAULT_LINK = {'normal': 'identity', 'binomial': 'logit', 'poisson': 'log', 'gamma': 'log', 'invgauss': 'log', 'negbin': 'log',
                 'tweedie': 'log'}
_DIST_LABEL = {'normal': 'Normal', 'binomial': 'Binomial', 'poisson': 'Poisson', 'gamma': 'Gamma', 'invgauss': 'Inverse Gaussian',
               'negbin': 'Negative Binomial', 'tweedie': 'Tweedie'}
_SM_FAMILY = {'normal': 'Gaussian', 'binomial': 'Binomial', 'poisson': 'Poisson', 'gamma': 'Gamma', 'invgauss': 'InverseGaussian',
              'negbin': 'NegativeBinomial', 'tweedie': 'Tweedie'}


def _family(dist, link, alpha_nb=1.0, var_power=1.5):
    import statsmodels.api as sm
    L = getattr(sm.families.links, _LINKS[link])()
    if dist == 'negbin':
        return sm.families.NegativeBinomial(link=L, alpha=alpha_nb)
    if dist == 'tweedie':
        return sm.families.Tweedie(link=L, var_power=var_power)
    return getattr(sm.families, _SM_FAMILY[dist])(link=L)


def _glm_endog(d, tid, ys, dist, target, what='the Generalized Linear Model'):
    """The response: a continuous Y, a two-level Y (the target level, the
    first by default, is the event), or events and trials (two Ys)."""
    yv = d.df[d.y_alias]
    info = {}
    if len(ys) == 2:
        if dist != 'binomial':
            raise ValueError('two Y columns (events, trials) are for the binomial distribution')
        ev = d.df[d.y_alias].to_numpy(float)
        tr = d.df[d.alias[ys[1]]].to_numpy(float)
        if np.any(tr <= 0) or np.any(ev < 0) or np.any(ev > tr):
            raise ValueError('events must lie between 0 and the number of trials, and the trials must be positive')
        info['trials'] = tr
        return np.column_stack([ev, tr - ev]), ev / tr, info
    if isinstance(yv.dtype, pd.CategoricalDtype):
        lv = [c for c in yv.cat.categories if (yv == c).any()]
        if dist != 'binomial' or len(lv) != 2:
            raise ValueError(f'{ys[0]} is categorical: {what} takes a two-level Y with the binomial distribution '
                             '(Nominal or Ordinal Logistic fits others)')
        t = _level_index(lv, target) if target is not None else 0
        info['levels'] = [lv[t], lv[1 - t]]
        e = (yv == lv[t]).to_numpy(float)
        return e, e, info
    v = yv.to_numpy(float)
    if dist == 'binomial' and (np.any(v < 0) or np.any(v > 1)):
        raise ValueError('a continuous binomial Y must be a proportion between 0 and 1 (or give events and trials as two Ys)')
    if dist in ('poisson', 'negbin', 'tweedie') and np.any(v < 0):
        raise ValueError(f'{_DIST_LABEL[dist]} needs a Y that is zero or above')
    if dist in ('gamma', 'invgauss') and np.any(v <= 0):
        raise ValueError(f'{_DIST_LABEL[dist]} needs a Y above zero')
    return v, v, info


# IRLS until the estimates settle: statsmodels' covariance comes from the
# weights of the last iteration's start, so a loose stop leaves the standard
# errors a step behind the estimates.
_IRLS = {'tol_criterion': 'params', 'atol': 1e-12, 'rtol': 1e-10, 'maxiter': 200}


def _glm_fit(endog, X, dist, link, offset, vw, fw, scale, alpha_nb=None, start=None):
    import statsmodels.api as sm
    fam = _family(dist, link, alpha_nb if alpha_nb is not None else 1.0)
    mod = sm.GLM(endog, X, family=fam, offset=offset, var_weights=vw, freq_weights=fw)
    return mod.fit(scale=scale, start_params=start, **_IRLS)


def _glm_model(tid, rows, spec):
    key = _key('glm', tid, rows, spec)
    m = models.recall(key)
    if m is not None:
        return m
    import statsmodels.api as sm
    ys = spec['y']
    if not ys:
        raise ValueError('choose a Y')
    dist = spec['dist'] or 'normal'
    link = spec['link'] or _DEFAULT_LINK[dist]
    effs = _eff_of(spec)
    rob = spec.get('robust')
    if rob and rob['type'] in ('HC1', 'HC2', 'HC3'):
        raise ValueError(f'statsmodels\' GLM gives {rob["type"]} the same as HC0: choose HC0 (the sandwich), Newey–West HAC or Cluster')
    ccol = rob['cluster'] if rob and rob['type'] == 'cluster' else None
    if ccol and ccol in ys:
        raise ValueError(f'{ccol} is the Y: cluster the standard errors by another column')
    V = _valid_sets(tid, ys, effs, rows, spec) if spec.get('validation') else None
    d = _design(tid, ys if len(ys) > 1 else ys[0], effs, V['train'] if V else rows, spec['weight'], spec['freq'], not spec['no_intercept'],
                extra=[c for c in (spec['offset'], ccol) if c], center=spec.get('center', True))
    if V and V['kfold']:
        d.kfold = (V['column'], V['kfold'])   # K folds: every row fits the model (the report says so)
        V = None
    if V:
        d.valid = V
    endog, yresp, info = _glm_endog(d, tid, ys, dist, spec['target'])
    X = _matrix(d)
    off = _col_values(tid, spec['offset'], d.df.index)
    vw = _col_values(tid, spec['weight'], d.df.index)
    fw = _col_values(tid, spec['freq'], d.df.index)
    scale = 'X2' if spec['overdispersion'] and dist in ('binomial', 'poisson') else None
    nb = nbm = None
    if dist == 'negbin':
        if vw is not None or fw is not None:
            raise ValueError('Weight and Freq are not supported with the negative binomial distribution')
        if link != 'log':
            raise ValueError('the negative binomial is fitted with the log link')
        nbm = sm.NegativeBinomial(endog, X, loglike_method='nb2', offset=off)
        nb = nbm.fit(disp=0, maxiter=500, method='bfgs')
        if not nb.mle_retvals.get('converged', True):
            nb = nbm.fit(start_params=nb.params, disp=0, maxiter=100, method='newton')
        res = _glm_fit(endog, X, dist, link, off, None, None, None, alpha_nb=float(nb.params.iloc[-1]), start=nb.params.to_numpy()[:-1])
    else:
        res = _glm_fit(endog, X, dist, link, off, vw, fw, scale)
    m = {'kind': 'glm', 'd': d, 'res': res, 'nb': nb, 'X': X, 'endog': endog, 'y': yresp, 'info': info, 'dist': dist, 'link': link,
         'offset': off, 'vw': vw, 'fw': fw, 'scale_opt': scale, 'coder': Coder(d, X.design_info), 'key': key, 'spec': spec, 'tid': tid,
         'rob': None, 'rob_V': None, 'rob_note': None, 'valid': V}
    if rob:
        _glm_robust(m, rob, nbm)
    models.remember(key, m)
    return m


def _glm_robust(m, rob, nbm):
    """Robust Standard Errors of a generalized linear model: statsmodels'
    fit(cov_type=...) from the estimates (the sandwich HC0, Newey–West HAC
    or clusters), normal-theory tests as statsmodels' GLM makes them. The
    negative binomial's covariance is the discrete NB2 model's, alpha
    included."""
    import statsmodels.api as sm
    if m['fw'] is not None:
        m['rob_note'] = ('Robust Standard Errors are not computed with a Freq column: statsmodels\' sandwich takes the frequencies as '
                         'weights of single rows, not as repeated rows. The standard errors are the model\'s.')
        return
    t = rob['type']
    if t == 'HAC':
        rob = dict(rob, maxlags=rob['maxlags'] if rob['maxlags'] is not None else _nw_lags(len(m['d'].df)))
        kw = {'maxlags': int(rob['maxlags'])}
    elif t == 'cluster':
        g = _cluster_codes(m['tid'], rob['cluster'], m['d'].df.index)
        if len(np.unique(g)) < 2:
            m['rob_note'] = f'{rob["cluster"]} has a single value in these rows: no cluster-robust standard errors.'
            return
        kw = {'groups': g}
    else:
        kw = {}
    ct = 'HAC' if t == 'HAC' else ('cluster' if t == 'cluster' else 'HC0')
    if m['nb'] is not None:
        r = nbm.fit(start_params=m['nb'].params, disp=0, maxiter=100, method='newton', cov_type=ct, cov_kwds=kw)
        m['rob_nb'] = r
        V = np.asarray(r.cov_params(), dtype=float)
        m['rob_V'] = V[:-1, :-1]
    else:
        fam = _family(m['dist'], m['link'])
        mod = sm.GLM(m['endog'], m['X'], family=fam, offset=m['offset'], var_weights=m['vw'])
        r = mod.fit(scale=m['scale_opt'], start_params=m['res'].params.to_numpy(float), cov_type=ct, cov_kwds=kw, **_IRLS)
        m['rob_res'] = r
        m['rob_V'] = np.asarray(r.cov_params(), dtype=float)
    m['rob'] = rob
    m['rob_groups'] = int(len(np.unique(kw['groups']))) if t == 'cluster' else None


def _glm_params(m):
    """The estimates and their covariance (the robust one when asked for)."""
    rv = m.get('rob_V')
    if m['nb'] is not None:
        p = m['nb'].params
        return p.to_numpy(float)[:-1], rv if rv is not None else m['nb'].cov_params().to_numpy(float)[:-1, :-1], list(p.index[:-1])
    return m['res'].params.to_numpy(float), rv if rv is not None else m['res'].cov_params().to_numpy(float), list(m['res'].params.index)


def _glm_llf(m, res=None, nb=None):
    """The log-likelihood on which the report's LR tests rest: for binomial
    and Poisson at scale one (an overdispersion estimate divides the tests
    afterwards), the negative binomial's, the normal with identity link
    concentrated over sigma; for the other scale families at the full
    model's dispersion, so a difference is a scaled deviance."""
    if m['dist'] == 'negbin':
        return float((nb if nb is not None else m['nb']).llf)
    r = res if res is not None else m['res']
    if m['dist'] in ('binomial', 'poisson'):
        return float(r.llf_scaled(scale=1.0))
    if m['dist'] == 'normal' and m['link'] == 'identity':
        return float(r.llf)
    return float(r.llf_scaled(scale=float(m['res'].scale)))


def _glm_reduced(m, keep):
    """The log-likelihood of the model with only the design columns keep."""
    import statsmodels.api as sm
    X = m['X'].to_numpy(float)
    n = X.shape[0]
    if m['dist'] == 'negbin':
        if not keep:
            # no regressors: the mean is exp(offset); only alpha is estimated
            from scipy import optimize
            mu = np.exp(m['offset']) if m['offset'] is not None else np.ones(n)
            y = m['endog']

            def nll(la):
                a = math.exp(la)
                return -float(np.sum(stats.nbinom.logpmf(y, 1 / a, 1 / (1 + a * mu))))
            return -float(optimize.minimize_scalar(nll, bounds=(-12, 6), method='bounded').fun)
        nbr = sm.NegativeBinomial(m['endog'], X[:, keep], loglike_method='nb2', offset=m['offset']).fit(disp=0, maxiter=500, method='bfgs')
        return float(nbr.llf)
    # a model without parameters: a column of zeros, whose coefficient IRLS leaves at zero
    Xr = X[:, keep] if keep else np.zeros((n, 1))
    start = np.asarray(m['res'].params, dtype=float)[keep] if keep else None
    try:
        r = _glm_fit(m['endog'], Xr, m['dist'], m['link'], m['offset'], m['vw'], m['fw'], None, start=start)
    except Exception:   # a start that is out of the link's domain
        r = _glm_fit(m['endog'], Xr, m['dist'], m['link'], m['offset'], m['vw'], m['fw'], None)
    return _glm_llf(m, res=r)


def _glm_lr(m, llf_full, llf_red):
    lr = 2 * (llf_full - llf_red)
    if m['scale_opt'] == 'X2':
        lr /= float(m['res'].scale)
    return max(lr, 0.0)


def _glm_predict(m, settings, alpha):
    L = m['coder'].rows(settings)
    b, V, _ = _glm_params(m)
    eta = L @ b
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', L, V, L), 0))
    z = float(stats.norm.ppf(1 - alpha / 2))
    inv = m['res'].family.link.inverse
    lo, hi = inv(eta - z * se), inv(eta + z * se)
    name = m['spec']['y'][0] if not m['info'].get('levels') else f'Prob[{_lvl(m["info"]["levels"][0])}]'
    return [{'name': name, 'pred': inv(eta), 'lower': np.minimum(lo, hi), 'upper': np.maximum(lo, hi), 'bounded': m['dist'] == 'binomial'}]


@api('fitmodel.glm')
def glm(table, y, effects=(), rows=None, weight=None, freq=None, offset=None, no_intercept=False, dist='normal', link=None,
        overdispersion=False, target=None, alpha=0.05, lr_params=True, robust=None, validation=None, center=True, table_name='data'):
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, offset=offset, no_intercept=no_intercept, dist=dist, link=link,
                 target=target, overdispersion=overdispersion, robust=robust, validation=validation, center=center)
    m = _glm_model(table, rows, spec)
    d, res = m['d'], m['res']
    dist, link = m['dist'], m['link']
    b, V, names = _glm_params(m)
    X = m['X'].to_numpy(float)
    p = X.shape[1]
    notes = []
    llf = _glm_llf(m)
    has_int = 'Intercept' in names
    llf0 = _glm_reduced(m, [names.index('Intercept')] if has_int else [])
    lr = _glm_lr(m, llf, llf0)
    dfm = int(np.linalg.matrix_rank(X)) - (1 if has_int else 0)
    n = float(np.sum(m['fw'])) if m['fw'] is not None else float(len(d.df))
    k = p + (1 if dist in ('normal', 'gamma', 'invgauss', 'negbin') else 0)
    aicc = -2 * llf + 2 * k + (2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else float('nan'))
    bic = -2 * llf + k * math.log(n)
    whole = [{'model': 'Difference', 'nll': lr / 2, 'lr': lr, 'df': dfm, 'p': float(stats.chi2.sf(lr, dfm)) if dfm > 0 else None},
             {'model': 'Full', 'nll': -llf, 'lr': None, 'df': None, 'p': None},
             {'model': 'Reduced', 'nll': -llf + lr / 2, 'lr': None, 'df': None, 'p': None}]
    dfr = float(res.df_resid)
    pear, dev = float(res.pearson_chi2), float(res.deviance)
    gof = [{'stat': 'Pearson', 'chisq': pear, 'df': dfr, 'p': float(stats.chi2.sf(pear, dfr)) if dfr > 0 else None},
           {'stat': 'Deviance', 'chisq': dev, 'df': dfr, 'p': float(stats.chi2.sf(dev, dfr)) if dfr > 0 else None}]
    overd = pear / dfr if dfr > 0 else None
    # effect tests: likelihood ratio (by dropping the effect's columns) and Wald
    et = []
    refit_failed = []
    for e in d.effects:
        cols = [names.index(t) for t in e.get('terms', []) if t in names]
        if not cols:
            continue
        keep = [j for j in range(p) if j not in cols]
        try:
            lr_e = _glm_lr(m, llf, _glm_reduced(m, keep))
        except Exception:   # a refit that does not converge: the Wald test stands in
            lr_e = None
            refit_failed.append(e['label'])
        Lm = np.zeros((len(cols), p))
        for i, c in enumerate(cols):
            Lm[i, c] = 1
        wb = Lm @ b
        wv = Lm @ V @ Lm.T
        wald = float(wb @ np.linalg.pinv(wv) @ wb)
        q = int(np.linalg.matrix_rank(wv))
        p_wald = float(stats.chi2.sf(wald, q)) if q else None
        et.append({'source': e['label'], 'nparm': len(cols), 'df': q, 'lr': lr_e, 'p': (float(stats.chi2.sf(lr_e, q)) if q else None) if lr_e is not None else p_wald,
                   'wald': wald, 'p_wald': p_wald})
    T = _uncenter(d, names)
    bJ, VJ = (T @ b, T @ V @ T.T) if T is not None else (b, V)
    se = np.sqrt(np.maximum(np.diag(VJ), 0))
    z = float(stats.norm.ppf(1 - alpha / 2))
    est = []
    for j, nm in enumerate(names):
        r = {'term': _tlabel(d, nm), 'estimate': float(bJ[j]), 'se': float(se[j]), 'wald': float((bJ[j] / se[j]) ** 2) if se[j] > 0 else None,
             'lower': float(bJ[j] - z * se[j]), 'upper': float(bJ[j] + z * se[j]), 'name': nm}
        r['p_wald'] = float(stats.chi2.sf(r['wald'], 1)) if r['wald'] is not None else None
        if T is not None and nm == 'Intercept':
            r['lr'], r['p'] = None, r['p_wald']   # the intercept at 0 is not a column to drop: its Wald test
        elif lr_params and p <= 40:
            keep = [i for i in range(p) if i != j]
            try:
                r['lr'] = _glm_lr(m, llf, _glm_reduced(m, keep))
                r['p'] = float(stats.chi2.sf(r['lr'], 1))
            except Exception:   # a refit that does not converge: the Wald test stands in
                r['lr'], r['p'] = None, r['p_wald']
                refit_failed.append(r['term'])
        else:
            r['lr'], r['p'] = None, r['p_wald']
        est.append(r)
    rank = {'Intercept': -1}
    for i, e in enumerate(d.effects):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    est.sort(key=lambda r: rank.get(r['name'], len(d.effects)))
    if m['nb'] is not None:
        a = m['nb'].params.iloc[-1]
        sa = (m['rob_nb'] if m.get('rob_V') is not None else m['nb']).bse.iloc[-1]
        est.append({'term': 'Dispersion (alpha)', 'estimate': float(a), 'se': float(sa), 'wald': None, 'p_wald': None, 'lr': None, 'p': None,
                    'lower': float(a - z * sa), 'upper': float(a + z * sa), 'name': 'alpha'})
    # rows
    eta = X @ b + (m['offset'] if m['offset'] is not None else 0)
    se_eta = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', X, V, X), 0))
    inv = res.family.link.inverse
    lo, hi = inv(eta - z * se_eta), inv(eta + z * se_eta)
    phi = float(res.scale)
    infl = res.get_influence()
    hat = np.asarray(infl.hat_matrix_diag, dtype=float)
    rdev = np.asarray(res.resid_deviance, dtype=float)
    rpear = np.asarray(res.resid_pearson, dtype=float)
    with np.errstate(invalid='ignore', divide='ignore'):
        sdev = rdev / np.sqrt(phi * (1 - hat))
        spear = rpear / np.sqrt(phi * (1 - hat))
    diag = {'rows': [int(i) for i in d.df.index], 'actual': m['y'], 'predicted': inv(eta), 'linpred': eta, 'resid_dev': rdev,
            'resid_pearson': rpear, 'stud_dev': sdev, 'stud_pearson': spear, 'hat': hat, 'lower_mean': np.minimum(lo, hi),
            'upper_mean': np.maximum(lo, hi), 'residual': m['y'] - inv(eta)}
    if dist in ('binomial', 'poisson') and not overdispersion and overd is not None and overd > 1.5:
        notes.append(f'Pearson χ²/DF is {overd:.3g}: the data may be overdispersed; Overdispersion Tests and Intervals scales the tests and the '
                     'intervals by it.')
    notes.append('Confidence limits are Wald limits (statsmodels); JMP gives profile-likelihood limits by default. The L-R ChiSquare of an '
                 'effect or a parameter comes from refitting the model without it.')
    if refit_failed:
        notes.append('The fit without ' + ', '.join(dict.fromkeys(refit_failed)) + ' did not converge: its line has the Wald test instead of the '
                     'likelihood ratio test.')
    if dist in ('gamma', 'invgauss') or (dist == 'normal' and link != 'identity'):
        notes.append('For this distribution the likelihood ratio tests are scaled deviance differences, at the full model\'s dispersion.')
    if offset:
        notes.append('The profilers predict at an offset of zero: per unit of exp(offset) with the log link.')
    fam = _SM_FAMILY[dist]
    lines = _code_frame(d, table, table_name, rows, [weight, freq, offset] + list(spec['y'][1:]))
    endog = f'd[{json.dumps(spec["y"][0])}]'
    if len(spec['y']) == 2:
        endog = f'np.column_stack([d[{json.dumps(spec["y"][0])}], d[{json.dumps(spec["y"][1])}] - d[{json.dumps(spec["y"][0])}]])'
    elif m['info'].get('levels'):
        endog = f'(d[{json.dumps(spec["y"][0])}] == {json.dumps(m["info"]["levels"][0] if not isinstance(m["info"]["levels"][0], (float, np.floating)) else float(m["info"]["levels"][0]))}).astype(float)'
    lines[0] = lines[0] + '\nimport patsy'
    lines.append(f'X = patsy.dmatrix({json.dumps(_code_formula(d, lhs=False))}, d)   # the design, effect coded')
    if dist == 'negbin':
        lines.append(f'fit = sm.NegativeBinomial({endog}, X{", offset=d[" + json.dumps(offset) + "]" if offset else ""}).fit()   # NB2, alpha by maximum likelihood')
    else:
        kw = []
        if offset:
            kw.append(f'offset=d[{json.dumps(offset)}]')
        if weight:
            kw.append(f'var_weights=d[{json.dumps(weight)}]')
        if freq:
            kw.append(f'freq_weights=d[{json.dumps(freq)}]')
        lines.append(f'fit = sm.GLM({endog}, X, family=sm.families.{fam}(link=sm.families.links.{_LINKS[link]}()){", " + ", ".join(kw) if kw else ""}).fit({"scale=" + repr("X2") if m["scale_opt"] else ""})')
    lines.append('print(fit.summary())')
    if dist != 'negbin':
        lines.append('print(fit.pearson_chi2, fit.deviance, fit.df_resid)   # Goodness of Fit')
    lines.append('print(fit.llf)   # the full model\'s log-likelihood; refit without an effect for its L-R test')
    rob = m.get('rob') if m.get('rob_V') is not None else None
    robust_out = None
    if m.get('rob_note'):
        notes.append(m['rob_note'])
    if rob:
        t = rob['type']
        ct = {'HAC': 'HAC', 'cluster': 'cluster'}.get(t, 'HC0')
        kw = (f', cov_kwds={{"maxlags": {int(rob["maxlags"])}}}' if t == 'HAC' else
              f', cov_kwds={{"groups": pd.factorize(d[{json.dumps(rob["cluster"])}], sort=True)[0]}}' if t == 'cluster' else '')
        if dist == 'negbin':
            lines.append(f'rob = fit.model.fit(start_params=fit.params, method="newton", cov_type="{ct}"{kw})   # Robust Standard Errors')
        else:
            sc = ', scale="X2"' if m['scale_opt'] else ''
            lines.append(f'rob = fit.model.fit(cov_type="{ct}"{kw}{sc})   # Robust Standard Errors')
        lines.append('print(rob.summary())   # the estimates with the robust standard errors, z tests')
        robust_out = {'type': t, 'label': 'Sandwich (HC0)' if t == 'HC0' else _robust_label(rob, groups=m.get('rob_groups')), 'maxlags': rob.get('maxlags'),
                      'clusters': m.get('rob_groups')}
        what = {'HC0': 'the sandwich (HC0, White\'s; the quasi-likelihood or "empirical" covariance)',
                'HAC': f'Newey and West\'s HAC covariance over {rob.get("maxlags")} lags, the rows in the order of the table',
                'cluster': f'the cluster-robust sandwich by {rob.get("cluster")} ({m.get("rob_groups")} clusters)'}[t]
        notes.append(f'Robust Standard Errors: {what}, from statsmodels\' GLM fit(cov_type=...). The standard errors, the Wald χ² tests '
                     'and intervals of the estimates and effects, and the profiler\'s intervals use it; the likelihood ratio tests assume the '
                     'model\'s variance, so the report shows the Wald tests. statsmodels\' GLM gives HC1–HC3 the same as HC0, so only HC0 is '
                     'offered here.')
    lines += _centred_code(d)
    out = {'model': {'response': ', '.join(spec['y']), 'distribution': _DIST_LABEL[dist], 'link': _LINK_LABEL.get(link, link), 'n': n,
                     'target': _lvl(m['info']['levels'][0]) if m['info'].get('levels') else None, 'converged': bool(getattr(res, 'converged', True))},
           'whole': whole, 'aicc': aicc, 'bic': bic, 'gof': gof, 'overdispersion': overd, 'scaled': m['scale_opt'] == 'X2', 'phi': phi,
           'effect_tests': et, 'estimates': est, 'diag': diag, 'factors': _factors(d), 'key': m['key'], 'notes': notes, 'alpha': alpha,
           'robust': robust_out, 'code': '\n'.join(lines)}
    notes.extend(_kfold_note(d))
    if m.get('valid'):
        out['crossvalidation'], out['holdout'] = _glm_cv(m, table, table_name, rows)
        notes.insert(0, f'{m["valid"]["column"]}: the model is fitted to the training rows (0, or Training); the validation (1) and test (2) rows '
                        'are predicted by it and measured in Crossvalidation, and marked in the plots. Every other table is the training fit\'s.')
    out['plot_code'] = _glm_plots(m, table, rows, table_name, alpha, out)
    return out


def _level_col(levels, v):
    """The position of the level v among levels (numbers compared as numbers), or None."""
    for j, lv in enumerate(levels):
        if lv == v or (isinstance(lv, (float, np.floating)) and isinstance(v, (int, float, np.integer, np.floating)) and float(lv) == float(v)):
            return j
    return None


def _glm_cv(m, table, table_name, rows):
    """A generalized linear model's Crossvalidation (a Validation column):
    every set's rows predicted from the training fit (the mean at the linear
    predictor, the offset in), measured by predictive.report; and the
    hold-out rows for the plots."""
    V, d, spec = m['valid'], m['d'], m['spec']
    P = V['P']
    off = spec['offset']
    idx, X, ex = models.new_rows(d, m['X'].design_info, table, rows=P.index, extra=[off] if off else ())
    b, _Vb, _ = _glm_params(m)
    eta = X @ b + (ex[off] if off else 0.0)
    mu = m['res'].family.link.inverse(eta)
    y = spec['y'][0]
    head = _glm_fit_code(m, table, table_name, rows) + _cv_frame_code(d, table, V, [spec['weight'], spec['freq'], off]) + [
        'Xa = np.asarray(patsy.build_design_matrices([Xd.design_info], a)[0])',
        f'pred = fit.family.link.inverse(Xa @ np.asarray(b){" + a[" + J(off) + "].to_numpy(float)" if off else ""})   # every set\'s mean, from the training fit']
    if P.kind == 'categorical':
        lv0 = m['info']['levels'][0]
        fitted = np.column_stack([mu if _level_col([lv0], lv) == 0 else 1 - mu for lv in P.levels])
        head += [f'levels = [{", ".join(_pylit(v) for v in P.levels)}]; ya = pd.Categorical(a[{J(y)}], categories=levels).codes   # the actual level',
                 f'P = np.column_stack([pred if v == {_pylit(lv0)} else 1 - pred for v in levels])   # each level\'s probability (the event {_lvl(lv0)})']
        tail = _cv_measure_code('categorical', P.levels)
    else:
        fitted = mu
        head += [f'ya = a[{J(y)}].to_numpy(float)']
        tail = _cv_measure_code('continuous')
    hold = _holdout(V, idx, mu, _glm_response(m, idx))   # the mean against the response (a two-level Y: its event, 0 or 1)
    return _cv_report(m, idx, fitted, code='\n'.join(head + tail)), hold


def _glm_fit_code(m, table, table_name, rows, imports=()):
    """The lines that fit the generalized linear model as the report does (the
    design, the response, statsmodels' GLM to the report's tolerance; the
    negative binomial's alpha from the NB2 model first), and give eta, the
    linear predictor, and pred, the fitted mean, at each row."""
    d, spec = m['d'], m['spec']
    ys, weight, freq, offset = spec['y'], spec['weight'], spec['freq'], spec['offset']
    rob = m.get('rob') if m.get('rob_V') is not None else None
    ccol = rob['cluster'] if rob and rob['type'] == 'cluster' else None
    lines = _code_frame(d, table, table_name, rows, [weight, freq, offset, ccol] + list(ys[1:]), [PLT, 'import patsy', *imports]) + _positive_weights(weight, freq)
    lines.append(f'Xd = patsy.dmatrix({J(_code_formula(d, lhs=False))}, d); X = np.asarray(Xd)   # the design, effect coded')
    if len(ys) == 2:
        lines.append(f'ev, tr = d[{J(ys[0])}].to_numpy(float), d[{J(ys[1])}].to_numpy(float)')
        lines.append('endog, actual = np.column_stack([ev, tr - ev]), ev / tr   # events and trials; the proportion')
    elif m['info'].get('levels'):
        lv0 = m['info']['levels'][0]
        lines.append(f'endog = actual = (d[{J(ys[0])}] == {_pylit(lv0)}).to_numpy(float)   # the event level, {one_line(_lvl(lv0))}')
    else:
        lines.append(f'endog = actual = d[{J(ys[0])}].to_numpy(float)')
    lines.append(f'off = d[{J(offset)}].to_numpy(float)' if offset else 'off = None')
    irls = 'tol_criterion="params", atol=1e-12, rtol=1e-10, maxiter=200'   # the report's tolerance (_IRLS)
    link = f'sm.families.links.{_LINKS[m["link"]]}()'
    if m['dist'] == 'negbin':
        lines += ['nb = sm.NegativeBinomial(endog, X, loglike_method="nb2", offset=off).fit(disp=0, maxiter=500, method="bfgs")   # NB2: alpha by maximum likelihood',
                  'if not nb.mle_retvals.get("converged", True):',
                  '    nb = nb.model.fit(start_params=nb.params, disp=0, maxiter=100, method="newton")',
                  f'fit = sm.GLM(endog, X, family=sm.families.NegativeBinomial(link={link}, alpha=nb.params[-1]), offset=off).fit(start_params=nb.params[:-1], {irls})',
                  'b, V = nb.params[:-1], nb.cov_params()[:-1, :-1]']
    else:
        kw = ['offset=off']
        if weight:
            kw.append(f'var_weights=d[{J(weight)}].to_numpy(float)')
        if freq:
            kw.append(f'freq_weights=d[{J(freq)}].to_numpy(float)')
        fam = f'sm.families.{_SM_FAMILY[m["dist"]]}(link={link})'
        if m['dist'] == 'tweedie':
            fam = f'sm.families.Tweedie(link={link}, var_power=1.5)'
        sc = 'scale="X2", ' if m['scale_opt'] else ''
        lines.append(f'fit = sm.GLM(endog, X, family={fam}, {", ".join(kw)}).fit({sc}{irls})')
        lines.append('b, V = fit.params, fit.cov_params()')
    lines.append('eta = X @ b + (off if off is not None else 0); pred = fit.family.link.inverse(eta)   # the linear predictor, the fitted mean')
    return lines


def _glm_hold_code(m, table):
    """The GLM's hold-out rows in a plot's code (after _glm_fit_code): every
    set's mean pa and response ya, and the marked points (as _hold_code)."""
    V = m.get('valid')
    if not V:
        return [], []
    spec = m['spec']
    off, y = spec['offset'], spec['y'][0]
    head = _cv_frame_code(m['d'], table, V, [spec['weight'], spec['freq'], off]) + [
        'Xa = np.asarray(patsy.build_design_matrices([Xd.design_info], a)[0])',
        f'pa = fit.family.link.inverse(Xa @ np.asarray(b){" + a[" + J(off) + "].to_numpy(float)" if off else ""})   # every set\'s mean, from the training fit']
    if m['info'].get('levels'):
        head.append(f'ya = (a[{J(y)}] == {_pylit(m["info"]["levels"][0])}).to_numpy(float)   # the event level, 0 or 1')
    else:
        head.append(f'ya = a[{J(y)}].to_numpy(float)')
    lines = ['for k, (name, marker, color) in {1: ("Validation", "^", "#d9822b"), 2: ("Test", "s", "#3a7d44")}.items():   # the hold-out rows, marked',
             '    s_ = sets == k',
             '    if s_.any():',
             '        ax.scatter(pa[s_], ya[s_], marker=marker, s=26, color=color, label=name)',
             'fig.legend(loc="outside lower center", ncols=3, fontsize=8, frameon=False)']
    return head, lines


def _glm_plots(m, table, rows, table_name, alpha, out):
    """The graphs of a Generalized Linear Model report as code: the residuals
    by predicted, actual by predicted, the linear predictor plot, the
    regression plot."""
    d = m['d']
    yl = out['model']['response']
    n = len(d.df)
    codes = {}
    resid = ['hat = fit.get_influence().hat_matrix_diag',
             'rdev, rpear = fit.resid_deviance, fit.resid_pearson']
    for key, what, expr, ylab, title in (('studDev', 'Studentized Deviance Residual', 'rdev / np.sqrt(fit.scale * (1 - hat))', 'Studentized Deviance Residual', 'studentized deviance residuals'),
                                         ('studPearson', 'Studentized Pearson Residual', 'rpear / np.sqrt(fit.scale * (1 - hat))', 'Studentized Pearson Residual', 'Studentized Pearson Residual by Predicted'),
                                         ('devPlot', 'Deviance Residual', 'rdev', 'Deviance Residual', 'Deviance Residual by Predicted'),
                                         ('pearPlot', 'Pearson Residual', 'rpear', 'Pearson Residual', 'Pearson Residual by Predicted')):
        codes[key] = _row_plot(_glm_fit_code(m, table, table_name, rows) + resid + [f'r = {expr}   # the {what.lower()}s'], 'pred', 'r', n, f'{yl} Predicted', ylab, title, zero=True)
    hh, hl = _glm_hold_code(m, table)
    ext = ('lo, hi = min(pred.min(), actual.min(), pa.min(), ya.min()), max(pred.max(), actual.max(), pa.max(), ya.max())   # the hold-out rows too' if hh
           else 'lo, hi = min(pred.min(), actual.min()), max(pred.max(), actual.max())')
    codes['actualPred'] = _row_plot(_glm_fit_code(m, table, table_name, rows) + hh + [ext], 'pred', 'actual', n,
                                    f'{yl} Predicted', f'{yl} Actual', f'{yl} actual by predicted', 400, 320, [f'ax.plot([lo, hi], [lo, hi], color="{FIT}", linewidth=1)'] + hl,
                                    label='Training' if hh else None)
    codes['linPlot'] = _row_plot(_glm_fit_code(m, table, table_name, rows) + ['o = np.argsort(eta, kind="stable")'], 'eta', 'actual', n, 'Linear Predictor', yl, 'linear predictor plot',
                                 lines=[f'ax.plot(eta[o], pred[o], color="{FIT}", linewidth=1)   # the fitted mean, the inverse link of the linear predictor'])
    # the Regression Plot: the profiler's curve over one continuous factor, at each level of a categorical one
    facs = out['factors']
    cont = [f for f in facs if f['type'] == 'continuous']
    cats = [f for f in facs if f['type'] == 'categorical']
    if len(cont) == 1 and len(cats) <= 1 and len(m['spec']['y']) == 1:
        xf, gf = cont[0], (cats[0] if cats else None)
        rob = m.get('rob') if m.get('rob_V') is not None else None
        c = _glm_fit_code(m, table, table_name, rows, ['from scipy import stats'])
        if rob:   # the profiler's interval follows Robust Standard Errors
            t = rob['type']
            ct = {'HAC': 'HAC', 'cluster': 'cluster'}.get(t, 'HC0')
            kw = (f', cov_kwds={{"maxlags": {int(rob["maxlags"])}}}' if t == 'HAC' else
                  f', cov_kwds={{"groups": pd.factorize(d[{J(rob["cluster"])}], sort=True)[0]}}' if t == 'cluster' else '')
            if m['dist'] == 'negbin':
                c.append(f'V = nb.model.fit(start_params=nb.params, disp=0, maxiter=100, method="newton", cov_type="{ct}"{kw}).cov_params()[:-1, :-1]   # Robust Standard Errors')
            else:
                c.append(f'V = fit.model.fit(start_params=fit.params, cov_type="{ct}"{kw}{", scale=" + repr("X2") if m["scale_opt"] else ""}, tol_criterion="params", atol=1e-12, rtol=1e-10, maxiter=200).cov_params()   # Robust Standard Errors')
        c.append(f'gx = np.linspace(d[{J(xf["name"])}].min(), d[{J(xf["name"])}].max(), 81)')
        c.append(f'z = stats.norm.ppf({1 - alpha / 2!r}); inv = fit.family.link.inverse')

        def curve(extra):
            return [f'L = np.asarray(patsy.build_design_matrices([Xd.design_info], pd.DataFrame({{{J(xf["name"])}: gx{extra}}}))[0])',
                    'e = L @ b; se = np.sqrt(np.einsum("ij,jk,ik->i", L, V, L))   # at an offset of zero']
        if gf is None:
            c += curve('') + ['lo_, hi_ = inv(e - z * se), inv(e + z * se)', _fig(400, 320),
                              f'ax.scatter(d[{J(xf["name"])}], actual, s={8 if n > 500 else 18}, color="{BASE}")',
                              f'ax.plot(gx, np.minimum(lo_, hi_), gx, np.maximum(lo_, hi_), color="{FIT}", linewidth=0.7, linestyle=":")   # the Wald interval, through the link',
                              f'ax.plot(gx, inv(e), color="{FIT}", linewidth=1.3)']
        else:
            c += [f'levels = [{", ".join(_pylit(v) for v in gf["levels"])}]; names = {J(gf["labels"])}   # {gf["name"]}, in the table\'s order',
                  f'colors = {J(PALETTE)}', _fig(440, 320),
                  f'ax.scatter(d[{J(xf["name"])}], actual, s={8 if n > 500 else 18}, c=[colors[levels.index(v) % len(colors)] for v in d[{J(gf["name"])}]])',
                  'for i, v in enumerate(levels):']
            c += ['    ' + ln for ln in curve(f', {J(gf["name"])}: [v] * len(gx)')]
            c += ['    ax.plot(gx, inv(e), color=colors[i % len(colors)], linewidth=1.3, label=names[i])', f'ax.legend(title={J(gf["name"])}, fontsize=8, frameon=False)']
        c += [f'ax.set_xlabel({J(xf["name"])})', f'ax.set_ylabel({J(yl)})', f'ax.set_title({J(yl + " regression plot")})', 'plt.show()']
        codes['regression'] = '\n'.join(c)
    return codes


# ---------------------------------------------------------------------------
# Nominal and Ordinal Logistic
# ---------------------------------------------------------------------------

def _expand(X, y, w):
    """Frequencies as repeated rows, for fits that take no weights."""
    if w is None:
        return X, y
    if np.any(np.abs(w - np.round(w)) > 1e-9):
        raise ValueError('weights for this fit must be whole numbers: they are used as frequencies')
    r = np.round(w).astype(int)
    return np.repeat(X, r, axis=0), np.repeat(y, r, axis=0)


def _ordered_fit(y, Xnc, distr):
    from statsmodels.miscmodels.ordinal_model import OrderedModel
    mod = OrderedModel(y, Xnc, distr=distr)
    res = mod.fit(method='bfgs', disp=0, maxiter=1000)
    if not res.mle_retvals.get('converged', True):
        res = mod.fit(start_params=res.params, method='newton', disp=0, maxiter=100)
    return res


def _logit_model(tid, rows, spec):
    key = _key('logit', tid, rows, spec)
    m = models.recall(key)
    if m is not None:
        return m
    import statsmodels.api as sm
    ys = spec['y']
    if not ys:
        raise ValueError('choose a Y')
    effs = _eff_of(spec)
    if not data.is_categorical(tid, ys[0]):
        raise ValueError(f'{ys[0]} is continuous: the logistic fits need a nominal or ordinal Y (change its modeling type, or use Standard Least Squares)')
    V = _valid_sets(tid, ys, effs, rows, spec) if spec.get('validation') else None
    d = _design(tid, ys[0], effs, V['train'] if V else rows, spec['weight'], spec['freq'], not spec['no_intercept'], center=spec.get('center', True))
    if V and V['kfold']:
        d.kfold = (V['column'], V['kfold'])   # K folds: every row fits the model (the report says so)
        V = None
    if V:
        d.valid = V
    yv = d.df[d.y_alias]
    levels = [c for c in yv.cat.categories if (yv == c).any()]
    k = len(levels)
    if k < 2:
        raise ValueError(f'{ys[0]} has only one level in these rows')
    ordinal = spec['ordinal'] if spec['ordinal'] is not None else bool(yv.cat.ordered)
    codes = pd.Categorical(yv, categories=levels).codes.astype(int)
    X = _matrix(d)
    Xa = X.to_numpy(float)
    w = d.weights
    names = list(X.columns)
    m = {'kind': 'logit', 'd': d, 'X': X, 'levels': levels, 'k': k, 'codes': codes, 'w': w, 'ordinal': ordinal, 'names': names,
         'coder': Coder(d, X.design_info), 'key': key, 'spec': spec, 'tid': tid, 'distr': spec['distr'] or 'logit', 'valid': V}
    if ordinal:
        if 'Intercept' in names:
            ic = names.index('Intercept')
            keep = [j for j in range(len(names)) if j != ic]
        else:
            keep = list(range(len(names)))
        m['beta_cols'] = keep
        Xe, ye = _expand(Xa[:, keep], codes, w)
        ycat = pd.Series(pd.Categorical.from_codes(ye, categories=[str(i) for i in range(k)], ordered=True))
        res = _ordered_fit(ycat, pd.DataFrame(Xe, columns=[names[j] for j in keep]), m['distr'])
        m['res'] = res
        m['mode'] = 'ordinal'
    elif k == 2:
        t = _level_index(levels, spec['target']) if spec['target'] is not None else 0
        m['target'] = t
        e = (codes == t).astype(float)
        res = sm.GLM(e, Xa, family=sm.families.Binomial(), freq_weights=w).fit(**_IRLS)
        m['res'] = res
        m['mode'] = 'binary'
    else:
        ysm = np.where(codes == k - 1, 0, codes + 1)
        Xe, ye = _expand(Xa, ysm, w)
        res = sm.MNLogit(ye, Xe).fit(disp=0, method='newton', maxiter=200)
        if not res.mle_retvals.get('converged', True):
            res = sm.MNLogit(ye, Xe).fit(disp=0, method='bfgs', maxiter=2000)
        m['res'] = res
        m['mode'] = 'multinomial'
    models.remember(key, m)
    return m


def _logit_probs(m, L):
    """Level probabilities (columns in the level order) at design rows L."""
    res = m['res']
    if m['mode'] == 'binary':
        eta = L @ res.params
        pt = 1 / (1 + np.exp(-eta))
        P = np.zeros((len(L), 2))
        P[:, m['target']] = pt
        P[:, 1 - m['target']] = 1 - pt
        return P, eta[:, None]
    if m['mode'] == 'multinomial':
        B = np.asarray(res.params, dtype=float)
        eta = L @ B
        ex = np.column_stack([np.zeros(len(L)), eta])
        ex = np.exp(ex - ex.max(axis=1, keepdims=True))
        Psm = ex / ex.sum(axis=1, keepdims=True)
        P = np.column_stack([Psm[:, 1:], Psm[:, :1]])
        return P, eta
    beta, cuts = _ordinal_params(m)
    xb = L[:, m['beta_cols']] @ beta
    F = stats.logistic.cdf if m['distr'] == 'logit' else stats.norm.cdf
    cum = np.column_stack([F(c + xb) for c in cuts] + [np.ones(len(L))])
    P = np.diff(np.column_stack([np.zeros(len(L)), cum]), axis=1)
    return P, xb[:, None]


def _logit_unstable(m):
    """models.unstable_params of a logistic fit, in the fit's own parameter
    vector: the binomial GLM's, MNLogit's (column by column, as its
    covariance) or OrderedModel's (the coefficients, then the thresholds)."""
    res, mode = m['res'], m['mode']
    try:
        C = np.asarray(res.cov_params(), dtype=float)
        rms = np.sqrt(np.mean(m['X'].to_numpy(float) ** 2, axis=0))   # each parameter's scale on the linear predictor
        if mode == 'multinomial':
            B = np.asarray(res.params, dtype=float)
            return models.unstable_params(lambda v: res.model.loglike(np.asarray(v).reshape(B.shape, order='F')), B.ravel(order='F'), C,
                                          scales=np.tile(rms, B.shape[1]))
        if mode == 'binary':
            # the binomial log-likelihood by log-sigmoids, finite where separation makes the probabilities 0 and 1
            X = m['X'].to_numpy(float)
            e = (m['codes'] == m['target']).astype(float)
            w = np.ones(len(e)) if m['w'] is None else np.asarray(m['w'], dtype=float)

            def ll(v):
                eta = X @ np.asarray(v, dtype=float)
                return float(-np.sum(w * (e * np.logaddexp(0.0, -eta) + (1 - e) * np.logaddexp(0.0, eta))))
            return models.unstable_params(ll, np.asarray(res.params, dtype=float), C, scales=rms)
        nb_ = len(m['beta_cols'])
        return models.unstable_params(lambda v: res.model.loglike(np.asarray(v)), np.asarray(res.params, dtype=float), C,
                                      scales=np.r_[rms[m['beta_cols']], np.ones(len(res.params) - nb_)])
    except Exception:   # no covariance: nothing to judge by
        return None


def _ordinal_params(m):
    """JMP's parameterisation of the cumulative model, P(Y <= j) = F(a_j + x'b):
    a_j the thresholds of statsmodels' OrderedModel and b minus its
    coefficients (statsmodels writes F(t_j - x'b))."""
    res = m['res']
    nb = len(m['beta_cols'])
    params = np.asarray(res.params, dtype=float)
    beta = -params[:nb]
    cuts = res.model.transform_threshold_params(params)[1:-1]
    return beta, cuts


def _ordinal_cov(m):
    """Covariance of (thresholds, JMP's b) by the delta method."""
    res = m['res']
    nb = len(m['beta_cols'])
    params = np.asarray(res.params, dtype=float)
    C = np.asarray(res.cov_params(), dtype=float)
    kk = len(params) - nb
    J = np.zeros((kk + nb, len(params)))
    for j in range(kk):
        J[j, nb] = 1.0
        for i in range(1, j + 1):
            J[j, nb + i] = math.exp(params[nb + i])
    for i in range(nb):
        J[kk + i, i] = -1.0
    return J @ C @ J.T


def _binary_llf(mu, e, w):
    """The binomial log-likelihood with 0 log 0 = 0, so that a perfectly
    separated fit has its limit (statsmodels gives nan there)."""
    from scipy.special import xlogy
    w = np.ones(len(e)) if w is None else w
    return float(np.sum(w * (xlogy(e, mu) + xlogy(1 - e, 1 - mu))))


def _ordinal_uncenter(m, kk):
    """JMP's thresholds at x = 0 for main effects centred by
    _center_main_effects: a_j - mean * b (JMP's signs), on (thresholds, b)."""
    d = m['d']
    cm = getattr(d, 'centered_main', None)
    if not cm:
        return None
    nb = len(m['beta_cols'])
    T = np.eye(kk + nb)
    for t, mean in cm.items():
        if t in m['names'] and m['names'].index(t) in m['beta_cols']:
            i = m['beta_cols'].index(m['names'].index(t))
            T[:kk, kk + i] = -mean
    return T


def _logit_llf_reduced(m, keep):
    import statsmodels.api as sm
    Xa = m['X'].to_numpy(float)
    if m['mode'] == 'binary':
        e = (m['codes'] == m['target']).astype(float)
        Xr = Xa[:, keep] if keep else None
        if Xr is None:
            w = m['w'] if m['w'] is not None else np.ones(len(e))
            p = 0.5
            return float(np.sum(w * (e * math.log(p) + (1 - e) * math.log(1 - p))))
        r = sm.GLM(e, Xr, family=sm.families.Binomial(), freq_weights=m['w']).fit(**_IRLS)
        return _binary_llf(np.asarray(r.fittedvalues, dtype=float), e, m['w'])
    if m['mode'] == 'multinomial':
        k = m['k']
        ysm = np.where(m['codes'] == k - 1, 0, m['codes'] + 1)
        if not keep:
            w = m['w'] if m['w'] is not None else np.ones(len(ysm))
            return float(np.sum(w) * math.log(1.0 / k))
        Xe, ye = _expand(Xa[:, keep], ysm, m['w'])
        return float(sm.MNLogit(ye, Xe).fit(disp=0, method='newton', maxiter=200).llf)
    bcols = [j for j in keep if j in m['beta_cols']]
    if not bcols:
        return float(m['res'].llnull)
    Xe, ye = _expand(Xa[:, bcols], m['codes'], m['w'])
    ycat = pd.Series(pd.Categorical.from_codes(ye, categories=[str(i) for i in range(m['k'])], ordered=True))
    return float(_ordered_fit(ycat, pd.DataFrame(Xe), m['distr']).llf)


def _logit_predict(m, settings, alpha):
    L = m['coder'].rows(settings)
    P, _eta = _logit_probs(m, L)
    out = []
    for j, lv in enumerate(m['levels']):
        out.append({'name': f'Prob[{_lvl(lv)}]', 'pred': P[:, j], 'lower': None, 'upper': None, 'bounded': True})
    if m['mode'] == 'binary':
        res = m['res']
        eta = L @ res.params
        se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', L, res.cov_params(), L), 0))
        z = float(stats.norm.ppf(1 - alpha / 2))
        lo, hi = 1 / (1 + np.exp(-(eta - z * se))), 1 / (1 + np.exp(-(eta + z * se)))
        t = m['target']
        out[t]['lower'], out[t]['upper'] = lo, hi
        out[1 - t]['lower'], out[1 - t]['upper'] = 1 - hi, 1 - lo
    return out


def _roc(score, event, w):
    order = np.argsort(-score, kind='stable')
    s, e, ww = score[order], event[order], w[order]
    tp = np.cumsum(ww * e)
    fp = np.cumsum(ww * (1 - e))
    last = np.r_[np.diff(s) != 0, True]
    P, N = tp[-1], fp[-1]
    if P <= 0 or N <= 0:
        return None
    tpr = np.r_[0, tp[last] / P]
    fpr = np.r_[0, fp[last] / N]
    auc = float(np.trapezoid(tpr, fpr)) if hasattr(np, 'trapezoid') else float(np.trapz(tpr, fpr))
    return {'fpr': fpr, 'tpr': tpr, 'auc': auc}


@api('fitmodel.logistic')
def logistic(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, ordinal=None, distr='logit', target=None,
             alpha=0.05, validation=None, center=True, table_name='data'):
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, ordinal=ordinal, distr=distr, target=target,
                 validation=validation, center=center)
    m = _logit_model(table, rows, spec)
    d, res, k, levels = m['d'], m['res'], m['k'], m['levels']
    Xa = m['X'].to_numpy(float)
    names = m['names']
    p = Xa.shape[1]
    w = m['w'] if m['w'] is not None else np.ones(len(m['codes']))
    N = float(np.sum(w))
    mode = m['mode']
    if mode == 'binary':
        e = (m['codes'] == m['target']).astype(float)
        llf = _binary_llf(np.asarray(res.fittedvalues, dtype=float), e, m['w'])
        pbar = float(np.average(e, weights=w))
        llnull = _binary_llf(np.full(len(e), pbar), e, m['w'])
    else:
        llf, llnull = float(res.llf), float(res.llnull)
    z = float(stats.norm.ppf(1 - alpha / 2))
    notes = []
    ylab = [_lvl(v) for v in levels]
    # parameter estimates, per logit
    est = []
    if mode == 'ordinal':
        beta, cuts = _ordinal_params(m)
        C = _ordinal_cov(m)
        kk = len(cuts)
        vals = np.r_[cuts, beta]
        To = _ordinal_uncenter(m, kk)
        if To is not None:
            vals, C = To @ vals, To @ C @ To.T
        vals = list(vals)
        labs = [f'Intercept[{ylab[j]}]' for j in range(kk)] + [_tlabel(d, names[j]) for j in m['beta_cols']]
        rank = {}
        for i, e in enumerate(d.effects):
            for c in e.get('terms', []):
                rank.setdefault(c, i)
        order = list(range(kk)) + sorted(range(kk, len(vals)), key=lambda i: rank.get(names[m['beta_cols'][i - kk]], len(d.effects)))
        # Unstable (JMP's mark): OrderedModel's vector is the coefficients, then the first threshold and the log increments
        un = _logit_unstable(m)
        nb_ = len(m['beta_cols'])
        un_row = ([bool(un[nb_:nb_ + j + 1].any()) for j in range(kk)] + [bool(un[i]) for i in range(nb_)]) if un is not None else [False] * len(vals)
        for i in order:
            v, lab = vals[i], labs[i]
            se = math.sqrt(max(C[i, i], 0))
            chi = (v / se) ** 2 if se > 0 else None
            est.append({'logit': '', 'term': lab, 'estimate': float(v), 'se': se, 'chisq': chi, 'p': float(stats.chi2.sf(chi, 1)) if chi is not None else None,
                        'lower': float(v - z * se), 'upper': float(v + z * se), 'unstable': 'Unstable' if un_row[i] else ''})
        footer = 'For the cumulative log odds P(Y ≤ level)/P(Y > level); positive coefficients make lower levels more likely.' if m['distr'] == 'logit' else 'Cumulative probit: P(Y ≤ level) = Φ(intercept + x′b).'
    else:
        B = np.asarray(res.params, dtype=float).reshape(p, -1).copy()
        S = np.asarray(res.bse, dtype=float).reshape(p, -1).copy()
        T = _uncenter(d, names)
        if T is not None:
            Cf = np.asarray(res.cov_params(), dtype=float)
            for q in range(B.shape[1]):
                Cq = Cf if mode == 'binary' else Cf[q * p:(q + 1) * p, q * p:(q + 1) * p]
                B[:, q] = T @ B[:, q]
                S[:, q] = np.sqrt(np.maximum(np.diag(T @ Cq @ T.T), 0))
        logits = [f'{ylab[m["target"]]}/{ylab[1 - m["target"]]}'] if mode == 'binary' else [f'{ylab[j]}/{ylab[-1]}' for j in range(k - 1)]
        order = list(range(p))
        rank = {'Intercept': -1}
        for i, e in enumerate(d.effects):
            for c in e.get('terms', []):
                rank.setdefault(c, i)
        order.sort(key=lambda j: rank.get(names[j], len(d.effects)))
        # Unstable (JMP's mark): the fit's vector is B column by column; the intercept at x = 0 takes the centred slopes' marks too
        un = _logit_unstable(m)
        U = un.reshape(B.shape, order='F') if un is not None else np.zeros(B.shape, dtype=bool)
        if T is not None and 'Intercept' in names:
            i0 = names.index('Intercept')
            U[i0, :] |= np.any(U[np.abs(T[i0]) > 0, :], axis=0)
        for q, lg in enumerate(logits):
            for j in order:
                v, se = B[j, q], S[j, q]
                chi = (v / se) ** 2 if se > 0 else None
                est.append({'logit': lg, 'term': _tlabel(d, names[j]), 'estimate': float(v), 'se': float(se), 'chisq': chi,
                            'p': float(stats.chi2.sf(chi, 1)) if chi is not None else None, 'lower': float(v - z * se), 'upper': float(v + z * se),
                            'unstable': 'Unstable' if U[j, q] else ''})
        footer = 'For log odds of ' + ', '.join(logits)
    # whole model
    dfm = len(m['beta_cols']) if mode == 'ordinal' else (p - (1 if 'Intercept' in names else 0)) * (1 if mode == 'binary' else k - 1)
    lr = 2 * (llf - llnull)
    kpar = (len(m['beta_cols']) + k - 1) if mode == 'ordinal' else p * (1 if mode == 'binary' else k - 1)
    aicc = -2 * llf + 2 * kpar + (2 * kpar * (kpar + 1) / (N - kpar - 1) if N - kpar - 1 > 0 else float('nan'))
    bic = -2 * llf + kpar * math.log(N)
    whole = [{'model': 'Difference', 'nll': llf - llnull, 'df': dfm, 'chisq': lr, 'p': float(stats.chi2.sf(lr, dfm)) if dfm > 0 else None},
             {'model': 'Full', 'nll': -llf, 'df': None, 'chisq': None, 'p': None},
             {'model': 'Reduced', 'nll': -llnull, 'df': None, 'chisq': None, 'p': None}]
    P, eta = _logit_probs(m, Xa)
    pa = P[np.arange(len(m['codes'])), m['codes']]
    most = np.argmax(P, axis=1)
    fit = {'entropy_rsq': 1 - llf / llnull if llnull else None,
           'generalized_rsq': (1 - _exp(2 * (llnull - llf) / N)) / (1 - _exp(2 * llnull / N)) if llnull else None,
           'mean_neg_log_p': -llf / N, 'rmse': float(math.sqrt(np.sum(w * (1 - pa) ** 2) / N)), 'mad': float(np.sum(w * np.abs(1 - pa)) / N),
           'misclass': float(np.sum(w * (most != m['codes'])) / N), 'n': N}
    # Lack of Fit: the fitted model against the saturated one over the distinct patterns of the X values (JMP's)
    xs_ = [a for a in d.alias.values() if a != d.y_alias and a in d.df]
    lof = None
    if xs_:
        pat = d.df[xs_].groupby(xs_, observed=True, sort=False).ngroup().to_numpy()
        lof = models.logistic_lack_of_fit(pat, m['codes'], w, k, llf, kpar - (k - 1))
    # effect likelihood ratio tests
    et = []
    for e in d.effects:
        cols = [names.index(t) for t in e.get('terms', []) if t in names]
        if not cols:
            continue
        keep = [j for j in range(p) if j not in cols]
        lr_e = max(2 * (llf - _logit_llf_reduced(m, keep)), 0.0)
        dfe = len(cols) * (1 if mode in ('binary', 'ordinal') else k - 1)
        et.append({'source': e['label'], 'nparm': len(cols), 'df': dfe, 'lr': lr_e, 'p': float(stats.chi2.sf(lr_e, dfe))})
    # odds ratios: unit and range for continuous main effects, level pairs for categorical ones
    odds = _odds_ratios(m, z)
    # confusion matrix, ROC
    conf = np.zeros((k, k))
    np.add.at(conf, (m['codes'], most), w)
    rocs = []
    for j in ([m['target']] if mode == 'binary' else range(k)):
        r = _roc(P[:, j], (m['codes'] == j).astype(float), w)
        if r:
            r['level'] = ylab[j]
            rocs.append(r)
    if lof is not None:
        xn = [d.name[a] for a in xs_]
        lc_ = _logit_fit_code(m, table, table_name, rows)
        lc_[0] = lc_[0].replace('\n' + PLT, '\nfrom scipy import stats')
        lof['code'] = '\n'.join(lc_ + models.LOGISTIC_LOF_CODE + [
            f'pattern = d.groupby({J(xn)}, observed=True, sort=False).ngroup().to_numpy()   # the distinct patterns of the X values',
            f'print(lack_of_fit(pattern, codes, w if w is not None else np.ones(len(d)), k, fit.llf, {kpar - (k - 1)}))'])
    out = {'mode': mode, 'levels': ylab, 'level_values': levels, 'target': ylab[m['target']] if mode == 'binary' else None, 'whole': whole,
           'lack_of_fit': lof,
           'rsquare_u': fit['entropy_rsq'], 'aicc': aicc, 'bic': bic, 'n': N, 'fit': fit, 'estimates': est, 'footer': footer, 'effect_tests': et,
           'odds': odds, 'confusion': {'levels': ylab, 'matrix': conf}, 'roc': rocs, 'factors': _factors(d), 'key': m['key'], 'alpha': alpha,
           'probs': {'rows': [int(i) for i in d.df.index], 'prob': P, 'most_likely': [ylab[i] for i in most], 'actual': [ylab[i] for i in m['codes']],
                     'lin': eta, 'lin_names': ([f'Lin[{ylab[m["target"]]}]'] if mode == 'binary' else [f'Lin[{ylab[j]}]' for j in range(k - 1)]) if mode != 'ordinal' else ['Linear']},
           'distr': m['distr']}
    out['plot'] = _logistic_plot(m)
    notes.append('Confidence limits are Wald limits; JMP gives profile-likelihood limits for the parameters and odds ratios.')
    if any(r.get('unstable') for r in est):
        out['unstable'] = True
        notes.insert(0, 'Unstable estimates: the data separate the levels of the response along the marked terms (a level of a factor, or a '
                        'range of an X, where every row has the same response level, often a sparse level), so the likelihood keeps rising as '
                        'those estimates move away from zero and the fit stops somewhere on the way. Their values, standard errors and tests '
                        'mean little; the probabilities of the other rows are still fine. Combine sparse levels or leave the term out.')
    if mode == 'ordinal':
        notes.append('statsmodels\' OrderedModel writes P(Y ≤ j) = F(t_j − x′b); the report shows JMP\'s form F(a_j + x′b): the same thresholds, the '
                     'coefficients with the opposite sign. The standard errors of the thresholds are by the delta method.')
    if m['w'] is not None and mode != 'binary':
        notes.append('The weights are used as frequencies (the rows are repeated).')
    lines = _code_frame(d, table, table_name, rows, [weight, freq], ['import patsy'])
    lines.append(f'X = patsy.dmatrix({json.dumps(_code_formula(d, lhs=False))}, d)   # the design, effect coded')
    yq = json.dumps(spec['y'][0])
    lvq = json.dumps([v if isinstance(v, str) else float(v) for v in levels])
    if mode == 'ordinal':
        lines[0] = lines[0] + '\nfrom statsmodels.miscmodels.ordinal_model import OrderedModel'
        lines.append(f'y = pd.Series(pd.Categorical(d[{yq}], categories={lvq}, ordered=True))')
        xs = 'X[:, 1:]' if 'Intercept' in names else 'np.asarray(X)'
        lines.append(f'fit = OrderedModel(y, {xs}, distr={json.dumps(m["distr"])}).fit(method="bfgs")   # no intercept: the thresholds take its place')
    elif mode == 'binary':
        lines.append(f'y = (d[{yq}] == {json.dumps(levels[m["target"]] if isinstance(levels[m["target"]], str) else float(levels[m["target"]]))}).astype(float)   # the target level')
        lines.append('fit = sm.Logit(y, X).fit()' if m['w'] is None else f'fit = sm.GLM(y, X, family=sm.families.Binomial(), freq_weights={" * ".join("d[" + json.dumps(v) + "]" for v in (weight, freq) if v)}).fit()')
    else:
        lines.append(f'codes = pd.Categorical(d[{yq}], categories={lvq}).codes')
        lines.append(f'y = np.where(codes == {k - 1}, 0, codes + 1)   # the last level is the reference, as in JMP')
        lines.append('fit = sm.MNLogit(y, X).fit()')
    lines.append('print(fit.summary()); print(fit.llf, fit.llnull)   # Whole Model Test: 2 (llf - llnull)')
    lines += _centred_code(d)
    out['code'] = '\n'.join(lines)
    out['notes'] = notes
    notes.extend(_kfold_note(d))
    out['fit_report'] = _logit_fit_report(m, table, table_name, rows)
    if m.get('valid'):
        out['crossvalidation'], out['holdout'] = _logit_cv(m, table, table_name, rows)
        notes.insert(0, f'{m["valid"]["column"]}: the model is fitted to the training rows (0, or Training); the validation (1) and test (2) rows '
                        'are predicted by it and measured in Crossvalidation (with a confusion matrix, ROC and lift curves by set), and marked '
                        'in the logistic plot. Every other table is the training fit\'s.')
    out['plot_code'] = _logit_plots(m, table, rows, table_name, out)
    return out


def _train_prepared(m):
    """A logistic fit's rows as predictive.prepare would give them (one
    Training set), so that the page's predictive parts (the lift curves, the
    Decision Threshold) take its probabilities as any platform's."""
    P = predictive.Prepared()
    spec = m['spec']
    P.table, P.y, P.kind = m['tid'], spec['y'][0], 'categorical'
    P.index = np.asarray(m['d'].df.index, dtype=int)
    P.levels = [v.item() if hasattr(v, 'item') else v for v in m['levels']]
    P.labels = [_lvl(v) for v in m['levels']]
    P.target = np.asarray(m['codes'], dtype=int)
    P.sets = np.zeros(len(P.index), dtype=int)
    P.w = None if m['w'] is None else np.asarray(m['w'], dtype=float)
    P.freq = None if not spec['freq'] else _col_values(m['tid'], spec['freq'], P.index)
    P.spec = {'weight': spec['weight'], 'freq': spec['freq'], 'validation': None, 'portion': 0.0, 'seed': None}
    return P


def _logit_fit_report(m, table, table_name, rows):
    """predictive.report of the training rows' probabilities: the lift and
    gains curves and, for two levels, the Decision Threshold (WP3's), with
    their code (the model fitted as the report's code fits it)."""
    Q = _train_prepared(m)
    P, _eta = _logit_probs(m, m['X'].to_numpy(float))
    head = _logit_fit_code(m, table, table_name, rows) + ['y, sets, fitted = codes, np.zeros(len(d), dtype=int), probs(X)   # the rows, their level, one Training set, the probabilities']
    return _jmp_target(m, predictive.report(Q, P, roc_curves=True, head='\n'.join(head)))


def _jmp_target(m, rep):
    """The Decision Threshold's target level at first: the fit's (the first
    level unless Target Level says otherwise), as JMP's logistic reports have
    it; predictive.threshold starts at the second."""
    if rep and rep.get('threshold') and m['mode'] == 'binary':
        labs = list(rep['threshold'].get('levels') or [])
        tl = _lvl(m['levels'][m['target']])
        if tl in labs:
            rep['threshold']['target'] = labs.index(tl)
    return rep


def _logit_cv(m, table, table_name, rows):
    """A logistic fit's Crossvalidation (a Validation column): every set's
    rows given the training fit's probabilities, measured by
    predictive.report (the measures, a confusion matrix, ROC and lift
    curves by set, their code); and the hold-out rows."""
    V, d = m['valid'], m['d']
    P = V['P']
    y = m['spec']['y'][0]
    idx, X, _ = models.new_rows(d, m['X'].design_info, table, rows=P.index)
    Pm, _eta = _logit_probs(m, X)
    cols = [_level_col(m['levels'], lv) for lv in P.levels]
    fitted = np.column_stack([Pm[:, c] if c is not None else np.zeros(len(idx)) for c in cols])
    fc = _logit_fit_code(m, table, table_name, rows)
    head = fc + _cv_frame_code(d, table, V, [m['spec']['weight'], m['spec']['freq']]) + [
        'La = np.asarray(patsy.build_design_matrices([Xd.design_info], a)[0])',
        f'plevels = [{", ".join(_pylit(v) for v in P.levels)}]   # the levels of every set',
        'Pt = probs(La); P = np.column_stack([Pt[:, levels.index(v)] if v in levels else np.zeros(len(a)) for v in plevels])   # each row\'s probabilities, from the training fit',
        f'ya = pd.Categorical(a[{J(y)}], categories=plevels).codes   # the actual level']
    graph_head = head + ['d, y, fitted = a, ya, P   # for the graphs: the rows, the level, the probabilities']
    code = '\n'.join(head + _cv_measure_code('categorical', P.levels))
    rep = _jmp_target(m, _cv_report(m, idx, fitted, code=code, head='\n'.join(graph_head), curves=True))
    return rep, _holdout(V, idx, fitted, None)


def _with_plt(lines, imports=()):
    """A report code's lines (a list of lines or of blocks of lines) with
    matplotlib, and the other imports, first among its head's extra imports
    (where code_head puts them)."""
    text = '\n'.join(lines).replace('import statsmodels.formula.api as smf', '\n'.join(['import statsmodels.formula.api as smf', PLT, *imports]), 1)
    return text.split('\n')


def _after_frame(lines, extra):
    """The lines with extra ones right after the frame (d = df[...].dropna())."""
    k = next(i for i, ln in enumerate(lines) if ln.startswith('d = df['))
    return lines[:k + 1] + list(extra) + lines[k + 1:]


def _upto(lines, start):
    """The lines up to the first that starts with start (the fit), without the rest (the prints)."""
    k = next(i for i, ln in enumerate(lines) if ln.startswith(start))
    return lines[:k + 1]


def _logit_fit_code(m, table, table_name, rows):
    """The lines that fit the logistic model as the report does, and give
    probs(L): each level's probability (in the table's order) at design rows L."""
    d, spec = m['d'], m['spec']
    weight, freq = spec['weight'], spec['freq']
    mode, k = m['mode'], m['k']
    imports = ['import patsy'] + (['from scipy import stats', 'from statsmodels.miscmodels.ordinal_model import OrderedModel'] if mode == 'ordinal' else [])
    lines = _code_frame(d, table, table_name, rows, [weight, freq], [PLT, *imports]) + _positive_weights(weight, freq)
    lines.append(f'Xd = patsy.dmatrix({J(_code_formula(d, lhs=False))}, d); X = np.asarray(Xd)   # the design, effect coded')
    lines.append(f'levels = [{", ".join(_pylit(v) for v in m["levels"])}]; names = {J([_lvl(v) for v in m["levels"]])}   # the levels in these rows, in the table\'s order')
    lines.append(f'codes = pd.Categorical(d[{J(spec["y"][0])}], categories=levels).codes; k = {k}')
    wexpr = ' * '.join(f'd[{J(v)}]' for v in (weight, freq) if v)
    lines.append(f'w = ({wexpr}).to_numpy(float)' if wexpr else 'w = None')
    if mode != 'binary' and wexpr:
        lines.append('r_ = np.round(w).astype(int)   # the weights as frequencies: the rows repeated')
    rep = lambda a: f'np.repeat({a}, r_, axis=0)' if wexpr else a   # noqa: E731
    if mode == 'binary':
        t = m['target']
        lines.append(f'fit = sm.GLM((codes == {t}).astype(float), X, family=sm.families.Binomial(), freq_weights=w).fit(tol_criterion="params", atol=1e-12, rtol=1e-10, maxiter=200)   # log odds of {one_line(_lvl(m["levels"][t]))}')
        lines += ['def probs(L):', f'    p = 1 / (1 + np.exp(-(L @ fit.params)))   # P({one_line(_lvl(m["levels"][t]))})',
                  f'    return np.column_stack({"[p, 1 - p]" if t == 0 else "[1 - p, p]"})']
    elif mode == 'multinomial':
        lines.append('ysm = np.where(codes == k - 1, 0, codes + 1)   # the last level is the reference, as in JMP')
        lines.append(f'fit = sm.MNLogit({rep("ysm")}, {rep("X")}).fit(disp=0, method="newton", maxiter=200)')
        lines.append('if not fit.mle_retvals.get("converged", True):')
        lines.append(f'    fit = sm.MNLogit({rep("ysm")}, {rep("X")}).fit(disp=0, method="bfgs", maxiter=2000)')
        lines.append('def probs(L):')
        lines.append('    e = np.column_stack([np.zeros(len(L)), L @ fit.params]); e = np.exp(e - e.max(axis=1, keepdims=True)); p = e / e.sum(axis=1, keepdims=True)')
        lines.append('    return np.column_stack([p[:, 1:], p[:, :1]])   # back in the table\'s order')
    else:
        keep = m['beta_cols']
        lines.append(f'keep = {keep}   # every column but the intercept: the thresholds take its place')
        lines.append(f'yc = pd.Series(pd.Categorical.from_codes({rep("codes")}, categories=[str(i) for i in range(k)], ordered=True))')
        lines.append(f'om = OrderedModel(yc, pd.DataFrame({rep("X")}[:, keep]), distr={J(m["distr"])})')
        lines.append('fit = om.fit(method="bfgs", disp=0, maxiter=1000)')
        lines.append('if not fit.mle_retvals.get("converged", True):')
        lines.append('    fit = om.fit(start_params=fit.params, method="newton", disp=0, maxiter=100)')
        lines.append(f'beta, cuts = -np.asarray(fit.params)[:{len(keep)}], om.transform_threshold_params(np.asarray(fit.params))[1:-1]   # JMP\'s P(Y <= j) = F(a_j + x\'b)')
        F = 'stats.logistic.cdf' if m['distr'] == 'logit' else 'stats.norm.cdf'
        lines.append('def probs(L):')
        lines.append(f'    cum = np.column_stack([{F}(c + L[:, keep] @ beta) for c in cuts] + [np.ones(len(L))])')
        lines.append('    return np.diff(np.column_stack([np.zeros(len(L)), cum]), axis=1)')
    return lines


def _logit_hold_code(m, table, p):
    """The logistic plot's validation and test rows in its code: their
    probabilities from the training fit, each placed at random between the
    curves of its level (a seed of their own, as the report), marked."""
    V = m['valid']
    y = m['spec']['y'][0]
    return [*_cv_frame_code(m['d'], table, V, [m['spec']['weight'], m['spec']['freq']]),
            f'keep_ = (sets > 0) & a[{J(y)}].isin(levels).to_numpy(); a, sets = a[keep_], sets[keep_]   # the hold-out rows of the training rows\' levels',
            f'ha = np.asarray(patsy.build_design_matrices([Xd.design_info], a)[0]); ch = pd.Categorical(a[{J(y)}], categories=levels).codes',
            'crh = np.column_stack([np.zeros(len(a)), np.cumsum(probs(ha), axis=1)]); ih = np.arange(len(a))',
            'uh = np.random.default_rng(20260927).uniform(0.1, 0.9, len(a)); pyh = crh[ih, ch] + uh * (crh[ih, ch + 1] - crh[ih, ch])',
            f'xh = a[{J(p["factor"])}].to_numpy(float)',
            'for kk, (name, marker, color) in {1: ("Validation", "^", "#d9822b"), 2: ("Test", "s", "#3a7d44")}.items():   # the hold-out rows, marked',
            '    s_ = sets == kk',
            '    if s_.any():',
            '        ax.scatter(xh[s_], pyh[s_], marker=marker, s=22, color=color, label=name)',
            'fig.legend(loc="outside lower center", ncols=3, fontsize=8, frameon=False)']


def _logit_plots(m, table, rows, table_name, out):
    """The Nominal and Ordinal Logistic report's graphs as code: the logistic
    plot (one continuous X) and the ROC curves."""
    codes = {}
    y = m['spec']['y'][0]
    p = out.get('plot')
    if p:
        c = _logit_fit_code(m, table, table_name, rows) + [
            f'x = d[{J(p["factor"])}].to_numpy(float)',
            'g = np.linspace(x.min(), x.max(), 100)',
            f'cum = np.cumsum(probs(np.asarray(patsy.build_design_matrices([Xd.design_info], pd.DataFrame({{{J(p["factor"])}: g}}))[0])), axis=1)[:, :-1]   # each level\'s cumulative probability',
            'cr = np.column_stack([np.zeros(len(x)), np.cumsum(probs(X), axis=1)])',
            'u = np.random.default_rng(20260926).uniform(0.1, 0.9, len(x))   # each row at random between the curves of its level, as the report',
            'i = np.arange(len(x)); py = cr[i, codes] + u * (cr[i, codes + 1] - cr[i, codes])',
            f'colors = {J(PALETTE)}', _fig(430, 320 + (22 if p.get('holdout') else 0)),
            'for j in range(k - 1):', '    ax.plot(g, cum[:, j], color=colors[j % len(colors)], linewidth=1.3)',
            f'ax.scatter(x, py, s={8 if len(m["d"].df) > 500 else 13}, color="{BASE}"{", label=" + J("Training") if p.get("holdout") else ""})',
            *(_logit_hold_code(m, table, p) if p.get('holdout') else []),
            'ends = [0.0] + [cum[-1, j] for j in range(k - 1)] + [1.0]   # the level names at the right, between their curves',
            'for j, nm in enumerate(names):',
            '    ax.text(1.01, (ends[j] + ends[j + 1]) / 2, nm, transform=ax.get_yaxis_transform(), color=colors[j % len(colors)], fontsize=8, va="center")',
            'ax.set_ylim(0, 1)', f'ax.set_xlabel({J(p["factor"])})', f'ax.set_ylabel({J(y + " (cumulative probability)")})', f'ax.set_title({J(y + " logistic plot")})', 'plt.show()']
        codes['logistic'] = '\n'.join(c)
    if out.get('roc'):
        targets = [m['target']] if m['mode'] == 'binary' else list(range(m['k']))
        c = _logit_fit_code(m, table, table_name, rows) + [
            'P = probs(X); wv = w if w is not None else np.ones(len(d))',
            'def roc(score, event, w):   # the thresholds from high to low; tied scores move together',
            '    o = np.argsort(-score, kind="stable"); s_, e_, w_ = score[o], event[o], w[o]',
            '    tp, fp = np.cumsum(w_ * e_), np.cumsum(w_ * (1 - e_)); last = np.r_[np.diff(s_) != 0, True]',
            '    return np.r_[0, fp[last] / fp[-1]], np.r_[0, tp[last] / tp[-1]]',
            f'colors = {J(PALETTE)}', _fig(360, 340),
            f'for i, j in enumerate({targets!r}):   # {"the target level" if m["mode"] == "binary" else "each level against all the others"}, by its fitted probability',
            '    fpr, tpr = roc(P[:, j], (codes == j).astype(float), wv)',
            '    ax.plot(fpr, tpr, drawstyle="steps-post", color=colors[i % len(colors)], linewidth=1.3, label=f"{names[j]} (AUC {np.trapezoid(tpr, fpr):.4f})")',
            f'ax.plot([0, 1], [0, 1], color="{MUTED}", linewidth=0.7, linestyle=":")', 'ax.set_xlim(0, 1); ax.set_ylim(0, 1.01)',
            'ax.legend(loc="lower right", fontsize=8, frameon=False)', 'ax.set_xlabel("1 - Specificity")', 'ax.set_ylabel("Sensitivity")', 'ax.set_title("ROC curve")', 'plt.show()']
        codes['roc'] = '\n'.join(c)
    return codes


def _iv_plots(m, table, rows, table_name):
    """The Instrumental Variables report's graphs as code: actual by predicted,
    the residuals by predicted and by row."""
    y = m['spec']['y'][0]
    n = len(m['d'].df)
    head = _upto(_with_plt(_iv_code(m, table, table_name, rows, {}, False).split('\n')), 'fit = IV2SLS')
    head.append('pred = np.asarray(X) @ fit.params.to_numpy(); actual = y.to_numpy(float)   # the model\'s own prediction, Xb (not the second stage\'s)')
    return {'actual': _row_plot(head + ['lo, hi = min(pred.min(), actual.min()), max(pred.max(), actual.max())'], 'pred', 'actual', n, f'{y} Predicted', f'{y} Actual',
                                f'{y} actual by predicted', 400, 320, [f'ax.plot([lo, hi], [lo, hi], color="{FIT}", linewidth=1)']),
            'resid': _row_plot(head, 'pred', 'actual - pred', n, f'{y} Predicted', f'{y} Residual', f'{y} residual by predicted', zero=True),
            'residRow': _row_plot(head, 'd.index + 1', 'actual - pred', n, 'Row Number', f'{y} Residual', f'{y} residual by row', 460, zero=True)}


def _qr_plots(m, table, rows, table_name, out):
    """The Quantile Regression report's graphs as code: actual by predicted,
    the residuals, the quantile process of each term, the quantile lines."""
    d = m['d']
    y = m['spec']['y'][0]
    n = len(d.df)
    tau = m['tau']
    base = _upto(_with_plt(_qr_code(m, table, table_name, rows, None, out['alpha']).split('\n')), 'fit = QuantReg')
    base.append('pred = np.asarray(X) @ fit.params.to_numpy(); actual = y.to_numpy(float)')
    tl = _fmt_num(tau)
    codes = {'actual': _row_plot(base + ['lo, hi = min(pred.min(), actual.min()), max(pred.max(), actual.max())'], 'pred', 'actual', n, f'{y} Predicted {tl} quantile',
                                 f'{y} Actual', f'{y} actual by predicted quantile', 400, 320, [f'ax.plot([lo, hi], [lo, hi], color="{FIT}", linewidth=1)']),
             'resid': _row_plot(base, 'pred', 'actual - pred', n, f'{y} Predicted {tl} quantile', f'{y} Residual', f'{y} quantile residual by predicted', zero=True)}
    # the quantile process: each term's estimate over the quantiles, with the least squares estimate beside it
    pr = out.get('process')
    if pr:
        names = m['names']
        order = [names.index(r['name']) for r in out['estimates']['rows']]
        T = _uncenter(d, names)
        opts = f'vcov={"iid" if m["cov"] == "iid" else "robust"!r}, kernel={m["kernel"]!r}, bandwidth={m["bw"]!r}, max_iter={_QR_MAXITER}'
        common = _upto(_with_plt(_qr_code(m, table, table_name, rows, None, out['alpha']).split('\n'), ['from scipy import stats']), 'y = d[')
        if T is not None:
            i0 = names.index('Intercept')
            common.append(f'T = np.eye({len(names)})   # the intercept at 0, as the report puts it back (the centred main effects)')
            for t_, mm in getattr(d, 'centered_main', {}).items():
                if t_ in names:
                    common.append(f'T[{i0}, {names.index(t_)}] = -{mm!r}')
        else:
            common.append(f'T = np.eye({len(names)})')
        common += [f'taus = {pr["taus"]!r}', 'est, low, upp = [], [], []', 'for t in taus:   # the fit at every quantile of the process, with its t interval',
                   f'    f = QuantReg(y, X).fit(q=t, {opts})']
        if m['cov'] == 'powell':
            common += ['    Xa, e = np.asarray(X), f.resid.to_numpy(); fk = kernels[' + repr(m['kernel']) + '](e / f.bandwidth) / f.bandwidth',
                       '    A = np.linalg.pinv((Xa * fk[:, None]).T @ Xa); V = t * (1 - t) * A @ Xa.T @ Xa @ A   # Powell\'s sandwich']
        else:
            common += ['    V = f.cov_params().to_numpy()']
        common += ['    b, s = T @ f.params.to_numpy(), np.sqrt(np.maximum(np.diag(T @ V @ T.T), 0))',
                   f'    tc = stats.t.ppf({1 - out["alpha"] / 2!r}, f.df_resid)',
                   '    est.append(b); low.append(b - tc * s); upp.append(b + tc * s)',
                   'est, low, upp = np.array(est), np.array(low), np.array(upp)',
                   'ols = sm.OLS(y, X).fit(); bo, so = T @ ols.params.to_numpy(), np.sqrt(np.maximum(np.diag(T @ ols.cov_params().to_numpy() @ T.T), 0))',
                   f'to = stats.t.ppf({1 - out["alpha"] / 2!r}, ols.df_resid)']
        proc = []
        for i, (j, term) in enumerate(zip(order, pr['terms'])):
            c = common + [f'j = {j}   # {one_line(term)}', _fig(300, 230),
                          f'ax.axhspan(bo[j] - to * so[j], bo[j] + to * so[j], color="{FIT}", alpha=0.1, linewidth=0)   # the least squares interval',
                          f'ax.axhline(bo[j], color="{FIT}", linewidth=0.9, linestyle="--")   # and its estimate',
                          f'ax.fill_between(taus, low[:, j], upp[:, j], color="{BASE}", alpha=0.18, linewidth=0)',
                          f'ax.plot(taus, est[:, j], color="{BASE}", linewidth=1.1, marker="o", markersize=3)',
                          f'ax.axvline({tau!r}, color="{MUTED}", linewidth=0.7, linestyle=":")   # the report\'s quantile',
                          'ax.set_xlim(0, 1)', 'ax.set_xlabel("Quantile τ")', f'ax.set_ylabel({J(term)})', f'ax.set_title({J(term + " quantile process")})', 'plt.show()']
            proc.append('\n'.join(c))
        codes['process'] = proc
    L = out.get('lines')
    if L:
        taus = [q['tau'] for q in L['lines']]
        c = base + ['from matplotlib.colors import LinearSegmentedColormap',
                    f'gx = np.linspace(d[{J(L["factor"])}].min(), d[{J(L["factor"])}].max(), 61)',
                    f'G = np.asarray(patsy.build_design_matrices([X.design_info], pd.DataFrame({{{J(L["factor"])}: gx}}))[0])',
                    f'taus = {taus!r}',
                    'ramp = LinearSegmentedColormap.from_list("ramp", ["#2f6ec7", "#b0b0b0", "#c0392b"])   # the page\'s colours, low to high quantiles',
                    _fig(520, 340),
                    f'ax.scatter(d[{J(L["factor"])}], actual, s={8 if n > 500 else 18}, color="{BASE}")',
                    'for t in taus:',
                    f'    ft = QuantReg(y, X).fit(q=t, vcov={"iid" if m["cov"] == "iid" else "robust"!r}, kernel={m["kernel"]!r}, bandwidth={m["bw"]!r}, max_iter={_QR_MAXITER})',
                    f'    ax.plot(gx, G @ ft.params.to_numpy(), color=ramp((t - min(taus)) / (max(taus) - min(taus)) if max(taus) > min(taus) else 0.5), linewidth=1.9 if abs(t - {tau!r}) < 1e-9 else 1.2, label=f"τ = {{t}}")',
                    f'ax.plot(gx, G @ sm.OLS(y, X).fit().params.to_numpy(), color="{TEXT}", linewidth=0.9, linestyle="--", label="Least squares")',
                    'ax.legend(title="Quantile", fontsize=8, frameon=False)',
                    f'ax.set_xlabel({J(L["factor"])})', f'ax.set_ylabel({J(y)})', f'ax.set_title({J(y + " quantile lines")})', 'plt.show()']
        codes['lines'] = '\n'.join(c)
    return codes


def _fmt_num(v):
    """A number as the page's fmt writes it (7 significant digits, no trailing zeros)."""
    if float(v).is_integer():
        return str(int(v))
    s = f'{float(v):.7g}'
    return s


def _gee_fit_code(m, table, table_name, rows):
    """The lines that fit the GEE model as the report does: X, the design
    (patsy), fam, the family, and fit."""
    head = _upto(_gee_code(m, table, table_name, rows, qic_scale=None, extra_imports=[PLT]), 'fit = sm.GEE')
    subj = m['spec']['subject']
    s0 = m['d'].df[m['d'].alias[subj]]
    if isinstance(s0.dtype, pd.CategoricalDtype):   # the subjects in the table's order, as the report numbers them
        cats = list(s0.cat.remove_unused_categories().cat.categories)
        head[-1] = head[-1].replace(f'groups=d[{J(subj)}]', f'groups=pd.Categorical(d[{J(subj)}], categories=[{", ".join(_pylit(v) for v in cats)}]).codes')
    return head


def _gee_plots(m, table, rows, table_name, out):
    """The GEE report's graphs as code: residual by predicted, actual by
    predicted, the residuals by subject, the working correlation."""
    y = m['spec']['y'][0]
    n = len(m['d'].df)
    head = _gee_fit_code(m, table, table_name, rows)
    head.append('mu, actual = fit.fittedvalues.to_numpy() if hasattr(fit.fittedvalues, "to_numpy") else np.asarray(fit.fittedvalues), np.asarray(y, float)   # the marginal mean')
    resp = out['model']['response']
    codes = {'residPred': _row_plot(head, 'mu', 'actual - mu', n, f'{resp} Predicted (marginal)', f'{resp} Residual', f'{y} residual by predicted', zero=True),
             'actualPred': _row_plot(head + ['lo, hi = min(mu.min(), actual.min()), max(mu.max(), actual.max())'], 'mu', 'actual', n, f'{resp} Predicted', f'{resp} Actual',
                                     f'{resp} actual by predicted', 400, 320, [f'ax.plot([lo, hi], [lo, hi], color="{FIT}", linewidth=1)'])}
    subj = m['spec']['subject']
    subjects = out['diag']['subjects']
    ns = len(subjects)
    by_subject = head + [
        f'subjects = {J(subjects)}   # every subject, in the table\'s order',
        f'at = d[{J(subj)}].map(lambda v: {_subject_key_code(m)}).map({{s: i for i, s in enumerate(subjects)}}).to_numpy()   # each row\'s subject on the axis',
        'res = actual - mu',
        _fig(max(420, min(900, 14 * ns + 120)), 300)]
    boxes = ['boxes = []   # Boxes per Subject: the quartiles as the page\'s graph takes them (the midpoint rule), whiskers to the furthest values within 1.5 IQR',
             'for i in range(len(subjects)):',
             '    v = res[at == i]; q1, med, q3 = np.percentile(v, [25, 50, 75], method="hazen"); iqr = q3 - q1',
             '    inside = v[(v >= q1 - 1.5 * iqr) & (v <= q3 + 1.5 * iqr)]',
             '    boxes.append({"q1": q1, "med": med, "q3": q3, "whislo": inside.min(), "whishi": inside.max()})',
             f'ax.bxp(boxes, positions=range(len(subjects)), widths=0.6, showfliers=False, manage_ticks=False, boxprops={{"color": "{MUTED}", "linewidth": 0.7}}, '
             f'medianprops={{"color": "{MUTED}", "linewidth": 0.7}}, whiskerprops={{"color": "{MUTED}", "linewidth": 0.7}}, capprops={{"color": "{MUTED}", "linewidth": 0.7}})']
    tail = [f'ax.scatter(at, res, s={8 if n > 500 else 13}, color="{BASE}")',
            f'ax.axhline(0, color="{MEAN}", linewidth=0.7)',
            f'ax.set_xticks(range(len(subjects)), subjects, rotation=90, fontsize={7 if ns > 40 else 8})', 'ax.set_xlim(-0.6, len(subjects) - 0.4)',
            f'ax.set_xlabel({J(subj)})', f'ax.set_ylabel({J(y + " Residual")})', f'ax.set_title({J(y + " residuals by subject")})', 'plt.show()']
    codes['residSubject'] = '\n'.join(by_subject + tail)
    codes['residSubjectBoxes'] = '\n'.join(by_subject + boxes + tail)
    k = len(out['dep']['matrix']['labels'])
    side = max(230, min(560, 70 + 42 * k))
    tl = m['spec']['time']
    c = head + ['from matplotlib.colors import LinearSegmentedColormap',
                'st = fit.model.cov_struct; sizes = [len(v) for v in fit.model.endog_li]; i = int(np.argmax(sizes))   # the first of the largest subjects',
                'M, is_cor = st.covariance_matrix(fit.model.cached_means[i][0], i); M = np.asarray(M, float)',
                'if not is_cor:', '    sd = np.sqrt(np.diag(M)); M = M / np.outer(sd, sd)',
                'idx = fit.model.group_indices[fit.model.group_labels[i]]']
    if tl:
        c.append(f'labels = [f"{{v:g}}" for v in d[{J(tl)}].to_numpy(float)[idx]]   # its rows\' times')
    else:
        c.append('labels = [f"row {j + 1}" for j in range(len(idx))]')
    c += [_fig(side + 80, side),
          'im = ax.imshow(M, vmin=-1, vmax=1, cmap=LinearSegmentedColormap.from_list("rb", ["#2f6ec7", "#f6f3f0", "#c0392b"]))',
          'fig.colorbar(im, ax=ax, shrink=0.85)',
          'ax.set_xticks(range(len(labels)), labels); ax.set_yticks(range(len(labels)), labels)']
    if k <= 12:
        c += ['for a in range(len(labels)):', '    for b_ in range(len(labels)):',
              '        ax.text(b_, a, f"{M[a, b_]:.2f}".replace("-", "−"), ha="center", va="center", fontsize=8, color="white" if abs(M[a, b_]) > 0.5 else "#352921")']
    c += [f'ax.set_xlabel({J(tl or "Row of the subject")})', 'ax.set_title("working correlation")', 'plt.show()']
    codes['workcorr'] = '\n'.join(c)
    return codes


def _subject_key_code(m):
    """How a subject's value is written as its label (the page's)."""
    return 'str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)'


def _odds_ratios(m, z):
    d, res = m['d'], m['res']
    names = m['names']
    mode = m['mode']
    ylab = [_lvl(v) for v in m['levels']]
    out = {'unit': [], 'levels': []}
    if mode == 'ordinal':
        beta, _cuts = _ordinal_params(m)
        C = _ordinal_cov(m)[m['k'] - 1:, m['k'] - 1:]
        cols = m['beta_cols']
        coefs = [(0, '', beta, C, cols)]
    else:
        B = np.asarray(res.params, dtype=float).reshape(len(names), -1)
        Cf = np.asarray(res.cov_params(), dtype=float)
        coefs = []
        nq = B.shape[1]
        for q in range(nq):
            if mode == 'binary':
                lg, Cq = f'{ylab[m["target"]]}/{ylab[1 - m["target"]]}', Cf
            else:
                lg = f'{ylab[q]}/{ylab[-1]}'
                # MNLogit's cov_params: the parameters of the first equation, then the second, ...
                sl = slice(q * len(names), (q + 1) * len(names))
                Cq = Cf[sl, sl]
            coefs.append((q, lg, B[:, q], Cq, list(range(len(names)))))
    for e in d.effects:
        if len(e['cols']) != 1:
            continue
        a = d.alias[e['cols'][0]]
        terms = [t for t in e.get('terms', []) if t in names]
        if a not in d.categorical and len(terms) == 1:
            x = d.df[a].to_numpy(float)
            rng = float(np.max(x) - np.min(x))
            for q, lg, b, C, cols in coefs:
                if names.index(terms[0]) not in cols:
                    continue
                j = cols.index(names.index(terms[0]))
                bj, sj = float(b[j]), math.sqrt(max(C[j, j], 0))
                out['unit'].append({'logit': lg, 'term': e['label'], 'unit': _exp(bj), 'lower': _exp(bj - z * sj), 'upper': _exp(bj + z * sj),
                                    'range': _exp(bj * rng), 'range_lower': _exp((bj - z * sj) * rng), 'range_upper': _exp((bj + z * sj) * rng),
                                    'p': float(stats.chi2.sf((bj / sj) ** 2, 1)) if sj > 0 else None, 'span': rng})
        elif a in d.categorical:
            lv = d.levels[a]
            others = {x: AVG for x in d.categorical if x != a}
            Ls = m['coder'].rows([dict(others, **{a: i}) for i in range(len(lv))])
            for q, lg, b, C, cols in coefs:
                Lq = Ls[:, cols]
                for i1 in range(len(lv)):
                    for i2 in range(len(lv)):
                        if i1 == i2:
                            continue
                        dl = Lq[i1] - Lq[i2]
                        lo_ = float(dl @ b)
                        se = math.sqrt(max(float(dl @ C @ dl), 0))
                        out['levels'].append({'logit': lg, 'term': e['label'], 'level1': _lvl(lv[i1]), 'level2': _lvl(lv[i2]), 'or': _exp(lo_),
                                              'lower': _exp(lo_ - z * se), 'upper': _exp(lo_ + z * se),
                                              'p': float(stats.chi2.sf((lo_ / se) ** 2, 1)) if se > 0 else None})
    return out


def _logistic_plot(m):
    """JMP's logistic plot for one continuous X: the cumulative probability
    curves, and each row's point placed at random between the curves of its
    level."""
    d = m['d']
    if len(d.effects) != 1 or len(d.effects[0]['cols']) != 1:
        return None
    n0 = d.effects[0]['cols'][0]
    a = d.alias[n0]
    if a in d.categorical:
        return None
    x = d.df[a].to_numpy(float)
    g = np.linspace(float(np.min(x)), float(np.max(x)), 100)
    Pg, _ = _logit_probs(m, m['coder'].rows([{a: v} for v in g]))
    cumg = np.cumsum(Pg, axis=1)[:, :-1]
    Pr, _ = _logit_probs(m, m['X'].to_numpy(float))
    cumr = np.column_stack([np.zeros(len(x)), np.cumsum(Pr, axis=1)])
    rng = np.random.default_rng(20260926)
    u = rng.uniform(0.1, 0.9, len(x))
    c = m['codes']
    lo, hi = cumr[np.arange(len(x)), c], cumr[np.arange(len(x)), c + 1]
    out = {'x': g, 'cum': cumg.T, 'factor': n0, 'points': {'x': x, 'y': lo + u * (hi - lo), 'rows': [int(i) for i in d.df.index]},
           'levels': [_lvl(v) for v in m['levels']]}
    V = m.get('valid')
    if V:   # the validation and test rows, placed the same way between their level's curves
        P = V['P']
        hrows = P.index[P.sets > 0]
        idx, Xh, _ = models.new_rows(d, m['X'].design_info, m['tid'], rows=hrows)
        yv = data.raw(m['tid'], m['spec']['y'][0], idx)
        ch = np.array([_level_col(m['levels'], v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else None for v in yv], dtype=object)
        ok = np.array([q is not None for q in ch], dtype=bool)
        idx, Xh, ch = idx[ok], Xh[ok], ch[ok].astype(int)
        Ph, _ = _logit_probs(m, Xh)
        cumh = np.column_stack([np.zeros(len(idx)), np.cumsum(Ph, axis=1)])
        uh = np.random.default_rng(20260927).uniform(0.1, 0.9, len(idx))
        loh, hih = cumh[np.arange(len(idx)), ch], cumh[np.arange(len(idx)), ch + 1]
        st_ = dict(zip((int(r) for r in P.index), (int(v) for v in P.sets)))
        out['holdout'] = {'x': _col_values(m['tid'], n0, idx), 'y': loh + uh * (hih - loh), 'rows': [int(r) for r in idx], 'set': [st_[int(r)] for r in idx]}
    return out


# ---------------------------------------------------------------------------
# Mixed Model (REML): mixed.py; these names delegate to it
# ---------------------------------------------------------------------------

def _mx():
    from . import mixed as mx
    return mx


def _zmatrix(d, cols):
    return _mx()._zmatrix(d, cols)


def _mixed_model(tid, rows, spec):
    return _mx()._mixed_model(tid, rows, spec)


def _reml(m):
    return _mx()._reml(m)


def _satterthwaite(dense, L):
    return _mx()._satterthwaite(dense, L)


def _mixed_predict(m, settings, alpha):
    return _mx()._mixed_predict(m, settings, alpha)


def _mixed_fit_code(m, table, table_name, rows, imports=()):
    return _mx()._mixed_fit_code(m, table, table_name, rows, imports)


def _mixed_plots(m, table, rows, table_name, out):
    return _mx()._mixed_plots(m, table, rows, table_name, out)


def _mixed_interaction_parts(m, table, table_name, rows):
    return _mx()._mixed_interaction_parts(m, table, table_name, rows)


def mixed(*args, **kwargs):
    """fitmodel.mixed (registered in mixed.py)."""
    return _mx().mixed(*args, **kwargs)


# ---------------------------------------------------------------------------
# MANOVA
# ---------------------------------------------------------------------------

def _transform_M(kind, k):
    if kind == 'sum':
        return np.ones((k, 1)), ['Sum']
    if kind == 'mean':
        return np.ones((k, 1)) / k, ['Mean']
    if kind == 'contrast':
        M = np.vstack([np.eye(k - 1), -np.ones((1, k - 1))])
        return M, [f'Contrast {i + 1}' for i in range(k - 1)]
    if kind == 'polynomial':
        t = np.arange(k, dtype=float)
        V = np.vander(t - t.mean(), k, increasing=True)
        Q, _ = np.linalg.qr(V)
        M = Q[:, 1:] * np.sign(Q[-1, 1:])
        return M, [['Linear', 'Quadratic', 'Cubic', 'Quartic'][i] if i < 4 else f'Degree {i + 1}' for i in range(k - 1)]
    return None, None


_MV_NAMES = {"Wilks' lambda": "Wilks' Lambda", "Pillai's trace": "Pillai's Trace", 'Hotelling-Lawley trace': 'Hotelling-Lawley',
             "Roy's greatest root": "Roy's Max Root"}

# ---- Repeated Measures ------------------------------------------------------------
# JMP's Choose Response > Repeated Measures: the Y columns are the levels of a
# within-subject factor (Y Name, Time by default). Between Subjects: each
# effect on the sum of the responses (M a column of ones). Within Subjects:
# the intercept on contrasts of the responses is the within factor, each
# effect on them its crossing with the within factor. With Univariate Tests
# Also: Mauchly's (1940) sphericity test and the univariate within tests,
# unadjusted and with the degrees of freedom times the Greenhouse-Geisser
# (1959) and Huynh-Feldt (1976) epsilons, all on the orthonormalized
# contrasts, as JMP computes them. The multivariate tests do not depend on
# the contrasts chosen; the univariate ones need them orthonormal.
_UNIVAR = (('unadj', 'Univar unadj Epsilon'), ('gg', 'Univar G-G Epsilon'), ('hf', 'Univar H-F Epsilon'))
_MV_F_NOTE = ('The F approximations are statsmodels\': Rao\'s for Wilks\' lambda, Pillai\'s, McKeon\'s for the Hotelling-Lawley trace and '
              'Roy\'s upper bound, the ones JMP reports (McKeon\'s gives the Hotelling-Lawley DenDF of 18.326 in JMP\'s Compound example).')


def _mv_results(mv, hyps, E, nu):
    """statsmodels' mv_test of each hypothesis (name, L[, M]), E the residual
    SSCP of the responses and nu its DF. statsmodels 0.14.6 fails
    (ValueError: the max of an empty array) when no eigenvalue of E^-1 H
    passes its tolerance, an effect that is exactly zero: that test gets the
    statistics of no effect (Wilks' lambda 1, the traces 0, F 0, p 1), with
    statsmodels' own degrees of freedom."""
    from statsmodels.multivariate.multivariate_ols import multivariate_stats
    out = {}
    for h in hyps:
        name, L = h[0], h[1]
        try:
            out[name] = mv.mv_test(hypotheses=[h]).results[name]
        except ValueError as ex:
            if 'zero-size array' not in str(ex):
                raise
            M = h[2] if len(h) > 2 else np.eye(E.shape[0])
            p_, q_ = int(np.linalg.matrix_rank(M)), int(np.linalg.matrix_rank(L))
            out[name] = {'stat': multivariate_stats(np.zeros(min(p_, q_)), p_, q_, nu, tolerance=-1.0),
                         'H': np.zeros((M.shape[1], M.shape[1])), 'E': M.T @ E @ M}
    return out


def _contrasts(k):
    """JMP's Contrast response design (each response minus the first),
    orthonormalized: k x (k - 1), orthogonal to a column of ones."""
    Mc = np.vstack([-np.ones((1, k - 1)), np.eye(k - 1)])
    return np.linalg.qr(Mc)[0]


def _mv_rows(stat, q, p, nu):
    """The test table of a hypothesis with q degrees of freedom on p
    transformed responses and nu error DF: JMP's single exact F Test when
    min(p, q) = 1 (every multivariate statistic is then the same test; its
    value is the one eigenvalue of E^-1 H), else the four statistics with
    statsmodels' F approximations (Rao, Pillai, McKeon, Roy's bound: the
    ones JMP reports)."""
    if min(p, q) == 1:
        lam = float(np.real(stat.loc['Hotelling-Lawley trace', 'Value']))
        df1, df2 = (q, nu) if p == 1 else (p, nu - p + 1)
        F = lam * df2 / df1 if df2 > 0 else float('nan')
        pv = float(stats.f.sf(F, df1, df2)) if df2 > 0 else None
        return [{'test': 'F Test', 'value': lam, 'f': F, 'numdf': float(df1), 'dendf': float(df2), 'p': pv}], True
    rows_ = []
    for idx, row in stat.iterrows():
        rows_.append({'test': _MV_NAMES.get(idx, idx), 'value': float(row['Value']), 'f': float(row['F Value']), 'numdf': float(row['Num DF']),
                      'dendf': float(row['Den DF']), 'p': float(row['Pr > F'])})
    return rows_, False


def _mauchly(W, nu, p):
    """Mauchly's criterion W of p orthonormal contrasts with nu error DF, as
    JMP reports it: -(nu - (2p² + p + 2)/(6p)) log W against chi-square with
    p(p + 1)/2 - 1 DF, the plain chi-square p-value (R's mauchly.test and
    pingouin add Anderson's second-order term to the p-value)."""
    df = p * (p + 1) / 2 - 1
    chi2 = -(nu - (2 * p * p + p + 2) / (6 * p)) * math.log(W) if W > 0 else float('inf')
    return chi2, df, float(stats.chi2.sf(chi2, df))


def _epsilons(S, n, nu):
    """The epsilons of the covariance S of p orthonormal contrasts, from n
    subjects and nu error DF: Greenhouse and Geisser's (Box's) tr(S)²/(p
    tr(S²)); Huynh and Feldt's (1976) (n p gg - 2)/(p (nu - p gg)) and
    Lecoutre's (1991) correction of it, nu + 1 in place of n (the same with
    one group of subjects); the lower bound 1/p. Capped at 1."""
    p = S.shape[0]
    tr, tr2 = float(np.trace(S)), float(np.trace(S @ S))
    gg = min(1.0, tr * tr / (p * tr2)) if tr2 > 0 else 1.0

    def hf(m):
        den = p * (nu - p * gg)
        return min(1.0, (m * p * gg - 2) / den) if den > 0 else 1.0
    return {'gg': gg, 'hf': hf(n), 'hf_lecoutre': hf(nu + 1), 'lower': 1.0 / p}


def _repeated(d, ys, Y, X, within, table, table_name, rows):
    from statsmodels.multivariate.manova import MANOVA
    names = list(X.columns)
    Xa = X.to_numpy(float)
    n, k = Y.shape
    p = k - 1
    nu = int(n - np.linalg.matrix_rank(Xa))
    if nu < 1:
        return {'error': f'{n} rows with every response: no error degrees of freedom left for the {int(np.linalg.matrix_rank(Xa))} parameters of the model'}
    C = _contrasts(k)
    one = np.ones((k, 1))
    I = np.eye(Xa.shape[1])
    nonint = [j for j, nm in enumerate(names) if nm != 'Intercept']
    Ls = []                                   # (between name, within name, columns)
    if nonint:
        Ls.append(('All Between', 'All Within Interactions', nonint))
    if 'Intercept' in names:
        Ls.append(('Intercept', within, [names.index('Intercept')]))
    for e in d.effects:
        cols = [names.index(t) for t in e.get('terms', []) if t in names]
        if cols:
            Ls.append((e['label'], f'{within}*{e["label"]}', cols))
    B = np.linalg.lstsq(Xa, Y, rcond=None)[0]
    R = Y - Xa @ B
    E = R.T @ R                               # the residual SSCP of the responses
    Ew = C.T @ E @ C
    S = Ew / nu                               # the covariance of the orthonormal contrasts
    eps = _epsilons(S, n, nu)
    multi = nu >= p                           # the multivariate within tests need E of full rank
    try:
        mv = MANOVA(Y, Xa)                    # statsmodels refuses a singular design (ValueError)
        tb = _mv_results(mv, [(b, I[c], one) for b, _w, c in Ls], E, nu)
        tw = _mv_results(mv, [(w, I[c], C) for _b, w, c in Ls], E, nu) if multi else None
    except (np.linalg.LinAlgError, ValueError):
        return {'error': 'The model cannot be tested: its design is singular (a crossing with an empty cell?), or the contrasts of the '
                         'responses are collinear.'}
    between, wtests = [], []
    for b, w, c in Ls:
        q = int(np.linalg.matrix_rank(I[c]))
        r_ = tb[b]
        rows_, exact = _mv_rows(r_['stat'], q, 1, nu)
        between.append({'effect': b, 'rows': rows_, 'exact': exact})
        if multi:
            r_ = tw[w]
            Hw = np.asarray(r_['H'], dtype=float)
            mrows, mexact = _mv_rows(r_['stat'], q, p, nu)
        else:
            Lc = I[c]
            XtXi = np.linalg.pinv(Xa.T @ Xa)
            t1 = Lc @ B @ C
            Hw = t1.T @ np.linalg.pinv(Lc @ XtXi @ Lc.T) @ t1
            mrows, mexact = [], min(p, q) == 1
        ssh, sse = float(np.trace(Hw)), float(np.trace(Ew))
        df1, df2 = q * p, nu * p
        F = (ssh / df1) / (sse / df2) if sse > 0 else float('nan')
        uni = []
        for key, label in _UNIVAR:
            ev = 1.0 if key == 'unadj' else eps[key]
            uni.append({'test': label, 'value': ev, 'f': F, 'numdf': ev * df1, 'dendf': ev * df2,
                        'p': float(stats.f.sf(F, ev * df1, ev * df2)) if np.isfinite(F) else None})
        wtests.append({'effect': w, 'rows': mrows, 'exact': mexact, 'univariate': uni, 'ss': ssh, 'df': df1})
    sph, sph_note = None, None
    if p < 2:
        sph_note = 'Two levels give a single contrast: sphericity holds trivially, and every epsilon is 1.'
    elif nu < p:
        sph_note = f'Sphericity test not performed: {nu} error degrees of freedom, fewer than the {p} contrasts.'
    else:
        sign, logdet = np.linalg.slogdet(S)
        W = float(math.exp(logdet - p * math.log(float(np.trace(S)) / p))) if sign > 0 else 0.0
        chi2, dfs, pv = _mauchly(W, nu, p)
        sph = {'w': W, 'chi2': chi2, 'df': dfs, 'p': pv}
    notes = [_MV_F_NOTE] if any(not t['exact'] for t in wtests if t['rows']) else []
    if not multi:
        notes.append(f'The multivariate within-subject tests need at least as many error degrees of freedom as contrasts ({nu} < {p}): '
                     'only the univariate tests are shown.')
    if 'Intercept' not in names:
        notes.append(f'Without an intercept there is no test of {within} itself: the within tests are its crossings with the effects.')
    sd = np.sqrt(np.diag(E))
    with np.errstate(invalid='ignore', divide='ignore'):
        pc = E / np.outer(sd, sd)
    # the code under the report
    lines = _code_frame(d, table, table_name, rows, [], ['import patsy', 'from scipy import stats', 'from statsmodels.multivariate.manova import MANOVA'])
    lines.append(f'X = np.asarray(patsy.dmatrix({json.dumps(_code_formula(d, lhs=False))}, d))   # the design, effect coded')
    lines.append(f'Y = d[{json.dumps(ys)}].to_numpy(); n, k = Y.shape; p = k - 1   # the levels of {one_line(within)}, in this order')
    lines.append('nu = n - np.linalg.matrix_rank(X)   # the error degrees of freedom')
    lines.append('C = np.linalg.qr(np.vstack([-np.ones((1, p)), np.eye(p)]))[0]   # the contrasts: each response minus the first, orthonormalized')
    lines.append('I = np.eye(X.shape[1])')
    lines.append('L = {' + ', '.join(f'{json.dumps(b)}: I[{c!r}]' for b, _w, c in Ls) + '}   # the rows of each hypothesis: the columns of its terms')
    lines.append('WS = {' + ', '.join(f'{json.dumps(w)}: {json.dumps(b)}' for b, w, _c in Ls) + '}   # a within test: the same rows on the contrasts')
    lines.append('mv = MANOVA(Y, X)')
    lines.append('between = mv.mv_test(hypotheses=[(h, L[h], np.ones((k, 1))) for h in L])   # Between Subjects: the sum of the responses')
    if multi:
        lines.append('within = mv.mv_test(hypotheses=[(w, L[h], C) for w, h in WS.items()])   # Within Subjects: the contrasts')
        lines.append('print(between.summary()); print(within.summary())   # one DF (or one response): all four statistics are the exact F Test')
    else:
        lines.append('print(between.summary())')
    lines += [
        'Rs = Y - X @ np.linalg.lstsq(X, Y, rcond=None)[0]; S = C.T @ Rs.T @ Rs @ C / nu   # the covariance of the orthonormal contrasts',
        'gg = min(1, np.trace(S) ** 2 / (p * np.trace(S @ S)))   # Greenhouse-Geisser epsilon',
        'hf = min(1, (n * p * gg - 2) / (p * (nu - p * gg)))   # Huynh-Feldt (1976); Lecoutre (1991) puts nu + 1 for n',
    ]
    if sph is not None:
        lines += ['Wm = np.linalg.det(S) / (np.trace(S) / p) ** p   # Mauchly\'s criterion',
                  'chi2 = -(nu - (2 * p * p + p + 2) / (6 * p)) * np.log(Wm); dfs = p * (p + 1) / 2 - 1',
                  'print("Sphericity Test", Wm, chi2, dfs, stats.chi2.sf(chi2, dfs))']
    lines += ['uni = {}',
              'for w, h in WS.items():   # the univariate within tests',
              '    t1 = L[h] @ np.linalg.lstsq(X, Y, rcond=None)[0] @ C; q = np.linalg.matrix_rank(L[h])',
              '    H = t1.T @ np.linalg.inv(L[h] @ np.linalg.pinv(X.T @ X) @ L[h].T) @ t1',
              '    F = (np.trace(H) / (q * p)) / (np.trace(S) / p)',
              '    uni[w] = [F] + [stats.f.sf(F, e * q * p, e * nu * p) for e in (1, gg, hf)]   # unadjusted, G-G and H-F p-values',
              'print(uni)']
    return {'response': 'repeated', 'responses': ys, 'within': within, 'n': int(n), 'k': int(k), 'p': int(p), 'dfe': nu,
            'between': between, 'within_tests': wtests, 'sphericity': sph, 'sphericity_note': sph_note, 'epsilon': eps,
            'multivariate_within': multi, 'E': E, 'partial_corr': pc, 'labels': ys, 'notes': notes, 'code': '\n'.join(lines)}


@api('fitmodel.manova')
def manova(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, response='identity', alpha=0.05, within='Time',
           table_name='data'):
    from statsmodels.multivariate.manova import MANOVA
    import statsmodels.api as sm
    ys = _ys(y)
    if len(ys) < 2:
        return {'error': 'MANOVA needs two or more continuous Y columns'}
    if weight or freq:
        return {'error': 'statsmodels\' MANOVA takes no weights: remove Weight and Freq'}
    effs = _eff_of(_spec(effects=effects))
    d = _design(table, ys, effs, rows, None, None, not no_intercept)
    for n0 in ys:
        if isinstance(d.df[d.alias[n0]].dtype, pd.CategoricalDtype):
            return {'error': f'{n0} is categorical: MANOVA needs continuous Y columns'}
    Y = d.df[[d.alias[n0] for n0 in ys]].to_numpy(float)
    X = _matrix(d)
    if response == 'repeated':
        return _repeated(d, ys, Y, X, str(within or 'Time').strip() or 'Time', table, table_name, rows)
    names = list(X.columns)
    Xa = X.to_numpy(float)
    p = Xa.shape[1]
    k = Y.shape[1]
    M, mnames = _transform_M(response, k)
    mv = MANOVA(Y, Xa)
    hyps = []
    nonint = [j for j, nm in enumerate(names) if nm != 'Intercept']

    def sel(cols):
        L = np.zeros((len(cols), p))
        for i, c in enumerate(cols):
            L[i, c] = 1
        return L
    if nonint:
        hyps.append(('Whole Model', sel(nonint)))
    if 'Intercept' in names:
        hyps.append(('Intercept', sel([names.index('Intercept')])))
    for e in d.effects:
        cols = [names.index(t) for t in e.get('terms', []) if t in names]
        if cols:
            hyps.append((e['label'], sel(cols)))
    B0 = np.linalg.lstsq(Xa, Y, rcond=None)[0]
    E0 = (Y - Xa @ B0).T @ (Y - Xa @ B0)
    res_ = _mv_results(mv, [(nm, L, M) if M is not None else (nm, L) for nm, L in hyps], E0, int(len(Y) - np.linalg.matrix_rank(Xa)))
    tests = []
    Hs = {}
    E = None
    for nm, _L in hyps:
        st = res_[nm]['stat']
        rows_ = []
        for idx, row in st.iterrows():
            rows_.append({'test': _MV_NAMES.get(idx, idx), 'value': float(row['Value']), 'f': float(row['F Value']), 'numdf': float(row['Num DF']),
                          'dendf': float(row['Den DF']), 'p': float(row['Pr > F'])})
        tests.append({'effect': nm, 'rows': rows_})
        Hs[nm] = np.asarray(res_[nm]['H'], dtype=float)
        E = np.asarray(res_[nm]['E'], dtype=float)
    labels = mnames if M is not None else ys
    sd = np.sqrt(np.diag(E))
    with np.errstate(invalid='ignore', divide='ignore'):
        pc = E / np.outer(sd, sd)
    uni = []
    for j, n0 in enumerate(ys):
        f = sm.OLS(Y[:, j], Xa).fit()
        rows_ = []
        for nm, L in hyps:
            if nm == 'Intercept':
                continue
            ft = f.f_test(L)
            q = int(np.linalg.matrix_rank(L))
            rows_.append({'source': nm, 'df': q, 'ss': float(np.squeeze(ft.fvalue)) * q * float(f.scale), 'f': float(np.squeeze(ft.fvalue)),
                          'p': float(np.squeeze(ft.pvalue))})
        uni.append({'y': n0, 'rows': rows_, 'rsq': float(f.rsquared), 'rmse': float(math.sqrt(f.scale))})
    lines = _code_frame(d, table, table_name, rows, [], ['import patsy', 'from statsmodels.multivariate.manova import MANOVA'])
    lines.append(f'X = patsy.dmatrix({json.dumps(_code_formula(d, lhs=False))}, d)   # the design, effect coded')
    lines.append(f'Y = d[{json.dumps(ys)}].to_numpy()')
    lines.append('L = np.eye(X.shape[1])[1:]   # the whole model; an effect: the rows of the columns of its terms')
    lines.append('print(MANOVA(Y, np.asarray(X)).mv_test(hypotheses=[("Whole Model", L)]))')
    return {'responses': ys, 'response': response, 'labels': labels, 'tests': tests, 'E': E, 'H': Hs, 'partial_corr': pc, 'univariate': uni,
            'n': int(len(d.df)), 'dfe': float(len(d.df) - np.linalg.matrix_rank(Xa)),
            'notes': [_MV_F_NOTE],
            'code': '\n'.join(lines)}


# ---------------------------------------------------------------------------
# Penalized Regression
# ---------------------------------------------------------------------------
# JMP Pro's Generalized Regression of a normal, binomial or Poisson response.
# Estimation Method: Lasso, Elastic Net, Ridge, Adaptive Lasso and Adaptive
# Elastic Net (penalized fits along a path of penalties), Forward Selection
# and Pruned Forward Selection (maximum likelihood fits of a growing set of
# terms). Validation Method, which picks the model on the path: AICc, BIC,
# KFold, Holdback, Leave-One-Out or a Validation column. The sets of a
# Validation column and of a holdback are predictive.prepare's, so the page's
# platforms agree on them; the KFold folds are drawn from the same seed.
#
# The predictors are centred and scaled by the weighted mean and SD of the
# rows that train the model (every row for KFold and Leave-One-Out); the
# intercept is not penalized. A penalized fit minimises the objective of
# statsmodels' fit_regularized,
#
#     -loglik / N + lambda * sum_j p_j (alpha |b_j| + (1 - alpha) b_j^2 / 2)
#
# (N the sum of the weights; for the normal -loglik is RSS / 2), p_j = 1, or
# 1 / |b_j| of an initial fit for the adaptive methods. It is solved as glmnet
# solves it (Friedman, Hastie and Tibshirani 2010): coordinate descent on the
# weighted least squares problem, inside Newton (IRLS) steps with step halving
# for the binomial and the Poisson, warm started along the path, every fold at
# once. statsmodels' own coordinate descent builds a model object for each
# coordinate of each sweep, too slow for the folds in the browser; scikit-learn
# has no penalty per term and no lasso for a Poisson response. The code under
# the report refits the chosen model with statsmodels' fit_regularized.

_GR_METHOD = {'lasso': 'Lasso', 'enet': 'Elastic Net', 'ridge': 'Ridge', 'forward': 'Forward Selection',
              'pruned': 'Pruned Forward Selection', 'mle': 'Maximum Likelihood'}
_GR_VALID = {'aicc': 'AICc', 'bic': 'BIC', 'kfold': 'KFold', 'holdback': 'Holdback', 'loo': 'Leave-One-Out',
             'validation': 'Validation Column'}
_GR_RIDGE0 = 0.01      # the ridge penalty of an adaptive method's initial fit when the MLE does not exist
_GR_ETA = 34.5         # |eta| of a binomial fit at most: probabilities stay 1e-15 from 0 and 1
_GR_LOO = {'normal': 1000, 'other': 300}   # rows Leave-One-Out takes (penalized normal; the rest)


def _gr_opts(spec):
    """What defines a Penalized Regression path (everything but the model
    chosen on it), as a plain dict: the key of the path's cache."""
    method = spec.get('method') if spec.get('method') in _GR_METHOD else 'lasso'
    crit = spec.get('criterion') if spec.get('criterion') in _GR_VALID else 'aicc'
    dist = spec.get('dist') if spec.get('dist') in ('normal', 'binomial', 'poisson') else 'normal'
    l1 = {'lasso': 1.0, 'ridge': 0.0}.get(method)
    if method == 'enet':
        l1 = float(spec['enet_alpha']) if spec.get('enet_alpha') not in (None, '') else 0.9
        if not 0 < l1 <= 1:
            raise ValueError('the Elastic Net Alpha is the lasso share of the penalty: above 0, at most 1')
    portion = folds = seed = None
    if crit == 'holdback':
        portion = float(spec['portion']) if spec.get('portion') not in (None, '') else 0.3
        if not 0 < portion < 1:
            raise ValueError('the Holdback Proportion is a share of the rows, between 0 and 1')
    if crit == 'kfold':
        folds = int(spec.get('folds') or 5)
    if crit in ('kfold', 'holdback'):
        seed = predictive.seed_of(spec.get('seed'))
        if seed is None:
            raise ValueError(f'{_GR_VALID[crit]} draws rows at random: it needs a random seed')
    return {'y': list(spec['y']), 'effects': spec['effects'], 'weight': spec.get('weight'), 'freq': spec.get('freq'), 'dist': dist,
            'target': spec.get('target'), 'method': method, 'l1': l1, 'adaptive': bool(spec.get('adaptive')) and method in ('lasso', 'enet'),
            'criterion': crit, 'validation': spec.get('validation') or None, 'portion': portion, 'folds': folds, 'seed': seed,
            'n_grid': int(spec.get('n_grid') or 40), 'center': spec.get('center', True)}


def _gr_label(O):
    """The method and the report's title, as JMP names them."""
    meth = ('Adaptive ' if O['adaptive'] else '') + _GR_METHOD[O['method']]
    v = _GR_VALID[O['criterion']]
    return meth, f'{meth} with {v}' if O['criterion'] == 'validation' else f'{meth} with {v} Validation'


def _gr_mu(dist, eta):
    if dist == 'binomial':
        return 1.0 / (1.0 + np.exp(-np.clip(eta, -_GR_ETA, _GR_ETA)))
    if dist == 'poisson':
        return np.exp(np.minimum(eta, 700.0))
    return eta


def _gr_var(dist, mu):
    if dist == 'binomial':
        return mu * (1.0 - mu)
    if dist == 'poisson':
        return mu
    return np.ones_like(mu)


def _gr_llc(dist, y, eta):
    """The part of a row's log-likelihood that depends on eta (binomial,
    Poisson): what the fits maximise."""
    if dist == 'binomial':
        e = np.clip(eta, -_GR_ETA, _GR_ETA)
        return y * e - np.logaddexp(0.0, e)
    e = np.minimum(eta, 700.0)
    return y * e - np.exp(e)


def _gr_ll(dist, y, eta, sigma2=None):
    """Each row's log-likelihood (weights not applied), with the constants of
    statsmodels' families; the normal's with the variance sigma2."""
    from scipy.special import gammaln
    if dist == 'normal':
        return -0.5 * (np.log(2 * np.pi * sigma2) + (y - eta) ** 2 / sigma2)
    if dist == 'binomial':
        return _gr_llc(dist, y, eta) - gammaln(y + 1) - gammaln(2 - y)
    return _gr_llc(dist, y, eta) - gammaln(y + 1)


def _gr_gram(W, Z, ZZ=None):
    """Z' diag(W_k) Z for each row W_k of W (K x n): K x p x p."""
    K, p = W.shape[0], Z.shape[1]
    if ZZ is not None:
        return (W @ ZZ).reshape(K, p, p)
    return np.stack([Z.T @ (Z * W[k][:, None]) for k in range(K)]) if K else np.zeros((0, p, p))


def _gr_zz(Z, K):
    """The rows' outer products (n x p^2), when there are many problems and they fit in memory."""
    n, p = Z.shape
    return (Z[:, :, None] * Z[:, None, :]).reshape(n, p * p) if K > 8 and n * p * p <= 4_000_000 else None


def _gr_cd(G, c, B, l1, l2, tol=1e-10, maxsweep=20000):
    """Coordinate descent for K problems at once: B_k minimises
    0.5 b'G_k b - c_k'b + sum_j l1_kj |b_j| + 0.5 sum_j l2_kj b_j^2
    (G: K x p x p, c and B: K x p; B is the start and is overwritten). A
    sweep over every coordinate, then sweeps over the nonzero ones until they
    settle, then a sweep over all again, as glmnet does."""
    K, p = c.shape
    if p == 0 or K == 0:
        return B
    l1 = np.broadcast_to(np.asarray(l1, dtype=float), (K, p))
    l2 = np.broadcast_to(np.asarray(l2, dtype=float), (K, p))
    if not np.any(l1):                      # ridge: a linear system
        return np.linalg.solve(G + l2[:, :, None] * np.eye(p)[None], c[:, :, None])[:, :, 0]
    dg = np.einsum('kjj->kj', G)
    den = dg + l2
    den = np.where(den > 1e-14, den, 1.0)   # a column constant in these rows stays at 0
    Q = np.einsum('kij,kj->ki', G, B)
    full, js = True, range(p)
    for _ in range(maxsweep):
        big = 0.0
        for j in js:
            bj = B[:, j]
            r = c[:, j] - Q[:, j] + dg[:, j] * bj
            nb = np.sign(r) * np.maximum(np.abs(r) - l1[:, j], 0.0) / den[:, j]
            dl = nb - bj
            m = float(np.max(np.abs(dl)))
            if m > 0.0:
                Q += dl[:, None] * G[:, :, j]
                B[:, j] = nb
                if m > big:
                    big = m
        if full:
            if big < tol:
                return B
            full, js = False, np.flatnonzero(np.any(B != 0, axis=0))
        elif big < tol:
            full, js = True, range(p)
    import warnings
    warnings.warn('Penalized Regression: coordinate descent stopped before it converged (highly correlated terms?)')
    return B


def _gr_normal_path(Z, y, w, M, lams, a1, pf):
    """Penalized least squares of the problems M (K x n: 1 for a training row)
    along the penalties lams: intercepts K x L and slopes K x L x p."""
    WM = M * w[None, :]
    N = WM.sum(1)
    m = (WM @ Z) / N[:, None]
    yb = (WM @ y) / N
    G = (_gr_gram(WM, Z, _gr_zz(Z, len(M))) - N[:, None, None] * m[:, :, None] * m[:, None, :]) / N[:, None, None]
    c = ((WM * y[None, :]) @ Z - N[:, None] * m * yb[:, None]) / N[:, None]
    K, p = c.shape
    B = np.zeros((K, p))
    out = np.zeros((K, len(lams), p))
    for l, lam in enumerate(lams):
        B = _gr_cd(G, c, B, lam * a1 * pf, lam * (1 - a1) * pf)
        out[:, l] = B
        _gr_progress(l + 1, len(lams), K)
    return yb[:, None] - np.einsum('kp,klp->kl', m, out), out


def _gr_progress(done, total, K):
    """A progress line for the page when the fits are many (Leave-One-Out)."""
    if K >= 50 and (done == total or done % max(1, total // 10) == 0):
        print(f'smui:progress penreg {done} {total}', flush=True)


def _gr_glm_path(Z, y, w, M, dist, lams, a1, pf, tol=1e-9, maxit=100):
    """Penalized binomial or Poisson fits of the problems M along lams: IRLS
    (Newton) steps, each a weighted least squares problem solved by coordinate
    descent, halved when the penalized objective does not fall."""
    K, n = M.shape
    p = Z.shape[1]
    WM = M * w[None, :]
    N = WM.sum(1)
    ZZ = _gr_zz(Z, K)
    ybar = np.clip((WM @ y) / N, 1e-10, 1 - 1e-10 if dist == 'binomial' else np.inf)
    b0 = np.log(ybar / (1 - ybar)) if dist == 'binomial' else np.log(ybar)
    B = np.zeros((K, p))
    out0, outB = np.zeros((K, len(lams))), np.zeros((K, len(lams), p))

    def objective(b0, B, p1, p2):
        eta = b0[:, None] + B @ Z.T
        return -np.sum(WM * _gr_llc(dist, y, eta), axis=1) / N + np.abs(B) @ p1 + 0.5 * (B * B) @ p2

    for l, lam in enumerate(lams):
        p1, p2 = lam * a1 * pf, lam * (1 - a1) * pf
        F = objective(b0, B, p1, p2)
        for _ in range(maxit):
            eta = b0[:, None] + B @ Z.T
            mu = _gr_mu(dist, eta)
            var = np.maximum(_gr_var(dist, mu), 1e-15)
            Wk = WM * var
            Wz = WM * (var * eta + (y[None, :] - mu))       # W times the working response
            sW = Wk.sum(1)
            m = (Wk @ Z) / sW[:, None]
            zb = Wz.sum(1) / sW
            G = (_gr_gram(Wk, Z, ZZ) - sW[:, None, None] * m[:, :, None] * m[:, None, :]) / N[:, None, None]
            c = (Wz @ Z - sW[:, None] * m * zb[:, None]) / N[:, None]
            Bn = _gr_cd(G, c, B.copy(), p1, p2)
            b0n = zb - np.sum(m * Bn, axis=1)
            Fn = objective(b0n, Bn, p1, p2)
            t = 1.0
            up = Fn > F + 1e-13 * np.abs(F)
            while up.any() and t > 1e-5:        # step halving where the objective rose
                t *= 0.5
                Bt, b0t = B + t * (Bn - B), b0 + t * (b0n - b0)
                Ft = objective(b0t, Bt, p1, p2)
                take = up & (Ft <= F + 1e-13 * np.abs(F))
                Bn[up], b0n[up], Fn[up] = Bt[up], b0t[up], Ft[up]
                up = up & ~take
            change = max(float(np.max(np.abs(Bn - B))) if p else 0.0, float(np.max(np.abs(b0n - b0))))
            B, b0, F = Bn, b0n, Fn
            if change < tol:
                break
        else:
            import warnings
            warnings.warn('Penalized Regression: the Newton steps of a penalized fit stopped before they converged')
        out0[:, l], outB[:, l] = b0, B
        _gr_progress(l + 1, len(lams), K)
    return out0, outB


def _gr_mle(A, y, w, dist, start=None, maxit=100):
    """The maximum likelihood fit of y on the columns of A (the first the
    intercept) with weights w: (coefficients, converged)."""
    if dist == 'normal':
        sw = np.sqrt(w)
        coef, _res, rank, _sv = np.linalg.lstsq(A * sw[:, None], y * sw, rcond=None)
        return coef, rank == A.shape[1]
    if start is None:
        start = np.zeros(A.shape[1])
        yb = min(max(float(np.average(y, weights=w)), 1e-10), 1 - 1e-10 if dist == 'binomial' else np.inf)
        start[0] = math.log(yb / (1 - yb)) if dist == 'binomial' else math.log(yb)
    coef = np.array(start, dtype=float)
    ll = float(np.sum(w * _gr_llc(dist, y, A @ coef)))
    for _ in range(maxit):
        mu = _gr_mu(dist, A @ coef)
        g = A.T @ (w * (y - mu))
        H = A.T @ (A * (w * np.maximum(_gr_var(dist, mu), 1e-15))[:, None])
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(H, g, rcond=None)[0]
        t = 1.0
        while True:
            new = coef + t * step
            ll_new = float(np.sum(w * _gr_llc(dist, y, A @ new)))
            if ll_new >= ll - 1e-12 * abs(ll) or t < 1e-6:
                break
            t *= 0.5
        small = float(np.max(np.abs(new - coef))) < 1e-9 * (1 + float(np.max(np.abs(coef))))
        coef, ll = new, ll_new
        if small:
            return coef, True
    return coef, False


def _gr_fitll(A, coef, y, w, dist):
    """The log-likelihood that ranks models of the same rows: -N/2 log(RSS/N)
    for the normal (the variance profiled out), else the fit's."""
    eta = A @ coef
    if dist == 'normal':
        rss = float(np.sum(w * (y - eta) ** 2))
        return -0.5 * float(np.sum(w)) * math.log(max(rss, 1e-300) / float(np.sum(w)))
    return float(np.sum(w * _gr_llc(dist, y, eta)))


def _gr_forward(Z, y, w, dist, pruned, kmax):
    """Forward Selection on these rows: the term with the largest score
    statistic enters, one at a time (for the normal the largest drop in the
    error sum of squares). Pruned: after each entry, terms leave while the
    model without one (the one with the smallest Wald statistic, never the
    term just entered) beats every model of that size seen so far (Pudil's
    floating search). Returns the steps: [(active columns, coefficients)]."""
    n, p = Z.shape
    one = np.ones((n, 1))
    active = []
    coef = _gr_mle(one, y, w, dist)[0]
    steps = [([], coef.copy())]
    best = {0: _gr_fitll(one, coef, y, w, dist)}
    dead = set()
    for _guard in range(4 * p + 10):
        if len(active) >= kmax:
            break
        A = np.column_stack([one, Z[:, active]])
        mu = _gr_mu(dist, A @ coef)
        wv = w * _gr_var(dist, mu)
        cand = [j for j in range(p) if j not in active and j not in dead]
        if not cand:
            break
        C = Z[:, cand]
        Iss = A.T @ (A * wv[:, None])
        Isc = A.T @ (C * wv[:, None])
        Icc = np.einsum('ij,ij,i->j', C, C, wv)
        eff = Icc - np.sum(Isc * np.linalg.lstsq(Iss, Isc, rcond=None)[0], axis=0)
        ok = eff > 1e-9 * np.maximum(Icc, 1e-300)
        dead.update(j for j, o in zip(cand, ok) if not o)
        if not ok.any():
            break
        U = C.T @ (w * (y - mu))
        stat = np.where(ok, U * U / np.where(ok, eff, 1.0), -np.inf)
        last = cand[int(np.argmax(stat))]
        active.append(last)
        A = np.column_stack([one, Z[:, active]])
        coef = _gr_mle(A, y, w, dist, start=np.r_[coef, 0.0])[0]
        steps.append((list(active), coef.copy()))
        best[len(active)] = max(best.get(len(active), -np.inf), _gr_fitll(A, coef, y, w, dist))
        while pruned and len(active) >= 2:
            mu = _gr_mu(dist, A @ coef)
            H = A.T @ (A * (w * np.maximum(_gr_var(dist, mu), 1e-15))[:, None])
            z2 = coef[1:] ** 2 / np.maximum(np.diag(np.linalg.pinv(H))[1:], 1e-300)
            z2[active.index(last)] = np.inf
            i = int(np.argmin(z2))
            red = active[:i] + active[i + 1:]
            Ar = np.column_stack([one, Z[:, red]])
            cr = _gr_mle(Ar, y, w, dist, start=np.r_[coef[:i + 1], coef[i + 2:]])[0]
            llr = _gr_fitll(Ar, cr, y, w, dist)
            if llr <= best.get(len(red), -np.inf) + 1e-9 * (1 + abs(llr)):
                break
            active, A, coef = red, Ar, cr
            best[len(red)] = llr
            steps.append((list(active), coef.copy()))
    return steps


def _gr_steps_matrix(steps, p):
    """Forward steps as coefficient rows over [intercept, every column]."""
    out = np.zeros((len(steps), p + 1))
    for s, (act, coef) in enumerate(steps):
        out[s, 0] = coef[0]
        out[s, 1 + np.asarray(act, dtype=int)] = coef[1:]
    return out


def _gr_setup(tid, rows, O):
    """The design and data of a fit: the rows, y, the weights, the sets
    (0 training, 1 validation, 2 test) and folds, and the centred and scaled
    predictors."""
    ys = O['y']
    if not ys:
        raise ValueError('choose a Y')
    dist, crit, vcol = O['dist'], O['criterion'], O['validation']
    effs = _eff_of(O)
    if vcol and (vcol in ys or any(vcol in e['cols'] for e in effs)):
        raise ValueError(f'{vcol} is the Validation column: it cannot also be the Y or in a model effect')
    d = _design(tid, ys[0], effs, rows, O['weight'], O['freq'], True, extra=[vcol] if vcol else (), center=O.get('center', True))
    info = {}
    yv = d.df[d.y_alias]
    if isinstance(yv.dtype, pd.CategoricalDtype):
        lv = [c for c in yv.cat.categories if (yv == c).any()]
        if len(lv) != 2:
            raise ValueError(f'{ys[0]} is categorical: Penalized Regression here takes a continuous Y or a two-level one (binomial)')
        dist = 'binomial'
        t = _level_index(lv, O['target']) if O['target'] is not None else 0
        info['levels'] = [lv[t], lv[1 - t]]
        y = (yv == lv[t]).to_numpy(float)
    else:
        y = yv.to_numpy(float)
        if dist == 'binomial' and (np.any(y < 0) or np.any(y > 1)):
            raise ValueError('a binomial Y must lie between 0 and 1')
        if dist == 'poisson' and np.any(y < 0):
            raise ValueError('a Poisson Y must be zero or above')
    X = _matrix(d)
    names = list(X.columns)
    Xa = X.to_numpy(float)
    w = d.weights if d.weights is not None else np.ones(len(y))
    n = len(y)
    ic = names.index('Intercept')
    cols = [j for j in range(len(names)) if j != ic]
    # the sets
    if vcol and crit in ('kfold', 'holdback', 'loo'):
        raise ValueError(f'with a Validation column ({vcol}) the fit is validated by it: choose Validation Column, AICc or BIC '
                         '(or take the column out of the Validation role); a column of more than three values gives KFold\'s folds')
    if crit == 'validation' and not vcol:
        raise ValueError('Validation Column needs a column in the Validation role of the launch dialog (Model Dialog)')
    sets = np.zeros(n, dtype=int)
    pnotes = []
    if vcol or crit == 'holdback':
        xcols = list(dict.fromkeys(c for e in effs for c in e['cols']))
        P = predictive.prepare(tid, ys[0], xcols, rows, O['weight'], O['freq'], validation=vcol,
                               portion=O['portion'] or 0, seed=O['seed'], missing='drop')
        if len(P.index) != n or not np.array_equal(P.index, np.asarray(d.df.index)):   # the same rows, in the same order (a resample repeats some)
            raise ValueError('the rows of the validation sets are not the rows of the model (an infinite value in a column?)')
        sets = P.sets.astype(int)
        pnotes = list(P.notes)
        if P.folds is not None:   # a K-fold Validation column (WP3's predictive.prepare): every row trains, its folds crossvalidate
            info['fold_column'] = {'column': vcol, 'values': list(P.fold_values), 'folds': P.folds.astype(int)}
        elif crit in ('validation', 'holdback') and not (sets == 1).any():
            raise ValueError(f'{vcol} has no validation rows (1 or Validation)' if vcol else 'the Holdback Proportion leaves no validation rows')
    folds = None
    eff = crit   # the validation the path uses: KFold by the column's folds for a K-fold Validation column
    if info.get('fold_column') and crit == 'validation':
        folds = info['fold_column']['folds']
        eff = 'kfold'
    elif crit == 'kfold':
        K = O['folds']
        if not 2 <= K <= n:
            raise ValueError(f'KFold needs between 2 and {n} folds (the number of rows)')
        folds = np.empty(n, dtype=int)
        folds[np.random.default_rng(O['seed']).permutation(n)] = np.arange(n) % K
    elif crit == 'loo':
        cap = _GR_LOO['normal' if dist == 'normal' and O['method'] not in ('forward', 'pruned') else 'other']
        if n > cap:
            raise ValueError(f'Leave-One-Out refits the model once for each row: it takes up to {cap} rows here, and these are {n}. Use KFold.')
        folds = np.arange(n)
    tr = sets == 0
    Xc = Xa[:, cols]
    mu_ = np.average(Xc[tr], axis=0, weights=w[tr]) if cols else np.zeros(0)
    sd_ = np.sqrt(np.average((Xc[tr] - mu_) ** 2, axis=0, weights=w[tr])) if cols else np.zeros(0)
    live = sd_ > 1e-12
    sd_[~live] = 1.0
    Z = (Xc - mu_) / sd_
    return {'d': d, 'X': X, 'names': names, 'Xa': Xa, 'y': y, 'w': w, 'n': n, 'ic': ic, 'cols': cols, 'dist': dist, 'info': info,
            'sets': sets, 'folds': folds, 'mu': mu_, 'sd': sd_, 'live': live, 'Zl': Z[:, live], 'notes': pnotes, 'crit': eff}


def _gr_adaptive(S, rows):
    """The adaptive methods' penalty factors 1/|b_j|, b the maximum likelihood
    estimates on the scaled predictors (least squares for the normal); when
    they do not exist (more terms than rows, a singular design, separation)
    the ridge estimates at a small penalty. Returns (factors, source)."""
    Zt, yt, wt = S['Zl'][rows], S['y'][rows], S['w'][rows]
    p = Zt.shape[1]
    A = np.column_stack([np.ones(len(yt)), Zt])
    b, ok = _gr_mle(A, yt, wt, S['dist'])
    if ok and len(yt) > p + 1 and np.all(np.isfinite(b)) and (S['dist'] == 'normal' or np.max(np.abs(b[1:]), initial=0) < 30):
        src = 'mle'
        b = b[1:]
    else:
        src = 'ridge'
        M = rows[None, :].astype(float)
        one = np.ones(p)
        if S['dist'] == 'normal':
            B = _gr_normal_path(S['Zl'], S['y'], S['w'], M, [_GR_RIDGE0], 0.0, one)[1]
        else:
            B = _gr_glm_path(S['Zl'], S['y'], S['w'], M, S['dist'], [_GR_RIDGE0], 0.0, one)[1]
        b = B[0, 0]
    return 1.0 / np.maximum(np.abs(b), 1e-8), src


def _gr_eval(S, M, V, b0, B, dist):
    """The validation -loglik of each problem k (rows V_k) at each step l of
    its path, and each problem's validation weight: (K x L, K). The normal's
    variance is the training rows' mean squared error."""
    Z, y, w = S['Zl'], S['y'], S['w']
    WM, WV = M * w[None, :], V * w[None, :]
    K, L = b0.shape
    out = np.zeros((K, L))
    for l in range(L):
        eta = b0[:, l, None] + B[:, l] @ Z.T
        if dist == 'normal':
            e2 = (y[None, :] - eta) ** 2
            s2 = np.maximum(np.sum(WM * e2, axis=1) / WM.sum(1), 1e-300)
            out[:, l] = 0.5 * np.sum(WV * (np.log(2 * np.pi * s2)[:, None] + e2 / s2[:, None]), axis=1)
        else:
            out[:, l] = -np.sum(WV * _gr_ll(dist, y[None, :], eta), axis=1)
    return out, WV.sum(1)


def _gr_train(S, rows, coef, dist, lam=None, a1=1.0, pf=None, nterms=None):
    """A model's fit on its training rows: -loglik, the degrees of freedom
    (the number of nonzero terms, for the elastic net and ridge the trace of
    the ridge hat matrix on them), AICc and BIC. coef: [intercept, the live
    columns], on the scaled predictors."""
    Z, y, w = S['Zl'][rows], S['y'][rows], S['w'][rows]
    N = float(np.sum(w))
    eta = coef[0] + Z @ coef[1:]
    if dist == 'normal':
        rss = float(np.sum(w * (y - eta) ** 2))
        ll = -0.5 * N * (math.log(2 * math.pi * rss / N) + 1) if rss > 0 else float('inf')
        W = w
    else:
        ll = float(np.sum(w * _gr_ll(dist, y, eta)))
        W = w * _gr_var(dist, _gr_mu(dist, eta))
    act = np.flatnonzero(np.abs(coef[1:]) > 1e-8)   # statsmodels' fit_regularized zeroes what is smaller
    if lam is None or a1 >= 1 or not len(act):
        df = float(len(act) + 1)
    else:
        Za = Z[:, act]
        Mx = Za.T @ (Za * W[:, None])
        v = np.ones(len(act)) if pf is None else pf[act]
        df = float(np.trace(np.linalg.solve(Mx + N * lam * (1 - a1) * np.diag(v), Mx))) + 1
    k = df + (1 if dist == 'normal' else 0)
    aicc = -2 * ll + 2 * k + (2 * k * (k + 1) / (N - k - 1) if N - k - 1 > 0 else float('nan'))
    return {'ll': ll, 'df': df, 'aicc': aicc, 'bic': -2 * ll + k * math.log(N), 'N': N, 'nonzero': int(len(act))}


def _penreg_path(tid, rows, spec):
    """The path of a fit and the validation that picks a model on it
    (remembered: choosing another model on the path does not refit)."""
    O = _gr_opts(spec)
    key = _key('penreg-path', tid, rows, O)
    R = models.recall(key)
    if R is not None:
        return R
    S = _gr_setup(tid, rows, O)
    dist, crit, method = S['dist'], S['crit'], O['method']
    Z, y, w = S['Zl'], S['y'], S['w']
    n, p = Z.shape
    tr = S['sets'] == 0
    if crit in ('kfold', 'loo'):
        K = int(S['folds'].max()) + 1
        M = (S['folds'][None, :] != np.arange(K)[:, None]).astype(float)
    else:
        K = 1
        M = tr[None, :].astype(float)
    V = (1.0 - M) if crit in ('kfold', 'loo') else (S['sets'] == 1)[None, :].astype(float)
    mle = method == 'mle'
    forward = method in ('forward', 'pruned') or mle   # Maximum Likelihood: one step that holds every term
    lams, a1, pf, pf_from = None, None, None, None
    if mle:
        A = np.column_stack([np.ones(n), Z])
        C = np.zeros((K, 1, p + 1))
        for k in range(K):
            r = M[k] > 0
            C[k, 0], ok_ = _gr_mle(A[r], y[r], w[r], dist)
            if not ok_:
                S['notes'].append('The maximum likelihood fit did not converge on some rows (separation, or more terms than rows?): its estimates '
                                  'are where it stopped.')
            _gr_progress(k + 1, K, K)
        b0, B = C[:, :, 0], C[:, :, 1:]
        L = 1
    elif forward:
        paths = []
        for k in range(K):
            r = M[k] > 0
            kmax = min(p, int(r.sum()) - (3 if dist == 'normal' else 2))
            paths.append(_gr_forward(Z[r], y[r], w[r], dist, method == 'pruned', max(kmax, 0)))
            _gr_progress(k + 1, K, K)
        L = max(len(s) for s in paths)
        C = np.stack([np.vstack([m_, np.repeat(m_[-1:], L - len(m_), axis=0)]) for m_ in (_gr_steps_matrix(s, p) for s in paths)])
        b0, B = C[:, :, 0], C[:, :, 1:]
    else:
        a1 = O['l1']
        pf = np.ones(p)
        if O['adaptive']:
            pf, pf_from = _gr_adaptive(S, tr)
        Nm = float(np.sum(w[tr]))
        grad = np.abs(Z[tr].T @ (w[tr] * (y[tr] - np.average(y[tr], weights=w[tr])))) / Nm / pf if p else np.zeros(1)
        amax = float(np.max(grad)) / max(a1, 1e-3) if p and np.max(grad) > 0 else 1.0
        lams = amax * (np.logspace(0, -4, O['n_grid']) if a1 > 0 else np.logspace(1, -5, O['n_grid']))
        if dist == 'normal':
            b0, B = _gr_normal_path(Z, y, w, M, lams, a1, pf)
        else:
            b0, B = _gr_glm_path(Z, y, w, M, dist, lams, a1, pf)
        L = len(lams)
    # the curve that picks the model, and the problem whose model is shown
    scaled = shown = None
    if crit not in ('aicc', 'bic'):
        nll, nv = _gr_eval(S, M, V, b0, B, dist)
        scaled = nll / np.maximum(nv, 1e-300)[:, None]
    if crit in ('aicc', 'bic'):
        rows0 = M[0] > 0
        shown = [_gr_train(S, rows0, np.r_[b0[0, l], B[0, l]], dist, None if forward else lams[l], a1 if a1 is not None else 1.0, pf) for l in range(L)]
        curve = np.array([s[crit] for s in shown], dtype=float)
    else:
        curve = scaled.mean(axis=0) if crit in ('kfold', 'loo') else scaled[0]
    finite = np.where(np.isfinite(curve), curve, np.inf)
    best = int(np.argmin(finite))
    fstar = int(np.argmin(np.where(np.isfinite(scaled[:, best]), scaled[:, best], np.inf))) if crit in ('kfold', 'loo') else 0
    rows_k = M[fstar] > 0
    if shown is None:
        shown = [_gr_train(S, rows_k, np.r_[b0[fstar, l], B[fstar, l]], dist, None if forward else lams[l], a1 if a1 is not None else 1.0, pf) for l in range(L)]
    coefs = np.column_stack([b0[fstar], B[fstar]])
    R = {'S': S, 'O': O, 'lams': lams, 'l1': a1, 'pf': pf, 'pf_from': pf_from, 'coefs': coefs, 'curve': curve, 'best': best, 'fstar': fstar,
         'K': K, 'train': rows_k, 'valid': V[fstar] > 0, 'shown': shown, 'forward': forward, 'mle': mle, 'crit': crit}
    models.remember(key, R)
    return R


def _penreg_model(tid, rows, spec):
    """The model chosen on the path (the best, or the one the page chose),
    in the form the profilers take."""
    key = _key('penreg', tid, rows, spec)
    m = models.recall(key)
    if m is not None:
        return m
    R = _penreg_path(tid, rows, spec)
    S = R['S']
    d, names, cols, ic, live = S['d'], S['names'], S['cols'], S['ic'], S['live']
    L = len(R['coefs'])
    chosen = R['best'] if spec.get('choose') is None else min(max(int(spec['choose']), 0), L - 1)
    c = np.zeros(1 + len(cols))                  # [intercept, every column] on the scaled predictors
    c[0] = R['coefs'][chosen, 0]
    c[1:][live] = R['coefs'][chosen, 1:]
    mu_, sd_ = S['mu'], S['sd']
    borig = np.zeros(len(names))
    borig[cols] = c[1:] / sd_
    borig[ic] = c[0] - float(np.sum(c[1:] * mu_ / sd_))
    bjmp = borig.copy()   # borig is on the design as fitted (a centred main effect: the intercept at its mean)
    for t, mean in getattr(d, 'centered_main', {}).items():
        if t in names:
            bjmp[ic] -= mean * borig[names.index(t)]
    sets = np.where(R['train'], 0, np.where(R['valid'], 1, np.where(S['sets'] == 2, 2, -1)))
    m = {'kind': 'penreg', 'd': d, 'X': S['X'], 'names': names, 'path': R, 'best': R['best'], 'chosen': chosen, 'b': borig, 'b_jmp': bjmp,
         'scaled': c, 'mu': mu_, 'sd': sd_, 'cols': cols, 'dist': S['dist'], 'info': S['info'], 'y': S['y'], 'w': S['w'],
         'sets': sets, 'coder': Coder(d, S['X'].design_info), 'key': key, 'spec': spec, 'tid': tid}
    models.remember(key, m)
    return m


def _penreg_predict(m, settings, alpha):
    L = m['coder'].rows(settings)
    eta = L @ m['b']
    pred = _gr_mu(m['dist'], eta)
    name = m['spec']['y'][0] if not m['info'].get('levels') else f'Prob[{_lvl(m["info"]["levels"][0])}]'
    return [{'name': name, 'pred': pred, 'lower': None, 'upper': None, 'bounded': m['dist'] == 'binomial'}]


def _gr_sets_stats(m):
    """The Model Summary's measures for each set of the chosen model:
    -LogLikelihood (the normal's variance from the training rows), Scaled
    -LogLikelihood (per unit of weight), Generalized RSquare (against the
    training mean), RASE; the fit's own on the training rows."""
    S = m['path']['S']
    dist, y, w, sets = S['dist'], S['y'], S['w'], m['sets']
    eta = m['X'].to_numpy(float) @ m['b']
    mu = _gr_mu(dist, eta)
    tr = sets == 0
    Ntr = float(np.sum(w[tr]))
    s2 = float(np.sum(w[tr] * (y[tr] - eta[tr]) ** 2)) / Ntr if dist == 'normal' else None
    ybar = float(np.average(y[tr], weights=w[tr]))
    s02 = float(np.sum(w[tr] * (y[tr] - ybar) ** 2)) / Ntr if dist == 'normal' else None
    if dist == 'binomial':
        eta0 = math.log(min(max(ybar, 1e-15), 1 - 1e-15) / (1 - min(max(ybar, 1e-15), 1 - 1e-15)))
    elif dist == 'poisson':
        eta0 = math.log(max(ybar, 1e-300))
    else:
        eta0 = ybar
    out = []
    for k, name in enumerate(predictive.SETS):
        r = sets == k
        if not r.any():
            continue
        N = float(np.sum(w[r]))
        ll = float(np.sum(w[r] * _gr_ll(dist, y[r], eta[r], s2)))
        ll0 = float(np.sum(w[r] * _gr_ll(dist, y[r], np.full(int(r.sum()), eta0), s02)))
        if dist == 'normal':
            gr = 1 - math.exp(2 * (ll0 - ll) / N)
        else:
            den = 1 - math.exp(2 * ll0 / N)
            gr = (1 - math.exp(2 * (ll0 - ll) / N)) / den if den > 0 else None
        out.append({'set': name, 'rows': int(r.sum()), 'n': N, 'nll': -ll, 'scaled': -ll / N, 'grsq': gr,
                    'rase': math.sqrt(float(np.sum(w[r] * (y[r] - mu[r]) ** 2)) / N)})
    return out


def _gr_code(m, table, table_name, rows):
    """The Python under the report: the sets and the scaled design as the
    report builds them, the chosen model refitted with statsmodels, its
    criterion or validation curve, and the Model Summary's -LogLikelihood."""
    R, S = m['path'], m['path']['S']
    O, d, dist = R['O'], m['d'], S['dist']
    vcol, crit, forward = O['validation'], R.get('crit', O['criterion']), R['forward']
    fcol = S['info'].get('fold_column')
    live = S['live']
    lines = _code_frame(d, table, table_name, rows, [O['weight'], O['freq'], vcol], ['import patsy', 'from scipy.special import gammaln'])
    lines.append(f'X = np.asarray(patsy.dmatrix({json.dumps(_code_formula(d, lhs=False))}, d))   # the design, effect coded')
    if S['info'].get('levels'):
        lv0 = S['info']['levels'][0]
        lines.append(f'y = (d[{json.dumps(O["y"][0])}] == {json.dumps(lv0 if isinstance(lv0, str) else float(lv0))}).to_numpy(float)   # the target level')
    else:
        lines.append(f'y = d[{json.dumps(O["y"][0])}].to_numpy(float)')
    wp = [f'd[{json.dumps(c)}].to_numpy(float)' for c in (O['weight'], O['freq']) if c]
    lines.append(f'w = {" * ".join(wp)}' if wp else 'w = np.ones(len(d))   # every row counts once')
    n = S['n']
    if vcol and fcol:   # a K-fold Validation column: its values are the folds, every row trains
        numeric = data.meta(table, vcol).get('dataType') == 'numeric'
        lines.append(f'fold_values = {json.dumps(fcol["values"])}   # the folds of {vcol}, in order')
        src = f'pd.to_numeric(d[{json.dumps(vcol)}], errors="coerce")' if numeric else f'd[{json.dumps(vcol)}].astype(str)'
        lines.append(f'fold = pd.Categorical({src}, categories=fold_values).codes   # each row\'s fold, 0 to {len(fcol["values"]) - 1}')
        lines.append('sets = np.zeros(len(d), dtype=int)   # every row trains; the folds crossvalidate')
    elif vcol:
        if data.meta(table, vcol).get('dataType') == 'numeric':
            lines.append(f'sets = d[{json.dumps(vcol)}].astype(float).to_numpy().astype(int)   # 0 training, 1 validation, 2 test')
        else:
            lines.append(f'names = {json.dumps(predictive._SET_NAMES)}')
            lines.append(f'sets = d[{json.dumps(vcol)}].astype(str).str.strip().str.lower().map(names).to_numpy(int)   # 0 training, 1 validation, 2 test')
    elif crit == 'holdback':
        lines.append(f'rng = np.random.default_rng({O["seed"]})   # the holdback, drawn as the page draws a Validation Portion')
        lines.append(f'sets = np.zeros(len(d), dtype=int); sets[rng.permutation(len(d))[:{int(round(O["portion"] * n))}]] = 1')
    elif crit == 'kfold':
        lines.append(f'fold = np.empty(len(d), dtype=int); fold[np.random.default_rng({O["seed"]}).permutation(len(d))] = np.arange(len(d)) % {O["folds"]}   # the folds')
    elif crit == 'loo':
        lines.append('fold = np.arange(len(d))   # Leave-One-Out: a fold per row')
    else:
        lines.append('sets = np.zeros(len(d), dtype=int)   # every row trains the model')
    if crit in ('kfold', 'loo'):
        lines.append('s = np.ones(len(d), dtype=bool)   # every row scales the predictors')
    else:
        lines.append('s = sets == 0   # the training rows scale the predictors')
    lines.append('m = np.average(X[s, 1:], axis=0, weights=w[s]); sd = np.sqrt(np.average((X[s, 1:] - m) ** 2, axis=0, weights=w[s]))')
    lines.append('sd[sd <= 1e-12] = 1.0')
    lines.append('Z = np.column_stack([np.ones(len(X)), (X[:, 1:] - m) / sd])   # centred and scaled; the intercept first')
    fam = {'binomial': 'sm.families.Binomial()', 'poisson': 'sm.families.Poisson()'}.get(dist)
    # the fit on some rows, the -loglik of rows under a fit on others
    if forward:
        if fam:
            lines.append(f'fit_on = lambda rows, cols: sm.GLM(y[rows], Z[rows][:, [0] + cols], family={fam}, var_weights=w[rows]).fit()   # maximum likelihood on those columns')
        else:
            lines.append('fit_on = lambda rows, cols: sm.WLS(y[rows], Z[rows][:, [0] + cols], weights=w[rows]).fit()   # least squares on those columns')
        lines.append('eta = lambda f, cols: Z[:, [0] + cols] @ f.params')
    else:
        a1 = R['l1']
        if O['adaptive']:
            if R['pf_from'] == 'mle':
                init = (f'sm.GLM(y[s], Z[s], family={fam}, var_weights=w[s]).fit()' if fam else 'sm.WLS(y[s], Z[s], weights=w[s]).fit()')
                lines.append(f'b0 = {init}.params[1:]   # the initial fit: maximum likelihood')
            else:
                init = (f'sm.GLM(y[s], Z[s], family={fam}, var_weights=w[s]).fit_regularized(method="elastic_net", alpha=np.r_[0, np.full(Z.shape[1] - 1, {_GR_RIDGE0})] * w[s].sum() / s.sum(), L1_wt=0)'
                        if fam else f'sm.WLS(y[s], Z[s], weights=w[s]).fit_regularized(method="elastic_net", alpha=np.r_[0, np.full(Z.shape[1] - 1, {_GR_RIDGE0})], L1_wt=0)')
                lines.append(f'b0 = {init}.params[1:]   # the initial fit: ridge (the maximum likelihood estimates do not exist here)')
            lines.append('pf = 1 / np.maximum(np.abs(b0), 1e-8)   # the adaptive penalty of each term')
        else:
            lines.append('pf = np.ones(Z.shape[1] - 1)   # the same penalty for every term')
        lines.append(f'L1 = {a1!r}   # the lasso share of the penalty')
        lines.append('def fit_at(rows, lam, start=None):')
        if fam:
            lines.append('    """The penalized fit on these rows (statsmodels scales the GLM\'s loss by the rows, the report by their weight)."""')
            lines.append(f'    return sm.GLM(y[rows], Z[rows], family={fam}, var_weights=w[rows]).fit_regularized(method="elastic_net", alpha=np.r_[0, lam * pf] * w[rows].sum() / rows.sum(),')
        else:
            lines.append('    """The penalized fit on these rows."""')
            lines.append('    return sm.WLS(y[rows], Z[rows], weights=w[rows]).fit_regularized(method="elastic_net", alpha=np.r_[0, lam * pf],')
        lines.append('                                         L1_wt=L1, start_params=start, maxiter=1000, cnvrg_tol=1e-12)')
        lines.append('def path(rows):')
        lines.append('    """The fits along the penalties, each started at the one before: statsmodels\' coordinate descent keeps a')
        lines.append('    coefficient that is zero after its second sweep at zero, so a fit started at zero can stop short."""')
        lines.append('    fits = []')
        lines.append('    for lam in lams:')
        lines.append('        fits.append(fit_at(rows, lam, fits[-1].params if fits else None))')
        lines.append('    return fits')
        lines.append('eta = lambda f: Z @ f.params')
        if crit in ('aicc', 'bic'):
            if (a1 or 0) >= 1:
                lines.append('df = lambda f, lam: np.sum(np.abs(f.params[1:]) > 1e-8) + 1   # the lasso\'s degrees of freedom: its nonzero terms and the intercept')
            else:
                lines.append('def df(f, lam, rows=None):')
                lines.append('    """The degrees of freedom: the trace of the ridge hat matrix on the nonzero terms, and the intercept."""')
                lines.append('    rows = train if rows is None else rows')
                lines.append('    a = np.flatnonzero(np.abs(f.params[1:]) > 1e-8) + 1')
                lines.append('    if not len(a): return 1.0')
                lines.append('    e_ = Z[rows] @ f.params')
                if dist == 'binomial':
                    lines.append(f'    p = 1 / (1 + np.exp(-np.clip(e_, -{_GR_ETA}, {_GR_ETA}))); v = w[rows] * p * (1 - p)')
                elif dist == 'poisson':
                    lines.append('    v = w[rows] * np.exp(e_)')
                else:
                    lines.append('    v = w[rows]')
                lines.append('    Za = Z[rows][:, a]; M = Za.T @ (Za * v[:, None])')
                lines.append('    return np.trace(np.linalg.solve(M + w[rows].sum() * lam * (1 - L1) * np.diag(pf[a - 1]), M)) + 1')
        lines.append('s0 = s & (w > 0)')
        lines.append('grad = np.abs(Z[s0, 1:].T @ (w[s0] * (y[s0] - np.average(y[s0], weights=w[s0])))) / w[s0].sum() / pf')
        grid = 'np.logspace(0, -4, ' if (a1 or 0) > 0 else 'np.logspace(1, -5, '
        lines.append(f'lams = grad.max() / max(L1, 1e-3) * {grid}{len(R["lams"])})   # the path, from the penalty that keeps every term out')
    if dist == 'normal':
        lines.append('def nll(e, train, rows):')
        lines.append('    """-LogLikelihood of rows, the variance the training rows\' mean squared error."""')
        lines.append('    s2 = np.sum(w[train] * (y[train] - e[train]) ** 2) / w[train].sum()')
        lines.append('    return 0.5 * np.sum(w[rows] * (np.log(2 * np.pi * s2) + (y[rows] - e[rows]) ** 2 / s2))')
    elif dist == 'binomial':
        lines.append('def nll(e, train, rows):')
        lines.append(f'    p = 1 / (1 + np.exp(-np.clip(e[rows], -{_GR_ETA}, {_GR_ETA})))')
        lines.append('    return -np.sum(w[rows] * (y[rows] * np.log(p) + (1 - y[rows]) * np.log(1 - p) - gammaln(y[rows] + 1) - gammaln(2 - y[rows])))')
    else:
        lines.append('def nll(e, train, rows):')
        lines.append('    return -np.sum(w[rows] * (y[rows] * e[rows] - np.exp(e[rows]) - gammaln(y[rows] + 1)))')
    ch = m['chosen']
    steps = None
    if forward:
        live_idx = np.flatnonzero(live)
        path_cols = [[int(live_idx[j]) + 1 for j in np.flatnonzero(np.abs(R['coefs'][s_, 1:]) > 0)] for s_ in range(len(R['coefs']))]
        steps = [sorted(c_) for c_ in path_cols]
    # the curve and the final model
    if crit in ('aicc', 'bic'):
        lines.append('train = sets == 0')
        lines.append('def criterion(e, k):')
        lines.append(f'    """{"AICc" if crit == "aicc" else "BIC"} of a fit with k nonzero parameters (the report\'s Number of Parameters){", plus the variance" if dist == "normal" else ""}."""')
        lines.append(f'    N = w[train].sum(); ll = -nll(e, train, train); k = k{" + 1" if dist == "normal" else ""}')
        lines.append('    return -2 * ll + 2 * k + 2 * k * (k + 1) / (N - k - 1)' if crit == 'aicc' else '    return -2 * ll + k * np.log(N)')
        if forward:
            lines.append(f'steps = {json.dumps(steps)}   # the columns of Z each step holds')
            lines.append('curve = [criterion(eta(fit_on(train, c), c), len(c) + 1) for c in steps]')
            lines.append(f'chosen = {ch}   # the report\'s: the smallest (np.argmin(curve)), or the one chosen on the plot')
            lines.append('fit = fit_on(train, steps[chosen])')
        else:
            lines.append('fits = path(train)')
            lines.append('curve = [criterion(eta(f), df(f, lam)) for f, lam in zip(fits, lams)]')
            lines.append(f'chosen = {ch}   # the report\'s: the smallest (np.argmin(curve)), or the one chosen on the plot')
            lines.append('fit = fits[chosen]')
        lines.append('valid = np.zeros(len(d), dtype=bool)' if not vcol else 'valid = sets == 1')
    elif crit in ('holdback', 'validation'):
        lines.append('train, valid = sets == 0, sets == 1')
        if forward:
            lines.append(f'steps = {json.dumps(steps)}   # the columns of Z each step holds')
            lines.append('curve = [nll(eta(f, c), train, valid) / w[valid].sum() for c, f in ((c, fit_on(train, c)) for c in steps)]   # Scaled -LogLikelihood of the validation rows')
            lines.append(f'chosen = {ch}   # the report\'s: the smallest (np.argmin(curve)), or the one chosen on the plot')
            lines.append('fit = fit_on(train, steps[chosen])')
        else:
            lines.append('fits = path(train)')
            lines.append('curve = [nll(eta(f), train, valid) / w[valid].sum() for f in fits]   # Scaled -LogLikelihood of the validation rows')
            lines.append(f'chosen = {ch}   # the report\'s: the smallest (np.argmin(curve)), or the one chosen on the plot')
            lines.append('fit = fits[chosen]')
    else:
        f = R['fstar']
        if forward:
            fcols = steps[ch]
            lines.append(f'train, valid = fold != {f}, fold == {f}   # the final model\'s fold: the Validation set')
            lines.append(f'chosen, cols = {ch}, {json.dumps(fcols)}   # the report\'s step, and the columns of Z it holds in that fold')
            lines.append('fit = fit_on(train, cols)')
        elif crit == 'kfold':
            K = R['K']
            lines.append(f'paths = [path(fold != k) for k in range({K})]   # every fold\'s path')
            lines.append(f'curve = [np.mean([nll(eta(paths[k][l]), fold != k, fold == k) / w[fold == k].sum() for k in range({K})]) for l in range(len(lams))]')
            lines.append(f'best = {R["best"]}   # np.argmin(curve): the mean Scaled -LogLikelihood of the folds')
            lines.append(f'scores = [nll(eta(paths[k][best]), fold != k, fold == k) / w[fold == k].sum() for k in range({K})]')
            lines.append(f'f = {f}   # np.argmin(scores): as JMP, the final model is the fold model that validates best at that penalty')
            lines.append(f'chosen = {ch}   # the report\'s penalty: the best, or the one chosen on the plot')
            lines.append('train, valid = fold != f, fold == f')
            lines.append('fit = paths[f][chosen]')
        else:
            lines.append('# the curve refits the path once per row, the mean of each row\'s Scaled -LogLikelihood; slow, so only the final model here')
            lines.append(f'f = {f}   # as JMP, the final model is the fit without row f, the row it predicts best at the best penalty')
            lines.append(f'chosen = {ch}')
            lines.append('train, valid = fold != f, fold == f')
            lines.append('fit = path(train)[chosen]')
    e = 'eta(fit, cols)' if forward and crit in ('kfold', 'loo') else ('eta(fit, steps[chosen])' if forward else 'eta(fit)')
    lines.append(f'e = {e}')
    lines.append('print(fit.params)   # the estimates on the scaled predictors')
    if forward:
        cc = 'cols' if crit in ('kfold', 'loo') else 'steps[chosen]'
        lines.append(f'b = np.zeros(Z.shape[1]); b[[0] + {cc}] = fit.params')
        lines.append('print(b[1:] / sd, b[0] - np.sum(b[1:] * m / sd))   # on the original predictors, and the intercept')
    else:
        lines.append('print(fit.params[1:] / sd, fit.params[0] - np.sum(fit.params[1:] * m / sd))   # on the original predictors, and the intercept')
    lines += _centred_code(d)
    lines.append('fit_nll = {"Training": nll(e, train, train) / w[train].sum()}   # the Model Summary\'s Scaled -LogLikelihood')
    lines.append('if valid.any(): fit_nll["Validation"] = nll(e, train, valid) / w[valid].sum()')
    if vcol:
        lines.append('if (sets == 2).any(): fit_nll["Test"] = nll(e, train, sets == 2) / w[sets == 2].sum()')
    lines.append('print(fit_nll)')
    return '\n'.join(lines)


def _penreg_plots(m, table, rows, table_name, out):
    """The Solution Path of a Penalized Regression as code: the estimates on
    the scaled predictors along the path (or the steps) and the curve that
    picks the model, with the model shown (red) and the best (dotted). The
    path is refitted as the report's code refits it (statsmodels'
    fit_regularized for the penalized methods; the report's own steps for
    forward selection). Without a block: the curve of Leave-One-Out (a path
    per row) and both plots of forward selection by KFold or Leave-One-Out
    (the steps of every fold)."""
    R = m['path']
    crit, forward = R.get('crit', R['O']['criterion']), R['forward']
    if forward and crit in ('kfold', 'loo'):
        return {}
    base = _gr_code(m, table, table_name, rows).split('\n')
    base = base[:next(i for i, ln in enumerate(base) if ln.startswith('e = '))]
    base = _after_frame(_with_plt(base), _positive_weights(R['O']['weight'], R['O']['freq']))
    p = out['path']
    terms = [c['term'] for c in p['coefs']]
    if forward:
        coef = ['P_ = np.zeros((len(steps), Z.shape[1] - 1))   # each step\'s estimates on the scaled predictors',
                'for s_, c_ in enumerate(steps):', '    P_[s_, [j - 1 for j in c_]] = fit_on(train, c_).params[1:]',
                'x = np.arange(len(steps))   # the step']
    else:
        src = {'kfold': 'paths[f]', 'loo': 'path(train)'}.get(crit, 'fits')
        coef = [f'P_ = np.array([q.params[1:] for q in {src}])   # the estimates on the scaled predictors along the path',
                'x = np.abs(P_).sum(axis=1)   # the magnitude of the scaled estimates']
    marks = [f'ax.axvline(x[chosen], color="{FIT}", linewidth=1.4)   # the model shown']
    best = 'best = int(np.argmin(curve))' if crit != 'kfold' else None
    codes = {}
    c = base + coef + [f'terms = {J(terms)}', f'colors = {J(PALETTE)}', _fig(400, 300),
                       'for i, t in enumerate(terms):',
                       f'    ax.plot(x, P_[:, i], color=colors[i % len(colors)], linewidth=1{", drawstyle=" + J("steps-post") + ", marker=" + J("o") + ", markersize=3" if forward else ""}, label=t)',
                       *marks]
    if crit != 'loo':
        c += ([best] if best else []) + ['if best != chosen:', f'    ax.axvline(x[best], color="{MUTED}", linewidth=0.7, linestyle=":")   # the best']
    c += [f'ax.set_xlabel({J(p["xlabel"])})', 'ax.set_ylabel("Parameter Estimates")', 'ax.set_title("solution path")', 'plt.show()']
    codes['path'] = '\n'.join(c)
    if crit != 'loo':
        c = base + coef + ([best] if best else []) + [_fig(340, 300),
                                                      f'ax.plot(x, curve, color="{BASE}", linewidth=0.9, marker="o", markersize=3.5)',
                                                      f'ax.plot(x[chosen], curve[chosen], linestyle="none", marker="D", markersize=7, color="{FIT}")', *marks,
                                                      'if best != chosen:', f'    ax.axvline(x[best], color="{MUTED}", linewidth=0.7, linestyle=":")',
                                                      f'ax.set_xlabel({J(p["xlabel"])})', f'ax.set_ylabel({J(p["label"])})', f'ax.set_title({J(p["label"] + " path")})', 'plt.show()']
        codes['curve'] = '\n'.join(c)
    return codes


@api('fitmodel.penreg')
def penreg(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, dist='normal', method='lasso', enet_alpha=0.9,
           criterion='aicc', n_grid=40, choose=None, target=None, adaptive=False, validation=None, portion=None, folds=None, seed=None,
           center=True, table_name='data'):
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, dist=dist, method=method, enet_alpha=enet_alpha, criterion=criterion,
                 n_grid=n_grid, choose=choose, target=target, adaptive=adaptive, validation=validation, portion=portion, folds=folds, seed=seed,
                 center=center)
    m = _penreg_model(table, rows, spec)
    R = m['path']
    S, O = R['S'], R['O']
    d, names = m['d'], m['names']
    ch = m['chosen']
    sh = R['shown'][ch]
    labels = [_tlabel(d, nm) for nm in names]
    ic = names.index('Intercept')
    est = [{'term': labels[j], 'estimate': float(m['b_jmp'][j]), 'zero': j != ic and abs(m['b_jmp'][j]) < 1e-12} for j in range(len(names))]
    rank = {'Intercept': -1}
    for i, e in enumerate(d.effects):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    order = sorted(range(len(names)), key=lambda j: rank.get(names[j], len(d.effects)))
    est = [est[j] for j in order]
    pos = {j: i for i, j in enumerate(m['cols'])}
    scaled = [{'term': labels[ic], 'estimate': float(m['scaled'][0])}] + [
        {'term': labels[j], 'estimate': float(m['scaled'][1 + pos[j]])} for j in order if j != ic]
    eta = m['X'].to_numpy(float) @ m['b']
    pred = _gr_mu(m['dist'], eta)
    meth, title = _gr_label(O)
    crit = R.get('crit', O['criterion'])   # KFold for a K-fold Validation column
    fcol = S['info'].get('fold_column')
    live = S['live']
    L = len(R['coefs'])
    full = np.zeros((L, len(m['cols'])))
    full[:, live] = R['coefs'][:, 1:]
    l1n = np.sum(np.abs(full), axis=1)
    stats_ = _gr_sets_stats(m)
    byset = {s_['set']: s_ for s_ in stats_}
    tr_ = byset['Training']
    msr = [('rows', 'Number of rows'), ('n', 'Sum of Frequencies'), ('nll', '-LogLikelihood'), ('scaled', 'Scaled -LogLikelihood'),
           ('nparm', 'Number of Parameters'), ('bic', 'BIC'), ('aicc', 'AICc'), ('grsq', 'Generalized RSquare'), ('rase', 'RASE')]
    extra = {'nparm': sh['df'], 'bic': sh['bic'], 'aicc': sh['aicc']}
    if not R['forward']:
        msr.append(('lambda', 'Lambda Penalty'))
        extra['lambda'] = float(R['lams'][ch])
        if O['method'] == 'enet':
            msr.append(('alpha', 'Elastic Net Alpha'))
            extra['alpha'] = float(R['l1'])
    srows = []
    for k_, lab in msr:
        r_ = {'measure': lab}
        for s_ in stats_:
            r_[s_['set']] = s_.get(k_) if k_ in s_ else (extra.get(k_) if s_['set'] == 'Training' else None)
        srows.append(r_)
    summary = rtable([col('measure', 'Measure', 'text')] + [col(s_['set'], s_['set']) for s_ in stats_], srows)
    notes = []
    if R.get('mle'):
        notes.append('Maximum Likelihood: every term, no penalty (statsmodels\' GLM, least squares for the normal), fitted on the centred and '
                     'scaled predictors and shown on the original ones. The standard errors are the inverse information of the training rows '
                     '(for the normal times SSE/(rows − parameters), as statsmodels\' GLM), the Wald ChiSquare (estimate/SE)².')
    elif R['forward']:
        notes.append(('Each step enters the term with the largest score statistic (for the normal: the largest drop in the error sum of squares) '
                      'and refits by maximum likelihood on the centred and scaled predictors'
                      + ('; after an entry, a term leaves while the model without it (the term with the smallest Wald statistic, never the one '
                         'just entered) fits better than any model of that size before it (floating search).' if O['method'] == 'pruned' else '.')))
    else:
        notes.append('The predictors are centred and scaled by the rows that train the model before the penalty; the intercept is not penalized. '
                     'The degrees of freedom of AICc and BIC are the number of nonzero terms for the lasso, the trace of the ridge hat matrix on '
                     'them for the elastic net and ridge. Penalized estimates have no standard errors here.')
    if O['adaptive']:
        notes.append('Adaptive: each term\'s penalty (both parts, for the elastic net) is divided by |b|, b its '
                     + ('maximum likelihood estimate on the scaled predictors' if R['pf_from'] == 'mle' else
                        f'ridge estimate at λ = {_GR_RIDGE0} (the maximum likelihood estimates do not exist here)')
                     + ', from the rows that train the model (every row for KFold and Leave-One-Out). Terms with small initial estimates are penalized more.')
    rowsets = {'rows': [int(i) for i in d.df.index]}
    if crit == 'kfold' and fcol:
        f = R['fstar']
        notes.append(f'KFold by {fcol["column"]}: its {len(fcol["values"])} values are the folds (every row trains; each fold is held out '
                     'once). The curve is the mean over the folds of each fold\'s validation −LogLikelihood per unit of weight (Scaled '
                     f'−LogLikelihood); as JMP, the model reported is the fold model with the smallest validation −LogLikelihood at the chosen '
                     f'penalty, the one without {fcol["column"]} = {_lvl(fcol["values"][f])}: its {int(R["valid"].sum())} rows are the Validation set.')
    elif crit == 'kfold':
        f = R['fstar']
        notes.append(f'KFold: {O["folds"]} folds drawn with the seed {O["seed"]}. The curve is the mean over the folds of each fold\'s validation '
                     '−LogLikelihood per unit of weight (Scaled −LogLikelihood). As JMP does, the model reported is the fold model with the smallest '
                     f'validation −LogLikelihood at the chosen penalty, fold {f + 1}: the other folds train it (the Training set), its '
                     f'{int(R["valid"].sum())} rows are the Validation set.')
    elif crit == 'loo':
        f = R['fstar']
        notes.append(f'Leave-One-Out: the path refitted once per row ({R["K"]} fits); the curve is the mean of each row\'s Scaled −LogLikelihood. As JMP '
                     f'does, the model reported is the one without the row it predicts best at the chosen penalty (row {int(d.df.index[f]) + 1}), '
                     'which is its Validation set.')
    elif crit == 'holdback':
        notes.append(f'Holdback: {int((S["sets"] == 1).sum())} rows ({O["portion"]:g} of them) held back for validation, drawn with the seed {O["seed"]} '
                     'as the page\'s predictive platforms draw a Validation Portion. The curve is their Scaled −LogLikelihood.')
    elif crit == 'validation':
        notes.append(f'Validation Column: rows {O["validation"]} = 0 (Training) fit the model, 1 (Validation) choose it by their Scaled '
                     '−LogLikelihood, 2 (Test) take no part and show how the chosen model predicts.')
    elif O['validation']:
        notes.append(f'{O["validation"]}: the training rows (0) fit the model; the Validation and Test rows are shown in the Model Summary.')
    notes += S['notes']
    if crit not in ('aicc', 'bic') and S['dist'] == 'normal':
        notes.append('The normal\'s −LogLikelihood of validation and test rows takes the variance of the training residuals (SSE/N).')
    model = {'response': O['y'][0], 'distribution': _DIST_LABEL[S['dist']], 'method': meth,
             'validation': f'KFold ({fcol["column"]})' if fcol and crit == 'kfold' else _GR_VALID[crit], 'title': title,
             'criterion': _GR_VALID[crit] if crit in ('aicc', 'bic') else 'Scaled -LogLikelihood',
             'n': tr_['n'], 'rows': tr_['rows'], 'nll': tr_['nll'], 'nparm': sh['df'], 'aicc': sh['aicc'], 'bic': sh['bic'], 'grsq': tr_['grsq'],
             'lambda': None if R['forward'] else float(R['lams'][ch]), 'enet_alpha': R['l1'],
             'target': _lvl(S['info']['levels'][0]) if S['info'].get('levels') else None, 'adaptive': bool(O['adaptive']),
             'folds': len(fcol['values']) if fcol and crit == 'kfold' else O['folds'], 'portion': O['portion'], 'seed': O['seed'],
             'fold': R['fstar'] + 1 if crit in ('kfold', 'loo') else None, 'validation_column': O['validation'], 'mle': bool(R.get('mle')),
             'nonzero': int(sum(1 for e_ in est if not e_['zero'] and e_['term'] != 'Intercept'))}
    path = {'x': list(range(L)) if R['forward'] else l1n.tolist(), 'xlabel': 'Step' if R['forward'] else 'Magnitude of Scaled Parameter Estimates',
            'l1': l1n.tolist(), 'alpha': None if R['forward'] else [float(a) for a in R['lams']],
            'aicc': [s_['aicc'] for s_ in R['shown']], 'bic': [s_['bic'] for s_ in R['shown']], 'df': [s_['df'] for s_ in R['shown']],
            'nonzero': [s_['nonzero'] for s_ in R['shown']], 'curve': [float(v) for v in R['curve']], 'label': model['criterion'],
            'coefs': [{'term': labels[j], 'values': full[:, i].tolist()} for i, j in enumerate(m['cols'])]}
    if R.get('mle'):   # JMP's Maximum Likelihood estimates carry standard errors and Wald tests
        Cm = _gr_mle_cov(m)
        zc = float(stats.norm.ppf(0.975))
        by_term = {labels[j]: j for j in range(len(names))}
        for e_ in est:
            j = by_term[e_['term']]
            se = math.sqrt(Cm[j, j]) if np.isfinite(Cm[j, j]) and Cm[j, j] > 0 else None
            chi = (e_['estimate'] / se) ** 2 if se else None
            e_.update({'se': se, 'chisq': chi, 'p': float(stats.chi2.sf(chi, 1)) if chi is not None else None,
                       'lower': e_['estimate'] - zc * se if se else None, 'upper': e_['estimate'] + zc * se if se else None})
    # the effects with a nonzero term (Make Model and Run Model take them), by their place among the model's effects
    out_active = [i for i, e_ in enumerate(d.effects) if any(abs(m['b_jmp'][names.index(t)]) > 1e-12 for t in e_.get('terms', []) if t in names)]
    code = _gr_code(m, table, table_name, rows)
    out = {'model': model, 'summary': summary, 'path': path, 'best': m['best'], 'chosen': ch, 'estimates': est, 'scaled': scaled,
           'factors': _factors(d), 'key': m['key'], 'active': out_active,
           'diag': {**rowsets, 'actual': m['y'], 'predicted': pred, 'residual': m['y'] - pred, 'set': m['sets']},
           'notes': notes, 'code': code}
    if R.get('mle'):
        fam = {'binomial': 'sm.families.Binomial()', 'poisson': 'sm.families.Poisson()'}.get(S['dist'])
        out['code'] = code + '\n' + ('fo = sm.GLM(y[train], X[train], family=' + fam + ', var_weights=w[train]).fit()' if fam else
                                     'fo = sm.WLS(y[train], X[train], weights=w[train]).fit()') + \
            '   # the same fit on the original predictors: its standard errors\nprint(fo.params, fo.bse)'
    if S['dist'] == 'binomial' and S['info'].get('levels'):
        out['fit_report'] = _gr_fit_report(m, code, crit, bool(O['validation']) and not fcol)
    out['plot_code'] = _penreg_plots(m, table, rows, table_name, out)
    return out


def _gr_mle_cov(m):
    """The covariance of a Maximum Likelihood fit's estimates on the original
    predictors (JMP's intercept at x = 0), from its training rows: the inverse
    information, for the normal times SSE/(rows - parameters) (statsmodels'
    GLM and WLS); the columns the fit leaves out (constant in the training
    rows) have none."""
    R, S = m['path'], m['path']['S']
    rows = R['train']
    names, ic, cols = m['names'], S['ic'], S['cols']
    use = [ic] + [c for k, c in enumerate(cols) if S['live'][k]]
    X = m['X'].to_numpy(float)[rows]
    y, w = S['y'][rows], S['w'][rows]
    eta = X @ m['b']
    if S['dist'] == 'normal':
        W = w
        scale = float(np.sum(w * (y - eta) ** 2)) / max(int(rows.sum()) - len(use), 1)
    else:
        W = w * _gr_var(S['dist'], _gr_mu(S['dist'], eta))
        scale = 1.0
    A = X[:, use]
    C = np.full((len(names), len(names)), np.nan)
    try:
        C[np.ix_(use, use)] = np.linalg.inv(A.T @ (A * W[:, None])) * scale
    except np.linalg.LinAlgError:
        return C
    T = np.eye(len(names))
    for t, mean in getattr(m['d'], 'centered_main', {}).items():
        if t in names:
            T[ic, names.index(t)] = -mean
    Cz = np.where(np.isfinite(C), C, 0.0)
    out = T @ Cz @ T.T
    out[~np.isfinite(np.diag(C)), :] = np.nan
    return out


def _gr_fit_report(m, code, crit, column_sets):
    """predictive.report of a binomial fit's probabilities by set (the Model
    Summary's sets): the confusion matrices, ROC and lift curves and the
    Decision Threshold (WP3's), the target level first, as the fit models it.
    The code: the report's own, then each row's level and probabilities."""
    S = m['path']['S']
    Q = predictive.Prepared()
    spec = m['spec']
    Q.table, Q.y, Q.kind = m['tid'], spec['y'][0], 'categorical'
    Q.index = np.asarray(m['d'].df.index, dtype=int)
    lv = S['info']['levels']
    Q.levels = [v.item() if hasattr(v, 'item') else v for v in lv]
    Q.labels = [_lvl(v) for v in lv]
    Q.target = np.where(S['y'] == 1, 0, 1).astype(int)
    Q.sets = np.asarray(m['sets'], dtype=int)
    Q.w = np.asarray(S['w'], dtype=float) if (spec.get('weight') or spec.get('freq')) else None
    Q.freq = None if not spec.get('freq') else _col_values(m['tid'], spec['freq'], Q.index)
    Q.spec = {'weight': spec.get('weight'), 'freq': spec.get('freq'), 'validation': spec.get('validation'), 'portion': 0.0, 'seed': None}
    p = _gr_mu('binomial', m['X'].to_numpy(float) @ m['b'])
    fitted = np.column_stack([p, 1 - p])
    head = [code,
            f'p_ = 1 / (1 + np.exp(-np.clip(e, -{_GR_ETA}, {_GR_ETA})))',
            'fitted = np.column_stack([p_, 1 - p_])   # each row\'s probabilities: the target level, the other',
            'y = np.where(y == 1, 0, 1)   # each row\'s level: 0 the target']
    if crit in ('kfold', 'loo'):
        head.append('sets = np.where(train, 0, np.where(valid, 1, -1))   # the final model\'s fold: Training and Validation')
    elif not column_sets and crit in ('aicc', 'bic'):
        head.append('sets = np.zeros(len(d), dtype=int)')
    rep_ = predictive.report(Q, fitted, roc_curves=True, head='\n'.join(head))
    if rep_.get('threshold'):
        rep_['threshold']['target'] = 0
    return rep_


# ---------------------------------------------------------------------------
# Generalized Estimating Equations
# ---------------------------------------------------------------------------

_GEE_CORR = {'independence': 'Independence', 'exchangeable': 'Exchangeable', 'ar1': 'Autoregressive AR(1)', 'nested': 'Nested',
             'unstructured': 'Unstructured'}
_GEE_STRUCT = {'independence': 'Independence()', 'exchangeable': 'Exchangeable()', 'ar1': 'Autoregressive(grid=False)', 'nested': 'Nested()',
               'unstructured': 'Unstructured()'}
_GEE_COV = {'robust': 'Robust (sandwich)', 'naive': 'Naive (model-based)', 'bias_reduced': 'Bias-reduced (Mancl and DeRouen)'}
_UNSTRUCTURED_MAX = 15    # distinct Time values the unstructured working correlation takes


def _gee_codes(d, name):
    """Integer codes of a grouping column for the rows of the design (in the
    table's level order, sorted values for a continuous column) and its
    levels as the page shows them."""
    s = d.df[d.alias[name]]
    if isinstance(s.dtype, pd.CategoricalDtype):
        s = s.cat.remove_unused_categories()
        return s.cat.codes.to_numpy().astype(int), [_lvl(v) for v in s.cat.categories]
    uniq, codes = np.unique(s.to_numpy(), return_inverse=True)
    return codes.astype(int), [_lvl(u) for u in uniq]


def _gee_scale_arg(spec):
    """statsmodels' scale argument: 'X2' estimates it (Pearson χ²/(N − p)),
    a float fixes it (an int would not: statsmodels takes only floats),
    None is the family's default (1 for binomial, Poisson and negative
    binomial, estimated otherwise)."""
    s = spec.get('scale')
    if s == 'estimated':
        return 'X2'
    if s == 'fixed':
        v = 1.0 if spec.get('scale_value') in (None, '') else float(spec['scale_value'])
        if not v > 0:
            raise ValueError('a fixed scale must be above zero')
        return float(v)
    return None


def _gee_model(tid, rows, spec):
    key = _key('gee', tid, rows, spec)
    m = models.recall(key)
    if m is not None:
        return m
    from statsmodels.genmod import cov_struct as cs
    from statsmodels.genmod.generalized_estimating_equations import GEE
    ys = spec['y']
    if not ys:
        raise ValueError('choose a Y')
    if len(ys) > 1:
        raise ValueError('Generalized Estimating Equations take one Y column at a time (events and trials are not supported)')
    subj, tcol, scol = spec['subject'], spec['time'], spec['subgroup']
    if not subj:
        raise ValueError('choose a Subject: the column that says which rows belong together (the subjects, or clusters)')
    dist = spec['dist'] or 'normal'
    if dist not in _DIST_LABEL:
        raise ValueError(f'no distribution {dist!r}')
    link = spec['link'] or _DEFAULT_LINK[dist]
    corr = spec['corr'] or 'exchangeable'
    cov = spec['cov'] or 'robust'
    if corr not in _GEE_CORR or cov not in _GEE_COV:
        raise ValueError(f'no working correlation {corr!r} or covariance {cov!r}')
    if spec['weight'] or spec['freq']:
        raise ValueError('statsmodels\' GEE takes case weights that several working correlations ignore: remove Weight and Freq for '
                         'Generalized Estimating Equations')
    effs = _eff_of(spec)
    if any(e['random'] for e in effs):
        raise ValueError('Generalized Estimating Equations model the correlation within a subject by the working correlation: take the '
                         'Random Effect attribute off the effects')
    if corr in ('ar1', 'unstructured') and not tcol:
        raise ValueError(f'the {_GEE_CORR[corr]} working correlation needs a Time column (the order of the rows within a subject)')
    if corr == 'nested' and not scol:
        raise ValueError('the Nested working correlation needs a Subgroup column (a grouping within the subjects)')
    roles = [c for c in (subj, tcol, scol) if c]
    if len(set(roles)) < len(roles):
        raise ValueError('Subject, Time and Subgroup must be different columns')
    extra = roles + ([spec['offset']] if spec['offset'] else [])
    if ys[0] in extra:
        raise ValueError(f'{ys[0]} is the Y: it cannot also be the Subject, Time, Subgroup or Offset')
    if tcol and data.meta(tid, tcol).get('dataType') != 'numeric':
        raise ValueError(f'Time must be numeric: {tcol} is character')
    d = _design(tid, ys[0], effs, rows, None, None, not spec['no_intercept'], extra=extra, center=spec.get('center', True))
    if tcol:
        # statsmodels' AR(1) working correlation counts positions within a
        # subject: its rows go in time order (a stable sort keeps ties as they are)
        g0, _ = _gee_codes(d, subj)
        t0 = data.series(tid, tcol, d.df.index, as_category=False).to_numpy(float)
        d.df = d.df.iloc[np.lexsort((t0, g0))]
    endog, yresp, info = _glm_endog(d, tid, ys, dist, spec['target'], what='Generalized Estimating Equations')
    X = _matrix(d)
    groups, glabels = _gee_codes(d, subj)
    tvals = data.series(tid, tcol, d.df.index, as_category=False).to_numpy(float) if tcol else None
    off = _col_values(tid, spec['offset'], d.df.index)
    sub, slabels = _gee_codes(d, scol) if scol else (None, None)
    nb_alpha = 1.0 if spec['nb_alpha'] in (None, '') else float(spec['nb_alpha'])
    var_power = 1.5 if spec['var_power'] in (None, '') else float(spec['var_power'])
    if dist == 'negbin' and not nb_alpha > 0:
        raise ValueError('the negative binomial α must be above zero')
    if dist == 'tweedie' and not 1 <= var_power <= 3:
        raise ValueError('the Tweedie power must lie between 1 (Poisson) and 3 (inverse Gaussian); 1 < p < 2 is the compound Poisson-gamma')
    fam = _family(dist, link, nb_alpha, var_power)
    time_arg, tcodes, tuniq = None, None, None
    if corr == 'ar1':
        time_arg = tvals
        struct = cs.Autoregressive(grid=False)
    elif corr == 'unstructured':
        tuniq, tcodes = np.unique(tvals, return_inverse=True)
        if len(tuniq) > _UNSTRUCTURED_MAX:
            raise ValueError(f'{tcol} has {len(tuniq)} distinct values: the Unstructured working correlation takes at most {_UNSTRUCTURED_MAX}')
        if pd.Series(groups.astype(np.int64) * len(tuniq) + tcodes).duplicated().any():
            raise ValueError(f'the Unstructured working correlation needs each value of {tcol} at most once within a subject')
        time_arg = tcodes.astype(np.int64)
        struct = cs.Unstructured()
    elif corr == 'nested':
        struct = cs.Nested()
    elif corr == 'exchangeable':
        struct = cs.Exchangeable()
    else:
        struct = cs.Independence()
    scale_arg = _gee_scale_arg(spec)
    mod = GEE(endog, X, groups=groups, time=time_arg, family=fam, cov_struct=struct, offset=off,
              dep_data=sub if corr == 'nested' else None)
    try:
        res = mod.fit(cov_type=cov, scale=scale_arg)
    except (ValueError, np.linalg.LinAlgError, FloatingPointError, ZeroDivisionError) as e:
        raise ValueError(f'statsmodels\' GEE did not fit this model with the {_GEE_CORR[corr]} working correlation ({e}); try another one '
                         '(Compare Working Correlations lists those that fit)') from e
    if res is None:
        raise ValueError('the GEE fit failed: statsmodels found the covariance of the estimates singular (see the messages)')
    m = {'kind': 'gee', 'd': d, 'res': res, 'X': X, 'endog': endog, 'y': yresp, 'info': info, 'dist': dist, 'link': link, 'corr': corr,
         'cov': cov, 'offset': off, 'groups': groups, 'glabels': glabels, 'time': tvals, 'tcodes': tcodes, 'tuniq': tuniq, 'sub': sub,
         'slabels': slabels, 'scale_arg': scale_arg, 'nb_alpha': nb_alpha, 'var_power': var_power, 'coder': Coder(d, X.design_info),
         'key': key, 'spec': spec, 'tid': tid}
    models.remember(key, m)
    return m


def _gee_independence(m):
    """The independence fit of the same model (for the common scale of QIC)."""
    if m['corr'] == 'independence':
        return m['res']
    if m.get('indep') is None:
        from statsmodels.genmod import cov_struct as cs
        from statsmodels.genmod.generalized_estimating_equations import GEE
        fam = _family(m['dist'], m['link'], m['nb_alpha'], m['var_power'])
        mod = GEE(m['endog'], m['X'], groups=m['groups'], family=fam, cov_struct=cs.Independence(), offset=m['offset'])
        m['indep'] = mod.fit(cov_type='robust', scale=m['scale_arg'])
    return m['indep']


def _gee_qic_scale(m):
    """The scale at which QIC is computed, the same for every working
    correlation: a fixed scale, 1 for the families whose scale is 1, else
    the Pearson estimate of the independence fit."""
    sa = m['scale_arg']
    if isinstance(sa, float):
        return sa, 'fixed'
    if sa is None and m['dist'] in ('binomial', 'poisson', 'negbin'):
        return 1.0, 'fixed'
    return float(_gee_independence(m).scale), 'independence'


def _gee_qic(m, res, scale):
    """QIC and QICu (Pan 2001) at the given scale. The quasi-likelihood is
    statsmodels' (Wedderburn's integral, by the trapezoid rule) and so is
    QICu, -2 Q + 2p. QIC is -2 Q + 2 trace(Omega_I V_R), V_R the robust
    covariance and Omega_I the information of the independence model at the
    estimates, sum X' diag(mu'(eta)^2 / v(mu)) X / phi. statsmodels' own
    qic() leaves v(mu) out of Omega_I (sum D'D / phi), which is Pan's only
    for the normal family; its value comes back as qic_sm."""
    mod = res.model
    b = res.params.to_numpy(float)
    ql, qic_sm, qicu = mod.qic(b, scale, res.cov_params())
    X = m['X'].to_numpy(float)
    lin = X @ b + (m['offset'] if m['offset'] is not None else 0.0)
    fam = mod.family
    mu = fam.link.inverse(lin)
    w = fam.link.inverse_deriv(lin) ** 2 / fam.variance(mu)
    omega = X.T @ (X * w[:, None]) / scale
    trace = float(np.trace(omega @ np.asarray(res.cov_robust, dtype=float)))
    return {'qic': float(-2 * ql + 2 * trace), 'qicu': float(qicu), 'qic_sm': float(qic_sm), 'ql': float(ql), 'trace': trace,
            'p': int(X.shape[1]), 'scale': float(scale)}


def _gee_dep(m):
    """The estimated dependence parameters, and the working correlation of a
    typical subject (the first of the largest)."""
    res, corr = m['res'], m['corr']
    mod = res.model
    st = mod.cov_struct
    subj, scol = m['spec']['subject'], m['spec']['subgroup']
    rows = []
    if corr in ('exchangeable', 'ar1'):
        rows.append({'param': 'Correlation of two rows of a subject' if corr == 'exchangeable' else 'Correlation of adjacent rows (lag 1)',
                     'value': float(st.dep_params)})
    elif corr == 'nested' and getattr(st, 'vcomp_coeff', None) is not None:   # none when no subject has two rows
        vc = np.asarray(st.vcomp_coeff, dtype=float)
        s = float(st.scale)
        rows += [{'param': f'Variance component: {subj}', 'value': float(vc[0])},
                 {'param': f'Variance component: {scol} within {subj}', 'value': float(vc[1])},
                 {'param': 'Residual', 'value': s - float(np.sum(vc))},
                 {'param': f'Correlation: same {subj}, another {scol}', 'value': float(vc[0]) / s if s > 0 else None},
                 {'param': f'Correlation: same {scol}', 'value': float(vc[0] + vc[1]) / s if s > 0 else None}]
    elif corr == 'unstructured':
        R = np.asarray(st.dep_params, dtype=float)
        tl = [_lvl(v) for v in m['tuniq']]
        for i in range(len(tl)):
            for j in range(i + 1, len(tl)):
                rows.append({'param': f'{tl[i]} and {tl[j]}', 'value': float(R[i, j])})
    sizes = np.array([len(y) for y in mod.endog_li])
    i = int(np.argmax(sizes))
    M, is_cor = st.covariance_matrix(mod.cached_means[i][0], i)
    M = np.asarray(M, dtype=float)
    if not is_cor:
        sd = np.sqrt(np.diag(M))
        M = M / np.outer(sd, sd)
    idx = mod.group_indices[mod.group_labels[i]]
    if m['time'] is not None:
        labels = [_lvl(v) for v in m['time'][idx]]
    else:
        labels = [f'row {k + 1}' for k in range(len(idx))]
    if m['sub'] is not None and corr == 'nested':
        labels = [f'{m["slabels"][s]}: {lb}' for s, lb in zip(m['sub'][idx], labels)]
    return {'rows': rows, 'matrix': {'values': M, 'labels': labels, 'subject': m['glabels'][int(mod.group_labels[i])], 'size': int(len(idx))}}


def _gee_predict(m, settings, alpha):
    res = m['res']
    L = m['coder'].rows(settings)
    b = res.params.to_numpy(float)
    V = np.asarray(res.cov_params(), dtype=float)
    eta = L @ b
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', L, V, L), 0))
    z = float(stats.norm.ppf(1 - alpha / 2))
    inv = res.model.family.link.inverse
    lo, hi = inv(eta - z * se), inv(eta + z * se)
    name = m['spec']['y'][0] if not m['info'].get('levels') else f'Prob[{_lvl(m["info"]["levels"][0])}]'
    return [{'name': name, 'pred': inv(eta), 'lower': np.minimum(lo, hi), 'upper': np.maximum(lo, hi), 'bounded': m['dist'] == 'binomial'}]


def _gee_ratios(m, z):
    """Odds ratios (logit link) or rate ratios (log link): per unit and over
    the range of a continuous main effect, between the levels of a
    categorical one (the other factors averaged), with the report's
    covariance; Wald intervals."""
    if m['link'] not in ('logit', 'log'):
        return None
    d, res = m['d'], m['res']
    names = list(m['X'].columns)
    b = res.params.to_numpy(float)
    V = np.asarray(res.cov_params(), dtype=float)
    kind = 'Odds Ratios' if m['link'] == 'logit' else ('Rate Ratios' if m['dist'] in ('poisson', 'negbin', 'tweedie') else 'Mean Ratios')
    out = {'kind': kind, 'unit': [], 'levels': []}
    for e in d.effects:
        if len(e['cols']) != 1:
            continue
        a = d.alias[e['cols'][0]]
        terms = [t for t in e.get('terms', []) if t in names]
        if a not in d.categorical and len(terms) == 1:
            j = names.index(terms[0])
            bj, sj = float(b[j]), math.sqrt(max(V[j, j], 0))
            x = d.df[a].to_numpy(float)
            rng_ = float(np.max(x) - np.min(x))
            out['unit'].append({'term': e['label'], 'ratio': _exp(bj), 'lower': _exp(bj - z * sj), 'upper': _exp(bj + z * sj),
                                'p': float(stats.chi2.sf((bj / sj) ** 2, 1)) if sj > 0 else None, 'range': _exp(bj * rng_),
                                'range_lower': _exp((bj - z * sj) * rng_), 'range_upper': _exp((bj + z * sj) * rng_), 'span': rng_})
        elif a in d.categorical:
            lv = d.levels[a]
            others = {x: AVG for x in d.categorical if x != a}
            Ls = m['coder'].rows([dict(others, **{a: i}) for i in range(len(lv))])
            for i1 in range(len(lv)):
                for i2 in range(len(lv)):
                    if i1 == i2:
                        continue
                    dl = Ls[i1] - Ls[i2]
                    lo_ = float(dl @ b)
                    se = math.sqrt(max(float(dl @ V @ dl), 0))
                    out['levels'].append({'term': e['label'], 'level1': _lvl(lv[i1]), 'level2': _lvl(lv[i2]), 'ratio': _exp(lo_),
                                          'lower': _exp(lo_ - z * se), 'upper': _exp(lo_ + z * se),
                                          'p': float(stats.chi2.sf((lo_ / se) ** 2, 1)) if se > 0 else None})
    return out


def _gee_code(m, table, table_name, rows, compare=False, qic_scale=None, extra_imports=()):
    """Runnable code for a GEE fit or, compare=True, for the fit of every
    working correlation the roles allow and their QIC."""
    d, spec = m['d'], m['spec']
    subj, tcol, scol, offset = spec['subject'], spec['time'], spec['subgroup'], spec['offset']
    lines = _code_frame(d, table, table_name, rows, [], [*extra_imports, 'import patsy'])
    if tcol:
        lines.append(f'd = d.sort_values([{json.dumps(subj)}, {json.dumps(tcol)}], kind="stable")   # a subject\'s rows in time order '
                     '(statsmodels\' AR(1) counts positions)')
    lines.append(f'X = patsy.dmatrix({json.dumps(_code_formula(d, lhs=False))}, d)   # the design, effect coded')
    yq = json.dumps(spec['y'][0])
    if m['info'].get('levels'):
        lv0 = m['info']['levels'][0]
        lines.append(f'y = (d[{yq}] == {json.dumps(lv0 if isinstance(lv0, str) else float(lv0))}).astype(float)   # the event level')
    else:
        lines.append(f'y = d[{yq}].astype(float)')
    L = f'sm.families.links.{_LINKS[m["link"]]}()'
    if m['dist'] == 'negbin':
        fam = f'sm.families.NegativeBinomial(link={L}, alpha={m["nb_alpha"]!r})'
    elif m['dist'] == 'tweedie':
        fam = f'sm.families.Tweedie(link={L}, var_power={m["var_power"]!r})'
    else:
        fam = f'sm.families.{_SM_FAMILY[m["dist"]]}(link={L})'
    lines.append(f'fam = {fam}')
    sa = m['scale_arg']
    fit_kw = f'cov_type={json.dumps(m["cov"])}' + (f', scale={sa!r}' if sa is not None else '')
    off = f', offset=d[{json.dumps(offset)}]' if offset else ''
    lin = 'lin = Xa @ b' + (f' + d[{json.dumps(offset)}].to_numpy(float)' if offset else '')
    pan = ('-2 * fit.model.qic(b, scale, fit.cov_params())[0] + 2 * np.trace(Xa.T @ (Xa * w[:, None]) / scale @ fit.cov_robust)')
    if compare:
        cands = ['independence', 'exchangeable'] + (['ar1', 'unstructured'] if tcol else []) + (['nested'] if scol else [])
        lines.append(f'scale = {qic_scale!r}   # QIC at one scale for every working correlation')
        lines.append('Xa = np.asarray(X)')
        lines.append('structs = {' + ', '.join(f'{json.dumps(c)}: sm.cov_struct.{_GEE_STRUCT[c]}' for c in cands) + '}')
        lines.append('for name, cs in structs.items():')
        lines.append('    kw = {}')
        if tcol:
            lines.append(f'    if name == "ar1": kw["time"] = d[{json.dumps(tcol)}].to_numpy(float)')
            lines.append(f'    if name == "unstructured": kw["time"] = pd.factorize(d[{json.dumps(tcol)}], sort=True)[0]')
        if scol:
            lines.append(f'    if name == "nested": kw["dep_data"] = pd.factorize(d[{json.dumps(scol)}], sort=True)[0]')
        lines.append(f'    fit = sm.GEE(y, X, groups=d[{json.dumps(subj)}]{off}, family=fam, cov_struct=cs, **kw).fit({fit_kw})')
        lines.append(f'    b = fit.params.to_numpy(); {lin}')
        lines.append('    w = fam.link.inverse_deriv(lin) ** 2 / fam.variance(fam.link.inverse(lin))   # the independence information')
        lines.append(f'    print(name, {pan}, fit.qic(scale=scale))   # QIC (Pan\'s penalty); statsmodels\' QIC and QICu')
        return lines
    kw = [f'groups=d[{json.dumps(subj)}]']
    if m['corr'] == 'ar1':
        kw.append(f'time=d[{json.dumps(tcol)}].to_numpy(float)')
    elif m['corr'] == 'unstructured':
        kw.append(f'time=pd.factorize(d[{json.dumps(tcol)}], sort=True)[0]')
    if m['corr'] == 'nested':
        kw.append(f'dep_data=pd.factorize(d[{json.dumps(scol)}], sort=True)[0]')
    lines.append(f'fit = sm.GEE(y, X, {", ".join(kw)}{off}, family=fam, cov_struct=sm.cov_struct.{_GEE_STRUCT[m["corr"]]}).fit({fit_kw})')
    what = {'robust': 'robust (sandwich)', 'naive': 'naive (model-based)', 'bias_reduced': 'bias-reduced'}[m['cov']]
    lines.append(f'print(fit.summary())   # the estimates with the {what} standard errors, z tests')
    lines.append('print(fit.model.cov_struct.summary())   # the working correlation\'s parameters')
    lines.append(f'scale = {qic_scale!r}   # QIC at the common scale')
    lines.append('print(fit.qic(scale=scale))   # statsmodels\' QIC and QICu')
    lines.append(f'Xa = np.asarray(X); b = fit.params.to_numpy(); {lin}')
    lines.append('w = fam.link.inverse_deriv(lin) ** 2 / fam.variance(fam.link.inverse(lin))   # the independence information, with the variance')
    lines.append(f'print({pan})   # QIC with Pan\'s penalty, as the report')
    return lines


@api('fitmodel.gee')
def gee(table, y, effects=(), rows=None, subject=None, time=None, subgroup=None, weight=None, freq=None, offset=None, no_intercept=False,
        dist='normal', link=None, target=None, corr='exchangeable', cov='robust', scale=None, scale_value=None, nb_alpha=None, var_power=None,
        alpha=0.05, center=True, table_name='data'):
    """Generalized Estimating Equations (statsmodels' GEE): the marginal model
    of rows grouped by a Subject, with a working correlation within the
    subjects and robust (sandwich), naive or bias-reduced standard errors."""
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, offset=offset, no_intercept=no_intercept, dist=dist, link=link, target=target,
                 subject=subject, time=time, subgroup=subgroup, corr=corr, cov=cov, scale=scale, scale_value=scale_value, nb_alpha=nb_alpha,
                 var_power=var_power, center=center)
    m = _gee_model(table, rows, spec)
    d, res = m['d'], m['res']
    mod = res.model
    names = list(m['X'].columns)
    p = len(names)
    b = res.params.to_numpy(float)
    V = np.asarray(res.cov_params(), dtype=float)
    Vr, Vn = np.asarray(res.cov_robust, dtype=float), np.asarray(res.cov_naive, dtype=float)
    T = _uncenter(d, names)
    if T is not None:
        bJ, VJ, VrJ, VnJ = T @ b, T @ V @ T.T, T @ Vr @ T.T, T @ Vn @ T.T
    else:
        bJ, VJ, VrJ, VnJ = b, V, Vr, Vn
    z = float(stats.norm.ppf(1 - alpha / 2))
    se = np.sqrt(np.maximum(np.diag(VJ), 0))
    est = []
    for j, nm in enumerate(names):
        zz = bJ[j] / se[j] if se[j] > 0 else None
        est.append({'term': _tlabel(d, nm), 'estimate': float(bJ[j]), 'se': float(se[j]), 'se_robust': float(math.sqrt(max(VrJ[j, j], 0))),
                    'se_naive': float(math.sqrt(max(VnJ[j, j], 0))), 'z': zz, 'p': float(2 * stats.norm.sf(abs(zz))) if zz is not None else None,
                    'lower': float(bJ[j] - z * se[j]), 'upper': float(bJ[j] + z * se[j]), 'name': nm})
    rank = {'Intercept': -1}
    for i, e in enumerate(d.effects):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    est.sort(key=lambda r: rank.get(r['name'], len(d.effects)))
    # Effect Tests: Wald chi-square of each effect's columns, with the report's covariance
    et = []
    for e in d.effects:
        cols = [names.index(t) for t in e.get('terms', []) if t in names]
        if not cols:
            continue
        Lm = np.zeros((len(cols), p))
        for i, c in enumerate(cols):
            Lm[i, c] = 1
        w = res.wald_test(Lm, scalar=True)
        et.append({'source': e['label'], 'nparm': len(cols), 'df': len(cols), 'wald': float(w.statistic), 'p': float(w.pvalue),
                   'logworth': _logworth(float(w.pvalue))})
    qs, qsrc = _gee_qic_scale(m)
    qic = _gee_qic(m, res, qs)
    qic['source'] = qsrc
    dep = _gee_dep(m)
    sizes = np.array([len(yy) for yy in mod.endog_li])
    mu = np.asarray(res.fittedvalues, dtype=float)
    lin = m['X'].to_numpy(float) @ b + (m['offset'] if m['offset'] is not None else 0.0)
    yv = np.asarray(m['endog'], dtype=float)
    diag = {'rows': [int(i) for i in d.df.index], 'actual': m['y'], 'predicted': mu, 'residual': yv - mu,
            'pearson': np.asarray(res.resid_pearson, dtype=float), 'linpred': lin, 'subject': [m['glabels'][g] for g in m['groups']],
            'subjects': m['glabels']}
    dist_label = _DIST_LABEL[m['dist']] + (f' (α = {m["nb_alpha"]:g})' if m['dist'] == 'negbin' else '') + \
        (f' (power {m["var_power"]:g})' if m['dist'] == 'tweedie' else '')
    iters = len(res.fit_history['params'])
    scale_kind = 'fixed' if isinstance(m['scale_arg'], float) or (m['scale_arg'] is None and m['dist'] in ('binomial', 'poisson', 'negbin')) else 'estimated'
    model = {'response': spec['y'][0], 'target': _lvl(m['info']['levels'][0]) if m['info'].get('levels') else None, 'distribution': dist_label,
             'link': _LINK_LABEL.get(m['link'], m['link']), 'corr': _GEE_CORR[m['corr']], 'corr_key': m['corr'], 'cov': _GEE_COV[m['cov']],
             'cov_key': m['cov'], 'scale': float(res.scale), 'scale_kind': scale_kind, 'subject': spec['subject'], 'time': spec['time'],
             'subgroup': spec['subgroup'], 'n': int(len(yv)), 'subjects': int(mod.num_group), 'size_min': int(sizes.min()),
             'size_mean': float(sizes.mean()), 'size_max': int(sizes.max()), 'iterations': iters, 'converged': bool(res.converged),
             'score_norm': float(res.score_norm)}
    notes = ['Generalized Estimating Equations (statsmodels\' GEE; Liang and Zeger 1986) estimate the marginal mean, the average over the '
             'subjects (the Mixed Model gives a subject\'s own, conditional, curve). JMP has no GEE platform; SAS\'s PROC GENMOD with a '
             'REPEATED statement is the nearest.',
             {'robust': 'Standard errors: the robust (sandwich) covariance, right even when the working correlation is wrong, given enough '
                        'subjects. ',
              'naive': 'Standard errors: the naive (model-based) covariance, right only when the working correlation is. ',
              'bias_reduced': 'Standard errors: Mancl and DeRouen\'s bias-reduced sandwich, for few subjects. '}[m['cov']] +
             'The tests are z and Wald χ² tests, with no small-sample degrees of freedom.',
             f'QIC and QICu are at the scale φ = {qs:.6g} ({"fixed" if qsrc == "fixed" else "the Pearson estimate of the independence fit"}), '
             'the same for every working correlation, as QIC needs. QICu (−2Q + 2p) is statsmodels\'; its QIC leaves the variance function '
             'out of the independence information (Σ D′D/φ instead of Σ D′V⁻¹D/φ), which is Pan\'s only for the normal family: the report\'s '
             'QIC uses Pan\'s penalty, 2 trace(Ω_I V_R), and shows statsmodels\' value beside it.']
    if m['corr'] == 'ar1':
        notes.append('statsmodels\' AR(1) working correlation is α^|j − k| over the positions j, k of the rows within a subject (sorted here by '
                     f'{spec["time"]}); the values of {spec["time"]} set the distances only when α is estimated. With gaps in the times the '
                     'working matrix still counts positions.')
    if m['corr'] == 'nested':
        notes.append('The Nested variance components are statsmodels\' moment estimates from the Pearson residuals, clipped at zero.')
    if m['corr'] == 'unstructured':
        notes.append(f'The Unstructured working correlation estimates a correlation for each pair of values of {spec["time"]}.')
    if scale_kind == 'estimated':
        notes.append('The scale φ is estimated as Pearson χ²/(N − p); it scales the naive covariance and the Pearson residuals\' variance.')
    if not res.converged:
        notes.append(f'The fit did not converge in {iters} iterations (statsmodels\' limit is 60): the estimates may be unreliable.')
    if spec['offset']:
        notes.append('The profilers predict at an offset of zero: per unit of exp(offset) with the log link.')
    if any(data.meta(table, nm).get('modelingType') == 'ordinal' for nm in _factor_names(d)):
        notes.append('Ordinal factors are coded like nominal ones (effect coding).')
    lines = _gee_code(m, table, table_name, rows, qic_scale=float(qs))
    lines += _centred_code(d)
    out = {'model': model, 'estimates': est, 'effect_tests': et, 'ratios': _gee_ratios(m, z), 'qic': qic, 'dep': dep, 'diag': diag,
           'factors': _factors(d), 'key': m['key'], 'alpha': alpha, 'notes': notes, 'code': '\n'.join(lines)}
    out['plot_code'] = _gee_plots(m, table, rows, table_name, out)
    return out


@api('fitmodel.gee_compare')
def gee_compare(table, y, effects=(), rows=None, subject=None, time=None, subgroup=None, weight=None, freq=None, offset=None,
                no_intercept=False, dist='normal', link=None, target=None, corr='exchangeable', cov='robust', scale=None, scale_value=None,
                nb_alpha=None, var_power=None, table_name='data'):
    """Compare Working Correlations: the model fitted with each working
    correlation the roles allow, and their QIC at one common scale."""
    base = dict(y=y, effects=effects, weight=weight, freq=freq, offset=offset, no_intercept=no_intercept, dist=dist, link=link, target=target,
                subject=subject, time=time, subgroup=subgroup, cov=cov, scale=scale, scale_value=scale_value, nb_alpha=nb_alpha,
                var_power=var_power)
    m0 = _gee_model(table, rows, _spec(**dict(base, corr='independence')))   # the common scale is the independence fit's
    qs, qsrc = _gee_qic_scale(m0)
    cands = ['independence', 'exchangeable'] + (['ar1', 'unstructured'] if time else []) + (['nested'] if subgroup else [])
    out = []
    for c in cands:
        try:
            mc = _gee_model(table, rows, _spec(**dict(base, corr=c)))
        except Exception as e:  # e.g. Unstructured with a Time value twice in a subject: a line that says so
            out.append({'corr': _GEE_CORR[c], 'key': c, 'error': str(e)})
            continue
        q = _gee_qic(mc, mc['res'], qs)
        dp = _gee_dep(mc)['rows']
        out.append({'corr': _GEE_CORR[c], 'key': c, 'qic': q['qic'], 'qicu': q['qicu'], 'qic_sm': q['qic_sm'], 'ql': q['ql'], 'trace': q['trace'],
                    'dep': dp[0]['value'] if len(dp) == 1 else None, 'converged': bool(mc['res'].converged),
                    'iterations': len(mc['res'].fit_history['params']), 'current': c == (corr or 'exchangeable')})
    ok = [r for r in out if r.get('qic') is not None and np.isfinite(r['qic'])]
    best = min(ok, key=lambda r: r['qic'])['key'] if ok else None
    for r in out:
        r['best'] = r['key'] == best
    lines = _gee_code(m0, table, table_name, rows, compare=True, qic_scale=float(qs))
    return {'rows': out, 'best': best, 'scale': qs, 'scale_source': qsrc, 'code': '\n'.join(lines),
            'notes': [f'Each working correlation fitted to the same rows; QIC at the common scale φ = {qs:.6g}. The smallest QIC marks the '
                      'working correlation that fits best (Pan 2001); QICu compares mean models, not working correlations. statsmodels\' '
                      'QIC is beside it (see the note under the fit).']}


# ---------------------------------------------------------------------------
# Regression Diagnostics (Standard Least Squares)
# ---------------------------------------------------------------------------

_DIAG = {'bp': 'Breusch–Pagan Test', 'white': 'White Test', 'gq': 'Goldfeld–Quandt Test', 'reset': 'Ramsey RESET Test',
         'hc': 'Harvey–Collier Test', 'rainbow': 'Rainbow Test', 'bg': 'Breusch–Godfrey Test', 'jb': 'Jarque–Bera Test',
         'omni': 'Omnibus Normality Test'}
_DIAG_COLS = [col('test', 'Test', 'text'), col('stat', 'Statistic'), col('df', 'DF', 'num'), col('dfden', 'DF Den', 'num'),
              col('p', 'p-Value', 'p')]


def _has_const(X):
    return bool(np.any((np.ptp(X, axis=0) == 0) & (X.max(axis=0) != 0)))


def _diag_order(m, how):
    """The order of the rows for a test that depends on it: the table's
    ('row'), by the predicted values, or by a continuous factor."""
    d = m['d']
    n = len(d.df)
    if how in (None, '', 'row'):
        return np.arange(n), 'in the order of the table'
    if how == 'predicted':
        return np.argsort(np.asarray(m['res'].fittedvalues, dtype=float), kind='stable'), 'sorted by the predicted values'
    a = d.alias.get(how)
    if a is None or a in d.categorical or a not in d.df or how in _ys(d.y):
        raise ValueError(f'{how} is not a continuous factor of the model to sort by')
    return np.argsort(d.df[a].to_numpy(float), kind='stable'), f'sorted by {how}'


def _diag_rows(*rows):
    return [{'test': t, 'stat': s, 'df': df, 'dfden': dd, 'p': p} for t, s, df, dd, p in rows]


@api('fitmodel.regdiag')
def regdiag(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, tests=(), reset_power=3, bg_lags=None,
            gq_sort='predicted', gq_drop=0.0, gq_alt='increasing', rainbow_frac=0.5, rainbow_order='leverage', hc_order='row',
            validation=None, center=True, table_name='data'):
    """Specification and residual tests of a least squares fit, from
    statsmodels.stats.diagnostic and stattools: heteroscedasticity
    (Breusch–Pagan, White, Goldfeld–Quandt), the functional form (RESET,
    Harvey–Collier, Rainbow), serial correlation (Breusch–Godfrey) and
    normality of the residuals (Jarque–Bera, omnibus). A weighted fit is
    tested as the regression of the whitened data (times √w)."""
    import statsmodels.api as sm
    from statsmodels.stats import diagnostic as dg
    from statsmodels.stats.stattools import jarque_bera, omni_normtest
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, validation=validation, center=center)
    m = _ls_model(table, rows, spec)
    d, res = m['d'], m['res']
    weighted = d.weights is not None
    yw = np.asarray(res.model.wendog, dtype=float)
    Xw = np.asarray(res.model.wexog, dtype=float)
    ow = sm.OLS(yw, Xw).fit()
    n, k = Xw.shape
    rk = int(np.linalg.matrix_rank(Xw))
    e = np.asarray(ow.resid, dtype=float)
    Xh = np.asarray(res.model.exog, dtype=float)
    if not _has_const(Xh):
        Xh = np.column_stack([np.ones(n), Xh])
    out = {}
    for t in [x for x in tests if x in _DIAG]:
        item = {'key': t, 'title': _DIAG[t], 'table': None, 'note': None, 'error': None}
        try:
            if t == 'bp':
                lm, lmp, f, fp = dg.het_breuschpagan(e, Xh)
                lm0, lmp0, _f0, _fp0 = dg.het_breuschpagan(e, Xh, robust=False)
                q = Xh.shape[1] - 1
                qr = int(np.linalg.matrix_rank(Xh)) - 1
                item['table'] = rtable(_DIAG_COLS, _diag_rows(('LM (Koenker, studentized)', lm, q, None, lmp),
                                                              ('LM (Breusch–Pagan, normal errors)', lm0, q, None, lmp0),
                                                              ('F', f, qr, n - qr - 1, fp)))
                item['note'] = ('H0: the variance of the residuals does not depend on the regressors (the squared residuals regressed on '
                                'them). Koenker\'s studentized LM, statsmodels\' default, holds without normal errors; the original '
                                'Breusch–Pagan LM assumes them.')
            elif t == 'white':
                i0, i1 = np.triu_indices(Xh.shape[1])
                qa = int(np.linalg.matrix_rank(Xh[:, i0] * Xh[:, i1]))
                if qa >= n:
                    raise ValueError(f'White\'s test needs more rows than the {qa} independent squares and cross products of the regressors')
                lm, lmp, f, fp = dg.het_white(e, Xh)
                item['table'] = rtable(_DIAG_COLS, _diag_rows(('LM', lm, qa - 1, None, lmp), ('F', f, qa - 1, n - qa, fp)))
                item['note'] = (f'H0: homoscedastic residuals. The squared residuals regressed on the regressors, their squares and their '
                                f'cross products ({qa - 1} columns after aliasing, and the constant).')
            elif t == 'gq':
                order, by = _diag_order(m, gq_sort)
                drop = min(max(float(gq_drop or 0.0), 0.0), 0.8)
                s = int(math.floor(n * (1 - drop) / 2))
                if s <= rk:
                    raise ValueError('too few rows for two halves that each fit the model')
                alt = gq_alt if gq_alt in ('increasing', 'decreasing', 'two-sided') else 'increasing'
                fval, pval, _o, st = dg.het_goldfeldquandt(yw[order], Xw[order], split=s, drop=n - 2 * s, alternative=alt, store=True)
                df2, df1 = st.df_fval   # the statistic is the second half's MSE over the first's: F(df2, df1)
                note = ''
                if df1 != df2 and alt != 'two-sided':
                    # statsmodels takes F(df1, df2) for the one-sided p-values; with halves of unequal rank the report uses F(df2, df1)
                    pval = float(stats.f.sf(fval, df2, df1)) if alt == 'increasing' else float(stats.f.cdf(fval, df2, df1))
                    note = ' The halves have unequal ranks: the p-value is from F(DF, DF Den) (statsmodels would take them the other way round).'
                label = {'increasing': 'F (variance increasing)', 'decreasing': 'F (variance decreasing)', 'two-sided': 'F (two-sided)'}[alt]
                item['table'] = rtable(_DIAG_COLS, _diag_rows((label, fval, float(df2), float(df1), float(pval))))
                item['note'] = (f'The rows {by}, split in two halves of {s} rows' + (f', the {n - 2 * s} middle rows left out'
                                if n - 2 * s else '') + '; F is the mean square error of the second half over the first\'s. H0: equal '
                                'variances.' + note)
            elif t == 'reset':
                pw = 2 if int(reset_power) <= 2 else 3
                r = dg.linear_reset(ow, power=pw, test_type='fitted', use_f=True)
                item['table'] = rtable(_DIAG_COLS, _diag_rows(('F', float(np.squeeze(r.fvalue)), float(r.df_num), float(r.df_denom), float(r.pvalue))))
                item['note'] = (f'Ramsey\'s RESET: the powers 2{"–3" if pw == 3 else ""} of the predicted values added to the model. H0: they '
                                'add nothing (the linear form is adequate).')
            elif t == 'hc':
                order, by = _diag_order(m, hc_order)
                Xo = Xw[order]
                skip = k
                while skip < n and np.linalg.matrix_rank(Xo[:skip]) < k:
                    skip += 1
                if skip >= n - 1:
                    raise ValueError('the recursive residuals need a set of first rows that fits the model: the design is singular in this order')
                rr = dg.recursive_olsresiduals(ow, skip=skip, alpha=0.95, order_by=order)
                w = rr[3][skip:]
                tt = stats.ttest_1samp(w, 0.0)
                item['table'] = rtable(_DIAG_COLS, _diag_rows(('t', float(tt.statistic), float(len(w) - 1), None, float(tt.pvalue))))
                item['note'] = (f'The {len(w)} recursive residuals, the rows {by} (statsmodels\' recursive_olsresiduals'
                                + (f', from the first {skip} rows that fit the model' if skip > k else '') + '); H0: their mean is zero, '
                                'the relation is linear along the order. statsmodels\' linear_harvey_collier keeps the recursive residuals '
                                'from the fourth on whatever the number of parameters (right for three, nan from five); the report takes '
                                'the n − p of Harvey and Collier (1977), as R\'s lmtest::harvtest.')
            elif t == 'rainbow':
                frac = min(max(float(rainbow_frac or 0.5), 0.1), 0.9)
                lo = int(np.ceil(0.5 * (1 - frac) * n))
                hi = int(np.floor(lo + frac * n))
                if rainbow_order == 'leverage':
                    # statsmodels' hats, rounded so that equal leverages (a balanced design) keep the rows' order
                    h = np.round(ow.get_influence().hat_matrix_diag, 12)
                    rank_h = np.argsort(h, kind='stable')
                    central, rest = rank_h[:hi - lo], np.sort(rank_h[hi - lo:])
                    order = np.concatenate([rest[:lo], central, rest[lo:]])   # linear_rainbow keeps positions lo..hi of the order
                    by = 'of smallest leverage'
                else:
                    order, by = _diag_order(m, rainbow_order)
                fstat, pval = dg.linear_rainbow(ow, frac=frac, order_by=order)
                nm = hi - lo
                rkm = int(np.linalg.matrix_rank(Xw[order][lo:hi]))
                item['table'] = rtable(_DIAG_COLS, _diag_rows(('F', float(fstat), float(n - nm), float(nm - rkm), float(pval))))
                central = by if rainbow_order == 'leverage' else f'in the middle, the rows {by}'
                item['note'] = (f'Utts\'s rainbow test: the fit of all rows against the fit of the central {nm} ({frac:g} of them), {central}. '
                                'H0: the model fits the whole range as well as the middle.' +
                                (' statsmodels\' use_distance ranks the rows by distance from the table\'s middle row and keeps the middle of '
                                 'that ranking; the report passes the leverage order to linear_rainbow\'s order_by, so that the central rows '
                                 'are those of smallest leverage (Utts 1982).' if rainbow_order == 'leverage' else ''))
            elif t == 'bg':
                lags = int(bg_lags) if bg_lags not in (None, '') else min(10, n // 5)
                lags = max(1, min(lags, n - rk - 2))
                lm, lmp, f, fp = dg.acorr_breusch_godfrey(ow, nlags=lags)
                aux = np.column_stack([Xw, np.ones(n), np.zeros((n, lags))])
                ee = np.concatenate([np.zeros(lags), e])
                for j in range(1, lags + 1):
                    aux[:, k + j] = ee[lags - j:lags - j + n]
                dfd = n - int(np.linalg.matrix_rank(aux))
                item['table'] = rtable(_DIAG_COLS, _diag_rows(('LM', lm, float(lags), None, lmp), ('F', f, float(lags), float(dfd), fp)))
                item['note'] = (f'H0: no autocorrelation of the residuals up to lag {lags}, in the order of the rows in the table (sort the '
                                'table by time first).')
            elif t == 'jb':
                jb, jbp, skew, kurt = jarque_bera(e)
                item['table'] = rtable(_DIAG_COLS, _diag_rows(('Jarque–Bera χ²', float(jb), 2.0, None, float(jbp)),
                                                              ('Skewness', float(skew), None, None, None), ('Kurtosis', float(kurt), None, None, None)))
                item['note'] = 'H0: normal residuals, judged by their skewness (0 for the normal) and kurtosis (3).'
            elif t == 'omni':
                r = omni_normtest(e)
                item['table'] = rtable(_DIAG_COLS, _diag_rows(('K² (D\'Agostino–Pearson)', float(r.statistic), 2.0, None, float(r.pvalue))))
                item['note'] = 'H0: normal residuals: D\'Agostino and Pearson\'s K², the sum of the squared skewness and kurtosis z tests.'
        except Exception as ex:  # a test that cannot be made on this model: its outline says why
            item['error'] = f'{type(ex).__name__}: {ex}' if not isinstance(ex, ValueError) else str(ex)
        out[t] = item
    notes = []
    if weighted:
        notes.append('With a Weight (or Freq) the tests are those of the weighted regression as ordinary least squares on the data times √w; '
                     'the heteroscedasticity tests regress its squared residuals on the unweighted regressors. With Freq each row counts '
                     'once, not as repeated rows.')
    if res.model.rank < res.model.exog.shape[1]:
        notes.append('The design is singular: the tests use the minimum-norm fit, and their degrees of freedom the rank.')
    notes.append('JMP has none of these tests beside the Durbin–Watson; they are statsmodels\' (statsmodels.stats.diagnostic and stattools).')
    conts = [f['name'] for f in _factors(d) if f['type'] == 'continuous']
    code = _regdiag_code(m, table, table_name, rows, [t for t in tests if t in _DIAG], weight, freq, reset_power, bg_lags, gq_sort, gq_drop,
                         gq_alt, rainbow_frac, rainbow_order, hc_order, out)
    return {'tests': out, 'order': list(tests), 'continuous': conts, 'n': n, 'p': rk, 'notes': notes, 'code': code}


def _regdiag_code(m, table, table_name, rows, tests, weight, freq, reset_power, bg_lags, gq_sort, gq_drop, gq_alt, rainbow_frac,
                  rainbow_order, hc_order, out):
    d = m['d']
    lines = _code_frame(d, table, table_name, rows, [weight, freq],
                        ['from scipy import stats', 'from statsmodels.stats import diagnostic as dg',
                         'from statsmodels.stats.stattools import jarque_bera, omni_normtest'])
    wexpr = ' * '.join(f'd[{json.dumps(v)}]' for v in (weight, freq) if v)
    fml = json.dumps(_code_formula(d))
    lines.append(f'fit = smf.wls({fml}, data=d, weights={wexpr}).fit()' if wexpr else f'fit = smf.ols({fml}, data=d).fit()')
    lines.append('ow = sm.OLS(fit.model.wendog, fit.model.wexog).fit()   # the fit as plain least squares (times √w when weighted)')
    lines.append('e, y, X, n = ow.resid, ow.model.endog, ow.model.exog, len(ow.resid)')
    lines.append('Xh = fit.model.exog' + ('' if _has_const(np.asarray(m['res'].model.exog, dtype=float)) else '; Xh = np.column_stack([np.ones(n), Xh])') +
                 '   # the regressors of the heteroscedasticity tests')

    def order_code(how):
        if how in (None, '', 'row'):
            return 'np.arange(n)'
        if how == 'predicted':
            return 'np.argsort(fit.fittedvalues.to_numpy(), kind="stable")'
        return f'np.argsort(d[{json.dumps(how)}].to_numpy(float), kind="stable")'
    for t in tests:
        if out.get(t, {}).get('error'):
            continue
        if t == 'bp':
            lines.append('print(dg.het_breuschpagan(e, Xh), dg.het_breuschpagan(e, Xh, robust=False))   # Breusch-Pagan: LM, p, F, p (Koenker; original)')
        elif t == 'white':
            lines.append('print(dg.het_white(e, Xh))   # White: LM, p, F, p')
        elif t == 'gq':
            drop = min(max(float(gq_drop or 0.0), 0.0), 0.8)
            alt = gq_alt if gq_alt in ('increasing', 'decreasing', 'two-sided') else 'increasing'
            lines.append(f'o = {order_code(gq_sort)}; s = int(np.floor(n * (1 - {drop!r}) / 2))')
            lines.append(f'print(dg.het_goldfeldquandt(y[o], X[o], split=s, drop=n - 2 * s, alternative={json.dumps(alt)}))   # Goldfeld-Quandt: F, p')
        elif t == 'reset':
            lines.append(f'print(dg.linear_reset(ow, power={2 if int(reset_power) <= 2 else 3}, use_f=True))   # RESET')
        elif t == 'hc':
            lines.append(f'o = {order_code(hc_order)}; k = X.shape[1]')
            lines.append('skip = next(s for s in range(k, n) if np.linalg.matrix_rank(X[o][:s]) == k)   # the first rows that fit the model')
            lines.append('rr = dg.recursive_olsresiduals(ow, skip=skip, order_by=o)')
            lines.append('print(stats.ttest_1samp(rr[3][skip:], 0))   # Harvey-Collier: t on the n - p recursive residuals')
        elif t == 'rainbow':
            frac = min(max(float(rainbow_frac or 0.5), 0.1), 0.9)
            lines.append(f'frac = {frac!r}; lo = int(np.ceil(0.5 * (1 - frac) * n)); hi = int(np.floor(lo + frac * n))')
            if rainbow_order == 'leverage':
                lines.append('h = np.round(ow.get_influence().hat_matrix_diag, 12); r = np.argsort(h, kind="stable")   # rounded: ties keep the rows\' order')
                lines.append('rest = np.sort(r[hi - lo:]); o = np.concatenate([rest[:lo], r[:hi - lo], rest[lo:]])   # the smallest leverages in the middle')
            else:
                lines.append(f'o = {order_code(rainbow_order)}')
            lines.append('print(dg.linear_rainbow(ow, frac=frac, order_by=o))   # Rainbow: F, p')
        elif t == 'bg':
            lags = int(bg_lags) if bg_lags not in (None, '') else min(10, len(d.df) // 5)
            lags = max(1, min(lags, len(d.df) - int(m['res'].model.rank) - 2))
            lines.append(f'print(dg.acorr_breusch_godfrey(ow, nlags={lags}))   # Breusch-Godfrey: LM, p, F, p')
        elif t == 'jb':
            lines.append('print(jarque_bera(e))   # Jarque-Bera: JB, p, skewness, kurtosis')
        elif t == 'omni':
            lines.append('print(omni_normtest(e))   # omnibus K2, p')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Shared by Instrumental Variables and Quantile Regression
# ---------------------------------------------------------------------------

def _est_table(d, names, b, V, dfi, alpha):
    """Parameter Estimates from estimates b and their covariance V in the
    fitted parameterisation: JMP's names, the intercept at x = 0 (the main
    effects centred by _center_main_effects put back), t tests on dfi
    degrees of freedom (z tests when dfi is None), in the effects' order."""
    b = np.asarray(b, dtype=float)
    V = np.asarray(V, dtype=float)
    T = _uncenter(d, names)
    if T is not None:
        b, V = T @ b, T @ V @ T.T
    se = np.sqrt(np.maximum(np.diag(V), 0))
    with np.errstate(divide='ignore', invalid='ignore'):
        tv = np.where(se > 0, b / np.where(se > 0, se, 1), np.nan)
    if dfi is None:
        pv, crit = 2 * stats.norm.sf(np.abs(tv)), float(stats.norm.ppf(1 - alpha / 2))
    else:
        pv, crit = 2 * stats.t.sf(np.abs(tv), dfi), _tcrit(alpha, dfi)
    rows = [{'term': _tlabel(d, nm), 'estimate': b[j], 'se': se[j], 't': tv[j], 'p': pv[j], 'lower': b[j] - crit * se[j],
             'upper': b[j] + crit * se[j], 'name': nm} for j, nm in enumerate(names)]
    rank = {'Intercept': -1}
    for i, e in enumerate(d.effects):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    rows.sort(key=lambda r: rank.get(r['name'], len(d.effects)))
    stat, pl = ('z Ratio', 'Prob>|z|') if dfi is None else ('t Ratio', 'Prob>|t|')
    lv = f'{100 * (1 - alpha):g}%'
    return rtable([col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('t', stat), col('p', pl, 'p'),
                   col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}')], rows)


def _wald_tests(d, names, R):
    """Effect Tests as Wald F tests, with the covariance of the results R
    (statsmodels' wald_test: F on the inference degrees of freedom)."""
    rows = []
    p = len(names)
    for e in d.effects:
        cols = [names.index(t) for t in e.get('terms', []) if t in names]
        if not cols:
            continue
        w = R.wald_test(np.eye(p)[cols], scalar=True, use_f=True)
        rows.append({'source': e['label'], 'nparm': len(cols), 'df': int(round(float(w.df_num))), 'dfden': float(w.df_denom),
                     'stat': float(np.squeeze(w.statistic)), 'p': float(np.squeeze(w.pvalue))})
    return rtable([col('source', 'Source', 'text'), col('nparm', 'Nparm', 'int'), col('df', 'DF', 'int'), col('dfden', 'DFDen', 'num'),
                   col('stat', 'F Ratio'), col('p', 'Prob > F', 'p')], rows)


def _ols_robust(fit, rob, groups=None):
    """statsmodels' robust covariance of an OLS fit (get_robustcov_results),
    as the report's Robust Standard Errors ask: HC0-HC3, Newey-West HAC or
    cluster (t tests on the clusters less one)."""
    from statsmodels.regression.linear_model import RegressionResultsWrapper as Wrap
    if not rob:
        return fit
    t = rob['type']
    if t == 'HAC':
        return Wrap(fit.get_robustcov_results(cov_type='HAC', maxlags=int(rob['maxlags']), use_t=True))
    if t == 'cluster':
        return Wrap(fit.get_robustcov_results(cov_type='cluster', groups=groups, use_t=True))
    return Wrap(fit.get_robustcov_results(cov_type=t, use_t=True))


def _check_loss(u, tau):
    """Koenker and Bassett's check function summed: sum of u (tau - [u < 0])."""
    u = np.asarray(u, dtype=float)
    return float(np.sum(u * (tau - (u < 0))))


# ---------------------------------------------------------------------------
# Instrumental Variables (two-stage least squares)
# ---------------------------------------------------------------------------

_WEAK_F = 10.0   # Staiger and Stock's (1997) rule of thumb for the first-stage F


def _rep_alias(d, n, k, raw):
    """One column's factor in an alias-space term of the instruments' design
    (k its power): a categorical column effect coded, a continuous one raw
    or centred as its main effect is in the model."""
    a = d.alias[n]
    if a in d.categorical:
        return f'C({a}, Sum)'
    if raw:
        return a if k == 1 else f'I({a} ** {k})'
    m = d.means[a]
    return f'I({a} - {m!r})' if k == 1 else f'I(({a} - {m!r}) ** {k})'


def _rep_code(d, n, k, raw):
    """_rep_alias over the real names, for the code under the report."""
    a = d.alias[n]
    if a in d.categorical:
        lv = [x.item() if hasattr(x, 'item') else x for x in d.levels[a]]
        return f'C({_q(n)}, Sum, levels={lv!r})'
    if raw:
        return _q(n) if k == 1 else f'I({_q(n)} ** {k})'
    m = d.means[a]
    return f'I({_q(n)} - {m!r})' if k == 1 else f'I(({_q(n)} - {m!r}) ** {k})'


def _iv_term(d, names, raw_of, code=False):
    counts = {}
    for n in names:
        counts[n] = counts.get(n, 0) + 1
    f = _rep_code if code else _rep_alias
    return ':'.join(f(d, n, 1 if d.alias[n] in d.categorical else k, raw_of(n)) for n, k in counts.items())


def _code_part(d, e):
    """One effect of the model as _code_formula writes it (real names)."""
    counts = {}
    for n in e['names']:
        counts[n] = counts.get(n, 0) + 1
    crossed = len(e['names']) > 1
    ps = []
    for n, k in counts.items():
        a = d.alias[n]
        if a in d.categorical:
            lv = [x.item() if hasattr(x, 'item') else x for x in d.levels[a]]
            ps.append(f'C({_q(n)}, {"Sum" if d.coding == "effect" else "Treatment"}, levels={lv!r})')
        elif (crossed and d.center) or (k == 1 and f'I({a} - {d.means.get(a)!r})' in getattr(d, 'centered_main', {})):
            m = d.means[a]
            ps.append(f'I(({_q(n)} - {m!r}) ** {k})' if k > 1 else f'I({_q(n)} - {m!r})')
        elif k > 1:
            ps.append(f'I({_q(n)} ** {k})')
        else:
            ps.append(_q(n))
    return ':'.join(ps)


def _iv_model(tid, rows, spec):
    """The 2SLS fit: the model's design X (JMP's coding), the instruments'
    design Z (the exogenous effects, the excluded instruments, and for an
    endogenous crossing or power the same crossing or power of the
    instruments), statsmodels' IV2SLS, and the covariance the report
    asks for."""
    key = _key('iv', tid, rows, spec)
    m = models.recall(key)
    if m is not None:
        return m
    import patsy
    from statsmodels.sandbox.regression.gmm import IV2SLS
    ys = spec['y']
    if not ys:
        raise ValueError('choose a Y')
    endog, inst = list(spec['endog']), list(spec['instruments'])
    if not endog:
        raise ValueError('Instrumental Variables need Endogenous columns: the model effects that are correlated with the error '
                         '(cast them into Endogenous in the launch dialog)')
    if not inst:
        raise ValueError('Instrumental Variables need Instruments: columns that move the endogenous columns but have no effect of '
                         'their own on Y (cast them into Instruments)')
    if spec['weight'] or spec['freq']:
        raise ValueError('statsmodels\' IV2SLS takes no weights: remove Weight and Freq for Instrumental Variables')
    effs = _eff_of(spec)
    if not effs:
        raise ValueError('Instrumental Variables need model effects, the endogenous ones among them')
    if any(e['random'] for e in effs):
        raise ValueError('Instrumental Variables take fixed effects only: take the Random Effect attribute off the effects')
    used = {n for e in effs for n in e['cols']}
    for n in endog:
        if n in ys:
            raise ValueError(f'{n} is the Y: it cannot also be Endogenous')
        if n not in used:
            raise ValueError(f'{n} is Endogenous but not in the model effects: add it to the model, or take it out of Endogenous')
    for n in inst:
        if n in ys or n in endog:
            raise ValueError(f'{n} is the Y or Endogenous: it cannot also be an Instrument')
        if n in used:
            raise ValueError(f'{n} is a model effect and an Instrument: an instrument is excluded from the model (the exogenous '
                             'effects instrument themselves); take it out of one of them')
    eset, iset = set(endog), set(inst)
    for e in effs:
        if e['nest'] and any(n in eset for n in e['cols']):
            raise ValueError(f'{e["label"]}: a nested effect with an endogenous column is not supported')
    rob = spec.get('robust')
    ccol = rob['cluster'] if rob and rob['type'] == 'cluster' else None
    if ccol and ccol in ys:
        raise ValueError(f'{ccol} is the Y: cluster the standard errors by another column')
    d = _design(tid, ys[0], effs, rows, None, None, not spec['no_intercept'], extra=inst + ([ccol] if ccol else []), center=spec.get('center', True))
    if isinstance(d.df[d.y_alias].dtype, pd.CategoricalDtype):
        raise ValueError(f'{ys[0]} is {data.meta(tid, ys[0]).get("modelingType")}: Instrumental Variables need a continuous Y')
    X = _matrix(d)
    names = list(X.columns)
    endo_eff = [e for e in d.effects if any(n in eset for n in e['names'])]
    exo_eff = [e for e in d.effects if e not in endo_eff]
    endo_cols = [t for e in endo_eff for t in e.get('terms', []) if t in names]
    # the instruments: the exogenous effects as in the model, each instrument's
    # main effect and, for an endogenous crossing or power, the same crossing or
    # power with the instruments in place of the endogenous columns (a column
    # keeps the form of its main effect, so that patsy codes the crossings as
    # the model's)
    cm = {_ALIAS_ANY.match(t).group(1) for t in getattr(d, 'centered_main', {})}
    raw_of = lambda n: n in iset or d.alias[n] not in cm  # noqa: E731
    zt, zc, gen = [], [], []
    for z in inst:
        zt.append(_iv_term(d, [z], raw_of))
        zc.append(_iv_term(d, [z], raw_of, code=True))
    seen = set()
    for e in endo_eff:
        en = [n for n in e['names'] if n in eset]
        ex = [n for n in e['names'] if n not in eset]
        if len(en) == 1 and not ex:
            continue
        for combo in itertools.combinations_with_replacement(inst, len(en)):
            if any(combo.count(z) > 1 and d.alias[z] in d.categorical for z in combo):
                continue   # a categorical instrument crossed with itself is itself
            nm = ex + list(combo)
            k2 = tuple(sorted(nm))
            if k2 in seen:
                continue
            seen.add(k2)
            zt.append(_iv_term(d, nm, raw_of))
            zc.append(_iv_term(d, nm, raw_of, code=True))
            gen.append({'effect': e['label'], 'instrument': '*'.join(nm)})
    zrhs = ' + '.join([e['term'] for e in exo_eff] + zt)
    zcode = ' + '.join([_code_part(d, e) for e in exo_eff] + zc)
    if spec['no_intercept']:
        zrhs += ' - 1'
        zcode += ' - 1'
    Z = patsy.dmatrix(zrhs, d.df, return_type='dataframe', NA_action='raise')
    znames = list(Z.columns)
    excl = []
    for tname, sl in Z.design_info.term_name_slices.items():
        if any(models._same_term(tname, t) for t in zt):
            excl += list(range(sl.start, sl.stop))
    exo_z = [j for j in range(len(znames)) if j not in excl]
    Xa, Za = X.to_numpy(float), Z.to_numpy(float)
    n, k = Xa.shape
    kE, L2 = len(endo_cols), len(excl)
    elabels = [_tlabel(d, c) for c in endo_cols]
    if not kE:
        raise ValueError('no model effect holds an Endogenous column')
    if np.linalg.matrix_rank(Xa) < k:
        raise ValueError('the design is singular: some effects are not estimable (aliased); take them out of the model')
    if np.linalg.matrix_rank(Za) < Za.shape[1]:
        raise ValueError('the instruments are collinear, with each other or with the exogenous effects: take out the ones that '
                         'add nothing')
    if L2 < kE:
        raise ValueError(f'the model is not identified: {kE} endogenous column{"s" if kE > 1 else ""} ({", ".join(elabels)}) need at '
                         f'least as many excluded instrument columns, and there {"is" if L2 == 1 else "are"} {L2}: add instruments')
    if np.linalg.matrix_rank(Za.T @ Xa) < k:
        raise ValueError('the instruments do not identify the endogenous columns: their first-stage predictions are collinear '
                         '(the rank condition fails)')
    if n <= max(k, Za.shape[1]):
        raise ValueError('too few rows for this model and these instruments')
    yv = d.df[d.y_alias].astype(float)
    res = IV2SLS(yv, X, Z).fit()
    m = {'kind': 'iv', 'd': d, 'res': res, 'X': X, 'Z': Z, 'names': names, 'znames': znames, 'excl': excl, 'exo_z': exo_z,
         'endo_cols': endo_cols, 'endo_labels': elabels, 'endo_effects': [e['label'] for e in endo_eff], 'gen': gen, 'zcode': zcode,
         'coder': Coder(d, X.design_info), 'y': yv.to_numpy(float), 'xhat': np.asarray(res.exog_hat, dtype=float), 'tid': tid,
         'key': key, 'spec': spec, 'instruments': inst, 'endog': endog}
    m['rob'] = dict(rob, maxlags=rob['maxlags'] if rob['maxlags'] is not None else _nw_lags(n)) if rob and rob['type'] == 'HAC' else rob
    m['groups'], m['rob_note'] = None, None
    if m['rob'] and m['rob']['type'] == 'cluster':
        g = _cluster_codes(tid, m['rob']['cluster'], d.df.index)
        if len(np.unique(g)) < 2:
            m['rob_note'] = f'{m["rob"]["cluster"]} has a single value in these rows: no cluster-robust standard errors.'
            m['rob'] = None
        else:
            m['groups'] = g
    m['R'] = _iv_robust(m) if m['rob'] else res
    models.remember(key, m)
    return m


def _iv_robust(m):
    """The robust covariance of 2SLS with statsmodels' formulas: the scores of
    2SLS are the second stage's regressors (X projected on Z) times the
    structural residuals y - Xb, which is least squares of Xhat b + e on
    Xhat. Its get_robustcov_results gives the sandwich."""
    import statsmodels.api as sm
    b = m['res'].params.to_numpy(float)
    e = m['y'] - m['X'].to_numpy(float) @ b
    xh = pd.DataFrame(m['xhat'], columns=m['names'], index=m['X'].index)
    proxy = sm.OLS(m['xhat'] @ b + e, xh).fit()
    return _ols_robust(proxy, m['rob'], m['groups'])


def _iv_predict(m, settings, alpha):
    L = m['coder'].rows(settings)
    b = m['res'].params.to_numpy(float)
    V = np.asarray(m['R'].cov_params(), dtype=float)
    est = L @ b
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', L, V, L), 0))
    t = _tcrit(alpha, _inference_df(m['R']))
    return [{'name': m['spec']['y'][0], 'pred': est, 'lower': est - t * se, 'upper': est + t * se}]


def _iv_first_stage(m, alpha):
    """Each endogenous column regressed on the instruments: its estimates,
    RSquare, the partial RSquare and the F test of the excluded instruments
    (with the report's covariance), and Shea's partial RSquare."""
    import statsmodels.api as sm
    d, X, Z = m['d'], m['X'], m['Z']
    Za = Z.to_numpy(float)
    Lx = np.eye(Za.shape[1])[m['excl']]
    kE = len(m['endo_cols'])
    Xa = X.to_numpy(float)
    shea = None
    if kE > 1:
        A = np.linalg.inv(Xa.T @ Xa)
        B = np.linalg.inv(m['xhat'].T @ m['xhat'])
        shea = {c: float(A[j, j] / B[j, j]) for j, c in enumerate(m['names']) if c in m['endo_cols']}
    out = []
    for c, lab in zip(m['endo_cols'], m['endo_labels']):
        xj = X[c].to_numpy(float)
        fs = sm.OLS(xj, Z).fit()
        FR = _ols_robust(fs, m['rob'], m['groups'])
        ft = FR.f_test(Lx)
        F = float(np.squeeze(ft.fvalue))
        if m['exo_z']:
            ssr_r = float(sm.OLS(xj, Za[:, m['exo_z']]).fit().ssr)
        else:
            ssr_r = float(xj @ xj)
        partial = (ssr_r - float(fs.ssr)) / ssr_r if ssr_r > 0 else None
        out.append({'column': c, 'label': lab, 'rsq': float(fs.rsquared), 'partial_rsq': partial, 'shea_rsq': shea[c] if shea else partial,
                    'f': F, 'df_num': float(ft.df_num), 'df_den': float(ft.df_denom), 'p': float(np.squeeze(ft.pvalue)), 'weak': F < _WEAK_F,
                    'estimates': _est_table(d, m['znames'], fs.params.to_numpy(float), FR.cov_params(), _inference_df(FR), alpha),
                    'fitted': np.asarray(fs.fittedvalues, dtype=float), 'resid': np.asarray(fs.resid, dtype=float)})
    return out


def _cragg_donald(m):
    """Cragg and Donald's minimum eigenvalue statistic (Stock and Yogo's
    g_min, ivreg2's Cragg-Donald Wald F): the smallest eigenvalue of
    S^-1/2' Y' P Y S^-1/2 / L2, Y the endogenous columns less their
    projection on the exogenous effects, P the projection on the excluded
    instruments so reduced, S = Y' M_Z Y / (n - L). With one endogenous
    column it is the first-stage F."""
    Xa = m['X'].to_numpy(float)
    Za = m['Z'].to_numpy(float)
    n = len(Xa)
    jx = [m['names'].index(c) for c in m['endo_cols']]
    Y2 = Xa[:, jx]
    Z1, Z2 = Za[:, m['exo_z']], Za[:, m['excl']]

    def resid(A, B):
        return A - B @ np.linalg.lstsq(B, A, rcond=None)[0] if B.shape[1] else A
    Y2t, Z2t = resid(Y2, Z1), resid(Z2, Z1)
    num = Y2t.T @ (Z2t @ np.linalg.lstsq(Z2t, Y2t, rcond=None)[0])
    S = Y2.T @ resid(Y2, Za) / (n - Za.shape[1])
    Ci = np.linalg.inv(np.linalg.cholesky(S))
    G = Ci @ num @ Ci.T / Z2.shape[1]
    return float(np.min(np.linalg.eigvalsh((G + G.T) / 2)))


def _iv_tests(m, first):
    """Durbin-Wu-Hausman by the control function: the first-stage residuals
    added to the least squares fit, their F test (robust when asked);
    Durbin's chi-square n (SSR_OLS - SSR_aug) / SSR_OLS; Sargan's (or with
    robust errors Hansen's J) test of the overidentifying restrictions."""
    import statsmodels.api as sm
    import statsmodels.stats.sandwich_covariance as sw
    Xa, Za, y = m['X'].to_numpy(float), m['Z'].to_numpy(float), m['y']
    n, k = Xa.shape
    kE, L2 = len(m['endo_cols']), len(m['excl'])
    rob = m['rob']
    Vh = np.column_stack([f['resid'] for f in first])
    ols = sm.OLS(y, Xa).fit()
    aug = sm.OLS(y, np.column_stack([Xa, Vh])).fit()
    AR = _ols_robust(aug, rob, m['groups'])
    w = AR.f_test(np.eye(k + kE)[k:])
    endo = {'f': float(np.squeeze(w.fvalue)), 'df_num': float(w.df_num), 'df_den': float(w.df_denom), 'p': float(np.squeeze(w.pvalue))}
    if not rob:
        dstat = n * (float(ols.ssr) - float(aug.ssr)) / float(ols.ssr)
        endo.update({'durbin': dstat, 'durbin_df': kE, 'durbin_p': float(stats.chi2.sf(dstat, kE))})
    over = None
    if L2 > kE:
        b = m['res'].params.to_numpy(float)
        e = y - Xa @ b
        dfo = L2 - kE
        if not rob:
            s = n * float(e @ Za @ np.linalg.lstsq(Za, e, rcond=None)[0]) / float(e @ e)
            over = {'test': 'Sargan', 'stat': s, 'df': dfo, 'p': float(stats.chi2.sf(s, dfo))}
        else:
            moms = Za * e[:, None]
            if rob['type'] == 'cluster':
                S = sw.S_crosssection(moms, m['groups'])
            elif rob['type'] == 'HAC':
                S = sw.S_hac_simple(moms, nlags=int(rob['maxlags']))
            else:
                S = sw.S_white_simple(moms)
            Si = np.linalg.pinv(S)
            A = Xa.T @ Za @ Si
            bg = np.linalg.solve(A @ Za.T @ Xa, A @ Za.T @ y)   # the efficient two-step GMM estimate
            u = Za.T @ (y - Xa @ bg)
            J = float(u @ Si @ u)
            over = {'test': 'Hansen J', 'stat': J, 'df': dfo, 'p': float(stats.chi2.sf(J, dfo)), 'gmm': bg}
    return {'endog': endo, 'overid': over, 'ols': ols}


@api('fitmodel.iv')
def iv(table, y, effects=(), endog=(), instruments=(), rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, robust=None,
       ols=False, center=True, table_name='data'):
    """Instrumental Variables: two-stage least squares (statsmodels' IV2SLS)
    with the first stages, the weak-instrument statistics, the
    Durbin-Wu-Hausman endogeneity test and Sargan's (Hansen's J)
    overidentification test; OLS beside it when asked."""
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, robust=robust, endog=endog,
                 instruments=instruments, center=center)
    m = _iv_model(table, rows, spec)
    d, res, R = m['d'], m['res'], m['R']
    names = m['names']
    b = res.params.to_numpy(float)
    V = np.asarray(R.cov_params(), dtype=float)
    dfi = _inference_df(R)
    rob = m['rob']
    Xa = m['X'].to_numpy(float)
    yv = m['y']
    n, k = Xa.shape
    kE, L2 = len(m['endo_cols']), len(m['excl'])
    est = _est_table(d, names, b, V, dfi, alpha)
    et = _wald_tests(d, names, R)
    nonint = [j for j, nm in enumerate(names) if nm != 'Intercept']
    whole = None
    if nonint:
        w = R.wald_test(np.eye(k)[nonint], scalar=True, use_f=True)
        whole = {'f': float(np.squeeze(w.statistic)), 'df_num': float(w.df_num), 'df_den': float(w.df_denom), 'p': float(np.squeeze(w.pvalue))}
    first = _iv_first_stage(m, alpha)
    cd = _cragg_donald(m)
    tests = _iv_tests(m, first)
    pred = Xa @ b
    ybar = float(np.mean(yv))
    summary = [{'stat': 'RSquare', 'value': float(res.rsquared)}, {'stat': 'RSquare Adj', 'value': float(res.rsquared_adj)},
               {'stat': 'Root Mean Square Error', 'value': float(math.sqrt(res.mse_resid))}, {'stat': 'Mean of Response', 'value': ybar},
               {'stat': 'Observations', 'value': float(n)}]
    ng = int(len(np.unique(m['groups']))) if m['groups'] is not None else None
    out = {'y': spec['y'][0], 'n': n, 'key': m['key'], 'alpha': alpha, 'summary': rtable([col('stat', '', 'text'), col('value', '')], summary),
           'whole': whole, 'estimates': est, 'effect_tests': et, 'factors': _factors(d), 'dfi': dfi, 'k': k,
           'model': {'response': spec['y'][0], 'endogenous': m['endog'], 'endogenous_columns': m['endo_labels'], 'instruments': m['instruments'],
                     'generated': m['gen'], 'excluded': L2, 'k_endog': kE, 'overidentified': L2 - kE,
                     'cov': _robust_label(rob, groups=ng) if rob else 'Classical (homoscedastic)', 'n': n},
           'first': [{kk: v for kk, v in f.items() if kk not in ('fitted', 'resid')} for f in first],
           'weak': {'cragg_donald': cd, 'k_endog': kE, 'excluded': L2},
           'tests': {'endog': tests['endog'], 'overid': {kk: v for kk, v in (tests['overid'] or {}).items() if kk != 'gmm'} or None},
           'diag': {'rows': [int(i) for i in d.df.index], 'actual': yv, 'predicted': pred, 'residual': yv - pred,
                    'first': [{'label': f['label'], 'fitted': f['fitted'], 'resid': f['resid']} for f in first]},
           'robust': {'type': rob['type'], 'label': _robust_label(rob, groups=ng), 'df': dfi, 'clusters': ng, 'maxlags': rob.get('maxlags')} if rob else None}
    if ols:
        O = _ols_robust(tests['ols'], rob, m['groups'])
        eo = _est_table(d, names, O.params, O.cov_params(), _inference_df(O), alpha)
        by = {r['name']: r for r in eo['rows']}
        rows_c = []
        for r in est['rows']:
            o_ = by[r['name']]
            rows_c.append({'term': r['term'], 'ols': o_['estimate'], 'ols_se': o_['se'], 'iv': r['estimate'], 'iv_se': r['se'],
                           'diff': r['estimate'] - o_['estimate'], 'ratio': r['se'] / o_['se'] if o_['se'] else None})
        out['ols'] = rtable([col('term', 'Term', 'text'), col('ols', 'OLS Estimate'), col('ols_se', 'OLS Std Error'), col('iv', '2SLS Estimate'),
                             col('iv_se', '2SLS Std Error'), col('diff', '2SLS − OLS'), col('ratio', 'Std Error Ratio')], rows_c)
        out['ols_rsq'] = float(tests['ols'].rsquared)
    notes = ['Two-stage least squares (statsmodels\' IV2SLS): each endogenous column is regressed on the instruments (the exogenous '
             'effects and the excluded instruments), and Y on the exogenous effects and the predicted endogenous columns. The standard '
             'errors use the residuals of the model itself, y − Xb, with σ² = SSR/(n − p) and t tests on n − p DF, as Stata\'s ivregress '
             '2sls, small and R\'s ivreg; without small, Stata and ivreg2 give z tests with σ² = SSR/n. JMP has no instrumental-variables '
             'platform.',
             'RSquare is 1 − SSR/TSS with those residuals: it can be negative and is no guide to the fit of 2SLS.']
    if m['gen']:
        notes.append('An endogenous crossing or power is instrumented by the same crossing or power of the instruments (Wooldridge 2010, '
                     'section 9.5): ' + '; '.join(f'{g["instrument"]} for {g["effect"]}' for g in m['gen']) + '.')
    weak = [f['label'] for f in first if f['weak']]
    if rob:
        notes.append(_iv_robust_note(rob, dfi, ng))
    if m.get('rob_note'):
        notes.append(m['rob_note'])
    if any(data.meta(table, nm).get('modelingType') == 'ordinal' for nm in _factor_names(d) + list(m['instruments'])):
        notes.append('Ordinal columns are coded like nominal ones (effect coding).')
    out['notes'] = notes
    out['weak_columns'] = weak
    out['code'] = _iv_code(m, table, table_name, rows, tests, ols)
    out['plot_code'] = _iv_plots(m, table, rows, table_name)
    return out


def _iv_robust_note(rob, dfi, groups):
    t = rob['type']
    what = {'HC0': 'White\'s heteroscedasticity-consistent covariance (HC0)', 'HC1': 'HC1 (HC0 times n/(n − p), Stata\'s ivregress, vce(robust) small)',
            'HC2': 'HC2', 'HC3': 'HC3', 'HAC': f'Newey and West\'s HAC covariance over {rob.get("maxlags")} lags, the rows in the order of the table',
            'cluster': f'the cluster-robust covariance by {rob.get("cluster")} ({groups} clusters), with the factor G/(G − 1)·(n − 1)/(n − p)'}[t]
    s = (f'Robust Standard Errors: {what}. The scores of 2SLS are the second stage\'s regressors X̂ (X projected on the instruments) times '
         'the residuals y − Xb, and statsmodels\' get_robustcov_results makes the sandwich from them; the second stage\'s estimates, Effect '
         'Tests, the first-stage F tests, the Wu–Hausman test and the profiler use it. The overidentification test is Hansen\'s J of the '
         'efficient two-step GMM estimate, with the matching weight matrix, as ivreg2 reports it.')
    if t in ('HC2', 'HC3'):
        s += (' HC2 and HC3 take the leverages of the second stage, the diagonal of X̂(X̂′X̂)⁻¹X̂′; Stata\'s ivregress and ivreg2 offer only '
              'the HC0 and HC1 forms, and Hansen\'s J uses White\'s (HC0) weights here.')
    return s + f' t and F tests on {("the clusters less one, " + _fmt_df(dfi) + " DF") if t == "cluster" else _fmt_df(dfi) + " DF"}.'


def _iv_code(m, table, table_name, rows, tests, ols):
    d = m['d']
    y = m['spec']['y'][0]
    rob = m['rob']
    ccol = rob['cluster'] if rob and rob['type'] == 'cluster' else None
    lines = _code_frame(d, table, table_name, rows, [ccol], ['import patsy', 'from statsmodels.sandbox.regression.gmm import IV2SLS'])
    lines.append(f'X = patsy.dmatrix({json.dumps(_code_formula(d, lhs=False))}, d, return_type="dataframe")   # the model: effect coded, '
                 'crossings centred')
    lines.append(f'Z = patsy.dmatrix({json.dumps(m["zcode"])}, d, return_type="dataframe")   # the instruments: the exogenous effects '
                 'and the excluded instruments')
    lines.append(f'y = d[{json.dumps(y)}]')
    lines.append('fit = IV2SLS(y, X, Z).fit()   # two-stage least squares: t tests on n - p DF')
    lines.append('print(fit.summary())')
    endo = [m['names'].index(c) for c in m['endo_cols']]
    lines.append(f'endog, excl = {endo}, {m["excl"]}   # the endogenous columns of X; the excluded instruments\' columns of Z')
    if rob:
        t = rob['type']
        if t == 'HAC':
            kw = f'cov_type="HAC", maxlags={int(rob["maxlags"])}'
        elif t == 'cluster':
            kw = f'cov_type="cluster", groups=pd.factorize(d[{json.dumps(ccol)}], sort=True)[0]'
        else:
            kw = f'cov_type="{t}"'
        lines.append(f'robust = dict({kw}, use_t=True)   # Robust Standard Errors')
        lines.append('xhat = fit.exog_hat   # the second stage\'s regressors: X projected on Z')
        lines.append('rob = sm.OLS(xhat @ fit.params.to_numpy() + fit.resid.to_numpy(), xhat).fit().get_robustcov_results(**robust)   '
                     '# 2SLS\'s sandwich: scores xhat * (y - Xb)')
        lines.append('print(rob.bse, rob.tvalues)')
        fit_ = '.get_robustcov_results(**robust)'
    else:
        fit_ = ''
    lines.append('for j in endog:   # the first stages: each endogenous column on Z, the F test of the excluded instruments')
    lines.append(f'    fs = sm.OLS(X.iloc[:, j], Z).fit(){fit_}')
    lines.append('    print(X.columns[j], fs.rsquared, fs.f_test(np.eye(Z.shape[1])[excl]))')
    lines.append('V = np.column_stack([sm.OLS(X.iloc[:, j], Z).fit().resid for j in endog])   # the first-stage residuals')
    lines.append(f'aug = sm.OLS(y, np.column_stack([X, V])).fit(){fit_}')
    lines.append('print(aug.f_test(np.eye(X.shape[1] + V.shape[1])[X.shape[1]:]))   # Wu-Hausman F: H0 the endogenous columns are exogenous')
    if not rob:
        lines.append('ols = sm.OLS(y, X).fit(); print(len(y) * (ols.ssr - sm.OLS(y, np.column_stack([X, V])).fit().ssr) / ols.ssr)   # Durbin chi2')
    over = tests.get('overid')
    if over and over['test'] == 'Sargan':
        lines.append('e, Za = fit.resid.to_numpy(), np.asarray(Z)')
        lines.append('print(len(e) * e @ Za @ np.linalg.lstsq(Za, e, rcond=None)[0] / (e @ e))   # Sargan chi2: n times R2 of e on Z')
    elif over:
        lines.append('import statsmodels.stats.sandwich_covariance as sw')
        lines.append('e, Za, Xa, ya = fit.resid.to_numpy(), np.asarray(Z), np.asarray(X), y.to_numpy()')
        if rob['type'] == 'cluster':
            lines.append('S = sw.S_crosssection(Za * e[:, None], robust["groups"])')
        elif rob['type'] == 'HAC':
            lines.append(f'S = sw.S_hac_simple(Za * e[:, None], nlags={int(rob["maxlags"])})')
        else:
            lines.append('S = sw.S_white_simple(Za * e[:, None])')
        lines.append('W = np.linalg.pinv(S); A = Xa.T @ Za @ W; bg = np.linalg.solve(A @ Za.T @ Xa, A @ Za.T @ ya)   # two-step GMM')
        lines.append('u = Za.T @ (ya - Xa @ bg); print(u @ W @ u)   # Hansen J')
    if ols:
        lines.append(f'print(sm.OLS(y, X).fit(){fit_}.summary())   # least squares, for contrast')
    lines += _centred_code(d)
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Quantile Regression
# ---------------------------------------------------------------------------

_QR_KERNEL = {'epa': 'Epanechnikov', 'gau': 'Gaussian', 'cos': 'Cosine', 'par': 'Parzen', 'biw': 'Biweight'}
_QR_BANDWIDTH = {'hsheather': 'Hall–Sheather', 'bofinger': 'Bofinger', 'chamberlain': 'Chamberlain'}
_QR_COV = {'robust': 'Robust (statsmodels)', 'iid': 'IID', 'powell': 'Powell sandwich'}
_QR_PROCESS = [round(0.05 * i, 2) for i in range(1, 20)]
_QR_LINES = [0.1, 0.25, 0.5, 0.75, 0.9]
_QR_MAXITER = 5000   # IRLS iterations: statsmodels' 1000 stop short at some quantiles (0.1 of the schooling example needs 1234)


def _qr_opts(spec):
    tau = 0.5 if spec.get('tau') is None else float(spec['tau'])
    if not 0 < tau < 1:
        raise ValueError('the quantile τ must lie strictly between 0 and 1')
    cov = spec.get('qr_cov') or 'robust'
    kernel = spec.get('kernel') or 'epa'
    bw = spec.get('bandwidth') or 'hsheather'
    if cov not in _QR_COV:
        raise ValueError(f'no standard errors {cov!r}: choose robust, iid or powell')
    if kernel not in _QR_KERNEL:
        raise ValueError(f'no kernel {kernel!r}: choose one of {", ".join(_QR_KERNEL)}')
    if bw not in _QR_BANDWIDTH:
        raise ValueError(f'no bandwidth {bw!r}: choose hsheather, bofinger or chamberlain')
    return tau, cov, kernel, bw


def _qr_model(tid, rows, spec):
    """A quantile regression at the spec's tau: the design and the fits of
    every quantile asked for so far (the report's tau, the quantile process,
    the lines) are shared by the specs that differ only in tau, so a new
    quantile reuses them."""
    base = _qr_base(tid, rows, dict(spec, tau=None))
    tau = _qr_opts(spec)[0]
    m = dict(base, tau=tau)
    m['res'], m['V'] = _qr_fit(base, tau)
    return m


def _qr_base(tid, rows, spec):
    key = _key('qr', tid, rows, spec)
    m = models.recall(key)
    if m is not None:
        return m
    ys = spec['y']
    if not ys:
        raise ValueError('choose a Y')
    if spec['weight'] or spec['freq']:
        raise ValueError('statsmodels\' QuantReg takes no weights: remove Weight and Freq for Quantile Regression')
    effs = _eff_of(spec)
    if any(e['random'] for e in effs):
        raise ValueError('Quantile Regression takes fixed effects only: take the Random Effect attribute off the effects')
    tau, cov, kernel, bw = _qr_opts(spec)
    d = _design(tid, ys[0], effs, rows, None, None, not spec['no_intercept'], center=spec.get('center', True))
    if isinstance(d.df[d.y_alias].dtype, pd.CategoricalDtype):
        raise ValueError(f'{ys[0]} is {data.meta(tid, ys[0]).get("modelingType")}: Quantile Regression needs a continuous Y')
    X = _matrix(d)
    if len(d.df) <= X.shape[1] + 1:
        raise ValueError('too few rows for the model')
    m = {'kind': 'qr', 'd': d, 'X': X, 'y': d.df[d.y_alias].astype(float), 'names': list(X.columns), 'coder': Coder(d, X.design_info),
         'fits': {}, 'cov': cov, 'kernel': kernel, 'bw': bw, 'tid': tid, 'key': key, 'spec': spec}
    models.remember(key, m)
    return m


def _qr_fit(m, tau):
    """statsmodels' QuantReg at one quantile, and the covariance the report
    uses: statsmodels' robust or iid, or Powell's kernel sandwich."""
    tk = round(float(tau), 10)
    if tk in m['fits']:
        return m['fits'][tk]
    from statsmodels.regression.quantile_regression import QuantReg
    res = QuantReg(m['y'], m['X']).fit(q=float(tau), vcov='iid' if m['cov'] == 'iid' else 'robust', kernel=m['kernel'], bandwidth=m['bw'],
                                        max_iter=_QR_MAXITER)
    V = _qr_powell(m, res, float(tau)) if m['cov'] == 'powell' else np.asarray(res.cov_params(), dtype=float)
    m['fits'][tk] = (res, V)
    return res, V


def _qr_powell(m, res, tau):
    """Powell's (1991) kernel sandwich, tau (1 - tau) (X'FX)^-1 X'X (X'FX)^-1,
    F the kernel density of each row's residual, K(e/h)/h, with
    statsmodels' kernel and its bandwidth h."""
    from statsmodels.regression.quantile_regression import kernels
    X = m['X'].to_numpy(float)
    e = np.asarray(res.resid, dtype=float)
    h = float(res.bandwidth)
    f = kernels[m['kernel']](e / h) / h
    A = np.linalg.pinv((X * f[:, None]).T @ X)
    return tau * (1 - tau) * A @ (X.T @ X) @ A


def _qr_null_loss(y, tau):
    """The check loss of the model with only an intercept: at the sample
    tau-quantile, an order statistic, which minimises it."""
    ys = np.sort(np.asarray(y, dtype=float))
    n = len(ys)
    k = int(math.ceil(n * tau)) - 1
    return min(_check_loss(ys - ys[j], tau) for j in range(max(0, k - 1), min(n, k + 2)))


def _qr_stats(m, res, tau):
    y = m['y'].to_numpy(float)
    e = y - m['X'].to_numpy(float) @ res.params.to_numpy(float)
    v1 = _check_loss(e, tau)
    v0 = _qr_null_loss(y, tau)
    return {'v1': v1, 'v0': v0, 'r1': 1 - v1 / v0 if v0 > 0 else None, 'below': float(np.mean(e < 0)), 'sparsity': float(res.sparsity),
            'bandwidth': float(res.bandwidth), 'iterations': int(res.iterations), 'prsquared': float(res.prsquared)}


def _qr_predict(m, settings, alpha):
    L = m['coder'].rows(settings)
    res, V = m['res'], m['V']
    est = L @ res.params.to_numpy(float)
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', L, V, L), 0))
    t = _tcrit(alpha, float(res.df_resid))
    return [{'name': f'{m["spec"]["y"][0]} (quantile {m["tau"]:g})', 'pred': est, 'lower': est - t * se, 'upper': est + t * se}]


def _qr_taus(taus):
    """The quantiles of the process: the page's list, else 0.05 to 0.95."""
    if not taus:
        return list(_QR_PROCESS)
    out = sorted({round(float(t), 6) for t in taus if 0 < float(t) < 1})
    if not out:
        raise ValueError('the quantile process needs quantiles strictly between 0 and 1')
    if len(out) > 99:
        raise ValueError('the quantile process takes at most 99 quantiles')
    return out


@api('fitmodel.quantreg')
def quantreg(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, tau=0.5, qr_cov='robust', kernel='epa',
             bandwidth='hsheather', taus=None, process=True, alpha=0.05, center=True, table_name='data'):
    """Quantile Regression (statsmodels' QuantReg): the estimates at tau, the
    Koenker-Machado pseudo RSquare, the quantile process (each coefficient
    over a list of quantiles, with the OLS estimate beside it) and, for
    one continuous factor, the fitted lines of several quantiles."""
    import statsmodels.api as sm
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, tau=tau, qr_cov=qr_cov, kernel=kernel,
                 bandwidth=bandwidth, center=center)
    m = _qr_model(table, rows, spec)
    d, res, V = m['d'], m['res'], m['V']
    tau = m['tau']
    names = m['names']
    dfr = float(res.df_resid)
    est = _est_table(d, names, res.params.to_numpy(float), V, dfr, alpha)
    st = _qr_stats(m, res, tau)
    yv = m['y'].to_numpy(float)
    Xa = m['X'].to_numpy(float)
    n = len(yv)
    pred = Xa @ res.params.to_numpy(float)
    summary = [{'stat': 'Quantile (τ)', 'value': tau}, {'stat': 'Pseudo RSquare (Koenker–Machado)', 'value': st['r1']},
               {'stat': 'Sum of Check Losses', 'value': st['v1']}, {'stat': 'Sum of Check Losses, Intercept Only', 'value': st['v0']},
               {'stat': 'Share of Rows Below the Fit', 'value': st['below']}, {'stat': 'Sparsity (1/f̂(0))', 'value': st['sparsity']},
               {'stat': 'Bandwidth', 'value': st['bandwidth']}, {'stat': 'Iterations', 'value': st['iterations']},
               {'stat': 'Observations', 'value': float(n)}]
    ols = sm.OLS(m['y'], m['X']).fit()
    T = _uncenter(d, names)
    # the terms in the effects' order, as the estimates table
    order = [names.index(r['name']) for r in est['rows']]
    labels = [r['term'] for r in est['rows']]

    def jmp(b, Vb):
        b, Vb = np.asarray(b, dtype=float), np.asarray(Vb, dtype=float)
        if T is not None:
            b, Vb = T @ b, T @ Vb @ T.T
        return b, np.sqrt(np.maximum(np.diag(Vb), 0))
    bo, so = jmp(ols.params, ols.cov_params())
    to = _tcrit(alpha, float(ols.df_resid))
    out = {'y': spec['y'][0], 'tau': tau, 'n': n, 'key': _key('qr', table, rows, spec), 'alpha': alpha, 'estimates': est,
           'summary': rtable([col('stat', '', 'text'), col('value', '')], summary), 'stats': st, 'factors': _factors(d),
           'model': {'response': spec['y'][0], 'tau': tau, 'cov': m['cov'], 'cov_label': _QR_COV[m['cov']], 'kernel': m['kernel'],
                     'kernel_label': _QR_KERNEL[m['kernel']], 'bandwidth': m['bw'], 'bandwidth_label': _QR_BANDWIDTH[m['bw']], 'n': n},
           'ols': {'terms': labels, 'estimate': [float(bo[j]) for j in order], 'lower': [float(bo[j] - to * so[j]) for j in order],
                   'upper': [float(bo[j] + to * so[j]) for j in order]},
           'diag': {'rows': [int(i) for i in d.df.index], 'actual': yv, 'predicted': pred, 'residual': yv - pred}}
    taus_p = _qr_taus(taus)
    if process:
        proc = {'taus': taus_p, 'terms': labels, 'estimate': [[] for _ in labels], 'se': [[] for _ in labels], 'lower': [[] for _ in labels],
                'upper': [[] for _ in labels], 'r1': []}
        for t in taus_p:
            rt_, Vt = _qr_fit(m, t)
            b, s = jmp(rt_.params, Vt)
            tc = _tcrit(alpha, float(rt_.df_resid))
            for i, j in enumerate(order):
                proc['estimate'][i].append(float(b[j]))
                proc['se'][i].append(float(s[j]))
                proc['lower'][i].append(float(b[j] - tc * s[j]))
                proc['upper'][i].append(float(b[j] + tc * s[j]))
            proc['r1'].append(_qr_stats(m, rt_, t)['r1'])
        out['process'] = proc
    # the fitted quantile lines of one continuous factor (its powers allowed)
    facs = _factors(d)
    if len(facs) == 1 and facs[0]['type'] == 'continuous':
        f = facs[0]
        a = d.alias[f['name']]
        gx = np.linspace(f['min'], f['max'], 61)
        L = m['coder'].rows([{a: float(v)} for v in gx])
        lines = []
        for t in sorted(set(_QR_LINES + [tau])):
            rt_, _Vt = _qr_fit(m, t)
            lines.append({'tau': t, 'y': L @ rt_.params.to_numpy(float), 'current': abs(t - tau) < 1e-9})
        out['lines'] = {'factor': f['name'], 'x': gx, 'lines': lines, 'ols': L @ ols.params.to_numpy(float),
                        'points': {'x': d.df[a].to_numpy(float), 'y': yv, 'rows': out['diag']['rows']}}
    notes = [f'Quantile regression (Koenker and Bassett 1978) estimates the {tau:g}-quantile of {spec["y"][0]} given the effects by '
             'minimising the sum of check losses, u·(τ − [u < 0]); statsmodels\' QuantReg solves it by iteratively reweighted least squares '
             f'(to 1e-6 in the estimates, at most {_QR_MAXITER} iterations where statsmodels stops at 1000), not by the linear program of R\'s quantreg (rq) or Stata\'s qreg, so the estimates agree with '
             'theirs to about that tolerance. t tests on n − p DF, as Stata and R. JMP Pro fits quantile regression in Generalized '
             'Regression (without the quantile process); JMP has none.',
             'Pseudo RSquare is Koenker and Machado\'s (1999) R¹ = 1 − V(τ)/Ṽ(τ), V the check loss of the fit and Ṽ that of the model with '
             'only an intercept (at the sample τ-quantile), as Stata\'s qreg reports it; statsmodels\' prsquared takes the unconditional '
             f'quantile by interpolation instead ({st["prsquared"]:.6g} here).']
    covnote = {'robust': (f'Standard errors: statsmodels\' robust covariance, (X′X)⁻¹X′DX(X′X)⁻¹ with D the squared scores (τ or 1 − τ over '
                          f'one kernel estimate f̂(0) of the residuals\' density at zero, {_QR_KERNEL[m["kernel"]]} kernel, '
                          f'{_QR_BANDWIDTH[m["bw"]]} bandwidth; Greene 2008). One density for every row makes it close to the iid formula '
                          '(at the median it is the iid formula exactly): it does not follow a density that changes with the regressors. '
                          'Powell\'s sandwich does (R\'s quantreg se = "ker"; choose it in Model Launch when the spread changes with X).'),
               'iid': (f'Standard errors: the iid formula τ(1 − τ)/f̂(0)²·(X′X)⁻¹ (statsmodels\' vcov="iid", Stata\'s qreg default), the '
                       f'sparsity 1/f̂(0) from a {_QR_KERNEL[m["kernel"]]} kernel with the {_QR_BANDWIDTH[m["bw"]]} bandwidth: right when the '
                       'errors have the same distribution in every row.'),
               'powell': (f'Standard errors: Powell\'s (1991) kernel sandwich τ(1 − τ)(X′FX)⁻¹X′X(X′FX)⁻¹, F the density of each row\'s '
                          f'residual K(e/h)/h (computed here from statsmodels\' residuals, its {_QR_KERNEL[m["kernel"]]} kernel and its '
                          f'{_QR_BANDWIDTH[m["bw"]]} bandwidth h = {st["bandwidth"]:.6g}); consistent when the errors\' spread changes with '
                          'the regressors, like R\'s quantreg se = "ker" (a Gaussian kernel with the bandwidth scaled by the residuals).')}[m['cov']]
    notes.append(covnote)
    if process:
        notes.append('The quantile process: each coefficient fitted at every quantile of the list, with its pointwise confidence band; the '
                     'dashed line and the shaded band are the least squares estimate and its confidence interval. A slope that changes with '
                     'τ means the effect differs across the distribution (the spread of Y changes with that term).')
    if any(data.meta(table, nm).get('modelingType') == 'ordinal' for nm in _factor_names(d)):
        notes.append('Ordinal factors are coded like nominal ones (effect coding).')
    out['notes'] = notes
    out['code'] = _qr_code(m, table, table_name, rows, taus_p if process else None, alpha)
    out['plot_code'] = _qr_plots(m, table, rows, table_name, out)
    return out


def _qr_code(m, table, table_name, rows, taus, alpha):
    d = m['d']
    y = m['spec']['y'][0]
    lines = _code_frame(d, table, table_name, rows, [], ['import patsy', 'from statsmodels.regression.quantile_regression import QuantReg, kernels'])
    lines.append(f'X = patsy.dmatrix({json.dumps(_code_formula(d, lhs=False))}, d, return_type="dataframe")   # the design, effect coded')
    lines.append(f'y = d[{json.dumps(y)}]')
    vc = 'iid' if m['cov'] == 'iid' else 'robust'
    opts = f'vcov={vc!r}, kernel={m["kernel"]!r}, bandwidth={m["bw"]!r}, max_iter={_QR_MAXITER}'
    lines.append(f'tau = {m["tau"]!r}')
    lines.append(f'fit = QuantReg(y, X).fit(q=tau, {opts})   # IRLS; t tests on n - p DF')
    lines.append('print(fit.summary())')
    if m['cov'] == 'powell':
        lines.append('Xa, e = np.asarray(X), fit.resid.to_numpy(); f = kernels[' + repr(m['kernel']) + '](e / fit.bandwidth) / fit.bandwidth')
        lines.append('A = np.linalg.pinv((Xa * f[:, None]).T @ Xa); V = tau * (1 - tau) * A @ Xa.T @ Xa @ A   # Powell\'s sandwich')
        lines.append('print(np.sqrt(np.diag(V)))   # its standard errors')
    lines.append('rho = lambda u: np.sum(u * (tau - (u < 0)))   # the check loss')
    lines.append('ys = np.sort(y.to_numpy()); k = int(np.ceil(len(ys) * tau)) - 1')
    lines.append('v0 = min(rho(ys - ys[j]) for j in range(max(0, k - 1), min(len(ys), k + 2)))   # the intercept-only fit: the sample quantile')
    lines.append('print(1 - rho(fit.resid.to_numpy()) / v0)   # Koenker and Machado\'s pseudo RSquare')
    if taus:
        lines.append(f'taus = {taus!r}')
        lines.append(f'process = pd.DataFrame({{t: QuantReg(y, X).fit(q=t, {opts}).params for t in taus}}).T   # the quantile process')
        lines.append('print(process)')
        lines.append(f'print(sm.OLS(y, X).fit().conf_int({alpha!r}))   # the least squares reference')
    lines += _centred_code(d)
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Recursive and Rolling Regression (Standard Least Squares)
# ---------------------------------------------------------------------------

def _rr_order(tid, d, order_by):
    """The positions of the model's rows in the order of the recursion: the
    table's, or sorted by a column (stably; a categorical column by its
    level order); rows without a value of that column are left out."""
    n = len(d.df)
    if not order_by:
        return np.arange(n), None, 0
    if order_by not in data.TABLES[tid]['meta']:
        raise ValueError(f'no column {order_by!r} to sort by')
    s = data.series(tid, order_by, d.df.index, as_category=True)
    if isinstance(s.dtype, pd.CategoricalDtype):
        v = s.cat.codes.to_numpy().astype(float)
        v[v < 0] = np.nan
        shown = [None if not np.isfinite(x) else _lvl(s.cat.categories[int(x)]) for x in v]
    else:
        v = s.to_numpy(float)
        shown = [None if not np.isfinite(x) else float(x) for x in v]
    ok = np.flatnonzero(np.isfinite(v))
    pos = ok[np.argsort(v[ok], kind='stable')]
    return pos, [shown[i] for i in pos], n - len(ok)


@api('fitmodel.recursive')
def recursive(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, order_by=None, alpha=0.05, conf=0.05,
              window=None, rolling=False, validation=None, center=True, table_name='data'):
    """Recursive least squares (statsmodels' RecursiveLS) of the least squares
    model with the rows taken one at a time, in the table's order or sorted
    by a column: the recursive estimates with their bands, the CUSUM and
    CUSUM of squares of the recursive residuals with their significance
    bounds (alpha: 0.01, 0.05 or 0.10); rolling least squares (statsmodels'
    RollingOLS) over windows of a number of rows when asked."""
    from statsmodels.regression.recursive_ls import RecursiveLS
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, validation=validation, center=center)
    if freq:
        raise ValueError('Recursive and rolling fits take the rows one at a time: remove Freq (a Weight is fine)')
    m = _ls_model(table, rows, spec)
    d, res = m['d'], m['res']
    names = list(res.params.index)
    Xw = np.asarray(res.model.wexog, dtype=float)
    yw = np.asarray(res.model.wendog, dtype=float)
    k = Xw.shape[1]
    if res.model.rank < k:
        raise ValueError('the design is singular: recursive estimates need every parameter estimable')
    pos, shown, dropped = _rr_order(table, d, order_by)
    no = len(pos)
    if no <= k + 3:
        raise ValueError('too few rows for recursive estimates')
    Xo, yo = Xw[pos], yw[pos]
    if np.linalg.matrix_rank(Xo) < k:
        raise ValueError('the rows left do not identify the model')
    rows_o = [int(i) for i in np.asarray(d.df.index)[pos]]
    rr = RecursiveLS(yo, Xo).fit()
    d0 = int(max(rr.nobs_diffuse, rr.loglikelihood_burn))
    if d0 >= no - 2:
        raise ValueError('the recursion starts too late: the design has full rank only after the last rows (sort by another column)')
    T = _uncenter(d, names)
    coef = rr.recursive_coefficients
    B = np.asarray(coef.filtered, dtype=float)           # k x n
    C = np.asarray(coef.filtered_cov, dtype=float)       # k x k x n
    if T is not None:
        B = T @ B
        C = np.einsum('ij,jkt,lk->ilt', T, C, T)
    z = float(stats.norm.ppf(1 - float(alpha) / 2))
    t_obs = np.arange(d0 + 1, no + 1)                    # the observations after the start, counted in the order
    est_rows = sorted(range(k), key=lambda j: -1 if names[j] == 'Intercept' else next((i for i, e in enumerate(d.effects) if names[j] in e.get('terms', [])), len(d.effects)))
    bfull = (T @ res.params.to_numpy(float)) if T is not None else res.params.to_numpy(float)
    recs = []
    for j in est_rows:
        se = np.sqrt(np.maximum(C[j, j, d0:], 0))
        recs.append({'term': _tlabel(d, names[j]), 'estimate': B[j, d0:], 'lower': B[j, d0:] - z * se, 'upper': B[j, d0:] + z * se,
                     'full': float(bfull[j])})
    conf = float(conf)
    if conf not in (0.01, 0.05, 0.1):
        raise ValueError('the CUSUM bounds are for the 1%, 5% or 10% level')
    W = np.asarray(rr.cusum, dtype=float)
    tmp = math.sqrt(no - d0)
    if conf == 0.1:
        # statsmodels 0.14 takes 0.950 for 10%, a slip for Brown, Durbin and Evans's 0.850
        a = 0.850
        up = a * tmp + 2 * a * (t_obs - d0) / tmp
        lo = -up
    else:
        lo, up = rr._cusum_significance_bounds(conf, points=t_obs)
        a = float(up[-1]) / (3 * tmp)
    crossed = np.flatnonzero(np.abs(W) > up)
    cusum = {'x': t_obs, 'y': W, 'lower': lo, 'upper': up, 'rows': rows_o[d0:], 'crossed': bool(len(crossed)),
             'first': int(t_obs[crossed[0]]) if len(crossed) else None, 'first_row': rows_o[d0 + int(crossed[0])] if len(crossed) else None,
             'ratio': float(np.max(np.abs(W) / up)), 'constant': float(a)}
    S = np.asarray(rr.cusum_squares, dtype=float)
    lo2, up2 = rr._cusum_squares_significance_bounds(conf, points=t_obs)
    line = (t_obs - d0) / (no - d0)
    crit = float(up2[0] - line[0])
    dev = S - line
    crossed2 = np.flatnonzero(np.abs(dev) > crit)
    jmax = int(np.argmax(np.abs(dev)))
    cusumsq = {'x': t_obs, 'y': S, 'lower': lo2, 'upper': up2, 'line': line, 'rows': rows_o[d0:], 'crit': crit,
               'dev': float(np.abs(dev[jmax])), 'at': int(t_obs[jmax]), 'at_row': rows_o[d0 + jmax], 'crossed': bool(len(crossed2)),
               'first': int(t_obs[crossed2[0]]) if len(crossed2) else None, 'first_row': rows_o[d0 + int(crossed2[0])] if len(crossed2) else None}
    out = {'n': no, 'k': k, 'start': d0, 'order': {'by': order_by, 'rows': rows_o, 'values': shown, 'dropped': dropped},
           'recursive': recs, 'resid': np.asarray(rr.resid_recursive, dtype=float)[d0:], 'cusum': cusum, 'cusumsq': cusumsq, 'alpha': alpha,
           'conf': conf, 'weighted': d.weights is not None}
    w = None
    if rolling:
        from statsmodels.regression.rolling import RollingOLS
        w = int(window) if window not in (None, '') else min(no, max(3 * k, int(round(no / 10))))
        if not k < w <= no:
            raise ValueError(f'the window must hold more rows than the {k} parameters and at most the {no} rows')
        ro = RollingOLS(yo, Xo, window=w).fit(use_t=True)
        P = np.asarray(ro.params, dtype=float)             # n x k
        Cv = np.asarray(ro.cov_params(), dtype=float)       # n x k x k
        if T is not None:
            P = P @ T.T
            Cv = np.einsum('ij,tjk,lk->til', T, Cv, T)
        dfr = np.asarray(ro.df_resid, dtype=float)
        with np.errstate(invalid='ignore'):
            tc = stats.t.ppf(1 - float(alpha) / 2, dfr)
        first = w - 1
        roll = []
        for j in est_rows:
            se = np.sqrt(np.maximum(Cv[first:, j, j], 0))
            roll.append({'term': _tlabel(d, names[j]), 'estimate': P[first:, j], 'lower': P[first:, j] - tc[first:] * se,
                         'upper': P[first:, j] + tc[first:] * se, 'full': float(bfull[j])})
        missing = int(np.sum(~np.isfinite(P[first:, 0])))
        out['rolling'] = {'window': w, 'x': np.arange(w, no + 1), 'terms': roll, 'singular': missing}
    notes = [f'The rows are taken one at a time {("sorted by " + order_by) if order_by else "in the order of the table"}; the recursive '
             f'estimates after t rows are least squares on those rows (statsmodels\' RecursiveLS, a Kalman filter with a diffuse start), '
             f'the last are the report\'s. The first {d0} rows start the recursion (until every parameter is estimable); after them each '
             f'row gives a recursive residual, its prediction error from the rows before it scaled to a common variance. The bands are '
             f'±{z:.4g} standard errors, with the full-sample σ, as statsmodels\' plot_recursive_coefficient draws them.',
             'CUSUM (Brown, Durbin and Evans 1975): the cumulative sum of the recursive residuals over their standard deviation. With '
             'stable coefficients it wanders about zero; a drift out of the bounds ±a(√(n − k) + 2(t − k)/√(n − k)) says the '
             'coefficients change along the order (a = 0.948 at 5%, 1.143 at 1%, 0.850 at 10%). CUSUM of squares: the cumulative share '
             'of the squared recursive residuals, which rises along the diagonal (t − k)/(n − k) when the coefficients and the variance '
             'are stable; its bounds are statsmodels\' (Edgerton and Wells\'s 1994 approximation to Durbin\'s 1969 critical values). '
             'The CUSUM finds shifts in the mean of Y along the order, the CUSUM of squares changes in the variance or in the slopes. Both '
             'are exact only for fixed regressors in the order, and say nothing about which coefficient moved: the recursive estimates do.',
             'The recursive residuals are those of R\'s strucchange (recresid) and Stata\'s cusum6. statsmodels scales the CUSUM by the '
             'standard deviation of all the recursive residuals and starts it at the first of them, as Brown, Durbin and Evans; cusum6 '
             'starts one row later and R\'s efp (Rec-CUSUM) scales it otherwise, so their paths and bounds differ slightly. JMP has no '
             'recursive or rolling fits.']
    if conf == 0.1:
        notes.append('At the 10% level the CUSUM bounds use a = 0.850 (Brown, Durbin and Evans); statsmodels 0.14\'s '
                     '_cusum_significance_bounds takes 0.950, a slip.')
    if dropped:
        notes.append(f'{dropped} row{"s" if dropped > 1 else ""} without a value of {order_by} {"are" if dropped > 1 else "is"} left out of '
                     'the recursion: its last estimates are least squares on the rows left.')
    if d.weights is not None:
        notes.append('With a Weight the recursion runs on the weighted regression as plain least squares on the data times √w.')
    if rolling:
        notes.append(f'Rolling regression (statsmodels\' RollingOLS): least squares on each window of {w} consecutive rows in the same order; '
                     f'each estimate is plotted at the window\'s last row, with its {100 * (1 - float(alpha)):g}% band (t on {w} − {k} DF). '
                     'A point stands for its window: clicking it selects the window\'s rows.' +
                     (f' {out["rolling"]["singular"]} windows have a singular design (a level of a factor missing in them) and no estimates.'
                      if out['rolling']['singular'] else ''))
    out['notes'] = notes
    out['code'] = _rr_code(m, table, table_name, rows, order_by, conf, w, weight)
    out['plot_code'] = _rr_plots(m, out, table, table_name, rows, order_by, conf, w, weight, alpha)
    return out


def _rr_plots(m, out, table, table_name, rows, order_by, conf, window, weight, alpha):
    """The Recursive and Rolling Regression graphs as code: each term's
    recursive estimate with its band, the CUSUM and the CUSUM of squares
    with their bounds, each term's rolling estimate."""
    d = m['d']
    y = m['spec']['y'][0]
    names = list(m['res'].params.index)
    base = _rr_code(m, table, table_name, rows, order_by, conf, window, weight).split('\n')
    base = _with_plt(base[:next(i for i, ln in enumerate(base) if ln.startswith('d0 = ')) + 1], ['from scipy import stats'])
    base = _after_frame(base, _positive_weights(weight, None))
    T = _uncenter(d, names)
    if T is not None:   # the intercept at 0, as the report puts it back (the centred main effects)
        i0 = names.index('Intercept')
        base.append(f'T = np.eye({len(names)})')
        for t_, mm in getattr(d, 'centered_main', {}).items():
            if t_ in names:
                base.append(f'T[{i0}, {names.index(t_)}] = -{mm!r}')
    else:
        base.append(f'T = np.eye({len(names)})')
    xt = f'Observation ({"sorted by " + order_by if order_by else "in row order"})'
    k = len(names)
    order = sorted(range(k), key=lambda j: -1 if names[j] == 'Intercept' else next((i for i, e in enumerate(d.effects) if names[j] in e.get('terms', [])), len(d.effects)))
    terms = [r['term'] for r in out['recursive']]
    band = lambda est, lo, hi, xs, title, ylab, xlab, ref, yfrom=None: ([_fig(340, 230),   # noqa: E731
                                                                        f'ax.fill_between({xs}, {lo}, {hi}, color="{BASE}", alpha=0.18, linewidth=0)',
                                                                        f'ax.plot({xs}, {est}, color="{BASE}", linewidth=1.1, marker="o", markersize={2 if len(d.df) > 300 else 3})',
                                                                        f'ax.axhline({ref}, color="{FIT}", linewidth=0.9, linestyle="--")   # the estimate from all the rows']
                                                                       + ([f'v = np.r_[({est})[{yfrom}:], ({lo})[{yfrom}:], ({hi})[{yfrom}:], {ref}]; pad = 0.08 * (v.max() - v.min())',
                                                                           'ax.set_ylim(v.min() - pad, v.max() + pad)   # the first estimates swing widely: the axis is made for the later ones'] if yfrom is not None else [])
                                                                       + [f'ax.set_xlabel({J(xlab)})', f'ax.set_ylabel({J(ylab)})', f'ax.set_title({J(title)})', 'plt.show()'])
    rec = base + ['B = T @ rls.recursive_coefficients.filtered; C = np.einsum("ij,jkt,lk->ilt", T, rls.recursive_coefficients.filtered_cov, T)',
                  f'z = stats.norm.ppf({1 - alpha / 2!r}); full = T @ fit.params.to_numpy()']
    npts = len(out['cusum']['x'])
    yfrom = min(npts - 1, max(2 * out['k'], round(0.05 * npts)))
    codes = {'recursive': []}
    for j, term in zip(order, terms):
        c = rec + [f'j = {j}   # {one_line(term)}', 'est = B[j, d0:]; se = np.sqrt(np.maximum(C[j, j, d0:], 0))']
        c += band('est', 'est - z * se', 'est + z * se', 't', f'{term} recursive estimate', term, xt, 'full[j]', yfrom)
        codes['recursive'].append('\n'.join(c))
    bounds = (['a = 0.850; up = a * np.sqrt(len(y) - d0) + 2 * a * (t - d0) / np.sqrt(len(y) - d0); lo = -up   # Brown, Durbin and Evans\'s 10% bound'] if conf == 0.1
              else [f'lo, up = rls._cusum_significance_bounds({conf!r}, points=t)'])
    codes['cusum'] = '\n'.join(base + bounds + [_fig(520, 300),
                                                f'ax.plot(t, up, t, lo, color="{FIT}", linewidth=0.9, linestyle="--")   # the {100 * conf:g}% bounds',
                                                f'ax.plot(t, rls.cusum, color="{BASE}", linewidth=1, marker="o", markersize={2 if npts > 300 else 3})',
                                                f'ax.axhline(0, color="{MUTED}", linewidth=0.7)',
                                                f'ax.set_xlabel({J(xt)})', 'ax.set_ylabel("CUSUM")', f'ax.set_title({J(y + " CUSUM")})', 'plt.show()'])
    codes['cusumsq'] = '\n'.join(base + [f'lo, up = rls._cusum_squares_significance_bounds({conf!r}, points=t)', _fig(520, 300),
                                         f'ax.plot(t, (t - d0) / (len(y) - d0), color="{MUTED}", linewidth=0.7, linestyle=":")   # the diagonal',
                                         f'ax.plot(t, up, t, lo, color="{FIT}", linewidth=0.9, linestyle="--")   # the {100 * conf:g}% bounds',
                                         f'ax.plot(t, rls.cusum_squares, color="{BASE}", linewidth=1, marker="o", markersize={2 if npts > 300 else 3})',
                                         f'ax.set_xlabel({J(xt)})', 'ax.set_ylabel("CUSUM of Squares")', f'ax.set_title({J(y + " CUSUM of squares")})', 'plt.show()'])
    ro = out.get('rolling')
    if ro:
        w = ro['window']
        roll = base + [f'roll = RollingOLS(y, X, window={int(w)}).fit(use_t=True)   # least squares on each window of {w} rows',
                       'P = np.asarray(roll.params) @ T.T; Cv = np.einsum("ij,tjk,lk->til", T, np.asarray(roll.cov_params()), T)',
                       f'tc = stats.t.ppf({1 - alpha / 2!r}, np.asarray(roll.df_resid, dtype=float)); full = T @ fit.params.to_numpy()',
                       f'ends = np.arange({int(w)}, len(y) + 1)   # each window at its last observation']
        codes['rolling'] = []
        for j, term in zip(order, [r['term'] for r in ro['terms']]):
            c = roll + [f'j = {j}   # {one_line(term)}', f'est = P[{int(w) - 1}:, j]; se = np.sqrt(np.maximum(Cv[{int(w) - 1}:, j, j], 0)); tj = tc[{int(w) - 1}:]']
            c += band('est', 'est - tj * se', 'est + tj * se', 'ends', f'{term} rolling estimate', term,
                      f'Last observation of the window ({"sorted by " + order_by if order_by else "row order"})', 'full[j]')
            codes['rolling'].append('\n'.join(c))
    return codes


def _rr_code(m, table, table_name, rows, order_by, conf, window, weight):
    d = m['d']
    lines = _code_frame(d, table, table_name, rows, [weight, order_by], ['from statsmodels.regression.recursive_ls import RecursiveLS',
                                                                        'from statsmodels.regression.rolling import RollingOLS'])
    fml = json.dumps(_code_formula(d))
    lines.append(f'fit = smf.wls({fml}, data=d, weights=d[{json.dumps(weight)}]).fit()' if weight else f'fit = smf.ols({fml}, data=d).fit()')
    if order_by:
        meta = data.meta(table, order_by)
        if meta.get('modelingType') in ('nominal', 'ordinal'):
            lv = meta.get('levels') or []
            lines.append(f'o = np.argsort(pd.Categorical(d[{json.dumps(order_by)}], categories={json.dumps(lv)}).codes, kind="stable")   '
                         '# the rows sorted by the column (its level order)')
        else:
            lines.append(f'o = np.argsort(d[{json.dumps(order_by)}].to_numpy(float), kind="stable")   # the rows sorted by the column')
    else:
        lines.append('o = np.arange(len(d))   # the rows in the order of the table')
    lines.append('X, y = fit.model.wexog[o], fit.model.wendog[o]' + ('   # times √w: the weighted fit as least squares' if weight else ''))
    lines.append('rls = RecursiveLS(y, X).fit()')
    lines.append('d0 = max(rls.nobs_diffuse, rls.loglikelihood_burn); t = np.arange(d0 + 1, len(y) + 1)   # the rows after the start')
    lines.append('print(rls.recursive_coefficients.filtered[:, d0:])   # the recursive estimates; the last are least squares\'')
    if conf == 0.1:
        lines.append('a = 0.850; print(rls.cusum, a * np.sqrt(len(y) - d0) + 2 * a * (t - d0) / np.sqrt(len(y) - d0))   # CUSUM, its 10% bound')
    else:
        lines.append(f'print(rls.cusum, rls._cusum_significance_bounds({conf!r}, points=t))   # CUSUM and its bounds')
    lines.append(f'print(rls.cusum_squares, rls._cusum_squares_significance_bounds({conf!r}, points=t))   # CUSUM of squares and its bounds')
    if window:
        lines.append(f'roll = RollingOLS(y, X, window={int(window)}).fit(use_t=True)   # rolling least squares')
        lines.append('print(roll.params, roll.bse)')
    lines += _centred_code(d)
    return '\n'.join(lines)
