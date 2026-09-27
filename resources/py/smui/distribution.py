"""Distribution: one column at a time.

Continuous columns: moments, JMP's quantiles, normality tests, tests of the
mean and the standard deviation, fitted distributions with standard errors,
process capability, and for counts the test of a Poisson rate (with an
exposure). Categorical columns: frequencies with confidence intervals by a
choice of method, and a test of hypothesised probabilities.

The statistics are statsmodels' where it has them (DescrStatsW, the
normality tests, GenericLikelihoodModel for the standard errors of a fit,
proportion_confint) and scipy's otherwise (Shapiro-Wilk, Wilcoxon, the
distribution families).
"""
import json
import math

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.base.model import GenericLikelihoodModel
from statsmodels.stats.diagnostic import lilliefors, normal_ad
from statsmodels.stats.proportion import proportion_confint
from statsmodels.stats.stattools import jarque_bera
from statsmodels.stats.weightstats import DescrStatsW

from . import data
from .registry import api
from .util import code_head, col, table

# JMP's quantiles, top down.
QUANTILES = [(1.0, 'maximum'), (0.995, ''), (0.975, ''), (0.90, ''), (0.75, 'quartile'), (0.50, 'median'),
             (0.25, 'quartile'), (0.10, ''), (0.025, ''), (0.005, ''), (0.0, 'minimum')]


def _values(table_id, column, rows, weight=None, freq=None):
    df = data.frame(table_id, [column, weight, freq], rows, as_category=False)
    df, w = data.weights(df, table_id, weight, freq)
    x = df[column].to_numpy(float)
    ok = np.isfinite(x)
    return x[ok], w[ok], df.index.to_numpy()[ok]


def _n_missing(table_id, column, rows):
    v = data.raw(table_id, column, rows)
    return int(np.sum(~np.isfinite(v.astype(float))))


@api('distribution.continuous')
def continuous(table, column, rows=None, weight=None, freq=None, alpha=0.05, table_name='data'):
    x, w, _ = _values(table, column, rows, weight, freq)
    n = len(x)
    out = {'column': column, 'n_rows': n, 'n_missing': _n_missing(table, column, rows)}
    if n == 0:
        out['error'] = 'no non-missing values'
        return out
    d = DescrStatsW(x, weights=w, ddof=1)
    weighted = weight is not None or freq is not None
    mean, sd = float(d.mean), float(d.std) if n > 1 else float('nan')
    se = float(d.std_mean) if n > 1 else float('nan')
    lo, hi = d.tconfint_mean(alpha) if n > 1 else (float('nan'), float('nan'))
    if weighted:
        qv = d.quantile([p for p, _ in QUANTILES], return_pandas=False)
    else:
        qv = np.quantile(x, [p for p, _ in QUANTILES], method='weibull')
    quant = [{'p': p, 'label': lab, 'value': float(v)} for (p, lab), v in zip(QUANTILES, qv)]
    moments = {
        'mean': mean, 'sd': sd, 'se': se, 'lower': float(lo), 'upper': float(hi), 'n': float(d.sum_weights),
        'sum_w': float(np.sum(w)), 'sum': float(np.sum(w * x)), 'var': float(d.var) if n > 1 else float('nan'),
        'cv': 100 * sd / mean if mean else float('nan'), 'min': float(np.min(x)), 'max': float(np.max(x)),
        'median': float(np.quantile(x, 0.5, method='weibull')) if not weighted else float(d.quantile([0.5], return_pandas=False)[0]),
        'range': float(np.max(x) - np.min(x)),
    }
    moments['iqr'] = quant[4]['value'] - quant[6]['value']
    if not weighted and n > 2:
        moments['skewness'] = float(stats.skew(x, bias=False))
    if not weighted and n > 3:
        moments['kurtosis'] = float(stats.kurtosis(x, bias=False))
    moments.update(_more_stats(x, w, weighted, mean))
    out['moments'] = moments
    out['quantiles'] = quant
    out['alpha'] = alpha
    out['normality'] = _normality(x) if not weighted else None
    c = [code_head(table_name, ['from statsmodels.stats.weightstats import DescrStatsW']),
         f'x = df[{json.dumps(column)}].dropna()']
    if weighted:
        wexpr = ' * '.join(f'df[{json.dumps(v)}]' for v in (weight, freq) if v)
        c.append(f'd = DescrStatsW(x, weights=({wexpr}).loc[x.index], ddof=1)')
    else:
        c.append('d = DescrStatsW(x, ddof=1)')
    c += ['print(d.mean, d.std, d.std_mean, d.tconfint_mean(alpha=%g))' % alpha,
          'print(np.quantile(x, [1, .995, .975, .9, .75, .5, .25, .1, .025, .005, 0], method="weibull"))']
    out['code'] = '\n'.join(c)
    return out


def _more_stats(x, w, weighted, mean):
    """The rest of JMP's Customize Summary Statistics: sums of squares,
    counts, robust and trimmed estimates, the shortest half."""
    n = len(x)
    out = {'n_zero': int(np.sum(x == 0)), 'n_unique': int(len(np.unique(x))),
           'uss': float(np.sum(w * x * x)), 'css': float(np.sum(w * (x - mean) ** 2))}
    if not weighted:
        xs = np.sort(x)
        out['geomean'] = float(stats.gmean(x)) if np.all(x > 0) else None
        out['trimmed'] = float(stats.trim_mean(x, 0.05)) if n > 2 else None
        med = float(np.median(x))
        out['mad'] = float(np.median(np.abs(x - med)))
        vals, counts = np.unique(x, return_counts=True)
        out['mode'] = float(vals[np.argmax(counts)])
        out['mode_count'] = int(counts.max())
        out['autocorr'] = float(np.corrcoef(x[:-1], x[1:])[0, 1]) if n > 2 and np.std(x) > 0 else None
        # the shortest interval that holds half the values
        h = n // 2 + 1 if n > 1 else 1
        if n > 1:
            widths = xs[h - 1:] - xs[:n - h + 1]
            i = int(np.argmin(widths))
            out['shortest_half'] = [float(xs[i]), float(xs[i + h - 1])]
        try:
            from statsmodels.robust.scale import Huber
            if n >= 5 and np.std(x) > 0:
                loc, scale = Huber()(x)
                out['robust_mean'] = float(np.asarray(loc).item())
                out['robust_sd'] = float(np.asarray(scale).item())
        except Exception:
            pass
    return out


