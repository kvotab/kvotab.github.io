"""Linear models as JMP reports them, shared by Fit Y by X and Fit Model.

A model is given as JMP's effects: a list of effects, each a list of column
names; a name twice in one effect is a power, two names a crossing:

    [['age'], ['sex'], ['age', 'sex'], ['height', 'height']]

build() turns that into a patsy formula over short aliases (v0, v1, ...) so
that any column name works, codes nominal and ordinal columns as JMP does
(effect coding, the last level the negative sum of the others) and centres
continuous columns inside crossings and powers (JMP's Center Polynomials).
It keeps JMP's names for the terms: sex[F], (height-157.4)*(height-157.4),
sex[F]*(age-14.5).

The report tables (Summary of Fit, Analysis of Variance, Parameter
Estimates, Effect Tests, Lack of Fit) are built from statsmodels results
with util.table's shape, so the page formats them.
"""
import itertools
import json
import math
import re

import numpy as np
import pandas as pd

from . import data
from .util import col, table

_MODELS = {}
_ORDER = []


class Design:
    """The frame, the formula and the names of one model."""

    def __init__(self):
        self.df = None
        self.formula = ''
        self.rhs = ''
        self.alias = {}        # column name -> alias
        self.name = {}         # alias -> column name
        self.categorical = set()
        self.means = {}        # alias -> mean, for centred terms
        self.effects = []      # [{'label', 'names', 'terms': [patsy term names]}]
        self.weights = None
        self.y = None
        self.y_alias = None
        self.center = True
        self.coding = 'effect'
        self.levels = {}       # alias -> the levels, in the page's order

    # ---- names ----------------------------------------------------------
    def label(self, column_name):
        """JMP's name for one design column (a patsy column name)."""
        if column_name == 'Intercept':
            return 'Intercept'
        if column_name in getattr(self, 'centered_main', {}):
            return self.name[re.match(r'I\((v\d+) ', column_name).group(1)]
        return '*'.join(self._part(p) for p in _split_colon(column_name))

    def _part(self, p):
        m = re.fullmatch(r'C\((v\d+), (?:Sum|Treatment)(?:\([^)]*\))?\)\[(?:S\.|T\.)?(.*)\]', p)
        if m:
            return f'{self.name[m.group(1)]}[{_level_text(m.group(2))}]'
        m = re.fullmatch(r'I\(\((v\d+) - ([-0-9.e+]+)\) \*\* (\d+)\)', p)
        if m:
            inner = f'({self.name[m.group(1)]}-{_g(float(m.group(2)))})'
            return '*'.join([inner] * int(m.group(3)))
        m = re.fullmatch(r'I\((v\d+) \*\* (\d+)\)', p)
        if m:
            return '*'.join([self.name[m.group(1)]] * int(m.group(2)))
        m = re.fullmatch(r'I\((v\d+) - ([-0-9.e+]+)\)', p)
        if m:
            return f'({self.name[m.group(1)]}-{_g(float(m.group(2)))})'
        if p in self.name:
            return self.name[p]
        return p

    def effect_of(self, term_name):
        for e in self.effects:
            if term_name in e['terms']:
                return e['label']
        return term_name

    # ---- new points ---------------------------------------------------
    def frame_for(self, values):
        """A DataFrame, in alias space, for points given by column name:
        {'age': [12, 13], 'sex': ['F', 'M']} or {'age': 12, 'sex': 'F'}."""
        n = max((len(v) if isinstance(v, (list, tuple, np.ndarray)) else 1) for v in values.values()) if values else 1
        cols = {}
        for name, a in self.alias.items():
            if a == self.y_alias:
                continue
            v = values.get(name)
            if v is None:
                # an unset factor sits at its mean, or at its first level
                if a in self.categorical:
                    v = self.levels[a][0]
                else:
                    v = float(self.df[a].mean())
            v = list(v) if isinstance(v, (list, tuple, np.ndarray)) else [v] * n
            if a in self.categorical:
                cols[a] = pd.Categorical(v, categories=self.levels[a], ordered=False)
            else:
                cols[a] = np.asarray(v, dtype=float)
        return pd.DataFrame(cols)


