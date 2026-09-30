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

# ---- saved columns: every row's design (new_rows) and the prediction formula (formula_linear) ----------
# The formula text is run by the page's own formula language (smui-util.js, smui-table.js and smui-formula.js
# in node, as test-formula.js loads them) on the table's columns; it must give, at every row whose columns have
# values, what statsmodels predicts there from the shown code's formula (another route: patsy on the real names).
FORMULA_JS = r'''
const fs = require('fs'); const path = require('path'); const vm = require('vm');
const sb = { console }; sb.self = sb; vm.createContext(sb);
for (const f of ['smui-util.js', 'smui-table.js', 'smui-formula.js']) vm.runInContext(fs.readFileSync(path.join(process.argv[2], f), 'utf8'), sb, { filename: f });
const inp = JSON.parse(fs.readFileSync(0, 'utf8'));
const t = new sb.SM.Table({ name: 'T', columns: inp.columns.map((c) => ({ name: c.name, dataType: c.dataType, values: c.values.map((v) => (v === null && c.dataType === 'numeric' ? NaN : v)) })) });
const out = [];
for (const f of inp.formulas) { try { out.push({ values: Array.from(sb.SM.formula.evaluate(t, f)).map((x) => (typeof x === 'number' && !Number.isFinite(x) ? null : x)) }); } catch (e) { out.push({ error: String(e.message || e) }); } }
process.stdout.write(JSON.stringify(out));
'''
import json as _json
import os
import shutil
import subprocess
import tempfile

JS_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'js'))
NODE = shutil.which('node')
_drv = os.path.join(tempfile.mkdtemp(prefix='smui-formula-'), 'eval.js')
with open(_drv, 'w') as _f:
    _f.write(FORMULA_JS)


def formula_values(columns, formulas):
    """Formula texts evaluated on a table {name: values} (a list of strings is a character column) by the page's formula language."""
    cols = [{'name': k, 'dataType': 'character' if any(isinstance(v, str) for v in vals) else 'numeric',
             'values': [None if (v is None or (isinstance(v, float) and np.isnan(v))) else v for v in vals]} for k, vals in columns.items()]
    out = _json.loads(subprocess.run([NODE, _drv, JS_DIR], input=_json.dumps({'columns': cols, 'formulas': formulas}), capture_output=True, text=True, check=True).stdout)
    return [np.array([np.nan if v is None else v for v in o['values']], dtype=float) if 'values' in o else o['error'] for o in out]