@api('distribution.intervals')
def intervals(table, column, rows=None, alpha=0.05, k_future=1, coverage=0.90, table_name='data'):
    """Prediction interval for k future values and a two-sided normal
    tolerance interval (Howe's k factor), as JMP's Prediction Interval and
    Tolerance Interval."""
    x, _, _ = _values(table, column, rows)
    n = len(x)
    if n < 2:
        return {'error': 'fewer than two values'}
    m, s = float(np.mean(x)), float(np.std(x, ddof=1))
    k = max(1, int(k_future))
    # Bonferroni over k future values, as JMP does for individual values
    t = stats.t.ppf(1 - alpha / (2 * k), n - 1)
    half = t * s * math.sqrt(1 + 1 / n)
    # the mean of k future values
    tm = stats.t.ppf(1 - alpha / 2, n - 1)
    half_m = tm * s * math.sqrt(1 / k + 1 / n)
    # tolerance: covers `coverage` of the population with confidence 1-alpha
    z = stats.norm.ppf((1 + coverage) / 2)
    chi = stats.chi2.ppf(alpha, n - 1)
    ktol = z * math.sqrt((n - 1) * (1 + 1 / n) / chi)
    return {'n': n, 'mean': m, 'sd': s, 'alpha': alpha, 'k': k, 'coverage': coverage,
            'prediction': {'lower': m - half, 'upper': m + half},
            'prediction_mean': {'lower': m - half_m, 'upper': m + half_m},
            'prediction_sd': {'lower': s * math.sqrt(stats.f.ppf(alpha / 2, k - 1, n - 1)) if k > 1 else None,
                              'upper': s * math.sqrt(stats.f.ppf(1 - alpha / 2, k - 1, n - 1)) if k > 1 else None},
            'tolerance': {'lower': m - ktol * s, 'upper': m + ktol * s, 'k': ktol},
            'code': '\n'.join([code_head(table_name, ['from scipy import stats']),
                               f'x = df[{json.dumps(column)}].dropna().to_numpy(); n, m, s = len(x), x.mean(), x.std(ddof=1)',
                               f't = stats.t.ppf(1 - {alpha}/(2*{k}), n - 1); print(m - t*s*np.sqrt(1 + 1/n), m + t*s*np.sqrt(1 + 1/n))   # prediction',
                               f'k = stats.norm.ppf((1 + {coverage})/2) * np.sqrt((n - 1)*(1 + 1/n)/stats.chi2.ppf({alpha}, n - 1)); print(m - k*s, m + k*s)   # tolerance (Howe)'])}


@api('distribution.equivalence')
def equivalence(table, column, rows=None, low=None, upp=None, alpha=0.05, table_name='data'):
    """Two one-sided t tests that the mean lies between low and upp."""
    x, _, _ = _values(table, column, rows)
    if len(x) < 2 or low is None or upp is None or not low < upp:
        return {'error': 'need two values and a lower bound below the upper'}
    d = DescrStatsW(x, ddof=1)
    p, lower, upper = d.ttost_mean(low, upp)
    return {'low': low, 'upp': upp, 'p': float(p), 'alpha': alpha, 'mean': float(d.mean),
            'lower': {'t': float(lower[0]), 'p': float(lower[1]), 'df': float(lower[2])},
            'upper': {'t': float(upper[0]), 'p': float(upper[1]), 'df': float(upper[2])},
            'ci': [float(v) for v in d.tconfint_mean(2 * alpha)],
            'code': '\n'.join([code_head(table_name, ['from statsmodels.stats.weightstats import DescrStatsW']),
                               f'x = df[{json.dumps(column)}].dropna()',
                               f'print(DescrStatsW(x, ddof=1).ttost_mean({low!r}, {upp!r}))   # p, (t, p, df) lower, (t, p, df) upper'])}


def _normality(x):
    n = len(x)
    res = []
    if 3 <= n <= 5000:
        w, p = stats.shapiro(x)
        res.append({'test': 'Shapiro-Wilk W', 'stat': float(w), 'p': float(p)})
    if n >= 8:
        a2, p = normal_ad(x)
        res.append({'test': 'Anderson-Darling A²', 'stat': float(a2), 'p': float(p)})
        ks, p = lilliefors(x, dist='norm', pvalmethod='table')
        res.append({'test': 'Lilliefors (Kolmogorov-Smirnov) D', 'stat': float(ks), 'p': float(p)})
        jb, p, _, _ = jarque_bera(x)
        res.append({'test': 'Jarque-Bera', 'stat': float(jb), 'p': float(p)})
    return res


@api('distribution.qq')
def qq(table, column, rows=None):
    """Normal quantile plot: each value against Φ⁻¹(r/(n+1)), as JMP."""
    x, _, idx = _values(table, column, rows)
    order = np.argsort(x, kind='stable')
    n = len(x)
    r = stats.rankdata(x[order], method='average')
    z = stats.norm.ppf(r / (n + 1))
    mean, sd = float(np.mean(x)), float(np.std(x, ddof=1)) if n > 1 else 0.0
    return {'x': x[order].tolist(), 'z': z.tolist(), 'rows': idx[order].tolist(), 'mean': mean, 'sd': sd}


@api('distribution.test_mean')
def test_mean(table, column, rows=None, mu=0.0, sigma=None, wilcoxon=True, weight=None, freq=None, table_name='data'):
    x, w, _ = _values(table, column, rows, weight, freq)
    n = len(x)
    if n < 2:
        return {'error': 'fewer than two values'}
    d = DescrStatsW(x, weights=w, ddof=1)
    t, p2, df = d.ttest_mean(mu)
    res = {'mu': mu, 'mean': float(d.mean), 'sd': float(d.std), 'n': float(d.sum_weights), 'df': float(df)}
    res['t'] = {'stat': float(t), 'p_two': float(p2), 'p_greater': float(stats.t.sf(t, df)), 'p_less': float(stats.t.cdf(t, df))}
    if sigma:
        z = (d.mean - mu) / (sigma / math.sqrt(d.sum_weights))
        res['z'] = {'stat': float(z), 'sigma': sigma, 'p_two': float(2 * stats.norm.sf(abs(z))), 'p_greater': float(stats.norm.sf(z)), 'p_less': float(stats.norm.cdf(z))}
    if wilcoxon and weight is None and freq is None:
        dif = x - mu
        dif = dif[dif != 0]
        if len(dif) >= 2:
            wr = stats.wilcoxon(dif)
            ranks = stats.rankdata(np.abs(dif))
            s = float(np.sum(np.sign(dif) * ranks) / 2)  # JMP's signed-rank statistic
            res['wilcoxon'] = {'stat': s, 'W': float(wr.statistic), 'p_two': float(wr.pvalue),
                               'p_greater': float(stats.wilcoxon(dif, alternative='greater').pvalue),
                               'p_less': float(stats.wilcoxon(dif, alternative='less').pvalue)}
    res['code'] = '\n'.join([code_head(table_name, ['from statsmodels.stats.weightstats import DescrStatsW', 'from scipy import stats']),
                             f'x = df[{json.dumps(column)}].dropna()',
                             f'print(DescrStatsW(x, ddof=1).ttest_mean({mu!r}))   # t, p (two-sided), df',
                             f'print(stats.wilcoxon(x - {mu!r}))'])
    return res


def _weighted_lines(column, weight, freq):
    """The code lines that read the column (and its weights) as the report does."""
    cols = [v for v in (column, weight, freq) if v]
    lines = [f'd = df[[{", ".join(json.dumps(v) for v in cols)}]].dropna()']
    if weight or freq:
        wexpr = ' * '.join(f'd[{json.dumps(v)}]' for v in (weight, freq) if v)
        lines.append(f'd = d[{wexpr} > 0]; ds = DescrStatsW(d[{json.dumps(column)}], weights={wexpr}, ddof=1)')
    else:
        lines.append(f'ds = DescrStatsW(d[{json.dumps(column)}], ddof=1)')
    lines.append('m, s, n = ds.mean, ds.std, ds.sum_weights')
    return lines


