"""System identification: iddata and idinput; polynomial models fitted to
data (arx, ar, armax, oe, bj, the idpoly object), state-space models (n4sid,
ssest), continuous transfer functions (tfest); and what is done with them:
compare, predict, sim, pe, resid, polydata, present, aic and fpe.

Models are of one output (and one input, or none for a time series). An
estimated model is also a linear model of the control functions (a discrete
transfer function from the input to the output, or a state-space model), so
step, bode, lsim and the rest take it. Polynomials are in the delay
operator q^-1: A(q)y(t) = B(q)/F(q) u(t) + C(q)/D(q) e(t).
"""
import math
import sys

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, darr, out, opt_str, is_str, sval, num
from ..values import MError, Obj, Char, Cell, Struct, Str, EMPTY, numel, py_str, class_of
from .. import runtime as R
from . import control as CT


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy or SciPy refuses told as the function's own error."""
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError, np.linalg.LinAlgError, OverflowError) as e:
                raise err(f'Ident:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _lfilter(b, a, x, zi=None):
    from scipy.signal import lfilter
    return lfilter(b, a, x) if zi is None else lfilter(b, a, x, zi=zi)[0]


# ---- data -----------------------------------------------------------------------------------------------------------------------

class IdData(Obj):
    cls = 'iddata'
    is_handle = False

    def __init__(self, y, u, Ts=1.0):
        self.y = np.asarray(y, float).reshape(len(y), -1) if np.size(y) else np.zeros((len(u) if u is not None else 0, 0))
        self.u = np.asarray(u, float).reshape(self.y.shape[0], -1) if u is not None and np.size(u) else np.zeros((self.y.shape[0], 0))
        self.Ts = float(Ts)
        self.tstart = self.Ts
        self.yname = [f'y{k + 1}' for k in range(self.y.shape[1])]
        self.uname = [f'u{k + 1}' for k in range(self.u.shape[1])]
        self.name = ''
        self.unit = 'seconds'

    def value_copy(self):
        import copy
        o = copy.copy(self)
        o.y, o.u = self.y.copy(), self.u.copy()
        o.yname, o.uname = list(self.yname), list(self.uname)
        return o

    @property
    def N(self):
        return self.y.shape[0]

    @property
    def shape(self):
        return (self.N, self.y.shape[1], self.u.shape[1])

    def getprop(self, name):
        k = name.lower()
        if k in ('outputdata', 'y'):
            return out(self.y)
        if k in ('inputdata', 'u'):
            return out(self.u)
        if k == 'ts':
            return self.Ts
        if k == 'tstart':
            return self.tstart
        if k == 'samplinginstants':
            return out((self.tstart + self.Ts * np.arange(self.N)).reshape(-1, 1))
        if k == 'outputname':
            return Cell.of_list([Char.of(x) for x in self.yname], (len(self.yname), 1))
        if k == 'inputname':
            return Cell.of_list([Char.of(x) for x in self.uname], (len(self.uname), 1))
        if k == 'name':
            return Char.of(self.name)
        if k == 'timeunit':
            return Char.of(self.unit)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'iddata'.")

    def setprop(self, name, value):
        k = name.lower()
        if k in ('outputdata', 'y'):
            y = np.asarray(darr(value), float)
            self.y = y.reshape(y.shape[0], -1) if y.ndim > 1 else y.reshape(-1, 1)
        elif k in ('inputdata', 'u'):
            u = np.asarray(darr(value), float)
            self.u = u.reshape(self.y.shape[0], -1) if u.size else np.zeros((self.y.shape[0], 0))
        elif k == 'ts':
            self.Ts = float(num(value))
        elif k == 'tstart':
            self.tstart = float(num(value))
        elif k in ('outputname', 'inputname'):
            names = [py_str(x) for x in (value.a.reshape(-1, order='F') if type(value) in (Cell, Str) else [value])]
            setattr(self, 'yname' if k == 'outputname' else 'uname', names)
        elif k == 'name':
            self.name = sval(value, 'Name', 'iddata')
        elif k == 'timeunit':
            self.unit = sval(value, 'TimeUnit', 'iddata')
        else:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'iddata'.")

    def propnames(self):
        return ['OutputData', 'InputData', 'Ts', 'Tstart', 'SamplingInstants', 'OutputName', 'InputName', 'Name', 'TimeUnit']

    def index(self, args):
        from ..index import idx
        rows = args[0] if args else Char.of(':')
        o = self.value_copy()
        sel = np.asarray(darr(idx(out(np.arange(1, self.N + 1, dtype=float).reshape(-1, 1)), (rows,))), float).reshape(-1).astype(int) - 1
        o.y, o.u = self.y[sel], self.u[sel]
        o.tstart = self.tstart + self.Ts * (sel[0] if sel.size else 0)
        if len(args) > 1 and not (is_str(args[1]) and py_str(args[1]) == ':'):
            ys = [int(v) - 1 for v in np.asarray(darr(args[1])).reshape(-1)]
            o.y, o.yname = o.y[:, ys], [self.yname[j] for j in ys]
        if len(args) > 2 and not (is_str(args[2]) and py_str(args[2]) == ':'):
            us = [int(v) - 1 for v in np.asarray(darr(args[2])).reshape(-1)] if numel(args[2]) else []
            o.u, o.uname = o.u[:, us], [self.uname[j] for j in us]
        return o

    def display_lines(self):
        lines = [f'  Time domain data set with {self.N} samples.', f'  Sample time: {self.Ts:g} {self.unit}', '']
        lines += ['  Outputs      Unit (if specified)'] + [f'     {n}' for n in self.yname]
        if self.uname:
            lines += ['', '  Inputs       Unit (if specified)'] + [f'     {n}' for n in self.uname]
        return lines


@bi('iddata', arr=False)
def iddata(nargout, *args):
    """data = iddata(y, u, Ts, Name, Value): a time-domain data set: the
    output y and the input u (a column each; [] for a time series), the
    sample time Ts (1)."""
    nargchk(args, 1, 20, 'iddata')
    pos, k = [], 0
    while k < len(args) and not (is_str(args[k]) and k >= 1):
        pos.append(args[k])
        k += 1
    y = np.asarray(darr(pos[0]), float)
    if y.ndim == 2 and y.shape[0] == 1 and y.shape[1] > 1:
        y = y.T
    u = np.asarray(darr(pos[1]), float) if len(pos) > 1 and numel(pos[1]) else None
    if u is not None and u.ndim == 2 and u.shape[0] == 1 and u.shape[1] > 1:
        u = u.T
    if u is not None and u.shape[0] != y.shape[0]:
        raise err('Ident:iddata:Lengths', 'y and u have the same number of samples (rows).', 'iddata')
    Ts = float(num(pos[2])) if len(pos) > 2 and numel(pos[2]) else 1.0
    d = IdData(y, u, Ts)
    rest = args[k:]
    for j in range(0, len(rest) - 1, 2):
        d.setprop(sval(rest[j], 'name', 'iddata'), rest[j + 1])
    return d


def _data(v, fn, need_input=None):
    """y, u (or None) and Ts from iddata, or y alone (a time series) from an array."""
    if isinstance(v, IdData):
        if v.y.shape[1] != 1:
            raise err(f'Ident:{fn}:Outputs', 'The data have one output here.', fn)
        if v.u.shape[1] > 1:
            raise err(f'Ident:{fn}:Inputs', 'The data have one input (or none) here.', fn)
        u = v.u[:, 0] if v.u.shape[1] else None
        y, Ts = v.y[:, 0], v.Ts
    else:
        y, u, Ts = np.asarray(darr(v, fn), float).reshape(-1), None, 1.0
    if need_input is True and u is None:
        raise err(f'Ident:{fn}:NoInput', f'{fn} needs data with an input: iddata(y, u, Ts).', fn)
    return y, u, Ts


@bi('idinput')
def idinput(nargout, *args):
    """u = idinput(N, type, band, levels): an input signal for experiments:
    'rgs' (random Gaussian, the default), 'rbs' (random binary), 'prbs'
    (pseudorandom binary of maximum length) or 'sine' (sines); band
    [lo hi] as fractions of the Nyquist frequency ([0 1]); levels [-1 1]
    (the binary levels, or mean +- one standard deviation)."""
    nargchk(args, 1, 4, 'idinput')
    Nv = np.asarray(darr(args[0]), float).reshape(-1)
    N = int(Nv[0])
    kind = py_str(args[1]).lower() if len(args) > 1 and is_str(args[1]) else 'rgs'
    band = np.asarray(darr(args[2]), float).reshape(-1) if len(args) > 2 and numel(args[2]) else np.array([0.0, 1.0])
    lev = np.asarray(darr(args[3]), float).reshape(-1) if len(args) > 3 and numel(args[3]) else np.array([-1.0, 1.0])
    if N < 1 or band.size != 2 or not 0 <= band[0] < band[1] <= 1:
        raise err('Ident:idinput:InvalidInput', 'N is a positive whole number and band [lo hi] within [0 1].', 'idinput')
    from .elmat import RNG
    rs = RNG.rs

    def band_limit(x):
        X = np.fft.rfft(x)
        f = np.linspace(0, 1, X.size)
        X[(f < band[0]) | (f > band[1])] = 0
        return np.fft.irfft(X, x.size)
    if kind == 'rgs':
        x = band_limit(rs.standard_normal(N)) if not (band[0] == 0 and band[1] == 1) else rs.standard_normal(N)
        x = (x - x.mean()) / (x.std() or 1)
        u = (lev[0] + lev[1]) / 2 + x * (lev[1] - lev[0]) / 2
    elif kind == 'rbs':
        x = band_limit(rs.standard_normal(N)) if not (band[0] == 0 and band[1] == 1) else rs.standard_normal(N)
        u = np.where(x >= 0, lev[1], lev[0])
    elif kind == 'prbs':
        # a maximum-length shift register: x^n + x^(n-1) + ... taps from a table of primitive polynomials
        taps = {2: (2, 1), 3: (3, 2), 4: (4, 3), 5: (5, 3), 6: (6, 5), 7: (7, 6), 8: (8, 6, 5, 4), 9: (9, 5), 10: (10, 7), 11: (11, 9), 12: (12, 6, 4, 1),
                13: (13, 4, 3, 1), 14: (14, 5, 3, 1), 15: (15, 14), 16: (16, 15, 13, 4), 17: (17, 14), 18: (18, 11)}
        n = max(2, min(18, int(math.ceil(math.log2(N + 1)))))
        state = [1] * n
        seq = []
        hold = max(1, int(round(1 / band[1]))) if band[1] < 1 else 1
        while len(seq) < N:
            bit = state[-1]
            fb = 0
            for t in taps[n]:
                fb ^= state[t - 1]
            state = [fb] + state[:-1]
            seq += [bit] * hold
        u = np.where(np.array(seq[:N]) == 1, lev[1], lev[0]).astype(float)
    elif kind == 'sine':
        nsin = 10
        f = np.linspace(max(band[0], 1 / N), band[1], nsin) * math.pi
        t = np.arange(N)
        ph = rs.uniform(0, 2 * math.pi, nsin)
        x = np.sum(np.sin(np.outer(t, f) + ph), axis=1)
        x = (x - x.mean()) / (x.std() or 1)
        u = (lev[0] + lev[1]) / 2 + x * (lev[1] - lev[0]) / 2
    else:
        raise err('Ident:idinput:InvalidType', "The type is 'rgs', 'rbs', 'prbs' or 'sine'.", 'idinput')
    return out(u.reshape(-1, 1))


# ---- the models ------------------------------------------------------------------------------------------------------------------

def _q_text(p, var='z'):
    """1 - 1.5 z^-1 + 0.7 z^-2."""
    terms = []
    for k, c in enumerate(np.asarray(p, float)):
        if c == 0:
            continue
        mag = abs(c)
        one = abs(mag - 1) < 1e-9
        v = '' if k == 0 else (f'{var}^-1' if k == 1 else f'{var}^-{k}')
        body = (f'{mag:.4g}' if (not one or not v) else '') + (' ' if not one and v else '') + v
        terms.append(('-' if c < 0 else '+', body.strip()))
    if not terms:
        return '0'
    s = ('-' if terms[0][0] == '-' else '') + terms[0][1]
    for sign, body in terms[1:]:
        s += f' {sign} {body}'
    return s


def _ztf(b, a):
    """B(q^-1)/A(q^-1) as numerator and denominator in descending powers of z (the zeros at the end)."""
    L = max(len(b), len(a))
    return np.pad(np.asarray(b, float), (0, L - len(b))), np.pad(np.asarray(a, float), (0, L - len(a)))


def _fit_report(method, y, yhat, npar, N, focus='prediction', extra=None):
    e = y - yhat
    mse = float(np.mean(e ** 2)) if e.size else np.nan
    den = np.linalg.norm(y - y.mean())
    fitp = float(100 * (1 - np.linalg.norm(e) / den)) if den > 0 else np.nan
    ratio = npar / N
    fpe = mse * (1 + ratio) / (1 - ratio) if ratio < 1 else np.inf
    aic = N * math.log(mse) + 2 * npar + N * (math.log(2 * math.pi) + 1) if mse > 0 else -np.inf
    rep = {'Method': method, 'FitPercent': fitp, 'MSE': mse, 'FPE': fpe, 'AIC': aic, 'AICc': aic + 2 * npar * (npar + 1) / max(N - npar - 1, 1),
           'nAIC': math.log(mse) + 2 * npar / N if mse > 0 else -np.inf, 'BIC': (N * math.log(mse) + N * (math.log(2 * math.pi) + 1) + npar * math.log(N)) if mse > 0 else -np.inf,
           'LossFcn': mse, 'focus': focus, 'npar': npar, 'N': N}
    if extra:
        rep.update(extra)
    return rep


def _report_struct(rep, pvec, pcov):
    fit = Struct.scalar({k: float(rep[k]) for k in ('FitPercent', 'LossFcn', 'MSE', 'FPE', 'AIC', 'AICc', 'nAIC', 'BIC')})
    par = Struct.scalar({'ParVector': out(np.asarray(pvec, float).reshape(-1, 1)), 'FreeParCovariance': out(pcov) if pcov is not None else EMPTY()})
    return Struct.scalar({'Method': Char.of(rep['Method']), 'Fit': fit, 'Parameters': par, 'Status': Char.of(f"Estimated using {rep['Method']}")})


class IdPoly(CT.LTI):
    """A polynomial model; as a linear model it is G = B/(A F), from u to y (or the noise model for a time series)."""

    def __init__(self, A, B, C, D, F, Ts, noisevar=np.nan, nk=0, method='', rep=None, pvec=None, pcov=None, timeseries=False):
        self.A, self.B, self.C, self.D, self.F = (np.atleast_1d(np.asarray(p, float)) for p in (A, B, C, D, F))
        self.nk, self.noisevar, self.method, self.rep = nk, noisevar, method, rep or {}
        self.pvec, self.pcov = pvec, pcov
        self.timeseries = timeseries
        if timeseries:
            num, den = _ztf(self.C, np.convolve(self.A, self.D))
        else:
            num, den = _ztf(self.B, np.convolve(self.A, self.F))
        super().__init__('tf', ([[num]], [[den]]), Ts if Ts > 0 else 1.0, variable='z')

    @property
    def cls(self):
        return 'idpoly'

    def value_copy(self):
        return IdPoly(self.A, self.B, self.C, self.D, self.F, self.Ts, self.noisevar, self.nk, self.method, self.rep, self.pvec, self.pcov, self.timeseries)

    def kind_name(self):
        has = lambda p: p.size > 1
        if self.timeseries:
            return 'AR' if not has(self.C) and not has(self.D) else 'ARMA'
        if has(self.F) and not has(self.A):
            return 'BJ' if has(self.C) or has(self.D) else 'OE'
        if has(self.C):
            return 'ARMAX'
        return 'ARX'

    def getprop(self, name):
        k = name.lower()
        if k in ('a', 'b', 'c', 'd', 'f'):
            return out(getattr(self, k.upper()).reshape(1, -1))
        if k == 'noisevariance':
            return float(self.noisevar)
        if k == 'report':
            return _report_struct(self.rep, self.pvec if self.pvec is not None else [], self.pcov)
        if k == 'iodelay':
            return 0.0
        return super().getprop(name)

    def propnames(self):
        return ['A', 'B', 'C', 'D', 'F', 'NoiseVariance', 'Report', 'Ts'] + [p for p in super().propnames() if p not in ('Ts',)]

    def display_lines(self):
        kind = self.kind_name()
        eqs = {'ARX': 'A(z)y(t) = B(z)u(t) + e(t)', 'ARMAX': 'A(z)y(t) = B(z)u(t) + C(z)e(t)', 'OE': 'y(t) = [B(z)/F(z)]u(t) + e(t)',
               'BJ': 'y(t) = [B(z)/F(z)]u(t) + [C(z)/D(z)]e(t)', 'AR': 'A(z)y(t) = e(t)', 'ARMA': 'A(z)y(t) = C(z)e(t)'}
        lines = [f'  Discrete-time {kind} model: {eqs[kind]}']
        for nm in ('A', 'B', 'C', 'D', 'F'):
            p = getattr(self, nm)
            if (nm == 'B' and not self.timeseries) or p.size > 1 or (nm == 'A' and kind in ('ARX', 'ARMAX', 'AR', 'ARMA')):
                lines.append(f'    {nm}(z) = {_q_text(p)}')
        lines += ['', f'  Sample time: {self.Ts:g} seconds', '']
        if self.rep:
            focus = self.rep.get('focus', 'prediction')
            lines += [f'  Status:', f'  Estimated using {self.method}.',
                      f'  Fit to estimation data: {self.rep["FitPercent"]:.4g}% ({focus} focus)',
                      f'  FPE: {self.rep["FPE"]:.4g}, MSE: {self.rep["MSE"]:.4g}']
        return lines

    def noise_tf(self):
        return np.convolve(self.C, [1.0]), np.convolve(self.A, self.D)

    def simulate(self, u):
        return _lfilter(self.B, np.convolve(self.A, self.F), u)

    def predict(self, y, u, K):
        """K-step-ahead predictions (K = inf: the simulation)."""
        G = self.simulate(u) if u is not None and not self.timeseries else np.zeros_like(y)
        if math.isinf(K):
            return G
        c, ad = self.C, np.convolve(self.A, self.D)
        # W_K = Hbar_K * A D / C with Hbar_K the first K terms of H = C/(A D)
        imp = np.zeros(int(K))
        imp[0] = 1
        hk = _lfilter(c, ad, imp)
        wnum = np.convolve(hk, ad)
        Wy = _lfilter(wnum, c, y)
        WG = _lfilter(wnum, c, G)
        return WG + y - Wy

    def ss(self):
        """A state-space realization of G (for initial states)."""
        num, den = self.data[0][0][0], self.data[1][0][0]
        from scipy.signal import tf2ss
        # leading zeros off first (a delay's), as SciPy warns of a badly conditioned numerator over any it strips
        num = np.trim_zeros(np.asarray(num, float), 'f')
        A, B, C, D = tf2ss(num if num.size else np.zeros(1), den)
        return A, B, C, D


class IdSS(CT.LTI):
    """A state-space model in innovations form x(t+1) = A x + B u + K e, y = C x + D u + e."""

    def __init__(self, A, B, C, D, K, Ts, noisevar=np.nan, method='', rep=None, pvec=None, pcov=None):
        self.K = np.asarray(K, float).reshape(-1, 1)
        self.noisevar, self.method, self.rep, self.pvec, self.pcov = noisevar, method, rep or {}, pvec, pcov
        super().__init__('ss', (np.asarray(A, float), np.asarray(B, float).reshape(np.shape(A)[0], -1), np.asarray(C, float).reshape(1, -1),
                                np.asarray(D, float).reshape(1, -1)), Ts)

    @property
    def cls(self):
        return 'idss'

    def value_copy(self):
        A, B, C, D = self.data
        return IdSS(A.copy(), B.copy(), C.copy(), D.copy(), self.K.copy(), self.Ts, self.noisevar, self.method, self.rep, self.pvec, self.pcov)

    def getprop(self, name):
        k = name.lower()
        if k == 'k':
            return out(self.K)
        if k == 'noisevariance':
            return float(self.noisevar)
        if k == 'report':
            return _report_struct(self.rep, self.pvec if self.pvec is not None else [], self.pcov)
        return super().getprop(name)

    def propnames(self):
        return ['A', 'B', 'C', 'D', 'K', 'NoiseVariance', 'Report'] + [p for p in super().propnames() if p not in ('A', 'B', 'C', 'D')]

    def display_lines(self):
        A, B, C, D = self.data
        lines = [f'  Discrete-time identified state-space model:', '    x(t+Ts) = A x(t) + B u(t) + K e(t)', '       y(t) = C x(t) + D u(t) + e(t)', '']
        for nm, M in (('A', A), ('B', B), ('C', C), ('D', D), ('K', self.K)):
            lines.append(f'  {nm} =')
            for row in np.atleast_2d(M):
                lines.append('    ' + '  '.join(f'{v:10.4g}' for v in row))
        lines += ['', f'  Sample time: {self.Ts:g} seconds', '']
        if self.rep:
            lines += ['  Status:', f'  Estimated using {self.method}.', f'  Fit to estimation data: {self.rep["FitPercent"]:.4g}% ({self.rep.get("focus", "prediction")} focus)',
                      f'  FPE: {self.rep["FPE"]:.4g}, MSE: {self.rep["MSE"]:.4g}']
        return lines

    def simulate(self, u, x0=None):
        A, B, C, D = self.data
        n = A.shape[0]
        x = np.zeros(n) if x0 is None else np.asarray(x0, float)
        y = np.zeros(u.size if u is not None else 0)
        for t in range(y.size):
            ut = u[t] if u is not None else 0.0
            y[t] = (C @ x)[0] + (D[0, 0] * ut if D.size else 0.0)
            x = A @ x + (B[:, 0] * ut if B.size else 0.0)
        return y

    def predict(self, y, u, K, x0=None):
        A, B, C, D = self.data
        n = A.shape[0]
        uu = u if u is not None else np.zeros(y.size)
        if math.isinf(K):
            return self.simulate(uu, x0)
        Kg = self.K.reshape(-1)
        x = np.zeros(n) if x0 is None else np.asarray(x0, float)
        xs = []
        for t in range(y.size):
            xs.append(x.copy())
            yh = (C @ x)[0] + (D[0, 0] * uu[t] if D.size else 0.0)
            x = A @ x + (B[:, 0] * uu[t] if B.size else 0.0) + Kg * (y[t] - yh)
        xs = np.array(xs)
        yp = np.zeros(y.size)
        k = int(K)
        for t in range(y.size):
            s = t - k + 1
            if s < 0:
                xx, start = np.zeros(n) if x0 is None else np.asarray(x0, float), 0
            else:
                xx, start = xs[s], s
            for j in range(start, t):
                xx = A @ xx + (B[:, 0] * uu[j] if B.size else 0.0)
            yp[t] = (C @ xx)[0] + (D[0, 0] * uu[t] if D.size else 0.0)
        return yp

    def ss(self):
        return self.data


def _install_ops():
    from .. import ops
    for cls_ in (IdPoly, IdSS):
        ops.OBJ_OPS[cls_] = CT._ops


_install_ops()


def _orders(v, k, fn, what):
    o = np.asarray(darr(v), float).reshape(-1)
    if o.size != k or np.any(o < 0) or np.any(o != np.round(o)):
        raise err(f'Ident:{fn}:InvalidOrders', f'The orders are {what}: {k} whole numbers from 0.', fn)
    return [int(x) for x in o]


def _shift(x, k, N):
    """x delayed by k samples (zeros before the start)."""
    s = np.zeros(N)
    if k < N:
        s[k:] = x[:N - k]
    return s


def _arx_fit(y, u, na, nb, nk):
    N = y.size
    cols = [-_shift(y, i, N) for i in range(1, na + 1)]
    if u is not None:
        cols += [_shift(u, nk + j, N) for j in range(nb)]
    t0 = max([na] + ([nk + nb - 1] if u is not None and nb else [0]))
    Phi = np.column_stack(cols)[t0:] if cols else np.zeros((N - t0, 0))
    yt = y[t0:]
    th, *_ = np.linalg.lstsq(Phi, yt, rcond=None) if Phi.shape[1] else (np.zeros(0),)
    e = yt - Phi @ th
    A = np.concatenate([[1.0], th[:na]])
    B = np.concatenate([np.zeros(nk), th[na:]]) if u is not None else np.zeros(1)
    npar = th.size
    s2 = float(e @ e) / max(yt.size - npar, 1)
    cov = s2 * np.linalg.pinv(Phi.T @ Phi) if npar else np.zeros((0, 0))
    return A, B, th, cov, e, t0


def _mk_poly(y, u, Ts, A, B, C, D, F, nk, method, th, cov, timeseries=False, focus='prediction'):
    M = IdPoly(A, B, C, D, F, Ts, nk=nk, method=method, timeseries=timeseries)
    yp = M.predict(y, u, 1)
    e = y - yp
    npar = int(np.size(th))
    M.noisevar = float(e @ e) / max(y.size - npar, 1)
    M.rep = _fit_report(method, y, yp, npar, y.size, focus)
    M.pvec, M.pcov = np.asarray(th, float), cov
    return M


@bi('arx', arr=False)
def arx(nargout, *args):
    """sys = arx(data, [na nb nk]): an ARX model A(q)y(t) = B(q)u(t-nk) + e(t) by least squares (a time series: arx(y, na))."""
    nargchk(args, 2, 4, 'arx')
    y, u, Ts = _data(args[0], 'arx')
    if u is None:
        na = _orders(args[1], 1, 'arx', '[na] for a time series')[0]
        nb, nk = 0, 0
    else:
        na, nb, nk = _orders(args[1], 3, 'arx', '[na nb nk]')
    A, B, th, cov, e, t0 = _arx_fit(y, u, na, nb, nk)
    return _mk_poly(y, u, Ts, A, B if u is not None else [1.0], [1.0], [1.0], [1.0], nk, 'ARX', th, cov, timeseries=u is None)


@bi('ar', arr=False)
def ar(nargout, *args):
    """sys = ar(y, n, approach): an autoregressive model of a time series by least squares ('ls', the default) or Yule-Walker ('yw')."""
    nargchk(args, 2, 3, 'ar')
    y, u, Ts = _data(args[0], 'ar')
    n = int(num(args[1]))
    how = py_str(args[2]).lower() if len(args) > 2 and is_str(args[2]) else 'ls'
    if how == 'yw':
        from scipy.linalg import solve_toeplitz
        d = y - y.mean() * 0
        N = d.size
        r = np.array([d[:N - k] @ d[k:] / N for k in range(n + 1)])
        phi = solve_toeplitz(r[:n], r[1:n + 1])
        A = np.concatenate([[1.0], -phi])
        M = IdPoly(A, [1.0], [1.0], [1.0], [1.0], Ts, method='AR (Yule-Walker)', timeseries=True)
        yp = M.predict(y, None, 1)
        M.rep = _fit_report('AR (Yule-Walker)', y, yp, n, N)
        M.noisevar = float(r[0] - phi @ r[1:n + 1])
        M.pvec = A[1:]
        return M
    if how != 'ls':
        raise err('Ident:ar:InvalidApproach', "The approach is 'ls' or 'yw' here.", 'ar')
    A, B, th, cov, e, t0 = _arx_fit(y, None, n, 0, 0)
    return _mk_poly(y, None, Ts, A, [1.0], [1.0], [1.0], [1.0], 0, 'AR (least squares)', th, cov, timeseries=True)


def _stabilize(p):
    """A polynomial in q^-1 with its roots outside the unit circle moved inside (reflected)."""
    p = np.asarray(p, float)
    if p.size <= 1:
        return p
    r = np.roots(p)
    big = np.abs(r) >= 1
    if not np.any(big):
        return p
    r[big] = 1 / np.conj(r[big])
    q = np.real(np.poly(r))
    return q * p[0] / q[0]


def _pem(y, u, parts, x0, residual, fn):
    """Least squares of the prediction errors over the free coefficients (scipy.optimize.least_squares), the C, D and F
    polynomials kept stable."""
    from scipy.optimize import least_squares

    def res(x):
        r = residual(x)
        return np.where(np.isfinite(r), r, 1e10)
    sol = least_squares(res, x0, method='lm' if x0.size <= y.size else 'trf', xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=200 * (x0.size + 1))
    J = sol.jac
    e = sol.fun
    s2 = float(e @ e) / max(y.size - x0.size, 1)
    cov = s2 * np.linalg.pinv(J.T @ J)
    return sol.x, cov


def _split(x, sizes):
    out_, k = [], 0
    for s in sizes:
        out_.append(x[k:k + s])
        k += s
    return out_


def _hannan_rissanen(y, u, na, nb, nc, nk):
    """Starting values for ARMAX: a long ARX model's residuals as the noise, then least squares with them."""
    N = y.size
    nl = min(max(na + nb + nc + 4, 10), N // 4)
    A0, B0, _, _, _, _ = _arx_fit(y, u, nl, nl if u is not None else 0, max(nk, 0))
    w = _lfilter(A0, [1.0], y) - (_lfilter(B0, [1.0], u) if u is not None else 0)
    cols = [-_shift(y, i, N) for i in range(1, na + 1)]
    if u is not None:
        cols += [_shift(u, nk + j, N) for j in range(nb)]
    cols += [_shift(w, i, N) for i in range(1, nc + 1)]
    t0 = max([na, nc, nl] + ([nk + nb - 1] if u is not None else []))
    Phi = np.column_stack(cols)[t0:]
    th, *_ = np.linalg.lstsq(Phi, y[t0:], rcond=None)
    a, b, c = _split(th, [na, nb if u is not None else 0, nc])
    return np.concatenate([a, b, _stabilize(np.concatenate([[1.0], c]))[1:]])


@bi('armax', arr=False)
def armax(nargout, *args):
    """sys = armax(data, [na nb nc nk]): an ARMAX model A(q)y(t) = B(q)u(t-nk) + C(q)e(t) by minimizing the prediction errors
    (a time series: armax(y, [na nc]))."""
    nargchk(args, 2, 4, 'armax')
    y, u, Ts = _data(args[0], 'armax')
    if u is None:
        na, nc = _orders(args[1], 2, 'armax', '[na nc] for a time series')
        nb, nk = 0, 0
    else:
        na, nb, nc, nk = _orders(args[1], 4, 'armax', '[na nb nc nk]')
    x0 = _hannan_rissanen(y, u, na, nb, nc, nk)

    def polys(x):
        a, b, c = _split(x, [na, nb, nc])
        return (np.concatenate([[1.0], a]), np.concatenate([np.zeros(nk), b]) if u is not None else np.zeros(1), np.concatenate([[1.0], c]))

    def residual(x):
        A, B, C = polys(x)
        if not _stable(C):
            return np.full(y.size, 1e5)
        w = _lfilter(A, [1.0], y) - (_lfilter(B, [1.0], u) if u is not None else 0)
        return _lfilter([1.0], C, w)
    th, cov = _pem(y, u, None, x0, residual, 'armax')
    A, B, C = polys(th)
    return _mk_poly(y, u, Ts, A, B if u is not None else [1.0], C, [1.0], [1.0], nk, 'ARMAX' if u is not None else 'ARMA', th, cov, timeseries=u is None)


def _stable(p):
    p = np.asarray(p, float)
    if p.size <= 1:
        return True
    return bool(np.all(np.abs(np.roots(p)) < 1 - 1e-9))


@bi('oe', arr=False)
def oe(nargout, *args):
    """sys = oe(data, [nb nf nk]): an output-error model y(t) = B(q)/F(q) u(t-nk) + e(t) by minimizing the simulation errors."""
    nargchk(args, 2, 4, 'oe')
    y, u, Ts = _data(args[0], 'oe', need_input=True)
    nb, nf, nk = _orders(args[1], 3, 'oe', '[nb nf nk]')
    A0, B0, _, _, _, _ = _arx_fit(y, u, nf, nb, nk)
    x0 = np.concatenate([B0[nk:], _stabilize(A0)[1:]])

    def polys(x):
        b, f = _split(x, [nb, nf])
        return np.concatenate([np.zeros(nk), b]), np.concatenate([[1.0], f])

    def residual(x):
        B, F = polys(x)
        if not _stable(F):
            return np.full(y.size, 1e5)
        return y - _lfilter(B, F, u)
    th, cov = _pem(y, u, None, x0, residual, 'oe')
    B, F = polys(th)
    return _mk_poly(y, u, Ts, [1.0], B, [1.0], [1.0], F, nk, 'OE', th, cov, focus='simulation')


@bi('bj', arr=False)
def bj(nargout, *args):
    """sys = bj(data, [nb nc nd nf nk]): a Box-Jenkins model y(t) = B(q)/F(q) u(t-nk) + C(q)/D(q) e(t) by minimizing the prediction errors."""
    nargchk(args, 2, 4, 'bj')
    y, u, Ts = _data(args[0], 'bj', need_input=True)
    nb, nc, nd, nf, nk = _orders(args[1], 5, 'bj', '[nb nc nd nf nk]')
    m = oe(1, args[0], out(np.array([[nb, nf, nk]], float)))
    v = y - m.simulate(u)
    xn = _hannan_rissanen(v, None, nd, 0, nc, 0) if nc + nd else np.zeros(0)
    d0, c0 = _split(xn, [nd, nc])
    x0 = np.concatenate([m.B[nk:], c0, _stabilize(np.concatenate([[1.0], d0]))[1:], m.F[1:]])

    def polys(x):
        b, c, d, f = _split(x, [nb, nc, nd, nf])
        return (np.concatenate([np.zeros(nk), b]), np.concatenate([[1.0], c]), np.concatenate([[1.0], d]), np.concatenate([[1.0], f]))

    def residual(x):
        B, C, D, F = polys(x)
        if not (_stable(C) and _stable(F) and _stable(D)):
            return np.full(y.size, 1e5)
        return _lfilter(D, C, y - _lfilter(B, F, u))
    th, cov = _pem(y, u, None, x0, residual, 'bj')
    B, C, D, F = polys(th)
    return _mk_poly(y, u, Ts, [1.0], B, C, D, F, nk, 'BJ', th, cov)


# ---- state space ----------------------------------------------------------------------------------------------------------------

def _hankel(x, i, j):
    return np.array([x[k:k + j] for k in range(i)])


def _n4sid(y, u, nx, i=None):
    """Subspace identification (the N4SID oblique projection): the states from the projection of the future outputs on the
    past along the future inputs, then A, B, C, D by least squares and K from the residuals' covariances (a Riccati
    equation)."""
    from scipy.linalg import solve_discrete_are, lstsq, svd
    N = y.size
    i = i or max(nx + 1, 2 * nx, 10)
    j = N - 2 * i + 1
    if j < 4 * i:
        raise err('Ident:n4sid:TooFew', 'Too few samples for this order.', 'n4sid')
    has_u = u is not None
    Y = _hankel(y, 2 * i, j)
    Yp, Yf = Y[:i], Y[i:]
    if has_u:
        U = _hankel(u, 2 * i, j)
        Up, Uf = U[:i], U[i:]
        Wp = np.vstack([Up, Yp])
    else:
        Wp = Yp
    def oblique(Yf_, Uf_, Wp_):
        # the past outputs of noise-free data are combinations of the past inputs: a tolerance keeps round-off's
        # singular values out of the pseudo-inverse
        if Uf_ is None:
            return Yf_ @ np.linalg.pinv(Wp_, rcond=1e-10) @ Wp_
        Z = np.vstack([Wp_, Uf_])
        L = Yf_ @ np.linalg.pinv(Z, rcond=1e-10)
        Lw = L[:, :Wp_.shape[0]]
        return Lw @ Wp_
    Oi = oblique(Yf, Uf if has_u else None, Wp)
    Uo, s, Vt = svd(Oi, full_matrices=False)
    n = nx
    G = Uo[:, :n] * np.sqrt(s[:n])
    X = np.linalg.pinv(G, rcond=1e-10) @ Oi
    # the next states: one block later
    Yp2, Yf2 = Y[:i + 1], Y[i + 1:]
    if has_u:
        Up2, Uf2 = U[:i + 1], U[i + 1:]
        Wp2 = np.vstack([Up2, Yp2])
    else:
        Uf2, Wp2 = None, Yp2
    Oi2 = oblique(Yf2, Uf2, Wp2)
    X2 = np.linalg.pinv(G[:-1], rcond=1e-10) @ Oi2
    yi = Y[i:i + 1]
    lhs = np.vstack([X2, yi])
    rhs = np.vstack([X, U[i:i + 1]]) if has_u else X
    Th = lhs @ np.linalg.pinv(rhs, rcond=1e-10)
    A, C = Th[:n, :n], Th[n:, :n]
    B = Th[:n, n:] if has_u else np.zeros((n, 0))
    D = Th[n:, n:] if has_u else np.zeros((1, 0))
    W = lhs - Th @ rhs
    S = W @ W.T / W.shape[1]
    Q, Ss, Rr = S[:n, :n], S[:n, n:], S[n:, n:]
    try:
        P = solve_discrete_are(A.T, C.T, Q, Rr, s=Ss)
        K = (A @ P @ C.T + Ss) @ np.linalg.inv(C @ P @ C.T + Rr)
    except (np.linalg.LinAlgError, ValueError):
        K = np.zeros((n, 1))
    return A, B, C, D, K


def _mk_ss(y, u, Ts, A, B, C, D, K, method, npar, focus='prediction'):
    has_u = u is not None
    M = IdSS(A, B if has_u else np.zeros((A.shape[0], 0)), C, D if has_u else np.zeros((1, 0)), K, Ts, method=method)
    yp = M.predict(y, u, 1)
    e = y - yp
    M.noisevar = float(e @ e) / max(y.size - npar, 1)
    M.rep = _fit_report(method, y, yp, npar, y.size, focus)
    M.pvec = np.concatenate([np.ravel(A), np.ravel(B), np.ravel(C), np.ravel(D), np.ravel(K)])
    return M


@bi('n4sid', arr=False)
def n4sid(nargout, *args):
    """sys = n4sid(data, nx, 'Feedthrough', false): a state-space model of order nx in innovations form by subspace
    identification (no direct feedthrough unless asked)."""
    nargchk(args, 2, 6, 'n4sid')
    y, u, Ts = _data(args[0], 'n4sid')
    nx = int(num(args[1]))
    feed = False
    for k in range(2, len(args) - 1, 2):
        if is_str(args[k]) and py_str(args[k]).lower() == 'feedthrough':
            feed = bool(num(args[k + 1]))
    if nx < 1:
        raise err('Ident:n4sid:InvalidOrder', 'nx is a whole number from 1.', 'n4sid')
    yc, uc = y, u
    A, B, C, D, K = _n4sid(yc, uc, nx)
    if u is not None and not feed:
        # without feedthrough: B and C again by least squares on the simulated response with D = 0
        A, B, C, D = _refit_bd(y, u, A, C, feed=False)
    n = A.shape[0]
    npar = n * n + n * (1 if u is not None else 0) + n + n + (1 if feed else 0)
    return _mk_ss(y, u, Ts, A, B, C, D if u is not None else np.zeros((1, 0)), K, 'N4SID', npar)


def _refit_bd(y, u, A, C, feed=False):
    """B (and D) by least squares, the response being linear in them for fixed A and C, with an initial state."""
    n = A.shape[0]
    N = y.size
    cols = []
    for k in range(n):
        Bk = np.zeros(n)
        Bk[k] = 1
        x = np.zeros(n)
        col = np.zeros(N)
        for t in range(N):
            col[t] = (C @ x).item()
            x = A @ x + Bk * u[t]
        cols.append(col)
    # free response from each initial state
    xs = np.eye(n)
    for k in range(n):
        x = xs[k].copy()
        col = np.zeros(N)
        for t in range(N):
            col[t] = (C @ x).item()
            x = A @ x
        cols.append(col)
    if feed:
        cols.append(u.copy())
    Phi = np.column_stack(cols)
    th, *_ = np.linalg.lstsq(Phi, y, rcond=None)
    B = th[:n].reshape(n, 1)
    D = np.array([[th[-1]]]) if feed else np.zeros((1, 1))
    return A, B, C.reshape(1, -1), D


@bi('ssest', arr=False)
def ssest(nargout, *args):
    """sys = ssest(data, nx): a state-space model of order nx: n4sid's, then
    its prediction errors minimized over A, B, C and K (in a canonical
    form)."""
    nargchk(args, 2, 6, 'ssest')
    y, u, Ts = _data(args[0], 'ssest')
    nx = int(num(args[1]))
    S0 = n4sid(1, *args)
    A0, B0, C0, D0 = S0.data
    K0 = S0.K
    # the observer canonical form of the start: A companion, C = [1 0 ... 0]
    n = A0.shape[0]
    Ob = np.vstack([C0 @ np.linalg.matrix_power(A0, k) for k in range(n)])
    try:
        T = np.linalg.inv(Ob)
    except np.linalg.LinAlgError:
        T = np.eye(n)
    Ac, Bc, Cc, Kc = np.linalg.inv(T) @ A0 @ T, np.linalg.inv(T) @ (B0 if B0.size else np.zeros((n, 0))), C0 @ T, np.linalg.inv(T) @ K0
    a0 = Ac[-1, :].copy()
    has_u = u is not None
    x0 = np.concatenate([a0, Bc.reshape(-1) if has_u else [], Kc.reshape(-1)])

    def build(x):
        a, b, k = _split(x, [n, n if has_u else 0, n])
        A = np.zeros((n, n))
        if n > 1:
            A[:-1, 1:] = np.eye(n - 1)
        A[-1, :] = a
        C = np.zeros((1, n))
        C[0, 0] = 1
        return A, (b.reshape(n, 1) if has_u else np.zeros((n, 0))), C, k.reshape(n, 1)

    def residual(x):
        A, B, C, K = build(x)
        if np.max(np.abs(np.linalg.eigvals(A - K @ C))) >= 1:
            return np.full(y.size, 1e5)
        M = IdSS(A, B, C, np.zeros((1, B.shape[1])), K, Ts)
        return y - M.predict(y, u, 1)
    th, cov = _pem(y, u, None, x0, residual, 'ssest')
    A, B, C, K = build(th)
    M = _mk_ss(y, u, Ts, A, B, C, np.zeros((1, B.shape[1])), K, 'SSEST', th.size)
    M.pcov = cov
    return M


# ---- continuous transfer functions -------------------------------------------------------------------------------------------------

class IdTf(CT.LTI):
    """A continuous-time transfer function fitted to sampled data."""

    def __init__(self, num_, den_, rep=None, method='TFEST', pvec=None, pcov=None, noisevar=np.nan):
        self.rep, self.method, self.pvec, self.pcov, self.noisevar = rep or {}, method, pvec, pcov, noisevar
        n, d = CT._padded(np.asarray(num_, float), np.asarray(den_, float))
        super().__init__('tf', ([[n]], [[d]]), 0.0)

    @property
    def cls(self):
        return 'idtf'

    def value_copy(self):
        return IdTf(self.data[0][0][0].copy(), self.data[1][0][0].copy(), self.rep, self.method, self.pvec, self.pcov, self.noisevar)

    def getprop(self, name):
        k = name.lower()
        if k == 'numerator':
            return out(np.trim_zeros(self.data[0][0][0], 'f').reshape(1, -1) if np.any(self.data[0][0][0]) else np.zeros((1, 1)))
        if k == 'denominator':
            return out(self.data[1][0][0].reshape(1, -1))
        if k == 'report':
            return _report_struct(self.rep, self.pvec if self.pvec is not None else [], self.pcov)
        if k == 'noisevariance':
            return float(self.noisevar)
        return super().getprop(name)

    def propnames(self):
        return ['Numerator', 'Denominator', 'NoiseVariance', 'Report'] + super().propnames()

    def display_lines(self):
        lines = CT._display(self)
        if self.rep:
            # an identified model's closing line in place of a transfer function's, then how it was found
            k = max((i for i, ln in enumerate(lines) if ln.strip() == 'Continuous-time transfer function.'), default=None)
            if k is not None:
                lines[k] = 'Continuous-time identified transfer function.'
            lines += ['', '  Status:', f'  Estimated using {self.method}.',
                      f'  Fit to estimation data: {self.rep["FitPercent"]:.4g}% (simulation focus)',
                      f'  FPE: {self.rep["FPE"]:.4g}, MSE: {self.rep["MSE"]:.4g}']
        return lines

    def simulate(self, u, Ts):
        from scipy.signal import cont2discrete
        num_, den_ = self.data[0][0][0], self.data[1][0][0]
        bd, ad, _ = cont2discrete((num_, den_), Ts, method='zoh')
        return _lfilter(np.ravel(bd), ad, u)


@bi('tfest', arr=False)
def tfest(nargout, *args):
    """sys = tfest(data, np, nz): a continuous-time transfer function with np
    poles and nz zeros (np - 1 unless given): a discrete output-error model's
    poles and zeros carried to continuous time as the start, then the
    simulated output's errors minimized (the input held between samples)."""
    nargchk(args, 2, 4, 'tfest')
    y, u, Ts = _data(args[0], 'tfest', need_input=True)
    npo = int(num(args[1]))
    nz = int(num(args[2])) if len(args) > 2 and numel(args[2]) else npo - 1
    if npo < 1 or not 0 <= nz <= npo:
        raise err('Ident:tfest:InvalidOrders', 'np is a whole number from 1, nz from 0 to np.', 'tfest')
    from scipy.signal import cont2discrete
    from scipy.optimize import least_squares
    m = oe(1, args[0], out(np.array([[nz + 1, npo, 1]], float)))
    # the discrete poles carried over (s = log(z)/Ts), the gain matched at low frequency
    zp = np.roots(m.F) if m.F.size > 1 else np.zeros(0)
    sp = np.log(np.where(np.abs(zp) > 1e-6, zp, 1e-6).astype(complex)) / Ts
    den0 = np.real(np.poly(sp)) if sp.size else np.array([1.0])
    if den0.size < npo + 1:
        den0 = np.concatenate([den0, np.zeros(npo + 1 - den0.size)])
    dc = float(np.sum(m.B) / np.sum(m.F)) if abs(np.sum(m.F)) > 1e-12 else 1.0
    num0 = np.zeros(nz + 1)
    num0[-1] = dc * den0[-1] if den0[-1] != 0 else dc
    x0 = np.concatenate([num0, den0[1:]])

    def tfp(x):
        return x[:nz + 1], np.concatenate([[1.0], x[nz + 1:]])

    def residual(x):
        nu_, de_ = tfp(x)
        if np.any(np.real(np.roots(de_)) >= 0) and npo:
            return np.full(y.size, 1e5)
        bd, ad, _ = cont2discrete((nu_, de_), Ts, method='zoh')
        return y - _lfilter(np.ravel(bd), ad, u)
    sol = least_squares(lambda x: np.where(np.isfinite(residual(x)), residual(x), 1e10), x0, method='lm', xtol=1e-13, ftol=1e-13, gtol=1e-13,
                        max_nfev=400 * (x0.size + 1))
    nu_, de_ = tfp(sol.x)
    e = sol.fun
    s2 = float(e @ e) / max(y.size - x0.size, 1)
    cov = s2 * np.linalg.pinv(sol.jac.T @ sol.jac)
    M = IdTf(nu_, de_, method='TFEST', pvec=sol.x, pcov=cov)
    ys = y - e
    M.rep = _fit_report('TFEST', y, ys, x0.size, y.size, 'simulation')
    M.noisevar = s2
    return M


# ---- using the models ---------------------------------------------------------------------------------------------------------

def _is_model(v):
    return isinstance(v, (IdPoly, IdSS, IdTf))


def _response(M, y, u, Ts, K, x0='zero'):
    """The model's output for the data: simulated (K = inf) or predicted K steps ahead; with x0 'estimate' the initial state
    fitted by least squares (the response being linear in it)."""
    if isinstance(M, IdTf):
        return M.simulate(u, Ts)            # no noise model: its predictions are its simulation
    if x0 == 'estimate' and math.isinf(K) and u is not None:
        A, B, C, D = M.ss()
        A, B, C = np.atleast_2d(A), np.atleast_2d(B), np.atleast_2d(C)
        n = A.shape[0]
        base = _ss_sim(A, B, C, D, u, np.zeros(n))
        cols = [_ss_sim(A, B * 0, C, D * 0, u * 0, np.eye(n)[k]) for k in range(n)]
        if cols:
            Phi = np.column_stack(cols)
            th, *_ = np.linalg.lstsq(Phi, y - base, rcond=None)
            return base + Phi @ th
        return base
    return M.predict(y, u, K)


def _ss_sim(A, B, C, D, u, x0):
    x = np.asarray(x0, float).copy()
    y = np.zeros(u.size)
    D = np.atleast_2d(D)
    for t in range(u.size):
        y[t] = float((C @ x).reshape(-1)[0]) + (float(D.reshape(-1)[0]) * u[t] if D.size else 0.0)
        x = A @ x + (B[:, 0] * u[t] if B.size else 0.0)
    return y


def _arg_names(fname, positions):
    """The names of the variables given as these inputs (1 for the first) of fname on the calling line, as inputname
    reads them: '' for an expression, or where the call cannot be told from the line."""
    from .core import _plab_frames, _call_arg
    frames = _plab_frames(sys._getframe(1))
    if not frames:
        return [''] * len(positions)
    mod, _, ln = frames[0]
    return [_call_arg(mod, ln, fname, k) or '' for k in positions]


def _fit_percent(y, yh):
    den = np.linalg.norm(y - y.mean())
    return float(100 * (1 - np.linalg.norm(y - yh) / den)) if den > 0 else np.nan


@bi('compare', nout=3, arr=False)
def compare(nargout, *args):
    """[y, fit] = compare(data, sys1, sys2, ..., K): the models' simulated
    outputs (or K-step-ahead predictions) against the measured output, with
    the fit 100*(1 - norm(y - yhat)/norm(y - mean(y))); the initial state is
    estimated for simulations. Without outputs, plotted with the fits in the
    legend."""
    nargchk(args, 2, 20, 'compare')
    data = args[0]
    if not isinstance(data, IdData):
        raise err('Ident:compare:NoData', 'compare takes iddata first.', 'compare')
    y, u, Ts = _data(data, 'compare')
    models = [a for a in args[1:] if _is_model(a)]
    rest = [a for a in args[1:] if not _is_model(a) and not is_str(a)]
    K = float(num(rest[0])) if rest else math.inf
    names = _arg_names('compare', [k + 1 for k, a in enumerate(args) if _is_model(a)]) if nargout == 0 else []
    if not models:
        raise err('Ident:compare:NoModels', 'Give one or more identified models.', 'compare')
    ys, fits = [], []
    for M in models:
        yh = _response(M, y, u, Ts, K, 'estimate')
        ys.append(yh)
        fits.append(_fit_percent(y, yh))
    if nargout == 0:
        t = data.tstart + Ts * np.arange(y.size)
        b = lambda name, *a: R._builtin(name, *a)
        b('plot', out(t.reshape(-1, 1)), out(y.reshape(-1, 1)), Char.of('Color'), out(np.array([[0.5, 0.5, 0.5]])))
        b('hold', Char.of('on'))
        for yh in ys:
            b('plot', out(t.reshape(-1, 1)), out(yh.reshape(-1, 1)))
        b('hold', Char.of('off'))
        labels = [Char.of('Measured')] + [Char.of(f'{names[k] or f"Model {k + 1}"}: {f:.2f}%') for k, f in enumerate(fits)]
        b('legend', *labels)
        b('title', Char.of('Simulated Response Comparison' if math.isinf(K) else f'{int(K)}-Step Predicted Response Comparison'))
        b('xlabel', Char.of(f'Time ({data.unit})'))
        b('ylabel', Char.of(data.yname[0]))
        return None
    yo = [IdData(yh.reshape(-1, 1), None, Ts) for yh in ys]
    yv = yo[0] if len(yo) == 1 else Cell.of_list(yo, (1, len(yo)))
    fv = fits[0] if len(fits) == 1 else out(np.array([fits]))
    return (yv, fv, EMPTY())[:nargout] if nargout > 1 else yv


def _predict_ident(nargout, M, *rest):
    """yp = predict(sys, data, K): K-step-ahead predictions (1)."""
    if not rest or not isinstance(rest[0], IdData) and not isinstance(rest[0], np.ndarray):
        raise err('Ident:predict:NoData', 'predict(sys, data, K) takes iddata.', 'predict')
    y, u, Ts = _data(rest[0], 'predict')
    K = float(num(rest[1])) if len(rest) > 1 else 1.0
    yp = _response(M, y, u, Ts, K)
    return IdData(yp.reshape(-1, 1), None, Ts) if isinstance(rest[0], IdData) else out(yp.reshape(-1, 1))


@bi('sim', arr=False)
def sim(nargout, *args):
    """y = sim(sys, u) or sim(sys, data): the model's response to the input from rest (no noise)."""
    nargchk(args, 2, 4, 'sim')
    M = args[0]
    if not _is_model(M):
        raise err('Ident:sim:NotModel', 'sim takes an identified model first.', 'sim')
    if isinstance(args[1], IdData):
        y, u, Ts = _data(args[1], 'sim')
    else:
        u = np.asarray(darr(args[1]), float).reshape(-1)
        Ts = M.Ts if M.Ts > 0 else 1.0
        y = np.zeros(u.size)
    if u is None:
        raise err('Ident:sim:NoInput', 'sim needs an input.', 'sim')
    ys = M.simulate(u, Ts) if isinstance(M, IdTf) else M.simulate(u)
    return IdData(ys.reshape(-1, 1), None, Ts) if isinstance(args[1], IdData) else out(ys.reshape(-1, 1))


@bi('pe', arr=False)
def pe(nargout, *args):
    """e = pe(sys, data, K): the K-step-ahead prediction errors (1)."""
    nargchk(args, 2, 3, 'pe')
    M, data = args[0], args[1]
    if not _is_model(M):
        raise err('Ident:pe:NotModel', 'pe takes an identified model first.', 'pe')
    y, u, Ts = _data(data, 'pe')
    K = float(num(args[2])) if len(args) > 2 else 1.0
    e = y - _response(M, y, u, Ts, K)
    return IdData(e.reshape(-1, 1), None, Ts) if isinstance(data, IdData) else out(e.reshape(-1, 1))


@bi('resid', nout=2, arr=False)
def resid(nargout, *args):
    """[E, R] = resid(data, sys): residual analysis: the one-step prediction
    errors, the autocorrelation of the errors and their cross-correlation
    with the input (lags 0 to 25 and -25 to 25) with 99% bounds; without
    outputs, plotted."""
    nargchk(args, 2, 4, 'resid')
    data, M = args[0], args[1]
    if _is_model(data) and isinstance(M, IdData):
        data, M = M, data
    if not _is_model(M):
        raise err('Ident:resid:NotModel', 'resid takes data and an identified model (arx, armax, oe, bj, n4sid, ssest, tfest).', 'resid')
    y, u, Ts = _data(data, 'resid')
    e = y - _response(M, y, u, Ts, 1.0)
    L = 25
    N = e.size
    ec = e - e.mean()
    r = np.array([ec[:N - k] @ ec[k:] / N for k in range(L + 1)]) / (ec @ ec / N)
    bound = 2.576 / math.sqrt(N)
    if u is not None:
        uc = u - u.mean()
        su = math.sqrt(uc @ uc / N)
        se = math.sqrt(ec @ ec / N)
        xc = np.array([(ec[k:] @ uc[:N - k] if k >= 0 else ec[:N + k] @ uc[-k:]) / N for k in range(-L, L + 1)]) / (su * se)
    if nargout == 0:
        b = lambda name, *a: R._builtin(name, *a)
        b('figure')
        b('subplot', 2.0 if u is not None else 1.0, 1.0, 1.0)
        b('stem', out(np.arange(L + 1, dtype=float).reshape(-1, 1)), out(r.reshape(-1, 1)))
        b('hold', Char.of('on'))
        b('plot', out(np.array([[0.0], [L]])), out(np.array([[bound], [bound]])), Char.of('r--'))
        b('plot', out(np.array([[0.0], [L]])), out(np.array([[-bound], [-bound]])), Char.of('r--'))
        b('hold', Char.of('off'))
        b('title', Char.of('Autocorrelation of residuals'))
        if u is not None:
            b('subplot', 2.0, 1.0, 2.0)
            b('stem', out(np.arange(-L, L + 1, dtype=float).reshape(-1, 1)), out(xc.reshape(-1, 1)))
            b('hold', Char.of('on'))
            b('plot', out(np.array([[-L], [L]], float)), out(np.array([[bound], [bound]])), Char.of('r--'))
            b('plot', out(np.array([[-L], [L]], float)), out(np.array([[-bound], [-bound]])), Char.of('r--'))
            b('hold', Char.of('off'))
            b('title', Char.of('Cross-correlation of residuals with the input'))
            b('xlabel', Char.of('Lag'))
        return None
    E = IdData(e.reshape(-1, 1), u.reshape(-1, 1) if u is not None else None, Ts)
    Rv = Struct.scalar({'AutoCorr': out(r.reshape(-1, 1)), 'CrossCorr': out(xc.reshape(-1, 1)) if u is not None else EMPTY(), 'Bound': bound})
    return (E, Rv) if nargout > 1 else E


@bi('polydata', nout=10, arr=False)
def polydata(nargout, *args):
    """[A, B, C, D, F, dA, dB, dC, dD, dF] = polydata(sys): a polynomial model's polynomials and their coefficients' standard deviations."""
    nargchk(args, 1, 1, 'polydata')
    M = args[0]
    if not isinstance(M, IdPoly):
        raise err('Ident:polydata:NotPoly', 'polydata takes a polynomial model (arx, armax, oe, bj, ar).', 'polydata')
    polys = [M.A, M.B, M.C, M.D, M.F]
    sd = [np.zeros_like(p) for p in polys]
    if M.pcov is not None and np.size(M.pcov):
        s = np.sqrt(np.maximum(np.diag(M.pcov), 0))
        k = 0
        order = _free_positions(M)
        for (pi, idx) in order:
            if k < s.size:
                sd[pi][idx] = s[k]
            k += 1
    vals = [out(p.reshape(1, -1)) for p in polys] + [out(d.reshape(1, -1)) for d in sd]
    n = max(nargout, 1)
    return tuple(vals[:n]) if n > 1 else vals[0]


def _free_positions(M):
    """The coefficients the estimate varied, in its parameter order: (polynomial index, position)."""
    kind = M.kind_name()
    pos = []
    if kind in ('ARX', 'AR', 'ARMAX', 'ARMA'):
        pos += [(0, k) for k in range(1, M.A.size)]
        if not M.timeseries:
            pos += [(1, k) for k in range(M.nk, M.B.size)]
        pos += [(2, k) for k in range(1, M.C.size)]
    elif kind == 'OE':
        pos += [(1, k) for k in range(M.nk, M.B.size)] + [(4, k) for k in range(1, M.F.size)]
    else:
        pos += [(1, k) for k in range(M.nk, M.B.size)] + [(2, k) for k in range(1, M.C.size)] + [(3, k) for k in range(1, M.D.size)] + [(4, k) for k in range(1, M.F.size)]
    return pos


@bi('present')
def present(nargout, *args):
    """present(sys): a model shown with the standard deviations of its estimated coefficients."""
    nargchk(args, 1, 1, 'present')
    M = args[0]
    lines = list(M.display_lines()) if hasattr(M, 'display_lines') else []
    if isinstance(M, IdPoly) and M.pcov is not None:
        vals = polydata(10, M)
        names = 'ABCDF'
        lines.append('')
        lines.append('  Coefficients with their standard deviations:')
        for k in range(5):
            p = np.asarray(vals[k]).reshape(-1)
            d = np.asarray(vals[5 + k]).reshape(-1)
            if p.size > 1 or (names[k] == 'B' and not M.timeseries):
                lines.append(f'    {names[k]}: ' + '  '.join(f'{v:.4g} (+/- {s:.3g})' if s else f'{v:.4g}' for v, s in zip(p, d)))
    R.write('\n'.join(lines) + '\n')
    return None


@bi('aic')
def aic(nargout, *args):
    """value = aic(sys1, sys2, ..., measure): the models' Akaike information criteria ('aic', the default; 'AICc', 'nAIC', 'BIC')."""
    nargchk(args, 1, 20, 'aic')
    measure = 'AIC'
    models = list(args)
    if models and is_str(models[-1]):
        measure = {'aic': 'AIC', 'aicc': 'AICc', 'naic': 'nAIC', 'bic': 'BIC'}.get(py_str(models.pop()).lower())
        if measure is None:
            raise err('Ident:aic:InvalidMeasure', "The measure is 'aic', 'AICc', 'nAIC' or 'BIC'.", 'aic')
    vals = []
    for M in models:
        if not _is_model(M) or not M.rep:
            raise err('Ident:aic:NotEstimated', 'aic takes estimated models.', 'aic')
        vals.append(M.rep[measure])
    return out(np.array([vals])) if len(vals) > 1 else float(vals[0])


@bi('fpe')
def fpe(nargout, *args):
    """value = fpe(sys1, sys2, ...): the models' final prediction errors, MSE*(1 + d/N)/(1 - d/N)."""
    nargchk(args, 1, 20, 'fpe')
    vals = []
    for M in args:
        if not _is_model(M) or not M.rep:
            raise err('Ident:fpe:NotEstimated', 'fpe takes estimated models.', 'fpe')
        vals.append(M.rep['FPE'])
    return out(np.array([vals])) if len(vals) > 1 else float(vals[0])


# ---- the builtins that take iddata or models too ---------------------------------------------------------------------------------

def _detrend_data(nargout, d, *rest):
    o = d.value_copy()
    order = int(num(rest[0])) if rest else 0
    t = np.arange(o.N, dtype=float)
    for M in (o.y, o.u):
        for j in range(M.shape[1]):
            c = np.polyfit(t, M[:, j], order)
            M[:, j] = M[:, j] - np.polyval(c, t)
    return o


def _size_data(nargout, d, *rest):
    sh = (float(d.N), float(d.y.shape[1]), float(d.u.shape[1]))
    if rest:
        return sh[int(num(rest[0])) - 1]
    if nargout <= 1:
        return out(np.array([sh]))
    return sh[:nargout]


def _plot_data(nargout, d, *rest):
    b = lambda name, *a: R._builtin(name, *a)
    t = (d.tstart + d.Ts * np.arange(d.N)).reshape(-1, 1)
    n = d.y.shape[1] + d.u.shape[1]
    k = 1
    for j in range(d.y.shape[1]):
        b('subplot', float(n), 1.0, float(k))
        b('plot', out(t), out(d.y[:, j:j + 1]))
        b('title', Char.of(d.yname[j]))
        k += 1
    for j in range(d.u.shape[1]):
        b('subplot', float(n), 1.0, float(k))
        b('stairs', out(t), out(d.u[:, j:j + 1]))
        b('title', Char.of(d.uname[j]))
        k += 1
    b('xlabel', Char.of(f'Time ({d.unit})'))
    return None


from .curvefit import _wrap as _cf_wrap  # noqa: E402
_cf_wrap('predict', _is_model, _predict_ident)
_cf_wrap('detrend', lambda v: isinstance(v, IdData), _detrend_data)
_cf_wrap('size', lambda v: isinstance(v, IdData), _size_data)
_cf_wrap('plot', lambda v: isinstance(v, IdData), _plot_data)
REG['size'].nout = max(REG['size'].nout, 3)


def classes():
    return (IdData, IdPoly, IdSS, IdTf)
