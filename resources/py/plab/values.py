"""The values a program works with, and how they are held in Python.

    double      float (a real scalar), complex (a complex scalar), or a
                numpy array of float64 / complex128 with two or more
                dimensions
    logical     bool, or a numpy bool array
    single      numpy float32 / complex64 array (a 1x1 array for a scalar)
    int8 ...    numpy integer arrays (a 1x1 array for a scalar)
    char        Char: a uint16 array of UTF-16 code units
    string      Str: an object array of Python str (None = <missing>)
    cell        Cell: an object array of values
    struct      Struct: an object array of dicts, plus the field order
    function_handle   FH (a named function or an anonymous one)

Arrays always have at least two dimensions and no trailing singleton
dimension past the second, as the language's sizes do.

Copies are made on write. Every name, cell and field holding a value holds
the same Python object, and a value that is held in more than one place is
marked shared: the numpy array under it is made read-only. Changing a value
in place (x(3) = 1) first copies it if it is shared, so the other holders
keep what they had, and changes it where it is when it is not, as a loop
filling an array needs.
"""
import numpy as np

F64 = np.float64
C128 = np.complex128

INT_TYPES = {
    'int8': np.int8, 'uint8': np.uint8, 'int16': np.int16, 'uint16': np.uint16,
    'int32': np.int32, 'uint32': np.uint32, 'int64': np.int64, 'uint64': np.uint64,
}
DTYPE_CLASS = {
    np.dtype(np.float64): 'double', np.dtype(np.complex128): 'double',
    np.dtype(np.float32): 'single', np.dtype(np.complex64): 'single',
    np.dtype(np.bool_): 'logical',
}
for _n, _t in INT_TYPES.items():
    DTYPE_CLASS[np.dtype(_t)] = _n
INT_RANGE = {n: (int(np.iinfo(t).min), int(np.iinfo(t).max)) for n, t in INT_TYPES.items()}


class MError(Exception):
    """An error raised by a program or by the runtime, as the language's
    MException carries it: an identifier, a message, and where it came from
    (filled in as it passes through compiled frames)."""

    def __init__(self, identifier, message=None, cause=None):
        if message is None:
            identifier, message = '', identifier
        super().__init__(message)
        self.identifier = identifier or ''
        self.message = message
        self.stack = []          # [(name, file, line)], innermost first
        self.cause = cause or []
        self.fn = None           # the builtin it came from: "Error using <fn>"
        self.exc = None          # the MException value, once made

    def __str__(self):
        return self.message


class Interrupt(BaseException):
    """Ctrl+C: not an error, so try/catch never catches it."""


class Unset:
    """The value of a name that has none: an output never assigned, an
    argument not given."""
    __slots__ = ()

    def __repr__(self):
        return 'NOVAL'


NOVAL = Unset()


class ColonAll:
    """A bare colon used as an index: every element along that dimension."""
    __slots__ = ()

    def __repr__(self):
        return 'COLON'


COLON = ColonAll()


def _2d(a):
    """An array with at least two dimensions and no trailing singleton
    dimension past the second."""
    if a.ndim < 2:
        if a.ndim == 0:
            return a.reshape(1, 1)
        return a.reshape(1, a.shape[0])
    while a.ndim > 2 and a.shape[-1] == 1:
        a = a.reshape(a.shape[:-1])
    return a


class Char:
    """A char array: UTF-16 code units in a uint16 array."""
    __slots__ = ('a', 'ro')

    def __init__(self, a, ro=False):
        self.a = a
        self.ro = ro

    @staticmethod
    def of(s):
        """A 1xN char from a Python str ('' gives 0x0)."""
        if not s:
            return Char(np.zeros((0, 0), np.uint16))
        if s.isascii():
            a = np.frombuffer(s.encode('ascii'), np.uint8).astype(np.uint16)
        else:
            a = np.frombuffer(s.encode('utf-16-le', 'surrogatepass'), '<u2').astype(np.uint16)
        return Char(a.reshape(1, -1))

    @staticmethod
    def rows(lines):
        """A char matrix from strings, padded with blanks."""
        if not lines:
            return Char(np.zeros((0, 0), np.uint16))
        cs = [Char.of(s).a.reshape(-1) for s in lines]
        n = max(c.size for c in cs)
        out = np.full((len(cs), n), 32, np.uint16)
        for i, c in enumerate(cs):
            out[i, :c.size] = c
        return Char(out)

    def str(self):
        """The characters in column-major order, as one Python str (a row
        vector reads as itself)."""
        a = self.a
        if a.size == 0:
            return ''
        if a.shape[0] != 1:
            a = a.reshape(-1, order='F')
        return a.astype('<u2').tobytes().decode('utf-16-le', 'surrogatepass')

    def row_strs(self):
        """Each row of a char matrix as a str."""
        a = self.a
        if a.ndim > 2:
            a = a.reshape(a.shape[0], -1, order='F')
        return [r.astype('<u2').tobytes().decode('utf-16-le', 'surrogatepass') for r in a]

    @property
    def shape(self):
        return self.a.shape

    def __repr__(self):
        return f"Char({self.str()!r})"


