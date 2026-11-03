"""Value objects of the built-in classes that are arrays of one kind of
element: datetime, duration, calendarDuration and categorical
(builtins/timetypes.py and builtins/categoricals.py). Each holds its
elements in NumPy arrays of one shape (ARRAYS, the per-element arrays)
beside what all its elements share (a display format, a time zone, the
categories). They never change in place: indexing, assignment and
concatenation make new ones, so a value can be held in many places.

install() connects them to the engine: operators (ops), concatenation and
ranges, the indexing paths (index, through Obj's index / index_assign), for
loops, display; wrap_builtins() puts each class's versions of the
built-in functions (sort, min, unique, ...) in front of the full-array
ones."""
import copy

import numpy as np

from .values import Obj, MError, Char, Str, Cell, Struct, numel, shape_of, is_empty_double, size_str


def _2d(a):
    a = np.asarray(a)
    if a.ndim == 0:
        return a.reshape(1, 1)
    if a.ndim == 1:
        return a.reshape(1, -1)
    return a


class VObj(Obj):
    is_handle = False
    is_missing = False
    cls = 'object'
    ARRAYS = ('a',)
    FILLS = {'a': np.nan}

    # ---- making new ones ----------------------------------------------------------------------------------
    def with_arrays(self, **arrays):
        """A copy sharing the metadata, with new element arrays."""
        o = copy.copy(self)
        for k, v in arrays.items():
            setattr(o, k, _2d(v) if np.asarray(v).ndim < 2 else np.asarray(v))
        return o

    def mapped(self, fn):
        """The same with fn applied to each element array."""
        return self.with_arrays(**{k: fn(getattr(self, k)) for k in self.ARRAYS})

    def empty_like(self, shape=(0, 0)):
        return self.with_arrays(**{k: np.full(shape, self.FILLS[k], dtype=getattr(self, k).dtype) for k in self.ARRAYS})

    @property
    def shape(self):
        return getattr(self, self.ARRAYS[0]).shape

    def value_copy(self):
        return self.mapped(lambda a: a.copy())

    # ---- converting another value to this class (for assignment, comparison, concatenation) ----------------
    def coerce(self, v):
        """v as a value of this class sharing this one's metadata: an error
        when it cannot be."""
        if type(v) is type(self):
            return v
        raise MError('MATLAB:invalidConversion', f'Unable to convert a value of class {_class(v)} to {self.cls}.')

    # ---- indexing --------------------------------------------------------------------------------------------
    def index(self, args):
        from .index import take
        return self.mapped(lambda a: take(a, args))

    def brace(self, args):
        raise MError('MATLAB:cellRefFromNonCell', f'Brace indexing is not supported for variables of class {self.cls}.')

    def index_assign(self, args, V):
        from .index import _conv_args, _region, _grow, _put
        if is_empty_double(V) and not isinstance(V, VObj):
            return self.delete(args)
        if getattr(V, 'is_missing', False) and not self.is_missing:
            V = V.like(self)
        V = self.coerce(V)
        out = {}
        for k in self.ARRAYS:
            arr = getattr(self, k)
            vals = np.asarray(getattr(V, k))
            if vals.dtype != arr.dtype:
                arr = arr.astype(np.result_type(arr, vals))
            ixs, linear = _conv_args(args)
            ixs2, new_shape, region = _region(arr.shape, ixs, linear, vals.shape, vals.size)
            arr = _grow(arr.copy(), new_shape, self.FILLS[k])
            _put(arr, ixs2, linear, region, vals, vals.shape)
            out[k] = arr
        return self.merged(V).with_arrays(**out)

    def merged(self, other):
        """The metadata after `self(i) = other` (categorical adds other's categories)."""
        return self

    def delete(self, args):
        from .index import delete
        S = Struct(self.shape, {k: getattr(self, k) for k in self.ARRAYS})
        r = delete(S, args)
        return self.with_arrays(**{k: r.f[k] for k in self.ARRAYS})

    def columns(self):
        """For loops: one column at a time."""
        a = getattr(self, self.ARRAYS[0])
        n = a.shape[1] if a.ndim > 1 else a.size
        return [self.mapped(lambda x, j=j: x.reshape(x.shape[0], -1, order='F')[:, j:j + 1]) for j in range(n)] if a.size else []

    # ---- shape ---------------------------------------------------------------------------------------------
    def transposed(self):
        if len(self.shape) > 2:
            raise MError('MATLAB:transpose:ndArray', 'Transpose on ND array is not defined. Use PERMUTE instead.')
        return self.mapped(lambda a: a.T.copy())

    @classmethod
    def concat(cls, axis, vals):
        """[a, b] (axis 1) or [a; b] (axis 0) with at least one value of this class."""
        first = next(v for v in vals if isinstance(v, cls))
        parts = []
        for v in vals:
            if (type(v) is np.ndarray and v.size == 0 and v.shape == (0, 0)) or (isinstance(v, VObj) and v.shape == (0, 0)):
                continue
            parts.append(first.coerce(v))
        if not parts:
            return first.empty_like()
        res = parts[0]
        for p in parts[1:]:
            res = res.merged(p)
        out = {}
        for k in cls.ARRAYS:
            arrs = [np.asarray(getattr(res.coerce(p) if p is not res else p, k)) for p in parts]
            try:
                out[k] = np.concatenate(arrs, axis=axis)
            except ValueError:
                raise MError('MATLAB:catenate:dimensionMismatch', 'Dimensions of arrays being concatenated are not consistent.')
        return res.with_arrays(**out)

    # ---- display ---------------------------------------------------------------------------------------------
    def elem_strings(self):
        """Each element as the Command Window shows it (an array of str, the elements' shape)."""
        raise NotImplementedError

    def _grid(self, indent='   '):
        s = np.asarray(self.elem_strings(), object)
        if s.ndim > 2:
            s = s.reshape(s.shape[0], -1, order='F')
        if s.size == 0:
            return []
        w = [max(len(x) for x in s[:, j]) for j in range(s.shape[1])]
        return [indent + '   '.join(s[i, j].rjust(w[j]) for j in range(s.shape[1])).rstrip() for i in range(s.shape[0])]

    def display_lines(self):
        from .display import FMT
        loose = FMT['spacing'] == 'loose'
        if numel(self) == 0:
            return [f'  {size_str(self.shape)} empty {self.cls} array']
        head = f'  {self.cls}' if numel(self) == 1 else f'  {size_str(self.shape)} {self.cls} array'
        return [head] + ([''] if loose else []) + self._grid()

    def disp_lines(self):
        return self._grid()

    def summary_text(self, brackets='[]'):
        """In a cell or a struct: a scalar shows its value, an array its size."""
        if numel(self) == 1:
            s = str(np.asarray(self.elem_strings(), object).reshape(-1)[0])
            return f'[{s}]' if brackets == '[]' else s
        t = f'{size_str(self.shape)} {self.cls}'
        return f'[{t}]' if brackets == '[]' else t

    # ---- ordering (sort, min, max, unique, ismember, isequal) -----------------------------------------------
    def key(self):
        """A float array that orders and compares the elements (NaN for missing)."""
        return np.asarray(getattr(self, self.ARRAYS[0]), float)

    def same_meta(self, other):
        """What isequal asks beyond the elements."""
        return True

    # ---- the language's operators: each class defines these -------------------------------------------------
    def binop(self, op, a, b):
        raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for operands of type '{self.cls}'.")

    def unop(self, op):
        if op in (".'", "'"):
            return self.transposed()
        raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for operands of type '{self.cls}'.")

    def colon(self, a, step, b):
        raise MError('MATLAB:UndefinedFunction', f'Ranges are not supported for values of class {self.cls}.')

    # functions the class answers itself (name -> fn(nargout, args)); see wrap_builtins
    FUNCS = {}


