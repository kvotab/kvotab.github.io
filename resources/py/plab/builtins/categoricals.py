"""categorical: arrays whose elements are one of a set of named categories
(or undefined). Each element is a code, 1 for the first category and so
on, 0 for undefined; the categories, whether they are ordered (ordinal)
and whether new ones may be added (protected) are shared by the array. A
value object (vobj.py)."""
import numpy as np

from . import bi
from ._util import err, nargchk, darr, out, num, opt_str, is_str, sval, ival
from ..values import MError, Char, Str, Cell, F64, numel, shape_of, class_of, text_list
from ..vobj import VObj, _2d


def _names_of(v):
    """The text of each element of a text or numeric value, in column order, None for missing."""
    t = type(v)
    if t in (Char, Str, Cell):
        if t is Char:
            rows = v.row_strs() if v.a.shape[0] > 1 else [v.str()]
            return [r.rstrip() if r.strip() else None for r in rows], (len(rows), 1) if v.a.shape[0] > 1 else (1, 1)
        if t is Str:
            vals = [None if s is None or s == '' else s for s in v.a.reshape(-1, order='F')]
            return vals, v.a.shape
        vals = []
        for x in v.a.reshape(-1, order='F'):
            if type(x) is Char:
                vals.append(x.str() if x.a.size else None)
            elif type(x) is Str and x.a.size == 1:
                vals.append(x.a.flat[0] or None)
            else:
                raise MError('MATLAB:categorical:InvalidData', 'A cell array of data must hold text.')
        return vals, v.a.shape
    raise TypeError


def _num_text(x):
    """A number as a category name (as num2str would write it)."""
    if not np.isfinite(x):
        raise MError('MATLAB:categorical:NonFiniteValueset', 'A category cannot be NaN or Inf: such values are undefined.')
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return f'{x:.5g}'