def _g(x):
    return f'{x:.6g}'


def _level_text(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in '\'"':
        s = s[1:-1]
    try:
        f = float(s)
        if f.is_integer():
            return str(int(f))
        return _g(f)
    except ValueError:
        return s


def _split_colon(name):
    """Split a patsy column name at the ':' between factors, not inside []."""
    parts, depth, cur = [], 0, ''
    for ch in name:
        if ch in '[(':
            depth += 1
        elif ch in '])':
            depth -= 1
        if ch == ':' and depth == 0:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    parts.append(cur)
    return parts


def build(table_id, y, effects, rows=None, weight=None, freq=None, center=True, coding='effect',
          intercept=True, y_as_category=False, extra=()):
    """The design of a model: y (a column name, or a list for several
    responses), effects as above. Rows with a missing value in any column
    used are dropped. extra: more columns to keep in the frame (by name)."""
    d = Design()
    d.center = center
    d.coding = coding
    ys = y if isinstance(y, (list, tuple)) else ([y] if y else [])
    names = []
    for e in effects:
        for n in e:
            if n not in names:
                names.append(n)
    used = list(dict.fromkeys(list(ys) + names + [c for c in extra if c]))
    frame = data.frame(table_id, used + [c for c in (weight, freq) if c], rows, dropna=True, as_category=True)
    frame, w = data.weights(frame, table_id, weight, freq)
    d.weights = w if (weight or freq) else None
    df = pd.DataFrame(index=frame.index)
    for i, n in enumerate(used):
        a = f'v{i}'
        d.alias[n] = a
        d.name[a] = n
        s = frame[n]
        if isinstance(s.dtype, pd.CategoricalDtype) and not (n in ys and not y_as_category):
            s = s.cat.remove_unused_categories()
            d.categorical.add(a)
            d.levels[a] = list(s.cat.categories)
            df[a] = s
        elif isinstance(s.dtype, pd.CategoricalDtype):
            df[a] = s  # a categorical response kept as it is (logistic fits)
            d.levels[a] = list(s.cat.categories)
        else:
            df[a] = s.astype(float)
    d.df = df
    if ys:
        d.y = ys[0] if len(ys) == 1 else ys
        d.y_alias = d.alias[ys[0]]
    for a in d.alias.values():
        if a not in d.categorical and a != d.y_alias and a in df:
            if pd.api.types.is_numeric_dtype(df[a]):
                d.means[a] = float(df[a].mean())
    terms = []
    for e in effects:
        counts = {}
        for n in e:
            counts[n] = counts.get(n, 0) + 1
        crossed = len(e) > 1
        parts = []
        for n, k in counts.items():
            a = d.alias[n]
            if a in d.categorical:
                code = 'Sum' if coding == 'effect' else 'Treatment'
                parts.append(f'C({a}, {code})')
            elif crossed and center:
                m = d.means[a]
                parts.append(f'I(({a} - {m!r}) ** {k})' if k > 1 else f'I({a} - {m!r})')
            elif k > 1:
                parts.append(f'I({a} ** {k})')
            else:
                parts.append(a)
        term = ':'.join(parts)
        terms.append(term)
        d.effects.append({'label': '*'.join(e), 'names': list(e), 'term': term, 'terms': []})
    # A continuous column centred in a crossing is centred in its main effect
    # too: patsy must see one factor, I(x - m), in x + g + x*g, or it codes g
    # at full rank inside the crossing and the design is singular. Only the
    # intercept moves (to the prediction at the mean); estimates() puts it
    # back at x = 0, as JMP reports it.
    d.centered_main = {}
    for i, e in enumerate(d.effects):
        if len(e['names']) != 1:
            continue
        a = d.alias[e['names'][0]]
        if a in d.categorical or a not in d.means:
            continue
        cterm = f'I({a} - {d.means[a]!r})'
        if any(cterm in _split_colon(t) for j, t in enumerate(terms) if j != i):
            terms[i] = cterm
            e['term'] = cterm
            d.centered_main[cterm] = float(d.means[a])
    rhs = ' + '.join(terms) if terms else '1'
    if not intercept:
        rhs += ' - 1'
    d.rhs = rhs
    d.formula = f'{d.y_alias} ~ {rhs}' if d.y_alias else rhs
    return d


def attach_terms(d, res):
    """After fitting: which design columns belong to which effect."""
    di = res.model.data.design_info
    for e in d.effects:
        e['terms'] = []
    for term, sl in di.term_name_slices.items():
        cols = di.column_names[sl]
        for e in d.effects:
            if _same_term(term, e['term']):
                e['terms'] = cols
                e['patsy'] = term
    return d


def _same_term(a, b):
    return sorted(_split_colon(a)) == sorted(_split_colon(b))


def fit_ols(d, alpha=0.05, freq_total=None):
    """Least squares; with a Freq column pass the sum of the frequencies, and
    the error degrees of freedom are JMP's (that sum less the rank)."""
    import statsmodels.formula.api as smf
    mod = smf.wls(d.formula, data=d.df, weights=d.weights) if d.weights is not None else smf.ols(d.formula, data=d.df)
    if freq_total is not None:
        mod.df_resid = float(freq_total) - np.linalg.matrix_rank(mod.exog)
    res = mod.fit()
    attach_terms(d, res)
    return res


def _uncentre(d, names):
    """The map from the fitted parameters to JMP's, the intercept at x = 0
    rather than at the means of the centred main effects; None when nothing
    was centred."""
    cm = getattr(d, 'centered_main', None)
    if not cm or 'Intercept' not in names:
        return None
    T = np.eye(len(names))
    i0 = names.index('Intercept')
    for t, m in cm.items():
        if t in names:
            T[i0, names.index(t)] = -m
    return T


# ---- report tables ----------------------------------------------------------

def summary_of_fit(d, res):
    y = d.df[d.y_alias].to_numpy(float)
    w = d.weights
    mean = float(np.average(y, weights=w)) if w is not None else float(np.mean(y))
    n = float(np.sum(w)) if w is not None else float(len(y))
    rows = [
        {'stat': 'RSquare', 'value': float(res.rsquared)},
        {'stat': 'RSquare Adj', 'value': float(res.rsquared_adj)},
        {'stat': 'Root Mean Square Error', 'value': float(np.sqrt(res.mse_resid)) if res.df_resid > 0 else None},
        {'stat': 'Mean of Response', 'value': mean},
        {'stat': 'Observations (or Sum Wgts)', 'value': n},
    ]
    return table([col('stat', '', 'text'), col('value', '')], rows)


def anova(d, res):
    rows = [
        {'source': 'Model', 'df': float(res.df_model), 'ss': float(res.ess), 'ms': float(res.ess / res.df_model) if res.df_model else None,
         'f': float(res.fvalue) if res.df_model and res.df_resid > 0 else None, 'p': float(res.f_pvalue) if res.df_model and res.df_resid > 0 else None},
        {'source': 'Error', 'df': float(res.df_resid), 'ss': float(res.ssr), 'ms': float(res.mse_resid) if res.df_resid > 0 else None, 'f': None, 'p': None},
        {'source': 'C. Total', 'df': float(res.df_model + res.df_resid), 'ss': float(res.centered_tss if res.k_constant else res.uncentered_tss), 'ms': None, 'f': None, 'p': None},
    ]
    return table([col('source', 'Source', 'text'), col('df', 'DF', 'num'), col('ss', 'Sum of Squares'), col('ms', 'Mean Square'),
                  col('f', 'F Ratio'), col('p', 'Prob > F', 'p')], rows)


def estimates(d, res, alpha=0.05, vif=False):
    ci = res.conf_int(alpha)
    ci = np.asarray(ci)
    names = list(res.params.index)
    tv = np.asarray(res.tvalues, dtype=float)
    pv = np.asarray(res.pvalues, dtype=float)
    se = np.asarray(res.bse, dtype=float)
    est = np.asarray(res.params, dtype=float)
    T = _uncentre(d, names)
    if T is not None:
        from scipy import stats as _st
        i0 = names.index('Intercept')
        V = np.asarray(res.cov_params(), dtype=float)
        est = T @ est
        se = se.copy()
        se[i0] = float(np.sqrt(max(T[i0] @ V @ T[i0], 0.0)))
        tv, pv, ci = tv.copy(), pv.copy(), ci.copy()
        tv[i0] = est[i0] / se[i0] if se[i0] > 0 else float('nan')
        use_t = getattr(res, 'use_t', True)
        dfe = float(getattr(res, 'df_resid', np.inf))
        crit = _st.t.ppf(1 - alpha / 2, dfe) if use_t else _st.norm.ppf(1 - alpha / 2)
        pv[i0] = float(2 * (_st.t.sf(abs(tv[i0]), dfe) if use_t else _st.norm.sf(abs(tv[i0]))))
        ci[i0] = [est[i0] - crit * se[i0], est[i0] + crit * se[i0]]
    vifs = None
    if vif:
        from statsmodels.stats.outliers_influence import variance_inflation_factor
        X = np.asarray(res.model.exog, dtype=float)
        vifs = []
        for j in range(X.shape[1]):
            if names[j] == 'Intercept':
                vifs.append(None)
                continue
            try:
                vifs.append(float(variance_inflation_factor(X, j)))
            except Exception:
                vifs.append(None)
    rows = []
    for j, nm in enumerate(names):
        r = {'term': d.label(nm), 'estimate': est[j], 'se': se[j], 't': tv[j], 'p': pv[j], 'lower': ci[j, 0], 'upper': ci[j, 1], 'name': nm}
        if vifs is not None:
            r['vif'] = vifs[j]
        rows.append(r)
    # In the order of the effects as given (patsy sorts terms its own way).
    rank = {'Intercept': -1}
    for i, e in enumerate(d.effects):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    rows.sort(key=lambda r: rank.get(r['name'], len(d.effects)))
    stat = 'z Ratio' if getattr(res, 'use_t', True) is False else 't Ratio'
    pl = 'Prob>|z|' if stat == 'z Ratio' else 'Prob>|t|'
    lv = f'{100 * (1 - alpha):g}%'
    cols = [col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('t', stat), col('p', pl, 'p'),
            col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}')]
    if vif:
        cols.append(col('vif', 'VIF'))
    return table(cols, rows)


def effect_tests(d, res):
    """F tests of each effect, all others in the model (JMP's Effect Tests;
    Type III with effect coding)."""
    rows = []
    try:
        frame = res.wald_test_terms(skip_single=False, scalar=True).table
    except Exception:
        frame = None
    linear = hasattr(res, 'mse_resid') and getattr(res, 'df_resid', 0) > 0 and hasattr(res, 'ssr')
    mse = float(res.mse_resid) if linear else float('nan')
    for e in d.effects:
        term = e.get('patsy')
        if frame is None or term not in frame.index:
            continue
        r = frame.loc[term]
        nparm = int(r['df_constraint'])
        stat = float(r['statistic'])
        row = {'source': e['label'], 'nparm': nparm, 'df': nparm, 'stat': stat, 'p': float(r['pvalue'])}
        if linear:
            row['ss'] = stat * nparm * mse
        rows.append(row)
    if linear:
        cols = [col('source', 'Source', 'text'), col('nparm', 'Nparm', 'int'), col('df', 'DF', 'int'), col('ss', 'Sum of Squares'),
                col('stat', 'F Ratio'), col('p', 'Prob > F', 'p')]
    else:
        cols = [col('source', 'Source', 'text'), col('nparm', 'Nparm', 'int'), col('df', 'DF', 'int'),
                col('stat', 'Wald ChiSquare'), col('p', 'Prob > ChiSq', 'p')]
    return table(cols, rows)


def lack_of_fit(d, res):
    """Pure error from rows with the same values of every factor; the rest of
    the error is lack of fit. None when nothing is replicated."""
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
    from scipy import stats
    f = (lof_ss / lof_df) / (pe_ss / pe_df) if pe_ss > 0 else float('nan')
    p = float(stats.f.sf(f, lof_df, pe_df)) if np.isfinite(f) else None
    max_r2 = 1 - pe_ss / float(res.centered_tss) if res.centered_tss else None
    rows = [
        {'source': 'Lack Of Fit', 'df': lof_df, 'ss': lof_ss, 'ms': lof_ss / lof_df, 'f': f, 'p': p},
        {'source': 'Pure Error', 'df': pe_df, 'ss': pe_ss, 'ms': pe_ss / pe_df, 'f': None, 'p': None},
        {'source': 'Total Error', 'df': float(res.df_resid), 'ss': float(res.ssr), 'ms': None, 'f': None, 'p': None},
    ]
    return table([col('source', 'Source', 'text'), col('df', 'DF', 'num'), col('ss', 'Sum of Squares'), col('ms', 'Mean Square'),
                  col('f', 'F Ratio'), col('p', 'Prob > F', 'p')], rows, max_rsquare=max_r2)


def diagnostics(d, res):
    """Per row: predicted, residual, studentized residual, leverage, Cook's D,
    with the page's row numbers. In closed form, from the SVD of the
    whitened design, so weighted fits have them too (statsmodels' own
    external studentized residuals refit the model once per row)."""
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
            'residual': np.asarray(res.resid, dtype=float), 'actual': d.df[d.y_alias].to_numpy(float),
            'studentized': ri, 'externally': ext, 'hat': h, 'cooks': cooks}


