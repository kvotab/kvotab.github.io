#!/usr/bin/env python3
"""Analyze > Fit Model's backend (resources/py/smui/fit_model.py), checked
against statsmodels and scipy called directly, the NIST StRD certified values
(Longley, Wampler 1 and 2), textbook results (Greene's logit of the Spector
and Mazzeo data, the balanced one-way random effects model) and brute force
(leave-one-out PRESS, simulated Durbin-Watson p-values, all subsets).

Generalized Estimating Equations are checked against statsmodels' documented
GEE example (epil), R's gee package (the results statsmodels' test suite
records), statsmodels' GEE called directly for every working correlation and
covariance, least squares and GLM for the independence model, and known truth
for Pan's QIC penalty; Robust Standard Errors against Stata's regress, robust /
cluster and ivreg2 (recorded in statsmodels' test suite, on its macrodata and
grunfeld data); the Regression Diagnostics against R's lmtest (bptest, gqtest,
bgtest, harvtest, raintest, as statsmodels' test suite records them), statsmodels
and scipy.

Instrumental Variables are checked against Stata's ivreg2 and ivendog on
Griliches's wage data (every estimate and standard error, classical, robust and
small robust; Sargan, Hansen's J, Cragg-Donald, Wu-Hausman and Durbin), IV2SLS
and the sandwiches by hand, Shea's definition, and a simulation with known truth;
Quantile Regression against Stata's qreg on Koenker's Engel data (estimates,
iid standard errors, sparsity, bandwidth, pseudo RSquare), QuantReg called
directly, Powell's sandwich by its formula and by the spread of the estimates
over simulated samples, and the true quantiles of a heteroscedastic model;
Recursive and Rolling Regression against R's strucchange (recursive residuals
and estimates, as statsmodels' tests record them), recursive_olsresiduals,
least squares on the first rows and on each window by brute force, RollingOLS
and RollingWLS, Brown, Durbin and Evans's constants, and a simulated break.

Generalized Regression is checked against scikit-learn called directly (the
lasso and elastic net paths, LogisticRegression and PoissonRegressor at the
same penalty, Lasso on the columns times |b| for the adaptive lasso, LassoCV's
folds, log_loss), statsmodels' fit_regularized and score_test, the validation
curves by their formulas on fits made by scikit-learn (KFold, Holdback,
Leave-One-Out, a Validation column), predictive.prepare's sets, brute force
(the forward steps, the best pair of the floating search) and the Model
Summary's measures by their formulas.

MANOVA's Repeated Measures is checked against statsmodels' AnovaRM and MANOVA
(with other contrast bases), least squares on the stacked data (Type III within
tests of unbalanced groups), anova_lm on the subjects' sums, Hotelling's T² and
t tests, the formulas of Mauchly, Greenhouse-Geisser, Huynh-Feldt and Lecoutre,
JMP's documented Sphericity Test of its Dogs example, and pingouin's rm_anova,
mixed_anova, sphericity and epsilon; the Effect Tests' partial eta and omega
squared against pingouin's anova and ancova, Hays's one-way omega squared and
expanded Freq rows. statsmodels' mv_test failing on an exactly null effect is
pinned. pingouin (GPL) is only called as a reference, its datasets read at run
time; without it those checks are skipped.

    python3 resources/tests/smui/test_fit_model.py

The statsmodels datasets, the data files of statsmodels' own GEE and IV tests
(griliches76.dta) and the results modules of its test suite are loaded from the
installed package at run time; everything else is simulated here with fixed
seeds.
"""
import contextlib
import io
import itertools
import math
import os
import sys
import tempfile

import numpy as np
import pandas as pd
import patsy
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from statsmodels.miscmodels.ordinal_model import OrderedModel

from backend import FAILED, Checks, call, table
from smui import fit_model, models

check = Checks()
if 'fit_model' in FAILED:
    print('fit_model failed to import:', FAILED['fit_model'])
    sys.exit(1)


def arr(v):
    return np.array([np.nan if x is None else x for x in v], dtype=float)


def maxdiff(a, b):
    return float(np.nanmax(np.abs(arr(a) - np.asarray(b, dtype=float))))


def rows_of(t):
    return {r['term'] if 'term' in r else r['source']: r for r in t['rows']}


tmp = tempfile.mkdtemp(prefix='smui-fitmodel-')


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


# ---- NIST StRD Longley: certified estimates, standard errors, ANOVA --------------------------
lon = sm.datasets.longley.load_pandas().data
tid = table({c: lon[c].tolist() for c in lon.columns})
E = [['GNPDEFL'], ['GNP'], ['UNEMP'], ['ARMED'], ['POP'], ['YEAR']]
r = call('fitmodel.ls', table=tid, y='TOTEMP', effects=E)
cert = {'Intercept': (-3482258.63459582, 890420.383607373), 'GNPDEFL': (15.0618722713733, 84.9149257747669),
        'GNP': (-0.358191792925910e-01, 0.334910077722432e-01), 'UNEMP': (-2.02022980381683, 0.488399681651699),
        'ARMED': (-1.03322686717359, 0.214274163161675), 'POP': (-0.511041056535807e-01, 0.226073200069370),
        'YEAR': (1829.15146461355, 455.478499142212)}
est = rows_of(r['estimates'])
for k, (b, se) in cert.items():
    check.near(f'Longley estimate {k}', est[k]['estimate'], b, rel=1e-7)
    check.near(f'Longley std error {k}', est[k]['se'], se, rel=1e-7)
an = {x['source']: x for x in r['anova']['rows']}
check.near('Longley model SS', an['Model']['ss'], 184172401.944494, rel=1e-9)
check.near('Longley error SS', an['Error']['ss'], 836424.055505915, rel=1e-8)
check.near('Longley F', an['Model']['f'], 330.285339234588, rel=1e-8)
sof = {x['stat']: x['value'] for x in r['summary']['rows']}
check.near('Longley RSquare', sof['RSquare'], 0.995479004577296, rel=1e-9)
check.near('Longley RMSE', sof['Root Mean Square Error'], 304.854073561965, rel=1e-9)
check('Longley: every effect has a leverage plot', [x['effect'] for x in r['leverage']], [e[0] for e in E])

# ---- NIST StRD Wampler 1 and 2: degree-5 polynomials fitted exactly (centred powers) ---------------
x = np.arange(21.0)
for name, coef in (('Wampler1', [1, 1, 1, 1, 1, 1]), ('Wampler2', [1, 0.1, 0.01, 0.001, 0.0001, 0.00001])):
    yv = sum(c * x ** k for k, c in enumerate(coef))
    t = table({'x': x.tolist(), 'y': yv.tolist()})
    eff = [['x'] * k for k in range(1, 6)]
    rw = call('fitmodel.ls', table=t, y='y', effects=eff)
    sw = {s['stat']: s['value'] for s in rw['summary']['rows']}
    check(f'{name}: exact fit, RSquare 1', abs(sw['RSquare'] - 1) < 1e-12, True)
    check(f'{name}: certified residual SD 0', sw['Root Mean Square Error'] < 1e-6 * np.std(yv), True)
    check.near(f'{name}: predictions are the certified polynomial', maxdiff(rw['diag']['predicted'], yv) / np.max(np.abs(yv)), 0.0, abs_=1e-10)
    # the centred parameterisation, expanded, gives the certified coefficients
    cen = {r2['term']: r2['estimate'] for r2 in rw['estimates']['rows']}
    xm = float(np.mean(x))
    poly = np.zeros(6)
    poly[0] += cen['Intercept']
    poly[1] += cen['x']
    for k in range(2, 6):
        term = '*'.join([f'(x-{xm:.6g})'] * k)
        pk = np.polynomial.polynomial.polypow([-xm, 1.0], k)
        poly[:len(pk)] += cen[term] * pk
    check.near(f'{name}: certified coefficients from the centred ones', float(np.max(np.abs(poly - coef) / np.abs(coef))), 0.0, abs_=1e-6)

# ---- a two-factor experiment with a covariate ------------------------------------------------------------
rng = np.random.default_rng(3)
n = 72
fert = np.repeat(['A', 'B', 'C'], 24)
water = np.tile(np.repeat(['low', 'high'], 12), 3)
light = rng.normal(6, 1.5, n)
yv = 20 + (fert == 'B') * 3 + (fert == 'C') * 5.5 + (water == 'high') * 4 + ((fert == 'C') & (water == 'high')) * 2.5 + 1.2 * light + rng.normal(0, 2.2, n)
yv[5] = np.nan
tid = table({'fertilizer': fert.tolist(), 'water': water.tolist(), 'light': light.tolist(), 'yield': yv.tolist()},
            types={'water': 'ordinal'}, levels={'water': ['low', 'high']})
E = [{'names': ['fertilizer']}, {'names': ['water']}, {'names': ['light']}, {'names': ['fertilizer', 'water']}, {'names': ['light', 'light']}]
r = call('fitmodel.ls', table=tid, y='yield', effects=E, vif=True, dw=True, sequential=True, corr=True)
ok = np.isfinite(yv)
df = pd.DataFrame({'f': fert[ok], 'w': pd.Categorical(water[ok], ['low', 'high']), 'l': light[ok], 'y': yv[ok]})
lm = light[ok].mean()
ref = smf.ols(f'y ~ C(f, Sum) + C(w, Sum) + l + C(f, Sum):C(w, Sum) + I((l - {lm!r})**2)', df).fit()
check('rows used (one missing Y)', r['n_rows'], 71)
a3 = sm.stats.anova_lm(ref, typ=3)
et = rows_of(r['effect_tests'])
for src, key in [('fertilizer', 'C(f, Sum)'), ('water', 'C(w, Sum)'), ('light', 'l'), ('fertilizer*water', 'C(f, Sum):C(w, Sum)'), ('light*light', f'I((l - {lm!r}) ** 2)')]:
    check.near(f'Effect Tests F {src} = anova_lm type III', et[src]['stat'], float(a3.loc[key, 'F']), rel=1e-9)
check('Effect Summary sorted by LogWorth', [x['source'] for x in r['effect_summary']] == sorted(et, key=lambda s: et[s]['p']), True)
check.near('LogWorth is -log10 p', r['effect_summary'][0]['logworth'], -math.log10(r['effect_summary'][0]['p']))
from statsmodels.stats.multitest import multipletests
check.near('FDR p (Benjamini-Hochberg)', max(x['fdr_p'] for x in r['effect_summary']),
           float(max(multipletests([x['p'] for x in r['effect_summary']], method='fdr_bh')[1])))
a1 = sm.stats.anova_lm(ref, typ=1)
seq = rows_of(r['sequential'])
check.near('Sequential Tests = anova_lm type I (fertilizer)', seq['fertilizer']['ss'], float(a1.loc['C(f, Sum)', 'sum_sq']), rel=1e-9)
check.near('Sequential Tests (light*light)', seq['light*light']['ss'], float(a1.loc[f'I((l - {lm!r}) ** 2)', 'sum_sq']), rel=1e-9)
from statsmodels.stats.outliers_influence import variance_inflation_factor
vif = {x['term']: x['vif'] for x in r['estimates']['rows']}
check.near('VIF of light', vif['light'], float(variance_inflation_factor(ref.model.exog, list(ref.params.index).index('l'))), rel=1e-9)
inf = ref.get_influence()
dg = r['diag']
check.near('hats', maxdiff(dg['hat'], inf.hat_matrix_diag), 0.0, abs_=1e-12)
check.near('studentized residuals (internal)', maxdiff(dg['studentized'], inf.resid_studentized_internal), 0.0, abs_=1e-10)
check.near('studentized residuals (external)', maxdiff(dg['externally'], inf.resid_studentized_external), 0.0, abs_=1e-10)
check.near("Cook's D", maxdiff(dg['cooks'], inf.cooks_distance[0]), 0.0, abs_=1e-12)
sf = ref.get_prediction().summary_frame(alpha=0.05)
check.near('mean confidence interval', maxdiff(dg['lower_mean'], sf['mean_ci_lower']), 0.0, abs_=1e-9)
check.near('individual confidence interval', maxdiff(dg['upper_indiv'], sf['obs_ci_upper']), 0.0, abs_=1e-9)
check.near('std error of predicted', maxdiff(dg['se_pred'], sf['mean_se']), 0.0, abs_=1e-12)
check('diagnostics carry the page\'s row numbers', dg['rows'][:6], [0, 1, 2, 3, 4, 6])
check.near('studentized residual plot: Bonferroni limit', dg['limits']['bonferroni'], float(stats.t.ppf(1 - 0.05 / (2 * 71), ref.df_resid - 1)), rel=1e-12)
# PRESS by leaving each row out
press = 0.0
for i in range(len(df)):
    fi = smf.ols(ref.model.formula, df.drop(index=df.index[i])).fit()
    press += float(df['y'].iloc[i] - fi.predict(df.iloc[[i]]).iloc[0]) ** 2
check.near('PRESS = leave-one-out', r['press']['press'], press, rel=1e-8)
check.near('Durbin-Watson', r['dw']['dw'], float(sm.stats.durbin_watson(ref.resid)), rel=1e-12)
# Prob<DW: the exact p-value against a simulation under the model
X = ref.model.exog
Q, _ = np.linalg.qr(X)
sim = np.random.default_rng(11).normal(size=(20000, X.shape[0]))
res_sim = sim - (sim @ Q) @ Q.T
dws = np.sum(np.diff(res_sim, axis=1) ** 2, axis=1) / np.sum(res_sim ** 2, axis=1)
check.near('Prob<DW (Imhof) against 20000 simulations', r['dw']['p'], float(np.mean(dws < r['dw']['dw'])), abs_=0.012)
# lack of fit: none here (no replicates of the continuous factor); models' version agrees
check('no replicates, no Lack of Fit', r['lof'], None)
# leverage plots: the plot's coordinates hold the model's and the hypothesis' residuals
d2 = fit_model._ls_model(tid, None, fit_model._spec(y='yield', effects=E))['d']
for lev in r['leverage']:
    xs, ys = arr(lev['x']), arr(lev['y'])
    c = lev['mean']
    if lev['slope'] is not None:
        zx = (xs - lev['xbar']) * lev['slope']
    else:
        zx = xs - c
    rr = (ys - c) - zx                  # the residual: distance from the line of fit
    check.near(f'leverage {lev["effect"]}: distance to the line is the residual', float(np.max(np.abs(rr - ref.resid.to_numpy()))), 0.0, abs_=1e-9)
    ss = float(np.sum((ys - c) ** 2) - np.sum(rr ** 2))
    check.near(f'leverage {lev["effect"]}: SS from the plot = the effect\'s SS', ss, et[lev['effect']]['ss'], rel=1e-8)
    cur = lev['curve']
    lo, up = arr(cur['lower']), arr(cur['upper'])
    crosses = bool(np.any(lo > c) or np.any(up < c))
    # Sall's curves cross the mean line (somewhere) exactly when F > F(alpha), that is p < alpha
    check(f'leverage {lev["effect"]}: F > F(0.05) iff p < 0.05', lev['f'] > lev['fcrit'], lev['p'] < 0.05)
    if lev['p'] >= 0.05:
        check(f'leverage {lev["effect"]}: not significant, the curves hold the mean line', crosses, False)
    else:
        tq = stats.t.ppf(0.975, ref.df_resid)
        zstar = math.sqrt(tq ** 2 * ref.scale * lev['hbar'] / (1 - lev['fcrit'] / lev['f']))
        if zstar < float(np.max(np.abs(zx))):
            check(f'leverage {lev["effect"]}: significant, the curves cross the mean line', crosses, True)
# least squares means: the prediction over the full grid of the other factors, averaged
lsm = r['lsmeans']['fertilizer']
grid = pd.DataFrame([(f_, w_) for f_ in 'ABC' for w_ in ['low', 'high']], columns=['f', 'w'])
grid['w'] = pd.Categorical(grid['w'], ['low', 'high'])
grid['l'] = lm
Lg = patsy.dmatrix(ref.model.data.design_info, grid, return_type='dataframe').to_numpy()
for i, lv in enumerate('ABC'):
    L = Lg[grid['f'].to_numpy() == lv].mean(axis=0)
    check.near(f'LS mean fertilizer {lv}', lsm['lsmean'][i], float(L @ ref.params), rel=1e-12)
    check.near(f'LS mean std error {lv}', lsm['se'][i], float(math.sqrt(L @ ref.cov_params().to_numpy() @ L)), rel=1e-10)
check.near('LSMeans table Mean is the raw mean', lsm['mean'][0], float(df.loc[df.f == 'A', 'y'].mean()))
lsi = r['lsmeans']['fertilizer*water']
check('interaction LS means levels', lsi['labels'], ['A,low', 'A,high', 'B,low', 'B,high', 'C,low', 'C,high'])
g2 = grid[(grid.f == 'C') & (grid.w == 'high')]
check.near('LS mean C,high is the prediction there', lsi['lsmean'][5], float(ref.get_prediction(g2).predicted_mean[0]), rel=1e-12)
# the design rows of new points match patsy's, crossings, powers and nesting included
t3 = table({'a': rng.choice(list('pqr'), 60).tolist(), 'b': rng.choice(['u', 'v', 'w', 'z'], 60).tolist(), 'x': rng.normal(size=60).tolist(),
            'z': rng.normal(size=60).tolist(), 'y': rng.normal(size=60).tolist()})
E3 = [{'names': ['a']}, {'names': ['x']}, {'names': ['x', 'x']}, {'names': ['a', 'x']}, {'names': ['b'], 'nest': ['a']}, {'names': ['x', 'z']}, {'names': ['z']}]
for noint in (False, True):
    mm = fit_model._ls_model(t3, None, fit_model._spec(y='y', effects=E3, no_intercept=noint))
    dd = mm['d']
    pts = pd.DataFrame({'a': ['p', 'r', 'q'], 'b': ['v', 'z', 'u'], 'x': [0.3, -1.2, 2.0], 'z': [1.0, 0.0, -0.4]})
    frame = dd.frame_for({c: pts[c].tolist() for c in pts})
    want = patsy.build_design_matrices([mm['res'].model.data.design_info], frame)[0]
    sett = [fit_model._setting(dd, row.to_dict()) for _, row in pts.iterrows()]
    got = mm['coder'].rows(sett)
    check(f'design rows of new points = patsy\'s ({"no intercept" if noint else "intercept"})', float(np.max(np.abs(got - np.asarray(want)))) < 1e-12, True)
# comparisons: one-way, against statsmodels' Tukey HSD
g = np.repeat(['a', 'b', 'c', 'd'], 9)
yo = rng.normal(0, 1, 36) + np.repeat([0.0, 0.4, 1.3, 1.5], 9)
t4 = table({'g': g.tolist(), 'y': yo.tolist()})
tk = call('fitmodel.compare', table=t4, y='y', effects=[['g']], effect='g', method='tukey')
from statsmodels.stats.multicomp import pairwise_tukeyhsd
ph = pairwise_tukeyhsd(yo, g)
ptab = {(row[0], row[1]): row for row in ph.summary().data[1:]}
for od in tk['ordered']:
    key = tuple(sorted([od['level'], od['minus']]))
    check.near(f'Tukey HSD p {key}', od['p'], float(ph.pvalues[list(ptab).index(key)]), abs_=2e-3)
check.near('Tukey q* = q(0.95, k, df)/sqrt 2', tk['critical'], float(stats.studentized_range.ppf(0.95, 4, 32) / math.sqrt(2)), rel=1e-9)
lets = {x['level']: set(x['letters'].split()) for x in tk['letters']}
for od in tk['ordered']:
    share = bool(lets[od['level']] & lets[od['minus']])
    check(f'connecting letters: {od["level"]} and {od["minus"]} share a letter iff not different', share, not od['sig'])
check('letters start at A with the largest mean', tk['letters'][0]['letters'].split()[0], 'A')
st_ = call('fitmodel.compare', table=t4, y='y', effects=[['g']], effect='g', method='student')
fit4 = smf.ols('y ~ C(g, Sum)', pd.DataFrame({'g': g, 'y': yo})).fit()
tt = fit4.t_test('C(g, Sum)[S.a] - C(g, Sum)[S.b] = 0')
ab = [o for o in st_['ordered'] if {o['level'], o['minus']} == {'a', 'b'}][0]
check.near("Student's t p for a - b", ab['p'], float(tt.pvalue), rel=1e-9)
ct = call('fitmodel.contrast', table=t4, y='y', effects=[['g']], effect='g', coefs=[[1, -1, 0, 0], [1, 1, -1, -1]])
tt2 = fit4.t_test('2*C(g, Sum)[S.a] + 2*C(g, Sum)[S.b] = 0')
check.near('contrast t test', ct['rows'][1]['t'], float(np.squeeze(tt2.tvalue)), rel=1e-9)
L2 = np.array([[0, 1, -1, 0], [0, 2, 2, 0]], dtype=float)
check.near('contrasts: joint F', ct['joint']['f'], float(np.squeeze(fit4.f_test(L2).fvalue)), rel=1e-9)
# Box-Cox, intercept only: the profile likelihood is scipy's boxcox_llf
xbc = rng.normal(size=50)
ypos = np.exp(1 + 0.3 * xbc + rng.normal(0, 0.5, 50))
t5 = table({'y': ypos.tolist(), 'x': xbc.tolist()})
bc = call('fitmodel.boxcox', table=t5, y='y', effects=[])
ll = -len(ypos) / 2 * np.log(arr(bc['sse']) / len(ypos))
ref_ll = np.array([stats.boxcox_llf(lam, ypos) for lam in bc['lambda']])
check.near('Box-Cox: SSE profile = boxcox_llf up to a constant', float(np.ptp(ll - ref_ll)), 0.0, abs_=1e-8)
check.near('Box-Cox best lambda = scipy boxcox_normmax (mle)', bc['best'], float(stats.boxcox_normmax(ypos, method='mle')), abs_=1e-4)
bc2 = call('fitmodel.boxcox', table=t5, y='y', effects=[['x']])
gm = math.exp(np.mean(np.log(ypos)))
lam_ = bc2['lambda'][30]
zt = (ypos ** lam_ - 1) / (lam_ * gm ** (lam_ - 1))
check.near('Box-Cox with a regressor: SSE of the scaled transform', bc2['sse'][30], float(sm.OLS(zt, sm.add_constant(xbc)).fit().ssr), rel=1e-9)
thr = bc2['sse_best'] * math.exp(stats.chi2.ppf(0.95, 1) / 50)
check('Box-Cox interval brackets the best lambda', bc2['ci'][0] < bc2['best'] < bc2['ci'][1], True)
check('Box-Cox interval: SSE at its ends is the likelihood-ratio threshold', all(abs(float(np.interp(v, bc2['lambda'], bc2['sse'])) - thr) / thr < 2e-3 for v in bc2['ci']), True)
# Freq: JMP's degrees of freedom (the rows counted that many times)
fq = rng.integers(1, 4, 30)
xf = rng.normal(size=30)
yf = 1 + 2 * xf + rng.normal(size=30)
t6 = table({'x': xf.tolist(), 'y': yf.tolist(), 'f': fq.tolist()})
rf = call('fitmodel.ls', table=t6, y='y', effects=[['x']], freq='f')
big = pd.DataFrame({'x': xf, 'y': yf}).loc[lambda d_: d_.index.repeat(fq)]
fb = smf.ols('y ~ x', big).fit()
check.near('Freq: std errors as the expanded rows', rows_of(rf['estimates'])['x']['se'], float(fb.bse['x']), rel=1e-10)
check('Freq: error df = sum of frequencies - 2', {x['source']: x for x in rf['anova']['rows']}['Error']['df'], float(fq.sum() - 2))
# lack of fit with replicates, against models.lack_of_fit
xr = np.repeat([1.0, 2, 3, 4, 5], 4)
yr = 2 + 0.5 * xr + 0.3 * (xr - 3) ** 2 + rng.normal(0, 0.2, 20)
t7 = table({'x': xr.tolist(), 'y': yr.tolist()})
rl = call('fitmodel.ls', table=t7, y='y', effects=[['x']])
mr = fit_model._ls_model(t7, None, fit_model._spec(y='y', effects=[['x']]))
ref_lof = models.lack_of_fit(mr['d'], mr['res'])
check.near('Lack of Fit = models.lack_of_fit', rl['lof']['rows'][0]['f'], ref_lof['rows'][0]['f'], rel=1e-12)
check.near('Max RSq', rl['lof']['max_rsquare'], ref_lof['max_rsquare'], rel=1e-12)
# the profiler: the prediction and its interval at the current values
pr = call('fitmodel.profile', table=tid, kind='ls', y='yield', effects=E, current={'fertilizer': 'C', 'water': 'high', 'light': 7.5})
pt = pd.DataFrame({'f': ['C'], 'w': pd.Categorical(['high'], ['low', 'high']), 'l': [7.5]})
sfp = ref.get_prediction(pt).summary_frame()
check.near('profiler prediction', pr['responses'][0]['current']['pred'], float(sfp['mean'].iloc[0]), rel=1e-12)
check.near('profiler lower limit', pr['responses'][0]['current']['lower'], float(sfp['mean_ci_lower'].iloc[0]), rel=1e-12)
tr = [t_ for t_ in pr['responses'][0]['traces'] if t_['factor'] == 'light'][0]
check('profiler trace: 41 points over the range', (len(tr['x']), round(tr['x'][0], 9), round(tr['x'][-1], 9)), (41, round(light[ok].min(), 9), round(light[ok].max(), 9)))
trf = [t_ for t_ in pr['responses'][0]['traces'] if t_['factor'] == 'fertilizer'][0]
check('profiler trace of a categorical factor: its levels', trf['x'], ['A', 'B', 'C'])
check.near('profiler trace value at level C = the current prediction', trf['pred'][2], pr['responses'][0]['current']['pred'], rel=1e-12)
it = call('fitmodel.interaction', table=tid, kind='ls', y='yield', effects=E)
cell = [c for c in it['cells'] if it['factors'][c['row']] == 'water' and it['factors'][c['col']] == 'fertilizer'][0]
check.near('interaction plot: the LS mean of C,high', cell['lines'][1]['y'][2], lsi['lsmean'][5], rel=1e-9)
# Stepwise: forward by p-values, as F tests of nested least squares fits
st = call('fitmodel.stepwise', table=tid, y='yield', effects=E, action='step', heredity='none')
# JMP's stepwise takes an effect's columns in and out of the full design (an interaction keeps its product columns)
Xf = ref.model.exog
yfull = ref.model.endog
sl = ref.model.data.design_info.term_name_slices
term_of = ['C(f, Sum)', 'C(w, Sum)', 'l', 'C(f, Sum):C(w, Sum)', f'I((l - {lm!r}) ** 2)']
ecols = [list(range(sl[t_].start, sl[t_].stop)) for t_ in term_of]


def sub(combo):
    return sm.OLS(yfull, Xf[:, [0] + [c for i in combo for c in ecols[i]]]).fit()


f0 = sub(())
cands = {i: float(sub((i,)).compare_f_test(f0)[1]) for i in range(len(E))}
first = min(cands, key=cands.get)
check('stepwise: the first step enters the most significant effect', st['entered'], [first])
check.near('stepwise: its Sig Prob', st['history'][0]['p'], cands[first], rel=1e-8)
cur = {c['effect']: c for c in st['current']}
sse = st['stats']['sse']
nn = len(df)
kk = st['stats']['p'] + 1
ll = -0.5 * nn * (math.log(2 * math.pi * sse / nn) + 1)
check.near('stepwise AICc counts the error variance', st['stats']['aicc'], -2 * ll + 2 * kk + 2 * kk * (kk + 1) / (nn - kk - 1), rel=1e-12)
full = smf.ols(ref.model.formula, df).fit()
check.near("stepwise Cp = SSE/MSE(full) - (n - 2p)", st['stats']['cp'], sse / full.mse_resid - (nn - 2 * st['stats']['p']), rel=1e-9)
go = call('fitmodel.stepwise', table=tid, y='yield', effects=E, action='go', heredity='none', p_enter=0.25)
check('stepwise go: every entered effect has p below 0.25 when it entered', all(h['p'] < 0.25 for h in go['history']), True)
check('stepwise go: nothing left to enter below 0.25', all((c['p'] is None or c['p'] >= 0.25) for c in go['current'] if not c['entered']), True)
bk = call('fitmodel.stepwise', table=tid, y='yield', effects=E, action='go', direction='backward', heredity='none', p_leave=0.1)
check('stepwise backward: the entered effects have p below 0.1', all(c['p'] < 0.1 for c in bk['current'] if c['entered']), True)
ai = call('fitmodel.stepwise', table=tid, y='yield', effects=E, action='go', rule='aicc', heredity='none')
allfits = {combo: sub(combo) for size in range(0, len(E) + 1) for combo in itertools.combinations(range(len(E)), size)}
check('stepwise AICc go: the model with the smallest AICc on its path', ai['stats']['aicc'] <= min(h['aicc'] for h in ai['history']) + 1e-9, True)
am = call('fitmodel.all_models', table=tid, y='yield', effects=E, per_size=1)
for row in am['models']:
    best = max((c for c in allfits if len(c) == row['number']), key=lambda c: allfits[c].rsquared)
    check.near(f'All Possible Models: best RSquare with {row["number"]} effects', row['rsq'], float(allfits[best].rsquared), rel=1e-10)
tog = call('fitmodel.stepwise', table=tid, y='yield', effects=E, entered=[0], action='toggle', index=2, heredity='none')
check('stepwise: an Entered box enters the effect', tog['entered'], [0, 2])
# heredity: restrict keeps the interaction out until both its effects are in
rs = call('fitmodel.stepwise', table=tid, y='yield', effects=E, entered=[0], action='show', heredity='restrict')
check('stepwise restrict rule: the state is reported', rs['entered'], [0])

# ---- a continuous column crossed with a factor, x + g + x*g (analysis of covariance, separate slopes) --------------
# JMP's design: 1, x, g[a], g[b], (x - m) g[a], (x - m) g[b]; checked against statsmodels fitted to that design by hand
na = 90
xa = rng.normal(5, 2, na)
ga = rng.choice(['a', 'b', 'c'], na)
ya = 1 + 0.8 * xa + (ga == 'b') * 1.5 + 0.4 * xa * (ga == 'c') + rng.normal(0, 1, na)
t20 = table({'x': xa.tolist(), 'g': ga.tolist(), 'y': ya.tolist()})
Ea = [['x'], ['g'], ['x', 'g']]
mx_ = xa.mean()
code_a = np.where(ga == 'a', 1.0, np.where(ga == 'c', -1.0, 0.0))
code_b = np.where(ga == 'b', 1.0, np.where(ga == 'c', -1.0, 0.0))
XJ = np.column_stack([np.ones(na), xa, code_a, code_b, (xa - mx_) * code_a, (xa - mx_) * code_b])
ra = call('fitmodel.ls', table=t20, y='y', effects=Ea)
check('x + g + x*g: the design is not singular', ra['singular'], False)
refj = sm.OLS(ya, XJ).fit()
ea = {r_['term']: r_ for r_ in ra['estimates']['rows']}
check('x + g + x*g: six parameters, JMP\'s names', [r_['term'] for r_ in ra['estimates']['rows']], ['Intercept', 'x', 'g[a]', 'g[b]', f'(x-{mx_:.6g})*g[a]', f'(x-{mx_:.6g})*g[b]'])
check.near('x + g + x*g: the Intercept at x = 0, as JMP', ea['Intercept']['estimate'], float(refj.params[0]), rel=1e-9)
check.near('x + g + x*g: its standard error', ea['Intercept']['se'], float(refj.bse[0]), rel=1e-9)
check.near('x + g + x*g: the slope of x', ea['x']['estimate'], float(refj.params[1]), rel=1e-9)
check.near('x + g + x*g: g[b]', ea['g[b]']['estimate'], float(refj.params[3]), rel=1e-9)
dfa = pd.DataFrame({'x': xa, 'g': ga, 'y': ya})
refa = smf.ols(f'y ~ I(x - {mx_!r}) + C(g, Sum) + I(x - {mx_!r}):C(g, Sum)', dfa).fit()
a3a = sm.stats.anova_lm(refa, typ=3)
eta = rows_of(ra['effect_tests'])
check('x + g + x*g: the crossing has 2 degrees of freedom', eta['x*g']['nparm'], 2)
check.near('x + g + x*g: its F = anova_lm type III', eta['x*g']['stat'], float(a3a.loc[f'I(x - {mx_!r}):C(g, Sum)', 'F']), rel=1e-9)
check.near('x + g + x*g: F of g (at the mean of x)', eta['g']['stat'], float(a3a.loc['C(g, Sum)', 'F']), rel=1e-9)
check.near('x + g + x*g: the fitted values', maxdiff(ra['diag']['predicted'], refj.fittedvalues), 0.0, abs_=1e-9)
ns, err = run_code(ra['code'], dfa, 'data')
check('x + g + x*g: the code runs', err, None)
if not err:
    check.near('and fits the same model', float(ns['fit'].rsquared), float(refj.rsquared), rel=1e-12)
