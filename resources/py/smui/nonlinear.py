"""Fit Curve and Nonlinear: curves fitted by least squares.

Fit Curve fits JMP's library of named models to Y by X -- polynomials,
sigmoid curves, exponential growth and decay, peaks, a pharmacokinetic
model and a few others -- each with automatic starting values, separately
for each level of a Group column. Nonlinear fits a model typed as an
expression over column names and parameter names. Both minimise the
weighted sum of squared residuals with scipy.optimize.least_squares
(Levenberg-Marquardt) and report the estimates with the usual asymptotic
standard errors,

    Cov = MSE (J'WJ)^-1,   MSE = SSE / (n - k),

J the Jacobian of the model at the estimates (central differences), with
Wald intervals from the t distribution on n - k degrees of freedom: what
scipy's curve_fit reports.

A typed model is parsed with Python's ast module into a small expression
tree -- numbers, parameter and column names, + - * / ** (and ^), unary
minus, comparisons, and a fixed set of numpy functions -- and evaluated by
walking that tree. Nothing else is accepted, and nothing is ever given to
eval or exec: a formula in a saved project cannot run code.
"""
import ast
import json
import keyword
import math
import re
import warnings

import numpy as np
from scipy import optimize, special, stats
from statsmodels.tools.numdiff import approx_fprime

from . import data
from .registry import api
from .survival import keep_lines
from .util import code_head, col, table as rtable

J = json.dumps
BASE, FIT0 = '#2f6690', '#b0413e'   # the points' colour and the first fit's (smui-p-survival.js), light theme

LETTERS = 'abcdfghijk'   # JMP skips e, which reads as Euler's number


# ---- the model library of Fit Curve ------------------------------------------------

def _poly(x, p):
    y = np.zeros_like(x, dtype=float) + p[-1]
    for c in p[-2::-1]:
        y = y * x + c
    return y


def _logistic5(x, p):
    a, b, c, d, f = p
    return c + (d - c) / (1 + np.exp(-a * (x - b))) ** f


def _onecomp(x, p):
    a, b, c = p
    return a * b * c / (c - b) * (np.exp(-b * x) - np.exp(-c * x))


# key: (label, family, parameter names, formula, f(x, p), index of the shift parameter or None, needs x > 0)
MODELS = {
    'linear': ('Linear', 'Polynomials', ['Intercept', 'Slope'], 'a + b·x', _poly, 0, False),
    'quadratic': ('Quadratic', 'Polynomials', ['Intercept', 'Linear', 'Quadratic'], 'a + b·x + c·x²', _poly, 0, False),
    'cubic': ('Cubic', 'Polynomials', ['Intercept', 'Linear', 'Quadratic', 'Cubic'], 'a + b·x + c·x² + d·x³', _poly, 0, False),
    'quartic': ('Quartic', 'Polynomials', ['Intercept', 'Linear', 'Quadratic', 'Cubic', 'Quartic'], 'a + b·x + c·x² + d·x³ + f·x⁴', _poly, 0, False),
    'quintic': ('Quintic', 'Polynomials', ['Intercept', 'Linear', 'Quadratic', 'Cubic', 'Quartic', 'Quintic'], 'a + b·x + c·x² + d·x³ + f·x⁴ + g·x⁵', _poly, 0, False),
    'logistic2': ('Logistic 2P', 'Sigmoid Curves', ['Growth Rate', 'Inflection Point'], '1 / (1 + exp(−a·(x − b)))',
                  lambda x, p: special.expit(p[0] * (x - p[1])), 1, False),
    'logistic3': ('Logistic 3P', 'Sigmoid Curves', ['Growth Rate', 'Inflection Point', 'Asymptote'], 'c / (1 + exp(−a·(x − b)))',
                  lambda x, p: p[2] * special.expit(p[0] * (x - p[1])), 1, False),
    'logistic4': ('Logistic 4P', 'Sigmoid Curves', ['Growth Rate', 'Inflection Point', 'Lower Asymptote', 'Upper Asymptote'],
                  'c + (d − c) / (1 + exp(−a·(x − b)))', lambda x, p: p[2] + (p[3] - p[2]) * special.expit(p[0] * (x - p[1])), 1, False),
    'logistic5': ('Logistic 5P', 'Sigmoid Curves', ['Growth Rate', 'Inflection Point', 'Asymptote 1', 'Asymptote 2', 'Power'],
                  'c + (d − c) / (1 + exp(−a·(x − b)))^f', _logistic5, 1, False),
    'probit2': ('Probit 2P', 'Sigmoid Curves', ['Growth Rate', 'Inflection Point'], 'Φ(a·(x − b))',
                lambda x, p: special.ndtr(p[0] * (x - p[1])), 1, False),
    'probit4': ('Probit 4P', 'Sigmoid Curves', ['Growth Rate', 'Inflection Point', 'Lower Asymptote', 'Upper Asymptote'],
                'c + (d − c)·Φ(a·(x − b))', lambda x, p: p[2] + (p[3] - p[2]) * special.ndtr(p[0] * (x - p[1])), 1, False),
    'gompertz3': ('Gompertz 3P', 'Sigmoid Curves', ['Asymptote', 'Growth Rate', 'Inflection Point'], 'a·exp(−exp(−b·(x − c)))',
                  lambda x, p: p[0] * np.exp(-np.exp(-p[1] * (x - p[2]))), 2, False),
    'gompertz4': ('Gompertz 4P', 'Sigmoid Curves', ['Lower Asymptote', 'Upper Asymptote', 'Growth Rate', 'Inflection Point'],
                  'a + (b − a)·exp(−exp(−c·(x − d)))', lambda x, p: p[0] + (p[1] - p[0]) * np.exp(-np.exp(-p[2] * (x - p[3]))), 3, False),
    'weibullgrowth': ('Weibull Growth', 'Sigmoid Curves', ['Asymptote', 'Inflection Point', 'Growth Rate'], 'a·(1 − exp(−(x/b)^c))',
                      lambda x, p: p[0] * (1 - np.exp(-(x / p[1]) ** p[2])), None, True),
    'exp2': ('Exponential 2P', 'Exponential Growth and Decay', ['Scale', 'Growth Rate'], 'a·exp(b·x)',
             lambda x, p: p[0] * np.exp(p[1] * x), None, False),
    'exp3': ('Exponential 3P', 'Exponential Growth and Decay', ['Asymptote', 'Scale', 'Growth Rate'], 'a + b·exp(c·x)',
             lambda x, p: p[0] + p[1] * np.exp(p[2] * x), None, False),
    'biexp4': ('Biexponential 4P', 'Exponential Growth and Decay', ['Scale 1', 'Decay Rate 1', 'Scale 2', 'Decay Rate 2'],
               'a·exp(−b·x) + c·exp(−d·x)', lambda x, p: p[0] * np.exp(-p[1] * x) + p[2] * np.exp(-p[3] * x), None, False),
    'biexp5': ('Biexponential 5P', 'Exponential Growth and Decay', ['Asymptote', 'Scale 1', 'Decay Rate 1', 'Scale 2', 'Decay Rate 2'],
               'a + b·exp(−c·x) + d·exp(−f·x)', lambda x, p: p[0] + p[1] * np.exp(-p[2] * x) + p[3] * np.exp(-p[4] * x), None, False),
    'mechanistic': ('Mechanistic Growth', 'Exponential Growth and Decay', ['Asymptote', 'Scale', 'Growth Rate'], 'a·(1 − b·exp(−c·x))',
                    lambda x, p: p[0] * (1 - p[1] * np.exp(-p[2] * x)), None, False),
    'gaussian': ('Gaussian Peak', 'Peak Models', ['Peak Value', 'Critical Point', 'Growth Rate'], 'a·exp(−(x − b)²/(2c²))',
                 lambda x, p: p[0] * np.exp(-0.5 * ((x - p[1]) / p[2]) ** 2), 1, False),
    'lorentzian': ('Lorentzian Peak', 'Peak Models', ['Peak Value', 'Growth Rate', 'Critical Point'], 'a·b² / ((x − c)² + b²)',
                   lambda x, p: p[0] * p[1] ** 2 / ((x - p[2]) ** 2 + p[1] ** 2), 2, False),
    'onecomp': ('One Compartment Oral Dose', 'Pharmacokinetic Models', ['Area Under Curve', 'Elimination Rate', 'Absorption Rate'],
                '(a·b·c / (c − b))·(exp(−b·x) − exp(−c·x))', _onecomp, None, False),
    'michaelis': ('Michaelis-Menten', 'Other', ['Max Reaction Rate', 'Inverse Affinity'], 'a·x / (b + x)',
                  lambda x, p: p[0] * x / (p[1] + x), None, False),
    'power': ('Power', 'Other', ['Scale', 'Power'], 'a·x^b', lambda x, p: p[0] * x ** p[1], None, True),
    'log': ('Logarithmic', 'Other', ['Intercept', 'Slope'], 'a + b·log(x)', lambda x, p: p[0] + p[1] * np.log(x), None, True),
}
POLY_DEGREE = {'linear': 1, 'quadratic': 2, 'cubic': 3, 'quartic': 4, 'quintic': 5}

