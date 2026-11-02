"""Element-wise mathematics: roots, logarithms, trigonometry, rounding,
remainders, complex parts, number theory and the special functions.

A real argument outside a function's real domain gives a complex result
(sqrt(-1) is 0 + 1i, log(-1) is 0 + 3.1416i). Integer arguments keep their
class where the result is a whole number (abs, sign, round, mod); the
transcendental functions take double and single only.
"""
import cmath
import math
import itertools

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, sval, ival, num, is_str, bool_out,
                    like_class, check_real)
from ..values import (MError, Char, Cell, Struct, Str, FH, Obj, F64, C128, INT_TYPES, INT_RANGE, DTYPE_CLASS, class_of, shape_of,
                      numel, _2d, scalar_out, EMPTY)
from ..ops import finish, to_int_class, INT_CLASSES, align, check_bcast, round_half_away


def _float_arg(v, fn):
    """(numbers, class) for a function that takes floating point: double
    or single; char and logical count as double; integers are refused."""
    t = type(v)
    if t is float or t is complex:
        return v, 'double'
    if t is bool:
        return float(v), 'double'
    a = arr(v, fn)
    k = a.dtype.kind
    if k in 'iu':
        raise err('MATLAB:UndefinedFunction', f"Undefined function '{fn}' for input arguments of type '{DTYPE_CLASS[a.dtype]}'.", fn)
    if k == 'b' or a.dtype == np.uint16:
        return a.astype(F64), 'double'
    if a.dtype == np.float32 or a.dtype == np.complex64:
        return a, 'single'
    return a, 'double'


def _finish(r, klass):
    if klass == 'single':
        r = np.asarray(r)
        if r.dtype.kind == 'c':
            r = r.astype(np.complex64)
            if not np.any(r.imag):
                r = r.real.astype(np.float32)
        else:
            r = r.astype(np.float32)
        return _2d(r)
    return out(r)


def _elem(name, real_fn, cfn=None, domain=None, scalar=None):
    """An element-wise function: real_fn on numpy arrays; where domain(x)
    is false somewhere, cfn on the complex values instead."""
    def f(nargout, *args):
        nargchk(args, 1, 1, name)
        x = args[0]
        if type(x) is float and scalar is not None:
            try:
                return scalar(x)
            except (ValueError, OverflowError, ZeroDivisionError):
                pass
        a, klass = _float_arg(x, name)
        with np.errstate(all='ignore'):
            if np.iscomplexobj(a):
                r = (cfn or real_fn)(np.asarray(a))
            else:
                A = np.asarray(a, np.float32 if klass == 'single' else F64)
                if domain is not None and cfn is not None:
                    bad = ~domain(A) & ~np.isnan(A)
                    if np.any(bad):
                        r = cfn(A.astype(np.complex64 if klass == 'single' else C128))
                        return _finish(r, klass)
                r = real_fn(A)
        return _finish(r, klass)
    f.__name__ = name
    bi(name)(f)
    return f


# roots and logarithms
_elem('sqrt', np.sqrt, np.sqrt, lambda x: x >= 0, lambda x: math.sqrt(x) if x >= 0 else complex(0, math.sqrt(-x)))
_elem('exp', np.exp, np.exp, None, lambda x: math.exp(x) if x < 709 else math.inf)
_elem('expm1', np.expm1, None, None, math.expm1)
_elem('log', np.log, np.log, lambda x: x >= 0, lambda x: math.log(x) if x > 0 else (complex(math.log(-x), math.pi) if x < 0 else -math.inf))
_elem('log10', np.log10, np.log10, lambda x: x >= 0, lambda x: math.log10(x) if x > 0 else (complex(math.log10(-x), math.pi / math.log(10)) if x < 0 else -math.inf))
_elem('log1p', np.log1p, lambda z: np.log(1 + z), lambda x: x >= -1, None)
_elem('realsqrt', np.sqrt, None, None, None)


@bi('reallog')
def reallog(nargout, *args):
    a = darr(args[0])
    if np.any(a < 0):
        raise err('MATLAB:reallog:complexResult', 'Reallog produced complex result.', 'reallog')
    with np.errstate(all='ignore'):
        return out(np.log(a))


@bi('realpow')
def realpow(nargout, *args):
    from ..ops import power
    r = power(args[0], args[1])
    if type(r) is complex or (type(r) is np.ndarray and r.dtype.kind == 'c'):
        raise err('MATLAB:realpow:complexResult', 'Realpow produced complex result.', 'realpow')
    return r


@bi('log2', nout=2)
def log2(nargout, *args):
    nargchk(args, 1, 1, 'log2')
    a, klass = _float_arg(args[0], 'log2')
    A = np.asarray(a)
    if nargout >= 2:
        m, e = np.frexp(A.real if np.iscomplexobj(A) else A)
        return _finish(m, klass), _finish(e.astype(F64), klass)
    with np.errstate(all='ignore'):
        if not np.iscomplexobj(A) and np.any(A < 0):
            return _finish(np.log2(A.astype(C128)), klass)
        return _finish(np.log2(A), klass)


@bi('pow2')
def pow2(nargout, *args):
    if len(args) == 2:
        f = darr(args[0])
        e = darr(args[1])
        return out(np.ldexp(f, e.astype(int)) if np.all(e == np.round(e)) else f * 2.0 ** e)
    a, klass = _float_arg(args[0], 'pow2')
    with np.errstate(all='ignore'):
        return _finish(2.0 ** np.asarray(a), klass)


@bi('nextpow2')
def nextpow2(nargout, *args):
    a = np.abs(darr(args[0]))
    with np.errstate(all='ignore'):
        f, e = np.frexp(a)
        r = np.where(f == 0.5, e - 1, e).astype(F64)
        r = np.where(a == 0, 0.0, r)
        r = np.where(np.isinf(a), np.inf, r)
    return out(r)


