#!/usr/bin/env python3
"""Analyze > Specialized Modeling > Multivariate Time Series's backend
(resources/py/smui/multits.py), checked against statsmodels called directly
and against published values:

  statsmodels' documented VAR example ("Vector Autoregressions
  tsa.vector_ar": the quarterly log differences of realgdp, realcons and
  realinv from statsmodels.datasets.macrodata, read at run time): the VAR(2)
  summary, the lag order table of select_order(15) and the Granger causality
  F test (as the 0.8.0 documentation prints them), the forecasts and the FEVD
  of the lag AIC chooses (as the current documentation prints them);
  the critical values of Johansen's tests of MacKinnon, Haug and Michelis
  (1999), as EViews prints them, and the chi-square(1) limit of the last trace
  test with a constant; MacKinnon's (2010) response surfaces for the
  Engle-Granger test with two series.

The other series are simulated here from a fixed seed.

    python3 resources/tests/smui/test_multits.py
"""
import contextlib
import io
import math
import os
import sys
import tempfile
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller, coint, kpss
from statsmodels.tsa.vector_ar import var_model
from statsmodels.tsa.vector_ar.vecm import VECM, coint_johansen, select_coint_rank

from backend import FAILED, Checks, call, table
from smui import data, registry
from smui import multits as mts

warnings.simplefilter('ignore', DeprecationWarning)
warnings.simplefilter('ignore', FutureWarning)
check = Checks()
check('the module imports', FAILED.get('multits'), None)
check('its entry points are registered', all(f'multits.{n}' in registry.API for n in
      ('series', 'select_order', 'var', 'granger', 'irf', 'fevd', 'forecast', 'johansen', 'vecm', 'engle_granger')), True)


def ms(d):
    return int((pd.Timestamp(d) - pd.Timestamp(0)) // pd.Timedelta(milliseconds=1))


def date_table(cols, date_cols=('quarter',)):
    tid = table(cols)
    for c in date_cols:
        if c in cols:
            data.TABLES[tid]['meta'][c]['format'] = {'kind': 'date'}
    return tid


def close(a, b, rtol=1e-9, atol=1e-12):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.allclose(a, b, rtol=rtol, atol=atol))


# ---- statsmodels' documented example: macrodata, log differences -----------------------
md = sm.datasets.macrodata.load_pandas().data
NAMES = ['realgdp', 'realcons', 'realinv']
quarters = [ms(f'{int(y)}-{3 * (int(q) - 1) + 1:02d}-01') for y, q in zip(md['year'], md['quarter'])]
tid = date_table({'quarter': quarters, **{c: md[c].tolist() for c in NAMES}, 'infl': md['infl'].tolist()})
base = dict(table=tid, y=NAMES, time='quarter', log=True, diff=True)
ref_data = np.log(md[NAMES]).diff().dropna().reset_index(drop=True)

S = call('multits.series', **base)
check('series: no error', S.get('error'), None)
check('a quarterly Time ID (pandas.infer_freq)', (S['kind'], S['freq'], S['n']), ('date', 'QS-OCT', 202))
check('the series as analysed are the log differences', close(np.array(S['values']).T, ref_data.to_numpy(), rtol=1e-12), True)
check('... named for their transform', S['labels'], ['Δ log realgdp', 'Δ log realcons', 'Δ log realinv'])
check('the time axis starts one quarter in (the difference)', S['t'][0], float(ms('1959-04-01')))
for row, c in zip(S['stationarity'], NAMES):
    a = adfuller(ref_data[c], regression='c', autolag='AIC')
    check.near(f'{c}: ADF tau is adfuller\'s', row['adf'], float(a[0]))
    check.near(f'{c}: ADF p-value (MacKinnon)', row['adf_p'], float(a[1]), rel=1e-9, abs_=1e-15)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        k = kpss(ref_data[c], regression='c', nlags='auto')
    check.near(f'{c}: KPSS statistic is kpss\'s', row['kpss'], float(k[0]))
check('stationary after log and difference', [r['verdict'] for r in S['stationarity']], ['stationary'] * 3)
S0 = call('multits.series', table=tid, y=NAMES, time='quarter')
check('the levels have a unit root: difference', [r['verdict'] for r in S0['stationarity']], ['unit root: difference'] * 3)

# The lag order table of select_order(15), as the 0.8.0 documentation prints it.
DOC_LAGS = [  # lag: AIC, BIC, FPE, HQIC
    (-27.70, -27.65, 9.358e-13, -27.68), (-28.02, -27.82, 6.745e-13, -27.94), (-28.03, -27.66, 6.732e-13, -27.88),
    (-28.04, -27.52, 6.651e-13, -27.83), (-28.03, -27.36, 6.681e-13, -27.76), (-28.02, -27.19, 6.773e-13, -27.69),
    (-27.97, -26.98, 7.147e-13, -27.57), (-27.93, -26.79, 7.446e-13, -27.47), (-27.94, -26.64, 7.407e-13, -27.41),
    (-27.96, -26.50, 7.280e-13, -27.37), (-27.91, -26.30, 7.629e-13, -27.26), (-27.86, -26.09, 8.076e-13, -27.14),
    (-27.83, -25.91, 8.316e-13, -27.05), (-27.80, -25.73, 8.594e-13, -26.96), (-27.80, -25.57, 8.627e-13, -26.90),
    (-27.81, -25.43, 8.599e-13, -26.85)]
L = call('multits.select_order', **base, maxlags=15)
check('select_order: no error', L.get('error'), None)
check('lags 0 to 15 on the same 187 observations', (len(L['rows']), L['maxlags'], L['nobs']), (16, 15, 187))
ok = all(abs(r['aic'] - d[0]) <= 0.00501 and abs(r['bic'] - d[1]) <= 0.00501 and abs(r['hqic'] - d[3]) <= 0.00501
         and abs(r['fpe'] - d[2]) <= 0.0005e-13 * 1.01 for r, d in zip(L['rows'], DOC_LAGS))