# the same models as code, for the Python shown under a fit
MODEL_CODE = {
    'logistic2': 'expit(a*(x - b))', 'logistic3': 'c*expit(a*(x - b))', 'logistic4': 'c + (d - c)*expit(a*(x - b))',
    'logistic5': 'c + (d - c)/(1 + np.exp(-a*(x - b)))**f', 'probit2': 'ndtr(a*(x - b))', 'probit4': 'c + (d - c)*ndtr(a*(x - b))',
    'gompertz3': 'a*np.exp(-np.exp(-b*(x - c)))', 'gompertz4': 'a + (b - a)*np.exp(-np.exp(-c*(x - d)))',
    'weibullgrowth': 'a*(1 - np.exp(-(x/b)**c))', 'exp2': 'a*np.exp(b*x)', 'exp3': 'a + b*np.exp(c*x)',
    'biexp4': 'a*np.exp(-b*x) + c*np.exp(-d*x)', 'biexp5': 'a + b*np.exp(-c*x) + d*np.exp(-f*x)',
    'mechanistic': 'a*(1 - b*np.exp(-c*x))', 'gaussian': 'a*np.exp(-0.5*((x - b)/c)**2)', 'lorentzian': 'a*b**2/((x - c)**2 + b**2)',
    'onecomp': 'a*b*c/(c - b)*(np.exp(-b*x) - np.exp(-c*x))', 'michaelis': 'a*x/(b + x)', 'power': 'a*x**b', 'log': 'a + b*np.log(x)',
}


# ---- starting values ------------------------------------------------------------------

def _lin(u, v, w=None):
    """Slope and intercept of v on u, weighted."""
    u, v = np.asarray(u, float), np.asarray(v, float)
    ok = np.isfinite(u) & np.isfinite(v)
    u, v = u[ok], v[ok]
    ww = None if w is None else np.asarray(w, float)[ok]
    if len(u) < 2 or np.ptp(u) == 0:
        return 0.0, float(np.average(v, weights=ww)) if len(v) else 0.0
    b, a = np.polyfit(u, v, 1, w=None if ww is None else np.sqrt(ww))
    return float(b), float(a)


def _clip(p):
    return np.clip(p, 0.02, 0.98)