class Str:
    """A string array: Python str elements in an object array; None is a
    missing string."""
    __slots__ = ('a', 'ro')

    def __init__(self, a, ro=False):
        self.a = a
        self.ro = ro

    @staticmethod
    def of(s):
        a = np.empty((1, 1), object)
        a[0, 0] = s
        return Str(a)

    @staticmethod
    def from_list(items, shape=None):
        a = np.empty(len(items), object)
        for i, s in enumerate(items):
            a[i] = s
        if shape is None:
            shape = (1, len(items))
        return Str(a.reshape(shape, order='F'))

    @property
    def shape(self):
        return self.a.shape

    def __repr__(self):
        return f"Str({self.a.tolist()!r})"


class Cell:
    """A cell array: any values in an object array."""
    __slots__ = ('a', 'ro')

    def __init__(self, a, ro=False):
        self.a = a
        self.ro = ro

    @staticmethod
    def empty(shape=(0, 0)):
        return Cell(np.empty(shape, object))

    @staticmethod
    def of_list(items, shape=None):
        a = np.empty(len(items), object)
        for i, v in enumerate(items):
            a[i] = v
        if shape is None:
            shape = (1, len(items))
        return Cell(a.reshape(shape, order='F'))

    @staticmethod
    def filled(shape):
        a = np.empty(shape, object)
        for i in range(a.size):
            a.flat[i] = EMPTY()
        return Cell(a)

    @property
    def shape(self):
        return self.a.shape

    def items(self):
        """The elements in column-major order."""
        return list(self.a.reshape(-1, order='F'))

    def __repr__(self):
        return f"Cell{self.a.shape}"


class Struct:
    """A struct array: one object array per field, all of the struct's
    shape; the dict keeps the fields in order."""
    __slots__ = ('shape', 'f', 'ro')

    def __init__(self, shape, f=None, ro=False):
        self.shape = tuple(shape)
        self.f = f if f is not None else {}
        self.ro = ro

    @staticmethod
    def scalar(d=None):
        s = Struct((1, 1))
        for k, v in (d or {}).items():
            a = np.empty((1, 1), object)
            a[0, 0] = v
            s.f[k] = a
        return s

    @staticmethod
    def empty(shape=(0, 0), keys=()):
        return Struct(shape, {k: np.empty(shape, object) for k in keys})

    @property
    def keys(self):
        return list(self.f)

    @property
    def size(self):
        n = 1
        for d in self.shape:
            n *= d
        return n

    def get1(self, name):
        """A field of a 1x1 struct."""
        return self.f[name].reshape(-1)[0]

    def elem(self, i):
        """Element i (column-major) as a dict."""
        return {k: a.reshape(-1, order='F')[i] for k, a in self.f.items()}

    def __repr__(self):
        return f"Struct{self.shape}{list(self.f)}"


FULL_LIMIT = 1 << 25          # elements a sparse matrix may have to be made full (256 MB of doubles)


