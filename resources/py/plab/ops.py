"""Operators: arithmetic, comparison, logic, the colon, transposes and
concatenation, with the language's rules for the class of a result.

    double  op double   -> double         single op double  -> single
    int     op double   -> int (rounded, saturated)
    int     op same int -> int            int op other int  -> error
    char, logical       -> counted as double in arithmetic

Sizes combine by implicit expansion: a dimension of 1 stretches to the
other's length. Complex results whose imaginary parts are all zero come back
real. Scalars come back as Python float/complex/bool, which every operator
takes as a 1x1 array.
"""
import math
import numpy as np

from .values import (MError, Char, Cell, Struct, Str, FH, Obj, F64, C128, INT_TYPES, INT_RANGE,
                     DTYPE_CLASS, class_of, scalar_out, EMPTY, share, share_all, _2d, numel, shape_of)

import contextlib
_ERR_IGNORE = contextlib.nullcontext()   # errors are ignored globally (seterr below)
np.seterr(all='ignore')

FLOAT = float
INT_CLASSES = set(INT_TYPES)


class _NoSym:
    pass


# symbolic values: symbolic.Sym and its operators once symbolic.py is loaded
SYM = _NoSym
SYMOPS = None
# objects of the language's own classes (classdef.py sets these)
UOBJ = _NoSym
UOPS = None


def _incompat():
    return MError('MATLAB:sizeDimensionsMustMatch', 'Arrays have incompatible sizes for this operation.')


def _optype_error(sym, *vals):
    name = class_of(vals[0]) if vals else 'unknown'
    return MError('MATLAB:UndefinedFunction', f"Operator '{sym}' is not supported for operands of type '{name}'.")


def operand(v, sym='+'):
    """(numbers, class) for arithmetic: numbers is a Python scalar or a numpy
    array of float64/complex128, float32/complex64 or an integer type."""
    t = type(v)
    if t is float or t is complex:
        return v, 'double'
    if t is bool:
        return float(v), 'double'
    if t is np.ndarray:
        k = v.dtype.kind
        if k == 'f':
            return v, ('double' if v.dtype == F64 else 'single')
        if k == 'c':
            return v, ('double' if v.dtype == C128 else 'single')
        if k == 'b':
            return v.astype(F64), 'double'
        if k in 'iu':
            return v, DTYPE_CLASS[v.dtype]
        raise _optype_error(sym, v)
    if t is Char:
        return v.a.astype(F64), 'double'
    if t is int:
        return float(v), 'double'
    if isinstance(v, (np.floating, np.integer)):
        return float(v), 'double'
    if isinstance(v, np.complexfloating):
        return complex(v), 'double'
    if isinstance(v, np.bool_):
        return float(v), 'double'
    raise _optype_error(sym, v)


def result_class(ca, cb, sym):
    if ca == cb:
        return ca
    if ca == 'double':
        return cb
    if cb == 'double':
        return ca
    if ca == 'single' and cb not in INT_CLASSES:
        return 'single'
    if cb == 'single' and ca not in INT_CLASSES:
        return 'single'
    raise MError('MATLAB:mixedClasses', 'Integers can only be combined with integers of the same class, or scalars of class double.')


def align(A, B):
    """Give two arrays the same number of dimensions, padding the shorter
    with trailing ones (the language lines dimensions up from the first;
    numpy from the last)."""
    if type(A) is np.ndarray and type(B) is np.ndarray and A.ndim != B.ndim:
        if A.ndim < B.ndim:
            A = A.reshape(A.shape + (1,) * (B.ndim - A.ndim))
        else:
            B = B.reshape(B.shape + (1,) * (A.ndim - B.ndim))
    return A, B


def check_bcast(A, B):
    if type(A) is np.ndarray and type(B) is np.ndarray:
        sa, sb = A.shape, B.shape
        if sa != sb:
            for x, y in zip(sa, sb):
                if x != y and x != 1 and y != 1:
                    raise _incompat()


def round_half_away(r):
    """Round half away from zero, exactly: r + 0.5 would itself round for
    values past 2^52 (9007199254740881 + 0.5 is ...882)."""
    t = np.trunc(r)
    return np.where(np.abs(r - t) >= 0.5, t + np.sign(r), t)


def to_int_class(r, cls):
    """Round half away from zero and saturate to an integer class."""
    lo, hi = INT_RANGE[cls]
    r = np.asarray(r)
    if r.dtype.kind in 'iub':
        # integers convert exactly, saturating in their own type (through
        # float64 a 64-bit value above 2^53 would lose its lowest bits)
        if r.dtype.kind != 'b':
            info = np.iinfo(r.dtype)
            r = np.clip(r, max(lo, int(info.min)), min(hi, int(info.max)))
        return r.astype(INT_TYPES[cls])
    if r.dtype.kind == 'c':
        r = r.real
    r = r.astype(F64, copy=False)
    with _ERR_IGNORE:
        r = round_half_away(r)
        r = np.where(np.isnan(r), 0, r)
        r = np.clip(r, lo, hi)
    dt = INT_TYPES[cls]
    if cls in ('int64', 'uint64'):
        # float64 cannot hold every 64-bit integer: clip in integer space at the ends
        out = np.empty(r.shape, dt)
        big = r >= float(hi)
        small = r <= float(lo)
        out[...] = np.where(big | small, 0, r).astype(dt)
        out[big] = hi
        out[small] = lo
        return out
    return r.astype(dt)


def narrow(r):
    """Complex results with no imaginary part come back real."""
    if type(r) is np.ndarray and r.dtype.kind == 'c':
        if not np.any(r.imag):
            return np.ascontiguousarray(r.real)
    elif type(r) is complex and r.imag == 0:
        return r.real
    return r


