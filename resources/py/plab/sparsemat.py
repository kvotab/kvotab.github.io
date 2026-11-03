"""Sparse matrices: the operators, indexing, concatenation and display of
values.Sparse, on SciPy's sparse matrices (CSC, by columns).

Which results stay sparse follows the language's rules: S + S, S - S,
S .* anything, S * S, S', S(i, j), [S F] and comparisons with S are sparse;
S + F, S * F and F \\ S are full. A part that would need a full matrix (an
operator without a sparse way here) is worked on full and given back sparse
when the rule says so, so the numbers are always those of the full
arrays."""
import math

import numpy as np

from .values import (MError, Sparse, Char, Cell, Str, Struct, FH, Obj, NOVAL, COLON, F64, C128, class_of, shape_of,
                     numel, to_array, FULL_LIMIT)


def S():
    import scipy.sparse as sp
    return sp


def make(m, logical=None):
    """A Sparse from a SciPy sparse matrix or a full array: CSC, float64,
    complex128 or bool, no explicit zeros, indices sorted; complex values
    with no imaginary part become real (as full results do)."""
    sp = S()
    if not sp.issparse(m):
        a = np.asarray(m)
        if a.ndim != 2:
            raise MError('MATLAB:sparse:NDArray', 'Sparse matrices are 2-D: an N-D array cannot be made sparse.')
        m = sp.csc_matrix(a)
    else:
        m = m.tocsc(copy=True)
    if logical is None:
        logical = m.dtype == np.bool_
    if logical:
        m = m.astype(np.bool_)
    elif m.dtype.kind == 'c':
        m = m.astype(C128)
        if m.nnz == 0 or not np.any(m.data.imag):
            m = m.real.astype(F64).tocsc()
    else:
        m = m.astype(F64)
    m.eliminate_zeros()
    m.sort_indices()
    return Sparse(m)


def zeros(r, c, logical=False):
    return Sparse(S().csc_matrix((int(r), int(c)), dtype=np.bool_ if logical else F64))


def to_sparse(v, what='value'):
    """A value as a Sparse: sparse already, or a full double, logical or char
    array (2-D); single and integers are not made sparse."""
    t = type(v)
    if t is Sparse:
        return v
    c = class_of(v)
    if c not in ('double', 'logical', 'char'):
        raise MError('MATLAB:sparse:InvalidClass', f'Sparse matrices are double or logical: a {c} value cannot be made sparse.')
    a = to_array(v)
    if a.ndim > 2:
        raise MError('MATLAB:sparse:NDArray', 'Sparse matrices are 2-D: an N-D array cannot be made sparse.')
    if t is Char:
        a = a.astype(F64)
    return make(a, logical=a.dtype == np.bool_)


def full(v):
    """The numbers of a value, full."""
    if type(v) is Sparse:
        return v.dense()
    return to_array(v)


def _value(a):
    """A full numpy result as the language's value."""
    from .ops import finish
    a = np.asarray(a)
    if a.dtype == np.bool_:
        return finish(a, 'logical')
    return finish(a, 'double')


def _check_class(v, sym):
    c = class_of(v)
    if c not in ('double', 'logical', 'char'):
        raise MError('MATLAB:sparse:mixedClasses', f"Operator '{sym}' is not supported for a sparse matrix and a {c} value: sparse matrices work with double, logical and char values.")


def _scalar(v):
    """The number of a 1x1 value (full or sparse), or None."""
    if numel(v) != 1:
        return None
    if type(v) is Sparse:
        x = v.m[0, 0]
        return complex(x) if v.m.dtype.kind == 'c' else float(x)
    a = to_array(v)
    x = a.reshape(-1)[0]
    return complex(x) if a.dtype.kind == 'c' else float(x)


# ---- element-wise operators ----------------------------------------------------------------------------

_SPARSE_RESULT = {
    '+': lambda sa, sb: sa and sb, '-': lambda sa, sb: sa and sb,
    '.*': lambda sa, sb: True, './': lambda sa, sb: sa, '.\\': lambda sa, sb: sb, '.^': lambda sa, sb: sa,
    '==': lambda sa, sb: True, '~=': lambda sa, sb: True, '<': lambda sa, sb: True, '<=': lambda sa, sb: True,
    '>': lambda sa, sb: True, '>=': lambda sa, sb: True, '&': lambda sa, sb: True, '|': lambda sa, sb: True,
    'xor': lambda sa, sb: True,
}

