"""dictionary: keys to values, a value (not a handle) in the order the keys
were put in. The keys are text (kept as strings) or numbers or logicals; each
value is one element of the values' class (a number, a string, a cell, a
struct ...). d(keys) looks up, d(keys) = values puts in (a new dictionary),
d(keys) = [] takes out, d{keys} gives the contents of cell values. An empty
dictionary() has no key and value types until something is put in.

The functions keys, values, isKey and remove (containers.Map's) take a
dictionary too; insert, lookup, numEntries, isConfigured, entries and types
are its own.
"""
import numpy as np

from . import bi, REG
from ._util import err, is_str
from ..values import MError, Obj, Char, Str, Cell, Struct, EMPTY, class_of, numel, py_str, share, is_empty_double
from .. import runtime as R

_NUMERIC = {'double', 'single', 'int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64', 'logical'}


class DictObj(Obj):
    __slots__ = ('d', 'ktype', 'vtype')
    cls = 'dictionary'
    is_handle = False
    own_assign = True

    def __init__(self, ktype=None, vtype=None, d=None):
        self.d = dict(d or {})        # key (str, float or bool) -> a 1-by-1 value
        self.ktype = ktype            # 'string', a number class or 'logical'; None: not configured
        self.vtype = vtype

    def value_copy(self):
        return DictObj(self.ktype, self.vtype, self.d)

    # ---- keys and values ---------------------------------------------------------------------------------
    def keys_of(self, k, configure=False):
        """A key argument as a list of Python keys (and its shape)."""
        if is_str(k) or type(k) is Str or (type(k) is Cell and all(is_str(x) for x in k.a.flat)):
            kt = 'string'
            if type(k) is Str:
                items = [s for s in k.a.reshape(-1, order='F')]
                shape = k.a.shape
            elif type(k) is Cell:
                items = [py_str(x) for x in k.a.reshape(-1, order='F')]
                shape = k.a.shape
            else:
                items, shape = [py_str(k)], (1, 1)
            if any(s is None for s in items):
                raise err('MATLAB:dictionary:MissingKey', 'A missing string cannot be a key of a dictionary.', 'dictionary')
        else:
            a = np.asarray(k) if type(k) in (float, bool, np.ndarray) else None
            if a is None:
                raise err('MATLAB:dictionary:KeyType', f'Keys of class {class_of(k)} are not supported by this dictionary: use text, numbers or logicals.', 'dictionary')
            kt = class_of(k)
            items = [bool(x) if a.dtype == bool else float(x) for x in a.reshape(-1, order='F')]
            shape = a.shape if a.ndim == 2 else (1, a.size)
            if any(x != x for x in items if isinstance(x, float)):
                raise err('MATLAB:dictionary:NaNKey', 'NaN cannot be a key of a dictionary.', 'dictionary')
        if self.ktype is None:
            if configure:
                self.ktype = kt
        elif (self.ktype == 'string') != (kt == 'string') or (self.ktype == 'logical') != (kt == 'logical'):
            raise err('MATLAB:dictionary:KeyTypeMismatch', f'This dictionary takes keys of class {self.ktype}, not {kt}.', 'dictionary')
        return items, shape

    def key_value(self, k):
        if self.ktype == 'string':
            return Str(np.array([[k]], object))
        if self.ktype == 'logical':
            return bool(k)
        return R._builtin(self.ktype, float(k)) if self.ktype != 'double' else float(k)

    def values_of(self, v, n, configure=False):
        """A values argument as n 1-by-1 values (one spread to all)."""
        if self.vtype is None and configure:
            self.vtype = class_of(v)
        elif self.vtype is not None and class_of(v) != self.vtype:
            # converted to the dictionary's class where it can be
            c = class_of(v)
            ok = (self.vtype in _NUMERIC and c in _NUMERIC) or (self.vtype == 'string' and (c == 'char' or c == 'cell'))
            try:
                v = R._builtin(self.vtype, v) if ok else v
            except MError:
                pass
            if class_of(v) != self.vtype:
                raise err('MATLAB:dictionary:ValueTypeMismatch', f'This dictionary takes values of class {self.vtype}, not {class_of(v)}.', 'dictionary')
        m = numel(v)
        if m == 1:
            return [share(v)] * n
        if m != n:
            raise err('MATLAB:dictionary:SizeMismatch', f'There are {n} keys but {m} values.', 'dictionary')
        from ..index import idx
        return [share(idx(v, (float(i + 1),))) for i in range(n)]

    def gather(self, vals, shape):
        """Values side by side in the shape of the keys asked for."""
        if not vals:
            return EMPTY()
        if len(vals) == 1:
            return vals[0]
        r = R._builtin('horzcat', *vals)
        return R._builtin('reshape', r, float(shape[0]), float(int(np.prod(shape)) // shape[0]))

    def missing(self, k):
        shown = f'"{k}"' if isinstance(k, str) else (str(k).lower() if isinstance(k, bool) else f'{k:g}')
        return err('MATLAB:dictionary:KeyNotFound', f'The key {shown} is not in the dictionary.', 'dictionary')

    # ---- indexing ----------------------------------------------------------------------------------------
    def index(self, args):
        if len(args) != 1:
            raise err('MATLAB:dictionary:OneKeyArgument', 'A dictionary is looked up with one set of keys: d(keys).', 'dictionary')
        if self.ktype is None:
            raise err('MATLAB:dictionary:Unconfigured', 'The dictionary has no keys yet.', 'dictionary')
        items, shape = self.keys_of(args[0])
        vals = []
        for k in items:
            if k not in self.d:
                raise self.missing(k)
            vals.append(self.d[k])
        return self.gather(vals, shape)

    def brace(self, args):
        v = self.index(args)
        if type(v) is not Cell:
            raise err('MATLAB:dictionary:BraceNotCell', 'Brace indexing gives the contents of cell values; the values of this dictionary are no cells.', 'dictionary')
        return list(v.a.reshape(-1, order='F'))

    def index_assign(self, args, V):
        if len(args) != 1:
            raise err('MATLAB:dictionary:OneKeyArgument', 'A dictionary is assigned with one set of keys: d(keys) = values.', 'dictionary')
        o = self.value_copy()
        if is_empty_double(V):
            # d(keys) = [] takes them out
            items, _ = o.keys_of(args[0])
            for k in items:
                o.d.pop(k, None)
            return o
        items, _ = o.keys_of(args[0], configure=True)
        for k, v in zip(items, o.values_of(V, len(items), configure=True)):
            o.d[k] = v
        return o

    def getprop(self, name):
        raise err('MATLAB:dictionary:NoProperties', 'A dictionary has no properties: use keys, values, numEntries and the like.', 'dictionary')

    # ---- display -----------------------------------------------------------------------------------------
    def head(self):
        if self.ktype is None:
            return 'dictionary with unset key and value types.'
        n = len(self.d)
        return (f'dictionary ({self.ktype} ⟼ {self.vtype}) with ' + ('no entries.' if n == 0 else f'{n} entr' + ('y:' if n == 1 else 'ies:')))

    def display_lines(self):
        from ..display import summary
        lines = ['  ' + self.head()]
        if self.d:
            lines.append('')
            for k, v in self.d.items():
                lines.append(f'    {summary(self.key_value(k))} ⟼ {summary(v)}')
        return lines

    def summary_text(self, brackets='[]'):
        return f'{brackets[0]}1×1 dictionary{brackets[1]}'


def _dict(v, fn):
    if not isinstance(v, DictObj):
        raise err(f'MATLAB:{fn}:NotADictionary', f'{fn} takes a dictionary.', fn)
    return v


@bi('dictionary', arr=False)
def dictionary(nargout, *args):
    if len(args) % 2:
        raise err('MATLAB:dictionary:KeyValuePairs', 'dictionary takes keys and values in pairs: dictionary(keys, values, ...).', 'dictionary')
    d = DictObj()
    for i in range(0, len(args), 2):
        d = d.index_assign((args[i],), args[i + 1])
    return d


@bi('insert', arr=False)
def insert(nargout, *args):
    """insert(d, keys, values): d with them put in."""
    d = _dict(args[0], 'insert')
    return d.index_assign((args[1],), args[2])


@bi('lookup', arr=False)
def lookup(nargout, *args):
    """lookup(d, keys) and lookup(d, keys, FallbackValue=v): the values (the fallback for keys not there)."""
    d = _dict(args[0], 'lookup')
    fallback = None
    if len(args) >= 4 and is_str(args[2]) and py_str(args[2]).lower() == 'fallbackvalue':
        fallback = args[3]
    if fallback is None:
        return d.index((args[1],))
    items, shape = d.keys_of(args[1])
    return d.gather([d.d.get(k, fallback) for k in items], shape)


@bi('numEntries')
def numEntries(nargout, *args):
    return float(len(_dict(args[0], 'numEntries').d))


@bi('isConfigured')
def isConfigured(nargout, *args):
    return _dict(args[0], 'isConfigured').ktype is not None


@bi('types', arr=False)
def types(nargout, *args):
    d = _dict(args[0], 'types')
    kt = Str(np.array([[d.ktype]], object)) if d.ktype else Str(np.array([[None]], object))
    vt = Str(np.array([[d.vtype]], object)) if d.vtype else Str(np.array([[None]], object))
    return (kt, vt) if nargout >= 2 else kt


@bi('entries', arr=False)
def entries(nargout, *args):
    """entries(d): a table of its keys and values (entries(d, 'struct') a struct array)."""
    d = _dict(args[0], 'entries')
    ks = [d.key_value(k) for k in d.d]
    vs = list(d.d.values())
    form = py_str(args[1]).lower() if len(args) > 1 else 'table'
    if form == 'struct':
        a = np.empty((len(ks), 1), object)
        b = np.empty((len(ks), 1), object)
        for i, (k, v) in enumerate(zip(ks, vs)):
            a[i, 0], b[i, 0] = k, v
        return Struct((len(ks), 1), {'Key': a, 'Value': b})
    K = d.gather(ks, (len(ks), 1)) if ks else EMPTY()
    V = d.gather(vs, (len(vs), 1)) if vs else EMPTY()
    if form == 'cell':
        return R._builtin('horzcat', R._builtin('num2cell', K) if type(K) is not Cell else K, V if type(V) is Cell else R._builtin('num2cell', V))
    return R._builtin('table', K, V, Char.of('VariableNames'), Cell.of_list([Char.of('Key'), Char.of('Value')]))


# keys, values, isKey and remove take a dictionary as well as a containers.Map
def _wrap(name, mine):
    info = REG[name]
    orig = info.fn

    def f(nargout, *args):
        if args and isinstance(args[0], DictObj):
            return mine(nargout, *args)
        return orig(nargout, *args)
    info.fn = f


def _keys(nargout, d, *rest):
    return d.gather([d.key_value(k) for k in d.d], (len(d.d), 1))


def _values(nargout, d, *rest):
    if rest:
        return d.index((rest[0],))
    return d.gather(list(d.d.values()), (len(d.d), 1))


def _iskey(nargout, d, k):
    if d.ktype is None:
        return False
    items, shape = d.keys_of(k)
    r = np.array([x in d.d for x in items], bool).reshape(shape, order='F')
    return bool(r.reshape(-1)[0]) if r.size == 1 else r


def _remove(nargout, d, k):
    o = d.value_copy()
    items, _ = o.keys_of(k)
    for x in items:
        if x not in o.d:
            raise o.missing(x)
        del o.d[x]
    return o


for _n, _f in (('keys', _keys), ('values', _values), ('isKey', _iskey), ('remove', _remove)):
    _wrap(_n, _f)