def finish(r, cls):
    """Bring a numpy result to the class it must have."""
    if cls == 'double':
        if type(r) is np.ndarray:
            if r.dtype.kind == 'c':
                if r.dtype != C128:
                    r = r.astype(C128)
                r = narrow(r)
            elif r.dtype != F64:
                r = r.astype(F64)
            r = _2d(r)
            if r.size == 1 and r.ndim == 2:
                return scalar_out(r)
            return r
        if type(r) is complex:
            return r.real if r.imag == 0 else r
        if isinstance(r, (np.floating, np.integer)):
            return float(r)
        if isinstance(r, np.complexfloating):
            z = complex(r)
            return z.real if z.imag == 0 else z
        return r
    if cls == 'single':
        r = np.asarray(r)
        if r.dtype.kind == 'c':
            r = narrow(r.astype(np.complex64))
            if r.dtype.kind == 'f':
                r = r.astype(np.float32)
        else:
            r = r.astype(np.float32)
        return _2d(r)
    if cls == 'logical':
        r = np.asarray(r, bool)
        r = _2d(r)
        return bool(r.reshape(-1)[0]) if r.size == 1 else r
    return _2d(to_int_class(r, cls))


def _arr(x):
    return np.asarray(x)


def _binary(a, b, fn, sym, int_fn=None):
    """An element-wise arithmetic operator on any two numeric values."""
    if type(a) is SYM or type(b) is SYM:
        # ldivide comes here with its operands swapped, as a./b
        return SYMOPS.binop('./' if sym == '.\\' else sym, a, b)
    if type(a) is UOBJ or type(b) is UOBJ:
        return UOPS.binop('./', b, a) if sym == '.\\' else UOPS.binop(sym, a, b)
    A, ca = operand(a, sym)
    B, cb = operand(b, sym)
    cls = result_class(ca, cb, sym)
    A, B = align(A, B)
    check_bcast(A, B)
    with _ERR_IGNORE:
        if cls == 'double':
            r = fn(A, B)
        elif cls == 'single':
            r = fn(np.asarray(A, np.complex64 if np.iscomplexobj(A) else np.float32),
                   np.asarray(B, np.complex64 if np.iscomplexobj(B) else np.float32))
        else:
            if (type(A) is np.ndarray and A.dtype.kind == 'c') or (type(B) is np.ndarray and B.dtype.kind == 'c') or type(A) is complex or type(B) is complex:
                raise MError('MATLAB:complexInt', 'Complex integer arithmetic is not supported.')
            if cls in ('int64', 'uint64') and sym in _EXACT_OPS and not _small_ints(A, B):
                return _2d(_int64_exact(A, B, sym, cls))
            r = (int_fn or fn)(np.asarray(A, F64), np.asarray(B, F64))
    return finish(r, cls)


# 64-bit integers: past 2^53 a double cannot hold them, so their arithmetic
# is done exactly (as rationals), rounded half away from zero and saturated.
_EXACT_OPS = ('+', '-', '.*', './', '.\\')


def _small_ints(A, B):
    """Both operands small enough (|x| <= 2^26) that arithmetic in doubles is
    exact: sums, products and correctly rounded quotients."""
    lim = 2.0 ** 26
    for X in (A, B):
        X = np.asarray(X)
        if X.size and X.dtype.kind in 'iu':
            if X.max() > lim or X.min() < -lim:
                return False
        elif X.size:
            with _ERR_IGNORE:
                Xf = np.abs(np.asarray(X, F64))
            if np.any(Xf > lim) and np.any(np.isfinite(Xf) & (Xf > lim)):
                return False
    return True


def _int64_exact(A, B, sym, cls):
    from fractions import Fraction
    lo, hi = INT_RANGE[cls]

    def one(x, y):
        if isinstance(x, float) and not math.isfinite(x) or isinstance(y, float) and not math.isfinite(y):
            with _ERR_IGNORE:
                f = float(x) + float(y) if sym == '+' else float(x) - float(y) if sym == '-' else \
                    float(x) * float(y) if sym == '.*' else np.true_divide(float(x), float(y))
            return 0 if math.isnan(f) else (hi if f > 0 else lo)
        fx, fy = Fraction(x), Fraction(y)
        if sym == '+':
            r = fx + fy
        elif sym == '-':
            r = fx - fy
        elif sym == '.*':
            r = fx * fy
        elif fy == 0:
            return 0 if fx == 0 else (hi if fx > 0 else lo)
        else:
            r = fx / fy
        n = math.floor(abs(r) + Fraction(1, 2))
        n = n if r >= 0 else -n
        return min(hi, max(lo, n))

    def pyvals(X):
        X = np.asarray(X)
        if X.dtype.kind in 'iu':
            return X.astype(object)
        return np.vectorize(lambda v: int(v) if math.isfinite(v) and v == int(v) else float(v), otypes=[object])(np.asarray(X, F64)) if X.size else X.astype(object)
    PA, PB = np.broadcast_arrays(pyvals(A), pyvals(B))
    r = np.frompyfunc(one, 2, 1)(PA, PB) if PA.size else np.zeros(PA.shape, object)
    return np.asarray(r, dtype=object).astype(INT_TYPES[cls]).reshape(PA.shape)


def plus(a, b):
    if type(a) is float and type(b) is float:
        return a + b
    if type(a) is Str or type(b) is Str:
        return str_plus(a, b)
    return _binary(a, b, np.add, '+')


def minus(a, b):
    if type(a) is float and type(b) is float:
        return a - b
    return _binary(a, b, np.subtract, '-')


def times(a, b):
    if type(a) is float and type(b) is float:
        return a * b
    return _binary(a, b, np.multiply, '.*')


def _div(A, B):
    return np.true_divide(A, B)


def rdivide(a, b):
    if type(a) is float and type(b) is float and b != 0.0:
        return a / b
    return _binary(a, b, _div, './')


