#!/usr/bin/env python3
"""Analyze > Specialized Modeling > Generalized Additive Model's backend
(resources/py/smui/gam.py), checked against statsmodels' GLMGam called
directly with the same bases and penalties: coefficients, EDF, deviance,
AIC, GCV, partial values and their standard errors, the tests, the
predictions; the penalty searches against select_penweight and
select_penweight_kfold run by hand; Weight against var_weights (and a
weighted GLM when unpenalized), Freq against copies of the rows; simulated
data with known smooth functions (the fitted partial effects close to the
truth); and the Python code of each report run on a CSV export of its
table.

    python3 resources/tests/smui/test_gam.py

It needs numpy, scipy, pandas, patsy and statsmodels 0.14 (Pyodide 314.0.7
has statsmodels 0.14.6).
"""
import contextlib
import io
import os
import sys
import tempfile
import warnings

import numpy as np
import pandas as pd
import patsy
import statsmodels.api as sm
from scipy import stats
from statsmodels.gam.api import BSplines, CyclicCubicSplines, GLMGam
from statsmodels.gam.smooth_basis import GenericSmoothers, UnivariateBSplines, UnivariateCubicCyclicSplines

from backend import FAILED, Checks, call, table

check = Checks()
check('gam imports', 'gam' in FAILED, False)
warnings.simplefilter('ignore', FutureWarning)

# ---- simulated data with known smooth functions --------------------------------
rng = np.random.default_rng(20260926)
n = 365
day = np.arange(1.0, n + 1)
temp = 12 - 10 * np.cos(2 * np.pi * (day - 15) / 365) + rng.normal(0, 3, n)
wind = rng.gamma(2.0, 2.0, n)
f_temp = lambda t: 30 / (1 + np.exp(-(t - 20) / 3))
f_wind = lambda w: 25 * np.exp(-w / 3)
f_day = lambda d: 8 * np.sin(2 * np.pi * (d - 80) / 365)
weekend = np.where(rng.uniform(size=n) < 2 / 7, 'yes', 'no')
eta = f_temp(temp) + f_wind(wind) + f_day(day)
ozone = 20 + eta - 4 * (weekend == 'yes') + rng.normal(0, 5, n)
alert = (rng.uniform(size=n) < 1 / (1 + np.exp(-(eta - 40) / 6))).astype(float)
visits = rng.poisson(np.exp(0.2 + 0.03 * eta)).astype(float)
cost = rng.gamma(5.0, np.exp(0.5 + 0.02 * eta) / 5.0)
wts = rng.uniform(0.4, 2.5, n)
freq = rng.integers(0, 4, n).astype(float)
ozone_miss = ozone.copy()
ozone_miss[[3, 50, 51]] = np.nan
level = np.where(alert > 0, 'high', 'low')
cols = {'ozone': ozone, 'temperature': temp, 'wind speed': wind, 'day of year': day, 'weekend': weekend.tolist(), 'alert': alert,
        'visits': visits, 'cost': cost, 'w': wts, 'f': freq, 'ozone2': ozone_miss, 'level': level.tolist()}
tid = table(cols, levels={'weekend': ['no', 'yes'], 'level': ['low', 'high']})
DF = pd.DataFrame(cols)
S3 = ['temperature', 'wind speed', 'day of year']


def truth_rmse(res_term, f, x):
    """RMSE between a fitted partial effect (at the rows) and the true
    function centred over the rows, relative to the function's SD."""
    tr = f(x) - np.mean(f(x))
    return float(np.sqrt(np.mean((np.asarray(res_term) - tr) ** 2)) / np.std(tr))


def bs_direct(xs, dfs, degrees, names):
    return BSplines(xs, df=dfs, degree=degrees, constraints='center', variable_names=names)


def lin_design(d, formula):
    return patsy.dmatrix(formula, d, return_type='dataframe')


def edf_terms(res, model, smoother):
    return [float(res.edf[model.k_exog_linear:][m].sum()) for m in smoother.mask]


# ---- 1. fixed penalties, all B-splines: the report against GLMGam with BSplines --------
pen = [150.0, 20.0, 5.0e4]
base = dict(y='ozone', smooth=S3, linear=['weekend'])
r = call('gam.fit', table=tid, **base, penalty=pen)
check('fixed: smoothing is fixed', r['summary']['smoothing'], 'fixed')
d = DF.copy()
d['weekend'] = pd.Categorical(d['weekend'], categories=['no', 'yes'])
xs = d[S3].to_numpy(float)
Gd = bs_direct(xs, [10, 10, 10], [3, 3, 3], S3)
X = lin_design(d, "C(weekend, Sum, levels=['no', 'yes'])")
md = GLMGam(d['ozone'].to_numpy(float), exog=X, smoother=Gd, alpha=pen, family=sm.families.Gaussian())
rd = md.fit()
check.near('deviance = GLMGam direct', r['summary']['deviance'], float(rd.deviance), rel=1e-9)
check.near('AIC', r['summary']['aic'], float(rd.aic), rel=1e-9)
check.near('BIC (llf)', r['summary']['bic'], float(rd.bic_llf), rel=1e-9)
check.near('GCV', r['summary']['gcv'], float(rd.gcv), rel=1e-9)
check.near('scale', r['summary']['scale'], float(rd.scale), rel=1e-9)
check.near('total EDF', r['summary']['edf'], float(rd.edf.sum()), rel=1e-9)
check.near('Pearson chi-square', r['summary']['pearson'], float(rd.pearson_chi2), rel=1e-9)
check.near('null deviance', r['summary']['null_deviance'], float(rd.null_deviance), rel=1e-9)
for j, e in enumerate(edf_terms(rd, md, Gd)):
    check.near(f'EDF of {S3[j]}', r['terms'][j]['edf'], e, rel=1e-9)
