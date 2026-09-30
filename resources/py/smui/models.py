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

Saved columns: new_rows() gives the design rows of every row of the table
in a By group whose model columns have values (rows left out of the fit
too: excluded, missing the response, held out for validation), so a saved
prediction covers them as JMP's does; formula_linear() writes a model's
linear predictor in the page's formula language (Save Prediction Formula).
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


def estimates(d, res, alpha=0.05, vif=False, std_beta=False, design_se=False):
    """Parameter Estimates in JMP's form (the intercept at x = 0, the terms in
    the order of the effects), with the optional columns VIF, Std Beta (the
    estimate had Y and the term's design column been standardized, b sd(x) /
    sd(y), by the fit's weights) and Design Std Error (the standard error
    over sigma: the square root of the diagonal of (X'WX)^-1)."""
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
    sbeta = dse = None
    if std_beta or design_se:
        X = np.asarray(res.model.exog, dtype=float)
        if std_beta:
            yv = np.asarray(res.model.endog, dtype=float)
            wv = np.broadcast_to(np.asarray(getattr(res.model, 'weights', 1.0), dtype=float), yv.shape)

            def _ss(v):
                return float(np.sum(wv * (v - np.sum(wv * v) / np.sum(wv)) ** 2))
            syy = _ss(yv)
            sbeta = [None if nm == 'Intercept' or not syy > 0 else float(est[j] * math.sqrt(_ss(X[:, j]) / syy)) for j, nm in enumerate(names)]
        if design_se:
            NC = np.asarray(res.normalized_cov_params, dtype=float)
            if T is not None:
                NC = T @ NC @ T.T
            dse = [float(math.sqrt(max(v, 0.0))) for v in np.diag(NC)]
    rows = []
    zero, biased = set(getattr(d, 'zeroed', None) or ()), set(getattr(d, 'biased', None) or ())
    for j, nm in enumerate(names):
        r = {'term': d.label(nm), 'estimate': est[j], 'se': se[j], 't': tv[j], 'p': pv[j], 'lower': ci[j, 0], 'upper': ci[j, 1], 'name': nm}
        if vifs is not None:
            r['vif'] = vifs[j]
        if sbeta is not None:
            r['std_beta'] = sbeta[j]
        if dse is not None:
            r['design_se'] = dse[j]
        if zero:   # a singular design, as JMP marks it
            r['bias'] = 'Zeroed' if nm in zero else 'Biased' if nm in biased else ''
            if nm in zero:
                r.update({k: None for k in ('se', 't', 'p', 'lower', 'upper', 'vif', 'std_beta', 'design_se') if k in r or k in ('se', 't', 'p', 'lower', 'upper')})
                r['estimate'] = 0.0
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
    if getattr(d, 'zeroed', None):
        cols.insert(1, col('bias', '', 'text'))
    if std_beta:
        cols.append(col('std_beta', 'Std Beta'))
    if vif:
        cols.append(col('vif', 'VIF'))
    if design_se:
        cols.append(col('design_se', 'Design Std Error'))
    return table(cols, rows)


def effect_tests(d, res):
    """F tests of each effect, all others in the model (JMP's Effect Tests;
    Type III with effect coding). A singular design with zeroed columns
    (d.zeroed): each effect is tested on its other columns, DF the number of
    them and LostDFs the zeroed ones, as JMP."""
    if getattr(d, 'zeroed', None):
        return _effect_tests_zeroed(d, res)
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


