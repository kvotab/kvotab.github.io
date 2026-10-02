#!/usr/bin/env python3
"""Analyze > Distribution's backend (resources/py/smui/distribution.py),
checked against scipy and statsmodels called directly, and against the
definitions JMP documents: quantiles by (n+1)p, the normal quantile plot
at r/(n+1), Wilson intervals for proportions. The other interval methods
by their formulas and Clopper and Pearson's 5 of 20; Test Rate against
the values statsmodels' tests record from R (DescTools PoissonCI, exactci,
ratesci) and the classic Garwood limits. Test Mean's effect size and Bayes
factor and Test Probabilities' binomial Bayes factor against a
noncentrality search, the noncentral t and beta integrals, the closed
forms, BayesFactor's 17.25888 for t = −4.0621 on 9 DF, and pingouin's
compute_effsize, compute_esci, bayesfactor_ttest and bayesfactor_binom
when it is installed (GPL: a reference only). Fit All brings back none of
statsmodels' warnings from its searches, names a search that did not
converge (a short Powell search still gains), prints a progress line
before each family, and gives the single fits' AICc.

    python3 resources/tests/smui/test_distribution.py
"""
import math
import sys

import numpy as np
from scipy import stats
from statsmodels.stats.proportion import proportion_confint
from statsmodels.stats.weightstats import DescrStatsW

from backend import Checks, call, table

check = Checks()
rng = np.random.default_rng(20260926)
x = rng.normal(50, 7, 83)
x[5] = np.nan
g = rng.choice(['a', 'b', 'c'], 83, p=[0.5, 0.3, 0.2]).tolist()
w = rng.uniform(0.5, 2, 83)
tid = table({'x': x, 'g': g, 'w': w})
xs = x[np.isfinite(x)]
n = len(xs)

r = call('distribution.continuous', table=tid, column='x')
m = r['moments']
check('n and n missing', (m['n'], r['n_missing']), (float(n), 1))
check.near('mean', m['mean'], float(np.mean(xs)))
check.near('std dev (n-1)', m['sd'], float(np.std(xs, ddof=1)))
check.near('std err mean', m['se'], float(np.std(xs, ddof=1) / math.sqrt(n)))
lo, hi = stats.t.interval(0.95, n - 1, loc=np.mean(xs), scale=np.std(xs, ddof=1) / math.sqrt(n))
check.near('lower 95% mean', m['lower'], float(lo))
check.near('upper 95% mean', m['upper'], float(hi))
check.near('skewness (unbiased)', m['skewness'], float(stats.skew(xs, bias=False)))
check.near('kurtosis (unbiased excess)', m['kurtosis'], float(stats.kurtosis(xs, bias=False)))
# JMP's quantiles: the (n+1)p-th order statistic, interpolated
srt = np.sort(xs)


def jmp_q(p):
    h = (n + 1) * p
    if h <= 1:
        return srt[0]
    if h >= n:
        return srt[-1]
    k = int(math.floor(h))
    return srt[k - 1] + (h - k) * (srt[k] - srt[k - 1])


for q in r['quantiles']:
    check.near(f'quantile {q["p"]}', q['value'], float(jmp_q(q['p'])))
check('quantile labels', [q['label'] for q in r['quantiles'] if q['label']], ['maximum', 'quartile', 'median', 'quartile', 'minimum'])
sw = [t for t in r['normality'] if t['test'].startswith('Shapiro')][0]
check.near('Shapiro-Wilk W', sw['stat'], float(stats.shapiro(xs).statistic))
check.near('robust mean is Huber', m['robust_mean'], float(np.asarray(__import__('statsmodels.robust.scale', fromlist=['Huber']).Huber()(xs)[0])), rel=1e-7)
check('code shown', 'DescrStatsW' in r['code'], True)

# weights
rw = call('distribution.continuous', table=tid, column='x', weight='w')
ww = w[np.isfinite(x)]
d = DescrStatsW(xs, weights=ww, ddof=1)
check.near('weighted mean', rw['moments']['mean'], float(d.mean))
check.near('weighted sd', rw['moments']['sd'], float(d.std))
check('weighted: no normality tests', rw['normality'], None)

# normal quantile plot positions
qq = call('distribution.qq', table=tid, column='x')
check.near('qq first z', qq['z'][0], float(stats.norm.ppf(1 / (n + 1))))
check('qq rows are table rows', sorted(qq['rows'])[:6], [0, 1, 2, 3, 4, 6])