for j in range(3):
    pv, se = rd.partial_values(j, include_constant=False)
    pvc, sec = rd.partial_values(j, include_constant=True)
    pts = r['terms'][j]['points']
    check('rows of the partial residuals are the table\'s', pts['rows'][:5], [0, 1, 2, 3, 4])
    # the curve on the grid, at the rows (the grid runs from min to max; interpolate the direct values instead: compare at the ends)
    order = np.argsort(xs[:, j])
    check.near(f'{S3[j]}: curve at the smallest x = partial_values', r['terms'][j]['curve']['f'][0], float(pv[order[0]]), rel=1e-7, abs_=1e-9)
    check.near(f'{S3[j]}: curve at the largest x', r['terms'][j]['curve']['f'][-1], float(pv[order[-1]]), rel=1e-7, abs_=1e-9)
    check.near(f'{S3[j]}: its standard error', r['terms'][j]['curve']['se'][0], float(se[order[0]]), rel=1e-7)
    check.near(f'{S3[j]}: with the intercept (include_constant=True)', r['intercept'] + r['terms'][j]['curve']['f'][-1], float(pvc[order[-1]]), rel=1e-7)
    check.near(f'{S3[j]}: its standard error with the intercept', r['terms'][j]['curve']['se_c'][-1], float(sec[order[-1]]), rel=1e-7)
    # partial residuals: the term plus the working residual (plot_partial's cpr)
    check('partial residuals = partial_values + resid_working', bool(np.allclose(pts['partial'], pv + rd.resid_working, rtol=1e-8, atol=1e-8)), True)
    ts = rd.test_significance(j)
    check.near(f'{S3[j]}: Wald chi-square = test_significance', r['tests'][j]['chisq'], float(np.squeeze(ts.statistic)), rel=1e-8)
    check.near(f'{S3[j]}: its p-value on the EDF', r['tests'][j]['p'], float(np.squeeze(ts.pvalue)), rel=1e-7, abs_=1e-300)
    check.near(f'{S3[j]}: the EDF of the test', r['tests'][j]['edf'], float(ts.df_denom), rel=1e-9)
    check.near(f'{S3[j]}: p on Nparm degrees of freedom', r['tests'][j]['p_nparm'], float(stats.chi2.sf(float(np.squeeze(ts.statistic)), 9)), rel=1e-7, abs_=1e-300)
    check(f'{S3[j]}: nine parameters (df 10, centred)', r['tests'][j]['nparm'], 9)
est = {e['term']: e for e in r['estimates']['rows']}
check('JMP names in Parameter Estimates', list(est), ['Intercept', 'weekend[no]'])
check.near('Intercept = GLMGam direct', est['Intercept']['estimate'], float(rd.params['Intercept']), rel=1e-9)
bname = [c for c in X.columns if 'weekend' in c][0]
check.near('weekend[no] (effect coded)', est['weekend[no]']['estimate'], float(rd.params[bname]), rel=1e-9)
check.near('its standard error', est['weekend[no]']['se'], float(rd.bse[bname]), rel=1e-9)
check.near('its Wald chi-square', est['weekend[no]']['chisq'], float((rd.params[bname] / rd.bse[bname]) ** 2), rel=1e-9)
check.near('the linear effect test (one parameter) = its Wald chi-square', r['effect_tests'][0]['chisq'], est['weekend[no]']['chisq'], rel=1e-9)
dg = r['diag']
check('diagnostics for every row', len(dg['rows']), n)
check('predicted = fittedvalues', bool(np.allclose(dg['predicted'], rd.fittedvalues, rtol=1e-10)), True)
check('deviance residuals = resid_deviance', bool(np.allclose(dg['resid_dev'], rd.resid_deviance, rtol=1e-9, atol=1e-9)), True)
check.near('the deviance is the sum of squared residuals (normal)', float(np.sum(np.square(dg['residual']))), float(rd.deviance), rel=1e-9)
gp = rd.get_prediction()
sf = gp.summary_frame(alpha=0.05)
check('mean confidence interval = get_prediction', bool(np.allclose(dg['lower_mean'], sf['mean_ci_lower'], rtol=1e-8) and np.allclose(dg['upper_mean'], sf['mean_ci_upper'], rtol=1e-8)), True)

# the code of the report on a CSV export
TMP = tempfile.mkdtemp(prefix='smui-gam-')


def run_code(code, frame, name):
    frame.to_csv(os.path.join(TMP, f'{name}.csv'), index=False)
    ns = {}
    here = os.getcwd()
    os.chdir(TMP)
    try:
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            exec(compile(code, f'<{name}>', 'exec'), ns)
    finally:
        os.chdir(here)
    return ns


r = call('gam.fit', table=tid, **base, penalty=pen, table_name='gamfixed')
ns = run_code(r['code'], DF, 'gamfixed')
check.near('code (fixed): its deviance is the report\'s', float(ns['res'].deviance), r['summary']['deviance'], rel=1e-9)
check.near('code (fixed): its AIC', float(ns['res'].aic), r['summary']['aic'], rel=1e-9)
check('code (fixed): BSplines for B-spline terms', 'BSplines(xs' in r['code'], True)

# ---- 2. a cyclic term: GenericSmoothers against the direct construction ----------------
terms = [{'basis': 'bs', 'df': 8, 'degree': 3}, {'basis': 'bs', 'df': 7, 'degree': 2}, {'basis': 'cc', 'df': 12}]
r = call('gam.fit', table=tid, **base, penalty=pen, terms=terms, table_name='gamcyc')
Gm = GenericSmoothers(xs, [UnivariateBSplines(xs[:, 0], df=8, degree=3, include_intercept=True, constraints='center', variable_name='temperature'),
                           UnivariateBSplines(xs[:, 1], df=7, degree=2, include_intercept=True, constraints='center', variable_name='wind speed'),
                           UnivariateCubicCyclicSplines(xs[:, 2], df=12, constraints='center', variable_name='day of year')])