def ldivide(a, b):
    if type(a) is float and type(b) is float and a != 0.0:
        return b / a
    return _binary(b, a, _div, '.\\')


def _pow(A, B):
    A = np.asarray(A)
    B = np.asarray(B)
    if A.dtype.kind != 'c' and B.dtype.kind != 'c':
        neg = A < 0
        if np.any(neg):
            frac = B != np.floor(B)
            if np.any(neg & frac):
                return np.power(A.astype(C128 if A.dtype == F64 else np.complex64), B)
    return np.power(A, B)


def power(a, b):
    if type(a) is float and type(b) is float:
        try:
            r = a ** b
        except (ZeroDivisionError, OverflowError):
            pass
        else:
            if type(r) is complex:
                return r.real if r.imag == 0 else r
            return r
    return _binary(a, b, _pow, '.^')


def uminus(a):
    t = type(a)
    if t is float or t is complex:
        return -a
    if t is bool:
        return -float(a)
    if t is SYM:
        return SYMOPS.unop('-', a)
    if t is UOBJ:
        return UOPS.unop('-', a)
    A, c = operand(a, '-')
    if c in ('int64', 'uint64'):
        lo, hi = INT_RANGE[c]
        A = np.asarray(A)
        if c == 'uint64':
            return _2d(np.zeros(A.shape, np.uint64))
        return _2d(np.where(A == lo, np.int64(hi), -np.where(A == lo, 0, A)).astype(np.int64))
    if c in INT_CLASSES:
        return finish(-np.asarray(A, F64), c)
    return finish(-A, c)


def uplus(a):
    t = type(a)
    if t is float or t is complex:
        return a
    if t is bool:
        return float(a)
    if t is SYM:
        return a
    A, c = operand(a, '+')
    if t is np.ndarray and A is a:
        return a
    return finish(A, c)


# ---- comparison ----------------------------------------------------------------

def _cmp_operand(v, sym):
    t = type(v)
    if t is float or t is complex or t is bool:
        return v
    if t is np.ndarray:
        if v.dtype.kind in 'fciub':
            return v
    if t is Char:
        return v.a
    if t is int:
        return float(v)
    raise _optype_error(sym, v)


def _handles_of(v):
    """Handle objects (graphics objects, timers) as an object array, or None."""
    if type(v).__name__ == 'HArr':
        return v.a
    if isinstance(v, Obj) and getattr(v, 'is_handle', False):
        a = np.empty((1, 1), object)
        a[0, 0] = v
        return a
    return None


def _handle_compare(a, b, sym):
    """h1 == h2: the same object; a handle against numbers, by its number."""
    ha, hb = _handles_of(a), _handles_of(b)
    num = lambda h: np.vectorize(lambda x: x.number_value() if hasattr(x, 'number_value') else np.nan, otypes=[float])(h)
    A = ha if hb is not None or ha is None else num(ha)
    B = hb if ha is not None or hb is None else num(hb)
    if ha is None:
        A = _cmp_operand(a, sym)
    if hb is None:
        B = _cmp_operand(b, sym)
    A, B = np.broadcast_arrays(np.asarray(A, object), np.asarray(B, object)) if ha is not None and hb is not None else (A, B)
    check_bcast(np.asarray(A), np.asarray(B))
    if ha is not None and hb is not None:
        r = np.vectorize(lambda x, y: x is y, otypes=[bool])(A, B)
    else:
        r = np.equal(np.asarray(A, float), np.asarray(B, float))
    if sym == '~=':
        r = ~r
    r = _2d(np.asarray(r))
    return bool(r.reshape(-1)[0]) if r.size == 1 else r


def _compare(a, b, fn, sym):
    if type(a) is SYM or type(b) is SYM:
        return SYMOPS.binop(sym, a, b)
    if type(a) is UOBJ or type(b) is UOBJ:
        return UOPS.binop(sym, a, b)
    if type(a) is Str or type(b) is Str:
        return str_compare(a, b, fn, sym)
    if sym in ('==', '~=') and (_handles_of(a) is not None or _handles_of(b) is not None):
        return _handle_compare(a, b, sym)
    A = _cmp_operand(a, sym)
    B = _cmp_operand(b, sym)
    A, B = align(A, B)
    check_bcast(A, B)
    if sym not in ('==', '~='):
        if np.iscomplexobj(A):
            A = np.real(A)
        if np.iscomplexobj(B):
            B = np.real(B)
    # integers against doubles compare by value (numpy promotes correctly)
    r = fn(A, B)
    if type(r) is np.ndarray:
        r = _2d(r)
        if r.size == 1:
            return bool(r.reshape(-1)[0])
        return r
    return bool(r)


def eq(a, b):
    if type(a) is float and type(b) is float:
        return a == b
    return _compare(a, b, np.equal, '==')


def ne(a, b):
    if type(a) is float and type(b) is float:
        return a != b
    return _compare(a, b, np.not_equal, '~=')


def lt(a, b):
    if type(a) is float and type(b) is float:
        return a < b
    return _compare(a, b, np.less, '<')


def le(a, b):
    if type(a) is float and type(b) is float:
        return a <= b
    return _compare(a, b, np.less_equal, '<=')


def gt(a, b):
    if type(a) is float and type(b) is float:
        return a > b
    return _compare(a, b, np.greater, '>')


def ge(a, b):
    if type(a) is float and type(b) is float:
        return a >= b
    return _compare(a, b, np.greater_equal, '>=')


# ---- logic -------------------------------------------------------------------

def _nan_err():
    return MError('MATLAB:nologicalnan', "NaN's cannot be converted to logicals.")


