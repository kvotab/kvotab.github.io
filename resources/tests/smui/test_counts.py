#!/usr/bin/env python3
"""Count Regression (resources/py/smui/counts.py) outside the browser.

Against statsmodels called directly, for every model family (Poisson, NB2,
NB1, generalized Poisson, zero-inflated Poisson, negative binomial and
generalized Poisson, hurdle Poisson and negative binomial): estimates,
standard errors, log-likelihood, AIC, AICc, BIC; means, variances, P(Y = 0)
and Pearson residuals against statsmodels' predict and resid_pearson; the
rootogram's expected frequencies as sums of predicted probabilities; the
Vuong statistic by its formula (as R's pscl::vuong) from statsmodels'
loglikeobs; the likelihood-ratio tests and their boundary p-values;
statsmodels' get_margeff; the profiler's predictions and delta-method
intervals; likelihood-ratio effect tests by refitting. Published values:
the RAND Health Insurance Experiment counts (statsmodels.datasets.randhie)
with the Stata and R results statsmodels' own tests use (Poisson, NB2, NB1,
ZIP, ZINB, ZIGP), and R pscl's hurdle Poisson of the docvis data. Freq
equals repeated rows; alpha at its bound, no zeros, bad counts and a
separated zero part give messages, not failures. Every model's Python code,
and the comparison's, runs on a CSV export and gives the report's numbers.

Run with a Python that has numpy, scipy, pandas, patsy and statsmodels 0.14:

    python3 resources/tests/smui/test_counts.py
"""
import contextlib
import io
import math
import os
import re
import sys
import tempfile
import time
import warnings

import numpy as np
import pandas as pd
import patsy
from scipy import stats

import statsmodels.api as sm
from statsmodels.discrete.count_model import ZeroInflatedGeneralizedPoisson, ZeroInflatedNegativeBinomialP, ZeroInflatedPoisson
from statsmodels.discrete.discrete_model import GeneralizedPoisson, NegativeBinomial, Poisson
from statsmodels.discrete.truncated_model import HurdleCountModel, TruncatedLFNegativeBinomialP, TruncatedLFPoisson

from backend import FAILED, Checks, call, table

warnings.simplefilter('ignore')
check = Checks()
check('counts imports', FAILED.get('counts'), None)
from smui import counts  # noqa: E402

tmp = tempfile.mkdtemp(prefix='smui-counts-')
ALL = counts.ORDER


def run_code(code, frame, name):
    """Write frame as the page exports it (File > Export CSV) and run code there."""
    frame.to_csv(os.path.join(tmp, f'{name}.csv'), index=False)
    ns = {}
    here = os.getcwd()
    os.chdir(tmp)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(code, ns)
        return ns, None
    except Exception as e:  # reported as a failed check
        return ns, f'{type(e).__name__}: {e}'
    finally:
        os.chdir(here)


def rows_of(t):
    return {r['term']: r for r in t['rows']}


def jmp(name):
    """JMP's name of a patsy column of this file's formulas."""
    m = re.fullmatch(r"C\((\w+), Sum.*\)\[S\.(.+)\]", name)
    return f'{m.group(1)}[{m.group(2)}]' if m else name


def maxdiff(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.max(np.abs(a - b))) if a.shape == b.shape and a.size else float('inf')


def near_all(label, got, want, rel=1e-6, abs_=1e-9):
    got, want = np.asarray(got, float), np.asarray(want, float)
    ok = got.shape == want.shape and bool(np.all(np.abs(got - want) <= np.maximum(abs_, rel * np.maximum(1, np.abs(want)))))
    return check(f'{label} (max diff {maxdiff(got, want):.2g})', ok)


# ---------------------------------------------------------------------------
# simulated data: a zero-inflated negative binomial with an exposure
# ---------------------------------------------------------------------------
rng = np.random.default_rng(20260926)
n = 600
age = rng.integers(18, 85, n).astype(float)
sex = rng.choice(['F', 'M'], n)
region = rng.choice(['east', 'north', 'south'], n, p=[0.3, 0.45, 0.25])
years = np.round(rng.uniform(0.5, 3.0, n), 1)
mu = years * np.exp(0.2 + 0.012 * (age - 50) + 0.25 * (sex == 'F') - 0.3 * (region == 'south'))
lam = rng.gamma(1 / 0.6, 0.6 * mu)
visits = rng.poisson(lam).astype(float)
pi = 1 / (1 + np.exp(-(-1.2 + 1.0 * (region == 'east') - 0.02 * (age - 50))))
visits[rng.uniform(size=n) < pi] = 0
LV = {'sex': ['F', 'M'], 'region': ['east', 'north', 'south']}
frame = pd.DataFrame({'age': age, 'sex': sex, 'region': region, 'years': years, 'visits': visits})
tid = table({c: frame[c].tolist() for c in frame.columns}, levels=LV)
X_EFF = ['age', 'sex', 'region']
BASE = dict(table=tid, y='visits', x=X_EFF, exposure='years')
FORM = "age + C(sex, Sum, levels=['F', 'M']) + C(region, Sum, levels=['east', 'north', 'south'])"
Xd = patsy.dmatrix(FORM, frame, return_type='dataframe')
yv, off = frame['visits'].to_numpy(), np.log(frame['years'].to_numpy())
BF = dict(method='bfgs', maxiter=1000, gtol=1e-8, disp=0)


def direct(key, X=Xd, Z=None, y=yv, offset=off):
    """The model fitted by statsmodels here, independently of the backend:
    (params in statsmodels' order, bse, llf, results or parts)."""
    Z = X if Z is None else Z
    kw = {} if offset is None else {'offset': offset}
    if key == 'poisson':
        r = Poisson(y, X, **kw).fit(method='newton', maxiter=100, disp=0)
    elif key in ('nb2', 'nb1'):
        r = NegativeBinomial(y, X, loglike_method=key, **kw).fit(**BF)
        r = r.model.fit(start_params=r.params, method='newton', maxiter=50, disp=0)
    elif key == 'gp':
        r = GeneralizedPoisson(y, X, p=1, **kw).fit(method='newton', maxiter=100, disp=0)
    elif key == 'zip':
        r = ZeroInflatedPoisson(y, X, exog_infl=Z, inflation='logit', **kw).fit(**BF)
        r = r.model.fit(start_params=r.params, method='newton', maxiter=50, disp=0)
    elif key in ('zinb', 'zigp'):
        z = direct('zip', X, Z, y, offset)[3]
        cls = ZeroInflatedNegativeBinomialP if key == 'zinb' else ZeroInflatedGeneralizedPoisson
        r = cls(y, X, exog_infl=Z, p=2 if key == 'zinb' else 1, **kw).fit(start_params=np.append(z.params, 0.5 if key == 'zinb' else 0.1), **BF)
    else:
        g = sm.GLM((y > 0).astype(float), Z, family=sm.families.Binomial(link=sm.families.links.CLogLog()), offset=offset).fit(maxiter=100)
        g = g.model.fit(start_params=g.params, method='newton', maxiter=100)
        tp = TruncatedLFPoisson(y, X, **kw).fit(method='newton', maxiter=100, disp=0)
        if key == 'hp':
            c = tp
        else:
            c = TruncatedLFNegativeBinomialP(y, X, p=2, **kw).fit(start_params=np.append(tp.params, 0.5), method='newton', maxiter=100, disp=0)
        return (np.concatenate([np.asarray(g.params), np.asarray(c.params)]), np.concatenate([np.asarray(g.bse), np.asarray(c.bse)]),
                float(g.llf + c.llf), (g, c))
    return np.asarray(r.params, float), np.asarray(r.bse, float), float(r.llf), r