_CMP = {'==': np.equal, '~=': np.not_equal, '<': np.less, '<=': np.less_equal, '>': np.greater, '>=': np.greater_equal}


def _dense_op(sym, a, b):
    from . import ops as O
    fn = {'+': O.plus, '-': O.minus, '.*': O.times, './': O.rdivide, '.\\': O.ldivide, '.^': O.power,
          '==': O.eq, '~=': O.ne, '<': O.lt, '<=': O.le, '>': O.gt, '>=': O.ge, '&': O.and_, '|': O.or_, 'xor': O.xor}[sym]
    fa = full(a) if type(a) is Sparse else a
    fb = full(b) if type(b) is Sparse else b
    if type(fa) is np.ndarray:
        fa = _value(fa)
    if type(fb) is np.ndarray:
        fb = _value(fb)
    return fn(fa, fb)


def binop(sym, a, b):
    """An element-wise or matrix operator with a sparse operand."""
    if sym == '*':
        return mtimes(a, b)
    if sym == '\\':
        return mldivide(a, b)
    if sym == '/':
        return mrdivide(a, b)
    if sym == '^':
        return mpower(a, b)
    _check_class(a, sym)
    _check_class(b, sym)
    sa, sb = type(a) is Sparse, type(b) is Sparse
    sha, shb = shape_of(a), shape_of(b)
    same = sha == shb
    xa, xb = _scalar(a), _scalar(b)
    # ways that keep the work sparse
    if same and sa and sb:
        A, B = a.m, b.m
        if sym in ('+', '-'):
            A = A.astype(F64) if A.dtype == np.bool_ else A
            B = B.astype(F64) if B.dtype == np.bool_ else B
            return make(A + B if sym == '+' else A - B)
        if sym == '.*':
            return make(A.astype(F64).multiply(B.astype(F64)) if A.dtype.kind != 'c' and B.dtype.kind != 'c' else A.multiply(B))
        if sym == '&':
            return make(A.astype(np.bool_).multiply(B.astype(np.bool_)), logical=True)
        if sym == '|':
            return make(A.astype(np.bool_).maximum(B.astype(np.bool_)), logical=True)
    if sym == '.*' and (sa or sb):
        s, other, x = (a, b, xb) if sa else (b, a, xa)
        if x is not None and (x == x) and abs(x) != math.inf:
            return make(s.m.astype(C128 if isinstance(x, complex) else (s.m.dtype if s.m.dtype != np.bool_ else F64)) * x)
        if same and type(other) is not Sparse:
            o = full(other)
            if np.all(np.isfinite(o)):
                return make(s.m.multiply(o.astype(F64) if o.dtype == np.bool_ else o))
    if sym == './' and sa and xb is not None and xb != 0 and xb == xb and abs(xb) != math.inf:
        return make(a.m.astype(C128 if isinstance(xb, complex) else (a.m.dtype if a.m.dtype != np.bool_ else F64)) / xb)
    if sym == '.^' and sa and xb is not None and not isinstance(xb, complex) and xb > 0:
        return make(a.m.astype(a.m.dtype if a.m.dtype != np.bool_ else F64).power(xb))
    if sym in _CMP and (sa or sb):
        s, x, flip = (a, xb, False) if sa else (b, xa, True)
        if x is not None and not isinstance(x, complex) and s.m.dtype.kind != 'c':
            op = _CMP[sym]
            zero_true = bool(op(x, 0.0)) if flip else bool(op(0.0, x))
            if not zero_true:
                m = s.m.copy()
                m.data = op(x, m.data) if flip else op(m.data, x)
                return make(m, logical=True)
    if sym in ('&', '|') and (sa or sb):
        s, x = (a, xb) if sa else (b, xa)
        if x is not None:
            if sym == '&':
                return make(s.m.astype(np.bool_), logical=True) if x != 0 else zeros(*s.shape, logical=True)
            if x == 0:
                return make(s.m.astype(np.bool_), logical=True)
    # otherwise the full operator, the result stored as the rule says
    r = _dense_op(sym, a, b)
    if _SPARSE_RESULT[sym](sa, sb):
        return make(to_array(r), logical=class_of(r) == 'logical')
    return r


