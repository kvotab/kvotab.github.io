"""Helpers the builtins share: reading arguments, shaping results."""
import math
import numpy as np

from ..values import (MError, Char, Cell, Struct, Str, FH, Obj, F64, C128, INT_TYPES, DTYPE_CLASS,
                      class_of, scalar_out, _2d, EMPTY, shape_of, numel, py_str, is_text, NOVAL, share,
                      share_all, to_float, to_int)
from ..ops import finish, to_int_class, INT_CLASSES

NUMERIC_CLASSES = {'double', 'single', 'logical', 'char'} | INT_CLASSES


def err(ident, msg=None, fn=None):
    e = MError(ident, msg) if msg is not None else MError('', ident)
    if fn:
        e.fn = fn
    return e


def nargchk(args, lo, hi, fn):
    n = len(args)
    if n < lo:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', fn)
    if hi is not None and n > hi:
        raise err('MATLAB:TooManyInputs', 'Too many input arguments.', fn)


def noout(nargout, fn):
    if nargout > 0:
        raise err('MATLAB:TooManyOutputs', 'Too many output arguments.', fn)


def maxout(nargout, k, fn):
    if nargout > k:
        raise err('MATLAB:TooManyOutputs', 'Too many output arguments.', fn)


def arr(v, fn=None):
    """The numbers of a numeric, logical or char value as a numpy array (2-D
    or more, dtype kept)."""
    t = type(v)
    if t is np.ndarray:
        return v
    if t is float:
        return np.array([[v]])
    if t is bool:
        return np.array([[v]])
    if t is complex:
        return np.array([[v]], C128)
    if t is Char:
        return v.a
    if t is int:
        return np.array([[float(v)]])
    if isinstance(v, (np.floating, np.integer, np.bool_, np.complexfloating)):
        return np.array([[v]])
    raise err('MATLAB:invalidType', f'Invalid data type. Input arguments must be numeric or logical, not {class_of(v)}.' if t is not Cell else
              'Invalid data type. First argument must be numeric or logical.', fn)


def darr(v, fn=None):
    """As float64 (complex128 when complex)."""
    a = arr(v, fn)
    if a.dtype.kind == 'c':
        return a.astype(C128, copy=False)
    if a.dtype != F64:
        return a.astype(F64)
    return a


def cls(v):
    return class_of(v)


def out(a, klass=None):
    """A numpy result as the value it stands for: at least 2-D, 1x1 double
    and logical as Python scalars."""
    if type(a) is not np.ndarray:
        if isinstance(a, (np.floating, np.integer)):
            if klass in INT_CLASSES or klass == 'single':
                return finish(np.array([[a]]), klass)
            return float(a)
        if isinstance(a, np.bool_):
            return bool(a)
        if isinstance(a, np.complexfloating):
            z = complex(a)
            return z.real if z.imag == 0 else z
        if isinstance(a, (int,)) and not isinstance(a, bool):
            return float(a)
        return a
    if klass is not None:
        return finish(a, klass)
    a = _2d(a)
    k = a.dtype.kind
    if k == 'c':
        if not np.any(a.imag):
            a = np.ascontiguousarray(a.real)
        elif a.dtype == np.complex64:
            pass
    if a.size == 1 and a.ndim == 2:
        return scalar_out(a)
    return a


def like_class(r, v):
    """A numpy result in the class of the value it came from."""
    c = class_of(v)
    if c in ('double', 'logical', 'char'):
        return out(r)
    return finish(r, c)


def is_str(v):
    return is_text(v)


def sval(v, what='argument', fn=None):
    try:
        return py_str(v, what)
    except MError as e:
        e.fn = fn
        raise


def opt_str(v):
    """The text of an option argument, or None if it is not text."""
    t = type(v)
    if t is Char:
        if v.a.ndim == 2 and v.a.shape[0] <= 1:
            return v.str()
        return None
    if t is Str and v.a.size == 1:
        return v.a.flat[0]
    return None


def num(v, what='input', fn=None):
    return to_float(v, what)


def ival(v, what='input', fn=None):
    try:
        x = to_float(v, what)
    except MError as e:
        e.fn = fn
        raise
    if x != x or abs(x) == math.inf or x != int(x):
        raise err('MATLAB:expectedInteger', f'The {what} must be an integer.' if what else 'Expected an integer.', fn)
    return int(x)