mm = GLMGam(d['ozone'].to_numpy(float), exog=X, smoother=Gm, alpha=pen, family=sm.families.Gaussian())
rm = mm.fit()
check.near('mixed bases: deviance = GLMGam direct', r['summary']['deviance'], float(rm.deviance), rel=1e-9)
check.near('mixed bases: EDF of the cyclic term', r['terms'][2]['edf'], edf_terms(rm, mm, Gm)[2], rel=1e-9)
check('the cyclic term has df - 1 = 11 parameters', r['terms'][2]['nparm'], 11)
check('degree 2 B-spline: 6 parameters', r['terms'][1]['nparm'], 6)
cc = r['terms'][2]['curve']['f']
check.near('the cyclic smooth takes the same value at both ends', cc[0], cc[-1], rel=1e-9, abs_=1e-9)
ns = run_code(r['code'], DF, 'gamcyc')
check.near('code (mixed bases): deviance', float(ns['res'].deviance), r['summary']['deviance'], rel=1e-9)
check('code (mixed bases): GenericSmoothers', 'GenericSmoothers(xs' in r['code'] and 'UnivariateCubicCyclicSplines' in r['code'], True)
rc = call('gam.fit', table=tid, y='ozone', smooth=['day of year'], terms=[{'basis': 'cc', 'df': 10}], penalty=[1.0e5], table_name='gamcc')
Gc = CyclicCubicSplines(d[['day of year']].to_numpy(float), df=[10], constraints='center', variable_names=['day of year'])
rcd = GLMGam(d['ozone'].to_numpy(float), exog=np.ones((n, 1)), smoother=Gc, alpha=[1.0e5], family=sm.families.Gaussian()).fit()
check.near('cyclic only: deviance = CyclicCubicSplines direct', rc['summary']['deviance'], float(rcd.deviance), rel=1e-9)
check('code (cyclic only): CyclicCubicSplines', 'CyclicCubicSplines(xs' in rc['code'], True)
ns = run_code(rc['code'], DF, 'gamcc')
check.near('code (cyclic only): deviance', float(ns['res'].deviance), rc['summary']['deviance'], rel=1e-9)

# ---- 3. the penalty search: AIC, BIC, GCV against select_penweight by hand ----------------
y = d['ozone'].to_numpy(float)
Xn = X.to_numpy(float)
fam = sm.families.Gaussian()


def by_hand(crit, G, y, Xn, fam, vw=None):
    """select_penweight as the module runs it: the start from the grid of
    common multiples of tr(B'WB)/tr(S), Nelder-Mead in log alpha."""
    w = fam.weights(fam.starting_mu(y)) * (vw if vw is not None else 1)
    a0 = np.array([np.sum(w[:, None] * s.basis ** 2) / np.trace(s.cov_der2) for s in G.smoothers])
    grid = 10.0 ** np.arange(-3, 5)
    kw = {'var_weights': vw} if vw is not None else {}
    vals = [getattr(GLMGam(y, exog=Xn, smoother=G, alpha=list(c * a0), family=fam, **kw).fit(weights=vw), crit) for c in grid]
    start = a0 * grid[int(np.argmin(vals))]
    mod = GLMGam(y, exog=Xn, smoother=G, alpha=list(start), family=fam, **kw)
    r0 = mod.fit(weights=vw)
    if vw is not None:
        import functools
        mod._fit_pirls = functools.partial(mod._fit_pirls, weights=vw)
    k = len(start)
    simplex = np.log(start) + np.vstack([np.zeros(k), 0.5 * np.log(10) * np.eye(k)])
    ftol = 1e-7 * max(1.0, abs(float(getattr(r0, crit))))
    bounds = [(np.log(a * 1e-6), np.log(a * 1e7)) for a in a0]
    a, _, _ = mod.select_penweight(criterion=crit, start_params=start, method='basinhopping', niter=0, minimizer_kwargs={
        'method': 'Nelder-Mead', 'bounds': bounds, 'options': {'xatol': 0.01, 'fatol': ftol, 'maxfev': 400, 'initial_simplex': simplex}})
    return a, a0, vals


for mode, crit in [('aic', 'aic'), ('bic', 'bic_llf'), ('gcv', 'gcv')]:
    r = call('gam.fit', table=tid, **base, smoothing=mode, table_name=f'gam{mode}')
    a, a0, vals = by_hand(crit, Gd, y, Xn, fam)
    got = [t['alpha'] for t in r['terms']]
    check(f'{mode}: the chosen penalties = select_penweight by hand', bool(np.allclose(got, a, rtol=1e-9)), True)
    check.near(f'{mode}: its criterion', r['summary'][{'aic': 'aic', 'bic': 'bic', 'gcv': 'gcv'}[mode]],
               float(getattr(GLMGam(y, exog=Xn, smoother=Gd, alpha=list(a), family=fam).fit(), crit)), rel=1e-9)
    check(f'{mode}: the search improves on the best grid point', r['summary'][{'aic': 'aic', 'bic': 'bic', 'gcv': 'gcv'}[mode]] <= min(vals) + 1e-9, True)
    check(f'{mode}: the scales are tr(BᵀWB)/tr(S)', bool(np.allclose([t['a0'] for t in r['terms']], a0, rtol=1e-12)), True)
    ns = run_code(r['code'], DF, f'gam{mode}')
    check(f'code ({mode}): the search finds the same penalties', bool(np.allclose(ns['alpha'], got, rtol=1e-9)), True)
    check.near(f'code ({mode}): deviance', float(ns['res'].deviance), r['summary']['deviance'], rel=1e-9)
r_aic = call('gam.fit', table=tid, **base, smoothing='aic')
r_bic = call('gam.fit', table=tid, **base, smoothing='bic')
check('BIC chooses a smoother fit than AIC (fewer EDF)', r_bic['summary']['edf'] < r_aic['summary']['edf'], True)

# known truth: the partial effects of the AIC fit are close to the true functions
for j, (f, x) in enumerate([(f_temp, temp), (f_wind, wind), (f_day, day)]):
    pv = np.interp(x, r_aic['terms'][j]['curve']['x'], r_aic['terms'][j]['curve']['f'])
    e = truth_rmse(pv, f, x)
    check(f'truth: s({S3[j]}) within 25% of the true function\'s SD (RMSE/SD {e:.3f})', e < 0.25, True)
wk_est = [e for e in r_aic['estimates']['rows'] if e['term'] == 'weekend[no]'][0]
check('truth: the weekend effect (+2 for no, effect coded) inside 3 SE', abs(wk_est['estimate'] - 2) < 3 * wk_est['se'], True)
cov = [abs(np.interp(x, t['curve']['x'], t['curve']['f']) - (f(x) - np.mean(f(x)))) <= 1.96 * np.interp(x, t['curve']['x'], t['curve']['se'])
       for t, f, x in zip(r_aic['terms'], [f_temp, f_wind, f_day], [temp, wind, day])]
