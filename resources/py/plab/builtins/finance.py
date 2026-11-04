"""Finance: option prices and sensitivities (blsprice and the other Black-
Scholes functions, blsimpv, blkprice, binprice), cash flows (irr, mirr, xirr,
pvvar, fvvar, pvfix, fvfix, payper, amortize, annurate, annuterm, effrr,
nomrr), returns (price2ret, ret2price, tick2ret, ret2tick, ewstats),
technical indicators (movavg, bollinger, rsindex, macd) and dates (daysact,
days360, yearfrac, holidays, isbusday, busdate, fbusdate, lbusdate).

Rates are per period (annual and continuously compounded for the option
formulas); dates are serial date numbers, datetimes or text, and come back
as datetimes when given as datetimes.
"""
import datetime as _dt
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, darr, out, opt_str, is_str, sval, num
from ..values import MError, Char, Cell, Struct, Str, EMPTY, numel, py_str, class_of
from .. import runtime as R


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy or SciPy refuses told as the function's own error."""
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError, OverflowError, np.linalg.LinAlgError) as e:
                raise err(f'finance:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _st():
    import scipy.stats as st
    return st


def _arrs(args, names, fn, defaults=None):
    """The numeric inputs broadcast against one another (defaults for those left out or empty)."""
    vals = []
    for k, nm in enumerate(names):
        if k < len(args) and numel(args[k]):
            a = np.asarray(darr(args[k], fn), float)
        elif defaults is not None and nm in defaults:
            a = np.asarray(defaults[nm], float)
        else:
            raise err(f'finance:{fn}:MissingInput', f'{fn} needs {nm}.', fn)
        vals.append(a)
    try:
        b = np.broadcast_arrays(*vals)
    except ValueError:
        raise err(f'finance:{fn}:SizeMismatch', 'The inputs are scalars or arrays of one size.', fn)
    return [np.array(x, float) for x in b]


def _pairs(args, fn, names):
    pos, opts = [], {}
    k = 0
    args = list(args)
    while k < len(args):
        o = opt_str(args[k])
        if o is not None and o.lower() in names and k + 1 < len(args):
            opts[o.lower()] = args[k + 1]
            k += 2
            continue
        pos.append(args[k])
        k += 1
    return pos, opts


def _two(nargout, a, b):
    return (out(a), out(b)) if nargout > 1 else out(a)


# ---- Black-Scholes -------------------------------------------------------------------------------------------------------

def _d12(S, K, r, T, sig, q):
    with np.errstate(divide='ignore', invalid='ignore'):
        st = sig * np.sqrt(T)
        d1 = (np.log(S / K) + (r - q + sig ** 2 / 2) * T) / st
    return d1, d1 - st


def _bls_args(args, fn):
    nargchk(args, 5, 6, fn)
    S, K, r, T, sig, q = _arrs(args, ['Price', 'Strike', 'Rate', 'Time', 'Volatility', 'Yield'], fn, {'Yield': 0.0})
    if np.any(S < 0) or np.any(K < 0) or np.any(T < 0) or np.any(sig < 0):
        raise err(f'finance:{fn}:Negative', 'Price, Strike, Time and Volatility are not negative.', fn)
    return S, K, r, T, sig, q


@bi('blsprice', nout=2)
def blsprice(nargout, *args):
    """[Call, Put] = blsprice(Price, Strike, Rate, Time, Volatility, Yield):
    European option prices by Black and Scholes; Rate and Yield continuously
    compounded per year, Time in years."""
    S, K, r, T, sig, q = _bls_args(args, 'blsprice')
    N = _st().norm.cdf
    d1, d2 = _d12(S, K, r, T, sig, q)
    call = S * np.exp(-q * T) * N(d1) - K * np.exp(-r * T) * N(d2)
    put = K * np.exp(-r * T) * N(-d2) - S * np.exp(-q * T) * N(-d1)
    # at expiry, or no volatility: the discounted payoff of the forward
    fwd = S * np.exp((r - q) * T)
    edge = (T == 0) | (sig == 0)
    call = np.where(edge, np.exp(-r * T) * np.maximum(fwd - K, 0), call)
    put = np.where(edge, np.exp(-r * T) * np.maximum(K - fwd, 0), put)
    return _two(nargout, call, put)


@bi('blsdelta', nout=2)
def blsdelta(nargout, *args):
    """[CallDelta, PutDelta] = blsdelta(Price, Strike, Rate, Time, Volatility, Yield): the prices' sensitivity to the asset price."""
    S, K, r, T, sig, q = _bls_args(args, 'blsdelta')
    d1, d2 = _d12(S, K, r, T, sig, q)
    N = _st().norm.cdf
    c = np.exp(-q * T) * N(d1)
    return _two(nargout, c, c - np.exp(-q * T))


@bi('blsgamma')
def blsgamma(nargout, *args):
    """Gamma = blsgamma(Price, Strike, Rate, Time, Volatility, Yield): delta's sensitivity to the asset price (calls and puts alike)."""
    S, K, r, T, sig, q = _bls_args(args, 'blsgamma')
    d1, d2 = _d12(S, K, r, T, sig, q)
    return out(np.exp(-q * T) * _st().norm.pdf(d1) / (S * sig * np.sqrt(T)))


@bi('blsvega')
def blsvega(nargout, *args):
    """Vega = blsvega(Price, Strike, Rate, Time, Volatility, Yield): the price's sensitivity to the volatility."""
    S, K, r, T, sig, q = _bls_args(args, 'blsvega')
    d1, d2 = _d12(S, K, r, T, sig, q)
    return out(S * np.exp(-q * T) * _st().norm.pdf(d1) * np.sqrt(T))


@bi('blstheta', nout=2)
def blstheta(nargout, *args):
    """[CallTheta, PutTheta] = blstheta(Price, Strike, Rate, Time, Volatility, Yield): the prices' change per year as time passes."""
    S, K, r, T, sig, q = _bls_args(args, 'blstheta')
    d1, d2 = _d12(S, K, r, T, sig, q)
    st = _st()
    a = -S * np.exp(-q * T) * st.norm.pdf(d1) * sig / (2 * np.sqrt(T))
    call = a - r * K * np.exp(-r * T) * st.norm.cdf(d2) + q * S * np.exp(-q * T) * st.norm.cdf(d1)
    put = a + r * K * np.exp(-r * T) * st.norm.cdf(-d2) - q * S * np.exp(-q * T) * st.norm.cdf(-d1)
    return _two(nargout, call, put)


@bi('blsrho', nout=2)
def blsrho(nargout, *args):
    """[CallRho, PutRho] = blsrho(Price, Strike, Rate, Time, Volatility, Yield): the prices' sensitivity to the interest rate."""
    S, K, r, T, sig, q = _bls_args(args, 'blsrho')
    d1, d2 = _d12(S, K, r, T, sig, q)
    N = _st().norm.cdf
    return _two(nargout, K * T * np.exp(-r * T) * N(d2), -K * T * np.exp(-r * T) * N(-d2))


@bi('blslambda', nout=2)
def blslambda(nargout, *args):
    """[CallEl, PutEl] = blslambda(Price, Strike, Rate, Time, Volatility, Yield): the elasticities (delta times price over option price)."""
    S, K, r, T, sig, q = _bls_args(args, 'blslambda')
    c, p = blsprice(2, *args)
    dc, dp = blsdelta(2, *args)
    with np.errstate(divide='ignore', invalid='ignore'):
        return _two(nargout, np.asarray(dc) * S / np.asarray(c), np.asarray(dp) * S / np.asarray(p))


def _class_flags(v, n, fn):
    """Calls (true) and puts (false) from logical values or 'call'/'put' texts."""
    if v is None:
        return np.ones(n, bool)
    if type(v) in (Cell, Str) or is_str(v):
        items = [py_str(x) if is_str(x) else x for x in (v.a.reshape(-1, order='F') if type(v) in (Cell, Str) else [v])]
        flags = []
        for x in items:
            s = str(x).lower()
            if s not in ('call', 'put'):
                raise err(f'finance:{fn}:InvalidClass', "Class is 'call' or 'put' (or true for a call).", fn)
            flags.append(s == 'call')
        a = np.array(flags, bool)
    else:
        a = np.asarray(darr(v)).reshape(-1).astype(bool)
    return np.broadcast_to(a, (n,)) if a.size in (1, n) else a


@bi('blsimpv')
def blsimpv(nargout, *args):
    """Volatility = blsimpv(Price, Strike, Rate, Time, Value, 'Limit', 10,
    'Yield', q, 'Tolerance', 1e-6, 'Class', {'call'}): the Black-Scholes
    implied volatility of option prices (NaN where none gives the price)."""
    nargchk(args, 5, 13, 'blsimpv')
    pos, opts = _pairs(args, 'blsimpv', ('limit', 'yield', 'tolerance', 'class', 'method'))
    old = pos[5:]
    for key, v in zip(('limit', 'yield', 'tolerance', 'class'), old):
        if numel(v):
            opts.setdefault(key, v)
    S, K, r, T, V = _arrs(pos[:5], ['Price', 'Strike', 'Rate', 'Time', 'Value'], 'blsimpv')
    q = np.broadcast_to(np.asarray(darr(opts['yield']), float), S.shape) if 'yield' in opts else np.zeros_like(S)
    lim = float(num(opts['limit'])) if 'limit' in opts else 10.0
    tol = float(num(opts['tolerance'])) if 'tolerance' in opts else 1e-6
    calls = _class_flags(opts.get('class'), S.size, 'blsimpv').reshape(S.shape) if 'class' in opts else np.ones(S.shape, bool)
    from scipy.optimize import brentq
    res = np.full(S.shape, np.nan)
    for idx in np.ndindex(S.shape):
        s, k, rr, t, v, qq, c = S[idx], K[idx], r[idx], T[idx], V[idx], q[idx], calls[idx]

        def f(sig):
            pr = blsprice(2, s, k, rr, t, sig, qq)
            return float(pr[0] if c else pr[1]) - v
        try:
            lo, hi = f(1e-12), f(lim)
            if lo * hi > 0:
                continue
            res[idx] = brentq(f, 1e-12, lim, xtol=tol * 1e-3, rtol=1e-14, maxiter=200)
        except (ValueError, ZeroDivisionError):
            continue
    return out(res)


@bi('blkprice', nout=2)
def blkprice(nargout, *args):
    """[Call, Put] = blkprice(Price, Strike, Rate, Time, Volatility): Black's
    prices of European options on futures (Price the futures price)."""
    nargchk(args, 5, 5, 'blkprice')
    F, K, r, T, sig = _arrs(args, ['Price', 'Strike', 'Rate', 'Time', 'Volatility'], 'blkprice')
    N = _st().norm.cdf
    d1, d2 = _d12(F, K, 0.0, T, sig, 0.0)
    df = np.exp(-r * T)
    return _two(nargout, df * (F * N(d1) - K * N(d2)), df * (K * N(-d2) - F * N(-d1)))


@bi('binprice', nout=2)
def binprice(nargout, *args):
    """[AssetPrice, OptionValue] = binprice(Price, Strike, Rate, Time,
    Increment, Volatility, Flag, DividendRate): the Cox-Ross-Rubinstein
    binomial trees of an American option (Flag 1 a call, 0 a put); the
    option's value is OptionValue(1, 1)."""
    nargchk(args, 7, 10, 'binprice')
    S, K, r, T, dt, sig, flag = (float(num(a)) for a in args[:7])
    q = float(num(args[7])) if len(args) > 7 and numel(args[7]) else 0.0
    if len(args) > 8 and numel(args[8]) and np.any(np.asarray(darr(args[8])) != 0):
        raise err('finance:binprice:Dividends', 'Discrete dividends are not taken here: give DividendRate, a continuous yield.', 'binprice')
    if dt <= 0 or T < 0 or sig <= 0:
        raise err('finance:binprice:InvalidInput', 'Increment and Volatility are positive, Time not negative.', 'binprice')
    n = int(round(T / dt))
    u = math.exp(sig * math.sqrt(dt))
    d = 1 / u
    p = (math.exp((r - q) * dt) - d) / (u - d)
    if not 0 <= p <= 1:
        raise err('finance:binprice:Arbitrage', 'The step is too long for this rate and volatility (the up probability leaves [0, 1]).', 'binprice')
    disc = math.exp(-r * dt)
    A = np.zeros((n + 1, n + 1))
    for j in range(n + 1):
        i = np.arange(j + 1)
        A[i, j] = S * u ** (j - i) * d ** i
    payoff = (lambda x: np.maximum(x - K, 0)) if flag else (lambda x: np.maximum(K - x, 0))
    O = np.zeros((n + 1, n + 1))
    O[:, n] = payoff(A[:, n])
    for j in range(n - 1, -1, -1):
        i = np.arange(j + 1)
        cont = disc * (p * O[i, j + 1] + (1 - p) * O[i + 1, j + 1])
        O[i, j] = np.maximum(cont, payoff(A[i, j]))
    return _two(nargout, A, O)


# ---- cash flows ---------------------------------------------------------------------------------------------------------------

def _flows(v, fn):
    a = np.asarray(darr(v, fn), float)
    if a.ndim == 2 and a.shape[0] == 1:
        a = a.T
    return a


def _irr_one(cf):
    """The rates r > -1 at which the flows' present value is 0 (roots of the polynomial in 1/(1+r))."""
    c = np.trim_zeros(cf, 'f')
    if c.size < 2:
        return []
    roots = np.roots(c)                       # in x = 1 + r: c0 x^n + c1 x^(n-1) + ... = 0
    found = []
    for x in roots:
        if abs(x.imag) < 1e-9 * max(1.0, abs(x.real)) and x.real > 0:
            found.append(x.real - 1)
    return sorted(set(round(v, 14) for v in found))


@bi('irr')
def irr(nargout, *args):
    """Return = irr(CashFlow): the internal rate of return per period of
    each column of cash flows (the first at time 0); with several rates,
    the one nearest 0, with a warning."""
    nargchk(args, 1, 1, 'irr')
    cf = _flows(args[0], 'irr')
    res = []
    for j in range(cf.shape[1]):
        rates = _irr_one(cf[:, j])
        if not rates:
            res.append(np.nan)
            continue
        if len(rates) > 1:
            R.warn('finance:irr:multipleIRR', f'These cash flows have {len(rates)} rates of return: ' + ', '.join(f'{v:.6g}' for v in rates) + '; the one nearest 0 is given.')
        res.append(min(rates, key=abs))
    return out(np.array([res]))


@bi('mirr')
def mirr(nargout, *args):
    """Return = mirr(CashFlow, FinRate, Reinvest): the modified internal rate
    of return: the outflows discounted at FinRate, the inflows compounded at
    Reinvest to the end."""
    nargchk(args, 3, 3, 'mirr')
    cf = _flows(args[0], 'mirr')
    fr, rr = float(num(args[1])), float(num(args[2]))
    n = cf.shape[0] - 1
    res = []
    t = np.arange(n + 1)
    for j in range(cf.shape[1]):
        c = cf[:, j]
        pv_neg = -np.sum(np.where(c < 0, c, 0) / (1 + fr) ** t)
        fv_pos = np.sum(np.where(c > 0, c, 0) * (1 + rr) ** (n - t))
        res.append((fv_pos / pv_neg) ** (1 / n) - 1 if pv_neg > 0 and fv_pos > 0 and n > 0 else np.nan)
    return out(np.array([res]))


def _datenums(v, fn):
    """Serial date numbers from numbers, datetimes or text."""
    from .timetypes import DateTime
    if isinstance(v, DateTime):
        return np.asarray(v.a, float) / 86400.0 + 719529.0
    if is_str(v) or type(v) in (Cell, Str):
        return np.asarray(darr(REG['datenum'].fn(1, v)), float)
    return np.asarray(darr(v, fn), float)


def _dates_out(dn, like):
    from .timetypes import DateTime
    dn = np.asarray(dn, float)
    if isinstance(like, DateTime):
        return DateTime((dn - 719529.0) * 86400.0, 'dd-MMM-uuuu', like.tz)
    return out(dn)


@bi('xirr')
def xirr(nargout, *args):
    """Return = xirr(CashFlow, CashFlowDates, Guess, MaxIterations, Basis):
    the annual internal rate of return of cash flows on dates (days over
    365, or the basis's year)."""
    nargchk(args, 2, 5, 'xirr')
    cf = _flows(args[0], 'xirr')
    d = _datenums(args[1], 'xirr').reshape(-1)
    if d.size != cf.shape[0]:
        raise err('finance:xirr:SizeMismatch', 'There is a date for each cash flow.', 'xirr')
    guess = float(num(args[2])) if len(args) > 2 and numel(args[2]) else 0.1
    from scipy.optimize import brentq, newton
    res = []
    yrs = (d - d[0]) / 365.0
    for j in range(cf.shape[1]):
        c = cf[:, j]
        f = lambda r: float(np.sum(c / (1 + r) ** yrs))
        try:
            r = newton(f, guess, maxiter=100, tol=1e-12)
            if not np.isfinite(r) or r <= -1:
                raise RuntimeError
        except (RuntimeError, OverflowError, ZeroDivisionError):
            grid = np.concatenate([np.linspace(-0.99, 1, 200), np.linspace(1, 100, 200)])
            vals = [f(g) for g in grid]
            r = np.nan
            for a, b, fa, fb in zip(grid[:-1], grid[1:], vals[:-1], vals[1:]):
                if np.isfinite(fa) and np.isfinite(fb) and fa * fb <= 0:
                    r = brentq(f, a, b, xtol=1e-14)
                    break
        res.append(r)
    return out(np.array([res]))


@bi('pvvar')
def pvvar(nargout, *args):
    """PresentVal = pvvar(CashFlow, Rate, CFDates): the present value of
    varying cash flows, the first at time 0, one period apart (or on dates,
    with the rate per year of 365 days)."""
    nargchk(args, 2, 3, 'pvvar')
    cf = _flows(args[0], 'pvvar')
    r = float(num(args[1]))
    if len(args) > 2 and numel(args[2]):
        d = _datenums(args[2], 'pvvar').reshape(-1)
        t = (d - d[0]) / 365.0
    else:
        t = np.arange(cf.shape[0], dtype=float)
    return out((cf / (1 + r) ** t[:, None]).sum(axis=0).reshape(1, -1))


@bi('fvvar')
def fvvar(nargout, *args):
    """FutureVal = fvvar(CashFlow, Rate, CFDates): the value at the last flow of varying cash flows compounded at Rate."""
    nargchk(args, 2, 3, 'fvvar')
    cf = _flows(args[0], 'fvvar')
    r = float(num(args[1]))
    if len(args) > 2 and numel(args[2]):
        d = _datenums(args[2], 'fvvar').reshape(-1)
        t = (d[-1] - d) / 365.0
    else:
        t = np.arange(cf.shape[0] - 1, -1, -1, dtype=float)
    return out((cf * (1 + r) ** t[:, None]).sum(axis=0).reshape(1, -1))


def _annuity(r, n):
    """The present value of 1 a period for n periods at end of period."""
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.where(r == 0, n, (1 - (1 + r) ** (-n)) / np.where(r == 0, 1, r))


@bi('pvfix')
def pvfix(nargout, *args):
    """PresentVal = pvfix(Rate, NumPeriods, Payment, ExtraPayment, Due): the
    present value of equal payments (Due 0 at the ends of the periods, 1 at
    their starts) and an extra payment at the end."""
    nargchk(args, 3, 5, 'pvfix')
    r, n, pmt, extra, due = _arrs(args, ['Rate', 'NumPeriods', 'Payment', 'ExtraPayment', 'Due'], 'pvfix', {'ExtraPayment': 0.0, 'Due': 0.0})
    return out(pmt * _annuity(r, n) * (1 + r * due) + extra * (1 + r) ** (-n))


@bi('fvfix')
def fvfix(nargout, *args):
    """FutureVal = fvfix(Rate, NumPeriods, Payment, PresentValue, Due): the
    future value of equal payments and a starting balance."""
    nargchk(args, 3, 5, 'fvfix')
    r, n, pmt, pv, due = _arrs(args, ['Rate', 'NumPeriods', 'Payment', 'PresentValue', 'Due'], 'fvfix', {'PresentValue': 0.0, 'Due': 0.0})
    g = (1 + r) ** n
    return out(pmt * _annuity(r, n) * g * (1 + r * due) + pv * g)


@bi('payper')
def payper(nargout, *args):
    """Payment = payper(Rate, NumPeriods, PresentValue, FutureValue, Due):
    the payment each period that pays off a loan of PresentValue (leaving
    FutureValue)."""
    nargchk(args, 3, 5, 'payper')
    r, n, pv, fv, due = _arrs(args, ['Rate', 'NumPeriods', 'PresentValue', 'FutureValue', 'Due'], 'payper', {'FutureValue': 0.0, 'Due': 0.0})
    a = _annuity(r, n)
    with np.errstate(divide='ignore', invalid='ignore'):
        pmt = (pv - fv * (1 + r) ** (-n)) / a / (1 + r * due)
    return out(pmt)


@bi('amortize', nout=4)
def amortize(nargout, *args):
    """[Principal, Interest, Balance, Payment] = amortize(Rate, NumPeriods,
    PresentValue, FutureValue, Due): a loan's schedule: each payment split
    into principal and interest, and the balance after it."""
    nargchk(args, 3, 5, 'amortize')
    r = float(num(args[0]))
    n = int(num(args[1]))
    pv = float(num(args[2]))
    fv = float(num(args[3])) if len(args) > 3 and numel(args[3]) else 0.0
    due = float(num(args[4])) if len(args) > 4 and numel(args[4]) else 0.0
    if n < 1:
        raise err('finance:amortize:InvalidPeriods', 'NumPeriods is a whole number from 1.', 'amortize')
    pmt = float(np.asarray(payper(1, r, float(n), pv, fv, due)).reshape(-1)[0])
    P, I, B = np.zeros(n), np.zeros(n), np.zeros(n)
    bal = pv
    owed = 0.0 if due else bal * r          # the interest the next payment meets
    for k in range(n):
        I[k] = owed
        P[k] = pmt - owed
        bal -= P[k]
        B[k] = bal
        owed = bal * r
    row = lambda v: out(v.reshape(1, -1))
    vals = (row(P), row(I), row(B), pmt)
    return vals[:nargout] if nargout > 1 else vals[0]


@bi('annurate')
def annurate(nargout, *args):
    """Rate = annurate(NumPeriods, Payment, PresentValue, FutureValue, Due): the periodic rate of an annuity."""
    nargchk(args, 3, 5, 'annurate')
    n, pmt, pv, fv, due = _arrs(args, ['NumPeriods', 'Payment', 'PresentValue', 'FutureValue', 'Due'], 'annurate', {'FutureValue': 0.0, 'Due': 0.0})
    from scipy.optimize import brentq
    res = np.full(n.shape, np.nan)
    for idx in np.ndindex(n.shape):
        f = lambda r: float(np.asarray(payper(1, r, n[idx], pv[idx], fv[idx], due[idx])).reshape(-1)[0]) - pmt[idx]
        # the payment grows with the rate: a bracket whose low end keeps (1 + r)^-n finite
        lo, hi = max(-0.9, -50.0 / max(float(n[idx]), 1.0)), 10.0
        try:
            with np.errstate(all='ignore'):
                flo, fhi = f(lo), f(hi)
            if np.isfinite(flo) and np.isfinite(fhi) and flo * fhi <= 0:
                res[idx] = brentq(f, lo, hi, xtol=1e-15, rtol=1e-15)
        except ValueError:
            pass
    return out(res)


@bi('annuterm')
def annuterm(nargout, *args):
    """NumPeriods = annuterm(Rate, Payment, PresentValue, FutureValue, Due): how many payments pay off an annuity (not whole in general)."""
    nargchk(args, 3, 5, 'annuterm')
    r, pmt, pv, fv, due = _arrs(args, ['Rate', 'Payment', 'PresentValue', 'FutureValue', 'Due'], 'annuterm', {'FutureValue': 0.0, 'Due': 0.0})
    with np.errstate(divide='ignore', invalid='ignore'):
        p = pmt * (1 + r * due)
        n = np.where(r == 0, (pv - fv) / pmt, np.log((p - fv * r) / (p - pv * r)) / np.log(1 + r))
    return out(n)


@bi('effrr')
def effrr(nargout, *args):
    """Return = effrr(Rate, NumPeriods): the effective annual rate of a nominal rate compounded NumPeriods times a year (Inf: continuously)."""
    nargchk(args, 2, 2, 'effrr')
    r, n = _arrs(args, ['Rate', 'NumPeriods'], 'effrr')
    return out(np.where(np.isinf(n), np.expm1(r), (1 + r / n) ** n - 1))


@bi('nomrr')
def nomrr(nargout, *args):
    """Return = nomrr(Rate, NumPeriods): the nominal rate compounded NumPeriods times a year of an effective rate."""
    nargchk(args, 2, 2, 'nomrr')
    r, n = _arrs(args, ['Rate', 'NumPeriods'], 'nomrr')
    return out(np.where(np.isinf(n), np.log1p(r), n * ((1 + r) ** (1 / n) - 1)))


# ---- returns -----------------------------------------------------------------------------------------------------------------

def _series_cols(v, fn):
    a = np.asarray(darr(v, fn), float)
    if a.ndim == 2 and a.shape[0] == 1:
        a = a.T
    return a


def _method(v, fn, default):
    m = (opt_str(v) or default).lower() if v is not None else default
    m = {'continuous': 'continuous', 'periodic': 'simple', 'simple': 'simple'}.get(m)
    if m is None:
        raise err(f'finance:{fn}:InvalidMethod', "Method is 'continuous' or 'simple' ('periodic').", fn)
    return m


@bi('price2ret', nout=2)
def price2ret(nargout, *args):
    """[Returns, Intervals] = price2ret(Prices, 'Ticks', t, 'Method', m): the
    returns of each column of prices: continuous (log differences, the
    default) or simple ('periodic'), per unit of time when times are given."""
    nargchk(args, 1, 5, 'price2ret')
    pos, opts = _pairs(args, 'price2ret', ('ticks', 'method'))
    P = _series_cols(pos[0], 'price2ret')
    t = None
    if len(pos) > 1 and numel(pos[1]):
        t = np.asarray(darr(pos[1]), float).reshape(-1)
    if 'ticks' in opts:
        t = np.asarray(darr(opts['ticks']), float).reshape(-1)
    m = _method(opts.get('method', pos[2] if len(pos) > 2 else None), 'price2ret', 'continuous')
    if np.any(P <= 0) and m == 'continuous':
        raise err('finance:price2ret:NonPositive', 'Continuous returns need positive prices.', 'price2ret')
    dt = np.diff(t).reshape(-1, 1) if t is not None else np.ones((P.shape[0] - 1, 1))
    if t is not None and t.size != P.shape[0]:
        raise err('finance:price2ret:Ticks', 'There is a time for each price.', 'price2ret')
    ret = (np.diff(np.log(P), axis=0) if m == 'continuous' else np.diff(P, axis=0) / P[:-1]) / dt
    return _two(nargout, ret, dt)


@bi('ret2price', nout=2)
def ret2price(nargout, *args):
    """[Prices, Ticks] = ret2price(Returns, 'StartPrice', p0, 'Ticks', t,
    'Method', m): the prices the returns make from StartPrice (1),
    continuous (the default) or simple."""
    nargchk(args, 1, 7, 'ret2price')
    pos, opts = _pairs(args, 'ret2price', ('startprice', 'ticks', 'method', 'starttime'))
    Rt = _series_cols(pos[0], 'ret2price')
    p0 = np.asarray(darr(opts.get('startprice', pos[1] if len(pos) > 1 and numel(pos[1]) else 1.0)), float).reshape(1, -1)
    dt = np.asarray(darr(pos[2]), float).reshape(-1, 1) if len(pos) > 2 and numel(pos[2]) else np.ones((Rt.shape[0], 1))
    t0 = float(num(opts.get('starttime', pos[3] if len(pos) > 3 and numel(pos[3]) else 0.0)))
    m = _method(opts.get('method', pos[4] if len(pos) > 4 else None), 'ret2price', 'continuous')
    if 'ticks' in opts:
        tk = np.asarray(darr(opts['ticks']), float).reshape(-1)
        dt = np.diff(tk).reshape(-1, 1)
        t0 = tk[0]
    g = np.exp(np.cumsum(Rt * dt, axis=0)) if m == 'continuous' else np.cumprod(1 + Rt * dt, axis=0)
    P = np.vstack([np.ones((1, Rt.shape[1])), g]) * p0
    ticks = np.concatenate([[t0], t0 + np.cumsum(dt.reshape(-1))]).reshape(-1, 1)
    return _two(nargout, P, ticks)


@bi('tick2ret', nout=2)
def tick2ret(nargout, *args):
    """[Returns, Intervals] = tick2ret(Data, 'TickTimes', t, 'Method', m): the returns of prices, simple (the default) or continuous."""
    nargchk(args, 1, 5, 'tick2ret')
    pos, opts = _pairs(args, 'tick2ret', ('ticktimes', 'method'))
    P = _series_cols(pos[0], 'tick2ret')
    m = _method(opts.get('method'), 'tick2ret', 'simple')
    t = np.asarray(darr(opts['ticktimes']), float).reshape(-1) if 'ticktimes' in opts else None
    dt = np.diff(t).reshape(-1, 1) if t is not None else np.ones((P.shape[0] - 1, 1))
    ret = (np.diff(np.log(P), axis=0) if m == 'continuous' else np.diff(P, axis=0) / P[:-1])
    return _two(nargout, ret, dt)


@bi('ret2tick', nout=2)
def ret2tick(nargout, *args):
    """[Prices, Times] = ret2tick(Returns, 'StartPrice', p0, 'StartTime', t0, 'Method', m): the prices from returns, simple (the default) or continuous."""
    nargchk(args, 1, 9, 'ret2tick')
    pos, opts = _pairs(args, 'ret2tick', ('startprice', 'starttime', 'method', 'retintervals'))
    Rt = _series_cols(pos[0], 'ret2tick')
    p0 = np.asarray(darr(opts['startprice']), float).reshape(1, -1) if 'startprice' in opts else np.ones((1, Rt.shape[1]))
    t0 = float(num(opts['starttime'])) if 'starttime' in opts else 0.0
    dt = np.asarray(darr(opts['retintervals']), float).reshape(-1, 1) if 'retintervals' in opts else np.ones((Rt.shape[0], 1))
    m = _method(opts.get('method'), 'ret2tick', 'simple')
    g = np.exp(np.cumsum(Rt, axis=0)) if m == 'continuous' else np.cumprod(1 + Rt, axis=0)
    P = np.vstack([np.ones((1, Rt.shape[1])), g]) * p0
    return _two(nargout, P, np.concatenate([[t0], t0 + np.cumsum(dt.reshape(-1))]).reshape(-1, 1))


@bi('ewstats', nout=3)
def ewstats(nargout, *args):
    """[ExpReturn, ExpCovariance, NumEffObs] = ewstats(RetSeries, DecayFactor,
    WindowLength): the exponentially weighted mean and covariance of the
    return series (rows in time order, the last weighted 1, the one before
    DecayFactor ...)."""
    nargchk(args, 1, 3, 'ewstats')
    X = _series_cols(args[0], 'ewstats')
    lam = float(num(args[1])) if len(args) > 1 and numel(args[1]) else 1.0
    if not 0 < lam <= 1:
        raise err('finance:ewstats:InvalidDecay', 'DecayFactor is above 0 and at most 1.', 'ewstats')
    W = int(num(args[2])) if len(args) > 2 and numel(args[2]) else X.shape[0]
    W = min(W, X.shape[0])
    Xw = X[-W:]
    w = lam ** np.arange(W - 1, -1, -1, dtype=float)
    w = w / w.sum()
    mu = w @ Xw
    D = Xw - mu
    C = (D * w[:, None]).T @ D
    neff = W if lam == 1 else (1 - lam ** W) / (1 - lam)
    vals = (out(mu.reshape(1, -1)), out(C), float(neff))
    return vals[:nargout] if nargout > 1 else vals[0]


# ---- technical indicators ---------------------------------------------------------------------------------------------------------

def _ema(x, alpha, seed='first'):
    """An exponential moving average of each column, from its first value."""
    y = np.empty_like(x)
    y[0] = x[0]
    for t in range(1, x.shape[0]):
        y[t] = alpha * x[t] + (1 - alpha) * y[t - 1]
    return y


def _trailing(x, w, weights=None):
    """Trailing weighted means of each column over windows of w, shorter at the start."""
    n = x.shape[0]
    y = np.empty_like(x)
    for t in range(n):
        k = min(w, t + 1)
        wt = np.ones(k) if weights is None else np.asarray(weights[-k:], float)
        y[t] = (wt[:, None] * x[t - k + 1:t + 1]).sum(axis=0) / wt.sum()
    return y


@bi('movavg', nout=2)
def movavg(nargout, *args):
    """ma = movavg(Data, type, windowSize): a moving average of each column:
    'simple', 'square-root', 'linear', 'exponential', 'triangular',
    'modified' (Wilder's) or 'custom' (weights as windowSize); trailing
    windows, shorter at the start."""
    nargchk(args, 2, 4, 'movavg')
    X = _series_cols(args[0], 'movavg')
    kind = opt_str(args[1])
    if kind is None:
        # the older form: [short, long] = movavg(Asset, Lead, Lag, Alpha)
        lead, lag = int(num(args[1])), int(num(args[2])) if len(args) > 2 else 20
        alpha = float(num(args[3])) if len(args) > 3 else 0.0
        if alpha == 0:
            s, l = _trailing(X, lead), _trailing(X, lag)
        else:
            s, l = _trailing(X, lead, np.arange(1, lead + 1) ** alpha), _trailing(X, lag, np.arange(1, lag + 1) ** alpha)
        return _two(nargout, s, l)
    kind = kind.lower()
    if len(args) < 3:
        raise err('finance:movavg:NoWindow', 'Give the window size (or the weights for custom).', 'movavg')
    if kind == 'custom':
        w = np.asarray(darr(args[2]), float).reshape(-1)
        return out(_trailing(X, w.size, w))
    n = int(num(args[2]))
    if n < 1:
        raise err('finance:movavg:InvalidWindow', 'The window size is a whole number from 1.', 'movavg')
    if kind == 'simple':
        return out(_trailing(X, n))
    if kind == 'square-root':
        return out(_trailing(X, n, np.sqrt(np.arange(1, n + 1))))
    if kind == 'linear':
        return out(_trailing(X, n, np.arange(1, n + 1, dtype=float)))
    if kind == 'exponential':
        return out(_ema(X, 2 / (n + 1)))
    if kind == 'modified':
        return out(_ema(X, 1 / n))
    if kind == 'triangular':
        m = int(math.ceil((n + 1) / 2))
        return out(_trailing(_trailing(X, m), m))
    raise err('finance:movavg:InvalidType', "The type is 'simple', 'square-root', 'linear', 'exponential', 'triangular', 'modified' or 'custom'.", 'movavg')


@bi('bollinger', nout=3)
def bollinger(nargout, *args):
    """[middle, upper, lower] = bollinger(Data, 'WindowSize', 20, 'NumStd',
    2): Bollinger bands: the simple moving average and that plus and minus
    NumStd standard deviations (of the window, divided by its length); NaN
    until a window is full."""
    nargchk(args, 1, 5, 'bollinger')
    pos, opts = _pairs(args, 'bollinger', ('windowsize', 'numstd'))
    X = _series_cols(pos[0], 'bollinger')
    w = int(num(opts['windowsize'])) if 'windowsize' in opts else 20
    k = float(num(opts['numstd'])) if 'numstd' in opts else 2.0
    n = X.shape[0]
    mid = np.full(X.shape, np.nan)
    sd = np.full(X.shape, np.nan)
    for t in range(w - 1, n):
        win = X[t - w + 1:t + 1]
        mid[t] = win.mean(axis=0)
        sd[t] = win.std(axis=0)
    vals = (out(mid), out(mid + k * sd), out(mid - k * sd))
    return vals[:nargout] if nargout > 1 else vals[0]


@bi('rsindex')
def rsindex(nargout, *args):
    """index = rsindex(Data, 'WindowSize', 14): Wilder's relative strength
    index of each column: 100 - 100/(1 + average gain/average loss), the
    averages smoothed by 1/WindowSize after a first simple mean; NaN until
    then."""
    nargchk(args, 1, 3, 'rsindex')
    pos, opts = _pairs(args, 'rsindex', ('windowsize',))
    X = _series_cols(pos[0], 'rsindex')
    w = int(num(opts['windowsize'])) if 'windowsize' in opts else 14
    d = np.diff(X, axis=0)
    gain, loss = np.maximum(d, 0), np.maximum(-d, 0)
    res = np.full(X.shape, np.nan)
    if d.shape[0] >= w:
        ag, al = gain[:w].mean(axis=0), loss[:w].mean(axis=0)
        for t in range(w, d.shape[0] + 1):
            if t > w:
                ag = (ag * (w - 1) + gain[t - 1]) / w
                al = (al * (w - 1) + loss[t - 1]) / w
            with np.errstate(divide='ignore', invalid='ignore'):
                res[t] = np.where(al == 0, 100.0, 100 - 100 / (1 + ag / al))
    return out(res)


@bi('macd', nout=2)
def macd(nargout, *args):
    """[MACDLine, SignalLine] = macd(Data): the 12-period exponential moving
    average less the 26-period one, and its 9-period exponential average;
    each average starts from the series' first value."""
    nargchk(args, 1, 1, 'macd')
    X = _series_cols(args[0], 'macd')
    line = _ema(X, 2 / 13) - _ema(X, 2 / 27)
    return _two(nargout, line, _ema(line, 2 / 10))


# ---- dates -------------------------------------------------------------------------------------------------------------------------

def _date(dn):
    k = int(math.floor(dn)) - 366
    if k < 1:
        raise err('finance:dates:BeforeYear1', 'Dates before the year 1 (day number 367) are not counted here.', 'finance')
    return _dt.date.fromordinal(k)


def _dn(d):
    return float(d.toordinal() + 366)


@bi('daysact')
def daysact(nargout, *args):
    """NumDays = daysact(StartDate, EndDate): the actual days between dates (from day numbers)."""
    nargchk(args, 1, 2, 'daysact')
    a = _datenums(args[0], 'daysact')
    if len(args) == 1:
        return out(np.floor(a))
    b = _datenums(args[1], 'daysact')
    a, b = np.broadcast_arrays(a, b)
    return out(np.floor(b) - np.floor(a))


def _is_eom_feb(d):
    return d.month == 2 and (d + _dt.timedelta(days=1)).month == 3


def _d360(a, b, rule):
    d1, d2 = _date(a), _date(b)
    D1, D2 = d1.day, d2.day
    if rule == 'sia':
        if _is_eom_feb(d1) and _is_eom_feb(d2):
            D2 = 30
        if _is_eom_feb(d1):
            D1 = 30
        if D2 == 31 and D1 >= 30:
            D2 = 30
        if D1 == 31:
            D1 = 30
    elif rule == 'psa':
        if D1 == 31 or _is_eom_feb(d1):
            D1 = 30
        if D2 == 31 and D1 == 30:
            D2 = 30
    elif rule == 'isda':
        if D1 == 31:
            D1 = 30
        if D2 == 31 and D1 == 30:
            D2 = 30
    else:                      # European
        D1, D2 = min(D1, 30), min(D2, 30)
    return 360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (D2 - D1)


@bi('days360')
def days360(nargout, *args):
    """NumDays = days360(StartDate, EndDate): days counted 30/360 (SIA): every month 30 days, the 31st and February's end taken as the 30th."""
    nargchk(args, 2, 2, 'days360')
    a, b = np.broadcast_arrays(_datenums(args[0], 'days360'), _datenums(args[1], 'days360'))
    return out(np.vectorize(lambda x, y: float(_d360(x, y, 'sia')), otypes=[float])(a, b) if a.size else a)


def _yearfrac(a, b, basis):
    d1, d2 = _date(a), _date(b)
    days = b - a
    if basis in (0, 12):
        # actual/actual (ISDA): the days in each calendar year over that year's length
        if d1 > d2:
            return -_yearfrac(b, a, basis)
        f = 0.0
        y = d1.year
        cur = d1
        while cur.year < d2.year:
            nxt = _dt.date(cur.year + 1, 1, 1)
            f += (nxt - cur).days / (366 if _leap(cur.year) else 365)
            cur = nxt
        return f + (d2 - cur).days / (366 if _leap(d2.year) else 365)
    if basis == 1:
        return _d360(a, b, 'sia') / 360
    if basis == 2:
        return days / 360
    if basis == 3:
        return days / 365
    if basis == 4:
        return _d360(a, b, 'psa') / 360
    if basis == 5:
        return _d360(a, b, 'isda') / 360
    if basis == 6:
        return _d360(a, b, 'european') / 360
    if basis == 7:
        # actual/365 Japanese: February 29 left out
        lo, hi = (d1, d2) if d1 <= d2 else (d2, d1)
        leapdays = sum(1 for y in range(lo.year, hi.year + 1) if _leap(y) and lo <= _dt.date(y, 2, 29) < hi)
        return (days - math.copysign(leapdays, days)) / 365
    if basis == 13:
        return _busdays(a, b) / 252
    raise err('finance:yearfrac:InvalidBasis', 'basis is 0 to 7, 12 or 13 here (8 to 11 count from coupon dates).', 'yearfrac')


def _leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


@bi('yearfrac')
def yearfrac(nargout, *args):
    """YearFraction = yearfrac(StartDate, EndDate, Basis): the fraction of a
    year between dates by a day count: 0 actual/actual (ISDA), 1 30/360
    SIA, 2 actual/360, 3 actual/365, 4 30/360 PSA, 5 30/360 ISDA, 6 30/360
    European, 7 actual/365 Japanese, 12 actual/actual ISDA, 13 business
    days/252."""
    nargchk(args, 2, 3, 'yearfrac')
    a, b = _datenums(args[0], 'yearfrac'), _datenums(args[1], 'yearfrac')
    basis = np.asarray(darr(args[2]), float) if len(args) > 2 and numel(args[2]) else np.zeros(1)
    a, b, basis = np.broadcast_arrays(np.floor(a), np.floor(b), basis)
    if np.any(~np.isin(basis, [0, 1, 2, 3, 4, 5, 6, 7, 12, 13])):
        raise err('finance:yearfrac:InvalidBasis', 'basis is 0 to 7, 12 or 13 here (8 to 11 count from coupon dates).', 'yearfrac')
    res = np.empty(a.shape)
    for idx in np.ndindex(a.shape):
        res[idx] = _yearfrac(a[idx], b[idx], int(basis[idx]))
    return out(res)


def _nth_weekday(y, m, wd, n):
    """The n-th (from 1; -1 the last) weekday wd (Monday 0) of a month."""
    if n > 0:
        d = _dt.date(y, m, 1)
        d += _dt.timedelta(days=(wd - d.weekday()) % 7)
        return d + _dt.timedelta(weeks=n - 1)
    last = _dt.date(y + (m == 12), m % 12 + 1, 1) - _dt.timedelta(days=1)
    return last - _dt.timedelta(days=(last.weekday() - wd) % 7)


def _easter(y):
    """Easter Sunday (the Gregorian computus, anonymous algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return _dt.date(y, month, day)


def _observed(d):
    """A holiday on a Saturday is kept the Friday before, on a Sunday the Monday after."""
    if d.weekday() == 5:
        return d - _dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + _dt.timedelta(days=1)
    return d


def nyse_holidays(y):
    """The New York Stock Exchange's regular holidays of a year (closings for special events left out)."""
    hs = []
    nyd = _dt.date(y, 1, 1)
    if nyd.weekday() != 5:          # a New Year's Day on a Saturday is not moved back into the old year
        hs.append(_observed(nyd))
    if y >= 1998:
        hs.append(_nth_weekday(y, 1, 0, 3))         # Martin Luther King Jr. Day
    hs.append(_nth_weekday(y, 2, 0, 3))             # Washington's Birthday
    hs.append(_easter(y) - _dt.timedelta(days=2))   # Good Friday
    hs.append(_nth_weekday(y, 5, 0, -1))            # Memorial Day
    if y >= 2022:
        hs.append(_observed(_dt.date(y, 6, 19)))    # Juneteenth
    hs.append(_observed(_dt.date(y, 7, 4)))
    hs.append(_nth_weekday(y, 9, 0, 1))             # Labor Day
    hs.append(_nth_weekday(y, 11, 3, 4))            # Thanksgiving
    hs.append(_observed(_dt.date(y, 12, 25)))
    return sorted(d for d in hs if d.year == y)


@bi('holidays')
def holidays(nargout, *args):
    """H = holidays(StartDate, EndDate): the New York Stock Exchange's
    regular holidays between the dates (as observed), a column of day
    numbers; with no inputs those of the current year."""
    nargchk(args, 0, 2, 'holidays')
    if not args:
        y = _dt.date.today().year
        a, b = _dn(_dt.date(y, 1, 1)), _dn(_dt.date(y, 12, 31))
    else:
        a = float(_datenums(args[0], 'holidays').reshape(-1)[0])
        b = float(_datenums(args[1], 'holidays').reshape(-1)[0]) if len(args) > 1 else a
    lo, hi = _date(a), _date(b)
    hs = [_dn(d) for y in range(lo.year, hi.year + 1) for d in nyse_holidays(y) if lo <= d <= hi]
    return _dates_out(np.array(hs).reshape(-1, 1), args[0] if args else None)


def _weekend(v):
    if v is None:
        return np.array([1, 0, 0, 0, 0, 0, 1], bool)      # Sunday to Saturday
    w = np.asarray(darr(v)).reshape(-1)
    if w.size != 7:
        raise err('finance:isbusday:InvalidWeekend', 'Weekend has 7 values, Sunday to Saturday.', 'isbusday')
    return w.astype(bool)


def _is_bus(dn, hol, wk):
    d = _date(dn)
    if wk[(d.weekday() + 1) % 7]:
        return False
    if hol is None:
        return d not in set(nyse_holidays(d.year))
    return math.floor(dn) not in hol


def _hol_set(args, k):
    """The holidays given at args[k] (an empty list: none), or None for the NYSE's when not given."""
    if len(args) <= k:
        return None
    if numel(args[k]) == 0:
        return set()
    return set(np.floor(_datenums(args[k], 'isbusday')).reshape(-1).tolist())


@bi('isbusday')
def isbusday(nargout, *args):
    """Busday = isbusday(Date, Holiday, Weekend): whether each date is a
    business day: not a weekend day (Saturday and Sunday unless Weekend, 7
    flags from Sunday, says otherwise) and not a holiday (the NYSE's unless
    a list is given)."""
    nargchk(args, 1, 3, 'isbusday')
    d = _datenums(args[0], 'isbusday')
    hol = _hol_set(args, 1)
    wk = _weekend(args[2] if len(args) > 2 else None)
    return out(np.vectorize(lambda x: _is_bus(x, hol, wk), otypes=[bool])(d) if d.size else d.astype(bool))


@bi('busdate')
def busdate(nargout, *args):
    """Busday = busdate(Date, Direction, Holiday, Weekend): the next (1, the default) or previous (-1) business day."""
    nargchk(args, 1, 4, 'busdate')
    d = _datenums(args[0], 'busdate')
    dirn = int(num(args[1])) if len(args) > 1 and numel(args[1]) else 1
    if dirn not in (1, -1):
        raise err('finance:busdate:InvalidDirection', 'Direction is 1 (next) or -1 (previous).', 'busdate')
    hol = _hol_set(args, 2)
    wk = _weekend(args[3] if len(args) > 3 else None)
    if np.all(wk):
        raise err('finance:busdate:NoBusinessDays', 'Every day is a weekend day.', 'busdate')

    def step(x):
        y = math.floor(x) + dirn
        while not _is_bus(y, hol, wk):
            y += dirn
        return float(y)
    res = np.vectorize(step, otypes=[float])(d) if d.size else d
    return _dates_out(res, args[0])


def _month_bus(args, fn, first):
    nargchk(args, 2, 4, fn)
    Y, M = np.broadcast_arrays(np.asarray(darr(args[0]), float), np.asarray(darr(args[1]), float))
    hol = _hol_set(args, 2)
    wk = _weekend(args[3] if len(args) > 3 else None)
    res = np.empty(Y.shape)
    for idx in np.ndindex(Y.shape):
        y, m = int(Y[idx]), int(M[idx])
        d = _dt.date(y, m, 1) if first else _dt.date(y + (m == 12), m % 12 + 1, 1) - _dt.timedelta(days=1)
        dn = _dn(d)
        while not _is_bus(dn, hol, wk):
            dn += 1 if first else -1
        res[idx] = dn
    return out(res)


@bi('fbusdate')
def fbusdate(nargout, *args):
    """Date = fbusdate(Year, Month, Holiday, Weekend): the first business day of the month (a day number)."""
    return _month_bus(args, 'fbusdate', True)


@bi('lbusdate')
def lbusdate(nargout, *args):
    """Date = lbusdate(Year, Month, Holiday, Weekend): the last business day of the month (a day number)."""
    return _month_bus(args, 'lbusdate', False)


def _busdays(a, b):
    """Business days from a (excluded) to b (included), NYSE holidays and Saturday-Sunday weekends."""
    lo, hi, s = (a, b, 1) if a <= b else (b, a, -1)
    n = 0
    wk = _weekend(None)
    x = math.floor(lo) + 1
    while x <= hi:
        if _is_bus(x, None, wk):
            n += 1
        x += 1
    return s * n
