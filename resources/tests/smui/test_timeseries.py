#!/usr/bin/env python3
"""Analyze > Specialized Modeling > Time Series's backend
(resources/py/smui/timeseries.py), checked against statsmodels called
directly and against published values:

  the ADF critical values of MacKinnon (2010, Table 2), the critical values of
  Fisher's g test (Fisher 1929, as tabulated by Davis 1941 and Wei 2006), the
  ETS forecast variances of Hyndman et al. (2008, Table 6.1), and the ARIMA
  fits of the sunspot numbers in statsmodels' documentation ("Autoregressive
  Moving Average (ARMA): Sunspots data"), with the data read from
  statsmodels.datasets at run time;

  and for what JMP does not have: Durbin and Koopman's (2012) local level
  model of the Nile, KFAS's structural models of US unemployment (bundled
  with statsmodels' tests), Hamilton's (1989) Markov switching model of US
  GNP as E-views estimates it, Stata's switching mean of the fed funds rate
  (its smoothed probabilities and predictions), the Hodrick-Prescott filter
  by its closed form, the Baxter-King weights and Christiano and
  Fitzgerald's formula, statsmodels' month_plot and quarter_plot drawings,
  the theta method's IMA(1, 1) forecast variance (against SARIMAX) and
  Hyndman and Billah's drift, Zivot and Andrews' (1992) real GNP break and
  critical values, statsmodels' ARDL example (Danish money demand: the
  selected order, the UECM, the cointegrating vector, the bounds tests) and
  the bounds of Pesaran, Shin and Smith (2001, Table CI(iii)).

  Forecast on Holdback (every model fitted on the training values by
  statsmodels directly, the holdback statistics by hand, the shown code on a
  CSV), the Naive, Seasonal Naive and Drift benchmarks (SARIMAX and OLS on
  the differences, the forecast package's rwf standard errors), the Simple
  Moving Average (np.convolve, pandas' rolling and seasonal_decompose's
  2 x w trend), JMP's Custom constraints (holtwinters' fix_params and
  bounds, a search over alpha by hand), Box-Cox (holtwinters' use_boxcox,
  the Jacobian), the multiplicative trends (ETSModel(trend='mul')), the
  averaged forecast, the runs test (the closed form and runstest_1samp, and
  its correction slip), rolling-origin cross-validation (every origin by
  hand), and Time Series Forecast (every candidate's AICc, BIC and holdback
  RMSE by ETSModel directly, stacked data, the shown code on a CSV).

The other series are simulated here from a fixed seed.

    python3 resources/tests/smui/test_timeseries.py
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
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.exponential_smoothing.ets import ETSModel
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.seasonal import STL, seasonal_decompose
from statsmodels.tsa.statespace.tools import diff
from statsmodels.tsa.stattools import acf, adfuller, ccf, kpss, pacf

from backend import FAILED, Checks, call, table
from smui import data
from smui import timeseries as ts

warnings.simplefilter('ignore', DeprecationWarning)
warnings.simplefilter('ignore', FutureWarning)
check = Checks()
check('the module imports', FAILED.get('timeseries'), None)


def date_table(cols, date_cols=('month',)):
    tid = table(cols)
    for c in date_cols:
        if c in cols:
            data.TABLES[tid]['meta'][c]['format'] = {'kind': 'date'}
    return tid


def ms(d):
    return int((pd.Timestamp(d) - pd.Timestamp(0)) // pd.Timedelta(milliseconds=1))


# ---- a monthly series like the page's Monthly sales example ---------------------
rng = np.random.default_rng(20260926)
n = 120
e, y, promo, temp = 0.0, [], [], []
for i in range(n):
    p = 1.0 if rng.uniform() < 0.15 else 0.0
    e = 0.6 * e + rng.normal(0, 4)
    season = 12 * np.sin(2 * np.pi * (i % 12) / 12) + 5 * np.cos(4 * np.pi * (i % 12) / 12)
    y.append(100 + 0.6 * i + season + 9 * p + e)
    promo.append(p)
    temp.append(8 + 10 * np.sin(2 * np.pi * ((i % 12) - 3) / 12) + rng.normal(0, 1.5))
y = np.array(y)
months = [ms(f'{2016 + i // 12}-{i % 12 + 1:02d}-01') for i in range(n)]
tid = date_table({'month': months, 'sales': y, 'promotion': promo, 'temperature': temp})

r = call('timeseries.series', table=tid, y='sales', time='month', nlags=25)
check('series: no error', r.get('error'), None)
check('a date Time ID is monthly (pandas.infer_freq)', (r['kind'], r['freq'], r['period_auto']), ('date', 'MS', 12))
check('the time axis is epoch milliseconds', r['t'][:2], [float(months[0]), float(months[1])])
check('rows are the table rows', r['rows'][:3], [0, 1, 2])
d = r['diag']
check.near('Mean', d['mean'], float(np.mean(y)))
check.near('SD (n - 1)', d['sd'], float(np.std(y, ddof=1)))
check('N and the number of lags', (d['n'], d['K']), (120, 25))
ref = acf(y, nlags=25, fft=False)
check('AutoCorr is statsmodels acf', np.allclose(d['acf']['r'], ref, rtol=0, atol=1e-12), True)
_, ci = acf(y, nlags=25, fft=False, alpha=0.05)
check('±2 standard errors: Bartlett, as acf(alpha) has them', np.allclose(d['acf']['se'][1:], (ci[1:, 1] - ref[1:]) / 1.959963984540054, atol=1e-12), True)
lb = acorr_ljungbox(y, lags=25, return_df=True)
check('Ljung-Box Q is acorr_ljungbox', np.allclose(d['acf']['q'][1:], lb['lb_stat'], rtol=1e-12), True)
check('Ljung-Box p-Value', np.allclose(d['acf']['p'][1:], lb['lb_pvalue'], rtol=1e-9, atol=1e-300), True)
check('Partial is pacf by Levinson-Durbin (method ldb)', np.allclose(d['pacf']['r'], pacf(y, nlags=25, method='ldb'), atol=1e-12), True)
check.near('the partial autocorrelation standard error is 1/sqrt(N)', d['pacf']['se'][3], 1 / math.sqrt(120))
check('Variogram (1 - r_k)/(1 - r_1)', np.allclose(d['variogram']['v'], (1 - ref[1:]) / (1 - ref[1]), atol=1e-12), True)
yw, _ = sm.regression.yule_walker(y, order=25, method='mle')
check('AR Coefficients are the Yule-Walker AR(25) fit', np.allclose(d['ar']['coef'], yw, atol=1e-8), True)

# ADF and KPSS, and the ADF critical values against MacKinnon (2010), Table 2
st = r['stationarity']
for row in st['adf']:
    ref_adf = adfuller(y, regression=row['regression'], autolag='AIC')
    check.near(f'{row["test"]} tau', row['stat'], float(ref_adf[0]))
    check.near(f'{row["test"]} p (MacKinnon)', row['p'], float(ref_adf[1]))
    check(f'{row["test"]} lags by AIC', row['lags'], int(ref_adf[2]))
MACKINNON_2010 = {  # tau, N = 1: beta_inf, beta_1, beta_2, beta_3 for 1%, 5%, 10%
    'n': [(-2.56574, -2.2358, -3.627, 0), (-1.94100, -0.2686, -3.365, 31.223), (-1.61682, 0.2656, -2.714, 25.364)],
    'c': [(-3.43035, -6.5393, -16.786, -79.433), (-2.86154, -2.8903, -4.234, -40.040), (-2.56677, -1.5384, -2.809, 0)],
    'ct': [(-3.95877, -9.0531, -28.428, -134.155), (-3.41049, -4.3904, -9.036, -45.374), (-3.12705, -2.5856, -3.925, -22.380)],
}
for row in st['adf']:
    T = row['nobs']
    for key, b in zip(('c1', 'c5', 'c10'), MACKINNON_2010[row['regression']]):
        crit = b[0] + b[1] / T + b[2] / T ** 2 + b[3] / T ** 3
        check.near(f'{row["test"]} critical value {key[1:]}% at T = {T} (MacKinnon 2010)', row[key], crit, rel=2e-3)
for row in st['kpss']:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        k_ref = kpss(y, regression=row['regression'], nlags='auto')
    check.near(f'{row["test"]} statistic', row['stat'], float(k_ref[0]))
    check(f'{row["test"]} p-value bound', row['p_bound'] in (None, '<', '>'), True)
check('series code', 'adfuller' in r['code'] and 'asfreq(\'MS\')' in r['code'], True)

# ---- excluded rows count as missing; missing time points are inserted ----------------
r2 = call('timeseries.series', table=tid, y='sales', time='month', excluded=[30, 31, 70])
yx = y.copy()
yx[[30, 31, 70]] = np.nan
check('excluded rows keep their slots', (r2['n'], r2['diag']['n'], r2['excluded_pos']), (120, 117, [30, 31, 70]))
check('... with missing values', [r2['values'][k] for k in (29, 30, 31, 70)], [float(y[29]), None, None, None])
check('ACF over the missing values is acf(missing="conservative")',
      np.allclose(r2['diag']['acf']['r'], acf(yx, nlags=25, fft=False, missing='conservative'), atol=1e-12), True)
keep = [k for k in range(n) if k not in (40, 41, 42)]
tid_gap = date_table({'month': [months[k] for k in keep], 'sales': [y[k] for k in keep]})
r3 = call('timeseries.series', table=tid_gap, y='sales', time='month')
check('three months with no row: the frequency is still monthly', (r3['freq'], r3['n'], r3['inserted']), ('MS', 120, 3))
check('... the gap is missing, with no row', (r3['values'][41], r3['rows'][41], r3['rows'][43]), (None, None, 40))
r4 = call('timeseries.series', table=tid, y='sales', time='month', rows=list(range(0, 60)))
check('a subset of rows', r4['n'], 60)
rnone = call('timeseries.series', table=tid, y='sales', time='month', rows=None)
check('rows=None is every row', rnone['n'], 120)
r5 = call('timeseries.series', table=tid, y='sales')
check('no Time ID: row numbers from 1', (r5['kind'], r5['t'][:3]), ('index', [1.0, 2.0, 3.0]))
check('an all-missing series is an error', 'error' in call('timeseries.series', table=tid, y='sales', rows=[0, 1], excluded=[0, 1]), True)
# By-group code
r6 = call('timeseries.series', table=tid, y='sales', time='month', where=[{'column': 'region', 'value': 'North'}], table_name='T')
check('the By group is in the code', 'df = df[df["region"] == \'North\']' in r6['code'], True)

# weekly data with missing weeks: statsmodels' co2 series
co2 = sm.datasets.co2.load_pandas().data
co2w = co2.iloc[:400]
tid_co2 = table({'week': [ms(t) for t in co2w.index], 'co2': co2w['co2'].tolist()})
data.TABLES[tid_co2]['meta']['week']['format'] = {'kind': 'date'}
rc = call('timeseries.series', table=tid_co2, y='co2', time='week')
check('co2: weekly on Saturdays, period 52', (rc['freq'], rc['period_auto']), ('W-SAT', 52))
check('co2: the missing weeks keep their slots', (rc['n'], rc['diag']['n_missing']), (400, int(co2w['co2'].isna().sum())))

# ---- differencing and decomposition ------------------------------------------------------
rd = call('timeseries.difference', table=tid, y='sales', time='month', d=1, D=1, s=12)
w = diff(y, k_diff=1, k_seasonal_diff=1, seasonal_periods=12)
check('difference (1 - B)(1 - B^12) is statespace.tools.diff', np.allclose([v for v in rd['values'] if v is not None], w), True)
check('... aligned to the last slots', (rd['start'], rd['values'][12], rd['values'][13] is not None), (13, None, True))
check.near('... its ACF', rd['diag']['acf']['r'][1], float(acf(w, nlags=1, fft=False)[1]))
rt_ = call('timeseries.detrend', table=tid, y='sales', time='month')
b1, b0 = np.polyfit(np.arange(1, n + 1), y, 1)
check.near('Remove Linear Trend: slope', rt_['params'][1]['estimate'], float(b1))
check.near('... intercept', rt_['params'][0]['estimate'], float(b0))
tt = np.arange(60)
yc = 5 + 3 * np.cos(2 * np.pi * tt / 12 + 0.7) + np.random.default_rng(1).normal(0, 1e-6, 60)
tid_c = table({'y': yc.tolist()})
rcy = call('timeseries.decycle', table=tid_c, y='y', units=12)
cp = {p['term']: p['estimate'] for p in rcy['params']}
check.near('Remove Cycle: constant', cp['Constant'], 5.0, rel=1e-5)
check.near('... amplitude', cp['Amplitude'], 3.0, rel=1e-5)
check.near('... phase', cp['Phase'], 0.7, rel=1e-5)
rdc = call('timeseries.decompose', table=tid, y='sales', time='month', method='classical', period=12)
sdr = seasonal_decompose(y, model='additive', period=12)
check('seasonal_decompose: seasonal', np.allclose(rdc['seasonal'], sdr.seasonal), True)
check('... trend (missing at the ends)', (rdc['trend'][0], np.allclose(rdc['trend'][6:-6], sdr.trend[6:-6])), (None, True))
rst = call('timeseries.decompose', table=tid, y='sales', time='month', method='stl', period=12, robust=True)
stl = STL(y, period=12, robust=True).fit()
check('STL: trend, seasonal and remainder', np.allclose(rst['trend'], stl.trend) and np.allclose(rst['seasonal'], stl.seasonal) and np.allclose(rst['resid'], stl.resid), True)
check('multiplicative needs positive values', 'error' in call('timeseries.decompose', table=table({'y': (y - 200).tolist()}), y='y', model='multiplicative', period=12), True)

# ---- the spectral density and the white noise tests ------------------------------------------
rs = call('timeseries.spectral', table=tid, y='sales', time='month')
N = n
tt = np.arange(1, N + 1)
f3 = 3 / N
a3 = 2 / N * np.sum(y * np.cos(2 * np.pi * f3 * tt))
b3 = 2 / N * np.sum(y * np.sin(2 * np.pi * f3 * tt))
check.near('periodogram I(3/N) = N/2 (a^2 + b^2), the least squares Fourier coefficients', rs['periodogram'][2], N / 2 * (a3 ** 2 + b3 ** 2), rel=1e-9)
check.near('... the cosine and sine coefficients (JMP\'s table)', rs['sine'][3], a3, rel=1e-9)
check('q = N/2 frequencies', (rs['q'], len(rs['frequency'])), (60, 60))
Iq = np.array(rs['periodogram'])
check.near("Fisher's kappa = q max I / sum I", rs['kappa'], 60 * Iq.max() / Iq.sum())
for q, g in [(5, 0.68377), (6, 0.61615), (7, 0.56115), (10, 0.44495), (15, 0.33462), (20, 0.27040), (25, 0.22805), (30, 0.19784), (40, 0.15738), (50, 0.13135)]:
    check.near(f"Prob > Kappa at Fisher's 5% critical value g = {g}, q = {q}", ts.fisher_kappa_p(q * g, q), 0.05, abs_=2e-4)
U = np.cumsum(Iq) / Iq.sum()
check.near("Bartlett's Kolmogorov-Smirnov statistic", rs['bartlett'], float(np.max(np.abs(U - np.arange(1, 61) / 60))))
wn = np.random.default_rng(5)
rej = 0
for _ in range(400):
    v = wn.normal(size=64)
    I = np.abs(np.fft.fft(v)) ** 2 / 32
    Iv = I[1:33]
    rej += ts.fisher_kappa_p(32 * Iv.max() / Iv.sum(), 32) < 0.05
check("white noise: Fisher's kappa rejects about 5% of the time", 0.02 < rej / 400 < 0.09, True)

# ---- cross correlation -------------------------------------------------------------------------
rx = call('timeseries.ccf', table=tid, y='sales', inputs=['temperature'], time='month', nlags=10)
cc = rx['inputs'][0]
check('lags -K..K', (cc['lag'][0], cc['lag'][-1]), (-10, 10))
check('positive lags are ccf(y, x)', np.allclose(cc['r'][10:], ccf(y, np.array(temp), adjusted=False, fft=False)[:11]), True)
check('negative lags are ccf(x, y)', np.allclose(cc['r'][:10][::-1], ccf(np.array(temp), y, adjusted=False, fft=False)[1:11]), True)
check.near('cross correlation standard error 1/sqrt(n - |k|)', cc['se'][0], 1 / math.sqrt(110))

# ---- ARIMA: the sunspot numbers of statsmodels' documentation -----------------------------------
sun = sm.datasets.sunspots.load_pandas().data
tid_sun = table({'YEAR': sun['YEAR'].tolist(), 'SUNACTIVITY': sun['SUNACTIVITY'].tolist()})
m = call('timeseries.arima', table=tid_sun, y='SUNACTIVITY', time='YEAR', p=2, h=5)
check('AR(2): no error', m.get('error'), None)
check("JMP's name", m['name'], 'AR(2)')
est = {p['term']: p['estimate'] for p in m['params']['rows']}
DOC = {'Intercept': 49.746198, 'AR1': 1.390633, 'AR2': -0.688573}   # the documented fit: const, ar.L1, ar.L2
for k_, v in DOC.items():
    check.near(f'sunspots AR(2) {k_} as documented', est[k_], v, rel=2e-6)
check.near('sunspots AR(2) statsmodels AIC as documented', m['sm']['aic'], 2622.637093, rel=1e-8)
check.near('sunspots AR(2) statsmodels BIC as documented', m['sm']['bic'], 2637.570458, rel=1e-8)
check.near('AIC in JMP\'s count (k = 3, the variance not counted)', m['stats']['aic'], 2622.637093 - 2, rel=1e-8)
check.near('SBC = -2LL + k ln n', m['stats']['sbc'], m['stats']['m2ll'] + 3 * math.log(309), rel=1e-12)
check.near('Constant Estimate = mu (1 - phi1 - phi2)', m['constant']['estimate'], 49.746198 * (1 - 1.390633 + 0.688573), rel=1e-5)
m3 = call('timeseries.arima', table=tid_sun, y='SUNACTIVITY', time='YEAR', p=3)
est3 = {p['term']: p['estimate'] for p in m3['params']['rows']}
for k_, v in {'Intercept': 49.751911, 'AR1': 1.300818, 'AR2': -0.508102, 'AR3': -0.129644}.items():
    check.near(f'sunspots AR(3) {k_} as documented', est3[k_], v, rel=5e-6)
check.near('sunspots AR(3) statsmodels AIC as documented', m3['sm']['aic'], 2619.403629, rel=1e-8)
ref_sun = ARIMA(sun['SUNACTIVITY'].to_numpy(), order=(2, 0, 0)).fit()
fc = ref_sun.get_forecast(5)
check('forecasts are get_forecast', np.allclose(m['forecast']['mean'], fc.predicted_mean, rtol=1e-7), True)
check('... and the prediction limits', np.allclose(m['forecast']['lower'], fc.conf_int(alpha=0.05)[:, 0], rtol=1e-7), True)
check('the forecast years continue the Time ID', m['forecast']['t'][:2], [2009.0, 2010.0])
check('one-step-ahead residuals are statsmodels\'', np.allclose([v for v in m['resid'] if v is not None], ref_sun.resid, rtol=1e-6, atol=1e-6), True)
check('Stable and invertible', (m['stable'], m['invertible']), (True, True))
t_ratio = est['AR1'] / [p['se'] for p in m['params']['rows'] if p['term'] == 'AR1'][0]
check.near('t Ratio', [p['t'] for p in m['params']['rows'] if p['term'] == 'AR1'][0], t_ratio)
check('the iteration history ends near the optimum', abs(m['iterations'][-1]['m2ll'] - m['stats']['m2ll']) < 1e-3, True)
check('residual Ljung-Box leaves out the ARMA terms (model_df = 2)', (m['resid_diag']['model_df'], m['resid_diag']['acf']['p'][2]), (2, None))

# JMP differences first, then fits: the mean of the differenced series is mu
m11 = call('timeseries.arima', table=tid, y='sales', time='month', p=1, d=1, h=3)
dy = np.diff(y)
ref11 = ARIMA(dy, order=(1, 0, 0), trend='c').fit()
e11 = {p['term']: p['estimate'] for p in m11['params']['rows']}
check("ARI(1, 1)'s name", m11['name'], 'ARI(1, 1)')
check.near('ARI(1, 1): mu is the mean of the differences (ARIMA on the differenced series)', e11['Intercept'], float(ref11.params[0]), rel=2e-3)
check.near('ARI(1, 1): AR1 as on the differenced series', e11['AR1'], float(ref11.params[1]), rel=5e-3)
check.near('-2LogLikelihood: the diffuse likelihood is that of the differences', m11['stats']['m2ll'], -2 * float(ref11.llf), rel=1e-4)
check('n after differencing', m11['stats']['n'], 119)
ms_ = call('timeseries.arima', table=tid, y='sales', time='month', p=1, D=1, Q=1, s=12, h=12)
check("seasonal ARIMA's name", ms_['name'], 'Seasonal ARIMA(1, 0, 0)(0, 1, 1)12')
terms = [p['term'] for p in ms_['params']['rows']]
check('seasonal terms: factor 2 at lag 12', terms, ['Intercept', 'AR1,1', 'MA2,12'])
ref_s = ARIMA(y, order=(1, 0, 0), seasonal_order=(0, 1, 1, 12), trend=[0, 1]).fit(method_kwargs={'maxiter': 200})
check.near('seasonal mu = 12 x the trend coefficient', ms_['params']['rows'][0]['estimate'], 12 * float(ref_s.params[0]), rel=1e-5)
check('seasonal forecasts', np.allclose(ms_['forecast']['mean'], ref_s.get_forecast(12).predicted_mean, rtol=1e-6), True)
check('the forecast months continue the dates', (ms_['forecast']['t'][0], ms_['forecast']['t'][11]), (float(ms('2026-01-01')), float(ms('2026-12-01'))))
mi = call('timeseries.arima', table=tid, y='sales', time='month', p=1, excluded=[50, 51])
check('ARIMA skips excluded rows as missing values (the Kalman filter)', (mi.get('error'), mi['stats']['n'], mi['resid'][50]), (None, 118, None))
check('too many parameters for the data is an error', 'error' in call('timeseries.arima', table=tid, y='sales', rows=list(range(8)), p=3, q=3), True)

# transfer function: regression with ARIMA errors
mt = call('timeseries.arima', table=tid, y='sales', time='month', p=1, h=3, inputs=[{'name': 'promotion'}, {'name': 'temperature'}])
X = pd.DataFrame({'promotion': promo, 'temperature': temp})
ref_t = ARIMA(pd.Series(y, name='sales'), exog=X, order=(1, 0, 0), trend='c').fit(method_kwargs={'maxiter': 200})
et = {p['term']: p['estimate'] for p in mt['params']['rows']}
check.near('transfer function: promotion coefficient is ARIMA(exog)\'s', et['promotion'], float(ref_t.params['promotion']), rel=1e-5)
check.near('... temperature', et['temperature'], float(ref_t.params['temperature']), rel=1e-5)
check('... no future inputs in the table: the last value is held', any('held' in s_ for s_ in mt['notes']), True)
mt2 = call('timeseries.arima', table=tid, y='sales', time='month', p=1, inputs=[{'name': 'temperature', 'lag': 2}])
check('a lagged input drops the first observations', (mt2['stats']['n'], mt2['fitted'][1], mt2['params']['rows'][1]['term']), (118, None, 'temperature(t−2)'))
fut_tid = date_table({'month': months + [ms('2026-01-01'), ms('2026-02-01')], 'sales': list(y) + [None, None], 'promotion': promo + [1, 0]})
mf = call('timeseries.arima', table=fut_tid, y='sales', time='month', p=1, h=2, inputs=[{'name': 'promotion'}])
ref_f = ARIMA(pd.Series(y), exog=pd.DataFrame({'promotion': promo}), order=(1, 0, 0), trend='c').fit()
check('future inputs from the rows after the series', np.allclose(mf['forecast']['mean'], ref_f.get_forecast(2, exog=pd.DataFrame({'promotion': [1.0, 0.0]})).predicted_mean, rtol=1e-5), True)

# ---- smoothing models ------------------------------------------------------------------------------
for method, kw in [('simple', {}), ('linear', {'trend': 'add'}), ('damped', {'trend': 'add', 'damped_trend': True, 'bounds': {'damping_trend': (0.0, 1.0)}}),
                   ('seasonal', {'seasonal': 'add', 'seasonal_periods': 12}), ('winters', {'trend': 'add', 'seasonal': 'add', 'seasonal_periods': 12})]:
    rm = call('timeseries.smooth', table=tid, y='sales', time='month', method=method, s=12, h=12)
    ref_m = ExponentialSmoothing(y, initialization_method='estimated', **kw).fit()
    check(f'{rm["name"]}: fitted values are holtwinters\'', np.allclose(rm['fitted'], ref_m.fittedvalues, rtol=1e-9), True)
    check(f'{rm["name"]}: forecasts', np.allclose(rm['forecast']['mean'], ref_m.forecast(12), rtol=1e-9), True)
    check.near(f'{rm["name"]}: SSE', rm['stats']['sse'], float(ref_m.sse), rel=1e-9)
    check.near(f'{rm["name"]}: -2LogLikelihood of the one-step errors', rm['stats']['m2ll'], 120 * (math.log(2 * math.pi * ref_m.sse / 120) + 1), rel=1e-9)
    if method == 'seasonal':
        dl = [p['estimate'] for p in rm['params']['rows'] if p['term'] == 'Seasonal Smoothing Weight'][0]
        check.near("JMP's seasonal weight delta = statsmodels' gamma / (1 - alpha)", dl * (1 - ref_m.params['smoothing_level']), float(ref_m.params['smoothing_seasonal']), abs_=1e-12)
rb = call('timeseries.smooth', table=tid, y='sales', time='month', method='double', h=6)
a = rb['weights']['alpha']
hb = ExponentialSmoothing(y, trend='add', initialization_method='estimated')
with hb.fix_params({'smoothing_level': a * (2 - a), 'smoothing_trend': a / (2 - a)}):
    href = hb.fit()
check("Brown's method is Holt's with level a(2 - a) and trend a/(2 - a)", np.allclose(rb['fitted'], href.fittedvalues, rtol=1e-9), True)


def sse_brown(a_):
    m_ = ExponentialSmoothing(y, trend='add', initialization_method='estimated')
    with m_.fix_params({'smoothing_level': a_ * (2 - a_), 'smoothing_trend': a_ / (2 - a_)}):
        return m_.fit().sse


check("Brown's alpha minimises the sum of squared errors", rb['stats']['sse'] <= min(sse_brown(a - 0.01), sse_brown(min(0.9999, a + 0.01))) + 1e-6, True)
rwm = call('timeseries.smooth', table=tid, y='sales', time='month', method='winters', s=12, multiplicative=True, h=6)
ref_wm = ExponentialSmoothing(y, trend='add', seasonal='mul', seasonal_periods=12, initialization_method='estimated').fit()
check("Winters multiplicative: holtwinters' forecasts", np.allclose(rwm['forecast']['mean'], ref_wm.forecast(6), rtol=1e-9), True)
rwm2 = call('timeseries.smooth', table=tid, y='sales', time='month', method='winters', s=12, multiplicative=True, h=6)
check('... simulated limits are the same every time (a fixed seed)', rwm['forecast']['lower'], rwm2['forecast']['lower'])
check('a smoothing model with missing values is filled and noted', any('interpolation' in s_ for s_ in call('timeseries.smooth', table=tid, y='sales', method='simple', excluded=[10])['notes']), True)

# The forecast variances against Hyndman et al. (2008), Table 6.1 (class 1),
# with beta = alpha gamma and the seasonal gamma = delta (1 - alpha).
al, ga, de, ph, mper = 0.3, 0.2, 0.25, 0.9, 4
beta, gam = al * ga, de * (1 - al)
H = 12
hh = np.arange(1, H + 1)
kk = np.floor((hh - 1) / mper)
ref_var = {
    'simple': 1 + al ** 2 * (hh - 1),
    'linear': 1 + (hh - 1) * (al ** 2 + al * beta * hh + beta ** 2 * hh * (2 * hh - 1) / 6),
    'seasonal': 1 + al ** 2 * (hh - 1) + gam * kk * (2 * al + gam),
    'winters': 1 + (hh - 1) * (al ** 2 + al * beta * hh + beta ** 2 * hh * (2 * hh - 1) / 6) + gam * kk * (2 * al + gam + beta * mper * (kk + 1)),
    'damped': 1 + al ** 2 * (hh - 1) + beta * ph * hh / (1 - ph) ** 2 * (2 * al * (1 - ph) + beta * ph)
              - beta * ph * (1 - ph ** hh) / ((1 - ph) ** 2 * (1 - ph ** 2)) * (2 * al * (1 - ph ** 2) + beta * ph * (1 + 2 * ph - ph ** hh)),
}
th = {'alpha': al, 'gamma': ga, 'delta': de, 'phi': ph}
for method, v in ref_var.items():
    check(f'{method}: forecast variance multipliers as Hyndman et al. (2008), Table 6.1', np.allclose(ts.psi_variance(method, th, mper, H), v, rtol=1e-12), True)
check("Brown's: the variance of Holt's with level a(2 - a), trend weight a/(2 - a)",
      np.allclose(ts.psi_variance('double', {'alpha': al}, 1, H), ts.psi_variance('linear', {'alpha': al * (2 - al), 'gamma': al / (2 - al)}, 1, H)), True)

# ---- state space smoothing ------------------------------------------------------------------------------
for err, tr, se_ in [('add', 'N', 'N'), ('add', 'Ad', 'A'), ('mul', 'A', 'M')]:
    re_ = call('timeseries.ets', table=tid, y='sales', time='month', error=err, trend=tr, seasonal=se_, s=12, h=6)
    ref_e = ETSModel(pd.Series(y), error=err, trend=None if tr == 'N' else 'add', damped_trend=tr == 'Ad',
                     seasonal={'N': None, 'A': 'add', 'M': 'mul'}[se_], seasonal_periods=12 if se_ != 'N' else None).fit(disp=False)
    check.near(f'{re_["name"]}: AICc is ETSModel\'s', re_['stats']['aicc'], float(ref_e.aicc), rel=1e-9)
    check(f'{re_["name"]}: fitted values', np.allclose(re_['fitted'], ref_e.fittedvalues, rtol=1e-9), True)
    check(f'{re_["name"]}: Nparm = parameters + 1 (sigma)', re_['nparm'], len(ref_e.params) + 1)
    if err == 'add' and se_ != 'M':
        pr = ref_e.get_prediction(start=120, end=125).summary_frame(alpha=0.05)
        check(f'{re_["name"]}: prediction limits', np.allclose(re_['forecast']['upper'], pr['pi_upper'], rtol=1e-8), True)
check('multiplicative ETS needs positive values', 'error' in call('timeseries.ets', table=table({'y': (y - 200).tolist()}), y='y', error='mul'), True)

# ---- a fit that runs out of iterations says so -------------------------------------------------------------
mw = call('timeseries.arima', table=tid, y='sales', time='month', p=2, q=2, P=1, Q=1, s=12, maxiter=5)
check('a fit stopped by Maximum Iterations: statsmodels\' ConvergenceWarning reaches the report', any('ConvergenceWarning' in w_ for w_ in mw.get('warnings', [])), True)
check('... and the result says it did not converge', (mw['converged'], len(mw['iterations']) <= 5), (False, True))
check('... with no deprecation noise', any('DeprecationWarning' in w_ for w_ in mw.get('warnings', [])), False)

# ---- the code under each result runs on a CSV export of the table ---------------------------------------------


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


csv = pd.DataFrame({'month': [pd.Timestamp(v, unit='ms').strftime('%Y-%m-%d') for v in months], 'sales': y, 'promotion': promo, 'temperature': temp})
for label, res_ in [('series', r), ('difference', rd), ('linear trend', rt_), ('seasonal decomposition', rdc), ('STL', rst), ('spectral density', rs), ('cross correlation', rx)]:
    check(f'the {label} code runs', run_code(res_['code'], csv).get('error'), None)
ns = run_code(ms_['code'], csv)
# the seasonal MA sits at the invertibility bound, where the likelihood is flat: compare the fit, not the digits of Theta
check('the seasonal ARIMA code gives the same fit (likelihood and forecasts)', ns.get('error') or (bool(np.isclose(-2 * ns['res'].llf, ms_['stats']['m2ll'], rtol=1e-6)),
      bool(np.allclose(ns['res'].get_forecast(12).predicted_mean, ms_['forecast']['mean'], rtol=1e-4))), (True, True))
ns = run_code(mt['code'], csv)
check('the transfer function code gives the same fit', ns.get('error') or bool(np.allclose(ns['res'].params[1:3], [et['promotion'], et['temperature']], rtol=1e-5)), True)
check('... and forecasts with the same future inputs', ns.get('error') or bool(np.allclose(ns['res'].get_forecast(3, exog=ns['X_future']).predicted_mean, mt['forecast']['mean'], rtol=1e-6)), True)
ns = run_code(mt2['code'], csv)
check('the lagged transfer function code gives the same fit', ns.get('error') or bool(np.isclose(ns['res'].params.iloc[1], mt2['params']['rows'][1]['estimate'], rtol=1e-5)), True)
ns = run_code(rb['code'], csv)
# Brown's alpha is a minimum on a flat sum of squares, found by the report and the
# code along their own paths: the fits agree to about 1e-6 (the minimum itself is
# checked above), so 1e-5 here.
check("Brown's code gives the same fit", ns.get('error') or bool(np.allclose(ns['res'].fittedvalues, rb['fitted'], rtol=1e-5)), True)
ns = run_code(rwm['code'], csv)
check('the Winters code gives the same forecasts', ns.get('error') or bool(np.allclose(ns['res'].forecast(6), rwm['forecast']['mean'], rtol=1e-6)), True)
ns = run_code(re_['code'], csv)
check('the ETS code gives the same AICc', ns.get('error') or bool(np.isclose(ns['res'].aicc, re_['stats']['aicc'], rtol=1e-8)), True)
sun_csv = pd.DataFrame({'YEAR': sun['YEAR'], 'SUNACTIVITY': sun['SUNACTIVITY']})
ns = run_code(m['code'], sun_csv)
check('the sunspots AR(2) code gives the same fit', ns.get('error') or bool(np.allclose(ns['res'].params[:3], [DOC['Intercept'], DOC['AR1'], DOC['AR2']], rtol=2e-6)), True)
ns = run_code(mi['code'], csv)
check('the code sets the excluded rows missing', ns.get('error') or bool(np.isnan(ns['y'].iloc[50]) and np.isnan(ns['y'].iloc[51])), True)
gap_csv = pd.DataFrame({'month': [pd.Timestamp(months[k], unit='ms').strftime('%Y-%m-%d') for k in keep], 'sales': [y[k] for k in keep]})
ns = run_code(r3['code'], gap_csv)
check('the code inserts the missing months', ns.get('error') or (len(ns['y']), bool(np.isnan(ns['y'].iloc[41]))), (120, True))

# ==== beyond JMP: structural models, regime switching, filters, the subseries plot, theta, Zivot-Andrews, ARDL ====
from scipy import stats as sstats
from statsmodels.tsa.statespace.structural import UnobservedComponents
from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
from statsmodels.tsa.regime_switching.markov_autoregression import MarkovAutoregression
from statsmodels.tsa.filters.hp_filter import hpfilter
from statsmodels.tsa.filters.bk_filter import bkfilter
from statsmodels.tsa.filters.cf_filter import cffilter
from statsmodels.tsa.forecasting.theta import ThetaModel
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.stattools import zivot_andrews
from statsmodels.tsa.ardl import ARDL, UECM, ardl_select_order
from statsmodels.tsa.ardl import pss_critical_values as PSS
FIT = dict(method='lbfgs', maxiter=200, pgtol=1e-7, factr=1e4, disp=False)


def near_all(label, got, want, rel=1e-9, abs_=0.0):
    got = np.array([np.nan if v is None else v for v in got], dtype=float)
    want = np.asarray(want, dtype=float)
    ok = got.shape == want.shape and bool(np.all(np.isfinite(got) == np.isfinite(want))) and \
        bool(np.all(np.abs(got - want)[np.isfinite(want)] <= np.maximum(abs_, rel * np.maximum(1.0, np.abs(want[np.isfinite(want)])))))
    worst = float(np.nanmax(np.abs(got - want))) if got.shape == want.shape and np.isfinite(got - want).any() else None
    check(f'{label}' + ('' if ok else f' (largest difference {worst})'), ok, True)


def year_table(years, values, name='y'):
    return table({'year': [float(v) for v in years], name: [float(v) for v in values]})


# ---- Structural Model: Durbin and Koopman's Nile local level, KFAS, statsmodels directly ------------------------
nile = sm.datasets.nile.load_pandas().data
tid_nile = year_table(nile['year'], nile['volume'], 'volume')
un = call('timeseries.structural', table=tid_nile, y='volume', time='year', trend='local level', exact=True, h=5)
check('Structural Model: no error', un.get('error'), None)
check("Structural Model: the name joins the components as statsmodels' summary does", un['name'], 'Structural: local level')
pn = {p['sm']: p['estimate'] for p in un['params']['rows']}
# Durbin and Koopman (2012), section 2.10: the maximum likelihood estimates for the Nile, with the
# exact diffuse initialization; R's StructTS(Nile, "level") gives the same (epsilon 15099, level 1469)
check.near('Nile local level: irregular variance 15099 (Durbin and Koopman 2012)', pn['sigma2.irregular'], 15099.0, rel=2e-4)
check.near('Nile local level: level variance 1469.1 (Durbin and Koopman 2012)', pn['sigma2.level'], 1469.1, rel=5e-4)
check.near('... the diffuse log-likelihood in KFAS\'s convention, -632.55 (the constant of the diffuse period left out)',
           -un['stats']['m2ll'] / 2 + 0.5 * math.log(2 * math.pi), -632.5456, abs_=5e-4)
ref_n = UnobservedComponents(nile['volume'].to_numpy(), level='local level', use_exact_diffuse=True).fit(**FIT)
near_all('Nile: the estimates are UnobservedComponents\' (exact diffuse)', [pn['sigma2.irregular'], pn['sigma2.level']], ref_n.params, rel=1e-8)
check.near('Nile: -2LogLikelihood = -2 llf', un['stats']['m2ll'], -2 * ref_n.llf, rel=1e-10)
check('Nile: the forecast years continue the Time ID', un['forecast']['t'][:2], [1971.0, 1972.0])
fcn = ref_n.get_forecast(5)
near_all('Nile: forecasts and prediction limits are get_forecast\'s', un['forecast']['mean'] + un['forecast']['lower'],
         list(fcn.predicted_mean) + list(fcn.conf_int(alpha=0.05)[:, 0]), rel=1e-8)
lev = [c for c in un['components'] if c['key'] == 'level'][0]
near_all('Nile: the smoothed level and its band are statsmodels\' (res.level.smoothed, smoothed_cov)', lev['mean'] + lev['upper'],
         list(ref_n.level.smoothed) + list(ref_n.level.smoothed + 1.959963984540054 * np.sqrt(ref_n.level.smoothed_cov)), rel=1e-7)
irr = [c for c in un['components'] if c['key'] == 'irregular'][0]
near_all('Nile: the irregular is the smoothed measurement disturbance', irr['mean'], ref_n.smoother_results.smoothed_measurement_disturbance[0], rel=1e-7, abs_=1e-6)
check('Nile: k leaves the scale out (statsmodels counts the 2 variances and the diffuse state)', (un['stats']['k'], un['sm']['df_model']), (2, 3))
check.near("Nile: AIC = statsmodels' AIC - 2", un['stats']['aic'], ref_n.aic - 2, rel=1e-10)
ua = call('timeseries.structural', table=tid_nile, y='volume', time='year', trend='local level', h=0)
ref_a = UnobservedComponents(nile['volume'].to_numpy(), level='local level').fit(**FIT)
near_all('Nile, approximate diffuse (statsmodels\' default): the estimates', [p['estimate'] for p in ua['params']['rows']], ref_a.params, rel=1e-8)
check('... the first observation is left out of the likelihood and of the fit statistics', (ua['burn'], ua['stats']['n'], ua['fitted'][0]), (1, 99, None))

# KFAS on the US unemployment rate, as bundled with statsmodels' tests (results_structural.py)
try:
    from statsmodels.tsa.statespace.tests.results import results_structural as KFAS
except Exception:  # noqa: BLE001 - a statsmodels install without its tests
    KFAS = None
macro = sm.datasets.macrodata.load_pandas().data
qdates = pd.date_range('1959-01-01', periods=len(macro), freq='QS')
tid_macro = date_table({'quarter': [ms(t) for t in qdates], 'unemp': macro['unemp'].tolist(), 'realgdp': np.log(macro['realgdp']).tolist()}, ('quarter',))
if KFAS is None:
    print('  (statsmodels\' test results are not installed: the KFAS checks are skipped)')
else:
    for spec_name, kw in [('local_linear_trend', {'trend': 'local linear trend'}), ('smooth_trend', {'trend': 'smooth trend'}),
                          ('random_walk_with_drift', {'trend': 'random walk with drift'})]:
        true = getattr(KFAS, spec_name)
        rk = call('timeseries.structural', table=tid_macro, y='unemp', time='quarter', h=0, **kw)
        # statsmodels' own test: a likelihood at least KFAS's, and within 1e-4 of it
        llk = -rk['stats']['m2ll'] / 2
        check(f'US unemployment {kw["trend"]}: the log-likelihood reaches KFAS\'s {true["llf"]:.6f}', llk >= true['llf'] - 1e-4 * abs(true['llf']), True)
        check.near(f'... and is within 1e-4 of it', llk, true['llf'], rel=1e-4)
# a basic structural model with an input, statsmodels called directly on the same date-indexed series
rb_ = call('timeseries.structural', table=tid, y='sales', time='month', trend='local linear trend', seasonal=12, inputs=['promotion'], h=6)
ys = pd.Series(y, index=pd.date_range('2016-01-01', periods=n, freq='MS'))
Xs = pd.DataFrame({'promotion': promo}, index=ys.index)
ref_b = UnobservedComponents(ys, level='local linear trend', seasonal=12, stochastic_seasonal=True, exog=Xs).fit(**FIT)
near_all('BSM with an input: the estimates are UnobservedComponents\'', [p['estimate'] for p in rb_['params']['rows']], ref_b.params, rel=1e-6, abs_=1e-9)
check('... the names', [p['term'] for p in rb_['params']['rows']], ['Irregular Variance (σ²ε)', 'Level Variance (σ²η)', 'Slope Variance (σ²ζ)', 'Seasonal Variance (σ²ω)', 'promotion'])
check.near('... the promotion effect is near the simulated 9', [p['estimate'] for p in rb_['params']['rows'] if p['term'] == 'promotion'][0], 9.0, abs_=2.0)
fcb = ref_b.get_forecast(6, exog=np.zeros((6, 1)))
near_all('... forecasts with the promotion held at its last value (0)', rb_['forecast']['mean'], fcb.predicted_mean, rel=1e-6)
check('... the components: level, trend, seasonal, regression, irregular', [c['key'] for c in rb_['components']], ['level', 'trend', 'seasonal', 'regression', 'irregular'])
reg = [c for c in rb_['components'] if c['key'] == 'regression'][0]
near_all('... the regression effect is promotion × β', reg['mean'], np.array(promo) * ref_b.params['beta.promotion'], rel=1e-9, abs_=1e-9)
comp_sum = sum(np.array([np.nan if v is None else v for v in c['mean']]) for c in rb_['components'] if c['key'] in ('level', 'seasonal', 'regression', 'irregular'))
check('... level + seasonal + regression + irregular add up to the series (the smoothed parts)', bool(np.allclose(comp_sum, y, atol=1e-6)), True)
check('... the one-step residuals are statsmodels\'', bool(np.allclose([v for v in rb_['resid'][13:]], (ys - ref_b.fittedvalues).to_numpy()[13:], rtol=1e-6, atol=1e-6)), True)
# the cycle: statsmodels' default bounds from the frequency (1.5 to 12 years), or the dialog's
rcy = call('timeseries.structural', table=tid_macro, y='unemp', time='quarter', trend='local level', cycle=True, h=0)
check('Cycle: statsmodels\' default period bounds for quarterly data, 6 to 48 quarters', rcy['cycle_bounds'], [6.0, 48.0])
ref_c = UnobservedComponents(pd.Series(macro['unemp'].to_numpy(), index=qdates), level='local level', cycle=True, stochastic_cycle=True, damped_cycle=True).fit(**FIT)
check.near('Cycle: the likelihood is UnobservedComponents\'', rcy['stats']['m2ll'], -2 * ref_c.llf, rel=1e-8)
per = [s_[1] for s_ in rcy['summary'] if s_[0] == 'Cycle Period (2π/λ)'][0]
check('... its period 2π/λ lies within the bounds', 6.0 <= per <= 48.0, True)
rcy2 = call('timeseries.structural', table=tid_macro, y='unemp', time='quarter', trend='local level', cycle=True, cycle_lo=8, cycle_hi=40, h=0)
check('Cycle: bounds from the dialog', rcy2['cycle_bounds'], [8.0, 40.0])
rtr = call('timeseries.structural', table=tid, y='sales', time='month', trend='local level', freq_period=12, freq_harmonics=2, ar=1, h=0)
check('Trigonometric seasonal and AR part: statsmodels\' parameter names', [p['sm'] for p in rtr['params']['rows']],
      ['sigma2.irregular', 'sigma2.level', 'sigma2.freq_seasonal_12(2)', 'sigma2.ar', 'ar.L1'])
rex = call('timeseries.structural', table=tid, y='sales', time='month', trend='local level', seasonal=12, excluded=[40], h=0)
check('Excluded rows are missing values the Kalman filter skips', (rex.get('error'), rex['resid'][40], rex['stats']['n']), (None, None, 120 - 12 - 1))
check('too short a series for the model is an error', 'error' in call('timeseries.structural', table=tid, y='sales', rows=list(range(10)), trend='local linear trend', seasonal=12), True)

# ---- Regime Switching: Hamilton (1989), Stata's fed funds, statsmodels directly -------------------------------------
try:
    from statsmodels.tsa.regime_switching.tests.test_markov_autoregression import hamilton_ar4_smoothed, rgnp as RGNP
    from statsmodels.tsa.regime_switching.tests.test_markov_regression import fedfunds as FEDFUNDS
except Exception:  # noqa: BLE001
    RGNP = None
if RGNP is None:
    print('  (statsmodels\' test data are not installed: the Hamilton and fed funds checks are skipped)')
else:
    qd = pd.date_range('1951-04-01', periods=len(RGNP), freq='QS')
    tid_h = date_table({'quarter': [ms(t) for t in qd], 'rgnp': list(RGNP)}, ('quarter',))
    mh = call('timeseries.markov', table=tid_h, y='rgnp', time='quarter', k=2, order=4, switching_ar=False, starts=5)
    check('Hamilton: no error', mh.get('error'), None)
    ph = {p['sm']: p['estimate'] for p in mh['params']['rows']}
    # Hamilton (1989), as E-views estimates it (statsmodels' test_markov_autoregression)
    HAM = {'p[0->0]': 0.754673, 'p[1->0]': 0.095915, 'const[0]': -0.358811, 'const[1]': 1.163516, 'sigma2': math.exp(-0.262658) ** 2,
           'ar.L1': 0.013486, 'ar.L2': -0.057521, 'ar.L3': -0.246983, 'ar.L4': -0.212923}
    for k_, v in HAM.items():
        check.near(f'Hamilton (1989) MS-AR(4): {k_}', ph[k_], v, rel=5e-4, abs_=2e-5)
    check.near('Hamilton: log-likelihood -181.26339', -mh['stats']['m2ll'] / 2, -181.26339, abs_=1e-4)
    dur = {r_['regime']: r_['duration'] for r_ in mh['regimes']}
    check.near('Hamilton: a recession lasts 1/(1 − p00) = 4.1 quarters', dur['Regime 0'], 1 / (1 - HAM['p[0->0]']), rel=1e-3)
    check.near('... an expansion 1/p10 = 10.4 quarters', dur['Regime 1'], 1 / HAM['p[1->0]'], rel=1e-3)
    near_all('Hamilton: the smoothed expansion probabilities are E-views\' (Kim smoother)', mh['prob'][1][4:], hamilton_ar4_smoothed, abs_=2e-4)
    check('... the first 4 quarters have no probability (the lags\' starting values)', mh['prob'][1][:4], [None] * 4)
    tm = {row['from']: [row['r0'], row['r1']] for row in mh['transition']}
    check.near('Transition Probabilities: from regime 1 to regime 0 is p10', tm['Regime 1'][0], HAM['p[1->0]'], rel=5e-4)
    check('... each row sums to 1', all(abs(sum(v) - 1) < 1e-12 for v in tm.values()), True)
    check('the Starts table: statsmodels\' default, the quantiles and 5 random starts, one best', (len(mh['starts']), sum(1 for s_ in mh['starts'] if s_['best'])), (7, 1))
    tid_f = table({'fedfunds': list(FEDFUNDS)})
    mf = call('timeseries.markov', table=tid_f, y='fedfunds', k=2, order=0, starts=3)
    pf = {p['sm']: p['estimate'] for p in mf['params']['rows']}
    # Stata's mswitch dr (Stata manual [TS] mswitch; statsmodels' test_markov_regression)
    STATA = {'p[0->0]': 0.9820939, 'p[1->0]': 0.0503587, 'const[0]': 3.70877, 'const[1]': 9.556793, 'sigma2': 2.107562 ** 2}
    for k_, v in STATA.items():
        check.near(f'Fed funds switching mean: {k_} as Stata', pf[k_], v, rel=2e-4)
    check.near('Fed funds: log-likelihood -508.63592 as Stata', -mf['stats']['m2ll'] / 2, -508.63592, abs_=1e-4)
    stata = pd.read_csv(os.path.join(os.path.dirname(sm.__file__), 'tsa', 'regime_switching', 'tests', 'results', 'results_predict_fedfunds.csv'))
    near_all('Fed funds: the smoothed probabilities are Stata\'s', mf['prob'][0], stata['const_sm1'], abs_=1e-5)
    near_all("Fed funds: the one-step predictions are Stata's predicted values (pyhat), at estimates equal to 5 digits", mf['fitted'], stata['const_pyhat'], abs_=5e-4)
    # the code shown reproduces the fit (the same starts, the same seed)
    ns = run_code(mh['code'], pd.DataFrame({'quarter': [t.strftime('%Y-%m-%d') for t in qd], 'rgnp': list(RGNP)}))
    check('the Hamilton code gives the same fit', ns.get('error') or bool(np.isclose(ns['res'].llf, -mh['stats']['m2ll'] / 2, rtol=1e-9)), True)
# the example's growth series: the quantile start finds the regimes statsmodels' own start misses
g_rng = np.random.default_rng(4)
st_, g0, gs = 0, 0.8, []
for t_ in range(184):
    if t_ and g_rng.uniform() > (0.95, 0.75)[st_]:
        st_ = 1 - st_
    g0 = (0.8, -0.6)[st_] + 0.3 * (g0 - (0.8, -0.6)[st_]) + g_rng.normal(0, 0.6)
    gs.append(g0)
tid_g = table({'growth': gs})
mg = call('timeseries.markov', table=tid_g, y='growth', k=2, order=1, switching_ar=False, starts=5)
mod_g = MarkovAutoregression(np.array(gs), k_regimes=2, order=1, switching_ar=False)
p_default = mod_g.fit(return_params=True)
check('simulated regimes: the best start is at least as good as statsmodels\' default', -mg['stats']['m2ll'] / 2 >= mod_g.loglike(p_default) - 1e-6, True)
pg = {p['sm']: p['estimate'] for p in mg['params']['rows']}
check('... and finds two regimes near the simulated means 0.8 and -0.6', abs(max(pg['const[0]'], pg['const[1]']) - 0.8) < 0.35 and abs(min(pg['const[0]'], pg['const[1]']) + 0.6) < 0.45, True)
res_g = mod_g.smooth(np.array([pg[nm] for nm in mod_g.param_names]), cov_type='approx')
near_all('... its smoothed probabilities are MarkovAutoregression.smooth\'s at those estimates', mg['prob'][0][1:], res_g.smoothed_marginal_probabilities[:, 0], abs_=1e-10)
near_all('... its one-step predictions are predict(probabilities="predicted")', mg['fitted'][1:], res_g.predict(probabilities='predicted'), rel=1e-9)
check('nothing switching is an error', 'error' in call('timeseries.markov', table=tid_g, y='growth', k=2, trend='n', switching_trend=False, switching_variance=False), True)
m3 = call('timeseries.markov', table=tid_g, y='growth', k=3, switching_variance=True, starts=2)
check('three regimes with switching variances: a 3 × 3 transition matrix, three variances', (len(m3['transition']), sum(1 for p in m3['params']['rows'] if p['sm'].startswith('sigma2'))), (3, 3))
mod3 = MarkovRegression(np.array(gs), k_regimes=3, switching_variance=True)
p3 = np.array([{p['sm']: p['estimate'] for p in m3['params']['rows']}[nm] for nm in mod3.param_names])
check.near('... the log-likelihood at its estimates is MarkovRegression\'s', -m3['stats']['m2ll'] / 2, float(mod3.loglike(p3)), rel=1e-10)
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    ll3_default = float(mod3.loglike(mod3.fit(return_params=True)))
check('... and at least that of statsmodels\' default start', -m3['stats']['m2ll'] / 2 >= ll3_default - 1e-6, True)
check('... statsmodels does not forecast Markov switching models', m3['forecast']['t'], [])

# ---- Filters: the Hodrick-Prescott closed form, the Baxter-King weights, Christiano-Fitzgerald's formula ----------------
fh = call('timeseries.filter', table=tid, y='sales', time='month', method='hp')
check('HP: monthly data take λ = 129600 (Ravn and Uhlig: 1600 × 3⁴)', fh['lamb'], 129600.0)
K2 = np.zeros((n - 2, n))
for i in range(n - 2):
    K2[i, i:i + 3] = [1, -2, 1]
tau = np.linalg.solve(np.eye(n) + 129600 * K2.T @ K2, y)
near_all('HP: the trend is the closed form (I + λK\'K)⁻¹y', fh['trend'], tau, rel=1e-8)
near_all('HP: the cycle is y − trend, as hpfilter', fh['cycle'], hpfilter(y, 129600)[0], rel=1e-9, abs_=1e-9)
lam_q = call('timeseries.filter', table=tid_macro, y='unemp', time='quarter', method='hp')['lamb']
lam_y = call('timeseries.filter', table=tid_nile, y='volume', time='year', method='hp')['lamb']
yr_dates = date_table({'yr': [ms(f'{1900 + i}-01-01') for i in range(40)], 'v': list(np.cumsum(np.random.default_rng(2).normal(size=40)))}, ('yr',))
lam_a = call('timeseries.filter', table=yr_dates, y='v', time='yr', method='hp')['lamb']
check('HP λ: 1600 quarterly, 6.25 for yearly dates, statsmodels\' 1600 for a numeric Time ID', (lam_q, lam_a, lam_y), (1600.0, 6.25, 1600.0))
fb = call('timeseries.filter', table=tid_macro, y='realgdp', time='quarter', method='bk')
lgdp = np.log(macro['realgdp'].to_numpy())
a_, b_ = 2 * np.pi / 32, 2 * np.pi / 6
jj = np.arange(1, 13)
wts = np.r_[(b_ - a_) / np.pi, (np.sin(b_ * jj) - np.sin(a_ * jj)) / (np.pi * jj)]
wts = wts - (wts[0] + 2 * wts[1:].sum()) / 25      # Baxter and King: the weights shifted to sum to zero
w_full = np.r_[wts[::-1], wts[1:]]
bk_hand = np.convolve(lgdp, w_full, mode='valid')
check('BK: the quarterly defaults are the band 6 to 32 quarters and K = 12', (fb['low'], fb['high'], fb['K']), (6.0, 32.0, 12))
near_all('BK: the cycle is the moving average of Baxter and King\'s weights', fb['cycle'][12:-12], bk_hand, rel=1e-9, abs_=1e-12)
near_all('... which is bkfilter', fb['cycle'][12:-12], bkfilter(lgdp, 6, 32, 12), rel=1e-12, abs_=1e-14)
check('... and K values are lost at each end', (fb['cycle'][:12], fb['cycle'][-12:], fb['cycle_n']), ([None] * 12, [None] * 12, len(lgdp) - 24))
fc_ = call('timeseries.filter', table=tid_macro, y='realgdp', time='quarter', method='cf')


def cf_by_hand(x, low, high):
    """Christiano and Fitzgerald (2003) for a random walk: the drift x[0] + t (x[-1] - x[0])/(T - 1)
    removed, then c_t = B0 x_t + sum B_j x_t+j over the sample, with the end weights ~B = -B0/2 - sum B_j."""
    T = len(x)
    x = x - (x[-1] - x[0]) / (T - 1) * np.arange(T)
    a, b = 2 * np.pi / high, 2 * np.pi / low
    B = np.r_[(b - a) / np.pi, [(np.sin(b * j) - np.sin(a * j)) / (np.pi * j) for j in range(1, T)]]
    out = np.empty(T)
    for t in range(T):
        f, bk = T - 1 - t, t                     # values after and before t
        wts_ = np.zeros(T)
        wts_[t] += B[0]
        for j in range(1, f):
            wts_[t + j] += B[j]
        for j in range(1, bk):
            wts_[t - j] += B[j]
        wts_[T - 1] += -0.5 * B[0] - B[1:f].sum()   # the end weights (on x_t itself at the ends)
        wts_[0] += -0.5 * B[0] - B[1:bk].sum()
        out[t] = wts_ @ x
    return out


near_all('CF: the cycle is Christiano and Fitzgerald\'s random-walk filter (by hand)', fc_['cycle'], cf_by_hand(lgdp, 6, 32), rel=1e-8, abs_=1e-10)
near_all('... which is cffilter', fc_['cycle'], cffilter(lgdp, 6, 32, True)[0], rel=1e-12, abs_=1e-14)
check('... no value is lost', fc_['cycle_n'], len(lgdp))
fcm = call('timeseries.filter', table=tid, y='sales', time='month', method='cf', excluded=[5])
check('a missing value: filled for the filter, the cycle missing there', (fcm['cycle'][5], fcm['trend'][5] is not None), (None, True))
check('the band must have its shorter period below the longer', 'error' in call('timeseries.filter', table=tid, y='sales', method='bk', low=20, high=10), True)

# ---- Seasonal Subseries Plot: statsmodels' month_plot, quarter_plot and seasonal_plot ------------------------------------
ss_ = call('timeseries.subseries', table=tid, y='sales', time='month', period=12)
check('Subseries: monthly dates are grouped by calendar month', (ss_['by'], [s_['label'] for s_ in ss_['seasons']][:3]), ('month', ['Jan', 'Feb', 'Mar']))
near_all('... each month\'s mean is the groupby mean', [s_['mean'] for s_ in ss_['seasons']], ys.groupby(ys.index.month).mean(), rel=1e-12)
check('... ten Januaries, the January rows 0, 12, 24 …', (ss_['seasons'][0]['n'], ss_['seasons'][0]['rows'][:3]), (10, [0, 12, 24]))
try:
    import matplotlib
    matplotlib.use('Agg')
    from statsmodels.graphics.tsaplots import month_plot, quarter_plot
except Exception:  # noqa: BLE001
    month_plot = None
if month_plot is None:
    print('  (matplotlib is not installed: the month_plot drawing checks are skipped)')
else:
    ax = month_plot(ys).axes[0]
    lines = ax.get_lines()[:12]
    check('... the positions are month_plot\'s, block by block', all(list(ln.get_xdata()) == s_['x'] for ln, s_ in zip(lines, ss_['seasons'])), True)
    check('... and so are the values', all(np.allclose(ln.get_ydata(), s_['values']) for ln, s_ in zip(lines, ss_['seasons'])), True)
    check('... and the mean lines', all(np.isclose(c_.get_segments()[0][0][1], s_['mean']) for c_, s_ in zip(ax.collections[:12], ss_['seasons'])), True)
    sq = call('timeseries.subseries', table=tid_macro, y='unemp', time='quarter', period=4)
    qs = pd.Series(macro['unemp'].to_numpy(), index=qdates)
    axq = quarter_plot(qs).axes[0]
    check('Subseries: quarterly dates by quarter, the positions and means of quarter_plot', (sq['by'], [s_['label'] for s_ in sq['seasons']],
          all(list(ln.get_xdata()) == s_['x'] for ln, s_ in zip(axq.get_lines()[:4], sq['seasons'])),
          all(np.isclose(c_.get_segments()[0][0][1], s_['mean']) for c_, s_ in zip(axq.collections[:4], sq['seasons']))), ('quarter', ['Q1', 'Q2', 'Q3', 'Q4'], True, True))
sp_ = call('timeseries.subseries', table=table({'v': list(range(1, 22))}), y='v', period=5)
check('Subseries: with no dates, the position in the period from the first value', (sp_['by'], sp_['seasons'][1]['values'][:3], sp_['seasons'][0]['x']), ('position', [2.0, 7.0, 12.0], [0, 1, 2, 3, 4]))
sm_ = call('timeseries.subseries', table=tid, y='sales', time='month', period=12, excluded=[0])
check('a missing value: the mean of the values present (statsmodels\' seasonal_plot would draw none)', (sm_['seasons'][0]['n'], round(sm_['seasons'][0]['mean'], 9)),
      (9, round(float(np.mean(y[12::12])), 9)))

# ---- Theta Model: ThetaModel directly, the IMA(1, 1) forecast variance, Hyndman and Billah ---------------------------------
th = call('timeseries.theta', table=tid, y='sales', time='month', period=12, h=12)
ref_t = ThetaModel(y, period=12).fit()
check.near('Theta: b0 is ThetaModel\'s', th['b0'], float(ref_t.params['b0']), rel=1e-12)
check.near('Theta: alpha is ThetaModel\'s', th['alpha'], float(ref_t.params['alpha']), rel=1e-12)
near_all('Theta: the forecasts are ThetaModel.forecast(12, theta=2)', th['forecast']['mean'], ref_t.forecast(12, theta=2), rel=1e-12)
pis = ref_t.prediction_intervals(12, theta=2, alpha=0.05)
near_all("... statsmodels' own prediction intervals are kept too", th['forecast']['sm_lower'], pis['lower'], rel=1e-12)
al_, s2_ = float(ref_t.params['alpha']), float(ref_t.sigma2)
near_all('... the report\'s interval is σ√(1 + (h − 1)α²), the IMA(1, 1)\'s', th['forecast']['upper'],
         ref_t.forecast(12) + 1.959963984540054 * np.sqrt(s2_ * (1 + np.arange(12) * al_ ** 2)), rel=1e-12)
check('... the seasonality test found the season and deseasonalized multiplicatively', (th['seasonal_found'], th['method']), (True, 'mul'))
seas_ = np.asarray(seasonal_decompose(y, model='multiplicative', period=12).seasonal[:12])
fit_T = ((1 - 1 / 2) * th['b0'] * (1 / al_ - (1 - al_) ** n / al_) + th['one_step']) * seas_[n % 12]
check.near('the in-sample recursion, carried to the last origin, is ThetaModel\'s one-step forecast', fit_T, float(ref_t.forecast(1).iloc[0]), rel=1e-10)
th3 = call('timeseries.theta', table=tid, y='sales', time='month', period=12, theta=3, h=4)
near_all('θ = 3: forecast(theta=3)', th3['forecast']['mean'], ref_t.forecast(4, theta=3), rel=1e-12)
# non-seasonal: an IMA(1, 1) with drift by MLE, SARIMAX's forecast variance, Hyndman and Billah's drift
ima_rng = np.random.default_rng(3)
eps = ima_rng.normal(0, 1, 301)
xi = np.cumsum(0.1 + eps[1:] - 0.6 * eps[:-1]) + 50
tid_i = table({'x': list(xi)})
tm_ = call('timeseries.theta', table=tid_i, y='x', period=0, use_mle=True, h=6)
ref_m = ThetaModel(xi, deseasonalize=False).fit(use_mle=True)
near_all('Theta by MLE: the forecasts are ThetaModel\'s', tm_['forecast']['mean'], ref_m.forecast(6), rel=1e-10)
sx = SARIMAX(xi, order=(0, 1, 1), trend='c').fit(disp=False)
near_all("... the report's forecast standard errors are the IMA(1, 1) with drift's (SARIMAX)", tm_['forecast']['se'], sx.get_forecast(6).se_mean, rel=1e-6)
ratio = (tm_['forecast']['sm_upper'][5] - tm_['forecast']['mean'][5]) / (tm_['forecast']['upper'][5] - tm_['forecast']['mean'][5])
a_m = tm_['alpha']
check.near("... statsmodels 0.14.6's prediction_intervals are wider, by √((1 + 5(1 + (α − 1)²))/(1 + 5α²)) at h = 6", ratio,
           math.sqrt((1 + 5 * (1 + (a_m - 1) ** 2)) / (1 + 5 * a_m ** 2)), rel=1e-10)
tn = call('timeseries.theta', table=tid_i, y='x', period=0, h=6)
dd = np.diff(tn['forecast']['mean'])
check('θ = 2 is simple exponential smoothing with drift b0/2 (Hyndman and Billah 2003)', bool(np.allclose(dd, tn['b0'] / 2, rtol=1e-10)), True)
check('θ below 1 is an error', 'error' in call('timeseries.theta', table=tid_i, y='x', theta=0.5), True)

# ---- Zivot-Andrews: Nelson and Plosser's real GNP (Zivot and Andrews 1992), statsmodels directly ---------------------------
za_file = os.path.join(os.path.dirname(sm.__file__), 'tsa', 'tests', 'results', 'rgnp.csv')
if not os.path.exists(za_file):
    print('  (statsmodels\' test data are not installed: the real GNP checks are skipped)')
else:
    gnp = pd.read_csv(za_file).iloc[:, 0].to_numpy(dtype=float)
    tid_z = year_table(range(1909, 1909 + len(gnp)), gnp, 'rgnp')
    za = call('timeseries.zivot', table=tid_z, y='rgnp', time='year', maxlag=8, autolag=None)
    zc = {t_['regression']: t_ for t_ in za['tests']}
    # Zivot and Andrews (1992), Table 4: real GNP, a break in the intercept, k = 8: t = -5.58 with the break in 1929
    check.near('Zivot-Andrews: real GNP, a break in the intercept, t = -5.58 (Zivot and Andrews 1992)', zc['c']['stat'], -5.58, abs_=0.006)
    check('... the break: 1929, the Great Crash', zc['c']['break'], 1929.0)
    check.near("... R's urca ur.za: -5.57615, p 0.00312 (statsmodels' test)", zc['c']['stat'], -5.57615, rel=1e-4)
    check.near('... the p-value', zc['c']['p'], 0.00312, rel=2e-3)
ZA92 = {'c': (-5.34, -4.80, -4.58), 't': (-4.93, -4.42, -4.11), 'ct': (-5.57, -5.08, -4.82)}   # Zivot and Andrews (1992), Tables 2-4
brk_rng = np.random.default_rng(11)
u_ = np.zeros(150)
for t_ in range(1, 150):
    u_[t_] = 0.5 * u_[t_ - 1] + brk_rng.normal(0, 0.5)
zb = u_ + np.where(np.arange(150) > 89, 3.0, 0.0) + 0.02 * np.arange(150)
zb[[20, 21]] = np.nan
tid_zb = table({'x': list(zb)})
zr = call('timeseries.zivot', table=tid_zb, y='x')
v_ok = zb[np.isfinite(zb)]
pos_ok = np.flatnonzero(np.isfinite(zb))
for t_ in zr['tests']:
    ref_z = zivot_andrews(v_ok, trim=0.15, maxlag=None, regression=t_['regression'], autolag='AIC')
    check.near(f'Zivot-Andrews ({t_["regression"]}): the statistic is zivot_andrews\'', t_['stat'], float(ref_z[0]), rel=1e-12)
    check(f'... the break maps back past the missing values to its slot', t_['break_slot'], int(pos_ok[ref_z[4]]))
    for key, pub, tol in zip(('c1', 'c5', 'c10'), ZA92[t_['regression']], (0.11, 0.03, 0.03)):
        check.near(f'... the {key[1:]}% critical value is near Zivot and Andrews\' {pub}', t_[key], pub, abs_=tol)
zc_ = {t_['regression']: t_ for t_ in zr['tests']}
check('the level shift after slot 89 is found (a break in the intercept, rejecting the unit root)', zc_['c']['break_slot'] in range(86, 93) and zc_['c']['p'] < 0.05, True)

# ---- ARDL: statsmodels' Danish money demand example, the PSS (2001) tables, statsmodels directly --------------------------
dan = sm.datasets.danish_data.load_pandas().data
tid_d = date_table({'period': [ms(t) for t in dan.index], **{c: dan[c].tolist() for c in ('lrm', 'lry', 'ibo', 'ide')}}, ('period',))
ad = call('timeseries.ardl', table=tid_d, y='lrm', time='period', inputs=['lry', 'ibo', 'ide'], maxlag=3, maxorder=3, ic='aic', trend='c', h=0)
check('ARDL: no error', ad.get('error'), None)
check("ARDL: the documented order ARDL(3, 1, 3, 2) (statsmodels' ARDL example)", ad['order'], [3, 1, 3, 2])
ref_sel = ardl_select_order(dan.lrm, 3, dan[['lry', 'ibo', 'ide']], 3, ic='aic', trend='c')
ref_ad = ref_sel.model.fit()
pa = {p['sm']: p['estimate'] for p in ad['params']['rows']}
near_all("ARDL(3, 1, 3, 2): the coefficients are ARDL's", [pa[k_] for k_ in ref_ad.params.index], ref_ad.params, rel=1e-10)
check.near('... the documented intercept 2.6202', pa['const'], 2.6202, abs_=6e-5)
DOC_UECM = {'const': 2.6202, 'lrm.L1': -0.4169, 'lry.L1': 0.4154, 'ibo.L1': -1.8917, 'ide.L1': 1.2053, 'D.lrm.L1': -0.2639, 'D.lrm.L2': 0.2687,
            'D.lry.L0': 0.6728, 'D.ibo.L0': -1.0785, 'D.ibo.L1': 0.7070, 'D.ibo.L2': 0.9947, 'D.ide.L0': 0.1255, 'D.ide.L1': -1.4079}
pe_ = {p['sm']: p['estimate'] for p in ad['ecm']}
near_all('the error correction form: the documented UECM coefficients', [pe_[k_] for k_ in DOC_UECM], list(DOC_UECM.values()), abs_=6e-5)
check.near('... the speed of adjustment is the coefficient of lrm(t-1), -0.4169', ad['speed'], -0.4169, abs_=6e-5)
lrd = {r_['term']: r_ for r_ in ad['long_run']}
DOC_CI = {'Intercept': (6.2857, 0.772), 'lry': (0.9965, 0.124), 'ibo': (-4.5381, 0.520), 'ide': (2.8915, 0.995)}   # minus the documented ci_summary()
near_all('Long-run coefficients: minus the documented cointegrating vector', [lrd[k_]['estimate'] for k_ in DOC_CI], [v[0] for v in DOC_CI.values()], abs_=6e-5)
near_all('... their standard errors', [lrd[k_]['se'] for k_ in DOC_CI], [v[1] for v in DOC_CI.values()], abs_=6e-4)
ref_u = UECM.from_ardl(ref_sel.model).fit()
near_all("... UECM's ci_params and ci_bse exactly", [lrd[k_]['estimate'] for k_ in ('Intercept', 'lry', 'ibo', 'ide')] + [lrd[k_]['se'] for k_ in ('Intercept', 'lry', 'ibo', 'ide')],
         list(-ref_u.ci_params[['const', 'lry', 'ibo', 'ide']]) + list(ref_u.ci_bse[['const', 'lry', 'ibo', 'ide']]), rel=1e-10)
near_all('... and the p-values (normal, as ci_pvalues)', [lrd[k_]['p'] for k_ in ('lry', 'ibo', 'ide')], ref_u.ci_pvalues[['lry', 'ibo', 'ide']], rel=1e-6, abs_=1e-12)
# the documented bounds tests are of UECM(lrm, 3, [lry, ibo, ide], 3): an ARDL(3, 3, 3, 3)
fixed = {'p': 3, 'q': {'lry': 3, 'ibo': 3, 'ide': 3}}
b3 = call('timeseries.ardl', table=tid_d, y='lrm', time='period', inputs=['lry', 'ibo', 'ide'], order=fixed, trend='c', h=0)['bounds']
b4 = call('timeseries.ardl', table=tid_d, y='lrm', time='period', inputs=['lry', 'ibo', 'ide'], order=fixed, trend='ct', h=0)['bounds']
check.near('Bounds test, case 3: F = 5.99305 as documented', b3['stat'], 5.99305, abs_=6e-6)
check.near('Bounds test, case 4: F = 5.07063 as documented', b4['stat'], 5.07063, abs_=6e-6)
check.near("... statsmodels' own upper p-value 0.00205 as documented (its tables at k + 1)", b3['sm_p_upper'], 0.00205, abs_=6e-6)
check.near("... and lower 0.000138", b3['sm_p_lower'], 0.000138, abs_=6e-7)
sm4 = {r_['level']: r_ for r_ in b4['sm_crit']}
check.near("... case 4: statsmodels' documented 5% bounds 3.069910 and 3.957893", sm4['5%']['lower'] + sm4['5%']['upper'], 3.069910 + 3.957893, abs_=2e-6)
check("statsmodels 0.14.6's bounds_test reads its PSS tables at k + 1: the documented case-4 bounds are the tables' for 4 inputs",
      (round(sm4['5%']['lower'], 5), round(sm4['5%']['upper'], 5)), (round(float(PSS.crit_vals[(4, 4, False)][1]), 5), round(float(PSS.crit_vals[(4, 4, True)][1]), 5)))
check('... which are not those for the model\'s 3', abs(sm4['5%']['lower'] - float(PSS.crit_vals[(3, 4, False)][1])) > 0.2, True)
c3 = {r_['level']: r_ for r_ in b3['crit']}
check('... the report reads them at k = 3, the model\'s inputs', (b3['k'], round(c3['5%']['lower'], 6), round(c3['5%']['upper'], 6)),
      (3, round(float(PSS.crit_vals[(3, 3, False)][1]), 6), round(float(PSS.crit_vals[(3, 3, True)][1]), 6)))
from statsmodels.tsa.ardl.model import _pss_pvalue
check.near('... with the p-value of statsmodels\' response surface at k = 3', b3['p_upper'], float(_pss_pvalue(b3['stat'], 3, 3, True)), rel=1e-12)
check('Bounds test, case 3: F = 5.99 is above the 5% I(1) bound: a level relationship', b3['verdict'], 'reject')
# Pesaran, Shin and Smith (2001), Table CI(iii), case III (unrestricted intercept, no trend): the F bounds at 10%, 5%, 1%
PSS01 = {1: ((4.04, 4.78), (4.94, 5.73), (6.84, 7.84)), 2: ((3.17, 4.14), (3.79, 4.85), (5.15, 6.36)), 3: ((2.72, 3.77), (3.23, 4.35), (4.29, 5.61)),
         4: ((2.45, 3.52), (2.86, 4.01), (3.74, 5.06)), 5: ((2.26, 3.35), (2.62, 3.79), (3.41, 4.68))}
for k_, rows_pss in PSS01.items():
    crit_k, _, _ = ts.pss_bounds(5.0, k_, 3)
    got = {r_['level']: (r_['lower'], r_['upper']) for r_ in crit_k}
    for level_, (lo_, hi_), tol in zip(('10%', '5%', '1%'), rows_pss, (0.04, 0.04, 0.07)):
        check(f'PSS (2001) Table CI(iii), k = {k_}, {level_}: bounds {lo_} and {hi_}', abs(got[level_][0] - lo_) <= tol and abs(got[level_][1] - hi_) <= tol, True)
# a simulated level relationship with future inputs: the bounds test finds it, forecasts continue with the future cost
pr_rng = np.random.default_rng(7)
cost_ = np.cumsum(0.2 + 0.8 * pr_rng.normal(size=184)) + 50
price_ = np.zeros(176)
price_[0] = 12.5 + 0.75 * cost_[0]
for t_ in range(1, 176):
    price_[t_] = 5 + 0.6 * price_[t_ - 1] + 0.5 * cost_[t_] - 0.2 * cost_[t_ - 1] + 0.5 * pr_rng.normal()
qd2 = pd.date_range('1980-01-01', periods=184, freq='QS')
tid_p = date_table({'quarter': [ms(t) for t in qd2], 'price': list(price_) + [None] * 8, 'cost': list(cost_)}, ('quarter',))
ap = call('timeseries.ardl', table=tid_p, y='price', time='quarter', inputs=['cost'], maxlag=4, maxorder=4, h=8)
check('simulated price on cost: ARDL chosen by AIC, no error', ap.get('error'), None)
lrp = {r_['term']: r_['estimate'] for r_ in ap['long_run']}
check.near('... the long-run cost coefficient near the simulated 0.75', lrp['cost'], 0.75, abs_=0.08)
check('... the bounds test rejects no level relationship', (ap['bounds']['verdict'], ap['bounds']['k']), ('reject', 1))
sel_p = ardl_select_order(pd.Series(price_, name='price'), 4, pd.DataFrame({'cost': cost_[:176]}), 4, ic='aic', trend='c')
res_p = sel_p.model.fit()
near_all('... the estimates are ardl_select_order\'s model\'s', [p['estimate'] for p in ap['params']['rows']], res_p.params, rel=1e-10)
pp = res_p.get_prediction(start=176, end=183, exog_oos=pd.DataFrame({'cost': cost_[176:]})).summary_frame(alpha=0.05)
near_all('... forecasts with the 8 future costs from the table (get_prediction with exog_oos)', ap['forecast']['mean'] + ap['forecast']['lower'], list(pp['mean']) + list(pp['mean_ci_lower']), rel=1e-10)
check('... the forecast quarters continue the dates', (ap['forecast']['t'][0], ap['forecast']['t'][7]), (float(ms('2024-01-01')), float(ms('2025-10-01'))))
check('... the future inputs are noted', any('future values come from the rows after' in s_ for s_ in ap['notes']), True)
check('ARDL needs inputs', 'error' in call('timeseries.ardl', table=tid_p, y='price', inputs=[]), True)
check('a bounds test case must go with the trend', 'error' in call('timeseries.ardl', table=tid_p, y='price', inputs=['cost'], trend='c', case=5), True)
check('too wide a global search is refused', 'error' in call('timeseries.ardl', table=tid_d, y='lrm', inputs=['lry', 'ibo', 'ide'], maxlag=3, maxorder=3, glob=True), True)
ag = call('timeseries.ardl', table=tid_d, y='lrm', time='period', inputs=['lry', 'ibo'], maxlag=2, maxorder=2, ic='bic', glob=True, h=0)
ref_g = ardl_select_order(dan.lrm, 2, dan[['lry', 'ibo']], 2, ic='bic', glob=True, trend='c')
check('a global search: the order is ardl_select_order(glob=True)\'s', (ag.get('error'), ag['order']), (None, list(ref_g.model.ardl_order)))
check.near('... and its BIC is the best in the selection table', ag['selection'][0]['ic'], float(ref_g.bic.index[0]), rel=1e-12)

# ---- the code under each new result runs on a CSV export and gives the same numbers ------------------------------------------
ns = run_code(rb_['code'], csv)
check('the structural model code gives the same fit and forecasts', ns.get('error') or (bool(np.isclose(-2 * ns['res'].llf, rb_['stats']['m2ll'], rtol=1e-9)),
      bool(np.allclose(ns['res'].get_forecast(6, exog=ns['X_future']).predicted_mean, rb_['forecast']['mean'], rtol=1e-6))), (True, True))
# (read_csv's fast float parser can change the last bit of a value, which moves an optimum on a flat likelihood by about 1e-7)
nile_csv = pd.DataFrame({'year': nile['year'], 'volume': nile['volume']})
ns = run_code(un['code'], nile_csv)
check('the Nile code gives the same estimates', ns.get('error') or bool(np.allclose(ns['res'].params, [pn['sigma2.irregular'], pn['sigma2.level']], rtol=1e-9)), True)
for label_, res_ in (('HP', fh), ('Theta', th), ('subseries', ss_)):
    ns = run_code(res_['code'], csv)
    check(f'the {label_} code runs', ns.get('error'), None)
ns = run_code(fh['code'], csv)
check('the HP code gives the same trend', ns.get('error') or bool(np.allclose(ns['trend'], fh['trend'], rtol=1e-10)), True)
ns = run_code(th['code'], csv)
check('the Theta code gives the same forecasts and the report\'s interval', ns.get('error') or (bool(np.allclose(ns['fc'], th['forecast']['mean'], rtol=1e-12)),
      bool(np.allclose(ns['fc'] + ns['half'], th['forecast']['upper'], rtol=1e-6))), (True, True))
macro_csv = pd.DataFrame({'quarter': [t.strftime('%Y-%m-%d') for t in qdates], 'unemp': macro['unemp'], 'realgdp': np.log(macro['realgdp'])})
ns = run_code(fb['code'], macro_csv)
check('the Baxter-King code gives the same cycle', ns.get('error') or bool(np.allclose(ns['cycle'], fb['cycle'][12:-12], rtol=1e-10)), True)
ns = run_code(zr['code'], pd.DataFrame({'x': zb}))
check('the Zivot-Andrews code runs', ns.get('error'), None)
dan_csv = pd.DataFrame({'period': [t.strftime('%Y-%m-%d') for t in dan.index], **{c: dan[c] for c in ('lrm', 'lry', 'ibo', 'ide')}})
ns = run_code(ad['code'], dan_csv)
check('the ARDL code gives the same fit and bounds statistic', ns.get('error') or (bool(np.allclose(ns['res'].params, [p['estimate'] for p in ad['params']['rows']], rtol=1e-10)),
      bool(np.isclose(ns['bt'].stat, ad['bounds']['stat'], rtol=1e-10))), (True, True))
price_csv = pd.DataFrame({'quarter': [t.strftime('%Y-%m-%d') for t in qd2], 'price': list(price_) + [np.nan] * 8, 'cost': cost_})
ns = run_code(ap['code'], price_csv)
check('the ARDL forecast code gives the same forecasts', ns.get('error') or bool(np.allclose(ns['res'].get_prediction(start=176, end=183, exog_oos=ns['X_future']).predicted_mean,
      ap['forecast']['mean'], rtol=1e-10)), True)
ns = run_code(mg['code'], pd.DataFrame({'growth': gs}))
check('the regime switching code gives the same fit', ns.get('error') or bool(np.isclose(ns['res'].llf, -mg['stats']['m2ll'] / 2, rtol=1e-10)), True)
check('every new result has its code', all(bool(x.get('code')) for x in (un, rb_, mg, fh, fb, fc_, ss_, th, zr, ad, ap)), True)

# ==== the graphs' matplotlib code =============================================================================
# Every graph's recipe (plot_code), put together as the page puts it together
# (timeseries.assemble, the page's recipe()), runs with matplotlib's Agg backend
# on the table's CSV export as File > Export CSV writes it (every row, dates as
# text), and the figure it draws is checked against the report's numbers: the
# series' points and lines with their gaps, the fits, the forecasts from the
# last prediction with their bands, the one-step intervals, the diagnostics
# charts' bars and ±2 standard error marks, the panels, labels, titles, size.
from test_charts import PROBE_MORE, close, strip_show

DAY = 86400000.0
# The panels' titles are on their left, as the page's labels are: PROBE_MORE
# reads the centred ones, so each axes' left title is read here too.
LEFT = r'''
def _ts_left():
    import matplotlib.pyplot as _plt
    return [[ax.get_title(loc="left") for ax in _plt.figure(n).axes] for n in _plt.get_fignums()]
'''


def run_more(code, frame):
    """test_charts.run_snippet_more, with each axes' left title as 'left'."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.close('all')
    with tempfile.TemporaryDirectory() as tmp:
        frame.to_csv(os.path.join(tmp, 'data.csv'), index=False)
        here = os.getcwd()
        os.chdir(tmp)
        ns = {'__name__': '__main__'}
        try:
            with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter('ignore')
                exec(strip_show(code), ns)
                exec(PROBE_MORE + LEFT, ns)
                out, left = ns['_smui_figures_more'](), ns['_ts_left']()
            for F, L in zip(out['figures'], left):
                for A, t in zip(F['axes'], L):
                    A['left'] = t
            return out, None
        except Exception as e:  # reported as a failed check
            return None, f'{type(e).__name__}: {e}'
        finally:
            os.chdir(here)
            plt.close('all')


