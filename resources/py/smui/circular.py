"""Circular Statistics: directions, angles and times of day.

A Y column holds angles in degrees, in radians, or on a clock of a given
period (24 hours, 7 days, 12 months); the report gives the mean direction,
the mean resultant length and the spreads, the median direction, intervals
for the mean direction, the Rayleigh and V tests, a von Mises fit, and with
an X column the circular-linear correlation (continuous X), the
circular-circular correlation (an X of angles) or a comparison of groups
(nominal or ordinal X: Watson-Williams and the uniform-scores test).

JMP has no such platform. The definitions and tests follow Mardia and Jupp
(2000), Fisher (1993) and Zar (2010); scipy has the circular mean, variance
and standard deviation and the von Mises distribution, the rest is written
out here from those books. Freq counts a row that many times.
"""
import json
import math

import numpy as np
from scipy import stats

from . import data
from .registry import api
from .util import code_head, col
from .util import table as rtable

J = json.dumps
TWO_PI = 2 * math.pi


# ---- units ------------------------------------------------------------------------

def _period(units, period):
    """The full circle in the column's units."""
    if units == 'degrees':
        return 360.0
    if units == 'radians':
        return TWO_PI
    if units == 'clock':
        p = 24.0 if period is None else float(period)
        if not p > 0:
            raise ValueError('the period of a clock must be positive')
        return p
    raise ValueError(f'unknown units {units!r}')


def _to_units(theta, P):
    """An angle in radians as the column's units, in [0, P)."""
    v = (float(theta) % TWO_PI) * P / TWO_PI
    return 0.0 if v >= P else v


def _span(theta, P):
    """A length on the circle (radians) in the column's units."""
    return float(theta) * P / TWO_PI


def _rad_expr(units, P, var='x'):
    """The expression that turns var (the column's values) into radians."""
    if units == 'degrees':
        return f'np.deg2rad({var}) % (2*np.pi)'
    if units == 'radians':
        return f'{var} % (2*np.pi)'
    return f'2*np.pi * {var} / {P!r} % (2*np.pi)'


def _units_code(units, P):
    """The line that turns x (the column's values) into radians."""
    what = 'degrees' if units == 'degrees' else 'radians' if units == 'radians' else f'a clock of period {P:g}'
    return f'theta = {_rad_expr(units, P)}   # the angles ({what}) in radians'


def _back_code(units, P):
    """The expression that turns radians (r) into the column's units."""
    if units == 'degrees':
        return 'np.rad2deg({})'
    if units == 'radians':
        return '({})'
    return f'({{}}) * {P!r} / (2*np.pi)'


def _reps(f):
    r = np.rint(f)
    if np.any(np.abs(f - r) > 1e-9):
        raise ValueError('Freq must hold whole numbers (each row is counted that many times)')
    return r.astype(int)


def _frame(table, names, rows, freq):
    """The rows with every column present and a positive Freq, repeated Freq
    times; the index is the page's row numbers."""
    df = data.frame(table, [*names, freq], rows, as_category=False)
    if freq:
        f = df[freq].to_numpy(float)
        df = df[np.isfinite(f) & (f > 0)]
        df = df.loc[df.index.repeat(_reps(df[freq].to_numpy(float)))]
    return df


def _theta(x, P):
    return np.mod(np.asarray(x, float) * (TWO_PI / P), TWO_PI)


def _freq_code(freq):
    return f'd = d[d[{J(freq)}] > 0]; d = d.loc[d.index.repeat(d[{J(freq)}].round().astype(int))]   # Freq: each row counted that many times'


def _head(table_name, where, cols, freq, extra=()):
    lines = [code_head(table_name, ['from scipy import stats', *extra])]
    for w in where or []:
        lines.append(f'df = df[df[{J(w["column"])}] == {J(w["value"])}]   # only the rows where {w["column"]} is {w["value"]}')
    lines.append(f'd = df[[{", ".join(J(c) for c in [*cols, freq] if c)}]].dropna()')
    if freq:
        lines.append(_freq_code(freq))
    return lines