@bi('nthroot')
def nthroot(nargout, *args):
    nargchk(args, 2, 2, 'nthroot')
    x = darr(args[0])
    n = darr(args[1])
    if np.iscomplexobj(x) or np.iscomplexobj(n):
        raise err('MATLAB:nthroot:ComplexInput', 'Both X and N must be real.', 'nthroot')
    x, n = align(x, n)
    check_bcast(x, n)
    if np.any((x < 0) & (np.mod(n, 2) != 1)):
        raise err('MATLAB:nthroot:NegXNotOddIntegerN', 'If X is negative, N must be an odd integer.', 'nthroot')
    with np.errstate(all='ignore'):
        r = np.sign(x) * np.abs(x) ** (1.0 / n)
        # one Newton step makes exact roots exact
        good = (r != 0) & np.isfinite(r) & np.isfinite(x)
        r2 = np.where(good, r - (r ** n - x) / (n * r ** (n - 1)), r)
        r = np.where(good, r2, r)
    return out(r)


@bi('hypot')
def hypot(nargout, *args):
    nargchk(args, 2, 2, 'hypot')
    a = darr(args[0])
    b = darr(args[1])
    a, b = align(a, b)
    check_bcast(a, b)
    return out(np.hypot(np.abs(a), np.abs(b)))


# trigonometry
_elem('sin', np.sin, None, None, math.sin)
_elem('cos', np.cos, None, None, math.cos)
_elem('tan', np.tan, None, None, math.tan)
_elem('sec', lambda x: 1 / np.cos(x), None, None, None)
_elem('csc', lambda x: 1 / np.sin(x), None, None, None)
_elem('cot', lambda x: 1 / np.tan(x), None, None, None)
_elem('asin', np.arcsin, np.arcsin, lambda x: np.abs(x) <= 1, None)
_elem('acos', np.arccos, np.arccos, lambda x: np.abs(x) <= 1, None)
_elem('atan', np.arctan, None, None, math.atan)
_elem('asec', lambda x: np.arccos(1 / x), lambda z: np.arccos(1 / z), lambda x: np.abs(x) >= 1, None)
_elem('acsc', lambda x: np.arcsin(1 / x), lambda z: np.arcsin(1 / z), lambda x: np.abs(x) >= 1, None)
_elem('acot', lambda x: np.arctan(1 / x), None, None, None)
_elem('sinh', np.sinh, None, None, None)
_elem('cosh', np.cosh, None, None, None)
_elem('tanh', np.tanh, None, None, math.tanh)
_elem('sech', lambda x: 1 / np.cosh(x), None, None, None)
_elem('csch', lambda x: 1 / np.sinh(x), None, None, None)
_elem('coth', lambda x: 1 / np.tanh(x), None, None, None)
_elem('asinh', np.arcsinh, None, None, math.asinh)
_elem('acosh', np.arccosh, np.arccosh, lambda x: x >= 1, None)
_elem('atanh', np.arctanh, np.arctanh, lambda x: np.abs(x) <= 1, None)
_elem('asech', lambda x: np.arccosh(1 / x), lambda z: np.arccosh(1 / z), lambda x: (x > 0) & (x <= 1), None)
_elem('acsch', lambda x: np.arcsinh(1 / x), None, None, None)
_elem('acoth', lambda x: np.arctanh(1 / x), lambda z: np.arctanh(1 / z), lambda x: np.abs(x) >= 1, None)


def _sind(x):
    # exact zeros at whole multiples of 180
    r = np.sin(np.deg2rad(np.mod(x, 360)))
    return np.where(np.mod(x, 180) == 0, 0.0, r)


def _cosd(x):
    r = np.cos(np.deg2rad(np.mod(x, 360)))
    return np.where(np.mod(x - 90, 180) == 0, 0.0, r)


def _tand(x):
    with np.errstate(all='ignore'):
        r = np.tan(np.deg2rad(np.mod(x, 360)))
        r = np.where(np.mod(x, 180) == 0, 0.0, r)
        r = np.where(np.mod(x - 90, 180) == 0, np.where(np.mod(x - 90, 360) == 0, np.inf, -np.inf), r)
        r = np.where(np.mod(x - 45, 180) == 0, 1.0, r)
        r = np.where(np.mod(x + 45, 180) == 0, -1.0, r)
    return r


_elem('sind', _sind, None, None, None)
_elem('cosd', _cosd, None, None, None)
_elem('tand', _tand, None, None, None)
_elem('secd', lambda x: 1 / _cosd(x), None, None, None)
_elem('cscd', lambda x: 1 / _sind(x), None, None, None)
_elem('cotd', lambda x: 1 / _tand(x), None, None, None)
_elem('asind', lambda x: np.rad2deg(np.arcsin(x)), lambda z: np.rad2deg(np.arcsin(z)), lambda x: np.abs(x) <= 1, None)
_elem('acosd', lambda x: np.rad2deg(np.arccos(x)), lambda z: np.rad2deg(np.arccos(z)), lambda x: np.abs(x) <= 1, None)
_elem('atand', lambda x: np.rad2deg(np.arctan(x)), None, None, None)
_elem('asecd', lambda x: np.rad2deg(np.arccos(1 / x)), lambda z: np.rad2deg(np.arccos(1 / z)), lambda x: np.abs(x) >= 1, None)
_elem('acscd', lambda x: np.rad2deg(np.arcsin(1 / x)), lambda z: np.rad2deg(np.arcsin(1 / z)), lambda x: np.abs(x) >= 1, None)
_elem('acotd', lambda x: np.rad2deg(np.arctan(1 / x)), None, None, None)
_elem('sinpi', lambda x: np.where(np.mod(x, 1) == 0, 0.0, np.sin(np.pi * np.mod(x, 2))), None, None, None)
_elem('cospi', lambda x: np.where(np.mod(x - 0.5, 1) == 0, 0.0, np.cos(np.pi * np.mod(x, 2))), None, None, None)
_elem('deg2rad', lambda x: x * (np.pi / 180), None, None, lambda x: x * (math.pi / 180))
_elem('rad2deg', lambda x: x * (180 / np.pi), None, None, lambda x: x * (180 / math.pi))