@api('distribution.effect')
def effect(table, column, rows=None, mu=0.0, weight=None, freq=None, alpha=0.05, table_name='data'):
    """Effect Size of Test Mean: Cohen's d = (mean − μ₀)/s with the exact
    interval from the noncentral t of the t test (δ = λ/√n; Steiger and
    Fouladi 1997), and Hedges' g = J(n − 1)·d (Hedges 1981). With Weight or
    Freq, n is the sum of the weights, as in the t test."""
    from .fit_y_by_x import NCP_T_CODE, _es_table, smd_rows
    x, w, _ = _values(table, column, rows, weight, freq)
    if len(x) < 2:
        return {'error': 'fewer than two values'}
    d = DescrStatsW(x, weights=w, ddof=1)
    n, sd = float(d.sum_weights), float(d.std)
    if not n > 2:
        return {'error': 'Hedges\' g needs more than two values'}
    if not sd > 0:
        return {'error': 'the values do not vary: no standardized effect'}
    dd = (float(d.mean) - mu) / sd
    rows_out = smd_rows(dd, dd * math.sqrt(n), n - 1, 1 / math.sqrt(n), alpha)
    out = {'table': _es_table(rows_out, alpha), 'mu': mu, 'n': n, 'sd': sd, 'alpha': alpha, 'j': rows_out[1]['j']}
    c = [code_head(table_name, ['from statsmodels.stats.weightstats import DescrStatsW', 'from scipy import stats, optimize, special'])]
    c += _weighted_lines(column, weight, freq)
    c.append(NCP_T_CODE)
    c.append(f'd_ = (m - {mu!r}) / s; t = d_ * np.sqrt(n); lo, hi = ncp(t, n - 1, {1 - alpha / 2!r}) / np.sqrt(n), ncp(t, n - 1, {alpha / 2!r}) / np.sqrt(n)')
    c.append('J = np.exp(special.gammaln((n - 1) / 2) - 0.5 * np.log((n - 1) / 2) - special.gammaln((n - 2) / 2))   # Hedges\' exact correction')
    c.append("print(d_, lo, hi, J * d_, J * lo, J * hi)   # Cohen's d with its exact interval (noncentral t), Hedges' g = J d")
    out['code'] = '\n'.join(c)
    return out


@api('distribution.bayes_t')
def bayes_t(table, column, rows=None, mu=0.0, r=None, weight=None, freq=None, table_name='data'):
    """Bayes Factor of Test Mean (Rouder et al. 2009): the t of the mean
    against μ₀, a Cauchy(0, r) prior on δ = (μ − μ₀)/σ under the
    alternative (r = √2/2 by default); two-sided and one-sided."""
    from .fit_y_by_x import JZS_CODE, JZS_R, _bf_table, jzs_rows
    r = JZS_R if r is None else r
    if not r > 0:
        return {'error': 'the scale of the Cauchy prior must be positive'}
    x, w, _ = _values(table, column, rows, weight, freq)
    if len(x) < 2:
        return {'error': 'fewer than two values'}
    d = DescrStatsW(x, weights=w, ddof=1)
    n, sd = float(d.sum_weights), float(d.std)
    if not sd > 0:
        return {'error': 'the values do not vary: no t statistic'}
    t = (float(d.mean) - mu) / (sd / math.sqrt(n))
    rows_out = jzs_rows(t, n, n - 1, r, [f'mean ≠ {mu:g}', f'mean > {mu:g}', f'mean < {mu:g}'])
    out = {'table': _bf_table(rows_out), 't': t, 'n': n, 'df': n - 1, 'r': r, 'mu': mu}
    c = [code_head(table_name, ['from statsmodels.stats.weightstats import DescrStatsW', 'from scipy import stats, integrate'])]
    c += _weighted_lines(column, weight, freq)
    c.append(f't = (m - {mu!r}) / (s / np.sqrt(n))')
    c.append(JZS_CODE)
    c.append(f'bf, p = jzs(t, n, n - 1, {r!r}); print(bf, 2*bf*p, 2*bf*(1 - p))   # BF10: two-sided, mean above, mean below; BF01 = 1/BF10')
    out['code'] = '\n'.join(c)
    return out


def _lit(v):
    """A level as a Python literal: 12.0 as 12, text quoted."""
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        f = float(v)
        return str(int(f)) if f.is_integer() else repr(f)
    return json.dumps(str(v))


@api('distribution.bayes_binom')
def bayes_binom(table, column, rows=None, probs=None, a=1.0, b=1.0, weight=None, freq=None, table_name='data'):
    """Bayes Factor of Test Probabilities for a column of two levels: the
    count k of the first level out of n against its hypothesized
    probability p₀, a beta(a, b) prior on the probability under the
    alternative (a = b = 1, uniform, by default): BF10 = B(k + a, n − k +
    b)/(B(a, b) p₀^k (1 − p₀)^(n−k)); one-sided, the prior cut at p₀:
    BF±0 = BF10·P(p ≷ p₀ | data)/P(p ≷ p₀)."""
    from scipy.special import betaln
    from .fit_y_by_x import _bf_row, _bf_table
    if not (a and a > 0 and b and b > 0):
        return {'error': 'the beta prior needs positive a and b'}
    res = categorical(table, column, rows, weight, freq)
    if 'error' in res:
        return res
    lv = res['levels']
    if len(lv) != 2:
        return {'error': f'the binomial Bayes factor is for a column of two levels; {column} has {len(lv)}'}
    labels = [l['level'] for l in lv]
    p = np.array([float((probs or {}).get(str(l), (probs or {}).get(l, 0)) or 0) for l in labels], dtype=float)
    if not p.sum() > 0:
        return {'error': 'give hypothesized probabilities'}
    p0 = float(p[0] / p.sum())
    if not 0 < p0 < 1:
        return {'error': 'the hypothesized probabilities must both be above zero'}
    k, n = float(lv[0]['count']), float(res['n'])
    lb = betaln(k + a, n - k + b) - betaln(a, b) - k * math.log(p0) - (n - k) * math.log(1 - p0)
    lpos = lb + stats.beta.logsf(p0, k + a, n - k + b) - stats.beta.logsf(p0, a, b)
    lneg = lb + stats.beta.logcdf(p0, k + a, n - k + b) - stats.beta.logcdf(p0, a, b)
    name = str(labels[0]) if not isinstance(labels[0], float) or not labels[0].is_integer() else str(int(labels[0]))
    rows_out = [_bf_row(f'P({name}) ≠ {p0:g}', lb), _bf_row(f'P({name}) > {p0:g}', lpos), _bf_row(f'P({name}) < {p0:g}', lneg)]
    notes = []
    if abs(k - round(k)) > 1e-9 or abs(n - round(n)) > 1e-9:
        notes.append('The counts are sums of weights and not whole numbers; the Bayes factor takes them as they are.')
    out = {'table': _bf_table(rows_out), 'k': k, 'n': n, 'p0': p0, 'a': a, 'b': b, 'level': labels[0], 'notes': notes}
    c = [code_head(table_name, ['from scipy import stats, special'])]
    if weight or freq:
        wexpr = ' * '.join(f'df[{json.dumps(v)}]' for v in (weight, freq) if v)
        c.append(f'counts = ({wexpr}).groupby(df[{json.dumps(column)}]).sum().reindex([{_lit(labels[0])}, {_lit(labels[1])}])')
    else:
        c.append(f'counts = df[{json.dumps(column)}].value_counts().reindex([{_lit(labels[0])}, {_lit(labels[1])}])')
    c.append(f'k, n, p0, a, b = counts.iloc[0], counts.sum(), {p0!r}, {a!r}, {b!r}   # the first level\'s count, its hypothesized probability, the beta prior')
    c.append('bf = np.exp(special.betaln(k + a, n - k + b) - special.betaln(a, b) - k*np.log(p0) - (n - k)*np.log(1 - p0))')
    c.append('print(bf, bf * stats.beta.sf(p0, k + a, n - k + b) / stats.beta.sf(p0, a, b), bf * stats.beta.cdf(p0, k + a, n - k + b) / stats.beta.cdf(p0, a, b))   # BF10: ≠, >, <; BF01 = 1/BF10')
    out['code'] = '\n'.join(c)
    return out