share = float(np.mean(np.concatenate(cov)))
check(f'truth: the 95% bands cover most of the true curves ({share:.2f})', share > 0.8, True)

# ---- 4. k-fold cross-validation against select_penweight_kfold by hand ----------------------
from smui import gam as G_mod  # noqa: E402
r = call('gam.fit', table=tid, **base, smoothing='kfold', folds=5, table_name='gamkfold')
a0 = np.array([t['a0'] for t in r['terms']])
g = np.linspace(-3, 4, 4)
acv, cvres = GLMGam(y, exog=Xn, smoother=Gd, alpha=list(a0), family=fam).select_penweight_kfold(
    alphas=[a * 10.0 ** g for a in a0], cv_iterator=G_mod._SeededKFold(5, G_mod._SEED))
check('k-fold: the penalties = select_penweight_kfold with the same folds', bool(np.allclose([t['alpha'] for t in r['terms']], acv, rtol=1e-12)), True)
check('k-fold: 4 grid values per term for three terms', r['summary']['fits'], 4 ** 3 * 5)
folds = [list(np.nonzero(te)[0]) for _tr, te in G_mod._SeededKFold(5, 1).split(np.zeros((20, 1)))]
check('the seeded folds are the same every time split() is called', folds, [list(np.nonzero(te)[0]) for _tr, te in G_mod._SeededKFold(5, 1).split(np.zeros((20, 1)))])
ns = run_code(r['code'], DF, 'gamkfold')
check('code (k-fold): the same penalties', bool(np.allclose(ns['alpha'], [t['alpha'] for t in r['terms']], rtol=1e-12)), True)
check.near('code (k-fold): deviance', float(ns['res'].deviance), r['summary']['deviance'], rel=1e-9)
r = call('gam.fit', table=tid, **base, smoothing='kfold', terms=[{}, {}, {'basis': 'cc'}])
check('k-fold with a cyclic term: AIC instead, and a note', (r['summary']['smoothing'], any('K-fold cross-validation is not available' in x for x in r['notes'])), ('aic', True))
r = call('gam.fit', table=tid, **base, freq='f', smoothing='kfold')
check('k-fold with a Freq column: AIC instead (copies of a row would fall into different folds)', r['summary']['smoothing'], 'aic')
r = call('gam.fit', table=tid, y='visits', smooth=S3, family='poisson', smoothing='kfold')
check('k-fold with the Poisson: AIC instead', r['summary']['smoothing'], 'aic')
r = call('gam.fit', table=tid, y='visits', smooth=S3, family='poisson', smoothing='gcv')
check('GCV with the Poisson (scale 1): AIC instead, and a note', (r['summary']['smoothing'], any('GCV with the scale fixed' in x for x in r['notes'])), ('aic', True))

# ---- 5. other families against GLMGam direct, and their predictions ------------------------
Gd2 = bs_direct(xs[:, :2], [10, 8], [3, 3], S3[:2])
for fam_key, yname, F in [('binomial', 'alert', sm.families.Binomial()), ('poisson', 'visits', sm.families.Poisson()),
                          ('gamma', 'cost', sm.families.Gamma(link=sm.families.links.Log()))]:
    pen2 = [30.0, 5.0]
    r = call('gam.fit', table=tid, y=yname, smooth=S3[:2], terms=[{'df': 10}, {'df': 8}], family=fam_key, penalty=pen2, table_name=f'gam{fam_key}')
    md2 = GLMGam(DF[yname].to_numpy(float), exog=np.ones((n, 1)), smoother=Gd2, alpha=pen2, family=F)
    rd2 = md2.fit()
    check.near(f'{fam_key}: deviance = GLMGam direct', r['summary']['deviance'], float(rd2.deviance), rel=1e-8)
    check.near(f'{fam_key}: AIC', r['summary']['aic'], float(rd2.aic), rel=1e-8)
    check.near(f'{fam_key}: EDF', r['summary']['edf'], float(rd2.edf.sum()), rel=1e-8)
    check.near(f'{fam_key}: scale', r['summary']['scale'], float(rd2.scale), rel=1e-8)
    check.near(f'{fam_key}: Wald chi-square of the first term', r['tests'][0]['chisq'], float(np.squeeze(rd2.test_significance(0).statistic)), rel=1e-7)
    cur = {'temperature': 18.5, 'wind speed': 3.25}
    p = call('gam.profile', table=tid, y=yname, smooth=S3[:2], terms=[{'df': 10}, {'df': 8}], family=fam_key, penalty=pen2, current=cur, grid=11)
    pr = rd2.get_prediction(exog=np.ones((1, 1)), exog_smooth=np.array([[18.5, 3.25]])).summary_frame(alpha=0.05)
    c0 = p['responses'][0]['current']
    check.near(f'{fam_key}: the profiler\'s prediction = get_prediction', c0['pred'], float(pr['mean'].iloc[0]), rel=1e-9)
    check.near(f'{fam_key}: its lower limit', c0['lower'], float(pr['mean_ci_lower'].iloc[0]), rel=1e-9)
    check.near(f'{fam_key}: its upper limit', c0['upper'], float(pr['mean_ci_upper'].iloc[0]), rel=1e-9)
    tr0 = p['responses'][0]['traces'][0]
    check(f'{fam_key}: a trace over the factor\'s range', (len(tr0['x']), tr0['x'][0], tr0['x'][-1]), (11, float(np.min(temp)), float(np.max(temp))))
    at = rd2.get_prediction(exog=np.ones((11, 1)), exog_smooth=np.column_stack([np.linspace(temp.min(), temp.max(), 11), np.full(11, 3.25)])).summary_frame()
    check(f'{fam_key}: the trace = get_prediction along it', bool(np.allclose(tr0['pred'], at['mean'], rtol=1e-9)), True)
    ns = run_code(r['code'], DF, f'gam{fam_key}')
    check.near(f'code ({fam_key}): deviance', float(ns['res'].deviance), r['summary']['deviance'], rel=1e-8)
    check(f'{fam_key}: bounded profiler for the binomial only', p['responses'][0]['bounded'], fam_key == 'binomial')
