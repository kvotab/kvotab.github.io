"""Analyze > Fit Model: JMP's Fit Model platform, computed by statsmodels.

A model is the launch dialog's list of effects (Construct Model Effects).
An effect is a crossing of columns (a column twice is a power), possibly
nested in other columns, possibly marked as a random effect:

    {'names': ['fertilizer', 'water'], 'nest': [], 'random': False}
    {'names': ['batch'], 'nest': ['lot'], 'random': True}        batch[lot]&Random

The personalities and the names the page calls:

  fitmodel.ls           Standard Least Squares: the report tables, row
                        diagnostics, leverage plots, least squares means
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
  fitmodel.mixed        Mixed Model (REML) with variance components
  fitmodel.manova       MANOVA
  fitmodel.genreg       Generalized Regression (lasso, elastic net, ridge)

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

from . import data, models
from .registry import api
from .util import code_head, col, table as rtable

AVG = 'avg'          # a categorical factor averaged over its levels (LS means)
_REML_MAX = 4_000_000   # rows x random levels up to which the REML information is computed


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


def _design(tid, y, effs, rows, weight=None, freq=None, intercept=True, extra=(), y_as_category=False):
    """models.build over the fixed effects; the random effects' columns (and
    any extra columns) are kept in the frame, so every fit of the model
    uses the same rows."""
    fixed = [e for e in effs if not e['random']]
    rand = [n for e in effs if e['random'] for n in e['cols']]
    d = models.build(tid, y, [e['cols'] for e in fixed], rows, weight, freq, intercept=intercept,
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
          choose=None, **_ignored):
    """Everything that defines a fit, as a plain dict (the cache key)."""
    return {'y': _ys(y), 'effects': [[e['names'], e['nest'], e['random']] for e in _effects(effects)], 'weight': weight, 'freq': freq,
            'offset': offset, 'no_intercept': bool(no_intercept), 'dist': dist, 'link': link, 'target': target,
            'overdispersion': bool(overdispersion), 'ordinal': ordinal, 'distr': distr, 'method': method, 'enet_alpha': enet_alpha,
            'criterion': criterion, 'n_grid': n_grid, 'choose': choose}


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


def _code_formula(d, lhs=True):
    """models.code_formula with keyword-safe names, and the '- 1' of a model
    without intercept. lhs=False gives the right-hand side only."""
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
                ps.append(f'C({_q(n)}, {"Sum" if d.coding == "effect" else "Treatment"}, levels={lv!r})')
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
    return res


def _ls_model(tid, rows, spec):
    key = _key('ls', tid, rows, spec)
    m = models.recall(key)
    if m is not None:
        return m
    ys = spec['y']
    if not ys:
        raise ValueError('choose a Y')
    effs = _eff_of(spec)
    d = _design(tid, ys[0], effs, rows, spec['weight'], spec['freq'], not spec['no_intercept'])
    if isinstance(d.df[d.y_alias].dtype, pd.CategoricalDtype):
        raise ValueError(f'{ys[0]} is {data.meta(tid, ys[0]).get("modelingType")}: Standard Least Squares needs a continuous Y '
                         '(Nominal or Ordinal Logistic fits a categorical one)')
    res = _fit_ols(d, _freq_total(tid, spec['freq'], d))
    wind = _col_values(tid, spec['weight'], d.df.index)
    m = {'kind': 'ls', 'd': d, 'res': res, 'coder': Coder(d, res.model.data.design_info), 'tid': tid, 'key': key, 'spec': spec,
         'w_indiv': wind if wind is not None else np.ones(len(d.df))}
    models.remember(key, m)
    return m


def _ls_predict(m, settings, alpha, individual=False):
    res, coder = m['res'], m['coder']
    L = coder.rows(settings)
    b = res.params.to_numpy(float)
    V = res.cov_params().to_numpy(float)
    est = L @ b
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', L, V, L), 0))
    t = _tcrit(alpha, res.df_resid)
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
        F, p, q = test['stat'], test['p'], test['nparm']
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
            'lsmean': est, 'se': se, 'mean': raw, 'n': cnt, 'L': L, 'C': C, 'estimable': ok}


def _effect_of(d, label):
    for e in d.effects:
        if e['label'] == label:
            return e
    raise KeyError(f'no effect {label!r} in the model')


@api('fitmodel.ls')
def ls(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, vif=False, leverage=True,
       dw=False, sequential=False, corr=False, table_name='data'):
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept)
    m = _ls_model(table, rows, spec)
    d, res = m['d'], m['res']
    yname = spec['y'][0]
    notes = []
    singular = res.model.rank < res.model.exog.shape[1]
    if singular:
        notes.append(f'The design is singular: {res.model.exog.shape[1] - res.model.rank} parameter(s) are not estimable. statsmodels '
                     'gives the minimum-norm solution (pinv); JMP would mark the aliased terms Biased or Zeroed. Tests of '
                     'non-estimable hypotheses are not meaningful.')
    et = models.effect_tests(d, res)
    tests = {r['source']: r for r in et['rows']}
    est = models.estimates(d, res, alpha, vif=vif)
    names = list(res.params.index)
    bJ, VJ = res.params.to_numpy(float), res.cov_params().to_numpy(float)
    T = _uncenter(d, names)
    if T is not None:
        bJ, VJ = T @ bJ, T @ VJ @ T.T
    for r in est['rows']:
        r['term'] = _tlabel(d, r['name'])
        if r['name'] == 'Intercept' and T is not None:
            i0 = names.index('Intercept')
            se0 = math.sqrt(max(VJ[i0, i0], 0))
            t0 = bJ[i0] / se0 if se0 > 0 else float('nan')
            tc0 = _tcrit(alpha, res.df_resid)
            r.update({'estimate': bJ[i0], 'se': se0, 't': t0, 'p': float(2 * stats.t.sf(abs(t0), res.df_resid)), 'lower': bJ[i0] - tc0 * se0, 'upper': bJ[i0] + tc0 * se0})
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
    for e in d.effects:
        lsm = _lsmeans(m, e)
        if lsm is not None:
            out['lsmeans'][e['label']] = {k2: lsm[k2] for k2 in ('factors', 'levels', 'labels', 'lsmean', 'se', 'mean', 'n')}
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
            R = VJ / np.outer(sd, sd)
        order = [r['name'] for r in est['rows']]
        idx = [names.index(o) for o in order]
        out['corr'] = {'terms': [_tlabel(d, o) for o in order], 'matrix': R[np.ix_(idx, idx)]}
    out['expression'] = [{'term': r['term'], 'estimate': r['estimate']} for r in est['rows']]
    if any(data.meta(table, nm).get('modelingType') == 'ordinal' for nm in _factor_names(d)):
        notes.append('Ordinal factors are coded like nominal ones (effect coding, the last level the negative sum of the others); JMP codes '
                     'them as differences between adjacent levels. The fit, the tests, the least squares means and the predictions are the '
                     'same; the parameter estimates of ordinal factors are not.')
    if spec['freq']:
        notes.append('Freq counts each row that many times: the error degrees of freedom are the sum of the frequencies minus the '
                     'parameters, as in JMP.')
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
    lines += ['print(fit.summary())   # Summary of Fit, Parameter Estimates', 'print(sm.stats.anova_lm(fit, typ=3))   # Effect Tests (Type III)']
    if wexpr:
        lines.append('infl = sm.OLS(fit.model.wendog, fit.model.wexog).fit().get_influence()   # hats, studentized residuals, Cook\'s D (of the weighted fit)')
    else:
        lines.append('infl = fit.get_influence()   # residuals, studentized residuals, hats, Cook\'s D')
    lines += _centred_code(d)
    out['code'] = '\n'.join(lines)
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
            table_name='data'):
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept)
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


@api('fitmodel.contrast')
def contrast(table, y, effects=(), effect=None, coefs=None, rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05,
             table_name='data'):
    """LSMeans Contrast: each row of coefs weights the least squares means of
    the effect's levels; t tests of each contrast and the joint F test."""
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept)
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
           table_name='data'):
    """JMP's Box-Cox Y Transformation: the error sum of squares of the model
    fitted to (y^lambda - 1) / (lambda * g^(lambda - 1)), g the geometric mean
    (g log y at lambda 0), over a grid of lambda; the best lambda minimises it.
    The interval holds the lambdas the likelihood ratio test does not reject."""
    from scipy import optimize
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept)
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
    return {'lambda': lams, 'sse': sses, 'best': best, 'sse_best': sbest, 'ci': ci, 'gm': gm, 'alpha': alpha,
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
    if kind == 'genreg':
        return _genreg_model(tid, rows, spec)
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
    if kind == 'genreg':
        return _genreg_predict(m, settings, alpha)
    raise KeyError(kind)


def _grid_of(f, n):
    if f['type'] == 'categorical':
        return list(range(len(f['levels'])))
    lo, hi = f['min'], f['max']
    return list(np.linspace(lo, hi, n)) if hi > lo else [lo]


@api('fitmodel.profile')
def profile(table, kind='ls', current=None, rows=None, grid=41, alpha=0.05, **model):
    """The Prediction Profiler: for each factor, the prediction (and its
    confidence interval) as that factor varies and the others stay at their
    current values."""
    spec = _spec(**model)
    m = _model(kind, table, rows, spec)
    d = m['d']
    facs = _factors(d)
    cur = _setting(d, current)
    settings = [dict(cur)]
    spans = []
    for f in facs:
        a = d.alias[f['name']]
        g = _grid_of(f, int(grid))
        spans.append((len(settings), len(g), g))
        for v in g:
            s = dict(cur)
            s[a] = v
            settings.append(s)
    preds = _predict(m, settings, alpha)
    for f in facs:
        a = d.alias[f['name']]
        v = cur.get(a, 0 if f['type'] == 'categorical' else f['mean'])
        f['current'] = f['levels'][v] if f['type'] == 'categorical' else float(v)
    out = {'factors': facs, 'responses': [], 'alpha': alpha}
    for p in preds:
        lo, up = p.get('lower'), p.get('upper')
        resp = {'name': p['name'], 'current': {'pred': float(p['pred'][0]), 'lower': None if lo is None else float(lo[0]),
                                               'upper': None if up is None else float(up[0])}, 'traces': [],
                'bounded': p.get('bounded')}
        for f, (at, k, g) in zip(facs, spans):
            sl = slice(at, at + k)
            resp['traces'].append({'factor': f['name'], 'x': (f['labels'] if f['type'] == 'categorical' else g),
                                   'pred': p['pred'][sl], 'lower': None if lo is None else lo[sl], 'upper': None if up is None else up[sl]})
        out['responses'].append(resp)
    return out


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
def interaction(table, kind='ls', rows=None, alpha=0.05, max_factors=6, **model):
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
    return {'factors': [f['name'] for f in facs], 'types': [f['type'] for f in facs], 'cells': cells,
            'response': _predict(m, [{}], alpha)[0]['name']}


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
    of all of them (JMP's stepwise includes and excludes whole effects)."""

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
    f = st.fit(tuple(state))
    return {'step': step, 'parameter': ' & '.join(st.effs[i]['label'] for i in sorted(group)), 'action': action,
            'p': test['p'] if test else None, 'seq_ss': test['ss'] if test else None, 'rsq': f['rsq'], 'cp': f['cp'],
            'p_params': f['p'], 'aicc': f['aicc'], 'bic': f['bic']}


def _stepwise_run(st, E, locked, rule, heredity, direction, p_enter, p_leave, single, max_steps):
    """Steps from the entered set E. With p-values: forward enters the most
    significant effect while its p-value is below p_enter, backward removes
    the least significant while above p_leave, mixed alternates (one step in,
    then out while any leaves). With AICc or BIC: forward (backward) enters
    (removes) the effect that gives the smallest criterion until none is
    left, then goes back to the model of the path with the smallest one;
    mixed makes the move in or out that lowers the criterion most while one
    does. Returns the new set, the steps and, for a criterion, the best
    model when it is not the last."""
    E = set(E)
    steps = []

    def moves(forward):
        best = None
        for g in _step_moves(st, E, locked, heredity, forward):
            new = (E | g) if forward else (E - g)
            test = st.ftest(tuple(E), tuple(new)) if forward else st.ftest(tuple(new), tuple(E))
            if rule == 'pvalue':
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
    crit = lambda S: st.fit(tuple(S))[rule]  # noqa: E731
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
             index=None, rule='pvalue', direction='forward', p_enter=0.25, p_leave=0.1, heredity='combine', step0=0, max_steps=200,
             table_name='data'):
    """JMP's Stepwise platform for a continuous Y. The state (the entered and
    locked effects, by their index in the list of candidates) lives in the
    page: action 'show' reports it, 'step' makes one step, 'go' steps until
    the rule stops, 'toggle' enters or removes the effect at index,
    'enter_all' and 'remove_all' do what they say. The steps made come back
    as rows of the step history, numbered on from step0."""
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept)
    st = _Step(table, rows, spec)
    k = len(st.effs)
    E = set(int(i) for i in (entered or []) if 0 <= int(i) < k)
    locked = set(int(i) for i in (locked or []) if 0 <= int(i) < k)
    rule = rule if rule in ('pvalue', 'aicc', 'bic') else 'pvalue'
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
            hist.append({'step': stepn, 'parameter': 'Best', 'action': 'Best', 'p': None, 'seq_ss': None, 'rsq': f['rsq'], 'cp': f['cp'],
                         'p_params': f['p'], 'aicc': f['aicc'], 'bic': f['bic']})
    cur = st.fit(tuple(E))
    current = []
    for i, e in enumerate(st.effs):
        est = None
        if i in E:
            test = st.ftest(tuple(E - {i}), tuple(E))
            if len(st.cols[i]) == 1 and st.cols[i][0] in cur['cols']:
                est = float(cur['b'][cur['cols'].index(st.cols[i][0])])
        else:
            test = st.ftest(tuple(E), tuple(E | {i}))
        current.append({'index': i, 'effect': e['label'], 'entered': i in E, 'locked': i in locked, 'estimate': est,
                        'ndf': len(st.cols[i]), 'ss': test['ss'], 'f': test['f'], 'p': test['p']})
    intercept = float(cur['b'][0]) if st.base and len(cur['b']) else None
    if intercept is not None:
        for t, mean in getattr(st.d, 'centered_main', {}).items():
            j = st.names.index(t) if t in st.names else None
            if j is not None and j in cur['cols']:
                intercept -= mean * float(cur['b'][cur['cols'].index(j)])
    stats_out = {k2: cur[k2] for k2 in ('sse', 'dfe', 'rmse', 'rsq', 'rsq_adj', 'cp', 'p', 'aicc', 'bic')}
    d = st.d
    lines = _code_frame(d, table, table_name, rows, [weight, freq])
    lines.append(f'full = smf.ols({json.dumps(_code_formula(d))}, data=d).fit()   # every candidate effect')
    lines.append('# a step: fit the model with and without an effect (the columns of its terms) and compare them: F test, AICc or BIC')
    lines.append('# AICc = -2 log L + 2k + 2k(k + 1)/(n - k - 1), k counting the error variance; Cp = SSE/MSE(full) - (n - 2p)')
    return {'entered': sorted(E), 'locked': sorted(locked), 'history': hist, 'step': stepn, 'stats': stats_out, 'current': current,
            'intercept': intercept, 'effects': [e['label'] for e in st.effs], 'n': st.n, 'code': '\n'.join(lines)}