class Sparse:
    """A sparse matrix, of class double (real or complex) or logical, always
    2-D: SciPy's CSC matrix (by columns, as the language stores them) of
    float64, complex128 or bool, holding no explicit zeros. It is never
    changed in place: operations and assignments make a new one, so it can
    be held in many places without copies."""
    __slots__ = ('m',)

    def __init__(self, m):
        self.m = m

    @property
    def shape(self):
        return self.m.shape

    @property
    def dtype(self):
        return self.m.dtype

    @property
    def cls(self):
        return 'logical' if self.m.dtype == np.bool_ else 'double'

    @property
    def nnz(self):
        return int(self.m.nnz)

    def dense(self):
        """The full matrix (an error past FULL_LIMIT elements)."""
        m, n = self.m.shape
        if m * n > FULL_LIMIT:
            raise MError('MATLAB:nomem', f'Out of memory: making the {m}\u00d7{n} sparse matrix full would need {m * n} elements. Work with it sparse.')
        return np.asarray(self.m.toarray(order='F'))

    def __array__(self, dtype=None, copy=None):
        # code written for full arrays (numpy.asarray of a value) reads it full
        a = self.dense()
        return a if dtype is None else a.astype(dtype)

    def __float__(self):
        if self.m.shape != (1, 1):
            raise TypeError('only a 1-by-1 sparse matrix converts to a number')
        return float(self.m[0, 0].real)

    def __repr__(self):
        return f'Sparse{self.m.shape}[{self.m.nnz}]'


class FH:
    """A function handle. Subclasses say what it calls; acall is a
    coroutine, as every compiled function is."""
    __slots__ = ()
    shape = (1, 1)


class Obj:
    """A value with properties, read and written by name: errors
    (MException), graphics objects, maps. Handle objects (graphics, maps)
    are never copied; value objects copy on write like the rest."""
    __slots__ = ()
    shape = (1, 1)
    is_handle = False
    cls = 'object'

    def getprop(self, name):
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")

    def setprop(self, name, value):
        raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class '{self.cls}'.")

    def propnames(self):
        return []


def EMPTY():
    """[]: the 0x0 double."""
    return np.zeros((0, 0))


def is_empty_double(v):
    return type(v) is np.ndarray and v.size == 0 and v.dtype == F64 and v.ndim == 2 and v.shape == (0, 0)


def shape_of(v):
    t = type(v)
    if t is float or t is bool or t is complex:
        return (1, 1)
    if t is np.ndarray:
        return v.shape
    if t is Char or t is Cell or t is Str:
        return v.a.shape
    if t is Struct:
        return v.shape
    if t is int:
        return (1, 1)
    sh = getattr(v, 'shape', None)
    if sh is not None:
        return sh
    return (1, 1)


def numel(v):
    t = type(v)
    if t is float or t is bool or t is complex:
        return 1
    if t is np.ndarray:
        return v.size
    if t is Char or t is Cell or t is Str:
        return v.a.size
    if t is Struct:
        return v.size
    sh = getattr(v, 'shape', (1, 1))
    n = 1
    for d in sh:
        n *= d
    return n


def class_of(v):
    t = type(v)
    if t is float or t is complex:
        return 'double'
    if t is bool:
        return 'logical'
    if t is np.ndarray:
        c = DTYPE_CLASS.get(v.dtype)
        if c is None:
            if v.dtype.kind == 'f':
                return 'double'
            if v.dtype.kind == 'c':
                return 'double'
            return 'double'
        return c
    if t is Char:
        return 'char'
    if t is Cell:
        return 'cell'
    if t is Struct:
        return 'struct'
    if t is Str:
        return 'string'
    if t is Sparse:
        return v.cls
    if isinstance(v, FH):
        return 'function_handle'
    if isinstance(v, Obj):
        return v.cls
    if t is int:
        return 'double'
    return 'double'


def is_numeric(v):
    """double, single or an integer class (not logical, not char)."""
    t = type(v)
    if t is float or t is complex:
        return True
    if t is np.ndarray:
        return v.dtype.kind in 'fciu'
    if t is Sparse:
        return v.m.dtype != np.bool_
    return False


def is_real(v):
    t = type(v)
    if t is complex:
        return False
    if t is np.ndarray:
        return v.dtype.kind != 'c'
    if t is Sparse:
        return v.m.dtype.kind != 'c'
    return True


CONTAINERS = (Char, Cell, Struct, Str)


def share(v):
    """Mark a value as held in more than one place: its next in-place
    change copies it first."""
    t = type(v)
    if t is np.ndarray:
        v.flags.writeable = False
    elif t is Char or t is Cell or t is Struct or t is Str:
        v.ro = True
    return v