# a two-level categorical Y: the event is its first level; Target Level picks the other
r = call('gam.fit', table=tid, y='level', smooth=S3[:2], family='binomial', penalty=[30.0, 5.0], table_name='gamlevel')
check('a two-level Y: the event is the first level', r['model']['event'], 'low')
r2 = call('gam.fit', table=tid, y='level', smooth=S3[:2], family='binomial', penalty=[30.0, 5.0], target='high')
check.near('the Target Level high models the same as the 0/1 alert', r2['summary']['deviance'],
           call('gam.fit', table=tid, y='alert', smooth=S3[:2], family='binomial', penalty=[30.0, 5.0])['summary']['deviance'], rel=1e-9)
ns = run_code(r['code'], DF, 'gamlevel')
check.near('code (categorical Y): deviance', float(ns['res'].deviance), r['summary']['deviance'], rel=1e-8)
p = call('gam.profile', table=tid, y='level', smooth=S3[:2], family='binomial', penalty=[30.0, 5.0])
check('the profiler names the event probability', p['responses'][0]['name'], 'Prob[low]')
r = call('gam.fit', table=tid, y='ozone', smooth=S3[:2], terms=[{'df': 10}, {'df': 8}], family='normal', link='log', penalty=[30.0, 5.0])
rl = GLMGam(y, exog=np.ones((n, 1)), smoother=Gd2, alpha=[30.0, 5.0], family=sm.families.Gaussian(link=sm.families.links.Log())).fit()
check.near('normal with the log link = GLMGam direct', r['summary']['deviance'], float(rl.deviance), rel=1e-8)

# ---- 6. Weight: var_weights and fit(weights=...) -----------------------------------------
r = call('gam.fit', table=tid, **base, weight='w', penalty=pen, table_name='gamw')
mw = GLMGam(y, exog=Xn, smoother=Gd, alpha=pen, family=fam, var_weights=wts)
rw = mw.fit(weights=wts)
check.near('Weight: deviance = GLMGam(var_weights).fit(weights=)', r['summary']['deviance'], float(rw.deviance), rel=1e-9)
check.near('Weight: AIC', r['summary']['aic'], float(rw.aic), rel=1e-9)
check.near('Weight: EDF', r['summary']['edf'], float(rw.edf.sum()), rel=1e-9)
check('Weight: not the unweighted fit', abs(r['summary']['deviance'] - float(GLMGam(y, exog=Xn, smoother=Gd, alpha=pen, family=fam, var_weights=wts).fit().deviance)) > 1e-6, True)
r0 = call('gam.fit', table=tid, **base, weight='w', penalty=[0.0, 0.0, 0.0])
g0 = sm.GLM(y, np.column_stack([Xn, Gd.basis]), family=fam, var_weights=wts).fit()
check.near('Weight, no penalty: the weighted GLM on the same basis', r0['summary']['deviance'], float(g0.deviance), rel=1e-9)
check.near('Weight, no penalty: the scale', r0['summary']['scale'], float(g0.scale), rel=1e-8)
ns = run_code(r['code'], DF, 'gamw')
check.near('code (Weight): deviance', float(ns['res'].deviance), r['summary']['deviance'], rel=1e-9)
r = call('gam.fit', table=tid, **base, weight='w', smoothing='aic', table_name='gamwaic')
a, _a0, _v = by_hand('aic', Gd, y, Xn, fam, vw=wts)
check('Weight + AIC: the search refits with the weights', bool(np.allclose([t['alpha'] for t in r['terms']], a, rtol=1e-9)), True)
ns = run_code(r['code'], DF, 'gamwaic')
check('code (Weight + AIC): the same penalties', bool(np.allclose(ns['alpha'], [t['alpha'] for t in r['terms']], rtol=1e-9)), True)

# ---- 7. Freq: copies of the rows ---------------------------------------------------------------
r = call('gam.fit', table=tid, **base, freq='f', smoothing='aic', table_name='gamf')
rep = freq.astype(int)
exp_cols = {k: (np.repeat(np.asarray(v, dtype=object if isinstance(v, list) else float), rep).tolist() if isinstance(v, list) else np.repeat(v, rep))
            for k, v in cols.items() if k in ('ozone', 'temperature', 'wind speed', 'day of year', 'weekend')}
tid_e = table(exp_cols, levels={'weekend': ['no', 'yes']})
re_ = call('gam.fit', table=tid_e, **base, smoothing='aic')
check('Freq: N is the sum of the frequencies', r['summary']['n'], int(rep.sum()))
check('Freq: the rows with frequency 0 are left out', r['summary']['n_rows'], int(np.sum(rep > 0)))
check.near('Freq = the table with the rows copied (deviance)', r['summary']['deviance'], re_['summary']['deviance'], rel=1e-8)
check.near('Freq = copies (scale)', r['summary']['scale'], re_['summary']['scale'], rel=1e-8)
check('Freq = copies (the same penalties)', bool(np.allclose([t['alpha'] for t in r['terms']], [t['alpha'] for t in re_['terms']], rtol=1e-8)), True)
check('Freq: one diagnostic row per table row', len(r['diag']['rows']), int(np.sum(rep > 0)))
ns = run_code(r['code'], DF, 'gamf')
check.near('code (Freq): deviance', float(ns['res'].deviance), r['summary']['deviance'], rel=1e-9)

