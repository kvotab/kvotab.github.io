"""More control systems: frequency-response data models (frd, frdata, and
bode, freqresp, feedback and the arithmetic taking them), bodemag,
lsiminfo, block interconnections (append, sumblk, connect), d2d, the
staircase forms (ctrbf, obsvf), lqi, and pidtune with pidtuneOptions."""
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, num, is_str, darr, out
from ..values import MError, Obj, Char, Cell, Struct, numel, py_str, text_list
from .. import runtime as R
from . import control as K


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                raise err(f'Control:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0]) from None
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


def _mat(v, fn, what):
    a = np.asarray(darr(v, fn), float)
    return a.reshape(1, 1) if a.ndim == 0 else a


# ---- frequency-response data ---------------------------------------------------------------------------------------------------

class FRD(Obj):
    """A model given by its frequency response: H (ny, nu, nf) at the frequencies w (rad/s, or Hz as FrequencyUnit says)."""
    cls = 'frd'
    is_handle = False

    def __init__(self, H, w, Ts=0.0, unit='rad/TimeUnit'):
        self.H = np.asarray(H, complex)
        self.w = np.asarray(w, float).reshape(-1)
        self.Ts = float(Ts)
        self.unit = unit
        self.names = {'InputName': [''] * self.H.shape[1], 'OutputName': [''] * self.H.shape[0], 'Name': ''}

    @property
    def shape(self):
        return self.H.shape[:2]

    def rad(self):
        """The frequencies in rad/s."""
        return self.w * 2 * np.pi if self.unit == 'Hz' else self.w

    def value_copy(self):
        o = FRD(self.H.copy(), self.w.copy(), self.Ts, self.unit)
        o.names = {k: (list(v) if isinstance(v, list) else v) for k, v in self.names.items()}
        return o

    def getprop(self, name):
        k = name.lower()
        if k == 'frequency':
            return out(self.w.reshape(-1, 1))
        if k == 'responsedata':
            return out(self.H)
        if k == 'ts':
            return self.Ts
        if k == 'frequencyunit':
            return Char.of(self.unit)
        if k == 'timeunit':
            return Char.of('seconds')
        for key in ('InputName', 'OutputName', 'Name'):
            if key.lower() == k:
                v = self.names[key]
                return Cell.of_list([Char.of(x) for x in v], (len(v), 1)) if isinstance(v, list) else Char.of(v)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'frd'.")

    def setprop(self, name, value):
        k = name.lower()
        if k == 'frequency':
            w = np.asarray(darr(value), float).reshape(-1)
            if w.size != self.w.size:
                raise err('Control:frd:size', 'Frequency must have one value for each response.', 'frd')
            self.w = w
            return
        if k == 'responsedata':
            self.H = _resp_array(value, self.w.size)
            return
        if k == 'frequencyunit':
            u = py_str(value)
            if u not in ('rad/TimeUnit', 'rad/s', 'Hz'):
                raise err('Control:frd:unit', "FrequencyUnit is 'rad/TimeUnit', 'rad/s' or 'Hz' here.", 'frd')
            self.unit = u
            return
        if k == 'ts':
            self.Ts = float(num(value))
            return
        for key in ('InputName', 'OutputName', 'Name'):
            if key.lower() == k:
                self.names[key] = py_str(value) if key == 'Name' else ([py_str(value)] if isinstance(value, Char) else [str(x) for x in text_list(value)])
                return
        raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class 'frd'.")

    def propnames(self):
        return ['Frequency', 'ResponseData', 'FrequencyUnit', 'Ts', 'TimeUnit', 'InputName', 'OutputName', 'Name']

    def display_lines(self):
        ny, nu, nf = self.H.shape
        lines = []
        u = 'Hz' if self.unit == 'Hz' else 'rad/s'
        if (ny, nu) == (1, 1):
            lines += [f'      Frequency({u})        Response', '      ' + '-' * 14 + '        ' + '-' * 8]
            for k in range(min(nf, 12)):
                h = self.H[0, 0, k]
                lines.append(f'  {self.w[k]:16.4g}   {h.real:12.4g} {"+" if h.imag >= 0 else "-"} {abs(h.imag):.4g}i')
            if nf > 12:
                lines.append(f'  ... ({nf - 12} more)')
            lines.append('')
        lines.append(f'  {"Continuous" if self.Ts == 0 else "Discrete"}-time frequency response with {ny} output{"s" if ny != 1 else ""}, '
                     f'{nu} input{"s" if nu != 1 else ""} and {nf} frequency point{"s" if nf != 1 else ""}.')
        return lines


def _resp_array(v, nf):
    H = np.asarray(darr(v), complex)
    if H.ndim == 2 and min(H.shape) == 1 and H.size == nf:
        return H.reshape(1, 1, nf)
    if H.ndim == 2 and nf == 1:
        return H.reshape(H.shape + (1,))
    if H.ndim != 3 or H.shape[2] != nf:
        raise err('Control:frd:size', 'The response must be ny-by-nu-by-numel(freq) (a vector for one input and one output).', 'frd')
    return H


@bi('frd')
def frd(nargout, *args):
    """sys = frd(response, freq), frd(response, freq, Ts), frd(sys, freq): a model given by its frequency response (ny-by-nu-by-nf, or a vector) at the frequencies freq (rad/s; 'FrequencyUnit', 'Hz' for hertz), or a model's response at them."""
    nargchk(args, 2, 7, 'frd')
    rest = list(args)
    unit = 'rad/TimeUnit'
    k = 0
    while k < len(rest) - 1:
        if is_str(rest[k]) and py_str(rest[k]).lower() == 'frequencyunit':
            unit = py_str(rest[k + 1])
            del rest[k:k + 2]
            continue
        k += 1
    if unit not in ('rad/TimeUnit', 'rad/s', 'Hz'):
        raise err('Control:frd:unit', "FrequencyUnit is 'rad/TimeUnit', 'rad/s' or 'Hz' here.", 'frd')
    w = np.asarray(darr(rest[1]), float).reshape(-1)
    if isinstance(rest[0], K.LTI):
        s = rest[0]
        wr = w * 2 * np.pi if unit == 'Hz' else w
        H = np.moveaxis(s.resp(K._jw(s, wr)), 0, -1)
        o = FRD(H, w, s.Ts, unit)
        o.names['InputName'], o.names['OutputName'] = list(s.names['InputName']), list(s.names['OutputName'])
        return o
    Ts = float(num(rest[2])) if len(rest) > 2 else 0.0
    return FRD(_resp_array(rest[0], w.size), w, Ts, unit)


@bi('frdata', nout=3)
def frdata(nargout, *args):
    """[response, freq, Ts] = frdata(sys), frdata(sys, 'v') (the response of a one-input, one-output model as a column)."""
    nargchk(args, 1, 2, 'frdata')
    s = args[0]
    if not isinstance(s, FRD):
        raise err('Control:frdata:model', 'frdata takes an frd model.', 'frdata')
    H = s.H
    if len(args) > 1 and py_str(args[1]).lower() == 'v' and s.shape == (1, 1):
        H = H.reshape(-1, 1)
    return _outs(nargout, out(H), out(s.w.reshape(-1, 1)), s.Ts)


def _frd_of(x, like):
    """x as frequency-response data at like's frequencies."""
    if isinstance(x, FRD):
        if x.w.size != like.w.size or not np.allclose(x.rad(), like.rad()):
            raise err('Control:frd:frequency', 'frd models are combined at the same frequencies.', 'frd')
        return x.H
    if isinstance(x, K.LTI):
        return np.moveaxis(x.resp(K._jw(x, like.rad())), 0, -1)
    a = np.atleast_2d(np.asarray(darr(x), complex))
    return np.repeat(a[:, :, None], like.w.size, axis=2)


def _frd_like(H, like):
    o = FRD(H, like.w.copy(), like.Ts, like.unit)
    return o


def _each(Hs, f):
    """f applied at each frequency to the matrices Hs[k][:, :, i]."""
    nf = Hs[0].shape[2]
    res = [f(*[H[:, :, i] for H in Hs]) for i in range(nf)]
    return np.stack(res, axis=2)


def _frd_ops(op, *xs):
    like = next(x for x in xs if isinstance(x, FRD))
    if op in ('plus', 'minus'):
        a, b = (_frd_of(x, like) for x in xs)
        if a.shape[:2] != b.shape[:2]:
            if a.shape[:2] == (1, 1):
                a = np.broadcast_to(a, b.shape)
            elif b.shape[:2] == (1, 1):
                b = np.broadcast_to(b, a.shape)
            else:
                raise err('Control:plus', 'The models have different numbers of inputs and outputs.', 'plus')
        return _frd_like(a + b if op == 'plus' else a - b, like)
    if op == 'uminus':
        return _frd_like(-xs[0].H, like)
    if op == 'uplus':
        return xs[0]
    if op in ('mtimes', 'times'):
        a, b = (_frd_of(x, like) for x in xs)
        if a.shape[:2] == (1, 1) or b.shape[:2] == (1, 1):
            return _frd_like(a * b, like)
        if a.shape[1] != b.shape[0]:
            raise err('Control:mtimes', 'The inner dimensions do not agree.', 'mtimes')
        return _frd_like(_each([a, b], lambda p, q: p @ q), like)
    if op in ('mrdivide', 'rdivide'):
        a, b = (_frd_of(x, like) for x in xs)
        if b.shape[:2] == (1, 1):
            return _frd_like(a / b, like)
        return _frd_like(_each([a, b], lambda p, q: p @ np.linalg.inv(q)), like)
    if op in ('mldivide', 'ldivide'):
        a, b = (_frd_of(x, like) for x in xs)
        if a.shape[:2] == (1, 1):
            return _frd_like(b / a, like)
        return _frd_like(_each([a, b], lambda p, q: np.linalg.solve(p, q)), like)
    if op in ('transpose', 'ctranspose'):
        H = np.swapaxes(xs[0].H, 0, 1)
        return _frd_like(np.conj(H) if op == 'ctranspose' else H, like)
    if op in ('hcat', 'vcat'):
        parts = [_frd_of(x, like) for x in xs if not (isinstance(x, np.ndarray) and x.size == 0)]
        return _frd_like(np.concatenate(parts, axis=1 if op == 'hcat' else 0), like)
    raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for frd models.")


def _install():
    from ..ops import OBJ_OPS
    OBJ_OPS[FRD] = _frd_ops


_install()


def _wrap(name, handler):
    """name's builtin, with handler taking the call when an argument is an frd model."""
    info = REG.get(name)
    if info is None:
        return
    orig, ws, aw = info.fn, info.ws, info.aw

    def f(*a):
        args = a[2:] if ws else a[1:]
        if any(isinstance(x, FRD) for x in args):
            return handler(a[1] if ws else a[0], *args)
        return orig(*a)
    if aw:
        async def g(*a):
            args = a[2:] if ws else a[1:]
            if any(isinstance(x, FRD) for x in args):
                return handler(a[1] if ws else a[0], *args)
            return await orig(*a)
        info.fn = g
    else:
        info.fn = f


def _frd_feedback(nargout, *args):
    G, H = args[0], args[1]
    like = G if isinstance(G, FRD) else H
    sign = float(num(args[2])) if len(args) > 2 and not is_str(args[2]) else -1.0
    g, h = _frd_of(G, like), _frd_of(H, like)
    ny = g.shape[0]
    return _frd_like(_each([g, h], lambda p, q: np.linalg.solve(np.eye(ny) - sign * p @ q, p)), like)


def _frd_freqresp(nargout, *args):
    s = args[0]
    if len(args) > 1:
        w = np.asarray(darr(args[1]), float).reshape(-1)
        idx = [int(np.argmin(np.abs(s.w - v))) for v in w]
        if any(abs(s.w[i] - v) > 1e-9 * max(1.0, abs(v)) for i, v in zip(idx, w)):
            raise err('Control:freqresp:frd', 'An frd model has a response only at its own frequencies.', 'freqresp')
        H, w = s.H[:, :, idx], s.w[idx]
    else:
        H, w = s.H, s.w
    return _outs(nargout, out(H if H.shape[2] > 1 else H[:, :, 0]), out(w.reshape(-1, 1)))


def _draw_mag(entries, phase):
    """Magnitude (dB) and, with phase, phase plots over log frequency for each (w, H, color) entry."""
    from ..graphics_base import Line
    ax1 = R._builtin('subplot', 2.0, 1.0, 1.0) if phase else R._builtin('gca')
    ax2 = R._builtin('subplot', 2.0, 1.0, 2.0) if phase else None
    for w, H in entries:
        col = ax1.next_color()
        if ax2 is not None:
            ax2.next_color()
        for i in range(H.shape[1]):
            for j in range(H.shape[2]):
                pairs = [(ax1, 20 * np.log10(np.maximum(np.abs(H[:, i, j]), 1e-300)))]
                if ax2 is not None:
                    pairs.append((ax2, np.degrees(np.unwrap(np.angle(H[:, i, j])))))
                for ax, vals in pairs:
                    L = Line(ax)
                    L.props['XData'], L.props['YData'] = w.reshape(1, -1), vals.reshape(1, -1)
                    L.props['Color'] = col
    axes = [(ax1, 'Magnitude (dB)')] + ([(ax2, 'Phase (deg)')] if ax2 is not None else [])
    for ax, yl in axes:
        ax.set_value('XScale', Char.of('log'))
        R._builtin('ylabel', ax, Char.of(yl))
        R._builtin('grid', ax, Char.of('on'))
        ax.touch()
    R._builtin('title', ax1, Char.of('Bode Diagram'))
    R._builtin('xlabel', ax2 if ax2 is not None else ax1, Char.of('Frequency (rad/s)'))
    return None


def _models_w(args, fn):
    syss, rest = [], list(args)
    while rest and isinstance(rest[0], (K.LTI, FRD)):
        syss.append(rest.pop(0))
        if rest and is_str(rest[0]):
            rest.pop(0)
    if not syss:
        raise err(f'Control:{fn}:model', f'{fn} takes a model.', fn)
    w = None
    if rest and isinstance(rest[0], Cell):
        lo, hi = (float(num(x)) for x in rest[0].a.reshape(-1))
        w = np.logspace(math.log10(lo), math.log10(hi), 400)
    elif rest and numel(rest[0]):
        w = np.asarray(darr(rest[0]), float).reshape(-1)
    lti = [s for s in syss if isinstance(s, K.LTI)]
    if w is None:
        frds = [s for s in syss if isinstance(s, FRD)]
        w = frds[0].rad() if frds and not lti else K._freq_grid(lti) if lti else frds[0].rad()
    entries = []
    for s in syss:
        if isinstance(s, FRD):
            entries.append((s.rad(), np.moveaxis(s.H, 2, 0)))
        else:
            entries.append((w, s.resp(K._jw(s, w))))
    return syss, entries


def _frd_bode(nargout, *args):
    syss, entries = _models_w(args, 'bode')
    if nargout:
        w, H = entries[0]
        mag = np.moveaxis(np.abs(H), 0, -1)
        ph = np.moveaxis(np.degrees(np.unwrap(np.angle(H), axis=0)), 0, -1)
        return _outs(nargout, out(mag), out(ph), out(w.reshape(-1, 1)))
    return _draw_mag(entries, True)


_wrap('feedback', _frd_feedback)
_wrap('freqresp', _frd_freqresp)
_wrap('bode', _frd_bode)
_wrap('bodeplot', lambda nargout, *args: _frd_bode(0, *args))


@bi('bodemag')
def bodemag(nargout, *args):
    """bodemag(sys), bodemag(sys, w), bodemag(sys1, sys2, ..., w): the gain alone (dB) over frequency (rad/s), drawn; models or frd models."""
    nargchk(args, 1, None, 'bodemag')
    _, entries = _models_w(args, 'bodemag')
    return _draw_mag(entries, False)


# ---- responses --------------------------------------------------------------------------------------------------------------------------

@bi('lsiminfo')
def lsiminfo(nargout, *args):
    """S = lsiminfo(y, t, yfinal, 'SettlingTimeThreshold', 0.02): of a response: SettlingTime (after which |y - yfinal| stays within the threshold times its largest value), Min, MinTime, Max, MaxTime; yfinal the last value unless given; a column for each column of y."""
    nargchk(args, 1, 5, 'lsiminfo')
    rest, thr = list(args), 0.02
    for k in range(len(rest) - 1):
        if is_str(rest[k]) and py_str(rest[k]).lower() == 'settlingtimethreshold':
            thr = float(num(rest[k + 1]))
            del rest[k:k + 2]
            break
    Y = np.asarray(darr(rest[0]), float)
    Y = Y.reshape(-1, 1) if Y.ndim == 1 or min(Y.shape) == 1 else Y
    t = np.asarray(darr(rest[1]), float).reshape(-1) if len(rest) > 1 and numel(rest[1]) else np.arange(Y.shape[0], dtype=float)
    yf = np.asarray(darr(rest[2]), float).reshape(-1) if len(rest) > 2 and numel(rest[2]) else Y[-1]
    res = []
    for j in range(Y.shape[1]):
        y = Y[:, j]
        f = yf[min(j, yf.size - 1)]
        e = np.abs(y - f)
        big = e.max()
        outside = np.flatnonzero(e > thr * big) if big > 0 else np.zeros(0, int)
        if not outside.size:
            st = t[0]
        elif outside[-1] == y.size - 1:
            st = math.nan
        else:
            k = outside[-1]
            st = t[k] + (t[k + 1] - t[k]) * (e[k] - thr * big) / max(e[k] - e[k + 1], 1e-300)
        i, k = int(np.argmin(y)), int(np.argmax(y))
        res.append({'SettlingTime': float(st), 'Min': float(y[i]), 'MinTime': float(t[i]), 'Max': float(y[k]), 'MaxTime': float(t[k])})
    if len(res) == 1:
        return Struct.scalar(res[0])
    S = Struct((len(res), 1), {key: np.empty((len(res), 1), object) for key in res[0]})
    for j, r in enumerate(res):
        for key, v in r.items():
            S.f[key][j, 0] = v
    return S


# ---- interconnections ---------------------------------------------------------------------------------------------------------------------

def _ss_of(s):
    if not isinstance(s, K.LTI):
        s = K._gain(np.atleast_2d(np.asarray(darr(s), float)), 0.0, 'ss')
    if np.any(s.total_delay()):
        raise err('Control:connect:delay', 'Models with delays are joined after pade here.', 'connect')
    return s


@bi('append')
def append(nargout, *args):
    """sys = append(sys1, sys2, ...): the models side by side, unconnected: their inputs and outputs one after another, a block-diagonal model."""
    nargchk(args, 1, None, 'append')
    from scipy.linalg import block_diag
    syss = [_ss_of(s) for s in args]
    Ts = next((s.Ts for s in syss if s.ss_data()[0].shape[0]), syss[0].Ts)
    parts = [s.ss_data() for s in syss]
    sys = K.LTI('ss', (block_diag(*[p[0] for p in parts]), block_diag(*[p[1] for p in parts]), block_diag(*[p[2] for p in parts]),
                       block_diag(*[p[3] for p in parts])), Ts)
    sys.names['InputName'] = [n for s in syss for n in s.names['InputName']]
    sys.names['OutputName'] = [n for s in syss for n in s.names['OutputName']]
    kind = K._kind_of(*[s for s in args if isinstance(s, K.LTI)])
    return sys.to(kind) if kind != 'ss' else sys


@bi('sumblk')
def sumblk(nargout, *args):
    """S = sumblk('e = r - y'), sumblk('e = r - y', n): a summing junction, a static model whose input and output names are the signal names (each name the n signals name1 ... namen when n > 1)."""
    nargchk(args, 1, 2, 'sumblk')
    text = py_str(args[0]).replace(' ', '')
    n = int(num(args[1])) if len(args) > 1 else 1
    if text.count('=') != 1:
        raise err('Control:sumblk:formula', "The formula is 'out = in1 + in2 - in3 ...'.", 'sumblk')
    lhs, rhs = text.split('=')
    import re
    terms = re.findall(r'([+-]?)([A-Za-z_][A-Za-z0-9_.()]*)', rhs)
    if not lhs or not terms or ''.join(s + v for s, v in terms) != rhs.lstrip('+'):
        raise err('Control:sumblk:formula', "The formula is 'out = in1 + in2 - in3 ...'.", 'sumblk')
    D = np.hstack([(-1.0 if s == '-' else 1.0) * np.eye(n) for s, _ in terms])
    sys = K._gain(D, 0.0, 'tf')

    def names(base):
        return [base] if n == 1 else [f'{base}({i + 1})' for i in range(n)]
    sys.names['OutputName'] = names(lhs)
    sys.names['InputName'] = [x for _, v in terms for x in names(v)]
    return sys


def _close(sys, M, N, S):
    """The appended model with its inputs u = M*y + N*r and outputs z = S*y (y its outputs, r the new inputs)."""
    A, B, C, D = sys.ss_data()
    m = B.shape[1]
    F = np.eye(m) - M @ D
    try:
        Fi = np.linalg.inv(F)
    except np.linalg.LinAlgError:
        raise err('Control:connect:algebraic', 'The interconnection has an algebraic loop with no solution.', 'connect') from None
    Ac = A + B @ Fi @ M @ C
    Bc = B @ Fi @ N
    Cc = S @ (C + D @ Fi @ M @ C)
    Dc = S @ D @ Fi @ N
    return K.LTI('ss', (Ac, Bc, Cc, Dc), sys.Ts)


@bi('connect')
def connect(nargout, *args):
    """sys = connect(sys1, sys2, ..., inputs, outputs): models joined by their signal names: an input is driven by the output of the same name (sumblk for sums), inputs and outputs (names, text or a cell) are the result's; sys = connect(blksys, Q, inputs, outputs): an appended model joined by the rows of Q ([input k, outputs feeding it, a minus sign for negative feedback]), inputs and outputs by index."""
    nargchk(args, 3, None, 'connect')
    models = [a for a in args if isinstance(a, K.LTI)]
    rest = [a for a in args if not isinstance(a, K.LTI)]
    if len(models) == 1 and len(rest) == 3 and not is_str(rest[1]) and not isinstance(rest[1], Cell):
        blk = _ss_of(models[0])
        Q = np.atleast_2d(np.asarray(darr(rest[0]), float))
        ins = np.asarray(darr(rest[1]), float).reshape(-1).astype(int)
        outs = np.asarray(darr(rest[2]), float).reshape(-1).astype(int)
        ny, nu = blk.shape
        M = np.zeros((nu, ny))
        for row in Q:
            if row.size == 0 or row[0] == 0:
                continue
            i = int(row[0]) - 1
            for v in row[1:]:
                if v != 0:
                    M[i, abs(int(v)) - 1] += math.copysign(1.0, v)
        N = np.zeros((nu, ins.size))
        N[ins - 1, np.arange(ins.size)] = 1.0
        S = np.zeros((outs.size, ny))
        S[np.arange(outs.size), outs - 1] = 1.0
        return _close(blk, M, N, S)
    if len(rest) != 2:
        raise err('Control:connect:args', 'connect(sys1, sys2, ..., inputs, outputs): the input and output names come last.', 'connect')
    names_in = [py_str(rest[0])] if isinstance(rest[0], Char) else [str(x) for x in text_list(rest[0])]
    names_out = [py_str(rest[1])] if isinstance(rest[1], Char) else [str(x) for x in text_list(rest[1])]
    blk = append(1, *models)
    blk = _ss_of(blk.to('ss') if blk.kind != 'ss' else blk)
    yn, un = blk.names['OutputName'], blk.names['InputName']
    if any(not n for n in yn + un):
        raise err('Control:connect:names', 'Every input and output of the models needs a name (InputName, OutputName) to be joined by name.', 'connect')
    ny, nu = len(yn), len(un)
    M = np.zeros((nu, ny))
    N = np.zeros((nu, len(names_in)))
    for i, u in enumerate(un):
        drive = [k for k, y in enumerate(yn) if y == u]
        if len(drive) > 1:
            raise err('Control:connect:names', f"Two outputs are named '{u}'.", 'connect')
        if drive:
            M[i, drive[0]] = 1.0
        elif u in names_in:
            N[i, names_in.index(u)] = 1.0
    for j, nm in enumerate(names_in):
        if not N[:, j].any():
            raise err('Control:connect:names', f"No input of the models is named '{nm}'.", 'connect')
    S = np.zeros((len(names_out), ny))
    for j, nm in enumerate(names_out):
        hit = [k for k, y in enumerate(yn) if y == nm]
        if not hit:
            raise err('Control:connect:names', f"No output of the models is named '{nm}'.", 'connect')
        S[j, hit[0]] = 1.0
    sys = _close(blk, M, N, S)
    sys.names['InputName'], sys.names['OutputName'] = list(names_in), list(names_out)
    return sys


# ---- sample times, staircase forms -------------------------------------------------------------------------------------------------------

@bi('d2d')
def d2d(nargout, *args):
    """sys2 = d2d(sys1, Ts), d2d(sys1, Ts, method): a discrete model resampled at Ts: through the continuous model 'zoh' (unless given) or 'tustin' gives."""
    nargchk(args, 2, 3, 'd2d')
    s = K._sys(args[0], 'd2d')
    if s.Ts <= 0:
        raise err('Control:d2d', 'd2d takes a discrete-time model with a sample time.', 'd2d')
    method = py_str(args[2]).lower() if len(args) > 2 else 'zoh'
    if method not in ('zoh', 'tustin'):
        raise err('Control:d2d:method', "The method is 'zoh' or 'tustin'.", 'd2d')
    c = REG['d2c'].fn(1, s, Char.of(method))
    return REG['c2d'].fn(1, c, float(num(args[1])), Char.of(method))


def _staircase(A, B, C, tol):
    """(Abar, Bbar, Cbar, T, k): T orthogonal, Abar = T*A*T', the uncontrollable part in the top left (Bbar's top rows zero)."""
    n = A.shape[0]
    T = np.eye(n)
    k = np.zeros(n)
    Aw, Bw = A.copy(), B.copy()
    top = n                     # the leading block still to be split: rows 0 .. top-1
    j = 0
    while top > 0:
        Bj = Bw[:top] if j == 0 else Aw[:top, top:top + int(k[j - 1])]
        if Bj.size == 0:
            break
        U, s, _ = np.linalg.svd(Bj)
        t = tol if tol is not None else max(Bj.shape) * (s[0] if s.size else 0) * np.finfo(float).eps
        r = int(np.sum(s > t))
        if r == 0:
            break
        P = np.hstack([U[:, r:], U[:, :r]])        # the range of Bj to the bottom
        Tj = np.eye(n)
        Tj[:top, :top] = P.T
        Aw = Tj @ Aw @ Tj.T
        Bw = Tj @ Bw
        T = Tj @ T
        top -= r
        k[j] = r
        j += 1
    Bw[:top] = 0.0
    return Aw, Bw, C @ T.T, T, k


def _tol(args, i):
    return float(num(args[i])) if len(args) > i and numel(args[i]) else None


@bi('ctrbf', nout=5)
def ctrbf(nargout, *args):
    """[Abar, Bbar, Cbar, T, k] = ctrbf(A, B, C, tol): the controllability staircase form: Abar = T*A*T', Bbar = T*B, Cbar = C*T', the uncontrollable states first ([Auc 0; A21 Ac], Bbar = [0; Bc]); sum(k) is the number of controllable states."""
    nargchk(args, 3, 4, 'ctrbf')
    A, B, C = _mat(args[0], 'ctrbf', 'A'), _mat(args[1], 'ctrbf', 'B'), _mat(args[2], 'ctrbf', 'C')
    Ab, Bb, Cb, T, k = _staircase(A, B, C, _tol(args, 3))
    return _outs(nargout, out(Ab), out(Bb), out(Cb), out(T), out(k.reshape(1, -1)))


@bi('obsvf', nout=5)
def obsvf(nargout, *args):
    """[Abar, Bbar, Cbar, T, k] = obsvf(A, B, C, tol): the observability staircase form: Abar = T*A*T', the unobservable states first ([Ano A12; 0 Ao], Cbar = [0 Co]); sum(k) is the number of observable states."""
    nargchk(args, 3, 4, 'obsvf')
    A, B, C = _mat(args[0], 'obsvf', 'A'), _mat(args[1], 'obsvf', 'B'), _mat(args[2], 'obsvf', 'C')
    Aa, Ba, Ca, T, k = _staircase(A.T, C.T, B.T, _tol(args, 3))
    Ca_ = Ba.T.copy()
    return _outs(nargout, out(Aa.T), out(Ca.T), out(Ca_), out(T), out(k.reshape(1, -1)))


@bi('lqi', nout=3)
def lqi(nargout, *args):
    """[K, S, e] = lqi(sys, Q, R, N): the LQ regulator with integral action: the state feedback u = -K*[x; xi] for the plant with the integrators xi' = r - y (in discrete time xi[k+1] = xi[k] + Ts*(r[k] - y[k])) appended, by lqr."""
    nargchk(args, 3, 4, 'lqi')
    s = K._sys(args[0], 'lqi')
    A, B, C, D = s.ss_data()
    n, m, p = A.shape[0], B.shape[1], C.shape[0]
    if s.Ts == 0:
        Aa = np.block([[A, np.zeros((n, p))], [-C, np.zeros((p, p))]])
        Ba = np.vstack([B, -D])
    else:
        Ts = s.Ts if s.Ts > 0 else 1.0
        Aa = np.block([[A, np.zeros((n, p))], [-Ts * C, np.eye(p)]])
        Ba = np.vstack([B, -Ts * D])
    aug = K.LTI('ss', (Aa, Ba, np.eye(n + p), np.zeros((n + p, m))), s.Ts)
    rest = [args[1], args[2]] + ([args[3]] if len(args) > 3 else [])
    return REG['lqr'].fn(nargout if nargout else 1, aug, *rest)


# ---- pidtune -----------------------------------------------------------------------------------------------------------------------------

@bi('pidtuneOptions')
def pidtuneOptions(nargout, *args):
    """opts = pidtuneOptions('PhaseMargin', 60, 'DesignFocus', 'balanced'): options for pidtune."""
    d = {'PhaseMargin': 60.0, 'DesignFocus': Char.of('balanced'), 'NumUnstablePoles': 0.0}
    for k in range(0, len(args) - 1, 2):
        key = next((n for n in d if n.lower() == py_str(args[k]).lower()), None)
        if key is None:
            raise err('Control:pidtuneOptions:option', f"'{py_str(args[k])}' is not an option of pidtune.", 'pidtuneOptions')
        d[key] = float(num(args[k + 1])) if key != 'DesignFocus' else Char.of(py_str(args[k + 1]))
    return Struct.scalar(d)


def _pid_at(kind, c, w, ratio=4.0):
    """Gains making C(jw) = c, or None: P (|c| alone), I, PI, PD, PID (Ti = ratio*Td); at the crossover pidtune picks,
    PI has Ki/Kp = w/3, PD Kd*w = Kp, PID w*Td = 1."""
    a, b = c.real, c.imag
    if kind == 'P':
        return (abs(c), 0.0, 0.0)
    if kind == 'I':
        return (0.0, abs(c) * w, 0.0) if b < 0 else None
    if kind == 'PI':
        return (a, -b * w, 0.0) if a > 0 and b < 0 else None
    if kind == 'PD':
        return (a, 0.0, b / w) if a > 0 and b > 0 else None
    # PID with Ki = Kp/Ti, Kd = Kp*Td, Ti = ratio*Td: Kp*(1 + j*(w*Td - 1/(ratio*Td*w))) = c
    if a <= 0:
        return None
    q = b / a                               # = w*Td - 1/(ratio*w*Td)
    x = (q + math.sqrt(q * q + 4 / ratio)) / 2      # x = w*Td > 0
    Td = x / w
    return (a, a / (ratio * Td), a * Td)


@bi('pidtune', nout=2)
def pidtune(nargout, *args):
    """[C, info] = pidtune(sys, type, wc, opts): a PID controller of type 'P', 'I', 'PI' (default), 'PD', 'PID', 'PDF' or 'PIDF' for a plant with one input and one output, placing the crossover of C*sys at wc with the phase margin opts.PhaseMargin (60 degrees); without wc, the crossover where the plant's phase leaves that margin with the controller's own phase (PI: Ki/Kp = wc/3; PD: Kd*wc = Kp; PID: Ti = 4*Td, wc*Td = 1), or else the largest crossover on a grid giving a stable loop. PyLAB's own design (see Help)."""
    nargchk(args, 1, 4, 'pidtune')
    G = K._sys(args[0], 'pidtune')
    if G.shape != (1, 1):
        raise err('Control:pidtune:siso', 'pidtune takes a plant with one input and one output here.', 'pidtune')
    kind = py_str(args[1]).upper() if len(args) > 1 and is_str(args[1]) else 'PI'
    if kind not in ('P', 'I', 'PI', 'PD', 'PID', 'PDF', 'PIDF'):
        raise err('Control:pidtune:type', "The type is 'P', 'I', 'PI', 'PD', 'PID', 'PDF' or 'PIDF'.", 'pidtune')
    nums = [a for a in args[1:] if not is_str(a) and not isinstance(a, Struct)]
    opts = next((a for a in args[1:] if isinstance(a, Struct)), None)
    pm = float(num(opts.get1('PhaseMargin'))) if opts is not None and 'PhaseMargin' in opts.keys else 60.0
    filt = kind.endswith('F')
    base = kind[:-1] if filt else kind
    target = np.exp(1j * np.radians(-180 + pm))

    def make(w):
        g = G.resp(K._jw(G, np.array([w])))[0, 0, 0]
        if abs(g) == 0 or not np.isfinite(g):
            return None
        c = target / g
        gains = _pid_at(base, c, w)
        if gains is None:
            return None
        Kp, Ki, Kd = gains
        Tf = Kd / Kp / 10 if filt and Kd > 0 and Kp > 0 else 0.0
        C = K._pid_lti(Kp, Ki, Kd, Tf, Ts=G.Ts)
        C.pid = {'Kp': Kp, 'Ki': Ki, 'Kd': Kd, 'Tf': Tf}
        L = K._mul(C, G)
        cl = REG['feedback'].fn(1, L, 1.0)
        poles = np.asarray(K._poles(cl), complex)
        stable = bool(np.all(poles.real < -1e-9)) if G.Ts == 0 else bool(np.all(np.abs(poles) < 1 - 1e-9))
        return C, stable
    if nums and numel(nums[0]):
        wc = float(num(nums[0]))
        got = make(wc)
        if got is None:
            raise err('Control:pidtune:wc', f'No {kind} controller gives that phase margin at crossover {wc:g} rad/s with positive gains.', 'pidtune')
        C, stable = got
    else:
        grid = K._freq_grid([G], 400)
        if G.Ts > 0:
            grid = grid[grid < np.pi / G.Ts * 0.9]
        # the controller's own phase at crossover, fixed by the type; the crossover where the plant's phase leaves the margin with it
        lead = {'P': 0.0, 'I': -90.0, 'PI': -math.degrees(math.atan(1 / 3)), 'PD': 45.0, 'PID': math.degrees(math.atan(0.75))}[base]
        ph = np.degrees(np.unwrap(np.angle(G.resp(K._jw(G, grid))[:, 0, 0])))
        level = -180 + pm - lead
        best = None
        cross = np.flatnonzero((ph[:-1] > level) & (ph[1:] <= level))
        if cross.size:
            i = cross[0]
            wc0 = float(np.exp(np.interp(level, [ph[i + 1], ph[i]], [np.log(grid[i + 1]), np.log(grid[i])])))
            got = make(wc0)
            if got is not None and got[1]:
                best = (wc0, got[0], True)
        if best is None:
            for w in grid:
                got = make(float(w))
                if got is not None and got[1]:
                    best = (float(w), got[0], True)
        if best is None:
            raise err('Control:pidtune:none', f'No {kind} controller on the frequency grid gives a stable loop with that phase margin.', 'pidtune')
        wc, C, stable = best
    L = K._mul(C, G)
    info = Struct.scalar({'Stable': bool(stable), 'CrossoverFrequency': float(wc), 'PhaseMargin': _margin_at(L, wc)})
    return _outs(nargout, C, info)


def _margin_at(L, wc):
    """180 + the phase of L at wc, in (-180, 180]."""
    h = L.resp(K._jw(L, np.array([wc])))[0, 0, 0]
    return float((math.degrees(math.atan2(h.imag, h.real)) + 360) % 360 - 180)