@api('distribution.test_sd')
def test_sd(table, column, rows=None, sigma=1.0):
    x, _, _ = _values(table, column, rows)
    n = len(x)
    if n < 2 or not sigma or sigma <= 0:
        return {'error': 'need two values and a positive hypothesised σ'}
    s = float(np.std(x, ddof=1))
    chi2 = (n - 1) * s * s / (sigma * sigma)
    lo, hi = stats.chi2.cdf(chi2, n - 1), stats.chi2.sf(chi2, n - 1)
    return {'sigma': sigma, 'sd': s, 'n': n, 'df': n - 1, 'chi2': chi2, 'p_two': float(min(1.0, 2 * min(lo, hi))), 'p_greater': float(hi), 'p_less': float(lo)}


@api('distribution.ci')
def conf_intervals(table, column, rows=None, alpha=0.05):
    x, _, _ = _values(table, column, rows)
    n = len(x)
    if n < 2:
        return {'error': 'fewer than two values'}
    d = DescrStatsW(x, ddof=1)
    m_lo, m_hi = d.tconfint_mean(alpha)
    s = float(d.std)
    v_lo = (n - 1) * s * s / stats.chi2.ppf(1 - alpha / 2, n - 1)
    v_hi = (n - 1) * s * s / stats.chi2.ppf(alpha / 2, n - 1)
    return {'alpha': alpha, 'rows': [
        {'parameter': 'Mean', 'estimate': float(d.mean), 'lower': float(m_lo), 'upper': float(m_hi)},
        {'parameter': 'Std Dev', 'estimate': s, 'lower': math.sqrt(v_lo), 'upper': math.sqrt(v_hi)},
        {'parameter': 'Variance', 'estimate': s * s, 'lower': v_lo, 'upper': v_hi},
    ]}


# ---- fitted distributions -------------------------------------------------

class _Fit(GenericLikelihoodModel):
    """Maximum likelihood on the natural parameters, for the Hessian-based
    standard errors of statsmodels' GenericLikelihoodModel."""

    def __init__(self, endog, logpdf, names):
        self._logpdf = logpdf
        super().__init__(endog, exog=None, extra_params_names=list(names))

    def loglike(self, params):
        with np.errstate(all='ignore'):
            v = self._logpdf(self.endog, params)
        s = np.sum(v)
        return s if np.isfinite(s) else -1e300


