"""Conversions between text values: char arrays, string arrays, cellstrs
and numbers turned into text (as string() and "a" + 1 do)."""
import math

import numpy as np

from .values import MError, Char, Str, Cell, Struct, FH, Obj, F64, class_of, _2d, py_str


def num_text(x):
    """A number as string() writes it: up to about 5 significant digits for
    non-integers, whole numbers in full."""
    if isinstance(x, (bool, np.bool_)):
        return 'true' if x else 'false'
    if isinstance(x, complex) or isinstance(x, np.complexfloating):
        z = complex(x)
        re = num_text(z.real)
        im = num_text(abs(z.imag))
        return f'{re}{"-" if z.imag < 0 else "+"}{im}i'
    x = float(x)
    if x != x:
        return 'NaN'
    if x in (math.inf, -math.inf):
        return 'Inf' if x > 0 else '-Inf'
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    s = f'{x:.5g}'
    if 'e' in s:
        m, e = s.split('e')
        s = f'{m}e{int(e):+03d}'
    return s


def to_str_array(v):
    """A string array from any value that converts: text, numbers, logicals,
    cellstrs."""
    t = type(v)
    if t is Str:
        return v
    if t is Char:
        a = v.a
        if a.ndim == 2 and a.shape[0] <= 1:
            return Str.of(v.str())
        return Str.from_list(v.row_strs(), (a.shape[0], 1))
    if t is Cell:
        out = np.empty(v.a.shape, object)
        for i, x in enumerate(v.a.flat):
            if type(x) is Char:
                out.flat[i] = x.str()
            elif type(x) is Str and x.a.size == 1:
                out.flat[i] = x.a.flat[0]
            else:
                out.flat[i] = to_str_array(x).a.flat[0] if np.size(to_str_array(x).a) == 1 else None
        return Str(out)
    if t is float or t is int or t is complex or t is bool:
        return Str.of(num_text(v))
    if t is np.ndarray:
        out = np.empty(v.shape, object)
        for i in range(v.size):
            x = v.flat[i]
            out.flat[i] = None if (v.dtype.kind == 'f' and x != x) else num_text(x)
        return Str(_2d(out))
    if isinstance(v, Obj) and hasattr(v, 'to_text'):
        return Str.of(v.to_text())
    raise MError('MATLAB:string:invalidConversion', f'Conversion to string from {class_of(v)} is not possible.')