ga_ = call('fitmodel.glm', table=t20, y='y', effects=Ea, dist='normal')
check.near('GLM x + g + x*g: the Intercept at x = 0', {r_['term']: r_ for r_ in ga_['estimates']}['Intercept']['estimate'], float(refj.params[0]), rel=1e-8)
cnta = rng.poisson(np.exp(0.2 + 0.1 * xa + 0.05 * xa * (ga == 'b')))
t21 = table({'x': xa.tolist(), 'g': ga.tolist(), 'c': cnta.tolist()})
gp_ = call('fitmodel.glm', table=t21, y='c', effects=Ea, dist='poisson')
rpj = sm.GLM(cnta, XJ, family=sm.families.Poisson()).fit()
gpe = {r_['term']: r_ for r_ in gp_['estimates']}
check.near('Poisson x + g + x*g: the Intercept at x = 0', gpe['Intercept']['estimate'], float(rpj.params[0]), rel=1e-7)
check.near('Poisson x + g + x*g: its standard error', gpe['Intercept']['se'], float(rpj.bse[0]), rel=1e-6)
check('Poisson x + g + x*g: the crossing\'s L-R test has 2 df', rows_of({'rows': gp_['effect_tests']})['x*g']['df'], 2)
yba = np.where(rng.uniform(size=na) < 1 / (1 + np.exp(-(xa - 5) * (1 + 0.5 * (ga == 'a')))), 'y', 'n')
t22 = table({'x': xa.tolist(), 'g': ga.tolist(), 'r': yba.tolist()})
lb_ = call('fitmodel.logistic', table=t22, y='r', effects=Ea, target='y')
rlj = sm.Logit((yba == 'y').astype(float), XJ).fit(disp=0)
lbe = {r_['term']: r_ for r_ in lb_['estimates']}
check.near('logistic x + g + x*g: the Intercept at x = 0', lbe['Intercept']['estimate'], float(rlj.params[0]), rel=1e-6)
check.near('logistic x + g + x*g: its standard error', lbe['Intercept']['se'], float(rlj.bse[0]), rel=1e-5)
yoa = np.array(['p', 'q', 'r'])[np.digitize(0.8 * xa + (ga == 'b') + rng.logistic(size=na), [3.5, 5])]
t23 = table({'x': xa.tolist(), 'g': ga.tolist(), 'o': yoa.tolist()}, types={'o': 'ordinal'}, levels={'o': ['p', 'q', 'r']})
lo_ = call('fitmodel.logistic', table=t23, y='o', effects=Ea)
roj = OrderedModel(pd.Series(pd.Categorical(yoa, ['p', 'q', 'r'], ordered=True)), XJ[:, 1:], distr='logit').fit(method='bfgs', disp=0, maxiter=2000)
thj = roj.model.transform_threshold_params(roj.params)
loe = {r_['term']: r_ for r_ in lo_['estimates']}
check.near('ordinal x + g + x*g: Intercept[p] at x = 0', loe['Intercept[p]']['estimate'], float(thj[1]), rel=1e-4)
check.near('ordinal x + g + x*g: the slope of x (JMP\'s sign)', loe['x']['estimate'], -float(roj.params.iloc[0]), rel=1e-4)
suba = np.repeat(np.arange(15), 6)
yma = ya + rng.normal(0, 1, 15)[suba]
t24 = table({'x': xa.tolist(), 'g': ga.tolist(), 'y': yma.tolist(), 's': [f's{i}' for i in suba]})
mm_ = call('fitmodel.mixed', table=t24, y='y', effects=Ea + [{'names': ['s'], 'random': True}])
rmj = sm.MixedLM(yma, XJ, groups=suba).fit(reml=True)
mme = {r_['term']: r_ for r_ in mm_['estimates']}
check.near('mixed x + g + x*g: the Intercept at x = 0', mme['Intercept']['estimate'], float(rmj.fe_params[0]), rel=1e-5)
check.near('mixed x + g + x*g: its standard error', mme['Intercept']['se'], float(rmj.bse_fe[0]), rel=1e-3)
gr_ = call('fitmodel.genreg', table=t20, y='y', effects=Ea, method='lasso', n_grid=25)
bj = np.array([e_['estimate'] for e_ in gr_['estimates']])   # Intercept, x, g[a], g[b], (x-m)*g[a], (x-m)*g[b], as XJ
check.near('Generalized Regression x + g + x*g: JMP\'s estimates give the report\'s predictions', maxdiff(gr_['diag']['predicted'], XJ @ bj), 0.0, abs_=1e-8)
swa = call('fitmodel.stepwise', table=t20, y='y', effects=Ea, action='enter_all')
check.near('stepwise x + g + x*g: the Intercept at x = 0', swa['intercept'], float(refj.params[0]), rel=1e-9)

# ---- Generalized Linear Model -----------------------------------------------------------------------
cnt = rng.poisson(np.exp(0.3 + 0.12 * light + (fert == 'B') * 0.4))
expo = rng.uniform(0.5, 2, n)
t8 = table({'fertilizer': fert.tolist(), 'light': light.tolist(), 'count': cnt.tolist(), 'logexp': np.log(expo).tolist()})
g1 = call('fitmodel.glm', table=t8, y='count', effects=[['fertilizer'], ['light']], dist='poisson', offset='logexp')
dfp = pd.DataFrame({'f': fert, 'l': light, 'c': cnt, 'o': np.log(expo)})
rp = smf.glm('c ~ C(f, Sum) + l', dfp, family=sm.families.Poisson(), offset=dfp['o']).fit()
ge = rows_of({'rows': g1['estimates']})
check.near('Poisson estimate light', ge['light']['estimate'], float(rp.params['l']), rel=1e-8)
check.near('Poisson std error light', ge['light']['se'], float(rp.bse['l']), rel=1e-7)
check.near('Poisson whole model L-R ChiSquare = 2 (llf - llnull)', g1['whole'][0]['lr'], float(2 * (rp.llf - rp.llnull)), rel=1e-8)
check.near('Poisson deviance', g1['gof'][1]['chisq'], float(rp.deviance), rel=1e-10)
check.near('Poisson Pearson', g1['gof'][0]['chisq'], float(rp.pearson_chi2), rel=1e-10)
r0 = smf.glm('c ~ l', dfp, family=sm.families.Poisson(), offset=dfp['o']).fit()
check.near('Poisson effect L-R test by refitting', rows_of({'rows': g1['effect_tests']})['fertilizer']['lr'], float(2 * (rp.llf - r0.llf)), rel=1e-7)
r1 = smf.glm('c ~ C(f, Sum)', dfp, family=sm.families.Poisson(), offset=dfp['o']).fit()
check.near('Poisson parameter L-R ChiSquare', ge['light']['lr'], float(2 * (rp.llf - r1.llf)), rel=1e-7)
check.near('Poisson Wald CI', ge['light']['lower'], float(rp.conf_int().loc['l', 0]), rel=1e-7)
k_ = len(rp.params)
check.near('Poisson AICc', g1['aicc'], float(-2 * rp.llf + 2 * k_ + 2 * k_ * (k_ + 1) / (n - k_ - 1)), rel=1e-10)
g2 = call('fitmodel.glm', table=t8, y='count', effects=[['fertilizer'], ['light']], dist='poisson', offset='logexp', overdispersion=True)
rpx = smf.glm('c ~ C(f, Sum) + l', dfp, family=sm.families.Poisson(), offset=dfp['o']).fit(scale='X2')
check.near('overdispersion: std errors scaled (statsmodels scale="X2")', rows_of({'rows': g2['estimates']})['light']['se'], float(rpx.bse['l']), rel=1e-7)
check.near('overdispersion: LR divided by Pearson/DF', g2['whole'][0]['lr'], g1['whole'][0]['lr'] / (rp.pearson_chi2 / rp.df_resid), rel=1e-8)
# normal with identity link: the LR test is n log(SSE0/SSE)
gn = call('fitmodel.glm', table=tid, y='yield', effects=E, dist='normal')
check.near('normal GLM: L-R ChiSquare = n log(SSE0/SSE)', gn['whole'][0]['lr'], float(nn * math.log(full.centered_tss / full.ssr)), rel=1e-9)
check.near('normal GLM estimates = OLS', rows_of({'rows': gn['estimates']})['light']['estimate'], float(full.params['l']), rel=1e-9)
# gamma, log link, on statsmodels' Scotland data
sc = sm.datasets.scotland.load_pandas().data
t9 = table({c: sc[c].tolist() for c in sc.columns})
xs_ = ['COUTAX', 'UNEMPF', 'MOR', 'ACT', 'GDP', 'AGE', 'COUTAX_FEMALEUNEMP']
gg = call('fitmodel.glm', table=t9, y='YES', effects=[[c] for c in xs_], dist='gamma', link='log')
rg = sm.GLM(sc['YES'], sm.add_constant(sc[xs_]), family=sm.families.Gamma(sm.families.links.Log())).fit()
check.near('gamma (Scotland) estimate COUTAX', rows_of({'rows': gg['estimates']})['COUTAX']['estimate'], float(rg.params['COUTAX']), rel=1e-6)
check.near('gamma std error AGE', rows_of({'rows': gg['estimates']})['AGE']['se'], float(rg.bse['AGE']), rel=1e-6)
rg0 = sm.GLM(sc['YES'], np.ones((len(sc), 1)), family=sm.families.Gamma(sm.families.links.Log())).fit()
check.near('gamma LR: scaled deviance difference', gg['whole'][0]['lr'], float((rg0.deviance - rg.deviance) / rg.scale), rel=1e-6)
# binomial with events and trials, on statsmodels' Star98 data
s98 = sm.datasets.star98.load_pandas()
ex = s98.exog[['LOWINC', 'PERASIAN', 'PERBLACK', 'PERHISP']]
ev = s98.endog['NABOVE']
tr_ = s98.endog['NABOVE'] + s98.endog['NBELOW']
t10 = table({'events': ev.tolist(), 'trials': tr_.tolist(), **{c: ex[c].tolist() for c in ex}})
gb = call('fitmodel.glm', table=t10, y=['events', 'trials'], effects=[[c] for c in ex], dist='binomial')
rb = sm.GLM(s98.endog[['NABOVE', 'NBELOW']], sm.add_constant(ex), family=sm.families.Binomial()).fit()
check.near('binomial events/trials (Star98) estimate LOWINC', rows_of({'rows': gb['estimates']})['LOWINC']['estimate'], float(rb.params['LOWINC']), rel=1e-8)
check.near('binomial events/trials deviance', gb['gof'][1]['chisq'], float(rb.deviance), rel=1e-9)
# negative binomial: statsmodels' NB2
cnb = rng.negative_binomial(2, 2 / (2 + np.exp(1 + 0.15 * light)))
t11 = table({'light': light.tolist(), 'c': cnb.tolist()})
gnb = call('fitmodel.glm', table=t11, y='c', effects=[['light']], dist='negbin')
rnb = sm.NegativeBinomial(cnb, sm.add_constant(light), loglike_method='nb2').fit(disp=0, method='bfgs', maxiter=500)
check.near('negative binomial estimate', rows_of({'rows': gnb['estimates']})['light']['estimate'], float(rnb.params[1]), rel=1e-4)
check.near('negative binomial alpha', rows_of({'rows': gnb['estimates']})['Dispersion (alpha)']['estimate'], float(rnb.params[2]), rel=1e-3)
# the GLM profiler: the mean from the inverse link, the interval from the linear predictor's
pg = call('fitmodel.profile', table=t8, kind='glm', y='count', effects=[['fertilizer'], ['light']], dist='poisson', offset='logexp',
          current={'fertilizer': 'B', 'light': 6.0})
pp = rp.get_prediction(pd.DataFrame({'f': ['B'], 'l': [6.0]}), offset=np.zeros(1)).summary_frame()
check.near('GLM profiler prediction (offset 0)', pg['responses'][0]['current']['pred'], float(pp['mean'].iloc[0]), rel=1e-7)
check.near('GLM profiler lower limit', pg['responses'][0]['current']['lower'], float(pp['mean_ci_lower'].iloc[0]), rel=1e-6)

# ---- Nominal and Ordinal Logistic -------------------------------------------------------------------------
sp = sm.datasets.spector.load_pandas().data
t12 = table({'GPA': sp['GPA'].tolist(), 'TUCE': sp['TUCE'].tolist(), 'PSI': sp['PSI'].tolist(), 'GRADE': sp['GRADE'].tolist()},
            types={'GRADE': 'nominal'})
lg = call('fitmodel.logistic', table=t12, y='GRADE', effects=[['GPA'], ['TUCE'], ['PSI']], target=1)
greene = {'Intercept': -13.0213, 'GPA': 2.8261, 'TUCE': 0.0952, 'PSI': 2.3787}
le = {x['term']: x for x in lg['estimates']}
for k, v in greene.items():
    check.near(f'logit (Spector and Mazzeo) {k}: Greene\'s estimate', le[k]['estimate'], v, abs_=6e-4)
rl_ = sm.Logit(sp['GRADE'], sm.add_constant(sp[['GPA', 'TUCE', 'PSI']])).fit(disp=0)
check.near('logit std error GPA = sm.Logit', le['GPA']['se'], float(rl_.bse['GPA']), rel=1e-6)
check.near('logit whole model ChiSquare', lg['whole'][0]['chisq'], float(rl_.llr), rel=1e-8)
check.near('logit RSquare (U) = McFadden', lg['rsquare_u'], float(rl_.prsquared), rel=1e-8)
lg0 = call('fitmodel.logistic', table=t12, y='GRADE', effects=[['GPA'], ['TUCE'], ['PSI']])
check('logit: by default the first level is the target (JMP)', lg0['target'], '0')
check.near('logit with the first level as target: signs flip', {x['term']: x for x in lg0['estimates']}['GPA']['estimate'], -le['GPA']['estimate'], rel=1e-7)
from scipy.stats import mannwhitneyu
p1 = arr([row[1] for row in lg['probs']['prob']])
yb = sp['GRADE'].to_numpy()
u = mannwhitneyu(p1[yb == 1], p1[yb == 0]).statistic
check.near('ROC area = Mann-Whitney U / (n1 n0)', lg['roc'][0]['auc'], float(u / ((yb == 1).sum() * (yb == 0).sum())), rel=1e-12)
pred_ = (p1 > 0.5).astype(int)
check.near('misclassification rate', lg['fit']['misclass'], float(np.mean(pred_ != yb)), rel=1e-12)
check('confusion matrix total', float(np.sum(lg['confusion']['matrix'])), float(len(yb)))
ou = [o for o in lg['odds']['unit'] if o['term'] == 'GPA'][0]
check.near('unit odds ratio = exp(estimate)', ou['unit'], math.exp(le['GPA']['estimate']), rel=1e-12)
rl0 = sm.Logit(sp['GRADE'], sm.add_constant(sp[['TUCE', 'PSI']])).fit(disp=0)
check.near('effect likelihood ratio test (GPA)', {x['source']: x for x in lg['effect_tests']}['GPA']['lr'], float(2 * (rl_.llf - rl0.llf)), rel=1e-7)
lp = call('fitmodel.logistic', table=t12, y='GRADE', effects=[['GPA']], target=1)
check('logistic plot for one continuous X', lp['plot'] is not None and len(lp['plot']['points']['rows']) == len(sp), True)
# multinomial: anes96 party identification, the last level the reference as in JMP
an96 = sm.datasets.anes96.load_pandas().data
t13 = table({'PID': an96['PID'].tolist(), 'logpopul': an96['logpopul'].tolist(), 'age': an96['age'].tolist(), 'educ': an96['educ'].tolist()},
            types={'PID': 'nominal'})
mn = call('fitmodel.logistic', table=t13, y='PID', effects=[['logpopul'], ['age'], ['educ']])
codes = an96['PID'].astype(int).to_numpy()
yl = np.where(codes == codes.max(), 0, codes + 1)
rm = sm.MNLogit(yl, sm.add_constant(an96[['logpopul', 'age', 'educ']].to_numpy())).fit(disp=0)
first_logit = [x for x in mn['estimates'] if x['logit'] == '0/6']
check.near('MNLogit (anes96) estimate age, log odds 0/6', {x['term']: x for x in first_logit}['age']['estimate'], float(rm.params[2, 0]), rel=1e-6)
check.near('MNLogit std error', {x['term']: x for x in first_logit}['age']['se'], float(rm.bse[2, 0]), rel=1e-5)
check.near('MNLogit whole model ChiSquare', mn['whole'][0]['chisq'], float(rm.llr), rel=1e-7)
rm0 = sm.MNLogit(yl, sm.add_constant(an96[['logpopul', 'educ']].to_numpy())).fit(disp=0)
check.near('MNLogit effect LR test', {x['source']: x for x in mn['effect_tests']}['age']['lr'], float(2 * (rm.llf - rm0.llf)), rel=1e-6)
check.near('MNLogit probabilities sum to one', float(np.max(np.abs(arr([sum(row) for row in mn['probs']['prob']]) - 1))), 0.0, abs_=1e-12)
# ordinal: OrderedModel, in JMP's signs
yo_lat = 1.1 * light + (fert == 'B') * 0.8 + rng.logistic(size=n)
yo_c = np.digitize(yo_lat, [5.5, 7, 8.5])
lvls = ['low', 'mid', 'high', 'top']
t14 = table({'light': light.tolist(), 'fertilizer': fert.tolist(), 'score': [lvls[i] for i in yo_c]}, types={'score': 'ordinal'}, levels={'score': lvls})
od = call('fitmodel.logistic', table=t14, y='score', effects=[['light'], ['fertilizer']])
Xo = pd.DataFrame({'light': light, 'fA': (fert == 'A') * 1.0 - (fert == 'C'), 'fB': (fert == 'B') * 1.0 - (fert == 'C')})
ro = OrderedModel(pd.Series(pd.Categorical([lvls[i] for i in yo_c], lvls, ordered=True)), Xo, distr='logit').fit(method='bfgs', disp=0, maxiter=2000)
oe = {x['term']: x for x in od['estimates']}
check.near('ordinal logistic: JMP\'s light = -statsmodels\'', oe['light']['estimate'], -float(ro.params['light']), rel=1e-4)
th = ro.model.transform_threshold_params(ro.params)
check.near('ordinal logistic: Intercept[mid] = the second threshold', oe['Intercept[mid]']['estimate'], float(th[2]), rel=1e-4)
check.near('ordinal logistic: whole model ChiSquare', od['whole'][0]['chisq'], float(2 * (ro.llf - ro.llnull)), rel=1e-6)
check.near('ordinal std error of light', oe['light']['se'], float(ro.bse['light']), rel=1e-3)
prd = ro.predict(Xo.iloc[:3])
check.near('ordinal probabilities = OrderedModel.predict', float(np.max(np.abs(np.array(od['probs']['prob'][:3]) - np.asarray(prd)))), 0.0, abs_=1e-5)
po = call('fitmodel.profile', table=t14, kind='logistic', y='score', effects=[['light'], ['fertilizer']], current={'light': 7, 'fertilizer': 'A'})
check('ordinal profiler: one response per level', [x['name'] for x in po['responses']], ['Prob[low]', 'Prob[mid]', 'Prob[high]', 'Prob[top]'])
check.near('ordinal profiler probabilities sum to one', sum(x['current']['pred'] for x in po['responses']), 1.0, rel=1e-12)

# ---- Mixed Model (REML) ----------------------------------------------------------------------------------------
a, n0 = 12, 10
gi = np.repeat(np.arange(a), n0)
yr_ = 2 + rng.normal(0, 1.5, a)[gi] + rng.normal(0, 1, a * n0)
t15 = table({'g': [f'G{i:02d}' for i in gi], 'y': yr_.tolist()})
mx = call('fitmodel.mixed', table=t15, y='y', effects=[{'names': ['g'], 'random': True}])
dfm = pd.DataFrame({'y': yr_, 'g': gi.astype(str)})
means = dfm.groupby('g').y.mean()
msb = n0 * float(((means - yr_.mean()) ** 2).sum()) / (a - 1)
mse = float(((dfm.y - dfm.g.map(means)) ** 2).sum()) / (a * (n0 - 1))
vc = {x['effect']: x for x in mx['varcomp']}
check.near('one-way random: REML = ANOVA estimate of the group variance', vc['g']['var'], (msb - mse) / n0, rel=2e-3)
check.near('one-way random: residual variance = MSE', vc['Residual']['var'], mse, rel=2e-4)
check.near('variance component std error: REML information (textbook formula)', vc['g']['se'],
           math.sqrt(2 / n0 ** 2 * (msb ** 2 / (a - 1) + mse ** 2 / (a * (n0 - 1)))), rel=2e-3)
check.near('intercept DFDen (Satterthwaite) = a - 1', mx['estimates'][0]['dfden'], a - 1, rel=1e-6)
rf_ = smf.mixedlm('y ~ 1', dfm, groups='g').fit(reml=True)
check.near('-2 Residual Log Likelihood = statsmodels\' REML llf', mx['fit']['m2rll'], -2 * float(rf_.llf), rel=1e-9)
check.near('Pct of Total', vc['g']['pct'], 100 * vc['g']['var'] / (vc['g']['var'] + vc['Residual']['var']), rel=1e-12)
# a split plot: a whole-plot factor tested on the subjects
subj = np.repeat(np.arange(12), 6)
trt = np.repeat(['A', 'B', 'C'], 24)
tm = np.tile(np.arange(6.0), 12)
ysp = 10 + (trt == 'B') * 1.0 + 0.4 * tm + rng.normal(0, 1.2, 12)[subj] + rng.normal(0, 0.8, 72)
t16 = table({'subject': [f's{i}' for i in subj], 'trt': trt.tolist(), 'time': tm.tolist(), 'y': ysp.tolist()})
sp2 = call('fitmodel.mixed', table=t16, y='y', effects=[{'names': ['trt']}, {'names': ['time']}, {'names': ['subject'], 'random': True}])
ts = {x['source']: x for x in sp2['tests']}
check.near('split plot: the whole-plot factor\'s DFDen = subjects - levels', ts['trt']['dfden'], 9.0, rel=1e-6)
check.near('split plot: the within factor\'s DFDen = the residual df', ts['time']['dfden'], 72 - 12 - 1, rel=1e-6)
dsp = pd.DataFrame({'y': ysp, 'trt': trt, 'time': tm, 'subject': subj.astype(str)})
rsp = smf.mixedlm('y ~ C(trt, Sum) + time', dsp, groups='subject').fit(reml=True)
check.near('mixed fixed effect estimate = MixedLM', {x['term']: x for x in sp2['estimates']}['time']['estimate'], float(rsp.fe_params['time']), rel=1e-6)
check.near('mixed fixed effect std error = MixedLM', {x['term']: x for x in sp2['estimates']}['time']['se'], float(rsp.bse_fe['time']), rel=1e-4)
check.near('mixed conditional predictions = MixedLM fittedvalues', maxdiff(sp2['diag']['predicted'], rsp.fittedvalues), 0.0, abs_=1e-4)
# the REML information, Satterthwaite's derivatives, the BLUPs and the log-likelihood (the module avoids n x n
# matrices by Woodbury's identity) against the same quantities computed densely here
for label_, tbl_, eff_ in [('split plot', t16, [{'names': ['trt']}, {'names': ['time']}, {'names': ['subject'], 'random': True}])]:
    mm = fit_model._mixed_model(tbl_, None, fit_model._spec(y='y', effects=eff_))
    Xd, yd, s2d = mm['X'], mm['y'], mm['scale']
    nd = len(yd)
    Vd = s2d * np.eye(nd) + sum(c['var'] * c['Z'] @ c['Z'].T for c in mm['comps'])
    Vi = np.linalg.inv(Vd)
    Cd = np.linalg.inv(Xd.T @ Vi @ Xd)
    Pd = Vi - Vi @ Xd @ Cd @ Xd.T @ Vi
    Vks = [c['Z'] @ c['Z'].T for c in mm['comps']] + [np.eye(nd)]
    Id = np.array([[0.5 * np.trace(Pd @ Va @ Pd @ Vb) for Vb in Vks] for Va in Vks])
    check.near(f'{label_}: REML information (Woodbury = dense)', float(np.max(np.abs(mm['dense']['info'] - Id)) / np.max(np.abs(Id))), 0.0, abs_=1e-9)
    dCd = [Cd @ Xd.T @ Vi @ Va @ Vi @ Xd @ Cd for Va in Vks]
    check.near(f'{label_}: derivatives of (X\'V^-1X)^-1', max(float(np.max(np.abs(a_ - b_))) for a_, b_ in zip(mm['dense']['dC'], dCd)), 0.0, abs_=1e-10)
    bd = Cd @ Xd.T @ Vi @ yd
    rd = yd - Xd @ bd
    lld = -0.5 * ((nd - np.linalg.matrix_rank(Xd)) * math.log(2 * math.pi) + np.linalg.slogdet(Vd)[1] + np.linalg.slogdet(Xd.T @ Vi @ Xd)[1] + rd @ Vi @ rd)
    check.near(f'{label_}: REML log-likelihood', mm['dense']['llr'], float(lld), rel=1e-10)
    blup_d = mm['comps'][0]['var'] * mm['comps'][0]['Z'].T @ Vi @ rd
    check.near(f'{label_}: BLUPs', float(np.max(np.abs(mm['dense']['blups'][0] - blup_d))), 0.0, abs_=1e-10)
    # the REML score is zero at the estimates: the variance components are an interior maximum
    score = [-0.5 * (np.trace(Pd @ Va) - rd @ Vi @ Va @ Vi @ rd) for Va in Vks]
    check.near(f'{label_}: the REML score vanishes at statsmodels\' estimates', float(np.max(np.abs(score))), 0.0, abs_=2e-3)
# crossed random effects: one group with a variance component each, as statsmodels takes them
op = np.tile(np.repeat(np.arange(4), 3), 10)
part = np.repeat(np.arange(10), 12)
ycr = 5 + rng.normal(0, 1, 4)[op] + rng.normal(0, 2, 10)[part] + rng.normal(0, 0.5, 120)
t17 = table({'operator': [f'o{i}' for i in op], 'part': [f'p{i}' for i in part], 'y': ycr.tolist()})
cr = call('fitmodel.mixed', table=t17, y='y', effects=[{'names': ['operator'], 'random': True}, {'names': ['part'], 'random': True}])
dcr = pd.DataFrame({'y': ycr, 'op': op.astype(str), 'part': part.astype(str), 'one': 1})
rcr = smf.mixedlm('y ~ 1', dcr, groups='one', re_formula='0', vc_formula={'op': '0 + C(op)', 'part': '0 + C(part)'}).fit(reml=True)
vcc = {x['effect']: x['var'] for x in cr['varcomp']}
check.near('crossed random effects: operator variance = MixedLM', vcc['operator'], float(rcr.vcomp[list(rcr.model.exog_vc.names).index('op')]), rel=1e-3)
check.near('crossed random effects: part variance = MixedLM', vcc['part'], float(rcr.vcomp[list(rcr.model.exog_vc.names).index('part')]), rel=1e-3)

# ---- MANOVA -------------------------------------------------------------------------------------------------
Y2 = np.column_stack([yv, light + rng.normal(0, 1, n), rng.normal(size=n) + (fert == 'C')])
okm = np.isfinite(Y2).all(axis=1)
t18 = table({'y1': Y2[:, 0].tolist(), 'y2': Y2[:, 1].tolist(), 'y3': Y2[:, 2].tolist(), 'fertilizer': fert.tolist(), 'water': water.tolist()})
mv = call('fitmodel.manova', table=t18, y=['y1', 'y2', 'y3'], effects=[['fertilizer'], ['water'], ['fertilizer', 'water']])
from statsmodels.multivariate.manova import MANOVA
dmv = pd.DataFrame({'y1': Y2[:, 0], 'y2': Y2[:, 1], 'y3': Y2[:, 2], 'f': fert, 'w': water})[okm]
rmv = MANOVA.from_formula('y1 + y2 + y3 ~ C(f, Sum) * C(w, Sum)', dmv).mv_test()
tf = {x['effect']: {r_['test']: r_ for r_ in x['rows']} for x in mv['tests']}
refst = rmv.results['C(f, Sum)']['stat']
check.near("MANOVA Wilks' Lambda (fertilizer)", tf['fertilizer']["Wilks' Lambda"]['value'], float(refst.loc["Wilks' lambda", 'Value']), rel=1e-9)
check.near("MANOVA Pillai's Trace F", tf['fertilizer']["Pillai's Trace"]['f'], float(refst.loc["Pillai's trace", 'F Value']), rel=1e-9)
check.near('MANOVA Hotelling-Lawley p', tf['fertilizer']['Hotelling-Lawley']['p'], float(refst.loc['Hotelling-Lawley trace', 'Pr > F']), rel=1e-7)
Em, Hm = np.array(mv['E']), np.array(mv['H']['fertilizer'])
check.near("Wilks' Lambda = det(E)/det(E + H)", tf['fertilizer']["Wilks' Lambda"]['value'], float(np.linalg.det(Em) / np.linalg.det(Em + Hm)), rel=1e-9)
uni = {u_['y']: {r_['source']: r_ for r_ in u_['rows']} for u_ in mv['univariate']}
r_y2 = smf.ols('y2 ~ C(f, Sum) * C(w, Sum)', dmv).fit()
check.near('univariate test of fertilizer on y2', uni['y2']['fertilizer']['f'], float(sm.stats.anova_lm(r_y2, typ=3).loc['C(f, Sum)', 'F']), rel=1e-9)

# ---- Generalized Regression -----------------------------------------------------------------------------------
nr = 120
Xr = rng.normal(size=(nr, 6))
yg = 1 + Xr @ np.array([2.0, -1.5, 0, 0, 0.8, 0]) + rng.normal(size=nr)
t19 = table({**{f'x{i}': Xr[:, i].tolist() for i in range(6)}, 'y': yg.tolist()})
Eg = [[f'x{i}'] for i in range(6)]
gr = call('fitmodel.genreg', table=t19, y='y', effects=Eg, method='ridge', n_grid=20)
Z = (Xr - Xr.mean(0)) / Xr.std(0)
lam = gr['model']['lambda']
bz = np.linalg.solve(Z.T @ Z / nr + lam * np.eye(6), Z.T @ (yg - yg.mean()) / nr)
check.near('ridge: the closed-form solution on the scaled predictors', float(np.max(np.abs(arr([s['estimate'] for s in gr['scaled'][1:]]) - bz))), 0.0, abs_=2e-4)
gl = call('fitmodel.genreg', table=t19, y='y', effects=Eg, method='lasso', n_grid=30)
check('lasso: the path starts with every term out', gl['path']['nonzero'][0], 0)
check('lasso: the chosen model minimises AICc', gl['chosen'], int(np.nanargmin(arr(gl['path']['aicc']))))
zero = {e['term']: e['zero'] for e in gl['estimates']}
check('lasso keeps the three true terms', [zero[f'x{i}'] for i in (0, 1, 4)], [False, False, False])
Zc = np.column_stack([np.ones(nr), Z])
alpha_c = gl['path']['alpha'][gl['chosen']]
rr = sm.OLS(yg, Zc).fit_regularized(method='elastic_net', alpha=np.r_[0, np.full(6, alpha_c)], L1_wt=1.0)
check.near('lasso estimates = statsmodels fit_regularized', float(np.max(np.abs(arr([s['estimate'] for s in gl['scaled']]) - rr.params))), 0.0, abs_=1e-4)
orig = {e['term']: e['estimate'] for e in gl['estimates']}
check.near('original-scale estimate = scaled / sd', orig['x0'], float(rr.params[1] / Xr[:, 0].std()), rel=1e-3)
gc = call('fitmodel.genreg', table=t19, y='y', effects=Eg, method='lasso', n_grid=30, choose=5)
check('a chosen step', gc['chosen'], 5)

# ---- the Python under each result runs on the table exported as CSV, and computes what the report shows -------------
plants = pd.DataFrame({'fertilizer': fert, 'water': water, 'light': light, 'yield': yv})
rc = call('fitmodel.ls', table=tid, y='yield', effects=E, table_name='plants')
ns, err = run_code(rc['code'], plants, 'plants')
check('Standard Least Squares code runs', err, None)
if not err:
    got = {r_['term']: r_['estimate'] for r_ in rc['estimates']['rows']}
    check.near('its fit has the report\'s estimates (light)', float(ns['fit'].params.filter(like='light').iloc[0]), got['light'], rel=1e-9)
    check.near('its fit has the report\'s RSquare', float(ns['fit'].rsquared), {x['stat']: x['value'] for x in rc['summary']['rows']}['RSquare'], rel=1e-12)
rw = call('fitmodel.ls', table=tid, y='yield', effects=E, rows=list(range(50)), table_name='plants')
ns, err = run_code(rw['code'], plants, 'plants')
check('code of a row subset runs', err, None)
if not err:
    check('and fits the same rows', int(ns['fit'].nobs), rw['n_rows'])
for fn, kw in [('fitmodel.compare', {'effect': 'fertilizer', 'method': 'tukey'}), ('fitmodel.compare', {'effect': 'fertilizer*water', 'method': 'student'}),
               ('fitmodel.boxcox', {}), ('fitmodel.stepwise', {'action': 'show'})]:
    rr = call(fn, table=tid, y='yield', effects=E, table_name='plants', **kw)
    ns, err = run_code(rr['code'], plants, 'plants')
    check(f'{fn} code runs ({kw.get("effect", "")})', err, None)
    if fn == 'fitmodel.compare' and not err:
        lsr = call('fitmodel.ls', table=tid, y='yield', effects=E)['lsmeans'][kw['effect']]
        check.near(f'its LS means are the report\'s ({kw["effect"]})', float(np.max(np.abs(ns['lsm'] - np.array(lsr['lsmean'])))), 0.0, abs_=1e-9)
rg1 = call('fitmodel.glm', table=t8, y='count', effects=[['fertilizer'], ['light']], dist='poisson', offset='logexp', table_name='counts')
counts = pd.DataFrame({'fertilizer': fert, 'light': light, 'count': cnt, 'logexp': np.log(expo)})
ns, err = run_code(rg1['code'], counts, 'counts')
check('GLM code runs', err, None)
if not err:
    check.near('its fit has the report\'s deviance', float(ns['fit'].deviance), rg1['gof'][1]['chisq'], rel=1e-9)