# tests
tm = call('distribution.test_mean', table=tid, column='x', mu=48)
t_ref = stats.ttest_1samp(xs, 48)
check.near('t test', tm['t']['stat'], float(t_ref.statistic))
check.near('t test p', tm['t']['p_two'], float(t_ref.pvalue))
check.near('wilcoxon p', tm['wilcoxon']['p_two'], float(stats.wilcoxon(xs - 48).pvalue))
ts = call('distribution.test_sd', table=tid, column='x', sigma=6)
check.near('chi-square of sd', ts['chi2'], float((n - 1) * np.var(xs, ddof=1) / 36))
eq = call('distribution.equivalence', table=tid, column='x', low=45, upp=55)
check.near('TOST p', eq['p'], float(DescrStatsW(xs, ddof=1).ttost_mean(45, 55)[0]))
iv = call('distribution.intervals', table=tid, column='x', alpha=0.05, k_future=1, coverage=0.9)
half = stats.t.ppf(0.975, n - 1) * np.std(xs, ddof=1) * math.sqrt(1 + 1 / n)
check.near('prediction interval', iv['prediction']['upper'], float(np.mean(xs) + half))

# fits
f = call('distribution.fit', table=tid, column='x', dist='normal')
check.near('normal fit mu', f['params'][0]['estimate'], float(np.mean(xs)))
check.near('normal fit sigma (n-1)', f['params'][1]['estimate'], float(np.std(xs, ddof=1)))
fw = call('distribution.fit', table=tid, column='x', dist='weibull')
c, loc, scale = stats.weibull_min.fit(xs, floc=0)
check.near('weibull scale', fw['params'][0]['estimate'], float(scale), rel=1e-4)
check.near('weibull shape', fw['params'][1]['estimate'], float(c), rel=1e-4)
check('weibull has standard errors', all(p['se'] and p['se'] > 0 for p in fw['params']), True)
fa = call('distribution.fit_all', table=tid, column='x')
check('fit all sorted by AICc', [x['aicc'] for x in fa['fits']] == sorted(x['aicc'] for x in fa['fits']), True)
check.near('AICc weights sum to one', sum(x['weight'] for x in fa['fits']), 1.0)

# Fit All's searches: statsmodels' warnings stay out of the report (Nelder-Mead
# stops at its 4000 steps on Johnson Su's flat likelihood here and BFGS then
# converges; t's ν and the negative binomial's σ end at their bounds); a
# search that did not converge is named (two tight clusters: Johnson Sb and the
# three-normal mixture gain more from a short Powell search); 'smui:progress'
# lines say which family is fitted; the fits are the single fits' (Fit All only
# leaves out their standard errors, goodness of fit and curves)
import contextlib  # noqa: E402
import io  # noqa: E402
from smui import distribution as D  # noqa: E402
r11 = np.random.default_rng(11)
near_normal = r11.normal(170, 9, 1000)
r11.uniform(0, 10, 200)
two = np.r_[np.full(30, 1.0), np.full(30, 2.0)] + r11.normal(0, 1e-3, 60)
tid_nn, tid_two = table({'v': near_normal.tolist()}), table({'v': two.tolist()})
out = io.StringIO()
with contextlib.redirect_stdout(out):
    fa_nn = call('distribution.fit_all', table=tid_nn, column='v')
lines = [ln for ln in out.getvalue().splitlines() if ln.startswith('smui:progress fitall')]
fams = [f[1] for f in D._families(near_normal) if f[-1]]
check('Fit All: no statsmodels warnings come back (Nelder-Mead\'s cap, t at its bound)', (fa_nn.get('warnings'), [f['dist'] for f in fa_nn['fits'] if f['note']]), (None, []))
check('... a progress line before each family, in words, and one at the end', lines, [f'smui:progress fitall {i} {len(fams)} Fitting the {lab} distribution' for i, lab in enumerate(fams)] + [f'smui:progress fitall {len(fams)} {len(fams)} Comparing the fits'])
one = call('distribution.fit', table=tid_nn, column='v', dist='johnsonsu')
check.near('... its Johnson Su fit is the single fit\'s (AICc)', next(f['aicc'] for f in fa_nn['fits'] if f['dist'] == 'johnsonsu'), one['aicc'], rel=1e-12)
check('a Johnson Su fit to near-normal data has no standard errors, and says why', (one.get('warning', '')[:18], all(p['se'] is None for p in one['params'])), ('No standard errors', True))
ft_nn = call('distribution.fit', table=tid_nn, column='v', dist='t')
check('a t whose ν reaches its bound is at its maximum: no warning, the bound noted', (ft_nn.get('warning'), 'bound' in ft_nn.get('note', ''), round(ft_nn['params'][2]['estimate'])), (None, True, 1000))
with contextlib.redirect_stdout(io.StringIO()):
    fa_two = call('distribution.fit_all', table=tid_two, column='v')