if NODE:
    rng = np.random.default_rng(29)
    n = 90
    a_ = rng.choice(['p', 'q', 'r'], n)
    b_ = rng.choice(['u', 'v', 'w'], n)
    dose = rng.choice([1.0, 2.0, 4.0], n)                    # a numeric column, nominal
    x_ = rng.normal(5, 2, n)
    z_ = rng.normal(0, 1, n)
    y_ = 1 + (a_ == 'q') * 2 + 0.5 * x_ + 0.3 * x_ * (a_ == 'r') - 0.4 * (dose == 4) + 0.2 * z_ * x_ + rng.normal(0, 1, n)
    y_[[3, 11]] = np.nan                                     # rows without a response: predicted all the same
    x_[5] = np.nan                                           # a row without x: no prediction
    a_[7] = 's'                                              # a level the fit does not see: no prediction
    cols = {'a (group)': a_.tolist(), 'b': b_.tolist(), 'dose': dose.tolist(), 'light "x"': x_.tolist(), 'z': z_.tolist(), 'y': y_.tolist()}
    fit_rows = [r for r in range(n) if r not in (3, 5, 7, 11, 13)]     # row 13 left out as if excluded
    tid = table(cols, types={'dose': 'nominal'}, levels={'a (group)': ['p', 'q', 'r', 's']})
    for label, effects, intercept in (('crossings, a power, a nested effect', [['a (group)'], ['light "x"'], ['light "x"', 'light "x"'], ['a (group)', 'light "x"'], ['b', 'a (group)'], ['light "x"', 'z'], ['z'], ['dose']], True),
                                      ('no intercept, a numeric nominal column', [['dose'], ['light "x"'], ['dose', 'light "x"']], False),
                                      ('two nominal factors crossed', [['a (group)'], ['b'], ['a (group)', 'b']], True)):
        d = models.build(tid, 'y', effects, fit_rows, intercept=intercept)
        res = models.fit_ols(d)
        di = res.model.data.design_info
        idx, X, _ = models.new_rows(d, di, tid)
        frame = pd.DataFrame({k: v for k, v in cols.items()})
        frame['dose'] = frame['dose'].astype(float)
        shown = smf.ols(models.code_formula(d), frame.loc[fit_rows]).fit()
        uses_a = any('a (group)' in e for e in effects)
        uses_x = any('light "x"' in e for e in effects)
        want_rows = [r for r in range(n) if (np.isfinite(x_[r]) or not uses_x) and (a_[r] != 's' or not uses_a)]
        check(f'every row with values is a new row ({label})', idx.tolist(), want_rows)
        check.near(f'the new rows\' prediction = statsmodels\' predict from the shown formula ({label})',
                   float(np.max(np.abs(X @ res.params.to_numpy() - shown.predict(frame.loc[want_rows]).to_numpy()))), 0.0, abs_=1e-9)
        txt = models.formula_linear(d, di, res.params.to_numpy(), tid)
        fv = formula_values(cols, [txt])[0]
        check.near(f'the formula column = the prediction at every such row ({label})', float(np.max(np.abs(fv[idx] - X @ res.params.to_numpy()))), 0.0, abs_=1e-9)
        check(f'the formula is missing where a column is, or the level unseen ({label})', bool(np.isnan(fv[5]) == uses_x and np.isnan(fv[7]) == uses_a), True)
        check(f'rows without a response get their prediction too ({label})', bool(np.isfinite(fv[3]) and np.isfinite(fv[11])), True)
        check(f'Match codes the nominal levels ({label})', 'Match(' in txt, True)
    # the centred crossings as the design has them; the effect coding folded into one Match per term
    d = models.build(tid, 'y', [['a (group)'], ['light "x"'], ['a (group)', 'light "x"']], fit_rows)
    txt = models.formula_linear(d, models.fit_ols(d).model.data.design_info, models.fit_ols(d).params.to_numpy(), tid)
    m_ = d.means[d.alias['light "x"']]
    check('a crossing with a continuous column: (x − mean) times a Match of the levels', 'Match(:"a (group)", "p", ' in txt and f'(:"light \\"x\\"" - {m_!r})' in txt, True)
    import re as _re
    bs = models.fit_ols(d).params
    al = d.alias['a (group)']
    b_p, b_q = float(bs[f'C({al}, Sum)[S.p]']), float(bs[f'C({al}, Sum)[S.q]'])
    mt = _re.search(r'Match\(:"a \(group\)", "p", ([^,]+), "q", ([^,]+), "r", ([^,]+), \.\)', txt)
    check('the main effect: one Match, its levels\' effects in the table\'s order', mt is not None, True)
    if mt:
        check.near('the first levels: their coefficients', abs(float(mt.group(1)) - b_p) + abs(float(mt.group(2)) - b_q), 0.0, abs_=1e-15)
        check.near('the last level: minus the sum of the others (effect coding)', float(mt.group(3)), -(b_p + b_q), rel=1e-14)
    # a By group: the rows of its level only, the formula wrapped in If
    by = rng.choice(['one', 'two'], n)
    cols_by = dict(cols, grp=by.tolist())
    tid2 = table(cols_by, levels={'a (group)': ['p', 'q', 'r', 's']})
    rows_one = [r for r in fit_rows if by[r] == 'one']
    d = models.build(tid2, 'y', [['a (group)'], ['light "x"']], rows_one)
    res = models.fit_ols(d)
    where = [{'column': 'grp', 'value': 'one'}]
    idx, X, _ = models.new_rows(d, res.model.data.design_info, tid2, where)
    check('By: the new rows are the group\'s', set(idx.tolist()) == {r for r in range(n) if by[r] == 'one' and np.isfinite(x_[r]) and a_[r] != 's'}, True)
    txt = models.formula_where(tid2, where, models.formula_linear(d, res.model.data.design_info, res.params.to_numpy(), tid2))
    fv = formula_values(cols_by, [txt])[0]
    check('By: the formula holds for the group\'s rows only', bool(np.all(np.isnan(fv[by == 'two'])) and np.all(np.isfinite(fv[idx]))), True)
    check.near('By: and there it is the prediction', float(np.max(np.abs(fv[idx] - X @ res.params.to_numpy()))), 0.0, abs_=1e-9)
    # levels and names that need escaping
    lv_odd = np.array(['say "hi"', 'back\\slash', 'plain'])[rng.integers(0, 3, n)]
    cols_odd = {'lev': lv_odd.tolist(), 'x': x_.tolist(), 'y': y_.tolist()}
    tid3 = table(cols_odd)
    d = models.build(tid3, 'y', [['lev'], ['x']], fit_rows)
    res = models.fit_ols(d)
    idx, X, _ = models.new_rows(d, res.model.data.design_info, tid3)
    fv = formula_values(cols_odd, [models.formula_linear(d, res.model.data.design_info, res.params.to_numpy(), tid3)])[0]
    check.near('quotes and backslashes in levels: the formula still predicts', float(np.max(np.abs(fv[idx] - X @ res.params.to_numpy()))), 0.0, abs_=1e-9)
    # the logistic formulas: Prob[level] and Most Likely from the linear predictors, as JMP writes them
    lin = ['0.5 + 1.5 * :x', '-1 + 0.25 * :x']
    xs = rng.normal(0, 1, 12)
    for mode, lins, cuts, target in (('binary', lin[:1], None, 1), ('multinomial', lin, None, 0), ('ordinal', ['0.8 * :x'], [-0.5, 0.7], 0)):
        labels = ['lo', 'mid', 'hi'] if mode != 'binary' else ['no', 'yes']
        F = models.probability_formulas(mode, labels, lins, 'y', target=target, cuts=cuts)
        cols_l = {'x': xs.tolist()}
        vals = {}
        for f in F:
            e = f['expr'] if isinstance(f['expr'], str) else ''.join(s_ if isinstance(s_, str) else ':"' + F[s_['ref']]['name'] + '"' for s_ in f['expr'])
            if f.get('character'):
                out = _json.loads(subprocess.run([NODE, _drv, JS_DIR], input=_json.dumps({'columns': [{'name': k, 'dataType': 'numeric', 'values': v} for k, v in cols_l.items()], 'formulas': [e]}), capture_output=True, text=True, check=True).stdout)[0]
                vals[f['name']] = out.get('values')
            else:
                vals[f['name']] = formula_values(cols_l, [e])[0]
                cols_l[f['name']] = vals[f['name']].tolist()
        if mode == 'binary':
            p_yes = 1 / (1 + np.exp(-(0.5 + 1.5 * xs)))
            P = np.column_stack([1 - p_yes, p_yes])
        elif mode == 'multinomial':
            e1, e2 = np.exp(0.5 + 1.5 * xs), np.exp(-1 + 0.25 * xs)
            P = np.column_stack([e1, e2, np.ones(12)]) / (1 + e1 + e2)[:, None]
        else:
            c1, c2 = 1 / (1 + np.exp(-(-0.5 + 0.8 * xs))), 1 / (1 + np.exp(-(0.7 + 0.8 * xs)))
            P = np.column_stack([c1, c2 - c1, 1 - c2])
        got = np.column_stack([vals[f'Prob[{lv_}]'] for lv_ in labels])
        check.near(f'{mode}: Prob[level] formulas = the model\'s probabilities', float(np.max(np.abs(got - P))), 0.0, abs_=1e-12)
        check(f'{mode}: Most Likely is the level of largest probability', vals['Most Likely y'] == [labels[i] for i in np.argmax(P, axis=1)], True)
        check(f'{mode}: JMP\'s column names', [f['name'] for f in F][:len(F) - len(labels) - 1],
              {'binary': ['Lin[yes]'], 'multinomial': ['Lin[lo]', 'Lin[mid]'], 'ordinal': ['Linear', 'Cum[lo]', 'Cum[mid]']}[mode])
else:
    print('(node is not installed: the formula checks are skipped)')
sys.exit(check.done())
