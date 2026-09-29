"""Analyze > Specialized Modeling > Mediation: causal mediation analysis by
statsmodels' Mediation (statsmodels.stats.mediation; Imai, Keele and
Tingley 2010, the algorithms of R's mediation package).

A treatment T may change an outcome Y directly, and through a mediator M
that T changes and that changes Y. Two models are fitted to the complete
rows, the mediator model M ~ T + covariates and the outcome model
Y ~ T + M (+ T x M) + covariates, each least squares or a generalized
linear model (binomial with a logit or probit link, Poisson with a log
link). Mediation then simulates: the models' parameters are drawn from
their approximate sampling distributions (the 'parametric', quasi-Bayesian
method) or refitted to bootstrap samples; for each draw the potential
mediators M(0) and M(1) are drawn from the mediator model and the
potential outcomes Y(t, M(t')) predicted by the outcome model, and
averaged over the rows:

  ACME(t) = E[Y(t, M(1)) - Y(t, M(0))]   the indirect (mediated) effect
  ADE(t)  = E[Y(1, M(t)) - Y(0, M(t))]   the direct effect
  total   = (ACME(0) + ACME(1) + ADE(0) + ADE(1)) / 2

with t = 0 the control and t = 1 the treated condition. The estimate is
the mean of the simulated values (the median for the proportion mediated,
ACME / total), the interval their percentiles, the p-value twice the share
of the simulated values on the far side of zero.

statsmodels sets the exposure to 0 and 1, so the treatment is recoded: 1
for the treated level and 0 for the control level of a two-level column;
(T - control value) / (treated value - control value) for a continuous
one (the same models, reparametrised). Three things in statsmodels 0.14.6
are handled here:

  * Mediation passes scale= to the mediator model's get_distribution
    whenever the mediator's results have a scale, and the results of
    every discrete model have one (1.0) while Logit's, Probit's and
    Poisson's get_distribution take none (a TypeError): the binary and
    count models are the GLM families, which take it (the same maximum
    likelihood fits);
  * its formula path builds both designs again with patsy for every
    simulation, some 25 times slower than its array path, and the array
    path does not update an interaction column: _Mediation below is the
    array path with T x M set from T and M, as the formula path computes
    it (resources/tests/smui/test_mediation.py checks that the two agree);
  * it keeps n x n_rep simulated effects of four kinds in memory: runs
    above ten million are refused.

The Python shown with the results uses the formula path, statsmodels'
documented way; with the same seed it gives the report's numbers.
"""
import hashlib
import json
import math
import re
import time

import numpy as np
import pandas as pd
import patsy
import statsmodels.api as sm
from statsmodels.stats.mediation import Mediation

from . import data, models
from .registry import api
from .util import code_head, col, q
from .util import table as rtable

J = json.dumps

KINDS = ('ols', 'logit', 'probit', 'poisson')
KIND_LABEL = {'ols': 'Least Squares', 'logit': 'Logistic (logit)', 'probit': 'Probit', 'poisson': 'Poisson (log)'}
METHODS = ('parametric', 'bootstrap')
MAX_WORK = 10_000_000          # rows x simulations
# what a fit to awkward data raises, said in the report rather than as a traceback
FIT_ERRORS = (np.linalg.LinAlgError, ValueError, OverflowError, FloatingPointError, ZeroDivisionError)
# statsmodels' summary() rows, in the order the report shows them
EFFECTS = [
    ('ACME (control)', 'ACME (control)', 'acme'), ('ACME (treated)', 'ACME (treated)', 'acme'), ('ACME (average)', 'ACME (average)', 'acme'),
    ('ADE (control)', 'ADE (control)', 'ade'), ('ADE (treated)', 'ADE (treated)', 'ade'), ('ADE (average)', 'ADE (average)', 'ade'),
    ('Total Effect', 'Total effect', 'total'),
    ('Prop. Mediated (control)', 'Prop. mediated (control)', 'prop'), ('Prop. Mediated (treated)', 'Prop. mediated (treated)', 'prop'),
    ('Prop. Mediated (average)', 'Prop. mediated (average)', 'prop'),
]


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
    """A level or a value as the page shows it: 1.0 as 1."""
    v = _num(v)
    if isinstance(v, float):
        return f'{v:.6g}'
    return str(v)


def _lit(v):
    """A Python literal for the code: numbers as numbers, text quoted."""
    v = _num(v)
    return J(v) if isinstance(v, str) else repr(v)


def _g(x):
    return f'{float(x):.6g}'


def _same(a, b):
    """Level equality across JSON: 1 and 1.0 are one level, '1' and 1 too."""
    if a is None or b is None:
        return False
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _alias(base, taken):
    a = base
    while a in taken:
        a += '_'
    return a


# ---- the models -------------------------------------------------------------------------

def _family(kind):
    if kind == 'logit':
        return sm.families.Binomial()
    if kind == 'probit':
        return sm.families.Binomial(link=sm.families.links.Probit())
    if kind == 'poisson':
        return sm.families.Poisson()
    return None


def _model(kind, y, X):
    fam = _family(kind)
    return sm.OLS(y, X) if fam is None else sm.GLM(y, X, family=fam)


def _family_code(kind):
    return {'logit': 'sm.families.Binomial()', 'probit': 'sm.families.Binomial(link=sm.families.links.Probit())',
            'poisson': 'sm.families.Poisson()'}.get(kind)