def draw(label, parts, frame, flags=None, size=(620, 300), color='#3a7d44'):
    """A recipe put together with the page's display flags, size and colour,
    run on frame (as data.csv): the figure it draws, and the code."""
    code = ts.assemble(parts, flags or {}, size, color)
    out, err = run_more(code, frame)
    check(f'{label}: the code runs', err, None)
    check(f'{label}: one figure, plt.show() last', (len(out['figures']) if out else 0, code.rstrip().rsplit('\n', 1)[-1]), (1, 'plt.show()'))
    return (out['figures'][0] if out and out['figures'] else None), code


def pairs(xs, ys):
    return [(a, b) for a, b in zip(xs, ys) if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)]


def lines_of(A):
    """Each line of an axes (its properties, its finite points; x in the
    axis's units, a date axis in days)."""
    return [(ln, pairs([q[0] for q in xy], [q[1] for q in xy])) for ln, xy in zip(A['lines'], A['xy_lines'])]


def line(A, xs, ys, rel=1e-7, abs_=1e-9, **props):
    """The line of A with these points (the missing ones left out) and properties, or None."""
    want = pairs(xs, ys)
    for ln, p in lines_of(A):
        if len(p) == len(want) and all(close(a, c, rel, abs_) and close(b, d, rel, abs_) for (a, b), (c, d) in zip(p, want)) \
                and all(ln.get(k) == v for k, v in props.items()):
            return ln
    return None


