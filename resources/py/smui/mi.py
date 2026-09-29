"""Analyze > Screening > Multiple Imputation: missing values filled in m
times, an analysis model fitted to each completed table, and the fits
pooled by Rubin's rules, with statsmodels' two imputers:

  MICE   statsmodels.imputation.mice (MICEData, MICE): chained equations,
         each column with missing values in turn regressed (least squares)
         on the others, the regression's parameters drawn from their
         approximate sampling distribution and each missing value replaced
         by the observed value of one of the 20 rows whose predictions are
         nearest (predictive mean matching). One chain: a burn-in, then an
         imputation every n_skip + 1 cycles.
  Bayes  statsmodels.imputation.bayes_mi (BayesGaussMI, MI): a Gibbs
         sampler of a multivariate normal, its mean, covariance and the
         missing values drawn in turn; after a burn-in an imputation every
         skip + 1 cycles.

Pooling (MICE.combine, MI._combine): the estimate is the mean of the m
estimates, the within variance W the mean of their variances, the between
variance B their variance, the total T = W + (1 + 1/m) B, and statsmodels'
fraction of missing information (1 + 1/m) B / T; the tests and intervals
are normal (z).

The columns go to statsmodels under plain names v0, v1, ... (MICEData
writes its imputation models as patsy formulas from the column names). A
categorical column is its level codes 0, 1, ... in the page's order:
predictive mean matching draws observed values, so the codes stay codes,
which serves a two-level or an ordinal column; a nominal column with more
levels and missing values is refused (MICE here has no multinomial model),
and when complete it enters the other columns' imputation models as C().
The multivariate normal imputes numbers: it takes continuous columns with
missing values, and complete categorical ones as 0/1 indicators.

statsmodels 0.14.6's BayesGaussMI has fixed priors, a N(0, I) prior for
the mean and an inverse Wishart with scale I and one degree of freedom for
the covariance: right for data of unit scale only. For a column in large
units the prior pulls the mean to zero (the imputed values of a column
whose mean is 50000 come out near 0; resources/tests/smui/test_mi.py shows
it). The page gives it every column standardized (the observed mean
subtracted, divided by the observed standard deviation) and turns the
imputations back; the Python shown does the same.

The analysis model is written as JMP writes it: nominal and ordinal
effects effect coded (the last level the negative sum of the others),
continuous columns centred in crossings and powers at the mean of their
observed values, the same for every imputation and for the complete-case
fit that the report sets beside the pooled one.
"""
import hashlib
import json
import math
import time

import numpy as np
import pandas as pd
import patsy
import statsmodels.api as sm
from scipy import stats

from . import data, models
from .registry import api
from .util import code_head, col
from .util import table as rtable

J = json.dumps
METHODS = ('mice', 'bayes')
KINDS = ('ols', 'logit', 'probit', 'poisson')
KIND_LABEL = {'ols': 'Least Squares', 'logit': 'Logistic (logit)', 'probit': 'Probit', 'poisson': 'Poisson (log)'}
DEFAULTS = {'mice': (10, 3), 'bayes': (100, 10)}   # burn-in cycles, cycles skipped between imputations: statsmodels' own
MAX_LEVELS = 30   # a categorical column with more is a label, not a predictor


class UserError(ValueError):
    """A problem with the roles or the data, said in words for the report."""


def _rows_sig(rows):
    if rows is None:
        return 'all'
    a = np.asarray(rows, dtype=np.int64)
    return f'{len(a)}:{hashlib.blake2b(a.tobytes(), digest_size=10).hexdigest()}'


