"""Time Series Forecast (Analyze > Specialized Modeling > Time Series
Forecast): the backend.

JMP's platform for many series at once: for each series (a Y column, or a
level of the grouping columns of stacked data), the state space smoothing
models ETS(error, trend, seasonal) of Hyndman et al. (2008) are fitted by
maximum likelihood (statsmodels' ETSModel), the best is chosen by an
information criterion (AICc, AIC or BIC) or by its forecasts of held-back
values (RMSE, MAE or MAPE on the last values), and it forecasts the next
periods with prediction intervals. The page draws a series' own report
(the chosen model's graphs, parameters and code) on demand with
timeseries.ets, so the numbers here are that function's.

Candidates are fitted as timeseries.ets fits them (the series filled by
linear interpolation, initialization_method='estimated', maxiter 1000);
their point forecasts need no simulation, so the choice is fast, and only
the chosen model gets its prediction intervals (simulated for the
multiplicative ones, with timeseries' fixed seed).
"""
import json
import math

import numpy as np
import pandas as pd

from . import timeseries as ts
from .registry import api
from .util import code_head, one_line

TRENDS = {'N': (None, False), 'A': ('add', False), 'Ad': ('add', True), 'M': ('mul', False), 'Md': ('mul', True)}
SEASONS = {'N': None, 'A': 'add', 'M': 'mul'}
MODEL_SETS = {
    # the forecast package's automatic set: no multiplicative trend, and not the unstable additive errors with multiplicative seasonality
    'recommended': ('Recommended: up to 15', ('add', 'mul'), ('N', 'A', 'Ad'), ('N', 'A', 'M')),
    'all': ('All 30', ('add', 'mul'), ('N', 'A', 'Ad', 'M', 'Md'), ('N', 'A', 'M')),
    'additive': ('Additive only: up to 6', ('add',), ('N', 'A', 'Ad'), ('N', 'A')),
}
CRITERIA = {'aicc': 'AICc', 'aic': 'AIC', 'bic': 'BIC', 'rmse': 'Holdback RMSE', 'mae': 'Holdback MAE', 'mape': 'Holdback MAPE'}
HOLD_CRITERIA = ('rmse', 'mae', 'mape')


def model_code(error, trend, seasonal):
    return f'{"A" if error == "add" else "M"},{trend},{seasonal}'


def model_name(error, trend, seasonal, period=0):
    """ETS(M,A,M)12, as the Time Series platform names its models (the period after a seasonal one)."""
    return f'ETS({model_code(error, trend, seasonal)}){period if seasonal != "N" and period else ""}'


def candidates(model_set, n, period, positive):
    """The (error, trend, seasonal) models of the set that the series allows:
    multiplicative parts need every value above zero, a seasonal part a
    period of at least 2 and two periods and four values more, as
    timeseries.ets asks."""
    _, errors, trends, seasons = MODEL_SETS.get(model_set, MODEL_SETS['recommended'])
    out = []
    for e in errors:
        for t in trends:
            for s in seasons:
                if model_set == 'recommended' and e == 'add' and s == 'M':
                    continue
                if not positive and (e == 'mul' or t in ('M', 'Md') or s == 'M'):
                    continue
                if s != 'N' and not (period and period >= 2 and n >= 2 * period + 4):
                    continue
                if s == 'N' and n < 8:
                    continue
                out.append((e, t, s))
    return out


def _ets_fit(x, e, t, s, period):
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel
    trend, damped = TRENDS[t]
    model = ETSModel(pd.Series(x), error=e, trend=trend, damped_trend=damped, seasonal=SEASONS[s],
                     seasonal_periods=period if s != 'N' else None, initialization_method='estimated')
    return model.fit(disp=False, maxiter=1000)


def _one_step(x, miss, res):
    fitted = np.asarray(res.fittedvalues, dtype=float)
    ok = ~miss & np.isfinite(fitted)
    e = (x - fitted)[ok]
    a = x[ok]
    return {'mae': ts._f(np.mean(np.abs(e))) if ok.any() else None,
            'mape': ts._f(100 * np.mean(np.abs(e / a))) if ok.any() and (a != 0).all() else None}


def _progress(done, total):
    print(f'smui:progress tsforecast {done} {total}', flush=True)