# ---- every model family against statsmodels directly ---------------------------------------------
t0 = time.time()
FITS = {}
for key in ALL:
    r = call('counts.fit', model=key, **BASE)
    FITS[key] = r
    check(f'{key}: fits', r.get('error'), None)
    if r.get('error'):
        continue
    p, se, llf, _res = direct(key)
    m = counts._get(tid, None, counts._spec('visits', X_EFF, 1, [], True, 'years', None, None), key)
    near_all(f'{key}: estimates = statsmodels\'', m['params'], p, rel=2e-5, abs_=2e-6)
    near_all(f'{key}: standard errors = statsmodels\'', np.sqrt(np.diag(m['cov'])), se, rel=2e-4, abs_=1e-6)
    check.near(f'{key}: log-likelihood = statsmodels\'', r['llf'], llf, rel=1e-9)
    k = len(p)
    check(f'{key}: k counts every parameter', r['k'], k)
    check.near(f'{key}: AIC = -2 llf + 2k', r['aic'], -2 * llf + 2 * k, rel=1e-9)
    check.near(f'{key}: AICc = AIC + 2k(k+1)/(n-k-1)', r['aicc'], -2 * llf + 2 * k + 2 * k * (k + 1) / (n - k - 1), rel=1e-9)
    check.near(f'{key}: BIC = -2 llf + k log n', r['bic'], -2 * llf + k * math.log(n), rel=1e-9)
    check(f'{key}: converged, no warnings', (r['converged'], r['warn']), (True, []))
    # the report's table: the count part by JMP's term names
    est = rows_of(r['estimates']['count'])
    names = list(Xd.columns)
    sl = m['parts']['count']
    check(f'{key}: the count part\'s terms are JMP\'s', sorted(est), sorted(jmp(c) for c in names))
    bad = [c for j, c in enumerate(names) if abs(est[jmp(c)]['estimate'] - p[sl][j]) > 2e-5 * max(1, abs(p[sl][j]))]
    check(f'{key}: the count part\'s table = the estimates', bad, [])
print(f'  ({time.time() - t0:.1f} s for the nine models)')

# the parameterizations: NB1's variance, GP's, JMP's NB sigma
check('the NB2 variance is mu + alpha mu^2 (JMP\'s sigma is alpha)', 'Var(Y) = μ + αμ²' in counts.VARIANCE['nb2'], True)

# ---- the fitted distributions against statsmodels' predictions -------------------------------------
spec = counts._spec('visits', X_EFF, 1, [], True, 'years', None, None)
for key in ALL:
    m = counts._get(tid, None, spec, key)
    D = m['D']
    ll = D.logpmf(yv)
    check.near(f'{key}: the log-probabilities of the rows sum to the log-likelihood', float(np.sum(ll)), m['llf'], rel=1e-10)
    if key in counts.ZERO and counts.ZERO[key] == 'hurdle':
        continue
    mod = m['res'].model
    b = np.asarray(m['res'].params, float)
    near_all(f'{key}: E[Y] = statsmodels\' predict(which="mean")', D.mean(), mod.predict(b, which='mean'), rel=1e-9)
    near_all(f'{key}: Var(Y) = statsmodels\' predict(which="var")', D.var(), mod.predict(b, which='var'), rel=1e-8)
    near_all(f'{key}: Pearson residuals = statsmodels\' resid_pearson', m['pearson'], m['res'].resid_pearson, rel=1e-8)
    if key in counts.ZERO:
        near_all(f'{key}: P(Y = 0) = statsmodels\' predict(which="prob-zero")', D.p0(), mod.predict(b, which='prob-zero'), rel=1e-9)
# the rootogram's expected frequencies: sums of the predicted probabilities (scipy's pmf of statsmodels' means)
r = FITS['poisson']
muP = counts._get(tid, None, spec, 'poisson')['res'].predict()
K = len(r['dist']['k']) - 1
want = [stats.poisson.pmf(j, muP).sum() for j in range(K)]
near_all('Poisson: expected frequencies = sums of scipy\'s pmf at the fitted means', r['dist']['expected'][:K], want, rel=1e-9)
nb = counts._get(tid, None, spec, 'nb2')['res']
a = float(nb.params[-1])
want = [stats.nbinom.pmf(j, 1 / a, 1 / (1 + a * nb.predict())).sum() for j in range(K)]
near_all('NB2: expected frequencies = sums of the NB2 pmf', FITS['nb2']['dist']['expected'][:K], want, rel=1e-9)
check('observed frequencies = the counts of each value', FITS['poisson']['dist']['observed'][:K], [float(np.sum(yv == j)) for j in range(K)])
if FITS['poisson']['dist']['tail']:
    check('the last bin holds the counts above it', FITS['poisson']['dist']['observed'][K], float(np.sum(yv >= K)))
check.near('Poisson: expected zeros = sum of exp(-mu)', FITS['poisson']['zeros']['predicted'], float(np.sum(np.exp(-muP))), rel=1e-10)

# ---- the hurdle model against statsmodels' HurdleCountModel (no exposure, the same effects) -----------
B0 = dict(table=tid, y='visits', x=X_EFF)
spec0 = counts._spec('visits', X_EFF, 1, [], True, None, None, None)
for key, dist in (('hp', 'poisson'), ('hnb', 'negbin')):
    r = call('counts.fit', model=key, **B0)
    h = HurdleCountModel(yv, Xd, dist=dist).fit(method='newton', maxiter=300, disp=0)
    m = counts._get(tid, None, spec0, key)
    near_all(f'{key}: estimates = HurdleCountModel\'s', m['params'], np.asarray(h.params), rel=1e-5, abs_=1e-6)
    near_all(f'{key}: standard errors = HurdleCountModel\'s', np.sqrt(np.diag(m['cov'])), np.asarray(h.bse), rel=1e-4, abs_=1e-6)
    check.near(f'{key}: log-likelihood = HurdleCountModel\'s', r['llf'], float(h.llf), rel=1e-9)
    check.near(f'{key}: AIC = HurdleCountModel\'s', r['aic'], float(h.aic), rel=1e-9)
    b = np.asarray(h.params)
    near_all(f'{key}: E[Y] = HurdleCountModel.predict(which="mean")', m['mean'], h.model.predict(b, which='mean'), rel=1e-5)
    near_all(f'{key}: P(Y = 0) = HurdleCountModel.predict(which="prob-zero")', m['p0'], h.model.predict(b, which='prob-zero'), rel=1e-5)
    near_all(f'{key}: Var(Y) = HurdleCountModel.predict(which="var")', m['var'], h.model.predict(b, which='var'), rel=1e-5)
    Kh = len(r['dist']['k']) - 1
    pr = h.model.predict(b, which='prob', y_values=np.arange(Kh))
    near_all(f'{key}: expected frequencies = sums of HurdleCountModel\'s predict(which="prob")', r['dist']['expected'][:Kh], pr.sum(0), rel=1e-4)
    near_all(f'{key}: Pearson residuals = HurdleCountModel\'s resid_pearson', m['pearson'], h.resid_pearson, rel=1e-4, abs_=1e-6)

