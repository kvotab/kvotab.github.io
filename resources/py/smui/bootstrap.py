"""Bootstrap confidence limits (JMP Pro's Bootstrap on a report table).

The page resamples the rows of a report with replacement, runs the platform
again on each sample and collects the numbers of one table of it
(smui-bootstrap.js): a Bootstrap Results table with a row per sample
(BootID 0 is the report itself) and a column per statistic. This module
turns such columns into confidence limits:

  percentile         the quantiles of the bootstrap values (JMP's quantile
                     rule, (n + 1)p);
  bias-corrected     the quantiles at Phi(2 z0 + z), z0 = Phi^-1 of the
                     share of values below the original (ties half);
  BCa                also corrected for the acceleration a, from the
                     jackknife (the platform run without each row in
                     turn): Phi(z0 + (z0 + z) / (1 - a (z0 + z)))
                     (Efron 1987; Efron and Tibshirani 1993, ch. 14).
"""
import json

import numpy as np
from scipy import stats

from . import data
from .registry import api
from .util import code_head

COVERAGE = (0.90, 0.95, 0.99)


def acceleration(jack):
    """Efron's acceleration from the jackknife values."""
    j = np.asarray(jack, dtype=float)
    j = j[np.isfinite(j)]
    if len(j) < 3:
        return None
    d = j.mean() - j
    s2 = float(np.sum(d * d))
    return float(np.sum(d ** 3) / (6 * s2 ** 1.5)) if s2 > 0 else 0.0


def intervals(original, samples, jackknife=None, coverage=COVERAGE, quantile='weibull'):
    """The summary and limits of one statistic's bootstrap values."""
    t0 = float(original) if original is not None else float('nan')
    th = np.asarray([np.nan if v is None else v for v in samples], dtype=float)
    th = th[np.isfinite(th)]
    B = len(th)
    out = {'original': t0 if np.isfinite(t0) else None, 'n_samples': B, 'n_missing': int(len(samples) - B)}
    if B < 2:
        out['error'] = 'fewer than two samples gave a value'
        return out
    q = lambda p: float(np.quantile(th, p, method=quantile))  # noqa: E731
    out.update({'mean': float(th.mean()), 'std_error': float(th.std(ddof=1)), 'bias': float(th.mean() - t0) if np.isfinite(t0) else None})
    z0 = None
    if np.isfinite(t0):
        p0 = (np.sum(th < t0) + 0.5 * np.sum(th == t0)) / B
        if 0 < p0 < 1:
            z0 = float(stats.norm.ppf(p0))
    a = acceleration(jackknife) if jackknife is not None else None
    out['z0'], out['acceleration'] = z0, a
    rows = []
    for c in coverage:
        al = (1 - float(c)) / 2
        z = stats.norm.ppf([al, 1 - al])
        row = {'coverage': float(c), 'pct_lower': q(al), 'pct_upper': q(1 - al)}
        if z0 is not None:
            b = stats.norm.cdf(2 * z0 + z)
            row['bc_lower'], row['bc_upper'] = q(b[0]), q(b[1])
            if a is not None:
                w = z0 + z
                ba = stats.norm.cdf(z0 + w / (1 - a * w))
                row['bca_lower'], row['bca_upper'] = q(ba[0]), q(ba[1])
        rows.append(row)
    out['limits'] = rows
    return out


def _keep_lines(table, rows, where=None):
    """After the code's head: the By group's rows (its where lines) and, of
    those, the ones the report uses (excluded and filtered rows dropped)."""
    L = []
    n = data.TABLES[table]['n'] if table in data.TABLES else 0
    match = np.ones(n, dtype=bool)
    for w in where or []:
        v = data.raw(table, w['column'])
        num = data.meta(table, w['column']).get('dataType') == 'numeric'
        match &= (np.asarray(v, dtype=float) == float(w['value'])) if num else np.array([x == w['value'] for x in v], dtype=bool)
        lit = repr(float(w['value'])) if num else json.dumps(w['value'])
        L.append(f'df = df[df[{json.dumps(w["column"])}] == {lit}]   # only the rows where {w["column"]} is {w["value"]}')
    if rows is not None and n:
        keep = np.zeros(n, dtype=bool)
        keep[np.asarray(rows, dtype=int)] = True
        drop = np.flatnonzero(match & ~keep).tolist()
        if drop and not where and keep.sum() <= n / 2:
            return [f'df = df.loc[{np.flatnonzero(keep).tolist()}]   # the rows of the report']
        if drop:
            L.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
    return L


@api('bootstrap.report')
def report(table, columns, rows=None, jackknife=None, coverage=COVERAGE, where=None, table_name='data'):
    """The Bootstrap report of a Bootstrap Results table: for each column,
    the original estimate (BootID 0), the bootstrap values (BootID > 0) and
    their limits. The code keeps the report's rows (excluded and filtered
    rows dropped)."""
    cols = [c for c in columns if c != 'BootID']
    df = data.frame(table, ['BootID'] + cols, rows, dropna=False, as_category=False)
    boot = df['BootID'].to_numpy(float)
    out = []
    for c in cols:
        v = df[c].to_numpy(float)
        orig = v[boot == 0]
        res = intervals(orig[0] if len(orig) else None, v[boot > 0].tolist(), (jackknife or {}).get(c), coverage)
        res['column'] = c
        res['rows'] = [int(i) for i in df.index[boot > 0]]
        out.append(res)
    name = json.dumps(cols[0]) if cols else '"x"'
    lines = [code_head(table_name, ['from scipy import stats']), *_keep_lines(table, rows, where),
             f'x = df.loc[df["BootID"] > 0, {name}].dropna().to_numpy()   # the bootstrap values',
             f't0 = df.loc[df["BootID"] == 0, {name}].iloc[0]   # the original estimate',
             'print(x.mean(), x.std(ddof=1), x.mean() - t0)   # mean, std error, bias',
             'al = np.array([0.05, 0.025, 0.005])   # 90%, 95%, 99%',
             'print(np.quantile(x, al, method="weibull"), np.quantile(x, 1 - al, method="weibull"))   # percentile limits',
             'z0 = stats.norm.ppf((np.sum(x < t0) + 0.5 * np.sum(x == t0)) / len(x))',
             'print(np.quantile(x, stats.norm.cdf(2 * z0 + stats.norm.ppf(al)), method="weibull"), np.quantile(x, stats.norm.cdf(2 * z0 + stats.norm.ppf(1 - al)), method="weibull"))   # bias-corrected']
    jk = (jackknife or {}).get(cols[0]) if cols else None
    if jk:
        vals = ', '.join('nan' if v is None or not np.isfinite(v) else repr(float(v)) for v in jk)
        lines += ['nan = np.nan',
                  f'jack = np.array([{vals}])   # the statistic with each row of the report left out in turn',
                  'jack = jack[np.isfinite(jack)]; d = jack.mean() - jack; a = np.sum(d**3) / (6 * np.sum(d**2)**1.5)',
                  'w = z0 + stats.norm.ppf(al); print(np.quantile(x, stats.norm.cdf(z0 + w / (1 - a * w)), method="weibull"))   # BCa lower',
                  'w = z0 + stats.norm.ppf(1 - al); print(np.quantile(x, stats.norm.cdf(z0 + w / (1 - a * w)), method="weibull"))   # BCa upper']
    return {'stats': out, 'code': '\n'.join(lines)}