def _num(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return int(f) if f.is_integer() and abs(f) < 1e15 else f
    return v


def _text(v):
    v = _num(v)
    return f'{v:.6g}' if isinstance(v, float) else str(v)


def _g(x):
    return f'{float(x):.6g}'


def _family(kind):
    if kind == 'logit':
        return sm.families.Binomial()
    if kind == 'probit':
        return sm.families.Binomial(link=sm.families.links.Probit())
    if kind == 'poisson':
        return sm.families.Poisson()
    return None


def _family_code(kind):
    return {'logit': 'sm.families.Binomial()', 'probit': 'sm.families.Binomial(link=sm.families.links.Probit())',
            'poisson': 'sm.families.Poisson()'}.get(kind)


# ---- the frame ------------------------------------------------------------------------------------------

def _columns(table, columns, response, effects):
    """Every column the imputation uses, in order: the columns to impute,
    then the response and the effects' columns."""
    effects = [list(e) for e in (effects or []) if e]
    used = list(dict.fromkeys([c for c in columns or [] if c] + ([response] if response else []) + [n for e in effects for n in e]))
    return used, effects


def _frame(table, used, rows, method):
    idx = np.arange(data.TABLES[table]['n']) if rows is None else np.asarray(rows, dtype=int)
    info = {'alias': {}, 'name': {}, 'cat': {}, 'levels': {}, 'ordinal': {}}
    cols = {}
    for j, c in enumerate(used):
        a = f'v{j}'
        info['alias'][c] = a
        info['name'][a] = c
        m = data.meta(table, c)
        if data.is_categorical(table, c):
            s = data.series(table, c, idx, as_category=True).cat.remove_unused_categories()   # levels these rows have
            lv = list(s.cat.categories)
            codes = s.cat.codes.to_numpy().astype(float)
            codes[codes < 0] = np.nan
            cols[a] = codes
            if len(lv) > MAX_LEVELS:
                raise UserError(f'{c} has {len(lv)} levels: too many to impute or to impute from (at most {MAX_LEVELS}); take it out, or make it continuous.')
            info['cat'][c] = True
            info['levels'][c] = lv
            info['ordinal'][c] = m.get('modelingType') == 'ordinal'
        else:
            if m.get('dataType') != 'numeric':
                raise UserError(f'{c} is a character column: make it nominal or ordinal (right click it in the dialog).')
            cols[a] = data.series(table, c, idx, as_category=False).to_numpy(float)
            info['cat'][c] = False
    d = pd.DataFrame(cols, index=idx)
    info['missing'] = _missing_report(used, d)
    empty = d.isna().all(axis=1).to_numpy()
    info['n_rows'] = len(d)
    info['dropped'] = [int(r) for r in idx[empty]]
    d = d[~empty]
    if len(d) < 5:
        raise UserError(f'{len(d)} row{"s" if len(d) != 1 else ""} with a value: too few to impute.')
    for c in used:
        a = info['alias'][c]
        miss = int(d[a].isna().sum())
        if miss == len(d):
            raise UserError(f'{c} has no values in these rows.')
        if info['cat'][c] and miss:
            k = len(info['levels'][c])
            if method == 'bayes':
                raise UserError(f'{c} is categorical and has missing values: the multivariate normal (Bayesian Gaussian) imputes numbers, not levels. Use MICE, which draws observed values.')
            if k > 2 and not info['ordinal'][c]:
                raise UserError(f'{c} is nominal with {k} levels and has missing values: statsmodels\' MICE imputes by least squares and predictive mean matching, which takes a numeric, two-level or ordinal column (R\'s mice would fit a multinomial model).')
    return d, info


# ---- the analysis model -----------------------------------------------------------------------------

def _analysis(response, effects, kind, d, info):
    """The formula over v0, v1, ... with JMP's coding, and a label for every
    column of its design."""
    labels = {'Intercept': 'Intercept'}
    order = ['Intercept']
    terms = []
    means = {}
    for c in dict.fromkeys(n for e in effects for n in e):
        if not info['cat'][c]:
            means[c] = float(np.nanmean(d[info['alias'][c]].to_numpy(float)))
    for e in effects:
        counts = {}
        for n in e:
            counts[n] = counts.get(n, 0) + 1
        if len(e) == 1:
            n = e[0]
            a = info['alias'][n]
            if info['cat'][n]:
                lv = info['levels'][n]
                code = f'C({a}, Sum, levels={[float(j) for j in range(len(lv))]!r})'
                base = patsy.EvalFactor(code).name()
                terms.append(code)
                for j in range(len(lv) - 1):
                    nm = f'{base}[S.{float(j)!r}]'
                    labels[nm] = f'{n}[{_text(lv[j])}]'
                    order.append(nm)
            else:
                terms.append(a)
                labels[a] = n
                order.append(a)
            continue
        parts = []   # per factor: [(expression, label), ...]
        for n, k in counts.items():
            a = info['alias'][n]
            if info['cat'][n]:
                lv = info['levels'][n]
                last = float(len(lv) - 1)
                parts.append([(f'(({a} == {float(j)!r}) * 1.0 - ({a} == {last!r}) * 1.0)', f'{n}[{_text(lv[j])}]') for j in range(len(lv) - 1)])
            else:
                mu = means[n]
                expr = f'({a} - {mu!r})' if k == 1 else f'({a} - {mu!r}) ** {k}'
                parts.append([(expr, '*'.join([f'({n}-{_g(mu)})'] * k))])
        combos = [[]]
        for p in parts:
            combos = [cmb + [x] for cmb in combos for x in p]
        for cmb in combos:
            code = 'I(' + ' * '.join(x[0] for x in cmb) + ')'
            nm = patsy.EvalFactor(code).name()
            terms.append(code)
            labels[nm] = '*'.join(x[1] for x in cmb)
            order.append(nm)
    rhs = ' + '.join(terms) if terms else '1'
    y = info['alias'][response]
    columns = list(dict.fromkeys([response] + [n for e in effects for n in e]))
    return {'formula': f'{y} ~ {rhs}', 'labels': labels, 'order': order, 'means': means, 'kind': kind,
            'columns': columns, 'aliases': [info['alias'][c] for c in columns]}


def _model_class(kind):
    fam = _family(kind)
    return (sm.OLS, {}) if fam is None else (sm.GLM, {'family': fam})


# ---- the imputers, with a trace ---------------------------------------------------------------------

class _Trace:
    """Called after every cycle of an imputer: the mean of each column's
    imputed values, and the completed values at the cycles an imputation
    is taken (after the burn-in, every skip + 1 cycles), with a line of
    progress to stdout for the page."""

    def __init__(self, cols, miss, burnin, skip, m, back=None):
        self.cols, self.miss, self.burnin, self.step, self.m = cols, miss, burnin, skip + 1, m
        self.total = burnin + m * (skip + 1)
        self.cycle = 0
        self.means = {c: [] for c in cols}
        self.draws = {c: [] for c in cols}
        self.back = back or (lambda c, v: v)
        self._next = 0.1

    def __call__(self, values):
        """values(c) -> the column's current values (all rows)."""
        self.cycle += 1
        take = self.cycle > self.burnin and (self.cycle - self.burnin) % self.step == 0
        for c in self.cols:
            v = self.back(c, np.asarray(values(c), dtype=float)[self.miss[c]])
            self.means[c].append(float(np.mean(v)))
            if take:
                self.draws[c].append(v.copy())
        if self.total >= 20 and self.cycle >= self._next * self.total:
            print(f'smui:progress mi {self.cycle} {self.total}', flush=True)
            self._next += 0.1


def _mice_classes():
    from statsmodels.imputation.mice import MICEData

    class TracedMICEData(MICEData):
        """MICEData that cycles one at a time, so that its history callback
        sees every cycle; the draws are MICEData's own."""

        def update_all(self, n_iter=1):
            for _ in range(n_iter):
                super().update_all(1)
    return TracedMICEData


def _bayes_classes():
    from statsmodels.imputation.bayes_mi import BayesGaussMI

    class TracedBayes(BayesGaussMI):
        trace = None

        def update(self):
            super().update()
            if self.trace is not None:
                self.trace(lambda j: self._data[:, j])
    return TracedBayes


def _imputation_formulas(used, info, d):
    """MICEData's default imputation model for a column is the main effects
    of all the others; a categorical predictor with more than two levels
    goes in as C() (its codes are not a scale)."""
    out = {}
    for c in used:
        a = info['alias'][c]
        if not d[a].isna().any():
            continue
        others = [x for x in used if x != c]
        if not any(info['cat'][x] and len(info['levels'][x]) > 2 for x in others):
            continue
        out[a] = ' + '.join(f'C({info["alias"][x]})' if info['cat'][x] and len(info['levels'][x]) > 2 else info['alias'][x] for x in others)
    return out


def _bayes_matrix(used, info, d):
    """The matrix the multivariate normal is fitted to: continuous columns,
    and complete categorical ones as 0/1 indicators (the first level the
    reference); the caller standardizes them."""
    parts, names = [], []
    for c in used:
        a = info['alias'][c]
        if info['cat'][c]:
            lv = info['levels'][c]
            for j in range(1, len(lv)):
                parts.append((d[a].to_numpy(float) == j).astype(float))
                names.append(f'{a}_{j}')
        else:
            parts.append(d[a].to_numpy(float))
            names.append(a)
    X = pd.DataFrame(np.column_stack(parts), columns=names, index=d.index)
    mean = X.mean()
    sd = X.std().replace(0, 1.0)
    return X, mean, sd


# ---- the analysis ---------------------------------------------------------------------------------------

def _pool_rows(res, labels, order, per, m, alpha, n, k_params):
    """The pooled table: statsmodels' estimate, standard error, z, p,
    interval and fraction of missing information, with the within, between
    and total variances by Rubin's formulas, the relative increase in
    variance, the Barnard-Rubin degrees of freedom (the complete-data
    degrees of freedom n - p) and R mice's fraction of missing information
    beside it."""
    names = list(getattr(res, 'exog_names', None) or res.model.exog_names)   # MICEResults keeps them itself
    P = np.asarray([p for p, _ in per])
    W = np.mean([np.diag(c) for _, c in per], axis=0)
    B = np.var(P, axis=0, ddof=1)
    T = W + (1 + 1 / m) * B
    ci = np.asarray(res.conf_int(alpha))
    fmi = np.asarray(res.frac_miss_info if hasattr(res, 'frac_miss_info') else res.fmi)   # MICEResults, MIResults
    dfcom = max(1, n - k_params)
    rows = []
    for j, nm in enumerate(names):
        riv = (1 + 1 / m) * B[j] / W[j] if W[j] > 0 else float('inf')
        lam = (1 + 1 / m) * B[j] / T[j] if T[j] > 0 else 0.0
        dfold = (m - 1) / lam ** 2 if lam > 0 else float('inf')
        dfobs = (dfcom + 1) / (dfcom + 3) * dfcom * (1 - lam)
        dfbr = dfold * dfobs / (dfold + dfobs) if math.isfinite(dfold) else dfobs
        tstat = float(res.params[j]) / float(res.bse[j]) if res.bse[j] > 0 else float('nan')
        rows.append({'term': labels.get(nm, nm), 'name': nm, 'estimate': float(res.params[j]), 'se': float(res.bse[j]), 'z': float(res.tvalues[j]),
                     'p': float(res.pvalues[j]), 'lower': float(ci[j, 0]), 'upper': float(ci[j, 1]), 'fmi': float(fmi[j]),
                     'w': float(W[j]), 'b': float(B[j]), 't': float(T[j]), 'riv': float(riv), 'df': float(dfbr),
                     'p_t': float(2 * stats.t.sf(abs(tstat), dfbr)) if math.isfinite(tstat) else None,
                     'fmi_mice': float((riv + 2 / (dfbr + 3)) / (riv + 1)) if math.isfinite(riv) else 1.0})
    rank = {nm: i for i, nm in enumerate(order)}
    rows.sort(key=lambda r: rank.get(r['name'], len(order)))
    lv = f'{100 * (1 - alpha):g}%'
    return rtable([col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('z', 'z Ratio'), col('p', 'Prob>|z|', 'p'),
                   col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}'), col('fmi', 'FMI'),
                   col('w', 'Within Var', hidden=True), col('b', 'Between Var', hidden=True), col('t', 'Total Var', hidden=True),
                   col('riv', 'RIV', hidden=True), col('df', 'DF', hidden=True), col('p_t', 'Prob>|t|', 'p', hidden=True),
                   col('fmi_mice', 'FMI (mice)', hidden=True)], rows)