# ---- published values: RAND HIE (Stata and R, from statsmodels' own tests) -----------------------------
try:
    from statsmodels.discrete.tests.results.results_discrete import RandHIE
except Exception:  # noqa: BLE001 - a statsmodels install without its tests
    RandHIE = None
if RandHIE is None:
    print('  (statsmodels\' test results are not installed: the RAND HIE checks are skipped)')
else:
    t0 = time.time()
    rh = sm.datasets.randhie.load_pandas().data
    rtid = table({c: rh[c].astype(float).tolist() for c in rh.columns})
    XR = ['lncoins', 'idp', 'lpi', 'fmde', 'physlm', 'disea', 'hlthg', 'hlthf', 'hlthp']

    def order_stata(r, xs, zs=None, alpha=False):
        """The report's estimates in the order of statsmodels' tests: the
        zero part (regressors, const), the count part (regressors, const), alpha."""
        out = []
        if zs is not None:
            e = rows_of(r['estimates']['zero'])
            out += [e[c]['estimate'] for c in zs] + [e['Intercept']['estimate']]
        e = rows_of(r['estimates']['count'])
        out += [e[c]['estimate'] for c in xs] + [e['Intercept']['estimate']]
        if alpha:
            out.append(r['estimates']['alpha']['rows'][0]['estimate'])
        return out

    def se_stata(r, xs):
        e = rows_of(r['estimates']['count'])
        return [e[c]['se'] for c in xs] + [e['Intercept']['se']]

    r = call('counts.fit', table=rtid, y='mdvis', x=XR, model='poisson')
    near_all('RAND HIE Poisson: estimates = Stata\'s', order_stata(r, XR), RandHIE.poisson.params, rel=1e-6)
    near_all('RAND HIE Poisson: standard errors = Stata\'s', se_stata(r, XR), RandHIE.poisson.bse, rel=1e-5)
    check.near('RAND HIE Poisson: log-likelihood = Stata\'s (its printed digits)', r['llf'], RandHIE.poisson.llf, rel=1e-9)
    check.near('RAND HIE Poisson: AIC = Stata\'s', r['aic'], RandHIE.poisson.aic, rel=1e-9)
    check.near('RAND HIE Poisson: BIC = Stata\'s', r['bic'], RandHIE.poisson.bic, rel=1e-9)
    r = call('counts.fit', table=rtid, y='mdvis', x=XR, model='nb2')
    near_all('RAND HIE NB2: estimates and alpha = Stata\'s', order_stata(r, XR, alpha=True), RandHIE.negativebinomial_nb2_bfgs.params, rel=1e-5)
    near_all('RAND HIE NB2: standard errors = Stata\'s', se_stata(r, XR), RandHIE.negativebinomial_nb2_bfgs.bse[:10], rel=2e-3)
    check.near('RAND HIE NB2: log-likelihood = Stata\'s', r['llf'], RandHIE.negativebinomial_nb2_bfgs.llf, rel=1e-9)
    check.near('RAND HIE NB2: AIC = Stata\'s', r['aic'], RandHIE.negativebinomial_nb2_bfgs.aic, rel=1e-9)
    r = call('counts.fit', table=rtid, y='mdvis', x=XR, model='nb1')
    near_all('RAND HIE NB1: estimates and alpha = the reference\'s', order_stata(r, XR, alpha=True), RandHIE.negativebinomial_nb1_bfgs.params, rel=2e-4, abs_=2e-4)
    check.near('RAND HIE NB1: log-likelihood = the reference\'s', r['llf'], RandHIE.negativebinomial_nb1_bfgs.llf, rel=1e-8)
    XZ, ZZ = ['idp', 'lpi', 'fmde'], ['lncoins']
    r = call('counts.fit', table=rtid, y='mdvis', x=XZ, zx=ZZ, model='zip')
    near_all('RAND HIE ZIP: estimates = Stata\'s zip', order_stata(r, XZ, ZZ), RandHIE.zero_inflated_poisson_logit.params, rel=1e-5, abs_=1e-6)
    ez = r['estimates']
    near_all('RAND HIE ZIP: standard errors = Stata\'s', [rows_of(ez['zero'])['lncoins']['se'], rows_of(ez['zero'])['Intercept']['se']]
             + [rows_of(ez['count'])[c]['se'] for c in XZ] + [rows_of(ez['count'])['Intercept']['se']], RandHIE.zero_inflated_poisson_logit.bse, rel=2e-4)
    check.near('RAND HIE ZIP: log-likelihood = Stata\'s', r['llf'], RandHIE.zero_inflated_poisson_logit.llf, rel=1e-9)
    check.near('RAND HIE ZIP: AIC = Stata\'s', r['aic'], RandHIE.zero_inflated_poisson_logit.aic, rel=1e-8)
    r = call('counts.fit', table=rtid, y='mdvis', x=XZ, zx=ZZ, model='zigp')
    check.near('RAND HIE ZIGP: log-likelihood = Stata\'s', r['llf'], RandHIE.zero_inflated_generalized_poisson.llf, rel=2e-6)
    near_all('RAND HIE ZIGP: the count part and alpha = Stata\'s', order_stata(r, XZ, ZZ, alpha=True)[2:], RandHIE.zero_inflated_generalized_poisson.params[2:], rel=2e-3, abs_=2e-3)
    r = call('counts.fit', table=rtid, y='mdvis', x=['idp'], zx=ZZ, model='zinb')
    check('RAND HIE ZINB: fits', r.get('error'), None)
    if not r.get('error'):
        check.near('RAND HIE ZINB: log-likelihood = Stata\'s', r['llf'], RandHIE.zero_inflated_negative_binomial.llf, rel=2e-6)
        near_all('RAND HIE ZINB: the count part and alpha = Stata\'s', order_stata(r, ['idp'], ZZ, alpha=True)[2:], RandHIE.zero_inflated_negative_binomial.params[2:], rel=2e-3, abs_=2e-3)
    print(f'  ({time.time() - t0:.1f} s for RAND HIE)')

