"""DOE > Sample Size Explorers > Sample Size and Power.

JMP's Sample Size and Power: pick a situation, give all but one of the
effect (a difference, proportions, a variance), the sample size and the
power, and the missing one is solved for; with only the effect or only the
sample size given, the power curve is the answer.

  One Sample Mean        statsmodels TTestPower (ttest_power with the error
                         degrees of freedom reduced by extra parameters)
  Two Sample Means       statsmodels TTestIndPower; the sample size is the
                         total of both groups, as in JMP
  k Sample Means         statsmodels FTestAnovaPower, Cohen's f from the means
  One Sample Proportion  statsmodels NormalIndPower (one sample: ratio 0) on
                         Cohen's h (proportion_effectsize), and the exact
                         binomial power from binom_test_reject_interval
  Two Sample Proportions statsmodels power_proportions_2indep (the pooled
                         z test)
  One Sample Variance    the chi-square test of a variance, exactly (scipy)
  Counts per Unit        the test of a Poisson rate: normal approximation
                         and the exact Poisson power (scipy)
  Sigma Quality Level    defects per opportunities and the sigma level with
                         the customary 1.5 sigma shift
"""
import math

import numpy as np
from scipy import optimize, stats
from statsmodels.stats.power import FTestAnovaPower, NormalIndPower, TTestIndPower, ttest_power
from statsmodels.stats.proportion import binom_test_reject_interval, power_proportions_2indep, proportion_effectsize

from .registry import api

SITUATIONS = {
    'one_mean': 'One Sample Mean', 'two_means': 'Two Sample Means', 'k_means': 'k Sample Means',
    'one_prop': 'One Sample Proportion', 'two_props': 'Two Sample Proportions', 'one_var': 'One Sample Variance',
    'poisson': 'Counts per Unit', 'sigma': 'Sigma Quality Level',
}

HEAD = 'import numpy as np\nfrom scipy import stats, optimize'


def _given(v):
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _alt(sides, sign=1):
    if int(sides or 2) == 2:
        return 'two-sided'
    return 'larger' if sign >= 0 else 'smaller'


def _solve_increasing(f, target, lo, hi, grow=True):
    """The x in [lo, hi] (hi doubled while needed) where the increasing f(x)
    reaches target."""
    flo = f(lo) - target
    if flo >= 0:
        return lo
    fhi = f(hi) - target
    tries = 0
    while fhi < 0 and grow and tries < 40:
        lo, hi = hi, hi * 2
        fhi = f(hi) - target
        tries += 1
    if fhi < 0:
        return float('nan')
    return optimize.brentq(lambda x: f(x) - target, lo, hi, xtol=1e-10)


def _safe(p, ncp):
    """A power from scipy's noncentral distributions, which return NaN far
    out in the tail: there the power is 1 (or the level, at no effect)."""
    if p is None or not np.isfinite(p):
        return 1.0 if abs(ncp) > 5 else float('nan')
    return float(min(max(p, 0.0), 1.0))


def _ceil_n(n_frac, power_at, target):
    """The smallest whole sample size at or above n_frac with the power."""
    if not np.isfinite(n_frac):
        return None, None
    n = int(math.ceil(n_frac - 1e-9))
    for _ in range(10000):
        pw = power_at(n)
        if pw >= target - 1e-12:
            return n, pw
        n += 1
    return None, None