def _effect_tests_zeroed(d, res):
    from scipy import stats as st_
    names = list(res.params.index)
    b = np.asarray(res.params, dtype=float)
    V = np.asarray(res.cov_params(), dtype=float)
    linear = hasattr(res, 'mse_resid') and getattr(res, 'df_resid', 0) > 0 and hasattr(res, 'ssr')
    mse = float(res.mse_resid) if linear else float('nan')
    dfe = float(getattr(res, 'df_resid_inference', None) or res.df_resid)
    zero = set(d.zeroed)
    rows = []
    for e in d.effects:
        cols = [names.index(c) for c in e.get('terms', []) if c in names]
        if not cols:
            continue
        tested = [j for j in cols if names[j] not in zero]
        q = len(tested)
        row = {'source': e['label'], 'nparm': len(cols), 'df': q, 'lost': len(cols) - q, 'stat': None, 'p': None}
        if q:
            bs = b[tested]
            stat = float(bs @ np.linalg.solve(V[np.ix_(tested, tested)], bs)) / q
            row['stat'] = stat
            row['p'] = float(st_.f.sf(stat, q, dfe)) if linear else float(st_.chi2.sf(stat * q, q))
            if not linear:
                row['stat'] = stat * q
            if linear:
                row['ss'] = stat * q * mse
        elif linear:
            row['ss'] = 0.0
        rows.append(row)
    if linear:
        cols_ = [col('source', 'Source', 'text'), col('nparm', 'Nparm', 'int'), col('df', 'DF', 'int'), col('lost', 'LostDFs', 'int'),
                 col('ss', 'Sum of Squares'), col('stat', 'F Ratio'), col('p', 'Prob > F', 'p')]
    else:
        cols_ = [col('source', 'Source', 'text'), col('nparm', 'Nparm', 'int'), col('df', 'DF', 'int'), col('lost', 'LostDFs', 'int'),
                 col('stat', 'Wald ChiSquare'), col('p', 'Prob > ChiSq', 'p')]
    return table(cols_, rows)


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


# ---- saved columns: every row's design, and the prediction formula ----------

def group_mask(tid, where):
    """The rows of the table in a By group: those whose By columns hold the
    group's values (every row of the table without By)."""
    n = data.TABLES[tid]['n']
    mask = np.ones(n, dtype=bool)
    for w in where or []:
        name, val = w['column'], w['value']
        v = data.raw(tid, name)
        if data.meta(tid, name).get('dataType') == 'numeric':
            try:
                fv = float(val)
            except (TypeError, ValueError):
                return np.zeros(n, dtype=bool)
            mask &= np.asarray(v, dtype=float) == fv
        else:
            mask &= np.array([x == val for x in v], dtype=bool)
    return mask


def design_columns(d):
    """The columns a design's effects read (crossed and nested ones too), in
    the order they first appear; not the response."""
    ys = set(d.y if isinstance(d.y, (list, tuple)) else ([d.y] if d.y else []))
    out = []
    for e in d.effects:
        for n in (e.get('cols') or e['names']):
            if n not in ys and n not in out:
                out.append(n)
    return out


def new_rows(d, di, tid, where=None, rows=None, extra=()):
    """The design rows, as the fit's design_info makes them, of every row of
    the table in the By group (where) or of the given rows, whose model
    columns and extra columns all have values: rows the fit left out
    (excluded, missing the response, held out for validation) included, as a
    formula column would compute them. A level the fit did not see (a
    categorical value outside the design's levels) gives no row. Returns
    (index, X, extra values): the table's row numbers, the design rows, and
    {extra column: values} for those rows."""
    import patsy
    cols = design_columns(d)
    extra = [c for c in dict.fromkeys(extra) if c and c not in cols]
    fr = data.frame(tid, cols + extra, rows, dropna=False)
    if rows is None:
        fr = fr[group_mask(tid, where)]
    ok = np.ones(len(fr), dtype=bool)
    parts = {}
    for nm in cols:
        a = d.alias[nm]
        s = fr[nm]
        if a in d.categorical:
            if not isinstance(s.dtype, pd.CategoricalDtype):
                s = pd.Series(pd.Categorical(s, categories=d.levels[a]), index=s.index)
            else:
                s = s.cat.set_categories(d.levels[a])
            ok &= s.notna().to_numpy()
            parts[a] = s
        else:
            v = pd.to_numeric(pd.Series(np.asarray(s, dtype=object)), errors='coerce').to_numpy(float)
            ok &= np.isfinite(v)
            parts[a] = v
    ex = {}
    for nm in extra:
        v = pd.to_numeric(pd.Series(np.asarray(fr[nm], dtype=object)), errors='coerce').to_numpy(float)
        ok &= np.isfinite(v)
        ex[nm] = v
    idx = fr.index.to_numpy()[ok]
    p = len(di.column_names)
    if not len(idx):
        X = np.zeros((0, p))
    elif not cols:
        X = np.ones((len(idx), p))           # the intercept alone
    else:
        frame = pd.DataFrame({a: (v.array[ok] if isinstance(v, pd.Series) else v[ok]) for a, v in parts.items()}, index=idx)
        X = np.asarray(patsy.build_design_matrices([di], frame, NA_action='raise')[0], dtype=float)
    return idx, X, {k: v[ok] for k, v in ex.items()}


