"""sprintf and fprintf formatting.

The format is used again from its start while arguments are left, taking
the arguments' elements down the columns. %s takes a whole character
vector; a number given to %s or %c is a character code when it is a whole
number. A number that is not whole given to %d, %i, %u, %x or %o is
written as %e would. Inf and NaN are written as Inf and NaN.
"""
import math
import re

import numpy as np

from ..values import MError, Char, Str, Cell, Struct, FH, Obj, class_of

_CONV = re.compile(r'%(?P<flags>[-+ #0]*)(?P<width>\*|\d+)?(?:\.(?P<prec>\*|\d+))?(?P<len>[lhL]*)(?P<conv>[diouxXfFeEgGcsaA%])')
_ESC = re.compile(r'\\(x[0-9a-fA-F]+|[0-7]{1,3}|.)', re.S)


def unescape(s):
    """The escapes a format understands: \\n \\t \\\\ \\xHH \\ooo and the rest."""
    def rep(m):
        c = m.group(1)
        if c[0] == 'x' and len(c) > 1:
            return chr(int(c[1:], 16))
        if c[0] in '01234567':
            return chr(int(c, 8))
        return {'n': '\n', 't': '\t', '\\': '\\', 'a': '\a', 'b': '\b', 'f': '\f',
                'r': '\r', 'v': '\v', "'": "'", '"': '"'}.get(c, '\\' + c)
    return _ESC.sub(rep, s) if '\\' in s else s


class _Args:
    """The arguments' elements, taken one at a time (a character vector
    can be taken whole)."""

    def __init__(self, args):
        self.items = []
        for a in args:
            t = type(a)
            if t is Char:
                self.items.append(('c', a))
            elif t is Str:
                for s in a.a.reshape(-1, order='F'):
                    self.items.append(('s', '<missing>' if s is None else s))
            elif t is float or t is int:
                self.items.append(('n', [float(a)]))
            elif t is bool:
                self.items.append(('n', [1.0 if a else 0.0]))
            elif t is complex:
                self.items.append(('n', [a.real]))
            elif t is np.ndarray:
                v = a.reshape(-1, order='F')
                if v.dtype.kind == 'c':
                    v = v.real
                if v.dtype.kind in 'iu':
                    self.items.append(('n', [int(x) for x in v]))
                elif v.dtype.kind == 'b':
                    self.items.append(('n', [1.0 if x else 0.0 for x in v]))
                else:
                    self.items.append(('n', [float(x) for x in v]))
            elif t is Cell:
                raise MError('MATLAB:sprintf:InvalidInputType', "Function is not defined for 'cell' inputs.")
            elif t is Struct:
                raise MError('MATLAB:sprintf:InvalidInputType', "Function is not defined for 'struct' inputs.")
            elif isinstance(a, FH):
                raise MError('MATLAB:sprintf:InvalidInputType', "Function is not defined for 'function_handle' inputs.")
            elif isinstance(a, Obj):
                h = getattr(a, 'number_value', None)
                if h is not None:
                    self.items.append(('n', [float(h())]))
                else:
                    raise MError('MATLAB:sprintf:InvalidInputType', f"Function is not defined for '{a.cls}' inputs.")
            else:
                self.items.append(('n', [float(a)]))
        self.i = 0      # which argument
        self.j = 0      # which element of it
        self.taken = 0

    def left(self):
        while self.i < len(self.items):
            k, v = self.items[self.i]
            n = (v.a.size if k == 'c' else 1 if k == 's' else len(v))
            if self.j < n:
                return True
            self.i += 1
            self.j = 0
        return False

    def take_value(self):
        """One element: a number or a one-character string."""
        if not self.left():
            return None
        k, v = self.items[self.i]
        self.taken += 1
        if k == 'c':
            code = int(v.a.reshape(-1, order='F')[self.j])
            self.j += 1
            return ('char', code)
        if k == 's':
            self.j += 1
            return ('str', v)
        x = v[self.j]
        self.j += 1
        return ('num', x)

    def take_string(self):
        """For %s: a whole character vector if one starts here, else one
        element."""
        if not self.left():
            return None
        k, v = self.items[self.i]
        if k == 'c' and self.j == 0:
            self.taken += 1
            self.i += 1
            return ('str', v.str() if v.a.ndim == 2 and v.a.shape[0] <= 1 else ''.join(chr(c) for c in v.a.reshape(-1, order='F')))
        return self.take_value()


