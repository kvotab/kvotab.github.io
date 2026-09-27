#!/usr/bin/env python3
"""Analyze > Screening > Multiple Imputation's backend
(resources/py/smui/mi.py), checked

  * against statsmodels called directly with the same seed: MICEData and
    MICE.fit (chained equations, predictive mean matching), BayesGaussMI
    and MI.fit (the multivariate normal), with and without an analysis
    model, a categorical predictor, a crossing, a binary response: the
    pooled estimates, standard errors, intervals and fractions of missing
    information, and the imputed values themselves;
  * against Rubin's rules written out here from the m fits: the within,
    between and total variances, statsmodels' fraction of missing
    information (1 + 1/m) B / T, the relative increase in variance, the
    Barnard-Rubin degrees of freedom and R mice's fraction of missing
    information;
  * against known truth: the page's example table (simulated with the
    page's own seeded generator, ported here) has true regression
    coefficients, and values missing at random with a probability that
    rises with the response; the complete-case fit is biased and the pooled
    fits are not, on the example and on average over simulated tables;
  * the missing-data summary against pandas, the complete-case fit against
    statsmodels' formula fit;
  * that the Python shown under the report runs on the table exported as
    CSV and gives the report's numbers.

It also shows why the page standardizes before BayesGaussMI: with
statsmodels 0.14.6's fixed priors a column in large units is imputed far
from its values.

    python3 resources/tests/smui/test_mi.py
"""
import contextlib
import io
import math
import os
import sys
import tempfile
import warnings
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats
from statsmodels.imputation.bayes_mi import MI, BayesGaussMI
from statsmodels.imputation.mice import MICE, MICEData

from backend import FAILED, Checks, call, table

check = Checks()
check('mi.py imports', FAILED.get('mi'), None)
if 'mi' in FAILED:
    sys.exit(check.done())

M32 = 0xffffffff