@api('fitmodel.all_models')
def all_models(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, max_terms=None, per_size=5,
               heredity=False, table_name='data'):
    """All Possible Models: every subset of the effects (at most 12), the
    best per_size of each size by R square."""
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept)
    st = _Step(table, rows, spec)
    k = len(st.effs)
    if k > 12:
        return {'error': f'{k} effects: All Possible Models takes at most 12'}
    top = k if not max_terms else min(k, int(max_terms))
    out = []
    for size in range(1, top + 1):
        fits = []
        for combo in itertools.combinations(range(k), size):
            if heredity and any(_contains(st.effs[j], st.effs[i]) and j not in combo for i in combo for j in range(k)):
                continue
            f = st.fit(combo)
            fits.append((combo, f))
        fits.sort(key=lambda t: -(t[1]['rsq'] or 0))
        for rank, (combo, f) in enumerate(fits[:int(per_size)]):
            out.append({'model': ','.join(st.effs[i]['label'] for i in combo), 'number': size, 'rsq': f['rsq'], 'rmse': f['rmse'],
                        'aicc': f['aicc'], 'bic': f['bic'], 'cp': f['cp'], 'best': rank == 0, 'effects': list(combo)})
    best_aicc = min((r['aicc'] for r in out if r['aicc'] is not None and np.isfinite(r['aicc'])), default=None)
    for r in out:
        r['min_aicc'] = best_aicc is not None and r['aicc'] == best_aicc
    return {'models': out, 'k': k}