class Categorical(VObj):
    cls = 'categorical'
    ARRAYS = ('a',)
    FILLS = {'a': 0.0}
    FUNCS = {}

    def __init__(self, codes, cats, ordinal=False, protected=False):
        self.a = _2d(np.asarray(codes, float))
        self.cats = list(cats)
        self.ordinal = bool(ordinal)
        self.protected = bool(protected or ordinal)

    def names(self):
        """Each element's category, '<undefined>' for undefined."""
        lut = np.array(['<undefined>'] + self.cats, object)
        return lut[self.a.astype(int)]

    def elem_strings(self):
        return self.names()

    def _grid(self, indent='   '):
        s = np.asarray(self.elem_strings(), object)
        if s.ndim > 2:
            s = s.reshape(s.shape[0], -1, order='F')
        if s.size == 0:
            return []
        w = [max(len(x) for x in s[:, j]) for j in range(s.shape[1])]
        return [indent + '   '.join(s[i, j].ljust(w[j]) for j in range(s.shape[1])).rstrip() for i in range(s.shape[0])]

    def key(self):
        return np.where(self.a == 0, np.nan, self.a)

    def same_meta(self, other):
        return True

    def with_cats(self, cats):
        """The same elements under a list of categories that holds all of this one's."""
        idx = {c: i + 1 for i, c in enumerate(cats)}
        remap = np.array([0.0] + [float(idx[c]) for c in self.cats])
        o = Categorical(remap[self.a.astype(int)], cats, self.ordinal, self.protected)
        return o

    def coerce(self, v):
        """v under this array's categories (new names added unless protected)."""
        if type(v) is Categorical:
            if v.cats == self.cats:
                return v
            new = [c for c in v.cats if c not in self.cats]
            if new and self.protected:
                raise MError('MATLAB:categorical:ProtectedForCombination', f'Cannot add the categories {new} to a protected categorical array.')
            if self.ordinal and v.ordinal and v.cats != self.cats:
                raise MError('MATLAB:categorical:OrdinalCategoriesMismatch', 'Ordinal categorical arrays must have the same categories, in the same order.')
            return v.with_cats(self.cats + new)
        try:
            names, shape = _names_of(v)
        except TypeError:
            if type(v) is np.ndarray and v.dtype.kind == 'f' and np.all(np.isnan(v)):
                return Categorical(np.zeros(shape_of(v)), self.cats, self.ordinal, self.protected)
            raise MError('MATLAB:invalidConversion', f'Unable to use a value of class {class_of(v)} as a categorical.')
        cats = list(self.cats)
        codes = []
        for n in names:
            if n is None or n == '<undefined>':
                codes.append(0.0)
                continue
            if n not in cats:
                if self.protected:
                    raise MError('MATLAB:categorical:ProtectedForAssign', f"Cannot add the new category '{n}' to a protected categorical array.")
                cats.append(n)
            codes.append(float(cats.index(n) + 1))
        return Categorical(np.array(codes).reshape(shape, order='F'), cats, self.ordinal, self.protected)

    def merged(self, other):
        if type(other) is Categorical and other.cats != self.cats:
            new = [c for c in other.cats if c not in self.cats]
            return self.with_cats(self.cats + new) if new else self
        return self

    def index_assign(self, args, V):
        if not (type(V) is np.ndarray and V.size == 0 and V.shape == (0, 0)):
            V = self.coerce(V)
            base = self.merged(V)
            return VObj.index_assign(base, args, V.with_cats(base.cats) if V.cats != base.cats else V)
        return VObj.index_assign(self, args, V)

    @classmethod
    def concat(cls, axis, vals):
        parts = [v for v in vals if not (type(v) is np.ndarray and v.size == 0 and v.shape == (0, 0))]
        first = next(v for v in parts if type(v) is Categorical)
        cats = list(first.cats)
        conv = []
        for p in parts:
            c = Categorical([[0.0]], cats, first.ordinal, first.protected).coerce(p) if type(p) is not Categorical else p
            for n in c.cats:
                if n not in cats:
                    if first.protected:
                        raise MError('MATLAB:categorical:ProtectedForCombination', f"Cannot add the category '{n}' to a protected categorical array.")
                    cats.append(n)
            conv.append(c)
        arrs = [c.with_cats(cats).a if c.cats != cats else c.a for c in conv]
        try:
            a = np.concatenate(arrs, axis=axis)
        except ValueError:
            raise MError('MATLAB:catenate:dimensionMismatch', 'Dimensions of arrays being concatenated are not consistent.')
        return Categorical(a, cats, first.ordinal, first.protected)

    def binop(self, op, a, b):
        if op in ('==', '~='):
            o = a if type(a) is Categorical else b
            try:
                A, B = (a if type(a) is Categorical else _text_cat(a, o)), (b if type(b) is Categorical else _text_cat(b, o))
            except TypeError:
                other = b if type(a) is Categorical else a
                raise MError('MATLAB:categorical:InvalidComparisonTypes', f'A categorical array can be compared with text or with a categorical array, not with a value of class {class_of(other)}.')
            try:
                na, nb = np.broadcast_arrays(np.asarray(A.names(), object), np.asarray(B.names(), object))
            except ValueError:
                raise MError('MATLAB:sizeDimensionsMustMatch', 'Arrays have incompatible sizes for this operation.')
            eq = (na == nb) & (na != '<undefined>') & (nb != '<undefined>')
            return _bool(eq if op == '==' else ~eq)
        if op in ('<', '<=', '>', '>='):
            o = a if type(a) is Categorical else b
            if not o.ordinal:
                raise MError('MATLAB:categorical:NotOrdinal', 'Relational comparisons are not allowed for categorical arrays that are not ordinal.')
            A, B = o.coerce(a), o.coerce(b)
            x, y = np.broadcast_arrays(A.key(), B.key())
            with np.errstate(invalid='ignore'):
                r = {'<': x < y, '<=': x <= y, '>': x > y, '>=': x >= y}[op]
            return _bool(r)
        raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for operands of type 'categorical'.")

    def propnames(self):
        return []


def _text_cat(v, like):
    """Text compared with a categorical: its names, whether or not they are categories."""
    names, shape = _names_of(v)
    cats = list(like.cats)
    codes = []
    for n in names:
        if n is None:
            codes.append(0.0)
            continue
        if n not in cats:
            cats.append(n)
        codes.append(float(cats.index(n) + 1))
    return Categorical(np.array(codes).reshape(shape, order='F'), cats)


def _bool(r):
    r = np.asarray(r, bool)
    if r.ndim < 2:
        r = r.reshape(1, -1) if r.ndim == 1 else r.reshape(1, 1)
    return bool(r.reshape(-1)[0]) if r.size == 1 and r.shape == (1, 1) else r


def _texts(v, fn):
    """A list of names from text (char, cellstr, string)."""
    if type(v) is Categorical:
        return [n for n in v.names().reshape(-1, order='F')]
    if type(v) not in (Char, Str, Cell):
        raise err(f'MATLAB:{fn}:InvalidNames', 'The names must be text.', fn)
    return text_list(v)


def _need(v, fn):
    if type(v) is not Categorical:
        raise err(f'MATLAB:{fn}:InvalidInput', 'The first input must be a categorical array.', fn)
    return v