@api('tsforecast.fit')
@ts._quietly
def fit(table, series=None, time=None, h=12, holdback=0, criterion='aicc', models='recommended', period=0, level=0.95,
        where=None, table_name='data', rows=None):
    """Every series: the candidates' criteria, the chosen model, its forecasts.
    series: [{key, label, y, rows, excluded, where}], one for each Y column
    and level of the grouping columns (the page splits the rows)."""
    series = [s for s in (series or []) if isinstance(s, dict) and s.get('y')]
    if not series:
        return {'error': 'no series to forecast'}
    criterion = criterion if criterion in CRITERIA else 'aicc'
    models = models if models in MODEL_SETS else 'recommended'
    h = max(1, int(h or 12))
    level = float(level or 0.95)
    held = criterion in HOLD_CRITERIA
    H = max(1, int(holdback or h)) if held else 0
    loaded = []
    for sp in series:
        try:
            S = ts.load(table, sp['y'], time, sp.get('rows'), sp.get('excluded'))
            x, miss = ts._filled(S)
            m = int(period or 0) if int(period or 0) >= 2 else int(S.period or 0)
            n_c = S.n - H if held else S.n
            cands = candidates(models, n_c, m, bool((x > 0).all()))
            loaded.append((sp, S, x, miss, m, cands, None))
        except ts.NoSeries as e:
            loaded.append((sp, None, None, None, 0, [], str(e)))
    total = sum(len(c) for *_, c, _ in loaded) + len(loaded)
    done = 0
    _progress(0, total)
    out = []
    for sp, S, x, miss, m, cands, err in loaded:
        row = {'key': sp.get('key'), 'label': sp.get('label') or sp.get('key'), 'y': sp['y'], 'rows_in': sp.get('rows'), 'excluded': sp.get('excluded') or [],
               'where': sp.get('where') or []}
        if err or not cands:
            row['error'] = err or ('too few values for any model of the set' if S is not None else 'no values')
            done += len(cands) + 1
            _progress(done, total)
            out.append(row)
            continue
        try:
            Sh = ts.load(table, sp['y'], time, sp.get('rows'), sp.get('excluded'), holdback=H, season=m) if held else None
        except ts.NoSeries as e:
            row['error'] = str(e)
            done += len(cands) + 1
            _progress(done, total)
            out.append(row)
            continue
        xh, missh = ts._filled(Sh) if held else (None, None)
        tried = []
        for e, t, s in cands:
            c = {'model': model_name(e, t, s, m), 'error': e, 'trend': t, 'seasonal': s}
            try:
                res = _ets_fit(xh if held else x, e, t, s, m)
                c.update(aic=ts._f(res.aic), aicc=ts._f(res.aicc), bic=ts._f(res.bic), m2ll=ts._f(-2 * float(res.llf)), nparm=int(len(res.params) + 1),
                         sigma=ts._f(math.sqrt(float(res.mse))) if res.mse is not None and res.mse >= 0 else None,
                         **_one_step(xh if held else x, missh if held else miss, res))
                if held:
                    hb = ts._holdback_stats(Sh, np.asarray(res.forecast(H), dtype=float))
                    c.update(hb_rmse=hb['rmse'], hb_mae=hb['mae'], hb_mape=hb['mape'], hb_mase=hb['mase'])
            except Exception as ex:  # noqa: BLE001 - a candidate that fails is listed with its error
                c['fail'] = f'{type(ex).__name__}: {ex}'
            tried.append(c)
            done += 1
            _progress(done, total)
        key = f'hb_{criterion}' if held else criterion
        ok = [c for c in tried if c.get(key) is not None and math.isfinite(c[key])]
        tried.sort(key=lambda c: c[key] if c.get(key) is not None and math.isfinite(c[key]) else math.inf)
        if not ok:
            row.update(error='no candidate could be fitted', candidates=tried)
            done += 1
            _progress(done, total)
            out.append(row)
            continue
        best = min(ok, key=lambda c: c[key])
        best['best'] = True
        # the chosen model on every value, and its forecasts with their intervals (timeseries.ets, as the series' own report has it)
        final = ts.ets(table, sp['y'], time, sp.get('rows'), sp.get('excluded'), error=best['error'], trend=best['trend'], seasonal=best['seasonal'],
                       s=m if best['seasonal'] != 'N' else 0, level=level, h=h, maxiter=1000, where=row['where'], table_name=table_name)
        done += 1
        _progress(done, total)
        if final.get('error'):
            row.update(error=final['error'], candidates=tried)
            out.append(row)
            continue
        fc = final['forecast']
        st = final['stats']
        row.update(n=int(np.isfinite(S.y).sum()), n_slots=S.n, period=m, candidates=tried, n_models=len(tried), n_ok=len(ok),
                   model=best['model'], name=final['name'], spec={'error': best['error'], 'trend': best['trend'], 'seasonal': best['seasonal'], 's': m if best['seasonal'] != 'N' else 0},
                   criterion_value=best[key], aic=st['aic'], aicc=st['aicc'], bic=st['sbc'], sigma=final.get('sigma'), mape=st['mape'], mae=st['mae'],
                   hb_rmse=best.get('hb_rmse'), hb_mae=best.get('hb_mae'), hb_mape=best.get('hb_mape'),
                   t=ts._arr(S.t), values=ts._arr(S.y), rows=S.rows, kind=S.kind, fitted=final['pred'], fit_lo=final['pred_lo'], fit_hi=final['pred_hi'], forecast=fc)
        out.append(row)
    return {'series': out, 'criterion': criterion, 'criterion_label': CRITERIA[criterion], 'models': models, 'models_label': MODEL_SETS[models][0],
            'h': h, 'holdback': H, 'level': level, 'code': _code(table, time, loaded, out, criterion, H, h, level, table_name, where)}