# ---------------------------------------------------------------------------
# Generalized Linear Model
# ---------------------------------------------------------------------------

_LINKS = {'identity': 'Identity', 'log': 'Log', 'logit': 'Logit', 'probit': 'Probit', 'cloglog': 'CLogLog', 'reciprocal': 'InversePower',
          'inverse_squared': 'InverseSquared', 'sqrt': 'Sqrt'}
_LINK_LABEL = {'identity': 'Identity', 'log': 'Log', 'logit': 'Logit', 'probit': 'Probit', 'cloglog': 'Comp LogLog', 'reciprocal': 'Reciprocal',
               'inverse_squared': 'Inverse Square', 'sqrt': 'Square Root'}
_DEFAULT_LINK = {'normal': 'identity', 'binomial': 'logit', 'poisson': 'log', 'gamma': 'log', 'invgauss': 'log', 'negbin': 'log'}
_DIST_LABEL = {'normal': 'Normal', 'binomial': 'Binomial', 'poisson': 'Poisson', 'gamma': 'Gamma', 'invgauss': 'Inverse Gaussian',
               'negbin': 'Negative Binomial'}
_SM_FAMILY = {'normal': 'Gaussian', 'binomial': 'Binomial', 'poisson': 'Poisson', 'gamma': 'Gamma', 'invgauss': 'InverseGaussian',
              'negbin': 'NegativeBinomial'}


def _family(dist, link, alpha_nb=1.0):
    import statsmodels.api as sm
    L = getattr(sm.families.links, _LINKS[link])()
    if dist == 'negbin':
        return sm.families.NegativeBinomial(link=L, alpha=alpha_nb)
    return getattr(sm.families, _SM_FAMILY[dist])(link=L)


def _glm_endog(d, tid, ys, dist, target):
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
            raise ValueError(f'{ys[0]} is categorical: the Generalized Linear Model takes a two-level Y with the binomial distribution '
                             '(Nominal or Ordinal Logistic fits others)')
        t = _level_index(lv, target) if target is not None else 0
        info['levels'] = [lv[t], lv[1 - t]]
        e = (yv == lv[t]).to_numpy(float)
        return e, e, info
    v = yv.to_numpy(float)
    if dist == 'binomial' and (np.any(v < 0) or np.any(v > 1)):
        raise ValueError('a continuous binomial Y must be a proportion between 0 and 1 (or give events and trials as two Ys)')
    if dist in ('poisson', 'negbin') and np.any(v < 0):
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
    d = _design(tid, ys if len(ys) > 1 else ys[0], effs, rows, spec['weight'], spec['freq'], not spec['no_intercept'],
                extra=[spec['offset']] if spec['offset'] else ())
    endog, yresp, info = _glm_endog(d, tid, ys, dist, spec['target'])
    X = _matrix(d)
    off = _col_values(tid, spec['offset'], d.df.index)
    vw = _col_values(tid, spec['weight'], d.df.index)
    fw = _col_values(tid, spec['freq'], d.df.index)
    scale = 'X2' if spec['overdispersion'] and dist in ('binomial', 'poisson') else None
    nb = None
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
         'offset': off, 'vw': vw, 'fw': fw, 'scale_opt': scale, 'coder': Coder(d, X.design_info), 'key': key, 'spec': spec, 'tid': tid}
    models.remember(key, m)
    return m