def hline(A, v, rel=1e-9):
    return any(len(p) == 2 and close([p[0][0], p[1][0]], [0, 1]) and close([p[0][1], p[1][1]], [v, v], rel) for _, p in lines_of(A))


def vline(A, v, rel=1e-9):
    return any(len(p) == 2 and close([p[0][1], p[1][1]], [0, 1]) and close([p[0][0], p[1][0]], [v, v], rel) for _, p in lines_of(A))


def worst(got, want):
    """The largest relative difference of two lists of numbers (inf when their lengths or their gaps differ)."""
    if len(got) != len(want):
        return float('inf')
    d = 0.0
    for a, b in zip(got, want):
        if (a is None or not math.isfinite(a)) != (b is None or not math.isfinite(b)):
            return float('inf')
        if a is not None and b is not None and math.isfinite(a):
            d = max(d, abs(a - b) / max(1.0, abs(b)))
    return d


CAPTIONS = {'acf': 'Autocorrelation', 'pacf': 'Partial Autocorrelation', 'variogram': 'Variogram', 'ar': 'AR Coefficients'}


def check_diag(label, codes, D, frame, keys=('acf', 'pacf', 'variogram', 'ar'), residual=False):
    """The diagnostics charts against the report's tables: a bar per lag, its
    length the value, ±2 standard error marks, the page's range, the caption."""
    for key in keys:
        F, _ = draw(f'{label}: the {CAPTIONS[key]} chart', codes[key], frame)
        if not F:
            continue
        A = F['axes'][0]
        lags, vals = (D[key]['lag'], D[key]['r']) if key in ('acf', 'pacf') else (D[key]['lag'], D[key]['v' if key == 'variogram' else 'coef'])
        bars = A['bars']
        check.near(f'{label}: {key}: a bar per lag, as long as the value', worst([b['w'] for b in bars], vals), 0, abs_=1e-9)
        check(f'{label}: {key}: the bars at the lags, lag by lag down', ([round(b['y'] + b['h'] / 2, 9) for b in bars], A['yinverted']), (lags, True))
        if key in ('acf', 'pacf'):
            se = D[key]['se'][1:]
            marks = [p for ln, p in lines_of(A) if ln['marker'] == '|']
            want = sorted([(round(2 * s, 9), lg) for s, lg in zip(se, lags[1:])] + [(round(-2 * s, 9), lg) for s, lg in zip(se, lags[1:])])
            check(f'{label}: {key}: the ±2 standard error marks', sorted((round(a, 9), round(b)) for p in marks for a, b in p), want)
            check(f'{label}: {key}: from −1 to 1', A['xlim'], [-1.0, 1.0])
        else:
            m = max(1e-12, max(abs(v) for v in vals if v is not None))
            check.near(f'{label}: {key}: over the range of the values, as the page scales them', worst(A['xlim'], [-m if any(v < 0 for v in vals if v is not None) else 0.0, m]), 0, abs_=1e-12)
        title = ('Residual ' + CAPTIONS[key]) if residual and key in ('acf', 'pacf') else CAPTIONS[key]
        check(f'{label}: {key}: the caption as its title', A['title'], title)