class _Mediation(Mediation):
    """statsmodels' Mediation on its array path, with the column of an
    interaction T x M in the outcome model set from the exposure and the
    mediator whenever those are set (the formula path gets it from patsy),
    and a line of progress to stdout, which the page shows while it runs."""

    def __init__(self, outcome_model, mediator_model, exposure, mediator, interaction=None, n_rep=0, method='parametric'):
        super().__init__(outcome_model, mediator_model, exposure, mediator)
        self._int_pos = interaction
        self._total = 2 * int(n_rep)
        self._done = 0
        self._next = 0.1
        self._method = method

    def _get_outcome_exog(self, exposure, mediator):
        x = super()._get_outcome_exog(exposure, mediator)
        if self._int_pos is not None:
            x[:, self._int_pos] = exposure * np.asarray(mediator, dtype=float)
        return x

    def _tick(self):
        self._done += 1
        if self._total >= 400 and self._done >= self._next * self._total:
            print(f'smui:progress mediation {self._done // 2} {self._total // 2}', flush=True)
            self._next += 0.1

    def _simulate_params(self, result):
        self._tick()
        return super()._simulate_params(result)

    def _fit_model(self, model, fit_kwargs, boot=False):
        if boot:
            self._tick()
        return super()._fit_model(model, fit_kwargs, boot=boot)


# ---- the specification --------------------------------------------------------------------

def _binary(s, name, what):
    """A 0/1 variable from a two-level column (1: the last level) or from a
    numeric column of zeros and ones."""
    if isinstance(s.dtype, pd.CategoricalDtype):
        s = s.cat.remove_unused_categories()
        lv = list(s.cat.categories)
        if len(lv) != 2:
            raise UserError(f'{name} ({what}) has {len(lv)} level{"s" if len(lv) != 1 else ""} in these rows; a logistic or probit model needs two.')
        return (s.cat.codes.to_numpy() == 1).astype(float), lv
    v = s.to_numpy(float)
    if not np.all((v == 0) | (v == 1)):
        raise UserError(f'{name} ({what}) takes a logistic or probit model only when it is 0 or 1 (or a column with two levels).')
    return v, None


def _spec(table, y, treatment, mediator, covariates, outcome_model, mediator_model, interaction, control, treated):
    covariates = [c for c in (covariates or []) if c]
    if not y or not treatment or not mediator:
        raise UserError('Mediation needs an outcome, a treatment and a mediator.')
    roles = [y, treatment, mediator]
    if len(set(roles)) < 3:
        raise UserError('The outcome, the treatment and the mediator must be three different columns.')
    for c in covariates:
        if c in roles:
            raise UserError(f'{c} is the {"outcome" if c == y else "treatment" if c == treatment else "mediator"}: take it out of the covariates.')
    covariates = list(dict.fromkeys(covariates))
    cat = {c: data.is_categorical(table, c) for c in roles + covariates}
    for c, what in ((y, 'the outcome'), (mediator, 'the mediator')):
        if not cat[c] and data.meta(table, c).get('dataType') != 'numeric':
            raise UserError(f'{c} ({what}) must be numeric or have two levels.')
    om = outcome_model or ('logit' if cat[y] else 'ols')
    mm = mediator_model or ('logit' if cat[mediator] else 'ols')
    for k, what in ((om, 'outcome'), (mm, 'mediator')):
        if k not in KINDS:
            raise UserError(f'no {what} model {k!r}; choose one of {", ".join(KINDS)}')
    for c, k, what in ((y, om, 'the outcome'), (mediator, mm, 'the mediator')):
        if cat[c] and k in ('ols', 'poisson'):
            lv = data.meta(table, c).get('levels') or []
            if k == 'poisson' or len(lv) != 2:
                raise UserError(f'{c} ({what}) is categorical: it takes a logistic or probit model' + (', with two levels.' if len(lv) != 2 else '.'))
    return {'y': y, 'treatment': treatment, 'mediator': mediator, 'covariates': covariates, 'cat': cat,
            'outcome_model': om, 'mediator_model': mm, 'interaction': bool(interaction), 'control': control, 'treated': treated}


