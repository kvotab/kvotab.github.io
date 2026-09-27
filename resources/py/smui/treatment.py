"""Treatment Effects: the effect of a two-level treatment on an outcome,
estimated from observational data with statsmodels' TreatmentEffect
(statsmodels.treatment.treatment_effects, after Stata's teffects).

A propensity-score model (logit or probit) gives each row its probability
of treatment given the treatment covariates; an outcome model (least
squares, one per treatment group) its predicted outcome under either
treatment given the outcome covariates. The estimators combine them:

  IPW        inverse probability weighting (normalised weights)
  AIPW       augmented IPW: the outcome models plus IPW-weighted residuals;
             doubly robust (right when either model is right)
  AIPW (WLS) AIPW with the outcome models fitted by IPW-weighted least squares
  RA         regression adjustment: the two outcome models' predictions
             averaged over the sample
  IPW-RA     regression adjustment with IPW-weighted outcome models (doubly
             robust)

Each gives the average treatment effect (ATE) and the two potential-outcome
means (POM); IPW, RA and IPW-RA also the effect on the treated (ATT,
effect_group=1). The standard errors come from statsmodels' joint GMM of
the propensity model's score, the outcome models' normal equations and the
effect's own moment (exactly identified, HC0), so they include the
estimation of the propensity scores.

Three things in statsmodels 0.14.6 are worked around here:

  * the moment conditions of AIPW (WLS) and IPW-RA take the propensity
    model's parameters as params[-6:], right only for a model with six;
    _AIPWWLSGMM6 and _IPWRAGMM6 below are statsmodels' with the slice after
    the outcome models' parameters (the same numbers when there are six);
  * RA needs the treatment indicator as integers (it slices with its sum);
  * the GMM's Jacobian is a finite difference with a fixed step of 1e-4 in
    every parameter (GMM.gradient_momcond), far too coarse for the
    coefficient of a covariate in large units (earnings in dollars: a
    coefficient near 1e-5), and the standard errors of IPW, AIPW (WLS) and
    IPW-RA come out wrong (in the job-training example several times too
    large, as resources/tests/smui/test_treatment.py shows). TreatmentEffect is given the
    designs with every column but the intercept centred and scaled to
    standard deviation 1: the same models (the same propensity scores and
    predictions, so the same effects), with coefficients near 1, for which
    the step is fine. The models' own tables are in the original units.

The report's other parts are glue in numpy: the covariate balance
(standardized mean differences and variance ratios before and after
weighting), the weights, the overlap of the propensity scores, and the
unadjusted difference in means (statsmodels' CompareMeans) for contrast.

Every result carries 'code': Python that computes it from a CSV export of
the table.
"""
import contextlib
import json
import math

import numpy as np
import pandas as pd
from scipy import stats
from scipy.linalg import block_diag

from . import data, models
from .registry import api
from .util import code_head, col
from .util import table as rtable

J = json.dumps

ESTIMATORS = [('ipw', 'IPW'), ('aipw', 'AIPW'), ('aipw_wls', 'AIPW (WLS)'), ('ra', 'RA'), ('ipw_ra', 'IPW-RA')]
LABEL = dict(ESTIMATORS)
ATT_OK = ('ipw', 'ra', 'ipw_ra')          # statsmodels' effect_group=1
USES_OUTCOME = ('aipw', 'aipw_wls', 'ra', 'ipw_ra')
CERTAIN = 1e-8                           # a propensity this close to 0 or 1 is a prediction with certainty


class UserError(ValueError):
    """A problem with the data or the roles, said in words for the report."""


# ---- statsmodels 0.14.6's AIPW (WLS) and IPW-RA moments, with the right slice -------------
# The moment conditions of statsmodels.treatment.treatment_effects._AIPWWLSGMM
# and _IPWRAGMM (statsmodels 0.14.6, BSD-3-Clause, Josef Perktold), unchanged
# except the propensity parameters: params[2 * k + 1:] (after the ATE and the
# two outcome models) where statsmodels has params[-6:].

