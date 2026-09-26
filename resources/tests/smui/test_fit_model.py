#!/usr/bin/env python3
"""Analyze > Fit Model's backend (resources/py/smui/fit_model.py), checked
against statsmodels and scipy called directly, the NIST StRD certified values
(Longley, Wampler 1 and 2), textbook results (Greene's logit of the Spector
and Mazzeo data, the balanced one-way random effects model) and brute force
(leave-one-out PRESS, simulated Durbin-Watson p-values, all subsets).

    python3 resources/tests/smui/test_fit_model.py

The statsmodels datasets are loaded from the installed package at run time;
everything else is simulated here with fixed seeds.
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
sys.exit(check.done())