# ---- the moments ------------------------------------------------------------------

TINY = 1e-12   # a mean resultant length below this is 0: rounding, no direction


def _moments(th):
    """C̄, S̄, R̄ and the mean direction of angles in radians (R̄ of rounding
    error only is 0)."""
    C, S = float(np.mean(np.cos(th))), float(np.mean(np.sin(th)))
    R = math.hypot(C, S)
    if R < TINY:
        R = 0.0
    return C, S, R, (math.atan2(S, C) % TWO_PI)


def a1(kappa):
    """A₁(κ) = I₁(κ)/I₀(κ), the mean resultant length of a von Mises."""
    from scipy.special import i0e, i1e
    return float(i1e(kappa) / i0e(kappa))


def a1inv(R):
    """The κ with A₁(κ) = R: the maximum likelihood κ of a von Mises
    (Mardia and Jupp 2000, §5.3.1). inf for R = 1."""
    from scipy.optimize import brentq
    if not R < 1:
        return math.inf
    if R <= 0:
        return 0.0
    hi = 1.0
    while a1(hi) < R:
        hi *= 2
        if hi > 1e12:
            return math.inf
    return float(brentq(lambda k: a1(k) - R, 0.0, hi, xtol=1e-14, rtol=1e-14, maxiter=500))


def median_direction(th):
    """The sample median direction (Fisher 1993, §2.3.2): the point of the
    circle with the least mean circular distance π − |π − |θ − φ|| to the
    data. The distance is linear between the data points, so the least is at
    a data point or along an arc between two (for an even n, as a linear
    median, between the two middle ones): the middle of that arc. Of
    several separate minima, the one nearest the mean direction; returns
    the median, its mean distance and how many separate minima there are.
    The distances at every data point and midpoint come from prefix sums
    of the sorted angles, twice around the circle: O(n log n)."""
    s = np.sort(np.mod(th, TWO_PI))
    n = len(s)
    gap = np.mod(np.roll(s, -1) - s, TWO_PI)
    cand = np.unique(np.concatenate([s, np.mod(s + gap / 2, TWO_PI)]))
    ext = np.concatenate([s, s + TWO_PI])
    cs = np.concatenate([[0.0], np.cumsum(ext)])
    a = np.searchsorted(ext, cand, 'left')              # the first angle at or after φ
    b = np.searchsorted(ext, cand + math.pi, 'right')   # past the half circle ahead of φ
    k1, k2 = b - a, n - (b - a)
    # ahead within π: θ − φ; the rest, behind: φ + 2π − θ
    ds = ((cs[b] - cs[a]) - k1 * cand + k2 * (cand + TWO_PI) - (cs[a + n] - cs[b])) / n
    best = float(ds.min())
    at = np.flatnonzero(ds <= best + 1e-12 * max(1.0, best))
    m = len(cand)
    # the minima as runs of neighbouring candidates (around the circle)
    runs = []
    for i in at:
        if runs and (i - runs[-1][-1]) == 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][-1] == m - 1:
        runs[0] = runs.pop() + runs[0]
    centres = []
    for run in runs:
        lo, hi = cand[run[0]], cand[run[-1]]
        centres.append(float(np.mod(lo + np.mod(hi - lo, TWO_PI) / 2, TWO_PI)))
    if len(centres) == 1:
        return centres[0], best, 1
    mean = _moments(th)[3]
    off = [abs((c - mean + math.pi) % TWO_PI - math.pi) for c in centres]
    return centres[int(np.argmin(off))], best, len(centres)