# ---- published values: R pscl's hurdle Poisson of the docvis data -------------------------------------
try:
    from statsmodels.discrete.tests.results import results_truncated as rt_
    from statsmodels.sandbox.regression.tests.test_gmm_poisson import DATA as DOC
except Exception:  # noqa: BLE001
    DOC = None
if DOC is None:
    print('  (statsmodels\' test data are not installed: the docvis hurdle checks are skipped)')
else:
    dtid = table({c: DOC[c].astype(float).tolist() for c in ('docvis', 'aget', 'totchr')})
    r = call('counts.fit', table=dtid, y='docvis', x=['aget', 'totchr'], model='hp')
    ref = rt_.hurdle_poisson
    check.near('docvis hurdle Poisson: log-likelihood = R pscl\'s', r['llf'], ref.loglik, rel=1e-9)
    check.near('docvis hurdle Poisson: AIC = R pscl\'s', r['aic'], ref.aic, rel=1e-9)
    check.near('docvis hurdle Poisson: BIC = R pscl\'s', r['bic'], ref.bic, rel=1e-9)
    ez, ec = rows_of(r['estimates']['zero']), rows_of(r['estimates']['count'])
    got = [ez['Intercept']['estimate'], ez['aget']['estimate'], ez['totchr']['estimate'], ec['Intercept']['estimate'], ec['aget']['estimate'], ec['totchr']['estimate']]
    near_all('docvis hurdle Poisson: estimates = R pscl\'s (zero part, count part)', got, ref.params_table[:, 0], rel=1e-4, abs_=2e-5)
    got = [ez['Intercept']['se'], ez['aget']['se'], ez['totchr']['se'], ec['Intercept']['se'], ec['aget']['se'], ec['totchr']['se']]
    near_all('docvis hurdle Poisson: standard errors = R pscl\'s', got, ref.params_table[:, 1], rel=1e-4, abs_=1e-6)
    pr = call('counts.profile', table=dtid, y='docvis', x=['aget', 'totchr'], model='hp', current={'aget': float(DOC['aget'].mean()), 'totchr': float(DOC['totchr'].mean())})
    check.near('docvis hurdle Poisson: the mean at the means = R pscl\'s predict', pr['responses'][0]['current']['pred'], ref.predict_mean, rel=1e-5)
    check.near('docvis hurdle Poisson: P(0) at the means = R pscl\'s predict(type="prob")[0]', pr['responses'][1]['current']['pred'], ref.predict_prob[0], rel=1e-4)

# ---- Model Comparison: the Vuong statistic by its formula, the likelihood ratio tests ----------------------
c = call('counts.compare', which=ALL, **BASE)
check('compare: every model', [x['model'] for x in c['models']], ALL)
check('compare: none failed', c['failed'], [])
byk = {x['model']: x for x in c['models']}
for key in ALL:
    check.near(f'compare: {key} -2LL = the fit\'s', byk[key]['m2ll'], FITS[key]['m2ll'], rel=1e-12)
    check.near(f'compare: {key} dispersion = Pearson chi2/(n - k)', byk[key]['dispersion'], FITS[key]['pearson']['ratio'], rel=1e-12)
check.near('compare: AICc weights sum to 1', sum(x['weight'] for x in c['models']), 1.0, rel=1e-12)


def pscl_vuong(l1, l2, k1, k2):
    m = l1 - l2
    nn = len(m)
    s = np.std(m, ddof=1)
    return [(m.sum() - cc) / (s * math.sqrt(nn)) for cc in (0, k1 - k2, (k1 - k2) * math.log(nn) / 2)]


ll = {}
for key in ('poisson', 'nb2', 'zip', 'zinb'):
    res = direct(key)[3]
    ll[key] = (res.model.loglikeobs(np.asarray(res.params, float)), len(res.params))
vu = {(v['s1'], v['s2']): v for v in c['vuong']}
for a_, b_ in (('zip', 'poisson'), ('zinb', 'nb2'), ('zip', 'nb2'), ('zinb', 'poisson')):
    z = pscl_vuong(ll[a_][0], ll[b_][0], ll[a_][1], ll[b_][1])
    v = vu[(counts.SHORT[a_], counts.SHORT[b_])]
    near_all(f'Vuong {counts.SHORT[a_]} vs {counts.SHORT[b_]}: raw, AIC and BIC z = pscl\'s formula', [v['z'], v['z_aic'], v['z_bic']], z, rel=1e-4, abs_=1e-4)
    check.near(f'Vuong {counts.SHORT[a_]} vs {counts.SHORT[b_]}: one-sided p = Phi(-|z|)', v['p_aic'], float(stats.norm.sf(abs(z[1]))), rel=1e-3, abs_=1e-12)
lr = {x['test']: x for x in c['lr']}
check('LR tests: the nested pairs', sorted(lr), sorted(['Poisson vs NB2', 'Poisson vs NB1', 'Poisson vs GP', 'Poisson vs Hurdle P', 'ZIP vs ZINB', 'ZIP vs ZIGP', 'Hurdle P vs Hurdle NB']))
s_ = 2 * (FITS['nb2']['llf'] - FITS['poisson']['llf'])
check.near('LR Poisson vs NB2: 2 (llf NB2 - llf Poisson)', lr['Poisson vs NB2']['lr'], s_, rel=1e-12)
check.near('LR Poisson vs NB2: alpha = 0 on the boundary, half the chi2(1) p-value', lr['Poisson vs NB2']['p'], 0.5 * float(stats.chi2.sf(s_, 1)), rel=1e-9, abs_=1e-300)
s_ = 2 * (FITS['gp']['llf'] - FITS['poisson']['llf'])
check.near('LR Poisson vs GP: an interior restriction, the full chi2(1) p-value', lr['Poisson vs GP']['p'], float(stats.chi2.sf(s_, 1)), rel=1e-9, abs_=1e-300)
check('LR Poisson vs hurdle Poisson: the zero part\'s parameters, df', lr['Poisson vs Hurdle P']['df'], Xd.shape[1])
check('Vuong: not for the nested pairs', any((v['s1'], v['s2']) == ('NB2', 'Poisson') for v in c['vuong']), False)

# ---- Freq: a row counted f times is f rows ------------------------------------------------------------------
fr = np.where(np.arange(n) % 7 == 0, 3, np.where(np.arange(n) % 5 == 0, 2, 1)).astype(float)
ftid = table({**{c: frame[c].tolist() for c in frame.columns}, 'f': fr.tolist()}, levels=LV)
rep = np.repeat(np.arange(n), fr.astype(int))
etid = table({c: frame[c].to_numpy()[rep].tolist() for c in frame.columns}, levels=LV)
for key in ('poisson', 'zinb', 'hnb'):
    a1 = call('counts.fit', model=key, table=ftid, y='visits', x=X_EFF, exposure='years', freq='f')
    a2 = call('counts.fit', model=key, table=etid, y='visits', x=X_EFF, exposure='years')
    check.near(f'Freq {key}: log-likelihood = the repeated rows\'', a1['llf'], a2['llf'], rel=1e-9)
    near_all(f'Freq {key}: estimates = the repeated rows\'', [x['estimate'] for x in a1['estimates']['count']['rows']], [x['estimate'] for x in a2['estimates']['count']['rows']], rel=1e-6)
    near_all(f'Freq {key}: observed and expected frequencies = the repeated rows\'', a1['dist']['observed'] + a1['dist']['expected'], a2['dist']['observed'] + a2['dist']['expected'], rel=1e-6)
    check(f'Freq {key}: n is the sum of Freq, the rows are the table\'s', (a1['n'], len(a1['rows'])), (float(fr.sum()), n))