def _starts(key, x, y, w):
    """Candidate starting values for model key: the fit keeps the best."""
    xr = float(np.ptp(x)) or 1.0
    ymin, ymax = float(np.min(y)), float(np.max(y))
    yr = (ymax - ymin) or (abs(ymax) or 1.0)
    slope = _lin(x, y, w)[0]
    sgn = 1.0 if slope >= 0 else -1.0
    ext = ymax if abs(ymax) >= abs(ymin) else ymin      # the extreme value, with its sign
    c = []
    if key in POLY_DEGREE:
        deg = POLY_DEGREE[key]
        c.append(list(np.polyfit(x, y, deg, w=np.sqrt(w))[::-1]))
        return c

    def sig(link, lo, hi):
        p = _clip((y - lo) / (hi - lo)) if hi != lo else np.full_like(y, 0.5)
        a, i = _lin(x, link(p), w)
        if a == 0:
            a = sgn * 4.0 / xr
        return a, -i / a

    if key in ('logistic2', 'probit2'):
        link = special.logit if key == 'logistic2' else special.ndtri
        a, b = sig(link, 0.0, 1.0)
        c += [[a, b], [a / 2, b], [a * 2, b]]
    elif key == 'logistic3':
        for asym in (ext * 1.05, ext * 1.25):
            a, b = sig(special.logit, 0.0, asym)
            c.append([a, b, asym])
    elif key in ('logistic4', 'probit4', 'logistic5'):
        link = special.ndtri if key == 'probit4' else special.logit
        lo, hi = ymin - 0.02 * yr, ymax + 0.02 * yr
        a, b = sig(link, lo, hi)
        base = [a, b, lo, hi]
        if key == 'logistic5':
            c += [base + [1.0], base + [0.5], base + [2.0]]
        else:
            c += [base, [a / 2, b, lo, hi], [a * 2, b, lo, hi]]
    elif key == 'gompertz3':
        for asym in (ext * 1.05, ext * 1.3):
            b, i = _lin(x, -np.log(-np.log(_clip(y / asym))), w)
            b = b or sgn * 3.0 / xr
            c.append([asym, b, -i / b])
    elif key == 'gompertz4':
        lo, hi = ymin - 0.02 * yr, ymax + 0.02 * yr
        cc, i = _lin(x, -np.log(-np.log(_clip((y - lo) / (hi - lo)))), w)
        cc = cc or sgn * 3.0 / xr
        c += [[lo, hi, cc, -i / cc], [lo, hi, cc / 2, -i / cc]]
    elif key == 'weibullgrowth':
        for asym in (ext * 1.05, ext * 1.3):
            s, i = _lin(np.log(x), np.log(-np.log(1 - _clip(y / asym))), w)
            s = s if s > 0 else 1.0
            c.append([asym, float(np.exp(-i / s)), s])
    elif key == 'exp2':
        if np.all(y > 0) or np.all(y < 0):
            s = 1.0 if y[0] > 0 else -1.0
            b, i = _lin(x, np.log(np.abs(y)), w)
            c.append([s * math.exp(i), b])
        c += [[float(np.mean(y)), 0.1 / xr], [float(np.mean(y)), -0.1 / xr]]
    elif key == 'exp3':
        for asym in (ymin - 0.1 * yr, ymax + 0.1 * yr, ymin - 0.5 * yr, ymax + 0.5 * yr):
            v = y - asym
            s = 1.0 if np.mean(v) > 0 else -1.0
            cc, i = _lin(x, np.log(np.maximum(s * v, 1e-12 * yr)), w)
            c.append([asym, s * math.exp(i), cc])
    elif key in ('biexp4', 'biexp5'):
        shift = ymin - 0.05 * yr if key == 'biexp5' else 0.0
        yy = y - shift
        order = np.argsort(x)
        xs, ys = x[order], yy[order]
        h = max(2, len(xs) // 2)
        rate = []
        if np.all(ys > 0):
            s2, i2 = _lin(xs[h:] if len(xs) - h >= 2 else xs, np.log(ys[h:] if len(xs) - h >= 2 else ys))
            d2, c2 = max(-s2, 0.1 / xr), math.exp(i2)
            r = ys[:h] - c2 * np.exp(-d2 * xs[:h])
            okr = r > 0
            if okr.sum() >= 2:
                s1, i1 = _lin(xs[:h][okr], np.log(r[okr]))
                d1, c1 = max(-s1, 2 * d2), math.exp(i1)
            else:
                d1, c1 = 5 * d2, float(ys[0]) / 2
            rate.append((c1, d1, c2, d2))
        y0 = float(ys[0]) if len(ys) else 1.0
        rate.append((y0 / 2, 5.0 / xr, y0 / 2, 0.5 / xr))
        for c1, d1, c2, d2 in rate:
            c.append(([shift] if key == 'biexp5' else []) + [c1, d1, c2, d2])
    elif key == 'mechanistic':
        for asym in (ymax + 0.05 * yr, ymin - 0.05 * yr, ymax + 0.3 * yr):
            if asym == 0:
                continue
            v = 1 - y / asym
            s = 1.0 if np.mean(v) > 0 else -1.0
            k, i = _lin(x, np.log(np.maximum(s * v, 1e-9)), w)
            c.append([asym, s * math.exp(i), -k if k != 0 else 1.0 / xr])
    elif key in ('gaussian', 'lorentzian'):
        med = float(np.median(y))
        i = int(np.argmax(np.abs(y - med)))
        a, b = float(y[i]), float(x[i])
        half = x[np.abs(y) >= abs(a) / 2]
        width = float(np.ptp(half)) if len(half) > 1 else xr / 5
        width = width or xr / 5
        if key == 'gaussian':
            c += [[a, b, width / 2.355], [a, b, xr / 6]]
        else:
            c += [[a, width / 2, b], [a, xr / 10, b]]
    elif key == 'onecomp':
        order = np.argsort(x)
        xs, ys = x[order], y[order]
        tail = max(3, len(xs) // 3)
        pos = ys[-tail:] > 0
        kel = -_lin(xs[-tail:][pos], np.log(ys[-tail:][pos]))[0] if pos.sum() >= 2 else 1.0 / xr
        kel = kel if kel > 0 else 1.0 / xr
        tmax = float(xs[int(np.argmax(ys))])
        ka = 3 * kel
        if 0 < tmax < 1 / kel:
            g = lambda k: math.log(k / kel) / (k - kel) - tmax  # noqa: E731
            try:
                ka = optimize.brentq(g, kel * (1 + 1e-6), kel * 1e6)
            except Exception:
                ka = 3 * kel
        auc = float(np.trapezoid(ys, xs) if hasattr(np, 'trapezoid') else np.trapz(ys, xs)) + max(float(ys[-1]), 0) / kel
        c += [[auc, kel, ka], [auc, kel / 2, ka * 2]]
    elif key == 'michaelis':
        order = np.argsort(x)
        xs, ys = x[order], y[order]
        for vmax in (ext * 1.2, ext * 2):
            above = np.flatnonzero(ys >= vmax / 2)
            km = float(xs[above[0]]) if len(above) else float(np.median(xs))
            c.append([vmax, km if km > 0 else float(np.median(np.abs(xs))) or 1.0])
    elif key == 'power':
        if np.all(y > 0) or np.all(y < 0):
            s = 1.0 if y[0] > 0 else -1.0
            b, i = _lin(np.log(x), np.log(np.abs(y)), w)
            c.append([s * math.exp(i), b])
        c.append([float(np.mean(y)), 1.0])
    elif key == 'log':
        b, i = _lin(np.log(x), y, w)
        c.append([i, b])
    return [list(map(float, s)) for s in c if all(np.isfinite(s))]


# ---- least squares --------------------------------------------------------------------

def _residual_fn(f, x, y, sw):
    big = 1e8 * (float(np.ptp(y)) + float(np.max(np.abs(y))) + 1.0)

    def resid(p):
        with np.errstate(all='ignore'):
            r = sw * (f(x, p) - y)
        r = np.asarray(r, dtype=float)
        return np.where(np.isfinite(r), r, big)
    return resid


def _lsq(resid, p0, method='lm', max_nfev=None):
    k = len(p0)
    kw = dict(x_scale='jac', ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=max_nfev or 400 * (k + 1))
    if method != 'lm':
        kw['method'] = method
    else:
        kw['method'] = 'lm'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return optimize.least_squares(resid, np.asarray(p0, dtype=float), **kw)


def _cov(resid, p, mse):
    """MSE (J'J)^-1, J the Jacobian of the weighted residuals at p. The
    columns of J are scaled to unit length first, so that whether the
    parameters are identifiable (the scaled J'J invertible) does not
    depend on their units."""
    J = np.atleast_2d(approx_fprime(np.asarray(p, dtype=float), resid, centered=True))
    if J.shape[0] != len(resid(p)):
        J = J.T
    d = np.sqrt(np.sum(J * J, axis=0))
    d = np.where(np.isfinite(d) & (d > 0), d, 1.0)
    A = (J / d).T @ (J / d)
    singular = False
    try:
        if not np.all(np.isfinite(A)) or np.linalg.cond(A) > 1e12:
            raise np.linalg.LinAlgError
        inv = np.linalg.inv(A)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(A)
        singular = True
    return mse * inv / np.outer(d, d), singular


def _summarize(sse, n, k, sst):
    dfe = n - k
    mse = sse / dfe if dfe > 0 else float('nan')
    K = k + 1                                   # the error variance counts as a parameter
    m2ll = n * math.log(2 * math.pi * sse / n) + n if sse > 0 and n > 0 else float('nan')
    aicc = m2ll + 2 * K + (2 * K * (K + 1) / (n - K - 1) if n - K - 1 > 0 else float('nan'))
    bic = m2ll + K * math.log(n) if n > 0 else float('nan')
    return {'sse': sse, 'dfe': dfe, 'mse': mse, 'rmse': math.sqrt(mse) if mse >= 0 else float('nan'),
            'rsquare': 1 - sse / sst if sst > 0 else float('nan'), 'aicc': aicc, 'bic': bic, 'm2ll': m2ll, 'n': n, 'k': k}


def _estimates(names, p, cov, dfe, alpha):
    se = np.sqrt(np.maximum(np.diag(cov), 0))
    tq = stats.t.ppf(1 - alpha / 2, dfe) if dfe > 0 else float('nan')
    out = []
    for nm, e, s in zip(names, p, se):
        t = e / s if s > 0 else float('nan')
        out.append({'parameter': nm, 'estimate': float(e), 'se': float(s), 'lower': float(e - tq * s), 'upper': float(e + tq * s),
                    't': float(t), 'p': float(2 * stats.t.sf(abs(t), dfe)) if math.isfinite(t) and dfe > 0 else None})
    return out


def _grad_f(f, xg, p):
    """d f(x, p) / dp at each x, by central differences: (len(x), k)."""
    p = np.asarray(p, dtype=float)
    G = np.empty((len(xg), len(p)))
    for j in range(len(p)):
        h = 6e-6 * max(abs(p[j]), 1e-3)
        a, b = p.copy(), p.copy()
        a[j] += h
        b[j] -= h
        with np.errstate(all='ignore'):
            G[:, j] = (f(xg, a) - f(xg, b)) / (2 * h)
    return G


def _band(f, xg, p, cov, dfe, alpha):
    with np.errstate(all='ignore'):
        yg = f(xg, p)
        G = _grad_f(f, xg, p)
        se = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', G, cov, G), 0))
    tq = stats.t.ppf(1 - alpha / 2, dfe) if dfe > 0 else float('nan')
    return yg, yg - tq * se, yg + tq * se


def _fit_one(key, x, y, w, starts=None):
    f = MODELS[key][4]
    sw = np.sqrt(w)
    resid = _residual_fn(f, x, y, sw)
    best = None
    for s in (starts or _starts(key, x, y, w)):
        try:
            r = _lsq(resid, s)
        except Exception:
            continue
        sse = float(np.sum(r.fun ** 2))
        if not np.all(np.isfinite(r.x)) or not math.isfinite(sse):
            continue
        if best is None or sse < best[1] * (1 - 1e-12):
            best = (r, sse)
    if best is None:
        raise ValueError('no starting values led to a fit')
    return best[0], best[1], resid


# ---- Fit Curve ------------------------------------------------------------------------

def _curve_data(table_id, y, x, rows, group, weight, freq):
    df = data.frame(table_id, [y, x, group, weight, freq], rows, dropna=True, as_category=True)
    df, w = data.weights(df, table_id, weight, freq)
    xv = df[x].to_numpy(float)
    yv = df[y].to_numpy(float)
    ok = np.isfinite(xv) & np.isfinite(yv)
    df, xv, yv, w = df[ok], xv[ok], yv[ok], w[ok]
    cnt = data.series(table_id, freq, df.index, as_category=False).to_numpy(float) if freq else np.ones(len(df))
    if group:
        s = df[group]
        if hasattr(s, 'cat'):
            present = set(s.dropna().unique().tolist())
            levels = [lv for lv in s.cat.categories if lv in present]
        else:
            levels = sorted(set(s.tolist()))
        codes = np.array([levels.index(v) for v in s.tolist()])
    else:
        levels, codes = [None], np.zeros(len(df), dtype=int)
    return df, xv, yv, w, cnt, levels, codes


@api('fitcurve.fit')
def fitcurve_fit(table, y, x, model, rows=None, group=None, weight=None, freq=None, alpha=0.05, ci=False,
                 parallel=False, equal=False, inverse=None, where=None, table_name='data'):
    """Fit Curve: one model of the library, per group, with its summary,
    parameter estimates, curve, and on request the tests across groups and
    inverse predictions."""
    if model not in MODELS:
        return {'error': f'no model {model!r}'}
    label, family, names, formula, f, shift, xpos = MODELS[model]
    k = len(names)
    df, xv, yv, w, cnt, levels, codes = _curve_data(table, y, x, rows, group, weight, freq)
    if xpos and np.any(xv <= 0):
        return {'error': f'{label} needs every {x} above zero'}
    out = {'model': model, 'label': label, 'family': family, 'names': names, 'formula': formula,
           'letters': [f'{LETTERS[j]} = {nm}' for j, nm in enumerate(names)], 'groups': []}
    total_sse, total_n = 0.0, 0.0
    fits = []
    for i, lv in enumerate(levels):
        m = codes == i
        n = float(np.sum(cnt[m]))
        g = {'level': lv, 'n': n}
        if n <= k:
            g['error'] = f'needs more than {k} points; this group has {n:g}'
            out['groups'].append(g)
            fits.append(None)
            continue
        try:
            r, sse, resid = _fit_one(model, xv[m], yv[m], w[m])
        except ValueError as ex:
            g['error'] = str(ex)
            out['groups'].append(g)
            fits.append(None)
            continue
        ybar = float(np.average(yv[m], weights=w[m]))
        sst = float(np.sum(w[m] * (yv[m] - ybar) ** 2))
        summ = _summarize(sse, n, k, sst)
        cov, singular = _cov(resid, r.x, summ['mse'])
        if singular:
            warnings.warn(f'{label}{"" if lv is None else f" ({lv})"}: the parameters are not all identifiable; the standard errors are unreliable')
        if not r.success:
            warnings.warn(f'{label}{"" if lv is None else f" ({lv})"}: {r.message}')
        g.update({'params': r.x, 'summary': summ, 'estimates': _estimates(names, r.x, cov, summ['dfe'], alpha),
                  'converged': bool(r.success), 'nfev': int(r.nfev)})
        lo, hi = float(np.min(xv[m])), float(np.max(xv[m]))
        xg = np.linspace(lo, hi, 200)
        if ci:
            yg, bl, bu = _band(f, xg, r.x, cov, summ['dfe'], alpha)
            g['curve'] = {'x': xg, 'y': yg, 'lower': bl, 'upper': bu}
        else:
            with np.errstate(all='ignore'):
                g['curve'] = {'x': xg, 'y': f(xg, r.x)}
        if inverse:
            g['inverse'] = _inverse(f, r.x, cov, summ['dfe'], alpha, lo, hi, inverse)
        total_sse += sse
        total_n += n
        fits.append({'r': r, 'cov': cov, 'n': n})
        out['groups'].append(g)
    good = [q for q in fits if q is not None]
    if not good:
        out['error'] = out['groups'][0].get('error', 'no fit') if out['groups'] else 'no rows'
        return out
    ybar = float(np.average(yv, weights=w))
    sst_all = float(np.sum(w * (yv - ybar) ** 2))
    out['summary'] = _summarize(total_sse, total_n, k * len(good), sst_all)
    # predictions for every row with an x (its group's curve), residuals for the fitted rows
    pf = data.frame(table, [x, group], rows, dropna=True, as_category=True)
    px = pf[x].to_numpy(float)
    pr, pv = [], []
    for i, lv in enumerate(levels):
        if fits[i] is None:
            continue
        mask = np.ones(len(pf), dtype=bool) if group is None else np.array([v == lv for v in pf[group].tolist()])
        with np.errstate(all='ignore'):
            yy = f(px[mask], fits[i]['r'].x)
        pr.extend(pf.index.to_numpy()[mask].tolist())
        pv.extend(yy.tolist())
    out['pred'] = {'rows': pr, 'values': pv}
    rr_, rv_ = [], []
    for i, lv in enumerate(levels):
        if fits[i] is None:
            continue
        m = codes == i
        with np.errstate(all='ignore'):
            rv_.extend((yv[m] - f(xv[m], fits[i]['r'].x)).tolist())
        rr_.extend(df.index.to_numpy()[m].tolist())
    out['resid'] = {'rows': rr_, 'values': rv_}
    ng = len(good)
    if ng >= 2 and (parallel or equal):
        sep_sse, sep_df = total_sse, total_n - k * ng
        idx = [i for i, q in enumerate(fits) if q is not None]
        mask_all = np.isin(codes, idx)
        xa, ya, wa, ca = xv[mask_all], yv[mask_all], w[mask_all], codes[mask_all]
        if equal:
            try:
                r0, sse0, resid0 = _fit_one(model, xa, ya, wa)
                df1 = k * (ng - 1)
                F = ((sse0 - sep_sse) / df1) / (sep_sse / sep_df) if sep_df > 0 and sep_sse > 0 else float('nan')
                out['equal'] = {'F': F, 'df1': df1, 'df2': sep_df, 'p': float(stats.f.sf(F, df1, sep_df)) if math.isfinite(F) else None,
                                'sse_common': sse0, 'sse_separate': sep_sse}
            except ValueError as ex:
                out['equal'] = {'error': str(ex)}
        if parallel and shift is not None:
            out['parallel'] = _parallel(model, xa, ya, wa, ca, idx, fits, sep_sse, sep_df, alpha, levels, cnt[mask_all])
    lines = [code_head(table_name, ['from scipy.optimize import curve_fit', 'from scipy.special import expit, ndtr'])] + keep_lines(table, rows, where) + [
             f'd = df.dropna(subset={json.dumps([c for c in (y, x, group, weight, freq) if c])})   # the rows with every value']
    wf = ' * '.join(f'd[{J(c)}]' for c in (weight, freq) if c)
    if wf:
        lines.append(f'd = d[{wf} > 0]   # the rows with a positive weight')
    args = ', '.join(LETTERS[j] for j in range(k))
    body = MODEL_CODE.get(model) or ' + '.join([LETTERS[0]] + [f'{LETTERS[j]}*x**{j}' for j in range(1, k)])
    out['plot'] = _curve_fragment(model, label, formula, args, body, k, weight, freq, ci, alpha)
    lines += [f'def f(x, {args}):   # {label}', f'    return {body}']
    # starting values: this page's estimates, each group its own, to ten significant digits (a small parameter keeps its value)
    starts = [(lv, [float(f'{float(v):.10g}') for v in q['r'].x]) for lv, q in zip(levels, fits) if q is not None]
    lit = lambda v: json.dumps(v) if isinstance(v, str) else repr(float(v))  # noqa: E731
    if group:
        lines.append(f'starts = {{{", ".join(f"{lit(lv)}: {st}" for lv, st in starts)}}}   # each group\'s starting values: this page\'s estimates')
        lines.append('for level, p0 in starts.items():   # the groups with a fit, in the table\'s order')
        ind = '    '
    else:
        lines.append(f'p0 = {starts[0][1]}   # starting values: this page\'s estimates')
        ind = ''
    wexpr = ''
    if weight:
        wexpr = f', sigma=1/np.sqrt(s[{json.dumps(weight)}])'
    lines += [f'{ind}s = ' + (f'd[d[{json.dumps(group)}] == level]' if group else 'd'),
              f'{ind}p, cov = curve_fit(f, s[{json.dumps(x)}], s[{json.dumps(y)}], p0=p0{wexpr})',
              f'{ind}print({"level, " if group else ""}p, np.sqrt(np.diag(cov)))   # estimates and standard errors']
    if freq:
        at = next(i for i, ln in enumerate(lines) if ln.startswith('def f('))
        lines.insert(at, f'd = d.loc[d.index.repeat(d[{json.dumps(freq)}].astype(int))]   # Freq: each row as many times as its count')
    out['code'] = '\n'.join(lines)
    return out


def _curve_fragment(model, label, formula, args, body, k, weight, freq, ci, alpha):
    """The lines of a Fit Curve model for the page's graph code (the page
    puts the graphs together: the rows, each group's fit, the points): the
    model as a function, and a function that fits it to a group's rows s from
    starting values p0 as the report's code fits it (scipy's curve_fit,
    weighted by Weight times Freq), giving its curve over the rows' X and,
    with Confidence Curves, the pointwise limits (the delta method)."""
    fn = f'f_{model}'
    w = ' * '.join(f's[{J(c)}].to_numpy(float)' for c in (weight, freq) if c) or 'np.ones(len(s))'
    L = [f'def {fn}(x, {args}):   # {label}: {formula}', f'    return {body}', '',
         f'def fit_{model}(s, p0):',
         f'    """{label} fitted to the rows s by least squares from p0 (curve_fit, as the report\'s code fits it): its curve over the rows\' X{" and the confidence curves" if ci else ""}."""',
         '    x, y = s[X].to_numpy(float), s[Y].to_numpy(float)',
         f'    w = {w}   # the weights: Weight times Freq',
         f'    p, pcov = curve_fit({fn}, x, y, p0=p0, sigma=1 / np.sqrt(w))',
         '    gx = np.linspace(x.min(), x.max(), 200)',
         f'    fy = {fn}(gx, *p)']
    if ci:
        L += [f'    n, k = {f"s[{J(freq)}].sum()" if freq else "len(s)"}, len(p)   # the observations (Freq counts rows) and the parameters']
        if freq:
            L.append('    pcov = pcov * (len(s) - k) / (n - k)   # MSE (J\'WJ)^-1, with N the sum of Freq')
        L += ['    h = 6e-6 * np.maximum(np.abs(p), 1e-3)',
              f'    G = np.column_stack([({fn}(gx, *(p + h[j] * np.eye(k)[j])) - {fn}(gx, *(p - h[j] * np.eye(k)[j]))) / (2 * h[j]) for j in range(k)])   # the curve\'s gradient in the parameters',
              '    se = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", G, pcov, G), 0))',
              f'    tq = stats.t.ppf({1 - alpha / 2!r}, n - k)',
              '    return gx, fy, fy - tq * se, fy + tq * se']
    else:
        L.append('    return gx, fy, None, None')
    imports = ['from scipy.optimize import curve_fit', 'from scipy.special import expit, ndtr'] + (['from scipy import stats'] if ci else [])
    return {'imports': imports, 'lines': L, 'fit': f'fit_{model}'}


def _parallel(model, xa, ya, wa, ca, idx, fits, sep_sse, sep_df, alpha, levels, counts):
    """Parallel curves: every parameter shared except the shift (the
    inflection or critical point, or the intercept of a polynomial), one
    per group."""
    label, family, names, formula, f, shift, xpos = MODELS[model]
    k = len(names)
    ng = len(idx)
    others = [j for j in range(k) if j != shift]
    gpos = {g: i for i, g in enumerate(idx)}
    gi = np.array([gpos[c] for c in ca])
    sw = np.sqrt(wa)

    def full(q):
        shared = q[:k - 1]
        shifts = q[k - 1:]
        P = np.empty((len(xa), k))
        for jj, j in enumerate(others):
            P[:, j] = shared[jj]
        P[:, shift] = shifts[gi]
        return P

    def fx(q):
        P = full(q)
        # evaluate row by row through the vectorised model: parameters vary by row
        return f(xa, [P[:, j] for j in range(k)])

    big = 1e8 * (float(np.ptp(ya)) + float(np.max(np.abs(ya))) + 1.0)

    def resid(q):
        with np.errstate(all='ignore'):
            r = sw * (fx(q) - ya)
        return np.where(np.isfinite(r), r, big)

    pars = np.array([fits[i]['r'].x for i in idx])
    q0 = np.r_[pars[:, others].mean(axis=0), pars[:, shift]]
    try:
        r = _lsq(resid, q0)
    except Exception as ex:
        return {'error': str(ex)}
    sse = float(np.sum(r.fun ** 2))
    n = float(np.sum(counts))
    dfp = n - len(q0)
    df1 = (k - 1) * (ng - 1)
    F = ((sse - sep_sse) / df1) / (sep_sse / sep_df) if sep_df > 0 and sep_sse > 0 and df1 > 0 else float('nan')
    mse = sse / dfp if dfp > 0 else float('nan')
    cov, _ = _cov(resid, r.x, mse)
    pn = [names[j] for j in others] + [f'{names[shift]}[{levels[i]}]' for i in idx]
    return {'F': F, 'df1': df1, 'df2': sep_df, 'p': float(stats.f.sf(F, df1, sep_df)) if math.isfinite(F) else None,
            'sse_parallel': sse, 'sse_separate': sep_sse, 'shift': names[shift], 'n': n,
            'estimates': _estimates(pn, r.x, cov, dfp, alpha)}


def _inverse(f, p, cov, dfe, alpha, lo, hi, targets):
    """x where the curve reaches each target y, with Wald limits."""
    span = hi - lo or 1.0
    grid = np.linspace(lo - 0.25 * span, hi + 0.25 * span, 2001)
    with np.errstate(all='ignore'):
        yg = f(grid, p)
    tq = stats.t.ppf(1 - alpha / 2, dfe) if dfe > 0 else float('nan')
    out = []
    for y0 in targets:
        try:
            y0 = float(y0)
        except (TypeError, ValueError):
            continue
        d = yg - y0
        roots = []
        for j in np.flatnonzero(np.isfinite(d[:-1]) & np.isfinite(d[1:]) & (np.sign(d[:-1]) * np.sign(d[1:]) <= 0)):
            if d[j] == 0 and j > 0 and d[j - 1] == 0:
                continue
            try:
                xr = optimize.brentq(lambda v: float(f(np.array([v]), p)[0]) - y0, grid[j], grid[j + 1]) if d[j] != 0 or d[j + 1] != 0 else float(grid[j])
            except ValueError:
                continue
            if roots and abs(xr - roots[-1]) < 1e-9 * span:
                continue
            roots.append(xr)
            if len(roots) >= 3:
                break
        if not roots:
            out.append({'y': y0, 'x': None, 'lower': None, 'upper': None, 'note': 'not reached within the range'})
            continue
        for xr in roots:
            h = 1e-6 * span
            with np.errstate(all='ignore'):
                slope = float((f(np.array([xr + h]), p)[0] - f(np.array([xr - h]), p)[0]) / (2 * h))
                G = _grad_f(f, np.array([xr]), p)[0]
            se = math.sqrt(max(float(G @ cov @ G), 0)) / abs(slope) if slope != 0 else float('nan')
            out.append({'y': y0, 'x': xr, 'lower': xr - tq * se, 'upper': xr + tq * se, 'se': se})
    return out


# ---- the model language of Nonlinear ------------------------------------------------------

FUNCS = {'exp': (np.exp, 1), 'log': (np.log, 1), 'log10': (np.log10, 1), 'sqrt': (np.sqrt, 1), 'abs': (np.abs, 1),
         'sin': (np.sin, 1), 'cos': (np.cos, 1), 'tan': (np.tan, 1), 'arctan': (np.arctan, 1), 'tanh': (np.tanh, 1),
         'minimum': (np.minimum, 2), 'maximum': (np.maximum, 2), 'where': (np.where, 3)}
_BINOPS = {ast.Add: (np.add, '+'), ast.Sub: (np.subtract, '-'), ast.Mult: (np.multiply, '*'), ast.Div: (np.divide, '/'), ast.Pow: (np.power, '**')}
_CMPOPS = {ast.Lt: (np.less, '<'), ast.LtE: (np.less_equal, '<='), ast.Gt: (np.greater, '>'), ast.GtE: (np.greater_equal, '>='),
           ast.Eq: (np.equal, '=='), ast.NotEq: (np.not_equal, '!=')}
MAX_LENGTH = 4000
MAX_NODES = 600
MAX_DEPTH = 80
_COLREF = re.compile(r':\s*[Nn]ame\(\s*"([^"]*)"\s*\)|:\s*"([^"]*)"n?|:\s*([^\W\d]\w*)', re.UNICODE)
_RESERVED_CODE = {'np', 'X', 'p', 'd', 'df', 'model', 'fit', 'pd', 'sm', 'smf', 'least_squares', 'cov', 'J', 'mse'}


class ModelError(ValueError):
    """A model that is not in the language."""


class Model:
    """A parsed model: its parameters (in order of appearance), the columns
    it uses, fn(P, C) to evaluate it, and py, the model as Python code."""

    def __init__(self, text, columns, declared=()):
        self.text = text
        self.params = []
        self.columns = []
        self._declared = list(declared)
        self._table_cols = list(columns)
        self._nodes = 0
        src = self._prepare(text)
        try:
            tree = ast.parse(src, mode='eval')
        except SyntaxError as e:
            raise ModelError(f'the model is not a valid expression ({e.msg})') from None
        except (ValueError, MemoryError, RecursionError):
            raise ModelError('the model is too long or too deeply nested') from None
        self.fn, self.py = self._build(tree.body, 0)
        if not self.params:
            raise ModelError('the model has no parameters to estimate')

    def _prepare(self, text):
        if not isinstance(text, str):
            raise ModelError('the model must be text')
        if len(text) > MAX_LENGTH:
            raise ModelError(f'the model is longer than {MAX_LENGTH} characters')
        refs = []

        def ref(m):
            name = next(g for g in m.groups() if g is not None)
            if name not in self._table_cols:
                raise ModelError(f'there is no column {name!r}')
            if name not in refs:
                refs.append(name)
            return f' __c{refs.index(name)} '
        out = _COLREF.sub(ref, text)
        if '"' in out or "'" in out:
            raise ModelError('quotes belong only in a column reference, :"name with spaces" or :Name("name")')
        self._refs = refs
        return out.replace('^', '**')

    def _column(self, name):
        if name not in self.columns:
            self.columns.append(name)
        return self.columns.index(name)

    def _build(self, node, depth):
        self._nodes += 1
        if self._nodes > MAX_NODES or depth > MAX_DEPTH:
            raise ModelError('the model is too long or too deeply nested')
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ModelError(f'only numbers are allowed as constants, not {v!r}')
            try:
                v = float(v)
            except OverflowError:
                raise ModelError('a number in the model is too large') from None
            return (lambda P, C, v=v: v), repr(v)
        if isinstance(node, ast.Name):
            nm = node.id
            if nm.startswith('__c') and nm[3:].isdigit() and int(nm[3:]) < len(self._refs):
                k = self._column(self._refs[int(nm[3:])])
                return (lambda P, C, k=k: C[k]), ('col', k)
            if nm.startswith('_'):
                raise ModelError(f'names may not start with an underscore: {nm}')
            if nm.lower() in FUNCS:
                raise ModelError(f'{nm} is a function: write {nm}(…)')
            if nm == 'pi' and nm not in self._declared:
                return (lambda P, C: math.pi), 'np.pi'
            if nm in self._table_cols and nm not in self._declared:
                k = self._column(nm)
                return (lambda P, C, k=k: C[k]), ('col', k)
            if nm not in self.params:
                self.params.append(nm)
            i = self.params.index(nm)
            return (lambda P, C, i=i: P[i]), ('par', i)
        if isinstance(node, ast.UnaryOp):
            f, s = self._build(node.operand, depth + 1)
            if isinstance(node.op, ast.USub):
                return (lambda P, C, f=f: np.negative(f(P, C))), ('neg', s)
            if isinstance(node.op, ast.UAdd):
                return f, s
            raise ModelError(f'the operator {type(node.op).__name__} is not allowed')
        if isinstance(node, ast.BinOp):
            if type(node.op) not in _BINOPS:
                raise ModelError(f'the operator {type(node.op).__name__} is not allowed (use + − * / ^)')
            op, sym = _BINOPS[type(node.op)]
            lf, ls = self._build(node.left, depth + 1)
            rf, rs = self._build(node.right, depth + 1)
            return (lambda P, C, lf=lf, rf=rf, op=op: op(lf(P, C), rf(P, C))), ('bin', sym, ls, rs)
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or type(node.ops[0]) not in _CMPOPS:
                raise ModelError('a comparison has one operator: <, <=, >, >=, == or !=')
            op, sym = _CMPOPS[type(node.ops[0])]
            lf, ls = self._build(node.left, depth + 1)
            rf, rs = self._build(node.comparators[0], depth + 1)
            return (lambda P, C, lf=lf, rf=rf, op=op: op(lf(P, C), rf(P, C))), ('bin', sym, ls, rs)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id.lower() not in FUNCS:
                name = node.func.id if isinstance(node.func, ast.Name) else type(node.func).__name__
                raise ModelError(f'{name}() is not one of the functions: {", ".join(sorted(FUNCS))}')
            if node.keywords:
                raise ModelError('functions take plain arguments, no name=value')
            fname = node.func.id.lower()
            fn, arity = FUNCS[fname]
            if len(node.args) != arity or any(isinstance(a, ast.Starred) for a in node.args):
                raise ModelError(f'{fname}() takes {arity} argument{"s" if arity > 1 else ""}')
            parts = [self._build(a, depth + 1) for a in node.args]
            fs = [p[0] for p in parts]
            return (lambda P, C, fn=fn, fs=fs: fn(*[g(P, C) for g in fs])), ('call', fname, [p[1] for p in parts])
        raise ModelError(f'{type(node).__name__} is not allowed in a model: use numbers, names, + − * / ^, comparisons and the listed functions')

    def evaluate(self, params, cols):
        with np.errstate(all='ignore'):
            v = self.fn(np.asarray(params, dtype=float), cols)
        return np.asarray(v, dtype=float) * np.ones(len(cols[0]) if cols else 1)

    def code(self, pname, cname):
        """The model as Python: pname(i) and cname(k) name a parameter and a column."""
        def emit(s):
            if isinstance(s, str):
                return s
            kind = s[0]
            if kind == 'col':
                return cname(s[1])
            if kind == 'par':
                return pname(s[1])
            if kind == 'neg':
                return f'(-{emit(s[1])})'
            if kind == 'bin':
                return f'({emit(s[2])} {s[1]} {emit(s[3])})'
            if kind == 'call':
                return f'np.{s[1]}({", ".join(emit(a) for a in s[2])})'
            raise ModelError('internal: unknown node')
        out = emit(self.py)
        return out[1:-1] if out.startswith('(') and out.endswith(')') and _balanced(out[1:-1]) else out


def _balanced(s):
    depth = 0
    for ch in s:
        depth += (ch == '(') - (ch == ')')
        if depth < 0:
            return False
    return depth == 0


def _table_columns(table_id):
    return list(data.TABLES[table_id]['meta'].keys())


@api('nonlinear.parse')
def nonlinear_parse(table, model, declared=None):
    """The parameters and columns of a typed model, or what is wrong with it."""
    try:
        m = Model(model, _table_columns(table), declared or ())
    except ModelError as e:
        return {'error': str(e)}
    return {'params': m.params, 'columns': m.columns}


@api('nonlinear.fit')
def nonlinear_fit(table, y, model, start=None, rows=None, weight=None, freq=None, method='lm', max_nfev=None, alpha=0.05,
                  ci=False, where=None, plot=None, table_name='data'):
    """Nonlinear: least squares for a typed model."""
    start = dict(start or {})
    try:
        m = Model(model, _table_columns(table), list(start))
    except ModelError as e:
        return {'error': str(e)}
    for c in m.columns:
        if data.meta(table, c).get('dataType') != 'numeric':
            return {'error': f'the column {c} is not numeric'}
    if y in m.columns:
        return {'error': f'the model uses the response {y} itself'}
    df = data.frame(table, [y] + m.columns + [weight, freq], rows, dropna=True, as_category=False)
    df, w = data.weights(df, table, weight, freq)
    yv = df[y].to_numpy(float)
    C = [df[c].to_numpy(float) for c in m.columns]
    ok = np.isfinite(yv)
    for cv in C:
        ok &= np.isfinite(cv)
    df, yv, w = df[ok], yv[ok], w[ok]
    C = [cv[ok] for cv in C]
    k = len(m.params)
    n = float(np.sum(data.series(table, freq, df.index, as_category=False).to_numpy(float))) if freq else float(len(yv))
    if n <= k:
        return {'error': f'{k} parameters need more than {k} rows with values; there are {n:g}'}
    missing = [p for p in m.params if p not in start]
    p0 = []
    for p in m.params:
        try:
            v = float(start.get(p, 1.0))
        except (TypeError, ValueError):
            return {'error': f'the starting value of {p} is not a number'}
        if not math.isfinite(v):
            return {'error': f'the starting value of {p} is not a finite number'}
        p0.append(v)
    sw = np.sqrt(w)

    def resid(q):
        with np.errstate(all='ignore'):
            r = sw * (m.evaluate(q, C) - yv)
        return np.where(np.isfinite(r), r, 1e8 * (float(np.ptp(yv)) + float(np.max(np.abs(yv))) + 1.0))

    r0 = resid(np.asarray(p0))
    if not np.all(np.isfinite(m.evaluate(p0, C))):
        return {'error': 'the model cannot be evaluated at the starting values (a log or square root of a negative number, a division by zero, an overflow): change them'}
    method = method if method in ('lm', 'trf', 'dogbox') else 'lm'
    try:
        r = _lsq(resid, p0, method=method, max_nfev=int(max_nfev) if max_nfev else None)
    except Exception as ex:
        return {'error': f'the fit failed: {ex}'}
    sse = float(np.sum(r.fun ** 2))
    ybar = float(np.average(yv, weights=w))
    sst = float(np.sum(w * (yv - ybar) ** 2))
    summ = _summarize(sse, n, k, sst)
    cov, singular = _cov(resid, r.x, summ['mse'])
    if singular:
        warnings.warn('the parameters are not all identifiable at the solution; the standard errors are unreliable')
    if not r.success:
        warnings.warn(f'the fit did not converge: {r.message}')
    sd = np.sqrt(np.maximum(np.diag(cov), 1e-300))
    R = cov / np.outer(sd, sd)
    lv = f'{100 * (1 - alpha):g}%'
    out = {'params': m.params, 'columns': m.columns, 'missing_start': missing, 'start': p0, 'estimates_raw': r.x,
           'estimates': rtable([col('parameter', 'Parameter', 'text'), col('estimate', 'Estimate'), col('se', 'ApproxStdErr'),
                                col('lower', f'Lower CL ({lv})'), col('upper', f'Upper CL ({lv})'), col('t', 't Ratio'), col('p', 'Prob>|t|', 'p')],
                               _estimates(m.params, r.x, cov, summ['dfe'], alpha)),
           'solution': summ, 'sse_start': float(np.sum(r0 ** 2)),
           'corr': rtable([col('parameter', 'Parameter', 'text')] + [col(f'c{j}', nm) for j, nm in enumerate(m.params)],
                          [{'parameter': nm, **{f'c{j}': R[i, j] for j in range(k)}} for i, nm in enumerate(m.params)]),
           'status': {'converged': bool(r.success), 'message': r.message, 'nfev': int(r.nfev), 'njev': int(r.njev) if r.njev is not None else None,
                      'optimality': float(r.optimality), 'method': method}}
    if len(m.columns) == 1:
        lo, hi = float(np.min(C[0])), float(np.max(C[0]))
        xg = np.linspace(lo, hi, 200)
        f1 = lambda xx, q: m.evaluate(q, [xx])  # noqa: E731
        if ci:
            yg, bl, bu = _band(f1, xg, r.x, cov, summ['dfe'], alpha)
            out['curve'] = {'x': xg, 'y': yg, 'lower': bl, 'upper': bu}
        else:
            out['curve'] = {'x': xg, 'y': f1(xg, r.x)}
        out['x'] = m.columns[0]
    # every row with the model's columns gets a prediction; the fitted rows a residual
    pf = data.frame(table, m.columns, rows, dropna=True, as_category=False)
    PC = [pf[c].to_numpy(float) for c in m.columns]
    okp = np.ones(len(pf), dtype=bool)
    for cv in PC:
        okp &= np.isfinite(cv)
    pv = m.evaluate(r.x, [cv[okp] for cv in PC]) if okp.any() else np.zeros(0)
    out['pred'] = {'rows': pf.index.to_numpy()[okp], 'values': pv}
    out['resid'] = {'rows': df.index.to_numpy(), 'values': yv - m.evaluate(r.x, C)}
    # the code: the model as a Python function of the parameters and the columns
    safe = all(p.isidentifier() and not keyword.iskeyword(p) and p not in _RESERVED_CODE for p in m.params)
    pname = (lambda i: m.params[i]) if safe else (lambda i: f'p[{i}]')
    body = m.code(pname, lambda kk: f'X[{json.dumps(m.columns[kk])}]')
    keep = keep_lines(table, rows, where)
    lines = [code_head(table_name, ['from scipy.optimize import least_squares'])] + keep + [
             f'd = df.dropna(subset={json.dumps([c for c in [y] + m.columns + [weight, freq] if c])})   # the rows with every value']
    wf = ' * '.join(f'd[{J(c)}]' for c in (weight, freq) if c)
    if wf:
        lines.append(f'd = d[{wf} > 0]   # the rows with a positive weight')
    if freq:
        lines.append(f'd = d.loc[d.index.repeat(d[{json.dumps(freq)}].astype(int))]   # Freq: each row as many times as its count')
    lines += ['def model(p, X):']
    if safe:
        lines.append(f'    {", ".join(m.params)}{"," if k == 1 else ""} = p')
    lines += [f'    return {body}']
    wexpr = f' * np.sqrt(d[{json.dumps(weight)}])' if weight else ''
    lines += [f'fit = least_squares(lambda p: (model(p, d) - d[{json.dumps(y)}]){wexpr}, x0={[float(v) for v in p0]}, method={method!r})',
              'J = fit.jac; mse = (fit.fun ** 2).sum() / (len(d) - len(fit.x))',
              'cov = mse * np.linalg.inv(J.T @ J)',
              f'print(dict(zip({m.params!r}, fit.x)), np.sqrt(np.diag(cov)))   # estimates, approximate standard errors']
    out['code'] = '\n'.join(lines)
    if plot is not None and len(m.columns) == 1:
        out['plot_code'] = _nonlinear_plot(table_name, keep, y, m, safe, pname, p0, method, weight, freq, ci, alpha, plot)
    return out


def _nonlinear_plot(table_name, keep, y, m, safe, pname, p0, method, weight, freq, ci, alpha, plot):
    """Nonlinear's plot (a model of one column): the fit as the report's
    code makes it (least squares from the starting values), the curve over
    the column's range, with Confidence Curves the pointwise limits (the
    delta method, MSE (J'J)^-1 with J by central differences), the rows."""
    c = m.columns[0]
    k = len(m.params)
    body = m.code(pname, lambda kk: f'X[{J(m.columns[kk])}]')
    w = ' * '.join(f'd[{J(v)}].to_numpy(float)' for v in (weight, freq) if v) or 'np.ones(len(d))'
    W, H = plot.get('size') or [480, 320]
    L = [f'Y, C = {J(y)}, {J(c)}   # the response and the model\'s column',
         f'd = df.dropna(subset={J([v for v in [y, c, weight, freq] if v])})   # the rows with every value']
    if weight or freq:
        L.append(f'd = d[{" * ".join(f"d[{J(v)}]" for v in (weight, freq) if v)} > 0]   # the rows with a positive weight')
    L += ['def model(p, X):']
    if safe:
        L.append(f'    {", ".join(m.params)}{"," if k == 1 else ""} = p')
    L += [f'    return {body}',
          f'w = {w}   # the weights: Weight times Freq',
          'resid = lambda p: (model(p, d) - d[Y].to_numpy(float)) * np.sqrt(w)',
          f'fit = least_squares(resid, x0={[float(v) for v in p0]}, method={method!r})   # from the starting values, as the report\'s code fits it',
          'gx = np.linspace(d[C].min(), d[C].max(), 200)',
          'fy = model(fit.x, {C: gx})']
    if ci:
        L += [f'n, k = {f"d[{J(freq)}].sum()" if freq else "len(d)"}, len(fit.x)   # the observations (Freq counts rows) and the parameters',
              'mse = np.sum(resid(fit.x) ** 2) / (n - k)',
              'J = np.atleast_2d(approx_fprime(fit.x, resid, centered=True))',
              'J = J if J.shape[0] == len(w) else J.T   # a row for each observation',
              'cov = mse * np.linalg.inv(J.T @ J)   # the approximate covariance of the estimates',
              'h = 6e-6 * np.maximum(np.abs(fit.x), 1e-3)',
              'G = np.column_stack([(model(fit.x + h[j] * np.eye(k)[j], {C: gx}) - model(fit.x - h[j] * np.eye(k)[j], {C: gx})) / (2 * h[j]) for j in range(k)])   # the curve\'s gradient in the parameters',
              'se = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", G, cov, G), 0))',
              f'tq = stats.t.ppf({1 - alpha / 2!r}, n - k)']
    L += [f'fig, ax = plt.subplots(figsize=({round(float(W)) / 100:g}, {round(float(H)) / 100:g}), layout="constrained")']
    if ci:
        L.append(f'ax.fill_between(gx, fy - tq * se, fy + tq * se, color="{FIT0}", alpha=0.14, linewidth=0)   # Confidence Curves')
    L += [f'ax.plot(gx, fy, color="{FIT0}", linewidth=2, label="Fit")',
          f'ax.scatter(d[C], d[Y], s=18, color="{BASE}", label=Y, zorder=3)',
          'ax.set_xlabel(C)', 'ax.set_ylabel(Y)',
          'fig.suptitle(Y + " by " + C, fontsize=10)', 'plt.show()']
    imports = ['import matplotlib.pyplot as plt', 'from scipy.optimize import least_squares'] + (['from scipy import stats', 'from statsmodels.tools.numdiff import approx_fprime'] if ci else [])
    return '\n'.join([code_head(table_name, imports)] + list(keep) + L)