def _gmm_classes():
    import statsmodels.treatment.treatment_effects as te

    class _AIPWWLSGMM6(te._AIPWWLSGMM):
        def momcond(self, params):
            ra = self.teff
            treat_mask = ra.treat_mask
            res_select = ra.results_select
            ppom = params[1]
            mask = np.arange(len(params)) != 1
            params = params[mask]
            k = ra.results0.model.exog.shape[1]
            pm = params[0]
            p0 = params[1:k + 1]
            p1 = params[k + 1:2 * k + 1]
            ps = params[2 * k + 1:]
            mod0 = ra.results0.model
            mod1 = ra.results1.model
            exog = ra.exog_grouped
            endog = ra.endog_grouped
            prob_sel = np.asarray(res_select.model.predict(ps))
            prob_sel = np.clip(prob_sel, 0.001, 0.999)
            prob0 = prob_sel[~treat_mask]
            prob1 = prob_sel[treat_mask]
            prob = np.concatenate((prob0, prob1))
            tind = 0
            ww0 = (1 - tind) / (1 - prob0) * ((1 - tind) / (1 - prob0) - 1)
            tind = 1
            ww1 = tind / prob1 * (tind / prob1 - 1)
            fitted0 = mod0.predict(p0, exog)
            mom0 = te._mom_olsex(p0, model=mod0) * ww0[:, None]
            fitted1 = mod1.predict(p1, exog)
            mom1 = te._mom_olsex(p1, model=mod1) * ww1[:, None]
            mom_outcome = block_diag(mom0, mom1)
            tind = ra.treatment
            tind = np.concatenate((tind[~treat_mask], tind[treat_mask]))
            correct0 = (endog - fitted0) / (1 - prob) * (1 - tind)
            correct1 = (endog - fitted1) / prob * tind
            tmean0 = fitted0 + correct0
            tmean1 = fitted1 + correct1
            ate = tmean1 - tmean0
            mm = ate - pm
            mpom = tmean0 - ppom
            mm = np.column_stack((mm, mpom))
            mom_select = res_select.model.score_obs(ps)
            mom_select = np.concatenate((mom_select[~treat_mask], mom_select[treat_mask]), axis=0)
            return np.column_stack((mm, mom_outcome, mom_select))

    class _IPWRAGMM6(te._IPWRAGMM):
        def momcond(self, params):
            ra = self.teff
            treat_mask = ra.treat_mask
            res_select = ra.results_select
            ppom = params[1]
            mask = np.arange(len(params)) != 1
            params = params[mask]
            k = ra.results0.model.exog.shape[1]
            pm = params[0]
            p0 = params[1:k + 1]
            p1 = params[k + 1:2 * k + 1]
            ps = params[2 * k + 1:]
            mod0 = ra.results0.model
            mod1 = ra.results1.model
            exog = ra.exog_grouped
            tind = np.zeros(len(treat_mask))
            tind[-treat_mask.sum():] = 1
            prob_sel = np.asarray(res_select.model.predict(ps))
            prob_sel = np.clip(prob_sel, 0.001, 0.999)
            prob0 = prob_sel[~treat_mask]
            prob1 = prob_sel[treat_mask]
            effect_group = self.effect_group
            if effect_group == "all":
                w0 = 1 / (1 - prob0)
                w1 = 1 / prob1
                sind = 1
            elif effect_group in [1, "treated"]:
                w0 = prob0 / (1 - prob0)
                w1 = prob1 / prob1
                sind = tind / tind.mean()
            elif effect_group in [0, "untreated", "control"]:
                w0 = (1 - prob0) / (1 - prob0)
                w1 = (1 - prob1) / prob1
                sind = (1 - tind)
                sind /= sind.mean()
            else:
                raise ValueError("incorrect option for effect_group")
            fitted0 = mod0.predict(p0, exog)
            mom0 = te._mom_olsex(p0, model=mod0) * w0[:, None]
            fitted1 = mod1.predict(p1, exog)
            mom1 = te._mom_olsex(p1, model=mod1) * w1[:, None]
            mom_outcome = block_diag(mom0, mom1)
            mm = (fitted1 - fitted0 - pm) * sind
            mpom = (fitted0 - ppom) * sind
            mm = np.column_stack((mm, mpom))
            mom_select = res_select.model.score_obs(ps)
            mom_select = np.concatenate((mom_select[~treat_mask], mom_select[treat_mask]), axis=0)
            return np.column_stack((mm, mom_outcome, mom_select))

    return te, _AIPWWLSGMM6, _IPWRAGMM6


_FIXED = []


@contextlib.contextmanager
def _right_slices():
    """statsmodels' own aipw_wls() and ipw_ra(), with the moment classes
    above in their module while they run."""
    if not _FIXED:
        _FIXED.extend(_gmm_classes())
    te, a, b = _FIXED
    old = te._AIPWWLSGMM, te._IPWRAGMM
    te._AIPWWLSGMM, te._IPWRAGMM = a, b
    try:
        yield
    finally:
        te._AIPWWLSGMM, te._IPWRAGMM = old


# ---- the sample: rows, designs, the propensity model --------------------------------------

def _num(v):
    """A level as Python: 1.0 as 1, text as text."""
    if isinstance(v, (np.floating, float)):
        v = float(v)
        return int(v) if v.is_integer() else v
    if isinstance(v, np.integer):
        return int(v)
    return v


def _lvtext(v):
    v = _num(v)
    return f'{v:g}' if isinstance(v, float) else str(v)


def _levels_of(table, name, values):
    """The distinct values present, in the page's order for a categorical
    column (its value order), ascending otherwise."""
    present = list(pd.unique(values))
    m = data.meta(table, name)
    order = m.get('levels') if m.get('modelingType') in ('nominal', 'ordinal') else None
    if order:
        if m.get('dataType') == 'numeric':
            order = [float(x) for x in order]
        seen = set(present)
        lv = [x for x in order if x in seen]
        lv += [x for x in present if x not in set(lv)]
        return lv
    try:
        return sorted(present)
    except TypeError:
        return sorted(present, key=str)