def _class(v):
    from .values import class_of
    return class_of(v)


def first_vobj(vals):
    for v in vals:
        if isinstance(v, VObj):
            return v
    return None


class VOps:
    @staticmethod
    def binop(op, a, b):
        o = a if isinstance(a, VObj) else b
        if getattr(a, 'is_missing', False) or getattr(b, 'is_missing', False):
            # missing becomes the missing value of the other operand
            o = a if getattr(a, 'is_missing', False) else b
        return o.binop(op, a, b)

    @staticmethod
    def unop(op, a):
        return a.unop(op)

    @staticmethod
    def cat(axis, vals):
        o = next((v for v in vals if getattr(v, 'is_missing', False)), None) or first_vobj(vals)
        return type(o).concat(axis, vals)

    @staticmethod
    def colon(a, step, b):
        o = first_vobj((a, step, b))
        return o.colon(a, step, b)


# ---- the array functions every class has: shape, order -----------------------------------------------------

def _num_args(args):
    from .builtins._util import darr
    return [np.asarray(darr(a)).reshape(-1).astype(int) for a in args]


def _shape_fn(name):
    from .builtins._util import darr, num, ival

    def fn(nargout, args):
        v = args[0]
        if name == 'reshape':
            if len(args) == 2:
                dims = [int(x) for x in np.asarray(darr(args[1])).reshape(-1)]
            else:
                dims = [None if numel(a) == 0 else int(num(a)) for a in args[1:]]
                if None in dims:
                    known = int(np.prod([d for d in dims if d is not None]))
                    dims[dims.index(None)] = numel(v) // max(known, 1)
            if int(np.prod(dims)) != numel(v):
                raise MError('MATLAB:getReshapeDims:notSameNumel', 'Number of elements must not change. Use [] as one of the size inputs to automatically calculate the appropriate size for that dimension.')
            return v.mapped(lambda a: _2d(a.reshape(dims, order='F')))
        if name == 'repmat':
            reps = [int(x) for x in np.asarray(darr(args[1])).reshape(-1)] if len(args) == 2 else [ival(a) for a in args[1:]]
            if len(reps) == 1:
                reps = reps * 2
            return v.mapped(lambda a: np.tile(a.reshape(a.shape + (1,) * (len(reps) - a.ndim)), reps))
        if name in ('fliplr', 'flipud', 'flip'):
            if name == 'fliplr':
                d = 1
            elif name == 'flipud':
                d = 0
            else:
                d = ival(args[1]) - 1 if len(args) > 1 else next((k for k, s in enumerate(v.shape) if s != 1), 0)
            return v.mapped(lambda a: np.flip(a, axis=d) if d < a.ndim else a)
        if name == 'circshift':
            k = np.asarray(darr(args[1])).reshape(-1).astype(int)
            if len(args) > 2:
                return v.mapped(lambda a: np.roll(a, int(k[0]), axis=ival(args[2]) - 1))
            if k.size == 1:
                d = next((i for i, s in enumerate(v.shape) if s != 1), 0)
                return v.mapped(lambda a: np.roll(a, int(k[0]), axis=d))
            return v.mapped(lambda a: np.roll(a, tuple(int(x) for x in k), axis=tuple(range(k.size))))
        if name in ('permute', 'ipermute'):
            order = [int(x) - 1 for x in np.asarray(darr(args[1])).reshape(-1)]
            if name == 'ipermute':
                order = list(np.argsort(order))
            return v.mapped(lambda a: _2d(np.transpose(a.reshape(a.shape + (1,) * (len(order) - a.ndim)), order)))
        if name == 'squeeze':
            def sq(a):
                if a.ndim <= 2:
                    return a
                s = [d for d in a.shape if d != 1]
                return _2d(a.reshape(s + [1] * (2 - len(s)) if len(s) < 2 else s))
            return v.mapped(sq)
        if name in ('transpose', 'ctranspose'):
            return v.transposed()
        if name == 'rot90':
            k = ival(args[1]) if len(args) > 1 else 1
            return v.mapped(lambda a: np.rot90(a, k))
        return NotImplemented
    return fn