def combos(widths):
    """Column combinations of a patsy subterm, the left-most factor iterating
    fastest, as patsy orders them."""
    for rev in itertools.product(*[range(w) for w in reversed(widths)]):
        yield rev[::-1]


_CAT_FACTOR = re.compile(r'C\((v\d+)')
_NUMERIC = (
    (re.compile(r'^(v\d+)$'), lambda m, ref: ref(m.group(1))),
    (re.compile(r'^I\(\((v\d+) - (.+)\) \*\* (\d+)\)$'), lambda m, ref: f'{_shifted(ref(m.group(1)), float(m.group(2)))}^{m.group(3)}'),
    (re.compile(r'^I\((v\d+) - (.+)\)$'), lambda m, ref: _shifted(ref(m.group(1)), float(m.group(2)))),
    (re.compile(r'^I\((v\d+) \*\* (\d+)\)$'), lambda m, ref: f'{ref(m.group(1))}^{m.group(2)}'),
)


def _shifted(r, mean):
    from .util import formula_num
    return f'({r} - {formula_num(mean)})' if mean >= 0 else f'({r} + {formula_num(-mean)})'


def numeric_text(code, ref):
    """A continuous factor of a design (x, x centred, a power of either) in
    formula text; ref(alias) gives the column's reference."""
    for rx, fn in _NUMERIC:
        m = rx.match(code)
        if m:
            return fn(m, ref)
    raise ValueError(f'no formula for the design factor {code}')


def formula_linear(d, di, b, tid):
    """The linear predictor b'x of a design as formula text over the table's
    columns (the page's formula language, smui-formula.js), in JMP's form:
    each term's categorical factors as a Match of their levels (nested for a
    crossing) giving the term's coefficient at that level, its effect
    coding folded in (the last level minus the sum of the others); a
    continuous factor as the design has it, centred ((:x - mean)) where the
    fit centred it, a power as ^; a level the fit did not see gives a
    missing value."""
    from .util import formula_num, formula_ref, formula_str
    b = np.asarray(b, dtype=float)

    def ref(a):
        return formula_ref(d.name[a])

    def lit(a, v):
        if data.meta(tid, d.name[a]).get('dataType') == 'numeric':
            return formula_num(v)
        return formula_str(v.item() if hasattr(v, 'item') else v)
    pieces = []
    j = 0
    for _term, subterms in di.term_codings.items():
        for st in subterms:
            cats, nums, widths = [], [], []
            for f in st.factors:
                fi = di.factor_infos[f]
                if fi.type == 'categorical':
                    cm = np.asarray(st.contrast_matrices[f].matrix, dtype=float)
                    cats.append((_CAT_FACTOR.match(f.code).group(1), cm, len(widths), list(fi.categories)))
                    widths.append(cm.shape[1])
                else:
                    nums.append(numeric_text(f.code, ref))
                    widths.append(int(fi.num_columns))
            ncol = int(np.prod(widths)) if widths else 1
            coef = b[j:j + ncol]
            cmb = list(combos(widths)) if widths else [()]
            j += ncol
            if not cats:
                c = float(coef[0])
                if c != 0:
                    pieces.append(' * '.join([formula_num(c)] + nums))
                continue

            def value(levels):
                v = 0.0
                for cc, combo in zip(coef, cmb):
                    prod = float(cc)
                    for (_a, cm, pos, _lv), li in zip(cats, levels):
                        prod *= cm[li, combo[pos]]
                    v += prod
                return v
            grid = {}
            for lv in itertools.product(*[range(len(c[3])) for c in cats]):
                grid[lv] = value(lv)
            if all(v == 0 for v in grid.values()):
                continue

            def match(k, prefix):
                a, _cm, _pos, levels = cats[k]
                parts = []
                for li, lv in enumerate(levels):
                    inner = formula_num(grid[prefix + (li,)]) if k == len(cats) - 1 else match(k + 1, prefix + (li,))
                    parts.append(f'{lit(a, lv)}, {inner}')
                return f'Match({ref(a)}, {", ".join(parts)}, .)'
            pieces.append(' * '.join([match(0, ())] + nums))
    return ' + '.join(pieces) if pieces else '0'