def _design(table, names, rows, n_index):
    """A design (models.build, JMP's effect coding) over the covariates, and
    its matrix with an intercept; with no covariates, the intercept only."""
    import patsy
    if not names:
        return None, pd.DataFrame({'Intercept': np.ones(len(n_index))}, index=n_index), ['Intercept'], '1'
    d = models.build(table, None, [[c] for c in names], rows=rows)
    X = patsy.dmatrix(d.rhs, d.df, return_type='dataframe')
    labels = [d.label(c) for c in X.columns]
    return d, X, labels, models.code_formula(d, lhs=False)


class _Sample:
    pass


def _sample(table, y, treatment, treated=None, outcome=None, covariates=None, rows=None, link='logit', trim=None):
    import statsmodels.api as sm
    if not y or not treatment:
        raise UserError('give the outcome (Y) and the treatment')
    outcome = [c for c in (outcome or []) if c]
    tcov = [c for c in (covariates or []) if c] or list(outcome)
    both = list(dict.fromkeys(outcome + tcov))
    if not tcov:
        raise UserError('the treatment model needs covariates: give Outcome Covariates or Treatment Covariates')
    for c in both:
        if c == y:
            raise UserError(f'{y} is the outcome: it cannot be a covariate too')
        if c == treatment:
            raise UserError(f'{treatment} is the treatment: it cannot be a covariate too')
    if data.meta(table, y).get('dataType') != 'numeric':
        raise UserError(f'the outcome {y} is not numeric: give a continuous or a 0/1 column')
    used = [y, treatment] + both
    n_all = data.TABLES[table]['n'] if rows is None else len(rows)
    base = data.frame(table, used, rows, dropna=True, as_category=False)
    S = _Sample()
    S.y_name, S.t_name, S.outcome, S.tcov, S.both = y, treatment, outcome, tcov, both
    S.link = 'probit' if link == 'probit' else 'logit'
    S.n_missing = int(n_all - len(base))
    tv = base[treatment].to_numpy()
    S.t_numeric = data.meta(table, treatment).get('dataType') == 'numeric'
    lv = _levels_of(table, treatment, tv)
    if len(lv) != 2:
        where = ' in the rows used' if S.n_missing or rows is not None else ''
        raise UserError(f'the treatment {treatment} needs exactly two levels{where}; it has {len(lv)}'
                        + (f' ({", ".join(_lvtext(v) for v in lv[:6])}{", …" if len(lv) > 6 else ""})' if lv else ''))
    if treated is None or (isinstance(treated, str) and treated == ''):
        tr = lv[1]
    else:
        tr = None
        for v in lv:
            if (S.t_numeric and isinstance(treated, (int, float, str)) and _float_or_none(treated) == float(v)) or (not S.t_numeric and str(v) == str(treated)):
                tr = v
        if tr is None:
            raise UserError(f'the treated level {treated!r} is not among the levels of {treatment} ({", ".join(_lvtext(v) for v in lv)})')
    S.treated = tr
    S.control = lv[0] if lv[1] == tr else lv[1]
    S.eps = float(trim) if trim else 0.0
    if not (0 <= S.eps < 0.5):
        raise UserError('trim the propensity scores at an ε between 0 and 0.5')
    S.base = base
    S.t_all = (tv == tr).astype(int)
    S.trim = None
    fit = sm.Probit if S.link == 'probit' else sm.Logit
    idx = base.index.to_numpy()
    for stage in ('all', 'trimmed'):
        n_before = len(idx)
        _fit_rows(S, table, idx, fit, stage)
        if stage == 'all':
            S.n_missing += n_before - len(S.idx)   # rows patsy takes as missing
        if stage == 'trimmed' or not S.eps:
            break
        keep = (S.p >= S.eps) & (S.p <= 1 - S.eps)
        gone = S.idx[~keep]
        S.trim = {'eps': S.eps, 'n_before': int(len(S.idx)), 'n_dropped': int(len(gone)), 'rows': [int(i) for i in gone],
                  'n_dropped_treated': int(np.sum(S.t[~keep])), 'n_dropped_control': int(np.sum(1 - S.t[~keep])),
                  'z_formula_before': S.z_formula}
        if not len(gone):
            break
        idx = S.idx[keep]
    return S