def to_logical(v, sym='&'):
    """A bool array (or bool) from a value, for the logical operators."""
    t = type(v)
    if t is bool:
        return v
    if t is float:
        if v != v:
            raise _nan_err()
        return v != 0.0
    if t is complex:
        if v != v:
            raise _nan_err()
        return v != 0
    if t is np.ndarray:
        k = v.dtype.kind
        if k == 'b':
            return v
        if k in 'fc':
            if np.isnan(v).any():
                raise _nan_err()
        return v != 0
    if t is Char:
        return v.a != 0
    if t is int:
        return v != 0
    raise MError('MATLAB:invalidConversion', f"Conversion to logical from {class_of(v)} is not possible.")


def _logic(a, b, fn, sym):
    if (type(a) is SYM or type(b) is SYM) and sym in ('&', '|'):
        return SYMOPS.binop(sym, a, b)
    if (type(a) is UOBJ or type(b) is UOBJ) and sym in ('&', '|'):
        return UOPS.binop(sym, a, b)
    A = to_logical(a, sym)
    B = to_logical(b, sym)
    A, B = align(A, B)
    check_bcast(A, B)
    r = fn(A, B)
    if type(r) is np.ndarray:
        r = _2d(r)
        if r.size == 1:
            return bool(r.reshape(-1)[0])
        return r
    return bool(r)


def and_(a, b):
    if type(a) is bool and type(b) is bool:
        return a and b
    return _logic(a, b, np.logical_and, '&')


def or_(a, b):
    if type(a) is bool and type(b) is bool:
        return a or b
    return _logic(a, b, np.logical_or, '|')


def xor(a, b):
    return _logic(a, b, np.logical_xor, 'xor')


def not_(a):
    t = type(a)
    if t is bool:
        return not a
    if t is float:
        if a != a:
            raise _nan_err()
        return a == 0.0
    if t is SYM:
        return SYMOPS.unop('~', a)
    if t is UOBJ:
        return UOPS.unop('~', a)
    L = to_logical(a, '~')
    if type(L) is np.ndarray:
        r = _2d(np.logical_not(L))
        return bool(r.reshape(-1)[0]) if r.size == 1 else r
    return not L


def truth(v):
    """The condition of if and while: true when not empty and no element is
    zero."""
    t = type(v)
    if t is bool:
        return v
    if t is float:
        if v != v:
            raise _nan_err()
        return v != 0.0
    if t is np.ndarray:
        if v.size == 0:
            return False
        k = v.dtype.kind
        if k == 'b':
            return bool(v.all())
        if k in 'fc' and np.isnan(v).any():
            raise _nan_err()
        return bool((v != 0).all())
    if t is complex:
        return v != 0
    if t is Char:
        return v.a.size > 0 and bool((v.a != 0).all())
    if t is Str:
        raise MError('MATLAB:invalidConversion', 'Conversion to logical from string is not possible.')
    if t is int:
        return v != 0
    if t is SYM:
        return SYMOPS.truth(v)
    raise MError('MATLAB:invalidConversion', f"Conversion to logical from {class_of(v)} is not possible.")


def sc_truth(v, sym):
    """An operand of && or ||: a value convertible to one logical."""
    t = type(v)
    if t is bool:
        return v
    if t is float:
        if v != v:
            raise _nan_err()
        return v != 0.0
    if numel_safe(v) != 1:
        raise MError('MATLAB:nonLogicalConditional',
                     f"Operands to the logical AND (&&) and OR (||) operators must be convertible to logical scalar values. Use the ANY or ALL functions to reduce operands to logical scalar values." if sym == '&&'
                     else "Operands to the logical AND (&&) and OR (||) operators must be convertible to logical scalar values. Use the ANY or ALL functions to reduce operands to logical scalar values.")
    return truth(v)


def numel_safe(v):
    try:
        return numel(v)
    except Exception:
        return 1


# ---- matrix operators ----------------------------------------------------------

def _is_scalar(v):
    t = type(v)
    return t is float or t is complex or t is bool or numel_safe(v) == 1


def mtimes(a, b):
    if type(a) is float and type(b) is float:
        return a * b
    if type(a) is SYM or type(b) is SYM:
        return SYMOPS.binop('*', a, b)
    if type(a) is UOBJ or type(b) is UOBJ:
        return UOPS.binop('*', a, b)
    if _is_scalar(a) or _is_scalar(b):
        return times(a, b)
    A, ca = operand(a, '*')
    B, cb = operand(b, '*')
    cls = result_class(ca, cb, '*')
    if cls in INT_CLASSES:
        raise MError('MATLAB:mtimes:integerNotSupported', 'MTIMES (*) is not fully supported for integer classes. At least one argument must be scalar.')
    if A.ndim > 2 or B.ndim > 2:
        raise MError('MATLAB:mtimes:notSupportedForND', 'Arguments must be 2-D, or at least one argument must be scalar. Use TIMES (.*) for elementwise multiplication.')
    if A.shape[1] != B.shape[0]:
        raise MError('MATLAB:innerdim', 'Incorrect dimensions for matrix multiplication. Check that the number of columns in the first matrix matches the number of rows in the second matrix. To operate on each element of the matrix individually, use TIMES (.*) for elementwise multiplication.')
    with _ERR_IGNORE:
        if cls == 'single':
            r = np.asarray(A, np.complex64 if np.iscomplexobj(A) else np.float32) @ np.asarray(B, np.complex64 if np.iscomplexobj(B) else np.float32)
        else:
            if A.shape[1] == 0:
                r = np.zeros((A.shape[0], B.shape[1]), np.result_type(A, B, F64))
            else:
                r = A @ B
    return finish(r, cls)


_warn_hook = [None]


def warn(ident, msg):
    if _warn_hook[0] is not None:
        _warn_hook[0](ident, msg)