check('the lag order table as documented (AIC, BIC, FPE, HQIC for lags 0 to 15)', ok, True)
check('the minima as documented: AIC 3, BIC 1, FPE 3, HQIC 1', L['selected'], {'aic': 3, 'bic': 1, 'hqic': 1, 'fpe': 3})
ref_sel = VAR(ref_data).select_order(15)
check('... and as select_order gives them now', close([[r[c] for c in ('aic', 'bic', 'hqic', 'fpe')] for r in L['rows']],
      np.column_stack([ref_sel.ics[c] for c in ('aic', 'bic', 'hqic', 'fpe')]), rtol=1e-12), True)
Lc = call('multits.select_order', **base, maxlags=500)
check('an impossible maximum lag is cut to the largest that can be fitted, with a note', (Lc['maxlags'], bool(Lc['notes'])),
      ((202 - 3 - 1) // 4, True))

# The VAR(2) of the documentation: results.summary().
DOC_VAR2 = {  # equation: [(coefficient, std. error, t-stat, prob)] for const, L1.realgdp, L1.realcons, L1.realinv, L2.realgdp, L2.realcons, L2.realinv
    'realgdp': [(0.001527, 0.001119, 1.365, 0.172), (-0.279435, 0.169663, -1.647, 0.100), (0.675016, 0.131285, 5.142, 0.000),
                (0.033219, 0.026194, 1.268, 0.205), (0.008221, 0.173522, 0.047, 0.962), (0.290458, 0.145904, 1.991, 0.047),
                (-0.007321, 0.025786, -0.284, 0.776)],
    'realcons': [(0.005460, 0.000969, 5.634, 0.000), (-0.100468, 0.146924, -0.684, 0.494), (0.268640, 0.113690, 2.363, 0.018),
                 (0.025739, 0.022683, 1.135, 0.257), (-0.123174, 0.150267, -0.820, 0.412), (0.232499, 0.126350, 1.840, 0.066),
                 (0.023504, 0.022330, 1.053, 0.293)],
    'realinv': [(-0.023903, 0.005863, -4.077, 0.000), (-1.970974, 0.888892, -2.217, 0.027), (4.414162, 0.687825, 6.418, 0.000),
                (0.225479, 0.137234, 1.643, 0.100), (0.380786, 0.909114, 0.419, 0.675), (0.800281, 0.764416, 1.047, 0.295),
                (-0.124079, 0.135098, -0.918, 0.358)],
}
V = call('multits.var', **base, p=2)
check('VAR(2): no error', V.get('error'), None)
eq = {e['name']: e['rows'] for e in V['equations']}
check("JMP-style term names beside statsmodels'", [(r['term'], r['sm']) for r in eq['realgdp'][:3]],
      [('Intercept', 'const'), ('realgdp(t−1)', 'L1.realgdp'), ('realcons(t−1)', 'L1.realcons')])
for name, want in DOC_VAR2.items():
    got = eq[name]
    ok = all(abs(r['estimate'] - w[0]) <= 5.01e-7 and abs(r['se'] - w[1]) <= 5.01e-7 and abs(r['t'] - w[2]) <= 5.01e-4
             and abs(r['p'] - w[3]) <= 5.01e-4 for r, w in zip(got, want))
    check(f'VAR(2) equation {name}: coefficients, std. errors, t and p as documented', ok, True)
sm_ = V['summary']
check('VAR(2) summary as documented (Nobs, Log likelihood, AIC, BIC, HQIC, FPE, Det(Omega_mle))',
      (V['nobs'], round(sm_['llf'], 2), round(sm_['aic'], 4), round(sm_['bic'], 4), round(sm_['hqic'], 4),
       float(f'{sm_["fpe"]:.5e}'), float(f'{sm_["detomega"]:.5e}')),
      (200, 1962.57, -27.9293, -27.5830, -27.7892, 7.42129e-13, 6.69358e-13))
DOC_CORR = [[1.000000, 0.603316, 0.750722], [0.603316, 1.000000, 0.131951], [0.750722, 0.131951, 1.000000]]
check('the correlation matrix of the residuals as documented', close(V['resid_corr'], DOC_CORR, rtol=0, atol=5.01e-7), True)
ref2 = VAR(ref_data).fit(2)
check('residuals are statsmodels\'', close(np.array(V['resid']['values']).T, ref2.resid, rtol=1e-10), True)
check('... aligned to the rows after the first two lags (and the difference)', V['resid']['rows'][:2], [3, 4])
w = ref2.test_whiteness(nlags=10)
check('Portmanteau test (test_whiteness, 10 lags)', (round(V['whiteness']['stat'], 9), V['whiteness']['df'], round(V['whiteness']['p'], 12)),
      (round(float(w.test_statistic), 9), int(w.df), round(float(w.pvalue), 12)))
wa = call('multits.var', **base, p=2, whiteness_lags=12, adjusted=True)['whiteness']
w2 = ref2.test_whiteness(nlags=12, adjusted=True)
check.near('... adjusted, 12 lags', wa['stat'], float(w2.test_statistic))
nt = ref2.test_normality()
check.near('normality test (test_normality: Jarque-Bera)', V['normality']['stat'], float(nt.test_statistic))
check('... df = 2k', V['normality']['df'], 6)
eigs = [complex(e['real'], e['imag']) for e in V['stability']['eigenvalues']]
check('companion eigenvalues: the reciprocals of statsmodels\' roots', close(sorted(np.abs(eigs)), sorted(1 / np.abs(ref2.roots)), rtol=1e-10), True)
check('stable, largest modulus first', (V['stability']['stable'], abs(eigs[0]) == max(abs(e) for e in eigs)), (True, True))

# The lag AIC chooses (3): the documented causality test, forecasts and FEVD.
G = call('multits.granger', **base, p=3)
check('Granger: no error', G.get('error'), None)
allg = [t for t in G['tests'] if t['caused'] == 'realgdp' and t['causing'] == 'all the others'][0]
check('realinv and realcons Granger-cause realgdp: the documented F test (6.999888, 2.114554, df (6, 567))',
      (round(allg['stat'], 6), round(allg['crit'], 6), allg['df'], allg['df_den']), (6.999888, 2.114554, 6, 567))
check.near('... p-value as documented', allg['p'], 3.3805963773884313e-07, rel=1e-6)
ref3 = VAR(ref_data).fit(3)
ok = all(abs(G['matrix'][i][j] - float(ref3.test_causality(j, [i], kind='f').pvalue)) < 1e-13 for i in range(3) for j in range(3) if i != j)
check('the p-value matrix: row causes column, test_causality for each pair', ok, True)
check('the diagonal is empty', [G['matrix'][i][i] for i in range(3)], [None, None, None])
Gw = call('multits.granger', **base, p=3, kind='wald')
check.near('Wald chi-square version', Gw['matrix'][2][0], float(ref3.test_causality(0, [2], kind='wald').pvalue), rel=1e-10, abs_=1e-15)
ic = ref3.test_inst_causality(1)
check.near('instantaneous causality (test_inst_causality)', G['inst'][1]['stat'], float(ic.test_statistic))
DOC_FC = [[0.00616044, 0.00500006, 0.00916198], [0.00427559, 0.00344836, -0.00238478], [0.00416634, 0.0070728, -0.01193629],
          [0.00557873, 0.00642784, 0.00147152], [0.00626431, 0.00666715, 0.00379567]]
F = call('multits.forecast', **base, p=3, h=5)
check('forecast: no error', F.get('error'), None)
check('the forecasts as documented (results.forecast(data.values[-3:], 5))', close(np.array(F['transformed']['mean']).T, DOC_FC, rtol=0, atol=5.01e-9), True)
fi = ref3.forecast_interval(ref_data.values[-3:], 5, alpha=0.05)
check('the limits are forecast_interval\'s', close(np.array(F['transformed']['lower']).T, fi[1], rtol=1e-12) and close(np.array(F['transformed']['upper']).T, fi[2], rtol=1e-12), True)
check('the forecast quarters continue the dates', (F['t'][0], F['t'][4]), (float(ms('2009-10-01')), float(ms('2010-10-01'))))
DOC_FEVD = {
    'realgdp': [[1.000000, 0.000000, 0.000000], [0.864889, 0.129253, 0.005858], [0.816725, 0.177898, 0.005378], [0.793647, 0.197590, 0.008763], [0.777279, 0.208127, 0.014594]],
    'realcons': [[0.359877, 0.640123, 0.000000], [0.358767, 0.635420, 0.005813], [0.348044, 0.645138, 0.006817], [0.319913, 0.653609, 0.026478], [0.317407, 0.652180, 0.030414]],
    'realinv': [[0.577021, 0.152783, 0.270196], [0.488158, 0.293622, 0.218220], [0.478727, 0.314398, 0.206874], [0.477182, 0.315564, 0.207254], [0.466741, 0.324135, 0.209124]],
}
FE = call('multits.fevd', **base, p=3, horizon=5)
check('FEVD: no error', FE.get('error'), None)
for i, c in enumerate(NAMES):
    check(f'FEVD for {c} as documented (fevd(5).summary())', close(FE['decomp'][i], DOC_FEVD[c], rtol=0, atol=5.01e-7), True)

# ---- impulse responses ------------------------------------------------------------------------
I = call('multits.irf', **base, p=2, horizon=10)
irf2 = ref2.irf(10)
check('orthogonalized by default: orth_irfs', close(I['values'], irf2.orth_irfs, rtol=1e-10), True)
q = stats.norm.ppf(0.975)
check('asymptotic bands: orth_irfs ± 1.96 stderr(orth=True)', close(I['lower'], irf2.orth_irfs - q * irf2.stderr(orth=True), rtol=1e-10), True)
check('... the band says which', 'asymptotic' in I['band_note'] and 'stderr' in I['band_note'], True)
In = call('multits.irf', **base, p=2, horizon=10, orth=False)
check('not orthogonalized: irfs', close(In['values'], irf2.irfs, rtol=1e-10), True)
check('... bands from stderr(orth=False)', close(In['upper'], irf2.irfs + q * irf2.stderr(orth=False), rtol=1e-10), True)
Ic = call('multits.irf', **base, p=2, horizon=10, cumulative=True)
check('cumulative: orth_cum_effects with cum_effect_stderr', close(Ic['values'], irf2.orth_cum_effects, rtol=1e-10) and
      close(Ic['lower'], irf2.orth_cum_effects - q * irf2.cum_effect_stderr(orth=True), rtol=1e-10), True)
Im = call('multits.irf', **base, p=2, horizon=10, bands='mc', repl=200)
lo_ref, hi_ref = irf2.errband_mc(orth=True, repl=200, signif=0.05, seed=np.random.MT19937(mts.SEED))
check('Monte Carlo bands are errband_mc\'s, seeded by a bit generator', close(Im['lower'], lo_ref, rtol=1e-12) and close(Im['upper'], hi_ref, rtol=1e-12), True)
check('... the same every time', Im['lower'], call('multits.irf', **base, p=2, horizon=10, bands='mc', repl=200)['lower'])
check('... bands with a width (an integer seed would give none)', float(np.max(np.array(Im['upper']) - np.array(Im['lower']))) > 1e-4, True)
lo_int, hi_int = irf2.errband_mc(orth=True, repl=20, signif=0.05, seed=mts.SEED)
check('why: statsmodels 0.14 with an integer seed repeats one simulated path', float(np.max(np.abs(hi_int - lo_int))), 0.0)
check('... the band says it is Monte Carlo, with the seed', 'Monte Carlo' in Im['band_note'] and str(mts.SEED) in Im['band_note'], True)
Io = call('multits.irf', **base, p=2, horizon=10, order=['realinv', 'realgdp', 'realcons'])
ref_o = VAR(ref_data[['realinv', 'realgdp', 'realcons']]).fit(2).irf(10)
check('another Cholesky ordering: the VAR refitted on the columns in that order', (Io['names'], close(Io['values'], ref_o.orth_irfs, rtol=1e-10)),
      (['realinv', 'realgdp', 'realcons'], True))
h0 = np.array(Io['values'][0])
check('... at impact a series answers only the shocks of the series before it', bool(np.allclose(np.triu(h0, 1), 0, atol=1e-15)), True)
check('an ordering that is not a permutation of Y is ignored', call('multits.irf', **base, p=2, order=['realinv', 'realgdp'])['names'], NAMES)
FEo = call('multits.fevd', **base, p=2, horizon=4, order=['realinv', 'realgdp', 'realcons'])
check('the FEVD takes the same ordering', close(FEo['decomp'], VAR(ref_data[['realinv', 'realgdp', 'realcons']]).fit(2).fevd(4).decomp, rtol=1e-10), True)

# ---- forecasts in the units of the table ---------------------------------------------------------
# A VAR(p) in differences is a VAR(p + 1) in levels: y_t = c + (I + A1) y_t-1 + (A2 - A1) y_t-2 + ... - Ap y_t-p-1.
A = ref3.coefs
p3 = A.shape[0]
Alev = np.zeros((p3 + 1, 3, 3))
Alev[0] = np.eye(3) + A[0]
for i in range(1, p3):
    Alev[i] = A[i] - A[i - 1]
Alev[p3] = -A[p3 - 1]
loglev = np.log(md[NAMES]).to_numpy()
fc_lev = var_model.forecast(loglev[-(p3 + 1):], Alev, ref3.coefs_exog.T, 5)
mse_lev = var_model.forecast_cov(var_model.ma_rep(Alev, 5), ref3.sigma_u.to_numpy(), 5)
orig = F['original']
check('forecasts in the units of the table: exp of the levels VAR\'s forecasts', close(np.array(orig['mean']).T, np.exp(fc_lev), rtol=1e-10), True)
lo_lev = np.exp(fc_lev - q * np.sqrt(np.diagonal(mse_lev, axis1=1, axis2=2)))
check('... the limits from the levels VAR\'s forecast MSE (statsmodels\' forecast_cov)', close(np.array(orig['lower']).T, lo_lev, rtol=1e-9), True)
lev, lse = mts.level_forecast(ref3, loglev[-1], ref3.forecast(ref_data.values[-3:], 5), 5)
check('level_forecast: the variances are the levels VAR\'s mse', close(lse ** 2, np.diagonal(mse_lev, axis1=1, axis2=2), rtol=1e-10), True)
check('... one step ahead the variance is sigma_u\'s', close(lse[0] ** 2, np.diag(ref3.sigma_u), rtol=1e-12), True)
check('the observed series in the units of the table', close(np.array(orig['observed']).T, md[NAMES].to_numpy(), rtol=1e-12), True)
fit_lev = np.array(orig['fitted'], dtype=float).T
check('in-sample one-step predictions in levels: the level before times exp of the predicted difference',
      close(fit_lev[4:], np.exp(loglev[3:-1] + np.asarray(ref3.fittedvalues)), rtol=1e-10) and bool(np.isnan(fit_lev[:4]).all()), True)
check('... and a note on how', 'median' in F['original_note'] and 'cumulated' in F['original_note'], True)
Fa = call('multits.forecast', **base, p=3, h=5, original=False)
check('original=False: only the forecasts as analysed', ('original' in Fa, Fa['units']), (False, 'as analysed'))

# ---- trends and exogenous columns ------------------------------------------------------------------
for tr in ('ct', 'n'):
    Vt = call('multits.var', **base, p=2, trend=tr)
    rt_ = VAR(ref_data).fit(2, trend=tr)
    check(f'trend {tr!r}: the coefficients are VAR.fit(trend={tr!r})\'s', close([[r['estimate'] for r in e['rows']] for e in Vt['equations']], rt_.params.T, rtol=1e-9), True)
check("'ct' has a Time Trend term", [r['term'] for r in call('multits.var', **base, p=1, trend='ct')['equations'][0]['rows']][:2], ['Intercept', 'Time Trend'])
Vx = call('multits.var', **base, p=2, exog=['infl'])
rx = VAR(ref_data, exog=md[['infl']].iloc[1:].reset_index(drop=True)).fit(2)
check('an exogenous column: VAR(exog=...)', close([[r['estimate'] for r in e['rows']] for e in Vx['equations']], rx.params.T, rtol=1e-9), True)
check('... its term after the intercept', [r['term'] for r in Vx['equations'][0]['rows']][:3], ['Intercept', 'infl', 'realgdp(t−1)'])
# future values of the exogenous column from the rows after the series (Y missing there)
tid_f = date_table({'quarter': quarters + [ms('2009-10-01'), ms('2010-01-01')], **{c: md[c].tolist() + [None, None] for c in NAMES},
                    'infl': md['infl'].tolist() + [1.5, 2.5]})
Fx = call('multits.forecast', table=tid_f, y=NAMES, time='quarter', log=True, diff=True, exog=['infl'], p=2, h=4)
check('forecasts with an exogenous column: no error', Fx.get('error'), None)
xf = np.array([[1.5], [2.5], [2.5], [2.5]])
check('... its future values from the rows after the series, the last held', close(np.array(Fx['transformed']['mean']).T, rx.forecast(ref_data.values[-2:], 4, exog_future=xf), rtol=1e-10), True)
check('... and a note says so', any('held' in n for n in Fx['notes']), True)
Imx = call('multits.irf', **base, p=2, exog=['infl'], bands='mc', repl=60)
check('Monte Carlo bands with an exogenous column run, with a caution', (Imx.get('error'), any('exogenous' in n for n in Imx['notes'])), (None, True))

# ---- missing values: excluded rows, dates with no row ------------------------------------------------
Sx = call('multits.series', table=tid, y=NAMES, time='quarter', excluded=[40, 41])
lev_ref = md[NAMES].copy()
lev_ref.iloc[[40, 41]] = np.nan
lev_ref = lev_ref.interpolate(limit_direction='both')
Vi = call('multits.var', table=tid, y=NAMES, time='quarter', excluded=[40, 41], p=1)
check('excluded rows are filled by linear interpolation for the VAR', close([[r['estimate'] for r in e['rows']] for e in Vi['equations']],
      VAR(lev_ref.reset_index(drop=True)).fit(1).params.T, rtol=1e-9), True)
check('... the report says so', any('interpolation' in n for n in Sx['notes']), True)
check('... and the graph shows them as gaps', (Sx['values'][0][40], Sx['values'][0][41], Sx['values'][0][42] is not None), (None, None, True))
keep = [k for k in range(len(md)) if k not in (60, 61, 62)]
tid_gap = date_table({'quarter': [quarters[k] for k in keep], **{c: [md[c][k] for k in keep] for c in NAMES}})
Sg = call('multits.series', table=tid_gap, y=NAMES, time='quarter')
check('three quarters with no row: the frequency is still quarterly and they are inserted', (Sg['freq_label'], Sg['n'], Sg['rows'][61]), ('quarterly', 203, None))
tid_short = date_table({'quarter': quarters, 'realgdp': md['realgdp'].tolist(), 'realcons': [None] * 10 + md['realcons'].tolist()[10:]})
Ss = call('multits.series', table=tid_short, y=['realgdp', 'realcons'], time='quarter')
check('the span is where every series has a value', (Ss['n'], Ss['t'][0], any('left out at the start' in n for n in Ss['notes'])), (193, float(quarters[10]), True))

# ---- cointegration: Johansen, VECM, Engle-Granger on the log levels --------------------------------------
loglev_df = np.log(md[NAMES])
J = call('multits.johansen', **base, det_order=0, k_ar_diff=2)
jr = coint_johansen(loglev_df.to_numpy(), 0, 2)
check('Johansen: no error, no complex-number noise', (J.get('error'), J.get('warnings')), (None, None))
check('trace and max-eigenvalue statistics are coint_johansen\'s (on the levels, even with Difference on)',
      close([r['trace'] for r in J['rows']], jr.lr1, rtol=1e-12) and close([r['maxeig'] for r in J['rows']], jr.lr2, rtol=1e-12), True)
check('... the eigenvalues', close([r['eig'] for r in J['rows']], np.real(jr.eig), rtol=1e-12), True)
check('... the critical values', close([[r['trace90'], r['trace95'], r['trace99']] for r in J['rows']], jr.cvt, rtol=0) and
      close([[r['max90'], r['max95'], r['max99']] for r in J['rows']], jr.cvm, rtol=0), True)
check('the rank select_coint_rank chooses (trace, 5%)', J['rank'], int(select_coint_rank(loglev_df.to_numpy(), 0, 2).rank))
Jm = call('multits.johansen', **base, det_order=0, k_ar_diff=2, method='maxeig', alpha=0.1)
check('... by the maximum eigenvalue at 10%', Jm['rank'], int(select_coint_rank(loglev_df.to_numpy(), 0, 2, method='maxeig', signif=0.1).rank))
Ja = call('multits.johansen', **base, det_order=0, k_ar_diff=2, alpha=0.02)
check('an alpha between the tabulated levels takes the nearest, with a note', (Ja['signif'], bool(Ja['notes'])), (0.01, True))
# MacKinnon, Haug and Michelis (1999) 5% critical values (as EViews prints them), by n - r = 1, 2, 3
MHM = {0: {'trace': [3.841466, 15.49471, 29.79707], 'max': [3.841466, 14.26460, 21.13162]},
       -1: {'trace': [4.129906, 12.32090, 24.27596], 'max': [4.129906, 11.22480, 17.79730]},
       1: {'trace': [3.841466, 18.39771]}}
for det, parts in MHM.items():
    Jd = call('multits.johansen', **base, det_order=det, k_ar_diff=1)
    for key, vals in parts.items():
        col = 'trace95' if key == 'trace' else 'max95'
        got = [Jd['rows'][3 - m][col] for m in range(1, len(vals) + 1)]
        check(f'det_order {det}: {key} 5% critical values as MacKinnon, Haug and Michelis (1999)', close(got, vals, rtol=1.2e-4), True)
check('with a constant, the last trace test is chi-square(1) in the limit', close([J['rows'][2]['trace90'], J['rows'][2]['trace95'], J['rows'][2]['trace99']],
      stats.chi2.ppf([0.9, 0.95, 0.99], 1), rtol=2e-5), True)
check('det_order 2 is refused', 'error' in call('multits.johansen', **base, det_order=2), True)

E = call('multits.vecm', **base, rank=1, k_ar_diff=2, deterministic='co', h=5)
check('VECM: no error', E.get('error'), None)
rv = VECM(loglev_df.reset_index(drop=True), k_ar_diff=2, coint_rank=1, deterministic='co').fit()
check('alpha (loadings) are VECM\'s', close([r['estimate'] for r in E['alpha']], rv.alpha.ravel(), rtol=1e-10), True)
check('... with their standard errors', close([r['se'] for r in E['alpha']], rv.stderr_alpha.ravel(), rtol=1e-10), True)
check('beta normalised: the first entry 1, not estimated', (E['beta'][0]['estimate'], E['beta'][0]['se']), (1.0, None))
check('beta\'s other entries and standard errors are VECM\'s', close([r['estimate'] for r in E['beta'][1:]], rv.beta.ravel()[1:], rtol=1e-10) and
      close([r['se'] for r in E['beta'][1:]], rv.stderr_beta.ravel()[1:], rtol=1e-10), True)
check('Gamma (short-run) are VECM\'s', close([[r['estimate'] for r in g['rows']] for g in E['gamma']], rv.gamma, rtol=1e-10), True)
check('... named by lag', [r['term'] for r in E['gamma'][0]['rows']][:4], ['Δrealgdp(t−1)', 'Δrealcons(t−1)', 'Δrealinv(t−1)', 'Δrealgdp(t−2)'])
check('the constant outside the relation', close([r['estimate'] for r in E['det']], rv.det_coef.ravel(), rtol=1e-10), True)
check.near('log likelihood (real)', E['llf'], float(np.real(rv.llf)))
fc_v, lo_v, hi_v = rv.predict(steps=5, alpha=0.05)
check('VECM forecasts, back in the units of the table', close(np.array(E['forecast']['mean']).T, np.exp(fc_v), rtol=1e-10) and
      close(np.array(E['forecast']['lower']).T, np.exp(lo_v), rtol=1e-10), True)
Eci = call('multits.vecm', **base, rank=1, k_ar_diff=2, deterministic='ci')
rci = VECM(loglev_df.reset_index(drop=True), k_ar_diff=2, coint_rank=1, deterministic='ci').fit()
check('a constant in the cointegrating relation shows as a row of beta', (Eci['beta'][-1]['variable'], round(Eci['beta'][-1]['estimate'], 10)),
      ('Constant', round(float(rci.det_coef_coint[0, 0]), 10)))
E2 = call('multits.vecm', **base, rank=2, k_ar_diff=1, deterministic='colo')
r2v = VECM(loglev_df.reset_index(drop=True), k_ar_diff=1, coint_rank=2, deterministic='colo').fit()
check('rank 2: beta\'s first two rows the identity', close([[r['estimate'] for r in E2['beta'] if r['relation'] == ec] for ec in ('ec1', 'ec2')], r2v.beta.T, rtol=1e-9, atol=1e-12), True)
check('rank 0 or k is refused', ('error' in call('multits.vecm', **base, rank=0), 'error' in call('multits.vecm', **base, rank=3)), (True, True))

EG = call('multits.engle_granger', **base)
check('Engle-Granger: every series on the others', [r['dependent'] for r in EG['rows']], NAMES)
t0, p0, c0 = coint(loglev_df['realgdp'], loglev_df[['realcons', 'realinv']], trend='c', autolag='aic')
check('... coint\'s statistic, p-value and critical values', (round(EG['rows'][0]['stat'], 10), round(EG['rows'][0]['p'], 10), close([EG['rows'][0][k] for k in ('c1', 'c5', 'c10')], c0)),
      (round(float(t0), 10), round(float(p0), 10), True))
EG2 = call('multits.engle_granger', table=tid, y=['realgdp', 'realcons'], time='quarter', log=True)
T = len(md) - 1
MACKINNON_N2_C = [(-3.89644, -10.9519, -22.527), (-3.33613, -6.1101, -6.823), (-3.04445, -4.2412, -2.720)]   # 1%, 5%, 10% (Table 2)
want = [b0 + b1 / T + b2 / T ** 2 for b0, b1, b2 in MACKINNON_N2_C]
got = [EG2['rows'][0][k] for k in ('c1', 'c5', 'c10')]
check('two series: the 5% and 10% critical values of MacKinnon (2010, Table 2, N = 2, constant)', close(got[1:], want[1:], rtol=1e-12), True)
check.near("... the 1% one differs by 11/T²: statsmodels 0.14.6 has β2 = −33.527 where the paper prints −22.527", got[0] - want[0], -11 / T ** 2, rel=1e-6)

# ---- a simulated VAR(2) and a cointegrated pair -------------------------------------------------------
rng = np.random.default_rng(20260926)
A1 = np.array([[0.45, 0.00, -0.25], [0.20, 0.55, 0.00], [0.10, 0.35, 0.60]])
A2 = np.array([[0.15, 0.00, 0.00], [0.00, 0.15, 0.00], [0.00, 0.00, 0.10]])
mu = np.array([2.5, 2.0, 4.0])
C = np.linalg.cholesky(np.array([[0.64, 0.096, 0.0], [0.096, 0.16, 0.048], [0.0, 0.048, 0.09]]))
n = 400
x = np.zeros((n + 50, 3))
for t in range(2, n + 50):
    x[t] = A1 @ x[t - 1] + A2 @ x[t - 2] + C @ rng.normal(size=3)
x = x[50:] + mu
inc = 100 + np.cumsum(0.5 + rng.normal(0, 1.0, n))
wv = np.zeros(n)
for t in range(1, n):
    wv[t] = 0.7 * wv[t - 1] + rng.normal(0, 0.8)
cons = 10 + 0.8 * inc + wv
sim = table({'growth': x[:, 0].tolist(), 'inflation': x[:, 1].tolist(), 'interest rate': x[:, 2].tolist(), 'income': inc.tolist(), 'consumption': cons.tolist()})
SIM = ['growth', 'inflation', 'interest rate']
Ls = call('multits.select_order', table=sim, y=SIM, maxlags=8)
check('simulated VAR(2): AIC picks 2', Ls['selected']['aic'], 2)
Vs = call('multits.var', table=sim, y=SIM, p=2)
est = np.array([[r['estimate'] for r in e['rows']] for e in Vs['equations']])
se_ = np.array([[r['se'] for r in e['rows']] for e in Vs['equations']])
truth = np.column_stack([mu - (A1 + A2) @ mu, A1, A2])
check('the true coefficients are within 4 standard errors', bool(np.all(np.abs(est - truth) < 4 * se_)), True)
check('a name with a space: interest rate(t−1)', [r['term'] for r in Vs['equations'][0]['rows']][3], 'interest rate(t−1)')
Gs = call('multits.granger', table=sim, y=SIM, p=2)
M = np.array([[np.nan if v is None else v for v in row] for row in Gs['matrix']])
check('the strong causal links are found (p < 0.001): growth → inflation, inflation → interest rate',
      (bool(M[0, 1] < 1e-3), bool(M[1, 2] < 1e-3)), (True, True))
check('... and inflation does not cause growth at 1% (no such link)', bool(M[1, 0] > 0.01), True)
Js = call('multits.johansen', table=sim, y=['income', 'consumption'], det_order=0, k_ar_diff=1)
check('the cointegrated pair: Johansen finds rank 1', Js['rank'], 1)
EGs = call('multits.engle_granger', table=sim, y=['consumption', 'income'])
check('... Engle-Granger rejects no cointegration', EGs['rows'][0]['p'] < 0.01, True)
Es = call('multits.vecm', table=sim, y=['consumption', 'income'], rank=1, k_ar_diff=1)
check('... the VECM\'s beta is near (1, −0.8)', abs(Es['beta'][1]['estimate'] + 0.8) < 0.05, True)

# ---- trends without a constant, numeric Time IDs -----------------------------------------------------------
Ln = call('multits.select_order', table=sim, y=SIM, maxlags=6, trend='n')
ref_n = VAR(pd.DataFrame(x, columns=SIM)).select_order(6, trend='n')
check("trend 'n': the table starts at lag 1, as select_order does (a VAR(0) has nothing to fit)", (Ln['rows'][0]['lag'], len(Ln['rows'])), (1, 6))
check('... with select_order\'s criteria', close([[r[c] for c in ('aic', 'bic', 'hqic', 'fpe')] for r in Ln['rows']], np.column_stack([ref_n.ics[c] for c in ('aic', 'bic', 'hqic', 'fpe')]), rtol=1e-12), True)
check('... and its choice', Ln['selected'], {c: int(v) for c, v in ref_n.selected_orders.items()})
yr = table({'year': (1900 + np.arange(400) * 0.25).tolist(), **{c: x[:, i].tolist() for i, c in enumerate(SIM)}})
Fy = call('multits.forecast', table=yr, y=SIM, time='year', p=2, h=3)
check('a numeric Time ID: the forecasts continue its step', Fy['t'], [2000.0, 2000.25, 2000.5])
Vy = call('multits.var', table=yr, y=SIM, time='year', p=2)
one = call('multits.series', table=table({'a': [None if i == 50 else v for i, v in enumerate(x[:, 0])], 'b': x[:, 1].tolist()}), y=['a', 'b'])
check('one missing cell inside: filled, and said so in the singular', any('1 missing value inside the span (excluded rows, missing cells, dates with no row) was filled' in n_ for n_ in one['notes']), True)

# ---- errors -------------------------------------------------------------------------------------------------
check('one series is an error', 'error' in call('multits.var', table=sim, y=['growth'], p=1), True)
check('too many lags for the data is an error', 'error' in call('multits.var', table=sim, y=SIM, rows=list(range(20)), p=6), True)
neg = table({'a': (x[:, 0] - 3).tolist(), 'b': x[:, 1].tolist()})
check('log of values at or below zero is an error', 'above zero' in call('multits.series', table=neg, y=['a', 'b'], log=True).get('error', ''), True)
check('lag 0 is refused (a VAR(0) has no dynamics)', 'error' in call('multits.var', table=sim, y=SIM, p=0), True)
flat = table({'a': x[:, 0].tolist(), 'c': [1.0] * 400})
check('a series that does not vary is an error, said plainly', call('multits.var', table=flat, y=['a', 'c'], p=1).get('error', ''), 'c does not vary over these rows: every series of a VAR must')
lin = table({'a': x[:, 0].tolist(), 'c': np.arange(400.0).tolist()})
check('... also when the difference makes it constant', 'after differencing' in call('multits.var', table=lin, y=['a', 'c'], diff=True, p=1).get('error', ''), True)
check('... and an exogenous column that does not vary', 'second constant' in call('multits.var', table=table({'a': x[:, 0].tolist(), 'b': x[:, 1].tolist(), 'z': [2.0] * 400}), y=['a', 'b'], exog=['z'], p=1).get('error', ''), True)
check('rows=None is every row', call('multits.series', table=sim, y=SIM, rows=None)['n'], 400)
Sb = call('multits.series', table=sim, y=SIM, rows=list(range(100, 300)))
check('a subset of rows (a By group)', (Sb['n'], Sb['rows'][0]), (200, 100))

# ---- the code under each result runs on a CSV export of the table -------------------------------------


def run_code(code, frame):
    with tempfile.TemporaryDirectory() as tmp:
        frame.to_csv(os.path.join(tmp, 'data.csv'), index=False)
        cwd = os.getcwd()
        os.chdir(tmp)
        ns = {}
        try:
            with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter('ignore')
                exec(code, ns)
        except Exception as ex:  # reported as a failed check
            ns['error'] = f'{type(ex).__name__}: {ex}'
        finally:
            os.chdir(cwd)
    return ns


csv = pd.DataFrame({'quarter': [pd.Timestamp(v, unit='ms').strftime('%Y-%m-%d') for v in quarters], **{c: md[c] for c in NAMES}, 'infl': md['infl']})
for label, res_ in [('series', S), ('lag order', L), ('Granger', G), ('Johansen', J), ('Engle-Granger', EG)]:
    check(f'the {label} code runs', run_code(res_['code'], csv).get('error'), None)
ns = run_code(L['code'], csv)
check('the lag order code gives the same choices', ns.get('error') or {k: int(v) for k, v in ns['sel'].selected_orders.items()}, L['selected'])
ns = run_code(V['code'], csv)
check('the VAR code gives the same fit', ns.get('error') or close(ns['res'].params.T, [[r['estimate'] for r in e['rows']] for e in V['equations']], rtol=1e-10), True)
ns = run_code(G['code'], csv)
check('the Granger code gives the same p-values', ns.get('error') or abs(float(ns['res'].test_causality('realgdp', ['realcons', 'realinv']).pvalue) - allg['p']) < 1e-15, True)
ns = run_code(I['code'], csv)
check('the impulse response code gives the same responses and bands', ns.get('error') or (close(ns['resp'], I['values'], rtol=1e-10) and close(ns['lower'], I['lower'], rtol=1e-10)), True)
ns = run_code(Im['code'], csv)
check('the Monte Carlo code gives the same bands', ns.get('error') or close(ns['lower'], Im['lower'], rtol=1e-12), True)
ns = run_code(Io['code'], csv)
check('the reordered impulse response code gives the same responses', ns.get('error') or close(ns['resp'], Io['values'], rtol=1e-10), True)
ns = run_code(FE['code'], csv)
check('the FEVD code gives the same decomposition', ns.get('error') or close(ns['fevd'].decomp, FE['decomp'], rtol=1e-10), True)
ns = run_code(F['code'], csv)
check('the forecast code gives the same forecasts and limits', ns.get('error') or (close(ns['mean'].T, F['transformed']['mean'], rtol=1e-10)
      and close(ns['level'].T, orig['mean'], rtol=1e-10) and close(ns['lower_level'].T, orig['lower'], rtol=1e-10)), True)
ns = run_code(Fx['code'], pd.DataFrame({'quarter': [pd.Timestamp(v, unit='ms').strftime('%Y-%m-%d') for v in quarters + [ms('2009-10-01'), ms('2010-01-01')]],
                                        **{c: md[c].tolist() + [None, None] for c in NAMES}, 'infl': md['infl'].tolist() + [1.5, 2.5]}))
check('the forecast code with an exogenous column gives the same forecasts', ns.get('error') or close(ns['mean'].T, Fx['transformed']['mean'], rtol=1e-10), True)
ns = run_code(E['code'], csv)
check('the VECM code gives the same fit and forecasts', ns.get('error') or (close(ns['res'].beta.ravel(), [r['estimate'] for r in E['beta']], rtol=1e-10)
      and close(ns['fc'].T, E['forecast']['mean'], rtol=1e-10)), True)
ns = run_code(J['code'], csv)
check('the Johansen code gives the same statistics', ns.get('error') or close(ns['jr'].lr1, [r['trace'] for r in J['rows']], rtol=1e-12), True)
ns = run_code(Vi['code'], csv)
check('the code sets the excluded rows missing and fills them', ns.get('error') or close(ns['res'].params.T, [[r['estimate'] for r in e['rows']] for e in Vi['equations']], rtol=1e-10), True)
gap_csv = pd.DataFrame({'quarter': [pd.Timestamp(quarters[k], unit='ms').strftime('%Y-%m-%d') for k in keep], **{c: [md[c][k] for k in keep] for c in NAMES}})
Vg = call('multits.var', table=tid_gap, y=NAMES, time='quarter', p=2)
ns = run_code(Vg['code'], gap_csv)
check('the code inserts the missing quarters and fills them', ns.get('error') or close(ns['res'].params.T, [[r['estimate'] for r in e['rows']] for e in Vg['equations']], rtol=1e-10), True)
ns = run_code(Vx['code'], csv)
check('the code with an exogenous column gives the same fit', ns.get('error') or close(ns['res'].params.T, [[r['estimate'] for r in e['rows']] for e in Vx['equations']], rtol=1e-10), True)
# a By group, without a Time ID: the rows of the group in table order
by_tid = table({'region': ['N'] * 200 + ['S'] * 200, 'growth': x[:, 0].tolist(), 'inflation': x[:, 1].tolist(), 'interest rate': x[:, 2].tolist()})
Vb = call('multits.var', table=by_tid, y=SIM, rows=list(range(200, 400)), where=[{'column': 'region', 'value': 'S'}], p=2, table_name='T')
by_csv = pd.DataFrame({'region': ['N'] * 200 + ['S'] * 200, 'growth': x[:, 0], 'inflation': x[:, 1], 'interest rate': x[:, 2]})
check('the By group is in the code', 'df = df[df["region"] == \'S\']' in Vb['code'] and 'pd.read_csv("T.csv")' in Vb['code'], True)
ns = run_code(Vb['code'].replace('T.csv', 'data.csv'), by_csv)
check('... and gives the group\'s fit', ns.get('error') or close(ns['res'].params.T, [[r['estimate'] for r in e['rows']] for e in Vb['equations']], rtol=1e-10), True)
ns = run_code(Vy['code'], pd.DataFrame({'year': 1900 + np.arange(400) * 0.25, **{c: x[:, i] for i, c in enumerate(SIM)}}))
check('the code with a numeric Time ID gives the same fit', ns.get('error') or close(ns['res'].params.T, [[r['estimate'] for r in e['rows']] for e in Vy['equations']], rtol=1e-10), True)
check('every result has its code', all(bool(r_.get('code')) for r_ in (S, L, V, G, I, FE, F, J, E, EG)), True)
sys.exit(check.done())