def _two(args, fn):
    a = darr(args[0], fn)
    b = darr(args[1], fn)
    a, b = align(a, b)
    check_bcast(a, b)
    return a, b


@bi('atan2')
def atan2(nargout, *args):
    nargchk(args, 2, 2, 'atan2')
    if type(args[0]) is float and type(args[1]) is float:
        return math.atan2(args[0], args[1])
    a, b = _two(args, 'atan2')
    if np.iscomplexobj(a) or np.iscomplexobj(b):
        raise err('MATLAB:atan2:complexArgument', 'Inputs must be real.', 'atan2')
    return out(np.arctan2(a, b))


@bi('atan2d')
def atan2d(nargout, *args):
    a, b = _two(args, 'atan2d')
    return out(np.rad2deg(np.arctan2(a, b)))


# ---- rounding, remainders -------------------------------------------------------------

def _round_like(name, fn, int_ok=True):
    def f(nargout, *args):
        x = args[0]
        if name == 'round' and len(args) > 1:
            return _round_digits(args)
        nargchk(args, 1, 1, name)
        t = type(x)
        if t is float:
            if x != x or abs(x) == math.inf:
                return x
            return float(fn(np.float64(x)))
        if t is bool:
            return float(x)
        a = arr(x, name)
        if a.dtype.kind in 'iub':
            return like_class(a, x) if a.dtype.kind != 'b' else out(a.astype(F64))
        if a.dtype == np.uint16 and t is Char:
            return out(a.astype(F64))
        with np.errstate(all='ignore'):
            if a.dtype.kind == 'c':
                r = fn(a.real) + 1j * fn(a.imag)
            else:
                r = fn(a)
        if a.dtype in (np.float32, np.complex64):
            return finish(r, 'single')
        return out(r)
    f.__name__ = name
    bi(name)(f)


def _round_half(x):
    t = np.trunc(x)
    frac = x - t
    return np.where(np.abs(frac) >= 0.5, t + np.sign(x), t)


_round_like('floor', np.floor)
_round_like('ceil', np.ceil)
_round_like('fix', np.trunc)
_round_like('round', _round_half)


def _round_digits(args):
    x = darr(args[0])
    n = ival(args[1], 'number of digits', 'round')
    kind = opt_str(args[2]).lower() if len(args) > 2 else 'decimals'
    with np.errstate(all='ignore'):
        if kind == 'significant':
            mag = np.where(x == 0, 0, np.floor(np.log10(np.abs(x))))
            digits = n - 1 - mag
            s = 10.0 ** digits
            r = _round_half(x * s) / s
        else:
            if n >= 0:
                s = 10.0 ** n
                r = _round_half(x * s) / s
            else:
                s = 10.0 ** (-n)
                r = _round_half(x / s) * s
        r = np.where(np.isfinite(x), r, x)
    return out(r)


def _intlike(a):
    return a.dtype.kind in 'iu'


def _modrem(args, name):
    nargchk(args, 2, 2, name)
    x, y = args
    if type(x) is float and type(y) is float:
        if y == 0:
            return x if name == 'mod' else math.nan
        if x != x or y != y or abs(x) == math.inf:
            return math.nan
        if abs(y) == math.inf:
            if name == 'rem':
                return x
            return x if (x == 0 or (x > 0) == (y > 0)) else y
        q = x / y
        rq = round(q)
        if abs(q - rq) <= 2.220446049250313e-16 * abs(q):
            n = rq
        else:
            n = math.floor(q) if name == 'mod' else math.trunc(q)
        r = x - n * y
        if name == 'mod' and r != 0 and (r < 0) != (y < 0):
            r += y
        return r if r != 0 else 0.0
    A = arr(x, name)
    B = arr(y, name)
    ca = class_of(x)
    cb = class_of(y)
    from ..ops import result_class
    klass = result_class('double' if ca in ('logical', 'char') else ca, 'double' if cb in ('logical', 'char') else cb, name)
    A, B = align(A, B)
    check_bcast(A, B)
    if klass in INT_CLASSES:
        a64 = np.asarray(A, F64)
        b64 = np.asarray(B, F64)
        a64 = round_half_away(a64)
        b64 = round_half_away(b64)
        with np.errstate(all='ignore'):
            if name == 'mod':
                r = np.where(b64 == 0, a64, a64 - np.floor(a64 / np.where(b64 == 0, 1, b64)) * b64)
            else:
                r = np.where(b64 == 0, a64, a64 - np.trunc(a64 / np.where(b64 == 0, 1, b64)) * b64)
        return finish(r, klass)
    A = np.asarray(A, F64)
    B = np.asarray(B, F64)
    with np.errstate(all='ignore'):
        q = A / B
        rq = np.round(q)
        near = np.abs(q - rq) <= 2.220446049250313e-16 * np.abs(q)
        n = np.where(near, rq, np.floor(q) if name == 'mod' else np.trunc(q))
        r = A - n * B
        if name == 'mod':
            r = np.where((r != 0) & ((r < 0) != (B < 0)), r + B, r)
            r = np.where(B == 0, A, r)
            r = np.where(np.isinf(B) & np.isfinite(A), np.where((A == 0) | ((A > 0) == (B > 0)), A, B), r)
        else:
            r = np.where(B == 0, np.nan, r)
            r = np.where(np.isinf(B) & np.isfinite(A), A, r)
        r = np.where(np.isinf(A), np.nan, r)
        r = np.where(r == 0, 0.0, r)
    return finish(r, klass)