check('two tight clusters: Fit All names the searches that did not converge', sorted(f['dist'] for f in fa_two['fits'] if f['note'] == 'the search did not converge'), ['johnsonsb', 'normal3'])
check('... and no statsmodels warnings', fa_two.get('warnings'), None)
sb = call('distribution.fit', table=tid_two, column='v', dist='johnsonsb')
check('... the single Johnson Sb fit says so in words', sb.get('warning', '').startswith('The maximum likelihood search did not converge'), True)

# more of JMP's Continuous Fit list
tw = stats.t.rvs(4, loc=3, scale=2, size=83, random_state=5)
k = np.random.default_rng(3).negative_binomial(3, 0.4, 83).astype(float)
mix = np.concatenate([np.random.default_rng(4).normal(10, 1, 50), np.random.default_rng(5).normal(16, 1, 33)])
tid2 = table({'t': tw.tolist(), 'k': k.tolist(), 'mix': mix.tolist()})
ft = call('distribution.fit', table=tid2, column='t', dist='t')
df_, loc_, sc_ = stats.t.fit(tw)
check.near("Student's t location as scipy", ft['params'][0]['estimate'], float(loc_), rel=1e-4)
check.near("Student's t df as scipy", ft['params'][2]['estimate'], float(df_), rel=1e-3)
fm = call('distribution.fit', table=tid2, column='mix', dist='normal2')
check('normal 2 mixture finds the components', (round(fm['params'][0]['estimate']), round(fm['params'][1]['estimate'])), (10, 16))
check.near('mixture proportion', fm['params'][4]['estimate'], 50 / 83, abs_=0.05)
import statsmodels.api as sm
nb = sm.NegativeBinomial(k, np.ones(len(k))).fit(disp=0)
alpha_nb = float(nb.params[-1])
fn = call('distribution.fit', table=tid2, column='k', dist='negbin')
check.near('Gamma Poisson mean = sample mean', fn['params'][0]['estimate'], float(np.mean(k)), rel=1e-4)
check.near('Gamma Poisson σ = 1 + α μ (statsmodels NB2)', fn['params'][1]['estimate'], 1 + alpha_nb * float(np.mean(k)), rel=1e-3)
fk = call('distribution.fit', table=tid2, column='mix', dist='kde')
check.near('smooth curve integrates to one', float(np.trapezoid(fk['curve']['pdf'], fk['curve']['x'])), 1.0, abs_=0.01)

# capability
cp = call('distribution.capability', table=tid, column='x', lsl=30, usl=70)
s = float(np.std(xs, ddof=1))
check.near('Cp overall', cp['sigma']['overall']['cp'], 40 / (6 * s))
check.near('Cpk overall', cp['sigma']['overall']['cpk'], min(70 - np.mean(xs), np.mean(xs) - 30) / (3 * s))