def unop(sym, a):
    m = a.m
    if sym == '-':
        return make(-(m.astype(F64) if m.dtype == np.bool_ else m))
    if sym == '+':
        return make(m.astype(F64)) if m.dtype == np.bool_ else a
    if sym == ".'":
        return make(m.T)
    if sym == "'":
        return make(m.conj().T if m.dtype.kind == 'c' else m.T)
    if sym == '~':
        return make(a.dense() == 0, logical=True)
    raise MError('MATLAB:UndefinedFunction', f"Operator '{sym}' is not supported for sparse matrices.")


def truth(v):
    """if S: true when S is not empty and has no zero."""
    r, c = v.shape
    return r * c > 0 and v.nnz == r * c


# ---- matrix operators --------------------------------------------------------------------------------------

def _mat(v):
    """A 2-D full array of a value (for the full side of a matrix operator)."""
    a = full(v)
    if a.ndim != 2:
        raise MError('MATLAB:mtimes:inputsMustBe2D', 'Arguments must be 2-D, or at least one argument must be scalar. Use TIMES (.*) for elementwise multiplication.')
    return a.astype(F64) if a.dtype.kind in 'bu' or a.dtype == np.bool_ else a


def mtimes(a, b):
    _check_class(a, '*')
    _check_class(b, '*')
    if numel(a) == 1 or numel(b) == 1:
        return binop('.*', a, b)
    sa, sb = type(a) is Sparse, type(b) is Sparse
    ra, ca = shape_of(a)
    rb, cb = shape_of(b)
    if ca != rb:
        raise MError('MATLAB:innerdim', 'Incorrect dimensions for matrix multiplication. Check that the number of columns in the first matrix matches the number of rows in the second matrix. To operate on each element of the matrix individually, use TIMES (.*) for elementwise multiplication.')
    if sa and sb:
        A = a.m.astype(F64) if a.m.dtype == np.bool_ else a.m
        B = b.m.astype(F64) if b.m.dtype == np.bool_ else b.m
        return make(A @ B)
    if sa:
        A = a.m.astype(F64) if a.m.dtype == np.bool_ else a.m
        return _value(np.asarray(A @ _mat(b)))
    B = b.m.astype(F64) if b.m.dtype == np.bool_ else b.m
    return _value(np.asarray((B.T @ _mat(a).T).T))


def _warn(ident, msg):
    from . import runtime as R
    R.warn(ident, msg)


def mldivide(a, b):
    """A \\ B: a sparse square A by SuperLU (scipy.sparse.linalg.splu), a
    rectangular one or a full one as the full operator (a rectangular one
    too large for that by its augmented system); sparse when both are
    sparse."""
    from . import ops as O
    _check_class(a, '\\')
    _check_class(b, '\\')
    if numel(a) == 1:
        return binop('.\\', a, b)
    sa, sb = type(a) is Sparse, type(b) is Sparse
    ra, ca = shape_of(a)
    rb = shape_of(b)[0]
    if ra != rb:
        raise MError('MATLAB:dimagree', 'Matrix dimensions must agree.')
    if sa and ra == ca:
        import scipy.sparse.linalg as SL
        A = a.m.astype(F64) if a.m.dtype == np.bool_ else a.m
        B = full(b)
        B = B.astype(np.result_type(B.dtype, A.dtype, F64))
        if A.dtype.kind == 'c' and B.dtype.kind != 'c':
            B = B.astype(C128)
        if A.dtype.kind != 'c' and B.dtype.kind == 'c':
            A = A.astype(C128)
        try:
            lu = SL.splu(A.tocsc())
            x = lu.solve(B if B.ndim == 2 else B.reshape(-1, 1))
            if not np.all(np.isfinite(x)) and np.all(np.isfinite(B)):
                raise RuntimeError('singular')
        except RuntimeError:
            _warn('MATLAB:singularMatrix', 'Matrix is singular to working precision.')
            with np.errstate(all='ignore'):
                x = np.asarray(O.mldivide(_value(A.toarray()), _value(B)))
        x = np.asarray(x).reshape(ca, -1)
        return make(x) if sb else _value(x)
    if sa and ra * ca > FULL_LIMIT:
        # least squares too large to make full: SuperLU on the augmented system [c*I A; A' 0] [r/c; x] = [b; 0]
        import scipy.sparse as sp
        import scipy.sparse.linalg as SL
        A = a.m.astype(F64) if a.m.dtype == np.bool_ else a.m
        B = full(b)
        B = B.reshape(rb, -1).astype(np.result_type(B.dtype, A.dtype, F64))
        c = float(abs(A).max()) / 1000 if A.nnz else 1.0
        K = sp.bmat([[c * sp.identity(ra), A], [A.conj().T, None]], format='csc')
        try:
            y = SL.splu(K).solve(np.vstack([B, np.zeros((ca, B.shape[1]), B.dtype)]))
        except RuntimeError:
            raise MError('MATLAB:rankDeficientMatrix', 'The sparse matrix is rank deficient: its least-squares solution is not unique.')
        x = y[ra:].reshape(ca, -1)
        return make(x) if sb else _value(x)
    r = O.mldivide(_value(full(a)) if sa else a, _value(full(b)) if sb else b)
    return make(to_array(r)) if (sa and sb) else r