def _frame(table, S, rows):
    """The complete rows, with the treatment recoded to 0/1 (or the
    contrast), 0/1 outcome and mediator where the model is binary."""
    names = [S['y'], S['treatment'], S['mediator']] + S['covariates']
    raw = data.frame(table, names, rows, dropna=False)
    n_rows = len(raw)
    df = raw.dropna(how='any')
    n = len(df)
    if n < 5:
        raise UserError(f'{n} complete row{"s" if n != 1 else ""}: too few to fit the two models.')
    taken = {q(c) for c in [S['y']] + S['covariates']} | {S['y']} | set(S['covariates'])
    t_alias = _alias('treat', taken)
    m_alias = _alias('med', taken | {t_alias})
    d = pd.DataFrame(index=df.index)
    info = {'n': n, 'n_rows': n_rows, 'n_missing': n_rows - n, 't_alias': t_alias, 'm_alias': m_alias}
    # the treatment
    ts = df[S['treatment']]
    if S['cat'][S['treatment']]:
        ts = ts.cat.remove_unused_categories()
        lv = list(ts.cat.categories)
        if len(lv) != 2:
            raise UserError(f'{S["treatment"]} (the treatment) has {len(lv)} level{"s" if len(lv) != 1 else ""} in these rows; it needs two, or a continuous column.')
        c0 = next((v for v in lv if _same(v, S['control'])), None)
        c1 = next((v for v in lv if _same(v, S['treated'])), None)
        if c1 is None:
            c1 = lv[-1] if c0 is None or not _same(c0, lv[-1]) else lv[0]
        if c0 is None or _same(c0, c1):
            c0 = lv[0] if not _same(lv[0], c1) else lv[1]
        codes = ts.cat.codes.to_numpy()
        d[t_alias] = (codes == lv.index(c1)).astype(float)
        info.update({'t_kind': 'categorical', 'control': c0, 'treated': c1, 'contrast': None,
                     't_label': f'{S["treatment"]}[{_text(c1)}]', 'n_treated': int(d[t_alias].sum()), 'n_control': int(n - d[t_alias].sum())})
    else:
        tv = ts.to_numpy(float)
        c0, c1 = S['control'], S['treated']
        if c0 is None or c1 is None:
            u = np.unique(tv)
            if len(u) == 2:
                c0, c1 = float(u[0]), float(u[1])
            else:
                c0, c1 = (float(v) for v in np.quantile(tv, [0.25, 0.75], method='weibull'))
        c0, c1 = float(c0), float(c1)
        if not (math.isfinite(c0) and math.isfinite(c1)) or c0 == c1:
            raise UserError('The control and the treated value of a continuous treatment must be two different numbers.')
        d[t_alias] = (tv - c0) / (c1 - c0)
        lab = S['treatment'] if (c0 == 0 and c1 == 1) else (f'({S["treatment"]}-{_g(c0)})/{_g(c1 - c0)}' if c0 != 0 else f'{S["treatment"]}/{_g(c1)}')
        info.update({'t_kind': 'continuous', 'control': c0, 'treated': c1, 'contrast': c1 - c0, 't_label': lab})
    # the mediator and the outcome
    for key, alias, kind_key in (('mediator', m_alias, 'mediator_model'), ('y', S['y'], 'outcome_model')):
        name = S[key]
        s = df[name]
        kind = S[kind_key]
        what = 'the mediator' if key == 'mediator' else 'the outcome'
        if kind in ('logit', 'probit'):
            v, lv = _binary(s, name, what)
            d[alias] = v
            info[f'{key}_levels'] = lv
            info[f'{key}_event'] = lv[1] if lv else 1
            info[f'{key}_label'] = f'{name}[{_text(lv[1])}]' if lv else name
        else:
            if isinstance(s.dtype, pd.CategoricalDtype):
                s = s.cat.remove_unused_categories()
                lv = list(s.cat.categories)
                d[alias] = (s.cat.codes.to_numpy() == 1).astype(float)
                info[f'{key}_levels'] = lv
                info[f'{key}_event'] = lv[1]
                info[f'{key}_label'] = f'{name}[{_text(lv[1])}]'
            else:
                v = s.to_numpy(float)
                if kind == 'poisson' and (np.any(v < 0) or np.any(v != np.round(v))):
                    raise UserError(f'{name} ({what}) takes a Poisson model only when it holds counts, whole numbers of zero or more.')
                d[alias] = v
                info[f'{key}_levels'] = None
                info[f'{key}_event'] = None
                info[f'{key}_label'] = name
    if d[m_alias].std() == 0:
        raise UserError(f'{S["mediator"]} (the mediator) is constant in these rows.')
    if d[t_alias].std() == 0:
        raise UserError(f'{S["treatment"]} (the treatment) is constant in these rows.')
    # the covariates: continuous as they are, categorical effect coded with the page's levels
    cov_terms, cov_levels = [], {}
    for c in S['covariates']:
        s = df[c]
        if isinstance(s.dtype, pd.CategoricalDtype):
            s = s.cat.remove_unused_categories()
            lv = list(s.cat.categories)
            if len(lv) < 2:
                raise UserError(f'{c} (a covariate) has one level in these rows: take it out.')
            d[c] = s
            pl = [_num(v) for v in lv]
            cov_levels[c] = lv
            cov_terms.append(f'C({q(c)}, Sum, levels={pl!r})')
        else:
            d[c] = s.to_numpy(float)
            cov_terms.append(q(c))
    info['cov_levels'] = cov_levels
    rhs_m = ' + '.join([t_alias] + cov_terms)
    rhs_o = ' + '.join([t_alias, m_alias] + ([f'{t_alias}:{m_alias}'] if S['interaction'] else []) + cov_terms)
    info['f_mediator'] = f'{m_alias} ~ {rhs_m}'
    info['f_outcome'] = f'{q(S["y"])} ~ {rhs_o}'
    return d, info


def _label(name, S, info):
    """JMP's name for a column of a design."""
    if name == 'Intercept':
        return 'Intercept'
    parts = []
    for p in models._split_colon(name):
        if p == info['t_alias']:
            parts.append(info['t_label'])
        elif p == info['m_alias']:
            parts.append(info['mediator_label'])
        else:
            m = re.fullmatch(r'C\((.+), Sum, levels=.*\)\[S\.(.*)\]', p)
            if m:
                c = next((c for c in S['covariates'] if q(c) == m.group(1)), None)
                if c is not None:
                    # patsy names the column after the level as given in levels=
                    lv = info['cov_levels'][c]
                    hit = next((v for v in lv if str(_num(v)) == m.group(2)), m.group(2))
                    parts.append(f'{c}[{_text(hit)}]')
                    continue
            c = next((c for c in [S['y']] + S['covariates'] if q(c) == p), None)
            parts.append(c if c is not None else p)
    return '*'.join(parts)


def _rank(name, S, info):
    """The order of the report's terms: the intercept, the treatment, the
    mediator, their interaction, then the covariates as given (patsy puts
    categorical terms first)."""
    if name == 'Intercept':
        return (-1, 0)
    fixed = [info['t_alias'], info['m_alias'], f'{info["t_alias"]}:{info["m_alias"]}']
    if name in fixed:
        return (fixed.index(name), 0)
    for k, c in enumerate(S['covariates']):
        if q(c) in name:
            return (3 + k, 0)
    return (99, 0)