def _families(x):
    """(key, label, names, fit(x)->params, logpdf(x, params), pdf(grid, params), cdf(x, params), k, applicable)"""
    pos = bool(np.all(x > 0))
    unit = bool(np.all((x > 0) & (x < 1)))
    counts = bool(np.all(x >= 0) and np.all(np.equal(np.mod(x, 1), 0)))
    fam = []
    fam.append(('normal', 'Normal', ['μ (location)', 'σ (dispersion)'],
                lambda v: [np.mean(v), np.std(v, ddof=1)],
                lambda v, p: stats.norm.logpdf(v, p[0], p[1]) if p[1] > 0 else np.full_like(v, -np.inf),
                lambda g, p: stats.norm.pdf(g, p[0], p[1]), lambda v, p: stats.norm.cdf(v, p[0], p[1]), True))
    fam.append(('lognormal', 'Lognormal', ['μ (scale, log)', 'σ (shape, log)'],
                lambda v: [np.mean(np.log(v)), np.std(np.log(v), ddof=1)],
                lambda v, p: stats.lognorm.logpdf(v, p[1], scale=np.exp(p[0])) if p[1] > 0 else np.full_like(v, -np.inf),
                lambda g, p: stats.lognorm.pdf(g, p[1], scale=np.exp(p[0])), lambda v, p: stats.lognorm.cdf(v, p[1], scale=np.exp(p[0])), pos))
    fam.append(('weibull', 'Weibull', ['α (scale)', 'β (shape)'],
                lambda v: (lambda c, loc, sc: [sc, c])(*stats.weibull_min.fit(v, floc=0)),
                lambda v, p: stats.weibull_min.logpdf(v, p[1], scale=p[0]) if p[0] > 0 and p[1] > 0 else np.full_like(v, -np.inf),
                lambda g, p: stats.weibull_min.pdf(g, p[1], scale=p[0]), lambda v, p: stats.weibull_min.cdf(v, p[1], scale=p[0]), pos))
    fam.append(('exponential', 'Exponential', ['σ (scale)'],
                lambda v: [np.mean(v)],
                lambda v, p: stats.expon.logpdf(v, scale=p[0]) if p[0] > 0 else np.full_like(v, -np.inf),
                lambda g, p: stats.expon.pdf(g, scale=p[0]), lambda v, p: stats.expon.cdf(v, scale=p[0]), pos))
    fam.append(('gamma', 'Gamma', ['α (shape)', 'σ (scale)'],
                lambda v: (lambda a, loc, sc: [a, sc])(*stats.gamma.fit(v, floc=0)),
                lambda v, p: stats.gamma.logpdf(v, p[0], scale=p[1]) if p[0] > 0 and p[1] > 0 else np.full_like(v, -np.inf),
                lambda g, p: stats.gamma.pdf(g, p[0], scale=p[1]), lambda v, p: stats.gamma.cdf(v, p[0], scale=p[1]), pos))
    fam.append(('beta', 'Beta', ['α (shape 1)', 'β (shape 2)'],
                lambda v: (lambda a, b, loc, sc: [a, b])(*stats.beta.fit(v, floc=0, fscale=1)),
                lambda v, p: stats.beta.logpdf(v, p[0], p[1]) if p[0] > 0 and p[1] > 0 else np.full_like(v, -np.inf),
                lambda g, p: stats.beta.pdf(g, p[0], p[1]), lambda v, p: stats.beta.cdf(v, p[0], p[1]), unit))
    fam.append(('logistic', 'Logistic', ['μ (location)', 's (scale)'],
                lambda v: list(stats.logistic.fit(v)),
                lambda v, p: stats.logistic.logpdf(v, p[0], p[1]) if p[1] > 0 else np.full_like(v, -np.inf),
                lambda g, p: stats.logistic.pdf(g, p[0], p[1]), lambda v, p: stats.logistic.cdf(v, p[0], p[1]), True))
    fam.append(('cauchy', 'Cauchy', ['θ (location)', 'σ (scale)'],
                lambda v: list(stats.cauchy.fit(v)),
                lambda v, p: stats.cauchy.logpdf(v, p[0], p[1]) if p[1] > 0 else np.full_like(v, -np.inf),
                lambda g, p: stats.cauchy.pdf(g, p[0], p[1]), lambda v, p: stats.cauchy.cdf(v, p[0], p[1]), True))
    fam.append(('t', "Student's t", ['μ (location)', 'σ (scale)', 'ν (degrees of freedom)'],
                lambda v: (lambda df, loc, sc: [loc, sc, min(df, 200.0)])(*stats.t.fit(v)),
                lambda v, p: stats.t.logpdf(v, p[2], p[0], p[1]) if p[1] > 0 and 0 < p[2] <= _T_DF_MAX else np.full_like(v, -np.inf),
                lambda g, p: stats.t.pdf(g, p[2], p[0], p[1]), lambda v, p: stats.t.cdf(v, p[2], p[0], p[1]), True))
    fam.append(('johnsonsu', 'Johnson Su', ['γ (shape)', 'δ (shape)', 'θ (location)', 'σ (scale)'],
                lambda v: list(stats.johnsonsu.fit(v)),
                lambda v, p: stats.johnsonsu.logpdf(v, p[0], p[1], p[2], p[3]) if p[1] > 0 and p[3] > 0 else np.full_like(v, -np.inf),
                lambda g, p: stats.johnsonsu.pdf(g, p[0], p[1], p[2], p[3]), lambda v, p: stats.johnsonsu.cdf(v, p[0], p[1], p[2], p[3]), True))
    fam.append(('johnsonsb', 'Johnson Sb', ['γ (shape)', 'δ (shape)', 'θ (lower threshold)', 'σ (range)'],
                lambda v: _sb_start(v),
                lambda v, p: stats.johnsonsb.logpdf(v, p[0], p[1], p[2], p[3]) if p[1] > 0 and p[3] > 0 else np.full_like(v, -np.inf),
                lambda g, p: stats.johnsonsb.pdf(g, p[0], p[1], p[2], p[3]), lambda v, p: stats.johnsonsb.cdf(v, p[0], p[1], p[2], p[3]), len(x) >= 8))
    for k in (2, 3):
        fam.append((f'normal{k}', f'Normal {k} Mixture', [f'μ{i + 1}' for i in range(k)] + [f'σ{i + 1}' for i in range(k)] + [f'π{i + 1} (proportion)' for i in range(k - 1)],
                    (lambda kk: lambda v: _mix_em(v, kk))(k),
                    (lambda kk: lambda v, p: _mix_logpdf(v, p, kk))(k),
                    (lambda kk: lambda g, p: np.exp(_mix_logpdf(g, p, kk)))(k),
                    (lambda kk: lambda v, p: _mix_cdf(v, p, kk))(k), len(x) >= 6 * k))
    fam.append(('poisson', 'Poisson', ['λ (mean)'],
                lambda v: [np.mean(v)],
                lambda v, p: stats.poisson.logpmf(v, p[0]) if p[0] > 0 else np.full_like(v, -np.inf),
                None, lambda v, p: stats.poisson.cdf(v, p[0]), counts))
    fam.append(('negbin', 'Gamma Poisson (negative binomial)', ['λ (mean)', 'σ (overdispersion: variance/mean)'],
                lambda v: [np.mean(v), max(1.05, np.var(v, ddof=1) / max(np.mean(v), 1e-9))],
                lambda v, p: stats.nbinom.logpmf(v, p[0] / (p[1] - 1), 1 / p[1]) if p[0] > 0 and p[1] > 1 else np.full_like(v, -np.inf),
                None, lambda v, p: stats.nbinom.cdf(v, p[0] / (p[1] - 1), 1 / p[1]), counts))
    return fam


# Above this many degrees of freedom a t is a normal for any sample size
# here; the likelihood is flat out there and the optimiser would wander.
_T_DF_MAX = 1000.0


def _sb_start(v):
    lo, hi = float(np.min(v)), float(np.max(v))
    pad = 0.05 * (hi - lo if hi > lo else 1.0)
    try:
        a, b, loc, sc = stats.johnsonsb.fit(v, loc=lo - pad, scale=hi - lo + 2 * pad)
        return [a, b, loc, sc]
    except Exception:
        return [0.0, 1.0, lo - pad, hi - lo + 2 * pad]


def _mix_unpack(p, k):
    mu = np.asarray(p[:k], dtype=float)
    sd = np.asarray(p[k:2 * k], dtype=float)
    pi = np.asarray(list(p[2 * k:3 * k - 1]) + [1 - float(np.sum(p[2 * k:3 * k - 1]))], dtype=float)
    return mu, sd, pi


def _mix_logpdf(v, p, k):
    mu, sd, pi = _mix_unpack(p, k)
    if np.any(sd <= 0) or np.any(pi <= 0):
        return np.full(np.shape(v), -np.inf)
    comp = np.stack([np.log(pi[j]) + stats.norm.logpdf(v, mu[j], sd[j]) for j in range(k)])
    return np.logaddexp.reduce(comp, axis=0)


def _mix_cdf(v, p, k):
    mu, sd, pi = _mix_unpack(p, k)
    return sum(pi[j] * stats.norm.cdf(v, mu[j], sd[j]) for j in range(k))


def _mix_em(x, k, iters=500):
    """Normal mixture by EM from quantile starts: the starting values for
    the likelihood fit (which then gives the standard errors)."""
    x = np.asarray(x, dtype=float)
    qs = np.quantile(x, (np.arange(k) + 0.5) / k)
    mu, sd, pi = qs.copy(), np.full(k, np.std(x) / k + 1e-9), np.full(k, 1 / k)
    for _ in range(iters):
        dens = np.stack([pi[j] * stats.norm.pdf(x, mu[j], sd[j]) for j in range(k)])
        tot = dens.sum(axis=0) + 1e-300
        w = dens / tot
        nk = w.sum(axis=1) + 1e-12
        mu_new = (w * x).sum(axis=1) / nk
        sd = np.sqrt((w * (x - mu_new[:, None]) ** 2).sum(axis=1) / nk) + 1e-9
        pi = nk / len(x)
        if np.max(np.abs(mu_new - mu)) < 1e-10 * (1 + np.max(np.abs(mu))):
            mu = mu_new
            break
        mu = mu_new
    order = np.argsort(mu)
    mu, sd, pi = mu[order], sd[order], pi[order]
    return list(mu) + list(sd) + list(pi[:-1])