def _fit_rows(S, table, idx, fit, stage):
    """The designs and the propensity model on the rows idx (the page's row
    numbers). Rows patsy takes as missing (a text value "nan") are left out
    as well, so that every part has the same rows."""
    for _ in range(2):
        here = S.base.loc[idx].index
        rows_now = [int(i) for i in idx]
        S.dz, Z, S.z_labels, S.z_formula = _design(table, S.tcov, rows_now, here)
        S.do, X, S.x_labels, S.x_formula = _design(table, S.outcome, rows_now, here)
        if Z.index.equals(here) and X.index.equals(here):
            break
        idx = idx[np.isin(idx, Z.index) & np.isin(idx, X.index)]
    S.idx = idx
    S.t = S.t_all[np.isin(S.base.index.to_numpy(), idx)]
    S.y = S.base.loc[idx, S.y_name].to_numpy(float)
    after = 'after trimming ' if stage == 'trimmed' else ''
    n1, n0 = int(S.t.sum()), int(len(S.t) - S.t.sum())
    if n1 < 2 or n0 < 2:
        raise UserError(f'{after}there are {n1} treated and {n0} control rows; each group needs two or more')
    S.Z, S.X = Z.to_numpy(float), X.to_numpy(float)
    if np.linalg.matrix_rank(S.Z) < S.Z.shape[1]:
        raise UserError(f'{after}the treatment model is singular: a covariate is constant, or one is a combination of others')
    S.model = fit(S.t, S.Z)
    try:
        S.res = S.model.fit(disp=0)
    except np.linalg.LinAlgError as e:
        raise UserError(f'the propensity model could not be fitted ({e}): the covariates may separate the treated from the controls') from e
    S.p = np.asarray(S.res.predict(), dtype=float)


