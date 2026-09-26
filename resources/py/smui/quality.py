"""Analyze > Quality and Process: Control Chart Builder, Process Capability,
Pareto Plot and Variability / Attribute Gauge Chart.

Control limits are Shewhart's. The constants of the range and of the
standard deviation of n normal values (d2, d3, c4, and the A2, A3, B3, B4,
D3, D4 made from them) are computed rather than looked up: d2 and d3 by
Gauss-Legendre quadrature of the distribution of the range, c4 from the
gamma function; the tests compare them with the printed tables.

  sigma within  XBar & R: the mean of R_i/d2(n_i); XBar & S: the mean of
                s_i/c4(n_i); Individuals: the mean moving range over
                d2(span) (1.128 for span 2). With equal subgroup sizes these
                are the textbook R-bar/d2 and S-bar/c4.
  XBar          grand mean +- k sigma/sqrt(n_i)
  R             d2(n_i) sigma +- k d3(n_i) sigma, the lower limit at least 0
  S             c4(n_i) sigma +- k sigma sqrt(1 - c4^2)
  P, NP         p-bar +- k sqrt(p-bar (1 - p-bar)/n_i), proportions or counts
  C, U          u-bar +- k sqrt(u-bar/n_i)
  EWMA          z_i = lambda xbar_i + (1 - lambda) z_(i-1), exact variance
  CUSUM         tabular: C+ = max(0, C+ + z - k), C- likewise, alarm above h

Capability indices are the usual ones (Cp, Cpk, Cpl, Cpu within; Pp, Ppk,
Ppl, Ppu, Cpm overall), with confidence intervals from chi-square (Cp, Pp),
Bissell's normal approximation (Cpk, Ppk), the noncentral t (the one-sided
indices) and Boyles' approximation (Cpm). Nonnormal data: a lognormal,
Weibull or gamma fit by scipy and the percentile (ISO 22514) method.

Variance components are the ANOVA (expected mean squares) estimates for a
balanced design, from statsmodels' OLS and anova_lm, or REML from
statsmodels' MixedLM, for crossed, nested and main-effect models.
"""
import functools
import itertools
import json
import math

import numpy as np
import pandas as pd
from scipy import optimize, special, stats

from . import data
from .registry import api
from .util import code_head, col, table as rtable

# ---------------------------------------------------------------------------
# The constants of control charts
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def _range_moments(n):
    """(d2, d3): the mean and standard deviation of the range of n standard
    normal values, from P(W > w) = 1 - n int phi(x) [Phi(x + w) - Phi(x)]^(n-1) dx
    integrated by Gauss-Legendre (E W = int P(W > w) dw, E W^2 = 2 int w P(W > w) dw)."""
    n = int(n)
    if n < 2:
        return (float('nan'), float('nan'))
    xg, wg = np.polynomial.legendre.leggauss(200)
    x, wx = 10.0 * xg, 10.0 * wg
    w, ww = 8.0 * (xg + 1.0), 8.0 * wg
    X, W = np.meshgrid(x, w, indexing='ij')
    inner = n * stats.norm.pdf(X) * (stats.norm.cdf(X + W) - stats.norm.cdf(X)) ** (n - 1)
    below = inner.T @ wx
    surv = 1.0 - below
    d2 = float(surv @ ww)
    ew2 = float(2.0 * (w * surv) @ ww)
    return (d2, math.sqrt(max(ew2 - d2 * d2, 0.0)))


def d2(n):
    return _range_moments(int(n))[0]


def d3(n):
    return _range_moments(int(n))[1]


def c4(n):
    n = int(n)
    if n < 2:
        return float('nan')
    return float(math.sqrt(2.0 / (n - 1)) * math.exp(special.gammaln(n / 2.0) - special.gammaln((n - 1) / 2.0)))


# The median of the range of two normal values: sqrt(2) times the upper
# quartile of the standard normal (0.954), for the median moving range.
D4_2 = math.sqrt(2.0) * float(stats.norm.ppf(0.75))


def factors(n, k=3.0):
    """The factors of the variables control charts for subgroups of n, with
    k-sigma limits (the printed tables have k = 3)."""
    dd2, dd3, cc4 = d2(n), d3(n), c4(n)
    rs = math.sqrt(max(1.0 - cc4 * cc4, 0.0))
    return {
        'n': n, 'A': k / math.sqrt(n), 'A2': k / (dd2 * math.sqrt(n)), 'A3': k / (cc4 * math.sqrt(n)),
        'c4': cc4, 'B3': max(0.0, 1.0 - k * rs / cc4), 'B4': 1.0 + k * rs / cc4,
        'B5': max(0.0, cc4 - k * rs), 'B6': cc4 + k * rs,
        'd2': dd2, 'd3': dd3, 'D1': max(0.0, dd2 - k * dd3), 'D2': dd2 + k * dd3,
        'D3': max(0.0, 1.0 - k * dd3 / dd2), 'D4': 1.0 + k * dd3 / dd2,
    }


@api('quality.constants')
def constants(n_max=25, k=3.0):
    rows = [factors(n, k) for n in range(2, int(n_max) + 1)]
    cols = [col('n', 'n', 'int')] + [col(key, key) for key in ('A2', 'A3', 'd2', 'd3', 'c4', 'D3', 'D4', 'B3', 'B4')]
    return {'table': rtable(cols, rows)}