c1 = call('counts.compare', which=['poisson', 'zip'], table=ftid, y='visits', x=X_EFF, exposure='years', freq='f')
c2 = call('counts.compare', which=['poisson', 'zip'], table=etid, y='visits', x=X_EFF, exposure='years')
check.near('Freq: the Vuong z = the repeated rows\'', c1['vuong'][0]['z'], c2['vuong'][0]['z'], rel=1e-6)
bad = call('counts.fit', model='poisson', table=table({'y': [0.0, 1, 2, 3], 'f': [1, 1.5, 1, 1]}), y='y', freq='f')
check('Freq must be whole numbers', 'whole numbers' in (bad.get('error') or ''), True)

# ---- alpha at its bound, no zeros, bad counts, separation: messages, not failures ------------------------------
rng2 = np.random.default_rng(7)
x1 = rng2.normal(size=400)
yp = rng2.poisson(np.exp(0.5 + 0.4 * x1)).astype(float)
ptid = table({'x': x1.tolist(), 'y': yp.tolist()})
r = call('counts.fit', model='nb2', table=ptid, y='y', x=['x'])
rp = call('counts.fit', model='poisson', table=ptid, y='y', x=['x'])
check('Poisson data: NB2 goes to alpha = 0', r['boundary'], 'alpha')
check.near('Poisson data: the NB2 is the Poisson', r['llf'], rp['llf'], rel=1e-8)
check('Poisson data: alpha = 0 is said', any('lower bound 0' in w for w in r['warn']), True)
check('Poisson data: alpha 0 shown without a standard error', (r['estimates']['alpha']['rows'][0]['estimate'], r['estimates']['alpha']['rows'][0]['se']), (0.0, None))
check('Poisson data: NB2 k without alpha', r['k'], 2)
cc = call('counts.compare', which=['poisson', 'nb2', 'zip', 'zinb', 'hp', 'hnb'], table=ptid, y='y', x=['x'])
lrp = {x['test']: x for x in cc['lr']}
check('Poisson data: the LR test of alpha = 0 is 0 with p = 1', (round(lrp['Poisson vs NB2']['lr'], 6), lrp['Poisson vs NB2']['p']), (0.0, 1.0))
check('Poisson data: every model still reports', cc['failed'], [])
m1 = call('counts.margeff', model='nb2', table=ptid, y='y', x=['x'])
m2 = call('counts.margeff', model='poisson', table=ptid, y='y', x=['x'])
check('Poisson data: the NB2\'s marginal effects are the Poisson\'s', [x['effect'] for x in m1['table']['rows']], [x['effect'] for x in m2['table']['rows']])
zb = call('counts.fit', model='zinb', table=ptid, y='y', x=['x'])
check('Poisson data: the ZINB goes to alpha = 0 (it is the ZIP)', zb['boundary'], 'alpha')
zp = call('counts.fit', model='zip', table=ptid, y='y', x=['x'])
check.near('Poisson data: the ZINB at alpha = 0 is the ZIP', zb['llf'], zp['llf'], rel=1e-7)
ntid = table({'x': x1[:100].tolist(), 'y': (yp[:100] + 1).tolist()})
check('no zeros: the zero-inflated model says so', 'no zeros' in (call('counts.fit', model='zip', table=ntid, y='y', x=['x']).get('error') or ''), True)
check('no zeros: the Poisson fits', call('counts.fit', model='poisson', table=ntid, y='y', x=['x']).get('error'), None)
cn = call('counts.compare', which=['poisson', 'zip', 'hp'], table=ntid, y='y', x=['x'])
check('no zeros: the comparison leaves the zero models out', [f['model'] for f in cn['failed']], ['zip', 'hp'])
btid = table({'y': [0.0, 1, 2.5, 3], 'x': [1.0, 2, 3, 4]})
check('a Y that is not a count is refused', 'whole numbers' in (call('counts.fit', model='poisson', table=btid, y='y', x=['x']).get('error') or ''), True)
check('... in the comparison too', 'whole numbers' in (call('counts.compare', which=['poisson'], table=btid, y='y', x=['x']).get('error') or ''), True)
etid2 = table({'y': [0.0, 1, 2, 3], 'x': [1.0, 2, 3, 4], 't': [1.0, 0, 2, 1]})
check('an exposure of 0 is refused', 'above zero' in (call('counts.fit', model='poisson', table=etid2, y='y', x=['x'], exposure='t').get('error') or ''), True)
# a zero part with a level where every count is zero: the inflation runs off; a warning, no failure
g = np.where(np.arange(300) < 60, 'A', np.where(np.arange(300) < 180, 'B', 'C'))
ys = rng2.poisson(2.0, 300).astype(float)
ys[g == 'A'] = 0
stid = table({'g': list(g), 'y': ys.tolist()})
r = call('counts.fit', model='zip', table=stid, y='y', x=[], zx=['g'])
check('separation: the zip reports', r.get('error'), None)
check('separation: its zero part is flagged', any('beyond ±12' in w or 'Hessian' in w for w in r['warn']), True)
r = call('counts.fit', model='hp', table=stid, y='y', x=['g'])
check('separation: the hurdle reports', r.get('error'), None)

# ---- effects: crossings, a zero part of its own, Intercept only, JMP's intercept at x = 0 --------------------------
r = call('counts.fit', model='zip', x=['age', 'sex'], degree=2, zx=['region'], table=tid, y='visits', exposure='years')
sF = np.where(frame['sex'] == 'F', 1.0, -1.0)   # JMP's effect coding of sex, by hand: the crossing centred, the main effect not
Xc = pd.DataFrame({'Intercept': 1.0, 'sex[F]': sF, 'age': frame['age'], 'cross': (frame['age'] - frame['age'].mean()) * sF})
Zc = patsy.dmatrix("C(region, Sum, levels=['east', 'north', 'south'])", frame, return_type='dataframe')
p, se, llf, res = direct('zip', Xc, Zc)
check.near('crossing, zero effects of its own: log-likelihood = statsmodels\'', r['llf'], llf, rel=1e-8)
e = rows_of(r['estimates']['count'])
check.near('crossing: the Intercept is JMP\'s, at age = 0', e['Intercept']['estimate'], float(res.params['Intercept']), rel=1e-5)
check.near('crossing: its standard error too', e['Intercept']['se'], float(res.bse['Intercept']), rel=1e-4)
cross = [t for t in e if '*' in t]
check('crossing: JMP\'s name of the centred crossing', len(cross) == 1 and cross[0].startswith('(age-') and cross[0].endswith(')*sex[F]'), True)
check('the zero part has its own terms', sorted(rows_of(r['estimates']['zero'])), ['Intercept', 'region[east]', 'region[north]'])
r = call('counts.fit', model='zinb', zero_same=False, **BASE)
check('Intercept only: the zero part is a constant', sorted(rows_of(r['estimates']['zero'])), ['Intercept'])
p, se, llf, _ = direct('zinb', Xd, Xd[['Intercept']])
check.near('Intercept only: log-likelihood = statsmodels\'', r['llf'], llf, rel=1e-8)