def _order_fn(name):
    from .builtins._util import darr, num, opt_str, ival

    def fn(nargout, args):
        v = args[0]
        if name == 'ismember':
            if len(args) < 2:
                raise MError('MATLAB:minrhs', 'Not enough input arguments.')
            if not isinstance(v, VObj) and isinstance(args[1], VObj):
                # ismember('red', c): the first input read as the second's class
                v = args[1].coerce(v)
        if not isinstance(v, VObj):
            return NotImplemented
        K = v.key()
        if name == 'sort':
            desc = any((opt_str(a) or '').lower() == 'descend' for a in args[1:])
            nums = [a for a in args[1:] if opt_str(a) is None]
            d = ival(nums[0]) - 1 if nums else next((k for k, s in enumerate(v.shape) if s != 1), 0)
            Kd = np.moveaxis(K, d, -1) if d < K.ndim else K
            # missing values last going up and first going down, as NaN; ties in their order
            filler = np.where(np.isnan(Kd), -np.inf, -Kd) if desc else np.where(np.isnan(Kd), np.inf, Kd)
            idx = np.argsort(filler, axis=-1, kind='stable')
            idx = np.moveaxis(idx, -1, d) if d < K.ndim else idx
            r = v.mapped(lambda a: np.take_along_axis(a, idx, axis=d) if d < a.ndim else a)
            return (r, _2d(idx.astype(float) + 1)) if nargout > 1 else r
        if name == 'issorted':
            k = K.reshape(-1, order='F')
            k = k[~np.isnan(k)]
            return bool(np.all(np.diff(k) >= 0))
        if name in ('min', 'max'):
            if len(args) >= 2 and numel(args[1]) and not (opt_str(args[1]) is not None):
                # min(a, b): elementwise, through the class's comparison
                a, b = args[0], args[1]
                o = a if isinstance(a, VObj) else b
                A, B = o.coerce(a), o.coerce(b)
                ka, kb = A.key(), B.key()
                ka, kb = np.broadcast_arrays(ka, kb)
                pick_b = (kb < ka) if name == 'min' else (kb > ka)
                pick_b = pick_b | np.isnan(ka)
                out = {}
                for k_ in o.ARRAYS:
                    xa, xb = np.broadcast_arrays(np.asarray(getattr(A, k_)), np.asarray(getattr(B, k_)))
                    out[k_] = np.where(pick_b, xb, xa)
                return A.with_arrays(**out)
            dim = None
            if len(args) >= 3:
                o3 = opt_str(args[2])
                dim = 'all' if o3 is not None and o3.lower() == 'all' else ival(args[2]) - 1
            if dim == 'all':
                v = v.mapped(lambda a: a.reshape(-1, 1, order='F'))
                K = v.key()
                dim = 0
            if dim is None:
                dim = next((k for k, s in enumerate(v.shape) if s != 1), 0)
            if K.shape[dim] == 0 if dim < K.ndim else False:
                r = v.mapped(lambda a: np.take(a, [], axis=dim))
                return (r, np.zeros(r.shape)) if nargout > 1 else r
            Kc = np.where(np.isnan(K), np.inf if name == 'min' else -np.inf, K)
            pos = np.argmin(Kc, axis=dim) if name == 'min' else np.argmax(Kc, axis=dim)
            allnan = np.all(np.isnan(K), axis=dim)
            pos = np.expand_dims(pos, dim)
            r = v.mapped(lambda a: np.take_along_axis(a, pos, axis=dim))
            idx = pos.astype(float) + 1
            idx = np.where(np.expand_dims(allnan, dim), 1.0, idx)
            return (r, _2d(idx)) if nargout > 1 else r
        if name == 'unique':
            flat = v.mapped(lambda a: a.reshape(-1, order='F'))
            k = flat.key().reshape(-1)
            stable = any((opt_str(a) or '').lower() == 'stable' for a in args[1:])
            ok = ~np.isnan(k)
            vals, first, inv = np.unique(k[ok], return_index=True, return_inverse=True)
            pos_ok = np.flatnonzero(ok)
            firsts = pos_ok[first]
            if stable:
                order = np.argsort(firsts, kind='stable')
                firsts = firsts[order]
                remap = np.empty_like(order)
                remap[order] = np.arange(order.size)
                inv = remap[inv]
            nan_pos = np.flatnonzero(~ok)
            keep = np.concatenate([firsts, nan_pos])
            col = len(v.shape) == 2 and v.shape[0] != 1 or numel(v) == 0
            r = flat.mapped(lambda a: a.reshape(-1)[keep].reshape((-1, 1) if col else (1, -1)))
            if nargout <= 1:
                return r
            ic = np.empty(k.size)
            ic[pos_ok] = inv + 1
            ic[nan_pos] = firsts.size + np.arange(nan_pos.size) + 1
            return r, (keep + 1.0).reshape(-1, 1), ic.reshape(-1, 1)
        if name in ('isequal', 'isequaln'):
            first = args[0]
            for other in args[1:]:
                if shape_of(other) != shape_of(first):
                    return False
                try:
                    o = first.coerce(other) if isinstance(first, VObj) else other.coerce(first)
                except MError:
                    return False
                ka, kb = (first if isinstance(first, VObj) else other.coerce(first)).key(), o.key()
                if name == 'isequaln':
                    same = np.all((ka == kb) | (np.isnan(ka) & np.isnan(kb)))
                else:
                    same = np.all(ka == kb)
                if not same or not first.same_meta(o):
                    return False
            return True
        if name == 'ismember':
            b = args[1]
            o = v
            B = o.coerce(b)
            ka, kb = o.key().reshape(-1, order='F'), B.key().reshape(-1, order='F')
            lut = {}
            for i, x in enumerate(kb):
                if not np.isnan(x) and x not in lut:
                    lut[x] = i + 1
            loc = np.array([lut.get(x, 0) if not np.isnan(x) else 0 for x in ka], float)
            tf = (loc > 0).reshape(v.shape, order='F')
            return (tf, loc.reshape(v.shape, order='F')) if nargout > 1 else tf
        return NotImplemented
    return fn