def _solve(A, B):
    """A\\B for 2-D numeric arrays (float64/complex128)."""
    import scipy.linalg as sla
    m, n = A.shape
    if B.shape[0] != m:
        raise MError('MATLAB:dimagree', 'Matrix dimensions must agree.')
    if m == 0 or n == 0:
        return np.zeros((n, B.shape[1]), np.result_type(A, B, F64))
    if not np.all(np.isfinite(A)):
        with _ERR_IGNORE:
            return np.full((n, B.shape[1]), np.nan)
    if m == n:
        # triangular systems solve directly
        if np.all(np.triu(A) == A) or np.all(np.tril(A) == A):
            lower = not np.all(np.triu(A) == A)
            d = np.abs(np.diag(A))
            if np.all(d != 0):
                rc = d.min() / d.max() if d.max() > 0 else 0
                if rc < np.finfo(float).eps:
                    warn('MATLAB:nearlySingularMatrix', f'Matrix is close to singular or badly scaled. Results may be inaccurate. RCOND =  {rc:.6e}.')
                return sla.solve_triangular(A, B, lower=lower)
        with _ERR_IGNORE:
            lu, piv = sla.lu_factor(A, check_finite=False)
            d = np.abs(np.diag(lu))
            if np.any(d == 0):
                warn('MATLAB:singularMatrix', 'Matrix is singular to working precision.')
                x = sla.lu_solve((lu, piv), B, check_finite=False)
                return x
            # an estimate of the reciprocal condition number, as the warning reports
            try:
                anorm = np.linalg.norm(A, 1)
                from scipy.linalg.lapack import get_lapack_funcs
                gecon, = get_lapack_funcs(('gecon',), (lu,))
                rc, info = gecon(lu, anorm, norm='1')
            except Exception:
                rc = 1.0
            x = sla.lu_solve((lu, piv), B, check_finite=False)
            if rc < np.finfo(float).eps:
                warn('MATLAB:nearlySingularMatrix', f'Matrix is close to singular or badly scaled. Results may be inaccurate. RCOND =  {rc:.6e}.')
            return x
    # rectangular: least squares by QR with column pivoting, a basic solution
    Q, Rm, P = sla.qr(A, mode='economic', pivoting=True)
    d = np.abs(np.diag(Rm))
    tol = max(m, n) * np.finfo(float).eps * (d[0] if d.size else 0)
    r = int(np.sum(d > tol))
    if r < min(m, n):
        warn('MATLAB:rankDeficientMatrix', f'Rank deficient, rank = {r}, tol =  {tol:.6e}.')
    x = np.zeros((n, B.shape[1]), np.result_type(A, B, F64))
    if r > 0:
        y = Q[:, :r].conj().T @ B
        z = sla.solve_triangular(Rm[:r, :r], y)
        x[P[:r], :] = z
    return x


def mldivide(a, b):
    if type(a) is SYM or type(b) is SYM:
        return SYMOPS.binop('\\', a, b)
    if type(a) is UOBJ or type(b) is UOBJ:
        return UOPS.binop('\\', a, b)
    if _is_scalar(a):
        return ldivide(a, b)
    A, ca = operand(a, '\\')
    B, cb = operand(b, '\\')
    cls = result_class(ca, cb, '\\')
    if cls in INT_CLASSES:
        raise MError('MATLAB:mldivide:integerNotSupported', 'Integer data types are not fully supported for this operation. At least one input must be scalar.')
    A = np.asarray(A)
    B = np.asarray(B)
    if A.ndim > 2 or B.ndim > 2:
        raise MError('MATLAB:mldivide:notSupportedForND', 'Arguments must be 2-D, or at least one argument must be scalar.')
    if A.shape[0] != B.shape[0]:
        raise MError('MATLAB:dimagree', 'Matrix dimensions must agree.')
    dt = C128 if (np.iscomplexobj(A) or np.iscomplexobj(B)) else F64
    x = _solve(A.astype(dt), B.astype(dt))
    return finish(x, cls)


def mrdivide(a, b):
    if type(a) is float and type(b) is float and b != 0.0:
        return a / b
    if type(a) is SYM or type(b) is SYM:
        return SYMOPS.binop('/', a, b)
    if type(a) is UOBJ or type(b) is UOBJ:
        return UOPS.binop('/', a, b)
    if _is_scalar(b):
        return rdivide(a, b)
    A, ca = operand(a, '/')
    B, cb = operand(b, '/')
    cls = result_class(ca, cb, '/')
    A = np.asarray(A)
    B = np.asarray(B)
    if A.ndim > 2 or B.ndim > 2:
        raise MError('MATLAB:mrdivide:notSupportedForND', 'Arguments must be 2-D, or at least one argument must be scalar.')
    if A.shape[1] != B.shape[1]:
        raise MError('MATLAB:dimagree', 'Matrix dimensions must agree.')
    dt = C128 if (np.iscomplexobj(A) or np.iscomplexobj(B)) else F64
    x = _solve(B.astype(dt).conj().T, A.astype(dt).conj().T).conj().T
    return finish(x, cls)