# ---- effect tests: Wald, and likelihood ratio by refitting ------------------------------------------------------
r = FITS['zinb']
m = counts._get(tid, None, spec, 'zinb')
res = m['res']
cols = [j for j, cname in enumerate(Xd.columns) if cname.startswith('C(region')]
kz = Xd.shape[1]
idx = [kz + j for j in cols]
bb, VV = np.asarray(res.params)[idx], np.asarray(res.cov_params())[np.ix_(idx, idx)]
wald = float(bb @ np.linalg.solve(VV, bb))
et = {x['source']: x for x in r['effects']['count']['rows']}
check.near('Wald test of region (count part) = b\' V^-1 b', et['region']['stat'], wald, rel=1e-8)
check('Wald test: DF', et['region']['df'], 2)
le = call('counts.lr_effects', model='poisson', **BASE)
Xr = Xd.drop(columns=[cname for cname in Xd.columns if cname.startswith('C(region')])
red = Poisson(yv, Xr, offset=off).fit(method='newton', maxiter=100, disp=0)
lrt = {x['source']: x for x in le['effects']['count']['rows']}
check.near('LR effect test of region = 2 (llf - llf without region)', lrt['region']['stat'], 2 * (FITS['poisson']['llf'] - red.llf), rel=1e-7)
le = call('counts.lr_effects', model='hp', **BASE)
check('LR effect tests of the hurdle: both parts', sorted(le['effects']), ['count', 'zero'])

# ---- rate ratios -----------------------------------------------------------------------------------------------------
R = FITS['poisson']['ratios']['count']
b = counts._get(tid, None, spec, 'poisson')['res'].params
bi = dict(zip(Xd.columns, np.asarray(b)))
u = {x['term']: x for x in R['unit']}
check.near('unit rate ratio of age = exp(b)', u['age']['ratio'], math.exp(bi['age']), rel=1e-12)
lvr = {(x['term'], x['level1'], x['level2']): x for x in R['levels']}
bs = bi["C(region, Sum, levels=['east', 'north', 'south'])[S.east]"], bi["C(region, Sum, levels=['east', 'north', 'south'])[S.north]"]
check.near('rate ratio east/south = exp(b_east - (-b_east - b_north))', lvr[('region', 'east', 'south')]['ratio'], math.exp(bs[0] - (-bs[0] - bs[1])), rel=1e-10)
check('zero-inflation ratios are odds ratios', FITS['zip']['ratios']['zero']['kind'], 'odds')

# ---- marginal effects: statsmodels' get_margeff ---------------------------------------------------------------------------
for key, at in (('poisson', 'overall'), ('nb2', 'mean')):
    me = call('counts.margeff', model=key, at=at, **BASE)
    res = counts._get(tid, None, spec, key)['res']
    sf = res.get_margeff(at=at).summary_frame()
    near_all(f'margins {key} at {at} = get_margeff', sorted(x['effect'] for x in me['table']['rows']), sorted(sf.iloc[:, 0]), rel=1e-10)
    check(f'margins {key}: the exposure note', any('rate per unit of exposure' in x for x in me['notes']), True)
check('margins: none for zero-inflated models, said', 'no marginal effects' in call('counts.margeff', model='zinb', **BASE).get('error', ''), True)

# ---- the profiler: predictions at the current values, delta-method intervals ----------------------------------------------
cur = {'age': 40.0, 'sex': 'M', 'region': 'north', 'years': 2.0}
pr = call('counts.profile', model='zinb', current=cur, **BASE)
row = pd.DataFrame({'age': [40.0], 'sex': ['M'], 'region': ['north']})
Xn = patsy.build_design_matrices([Xd.design_info], row, return_type='dataframe')[0]
res = counts._get(tid, None, spec, 'zinb')['res']
mz = res.model.predict(np.asarray(res.params), exog=np.asarray(Xn), exog_infl=np.asarray(Xn), exposure=np.array([2.0]), which='mean')
p0z = res.model.predict(np.asarray(res.params), exog=np.asarray(Xn), exog_infl=np.asarray(Xn), exposure=np.array([2.0]), which='prob-zero')
check.near('profiler: the ZINB mean at the current values = statsmodels\' predict', pr['responses'][0]['current']['pred'], float(mz[0]), rel=1e-9)
check.near('profiler: P(0) at the current values = statsmodels\' predict(which="prob-zero")', pr['responses'][1]['current']['pred'], float(p0z[0]), rel=1e-9)
check('profiler: the factors, the exposure last', [f['name'] for f in pr['factors']], ['age', 'sex', 'region', 'years'])
check('profiler: a trace per factor and response', [len(x['traces']) for x in pr['responses']], [4, 4])
pr = call('counts.profile', model='poisson', current=cur, **BASE)
resp = counts._get(tid, None, spec, 'poisson')['res']
fresh = Poisson(yv, Xd, offset=off).fit(start_params=np.asarray(resp.params), method='newton', maxiter=5, disp=0)
gp_ = fresh.get_prediction(exog=np.asarray(Xn), offset=np.array([math.log(2.0)]), which='linear')
zc = stats.norm.ppf(0.975)
lin, sel = float(np.asarray(gp_.predicted)[0]), float(np.asarray(gp_.se)[0])
check.near('profiler: the Poisson interval = exp(linear prediction ± z se) (statsmodels get_prediction)', pr['responses'][0]['current']['lower'], math.exp(lin - zc * sel), rel=1e-5)
check.near('... its upper limit', pr['responses'][0]['current']['upper'], math.exp(lin + zc * sel), rel=1e-5)

# ---- randomized quantile residuals: seeded, uniform between F(y-1) and F(y) ----------------------------------------------
m = counts._get(tid, None, spec, 'nb2')
res = m['res']
a = float(res.params[-1])
mu_ = res.predict()
F = lambda k: stats.nbinom.cdf(k, 1 / a, 1 / (1 + a * mu_))  # noqa: E731
u = np.random.default_rng(1).uniform(F(yv - 1), F(yv))
near_all('quantile residuals = Phi^-1 of a seeded uniform between F(y-1) and F(y)', FITS['nb2']['resid_quantile'], stats.norm.ppf(u), rel=1e-9)
r5 = call('counts.fit', model='nb2', seed=5, **BASE)
check('another seed, other residuals', maxdiff(r5['resid_quantile'], FITS['nb2']['resid_quantile']) > 0.01, True)
check.near('quantile residuals of a good model are about standard normal (sd)', float(np.std(FITS['zinb']['resid_quantile'])), 1.0, rel=0.1)