def _fit_one(x, key, alpha=0.05):
    fam = {f[0]: f for f in _families(x)}
    if key not in fam:
        raise KeyError(f'no distribution {key!r}')
    k, label, names, start, logpdf, pdf, cdf, ok = fam[key]
    if not ok:
        return {'dist': key, 'label': label, 'error': {
            'lognormal': 'needs every value above zero', 'weibull': 'needs every value above zero', 'exponential': 'needs every value above zero',
            'gamma': 'needs every value above zero', 'beta': 'needs every value strictly between 0 and 1',
            'poisson': 'needs whole non-negative numbers', 'negbin': 'needs whole non-negative numbers',
            'normal2': 'needs at least 12 values', 'normal3': 'needs at least 18 values', 'johnsonsb': 'needs at least 8 values'}.get(key, 'not applicable')}
    n = len(x)
    p0 = np.asarray(start(x), dtype=float)
    model = _Fit(x, logpdf, names)
    try:
        res = model.fit(start_params=p0, method='nm', maxiter=4000, disp=0)
        res = model.fit(start_params=res.params, method='bfgs', maxiter=200, disp=0)
        est = np.asarray(res.params, dtype=float)
        try:
            se = np.asarray(res.bse, dtype=float)
        except Exception:
            se = np.full(len(est), np.nan)
        llf = float(model.loglike(est))
    except Exception:
        est, se, llf = p0, np.full(len(p0), np.nan), float(model.loglike(p0))
    if key == 'normal':   # JMP reports the sample standard deviation for σ
        est = np.array([np.mean(x), np.std(x, ddof=1)])
        se = np.array([est[1] / math.sqrt(n), est[1] / math.sqrt(2 * (n - 1))])
        llf = float(np.sum(stats.norm.logpdf(x, est[0], est[1])))
    z = stats.norm.ppf(1 - alpha / 2)
    params = [{'name': nm, 'estimate': float(e), 'se': float(s), 'lower': float(e - z * s), 'upper': float(e + z * s)} for nm, e, s in zip(names, est, se)]
    kp = len(est)
    aic = -2 * llf + 2 * kp
    aicc = aic + (2 * kp * (kp + 1) / (n - kp - 1) if n - kp - 1 > 0 else float('nan'))
    bic = -2 * llf + kp * math.log(n)
    out = {'dist': key, 'label': label, 'params': params, 'loglik': llf, 'aic': aic, 'aicc': aicc, 'bic': bic, 'n': n, 'k': kp}
    # Goodness of fit: KS with estimated parameters (approximate), plus the
    # exact normal tests for the normal.
    try:
        d, p = stats.kstest(x, lambda v: cdf(v, est))
        out['gof'] = [{'test': 'Kolmogorov-Smirnov D (parameters estimated: p is approximate)', 'stat': float(d), 'p': float(p)}]
    except Exception:
        out['gof'] = []
    if key == 'normal':
        out['gof'] = _normality(x) + out['gof'][1:]
    lo, hi = float(np.min(x)), float(np.max(x))
    pad = 0.08 * (hi - lo if hi > lo else abs(hi) + 1)
    if pdf is not None:
        a = lo - pad
        if key in ('lognormal', 'weibull', 'exponential', 'gamma'):
            a = max(a, 1e-9)
        if key == 'beta':
            a, hi2 = 1e-6, 1 - 1e-6
        else:
            hi2 = hi + pad
        g = np.linspace(a, hi2, 200)
        out['curve'] = {'x': g.tolist(), 'pdf': pdf(g, est).tolist()}
    else:
        ks = np.arange(int(lo), int(hi) + 1)
        pmf = np.exp(logpdf(ks.astype(float), est))
        out['curve'] = {'x': ks.tolist(), 'pmf': pmf.tolist(), 'discrete': True}
    if key.startswith('normal') and key != 'normal':
        out['note'] = 'Estimates by EM, then maximum likelihood; the proportions of the components sum to one (the last is one minus the others).'
    if key == 't' and est[2] > 0.95 * _T_DF_MAX:
        out['note'] = f'ν is at its bound ({_T_DF_MAX:g}): the tails are no heavier than a normal distribution\'s, and the normal fit says the same with one parameter less.'
    return out


def _kde(x):
    kde = stats.gaussian_kde(x)
    lo, hi = float(np.min(x)), float(np.max(x))
    bw = float(kde.factor * np.std(x, ddof=1))
    pad = 3 * bw   # the kernels' tails, so that the curve holds its whole area
    g = np.linspace(lo - pad, hi + pad, 300)
    return {'dist': 'kde', 'label': 'Smooth Curve', 'params': [], 'bandwidth': bw, 'n': len(x),
            'loglik': float(np.sum(np.log(kde(x)))), 'aicc': None, 'bic': None, 'gof': [],
            'curve': {'x': g.tolist(), 'pdf': kde(g).tolist()},
            'note': f"A Gaussian kernel density estimate (scipy gaussian_kde, Scott's bandwidth: {bw:.4g}); JMP's Smooth Curve chooses its own bandwidth."}


@api('distribution.fit')
def fit(table, column, rows=None, dist='normal', alpha=0.05, table_name='data'):
    x, _, _ = _values(table, column, rows)
    if len(x) < 3:
        return {'error': 'fewer than three values'}
    head = [code_head(table_name, ['from scipy import stats', 'from statsmodels.base.model import GenericLikelihoodModel']),
            f'x = df[{json.dumps(column)}].dropna().to_numpy()']
    if dist == 'kde':
        out = _kde(x)
        out['code'] = '\n'.join(head + ['kde = stats.gaussian_kde(x)   # Scott\'s bandwidth', 'print(kde.factor * x.std(ddof=1))'])
        return out
    out = _fit_one(x, dist, alpha)
    scipy_name = {'normal': 'norm', 'lognormal': 'lognorm', 'weibull': 'weibull_min', 'exponential': 'expon', 'gamma': 'gamma',
                  'beta': 'beta', 'logistic': 'logistic', 'cauchy': 'cauchy', 't': 't', 'johnsonsu': 'johnsonsu', 'johnsonsb': 'johnsonsb'}.get(dist)
    if scipy_name:
        line = f'print(stats.{scipy_name}.fit(x{", floc=0" if dist in ("lognormal", "weibull", "exponential", "gamma") else ""}))'
    elif dist == 'poisson':
        line = 'print(x.mean())   # the Poisson MLE of λ'
        if 'error' not in out:
            from statsmodels.stats.rates import confint_poisson
            lo, hi = confint_poisson(float(np.sum(x)), float(len(x)), method='exact-c', alpha=alpha)
            out['exact'] = {'lower': float(lo), 'upper': float(hi), 'method': 'exact (Garwood)'}
            line += f'\nfrom statsmodels.stats.rates import confint_poisson; print(confint_poisson(x.sum(), len(x), method="exact-c", alpha={alpha!r}))   # the exact interval of λ'
    elif dist == 'negbin':
        line = '# λ, σ: maximise stats.nbinom.logpmf(x, λ/(σ-1), 1/σ).sum() over λ > 0, σ > 1'
    else:
        line = f'# a normal mixture of {dist[-1]}: EM from quantile starts, then maximise the mixture log likelihood'
    out['code'] = '\n'.join(head + [line, '# standard errors: subclass GenericLikelihoodModel with loglike = the logpdf summed, then .fit().bse'])
    return out