# ---- the page's seeded generator (SM.util.rng) and its example ---------------------------------------
class Rng:
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
    return float(Decimal(x).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


def jround(x):
    return math.floor(x + 0.5)


TRUE = {'Intercept': 60.0, 'age': 0.45, 'bmi': 1.1, 'cholesterol': 3.5, 'activity': -1.2}


def make_health(seed='incomplete-health-3'):
    """File > Examples > Health survey (smui-p-mi.js), row for row: the
    table as the page makes it, and the full data before the values went
    missing."""
    r = Rng(seed)
    full, obs = [], []

    def L(z):
        return 1 / (1 + math.exp(-z))
    for _ in range(400):
        age = 25 + math.floor(r.u() * 51)
        bmi = fixed(20 + 0.08 * age + r.normal(0, 3.2), 1)
        act = fixed(max(0.0, 7 - 0.06 * age - 0.12 * (bmi - 25) + r.normal(0, 2)), 1)
        chol = fixed(3.6 + 0.03 * age + 0.04 * (bmi - 25) + r.normal(0, 0.8), 2)
        sbp = jround(60 + 0.45 * age + 1.1 * bmi + 3.5 * chol - 1.2 * act + r.normal(0, 9))
        mb = r.u() < L(-1.0 + 0.12 * (sbp - 130))
        mc = r.u() < L(-1.0 + 0.12 * (sbp - 130))
        ma = r.u() < L(-1.3 + 0.03 * (age - 50) + 0.1 * (sbp - 130))
        full.append((age, bmi, act, chol, sbp))
        obs.append((age, np.nan if mb else bmi, np.nan if ma else act, np.nan if mc else chol, sbp))
    cols = ['age', 'bmi', 'activity', 'cholesterol', 'sbp']
    return pd.DataFrame(full, columns=cols, dtype=float), pd.DataFrame(obs, columns=cols, dtype=float)


def as_table(frame, **kw):
    return table({c: [None if (isinstance(v, float) and math.isnan(v)) else v for v in frame[c].tolist()] for c in frame.columns}, **kw)


FULL, D = make_health()
tid = as_table(D)
COLS = ['age', 'bmi', 'activity', 'cholesterol', 'sbp']
EFF = [['age'], ['bmi'], ['cholesterol'], ['activity']]
F = 'v4 ~ v0 + v1 + v3 + v2'
check('the example: 400 people, missing values in bmi, activity and cholesterol', (len(D), [int(D[c].isna().sum()) for c in COLS]), (400, [0, 102, 84, 82, 0]))
dd = D.copy()
dd.columns = [f'v{j}' for j in range(5)]

tmp = tempfile.mkdtemp(prefix='smui-mi-')


def run_code(code, frame, name):
    frame.to_csv(os.path.join(tmp, f'{name}.csv'), index=False)
    ns = {}
    here = os.getcwd()
    os.chdir(tmp)
    try:
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            exec(compile(code, name, 'exec'), ns)
        return ns, None
    except Exception as ex_:
        return ns, f'{type(ex_).__name__}: {ex_}'
    finally:
        os.chdir(here)


def rows_of(res, part='pooled'):
    return {x['term']: x for x in res['analysis'][part]['rows']}


def gap(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(np.max(np.abs(a - b) / np.maximum(1.0, np.abs(b))))


NAMES = ['Intercept', 'age', 'bmi', 'cholesterol', 'activity']
SM_ORDER = ['Intercept', 'v0', 'v1', 'v3', 'v2']   # the formula's order

# ---- MICE: the report against MICEData and MICE.fit --------------------------------------------------------------
out = io.StringIO()
with contextlib.redirect_stdout(out):
    r = call('mi.fit', table=tid, columns=COLS, response='sbp', effects=EFF, method='mice', seed=1)
check('MICE: no error', r.get('error'), None)
prog = [ln for ln in out.getvalue().splitlines() if ln.startswith('smui:progress mi')]
check('it reports its progress, ten lines to all 90 cycles', (len(prog), prog[-1] if prog else None), (10, 'smui:progress mi 90 90'))
check('the defaults are statsmodels\': 20 imputations, 10 cycles of burn-in, 3 skipped', (r['m'], r['burnin'], r['skip'], r['seed']), (20, 10, 3, 1))
np.random.seed(1)
imp = MICEData(dd)
mice = MICE(F, sm.OLS, imp, n_skip=3)
ref = mice.fit(n_burnin=10, n_imputations=20)
P = rows_of(r)
check.near('MICE: the pooled estimates are statsmodels\'', gap([P[n]['estimate'] for n in NAMES], ref.params), 0.0, abs_=1e-10)
check.near('MICE: the pooled standard errors', gap([P[n]['se'] for n in NAMES], ref.bse), 0.0, abs_=1e-10)
check.near('MICE: z and p', gap([P[n]['p'] for n in NAMES], ref.pvalues), 0.0, abs_=1e-10)
check.near('MICE: the intervals', gap([[P[n]['lower'], P[n]['upper']] for n in NAMES], ref.conf_int()), 0.0, abs_=1e-10)
check.near('MICE: the fractions of missing information', gap([P[n]['fmi'] for n in NAMES], ref.frac_miss_info), 0.0, abs_=1e-10)
check('statsmodels\' pooled tests are normal (z): use_t is False', bool(ref.use_t), False)
check.near('so p is 2 Φ(−|z|)', gap([P[n]['p'] for n in NAMES], 2 * stats.norm.sf(np.abs(ref.params / ref.bse))), 0.0, abs_=1e-12)

# Rubin's rules by their formulas, from statsmodels' own m fits
m = 20
Q = np.array([np.asarray(x.params) for x in mice.results_list])
U = np.array([np.diag(np.asarray(x.cov_params())) for x in mice.results_list])
W = U.mean(0)
B = Q.var(0, ddof=1)
T = W + (1 + 1 / m) * B
lam = (1 + 1 / m) * B / T
riv = (1 + 1 / m) * B / W
dfcom = 400 - 5
dfold = (m - 1) / lam ** 2
dfobs = (dfcom + 1) / (dfcom + 3) * dfcom * (1 - lam)
dfbr = dfold * dfobs / (dfold + dfobs)
check.near('Rubin: the estimate is the mean of the m estimates', gap([P[n]['estimate'] for n in NAMES], Q.mean(0)), 0.0, abs_=1e-12)
check.near('Rubin: the within variance W, the mean of the m variances', gap([P[n]['w'] for n in NAMES], W), 0.0, abs_=1e-12)
check.near('Rubin: the between variance B, the variance of the m estimates', gap([P[n]['b'] for n in NAMES], B), 0.0, abs_=1e-12)
check.near('Rubin: T = W + (1 + 1/m) B', gap([P[n]['t'] for n in NAMES], T), 0.0, abs_=1e-12)
check.near('and statsmodels\' standard error is √T', gap([P[n]['se'] for n in NAMES], np.sqrt(T)), 0.0, abs_=1e-12)
check.near('statsmodels\' FMI is (1 + 1/m) B / T (R mice calls it lambda)', gap([P[n]['fmi'] for n in NAMES], lam), 0.0, abs_=1e-12)
check.near('the relative increase in variance (1 + 1/m) B / W', gap([P[n]['riv'] for n in NAMES], riv), 0.0, abs_=1e-12)
check.near('the Barnard-Rubin degrees of freedom, complete-data DF n − p', gap([P[n]['df'] for n in NAMES], dfbr), 0.0, abs_=1e-12)
mice_br = (m - 1) * (1 - lam) * (1 + dfcom) * dfcom / ((dfcom + 3) * (m - 1) + lam ** 2 * (1 - lam) * (1 + dfcom) * dfcom)
check.near('as R mice\'s barnard.rubin() writes them', gap([P[n]['df'] for n in NAMES], mice_br), 0.0, abs_=1e-12)
check.near('R mice\'s fmi, (riv + 2/(df + 3)) / (riv + 1)', gap([P[n]['fmi_mice'] for n in NAMES], (riv + 2 / (dfbr + 3)) / (riv + 1)), 0.0, abs_=1e-12)
check.near('Prob>|t| on those degrees of freedom', gap([P[n]['p_t'] for n in NAMES], 2 * stats.t.sf(np.abs(Q.mean(0) / np.sqrt(T)), dfbr)), 0.0, abs_=1e-12)
check('the optional columns are hidden', [c['key'] for c in r['analysis']['pooled']['columns'] if c.get('hidden')], ['w', 'b', 't', 'riv', 'df', 'p_t', 'fmi_mice'])
check('the terms, with JMP\'s names in the order of the effects', [x['term'] for x in r['analysis']['pooled']['rows']], NAMES)

# the imputed values
imp2 = MICEData(dd)
np.random.seed(1)
imp2 = MICEData(dd)
draws = {c: [] for c in ('bmi', 'activity', 'cholesterol')}
imp2.update_all(10)
for j in range(20):
    imp2.update_all(4)
    for c in draws:
        a = f'v{COLS.index(c)}'
        draws[c].append(imp2.data[a].to_numpy()[D[c].isna().to_numpy()])
# (MICE.fit fits the analysis model between the cycles, which draws nothing: the same values)
for x in r['imputed']:
    c = x['column']
    check.near(f'the imputed {c}: MICEData\'s values at every imputation', gap(x['draws'], draws[c]), 0.0, abs_=0)
    check(f'the imputed {c}: the rows where it is missing', x['rows'], [int(i) for i in np.flatnonzero(D[c].isna().to_numpy())])
    obs = set(D[c].dropna().tolist())
    check(f'the imputed {c}: every value is an observed one (predictive mean matching)', all(v in obs for dr in x['draws'] for v in dr), True)
tr = r['trace']
check('the trace: a mean of the imputed values for each of the 90 cycles', (tr['cycles'], [len(v) for v in tr['means'].values()]), (90, [90, 90, 90]))
check.near('the trace at an imputation is the mean of its values (bmi, the 5th)', tr['means']['bmi'][10 + 5 * 4 - 1], float(np.mean(draws['bmi'][4])), rel=1e-12)

# the missing-data summary and the complete-case fit
mr = r['missing']
check('missing: each column\'s count', [x['n_missing'] for x in mr['columns']], [int(D[c].isna().sum()) for c in COLS])
check.near('missing: the percent of bmi', mr['columns'][1]['pct'], 100 * float(D['bmi'].isna().mean()), rel=1e-12)
pat = D.isna().astype(int).astype(str).agg(''.join, axis=1).value_counts()
check('missing: the patterns and their counts (pandas)', {p['pattern']: p['count'] for p in mr['patterns']}, {k: int(v) for k, v in pat.items()})
check('missing: complete rows, rows with a missing value', (mr['complete'], mr['rows_with_missing']), (int(D.notna().all(axis=1).sum()), int(D.isna().any(axis=1).sum())))
cc = smf.ols('sbp ~ age + bmi + cholesterol + activity', D).fit()
C = rows_of(r, 'cc')
check.near('complete cases: the estimates of smf.ols on the complete rows', gap([C[n]['estimate'] for n in NAMES], cc.params[NAMES]), 0.0, abs_=1e-10)
check.near('complete cases: their standard errors', gap([C[n]['se'] for n in NAMES], cc.bse[NAMES]), 0.0, abs_=1e-10)
check('complete cases: N', r['analysis']['n_cc'], int(cc.nobs))

# known truth: the complete cases biased, the pooled fits not
ful = smf.ols('sbp ~ age + bmi + cholesterol + activity', FULL).fit()
zc = {n: (C[n]['estimate'] - TRUE[n]) / C[n]['se'] for n in NAMES}
zm = {n: (P[n]['estimate'] - TRUE[n]) / P[n]['se'] for n in NAMES}
print('   z from the truth, complete cases:', {k: round(v, 2) for k, v in zc.items()}, 'MICE:', {k: round(v, 2) for k, v in zm.items()})
check('known truth: every MICE estimate within 2 standard errors of the true coefficient', all(abs(v) < 2 for v in zm.values()), True)
check('known truth: the complete cases miss three coefficients or more by over 2 standard errors', sum(abs(v) > 2 for v in zc.values()) >= 3, True)
off = [n for n in NAMES if abs(zc[n]) > 2]
check(f'known truth: for those ({", ".join(off)}) MICE is closer than the complete cases to the fit of the data before any went missing',
      all(abs(P[n]['estimate'] - ful.params[n]) < abs(C[n]['estimate'] - ful.params[n]) for n in off), True)
check('known truth: MICE\'s intervals cover the true coefficients', all(P[n]['lower'] < TRUE[n] < P[n]['upper'] for n in NAMES), True)

# ---- the multivariate normal: the report against BayesGaussMI and MI.fit ----------------------------------------------
rb = call('mi.fit', table=tid, columns=COLS, response='sbp', effects=EFF, method='bayes', seed=1)
check('Bayesian Gaussian: no error', rb.get('error'), None)
check('its defaults are statsmodels\' MI: burn-in 100, 10 skipped', (rb['burnin'], rb['skip']), (100, 10))
mean, sd = dd.mean(), dd.std()
Z = (dd - mean) / sd
np.random.seed(1)
bimp = BayesGaussMI(Z)
mi = MI(bimp, sm.OLS, formula=F, model_args_fn=lambda f: [f], xfunc=lambda z: pd.DataFrame(np.asarray(z), columns=dd.columns) * sd + mean, burn=100, nrep=20, skip=10)
refb = mi.fit()
PB = rows_of(rb)
check.near('Bayesian Gaussian: the pooled estimates are statsmodels\'', gap([PB[n]['estimate'] for n in NAMES], refb.params), 0.0, abs_=1e-10)
check.near('Bayesian Gaussian: the standard errors', gap([PB[n]['se'] for n in NAMES], refb.bse), 0.0, abs_=1e-10)
check.near('Bayesian Gaussian: the fractions of missing information (MI.fit\'s fmi)', gap([PB[n]['fmi'] for n in NAMES], refb.fmi), 0.0, abs_=1e-10)
check('MIResults tests are normal too', bool(refb.use_t), False)
zb = {n: (PB[n]['estimate'] - TRUE[n]) / PB[n]['se'] for n in NAMES}
print('   z from the truth, Bayesian Gaussian:', {k: round(v, 2) for k, v in zb.items()})
check('known truth: every Bayesian Gaussian estimate within 2 standard errors of the truth', all(abs(v) < 2 for v in zb.values()), True)
check('its imputed values are not observed ones: the normal draws numbers', any(v not in set(D['bmi'].dropna()) for v in rb['imputed'][0]['draws'][0]), True)
check('its trace has 100 + 20 x 11 cycles', rb['trace']['cycles'], 320)

# why the page standardizes: statsmodels' priors with a column in large units. Standardized,
# the imputation does not depend on the units: bmi x 1000 + 50000 is imputed as 1000 x bmi's
# imputations + 50000, draw for draw. On the raw data statsmodels' fixed priors pull it away.
big = D.copy()
big['bmi'] = big['bmi'] * 1000 + 50000
r_one = call('mi.fit', table=tid, columns=COLS, method='bayes', m=5, seed=2)
r_big = call('mi.fit', table=as_table(big), columns=COLS, method='bayes', m=5, seed=2)
d_one = np.array(next(x for x in r_one['imputed'] if x['column'] == 'bmi')['draws'])
d_big = np.array(next(x for x in r_big['imputed'] if x['column'] == 'bmi')['draws'])
check.near('standardized, the imputations do not depend on the units: bmi x 1000 + 50000, draw for draw', gap(d_big, d_one * 1000 + 50000), 0.0, abs_=1e-9)
bb = big.copy()
bb.columns = [f'v{j}' for j in range(5)]
np.random.seed(2)
raw = BayesGaussMI(bb.copy())
for _ in range(100):
    raw.update()
miss_b = big['bmi'].isna().to_numpy()
raw_mean = float(np.asarray(raw.data)[miss_b, 1].mean())
page_mean = float(d_big.mean())
sd_b = float(big['bmi'].std())
print(f'   bmi x 1000 + 50000: observed mean {big["bmi"].mean():.0f} (sd {sd_b:.0f}); imputed mean, standardized {page_mean:.0f}, raw {raw_mean:.0f}')
check('statsmodels 0.14.6: BayesGaussMI on the raw data imputes it over 2 standard deviations away', abs(raw_mean - page_mean) > 2 * sd_b, True)

# ---- on average over simulated tables: the complete cases biased, the pooled fits not ---------------------------------------
rng = np.random.default_rng(20260927)
bias_cc, bias_mi = [], []
for k in range(8):
    n = 400
    age = np.round(rng.uniform(25, 76, n) - 0.5)
    bmi = np.round(20 + 0.08 * age + rng.normal(0, 3.2, n), 1)
    act = np.round(np.maximum(0, 7 - 0.06 * age - 0.12 * (bmi - 25) + rng.normal(0, 2, n)), 1)
    chol = np.round(3.6 + 0.03 * age + 0.04 * (bmi - 25) + rng.normal(0, 0.8, n), 2)
    sbp = np.round(60 + 0.45 * age + 1.1 * bmi + 3.5 * chol - 1.2 * act + rng.normal(0, 9, n))
    L_ = lambda z: 1 / (1 + np.exp(-z))  # noqa: E731
    fr = pd.DataFrame({'age': age, 'bmi': bmi, 'activity': act, 'cholesterol': chol, 'sbp': sbp})
    fr.loc[rng.uniform(size=n) < L_(-1.0 + 0.12 * (sbp - 130)), 'bmi'] = np.nan
    fr.loc[rng.uniform(size=n) < L_(-1.0 + 0.12 * (sbp - 130)), 'cholesterol'] = np.nan
    fr.loc[rng.uniform(size=n) < L_(-1.3 + 0.03 * (age - 50) + 0.1 * (sbp - 130)), 'activity'] = np.nan
    rr = call('mi.fit', table=as_table(fr), columns=COLS, response='sbp', effects=EFF, method='mice', seed=k)
    Pk, Ck = rows_of(rr), rows_of(rr, 'cc')
    bias_cc.append([Ck[n]['estimate'] - TRUE[n] for n in NAMES])
    bias_mi.append([Pk[n]['estimate'] - TRUE[n] for n in NAMES])
bc, bm = np.mean(bias_cc, 0), np.mean(bias_mi, 0)
print('   mean error over 8 tables, complete cases:', dict(zip(NAMES, bc.round(3))), 'MICE:', dict(zip(NAMES, bm.round(3))))
check('over 8 simulated tables the complete cases underestimate the age slope by over 20 %', bc[1] < -0.2 * TRUE['age'], True)
check('and MICE\'s mean error of it is under 10 %', abs(bm[1]) < 0.1 * TRUE['age'], True)
check('MICE\'s mean error is the smaller for the intercept and age', (abs(bm[0]) < abs(bc[0]), abs(bm[1]) < abs(bc[1])), (True, True))

# ---- categorical columns, a crossing, a binary response ----------------------------------------------------------------------------
rng = np.random.default_rng(3)
n = 300
g = rng.integers(0, 3, n)
x1 = rng.normal(0, 1, n) + 0.5 * g
x2 = 0.6 * x1 + rng.normal(0, 1, n)
sex = rng.integers(0, 2, n)
y = 1 + 0.8 * x1 - 0.5 * x2 + np.array([0.0, 0.7, -0.4])[g] + 0.6 * sex + 0.4 * x1 * sex + rng.normal(0, 1, n)
yb = (rng.uniform(size=n) < 1 / (1 + np.exp(-(-0.3 + 0.9 * x1 - 0.6 * x2)))).astype(float)
fr = pd.DataFrame({'y': y, 'x1': x1, 'x2': x2, 'group': np.array(['a', 'b', 'c'])[g], 'sex': np.where(sex == 1, 'M', 'F'), 'event': yb})
fr.loc[rng.uniform(size=n) < 0.2, 'x2'] = np.nan
fr.loc[rng.uniform(size=n) < 0.15, 'sex'] = np.nan
fr.loc[rng.uniform(size=n) < 0.1, 'x1'] = np.nan
frt = fr.copy()
frt['sex'] = frt['sex'].where(frt['sex'].notna(), None)
tid2 = table({c: [None if (isinstance(v, float) and math.isnan(v)) else v for v in frt[c].tolist()] for c in frt.columns},
             types={'group': 'nominal', 'sex': 'nominal', 'event': 'nominal'}, levels={'group': ['a', 'b', 'c'], 'sex': ['F', 'M'], 'event': [0.0, 1.0]})
C2 = ['y', 'x1', 'x2', 'group', 'sex']
r2 = call('mi.fit', table=tid2, columns=C2, response='y', effects=[['x1'], ['x2'], ['group'], ['sex'], ['x1', 'sex']], m=10, seed=4)
check('categorical columns and a crossing: no error', r2.get('error'), None)
check('the terms: effect coded, the crossing centred', [x['term'] for x in r2['analysis']['pooled']['rows']][:6],
      ['Intercept', 'x1', 'x2', 'group[a]', 'group[b]', 'sex[F]'])
m1 = float(fr['x1'].mean())
check('the crossing is named as JMP names it', r2['analysis']['pooled']['rows'][6]['term'], f'(x1-{m1:.6g})*sex[F]')
d2 = pd.DataFrame({'v0': fr['y'], 'v1': fr['x1'], 'v2': fr['x2'], 'v3': pd.Categorical(fr['group'], categories=['a', 'b', 'c']).codes.astype(float),
                   'v4': pd.Series(pd.Categorical(fr['sex'], categories=['F', 'M']).codes).replace(-1, np.nan).astype(float)})
F2 = (f'v0 ~ v1 + v2 + C(v3, Sum, levels=[0.0, 1.0, 2.0]) + C(v4, Sum, levels=[0.0, 1.0]) + '
      f'I((v1 - {m1!r}) * ((v4 == 0.0) * 1.0 - (v4 == 1.0) * 1.0))')
np.random.seed(4)
imp3 = MICEData(d2)
for a_ in ('v1', 'v2', 'v4'):
    imp3.set_imputer(a_, formula=' + '.join('C(v3)' if o == 'v3' else o for o in ['v0', 'v1', 'v2', 'v3', 'v4'] if o != a_))
ref3 = MICE(F2, sm.OLS, imp3, n_skip=3).fit(n_burnin=10, n_imputations=10)
P2 = r2['analysis']['pooled']['rows']
order2 = [x['name'] for x in P2]
names3 = list(ref3.exog_names)
check.near('categorical columns and a crossing: the pooled estimates are statsmodels\'', gap([x['estimate'] for x in P2], [ref3.params[names3.index(nm)] for nm in order2]), 0.0, abs_=1e-10)
check.near('and the fractions of missing information', gap([x['fmi'] for x in P2], [ref3.frac_miss_info[names3.index(nm)] for nm in order2]), 0.0, abs_=1e-10)
sx = next(x for x in r2['imputed'] if x['column'] == 'sex')
check('the binary categorical column is imputed as its codes, 0 or 1', set(v for dr in sx['draws'] for v in dr) <= {0.0, 1.0}, True)
check('its levels go with it', r2['levels']['sex'], ['F', 'M'])
tr2 = r2['trace']
check('the trace covers the three columns with missing values', sorted(tr2['means']), ['sex', 'x1', 'x2'])

r3 = call('mi.fit', table=tid2, columns=['x1', 'x2', 'event'], response='event', effects=[['x1'], ['x2']], m=8, seed=5)
check('a two-level response: logistic by default', (r3.get('error'), r3['model'], r3['analysis']['kind']), (None, 'logit', 'logit'))
check('its response is named by the level that is 1', r3['analysis']['response_label'], 'event[1]')
d3 = pd.DataFrame({'v0': fr['x1'], 'v1': fr['x2'], 'v2': fr['event']})
np.random.seed(5)
ref4 = MICE('v2 ~ v0 + v1', sm.GLM, MICEData(d3), n_skip=3, init_kwds={'family': sm.families.Binomial()}).fit(n_burnin=10, n_imputations=8)
check.near('a binary response: statsmodels\' MICE with a binomial GLM', gap([x['estimate'] for x in r3['analysis']['pooled']['rows']], ref4.params), 0.0, abs_=1e-9)

# ---- imputing only ----------------------------------------------------------------------------------------------------------------------
r5 = call('mi.fit', table=tid, columns=COLS, m=5, seed=7)
check('imputing only: no error and no analysis model', (r5.get('error'), 'analysis' in r5), (None, False))
check('imputing only: five imputations of each column', [len(x['draws']) for x in r5['imputed']], [5, 5, 5])
r6 = call('mi.fit', table=tid, columns=COLS, m=5, seed=7, method='bayes', burnin=20, skip=2)
check('imputing only, the normal: its cycles', (r6.get('error'), r6['trace']['cycles']), (None, 20 + 5 * 3))

# ---- the Python shown runs on the CSV export and gives the report's numbers ---------------------------------------------------------------
for label, kw, frame, name in (
        ('MICE with the model', dict(table=tid, columns=COLS, response='sbp', effects=EFF, seed=1), D, 'Health survey'),
        ('the normal with the model', dict(table=tid, columns=COLS, response='sbp', effects=EFF, method='bayes', seed=1), D, 'Health survey'),
        ('categorical, a crossing', dict(table=tid2, columns=C2, response='y', effects=[['x1'], ['x2'], ['group'], ['sex'], ['x1', 'sex']], m=10, seed=4), fr, 'mixed'),
        ('binary response', dict(table=tid2, columns=['x1', 'x2', 'event'], response='event', effects=[['x1'], ['x2']], m=8, seed=5), fr, 'mixed'),
        ('the normal, a complete categorical column', dict(table=tid2, columns=['y', 'x1', 'x2', 'group'], response='y', effects=[['x1'], ['group']], method='bayes', m=6, burnin=30, skip=3, seed=2), fr, 'mixed'),
        ('a subset of rows', dict(table=tid, columns=COLS, response='sbp', effects=EFF, rows=list(range(0, 400, 2)), m=6, seed=3), D, 'Health survey'),
        ('most rows', dict(table=tid, columns=COLS, response='sbp', effects=EFF, rows=list(range(9, 400)), m=6, seed=3), D, 'Health survey')):
    rr = call('mi.fit', **kw, table_name=name)
    if rr.get('error'):
        check(f'code ({label}): the report ran', rr['error'], None)
        continue
    ns, err = run_code(rr['code'], frame, name)
    check(f'code ({label}): runs', err, None)
    if err:
        print(rr['code'])
        continue
    res_ = ns['res']
    en = list(getattr(res_, 'exog_names', None) or res_.model.exog_names)
    P_ = rr['analysis']['pooled']['rows']
    check.near(f'code ({label}): its pooled estimates are the report\'s', gap([x['estimate'] for x in P_], [res_.params[en.index(x['name'])] for x in P_]), 0.0, abs_=1e-10)
    check.near(f'code ({label}): its standard errors', gap([x['se'] for x in P_], [res_.bse[en.index(x['name'])] for x in P_]), 0.0, abs_=1e-10)
    ccn = list(ns['cc'].params.index)
    ccp = np.asarray(ns['cc'].params)
    check.near(f'code ({label}): its complete-case fit', gap([x['estimate'] for x in rr['analysis']['cc']['rows']], [ccp[ccn.index(x['name'])] for x in rr['analysis']['cc']['rows']]), 0.0, abs_=1e-10)
for label, kw in (('MICE, imputing only', dict(columns=COLS, m=4, seed=8)), ('the normal, imputing only', dict(columns=COLS, m=4, seed=8, method='bayes', burnin=15, skip=1))):
    rr = call('mi.fit', table=tid, **kw, table_name='Health survey')
    ns, err = run_code(rr['code'], D, 'Health survey')
    check(f'code ({label}): runs', err, None)
    if err:
        print(rr['code'])
        continue
    for x in rr['imputed']:
        a_ = f'v{COLS.index(x["column"])}'
        mask = D[x['column']].isna().to_numpy()
        got = [np.asarray(im[a_])[mask] for im in ns['imputations']]
        check.near(f'code ({label}): its imputations of {x["column"]} are the report\'s', gap(got, x['draws']), 0.0, abs_=1e-9)

# ---- the cache and alpha ------------------------------------------------------------------------------------------------------------------
ra = call('mi.fit', table=tid, columns=COLS, response='sbp', effects=EFF, method='mice', seed=1, alpha=0.1)
check('another alpha comes from the cache', ra['cached'], True)
check.near('alpha 0.1: the interval of statsmodels\' conf_int(0.1)', gap([[x['lower'], x['upper']] for x in ra['analysis']['pooled']['rows']], ref.conf_int(0.1)), 0.0, abs_=1e-10)

# ---- refusals said in words ---------------------------------------------------------------------------------------------------------------
frn = fr.copy()
frn.loc[:30, 'group'] = None
tidn = table({c: [None if (v is None or (isinstance(v, float) and math.isnan(v))) else v for v in frn[c].tolist()] for c in frn.columns},
             types={'group': 'nominal', 'sex': 'nominal'}, levels={'group': ['a', 'b', 'c'], 'sex': ['F', 'M']})
for label, kw, want in (
        ('a three-level nominal column with missing values', dict(table=tidn, columns=['y', 'x1', 'group']), 'multinomial'),
        ('a categorical column with missing values for the normal', dict(table=tid2, columns=['y', 'x1', 'sex'], method='bayes'), 'not levels'),
        ('one column', dict(table=tid, columns=['bmi']), 'two columns'),
        ('the response among the effects', dict(table=tid, columns=COLS, response='sbp', effects=[['sbp']]), 'take it out'),
        ('one imputation', dict(table=tid, columns=COLS, m=1), 'between 2 and 200'),
        ('a logistic model of a continuous response', dict(table=tid, columns=COLS, response='sbp', effects=[['age']], model='logit'), '0 or 1'),
        ('a label column with 400 levels', dict(table=table({'id': [f'H{i}' for i in range(400)], **{c: D[c].tolist() for c in ('bmi', 'sbp')}}), columns=['id', 'bmi', 'sbp']), 'too many')):
    rr = call('mi.fit', **kw)
    check(f'refused, {label}', want in (rr.get('error') or ''), True)
    if want not in (rr.get('error') or ''):
        print(rr.get('error'))

sys.exit(check.done())