# ---- every result's Python code runs on a CSV export and gives the report's numbers ----------------------------------------
for tag, B, fr_ in (('exposure', BASE, frame), ('no exposure', B0, frame)):
    sp = counts._spec('visits', X_EFF, 1, [], True, B.get('exposure'), None, None)
    for key in ALL:
        r = call('counts.fit', model=key, table_name='visits', **B)
        ns, err = run_code(r['code'], fr_, 'visits')
        check(f'code {key} ({tag}) runs', err, None)
        if err:
            continue
        m = counts._get(B['table'], None, sp, key)
        near_all(f'code {key} ({tag}): the estimates', ns['fit_params'], m['params'], rel=1e-9)
        check.near(f'code {key} ({tag}): the log-likelihood', float(ns['fit_llf']), r['llf'], rel=1e-10)
        near_all(f'code {key} ({tag}): the expected frequencies', ns['expected'], r['dist']['expected'], rel=1e-9)
        near_all(f'code {key} ({tag}): P(Y = 0)', ns['p0'], r['p0'], rel=1e-9)
        near_all(f'code {key} ({tag}): the quantile residuals', ns['quantile_resid'], r['resid_quantile'], rel=1e-8, abs_=1e-9)
c = call('counts.compare', which=ALL, table_name='visits', **BASE)
ns, err = run_code(c['code'], frame, 'visits')
check('code of the comparison runs', err, None)
if not err:
    for v in c['vuong']:
        a1 = next(k for k in ALL if counts.LABEL[k] == v['m1'])
        a2 = next(k for k in ALL if counts.LABEL[k] == v['m2'])
        near_all(f'code of the comparison: Vuong {v["s1"]} vs {v["s2"]}', ns['vuong'](a1, a2), [v['z'], v['z_aic'], v['z_bic']], rel=1e-8)
    for x in c['models']:
        check.near(f'code of the comparison: -2LL {x["model"]}', float(-2 * ns['ll'][x['model']].sum()), x['m2ll'], rel=1e-10)
r = call('counts.fit', model='zinb', table=ftid, y='visits', x=X_EFF, exposure='years', freq='f', table_name='visitsf')
ns, err = run_code(r['code'], pd.concat([frame, pd.Series(fr, name='f')], axis=1), 'visitsf')
check('code with Freq runs', err, None)
if not err:
    check.near('code with Freq: the log-likelihood', float(ns['fit_llf']), r['llf'], rel=1e-10)
    near_all('code with Freq: the quantile residuals, one a row', ns['quantile_resid'], r['resid_quantile'], rel=1e-8, abs_=1e-9)
sub = [i for i in range(n) if i % 3]
r = call('counts.fit', model='hnb', rows=sub, table_name='visits', **BASE)
ns, err = run_code(r['code'], frame, 'visits')
check('code of a subset of rows runs', err, None)
if not err:
    check.near('code of a subset of rows: the log-likelihood', float(ns['fit_llf']), r['llf'], rel=1e-10)
me = call('counts.margeff', model='poisson', at='overall', table_name='visits', **BASE)
ns, err = run_code(me['code'], frame, 'visits')
check('code of the marginal effects runs', err, None)

# ---- the graphs' matplotlib code, run with Agg on the CSV, against the report's numbers ----------------------------------
from test_charts import run_snippet_more  # noqa: E402

COLOR = {k: c for k, c in zip(ALL, ['#b0413e', '#2f6690', '#3a7d44', '#6c5b7b', '#1f8a78', '#9c8200', '#8c564b', '#b8408f', '#12808f'])}


def page_ticks(d):
    """The rootogram's ticks as the page puts them: about a dozen at round steps, the tail's '≥K' last."""
    K = len(d['k']) - 1
    step = next((s_ for s_ in (1, 2, 5, 10, 20, 25, 50) if (K + 1) / s_ <= 12), 50)
    tv = [v for v in d['k'] if v % step == 0 and (not d['tail'] or K - v >= step / 2)]
    if d['tail']:
        tv.append(K)
    return tv, [f'≥{v}' if (v == K and d['tail']) else str(v) for v in tv]


def graph(kind, label, frame_, name, **kw):
    r = call('counts.plot_code', kind=kind, table_name=name, **kw)
    check(f'{label}: the code is written', r.get('error'), None)
    code = r.get('plot_code') or ''
    out, err = run_snippet_more(code, frame_, name, tmp)
    check(f'{label}: the code runs', err, None)
    check(f'{label}: it ends with plt.show()', code.rstrip().split('\n')[-1] if code else None, 'plt.show()')
    check(f'{label}: one figure', len(out['figures']) if out else 0, 1)
    return out['figures'][0] if out and out['figures'] else None