# the mean from the linear predictor, as formula text (statsmodels' links)
INVERSE_LINK = {'identity': '{}', 'log': 'Exp({})', 'logit': 'Squash({})', 'probit': 'Normal Distribution({})',
                'cloglog': '1 - Exp(-Exp({}))', 'reciprocal': '1 / ({})', 'inverse_squared': '1 / Sqrt({})', 'sqrt': '({})^2'}


def where_condition(tid, where):
    """The condition, in formula text, that holds for the rows of a By group
    (:by == value & ...), or None without By."""
    from .util import formula_num, formula_ref, formula_str
    if not where:
        return None
    conds = []
    for w in where:
        num = data.meta(tid, w['column']).get('dataType') == 'numeric'
        conds.append(f'{formula_ref(w["column"])} == {formula_num(w["value"]) if num else formula_str(w["value"])}')
    return ' & '.join(conds)


def formula_where(tid, where, expr):
    """A formula for the rows of a By group only: If(:by == value, expr, .)."""
    cond = where_condition(tid, where)
    return expr if cond is None else f'If({cond}, {expr}, .)'


class Ref:
    """A reference, in a formula, to the k-th column saved with it."""
    __slots__ = ('k',)

    def __init__(self, k):
        self.k = k


def segs(*parts):
    """Formula text that refers to columns saved with it: a list of text and
    {'ref': k}, the k-th column of the save (the page puts in its name, which
    the table may have changed to keep names unique)."""
    out = []
    for p in parts:
        if isinstance(p, Ref):
            out.append({'ref': p.k})
        elif p:
            if out and isinstance(out[-1], str):
                out[-1] += p
            else:
                out.append(p)
    return out


