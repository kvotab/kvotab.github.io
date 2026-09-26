#!/usr/bin/env python3
"""Analyze > Specialized Modeling > Time Series's backend
(resources/py/smui/timeseries.py), checked against statsmodels called
directly and against published values:

  the ADF critical values of MacKinnon (2010, Table 2), the critical values of
  Fisher's g test (Fisher 1929, as tabulated by Davis 1941 and Wei 2006), the
  ETS forecast variances of Hyndman et al. (2008, Table 6.1), and the ARIMA
  fits of the sunspot numbers in statsmodels' documentation ("Autoregressive
  Moving Average (ARMA): Sunspots data"), with the data read from
  statsmodels.datasets at run time.

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
check("Brown's code gives the same fit", ns.get('error') or bool(np.allclose(ns['res'].fittedvalues, rb['fitted'], rtol=1e-6)), True)
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

# ---- names ------------------------------------------------------------------------------------------------
check("JMP's ARIMA names", [ts.arima_name(1, 0, 0), ts.arima_name(0, 0, 2), ts.arima_name(1, 0, 1), ts.arima_name(0, 1, 0), ts.arima_name(0, 1, 1), ts.arima_name(2, 1, 0), ts.arima_name(1, 1, 1)],
      ['AR(1)', 'MA(2)', 'ARMA(1, 1)', 'I(1)', 'IMA(1, 1)', 'ARI(2, 1)', 'ARIMA(1, 1, 1)'])
check('every result has its code', all(bool(x.get('code')) for x in (r, rd, rt_, rcy, rdc, rs, rx, m, rb, re_)), True)
sys.exit(check.done())