def check_model(label, R, frame, tx, values, flags=None, size=(620, 300), rel=1e-6, yname='sales'):
    """A model's forecast graph, with and without its points and interval,
    its residuals and their diagnostics, against its result. tx: the time
    axis in the axis's units; values: the series."""
    pc, fc = R['plot_code'], R['forecast']
    F, _ = draw(f'{label}: the forecast graph', pc['forecast'], frame, {'points': True, 'pi': True, 'onestep': True, **(flags or {})}, size)
    if not F:
        return
    A = F['axes'][0]
    last = len(tx) - 1
    check(f'{label}: the data as points', line(A, tx, values, marker='o', ls='None', color='#2f6690ff') is not None, True)
    check(f'{label}: the one-step-ahead predictions in the model\'s colour', line(A, tx, R['fitted'], rel, marker='None', ls='-', color='#3a7d44ff') is not None, True)
    onestep = any(v is not None for v in R['fit_lo'])
    if onestep:
        check(f'{label}: the one-step prediction interval, dotted', [line(A, tx, R[k], rel, ls=':') is not None for k in ('fit_lo', 'fit_hi')], [True, True])
    if fc['t']:
        xf = [tx[last]] + [v / DAY for v in fc['t']] if A['xaxis_date'] else [tx[last]] + fc['t']
        y0 = R['fitted'][last] if R['fitted'][last] is not None else values[last]
        lo0 = R['fit_lo'][last] if R['fit_lo'][last] is not None else fc['lower'][0]
        hi0 = R['fit_hi'][last] if R['fit_hi'][last] is not None else fc['upper'][0]
        check(f'{label}: the forecasts, from the last prediction', line(A, xf, [y0] + fc['mean'], rel, marker='o') is not None, True)
        check(f'{label}: the prediction interval\'s edges', [line(A, xf, [hi0] + fc['upper'], rel) is not None, line(A, xf, [lo0] + fc['lower'], rel) is not None], [True, True])
        check(f'{label}: ... filled', len(A['polys']), 1)
    check(f'{label}: the end of the data', vline(A, tx[last]), True)
    check(f'{label}: the labels and the title', (A['ylabel'], A['title'], F['size']), (yname, f'{R["name"]} forecast', [size[0] / 100, size[1] / 100]))
    F, _ = draw(f'{label}: the forecast graph without points or interval', pc['forecast'], frame, {'onestep': True, **(flags or {})}, size)
    if F:
        A = F['axes'][0]
        dotted = [p for ln, p in lines_of(A) if ln['ls'] == ':' and len(p) > 2]   # the one-step interval (not the end-of-data line)
        check(f'{label}: ... no points, no band, no one-step interval', (line(A, tx, values, marker='o', ls='None') is None, len(A['polys']), len(dotted)), (True, 0, 0))
        check(f'{label}: ... the predictions still there', line(A, tx, R['fitted'], rel) is not None, True)
    F, _ = draw(f'{label}: the residual graph', pc['resid'], frame, size=(620, 220))
    if F:
        A = F['axes'][0]
        check(f'{label}: the residuals as points, in the model\'s colour; the zero line', (line(A, tx, R['resid'], rel, marker='o', color='#3a7d44ff') is not None, hline(A, 0.0)), (True, True))
        check(f'{label}: ... the labels', (A['ylabel'], A['title']), ('Residual', f'{R["name"]} residuals'))
    if R['resid_diag'] and not R['resid_diag'].get('error'):
        check_diag(f'{label} residuals', pc, R['resid_diag'], frame, residual=True)