def share_all(a):
    """Mark every value in an object array shared (they are now held by a
    second container too)."""
    for x in a.flat:
        t = type(x)
        if t is np.ndarray:
            x.flags.writeable = False
        elif t is Char or t is Cell or t is Struct or t is Str:
            x.ro = True


def is_shared(v):
    t = type(v)
    if t is np.ndarray:
        return not v.flags.writeable
    if t is Char or t is Cell or t is Struct or t is Str:
        return v.ro
    return False


def copy_container(v):
    """A writable shallow copy; the values inside are now held twice, so
    they are marked shared."""
    t = type(v)
    if t is Cell:
        a = v.a.copy()
        share_all(a)
        return Cell(a)
    if t is Struct:
        f = {}
        for k, a in v.f.items():
            a2 = a.copy()
            share_all(a2)
            f[k] = a2
        return Struct(v.shape, f)
    if t is Str:
        return Str(v.a.copy())
    if t is Char:
        return Char(v.a.copy())
    if t is np.ndarray:
        return v.copy()
    return v


def writable(v):
    """The value itself if nobody else holds it, else a copy to change."""
    t = type(v)
    if t is np.ndarray:
        return v if v.flags.writeable else v.copy()
    if t is Char or t is Cell or t is Struct or t is Str:
        return copy_container(v) if v.ro else v
    return v


def scalar_out(a):
    """Plain Python scalars for 1x1 double and logical results, the rest as
    they are."""
    if type(a) is np.ndarray and a.size == 1 and a.ndim <= 2:
        k = a.dtype.kind
        if k == 'f' and a.dtype == F64:
            return float(a.reshape(-1)[0])
        if k == 'b':
            return bool(a.reshape(-1)[0])
        if k == 'c' and a.dtype == C128:
            z = complex(a.reshape(-1)[0])
            return z
    return a


def to_array(v):
    """A numpy array of the value's numbers (2-D or more): char gives its
    codes, logical stays bool."""
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
    if t is Sparse:
        return v.dense()
    raise MError('MATLAB:invalidType', f"Expected a numeric value, not a value of class {class_of(v)}.")


def py_str(v, what='argument'):
    """A Python str from a char row vector or a string scalar."""
    t = type(v)
    if t is Char:
        return v.str()
    if t is Str:
        if v.a.size == 1:
            s = v.a.flat[0]
            return '' if s is None else s
        raise MError('MATLAB:invalidType', f"The {what} must be a string scalar or character vector.")
    if t is str:
        return v
    raise MError('MATLAB:invalidType', f"The {what} must be a string scalar or character vector.")


def is_text(v):
    t = type(v)
    return t is Char or (t is Str and v.a.size == 1)


def text_list(v):
    """Strings from a char row, a cellstr or a string array."""
    t = type(v)
    if t is Char:
        if v.a.shape[0] <= 1 or v.a.ndim > 2:
            return [v.str()]
        return v.row_strs()
    if t is Str:
        return ['' if s is None else s for s in v.a.reshape(-1, order='F')]
    if t is Cell:
        out = []
        for x in v.a.reshape(-1, order='F'):
            out.append(py_str(x))
        return out
    raise MError('MATLAB:invalidType', 'Expected text: a character vector, a cell array of character vectors, or a string array.')


def to_float(v, what='value'):
    """A Python float from a numeric (or logical, char) scalar."""
    t = type(v)
    if t is float:
        return v
    if t is bool or t is int:
        return float(v)
    if t is np.ndarray and v.size >= 1:
        x = v.reshape(-1)[0]
        if v.dtype.kind == 'c':
            return float(x.real)
        return float(x)
    if t is complex:
        return v.real
    if t is Char and v.a.size >= 1:
        return float(v.a.reshape(-1)[0])
    if t is Sparse and v.m.shape[0] * v.m.shape[1] >= 1:
        x = v.m[0, 0]
        return float(x.real) if v.m.dtype.kind == 'c' else float(x)
    raise MError('MATLAB:invalidType', f"Expected a numeric scalar for the {what}.")


def to_int(v, what='value'):
    x = to_float(v, what)
    if x != x or x in (float('inf'), float('-inf')):
        raise MError('MATLAB:invalidType', f"The {what} must be a finite integer.")
    i = int(x)
    if i != x:
        raise MError('MATLAB:invalidType', f"The {what} must be an integer.")
    return i


def size_str(shape):
    return '×'.join(str(d) for d in shape)