@bi('mod')
def mod(nargout, *args):
    return _modrem(args, 'mod')


@bi('rem')
def rem(nargout, *args):
    return _modrem(args, 'rem')


@bi('idivide')
def idivide(nargout, *args):
    nargchk(args, 2, 3, 'idivide')
    kind = opt_str(args[2]).lower() if len(args) > 2 else 'fix'
    a, b = args[0], args[1]
    klass = class_of(a) if class_of(a) in INT_CLASSES else class_of(b)
    if klass not in INT_CLASSES:
        raise err('MATLAB:idivide:invalidInput', 'At least one input must be an integer type.', 'idivide')
    A = np.asarray(arr(a), F64)
    B = np.asarray(arr(b), F64)
    A, B = align(A, B)
    with np.errstate(all='ignore'):
        q = A / B
        fn = {'fix': np.trunc, 'floor': np.floor, 'ceil': np.ceil, 'round': _round_half}[kind]
        r = fn(q)
    return finish(r, klass)


# ---- bits ------------------------------------------------------------------------------------------

_UNSIGNED = {'int8': np.uint8, 'int16': np.uint16, 'int32': np.uint32, 'int64': np.uint64,
             'uint8': np.uint8, 'uint16': np.uint16, 'uint32': np.uint32, 'uint64': np.uint64}


def _bit_args(vals, fn, assumed=None):
    """The integer class bit functions work in, the class they give, and the
    inputs as arrays of the first: an integer input's class, or for doubles
    the assumed type (uint64 unless named), their values whole numbers in
    its range; the result is then double."""
    ints = {class_of(v) for v in vals} & set(INT_CLASSES)
    if len(ints) > 1:
        raise err(f'MATLAB:{fn}:mixedClasses', 'Integer inputs must be of the same class.', fn)
    if ints:
        klass = ints.pop()
        if assumed is not None and assumed.lower() != klass:
            raise err(f'MATLAB:{fn}:assumedtypeForIntegers', 'An assumed type is for double inputs only.', fn)
        result = klass
    else:
        klass = (assumed or 'uint64').lower()
        if klass not in INT_CLASSES:
            raise err(f'MATLAB:{fn}:badAssumedType', 'The assumed type must be the name of an integer class, such as uint8 or int64.', fn)
        result = 'double'
    dt = INT_TYPES[klass]
    lo, hi = INT_RANGE[klass]
    arrays = []
    for v in vals:
        a = arr(v)
        if a.dtype == dt:
            arrays.append(a)
            continue
        if a.dtype.kind == 'c':
            raise err(f'MATLAB:{fn}:complexInput', 'Inputs must be real.', fn)
        f = np.asarray(a, F64)
        if f.size and (not np.all(np.isfinite(f)) or np.any(f != np.floor(f)) or np.any(f < lo) or np.any(f >= float(hi) + 1.0)):
            raise err(f'MATLAB:{fn}:outOfRange', 'Double inputs must have integer values in the range of ASSUMEDTYPE.', fn)
        arrays.append(f.astype(np.int64 if lo < 0 else np.uint64).astype(dt))
    return klass, result, arrays


def _bit_out(r, result):
    return out(r if result != 'double' else r.astype(F64))


def _bcast(*arrays):
    """Arrays brought to one size, the language's way."""
    n = max(a.ndim for a in arrays)
    arrays = [a.reshape(a.shape + (1,) * (n - a.ndim)) for a in arrays]
    for a in arrays[1:]:
        check_bcast(arrays[0], a)
    try:
        return np.broadcast_arrays(*arrays)
    except ValueError:
        raise err('MATLAB:sizeDimensionsMustMatch', 'Arrays have incompatible sizes for this operation.')


def _bitwise(args, fn, op):
    nargchk(args, 2, 3, fn)
    klass, result, (a, b) = _bit_args(args[:2], fn, opt_str(args[2]) if len(args) > 2 else None)
    a, b = _bcast(a, b)
    return _bit_out(op(a, b), result)


@bi('bitand')
def bitand(nargout, *args):
    return _bitwise(args, 'bitand', np.bitwise_and)


@bi('bitor')
def bitor(nargout, *args):
    return _bitwise(args, 'bitor', np.bitwise_or)


@bi('bitxor')
def bitxor(nargout, *args):
    return _bitwise(args, 'bitxor', np.bitwise_xor)


def _bit_positions(bit, nbits, fn):
    b = np.asarray(arr(bit), F64)
    if b.size and (np.any(b != np.floor(b)) or np.any(b < 1) or np.any(b > nbits)):
        raise err(f'MATLAB:{fn}:outOfRange', f'Bit positions must be integers from 1 to {nbits}.', fn)
    return b


@bi('bitget')
def bitget(nargout, *args):
    nargchk(args, 2, 3, 'bitget')
    klass, result, (a,) = _bit_args(args[:1], 'bitget', opt_str(args[2]) if len(args) > 2 else None)
    ut = _UNSIGNED[klass]
    width = 8 * np.dtype(ut).itemsize
    b = _bit_positions(args[1], width, 'bitget')
    u, b = _bcast(np.ascontiguousarray(a).view(ut), b)
    r = (u >> (b - 1).astype(ut)) & ut(1)
    return _bit_out(r.astype(INT_TYPES[klass]), result)