def mpower(a, b):
    if type(a) is float and type(b) is float:
        return power(a, b)
    if type(a) is SYM or type(b) is SYM:
        return SYMOPS.binop('^', a, b)
    if type(a) is UOBJ or type(b) is UOBJ:
        return UOPS.binop('^', a, b)
    sa, sb = _is_scalar(a), _is_scalar(b)
    if sa and sb:
        return power(a, b)
    A, ca = operand(a, '^')
    B, cb = operand(b, '^')
    cls = result_class(ca, cb, '^')
    import scipy.linalg as sla
    if sb:
        A = np.asarray(A)
        if A.ndim != 2 or A.shape[0] != A.shape[1]:
            raise MError('MATLAB:square', 'Incorrect dimensions for raising a matrix to a power. Check that the matrix is square and the power is a scalar. To operate on each element of the matrix individually, use POWER (.^) for elementwise power.')
        p = complex(np.asarray(B).reshape(-1)[0])
        if p.imag == 0 and p.real == int(p.real):
            k = int(p.real)
            M = A.astype(C128 if np.iscomplexobj(A) else F64)
            if cls in INT_CLASSES:
                if k < 0:
                    raise MError('MATLAB:mpower', 'Integers can only be raised to positive integral powers.')
                r = np.linalg.matrix_power(M, k)
            elif k < 0:
                r = np.linalg.matrix_power(np.asarray(mldivide(M, np.eye(M.shape[0]))), -k)
            else:
                r = np.linalg.matrix_power(M, k)
            return finish(r, cls)
        with _ERR_IGNORE:
            r = sla.fractional_matrix_power(A.astype(F64) if not np.iscomplexobj(A) else A, p.real if p.imag == 0 else p)
        return finish(r, cls)
    if sa:
        B = np.asarray(B)
        if B.ndim != 2 or B.shape[0] != B.shape[1]:
            raise MError('MATLAB:square', 'Incorrect dimensions for raising a matrix to a power. Check that the matrix is square and the power is a scalar. To operate on each element of the matrix individually, use POWER (.^) for elementwise power.')
        s = complex(np.asarray(A).reshape(-1)[0])
        with _ERR_IGNORE:
            r = sla.expm(np.log(s) * B.astype(C128))
        return finish(r, cls)
    raise MError('MATLAB:mpower:notScalarAndSquareMatrix', 'Incorrect dimensions for raising a matrix to a power. Check that the matrix is square and the power is a scalar. To operate on each element of the matrix individually, use POWER (.^) for elementwise power.')


# ---- transposes ---------------------------------------------------------------

def transpose(a):
    t = type(a)
    if t is float or t is bool or t is complex:
        return a
    if t is np.ndarray:
        if a.ndim > 2:
            raise MError('MATLAB:transpose:ndArray', 'Transpose on ND array is not defined. Use PERMUTE instead.')
        r = a.T.copy()
        return scalar_out(r) if r.size == 1 else r
    if t in (Char, Cell, Str):
        if a.a.ndim > 2:
            raise MError('MATLAB:transpose:ndArray', 'Transpose on ND array is not defined. Use PERMUTE instead.')
        r = a.a.T.copy()
        if t is Cell:
            share_all(r)
        return t(r)
    if t is Struct:
        if len(a.shape) > 2:
            raise MError('MATLAB:transpose:ndArray', 'Transpose on ND array is not defined. Use PERMUTE instead.')
        f = {}
        for k, x in a.f.items():
            x2 = x.T.copy()
            share_all(x2)
            f[k] = x2
        return Struct((a.shape[1], a.shape[0]), f)
    if t is SYM:
        return SYMOPS.unop(".'", a)
    if t is UOBJ:
        return UOPS.unop(".'", a)
    if isinstance(a, Obj) and hasattr(a, 'transposed'):
        return a.transposed()
    if isinstance(a, (FH, Obj)):
        return a
    raise _optype_error(".'", a)


def ctranspose(a):
    t = type(a)
    if t is float or t is bool:
        return a
    if t is SYM:
        return SYMOPS.unop("'", a)
    if t is UOBJ:
        return UOPS.unop("'", a)
    if t is complex:
        z = a.conjugate()
        return z
    if t is np.ndarray and a.dtype.kind == 'c':
        if a.ndim > 2:
            raise MError('MATLAB:transpose:ndArray', 'Transpose on ND array is not defined. Use PERMUTE instead.')
        r = a.conj().T.copy()
        return scalar_out(r) if r.size == 1 else r
    return transpose(a)


# ---- colon ----------------------------------------------------------------------

def _colon_scalar(v, which):
    t = type(v)
    if t is float:
        return v, 'double'
    if t is bool:
        return float(v), 'double'
    if t is np.ndarray:
        if v.size == 0:
            return None, None
        c = DTYPE_CLASS.get(v.dtype, 'double')
        x = v.reshape(-1)[0]
        if v.dtype.kind == 'c':
            x = x.real
        return (float(x) if c in ('double', 'logical', 'single') else int(x)), ('double' if c == 'logical' else c)
    if t is complex:
        return v.real, 'double'
    if t is Char:
        if v.a.size == 0:
            return None, None
        return float(v.a.reshape(-1)[0]), 'char'
    if t is int:
        return float(v), 'double'
    raise MError('MATLAB:colon:invalidType', f"Colon operands must be real scalars, not {class_of(v)}.")


def colon(a, b, c=None):
    """a:b or a:s:b (colon(a, s, b))."""
    if c is None:
        if type(a) is float and type(b) is float:
            return _range(a, 1.0, b)
        start, ca = _colon_scalar(a, 'start')
        stop, cb = _colon_scalar(b, 'stop')
        step, cs = 1.0, 'double'
    else:
        if type(a) is float and type(b) is float and type(c) is float:
            return _range(a, b, c)
        start, ca = _colon_scalar(a, 'start')
        step, cs = _colon_scalar(b, 'step')
        stop, cb = _colon_scalar(c, 'stop')
    if start is None or stop is None or step is None:
        return np.zeros((1, 0))
    classes = {ca, cb, cs} - {'double'}
    if 'char' in classes and classes <= {'char'}:
        if ca == 'char' and cb == 'char':
            r = _range(float(start), float(step), float(stop))
            if type(r) is float:
                r = np.array([[r]])
            return Char(r.astype(np.uint16).reshape(1, -1))
        classes.discard('char')
    if not classes:
        return _range(float(start), float(step), float(stop))
    cls = classes.pop() if len(classes) == 1 else None
    if cls is None:
        raise MError('MATLAB:colon:mixedClasses', 'Colon operands must all be the same class, or mixed with real double scalar values.')
    if cls == 'single':
        r = _range(float(start), float(step), float(stop))
        return np.asarray(r, np.float32).reshape(1, -1)
    # integers: whole steps
    st, sp, en = float(start), float(step), float(stop)
    if sp == 0 or (sp > 0 and st > en) or (sp < 0 and st < en):
        return np.zeros((1, 0), INT_TYPES[cls])
    n = int(math.floor((en - st) / sp))
    return to_int_class(st + sp * np.arange(n + 1, dtype=F64), cls).reshape(1, -1)