def _glm_params(m):
    if m['nb'] is not None:
        p = m['nb'].params
        return p.to_numpy(float)[:-1], m['nb'].cov_params().to_numpy(float)[:-1, :-1], list(p.index[:-1])
    return m['res'].params.to_numpy(float), m['res'].cov_params().to_numpy(float), list(m['res'].params.index)


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
        overdispersion=False, target=None, alpha=0.05, lr_params=True, table_name='data'):
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, offset=offset, no_intercept=no_intercept, dist=dist, link=link,
                 target=target, overdispersion=overdispersion)
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
        sa = m['nb'].bse.iloc[-1]
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
    lines += _centred_code(d)
    return {'model': {'response': ', '.join(spec['y']), 'distribution': _DIST_LABEL[dist], 'link': _LINK_LABEL.get(link, link), 'n': n,
                      'target': _lvl(m['info']['levels'][0]) if m['info'].get('levels') else None, 'converged': bool(getattr(res, 'converged', True))},
            'whole': whole, 'aicc': aicc, 'bic': bic, 'gof': gof, 'overdispersion': overd, 'scaled': m['scale_opt'] == 'X2', 'phi': phi,
            'effect_tests': et, 'estimates': est, 'diag': diag, 'factors': _factors(d), 'key': m['key'], 'notes': notes, 'alpha': alpha,
            'code': '\n'.join(lines)}


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
    d = _design(tid, ys[0], effs, rows, spec['weight'], spec['freq'], not spec['no_intercept'])
    yv = d.df[d.y_alias]
    if not isinstance(yv.dtype, pd.CategoricalDtype):
        raise ValueError(f'{ys[0]} is continuous: the logistic fits need a nominal or ordinal Y (change its modeling type, or use Standard Least Squares)')
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
         'coder': Coder(d, X.design_info), 'key': key, 'spec': spec, 'tid': tid, 'distr': spec['distr'] or 'logit'}
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
             alpha=0.05, table_name='data'):
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept, ordinal=ordinal, distr=distr, target=target)
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
        for i in order:
            v, lab = vals[i], labs[i]
            se = math.sqrt(max(C[i, i], 0))
            chi = (v / se) ** 2 if se > 0 else None
            est.append({'logit': '', 'term': lab, 'estimate': float(v), 'se': se, 'chisq': chi, 'p': float(stats.chi2.sf(chi, 1)) if chi is not None else None,
                        'lower': float(v - z * se), 'upper': float(v + z * se)})
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
        for q, lg in enumerate(logits):
            for j in order:
                v, se = B[j, q], S[j, q]
                chi = (v / se) ** 2 if se > 0 else None
                est.append({'logit': lg, 'term': _tlabel(d, names[j]), 'estimate': float(v), 'se': float(se), 'chisq': chi,
                            'p': float(stats.chi2.sf(chi, 1)) if chi is not None else None, 'lower': float(v - z * se), 'upper': float(v + z * se)})
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
    out = {'mode': mode, 'levels': ylab, 'level_values': levels, 'target': ylab[m['target']] if mode == 'binary' else None, 'whole': whole,
           'rsquare_u': fit['entropy_rsq'], 'aicc': aicc, 'bic': bic, 'n': N, 'fit': fit, 'estimates': est, 'footer': footer, 'effect_tests': et,
           'odds': odds, 'confusion': {'levels': ylab, 'matrix': conf}, 'roc': rocs, 'factors': _factors(d), 'key': m['key'], 'alpha': alpha,
           'probs': {'rows': [int(i) for i in d.df.index], 'prob': P, 'most_likely': [ylab[i] for i in most], 'actual': [ylab[i] for i in m['codes']],
                     'lin': eta, 'lin_names': ([f'Lin[{ylab[m["target"]]}]'] if mode == 'binary' else [f'Lin[{ylab[j]}]' for j in range(k - 1)]) if mode != 'ordinal' else ['Linear']},
           'distr': m['distr']}
    out['plot'] = _logistic_plot(m)
    notes.append('Confidence limits are Wald limits; JMP gives profile-likelihood limits for the parameters and odds ratios.')
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
    return out


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
    return {'x': g, 'cum': cumg.T, 'factor': n0, 'points': {'x': x, 'y': lo + u * (hi - lo), 'rows': [int(i) for i in d.df.index]},
            'levels': [_lvl(v) for v in m['levels']]}


# ---------------------------------------------------------------------------
# Mixed Model (REML)
# ---------------------------------------------------------------------------

def _zmatrix(d, cols):
    """The random effect's design: an indicator of each combination of its
    categorical columns, times its continuous columns."""
    cats = [d.alias[c] for c in dict.fromkeys(cols) if d.alias[c] in d.categorical]
    nums = [d.alias[c] for c in cols if d.alias[c] not in d.categorical]
    n = len(d.df)
    if cats:
        codes = [tuple(r) for r in np.column_stack([d.df[a].cat.codes.to_numpy() for a in cats]).tolist()]
        uniq = sorted(set(codes))
        pos = {u: i for i, u in enumerate(uniq)}
        Z = np.zeros((n, len(uniq)))
        Z[np.arange(n), [pos[v] for v in codes]] = 1.0
        labels = [','.join(_lvl(d.levels[a][c]) for a, c in zip(cats, u)) for u in uniq]
    else:
        Z = np.ones((n, 1))
        labels = ['']
    for a in nums:
        Z = Z * d.df[a].to_numpy(float)[:, None]
    return Z, labels