@bi('bitset')
def bitset(nargout, *args):
    nargchk(args, 2, 4, 'bitset')
    rest = list(args[2:])
    assumed = opt_str(rest.pop()) if rest and opt_str(rest[-1]) is not None else None
    klass, result, (a,) = _bit_args(args[:1], 'bitset', assumed)
    ut = _UNSIGNED[klass]
    width = 8 * np.dtype(ut).itemsize
    b = _bit_positions(args[1], width, 'bitset')
    v = np.asarray(arr(rest[0]), F64) if rest else np.ones((1, 1))
    u, b, v = _bcast(np.ascontiguousarray(a).view(ut), b, v)
    mask = ut(1) << (b - 1).astype(ut)
    r = np.where(v != 0, u | mask, u & ~mask).astype(ut)
    return _bit_out(r.view(INT_TYPES[klass]), result)


@bi('bitshift')
def bitshift(nargout, *args):
    nargchk(args, 2, 3, 'bitshift')
    third = args[2] if len(args) > 2 else None
    assumed = opt_str(third) if third is not None else None
    klass, result, (a,) = _bit_args(args[:1], 'bitshift', assumed)
    ut = _UNSIGNED[klass]
    width = 8 * np.dtype(ut).itemsize
    k = np.asarray(arr(args[1]), F64)
    if k.size and np.any(k != np.floor(k)):
        raise err('MATLAB:bitshift:nonIntegerShift', 'The number of bits to shift must be an integer.', 'bitshift')
    a, k = _bcast(np.ascontiguousarray(a), k)
    with np.errstate(all='ignore'):
        u = a.view(ut)
        s = np.minimum(np.abs(k), width - 1).astype(ut)
        # left: the bit pattern moves up and what passes the top is gone;
        # right: down, a signed value's sign filling in (rounding to -Inf)
        down = (a >> s.astype(a.dtype)).view(ut) if a.dtype.kind == 'i' else u >> s
        r = np.where(k >= 0, u << s, down).astype(ut)
        gone = np.abs(k) >= width
        if gone.any():
            r = np.where(gone, np.where((k < 0) & (a < 0), ~ut(0), ut(0)), r).astype(ut)
    if third is not None and assumed is None and int(num(third)) < width:
        # the older form's third input: bits past the lowest n are dropped
        r = r & ut((1 << int(num(third))) - 1)
    return _bit_out(r.view(INT_TYPES[klass]), result)


@bi('bitcmp')
def bitcmp(nargout, *args):
    nargchk(args, 1, 2, 'bitcmp')
    second = args[1] if len(args) > 1 else None
    assumed = opt_str(second) if second is not None else None
    klass, result, (a,) = _bit_args(args[:1], 'bitcmp', assumed)
    if second is not None and assumed is None:
        # the older form: complement the lowest n bits
        n = int(num(second))
        ut = _UNSIGNED[klass]
        r = (np.ascontiguousarray(a).view(ut) ^ ut((1 << n) - 1)).view(INT_TYPES[klass])
        return _bit_out(r, result)
    return _bit_out(np.invert(a), result)


@bi('sign')
def sign(nargout, *args):
    nargchk(args, 1, 1, 'sign')
    x = args[0]
    if type(x) is float:
        return 1.0 if x > 0 else (-1.0 if x < 0 else (0.0 if x == 0 else math.nan))
    a = arr(x)
    if a.dtype.kind == 'c':
        with np.errstate(all='ignore'):
            r = np.where(a == 0, 0, a / np.abs(a))
        return out(r)
    if a.dtype.kind in 'iu':
        return like_class(np.sign(a), x)
    if a.dtype.kind == 'b' or a.dtype == np.uint16:
        return out(np.sign(a.astype(F64)))
    return like_class(np.sign(a), x)


@bi('abs')
def abs_(nargout, *args):
    nargchk(args, 1, 1, 'abs')
    x = args[0]
    t = type(x)
    if t is float:
        return abs(x)
    if t is complex:
        return abs(x)
    if t is bool:
        return float(x)
    a = arr(x, 'abs')
    if a.dtype.kind in 'iu':
        return finish(np.abs(a.astype(F64)), DTYPE_CLASS[a.dtype])
    if a.dtype.kind == 'b' or (t is Char):
        return out(np.abs(a.astype(F64)))
    r = np.abs(a)
    if a.dtype in (np.float32, np.complex64):
        return finish(r.astype(np.float32), 'single')
    return out(r)


# ---- complex numbers -------------------------------------------------------------------

@bi('real')
def real(nargout, *args):
    nargchk(args, 1, 1, 'real')
    x = args[0]
    if type(x) is float:
        return x
    if type(x) is complex:
        return x.real
    a = arr(x)
    if a.dtype.kind == 'c':
        return like_class(np.ascontiguousarray(a.real), x)
    return like_class(a.copy(), x) if type(x) is not Char else out(a.astype(F64))


@bi('imag')
def imag(nargout, *args):
    nargchk(args, 1, 1, 'imag')
    x = args[0]
    if type(x) is float:
        return 0.0
    if type(x) is complex:
        return x.imag
    a = arr(x)
    if a.dtype.kind == 'c':
        return like_class(np.ascontiguousarray(a.imag), x)
    return like_class(np.zeros(a.shape, a.dtype if a.dtype.kind in 'fiu' else F64), x) if type(x) is not Char else out(np.zeros(a.shape))


@bi('conj')
def conj(nargout, *args):
    nargchk(args, 1, 1, 'conj')
    x = args[0]
    if type(x) is complex:
        return x.conjugate()
    if type(x) is float:
        return x
    a = arr(x)
    return like_class(np.conj(a), x) if a.dtype.kind == 'c' else x


@bi('angle')
def angle(nargout, *args):
    nargchk(args, 1, 1, 'angle')
    a = darr(args[0])
    return out(np.angle(a))


