#!/usr/bin/env python3
"""The linear-model helpers (resources/py/smui/models.py): JMP's term names,
effect coding, centred crossings, and the report tables, checked against
statsmodels' own anova_lm and the NIST certified values for the Longley
regression (loaded from statsmodels.datasets at run time).

    python3 resources/tests/smui/test_models.py
"""
import sys

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from backend import Checks, table
from smui import models

check = Checks()

# NIST StRD Longley, certified values
lon = sm.datasets.longley.load_pandas().data
tid = table({c: lon[c].tolist() for c in lon.columns})
d = models.build(tid, 'TOTEMP', [['GNPDEFL'], ['GNP'], ['UNEMP'], ['ARMED'], ['POP'], ['YEAR']])
res = models.fit_ols(d)
cert = {'Intercept': -3482258.63459582, 'GNPDEFL': 15.0618722713733, 'GNP': -0.358191792925910e-01, 'UNEMP': -2.02022980381683,
        'ARMED': -1.03322686717359, 'POP': -0.511041056535807e-01, 'YEAR': 1829.15146461355}
est = {r['term']: r['estimate'] for r in models.estimates(d, res)['rows']}
for k, v in cert.items():
    check.near(f'Longley {k}', est[k], v, rel=1e-7)
sof = {r['stat']: r['value'] for r in models.summary_of_fit(d, res)['rows']}
check.near('Longley RSquare', sof['RSquare'], 0.995479004577296, rel=1e-9)
check.near('Longley RMSE', sof['Root Mean Square Error'], 304.854073561965, rel=1e-9)

# Effect coding, crossings, powers: names and Type III tests
rng = np.random.default_rng(3)
n = 72
fert = np.repeat(['A', 'B', 'C'], 24)
water = np.tile(np.repeat(['low', 'high'], 12), 3)
light = rng.normal(6, 1.5, n)
y = 20 + (fert == 'B') * 3 + (fert == 'C') * 5.5 + (water == 'high') * 4 + ((fert == 'C') & (water == 'high')) * 2.5 + 1.2 * light + rng.normal(0, 2.2, n)
tid = table({'fertilizer': fert.tolist(), 'water': water.tolist(), 'light': light.tolist(), 'yield': y.tolist()},
            types={'water': 'ordinal'}, levels={'water': ['low', 'high']})
d = models.build(tid, 'yield', [['fertilizer'], ['water'], ['light'], ['fertilizer', 'water'], ['light', 'light']])
res = models.fit_ols(d)
terms = [r['term'] for r in models.estimates(d, res)['rows']]
m = light.mean()
check('term names', terms, ['Intercept', 'fertilizer[A]', 'fertilizer[B]', 'water[low]', 'light', 'fertilizer[A]*water[low]', 'fertilizer[B]*water[low]', f'(light-{m:.6g})*(light-{m:.6g})'])
df = pd.DataFrame({'f': fert, 'w': pd.Categorical(water, ['low', 'high']), 'l': light, 'y': y})
ref = smf.ols(f'y ~ C(f, Sum) + C(w, Sum) + l + C(f, Sum):C(w, Sum) + I((l - {m!r})**2)', df).fit()
a3 = sm.stats.anova_lm(ref, typ=3)
et = {r['source']: r for r in models.effect_tests(d, res)['rows']}
for src, key in [('fertilizer', 'C(f, Sum)'), ('water', 'C(w, Sum)'), ('light', 'l'), ('fertilizer*water', 'C(f, Sum):C(w, Sum)')]:
    check.near(f'type III SS {src}', et[src]['ss'], float(a3.loc[key, 'sum_sq']), rel=1e-9)
    check.near(f'type III p {src}', et[src]['p'], float(a3.loc[key, 'PR(>F)']), rel=1e-7)
