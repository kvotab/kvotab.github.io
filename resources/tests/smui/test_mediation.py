#!/usr/bin/env python3
"""Analyze > Specialized Modeling > Mediation's backend
(resources/py/smui/mediation.py), checked

  * against statsmodels' Mediation called directly on its formula path (the
    documented way, which builds both designs with patsy for every
    simulation) with the same seed: the report's effects, intervals and
    p-values to the last digit, for the parametric and the bootstrap
    method, with and without the treatment x mediator interaction, with a
    categorical covariate, a binary outcome (logit and probit), a binary
    mediator, a count mediator (Poisson) and a continuous treatment;
  * against the definitions: every line of the Mediation Effects table from
    the simulated draws the report returns (the mean, the percentiles, twice
    the share on the far side of zero, the median of ACME/total); the
    mediator and outcome models against statsmodels' OLS and GLM fits;
  * against known truth: the page's example table (simulated with the
    page's own seeded generator, ported here and checked against it by
    test-ui-mediation.py) has an indirect effect of 6 and a direct effect of
    2; the estimates are near them, and for linear models without the
    interaction ACME is the product a x b of the models' coefficients and
    ADE the coefficient c';
  * that the Python shown under the report runs on the table exported as
    CSV and gives the report's numbers.

It also shows why the page uses the GLM families for binary and count
mediators: statsmodels 0.14.6's Mediation cannot take a discrete Logit,
Probit or Poisson mediator model (a TypeError).

    python3 resources/tests/smui/test_mediation.py
"""
import contextlib
import io
import math
import os
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from statsmodels.stats.mediation import Mediation

from backend import FAILED, Checks, call, table

check = Checks()
check('mediation.py imports', FAILED.get('mediation'), None)
if 'mediation' in FAILED:
    sys.exit(check.done())

M32 = 0xffffffff


# ---- the page's seeded generator (SM.util.rng in smui-util.js) and its example -------------------
class Rng:
    """sfc32 seeded from a string, and the Marsaglia polar normal with its
    spare, as SM.util.rng draws them."""

    def __init__(self, seed):
        s = str(seed)
        h = (1779033703 ^ len(s)) & M32
        for ch in s:
            h = ((h ^ ord(ch)) * 3432918353) & M32
            h = ((h << 13) & M32) | (h >> 19)
        self.h = h
        self.a, self.b, self.c, self.d = (self._next() for _ in range(4))
        self.spare = None

    def _next(self):
        h = self.h
        h = ((h ^ (h >> 16)) * 2246822507) & M32
        h = ((h ^ (h >> 13)) * 3266489909) & M32
        h ^= h >> 16
        self.h = h
        return h

    def u(self):
        a, b, c, d = self.a, self.b, self.c, self.d
        t = (a + b) & M32
        a = b ^ (b >> 9)
        b = (c + ((c << 3) & M32)) & M32
        c = ((c << 21) & M32) | (c >> 11)
        d = (d + 1) & M32
        t = (t + d) & M32
        c = (c + t) & M32
        self.a, self.b, self.c, self.d = a, b, c, d
        return t / 4294967296

    def normal(self, mu=0.0, sd=1.0):
        if self.spare is not None:
            z, self.spare = self.spare, None
            return mu + sd * z
        while True:
            x, y = 2 * self.u() - 1, 2 * self.u() - 1
            r = x * x + y * y
            if 0 < r < 1:
                break
        f = math.sqrt(-2 * math.log(r) / r)
        self.spare = y * f
        return mu + sd * x * f