# ---- the series and what is made from it: the monthly sales, two rows excluded
ex = [30, 31]
base_g = dict(table=tid, y='sales', time='month', excluded=ex, nlags=25)
Sg = call('timeseries.series', **base_g)
tday = [v / DAY for v in Sg['t']]
F, code = draw('the series graph', Sg['plot_code']['series'], csv, {'points': True, 'lines': True, 'mean': True}, (560, 260))
A = F['axes'][0]
check('the series graph: the points and the lines between them', line(A, tday, Sg['values'], marker='o', ls='-', color='#2f6690ff') is not None, True)
check('... every slot, the excluded rows missing in their place', (len(A['xy_lines'][0]), A['xy_lines'][0][30][1], A['xy_lines'][0][31][1]), (120, None, None))
check('... the Mean Line at the mean', hline(A, Sg['diag']['mean']), True)
check('... a date axis, the labels, the title, the size', (A['xaxis_date'], A['xlabel'], A['ylabel'], A['title'], F['size']), (True, 'month', 'sales', 'sales time series', [5.6, 2.6]))
check('... the table read as exported, the dates parsed as the Time ID', ('pd.read_csv("data.csv"' in code, 'df["month"] = pd.to_datetime(df["month"])' in code), (True, True))
for flags_, want in (({'points': True}, [('o', 'None')]), ({'lines': True}, [('None', '-')]), ({}, [])):
    F2, _ = draw(f'the series graph with {", ".join(flags_) or "neither points nor lines"}', Sg['plot_code']['series'], csv, flags_, (560, 260))
    if F2:
        check(f'... {", ".join(flags_) or "neither"}: as the page draws it, no mean line', [(ln['marker'], ln['ls']) for ln in F2['axes'][0]['lines']], want)
check_diag('the series', Sg['plot_code'], Sg['diag'], csv)
ns = run_code('\n'.join(['import numpy as np', 'import pandas as pd', 'df = pd.read_csv("data.csv", float_precision="round_trip")', *Sg['plot_frag']['series']]), csv)
check('the series lines for the page\'s lag plot: y and t as the graph has them', ns.get('error') or (worst(list(ns['y'].to_numpy()), Sg['values']), len(ns['t'])), (0.0, 120))

Dg = call('timeseries.difference', **base_g, d=1, D=1, s=12)
F, _ = draw('the difference graph', Dg['plot_code']['series'], csv, {'points': True, 'lines': True, 'mean': True}, (560, 260))
A = F['axes'][0]
check('the difference graph: the differenced series, from the 14th slot', line(A, tday, Dg['values'], marker='o', ls='-') is not None, True)
check('... its mean line, labels and title', (hline(A, Dg['diag']['mean']), A['ylabel'], A['title']), (True, 'sales differenced', 'sales differenced time series'))
check_diag('the difference', Dg['plot_code'], Dg['diag'], csv)

for kind_, fn_, extra_, label_, dname_ in (('trend', 'timeseries.detrend', {}, 'linear trend', 'Detrended sales'), ('cycle', 'timeseries.decycle', {'units': 12}, 'cycle', 'Decycled sales')):
    R = call(fn_, **base_g, **extra_)
    F, _ = draw(f'the {label_} graph', R['plot_code']['fit'], csv, size=(560, 230))
    A = F['axes'][0]
    check(f'the {label_} graph: the series and the fitted {label_} in red', (line(A, tday, Sg['values'], marker='o', ls='-') is not None,
                                                                          line(A, tday, R[kind_], marker='None', color='#b0413eff') is not None), (True, True))
    check(f'... its title', A['title'], f'sales {label_}')
    F, _ = draw(f'the {dname_} graph', R['plot_code']['series'], csv, size=(560, 230))
    check(f'the {dname_} graph: the series less the {label_}', (line(F['axes'][0], tday, R['values'], marker='o') is not None, F['axes'][0]['title']), (True, f'{dname_} time series'))
    check_diag(dname_, R['plot_code'], R['diag'], csv, keys=('acf', 'pacf'))

for method_, extra_, label_ in (('stl', {'robust': True}, 'STL Decomposition (period 12, robust)'), ('classical', {'model': 'multiplicative'}, 'Seasonal Decomposition (multiplicative, period 12)')):
    R = call('timeseries.decompose', **base_g, method=method_, period=12, **extra_)
    F, _ = draw(label_, R['plot_code']['decomp'], csv, size=(620, 520))
    ax_ = F['axes']
    check(f'{label_}: four panels with the page\'s titles, the label as the title', ([a['left'] for a in ax_], F['suptitle'], ax_[3]['xlabel']),
          (['Original and adjusted', 'Trend', 'Seasonal', 'Irregular'], label_, 'month'))
    check(f'{label_}: the series and the seasonally adjusted series', (line(ax_[0], tday, Sg['values'], marker='o') is not None, line(ax_[0], tday, R['adjusted'], color='#b0413eff') is not None), (True, True))
    check(f'{label_}: the trend, the seasonal and the irregular parts', [line(ax_[i], tday, R[k]) is not None for i, k in ((1, 'trend'), (2, 'seasonal'), (3, 'resid'))], [True] * 3)

R = call('timeseries.spectral', **base_g)
F, _ = draw('the spectral density by period', R['plot_code']['period'], csv, size=(420, 250))
A = F['axes'][0]
check('the spectral density by period: the smoothed periodogram, on a log axis', (line(A, R['period'], R['density'], 1e-9, color='#b0413eff') is not None, A['xscale']), (True, 'log'))
check('... its labels', (A['xlabel'], A['ylabel'], A['title']), ('Period', 'Spectral density', 'sales spectral density by period'))
F, _ = draw('the spectral density by frequency', R['plot_code']['frequency'], csv, size=(420, 270))
A = F['axes'][0]
check('the spectral density by frequency: the periodogram as points, scaled by 1/(4π)', line(A, R['frequency'], [v / (4 * math.pi) for v in R['periodogram']], 1e-9, marker='o', ls='None') is not None, True)
check('... the density, and the legend', (line(A, R['frequency'], R['density'], 1e-9) is not None, F['legend']), (True, ['Periodogram', 'Spectral density']))