# predictions at new points in alias space
fr = d.frame_for({'fertilizer': ['A', 'C'], 'water': ['low', 'high'], 'light': [5.0, 7.0]})
p = res.get_prediction(fr).predicted_mean
pr = ref.get_prediction(pd.DataFrame({'f': ['A', 'C'], 'w': pd.Categorical(['low', 'high'], ['low', 'high']), 'l': [5.0, 7.0]})).predicted_mean
check.near('prediction at a new point', float(p[1]), float(pr[1]))
# lack of fit with replicates
xr = np.repeat([1.0, 2, 3, 4, 5], 4)
yr = 2 + 0.5 * xr + 0.3 * (xr - 3) ** 2 + rng.normal(0, 0.2, 20)
tid = table({'x': xr.tolist(), 'y': yr.tolist()})
d = models.build(tid, 'y', [['x']])
res = models.fit_ols(d)
lof = models.lack_of_fit(d, res)
pe = sum(float(np.sum((yr[xr == v] - yr[xr == v].mean()) ** 2)) for v in np.unique(xr))
check.near('pure error SS', lof['rows'][1]['ss'], pe)
check('lack of fit df', (lof['rows'][0]['df'], lof['rows'][1]['df']), (3.0, 15))
check('lack of fit significant (curvature)', lof['rows'][0]['p'] < 0.001, True)
check('code formula', models.code_formula(d), 'y ~ x')
# The shown code must drop the same level as the report: a value order that
# is not alphabetical (placebo before drug) must survive into the formula.
trt = np.where(rng.uniform(size=60) < 0.5, 'placebo', 'drug')
yv = 5 + (trt == 'drug') * 2 + rng.normal(0, 1, 60)
tid = table({'treatment': trt.tolist(), 'y': yv.tolist()}, levels={'treatment': ['placebo', 'drug']})
d = models.build(tid, 'y', [['treatment']])
res = models.fit_ols(d)
f = models.code_formula(d)
check('the formula keeps the level order', f, "y ~ C(treatment, Sum, levels=['placebo', 'drug'])")
shown = smf.ols(f, pd.DataFrame({'treatment': trt, 'y': yv})).fit()
check.near('the shown code gives the report\'s estimate', float(shown.params.iloc[1]), float(res.params.iloc[1]))
check('and names the same level', [r['term'] for r in models.estimates(d, res)['rows']][1], 'treatment[placebo]')
# Analysis of covariance, x + g + x*g: patsy must see one factor for x (the
# main effect centred like the crossing), or it codes g at full rank inside
# the crossing and the design is singular. JMP's design, built by hand:
# intercept, x, the effect-coded g, and g times (x - mean).
xa = rng.normal(10, 2, 90)
ga = np.repeat(['a', 'b', 'c'], 30)
ya = 3 + 0.8 * xa + (ga == 'b') * 1.5 + rng.normal(0, 1, 90)
tid = table({'x': xa.tolist(), 'g': ga.tolist(), 'y': ya.tolist()})
d = models.build(tid, 'y', [['x'], ['g'], ['x', 'g']])
res = models.fit_ols(d)
et = {r['source']: r for r in models.effect_tests(d, res)['rows']}
check('the crossing has k - 1 degrees of freedom', et['x*g']['df'], 2)
check('the design is of full rank', int(np.linalg.matrix_rank(res.model.exog)), res.model.exog.shape[1])
mx = xa.mean()
eff = np.stack([np.where(ga == 'a', 1.0, np.where(ga == 'c', -1.0, 0.0)), np.where(ga == 'b', 1.0, np.where(ga == 'c', -1.0, 0.0))], axis=1)
X = np.column_stack([np.ones(90), xa, eff, eff * (xa - mx)[:, None]])
jmp = sm.OLS(ya, X).fit()
est = {r['term']: r for r in models.estimates(d, res)['rows']}
check.near('the intercept at x = 0, as JMP reports it', est['Intercept']['estimate'], float(jmp.params[0]))
check.near('and its standard error', est['Intercept']['se'], float(jmp.bse[0]))
check.near('the slope of x', est['x']['estimate'], float(jmp.params[1]))
full = sm.OLS(ya, X).fit()
red = sm.OLS(ya, X[:, :4]).fit()
f_ref = ((red.ssr - full.ssr) / 2) / (full.ssr / full.df_resid)
check.near('the F test of the crossing', et['x*g']['stat'], float(f_ref))
code = models.code_formula(d)
shown = smf.ols(code, pd.DataFrame({'x': xa, 'g': ga, 'y': ya})).fit()
slope = [k for k in shown.params.index if k.startswith('I(x') and ':' not in k][0]
check.near("the shown code's slope for x", float(shown.params[slope]), float(jmp.params[1]))
# a column named like a Python keyword is quoted in the shown code
tid = table({'yield': ya.tolist(), 'class': ga.tolist()})
d = models.build(tid, 'yield', [['class']], intercept=False)
f = models.code_formula(d)
check('keyword names are quoted, no intercept kept', f, 'Q("yield") ~ C(Q("class"), Sum, levels=[\'a\', \'b\', \'c\']) - 1')
smf.ols(f, pd.DataFrame({'yield': ya, 'class': ga})).fit()
# Freq: the error degrees of freedom are the sum of the frequencies less the rank
fq = np.tile([1.0, 2.0, 3.0], 30)
tid = table({'x': xa.tolist(), 'y': ya.tolist(), 'f': fq.tolist()})
d = models.build(tid, 'y', [['x']], freq='f')
res = models.fit_ols(d, freq_total=float(fq.sum()))
check('Freq sets the error degrees of freedom', float(res.df_resid), float(fq.sum()) - 2)
dg = models.diagnostics(d, res)
check('diagnostics for a weighted fit', len(dg['hat']) == 90 and np.all(np.isfinite(dg['externally'])), True)
sys.exit(check.done())