@bi('complex')
def complex_(nargout, *args):
    nargchk(args, 1, 2, 'complex')
    a = darr(args[0])
    b = darr(args[1]) if len(args) > 1 else np.zeros_like(a)
    a, b = align(a, b)
    r = np.asarray(a, F64) + 1j * np.asarray(b, F64)
    r = _2d(np.asarray(r, C128))
    if r.size == 1:
        # complex() keeps a zero imaginary part: the value stays complex
        return r
    return r


@bi('isnan')
def isnan(nargout, *args):
    nargchk(args, 1, 1, 'isnan')
    x = args[0]
    if type(x) is float:
        return x != x
    if type(x) in (Cell, Struct):
        raise err('MATLAB:UndefinedFunction', f"Undefined function 'isnan' for input arguments of type '{class_of(x)}'.", 'isnan')
    if type(x) is Str:
        return out(np.vectorize(lambda s: s is None, otypes=[bool])(x.a))
    a = arr(x)
    return out(np.isnan(a) if a.dtype.kind in 'fc' else np.zeros(a.shape, bool))


@bi('ismissing')
def ismissing(nargout, *args):
    nargchk(args, 1, 1, 'ismissing')
    x = args[0]
    if type(x) is Str:
        return out(np.vectorize(lambda s: s is None, otypes=[bool])(x.a))
    if type(x) is Char:
        return out(x.a == 32)
    if type(x) is Cell:
        # a cell of text: the empty char vectors
        return out(np.vectorize(lambda v: type(v) is Char and v.a.size == 0, otypes=[bool])(x.a))
    if type(x) is Struct or isinstance(x, (FH, Obj)):
        raise err('MATLAB:UndefinedFunction', f"Undefined function 'ismissing' for input arguments of type '{class_of(x)}'.", 'ismissing')
    a = arr(x)
    return out(np.isnan(a) if a.dtype.kind in 'fc' else np.zeros(a.shape, bool))


@bi('isinf')
def isinf(nargout, *args):
    nargchk(args, 1, 1, 'isinf')
    x = args[0]
    if type(x) is float:
        return x in (math.inf, -math.inf)
    a = arr(x)
    return out(np.isinf(a) if a.dtype.kind in 'fc' else np.zeros(a.shape, bool))


@bi('isfinite')
def isfinite(nargout, *args):
    nargchk(args, 1, 1, 'isfinite')
    x = args[0]
    if type(x) is float:
        return math.isfinite(x)
    a = arr(x)
    return out(np.isfinite(a) if a.dtype.kind in 'fc' else np.ones(a.shape, bool))


@bi('cplxpair')
def cplxpair(nargout, *args):
    a = darr(args[0]).reshape(-1)
    re = a[np.abs(a.imag) <= 100 * np.finfo(float).eps * np.abs(a)]
    cx = a[np.abs(a.imag) > 100 * np.finfo(float).eps * np.abs(a)]
    neg = sorted([z for z in cx if z.imag < 0], key=lambda z: (z.real, z.imag))
    out_l = []
    for z in neg:
        out_l += [z, z.conjugate()]
    out_l += sorted(re.real)
    r = np.array(out_l, dtype=C128)
    return out(r.reshape(-1, 1) if args[0].shape[0] != 1 else r.reshape(1, -1))


@bi('unwrap')
def unwrap(nargout, *args):
    a = darr(args[0])
    tol = num(args[1]) if len(args) > 1 and numel(args[1]) else math.pi
    if a.ndim == 2 and a.shape[0] == 1:
        return out(np.unwrap(a, discont=tol, axis=1))
    return out(np.unwrap(a, discont=tol, axis=0))


# ---- number theory -----------------------------------------------------------------------

def _ints(v, fn):
    a = arr(v)
    if a.dtype.kind == 'f' and np.any(a != np.round(a)):
        raise err('MATLAB:' + fn + ':NonIntegerInput', f'Input arguments must contain only integer values.', fn)
    return a


@bi('gcd', nout=3)
def gcd(nargout, *args):
    nargchk(args, 2, 2, 'gcd')
    a = _ints(args[0], 'gcd').astype(np.int64)
    b = _ints(args[1], 'gcd').astype(np.int64)
    a, b = align(a, b)
    g = np.gcd(a, b)
    klass = class_of(args[0]) if class_of(args[0]) in INT_CLASSES else class_of(args[1]) if class_of(args[1]) in INT_CLASSES else 'double'
    if nargout <= 1:
        return finish(g.astype(F64), klass)
    # Bezout coefficients
    A, Bb = np.broadcast_arrays(a, b)
    U = np.zeros(A.shape)
    V = np.zeros(A.shape)
    for i in range(A.size):
        x, y = int(A.flat[i]), int(Bb.flat[i])
        old_r, r = x, y
        old_s, s = 1, 0
        old_t, t = 0, 1
        while r != 0:
            q = old_r // r
            old_r, r = r, old_r - q * r
            old_s, s = s, old_s - q * s
            old_t, t = t, old_t - q * t
        if old_r < 0:
            old_r, old_s, old_t = -old_r, -old_s, -old_t
        U.flat[i], V.flat[i] = old_s, old_t
    return (finish(g.astype(F64), klass), out(U), out(V))[:nargout]


@bi('lcm')
def lcm(nargout, *args):
    nargchk(args, 2, 2, 'lcm')
    a = _ints(args[0], 'lcm').astype(np.int64)
    b = _ints(args[1], 'lcm').astype(np.int64)
    a, b = align(a, b)
    return out(np.lcm(np.abs(a), np.abs(b)).astype(F64))