def _grid(lo, hi, m=60, integer=False):
    if integer:
        lo, hi = int(max(1, math.floor(lo))), int(max(math.ceil(hi), math.floor(lo) + 2))
        step = max(1, (hi - lo) // m)
        return np.arange(lo, hi + 1, step, dtype=float)
    return np.linspace(lo, hi, m)


# ---- means ------------------------------------------------------------------

def _one_mean(alpha, sides, sd=None, diff=None, n=None, power=None, extra=0, **_):
    extra = int(extra or 0)
    alt = _alt(sides, 1 if (diff or 0) >= 0 else -1)

    def pw(d, nn):
        es = d / sd
        dfree = nn - 1 - extra
        if dfree < 1:
            return float('nan')
        a = alt if not (alt == 'larger' and es < 0) else 'smaller'
        return _safe(float(ttest_power(es, nobs=nn, alpha=alpha, df=dfree, alternative=a)), es * math.sqrt(nn))
    out = _solve_three(pw, diff, n, power, n_min=2 + extra, diff_name='Difference to detect', n_name='Sample Size',
                       diff_hi=6 * sd, integer=True)
    out['code'] = '\n'.join([
        'from statsmodels.stats.power import TTestPower, ttest_power',
        f'alpha, sd = {alpha!r}, {sd!r}',
        (f'print(ttest_power({out["values"]["diff"]!r} / sd, nobs={out["values"]["n"]!r}, alpha=alpha, df={out["values"]["n"]!r} - 1 - {extra}, alternative={alt!r}))'
         if extra else f'print(TTestPower().power(effect_size={out["values"]["diff"]!r} / sd, nobs={out["values"]["n"]!r}, alpha=alpha, alternative={alt!r}))'),
        f'print(TTestPower().solve_power(effect_size={out["values"]["diff"]!r} / sd, alpha=alpha, power={out["values"]["power"]!r}, alternative={alt!r}))   # the sample size',
    ])
    out['notes'].append(f'A one-sample t test ({"two-sided" if alt == "two-sided" else "one-sided"}) of a mean shift of the difference, in units of the standard deviation.'
                        + (f' The error degrees of freedom are n − 1 − {extra} (extra parameters).' if extra else ''))
    return out


def _two_means(alpha, sides, sd=None, diff=None, n=None, power=None, extra=0, ratio=1.0, **_):
    extra = int(extra or 0)
    ratio = float(ratio or 1.0)
    alt = _alt(sides, 1 if (diff or 0) >= 0 else -1)

    def pw(d, total):
        n1 = total / (1 + ratio)
        dfree = total - 2 - extra
        if n1 < 1 or dfree < 1:
            return float('nan')
        a = alt if not (alt == 'larger' and d < 0) else 'smaller'
        es = d / sd
        return _safe(float(TTestIndPower().power(effect_size=es, nobs1=n1, alpha=alpha, ratio=ratio, df=dfree, alternative=a)), es * math.sqrt(n1 * ratio / (1 + ratio)))
    out = _solve_three(pw, diff, n, power, n_min=3 + extra, diff_name='Difference to detect', n_name='Sample Size (total)',
                       diff_hi=6 * sd, integer=True)
    v = out['values']
    if _given(v.get('n')):
        out['rows'].append(['Sample size of each group', f'{v["n"] / (1 + ratio):.6g} and {v["n"] * ratio / (1 + ratio):.6g}', 'text'])
    out['code'] = '\n'.join([
        'from statsmodels.stats.power import TTestIndPower',
        f'alpha, sd, ratio = {alpha!r}, {sd!r}, {ratio!r}   # ratio: the second group\'s size over the first\'s',
        f'total = {v["n"]!r}; n1 = total / (1 + ratio)',
        f'print(TTestIndPower().power(effect_size={v["diff"]!r} / sd, nobs1=n1, alpha=alpha, ratio=ratio, df=total - 2 - {extra}, alternative={alt!r}))',
        f'print((1 + ratio) * TTestIndPower().solve_power(effect_size={v["diff"]!r} / sd, alpha=alpha, power={v["power"]!r}, ratio=ratio, alternative={alt!r}))   # total sample size',
    ])
    out['notes'].append('A two-sample t test with a common standard deviation. The sample size is the total of both groups, as in JMP.'
                        + (f' The error degrees of freedom are n − 2 − {extra}.' if extra else ''))
    return out


def _k_means(alpha, sd=None, means=None, n=None, power=None, extra=0, **_):
    extra = int(extra or 0)
    mu = np.asarray([float(m) for m in (means or []) if _given(m)], dtype=float)
    k = len(mu)
    if k < 2:
        return {'error': 'give two or more means'}
    f = float(np.sqrt(np.mean((mu - mu.mean()) ** 2)) / sd)

    def pw_n(total):
        dfd = total - k - extra
        if dfd < 1:
            return float('nan')
        if not extra:
            return _safe(float(FTestAnovaPower().power(effect_size=f, nobs=total, alpha=alpha, k_groups=k)), f * math.sqrt(total))
        crit = stats.f.ppf(1 - alpha, k - 1, dfd)
        return _safe(float(stats.ncf.sf(crit, k - 1, dfd, total * f * f)), f * math.sqrt(total))
    values = {'n': n, 'power': power}
    rows = [['Effect size f (Cohen)', f], ['Number of groups', k, 'int']]
    notes = ['A one-way ANOVA F test; the effect size is Cohen\'s f = √(Σ(μᵢ − μ̄)²/k)/σ and the noncentrality n·f². The sample size is the total over the groups.']
    solved = None
    if _given(n) and not _given(power):
        values['power'] = pw_n(float(n))
        solved = 'power'
    elif _given(power) and not _given(n):
        nf = _solve_increasing(pw_n, float(power), k + extra + 1.0, 50.0 * k)
        values['n'] = nf
        solved = 'n'
        ni, pi = _ceil_n(nf, pw_n, float(power))
        if ni is not None:
            rows.append([f'Whole sample size (actual power {pi:.4f})', ni, 'int'])
    elif _given(n) and _given(power):
        values['power'] = pw_n(float(n))
        solved = 'power'
        notes.append('Both the sample size and the power were given: the power is recomputed from the sample size.')
    nn = values['n'] if _given(values['n']) else 10 * k
    xs = _grid(k + extra + 1, max(3 * nn, 4 * k), integer=True)
    curves = {'n': {'x': xs, 'y': [pw_n(x) for x in xs], 'label': 'Sample Size (total)'}}
    return {'values': values, 'solved': solved, 'rows': rows, 'notes': notes, 'curves': curves,
            'code': '\n'.join(['from statsmodels.stats.power import FTestAnovaPower', f'means, sd = np.array({mu.tolist()!r}), {sd!r}',
                               'f = np.sqrt(np.mean((means - means.mean()) ** 2)) / sd   # Cohen\'s f',
                               f'print(FTestAnovaPower().power(effect_size=f, nobs={values["n"]!r}, alpha={alpha!r}, k_groups=len(means)))',
                               f'print(FTestAnovaPower().solve_power(effect_size=f, alpha={alpha!r}, power={values["power"]!r}, k_groups=len(means)))'])}


def _solve_three(pw, diff, n, power, n_min, diff_name, n_name, diff_hi, integer=True):
    """Given two of the difference, the sample size and the power, the third;
    power(d, n) increases in |d| and n."""
    values = {'diff': diff, 'n': n, 'power': power}
    rows, notes = [], []
    solved = None
    if _given(diff) and _given(n):
        values['power'] = pw(float(diff), float(n))
        solved = 'power'
        if _given(power):
            notes.append('All three were given: the power is recomputed from the difference and the sample size.')
    elif _given(diff) and _given(power):
        if float(power) <= 0 or float(power) >= 1:
            return {'error': 'the power must lie between 0 and 1'}
        nf = _solve_increasing(lambda x: pw(float(diff), x), float(power), float(n_min), 100.0)
        values['n'] = nf
        solved = 'n'
        ni, pi = _ceil_n(nf, lambda x: pw(float(diff), float(x)), float(power))
        if ni is not None:
            rows.append([f'Whole sample size (actual power {pi:.4f})', ni, 'int'])
    elif _given(n) and _given(power):
        if float(power) <= 0 or float(power) >= 1:
            return {'error': 'the power must lie between 0 and 1'}
        sign = 1.0

        def f(d):
            return pw(sign * d, float(n))
        d = _solve_increasing(f, float(power), 1e-9, diff_hi / 6)
        values['diff'] = d
        solved = 'diff'
    curves = {}
    if _given(values['diff']):
        d0 = float(values['diff'])
        nn = values['n'] if _given(values['n']) else None
        hi = max(3 * nn, 20) if nn else 100
        xs = _grid(n_min, hi, integer=integer)
        curves['n'] = {'x': xs, 'y': [pw(d0, float(x)) for x in xs], 'label': n_name, 'at': d0}
    if _given(values['n']):
        n0 = float(values['n'])
        dd = abs(float(values['diff'])) if _given(values['diff']) else diff_hi / 3
        xs = np.linspace(0, max(2.5 * dd, 1e-9), 60)
        sgn = -1.0 if _given(values['diff']) and float(values['diff']) < 0 else 1.0
        curves['diff'] = {'x': sgn * xs, 'y': [pw(sgn * x, n0) for x in xs], 'label': diff_name, 'at': n0}
    return {'values': values, 'solved': solved, 'rows': rows, 'notes': notes, 'curves': curves}


# ---- proportions ---------------------------------------------------------------

def _one_prop(alpha, sides, p0=None, p1=None, n=None, power=None, **_):
    if not (_given(p0) and 0 < float(p0) < 1):
        return {'error': 'give the null proportion p0 between 0 and 1'}
    p0 = float(p0)
    alt_sign = 1 if (not _given(p1) or float(p1) >= p0) else -1
    alt = _alt(sides, alt_sign)

    def approx(pp, nn):
        h = proportion_effectsize(pp, p0)
        a = alt if alt == 'two-sided' else ('larger' if h >= 0 else 'smaller')
        return float(NormalIndPower().power(effect_size=h, nobs1=nn, alpha=alpha, ratio=0, alternative=a))

    def exact(pp, nn):
        nn = int(round(nn))
        if nn < 1:
            return float('nan')
        a = alt if alt == 'two-sided' else ('larger' if pp >= p0 else 'smaller')
        lo, hi = binom_test_reject_interval(p0, nn, alpha=alpha, alternative=a)
        return float(stats.binom.cdf(lo, nn, pp) + stats.binom.sf(hi - 1, nn, pp))
    values = {'p1': p1, 'n': n, 'power': power}
    rows, notes = [], ['Power by the normal approximation on Cohen\'s h = 2·asin√p − 2·asin√p₀ (statsmodels NormalIndPower, one sample) and exactly from the binomial test\'s rejection region (binom_test_reject_interval). The exact power zigzags with n.']
    solved = None
    if _given(p1) and _given(n):
        values['power'] = approx(float(p1), float(n))
        solved = 'power'
        rows.append(['Power (exact binomial)', exact(float(p1), float(n))])
    elif _given(p1) and _given(power):
        h = proportion_effectsize(float(p1), p0)
        a = alt if alt == 'two-sided' else ('larger' if h >= 0 else 'smaller')
        nf = float(NormalIndPower().solve_power(effect_size=h, alpha=alpha, power=float(power), ratio=0, alternative=a))
        values['n'] = nf
        solved = 'n'
        ni, pi = _ceil_n(nf, lambda x: approx(float(p1), x), float(power))
        if ni is not None:
            rows.append([f'Whole sample size (actual power {pi:.4f})', ni, 'int'])
        ne = None
        for m in range(1, int(max(10, 6 * nf)) + 1):
            if exact(float(p1), m) >= float(power):
                ne = m
                break
        rows.append(['Smallest n with exact power ≥ target', ne, 'int'])
        if ne is not None:
            # the smallest n from which every larger n also has the power
            nx = ne
            for m in range(ne, int(max(10, 6 * nf)) + 40):
                if exact(float(p1), m) < float(power):
                    nx = m + 1
            rows.append(['Smallest n with exact power ≥ target from there on', nx, 'int'])
    elif _given(n) and _given(power):
        f = lambda pp: approx(pp, float(n))
        if alt_sign >= 0:
            pp = _solve_increasing(f, float(power), p0 + 1e-9, 1 - 1e-9, grow=False)
        else:
            pp = _solve_increasing(lambda q: approx(p0 - q, float(n)), float(power), 1e-9, p0 - 1e-9, grow=False)
            pp = p0 - pp if np.isfinite(pp) else pp
        values['p1'] = pp
        solved = 'p1'
    curves = {}
    if _given(values['p1']):
        pp = float(values['p1'])
        nn = values['n'] if _given(values['n']) else 50
        xs = _grid(2, max(3 * nn, 30), integer=True)
        curves['n'] = {'x': xs, 'y': [approx(pp, x) for x in xs], 'y_exact': [exact(pp, x) for x in xs], 'label': 'Sample Size', 'at': pp}
    if _given(values['n']):
        nn = float(values['n'])
        xs = np.linspace(0.001, 0.999, 120)
        curves['diff'] = {'x': xs, 'y': [approx(x, nn) for x in xs], 'y_exact': [exact(x, nn) for x in xs], 'label': 'Proportion p', 'at': nn}
    code = '\n'.join(['from statsmodels.stats.power import NormalIndPower', 'from statsmodels.stats.proportion import proportion_effectsize, binom_test_reject_interval',
                      f'p0, p1, n, alpha = {p0!r}, {values["p1"]!r}, {values["n"]!r}, {alpha!r}',
                      f'h = proportion_effectsize(p1, p0); print(NormalIndPower().power(effect_size=h, nobs1=n, alpha=alpha, ratio=0, alternative={alt!r}))',
                      f'lo, hi = binom_test_reject_interval(p0, int(round(n)), alpha=alpha, alternative={alt!r})',
                      'print(stats.binom.cdf(lo, int(round(n)), p1) + stats.binom.sf(hi - 1, int(round(n)), p1))   # exact power'])
    return {'values': values, 'solved': solved, 'rows': rows, 'notes': notes, 'curves': curves, 'code': code}


def _two_props(alpha, sides, p1=None, p2=None, n=None, n2=None, power=None, null_diff=0.0, **_):
    if not (_given(p2) and 0 < float(p2) < 1):
        return {'error': 'give the proportion p2 between 0 and 1'}
    p2 = float(p2)
    nd = float(null_diff or 0.0)
    sign = 1 if (not _given(p1) or float(p1) - p2 >= nd) else -1
    alt = _alt(sides, sign)
    ratio = (float(n2) / float(n)) if (_given(n2) and _given(n) and float(n) > 0) else 1.0

    def pw(pp, nn):
        if not 0 < pp < 1 or nn < 2:
            return float('nan')
        a = alt if alt == 'two-sided' else ('larger' if pp - p2 >= nd else 'smaller')
        return float(power_proportions_2indep(pp - p2, p2, nn, ratio=ratio, alpha=alpha, value=nd, alternative=a, return_results=False))
    values = {'p1': p1, 'n': n, 'n2': n2, 'power': power}
    rows, notes = [], ['The z test of p1 − p2 with the pooled variance under the null (statsmodels power_proportions_2indep). n is the size of the first group; the second is n2, or as large as the first.']
    solved = None
    if _given(p1) and _given(n):
        values['power'] = pw(float(p1), float(n))
        solved = 'power'
    elif _given(p1) and _given(power):
        nf = _solve_increasing(lambda x: pw(float(p1), x), float(power), 2.0, 100.0)
        values['n'] = nf
        solved = 'n'
        ni, pi = _ceil_n(nf, lambda x: pw(float(p1), float(x)), float(power))
        if ni is not None:
            rows.append([f'Whole sample size per group (actual power {pi:.4f})', ni, 'int'])
    elif _given(n) and _given(power):
        if sign >= 0:
            pp = _solve_increasing(lambda q: pw(p2 + nd + q, float(n)), float(power), 1e-9, 1 - p2 - nd - 1e-9, grow=False)
            values['p1'] = p2 + nd + pp if np.isfinite(pp) else pp
        else:
            pp = _solve_increasing(lambda q: pw(p2 + nd - q, float(n)), float(power), 1e-9, p2 + nd - 1e-9, grow=False)
            values['p1'] = p2 + nd - pp if np.isfinite(pp) else pp
        solved = 'p1'
    if _given(values['n']):
        rows.append(['Total sample size', float(values['n']) * (1 + ratio)])
    curves = {}
    if _given(values['p1']):
        pp = float(values['p1'])
        nn = values['n'] if _given(values['n']) else 100
        xs = _grid(2, max(3 * nn, 30), integer=True)
        curves['n'] = {'x': xs, 'y': [pw(pp, x) for x in xs], 'label': 'Sample Size (group 1)', 'at': pp}
    if _given(values['n']):
        nn = float(values['n'])
        xs = np.linspace(0.001, 0.999, 120)
        curves['diff'] = {'x': xs, 'y': [pw(x, nn) for x in xs], 'label': 'Proportion p1', 'at': nn}
    code = '\n'.join(['from statsmodels.stats.proportion import power_proportions_2indep',
                      f'p1, p2, n1, ratio, alpha = {values["p1"]!r}, {p2!r}, {values["n"]!r}, {ratio!r}, {alpha!r}',
                      f'print(power_proportions_2indep(p1 - p2, p2, n1, ratio=ratio, alpha=alpha, value={nd!r}, alternative={alt!r}).power)'])
    return {'values': values, 'solved': solved, 'rows': rows, 'notes': notes, 'curves': curves, 'code': code}


# ---- a variance, a Poisson rate ------------------------------------------------------

def _one_var(alpha, sides, var0=None, dvar=None, n=None, power=None, **_):
    if not (_given(var0) and float(var0) > 0):
        return {'error': 'give the baseline variance'}
    v0 = float(var0)
    two = int(sides or 2) == 2

    def pw(dv, nn):
        v1 = v0 + dv
        if v1 <= 0 or nn < 2:
            return float('nan')
        df_ = nn - 1
        r = v0 / v1
        if two:
            return float(stats.chi2.sf(stats.chi2.ppf(1 - alpha / 2, df_) * r, df_) + stats.chi2.cdf(stats.chi2.ppf(alpha / 2, df_) * r, df_))
        if dv >= 0:
            return float(stats.chi2.sf(stats.chi2.ppf(1 - alpha, df_) * r, df_))
        return float(stats.chi2.cdf(stats.chi2.ppf(alpha, df_) * r, df_))
    values = {'dvar': dvar, 'n': n, 'power': power}
    rows = []
    notes = ['The chi-square test of a variance, (n − 1)s²/σ₀² against χ² with n − 1 degrees of freedom; the power is exact for normal data. The difference is σ₁² − σ₀²; a negative one guards against a smaller variance.']
    solved = None
    if _given(dvar) and _given(n):
        values['power'] = pw(float(dvar), float(n))
        solved = 'power'
    elif _given(dvar) and _given(power):
        nf = _solve_increasing(lambda x: pw(float(dvar), x), float(power), 2.0, 100.0)
        values['n'] = nf
        solved = 'n'
        ni, pi = _ceil_n(nf, lambda x: pw(float(dvar), float(x)), float(power))
        if ni is not None:
            rows.append([f'Whole sample size (actual power {pi:.4f})', ni, 'int'])
    elif _given(n) and _given(power):
        up = _solve_increasing(lambda d: pw(d, float(n)), float(power), 1e-12, 10 * v0)
        values['dvar'] = up
        solved = 'dvar'
        if not two:
            dn = _solve_increasing(lambda d: pw(-d, float(n)), float(power), 1e-12, v0 * (1 - 1e-9), grow=False)
            if np.isfinite(dn):
                rows.append(['Difference to detect, smaller variance', -dn])
    if _given(values['dvar']):
        rows.append(['Alternative variance σ₁²', v0 + float(values['dvar'])])
        rows.append(['Alternative std dev σ₁', math.sqrt(max(v0 + float(values['dvar']), 0))])
    curves = {}
    if _given(values['dvar']):
        dv = float(values['dvar'])
        nn = values['n'] if _given(values['n']) else 30
        xs = _grid(2, max(3 * nn, 30), integer=True)
        curves['n'] = {'x': xs, 'y': [pw(dv, x) for x in xs], 'label': 'Sample Size', 'at': dv}
    if _given(values['n']):
        nn = float(values['n'])
        dd = abs(float(values['dvar'])) if _given(values['dvar']) else v0
        sgn = -1.0 if _given(values['dvar']) and float(values['dvar']) < 0 else 1.0
        top = min(3 * dd, v0 * 0.999) if sgn < 0 else 3 * dd
        xs = np.linspace(0, top, 60)
        curves['diff'] = {'x': sgn * xs, 'y': [pw(sgn * x, nn) for x in xs], 'label': 'Difference in variance', 'at': nn}
    code = '\n'.join([HEAD, f'v0, v1, n, alpha = {v0!r}, {v0!r} + {values["dvar"]!r}, {values["n"]!r}, {alpha!r}',
                      'df = n - 1; r = v0 / v1',
                      ('print(stats.chi2.sf(stats.chi2.ppf(1 - alpha / 2, df) * r, df) + stats.chi2.cdf(stats.chi2.ppf(alpha / 2, df) * r, df))' if two else
                       'print(stats.chi2.sf(stats.chi2.ppf(1 - alpha, df) * r, df) if v1 > v0 else stats.chi2.cdf(stats.chi2.ppf(alpha, df) * r, df))')])
    return {'values': values, 'solved': solved, 'rows': rows, 'notes': notes, 'curves': curves, 'code': code}


def _poisson(alpha, sides, lam0=None, dlam=None, n=None, power=None, **_):
    if not (_given(lam0) and float(lam0) > 0):
        return {'error': 'give the baseline count per unit'}
    l0 = float(lam0)
    two = int(sides or 2) == 2
    za = stats.norm.ppf(1 - alpha / 2) if two else stats.norm.ppf(1 - alpha)

    def approx(d, nn):
        l1 = l0 + d
        if l1 <= 0 or nn <= 0:
            return float('nan')
        # z = (xbar - l0)/sqrt(l0/n); under the alternative xbar ~ N(l1, l1/n)
        s0, s1 = math.sqrt(l0 / nn), math.sqrt(l1 / nn)
        up = stats.norm.sf((l0 + za * s0 - l1) / s1)
        dn = stats.norm.cdf((l0 - za * s0 - l1) / s1)
        if two:
            return float(up + dn)
        return float(up if d >= 0 else dn)

    def exact(d, nn):
        l1 = l0 + d
        mu0, mu1 = nn * l0, nn * l1
        a = alpha / 2 if two else alpha
        hi = int(stats.poisson.isf(a, mu0)) + 1          # reject when X >= hi: P0(X >= hi) <= a
        while hi > 0 and stats.poisson.sf(hi - 2, mu0) <= a:
            hi -= 1
        lo = int(stats.poisson.ppf(a, mu0)) - 1          # reject when X <= lo
        while stats.poisson.cdf(lo + 1, mu0) <= a:
            lo += 1
        p_up = stats.poisson.sf(hi - 1, mu1)
        p_dn = stats.poisson.cdf(lo, mu1) if lo >= 0 else 0.0
        if two:
            return float(p_up + p_dn)
        return float(p_up if d >= 0 else p_dn)
    values = {'dlam': dlam, 'n': n, 'power': power}
    rows, notes = [], ['The test of a Poisson rate per unit: the normal approximation of the total count over n units, and the exact Poisson power from the rejection region of the count. The difference to detect is λ₁ − λ₀.']
    solved = None
    if _given(dlam) and _given(n):
        values['power'] = approx(float(dlam), float(n))
        solved = 'power'
        rows.append(['Power (exact Poisson)', exact(float(dlam), float(n))])
    elif _given(dlam) and _given(power):
        nf = _solve_increasing(lambda x: approx(float(dlam), x), float(power), 1e-6, 100.0)
        values['n'] = nf
        solved = 'n'
        ni, pi = _ceil_n(nf, lambda x: approx(float(dlam), float(x)), float(power))
        if ni is not None:
            rows.append([f'Whole number of units (actual power {pi:.4f})', ni, 'int'])
            ne = None
            for m in range(1, int(max(10, 6 * nf)) + 1):
                if exact(float(dlam), m) >= float(power):
                    ne = m
                    break
            rows.append(['Smallest n with exact power ≥ target', ne, 'int'])
    elif _given(n) and _given(power):
        values['dlam'] = _solve_increasing(lambda d: approx(d, float(n)), float(power), 1e-12, 10 * l0 + 10)
        solved = 'dlam'
    curves = {}
    if _given(values['dlam']):
        d = float(values['dlam'])
        nn = values['n'] if _given(values['n']) else 20
        xs = _grid(1, max(3 * nn, 20), integer=True)
        curves['n'] = {'x': xs, 'y': [approx(d, x) for x in xs], 'y_exact': [exact(d, x) for x in xs], 'label': 'Sample Size (units)', 'at': d}
    if _given(values['n']):
        nn = float(values['n'])
        dd = abs(float(values['dlam'])) if _given(values['dlam']) else l0
        xs = np.linspace(0, 3 * dd, 60)
        curves['diff'] = {'x': xs, 'y': [approx(x, nn) for x in xs], 'label': 'Difference to detect', 'at': nn}
    code = '\n'.join([HEAD, f'l0, l1, n, alpha = {l0!r}, {l0!r} + {values["dlam"]!r}, {values["n"]!r}, {alpha!r}',
                      f'z = stats.norm.ppf(1 - alpha{" / 2" if two else ""}); s0, s1 = np.sqrt(l0 / n), np.sqrt(l1 / n)',
                      'print(stats.norm.sf((l0 + z * s0 - l1) / s1)' + (' + stats.norm.cdf((l0 - z * s0 - l1) / s1))' if two else ')   # normal approximation')])
    return {'values': values, 'solved': solved, 'rows': rows, 'notes': notes, 'curves': curves, 'code': code}


def _sigma(defects=None, opportunities=None, sigma_level=None, **_):
    values = {'defects': defects, 'opportunities': opportunities, 'sigma_level': sigma_level}
    solved = None
    if _given(defects) and _given(opportunities):
        if not 0 <= float(defects) < float(opportunities):
            return {'error': 'the defects must be fewer than the opportunities'}
        values['sigma_level'] = float(stats.norm.ppf(1 - float(defects) / float(opportunities)) + 1.5)
        solved = 'sigma_level'
    elif _given(sigma_level) and _given(opportunities):
        values['defects'] = float(opportunities) * float(stats.norm.sf(float(sigma_level) - 1.5))
        solved = 'defects'
    elif _given(sigma_level) and _given(defects):
        values['opportunities'] = float(defects) / float(stats.norm.sf(float(sigma_level) - 1.5))
        solved = 'opportunities'
    rows = []
    if _given(values['defects']) and _given(values['opportunities']):
        rows.append(['Defects per million opportunities (DPMO)', 1e6 * float(values['defects']) / float(values['opportunities'])])
    return {'values': values, 'solved': solved, 'rows': rows, 'curves': {},
            'notes': ['Sigma quality level = Φ⁻¹(1 − defects/opportunities) + 1.5, the customary long-term 1.5σ shift.'],
            'code': '\n'.join([HEAD, f'defects, opportunities = {values["defects"]!r}, {values["opportunities"]!r}',
                               'print(stats.norm.ppf(1 - defects / opportunities) + 1.5)   # the sigma quality level'])}


@api('power.compute')
def compute(situation='one_mean', alpha=0.05, sides=2, **kw):
    """Solve one situation. Every input is optional; the one left out of
    the effect, the sample size and the power is computed."""
    if situation not in SITUATIONS:
        return {'error': f'unknown situation {situation!r}'}
    try:
        alpha = float(alpha)
    except (TypeError, ValueError):
        return {'error': 'α is not a number'}
    if not 0 < alpha < 1:
        return {'error': 'α must lie between 0 and 1'}
    kw = {k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in kw.items()}
    if situation in ('one_mean', 'two_means', 'k_means') and not (_given(kw.get('sd')) and float(kw['sd']) > 0):
        return {'error': 'give a standard deviation above zero'}
    fn = {'one_mean': _one_mean, 'two_means': _two_means, 'k_means': _k_means, 'one_prop': _one_prop, 'two_props': _two_props,
          'one_var': _one_var, 'poisson': _poisson, 'sigma': _sigma}[situation]
    if situation == 'sigma':
        out = fn(**kw)
    elif situation == 'k_means':
        out = fn(alpha=alpha, **kw)
    else:
        out = fn(alpha=alpha, sides=sides, **kw)
    if 'error' in out:
        return out
    out['situation'] = situation
    out['label'] = SITUATIONS[situation]
    out['alpha'] = alpha
    out['sides'] = sides
    body = out.get('code') or ''
    head = [h for h in ('import numpy as np', 'from scipy import stats') if h not in body]
    out['code'] = '\n'.join([f'# {SITUATIONS[situation]}', *head, body])
    return out


@api('power.situations')
def situations():
    return {'situations': [{'key': k, 'label': v} for k, v in SITUATIONS.items()]}