for ex_, label_ in (([], 'every value present'), (ex, 'with missing values')):
    R = call('timeseries.ccf', table=tid, y='sales', time='month', excluded=ex_, nlags=25, inputs=['promotion', 'temperature'])
    F, _ = draw(f'the cross correlation charts ({label_})', R['plot_code']['ccf'], csv)
    for A, c_ in zip(F['axes'], R['inputs']):
        check.near(f'... {c_["input"]} ({label_}): a bar per lag, as long as the correlation', worst([b['w'] for b in A['bars']], c_['r']), 0, abs_=1e-9)
        check(f'... {c_["input"]}: at the lags −K … K, the caption as the title', ([round(b['y'] + b['h'] / 2) for b in A['bars']], A['title']), (c_['lag'], f'sales with {c_["input"]}'))
        marks = sorted((round(a, 9), round(b)) for ln, p in lines_of(A) if ln['marker'] == '|' for a, b in p)
        check(f'... {c_["input"]}: ±2 standard errors at every lag', marks, sorted([(round(s * 2 * e_, 9), lg) for e_, lg in zip(c_['se'], c_['lag']) for s in (1, -1)]))
    check(f'... ({label_}) the code keeps the By group and the report\'s rows (the fix: it read every row before)', 'd.loc[y.index, name]' in ts.assemble(R['plot_code']['ccf']), True)

Zg = call('timeseries.zivot', **base_g)
F, _ = draw('the Zivot-Andrews graph (dates)', Zg['plot_code']['breaks'], csv, size=(560, 220))
A = F['axes'][0]
brk = list(dict.fromkeys(t_['break'] for t_ in Zg['tests'] if not t_.get('error')))
check('the Zivot-Andrews graph: the series, and a line at each break date', (line(A, tday, Sg['values'], marker='o') is not None, [vline(A, b / DAY) for b in brk]), (True, [True] * len(brk)))
models_at = {b: [{'c': 'intercept', 't': 'trend', 'ct': 'both'}[t_['regression']] for t_ in Zg['tests'] if not t_.get('error') and t_['break'] == b] for b in brk}
check('... labelled with the models that put it there', [t_['s'] for t_ in A['texts']], [' ' + ', '.join(models_at[b]) for b in brk])
check('... the dash of each date, as the page draws them', [ln['ls'] for ln in A['lines'][1:]], [[':', '--', '-.'][i % 3] for i in range(len(brk))])
F, _ = draw('the Zivot-Andrews graph (no Time ID)', zr['plot_code']['breaks'], pd.DataFrame({'x': zb}), size=(560, 220))
brk = list(dict.fromkeys(t_['break'] for t_ in zr['tests'] if not t_.get('error')))
check('... on the row numbers: a line at each break', [vline(F['axes'][0], b) for b in brk], [True] * len(brk))

R = call('timeseries.subseries', **base_g, period=12)
F, _ = draw('the seasonal subseries plot', R['plot_code']['subseries'], csv, size=(720, 300))
A = F['axes'][0]
check('the seasonal subseries plot: each month\'s values in time order, side by side', [line(A, s_['x'], s_['values'], marker='o') is not None for s_ in R['seasons']], [True] * 12)
check('... and its mean', [line(A, [s_['x'][0] - 0.35, s_['x'][-1] + 0.35], [s_['mean']] * 2, 1e-9, color='#b0413eff') is not None for s_ in R['seasons']], [True] * 12)
check('... the ticks at the seasons, named', (close(A['xticks'], [(s_['x'][0] + s_['x'][-1]) / 2 for s_ in R['seasons']]), A['xticklabels']), (True, [s_['label'] for s_ in R['seasons']]))

for m_ in ('hp', 'bk', 'cf'):
    R = call('timeseries.filter', **base_g, method=m_)
    F, _ = draw(R['label'], R['plot_code']['filter'], csv, size=(620, 400))
    ax_, cx_ = F['axes']
    check(f'{R["label"]}: the series as points and the trend', (line(ax_, tday, Sg['values'], marker='o', ls='None') is not None, line(ax_, tday, R['trend'], 1e-9, color='#b0413eff') is not None), (True, True))
    check(f'{R["label"]}: the cycle, missing where the series is', line(cx_, tday, R['cycle'], 1e-9) is not None, True)
    check(f'{R["label"]}: the panels\' titles, the label as the title', (ax_['left'], cx_['left'], F['suptitle']),
          ('sales and y − cycle' if m_ == 'bk' else 'sales and trend', 'Cycle', R['label']))

# ---- the models' graphs
fut_csv = pd.DataFrame({'month': [pd.Timestamp(v, unit='ms').strftime('%Y-%m-%d') for v in months + [ms('2026-01-01'), ms('2026-02-01')]],
                        'sales': list(y) + [None, None], 'promotion': promo + [1, 0]})
arma = call('timeseries.arima', **base_g, p=1, q=1, h=12)
check_model('ARMA(1, 1)', arma, csv, tday, Sg['values'])
sarima = call('timeseries.arima', **base_g, q=1, D=1, Q=1, s=12, h=12)
check_model('seasonal ARIMA', sarima, csv, tday, Sg['values'])
tf = call('timeseries.arima', table=fut_tid, y='sales', time='month', excluded=ex, p=1, h=4, inputs=[{'name': 'promotion', 'lag': 1, 'num': 1}])
check_model('a transfer function (the future inputs from the table, then held)', tf, fut_csv, tday, Sg['values'])
for m_ in ('simple', 'double', 'linear', 'damped', 'seasonal', 'winters'):
    check_model(f'smoothing: {m_}', call('timeseries.smooth', **base_g, method=m_, s=12, h=12), csv, tday, Sg['values'])
check_model('smoothing: multiplicative Winters (simulated intervals)', call('timeseries.smooth', **base_g, method='winters', s=12, h=12, multiplicative=True), csv, tday, Sg['values'])
for e_, t_, s_ in (('add', 'A', 'N'), ('mul', 'Ad', 'M')):
    Eg = call('timeseries.ets', **base_g, error=e_, trend=t_, seasonal=s_, s=12, h=12)
    check_model(f'ETS({e_}, {t_}, {s_})', Eg, csv, tday, Sg['values'])
    for k_, v_ in Eg['states'].items():
        F, _ = draw(f'ETS({e_}, {t_}, {s_}): the {k_} state', Eg['plot_code']['states'][k_], csv, size=(520, 180))
        check(f'... its line and labels', (line(F['axes'][0], tday, v_, 1e-6, color='#3a7d44ff') is not None, F['axes'][0]['ylabel'], F['axes'][0]['title']),
              (True, k_[:1].upper() + k_[1:], f'{Eg["name"]} {k_}'))
Ug = call('timeseries.structural', **base_g, trend='local linear trend', seasonal=12, inputs=['promotion'], h=12)
check_model('a structural model', Ug, csv, tday, Sg['values'])
n_ = len(Ug['components'])
F, _ = draw('the structural model\'s components', Ug['plot_code']['components'], csv, size=(640, max(260, 125 * n_ + 60)))
check('... a panel for each component, named as the page names them', [a['left'] for a in F['axes']], [c_['label'] for c_ in Ug['components']])
check('... each smoothed component, in the model\'s colour', [line(a, tday, c_['mean'], 1e-6, color='#3a7d44ff') is not None for a, c_ in zip(F['axes'], Ug['components'])], [True] * n_)
check('... a band where the page has one', [len(a['polys']) for a in F['axes']], [1 if c_['lower'] else 0 for c_ in Ug['components']])
check('... the data in the level panel', line(F['axes'][0], tday, Sg['values'], marker='o', ls='None', color='#786b5dff') is not None, True)
Tg = call('timeseries.theta', **base_g, period=12, h=12)
check_model('the Theta model', Tg, csv, tday, Sg['values'])
T2 = dict(Tg, forecast=dict(Tg['forecast'], lower=Tg['forecast']['sm_lower'], upper=Tg['forecast']['sm_upper']))
check_model('the Theta model with statsmodels\' intervals', T2, csv, tday, Sg['values'], flags={'smpi': True})
tg_ = [float(i + 1) for i in range(len(gs))]
g_csv = pd.DataFrame({'growth': gs})
check_model('regime switching (no Time ID: the row numbers)', mg, g_csv, tg_, list(gs), yname='growth')
F, _ = draw('the regimes', mg['plot_code']['regimes'], g_csv, size=(620, 290))
A = F['axes'][0]
step_ = (tg_[-1] - tg_[0]) / (len(tg_) - 1)
edges_ = [tg_[0] - step_ / 2] + [(a + b) / 2 for a, b in zip(tg_[:-1], tg_[1:])] + [tg_[-1] + step_ / 2]
runs, i_ = [], 0
while i_ < len(mg['most']):
    j_ = i_ + 1
    while j_ < len(mg['most']) and mg['most'][j_] == mg['most'][i_]:
        j_ += 1
    if mg['most'][i_] is not None:
        runs.append((edges_[i_], edges_[j_] - edges_[i_]))
    i_ = j_
check('the regimes: a band over each run of the most likely regime, as the page shades them', [(round(b['x'], 9), round(b['w'], 9)) for b in A['bars']], [(round(a, 9), round(b, 9)) for a, b in runs])
check('... the series in ink, the legend', (line(A, tg_, list(gs), marker='o', color='#352921ff') is not None, F['legend']), (True, ['growth', 'Regime 0 most likely', 'Regime 1 most likely']))
F, _ = draw('the regime probabilities', mg['plot_code']['prob'], g_csv, {'fprob': True}, size=(620, 260))
A = F['axes'][0]
check('the regime probabilities: the smoothed ones, with points', [line(A, tg_, p_, 1e-6, marker='o') is not None for p_ in mg['prob']], [True, True])
check('... the filtered ones dotted (Filtered Probabilities)', [line(A, tg_, p_, 1e-6, ls=':') is not None for p_ in mg['fprob']], [True, True])
check('... from 0 to 1, the legend', (A['ylim'], F['legend']), ([-0.03, 1.03], ['Regime 0', 'Regime 1', 'Regime 0 filtered', 'Regime 1 filtered']))
F, _ = draw('the regime probabilities without the filtered ones', mg['plot_code']['prob'], g_csv, size=(620, 260))
check('... two lines then', len(F['axes'][0]['lines']), 2)
qday = [ms(t_) / DAY for t_ in qd2[:176]]
check_model('ARDL (the future costs from the table)', ap, price_csv, qday, list(price_), yname='price')
check('... its forecasts continue the quarters', [round(v / DAY) for v in ap['forecast']['t'][:2]], [round(ms(t_) / DAY) for t_ in qd2[176:178]])
Ms_ = call('timeseries.arima', table=tid_sun, y='SUNACTIVITY', time='YEAR', p=2, h=5)
check_model('AR(2) on a numeric Time ID', Ms_, sun_csv, [float(v) for v in sun['YEAR']], list(sun['SUNACTIVITY']), yname='SUNACTIVITY')
check('... the forecasts at the next years', Ms_['forecast']['t'], [float(sun['YEAR'].iloc[-1]) + k_ for k_ in range(1, 6)])

# ---- rows the report leaves out: By, a Local Data Filter, an exclusion, no Time ID
# The page sends a group's rows without those a Local Data Filter takes out; the
# code drops them (it read them before), and counts an excluded row as missing.
rng_b = np.random.default_rng(7)
reg_b = ['North' if i % 2 == 0 else 'South' for i in range(80)]
x_b = [round(v, 3) for v in np.cumsum(rng_b.normal(size=80)) + 10]
z_b = [round(v, 3) for v in rng_b.normal(size=80)]
tid_b = table({'region': reg_b, 'x': x_b, 'z': z_b})
north = [i for i in range(80) if reg_b[i] == 'North']
filtered_b = north[5:8]
rows_b = [i for i in north if i not in filtered_b]
base_b = dict(table=tid_b, y='x', rows=rows_b, excluded=[north[12]], where=[{'column': 'region', 'value': 'North'}], nlags=10)
csv_b = pd.DataFrame({'region': reg_b, 'x': x_b, 'z': z_b})
Sb = call('timeseries.series', **base_b)
check('filtered rows: the statistics code drops them', f'df = df.drop(index={filtered_b})   # the rows the report leaves out' in Sb['code'], True)
ns = run_code(Sb['code'], csv_b)
check('... and gives the report\'s series, the excluded row missing in its place', ns.get('error') or worst(list(ns['y'].to_numpy()), Sb['values']), 0.0)
check('... the report\'s mean and N', ns.get('error') or (round(float(ns['y'].mean()), 9), int(ns['y'].count())), (round(Sb['diag']['mean'], 9), Sb['diag']['n']))
F, _ = draw('the series graph (By, a filter, an exclusion, no Time ID)', Sb['plot_code']['series'], csv_b, {'points': True, 'lines': True}, (560, 260))
check('... on the row numbers of the table, as the page draws it', (line(F['axes'][0], Sb['t'], Sb['values'], marker='o') is not None, F['axes'][0]['xlabel']), (True, 'Row'))
Cb = call('timeseries.ccf', **base_b, inputs=['z'])
check('the cross correlation code keeps the By group now (it read every row before)', 'df = df[df["region"] == \'North\']' in Cb['code'], True)
F, _ = draw('the cross correlation chart (By, a filter)', Cb['plot_code']['ccf'], csv_b)
check.near('... the report\'s correlations', worst([b['w'] for b in F['axes'][0]['bars']], Cb['inputs'][0]['r']), 0, abs_=1e-9)
Ab = call('timeseries.arima', **base_b, p=1, h=3)
check_model('AR(1) on the filtered group', Ab, csv_b, Sb['t'], Sb['values'], yname='x')
check('... its forecasts continue the row numbers', Ab['forecast']['t'], [Sb['t'][-1] + k_ for k_ in (1, 2, 3)])

# ---- names ------------------------------------------------------------------------------------------------
check("JMP's ARIMA names", [ts.arima_name(1, 0, 0), ts.arima_name(0, 0, 2), ts.arima_name(1, 0, 1), ts.arima_name(0, 1, 0), ts.arima_name(0, 1, 1), ts.arima_name(2, 1, 0), ts.arima_name(1, 1, 1)],
      ['AR(1)', 'MA(2)', 'ARMA(1, 1)', 'I(1)', 'IMA(1, 1)', 'ARI(2, 1)', 'ARIMA(1, 1, 1)'])
check('every result has its code', all(bool(x.get('code')) for x in (r, rd, rt_, rcy, rdc, rs, rx, m, rb, re_)), True)

# ==== Forecast on Holdback, benchmarks, the moving average, constraints, Box-Cox, averages, runs tests, cross-validation ====
# Each against statsmodels (or pandas) called directly on the training part,
# or against the closed forms written out here.
from scipy.special import boxcox as sp_boxcox, inv_boxcox as sp_inv_boxcox
from statsmodels.sandbox.stats.runs import runstest_1samp
HB = 12
y_tr, y_ho = y[:n - HB], y[n - HB:]


def hb_by_hand(actual, fc, train, lag):
    e = np.asarray(actual, dtype=float) - np.asarray(fc, dtype=float)
    ok = np.isfinite(e)
    e, a = e[ok], np.asarray(actual, dtype=float)[ok]
    scale = np.mean(np.abs(train[lag:] - train[:-lag]))
    return {'n': int(ok.sum()), 'rmse': math.sqrt(np.mean(e ** 2)), 'mse': np.mean(e ** 2), 'mae': np.mean(np.abs(e)), 'mape': 100 * np.mean(np.abs(e / a)),
            'me': np.mean(e), 'mase': np.mean(np.abs(e)) / scale}


def check_hb(label, R, fc, train=y_tr, actual=y_ho, lag=12, rel=1e-7):
    want = hb_by_hand(actual, fc, train, lag)
    check(f'{label}: holdback N', R['holdback']['n'], want['n'])
    near_all(f'{label}: holdback RMSE, MSE, MAE, MAPE, mean error and MASE (the MAE over the training values\' in-sample seasonal naive MAE)',
             [R['holdback'][k] for k in ('rmse', 'mse', 'mae', 'mape', 'me', 'mase')], [want[k] for k in ('rmse', 'mse', 'mae', 'mape', 'me', 'mase')], rel=rel)


def hb_from_code(label, R, frame, lag=12, rel=1e-6):
    """The model's code (with its holdback part) run on the CSV: the same statistics."""
    ns = run_code(R['code'], frame)
    if ns.get('error'):
        check(f'{label}: the code with its holdback part runs', ns['error'], None)
        return
    got = ns['holdback_stats'](ns['y_hold'], ns['f_mean'], ns['y'], lag)
    near_all(f'{label}: the code gives the report\'s holdback statistics', [got[k] for k in ('RMSE', 'MAE', 'MAPE', 'Mean Error', 'MASE')],
             [R['holdback'][k] for k in ('rmse', 'mae', 'mape', 'me', 'mase')], rel=rel)


# ---- Forecast on Holdback: every model fitted on the first n − h values, forecasting the last h
ha = call('timeseries.arima', table=tid, y='sales', time='month', p=1, h=HB, holdback=HB, season=12)
ref_ha = ARIMA(y_tr, order=(1, 0, 0), trend='c').fit()
check('holdback: no error; the model is fitted on the first n − h values', (ha.get('error'), ha['n'], len(ha['fitted'])), (None, n - HB, n - HB))
near_all('holdback AR(1): the estimates are ARIMA\'s on the training values', [p['estimate'] for p in ha['params']['rows']], ref_ha.params[:2], rel=1e-5)
near_all('... the forecasts of the held-back values are its get_forecast(12)', ha['forecast']['mean'], ref_ha.get_forecast(HB).predicted_mean, rel=1e-6)
check('... at the held-back months', ha['forecast']['t'], [float(v) for v in months[n - HB:]])
check_hb('holdback AR(1)', ha, ref_ha.get_forecast(HB).predicted_mean, rel=1e-6)
check('... the held-back values and the forecast errors come with the result', (ha['holdback']['actual'][:2], ha['holdback']['rows'][:2]), ([float(y_ho[0]), float(y_ho[1])], [n - HB, n - HB + 1]))
hb_from_code('holdback AR(1)', ha, csv)
hx = call('timeseries.arima', table=tid, y='sales', time='month', p=1, h=HB, holdback=HB, season=12, excluded=[113])
ref_hx = ARIMA(y_tr, order=(1, 0, 0), trend='c').fit()
y_hox = y_ho.copy()
y_hox[113 - (n - HB)] = np.nan
check_hb('an excluded row among the held-back ones: left out of the statistics', hx, ref_hx.get_forecast(HB).predicted_mean, actual=y_hox, rel=1e-6)
check('too long a holdback is an error', 'error' in call('timeseries.arima', table=tid, y='sales', p=1, h=118, holdback=118), True)
hw = call('timeseries.smooth', table=tid, y='sales', time='month', method='winters', s=12, h=HB, holdback=HB, season=12)
ref_hw = ExponentialSmoothing(y_tr, trend='add', seasonal='add', seasonal_periods=12, initialization_method='estimated').fit()
near_all('holdback Winters: the forecasts are holtwinters\' on the training values', hw['forecast']['mean'], ref_hw.forecast(HB), rel=1e-9)
check_hb('holdback Winters', hw, ref_hw.forecast(HB), rel=1e-9)
hb_from_code('holdback Winters', hw, csv)
he = call('timeseries.ets', table=tid, y='sales', time='month', error='mul', trend='A', seasonal='M', s=12, h=HB, holdback=HB, season=12)
ref_he = ETSModel(pd.Series(y_tr), error='mul', trend='add', seasonal='mul', seasonal_periods=12).fit(disp=False)
near_all('holdback ETS(M,A,M): the forecasts are ETSModel\'s on the training values', he['forecast']['mean'], ref_he.forecast(HB), rel=1e-7)
check_hb('holdback ETS(M,A,M)', he, ref_he.forecast(HB), rel=1e-7)
hb_from_code('holdback ETS(M,A,M)', he, csv, rel=1e-5)
ht = call('timeseries.arima', table=tid, y='sales', time='month', p=1, h=HB, holdback=HB, season=12, inputs=[{'name': 'promotion'}])
ref_ht = ARIMA(pd.Series(y_tr), exog=np.array(promo[:n - HB])[:, None], order=(1, 0, 0), trend='c').fit()
fc_ht = ref_ht.get_forecast(HB, exog=np.array(promo[n - HB:])[:, None]).predicted_mean
near_all('holdback transfer function: the forecasts take the held-back rows\' promotion', ht['forecast']['mean'], fc_ht, rel=1e-5)
check('... and say so', any('held-back row' in s_ for s_ in ht['notes']), True)
hb_from_code('holdback transfer function', ht, csv, rel=1e-5)
hu = call('timeseries.structural', table=tid, y='sales', time='month', trend='local linear trend', seasonal=12, inputs=['promotion'], h=HB, holdback=HB, season=12)
hb_from_code('holdback structural model with an input', hu, csv, rel=1e-5)
ys_tr = pd.Series(y_tr, index=pd.date_range('2016-01-01', periods=n - HB, freq='MS'))
ref_hu = UnobservedComponents(ys_tr, level='local linear trend', seasonal=12, stochastic_seasonal=True, exog=pd.DataFrame({'promotion': promo[:n - HB]}, index=ys_tr.index)).fit(**FIT)
near_all('... its forecasts are UnobservedComponents\' with the held-back inputs', hu['forecast']['mean'],
         ref_hu.get_forecast(HB, exog=np.array(promo[n - HB:])[:, None]).predicted_mean, rel=1e-5)