def _mixed_model(tid, rows, spec):
    key = _key('mixed', tid, rows, spec)
    m = models.recall(key)
    if m is not None:
        return m
    import statsmodels.formula.api as smf
    ys = spec['y']
    if not ys:
        raise ValueError('choose a Y')
    effs = _eff_of(spec)
    rand = [e for e in effs if e['random']]
    if not rand:
        raise ValueError('no random effects: mark effects with Attributes > Random Effect in the launch dialog')
    if spec['weight'] or spec['freq']:
        raise ValueError('statsmodels\' MixedLM takes no weights: remove Weight and Freq for the mixed model')
    d = _design(tid, ys[0], effs, rows, None, None, not spec['no_intercept'])
    if isinstance(d.df[d.y_alias].dtype, pd.CategoricalDtype):
        raise ValueError(f'{ys[0]} is categorical: the mixed model needs a continuous Y')
    for e in rand:
        if not any(d.alias[c] in d.categorical for c in e['cols']):
            raise ValueError(f'the random effect {e["label"]} has no categorical column (a random effect is a factor, or a slope within one)')
    cat_sets = [[d.alias[c] for c in e['cols'] if d.alias[c] in d.categorical] for e in rand]
    common = [a for a in cat_sets[0] if all(a in s for s in cat_sets)]
    G = None
    for a in common:
        if any(len(e['cols']) == 1 and d.alias[e['cols'][0]] == a for e in rand):
            G = a
            break
    if G is None and common:
        G = common[0]
    vc, labels, re_formula, vc_code = {}, {}, '0', {}
    df = d.df.copy()
    real = {a: n for n, a in d.alias.items()}
    for i, e in enumerate(rand):
        al = [d.alias[c] for c in e['cols']]
        rest = [a for a in dict.fromkeys(al) if a != G] if G else list(dict.fromkeys(al))
        if G and not rest:
            re_formula = '1'
            labels['__re__'] = e['label']
            continue
        vc[f'vc{i}'] = '0 + ' + ':'.join(f'C({a})' if a in d.categorical else a for a in rest)
        vc_code[e['label']] = '0 + ' + ':'.join(f'C({_q(real[a])})' if a in d.categorical else _q(real[a]) for a in rest)
        labels[f'vc{i}'] = e['label']
    if G is None:
        df['_one'] = 1.0
        groups = '_one'
    else:
        groups = G
    md = smf.mixedlm(d.formula, df, groups=groups, re_formula=re_formula, vc_formula=vc or None)
    res = md.fit(reml=True)
    if not res.converged:
        res2 = md.fit(reml=True, method=['lbfgs', 'powell'])
        if res2.llf >= res.llf:
            res = res2
    X = np.asarray(md.exog, dtype=float)
    fe_names = list(md.exog_names)
    comps = []
    if re_formula == '1':
        comps.append({'label': labels['__re__'], 'var': float(res.cov_re.iloc[0, 0]), 'spec': next(e for e in rand if e['label'] == labels['__re__'])})
    vnames = list(md.exog_vc.names) if vc else []
    for nm, v in zip(vnames, np.atleast_1d(res.vcomp)):
        comps.append({'label': labels[nm], 'var': float(v), 'spec': next(e for e in rand if e['label'] == labels[nm])})
    for c in comps:
        c['Z'], c['levels'] = _zmatrix(d, c['spec']['cols'])
    y = d.df[d.y_alias].to_numpy(float)
    ms = {'kind': 'mixed', 'd': d, 'res': res, 'md': md, 'X': X, 'fe_names': fe_names, 'comps': comps, 'y': y, 'scale': float(res.scale),
          'key': key, 'spec': spec, 'tid': tid, 'group': real.get(G) if G else None, 're_formula': re_formula, 'vc_code': vc_code}
    # the fixed-effects design as patsy made it, for the profilers
    import patsy
    di = patsy.dmatrix(d.rhs, d.df, return_type='dataframe').design_info
    _attach(d, di)
    ms['coder'] = Coder(d, di)
    ms['dense'] = _reml(ms) if len(y) * sum(c['Z'].shape[1] for c in comps) <= _REML_MAX else None
    models.remember(key, ms)
    return ms


def _reml(m):
    """The REML quantities at statsmodels' estimates: the covariance of the
    fixed effects (X'V^-1 X)^-1, the variance components' covariance from
    the expected information I_ij = tr(P V_i P V_j) / 2, the derivatives of
    the fixed effects' covariance for Satterthwaite's degrees of freedom, the
    BLUPs and the REML log-likelihood. V = s2 I + sum_k var_k Z_k Z_k' is
    never formed: with Zs = [Z_k sqrt(var_k)] and K = s2 I + Zs'Zs (q x q),
    V^-1 B = (B - Zs K^-1 Zs'B) / s2 (Woodbury), so the cost grows with the
    rows times the random levels, not with the rows squared."""
    X, y, comps, s2 = m['X'], m['y'], m['comps'], m['scale']
    n, p = X.shape
    Zk = [c['Z'] for c in comps]
    Z = np.hstack(Zk) if Zk else np.zeros((n, 0))
    Zs = np.hstack([c['Z'] * math.sqrt(max(c['var'], 0.0)) for c in comps]) if comps else np.zeros((n, 0))
    q = Z.shape[1]
    S = Zs.T @ Zs
    K = s2 * np.eye(q) + S
    Kinv = np.linalg.inv(K) if q else np.zeros((0, 0))

    def vinv(B):
        return (B - Zs @ (Kinv @ (Zs.T @ B))) / s2
    W = vinv(X)                       # V^-1 X
    XtViX = X.T @ W
    C = np.linalg.pinv(XtViX)
    b = C @ (W.T @ y)
    r = y - X @ b
    Vir = vinv(r)
    WC = W @ C
    PZ = vinv(Z) - WC @ (W.T @ Z)     # P Z
    ZPZ = Z.T @ PZ
    edges = np.cumsum([0] + [z.shape[1] for z in Zk])
    blocks = [slice(edges[i], edges[i + 1]) for i in range(len(Zk))]
    kq = len(Zk) + 1
    info = np.zeros((kq, kq))
    for i, bi in enumerate(blocks):
        for j, bj in enumerate(blocks[i:], start=i):
            info[i, j] = info[j, i] = 0.5 * float(np.sum(ZPZ[bi, bj] ** 2))
        info[i, -1] = info[-1, i] = 0.5 * float(np.sum(PZ[:, bi] ** 2))
    KS = Kinv @ S
    tr_v2 = (n - 2 * np.trace(KS) + np.sum(KS * KS.T)) / (s2 * s2)
    CWW = C @ (W.T @ W)
    info[-1, -1] = 0.5 * float(tr_v2 - 2 * np.trace(C @ (W.T @ vinv(W))) + np.sum(CWW * CWW.T))
    A = np.linalg.pinv(info)
    dC = [(z.T @ WC).T @ (z.T @ WC) for z in Zk] + [WC.T @ WC]
    ldk = np.linalg.slogdet(K)[1] if q else 0.0
    logdet_v = n * math.log(s2) + ldk - q * math.log(s2)
    rank = int(np.linalg.matrix_rank(X))
    llr = -0.5 * ((n - rank) * math.log(2 * math.pi) + logdet_v + np.linalg.slogdet(XtViX)[1] + float(r @ Vir))
    blups = [c['var'] * (c['Z'].T @ Vir) for c in comps]
    return {'C': C, 'b': b, 'A': A, 'dC': dC, 'llr': llr, 'blups': blups, 'info': info}