@bi('categorical', arr=False)
def categorical(nargout, *args):
    """categorical(data), categorical(data, valueset),
    categorical(data, valueset, catnames), with 'Ordinal' and 'Protected'
    (true or false): the data's values as categories, in sorted order
    unless valueset gives them; missing values ('', <missing>, NaN) are
    undefined."""
    data = list(args)
    opts = {}
    while len(data) >= 3 and opt_str(data[-2]) is not None and opt_str(data[-2]).lower() in ('ordinal', 'protected'):
        opts[opt_str(data[-2]).lower()] = bool(num(data[-1]))
        data = data[:-2]
    if len(data) == 2 and opt_str(data[0]) is not None and opt_str(data[0]).lower() in ('ordinal', 'protected'):
        pass
    if not data:
        return Categorical(np.zeros((0, 0)), [])
    v = data[0]
    ordinal = opts.get('ordinal', False)
    protected = opts.get('protected', ordinal)
    if type(v) is Categorical and len(data) == 1:
        return Categorical(v.a, v.cats, opts.get('ordinal', v.ordinal), opts.get('protected', v.protected or opts.get('ordinal', v.ordinal)))
    if type(v) is Categorical:
        v = Str.from_list([None if n == '<undefined>' else n for n in v.names().reshape(-1, order='F')], v.shape)
    # the values as keys: text, or numbers (logical as numbers)
    if type(v) in (Char, Str, Cell):
        vals, shape = _names_of(v)
        keys = vals
        numeric = False
    else:
        a = np.asarray(darr(v))
        shape = a.shape
        flat = a.reshape(-1, order='F').astype(float)
        keys = [None if np.isnan(x) else float(x) for x in flat]
        numeric = True
    if len(data) > 1:
        vs = data[1]
        if numeric:
            valueset = [float(x) for x in np.asarray(darr(vs)).reshape(-1, order='F')]
        else:
            valueset = _texts(vs, 'categorical')
        if len(set(valueset)) != len(valueset):
            raise err('MATLAB:categorical:NonUniqueValueset', 'valueset must not repeat a value.', 'categorical')
    else:
        present = sorted({k for k in keys if k is not None}, key=(lambda x: x) if numeric else (lambda s: s))
        valueset = present
    if len(data) > 2:
        names = _texts(data[2], 'categorical')
        if len(names) != len(valueset):
            raise err('MATLAB:categorical:NamesValuesetSize', 'catnames must have one name for each value of valueset.', 'categorical')
    else:
        names = [_num_text(x) for x in valueset] if numeric else list(valueset)
    # names repeated (several values to one category): the categories are the distinct names
    cats = []
    for n in names:
        if n not in cats:
            cats.append(n)
    lut = {val: float(cats.index(n) + 1) for val, n in zip(valueset, names)}
    codes = np.array([lut.get(k, 0.0) if k is not None else 0.0 for k in keys]).reshape(shape, order='F')
    return Categorical(codes, cats, ordinal, protected)


@bi('categories', arr=False)
def categories(nargout, *args):
    nargchk(args, 1, 1, 'categories')
    c = _need(args[0], 'categories')
    return Cell.of_list([Char.of(n) for n in c.cats], (len(c.cats), 1))


@bi('iscategorical', arr=False)
def iscategorical(nargout, *args):
    nargchk(args, 1, 1, 'iscategorical')
    return type(args[0]) is Categorical


@bi('isordinal', arr=False)
def isordinal(nargout, *args):
    nargchk(args, 1, 1, 'isordinal')
    return _need(args[0], 'isordinal').ordinal


@bi('isprotected', arr=False)
def isprotected(nargout, *args):
    nargchk(args, 1, 1, 'isprotected')
    return _need(args[0], 'isprotected').protected


@bi('isundefined', arr=False)
def isundefined(nargout, *args):
    nargchk(args, 1, 1, 'isundefined')
    return _bool(_need(args[0], 'isundefined').a == 0)


@bi('iscategory', arr=False)
def iscategory(nargout, *args):
    nargchk(args, 2, 2, 'iscategory')
    c = _need(args[0], 'iscategory')
    names = _texts(args[1], 'iscategory')
    r = np.array([n in c.cats for n in names])
    return _bool(r.reshape(shape_of(args[1]) if type(args[1]) in (Cell, Str) else (1, 1)))