hth = call('timeseries.theta', table=tid, y='sales', time='month', period=12, h=HB, holdback=HB, season=12)
near_all('holdback Theta: ThetaModel on the training values', hth['forecast']['mean'], ThetaModel(y_tr, period=12).fit().forecast(HB), rel=1e-10)
hb_from_code('holdback Theta', hth, csv)
hp = call('timeseries.ardl', table=tid_p, y='price', time='quarter', inputs=['cost'], maxlag=2, maxorder=2, h=8, holdback=8, season=4)
sel_hp = ardl_select_order(pd.Series(price_[:168], name='price'), 2, pd.DataFrame({'cost': cost_[:168]}), 2, ic='aic', trend='c').model.fit()
fc_hp = sel_hp.get_prediction(start=168, end=175, exog_oos=pd.DataFrame({'cost': cost_[168:176]})).predicted_mean
near_all('holdback ARDL: the forecasts take the held-back quarters\' costs', hp['forecast']['mean'], fc_hp, rel=1e-8)
check_hb('holdback ARDL', hp, fc_hp, train=price_[:168], actual=price_[168:176], lag=4, rel=1e-8)
hb_from_code('holdback ARDL', hp, price_csv, lag=4)
hm = call('timeseries.markov', table=tid_g, y='growth', k=2, order=0, starts=0, holdback=10, h=10)
check('holdback regime switching: no forecasts, no holdback statistics', (hm.get('error'), hm['holdback']['rmse'], hm['holdback']['n']), (None, None, 0))

# the holdback graph: every value as points, the held-back span shaded, the forecasts at the held-back months
F, _ = draw('holdback: the forecast graph', ha['plot_code']['forecast'], csv, {'points': True, 'pi': True, 'onestep': True})
if F:
    A = F['axes'][0]
    tday_all = [v / DAY for v in months]
    check('holdback graph: every value as points, the held-back ones too', line(A, tday_all, list(y), marker='o', ls='None') is not None, True)
    check('... the one-step-ahead predictions over the training values', line(A, tday_all[:n - HB], ha['fitted'], 1e-6, marker='None', ls='-') is not None, True)
    xf = [tday_all[n - HB - 1]] + [v / DAY for v in ha['forecast']['t']]
    check('... the forecasts from the last training prediction over the held-back months', line(A, xf, [ha['fitted'][-1]] + ha['forecast']['mean'], 1e-6, marker='o') is not None, True)
    check('... the held-back span shaded, from the last training value to the last held-back one',
          any(close([b['x'], b['x'] + b['w']], [tday_all[n - HB - 1], tday_all[-1]], 1e-9) for b in A['bars']), True)
    check('... the end of the training values', vline(A, tday_all[n - HB - 1]), True)

# ---- benchmarks: Naive, Seasonal Naive, Drift, against SARIMAX and OLS on the differences
bn = call('timeseries.benchmark', table=tid, y='sales', time='month', method='naive', h=12)
sx_n = SARIMAX(y, order=(0, 1, 0)).fit(disp=False)
check('Naive: its name, k = 0 (DF = n − 1 one-step errors)', (bn['name'], bn['stats']['df']), ('Naive', n - 1))
near_all('Naive: every forecast the last value (SARIMAX(0, 1, 0))', bn['forecast']['mean'], sx_n.get_forecast(12).predicted_mean, rel=1e-9)
near_all('... standard errors σ√h, σ² the mean squared difference (SARIMAX\'s MLE)', bn['forecast']['se'], sx_n.get_forecast(12).se_mean, rel=2e-4)
near_all('... σ² exactly the mean squared difference', [bn['stats']['variance']], [np.mean(np.diff(y) ** 2)], rel=1e-12)
near_all('... the one-step predictions are the values before', bn['fitted'][1:], y[:-1], rel=1e-12)
bs = call('timeseries.benchmark', table=tid, y='sales', time='month', method='snaive', s=12, h=15)
sx_s = SARIMAX(y, order=(0, 0, 0), seasonal_order=(0, 1, 0, 12)).fit(disp=False)
check('Seasonal Naive: its name', bs['name'], 'Seasonal Naive(12)')
near_all('Seasonal Naive: the same season a period before (SARIMAX(0, 0, 0)(0, 1, 0)12)', bs['forecast']['mean'], sx_s.get_forecast(15).predicted_mean, rel=1e-9)
near_all('... standard errors σ√(k + 1) (SARIMAX\'s)', bs['forecast']['se'], sx_s.get_forecast(15).se_mean, rel=2e-4)
d12 = y[12:] - y[:-12]
near_all('... σ² the mean squared seasonal difference', [bs['stats']['variance']], [np.mean(d12 ** 2)], rel=1e-12)
bd = call('timeseries.benchmark', table=tid, y='sales', time='month', method='drift', h=10)
ols_d = sm.OLS(np.diff(y), np.ones(n - 1)).fit()
b_ = float(ols_d.params[0])
hh_ = np.arange(1, 11)
near_all('Drift: the last value plus h times the mean change (y_T − y_1)/(T − 1)', bd['forecast']['mean'], y[-1] + hh_ * b_, rel=1e-12)
near_all('... standard errors √(h σ² + h² se(b)²), the forecast package\'s rwf (OLS of the differences on a constant)', bd['forecast']['se'],
         np.sqrt(hh_ * ols_d.scale + hh_ ** 2 * float(ols_d.bse[0]) ** 2), rel=1e-10)
check.near('... the drift and its standard error in Parameter Estimates', bd['params']['rows'][0]['se'], float(ols_d.bse[0]), rel=1e-10)
for label_, R in (('Naive', bn), ('Seasonal Naive', bs), ('Drift', bd)):
    ns = run_code(R['code'], csv)
    check(f'the {label_} code gives the same forecasts and standard errors', ns.get('error') or (bool(np.allclose(ns['f_mean'], R['forecast']['mean'], rtol=1e-12)),
          bool(np.allclose(ns['f_se'], R['forecast']['se'], rtol=1e-10))), (True, True))
bh = call('timeseries.benchmark', table=tid, y='sales', time='month', method='snaive', s=12, h=HB, holdback=HB, season=12)
check_hb('holdback Seasonal Naive', bh, y[n - 2 * HB:n - HB], rel=1e-12)
check_model('Seasonal Naive', bs, csv, [v / DAY for v in months], list(y))
check('Seasonal Naive needs a period', 'error' in call('timeseries.benchmark', table=tid, y='sales', method='snaive', s=1), True)

# ---- Simple Moving Average: pandas' rolling means, statsmodels' seasonal_decompose trend for the centered ones
sa = call('timeseries.sma', table=tid, y='sales', time='month', width=12, centering='none', h=6)
trail = np.convolve(y, np.ones(12) / 12, mode='valid')          # the mean of y[t−11 .. t]
check('Simple Moving Average: its name', sa['name'], 'Simple Moving Average(12)')
near_all('No Centering: the mean of the value and the 11 before it (np.convolve)', sa['smoothed'][11:], trail, rel=1e-12)
near_all('... the one-step predictions: the mean of the 12 values before', sa['fitted'][12:], trail[:-1], rel=1e-12)
near_all('... every forecast the mean of the last 12', sa['forecast']['mean'], [y[-12:].mean()] * 6, rel=1e-12)
e_sa = y[12:] - trail[:-1]
near_all('... the interval ±z times the one-step errors\' RMS, at every horizon', sa['forecast']['upper'], [y[-12:].mean() + 1.959963984540054 * np.sqrt(np.mean(e_sa ** 2))] * 6, rel=1e-10)
sc = call('timeseries.sma', table=tid, y='sales', time='month', width=5, centering='centered', h=6)
near_all('Centered (odd width 5): statsmodels\' seasonal_decompose trend', sc['smoothed'], seasonal_decompose(y, period=5).trend, rel=1e-12)
sdd = call('timeseries.sma', table=tid, y='sales', time='month', width=12, centering='double', h=6)
near_all('Centered and Double Smoothed (width 12): the 2 × 12 moving average of seasonal_decompose', sdd['smoothed'], seasonal_decompose(y, period=12).trend, rel=1e-12)
s4 = call('timeseries.sma', table=tid, y='sales', time='month', width=4, centering='centered', h=0)
near_all('Centered with an even width: one more value before than after (pandas\' rolling(center=True))', s4['smoothed'][2:-1], [np.mean(y[t_ - 2:t_ + 2]) for t_ in range(2, n - 1)], rel=1e-12)
check('Centered and Double Smoothed needs an even width', 'error' in call('timeseries.sma', table=tid, y='sales', width=5, centering='double'), True)
for label_, R in (('No Centering', sa), ('Centered and Double Smoothed', sdd)):
    ns = run_code(R['code'], csv)
    check(f'the moving average code ({label_}) gives the same smoothed series and forecasts', ns.get('error') or (worst(list(ns['ma'].to_numpy()), R['smoothed']) < 1e-12,
          bool(np.allclose(ns['f_mean'], R['forecast']['mean'], rtol=1e-12))), (True, True))
F, _ = draw('the moving average\'s smoothed series', sdd['plot_code']['smoothed'], csv, size=(620, 300))
if F:
    check('... the smoothed series over the data, in the model\'s colour', (line(F['axes'][0], [v / DAY for v in months], sdd['smoothed'], 1e-9, color='#3a7d44ff') is not None,
          line(F['axes'][0], [v / DAY for v in months], list(y), marker='o') is not None), (True, True))
check_model('Simple Moving Average', sa, csv, [v / DAY for v in months], list(y))
sh = call('timeseries.sma', table=tid, y='sales', time='month', width=6, h=HB, holdback=HB, season=12)
check_hb('holdback moving average', sh, [y_tr[-6:].mean()] * HB, rel=1e-12)

# ---- smoothing models: JMP's Custom constraints, holtwinters' fix_params and bounds called directly
cf = call('timeseries.smooth', table=tid, y='sales', time='month', method='simple', h=6, weights={'alpha': {'fix': 0.2}})
m_cf = ExponentialSmoothing(y, initialization_method='estimated')
with m_cf.fix_params({'smoothing_level': 0.2}):
    ref_cf = m_cf.fit()
check('Custom, α fixed at 0.2: the name says so, k = 0', (cf['name'], cf['stats']['df'], cf['params']['rows'][0]['constraint']), ('Simple Exponential Smoothing, α = 0.2', n, 'Fixed'))
near_all('... the fit is holtwinters\' with fix_params (the starting level estimated)', cf['fitted'] + cf['forecast']['mean'], list(ref_cf.fittedvalues) + list(ref_cf.forecast(6)), rel=1e-9)
check('... a fixed weight has no standard error', (cf['params']['rows'][0]['se'], cf['params']['rows'][0]['t']), (None, None))
cb = call('timeseries.smooth', table=tid, y='sales', time='month', method='linear', h=6, weights={'alpha': {'lo': 0.1, 'hi': 0.4}})
ref_cb = ExponentialSmoothing(y, trend='add', initialization_method='estimated', bounds={'smoothing_level': (0.1, 0.4)}).fit()
check('Custom, α bounded by 0.1 and 0.4', (cb['name'], 0.1 <= cb['weights']['alpha'] <= 0.4), ('Linear (Holt) Exponential Smoothing, α in [0.1, 0.4]', True))
near_all('... holtwinters with bounds', cb['fitted'], ref_cb.fittedvalues, rel=1e-9)
cp_ = call('timeseries.smooth', table=tid, y='sales', time='month', method='damped', h=6, weights={'phi': {'fix': 0.9}})
m_cp = ExponentialSmoothing(y, trend='add', damped_trend=True, initialization_method='estimated', bounds={'damping_trend': (0.0, 1.0)})
with m_cp.fix_params({'damping_trend': 0.9}):
    ref_cp = m_cp.fit()
near_all('Custom, φ fixed at 0.9: holtwinters with fix_params', cp_['forecast']['mean'], ref_cp.forecast(6), rel=1e-9)
check('... k = 2 (α and γ estimated)', cp_['stats']['df'], n - 2)
cd = call('timeseries.smooth', table=tid, y='sales', time='month', method='seasonal', s=12, h=6, weights={'delta': {'fix': 0.3}})


def sse_seasonal(a):
    m_ = ExponentialSmoothing(y, seasonal='add', seasonal_periods=12, initialization_method='estimated')
    with m_.fix_params({'smoothing_level': a, 'smoothing_seasonal': 0.3 * (1 - a)}):
        return m_.fit().sse


a_cd = cd['weights']['alpha']
check.near('Custom, δ fixed at 0.3 with α free: statsmodels\' seasonal weight is δ(1 − α)', cd['weights']['delta'], 0.3, rel=1e-9)
check('... α minimises the one-step errors\' sum of squares (a search over α)', cd['stats']['sse'] <= min(sse_seasonal(max(1e-4, a_cd - 0.01)), sse_seasonal(min(0.999, a_cd + 0.01))) + 1e-6, True)
check.near('... the fit is holtwinters\' at that α', cd['stats']['sse'], sse_seasonal(a_cd), rel=1e-9)
cw = call('timeseries.smooth', table=tid, y='sales', time='month', method='double', h=6, weights={'alpha': {'lo': 0.05, 'hi': 0.2}})


def sse_brown2(a_):
    m_ = ExponentialSmoothing(y, trend='add', initialization_method='estimated')
    with m_.fix_params({'smoothing_level': a_ * (2 - a_), 'smoothing_trend': a_ / (2 - a_)}):
        return m_.fit().sse


grid_b = min(sse_brown2(a_) for a_ in np.linspace(0.05, 0.2, 31))
check('Brown, α bounded by 0.05 and 0.2: within them, and no worse than a grid over them', (0.05 <= cw['weights']['alpha'] <= 0.2, cw['stats']['sse'] <= grid_b + 1e-6), (True, True))
check('a trend weight fixed above the level weight: statsmodels\' own message', 'smoothing_trend' in call('timeseries.smooth', table=tid, y='sales', method='linear',
      weights={'alpha': {'fix': 0.2}, 'gamma': {'fix': 0.5}}).get('error', ''), True)
check('a weight outside 0 and 1 is refused', 'error' in call('timeseries.smooth', table=tid, y='sales', method='simple', weights={'alpha': {'fix': 1.5}}), True)
for label_, R in (('α fixed', cf), ('α bounded', cb), ('δ fixed, α searched', cd), ('Brown bounded', cw)):
    ns = run_code(R['code'], csv)
    check(f'the Custom constraints code ({label_}) gives the same fit', ns.get('error') or bool(np.allclose(np.asarray(ns['res'].fittedvalues), R['fitted'], rtol=1e-6)), True)
    check_model(f'smoothing, Custom ({label_})', R, csv, [v / DAY for v in months], list(y))

# ---- the Box-Cox transformation: statsmodels' own use_boxcox, the Jacobian, the limits transformed back
for lam_ in (0.0, 0.5):
    bx = call('timeseries.smooth', table=tid, y='sales', time='month', method='winters', s=12, h=12, boxcox=lam_)
    ref_bx = ExponentialSmoothing(y, trend='add', seasonal='add', seasonal_periods=12, initialization_method='estimated', use_boxcox=lam_).fit()
    check(f'Box-Cox λ = {lam_:g}: the name says so', bx['name'], f'Winters Method (Additive)(12), Box-Cox λ = {lam_:g}')
    near_all(f'... the predictions and forecasts are holtwinters\' use_boxcox={lam_:g} (transformed back)', bx['fitted'] + bx['forecast']['mean'],
             list(ref_bx.fittedvalues) + list(ref_bx.forecast(12)), rel=1e-7)
    yt_ = sp_boxcox(y, lam_)
    ref_t_ = ExponentialSmoothing(yt_, trend='add', seasonal='add', seasonal_periods=12, initialization_method='estimated').fit()
    sse_t_ = float(ref_t_.sse)
    check.near(f'... −2LogLikelihood of the values themselves: the transformed fit\'s and the Jacobian −2(λ − 1)Σ log y', bx['stats']['m2ll'],
               n * (math.log(2 * math.pi * sse_t_ / n) + 1) - 2 * (lam_ - 1) * float(np.sum(np.log(y))), rel=1e-8)
    sd_t_ = math.sqrt(sse_t_ / (n - 3))
    th_ = bx['weights']
    fse_t_ = sd_t_ * np.sqrt(ts.psi_variance('winters', th_, 12, 12))
    near_all('... the limits: the transformed scale\'s, transformed back', bx['forecast']['lower'] + bx['forecast']['upper'],
             list(sp_inv_boxcox(ref_t_.forecast(12) - 1.959963984540054 * fse_t_, lam_)) + list(sp_inv_boxcox(ref_t_.forecast(12) + 1.959963984540054 * fse_t_, lam_)), rel=1e-6)
    near_all('... the residuals on the values\' own scale', bx['resid'], y - np.asarray(ref_bx.fittedvalues), rel=1e-7, abs_=1e-7)
    ns = run_code(bx['code'], csv)
    check(f'... the Box-Cox code gives the same forecasts', ns.get('error') or bool(np.allclose(sp_inv_boxcox(np.asarray(ns['res'].forecast(12)), lam_), bx['forecast']['mean'], rtol=1e-7)), True)
    check_model(f'smoothing, Box-Cox λ = {lam_:g}', bx, csv, [v / DAY for v in months], list(y))
check('Box-Cox needs every value above zero', 'error' in call('timeseries.smooth', table=table({'y': (y - 200).tolist()}), y='y', method='simple', boxcox=0), True)

# ---- state space smoothing: the multiplicative and the multiplicative damped trend (ETSModel(trend='mul'))
for err_, tr_, se_ in (('mul', 'M', 'N'), ('mul', 'Md', 'A'), ('add', 'M', 'N'), ('mul', 'M', 'M')):
    em = call('timeseries.ets', table=tid, y='sales', time='month', error=err_, trend=tr_, seasonal=se_, s=12, h=8)
    ref_em = ETSModel(pd.Series(y), error=err_, trend='mul', damped_trend=tr_ == 'Md', seasonal={'N': None, 'A': 'add', 'M': 'mul'}[se_],
                      seasonal_periods=12 if se_ != 'N' else None).fit(disp=False)
    code_ = f'{"A" if err_ == "add" else "M"},{tr_},{se_}'
    check(f'ETS({code_}): no error, its name', (em.get('error'), em['name']), (None, f'State Space Smoothing ETS({code_}){"12" if se_ != "N" else ""}'))
    check.near(f'ETS({code_}): AICc is ETSModel(trend="mul"{", damped_trend=True" if tr_ == "Md" else ""})\'s', em['stats']['aicc'], float(ref_em.aicc), rel=1e-9)
    near_all(f'ETS({code_}): the fitted values and the point forecasts', em['fitted'] + em['forecast']['mean'], list(ref_em.fittedvalues) + list(ref_em.forecast(8)), rel=1e-8)
    check(f'ETS({code_}): simulated prediction intervals', any('simulated' in s_ for s_ in em['notes']), True)