def _special(x, flags, width):
    s = 'NaN' if x != x else ('Inf' if x > 0 else '-Inf')
    if '+' in flags and x == x and x > 0:
        s = '+' + s
    return _pad(s, flags, width)


def _pad(s, flags, width):
    if width:
        w = int(width)
        if '-' in flags:
            return s.ljust(w)
        return s.rjust(w)
    return s


def _fmt_num(x, flags, width, prec, conv):
    if isinstance(x, float) and not math.isfinite(x):
        return _special(x, flags, width)
    spec = '%' + flags + (str(width) if width else '') + ('.' + str(prec) if prec is not None else '')
    if conv in 'diu':
        if isinstance(x, float) and x != int(x):
            # not a whole number: written as %e
            return ('%' + flags + (str(width) if width else '') + 'e') % x
        xi = int(x)
        if conv == 'u' and xi < 0:
            return ('%' + flags + (str(width) if width else '') + 'e') % float(x)
        return (spec + 'd') % xi
    if conv in 'xXo':
        if isinstance(x, float) and x != int(x):
            return ('%' + flags + (str(width) if width else '') + 'e') % x
        xi = int(x)
        if xi < 0:
            return ('%' + flags + (str(width) if width else '') + 'e') % float(x)
        return (spec + conv) % xi
    if conv in 'fFeEgG':
        r = (spec + conv) % float(x)
        return r
    if conv in 'aA':
        return float(x).hex()
    return str(x)


def sprintf(fmt, args):
    """The text of a format applied to arguments."""
    fmt = unescape(fmt)
    parts = []
    pos = 0
    pieces = []        # literal text and conversions in order
    for m in _CONV.finditer(fmt):
        if m.start() > pos:
            pieces.append(('lit', fmt[pos:m.start()]))
        if m.group('conv') == '%':
            pieces.append(('lit', '%'))
        else:
            pieces.append(('conv', m))
        pos = m.end()
    if pos < len(fmt):
        pieces.append(('lit', fmt[pos:]))
    a = _Args(args)
    nconv = sum(1 for p in pieces if p[0] == 'conv')
    out = []
    if nconv == 0:
        return ''.join(p[1] for p in pieces)
    first = True
    while True:
        if not first and not a.left():
            break
        stop = False
        for kind, p in pieces:
            if kind == 'lit':
                out.append(p)
                continue
            m = p
            flags = m.group('flags') or ''
            width = m.group('width')
            prec = m.group('prec')
            conv = m.group('conv')
            if width == '*':
                v = a.take_value()
                width = str(int(v[1])) if v and v[0] == 'num' else None
            if prec == '*':
                v = a.take_value()
                prec = str(int(v[1])) if v and v[0] == 'num' else None
            if conv == 's':
                v = a.take_string()
            else:
                v = a.take_value()
            if v is None:
                if first and a.taken == 0:
                    # no arguments at all: the conversions write nothing
                    continue
                stop = True
                break
            vk, val = v
            if conv == 's':
                if vk == 'str':
                    s = val
                elif vk == 'char':
                    s = chr(val)
                else:
                    if isinstance(val, float) and val == int(val) and math.isfinite(val) and val >= 0:
                        s = chr(int(val))
                    elif isinstance(val, int) and val >= 0:
                        s = chr(val)
                    else:
                        s = _fmt_num(val, flags, width, prec, 'e') if math.isfinite(val) else _special(val, flags, width)
                        out.append(s)
                        continue
                if prec is not None:
                    s = s[:int(prec)]
                out.append(_pad(s, flags, width))
            elif conv == 'c':
                if vk == 'char':
                    s = chr(val)
                elif vk == 'str':
                    s = val
                else:
                    if isinstance(val, float) and (not math.isfinite(val) or val != int(val)):
                        out.append(_fmt_num(val, flags, width, prec, 'e'))
                        continue
                    s = chr(int(val))
                out.append(_pad(s, flags, width))
            else:
                if vk == 'char':
                    val = val
                elif vk == 'str':
                    out.append(_pad(val, flags, width))
                    continue
                out.append(_fmt_num(val, flags, width, int(prec) if prec is not None else None, conv))
        first = False
        if stop:
            break
        if not a.left():
            break
    return ''.join(out)


def compose_one(fmt, args):
    return sprintf(fmt, args)