def fixed(x, d):
    """+x.toFixed(d): the exact binary value rounded half up."""
    return float(Decimal(x).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


def jround(x):
    return math.floor(x + 0.5)


def make_coaching():
    """File > Examples > Coaching study (smui-p-mediation.js), row for row,
    with the sample's true effects from both potential outcomes of each
    person."""
    r = Rng('mediation-coaching')
    n = 600
    arms = [0] * (n // 2) + [1] * (n // 2)
    for i in range(n - 1, 0, -1):
        j = math.floor(r.u() * (i + 1))
        arms[i], arms[j] = arms[j], arms[i]
    c = {k: [] for k in ('id', 'age', 'sex', 'baseline', 'program', 'confidence', 'score', 'passed')}
    acme, ade, pacme, pade = [0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]
    for i in range(n):
        age = max(20, min(65, jround(r.normal(38, 9))))
        sex = 'F' if r.u() < 0.5 else 'M'
        base = fixed(r.normal(50, 10), 1)
        t = arms[i]
        em, ey = r.normal(0, 3), r.normal(0, 5)
        mu = 20 + 0.3 * (base - 50) + 0.05 * (age - 38) + (1.0 if sex == 'F' else 0.0) + em
        m = [fixed(mu, 1), fixed(mu + 4, 1)]

        def y(tt, mm):
            return fixed(30 + 1.5 * mm + 2 * tt + 0.4 * (base - 50) - 0.1 * (age - 38) + ey, 1)
        for k in (0, 1):
            acme[k] += y(k, m[1]) - y(k, m[0])
            ade[k] += y(1, m[k]) - y(0, m[k])
            pacme[k] += (y(k, m[1]) >= 70) - (y(k, m[0]) >= 70)
            pade[k] += (y(1, m[k]) >= 70) - (y(0, m[k]) >= 70)
        c['id'].append(f'P{i + 1:03d}')
        c['age'].append(age)
        c['sex'].append(sex)
        c['baseline'].append(base)
        c['program'].append('coaching' if t else 'control')
        c['confidence'].append(m[t])
        c['score'].append(y(t, m[t]))
        c['passed'].append('yes' if y(t, m[t]) >= 70 else 'no')
    truth = {'acme': [a / n for a in acme], 'ade': [a / n for a in ade], 'acme_passed': [a / n for a in pacme], 'ade_passed': [a / n for a in pade]}
    return c, truth


EX, TRUTH = make_coaching()
df = pd.DataFrame(EX)
LEVELS = {'program': ['control', 'coaching'], 'passed': ['no', 'yes'], 'sex': ['F', 'M']}
tid = table({k: v for k, v in EX.items()}, levels=LEVELS)
check('the example: 600 people, 300 coached', (len(df), int((df['program'] == 'coaching').sum())), (600, 300))
check.near('its true indirect effect (control) is 6', TRUTH['acme'][0], 6.0, abs_=0.02)
check.near('its true indirect effect (treated) is 6', TRUTH['acme'][1], 6.0, abs_=0.02)
check.near('its true direct effect is 2', TRUTH['ade'][0], 2.0, abs_=1e-9)

tmp = tempfile.mkdtemp(prefix='smui-mediation-')


def run_code(code, frame, name):
    frame.to_csv(os.path.join(tmp, f'{name}.csv'), index=False)
    ns = {}
    here = os.getcwd()
    os.chdir(tmp)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(code, name, 'exec'), ns)
        return ns, None
    except Exception as ex_:
        return ns, f'{type(ex_).__name__}: {ex_}'
    finally:
        os.chdir(here)


def effects(res):
    return {r['effect']: r for r in res['effects']['rows']}


SM_NAMES = {'ACME (control)': 'ACME (control)', 'ACME (treated)': 'ACME (treated)', 'ACME (average)': 'ACME (average)',
            'ADE (control)': 'ADE (control)', 'ADE (treated)': 'ADE (treated)', 'ADE (average)': 'ADE (average)', 'Total Effect': 'Total effect',
            'Prop. Mediated (control)': 'Prop. mediated (control)', 'Prop. Mediated (treated)': 'Prop. mediated (treated)',
            'Prop. Mediated (average)': 'Prop. mediated (average)'}


def same_as(label, res, smry, rel=1e-10):
    """Every number of the report's effects table against statsmodels' own summary()."""
    e = effects(res)
    worst = 0.0
    for mine, theirs in SM_NAMES.items():
        for k, col_ in (('estimate', 'Estimate'), ('lower', 'Lower CI bound'), ('upper', 'Upper CI bound'), ('p', 'P-value')):
            a, b = e[mine][k], float(smry.loc[theirs, col_])
            worst = max(worst, abs(a - b) / max(1.0, abs(b)))
    check.near(f'{label}: every estimate, bound and p-value is statsmodels\' (largest relative gap)', worst, 0.0, abs_=rel)


# ---- the continuous outcome and mediator, against statsmodels' formula path ----------------------------
d = df.copy()
d['treat'] = (d['program'] == 'coaching').astype(float)
d['med'] = d['confidence']
F_OUT = "score ~ treat + med + age + baseline + C(sex, Sum, levels=['F', 'M'])"
F_MED = "med ~ treat + age + baseline + C(sex, Sum, levels=['F', 'M'])"
base = dict(table=tid, y='score', treatment='program', mediator='confidence', covariates=['age', 'baseline', 'sex'])

out = io.StringIO()
with contextlib.redirect_stdout(out):
    r = call('mediation.fit', **base, n_rep=300, seed=11)
check('fit: no error', r.get('error'), None)
lines = [ln for ln in out.getvalue().splitlines() if ln.startswith('smui:progress mediation')]
check('it reports its progress: ten lines, the last all the simulations', (len(lines), lines[-1] if lines else None), (10, 'smui:progress mediation 300 300'))
check('the rows: all 600 complete', (r['n'], r['n_missing'], r['n_treated'], r['n_control']), (600, 0, 300, 300))
check('the treatment: coaching (treated) against control', (r['t_kind'], r['control'], r['treated'], r['t_label']), ('categorical', 'control', 'coaching', 'program[coaching]'))
check('the models: least squares, as the columns are continuous', (r['outcome_model'], r['mediator_model']), ('ols', 'ols'))
np.random.seed(11)
ref = Mediation(smf.ols(F_OUT, d), smf.ols(F_MED, d), 'treat', 'med').fit(method='parametric', n_rep=300)
same_as('parametric, 300 simulations', r, ref.summary())
check.near('the draws are statsmodels\': ACME (control)', float(np.max(np.abs(np.array(r['draws']['acme_ctrl']) - ref.ACME_ctrl))), 0.0, abs_=1e-10)
check.near('the draws are statsmodels\': ADE (treated)', float(np.max(np.abs(np.array(r['draws']['ade_tx']) - ref.ADE_tx))), 0.0, abs_=1e-10)

# every line of the table from the draws, by the definitions
a0, a1 = np.array(r['draws']['acme_ctrl']), np.array(r['draws']['acme_tx'])
z0, z1 = np.array(r['draws']['ade_ctrl']), np.array(r['draws']['ade_tx'])
tot = (a0 + a1 + z0 + z1) / 2
vecs = {'ACME (control)': a0, 'ACME (treated)': a1, 'ACME (average)': (a0 + a1) / 2, 'ADE (control)': z0, 'ADE (treated)': z1,
        'ADE (average)': (z0 + z1) / 2, 'Total Effect': tot, 'Prop. Mediated (control)': a0 / tot, 'Prop. Mediated (treated)': a1 / tot,
        'Prop. Mediated (average)': (a0 / tot + a1 / tot) / 2}
e = effects(r)
for name, v in vecs.items():
    est = np.median(v) if name.startswith('Prop') else v.mean()
    check.near(f'{name}: the {"median" if name.startswith("Prop") else "mean"} of the draws', e[name]['estimate'], float(est), rel=1e-12)
    check.near(f'{name}: the lower bound is the 2.5th percentile', e[name]['lower'], float(np.percentile(v, 2.5)), rel=1e-12)
    check.near(f'{name}: the upper bound is the 97.5th percentile', e[name]['upper'], float(np.percentile(v, 97.5)), rel=1e-12)
    check.near(f'{name}: p is twice the share on the far side of zero', e[name]['p'], 2 * min(np.sum(v > 0), np.sum(v < 0)) / len(v), abs_=1e-15)

# known truth, and the product of coefficients
for name, truth_ in (('ACME (average)', 6.0), ('ADE (average)', 2.0), ('Total Effect', 8.0), ('Prop. Mediated (average)', 0.75)):
    check(f'{name}: its interval covers the truth, {truth_}', e[name]['lower'] < truth_ < e[name]['upper'], True)
check('ACME is well away from zero (p below 1/150)', e['ACME (average)']['p'] < 1 / 150, True)
ols_o, ols_m = smf.ols(F_OUT, d).fit(), smf.ols(F_MED, d).fit()
ab = ols_m.params['treat'] * ols_o.params['med']
sd_a = float(np.std(a0))
check.near('the path a: the mediator model\'s coefficient of the treatment', r['paths']['a']['estimate'], float(ols_m.params['treat']), rel=1e-10)
check.near('the path b: the outcome model\'s coefficient of the mediator', r['paths']['b']['estimate'], float(ols_o.params['med']), rel=1e-10)
check.near('the path c\': the outcome model\'s coefficient of the treatment', r['paths']['c']['estimate'], float(ols_o.params['treat']), rel=1e-10)
check.near('linear models: a x b as the report gives it', r['product']['ab'], float(ab), rel=1e-10)
check('linear models: ACME is a x b, within four Monte Carlo errors', abs(e['ACME (average)']['estimate'] - ab) < 4 * sd_a / math.sqrt(300), True)
check('linear models: ADE is c\', within four Monte Carlo errors', abs(e['ADE (average)']['estimate'] - ols_o.params['treat']) < 4 * float(np.std(z0)) / math.sqrt(300), True)
check.near('the truth by the page\'s numbers: a is 4 in the model the data came from (within 3 SE)', (r['paths']['a']['estimate'] - 4) / r['paths']['a']['se'], 0.0, abs_=3)
check.near('and b is 1.5 (within 3 SE)', (r['paths']['b']['estimate'] - 1.5) / r['paths']['b']['se'], 0.0, abs_=3)

# the model tables against statsmodels' fits, with JMP's names in the order of the roles
mo = {x['term']: x for x in r['models']['outcome']['estimates']['rows']}
mm_ = {x['term']: x for x in r['models']['mediator']['estimates']['rows']}
check('outcome model terms, in the order of the roles', [x['term'] for x in r['models']['outcome']['estimates']['rows']],
      ['Intercept', 'program[coaching]', 'confidence', 'age', 'baseline', 'sex[F]'])
check('mediator model terms', [x['term'] for x in r['models']['mediator']['estimates']['rows']], ['Intercept', 'program[coaching]', 'age', 'baseline', 'sex[F]'])
names_o = {'Intercept': 'Intercept', 'program[coaching]': 'treat', 'confidence': 'med', 'age': 'age', 'baseline': 'baseline', 'sex[F]': "C(sex, Sum, levels=['F', 'M'])[S.F]"}
for term, nm in names_o.items():
    check.near(f'outcome model {term}: estimate', mo[term]['estimate'], float(ols_o.params[nm]), rel=1e-10)
    check.near(f'outcome model {term}: std error', mo[term]['se'], float(ols_o.bse[nm]), rel=1e-10)
    check.near(f'outcome model {term}: p-value (t)', mo[term]['p'], float(ols_o.pvalues[nm]), rel=1e-8, abs_=1e-300)
check.near('mediator model sex[F] (effect coded: half the F - M difference)', mm_['sex[F]']['estimate'], float(ols_m.params["C(sex, Sum, levels=['F', 'M'])[S.F]"]), rel=1e-10)
check('the outcome model reports t ratios (least squares)', [c_['label'] for c_ in r['models']['outcome']['estimates']['columns']][3:5], ['t Ratio', 'Prob>|t|'])
summ = dict((k, v) for k, v, _f in r['models']['outcome']['summary'])
check.near('outcome model RSquare', summ['RSquare'], float(ols_o.rsquared), rel=1e-12)

# the cache, and another alpha from the same draws
r2 = call('mediation.fit', **base, n_rep=300, seed=11)
check('the same call again comes from the cache', (r2['cached'], effects(r2)['ACME (average)']['estimate']), (True, e['ACME (average)']['estimate']))
r3 = call('mediation.fit', **base, n_rep=300, seed=11, alpha=0.1)
check('another alpha: from the cache too', r3['cached'], True)
check.near('alpha 0.1: the 5th percentile of the same draws', effects(r3)['ACME (average)']['lower'], float(np.percentile((a0 + a1) / 2, 5)), rel=1e-12)
check('the columns say 90%', [c_['label'] for c_ in r3['effects']['columns']][2:4], ['Lower 90%', 'Upper 90%'])
r4 = call('mediation.fit', **base, n_rep=300, seed=12)
check('another seed: simulated again, other numbers', (r4['cached'], effects(r4)['ACME (average)']['estimate'] != e['ACME (average)']['estimate']), (False, True))

# ---- the interaction, and the bootstrap, against the formula path ---------------------------------------------
ri = call('mediation.fit', **base, n_rep=200, seed=5, interaction=True)
check('interaction: no error', ri.get('error'), None)
np.random.seed(5)
refi = Mediation(smf.ols(F_OUT.replace('treat + med', 'treat + med + treat:med'), d), smf.ols(F_MED, d), 'treat', 'med').fit(n_rep=200)
same_as('with the interaction treat:med (the formula path rebuilds it, the page sets it)', ri, refi.summary())
check('its term is named as JMP names a crossing', [x['term'] for x in ri['models']['outcome']['estimates']['rows']][:4],
      ['Intercept', 'program[coaching]', 'confidence', 'program[coaching]*confidence'])
check('its path i is the interaction\'s coefficient', ri['paths']['i'] is not None and abs(ri['paths']['i']['estimate'] - smf.ols(F_OUT.replace('treat + med', 'treat + med + treat:med'), d).fit().params['treat:med']) < 1e-10, True)
check('the interaction\'s note', any('interaction' in n for n in ri['notes']), True)
check('no product a x b with the interaction', 'product' in ri, False)

rb = call('mediation.fit', **base, n_rep=150, seed=9, method='bootstrap')
np.random.seed(9)
refb = Mediation(smf.ols(F_OUT, d), smf.ols(F_MED, d), 'treat', 'med').fit(method='bootstrap', n_rep=150)
same_as('bootstrap, 150 resamples', rb, refb.summary())
rbi = call('mediation.fit', **base, n_rep=100, seed=9, method='bootstrap', interaction=True)
np.random.seed(9)
refbi = Mediation(smf.ols(F_OUT.replace('treat + med', 'treat + med + treat:med'), d), smf.ols(F_MED, d), 'treat', 'med').fit(method='bootstrap', n_rep=100)
same_as('bootstrap with the interaction', rbi, refbi.summary())
check('bootstrap: the intervals still cover the truth (ACME 6)', effects(rb)['ACME (average)']['lower'] < 6 < effects(rb)['ACME (average)']['upper'], True)

# ---- a binary outcome: logit and probit (GLM binomial), effects on the probability scale ------------------------------
db = d.copy()
db['passed'] = (db['passed'] == 'yes').astype(float)
F_OB = F_OUT.replace('score ~', 'passed ~')
for link, fam in (('logit', sm.families.Binomial()), ('probit', sm.families.Binomial(link=sm.families.links.Probit()))):
    rl = call('mediation.fit', **{**base, 'y': 'passed'}, n_rep=200, seed=3, outcome_model=link)
    check(f'binary outcome, {link}: no error', rl.get('error'), None)
    check(f'binary outcome, {link}: the model follows the column (logit by default) or the choice', rl['outcome_model'], link)
    np.random.seed(3)
    refl = Mediation(smf.glm(F_OB, db, family=fam), smf.ols(F_MED, d), 'treat', 'med').fit(n_rep=200)
    same_as(f'binary outcome, {link}', rl, refl.summary())
    check(f'binary outcome, {link}: the note says the effects are on the probability scale', any('probability' in n for n in rl['notes']), True)
    ee = effects(rl)
    truth_p = sum(TRUTH['acme_passed']) / 2
    check(f'binary outcome, {link}: ACME (average) covers the sample\'s true {truth_p:.3f}', ee['ACME (average)']['lower'] < truth_p < ee['ACME (average)']['upper'], True)
    check(f'binary outcome, {link}: z tests in its table', [c_['label'] for c_ in rl['models']['outcome']['estimates']['columns']][3], 'z Ratio')
    gl = smf.glm(F_OB, db, family=fam).fit()
    check.near(f'binary outcome, {link}: the coefficient of the mediator is the GLM\'s', rl['paths']['b']['estimate'], float(gl.params['med']), rel=1e-9)
check('the default for a two-level outcome is logistic', call('mediation.fit', **{**base, 'y': 'passed'}, n_rep=50, seed=1)['outcome_model'], 'logit')
check('its outcome term is named by the level that is 1', call('mediation.fit', **{**base, 'y': 'passed'}, n_rep=50, seed=1)['models']['outcome']['response'], 'passed[yes]')

# ---- a binary mediator (GLM binomial), and why not statsmodels' Logit ----------------------------------------------------
rng = np.random.default_rng(4)
n = 500
x = rng.normal(size=n)
tt = rng.integers(0, 2, n)
mb = (rng.uniform(size=n) < 1 / (1 + np.exp(-(-0.4 + 1.2 * tt + 0.5 * x)))).astype(int)
yb = 1.0 + 2.0 * mb + 0.5 * tt + 0.7 * x + rng.normal(0, 1, n)
cnt = rng.poisson(np.exp(0.3 + 0.6 * tt + 0.2 * x))
y2 = 1.0 + 0.4 * cnt + 0.5 * tt + 0.7 * x + rng.normal(0, 1, n)
frame2 = pd.DataFrame({'y': yb, 'treated': tt.astype(float), 'm': np.where(mb == 1, 'high', 'low'), 'x': x, 'count': cnt.astype(float), 'y2': y2})
tid2 = table({k: frame2[k].tolist() for k in frame2.columns}, types={'treated': 'nominal'}, levels={'m': ['low', 'high']})
rm = call('mediation.fit', table=tid2, y='y', treatment='treated', mediator='m', covariates=['x'], n_rep=200, seed=8)
check('binary mediator: no error, logistic by default', (rm.get('error'), rm.get('mediator_model')), (None, 'logit'))
d2 = frame2.copy()
d2['treat'] = (d2['treated'] == 1).astype(float)
d2['med'] = (d2['m'] == 'high').astype(float)
np.random.seed(8)
refm = Mediation(smf.ols('y ~ treat + med + x', d2), smf.glm('med ~ treat + x', d2, family=sm.families.Binomial()), 'treat', 'med').fit(n_rep=200)
same_as('binary mediator (GLM binomial)', rm, refm.summary())
check('binary mediator: its note', any('binary' in n_ and 'm = high' in n_ for n_ in rm['notes']), True)
true_acme = 2.0 * np.mean(1 / (1 + np.exp(-(-0.4 + 1.2 + 0.5 * x))) - 1 / (1 + np.exp(-(-0.4 + 0.5 * x))))
check(f'binary mediator: ACME covers the true 2 x the change in P(m = high), {true_acme:.3f}', effects(rm)['ACME (average)']['lower'] < true_acme < effects(rm)['ACME (average)']['upper'], True)
try:
    np.random.seed(8)
    Mediation(smf.ols('y ~ treat + med + x', d2), smf.logit('med ~ treat + x', d2), 'treat', 'med',
              mediator_fit_kwargs={'disp': 0}).fit(n_rep=20)
    got = 'no error'
except TypeError as ex:
    got = str(ex)
check('statsmodels 0.14.6: a discrete Logit mediator fails (so the page uses the GLM family)', 'scale' in got, True)

rp = call('mediation.fit', table=tid2, y='y2', treatment='treated', mediator='count', covariates=['x'], mediator_model='poisson', n_rep=200, seed=2)
check('count mediator (Poisson): no error', rp.get('error'), None)
d2['med'] = d2['count']
np.random.seed(2)
refp = Mediation(smf.ols('y2 ~ treat + med + x', d2), smf.glm('med ~ treat + x', d2, family=sm.families.Poisson()), 'treat', 'med').fit(n_rep=200)
same_as('count mediator (GLM Poisson)', rp, refp.summary())
true_p = 0.4 * np.mean(np.exp(0.3 + 0.6 + 0.2 * x) - np.exp(0.3 + 0.2 * x))
check(f'count mediator: ACME covers the true 0.4 x the change in the mean count, {true_p:.3f}', effects(rp)['ACME (average)']['lower'] < true_p < effects(rp)['ACME (average)']['upper'], True)

# ---- a continuous treatment: the contrast of two values ------------------------------------------------------------------------
rc = call('mediation.fit', **{**base, 'treatment': 'baseline', 'covariates': ['age', 'sex']}, n_rep=200, seed=4, control=45, treated=55)
check('continuous treatment: no error', rc.get('error'), None)
check('continuous treatment: the contrast', (rc['t_kind'], rc['control'], rc['treated'], rc['contrast'], rc['t_label']), ('continuous', 45, 55, 10.0, '(baseline-45)/10'))
dc = df.copy()
dc['treat'] = (dc['baseline'] - 45) / 10
dc['med'] = dc['confidence']
np.random.seed(4)
refc = Mediation(smf.ols("score ~ treat + med + age + C(sex, Sum, levels=['F', 'M'])", dc), smf.ols("med ~ treat + age + C(sex, Sum, levels=['F', 'M'])", dc), 'treat', 'med').fit(n_rep=200)
same_as('continuous treatment, 45 against 55', rc, refc.summary())
unit_o = smf.ols("score ~ baseline + confidence + age + C(sex, Sum, levels=['F', 'M'])", df).fit()
unit_m = smf.ols("confidence ~ baseline + age + C(sex, Sum, levels=['F', 'M'])", df).fit()
check.near('continuous treatment: a is the per-unit slope times the contrast (10)', rc['paths']['a']['estimate'], 10 * float(unit_m.params['baseline']), rel=1e-9)
check.near('and c\' likewise', rc['paths']['c']['estimate'], 10 * float(unit_o.params['baseline']), rel=1e-9)
check('its note names the two values', any('45' in n_ and '55' in n_ for n_ in rc['notes']), True)
rq = call('mediation.fit', **{**base, 'treatment': 'baseline', 'covariates': ['age', 'sex']}, n_rep=50, seed=4)
qs = np.quantile(df['baseline'], [0.25, 0.75], method='weibull')
check('continuous treatment without values: the quartiles (JMP\'s definition)', (rq['control'], rq['treated']), (float(qs[0]), float(qs[1])))

# ---- rows left out, missing values ---------------------------------------------------------------------------------
dm = df.copy()
dm.loc[[3, 17, 250], 'confidence'] = np.nan
dm.loc[[40], 'age'] = np.nan
tidm = table({k: [None if (isinstance(v, float) and math.isnan(v)) else v for v in dm[k].tolist()] for k in dm.columns}, levels=LEVELS)
sub = [i for i in range(600) if i % 7 != 0]
rs = call('mediation.fit', **{**base, 'table': tidm}, rows=sub, n_rep=100, seed=6, table_name='Coaching study')
kept = [i for i in sub if i not in (3, 17, 250, 40)]
check('rows: the report\'s rows, less those with a missing value', (rs['n'], rs['n_rows'], rs['n_missing']), (len(kept), len(sub), len(sub) - len(kept)))
ds = d.loc[kept]
np.random.seed(6)
refs = Mediation(smf.ols(F_OUT, ds), smf.ols(F_MED, ds), 'treat', 'med').fit(n_rep=100)
same_as('a subset of rows with missing values', rs, refs.summary())

# ---- the Python shown runs on the CSV export and gives the report's numbers -------------------------------------------------------------
for label, kw, frame, name in (
        ('continuous outcome', dict(base), df, 'Coaching study'),
        ('interaction, bootstrap', dict(base, interaction=True, method='bootstrap'), df, 'Coaching study'),
        ('binary outcome, probit', dict(base, y='passed', outcome_model='probit'), df, 'Coaching study'),
        ('continuous treatment', dict(base, treatment='baseline', covariates=['age', 'sex'], control=45, treated=55), df, 'Coaching study'),
        ('binary mediator, numeric 0/1 treatment', dict(table=tid2, y='y', treatment='treated', mediator='m', covariates=['x']), frame2, 'mediators'),
        ('count mediator', dict(table=tid2, y='y2', treatment='treated', mediator='count', covariates=['x'], mediator_model='poisson'), frame2, 'mediators'),
        ('rows and missing values', dict(base, table=tidm, rows=sub), dm, 'Coaching study (missing)')):
    rr = call('mediation.fit', **kw, n_rep=60, seed=21, table_name=name)
    ns, err = run_code(rr['code'], frame, name)
    check(f'code ({label}): runs', err, None)
    if err:
        print(rr['code'])
        continue
    same_as(f'code ({label}): its summary() is the report', rr, ns['med'].summary(alpha=0.05), rel=1e-10)

# ---- refusals said in words ---------------------------------------------------------------------------------------------------------
tid3 = table({'y': list(range(9)), 't': ['a', 'b', 'c'] * 3, 'm': [1.0, 2, 3, 1, 2, 5, 2, 2, 1]})
for label, kw, want in (
        ('three treatment levels', dict(table=tid3, y='y', treatment='t', mediator='m'), 'needs two'),
        ('the mediator is the outcome', dict(base, mediator='score'), 'three different'),
        ('a covariate is the treatment', dict(base, covariates=['program']), 'take it out of the covariates'),
        ('a Poisson mediator that is not a count', dict(base, mediator_model='poisson'), 'counts'),
        ('a logistic mediator that is not 0/1', dict(base, mediator_model='logit'), '0 or 1'),
        ('a categorical outcome as Poisson', dict(base, y='passed', outcome_model='poisson'), 'categorical'),
        ('too few simulations', dict(base, n_rep=5), 'between 20'),
        ('more than the page keeps', dict(base, n_rep=20000), 'million')):
    rr = call('mediation.fit', **kw)
    check(f'refused, {label}', want in (rr.get('error') or ''), True)
    if want not in (rr.get('error') or ''):
        print(rr.get('error'))

sys.exit(check.done())