def probability_formulas(mode, labels, lins, y_name, target=0, cuts=None, distr='logit'):
    """Save Probability Formula of a logistic model, as JMP names and writes
    it: the linear predictors, then Prob[level] from them, then Most Likely
    y, the level with the largest probability (the first of equals). mode
    'binary': lins = [the target's log odds] (Lin[target]); 'multinomial':
    lins = each level's log odds against the last (Lin[level]); 'ordinal':
    lins = [x'b] (Linear) with cuts, the thresholds a_j of P(Y <= j) =
    F(a_j + x'b), F logistic or normal (Cum[level])."""
    from .util import formula_num, formula_str
    k = len(labels)
    F = []
    if mode == 'binary':
        F.append({'name': f'Lin[{labels[target]}]', 'expr': lins[0]})
        probs = [segs('Squash(', Ref(0), ')') if j == target else segs('1 - Squash(', Ref(0), ')') for j in range(k)]
    elif mode == 'multinomial':
        for q in range(k - 1):
            F.append({'name': f'Lin[{labels[q]}]', 'expr': lins[q]})
        den = ['1']
        for q in range(k - 1):
            den += [' + Exp(', Ref(q), ')']
        probs = [segs('Exp(', Ref(q), ') / (', *den, ')') for q in range(k - 1)] + [segs('1 / (', *den, ')')]
    else:
        F.append({'name': 'Linear', 'expr': lins[0]})
        cdf = 'Squash' if distr == 'logit' else 'Normal Distribution'
        for j in range(k - 1):
            F.append({'name': f'Cum[{labels[j]}]', 'expr': segs(f'{cdf}({formula_num(cuts[j])} + ', Ref(0), ')')})
        probs = [segs(Ref(1))] + [segs(Ref(1 + j), ' - ', Ref(j)) for j in range(1, k - 1)] + [segs('1 - ', Ref(k - 1))]
    first = len(F)
    for j in range(k):
        F.append({'name': f'Prob[{labels[j]}]', 'expr': probs[j]})
    mx = ['Max(']
    for j in range(k):
        mx += ([', '] if j else []) + [Ref(first + j)]
    mx.append(')')
    parts = ['If(']
    for j in range(k - 1):
        parts += ([', '] if j else []) + [Ref(first + j), ' == ', *mx, f', {formula_str(labels[j])}']
    parts.append(f', {formula_str(labels[-1])})')
    F.append({'name': f'Most Likely {y_name}', 'expr': segs(*parts), 'character': True,
              'modelingType': 'ordinal' if mode == 'ordinal' else 'nominal', 'valueOrder': list(labels)})
    return F


def logistic_lack_of_fit(pattern, y, w, k, llf, df_fit):
    """JMP's Lack of Fit of a logistic model: the fitted model against the
    saturated one, which gives each distinct pattern of the X values its own
    probabilities of the k levels (their shares among the pattern's rows,
    each row counted by its weight). pattern: each row's pattern (codes), y:
    its level index, llf: the fitted model's log-likelihood, df_fit: its
    parameters beyond the intercepts. -LogLikelihood of Lack Of Fit is
    -llf - (-LL_saturated), ChiSquare twice that on (patterns - 1)(k - 1) -
    df_fit degrees of freedom. None when no pattern holds two rows or no
    degree of freedom is left."""
    from scipy import stats as st_
    pattern = np.asarray(pd.factorize(np.asarray(pattern))[0], dtype=int)
    y = np.asarray(y, dtype=int)
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    m = int(pattern.max()) + 1 if len(pattern) else 0
    if m >= len(y):
        return None
    cnt = np.zeros((m, k))
    np.add.at(cnt, (pattern, y), w)
    tot = cnt.sum(axis=1, keepdims=True)
    with np.errstate(divide='ignore', invalid='ignore'):
        ll_sat = float(np.sum(np.where(cnt > 0, cnt * np.log(cnt / tot), 0.0)))
    df_sat = (m - 1) * (k - 1)
    df_lof = df_sat - int(df_fit)
    if df_lof <= 0:
        return None
    nll_lof = max(-llf - (-ll_sat), 0.0)
    chi = 2 * nll_lof
    rows = [{'source': 'Lack Of Fit', 'df': float(df_lof), 'nll': nll_lof, 'chisq': chi, 'p': float(st_.chi2.sf(chi, df_lof))},
            {'source': 'Saturated', 'df': float(df_sat), 'nll': -ll_sat, 'chisq': None, 'p': None},
            {'source': 'Fitted', 'df': float(df_fit), 'nll': -float(llf), 'chisq': None, 'p': None}]
    return table([col('source', 'Source', 'text'), col('df', 'DF', 'num'), col('nll', '-LogLikelihood'), col('chisq', 'ChiSquare'),
                  col('p', 'Prob>ChiSq', 'p')], rows, patterns=m)