# ---- 8. rows, missing values, By groups --------------------------------------------------------
r = call('gam.fit', table=tid, y='ozone2', smooth=S3[:2], penalty=[30.0, 5.0], table_name='gammiss')
check('rows with a missing Y are left out', (r['summary']['n'], 3 in r['diag']['rows']), (n - 3, False))
sub = [i for i in range(n) if weekend[i] == 'no']
r = call('gam.fit', table=tid, y='ozone', smooth=S3[:2], rows=sub, penalty=[30.0, 5.0], table_name='gamsub')
ds = DF.loc[sub]
Gs = bs_direct(ds[S3[:2]].to_numpy(float), [10, 10], [3, 3], S3[:2])
rs = GLMGam(ds['ozone'].to_numpy(float), exog=np.ones((len(sub), 1)), smoother=Gs, alpha=[30.0, 5.0], family=fam).fit()
check.near('a subset of rows (a By group) = GLMGam on those rows', r['summary']['deviance'], float(rs.deviance), rel=1e-9)
check('its rows are the table\'s', r['diag']['rows'][:3], sub[:3])
ns = run_code(r['code'], DF, 'gamsub')
check.near('code (a subset of rows): deviance', float(ns['res'].deviance), r['summary']['deviance'], rel=1e-9)

# ---- 9. the slider, the surface, the comparison with the linear model ---------------------------
tm = call('gam.term', table=tid, **base, penalty=[1500.0, 20.0, 5.0e4], index=0)
full = call('gam.fit', table=tid, **base, penalty=[1500.0, 20.0, 5.0e4])
check.near('the slider\'s preview = the fit at those penalties (EDF of the term)', tm['term']['edf'], full['terms'][0]['edf'], rel=1e-12)
check.near('and its AIC', tm['aic'], full['summary']['aic'], rel=1e-12)
check('a larger penalty: fewer EDF', tm['term']['edf'] < call('gam.fit', table=tid, **base, penalty=pen)['terms'][0]['edf'], True)
s = call('gam.surface', table=tid, **base, penalty=pen, first=0, second=1, n=12)
rf = call('gam.fit', table=tid, **base, penalty=pen)
fa = np.interp(s['x'], rf['terms'][0]['curve']['x'], rf['terms'][0]['curve']['f'])
check('surface: 12 × 12', (len(s['z']), len(s['z'][0])), (12, 12))
check.near('surface: z at a corner = s(temperature) + s(wind speed)', s['z'][0][0], rf['terms'][0]['curve']['f'][0] + rf['terms'][1]['curve']['f'][0], rel=1e-9)
check('surface: its points are the rows', len(s['points']['rows']), n)
c = call('gam.compare', table=tid, **base, penalty=pen, table_name='gamcmp')
glm = sm.GLM(y, np.column_stack([Xn, xs]), family=fam).fit()
check.near('compare: the linear model = sm.GLM with the smooth columns', c['models'][0]['deviance'], float(glm.deviance), rel=1e-9)
check.near('compare: its AIC', c['models'][0]['aic'], float(glm.aic), rel=1e-9)
ddf = rd.edf.sum() - 5
fr = ((glm.deviance - rd.deviance) / ddf) / rd.scale
check.near('compare: F = (ΔD/ΔEDF)/scale', c['test']['stat'], float(fr), rel=1e-9)
check.near('compare: its p-value', c['test']['p'], float(stats.f.sf(fr, ddf, rd.df_resid)), rel=1e-6, abs_=1e-300)
ns = run_code(c['code'], DF, 'gamcmp')
check.near('code (compare): the linear model\'s deviance', float(ns['glm'].deviance), c['models'][0]['deviance'], rel=1e-9)
cp = call('gam.compare', table=tid, y='visits', smooth=S3[:2], family='poisson', penalty=[30.0, 5.0])
check('compare, Poisson: a likelihood ratio chi-square', cp['test']['label'], 'L-R ChiSquare')

# ---- 10. errors and adjustments ------------------------------------------------------------------
def err(**kw):
    try:
        call('gam.fit', table=tid, **kw)
        return None
    except Exception as e:
        return str(e)


check('a categorical smooth column is refused', 'not continuous' in (err(y='ozone', smooth=['weekend']) or ''), True)
check('the binomial refuses a Y that is not 0/1', '0s and 1s' in (err(y='ozone', smooth=['wind speed'], family='binomial') or ''), True)
check('the Gamma refuses a Y at or below zero', 'above zero' in (err(y='day of year', smooth=['wind speed'], family='gamma', penalty=[1.0]) or '') or
      err(y='day of year', smooth=['wind speed'], family='gamma', penalty=[1.0]) is None, True)
check('a column in two roles is refused', 'two roles' in (err(y='ozone', smooth=['wind speed'], linear=['wind speed']) or ''), True)
tid2 = table({'y': rng.normal(size=60), 'x': np.repeat([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 10)})
r = call('gam.fit', table=tid2, y='y', smooth=['x'], penalty=[1.0])
check('six distinct values: the basis size falls to six, with a note', (r['terms'][0]['df'], any('basis size is 6' in x for x in r['notes'])), (6, True))
tid3 = table({'y': rng.normal(size=40), 'x': np.repeat([1.0, 2.0, 3.0], [10, 20, 10])})
try:
    call('gam.fit', table=tid3, y='y', smooth=['x'])
    msg = ''
except Exception as e:
    msg = str(e)
check('three distinct values are refused', 'at least four' in msg, True)

# ---- 11. what the report says about the tests: test_significance under the null ----------------
# A term with no effect (its EDF often near 1): the Wald statistic of all its coefficients on the EDF
# rejects somewhat more often than 5%, on as many degrees of freedom as it has parameters rarely.
rng2 = np.random.default_rng(11)
p_edf, p_np = [], []
for rep_i in range(60):
    m_ = 150
    tt = table({'y': np.sin(np.linspace(0, 6, m_)) + rng2.normal(size=m_), 'x': rng2.uniform(0, 10, m_), 'z': np.linspace(0, 6, m_)})
    rr = call('gam.fit', table=tt, y='y', smooth=['x', 'z'], smoothing='aic')
    p_edf.append(rr['tests'][0]['p'])
    p_np.append(rr['tests'][0]['p_nparm'])
share_edf, share_np = float(np.mean(np.array(p_edf) < 0.05)), float(np.mean(np.array(p_np) < 0.05))
print(f'      null term: p < 0.05 in {share_edf:.3f} of fits on the EDF, {share_np:.3f} on Nparm')
check('under the null the EDF version rejects at least as often as the Nparm one', share_edf >= share_np, True)
check('the Nparm version rejects at most 5%', share_np <= 0.05, True)
check('the EDF version stays below 20% (the search is bounded)', share_edf <= 0.2, True)
# the bounded search: a term with no effect goes to the top of the range, not beyond it
top = [t for t in rr['terms'] if t['alpha'] > t['a0'] * 1e6]
check('penalties stay within 1e7 times the term\'s scale', all(t['alpha'] <= t['a0'] * 1e7 * (1 + 1e-9) for t in rr['terms']), True)
check('and a B-spline term\'s EDF at least 1 (its straight line is not penalized)', all(t['edf'] > 0.999 for t in rr['terms'] if t['basis'] == 'bs'), True)

# ---- the graphs' matplotlib code, run with Agg on the CSV, against the report's numbers --------------------
from test_charts import run_snippet_more  # noqa: E402


def graph(kind, plot, label, frame_, name, **model):
    rr = call('gam.plot_code', table=tid, kind=kind, plot=plot, table_name=name, **model)
    code = rr.get('plot_code') or ''
    out, err = run_snippet_more(code, frame_, name, TMP)
    check(f'{label}: the code runs', err, None)
    check(f'{label}: it ends with plt.show()', code.rstrip().split('\n')[-1] if code else None, 'plt.show()')
    check(f'{label}: one figure', len(out['figures']) if out else 0, 1)
    return (out['figures'][0] if out and out['figures'] else None), code


def close_to(a, b, rel=1e-7, abs_=1e-9):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.all(np.abs(a - b) <= np.maximum(abs_, rel * np.maximum(np.abs(a), np.abs(b)))))


