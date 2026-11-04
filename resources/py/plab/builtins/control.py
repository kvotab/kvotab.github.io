"""Control systems: linear time-invariant models (tf, zpk, ss, pid), their
algebra (+, -, *, /, feedback, series, parallel, inv, concatenation,
indexing, delays), conversions (tfdata, zpkdata, ssdata, ss2tf, tf2ss,
c2d, d2c, canon, ss2ss, xperm, minreal, pade), analysis (pole, zero,
tzero, dcgain, damp, isstable, evalfr, freqresp, stepinfo, margin,
allmargin, bandwidth, norm, getPeakGain, covar, ctrb, obsv, gram, hsvd),
responses drawn or returned (step, impulse, initial, lsim, bode, nyquist,
nichols, sigma, rlocus, pzmap), design (lqr, dlqr, lqry, lqe, kalman,
estim, reg, place, acker), reduction (balreal, balred, modred) and the
matrix equations (lyap, dlyap, care, dare).

A model is held as it was made (a transfer function's polynomials, a
zero-pole-gain form's roots, or state-space matrices) and converted when
an operation needs another form: an operation mixing forms gives state
space if either is, else zero-pole-gain if either is, else a transfer
function."""
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, num, is_str, darr, out
from ..values import MError, Obj, Char, Cell, Struct, Str, EMPTY, numel, py_str, text_list
from .. import runtime as R


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, np.linalg.LinAlgError) as e:
                raise err(f'Control:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _vec(v):
    return np.asarray(darr(v), complex if np.iscomplexobj(darr(v)) else float).reshape(-1)


def _mat(v, fn='', what='the matrix'):
    a = np.asarray(darr(v), float)
    if a.ndim != 2:
        raise err(f'Control:{fn}:matrix', f'{what} is a matrix.', fn)
    return a


def _clean(p):
    """Coefficients that are round-off beside the largest (from a conversion) set to zero."""
    p = np.asarray(p)
    big = np.max(np.abs(p), initial=0)
    return np.where(np.abs(p) <= 1e-12 * big, 0, p) if big > 0 else p


def _trim(p):
    p = np.atleast_1d(np.asarray(p, complex if np.iscomplexobj(p) else float))
    nz = np.flatnonzero(np.abs(p) > 0)
    p = p[nz[0]:] if nz.size else np.zeros(1)
    if np.iscomplexobj(p) and np.max(np.abs(p.imag), initial=0) <= 1e-12 * max(np.max(np.abs(p.real), initial=0), 1e-300):
        p = p.real
    return p


def _real_poly(roots, k=1.0):
    p = np.atleast_1d(np.poly(roots)) * k if len(roots) else np.array([k], complex if np.iscomplexobj(k) else float)
    return _trim(np.real_if_close(p, tol=1e6))


def _padd(a, b):
    n = max(len(a), len(b))
    return np.pad(a, (n - len(a), 0)) + np.pad(b, (n - len(b), 0))


# ---- the model ------------------------------------------------------------------------------------------------------------------------

class LTI(Obj):
    """A linear time-invariant model: kind 'tf' (num, den: lists of lists of coefficient rows), 'zpk' (Z, P, K) or 'ss' (A, B, C,
    D); Ts 0 for continuous time, -1 unspecified, else the sample time; delays on the inputs, outputs and each I/O pair."""

    def __init__(self, kind, data, Ts=0.0, **kw):
        self.kind = kind
        self.data = data
        self.Ts = float(Ts)
        if kind == 'ss':
            A, B, C, D = data
            self.ny, self.nu = D.shape
        elif kind == 'tf':
            self.ny, self.nu = len(data[0]), (len(data[0][0]) if data[0] else 0)
        else:
            self.ny, self.nu = data[2].shape
        self.input_delay = np.asarray(kw.get('input_delay', np.zeros(self.nu)), float).reshape(-1)
        self.output_delay = np.asarray(kw.get('output_delay', np.zeros(self.ny)), float).reshape(-1)
        self.io_delay = np.asarray(kw.get('io_delay', np.zeros((self.ny, self.nu))), float).reshape(self.ny, self.nu)
        self.names = {'InputName': kw.get('InputName', [''] * self.nu), 'OutputName': kw.get('OutputName', [''] * self.ny),
                      'StateName': kw.get('StateName', None), 'Name': kw.get('Name', ''), 'Notes': kw.get('Notes', ''),
                      'InputUnit': [''] * self.nu, 'OutputUnit': [''] * self.ny}
        self.variable = kw.get('variable', 's' if self.Ts == 0 else 'z')
        self.pid = None

    @property
    def cls(self):
        return 'pid' if self.pid is not None else self.kind

    def value_copy(self):
        o = LTI(self.kind, _copy_data(self.kind, self.data), self.Ts, input_delay=self.input_delay.copy(), output_delay=self.output_delay.copy(),
                io_delay=self.io_delay.copy(), variable=self.variable)
        o.names = {k: (list(v) if isinstance(v, list) else v) for k, v in self.names.items()}
        o.pid = dict(self.pid) if self.pid else None
        return o

    @property
    def shape(self):
        return (self.ny, self.nu)

    def same_props(self, kind, data):
        o = LTI(kind, data, self.Ts, input_delay=self.input_delay.copy(), output_delay=self.output_delay.copy(), io_delay=self.io_delay.copy(),
                variable=self.variable)
        o.names = {k: (list(v) if isinstance(v, list) else v) for k, v in self.names.items()}
        if kind != 'ss':
            o.names['StateName'] = None
        return o

    # ---- forms ----
    def tf_data(self):
        if self.kind == 'tf':
            return self.data
        if self.kind == 'zpk':
            Z, P, K = self.data
            num_ = [[_real_poly(Z[i][j], K[i, j]) for j in range(self.nu)] for i in range(self.ny)]
            den = [[_real_poly(P[i][j]) for j in range(self.nu)] for i in range(self.ny)]
            return num_, den
        A, B, C, D = self.data
        from scipy.signal import ss2tf
        num_ = [[None] * self.nu for _ in range(self.ny)]
        den = [[None] * self.nu for _ in range(self.ny)]
        for j in range(self.nu):
            for i in range(self.ny):
                if A.shape[0] == 0:
                    num_[i][j], den[i][j] = np.array([D[i, j]]), np.array([1.0])
                    continue
                Am, Bm, Cm = _minimal_siso(A, B[:, j:j + 1], C[i:i + 1, :])
                if Am.shape[0] == 0:
                    num_[i][j], den[i][j] = np.array([D[i, j]]), np.array([1.0])
                    continue
                nn, dd = ss2tf(Am, Bm, Cm, D[i:i + 1, j:j + 1])
                num_[i][j], den[i][j] = _trim(_clean(np.real_if_close(nn[0]))), _trim(_clean(np.real_if_close(dd)))
        return num_, den

    def zpk_data(self):
        if self.kind == 'zpk':
            return self.data
        num_, den = self.tf_data()
        Z = [[None] * self.nu for _ in range(self.ny)]
        P = [[None] * self.nu for _ in range(self.ny)]
        K = np.zeros((self.ny, self.nu))
        for i in range(self.ny):
            for j in range(self.nu):
                n_, d_ = _trim(num_[i][j]), _trim(den[i][j])
                if np.all(n_ == 0):
                    Z[i][j], P[i][j], K[i, j] = np.zeros(0), np.zeros(0), 0.0
                    continue
                Z[i][j] = np.roots(n_) if n_.size > 1 else np.zeros(0)
                P[i][j] = np.roots(d_) if d_.size > 1 else np.zeros(0)
                K[i, j] = float(np.real(n_[0] / d_[0]))
        return Z, P, K

    def ss_data(self):
        if self.kind == 'ss':
            return self.data
        num_, den = self.tf_data()
        from scipy.signal import tf2ss
        blocks = []
        for i in range(self.ny):
            for j in range(self.nu):
                n_, d_ = _trim(num_[i][j]), _trim(den[i][j])
                if np.all(n_ == 0):
                    continue
                if n_.size > d_.size:
                    raise err('Control:ss:improper', 'An improper transfer function (numerator of higher degree) has no state-space form here.', 'ss')
                a, b, c, d = tf2ss(n_, d_)
                blocks.append((i, j, a, b, c, d))
        n = sum(b_[2].shape[0] for b_ in blocks)
        A = np.zeros((n, n))
        B = np.zeros((n, self.nu))
        C = np.zeros((self.ny, n))
        D = np.zeros((self.ny, self.nu))
        k = 0
        for i, j, a, b, c, d in blocks:
            m = a.shape[0]
            A[k:k + m, k:k + m] = a
            B[k:k + m, j] = b[:, 0]
            C[i, k:k + m] = c[0]
            D[i, j] += d[0, 0]
            k += m
        return A, B, C, D

    def to(self, kind):
        if kind == self.kind:
            return self
        data = self.tf_data() if kind == 'tf' else self.zpk_data() if kind == 'zpk' else self.ss_data()
        return self.same_props(kind, data)

    # ---- response at complex frequencies ----
    def resp(self, s):
        """H(s) for an array of s: (len(s), ny, nu), delays included."""
        s = np.asarray(s, complex).reshape(-1)
        H = np.zeros((s.size, self.ny, self.nu), complex)
        if self.kind == 'ss':
            A, B, C, D = self.data
            n = A.shape[0]
            I = np.eye(n)
            for k, sk in enumerate(s):
                H[k] = (C @ np.linalg.solve(sk * I - A, B) if n else 0) + D
        elif self.kind == 'zpk':
            Z, P, K = self.data
            for i in range(self.ny):
                for j in range(self.nu):
                    H[:, i, j] = K[i, j] * np.prod([s - z for z in Z[i][j]], axis=0) / np.prod([s - p for p in P[i][j]], axis=0) if K[i, j] else 0
        else:
            num_, den = self.data
            for i in range(self.ny):
                for j in range(self.nu):
                    H[:, i, j] = np.polyval(num_[i][j], s) / np.polyval(den[i][j], s)
        tau = self.total_delay()
        if np.any(tau):
            if self.Ts == 0:
                H *= np.exp(-s[:, None, None] * tau[None])
            else:
                H *= s[:, None, None] ** (-tau[None])
        return H

    def total_delay(self):
        return self.io_delay + self.input_delay[None, :] + self.output_delay[:, None]

    # ---- properties ----
    def getprop(self, name):
        k = name.lower()
        if self.pid is not None and k in ('kp', 'ki', 'kd', 'tf'):
            return float(self.pid[{'kp': 'Kp', 'ki': 'Ki', 'kd': 'Kd', 'tf': 'Tf'}[k]])
        if k in ('numerator', 'num', 'denominator', 'den'):
            num_, den = self.tf_data()
            first = k.startswith('num')
            return Cell.of_list([out(_padded(num_[i][j], den[i][j])[0 if first else 1].reshape(1, -1)) for j in range(self.nu) for i in range(self.ny)], (self.ny, self.nu))
        if k in ('z', 'p', 'k'):
            Z, P, K = self.zpk_data()
            if k == 'k':
                return out(K)
            src = Z if k == 'z' else P
            return Cell.of_list([out(np.asarray(src[i][j]).reshape(-1, 1)) for j in range(self.nu) for i in range(self.ny)], (self.ny, self.nu))
        if k in ('a', 'b', 'c', 'd'):
            return out(np.asarray(self.ss_data()['abcd'.index(k)], float))
        if k == 'e':
            return EMPTY()
        if k == 'ts':
            return float(self.Ts)
        if k == 'variable':
            return Char.of(self.variable)
        if k == 'inputdelay':
            return out(self.input_delay.reshape(-1, 1))
        if k == 'outputdelay':
            return out(self.output_delay.reshape(-1, 1))
        if k == 'iodelay':
            return out(self.io_delay)
        if k == 'timeunit':
            return Char.of('seconds')
        for key in ('InputName', 'OutputName', 'StateName', 'Name', 'Notes', 'InputUnit', 'OutputUnit'):
            if key.lower() == k:
                v = self.names[key]
                if key == 'StateName':
                    nst = self.ss_data()[0].shape[0] if self.kind == 'ss' else 0
                    v = v if v is not None else [''] * nst
                if isinstance(v, list):
                    return Cell.of_list([Char.of(x) for x in v], (len(v), 1))
                return Char.of(v)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class '{self.cls}'.")

    def setprop(self, name, value):
        k = name.lower()
        if self.pid is not None and k in ('kp', 'ki', 'kd', 'tf'):
            self.pid[{'kp': 'Kp', 'ki': 'Ki', 'kd': 'Kd', 'tf': 'Tf'}[k]] = float(num(value))
            fresh = _pid_lti(**self.pid, Ts=self.Ts)
            self.data, self.kind = fresh.data, fresh.kind
            return
        if k == 'ts':
            self.Ts = float(num(value))
            self.variable = 's' if self.Ts == 0 else ('z' if self.variable == 's' else self.variable)
            return
        if k == 'inputdelay':
            self.input_delay = np.broadcast_to(np.asarray(darr(value), float).reshape(-1), (self.nu,)).copy()
            return
        if k == 'outputdelay':
            self.output_delay = np.broadcast_to(np.asarray(darr(value), float).reshape(-1), (self.ny,)).copy()
            return
        if k == 'iodelay':
            self.io_delay = np.broadcast_to(np.asarray(darr(value), float).reshape(self.ny, self.nu) if numel(value) > 1 else float(num(value)), (self.ny, self.nu)).copy()
            return
        if k == 'variable':
            self.variable = py_str(value)
            return
        if k in ('a', 'b', 'c', 'd') and self.kind == 'ss':
            parts = list(self.data)
            parts['abcd'.index(k)] = np.asarray(darr(value), float)
            self.data = tuple(parts)
            return
        if k in ('numerator', 'denominator') and self.kind == 'tf':
            vals = [np.asarray(darr(x), float).reshape(-1) for x in (value.a.reshape(-1, order='F') if isinstance(value, Cell) else [value])]
            num_, den = self.data
            grid = num_ if k == 'numerator' else den
            for idx, v in enumerate(vals):
                i, j = idx % self.ny, idx // self.ny
                grid[i][j] = _trim(v)
            return
        for key in ('InputName', 'OutputName', 'StateName', 'Name', 'Notes', 'InputUnit', 'OutputUnit'):
            if key.lower() == k:
                if key in ('Name', 'Notes'):
                    self.names[key] = py_str(value)
                else:
                    vals = [py_str(value)] if isinstance(value, Char) else [str(x) for x in text_list(value)]
                    self.names[key] = vals
                return
        raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class '{self.cls}'.")

    def propnames(self):
        base = {'tf': ['Numerator', 'Denominator', 'Variable'], 'zpk': ['Z', 'P', 'K', 'Variable'], 'ss': ['A', 'B', 'C', 'D', 'StateName']}[self.kind]
        if self.pid is not None:
            base = ['Kp', 'Ki', 'Kd', 'Tf']
        return base + ['IODelay', 'InputDelay', 'OutputDelay', 'Ts', 'TimeUnit', 'InputName', 'OutputName', 'Name', 'Notes']

    def index(self, args):
        if len(args) != 2:
            raise MError('MATLAB:badsubscript', 'A model is indexed as sys(outputs, inputs).')
        rows = _sel(args[0], self.ny, self.names['OutputName'])
        cols = _sel(args[1], self.nu, self.names['InputName'])
        if self.kind == 'ss':
            A, B, C, D = self.data
            data = (A.copy(), B[:, cols], C[rows], D[np.ix_(rows, cols)])
        elif self.kind == 'tf':
            num_, den = self.data
            data = ([[num_[i][j] for j in cols] for i in rows], [[den[i][j] for j in cols] for i in rows])
        else:
            Z, P, K = self.data
            data = ([[Z[i][j] for j in cols] for i in rows], [[P[i][j] for j in cols] for i in rows], K[np.ix_(rows, cols)])
        o = LTI(self.kind, data, self.Ts, input_delay=self.input_delay[cols], output_delay=self.output_delay[rows],
                io_delay=self.io_delay[np.ix_(rows, cols)], variable=self.variable,
                InputName=[self.names['InputName'][j] for j in cols], OutputName=[self.names['OutputName'][i] for i in rows])
        return o

    def display_lines(self):
        return _display(self)


def _padded(n, d):
    """A numerator and denominator padded with leading zeros to one length, as the language keeps them."""
    n, d = np.atleast_1d(n), np.atleast_1d(d)
    m = max(n.size, d.size)
    return np.pad(n, (m - n.size, 0)), np.pad(d, (m - d.size, 0))


def _copy_data(kind, data):
    if kind == 'ss':
        return tuple(np.array(x) for x in data)
    if kind == 'tf':
        return ([[np.array(x) for x in row] for row in data[0]], [[np.array(x) for x in row] for row in data[1]])
    return ([[np.array(x) for x in row] for row in data[0]], [[np.array(x) for x in row] for row in data[1]], np.array(data[2]))


def _sel(v, n, names):
    if is_str(v) and py_str(v) == ':':
        return list(range(n))
    if isinstance(v, (Char, Str, Cell)) and names:
        items = [py_str(v)] if isinstance(v, Char) else [str(x) for x in text_list(v)]
        return [names.index(x) for x in items]
    a = np.asarray(darr(v))
    if a.dtype == bool:
        return list(np.flatnonzero(a.reshape(-1)))
    return [int(x) - 1 for x in a.reshape(-1)]


def _minimal_siso(A, B, C, tol=None):
    """The controllable and observable part of a single-input single-output realization (staircase by SVD)."""
    n = A.shape[0]
    if n == 0:
        return A, B, C
    scale = max(np.linalg.norm(A, 1), np.linalg.norm(B, 1), np.linalg.norm(C, 1), 1.0)
    tol = tol if tol is not None else n * 1e-10 * scale
    Kc = np.column_stack([np.linalg.matrix_power(A, k) @ B for k in range(n)])
    U, S, Vt = np.linalg.svd(Kc)
    r = int(np.sum(S > tol * max(S[0], 1e-300))) if S.size else 0
    if r == 0:
        return np.zeros((0, 0)), np.zeros((0, 1)), np.zeros((1, 0))
    Q = U[:, :r]
    A1, B1, C1 = Q.T @ A @ Q, Q.T @ B, C @ Q
    Ko = np.vstack([C1 @ np.linalg.matrix_power(A1, k) for k in range(r)])
    U2, S2, Vt2 = np.linalg.svd(Ko)
    r2 = int(np.sum(S2 > tol * max(S2[0], 1e-300))) if S2.size else 0
    if r2 == 0:
        return np.zeros((0, 0)), np.zeros((0, 1)), np.zeros((1, 0))
    W = Vt2[:r2].T
    return W.T @ A1 @ W, W.T @ B1, C1 @ W


# ---- display -------------------------------------------------------------------------------------------------------------------------

def _num_text(c):
    c = float(c) + 0.0
    if abs(c - round(c)) < 1e-10 * max(1, abs(c)):
        return f'{int(round(c))}'
    return f'{c:.4g}'


def _poly_text(p, var):
    p = np.real_if_close(_trim(p))
    n = p.size - 1
    terms = []
    for k, c in enumerate(p):
        if c == 0:
            continue
        power = n - k
        if np.iscomplexobj(c):
            mag = f'({c:.4g})'
            sign = '+'
        else:
            sign = '-' if c < 0 else '+'
            a = abs(c)
            mag = '' if (a == 1 and power > 0) else _num_text(a)
        v = '' if power == 0 else (var if power == 1 else f'{var}^{power}')
        body = f'{mag} {v}'.strip() if mag and v else (mag or v)
        terms.append((sign, body))
    if not terms:
        return '0'
    s = ('-' if terms[0][0] == '-' else '') + terms[0][1]
    for sign, body in terms[1:]:
        s += f' {sign} {body}'
    return s


def _factor_text(roots, var):
    roots = list(np.asarray(roots, complex))
    parts = []
    used = [False] * len(roots)
    for i, r in enumerate(roots):
        if used[i]:
            continue
        used[i] = True
        if abs(r.imag) > 1e-10 * max(1, abs(r)):
            for j in range(i + 1, len(roots)):
                if not used[j] and abs(roots[j] - r.conjugate()) < 1e-8 * max(1, abs(r)):
                    used[j] = True
                    break
            q = _poly_text(np.real(np.poly([r, r.conjugate()])), var)
            parts.append(f'({q})')
        else:
            a = r.real
            parts.append(var if a == 0 else f'({var}{"-" if a > 0 else "+"}{_num_text(abs(a))})')
    out_ = []
    for p in sorted(set(parts), key=parts.index):
        c = parts.count(p)
        out_.append(p if c == 1 else f'{p}^{c}')
    return ' '.join(out_) if out_ else '1'


def _fraction(top, bottom):
    if bottom.strip() == '1':
        return ['  ' + top]
    w = max(len(top), len(bottom))
    return ['  ' + top.center(w), '  ' + '-' * w, '  ' + bottom.center(w)]


def _time_text(sys):
    if sys.Ts == 0:
        return 'Continuous-time'
    if sys.Ts < 0:
        return 'Discrete-time (unspecified sample time)'
    return f'Sample time: {sys.Ts:g} seconds\nDiscrete-time'


def _display(sys):
    var = sys.variable
    lines = []
    multi = sys.ny > 1 or sys.nu > 1
    tau = sys.total_delay()
    if sys.pid is not None:
        g = sys.pid
        parts = []
        if g['Kp']:
            parts.append('Kp')
        if g['Ki']:
            parts.append('Ki * 1/s' if sys.Ts == 0 else 'Ki * Ts/(z-1)')
        if g['Kd']:
            parts.append('Kd * s' if not g['Tf'] else 'Kd * s/(Tf*s+1)')
        lines = ['', '             ' + ' + '.join(parts or ['0']), '', '  with ' + ', '.join(f'{k} = {g[k]:.4g}' for k in ('Kp', 'Ki', 'Kd', 'Tf') if g[k] or k == 'Kp'),
                 '', f"  {'Continuous' if sys.Ts == 0 else 'Discrete'}-time {'PID' if g['Kd'] else ('PI' if g['Ki'] else 'P')} controller in parallel form."]
        return lines
    if sys.kind in ('tf', 'zpk'):
        for i in range(sys.ny):
            for j in range(sys.nu):
                if multi:
                    lines.append(f'  From input {j + 1} to output {i + 1}:' if sys.nu > 1 else f'  {i + 1}:' if sys.ny > 1 else '')
                if sys.kind == 'tf':
                    n_, d_ = sys.data[0][i][j], sys.data[1][i][j]
                    top, bot = _poly_text(n_, var), _poly_text(d_, var)
                else:
                    Z, P, K = sys.data
                    k = K[i, j]
                    top = '0' if k == 0 else ((_num_text(k) + ' ' if k != 1 or not len(Z[i][j]) else '') + _factor_text(Z[i][j], var) if len(Z[i][j]) else _num_text(k))
                    top = top.replace(' 1', '') if top.endswith(' 1') and len(Z[i][j]) == 0 else top
                    bot = _factor_text(P[i][j], var)
                if tau[i, j]:
                    top = f'exp(-{tau[i, j]:g}*{var}) * ' + (f'({top})' if '+' in top or '-' in top[1:] else top) if sys.Ts == 0 else f'{var}^(-{int(tau[i, j])}) * ({top})'
                lines += [''] + _fraction(top, bot)
                lines.append('')
        kind = 'transfer function' if sys.kind == 'tf' else 'zero/pole/gain model'
        lines.append(f'{_time_text(sys)} {kind}.')
        return lines
    A, B, C, D = sys.data
    n = A.shape[0]
    snames = sys.names['StateName'] or [f'x{k + 1}' for k in range(n)]
    snames = [s or f'x{k + 1}' for k, s in enumerate(snames)]
    inames = [s or f'u{k + 1}' for k, s in enumerate(sys.names['InputName'])]
    onames = [s or f'y{k + 1}' for k, s in enumerate(sys.names['OutputName'])]

    def grid(name, M, rn, cn):
        out_ = [f'  {name} = ']
        if M.size == 0:
            return out_ + ['    (empty)', '']
        cells = [[_num_text(v) if abs(v) >= 1e-12 or v == 0 else f'{v:.4g}' for v in row] for row in M]
        w = max(max(len(c) for c in cn), max(len(c) for row in cells for c in row)) + 2
        rw = max(len(r) for r in rn) + 4
        out_.append(' ' * rw + ''.join(c.rjust(w) for c in cn))
        for r, row in zip(rn, cells):
            out_.append(('   ' + r).ljust(rw) + ''.join(c.rjust(w) for c in row))
        return out_ + ['']
    lines += grid('A', A, snames, snames) + grid('B', B, snames, inames) + grid('C', C, onames, snames) + grid('D', D, onames, inames)
    if np.any(tau):
        lines.append('  Delays: ' + ', '.join(f'{v:g}' for v in tau.reshape(-1)))
    lines.append(f'{_time_text(sys)} state-space model.')
    return lines


# ---- making models ---------------------------------------------------------------------------------------------------------------------

def _props_from(args, sys):
    for i in range(0, len(args) - 1, 2):
        sys.setprop(py_str(args[i]), args[i + 1])
    return sys


def _cell_polys(v):
    if isinstance(v, Cell):
        return [[_trim(np.asarray(darr(v.a[i, j]), float).reshape(-1)) for j in range(v.a.shape[1])] for i in range(v.a.shape[0])]
    return [[_trim(np.asarray(darr(v), float).reshape(-1))]]


def _ts_and_props(rest):
    Ts = 0.0
    if rest and not is_str(rest[0]):
        Ts = float(num(rest.pop(0)))
    return Ts, rest


def _gain(D, Ts=0.0, kind='tf'):
    D = np.atleast_2d(np.asarray(D, float))
    if kind == 'ss':
        return LTI('ss', (np.zeros((0, 0)), np.zeros((0, D.shape[1])), np.zeros((D.shape[0], 0)), D), Ts)
    if kind == 'zpk':
        return LTI('zpk', ([[np.zeros(0)] * D.shape[1] for _ in range(D.shape[0])], [[np.zeros(0)] * D.shape[1] for _ in range(D.shape[0])], D.copy()), Ts)
    return LTI('tf', ([[np.array([D[i, j]]) for j in range(D.shape[1])] for i in range(D.shape[0])],
                      [[np.array([1.0]) for _ in range(D.shape[1])] for _ in range(D.shape[0])]), Ts)


@bi('tf')
def tf(nargout, *args):
    """sys = tf(num, den), tf(num, den, Ts), tf('s'), tf('z', Ts), tf(M), tf(sys), tf(..., Name, Value): a transfer function: the numerator and denominator coefficients in descending powers (a cell of them for many inputs and outputs)."""
    if not args:
        return _gain(np.zeros((0, 0)))
    a = list(args)
    if is_str(a[0]) and py_str(a[0]) in ('s', 'z', 'p', 'q', 'z^-1'):
        var = py_str(a.pop(0))
        Ts, a = _ts_and_props(a)
        if var in ('z', 'q', 'z^-1') and Ts == 0:
            Ts = -1.0
        sys = LTI('tf', ([[np.array([1.0, 0.0])]], [[np.array([1.0])]]), Ts, variable=var)
        return _props_from(a, sys)
    if isinstance(a[0], LTI):
        sys = a.pop(0).to('tf')
        return _props_from(a, sys.value_copy() if sys is args[0] else sys)
    if len(a) == 1 or (len(a) > 1 and is_str(a[1])):
        G = np.atleast_2d(np.asarray(darr(a.pop(0)), float))
        return _props_from(a, _gain(G))
    num_, den = _cell_polys(a.pop(0)), _cell_polys(a.pop(0))
    if len(num_) != len(den) or len(num_[0]) != len(den[0]):
        if len(den) == 1 and len(den[0]) == 1:
            den = [[den[0][0] for _ in row] for row in num_]
        else:
            raise err('Control:tf:size', 'The numerators and denominators come in cells of the same size.', 'tf')
    for row in den:
        for d_ in row:
            if np.all(d_ == 0):
                raise err('Control:tf:zeroDen', 'A denominator is zero.', 'tf')
    Ts, a = _ts_and_props(a)
    sys = LTI('tf', (num_, den), Ts)
    return _props_from(a, sys)


@bi('zpk')
def zpk(nargout, *args):
    """sys = zpk(z, p, k), zpk(z, p, k, Ts), zpk('s'), zpk(sys), zpk(..., Name, Value): a model as its zeros, poles and gain (cells of them for many inputs and outputs)."""
    a = list(args)
    if a and is_str(a[0]) and py_str(a[0]) in ('s', 'z'):
        var = py_str(a.pop(0))
        Ts, a = _ts_and_props(a)
        if var == 'z' and Ts == 0:
            Ts = -1.0
        return _props_from(a, LTI('zpk', ([[np.zeros(1)]], [[np.zeros(0)]], np.ones((1, 1))), Ts, variable=var))
    if a and isinstance(a[0], LTI):
        sys = a.pop(0).to('zpk')
        return _props_from(a, sys)
    if len(a) == 1 or (len(a) > 1 and is_str(a[1])):
        return _props_from(a[1:], _gain(np.asarray(darr(a[0]), float), kind='zpk'))
    nargchk(args, 3, 30, 'zpk')

    def roots_of(v):
        if isinstance(v, Cell):
            return [[np.asarray(darr(v.a[i, j]), complex).reshape(-1) for j in range(v.a.shape[1])] for i in range(v.a.shape[0])]
        return [[np.asarray(darr(v), complex).reshape(-1)]]
    Z, P = roots_of(a.pop(0)), roots_of(a.pop(0))
    K = np.atleast_2d(np.asarray(darr(a.pop(0)), float))
    Z = [[np.real_if_close(z) for z in row] for row in Z]
    P = [[np.real_if_close(p) for p in row] for row in P]
    Ts, a = _ts_and_props(a)
    return _props_from(a, LTI('zpk', (Z, P, K), Ts))


@bi('ss')
def ss(nargout, *args):
    """sys = ss(A, B, C, D), ss(A, B, C, D, Ts), ss(D), ss(sys), ss(..., Name, Value): a state-space model x' = Ax + Bu, y = Cx + Du (x(k+1) = ... in discrete time)."""
    a = list(args)
    if a and isinstance(a[0], LTI):
        sys = a.pop(0)
        if a and is_str(a[0]) and py_str(a[0]).lower() == 'minimal':
            a.pop(0)
            return _props_from(a, _minreal(sys.to('ss')))
        return _props_from(a, sys.to('ss'))
    if len(a) == 1 or (len(a) > 1 and is_str(a[1])):
        return _props_from(a[1:], _gain(np.asarray(darr(a[0]), float), kind='ss'))
    nargchk(args, 4, 30, 'ss')
    A, B, C, D = (np.atleast_2d(np.asarray(darr(x), float)) for x in a[:4])
    a = a[4:]
    n = A.shape[0]
    if A.size == 0:
        A = np.zeros((0, 0))
        n = 0
    if B.size == 0:
        B = np.zeros((n, D.shape[1] if D.size else 0))
    if C.size == 0:
        C = np.zeros((D.shape[0] if D.size else 0, n))
    if D.size == 0 or (D.shape == (1, 1) and D[0, 0] == 0 and (C.shape[0] != 1 or B.shape[1] != 1)):
        D = np.zeros((C.shape[0], B.shape[1])) if D.size <= 1 and float(D.reshape(-1)[0] if D.size else 0) == 0 else D
    if A.shape != (n, n) or B.shape[0] != n or C.shape[1] != n or D.shape != (C.shape[0], B.shape[1]):
        raise err('Control:ss:size', 'A is n-by-n, B n-by-m, C p-by-n and D p-by-m.', 'ss')
    Ts, a = _ts_and_props(a)
    return _props_from(a, LTI('ss', (A, B, C, D), Ts))


def _pid_lti(Kp=0.0, Ki=0.0, Kd=0.0, Tf=0.0, Ts=0.0):
    if Ts == 0:
        s = LTI('tf', ([[np.array([1.0, 0.0])]], [[np.array([1.0])]]), 0.0)
        parts = [_gain([[Kp]])]
        if Ki:
            parts.append(_div(_gain([[Ki]]), s))
        if Kd:
            parts.append(_div(_mul(_gain([[Kd]]), s), _add(_mul(_gain([[Tf]]), s), _gain([[1.0]]))) if Tf else _mul(_gain([[Kd]]), s))
    else:
        z = LTI('tf', ([[np.array([1.0, 0.0])]], [[np.array([1.0])]]), Ts)
        parts = [_gain([[Kp]], Ts)]
        if Ki:
            parts.append(_div(_gain([[Ki * Ts]], Ts), _add(z, _gain([[-1.0]], Ts))))
        if Kd:
            parts.append(_div(_mul(_gain([[Kd / Ts]], Ts), _add(z, _gain([[-1.0]], Ts))), z) if not Tf else
                         _div(_gain([[Kd]], Ts), _add(_gain([[Tf]], Ts), _div(_gain([[Ts]], Ts), _add(z, _gain([[-1.0]], Ts))))))
    sys = parts[0]
    for p in parts[1:]:
        sys = _add(sys, p)
    sys = _simplify_tf(sys)
    n, d = sys.data
    lead = d[0][0][0]
    return LTI('tf', ([[n[0][0] / lead]], [[d[0][0] / lead]]), Ts)


@bi('pid')
def pid(nargout, *args):
    """C = pid(Kp, Ki, Kd, Tf), pid(Kp, Ki, Kd, Tf, Ts): a PID controller in parallel form, Kp + Ki/s + Kd*s/(Tf*s + 1) (Ki*Ts/(z - 1) and so on in discrete time)."""
    g = [float(num(a)) for a in args[:4]] + [0.0] * (4 - min(len(args), 4))
    Ts = float(num(args[4])) if len(args) > 4 else 0.0
    sys = _pid_lti(*g, Ts=Ts)
    sys.pid = {'Kp': g[0], 'Ki': g[1], 'Kd': g[2], 'Tf': g[3]}
    return sys


# ---- the algebra ---------------------------------------------------------------------------------------------------------------------------

def _as_lti(x, like):
    if isinstance(x, LTI):
        return x
    D = np.atleast_2d(np.asarray(darr(x), float))
    if not isinstance(like, LTI):                   # two numbers: static gains in continuous time
        return _gain(D, 0.0, 'tf')
    return _gain(D, like.Ts, 'tf' if like.kind != 'ss' else 'ss')


def _kind_of(*sys):
    kinds = {s.kind for s in sys}
    return 'ss' if 'ss' in kinds else 'zpk' if 'zpk' in kinds else 'tf'


def _check_ts(a, b):
    if a.Ts != b.Ts and a.Ts != -1 and b.Ts != -1 and not (a.nu == a.ny == 0 or b.nu == b.ny == 0):
        if a.ss_data()[0].shape[0] and b.ss_data()[0].shape[0]:
            raise err('Control:combination', 'The models have different sample times.', 'combination')
    return a.Ts if a.Ts != -1 or b.Ts == 0 else b.Ts


def _tf_add(n1, d1, n2, d2):
    if d1.size == d2.size and np.allclose(d1, d2):
        return _trim(_padd(n1, n2)), d1
    return _trim(_padd(np.polymul(n1, d2), np.polymul(n2, d1))), _trim(np.polymul(d1, d2))


def _add(a, b, sign=1.0):
    a, b = (_as_lti(a, b if isinstance(b, LTI) else a), _as_lti(b, a if isinstance(a, LTI) else b))
    Ts = _check_ts(a, b)
    if a.shape != b.shape:
        if a.shape == (1, 1):
            a = _replicate(a, b.shape)
        elif b.shape == (1, 1):
            b = _replicate(b, a.shape)
        else:
            raise err('Control:plus', 'The models have different numbers of inputs and outputs.', 'plus')
    kind = _kind_of(a, b)
    if kind == 'ss' or np.any(a.total_delay() != b.total_delay()):
        if np.any(a.total_delay() != b.total_delay()):
            raise err('Control:delay', 'Adding models with different delays needs pade first.', 'plus')
        A1, B1, C1, D1 = a.ss_data()
        A2, B2, C2, D2 = b.ss_data()
        from scipy.linalg import block_diag
        sys = LTI('ss', (block_diag(A1, A2), np.vstack([B1, B2]), np.hstack([C1, sign * C2]), D1 + sign * D2), Ts)
        sys.io_delay = a.io_delay.copy()
        sys.input_delay, sys.output_delay = a.input_delay.copy(), a.output_delay.copy()
        return sys.to(kind) if kind != 'ss' else sys
    n1, d1 = a.tf_data()
    n2, d2 = b.tf_data()
    num_ = [[None] * a.nu for _ in range(a.ny)]
    den = [[None] * a.nu for _ in range(a.ny)]
    for i in range(a.ny):
        for j in range(a.nu):
            num_[i][j], den[i][j] = _tf_add(n1[i][j], d1[i][j], sign * n2[i][j], d2[i][j])
    sys = a.same_props('tf', (num_, den))
    sys.Ts = Ts
    return sys.to(kind) if kind == 'zpk' else sys


def _replicate(sys, shape):
    ny, nu = shape
    n, d = sys.tf_data()
    o = LTI('tf', ([[n[0][0]] * nu for _ in range(ny)], [[d[0][0]] * nu for _ in range(ny)]), sys.Ts, variable=sys.variable,
            io_delay=np.full((ny, nu), sys.total_delay()[0, 0]))
    return o.to(sys.kind) if sys.kind != 'tf' else o


def _mul(a, b):
    """a * b: a after b (b's outputs feed a's inputs)."""
    a, b = (_as_lti(a, b if isinstance(b, LTI) else a), _as_lti(b, a if isinstance(a, LTI) else b))
    Ts = _check_ts(a, b)
    if a.shape == (1, 1) and b.shape != (1, 1):
        a = _diag_rep(a, b.ny)
    elif b.shape == (1, 1) and a.shape != (1, 1):
        b = _diag_rep(b, a.nu)
    if a.nu != b.ny:
        raise err('Control:mtimes', 'The inner dimensions do not agree: a model with as many inputs as the other has outputs.', 'mtimes')
    kind = _kind_of(a, b)
    delays = np.any(a.total_delay()) or np.any(b.total_delay())
    if kind == 'ss' or a.ny > 1 or a.nu > 1 or b.nu > 1:
        A1, B1, C1, D1 = a.ss_data()
        A2, B2, C2, D2 = b.ss_data()
        n1, n2 = A1.shape[0], A2.shape[0]
        A = np.block([[A1, B1 @ C2], [np.zeros((n2, n1)), A2]])
        B = np.vstack([B1 @ D2, B2])
        C = np.hstack([C1, D1 @ C2])
        sys = LTI('ss', (A, B, C, D1 @ D2), Ts)
        if delays:
            if a.nu == 1 and b.ny == 1:
                sys.io_delay = (a.total_delay()[:, :1] + b.total_delay()[:1, :]) if a.shape == (1, 1) or b.shape == (1, 1) else np.zeros((a.ny, b.nu))
            else:
                raise err('Control:delay', 'Connecting models with delays between many channels needs pade first.', 'mtimes')
        return sys.to(kind) if kind != 'ss' else sys
    if kind == 'zpk':
        Z1, P1, K1 = a.zpk_data()
        Z2, P2, K2 = b.zpk_data()
        sys = LTI('zpk', ([[np.concatenate([Z1[0][0], Z2[0][0]])]], [[np.concatenate([P1[0][0], P2[0][0]])]], K1 * K2), Ts, variable=a.variable)
    else:
        n1, d1 = a.tf_data()
        n2, d2 = b.tf_data()
        sys = LTI('tf', ([[_trim(np.polymul(n1[0][0], n2[0][0]))]], [[_trim(np.polymul(d1[0][0], d2[0][0]))]]), Ts, variable=a.variable)
    sys.io_delay = a.total_delay() + b.total_delay()
    return sys


def _diag_rep(sys, n):
    """A scalar model times the identity of size n."""
    if n == 1:
        return sys
    A, B, C, D = sys.to('ss').data
    from scipy.linalg import block_diag
    S = LTI('ss', (block_diag(*[A] * n), block_diag(*[B] * n), block_diag(*[C] * n), block_diag(*[D] * n)), sys.Ts)
    return S.to(sys.kind) if sys.kind != 'ss' else S


def _inv(sys):
    if sys.ny != sys.nu:
        raise err('Control:inv', 'Only a square model has an inverse.', 'inv')
    if np.any(sys.total_delay()):
        raise err('Control:inv', 'A model with delays has no causal inverse.', 'inv')
    if sys.kind in ('tf', 'zpk') and sys.shape == (1, 1):
        if sys.kind == 'zpk':
            Z, P, K = sys.data
            if K[0, 0] == 0:
                raise err('Control:inv', 'The model is zero.', 'inv')
            return sys.same_props('zpk', ([[P[0][0].copy()]], [[Z[0][0].copy()]], 1 / K))
        n, d = sys.data
        return sys.same_props('tf', ([[d[0][0].copy()]], [[n[0][0].copy()]]))
    A, B, C, D = sys.ss_data()
    Di = np.linalg.inv(D)
    return sys.same_props('ss', (A - B @ Di @ C, B @ Di, -Di @ C, Di)).to(sys.kind) if sys.kind != 'ss' else sys.same_props('ss', (A - B @ Di @ C, B @ Di, -Di @ C, Di))


def _div(a, b):
    b = _as_lti(b, a if isinstance(a, LTI) else b)
    a = _as_lti(a, b)
    return _mul(a, _inv(b))


def _simplify_tf(sys):
    """Common roots of a SISO transfer function's numerator and denominator cancelled (to round-off)."""
    if sys.kind != 'tf' or sys.shape != (1, 1):
        return sys
    n, d = sys.data[0][0][0], sys.data[1][0][0]
    if np.all(np.asarray(n) == 0):
        return sys.same_props('tf', ([[np.zeros(1)]], [[np.ones(1)]]))
    z = list(np.roots(n)) if n.size > 1 else []
    p = list(np.roots(d)) if d.size > 1 else []
    changed = False
    for r in list(z):
        for q in p:
            if abs(r - q) <= 1e-8 * max(1, abs(r)):
                z.remove(r)
                p.remove(q)
                changed = True
                break
    if not changed:
        return sys
    k = n[0] / d[0]
    return sys.same_props('tf', ([[_real_poly(z, k)]], [[_real_poly(p)]]))


def _power(sys, k):
    k = int(round(float(num(k))))
    if sys.shape != (1, 1) and k != 1:
        if sys.ny != sys.nu:
            raise err('Control:mpower', 'Only a square model has powers.', 'mpower')
    if k == 0:
        return _gain(np.eye(sys.ny), sys.Ts, sys.kind)
    base = sys if k > 0 else _inv(sys)
    res = base
    for _ in range(abs(k) - 1):
        res = _mul(res, base)
    return res


def _concat(op, *vals):
    items = [v for v in vals if not (isinstance(v, np.ndarray) and v.size == 0)]
    first = next(v for v in items if isinstance(v, LTI))
    items = [_as_lti(v, first) for v in items]
    kind = _kind_of(*items)
    Ts = first.Ts
    from scipy.linalg import block_diag
    if kind == 'ss' or any(np.any(s.total_delay()) for s in items):
        parts = [s.ss_data() for s in items]
        A = block_diag(*[p[0] for p in parts])
        if op == 'hcat':
            if len({s.ny for s in items}) != 1:
                raise err('Control:horzcat', 'Models side by side have as many outputs.', 'horzcat')
            B = block_diag(*[p[1] for p in parts])
            C = np.hstack([p[2] for p in parts])
            D = np.hstack([p[3] for p in parts])
        else:
            if len({s.nu for s in items}) != 1:
                raise err('Control:vertcat', 'Models one above another have as many inputs.', 'vertcat')
            B = np.vstack([p[1] for p in parts])
            C = block_diag(*[p[2] for p in parts])
            D = np.vstack([p[3] for p in parts])
        sys = LTI('ss', (A, B, C, D), Ts)
        sys.io_delay = np.hstack([s.total_delay() for s in items]) if op == 'hcat' else np.vstack([s.total_delay() for s in items])
        return sys.to(kind) if kind != 'ss' else sys
    tfs = [s.tf_data() for s in items]
    if op == 'hcat':
        if len({s.ny for s in items}) != 1:
            raise err('Control:horzcat', 'Models side by side have as many outputs.', 'horzcat')
        num_ = [[x for t in tfs for x in t[0][i]] for i in range(items[0].ny)]
        den = [[x for t in tfs for x in t[1][i]] for i in range(items[0].ny)]
    else:
        if len({s.nu for s in items}) != 1:
            raise err('Control:vertcat', 'Models one above another have as many inputs.', 'vertcat')
        num_ = [row for t in tfs for row in t[0]]
        den = [row for t in tfs for row in t[1]]
    sys = LTI('tf', (num_, den), Ts, variable=first.variable)
    return sys.to(kind) if kind == 'zpk' else sys


def _ops(op, *xs):
    if op == 'plus':
        return _add(*xs)
    if op == 'minus':
        return _add(xs[0], xs[1], -1.0)
    if op in ('mtimes', 'times'):
        return _mul(*xs)
    if op in ('mrdivide', 'rdivide'):
        return _div(*xs)
    if op in ('mldivide', 'ldivide'):
        return _mul(_inv(_as_lti(xs[0], xs[1] if isinstance(xs[1], LTI) else xs[0])), xs[1])
    if op in ('mpower', 'power'):
        if not isinstance(xs[0], LTI):
            raise err('Control:mpower', 'A model is raised to a whole power, not used as one.', 'mpower')
        return _power(xs[0], xs[1])
    if op == 'uminus':
        return _mul(_gain([[-1.0]], xs[0].Ts, xs[0].kind), xs[0]) if xs[0].shape == (1, 1) else _add(_gain(np.zeros(xs[0].shape), xs[0].Ts), xs[0], -1.0)
    if op == 'uplus':
        return xs[0]
    if op in ('transpose', 'ctranspose'):
        s = xs[0]
        if s.kind == 'ss':
            A, B, C, D = s.data
            return s.same_props('ss', (A.T, C.T, B.T, D.T)) if op == 'transpose' else s.same_props('ss', (-A.T, -C.T, B.T, D.T))
        n, d = s.tf_data()
        t = LTI('tf', ([[n[i][j] for i in range(s.ny)] for j in range(s.nu)], [[d[i][j] for i in range(s.ny)] for j in range(s.nu)]), s.Ts, variable=s.variable)
        return t.to(s.kind) if s.kind != 'tf' else t
    if op in ('hcat', 'vcat'):
        return _concat(op, *xs)
    if op in ('eq', 'ne'):
        a, b = xs
        same = isinstance(a, LTI) and isinstance(b, LTI) and a.shape == b.shape and np.allclose(a.resp(np.array([0.37j, 1.9j, 7.1])), b.resp(np.array([0.37j, 1.9j, 7.1])))
        return same if op == 'eq' else not same
    raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for models.")


def _register_ops():
    from ..ops import OBJ_OPS
    OBJ_OPS[LTI] = _ops


_register_ops()


def _sys(v, fn):
    if not isinstance(v, LTI):
        raise err(f'Control:{fn}:model', f'{fn} takes a model (tf, zpk, ss).', fn)
    return v


def _series_lti(nargout, a, b, *rest):
    return _mul(b, a)


@bi('parallel')
def parallel(nargout, *args):
    """sys = parallel(sys1, sys2): the two models' outputs added, their inputs shared (sys1 + sys2)."""
    nargchk(args, 2, 6, 'parallel')
    return _add(args[0], args[1])


@bi('feedback')
def feedback(nargout, *args):
    """sys = feedback(sys1, sys2), feedback(sys1, sys2, sign): the closed loop of sys1 in the forward path and sys2 in the feedback path (negative feedback unless sign is +1)."""
    nargchk(args, 2, 5, 'feedback')
    G = args[0]
    H = args[1]
    sign = float(num(args[2])) if len(args) > 2 and not is_str(args[2]) else -1.0
    G = _as_lti(G, H if isinstance(H, LTI) else G)
    H = _as_lti(H, G)
    if H.shape == (1, 1) and G.shape != (1, 1) and G.ny == G.nu:
        H = _diag_rep(H, G.ny)
    if G.nu != H.ny or H.nu != G.ny:
        raise err('Control:feedback', 'The inner dimensions do not agree: the feedback path takes the outputs and gives the inputs of the forward path.', 'feedback')
    kind = _kind_of(G, H)
    if G.shape == (1, 1) and H.shape == (1, 1) and kind != 'ss' and not np.any(G.total_delay()) and not np.any(H.total_delay()):
        if kind == 'zpk':
            return feedback(1, G.to('tf'), H.to('tf'), sign).to('zpk')
        nG, dG = G.tf_data()
        nH, dH = H.tf_data()
        num_ = np.polymul(nG[0][0], dH[0][0])
        den = _padd(np.polymul(dG[0][0], dH[0][0]), -sign * np.polymul(nG[0][0], nH[0][0]))
        return _simplify_tf(LTI('tf', ([[_trim(num_)]], [[_trim(den)]]), G.Ts if G.Ts else H.Ts, variable=G.variable))
    if np.any(G.total_delay()) or np.any(H.total_delay()):
        raise err('Control:feedback', 'Closing a loop around a delay needs pade first.', 'feedback')
    A1, B1, C1, D1 = G.ss_data()
    A2, B2, C2, D2 = H.ss_data()
    E = np.eye(D1.shape[0]) - sign * D1 @ D2
    Ei = np.linalg.inv(E)
    F = np.eye(D2.shape[0]) - sign * D2 @ D1
    Fi = np.linalg.inv(F)
    A = np.block([[A1 + sign * B1 @ Fi @ D2 @ C1, sign * B1 @ Fi @ C2], [B2 @ Ei @ C1, A2 + sign * B2 @ Ei @ D1 @ C2]])
    B = np.vstack([B1 @ Fi, B2 @ Ei @ D1])
    C = np.hstack([Ei @ C1, sign * Ei @ D1 @ C2])
    D = Ei @ D1
    sys = LTI('ss', (A, B, C, D), G.Ts)
    return sys.to(kind) if kind != 'ss' else sys


def _inv_lti(nargout, sys, *rest):
    return _inv(sys)


def _exp_lti(nargout, sys, *rest):
    """exp(-tau*s): a pure delay, from s = tf('s')."""
    if sys.kind == 'tf' and sys.shape == (1, 1):
        n, d = sys.data[0][0][0], sys.data[1][0][0]
        if d.size == 1 and n.size == 2 and n[1] == 0 and n[0] / d[0] <= 0 and sys.Ts == 0:
            tau = -n[0] / d[0]
            o = LTI('tf', ([[np.array([1.0])]], [[np.array([1.0])]]), 0.0)
            o.io_delay = np.array([[tau]])
            return o
    raise err('Control:exp', 'exp of a model takes a delay: exp(-tau*s), s = tf(\'s\').', 'exp')


# ---- data out ------------------------------------------------------------------------------------------------------------------------

@bi('tfdata', nout=3)
def tfdata(nargout, *args):
    """[num, den, Ts] = tfdata(sys), tfdata(sys, 'v'): the numerators and denominators (cells, or rows for one input and output with 'v')."""
    nargchk(args, 1, 2, 'tfdata')
    s = _sys(args[0], 'tfdata')
    n, d = s.tf_data()
    if len(args) > 1:
        pn, pd = _padded(n[0][0], d[0][0])
        res = (out(pn.reshape(1, -1)), out(pd.reshape(1, -1)), float(s.Ts))
    else:
        res = (s.getprop('Numerator'), s.getprop('Denominator'), float(s.Ts))
    return res[:nargout] if nargout > 1 else res[0]


@bi('zpkdata', nout=4)
def zpkdata(nargout, *args):
    """[z, p, k, Ts] = zpkdata(sys), zpkdata(sys, 'v'): the zeros, poles and gains."""
    nargchk(args, 1, 2, 'zpkdata')
    s = _sys(args[0], 'zpkdata')
    Z, P, K = s.zpk_data()
    if len(args) > 1:
        res = (out(np.asarray(Z[0][0]).reshape(-1, 1)), out(np.asarray(P[0][0]).reshape(-1, 1)), float(K[0, 0]), float(s.Ts))
    else:
        res = (s.getprop('Z'), s.getprop('P'), out(K), float(s.Ts))
    return res[:nargout] if nargout > 1 else res[0]


@bi('ssdata', nout=5)
def ssdata(nargout, *args):
    """[A, B, C, D, Ts] = ssdata(sys): the state-space matrices."""
    nargchk(args, 1, 1, 'ssdata')
    s = _sys(args[0], 'ssdata')
    A, B, C, D = s.ss_data()
    res = (out(A), out(B), out(C), out(D), float(s.Ts))
    return res[:nargout] if nargout > 1 else res[0]


@bi('ss2tf', nout=2)
def ss2tf_(nargout, *args):
    """[b, a] = ss2tf(A, B, C, D), ss2tf(A, B, C, D, iu): the transfer function of a state-space model from input iu (1)."""
    nargchk(args, 4, 5, 'ss2tf')
    from scipy.signal import ss2tf
    A, B, C, D = (np.atleast_2d(np.asarray(darr(x), float)) for x in args[:4])
    iu = int(num(args[4])) - 1 if len(args) > 4 else 0
    b, a = ss2tf(A, B, C, D, iu)
    return (out(np.real_if_close(b)), out(np.real_if_close(a).reshape(1, -1))) if nargout > 1 else out(np.real_if_close(b))


@bi('tf2ss', nout=4)
def tf2ss_(nargout, *args):
    """[A, B, C, D] = tf2ss(b, a): a state-space realization (controller canonical form) of a transfer function."""
    nargchk(args, 2, 2, 'tf2ss')
    from scipy.signal import tf2ss
    A, B, C, D = tf2ss(np.asarray(darr(args[0]), float), np.asarray(darr(args[1]), float).reshape(-1))
    res = (out(A), out(B), out(C), out(D))
    return res[:nargout] if nargout > 1 else res[0]


# ---- poles, zeros, gains ---------------------------------------------------------------------------------------------------------------------

def _poles(s):
    if s.kind in ('tf', 'zpk') and s.shape == (1, 1):
        Z, P, K = s.zpk_data()
        return np.asarray(P[0][0], complex)
    A = _minreal(s.to('ss')).data[0] if s.kind != 'ss' else s.data[0]
    return np.linalg.eigvals(A) if A.size else np.zeros(0)


@bi('pole')
def pole(nargout, *args):
    """p = pole(sys): the poles (the eigenvalues of A; for a transfer function the roots of its denominator)."""
    nargchk(args, 1, 1, 'pole')
    p = _poles(_sys(args[0], 'pole'))
    return out(np.real_if_close(p).reshape(-1, 1))


def _tzero(s):
    A, B, C, D = s.ss_data()
    n = A.shape[0]
    if n == 0:
        return np.zeros(0)
    from scipy.linalg import eigvals
    M = np.block([[A, B], [C, D]])
    N = np.block([[np.eye(n), np.zeros_like(B)], [np.zeros_like(C), np.zeros_like(D)]])
    if M.shape[0] != M.shape[1]:
        # non-square: zeros where the system matrix loses rank, by its square compressions
        return np.zeros(0)
    ev = eigvals(M, N)
    return ev[np.isfinite(ev) & (np.abs(ev) < 1e12)]


@bi('zero', nout=2)
def zero(nargout, *args):
    """[z, gain] = zero(sys): the zeros (transmission zeros of a model with many inputs and outputs), and the gain of a single-input single-output model."""
    nargchk(args, 1, 1, 'zero')
    s = _sys(args[0], 'zero')
    if s.shape == (1, 1):
        Z, P, K = s.zpk_data()
        z = np.asarray(Z[0][0], complex)
        res = (out(np.real_if_close(z).reshape(-1, 1)), float(K[0, 0]))
    else:
        res = (out(np.real_if_close(_tzero(s)).reshape(-1, 1)), EMPTY())
    return res if nargout > 1 else res[0]


@bi('tzero')
def tzero(nargout, *args):
    """z = tzero(sys): the transmission zeros: where the system matrix [A - sI, B; C, D] loses rank."""
    nargchk(args, 1, 1, 'tzero')
    return out(np.real_if_close(_tzero(_sys(args[0], 'tzero'))).reshape(-1, 1))


@bi('dcgain')
def dcgain(nargout, *args):
    """k = dcgain(sys): the steady-state gain, H(0) (H(1) in discrete time); Inf at a pole there."""
    nargchk(args, 1, 1, 'dcgain')
    s = _sys(args[0], 'dcgain')
    with np.errstate(divide='ignore', invalid='ignore'):
        H = s.resp(np.array([0.0 if s.Ts == 0 else 1.0]))[0] if not _pole_at(s) else np.full(s.shape, np.inf)
    return out(np.real_if_close(H))


def _pole_at(s):
    pt = 0.0 if s.Ts == 0 else 1.0
    p = _poles(s)
    return bool(np.any(np.abs(p - pt) < 1e-10))


@bi('evalfr')
def evalfr(nargout, *args):
    """frsp = evalfr(sys, x): the model's response at the complex frequency x."""
    nargchk(args, 2, 2, 'evalfr')
    s = _sys(args[0], 'evalfr')
    H = s.resp(np.asarray(darr(args[1]), complex).reshape(-1)[:1])[0]
    return out(np.real_if_close(H))


def _freq_grid(syss, n=400):
    pts = []
    for s in syss:
        zeros_ = _tzero(s) if s.shape != (1, 1) else np.asarray(s.zpk_data()[0][0][0], complex)
        for v in list(_poles(s)) + list(zeros_):
            v = complex(v)
            if s.Ts > 0:
                if abs(v) > 0:
                    v = np.log(v) / s.Ts
                else:
                    continue
            if abs(v) > 1e-9:
                pts.append(abs(v))
    lo = 10 ** np.floor(np.log10(min(pts) / 10)) if pts else 0.01
    hi = 10 ** np.ceil(np.log10(max(pts) * 10)) if pts else 100.0
    ts = [s.Ts for s in syss if s.Ts > 0]
    if ts:
        hi = min(hi, math.pi / min(ts))
        lo = min(lo, hi / 1e3)
    return np.logspace(np.log10(lo), np.log10(hi), n)


def _jw(s, w):
    return 1j * w if s.Ts == 0 else np.exp(1j * w * (s.Ts if s.Ts > 0 else 1.0))


@bi('freqresp', nout=2)
def freqresp(nargout, *args):
    """[H, wout] = freqresp(sys), freqresp(sys, w): the frequency response at the frequencies w (rad/s), an ny-by-nu-by-numel(w) array."""
    nargchk(args, 1, 2, 'freqresp')
    s = _sys(args[0], 'freqresp')
    w = np.asarray(darr(args[1]), float).reshape(-1) if len(args) > 1 else _freq_grid([s])
    H = s.resp(_jw(s, w))
    Hm = np.moveaxis(H, 0, -1)
    res = (out(Hm if Hm.shape[2] > 1 else Hm[:, :, 0]), out(w.reshape(-1, 1)))
    return res if nargout > 1 else res[0]


@bi('damp', nout=3)
def damp(nargout, *args):
    """[wn, zeta, p] = damp(sys): the natural frequency and damping ratio of each pole (in order of frequency); shown when nothing is asked for."""
    nargchk(args, 1, 1, 'damp')
    s = _sys(args[0], 'damp')
    p = _poles(s).astype(complex)
    pc = np.log(p) / s.Ts if s.Ts > 0 else p
    wn = np.abs(pc)
    zeta = -np.cos(np.angle(pc))
    order = np.argsort(wn, kind='stable')
    p, pc, wn, zeta = p[order], pc[order], wn[order], zeta[order]
    if nargout == 0:
        lines = ['', '         Pole              Damping       Frequency      Time Constant', '                                       (rad/seconds)     (seconds)', '']
        for pk, ck, z_, w_ in zip(p, pc, zeta, wn):
            tc = 1 / -ck.real if ck.real < 0 else np.inf
            ptxt = f'{pk.real:.2e}' + (f' {"+" if pk.imag >= 0 else "-"} {abs(pk.imag):.2e}i' if abs(pk.imag) > 0 else '')
            lines.append(f'  {ptxt:>24}   {z_:10.2e}   {w_:12.2e}   {tc:12.2e}')
        R.write('\n'.join(lines) + '\n\n')
        return None
    res = (out(wn.reshape(-1, 1)), out(zeta.reshape(-1, 1)), out(np.real_if_close(p).reshape(-1, 1)))
    return res[:nargout] if nargout > 1 else res[0]


@bi('isstable')
def isstable(nargout, *args):
    """tf = isstable(sys): whether every pole is in the open left half plane (inside the unit circle in discrete time)."""
    nargchk(args, 1, 1, 'isstable')
    s = _sys(args[0], 'isstable')
    p = _poles(s)
    return bool(np.all(p.real < 0)) if s.Ts == 0 else bool(np.all(np.abs(p) < 1))


# ---- state-space analysis and design -------------------------------------------------------------------------------------------------------

def _abcd_args(args, fn, need):
    if isinstance(args[0], LTI):
        A, B, C, D = args[0].ss_data()
        return (A, B, C, D), list(args[1:]), args[0].Ts
    mats = [np.atleast_2d(np.asarray(darr(a), float)) for a in args[:need]]
    return tuple(mats) + (None,) * (4 - need), list(args[need:]), 0.0


@bi('ctrb')
def ctrb(nargout, *args):
    """Co = ctrb(A, B), ctrb(sys): the controllability matrix [B AB A^2B ...]."""
    nargchk(args, 1, 2, 'ctrb')
    (A, B, _, _), _, _ = _abcd_args(args, 'ctrb', 2)
    n = A.shape[0]
    return out(np.hstack([np.linalg.matrix_power(A, k) @ B for k in range(n)]) if n else np.zeros((0, 0)))


@bi('obsv')
def obsv(nargout, *args):
    """Ob = obsv(A, C), obsv(sys): the observability matrix [C; CA; CA^2; ...]."""
    nargchk(args, 1, 2, 'obsv')
    if isinstance(args[0], LTI):
        A, _, C, _ = args[0].ss_data()
    else:
        A, C = (np.atleast_2d(np.asarray(darr(a), float)) for a in args[:2])
    n = A.shape[0]
    return out(np.vstack([C @ np.linalg.matrix_power(A, k) for k in range(n)]) if n else np.zeros((0, 0)))


@bi('lyap')
def lyap(nargout, *args):
    """X = lyap(A, Q), lyap(A, B, C), lyap(A, Q, [], E): the solution of A X + X A' + Q = 0 (or of the Sylvester equation A X + X B + C = 0)."""
    nargchk(args, 2, 4, 'lyap')
    from scipy.linalg import solve_continuous_lyapunov, solve_sylvester
    A = _mat(args[0], 'lyap', 'A')
    if len(args) >= 3 and numel(args[2]):
        return out(solve_sylvester(A, _mat(args[1], 'lyap'), -_mat(args[2], 'lyap')))
    return out(solve_continuous_lyapunov(A, -_mat(args[1], 'lyap', 'Q')))


@bi('dlyap')
def dlyap(nargout, *args):
    """X = dlyap(A, Q): the solution of A X A' - X + Q = 0."""
    nargchk(args, 2, 4, 'dlyap')
    from scipy.linalg import solve_discrete_lyapunov
    return out(solve_discrete_lyapunov(_mat(args[0], 'dlyap', 'A'), _mat(args[1], 'dlyap', 'Q')))


@bi('care', nout=3)
def care(nargout, *args):
    """[X, L, G] = care(A, B, Q, R, S): the stabilizing solution of A'X + XA - (XB + S) R^-1 (B'X + S') + Q = 0, the closed-loop eigenvalues and the gain G = R^-1 (B'X + S')."""
    nargchk(args, 3, 6, 'care')
    from scipy.linalg import solve_continuous_are
    A, B, Q = (_mat(a, 'care') for a in args[:3])
    Rm = _mat(args[3], 'care') if len(args) > 3 and numel(args[3]) else np.eye(B.shape[1])
    S = _mat(args[4], 'care') if len(args) > 4 and numel(args[4]) else None
    X = solve_continuous_are(A, B, Q, Rm, s=S)
    G = np.linalg.solve(Rm, B.T @ X + (S.T if S is not None else 0))
    L = np.linalg.eigvals(A - B @ G)
    res = (out(X), out(np.real_if_close(L).reshape(-1, 1)), out(G))
    return res[:nargout] if nargout > 1 else res[0]


@bi('dare', nout=3)
def dare(nargout, *args):
    """[X, L, G] = dare(A, B, Q, R, S): the stabilizing solution of the discrete Riccati equation, the closed-loop eigenvalues and the gain G = (B'XB + R)^-1 (B'XA + S')."""
    nargchk(args, 3, 6, 'dare')
    from scipy.linalg import solve_discrete_are
    A, B, Q = (_mat(a, 'dare') for a in args[:3])
    Rm = _mat(args[3], 'dare') if len(args) > 3 and numel(args[3]) else np.eye(B.shape[1])
    S = _mat(args[4], 'dare') if len(args) > 4 and numel(args[4]) else None
    X = solve_discrete_are(A, B, Q, Rm, s=S)
    G = np.linalg.solve(B.T @ X @ B + Rm, B.T @ X @ A + (S.T if S is not None else 0))
    L = np.linalg.eigvals(A - B @ G)
    res = (out(X), out(np.real_if_close(L).reshape(-1, 1)), out(G))
    return res[:nargout] if nargout > 1 else res[0]


@bi('lqr', nout=3)
def lqr(nargout, *args):
    """[K, S, P] = lqr(sys, Q, R, N), lqr(A, B, Q, R, N): the state feedback u = -Kx minimizing the integral of x'Qx + u'Ru + 2x'Nu; S the Riccati solution, P the closed-loop poles."""
    nargchk(args, 3, 5, 'lqr')
    if isinstance(args[0], LTI):
        A, B, _, _ = args[0].ss_data()
        rest = list(args[1:])
        disc = args[0].Ts != 0
    else:
        A, B = _mat(args[0], 'lqr', 'A'), _mat(args[1], 'lqr', 'B')
        rest = list(args[2:])
        disc = False
    Q, Rm = _mat(rest[0], 'lqr', 'Q'), _mat(rest[1], 'lqr', 'R')
    N = _mat(rest[2], 'lqr', 'N') if len(rest) > 2 else None
    f = dare if disc else care
    X, L, G = f(3, out(A), out(B), out(Q), out(Rm), out(N) if N is not None else EMPTY())
    res = (G, X, L)
    return res[:nargout] if nargout > 1 else res[0]


@bi('dlqr', nout=3)
def dlqr(nargout, *args):
    """[K, S, e] = dlqr(A, B, Q, R, N): the discrete-time linear-quadratic state feedback u(k) = -K x(k)."""
    nargchk(args, 4, 5, 'dlqr')
    X, L, G = dare(3, *args[:4], args[4] if len(args) > 4 else EMPTY())
    res = (G, X, L)
    return res[:nargout] if nargout > 1 else res[0]


@bi('lqry', nout=3)
def lqry(nargout, *args):
    """[K, S, e] = lqry(sys, Q, R, N): the state feedback that weighs the outputs: y'Qy + u'Ru + 2y'Nu."""
    nargchk(args, 3, 4, 'lqry')
    s = _sys(args[0], 'lqry')
    A, B, C, D = s.ss_data()
    Q, Rm = _mat(args[1], 'lqry'), _mat(args[2], 'lqry')
    N = _mat(args[3], 'lqry') if len(args) > 3 else np.zeros((C.shape[0], B.shape[1]))
    Qx = C.T @ Q @ C
    Rx = Rm + D.T @ Q @ D + N.T @ D + D.T @ N
    Nx = C.T @ (Q @ D + N)
    return lqr(nargout, s, out(Qx), out(Rx), out(Nx))


@bi('lqe', nout=3)
def lqe(nargout, *args):
    """[L, P, E] = lqe(A, G, C, Q, R, N): the Kalman estimator gain for x' = Ax + Bu + Gw, y = Cx + Du + v, w and v of covariances Q and R."""
    nargchk(args, 5, 6, 'lqe')
    A, G, C, Q, Rm = (_mat(a, 'lqe') for a in args[:5])
    N = _mat(args[5], 'lqe') if len(args) > 5 else None
    X, Lp, K = care(3, out(A.T), out(C.T), out(G @ Q @ G.T), out(Rm), out(G @ N) if N is not None else EMPTY())
    L = np.asarray(darr(K), float).T
    res = (out(L), X, out(np.linalg.eigvals(A - L @ C).reshape(-1, 1)))
    return res[:nargout] if nargout > 1 else res[0]


@bi('kalman', nout=3)
def kalman(nargout, *args):
    """[kest, L, P] = kalman(sys, Qn, Rn, Nn): the steady-state Kalman filter for sys with inputs [u; w] (w the last size(Qn, 1) inputs, process noise) and measured outputs y = Cx + Du + v: an estimator with inputs [u; y] and outputs [yhat; xhat]."""
    nargchk(args, 3, 4, 'kalman')
    s = _sys(args[0], 'kalman')
    A, B, C, D = s.ss_data()
    Qn, Rn = _mat(args[1], 'kalman', 'Qn'), _mat(args[2], 'kalman', 'Rn')
    Nn = _mat(args[3], 'kalman', 'Nn') if len(args) > 3 else np.zeros((Qn.shape[0], Rn.shape[0]))
    nw = Qn.shape[0]
    Bu, G = B[:, :B.shape[1] - nw], B[:, B.shape[1] - nw:]
    Du, H = D[:, :D.shape[1] - nw], D[:, D.shape[1] - nw:]
    Qb = G @ Qn @ G.T
    Rb = Rn + H @ Nn + Nn.T @ H.T + H @ Qn @ H.T
    Nb = G @ (Qn @ H.T + Nn)
    if s.Ts == 0:
        from scipy.linalg import solve_continuous_are
        P = solve_continuous_are(A.T, C.T, Qb, Rb, s=Nb)
        L = (P @ C.T + Nb) @ np.linalg.inv(Rb)
    else:
        from scipy.linalg import solve_discrete_are
        P = solve_discrete_are(A.T, C.T, Qb, Rb, s=Nb)
        L = (A @ P @ C.T + Nb) @ np.linalg.inv(C @ P @ C.T + Rb)
    Ae = A - L @ C
    Be = np.hstack([Bu - L @ Du, L])
    n, ny = A.shape[0], C.shape[0]
    Ce = np.vstack([C, np.eye(n)])
    De = np.vstack([np.hstack([Du, np.zeros((ny, ny))]), np.zeros((n, Bu.shape[1] + ny))])
    est = LTI('ss', (Ae, Be, Ce, De), s.Ts)
    res = (est, out(L), out(P))
    return res[:nargout] if nargout > 1 else res[0]


@bi('estim')
def estim(nargout, *args):
    """est = estim(sys, L): the state estimator with gain L: inputs y, outputs [yhat; xhat]."""
    nargchk(args, 2, 4, 'estim')
    s = _sys(args[0], 'estim')
    A, B, C, D = s.ss_data()
    L = _mat(args[1], 'estim', 'L')
    n = A.shape[0]
    return LTI('ss', (A - L @ C, L, np.vstack([C, np.eye(n)]), np.zeros((C.shape[0] + n, L.shape[1]))), s.Ts)


@bi('reg')
def reg(nargout, *args):
    """rsys = reg(sys, K, L): the regulator of state feedback K and estimator gain L: input y, output u = -K xhat."""
    nargchk(args, 3, 5, 'reg')
    s = _sys(args[0], 'reg')
    A, B, C, D = s.ss_data()
    K, L = _mat(args[1], 'reg', 'K'), _mat(args[2], 'reg', 'L')
    Ar = A - B @ K - L @ C + L @ D @ K
    return LTI('ss', (Ar, L, -K, np.zeros((K.shape[0], L.shape[1]))), s.Ts)


@bi('place', nout=2)
def place(nargout, *args):
    """K = place(A, B, p): the state feedback u = -Kx that puts the closed-loop poles at p (robust placement, Kautsky and others)."""
    nargchk(args, 3, 3, 'place')
    from scipy.signal import place_poles
    A, B = _mat(args[0], 'place', 'A'), _mat(args[1], 'place', 'B')
    p = np.asarray(darr(args[2])).reshape(-1)
    r = place_poles(A, B, p)
    res = (out(r.gain_matrix), 0.0)
    return res if nargout > 1 else res[0]


@bi('acker')
def acker(nargout, *args):
    """k = acker(A, b, p): the gain that puts a single-input system's poles at p (Ackermann's formula)."""
    nargchk(args, 3, 3, 'acker')
    A, b = _mat(args[0], 'acker', 'A'), _mat(args[1], 'acker', 'b')
    p = np.asarray(darr(args[2])).reshape(-1)
    n = A.shape[0]
    Co = np.hstack([np.linalg.matrix_power(A, k) @ b for k in range(n)])
    c = np.real(np.poly(p))
    phi = sum(c[k] * np.linalg.matrix_power(A, n - k) for k in range(n + 1))
    e = np.zeros((1, n))
    e[0, -1] = 1
    return out(e @ np.linalg.solve(Co, phi))


@bi('gram')
def gram(nargout, *args):
    """W = gram(sys, 'c'|'o'): the controllability or observability Gramian of a stable model."""
    nargchk(args, 2, 2, 'gram')
    from scipy.linalg import solve_continuous_lyapunov, solve_discrete_lyapunov
    s = _sys(args[0], 'gram')
    A, B, C, D = s.ss_data()
    which = py_str(args[1]).lower()
    M = B @ B.T if which == 'c' else C.T @ C
    At = A if which == 'c' else A.T
    return out(solve_continuous_lyapunov(At, -M) if s.Ts == 0 else solve_discrete_lyapunov(At, M))


@bi('covar', nout=2)
def covar(nargout, *args):
    """[P, Q] = covar(sys, W): the steady-state covariance of the outputs (P) and states (Q) driven by white noise of intensity W."""
    nargchk(args, 2, 2, 'covar')
    from scipy.linalg import solve_continuous_lyapunov, solve_discrete_lyapunov
    s = _sys(args[0], 'covar')
    A, B, C, D = s.ss_data()
    W = _mat(args[1], 'covar', 'W')
    if s.Ts == 0:
        if np.any(D):
            P = np.full((C.shape[0], C.shape[0]), np.inf)
            return (out(P), out(np.full((A.shape[0],) * 2, np.inf))) if nargout > 1 else out(P)
        Q = solve_continuous_lyapunov(A, -B @ W @ B.T)
        P = C @ Q @ C.T
    else:
        Q = solve_discrete_lyapunov(A, B @ W @ B.T)
        P = C @ Q @ C.T + D @ W @ D.T
    return (out(P), out(Q)) if nargout > 1 else out(P)


def _h2(s):
    from scipy.linalg import solve_continuous_lyapunov, solve_discrete_lyapunov
    A, B, C, D = s.ss_data()
    if s.Ts == 0:
        if np.any(D) or (A.size and np.any(np.linalg.eigvals(A).real >= 0)):
            return np.inf
        P = solve_continuous_lyapunov(A, -B @ B.T) if A.size else np.zeros((0, 0))
        return float(np.sqrt(np.trace(C @ P @ C.T))) if A.size else 0.0
    if A.size and np.any(np.abs(np.linalg.eigvals(A)) >= 1):
        return np.inf
    P = solve_discrete_lyapunov(A, B @ B.T) if A.size else np.zeros((0, 0))
    return float(np.sqrt(np.trace(C @ P @ C.T + D @ D.T)))


def _hinf(s):
    """The peak gain over frequency: a fine grid around the poles and zeros, each local peak refined (golden section)."""
    from scipy.optimize import minimize_scalar
    w = np.concatenate([[0.0], _freq_grid([s], 2000)])
    sv = np.array([np.linalg.svd(H, compute_uv=False)[0] if H.size else 0.0 for H in s.resp(_jw(s, w))])
    best_i = int(np.argmax(sv))
    best, wbest = sv[best_i], w[best_i]
    for i in np.flatnonzero((sv[1:-1] >= sv[:-2]) & (sv[1:-1] >= sv[2:])) + 1:
        lo, hi = w[i - 1], w[i + 1]
        r = minimize_scalar(lambda x: -np.linalg.svd(s.resp(_jw(s, np.array([x])))[0], compute_uv=False)[0], bounds=(lo, hi), method='bounded',
                            options={'xatol': 1e-10 * max(1, hi)})
        if -r.fun > best:
            best, wbest = -r.fun, r.x
    if s.Ts == 0:
        Hinf = s.resp(np.array([1e12j]))[0]
        if Hinf.size and np.linalg.svd(Hinf, compute_uv=False)[0] > best:
            best, wbest = np.linalg.svd(Hinf, compute_uv=False)[0], np.inf
    return float(best), float(wbest)


def _norm_lti(nargout, s, *rest):
    kind = rest[0] if rest else 2.0
    if is_str(kind) and py_str(kind).lower() == 'inf' or (not is_str(kind) and np.isinf(float(num(kind)))):
        if s.Ts == 0 and np.any(_poles(s).real >= 0) or s.Ts != 0 and np.any(np.abs(_poles(s)) >= 1):
            return (np.inf, np.nan) if nargout > 1 else np.inf
        g, w = _hinf(s)
        return (g, w) if nargout > 1 else g
    return _h2(s)


@bi('getPeakGain', nout=2)
def getPeakGain(nargout, *args):
    """[gpeak, fpeak] = getPeakGain(sys): the largest gain over frequency (the largest singular value of the response), and where."""
    nargchk(args, 1, 3, 'getPeakGain')
    g, w = _hinf(_sys(args[0], 'getPeakGain'))
    return (g, w) if nargout > 1 else g


@bi('hinfnorm', nout=2)
def hinfnorm(nargout, *args):
    """[ninf, fpeak] = hinfnorm(sys): the H-infinity norm (Inf for an unstable model) and the frequency of the peak."""
    nargchk(args, 1, 2, 'hinfnorm')
    return _norm_lti(nargout, _sys(args[0], 'hinfnorm'), Char.of('inf'))


def _bandwidth_lti(nargout, s, *rest):
    drop = float(num(rest[0])) if rest else -3.0
    if s.shape != (1, 1):
        raise err('Control:bandwidth', 'bandwidth takes a model with one input and one output.', 'bandwidth')
    dc = abs(np.asarray(darr(dcgain(1, s)), complex).reshape(-1)[0])
    if not np.isfinite(dc):
        return np.inf
    w = np.concatenate([[0.0], _freq_grid([s], 4000)])
    mag = np.abs(s.resp(_jw(s, w))[:, 0, 0])
    target = dc * 10 ** (drop / 20)
    below = np.flatnonzero(mag < target)
    if not below.size:
        return np.inf
    i = below[0]
    from scipy.optimize import brentq
    return float(brentq(lambda x: abs(s.resp(_jw(s, np.array([x])))[0, 0, 0]) - target, w[i - 1], w[i]))


# ---- conversions in time --------------------------------------------------------------------------------------------------------------------

@bi('c2d')
def c2d(nargout, *args):
    """sysd = c2d(sysc, Ts), c2d(sysc, Ts, method): the discrete-time model: 'zoh' (unless given), 'foh', 'tustin', 'matched', 'impulse'."""
    nargchk(args, 2, 4, 'c2d')
    from scipy.signal import cont2discrete
    s = _sys(args[0], 'c2d')
    if s.Ts != 0:
        raise err('Control:c2d', 'c2d takes a continuous-time model.', 'c2d')
    Ts = float(num(args[1]))
    method = py_str(args[2]).lower() if len(args) > 2 else 'zoh'
    if method == 'matched':
        if s.shape != (1, 1):
            raise err('Control:c2d', "'matched' takes a model with one input and one output.", 'c2d')
        Z, P, K = s.zpk_data()
        zd = np.exp(np.asarray(Z[0][0], complex) * Ts)
        pd = np.exp(np.asarray(P[0][0], complex) * Ts)
        # zeros at infinity go to z = -1, but one of them (so as to stay causal)
        extra = len(pd) - len(zd) - 1
        zd = np.concatenate([zd, -np.ones(max(extra, 0))])
        hc = s.resp(np.array([0.0]))[0, 0, 0] if not _pole_at(s) else 1.0
        tmp = LTI('zpk', ([[zd]], [[pd]], np.ones((1, 1))), Ts)
        hd = tmp.resp(np.array([1.0]))[0, 0, 0]
        k = float(np.real(hc / hd)) if abs(hd) > 0 else 1.0
        o = LTI('zpk', ([[np.real_if_close(zd)]], [[np.real_if_close(pd)]], np.array([[k]])), Ts)
        return o.to(s.kind) if s.kind != 'zpk' else o
    m = {'zoh': 'zoh', 'foh': 'foh', 'tustin': 'bilinear', 'impulse': 'impulse'}.get(method)
    if m is None:
        raise err('Control:c2d:method', "The method is 'zoh', 'foh', 'tustin', 'matched' or 'impulse'.", 'c2d')
    A, B, C, D = s.ss_data()
    if A.shape[0] == 0:
        return _gain(D, Ts, s.kind)
    Ad, Bd, Cd, Dd, _ = cont2discrete((A, B, C, D), Ts, method=m)
    o = LTI('ss', (Ad, Bd, Cd, Dd), Ts)
    tau = s.total_delay()
    if np.any(tau):
        o.io_delay = np.round(tau / Ts)
    return o.to(s.kind) if s.kind != 'ss' else o


@bi('d2c')
def d2c(nargout, *args):
    """sysc = d2c(sysd), d2c(sysd, method): the continuous-time model a discrete one came from: 'zoh' (unless given) or 'tustin'."""
    nargchk(args, 1, 3, 'd2c')
    from scipy.linalg import logm
    s = _sys(args[0], 'd2c')
    if s.Ts <= 0:
        raise err('Control:d2c', 'd2c takes a discrete-time model with a sample time.', 'd2c')
    T = s.Ts
    method = py_str(args[1]).lower() if len(args) > 1 else 'zoh'
    A, B, C, D = s.ss_data()
    n, m = A.shape[0], B.shape[1]
    if method == 'zoh':
        M = np.block([[A, B], [np.zeros((m, n)), np.eye(m)]])
        L = np.real(logm(M)) / T
        o = LTI('ss', (L[:n, :n], L[:n, n:], C, D), 0.0)
    elif method == 'tustin':
        # the inverse of the bilinear map as c2d makes it (SciPy's cont2discrete, alpha 1/2)
        I = np.eye(n)
        Mi = np.linalg.inv(A + I)
        o = LTI('ss', (2 / T * (A - I) @ Mi, 2 / T * Mi @ B, 2 * C @ Mi, D - C @ Mi @ B), 0.0)
    else:
        raise err('Control:d2c:method', "The method is 'zoh' or 'tustin'.", 'd2c')
    return o.to(s.kind) if s.kind != 'ss' else o


@bi('pade', nout=4)
def pade(nargout, *args):
    """[num, den] = pade(T, N): the Pade approximation of order N of the delay exp(-sT); sysx = pade(sys, N) replaces a model's delays by them."""
    nargchk(args, 2, 4, 'pade')
    N = int(num(args[1])) if not isinstance(args[1], LTI) else 1

    def coeffs(T, N):
        c = [math.factorial(2 * N - k) * math.factorial(N) / (math.factorial(2 * N) * math.factorial(k) * math.factorial(N - k)) * T ** k for k in range(N + 1)]
        den = np.array(c[::-1])
        num_ = np.array([c[k] * (-1) ** k for k in range(N + 1)][::-1])
        return num_ / den[0], den / den[0]
    if isinstance(args[0], LTI):
        s = args[0]
        tau = s.total_delay()
        res = s.to('ss') if s.kind == 'ss' else s
        res = res.value_copy()
        res.io_delay = np.zeros_like(res.io_delay)
        res.input_delay = np.zeros_like(res.input_delay)
        res.output_delay = np.zeros_like(res.output_delay)
        if s.shape == (1, 1) and tau[0, 0]:
            n_, d_ = coeffs(tau[0, 0], N)
            return _mul(res, LTI('tf', ([[n_]], [[d_]]), 0.0).to(res.kind) if res.kind != 'tf' else LTI('tf', ([[n_]], [[d_]]), 0.0))
        if np.any(tau):
            parts = [[_mul(res.index((out(np.array([[i + 1.0]])), out(np.array([[j + 1.0]])))), LTI('tf', ([[coeffs(tau[i, j], N)[0]]], [[coeffs(tau[i, j], N)[1]]]), 0.0))
                      for j in range(s.nu)] for i in range(s.ny)]
            return _concat('vcat', *[_concat('hcat', *row) for row in parts])
        return res
    T = float(num(args[0]))
    n_, d_ = coeffs(T, N)
    if nargout <= 1:
        return LTI('tf', ([[n_]], [[d_]]), 0.0)
    return out(n_.reshape(1, -1)), out(d_.reshape(1, -1))


# ---- realizations and reduction -------------------------------------------------------------------------------------------------------------

def _minreal(s, tol=None):
    if s.kind != 'ss':
        if s.shape == (1, 1):
            return _simplify_tf(s.to('tf')).to(s.kind) if s.kind != 'tf' else _simplify_tf(s)
        n, d = s.tf_data()
        parts = [[_simplify_tf(LTI('tf', ([[n[i][j]]], [[d[i][j]]]), s.Ts)) for j in range(s.nu)] for i in range(s.ny)]
        o = s.same_props('tf', ([[p.data[0][0][0] for p in row] for row in parts], [[p.data[1][0][0] for p in row] for row in parts]))
        return o.to(s.kind) if s.kind != 'tf' else o
    A, B, C, D = s.data
    n = A.shape[0]
    if n == 0:
        return s
    scale = max(np.linalg.norm(A, 1), np.linalg.norm(B, 1), np.linalg.norm(C, 1), 1.0)
    tol = tol if tol is not None else n * 1e-10 * scale
    Kc = np.hstack([np.linalg.matrix_power(A, k) @ B for k in range(n)])
    U, S, _ = np.linalg.svd(Kc)
    r = int(np.sum(S > tol * max(S[0], 1e-300))) if S.size else 0
    Q = U[:, :r]
    A1, B1, C1 = Q.T @ A @ Q, Q.T @ B, C @ Q
    if r:
        Ko = np.vstack([C1 @ np.linalg.matrix_power(A1, k) for k in range(r)])
        U2, S2, Vt2 = np.linalg.svd(Ko)
        r2 = int(np.sum(S2 > tol * max(S2[0], 1e-300))) if S2.size else 0
        W = Vt2[:r2].T
        A1, B1, C1 = W.T @ A1 @ W, W.T @ B1, C1 @ W
    o = s.same_props('ss', (A1, B1, C1, D.copy()))
    return o


@bi('minreal', nout=2)
def minreal(nargout, *args):
    """sysr = minreal(sys), minreal(sys, tol): the model without the states it cannot control or observe (the poles and zeros that cancel)."""
    nargchk(args, 1, 2, 'minreal')
    s = _sys(args[0], 'minreal')
    r = _minreal(s, float(num(args[1])) if len(args) > 1 else None)
    nr = r.ss_data()[0].shape[0] if r.kind == 'ss' else None
    n0 = s.ss_data()[0].shape[0] if s.kind == 'ss' else None
    if nargout == 0 and nr is not None and n0 is not None and nr < n0:
        R.write(f'{n0 - nr} state{"s" if n0 - nr != 1 else ""} removed.\n')
    return r


@bi('ss2ss')
def ss2ss(nargout, *args):
    """sysT = ss2ss(sys, T): the model in the states z = T x."""
    nargchk(args, 2, 2, 'ss2ss')
    s = _sys(args[0], 'ss2ss').to('ss')
    T = _mat(args[1], 'ss2ss', 'T')
    A, B, C, D = s.data
    Ti = np.linalg.inv(T)
    return s.same_props('ss', (T @ A @ Ti, T @ B, C @ Ti, D.copy()))


@bi('xperm')
def xperm(nargout, *args):
    """sysp = xperm(sys, p): the states reordered."""
    nargchk(args, 2, 2, 'xperm')
    s = _sys(args[0], 'xperm').to('ss')
    p = [int(v) - 1 for v in np.asarray(darr(args[1])).reshape(-1)]
    A, B, C, D = s.data
    return s.same_props('ss', (A[np.ix_(p, p)], B[p], C[:, p], D.copy()))


@bi('canon', nout=2)
def canon(nargout, *args):
    """[csys, T] = canon(sys, 'modal'|'companion'): a canonical realization: modal (real block-diagonal, the modes apart) or companion."""
    nargchk(args, 1, 3, 'canon')
    s = _sys(args[0], 'canon').to('ss')
    kind = py_str(args[1]).lower() if len(args) > 1 else 'modal'
    A, B, C, D = s.data
    n = A.shape[0]
    if kind == 'modal':
        vals, V = np.linalg.eig(A)
        order = np.argsort(np.abs(vals), kind='stable')
        cols = []
        done = set()
        for i in order:
            if i in done:
                continue
            v, lam = V[:, i], vals[i]
            if abs(lam.imag) > 1e-12 * max(1, abs(lam)):
                j = next(k for k in order if k not in done and k != i and abs(vals[k] - lam.conjugate()) < 1e-8 * max(1, abs(lam)))
                done |= {i, j}
                if lam.imag < 0:
                    v = V[:, j]
                cols += [v.real, v.imag]
            else:
                done.add(i)
                cols.append(v.real)
        Tm = np.column_stack(cols)
        T = np.linalg.inv(Tm)
    elif kind == 'companion':
        if B.shape[1] != 1:
            raise err('Control:canon', "'companion' takes one input.", 'canon')
        Kc = np.hstack([np.linalg.matrix_power(A, k) @ B for k in range(n)])
        T = np.linalg.inv(Kc)
    else:
        raise err('Control:canon', "The form is 'modal' or 'companion'.", 'canon')
    Ti = np.linalg.inv(T)
    o = s.same_props('ss', (T @ A @ Ti, T @ B, C @ Ti, D.copy()))
    return (o, out(T)) if nargout > 1 else o


def _balance(s):
    from scipy.linalg import solve_continuous_lyapunov, solve_discrete_lyapunov, cholesky, svd
    A, B, C, D = s.ss_data()
    if s.Ts == 0:
        Wc = solve_continuous_lyapunov(A, -B @ B.T)
        Wo = solve_continuous_lyapunov(A.T, -C.T @ C)
    else:
        Wc = solve_discrete_lyapunov(A, B @ B.T)
        Wo = solve_discrete_lyapunov(A.T, C.T @ C)
    Lc = cholesky((Wc + Wc.T) / 2 + 1e-14 * np.eye(A.shape[0]), lower=True)
    Lo = cholesky((Wo + Wo.T) / 2 + 1e-14 * np.eye(A.shape[0]), lower=True)
    U, g, Vt = svd(Lo.T @ Lc)
    S = np.diag(g ** -0.5)
    T = S @ U.T @ Lo.T
    Ti = Lc @ Vt.T @ S
    return T, Ti, g


@bi('hsvd')
def hsvd(nargout, *args):
    """hsv = hsvd(sys): the Hankel singular values of a stable model, largest first."""
    nargchk(args, 1, 1, 'hsvd')
    s = _sys(args[0], 'hsvd')
    _, _, g = _balance(s)
    return out(g.reshape(-1, 1))


@bi('balreal', nout=4)
def balreal(nargout, *args):
    """[sysb, g, T, Ti] = balreal(sys): the balanced realization (both Gramians diag(g)) of a stable model."""
    nargchk(args, 1, 1, 'balreal')
    s = _sys(args[0], 'balreal')
    A, B, C, D = s.ss_data()
    T, Ti, g = _balance(s)
    o = s.same_props('ss', (T @ A @ Ti, T @ B, C @ Ti, D.copy()))
    res = (o, out(g.reshape(-1, 1)), out(T), out(Ti))
    return res[:nargout] if nargout > 1 else res[0]


@bi('balred')
def balred(nargout, *args):
    """rsys = balred(sys, r): a reduced model of order r by balanced truncation (the states of the smallest Hankel singular values left out, the DC gain kept unless 'Truncate')."""
    nargchk(args, 2, 4, 'balred')
    s = _sys(args[0], 'balred')
    r = int(num(args[1]))
    A, B, C, D = s.ss_data()
    T, Ti, g = _balance(s)
    Ab, Bb, Cb = T @ A @ Ti, T @ B, C @ Ti
    elim = list(range(r, A.shape[0]))
    trunc = any(is_str(a) and py_str(a).lower() == 'truncate' for a in args[2:])
    o = _modred_data(Ab, Bb, Cb, D, elim, not trunc, s.Ts)
    return s.same_props('ss', o).to(s.kind) if s.kind != 'ss' else s.same_props('ss', o)


def _modred_data(A, B, C, D, elim, matchdc, Ts):
    keep = [i for i in range(A.shape[0]) if i not in elim]
    if not matchdc or not elim:
        return A[np.ix_(keep, keep)], B[keep], C[:, keep], D.copy()
    A11, A12, A21, A22 = A[np.ix_(keep, keep)], A[np.ix_(keep, elim)], A[np.ix_(elim, keep)], A[np.ix_(elim, elim)]
    B1, B2, C1, C2 = B[keep], B[elim], C[:, keep], C[:, elim]
    M = A22 if Ts == 0 else A22 - np.eye(len(elim))
    Mi = np.linalg.inv(M)
    return A11 - A12 @ Mi @ A21, B1 - A12 @ Mi @ B2, C1 - C2 @ Mi @ A21, D - C2 @ Mi @ B2


@bi('modred')
def modred(nargout, *args):
    """rsys = modred(sys, elim), modred(sys, elim, 'MatchDC'|'Truncate'): the model without the states elim: their derivatives set to zero so that the DC gain stays (unless 'Truncate')."""
    nargchk(args, 2, 3, 'modred')
    s = _sys(args[0], 'modred')
    A, B, C, D = s.ss_data()
    elim = [int(v) - 1 for v in np.asarray(darr(args[1])).reshape(-1)] if np.asarray(darr(args[1])).dtype != bool else list(np.flatnonzero(np.asarray(darr(args[1])).reshape(-1)))
    match = not (len(args) > 2 and py_str(args[2]).lower() in ('truncate', 'del'))
    o = s.same_props('ss', _modred_data(A, B, C, D, elim, match, s.Ts))
    return o.to(s.kind) if s.kind != 'ss' else o


# ---- time responses -------------------------------------------------------------------------------------------------------------------------

def _final_time(syss):
    tf_ = 0.0
    for s in syss:
        p = _poles(s)
        pc = np.log(p.astype(complex)) / s.Ts if s.Ts > 0 else p.astype(complex)
        stable = pc[pc.real < -1e-9]
        if stable.size:
            # seven time constants of the slowest pole; a lightly damped one shows its swings within them, and repeated
            # poles (split a little by root finding) must not count as slow oscillations
            p0 = stable[np.argmax(stable.real)]
            m = int(np.sum(np.abs(stable - p0) < 1e-2 * abs(p0)))       # its multiplicity: t^(m-1) e^(-t) decays later
            slow = -p0.real
            tf_ = max(tf_, min((7 + 3 * (m - 1)) / slow, 1e4 * 7 / -np.min(stable.real)))
        elif pc.size:
            tf_ = max(tf_, 10.0 if np.all(np.abs(pc) < 1e-9) else 5 / max(np.max(np.abs(pc)), 1e-3))
        tau = np.max(s.total_delay()) if s.total_delay().size else 0
        tf_ += tau * (s.Ts if s.Ts > 0 else 1)
    return tf_ if tf_ > 0 else 10.0


def _time_vec(s, T):
    if s.Ts > 0:
        if T is None:
            T = _final_time([s])
        if np.ndim(T) == 0:
            return np.arange(0, float(T) + s.Ts / 2, s.Ts)
        return np.asarray(T, float)
    if T is None:
        T = _final_time([s])
    if np.ndim(T) == 0:
        p = _poles(s)
        fast = np.max(np.abs(p)) if p.size else 1.0
        n = int(min(max(float(T) * fast * 20, 400), 5000))
        return np.linspace(0, float(T), n)
    return np.asarray(T, float)


def _simulate(s, t, u, x0=None, method='foh'):
    """y(t) (len(t), ny) and x(t) for input samples u (len(t), nu), delays applied by shifting."""
    A, B, C, D = s.ss_data()
    n = A.shape[0]
    x = np.zeros(n) if x0 is None else np.asarray(x0, float).reshape(-1)
    N = t.size
    Y = np.zeros((N, s.ny))
    X = np.zeros((N, n))
    tau = s.total_delay()
    if np.any(tau) and np.ptp(tau) == 0:
        d = tau.reshape(-1)[0] * (s.Ts if s.Ts > 0 else 1)
        if N > 1:
            u = np.vstack([np.zeros((int(np.sum(t < t[0] + d - 1e-12)), u.shape[1])), u])[:N] if s.Ts > 0 else \
                np.array([np.interp(t - d, t, u[:, k], left=0.0) for k in range(u.shape[1])]).T
    elif np.any(tau):
        raise err('Control:delay', 'Different delays on different channels: use pade first.', 'lsim')
    if s.Ts > 0:
        for k in range(N):
            X[k] = x
            Y[k] = C @ x + D @ u[k] if n else D @ u[k]
            x = A @ x + B @ u[k] if n else x
        return Y, X
    from scipy.linalg import expm
    X[0] = x
    Y[0] = (C @ x if n else 0) + D @ u[0]
    for k in range(1, N):
        h = t[k] - t[k - 1]
        if n:
            m = B.shape[1]
            # exact for a piecewise-linear input (or piecewise constant, 'zoh')
            M = np.zeros((n + 2 * m, n + 2 * m))
            M[:n, :n] = A * h
            M[:n, n:n + m] = B * h
            M[n:n + m, n + m:] = np.eye(m)
            E = expm(M)
            F0, F1 = E[:n, n:n + m], E[:n, n + m:]
            du = u[k] - u[k - 1] if method == 'foh' else 0 * u[k]
            x = E[:n, :n] @ x + F0 @ u[k - 1] + F1 @ du
        X[k] = x
        Y[k] = (C @ x if n else 0) + D @ u[k]
    return Y, X


def _response(kind, s, T, x0=None):
    t = _time_vec(s, T)
    N = t.size
    if kind == 'step':
        cols = []
        for j in range(s.nu):
            u = np.zeros((N, s.nu))
            u[:, j] = 1.0
            Y, _ = _simulate(s, t, u, method='zoh')
            cols.append(Y)
        return t, np.stack(cols, axis=2)
    if kind == 'impulse':
        cols = []
        A, B, C, D = s.ss_data()
        for j in range(s.nu):
            if s.Ts > 0:
                u = np.zeros((N, s.nu))
                u[0, j] = 1.0 / s.Ts
                Y, _ = _simulate(s, t, u)
            else:
                sj = LTI('ss', (A, np.zeros_like(B), C, np.zeros_like(D)), 0.0, io_delay=np.zeros((s.ny, s.nu)))
                Y, _ = _simulate(sj, t, np.zeros((N, s.nu)), x0=B[:, j])
                tau = s.total_delay()[0, j] if s.total_delay().size else 0
                if tau:
                    Y = np.array([np.interp(t - tau, t, Y[:, i], left=0.0) for i in range(Y.shape[1])]).T
            cols.append(Y)
        return t, np.stack(cols, axis=2)
    Y, _ = _simulate(s, t, np.zeros((N, s.nu)), x0=x0)
    return t, Y[:, :, None]


def _plot_args(args, fn):
    """(systems with their line specs, time or frequency argument, the rest)."""
    syss, rest = [], list(args)
    spec = []
    while rest and isinstance(rest[0], LTI):
        syss.append(rest.pop(0))
        spec.append(py_str(rest.pop(0)) if rest and is_str(rest[0]) and not isinstance(rest[0], Cell) else None)
    if not syss:
        raise err(f'Control:{fn}:model', f'{fn} takes a model (tf, zpk, ss).', fn)
    return syss, spec, rest


def _draw_time(fn, syss, specs, results, title, ylabel='Amplitude'):
    from .graphics import newplot
    from ..graphics_base import Line
    ax = newplot(None)
    for s, sp, (t, Y) in zip(syss, specs, results):
        col = ax.next_color()
        style, marker = '-', 'none'
        if sp:
            from ..graphics_base import parse_linespec
            ps = parse_linespec(sp)
            if ps:
                c, ls, mk = ps
                col = c if c is not None else col
                style = ls or '-'
                marker = mk or 'none'
        for i in range(Y.shape[1]):
            for j in range(Y.shape[2]):
                L = Line(ax)
                if s.Ts > 0:
                    xs = np.repeat(t, 2)[1:]
                    ys = np.repeat(Y[:, i, j], 2)[:-1]
                    L.props['XData'], L.props['YData'] = xs.reshape(1, -1), ys.reshape(1, -1)
                else:
                    L.props['XData'], L.props['YData'] = t.reshape(1, -1), Y[:, i, j].reshape(1, -1)
                L.props['Color'] = col
                L.props['LineStyle'] = style
                L.props['Marker'] = marker
    R._builtin('title', ax, Char.of(title))
    R._builtin('xlabel', ax, Char.of('Time (seconds)'))
    R._builtin('ylabel', ax, Char.of(ylabel))
    R._builtin('grid', ax, Char.of('on'))
    ax.touch()


def _timefun(kind):
    def f(nargout, *args):
        nargchk(args, 1, 20, kind)
        if kind == 'initial':
            syss, specs, rest = _plot_args(args[:1], kind)
            x0 = np.asarray(darr(args[1]), float).reshape(-1)
            rest = list(args[2:])
        else:
            syss, specs, rest = _plot_args(args, kind)
            x0 = None
        T = None
        if rest:
            Tv = np.asarray(darr(rest[0]), float).reshape(-1)
            T = float(Tv[0]) if Tv.size == 1 else Tv
        if nargout == 0:
            res = [_response(kind, s, T if T is not None else _final_time(syss), x0) for s in syss]
            _draw_time(kind, syss, specs, res, {'step': 'Step Response', 'impulse': 'Impulse Response', 'initial': 'Response to Initial Conditions'}[kind])
            return None
        s = syss[0]
        t, Y = _response(kind, s, T, x0)
        if kind == 'initial':
            _, X = _simulate(s, t, np.zeros((t.size, s.nu)), x0=x0)
            res = (out(Y[:, :, 0]), out(t.reshape(-1, 1)), out(X))
        else:
            Yo = Y[:, :, 0] if s.nu == 1 else Y
            res = (out(Yo if Yo.ndim == 2 else Yo), out(t.reshape(-1, 1)))
            if nargout > 2:
                A, B, C, D = s.ss_data()
                res = res + (EMPTY(),)
        return res[:nargout] if nargout > 1 else res[0]
    f.__name__ = kind
    return f


for _name, _kind, _doc in (
        ('step', 'step', "[y, t] = step(sys), step(sys, Tfinal), step(sys, t), step(sys1, 'r', sys2, ...): the step response, drawn when nothing is asked for."),
        ('impulse', 'impulse', '[y, t] = impulse(sys), impulse(sys, Tfinal), impulse(sys, t): the impulse response, drawn when nothing is asked for.'),
        ('initial', 'initial', '[y, t, x] = initial(sys, x0), initial(sys, x0, Tfinal): the free response from the state x0, drawn when nothing is asked for.'),
        ('stepplot', 'step', 'stepplot(sys, ...): the step response drawn.'),
        ('impulseplot', 'impulse', 'impulseplot(sys, ...): the impulse response drawn.')):
    _f = _timefun(_kind)
    _f.__doc__ = _doc
    bi(_name, nout=3)(_f)


@bi('lsim', nout=3)
def lsim(nargout, *args):
    """[y, t, x] = lsim(sys, u, t), lsim(sys, u, t, x0), lsim(sys, u, t, x0, 'zoh'|'foh'): the response to the input u (a column for each input, a row for each time t)."""
    nargchk(args, 2, 6, 'lsim')
    s = _sys(args[0], 'lsim')
    u = np.asarray(darr(args[1]), float)
    if u.ndim == 1 or (u.shape[0] == 1 and s.nu == 1):
        u = u.reshape(-1, 1)
    t = np.asarray(darr(args[2]), float).reshape(-1) if len(args) > 2 else (np.arange(u.shape[0]) * s.Ts if s.Ts > 0 else None)
    if t is None:
        raise err('Control:lsim', 'lsim of a continuous-time model takes the times t.', 'lsim')
    if u.shape[0] != t.size and u.shape[1] == t.size:
        u = u.T
    x0 = np.asarray(darr(args[3]), float).reshape(-1) if len(args) > 3 and numel(args[3]) else None
    method = py_str(args[4]).lower() if len(args) > 4 else 'foh'
    Y, X = _simulate(s, t, u, x0, method)
    if nargout == 0:
        _draw_time('lsim', [s], [None], [(t, Y[:, :, None])], 'Linear Simulation Results')
        return None
    res = (out(Y), out(t.reshape(-1, 1)), out(X))
    return res[:nargout] if nargout > 1 else res[0]


@bi('stepinfo')
def stepinfo(nargout, *args):
    """S = stepinfo(sys), stepinfo(y, t), stepinfo(y, t, yfinal), stepinfo(..., 'SettlingTimeThreshold', s, 'RiseTimeLimits', [lo hi]): the step response's rise time, settling time, overshoot, undershoot, peak and peak time."""
    nargchk(args, 1, 8, 'stepinfo')
    a = list(args)
    if isinstance(a[0], LTI):
        s = a.pop(0)
        T = _final_time([s])
        t, Y = _response('step', s, np.linspace(0, T, 4001) if s.Ts == 0 else None)
        y = Y[:, 0, 0]
        dc = np.asarray(darr(dcgain(1, s)), complex).reshape(-1)[0].real
        yfinal = dc if np.isfinite(dc) else y[-1]
        y0 = y[0]
    else:
        y = np.asarray(darr(a.pop(0)), float).reshape(-1)
        t = np.asarray(darr(a.pop(0)), float).reshape(-1) if a and not is_str(a[0]) else np.arange(y.size, dtype=float)
        yfinal = float(num(a.pop(0))) if a and not is_str(a[0]) else y[-1]
        y0 = y[0]
    o = {py_str(a[i]).lower(): a[i + 1] for i in range(0, len(a) - 1, 2)}
    thr = float(num(o.get('settlingtimethreshold', 0.02)))
    rl = np.asarray(darr(o['risetimelimits']), float).reshape(-1) if 'risetimelimits' in o else np.array([0.1, 0.9])
    span = yfinal - y0
    if not np.isfinite(yfinal) or span == 0:
        nanv = float('nan')
        return Struct.scalar({k: nanv for k in ('RiseTime', 'TransientTime', 'SettlingTime', 'SettlingMin', 'SettlingMax', 'Overshoot', 'Undershoot', 'Peak', 'PeakTime')})
    z = (y - y0) / span

    def cross(level):
        idx = np.flatnonzero(z >= level)
        if not idx.size:
            return np.nan
        i = idx[0]
        if i == 0:
            return t[0]
        return t[i - 1] + (level - z[i - 1]) / (z[i] - z[i - 1]) * (t[i] - t[i - 1])
    rise = cross(rl[1]) - cross(rl[0])
    err_ = np.abs(y - yfinal)
    out_band = np.flatnonzero(err_ > thr * abs(span))
    if not out_band.size:
        settle = t[0]
    elif out_band[-1] == y.size - 1:
        settle = np.nan
    else:
        k = out_band[-1]
        settle = t[k] + (t[k + 1] - t[k]) * (err_[k] - thr * abs(span)) / max(err_[k] - err_[k + 1], 1e-300)
    after = t >= (t[0] + (cross(rl[1]) if np.isfinite(cross(rl[1])) else 0))
    ip = int(np.argmax(np.abs(y)))
    peak, tpeak = abs(y[ip]), t[ip]
    if 0 < ip < y.size - 1:
        # the peak between samples: the parabola through the three around it
        y0_, y1_, y2_ = abs(y[ip - 1]), abs(y[ip]), abs(y[ip + 1])
        den_ = y0_ - 2 * y1_ + y2_
        if den_ < 0:
            off = 0.5 * (y0_ - y2_) / den_
            h = t[ip + 1] - t[ip]
            peak, tpeak = y1_ - 0.25 * (y0_ - y2_) * off, t[ip] + off * h
    over = max(0.0, 100 * (np.max(z) - 1)) if span else 0.0
    under = max(0.0, -100 * np.min(z))
    S = {'RiseTime': float(rise), 'TransientTime': float(settle), 'SettlingTime': float(settle),
         'SettlingMin': float(np.min(y[after])) if np.any(after) else float('nan'), 'SettlingMax': float(np.max(y[after])) if np.any(after) else float('nan'),
         'Overshoot': float(max(over, 100 * (peak - abs(yfinal)) / abs(span)) if span > 0 and peak > abs(yfinal) else over), 'Undershoot': float(under),
         'Peak': float(peak), 'PeakTime': float(tpeak)}
    return Struct.scalar(S)


# ---- frequency responses and margins ----------------------------------------------------------------------------------------------------------

def _w_arg(rest, syss):
    if rest and not is_str(rest[0]):
        w = rest[0]
        if isinstance(w, Cell):
            lo, hi = (float(num(x)) for x in w.a.reshape(-1))
            return np.logspace(math.log10(lo), math.log10(hi), 400)
        return np.asarray(darr(w), float).reshape(-1)
    return _freq_grid(syss)


def _unwrap_deg(H):
    return np.degrees(np.unwrap(np.angle(H), axis=0))


@bi('bode', nout=3)
def bode(nargout, *args):
    """[mag, phase, wout] = bode(sys), bode(sys, w), bode(sys, {wmin, wmax}), bode(sys1, sys2, ...): the gain (absolute) and phase (degrees) over frequency (rad/s), drawn when nothing is asked for (gain in dB)."""
    syss, specs, rest = _plot_args(args, 'bode')
    w = _w_arg(rest, syss)
    if nargout:
        s = syss[0]
        H = s.resp(_jw(s, w))
        mag = np.moveaxis(np.abs(H), 0, -1)
        ph = np.moveaxis(_unwrap_deg(H), 0, -1)
        res = (out(mag), out(ph), out(w.reshape(-1, 1)))
        return res[:nargout] if nargout > 1 else res[0]
    from ..graphics_base import Line
    ax1 = R._builtin('subplot', 2.0, 1.0, 1.0)
    ax2 = R._builtin('subplot', 2.0, 1.0, 2.0)
    for s, sp in zip(syss, specs):
        H = s.resp(_jw(s, w))
        col = ax1.next_color()
        ax2.next_color()
        for i in range(s.ny):
            for j in range(s.nu):
                for ax, vals in ((ax1, 20 * np.log10(np.abs(H[:, i, j]))), (ax2, _unwrap_deg(H[:, i:i + 1, j])[:, 0])):
                    L = Line(ax)
                    L.props['XData'], L.props['YData'] = w.reshape(1, -1), vals.reshape(1, -1)
                    L.props['Color'] = col
    for ax, yl in ((ax1, 'Magnitude (dB)'), (ax2, 'Phase (deg)')):
        ax.set_value('XScale', Char.of('log'))
        R._builtin('ylabel', ax, Char.of(yl))
        R._builtin('grid', ax, Char.of('on'))
        ax.touch()
    R._builtin('title', ax1, Char.of('Bode Diagram'))
    R._builtin('xlabel', ax2, Char.of('Frequency (rad/s)'))
    return None


bi('bodeplot')(lambda nargout, *args: bode(0, *args))


@bi('nyquist', nout=3)
def nyquist(nargout, *args):
    """[re, im, wout] = nyquist(sys), nyquist(sys, w): the frequency response in the complex plane, drawn with its mirror image for negative frequencies when nothing is asked for."""
    syss, specs, rest = _plot_args(args, 'nyquist')
    w = _w_arg(rest, syss)
    if nargout:
        s = syss[0]
        H = np.moveaxis(s.resp(_jw(s, w)), 0, -1)
        res = (out(H.real), out(H.imag), out(w.reshape(-1, 1)))
        return res[:nargout] if nargout > 1 else res[0]
    from .graphics import newplot
    from ..graphics_base import Line
    ax = newplot(None)
    for s in syss:
        H = s.resp(_jw(s, w))[:, 0, 0]
        col = ax.next_color()
        for vals, style in ((H, '-'), (np.conj(H), '--')):
            L = Line(ax)
            L.props['XData'], L.props['YData'] = vals.real.reshape(1, -1), vals.imag.reshape(1, -1)
            L.props['Color'] = col
            L.props['LineStyle'] = style
    M = Line(ax)
    M.props['XData'], M.props['YData'] = np.array([[-1.0]]), np.array([[0.0]])
    M.props['Marker'] = '+'
    M.props['LineStyle'] = 'none'
    M.props['Color'] = (0.85, 0.0, 0.0)
    R._builtin('title', ax, Char.of('Nyquist Diagram'))
    R._builtin('xlabel', ax, Char.of('Real Axis'))
    R._builtin('ylabel', ax, Char.of('Imaginary Axis'))
    R._builtin('grid', ax, Char.of('on'))
    ax.touch()
    return None


@bi('nichols', nout=3)
def nichols(nargout, *args):
    """[mag, phase, wout] = nichols(sys), nichols(sys, w): the open-loop gain (dB when drawn) against phase (degrees)."""
    syss, specs, rest = _plot_args(args, 'nichols')
    w = _w_arg(rest, syss)
    if nargout:
        return bode(nargout, syss[0], out(w))
    from .graphics import newplot
    from ..graphics_base import Line
    ax = newplot(None)
    for s in syss:
        H = s.resp(_jw(s, w))[:, 0:1, 0]
        L = Line(ax)
        L.props['XData'], L.props['YData'] = _unwrap_deg(H)[:, 0].reshape(1, -1), (20 * np.log10(np.abs(H[:, 0]))).reshape(1, -1)
        L.props['Color'] = ax.next_color()
    R._builtin('title', ax, Char.of('Nichols Chart'))
    R._builtin('xlabel', ax, Char.of('Open-Loop Phase (deg)'))
    R._builtin('ylabel', ax, Char.of('Open-Loop Gain (dB)'))
    R._builtin('grid', ax, Char.of('on'))
    ax.touch()
    return None


@bi('sigma', nout=2)
def sigma(nargout, *args):
    """[sv, wout] = sigma(sys), sigma(sys, w): the singular values of the frequency response, drawn in dB when nothing is asked for."""
    syss, specs, rest = _plot_args(args, 'sigma')
    w = _w_arg(rest, syss)
    s = syss[0]
    H = s.resp(_jw(s, w))
    sv = np.array([np.linalg.svd(Hk, compute_uv=False) for Hk in H]).T
    if nargout:
        return (out(sv), out(w.reshape(-1, 1))) if nargout > 1 else out(sv)
    from .graphics import newplot
    from ..graphics_base import Line
    ax = newplot(None)
    col = ax.next_color()
    for row in sv:
        L = Line(ax)
        L.props['XData'], L.props['YData'] = w.reshape(1, -1), (20 * np.log10(row)).reshape(1, -1)
        L.props['Color'] = col
    ax.set_value('XScale', Char.of('log'))
    R._builtin('title', ax, Char.of('Singular Values'))
    R._builtin('xlabel', ax, Char.of('Frequency (rad/s)'))
    R._builtin('ylabel', ax, Char.of('Singular Values (dB)'))
    R._builtin('grid', ax, Char.of('on'))
    ax.touch()
    return None


def _margins(s):
    """All gain and phase margins of a single-input single-output loop: the phase crossings where the response crosses the
    negative real axis (Im H changes sign, Re H < 0), the gain crossings where |H| passes 1, found on a fine grid and refined
    by Brent's method."""
    from scipy.optimize import brentq
    if s.shape != (1, 1):
        raise err('Control:margin', 'margin takes a model with one input and one output.', 'margin')
    w = _freq_grid([s], 6000)
    if s.Ts > 0:
        w = w[w < math.pi / s.Ts]
        w = np.concatenate([w, [math.pi / s.Ts * (1 - 1e-12)]])

    def H1(x):
        return s.resp(_jw(s, np.array([x])))[0, 0, 0]
    H = s.resp(_jw(s, w))[:, 0, 0]
    gm, wg, pm, wp = [], [], [], []
    for i in range(len(w) - 1):
        a_, b_ = H[i].imag, H[i + 1].imag
        if a_ * b_ < 0 or (b_ == 0 and a_ != 0):
            try:
                x = brentq(lambda v: H1(v).imag, w[i], w[i + 1]) if b_ != 0 else w[i + 1]
            except ValueError:
                continue
            h = H1(x)
            if h.real < 0 and abs(h) > 0:
                gm.append(1 / abs(h))
                wg.append(x)
        m1, m2 = abs(H[i]) - 1, abs(H[i + 1]) - 1
        if m1 * m2 < 0:
            x = brentq(lambda v: abs(H1(v)) - 1, w[i], w[i + 1])
            ph = math.degrees(np.angle(H1(x)))
            pm.append((ph + 180 + 180) % 360 - 180)
            wp.append(x)
    return gm, wg, pm, wp


@bi('margin', nout=4)
def margin(nargout, *args):
    """[Gm, Pm, Wcg, Wcp] = margin(sys): the gain margin (absolute) and phase margin (degrees) of a loop, and the frequencies where the phase crosses -180 and the gain crosses 1; Inf when there is no crossing. Drawn on its Bode diagram when nothing is asked for."""
    nargchk(args, 1, 3, 'margin')
    s = _sys(args[0], 'margin')
    gm, wg, pm, wp = _margins(s)
    if gm:
        i = int(np.argmin(np.abs(np.log(np.array(gm)))))
        Gm, Wcg = gm[i], wg[i]
    else:
        Gm, Wcg = np.inf, np.nan
    if pm:
        i = int(np.argmin(np.abs(pm)))
        Pm, Wcp = pm[i], wp[i]
    else:
        Pm, Wcp = np.inf, np.nan
    if nargout == 0:
        bode(0, s)
        fig = R._builtin('gcf')
        ax1 = [c for c in fig.children if getattr(c, 'TYPE', '') == 'axes']
        title = f'Bode Diagram   Gm = {20 * math.log10(Gm):.3g} dB (at {Wcg:.3g} rad/s), Pm = {Pm:.3g} deg (at {Wcp:.3g} rad/s)'
        if ax1:
            R._builtin('title', ax1[-1] if len(ax1) == 1 else sorted(ax1, key=lambda a: -np.asarray(a.get_value('Position')).reshape(-1)[1])[0], Char.of(title))
        return None
    res = (float(Gm), float(Pm), float(Wcg), float(Wcp))
    return res[:nargout] if nargout > 1 else res[0]


@bi('allmargin')
def allmargin(nargout, *args):
    """S = allmargin(sys): every gain margin and phase margin of a loop, the delay margins, the frequencies, and whether the closed loop is stable."""
    nargchk(args, 1, 1, 'allmargin')
    s = _sys(args[0], 'allmargin')
    gm, wg, pm, wp = _margins(s)
    dm = [((p * math.pi / 180) / w_ if w_ > 0 and p >= 0 else np.inf) for p, w_ in zip(pm, wp)]
    if s.Ts > 0:
        dm = [d / s.Ts for d in dm]
    try:
        cl = feedback(1, s, 1.0)
        stable = isstable(1, cl)
    except MError:
        stable = False
    return Struct.scalar({'GainMargin': out(np.array(gm).reshape(1, -1)), 'GMFrequency': out(np.array(wg).reshape(1, -1)),
                          'PhaseMargin': out(np.array(pm).reshape(1, -1)), 'PMFrequency': out(np.array(wp).reshape(1, -1)),
                          'DelayMargin': out(np.array(dm).reshape(1, -1)), 'DMFrequency': out(np.array(wp).reshape(1, -1)), 'Stable': bool(stable)})


# ---- root locus and pole-zero maps -------------------------------------------------------------------------------------------------------

def _locus(s, ks=None):
    n, d = s.tf_data()
    num_, den = _trim(n[0][0]), _trim(d[0][0])
    if ks is None:
        ks = np.concatenate([[0.0], np.logspace(-4, 4, 600)])
        dc = abs(num_[0] / den[0]) if num_[0] else 1
        ks = ks / max(dc, 1e-12) if dc > 0 else ks
    deg = len(den) - 1
    rows = []
    prev = None
    for k in ks:
        r = np.roots(_padd(den, k * num_))
        r = np.concatenate([r, np.full(deg - r.size, np.nan)]) if r.size < deg else r[:deg]
        if prev is not None:
            # each branch carries on to the nearest new root
            order = []
            left = list(range(len(r)))
            for p in prev:
                if not left:
                    break
                j = min(left, key=lambda q: abs(r[q] - p) if np.isfinite(r[q]) and np.isfinite(p) else np.inf)
                order.append(j)
                left.remove(j)
            r = r[order + left]
        rows.append(r)
        prev = r
    return np.array(rows), ks


@bi('rlocus', nout=2)
def rlocus(nargout, *args):
    """[r, k] = rlocus(sys), rlocus(sys, k): the closed-loop poles of the loop sys with negative feedback gain k, as k goes from 0 to infinity (each column a gain); drawn when nothing is asked for."""
    nargchk(args, 1, 3, 'rlocus')
    s = _sys(args[0], 'rlocus')
    if s.shape != (1, 1):
        raise err('Control:rlocus', 'rlocus takes a model with one input and one output.', 'rlocus')
    ks = np.asarray(darr(args[1]), float).reshape(-1) if len(args) > 1 and not isinstance(args[1], LTI) else None
    rows, ks = _locus(s, ks)
    if nargout:
        return (out(rows.T), out(ks.reshape(1, -1))) if nargout > 1 else out(rows.T)
    from .graphics import newplot
    from ..graphics_base import Line
    ax = newplot(None)
    col = ax.next_color()
    for b in range(rows.shape[1]):
        L = Line(ax)
        L.props['XData'], L.props['YData'] = rows[:, b].real.reshape(1, -1), rows[:, b].imag.reshape(1, -1)
        L.props['Color'] = col
    _pz_marks(ax, s)
    R._builtin('title', ax, Char.of('Root Locus'))
    R._builtin('xlabel', ax, Char.of('Real Axis'))
    R._builtin('ylabel', ax, Char.of('Imaginary Axis'))
    R._builtin('grid', ax, Char.of('on'))
    ax.touch()
    return None


def _pz_marks(ax, s):
    from ..graphics_base import Line
    p = _poles(s)
    z = np.asarray(s.zpk_data()[0][0][0], complex) if s.shape == (1, 1) else _tzero(s)
    for vals, mk in ((p, 'x'), (z, 'o')):
        if len(vals):
            L = Line(ax)
            L.props['XData'], L.props['YData'] = np.real(vals).reshape(1, -1), np.imag(vals).reshape(1, -1)
            L.props['LineStyle'] = 'none'
            L.props['Marker'] = mk
            L.props['MarkerSize'] = 8.0
            L.props['Color'] = (0.0, 0.447, 0.741)


@bi('pzmap', nout=2)
def pzmap(nargout, *args):
    """[p, z] = pzmap(sys): the poles and zeros, drawn (x and o) when nothing is asked for."""
    nargchk(args, 1, 10, 'pzmap')
    syss, specs, rest = _plot_args(args, 'pzmap')
    s = syss[0]
    if nargout:
        z = np.asarray(s.zpk_data()[0][0][0], complex) if s.shape == (1, 1) else _tzero(s)
        return (out(np.real_if_close(_poles(s)).reshape(-1, 1)), out(np.real_if_close(z).reshape(-1, 1))) if nargout > 1 else out(np.real_if_close(_poles(s)).reshape(-1, 1))
    from .graphics import newplot
    ax = newplot(None)
    for s in syss:
        _pz_marks(ax, s)
    R._builtin('title', ax, Char.of('Pole-Zero Map'))
    R._builtin('xlabel', ax, Char.of('Real Axis'))
    R._builtin('ylabel', ax, Char.of('Imaginary Axis'))
    R._builtin('grid', ax, Char.of('on'))
    ax.touch()
    return None


# ---- the builtins that take models too ---------------------------------------------------------------------------------------------------

def _wrap(name, handler, nout=None):
    info = REG.get(name)
    if info is None:
        return
    orig = info.fn
    ws, aw = info.ws, info.aw
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and isinstance(args[0], LTI):
                return handler(a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and isinstance(args[0], LTI):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = f
    if nout is not None:
        info.nout = max(info.nout, nout)


_wrap('series', _series_lti)
_wrap('inv', _inv_lti)
_wrap('exp', _exp_lti)
_wrap('norm', _norm_lti, 2)
_wrap('bandwidth', _bandwidth_lti)
def _size_lti(nargout, s, *rest):
    if rest:
        d = int(num(rest[0]))
        return float((s.ny, s.nu)[d - 1]) if d <= 2 else 1.0
    if nargout > 1:
        return (float(s.ny), float(s.nu)) + (1.0,) * (nargout - 2)
    return out(np.array([[s.ny, s.nu]], float))


_wrap('size', _size_lti)