def mrdivide(a, b):
    if numel(b) == 1:
        return binop('./', a, b)
    from .ops import transpose
    return transpose(mldivide(transpose(b), transpose(a)))


def mpower(a, b):
    from . import ops as O
    x = _scalar(b)
    if type(a) is Sparse and type(b) is not Sparse and x is not None and not isinstance(x, complex) and x == int(x) and math.isfinite(x):
        r, c = a.shape
        if r != c:
            raise MError('MATLAB:mpower:notSquare', 'Inputs must be a scalar and a square matrix. To operate on each element of the matrix individually, use POWER (.^) for elementwise power.')
        k = int(x)
        res = S().identity(r, dtype=F64, format='csc')
        base = a.m.astype(F64) if a.m.dtype == np.bool_ else a.m
        if k < 0 and r:
            # S^-k = inv(S)^k: SuperLU's factors solve for the identity
            import scipy.sparse.linalg as SL
            k = -k
            try:
                base = SL.splu(base.tocsc()).solve(np.eye(r, dtype=C128 if base.dtype.kind == 'c' else F64))
                if not np.all(np.isfinite(base)):
                    raise RuntimeError('singular')
            except RuntimeError:
                _warn('MATLAB:singularMatrix', 'Matrix is singular to working precision.')
                return make(np.full((r, r), np.inf))
            base = S().csc_matrix(base)
        k = abs(k)
        while k:
            if k & 1:
                res = res @ base
            k >>= 1
            if k:
                base = base @ base
        return make(res)
    r = O.mpower(_value(full(a)) if type(a) is Sparse else a, _value(full(b)) if type(b) is Sparse else b)
    return make(to_array(r)) if type(a) is Sparse else r


# ---- indexing ----------------------------------------------------------------------------------------------