# categorical
cr = call('distribution.categorical', table=tid, column='g')
counts = {lv: g.count(lv) for lv in 'abc'}
check('level counts', [(l['level'], l['count']) for l in cr['levels']], [(k, float(v)) for k, v in counts.items()])
lo, hi = proportion_confint(counts['a'], 83, method='wilson')
check.near('Wilson interval', cr['levels'][0]['lower'], float(lo))
tp = call('distribution.test_probs', table=tid, column='g', probs={'a': 1, 'b': 1, 'c': 1})
check.near('Pearson chi-square', tp['tests'][1]['stat'], float(stats.chisquare(list(counts.values())).statistic))
# Confidence Interval Method: statsmodels' proportion_confint, and each method by its formula
z975 = stats.norm.ppf(0.975)
k_, n_ = counts['a'], 83
p_ = k_ / n_
formula = {
    'wilson': ((p_ + z975 ** 2 / (2 * n_)) / (1 + z975 ** 2 / n_), z975 * math.sqrt(p_ * (1 - p_) / n_ + z975 ** 2 / (4 * n_ ** 2)) / (1 + z975 ** 2 / n_)),
    'agresti_coull': ((k_ + z975 ** 2 / 2) / (n_ + z975 ** 2), None),
    'normal': (p_, z975 * math.sqrt(p_ * (1 - p_) / n_)),
}
for meth in ('wilson', 'agresti_coull', 'jeffreys', 'beta', 'normal'):
    cm = call('distribution.categorical', table=tid, column='g', ci_method=meth)
    lo_, hi_ = proportion_confint(counts['a'], 83, method=meth)
    check.near(f'{meth}: = proportion_confint', cm['levels'][0]['upper'], float(hi_))
    check('its label', cm['ci_label'], {'wilson': 'Wilson score', 'agresti_coull': 'Agresti-Coull', 'jeffreys': 'Jeffreys', 'beta': 'Clopper-Pearson (exact)', 'normal': 'Wald'}[meth])
    if meth == 'beta':
        check.near('Clopper-Pearson by the beta quantiles', cm['levels'][0]['lower'], float(stats.beta.ppf(0.025, k_, n_ - k_ + 1)))
    elif meth == 'jeffreys':
        check.near('Jeffreys: the Beta(x + ½, n − x + ½) interval', cm['levels'][0]['upper'], float(stats.beta.ppf(0.975, k_ + 0.5, n_ - k_ + 0.5)))
    elif meth == 'agresti_coull':
        pt = formula[meth][0]
        check.near('Agresti-Coull by its formula', cm['levels'][0]['lower'], float(pt - z975 * math.sqrt(pt * (1 - pt) / (n_ + z975 ** 2))))
    else:
        c_, h_ = formula[meth]
        check.near(f'{meth} by its formula', cm['levels'][0]['lower'], float(c_ - h_))
# the classic 5 of 20 (Clopper and Pearson's exact interval 0.0866 to 0.4910)
t520 = table({'r': ['yes'] * 5 + ['no'] * 15}, levels={'r': ['yes', 'no']})
cp = call('distribution.categorical', table=t520, column='r', ci_method='beta')['levels'][0]
check('5 of 20, Clopper-Pearson: 0.0866 to 0.4910', (round(cp['lower'], 4), round(cp['upper'], 4)), (0.0866, 0.491))
check('an unknown method', 'error' in call('distribution.categorical', table=tid, column='g', ci_method='nope'), True)

# Test Rate: 15 events in 400 (R DescTools PoissonCI and the exact test, as statsmodels' tests record them)
tr15 = table({'k': [3.0, 4, 2, 6, 0], 'e': [100.0, 80, 70, 120, 30]})
for meth, cim, pv, ci_ in (('exact-c', 'exact-c', 0.313026269279486, (0.0209884653319583, 0.0618505471787146)),
                           ('score', 'score', 0.263552477282973, (0.0227264749053794, 0.0618771721463559)),
                           ('score', 'jeff', None, (0.0219234232268444, 0.0602898619930649)),
                           ('wald', 'wald', None, (0.0185227303217751, 0.0564772696782249))):
    rt = call('distribution.test_rate', table=tr15, column='k', rate=0.05, exposure='e', method=meth, ci_method=cim)
    check('15 events in 400 exposure', (rt['count'], rt['exposure'], rt['units']), (15.0, 400.0, 5.0))
    if pv is not None:
        check.near(f'Test Rate, {meth}: p (DescTools / exactci {pv})', rt['p_two'], pv, rel=1e-12)
    check.near(f'{cim} interval: lower ({ci_[0]})', rt['lower'], ci_[0], rel=1e-12)
    check.near(f'{cim} interval: upper ({ci_[1]})', rt['upper'], ci_[1], rel=1e-12)