def _range(a, d, b):
    """The elements of a:d:b, computed as the language does so that the end
    lands exactly: the first half counts up from a, the second down from the
    last element."""
    if d == 0 or a != a or b != b or d != d or (d > 0 and a > b) or (d < 0 and a < b):
        return np.zeros((1, 0))
    if math.isinf(a) or math.isinf(b):
        if math.isinf(d) or a == b:
            return np.array([[a]]) if a == b else np.zeros((1, 0))
        raise MError('MATLAB:colon:tooManyElements', 'Maximum variable size allowed by the program is exceeded.')
    n = (b - a) / d
    tol = 3.0 * 2.220446049250313e-16 * max(abs(a), abs(b)) / abs(d)
    nf = math.floor(n + tol)
    if nf > 2 ** 31:
        raise MError('MATLAB:array:SizeLimitExceeded', 'Requested array exceeds the maximum possible variable size.')
    if a == int(a) and d == int(d) and abs(a) < 2 ** 52 and abs(b) < 2 ** 52:
        r = a + d * np.arange(nf + 1, dtype=F64)
        return r.reshape(1, -1)
    k = np.arange(nf + 1, dtype=F64)
    last = a + nf * d
    if abs(last - b) < abs(d) * 1e-10 + tol * abs(d):
        last = b
    half = nf // 2
    r = np.empty(nf + 1)
    r[:half + 1] = a + k[:half + 1] * d
    r[half + 1:] = last - (nf - k[half + 1:]) * d
    return r.reshape(1, -1)


def frange(a, b, c=None):
    """The values a for loop over a:b (or a:s:b), one at a time, as Python
    floats; the array is never made."""
    if c is None:
        start, step, stop = a, 1.0, b
    else:
        start, step, stop = a, b, c
    if type(start) is float and type(step) is float and type(stop) is float:
        if start == int(start) and step == int(step) and abs(start) < 2 ** 52 and abs(stop) < 2 ** 52 and step != 0:
            if (step > 0 and start > stop) or (step < 0 and start < stop) or stop != stop or start != start:
                return None
            n = int(math.floor((stop - start) / step + 1e-9))
            s0 = int(start)
            st = int(step)
            return map(float, range(s0, s0 + st * n + (1 if st > 0 else -1), st))
    return None


# ---- concatenation ------------------------------------------------------------

def _cat_kind(vals):
    kinds = set()
    for v in vals:
        kinds.add(type(v))
    return kinds


def _num_cat_class(vals):
    """The class of a concatenation of numeric, logical and char values."""
    cls = None
    has_char = False
    has_single = False
    int_cls = None
    all_logical = True
    for v in vals:
        c = class_of(v)
        if c == 'char':
            has_char = True
            all_logical = False
        elif c == 'logical':
            pass
        else:
            all_logical = False
            if c == 'single':
                has_single = True
            elif c in INT_CLASSES:
                if int_cls is None:
                    int_cls = c
    if int_cls is not None:
        return int_cls
    if has_char:
        return 'char'
    if has_single:
        return 'single'
    if all_logical and vals:
        return 'logical'
    return 'double'


def _as_np(v):
    t = type(v)
    if t is float:
        return np.array([[v]])
    if t is bool:
        return np.array([[v]])
    if t is complex:
        return np.array([[v]], C128)
    if t is np.ndarray:
        return v
    if t is Char:
        return v.a
    if t is int:
        return np.array([[float(v)]])
    raise MError('MATLAB:catenate:invalidType', f"Unable to concatenate a value of class {class_of(v)} here.")


def _concat_arrays(arrs, axis):
    nd = max(max(a.ndim for a in arrs), axis + 1)
    arrs = [a.reshape(a.shape + (1,) * (nd - a.ndim)) if a.ndim < nd else a for a in arrs]
    ref = None
    for a in arrs:
        sh = a.shape[:axis] + a.shape[axis + 1:]
        if ref is None:
            ref = sh
        elif sh != ref:
            raise MError('MATLAB:catenate:dimensionMismatch', 'Dimensions of arrays being concatenated are not consistent.')
    return np.concatenate(arrs, axis=axis)


def _drop_empties(vals):
    """[] and '' (0x0) take no part in concatenation."""
    out = []
    for v in vals:
        t = type(v)
        if (t is np.ndarray and v.ndim == 2 and v.shape == (0, 0)) or (t is Char and v.a.shape == (0, 0)):
            continue
        out.append(v)
    return out


