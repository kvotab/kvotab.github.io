"""DOE > Sample Size Explorers > Test Calculators.

JMP's hypothesis test calculators (Help > Sample Index > Calculators), the
A/B test of Shmueli et al. ch. 14: a test of two groups from their summary
statistics alone, without the rows.

  Two Means        from the means, standard deviations and sizes: the
                   Welch (unequal variances) or pooled t test,
                   scipy.stats.ttest_ind_from_stats, one- or two-sided,
                   against a hypothesized difference; the interval of the
                   difference; Cohen's d and Hedges' g (the pooled test's,
                   with the exact interval from the noncentral t) or d* and
                   g* (Welch's, Bonett's interval), as Bivariate Analysis's Effect
                   Size computes them
  Two Proportions  from the counts and sizes: statsmodels
                   test_proportions_2indep and confint_proportions_2indep,
                   the difference, the ratio or the odds ratio, by any of
                   their methods; the score test without the n/(n - 1)
                   factor (the default) is at a null difference of 0 the
                   pooled z test JMP's calculator reports
  Several tests    the p-values of several tests adjusted together,
                   statsmodels.stats.multitest.multipletests

Every result carries the Python (scipy, statsmodels) that gives its
numbers, and each test's graph (the statistic's distribution under the
null hypothesis, the observed statistic and its p-value shaded) the
matplotlib that draws it.
"""
import json
import math

import numpy as np
from scipy import stats

from .registry import api

ALTERNATIVES = {'two-sided': 'two-sided', 'greater': 'larger', 'less': 'smaller'}
# the methods of Two Proportions: key -> (statsmodels method, correction, label, has a test)
PROP_METHODS = {
    'diff': [('score', 'score', False, 'Score (pooled z at a difference of 0)', True), ('mn', 'score', True, 'Miettinen-Nurminen (score, n/(n − 1))', True),
             ('agresti-caffo', 'agresti-caffo', False, 'Agresti-Caffo (adjusted Wald)', True), ('wald', 'wald', False, 'Wald', True),
             ('newcomb', 'newcomb', False, 'Newcombe (hybrid score)', False)],
    'ratio': [('score', 'score', False, 'Koopman (score)', True), ('mn', 'score', True, 'Miettinen-Nurminen (score, n/(n − 1))', True),
              ('log', 'log', False, 'Katz (log)', True), ('log-adjusted', 'log-adjusted', False, 'Adjusted log (0.5 added)', True)],
    'odds-ratio': [('score', 'score', False, 'Score', True), ('mn', 'score', True, 'Miettinen-Nurminen (score, n/(n − 1))', True),
                   ('logit', 'logit', False, 'Woolf (logit)', True), ('logit-adjusted', 'logit-adjusted', False, 'Gart (adjusted logit, 0.5 added)', True),
                   ('logit-smoothed', 'logit-smoothed', False, 'Independence-smoothed logit', True)],
}
COMPARE = {'diff': 'Difference', 'ratio': 'Ratio', 'odds-ratio': 'Odds Ratio'}
# multipletests' methods: key -> (label, shown at first)
MULTI = [('holm', 'Holm', True), ('fdr_bh', 'Benjamini-Hochberg (FDR)', True), ('bonferroni', 'Bonferroni', False), ('sidak', 'Šidák', False),
         ('holm-sidak', 'Holm-Šidák', False), ('simes-hochberg', 'Hochberg', False), ('hommel', 'Hommel', False), ('fdr_by', 'Benjamini-Yekutieli (FDR)', False)]
BASE, MUTED, FILL, CRIT = '#2f6690', '#786b5d', '#d9822b', '#b0413e'


def _f(v, name):
    """A number from the page, or an error naming the field."""
    if v is None or v == '':
        raise ValueError(f'{name}: give a value')
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'{name}: not a number')
    if not math.isfinite(x):
        raise ValueError(f'{name}: not a number')
    return x