def check_term(label, F, t, intercept, opts, alpha=0.05):
    A = F['axes'][0]
    c0 = intercept if opts.get('constant') else 0.0
    se = np.asarray(t['curve']['se_c'] if opts.get('constant') else t['curve']['se'])
    f_ = np.asarray(t['curve']['f']) + c0
    z = stats.norm.ppf(1 - alpha / 2)
    curve = [ln for ln in A['lines'] if len(ln['x']) == len(t['curve']['x']) and ln['color'] == '#c0392bff']
    check(f'{label}: the curve, the report\'s partial effect on its grid', bool(curve) and close_to(curve[0]['x'], t['curve']['x'], 1e-12) and close_to(curve[0]['y'], f_), True)
    band = [p_ for p_ in A['polys'] if p_['colors'] and p_['colors'][0] == '#c0392b21']
    if opts.get('band', True):
        v = np.asarray(band[0]['paths'][0]) if band else np.zeros((0, 2))
        m_ = len(t['curve']['x'])
        lo_ok = band and close_to(v[1:m_ + 1, 1], f_ - z * se, 1e-6)   # fill_between: along the lower edge, then back along the upper
        hi_ok = band and close_to(v[m_ + 2:2 * m_ + 2, 1][::-1], f_ + z * se, 1e-6)
        check(f'{label}: the pointwise band from the report\'s standard errors', bool(lo_ok and hi_ok), True)
    else:
        check(f'{label}: no band', band, [])
    pts = [x for x in A['scatter'] if x['label'] == 'Partial residuals']
    if opts.get('resid', True):
        xy = np.asarray(pts[0]['xy']) if pts else np.zeros((0, 2))
        check(f'{label}: the partial residuals at the rows, the report\'s', bool(pts) and close_to(xy[:, 0], t['points']['x'], 1e-12) and close_to(xy[:, 1], np.asarray(t['points']['partial']) + c0, 1e-6), True)
    else:
        check(f'{label}: no partial residuals', pts, [])
    rug = [ln for ln in A['lines'] if ln['marker'] == '|']
    if opts.get('rug', True):
        check(f'{label}: the rug at the rows\' values', bool(rug) and close_to(rug[0]['x'], t['points']['x'], 1e-12) and set(rug[0]['y']) == {0.035}, True)
    else:
        check(f'{label}: no rug', rug, [])
    check(f'{label}: the titles', (A['xlabel'], A['ylabel'], A['title']), (t['name'], f'Intercept + s({t["name"]})' if opts.get('constant') else f's({t["name"]})', f'{t["name"]} partial effect'))


def check_diag(label, F, kind, rep, yname):
    A = F['axes'][0]
    d_ = rep['diag']
    pts = np.asarray(A['scatter'][0]['xy']) if A['scatter'] else np.zeros((0, 2))
    if kind == 'actual':
        check(f'{label}: (predicted, actual) of the report\'s rows', close_to(pts[:, 0], d_['predicted']) and close_to(pts[:, 1], d_['actual'], 1e-12), True)
        lo_, hi_ = min(min(d_['predicted']), min(d_['actual'])), max(max(d_['predicted']), max(d_['actual']))
        check(f'{label}: the line actual = predicted over both ranges', [(ln['x'], ln['y']) for ln in A['lines']] and close_to(A['lines'][0]['x'], [lo_, hi_]) and A['lines'][0]['x'] == A['lines'][0]['y'], True)
    elif kind == 'residual':
        check(f'{label}: (predicted, residual) of the report\'s rows', close_to(pts[:, 0], d_['predicted']) and close_to(pts[:, 1], d_['residual'], 1e-6, 1e-8), True)
        check(f'{label}: the zero line', [ln['y'] for ln in A['lines']], [[0.0, 0.0]])
    else:
        r_ = np.asarray(d_['resid_dev'])
        o = np.argsort(r_, kind='stable')
        zq = stats.norm.ppf(stats.rankdata(r_) / (len(r_) + 1))
        check(f'{label}: the report\'s deviance residuals, sorted, at their normal quantiles', close_to(pts[:, 1], r_[o], 1e-6, 1e-8) and close_to(pts[:, 0], zq[o], 1e-12), True)
        ln = A['lines'][0] if A['lines'] else {'x': [], 'y': []}
        check(f'{label}: the line with their mean and SD', close_to(ln['y'], [r_.mean() + r_.std(ddof=1) * zq.min(), r_.mean() + r_.std(ddof=1) * zq.max()], 1e-6, 1e-8), True)