def _satterthwaite(dense, L):
    """Denominator degrees of freedom for L b (one row: Satterthwaite; several:
    Fai and Cornelius's approximation, as lmerTest computes them)."""
    L = np.atleast_2d(L)
    C, A, dC = dense['C'], dense['A'], dense['dC']
    M = L @ C @ L.T
    vals, vecs = np.linalg.eigh(M)
    keep = vals > 1e-10 * max(vals.max(), 1e-300)
    nus = []
    for dval, vec in zip(vals[keep], vecs[:, keep].T):
        lm = vec @ L
        g = np.array([lm @ D @ lm for D in dC])
        den = float(g @ A @ g)
        nus.append(2 * dval * dval / den if den > 0 else float('inf'))
    q = len(nus)
    if q == 0:
        return float('nan')
    if q == 1:
        return float(nus[0])
    nus = np.asarray(nus)
    if np.all(np.abs(np.diff(nus)) < 1e-8):
        return float(nus.mean())
    if np.any(nus <= 2):
        return 2.0
    E = float(np.sum(nus / (nus - 2)))
    return 2 * E / (E - q) if E > q else float('nan')


def _mixed_predict(m, settings, alpha):
    L = m['coder'].rows(settings)
    names = list(m['coder'].names)
    fe = m['res'].fe_params
    b = np.array([fe[nm] for nm in names])
    C = m['dense']['C'] if m['dense'] else np.asarray(m['res'].cov_params(), dtype=float)[:len(names), :len(names)]
    idx = [m['fe_names'].index(nm) for nm in names]
    C = C[np.ix_(idx, idx)]
    est = L @ b
    se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', L, C, L), 0))
    z = float(stats.norm.ppf(1 - alpha / 2))
    return [{'name': m['spec']['y'][0], 'pred': est, 'lower': est - z * se, 'upper': est + z * se}]


@api('fitmodel.mixed')
def mixed(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, alpha=0.05, table_name='data'):
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, no_intercept=no_intercept)
    m = _mixed_model(table, rows, spec)
    d, res, X, dense = m['d'], m['res'], m['X'], m['dense']
    n, p = X.shape
    notes = []
    z = float(stats.norm.ppf(1 - alpha / 2))
    s2 = m['scale']
    comps = m['comps']
    total = s2 + sum(c['var'] for c in comps if c['spec']['cols'] and all(d.alias[x] in d.categorical for x in c['spec']['cols']))
    vc_rows = []
    if dense:
        se_all = np.sqrt(np.maximum(np.diag(dense['A']), 0))
    else:
        se_all = np.asarray(res.bse_re, dtype=float)
        se_all = np.r_[se_all, np.nan]
        notes.append('A model this large (rows times random levels): the variance components\' standard errors are statsmodels\' (bse_re), '
                     'and the fixed effects are tested with the normal distribution.')
    for i, c in enumerate(comps + [{'label': 'Residual', 'var': s2}]):
        v = c['var']
        se = float(se_all[i]) if i < len(se_all) else float('nan')
        slope = c['label'] != 'Residual' and not all(d.alias[x] in d.categorical for x in c['spec']['cols'])
        vc_rows.append({'effect': c['label'], 'ratio': v / s2 if s2 > 0 and c['label'] != 'Residual' else None, 'var': v, 'se': se,
                        'lower': v - z * se if np.isfinite(se) else None, 'upper': v + z * se if np.isfinite(se) else None,
                        'p': float(2 * stats.norm.sf(v / se)) if np.isfinite(se) and se > 0 and c['label'] != 'Residual' else None,
                        'pct': 100 * v / total if total > 0 and not slope else None})
    vc_rows.append({'effect': 'Total', 'ratio': None, 'var': total, 'se': None, 'lower': None, 'upper': None, 'p': None, 'pct': 100.0})
    # fixed effects
    fe_names = m['fe_names']
    b = np.asarray(res.fe_params, dtype=float)
    C = dense['C'] if dense else np.asarray(res.cov_params(), dtype=float)[:p, :p]
    T = _uncenter(d, fe_names)
    bJ, CJ = (T @ b, T @ C @ T.T) if T is not None else (b, C)
    se_b = np.sqrt(np.maximum(np.diag(CJ), 0))
    est = []
    for j, nm in enumerate(fe_names):
        L = T[j].copy() if T is not None else np.zeros(p)
        if T is None:
            L[j] = 1
        df_ = _satterthwaite(dense, L) if dense else float('inf')
        t = bJ[j] / se_b[j] if se_b[j] > 0 else float('nan')
        tc = float(stats.t.ppf(1 - alpha / 2, df_)) if np.isfinite(df_) else z
        pv = float(2 * stats.t.sf(abs(t), df_)) if np.isfinite(df_) else float(2 * stats.norm.sf(abs(t)))
        est.append({'term': _tlabel(d, nm), 'estimate': float(bJ[j]), 'se': float(se_b[j]), 'dfden': df_, 't': float(t), 'p': pv,
                    'lower': float(bJ[j] - tc * se_b[j]), 'upper': float(bJ[j] + tc * se_b[j]), 'name': nm})
    rank = {'Intercept': -1}
    for i, e in enumerate(d.effects):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    est.sort(key=lambda r: rank.get(r['name'], len(d.effects)))
    tests = []
    for e in d.effects:
        cols = [fe_names.index(t) for t in e.get('terms', []) if t in fe_names]
        if not cols:
            continue
        L = np.zeros((len(cols), p))
        for i, c in enumerate(cols):
            L[i, c] = 1
        Lb = L @ b
        M = L @ C @ L.T
        q = int(np.linalg.matrix_rank(M))
        F = float(Lb @ np.linalg.pinv(M) @ Lb / q) if q else float('nan')
        dfd = _satterthwaite(dense, L) if dense else float('inf')
        pv = float(stats.f.sf(F, q, dfd)) if np.isfinite(dfd) else float(stats.chi2.sf(F * q, q))
        tests.append({'source': e['label'], 'nparm': len(cols), 'dfnum': q, 'dfden': dfd, 'f': F, 'p': pv})
    # fit statistics
    llr = dense['llr'] if dense else float(res.llf)
    kcov = len(comps) + 1
    nstar = n - int(np.linalg.matrix_rank(X))
    aicc = -2 * llr + 2 * kcov * nstar / (nstar - kcov - 1) if nstar - kcov - 1 > 0 else float('nan')
    bic = -2 * llr + kcov * math.log(nstar) if nstar > 0 else float('nan')
    cond = np.asarray(res.fittedvalues, dtype=float)
    marg = X @ b
    y = m['y']
    blups = []
    if dense:
        for c, bl in zip(comps, dense['blups']):
            blups.append({'effect': c['label'], 'rows': [{'level': lv, 'blup': float(v)} for lv, v in zip(c['levels'], bl)]})
    notes.append('Denominator degrees of freedom are Satterthwaite\'s (Fai and Cornelius\'s for several), computed from statsmodels\' REML fit; '
                 'JMP uses Kenward and Roger\'s, which agree for balanced designs. Variance component standard errors come from the REML '
                 'expected information; their intervals are Wald intervals.')
    notes.append('AICc and BIC count the covariance parameters and use n − rank(X) observations, as for REML in SAS.')
    lines = _code_frame(d, table, table_name, rows, [])
    if m['group']:
        grp = f'd[{json.dumps(m["group"])}]'
    else:
        lines.append('d["_one"] = 1   # crossed random effects: one group, a variance component each')
        grp = 'd["_one"]'
    vcs = ', '.join(f'{json.dumps(k2)}: {json.dumps(v)}' for k2, v in m['vc_code'].items())
    lines.append(f'md = smf.mixedlm({json.dumps(_code_formula(d))}, data=d, groups={grp}, re_formula={json.dumps(m["re_formula"])}'
                 + (f', vc_formula={{{vcs}}})' if vcs else ')'))
    lines.append('fit = md.fit(reml=True)')
    lines.append('print(fit.summary())   # fixed effects (z tests), the variances of the random effects, the residual variance (Scale)')
    lines += _centred_code(d)
    return {'fit': {'m2rll': -2 * llr, 'aicc': aicc, 'bic': bic, 'n': n, 'converged': bool(res.converged), 'method': 'REML',
                    'statsmodels_llf': float(res.llf)},
            'varcomp': vc_rows, 'estimates': est, 'tests': tests, 'blups': blups, 'factors': _factors(d), 'key': m['key'], 'notes': notes,
            'alpha': alpha,
            'diag': {'rows': [int(i) for i in d.df.index], 'actual': y, 'predicted': cond, 'marginal': marg, 'residual': y - cond,
                     'marg_resid': y - marg},
            'code': '\n'.join(lines)}


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