LOGISTIC_LOF_CODE = [
    'def lack_of_fit(pattern, y, w, k, llf, df_fit):',
    '    """The fitted model against the saturated one (each X pattern its own shares of the levels), as JMP\'s Lack of Fit."""',
    '    p_ = pd.factorize(pattern)[0]; m = p_.max() + 1',
    '    cnt = np.zeros((m, k)); np.add.at(cnt, (p_, y), w)',
    '    ll_sat = np.sum(np.where(cnt > 0, cnt * np.log(np.where(cnt > 0, cnt, 1) / cnt.sum(axis=1, keepdims=True)), 0.0))',
    '    df_lof = (m - 1) * (k - 1) - df_fit; chi = 2 * (ll_sat - llf)',
    '    return df_lof, ll_sat - llf, chi, stats.chi2.sf(chi, df_lof)   # DF, -LogLikelihood, ChiSquare and Prob>ChiSq of Lack Of Fit',
]


# ---- the Estimates menu: Indicator Parameterization and Expanded Estimates ------------------------------
# JMP's effect coding reparametrized: Indicator Parameterization Estimates code each effect-coded factor 0/1,
# its last level the reference (the same fit when the model holds the effects a crossing contains; otherwise
# a fit of its own), and Expanded Estimates give every level (combination) of a term its parameter, the
# last level's the negative sum of the others'. Both keep the report's intercept at x = 0 (estimates()).

def _last_level(d, a):
    cats = d.df[a].cat.categories if isinstance(d.df[a].dtype, pd.CategoricalDtype) else d.levels[a]
    v = list(cats)[-1]
    return v.item() if hasattr(v, 'item') else v


def indicator_rhs(d):
    """The design's right-hand side with each effect-coded factor 0/1 coded, its last level the reference."""
    return re.sub(r'C\((v\d+), Sum\)', lambda m: f'C({m.group(1)}, Treatment(reference={_last_level(d, m.group(1))!r}))', d.rhs)


def _indicator_to_effect(nm):
    """An indicator column's name as the effect-coded design names the same level (both leave out the last)."""
    return re.sub(r'C\((v\d+), Treatment\(reference=[^)]*\)\)\[T\.', r'C(\1, Sum)[S.', nm)


def _estimate_rows(d, names, b, V, dfe, use_t, alpha, labels=None, order=None):
    from scipy import stats as st_
    se = np.sqrt(np.maximum(np.diag(V), 0.0))
    crit = st_.t.ppf(1 - alpha / 2, dfe) if use_t else st_.norm.ppf(1 - alpha / 2)
    rows = []
    for j, nm in enumerate(names):
        t = b[j] / se[j] if se[j] > 0 else float('nan')
        p = float(2 * (st_.t.sf(abs(t), dfe) if use_t else st_.norm.sf(abs(t)))) if np.isfinite(t) else None
        rows.append({'term': labels[j] if labels else d.label(nm), 'estimate': float(b[j]), 'se': float(se[j]), 't': t, 'p': p,
                     'lower': float(b[j] - crit * se[j]), 'upper': float(b[j] + crit * se[j]), 'name': nm})
    rank = {'Intercept': -1}
    for i, e in enumerate(d.effects):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    key = order or (lambda r: rank.get(r['name'], len(d.effects)))
    rows.sort(key=key)
    return rows