_CONST_CODE = '''from scipy import integrate, special, stats
def d2(n):   # the mean range of n standard normal values
    return integrate.quad(lambda x: 1 - stats.norm.cdf(x) ** n - stats.norm.sf(x) ** n, -np.inf, np.inf)[0]
def d3(n):   # the standard deviation of that range
    ew2 = integrate.dblquad(lambda w, x: w * w * n * (n - 1) * stats.norm.pdf(x) * stats.norm.pdf(x + w) * (stats.norm.cdf(x + w) - stats.norm.cdf(x)) ** (n - 2), -10, 10, 0, 16)[0]
    return np.sqrt(ew2 - d2(n) ** 2)
def c4(n):
    return np.sqrt(2 / (n - 1)) * np.exp(special.gammaln(n / 2) - special.gammaln((n - 1) / 2))'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _label(v):
    if v is None:
        return ''
    if isinstance(v, (float, np.floating)):
        if not np.isfinite(v):
            return ''
        if float(v).is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f'{float(v):.10g}'
    return str(v)


def _codes(tid, name, rows):
    """Integer codes (-1 for missing) in the page's level order, and the
    labels of the levels. A continuous column's levels are its sorted
    distinct values."""
    s = data.series(tid, name, rows, as_category=True)
    if isinstance(s.dtype, pd.CategoricalDtype):
        return s.cat.codes.to_numpy().astype(int), [_label(v) for v in s.cat.categories]
    v = s.to_numpy(dtype=float) if data.meta(tid, name).get('dataType') == 'numeric' else None
    if v is None:
        vals = s.to_numpy(dtype=object)
        u = sorted({x for x in vals if x is not None})
        m = {x: i for i, x in enumerate(u)}
        return np.array([m[x] if x is not None else -1 for x in vals], dtype=int), [str(x) for x in u]
    ok = np.isfinite(v)
    u = np.unique(v[ok])
    codes = np.full(len(v), -1, dtype=int)
    codes[ok] = np.searchsorted(u, v[ok])
    return codes, [_label(x) for x in u]


def _num(tid, name, rows):
    return data.series(tid, name, rows, as_category=False).to_numpy(dtype=float)


# ---------------------------------------------------------------------------
# Control Chart Builder
# ---------------------------------------------------------------------------

CHART_LABEL = {
    'xbar_r': 'XBar & R', 'xbar_s': 'XBar & S', 'ir': 'Individual & Moving Range', 'run': 'Run Chart',
    'p': 'P', 'np': 'NP', 'c': 'C', 'u': 'U', 'ewma': 'EWMA', 'cusum': 'CUSUM', 'lj': 'Levey Jennings',
}
SIGMA_LABEL = {'range': 'Range', 'std': 'Standard Deviation', 'mr': 'Moving Range', 'mmr': 'Median Moving Range',
               'lj': 'Levey Jennings', 'known': 'Known', 'binomial': 'Binomial', 'poisson': 'Poisson', 'pooled': 'Pooled Standard Deviation'}

TEST_TEXT = {
    1: 'One point beyond Zone A (outside the control limits)',
    2: '{n} points in a row on one side of the center line',
    3: '{n} points in a row steadily increasing or decreasing',
    4: '{n} points in a row alternating up and down',
    5: '{m} out of {n} points in a row in Zone A or beyond, on one side',
    6: '{m} out of {n} points in a row in Zone B or beyond, on one side',
    7: '{n} points in a row in Zone C, on both sides of the center line',
    8: '{n} points in a row on both sides of the center line with none in Zone C',
}
TEST_N = {2: 9, 3: 6, 4: 14, 5: [2, 3], 6: [4, 5], 7: 15, 8: 8}


def _test_n(test_n):
    out = {k: (list(v) if isinstance(v, (list, tuple)) else v) for k, v in TEST_N.items()}
    for k, v in (test_n or {}).items():
        k = int(k)
        if k in (5, 6):
            if isinstance(v, (list, tuple)) and len(v) == 2 and 0 < int(v[0]) <= int(v[1]):
                out[k] = [int(v[0]), int(v[1])]
        elif k in out and v is not None and int(v) >= 2:
            out[k] = int(v)
    return out


def test_description(t, n):
    spec = n.get(t)
    if isinstance(spec, list):
        return TEST_TEXT[t].format(m=spec[0], n=spec[1])
    return TEST_TEXT[t].format(n=spec)


def nelson(values, cl, sd, lcl, ucl, tests, test_n=None, k=3.0):
    """The Western Electric / Nelson tests. Returns, for every point, the
    sorted list of the tests it fails (flagged on the point that completes
    the pattern). Zones are thirds of the distance from the center line to
    the k-sigma limit; NaN points are skipped (a pattern runs over the valid
    points)."""
    nn = _test_n(test_n)
    v = np.asarray(values, dtype=float)
    c = np.asarray(cl, dtype=float)
    s = np.asarray(sd, dtype=float)
    lo = np.asarray(lcl, dtype=float)
    hi = np.asarray(ucl, dtype=float)
    npts = len(v)
    flags = [[] for _ in range(npts)]
    valid = [i for i in range(npts) if np.isfinite(v[i]) and np.isfinite(c[i])]
    if not valid:
        return flags
    idx = np.array(valid)
    x = v[idx]
    with np.errstate(divide='ignore', invalid='ignore'):
        z = np.where(s[idx] > 0, 3.0 * (x - c[idx]) / (k * s[idx]), 0.0)
    m = len(x)
    tests = sorted({int(t) for t in (tests or [])})

    def flag(j, t):
        i = int(idx[j])
        if t not in flags[i]:
            flags[i].append(t)

    for t in tests:
        if t == 1:
            for j in range(m):
                i = idx[j]
                if (np.isfinite(hi[i]) and x[j] > hi[i]) or (np.isfinite(lo[i]) and x[j] < lo[i]):
                    flag(j, 1)
        elif t == 2:
            need = nn[2]
            run, side = 0, 0
            for j in range(m):
                sg = 1 if z[j] > 0 else (-1 if z[j] < 0 else 0)
                if sg != 0 and sg == side:
                    run += 1
                else:
                    run, side = (1, sg) if sg != 0 else (0, 0)
                if run >= need:
                    flag(j, 2)
        elif t == 3:
            need = nn[3]
            run, dirn = 1, 0
            for j in range(1, m):
                d = 1 if x[j] > x[j - 1] else (-1 if x[j] < x[j - 1] else 0)
                if d != 0 and d == dirn:
                    run += 1
                else:
                    run, dirn = (2, d) if d != 0 else (1, 0)
                if run >= need:
                    flag(j, 3)
        elif t == 4:
            need = nn[4]
            run, last = 1, 0
            for j in range(1, m):
                d = 1 if x[j] > x[j - 1] else (-1 if x[j] < x[j - 1] else 0)
                if d != 0 and last != 0 and d == -last:
                    run += 1
                else:
                    run = 2 if d != 0 else 1
                last = d
                if run >= need:
                    flag(j, 4)
        elif t in (5, 6):
            mm, win = nn[t]
            lim = 2.0 if t == 5 else 1.0
            for j in range(m):
                for sg in (1, -1):
                    if sg * z[j] > lim:
                        w0 = max(0, j - win + 1)
                        if int(np.sum(sg * z[w0:j + 1] > lim)) >= mm:
                            flag(j, t)
        elif t == 7:
            need = nn[7]
            run = 0
            for j in range(m):
                run = run + 1 if abs(z[j]) < 1.0 else 0
                if run >= need:
                    flag(j, 7)
        elif t == 8:
            need = nn[8]
            run = 0
            for j in range(m):
                run = run + 1 if abs(z[j]) > 1.0 else 0
                if run >= need:
                    flag(j, 8)
    for f in flags:
        f.sort()
    return flags


def _units(tid, y, rows, subgroup=None, phase=None, n_trials=None, subgroup_size=None, individual=False):
    """The plotted units (subgroups, or rows for individual charts), in the
    order of the subgroup column's levels (then of the rows)."""
    yv = _num(tid, y, rows)
    idx = data.series(tid, y, rows, as_category=False).index.to_numpy()
    ok = np.isfinite(yv)
    sg_codes, sg_labels = (_codes(tid, subgroup, rows) if subgroup else (None, None))
    ph_codes, ph_labels = (_codes(tid, phase, rows) if phase else (None, None))
    nt = _num(tid, n_trials, rows) if n_trials else None
    if sg_codes is not None:
        ok &= sg_codes >= 0
    if ph_codes is not None:
        ok &= ph_codes >= 0
    if nt is not None:
        ok &= np.isfinite(nt) & (nt >= 0)
    pos = np.nonzero(ok)[0]
    units = []
    if individual or (sg_codes is None and not subgroup_size):
        order = pos if sg_codes is None else pos[np.lexsort((pos, sg_codes[pos]))]
        for seq, p in enumerate(order):
            units.append({'label': sg_labels[sg_codes[p]] if sg_codes is not None else str(seq + 1), 'pos': [int(p)],
                          'phase': int(ph_codes[p]) if ph_codes is not None else -1})
    elif sg_codes is None:
        size = max(1, int(subgroup_size))
        # consecutive rows, a new subgroup also where the phase changes
        cur, cur_phase = [], None
        for p in pos:
            ph = int(ph_codes[p]) if ph_codes is not None else -1
            if cur and (len(cur) >= size or ph != cur_phase):
                units.append({'label': str(len(units) + 1), 'pos': cur, 'phase': cur_phase})
                cur = []
            cur.append(int(p))
            cur_phase = ph
        if cur:
            units.append({'label': str(len(units) + 1), 'pos': cur, 'phase': cur_phase})
    else:
        keys = {}
        for p in pos:
            ph = int(ph_codes[p]) if ph_codes is not None else -1
            key = (int(sg_codes[p]), ph)
            keys.setdefault(key, []).append(int(p))
        for (code, ph) in sorted(keys, key=lambda kk: (kk[0], min(keys[kk]))):
            units.append({'label': sg_labels[code], 'pos': keys[(code, ph)], 'phase': ph})
    for u in units:
        p = np.asarray(u['pos'], dtype=int)
        u['y'] = yv[p]
        u['rows'] = [int(r) for r in idx[p]]
        u['n'] = len(p)
        u['trials'] = float(np.sum(nt[p])) if nt is not None else None
        del u['pos']
    return units, (ph_labels or [])


def _moving_ranges(x, span=2):
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    for i in range(span - 1, len(x)):
        w = x[i - span + 1:i + 1]
        out[i] = np.max(w) - np.min(w)
    return out


def within_sigma(units, method, span=2):
    """The within-subgroup sigma of a list of units, and its effective
    degrees of freedom (for the capability intervals)."""
    if method == 'range':
        rs = [(np.ptp(u['y']), len(u['y'])) for u in units if len(u['y']) >= 2]
        if not rs:
            return float('nan'), float('nan')
        sig = float(np.mean([r / d2(n) for r, n in rs]))
        nu = float(sum(d2(n) ** 2 / (2 * d3(n) ** 2) for _, n in rs))   # Patnaik
        return sig, nu
    if method == 'std':
        ss = [(np.std(u['y'], ddof=1), len(u['y'])) for u in units if len(u['y']) >= 2]
        if not ss:
            return float('nan'), float('nan')
        sig = float(np.mean([s / c4(n) for s, n in ss]))
        nu = float(sum(c4(n) ** 2 / (2 * (1 - c4(n) ** 2)) for _, n in ss))
        return sig, nu
    if method == 'pooled':
        num = sum((len(u['y']) - 1) * np.var(u['y'], ddof=1) for u in units if len(u['y']) >= 2)
        dof = sum(len(u['y']) - 1 for u in units if len(u['y']) >= 2)
        if dof <= 0:
            return float('nan'), float('nan')
        return float(math.sqrt(num / dof) / c4(dof + 1)), float(dof)
    if method in ('mr', 'mmr'):
        x = np.array([float(np.mean(u['y'])) for u in units])
        mr = _moving_ranges(x, span)
        mr = mr[np.isfinite(mr)]
        if not len(mr):
            return float('nan'), float('nan')
        if method == 'mmr':
            return float(np.median(mr) / D4_2), float(0.62 * len(mr))
        return float(np.mean(mr) / d2(span)), float(0.62 * len(mr))
    if method == 'lj':
        allv = np.concatenate([u['y'] for u in units]) if units else np.array([])
        if len(allv) < 2:
            return float('nan'), float('nan')
        return float(np.std(allv, ddof=1)), float(len(allv) - 1)
    raise ValueError(f'unknown sigma method {method!r}')


def _grand_mean(units):
    tot = sum(float(np.sum(u['y'])) for u in units)
    n = sum(len(u['y']) for u in units)
    return tot / n if n else float('nan')


def _default_sigma(chart, units):
    if chart == 'xbar_s':
        return 'std'
    if chart in ('ir', 'run', 'lj'):
        return 'lj' if chart == 'lj' else 'mr'
    if chart in ('xbar_r', 'ewma', 'cusum'):
        return 'range' if any(len(u['y']) >= 2 for u in units) else 'mr'
    return None


def _cusum_arl(k, h, shift):
    """Siegmund's approximation to the average run length of a two-sided
    tabular CUSUM (k, h in sigma units of the plotted mean) at a shift."""
    b = h + 1.166

    def one(delta):
        if abs(delta) < 1e-9:
            return b * b
        return (math.exp(-2 * delta * b) + 2 * delta * b - 1) / (2 * delta * delta)
    up, dn = one(shift - k), one(-shift - k)
    return 1.0 / (1.0 / up + 1.0 / dn)


@api('quality.control_chart')
def control_chart(table, y, rows=None, chart='xbar_r', subgroup=None, phase=None, n_trials=None, subgroup_size=None,
                  sigma=None, k=3.0, mr_span=2, known_mean=None, known_sigma=None, lam=0.2, ewma_l=3.0, target=None,
                  cusum_h=4.0, cusum_k=0.5, head_start=False, tests=None, test_n=None, dispersion_tests=False,
                  spec=None, alpha=0.05, table_name='data'):
    """One process column: the points, center lines, limits and zones of each
    chart, the tests, the limit summaries and (with spec limits) a short
    capability analysis."""
    chart = chart or 'xbar_r'
    if chart not in CHART_LABEL:
        return {'error': f'unknown chart type {chart}'}
    k = float(k or 3.0)
    span = max(2, int(mr_span or 2))
    individual = chart in ('ir', 'lj')
    units, phase_labels = _units(table, y, rows, subgroup, phase, n_trials, subgroup_size, individual=individual)
    if not units:
        return {'error': f'{y}: no values to chart'}
    attribute = chart in ('p', 'np', 'c', 'u')
    if chart in ('xbar_r', 'xbar_s') and all(u['n'] < 2 for u in units):
        return {'error': 'XBar charts need subgroups of two or more: give a Subgroup column (or a subgroup size), or choose Individual & Moving Range'}
    if attribute:
        for u in units:
            u['count'] = float(np.sum(u['y']))
            u['size'] = u['trials'] if u['trials'] is not None else float(u['n'])
        if chart in ('p', 'np') and any(u['count'] > u['size'] + 1e-9 for u in units):
            return {'error': 'a P or NP chart counts defective units: the count is larger than the number inspected (n Trials) in some subgroup'}
    method = sigma if (sigma and not attribute) else _default_sigma(chart, units)
    if known_sigma is not None and not attribute:
        method = 'known'
    if chart == 'run':
        method = None   # a run chart has no limits
    nu = len(units)
    ph = [u['phase'] for u in units]
    phases = sorted(set(ph), key=lambda p: ph.index(p))
    ylab = y
    panels = []
    notes = []
    sig_by_phase = {}
    center_by_phase = {}

    def arr(val=float('nan')):
        return np.full(nu, val, dtype=float)

    def panel(key, title, ylabel, values, cl, sd, lcl, ucl, lower_bound=None, upper_bound=None, zones=True, tested=True):
        if lower_bound is not None:
            lcl = np.maximum(lcl, lower_bound)
        if upper_bound is not None:
            ucl = np.minimum(ucl, upper_bound)
        return {'key': key, 'title': title, 'ylabel': ylabel, 'values': np.asarray(values, dtype=float), 'cl': cl, 'sd': sd,
                'lcl': lcl, 'ucl': ucl, 'zones': zones, 'tested': tested}

    for p in phases:
        sel = [i for i in range(nu) if ph[i] == p]
        us = [units[i] for i in sel]
        if not attribute and chart != 'run':
            if method == 'known':
                s_hat = float(known_sigma)
            else:
                s_hat, _nu = within_sigma(us, method, span)
            sig_by_phase[p] = s_hat
            if known_mean is not None:
                center_by_phase[p] = float(known_mean)
            elif chart in ('ewma', 'cusum') and target is not None:
                center_by_phase[p] = float(target)
            else:
                center_by_phase[p] = _grand_mean(us)
    # ---- the panels
    if chart in ('xbar_r', 'xbar_s'):
        mean, cl, sd = arr(), arr(), arr()
        dv, dcl, dsd = arr(), arr(), arr()
        for i, u in enumerate(units):
            n = u['n']
            s_hat = sig_by_phase[u['phase']]
            mean[i] = float(np.mean(u['y']))
            cl[i] = center_by_phase[u['phase']]
            sd[i] = s_hat / math.sqrt(n)
            if n >= 2:
                if chart == 'xbar_r':
                    dv[i] = float(np.ptp(u['y']))
                    dcl[i] = d2(n) * s_hat
                    dsd[i] = d3(n) * s_hat
                else:
                    dv[i] = float(np.std(u['y'], ddof=1))
                    dcl[i] = c4(n) * s_hat
                    dsd[i] = s_hat * math.sqrt(max(0.0, 1 - c4(n) ** 2))
        panels.append(panel('xbar', 'XBar', f'Mean({ylab})', mean, cl, sd, cl - k * sd, cl + k * sd))
        dk = 'r' if chart == 'xbar_r' else 's'
        panels.append(panel(dk, 'R' if dk == 'r' else 'S', f'{"Range" if dk == "r" else "Std Dev"}({ylab})', dv, dcl, dsd,
                            dcl - k * dsd, dcl + k * dsd, lower_bound=0.0, tested=bool(dispersion_tests)))
        if any(u['n'] < 2 for u in units):
            notes.append('Subgroups of one value have no range or standard deviation; they are left out of the sigma estimate and the lower chart.')
    elif chart in ('ir', 'lj'):
        x = np.array([float(u['y'][0]) for u in units])
        cl, sd = arr(), arr()
        for i, u in enumerate(units):
            cl[i] = center_by_phase[u['phase']]
            sd[i] = sig_by_phase[u['phase']]
        panels.append(panel('i', 'Individual', ylab, x, cl, sd, cl - k * sd, cl + k * sd))
        if chart == 'lj':
            notes.append('Levey Jennings: the limits use the overall standard deviation of the values, not the moving range.')
        mr = arr()
        for p in phases:
            sel = [i for i in range(nu) if ph[i] == p]
            m = _moving_ranges(x[sel], span)
            mr[sel] = m
        mcl = np.array([d2(span) * sig_by_phase[u['phase']] for u in units])
        msd = np.array([d3(span) * sig_by_phase[u['phase']] for u in units])
        if chart != 'lj':
            panels.append(panel('mr', 'Moving Range', f'Moving Range({ylab})', mr, mcl, msd, mcl - k * msd, mcl + k * msd, lower_bound=0.0,
                                tested=bool(dispersion_tests)))
    elif chart == 'run':
        x = np.array([float(np.mean(u['y'])) for u in units])
        cl = arr()
        for p in phases:
            sel = [i for i in range(nu) if ph[i] == p]
            cl[sel] = float(np.mean(x[sel]))
        panels.append(panel('run', 'Run Chart', ylab if all(u['n'] == 1 for u in units) else f'Mean({ylab})', x, cl, arr(), arr(), arr(), zones=False))
    elif attribute:
        vals, cl, sd, lcl, ucl = arr(), arr(), arr(), arr(), arr()
        for p in phases:
            sel = [i for i in range(nu) if ph[i] == p]
            tot_c = sum(units[i]['count'] for i in sel)
            tot_n = sum(units[i]['size'] for i in sel)
            if chart in ('p', 'np'):
                pbar = tot_c / tot_n if tot_n > 0 else float('nan')
                center_by_phase[p] = pbar
                for i in sel:
                    n_i = units[i]['size']
                    if chart == 'p':
                        vals[i] = units[i]['count'] / n_i if n_i > 0 else float('nan')
                        cl[i] = pbar
                        sd[i] = math.sqrt(pbar * (1 - pbar) / n_i) if n_i > 0 else float('nan')
                        lcl[i], ucl[i] = max(0.0, cl[i] - k * sd[i]), min(1.0, cl[i] + k * sd[i])
                    else:
                        vals[i] = units[i]['count']
                        cl[i] = n_i * pbar
                        sd[i] = math.sqrt(n_i * pbar * (1 - pbar))
                        lcl[i], ucl[i] = max(0.0, cl[i] - k * sd[i]), min(n_i, cl[i] + k * sd[i])
            else:
                if chart == 'c':
                    cbar = float(np.mean([units[i]['count'] for i in sel]))
                    center_by_phase[p] = cbar
                    for i in sel:
                        vals[i] = units[i]['count']
                        cl[i] = cbar
                        sd[i] = math.sqrt(cbar)
                        lcl[i], ucl[i] = max(0.0, cbar - k * sd[i]), cbar + k * sd[i]
                else:
                    ubar = tot_c / tot_n if tot_n > 0 else float('nan')
                    center_by_phase[p] = ubar
                    for i in sel:
                        n_i = units[i]['size']
                        vals[i] = units[i]['count'] / n_i if n_i > 0 else float('nan')
                        cl[i] = ubar
                        sd[i] = math.sqrt(ubar / n_i) if n_i > 0 else float('nan')
                        lcl[i], ucl[i] = max(0.0, ubar - k * sd[i]), ubar + k * sd[i]
        label = {'p': f'Proportion({ylab})', 'np': f'Count({ylab})', 'c': f'Count({ylab})', 'u': f'Rate({ylab})'}[chart]
        panels.append(panel(chart, chart.upper(), label, vals, cl, sd, lcl, ucl))
        if chart in ('np', 'c') and len({u['size'] for u in units}) > 1:
            notes.append(f'The subgroups differ in size; a{"n" if chart == "np" else ""} {chart.upper()} chart assumes equal sizes. A {"P" if chart == "np" else "U"} chart takes unequal sizes into account.')
    elif chart == 'ewma':
        lam = float(lam)
        if not 0 < lam <= 1:
            return {'error': 'λ must lie in (0, 1]'}
        xbar = np.array([float(np.mean(u['y'])) for u in units])
        z, cl, sd = arr(), arr(), arr()
        for p in phases:
            sel = [i for i in range(nu) if ph[i] == p]
            t0 = center_by_phase[p]
            s_hat = sig_by_phase[p]
            zz, var = t0, 0.0
            for i in sel:
                zz = lam * xbar[i] + (1 - lam) * zz
                var = (1 - lam) ** 2 * var + lam * lam * s_hat * s_hat / units[i]['n']
                z[i], cl[i], sd[i] = zz, t0, math.sqrt(var)
        pn = panel('ewma', 'EWMA', f'EWMA({ylab})', z, cl, sd, cl - float(ewma_l) * sd, cl + float(ewma_l) * sd, zones=False)
        pn['data'] = xbar
        pn['k'] = float(ewma_l)
        panels.append(pn)
    elif chart == 'cusum':
        h, kk = float(cusum_h), float(cusum_k)
        xbar = np.array([float(np.mean(u['y'])) for u in units])
        up, dn, scale = arr(), arr(), arr()
        same_n = len({u['n'] for u in units}) == 1
        for p in phases:
            sel = [i for i in range(nu) if ph[i] == p]
            t0 = center_by_phase[p]
            s_hat = sig_by_phase[p]
            cp_ = cm_ = (h / 2.0 if head_start else 0.0)
            for i in sel:
                se = s_hat / math.sqrt(units[i]['n'])
                zi = (xbar[i] - t0) / se if se > 0 else 0.0
                cp_ = max(0.0, cp_ + zi - kk)
                cm_ = max(0.0, cm_ - zi - kk)
                f = se if same_n else 1.0
                up[i], dn[i], scale[i] = cp_ * f, -cm_ * f, f
        lim = h * scale
        pn = panel('cusum', 'CUSUM', f'CUSUM({ylab})' if same_n else f'CUSUM({ylab}), standardized', up, np.zeros(nu), scale, -lim, lim, zones=False)
        pn['lower'] = dn
        pn['units'] = 'data' if same_n else 'sigma'
        pn['arl'] = {'h': h, 'k': kk, 'in_control': _cusum_arl(kk, h, 0.0), 'shift': 2 * kk, 'at_shift': _cusum_arl(kk, h, 2 * kk)}
        panels.append(pn)
    # ---- tests, on the charts that take them
    nn = _test_n(test_n)
    chosen = sorted({int(t) for t in (tests or [])})
    for pn in panels:
        pn['tests'] = [[] for _ in range(nu)]
        if not chosen:
            continue
        use = chosen if (pn['zones'] and pn['tested']) else ([1] if 1 in chosen else [])
        if pn['key'] == 'run':
            use = [t for t in chosen if t in (2, 3, 4)]
        if pn['key'] in ('r', 's', 'mr') and not pn['tested']:
            use = [1] if 1 in chosen else []
        if not use:
            continue
        flags = [[] for _ in range(nu)]
        for p in phases:
            sel = [i for i in range(nu) if ph[i] == p]
            if pn['key'] == 'cusum':
                f1 = [[1] if (pn['values'][i] > pn['ucl'][i] or pn['lower'][i] < pn['lcl'][i]) else [] for i in sel]
                for i, f in zip(sel, f1):
                    flags[i] = f if 1 in use else []
                continue
            fl = nelson(pn['values'][sel], pn['cl'][sel], pn['sd'][sel], pn['lcl'][sel], pn['ucl'][sel], use, nn, k=(pn.get('k') or k))
            for i, f in zip(sel, fl):
                flags[i] = f
        pn['tests'] = flags
    # ---- limit summaries
    lim_rows = []
    for pn in panels:
        for p in phases:
            sel = [i for i in range(nu) if ph[i] == p]
            ns = sorted({units[i]['size'] if attribute else units[i]['n'] for i in sel})
            one = lambda a: (float(a[sel][0]) if len({round(float(v), 12) for v in a[sel] if np.isfinite(v)}) == 1 else None)
            if pn['key'] == 'ewma' and len(ns) == 1:
                # the limits the EWMA settles to
                s_a = sig_by_phase[p] * math.sqrt(float(lam) / ((2 - float(lam)) * ns[0]))
                c_a = center_by_phase[p]
                one = lambda a, _c=c_a, _s=s_a, _k=pn['k']: (_c - _k * _s) if a is pn['lcl'] else (_c + _k * _s)
            cl_ = pn['cl'][sel]
            finite_cl = cl_[np.isfinite(cl_)]
            lim_rows.append({
                'points': pn['ylabel'], 'phase': phase_labels[p] if p >= 0 and phase_labels else None,
                'lcl': one(pn['lcl']) if pn['key'] != 'run' else None, 'avg': float(finite_cl[0]) if len(finite_cl) and len(set(np.round(finite_cl, 12))) == 1 else (float(np.nanmean(cl_)) if len(finite_cl) else None),
                'ucl': one(pn['ucl']) if pn['key'] != 'run' else None,
                'sigma': ('Binomial' if chart in ('p', 'np') else 'Poisson' if chart in ('c', 'u') else ('' if chart == 'run' else SIGMA_LABEL.get(method, method))),
                'n': (_label(ns[0]) if len(ns) == 1 else f'{_label(ns[0])} to {_label(ns[-1])}'),
            })
    lim_cols = [col('points', 'Points plotted', 'text')]
    if phase_labels:
        lim_cols.append(col('phase', 'Phase', 'text'))
    lim_cols += [col('lcl', 'LCL'), col('avg', 'Avg'), col('ucl', 'UCL'), col('sigma', 'Limits Sigma', 'text'), col('n', 'Subgroup Size', 'text')]
    # ---- the tests table
    t_rows = []
    for pn in panels:
        for i in range(nu):
            if pn['tests'][i]:
                t_rows.append({'chart': pn['title'], 'label': units[i]['label'], 'value': float(pn['values'][i]) if np.isfinite(pn['values'][i]) else (float(pn['lower'][i]) if 'lower' in pn else None),
                               'tests': ', '.join(str(t) for t in pn['tests'][i]), 'n_rows': len(units[i]['rows']), 'index': i})
    # ---- sigma and the summary
    all_y = np.concatenate([u['y'] for u in units])
    overall = float(np.std(all_y, ddof=1)) if len(all_y) > 1 else float('nan')
    summary = {'n_points': nu, 'n_values': int(len(all_y)), 'overall_sd': overall, 'mean': float(np.mean(all_y)),
               'sigma_method': SIGMA_LABEL.get(method, method) if method else None,
               'sigma': [{'phase': phase_labels[p] if p >= 0 and phase_labels else None, 'sigma': sig_by_phase.get(p), 'center': center_by_phase.get(p)} for p in phases]}
    out = {
        'y': y, 'chart': chart, 'chart_label': CHART_LABEL[chart], 'k': k, 'method': method,
        'units': [{'label': u['label'], 'rows': u['rows'], 'n': u['n'], 'size': u.get('size'), 'phase': u['phase']} for u in units],
        'phases': [{'label': phase_labels[p] if p >= 0 and phase_labels else None, 'code': p} for p in phases] if phase_labels else [],
        'panels': panels,
        'limits': rtable(lim_cols, lim_rows),
        'tests_table': rtable([col('chart', 'Chart', 'text'), col('label', 'Subgroup', 'text'), col('value', 'Value'), col('tests', 'Tests Failed', 'text'), col('n_rows', 'Rows', 'int')], t_rows),
        'test_text': {str(t): test_description(t, nn) for t in range(1, 9)},
        'summary': summary, 'notes': notes,
    }
    if spec and (spec.get('lsl') is not None or spec.get('usl') is not None) and not attribute and chart not in ('run',):
        s_w = sig_by_phase.get(phases[-1]) if len(phases) == 1 else None
        if s_w is None or not np.isfinite(s_w):
            s_w, nu_w = within_sigma(units, method if method not in ('known',) else 'mr', span)
        else:
            _s, nu_w = within_sigma(units, method, span) if method != 'known' else (s_w, len(all_y) - 1)
        cap = capability_core(all_y, spec.get('lsl'), spec.get('usl'), spec.get('target'), s_w, nu_w, alpha)
        cap['within_method'] = SIGMA_LABEL.get(method, method)
        if len(phases) > 1:
            cap['note'] = 'With phases, the within sigma pools the whole chart (the phases\' own sigmas are in the Limit Summaries).'
        out['capability'] = cap
    out['code'] = _chart_code(table_name, y, chart, subgroup, phase, n_trials, subgroup_size, method, k, span, lam, ewma_l, cusum_h, cusum_k, known_mean, known_sigma, target)
    return out


def _chart_code(table_name, y, chart, subgroup, phase, n_trials, subgroup_size, method, k, span, lam, ewma_l, h, kk, known_mean, known_sigma, target):
    Y = json.dumps(y)
    lines = [code_head(table_name, [_CONST_CODE])]
    keep = [y] + [c for c in (subgroup, phase, n_trials) if c]
    lines.append(f'df = df.dropna(subset={json.dumps(keep)})')
    if phase:
        lines.append(f'# Phase: every line below runs once per level of {json.dumps(phase)}: for level, df in df.groupby({json.dumps(phase)}): ...')
    if chart in ('ir', 'lj'):
        if subgroup:
            lines.append(f'df = df.sort_values({json.dumps(subgroup)}, kind="stable")')
        lines += [f'x = df[{Y}].to_numpy()', 'mr = np.abs(np.diff(x))' if span == 2 else f'mr = pd.Series(x).rolling({span}).apply(np.ptp).dropna().to_numpy()']
        if known_sigma is not None:
            lines.append(f'sigma = {known_sigma!r}   # given')
        elif chart == 'lj' or method == 'lj':
            lines.append('sigma = x.std(ddof=1)   # Levey Jennings: the overall standard deviation')
        elif method == 'mmr':
            lines.append('sigma = np.median(mr) / (np.sqrt(2) * stats.norm.ppf(0.75))   # median moving range / 0.954')
        else:
            lines.append(f'sigma = mr.mean() / d2({span})   # average moving range / d2')
        lines.append(f'center = {known_mean!r}' if known_mean is not None else 'center = x.mean()')
        lines += [f'print("Individual:", center - {k:g} * sigma, center, center + {k:g} * sigma)',
                  f'print("Moving range:", max(0, d2({span}) * sigma - {k:g} * d3({span}) * sigma), d2({span}) * sigma, d2({span}) * sigma + {k:g} * d3({span}) * sigma)']
        return '\n'.join(lines)
    if subgroup:
        lines.append(f'g = df.groupby({json.dumps(subgroup)}, sort=True)')
    elif subgroup_size:
        lines.append(f'g = df.groupby(np.arange(len(df)) // {int(subgroup_size)})   # consecutive subgroups of {int(subgroup_size)}')
    else:
        lines.append('g = df.groupby(np.arange(len(df)))   # every row its own subgroup')
    if chart in ('p', 'np', 'c', 'u'):
        lines.append(f'count = g[{Y}].sum()')
        lines.append(f'size = g[{json.dumps(n_trials)}].sum()' if n_trials else 'size = g.size()   # the rows in each subgroup')
        if chart in ('p', 'np'):
            lines += ['pbar = count.sum() / size.sum()', 'sd = np.sqrt(pbar * (1 - pbar) / size)']
            if chart == 'p':
                lines.append(f'print(pd.DataFrame({{"p": count / size, "LCL": np.maximum(0, pbar - {k:g} * sd), "CL": pbar, "UCL": np.minimum(1, pbar + {k:g} * sd)}}))')
            else:
                lines.append(f'print(pd.DataFrame({{"np": count, "LCL": np.maximum(0, size * (pbar - {k:g} * sd)), "CL": size * pbar, "UCL": size * (pbar + {k:g} * sd)}}))')
        elif chart == 'c':
            lines.append(f'cbar = count.mean(); print(max(0, cbar - {k:g} * np.sqrt(cbar)), cbar, cbar + {k:g} * np.sqrt(cbar))')
        else:
            lines.append(f'ubar = count.sum() / size.sum(); sd = np.sqrt(ubar / size); print(pd.DataFrame({{"u": count / size, "LCL": np.maximum(0, ubar - {k:g} * sd), "CL": ubar, "UCL": ubar + {k:g} * sd}}))')
        return '\n'.join(lines)
    lines += [f'n, xbar = g[{Y}].size(), g[{Y}].mean()', f'r, s = g[{Y}].max() - g[{Y}].min(), g[{Y}].std(ddof=1)']
    if known_sigma is not None:
        lines.append(f'sigma = {known_sigma!r}   # given')
    elif method == 'std':
        lines.append('sigma = (s / n.map(c4)).mean()   # the mean of s_i / c4(n_i)')
    elif method == 'pooled':
        lines.append('dof = (n - 1).sum(); sigma = np.sqrt(((n - 1) * s ** 2).sum() / dof) / c4(dof + 1)')
    elif method in ('mr', 'mmr'):
        lines.append('sigma = np.abs(np.diff(xbar)).mean() / d2(2)   # moving range of the subgroup means')
    elif method == 'lj':
        lines.append(f'sigma = df[{Y}].std(ddof=1)')
    else:
        lines.append('sigma = (r / n.map(d2)).mean()   # the mean of R_i / d2(n_i)')
    lines.append(f'center = {known_mean!r}' if known_mean is not None else (f'center = {target!r}' if (target is not None and chart in ('ewma', 'cusum')) else f'center = df[{Y}].mean()'))
    if chart in ('xbar_r', 'xbar_s'):
        lines.append(f'print(pd.DataFrame({{"XBar": xbar, "LCL": center - {k:g} * sigma / np.sqrt(n), "UCL": center + {k:g} * sigma / np.sqrt(n)}}))')
        if chart == 'xbar_r':
            lines.append(f'print(pd.DataFrame({{"R": r, "LCL": np.maximum(0, (n.map(d2) - {k:g} * n.map(d3)) * sigma), "CL": n.map(d2) * sigma, "UCL": (n.map(d2) + {k:g} * n.map(d3)) * sigma}}))')
        else:
            lines.append(f'c = n.map(c4); print(pd.DataFrame({{"S": s, "LCL": np.maximum(0, (c - {k:g} * np.sqrt(1 - c ** 2)) * sigma), "CL": c * sigma, "UCL": (c + {k:g} * np.sqrt(1 - c ** 2)) * sigma}}))')
    elif chart == 'ewma':
        lines += [f'lam, L = {float(lam)!r}, {float(ewma_l)!r}', 'z, var, out = center, 0.0, []',
                  'for m, k in zip(xbar, n):',
                  '    z = lam * m + (1 - lam) * z; var = (1 - lam) ** 2 * var + lam ** 2 * sigma ** 2 / k',
                  '    out.append((z, center - L * np.sqrt(var), center + L * np.sqrt(var)))',
                  'print(pd.DataFrame(out, columns=["EWMA", "LCL", "UCL"], index=xbar.index))']
    elif chart == 'cusum':
        lines += [f'h, k = {float(h)!r}, {float(kk)!r}   # in standard errors of the subgroup mean', 'z = (xbar - center) / (sigma / np.sqrt(n))',
                  'up, lo, cp, cm = [], [], 0.0, 0.0', 'for zi in z:', '    cp = max(0, cp + zi - k); cm = max(0, cm - zi - k); up.append(cp); lo.append(-cm)',
                  'se = sigma / np.sqrt(n)   # back to the units of the data (equal subgroups)',
                  'print(pd.DataFrame({"C+": np.array(up) * se, "C-": np.array(lo) * se, "H": h * se, "signal": np.maximum(up, np.abs(lo)) > h}, index=xbar.index))']
    elif chart == 'run':
        lines.append('print(xbar, xbar.mean())')
    return '\n'.join(lines)


@api('quality.runs_test')
def runs_test(table, y, rows=None, subgroup=None):
    """The runs test about the median of a run chart's points (statsmodels'
    runstest_1samp): too few runs means clustering or a trend, too many
    means mixing or oscillation."""
    from statsmodels.sandbox.stats.runs import runstest_1samp
    units, _ = _units(table, y, rows, subgroup)
    x = np.array([float(np.mean(u['y'])) for u in units])
    if len(x) < 5:
        return {'error': 'too few points for a runs test'}
    med = float(np.median(x))
    z, p = runstest_1samp(x, cutoff=med, correction=True)
    above = x > med
    keep = x != med
    runs = 1 + int(np.sum(above[keep][1:] != above[keep][:-1])) if keep.sum() > 1 else 0
    n1, n2 = int(np.sum(x > med)), int(np.sum(x < med))
    expected = 1 + 2 * n1 * n2 / (n1 + n2) if n1 + n2 else float('nan')
    return {'median': med, 'runs': runs, 'expected': expected, 'z': float(z), 'p': float(p),
            'p_clustering': float(stats.norm.cdf(z)), 'p_mixtures': float(stats.norm.sf(z)), 'n_above': n1, 'n_below': n2,
            'code': '\n'.join([code_head('data', ['from statsmodels.sandbox.stats.runs import runstest_1samp']),
                               f'x = df[{json.dumps(y)}].dropna()' + (f'.groupby(df[{json.dumps(subgroup)}]).mean()' if subgroup else ''),
                               'print(runstest_1samp(x, cutoff=np.median(x), correction=True))   # z, p (two-sided)'])}


# ---------------------------------------------------------------------------
# Process capability
# ---------------------------------------------------------------------------

def _nct_interval(t_obs, df, alpha):
    """The confidence interval of the noncentrality of a noncentral t from
    one observation t_obs (the Chou-Owen interval of Cpl and Cpu)."""
    lo_p, hi_p = 1 - alpha / 2, alpha / 2
    spread = math.sqrt(1 + t_obs * t_obs / (2 * df))   # the normal approximation's standard error

    def root(p, sign):
        f = lambda d: stats.nct.cdf(t_obs, df, d) - p
        for width in (4, 8, 16, 32):
            a, b = (t_obs - width * spread, t_obs) if sign < 0 else (t_obs, t_obs + width * spread)
            fa, fb = f(a), f(b)
            if np.isfinite(fa) and np.isfinite(fb) and fa * fb < 0:
                return optimize.brentq(f, a, b, xtol=1e-10)
        return float('nan')
    return root(lo_p, -1), root(hi_p, 1)


def capability_core(x, lsl, usl, target, s_within, nu_within, alpha=0.05, dist='normal'):
    """Capability of the values x with the spec limits, a within sigma (and
    its effective degrees of freedom) and the overall standard deviation."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return {'error': 'fewer than three values'}
    lsl = None if lsl is None else float(lsl)
    usl = None if usl is None else float(usl)
    target = None if target is None else float(target)
    if lsl is None and usl is None:
        return {'error': 'give at least one specification limit'}
    if lsl is not None and usl is not None and not lsl < usl:
        return {'error': 'the lower spec limit must be below the upper'}
    mean = float(np.mean(x))
    s = float(np.std(x, ddof=1))
    z = float(stats.norm.ppf(1 - alpha / 2))
    out = {'n': n, 'mean': mean, 'sd_overall': s, 'sd_within': s_within, 'nu_within': nu_within, 'lsl': lsl, 'usl': usl,
           'target': target, 'alpha': alpha, 'min': float(np.min(x)), 'max': float(np.max(x)),
           'stability': s / s_within if s_within and np.isfinite(s_within) and s_within > 0 else None}

    def indices(sig, nu, names):
        rows = []
        if not (sig and np.isfinite(sig) and sig > 0):
            return rows
        cp_name, cpk_name, cpl_name, cpu_name = names
        nu = float(nu) if nu and np.isfinite(nu) and nu > 0 else n - 1.0
        cpl = (mean - lsl) / (3 * sig) if lsl is not None else None
        cpu = (usl - mean) / (3 * sig) if usl is not None else None
        if lsl is not None and usl is not None:
            cp = (usl - lsl) / (6 * sig)
            rows.append({'index': cp_name, 'estimate': cp, 'lower': cp * math.sqrt(stats.chi2.ppf(alpha / 2, nu) / nu),
                         'upper': cp * math.sqrt(stats.chi2.ppf(1 - alpha / 2, nu) / nu)})
        cpk = min(v for v in (cpl, cpu) if v is not None)
        se = math.sqrt(1 / (9 * n) + cpk * cpk / (2 * nu))
        rows.append({'index': cpk_name, 'estimate': cpk, 'lower': cpk - z * se, 'upper': cpk + z * se})
        for name, v in ((cpl_name, cpl), (cpu_name, cpu)):
            if v is None:
                continue
            lo, hi = _nct_interval(3 * math.sqrt(n) * v, nu, alpha)
            rows.append({'index': name, 'estimate': v, 'lower': lo / (3 * math.sqrt(n)), 'upper': hi / (3 * math.sqrt(n))})
        return rows

    def expected(sig):
        if not (sig and np.isfinite(sig) and sig > 0):
            return None
        below = float(stats.norm.cdf((lsl - mean) / sig)) if lsl is not None else 0.0
        above = float(stats.norm.sf((usl - mean) / sig)) if usl is not None else 0.0
        return {'below': below, 'above': above, 'total': below + above}

    obs_b = float(np.mean(x < lsl)) if lsl is not None else 0.0
    obs_a = float(np.mean(x > usl)) if usl is not None else 0.0
    out['observed'] = {'below': obs_b, 'above': obs_a, 'total': obs_b + obs_a, 'n_below': int(np.sum(x < lsl)) if lsl is not None else 0, 'n_above': int(np.sum(x > usl)) if usl is not None else 0}
    if dist == 'normal':
        out['dist'] = 'normal'
        out['within'] = indices(s_within, nu_within, ('Cp', 'Cpk', 'Cpl', 'Cpu'))
        ov = indices(s, n - 1, ('Pp', 'Ppk', 'Ppl', 'Ppu'))
        if target is not None and lsl is not None and usl is not None:
            dd = (mean - target) / s if s > 0 else 0.0
            cpm = min(target - lsl, usl - target) / (3 * math.sqrt(s * s + (mean - target) ** 2))
            nu_m = n * (1 + dd * dd) ** 2 / (1 + 2 * dd * dd)
            ov.append({'index': 'Cpm', 'estimate': cpm, 'lower': cpm * math.sqrt(stats.chi2.ppf(alpha / 2, nu_m) / nu_m),
                       'upper': cpm * math.sqrt(stats.chi2.ppf(1 - alpha / 2, nu_m) / nu_m)})
        out['overall'] = ov
        out['expected_within'] = expected(s_within)
        out['expected_overall'] = expected(s)
    else:
        fit = _fit_nonnormal(x, dist)
        if 'error' in fit:
            return {**out, 'error': fit['error']}
        out['dist'] = fit['dist']
        out['fit'] = {k: v for k, v in fit.items() if k not in ('frozen',)}
        fr = fit['frozen']
        p_lo, p50, p_hi = (float(fr.ppf(q)) for q in (0.00135, 0.5, 0.99865))
        out['percentiles'] = {'p00135': p_lo, 'p50': p50, 'p99865': p_hi}
        ov = []
        ppl = (p50 - lsl) / (p50 - p_lo) if lsl is not None else None
        ppu = (usl - p50) / (p_hi - p50) if usl is not None else None
        if lsl is not None and usl is not None:
            ov.append({'index': 'Pp', 'estimate': (usl - lsl) / (p_hi - p_lo), 'lower': None, 'upper': None})
        ov.append({'index': 'Ppk', 'estimate': min(v for v in (ppl, ppu) if v is not None), 'lower': None, 'upper': None})
        if ppl is not None:
            ov.append({'index': 'Ppl', 'estimate': ppl, 'lower': None, 'upper': None})
        if ppu is not None:
            ov.append({'index': 'Ppu', 'estimate': ppu, 'lower': None, 'upper': None})
        out['overall'] = ov
        out['within'] = []
        below = float(fr.cdf(lsl)) if lsl is not None else 0.0
        above = float(fr.sf(usl)) if usl is not None else 0.0
        out['expected_overall'] = {'below': below, 'above': above, 'total': below + above}
        out['expected_within'] = None
        lo_, hi_ = float(np.min(x)), float(np.max(x))
        span = hi_ - lo_ if hi_ > lo_ else abs(hi_) + 1
        a = max(lo_ - 0.2 * span, 1e-9 if fit['dist'] != 'normal' else lo_ - 0.2 * span)
        g = np.linspace(a, hi_ + 0.2 * span, 200)
        out['curve'] = {'x': g, 'pdf': fr.pdf(g)}
    # the goal plot's coordinates: spec-normalised mean and standard deviation
    if lsl is not None and usl is not None:
        tt = target if target is not None else (lsl + usl) / 2
        w = usl - lsl
        out['goal'] = {'x': (mean - tt) / w, 'y_overall': s / w, 'y_within': (s_within / w) if s_within and np.isfinite(s_within) else None}
    return out


def _fit_nonnormal(x, dist):
    """A distribution fitted by maximum likelihood (scipy), the threshold at
    zero; 'best' picks the smallest AICc of normal, lognormal, Weibull, gamma."""
    fams = {
        'normal': ('Normal', lambda v: stats.norm(*stats.norm.fit(v)), 2, True),
        'lognormal': ('Lognormal', lambda v: (lambda s, loc, sc: stats.lognorm(s, loc=0, scale=sc))(*stats.lognorm.fit(v, floc=0)), 2, bool(np.all(x > 0))),
        'weibull': ('Weibull', lambda v: (lambda c, loc, sc: stats.weibull_min(c, loc=0, scale=sc))(*stats.weibull_min.fit(v, floc=0)), 2, bool(np.all(x > 0))),
        'gamma': ('Gamma', lambda v: (lambda a, loc, sc: stats.gamma(a, loc=0, scale=sc))(*stats.gamma.fit(v, floc=0)), 2, bool(np.all(x > 0))),
    }
    n = len(x)
    if dist == 'best':
        best = None
        cands = []
        for key, (label, make, kp, ok) in fams.items():
            if not ok:
                continue
            try:
                fr = make(x)
                ll = float(np.sum(fr.logpdf(x)))
            except Exception:
                continue
            aicc = -2 * ll + 2 * kp + (2 * kp * (kp + 1) / (n - kp - 1) if n - kp - 1 > 0 else 0)
            cands.append({'dist': key, 'label': label, 'aicc': aicc})
            if best is None or aicc < best[0]:
                best = (aicc, key)
        if best is None:
            return {'error': 'no distribution could be fitted'}
        r = _fit_nonnormal(x, best[1])
        r['compared'] = sorted(cands, key=lambda c: c['aicc'])
        r['best'] = True
        return r
    if dist not in fams:
        return {'error': f'unknown distribution {dist}'}
    label, make, kp, ok = fams[dist]
    if not ok:
        return {'error': f'a {label} fit needs every value above zero'}
    fr = make(x)
    params = {'normal': lambda: {'μ': float(fr.mean()), 'σ': float(fr.std())},
              'lognormal': lambda: {'μ (log scale)': float(np.log(fr.kwds.get('scale', fr.args[-1] if fr.args else 1))), 'σ (log shape)': float(fr.args[0])},
              'weibull': lambda: {'α (scale)': float(fr.kwds['scale']), 'β (shape)': float(fr.args[0])},
              'gamma': lambda: {'α (shape)': float(fr.args[0]), 'σ (scale)': float(fr.kwds['scale'])}}[dist]()
    ll = float(np.sum(fr.logpdf(x)))
    return {'dist': dist, 'label': label, 'params': params, 'loglik': ll,
            'aicc': -2 * ll + 2 * kp + (2 * kp * (kp + 1) / (n - kp - 1) if n - kp - 1 > 0 else 0), 'frozen': fr}


@api('quality.capability')
def capability(table, columns, rows=None, specs=None, subgroup=None, within=None, dist=None, alpha=0.05, mr_span=2,
               historical=None, table_name='data'):
    """Process Capability of several columns. specs: {column: {lsl, target,
    usl}}; within: the within-sigma method ('range', 'std', 'pooled' with a
    subgroup; 'mr', 'mmr' without); dist: {column: 'normal' | 'lognormal' |
    'weibull' | 'gamma' | 'best'}; historical: {column: sigma}."""
    specs = specs or {}
    dist = dist or {}
    historical = historical or {}
    out = []
    for c in columns:
        sp = specs.get(c) or {}
        units, _ = _units(table, c, rows, subgroup)
        x = np.concatenate([u['y'] for u in units]) if units else np.array([])
        rowsx = [r for u in units for r in u['rows']]
        method = within or ('range' if subgroup else 'mr')
        if subgroup and method in ('mr', 'mmr'):
            method = 'range'
        if not subgroup and method in ('range', 'std', 'pooled'):
            method = 'mr'
        if historical.get(c):
            s_w, nu_w, label = float(historical[c]), float('inf'), 'Historical'
        else:
            s_w, nu_w = within_sigma(units, method, mr_span) if units else (float('nan'), float('nan'))
            label = {'range': 'Average of Ranges', 'std': 'Average of Unbiased Standard Deviations', 'pooled': 'Pooled Unbiased Standard Deviation',
                     'mr': 'Average of Moving Ranges', 'mmr': 'Median of Moving Ranges'}[method]
        r = capability_core(x, sp.get('lsl'), sp.get('usl'), sp.get('target'), s_w, nu_w if np.isfinite(nu_w) else 1e9, alpha, dist.get(c, 'normal'))
        r['column'] = c
        r['within_method'] = label
        r['n_subgroups'] = len(units) if subgroup else None
        r['subgroup_sizes'] = sorted({u['n'] for u in units}) if subgroup else None
        r['rows'] = rowsx
        out.append(r)
    code = [code_head(table_name, ['from scipy import stats', _CONST_CODE])]
    for r in out:
        c = r['column']
        code.append(f'x = df[{json.dumps(c)}].dropna()')
        if subgroup:
            code.append(f'g = df.dropna(subset=[{json.dumps(c)}]).groupby({json.dumps(subgroup)})[{json.dumps(c)}]; n = g.size()')
            code.append({'range': 'sw = ((g.max() - g.min()) / n.map(d2)).mean()', 'std': 'sw = (g.std(ddof=1) / n.map(c4)).mean()',
                         'pooled': 'dof = (n - 1).sum(); sw = np.sqrt(((n - 1) * g.var(ddof=1)).sum() / dof) / c4(dof + 1)'}.get(within or 'range', 'sw = ((g.max() - g.min()) / n.map(d2)).mean()'))
        else:
            code.append('sw = np.abs(np.diff(x)).mean() / d2(2)   # average moving range / 1.128' if (within or 'mr') == 'mr' else 'sw = np.median(np.abs(np.diff(x))) / (np.sqrt(2) * stats.norm.ppf(0.75))')
        code.append('m, so = x.mean(), x.std(ddof=1)')
        if r.get('lsl') is not None and r.get('usl') is not None:
            code.append(f'lsl, usl = {r["lsl"]!r}, {r["usl"]!r}; print("Cp", (usl - lsl) / (6 * sw), "Cpk", min(usl - m, m - lsl) / (3 * sw), "Pp", (usl - lsl) / (6 * so), "Ppk", min(usl - m, m - lsl) / (3 * so))')
        elif r.get('lsl') is not None:
            code.append(f'lsl = {r["lsl"]!r}; print("Cpl", (m - lsl) / (3 * sw), "Ppl", (m - lsl) / (3 * so))')
        elif r.get('usl') is not None:
            code.append(f'usl = {r["usl"]!r}; print("Cpu", (usl - m) / (3 * sw), "Ppu", (usl - m) / (3 * so))')
        if r.get('dist') not in (None, 'normal'):
            sc = {'lognormal': 'lognorm', 'weibull': 'weibull_min', 'gamma': 'gamma'}[r['dist']]
            code.append(f'f = stats.{sc}(*stats.{sc}.fit(x, floc=0)); p = f.ppf([0.00135, 0.5, 0.99865])   # the percentile method')
    return {'columns': out, 'code': '\n'.join(code)}


# ---------------------------------------------------------------------------
# Pareto Plot
# ---------------------------------------------------------------------------

@api('quality.pareto')
def pareto(table, cause, rows=None, freq=None, groups=None, combine=None, table_name='data'):
    """Counts of each cause, largest first, with percents and the cumulative
    percent; the rows of each cause for linking; the same per level of the
    X, Grouping columns, and a test that the rates are equal across the
    groups (a Poisson log-linear model, statsmodels' GLM)."""
    groups = [g for g in (groups or []) if g]
    names = [cause] + groups + ([freq] if freq else [])
    df = data.frame(table, names, rows, dropna=True, as_category=True)
    if freq:
        w = data.series(table, freq, df.index, as_category=False).to_numpy(float)
        keep = np.isfinite(w) & (w > 0)
        df, w = df[keep], w[keep]
    else:
        w = np.ones(len(df))
    if not len(df):
        return {'error': 'no rows with a cause'}
    cs = df[cause]
    if isinstance(cs.dtype, pd.CategoricalDtype):
        levels = [lv for lv in cs.cat.categories]
        codes = cs.cat.codes.to_numpy()
    else:
        levels = sorted(pd.unique(cs.dropna()))
        m = {v: i for i, v in enumerate(levels)}
        codes = np.array([m[v] for v in cs])
    labels = [_label(v) for v in levels]
    counts = np.bincount(codes, weights=w, minlength=len(levels)).astype(float)
    idx = df.index.to_numpy()
    members = [[] for _ in levels]
    for r, cde in zip(idx, codes):
        members[cde].append(int(r))
    present = [i for i in range(len(levels)) if counts[i] > 0]
    order = sorted(present, key=lambda i: (-counts[i], i))
    total = float(counts.sum())
    combined = []
    if combine and combine.get('below') is not None:
        thr = float(combine['below']) / 100.0
        small = [i for i in order if counts[i] / total < thr]
        if len(small) >= 2:
            combined = small
    elif combine and combine.get('top'):
        top = int(combine['top'])
        if len(order) > top + 1:
            combined = order[top:]
    causes = []
    cum = 0.0
    keep_order = [i for i in order if i not in combined]
    for i in keep_order:
        cum += counts[i]
        causes.append({'cause': labels[i], 'level': i, 'count': counts[i], 'percent': counts[i] / total, 'cum': cum / total, 'rows': members[i]})
    if combined:
        c_ = float(sum(counts[i] for i in combined))
        cum += c_
        causes.append({'cause': 'Other', 'level': None, 'count': c_, 'percent': c_ / total, 'cum': cum / total,
                       'rows': sorted(r for i in combined for r in members[i]), 'combined': [labels[i] for i in combined]})
    out = {'cause': cause, 'total': total, 'n_rows': int(len(df)), 'causes': causes,
           'table': rtable([col('cause', 'Cause', 'text'), col('count', 'Count'), col('percent', 'Percent', 'pct'), col('cum', 'Cum Percent', 'pct')], [
               {k: v for k, v in c.items() if k in ('cause', 'count', 'percent', 'cum')} for c in causes])}
    # ---- by the grouping columns
    if groups:
        gcodes = []
        glabels = []
        for g in groups:
            s = df[g]
            if isinstance(s.dtype, pd.CategoricalDtype):
                gcodes.append(s.cat.codes.to_numpy())
                glabels.append([_label(v) for v in s.cat.categories])
            else:
                u = sorted(pd.unique(s))
                mm = {v: i for i, v in enumerate(u)}
                gcodes.append(np.array([mm[v] for v in s]))
                glabels.append([_label(v) for v in u])
        cell_key = list(zip(*gcodes))
        cells = sorted(set(cell_key))
        pos = {c: i for i, c in enumerate(cells)}
        cause_pos = {c['level']: j for j, c in enumerate(causes) if c['level'] is not None}
        other_j = len(causes) - 1 if combined else None
        grid = np.zeros((len(cells), len(causes)))
        grows = [[[] for _ in causes] for _ in cells]
        for r, cde, key, wt in zip(idx, codes, cell_key, w):
            j = cause_pos.get(cde, other_j)
            if j is None:
                continue
            grid[pos[key], j] += wt
            grows[pos[key]][j].append(int(r))
        out['groups'] = [{'label': ', '.join(glabels[k][c[k]] for k in range(len(groups))), 'levels': [glabels[k][c[k]] for k in range(len(groups))],
                          'counts': grid[i], 'rows': grows[i], 'total': float(grid[i].sum())} for i, c in enumerate(cells)]
        out['group_names'] = groups
        # Test Rates Across Groups: counts ~ cause + group against the saturated model
        out['test'] = _rates_test(grid)
    out['code'] = '\n'.join([code_head(table_name),
                             (f'counts = df.groupby({json.dumps(cause)})[{json.dumps(freq)}].sum()' if freq else f'counts = df[{json.dumps(cause)}].value_counts()') + '.sort_values(ascending=False, kind="stable")',
                             'pareto = pd.DataFrame({"Count": counts, "Percent": 100 * counts / counts.sum(), "Cum Percent": 100 * counts.cumsum() / counts.sum()})',
                             'print(pareto)'] + ([
                                 '# Test Rates Across Groups: a Poisson log-linear model without the cause-by-group interaction',
                                 f'cells = df.groupby([{json.dumps(cause)}, {json.dumps(groups[0])}], observed=True)' + (f'[{json.dumps(freq)}].sum()' if freq else '.size()') + '.rename("n").reset_index()',
                                 f'fit = smf.glm({"n ~ C(Q(" + json.dumps(cause) + ")) + C(Q(" + json.dumps(groups[0]) + "))"!r}, cells, family=sm.families.Poisson()).fit()',
                                 'print(fit.deviance, fit.df_resid)   # the likelihood-ratio chi-square and its degrees of freedom'] if groups else []))
    return out


def _rates_test(grid):
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    g = np.asarray(grid, dtype=float)
    r, c = g.shape
    if r < 2 or c < 2:
        return None
    keep_r = g.sum(axis=1) > 0
    keep_c = g.sum(axis=0) > 0
    g = g[keep_r][:, keep_c]
    r, c = g.shape
    if r < 2 or c < 2:
        return None
    cells = pd.DataFrame([(i, j, g[i, j]) for i in range(r) for j in range(c)], columns=['grp', 'cause', 'n'])
    fit = smf.glm('n ~ C(grp) + C(cause)', cells, family=sm.families.Poisson()).fit()
    lr, df_ = float(fit.deviance), int(fit.df_resid)
    exp = np.outer(g.sum(axis=1), g.sum(axis=0)) / g.sum()
    pearson = float(np.sum((g - exp) ** 2 / exp))
    return {'lr': lr, 'pearson': pearson, 'df': df_, 'p_lr': float(stats.chi2.sf(lr, df_)), 'p_pearson': float(stats.chi2.sf(pearson, df_)),
            'min_expected': float(exp.min())}


# ---------------------------------------------------------------------------
# Variability Chart and Gauge R&R
# ---------------------------------------------------------------------------

def _terms(factors, model):
    """The random terms of a model: (label, cell factor set) pairs, in order."""
    k = len(factors)
    if k == 0:
        return []
    if model == 'main' or k == 1:
        return [(f, (f,)) for f in factors]
    if model == 'nested':
        out = []
        for i in range(k):
            f = factors[i]
            label = f if i == 0 else f'{f}[{",".join(factors[:i])}]'
            out.append((label, tuple(factors[:i + 1])))
        return out
    if model == 'crossed_nested' and k >= 3:
        a, b = factors[0], factors[1]
        out = [(a, (a,)), (b, (b,)), (f'{a}*{b}', (a, b))]
        for i in range(2, k):
            f = factors[i]
            out.append((f'{f}[{",".join(factors[:i])}]', tuple(factors[:i + 1])))
        return out
    if model == 'nested_crossed' and k == 3:
        a, b, c = factors
        return [(a, (a,)), (f'{b}[{a}]', (a, b)), (c, (c,)), (f'{a}*{c}', (a, c)), (f'{b}*{c}[{a}]', (a, b, c))]
    # crossed: every subset
    out = []
    for r in range(1, k + 1):
        for combo in itertools.combinations(factors, r):
            out.append(('*'.join(combo), tuple(combo)))
    return out


def _balanced(df, factors, terms):
    for _label_, fs in terms:
        cnt = df.groupby(list(fs), observed=True).size()
        if cnt.nunique() != 1:
            return False
    # crossed terms must have every combination
    for label_, fs in terms:
        if '[' in label_:
            continue
        if len(fs) > 1:
            n_cells = df.groupby(list(fs), observed=True).ngroups
            if n_cells != int(np.prod([df[f].nunique() for f in fs])):
                return False
    return True


def _ems(df, y, factors, terms):
    """ANOVA variance components for a balanced random-effects design: the
    sums of squares from statsmodels (OLS, anova_lm with sequential sums,
    which for balanced data are the same as Type II and III), the expected
    mean squares E[MS_T] = sigma^2 + sum over the terms U containing T of
    c_U sigma^2_U, c_U the observations per cell of U, solved top down."""
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    alias = {f: f'f{i}' for i, f in enumerate(factors)}
    d = pd.DataFrame({alias[f]: df[f].astype(str) for f in factors})
    d['y'] = df[y].to_numpy(float)
    parts = []
    for label_, fs in terms:
        parts.append(':'.join(f'C({alias[f]})' for f in fs))
    fit = smf.ols('y ~ ' + ' + '.join(parts), d).fit()
    a = sm.stats.anova_lm(fit, typ=1)
    names = list(a.index)
    n = len(d)
    rows = []
    ms = {}
    dfs = {}
    for (label_, fs), term in zip(terms, parts):
        # patsy may name the term with its factors in another order
        hit = [nm for nm in names if sorted(nm.split(':')) == sorted(term.split(':'))]
        if not hit:
            raise ValueError(f'the term {label_} is not estimable in this design')
        r = a.loc[hit[0]]
        ms[label_] = float(r['mean_sq'])
        dfs[label_] = float(r['df'])
        rows.append({'source': label_, 'df': float(r['df']), 'ss': float(r['sum_sq']), 'ms': float(r['mean_sq'])})
    e = a.loc['Residual']
    mse, dfe = float(e['mean_sq']), float(e['df'])
    cells = {label_: n / d.groupby([alias[f] for f in fs], observed=True).ngroups for label_, fs in terms}
    contains = {t: [u for u, us in terms if set(dict(terms)[t]) <= set(us)] for t, _ in terms}
    unbounded = {}
    # solve from the terms with the largest cell sets down; negative estimates
    # are set to zero afterwards (the others use the unbounded ones)
    for t, fs in sorted(terms, key=lambda tt: -len(tt[1])):
        rest = sum(cells[u] * unbounded[u] for u in contains[t] if u != t and u in unbounded)
        unbounded[t] = (ms[t] - mse - rest) / cells[t]
    comp = {t: max(0.0, v) for t, v in unbounded.items()}
    # F tests where one mean square is the right denominator
    for rr in rows:
        t = rr['source']
        target = [u for u in contains[t] if u != t]
        denom = None
        if not target:
            denom = ('Within', mse, dfe)
        else:
            # the denominator is the MS of a term whose EMS is E[MS_t] minus t's own part
            for u in target:
                if set(contains[u]) == set(target):
                    denom = (u, ms[u], dfs[u])
        if denom and denom[2] > 0 and denom[1] > 0:
            rr['f'] = rr['ms'] / denom[1]
            rr['p'] = float(stats.f.sf(rr['f'], rr['df'], denom[2]))
            rr['denominator'] = denom[0]
    rows.append({'source': 'Within', 'df': dfe, 'ss': float(e['sum_sq']), 'ms': mse})
    rows.append({'source': 'Total', 'df': float(n - 1), 'ss': float(np.sum((d['y'] - d['y'].mean()) ** 2)), 'ms': None})
    return comp, mse, rows, unbounded, dfe


def _reml(df, y, factors, terms):
    """REML variance components from statsmodels' MixedLM: one group, every
    random term a variance component (crossed or nested alike)."""
    import statsmodels.formula.api as smf
    alias = {f: f'f{i}' for i, f in enumerate(factors)}
    d = pd.DataFrame({alias[f]: df[f].astype(str) for f in factors})
    d['y'] = df[y].to_numpy(float)
    vc = {}
    keys = {}
    for i, (label_, fs) in enumerate(terms):
        key = f'v{i}'
        vc[key] = '0 + ' + ':'.join(f'C({alias[f]})' for f in fs)
        keys[key] = label_
    md = smf.mixedlm('y ~ 1', d, groups=np.ones(len(d)), re_formula='0', vc_formula=vc)
    res = md.fit(reml=True)
    comp = {}
    names = md.exog_vc.names
    for nm, v in zip(names, np.asarray(res.vcomp, dtype=float)):
        comp[keys[nm]] = float(v)
    se = {}
    try:
        b = res.bse
        for nm in names:
            key = f'{nm} Var'
            if key in b.index:
                se[keys[nm]] = float(b[key]) * float(res.scale)
    except Exception:
        pass
    return comp, float(res.scale), se, bool(res.converged)


@api('quality.variability')
def variability(table, y, xs, rows=None, part=None, model=None, method='best', gauge=False, k_mult=6.0, tolerance=None,
                lsl=None, usl=None, historical_sigma=None, components=True, table_name='data'):
    """The cells of a variability chart (every combination of the X levels,
    outer to inner) with their means, standard deviations and ranges, the
    variance components, and the Gauge R&R."""
    factors = list(dict.fromkeys([x for x in xs if x] + ([part] if part and part not in xs else [])))
    if not factors:
        return {'error': 'give at least one X, Grouping column'}
    df = data.frame(table, [y] + factors, rows, dropna=True, as_category=True)
    df = df.copy()
    df[y] = df[y].astype(float)
    if len(df) < 2:
        return {'error': 'fewer than two rows with every value'}
    codes, labels = [], []
    for f in factors:
        s = df[f]
        if isinstance(s.dtype, pd.CategoricalDtype):
            s = s.cat.remove_unused_categories()
            codes.append(s.cat.codes.to_numpy())
            labels.append([_label(v) for v in s.cat.categories])
        else:
            u = sorted(pd.unique(s))
            m = {v: i for i, v in enumerate(u)}
            codes.append(np.array([m[v] for v in s]))
            labels.append([_label(v) for v in u])
    key = list(zip(*codes))
    cells_keys = sorted(set(key))
    pos = {c: i for i, c in enumerate(cells_keys)}
    yv = df[y].to_numpy(float)
    idx = df.index.to_numpy()
    members = [[] for _ in cells_keys]
    vals = [[] for _ in cells_keys]
    for r, kk, v in zip(idx, key, yv):
        members[pos[kk]].append(int(r))
        vals[pos[kk]].append(v)
    cells = []
    for i, ck in enumerate(cells_keys):
        v = np.asarray(vals[i])
        cells.append({'levels': [labels[j][ck[j]] for j in range(len(factors))], 'codes': list(ck), 'rows': members[i], 'n': len(v),
                      'mean': float(np.mean(v)), 'sd': float(np.std(v, ddof=1)) if len(v) > 1 else None,
                      'range': float(np.ptp(v)) if len(v) > 1 else None, 'min': float(np.min(v)), 'max': float(np.max(v))})
    out = {'y': y, 'factors': factors, 'labels': labels, 'cells': cells, 'grand_mean': float(np.mean(yv)), 'grand_median': float(np.median(yv)),
           'n': int(len(yv))}
    # group means of the outer factors (every prefix)
    gm = []
    for depth in range(1, len(factors)):
        sub = {}
        for i, ck in enumerate(cells_keys):
            sub.setdefault(ck[:depth], []).append(i)
        for pk, members_ in sub.items():
            vv = np.concatenate([np.asarray(vals[i]) for i in members_])
            gm.append({'depth': depth, 'levels': [labels[j][pk[j]] for j in range(depth)], 'first': members_[0], 'last': members_[-1], 'mean': float(np.mean(vv))})
    out['group_means'] = gm
    sds = [c['sd'] for c in cells if c['sd'] is not None]
    out['mean_sd'] = float(np.mean(sds)) if sds else None
    # S chart limits for the cells: sigma = mean(s_i / c4(n_i))
    if sds:
        sig = float(np.mean([c['sd'] / c4(c['n']) for c in cells if c['sd'] is not None]))
        out['s_limits'] = [{'cl': c4(c['n']) * sig, 'ucl': (c4(c['n']) + 3 * math.sqrt(1 - c4(c['n']) ** 2)) * sig,
                            'lcl': max(0.0, (c4(c['n']) - 3 * math.sqrt(1 - c4(c['n']) ** 2)) * sig)} if c['n'] > 1 else None for c in cells]
    if not components and not gauge:
        out['code'] = _var_code(table_name, y, factors, None, None)
        return out
    # ---- variance components
    model = model or ('crossed' if len(factors) > 1 else 'main')
    work = pd.DataFrame({f: [labels[j][c] for c in codes[j]] for j, f in enumerate(factors)}, index=df.index)
    work[y] = yv
    terms = _terms(factors, model)
    balanced = _balanced(work, factors, terms)
    notes = []
    # the full cross without replicates: its interaction is the error
    if work.groupby(list(factors), observed=True).size().max() == 1 and any(len(fs) == len(factors) for _l, fs in terms):
        dropped = [lab for lab, fs in terms if len(fs) == len(factors)]
        terms = [(lab, fs) for lab, fs in terms if len(fs) < len(factors)]
        notes.append(f'No replicates: the {dropped[0]} term cannot be told apart from the within variation; it is part of Within.')
        if not terms:
            out['components_error'] = 'With one value in every cell and a single grouping factor there is nothing left to estimate the within variation from: variance components need replicates.'
            out['notes'] = notes
            out['code'] = _var_code(table_name, y, factors, None, None)
            return out
    use = method
    if method == 'best':
        use = 'ems' if balanced else 'reml'
    if use == 'ems' and not balanced:
        notes.append('The design is not balanced: the ANOVA (EMS) estimates are not unbiased here; REML is the better choice.')
    comp_rows = []
    anova_rows = None
    try:
        if use == 'ems':
            comp, within, anova_rows, unbounded, dfe = _ems(work, y, factors, terms)
            neg = [t for t, v in unbounded.items() if v < 0]
            if neg:
                notes.append(f'Negative estimates set to zero: {", ".join(f"{t} ({v:.4g})" for t, v in unbounded.items() if v < 0)}.')
            se = {}
            converged = True
        else:
            comp, within, se, converged = _reml(work, y, factors, terms)
            if not converged:
                notes.append('REML did not converge; the estimates are the last iterate.')
    except Exception as e:  # e.g. a singular design
        out['components_error'] = str(e)
        out['notes'] = notes
        out['code'] = _var_code(table_name, y, factors, terms, use)
        return out
    total = sum(comp.values()) + within
    for label_, _fs in terms:
        v = comp.get(label_, 0.0)
        comp_rows.append({'component': label_, 'var': v, 'pct': 100 * v / total if total > 0 else None, 'sd': math.sqrt(max(v, 0.0)), 'se': se.get(label_)})
    comp_rows.append({'component': 'Within', 'var': within, 'pct': 100 * within / total if total > 0 else None, 'sd': math.sqrt(within), 'se': None})
    comp_rows.append({'component': 'Total', 'var': total, 'pct': 100.0 if total > 0 else None, 'sd': math.sqrt(total), 'se': None})
    out['components'] = {'method': 'EMS' if use == 'ems' else 'REML', 'balanced': balanced, 'model': model,
                         'table': rtable([col('component', 'Component', 'text'), col('var', 'Var Component'), col('pct', '% of Total'), col('sd', 'Sqrt(Var Comp)')] +
                                        ([col('se', 'Std Error')] if use == 'reml' else []), comp_rows)}
    if anova_rows:
        out['components']['anova'] = rtable([col('source', 'Source', 'text'), col('df', 'DF'), col('ss', 'Sum of Squares'), col('ms', 'Mean Square'),
                                            col('f', 'F Ratio'), col('p', 'Prob > F', 'p')], anova_rows)
    out['notes'] = notes
    # ---- Gauge R&R: the part is the Part role, else the last X
    if gauge:
        p_name = part or factors[-1]
        ops = [f for f in factors if f != p_name]
        p_term = next((lab for lab, fs in terms if fs == (p_name,) or (len(fs) >= 1 and fs[-1] == p_name and '[' in lab)), None)
        if p_term is None:
            p_term = next((lab for lab, fs in terms if p_name in fs and len(fs) == 1), None)
        v_part = comp.get(p_term, 0.0) if p_term else 0.0
        repro_terms = [lab for lab, _fs in terms if lab != p_term]
        v_repro = sum(comp.get(t, 0.0) for t in repro_terms)
        v_repeat = within
        v_grr = v_repeat + v_repro
        v_tot = v_grr + v_part
        if historical_sigma:
            v_tot = float(historical_sigma) ** 2
            v_part = max(0.0, v_tot - v_grr)
        km = float(k_mult or 6.0)
        tol = tolerance if tolerance is not None else ((usl - lsl) if (lsl is not None and usl is not None) else None)
        grr_rows = []

        def row(name, v, which=''):
            sd = math.sqrt(max(v, 0.0))
            r = {'source': name, 'which': which, 'var': v, 'sd': sd, 'variation': km * sd, 'pct_tv': 100 * sd / math.sqrt(v_tot) if v_tot > 0 else None,
                 'pct_contrib': 100 * v / v_tot if v_tot > 0 else None}
            if tol:
                r['pct_tol'] = 100 * km * sd / tol
            grr_rows.append(r)
        row('Repeatability', v_repeat, 'EV')
        row('Reproducibility', v_repro, 'AV')
        for t in repro_terms:
            row(t, comp.get(t, 0.0))
        row('Gauge R&R', v_grr, 'RR')
        row('Part Variation', v_part, 'PV')
        row('Total Variation', v_tot, 'TV')
        cols_ = [col('source', 'Measurement Source', 'text'), col('which', ' ', 'text'), col('variation', f'Variation ({km:g}*StdDev)'),
                 col('pct_tv', '% of Total Variation'), col('pct_contrib', '% Contribution')]
        if tol:
            cols_.append(col('pct_tol', '% of Tolerance'))
        grr = math.sqrt(v_grr)
        pv = math.sqrt(max(v_part, 0.0))
        tv = math.sqrt(v_tot) if v_tot > 0 else float('nan')
        out['gauge'] = {
            'part': p_name, 'operators': ops, 'k': km, 'tolerance': tol,
            'table': rtable(cols_, grr_rows),
            'pct_grr': 100 * grr / tv if tv > 0 else None,
            'p_to_pv': grr / pv if pv > 0 else None,
            'ndc': int(math.floor(1.41 * pv / grr)) if grr > 0 else None,
            'discrimination': math.sqrt(2 * v_part / v_grr + 1) if v_grr > 0 else None,
            'p_to_t': km * grr / tol if tol else None,
            'components': rtable([col('component', 'Component', 'text'), col('var', 'Var Component'), col('pct', '% of Total'), col('sd', 'Sqrt(Var Comp)')], [
                {'component': 'Gauge R&R', 'var': v_grr, 'pct': 100 * v_grr / v_tot if v_tot > 0 else None, 'sd': grr},
                {'component': '  Repeatability', 'var': v_repeat, 'pct': 100 * v_repeat / v_tot if v_tot > 0 else None, 'sd': math.sqrt(v_repeat)},
                {'component': '  Reproducibility', 'var': v_repro, 'pct': 100 * v_repro / v_tot if v_tot > 0 else None, 'sd': math.sqrt(v_repro)},
                {'component': 'Part-to-Part', 'var': v_part, 'pct': 100 * v_part / v_tot if v_tot > 0 else None, 'sd': pv},
                {'component': 'Total', 'var': v_tot, 'pct': 100.0, 'sd': tv}]),
        }
        if not ops:
            out['gauge']['note'] = 'With only the part as a factor there is no reproducibility: the Gauge R&R is the repeatability alone.'
    out['code'] = _var_code(table_name, y, factors, terms, use)
    return out


def _var_code(table_name, y, factors, terms, use):
    Y = json.dumps(y)
    q = lambda n: n if n.isidentifier() else f'Q({json.dumps(n)})'
    lines = [code_head(table_name), f'df = df.dropna(subset={json.dumps([y] + factors)})',
             f'cells = df.groupby({json.dumps(factors)})[{Y}].agg(["mean", "std", "min", "max", "size"])', 'print(cells)']
    if terms:
        rhs = ' + '.join(':'.join(f'C({q(f)})' for f in fs) for _l, fs in terms)
        if use == 'ems':
            lines += [f'fit = smf.ols("{q(y)} ~ {rhs}", df).fit()', 'print(sm.stats.anova_lm(fit, typ=1))',
                      '# variance components: solve E[MS_T] = sigma^2 + sum c_U sigma^2_U (U the terms containing T, c_U the rows per cell of U)']
        else:
            vc = ', '.join(f'"v{i}": "0 + {":".join(f"C({q(f)})" for f in fs)}"' for i, (_l, fs) in enumerate(terms))
            lines += [f'md = smf.mixedlm("{q(y)} ~ 1", df, groups=np.ones(len(df)), re_formula="0", vc_formula={{{vc}}})',
                      'res = md.fit(reml=True); print(dict(zip(md.exog_vc.names, res.vcomp)), "within", res.scale)']
    return '\n'.join(lines)


@api('quality.attribute_gauge')
def attribute_gauge(table, y, rater, part, rows=None, standard=None, table_name='data'):
    """Attribute gauge: agreement of raters who classify parts, within each
    rater over repeated trials, between raters (Cohen's kappa for each pair)
    and over all (Fleiss' kappa), and against a standard (effectiveness)."""
    from statsmodels.stats.inter_rater import cohens_kappa, fleiss_kappa
    names = [y, rater, part] + ([standard] if standard else [])
    df = data.frame(table, names, rows, dropna=True, as_category=True)
    if len(df) < 2:
        return {'error': 'fewer than two ratings'}
    Yv = df[y].map(_label) if not isinstance(df[y].dtype, pd.CategoricalDtype) else df[y].astype(object).map(_label)
    Rv = df[rater].astype(object).map(_label)
    Pv = df[part].astype(object).map(_label)
    cats = [_label(v) for v in (df[y].cat.categories if isinstance(df[y].dtype, pd.CategoricalDtype) else sorted(pd.unique(df[y])))]
    cats = [c for c in cats if c in set(Yv)]
    raters = [_label(v) for v in (df[rater].cat.categories if isinstance(df[rater].dtype, pd.CategoricalDtype) else sorted(pd.unique(df[rater])))]
    raters = [r for r in raters if r in set(Rv)]
    parts = [_label(v) for v in (df[part].cat.categories if isinstance(df[part].dtype, pd.CategoricalDtype) else sorted(pd.unique(df[part])))]
    parts = [p for p in parts if p in set(Pv)]
    d = pd.DataFrame({'y': Yv.to_numpy(), 'r': Rv.to_numpy(), 'p': Pv.to_numpy()}, index=df.index)
    d['trial'] = d.groupby(['p', 'r']).cumcount()
    if standard:
        d['std'] = (df[standard].astype(object).map(_label)).to_numpy()
    # per part: the share of agreeing pairs among all its ratings
    part_rows = []
    for p in parts:
        s = d[d['p'] == p]
        cnt = s['y'].value_counts()
        nn = len(s)
        pairs = nn * (nn - 1) / 2
        agree = float(sum(c * (c - 1) / 2 for c in cnt))
        part_rows.append({'part': p, 'agree': agree / pairs if pairs else None, 'n': nn, 'rows': [int(i) for i in s.index]})
    # per rater: pairs of one of its ratings with every other rating of the part
    rater_rows = []
    for r in raters:
        agree = tot = 0.0
        within_ok = within_n = 0
        for p in parts:
            s = d[d['p'] == p]
            mine = s[s['r'] == r]['y'].tolist()
            others = s[s['r'] != r]['y'].tolist()
            for i, a in enumerate(mine):
                for b in mine[i + 1:] + others:
                    tot += 1
                    agree += a == b
            if len(mine) > 1:
                within_n += 1
                within_ok += len(set(mine)) == 1
        row = {'rater': r, 'agree': agree / tot if tot else None, 'within': within_ok / within_n if within_n else None, 'n_parts_within': within_n,
               'rows': [int(i) for i in d.index[d['r'] == r]]}
        if standard:
            s = d[d['r'] == r]
            row['effectiveness'] = float(np.mean(s['y'] == s['std'])) if len(s) else None
        rater_rows.append(row)
    out = {'categories': cats, 'raters': raters, 'parts': part_rows, 'rater_table': rater_rows}
    # Fleiss' kappa over all ratings of each part (needs as many ratings per part)
    counts = d.groupby('p')['y'].value_counts().unstack(fill_value=0).reindex(index=parts, columns=cats, fill_value=0)
    m = counts.sum(axis=1)
    kappa_rows = []
    if m.nunique() == 1 and int(m.iloc[0]) >= 2 and len(cats) >= 2:
        tbl = counts.to_numpy(float)
        k_all = float(fleiss_kappa(tbl, method='fleiss'))
        mm = float(m.iloc[0])
        N = tbl.shape[0]
        for j, c in enumerate(cats):
            pj = tbl[:, j].sum() / (N * mm)
            if 0 < pj < 1:
                kj = 1 - np.sum(tbl[:, j] * (mm - tbl[:, j])) / (N * mm * (mm - 1) * pj * (1 - pj))
            else:
                kj = None
            kappa_rows.append({'category': c, 'kappa': kj})
        kappa_rows.append({'category': 'Overall', 'kappa': k_all})
        out['fleiss'] = rtable([col('category', 'Category', 'text'), col('kappa', 'Kappa')], kappa_rows)
    else:
        out['fleiss_note'] = "Fleiss' kappa needs the same number of ratings of every part."
    # Cohen's kappa between each pair of raters, matched by part and trial
    pair_rows = []
    for a, b in itertools.combinations(raters, 2):
        A = d[d['r'] == a].set_index(['p', 'trial'])['y']
        B = d[d['r'] == b].set_index(['p', 'trial'])['y']
        j = A.to_frame('a').join(B.to_frame('b'), how='inner')
        if len(j) < 2:
            continue
        tab = pd.crosstab(pd.Categorical(j['a'], categories=cats), pd.Categorical(j['b'], categories=cats), dropna=False).to_numpy(float)
        try:
            kr = cohens_kappa(tab)
            pair_rows.append({'a': a, 'b': b, 'kappa': float(kr.kappa), 'se': float(kr.std_kappa), 'n': int(len(j)), 'agree': float(np.trace(tab) / tab.sum())})
        except Exception:
            pass
    out['pairs'] = rtable([col('a', 'Rater', 'text'), col('b', 'Rater', 'text'), col('kappa', 'Kappa'), col('se', 'Std Err'), col('agree', '% Agreement', 'pct'), col('n', 'N', 'int')], pair_rows)
    if standard:
        eff = []
        for r in raters:
            s = d[d['r'] == r]
            row = {'rater': r, 'correct': int(np.sum(s['y'] == s['std'])), 'incorrect': int(np.sum(s['y'] != s['std']))}
            row['effectiveness'] = row['correct'] / max(1, row['correct'] + row['incorrect'])
            eff.append(row)
        tot_c = sum(e['correct'] for e in eff)
        tot_i = sum(e['incorrect'] for e in eff)
        eff.append({'rater': 'Totals', 'correct': tot_c, 'incorrect': tot_i, 'effectiveness': tot_c / max(1, tot_c + tot_i)})
        out['effectiveness'] = rtable([col('rater', 'Rater', 'text'), col('correct', 'Correct', 'int'), col('incorrect', 'Incorrect', 'int'), col('effectiveness', 'Effectiveness', 'pct')], eff)
        mis = pd.crosstab(d['std'], d['y'])
        out['misclassification'] = {'standard': [str(i) for i in mis.index], 'rated': [str(c) for c in mis.columns], 'counts': mis.to_numpy().tolist()}
    out['code'] = '\n'.join([code_head(table_name, ['from statsmodels.stats.inter_rater import aggregate_raters, cohens_kappa, fleiss_kappa']),
                             f'counts = df.groupby({json.dumps(part)})[{json.dumps(y)}].value_counts().unstack(fill_value=0)',
                             "print(fleiss_kappa(counts.to_numpy(), method='fleiss'))   # all raters and trials",
                             f'wide = df.assign(trial=df.groupby([{json.dumps(part)}, {json.dumps(rater)}]).cumcount()).pivot_table(index=[{json.dumps(part)}, "trial"], columns={json.dumps(rater)}, values={json.dumps(y)}, aggfunc="first")',
                             'a, b = wide.columns[:2]; print(cohens_kappa(pd.crosstab(wide[a], wide[b]).to_numpy()))'])
    return out