def _cc_rows(res, labels, order, alpha):
    ci = np.asarray(res.conf_int(alpha))
    names = list(res.model.exog_names)
    use_t = bool(getattr(res, 'use_t', False))
    rows = [{'term': labels.get(nm, nm), 'name': nm, 'estimate': float(res.params.iloc[j]), 'se': float(res.bse.iloc[j]), 't': float(res.tvalues.iloc[j]),
             'p': float(res.pvalues.iloc[j]), 'lower': float(ci[j, 0]), 'upper': float(ci[j, 1])} for j, nm in enumerate(names)]
    rank = {nm: i for i, nm in enumerate(order)}
    rows.sort(key=lambda r: rank.get(r['name'], len(order)))
    lv = f'{100 * (1 - alpha):g}%'
    stat, pl = ('t Ratio', 'Prob>|t|') if use_t else ('z Ratio', 'Prob>|z|')
    return rtable([col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('t', stat), col('p', pl, 'p'),
                   col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}')], rows)


def _missing_report(used, d):
    M = d.isna().to_numpy()
    n = len(d)
    per = M.sum(axis=0)
    cols = [{'column': c, 'n_missing': int(per[j]), 'pct': 100.0 * per[j] / n if n else None} for j, c in enumerate(used)]
    pats = [''.join('1' if b else '0' for b in r) for r in M]
    counts = pd.Series(pats, dtype=object).value_counts()
    keys = sorted(counts.index.tolist(), key=lambda k: (k.count('1'), k))
    patterns = [{'pattern': k, 'count': int(counts[k]), 'n_missing': k.count('1'), 'columns': [c for c, b in zip(used, k) if b == '1']} for k in keys]
    return {'columns': cols, 'patterns': patterns, 'n': n, 'rows_with_missing': int(M.any(axis=1).sum()), 'cells_missing': int(M.sum()),
            'complete': int((~M.any(axis=1)).sum())}


@api('mi.fit')
def fit(table, columns, rows=None, response=None, effects=None, model=None, method='mice', m=20, burnin=None, skip=None, seed=1,
        alpha=0.05, table_name='data'):
    method = method if method in METHODS else 'mice'
    try:
        used, effects = _columns(table, columns, response, effects)
        if len(used) < 2:
            raise UserError('Multiple imputation needs two columns or more: each column is imputed from the others.')
        if response and any(response in e for e in effects):
            raise UserError(f'{response} is the analysis model\'s response: take it out of the effects.')
        d, info = _frame(table, used, rows, method)
        kind = None
        if response:
            kind = model or ('logit' if info['cat'][response] else 'ols')
            if kind not in KINDS:
                raise UserError(f'no analysis model {kind!r}')
            ya = info['alias'][response]
            yv = d[ya].to_numpy(float)
            yv = yv[np.isfinite(yv)]
            if info['cat'][response]:
                if len(info['levels'][response]) != 2 or kind in ('ols', 'poisson'):
                    raise UserError(f'{response} is categorical: the analysis model takes it with two levels, as a logistic or probit model.')
            elif kind in ('logit', 'probit') and not np.all((yv == 0) | (yv == 1)):
                raise UserError(f'{response} takes a logistic or probit model only when it is 0 or 1 (or a column with two levels).')
            elif kind == 'poisson' and (np.any(yv < 0) or np.any(yv != np.round(yv))):
                raise UserError(f'{response} takes a Poisson model only when it holds counts, whole numbers of zero or more.')
    except UserError as e:
        return {'error': str(e)}
    m = int(m or 20)
    if not 2 <= m <= 200:
        return {'error': 'The number of imputations must be between 2 and 200.'}
    b0, s0 = DEFAULTS[method]
    burnin = int(b0 if burnin is None else burnin)
    skip = int(s0 if skip is None else skip)
    if burnin < 0 or skip < 0 or burnin + m * (skip + 1) > 20000:
        return {'error': 'Burn-in and the cycles between imputations must be zero or more, and all the cycles together at most 20000.'}
    seed = int(seed if seed is not None else 1) % (2 ** 32)
    A = _analysis(response, effects, kind, d, info) if response else None
    miss_cols = [c for c in used if d[info['alias'][c]].isna().any()]
    key = models.model_key('mi', table, data.version(table), _rows_sig(rows), used, response, effects, kind, method, m, burnin, skip, seed)
    hit = models.recall(key)
    cached = hit is not None
    if hit is None:
        t0 = time.time()
        try:
            hit = _run(d, info, used, miss_cols, A, method, m, burnin, skip, seed)
        except (np.linalg.LinAlgError, ValueError, OverflowError, FloatingPointError, ZeroDivisionError, patsy.PatsyError) as e:
            return {'error': f'The imputation failed: {e}'}
        hit['seconds'] = time.time() - t0
        models.remember(key, hit, keep=24)
    out = {'columns': used, 'response': response, 'model': kind, 'method': method, 'm': m, 'burnin': burnin, 'skip': skip, 'seed': seed,
           'alpha': alpha, 'cached': cached, 'seconds': hit['seconds'], 'n': len(d), 'n_rows': info['n_rows'], 'dropped': info['dropped'],
           'missing': info['missing'],
           'rows': [int(r) for r in d.index],
           'kinds': {c: ('categorical' if info['cat'][c] else 'continuous') for c in used},
           'levels': {c: [_num(v) for v in info['levels'][c]] for c in used if info['cat'][c]},
           'observed_mean': {c: float(np.nanmean(d[info['alias'][c]].to_numpy(float))) for c in used},
           'imputed': [{'column': c, 'rows': [int(r) for r in d.index[d[info['alias'][c]].isna().to_numpy()]], 'draws': hit['trace'].draws[c]} for c in miss_cols],
           'trace': {'cycles': hit['trace'].cycle, 'burnin': burnin, 'step': skip + 1, 'means': hit['trace'].means}}
    notes = []
    if not miss_cols:
        notes.append('No missing values in these columns and rows: every imputation is the data itself, and the pooled fit is the complete-data fit (FMI 0).')
    if info['dropped']:
        notes.append(f'{len(info["dropped"])} row{"s have" if len(info["dropped"]) != 1 else " has"} no value in any of the columns and '
                     f'{"are" if len(info["dropped"]) != 1 else "is"} left out (MICEData drops such rows).')
    if A:
        res = hit['pooled']
        k_params = len(res.params)
        out['analysis'] = {
            'formula': A['formula'], 'kind': kind, 'label': KIND_LABEL[kind],
            'response_label': f'{response}[{_text(info["levels"][response][1])}]' if info['cat'][response] else response,
            'pooled': _pool_rows(res, A['labels'], A['order'], hit['per'], m, alpha, len(d), k_params),
        }
        cc = hit['cc']
        if cc is not None:
            out['analysis']['cc'] = _cc_rows(cc, A['labels'], A['order'], alpha)
            out['analysis']['n_cc'] = int(cc.nobs)
        else:
            out['analysis']['cc'] = None
            out['analysis']['n_cc'] = int(hit.get('n_cc', 0))
            notes.append(hit.get('cc_error') or 'The complete-case fit failed.')
    out['notes'] = notes
    out['code'] = _code(table, table_name, rows, used, info, d, A, method, m, burnin, skip, seed, alpha)
    return out


def _run(d, info, used, miss_cols, A, method, m, burnin, skip, seed):
    """Impute (and fit and pool); the numbers are the same as those of the
    plain statsmodels calls the code shows."""
    miss = {c: d[info['alias'][c]].isna().to_numpy() for c in used}
    out = {}
    if method == 'mice':
        from statsmodels.imputation.mice import MICE
        Traced = _mice_classes()
        dd = d.reset_index(drop=True)
        trace = _Trace(miss_cols, miss, burnin, skip, m)
        np.random.seed(seed)
        imp = Traced(dd, history_callback=lambda x: trace(lambda c: x.data[info['alias'][c]].to_numpy()))
        for a, f in _imputation_formulas(used, info, dd).items():
            imp.set_imputer(a, formula=f)
        if A:
            klass, kw = _model_class(A['kind'])
            mice = MICE(A['formula'], klass, imp, n_skip=skip, init_kwds=kw)
            res = mice.fit(n_burnin=burnin, n_imputations=m)
            out['pooled'] = res
            out['per'] = [(np.asarray(r.params, dtype=float), np.asarray(r.cov_params(), dtype=float)) for r in mice.results_list]
        else:
            imp.update_all(burnin)
            for _ in range(m):
                imp.update_all(skip + 1)
    else:
        from statsmodels.imputation.bayes_mi import MI
        Traced = _bayes_classes()
        X, mean, sd = _bayes_matrix(used, info, d)
        Z = (X - mean) / sd
        pos = {c: list(X.columns).index(info['alias'][c]) for c in miss_cols}
        trace = _Trace(miss_cols, miss, burnin, skip, m,
                       back=lambda c, v: v * sd[info['alias'][c]] + mean[info['alias'][c]])
        np.random.seed(seed)
        imp = Traced(Z.reset_index(drop=True))
        imp.trace = lambda get: trace(lambda c: get(pos[c]))
        if A:
            klass, kw = _model_class(A['kind'])
            complete = _completer(info, used, d, X.columns, mean, sd)
            mi = MI(imp, klass, formula=A['formula'], model_args_fn=lambda f: [f], model_kwds_fn=lambda f: dict(kw), xfunc=complete,
                    burn=burnin, nrep=m, skip=skip)
            res = mi.fit(results_cb=lambda r: (np.asarray(r.params, dtype=float), np.asarray(r.cov_params(), dtype=float)))
            out['pooled'] = res
            out['per'] = res.results
        else:
            for _ in range(burnin + m * (skip + 1)):
                imp.update()
    out['trace'] = trace
    if A:
        klass, kw = _model_class(A['kind'])
        dcc = d[A['aliases']].dropna()
        out['n_cc'] = len(dcc)
        try:
            out['cc'] = klass.from_formula(A['formula'], d.loc[dcc.index], **kw).fit()
        except Exception as e:   # noqa: BLE001 - said in the report
            out['cc'] = None
            out['cc_error'] = f'The complete-case fit failed: {e}'
    return out


def _completer(info, used, d, xcols, mean, sd):
    """xfunc for MI: the standardized draws back in the table's units, with
    the categorical columns' codes (complete) beside them."""
    codes = {info['alias'][c]: d[info['alias'][c]].to_numpy(float) for c in used if info['cat'][c]}
    cont = [info['alias'][c] for c in used if not info['cat'][c]]
    order = [info['alias'][c] for c in used]

    def complete(z):
        z = pd.DataFrame(np.asarray(z), columns=list(xcols))
        f = {}
        for a in order:
            f[a] = z[a].to_numpy() * sd[a] + mean[a] if a in cont else codes[a]
        return pd.DataFrame(f)
    return complete


# ---- the code shown -------------------------------------------------------------------------------------

def _code(table, table_name, rows, used, info, d, A, method, m, burnin, skip, seed, alpha):
    lines = _prep_lines(table, table_name, rows, used, info, d, method, seed)
    if A:
        lines += _model_lines(A, info, used, method, m, burnin, skip)
        lines.append(f'print(res.summary(alpha={alpha!r}))')
        lines.append(_cc_code(A, info, alpha))
    elif method == 'mice':
        lines.append(f'imp.update_all({burnin})   # the burn-in')
        lines.append('imputations = []')
        lines.append(f'for j in range({m}):')
        lines.append(f'    imp.update_all({skip + 1})   # the cycles between imputations, as MICE.fit spaces them (n_skip + 1)')
        lines.append('    imputations.append(imp.data.copy())')
        lines.append('print(imputations[0].describe())')
    else:
        lines.append(f'for k in range({burnin}):   # the burn-in')
        lines.append('    imp.update()')
        lines.append('imputations = []')
        lines.append(f'for j in range({m}):')
        lines.append(f'    for k in range({skip + 1}):   # the cycles between imputations, as MI.fit spaces them (skip + 1)')
        lines.append('        imp.update()')
        lines.append('    imputations.append(imp.data * sd + mean)')
        lines.append('print(imputations[0].describe())')
    return '\n'.join(lines)


def _prep_lines(table, table_name, rows, used, info, d, method, seed, extra_imports=()):
    """The code that reads the table, keeps the report's rows, gives the
    columns plain names (a categorical one its level codes) and sets up the
    imputer with the report's seed: up to imp = MICEData(...) or
    BayesGaussMI(...) (the normal's columns standardized)."""
    lines = [code_head(table_name, [*extra_imports, 'from statsmodels.imputation.mice import MICEData, MICE' if method == 'mice'
                                    else 'from statsmodels.imputation.bayes_mi import BayesGaussMI, MI'])]
    if rows is not None:
        n_all = data.TABLES[table]['n']
        keep = sorted(int(r) for r in rows)
        if len(keep) > n_all / 2:
            drop = sorted(set(range(n_all)) - set(keep))
            if drop:
                lines.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
        else:
            lines.append(f'df = df.loc[{keep}]   # the rows of the report')
    lines.append(f'cols = {J(used)}')
    lines.append('d = pd.DataFrame({f"v{j}": df[c] for j, c in enumerate(cols)})   # plain names for patsy: ' +
                 ', '.join(f'{info["alias"][c]} = {c}' for c in used))
    for c in used:
        if info['cat'][c]:
            a = info['alias'][c]
            lv = [_num(v) for v in info['levels'][c]]
            src = f'df[{J(c)}].astype(str)' if any(isinstance(v, str) for v in lv) else f'df[{J(c)}]'
            cats = [str(v) for v in lv] if any(isinstance(v, str) for v in lv) else lv
            lines.append(f'd[{J(a)}] = pd.Series(pd.Categorical({src}, categories={cats!r}).codes, index=df.index).replace(-1, np.nan).astype(float)   # {c}: the codes of its levels')
    if info['dropped']:
        lines.append('d = d.dropna(how="all")   # rows with no value in any column')
    if method == 'mice':
        lines.append(f'np.random.seed({seed})   # statsmodels draws from numpy\'s global generator')
        lines.append('imp = MICEData(d.reset_index(drop=True))')
        for a, f in _imputation_formulas(used, info, d.reset_index(drop=True)).items():
            lines.append(f'imp.set_imputer({J(a)}, formula={J(f)})   # a categorical predictor as C()')
        return lines
    cat_cols = [c for c in used if info['cat'][c]]
    if not cat_cols:
        lines.append('X = d.copy()')
    else:
        lines.append('X = pd.DataFrame(index=d.index)   # the columns the normal is fitted to, a categorical one as indicators')
        for c in used:
            a = info['alias'][c]
            if info['cat'][c]:
                for j in range(1, len(info['levels'][c])):
                    lines.append(f'X[{J(f"{a}_{j}")}] = (d[{J(a)}] == {j}).astype(float)   # {c} = {_text(info["levels"][c][j])}')
            else:
                lines.append(f'X[{J(a)}] = d[{J(a)}]')
    lines.append('mean, sd = X.mean(), X.std().replace(0, 1.0)')
    lines.append('Z = (X - mean) / sd   # standardized: BayesGaussMI\'s priors (the mean N(0, I), the covariance inverse Wishart(I, 1)) suit data on the unit scale')
    lines.append(f'np.random.seed({seed})   # statsmodels draws from numpy\'s global generator')
    lines.append('imp = BayesGaussMI(Z.reset_index(drop=True))')
    return lines


def _model_lines(A, info, used, method, m, burnin, skip):
    """The analysis model fitted to every imputation and pooled, as the report does: res."""
    lines = []
    if method == 'mice':
        klass = 'sm.OLS' if A['kind'] == 'ols' else 'sm.GLM'
        kw = '' if A['kind'] == 'ols' else f', init_kwds={{"family": {_family_code(A["kind"])}}}'
        lines.append(f'mice = MICE({J(A["formula"])}, {klass}, imp, n_skip={skip}{kw})')
        lines.append(f'res = mice.fit(n_burnin={burnin}, n_imputations={m})   # pooled by Rubin\'s rules')
        return lines
    cat_cols = [c for c in used if info['cat'][c]]
    cont = [info['alias'][c] for c in used if not info['cat'][c]]
    lines.append('def complete(z):   # the imputed table in its own units' + (', the categorical codes beside it' if cat_cols else ''))
    lines.append('    z = pd.DataFrame(np.asarray(z), columns=X.columns)')
    lines.append(f'    f = pd.DataFrame({{a: z[a] * sd[a] + mean[a] for a in {cont!r}}})')
    for c in cat_cols:
        a = info['alias'][c]
        lines.append(f'    f[{J(a)}] = d[{J(a)}].to_numpy()')
    lines.append('    return f')
    kw = '' if A['kind'] == 'ols' else f', model_kwds_fn=lambda f: {{"family": {_family_code(A["kind"])}}}'
    klass = 'sm.OLS' if A['kind'] == 'ols' else 'sm.GLM'
    lines.append(f'mi = MI(imp, {klass}, formula={J(A["formula"])}, model_args_fn=lambda f: [f]{kw}, xfunc=complete, burn={burnin}, nrep={m}, skip={skip})')
    lines.append('res = mi.fit()   # pooled by Rubin\'s rules')
    return lines


def _cc_code(A, info, alpha):
    fam = '' if A['kind'] == 'ols' else f', family={_family_code(A["kind"])}'
    fn = 'smf.ols' if A['kind'] == 'ols' else 'smf.glm'
    return (f'cc = {fn}({J(A["formula"])}, data=d.dropna(subset={J(A["aliases"])}){fam}).fit()   # the complete cases, for contrast\n'
            f'print(cc.summary(alpha={alpha!r}))')


# ---- the graphs as matplotlib code ----------------------------------------------------------------
# Under each graph the report shows Python that draws it with matplotlib from
# a CSV export of the table (the notebook runs it): the report's rows, the
# imputer set up as the report's code sets it up (the same seed: the same
# draws), the light theme's colours, the graph's size at 100 pixels an inch.
# The diagnostics run the imputer one cycle at a time (the same draws as
# MICE.fit and MI.fit make: fitting the analysis model draws nothing) and
# keep what the graph shows. The page sends what it chose (the bins, the
# level names); mi.plot_code writes the code of one graph.
OBS, IMP, TEXT, MUTED, SURFACE = '#2e6fba', '#b8406e', '#352921', '#786b5d', '#fcf7f2'
PX = 0.72   # points per pixel: a figure at 100 pixels an inch


def _pt(px):
    return f'{px * PX:.3g}'


def _cycle_lines(info, used, d, column, method, m, burnin, skip, keep_means):
    """The imputer run one cycle at a time: after each, the column's imputed
    values; at the cycles MICE.fit and MI.fit take (after the burn-in, every
    skip + 1 cycles) an imputation of them."""
    a = info['alias'][column]
    c = [f'a = {J(a)}   # {column}',
         f'burnin, step, m = {burnin}, {skip + 1}, {m}   # the burn-in, an imputation every skip + 1 cycles, m of them']
    if method == 'mice':
        c += ['miss = d[a].isna().to_numpy()   # the rows whose value is imputed',
              'means, draws = [], []',
              'for cycle in range(1, burnin + m * step + 1):',
              '    imp.update_all(1)   # one cycle of the chained equations',
              '    v = imp.data[a].to_numpy()[miss]']
    else:
        c += ['miss = X[a].isna().to_numpy()   # the rows whose value is imputed',
              'j = list(X.columns).index(a)',
              'means, draws = [], []',
              'for cycle in range(1, burnin + m * step + 1):',
              '    imp.update()   # one cycle of the Gibbs sampler',
              '    v = np.asarray(imp.data)[miss, j] * sd[a] + mean[a]   # back in the column\'s units (imp.data is a DataFrame after an update)']
    if keep_means:
        c.append('    means.append(v.mean())')
    c += ['    if cycle > burnin and (cycle - burnin) % step == 0:',
          '        draws.append(v.copy())']
    return c


def _observed_code(head, info, used, d, column, method, m, burnin, skip, plot):
    b = plot.get('bins') or {'start': 0.0, 'end': 1.0, 'size': 1.0}
    start, end, size = float(b['start']), float(b['end']), float(b['size'])
    nb = max(1, int(round((end - start) / size)))
    c = head + _cycle_lines(info, used, d, column, method, m, burnin, skip, False)
    c += ['obs = d[a].to_numpy()[~miss]   # the observed values', 'drawn = np.concatenate(draws)   # the imputed ones, every imputation',
          f'start, end, size, nb = {start!r}, {end!r}, {size!r}, {nb}   # the page\'s bins',
          'bin_of = lambda v: np.clip(np.floor((v - start) / size + 1e-9), 0, nb - 1).astype(int)',
          'mids = start + (np.arange(nb) + 0.5) * size',
          'fig, ax = plt.subplots(figsize=(4.0, 2.7), layout="constrained")',
          f'for v, name, color in ((obs, "Observed", "{OBS}"), (drawn, "Imputed", "{IMP}")):   # as densities: the counts over n times the bin width',
          f'    ax.bar(mids, np.bincount(bin_of(v), minlength=nb) / (max(1, len(v)) * size), width=size, color=color, alpha=0.55, edgecolor="{SURFACE}", linewidth={_pt(1)}, label=f"{{name}} ({{len(v)}})")',
          'ax.set_xlim(start, end); ax.set_ylim(bottom=0)',
          f'ax.set_xlabel({J(column)})', 'ax.set_ylabel("Density")',
          f'fig.legend(loc="outside upper left", ncols=2, frameon=False, fontsize={_pt(11)})',
          f'ax.set_title({J(f"{column} observed and imputed")})', 'plt.show()']
    return '\n'.join(c)


def _levels_code(head, info, used, d, column, method, m, burnin, skip, plot):
    labels = [str(x) for x in (plot.get('labels') or [_text(v) for v in info['levels'][column]])]
    c = head + _cycle_lines(info, used, d, column, method, m, burnin, skip, False)
    c += [f'labels = {J(labels)}   # the levels, as the page names them', 'k = len(labels)',
          'obs = d[a].to_numpy()[~miss].astype(int)   # the observed levels\' codes',
          'drawn = np.round(np.concatenate(draws)).astype(int)   # the imputed codes, every imputation',
          'po, pi = np.bincount(obs, minlength=k)[:k] / max(1, len(obs)), np.bincount(drawn, minlength=k)[:k] / max(1, len(drawn))',
          'fig, ax = plt.subplots(figsize=(3.4, 2.7), layout="constrained")',
          f'ax.bar(np.arange(k) - 0.4, po, width=0.38, align="edge", color="{OBS}", edgecolor="{SURFACE}", linewidth={_pt(1)}, label=f"Observed ({{len(obs)}})")',
          f'ax.bar(np.arange(k) + 0.02, pi, width=0.38, align="edge", color="{IMP}", edgecolor="{SURFACE}", linewidth={_pt(1)}, label=f"Imputed ({{len(drawn)}})")',
          'ax.set_xticks(range(k), labels); ax.set_ylim(bottom=0)',
          f'ax.set_xlabel({J(column)})', 'ax.set_ylabel("Proportion")',
          f'fig.legend(loc="outside upper left", ncols=2, frameon=False, fontsize={_pt(11)})',
          f'ax.set_title({J(f"{column} observed and imputed levels")})', 'plt.show()']
    return '\n'.join(c)


def _trace_code(head, info, used, d, column, method, m, burnin, skip):
    cat = info['cat'][column]
    c = head + _cycle_lines(info, used, d, column, method, m, burnin, skip, True)
    c += ['x = np.arange(1, len(means) + 1)',
          'takes = burnin + step * np.arange(1, m + 1)   # the cycles whose values became the imputations',
          'om = np.nanmean(d[a].to_numpy())   # the observed mean' + (' (of the codes)' if cat else ''),
          'fig, ax = plt.subplots(figsize=(4.3, 2.7), layout="constrained")']
    if burnin > 0:
        c += [f'ax.axvspan(0.5, burnin + 0.5, color="{MUTED}", alpha=0.1, linewidth=0)   # the burn-in',
              f'ax.text(1, 1, "burn-in", transform=ax.get_xaxis_transform(), ha="left", va="top", fontsize={_pt(10)}, color="{MUTED}")']
    c += [f'ax.plot(x, means, color="{OBS}", linewidth={_pt(2)}, label="Mean of the imputed values")',
          f'ax.plot(takes, np.asarray(means)[takes - 1], linestyle="none", marker="o", markersize={_pt(8)}, color="{IMP}", mec="{SURFACE}", mew={_pt(2)}, label="An imputation")',
          f'ax.axhline(om, color="{MUTED}", linewidth={_pt(1.2)}, linestyle=":")',
          f'ax.text(1, om, f"observed mean {{om:.4g}}", transform=ax.get_yaxis_transform(), ha="right", va="bottom", fontsize={_pt(10)}, color="{MUTED}")',
          'ax.set_xlim(0.5, max(2, len(means)) + 0.5)',
          'ax.set_xlabel("Cycle")', f'ax.set_ylabel({J(f"Mean of imputed {column}" + (" (codes)" if cat else ""))})',
          f'fig.legend(loc="outside upper left", ncols=2, frameon=False, fontsize={_pt(11)})',
          f'ax.set_title({J(f"{column} trace")})', 'plt.show()']
    return '\n'.join(c)


def _compare_code(head, A, info, used, method, m, burnin, skip, alpha, cc_ok):
    terms = [(nm, A['labels'].get(nm, nm)) for nm in A['order']][:12]
    k = len(terms)
    fam = '' if A['kind'] == 'ols' else f', family={_family_code(A["kind"])}'
    fn = 'smf.ols' if A['kind'] == 'ols' else 'smf.glm'
    c = head + _model_lines(A, info, used, method, m, burnin, skip)
    c += [f'cc = {fn}({J(A["formula"])}, data=d.dropna(subset={J(A["aliases"])}){fam}).fit()   # the complete cases' if cc_ok else 'cc = None   # the complete-case fit failed',
          'names = list(getattr(res, "exog_names", None) or res.model.exog_names)',
          f'ci = np.asarray(res.conf_int({alpha!r}))',
          'pooled = {nm: (res.params[q], ci[q, 0], ci[q, 1]) for q, nm in enumerate(names)}']
    if cc_ok:
        c += [f'cci = np.asarray(cc.conf_int({alpha!r}))',
              'complete = {nm: (cc.params.iloc[q], cci[q, 0], cci[q, 1]) for q, nm in enumerate(cc.params.index)}']
    else:
        c.append('complete = {}')
    c += ['terms = [' + ', '.join(f'({J(nm)}, {J(lab)})' for nm, lab in terms) + ']   # the report\'s terms, in its order (at most twelve), and its names for them',
          f'fig, axs = plt.subplots(len(terms), 1, figsize=(5.2, {(64 + 56 * k) / 100:g}), layout="constrained", squeeze=False)',
          'for ax, (nm, label) in zip(axs[:, 0], terms):',
          f'    for fit, yv, name, color, marker in ((pooled, 1, "Pooled ({m} imputations)", "{OBS}", "o"), (complete, 0, "Complete cases", "{IMP}", "s")):',
          '        if nm in fit:',
          '            e, lo, hi = fit[nm]',
          f'            ax.errorbar([e], [yv], xerr=[[e - lo], [hi - e]], fmt=marker, color=color, ecolor=color, elinewidth={_pt(2)}, capsize={_pt(2)}, markersize={_pt(9)}, mec="{SURFACE}", mew={_pt(2)}, label=name)',
          '    ax.set_ylim(-0.7, 1.7); ax.set_yticks([])',
          f'    ax.set_ylabel(label, rotation=0, ha="right", va="center", fontsize={_pt(11)})',
          f'fig.legend(*axs[0, 0].get_legend_handles_labels(), loc="outside upper left", ncols=2, frameon=False, fontsize={_pt(11)})',
          'fig.suptitle("pooled and complete-case estimates")', 'plt.show()']
    return '\n'.join(c)


@api('mi.plot_code')
def plot_code(table, columns, kind='compare', plot=None, rows=None, response=None, effects=None, model=None, method='mice', m=20, burnin=None,
              skip=None, seed=1, alpha=0.05, table_name='data'):
    """The Python that draws one of the report's graphs with matplotlib (kind:
    compare, observed, levels, trace), the imputer and the analysis model as
    the report's code sets them up, from what the page chose (plot)."""
    method = method if method in METHODS else 'mice'
    plot = plot or {}
    try:
        used, effects = _columns(table, columns, response, effects)
        d, info = _frame(table, used, rows, method)
        kind_m = (model or ('logit' if info['cat'][response] else 'ols')) if response else None
    except UserError as e:
        return {'error': str(e)}
    m = int(m or 20)
    b0, s0 = DEFAULTS[method]
    burnin = int(b0 if burnin is None else burnin)
    skip = int(s0 if skip is None else skip)
    seed = int(seed if seed is not None else 1) % (2 ** 32)
    head = _prep_lines(table, table_name, rows, used, info, d, method, seed, ['import matplotlib.pyplot as plt'])
    if kind == 'compare':
        if not response:
            return {'error': 'no analysis model'}
        A = _analysis(response, effects, kind_m, d, info)
        return {'plot_code': _compare_code(head, A, info, used, method, m, burnin, skip, alpha, plot.get('cc', True) is not False)}
    column = plot.get('column')
    if column not in used:
        return {'error': f'{column!r} is not a column of the imputation'}
    if kind == 'observed':
        return {'plot_code': _observed_code(head, info, used, d, column, method, m, burnin, skip, plot)}
    if kind == 'levels':
        return {'plot_code': _levels_code(head, info, used, d, column, method, m, burnin, skip, plot)}
    if kind == 'trace':
        return {'plot_code': _trace_code(head, info, used, d, column, method, m, burnin, skip)}
    return {'error': f'no graph {kind!r}'}