def _code(table, time, loaded, out, criterion, H, h, level, table_name, where):
    """Python that does what the report did, from a CSV export of the table:
    each series, the candidates fitted, the best chosen, its forecasts."""
    held = criterion in HOLD_CRITERIA
    L = [code_head(table_name, ['from statsmodels.tsa.exponential_smoothing.ets import ETSModel']),
         f'TRENDS = {TRENDS!r}   # (statsmodels\' trend, damped) of N, A, Ad, M and Md',
         'SEASONS = {"N": None, "A": "add", "M": "mul"}', '',
         'def fit_ets(y, error, trend, seasonal, m):   # an ETS model, fitted as the report fits it (the missing values filled)',
         '    x = y.interpolate(limit_direction="both").reset_index(drop=True)',
         '    return ETSModel(x, error=error, trend=TRENDS[trend][0], damped_trend=TRENDS[trend][1], seasonal=SEASONS[seasonal],',
         '                    seasonal_periods=m if seasonal != "N" else None, initialization_method="estimated").fit(disp=False, maxiter=1000)', '']
    if held:
        L += [f'H = {H}   # the last values held back: the candidates are compared on their forecasts of them ({CRITERIA[criterion]})',
              'def score(y, error, trend, seasonal, m):',
              '    res = fit_ets(y.iloc[:-H], error, trend, seasonal, m)',
              '    a = y.iloc[-H:].to_numpy(); e = a - np.asarray(res.forecast(H)); ok = np.isfinite(e)',
              {'rmse': '    return np.sqrt(np.mean(e[ok] ** 2))', 'mae': '    return np.mean(np.abs(e[ok]))',
               'mape': '    return 100 * np.mean(np.abs(e[ok] / a[ok]))'}[criterion], '']
    else:
        attr = {'aicc': 'aicc', 'aic': 'aic', 'bic': 'bic'}[criterion]
        L += [f'def score(y, error, trend, seasonal, m):   # {CRITERIA[criterion]}, statsmodels\' (Nparm counts the smoothing parameters, the starting states and σ)',
              f'    return fit_ets(y, error, trend, seasonal, m).{attr}', '']
    getters = []
    for k, (sp, S, x, miss, m, cands, err) in enumerate(loaded, 1):
        if S is None or not cands:
            continue
        fn = f'series_{k}'
        body = ts._series_lines(S, sp.get('where') or [])
        L += [f'def {fn}(df):   # {one_line(sp.get("label") or sp.get("key"))}', *['    ' + ln for ln in body], '    return y', '']
        getters.append((sp.get('label') or sp.get('key'), fn, m, [list(c) for c in cands]))
    L += ['summary, forecasts = [], []', 'for name, get, m, candidates in [']
    for name, fn, m, cands in getters:
        L.append(f'        ({J(name)}, {fn}, {m}, {cands}),')
    L += [']:',
          '    y = get(df)',
          '    scores = {}',
          '    for spec in candidates:   # (error, trend, seasonal) of every candidate of the model set that the series allows',
          '        try:',
          '            scores[tuple(spec)] = score(y, *spec, m)',
          '        except Exception:',
          '            continue',
          '    best = min(scores, key=scores.get)',
          '    model = f\'ETS({"A" if best[0] == "add" else "M"},{best[1]},{best[2]})\' + (str(m) if best[2] != "N" else "")   # ETS(M,A,M)12, as the report names it',
          f'    summary.append({{"Series": name, "Model": model, {J(CRITERIA[criterion])}: scores[best]}})',
          '    res = fit_ets(y, *best, m)   # the chosen model on every value',
          f'    fr = res.get_prediction(start=len(res.fittedvalues), end=len(res.fittedvalues) + {h - 1}, simulate_repetitions=2000, random_state={ts.SEED}).summary_frame(alpha={1 - level:.6g})',
          '    forecasts.append(fr.assign(Series=name))',
          'print(pd.DataFrame(summary).to_string())',
          'print(pd.concat(forecasts).to_string())']
    return '\n'.join(L)


J = json.dumps