def page_groups(f):
    """Zero Probability's squares as the page makes them: the rows by predicted mean in ten groups at most."""
    mean, y_, w = np.asarray(f['mean']), np.asarray(f['y']), np.asarray(f['freq'] if f['freq'] else np.ones(len(f['y'])), dtype=float)
    order = sorted(range(len(mean)), key=lambda i: mean[i])
    m_ = len(mean)
    g = max(1, min(10, m_ // 15))
    out = []
    for j in range(g):
        idx = order[(j * m_) // g:((j + 1) * m_) // g]
        sw = w[idx].sum()
        if sw:
            out.append((float((w[idx] * mean[idx]).sum() / sw), float((w[idx] * (y_[idx] == 0)).sum() / sw)))
    return out


for tag, B, fr_, nm in (('exposure', BASE, frame, 'visits'), ('Freq', dict(table=ftid, y='visits', x=X_EFF, exposure='years', freq='f'), pd.concat([frame, pd.Series(fr, name='f')], axis=1), 'visitsf'),
                        ('a subset of rows', dict(BASE, rows=sub), frame, 'visits')):
    keys = ALL if tag == 'exposure' else ['poisson', 'zinb', 'hnb']
    for key in keys:
        f = call('counts.fit', model=key, **B)
        if f.get('error'):
            check(f'charts {key} ({tag}): the model fits', f['error'], None)
            continue
        d = f['dist']
        tv, tt = page_ticks(d)
        so, se = np.sqrt(d['observed']), np.sqrt(np.maximum(d['expected'], 0))
        styles = ('hanging', 'standing', 'suspended') if key == 'nb2' and tag == 'exposure' else ('hanging',)
        for style in styles:
            lab = f'rootogram, {style} ({key}, {tag})'
            F = graph('rootogram', lab, fr_, nm, model=key, plot={'style': style, 'tickvals': tv, 'ticktext': tt, 'width': 340}, **B)
            if not F:
                continue
            A = F['axes'][0]
            bars = A['bars']
            if style == 'hanging':
                want_h, want_b = so, se - so
            elif style == 'standing':
                want_h, want_b = so, np.zeros(len(so))
            else:
                want_h, want_b = se - so, np.zeros(len(so))
            check(f'{lab}: a bar for each count', len(bars), len(d['k']))
            if len(bars) == len(d['k']):
                check(f'{lab}: the bars, from the report\'s observed and expected frequencies', maxdiff([b['h'] for b in bars], want_h) < 1e-8 and maxdiff([b['y'] for b in bars], want_b) < 1e-8
                      and maxdiff([b['x'] + b['w'] / 2 for b in bars], d['k']) < 1e-12, True)
            curve = [ln for ln in A['lines'] if len(ln['x']) == len(d['k']) and ln['marker'] == 'o']
            if style == 'suspended':
                check(f'{lab}: no curve', curve, [])
            else:
                check(f'{lab}: the curve √expected, in the model\'s colour', bool(curve) and maxdiff(curve[0]['y'], se) < 1e-8 and curve[0]['color'] == COLOR[key] + 'ff', True)
            check(f'{lab}: the page\'s ticks', (A['xticks'], A['xticklabels']), ([float(v) for v in tv], tt))
            check(f'{lab}: the titles', (A['xlabel'], A['ylabel'], A['title']), ('visits', '√Expected − √Observed' if style == 'suspended' else '√Frequency', counts.LABEL[key]))
        if tag == 'exposure' and key not in ('poisson', 'nb2', 'zinb', 'hnb', 'gp'):
            continue   # the rows' graphs for five of the models (with the exposure), and each model of the other runs
        n_ = len(f['rows'])
        lab = f'zero probability ({key}, {tag})'
        F = graph('zero', lab, fr_, nm, model=key, **B)
        if F:
            A = F['axes'][0]
            rows_pts = [x for x in A['scatter'] if x['label'] == 'Rows']
            check(f'{lab}: a point for each row, (mean, P(Y = 0)) of the report', bool(rows_pts) and len(rows_pts[0]['xy']) == n_
                  and maxdiff([p_[0] for p_ in rows_pts[0]['xy']], f['mean']) < 1e-8 and maxdiff([p_[1] for p_ in rows_pts[0]['xy']], f['p0']) < 1e-8, True)
            sq = [x for x in A['scatter'] if x['label'] == 'Observed share of zeros']
            want = page_groups(f)
            check(f'{lab}: the squares, the page\'s groups', bool(sq) and len(sq[0]['xy']) == len(want) and all(abs(a[0] - b[0]) < 1e-8 and abs(a[1] - b[1]) < 1e-12 for a, b in zip(sq[0]['xy'], want)), True)
            ex = [ln for ln in A['lines'] if ln['label'] == 'Poisson exp(−μ)']
            lo_, hi_ = min(f['mean']), max(f['mean'])
            check(f'{lab}: exp(−μ) over the range of the means', bool(ex) and len(ex[0]['x']) == 80 and abs(ex[0]['x'][0] - lo_) < 1e-9 and abs(ex[0]['x'][-1] - hi_) < 1e-9
                  and maxdiff(ex[0]['y'], np.exp(-np.asarray(ex[0]['x']))) < 1e-12, True)
            check(f'{lab}: the range and the titles', (A['ylim'], A['xlabel'], A['ylabel'], A['title']), ([-0.02, 1.02], 'Predicted mean of visits', 'P(visits = 0)', f'visits zero probability, {counts.SHORT[key]}'))
        lab = f'Pearson residuals ({key}, {tag})'
        F = graph('pearson', lab, fr_, nm, model=key, **B)
        if F:
            A = F['axes'][0]
            pts = A['scatter'][0]['xy'] if A['scatter'] else []
            check(f'{lab}: a point for each row, (mean, Pearson residual) of the report', len(pts) == n_ and maxdiff([p_[0] for p_ in pts], f['mean']) < 1e-8
                  and maxdiff([p_[1] for p_ in pts], f['resid_pearson']) < 1e-7, True)
            check(f'{lab}: the zero line and the titles', ([ln['y'] for ln in A['lines']], A['ylabel'], A['title']), ([[0.0, 0.0]], 'Pearson Residual', f'visits Pearson residuals by predicted, {counts.SHORT[key]}'))
        lab = f'quantile residuals ({key}, {tag})'
        F = graph('quantile', lab, fr_, nm, model=key, seed=1, **B)
        if F:
            A = F['axes'][0]
            pts = A['scatter'][0]['xy'] if A['scatter'] else []
            rq = np.sort(np.asarray([v for v in f['resid_quantile'] if v is not None and math.isfinite(v)]))
            z = stats.norm.ppf(np.arange(1, len(rq) + 1) / (len(rq) + 1))
            check(f'{lab}: the report\'s randomized quantile residuals (seed 1), sorted, against the normal quantiles', len(pts) == len(rq) and maxdiff([p_[1] for p_ in pts], rq) < 1e-7
                  and maxdiff([p_[0] for p_ in pts], z) < 1e-12, True)
            ln = [x for x in A['lines'] if len(x['x']) == 2]
            check(f'{lab}: the line y = x over the quantiles', bool(ln) and maxdiff(ln[0]['x'], [z.min(), z.max()]) < 1e-12 and ln[0]['x'] == ln[0]['y'], True)
fo = call('counts.fit', model='poisson', **BASE)
tv, tt = page_ticks(fo['dist'])
keys = ['poisson', 'nb2', 'zip', 'zinb']
F = graph('overlay', 'rootogram, the models overlaid', frame, 'visits', models=keys, plot={'tickvals': tv, 'ticktext': tt, 'width': 520}, **BASE)
if F:
    A = F['axes'][0]
    check('overlay: standing bars of √observed', maxdiff([b['h'] for b in A['bars']], np.sqrt(fo['dist']['observed'])) < 1e-12 and all(b['y'] == 0 for b in A['bars']), True)
    for key in keys:
        e = call('counts.fit', model=key, **BASE)['dist']['expected']
        ln = [x for x in A['lines'] if x['label'] == counts.SHORT[key]]
        check(f'overlay: the curve of {key}, √expected, in its colour', bool(ln) and maxdiff(ln[0]['y'], np.sqrt(np.maximum(e, 0))) < 1e-8 and ln[0]['color'] == COLOR[key] + 'ff', True)
    check('overlay: the legend, the title', (F['legend'], A['title']), (['Observed'] + [counts.SHORT[k] for k in keys], 'visits rootogram, the models overlaid'))
check('an unknown graph is refused', 'error' in call('counts.plot_code', kind='pie', model='poisson', **BASE), True)
check('a model that cannot be fitted says so', 'error' in call('counts.plot_code', kind='zero', model='zip', table=table({'y': [1.0, 2, 3, 4, 5]}), y='y'), True)

sys.exit(check.done())