rnb_ = call('fitmodel.glm', table=t11, y='c', effects=[['light']], dist='negbin', table_name='nb')
ns, err = run_code(rnb_['code'], pd.DataFrame({'light': light, 'c': cnb}), 'nb')
check('negative binomial code runs', err, None)
spector = sp[['GPA', 'TUCE', 'PSI', 'GRADE']]
rl1 = call('fitmodel.logistic', table=t12, y='GRADE', effects=[['GPA'], ['TUCE'], ['PSI']], table_name='spector')
ns, err = run_code(rl1['code'], spector, 'spector')
check('binary logistic code runs', err, None)
if not err:
    check.near('its fit has the report\'s -LogLikelihood', float(-ns['fit'].llf), rl1['whole'][1]['nll'], rel=1e-8)
rm1 = call('fitmodel.logistic', table=t13, y='PID', effects=[['logpopul'], ['age'], ['educ']], table_name='anes')
ns, err = run_code(rm1['code'], an96[['PID', 'logpopul', 'age', 'educ']], 'anes')
check('multinomial logistic code runs', err, None)
if not err:
    check.near('its fit has the report\'s -LogLikelihood', float(-ns['fit'].llf), rm1['whole'][1]['nll'], rel=1e-7)
ro1 = call('fitmodel.logistic', table=t14, y='score', effects=[['light'], ['fertilizer']], table_name='scores')
ns, err = run_code(ro1['code'], pd.DataFrame({'light': light, 'fertilizer': fert, 'score': [lvls[i] for i in yo_c]}), 'scores')
check('ordinal logistic code runs', err, None)
if not err:
    check.near('its fit has the report\'s -LogLikelihood', float(-ns['fit'].llf), ro1['whole'][1]['nll'], rel=1e-5)
mx1 = call('fitmodel.mixed', table=t16, y='y', effects=[{'names': ['trt']}, {'names': ['time']}, {'names': ['subject'], 'random': True}], table_name='split')
ns, err = run_code(mx1['code'], pd.DataFrame({'subject': [f's{i}' for i in subj], 'trt': trt, 'time': tm, 'y': ysp}), 'split')
check('mixed model code runs', err, None)
if not err:
    check.near('its fit has the report\'s -2 residual log likelihood', float(-2 * ns['fit'].llf), mx1['fit']['m2rll'], rel=1e-6)
cr1 = call('fitmodel.mixed', table=t17, y='y', effects=[{'names': ['operator'], 'random': True}, {'names': ['part'], 'random': True}], table_name='gauge')
ns, err = run_code(cr1['code'], pd.DataFrame({'operator': [f'o{i}' for i in op], 'part': [f'p{i}' for i in part], 'y': ycr}), 'gauge')
check('crossed random effects code runs', err, None)
if not err:
    check.near('its fit has the report\'s -2 residual log likelihood', float(-2 * ns['fit'].llf), cr1['fit']['m2rll'], rel=1e-5)
mv1 = call('fitmodel.manova', table=t18, y=['y1', 'y2', 'y3'], effects=[['fertilizer'], ['water'], ['fertilizer', 'water']], table_name='mv')
ns, err = run_code(mv1['code'], pd.DataFrame({'y1': Y2[:, 0], 'y2': Y2[:, 1], 'y3': Y2[:, 2], 'fertilizer': fert, 'water': water}), 'mv')
check('MANOVA code runs', err, None)
gr1 = call('fitmodel.genreg', table=t19, y='y', effects=Eg, method='lasso', n_grid=30, table_name='gr')
ns, err = run_code(gr1['code'], pd.DataFrame({**{f'x{i}': Xr[:, i] for i in range(6)}, 'y': yg}), 'gr')
check('Generalized Regression code runs', err, None)
if not err:
    check.near('its fit has the report\'s scaled estimate of x0', float(ns['fit'].params[1]), {e_['term']: e_['estimate'] for e_ in gr1['scaled']}['x0'], abs_=1e-3)

# ---- rows: a subset, and every row (rows None) -----------------------------------------------------------------
rs1 = call('fitmodel.ls', table=tid, y='yield', effects=E, rows=list(range(40)))
check('a row subset uses those rows', rs1['n_rows'], 39)
check('code of a row subset keeps those rows', 'df.loc[' in rs1['code'] or 'df.drop(' in rs1['code'], True)
check('the code names the table', 'read_csv' in r['code'] and 'C(fertilizer, Sum' in r['code'], True)
bad = None
try:
    call('fitmodel.ls', table=t13, y='PID', effects=[['age']])
except Exception as e:
    bad = str(e)
check('a categorical Y is refused by least squares', bad is not None and 'continuous' in bad, True)
# ======================================================================================================================
# Generalized Estimating Equations, Robust Standard Errors, Regression Diagnostics
# ======================================================================================================================
import statsmodels
from statsmodels.genmod import cov_struct as cs
from statsmodels.genmod.generalized_estimating_equations import GEE
from statsmodels.stats import diagnostic as dg
from statsmodels.stats.stattools import jarque_bera, omni_normtest

SMRES = os.path.join(os.path.dirname(statsmodels.__file__), 'genmod', 'tests', 'results')   # data that ship with statsmodels


def est_of(r_):
    return {x['term']: x for x in r_['estimates']}


def err_of(fn, **kw):
    try:
        call(fn, **kw)
    except Exception as e_:  # the message the report shows
        return str(e_)
    return None


# ---- statsmodels' documented GEE example: epil (the GEE page; release 0.6), Poisson, exchangeable ----------------------
epil = pd.read_csv(os.path.join(SMRES, 'epil.csv'))
t_ep = table({'y': epil['y'].tolist(), 'trt': epil['trt'].tolist(), 'base': epil['base'].tolist(), 'age': epil['age'].tolist(),
              'subject': epil['subject'].tolist()})
gep = call('fitmodel.gee', table=t_ep, y='y', effects=[['age'], ['trt'], ['base']], subject='subject', dist='poisson', corr='exchangeable')
eep = est_of(gep)
# printed there (treatment coding): Intercept 0.5730, trt[T.progabide] -0.1519 (0.171, z -0.888), age 0.0223 (0.011, z 1.960),
# base 0.0226 (0.001, z 18.451); JMP's effect coding has trt[placebo] = minus half that difference, the intercept at the average level
check.near('GEE epil, the documented example: age 0.0223', eep['age']['estimate'], 0.0223, abs_=5e-5)
check.near('GEE epil: age robust std error 0.011', eep['age']['se'], 0.011, abs_=5e-4)
check.near('GEE epil: age z 1.960', eep['age']['z'], 1.960, abs_=5e-4)
check.near('GEE epil: base 0.0226', eep['base']['estimate'], 0.0226, abs_=5e-5)
check.near('GEE epil: base z 18.451', eep['base']['z'], 18.451, abs_=5e-4)
check.near('GEE epil: trt[placebo] (effect coded) = 0.1519 / 2', eep['trt[placebo]']['estimate'], 0.1519 / 2, abs_=5e-5)
check.near('GEE epil: its robust std error = 0.171 / 2', eep['trt[placebo]']['se'], 0.171 / 2, abs_=2.5e-4)
check.near('GEE epil: its z = 0.888, the sign turned', eep['trt[placebo]']['z'], 0.888, abs_=5e-4)
check.near('GEE epil: the Intercept (effect coding) = 0.5730 - 0.1519 / 2', eep['Intercept']['estimate'], 0.5730 - 0.1519 / 2, abs_=1e-4)
m_ep = gep['model']
check('GEE epil: 236 rows, 59 subjects of 4, 2 iterations, converged, scale 1',
      (m_ep['n'], m_ep['subjects'], m_ep['size_min'], m_ep['size_max'], m_ep['iterations'], m_ep['converged'], m_ep['scale']), (236, 59, 4, 4, 2, True, 1.0))
ep2 = epil.copy()
ep2['trt'] = pd.Categorical(ep2['trt'], ['placebo', 'progabide'])
dep_ = smf.gee('y ~ age + C(trt, Sum) + base', 'subject', ep2, cov_struct=cs.Exchangeable(), family=sm.families.Poisson()).fit()
check.near('GEE epil: trt[placebo] = statsmodels\' GEE called directly', eep['trt[placebo]']['estimate'], float(dep_.params['C(trt, Sum)[S.placebo]']), rel=1e-10)
check.near('GEE epil: its robust std error', eep['trt[placebo]']['se'], float(dep_.bse['C(trt, Sum)[S.placebo]']), rel=1e-9)
check.near('GEE epil: the naive std error of base', eep['base']['se_naive'], float(np.asarray(dep_.standard_errors('naive'))[list(dep_.params.index).index('base')]), rel=1e-9)
check.near('GEE epil: the exchangeable correlation', gep['dep']['rows'][0]['value'], float(dep_.model.cov_struct.dep_params), rel=1e-9)
check.near('GEE epil: the Pearson residuals', maxdiff(gep['diag']['pearson'], dep_.resid_pearson), 0.0, abs_=1e-9)
check.near('GEE epil: the residuals, y - the marginal mean', maxdiff(gep['diag']['residual'], dep_.resid), 0.0, abs_=1e-9)
check('GEE epil: log link, so rate ratios', gep['ratios']['kind'], 'Rate Ratios')
rr_ep = [x for x in gep['ratios']['levels'] if x['level1'] == 'progabide'][0]
check.near('GEE epil: rate ratio progabide/placebo = exp(-0.1519)', rr_ep['ratio'], math.exp(float(dep_.params['C(trt, Sum)[S.placebo]']) * -2), rel=1e-9)

# ---- R's gee package, the values statsmodels' test suite records (statsmodels' gee_logistic_1 and gee_poisson_1 data) ----
Zl = np.genfromtxt(os.path.join(SMRES, 'gee_logistic_1.csv'), delimiter=',')
t_rl = table({'id': Zl[:, 0].tolist(), 'y': Zl[:, 1].tolist(), 'x1': Zl[:, 2].tolist(), 'x2': Zl[:, 3].tolist(), 'x3': Zl[:, 4].tolist()})
R_cf = [[0.0167272965285882, 1.13038654425893, -1.86896345082962, 1.09397608331333],
        [0.0178982283915449, 1.13118798191788, -1.86133518416017, 1.08944256230299]]
R_se = [[0.127291720283049, 0.166725808326067, 0.192430061340865, 0.173141068839597],
        [0.127045031730155, 0.165470678232842, 0.192052750030501, 0.173174779369249]]
for j, corr_ in enumerate(['independence', 'exchangeable']):
    rgl = call('fitmodel.gee', table=t_rl, y='y', effects=[['x1'], ['x2'], ['x3']], subject='id', dist='binomial', corr=corr_)
    check.near(f'GEE logistic ({corr_}) = R\'s gee: the coefficients', maxdiff([x['estimate'] for x in rgl['estimates']], R_cf[j]), 0.0, abs_=1e-6)
    check.near(f'GEE logistic ({corr_}) = R\'s gee: the robust std errors', maxdiff([x['se'] for x in rgl['estimates']], R_se[j]), 0.0, abs_=1e-6)
Zp = np.genfromtxt(os.path.join(SMRES, 'gee_poisson_1.csv'), delimiter=',')
t_rp = table({'id': Zp[:, 0].tolist(), 'y': Zp[:, 1].tolist(), **{f'x{k}': Zp[:, 1 + k].tolist() for k in range(1, 6)}})
Rp_cf = [[-0.0364450410793481, -0.0543209391301178, 0.0156642711741052, 0.57628591338724, -0.00465659951186211, -0.477093153099256],
         [-0.0315615554826533, -0.0562589480840004, 0.0178419412298561, 0.571512795340481, -0.00363255566297332, -0.475971696727736]]
Rp_se = [[0.0611309237214186, 0.0390680524493108, 0.0334234174505518, 0.0366860768962715, 0.0304758505008105, 0.0316348058881079],
         [0.0610840153582275, 0.0376887268649102, 0.0325168379415177, 0.0369786751362213, 0.0296141014225009, 0.0306115470200955]]
for j, corr_ in enumerate(['independence', 'exchangeable']):
    rgp = call('fitmodel.gee', table=t_rp, y='y', effects=[[f'x{k}'] for k in range(1, 6)], subject='id', dist='poisson', corr=corr_)
    check.near(f'GEE Poisson ({corr_}) = R\'s gee: the coefficients', maxdiff([x['estimate'] for x in rgp['estimates']], Rp_cf[j]), 0.0, abs_=1e-5)
    check.near(f'GEE Poisson ({corr_}) = R\'s gee: the robust std errors', maxdiff([x['se'] for x in rgp['estimates']], Rp_se[j]), 0.0, abs_=1e-6)