def dims_from(args, fn, allow_class=True):
    """zeros(n), zeros(m,n,...), zeros([m n ...]) with an optional class name
    or 'like', x at the end: (shape, class, complex?)."""
    args = list(args)
    klass = 'double'
    cplx = False
    if allow_class and args:
        # 'like', p
        if len(args) >= 2 and opt_str(args[-2]) is not None and opt_str(args[-2]).lower() == 'like':
            p = args[-1]
            klass = class_of(p)
            cplx = type(p) is complex or (type(p) is np.ndarray and p.dtype.kind == 'c')
            args = args[:-2]
        else:
            s = opt_str(args[-1])
            if s is not None:
                klass = s.lower() if s.lower() != 'logical' else 'logical'
                if klass not in NUMERIC_CLASSES and klass != 'logical':
                    raise err('MATLAB:invalidClass', f"Invalid data type. Use one of the numeric classes or 'logical', not '{s}'." if False else f"The class name '{s}' is not supported here.", fn)
                args = args[:-1]
    if not args:
        return (1, 1), klass, cplx
    if len(args) == 1:
        v = args[0]
        a = arr(v, fn)
        if a.size == 1:
            n = _dim_val(a.reshape(-1)[0], fn)
            return (n, n), klass, cplx
        if a.ndim == 2 and a.shape[0] == 1 or a.ndim == 2 and a.shape[1] == 1:
            dims = [_dim_val(x, fn) for x in a.reshape(-1)]
            return _norm_shape(dims), klass, cplx
        raise err('MATLAB:getReshapeDims:notRealInt', 'Size vector must be a row vector with real elements.', fn)
    dims = []
    for v in args:
        a = arr(v, fn)
        if a.size != 1:
            raise err('MATLAB:sizeDimensionsMustBeScalar', 'Size inputs must be scalar.', fn)
        dims.append(_dim_val(a.reshape(-1)[0], fn))
    return _norm_shape(dims), klass, cplx


def _dim_val(x, fn):
    try:
        f = float(x.real if isinstance(x, complex) else x)
    except Exception:
        raise err('MATLAB:invalidType', 'Size inputs must be numeric.', fn)
    if f != f:
        raise err('MATLAB:NonIntegerInput', 'Size inputs must be integers.' if True else '', fn)
    if f != math.floor(f) and abs(f) != math.inf:
        raise err('MATLAB:NonIntegerInput', 'Size inputs must be integers.', fn)
    if abs(f) == math.inf:
        raise err('MATLAB:array:SizeLimitExceeded', 'Requested array exceeds the maximum possible variable size.', fn)
    return max(0, int(f))


def _norm_shape(dims):
    dims = list(dims)
    if len(dims) == 1:
        dims = [dims[0], dims[0]]
    while len(dims) > 2 and dims[-1] == 1:
        dims.pop()
    return tuple(dims)


def np_dtype(klass, cplx=False):
    if klass == 'double':
        return C128 if cplx else F64
    if klass == 'single':
        return np.complex64 if cplx else np.float32
    if klass == 'logical':
        return np.bool_
    if klass == 'char':
        return np.uint16
    if klass in INT_TYPES:
        return INT_TYPES[klass]
    raise err('MATLAB:invalidClass', f'Unknown class {klass}.')


def make(a, klass):
    """A numpy array of a class as the value."""
    if klass == 'char':
        return Char(_2d(a.astype(np.uint16)))
    if klass == 'double':
        return out(a.astype(F64) if a.dtype.kind != 'c' else a.astype(C128))
    if klass == 'logical':
        return out(a.astype(bool))
    return finish(a, klass)


def first_dim(shape):
    """The first dimension that is not 1 (0-based), as reductions use by
    default."""
    for i, d in enumerate(shape):
        if d != 1:
            return i
    return 0


def dim_arg(v, fn):
    s = opt_str(v)
    if s is not None:
        if s.lower() == 'all':
            return 'all'
        raise err('MATLAB:invalidDim', f"Invalid option '{s}'.", fn)
    d = ival(v, 'dimension', fn)
    if d < 1:
        raise err('MATLAB:getdimarg:dimensionMustBePositiveInteger', 'Dimension argument must be a positive integer scalar within indexing range.', fn)
    return d - 1


def expand_dims(a, dim):
    """a with at least dim+1 dimensions."""
    if a.ndim <= dim:
        return a.reshape(a.shape + (1,) * (dim + 1 - a.ndim))
    return a


def reduce(a, dim, fn, empty_value=0.0, keepdims=True):
    """Apply fn(a, axis) along a dimension the way the language's
    reductions do: the first non-singleton dimension by default, [] summing
    to one value."""
    if dim == 'all':
        return fn(a.reshape(-1), 0)
    if dim is None:
        if a.ndim == 2 and a.shape == (0, 0):
            r = fn(np.zeros((0, 1), a.dtype), 0)
            return r
        dim = first_dim(a.shape)
    a = expand_dims(a, dim)
    r = fn(a, dim)
    if keepdims and r.ndim < a.ndim:
        r = np.expand_dims(r, dim)
    return r


def strip_flags(args, flags):
    """Pull known text options out of an argument list: (rest, found)."""
    rest = []
    found = {}
    for a in args:
        s = opt_str(a)
        if s is not None and s.lower() in flags:
            found[s.lower()] = True
            continue
        rest.append(a)
    return rest, found


def as_bool(v):
    t = type(v)
    if t is bool:
        return v
    if t is float:
        return v != 0
    a = arr(v)
    return bool(np.all(a != 0)) and a.size > 0


def cellstr_list(v, fn=None):
    """A list of str from a cell array of char vectors (or text)."""
    from ..values import text_list
    return text_list(v)


def to_cell_of_char(lst, shape=None):
    c = Cell.of_list([Char.of(s) for s in lst], shape)
    return c


def bool_out(a):
    a = np.asarray(a, bool)
    a = _2d(a)
    return bool(a.reshape(-1)[0]) if a.size == 1 else a


def check_real(a, fn, what='Input'):
    if a.dtype.kind == 'c':
        raise err('MATLAB:expectedReal', f'{what} must be real.', fn)