fixed = dict(base, penalty=pen)
rf = call('gam.fit', table=tid, **fixed)
for j, t in enumerate(rf['terms']):
    for opts in ({'band': True, 'resid': True, 'rug': True, 'constant': False},) + (({'band': False, 'resid': False, 'rug': False, 'constant': False}, {'band': True, 'resid': True, 'rug': True, 'constant': True}) if j == 0 else ()):
        tag = f's({t["name"]}), fixed penalties' + ('' if opts['band'] else ', no band, residuals or rug') + (', with the intercept' if opts['constant'] else '')
        F, code = graph('term', dict(opts, index=j), tag, DF, 'gamplot', **fixed)
        if F:
            check_term(tag, F, t, rf['intercept'], opts)
for kind in ('actual', 'residual', 'devqq'):
    F, code = graph(kind, {}, f'{kind} (fixed penalties)', DF, 'gamplot', **fixed)
    if F:
        check_diag(f'{kind} (fixed penalties)', F, kind, rf, 'ozone')
        check(f'{kind} (fixed penalties): the title', F['axes'][0]['title'], {'actual': 'ozone actual by predicted', 'residual': 'ozone residual by predicted', 'devqq': 'ozone deviance residual normal quantile plot'}[kind])
sf = call('gam.surface', table=tid, first=0, second=2, n=40, **fixed)
F, code = graph('surface', {'first': 0, 'second': 2, 'n': 40}, 'surface of temperature and day of year', DF, 'gamplot', **fixed)
if F:
    out2, _ = run_snippet_more(code, DF, 'gamplot', TMP)
    A = out2['figures'][0]['axes'][0] if out2 else {}
    mesh = A.get('meshes', [])
    check('surface: the heatmap is the report\'s grid of s(temperature) + s(day of year)', bool(mesh) and close_to(mesh[0]['z'], np.asarray(sf['z']).ravel()) and close_to(mesh[0]['x'], sf['x'], 1e-12)
          and close_to(mesh[0]['y'], sf['y'], 1e-12), True)
    pts = np.asarray(A['scatter'][0]['xy']) if A.get('scatter') else np.zeros((0, 2))
    check('surface: the rows\' points', close_to(pts[:, 0], sf['points']['x'], 1e-12) and close_to(pts[:, 1], sf['points']['y'], 1e-12), True)
    lv = [p_['contour'] for p_ in A.get('polys', []) if 'contour' in p_]
    zz = np.asarray(sf['z'])
    steps = np.diff(lv[0]) if lv else []
    check('surface: contour levels at a round step, inside the range, about fifteen or fewer', bool(lv) and len(lv[0]) <= 16 and np.allclose(steps, steps[0]) and zz.min() < lv[0][0] and lv[0][-1] < zz.max(), True)
    check('surface: the colour bar and the titles', (out2['figures'][0]['colorbars'], A['xlabel'], A['ylabel'], A['title']),
          (['s(temperature) + s(day of year)'], 'temperature', 'day of year', 'temperature and day of year surface'))
# the penalties chosen by AIC: the code searches as the report does and draws its curve
ra = call('gam.fit', table=tid, **base, smoothing='aic')
F, code = graph('term', {'index': 1, 'band': True, 'resid': True, 'rug': True}, 's(wind speed), penalties by AIC', DF, 'gamplot', **base, smoothing='aic')
if F:
    check('penalties by AIC: the code runs the search', 'select_penweight' in code, True)
    check_term('s(wind speed), penalties by AIC', F, ra['terms'][1], ra['intercept'], {'band': True, 'resid': True, 'rug': True}, )
# Freq repeats rows for the fit: one point, residual and rug mark a row; rows the report leaves out
subset = [i for i in range(n) if i not in (5, 6, 7, 100)]
rq = call('gam.fit', table=tid, **base, freq='f', penalty=pen, rows=subset)
for kind in ('term', 'actual', 'devqq'):
    F, code = graph(kind, {'index': 2}, f'{kind} with Freq and rows left out', DF, 'gamplot', **base, freq='f', penalty=pen, rows=subset)
    if F:
        check(f'{kind} with Freq and rows left out: the code drops them', 'df = df.drop(index=[5, 6, 7, 100])' in code, True)
        if kind == 'term':
            check_term(f'{kind} with Freq and rows left out', F, rq['terms'][2], rq['intercept'], {'band': True, 'resid': True, 'rug': True})
        else:
            check_diag(f'{kind} with Freq and rows left out', F, kind, rq, 'ozone')
# a two-level Y (binomial): the event in the axis title, no residuals by default
rb = call('gam.fit', table=tid, y='level', smooth=S3[:2], family='binomial', penalty=[30.0, 5.0])
F, code = graph('actual', {}, 'binomial actual by predicted', DF, 'gamplot', y='level', smooth=S3[:2], family='binomial', penalty=[30.0, 5.0])
if F:
    check_diag('binomial actual by predicted', F, 'actual', rb, 'level')
    check('binomial actual by predicted: the event in the axis title', F['axes'][0]['ylabel'], 'level (low = 1)')
F, code = graph('term', {'index': 0, 'band': True, 'resid': False, 'rug': True}, 'binomial s(temperature)', DF, 'gamplot', y='level', smooth=S3[:2], family='binomial', penalty=[30.0, 5.0])
if F:
    check_term('binomial s(temperature)', F, rb['terms'][0], rb['intercept'], {'band': True, 'resid': False, 'rug': True})
# a cyclic term
terms_c = [{'basis': 'bs', 'df': 8, 'degree': 3}, {'basis': 'bs', 'df': 7, 'degree': 2}, {'basis': 'cc', 'df': 12}]
rc_ = call('gam.fit', table=tid, **base, penalty=pen, terms=terms_c)
F, code = graph('term', {'index': 2}, 'a cyclic s(day of year)', DF, 'gamplot', **base, penalty=pen, terms=terms_c)
if F:
    check_term('a cyclic s(day of year)', F, rc_['terms'][2], rc_['intercept'], {'band': True, 'resid': True, 'rug': True})
try:
    call('gam.plot_code', table=tid, kind='pie', **fixed)
    refused = False
except Exception:
    refused = True
check('an unknown graph is refused', refused, True)

sys.exit(check.done())