@api('fitmodel.manova')
def manova(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, response='identity', alpha=0.05, table_name='data'):
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
    r = mv.mv_test(hypotheses=[(nm, L, M) if M is not None else (nm, L) for nm, L in hyps])
    tests = []
    Hs = {}
    E = None
    for nm, _L in hyps:
        st = r.results[nm]['stat']
        rows_ = []
        for idx, row in st.iterrows():
            rows_.append({'test': _MV_NAMES.get(idx, idx), 'value': float(row['Value']), 'f': float(row['F Value']), 'numdf': float(row['Num DF']),
                          'dendf': float(row['Den DF']), 'p': float(row['Pr > F'])})
        tests.append({'effect': nm, 'rows': rows_})
        Hs[nm] = np.asarray(r.results[nm]['H'], dtype=float)
        E = np.asarray(r.results[nm]['E'], dtype=float)
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
            'notes': ['The F approximations are statsmodels\' (Rao\'s for Wilks\' lambda, Pillai\'s and McKeon\'s forms for the traces; '
                      'Roy\'s F is an upper bound). JMP\'s approximations can differ in the degrees of freedom of Hotelling-Lawley.'],
            'code': '\n'.join(lines)}


# ---------------------------------------------------------------------------
# Generalized Regression
# ---------------------------------------------------------------------------

def _genreg_model(tid, rows, spec):
    key = _key('genreg', tid, rows, spec)
    m = models.recall(key)
    if m is not None:
        return m
    import statsmodels.api as sm
    ys = spec['y']
    if not ys:
        raise ValueError('choose a Y')
    dist = spec['dist'] if spec['dist'] in ('normal', 'binomial', 'poisson') else 'normal'
    effs = _eff_of(spec)
    d = _design(tid, ys[0], effs, rows, spec['weight'], spec['freq'], True)
    info = {}
    yv = d.df[d.y_alias]
    if isinstance(yv.dtype, pd.CategoricalDtype):
        lv = [c for c in yv.cat.categories if (yv == c).any()]
        if len(lv) != 2:
            raise ValueError(f'{ys[0]} is categorical: Generalized Regression here takes a continuous Y or a two-level one (binomial)')
        dist = 'binomial'
        t = _level_index(lv, spec['target']) if spec['target'] is not None else 0
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
    ic = names.index('Intercept')
    cols = [j for j in range(len(names)) if j != ic]
    mu_ = np.average(Xa[:, cols], axis=0, weights=w) if cols else np.zeros(0)
    sd_ = np.sqrt(np.average((Xa[:, cols] - mu_) ** 2, axis=0, weights=w)) if cols else np.zeros(0)
    live = sd_ > 1e-12
    sd_[~live] = 1.0
    Z = np.column_stack([np.ones(len(y)), (Xa[:, cols] - mu_) / sd_])
    method = spec['method'] if spec['method'] in ('lasso', 'enet', 'ridge') else 'lasso'
    l1 = 1.0 if method == 'lasso' else (0.0 if method == 'ridge' else float(spec['enet_alpha'] or 0.9))
    N = float(np.sum(w))
    if dist == 'normal':
        mod = sm.WLS(y, Z, weights=w)
        base = y - np.average(y, weights=w)
        fam = None
    else:
        fam = sm.families.Binomial() if dist == 'binomial' else sm.families.Poisson()
        mod = sm.GLM(y, Z, family=fam, var_weights=w)
        base = y - np.average(y, weights=w)
    grad = np.abs(Z[:, 1:].T @ (w * base)) / N if len(cols) else np.zeros(1)
    amax = float(np.max(grad)) / max(l1, 1e-3) if len(cols) and np.max(grad) > 0 else 1.0
    ng = int(spec['n_grid'] or 40)
    alphas = amax * np.logspace(0, -4, ng) if l1 > 0 else amax * np.logspace(1, -5, ng)
    path = []
    sp = None
    for a in alphas:
        pen = np.r_[0.0, np.full(Z.shape[1] - 1, a)]
        r = mod.fit_regularized(method='elastic_net', alpha=pen, L1_wt=l1, start_params=sp, maxiter=200)
        c = np.asarray(r.params, dtype=float)
        c[1:][~live] = 0.0
        sp = c
        eta = Z @ c
        if dist == 'normal':
            rss = float(np.sum(w * (y - eta) ** 2))
            ll = -0.5 * N * (math.log(2 * math.pi * rss / N) + 1) if rss > 0 else float('inf')
            W = w
        else:
            mu = fam.link.inverse(eta)
            ll = float(fam.loglike(y, mu, var_weights=w))
            W = w * fam.variance(mu) if dist == 'binomial' else w * mu
        act = np.flatnonzero(np.abs(c[1:]) > 1e-10)
        if l1 >= 1:
            df_ = len(act) + 1
        else:
            Za = Z[:, 1:][:, act]
            if len(act):
                Mx = Za.T @ (Za * W[:, None])
                df_ = float(np.trace(np.linalg.solve(Mx + N * a * (1 - l1) * np.eye(len(act)), Mx))) + 1
            else:
                df_ = 1.0
        kk = df_ + (1 if dist == 'normal' else 0)
        aicc = -2 * ll + 2 * kk + (2 * kk * (kk + 1) / (N - kk - 1) if N - kk - 1 > 0 else float('nan'))
        bic = -2 * ll + kk * math.log(N)
        path.append({'alpha': float(a), 'coef': c, 'l1': float(np.sum(np.abs(c[1:]))), 'll': ll, 'df': df_, 'aicc': aicc, 'bic': bic,
                     'nonzero': int(len(act))})
    crit = spec['criterion'] if spec['criterion'] in ('aicc', 'bic') else 'aicc'
    vals = np.array([p_[crit] if np.isfinite(p_[crit]) else np.inf for p_ in path])
    best = int(np.argmin(vals))
    chosen = best if spec['choose'] is None else min(max(int(spec['choose']), 0), len(path) - 1)
    c = path[chosen]['coef']
    borig = np.zeros(len(names))
    borig[cols] = c[1:] / sd_
    borig[ic] = c[0] - float(np.sum(c[1:] * mu_ / sd_))
    bjmp = borig.copy()   # borig is on the design as fitted (a centred main effect: the intercept at its mean)
    for t, mean in getattr(d, 'centered_main', {}).items():
        if t in names:
            bjmp[ic] -= mean * borig[names.index(t)]
    m = {'kind': 'genreg', 'd': d, 'X': X, 'names': names, 'path': path, 'best': best, 'chosen': chosen, 'b': borig, 'b_jmp': bjmp, 'scaled': c, 'mu': mu_,
         'sd': sd_, 'cols': cols, 'dist': dist, 'fam': fam, 'method': method, 'l1': l1, 'crit': crit, 'info': info, 'N': N, 'y': y, 'w': w,
         'coder': Coder(d, X.design_info), 'key': key, 'spec': spec, 'tid': tid}
    models.remember(key, m)
    return m