def rayleigh(n, R):
    """Rayleigh's test of uniformity against one mode: Z = nR̄² and Zar's
    (2010) approximation of its p-value, exp(√(1 + 4n + 4(n² − (nR̄)²)) −
    (1 + 2n))."""
    Z = n * R * R
    p = math.exp(math.sqrt(1 + 4 * n + 4 * (n * n - (n * R) ** 2)) - (1 + 2 * n))
    return Z, min(1.0, max(0.0, p))


def mean_ci(n, R, rho2, alpha):
    """Intervals for the mean direction, as half-widths in radians (None
    where the method does not give one): von Mises, Upton's (1986)
    approximation as Zar (2010) gives it; and any unimodal distribution,
    Fisher's (1993, §4.4.4) large-sample θ̄ ± arcsin(z σ̂), σ̂² = (1 −
    ρ̂₂)/(2nR̄²), ρ̂₂ the mean of cos 2(θ − θ̄)."""
    c2 = float(stats.chi2.ppf(1 - alpha, 1))
    Rn = n * R
    vm = None
    if R < 0.9 and R > math.sqrt(c2 / (2 * n)):
        t = math.sqrt(2 * n * (2 * Rn * Rn - n * c2) / (4 * n - c2))
        vm = math.acos(min(1.0, t / Rn))
    elif R >= 0.9:
        inside = n * n - (n * n - Rn * Rn) * math.exp(c2 / n)
        if inside > 0:
            vm = math.acos(min(1.0, math.sqrt(inside) / Rn))
    fi = None
    if R > 0:
        s = math.sqrt(max(0.0, 1 - rho2) / (2 * n * R * R))
        zs = float(stats.norm.ppf(1 - alpha / 2)) * s
        if zs <= 1:
            fi = math.asin(zs)
    return vm, fi


# ---- the summary ------------------------------------------------------------------