def _estimates(res, names, S, info, alpha):
    ci = np.asarray(res.conf_int(alpha))
    use_t = bool(getattr(res, 'use_t', False))
    rows = []
    for j, nm in enumerate(names):
        rows.append({'term': _label(nm, S, info), 'name': nm, 'estimate': float(res.params[j]), 'se': float(res.bse[j]),
                     't': float(res.tvalues[j]), 'p': float(res.pvalues[j]), 'lower': float(ci[j, 0]), 'upper': float(ci[j, 1])})
    rows.sort(key=lambda r: _rank(r['name'], S, info))   # stable: a factor's levels stay in order
    lv = f'{100 * (1 - alpha):g}%'
    stat, pl = ('t Ratio', 'Prob>|t|') if use_t else ('z Ratio', 'Prob>|z|')
    return rtable([col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('t', stat), col('p', pl, 'p'),
                   col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}')], rows)


def _fit_summary(kind, res, y):
    n = int(res.nobs)
    if kind == 'ols':
        return [['RSquare', float(res.rsquared), 'num'], ['RSquare Adj', float(res.rsquared_adj), 'num'],
                ['Root Mean Square Error', float(np.sqrt(res.scale)), 'num'], ['Mean of Response', float(np.mean(y)), 'num'],
                ['Observations', n, 'int']]
    return [['Distribution, link', {'logit': 'Binomial, logit', 'probit': 'Binomial, probit', 'poisson': 'Poisson, log'}[kind], 'text'],
            ['−2 LogLikelihood', float(-2 * res.llf), 'num'], ['AIC', float(res.aic), 'num'], ['Deviance', float(res.deviance), 'num'],
            ['Observations', n, 'int']]


def _path(res, names, name, alpha):
    if name not in names:
        return None
    j = names.index(name)
    ci = np.asarray(res.conf_int(alpha))
    return {'estimate': float(res.params[j]), 'se': float(res.bse[j]), 'p': float(res.pvalues[j]), 'lower': float(ci[j, 0]), 'upper': float(ci[j, 1])}


# ---- the analysis -----------------------------------------------------------------------------

@api('mediation.fit')
def fit(table, y, treatment, mediator, covariates=None, rows=None, outcome_model=None, mediator_model=None, interaction=False,
        control=None, treated=None, n_rep=1000, method='parametric', seed=1, alpha=0.05, table_name='data'):
    try:
        S = _spec(table, y, treatment, mediator, covariates, outcome_model, mediator_model, interaction, control, treated)
        d, info = _frame(table, S, rows)
    except UserError as e:
        return {'error': str(e)}
    method = method if method in METHODS else 'parametric'
    n_rep = int(n_rep or 1000)
    if n_rep < 20 or n_rep > 100000:
        return {'error': 'The number of simulations must be between 20 and 100000.'}
    if info['n'] * n_rep > MAX_WORK:
        return {'error': f'{info["n"]} rows × {n_rep} simulations is more than the page keeps in memory ({MAX_WORK // 1_000_000} million): '
                         f'use at most {max(20, MAX_WORK // info["n"])} simulations, or fewer rows.'}
    seed = int(seed if seed is not None else 1) % (2 ** 32)
    Yo, Xo = patsy.dmatrices(info['f_outcome'], d, return_type='dataframe')
    Ym, Xm = patsy.dmatrices(info['f_mediator'], d, return_type='dataframe')
    on, mn = list(Xo.columns), list(Xm.columns)
    yo, ym = Yo.iloc[:, 0].to_numpy(float), Ym.iloc[:, 0].to_numpy(float)
    for X, what in ((Xo, 'outcome'), (Xm, 'mediator')):
        if np.linalg.matrix_rank(X.to_numpy(float)) < X.shape[1]:
            raise_msg = f'The {what} model\'s design is singular: a covariate is constant, or one is a combination of the others (or of the treatment).'
            return {'error': raise_msg}
    t_a, m_a = info['t_alias'], info['m_alias']
    key = models.model_key('mediation', table, data.version(table), _rows_sig(rows), S['y'], S['treatment'], S['mediator'], S['covariates'],
                           S['outcome_model'], S['mediator_model'], S['interaction'], _num(info['control']), _num(info['treated']), n_rep, method, seed)
    hit = models.recall(key)
    t0 = time.time()
    if hit is None:
        om = _model(S['outcome_model'], yo, Xo.to_numpy(float))
        mm = _model(S['mediator_model'], ym, Xm.to_numpy(float))
        med = _Mediation(om, mm, (on.index(t_a), mn.index(t_a)), on.index(m_a),
                         interaction=on.index(f'{t_a}:{m_a}') if S['interaction'] else None, n_rep=n_rep, method=method)
        np.random.seed(seed)
        try:
            res = med.fit(method=method, n_rep=n_rep)
            o_res, m_res = om.fit(), mm.fit()
        except FIT_ERRORS as e:
            return {'error': f'The models could not be fitted: {e}'}
        # summary() needs the averages over the rows only: the rows x simulations
        # arrays (20 MB for 600 rows and 1000 simulations) are not kept
        res.indirect_effects = res.direct_effects = None
        hit = {'res': res, 'o_res': o_res, 'm_res': m_res, 'seconds': time.time() - t0}
        models.remember(key, hit, keep=24)
        cached = False
    else:
        cached = True
    res, o_res, m_res = hit['res'], hit['o_res'], hit['m_res']
    smry = res.summary(alpha=alpha)
    eff_rows = []
    for label, sm_label, kind in EFFECTS:
        r = smry.loc[sm_label]
        eff_rows.append({'effect': label, 'kind': kind, 'estimate': float(r['Estimate']), 'lower': float(r['Lower CI bound']),
                         'upper': float(r['Upper CI bound']), 'p': float(r['P-value'])})
    lv = f'{100 * (1 - alpha):g}%'
    effects = rtable([col('effect', 'Effect', 'text'), col('estimate', 'Estimate'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}'),
                      col('p', 'P-value', 'p')], eff_rows)
    paths = {'a': _path(m_res, mn, t_a, alpha), 'b': _path(o_res, on, m_a, alpha), 'c': _path(o_res, on, t_a, alpha),
             'i': _path(o_res, on, f'{t_a}:{m_a}', alpha) if S['interaction'] else None}
    out = {
        'y': S['y'], 'treatment': S['treatment'], 'mediator': S['mediator'], 'covariates': S['covariates'],
        'n': info['n'], 'n_rows': info['n_rows'], 'n_missing': info['n_missing'],
        't_kind': info['t_kind'], 'control': _num(info['control']), 'treated': _num(info['treated']), 'contrast': info['contrast'],
        'n_treated': info.get('n_treated'), 'n_control': info.get('n_control'), 't_label': info['t_label'],
        'outcome_model': S['outcome_model'], 'mediator_model': S['mediator_model'], 'interaction': S['interaction'],
        'outcome_event': _num(info['y_event']) if info['y_event'] is not None else None,
        'mediator_event': _num(info['mediator_event']) if info['mediator_event'] is not None else None,
        'outcome_binary': S['outcome_model'] in ('logit', 'probit') or info['y_levels'] is not None,
        'mediator_binary': S['mediator_model'] in ('logit', 'probit') or info['mediator_levels'] is not None,
        'n_rep': n_rep, 'method': method, 'seed': seed, 'alpha': alpha, 'cached': cached, 'seconds': hit['seconds'],
        'effects': effects,
        'draws': {'acme_ctrl': np.asarray(res.ACME_ctrl), 'acme_tx': np.asarray(res.ACME_tx), 'ade_ctrl': np.asarray(res.ADE_ctrl),
                  'ade_tx': np.asarray(res.ADE_tx)},
        'paths': paths,
        'models': {
            'mediator': {'kind': S['mediator_model'], 'label': KIND_LABEL[S['mediator_model']], 'response': info['mediator_label'],
                         'estimates': _estimates(m_res, mn, S, info, alpha), 'summary': _fit_summary(S['mediator_model'], m_res, ym)},
            'outcome': {'kind': S['outcome_model'], 'label': KIND_LABEL[S['outcome_model']], 'response': info['y_label'],
                        'estimates': _estimates(o_res, on, S, info, alpha), 'summary': _fit_summary(S['outcome_model'], o_res, yo)},
        },
    }
    if S['outcome_model'] == 'ols' and S['mediator_model'] == 'ols' and not S['interaction']:
        out['product'] = {'ab': paths['a']['estimate'] * paths['b']['estimate'], 'c': paths['c']['estimate']}
    out['notes'] = _notes(S, info, out)
    out['code'] = _code(S, info, table, table_name, rows, n_rep, method, seed, alpha)
    return out


def _notes(S, info, out):
    notes = []
    ev = lambda v: _text(v)  # noqa: E731
    if out['outcome_binary']:
        yl = f'{S["y"]} = {ev(info["y_event"])}' if info['y_levels'] else f'{S["y"]} = 1'
        notes.append(f'{S["y"]} is binary: the effects are differences in the probability that {yl}, averaged over the rows (risk differences, the probability scale), '
                     f'whatever the link of the outcome model; its coefficients are on the {"log-odds" if S["outcome_model"] == "logit" else "probit" if S["outcome_model"] == "probit" else "linear"} scale.')
    elif S['outcome_model'] == 'poisson':
        notes.append(f'The effects are differences in the expected count of {S["y"]}, averaged over the rows; the outcome model\'s coefficients are on the log scale.')
    if out['mediator_binary']:
        ml = f'{S["mediator"]} = {ev(info["mediator_event"])}' if info['mediator_levels'] else f'{S["mediator"]} = 1'
        notes.append(f'{S["mediator"]} is binary ({ml} is 1): each simulation draws it as 0 or 1 from the mediator model, so the indirect effect passes through the probability that {ml}.')
    if info['t_kind'] == 'continuous':
        notes.append(f'{S["treatment"]} is continuous: the effects compare {S["treatment"]} = {_g(info["treated"])} (treated) with {_g(info["control"])} (control). '
                     f'The models use {info["t_label"]}, which is 0 at the control value and 1 at the treated value; its coefficients are per {_g(info["contrast"])} of {S["treatment"]}.')
    if S['interaction']:
        notes.append(f'With the interaction {info["t_label"]}*{info["mediator_label"]} the mediator may act differently in the two conditions, so the control and treated effects can differ.')
    return notes


def _code(S, info, table, table_name, rows, n_rep, method, seed, alpha):
    lines = _fit_code(S, info, table, table_name, rows, n_rep, method, seed)
    lines.append(f'print(med.summary(alpha={alpha!r}))')
    lines.append('print(outcome_model.fit().summary(), mediator_model.fit().summary())')
    return '\n'.join(lines)


def _fit_code(S, info, table, table_name, rows, n_rep, method, seed, extra_imports=()):
    """The code that reads the table, recodes the treatment (and a binary
    outcome or mediator), sets up the two models and runs the simulations,
    as the report does: up to med = Mediation(...).fit(...)."""
    lines = [code_head(table_name, [*extra_imports, 'from statsmodels.stats.mediation import Mediation'])]
    if rows is not None:
        n_all = data.TABLES[table]['n']
        keep = sorted(int(r) for r in rows)
        if len(keep) > n_all / 2:
            drop = sorted(set(range(n_all)) - set(keep))
            if drop:
                lines.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
        else:
            lines.append(f'df = df.loc[{keep}]   # the rows of the report')
    names = [S['y'], S['treatment'], S['mediator']] + S['covariates']
    lines.append(f'd = df[{J(names)}].dropna().copy()   # the complete rows')
    t, m = info['t_alias'], info['m_alias']
    T, M = f'd[{J(S["treatment"])}]', f'd[{J(S["mediator"])}]'

    def eq(expr, v):
        v = _num(v)
        return f'({expr} == {_lit(v)})' if not isinstance(v, str) else f'({expr}.astype(str) == {J(v)})'
    lines.append('# Mediation sets the exposure to 0 (control) and 1 (treated), by name: the treatment and the mediator get plain names')
    if info['t_kind'] == 'categorical':
        lines.append(f'd[{J(t)}] = {eq(T, info["treated"])}.astype(float)   # 1: treated ({S["treatment"]} = {_text(info["treated"])}), 0: control ({S["treatment"]} = {_text(info["control"])})')
    else:
        lines.append(f'd[{J(t)}] = ({T} - {info["control"]!r}) / ({info["treated"]!r} - {info["control"]!r})   # 0 at the control value, 1 at the treated value')
    for key, alias, expr in (('mediator', m, M), ('y', S['y'], f'd[{J(S["y"])}]')):
        lv = info[f'{key}_levels']
        if lv:
            lines.append(f'd[{J(alias)}] = {eq(expr, lv[1])}.astype(float)   # 1: {S[key]} = {_text(lv[1])}, 0: {S[key]} = {_text(lv[0])}')
        elif alias != S[key]:
            lines.append(f'd[{J(alias)}] = {expr}   # the mediator')
    for c, lv in info['cov_levels'].items():
        pl = [_num(v) for v in lv]
        if any(isinstance(v, str) for v in pl):
            lines.append(f'd[{J(c)}] = d[{J(c)}].astype(str)')
    for which, f, kind in (('outcome_model', info['f_outcome'], S['outcome_model']), ('mediator_model', info['f_mediator'], S['mediator_model'])):
        if kind == 'ols':
            lines.append(f'{which} = smf.ols({J(f)}, data=d)')
        else:
            lines.append(f'{which} = smf.glm({J(f)}, data=d, family={_family_code(kind)})')
    lines.append(f'np.random.seed({seed})   # statsmodels draws from numpy\'s global generator')
    lines.append('# the formula path builds both designs again for every simulation: some seconds per thousand')
    lines.append(f'med = Mediation(outcome_model, mediator_model, {J(t)}, {J(m)}).fit(method={J(method)}, n_rep={n_rep})')
    return lines


# ---- the graphs as matplotlib code ----------------------------------------------------------------
# Under each graph the report shows Python that draws it with matplotlib from
# a CSV export of the table (the notebook runs it): the report's rows, the two
# models and the simulations as the report's code sets them up (the formula
# path, the same seed: the same numbers), the light theme's colours, the
# graph's size at 100 pixels an inch. The page sends what it chose (the
# diagram's layout and the treatment's labels, the histograms' bins);
# mediation.plot_code writes the code of one graph.
ACME, ADE, TEXT, MUTED, SURFACE = '#2e6fba', '#b8406e', '#352921', '#786b5d', '#fcf7f2'
PX = 0.72   # points per pixel: a figure at 100 pixels an inch
SM_ROW = {mine: theirs for mine, theirs, _ in EFFECTS}   # the report's names of the effects -> statsmodels' summary() rows
COEF_SCALE = {'ols': '', 'logit': ' (log odds)', 'probit': ' (probit)', 'poisson': ' (log)'}

SIG_LINES = ['def sig(v, digits=4):   # a number as the page writes it: 4 significant digits, no trailing zeros, a minus sign',
             '    v = float(v)',
             '    if v.is_integer() and abs(v) < 1e15:',
             '        s = str(int(v))',
             '    elif abs(v) >= 1e9 or abs(v) < 1e-4:',
             '        m, e = f"{v:.{min(digits, 5) - 1}e}".split("e")',
             '        s = f"{m}e{int(e)}"',
             '    else:',
             '        s = f"{v:.{digits}g}"',
             '        s = str(int(float(s))) if "e" in s else (s.rstrip("0").rstrip(".") if "." in s else s)',
             '    return "−" + s[1:] if s.startswith("-") else s']


def _pt(px):
    return f'{px * PX:.3g}'


def _effects_code(S, info, head, plot, alpha):
    names = ['ACME (control)', 'ACME (treated)', 'ACME (average)', 'ADE (control)', 'ADE (treated)', 'ADE (average)', 'Total Effect']
    kinds = {n: k for n, _, k in EFFECTS}
    binary = S['outcome_model'] in ('logit', 'probit') or info['y_levels'] is not None
    c = head + [f'smry = med.summary(alpha={alpha!r})',
                f'names = {J(names)}   # the report\'s names, top down',
                'rows = ' + J({n: SM_ROW[n] for n in names}) + '   # their rows in statsmodels\' summary()',
                f'kinds = {J({n: kinds[n] for n in names})}',
                'fig, ax = plt.subplots(figsize=(4.3, 2.9), layout="constrained")',
                f'style = {{"acme": ("ACME (indirect)", "o", "{ACME}", {_pt(9)}), "ade": ("ADE (direct)", "s", "{ADE}", {_pt(9)}), "total": ("Total", "D", "{TEXT}", {_pt(11)})}}',
                'for kind, (label, marker, color, size) in style.items():',
                '    at = [i for i, n in enumerate(names) if kinds[n] == kind]',
                '    e, lo, hi = (smry.loc[[rows[names[i]] for i in at], col].to_numpy(float) for col in ("Estimate", "Lower CI bound", "Upper CI bound"))',
                f'    ax.errorbar(e, at, xerr=[e - lo, hi - e], fmt=marker, color=color, ecolor=color, elinewidth={_pt(2)}, capsize={_pt(2.5)}, markersize=size, mec="{SURFACE}", mew={_pt(2)}, label=label)',
                'ax.set_yticks(range(len(names)), names); ax.invert_yaxis()   # the first at the top',
                'lo, hi = smry.loc[list(rows.values()), "Lower CI bound"].min(), smry.loc[list(rows.values()), "Upper CI bound"].max()',
                'if lo <= 0 <= hi:',
                f'    ax.axvline(0, color="{MUTED}", linewidth={_pt(1)})   # no effect',
                f'ax.set_xlabel({J(f"Effect on P({S[chr(121)]})" if binary else f"Effect on {S[chr(121)]}")})',
                f'fig.legend(loc="outside upper left", ncols=3, frameon=False, fontsize={_pt(11)})',
                'ax.set_title("mediation effects")', 'plt.show()']
    return '\n'.join(c)


def _draws_code(S, info, head, plot, alpha):
    name = 'ADE (average)' if plot.get('name') == 'ADE (average)' else 'ACME (average)'
    what = 'ADE' if name.startswith('ADE') else 'ACME'
    color = ADE if what == 'ADE' else ACME
    b = plot.get('bins') or {'start': 0.0, 'end': 1.0, 'size': 1.0}
    start, end, size = float(b['start']), float(b['end']), float(b['size'])
    nb = max(1, int(round((end - start) / size)))
    c = head + [f'smry = med.summary(alpha={alpha!r})',
                f'v = (np.asarray(med.{what}_ctrl) + np.asarray(med.{what}_tx)) / 2   # the {name} of each simulation',
                f'start, end, size, nb = {start!r}, {end!r}, {size!r}, {nb}   # the page\'s bins',
                'k = np.clip(np.floor((v - start) / size + 1e-9), 0, nb - 1).astype(int)',
                'counts = np.bincount(k, minlength=nb)',
                'fig, ax = plt.subplots(figsize=(3.6, 2.4), layout="constrained")',
                f'ax.bar(start + (np.arange(nb) + 0.5) * size, counts, width=size, color="{color}", alpha=0.75, edgecolor="{SURFACE}", linewidth={_pt(1)})',
                f'e = smry.loc[{J(SM_ROW[name])}]',
                f'ax.axvline(e["Estimate"], color="{TEXT}", linewidth={_pt(2)})   # the estimate: the mean of the simulations',
                f'for bound in (e["Lower CI bound"], e["Upper CI bound"]):   # the {100 * (1 - alpha):g}% interval: their percentiles',
                f'    ax.axvline(bound, color="{TEXT}", linewidth={_pt(1.5)}, linestyle=":")']
    if start < 0 < end:
        c.append(f'ax.axvline(0, color="{MUTED}", linewidth={_pt(1)})   # no effect')
    c += ['ax.set_ylim(bottom=0)', f'ax.set_xlabel({J(name)})', 'ax.set_ylabel("Simulations")', f'ax.set_title({J(name + " simulated")})', 'plt.show()']
    return '\n'.join(c)


def _diagram_code(S, info, head, plot, alpha):
    """The path diagram: the three boxes in a triangle, the arrows (the
    indirect path in blue, the direct one in rose), the models'
    coefficients on them and the simulated effects, as the page lays them
    out (compact: at phone width)."""
    compact = bool(plot.get('compact'))
    width, height = float(plot.get('width') or 620), (380 if compact else 330)
    bw, bh = (3.9, 1.25) if compact else (2.7, 1.05)
    T, M, Y = ((2.15 if compact else 1.55), 0.95), (5.0, 4.25), ((7.85 if compact else 8.45), 0.95)
    f = {'node': 10.5, 'sub': 9, 'lab': 9.5, 'eff': 10} if compact else {'node': 11.5, 'sub': 10, 'lab': 11, 'eff': 11}
    t, m = info['t_alias'], info['m_alias']
    ms, os_ = COEF_SCALE[S['mediator_model']], COEF_SCALE[S['outcome_model']]
    inter = S['interaction']
    lv = f'{100 * (1 - alpha):g}'
    mlabel = {'ols': 'Least Squares', 'logit': 'Logistic (logit)', 'probit': 'Probit', 'poisson': 'Poisson (log)'}

    def line(text, bold=False, size=None):   # one line of a label, as Python: (an f-string, bold, size)
        return f'(f{J(text)}, {bold}, {size or f["lab"]})'

    # the aliases are plain names (treat, med): single quotes inside the labels' f-strings
    se_a = [] if compact else [line(f"(SE {{sig(mm.bse['{t}'])}})")]
    se_b = [] if compact else [line(f"(SE {{sig(om.bse['{m}'])}})")]
    a_lines = [line(f'a = {{sig(a)}}{ms}')] + se_a
    csz = f['lab'] if compact else 10.5
    if inter:
        b_lines = [line('b = {sig(b)} at control,'), line(f'{{sig(b + i)}} at treated{os_}')]
        if compact:
            c_lines = [line(f'c′ = {{sig(cp)}} at {S["mediator"]} = 0, T×M {{sig(i)}}{os_}', size=csz)]
        else:
            c_lines = [line(f'c′ = {{sig(cp)}} at {S["mediator"]} = 0', size=csz), line(f'T×M {{sig(i)}}{os_}', size=csz)]
    else:
        b_lines = [line(f'b = {{sig(b)}}{os_}')] + se_b
        c_lines = [line(f"c′ = {{sig(cp)}}{os_} (SE {{sig(om.bse['{t}'])}})", size=csz)]
    mediated = "{sig(100 * prop['Estimate'], 3)}% mediated"
    c = head + SIG_LINES + ['',
         'def edge(a, b, pad=0.12):   # where the line from the box at a to the box at b leaves the first box',
         '    dx, dy = b[0] - a[0], b[1] - a[1]',
         f'    t = min(({bw} / 2 + pad) / abs(dx) if dx else np.inf, ({bh} / 2 + pad) / abs(dy) if dy else np.inf)',
         '    return a[0] + t * dx, a[1] + t * dy',
         '',
         'def label(x, y, lines, ha="center"):   # lines of (text, bold, size in pixels) centred on (x, y), as the page\'s annotations',
         '    k = len(lines)',
         '    for i, (text, bold, size) in enumerate(lines):',
         f'        ax.annotate(text, (x, y), xytext=(0, ((k - 1) / 2 - i) * 1.3 * size * {PX}), textcoords="offset points", ha=ha, va="center",',
         f'                    fontsize=size * {PX}, fontweight="bold" if bold else "normal", color="{TEXT}")',
         '',
         f'smry = med.summary(alpha={alpha!r})',
         'om, mm = outcome_model.fit(), mediator_model.fit()',
         f'a, b, cp = mm.params[{J(t)}], om.params[{J(m)}], om.params[{J(t)}]   # the paths: the treatment on the mediator, the mediator on the outcome, the treatment on the outcome']
    if inter:
        c.append(f'i = om.params[{J(t + ":" + m)}]   # the treatment × mediator interaction')
    c += ['acme, ade, tot, prop = (smry.loc[r] for r in ("ACME (average)", "ADE (average)", "Total effect", "Prop. mediated (average)"))',
          'ci = lambda e: f"{sig(e[\'Lower CI bound\'])} to {sig(e[\'Upper CI bound\'])}"',
          f'fig = plt.figure(figsize=({width / 100:g}, {(height + 24) / 100:g}))',
          f'ax = fig.add_axes([6 / {width:g}, 6 / {height + 24:g}, 1 - 12 / {width:g}, 1 - 30 / {height + 24:g}])   # the page\'s margins, and room for the title',
          f'ax.set_xlim(-0.1, 10.1); ax.set_ylim({-1.65 if compact else -0.75}, 5.6); ax.axis("off")',
          f'T, M, Y = {T}, {M}, {Y}   # the boxes\' centres: the treatment and the outcome below, the mediator above',
          'for p in (T, M, Y):',
          f'    ax.add_patch(plt.Rectangle((p[0] - {bw} / 2, p[1] - {bh} / 2), {bw}, {bh}, facecolor=(0, 0, 0, 0.025), edgecolor="{TEXT}", linewidth={_pt(1.2)}))',
          f'for p, q, color in ((T, M, "{ACME}"), (M, Y, "{ACME}"), (T, Y, "{ADE}")):   # the indirect path in blue, the direct path in rose',
          f'    ax.annotate("", xy=edge(q, p), xytext=edge(p, q), color=color, arrowprops={{"arrowstyle": "-|>", "color": color, "lw": {_pt(2)}, "shrinkA": 0, "shrinkB": 0, "mutation_scale": 12}})',
          f'label(*T, [("Treatment", True, {f["node"]}), ({J(S["treatment"])}, False, {f["node"]}), ({J(plot.get("tlabel") or "")}, False, {f["sub"]})])',
          f'label(*M, [("Mediator", True, {f["node"]}), ({J(S["mediator"])}, False, {f["node"]}), ({J(mlabel[S["mediator_model"]])}, False, {f["sub"]})])',
          f'label(*Y, [("Outcome", True, {f["node"]}), ({J(S["y"])}, False, {f["node"]}), ({J(mlabel[S["outcome_model"]])}, False, {f["sub"]})])']
    est = {k: f"{{sig({k}['Estimate'])}}" for k in ('acme', 'ade', 'tot')}
    if compact:
        acme_l = [line(f"ACME {est['acme']}", True, f['eff']), f"(ci(acme), False, {f['eff']})"]
        ade_l = [line(f"ADE {est['ade']}  {{ci(ade)}}", True, f['eff'])]
        tot_l = [line(f"Total {est['tot']}, {mediated}")]
        places = [(3.3, 2.65, a_lines, 'right'), (6.7, 2.65, b_lines, 'left'), (5, 2.3, acme_l, None), (5, 0.0, c_lines, None), (5, -0.6, ade_l, None), (5, -1.2, tot_l, None)]
    else:
        acme_l = [line(f"ACME {est['acme']}", True, f['eff']), line(f"{lv}%: {{ci(acme)}}", False, f['eff'])]
        ade_l = [line(f"ADE {est['ade']}  {lv}%: {{ci(ade)}}", True, f['eff'])]
        tot_l = [line(f"Total effect {est['tot']} ({{ci(tot)}}), {mediated}", False, 10.5)]
        places = [(2.9, 2.85, a_lines, 'right'), (7.1, 2.85, b_lines, 'left'), (5, 1.45 if inter else 1.28, c_lines, None), (5, 2.45, acme_l, None), (5, 0.1, ade_l, None), (5, -0.42, tot_l, None)]
    for x, y, lines, ha in places:
        c.append(f'label({x}, {y}, [{", ".join(lines)}]' + (f', ha="{ha}"' if ha else '') + ')' + ('   # the page bolds only the estimate' if lines is ade_l else ''))
    if S['covariates']:
        adj = f'Adjusted for {", ".join(S["covariates"])}'
        if compact and len(adj) > 44:
            adj = f'Adjusted for {len(S["covariates"])} covariates'
        c.append(f'label(0.05, 5.4, [({J(adj)}, False, {9 if compact else 10})], ha="left")')
    c += ['ax.set_title("mediation path diagram")', 'plt.show()']
    return '\n'.join(c)


@api('mediation.plot_code')
def plot_code(table, y, treatment, mediator, kind='effects', plot=None, covariates=None, rows=None, outcome_model=None, mediator_model=None, interaction=False,
              control=None, treated=None, n_rep=1000, method='parametric', seed=1, alpha=0.05, table_name='data'):
    """The Python that draws one of the report's graphs with matplotlib
    (kind: diagram, effects, draws), the models and simulations as the
    report's code runs them, from what the page chose (plot)."""
    try:
        S = _spec(table, y, treatment, mediator, covariates, outcome_model, mediator_model, interaction, control, treated)
        _, info = _frame(table, S, rows)
    except UserError as e:
        return {'error': str(e)}
    method = method if method in METHODS else 'parametric'
    seed = int(seed if seed is not None else 1) % (2 ** 32)
    head = _fit_code(S, info, table, table_name, rows, int(n_rep or 1000), method, seed, ['import matplotlib.pyplot as plt'])
    plot = plot or {}
    if kind == 'effects':
        return {'plot_code': _effects_code(S, info, head, plot, alpha)}
    if kind == 'draws':
        return {'plot_code': _draws_code(S, info, head, plot, alpha)}
    if kind == 'diagram':
        return {'plot_code': _diagram_code(S, info, head, plot, alpha)}
    return {'error': f'no graph {kind!r}'}