def _fin(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(x):
    """A number as the shortest Python literal that is the same float."""
    return repr(float(x))


def _name(g, default):
    s = str((g or {}).get('name') or '').strip()
    return s or default


# ---------------------------------------------------------------------------
# the graph: the statistic under the null hypothesis, the observed one, its p-value
# ---------------------------------------------------------------------------

def _curve(stat, df, alternative, alpha):
    """The density of the null distribution (t on df, or the standard normal when df is None) on the graph's grid,
    the tails whose area is the p-value, and the critical values of the test at alpha."""
    dist = stats.norm() if df is None else stats.t(df)
    half = max(4.0, abs(stat) + 1.0) if math.isfinite(stat) else 4.0
    half = min(half, 60.0)
    x = np.linspace(-half, half, 401)
    y = dist.pdf(x)
    if alternative == 'two-sided':
        crit = [float(dist.ppf(alpha / 2)), float(dist.ppf(1 - alpha / 2))]
        a = abs(stat)
        tails = [(-half, -a), (a, half)]
    elif alternative == 'greater':
        crit = [float(dist.ppf(1 - alpha))]
        tails = [(stat, half)]
    else:
        crit = [float(dist.ppf(alpha))]
        tails = [(-half, stat)]
    shade = []
    for lo, hi in tails:
        if hi <= lo:
            continue
        xs = np.linspace(lo, hi, 81)
        shade.append({'x': xs.tolist(), 'y': dist.pdf(xs).tolist()})
    return {'x': x.tolist(), 'y': y.tolist(), 'tails': shade, 'crit': [c for c in crit if math.isfinite(c)], 'stat': stat, 'half': half,
            'df': df, 'label': 't Ratio' if df is not None else 'z'}


def _plot_code(title, c, alternative, alpha):
    """The matplotlib code of the graph _curve() describes."""
    half = c['half']
    dist = f'stats.t({_r(c["df"])})' if c['df'] is not None else 'stats.norm()'
    stat = c['stat']
    if alternative == 'two-sided':
        tails = f'[(-{_r(half)}, -abs(stat)), (abs(stat), {_r(half)})]'
        crit = f'[dist.ppf({alpha!r} / 2), dist.ppf(1 - {alpha!r} / 2)]'
    elif alternative == 'greater':
        tails = f'[(stat, {_r(half)})]'
        crit = f'[dist.ppf(1 - {alpha!r})]'
    else:
        tails = f'[(-{_r(half)}, stat)]'
        crit = f'[dist.ppf({alpha!r})]'
    return '\n'.join([
        'import numpy as np',
        'import matplotlib.pyplot as plt',
        'from scipy import stats',
        f'dist = {dist}   # the statistic\'s distribution when the null hypothesis holds',
        f'stat = {_r(stat)}   # the observed {c["label"]}',
        f'x = np.linspace(-{_r(half)}, {_r(half)}, 401)',
        'fig, ax = plt.subplots(figsize=(4.2, 2.8), layout="constrained")',
        f'ax.plot(x, dist.pdf(x), color="{BASE}", linewidth=1.6)',
        f'for lo, hi in {tails}:   # the p-value: the area beyond the observed statistic',
        '    if hi > lo:',
        '        xs = np.linspace(lo, hi, 81)',
        f'        ax.fill_between(xs, dist.pdf(xs), color="{FILL}", alpha=0.45, linewidth=0)',
        f'for c in {crit}:   # the critical values at alpha',
        f'    ax.axvline(c, color="{CRIT}", linewidth=1, linestyle="--")',
        f'ax.axvline(stat, color="{MUTED}", linewidth=1.4)',
        f'ax.set_xlim(-{_r(half)}, {_r(half)})', 'ax.set_ylim(bottom=0)',
        f'ax.set_xlabel({json.dumps(c["label"])})', 'ax.set_ylabel("Density")', f'ax.set_title({json.dumps(title)})',
        'plt.show()'])


# ---------------------------------------------------------------------------
# Two Means
# ---------------------------------------------------------------------------

def two_means(g1, g2, null=0.0, alternative='two-sided', variance='unequal', alpha=0.05, name='Two Means'):
    """The t test of two means from their summary statistics (scipy.stats.ttest_ind_from_stats)."""
    from .bivariate import bonett_se, hedges_j, smd_rows
    m1, s1, n1 = _f(g1.get('mean'), 'Mean 1'), _f(g1.get('sd'), 'Std Dev 1'), _f(g1.get('n'), 'N 1')
    m2, s2, n2 = _f(g2.get('mean'), 'Mean 2'), _f(g2.get('sd'), 'Std Dev 2'), _f(g2.get('n'), 'N 2')
    d0 = _f(null if null not in (None, '') else 0.0, 'Hypothesized Difference')
    if alternative not in ALTERNATIVES:
        raise ValueError(f'unknown alternative {alternative!r}')
    for v, nm in ((n1, 'N 1'), (n2, 'N 2')):
        if v < 2:
            raise ValueError(f'{nm}: at least 2 (a standard deviation needs two values)')
    for v, nm in ((s1, 'Std Dev 1'), (s2, 'Std Dev 2')):
        if v < 0:
            raise ValueError(f'{nm}: 0 or more')
    if s1 == 0 and s2 == 0:
        raise ValueError('both standard deviations are 0: no test')
    equal = variance == 'equal'
    names = (_name(g1, 'Group 1'), _name(g2, 'Group 2'))
    diff = m1 - m2
    df_p = n1 + n2 - 2
    sp = math.sqrt(((n1 - 1) * s1 * s1 + (n2 - 1) * s2 * s2) / df_p)
    if equal:
        se = sp * math.sqrt(1 / n1 + 1 / n2)
        df = df_p
    else:
        v1, v2 = s1 * s1 / n1, s2 * s2 / n2
        se = math.sqrt(v1 + v2)
        df = (v1 + v2) ** 2 / (v1 * v1 / (n1 - 1) + v2 * v2 / (n2 - 1))
    # scipy's test, the first mean shifted by the hypothesized difference
    res = {a: stats.ttest_ind_from_stats(m1 - d0, s1, n1, m2, s2, n2, equal_var=equal, alternative=a) for a in ALTERNATIVES}
    t = float(res['two-sided'].statistic)
    q = float(stats.t.ppf(1 - alpha / 2, df))
    out = {'kind': 'means', 'name': name, 'groups': names, 'equal': equal, 'null': d0, 'alternative': alternative, 'alpha': alpha,
           'diff': diff, 'se': se, 'lower': diff - q * se, 'upper': diff + q * se, 't': t, 'df': df,
           'p_two': float(res['two-sided'].pvalue), 'p_greater': float(res['greater'].pvalue), 'p_less': float(res['less'].pvalue),
           'pooled_sd': sp}
    out['p'] = out[{'two-sided': 'p_two', 'greater': 'p_greater', 'less': 'p_less'}[alternative]]
    qm = [float(stats.t.ppf(1 - alpha / 2, n - 1)) for n in (n1, n2)]
    out['summary'] = [{'group': names[i], 'mean': m, 'sd': s, 'n': n, 'se': s / math.sqrt(n), 'lower': m - qm[i] * s / math.sqrt(n), 'upper': m + qm[i] * s / math.sqrt(n)}
                      for i, (m, s, n) in enumerate(((m1, s1, n1), (m2, s2, n2)))]
    # effect sizes, as Bivariate Analysis's Effect Size (the observed difference)
    if equal:
        if sp > 0:
            k = math.sqrt(1 / n1 + 1 / n2)
            d = diff / sp
            out['effect'] = [{**r, 'method': r['method']} for r in smd_rows(d, d / k, df_p, k, alpha)]
    else:
        s = math.sqrt((s1 * s1 + s2 * s2) / 2)
        d = diff / s
        sed = bonett_se(d, s1 * s1, s2 * s2, n1, n2)
        z = float(stats.norm.ppf(1 - alpha / 2))
        j = hedges_j(df_p)
        out['effect'] = [{'effect': "Cohen's d*", 'estimate': d, 'lower': d - z * sed, 'upper': d + z * sed, 'method': 'Bonett (2008)'},
                         {'effect': "Hedges' g*", 'estimate': j * d, 'lower': j * (d - z * sed), 'upper': j * (d + z * sed), 'method': 'Bonett (2008) × J'}]
    out['curve'] = _curve(t, df, alternative, alpha)
    out['plot_code'] = _plot_code(f'{name}: t Ratio', out['curve'], alternative, alpha)
    out['code'] = _means_code(m1, s1, n1, m2, s2, n2, d0, alternative, equal, alpha, names)
    return out


def _means_code(m1, s1, n1, m2, s2, n2, d0, alternative, equal, alpha, names):
    L = ['import numpy as np', 'from scipy import stats, optimize, special',
         f'mean1, sd1, n1 = {_r(m1)}, {_r(s1)}, {_r(n1)}   # {names[0]}',
         f'mean2, sd2, n2 = {_r(m2)}, {_r(s2)}, {_r(n2)}   # {names[1]}',
         f'd0 = {_r(d0)}   # the hypothesized difference, mean 1 - mean 2',
         f'alpha = {alpha!r}',
         f'equal = {equal!r}   # {"the pooled t test (equal variances)" if equal else "Welch" + chr(39) + "s t test (unequal variances)"}',
         '# the test: the first mean shifted by d0, as ttest_ind_from_stats tests a difference of 0',
         f'for alt in ["two-sided", "greater", "less"]:   # the report\'s chosen: {alternative}',
         '    print(alt, stats.ttest_ind_from_stats(mean1 - d0, sd1, n1, mean2, sd2, n2, equal_var=equal, alternative=alt))',
         'diff = mean1 - mean2',
         'sp = np.sqrt(((n1 - 1) * sd1 ** 2 + (n2 - 1) * sd2 ** 2) / (n1 + n2 - 2))   # the pooled standard deviation',
         'if equal:',
         '    se, df_ = sp * np.sqrt(1 / n1 + 1 / n2), n1 + n2 - 2',
         'else:',
         '    v1, v2 = sd1 ** 2 / n1, sd2 ** 2 / n2',
         '    se, df_ = np.sqrt(v1 + v2), (v1 + v2) ** 2 / (v1 ** 2 / (n1 - 1) + v2 ** 2 / (n2 - 1))   # Welch-Satterthwaite',
         'q = stats.t.ppf(1 - alpha / 2, df_)',
         'print("Difference", diff, "Std Err Dif", se, "DF", df_, "Lower CL", diff - q * se, "Upper CL", diff + q * se)',
         '# effect size (Bivariate Analysis\'s): the observed difference standardized',
         'J = np.exp(special.gammaln((n1 + n2 - 2) / 2) - 0.5 * np.log((n1 + n2 - 2) / 2) - special.gammaln((n1 + n2 - 3) / 2))   # Hedges\' exact correction']
    if equal:
        L += ['def ncp(t, df, q):   # the noncentrality at which t is the q quantile of the noncentral t',
              '    return optimize.brentq(lambda lam: stats.nct.cdf(t, df, lam) - q, t - 10 - abs(t), t + 10 + abs(t))',
              'd = diff / sp; k = np.sqrt(1 / n1 + 1 / n2); t_d = d / k',
              'lo, hi = ncp(t_d, n1 + n2 - 2, 1 - alpha / 2) * k, ncp(t_d, n1 + n2 - 2, alpha / 2) * k',
              'print("Cohen\'s d", d, lo, hi, "Hedges\' g", J * d, J * lo, J * hi)   # the exact interval from the noncentral t']
    else:
        L += ['s = np.sqrt((sd1 ** 2 + sd2 ** 2) / 2); d = diff / s',
              'se_d = np.sqrt(d ** 2 * (sd1 ** 4 / (n1 - 1) + sd2 ** 4 / (n2 - 1)) / (8 * s ** 4) + (sd1 ** 2 / (n1 - 1) + sd2 ** 2 / (n2 - 1)) / s ** 2)   # Bonett (2008)',
              'z = stats.norm.ppf(1 - alpha / 2)',
              'print("Cohen\'s d*", d, d - z * se_d, d + z * se_d, "Hedges\' g*", J * d, J * (d - z * se_d), J * (d + z * se_d))']
    return '\n'.join(L)


# ---------------------------------------------------------------------------
# Two Proportions
# ---------------------------------------------------------------------------

def _methods(compare):
    if compare not in PROP_METHODS:
        raise ValueError(f'unknown comparison {compare!r}')
    return PROP_METHODS[compare]


def two_props(g1, g2, compare='diff', null=None, alternative='two-sided', method='score', alpha=0.05, name='Two Proportions'):
    """The comparison of two proportions from counts (statsmodels test_proportions_2indep, confint_proportions_2indep)."""
    from statsmodels.stats.proportion import confint_proportions_2indep, proportion_confint, test_proportions_2indep
    x1, n1 = _f(g1.get('count'), 'Count 1'), _f(g1.get('n'), 'N 1')
    x2, n2 = _f(g2.get('count'), 'Count 2'), _f(g2.get('n'), 'N 2')
    for x, n, i in ((x1, n1, 1), (x2, n2, 2)):
        if n < 1:
            raise ValueError(f'N {i}: at least 1')
        if not 0 <= x <= n:
            raise ValueError(f'Count {i}: from 0 to N {i}')
    if alternative not in ALTERNATIVES:
        raise ValueError(f'unknown alternative {alternative!r}')
    methods = _methods(compare)
    keys = [m[0] for m in methods]
    if method not in keys or not dict((m[0], m[4]) for m in methods)[method]:
        raise ValueError(f'the method {method!r} has no test of the {COMPARE[compare].lower()}')
    base = 0.0 if compare == 'diff' else 1.0
    v0 = base if null in (None, '') else _f(null, 'Hypothesized Value')
    if compare != 'diff' and not v0 > 0:
        raise ValueError(f'Hypothesized Value: a {COMPARE[compare].lower()} above 0')
    if compare == 'diff' and not -1 < v0 < 1:
        raise ValueError('Hypothesized Value: a difference between -1 and 1')
    names = (_name(g1, 'Group 1'), _name(g2, 'Group 2'))
    p1, p2 = x1 / n1, x2 / n2
    with np.errstate(divide='ignore', invalid='ignore'):
        est = {'diff': p1 - p2, 'ratio': p1 / p2 if p2 > 0 else (math.inf if p1 > 0 else math.nan),
               'odds-ratio': (p1 / (1 - p1)) / (p2 / (1 - p2)) if 0 < p2 < 1 and p1 < 1 else math.nan}[compare]
    rows, notes = [], []
    for key, sm_m, corr, label, has_test in methods:
        row = {'key': key, 'method': label, 'lower': None, 'upper': None, 'z': None, 'p_two': None, 'p_greater': None, 'p_less': None}
        with np.errstate(divide='ignore', invalid='ignore'):
            try:
                lo, hi = confint_proportions_2indep(x1, n1, x2, n2, method=sm_m, compare=compare, alpha=alpha, correction=corr)
                row['lower'], row['upper'] = _fin(lo), _fin(hi)
                if row['lower'] is not None and row['upper'] is not None and not row['lower'] <= row['upper']:
                    row['lower'] = row['upper'] = None
            except (ValueError, ZeroDivisionError, FloatingPointError, RuntimeError):
                row['note'] = 'not defined with these counts'
            if has_test:
                try:
                    for a, sa in ALTERNATIVES.items():
                        r = test_proportions_2indep(x1, n1, x2, n2, value=v0, method=sm_m, compare=compare, alternative=sa, correction=corr)
                        row['z'] = _fin(r.statistic)
                        row[{'two-sided': 'p_two', 'greater': 'p_greater', 'less': 'p_less'}[a]] = _fin(r.pvalue)
                except (ValueError, ZeroDivisionError, FloatingPointError, RuntimeError):
                    row['note'] = 'not defined with these counts'
        rows.append(row)
    chosen = next(r for r in rows if r['key'] == method)
    if chosen['z'] is None:
        raise ValueError(f'{chosen["method"]}: not defined with these counts; choose another method')
    if min(x1, x2, n1 - x1, n2 - x2) <= 0:
        notes.append('A count is 0 (or all): some methods are not defined, and the adjusted ones add 0.5 (or 1) to the counts.')
    if any(abs(v - round(v)) > 1e-9 for v in (x1, n1, x2, n2)):
        notes.append('The counts are not whole numbers: the methods take them as they are.')
    out = {'kind': 'props', 'name': name, 'groups': names, 'compare': compare, 'null': v0, 'alternative': alternative, 'alpha': alpha, 'method': method,
           'estimate': _fin(est), 'p1': p1, 'p2': p2, 'methods': rows, 'z': chosen['z'], 'lower': chosen['lower'], 'upper': chosen['upper'],
           'p_two': chosen['p_two'], 'p_greater': chosen['p_greater'], 'p_less': chosen['p_less'], 'notes': notes}
    out['p'] = out[{'two-sided': 'p_two', 'greater': 'p_greater', 'less': 'p_less'}[alternative]]
    out['summary'] = []
    for i, (x, n) in enumerate(((x1, n1), (x2, n2))):
        lo, hi = proportion_confint(x, n, alpha=alpha, method='wilson')
        out['summary'].append({'group': names[i], 'count': x, 'n': n, 'prop': x / n, 'lower': float(lo), 'upper': float(hi)})
    out['curve'] = _curve(chosen['z'], None, alternative, alpha)
    out['plot_code'] = _plot_code(f'{name}: z', out['curve'], alternative, alpha)
    out['code'] = _props_code(x1, n1, x2, n2, compare, v0, alternative, methods, method, alpha, names)
    return out


def _props_code(x1, n1, x2, n2, compare, v0, alternative, methods, method, alpha, names):
    J = json.dumps
    L = ['from statsmodels.stats.proportion import confint_proportions_2indep, proportion_confint, test_proportions_2indep',
         f'count1, n1 = {_r(x1)}, {_r(n1)}   # {names[0]}',
         f'count2, n2 = {_r(x2)}, {_r(n2)}   # {names[1]}',
         f'value = {_r(v0)}   # the hypothesized {COMPARE[compare].lower()}',
         f'alpha = {alpha!r}',
         'print(proportion_confint(count1, n1, alpha=alpha, method="wilson"), proportion_confint(count2, n2, alpha=alpha, method="wilson"))   # each proportion, Wilson\'s interval']
    for key, sm_m, corr, label, has_test in methods:
        args = f'count1, n1, count2, n2, method={J(sm_m)}, compare={J(compare)}, correction={corr!r}'
        mark = '   # the report\'s test' if key == method else ''
        L.append(f'print({J(label)}, confint_proportions_2indep({args}, alpha=alpha)){mark}')
        if has_test:
            L.append(f'for alt in ["two-sided", "larger", "smaller"]:   # the report\'s chosen: {ALTERNATIVES[alternative]}')
            L.append(f'    r = test_proportions_2indep({args}, value=value, alternative=alt)')
            L.append('    print("  ", alt, "z", r.statistic, "p", r.pvalue)')
    return '\n'.join(L)


# ---------------------------------------------------------------------------
# several tests at once
# ---------------------------------------------------------------------------

def multiple(names, pvals, alpha):
    """The p-values adjusted together by each of multipletests' methods."""
    from statsmodels.stats.multitest import multipletests
    p = np.asarray(pvals, dtype=float)
    rows = [{'test': n, 'p': float(v)} for n, v in zip(names, p)]
    for key, _, _ in MULTI:
        rej, adj, _, _ = multipletests(p, alpha=alpha, method=key)
        for r, a, j in zip(rows, adj, rej):
            r[key] = float(a)
            r[f'{key}_reject'] = bool(j)
    code = '\n'.join(['from statsmodels.stats.multitest import multipletests',
                      f'names = {json.dumps(list(names))}',
                      f'p = [{", ".join(_r(v) for v in p)}]   # each test\'s p-value (of its chosen alternative)',
                      f'for method in {json.dumps([k for k, _, _ in MULTI])}:',
                      f'    reject, adjusted, _, _ = multipletests(p, alpha={alpha!r}, method=method)',
                      '    print(method, dict(zip(names, adjusted)))'])
    return {'rows': rows, 'methods': [{'key': k, 'label': lab, 'shown': sh} for k, lab, sh in MULTI], 'code': code, 'alpha': alpha}


@api('calculators.compute')
def compute(tests, alpha=0.05):
    """Every test of the report: [{key, kind ('means' or 'props'), name, g1, g2, null, alternative, variance
    (means: 'unequal' or 'equal'), compare, method (props)}]. An error in a test is that test's; with two or
    more good tests their p-values are adjusted together."""
    alpha = _f(alpha, 'α')
    if not 0 < alpha < 1:
        raise ValueError('α: between 0 and 1')
    out = []
    for i, t in enumerate(tests or []):
        name = str(t.get('name') or f'Test {i + 1}')
        try:
            if t.get('kind') == 'means':
                r = two_means(t.get('g1') or {}, t.get('g2') or {}, t.get('null'), t.get('alternative') or 'two-sided', t.get('variance') or 'unequal', alpha, name)
            elif t.get('kind') == 'props':
                r = two_props(t.get('g1') or {}, t.get('g2') or {}, t.get('compare') or 'diff', t.get('null'), t.get('alternative') or 'two-sided',
                              t.get('method') or 'score', alpha, name)
            else:
                raise ValueError(f'unknown test {t.get("kind")!r}')
        except ValueError as e:
            r = {'kind': t.get('kind'), 'name': name, 'error': str(e)}
        r['key'] = t.get('key')
        out.append(r)
    ok = [r for r in out if 'error' not in r and r.get('p') is not None]
    res = {'tests': out, 'alpha': alpha}
    if len(ok) >= 2:
        res['multiple'] = multiple([r['name'] for r in ok], [r['p'] for r in ok], alpha)
    return res