# ---- a simulated trial, 60 subjects x 4 visits, its rows shuffled: the report sorts a subject's rows by time -------------
ls_rng = np.random.default_rng(2026)
NG, NT = 60, 4
sj = np.repeat(np.arange(NG), NT)
vis = np.tile(np.arange(1, NT + 1), NG).astype(float)
arm = np.where(ls_rng.permutation(np.repeat([0, 1], NG // 2))[sj] == 1, 'active', 'placebo')
bl = ls_rng.normal(20, 5, NG)[sj]
eta_ = -1.1 + 0.25 * vis + 0.55 * (arm == 'active') * (vis - 1) + 0.08 * (bl - 20) + ls_rng.normal(0, 1.3, NG)[sj]
impv = np.where(ls_rng.uniform(size=NG * NT) < 1 / (1 + np.exp(-eta_)), 'yes', 'no')
cnts = ls_rng.poisson(np.exp(1.7 - 0.08 * vis - 0.18 * (arm == 'active') * (vis - 1) + 0.035 * (bl - 20) + ls_rng.normal(0, 0.45, NG)[sj]))
ear = np.zeros(NG * NT)
for g_ in range(NG):
    x_ = ls_rng.normal(0, 4)
    for t_ in range(NT):
        if t_:
            x_ = 0.6 * x_ + ls_rng.normal(0, 4 * math.sqrt(1 - 0.36))
        ear[g_ * NT + t_] = x_
scr = 40 + 0.6 * (bl - 20) - 1.2 * vis - 2.2 * (arm == 'active') * (vis - 1) + ear
lt = pd.DataFrame({'subject': [f'S{i + 1:02d}' for i in sj], 'clinic': [f'C{c + 1:02d}' for c in sj // 6], 'treatment': arm, 'visit': vis,
                   'baseline': bl, 'improved': impv, 'symptoms': cnts, 'score': scr, 'lexp': np.log(ls_rng.uniform(0.5, 2, NG * NT))})
lt = lt.iloc[ls_rng.permutation(NG * NT)].reset_index(drop=True)
t_lt = table({c: lt[c].tolist() for c in lt.columns}, levels={'treatment': ['placebo', 'active'], 'improved': ['yes', 'no']})
Elt = [['treatment'], ['visit'], ['baseline']]
st_ = lt.sort_values(['subject', 'visit'], kind='stable')
X_st = np.column_stack([np.ones(len(st_)), np.where(st_['treatment'] == 'placebo', 1.0, -1.0), st_['visit'], st_['baseline']])   # JMP's coding
X_lt = np.column_stack([np.ones(len(lt)), np.where(lt['treatment'] == 'placebo', 1.0, -1.0), lt['visit'], lt['baseline']])
yb_st = (st_['improved'] == 'yes').to_numpy(float)
gee_fits = {}
for corr_, struct_, kw_ in [('exchangeable', cs.Exchangeable(), {}), ('ar1', cs.Autoregressive(grid=False), {'time': st_['visit'].to_numpy()}),
                            ('unstructured', cs.Unstructured(), {'time': (st_['visit'].to_numpy() - 1).astype(int)}), ('independence', cs.Independence(), {})]:
    rep_ = call('fitmodel.gee', table=t_lt, y='improved', effects=Elt, subject='subject', time='visit', dist='binomial', corr=corr_)
    dir_ = GEE(yb_st, X_st, groups=st_['subject'].to_numpy(), family=sm.families.Binomial(), cov_struct=struct_, **kw_).fit()
    er_ = rep_['estimates']
    # AR(1)'s alpha is statsmodels' brent minimum (tolerance about 1.5e-8): a last bit elsewhere moves its ninth digit
    tol_ = 1e-7 if corr_ == 'ar1' else 1e-9
    check.near(f'GEE binomial {corr_}: estimates = statsmodels\' on the rows sorted by subject and visit', maxdiff([x['estimate'] for x in er_], dir_.params), 0.0, abs_=tol_)
    check.near(f'GEE binomial {corr_}: robust std errors', maxdiff([x['se'] for x in er_], dir_.bse), 0.0, abs_=tol_)
    check.near(f'GEE binomial {corr_}: naive std errors', maxdiff([x['se_naive'] for x in er_], dir_.standard_errors('naive')), 0.0, abs_=tol_)
    check.near(f'GEE binomial {corr_}: p-values (normal)', maxdiff([x['p'] for x in er_], dir_.pvalues), 0.0, abs_=tol_)
    check.near(f'GEE binomial {corr_}: confidence limits', maxdiff([x['lower'] for x in er_], np.asarray(dir_.conf_int())[:, 0]), 0.0, abs_=tol_)
    check(f'GEE binomial {corr_}: the iterations and convergence', (rep_['model']['iterations'], rep_['model']['converged']),
          (len(dir_.fit_history['params']), bool(dir_.converged)))
    gee_fits[corr_] = (rep_, dir_)
rar, dar = gee_fits['ar1']
rex, dex = gee_fits['exchangeable']
fit_by_row = dict(zip(st_.index.tolist(), np.asarray(dar.fittedvalues).tolist()))
check.near('GEE: each row\'s prediction goes back to its row of the (shuffled) table', max(abs(p_ - fit_by_row[r_]) for r_, p_ in zip(rar['diag']['rows'], rar['diag']['predicted'])), 0.0, abs_=1e-12)
check('GEE: the subject of each row', all(s_ == lt.loc[r_, 'subject'] for r_, s_ in zip(rar['diag']['rows'], rar['diag']['subject'])), True)
uns = GEE((lt['improved'] == 'yes').to_numpy(float), X_lt, groups=lt['subject'].to_numpy(), time=lt['visit'].to_numpy(), family=sm.families.Binomial(),
          cov_struct=cs.Autoregressive(grid=False)).fit()
check('GEE AR(1): statsmodels on the rows in table order gives other estimates (its working matrix counts positions): the report sorts',
      float(np.max(np.abs(uns.params - dar.params))) > 1e-6, True)
a_ar = float(dar.model.cov_struct.dep_params)
check.near('GEE AR(1): the dependence parameter (to brent\'s tolerance)', rar['dep']['rows'][0]['value'], a_ar, rel=1e-7)
a_rep = rar['dep']['rows'][0]['value']
check.near('GEE AR(1): the working correlation of a subject is alpha^|j - k|', float(np.max(np.abs(np.array(rar['dep']['matrix']['values']) - a_rep ** np.abs(np.subtract.outer(np.arange(4), np.arange(4)))))), 0.0, abs_=1e-12)
check('GEE AR(1): its rows labelled by visit', rar['dep']['matrix']['labels'], ['1', '2', '3', '4'])
run_, dun_ = gee_fits['unstructured']
check.near('GEE unstructured: the correlation of visits 1 and 3', [x for x in run_['dep']['rows'] if x['param'] == '1 and 3'][0]['value'], float(dun_.model.cov_struct.dep_params[0, 2]), rel=1e-12)
# QIC: statsmodels' qic() as it is, QICu, and Pan's penalty with the information of statsmodels' own independence model
for lab_, (rep_, dir_) in [('exchangeable', gee_fits['exchangeable']), ('AR(1)', gee_fits['ar1']), ('unstructured', gee_fits['unstructured'])]:
    q_ = rep_['qic']
    qsm_ = dir_.qic(scale=1.0)
    check.near(f'QIC ({lab_}): statsmodels\' qic() as the report shows it', q_['qic_sm'], float(qsm_[0]), rel=1e-10)
    check.near(f'QICu ({lab_}) = statsmodels\'', q_['qicu'], float(qsm_[1]), rel=1e-10)
    ind_ = GEE(yb_st, X_st, groups=st_['subject'].to_numpy(), family=sm.families.Binomial(), cov_struct=cs.Independence()).fit(
        start_params=np.asarray(dir_.params), maxiter=0, scale=1.0)
    omega_ = np.linalg.inv(np.asarray(ind_.cov_naive))   # statsmodels' model-based covariance of the independence model, at the same estimates
    check.near(f'QIC ({lab_}): Pan\'s penalty trace(Omega_I V_R) through statsmodels\' independence covariance', q_['trace'], float(np.trace(omega_ @ np.asarray(dir_.cov_robust))), rel=1e-9)
    check.near(f'QIC ({lab_}) = -2 Q + 2 trace', q_['qic'], -2 * q_['ql'] + 2 * q_['trace'], rel=1e-12)
q_rng = np.random.default_rng(99)
gq_ = np.repeat(np.arange(400), 4)
xq_ = q_rng.normal(size=1600)
t_q = table({'g': gq_.tolist(), 'x': xq_.tolist(), 'y': q_rng.poisson(np.exp(1.5 + 0.3 * xq_)).tolist()})
rq_ = call('fitmodel.gee', table=t_q, y='y', effects=[['x']], subject='g', dist='poisson', corr='independence')['qic']
pen_sm = (rq_['qic_sm'] + 2 * rq_['ql']) / 2
check('QIC, known truth: a right independence model has the penalty trace(Omega_I V_R) near p = 2', abs(rq_['trace'] - 2) < 0.5, True)
check('QIC, known truth: statsmodels\' qic() penalty is not near p (it leaves the variance function out)', abs(pen_sm - 2) > 3, True)
print(f'      QIC penalty for p = 2: Pan {rq_["trace"]:.3f}, statsmodels\' qic() {pen_sm:.3f}')
rnr = call('fitmodel.gee', table=t_lt, y='score', effects=Elt, subject='subject', time='visit', dist='normal', corr='ar1')
check.near('QIC for the normal family: Pan\'s = statsmodels\' qic() (the variance function is 1)', rnr['qic']['qic'], rnr['qic']['qic_sm'], rel=1e-10)
ind_n = GEE(st_['score'].to_numpy(float), X_st, groups=st_['subject'].to_numpy(), cov_struct=cs.Independence()).fit()
check.near('QIC for the normal family: at the scale of the independence fit', rnr['qic']['scale'], float(ind_n.scale), rel=1e-12)
check('... which the report says', rnr['qic']['source'], 'independence')
# the normal independence GEE is least squares with cluster-robust errors
rni = call('fitmodel.gee', table=t_lt, y='score', effects=Elt, subject='subject', dist='normal', corr='independence')
fo_ = sm.OLS(lt['score'].to_numpy(float), X_lt).fit()
check.near('GEE normal independence: the estimates are least squares\'', maxdiff([x['estimate'] for x in rni['estimates']], fo_.params), 0.0, abs_=1e-9)
check.near('GEE normal independence: the naive std errors are least squares\'', maxdiff([x['se_naive'] for x in rni['estimates']], fo_.bse), 0.0, abs_=1e-9)
fc_ = fo_.get_robustcov_results(cov_type='cluster', groups=pd.factorize(lt['subject'])[0], use_correction=False)
check.near('GEE normal independence: the robust std errors are the cluster-robust ones of least squares (no small-sample factor)',
           maxdiff([x['se'] for x in rni['estimates']], fc_.bse), 0.0, abs_=1e-9)
rpi = call('fitmodel.gee', table=t_lt, y='symptoms', effects=Elt, subject='subject', dist='poisson', corr='independence')
gpi = sm.GLM(lt['symptoms'].to_numpy(float), X_lt, family=sm.families.Poisson()).fit()
check.near('GEE Poisson independence: the estimates are the GLM\'s', maxdiff([x['estimate'] for x in rpi['estimates']], gpi.params), 0.0, abs_=1e-7)
# the covariances, the scale
for cov_ in ['naive', 'bias_reduced']:
    rcv = call('fitmodel.gee', table=t_lt, y='improved', effects=Elt, subject='subject', dist='binomial', corr='exchangeable', cov=cov_)
    dcv = GEE((lt['improved'] == 'yes').to_numpy(float), X_lt, groups=lt['subject'].to_numpy(), family=sm.families.Binomial(), cov_struct=cs.Exchangeable()).fit(cov_type=cov_)
    check.near(f'GEE {cov_} covariance: std errors = statsmodels\' fit(cov_type={cov_!r})', maxdiff([x['se'] for x in rcv['estimates']], dcv.bse), 0.0, abs_=1e-9)
    check.near(f'GEE {cov_} covariance: the robust ones beside them', maxdiff([x['se_robust'] for x in rcv['estimates']], dcv.standard_errors('robust')), 0.0, abs_=1e-9)
rsx = call('fitmodel.gee', table=t_lt, y='improved', effects=Elt, subject='subject', dist='binomial', corr='exchangeable', scale='estimated')
dsx = GEE((lt['improved'] == 'yes').to_numpy(float), X_lt, groups=lt['subject'].to_numpy(), family=sm.families.Binomial(), cov_struct=cs.Exchangeable()).fit(scale='X2')
check.near('GEE scale estimated: statsmodels\' fit(scale="X2")', rsx['model']['scale'], float(dsx.scale), rel=1e-12)
check.near('... = Pearson chi-square / (N - p)', rsx['model']['scale'], float(np.sum(np.asarray(dsx.resid_pearson) ** 2) / (len(lt) - 4)), rel=1e-9)
check('... and the report says so', rsx['model']['scale_kind'], 'estimated')
rsf = call('fitmodel.gee', table=t_lt, y='score', effects=Elt, subject='subject', dist='normal', corr='exchangeable', scale='fixed', scale_value=2)
dsf = GEE(lt['score'].to_numpy(float), X_lt, groups=lt['subject'].to_numpy(), cov_struct=cs.Exchangeable()).fit(scale=2.0)
check.near('GEE scale fixed at 2 (an integer from the page is taken as fixed): the naive std errors', maxdiff([x['se_naive'] for x in rsf['estimates']], dsf.standard_errors('naive')), 0.0, abs_=1e-9)
check('... the scale is 2', rsf['model']['scale'], 2.0)
# nested, offset, negative binomial, Tweedie
rne = call('fitmodel.gee', table=t_lt, y='symptoms', effects=Elt, subject='clinic', subgroup='subject', dist='poisson', corr='nested')
dne = GEE(lt['symptoms'].to_numpy(float), X_lt, groups=pd.factorize(lt['clinic'], sort=True)[0], family=sm.families.Poisson(), cov_struct=cs.Nested(),
          dep_data=pd.factorize(lt['subject'], sort=True)[0]).fit()
check.near('GEE nested (subjects in clinics): estimates', maxdiff([x['estimate'] for x in rne['estimates']], dne.params), 0.0, abs_=1e-9)
check.near('GEE nested: robust std errors', maxdiff([x['se'] for x in rne['estimates']], dne.bse), 0.0, abs_=1e-9)
check.near('GEE nested: the subject\'s variance component', rne['dep']['rows'][1]['value'], float(dne.model.cov_struct.vcomp_coeff[1]), rel=1e-9)
check('GEE nested: 10 clinics of 24 rows', (rne['model']['subjects'], rne['model']['size_max']), (10, 24))
roff = call('fitmodel.gee', table=t_lt, y='symptoms', effects=Elt, subject='subject', offset='lexp', dist='poisson', corr='exchangeable')
doff = GEE(lt['symptoms'].to_numpy(float), X_lt, groups=lt['subject'].to_numpy(), offset=lt['lexp'].to_numpy(), family=sm.families.Poisson(),
           cov_struct=cs.Exchangeable()).fit()
check.near('GEE with an offset: estimates', maxdiff([x['estimate'] for x in roff['estimates']], doff.params), 0.0, abs_=1e-9)
check.near('GEE with an offset: the marginal means', maxdiff(roff['diag']['predicted'], doff.fittedvalues), 0.0, abs_=1e-9)
rnb2 = call('fitmodel.gee', table=t_lt, y='symptoms', effects=Elt, subject='subject', dist='negbin', nb_alpha=0.5, corr='exchangeable')
dnb2 = GEE(lt['symptoms'].to_numpy(float), X_lt, groups=lt['subject'].to_numpy(), family=sm.families.NegativeBinomial(alpha=0.5), cov_struct=cs.Exchangeable()).fit()
check.near('GEE negative binomial (alpha 0.5): estimates', maxdiff([x['estimate'] for x in rnb2['estimates']], dnb2.params), 0.0, abs_=1e-9)
check.near('GEE negative binomial: robust std errors', maxdiff([x['se'] for x in rnb2['estimates']], dnb2.bse), 0.0, abs_=1e-9)
rtw = call('fitmodel.gee', table=t_lt, y='symptoms', effects=Elt, subject='subject', dist='tweedie', var_power=1.5, corr='exchangeable', scale='estimated')
dtw = GEE(lt['symptoms'].to_numpy(float), X_lt, groups=lt['subject'].to_numpy(), family=sm.families.Tweedie(link=sm.families.links.Log(), var_power=1.5),
          cov_struct=cs.Exchangeable()).fit(scale='X2')
check.near('GEE Tweedie (power 1.5): estimates', maxdiff([x['estimate'] for x in rtw['estimates']], dtw.params), 0.0, abs_=1e-9)
check.near('GEE Tweedie: the scale', rtw['model']['scale'], float(dtw.scale), rel=1e-10)
# effect tests, odds ratios, the profiler
et_ex = {x['source']: x for x in rex['effect_tests']}
check.near('GEE Effect Tests: the Wald chi-square of visit is its z squared', et_ex['visit']['wald'], est_of(rex)['visit']['z'] ** 2, rel=1e-10)
rcl = call('fitmodel.gee', table=t_lt, y='improved', effects=Elt + [['clinic']], subject='subject', dist='binomial', corr='exchangeable')
Dcl = patsy.dmatrix('C(treatment, Sum, levels=["placebo", "active"]) + visit + baseline + C(clinic, Sum)', lt)
dcl = GEE((lt['improved'] == 'yes').to_numpy(float), np.asarray(Dcl), groups=lt['subject'].to_numpy(), family=sm.families.Binomial(), cov_struct=cs.Exchangeable()).fit()
Lcl = np.eye(Dcl.shape[1])[Dcl.design_info.slice('C(clinic, Sum)')]   # patsy puts the categorical terms first
wcl = dcl.wald_test(Lcl, scalar=True)
etc = {x['source']: x for x in rcl['effect_tests']}['clinic']
check.near('GEE Effect Tests: the Wald chi-square of clinic (9 DF) = statsmodels\' wald_test', etc['wald'], float(wcl.statistic), rel=1e-9)
check('... on 9 DF, its p-value', (etc['df'], round(etc['p'], 12)), (9, round(float(wcl.pvalue), 12)))
ou_ = {x['term']: x for x in rex['ratios']['unit']}
check.near('GEE odds ratio per visit = exp(estimate)', ou_['visit']['ratio'], math.exp(est_of(rex)['visit']['estimate']), rel=1e-12)
ol_ = [x for x in rex['ratios']['levels'] if x['level1'] == 'placebo'][0]
b_pl, s_pl = est_of(rex)['treatment[placebo]']['estimate'], est_of(rex)['treatment[placebo]']['se']
check.near('GEE odds ratio placebo/active = exp(2 x treatment[placebo])', ol_['ratio'], math.exp(2 * b_pl), rel=1e-10)
check.near('... its lower limit from the robust std error', ol_['lower'], math.exp(2 * b_pl - 1.959963984540054 * 2 * s_pl), rel=1e-9)
check('GEE: the identity link has no ratios', rnr['ratios'], None)
pgp = call('fitmodel.profile', table=t_lt, kind='gee', y='improved', effects=Elt, subject='subject', time='visit', dist='binomial', corr='exchangeable',
           current={'treatment': 'active', 'visit': 3, 'baseline': 22})
xp_ = np.array([1.0, -1.0, 3.0, 22.0])
ep_ = float(xp_ @ np.asarray(dex.params))
sp_ = math.sqrt(float(xp_ @ np.asarray(dex.cov_params()) @ xp_))
check('GEE profiler: the response is Prob[yes]', pgp['responses'][0]['name'], 'Prob[yes]')
check.near('GEE profiler: the marginal prediction', pgp['responses'][0]['current']['pred'], 1 / (1 + math.exp(-ep_)), rel=1e-10)
check.near('GEE profiler: its lower limit, from the robust covariance', pgp['responses'][0]['current']['lower'], 1 / (1 + math.exp(-(ep_ - 1.959963984540054 * sp_))), rel=1e-9)
# Compare Working Correlations
cmpc = call('fitmodel.gee_compare', table=t_lt, y='improved', effects=Elt, subject='subject', time='visit', dist='binomial', corr='exchangeable')
cq_ = {x['key']: x for x in cmpc['rows']}
check('Compare Working Correlations: the structures the roles allow', [x['key'] for x in cmpc['rows']], ['independence', 'exchangeable', 'ar1', 'unstructured'])
check.near('Compare: the exchangeable line is its fit\'s QIC', cq_['exchangeable']['qic'], rex['qic']['qic'], rel=1e-12)
check.near('Compare: the AR(1) line is its fit\'s QIC', cq_['ar1']['qic'], rar['qic']['qic'], rel=1e-12)
check('Compare: the smallest QIC is marked', cmpc['best'], min(cq_, key=lambda k_: cq_[k_]['qic']))
check('Compare: the current working correlation is marked', [k_ for k_ in cq_ if cq_[k_]['current']], ['exchangeable'])
cmpn = call('fitmodel.gee_compare', table=t_lt, y='symptoms', effects=Elt, subject='clinic', subgroup='subject', dist='poisson', corr='nested')
check('Compare with a Subgroup and no Time: independence, exchangeable, nested', [x['key'] for x in cmpn['rows']], ['independence', 'exchangeable', 'nested'])
dup = lt.copy()
dup.loc[dup.index[(dup['subject'] == 'S01') & (dup['visit'] == 2)], 'visit'] = 1.0
t_dup = table({c: dup[c].tolist() for c in dup.columns}, levels={'treatment': ['placebo', 'active'], 'improved': ['yes', 'no']})
emsg = err_of('fitmodel.gee', table=t_dup, y='improved', effects=Elt, subject='subject', time='visit', dist='binomial', corr='unstructured')
check('Unstructured refuses a Time value twice within a subject', emsg is not None and 'at most once' in emsg, True)
cmpd = call('fitmodel.gee_compare', table=t_dup, y='improved', effects=Elt, subject='subject', time='visit', dist='binomial', corr='exchangeable')
check('Compare: the Unstructured line says why it is not fitted', 'at most once' in ({x['key']: x for x in cmpd['rows']}['unstructured'].get('error') or ''), True)
check('GEE without a Subject is refused', 'Subject' in (err_of('fitmodel.gee', table=t_lt, y='score', effects=Elt, dist='normal') or ''), True)
check('GEE AR(1) without a Time is refused', 'Time' in (err_of('fitmodel.gee', table=t_lt, y='score', effects=Elt, subject='subject', corr='ar1') or ''), True)
check('GEE with a Weight is refused', 'Weight' in (err_of('fitmodel.gee', table=t_lt, y='score', effects=Elt, subject='subject', weight='baseline') or ''), True)
check('GEE with a random effect is refused', 'Random' in (err_of('fitmodel.gee', table=t_lt, y='score', effects=[{'names': ['treatment']}, {'names': ['clinic'], 'random': True}], subject='subject') or ''), True)
rsub = call('fitmodel.gee', table=t_lt, y='score', effects=Elt, subject='subject', corr='exchangeable', rows=list(range(120)))
check('GEE on a row subset (a By group) uses those rows', (rsub['model']['n'], sorted(rsub['diag']['rows']) == list(range(120))), (120, True))
# the code under the fit runs on the exported table and gives the report's numbers
rcd = call('fitmodel.gee', table=t_lt, y='improved', effects=Elt, subject='subject', time='visit', dist='binomial', corr='ar1', table_name='trial')
ns, err = run_code(rcd['code'], lt, 'trial')
check('GEE code runs', err, None)
if not err:
    check.near('its fit has the report\'s estimates', maxdiff([x['estimate'] for x in rcd['estimates']], ns['fit'].params.to_numpy()), 0.0, abs_=1e-8)
    check.near('and its robust std errors', maxdiff([x['se'] for x in rcd['estimates']], ns['fit'].bse.to_numpy()), 0.0, abs_=1e-8)
    qpan = -2 * ns['fit'].model.qic(ns['b'], ns['scale'], ns['fit'].cov_params())[0] + 2 * np.trace(ns['Xa'].T @ (ns['Xa'] * ns['w'][:, None]) / ns['scale'] @ ns['fit'].cov_robust)
    check.near('and the report\'s QIC (Pan)', float(qpan), rcd['qic']['qic'], rel=1e-8)
ns, err = run_code(cmpc['code'], lt, 'data')
check('Compare Working Correlations code runs', err, None)
if not err:
    check.near('its last fit (unstructured) has the report\'s parameters', maxdiff([x['estimate'] for x in gee_fits['unstructured'][0]['estimates']], ns['fit'].params.to_numpy()), 0.0, abs_=1e-8)
rcn = call('fitmodel.gee', table=t_lt, y='symptoms', effects=Elt, subject='clinic', subgroup='subject', dist='poisson', corr='nested', table_name='trial')
ns, err = run_code(rcn['code'], lt, 'trial')
check('GEE nested code runs', err, None)
if not err:
    check.near('its fit has the report\'s estimates', maxdiff([x['estimate'] for x in rcn['estimates']], ns['fit'].params.to_numpy()), 0.0, abs_=1e-8)
rco = call('fitmodel.gee', table=t_lt, y='symptoms', effects=Elt, subject='subject', offset='lexp', dist='negbin', nb_alpha=0.5, corr='exchangeable', table_name='trial')
ns, err = run_code(rco['code'], lt, 'trial')
check('GEE negative binomial code with an offset runs', err, None)
if not err:
    check.near('its fit has the report\'s estimates', maxdiff([x['estimate'] for x in rco['estimates']], ns['fit'].params.to_numpy()), 0.0, abs_=1e-8)
emsg = err_of('fitmodel.gee', table=t_lt, y='symptoms', effects=Elt, subject='clinic', subgroup='subject', offset='lexp', dist='poisson', corr='nested')
check('a fit that statsmodels cannot make (nested with this offset diverges) says so, and what to try', emsg is not None and 'did not fit' in emsg and 'Compare Working Correlations' in emsg, True)

# the centred design x + g + x*g: GEE puts the intercept back at x = 0, as the other personalities
t20s = table({'x': xa.tolist(), 'g': ga.tolist(), 'y': ya.tolist(), 's': [f's{i // 6}' for i in range(na)]})
g20 = call('fitmodel.gee', table=t20s, y='y', effects=Ea, subject='s', dist='normal', corr='independence')
check.near('GEE x + g + x*g: the estimates are JMP\'s (least squares on its design, the intercept at x = 0)', maxdiff([x['estimate'] for x in g20['estimates']], refj.params), 0.0, abs_=1e-8)
g20e = GEE(ya, XJ, groups=np.arange(na) // 6, cov_struct=cs.Independence()).fit()
check.near('GEE x + g + x*g: the intercept\'s robust std error = statsmodels\' on JMP\'s design', g20['estimates'][0]['se'], float(g20e.bse[0]), rel=1e-8)
it20 = call('fitmodel.interaction', table=t20s, kind='gee', y='y', effects=Ea, subject='s', dist='normal', corr='exchangeable')
check('GEE: the interaction plots take the GEE fit', len(it20['cells']) > 0 and it20['response'] == 'y', True)
h20 = call('fitmodel.ls', table=t20, y='y', effects=Ea, robust='HC3')
check.near('HC3 on x + g + x*g: the intercept\'s robust std error = statsmodels\' HC3 on JMP\'s design', rows_of(h20['estimates'])['Intercept']['se'], float(refj.HC3_se[0]), rel=1e-9)
check.near('HC3 on x + g + x*g: the crossing\'s robust F = statsmodels\'', rows_of(h20['effect_tests'])['x*g']['stat'],
           float(np.squeeze(sm.OLS(ya, XJ).fit().get_robustcov_results(cov_type='HC3', use_t=True).f_test(np.eye(6)[4:]).fvalue)), rel=1e-9)

# ---- Robust Standard Errors: Stata's results, recorded in statsmodels' test suite, on statsmodels' macrodata and grunfeld ----
md_ = sm.datasets.macrodata.load_pandas().data
g_inv = 400 * np.diff(np.log(md_['realinv'].to_numpy()))
g_gdp = 400 * np.diff(np.log(md_['realgdp'].to_numpy()))
lint_ = md_['realint'].to_numpy()[:-1]
mac = pd.DataFrame({'g_inv': g_inv, 'g_gdp': g_gdp, 'lint': lint_})
t_mac = table({c: mac[c].tolist() for c in mac.columns})
Emac = [['g_gdp'], ['lint']]
ols_m = sm.OLS(g_inv, sm.add_constant(np.column_stack([g_gdp, lint_]))).fit()
h1 = call('fitmodel.ls', table=t_mac, y='g_inv', effects=Emac, robust='HC1')
e_h1 = rows_of(h1['estimates'])
stata_hc1 = {'g_gdp': (0.32355452428856, 13.519272136038, 5.703151404e-30), 'lint': (0.32772840315987, -1.8734933059173, 0.06246625509181),
             'Intercept': (1.3690593206013, -6.9256843965613, 5.860240898e-11)}
for k_, (se_, t_, p_) in stata_hc1.items():
    check.near(f'HC1 = Stata\'s regress, robust (macrodata): the std error of {k_}', e_h1[k_]['se'], se_, rel=1e-9)
    check.near(f'HC1 = Stata: the t ratio of {k_}', e_h1[k_]['t'], t_, rel=1e-9)
    check.near(f'HC1 = Stata: the p-value of {k_} (t on 199 DF)', e_h1[k_]['p'], p_, rel=1e-6)
check.near('HC1 = Stata: the whole model\'s robust Wald F', h1['robust']['wald_f'], 92.94502024547633, rel=1e-9)
check('HC1: the report says which covariance it uses', (h1['robust']['type'], 'HC1' in h1['robust']['label'], any('HC1' in n_ for n_ in h1['notes'])), ('HC1', True, True))
hac = call('fitmodel.ls', table=t_mac, y='g_inv', effects=Emac, robust={'type': 'HAC', 'maxlags': 4})
for k_, v_ in {'g_gdp': 0.32878742225811, 'lint': 0.29361854972141, 'Intercept': 1.1770944273439}.items():
    check.near(f'Newey-West, 4 lags = Stata\'s ivreg2 bw(5) (no small-sample factor): {k_}', rows_of(hac['estimates'])[k_]['se'], v_, rel=1e-9)
hac0 = call('fitmodel.ls', table=t_mac, y='g_inv', effects=Emac, robust={'type': 'HAC'})
check('Newey-West without a lag: 4 (n/100)^(2/9) lags', hac0['robust']['maxlags'], int(math.floor(4 * (202 / 100) ** (2 / 9))))
for t_ in ['HC0', 'HC2', 'HC3']:
    r_ = call('fitmodel.ls', table=t_mac, y='g_inv', effects=Emac, robust=t_)
    check.near(f'{t_} std errors = statsmodels\' {t_}_se', maxdiff([rows_of(r_['estimates'])[k_]['se'] for k_ in ['Intercept', 'g_gdp', 'lint']], getattr(ols_m, f'{t_}_se')), 0.0, abs_=1e-10)
gf = sm.datasets.grunfeld.load_pandas().data.iloc[:200]   # the ten firms of Stata's example
gfd = pd.DataFrame({'invest': gf['invest'], 'value': gf['value'], 'capital': gf['capital'], 'firm': gf['firm'].astype(str)})
t_gf = table({c: gfd[c].tolist() for c in gfd.columns})
clr = call('fitmodel.ls', table=t_gf, y='invest', effects=[['value'], ['capital']], robust={'type': 'cluster', 'cluster': 'firm'})
stata_cl = {'value': (0.01589433647768, 7.2706499090564, 4.710548549e-05), 'capital': (0.08496711097464, 2.7149150406994, 0.02380515903536),
            'Intercept': (20.425202580078, -2.0912580352272, 0.06604843284516)}
for k_, (se_, t_, p_) in stata_cl.items():
    check.near(f'Cluster by firm = Stata\'s regress, cluster(firm) (grunfeld): the std error of {k_}', rows_of(clr['estimates'])[k_]['se'], se_, rel=1e-6)
    check.near(f'Cluster = Stata: the t ratio of {k_}', rows_of(clr['estimates'])[k_]['t'], t_, rel=1e-6)
    check.near(f'Cluster = Stata: the p-value of {k_} (t on 10 - 1 DF)', rows_of(clr['estimates'])[k_]['p'], p_, rel=1e-5)
check('Cluster: 10 clusters, t and F tests on 9 DF', (clr['robust']['clusters'], clr['robust']['df'], rows_of(clr['effect_tests'])['value']['dfden']), (10, 9.0, 9.0))
check.near('Cluster = Stata: the whole model\'s robust Wald F', clr['robust']['wald_f'], 51.59060716590177, rel=1e-6)
ns, err = run_code(clr['code'], gfd, 'data')
check('cluster-robust code runs', err, None)
if not err:
    check.near('its robust std errors are the report\'s', maxdiff([rows_of(clr['estimates'])[k_]['se'] for k_ in ['Intercept', 'value', 'capital']], ns['rob'].bse), 0.0, abs_=1e-9)
hr = np.random.default_rng(12)
gh = hr.choice(['a', 'b', 'c'], 90)
xh = hr.normal(size=90)
yh = 1 + (gh == 'b') * 1.2 + 0.7 * xh + hr.normal(size=90) * (0.5 + np.abs(xh))
dfh = pd.DataFrame({'g': gh, 'x': xh, 'y': yh})
t_h = table({c: dfh[c].tolist() for c in dfh.columns})
rh3 = call('fitmodel.ls', table=t_h, y='y', effects=[['g'], ['x']], robust='HC3')
fh = smf.ols('y ~ C(g, Sum) + x', dfh).fit()
fh3 = fh.get_robustcov_results(cov_type='HC3', use_t=True)
wth = fh3.wald_test_terms(skip_single=False, scalar=True).table
check.near('HC3 Effect Tests: the F of g (2 DF) = statsmodels\' wald_test_terms', rows_of(rh3['effect_tests'])['g']['stat'], float(wth.loc['C(g, Sum)', 'statistic']), rel=1e-10)
check.near('HC3 Effect Tests: its p-value', rows_of(rh3['effect_tests'])['g']['p'], float(wth.loc['C(g, Sum)', 'pvalue']), rel=1e-9)
check('HC3 Effect Tests: no sums of squares, a DFDen', ('ss' in rh3['effect_tests']['rows'][0], rows_of(rh3['effect_tests'])['g']['dfden']), (False, 86.0))
check.near('HC3: the Analysis of Variance stays least squares\'', {x['source']: x for x in rh3['anova']['rows']}['Model']['f'], float(fh.fvalue), rel=1e-10)
prh = call('fitmodel.profile', table=t_h, kind='ls', y='y', effects=[['g'], ['x']], robust='HC3', current={'g': 'b', 'x': 0.5})
sfh = fh3.get_prediction(np.asarray(patsy.build_design_matrices([fh.model.data.design_info], pd.DataFrame({'g': ['b'], 'x': [0.5]}))[0]), transform=False).summary_frame(alpha=0.05)
check.near('HC3: the profiler\'s interval uses the robust covariance', prh['responses'][0]['current']['lower'], float(sfh['mean_ci_lower'].iloc[0]), rel=1e-10)
pr0 = call('fitmodel.profile', table=t_h, kind='ls', y='y', effects=[['g'], ['x']], current={'g': 'b', 'x': 0.5})
check('... not the usual one', abs(pr0['responses'][0]['current']['lower'] - prh['responses'][0]['current']['lower']) > 1e-6, True)
ns, err = run_code(rh3['code'], dfh, 'data')
check('HC3 code runs', err, None)
if not err:
    check.near('its robust std errors are the report\'s', maxdiff([x['se'] for x in rh3['estimates']['rows']], ns['rob'].bse), 0.0, abs_=1e-10)
rf_rob = call('fitmodel.ls', table=t6, y='y', effects=[['x']], freq='f', robust='HC1')
check('with Freq, no robust standard errors, and a note that says why', ('robust' in rf_rob, any('Freq' in n_ and 'Robust' in n_ for n_ in rf_rob['notes'])), (False, True))
rglc = call('fitmodel.glm', table=t_lt, y='symptoms', effects=Elt, dist='poisson', robust={'type': 'cluster', 'cluster': 'subject'})
gcl = sm.GLM(lt['symptoms'].to_numpy(float), X_lt, family=sm.families.Poisson()).fit(cov_type='cluster', cov_kwds={'groups': pd.factorize(lt['subject'], sort=True)[0]})
check.near('GLM cluster-robust std errors = statsmodels\' GLM fit(cov_type="cluster")', maxdiff([x['se'] for x in rglc['estimates']], gcl.bse), 0.0, abs_=1e-8)
check.near('GLM cluster-robust: the Wald chi-square of visit', {x['term']: x for x in rglc['estimates']}['visit']['wald'], float(gcl.tvalues[2] ** 2), rel=1e-8)
rgl0 = call('fitmodel.glm', table=t_lt, y='symptoms', effects=Elt, dist='poisson', robust='HC0')
gh0 = sm.GLM(lt['symptoms'].to_numpy(float), X_lt, family=sm.families.Poisson()).fit(cov_type='HC0')
check.near('GLM sandwich (HC0) std errors = statsmodels\'', maxdiff([x['se'] for x in rgl0['estimates']], gh0.bse), 0.0, abs_=1e-8)
check('GLM refuses HC3 (statsmodels\' GLM gives it as HC0)', 'HC0' in (err_of('fitmodel.glm', table=t_lt, y='symptoms', effects=Elt, dist='poisson', robust='HC3') or ''), True)
pgl = call('fitmodel.profile', table=t_lt, kind='glm', y='symptoms', effects=Elt, dist='poisson', robust='HC0', current={'treatment': 'active', 'visit': 2, 'baseline': 20})
xg_ = np.array([1.0, -1.0, 2.0, 20.0])
eg_ = float(xg_ @ gh0.params)
check.near('GLM profiler with HC0: the lower limit from the sandwich', pgl['responses'][0]['current']['lower'], math.exp(eg_ - 1.959963984540054 * math.sqrt(float(xg_ @ gh0.cov_params() @ xg_))), rel=1e-7)
ns, err = run_code(rglc['code'], lt, 'data')
check('GLM robust code runs', err, None)
if not err:
    check.near('its robust std errors are the report\'s', maxdiff([x['se'] for x in rglc['estimates']], ns['rob'].bse), 0.0, abs_=1e-7)

# ---- Regression Diagnostics: R's lmtest results, recorded in statsmodels' test suite, on the same macrodata regression ------
dmx = call('fitmodel.regdiag', table=t_mac, y='g_inv', effects=Emac, tests=['bp', 'white', 'gq', 'reset', 'hc', 'rainbow', 'bg', 'jb', 'omni'],
           gq_sort='row', rainbow_order='row', hc_order='row', bg_lags=4)
TD = {k_: v_['table']['rows'] for k_, v_ in dmx['tests'].items()}
check('Regression Diagnostics: every test made', [k_ for k_, v_ in dmx['tests'].items() if v_['error'] is None], ['bp', 'white', 'gq', 'reset', 'hc', 'rainbow', 'bg', 'jb', 'omni'])
check.near('Breusch-Pagan (Koenker) = R\'s bptest', TD['bp'][0]['stat'], 0.709924388395087, rel=1e-10)
check.near('Breusch-Pagan (Koenker): its p-value', TD['bp'][0]['p'], 0.701199952134347, rel=1e-9)
check.near('Breusch-Pagan (normal errors) = R\'s bptest(studentize = FALSE)', TD['bp'][1]['stat'], 1.302014063483341, rel=1e-10)
check.near('Breusch-Pagan (normal errors): its p-value', TD['bp'][1]['p'], 0.5215203247110649, rel=1e-9)
check('Breusch-Pagan: 2 DF', TD['bp'][0]['df'], 2)
check.near('Goldfeld-Quandt (the table\'s order, halves) = R\'s gqtest', TD['gq'][0]['stat'], 0.5313259064778423, rel=1e-10)
check.near('Goldfeld-Quandt: its p-value (variance increasing)', TD['gq'][0]['p'], 0.9990217851193723, rel=1e-9)
check('Goldfeld-Quandt: on 98 and 98 DF', (TD['gq'][0]['df'], TD['gq'][0]['dfden']), (98.0, 98.0))
check.near('Breusch-Godfrey LM, 4 lags = R\'s bgtest', TD['bg'][0]['stat'], 4.771042651230007, rel=1e-9)
check.near('Breusch-Godfrey LM: its p-value', TD['bg'][0]['p'], 0.3116067133066697, rel=1e-9)
check.near('Breusch-Godfrey F = R\'s bgtest(type = "F")', TD['bg'][1]['stat'], 1.179280833676792, rel=1e-9)
check.near('Breusch-Godfrey F: its p-value', TD['bg'][1]['p'], 0.321197487261203, rel=1e-9)
check('Breusch-Godfrey F: on 4 and 195 DF', (TD['bg'][1]['df'], TD['bg'][1]['dfden']), (4.0, 195.0))
check.near('Harvey-Collier = R\'s harvtest', TD['hc'][0]['stat'], 0.494432160939874, rel=1e-9)
check.near('Harvey-Collier: its p-value', TD['hc'][0]['p'], 0.6215491310408242, rel=1e-9)
check('Harvey-Collier: on 198 DF', TD['hc'][0]['df'], 198.0)
check.near('Rainbow (the table\'s order) = R\'s raintest', TD['rainbow'][0]['stat'], 0.6809600116739604, rel=1e-9)
check.near('Rainbow: its p-value', TD['rainbow'][0]['p'], 0.971832843583418, rel=1e-9)
check('Rainbow: on 101 and 98 DF', (TD['rainbow'][0]['df'], TD['rainbow'][0]['dfden']), (101.0, 98.0))
hw_ = dg.het_white(ols_m.resid, ols_m.model.exog)
check.near('White LM = statsmodels\' het_white', TD['white'][0]['stat'], float(hw_[0]), rel=1e-10)
check.near('White LM = statsmodels\' reference value', TD['white'][0]['stat'], 33.503722896538441, rel=1e-10)
check.near('White F and its p-value', TD['white'][1]['p'], float(hw_[3]), rel=1e-9)
check('White: 5 DF (the squares and products of 1, g_gdp, lint, less the constant)', TD['white'][0]['df'], 5)
rst_ = dg.linear_reset(ols_m, power=3, use_f=True)
check.near('RESET = statsmodels\' linear_reset', TD['reset'][0]['stat'], float(rst_.fvalue), rel=1e-10)
aug_ = sm.OLS(g_inv, np.column_stack([ols_m.model.exog, ols_m.fittedvalues ** 2, ols_m.fittedvalues ** 3])).fit()
check.near('RESET = the F test of the regression with the squared and cubed predictions added', TD['reset'][0]['stat'], float(aug_.compare_f_test(ols_m)[0]), rel=1e-7)
check('RESET: on 2 and 197 DF', (TD['reset'][0]['df'], TD['reset'][0]['dfden']), (2.0, 197.0))
check.near('Jarque-Bera = scipy\'s jarque_bera', TD['jb'][0]['stat'], float(stats.jarque_bera(ols_m.resid).statistic), rel=1e-10)
check.near('Jarque-Bera: its p-value = statsmodels\'', TD['jb'][0]['p'], float(jarque_bera(ols_m.resid)[1]), rel=1e-10)
check.near('Jarque-Bera: the kurtosis', TD['jb'][2]['stat'], float(stats.kurtosis(ols_m.resid, fisher=False)), rel=1e-10)
check.near('Omnibus = scipy\'s normaltest', TD['omni'][0]['stat'], float(stats.normaltest(ols_m.resid).statistic), rel=1e-10)
check.near('Omnibus = statsmodels\' omni_normtest (p)', TD['omni'][0]['p'], float(omni_normtest(ols_m.resid).pvalue), rel=1e-10)
o2_ = sm.OLS(g_inv, sm.add_constant(g_gdp)).fit()
hc2 = call('fitmodel.regdiag', table=t_mac, y='g_inv', effects=[['g_gdp']], tests=['hc'])['tests']['hc']['table']['rows'][0]
w2_ = dg.recursive_olsresiduals(o2_, alpha=0.95)[4][2:]
t2_ = float(np.mean(w2_) / (np.std(w2_, ddof=1) / math.sqrt(len(w2_))))
check.near('Harvey-Collier with two parameters: t on the n - p recursive residuals (Harvey and Collier 1977)', hc2['stat'], t2_, rel=1e-9)
check('Harvey-Collier with two parameters: on n - p - 1 = 199 DF', hc2['df'], 199.0)
check('statsmodels\' linear_harvey_collier differs here (it drops the first recursive residual)', abs(float(dg.linear_harvey_collier(o2_).statistic) - t2_) > 1e-3, True)
rb_ = call('fitmodel.regdiag', table=t_mac, y='g_inv', effects=Emac, tests=['rainbow'], rainbow_order='leverage')['tests']['rainbow']['table']['rows'][0]
hh_ = np.round(ols_m.get_influence().hat_matrix_diag, 12)
lo_ = int(np.ceil(0.25 * 202))
hi_ = int(np.floor(lo_ + 0.5 * 202))
cen_ = np.argsort(hh_, kind='stable')[:hi_ - lo_]
oc_ = sm.OLS(g_inv[cen_], ols_m.model.exog[cen_]).fit()
check.near('Rainbow by leverage = Utts\'s F, the central rows those of smallest leverage', rb_['stat'], ((ols_m.ssr - oc_.ssr) / (202 - len(cen_))) / (oc_.ssr / oc_.df_resid), rel=1e-10)
gq4 = call('fitmodel.regdiag', table=t_mac, y='g_inv', effects=Emac, tests=['gq'], gq_sort='predicted', gq_drop=0.2, gq_alt='two-sided')['tests']['gq']['table']['rows'][0]
o4_ = np.argsort(ols_m.fittedvalues, kind='stable')
s4_ = int(np.floor(202 * 0.8 / 2))
ref4 = dg.het_goldfeldquandt(g_inv[o4_], ols_m.model.exog[o4_], split=s4_, drop=202 - 2 * s4_, alternative='two-sided')
check.near('Goldfeld-Quandt sorted by the predicted values, a fifth left out, two-sided = statsmodels\'', gq4['stat'], float(ref4[0]), rel=1e-12)
check.near('... its p-value', gq4['p'], float(ref4[1]), rel=1e-10)
ns, err = run_code(dmx['code'], mac, 'data')
check('Regression Diagnostics code runs', err, None)
if not err:
    check.near('its Breusch-Pagan is the report\'s', float(dg.het_breuschpagan(ns['e'], ns['Xh'])[0]), TD['bp'][0]['stat'], rel=1e-10)
dml = call('fitmodel.regdiag', table=t_mac, y='g_inv', effects=Emac, tests=['rainbow'], rainbow_order='leverage')
ns, err = run_code(dml['code'], mac, 'data')
check('Rainbow by leverage code runs', err, None)
if not err:
    check.near('and gives the report\'s F', float(dg.linear_rainbow(ns['ow'], frac=ns['frac'], order_by=ns['o'])[0]), rb_['stat'], rel=1e-10)
wr = np.random.default_rng(31)
wts = wr.uniform(0.5, 3, 202)
t_w = table({**{c: mac[c].tolist() for c in mac.columns}, 'w': wts.tolist()})
rwd = call('fitmodel.regdiag', table=t_w, y='g_inv', effects=Emac, weight='w', tests=['bp', 'jb'])
fw_ = sm.WLS(g_inv, ols_m.model.exog, weights=wts).fit()
check.near('weighted fit: Breusch-Pagan on the whitened residuals and the regressors', rwd['tests']['bp']['table']['rows'][0]['stat'], float(dg.het_breuschpagan(fw_.wresid, fw_.model.exog)[0]), rel=1e-10)
check.near('weighted fit: Jarque-Bera on the whitened residuals', rwd['tests']['jb']['table']['rows'][0]['stat'], float(jarque_bera(fw_.wresid)[0]), rel=1e-10)
bad_order = call('fitmodel.regdiag', table=t_mac, y='g_inv', effects=Emac, tests=['gq'], gq_sort='nosuchcolumn')['tests']['gq']
check('an unknown sort column: the test says why', bad_order['error'] is not None and 'continuous factor' in bad_order['error'], True)
# the Influence Plot and the Component + Residual plots come with the least squares report
rc2 = call('fitmodel.ls', table=t_mac, y='g_inv', effects=Emac, ccpr=True)
check('the report gives the rank p for the influence plot\'s lines', rc2['rank'], 3)
inf_ = ols_m.get_influence()
check.near('Influence Plot: the studentized residuals = statsmodels\' resid_studentized_external', maxdiff(rc2['diag']['externally'], inf_.resid_studentized_external), 0.0, abs_=1e-10)
check.near('Influence Plot: Cook\'s D = statsmodels\' cooks_distance', maxdiff(rc2['diag']['cooks'], inf_.cooks_distance[0]), 0.0, abs_=1e-12)
cp_ = {c_['term']: c_ for c_ in rc2['ccpr']}
check('Component + Residual plots of the continuous terms', sorted(cp_), ['g_gdp', 'lint'])
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig_ = sm.graphics.plot_ccpr(ols_m, 1)
    pts_ = fig_.axes[0].lines[0].get_xydata()
    plt.close(fig_)
    check.near('Component + Residual of g_gdp = the points of statsmodels\' plot_ccpr', maxdiff(cp_['g_gdp']['partial'], pts_[:, 1]), 0.0, abs_=1e-10)
    check.near('... against the regressor', maxdiff(cp_['g_gdp']['x'], pts_[:, 0]), 0.0, abs_=1e-12)
except ImportError:
    check.near('Component + Residual of g_gdp = residual + b x (plot_ccpr\'s definition)', maxdiff(cp_['g_gdp']['partial'], ols_m.resid + ols_m.params[1] * g_gdp), 0.0, abs_=1e-10)
ra2 = call('fitmodel.ls', table=t20, y='y', effects=Ea, ccpr=True)
ca2 = {c_['term']: c_ for c_ in ra2['ccpr']}
check('a centred main effect (x + g + x*g) is plotted against x itself', (sorted(ca2), maxdiff(ca2['x']['x'], xa) < 1e-9), (['x'], True))
check.near('... its partial residual = residual + b (x - mean)', maxdiff(ca2['x']['partial'], np.asarray(refj.resid) + float(refj.params[1]) * (xa - xa.mean())), 0.0, abs_=1e-8)

# ======================================================================================================================
# Instrumental Variables, Quantile Regression, Recursive and Rolling Regression
# ======================================================================================================================
import importlib.util
from statsmodels.regression.quantile_regression import QuantReg
from statsmodels.regression.recursive_ls import RecursiveLS
from statsmodels.regression.rolling import RollingOLS, RollingWLS
from statsmodels.sandbox.regression.gmm import IV2SLS

SMDIR = os.path.dirname(statsmodels.__file__)


def load_results(*parts):
    """A results module of statsmodels' own test suite, from the installed package."""
    path = os.path.join(SMDIR, *parts)
    spec_ = importlib.util.spec_from_file_location('smres_' + parts[-1][:-3], path)
    mod_ = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod_)
    return mod_


# ---- 2SLS on Griliches's wage data, against Stata's ivreg2 and ivendog (the results statsmodels' test suite records) --------
rg = load_results('sandbox', 'regression', 'tests', 'results_ivreg2_griliches.py')
gri = pd.read_stata(os.path.join(SMDIR, 'sandbox', 'regression', 'tests', 'griliches76.dta'))
for yr_ in sorted(gri['year'].unique()):
    gri[f'dyear_{int(yr_) % 100}'] = (gri['year'] == yr_).astype(float)
g_dums = ['dyear_67', 'dyear_68', 'dyear_69', 'dyear_70', 'dyear_71', 'dyear_73']
g_cols = ['lw', 's', 'iq', 'expr', 'tenure', 'rns', 'smsa', 'med', 'kww', 'age', 'mrt'] + g_dums
t_gri = table({c: gri[c].astype(float).tolist() for c in g_cols})
E_gri = [[c] for c in ['s', 'iq', 'expr', 'tenure', 'rns', 'smsa'] + g_dums]
IVG = dict(table=t_gri, y='lw', effects=E_gri, endog=['s', 'iq'], instruments=['med', 'kww', 'age', 'mrt'])
ivg = call('fitmodel.iv', **IVG, ols=True)
eg = rows_of(ivg['estimates'])
names_st = [('Intercept' if nm == '_cons' else nm) for nm in rg.param_names]
pt_small = rg.results_small.params_table
check.near('2SLS (Griliches) = ivreg2, small: every estimate', max(abs(eg[nm]['estimate'] - pt_small[i, 0]) / max(1, abs(pt_small[i, 0])) for i, nm in enumerate(names_st)), 0.0, abs_=1e-9)
check.near('2SLS = ivreg2, small: every standard error', max(abs(eg[nm]['se'] - pt_small[i, 1]) / pt_small[i, 1] for i, nm in enumerate(names_st)), 0.0, abs_=1e-9)
check.near('2SLS = ivreg2, small: the t ratio of s', eg['s']['t'], pt_small[0, 2], rel=1e-9)
check.near('2SLS = ivreg2, small: the p-value of iq (t on 745 DF)', eg['iq']['p'], pt_small[1, 3], rel=1e-7)
check.near('2SLS = ivreg2, small: the lower limit of expr', [r_ for r_ in ivg['estimates']['rows'] if r_['term'] == 'expr'][0]['lower'], pt_small[2, 4], rel=1e-9)
sof_g = {r_['stat']: r_['value'] for r_ in ivg['summary']['rows']}
check.near('2SLS RSquare = ivreg2\'s r2', sof_g['RSquare'], rg.results_small.r2, rel=1e-9)
check.near('2SLS RSquare Adj = ivreg2\'s r2_a', sof_g['RSquare Adj'], rg.results_small.r2_a, rel=1e-9)
check.near('2SLS Root Mean Square Error = ivreg2, small', sof_g['Root Mean Square Error'], rg.results_small.rmse, rel=1e-9)
check.near('2SLS whole-model Wald F = ivreg2\'s F (12, 745)', ivg['whole']['f'], rg.results_small.F, rel=1e-9)
check('... on 12 and 745 DF', (ivg['whole']['df_num'], ivg['whole']['df_den']), (12.0, 745.0))
ov_g = ivg['tests']['overid']
check.near('Sargan = ivreg2\'s sargan', ov_g['stat'], rg.results_small.sargan, rel=1e-9)
check.near('Sargan p-value = ivreg2\'s', ov_g['p'], rg.results_small.sarganp, rel=1e-8)
check('Sargan: 2 overidentifying restrictions', (ov_g['test'], ov_g['df']), ('Sargan', 2))
check.near('Cragg-Donald Wald F = ivreg2\'s cdf', ivg['weak']['cragg_donald'], rg.results_small.cdf, rel=1e-9)
en_g = ivg['tests']['endog']
check.near('Wu-Hausman F = ivendog\'s WHF', en_g['f'], rg.results_small.hausman['WHF'], rel=1e-9)
check('Wu-Hausman F on 2 and 743 DF, as ivendog', (en_g['df_num'], en_g['df_den']), (2.0, float(rg.results_small.hausman['df_r'])))
check.near('Wu-Hausman p-value = ivendog\'s', en_g['p'], rg.results_small.hausman['WHFp'], rel=1e-6)
check.near('Durbin chi2 = ivendog\'s Durbin-Wu-Hausman', en_g['durbin'], rg.results_small.hausman['DWH'], rel=1e-9)
check.near('Durbin p-value = ivendog\'s', en_g['durbin_p'], rg.results_small.hausman['DWHp'], rel=1e-6)
Xg = np.column_stack([np.ones(len(gri)), gri[['s', 'iq', 'expr', 'tenure', 'rns', 'smsa'] + g_dums].to_numpy(float)])
Zg = np.column_stack([np.ones(len(gri)), gri[['expr', 'tenure', 'rns', 'smsa'] + g_dums + ['med', 'kww', 'age', 'mrt']].to_numpy(float)])
yg_ = gri['lw'].to_numpy(float)
ivd = IV2SLS(yg_, Xg, Zg).fit()
h_sm = ivd.spec_hausman()
Xg_last = np.column_stack([Xg[:, 1:], Xg[:, :1]])
Zg_last = np.column_stack([Zg[:, 1:], Zg[:, :1]])
h_last = IV2SLS(yg_, Xg_last, Zg_last).fit().spec_hausman()
check('statsmodels\' spec_hausman is the same statistic up to its pinv (constant first or last: both near ivendog)', abs(h_sm[0] - en_g['durbin']) / en_g['durbin'] < 1e-4 and abs(h_last[0] - en_g['durbin']) / en_g['durbin'] < 1e-9, True)
print(f'      spec_hausman with the constant first {h_sm[0]:.10g}, last {h_last[0]:.10g}; regression-based {en_g["durbin"]:.10g}')
fs_g = {f['label']: f for f in ivg['first']}
for c_, j_ in [('s', 1), ('iq', 2)]:
    fsd = sm.OLS(Xg[:, j_], Zg).fit()
    ftd = fsd.f_test(np.eye(Zg.shape[1])[-4:])
    check.near(f'first stage of {c_}: F of the excluded instruments = statsmodels\' f_test', fs_g[c_]['f'], float(np.squeeze(ftd.fvalue)), rel=1e-10)
    check.near(f'first stage of {c_}: its RSquare', fs_g[c_]['rsq'], float(fsd.rsquared), rel=1e-12)
    fr0 = sm.OLS(Xg[:, j_], Zg[:, :-4]).fit()
    check.near(f'first stage of {c_}: partial RSquare = 1 - SSR(all)/SSR(exogenous only)', fs_g[c_]['partial_rsq'], 1 - fsd.ssr / fr0.ssr, rel=1e-10)
    # Shea's partial RSquare by his definition: the regressor and its first-stage prediction, each purged of the other regressors
    others = [k for k in range(Xg.shape[1]) if k != j_]
    xh_ = Zg @ np.linalg.lstsq(Zg, Xg, rcond=None)[0]
    r_x = Xg[:, j_] - Xg[:, others] @ np.linalg.lstsq(Xg[:, others], Xg[:, j_], rcond=None)[0]
    r_h = xh_[:, j_] - xh_[:, others] @ np.linalg.lstsq(xh_[:, others], xh_[:, j_], rcond=None)[0]
    check.near(f'first stage of {c_}: Shea\'s partial RSquare (Godfrey\'s formula) = the squared correlation of the purged columns', fs_g[c_]['shea_rsq'], float(np.corrcoef(r_x, r_h)[0, 1] ** 2), rel=1e-9)
check('first stages: F above 10, not weak', [f['weak'] for f in ivg['first']], [False, False])
ols_g = rows_of(ivg['ols'])
ols_d = sm.OLS(yg_, Xg).fit()
check.near('OLS beside 2SLS: the OLS estimate of s', ols_g['s']['ols'], float(ols_d.params[1]), rel=1e-10)
check.near('... and its 2SLS - OLS difference', ols_g['s']['diff'], eg['s']['estimate'] - float(ols_d.params[1]), rel=1e-10)
ns, err = run_code(ivg['code'], gri[g_cols].astype(float), 'data')   # float64: the Stata file's float32 would be written short
check('2SLS code runs', err, None)
if not err:
    check.near('its fit has the report\'s estimates', maxdiff([eg[nm]['estimate'] for nm in ['Intercept', 's', 'iq']], ns['fit'].params.to_numpy()[:3]), 0.0, abs_=1e-10)
    check.near('its Durbin-Wu-Hausman and Sargan are the report\'s', abs(float(np.squeeze(ns['aug'].f_test(np.eye(ns['X'].shape[1] + 2)[ns['X'].shape[1]:]).fvalue)) - en_g['f'])
               + abs(float(len(ns['e']) * ns['e'] @ ns['Za'] @ np.linalg.lstsq(ns['Za'], ns['e'], rcond=None)[0] / (ns['e'] @ ns['e'])) - ov_g['stat']), 0.0, abs_=1e-8)
# robust: HC0 is ivreg2's robust (no small-sample factor), HC1 ivreg2's small robust; Hansen's J
ivh0 = call('fitmodel.iv', **IVG, robust='HC0')
e0 = rows_of(ivh0['estimates'])
pt_r = rg.results_robust.params_table
check.near('2SLS HC0 = ivreg2, robust: every standard error', max(abs(e0[nm]['se'] - pt_r[i, 1]) / pt_r[i, 1] for i, nm in enumerate(names_st)), 0.0, abs_=1e-9)
check.near('Hansen J = ivreg2\'s j (robust)', ivh0['tests']['overid']['stat'], rg.results_robust.j, rel=1e-9)
check.near('Hansen J p-value = ivreg2\'s jp', ivh0['tests']['overid']['p'], rg.results_robust.jp, rel=1e-8)
check('robust: the test is Hansen\'s J, and no Durbin chi2', (ivh0['tests']['overid']['test'], 'durbin' in ivh0['tests']['endog']), ('Hansen J', False))
ivh1 = call('fitmodel.iv', **IVG, robust='HC1')
e1 = rows_of(ivh1['estimates'])
pt_sr = rg.results_small_robust.params_table
check.near('2SLS HC1 = ivreg2, small robust: every standard error', max(abs(e1[nm]['se'] - pt_sr[i, 1]) / pt_sr[i, 1] for i, nm in enumerate(names_st)), 0.0, abs_=1e-9)
check.near('2SLS HC1 = ivreg2, small robust: the p-value of s', e1['s']['p'], pt_sr[0, 3], rel=1e-6)
check.near('2SLS HC1: the whole-model robust Wald F = ivreg2\'s (small robust)', ivh1['whole']['f'], rg.results_small_robust.F, rel=1e-9)
# the robust sandwich of 2SLS by its formula: (Xhat'Xhat)^-1 Xhat' diag(e^2) Xhat (Xhat'Xhat)^-1 n/(n - k)
xh_g = ivd.exog_hat
eg_res = yg_ - Xg @ ivd.params
Bg = np.linalg.inv(xh_g.T @ xh_g)
Vg1 = Bg @ (xh_g * eg_res[:, None] ** 2).T @ xh_g @ Bg * len(yg_) / (len(yg_) - Xg.shape[1])
check.near('HC1 of 2SLS = the sandwich with the second stage\'s regressors and the structural residuals', abs(e1['s']['se'] - math.sqrt(Vg1[1, 1])) / e1['s']['se'], 0.0, abs_=1e-10)
ns, err = run_code(ivh1['code'], gri[g_cols].astype(float), 'data')
check('robust 2SLS code runs', err, None)
if not err:
    check.near('its robust std errors are the report\'s', maxdiff([e1[nm]['se'] for nm in ['Intercept', 's', 'iq']], np.asarray(ns['rob'].bse)[:3]), 0.0, abs_=1e-10)
    check.near('its Hansen J is the report\'s', float(ns['u'] @ ns['W'] @ ns['u']), ivh1['tests']['overid']['stat'], rel=1e-9)

# ---- 2SLS with known truth: an unobserved ability behind both education and the wage -------------------------------------
ivr = np.random.default_rng(11)
n_iv = 3000
abil = ivr.normal(size=n_iv)
z1_ = ivr.normal(size=n_iv)
z2_ = np.where(ivr.uniform(size=n_iv) < 0.4, 'won', 'lost')
fem_ = np.where(ivr.uniform(size=n_iv) < 0.5, 'F', 'M')
exper_ = ivr.uniform(0, 30, n_iv)
weakz = ivr.normal(size=n_iv)
educ_ = 12 + 1.0 * abil + 0.8 * z1_ + 1.0 * (z2_ == 'won') + 0.3 * (fem_ == 'F') + 0.02 * weakz + ivr.normal(size=n_iv)
lw_ = 1 + 0.08 * educ_ + 0.02 * exper_ - 0.1 * (fem_ == 'F') + 0.004 * exper_ * (fem_ == 'F') + 0.25 * abil + ivr.normal(0, 0.3, n_iv)
bad_ = z1_ + ivr.normal(size=n_iv)                       # an "instrument" that moves the wage directly
lw_bad = lw_ + 0.15 * bad_
d_iv = pd.DataFrame({'educ': educ_, 'exper': exper_, 'sex': fem_, 'z1': z1_, 'lottery': z2_, 'weak': weakz, 'bad': bad_, 'lw': lw_, 'lwbad': lw_bad})
t_iv = table({c: d_iv[c].tolist() for c in d_iv.columns}, levels={'sex': ['F', 'M'], 'lottery': ['won', 'lost']})
E_iv = [['educ'], ['exper'], ['sex'], ['exper', 'sex']]
tr_iv = call('fitmodel.iv', table=t_iv, y='lw', effects=E_iv, endog=['educ'], instruments=['z1', 'lottery'], ols=True)
et_iv = rows_of(tr_iv['estimates'])
ot_iv = rows_of(tr_iv['ols'])
check('known truth: 2SLS recovers the return to education, 0.08, within 3 standard errors', abs(et_iv['educ']['estimate'] - 0.08) < 3 * et_iv['educ']['se'], True)
check('known truth: least squares is biased upward, more than 5 of its standard errors from 0.08', ot_iv['educ']['ols'] - 0.08 > 5 * ot_iv['educ']['ols_se'], True)
check('known truth: the Durbin-Wu-Hausman test rejects exogeneity', tr_iv['tests']['endog']['p'] < 1e-4, True)
check('known truth: Sargan does not reject valid instruments at 1%', tr_iv['tests']['overid']['p'] > 0.01, True)
tb_iv = call('fitmodel.iv', table=t_iv, y='lwbad', effects=E_iv, endog=['educ'], instruments=['z1', 'bad'])
check('known truth: Sargan rejects when an instrument moves Y directly', tb_iv['tests']['overid']['p'] < 1e-4, True)
tw_iv = call('fitmodel.iv', table=t_iv, y='lw', effects=E_iv, endog=['educ'], instruments=['weak'])
check('a weak instrument: first-stage F below 10, flagged', (tw_iv['first'][0]['f'] < 10, tw_iv['first'][0]['weak'], tw_iv['weak_columns']), (True, True, ['educ']))
check.near('one endogenous column: Cragg-Donald = the (classical) first-stage F', tw_iv['weak']['cragg_donald'], tw_iv['first'][0]['f'], rel=1e-9)
check('exactly identified: no overidentification test', tw_iv['tests']['overid'], None)
# JMP's design by hand: effect codes, the crossing centred, the intercept at exper = 0; the instruments with the lottery effect coded
fcode = np.where(fem_ == 'F', 1.0, -1.0)
mx_iv = exper_.mean()
XJ_iv = np.column_stack([np.ones(n_iv), educ_, exper_, fcode, (exper_ - mx_iv) * fcode])
ZJ_iv = np.column_stack([np.ones(n_iv), exper_, fcode, (exper_ - mx_iv) * fcode, z1_, np.where(z2_ == 'won', 1.0, -1.0)])
ivj = IV2SLS(lw_, XJ_iv, ZJ_iv).fit()
check.near('2SLS on JMP\'s design (x + g + x*g, a categorical instrument) = IV2SLS by hand: the intercept at exper = 0', et_iv['Intercept']['estimate'], float(ivj.params[0]), rel=1e-9)
check.near('... its standard error', et_iv['Intercept']['se'], float(ivj.bse[0]), rel=1e-9)
check.near('... the crossing', et_iv[f'(exper-{mx_iv:.6g})*sex[F]']['estimate'], float(ivj.params[4]), rel=1e-9)
check('the effect tests of the model\'s effects', [r_['source'] for r_ in tr_iv['effect_tests']['rows']], ['educ', 'exper', 'sex', 'exper*sex'])
check.near('the Wald F of educ is its t squared', rows_of(tr_iv['effect_tests'])['educ']['stat'], et_iv['educ']['t'] ** 2, rel=1e-9)
# an endogenous crossing: educ*sex instrumented by z1*sex and lottery*sex
tx_iv = call('fitmodel.iv', table=t_iv, y='lw', effects=[['educ'], ['exper'], ['sex'], ['educ', 'sex']], endog=['educ'], instruments=['z1', 'lottery'])
mz_ = z1_.mean()
me_ = educ_.mean()
lc_ = np.where(z2_ == 'won', 1.0, -1.0)
XX_ = np.column_stack([np.ones(n_iv), educ_, exper_, fcode, (educ_ - me_) * fcode])
ZX_ = np.column_stack([np.ones(n_iv), exper_, fcode, z1_, lc_, z1_ * fcode, lc_ * fcode])
ivx = IV2SLS(lw_, XX_, ZX_).fit()
ex_ = rows_of(tx_iv['estimates'])
check('an endogenous crossing: its instruments are the crossings of the instruments', [g_['instrument'] for g_ in tx_iv['model']['generated']], ['sex*z1', 'sex*lottery'])
check.near('... and 2SLS with them = IV2SLS by hand (the crossing\'s estimate)', ex_[f'(educ-{me_:.6g})*sex[F]']['estimate'], float(ivx.params[4]), rel=1e-8)
check.near('... educ\'s', ex_['educ']['estimate'], float(ivx.params[1]), rel=1e-8)
check('... two endogenous columns, four excluded instruments', (tx_iv['model']['k_endog'], tx_iv['model']['excluded']), (2, 4))
check('an endogenous crossing is said in the notes', any('Wooldridge' in n_ for n_ in tx_iv['notes']), True)
# cluster and HAC by their formulas
cl_iv = np.arange(n_iv) % 60
t_ivc = table({**{c: d_iv[c].tolist() for c in d_iv.columns}, 'cl': [f'c{k}' for k in cl_iv]}, levels={'sex': ['F', 'M'], 'lottery': ['won', 'lost']})
tc_iv = call('fitmodel.iv', table=t_ivc, y='lw', effects=[['educ'], ['exper']], endog=['educ'], instruments=['z1', 'lottery'], robust={'type': 'cluster', 'cluster': 'cl'})
X2_ = np.column_stack([np.ones(n_iv), educ_, exper_])
Z2_ = np.column_stack([np.ones(n_iv), exper_, z1_, lc_])
iv2 = IV2SLS(lw_, X2_, Z2_).fit()
xh2 = iv2.exog_hat
u2 = xh2 * (lw_ - X2_ @ iv2.params)[:, None]
G_ = pd.factorize(pd.Series([f'c{k}' for k in cl_iv]), sort=True)[0]
S_ = sum(np.outer(u2[G_ == g].sum(0), u2[G_ == g].sum(0)) for g in range(60))
B2 = np.linalg.inv(xh2.T @ xh2)
Vc = B2 @ S_ @ B2 * 60 / 59 * (n_iv - 1) / (n_iv - 3)
check.near('cluster-robust 2SLS = the clustered sandwich by hand, G/(G-1)(n-1)/(n-k)', rows_of(tc_iv['estimates'])['educ']['se'], math.sqrt(Vc[1, 1]), rel=1e-9)
check('... t tests on the clusters less one', tc_iv['dfi'], 59.0)
Sc = sum(np.outer((Z2_[G_ == g] * iv2.resid[G_ == g][:, None]).sum(0), (Z2_[G_ == g] * iv2.resid[G_ == g][:, None]).sum(0)) for g in range(60))
Wc = np.linalg.inv(Sc)
bgc = np.linalg.solve(X2_.T @ Z2_ @ Wc @ Z2_.T @ X2_, X2_.T @ Z2_ @ Wc @ Z2_.T @ lw_)
uc = Z2_.T @ (lw_ - X2_ @ bgc)
check.near('Hansen J with clusters: the two-step GMM criterion by hand', tc_iv['tests']['overid']['stat'], float(uc @ Wc @ uc), rel=1e-8)
th_iv = call('fitmodel.iv', table=t_iv, y='lw', effects=[['educ'], ['exper']], endog=['educ'], instruments=['z1', 'lottery'], robust={'type': 'HAC', 'maxlags': 3})
Sh = u2.T @ u2
for L_ in range(1, 4):
    Gm = u2[L_:].T @ u2[:-L_]
    Sh = Sh + (1 - L_ / 4) * (Gm + Gm.T)
Vh = B2 @ Sh @ B2
check.near('Newey-West 2SLS = the Bartlett sandwich by hand (3 lags, no small-sample factor)', rows_of(th_iv['estimates'])['educ']['se'], math.sqrt(Vh[1, 1]), rel=1e-9)
fs_c = sm.OLS(educ_, Z2_).fit().get_robustcov_results(cov_type='cluster', groups=G_, use_t=True)
check.near('cluster-robust first stage: the robust Wald F of the excluded instruments', tc_iv['first'][0]['f'], float(np.squeeze(fs_c.f_test(np.eye(4)[2:]).fvalue)), rel=1e-9)
pr_iv = call('fitmodel.profile', table=t_iv, kind='iv', y='lw', effects=E_iv, endog=['educ'], instruments=['z1', 'lottery'], current={'educ': 14, 'exper': 10, 'sex': 'M'})
xp_iv = np.array([1, 14, 10, -1, (10 - mx_iv) * -1])
tq_iv = stats.t.ppf(0.975, n_iv - 5)
check.near('the IV profiler: the prediction x\'b', pr_iv['responses'][0]['current']['pred'], float(xp_iv @ ivj.params), rel=1e-10)
check.near('... its lower limit, t on n - p DF', pr_iv['responses'][0]['current']['lower'], float(xp_iv @ ivj.params - tq_iv * math.sqrt(xp_iv @ ivj.cov_params() @ xp_iv)), rel=1e-9)
ns, err = run_code(tr_iv['code'], d_iv, 'data')
check('IV code with a crossing and a categorical instrument runs', err, None)
if not err:
    check.near('its estimates are the report\'s (the fitted parameterisation)', abs(float(ns['fit'].params['educ']) - et_iv['educ']['estimate']), 0.0, abs_=1e-10)
ns, err = run_code(tc_iv['code'], pd.DataFrame({**{c: d_iv[c] for c in d_iv.columns}, 'cl': [f'c{k}' for k in cl_iv]}), 'data')
check('cluster-robust IV code runs', err, None)
if not err:
    check.near('its robust std errors and Hansen J are the report\'s', abs(float(np.asarray(ns['rob'].bse)[1]) - rows_of(tc_iv['estimates'])['educ']['se'])
               + abs(float(ns['u'] @ ns['W'] @ ns['u']) - tc_iv['tests']['overid']['stat']), 0.0, abs_=1e-8)
check('IV refuses a model that is not identified', 'not identified' in (err_of('fitmodel.iv', table=t_iv, y='lw', effects=[['educ'], ['exper']], endog=['educ', 'exper'], instruments=['z1']) or ''), True)
check('IV refuses an Endogenous column outside the model', 'not in the model' in (err_of('fitmodel.iv', table=t_iv, y='lw', effects=[['exper']], endog=['educ'], instruments=['z1']) or ''), True)
check('IV refuses an instrument that is a model effect', 'excluded from the model' in (err_of('fitmodel.iv', table=t_iv, y='lw', effects=[['educ'], ['z1']], endog=['educ'], instruments=['z1']) or ''), True)
check('IV refuses weights', 'weights' in (err_of('fitmodel.iv', table=t_iv, y='lw', effects=[['educ']], endog=['educ'], instruments=['z1'], weight='exper') or ''), True)
check('IV refuses instruments collinear with the model', 'collinear' in (err_of('fitmodel.iv', table=t_iv, y='lw', effects=[['educ'], ['exper']], endog=['educ'], instruments=['z1', 'exper']) or '') or
      'model effect' in (err_of('fitmodel.iv', table=t_iv, y='lw', effects=[['educ'], ['exper']], endog=['educ'], instruments=['z1', 'exper']) or ''), True)
rsub_iv = call('fitmodel.iv', table=t_iv, y='lw', effects=[['educ'], ['exper']], endog=['educ'], instruments=['z1'], rows=list(range(0, n_iv, 2)))
check('IV on a row subset (a By group) uses those rows', (rsub_iv['n'], rsub_iv['diag']['rows'][:3]), (n_iv // 2, [0, 2, 4]))

# ---- Quantile Regression: Koenker's Engel data against Stata's qreg (the results statsmodels' test suite records) -------------
rq = load_results('regression', 'tests', 'results', 'results_quantile_regression.py')
engel = sm.datasets.engel.load_pandas().data
t_en = table({'income': engel['income'].tolist(), 'foodexp': engel['foodexp'].tolist()})
for tau_, ker_, bw_, ref_ in [(0.5, 'epa', 'hsheather', rq.epan2_hsheather), (0.75, 'epa', 'hsheather', rq.epanechnikov_hsheather_q75),
                              (0.5, 'gau', 'bofinger', rq.gaussian_bofinger), (0.5, 'cos', 'chamberlain', rq.cosine_chamberlain),
                              (0.5, 'par', 'hsheather', rq.parzen_hsheather), (0.5, 'biw', 'bofinger', rq.biweight_bofinger)]:
    qe = call('fitmodel.quantreg', table=t_en, y='foodexp', effects=[['income']], tau=tau_, qr_cov='iid', kernel=ker_, bandwidth=bw_, process=False)
    qr_ = rows_of(qe['estimates'])
    lab_ = f'{tau_}, {ker_}, {bw_}'
    check.near(f'QuantReg (Engel, {lab_}) = Stata\'s qreg: the slope (IRLS against the simplex)', qr_['income']['estimate'], ref_.table[0, 0], rel=2e-6)
    check.near(f'... the intercept ({lab_})', qr_['Intercept']['estimate'], ref_.table[1, 0], rel=2e-5)
    check.near(f'... the slope\'s iid std error ({lab_}; statsmodels\' own tolerance)', qr_['income']['se'], ref_.table[0, 1], rel=1e-3)
    if tau_ == 0.5 and ker_ == 'epa':
        check.near('... the sparsity 1/f(0)', qe['stats']['sparsity'], ref_.sparsity, rel=1e-3)
        check.near('... the kernel bandwidth', qe['stats']['bandwidth'], ref_.kbwidth, rel=1e-3)
    sof_q = {r_['stat']: r_['value'] for r_ in qe['summary']['rows']}
    check.near(f'... Koenker-Machado pseudo RSquare = Stata\'s 1 - sum_adev/sum_rdev ({lab_})', sof_q['Pseudo RSquare (Koenker–Machado)'], 1 - ref_.sum_adev / ref_.sum_rdev, rel=1e-6)
    check.near(f'... Stata\'s sum of weighted deviations is twice the check loss ({lab_})', 2 * sof_q['Sum of Check Losses'], ref_.sum_adev, rel=2e-6)
qe5 = call('fitmodel.quantreg', table=t_en, y='foodexp', effects=[['income']], tau=0.75, qr_cov='iid', process=False)
qsm = QuantReg(engel['foodexp'], sm.add_constant(engel['income'])).fit(q=0.75, vcov='iid', max_iter=5000)
check('statsmodels\' prsquared interpolates the unconditional quantile: it is not Stata\'s at 0.75', abs(float(qsm.prsquared) - (1 - rq.epanechnikov_hsheather_q75.sum_adev / rq.epanechnikov_hsheather_q75.sum_rdev)) > 1e-6, True)
check.near('... the report shows it in its notes', float(qe5['stats']['prsquared']), float(qsm.prsquared), rel=1e-10)
# the estimates are statsmodels' QuantReg at every quantile, robust and iid; the robust covariance is the iid one at the median
yq_ = engel['foodexp'].to_numpy(float)
Xq_ = sm.add_constant(engel['income'].to_numpy(float))
for tau_ in (0.1, 0.25, 0.5, 0.9):
    for cov_ in ('robust', 'iid'):
        qq = call('fitmodel.quantreg', table=t_en, y='foodexp', effects=[['income']], tau=tau_, qr_cov=cov_, process=False)
        dq = QuantReg(yq_, Xq_).fit(q=tau_, vcov=cov_, max_iter=5000)
        # the same IRLS; the design's memory order changes the rounding of its products, so they agree to the IRLS tolerance
        check.near(f'QuantReg at {tau_} ({cov_}) = statsmodels called directly: estimates and std errors', maxdiff([r_['estimate'] for r_ in qq['estimates']['rows']] + [r_['se'] for r_ in qq['estimates']['rows']], np.r_[dq.params, dq.bse]), 0.0, abs_=2e-6)
qr_i = rows_of(call('fitmodel.quantreg', table=t_en, y='foodexp', effects=[['income']], tau=0.5, qr_cov='iid', process=False)['estimates'])
qr_r = rows_of(call('fitmodel.quantreg', table=t_en, y='foodexp', effects=[['income']], tau=0.5, qr_cov='robust', process=False)['estimates'])
check.near('statsmodels\' robust covariance is its iid one at the median (one density for every row)', qr_r['income']['se'], qr_i['income']['se'], rel=1e-12)
# heteroscedastic errors: the true quantile slopes, Powell's sandwich against the spread of the estimates over samples
hq = np.random.default_rng(77)


def het_sample(n_, rng_):
    x_ = rng_.uniform(0, 10, n_)
    return x_, 1 + 0.5 * x_ + (0.2 + 0.3 * x_) * rng_.normal(size=n_)


xq1, yq1 = het_sample(4000, hq)
t_hq = table({'x': xq1.tolist(), 'y': yq1.tolist()})
for tau_ in (0.1, 0.5, 0.9):
    qh_ = rows_of(call('fitmodel.quantreg', table=t_hq, y='y', effects=[['x']], tau=tau_, qr_cov='powell', process=False)['estimates'])
    truth_ = 0.5 + 0.3 * stats.norm.ppf(tau_)
    check(f'known truth: the {tau_} quantile slope {truth_:.4f} within 3 Powell standard errors', abs(qh_['x']['estimate'] - truth_) < 3 * qh_['x']['se'], True)
reps, n_rep = 150, 500
slopes, se_pw, se_rb = [], [], []
Xr_rep = None
from statsmodels.regression.quantile_regression import kernels as qr_kernels
for _ in range(reps):
    xr_, yr_ = het_sample(n_rep, hq)
    Xr_rep = sm.add_constant(xr_)
    fr_ = QuantReg(yr_, Xr_rep).fit(q=0.9, max_iter=5000)
    slopes.append(float(fr_.params[1]))
    se_rb.append(float(fr_.bse[1]))
    e_ = yr_ - Xr_rep @ fr_.params
    f_ = qr_kernels['epa'](e_ / fr_.bandwidth) / fr_.bandwidth
    A_ = np.linalg.inv((Xr_rep * f_[:, None]).T @ Xr_rep)
    se_pw.append(float(np.sqrt((0.9 * 0.1 * A_ @ Xr_rep.T @ Xr_rep @ A_)[1, 1])))
sd_true = float(np.std(slopes, ddof=1))
print(f'      the 0.9 slope over {reps} samples: sd {sd_true:.4f}; mean Powell se {np.mean(se_pw):.4f}; mean statsmodels robust se {np.mean(se_rb):.4f}')
check('Powell\'s sandwich tracks the spread of the estimates over samples (within 20%)', abs(np.mean(se_pw) / sd_true - 1) < 0.2, True)
check('statsmodels\' robust standard error is too small with this heteroscedasticity (by more than 20%)', np.mean(se_rb) / sd_true < 0.8, True)
xs_, ys_ = het_sample(300, np.random.default_rng(5))
t_pw = table({'x': xs_.tolist(), 'y': ys_.tolist()})
pw_ = call('fitmodel.quantreg', table=t_pw, y='y', effects=[['x']], tau=0.9, qr_cov='powell', kernel='gau', bandwidth='bofinger', process=False)
fpw = QuantReg(ys_, sm.add_constant(xs_)).fit(q=0.9, kernel='gau', bandwidth='bofinger', max_iter=5000)
ep_ = ys_ - sm.add_constant(xs_) @ fpw.params
fk_ = np.exp(-0.5 * (ep_ / fpw.bandwidth) ** 2) / math.sqrt(2 * math.pi) / fpw.bandwidth
Xp_ = sm.add_constant(xs_)
Ap_ = np.linalg.inv((Xp_ * fk_[:, None]).T @ Xp_)
check.near('Powell\'s sandwich (Gaussian kernel, Bofinger) = its formula', rows_of(pw_['estimates'])['x']['se'], float(np.sqrt((0.09 * Ap_ @ Xp_.T @ Xp_ @ Ap_)[1, 1])), rel=1e-9)
# the quantile process, the least squares reference, the lines, the share below
d_qp = pd.DataFrame({'x': xq1, 'g': np.where(np.arange(4000) % 3 == 0, 'a', np.where(np.arange(4000) % 3 == 1, 'b', 'c')), 'y': yq1})
t_qp = table({c: d_qp[c].tolist() for c in d_qp.columns})
qp_ = call('fitmodel.quantreg', table=t_qp, y='y', effects=[['x'], ['g']], tau=0.5, taus=[0.1, 0.3, 0.5, 0.7, 0.9])
pr_ = qp_['process']
Xqp = patsy.dmatrix('x + C(g, Sum)', d_qp)
check('the quantile process at the quantiles asked for', pr_['taus'], [0.1, 0.3, 0.5, 0.7, 0.9])
check('... one curve per term, in the estimates\' order', pr_['terms'], ['Intercept', 'x', 'g[a]', 'g[b]'])
for j_, tau_ in enumerate(pr_['taus']):
    dq = QuantReg(yq1, np.asarray(Xqp)).fit(q=tau_, max_iter=5000)
    check.near(f'the process at {tau_} = QuantReg there (every coefficient)', maxdiff([pr_['estimate'][i][j_] for i in range(4)], dq.params[[0, 3, 1, 2]]), 0.0, abs_=2e-6)   # patsy puts g first
olq = sm.OLS(yq1, np.asarray(Xqp)).fit()
check.near('the process\'s least squares line and band = OLS and its interval', maxdiff(qp_['ols']['estimate'] + qp_['ols']['lower'], np.r_[olq.params[[0, 3, 1, 2]], olq.conf_int()[[0, 3, 1, 2], 0]]), 0.0, abs_=1e-9)
check('two factors: no quantile lines', 'lines' in qp_, False)
ql_ = call('fitmodel.quantreg', table=t_hq, y='y', effects=[['x'], ['x', 'x']], tau=0.6, process=False)
check('one continuous factor (with its square): the lines of 0.1, 0.25, 0.5, 0.6, 0.75, 0.9', [l_['tau'] for l_ in ql_['lines']['lines']], [0.1, 0.25, 0.5, 0.6, 0.75, 0.9])
mxq = float(xq1.mean())
Xl_ = np.column_stack([np.ones(4000), xq1, (xq1 - mxq) ** 2])
dl_ = QuantReg(yq1, Xl_).fit(q=0.75, max_iter=5000)
gx_ = np.asarray(ql_['lines']['x'])
check.near('... the 0.75 line is the fitted quantile over the grid', maxdiff(ql_['lines']['lines'][4]['y'], dl_.params[0] + dl_.params[1] * gx_ + dl_.params[2] * (gx_ - mxq) ** 2), 0.0, abs_=1e-9)
check('... the report\'s quantile is marked', [l_['current'] for l_ in ql_['lines']['lines']], [False, False, False, True, False, False])
check.near('the share of rows below the fitted 0.6 quantile is 0.6', ql_['stats']['below'], 0.6, abs_=4 / 4000)
qa_ = call('fitmodel.quantreg', table=t_qp, y='y', effects=[['x'], ['g']], tau=0.3, taus=[0.3, 0.6])
qb_ = call('fitmodel.quantreg', table=t_qp, y='y', effects=[['x'], ['g']], tau=0.6, taus=[0.3, 0.6])
check.near('a new quantile: its estimates are the process\'s at that quantile (the fits are shared)', maxdiff([r_['estimate'] for r_ in qb_['estimates']['rows']], [qa_['process']['estimate'][i][1] for i in range(4)]), 0.0, abs_=1e-12)
check('... and the report\'s key names the quantile', qa_['key'] != qb_['key'], True)
t_md = table({'y': [3.0, 1.0, 4.0, 1.5, 9.0, 2.6, 5.3], 'x': [1.0, 2, 3, 4, 5, 6, 7]})
qmd = call('fitmodel.quantreg', table=t_md, y='y', effects=[['x']], tau=0.5, no_intercept=False, process=False)
check.near('the pseudo RSquare\'s null loss is the check loss at the sample median', qmd['stats']['v0'], 0.5 * float(np.sum(np.abs(np.array([3.0, 1.0, 4.0, 1.5, 9.0, 2.6, 5.3]) - 3.0))), rel=1e-12)
pq_ = call('fitmodel.profile', table=t_qp, kind='qr', y='y', effects=[['x'], ['g']], tau=0.5, current={'x': 4.0, 'g': 'b'})
d05 = QuantReg(yq1, np.asarray(Xqp)).fit(q=0.5, max_iter=5000)
xq_p = np.array([1.0, 0.0, 1.0, 4.0])   # patsy's order: 1, g[a], g[b], x
check.near('the quantile profiler: the predicted median at x = 4, g = b', pq_['responses'][0]['current']['pred'], float(xq_p @ d05.params), rel=1e-9)
check.near('... its lower limit', pq_['responses'][0]['current']['lower'], float(xq_p @ d05.params - stats.t.ppf(0.975, 4000 - 4) * math.sqrt(xq_p @ d05.cov_params() @ xq_p)), rel=1e-8)
ns, err = run_code(qp_['code'], d_qp, 'data')
check('Quantile Regression code runs', err, None)
if not err:
    check.near('its fit and process are the report\'s', abs(float(ns['fit'].params['x']) - rows_of(qp_['estimates'])['x']['estimate']) + abs(float(ns['process']['x'].iloc[4]) - pr_['estimate'][1][4]), 0.0, abs_=1e-9)
qpw = call('fitmodel.quantreg', table=t_pw, y='y', effects=[['x']], tau=0.9, qr_cov='powell', process=False)
ns, err = run_code(qpw['code'], pd.DataFrame({'x': xs_, 'y': ys_}), 'data')
check('Powell code runs', err, None)
if not err:
    check.near('its standard errors are the report\'s', float(np.sqrt(np.diag(ns['V']))[1]), rows_of(qpw['estimates'])['x']['se'], rel=1e-9)
    check.near('and its pseudo RSquare', float(1 - ns['rho'](ns['fit'].resid.to_numpy()) / ns['v0']), qpw['stats']['r1'], rel=1e-9)
check('Quantile Regression refuses a quantile of 1', 'strictly between' in (err_of('fitmodel.quantreg', table=t_en, y='foodexp', effects=[['income']], tau=1.0) or ''), True)
check('Quantile Regression refuses weights', 'weights' in (err_of('fitmodel.quantreg', table=t_en, y='foodexp', effects=[['income']], weight='income') or ''), True)

# ---- Recursive and rolling regression: R's strucchange (the values statsmodels' test suite records), brute force, known truth ------
rls_R = pd.read_csv(os.path.join(SMDIR, 'regression', 'tests', 'results', 'results_rls_R.csv'))
mdat = sm.datasets.macrodata.load_pandas().data
t_rls = table({'cpi': mdat['cpi'].tolist(), 'm1': mdat['m1'].tolist(), 'realgdp': mdat['realgdp'].tolist(), 'quarter': mdat['quarter'].tolist()})
rr_ = call('fitmodel.recursive', table=t_rls, y='cpi', effects=[['m1']], rolling=True, window=40)
rec_ = {c_['term']: c_ for c_ in rr_['recursive']}
check('the recursion starts after the 2 parameters\' rows', rr_['start'], 2)
check.near('recursive residuals = R\'s strucchange (recresid)', maxdiff(rr_['resid'], rls_R['rec_resid']), 0.0, abs_=1e-7)
check.near('recursive estimates of m1 = R\'s (from the 10th row, as statsmodels\' tests)', maxdiff(rec_['m1']['estimate'][7:], rls_R['beta2'].to_numpy()[7:]), 0.0, abs_=1e-9)
check.near('... of the intercept', maxdiff(rec_['Intercept']['estimate'][7:], rls_R['beta1'].to_numpy()[7:]), 0.0, abs_=5e-7)
ols_m1 = sm.OLS(mdat['cpi'].to_numpy(), sm.add_constant(mdat['m1'].to_numpy())).fit()
from statsmodels.stats.diagnostic import recursive_olsresiduals
check.near('CUSUM = statsmodels\' recursive_olsresiduals (another implementation)', maxdiff(rr_['cusum']['y'], recursive_olsresiduals(ols_m1)[-2][1:]), 0.0, abs_=1e-6)
Xm = sm.add_constant(mdat['m1'].to_numpy())
ym = mdat['cpi'].to_numpy()
for t_ in (5, 60, 150, 202):
    b_prev = np.linalg.lstsq(Xm[:t_ - 1], ym[:t_ - 1], rcond=None)[0]
    w_ = (ym[t_ - 1] - Xm[t_ - 1] @ b_prev) / math.sqrt(1 + Xm[t_ - 1] @ np.linalg.inv(Xm[:t_ - 1].T @ Xm[:t_ - 1]) @ Xm[t_ - 1])
    check.near(f'the recursive residual of row {t_}: its prediction error from the rows before, standardised (by hand)', rr_['resid'][t_ - 3], float(w_), rel=1e-7)
    bt_ = np.linalg.lstsq(Xm[:t_], ym[:t_], rcond=None)[0]
    check.near(f'the recursive estimate at row {t_} = least squares on the first {t_} rows', rec_['m1']['estimate'][t_ - 3], float(bt_[1]), rel=1e-8)
check.near('the last recursive estimates are the report\'s least squares', rec_['m1']['estimate'][-1], float(ols_m1.params[1]), rel=1e-9)
check.near('... and their band the ±1.96 standard errors of least squares', rec_['m1']['upper'][-1], float(ols_m1.params[1] + stats.norm.ppf(0.975) * ols_m1.bse[1]), rel=1e-8)
w_all = np.asarray(rr_['resid'])
check.near('CUSUM = the cumulative sum of the recursive residuals over their standard deviation', maxdiff(rr_['cusum']['y'], np.cumsum(w_all) / np.std(w_all, ddof=1)), 0.0, abs_=1e-9)
t_o = np.arange(3, 204)
check.near('the 5% CUSUM bounds: 0.948 (sqrt(n - k) + 2 (t - k)/sqrt(n - k))', maxdiff(rr_['cusum']['upper'], 0.948 * (math.sqrt(201) + 2 * (t_o - 2) / math.sqrt(201))), 0.0, abs_=1e-9)
check.near('CUSUM of squares = the cumulative share of the squared recursive residuals', maxdiff(rr_['cusumsq']['y'], np.cumsum(w_all ** 2) / np.sum(w_all ** 2)), 0.0, abs_=1e-12)
rls_m = RecursiveLS(ym, Xm).fit()
lo_sq, up_sq = rls_m._cusum_squares_significance_bounds(0.05, points=t_o)
check.near('... its bounds are statsmodels\' (Edgerton and Wells)', maxdiff(rr_['cusumsq']['upper'], up_sq), 0.0, abs_=1e-12)
check('macrodata: prices and money do not keep one relation (CUSUM and CUSUM of squares cross)', (rr_['cusum']['crossed'], rr_['cusumsq']['crossed']), (True, True))


def bde(a_):
    return 1 - stats.norm.cdf(3 * a_) + math.exp(-4 * a_ * a_) * stats.norm.cdf(a_)


from scipy import optimize as sopt
check('Brown, Durbin and Evans\'s constants 1.143, 0.948, 0.850 solve alpha/2 = 1 - Phi(3a) + exp(-4a^2) Phi(a)',
      [round(sopt.brentq(lambda a_: bde(a_) - al_ / 2, 0.1, 3), 3) for al_ in (0.01, 0.05, 0.1)], [1.143, 0.948, 0.85])
rr10 = call('fitmodel.recursive', table=t_rls, y='cpi', effects=[['m1']], conf=0.1)
check.near('the 10% bounds take 0.850', rr10['cusum']['constant'], 0.850, rel=1e-12)
check('statsmodels\' _cusum_significance_bounds takes 0.950 at 10% (a slip)', round(float(rls_m._cusum_significance_bounds(0.1, points=np.array([203]))[1][0]) / (3 * math.sqrt(201)), 3), 0.95)
ro_ = rr_['rolling']
check('rolling windows of 40: the estimates from the 40th row on', (ro_['window'], ro_['x'][0], len(ro_['x'])), (40, 40, 164))
for end_ in (40, 100, 203):
    bw_ = sm.OLS(ym[end_ - 40:end_], Xm[end_ - 40:end_]).fit()
    rro = {c_['term']: c_ for c_ in ro_['terms']}
    check.near(f'the rolling estimate of the window ending at row {end_} = least squares on it', rro['m1']['estimate'][end_ - 40], float(bw_.params[1]), rel=1e-9)
    check.near(f'... its upper limit (t on 38 DF, window ending at row {end_})', rro['m1']['upper'][end_ - 40], float(bw_.conf_int()[1, 1]), rel=1e-9)
check.near('the rolling estimates = statsmodels\' RollingOLS called directly', maxdiff(ro_['terms'][1]['estimate'], np.asarray(RollingOLS(ym, Xm, window=40).fit().params)[39:, 1]), 0.0, abs_=1e-12)
rsr = call('fitmodel.recursive', table=t_rls, y='cpi', effects=[['m1']], rows=list(range(100)))
check('a row subset (a By group): the recursion over those rows', (rsr['n'], rsr['order']['rows'][-1]), (100, 99))
check.near('... its last estimate is least squares on them', {c_['term']: c_ for c_ in rsr['recursive']}['m1']['estimate'][-1], float(sm.OLS(ym[:100], Xm[:100]).fit().params[1]), rel=1e-9)
t_sm12 = table({'x': list(range(12)), 'y': [1.0, 2.5, 2.0, 4.1, 3.9, 6.2, 5.8, 8.1, 7.7, 9.9, 10.4, 12.2]})
check('the default rolling window: a tenth of the rows, at least 3 per parameter, at most every row', call('fitmodel.recursive', table=t_sm12, y='y', effects=[['x']], rolling=True)['rolling']['window'], 6)
ns, err = run_code(rr_['code'], mdat[['cpi', 'm1', 'realgdp', 'quarter']], 'data')
check('recursive and rolling code runs', err, None)
if not err:
    check.near('its recursive estimates, CUSUM and rolling estimates are the report\'s', abs(float(ns['rls'].recursive_coefficients.filtered[1, -1]) - rec_['m1']['estimate'][-1]) +
               abs(float(ns['rls'].cusum[-1]) - rr_['cusum']['y'][-1]) + abs(float(ns['roll'].params[-1, 1]) - ro_['terms'][1]['estimate'][-1]), 0.0, abs_=1e-9)
# known truth: a break in a slope along a time column; the rows of the table shuffled, the report sorts them
br = np.random.default_rng(8)
n_br = 600
tt_ = np.arange(n_br, dtype=float)
xb_ = br.normal(5, 2, n_br)
gb_ = np.where(br.uniform(size=n_br) < 0.5, 'p', 'q')
yb_ = 1 + np.where(tt_ < 350, 0.5, 0.9) * xb_ + 0.3 * (gb_ == 'p') + br.normal(0, 1, n_br)
ys0 = 1 + 0.5 * xb_ + 0.3 * (gb_ == 'p') + br.normal(0, 1, n_br)
perm = br.permutation(n_br)
d_br = pd.DataFrame({'time': tt_, 'x': xb_, 'g': gb_, 'y': yb_, 'y0': ys0}).iloc[perm].reset_index(drop=True)
t_br = table({c: d_br[c].tolist() for c in d_br.columns})
rb_ = call('fitmodel.recursive', table=t_br, y='y', effects=[['x'], ['g'], ['x', 'g']], order_by='time', rolling=True, window=60)
check('known truth: a break at time 350, found by the CUSUM after it', rb_['cusum']['crossed'] and 350 < rb_['cusum']['first'] < 600, True)
check('... the rows are the table\'s, sorted by time', rb_['order']['rows'][:3], [int(np.flatnonzero(d_br['time'] == v)[0]) for v in (0.0, 1.0, 2.0)])
check('... the order values come back for the hover text', rb_['order']['values'][:3], [0.0, 1.0, 2.0])
rb0 = call('fitmodel.recursive', table=t_br, y='y0', effects=[['x'], ['g'], ['x', 'g']], order_by='time')
check('known truth: without a break the CUSUM keeps inside its bounds', (rb0['cusum']['crossed'], rb0['cusum']['ratio'] < 1), (False, True))
srt = d_br.sort_values('time', kind='stable')
mxb = float(d_br['x'].mean())
gcb = np.where(srt['g'] == 'p', 1.0, -1.0)
Xb = np.column_stack([np.ones(n_br), srt['x'] - mxb, gcb, (srt['x'] - mxb) * gcb])   # the design as fitted (x centred like its crossing)
rlb = RecursiveLS(srt['y'].to_numpy(), Xb).fit()
recb = {c_['term']: c_ for c_ in rb_['recursive']}
check.near('the recursion sorted by time = RecursiveLS on the sorted rows (the slope of x)', maxdiff(recb['x']['estimate'], rlb.recursive_coefficients.filtered[1, rb_['start']:]), 0.0, abs_=1e-9)
check.near('... the intercept put back at x = 0 at every step', maxdiff(recb['Intercept']['estimate'], rlb.recursive_coefficients.filtered[0, rb_['start']:] - mxb * rlb.recursive_coefficients.filtered[1, rb_['start']:]), 0.0, abs_=1e-8)
rob_ = {c_['term']: c_ for c_ in rb_['rolling']['terms']}
wlast = sm.OLS(srt['y'].to_numpy()[-60:], Xb[-60:]).fit()
check.near('the last rolling window = least squares on the last 60 rows in time', rob_['x']['estimate'][-1], float(wlast.params[1]), rel=1e-9)
check.near('... its intercept at x = 0', rob_['Intercept']['estimate'][-1], float(wlast.params[0] - mxb * wlast.params[1]), rel=1e-9)
rbc = call('fitmodel.recursive', table=t_br, y='y', effects=[['x'], ['g']], order_by='g', rolling=True, window=30)
check('sorted by a nominal column: the rows of p first (its level order)', all(d_br['g'][r_] == 'p' for r_ in rbc['order']['rows'][:10]), True)
check('... the recursion starts when both levels have come', rbc['start'] > int((d_br['g'] == 'p').sum()) - 1, True)
check('... windows of one level have a singular design: no estimates, and the notes say so', rbc['rolling']['singular'] > 0 and any('singular' in n_ for n_ in rbc['notes']), True)
t_brm = table({**{c: d_br[c].tolist() for c in d_br.columns}, 'tm': [None if i % 10 == 0 else v for i, v in enumerate(d_br['time'])]})
rbm = call('fitmodel.recursive', table=t_brm, y='y', effects=[['x']], order_by='tm')
check('rows without a value of the order column are left out, and the notes say so', (rbm['n'], rbm['order']['dropped'], any('left out' in n_ for n_ in rbm['notes'])), (540, 60, True))
wts_b = br.uniform(0.5, 2, n_br)
t_brw = table({**{c: d_br[c].tolist() for c in d_br.columns}, 'w': wts_b.tolist()})
rbw = call('fitmodel.recursive', table=t_brw, y='y', effects=[['x']], weight='w', order_by='time', rolling=True, window=50)
ow_ = np.argsort(d_br['time'].to_numpy(), kind='stable')
Xw_ = sm.add_constant(d_br['x'].to_numpy())[ow_]
rlw = RecursiveLS(d_br['y'].to_numpy()[ow_] * np.sqrt(wts_b[ow_]), Xw_ * np.sqrt(wts_b[ow_])[:, None]).fit()
check.near('with a Weight: the recursion of the data times sqrt(w)', maxdiff({c_['term']: c_ for c_ in rbw['recursive']}['x']['estimate'], rlw.recursive_coefficients.filtered[1, rbw['start']:]), 0.0, abs_=1e-9)
rww = RollingWLS(d_br['y'].to_numpy()[ow_], Xw_, window=50, weights=wts_b[ow_]).fit()
check.near('... and the rolling estimates = RollingWLS', maxdiff({c_['term']: c_ for c_ in rbw['rolling']['terms']}['x']['estimate'], np.asarray(rww.params)[49:, 1]), 0.0, abs_=1e-9)
ns, err = run_code(rb_['code'], d_br, 'data')
check('recursive code sorted by a column runs', err, None)
if not err:
    jx_ = [i for i, nm in enumerate(ns['fit'].model.exog_names) if nm.startswith('I(x') and ':' not in nm][0]   # patsy puts g first
    check.near('its recursive estimates are the report\'s', abs(float(ns['rls'].recursive_coefficients.filtered[jx_, -1]) - recb['x']['estimate'][-1]) + abs(float(ns['rls'].cusum[-1]) - rb_['cusum']['y'][-1]), 0.0, abs_=1e-9)
check('recursive fits refuse Freq', 'Freq' in (err_of('fitmodel.recursive', table=t_brw, y='y', effects=[['x']], freq='w') or ''), True)


# ======================================================================================================================
# Generalized Regression: JMP Pro's validation methods, the adaptive methods, forward selection
# ======================================================================================================================
import warnings

from scipy.special import gammaln
from sklearn import metrics as skm
from sklearn.linear_model import ElasticNet, Lasso, LassoCV, LogisticRegression, PoissonRegressor, lasso_path

from smui import predictive

gr_rng = np.random.default_rng(20260927)
ng = 240
Xg = gr_rng.normal(size=(ng, 6))
Xg[:, 2] = 0.6 * Xg[:, 0] + 0.8 * Xg[:, 2]                  # two correlated columns
bg = np.array([1.5, -1.0, 0.0, 0.0, 0.6, 0.0])
yg_n = 1 + Xg @ bg + gr_rng.normal(size=ng)
yg_b = np.where(gr_rng.uniform(size=ng) < 1 / (1 + np.exp(-(0.3 + Xg @ bg))), 'yes', 'no')
yb01 = (yg_b == 'yes').astype(float)
yg_c = gr_rng.poisson(np.exp(0.3 + 0.4 * Xg[:, 0] - 0.3 * Xg[:, 1])).astype(float)
wg = gr_rng.uniform(0.5, 2.0, ng).round(2)
vg = gr_rng.choice([0.0, 1.0, 2.0], ng, p=[0.6, 0.25, 0.15])
vg_m = vg.copy()
vg_m[[3, 50]] = np.nan                                     # rows with no validation value
gdf = pd.DataFrame({**{f'x{i}': Xg[:, i] for i in range(6)}, 'y': yg_n, 'yb': yg_b, 'yc': yg_c, 'w': wg, 'v': vg_m,
                    'vt': np.array(['Training', 'Validation', 'Test'])[vg.astype(int)]})
tg = table({c: [None if isinstance(v_, float) and np.isnan(v_) else v_ for v_ in gdf[c].tolist()] for c in gdf.columns},
           types={'yb': 'nominal', 'vt': 'nominal'}, levels={'yb': ['yes', 'no']})
Eg6 = [[f'x{i}'] for i in range(6)]
X6 = [f'x{i}' for i in range(6)]


def gr(**kw):
    return call('fitmodel.genreg', table=tg, effects=kw.pop('effects', Eg6), **kw)


def gr_scaled(rows_mask, weights=None):
    """The predictors centred and scaled by some rows, as the report does."""
    ww = np.ones(ng) if weights is None else weights
    m_ = np.average(Xg[rows_mask], axis=0, weights=ww[rows_mask])
    return (Xg - m_) / np.sqrt(np.average((Xg[rows_mask] - m_) ** 2, axis=0, weights=ww[rows_mask]))


def path_coefs(r_):
    """The report's path of the scaled estimates: terms x steps."""
    return np.array([c_['values'] for c_ in r_['path']['coefs']])


def summary_of(r_):
    return {x_['measure']: x_ for x_ in r_['summary']['rows']}


def scaled_est(r_):
    return [e_['estimate'] for e_ in r_['scaled']]


allr = np.ones(ng, dtype=bool)
Z1 = gr_scaled(allr)
Z1w = gr_scaled(allr, wg)
A1 = np.column_stack([np.ones(ng), Z1])

# ---- the sets: predictive.prepare's (the page's rules), the folds from the seed ----------------------------------------
rh = gr(y='y', criterion='holdback', portion=0.25, seed=77)
Ph = predictive.prepare(tg, 'y', X6, portion=0.25, seed=77, missing='drop')
check('Holdback: the sets are predictive.prepare\'s (the page\'s Validation Portion)', rh['diag']['set'], Ph.sets.tolist())
want_h = np.zeros(ng, dtype=int)
want_h[np.random.default_rng(77).permutation(ng)[:int(round(0.25 * ng))]] = 1
check('... drawn as numpy permutes the rows with the seed', rh['diag']['set'], want_h.tolist())
check('... the same seed draws the same rows', gr(y='y', criterion='holdback', portion=0.25, seed=77, method='enet')['diag']['set'], rh['diag']['set'])
check('... another seed other rows', gr(y='y', criterion='holdback', portion=0.25, seed=78)['diag']['set'] != rh['diag']['set'], True)
check('the report says Holdback Validation', rh['model']['title'], 'Lasso with Holdback Validation')
rv = gr(y='y', criterion='validation', validation='v')
okv = ~np.isnan(vg_m)
check('Validation Column (0/1/2): rows with no value are left out', (len(rv['diag']['rows']), rv['diag']['rows'][:5]), (int(okv.sum()), np.flatnonzero(okv)[:5].tolist()))
check('... the sets are the column\'s', rv['diag']['set'], vg_m[okv].astype(int).tolist())
check('... and the notes say what was left out', any('no v value' in n_ for n_ in rv['notes']), True)
check('... the report\'s title, as JMP names it', rv['model']['title'], 'Lasso with Validation Column')
rvt = gr(y='y', criterion='validation', validation='vt')
check('a Validation column of names: Training, Validation, Test', rvt['diag']['set'], vg.astype(int).tolist())
check('the Model Summary has a column per set', [c_['label'] for c_ in rvt['summary']['columns']], ['Measure', 'Training', 'Validation', 'Test'])
check('AICc with a Validation column: the training rows fit, the others are reported', ([c_['label'] for c_ in gr(y='y', validation='vt')['summary']['columns']], summary_of(gr(y='y', validation='vt'))['Number of rows']['Training']),
      (['Measure', 'Training', 'Validation', 'Test'], int((vg == 0).sum())))
rk = gr(y='y', criterion='kfold', folds=5, seed=123)
fold = np.empty(ng, dtype=int)
fold[np.random.default_rng(123).permutation(ng)] = np.arange(ng) % 5
fk = rk['model']['fold'] - 1
check('KFold: the final model\'s Validation set is one fold, drawn from the seed', rk['diag']['set'], (fold == fk).astype(int).tolist())
check('KFold with a Validation column is refused', 'Validation column' in (err_of('fitmodel.genreg', table=tg, y='y', effects=Eg6, criterion='kfold', seed=1, validation='v') or ''), True)
check('Validation Column needs a column in the role', 'Validation role' in (err_of('fitmodel.genreg', table=tg, y='y', effects=Eg6, criterion='validation') or ''), True)
check('a Validation column holds 0, 1 and 2 (predictive.prepare\'s message)', 'holds 0 (training)' in (err_of('fitmodel.genreg', table=tg, y='y', effects=Eg6, criterion='validation', validation='w') or ''), True)
check('the Validation column cannot be a model effect', 'cannot also' in (err_of('fitmodel.genreg', table=tg, y='y', effects=Eg6, criterion='validation', validation='x0') or ''), True)
check('KFold needs a seed', 'seed' in (err_of('fitmodel.genreg', table=tg, y='y', effects=Eg6, criterion='kfold') or ''), True)
check('KFold needs 2 to n folds', 'folds' in (err_of('fitmodel.genreg', table=tg, y='y', effects=Eg6, criterion='kfold', seed=1, folds=1) or ''), True)
t_big = table({'x': gr_rng.normal(size=320).tolist(), 'y': gr_rng.normal(size=320).tolist()})
check('Leave-One-Out is refused beyond its rows (Forward Selection: 300)', 'KFold' in (err_of('fitmodel.genreg', table=t_big, y='y', effects=[['x']], method='forward', criterion='loo') or ''), True)

# ---- the fits against scikit-learn and statsmodels called directly -------------------------------------------------------
r1 = gr(y='y', method='lasso')
_, co1, _ = lasso_path(Z1, yg_n - yg_n.mean(), alphas=np.array(r1['path']['alpha']), tol=1e-12, max_iter=100000)
check.near('lasso path = scikit-learn lasso_path on the centred and scaled predictors', float(np.max(np.abs(path_coefs(r1) - co1))), 0.0, abs_=1e-8)
check.near('... from λ_max = max |z\'(y - ȳ)| / N, where every term is out', r1['path']['alpha'][0], float(np.max(np.abs(Z1.T @ (yg_n - yg_n.mean())))) / ng, rel=1e-12)
check('... which it is', r1['path']['nonzero'][0], 0)
r2 = gr(y='y', method='enet', enet_alpha=0.5, weight='w')
l2_ = np.array(r2['path']['alpha'])
d2 = max(float(np.max(np.abs(ElasticNet(alpha=l2_[l], l1_ratio=0.5, tol=1e-12, max_iter=100000).fit(Z1w, yg_n, sample_weight=wg).coef_ - path_coefs(r2)[:, l]))) for l in (0, 13, 26, 39))
check.near('elastic net with a Weight = scikit-learn ElasticNet(sample_weight)', d2, 0.0, abs_=1e-8)
r3 = gr(y='yb', method='lasso')
check('a two-level Y is binomial, the first level the target', (r3['model']['distribution'], r3['model']['target']), ('Binomial', 'yes'))
l3 = np.array(r3['path']['alpha'])
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    d3 = max(float(np.max(np.abs(LogisticRegression(l1_ratio=1.0, C=1 / (l3[l] * ng), solver='saga', tol=1e-14, max_iter=10 ** 6, random_state=0).fit(Z1, yb01).coef_[0] - path_coefs(r3)[:, l]))) for l in (8, 20, 32))
check.near('binomial lasso = scikit-learn LogisticRegression(l1_ratio=1, saga) at C = 1/(λN)', d3, 0.0, abs_=1e-6)
r4 = gr(y='yb', method='ridge', weight='w')
l4 = np.array(r4['path']['alpha'])
d4 = max(float(np.max(np.abs(LogisticRegression(l1_ratio=0.0, C=1 / (l4[l] * wg.sum()), solver='newton-cholesky', tol=1e-12, max_iter=10000).fit(Z1w, yb01, sample_weight=wg).coef_[0] - path_coefs(r4)[:, l]))) for l in (0, 20, 39))
check.near('binomial ridge with a Weight = LogisticRegression(l1_ratio=0): the penalty per unit of weight', d4, 0.0, abs_=1e-8)
r5 = gr(y='yc', dist='poisson', method='ridge', weight='w')
l5 = np.array(r5['path']['alpha'])
d5 = max(float(np.max(np.abs(PoissonRegressor(alpha=l5[l], solver='newton-cholesky', tol=1e-12, max_iter=10000).fit(Z1w, yg_c, sample_weight=wg).coef_ - path_coefs(r5)[:, l]))) for l in (0, 20, 39))
check.near('Poisson ridge with a Weight = scikit-learn PoissonRegressor(alpha=λ)', d5, 0.0, abs_=1e-8)
r6 = gr(y='yc', dist='poisson', method='lasso')
lam6 = r6['path']['alpha'][r6['chosen']]
f6 = sm.GLM(yg_c, A1, family=sm.families.Poisson()).fit_regularized(method='elastic_net', alpha=np.r_[0, np.full(6, lam6)], L1_wt=1.0, cnvrg_tol=1e-12, maxiter=1000)
check.near('Poisson lasso = statsmodels GLM fit_regularized (scikit-learn has no lasso for a Poisson Y)', maxdiff(scaled_est(r6), f6.params), 0.0, abs_=1e-6)
r7 = gr(y='y', method='lasso', adaptive=True)
b_ols = sm.OLS(yg_n, A1).fit().params[1:]
l7 = np.array(r7['path']['alpha'])
check('Adaptive Lasso, its initial fit least squares (the notes say so)', (r7['model']['method'], any('maximum likelihood estimate' in n_ for n_ in r7['notes'])), ('Adaptive Lasso', True))
d7 = max(float(np.max(np.abs(Lasso(alpha=l7[l], tol=1e-12, max_iter=100000).fit(Z1 * np.abs(b_ols), yg_n).coef_ * np.abs(b_ols) - path_coefs(r7)[:, l]))) for l in (5, 20, 35))
check.near('... = scikit-learn Lasso on the columns times |b|, the estimates times |b| again (the adaptive lasso\'s identity)', d7, 0.0, abs_=1e-8)
check.near('... its path starts at max |z_j\'(y - ȳ)| |b_j| / N', l7[0], float(np.max(np.abs(Z1.T @ (yg_n - yg_n.mean())) * np.abs(b_ols))) / ng, rel=1e-10)
r8 = gr(y='y', method='enet', enet_alpha=0.7, adaptive=True)
f8 = sm.OLS(yg_n, A1).fit_regularized(method='elastic_net', alpha=np.r_[0, r8['path']['alpha'][r8['chosen']] / np.abs(b_ols)], L1_wt=0.7, maxiter=2000)
check.near('Adaptive Elastic Net = statsmodels fit_regularized with each term\'s penalty (both parts) divided by |b|', maxdiff(scaled_est(r8), f8.params), 0.0, abs_=1e-6)
r8b = gr(y='yb', method='lasso', adaptive=True)
b_glm = sm.GLM(yb01, A1, family=sm.families.Binomial()).fit().params[1:]
check.near('Adaptive Lasso (binomial): the initial fit is the logistic MLE', r8b['path']['alpha'][0], float(np.max(np.abs(Z1.T @ (yb01 - yb01.mean())) * np.abs(b_glm))) / ng, rel=1e-6)
Xs_ = gr_rng.normal(size=(8, 10))
ys_ = Xs_[:, 0] + gr_rng.normal(size=8)
ts_ = table({**{f's{i}': Xs_[:, i].tolist() for i in range(10)}, 'y': ys_.tolist()})
ra_ = call('fitmodel.genreg', table=ts_, y='y', effects=[[f's{i}'] for i in range(10)], method='lasso', adaptive=True)
Zs_ = (Xs_ - Xs_.mean(0)) / Xs_.std(0)
b_rdg = np.linalg.solve(Zs_.T @ Zs_ / 8 + 0.01 * np.eye(10), Zs_.T @ (ys_ - ys_.mean()) / 8)
check('Adaptive with more terms than rows: the initial fit is ridge (λ = 0.01), and the notes say so', any('ridge estimate' in n_ for n_ in ra_['notes']), True)
check.near('... its weights 1/|b| of that ridge fit start the path', ra_['path']['alpha'][0], float(np.max(np.abs(Zs_.T @ (ys_ - ys_.mean())) * np.abs(b_rdg))) / 8, rel=1e-9)

# ---- the validation curves: the formulas on fits made by scikit-learn ------------------------------------------------------
lk = np.array(rk['path']['alpha'])
cvk = [(np.flatnonzero(fold != k), np.flatnonzero(fold == k)) for k in range(5)]
scores = np.zeros((5, len(lk)))
mse = np.zeros((len(lk), 5))
for k, (a_, v_) in enumerate(cvk):
    for l, lam in enumerate(lk):
        la = Lasso(alpha=lam, tol=1e-12, max_iter=100000).fit(Z1[a_], yg_n[a_])
        e_ = yg_n - la.predict(Z1)
        s2_ = np.mean(e_[a_] ** 2)
        scores[k, l] = 0.5 * np.mean(np.log(2 * np.pi * s2_) + e_[v_] ** 2 / s2_)
        mse[l, k] = np.mean(e_[v_] ** 2)
check.near('KFold curve = the mean of the folds\' Scaled -LogLikelihood (scikit-learn Lasso on each fold, the variance its SSE/N)', maxdiff(rk['path']['curve'], scores.mean(0)), 0.0, abs_=1e-9)
check('... the model is at the curve\'s smallest value', rk['best'], int(np.argmin(scores.mean(0))))
check('... and, as JMP, it is the fold model that validates best there', fk, int(np.argmin(scores[:, rk['best']])))
lcv = LassoCV(alphas=lk, cv=cvk, tol=1e-12, max_iter=100000).fit(Z1, yg_n)
check.near('the same folds give scikit-learn LassoCV\'s mse_path_', float(np.max(np.abs(lcv.mse_path_ - mse))), 0.0, abs_=1e-9)
la_k = Lasso(alpha=lk[rk['chosen']], tol=1e-12, max_iter=100000).fit(Z1[fold != fk], yg_n[fold != fk])
check.near('the final model = the fold\'s Lasso fit', maxdiff(scaled_est(rk), np.r_[la_k.intercept_, la_k.coef_]), 0.0, abs_=1e-8)
sk_ = summary_of(rk)
check('its Training and Validation rows are the other folds and the fold', (sk_['Number of rows']['Training'], sk_['Number of rows']['Validation']), (int((fold != fk).sum()), int((fold == fk).sum())))
check.near('its Validation Scaled -LogLikelihood is the fold\'s score', sk_['Scaled -LogLikelihood']['Validation'], float(scores[fk, rk['chosen']]), abs_=1e-9)
rhb = gr(y='yb', method='enet', enet_alpha=0.5, criterion='holdback', portion=0.3, seed=9)
sh_ = np.array(rhb['diag']['set'])
trh, vah = sh_ == 0, sh_ == 1
Zh = gr_scaled(trh)
lh = np.array(rhb['path']['alpha'])
# the first point keeps every term out: the training rows' share. scikit-learn 1.8, pinned: saga stops early there, its
# intercept short of logit(share)
share_h = float(yb01[trh].mean())
lr0 = LogisticRegression(l1_ratio=0.5, C=1 / (lh[0] * trh.sum()), solver='saga', tol=1e-14, max_iter=10 ** 6, random_state=0).fit(Zh[trh], yb01[trh])
logit_h = math.log(share_h / (1 - share_h))
p_h = fit_model._genreg_path(tg, None, fit_model._spec(y='yb', effects=Eg6, method='enet', enet_alpha=0.5, criterion='holdback', portion=0.3, seed=9))
check('scikit-learn pinned: saga where every term is out stops with the intercept short of logit(share) (the report\'s is it)',
      (bool(np.all(lr0.coef_ == 0)), abs(float(lr0.intercept_[0]) - logit_h) > 1e-4, abs(float(p_h['coefs'][0, 0]) - logit_h) < 1e-10), (True, True, True))
cur_h = [skm.log_loss(yb01[vah], np.full(int(vah.sum()), share_h), labels=[0, 1])]
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    for lam in lh[1:]:
        lr_ = LogisticRegression(l1_ratio=0.5, C=1 / (lam * trh.sum()), solver='saga', tol=1e-14, max_iter=10 ** 6, random_state=0).fit(Zh[trh], yb01[trh])
        cur_h.append(skm.log_loss(yb01[vah], lr_.predict_proba(Zh[vah])[:, 1], labels=[0, 1]))
check.near('Holdback curve = scikit-learn log_loss of the held-back rows, LogisticRegression(elastic net) on the others', maxdiff(rhb['path']['curve'], cur_h), 0.0, abs_=1e-8)
check('... the chosen model is at its smallest value', rhb['chosen'], int(np.argmin(cur_h)))
# statsmodels 0.14.6, pinned: fit_elasticnet keeps a coefficient that is zero after its second sweep at zero for good (its
# "active set"), so fit_regularized from its default start (zeros) can stop short of the optimum. The code under the report
# starts each fit at the one before it on the path, which reaches the report's fit.
lam_h = lh[rhb['chosen']]
Ah = np.column_stack([np.ones(ng), Zh])
glm_h = lambda start: sm.GLM(yb01[trh], Ah[trh], family=sm.families.Binomial()).fit_regularized(  # noqa: E731
    method='elastic_net', alpha=np.r_[0, np.full(6, lam)], L1_wt=0.5, start_params=start, maxiter=1000, cnvrg_tol=1e-12)
obj_h = lambda b_: float(-np.mean(yb01[trh] * (Ah[trh] @ b_) - np.logaddexp(0, Ah[trh] @ b_)) + lam_h * (0.5 * np.sum(np.abs(b_[1:])) + 0.25 * np.sum(b_[1:] ** 2)))  # noqa: E731
lam = lam_h
cold = glm_h(None)
check('statsmodels bug pinned: a binomial elastic net started at zero leaves a term at 0, at a larger objective', (float(cold.params[-1]), obj_h(cold.params) > obj_h(np.array(scaled_est(rhb))) + 1e-6), (0.0, True))
warm = None
for lam in lh[:rhb['chosen'] + 1]:
    warm = glm_h(None if warm is None else warm.params)
check.near('... started at the fit before it on the path, it reaches the report\'s fit', maxdiff(scaled_est(rhb), warm.params), 0.0, abs_=1e-8)
rvc = gr(y='yc', dist='poisson', method='lasso', criterion='validation', validation='vt')
sv_ = np.array(rvc['diag']['set'])
trv, vav, tev = sv_ == 0, sv_ == 1, sv_ == 2
Zv = gr_scaled(trv)
fv = sm.GLM(yg_c[trv], np.column_stack([np.ones(int(trv.sum())), Zv[trv]]), family=sm.families.Poisson()).fit_regularized(
    method='elastic_net', alpha=np.r_[0, np.full(6, rvc['path']['alpha'][rvc['chosen']])], L1_wt=1.0, cnvrg_tol=1e-12, maxiter=1000)
mu_v = np.exp(np.column_stack([np.ones(ng), Zv]) @ fv.params)
sv2 = summary_of(rvc)
nll_pois = lambda m_: -float(np.sum(yg_c[m_] * np.log(mu_v[m_]) - mu_v[m_] - gammaln(yg_c[m_] + 1)))  # noqa: E731
check.near('Validation Column (Poisson lasso): the model = statsmodels fit_regularized on the training rows', maxdiff(scaled_est(rvc), fv.params), 0.0, abs_=1e-6)
check.near('... the Validation -LogLikelihood is Poisson\'s (its constant too)', sv2['-LogLikelihood']['Validation'], nll_pois(vav), rel=1e-6)
check.near('... and the Test rows\', which take no part', sv2['-LogLikelihood']['Test'], nll_pois(tev), rel=1e-6)
check.near('... the curve at the model is the Validation Scaled -LogLikelihood', rvc['path']['curve'][rvc['chosen']], sv2['Scaled -LogLikelihood']['Validation'], abs_=1e-12)
rl_ = gr(y='y', method='lasso', criterion='loo', rows=list(range(40)))
Z40 = (Xg[:40] - Xg[:40].mean(0)) / Xg[:40].std(0)
y40 = yg_n[:40]
ll_ = np.array(rl_['path']['alpha'])
sc40 = np.zeros((40, len(ll_)))
for i in range(40):
    a_ = np.arange(40) != i
    for l, lam in enumerate(ll_):
        e_ = y40 - Lasso(alpha=lam, tol=1e-12, max_iter=100000).fit(Z40[a_], y40[a_]).predict(Z40)
        s2_ = np.mean(e_[a_] ** 2)
        sc40[i, l] = 0.5 * (np.log(2 * np.pi * s2_) + e_[i] ** 2 / s2_)
check.near('Leave-One-Out curve = the mean of each row\'s Scaled -LogLikelihood, scikit-learn Lasso without it', maxdiff(rl_['path']['curve'], sc40.mean(0)), 0.0, abs_=1e-8)
check('... the model shown leaves out the row it predicts best at the best penalty (as KFold, JMP\'s rule)', rl_['model']['fold'] - 1, int(np.argmin(sc40[:, rl_['best']])))
rlb = gr(y='yb', method='ridge', criterion='loo', rows=list(range(40)))
lb_ = np.array(rlb['path']['alpha'])
yb40 = yb01[:40]
sb40 = np.zeros((40, len(lb_)))
for i in range(40):
    a_ = np.arange(40) != i
    for l, lam in enumerate(lb_):
        pr_ = LogisticRegression(l1_ratio=0.0, C=1 / (lam * 39), solver='newton-cholesky', tol=1e-12, max_iter=1000).fit(Z40[a_], yb40[a_]).predict_proba(Z40[i:i + 1])[0, 1]
        sb40[i, l] = -(yb40[i] * np.log(pr_) + (1 - yb40[i]) * np.log(1 - pr_))
check.near('Leave-One-Out (binomial ridge) = the rows\' log loss under LogisticRegression without them', maxdiff(rlb['path']['curve'], sb40.mean(0)), 0.0, abs_=1e-7)

# ---- Forward Selection and Pruned Forward Selection ---------------------------------------------------------------------
rf = gr(y='y', method='forward')
cf = path_coefs(rf)
act, seq_ok, est_ok = [], True, 0.0
for s_ in range(1, cf.shape[1]):
    rss_ = {j: sm.OLS(yg_n, np.column_stack([A1[:, :1]] + [Z1[:, k] for k in act + [j]])).fit().ssr for j in range(6) if j not in act}
    new_ = [j for j in range(6) if cf[j, s_] != 0 and j not in act]
    seq_ok &= new_ == [min(rss_, key=rss_.get)]
    act = act + new_
    ols_ = sm.OLS(yg_n, np.column_stack([A1[:, :1]] + [Z1[:, k] for k in act])).fit().params[1:]
    est_ok = max(est_ok, float(np.max(np.abs(cf[act, s_] - ols_))))
check('Forward Selection (normal): each step enters the term that most lowers the error sum of squares', (seq_ok, cf.shape[1]), (True, 7))
check.near('... and each step is least squares on its terms', est_ok, 0.0, abs_=1e-9)
k_ = np.arange(cf.shape[1]) + 2.0                           # the terms, the intercept and the variance
ll_f = np.array([-0.5 * ng * (np.log(2 * np.pi * sm.OLS(yg_n, np.column_stack([A1[:, :1]] + [Z1[:, j] for j in range(6) if cf[j, s_] != 0])).fit().ssr / ng) + 1) for s_ in range(cf.shape[1])])
check.near('... its AICc path: -2LL + 2k + 2k(k + 1)/(N - k - 1), k counting the variance', maxdiff(rf['path']['aicc'], -2 * ll_f + 2 * k_ + 2 * k_ * (k_ + 1) / (ng - k_ - 1)), 0.0, abs_=1e-8)
check('... the step chosen has the smallest AICc', rf['chosen'], int(np.argmin(rf['path']['aicc'])))
rfb = gr(y='yb', method='forward')
cfb = path_coefs(rfb)
act, seq_ok, est_ok = [], True, 0.0
for s_ in range(1, cfb.shape[1]):
    fit_ = sm.GLM(yb01, np.column_stack([A1[:, :1]] + [Z1[:, k] for k in act]), family=sm.families.Binomial()).fit()
    st_ = {j: float(np.squeeze(fit_.score_test(exog_extra=Z1[:, [j]])[0])) for j in range(6) if j not in act}
    new_ = [j for j in range(6) if cfb[j, s_] != 0 and j not in act]
    seq_ok &= new_ == [max(st_, key=st_.get)]
    act = act + new_
    mle_ = sm.GLM(yb01, np.column_stack([A1[:, :1]] + [Z1[:, k] for k in act]), family=sm.families.Binomial()).fit().params[1:]
    est_ok = max(est_ok, float(np.max(np.abs(cfb[act, s_] - mle_))))
check('Forward Selection (binomial): each step enters the term with the largest score statistic (statsmodels\' score_test)', seq_ok, True)
check.near('... and each step is the logistic MLE on its terms', est_ok, 0.0, abs_=1e-6)
# a design where the floating search pays: xc = xa + xb + noise enters first, but {xa, xb} is the best pair
fx = np.random.default_rng(31)
xa_, xb_ = fx.normal(size=150), fx.normal(size=150)
xc_ = xa_ + xb_ + 0.4 * fx.normal(size=150)
yp_ = xa_ + xb_ + 0.3 * fx.normal(size=150)
tp_ = table({'xa': xa_.tolist(), 'xb': xb_.tolist(), 'xc': xc_.tolist(), 'xd': fx.normal(size=150).tolist(), 'y': yp_.tolist()})
Ep_ = [['xa'], ['xb'], ['xc'], ['xd']]
rfp = call('fitmodel.genreg', table=tp_, y='y', effects=Ep_, method='forward')
rpp = call('fitmodel.genreg', table=tp_, y='y', effects=Ep_, method='pruned')
steps_f = [tuple(int(j) for j in np.flatnonzero(c_)) for c_ in path_coefs(rfp).T]
steps_p = [tuple(int(j) for j in np.flatnonzero(c_)) for c_ in path_coefs(rpp).T]
check('Forward Selection enters xc first, then keeps it', (steps_f[1], all(2 in s_ for s_ in steps_f[1:])), ((2,), True))
check('Pruned Forward Selection: after xa and xb enter, xc leaves (the pair beats every pair before it)', steps_p[:5], [(), (2,), (0, 2), (0, 1, 2), (0, 1)])
rss_pair = lambda c_: sm.OLS(yp_, sm.add_constant(np.column_stack([[xa_, xb_, xc_][j] for j in c_]))).fit().ssr  # noqa: E731
best_pair = min(itertools.combinations(range(3), 2), key=rss_pair)
check('... which is the best pair, by brute force', best_pair, (0, 1))
check('... so its pair fits better than forward selection\'s', rss_pair(steps_p[4]) < rss_pair(steps_f[2]), True)

# ---- the Model Summary: the measures of each set by their formulas -------------------------------------------------------
S_h = summary_of(rh)
pr_h = np.array(rh['diag']['predicted'])
st_h = np.array(rh['diag']['set'])
tr_, va_ = st_h == 0, st_h == 1
s2_h = float(np.mean((yg_n[tr_] - pr_h[tr_]) ** 2))
nll_hv = 0.5 * float(np.sum(np.log(2 * np.pi * s2_h) + (yg_n[va_] - pr_h[va_]) ** 2 / s2_h))
check.near('Model Summary (normal): the Validation -LogLikelihood takes the training residuals\' variance SSE/N', S_h['-LogLikelihood']['Validation'], nll_hv, rel=1e-10)
check.near('... the Training -LogLikelihood = N/2 (log 2π SSE/N + 1)', S_h['-LogLikelihood']['Training'], 0.5 * tr_.sum() * (math.log(2 * math.pi * s2_h) + 1), rel=1e-10)
check.near('... Scaled -LogLikelihood = -LogLikelihood / N', S_h['Scaled -LogLikelihood']['Validation'], nll_hv / va_.sum(), rel=1e-10)
check.near('... RASE of the Validation rows', S_h['RASE']['Validation'], math.sqrt(float(np.mean((yg_n[va_] - pr_h[va_]) ** 2))), rel=1e-10)
check.near('... Generalized RSquare of the Training rows = 1 - SSE/SST', S_h['Generalized RSquare']['Training'],
           1 - float(np.sum((yg_n[tr_] - pr_h[tr_]) ** 2) / np.sum((yg_n[tr_] - yg_n[tr_].mean()) ** 2)), rel=1e-9)
s02_ = float(np.mean((yg_n[tr_] - yg_n[tr_].mean()) ** 2))
ll0_v = -0.5 * float(np.sum(np.log(2 * np.pi * s02_) + (yg_n[va_] - yg_n[tr_].mean()) ** 2 / s02_))
check.near('... of the Validation rows, against the training mean: 1 - exp(2(LL0 - LL)/N)', S_h['Generalized RSquare']['Validation'], 1 - math.exp(2 * (ll0_v + nll_hv) / va_.sum()), rel=1e-9)
check('... Number of Parameters, BIC and AICc are the training fit\'s', (S_h['AICc']['Validation'], S_h['BIC']['Validation'], S_h['Number of Parameters']['Training']), (None, None, rh['path']['df'][rh['chosen']]))
check.near('the holdback curve at the model is its Validation Scaled -LogLikelihood', rh['path']['curve'][rh['chosen']], S_h['Scaled -LogLikelihood']['Validation'], abs_=1e-12)
S_b = summary_of(rhb)
pb_ = np.array(rhb['diag']['predicted'])
check.near('Model Summary (binomial): Scaled -LogLikelihood = scikit-learn log_loss, Validation rows', S_b['Scaled -LogLikelihood']['Validation'], skm.log_loss(yb01[vah], pb_[vah], labels=[0, 1]), rel=1e-9)
check.near('... and Training rows', S_b['Scaled -LogLikelihood']['Training'], skm.log_loss(yb01[trh], pb_[trh], labels=[0, 1]), rel=1e-9)
ll0b = float(np.sum(yb01[trh] * np.log(yb01[trh].mean()) + (1 - yb01[trh]) * np.log(1 - yb01[trh].mean())))
llb = -S_b['-LogLikelihood']['Training']
check.near('... Generalized RSquare (Nagelkerke) of the training rows', S_b['Generalized RSquare']['Training'], (1 - math.exp(2 * (ll0b - llb) / trh.sum())) / (1 - math.exp(2 * ll0b / trh.sum())), rel=1e-9)
check('predicted probabilities stay inside (0, 1)', bool(np.all((pb_ > 0) & (pb_ < 1))), True)

# ---- a model chosen on the path; the profiler --------------------------------------------------------------------------
rc_ = gr(y='y', criterion='kfold', folds=5, seed=123, choose=5)
check('a chosen point: the model at that penalty, of the same fold', (rc_['chosen'], rc_['best'], rc_['model']['fold']), (5, rk['best'], rk['model']['fold']))
check.near('... its estimates are the path\'s there', maxdiff(scaled_est(rc_)[1:], path_coefs(rk)[:, 5]), 0.0, abs_=1e-12)
p1_ = fit_model._genreg_path(tg, None, fit_model._spec(y='y', effects=Eg6, criterion='kfold', folds=5, seed=123))
p2_ = fit_model._genreg_path(tg, None, fit_model._spec(y='y', effects=Eg6, criterion='kfold', folds=5, seed=123, choose=5))
check('choosing a point does not refit the path', p1_ is p2_, True)
pf_ = call('fitmodel.profile', table=tg, kind='genreg', y='yb', effects=Eg6, method='enet', enet_alpha=0.5, criterion='holdback', portion=0.3, seed=9,
           current={f'x{i}': float(Xg[7, i]) for i in range(6)})
check.near('the profiler predicts the chosen model (a row\'s Prob[yes])', pf_['responses'][0]['current']['pred'], rhb['diag']['predicted'][7], abs_=1e-12)
check('... named as the level', pf_['responses'][0]['name'], 'Prob[yes]')
t0_ = __import__('time').time()
Xt_ = gr_rng.normal(size=(5000, 10))
tt_ = table({**{f'z{i}': Xt_[:, i].tolist() for i in range(10)}, 'yb': np.where(Xt_[:, 0] - Xt_[:, 1] + gr_rng.logistic(size=5000) > 0, 'a', 'b').tolist()})
call('fitmodel.genreg', table=tt_, y='yb', effects=[[f'z{i}'] for i in range(10)], criterion='kfold', seed=1)
check('5000 rows, 10 terms, binomial lasso with KFold: a few seconds at most', __import__('time').time() - t0_ < 6, True)

# ---- the Python under the report, on the table exported as CSV --------------------------------------------------------
for label, kw in [('KFold lasso (normal)', dict(y='y', criterion='kfold', folds=5, seed=123)),
                  ('a chosen point of KFold', dict(y='y', criterion='kfold', folds=5, seed=123, choose=5)),
                  ('Holdback elastic net (binomial)', dict(y='yb', method='enet', enet_alpha=0.5, criterion='holdback', portion=0.3, seed=9)),
                  ('a Validation column of names, Poisson lasso', dict(y='yc', dist='poisson', criterion='validation', validation='vt')),
                  ('Forward Selection by AICc', dict(y='y', method='forward')),
                  ('Adaptive Lasso by BIC with a Weight', dict(y='y', adaptive=True, criterion='bic', weight='w')),
                  ('Adaptive Elastic Net, binomial, KFold', dict(y='yb', method='enet', adaptive=True, criterion='kfold', folds=4, seed=5)),
                  ('Pruned Forward Selection with a numeric Validation column missing some rows', dict(y='yb', method='pruned', criterion='validation', validation='v')),
                  ('Leave-One-Out ridge on 40 rows', dict(y='y', method='ridge', criterion='loo', rows=list(range(40))))]:
    rr_ = gr(table_name='grcsv', **kw)
    ns, err = run_code(rr_['code'], gdf, 'grcsv')
    check(f'Generalized Regression code runs: {label}', err, None)
    if err:
        print(rr_['code'])
        continue
    got_ = ns['b'] if 'b' in ns and kw.get('method') in ('forward', 'pruned') else np.asarray(ns['fit'].params)
    check.near(f'... its fit has the report\'s scaled estimates: {label}', maxdiff(scaled_est(rr_), got_), 0.0, abs_=1e-4)
    if 'curve' in ns:
        check.near(f'... its curve is the report\'s: {label}', maxdiff(rr_['path']['curve'], ns['curve']) / max(1.0, float(np.max(np.abs(ns['curve'])))), 0.0, abs_=1e-5)
    if 'lams' in ns:
        check.near(f'... its penalties are the report\'s: {label}', maxdiff(rr_['path']['alpha'], ns['lams']) / rr_['path']['alpha'][0], 0.0, abs_=1e-9)
    sm_ = summary_of(rr_)['Scaled -LogLikelihood']
    check.near(f'... the Scaled -LogLikelihood of its sets: {label}', max(abs(ns['fit_nll'][k_] - sm_[k_]) for k_ in ns['fit_nll']), 0.0, abs_=1e-5)

# ======================================================================================================================
# MANOVA > Repeated Measures, and the effect sizes of the Effect Tests
# ======================================================================================================================
# Checked against statsmodels' AnovaRM and MANOVA called directly, least squares
# on the stacked (long) data with a column per subject, scipy's t tests, the
# formulas of Mauchly (1940), Greenhouse and Geisser (1959), Huynh and Feldt
# (1976) and Lecoutre (1991) written out here, JMP's documented Sphericity Test
# (Fitting Linear Models, Figure 10.10: the Dogs example, Mauchly Criterion
# 0.1752641, ChiSquare 16.930873, DF 5, Prob > Chisq 0.0046328, 15 dogs in 4
# groups), and pingouin (GPL: called here as a reference only, its datasets read
# at run time) when it is installed.
from statsmodels.multivariate.manova import MANOVA as SM_MANOVA
from statsmodels.stats.anova import AnovaRM
try:
    import pingouin as pg
except ImportError:  # the reference checks that need it are skipped
    pg = None
    print('pingouin is not installed: its reference checks are skipped')


def rm_call(tid_, ys_, effects_, within_='Time', **kw):
    return call('fitmodel.manova', table=tid_, y=ys_, effects=effects_, response='repeated', within=within_, **kw)


def rm_tests(r_):
    """{effect: {test: row}} of the between and the within tables, and the univariate rows."""
    b_ = {t['effect']: {x['test']: x for x in t['rows']} for t in r_['between']}
    w_ = {t['effect']: {x['test']: x for x in t['rows'] + t['univariate']} for t in r_['within_tests']}
    return b_, w_


def orthonormal_contrasts(k_):
    """An orthonormal basis of the contrasts other than the page's (normalized Helmert): the
    univariate tests and the sphericity test must not depend on the basis."""
    H_ = np.zeros((k_, k_ - 1))
    for j_ in range(1, k_):
        H_[:j_, j_ - 1] = 1.0
        H_[j_, j_ - 1] = -j_
        H_[:, j_ - 1] /= np.linalg.norm(H_[:, j_ - 1])
    return H_


def long_ols(Y_, groups_):
    """The within tests of a split plot by least squares on the stacked data: a column per
    subject, the within factor effect coded, its crossing with the group (effect coded).
    Returns (the fit, the within columns, the crossing columns); the tests are Type III."""
    n_, k_ = Y_.shape
    lv = sorted(set(groups_))
    g_ = len(lv)
    Tc = np.vstack([np.eye(k_ - 1), -np.ones((1, k_ - 1))])          # effect coding of the levels
    Gc = np.vstack([np.eye(g_ - 1), -np.ones((1, g_ - 1))]) if g_ > 1 else np.zeros((1, 0))
    rows_ = []
    for i_ in range(n_):
        gi = Gc[lv.index(groups_[i_])]
        for t_ in range(k_):
            subj = np.zeros(n_)
            subj[i_] = 1
            rows_.append(np.concatenate([subj, Tc[t_], np.kron(gi, Tc[t_])]))
    Z_ = np.array(rows_)
    fit_ = sm.OLS(Y_.reshape(-1), Z_).fit()
    wcols = list(range(n_, n_ + k_ - 1))
    icols = list(range(n_ + k_ - 1, Z_.shape[1]))
    return fit_, wcols, icols


def ftest_cols(fit_, cols):
    R_ = np.zeros((len(cols), len(fit_.params)))
    for i_, c_ in enumerate(cols):
        R_[i_, c_] = 1
    ft_ = fit_.f_test(R_)
    return float(np.squeeze(ft_.fvalue)), float(np.squeeze(ft_.pvalue)), float(ft_.df_num), float(ft_.df_denom)


def mauchly_by_hand(S_, nu_):
    p_ = S_.shape[0]
    W_ = np.linalg.det(S_) / (np.trace(S_) / p_) ** p_
    chi2_ = -(nu_ - (2 * p_ * p_ + p_ + 2) / (6 * p_)) * np.log(W_)
    df_ = p_ * (p_ + 1) / 2 - 1
    return W_, chi2_, df_, stats.chi2.sf(chi2_, df_)


def pooled_contrast_cov(Y_, groups_, C_):
    """The covariance of the contrasts C of the responses about their group means (the
    between model of one factor), on n - g DF: what Mauchly's test and the epsilons read."""
    D_ = Y_ @ C_
    lv = sorted(set(groups_))
    R_ = np.vstack([D_[np.array(groups_) == g_] - D_[np.array(groups_) == g_].mean(0) for g_ in lv])
    return R_.T @ R_ / (len(Y_) - len(lv))


# ---- JMP's documented Sphericity Test (the Dogs example) and the helper's formulas ------------------------------
chi2_j, df_j, p_j = fit_model._mauchly(0.1752641, 11, 3)
check.near("Mauchly's chi-square of JMP's Dogs example (W 0.1752641, 11 error DF, 4 times): 16.930873", chi2_j, 16.930873, rel=2e-7)
check('... on 5 DF', df_j, 5.0)
check.near('... Prob > Chisq 0.0046328 (the plain chi-square p-value, as JMP)', p_j, 0.0046328, rel=2e-5)
eps_t = fit_model._epsilons(np.diag([1.0, 1.0, 1.0]), 12, 9)
check('spherical S: every epsilon 1, the lower bound 1/p', (eps_t['gg'], eps_t['hf'], eps_t['hf_lecoutre'], round(eps_t['lower'], 12)), (1.0, 1.0, 1.0, round(1 / 3, 12)))
Sx = np.array([[4.0, 1.0], [1.0, 0.5]])
eps_t = fit_model._epsilons(Sx, 20, 17)
gg_x = np.trace(Sx) ** 2 / (2 * np.trace(Sx @ Sx))
check.near('Greenhouse-Geisser epsilon = tr(S)²/(p tr(S²))', eps_t['gg'], gg_x, rel=1e-12)
check.near('Huynh-Feldt (1976): (N p gg - 2)/(p (nu - p gg)), N = 20 subjects, nu = 17', eps_t['hf'], min(1, (20 * 2 * gg_x - 2) / (2 * (17 - 2 * gg_x))), rel=1e-12)
check.near("Lecoutre's (1991) correction: nu + 1 in place of N", eps_t['hf_lecoutre'], min(1, (18 * 2 * gg_x - 2) / (2 * (17 - 2 * gg_x))), rel=1e-12)

# ---- one within factor, no between effects -------------------------------------------------------------------------
rng_rm = np.random.default_rng(20260927)
n1, k1 = 14, 4
Y1 = rng_rm.normal(size=(n1, 1)) * 1.5 + rng_rm.normal(size=(n1, k1)) @ np.diag([1, 1.4, 2, 2.6]) + np.array([0, 0.4, 0.9, 0.7])
Y1[:, 2] += 0.8 * Y1[:, 1]
Y1m = Y1.copy()
Y1m[3, 2] = np.nan                                           # a subject missing a measurement is left out
cols1 = [f't{i}' for i in range(k1)]
tid_rm1 = table({c: Y1m[:, i].tolist() for i, c in enumerate(cols1)})
r1 = rm_call(tid_rm1, cols1, [])
Y1c = np.delete(Y1, 3, axis=0)
nc1 = len(Y1c)
check('Repeated Measures: the rows with every response (a subject with a missing one is left out)', (r1['n'], r1['k'], r1['p'], r1['dfe']), (nc1, 4, 3, nc1 - 1))
b1, w1 = rm_tests(r1)
check('Between Subjects: the Intercept; Within Subjects: Time (no effects, no All Between)', (list(b1), list(w1)), (['Intercept'], ['Time']))
long1 = pd.DataFrame(Y1c, columns=cols1).reset_index().melt(id_vars='index', var_name='time', value_name='y')
arm = AnovaRM(long1, 'y', 'index', within=['time']).fit().anova_table
check.near('the univariate Time F = statsmodels AnovaRM', w1['Time']['Univar unadj Epsilon']['f'], float(arm['F Value'].iloc[0]), rel=1e-10)
check.near('... its p-value (unadjusted)', w1['Time']['Univar unadj Epsilon']['p'], float(arm['Pr > F'].iloc[0]), rel=1e-9)
check('... its DF', (w1['Time']['Univar unadj Epsilon']['numdf'], w1['Time']['Univar unadj Epsilon']['dendf']), (float(arm['Num DF'].iloc[0]), float(arm['Den DF'].iloc[0])))
# the within Time test is Hotelling's one-sample T² of the contrasts
Dc = Y1c[:, 1:] - Y1c[:, :1]
dbar = Dc.mean(0)
T2 = nc1 * dbar @ np.linalg.inv(np.cov(Dc, rowvar=False)) @ dbar
F_T2 = (nc1 - 3) / (3 * (nc1 - 1)) * T2
check('Time: one DF, so one exact F Test', (list(w1['Time'])[0], r1['within_tests'][0]['exact']), ('F Test', True))
check.near("Time's Exact F = Hotelling's T² of the contrasts, (n - p)/(p (n - 1)) T²", w1['Time']['F Test']['f'], F_T2, rel=1e-10)
check('... on p and n - p DF', (w1['Time']['F Test']['numdf'], w1['Time']['F Test']['dendf']), (3.0, float(nc1 - 3)))
check.near('... its p-value', w1['Time']['F Test']['p'], float(stats.f.sf(F_T2, 3, nc1 - 3)), rel=1e-9)
# the between Intercept is the t test of the sums
tt = stats.ttest_1samp(Y1c.sum(1), 0.0)
check.near('Between Intercept: the Exact F is t² of the one-sample t test of the sums', b1['Intercept']['F Test']['f'], float(tt.statistic) ** 2, rel=1e-10)
check.near('... its Value is F/nu (the eigenvalue h/e of the sum)', b1['Intercept']['F Test']['value'], float(tt.statistic) ** 2 / (nc1 - 1), rel=1e-10)
# sphericity and the epsilons, by hand, with another orthonormal basis
Sh = np.cov(Y1c @ orthonormal_contrasts(k1), rowvar=False)
Wh, chih, dfh, ph = mauchly_by_hand(Sh, nc1 - 1)
sp1 = r1['sphericity']
check.near("Mauchly's criterion by the formula (Helmert contrasts: the basis does not matter)", sp1['w'], Wh, rel=1e-10)
check.near('... its chi-square', sp1['chi2'], chih, rel=1e-10)
check('... its DF', sp1['df'], dfh)
check.near('... its p-value', sp1['p'], ph, rel=1e-9)
gg1 = np.trace(Sh) ** 2 / (3 * np.trace(Sh @ Sh))
check.near('G-G epsilon by the formula', r1['epsilon']['gg'], gg1, rel=1e-10)
check.near('the G-G row: its Value is the epsilon', w1['Time']['Univar G-G Epsilon']['value'], gg1, rel=1e-10)
check.near('... and both DF are multiplied by it', w1['Time']['Univar G-G Epsilon']['numdf'], 3 * gg1, rel=1e-10)
check.near('... its p-value', w1['Time']['Univar G-G Epsilon']['p'], float(stats.f.sf(float(arm['F Value'].iloc[0]), 3 * gg1, 3 * (nc1 - 1) * gg1)), rel=1e-8)
hf1 = min(1, (nc1 * 3 * gg1 - 2) / (3 * (nc1 - 1 - 3 * gg1)))
check.near('H-F epsilon by the 1976 formula', r1['epsilon']['hf'], hf1, rel=1e-10)
check.near('... Lecoutre\'s correction gives the same with one group', r1['epsilon']['hf_lecoutre'], hf1, rel=1e-10)
check('the univariate F is the same in the three rows', len({round(w1['Time'][t]['f'], 12) for t in ('Univar unadj Epsilon', 'Univar G-G Epsilon', 'Univar H-F Epsilon')}), 1)
if pg is not None:
    ra = pg.rm_anova(data=long1, dv='y', within='time', subject='index', correction=True)
    check.near('pingouin rm_anova: F', w1['Time']['Univar unadj Epsilon']['f'], float(ra['F'].iloc[0]), rel=1e-10)
    check.near('pingouin rm_anova: the unadjusted p', w1['Time']['Univar unadj Epsilon']['p'], float(ra['p_unc'].iloc[0]), rel=1e-8)
    check.near('pingouin rm_anova: the G-G p', w1['Time']['Univar G-G Epsilon']['p'], float(ra['p_GG_corr'].iloc[0]), rel=1e-8)
    check.near('pingouin rm_anova: the G-G epsilon', r1['epsilon']['gg'], float(ra['eps'].iloc[0]), rel=1e-10)
    check.near('pingouin rm_anova: Mauchly\'s W', sp1['w'], float(ra['W_spher'].iloc[0]), rel=1e-10)
    sph_pg = pg.sphericity(long1, dv='y', within='time', subject='index')
    check.near('pingouin sphericity: W', sp1['w'], float(sph_pg.W), rel=1e-10)
    check.near('pingouin sphericity: the chi-square', sp1['chi2'], float(sph_pg.chi2), rel=1e-10)
    check('pingouin sphericity: the DF', sp1['df'], float(sph_pg.dof))
    # pingouin's p-value (as R's mauchly.test) adds a second-order term; JMP's is the plain chi-square (its Dogs example, above)
    check('pingouin\'s sphericity p-value is a little above the plain chi-square one', 0 < float(sph_pg.pval) - sp1['p'] < 0.01 * sp1['p'] + 1e-3, True)
    for c_, key_ in (('gg', 'gg'), ('hf', 'hf'), ('lb', 'lower')):
        check.near(f'pingouin epsilon({c_!r})', r1['epsilon'][key_], float(pg.epsilon(long1, dv='y', within='time', subject='index', correction=c_)), rel=1e-10)
    wide_pg = pg.read_dataset('rm_anova_wide')                  # pingouin's own example, read at run time
    tid_pgw = table({c: wide_pg[c].tolist() for c in wide_pg.columns})
    rpw = rm_call(tid_pgw, list(wide_pg.columns), [])
    lpw = wide_pg.dropna().reset_index().melt(id_vars='index', var_name='time', value_name='y')
    rpa = pg.rm_anova(data=lpw, dv='y', within='time', subject='index', correction=True)
    _b, wpw = rm_tests(rpw)
    check.near("pingouin's rm_anova_wide example (its complete rows): F", wpw['Time']['Univar unadj Epsilon']['f'], float(rpa['F'].iloc[0]), rel=1e-10)
    check.near('... the G-G p', wpw['Time']['Univar G-G Epsilon']['p'], float(rpa['p_GG_corr'].iloc[0]), rel=1e-8)
    check.near('... W', rpw['sphericity']['w'], float(rpa['W_spher'].iloc[0]), rel=1e-9)

# ---- a mixed design: one between factor, balanced ------------------------------------------------------------------
if pg is not None:
    mx = pg.read_dataset('mixed_anova')                        # 60 subjects in two groups, three times
    wide_mx = mx.pivot_table(index=['Subject', 'Group'], columns='Time', values='Scores').reset_index()
    times = ['August', 'January', 'June']
    grp_mx = wide_mx['Group'].astype(str).tolist()
    Ymx = wide_mx[times].to_numpy(float)
else:
    grp_mx = ['a' if i < 30 else 'b' for i in range(60)]
    Ymx = rng_rm.normal(size=(60, 3)) + rng_rm.normal(size=(60, 1)) + np.where(np.array(grp_mx) == 'a', 0.0, 0.5)[:, None]
    times = ['August', 'January', 'June']
tid_mx = table({'Group': grp_mx, **{t: Ymx[:, i].tolist() for i, t in enumerate(times)}})
rmx = rm_call(tid_mx, times, [['Group']])
bmx, wmx = rm_tests(rmx)
check('Between Subjects: All Between, Intercept, Group', list(bmx), ['All Between', 'Intercept', 'Group'])
check('Within Subjects: All Within Interactions, Time, Time*Group', list(wmx), ['All Within Interactions', 'Time', 'Time*Group'])
fit_l, wc_l, ic_l = long_ols(Ymx, grp_mx)
Fw, pw_, d1w, d2w = ftest_cols(fit_l, wc_l)
check.near('balanced: the univariate Time F = least squares on the stacked data (a column per subject)', wmx['Time']['Univar unadj Epsilon']['f'], Fw, rel=1e-9)
check('... its DF', (wmx['Time']['Univar unadj Epsilon']['numdf'], wmx['Time']['Univar unadj Epsilon']['dendf']), (d1w, d2w))
Fi, pi_, d1i, d2i = ftest_cols(fit_l, ic_l)
check.near('balanced: the univariate Time*Group F = the stacked fit\'s crossing', wmx['Time*Group']['Univar unadj Epsilon']['f'], Fi, rel=1e-9)
check.near('... its p-value', wmx['Time*Group']['Univar unadj Epsilon']['p'], pi_, rel=1e-8)
sums_mx = pd.DataFrame({'s': Ymx.sum(1), 'g': grp_mx})
a3_mx = sm.stats.anova_lm(smf.ols('s ~ C(g, Sum)', sums_mx).fit(), typ=3)
check.near('Between Group: the Exact F = the ANOVA of the subjects\' sums (anova_lm type III)', bmx['Group']['F Test']['f'], float(a3_mx.loc['C(g, Sum)', 'F']), rel=1e-10)
Sp = pooled_contrast_cov(Ymx, grp_mx, orthonormal_contrasts(3))
Wp, chip, dfp, pp_ = mauchly_by_hand(Sp, len(Ymx) - 2)
check.near('Mauchly\'s W of the contrasts pooled within the groups', rmx['sphericity']['w'], Wp, rel=1e-10)
check.near('... its chi-square on nu = n - g', rmx['sphericity']['chi2'], chip, rel=1e-9)
if pg is not None:
    ma = pg.mixed_anova(data=mx, dv='Scores', within='Time', subject='Subject', between='Group', correction=True).set_index('Source')
    check.near('pingouin mixed_anova: the between F of Group', bmx['Group']['F Test']['f'], float(ma.loc['Group', 'F']), rel=1e-9)
    check.near('pingouin mixed_anova: its p', bmx['Group']['F Test']['p'], float(ma.loc['Group', 'p_unc']), rel=1e-8)
    check.near('pingouin mixed_anova: the within F of Time', wmx['Time']['Univar unadj Epsilon']['f'], float(ma.loc['Time', 'F']), rel=1e-9)
    check.near('pingouin mixed_anova: its unadjusted p', wmx['Time']['Univar unadj Epsilon']['p'], float(ma.loc['Time', 'p_unc']), rel=1e-8)
    check.near('pingouin mixed_anova: its G-G p', wmx['Time']['Univar G-G Epsilon']['p'], float(ma.loc['Time', 'p_GG_corr']), rel=1e-8)
    check.near('pingouin mixed_anova: the Interaction F = Time*Group', wmx['Time*Group']['Univar unadj Epsilon']['f'], float(ma.loc['Interaction', 'F']), rel=1e-9)
    check.near('pingouin mixed_anova: the Interaction G-G p', wmx['Time*Group']['Univar G-G Epsilon']['p'], float(ma.loc['Interaction', 'p_GG_corr']), rel=1e-8)
    check.near('pingouin mixed_anova: the epsilon', rmx['epsilon']['gg'], float(ma.loc['Time', 'eps']), rel=1e-9)
    check.near('pingouin mixed_anova: W (pooled within the groups too)', rmx['sphericity']['w'], float(ma.loc['Time', 'W_spher']), rel=1e-9)

# ---- a mixed design: three unbalanced groups ------------------------------------------------------------------------
if pg is not None:
    mu = pg.read_dataset('mixed_anova_unbalanced')
    wide_mu = mu.pivot_table(index=['Subject', 'Group'], columns='Time', values='Scores').reset_index()
    tms = ['T0', 'T1', 'T2', 'T3']
    grp_mu = wide_mu['Group'].astype(str).tolist()
    Ymu = wide_mu[tms].to_numpy(float)
else:
    tms = ['T0', 'T1', 'T2', 'T3']
    grp_mu = ['a'] * 7 + ['b'] * 10 + ['c'] * 9
    Ymu = rng_rm.normal(size=(26, 4)) + rng_rm.normal(size=(26, 1))
tid_mu = table({'Group': grp_mu, **{t: Ymu[:, i].tolist() for i, t in enumerate(tms)}})
rmu = rm_call(tid_mu, tms, [['Group']])
bmu, wmu = rm_tests(rmu)
fit_u, wc_u, ic_u = long_ols(Ymu, grp_mu)
check.near('unbalanced: Time is the Type III test (the stacked fit, effect coded)', wmu['Time']['Univar unadj Epsilon']['f'], ftest_cols(fit_u, wc_u)[0], rel=1e-9)
check.near('unbalanced: Time*Group', wmu['Time*Group']['Univar unadj Epsilon']['f'], ftest_cols(fit_u, ic_u)[0], rel=1e-9)
Su = pooled_contrast_cov(Ymu, grp_mu, orthonormal_contrasts(4))
ggu = np.trace(Su) ** 2 / (3 * np.trace(Su @ Su))
nu_u = len(Ymu) - 3
check.near('unbalanced: the G-G epsilon of the pooled covariance', rmu['epsilon']['gg'], ggu, rel=1e-10)
check.near('unbalanced: Huynh-Feldt (1976), N = the subjects', rmu['epsilon']['hf'], min(1, (len(Ymu) * 3 * ggu - 2) / (3 * (nu_u - 3 * ggu))), rel=1e-10)
check.near('unbalanced: Lecoutre\'s correction, nu + 1 = N - g + 1', rmu['epsilon']['hf_lecoutre'], min(1, ((nu_u + 1) * 3 * ggu - 2) / (3 * (nu_u - 3 * ggu))), rel=1e-10)
# three small groups, very unequal variances over the levels: H-F below 1, and Lecoutre's correction below it
rng_ns = np.random.default_rng(7)
g_ns = ['a'] * 5 + ['b'] * 6 + ['c'] * 4
Y_ns = rng_ns.normal(size=(15, 1)) + rng_ns.normal(size=(15, 4)) * np.array([0.3, 0.6, 2.5, 4.0])
r_ns = rm_call(table({'Group': g_ns, **{t: Y_ns[:, i].tolist() for i, t in enumerate(tms)}}), tms, [['Group']])
S_ns = pooled_contrast_cov(Y_ns, g_ns, orthonormal_contrasts(4))
gg_ns = np.trace(S_ns) ** 2 / (3 * np.trace(S_ns @ S_ns))
hf_ns, hfl_ns = min(1, (15 * 3 * gg_ns - 2) / (3 * (12 - 3 * gg_ns))), min(1, (13 * 3 * gg_ns - 2) / (3 * (12 - 3 * gg_ns)))
check('a non-spherical design with three groups: Huynh-Feldt and Lecoutre below 1 and apart', (hf_ns < 1, hfl_ns < hf_ns - 0.01), (True, True))
check.near('... the H-F epsilon is the 1976 formula (N = 15 subjects)', r_ns['epsilon']['hf'], hf_ns, rel=1e-10)
check.near('... Lecoutre\'s (nu + 1 = 13) is given beside it', r_ns['epsilon']['hf_lecoutre'], hfl_ns, rel=1e-10)
check.near('... the Univar H-F row of Time uses the 1976 epsilon', rm_tests(r_ns)[1]['Time']['Univar H-F Epsilon']['value'], hf_ns, rel=1e-10)
# statsmodels MANOVA called directly on the design: the four statistics of Time*Group, and Time
Xmu = patsy.dmatrix('C(g, Sum)', pd.DataFrame({'g': grp_mu}), return_type='dataframe')
mvu = SM_MANOVA(Ymu, np.asarray(Xmu))
Cj = np.vstack([-np.ones((1, 3)), np.eye(3)])                     # JMP's Contrast, not orthonormal: the same tests
st_i = mvu.mv_test(hypotheses=[('i', np.eye(3)[1:], Cj)]).results['i']['stat']
for sm_name, jmp_name in [("Wilks' lambda", "Wilks' Lambda"), ("Pillai's trace", "Pillai's Trace"), ('Hotelling-Lawley trace', 'Hotelling-Lawley'), ("Roy's greatest root", "Roy's Max Root")]:
    check.near(f'Time*Group {jmp_name}: statsmodels MANOVA with the unorthonormalized contrasts', wmu['Time*Group'][jmp_name]['value'], float(st_i.loc[sm_name, 'Value']), rel=1e-9)
    check.near(f'... its F ({jmp_name})', wmu['Time*Group'][jmp_name]['f'], float(st_i.loc[sm_name, 'F Value']), rel=1e-9)
st_t = mvu.mv_test(hypotheses=[('t', np.eye(3)[:1], Cj)]).results['t']['stat']
check.near('Time: the exact F = statsmodels\' Wilks F of the intercept on the contrasts', wmu['Time']['F Test']['f'], float(st_t.loc["Wilks' lambda", 'F Value']), rel=1e-9)
check.near('... = its Hotelling-Lawley F (one DF: every statistic the same test)', wmu['Time']['F Test']['f'], float(st_t.loc['Hotelling-Lawley trace', 'F Value']), rel=1e-9)
check('All Within Interactions = Time*Group with one effect', wmu['All Within Interactions']["Wilks' Lambda"]['value'], wmu['Time*Group']["Wilks' Lambda"]['value'])
check('the note names the F approximations', any('McKeon' in x for x in rmu['notes']), True)
if pg is not None:
    mau = pg.mixed_anova(data=mu, dv='Scores', within='Time', subject='Subject', between='Group', correction=True).set_index('Source')
    check.near('pingouin mixed_anova (unbalanced): the between F of Group', bmu['Group']['F Test']['f'], float(mau.loc['Group', 'F']), rel=1e-9)
    check.near('pingouin mixed_anova (unbalanced): the Interaction F', wmu['Time*Group']['Univar unadj Epsilon']['f'], float(mau.loc['Interaction', 'F']), rel=1e-9)
    check.near('pingouin mixed_anova (unbalanced): the epsilon', rmu['epsilon']['gg'], float(mau.loc['Time', 'eps']), rel=1e-9)
    check.near('pingouin mixed_anova (unbalanced): W', rmu['sphericity']['w'], float(mau.loc['Time', 'W_spher']), rel=1e-9)
    # pingouin's Time main effect weighs the groups by their sizes (Type II); JMP's and ours is Type III
    check('pingouin\'s within main effect of unbalanced groups is not Type III (it weighs the groups)', abs(wmu['Time']['Univar unadj Epsilon']['f'] - float(mau.loc['Time', 'F'])) > 0.05, True)

# ---- two crossed between factors, and a continuous covariate --------------------------------------------------------
n4 = 40
a4 = np.repeat(['a1', 'a2'], 20)
b4 = np.tile(np.repeat(['b1', 'b2'], 10), 2)
x4 = rng_rm.normal(size=n4)
Y4 = rng_rm.normal(size=(n4, 1)) + rng_rm.normal(size=(n4, 5)) * np.array([1, 1.2, 1.5, 1.9, 2.4]) + np.outer(a4 == 'a2', [0, 0.5, 1.0, 1.2, 1.3]) + np.outer(x4, [0, 0.2, 0.4, 0.6, 0.8])
cols4 = [f'v{i}' for i in range(5)]
tid4 = table({'a': a4.tolist(), 'b': b4.tolist(), 'x': x4.tolist(), **{c: Y4[:, i].tolist() for i, c in enumerate(cols4)}})
E4 = [['a'], ['b'], ['a', 'b'], ['x']]
r4 = rm_call(tid4, cols4, E4, within_='Dose')
b4r, w4r = rm_tests(r4)
check('crossed factors and a covariate: the within tests take the Y Name', list(w4r), ['All Within Interactions', 'Dose', 'Dose*a', 'Dose*b', 'Dose*a*b', 'Dose*x'])
X4 = patsy.dmatrix('C(a, Sum) * C(b, Sum) + x', pd.DataFrame({'a': a4, 'b': b4, 'x': x4}), return_type='dataframe')
mv4 = SM_MANOVA(Y4, np.asarray(X4))
nm4 = list(X4.columns)
Pol = fit_model._transform_M('polynomial', 5)[0]                  # orthogonal polynomials: yet another contrast basis
for eff, term in [('a', 'C(a, Sum)[S.a1]'), ('x', 'x')]:
    L4 = np.eye(len(nm4))[[nm4.index(term)]]
    st4 = mv4.mv_test(hypotheses=[('h', L4, Pol)]).results['h']['stat']
    check.near(f'Dose*{eff}: the exact F = statsmodels MANOVA with polynomial contrasts', w4r[f'Dose*{eff}']['F Test']['f'], float(st4.loc["Wilks' lambda", 'F Value']), rel=1e-9)
    check.near(f'Dose*{eff}: its value = the Hotelling-Lawley trace', w4r[f'Dose*{eff}']['F Test']['value'], float(st4.loc['Hotelling-Lawley trace', 'Value']), rel=1e-9)
sums4 = pd.DataFrame({'s': Y4.sum(1), 'a': a4, 'b': b4, 'x': x4})
a3_4 = sm.stats.anova_lm(smf.ols('s ~ C(a, Sum) * C(b, Sum) + x', sums4).fit(), typ=3)
for eff, term in [('a', 'C(a, Sum)'), ('a*b', 'C(a, Sum):C(b, Sum)'), ('x', 'x')]:
    check.near(f'Between {eff}: the Exact F = the type III ANOVA of the sums', b4r[eff]['F Test']['f'], float(a3_4.loc[term, 'F']), rel=1e-9)
f4 = smf.ols('s ~ C(a, Sum) * C(b, Sum) + x', sums4).fit()
check.near('All Between = the whole-model F of the sums', b4r['All Between']['F Test']['f'], float(f4.fvalue), rel=1e-9)
U4 = orthonormal_contrasts(5)
R4 = Y4 - np.asarray(X4) @ np.linalg.lstsq(np.asarray(X4), Y4, rcond=None)[0]
S4 = U4.T @ R4.T @ R4 @ U4 / (n4 - 5)
check.near('Mauchly\'s W with the residuals of the full between model (nu = n - 5)', r4['sphericity']['w'], mauchly_by_hand(S4, n4 - 5)[0], rel=1e-9)
check('the whole-model tests have four statistics (Approx. F)', [t['exact'] for t in r4['within_tests']][0], False)

# ---- two levels: a paired t test; too few subjects; no intercept -----------------------------------------------------
Y2l = Y4[:, :2]
tid2l = table({'g': a4.tolist(), 'u': Y2l[:, 0].tolist(), 'w': Y2l[:, 1].tolist()})
r2l = rm_call(tid2l, ['u', 'w'], [])
_b, w2l = rm_tests(r2l)
check.near('two levels: the Time F Test is t² of the paired t test', w2l['Time']['F Test']['f'], float(stats.ttest_rel(Y2l[:, 1], Y2l[:, 0]).statistic) ** 2, rel=1e-10)
check('two levels: no sphericity test, every epsilon 1', (r2l['sphericity'], r2l['epsilon']['gg'], r2l['epsilon']['hf'], 'trivially' in r2l['sphericity_note']), (None, 1.0, 1.0, True))
r2g = rm_call(tid2l, ['u', 'w'], [['g']])
_b, w2g = rm_tests(r2g)
dd = Y2l[:, 1] - Y2l[:, 0]
check.near('two levels and a group: Time*g is t² of the two-sample t test of the differences', w2g['Time*g']['F Test']['f'], float(stats.ttest_ind(dd[a4 == 'a1'], dd[a4 == 'a2']).statistic) ** 2, rel=1e-10)
Yf = rng_rm.normal(size=(4, 6)) + np.arange(6)
tidf = table({f'q{i}': Yf[:, i].tolist() for i in range(6)})
rf = rm_call(tidf, [f'q{i}' for i in range(6)], [])
_b, wf = rm_tests(rf)
lf = pd.DataFrame(Yf).reset_index().melt(id_vars='index', var_name='t', value_name='y')
check('4 subjects, 6 levels (nu 3 < p 5): no multivariate within tests, no sphericity test', (rf['multivariate_within'], rf['sphericity'], 'not performed' in rf['sphericity_note']), (False, None, True))
check.near('... the univariate test still = AnovaRM', wf['Time']['Univar unadj Epsilon']['f'], float(AnovaRM(lf, 'y', 'index', within=['t']).fit().anova_table['F Value'].iloc[0]), rel=1e-10)
rni = rm_call(tid4, cols4, [['a']], no_intercept=True)
check('no intercept: no Time test, a note says so', ([t['effect'] for t in rni['within_tests']], any('no test of Time' in x for x in rni['notes'])), (['All Within Interactions', 'Time*a'], True))
check('a Weight is refused as in MANOVA', 'error' in call('fitmodel.manova', table=tid4, y=cols4, effects=[['a']], response='repeated', weight='x'), True)
rng_e = np.random.default_rng(11)
a_e, b_e = ['a1'] * 6 + ['a2'] * 6, ['b1'] * 3 + ['b2'] * 3 + ['b1'] * 6
tid_e = table({'a': a_e, 'b': b_e, **{f'y{i}': rng_e.normal(size=12).tolist() for i in range(3)}})
check('a crossing with an empty cell: a message, not an exception', 'singular' in rm_call(tid_e, ['y0', 'y1', 'y2'], [['a'], ['b'], ['a', 'b']]).get('error', ''), True)
# an effect that is exactly zero: statsmodels 0.14.6's mv_test fails (the max of an empty array); the page gives no effect
Ya_ = rng_e.normal(size=(8, 3))
Y0_ = np.vstack([Ya_, Ya_])                                       # the two groups hold the same rows
g0_ = ['g1'] * 8 + ['g2'] * 8
try:
    SM_MANOVA(Y0_, np.column_stack([np.ones(16), np.r_[np.ones(8), -np.ones(8)]])).mv_test(hypotheses=[('g', np.array([[0, 1.0]]))])
    sm_null = 'no error'
except ValueError as ex_:
    sm_null = 'zero-size array' in str(ex_)
check('statsmodels 0.14.6: mv_test of an exactly null effect raises (pinned; the page works around it)', sm_null, True)
tid0_ = table({'g': g0_, **{f'z{i}': Y0_[:, i].tolist() for i in range(3)}})
r0_ = rm_call(tid0_, ['z0', 'z1', 'z2'], [['g']])
b0_, w0_ = rm_tests(r0_)
check('an exactly null effect: no error; its between F Test is F 0, p 1', ('error' in r0_, b0_['g']['F Test']['f'], b0_['g']['F Test']['p']), (False, 0.0, 1.0))
check('... and its within test too', (round(w0_['Time*g']['F Test']['value'], 12), w0_['Time*g']['F Test']['p']), (0.0, 1.0))
ri0_ = call('fitmodel.manova', table=tid0_, y=['z0', 'z1', 'z2'], effects=[['g']])
ti0_ = {t['effect']: {x['test']: x for x in t['rows']} for t in ri0_['tests']}
check("... and in the Identity design: Wilks' lambda 1, p 1", (ti0_['g']["Wilks' Lambda"]['value'], ti0_['g']["Wilks' Lambda"]['p']), (1.0, 1.0))
Yc = rng_e.normal(size=(20, 3))
Yc = np.column_stack([Yc, Yc[:, 0] + Yc[:, 1]])                   # collinear responses: the contrasts can still be of full rank
rc_ = rm_call(table({f'c{i}': Yc[:, i].tolist() for i in range(4)}), [f'c{i}' for i in range(4)], [])
lc_ = pd.DataFrame(Yc).reset_index().melt(id_vars='index', var_name='t', value_name='y')
check.near('collinear responses: the within test still = AnovaRM', rm_tests(rc_)[1]['Time']['Univar unadj Epsilon']['f'], float(AnovaRM(lc_, 'y', 'index', within=['t']).fit().anova_table['F Value'].iloc[0]), rel=1e-9)
ri = call('fitmodel.manova', table=tid4, y=cols4, effects=E4)
check('the Identity response is as before (no repeated-measures keys)', ('tests' in ri, 'within_tests' in ri, [t['effect'] for t in ri['tests']][:2]), (True, False, ['Whole Model', 'Intercept']))

# ---- the code under the report, on the table exported as CSV --------------------------------------------------------
for label_, tid_, frame_, ys_, eff_, res_ in [
        ('no between effects, a missing value', tid_rm1, pd.DataFrame({c: Y1m[:, i] for i, c in enumerate(cols1)}), cols1, [], r1),
        ('crossed factors and a covariate', tid4, pd.DataFrame({'a': a4, 'b': b4, 'x': x4, **{c: Y4[:, i] for i, c in enumerate(cols4)}}), cols4, E4, r4),
        ('three unbalanced groups', tid_mu, pd.DataFrame({'Group': grp_mu, **{t: Ymu[:, i] for i, t in enumerate(tms)}}), tms, [['Group']], rmu)]:
    rr_ = rm_call(tid_, ys_, eff_, within_=res_['within'], table_name='rm')
    ns, err = run_code(rr_['code'], frame_, 'rm')
    check(f'Repeated Measures code runs: {label_}', err, None)
    if err:
        print(rr_['code'])
        continue
    bb_, ww_ = rm_tests(rr_)
    check.near(f'... its Mauchly W: {label_}', float(ns['Wm']), rr_['sphericity']['w'], rel=1e-9)
    check.near(f'... its chi-square: {label_}', float(ns['chi2']), rr_['sphericity']['chi2'], rel=1e-9)
    check.near(f'... its G-G and H-F epsilons: {label_}', float(ns['gg']) + float(ns['hf']), rr_['epsilon']['gg'] + rr_['epsilon']['hf'], rel=1e-10)
    for w_name, vals in ns['uni'].items():
        check.near(f'... its univariate F of {w_name}: {label_}', float(vals[0]), ww_[w_name]['Univar unadj Epsilon']['f'], rel=1e-9)
        check.near(f'... its G-G p of {w_name}: {label_}', float(vals[2]), ww_[w_name]['Univar G-G Epsilon']['p'], rel=1e-8)
        check.near(f'... its H-F p of {w_name}: {label_}', float(vals[3]), ww_[w_name]['Univar H-F Epsilon']['p'], rel=1e-8)
    for h_ in bb_:
        st_ = ns['between'].results[h_]['stat']
        check.near(f'... its between test of {h_}: {label_}', float(st_.loc['Hotelling-Lawley trace', 'Value']), bb_[h_]['F Test']['value'], rel=1e-9)
    for w_name in ww_:
        st_ = ns['within'].results[w_name]['stat']
        check.near(f'... its within Wilks\' lambda of {w_name}: {label_}', float(st_.loc["Wilks' lambda", 'Value']),
                   float(np.real(1 / (1 + ww_[w_name]['F Test']['value']))) if 'F Test' in ww_[w_name] else ww_[w_name]["Wilks' Lambda"]['value'], rel=1e-9)

# ---- Effect Tests: partial eta and omega squared -------------------------------------------------------------------
def es_rows(r_):
    return {x['source']: x for x in r_['effect_tests']['rows']}


tid_lon = table({c: lon[c].tolist() for c in lon.columns})
E_lon = [['GNPDEFL'], ['GNP'], ['UNEMP'], ['ARMED'], ['POP'], ['YEAR']]
r_lon = call('fitmodel.ls', table=tid_lon, y='TOTEMP', effects=E_lon)
es_cols = {c['key']: c for c in r_lon['effect_tests']['columns']}
check('Effect Tests: Partial η² and Partial ω², optional (hidden) columns', (es_cols['pes']['label'], es_cols['pes'].get('hidden'), es_cols['pos']['label'], es_cols['pos'].get('hidden')),
      ('Partial η²', True, 'Partial ω²', True))
check('... and the columns shown before are the same', [c['key'] for c in r_lon['effect_tests']['columns'] if not c.get('hidden')], ['source', 'nparm', 'df', 'ss', 'stat', 'p'])
rows_ = es_rows(r_lon)
sse_l = {x['source']: x for x in r_lon['anova']['rows']}['Error']
for src in ('GNP', 'YEAR'):
    x_ = rows_[src]
    check.near(f'Longley {src}: partial η² = SS/(SS + SSE)', x_['pes'], x_['ss'] / (x_['ss'] + sse_l['ss']), rel=1e-12)
    check.near(f'Longley {src}: partial ω² = DF(F - 1)/(DF(F - 1) + N)', x_['pos'], x_['df'] * (x_['stat'] - 1) / (x_['df'] * (x_['stat'] - 1) + 16), rel=1e-10)
check('the effect tests of a robust fit have no effect sizes', any('pes' in x for x in call('fitmodel.ls', table=tid_lon, y='TOTEMP', effects=E_lon, robust='HC3')['effect_tests']['rows']), False)
if pg is not None:
    an = pg.read_dataset('anova')                               # pain threshold by hair colour (McClave and Dietrich 1991)
    tid_an = table({'pain': an['Pain threshold'].tolist(), 'hair': an['Hair color'].astype(str).tolist()})
    ran = es_rows(call('fitmodel.ls', table=tid_an, y='pain', effects=[['hair']]))['hair']
    pga = pg.anova(data=an, dv='Pain threshold', between='Hair color', effsize='np2')
    check.near('one-way: partial η² = pingouin anova np2', ran['pes'], float(pga['np2'].iloc[0]), rel=1e-10)
    sst = float(((an['Pain threshold'] - an['Pain threshold'].mean()) ** 2).sum())
    mse_an = (sst - ran['ss']) / (len(an) - 4)
    check.near('one-way: partial ω² = Hays\'s ω² (SS_b - df_b MSE)/(SS_T + MSE)', ran['pos'], (ran['ss'] - 3 * mse_an) / (sst + mse_an), rel=1e-10)
    a2u = pg.read_dataset('anova2_unbalanced')                   # diet and exercise, unbalanced
    tid_a2 = table({'y': a2u['Scores'].tolist(), 'diet': a2u['Diet'].astype(str).tolist(), 'exercise': a2u['Exercise'].astype(str).tolist()})
    ra2 = es_rows(call('fitmodel.ls', table=tid_a2, y='y', effects=[['diet'], ['exercise'], ['diet', 'exercise']]))
    pa2 = pg.anova(data=a2u, dv='Scores', between=['Diet', 'Exercise'], ss_type=3, effsize='np2').set_index('Source')
    for src, pgs in (('diet', 'Diet'), ('exercise', 'Exercise'), ('diet*exercise', 'Diet * Exercise')):
        check.near(f'two-way unbalanced, type III: partial η² of {src} = pingouin anova np2', ra2[src]['pes'], float(pa2.loc[pgs, 'np2']), rel=1e-9)
    ac = pg.read_dataset('ancova')                              # teaching method with family income as covariate
    tid_ac = table({'y': ac['Scores'].tolist(), 'method': ac['Method'].astype(str).tolist(), 'income': ac['Income'].tolist()})
    rac = es_rows(call('fitmodel.ls', table=tid_ac, y='y', effects=[['method'], ['income']]))
    pac = pg.ancova(data=ac, dv='Scores', covar='Income', between='Method', effsize='np2').set_index('Source')
    check.near('ANCOVA: partial η² of the factor = pingouin ancova np2', rac['method']['pes'], float(pac.loc['Method', 'np2']), rel=1e-9)
    check.near('ANCOVA: partial η² of the covariate = pingouin ancova np2', rac['income']['pes'], float(pac.loc['Income', 'np2']), rel=1e-9)
# Freq counts rows: the effect sizes of a table with frequencies = those of its expanded rows
fq = rng_rm.integers(1, 4, 30).astype(float)
xq = rng_rm.normal(size=30)
gq = np.array(['p', 'q', 'r'])[np.arange(30) % 3]
yq = xq + (gq == 'q') * 0.8 + rng_rm.normal(size=30)
rfq = es_rows(call('fitmodel.ls', table=table({'y': yq.tolist(), 'x': xq.tolist(), 'g': gq.tolist(), 'f': fq.tolist()}), y='y', effects=[['x'], ['g']], freq='f'))
rep_ = np.repeat(np.arange(30), fq.astype(int))
rex_ = es_rows(call('fitmodel.ls', table=table({'y': yq[rep_].tolist(), 'x': xq[rep_].tolist(), 'g': gq[rep_].tolist()}), y='y', effects=[['x'], ['g']]))
check.near('Freq: partial η² = that of the expanded rows', rfq['g']['pes'], rex_['g']['pes'], rel=1e-9)
check.near('Freq: partial ω² = that of the expanded rows (N the sum of the frequencies)', rfq['x']['pos'], rex_['x']['pos'], rel=1e-9)
tid_pl = table({'fertilizer': fert.tolist(), 'water': water.tolist(), 'light': light.tolist(), 'yield': yv.tolist()},
               types={'water': 'ordinal'}, levels={'water': ['low', 'high']})
E_pl = [{'names': ['fertilizer']}, {'names': ['water']}, {'names': ['light']}, {'names': ['fertilizer', 'water']}, {'names': ['light', 'light']}]
plants_es = pd.DataFrame({'fertilizer': fert, 'water': water, 'light': light, 'yield': yv})
for label_, kw_, frame_ in [('the plants model (crossings, a power)', dict(table=tid_pl, y='yield', effects=E_pl), plants_es),
                            ('with a Freq column', dict(table=table({'y': yq.tolist(), 'x': xq.tolist(), 'g': gq.tolist(), 'f': fq.tolist()}), y='y', effects=[['x'], ['g']], freq='f'),
                             pd.DataFrame({'y': yq, 'x': xq, 'g': gq, 'f': fq}))]:
    rr_ = call('fitmodel.ls', table_name='es', **kw_)
    ns, err = run_code(rr_['code'], frame_, 'es')
    check(f'the Standard Least Squares code computes the effect sizes: {label_}', err, None)
    if not err:
        got_ = sorted(x['pes'] for x in rr_['effect_tests']['rows'])
        check.near(f'... its partial eta squared are the report\'s: {label_}', maxdiff(got_, sorted(ns['et']['Partial eta2'])), 0.0, abs_=1e-10)
        check.near(f'... and its partial omega squared: {label_}', maxdiff(sorted(x['pos'] for x in rr_['effect_tests']['rows']), sorted(ns['et']['Partial omega2'])), 0.0, abs_=1e-10)
noise = es_rows(call('fitmodel.ls', table=table({'y': rng_rm.normal(size=40).tolist(), 'z': rng_rm.normal(size=40).tolist(), 'h': (['s', 't'] * 20)}), y='y', effects=[['z'], ['h']]))
check('partial ω² is negative exactly when F < 1', [(noise[s_]['pos'] < 0) == (noise[s_]['stat'] < 1) for s_ in ('z', 'h')], [True, True])

sys.exit(check.done())