def idx(A, args):
    """A(args): a part of a sparse matrix, sparse (even one element)."""
    from .index import conv, _exceeds, _exceeds_pos, _lin_shape
    m = A.m
    r, c = m.shape
    n = len(args)
    if n == 0:
        return A
    if n == 1:
        ix, ish, cover = conv(args[0])
        if ix is COLON:
            return make(m.reshape((r * c, 1), order='F'))
        if ix.size and ix.max() >= r * c:
            raise _exceeds(r * c)
        p, q = _lin_shape((r, c), ish, ix.size)
        if ix.size == 0:
            return zeros(p, q, logical=m.dtype == np.bool_)
        vals = np.asarray(m[ix % r, ix // r]).reshape(-1)
        k = np.arange(ix.size)
        nz = vals != 0
        out = S().csc_matrix((vals[nz], (k[nz] % p, k[nz] // p)), shape=(p, q), dtype=m.dtype)
        return make(out)
    subs = [conv(a)[0] for a in args]
    for k in range(2, n):
        s = subs[k]
        if s is not COLON and (s.size == 0 or np.any(s != 0)):
            if s.size and s.max() > 0:
                raise _exceeds_pos(k + 1, 1)
    I, J = subs[0], subs[1]
    if n > 2 and any(s is not COLON and s.size == 0 for s in subs[2:]):
        return zeros(r if I is COLON else I.size, 0, logical=m.dtype == np.bool_)
    if I is not COLON and I.size and I.max() >= r:
        raise _exceeds_pos(1, r)
    if J is not COLON and J.size and J.max() >= c:
        raise _exceeds_pos(2, c)
    part = m if J is COLON else m[:, J]
    part = part if I is COLON else part.tocsr()[I, :]
    return make(part)


def _grow_to(m, r, c):
    """m (LIL) made r-by-c, keeping what it holds."""
    if (r, c) != m.shape:
        m = m.copy()
        m.resize((r, c))
    return m


def asgn(A, args, V):
    """A(args) = V where A or V is sparse: a sparse A stays sparse (V made
    sparse, logical A turned double for a double V); a full A takes V full."""
    from .index import conv
    if type(A) is not Sparse:
        if A is NOVAL or (type(A) is np.ndarray and A.size == 0 and A.shape == (0, 0)):
            A = zeros(0, 0, logical=class_of(V) == 'logical')
        else:
            from .index import asgn as full_asgn
            return full_asgn(A, args, _value(full(V)) if type(V) is Sparse else V)
    c_v = class_of(V)
    if c_v not in ('double', 'logical', 'char'):
        raise MError('MATLAB:sparse:InvalidClass', f'Sparse matrices are double or logical: a {c_v} value cannot be put in one.')
    logical = A.m.dtype == np.bool_ and c_v == 'logical'
    vals = full(V)
    if vals.dtype.kind not in 'fcb':
        vals = vals.astype(F64)
    r, c = A.shape
    m = A.m.tolil(copy=True)
    if not logical and m.dtype == np.bool_:
        m = m.astype(F64)
    if vals.dtype.kind == 'c' and m.dtype.kind != 'c':
        m = m.astype(C128)
    n = len(args)
    if n == 1:
        ix, ish, cover = conv(args[0])
        if ix is COLON:
            ix = np.arange(r * c)
        need = int(ix.max()) + 1 if ix.size else 0
        if need > r * c:
            if r == 0 and c == 0:
                m = _grow_to(m, 1, need)
                r, c = 1, need
            elif r == 1:
                m = _grow_to(m, 1, need)
                c = need
            elif c == 1:
                m = _grow_to(m, need, 1)
                r = need
            else:
                raise MError('MATLAB:indexed:growAmbiguous', 'Attempt to grow array along ambiguous dimension.')
        rows, cols = ix % r, ix // r
        flat = vals.reshape(-1, order='F')
        if flat.size == 1:
            flat = np.repeat(flat, ix.size)
        elif flat.size != ix.size:
            raise MError('MATLAB:subsassignnumelmismatch', 'Unable to perform assignment because the left and right sides have a different number of elements.')
        if ix.size:
            m[rows, cols] = flat.astype(m.dtype)
        return make(m.tocsc(), logical=logical)
    subs = [conv(a)[0] for a in args]
    for s in subs[2:]:
        if s is not COLON and np.any(s != 0):
            raise MError('MATLAB:sparse:NDAssign', 'Sparse matrices are 2-D: an index past the second dimension must be 1.')
    I, J = subs[0], subs[1]
    I = np.arange(r) if I is COLON else I
    J = np.arange(c) if J is COLON else J
    nr = max(r, int(I.max()) + 1 if I.size else 0)
    nc = max(c, int(J.max()) + 1 if J.size else 0)
    m = _grow_to(m, nr, nc)
    if I.size and J.size:
        if vals.size == 1:
            block = np.full((I.size, J.size), vals.reshape(-1)[0])
        elif vals.size == I.size * J.size:
            block = vals.reshape(I.size, J.size, order='F') if vals.shape != (I.size, J.size) else vals
        else:
            raise MError('MATLAB:subsassigndimmismatch', f'Unable to perform assignment because the size of the left side is {I.size}-by-{J.size} and the size of the right side is {"-by-".join(str(d) for d in vals.shape)}.')
        m[np.ix_(I, J)] = block.astype(m.dtype)
    return make(m.tocsc(), logical=logical)


def delete(A, args):
    """A(args) = [] for a sparse A: rows, columns, or elements of a vector."""
    from .index import conv
    r, c = A.shape
    n = len(args)
    if n == 1:
        ix, _, _ = conv(args[0])
        if ix is COLON:
            return zeros(0, 0, logical=A.m.dtype == np.bool_)
        keep = np.ones(r * c, bool)
        keep[ix] = False
        if r == 1 or c == 1:
            col = A.m.reshape((r * c, 1), order='F').tocsr()[np.flatnonzero(keep), :]
            return make(col.T if r == 1 else col)
        if keep.all():
            return A
        raise MError('MATLAB:subsdeldimmismatch', 'A null assignment can have only one non-colon index.')
    I, J = conv(args[0])[0], conv(args[1])[0]
    if I is COLON:
        keep = np.ones(c, bool)
        keep[J] = False
        return make(A.m[:, np.flatnonzero(keep)])
    if J is COLON:
        keep = np.ones(r, bool)
        keep[I] = False
        return make(A.m.tocsr()[np.flatnonzero(keep), :])
    if set(I.tolist()) == set(range(r)):
        keep = np.ones(c, bool)
        keep[J] = False
        return make(A.m[:, np.flatnonzero(keep)])
    if set(J.tolist()) == set(range(c)):
        keep = np.ones(r, bool)
        keep[I] = False
        return make(A.m.tocsr()[np.flatnonzero(keep), :])
    raise MError('MATLAB:subsdeldimmismatch', 'A null assignment can have only one non-colon index.')


# ---- concatenation, loops ---------------------------------------------------------------------------------

def cat(axis, vals):
    """[A, B] and [A; B] with a sparse part: sparse, double unless every part
    is logical."""
    parts = []
    for v in vals:
        if type(v) is np.ndarray and v.shape == (0, 0):
            continue
        if type(v) in (Cell, Struct, Str) or isinstance(v, (FH, Obj)):
            raise MError('MATLAB:sparse:CatClass', f'A {class_of(v)} value cannot be concatenated with a sparse matrix.')
        parts.append(to_sparse(v))
    if not parts:
        return zeros(0, 0)
    if axis > 1:
        raise MError('MATLAB:sparse:NDArray', 'Sparse matrices are 2-D: they cannot be concatenated along a third dimension.')
    logical = all(p.m.dtype == np.bool_ for p in parts)
    sizes = [p.shape[1 - axis] for p in parts if p.shape[0] * p.shape[1] > 0 or p.shape[1 - axis] > 0]
    if len(set(sizes)) > 1:
        raise MError('MATLAB:catenate:dimensionMismatch', 'Dimensions of arrays being concatenated are not consistent.')
    mats = [p.m if logical else p.m.astype(C128 if p.m.dtype.kind == 'c' else F64) for p in parts]
    sp = S()
    r = sp.hstack(mats, format='csc') if axis == 1 else sp.vstack(mats, format='csc')
    return make(r, logical=logical)


def columns(v):
    """A for loop over a sparse matrix: its columns, sparse."""
    return [make(v.m[:, j]) for j in range(v.shape[1])]


# ---- display -----------------------------------------------------------------------------------------------

def _entry_lines(v):
    """'(i,j)   value' lines, the values formatted together as a column."""
    from .display import matrix2d_lines
    m = v.m.tocoo()
    order = np.lexsort((m.row, m.col))
    rows, cols, data = m.row[order] + 1, m.col[order] + 1, m.data[order]
    if v.m.dtype == np.bool_:
        vlines = ['     1'] * data.size
        head = []
    else:
        col = data.reshape(-1, 1)
        lines = matrix2d_lines(col if col.dtype.kind == 'c' else col.astype(F64))
        lines = [l for l in lines if l.strip() != '']
        head = lines[:len(lines) - data.size]
        vlines = lines[len(lines) - data.size:]
    wr = len(str(int(rows.max()))) if rows.size else 1
    wc = len(str(int(cols.max()))) if cols.size else 1
    out = list(head)
    for i, j, s in zip(rows, cols, vlines):
        out.append(f'   ({i:>{wr}d},{j:d})' + ' ' * (wc - len(str(j))) + '  ' + s.rstrip())
    return out


def header(v):
    r, c = v.shape
    kind = 'logical' if v.m.dtype == np.bool_ else 'double'
    nz = v.nnz
    return f'  {r}×{c} sparse {kind} matrix ({nz} nonzero{"" if nz == 1 else "s"})'


def display(name, v):
    from .display import FMT
    loose = FMT['spacing'] == 'loose'
    out = [f'{name} =']
    if loose:
        out.append('')
    if v.nnz == 0:
        r, c = v.shape
        out.append(f'   All zero sparse: {r}×{c}')
    else:
        out.append(header(v))
        if loose:
            out.append('')
        out += _entry_lines(v)
    if loose:
        out.append('')
    return '\n'.join(out) + '\n'


def disp_text(v):
    if v.nnz == 0:
        r, c = v.shape
        return f'   All zero sparse: {r}×{c}\n'
    return '\n'.join(_entry_lines(v)) + '\n'