@bi('countcats', arr=False)
def countcats(nargout, *args):
    """countcats(c): how many elements are in each category, along the first
    dimension that is not 1 (countcats(c, dim) along dim)."""
    nargchk(args, 1, 2, 'countcats')
    c = _need(args[0], 'countcats')
    a = c.a
    d = ival(args[1], 'dim', 'countcats') - 1 if len(args) > 1 else next((k for k, s in enumerate(a.shape) if s != 1), 0)
    if d < 0 or d >= 31:
        raise err('MATLAB:getdimarg:dimensionMustBePositiveInteger', 'Dimension argument must be a positive integer scalar within indexing range.', 'countcats')
    if d >= a.ndim:
        a = a.reshape(a.shape + (1,) * (d + 1 - a.ndim))
    k = len(c.cats)
    am = np.moveaxis(a, d, -1)
    counts = np.stack([(am == i + 1).sum(axis=-1) for i in range(k)], axis=-1) if k else np.zeros(am.shape[:-1] + (0,))
    r = np.moveaxis(counts, -1, d).astype(float)
    return out(r)


@bi('addcats', arr=False)
def addcats(nargout, *args):
    """addcats(c, names), with 'Before' or 'After' a category."""
    nargchk(args, 2, 4, 'addcats')
    c = _need(args[0], 'addcats')
    new = _texts(args[1], 'addcats')
    if any(n in c.cats for n in new):
        raise err('MATLAB:categorical:addcats:DuplicateCategoryNames', 'The new categories must not be categories already.', 'addcats')
    cats = list(c.cats)
    if len(args) == 4:
        where = sval(args[2], 'Before or After', 'addcats').lower()
        ref = sval(args[3], 'category', 'addcats')
        if ref not in cats:
            raise err('MATLAB:categorical:addcats:UnrecognizedCategory', f"'{ref}' is not a category.", 'addcats')
        pos = cats.index(ref) + (1 if where == 'after' else 0)
        cats[pos:pos] = new
    elif c.ordinal:
        raise err('MATLAB:categorical:addcats:NoBeforeOrAfter', "Give 'Before' or 'After' to add categories to an ordinal categorical array.", 'addcats')
    else:
        cats += new
    return c.with_cats(cats)


@bi('removecats', arr=False)
def removecats(nargout, *args):
    """removecats(c, names): the categories gone, their elements undefined;
    removecats(c) removes the categories no element is in."""
    nargchk(args, 1, 2, 'removecats')
    c = _need(args[0], 'removecats')
    if len(args) > 1:
        drop = set(_texts(args[1], 'removecats'))
    else:
        used = set(np.unique(c.a[c.a > 0]).astype(int).tolist())
        drop = {n for i, n in enumerate(c.cats) if i + 1 not in used}
    keep = [n for n in c.cats if n not in drop]
    remap = np.array([0.0] + [float(keep.index(n) + 1) if n in keep else 0.0 for n in c.cats])
    return Categorical(remap[c.a.astype(int)], keep, c.ordinal, c.protected)


@bi('mergecats', arr=False)
def mergecats(nargout, *args):
    """mergecats(c, oldcats, newcat): the categories made one (named newcat,
    or the first of oldcats), where the first of them stood."""
    nargchk(args, 2, 3, 'mergecats')
    c = _need(args[0], 'mergecats')
    old = _texts(args[1], 'mergecats')
    if any(n not in c.cats for n in old):
        raise err('MATLAB:categorical:mergecats:UnrecognizedCategory', 'The categories to merge must be categories of the array.', 'mergecats')
    new = sval(args[2], 'new category', 'mergecats') if len(args) > 2 else old[0]
    first = min(c.cats.index(n) for n in old)
    cats = []
    for i, n in enumerate(c.cats):
        if i == first:
            cats.append(new)
        elif n not in old and n != new:
            cats.append(n)
    remap = np.array([0.0] + [float(cats.index(new if n in old else n) + 1) for n in c.cats])
    return Categorical(remap[c.a.astype(int)], cats, c.ordinal, c.protected)


@bi('renamecats', arr=False)
def renamecats(nargout, *args):
    """renamecats(c, newnames) or renamecats(c, oldnames, newnames)."""
    nargchk(args, 2, 3, 'renamecats')
    c = _need(args[0], 'renamecats')
    if len(args) == 2:
        new = _texts(args[1], 'renamecats')
        if len(new) != len(c.cats):
            raise err('MATLAB:categorical:renamecats:IncorrectNumNames', 'Give one new name for each category.', 'renamecats')
        cats = new
    else:
        old, new = _texts(args[1], 'renamecats'), _texts(args[2], 'renamecats')
        if len(old) != len(new) or any(n not in c.cats for n in old):
            raise err('MATLAB:categorical:renamecats:InvalidNames', 'Give existing categories and as many new names.', 'renamecats')
        m = dict(zip(old, new))
        cats = [m.get(n, n) for n in c.cats]
    if len(set(cats)) != len(cats):
        raise err('MATLAB:categorical:renamecats:DuplicateNames', 'The new names must not repeat.', 'renamecats')
    return Categorical(c.a, cats, c.ordinal, c.protected)