@api('distribution.fit_all')
def fit_all(table, column, rows=None, alpha=0.05):
    x, _, _ = _values(table, column, rows)
    if len(x) < 3:
        return {'error': 'fewer than three values'}
    fits = []
    for key, *_rest in _families(x):
        r = _fit_one(x, key, alpha)
        if 'error' not in r:
            fits.append({'dist': key, 'label': r['label'], 'k': r['k'], 'loglik': r['loglik'], 'aicc': r['aicc'], 'bic': r['bic']})
    fits.sort(key=lambda r: (np.inf if r['aicc'] is None or not np.isfinite(r['aicc']) else r['aicc']))
    best = fits[0]['aicc'] if fits else None
    for r in fits:
        r['delta'] = (r['aicc'] - best) if best is not None and np.isfinite(r['aicc']) else None
        r['weight'] = None
    tot = sum(math.exp(-0.5 * r['delta']) for r in fits if r['delta'] is not None)
    for r in fits:
        if r['delta'] is not None and tot > 0:
            r['weight'] = math.exp(-0.5 * r['delta']) / tot
    return {'fits': fits, 'n': len(x)}


@api('distribution.capability')
def capability(table, column, rows=None, lsl=None, usl=None, target=None, alpha=0.05):
    x, _, _ = _values(table, column, rows)
    n = len(x)
    if n < 3:
        return {'error': 'fewer than three values'}
    if lsl is None and usl is None:
        return {'error': 'give at least one specification limit'}
    mean = float(np.mean(x))
    s_overall = float(np.std(x, ddof=1))
    mr = np.abs(np.diff(x))
    s_within = float(np.mean(mr) / 1.128) if len(mr) else float('nan')   # moving range / d2(2)
    out = {'n': n, 'mean': mean, 'lsl': lsl, 'usl': usl, 'target': target, 'sigma': {}}
    for key, s in (('within', s_within), ('overall', s_overall)):
        r = {'sigma': s}
        if lsl is not None and usl is not None:
            r['cp'] = (usl - lsl) / (6 * s)
        if lsl is not None:
            r['cpl'] = (mean - lsl) / (3 * s)
        if usl is not None:
            r['cpu'] = (usl - mean) / (3 * s)
        r['cpk'] = min(v for k, v in r.items() if k in ('cpl', 'cpu'))
        if target is not None and lsl is not None and usl is not None:
            r['cpm'] = (usl - lsl) / (6 * math.sqrt(s * s + (mean - target) ** 2))
        # Expected fraction outside, from a normal with this sigma
        below = stats.norm.cdf((lsl - mean) / s) if lsl is not None else 0.0
        above = stats.norm.sf((usl - mean) / s) if usl is not None else 0.0
        r['expected'] = {'below': float(below), 'above': float(above), 'total': float(below + above)}
        # Confidence interval of Cpk (Bissell) and Cp (chi-square)
        z = stats.norm.ppf(1 - alpha / 2)
        cpk = r['cpk']
        se = math.sqrt(1 / (9 * n) + cpk * cpk / (2 * (n - 1)))
        r['cpk_ci'] = [cpk - z * se, cpk + z * se]
        if 'cp' in r:
            r['cp_ci'] = [r['cp'] * math.sqrt(stats.chi2.ppf(alpha / 2, n - 1) / (n - 1)), r['cp'] * math.sqrt(stats.chi2.ppf(1 - alpha / 2, n - 1) / (n - 1))]
        out['sigma'][key] = r
    obs_below = float(np.mean(x < lsl)) if lsl is not None else 0.0
    obs_above = float(np.mean(x > usl)) if usl is not None else 0.0
    out['observed'] = {'below': obs_below, 'above': obs_above, 'total': obs_below + obs_above}
    return out


# ---- categorical columns --------------------------------------------------

# Confidence Interval Method for the level probabilities: statsmodels'
# proportion_confint names, and what the report calls them
CI_METHODS = {'wilson': 'Wilson score', 'agresti_coull': 'Agresti-Coull', 'jeffreys': 'Jeffreys', 'beta': 'Clopper-Pearson (exact)', 'normal': 'Wald'}


@api('distribution.categorical')
def categorical(table, column, rows=None, weight=None, freq=None, alpha=0.05, ci_method='wilson', table_name='data'):
    """Frequencies of an ordinal or nominal column, and a confidence
    interval for each level's probability (statsmodels proportion_confint:
    Wilson's score interval, JMP's, by default; Agresti-Coull, Jeffreys,
    Clopper-Pearson or Wald)."""
    if ci_method not in CI_METHODS:
        return {'error': f'unknown interval method {ci_method!r}'}
    s = data.series(table, column, rows)
    df = pd.DataFrame({column: s})
    if weight or freq:
        df, w = data.weights(df.dropna(), table, weight, freq)
    else:
        df = df.dropna()
        w = np.ones(len(df))
    levels = list(s.cat.categories) if hasattr(s, 'cat') else sorted(df[column].unique())
    counts = pd.Series(w, index=df.index).groupby(df[column], observed=False).sum().reindex(levels, fill_value=0)
    total = float(counts.sum())
    rows_out = []
    cum = 0.0
    for lv, c in counts.items():
        p = c / total if total else float('nan')
        cum += p
        lo, hi = proportion_confint(c, total, alpha=alpha, method=ci_method) if total else (float('nan'), float('nan'))
        rows_out.append({'level': lv, 'count': float(c), 'prob': p, 'se': math.sqrt(p * (1 - p) / total) if total else None,
                         'cum': cum, 'lower': float(lo), 'upper': float(hi)})
    if weight or freq:
        wexpr = ' * '.join(f'df[{json.dumps(v)}]' for v in (weight, freq) if v)
        count_line = f'counts = ({wexpr}).groupby(df[{json.dumps(column)}]).sum()'
    else:
        count_line = f'counts = df[{json.dumps(column)}].value_counts().sort_index()'
    return {'column': column, 'levels': rows_out, 'n': total, 'n_levels': len(levels), 'n_missing': int(s.isna().sum()), 'alpha': alpha,
            'ci_method': ci_method, 'ci_label': CI_METHODS[ci_method],
            'code': '\n'.join([code_head(table_name, ['from statsmodels.stats.proportion import proportion_confint']),
                               count_line,
                               f'print(proportion_confint(counts, counts.sum(), alpha={alpha}, method={ci_method!r}))   # {CI_METHODS[ci_method]}'])}


# Test Rate: statsmodels' methods for one Poisson rate
RATE_TESTS_1 = {'exact-c': 'exact (central)', 'midp-c': 'mid-p (central)', 'score': 'score', 'wald': 'Wald', 'waldccv': 'Wald, 0.5 added to the variance',
                'sqrt-a': 'Anscombe square root', 'sqrt-v': 'Vandenbroucke square root', 'sqrt': 'square root'}