def durbin_watson(res):
    from statsmodels.stats.stattools import durbin_watson as dw
    e = np.asarray(res.resid, dtype=float)
    return {'dw': float(dw(e)), 'n': len(e), 'autocorr': float(np.corrcoef(e[:-1], e[1:])[0, 1]) if len(e) > 2 else None}


# ---- remembered fits, for profilers and predictions -----------------------

def remember(key, value, keep=24):
    _MODELS[key] = value
    if key in _ORDER:
        _ORDER.remove(key)
    _ORDER.append(key)
    while len(_ORDER) > keep:
        _MODELS.pop(_ORDER.pop(0), None)
    return key


def recall(key):
    return _MODELS.get(key)


def model_key(*parts):
    return json.dumps(parts, sort_keys=True, default=str)


# ---- code shown under the reports -------------------------------------------

def code_formula(d, lhs=True):
    """The model as a statsmodels formula over the real names, which gives
    the report's estimates exactly: the page's level order, the means in
    full, the centred main effects, '- 1' without an intercept. lhs=False
    gives the right-hand side only."""
    from .util import q
    cm = getattr(d, 'centered_main', {})
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
                # The page's level order, so that the shown code drops the same
                # level (and gives the same signs) as the report.
                lv = [x.item() if hasattr(x, 'item') else x for x in d.levels[a]]
                ps.append(f'C({q(n)}, {"Sum" if d.coding == "effect" else "Treatment"}, levels={lv!r})')
            elif (crossed and d.center) or (k == 1 and f'I({a} - {d.means.get(a)!r})' in cm):
                m = d.means[a]
                ps.append(f'I(({q(n)} - {m!r}) ** {k})' if k > 1 else f'I({q(n)} - {m!r})')
            elif k > 1:
                ps.append(f'I({q(n)} ** {k})')
            else:
                ps.append(q(n))
        parts.append(':'.join(ps))
    rhs = ' + '.join(parts) if parts else '1'
    if d.rhs.endswith(' - 1'):
        rhs += ' - 1'
    y = d.y if isinstance(d.y, str) else (d.y[0] if d.y else '')
    return f'{q(y)} ~ {rhs}' if (y and lhs) else rhs


def full_factorial(names, degree=None):
    """JMP's Full Factorial macro: every crossing of the names (up to degree)."""
    out = []
    k = len(names) if degree is None else min(degree, len(names))
    for r in range(1, k + 1):
        for combo in itertools.combinations(names, r):
            out.append(list(combo))
    return out


def response_surface(names, categorical=()):
    """JMP's Response Surface macro: main effects, two-way crossings, and
    squares of the continuous ones."""
    out = [[n] for n in names]
    out += [list(c) for c in itertools.combinations(names, 2)]
    out += [[n, n] for n in names if n not in categorical]
    return out