def _estimate_columns(use_t, alpha):
    stat = 't Ratio' if use_t else 'z Ratio'
    lv = f'{100 * (1 - alpha):g}%'
    return [col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('t', stat),
            col('p', 'Prob>|t|' if use_t else 'Prob>|z|', 'p'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}')]


def indicator_estimates(d, res, alpha=0.05, df=None):
    """Indicator Parameterization Estimates: the fit's parameters with each
    effect-coded factor 0/1 coded (the last level the reference, its column
    left out), a crossing the products of the indicators. When the effect
    coded design lies in the indicator design's span (every effect a crossing
    contains is in the model) this is the same fit reparametrized: b_i = K b
    and V_i = K V K' with K = pinv(X_i) X, so the robust covariance carries
    over; otherwise the indicator design is a model of its own, fitted here
    by (weighted) least squares ('refit' True)."""
    import patsy
    Xe = np.asarray(res.model.exog, dtype=float)
    Xi_df = patsy.dmatrix(indicator_rhs(d), d.df, return_type='dataframe', NA_action='raise')
    Xi = Xi_df.to_numpy(float)
    names = list(Xi_df.columns)
    if Xi.shape[0] != Xe.shape[0]:
        raise ValueError('the indicator design does not have the fit\'s rows')
    K = np.linalg.pinv(Xi) @ Xe
    scale = max(1.0, float(np.max(np.abs(Xe)))) if Xe.size else 1.0
    exact = bool(np.max(np.abs(Xi @ K - Xe)) <= 1e-8 * scale) if Xe.size else True
    use_t = getattr(res, 'use_t', True) is not False
    dfe = float(getattr(res, 'df_resid', np.inf)) if df is None else float(df)
    if exact:
        b = K @ np.asarray(res.params, dtype=float)
        V = K @ np.asarray(res.cov_params(), dtype=float) @ K.T
    else:
        import statsmodels.api as sm_
        w = np.broadcast_to(np.asarray(getattr(res.model, 'weights', 1.0), dtype=float), (Xi.shape[0],))
        mod = sm_.WLS(np.asarray(res.model.endog, dtype=float), Xi, weights=w)
        mod.df_resid = res.model.df_resid
        r2 = mod.fit()
        b, V, dfe, use_t = np.asarray(r2.params, dtype=float), np.asarray(r2.cov_params(), dtype=float), float(r2.df_resid), True
    T = _uncentre(d, names)
    if T is not None:
        b, V = T @ b, T @ V @ T.T
    labels = [d.label(nm) for nm in names]
    rows = _estimate_rows(d, [_indicator_to_effect(nm) for nm in names], b, V, dfe, use_t, alpha, labels=labels)
    return table(_estimate_columns(use_t, alpha), rows, refit=not exact)


def expanded_estimates(d, res, alpha=0.05, df=None):
    """Expanded Estimates: each term with categorical factors at every
    combination of their levels, its estimate the term's coded columns
    there times the parameters (for effect coding the last level's is minus
    the sum of the others'), with its standard error from the covariance;
    continuous terms as they are. The nested effects list the combinations
    that occur. Also 'L': each line's weights of the parameters (the code
    prints them from the fit)."""
    di = res.model.data.design_info
    names = list(res.params.index)
    b = np.asarray(res.params, dtype=float)
    V = np.asarray(res.cov_params(), dtype=float)
    T = _uncentre(d, names)
    if T is None:
        T = np.eye(len(names))
    p = len(names)
    lines = []
    j = 0
    for term, subterms in di.term_codings.items():
        e_ = next((e for e in d.effects if e.get('patsy') and _same_term(e['patsy'], term.name())), None)
        nested = bool(e_ and (e_.get('spec') or {}).get('nest'))
        for st in subterms:
            cats, parts, widths = [], [], []
            for f in st.factors:
                fi = di.factor_infos[f]
                if fi.type == 'categorical':
                    cm = np.asarray(st.contrast_matrices[f].matrix, dtype=float)
                    a = _CAT_FACTOR.match(f.code).group(1)
                    cats.append((a, cm, len(widths), list(fi.categories)))
                    parts.append(('cat', len(cats) - 1))
                    widths.append(cm.shape[1])
                else:
                    parts.append(('num', d._part(f.code)))
                    widths.append(int(fi.num_columns))
            ncol = int(np.prod(widths)) if widths else 1
            if not cats:
                for c in range(j, j + ncol):
                    lines.append((names[c], d.label(names[c]), T[c].copy()))
                j += ncol
                continue
            cmb = list(combos(widths))
            seen = None
            if nested:
                codes = np.column_stack([pd.Categorical(d.df[a], categories=lv).codes for a, _cm, _pos, lv in cats])
                seen = {tuple(r) for r in codes.tolist()}
            for lv in itertools.product(*[range(len(c[3])) for c in cats]):
                if seen is not None and lv not in seen:
                    continue
                L = np.zeros(p)
                for k_, combo in enumerate(cmb):
                    prod = 1.0
                    for (_a, cm, pos, _l), li in zip(cats, lv):
                        prod *= cm[li, combo[pos]]
                    L[j + k_] = prod
                if not L.any():
                    continue
                lab = '*'.join(f'{d.name[cats[i][0]]}[{_level_text(str(cats[i][3][lv[i]]))}]' if kind == 'cat' else i for kind, i in parts)
                lines.append((names[j], lab, L))
            j += ncol
    use_t = getattr(res, 'use_t', True) is not False
    dfe = float(getattr(res, 'df_resid', np.inf)) if df is None else float(df)
    # in the order of the effects as given, as the Parameter Estimates (patsy sorts terms its own way)
    rank = {'Intercept': -1}
    for i, e in enumerate(d.effects):
        for c in e.get('terms', []):
            rank.setdefault(c, i)
    lines.sort(key=lambda ln: rank.get(ln[0], len(d.effects)))
    Lm = np.array([ln[2] for ln in lines]) if lines else np.zeros((0, p))
    est, C = Lm @ b, Lm @ V @ Lm.T
    rows = _estimate_rows(d, [ln[0] for ln in lines], est, C, dfe, use_t, alpha, labels=[ln[1] for ln in lines], order=lambda r: 0)
    return table(_estimate_columns(use_t, alpha), rows, L=[{int(k): float(v) for k, v in enumerate(ln[2]) if v != 0} for ln in lines])


# ---- Unstable estimates of a logistic fit (JMP marks them) --------------------------------------------
def unstable_params(loglike, params, cov, tol=1e-3, scales=None):
    """Which parameters of a maximum likelihood fit do not settle: along a
    direction in which the estimates are least determined (an eigenvector of
    their covariance), a step of five standard errors (at most 10 on the
    scale of the linear predictor's coefficients: a flat likelihood's
    standard errors are huge, and so would the step's misalignment be) away
    from zero does not lower the log-likelihood by tol, so the data separate
    the levels along it
    (a level of a factor, or a range of X, where every row has the same
    response level) and the maximum is at infinity. Every parameter that
    takes part in such a direction (a tenth of its largest weight or more,
    each weight times the parameter's scale: the root mean square of its
    design column, so that a slope and an intercept compare by what they do
    to the linear predictor), or whose variance is not finite, is unstable.
    loglike(v) is the fit's log-likelihood at the parameter vector v (in the
    covariance's order)."""
    b = np.asarray(params, dtype=float).ravel()
    C = np.asarray(cov, dtype=float)
    out = np.zeros(len(b), dtype=bool)
    if not len(b):
        return out
    bad = ~np.isfinite(np.diag(C)) | (np.diag(C) < 0)
    out |= bad
    ok = ~bad
    if not ok.any():
        return out
    Cs = C[np.ix_(ok, ok)]
    if not np.all(np.isfinite(Cs)):
        return out | ok
    lam, U = np.linalg.eigh((Cs + Cs.T) / 2)
    idx = np.flatnonzero(ok)
    try:
        L0 = float(loglike(b))
    except Exception:
        return out
    for i in range(len(lam)):
        if not lam[i] > 0:
            continue
        u = np.zeros(len(b))
        u[idx] = U[:, i]
        s = 1.0 if float(u @ b) >= 0 else -1.0
        step = min(5 * math.sqrt(lam[i]), 10.0)
        try:
            L1 = float(loglike(b + s * step * u))
        except Exception:
            continue
        if np.isfinite(L1) and L1 > L0 - tol:
            su = np.abs(u) * (1.0 if scales is None else np.asarray(scales, dtype=float))
            out |= su >= 0.1 * np.max(su)
    return out