@bi('factorial')
def factorial(nargout, *args):
    nargchk(args, 1, 1, 'factorial')
    a = arr(args[0])
    if np.any(a < 0) or np.any(a != np.floor(a)):
        raise err('MATLAB:factorial:NNegativeInt', 'N must be an array of real non-negative integers.', 'factorial')
    import scipy.special as sp
    with np.errstate(all='ignore'):
        r = np.round(sp.gamma(a.astype(F64) + 1))
        r = np.where(a > 170, np.inf, r)
    return like_class(r, args[0]) if class_of(args[0]) in INT_CLASSES else out(r)


@bi('nchoosek')
def nchoosek(nargout, *args):
    nargchk(args, 2, 2, 'nchoosek')
    v = args[0]
    k = ival(args[1], 'k', 'nchoosek')
    if numel(v) == 1:
        n = int(num(v))
        if k > n or k < 0:
            raise err('MATLAB:nchoosek:KOutOfRange', 'K must be an integer between 0 and N.', 'nchoosek')
        r = math.comb(n, k)
        if r > 2 ** 53:
            from .. import runtime as R
            R.warn('MATLAB:nchoosek:LargeCoefficient', f'Result may not be exact. Coefficient is greater than 9.007199e+15 and is only accurate to 15 digits')
        return float(r)
    a = arr(v).reshape(-1)
    combos = list(itertools.combinations(range(a.size), k))
    if not combos:
        return out(np.zeros((0, k), a.dtype))
    idx = np.array(combos)
    r = a[idx]
    if type(v) is Cell:
        return v
    return like_class(r, v) if type(v) is not Char else _char_out(r)


def _char_out(r):
    from ..values import Char
    return Char(_2d(r.astype(np.uint16)))


@bi('primes')
def primes(nargout, *args):
    n = int(math.floor(num(args[0])))
    if n < 2:
        return np.zeros((1, 0))
    sieve = np.ones(n + 1, bool)
    sieve[:2] = False
    for i in range(2, int(n ** 0.5) + 1):
        if sieve[i]:
            sieve[i * i::i] = False
    return out(np.flatnonzero(sieve).astype(F64).reshape(1, -1))


@bi('isprime')
def isprime(nargout, *args):
    a = arr(args[0])
    if np.any(a < 0) or np.any(a != np.round(a)):
        raise err('MATLAB:isprime:InputNotPosInt', 'All entries must be real, nonnegative integers.', 'isprime')
    flat = a.reshape(-1).astype(np.int64)
    res = np.zeros(flat.size, bool)
    for i, x in enumerate(flat):
        x = int(x)
        if x < 2:
            continue
        if x < 4:
            res[i] = True
            continue
        if x % 2 == 0:
            continue
        ok = True
        r = int(math.isqrt(x))
        f = 3
        while f <= r:
            if x % f == 0:
                ok = False
                break
            f += 2
        res[i] = ok
    return out(res.reshape(a.shape))


@bi('factor')
def factor(nargout, *args):
    n = int(num(args[0]))
    if n < 0:
        raise err('MATLAB:factor:InputNotPosInt', 'N must be a real nonnegative integer.', 'factor')
    if n < 4:
        return float(n)
    fs = []
    d = 2
    while d * d <= n:
        while n % d == 0:
            fs.append(d)
            n //= d
        d += 1 if d == 2 else 2
    if n > 1:
        fs.append(n)
    return out(np.array([fs], F64))


@bi('perms')
def perms(nargout, *args):
    v = args[0]
    a = arr(v).reshape(-1)
    rows = list(itertools.permutations(a[::-1]))
    r = np.array(rows) if rows else np.zeros((1, 0))
    if type(v) is Char:
        return _char_out(r)
    return like_class(r, v)


@bi('rats')
def rats(nargout, *args):
    from ..display import rat_text
    from ..values import Char
    a = darr(args[0]).reshape(-1)
    return Char.of('  '.join(rat_text(float(x)).rjust(13) for x in a.real))


@bi('rat', nout=2)
def rat(nargout, *args):
    from ..values import Char
    a = darr(args[0])
    tol = num(args[1]) if len(args) > 1 else None
    N = np.zeros(a.shape)
    Dn = np.ones(a.shape)
    for i, x in enumerate(a.reshape(-1).real):
        if not math.isfinite(x):
            N.flat[i] = x
            Dn.flat[i] = 0 if x != x else 1
            continue
        t = tol if tol is not None else 1e-6 * np.linalg.norm(a.reshape(-1), 1)
        n0, d0, n1, d1 = 1, 0, 0, 1
        y = x
        for _ in range(64):
            k = round(y)
            n0, n1 = k * n0 + n1, n0
            d0, d1 = k * d0 + d1, d0
            if abs(x - n0 / d0) <= max(t, 0):
                break
            f = y - k
            if f == 0:
                break
            y = 1 / f
        if d0 < 0:
            n0, d0 = -n0, -d0
        N.flat[i] = n0
        Dn.flat[i] = d0
    if nargout >= 2:
        return out(N), out(Dn)
    from ..display import rat_text
    return Char.of(' '.join(rat_text(float(x)) for x in a.reshape(-1).real))


# ---- special functions --------------------------------------------------------------------

def _sp():
    import scipy.special as sp
    return sp


def _special1(name, fname):
    def f(nargout, *args):
        nargchk(args, 1, 1, name)
        sp = _sp()
        a, klass = _float_arg(args[0], name)
        with np.errstate(all='ignore'):
            r = getattr(sp, fname)(np.asarray(a))
        return _finish(r, klass)
    f.__name__ = name
    bi(name)(f)


_special1('gamma', 'gamma')
_special1('gammaln', 'gammaln')
_special1('erf', 'erf')
_special1('erfc', 'erfc')
_special1('erfinv', 'erfinv')
_special1('erfcinv', 'erfcinv')
_special1('erfcx', 'erfcx')
_special1('expint', 'exp1')