def cat(axis, vals):
    """Concatenate values along a dimension (0 = rows: vertical, 1 = columns:
    horizontal)."""
    if not vals:
        return EMPTY()
    if len(vals) == 1:
        v = vals[0]
        return v
    kinds = _cat_kind(vals)
    if Cell in kinds:
        parts = []
        for v in vals:
            if type(v) is Cell:
                if v.a.shape == (0, 0):
                    continue
                parts.append(v.a)
            elif (type(v) is np.ndarray and v.shape == (0, 0)) or (type(v) is Char and v.a.shape == (0, 0)):
                continue
            else:
                a = np.empty((1, 1), object)
                a[0, 0] = share(v)
                parts.append(a)
        if not parts:
            return Cell.empty()
        r = _concat_arrays(parts, axis)
        share_all(r)
        return Cell(_2d(r))
    if Str in kinds:
        from .strings import to_str_array
        parts = [to_str_array(v).a for v in vals if not (type(v) is np.ndarray and v.shape == (0, 0))]
        if not parts:
            return Str(np.empty((0, 0), object))
        return Str(_2d(_concat_arrays(parts, axis)))
    if Struct in kinds:
        parts = []
        keys = None
        for v in vals:
            if type(v) is np.ndarray and v.shape == (0, 0):
                continue
            if type(v) is not Struct:
                raise MError('MATLAB:catenate:structFieldBad', 'Concatenation of a struct with a value of another class is not allowed.')
            if v.shape == (0, 0):
                if keys is None:
                    keys = v.keys
                continue
            if keys is None or not parts:
                keys = v.keys
            elif set(keys) != set(v.keys):
                raise MError('MATLAB:catenate:structFieldBad', 'Concatenation of structures requires that they have the same field names.')
            parts.append(v)
        if not parts:
            return Struct.empty((0, 0), keys or [])
        if len(parts) == 1:
            return parts[0]
        f = {}
        shape = None
        for k in keys:
            r = _concat_arrays([p.f[k] if p.f[k].ndim == len(p.shape) else p.f[k].reshape(p.shape) for p in parts], axis)
            r = _2d(r)
            share_all(r)
            f[k] = r
            shape = r.shape
        if shape is None:
            # no fields: the shape alone concatenates
            shs = [np.empty(p.shape, object) for p in parts]
            shape = _2d(_concat_arrays(shs, axis)).shape
        return Struct(shape, f)
    if any(type(v) is SYM for v in vals):
        return SYMOPS.cat(axis, vals)
    if any(isinstance(v, (Obj, FH)) for v in vals):
        from .graphics_base import cat_handles
        return cat_handles(axis, vals)
    had_char = any(type(v) is Char for v in vals)
    vals = _drop_empties(vals)
    if not vals:
        return Char(np.zeros((0, 0), np.uint16)) if had_char else EMPTY()
    if len(vals) == 1 and (type(vals[0]) is Char or not had_char):
        return vals[0]
    cls = _num_cat_class(vals)
    if had_char and cls != 'logical':
        # with characters, numbers become characters (integers and single too);
        # an empty '' still makes them so: ['' 65] is 'A'
        cls = 'char'
    arrs = [_as_np(v) for v in vals]
    if cls == 'char':
        conv = []
        for v, a in zip(vals, arrs):
            if type(v) is Char:
                conv.append(a)
            else:
                if a.dtype.kind == 'c':
                    a = a.real
                conv.append(np.asarray(np.clip(np.nan_to_num(a, nan=0), 0, 65535), F64).astype(np.uint16))
        r = _concat_arrays(conv, axis)
        return Char(_2d(r))
    if cls == 'logical':
        return finish(_concat_arrays(arrs, axis), 'logical')
    if cls == 'double':
        cplx = any(a.dtype.kind == 'c' for a in arrs)
        dt = C128 if cplx else F64
        r = _concat_arrays([a.astype(dt, copy=False) for a in arrs], axis)
        return finish(r, 'double')
    if cls == 'single':
        cplx = any(a.dtype.kind == 'c' for a in arrs)
        dt = np.complex64 if cplx else np.float32
        r = _concat_arrays([a.astype(dt) for a in arrs], axis)
        return _2d(r)
    # integer: each converted (doubles rounded and saturated)
    conv = []
    for a in arrs:
        if a.dtype == INT_TYPES[cls]:
            conv.append(a)
        else:
            conv.append(to_int_class(a.astype(F64) if a.dtype.kind != 'c' else a.real, cls))
    return _2d(_concat_arrays(conv, axis))


def hcat(vals):
    if all(type(v) is float for v in vals):
        if not vals:
            return EMPTY()
        if len(vals) == 1:
            return vals[0]
        return np.array([vals])
    return cat(1, vals)


def vcat(vals):
    if all(type(v) is float for v in vals):
        if not vals:
            return EMPTY()
        if len(vals) == 1:
            return vals[0]
        return np.array(vals).reshape(-1, 1)
    return cat(0, vals)


def matrix(rows):
    """A [ ... ] literal: each row concatenated horizontally, then the rows
    vertically."""
    if len(rows) == 1:
        return hcat(rows[0])
    return vcat([hcat(r) for r in rows])


# ---- string arithmetic --------------------------------------------------------

def str_plus(a, b):
    from .strings import to_str_array
    A = to_str_array(a)
    B = to_str_array(b)
    sa, sb = A.a, B.a
    sa2, sb2 = align(sa, sb)
    check_bcast(sa2, sb2)
    sa2, sb2 = np.broadcast_arrays(sa2, sb2)
    out = np.empty(sa2.shape, object)
    for i in range(out.size):
        x, y = sa2.flat[i], sb2.flat[i]
        out.flat[i] = None if (x is None or y is None) else x + y
    return Str(_2d(out))


def str_compare(a, b, fn, sym):
    from .strings import to_str_array
    A = to_str_array(a)
    B = to_str_array(b)
    sa, sb = align(A.a, B.a)
    check_bcast(sa, sb)
    sa, sb = np.broadcast_arrays(sa, sb)
    out = np.empty(sa.shape, bool)
    import operator
    pyop = {'==': operator.eq, '~=': operator.ne, '<': operator.lt, '<=': operator.le, '>': operator.gt, '>=': operator.ge}[sym]
    for i in range(out.size):
        x, y = sa.flat[i], sb.flat[i]
        if x is None or y is None:
            out.flat[i] = (sym == '~=')
        else:
            out.flat[i] = pyop(x, y)
    out = _2d(out)
    return bool(out.reshape(-1)[0]) if out.size == 1 else out