from statsmodels.stats.rates import confint_poisson, test_poisson  # noqa: E402
rt = call('distribution.test_rate', table=tr15, column='k', rate=0.05, exposure='e', method='midp-c', ci_method='midp-c')
check.near('mid-p test = test_poisson', rt['p_two'], float(test_poisson(15, 400, value=0.05, method='midp-c').pvalue))
check.near('mid-p upper limit (R ratesci 0.0604627555786095)', rt['upper'], 0.0604627555786095, rel=1e-5)
# the classic exact (Garwood) limits: 10 events, 4.7954 to 18.3904; one-sided exact p P(X ≥ 10 | 5)
t10 = table({'k': [10.0]})
rt = call('distribution.test_rate', table=t10, column='k', rate=5, method='exact-c', ci_method='exact-c')
check('Garwood: 10 events, 4.7954 to 18.3904', (round(rt['lower'], 4), round(rt['upper'], 4)), (4.7954, 18.3904))
check.near('exact one-sided p = P(X ≥ 10) for a mean of 5 (R poisson.test 0.03182806)', rt['p_greater'], float(stats.poisson.sf(9, 5)))
check.near('the same, as R prints it', rt['p_greater'], 0.03182806, abs_=5e-9)
check.near('exact two-sided p doubles the smaller tail', rt['p_two'], 2 * float(stats.poisson.sf(9, 5)))
# Freq counts units; the Pearson dispersion without an exposure is the index of dispersion s²/mean
kk = np.array([0, 1, 2, 3, 1, 0, 2, 5, 1, 1, 4, 0], float)
fq = np.array([1, 2, 1, 1, 3, 1, 1, 1, 2, 1, 1, 2], float)
tfr = table({'k': kk, 'f': fq})
rt = call('distribution.test_rate', table=tfr, column='k', rate=1.5, freq='f', method='score', ci_method='score')
ke = np.repeat(kk, fq.astype(int))
check('Freq: the count and units of the repeated rows', (rt['count'], rt['exposure'], rt['units']), (float(ke.sum()), float(len(ke)), float(len(ke))))
check.near('Freq: the score test of the repeated rows', rt['p_two'], float(test_poisson(ke.sum(), len(ke), value=1.5, method='score').pvalue))
check.near('the dispersion = variance/mean of the repeated counts', rt['dispersion'], float(np.var(ke, ddof=1) / np.mean(ke)))
tz0 = table({'k': [0.0, 0, 0], 'e': [4.0, 4, 4]})
rt = call('distribution.test_rate', table=tz0, column='k', rate=0.2, exposure='e', method='exact-c', ci_method='midp-c')
check('no events: the mid-p lower limit is 0 (statsmodels returns the upper twice)', (rt['lower'], round(rt['upper'], 6), len(rt['notes']) > 0), (0.0, round(math.log(20) / 12, 6), True))
check('Test Rate needs counts', 'error' in call('distribution.test_rate', table=tid, column='x', rate=1), True)
check('and a positive rate', 'error' in call('distribution.test_rate', table=t10, column='k', rate=0), True)
te0 = table({'k': [1.0, 2, 3], 'e': [1.0, 0, 2]})
rt = call('distribution.test_rate', table=te0, column='k', rate=1, exposure='e')
check('a row without a positive exposure is left out, said so', (rt['count'], rt['exposure'], len(rt['notes'])), (4.0, 3.0, 1))
# the Poisson fit's exact interval of λ
kf = call('distribution.fit', table=table({'k': kk}), column='k', dist='poisson')
lo_, hi_ = confint_poisson(kk.sum(), len(kk), method='exact-c')
check.near('Fitted Poisson: the exact interval of λ = confint_poisson(exact-c)', kf['exact']['upper'], float(hi_))

# the code under these results runs on a CSV export and gives the report's numbers
import contextlib  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import warnings  # noqa: E402
import pandas as pd  # noqa: E402


def code_ns(columns, code, label):
    with tempfile.TemporaryDirectory() as tmp:
        pd.DataFrame(columns).to_csv(os.path.join(tmp, 'data.csv'), index=False)
        here = os.getcwd()
        os.chdir(tmp)
        ns = {}
        try:
            with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter('ignore')
                exec(compile(code, label, 'exec'), ns)
        except Exception as e:
            ns['__error__'] = f'{type(e).__name__}: {e}'
        finally:
            os.chdir(here)
    check(f'the code of {label} runs', ns.get('__error__', True), True)
    return ns


for label_, cols_, tbl_, kw in (('Test Rate with an exposure', {'k': [3.0, 4, 2, 6, 0], 'e': [100.0, 80, 70, 120, 30]}, tr15, {'exposure': 'e', 'method': 'score', 'ci_method': 'jeff', 'rate': 0.05}),
                                ('Test Rate with Freq', {'k': kk, 'f': fq}, tfr, {'freq': 'f', 'rate': 1.5}),
                                ('Test Rate of rows', {'k': kk}, table({'k': kk}), {'rate': 1.5, 'method': 'midp-c'})):
    rt = call('distribution.test_rate', table=tbl_, column='k', **kw)
    ns = code_ns(cols_, rt['code'], label_)
    if 'count' in ns:
        check(f'{label_}: the count and exposure', (float(ns['count']), float(ns['exposure'])), (rt['count'], rt['exposure']))
        check.near(f'{label_}: the interval', float(confint_poisson(ns['count'], ns['exposure'], method=rt['ci_method'])[1]), rt['upper'])
        check.near(f'{label_}: the p-value', float(test_poisson(ns['count'], ns['exposure'], value=kw['rate'], method=rt['method']).pvalue), rt['p_two'])