def _genreg_predict(m, settings, alpha):
    L = m['coder'].rows(settings)
    eta = L @ m['b']
    pred = eta if m['dist'] == 'normal' else m['fam'].link.inverse(eta)
    name = m['spec']['y'][0] if not m['info'].get('levels') else f'Prob[{_lvl(m["info"]["levels"][0])}]'
    return [{'name': name, 'pred': pred, 'lower': None, 'upper': None, 'bounded': m['dist'] == 'binomial'}]


@api('fitmodel.genreg')
def genreg(table, y, effects=(), rows=None, weight=None, freq=None, no_intercept=False, dist='normal', method='lasso', enet_alpha=0.9,
           criterion='aicc', n_grid=40, choose=None, target=None, table_name='data'):
    spec = _spec(y=y, effects=effects, weight=weight, freq=freq, dist=dist, method=method, enet_alpha=enet_alpha, criterion=criterion,
                 n_grid=n_grid, choose=choose, target=target)
    m = _genreg_model(table, rows, spec)
    d, names, path = m['d'], m['names'], m['path']
    ch = m['chosen']
    pc = path[ch]
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
    pred = eta if m['dist'] == 'normal' else m['fam'].link.inverse(eta)
    ll = pc['ll']
    if m['dist'] == 'normal':
        yb = np.average(m['y'], weights=m['w'])
        ll0 = -0.5 * m['N'] * (math.log(2 * math.pi * float(np.sum(m['w'] * (m['y'] - yb) ** 2)) / m['N']) + 1)
    else:
        mu0 = np.full(len(m['y']), np.average(m['y'], weights=m['w']))
        ll0 = float(m['fam'].loglike(m['y'], mu0, var_weights=m['w']))
    grsq = (1 - math.exp(2 * (ll0 - ll) / m['N'])) / (1 - math.exp(2 * ll0 / m['N'])) if m['dist'] != 'normal' else 1 - math.exp(2 * (ll0 - ll) / m['N'])
    meth = {'lasso': 'Lasso', 'enet': 'Elastic Net', 'ridge': 'Ridge'}[m['method']]
    lines = _code_frame(d, table, table_name, rows, [weight, freq], ['import patsy'])
    lines.append(f'X = np.asarray(patsy.dmatrix({json.dumps(_code_formula(d, lhs=False))}, d))   # the design, effect coded')
    lines.append('Z = (X[:, 1:] - X[:, 1:].mean(0)) / X[:, 1:].std(0); Z = np.column_stack([np.ones(len(Z)), Z])   # centred and scaled')
    fam = 'sm.WLS(y, Z)' if m['dist'] == 'normal' else f'sm.GLM(y, Z, family=sm.families.{"Binomial" if m["dist"] == "binomial" else "Poisson"}())'
    if m['info'].get('levels'):
        lv0 = m['info']['levels'][0]
        lines.append(f'y = (d[{json.dumps(spec["y"][0])}] == {json.dumps(lv0 if isinstance(lv0, str) else float(lv0))}).to_numpy(float)   # the target level')
    else:
        lines.append(f'y = d[{json.dumps(spec["y"][0])}].to_numpy(float)')
    lines.append(f'fit = {fam}.fit_regularized(method="elastic_net", alpha=np.r_[0, np.full(Z.shape[1] - 1, {pc["alpha"]!r})], L1_wt={m["l1"]!r})')
    lines += _centred_code(d)
    return {'model': {'response': spec['y'][0], 'distribution': _DIST_LABEL[m['dist']], 'method': meth, 'criterion': m['crit'].upper() if m['crit'] == 'bic' else 'AICc',
                      'n': m['N'], 'rows': int(len(d.df)), 'nll': -ll, 'nparm': pc['df'], 'aicc': pc['aicc'], 'bic': pc['bic'], 'grsq': grsq,
                      'lambda': pc['alpha'], 'enet_alpha': m['l1'], 'target': _lvl(m['info']['levels'][0]) if m['info'].get('levels') else None},
            'path': {'l1': [p_['l1'] for p_ in path], 'alpha': [p_['alpha'] for p_ in path], 'aicc': [p_['aicc'] for p_ in path],
                     'bic': [p_['bic'] for p_ in path], 'df': [p_['df'] for p_ in path], 'nonzero': [p_['nonzero'] for p_ in path],
                     'coefs': [{'term': labels[j], 'values': [float(p_['coef'][1 + i]) for p_ in path]} for i, j in enumerate(m['cols'])]},
            'best': m['best'], 'chosen': ch, 'estimates': est, 'scaled': scaled, 'factors': _factors(d), 'key': m['key'],
            'diag': {'rows': [int(i) for i in d.df.index], 'actual': m['y'], 'predicted': pred, 'residual': m['y'] - pred},
            'notes': ['The predictors are centred and scaled before the penalty (the intercept is not penalised); the estimates are shown on '
                      'both scales. The degrees of freedom are the number of non-zero terms for the lasso and the trace of the ridge hat matrix '
                      'on the active terms otherwise. statsmodels\' fit_regularized gives no standard errors for penalised estimates.'],
            'code': '\n'.join(lines)}