RATE_CIS_1 = {'exact-c': 'exact (Garwood)', 'midp-c': 'mid-p', 'score': 'score', 'jeff': 'Jeffreys', 'wald': 'Wald', 'waldccv': 'Wald, 0.5 added to the variance',
              'sqrt-a': 'Anscombe square root'}


@api('distribution.test_rate')
def test_rate(table, column, rows=None, rate=1.0, exposure=None, method='exact-c', ci_method='exact-c', weight=None, freq=None, alpha=0.05,
              table_name='data'):
    """Test Rate: the column counts events, each row a unit observed for its
    exposure (1 without one). The rate is the total count over the total
    exposure; its test against a hypothesized rate is statsmodels'
    test_poisson (two-sided and each one-sided) and its interval
    confint_poisson. Freq counts a row as that many units."""
    from statsmodels.stats.rates import confint_poisson, test_poisson
    if method not in RATE_TESTS_1:
        return {'error': f'unknown test method {method!r}'}
    if ci_method not in RATE_CIS_1:
        return {'error': f'unknown interval method {ci_method!r}'}
    if rate is None or not rate > 0:
        return {'error': 'the hypothesized rate must be positive'}
    if exposure and exposure == column:
        return {'error': 'the exposure must be another column'}
    df = data.frame(table, [column, exposure, freq], rows, as_category=False)
    y = df[column].to_numpy(float)
    e = df[exposure].to_numpy(float) if exposure else np.ones(len(df))
    f = df[freq].to_numpy(float) if freq else np.ones(len(df))
    ok = np.isfinite(y) & np.isfinite(e) & (e > 0) & np.isfinite(f) & (f > 0)
    notes = []
    if exposure and np.sum(np.isfinite(y) & ~(np.isfinite(e) & (e > 0))):
        notes.append(f'{int(np.sum(np.isfinite(y) & ~(np.isfinite(e) & (e > 0))))} row(s) without a positive exposure are left out.')
    y, e, f = y[ok], e[ok], f[ok]
    if not len(y):
        return {'error': 'no rows with a count' + (' and a positive exposure' if exposure else '')}
    if not (np.all(y >= 0) and np.all(np.abs(y - np.rint(y)) < 1e-9)):
        return {'error': 'Test Rate needs counts: whole numbers of zero or more'}
    count, expo, units = float(np.sum(f * y)), float(np.sum(f * e)), float(np.sum(f))
    if method in ('exact-c', 'midp-c') and abs(count - round(count)) > 1e-9:
        return {'error': 'the exact tests need a whole total count: Freq must hold whole numbers'}
    tests = {}
    for alt in ('two-sided', 'larger', 'smaller'):
        with np.errstate(divide='ignore', invalid='ignore'):
            r = test_poisson(count, expo, value=float(rate), method=method, alternative=alt)
        tests[alt] = r
    with np.errstate(divide='ignore', invalid='ignore'):
        lo, hi = confint_poisson(count, expo, method=ci_method, alpha=alpha)
    lo, hi = float(lo), float(hi)
    if ci_method == 'midp-c' and count == 0:
        lo = 0.0   # statsmodels' root finding returns the upper limit twice when there are no events
        notes.append('With no events the lower mid-p limit is 0 (statsmodels\' inversion returns the upper limit twice).')
    if ci_method == 'wald' and count == 0:
        notes.append('With no events the Wald interval has no width: use the exact or score interval.')
    est = count / expo
    mu = est * e
    with np.errstate(divide='ignore', invalid='ignore'):
        disp = float(np.sum(f * (y - mu) ** 2 / mu) / (units - 1)) if est > 0 and units > 1 else None
    if disp is not None and disp > 1.5:
        notes.append(f'The Pearson χ²/DF of the counts about the rate is {disp:.3g}: they vary more than a Poisson allows, and the test treats the evidence as stronger than it is.')
    if weight:
        notes.append('Weight is not used by the rate test.')
    out = {'column': column, 'rate0': float(rate), 'count': count, 'exposure': expo, 'units': units, 'rate': est, 'lower': lo, 'upper': hi,
           'method': method, 'method_label': RATE_TESTS_1[method], 'ci_method': ci_method, 'ci_label': RATE_CIS_1[ci_method], 'alpha': alpha,
           'statistic': _num(tests['two-sided'].statistic), 'p_two': _num(tests['two-sided'].pvalue), 'p_greater': _num(tests['larger'].pvalue),
           'p_less': _num(tests['smaller'].pvalue), 'dispersion': disp, 'has_exposure': bool(exposure), 'notes': notes}
    c = [code_head(table_name, ['from statsmodels.stats.rates import test_poisson, confint_poisson']),
         f'd = df[[{", ".join(json.dumps(v) for v in (column, exposure, freq) if v)}]].dropna()']
    if exposure:
        c.append(f'd = d[d[{json.dumps(exposure)}] > 0]')
    fw = f'd[{json.dumps(freq)}]' if freq else '1'
    ex = f'd[{json.dumps(exposure)}]' if exposure else '1'
    if exposure or freq:
        c.append(f'count, exposure = (d[{json.dumps(column)}] * {fw}).sum(), ({ex} * {fw}).sum()')
    else:
        c.append(f'count, exposure = d[{json.dumps(column)}].sum(), len(d)   # without an exposure each row is one unit')
    c.append(f'print(count / exposure, confint_poisson(count, exposure, method={ci_method!r}, alpha={alpha!r}))   # the rate and its {RATE_CIS_1[ci_method]} interval')
    c.append(f'for alt in ["two-sided", "larger", "smaller"]: print(alt, test_poisson(count, exposure, value={float(rate)!r}, method={method!r}, alternative=alt).pvalue)')
    out['code'] = '\n'.join(c)
    return out


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


@api('distribution.test_probs')
def test_probs(table, column, rows=None, probs=None, weight=None, freq=None):
    res = categorical(table, column, rows, weight, freq)
    obs = np.array([r['count'] for r in res['levels']], dtype=float)
    labels = [r['level'] for r in res['levels']]
    p = np.array([float((probs or {}).get(str(l), (probs or {}).get(l, 0)) or 0) for l in labels], dtype=float)
    if p.sum() <= 0:
        return {'error': 'give hypothesised probabilities'}
    p = p / p.sum()
    keep = p > 0
    exp = obs.sum() * p
    chi = stats.chisquare(obs[keep], exp[keep])
    g = stats.power_divergence(obs[keep], exp[keep], lambda_='log-likelihood')
    return {'levels': [{'level': l, 'hypothesized': float(pp), 'observed': float(o) / obs.sum(), 'count': float(o), 'expected': float(e)} for l, pp, o, e in zip(labels, p, obs, exp)],
            'tests': [{'test': 'Likelihood Ratio', 'stat': float(g.statistic), 'df': int(keep.sum() - 1), 'p': float(g.pvalue)},
                      {'test': 'Pearson', 'stat': float(chi.statistic), 'df': int(keep.sum() - 1), 'p': float(chi.pvalue)}],
            'min_expected': float(exp[keep].min())}