GENERIC = {}
ANY_INPUT = {'isequal', 'isequaln', 'ismember', 'findgroups', 'max', 'min'}
for _n in ('reshape', 'repmat', 'fliplr', 'flipud', 'flip', 'circshift', 'permute', 'ipermute', 'squeeze', 'transpose',
           'ctranspose', 'rot90'):
    GENERIC[_n] = _shape_fn(_n)
for _n in ('sort', 'issorted', 'min', 'max', 'unique', 'isequal', 'isequaln', 'ismember'):
    GENERIC[_n] = _order_fn(_n)


def wrap_builtins(reg, classes):
    """Put the classes' functions (and the generic ones) in front of the
    built-ins of those names: a call with one of these values among its
    inputs goes to its class (or the generic version); NotImplemented hands
    the call back."""
    from .builtins import Info
    names = set(GENERIC)
    for c in classes:
        names |= set(c.FUNCS)
    for name in names:
        info = reg.get(name)
        if info is None:
            continue
        orig = info.fn

        def make(name, orig, ws, aw):
            def pick(args):
                # the class of the first input answers; for a few functions
                # the class of any input (isequal(x, t), ismember('a', c))
                v = first_vobj(args) if name in ANY_INPUT else (args[0] if args and isinstance(args[0], VObj) else None)
                if v is None:
                    return None
                f = type(v).FUNCS.get(name) or GENERIC.get(name)
                return f
            if aw:
                async def f(*a):
                    args = a[2:] if ws else a[1:]
                    g = pick(args)
                    if g is not None:
                        r = g(a[1] if ws else a[0], args)
                        if r is not NotImplemented:
                            return r
                    return await orig(*a)
            else:
                def f(*a):
                    args = a[2:] if ws else a[1:]
                    g = pick(args)
                    if g is not None:
                        r = g(a[1] if ws else a[0], args)
                        if r is not NotImplemented:
                            return r
                    return orig(*a)
            return f
        reg[name] = Info(info.name, make(name, orig, info.ws, info.aw), info.ws, info.aw, max(info.nout, 3 if name == 'unique' else 2 if name in ('sort', 'min', 'max', 'ismember') else info.nout), info.arr)
    # new names (the classes' own functions that are no built-in yet) are registered by their modules


def install():
    from . import ops, display, index, runtime
    ops.VOBJ = VObj
    ops.VOPS = VOps
    display.VOBJ = VObj
    index.VOBJ = VObj
    runtime.VOBJ = VObj