@bi('psi')
def psi(nargout, *args):
    sp = _sp()
    if len(args) == 2:
        k = arr(args[0]).astype(int)
        x = darr(args[1])
        return out(sp.polygamma(k, x))
    return out(sp.digamma(darr(args[0])))


def _bcast2(args, fn):
    a = darr(args[0], fn)
    b = darr(args[1], fn)
    a, b = align(a, b)
    check_bcast(a, b)
    return a, b


@bi('gammainc')
def gammainc(nargout, *args):
    nargchk(args, 2, 3, 'gammainc')
    sp = _sp()
    x, a = _bcast2(args, 'gammainc')
    tail = opt_str(args[2]).lower() if len(args) > 2 else 'lower'
    with np.errstate(all='ignore'):
        r = sp.gammaincc(a, x) if tail == 'upper' else sp.gammainc(a, x)
    return out(r)


@bi('gammaincinv')
def gammaincinv(nargout, *args):
    sp = _sp()
    y, a = _bcast2(args, 'gammaincinv')
    tail = opt_str(args[2]).lower() if len(args) > 2 else 'lower'
    with np.errstate(all='ignore'):
        r = sp.gammainccinv(a, y) if tail == 'upper' else sp.gammaincinv(a, y)
    return out(r)


@bi('beta')
def beta(nargout, *args):
    sp = _sp()
    a, b = _bcast2(args, 'beta')
    return out(sp.beta(a, b))


@bi('betaln')
def betaln(nargout, *args):
    sp = _sp()
    a, b = _bcast2(args, 'betaln')
    return out(sp.betaln(a, b))


@bi('betainc')
def betainc(nargout, *args):
    nargchk(args, 3, 4, 'betainc')
    sp = _sp()
    x = darr(args[0])
    z = darr(args[1])
    w = darr(args[2])
    tail = opt_str(args[3]).lower() if len(args) > 3 else 'lower'
    x, z, w = np.broadcast_arrays(x, z, w)
    with np.errstate(all='ignore'):
        r = sp.betainc(z, w, x) if tail == 'lower' else sp.betaincc(z, w, x)
    return out(r)


@bi('betaincinv')
def betaincinv(nargout, *args):
    sp = _sp()
    y = darr(args[0])
    z = darr(args[1])
    w = darr(args[2])
    y, z, w = np.broadcast_arrays(y, z, w)
    return out(sp.betaincinv(z, w, y))


def _bessel(name, fn):
    def f(nargout, *args):
        nargchk(args, 2, 3, name)
        sp = _sp()
        nu = darr(args[0])
        z = darr(args[1])
        nu, z = align(nu, z)
        scaled = len(args) > 2 and num(args[2]) == 1
        with np.errstate(all='ignore'):
            if np.iscomplexobj(z) or (name in ('besselj', 'bessely') and np.any(z < 0) and np.any(nu != np.round(nu))) or (name == 'bessely' and np.any(z < 0)):
                z = z.astype(C128)
            r = fn(sp, nu, z, scaled)
        return out(r)
    f.__name__ = name
    bi(name)(f)


_bessel('besselj', lambda sp, nu, z, s: sp.jve(nu, z) if s else sp.jv(nu, z))
_bessel('bessely', lambda sp, nu, z, s: sp.yve(nu, z) if s else sp.yv(nu, z))
_bessel('besseli', lambda sp, nu, z, s: sp.ive(nu, z) if s else sp.iv(nu, z))
_bessel('besselk', lambda sp, nu, z, s: sp.kve(nu, z) if s else sp.kv(nu, z))


@bi('besselh')
def besselh(nargout, *args):
    sp = _sp()
    nu = darr(args[0])
    if len(args) == 2:
        k, z = 1, darr(args[1])
    else:
        k, z = int(num(args[1])), darr(args[2])
    nu, z = align(nu, z)
    r = sp.hankel1(nu, z) if k == 1 else sp.hankel2(nu, z)
    return out(r)


@bi('airy')
def airy(nargout, *args):
    sp = _sp()
    if len(args) == 1:
        k, z = 0, darr(args[0])
    else:
        k, z = int(num(args[0])), darr(args[1])
    ai, aip, bi_, bip = sp.airy(z)
    return out([ai, aip, bi_, bip][k])


@bi('ellipke', nout=2)
def ellipke(nargout, *args):
    sp = _sp()
    m = darr(args[0])
    K = sp.ellipk(m)
    if nargout >= 2:
        return out(K), out(sp.ellipe(m))
    return out(K)


@bi('ellipj', nout=3)
def ellipj(nargout, *args):
    sp = _sp()
    u = darr(args[0])
    m = darr(args[1])
    u, m = align(u, m)
    sn, cn, dn, ph = sp.ellipj(u, m)
    res = (out(sn), out(cn), out(dn))
    return res[0] if nargout <= 1 else res[:nargout]


@bi('legendre')
def legendre(nargout, *args):
    sp = _sp()
    n = ival(args[0], 'degree', 'legendre')
    x = darr(args[1])
    norm = opt_str(args[2]).lower() if len(args) > 2 else 'unnorm'
    xs = x.reshape(-1)
    rows = []
    for m in range(n + 1):
        p = sp.lpmv(m, n, xs)
        if norm == 'sch' and m > 0:
            p = p * (-1) ** m * math.sqrt(2 * math.factorial(n - m) / math.factorial(n + m))
        elif norm == 'norm':
            p = p * (-1) ** m * math.sqrt((n + 0.5) * math.factorial(n - m) / math.factorial(n + m))
        rows.append(p)
    r = np.array(rows)
    if x.size == 1:
        return out(r.reshape(-1, 1))
    if x.ndim == 2 and (x.shape[0] == 1 or x.shape[1] == 1):
        return out(r)
    return out(r.reshape((n + 1,) + x.shape, order='C'))