for label_, kw in (('Frequencies, Clopper-Pearson', {'ci_method': 'beta'}), ('Frequencies with a weight', {'ci_method': 'wilson', 'weight': 'w'})):
    cm = call('distribution.categorical', table=tid, column='g', **kw)
    ns = code_ns({'x': x, 'g': g, 'w': w}, cm['code'], label_)
    if 'counts' in ns:
        check(f'{label_}: the counts', [round(float(v), 9) for v in ns['counts'].to_numpy()], [round(l_['count'], 9) for l_ in cm['levels']])
        check.near(f'{label_}: the first interval', float(proportion_confint(ns['counts'].iloc[0], ns['counts'].sum(), method=cm['ci_method'])[1]), cm['levels'][0]['upper'])
ns = code_ns({'k': kk}, kf['code'], 'Fitted Poisson')

# ---- Test Mean's effect size and Bayes factor, Test Probabilities' Bayes factor (round 5) ----------
# Against pingouin (GPL: a reference only, skipped without it), the formulas and a noncentrality
# search written out here, the noncentral t integral of the one-sided Bayes
# factors, direct integrals of the beta prior, and BayesFactor's published
# 17.25888 (t = −4.062128 on 9 DF, r = √2/2).
try:
    import pingouin as pg  # noqa: E402
except ImportError:
    pg = None
    print('pingouin is not installed: its reference checks are skipped')
from scipy import integrate, special  # noqa: E402


def ncp_bisect(t, df, q):
    a, b = t - 20 - abs(t), t + 20 + abs(t)
    for _ in range(200):
        m_ = (a + b) / 2
        if stats.nct.cdf(t, df, m_) > q:
            a = m_
        else:
            b = m_
    return (a + b) / 2


ef = call('distribution.effect', table=tid, column='x', mu=48)
er = {r_['effect']: r_ for r_ in ef['table']['rows']}
d_ = (xs.mean() - 48) / xs.std(ddof=1)
check.near("Test Mean: Cohen's d = (mean − μ₀)/s", er["Cohen's d"]['estimate'], float(d_), rel=1e-12)
if pg is not None:
    check.near("Test Mean: Cohen's d = pingouin compute_effsize(x, μ₀)", er["Cohen's d"]['estimate'], float(pg.compute_effsize(xs, 48)), rel=1e-12)
J_ = np.exp(special.gammaln((n - 1) / 2) - 0.5 * np.log((n - 1) / 2) - special.gammaln((n - 2) / 2))
check.near("Test Mean: Hedges' g = J(n − 1)·d, J exact", er["Hedges' g"]['estimate'], float(J_ * d_), rel=1e-12)
check.near("Test Mean: Hedges' g ≈ d(1 − 3/(4n − 5)), the usual approximation", er["Hedges' g"]['estimate'], float(d_ * (1 - 3 / (4 * n - 5))), rel=1e-4)
if pg is not None:
    check.near("Test Mean: Hedges' g ≈ pingouin's", er["Hedges' g"]['estimate'], float(pg.compute_effsize(xs, 48, eftype='hedges')), rel=1e-4)
t_ = d_ * np.sqrt(n)
check.near("Test Mean: d's exact lower limit, a noncentrality search", er["Cohen's d"]['lower'], ncp_bisect(t_, n - 1, 0.975) / np.sqrt(n), rel=1e-9)
check.near("Test Mean: d's exact upper limit", er["Cohen's d"]['upper'], ncp_bisect(t_, n - 1, 0.025) / np.sqrt(n), rel=1e-9)
if pg is not None:
    lo_, hi_ = pg.compute_esci(float(d_), n, 1, eftype='cohen', decimals=6)
    check("Test Mean: pingouin's approximate interval is within 0.02 of the exact one", abs(lo_ - er["Cohen's d"]['lower']) < 0.02 and abs(hi_ - er["Cohen's d"]['upper']) < 0.02, True)