check('a multiplicative trend needs every value above zero', 'error' in call('timeseries.ets', table=table({'y': (y - 200).tolist()}), y='y', error='add', trend='M'), True)
ns = run_code(em['code'], csv)
check('the ETS(M,M,M) code gives the same AICc', ns.get('error') or bool(np.isclose(ns['res'].aicc, em['stats']['aicc'], rtol=1e-8)), True)
check_model('ETS(M,Md,A)', call('timeseries.ets', table=tid, y='sales', time='month', error='mul', trend='Md', seasonal='A', s=12, h=8), csv, [v / DAY for v in months], list(y))

# ---- the averaged forecast: the mean of the members' predictions, forecasts and limits
mem_ = [{'fn': 'timeseries.arima', 'args': {'p': 1, 'q': 1}}, {'fn': 'timeseries.smooth', 'args': {'method': 'winters', 's': 12}},
        {'fn': 'timeseries.benchmark', 'args': {'method': 'snaive', 's': 12}}]
av = call('timeseries.average', table=tid, y='sales', time='month', members=mem_, h=12)
parts_ = [call('timeseries.arima', table=tid, y='sales', time='month', p=1, q=1, h=12), call('timeseries.smooth', table=tid, y='sales', time='month', method='winters', s=12, h=12),
          call('timeseries.benchmark', table=tid, y='sales', time='month', method='snaive', s=12, h=12)]
check('Averaged forecast: its name lists the members', av['name'], 'Average of ARMA(1, 1), Winters Method (Additive)(12), Seasonal Naive(12)')


def mean_of(key, sub=None):
    rows_ = [np.array([np.nan if v is None else v for v in (p[sub][key] if sub else p[key])], dtype=float) for p in parts_]
    return np.mean(rows_, axis=0)


near_all('... the forecasts are the members\' mean', av['forecast']['mean'], mean_of('mean', 'forecast'), rel=1e-12)
near_all('... the limits the mean of the members\' limits', av['forecast']['lower'] + av['forecast']['upper'], list(mean_of('lower', 'forecast')) + list(mean_of('upper', 'forecast')), rel=1e-12)
near_all('... the one-step predictions the mean where every member has one (from the 13th month: the seasonal naive\'s first)', av['fitted'], mean_of('fitted'), rel=1e-12)
check('... no AIC: an average has no likelihood', (av['stats']['aic'], av['stats']['sbc']), (None, None))
ns = run_code(av['code'], csv)
check('the averaged forecast\'s code gives the same forecasts', ns.get('error') or bool(np.allclose(ns['f_mean'], av['forecast']['mean'], rtol=1e-6)), True)
check_model('the averaged forecast', av, csv, [v / DAY for v in months], list(y))
avh = call('timeseries.average', table=tid, y='sales', time='month', members=mem_, h=HB, holdback=HB, season=12)
parts_h = [call(m_['fn'], table=tid, y='sales', time='month', h=HB, holdback=HB, season=12, **m_['args']) for m_ in mem_]
check_hb('holdback averaged forecast', avh, np.mean([p['forecast']['mean'] for p in parts_h], axis=0), rel=1e-10)
check('an average of one model is refused', 'error' in call('timeseries.average', table=tid, y='sales', members=mem_[:1]), True)

# ---- the runs test: the closed form, statsmodels' runstest_1samp, and its correction slip below N = 50
rt_s = call('timeseries.series', table=tid, y='sales', time='month')['runs']
above_ = y >= y.mean()
R_ = 1 + int(np.sum(above_[1:] != above_[:-1]))
n1_, n2_ = int(above_.sum()), int((~above_).sum())
E_ = 2 * n1_ * n2_ / n + 1
V_ = 2 * n1_ * n2_ * (2 * n1_ * n2_ - n) / (n ** 2 * (n - 1))
check('Runs Test about the mean: the runs, the counts at or above and below', (rt_s['mean']['runs'], rt_s['mean']['n_above'], rt_s['mean']['n_below']), (R_, n1_, n2_))
check.near('... z = (R − E)/√V with E = 2 n1 n2/N + 1 (N = 120: no correction)', rt_s['mean']['z'], (R_ - E_) / math.sqrt(V_), rel=1e-12)
zs, ps = runstest_1samp(y, cutoff='mean', correction=True)
check.near('... statsmodels\' runstest_1samp (N ≥ 50: no correction there either)', rt_s['mean']['z'], float(zs), rel=1e-12)
check.near('... and its p-value', rt_s['mean']['p'], float(ps), rel=1e-10)
zm, _ = runstest_1samp(y, cutoff='median', correction=True)
check.near('... about the median', rt_s['median']['z'], float(zm), rel=1e-12)
small = [10, 10, 10, 0, 10, 0, 0, 10, 0, 0]   # 6 runs, 5 above the mean and 5 below: R = E exactly
rs_small = ts.runs_test(small, 'mean')
check('a short series with R = E: the corrected z is 0, p 1', (rs_small['runs'], rs_small['expected'], rs_small['z'], rs_small['p']), (6, 6.0, 0.0, 1.0))
z_sm, _ = runstest_1samp(np.array(small, dtype=float), cutoff='mean', correction=True)
check('... statsmodels 0.14.6 moves a distance below 1/2 away from 0 (z ≠ 0), the slip the report avoids', abs(float(z_sm)) > 0.2, True)
z_nc, _ = runstest_1samp(np.array(small[:9] + [10], dtype=float), cutoff='mean', correction=False)
rs9 = ts.runs_test(small[:9] + [10], 'mean', correction=False)
check.near('... without the correction the two agree', rs9['z'], float(z_nc), rel=1e-12)
rr = call('timeseries.arima', table=tid, y='sales', time='month', p=1, h=0)['resid_runs']
e_ar = np.array([v for v in call('timeseries.arima', table=tid, y='sales', time='month', p=1, h=0)['resid'] if v is not None])
check.near('the residuals\' runs test about zero (every model has it)', rr['z'], float(runstest_1samp(e_ar, cutoff=0.0, correction=True)[0]), rel=1e-12)
S_rt = call('timeseries.series', table=tid, y='sales', time='month')
for cut_ in ('mean', 'median', 'zero'):
    ns = run_code('\n'.join(S_rt['runs_code'][cut_]), csv)
    check(f'the runs test code (about {cut_}) gives the same z', ns.get('error') or bool(np.isclose(ns['z'], S_rt['runs'][cut_]['z'], rtol=1e-12)) if S_rt['runs'][cut_].get('z') is not None else ns.get('error'), True if S_rt['runs'][cut_].get('z') is not None else None)
Ar = call('timeseries.arima', table=tid, y='sales', time='month', p=1, h=0)
ns = run_code(ts.assemble(Ar['plot_code']['runs']), csv)
check('the residual runs test code gives the same z', ns.get('error') or bool(np.isclose(ns['z'], Ar['resid_runs']['z'], rtol=1e-9)), True)

# ---- rolling-origin cross-validation: expanding windows, the models refitted at every origin
cv_models = [{'id': 1, 'name': 'ARMA(1, 1)', 'fn': 'timeseries.arima', 'args': {'p': 1, 'q': 1}},
             {'id': 2, 'name': 'Seasonal Naive(12)', 'fn': 'timeseries.benchmark', 'args': {'method': 'snaive', 's': 12}},
             {'id': 3, 'name': 'Winters', 'fn': 'timeseries.smooth', 'args': {'method': 'winters', 's': 12}}]
with contextlib.redirect_stdout(io.StringIO()) as prog:
    cvr = call('timeseries.cv', table=tid, y='sales', time='month', models=cv_models, origins=4, horizon=6, step=6, season=12)
check('cross-validation: no error, 4 origins 6 apart, the last 6 before the end', (cvr.get('error'), cvr['cuts'], cvr['horizon']), (None, [18, 12, 6, 0], 6))
check('... progress lines for the page, one per fit', prog.getvalue().strip().split('\n')[-1], 'smui:progress tscv 12 12')
cv_sn = next(m_ for m_ in cvr['models'] if m_['id'] == 2)
by_hand = []
for cut_ in (18, 12, 6, 0):
    o_ = n - cut_ - 6
    fc_ = y[o_ - 12:o_ - 6]
    e_ = y[o_:o_ + 6] - fc_
    by_hand.append((math.sqrt(np.mean(e_ ** 2)), np.mean(np.abs(e_)), 100 * np.mean(np.abs(e_ / y[o_:o_ + 6]))))
near_all('... Seasonal Naive at each origin: RMSE, MAE and MAPE of the next 6 values by hand', [v for p in cv_sn['origins'] for v in (p['rmse'], p['mae'], p['mape'])],
         [v for t3 in by_hand for v in t3], rel=1e-12)
near_all('... and their means over the origins', [cv_sn['rmse'], cv_sn['mae'], cv_sn['mape']], np.mean(by_hand, axis=0), rel=1e-12)
cv_ar = next(m_ for m_ in cvr['models'] if m_['id'] == 1)
o2 = n - 12 - 6
ref_o2 = ARIMA(y[:o2], order=(1, 0, 1), trend='c').fit()
check.near('... ARMA(1, 1) at the second origin: ARIMA fitted on the values up to it', cv_ar['origins'][1]['rmse'], math.sqrt(np.mean((y[o2:o2 + 6] - ref_o2.get_forecast(6).predicted_mean) ** 2)), rel=1e-5)
check('... the origins\' last training months', cvr['t_origins'], [float(months[n - c_ - 6 - 1]) for c_ in (18, 12, 6, 0)])
ns = run_code(cvr['code'], csv)
if ns.get('error'):
    check('the cross-validation code runs', ns['error'], None)
else:
    cvd = ns['cv']
    near_all('the cross-validation code gives every origin\'s RMSE', list(cvd['RMSE']), [m_['origins'][j_]['rmse'] for j_ in range(4) for m_ in cvr['models']], rel=1e-5)
check('too many origins for the series is an error', 'error' in call('timeseries.cv', table=tid, y='sales', models=cv_models, origins=30, horizon=6), True)

# ==== Time Series Forecast (tsforecast): the best ETS model of each of many series ====
# against ETSModel fitted directly for every candidate, timeseries.ets for the chosen model, and the shown code on a CSV
from smui import tsforecast as tsf


def quiet_call(fn, **kw):
    with contextlib.redirect_stdout(io.StringIO()):   # the 'smui:progress' lines are the page's
        return call(fn, **kw)


f_rng = np.random.default_rng(99)
nF = 72
mF = [ms(f'{2019 + i // 12}-{i % 12 + 1:02d}-01') for i in range(nF)]
tt_ = np.arange(nF)
sA = 200 * 1.005 ** tt_ * (1 + 0.15 * np.sin(2 * np.pi * tt_ / 12)) * np.exp(f_rng.normal(0, 0.02, nF))       # multiplicative season and growth
sB = 50 + np.cumsum(f_rng.normal(0.3, 1.0, nF))                                                              # a random walk with drift
sC = 20 + 5 * np.sin(2 * np.pi * tt_ / 12) + f_rng.normal(0, 1.0, nF) - 30                                     # additive season, some values below zero
tidF = date_table({'month': mF, 'A': list(sA), 'B': list(sB), 'C': list(sC)})
specsF = [{'key': k, 'label': k, 'y': k, 'rows': None, 'excluded': []} for k in ('A', 'B', 'C')]
with contextlib.redirect_stdout(io.StringIO()) as progF:
    fF = call('tsforecast.fit', table=tidF, series=specsF, time='month', h=6, criterion='aicc', models='recommended')
check('Time Series Forecast: no error, three series', (fF.get('error'), [s_['key'] for s_ in fF['series']]), (None, ['A', 'B', 'C']))
check('... progress lines, the last one all done', prog_last := progF.getvalue().strip().split('\n')[-1].split()[-1] == progF.getvalue().strip().split('\n')[-1].split()[-2], True)
TR = {'N': (None, False), 'A': ('add', False), 'Ad': ('add', True), 'M': ('mul', False), 'Md': ('mul', True)}
for sF, yv_ in zip(fF['series'], (sA, sB, sC)):
    pos_ = bool((yv_ > 0).all())
    want_c = tsf.candidates('recommended', nF, 12, pos_)
    check(f'{sF["key"]}: the recommended candidates the series allows ({len(want_c)}; multiplicative ones only above zero)',
          sorted((c['error'], c['trend'], c['seasonal']) for c in sF['candidates']), sorted(want_c))
    direct = {}
    for e_, t_, s_ in want_c:
        rr = ETSModel(pd.Series(yv_), error=e_, trend=TR[t_][0], damped_trend=TR[t_][1], seasonal={'N': None, 'A': 'add', 'M': 'mul'}[s_],
                      seasonal_periods=12 if s_ != 'N' else None, initialization_method='estimated').fit(disp=False, maxiter=1000)
        direct[(e_, t_, s_)] = float(rr.aicc)
    got_ = {(c['error'], c['trend'], c['seasonal']): c['aicc'] for c in sF['candidates']}
    near_all(f'{sF["key"]}: every candidate\'s AICc is ETSModel\'s', [got_[k_] for k_ in want_c], [direct[k_] for k_ in want_c], rel=1e-9)
    best_ = min(direct, key=direct.get)
    check(f'{sF["key"]}: the chosen model has the least AICc', sF['model'], tsf.model_name(*best_, 12))
    ref_f = call('timeseries.ets', table=tidF, y=sF['key'], time='month', error=best_[0], trend=best_[1], seasonal=best_[2], s=12 if best_[2] != 'N' else 0, h=6)
    near_all(f'{sF["key"]}: its forecasts and limits are timeseries.ets\' (the series\' own report)', sF['forecast']['mean'] + sF['forecast']['lower'] + sF['forecast']['upper'],
             ref_f['forecast']['mean'] + ref_f['forecast']['lower'] + ref_f['forecast']['upper'], rel=1e-10)
    check(f'{sF["key"]}: the forecast months continue the dates', sF['forecast']['t'][0], float(ms('2025-01-01')))
check('C has values below zero: no multiplicative candidate', any(c['error'] == 'mul' or c['seasonal'] == 'M' for c in fF['series'][2]['candidates']), False)
check('the model sets: all 30 for a positive seasonal series, 6 additive ones, 15 recommended', (len(tsf.candidates('all', 72, 12, True)), len(tsf.candidates('additive', 72, 12, True)),
      len(tsf.candidates('recommended', 72, 12, True))), (30, 6, 15))
check('... a short series gets no seasonal candidates (two periods and four values needed)', any(c[2] != 'N' for c in tsf.candidates('all', 27, 12, True)), False)
# BIC
fB = quiet_call('tsforecast.fit', table=tidF, series=specsF[:1], time='month', h=6, criterion='bic', models='additive')
bic_ = {(c['error'], c['trend'], c['seasonal']): c['bic'] for c in fB['series'][0]['candidates']}
check('BIC: the chosen model has the least BIC', fB['series'][0]['model'], tsf.model_name(*min(bic_, key=bic_.get), 12))
# the holdback criterion: every candidate fitted on the first n − 12, compared on its forecasts of the last 12; the chosen refitted on all
fH = quiet_call('tsforecast.fit', table=tidF, series=specsF[:2], time='month', h=6, criterion='rmse', holdback=12, models='recommended')
for sF, yv_ in zip(fH['series'], (sA, sB)):
    hbd = {}
    for c in sF['candidates']:
        rr = ETSModel(pd.Series(yv_[:nF - 12]), error=c['error'], trend=TR[c['trend']][0], damped_trend=TR[c['trend']][1], seasonal={'N': None, 'A': 'add', 'M': 'mul'}[c['seasonal']],
                      seasonal_periods=12 if c['seasonal'] != 'N' else None, initialization_method='estimated').fit(disp=False, maxiter=1000)
        hbd[(c['error'], c['trend'], c['seasonal'])] = math.sqrt(np.mean((yv_[nF - 12:] - np.asarray(rr.forecast(12))) ** 2))
    got_ = {(c['error'], c['trend'], c['seasonal']): c['hb_rmse'] for c in sF['candidates']}
    near_all(f'holdback RMSE, {sF["key"]}: every candidate\'s, fitted on the first 60 values', [got_[k_] for k_ in hbd], list(hbd.values()), rel=1e-7)
    b_ = min(hbd, key=hbd.get)
    check(f'... {sF["key"]}: the chosen model has the least holdback RMSE, and its criterion is that RMSE', (sF['model'], abs(sF['criterion_value'] - hbd[b_]) < 1e-7 * hbd[b_]),
          (tsf.model_name(*b_, 12), True))
    ref_f = call('timeseries.ets', table=tidF, y=sF['key'], time='month', error=b_[0], trend=b_[1], seasonal=b_[2], s=12 if b_[2] != 'N' else 0, h=6)
    near_all(f'... {sF["key"]}: the forecasts after the end from the chosen model refitted on all 72 values', sF['forecast']['mean'], ref_f['forecast']['mean'], rel=1e-10)
# stacked data: a grouping column; each level is a series, the same as its own column
stack = pd.DataFrame({'store': ['north'] * nF + ['south'] * nF, 'month': mF * 2, 'units': list(sA) + list(sB)})
tidS = date_table({c: list(stack[c]) for c in stack.columns})
rowsN, rowsS = list(range(nF)), list(range(nF, 2 * nF))
spS = [{'key': 'north', 'label': 'North store', 'y': 'units', 'rows': rowsN, 'excluded': [], 'where': [{'column': 'store', 'value': 'north'}]},
       {'key': 'south', 'label': 'South store', 'y': 'units', 'rows': rowsS, 'excluded': [], 'where': [{'column': 'store', 'value': 'south'}]}]
fS = quiet_call('tsforecast.fit', table=tidS, series=spS, time='month', h=6, criterion='aicc', models='recommended')
check('stacked data: a series per level, with the page\'s labels', [(s_['key'], s_['label']) for s_ in fS['series']], [('north', 'North store'), ('south', 'South store')])
near_all('... each level\'s forecasts are those of the same values in a column of their own', fS['series'][0]['forecast']['mean'] + fS['series'][1]['forecast']['mean'],
         fF['series'][0]['forecast']['mean'] + fF['series'][1]['forecast']['mean'], rel=1e-10)
check('... the same models chosen', [s_['model'] for s_ in fS['series']], [fF['series'][0]['model'], fF['series'][1]['model']])
fSx = quiet_call('tsforecast.fit', table=tidS, series=[dict(spS[0], excluded=[10, 11])], time='month', h=6)
check('... an excluded row counts as missing in its place', (fSx['series'][0]['n'], fSx['series'][0]['n_slots'], fSx['series'][0]['values'][10]), (nF - 2, nF, None))
# the code: every series' candidates, the choice, the forecasts, from a CSV export
csvF = pd.DataFrame({'month': [pd.Timestamp(v, unit='ms').strftime('%Y-%m-%d') for v in mF], 'A': sA, 'B': sB, 'C': sC})
ns = run_code(fF['code'], csvF)
if ns.get('error'):
    check('the Time Series Forecast code runs', ns['error'], None)
else:
    check('the Time Series Forecast code chooses the same models', list(ns['pd'].DataFrame(ns['summary'])['Model']), [s_['model'] for s_ in fF['series']])
    near_all('... with the same AICc', list(ns['pd'].DataFrame(ns['summary'])['AICc']), [s_['criterion_value'] for s_ in fF['series']], rel=1e-8)
    near_all('... and the same forecasts', list(ns['pd'].concat(ns['forecasts'])['mean']), [v for s_ in fF['series'] for v in s_['forecast']['mean']], rel=1e-8)
ns = run_code(fH['code'], csvF)
check('the holdback criterion\'s code chooses the same models', ns.get('error') or list(ns['pd'].DataFrame(ns['summary'])['Model']), [s_['model'] for s_ in fH['series']])
stack_csv = pd.DataFrame({'store': stack['store'], 'month': [pd.Timestamp(v, unit='ms').strftime('%Y-%m-%d') for v in stack['month']], 'units': stack['units']})
ns = run_code(fS['code'], stack_csv)
check('the stacked data\'s code (each level\'s rows) chooses the same models', ns.get('error') or list(ns['pd'].DataFrame(ns['summary'])['Model']), [s_['model'] for s_ in fS['series']])
check('no series is an error', 'error' in quiet_call('tsforecast.fit', table=tidF, series=[]), True)

sys.exit(check.done())