@bi('reordercats', arr=False)
def reordercats(nargout, *args):
    """reordercats(c): the categories in alphabetical order; reordercats(c,
    neworder) by names or by their positions."""
    nargchk(args, 1, 2, 'reordercats')
    c = _need(args[0], 'reordercats')
    if len(args) == 1:
        cats = sorted(c.cats)
    elif type(args[1]) in (Char, Str, Cell):
        cats = _texts(args[1], 'reordercats')
    else:
        pos = [int(x) - 1 for x in np.asarray(darr(args[1])).reshape(-1)]
        cats = [c.cats[p] for p in pos]
    if sorted(cats) != sorted(c.cats):
        raise err('MATLAB:categorical:reordercats:InvalidNeworder', 'The new order must hold every category once.', 'reordercats')
    return c.with_cats(cats)


@bi('setcats', arr=False)
def setcats(nargout, *args):
    """setcats(c, newcats): the categories set to newcats; elements of other
    categories become undefined."""
    nargchk(args, 2, 2, 'setcats')
    c = _need(args[0], 'setcats')
    cats = _texts(args[1], 'setcats')
    remap = np.array([0.0] + [float(cats.index(n) + 1) if n in cats else 0.0 for n in c.cats])
    return Categorical(remap[c.a.astype(int)], cats, c.ordinal, c.protected)


# ---- the existing functions on categorical arrays --------------------------------------------------------

def _cellstr(nargout, args):
    c = args[0]
    return Cell.of_list([Char.of(n) for n in c.names().reshape(-1, order='F')], c.shape)


def _string(nargout, args):
    c = args[0]
    return Str.from_list([None if n == '<undefined>' else n for n in c.names().reshape(-1, order='F')], c.shape)


def _char(nargout, args):
    c = args[0]
    return Char.rows([n for n in c.names().reshape(-1, order='F')])


def _double(nargout, args):
    c = args[0]
    return out(np.where(c.a == 0, np.nan, c.a))


def _summary(nargout, args):
    """summary(c): each category and how many elements are in it."""
    from .. import runtime as R
    c = args[0]
    counts = [int(np.sum(c.a == i + 1)) for i in range(len(c.cats))]
    undef = int(np.sum(c.a == 0))
    names = list(c.cats) + (['<undefined>'] if undef else [])
    vals = counts + ([undef] if undef else [])
    w = max([len(n) for n in names] + [1])
    lines = [f'     {n.ljust(w)}      {v}' for n, v in zip(names, vals)]
    R.write('\n'.join(lines) + '\n')
    return None


def _findgroups(nargout, args):
    c = args[0]
    if len(args) > 1 or type(c) is not Categorical:
        return NotImplemented
    present = sorted(set(c.a[c.a > 0].astype(int).tolist()))
    lut = np.full(len(c.cats) + 1, np.nan)
    for k, code in enumerate(present):
        lut[code] = k + 1
    g = lut[c.a.astype(int)]
    if nargout > 1:
        return out(g), Categorical(np.array(present, float).reshape(-1, 1), c.cats, c.ordinal, c.protected)
    return out(g)


def _histcounts(nargout, args):
    c = args[0]
    if type(c) is not Categorical:
        return NotImplemented
    cats = c.cats if len(args) < 2 else _texts(args[1], 'histcounts')
    counts = np.array([np.sum(c.names() == n) for n in cats], float).reshape(1, -1)
    if nargout > 1:
        return out(counts), Cell.of_list([Char.of(n) for n in cats], (1, len(cats)))
    return out(counts)


@bi('summary', arr=False)
def summary(nargout, *args):
    """summary(c): each category of a categorical array and how many elements are in it."""
    nargchk(args, 1, 1, 'summary')
    if type(args[0]) is not Categorical:
        raise err('MATLAB:summary:InvalidInput', 'summary takes a categorical array or a table.', 'summary')
    return _summary(nargout, args)


Categorical.FUNCS = {'cellstr': _cellstr, 'string': _string, 'char': _char, 'double': _double, 'summary': _summary,
                     'findgroups': _findgroups, 'histcounts': _histcounts}


def classes():
    return (Categorical,)