efw = call('distribution.effect', table=tid, column='x', mu=48, weight='w')
dw = DescrStatsW(xs, weights=ww, ddof=1)
check.near("Test Mean with Weight: d from the weighted mean and SD", efw['table']['rows'][0]['estimate'], float((dw.mean - 48) / dw.std), rel=1e-12)
check.near("Test Mean with Weight: n is the sum of the weights, as in the t test", efw['n'], float(dw.sum_weights), rel=1e-12)
bt = call('distribution.bayes_t', table=tid, column='x', mu=48)
bf_ = [r_['bf10'] for r_ in bt['table']['rows']]
f1 = lambda dd: stats.nct.pdf(t_, n - 1, dd * np.sqrt(n)) * stats.cauchy.pdf(dd, 0, np.sqrt(2) / 2)
den = stats.t.pdf(t_, n - 1)
check.near('Test Mean: BF10 = the noncentral t likelihood integrated over the Cauchy prior', bf_[0], integrate.quad(f1, -np.inf, np.inf, limit=400)[0] / den, rel=1e-7)
if pg is not None:
    check.near('Test Mean: BF10 = pingouin bayesfactor_ttest (r = √2/2)', bf_[0], float(pg.bayesfactor_ttest(float(t_), n, r=np.sqrt(2) / 2)), rel=1e-8)
check.near('Test Mean: BF+0 = 2 × the noncentral t integral over δ > 0', bf_[1], 2 * integrate.quad(f1, 0, np.inf, limit=400)[0] / den, rel=1e-7)
check.near('Test Mean: BF−0 = 2 × the integral over δ < 0', bf_[2], 2 * integrate.quad(f1, -np.inf, 0, limit=400)[0] / den, rel=1e-7)
xs_sleep = 3.0 + (lambda z: (z - z.mean()) / z.std(ddof=1))(np.random.default_rng(11).normal(size=10)) + (-4.062127683382037 / np.sqrt(10))
bs = call('distribution.bayes_t', table=table({'v': xs_sleep}), column='v', mu=3.0)
check.near("Test Mean: t = −4.062128 on 9 DF gives BayesFactor's 17.25888", bs['table']['rows'][0]['bf10'], 17.25888, rel=3e-7)
check('Test Mean: prior scale 0 is refused', 'error' in call('distribution.bayes_t', table=tid, column='x', mu=48, r=0), True)
# the binomial Bayes factor of a two-level column
yn = ['yes'] * 37 + ['no'] * 23
tb2 = table({'yn': yn, 'f': [2.0] * 30 + [1.0] * 30, 'w': [0.5] * 60}, levels={'yn': ['yes', 'no']})
bb = call('distribution.bayes_binom', table=tb2, column='yn', probs={'yes': 1, 'no': 1})
bbf = [r_['bf10'] for r_ in bb['table']['rows']]
check.near('binomial BF10 = B(38, 24)/(B(1, 1)·½⁶⁰)', bbf[0], float(np.exp(special.betaln(38, 24) - special.betaln(1, 1) - 60 * np.log(0.5))), rel=1e-10)
if pg is not None:
    check.near('binomial BF10 = pingouin bayesfactor_binom (uniform prior)', bbf[0], float(pg.bayesfactor_binom(37, 60, 0.5)), rel=1e-10)
lik = lambda p_: p_ ** 37 * (1 - p_) ** 23
check.near('binomial BF+0 = ∫ over p > ½ of the likelihood × the prior renormalized, over the likelihood at ½', bbf[1], integrate.quad(lik, 0.5, 1)[0] / 0.5 / lik(0.5), rel=1e-8)
check.near('binomial BF−0', bbf[2], integrate.quad(lik, 0, 0.5)[0] / 0.5 / lik(0.5), rel=1e-8)
bb2 = call('distribution.bayes_binom', table=tb2, column='yn', probs={'yes': 3, 'no': 1}, a=2, b=3)
lik2 = lambda p_: p_ ** 37 * (1 - p_) ** 23 * stats.beta.pdf(p_, 2, 3)
check.near('p₀ = 0.75, a beta(2, 3) prior: BF10 by direct integration', bb2['table']['rows'][0]['bf10'], integrate.quad(lik2, 0, 1)[0] / 0.75 ** 37 / 0.25 ** 23, rel=1e-8)
if pg is not None:
    check.near('p₀ = 0.75, a beta(2, 3) prior: BF10 = pingouin', bb2['table']['rows'][0]['bf10'], float(pg.bayesfactor_binom(37, 60, 0.75, a=2, b=3)), rel=1e-10)