def _float_or_none(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def standardize(M):
    """The design with every column but the first (the intercept) centred
    and scaled to standard deviation 1; a constant column stays as it is."""
    M = np.asarray(M, dtype=float)
    rest = M[:, 1:]
    sd = rest.std(0)
    return np.column_stack([M[:, 0], (rest - rest.mean(0)) / np.where(sd > 0, sd, 1.0)])


def _teffect(S):
    """statsmodels' TreatmentEffect on the standardized designs (see the
    module's notes): the outcome model, the treatment indicator (integers)
    and the propensity model refitted on its standardized design."""
    import statsmodels.api as sm
    from statsmodels.treatment.treatment_effects import TreatmentEffect
    fit = sm.Probit if S.link == 'probit' else sm.Logit
    sel = fit(S.t, standardize(S.Z)).fit(disp=0)
    return TreatmentEffect(sm.OLS(S.y, standardize(S.X)), S.t, results_select=sel)


# ---- the propensity model's report --------------------------------------------------------

def _propensity(S, alpha):
    res = S.res
    params = np.asarray(res.params, dtype=float)
    se = np.asarray(res.bse, dtype=float)
    z = float(stats.norm.ppf(1 - alpha / 2))
    est = []
    for j, lab in enumerate(S.z_labels):
        chi = (params[j] / se[j]) ** 2 if se[j] > 0 else None
        est.append({'term': lab, 'estimate': params[j], 'se': se[j], 'chisq': chi, 'p': float(stats.chi2.sf(chi, 1)) if chi is not None else None,
                    'lower': params[j] - z * se[j], 'upper': params[j] + z * se[j]})
    n = len(S.t)
    k = len(params)
    llf, llnull = float(res.llf), float(res.llnull)
    lr = 2 * (llf - llnull)
    dfm = int(round(res.df_model))
    whole = [{'model': 'Difference', 'nll': llf - llnull, 'df': dfm, 'chisq': lr, 'p': float(stats.chi2.sf(lr, dfm)) if dfm > 0 else None},
             {'model': 'Full', 'nll': -llf, 'df': None, 'chisq': None, 'p': None},
             {'model': 'Reduced', 'nll': -llnull, 'df': None, 'chisq': None, 'p': None}]
    lv = f'{100 * (1 - alpha):g}%'
    tl = f'{S.t_name} = {_lvtext(S.treated)}'
    ret = getattr(res, 'mle_retvals', {}) or {}
    ranks = stats.rankdata(S.p)
    n1 = int(S.t.sum())
    auc = float((ranks[S.t == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * (n - n1)))
    fitstats = {'rsquare_u': float(1 - llf / llnull) if llnull else None, 'aicc': -2 * llf + 2 * k + (2 * k * (k + 1) / (n - k - 1) if n - k - 1 > 0 else float('nan')),
                'bic': -2 * llf + k * math.log(n), 'n': n, 'auc': auc, 'converged': bool(ret.get('converged', True)), 'iterations': ret.get('iterations')}
    return {'estimates': rtable([col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('chisq', 'ChiSquare'),
                                 col('p', 'Prob>ChiSq', 'p'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}')], est,
                                footer=f'{"Logit" if S.link == "logit" else "Probit"} of P({tl}): positive estimates make the treatment more likely.'),
            'whole': rtable([col('model', 'Model', 'text'), col('nll', '-LogLikelihood'), col('df', 'DF', 'int'), col('chisq', 'ChiSquare'), col('p', 'Prob>ChiSq', 'p')], whole),
            'fit': fitstats, 'link': S.link, 'separation': _separation(S)}


def _separation(S):
    """How close the model is to predicting the treatment with certainty."""
    p = S.p
    certain = (p < CERTAIN) | (p > 1 - CERTAIN)
    ret = getattr(S.res, 'mle_retvals', {}) or {}
    out = {'n_certain': int(certain.sum()), 'rows_certain': [int(i) for i in S.idx[certain]], 'converged': bool(ret.get('converged', True)),
           'max_abs_estimate': float(np.max(np.abs(np.asarray(S.res.params, dtype=float)))), 'levels': []}
    # a level of a categorical covariate that holds only treated or only control rows
    if S.dz is not None:
        for name in S.tcov:
            a = S.dz.alias.get(name)
            if a not in S.dz.categorical:
                continue
            s = S.dz.df[a]
            for lv in S.dz.levels[a]:
                m = (s == lv).to_numpy()
                n1 = int(S.t[m].sum())
                if m.sum() and (n1 == 0 or n1 == m.sum()):
                    out['levels'].append({'column': name, 'level': _lvtext(lv), 'n': int(m.sum()), 'all': 'treated' if n1 else 'control'})
    out['state'] = 'complete' if out['n_certain'] == len(p) else ('quasi' if out['n_certain'] or out['levels'] or not out['converged'] else 'none')
    return out


def _weights(S):
    p, t = S.p, S.t
    w_ate = t / p + (1 - t) / (1 - p)
    w_att = t + (1 - t) * p / (1 - p)
    summ = {}
    for key, w in (('ate', w_ate), ('att', w_att)):
        g = {}
        for name, m in (('treated', t == 1), ('control', t == 0)):
            ww = w[m]
            g[name] = {'n': int(m.sum()), 'sum': float(ww.sum()), 'mean': float(ww.mean()), 'min': float(ww.min()), 'max': float(ww.max()),
                       'ess': float(ww.sum() ** 2 / np.sum(ww ** 2))}
        g['n_over_10'] = int(np.sum(w > 10))
        g['max'] = float(w.max())
        summ[key] = g
    return w_ate, w_att, summ


def _wvar(x, w, binary):
    m = float(np.sum(w * x) / np.sum(w))
    if binary:
        return m, m * (1 - m)
    sw, sw2 = float(np.sum(w)), float(np.sum(w * w))
    return m, float(np.sum(w * (x - m) ** 2) * sw / (sw * sw - sw2)) if sw * sw > sw2 else float('nan')


def _balance_row(term, x, binary, t, weights):
    r = {'term': term, 'kind': 'level' if binary else 'continuous'}
    for key, w in weights.items():
        m1, v1 = _wvar(x[t == 1], w[t == 1], binary)
        m0, v0 = _wvar(x[t == 0], w[t == 0], binary)
        den = math.sqrt((v1 + v0) / 2) if np.isfinite(v1 + v0) and v1 + v0 > 0 else float('nan')
        r[f'mean_t{key}'] = m1
        r[f'mean_c{key}'] = m0
        r[f'smd{key}'] = (m1 - m0) / den if den > 0 else None
        r[f'vr{key}'] = (v1 / v0 if v0 > 0 else None) if not binary else None
    return r


def _covariate_frame(S):
    """The covariates of either model, as the page shows them: continuous
    columns as numbers, categorical ones with their levels."""
    cols = {}
    for name in S.both:
        d = S.dz if (S.dz is not None and name in S.dz.alias) else S.do
        a = d.alias[name]
        if a in d.categorical:
            cols[name] = ('cat', d.df[a], d.levels[a])
        else:
            cols[name] = ('num', d.df[a].to_numpy(float), None)
    return cols


def _balance(S, w_ate, w_att):
    ones = np.ones(len(S.t))
    weights = {'': ones, '_w': w_ate, '_att': w_att}
    out = []
    for name, (kind, s, lv) in _covariate_frame(S).items():
        if kind == 'cat':
            for v in lv:
                out.append(_balance_row(f'{name}[{_lvtext(v)}]', (s == v).to_numpy(float), True, S.t, weights))
        else:
            out.append(_balance_row(name, s, False, S.t, weights))
    return out


def _naive(S, alpha):
    from statsmodels.stats.weightstats import CompareMeans, DescrStatsW
    y1, y0 = S.y[S.t == 1], S.y[S.t == 0]
    cm = CompareMeans(DescrStatsW(y1), DescrStatsW(y0))
    z, p = cm.ztest_ind(usevar='unequal')
    lo, hi = cm.zconfint_diff(alpha=alpha, usevar='unequal')
    return {'estimate': float(y1.mean() - y0.mean()), 'se': float(cm.std_meandiff_separatevar), 'z': float(z), 'p': float(p),
            'lower': float(lo), 'upper': float(hi), 'mean_treated': float(y1.mean()), 'mean_control': float(y0.mean()),
            'n_treated': int(len(y1)), 'n_control': int(len(y0))}


# ---- the Python shown under the results ----------------------------------------------------

def _lit(v):
    v = _num(v)
    return J(v) if isinstance(v, str) else repr(v)


def _code_prep(S, table, table_name, rows, imports=()):
    """Read the CSV export, keep the report's rows, and fit the propensity
    model as the report does (with the trimming, when there is one)."""
    lines = [code_head(table_name, ['import patsy'] + list(imports))]
    if rows is not None:
        n = data.TABLES[table]['n']
        keep = sorted(int(r) for r in rows)
        if len(keep) > n / 2:
            drop = sorted(set(range(n)) - set(keep))
            if drop:
                lines.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
        else:
            lines.append(f'df = df.loc[{keep}]   # the rows of the report')
    cols = [S.y_name, S.t_name] + S.both
    lines.append(f'd = df[{J(cols)}].dropna()')
    tcol = f'd[{J(S.t_name)}]' if S.t_numeric else f'd[{J(S.t_name)}].astype(str)'
    lines.append(f't = ({tcol} == {_lit(S.treated) if S.t_numeric else J(str(_num(S.treated)))}).to_numpy(int)   '
                 f'# 1: treated ({S.t_name} = {_lvtext(S.treated)}), 0: control ({_lvtext(S.control)})')
    lines.append(f'y = d[{J(S.y_name)}].to_numpy(float)')
    fit = 'sm.Probit' if S.link == 'probit' else 'sm.Logit'
    if S.trim and S.trim['n_dropped']:
        e = S.trim['eps']
        lines.append(f'Z = patsy.dmatrix({J(S.trim["z_formula_before"])}, d)')
        lines.append(f'p = {fit}(t, Z).fit(disp=0).predict()')
        lines.append(f'keep = (p >= {e!r}) & (p <= 1 - {e!r})   # trimming: {S.trim["n_dropped"]} rows with a propensity score outside [ε, 1 − ε] go')
        lines.append('d, t, y = d[keep], t[keep], y[keep]')
    lines.append(f'Z = patsy.dmatrix({J(S.z_formula)}, d)   # the treatment (propensity) model, effect coded')
    lines.append(f'ps = {fit}(t, Z).fit(disp=0)   # the propensity score model' + (', refitted on the rows left' if S.trim and S.trim['n_dropped'] else ''))
    lines.append(f'X = patsy.dmatrix({J(S.x_formula)}, d)   # the outcome model (least squares in each group)')
    return lines


def _code_standardize(S):
    fit = 'sm.Probit' if S.link == 'probit' else 'sm.Logit'
    return ['def standardize(M):   # every column but the intercept centred and scaled to sd 1: the same model, with coefficients',
            '    M = np.asarray(M, dtype=float)   # near 1, which the GMM\'s derivatives (a fixed step of 1e-4) need',
            '    sd = M[:, 1:].std(0)',
            '    return np.column_stack([M[:, 0], (M[:, 1:] - M[:, 1:].mean(0)) / np.where(sd > 0, sd, 1.0)])',
            f'teff = TreatmentEffect(sm.OLS(y, standardize(X)), t, results_select={fit}(t, standardize(Z)).fit(disp=0))']


# ---- the entry points --------------------------------------------------------------------------

def _guard(fn):
    def run(*a, **k):
        try:
            return fn(*a, **k)
        except UserError as e:
            return {'error': str(e)}
    run.__name__ = fn.__name__
    run.__wrapped__ = fn
    import inspect
    run.__signature__ = inspect.signature(fn)
    return run


@api('treatment.fit')
@_guard
def fit(table, y, treatment, treated=None, outcome=None, covariates=None, rows=None, link='logit', trim=None, alpha=0.05, table_name='data'):
    """The sample, the propensity score model, the overlap of the scores, the
    covariate balance before and after weighting, the weights, and the
    unadjusted difference in means."""
    S = _sample(table, y, treatment, treated, outcome, covariates, rows, link, trim)
    w_ate, w_att, wsum = _weights(S)
    t, p = S.t, S.p
    lo = max(float(p[t == 1].min()), float(p[t == 0].min()))
    hi = min(float(p[t == 1].max()), float(p[t == 0].max()))
    outside = (p < lo) | (p > hi)
    overlap = {'treated': {'min': float(p[t == 1].min()), 'max': float(p[t == 1].max()), 'mean': float(p[t == 1].mean())},
               'control': {'min': float(p[t == 0].min()), 'max': float(p[t == 0].max()), 'mean': float(p[t == 0].mean())},
               'support': [lo, hi] if lo <= hi else None, 'n_outside': int(outside.sum()), 'rows_outside': [int(i) for i in S.idx[outside]],
               'n_outside_treated': int(np.sum(outside & (t == 1))), 'n_outside_control': int(np.sum(outside & (t == 0))),
               'n_clip': int(np.sum((p < 0.01) | (p > 0.99))), 'n_clip3': int(np.sum((p < 0.001) | (p > 0.999)))}
    binary = bool(np.all(np.isin(S.y, [0.0, 1.0])))
    out = {'n': int(len(t)), 'n_treated': int(t.sum()), 'n_control': int(len(t) - t.sum()), 'n_missing': S.n_missing,
           'treated': _num(S.treated), 'control': _num(S.control), 'treated_text': _lvtext(S.treated), 'control_text': _lvtext(S.control),
           'y': S.y_name, 'treatment': S.t_name, 'outcome': S.outcome, 'covariates': S.tcov, 'binary_y': binary,
           'trim': {k: v for k, v in S.trim.items() if k != 'z_formula_before'} if S.trim else None, 'propensity': _propensity(S, alpha), 'overlap': overlap, 'weights': wsum,
           'scores': {'rows': [int(i) for i in S.idx], 'ps': p, 't': t, 'w_ate': w_ate, 'w_att': w_att},
           'balance': _balance(S, w_ate, w_att), 'naive': _naive(S, alpha), 'alpha': alpha}
    lines = _code_prep(S, table, table_name, rows, ['from statsmodels.stats.weightstats import CompareMeans, DescrStatsW'])
    lines += ['print(ps.summary())',
              'p = ps.predict()   # the propensity scores',
              'w = t / p + (1 - t) / (1 - p)   # IPW weights (for the ATE)',
              'w_att = t + (1 - t) * p / (1 - p)   # weights for the effect on the treated',
              '',
              'def balance(x, w, binary):',
              '    """Treated minus control: the standardized mean difference and the variance ratio, with weights w."""',
              '    def mv(x, w):',
              '        m = np.average(x, weights=w)',
              '        if binary:',
              '            return m, m * (1 - m)',
              '        return m, np.sum(w * (x - m) ** 2) * w.sum() / (w.sum() ** 2 - np.sum(w ** 2))',
              '    (m1, v1), (m0, v0) = mv(x[t == 1], w[t == 1]), mv(x[t == 0], w[t == 0])',
              '    return (m1 - m0) / np.sqrt((v1 + v0) / 2), (None if binary else v1 / v0)',
              '',
              'covariates = {   # name: (values, whether a level\'s 0/1 indicator)']
    for name, (kind, s, lv) in _covariate_frame(S).items():
        if kind == 'cat':
            src = f'd[{J(name)}]' if all(isinstance(v, str) for v in lv) else f'd[{J(name)}].astype(float)'
            for v in lv:
                lines.append(f'    {J(f"{name}[{_lvtext(v)}]")}: (({src} == {_lit(v)}).to_numpy(float), True),')
        else:
            lines.append(f'    {J(name)}: (d[{J(name)}].to_numpy(float), False),')
    lines += ['}',
              'one = np.ones(len(t))',
              'smd = pd.DataFrame({name: [*balance(x, one, b), *balance(x, w, b)] for name, (x, b) in covariates.items()},',
              '                   index=["SMD", "Variance Ratio", "SMD (weighted)", "Variance Ratio (weighted)"]).T',
              'print(smd)',
              'cm = CompareMeans(DescrStatsW(y[t == 1]), DescrStatsW(y[t == 0]))',
              f'print(cm.summary(use_t=False, usevar="unequal", alpha={alpha!r}))   # the difference in means, unadjusted']
    out['code'] = '\n'.join(lines)
    return out


def _results_row(key, r, cf, alpha):
    ci = np.asarray(r.conf_int(alpha=alpha), dtype=float)
    parts = {}
    for j, name in enumerate(('ate', 'pom0', 'pom1')):
        parts[name] = {'estimate': float(r.effect[j]), 'se': float(r.sd[j]), 'z': float(r.statistic[j]), 'p': float(r.pvalue[j]),
                       'lower': float(ci[j, 0]), 'upper': float(ci[j, 1])}
    cf = np.asarray(cf, dtype=float).ravel()
    parts['closed_form'] = [float(v) for v in cf]
    parts['gmm_gap'] = float(np.max(np.abs(np.asarray(r.effect, dtype=float) - cf) / np.maximum(1.0, np.abs(cf))))
    return {'key': key, 'label': LABEL[key], **parts}


def _singular_groups(S):
    """The groups in which the outcome model's design is singular (a
    covariate constant there), with the columns to blame."""
    bad = []
    for g, name in ((1, 'treated'), (0, 'control')):
        Xg = S.X[S.t == g]
        if np.linalg.matrix_rank(Xg) < Xg.shape[1]:
            const = [S.x_labels[j] for j in range(1, Xg.shape[1]) if np.ptp(Xg[:, j]) == 0]
            bad.append({'group': name, 'n': int(len(Xg)), 'terms': const})
    return bad


@api('treatment.estimates')
@_guard
def estimates(table, y, treatment, treated=None, outcome=None, covariates=None, rows=None, link='logit', trim=None,
              estimators=None, effect_group='all', alpha=0.05, table_name='data'):
    """ATE and potential-outcome means (effect_group 'all') or the effect on
    the treated (effect_group 1) by each estimator, with statsmodels' GMM
    standard errors."""
    S = _sample(table, y, treatment, treated, outcome, covariates, rows, link, trim)
    att = effect_group not in ('all', None)
    keys = [k for k, _ in ESTIMATORS if (estimators is None or k in estimators) and (not att or k in ATT_OK)]
    teff = _teffect(S)
    bad = _singular_groups(S)
    out = []
    for k in keys:
        if k in USES_OUTCOME and bad:
            b = bad[0]
            out.append({'key': k, 'label': LABEL[k], 'error': f'the outcome model is singular among the {b["n"]} {b["group"]} rows'
                        + (f' ({", ".join(b["terms"])} constant there)' if b['terms'] else '') + ': take the covariate out of the outcome model'})
            continue
        kw = {'effect_group': 1} if att else {}
        try:
            with _right_slices():
                r = getattr(teff, k)(**kw)
                cf = getattr(teff, k)(return_results=False, **kw)
            out.append(_results_row(k, r, cf, alpha))
        except (np.linalg.LinAlgError, ValueError, ZeroDivisionError, FloatingPointError) as e:
            out.append({'key': k, 'label': LABEL[k], 'error': f'{type(e).__name__}: {e}'})
    p = S.p
    res = {'effect_group': 1 if att else 'all', 'estimates': out, 'alpha': alpha, 'n': int(len(S.t)),
           'n_clip': int(np.sum((p < 0.01) | (p > 0.99))), 'n_clip3': int(np.sum((p < 0.001) | (p > 0.999))),
           'k_select': int(S.Z.shape[1]), 'k_outcome': int(S.X.shape[1])}
    patch = any(k in ('aipw_wls', 'ipw_ra') for k in keys)
    lines = _code_prep(S, table, table_name, rows, (['import inspect', 'import statsmodels.treatment.treatment_effects as te'] if patch else [])
                       + ['from statsmodels.treatment.treatment_effects import TreatmentEffect'])
    if patch:
        lines += ['# statsmodels 0.14 takes the last six parameters as the propensity model\'s in the moment conditions of AIPW (WLS)',
                  f'# and IPW-RA, right only for a model with six (this one has {S.Z.shape[1]}); give them the ones after the outcome models\':',
                  'for name in ("_AIPWWLSGMM", "_IPWRAGMM"):',
                  '    src = inspect.getsource(getattr(te, name))',
                  '    exec(src.replace("params[-6:]", "params[2 * k + 1:]"), te.__dict__)']
    lines += _code_standardize(S)
    arg = 'effect_group=1' if att else ''
    lines.append('res = {' + ', '.join(f'{J(LABEL[k])}: teff.{k}({arg})' for k in keys) + '}')
    lines += ['for name, r in res.items():',
              '    print(name)',
              f'    print(r.summary_frame(alpha={alpha!r}))   # {"ATT (in the row ATE), POM0 and POM1 of the treated" if att else "ATE, POM0 and POM1"}: GMM standard errors']
    res['code'] = '\n'.join(lines)
    return res


@api('treatment.outcome_models')
@_guard
def outcome_models(table, y, treatment, treated=None, outcome=None, covariates=None, rows=None, link='logit', trim=None, alpha=0.05, table_name='data'):
    """The least squares outcome model in each treatment group, as
    TreatmentEffect fits them for RA and AIPW (HC0 standard errors)."""
    import statsmodels.api as sm
    S = _sample(table, y, treatment, treated, outcome, covariates, rows, link, trim)
    lv = f'{100 * (1 - alpha):g}%'
    groups = []
    bad = {b['group']: b for b in _singular_groups(S)}
    fits = [sm.OLS(S.y[S.t == g], S.X[S.t == g]).fit(cov_type='HC0') for g in (0, 1)]
    for name, r, level in (('control', fits[0], S.control), ('treated', fits[1], S.treated)):
        ci = np.asarray(r.conf_int(alpha), dtype=float)
        est = [{'term': S.x_labels[j], 'estimate': float(r.params[j]), 'se': float(r.bse[j]), 'z': float(r.tvalues[j]), 'p': float(r.pvalues[j]),
                'lower': float(ci[j, 0]), 'upper': float(ci[j, 1])} for j in range(len(S.x_labels))]
        groups.append({'group': name, 'level': _lvtext(level), 'n': int(r.nobs), 'rsquare': float(r.rsquared) if r.df_model > 0 else None,
                       'rmse': float(np.sqrt(r.mse_resid)) if r.df_resid > 0 else None, 'mean_y': float(np.mean(r.model.endog)),
                       'singular': name in bad,
                       'estimates': rtable([col('term', 'Term', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('z', 'z Ratio'),
                                            col('p', 'Prob>|z|', 'p'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}')], est)})
    lines = _code_prep(S, table, table_name, rows)
    lines += ['fits = {g: sm.OLS(y[t == g], np.asarray(X)[t == g]).fit(cov_type="HC0") for g in (0, 1)}   # as TreatmentEffect fits them',
              f'print(fits[0].summary(alpha={alpha!r}))   # control: least squares, HC0 standard errors',
              f'print(fits[1].summary(alpha={alpha!r}))   # treated']
    return {'groups': groups, 'code': '\n'.join(lines), 'alpha': alpha}