@api('circular.summary')
def summary(table, column, rows=None, units='degrees', period=None, alpha=0.05, v_dir=None, freq=None, where=None, table_name='data'):
    """Summary Statistics of one column of angles, the intervals for the
    mean direction, the Rayleigh test and (a direction given) the V test."""
    P = _period(units, period)
    df = _frame(table, [column], rows, freq)
    x = df[column].to_numpy(float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return {'error': 'fewer than two angles'}
    th = _theta(x, P)
    C, S, R, mean = _moments(th)
    rho2 = float(np.mean(np.cos(2 * (th - mean))))
    C2, S2 = float(np.mean(np.cos(2 * th))), float(np.mean(np.sin(2 * th)))
    R2, m2 = math.hypot(C2, S2), math.atan2(S2, C2)
    med, med_d, med_ties = median_direction(th)
    one = 1 - R
    out = {'n': n, 'units': units, 'period': P, 'alpha': alpha, 'C': C, 'S': S, 'rbar': R, 'resultant': n * R,
           'mean': _to_units(mean, P) if R > 0 else None, 'mean_rad': mean,
           'circ_var': one, 'circ_sd': _span(math.sqrt(-2 * math.log(R)), P) if R > 0 else math.inf,
           'ang_dev': _span(math.sqrt(2 * one), P), 'dispersion': (1 - rho2) / (2 * R * R) if R > 0 else math.inf,
           'median': _to_units(med, P), 'median_dist': _span(med_d, P), 'median_ties': med_ties,
           'skewness': R2 * math.sin(m2 - 2 * mean) / one ** 1.5 if one > 0 and R > 0 else None,
           'kurtosis': (R2 * math.cos(m2 - 2 * mean) - R ** 4) / one ** 2 if one > 0 and R > 0 else None}
    vm, fi = mean_ci(n, R, rho2, alpha)
    lv = f'{100 * (1 - alpha):g}%'
    ci_rows = []
    for label, h, why in (('von Mises (Upton 1986)', vm, 'R̄ too small for this n' if R < 0.9 else 'not defined for these data'),
                          ('Any unimodal, large n (Fisher 1993)', fi, 'z·σ̂ exceeds 1')):
        if h is None:
            ci_rows.append({'method': label, 'lower': None, 'upper': None, 'half': None, 'note': why})
        else:
            ci_rows.append({'method': label, 'lower': _to_units(mean - h, P), 'upper': _to_units(mean + h, P), 'half': _span(h, P), 'note': ''})
    out['ci'] = rtable([col('method', 'Method', 'text'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}'), col('half', '± Half Width'), col('note', 'Note', 'text')], ci_rows)
    Z, p = rayleigh(n, R)
    out['rayleigh'] = {'Z': Z, 'p': p, 'rbar': R, 'n': n}
    if v_dir is not None:
        mu0 = float(v_dir) * TWO_PI / P
        V = n * R * math.cos(mean - mu0)
        u = V * math.sqrt(2 / n)
        out['vtest'] = {'dir': float(v_dir), 'V': V, 'u': u, 'p': float(stats.norm.sf(u))}
    back = _back_code(units, P)
    c = _head(table_name, where, [column], freq)
    c.append(f'x = d[{J(column)}].to_numpy(); n = len(x)')
    c.append(_units_code(units, P))
    c.append('C, S = np.cos(theta).mean(), np.sin(theta).mean(); R = np.hypot(C, S); m = np.arctan2(S, C) % (2*np.pi)')
    c.append(f'print({back.format("m")}, R, 1 - R, {back.format("np.sqrt(-2*np.log(R))")}, {back.format("np.sqrt(2*(1 - R))")})   # mean direction, R̄, circular variance, circular SD, angular deviation')
    c.append('print(stats.circmean(theta), stats.circvar(theta), stats.circstd(theta))   # the same in radians, by scipy')
    c.append('rho2 = np.cos(2*(theta - m)).mean(); print((1 - rho2) / (2*R**2))   # the circular dispersion (Fisher 1993)')
    c.append('print(n*R**2, np.exp(np.sqrt(1 + 4*n + 4*(n**2 - (n*R)**2)) - (1 + 2*n)))   # Rayleigh Z and its p-value (Zar 2010)')
    c.append(f'c2, Rn = stats.chi2.ppf({1 - alpha!r}, 1), n*R   # the von Mises interval of the mean direction (Upton 1986, as Zar gives it)')
    c.append('h = np.arccos(np.sqrt(2*n*(2*Rn**2 - n*c2) / (4*n - c2)) / Rn) if R < 0.9 else np.arccos(np.sqrt(n**2 - (n**2 - Rn**2)*np.exp(c2/n)) / Rn)')
    c.append(f'hf = np.arcsin(stats.norm.ppf({1 - alpha / 2!r}) * np.sqrt((1 - rho2) / (2*n*R**2)))   # any unimodal, large n (Fisher 1993)')
    c.append(f'print({back.format("(m - h) % (2*np.pi)")}, {back.format("(m + h) % (2*np.pi)")}, {back.format("(m - hf) % (2*np.pi)")}, {back.format("(m + hf) % (2*np.pi)")})')
    if v_dir is not None:
        c.append(f'mu0 = {float(v_dir)!r} * 2*np.pi / {P!r}; V = n*R*np.cos(m - mu0); print(V, stats.norm.sf(V*np.sqrt(2/n)))   # the V test of a mean direction {float(v_dir):g}')
    out['code'] = '\n'.join(c)
    return out


# ---- the von Mises fit ------------------------------------------------------------

def _vm_loglik(n, R, kappa):
    """The von Mises log likelihood with μ at the mean direction."""
    from scipy.special import i0e
    return n * (kappa * R - (math.log(i0e(kappa)) + kappa) - math.log(TWO_PI))


@api('circular.vonmises')
def vonmises(table, column, rows=None, units='degrees', period=None, alpha=0.05, freq=None, where=None, table_name='data'):
    """Fitted von Mises: μ̂ the mean direction, κ̂ = A₁⁻¹(R̄) by maximum
    likelihood (Mardia and Jupp 2000, §5.3.1; scipy.stats.vonmises.fit gives
    the same), the standard errors from the information, 1/√(nκA₁(κ)) for
    μ and 1/√(nA₁′(κ)) for κ, a normal interval for μ and the
    likelihood-ratio interval for κ; the small-sample κ of Best and Fisher
    (1981); the density on a grid."""
    from scipy.optimize import brentq
    from scipy.special import i0e
    P = _period(units, period)
    df = _frame(table, [column], rows, freq)
    x = df[column].to_numpy(float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return {'error': 'fewer than two angles'}
    th = _theta(x, P)
    C, S, R, mean = _moments(th)
    kappa = a1inv(R)
    if not math.isfinite(kappa):
        return {'error': 'every angle is the same: κ is infinite'}
    A = a1(kappa)
    dA = 1 - A / kappa - A * A if kappa > 0 else 0.5
    se_mu = 1 / math.sqrt(n * kappa * A) if kappa > 0 else math.inf
    se_k = 1 / math.sqrt(n * dA) if dA > 0 else math.inf
    z = float(stats.norm.ppf(1 - alpha / 2))
    top = _vm_loglik(n, R, kappa)
    crit = float(stats.chi2.ppf(1 - alpha, 1)) / 2
    g = lambda k: top - _vm_loglik(n, R, k) - crit
    lo = 0.0 if g(0.0) <= 0 else float(brentq(g, 0.0, kappa, xtol=1e-12))
    hi = kappa * 2 + 1
    while g(hi) < 0:
        hi *= 2
    hi = float(brentq(g, kappa, hi, xtol=1e-12))
    if kappa < 2:
        k_small = max(kappa - 2 / (n * kappa), 0.0) if kappa > 0 else 0.0
    else:
        k_small = (n - 1) ** 3 * kappa / (n ** 3 + n)
    lv = f'{100 * (1 - alpha):g}%'
    est = rtable([col('term', 'Parameter', 'text'), col('estimate', 'Estimate'), col('se', 'Std Error'), col('lower', f'Lower {lv}'), col('upper', f'Upper {lv}'), col('method', 'Interval', 'text')], [
        {'term': 'μ (mean direction)', 'estimate': _to_units(mean, P), 'se': _span(se_mu, P), 'lower': _to_units(mean - z * se_mu, P) if z * se_mu < math.pi else None,
         'upper': _to_units(mean + z * se_mu, P) if z * se_mu < math.pi else None, 'method': 'normal (Wald)'},
        {'term': 'κ (concentration)', 'estimate': kappa, 'se': se_k, 'lower': lo, 'upper': hi, 'method': 'likelihood ratio'},
    ])
    grid = np.linspace(0, TWO_PI, 361)
    dens = np.exp(kappa * (np.cos(grid - mean) - 1)) / (TWO_PI * i0e(kappa))    # per radian
    out = {'estimates': est, 'mu': _to_units(mean, P), 'kappa': kappa, 'kappa_small': k_small, 'se_mu': _span(se_mu, P), 'se_kappa': se_k,
           'loglik': top, 'n': n, 'rbar': R, 'units': units, 'period': P, 'alpha': alpha,
           'curve': {'x': [_span(v, P) for v in grid], 'density': (dens * TWO_PI / P).tolist()}}
    notes = []
    if n <= 15:
        notes.append(f'With {n} angles κ̂ is biased upward; Best and Fisher\'s (1981) small-sample value is {k_small:.4g}.')
    out['notes'] = notes
    back = _back_code(units, P)
    c = _head(table_name, where, [column], freq, ['from scipy import optimize, special'])
    c.append(f'x = d[{J(column)}].to_numpy(); n = len(x)')
    c.append(_units_code(units, P))
    c.append('kappa, mu, _ = stats.vonmises.fit(theta, fscale=1); print(kappa, ' + back.format('mu % (2*np.pi)') + ')   # the maximum likelihood κ and μ')
    c.append('R = np.hypot(np.cos(theta).mean(), np.sin(theta).mean()); A = special.i1e(kappa) / special.i0e(kappa)')
    c.append('print(' + back.format('1 / np.sqrt(n*kappa*A)') + ', 1 / np.sqrt(n*(1 - A/kappa - A**2)))   # the standard errors of μ and κ')
    c.append('ll = lambda k: n*(k*R - np.log(special.i0e(k)) - k - np.log(2*np.pi))   # the log likelihood, μ at its estimate')
    c.append(f'g = lambda k: ll(kappa) - ll(k) - stats.chi2.ppf({1 - alpha!r}, 1)/2')
    c.append('print(0.0 if g(0) <= 0 else optimize.brentq(g, 0, kappa), optimize.brentq(g, kappa, 100*kappa + 100))   # the likelihood-ratio interval of κ')
    out['code'] = '\n'.join(c)
    return out


# ---- with an X column -------------------------------------------------------------

@api('circular.linear')
def linear(table, y, x, rows=None, units='degrees', period=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """The circular-linear correlation of the angle Y with a continuous X
    (Mardia 1976; Mardia and Jupp 2000, §11.2.1): R² = (r_xc² + r_xs² −
    2r_xc r_xs r_cs)/(1 − r_cs²) from the correlations of x, cos θ and sin
    θ; nR² is about χ² with 2 DF when they are independent."""
    if y == x:
        return {'error': 'Y and X are the same column'}
    P = _period(units, period)
    df = _frame(table, [y, x], rows, freq)
    n = len(df)
    if n < 4:
        return {'error': 'fewer than four rows with both values'}
    th = _theta(df[y].to_numpy(float), P)
    xv = df[x].to_numpy(float)
    cs, sn = np.cos(th), np.sin(th)
    if np.std(xv) == 0 or np.std(cs) == 0 or np.std(sn) == 0:
        return {'error': 'X or the angles do not vary'}
    rxc, rxs, rcs = (float(np.corrcoef(a, b)[0, 1]) for a, b in ((xv, cs), (xv, sn), (cs, sn)))
    R2 = (rxc ** 2 + rxs ** 2 - 2 * rxc * rxs * rcs) / (1 - rcs ** 2)
    R2 = min(max(R2, 0.0), 1.0)
    chi = n * R2
    out = {'n': n, 'r': math.sqrt(R2), 'r2': R2, 'r_xc': rxc, 'r_xs': rxs, 'r_cs': rcs, 'chisq': chi, 'df': 2, 'p': float(stats.chi2.sf(chi, 2))}
    c = _head(table_name, where, [y, x], freq)
    c.append(f'x = d[{J(y)}].to_numpy(); v = d[{J(x)}].to_numpy(); n = len(x)')
    c.append(_units_code(units, P))
    c.append('rxc, rxs, rcs = [np.corrcoef(a, b)[0, 1] for a, b in ((v, np.cos(theta)), (v, np.sin(theta)), (np.cos(theta), np.sin(theta)))]')
    c.append('R2 = (rxc**2 + rxs**2 - 2*rxc*rxs*rcs) / (1 - rcs**2); print(np.sqrt(R2), R2, n*R2, stats.chi2.sf(n*R2, 2))   # the circular-linear correlation (Mardia 1976)')
    out['code'] = '\n'.join(c)
    return out


@api('circular.circular')
def circular_corr(table, y, x, rows=None, units='degrees', period=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """The circular-circular correlation of two columns of angles
    (Jammalamadaka and SenGupta 2001, §8.2): r = Σ sin(α − ᾱ) sin(β − β̄)/√(Σ
    sin²(α − ᾱ) Σ sin²(β − β̄)), with its large-sample z = r√(n λ₂₀λ₀₂/λ₂₂),
    λᵢⱼ the means of sinⁱ(α − ᾱ) sinʲ(β − β̄), against the normal."""
    if y == x:
        return {'error': 'the two angles are the same column'}
    P = _period(units, period)
    df = _frame(table, [y, x], rows, freq)
    n = len(df)
    if n < 4:
        return {'error': 'fewer than four rows with both values'}
    a, b = _theta(df[y].to_numpy(float), P), _theta(df[x].to_numpy(float), P)
    sa, sb = np.sin(a - _moments(a)[3]), np.sin(b - _moments(b)[3])
    den = math.sqrt(float(np.sum(sa ** 2) * np.sum(sb ** 2)))
    if not den > 0:
        return {'error': 'the angles do not vary'}
    r = float(np.sum(sa * sb)) / den
    l20, l02, l22 = float(np.mean(sa ** 2)), float(np.mean(sb ** 2)), float(np.mean(sa ** 2 * sb ** 2))
    z = r * math.sqrt(n * l20 * l02 / l22) if l22 > 0 else math.inf
    out = {'n': n, 'r': r, 'z': z, 'p': float(2 * stats.norm.sf(abs(z)))}
    c = _head(table_name, where, [y, x], freq)
    c.append(f'n = len(d); a = {_rad_expr(units, P, "d[" + J(y) + "].to_numpy()")}; b = {_rad_expr(units, P, "d[" + J(x) + "].to_numpy()")}   # the angles in radians')
    c.append('sa, sb = np.sin(a - stats.circmean(a)), np.sin(b - stats.circmean(b)); r = (sa*sb).sum() / np.sqrt((sa**2).sum() * (sb**2).sum())')
    c.append('z = r * np.sqrt(n * (sa**2).mean() * (sb**2).mean() / (sa**2 * sb**2).mean()); print(r, z, 2*stats.norm.sf(abs(z)))   # Jammalamadaka and SenGupta (2001)')
    out['code'] = '\n'.join(c)
    return out


@api('circular.groups')
def groups(table, y, x, rows=None, units='degrees', period=None, freq=None, alpha=0.05, where=None, table_name='data'):
    """The angle Y in the groups of a nominal or ordinal X: each group's
    summary; the Watson-Williams test that the mean directions are equal
    (von Mises groups of one concentration; Mardia and Jupp 2000, §7.4.1):
    F = (1 + 3/(8κ̂))·((ΣRⱼ − R)/(q − 1))/((n − ΣRⱼ)/(n − q)), κ̂ = A₁⁻¹(ΣRⱼ/n);
    and the Mardia-Watson-Wheeler uniform-scores test that the
    distributions are the same (Mardia and Jupp 2000, §8.3.6): the angles
    replaced by 2π·rank/n, W = 2Σ(Cⱼ² + Sⱼ²)/nⱼ against χ² with 2(q − 1) DF,
    ties by their average rank."""
    if y == x:
        return {'error': 'Y and X are the same column'}
    P = _period(units, period)
    df = _frame(table, [y], rows, freq)
    if not data.is_categorical(table, x):
        return {'error': 'the groups need an ordinal or nominal X'}
    gs = data.series(table, x, df.index.unique())
    gser = gs.reindex(df.index)
    ok = gser.notna().to_numpy()
    df = df[ok]
    gser = gser[ok]
    levels = [lv for lv in gser.cat.categories if (gser == lv).any()]
    q = len(levels)
    if q < 2:
        return {'error': 'X has fewer than two levels with angles'}
    th = _theta(df[y].to_numpy(float), P)
    code = np.array([levels.index(v) for v in gser.astype(object)])
    n = len(th)
    grp = []
    Rsum = 0.0
    for j, lv in enumerate(levels):
        tj = th[code == j]
        Cj, Sj, Rj, mj = _moments(tj)
        Rsum += len(tj) * Rj
        grp.append({'level': lv, 'n': len(tj), 'mean': _to_units(mj, P) if Rj > 0 else None, 'rbar': Rj,
                    'circ_sd': _span(math.sqrt(-2 * math.log(Rj)), P) if Rj > 0 else None})
    _, _, Rall, mall = _moments(th)
    Rw = Rsum / n
    kappa = a1inv(Rw)
    notes = []
    ww = None
    if n > q and Rsum < n:
        corr = 1 + 3 / (8 * kappa) if kappa > 0 else math.inf
        F = corr * ((Rsum - n * Rall) / (q - 1)) / ((n - Rsum) / (n - q))
        ww = {'F': F, 'df_num': q - 1, 'df_den': n - q, 'p': float(stats.f.sf(F, q - 1, n - q)), 'kappa': kappa, 'correction': corr, 'rbar_within': Rw}
        if kappa < 1:
            notes.append(f'κ̂ = {kappa:.3g} is below 1: the Watson-Williams test assumes concentrated von Mises groups (κ of at least 1 or 2), and its p-value is not reliable here; the uniform-scores test does not assume it.')
        elif Rw < 0.45:
            notes.append(f'The mean resultant length within the groups is {Rw:.3g}, below 0.45: Zar (2010) advises against the Watson-Williams test here.')
    # uniform scores: the ranks of all the angles around the circle
    ranks = stats.rankdata(th, method='average')
    gam = TWO_PI * ranks / n
    W = 0.0
    for j in range(q):
        gj = gam[code == j]
        W += 2 * (float(np.sum(np.cos(gj))) ** 2 + float(np.sum(np.sin(gj))) ** 2) / len(gj)
    usc = {'W': W, 'df': 2 * (q - 1), 'p': float(stats.chi2.sf(W, 2 * (q - 1)))}
    if min(g_['n'] for g_ in grp) <= 10:
        notes.append('A group has 10 angles or fewer: the χ² approximation of the uniform-scores test is rough there (Mardia and Jupp 2000).')
    if len(np.unique(th)) < n:
        notes.append('Tied angles share their average rank in the uniform-scores test.')
    out = {'groups': grp, 'levels': levels, 'n': n, 'rbar': Rall, 'mean': _to_units(mall, P), 'resultant_sum': Rsum, 'ww': ww, 'uscores': usc, 'notes': notes}
    back = _back_code(units, P)
    c = _head(table_name, where, [y, x], freq)
    c.append(f'x = d[{J(y)}].to_numpy(); g = d[{J(x)}].to_numpy(); n = len(x)')
    c.append(_units_code(units, P))
    c.append('lv = pd.unique(g); q = len(lv); Rj = np.array([np.abs(np.exp(1j*theta[g == v]).sum()) for v in lv]); nj = np.array([(g == v).sum() for v in lv])')
    c.append('print([(v, ' + back.format('stats.circmean(theta[g == v])') + ', Rj[i]/nj[i]) for i, v in enumerate(lv)])   # each group: mean direction, R̄')
    c.append('from scipy import optimize, special; R = np.abs(np.exp(1j*theta).sum())')
    c.append('kappa = optimize.brentq(lambda k: special.i1e(k)/special.i0e(k) - Rj.sum()/n, 1e-12, 1e6)   # κ from the mean resultant length within the groups')
    c.append('F = (1 + 3/(8*kappa)) * ((Rj.sum() - R)/(q - 1)) / ((n - Rj.sum())/(n - q)); print(F, stats.f.sf(F, q - 1, n - q))   # Watson-Williams')
    c.append('gam = 2*np.pi*stats.rankdata(theta)/n; W = sum(2*(np.cos(gam[g == v]).sum()**2 + np.sin(gam[g == v]).sum()**2)/(g == v).sum() for v in lv)')
    c.append('print(W, stats.chi2.sf(W, 2*(q - 1)))   # the uniform-scores test (Mardia-Watson-Wheeler)')
    out['code'] = '\n'.join(c)
    return out