check.near('p₀ = 0.75, beta(2, 3): BF+0 by direct integration', bb2['table']['rows'][1]['bf10'], integrate.quad(lik2, 0.75, 1)[0] / stats.beta.sf(0.75, 2, 3) / 0.75 ** 37 / 0.25 ** 23, rel=1e-8)
bbf_ = call('distribution.bayes_binom', table=tb2, column='yn', probs={'yes': 1, 'no': 1}, freq='f')
check.near('with Freq: the counts are summed (67 of 90)', bbf_['table']['rows'][0]['bf10'], float(np.exp(special.betaln(68, 24) - 90 * np.log(0.5))), rel=1e-10)
bbw = call('distribution.bayes_binom', table=tb2, column='yn', probs={'yes': 1, 'no': 1}, weight='w')
check('with a Weight the counts are not whole: noted', any('whole' in t for t in bbw['notes']), True)
check('three levels: refused', 'error' in call('distribution.bayes_binom', table=tid, column='g', probs={'a': 1, 'b': 1, 'c': 1}), True)
# the code, on a CSV export
for label_, res_, cols_ in (('Test Mean\'s effect size', ef, {'x': x, 'g': g, 'w': w}), ('Test Mean\'s effect size with a weight', efw, {'x': x, 'g': g, 'w': w}),
                            ('Test Mean\'s Bayes factor', bt, {'x': x, 'g': g, 'w': w}), ('the binomial Bayes factor', bb2, {'yn': yn, 'f': [2.0] * 30 + [1.0] * 30, 'w': [0.5] * 60}),
                            ('the binomial Bayes factor with Freq', bbf_, {'yn': yn, 'f': [2.0] * 30 + [1.0] * 30, 'w': [0.5] * 60})):
    ns = code_ns(cols_, res_['code'], label_)
    if 'd_' in ns:
        check.near(f'{label_}: d', float(ns['d_']), res_['table']['rows'][0]['estimate'], rel=1e-12)
        check.near(f'{label_}: the exact lower limit', float(ns['lo']), res_['table']['rows'][0]['lower'], rel=1e-8)
    elif 'p' in ns and 'bf' in ns and 'k' not in ns:
        check.near(f'{label_}: BF10', float(ns['bf']), res_['table']['rows'][0]['bf10'], rel=1e-7)
        check.near(f'{label_}: BF+0', float(2 * ns['bf'] * ns['p']), res_['table']['rows'][1]['bf10'], rel=1e-7)
    elif 'bf' in ns:
        check.near(f'{label_}: BF10', float(ns['bf']), res_['table']['rows'][0]['bf10'], rel=1e-10)

# excluded rows: on the whole table's CSV, the code leaves out the rows the report leaves out
keep_ = [i for i in range(len(x)) if i % 4]
rex = call('distribution.continuous', table=tid, column='x', rows=keep_)
ns = code_ns({'x': x, 'g': g, 'w': w}, rex['code'], 'the moments with rows excluded')
if 'd' in ns:
    check.near("with rows excluded: the code's mean is the report's", float(ns['d'].mean), rex['moments']['mean'], rel=1e-12)
    check("... and its N", float(ns['d'].nobs), rex['moments']['n'])
rct = call('distribution.categorical', table=tid, column='g', rows=keep_)
ns = code_ns({'x': x, 'g': g, 'w': w}, rct['code'], 'the frequencies with rows excluded')
check("... the frequencies' code counts only the report's rows", int(ns['counts'].sum()) if 'counts' in ns else None, len([i for i in keep_ if g[i] is not None]))

# levels named None, NA and null: text in the CSV, and the code reads them as text (pandas'
# default would take them for missing values)
tna = table({'g': ['None', 'NA', 'a', 'None', 'null', 'a', None]})
rna = call('distribution.categorical', table=tna, column='g')
ns = code_ns({'g': ['None', 'NA', 'a', 'None', 'null', 'a', None]}, rna['code'], 'the frequencies of levels named None, NA and null')
check("levels named None, NA and null are levels in the code's counts, and the empty value is missing",
      sorted((str(k), int(v)) for k, v in ns['counts'].items()) if 'counts' in ns else None, [('NA', 1), ('None', 2), ('a', 2), ('null', 1)])

# rows subset and the error path
check('rows subset (row 5 is missing)', call('distribution.continuous', table=tid, column='x', rows=list(range(10)))['moments']['n'], 9.0)
check('no values', 'error' in call('distribution.continuous', table=tid, column='x', rows=[5]), True)
sys.exit(check.done())
